"""Immutable lobby match downloads, separate from live match/resync streams.

No game state is loaded here and Ready is never changed. MATCH still checks the
full selected spec, runtime writes and archive hash before the normal load/GO.
"""
import hashlib
import os
from pathlib import Path
import re
import time

import kit_match
import kit_net
import kit_spec
import kit_verify
import netplay_fixups


class PrefetchMixin:
    def init_prefetch(self):
        self.prefetch_meta = None
        self.prefetch_offered = {}
        self.prefetch_receiving = None
        self.prefetch_sending = {}

    def current_lobby_spec(self):
        if not self.lobby or not self.local:
            return None
        return self.lobby.spec(self.local['catalog']['tables_sha256'],
                               mod_build=(self.local.get('install') or {}).get('version'))

    def _prefetch_options(self):
        options = getattr(self, 'test_prep', None)
        return dict(options) if getattr(self.args, 'test_hooks', False) and options else None

    def _prefetch_meta_current(self, meta):
        spec = self.current_lobby_spec()
        return spec is not None and kit_spec.spec_sha(spec) == meta['spec_sha'] and \
            (meta.get('options') or None) == self._prefetch_options() and \
            meta.get('max_stall') == self.args.max_stall

    def publish_prebuild(self, meta):
        if self.role != 'host' or self.phase != 'lobby' or self.busy('prefetch-state'):
            return False
        self.job('prefetch-state', self.prefetch_state_job, meta, self.match_delay(), self.args.max_stall,
                 then=self.prefetch_state_ready, fail=lambda e: self.say(f'Lobby download deferred: {e}'))
        return True

    def prefetch_state_job(self, prepared, delay, max_stall=None):
        max_stall = self.args.max_stall if max_stall is None else max_stall
        meta = kit_match.netplay_state(prepared['file'], delay, max_stall, self.states, self.say,
                                      base_controls=kit_match.prepared_controls(prepared))
        words = kit_verify.file_words(meta['state'])
        problems = kit_verify.problems(words, prepared['spec'], netplay_fixups.fixed_sha256())
        if problems:
            raise ValueError('Lobby match differs from selected rules: ' + '; '.join(problems[:5]))
        meta = dict(meta, spec=prepared['spec'], spec_sha=prepared['spec_sha'], pnach=prepared['pnach'],
                    verify_sha=kit_verify.sha(words), options=prepared.get('options'))
        if hasattr(self, 'wire_artifact'):
            meta['wire'] = self.wire_artifact(meta)
        return meta

    def prefetch_state_ready(self, meta):
        if self.role != 'host' or self.phase != 'lobby' or not self._prefetch_meta_current(meta):
            return
        self.prefetch_meta = meta
        # A returning/canceled choice may use the same immutable SHA. Give
        # every current channel a fresh offer rather than remembering an old
        # room or a partial download its recipient has since discarded.
        self.prefetch_offered.clear()
        self.say('Selected match prepared in the lobby; downloading to the other players before Start.')
        self.tick_prefetch()

    def tick_prefetch(self):
        meta = self.prefetch_meta
        if self.role != 'host' or self.phase != 'lobby' or not meta:
            return
        if not self._prefetch_meta_current(meta):
            return
        for ident, offered in list(self.prefetch_offered.items()):
            member = self.members.get(ident)
            if member is None or offered['channel'] is not member['channel']:
                self.prefetch_offered.pop(ident)
        for ident in list(self.members):
            channel = self.members[ident]['channel']
            offered = self.prefetch_offered.get(ident)
            if offered is not None and offered['sha'] == meta['state_sha256'] and offered['channel'] is channel:
                continue
            active = self.prefetch_sending.get((ident, meta['state_sha256']))
            if active is not None and active['channel'] is channel:
                # Old same-SHA chunks have no offset tag. Wait for their
                # sender to finish before a canceled receiver starts anew;
                # the unmarked offer is retried on the next lobby tick.
                continue
            self.prefetch_offered[ident] = dict(sha=meta['state_sha256'], channel=channel)
            descriptor = self.make_transfer(ident, meta, 'prefetch') if hasattr(self, 'make_transfer') else None
            self.send_to(ident, type='PREFETCH', sha256=meta['state_sha256'], size=meta['size'],
                         spec=meta['spec'], spec_sha=meta['spec_sha'], transfer=descriptor)

    def msg_PREFETCH(self, ident, message):
        if self.role != 'guest' or self.phase != 'lobby':
            return
        try:
            import kit_controller
            sha, size, spec = message['sha256'], message['size'], message['spec']
            if not re.fullmatch(r'[0-9a-f]{64}', str(sha)) or type(size) is not int or not 0 < size <= 512 << 20:
                return
            kit_spec.validate(spec, self.local['view'], kit_controller.ALLOWED_SERVICES)
            if kit_spec.spec_sha(spec) != message.get('spec_sha'):
                return
        except (KeyError, TypeError, ValueError, kit_controller.KitError):
            return
        if kit_match.have_state(sha, self.states) is not None:
            self.send(type='PREFETCH_WANT', sha256=sha, send=False)
            return
        descriptor = message.get('transfer')
        if isinstance(descriptor, dict) and hasattr(self, 'begin_transfer'):
            if descriptor.get('archive_sha256') == sha and descriptor.get('archive_size') == size and \
                    descriptor.get('spec_sha') == message['spec_sha'] and descriptor.get('epoch') == 0:
                self.begin_transfer(descriptor, 'prefetch')
            return
        existing = self.prefetch_receiving
        if existing is not None and existing['sha'] == sha and existing['size'] == size and \
                existing['spec_sha'] == message['spec_sha']:
            # Repeated offers must not truncate the copy already arriving.
            self.send(type='PREFETCH_WANT', sha256=sha, send=True)
            return
        self.stop_prefetch_receive()
        target = kit_match.received_path(sha, self.states)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(f'{target.name}.{os.getpid()}.prefetch.part')
        self.prefetch_receiving = dict(sha=sha, size=size, got=0, h=hashlib.sha256(), part=part,
                                      target=target, file=part.open('wb'), promoted=False, started=time.time(),
                                      spec_sha=message['spec_sha'])
        self.send(type='PREFETCH_WANT', sha256=sha, send=True)

    def msg_PREFETCH_WANT(self, ident, message):
        meta = self.prefetch_meta
        if self.role != 'host' or not meta or ident not in self.members or message.get('sha256') != meta['state_sha256']:
            return
        if message.get('send') is not True:
            return
        channel = self.members[ident]['channel']
        key = ident, meta['state_sha256']
        current = self.prefetch_sending.get(key)
        if current is not None and current['channel'] is channel:
            return
        transfer = dict(channel=channel)
        self.prefetch_sending[key] = transfer
        channel.transfers += 1
        self.job('prefetch-send', self.send_prefetch_file, channel, dict(meta),
                 then=lambda _, k=key, t=transfer: self.prefetch_sent(k, t),
                 fail=lambda e, k=key, t=transfer: self.prefetch_sent(k, t, e))

    def prefetch_sent(self, key, transfer, error=None):
        if self.prefetch_sending.get(key) is transfer:
            self.prefetch_sending.pop(key)
        self.sent_file(transfer['channel'], error)

    def _prefetch_send_current(self, channel, meta):
        return not self.quit and not channel.closed and self._prefetch_meta_current(meta)

    def send_prefetch_file(self, channel, meta):
        sha = meta['state_sha256']
        sent, started = 0, time.monotonic()
        rate = max(0.0, float(getattr(self.args, 'send_rate', 0) or 0)) * 1000.0
        try:
            if Path(meta['state']).stat().st_size != meta['size']:
                raise ValueError('Lobby download size changed')
            with Path(meta['state']).open('rb') as stream:
                for chunk in iter(lambda: stream.read(kit_net.CHUNK), b''):
                    # Cancellation and stale roster edits stop only this stream.
                    # A promoted matching match may continue during preparation.
                    if not self._prefetch_send_current(channel, meta):
                        channel.try_send(type='PREFETCH_ABORT', sha256=sha)
                        return
                    channel.send_prefetch_chunk(sha, chunk)
                    sent += len(chunk)
                    if rate:
                        deadline = started + sent / rate
                        while time.monotonic() < deadline:
                            if not self._prefetch_send_current(channel, meta):
                                channel.try_send(type='PREFETCH_ABORT', sha256=sha)
                                return
                            # A low send-rate must not delay cancellation for
                            # the duration of a complete chunk.
                            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            if sent != meta['size']:
                raise ValueError('Lobby download size changed while reading')
            channel.send_json(type='PREFETCH_END', sha256=sha)
        except BaseException:
            channel.try_send(type='PREFETCH_ABORT', sha256=sha)
            raise

    def on_prefetch_chunk(self, ident, payload):
        box = self.prefetch_receiving
        if box is None or len(payload) <= 32 or payload[:32].hex() != box['sha']:
            return
        data = payload[32:]
        if box['got'] + len(data) > box['size']:
            self.stop_prefetch_receive()
            self._fallback_prefetch(box)
            return
        box['file'].write(data)
        box['h'].update(data)
        box['got'] += len(data)
        if box['promoted']:
            self.progress = dict(step='send.receiving', pct=box['got'] * 100 // box['size'],
                                 mb=round(box['size'] / 1e6, 1))
            self.dirty = True

    def promote_prefetch(self, sha, size=None):
        box = self.prefetch_receiving
        match = self.match or {}
        expected_size = match.get('size') if size is None else size
        if box is None or box['sha'] != sha or type(expected_size) is not int or \
                expected_size != box['size'] or box['got'] > expected_size or \
                match.get('spec_sha') != box['spec_sha']:
            self.stop_prefetch_receive()
            return False
        box['promoted'] = True
        return True

    def msg_PREFETCH_END(self, ident, message):
        box = self.prefetch_receiving
        if not box or message.get('sha256') != box['sha']:
            return
        promoted = box['promoted']
        self.prefetch_receiving = None
        box['file'].close()
        if box['got'] != box['size'] or box['h'].hexdigest() != box['sha']:
            box['part'].unlink(missing_ok=True)
            self._fallback_prefetch(box)
            return
        box['part'].replace(box['target'])
        self.say(f'Lobby match download checked ({box["got"] / 1e6:.1f} MB).')
        if promoted and self.match and self.match.get('sha') == box['sha'] and self.phase == 'sending':
            self.match['state'] = str(box['target'])
            self.job('verify', self.verify_file, box['target'], then=self.verified, fail=self.verify_failed)

    def msg_PREFETCH_ABORT(self, ident, message):
        box = self.prefetch_receiving
        if box and message.get('sha256') == box['sha']:
            self.stop_prefetch_receive()
            self._fallback_prefetch(box)

    def _fallback_prefetch(self, box):
        """Retry only the currently committed matching download, once."""
        match = self.match or {}
        if not box['promoted'] or self.role != 'guest' or self.phase != 'sending' or \
                match.get('sha') != box['sha'] or match.get('spec_sha') != box['spec_sha']:
            return False
        receiving = getattr(self, 'receiving', None)
        if receiving is not None and receiving.get('sha') == match['sha']:
            return True
        self.start_receive(match['sha'], match['size'], kit_match.received_path(match['sha'], self.states))
        self.send(type='WANT', send=True)
        return True

    def stop_prefetch_receive(self):
        box, self.prefetch_receiving = self.prefetch_receiving, None
        if box is not None:
            box['file'].close()
            box['part'].unlink(missing_ok=True)
