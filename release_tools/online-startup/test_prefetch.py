"""Lobby downloads remain optional, tagged, paced and safe to promote."""
import copy
import hashlib
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_prefetch
import kit_prebuild
import kit_net
import kit_spec


def choice():
    return kit_spec.make(tables_sha256='1' * 64, teams=[[(2, 0, 0)], [(54, 0, 1)]], stage=0,
                         mod_build='0.1.0-beta.8')


class Channel:
    def __init__(self):
        self.closed = False
        self.transfers = 0
        self.messages = []
        self.chunks = []

    def send_prefetch_chunk(self, sha, data):
        self.chunks.append((sha, data))

    def send_json(self, **message):
        self.messages.append(message)

    def try_send(self, **message):
        self.messages.append(message)
        return True


class Member(kit_prefetch.PrefetchMixin):
    def __init__(self, root):
        self.role, self.phase = 'guest', 'lobby'
        self.local = dict(catalog=dict(tables_sha256='1' * 64), view=object(),
                          install=dict(version='0.1.0-beta.8'))
        self.spec = choice()
        self.lobby = SimpleNamespace(spec=lambda *a, **k: copy.deepcopy(self.spec), ready=False)
        self.args = SimpleNamespace(send_rate=0, max_stall=18000, test_hooks=True)
        self.test_prep = {}
        self.states = Path(root)
        self.match, self.receiving = None, None
        self.quit = False
        self.jobs, self.messages, self.logs = [], [], []
        self.members = {2: dict(channel=Channel())}
        self.dirty = False
        self.init_prefetch()

    def say(self, text):
        self.logs.append(text)

    def send(self, **message):
        self.messages.append(message)

    def send_to(self, ident, **message):
        self.messages.append(dict(message, ident=ident))

    def busy(self, name):
        return any(item['name'] == name for item in self.jobs)

    def job(self, name, fn, *args, then=None, fail=None):
        self.jobs.append(dict(name=name, fn=fn, args=args, then=then, fail=fail))

    def match_delay(self):
        return 2

    def sent_file(self, channel, error=None):
        channel.transfers = max(0, channel.transfers - 1)

    def start_receive(self, sha, size, target):
        self.receiving = dict(sha=sha, size=size, target=target, got=0, data=bytearray())

    def on_chunk(self, ident, payload):
        if self.receiving is not None:
            self.receiving['data'].extend(payload)
            self.receiving['got'] += len(payload)

    def verify_file(self, path):
        return None

    def verified(self, static):
        pass

    def verify_failed(self, error):
        pass


class PrefetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.member = Member(self.temp.name)
        self.addCleanup(self.member.stop_prefetch_receive)
        self.validate = patch.object(kit_spec, 'validate').start()
        self.addCleanup(patch.stopall)
        self.payload = b'full validated snapshot payload'
        self.sha = hashlib.sha256(self.payload).hexdigest()

    def offer(self, size=None):
        return dict(sha256=self.sha, size=len(self.payload) if size is None else size,
                    spec=self.member.spec, spec_sha=kit_spec.spec_sha(self.member.spec))

    def begin(self, promote=False):
        m = self.member
        m.msg_PREFETCH(1, self.offer())
        self.assertIsNotNone(m.prefetch_receiving)
        if promote:
            m.match = dict(sha=self.sha, size=len(self.payload), spec_sha=kit_spec.spec_sha(m.spec))
            self.assertTrue(m.promote_prefetch(self.sha))
            m.phase = 'sending'
        return m.prefetch_receiving

    def host_meta(self, payload=None):
        m = self.member
        payload = self.payload if payload is None else payload
        source = m.states / 'host.p2s'
        source.write_bytes(payload)
        return dict(state=str(source), state_sha256=hashlib.sha256(payload).hexdigest(),
                    size=len(payload), spec=m.spec, spec_sha=kit_spec.spec_sha(m.spec),
                    max_stall=m.args.max_stall, options=None)

    def test_busy_publish_returns_false_and_accepted_publish_returns_true(self):
        m = self.member
        m.role = 'host'
        m.jobs.append(dict(name='prefetch-state'))
        self.assertFalse(m.publish_prebuild({}))
        m.jobs.clear()
        self.assertTrue(m.publish_prebuild({}))
        self.assertEqual([job['name'] for job in m.jobs], ['prefetch-state'])
        self.assertFalse(m.lobby.ready)

    def test_prebuild_retries_publish_when_previous_state_job_is_busy(self):
        token = object()
        record = dict(published=False, meta=dict(file='immutable.p2s'), prep=token, key=('exact', 'options'))
        with patch.object(self.member, 'publish_prebuild', side_effect=[False, True]) as publish:
            owner = SimpleNamespace(phase='lobby', role='host', prep=token,
                                    _prebuild_lobby_choice=lambda: dict(key=record['key']),
                                    publish_prebuild=publish)
            kit_prebuild.PrebuildMixin._publish_prebuild(owner, record)
            self.assertFalse(record['published'])
            kit_prebuild.PrebuildMixin._publish_prebuild(owner, record)
            self.assertTrue(record['published'])
            kit_prebuild.PrebuildMixin._publish_prebuild(owner, record)
            self.assertEqual(publish.call_count, 2)

    def test_duplicate_offer_does_not_reset_partial_file(self):
        m = self.member
        box = self.begin()
        m.on_prefetch_chunk(1, bytes.fromhex(self.sha) + self.payload[:10])
        m.msg_PREFETCH(1, self.offer())
        self.assertIs(m.prefetch_receiving, box)
        self.assertEqual(box['got'], 10)
        self.assertFalse(m.lobby.ready)

    def test_reused_member_id_with_new_channel_gets_the_same_sha_offer(self):
        m = self.member
        m.role = 'host'
        meta = self.host_meta()
        m.prefetch_state_ready(meta)
        original = m.members[2]['channel']
        self.assertIs(m.prefetch_offered[2]['channel'], original)
        m.members[2]['channel'] = Channel()        # a new room can reuse id2
        m.tick_prefetch()
        self.assertEqual(sum(message['type'] == 'PREFETCH' for message in m.messages), 2)
        self.assertIs(m.prefetch_offered[2]['channel'], m.members[2]['channel'])
        m.tick_prefetch()
        self.assertEqual(sum(message['type'] == 'PREFETCH' for message in m.messages), 2)
        self.assertFalse(m.lobby.ready)

    def test_departed_member_offer_is_pruned_before_an_id_is_reused(self):
        m = self.member
        m.role = 'host'
        meta = self.host_meta()
        m.prefetch_state_ready(meta)
        m.members.pop(2)
        m.tick_prefetch()
        self.assertNotIn(2, m.prefetch_offered)
        m.members[2] = dict(channel=Channel())
        m.tick_prefetch()
        self.assertEqual(sum(message['type'] == 'PREFETCH' for message in m.messages), 2)

    def test_accepted_republication_reoffers_same_sha_once(self):
        m = self.member
        m.role = 'host'
        meta = self.host_meta()
        m.prefetch_state_ready(meta)
        m.prefetch_state_ready(dict(meta))
        m.tick_prefetch()
        self.assertEqual(sum(message['type'] == 'PREFETCH' for message in m.messages), 2)
        stale = dict(meta, spec_sha='f' * 64)
        m.prefetch_state_ready(stale)
        m.tick_prefetch()
        self.assertEqual(sum(message['type'] == 'PREFETCH' for message in m.messages), 2)

    def test_canceled_same_sha_download_republished_during_active_send_restarts_from_zero(self):
        host = self.member
        host.role = 'host'
        meta = self.host_meta()
        guest = Member(host.states / 'guest')
        self.addCleanup(guest.stop_prefetch_receive)
        host.prefetch_state_ready(meta)
        offer = self.offer()
        guest.msg_PREFETCH(1, offer)
        host.msg_PREFETCH_WANT(2, guest.messages[-1])
        guest.on_prefetch_chunk(1, bytes.fromhex(self.sha) + self.payload[:10])
        old_part = guest.prefetch_receiving['part']
        guest.stop_prefetch_receive()
        self.assertFalse(old_part.exists())
        host.prefetch_state_ready(dict(meta))
        # No new receiver may start partway through the old same-SHA stream.
        self.assertEqual(sum(message['type'] == 'PREFETCH' for message in host.messages), 1)
        guest.on_prefetch_chunk(1, bytes.fromhex(self.sha) + self.payload[10:])
        guest.msg_PREFETCH_END(1, dict(sha256=self.sha))
        self.assertIsNone(guest.prefetch_receiving)
        host.jobs[-1]['then'](None)
        host.tick_prefetch()
        self.assertEqual(sum(message['type'] == 'PREFETCH' for message in host.messages), 2)
        guest.msg_PREFETCH(1, offer)
        self.assertEqual(guest.prefetch_receiving['got'], 0)
        host.msg_PREFETCH_WANT(2, guest.messages[-1])
        guest.on_prefetch_chunk(1, bytes.fromhex(self.sha) + self.payload)
        guest.msg_PREFETCH_END(1, dict(sha256=self.sha))
        cached = kit_prefetch.kit_match.have_state(self.sha, guest.states)
        self.assertEqual(cached.read_bytes(), self.payload)
        host.jobs[-1]['then'](None)
        host.tick_prefetch()
        self.assertEqual(sum(message['type'] == 'PREFETCH' for message in host.messages), 2)
        self.assertFalse(host.lobby.ready)
        self.assertFalse(guest.lobby.ready)

    def test_duplicate_wants_share_one_inflight_transfer(self):
        m = self.member
        m.role = 'host'
        m.prefetch_meta = self.host_meta()
        want = dict(sha256=self.sha, send=True)
        m.msg_PREFETCH_WANT(2, want)
        m.msg_PREFETCH_WANT(2, want)
        channel = m.members[2]['channel']
        self.assertEqual(channel.transfers, 1)
        self.assertEqual(len(m.jobs), 1)
        m.jobs[0]['then'](None)
        self.assertEqual(channel.transfers, 0)
        self.assertFalse(m.prefetch_sending)

    def test_old_channel_completion_does_not_clear_replacement_send(self):
        m = self.member
        m.role = 'host'
        m.prefetch_meta = self.host_meta()
        want = dict(sha256=self.sha, send=True)
        m.msg_PREFETCH_WANT(2, want)
        old = m.jobs[0]
        channel = Channel()
        m.members[2]['channel'] = channel
        m.msg_PREFETCH_WANT(2, want)
        old['then'](None)
        self.assertEqual(m.prefetch_sending[(2, self.sha)]['channel'], channel)
        self.assertEqual(channel.transfers, 1)

    def test_paced_stream_honors_send_rate(self):
        m = self.member
        m.role = 'host'
        m.args.send_rate = 1                  # kilobytes per second
        meta = self.host_meta(b'x' * 256)
        channel = Channel()
        clock = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        with patch.object(kit_prefetch.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(kit_prefetch.time, 'sleep', side_effect=sleep):
            m.send_prefetch_file(channel, meta)
        self.assertAlmostEqual(sum(sleeps), 0.256)
        self.assertTrue(all(0 < n <= 0.1 for n in sleeps))
        self.assertEqual(channel.messages[-1]['type'], 'PREFETCH_END')

    def test_stale_spec_during_rate_wait_aborts_without_end(self):
        m = self.member
        m.role = 'host'
        m.args.send_rate = 1
        meta = self.host_meta(b'x' * 256)
        channel = Channel()
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds
            m.spec['stage'] = 1

        with patch.object(kit_prefetch.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(kit_prefetch.time, 'sleep', side_effect=sleep):
            m.send_prefetch_file(channel, meta)
        self.assertEqual(channel.messages[-1]['type'], 'PREFETCH_ABORT')
        self.assertLessEqual(clock[0], 0.1)

    def test_unlimited_stream_does_not_sleep(self):
        m = self.member
        m.role = 'host'
        channel = Channel()
        meta = self.host_meta()
        with patch.object(kit_prefetch.time, 'sleep') as sleep:
            m.send_prefetch_file(channel, meta)
        sleep.assert_not_called()
        self.assertEqual(channel.chunks, [(self.sha, self.payload)])

    def test_stale_spec_options_or_stall_limit_cannot_offer(self):
        m = self.member
        m.role = 'host'
        meta = self.host_meta()
        for change in (lambda: m.spec.update(stage=1),
                       lambda: m.test_prep.update(test_ko=True),
                       lambda: setattr(m.args, 'max_stall', 9000)):
            original = copy.deepcopy(m.spec)
            change()
            m.prefetch_state_ready(meta)
            self.assertIsNone(m.prefetch_meta)
            self.assertFalse(m.messages)
            m.spec = original
            m.test_prep.clear()
            m.args.max_stall = 18000
        self.assertFalse(m.lobby.ready)

    def test_promoted_size_and_spec_must_match_match_offer(self):
        m = self.member
        for size, spec_sha in ((len(self.payload) + 1, kit_spec.spec_sha(m.spec)),
                               (len(self.payload), 'f' * 64)):
            self.begin()
            m.match = dict(sha=self.sha, size=size, spec_sha=spec_sha)
            self.assertFalse(m.promote_prefetch(self.sha))
            self.assertIsNone(m.prefetch_receiving)

    def test_oversize_promoted_stream_falls_back_once(self):
        m = self.member
        box = self.begin(promote=True)
        m.on_prefetch_chunk(1, bytes.fromhex(self.sha) + self.payload + b'oversize')
        self.assertFalse(box['part'].exists())
        self.assertIsNone(m.prefetch_receiving)
        self.assertEqual(m.receiving['sha'], self.sha)
        self.assertEqual([message for message in m.messages if message['type'] == 'WANT'],
                         [dict(type='WANT', send=True)])
        m.msg_PREFETCH_END(1, dict(sha256=self.sha))
        m.msg_PREFETCH_ABORT(1, dict(sha256=self.sha))
        self.assertEqual(sum(message['type'] == 'WANT' for message in m.messages), 1)

    def test_corrupt_or_incomplete_promoted_stream_falls_back(self):
        m = self.member
        for data in (b'x' * len(self.payload), self.payload[:10]):
            m.phase = 'lobby'
            m.receiving = None
            m.messages.clear()
            self.begin(promote=True)
            m.on_prefetch_chunk(1, bytes.fromhex(self.sha) + data)
            m.msg_PREFETCH_END(1, dict(sha256=self.sha))
            self.assertIsNotNone(m.receiving)
            self.assertEqual(sum(message['type'] == 'WANT' for message in m.messages), 1)
            self.assertFalse(m.jobs)

    def test_abort_promoted_stream_falls_back(self):
        m = self.member
        self.begin(promote=True)
        m.msg_PREFETCH_ABORT(1, dict(sha256=self.sha))
        self.assertIsNotNone(m.receiving)
        self.assertIsNone(m.prefetch_receiving)

    def test_valid_promoted_file_reaches_existing_verify_path_only(self):
        m = self.member
        self.begin(promote=True)
        m.on_prefetch_chunk(1, bytes.fromhex(self.sha) + self.payload)
        m.msg_PREFETCH_END(1, dict(sha256=self.sha))
        self.assertEqual(Path(m.match['state']).read_bytes(), self.payload)
        self.assertEqual([job['name'] for job in m.jobs], ['verify'])
        self.assertIsNone(m.receiving)
        self.assertFalse(m.lobby.ready)

    def test_old_sha_chunks_do_not_feed_new_prefetch_or_normal_match(self):
        m = self.member
        box = self.begin()
        old = bytes.fromhex('f' * 64) + b'wrong payload'
        m.on_prefetch_chunk(1, old)
        self.assertEqual(box['got'], 0)
        m.start_receive(self.sha, len(self.payload), m.states / 'normal.p2s')
        m.on_prefetch_chunk(1, old)
        self.assertEqual(m.receiving['got'], 0)

    def test_tagged_prefetch_and_normal_binary_frames_interleave_without_contamination(self):
        m = self.member
        box = self.begin()
        m.start_receive('f' * 64, 6, m.states / 'ordinary.p2s')
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        sender, receiver = kit_net.Channel(left), kit_net.Channel(right)
        sender.send_prefetch_chunk(self.sha, self.payload[:10])
        sender.send_chunk(b'normal')
        sender.send_prefetch_chunk('e' * 64, b'stale')
        sender.send_prefetch_chunk(self.sha, self.payload[10:])
        frames = receiver.poll_frames()
        self.assertEqual([kind for kind, _ in frames], ['P', 'B', 'P', 'P'])
        for kind, payload in frames:
            if kind == 'P':
                m.on_prefetch_chunk(1, payload)
            else:
                m.on_chunk(1, payload)
        self.assertEqual(box['got'], len(self.payload))
        self.assertEqual(box['h'].hexdigest(), self.sha)
        self.assertEqual(bytes(m.receiving['data']), b'normal')


if __name__ == '__main__':
    unittest.main()
