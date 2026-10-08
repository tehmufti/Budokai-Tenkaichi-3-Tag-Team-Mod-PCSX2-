"""Channel-owned, tagged initial/prefetch snapshots; resync uses its own stream.

A transport token identifies one offer, not just its immutable state. Canceled
chunks, old epochs and replaced member channels cannot feed a new receiver.
"""
import copy
import hashlib
import os
from pathlib import Path
import secrets
import struct
import time

import kit_match
import kit_net
import kit_wire

TAG = struct.Struct('>16sQ')


def valid_descriptor(d):
    if not isinstance(d, dict) or set(d) != {'token', 'codec', 'sha256', 'size', 'archive_sha256',
                                           'archive_size', 'spec_sha', 'epoch', 'iso_sha256'}:
        return False
    return isinstance(d['token'], str) and len(d['token']) == 32 and all(c in '0123456789abcdef' for c in d['token']) \
        and d['codec'] in ('archive', kit_wire.CODEC) and all(kit_wire.valid_sha(d[k]) for k in
                                                            ('sha256', 'archive_sha256', 'spec_sha')) \
        and type(d['size']) is int and 0 < d['size'] <= (kit_wire.MAX_WIRE if d['codec'] != 'archive' else kit_wire.MAX_ARCHIVE) \
        and type(d['archive_size']) is int and 0 < d['archive_size'] <= kit_wire.MAX_ARCHIVE \
        and type(d['epoch']) is int and 0 <= d['epoch'] <= 0x7FFFFFFF \
        and (d['codec'] == 'archive' and d['iso_sha256'] is None and d['sha256'] == d['archive_sha256']
             and d['size'] == d['archive_size'] or d['codec'] == kit_wire.CODEC and kit_wire.valid_sha(d['iso_sha256']))


