"""Tagged online snapshot lifecycle regressions, without game/emulator dependencies."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_paths
import kit_transfer as transfer
import kit_wire


def digest(value):
    return hashlib.sha256(value).hexdigest()


class Channel:
    def __init__(self):
        self.closed, self.transfers = False, 0
        self.messages, self.chunks = [], []
    def send_json(self, **message): self.messages.append(message)
    def try_send(self, **message): self.messages.append(message)
    def send_transfer_chunk(self, token, offset, data): self.chunks.append((token, offset, data))


class Peer(transfer.TransferMixin):
    def __init__(self, root, role='guest'):
        self.init_transfers()
        self.role, self.phase, self.quit = role, 'sending', False
        self.local, self.members = {}, {}
        self.net = dict(channel=Channel()) if role == 'guest' else None
        self.states = Path(root) / 'states'
        self.args = SimpleNamespace(send_rate=0)
        self.match = None
        self.sent, self.jobs, self.notes, self.failures = [], [], [], []
        self.verified_results = []
        self.progress, self.dirty = {}, False
    def send(self, **message): self.sent.append(message)
    def send_to(self, ident, **message): self.sent.append(dict(ident=ident, **message))
    def say(self, message): self.notes.append(message)
    def job(self, name, function, *args, then=None, fail=None):
        self.jobs.append((name, function, args, then, fail))
    def verify_failed(self, error): self.failures.append(error)
    def verify_file(self, path, owner): return dict(path=path, owner=owner)
    def verified(self, value): self.verified_results.append(value)
    def _prefetch_meta_current(self, meta): return True
    def run_job(self, index=0):
        _, function, args, then, fail = self.jobs.pop(index)
        try:
            result = function(*args)
        except Exception as error:
            if fail: fail(error)
            else: raise
        else:
            if then: then(result)


class Protocol(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.guest = Peer(self.root / 'guest')
        self.host = Peer(self.root / 'host', 'host')
        self.channel = Channel()
        self.host.members[2] = dict(channel=self.channel)
        self.archive = b'authoritative original snapshot'
        self.compact = b'compact representation'
        self.source = self.root / 'original.p2s'; self.source.write_bytes(self.archive)
        self.wire = self.root / 'compact.wire'; self.wire.write_bytes(self.compact)
        self.meta = dict(state=str(self.source), state_sha256=digest(self.archive), size=len(self.archive),
                         spec_sha=digest(b'spec'), wire=dict(codec=kit_wire.CODEC, path=str(self.wire),
                         sha256=digest(self.compact), size=len(self.compact), iso_sha256=digest(b'iso')))
        self.owner = dict(sha=self.meta['state_sha256'], size=self.meta['size'], spec_sha=self.meta['spec_sha'], epoch=7)
        self.guest.match = self.owner
        self.host.match = dict(self.owner)
        manager = SimpleNamespace(compatible=lambda remote: True)
        self.host.local['wire'] = manager
        self.host.members[2]['wire'] = dict(codec=kit_wire.CODEC)
        self.d = self.host.make_transfer(2, self.meta, 'match', epoch=7)
        self.addCleanup(self.guest.cancel_transfers)
        self.addCleanup(self.host.cancel_transfers)

    def begin(self, descriptor=None, purpose='match', owner=None):
        descriptor = descriptor or self.d
        self.assertTrue(self.guest.begin_transfer(descriptor, purpose,
                                                 owner or (self.owner if purpose == 'match' else None)))
        return self.guest.transfer_receives[purpose]

    def chunk(self, descriptor, data, offset=0, ident=1):
        self.guest.on_transfer_chunk(ident, transfer.TAG.pack(bytes.fromhex(descriptor['token']), offset) + data)

    def complete(self, descriptor, data):
        self.chunk(descriptor, data)
        self.guest.msg_TRANSFER_END(1, dict(token=descriptor['token'], sha256=descriptor['sha256']))

    def test_descriptor_rejects_bool_sizes_unbounded_sizes_and_unknown_codec(self):
        self.assertTrue(transfer.valid_descriptor(self.d))
        for changed in (dict(size=True), dict(size=kit_wire.MAX_WIRE + 1), dict(codec='unknown'),
                        dict(epoch=-1), dict(iso_sha256='bad'), dict(unexpected=1)):
            self.assertFalse(transfer.valid_descriptor(dict(self.d, **changed)))

    def test_match_receiver_refuses_changed_epoch_spec_and_owner(self):
        for changed in (dict(epoch=8), dict(spec_sha=digest(b'other')), dict(archive_sha256=digest(b'other'))):
            self.assertFalse(self.guest.begin_transfer(dict(self.d, **changed), 'match', self.owner))
        self.assertFalse(self.guest.begin_transfer(self.d, 'match', dict(self.owner)))
        self.assertEqual(self.guest.transfer_receives, {})
        self.assertEqual(self.guest.sent, [])

    def test_wrong_peer_token_and_replaced_channel_cannot_feed_receiver(self):
        record = self.begin()
        self.chunk(self.d, b'first', ident=2)
        self.chunk(dict(self.d, token='00' * 16), b'first')
        self.assertEqual(record['got'], 0)
        self.guest.net['channel'] = Channel()
        self.chunk(self.d, b'first')
        self.assertEqual(record['got'], 0)
        self.assertEqual(self.guest.jobs, [])

    def test_canceled_token_cannot_feed_next_match_or_leave_partial_file(self):
        record = self.begin()
        self.chunk(self.d, self.compact[:4])
        path = record['part']
        self.guest.cancel_transfers()
        self.assertFalse(path.exists())
        self.guest.match = dict(self.owner, epoch=8)
        new = dict(self.d, token='33' * 16, epoch=8)
        current = self.begin(new, owner=self.guest.match)
        self.chunk(self.d, self.compact[4:], offset=4)
        self.assertEqual(current['got'], 0)
        self.assertEqual(self.guest.jobs, [])

    def test_promoted_prefetch_keeps_received_prefix_and_requests_remaining_offset(self):
        self.guest.phase = 'lobby'
        prefetch = dict(self.d, epoch=0)
        record = self.begin(prefetch, 'prefetch')
        self.chunk(prefetch, self.compact[:5])
        self.guest.phase = 'sending'
        self.assertTrue(self.guest.promote_transfer(self.d, self.owner))
        self.assertIs(self.guest.transfer_receives['match'], record)
        self.assertEqual(record['got'], 5)
        self.assertTrue(self.guest.begin_transfer(self.d, 'match', self.owner))
        self.assertEqual(self.guest.sent[-1]['offset'], 5)
        self.chunk(self.d, self.compact[5:], offset=5)
        self.assertEqual(record['got'], len(self.compact))

    def test_replaced_channel_cannot_promote_old_prefetch(self):
        self.guest.phase = 'lobby'
        record = self.begin(dict(self.d, epoch=0), 'prefetch')
        self.guest.net['channel'] = Channel()
        self.guest.phase = 'sending'
        self.assertFalse(self.guest.promote_transfer(self.d, self.owner))
        self.assertNotIn('match', self.guest.transfer_receives)
        self.assertEqual(record['got'], 0)

    def test_changed_owner_or_epoch_cannot_promote_prefetch(self):
        self.guest.phase = 'lobby'
        self.begin(dict(self.d, epoch=0), 'prefetch')
        self.guest.phase = 'sending'
        self.assertFalse(self.guest.promote_transfer(self.d, dict(self.owner)))
        self.assertFalse(self.guest.promote_transfer(dict(self.d, epoch=8), self.owner))
        self.assertIn('prefetch', self.guest.transfer_receives)
        self.assertNotIn('match', self.guest.transfer_receives)

    def test_bad_offset_requests_original_archive_once_and_closes_part(self):
        record = self.begin()
        self.chunk(self.d, b'bad', offset=4)
        self.assertFalse(record['part'].exists())
        self.assertIsNone(record['file'])
        self.assertEqual([row['type'] for row in self.guest.sent], ['TRANSFER_WANT', 'TRANSFER_FALLBACK'])
        self.chunk(self.d, b'late', offset=0)
        self.guest.msg_TRANSFER_END(1, dict(token=self.d['token'], sha256=self.d['sha256']))
        self.assertEqual(len(self.guest.sent), 2)
        self.assertEqual(self.guest.jobs, [])

    def test_corrupt_same_size_payload_cannot_reach_verifier(self):
        self.begin()
        self.complete(self.d, b'x' * len(self.compact))
        self.assertEqual(self.guest.jobs, [])
        self.assertEqual(self.guest.sent[-1]['type'], 'TRANSFER_FALLBACK')
        self.assertNotIn('state', self.owner)

    def test_fallback_offer_must_match_pending_identity_epoch_and_channel(self):
        record = self.begin()
        self.chunk(self.d, b'bad', offset=3)
        self.host.msg_TRANSFER_FALLBACK(2, self.guest.sent[-1])
        offered = self.host.sent[-1]
        replacement = offered['transfer']
        self.assertEqual(replacement['codec'], 'archive')
        self.guest.msg_TRANSFER_OFFER(1, dict(offered, transfer=dict(replacement, epoch=8)))
        self.assertNotIn('match', self.guest.transfer_receives)
        self.guest.msg_TRANSFER_OFFER(1, offered)
        self.assertEqual(self.guest.transfer_receives['match']['descriptor'], replacement)
        self.assertNotEqual(record['descriptor']['token'], replacement['token'])
        self.assertNotIn('match', self.guest.transfer_fallback)
        self.guest.msg_TRANSFER_OFFER(1, offered)
        self.assertEqual(len([row for row in self.guest.sent if row['type'] == 'TRANSFER_WANT']), 2)

    def test_unsolicited_archive_offer_cannot_allocate_receiver(self):
        self.host.msg_TRANSFER_FALLBACK(2, dict(token=self.d['token'], archive_sha256=self.d['archive_sha256'], epoch=7))
        self.guest.msg_TRANSFER_OFFER(1, self.host.sent[-1])
        self.assertEqual(self.guest.transfer_receives, {})
        self.assertEqual(self.guest.sent, [])

    def test_host_repeated_fallback_reuses_single_original_offer(self):
        message = dict(token=self.d['token'], archive_sha256=self.d['archive_sha256'], epoch=7)
        self.host.msg_TRANSFER_FALLBACK(2, message)
        descriptor = self.host.sent[-1]['transfer']
        self.host.msg_TRANSFER_FALLBACK(2, message)
        self.host.msg_TRANSFER_FALLBACK(2, dict(message, token=descriptor['token']))
        self.assertEqual(len(self.host.sent), 1)
        self.assertEqual(self.host.transfer_offers[(2, 'match')]['descriptor'], descriptor)

    def test_stale_decode_callback_keeps_cache_but_cannot_load_or_verify_new_match(self):
        self.begin()
        self.complete(self.d, self.compact)
        job = self.guest.jobs.pop()
        self.guest.cancel_transfers()
        self.guest.match = dict(self.owner, epoch=8)
        cached = self.root / 'cached.p2s'
        cached.write_bytes(self.archive)
        job[3](str(cached))
        self.assertNotIn('state', self.guest.match)
        self.assertEqual(self.guest.jobs, [])
        self.assertEqual(self.guest.verified_results, [])
        self.assertEqual(cached.read_bytes(), self.archive)

    def test_compact_manager_receives_exact_wire_identity_before_verify(self):
        calls = []
        def restore(descriptor, part, target):
            calls.append((descriptor, part.read_bytes()))
            if digest(part.read_bytes()) != descriptor['sha256']:
                raise ValueError('Wire identity differs')
            target.write_bytes(self.archive)
            return str(target)
        self.guest.local['wire'] = SimpleNamespace(restore=restore)
        record = self.begin()
        self.complete(self.d, self.compact)
        self.guest.run_job()
        self.assertEqual(calls, [(self.d, self.compact)])
        self.assertFalse(record['part'].exists())
        self.assertEqual(record['target'].read_bytes(), self.archive)
        self.assertEqual(self.guest.jobs[0][0], 'verify')
        self.guest.run_job()
        self.assertEqual(len(self.guest.verified_results), 1)

    def test_compact_decode_failure_falls_back_once_without_loading_bad_state(self):
        def restore(descriptor, part, target):
            raise ValueError('Different ISO dictionary')
        self.guest.local['wire'] = SimpleNamespace(restore=restore)
        record = self.begin()
        self.complete(self.d, self.compact)
        self.guest.run_job()
        self.assertFalse(record['part'].exists())
        self.assertFalse(record['target'].exists())
        self.assertNotIn('state', self.owner)
        self.assertEqual(self.guest.sent[-1]['type'], 'TRANSFER_FALLBACK')
        self.assertEqual(len([row for row in self.guest.sent if row['type'] == 'TRANSFER_FALLBACK']), 1)
        self.assertEqual(self.guest.jobs, [])

    def test_completed_old_verify_callback_cannot_verify_replacement_match(self):
        descriptor = self.host.make_transfer(2, self.meta, 'match', epoch=7, force_archive=True)
        self.begin(descriptor)
        self.complete(descriptor, self.archive)
        self.guest.run_job()
        job = self.guest.jobs.pop()
        self.guest.match = dict(self.owner, epoch=8)
        job[3](dict(static='old match'))
        self.assertEqual(self.guest.verified_results, [])

    def test_ordinary_archive_without_codec_is_still_verified_before_load(self):
        descriptor = self.host.make_transfer(2, self.meta, 'match', epoch=7, force_archive=True)
        record = self.begin(descriptor)
        self.complete(descriptor, self.archive)
        self.assertEqual(self.guest.jobs[0][0], 'transfer-decode')
        self.guest.run_job()
        self.assertEqual(record['target'].read_bytes(), self.archive)
        self.assertFalse(record['part'].exists())
        self.assertEqual(self.guest.jobs[0][0], 'verify')
        self.guest.run_job()
        self.assertEqual(len(self.guest.verified_results), 1)

    def test_rate_limited_sender_cancel_finishes_without_end_and_balances_channel_counter(self):
        self.host.args.send_rate = .01
        message = dict(token=self.d['token'], epoch=7, archive_sha256=self.d['archive_sha256'], offset=0)
        self.host.msg_TRANSFER_WANT(2, message)
        self.assertEqual(self.channel.transfers, 1)
        job = self.host.jobs.pop()
        result = []
        worker = threading.Thread(target=lambda: result.append(job[1](*job[2])))
        worker.start()
        deadline = time.monotonic() + 1
        while not self.channel.chunks and time.monotonic() < deadline: time.sleep(.005)
        self.host.cancel_transfers(2)
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])
        job[3](result[0])
        self.assertEqual(self.channel.transfers, 0)
        self.assertFalse(any(row['type'] == 'TRANSFER_END' for row in self.channel.messages))

    def test_resume_sender_checks_full_representation_before_skipping_prefix(self):
        self.host.msg_TRANSFER_WANT(2, dict(token=self.d['token'], epoch=7,
                                           archive_sha256=self.d['archive_sha256'], offset=5))
        self.host.run_job()
        self.assertEqual(self.channel.chunks[0][1:], (5, self.compact[5:]))
        self.assertEqual(self.channel.messages[-1]['type'], 'TRANSFER_END')
        self.assertEqual(self.channel.transfers, 0)

    def test_replaced_host_member_channel_cannot_receive_old_offer(self):
        self.host.members[2]['channel'] = Channel()
        self.host.msg_TRANSFER_WANT(2, dict(token=self.d['token'], epoch=7,
                                           archive_sha256=self.d['archive_sha256'], offset=0))
        self.assertEqual(self.host.jobs, [])
        self.assertEqual(self.channel.chunks, [])


if __name__ == '__main__':
    unittest.main()