class TransferMixin:
    def init_transfers(self):
        self.transfer_generation = 0
        self.transfer_offers = {}
        self.transfer_receives = {}
        self.transfer_fallback = {}

    def wire_artifact(self, meta):
        manager = (self.local or {}).get('wire')
        if manager is None or not any(manager.compatible(m.get('wire')) for m in tuple(self.members.values())):
            return None
        return manager.artifact(meta['state'], meta['state_sha256'], meta['size'])

    def make_transfer(self, ident, meta, purpose, epoch=0, force_archive=False):
        channel = self.members[ident]['channel']
        manager = (self.local or {}).get('wire')
        artifact = meta.get('wire') if manager and manager.compatible(self.members[ident].get('wire')) else None
        if force_archive or not artifact:
            artifact = dict(codec='archive', path=meta['state'], sha256=meta['state_sha256'], size=meta['size'])
        key = ident, purpose
        current = self.transfer_offers.get(key)
        if purpose == 'match' and not force_archive:
            current = self.transfer_offers.get((ident, 'prefetch')) or current
        if purpose == 'match' and not force_archive and current and not current.get('cancelled') and current['channel'] is channel and \
                current['generation'] == self.transfer_generation and \
                all(current['descriptor'][k] == v for k, v in
                    dict(archive_sha256=meta['state_sha256'], archive_size=meta['size'],
                         spec_sha=meta['spec_sha'], codec=artifact['codec'], sha256=artifact['sha256'], size=artifact['size']).items()):
            self.transfer_offers.pop((ident, current['purpose']), None)
            current.update(purpose=purpose, owner=self.match if purpose == 'match' else None)
            current['descriptor'] = dict(current['descriptor'], epoch=epoch)
            self.transfer_offers[key] = current
            return copy.deepcopy(current['descriptor'])
        old = self.transfer_offers.pop(key, None)
        if old:
            old['cancelled'] = True
        d = dict(token=secrets.token_hex(16), codec=artifact['codec'], sha256=artifact['sha256'], size=artifact['size'],
                 archive_sha256=meta['state_sha256'], archive_size=meta['size'], spec_sha=meta['spec_sha'], epoch=epoch,
                 iso_sha256=artifact.get('iso_sha256'))
        self.transfer_offers[key] = dict(descriptor=d, artifact=artifact, meta=copy.deepcopy(meta), channel=channel,
                                        ident=ident, purpose=purpose, generation=self.transfer_generation,
                                        owner=self.match if purpose == 'match' else None, cancelled=False,
                                        sending=False, sent=False, fallback=force_archive)
        return copy.deepcopy(d)

    def _offer_current(self, record):
        if self.quit or record['cancelled'] or record['channel'].closed or \
                record['generation'] != self.transfer_generation or \
                (self.members.get(record['ident']) or {}).get('channel') is not record['channel'] or \
                self.transfer_offers.get((record['ident'], record['purpose'])) is not record:
            return False
        if record['purpose'] == 'match':
            return self.match is record['owner'] and self.match.get('epoch') == record['descriptor']['epoch'] \
                and self.phase in ('sending', 'loading', 'fight')
        return self.phase in ('lobby', 'preparing', 'sending', 'loading') and self._prefetch_meta_current(record['meta'])

    def msg_TRANSFER_WANT(self, ident, message):
        if self.role != 'host':
            return
        record = next((r for r in self.transfer_offers.values() if r['ident'] == ident
                       and r['descriptor']['token'] == message.get('token')), None)
        if record is None or not self._offer_current(record) or record['sending']:
            return
        d = record['descriptor']
        if message.get('epoch') != d['epoch'] or message.get('archive_sha256') != d['archive_sha256']:
            return
        offset = message.get('offset', 0)
        if type(offset) is not int or not 0 <= offset <= d['size']:
            return
        record['send_offset'] = offset
        record['sending'] = True
        record['channel'].transfers += 1
        self.job('transfer-send', self._send_transfer, record,
                 then=lambda value, r=record: self._sent_transfer(r, cancelled=value is False),
                 fail=lambda e, r=record: self._sent_transfer(r, e))

    def _send_transfer(self, record):
        d, channel = record['descriptor'], record['channel']
        path = Path(record['artifact']['path'])
        rate = max(0.0, float(getattr(self.args, 'send_rate', 0) or 0)) * 1000.0
        got, started = record.get('send_offset', 0), time.monotonic()
        initial_offset = got
        checksum = hashlib.sha256()
        with path.open('rb') as stream:
            if path.stat().st_size != d['size'] or kit_wire.sha(path) != d['sha256']:
                raise ValueError('Offered representation changed before sending')
            left = got
            while left:
                prefix = stream.read(min(left, 1 << 20))
                if not prefix:
                    raise ValueError('Truncated representation prefix')
                checksum.update(prefix); left -= len(prefix)
            for chunk in iter(lambda: stream.read(kit_net.CHUNK), b''):
                if not self._offer_current(record):
                    return False
                if got + len(chunk) > d['size']:
                    raise ValueError('Offered representation grew')
                channel.send_transfer_chunk(d['token'], got, chunk)
                got += len(chunk); checksum.update(chunk)
                if rate:
                    deadline = started + (got - initial_offset) / rate
                    while time.monotonic() < deadline:
                        if not self._offer_current(record):
                            return False
                        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        if got != d['size'] or checksum.hexdigest() != d['sha256']:
            raise ValueError('Offered representation changed')
        if self._offer_current(record):
            channel.send_json(type='TRANSFER_END', token=d['token'], sha256=d['sha256'])
            return True
        return False

    def _sent_transfer(self, record, error=None, cancelled=False):
        if not record['sending']:
            return
        record['sending'] = False
        record['sent'] = error is None and not cancelled
        record['channel'].transfers = max(0, record['channel'].transfers - 1)
        if error and self._offer_current(record):
            record['channel'].try_send(type='TRANSFER_ABORT', token=record['descriptor']['token'])
            self.say(f'Snapshot transfer failed: {error}')

    def begin_transfer(self, descriptor, purpose, owner=None):
        if self.role != 'guest' or purpose not in ('match', 'prefetch') or not valid_descriptor(descriptor) or not self.net:
            return False
        if purpose == 'match' and (owner is not self.match or descriptor['archive_sha256'] != owner.get('sha')
                or descriptor['archive_size'] != owner.get('size') or descriptor['spec_sha'] != owner.get('spec_sha')
                or descriptor['epoch'] != owner.get('epoch')):
            return False
        previous = self.transfer_receives.get(purpose)
        if previous and previous['descriptor'] == descriptor and self._receive_current(previous):
            self._request_transfer(previous)
            return True
        self.stop_transfer(purpose)
        target = kit_match.received_path(descriptor['archive_sha256'], self.states)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + f'.{os.getpid()}-{descriptor["token"]}.wire.part')
        record = dict(descriptor=copy.deepcopy(descriptor), purpose=purpose, owner=owner,
                      generation=self.transfer_generation, channel=self.net['channel'], file=part.open('wb'),
                      part=part, target=target, h=hashlib.sha256(), got=0, cancelled=False, decoding=False)
        self.transfer_receives[purpose] = record
        self._request_transfer(record)
        return True

    def _request_transfer(self, record):
        d = record['descriptor']
        self.send(type='TRANSFER_WANT', token=d['token'], epoch=d['epoch'], archive_sha256=d['archive_sha256'],
                  offset=record['got'])

    def _receive_current(self, record):
        if record['cancelled'] or record['generation'] != self.transfer_generation or self.role != 'guest' or \
                not self.net or self.net['channel'] is not record['channel'] or record['channel'].closed or \
                self.transfer_receives.get(record['purpose']) is not record:
            return False
        if record['purpose'] == 'match':
            d = record['descriptor']
            return self.match is record['owner'] and self.match.get('epoch') == d['epoch'] \
                and self.match.get('sha') == d['archive_sha256'] and self.match.get('spec_sha') == d['spec_sha'] \
                and self.phase in ('sending', 'loading')
        return self.phase == 'lobby' or self.phase == 'preparing' and self.match is not None \
            and self.match.get('spec_sha') == record['descriptor']['spec_sha']

    def promote_transfer(self, descriptor, owner):
        record = self.transfer_receives.get('prefetch')
        if not record or not valid_descriptor(descriptor) or record['cancelled'] or owner is not self.match or \
                descriptor['archive_sha256'] != owner.get('sha') or descriptor['archive_size'] != owner.get('size') or \
                descriptor['spec_sha'] != owner.get('spec_sha') or descriptor['epoch'] != owner.get('epoch'):
            return False
        old = dict(record['descriptor'], epoch=descriptor['epoch'])
        if old != descriptor or record['channel'] is not (self.net or {}).get('channel') or \
                record['generation'] != self.transfer_generation:
            return False
        self.stop_transfer('match')
        self.transfer_receives.pop('prefetch')
        record.update(purpose='match', owner=owner, descriptor=copy.deepcopy(descriptor))
        self.transfer_receives['match'] = record
        return True

    def on_transfer_chunk(self, ident, payload):
        if self.role != 'guest' or ident != 1 or len(payload) <= TAG.size:
            return
        token, offset = TAG.unpack_from(payload)
        record = next((r for r in self.transfer_receives.values()
                       if r['descriptor']['token'] == token.hex()), None)
        if not record or not self._receive_current(record) or record['decoding']:
            return
        data = payload[TAG.size:]
        if offset != record['got'] or record['got'] + len(data) > record['descriptor']['size']:
            self._transfer_failed(record, ValueError('Invalid transfer offset or size'))
            return
        record['file'].write(data); record['h'].update(data); record['got'] += len(data)
        if record['purpose'] == 'match':
            self.progress = dict(step='send.receiving', pct=record['got'] * 100 // record['descriptor']['size'],
                                 mb=round(record['descriptor']['size'] / 1e6, 1))
            self.dirty = True

    def msg_TRANSFER_END(self, ident, message):
        if self.role != 'guest' or ident != 1:
            return
        record = next((r for r in self.transfer_receives.values()
                       if r['descriptor']['token'] == message.get('token')), None)
        if not record or not self._receive_current(record) or record['decoding']:
            return
        d = record['descriptor']
        record['file'].close(); record['file'] = None
        if message.get('sha256') != d['sha256'] or record['got'] != d['size'] or record['h'].hexdigest() != d['sha256']:
            self._transfer_failed(record, ValueError('Snapshot representation arrived damaged'))
            return
        record['decoding'] = True
        self.job('transfer-decode', self._restore_transfer, record,
                 then=lambda path, r=record: self._transfer_restored(r, path),
                 fail=lambda e, r=record: self._transfer_failed(r, e))

    def _restore_transfer(self, record):
        d = record['descriptor']
        manager = (self.local or {}).get('wire')
        if d['codec'] == 'archive' and manager is None:
            if record['part'].stat().st_size != d['archive_size'] or kit_wire.sha(record['part']) != d['archive_sha256']:
                raise ValueError('Ordinary snapshot identity differs')
            record['part'].replace(record['target'])
            return str(record['target'])
        if manager is None:
            raise ValueError('Compact transfer codec is unavailable')
        try:
            if isinstance(manager, kit_wire.Manager):
                return manager.restore(d, record['part'], record['target'], current=lambda: self._receive_current(record))
            return manager.restore(d, record['part'], record['target'])
        finally:
            record['part'].unlink(missing_ok=True)

    def _transfer_restored(self, record, path):
        if not self._receive_current(record):
            record['part'].unlink(missing_ok=True)
            return
        self.transfer_receives.pop(record['purpose'], None)
        if record['purpose'] == 'match':
            owner = record['owner']
            owner['state'] = path
            self.queue_state_verification(path, owner)
        else:
            self.say('Lobby snapshot received and reconstructed; Ready is unchanged.')

    def queue_state_verification(self, path, owner):
        epoch, generation = owner.get('epoch'), self.transfer_generation
        def current():
            return self.match is owner and owner.get('epoch') == epoch and \
                self.transfer_generation == generation and self.phase in ('sending', 'loading')
        self.job('verify', self.verify_file, path, copy.deepcopy(owner),
                 then=lambda static: self.verified(static) if current() else None,
                 fail=lambda error: self.verify_failed(error) if current() else None)

    def _transfer_failed(self, record, error):
        if not self._receive_current(record):
            record['part'].unlink(missing_ok=True)
            return
        d, purpose = record['descriptor'], record['purpose']
        if d['codec'] == kit_wire.CODEC:
            self.transfer_fallback[purpose] = dict(descriptor=copy.deepcopy(d), owner=record['owner'],
                                                   generation=record['generation'], channel=record['channel'])
        self.stop_transfer(purpose)
        if d['codec'] == kit_wire.CODEC:
            self.send(type='TRANSFER_FALLBACK', token=d['token'], archive_sha256=d['archive_sha256'], epoch=d['epoch'])
            self.say('Compact snapshot could not be used; requesting the original archive.')
        elif purpose == 'match':
            self.verify_failed(error)

    def msg_TRANSFER_FALLBACK(self, ident, message):
        if self.role != 'host':
            return
        record = next((r for r in self.transfer_offers.values() if r['ident'] == ident
                       and r['descriptor']['token'] == message.get('token')), None)
        if not record or not self._offer_current(record) or record['fallback'] or \
                record['descriptor']['codec'] != kit_wire.CODEC or message.get('epoch') != record['descriptor']['epoch'] \
                or message.get('archive_sha256') != record['descriptor']['archive_sha256']:
            return
        purpose, epoch = record['purpose'], record['descriptor']['epoch']
        descriptor = self.make_transfer(ident, record['meta'], purpose, epoch, force_archive=True)
        self.send_to(ident, type='TRANSFER_OFFER', transfer=descriptor, purpose=purpose)

    def msg_TRANSFER_OFFER(self, ident, message):
        if self.role != 'guest' or ident != 1:
            return
        purpose, descriptor = message.get('purpose'), message.get('transfer')
        if purpose not in ('match', 'prefetch'):
            return
        pending = self.transfer_fallback.get(purpose)
        if not pending or pending['generation'] != self.transfer_generation or \
                pending['channel'] is not (self.net or {}).get('channel') or not valid_descriptor(descriptor) or \
                descriptor['codec'] != 'archive' or any(descriptor[k] != pending['descriptor'][k]
                    for k in ('archive_sha256', 'archive_size', 'spec_sha', 'epoch')):
            return
        self.transfer_fallback.pop(purpose)
        if purpose == 'match' and self.match is pending['owner'] and self.phase == 'sending':
            self.begin_transfer(descriptor, purpose, self.match)
        elif purpose == 'prefetch' and self.phase == 'lobby':
            self.begin_transfer(descriptor, purpose)

    def msg_TRANSFER_ABORT(self, ident, message):
        if self.role != 'guest' or ident != 1:
            return
        record = next((r for r in self.transfer_receives.values()
                       if r['descriptor']['token'] == message.get('token')), None)
        if record:
            self._transfer_failed(record, ValueError('Snapshot sender stopped'))

    def stop_transfer(self, purpose):
        record = self.transfer_receives.pop(purpose, None)
        if record:
            record['cancelled'] = True
            if record['file']:
                record['file'].close(); record['file'] = None
            try:
                record['part'].unlink(missing_ok=True)
            except OSError:
                pass  # an in-flight decoder removes its own temporary file

    def cancel_transfers(self, ident=None):
        if ident is None:
            self.transfer_generation += 1
            self.transfer_fallback.clear()
            for purpose in list(self.transfer_receives):
                self.stop_transfer(purpose)
        for key, record in list(self.transfer_offers.items()):
            if ident is None or record['ident'] == ident:
                record['cancelled'] = True
                self.transfer_offers.pop(key)
