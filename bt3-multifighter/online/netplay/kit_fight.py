"""The match half of a kit's session process (kit 2.0): starting a match, the match file, loading, the lockstep fight,
resync and join, the result and the Retry / Return to lobby vote, and the emulator watch. Mixed into
kit_controller.Controller (the room half).

Host, Start (every player Ready): the lobby's spec (Random stage / music resolved), the players' slots and the input
delay (the worst guest-to-guest path) are fixed; PREPARE goes to every member; the host's match-making copy makes the
match (or a match made earlier for the same spec is reused); MATCH {sha256, size, delay, epoch, spec, verify_sha,
pnach, slot of THAT member} goes to every member, each fetches the file (WANT, B chunks, END) unless it has it,
checks it offline against the spec (kit_verify: verify_sha), writes its per-machine copy (kit_match.machine_copy: its
slot, its watched side, its display settings) and starts or PINE-loads it (LOADED). When every remaining PLAYER loaded, GO:
every game runs from the first update after the load (the intro) in lockstep (kit_lockstep: Hub on the host, Client
on a guest). A spectator that is late simply starts when it is ready.
The host may opt to remove guests whose load fails or times out (120 s), switching their fighters to CPUs with
frame-scheduled writes. The default cancels the start. The host's own load must succeed in either mode.
A member that joins during a fight gets JOINFIGHT and the host's current game (kit_resync, no hold): it watches at
once. A player that leaves a running fight leaves its fighter idle (neutral input from the host) and the fight goes
on; the host's PCSX2 closing ends the fight for everybody (No contest).
The end: every game parks in its result menu (neutral pads); the host sends RESULT and runs the vote (kit_postmatch.
Vote: Retry needs every player within 10 s; Return to lobby by anyone or the time out). RETRY: every PC PINE-loads its
own copy again (save slot 241) and attaches late; TO_LOBBY: every PC pauses and minimises its game.
"""
import copy
import json
import os
import shutil
import threading
import time
from pathlib import Path

import kit_lockstep
import kit_match
import kit_net
import kit_paths
import kit_postmatch
import kit_resync
import kit_settings
import kit_spec
import kit_verify
import kit_win
import netplay_fixups
from kit_codes import KitError

REMATCH_SLOT = kit_postmatch.REMATCH_SLOT
LOAD_SENTINEL = kit_resync.TOKEN_WORD
STALL_BANNER = 2.0
FREEZE_REPORT, FREEZE_END = 20.0, 40.0
FREEZE_SLOT = 246
LOAD_WAIT = 120.0                    # load deadline: cancel, or drop missing players if the host opted in
WATCH_EVERY = 1.0


def now():
    return time.monotonic()


class FightMixin:
    # ---- state --------------------------------------------------------------------------------------------------------
    def init_fight(self):
        self.match = None                    # spec, spec_sha, title, sha, size, delay, state, epoch, seats, pnach
        self.session = None                  # kit_lockstep.Hub (host) / Client (guest)
        self.fight = None
        self.fight_no = 0
        self.epoch = 0
        self.results = None
        self.vote = None                     # host: kit_postmatch.Vote
        self.vote_state = None               # guest: the host's VOTE_STATE
        self.resync = None                   # guest: kit_resync.GuestResync
        self.resyncs = {}                    # host: member -> kit_resync.HostResync
        self.receiving = None
        self.rematch_copy = None
        self.load_generation = 0
        self.load_lock = threading.RLock()
        self.loaded = set()                  # host: members whose game loaded this match
        self.my_loaded = False
        self.go = False
        self.load_started = None
        self.dropping_load_failures = False
        self.start_cpu_pending = []
        self.bot = None
        self.files = {}
        self.watch_side = None
        self.emu_watch = None
        self.last_watch = 0.0
        self.freeze_watch = None
        self.join_pending = {}               # host: member -> time it should get JOINFIGHT
        self.nocontest = None
        self.load_mode = None
        self.startup_started_at = None       # includes preparation, transfer, load and native introduction
        self.waiting_late = None
        self.service = None                  # host: kit_services.Broker while a match runs host services
        self.guest_bulk = None               # guest: kit_services.GuestBulk

    def my_slot(self):
        return (self.match or {}).get('slot')

    def fight_status(self):
        if self.session is None or self.phase != 'fight':
            return None
        s = self.session.status()
        out = dict(frame=s.get('frame'), state=s.get('state'), waiting=bool(s.get('waiting')),
                   stall_now=s.get('stall_now'), delay=self.session.delay, epoch=self.epoch,
                   resyncing=bool(self.resync) or bool(self.resyncs), decided=bool(s.get('decided')),
                   slot=self.my_slot(), watch=self.watch_side,
                   startup_seconds=s.get('startup_seconds'))
        if self.role == 'host':
            out['members'] = s.get('members')
        else:
            out.update(rtt_ms=s.get('rtt_ms'), lost=s.get('lost'))
        return out

    def vote_view(self):
        if self.role == 'host' and self.vote is not None:
            return self.vote.state(now())
        return self.vote_state

    def match_view(self):
        m = self.match
        if not m:
            return None
        return dict(title=m.get('title'), spec_sha=m.get('spec_sha'), delay=m.get('delay'), slot=m.get('slot'),
                    seats=m.get('seats'), epoch=self.epoch, spec=m.get('spec'))

    def write_summary(self):
        if not self.run_dir:
            return
        try:
            (self.run_dir / 'summary.json').write_text(json.dumps(self.summary, indent=1, default=str),
                                                       encoding='utf-8')
        except OSError:
            pass

    # ---- host: Start ---------------------------------------------------------------------------------------------------
    def match_delay(self):
        seats = self.lobby.seats()
        rtts = [self.members[m]['rtt'] for m in seats if m in self.members]
        forced = [d for d in [self.cfg.get('delay')] + [self.members[m].get('request_delay') for m in seats
                                                       if m in self.members] if d]
        return kit_net.pair_delay(rtts, max(int(x) for x in forced) if forced else None)

    def cmd_start(self, c):
        lob = self.lobby
        if self.role != 'host' or not lob or lob.phase != 'lobby' or self.phase != 'lobby':
            return
        if not lob.all_ready():
            lob.bump(dict(code=None, key='notice.not_ready', args={}))
            self.broadcast()
            return
        if self.prep is None:
            self.fail(KitError('TTM-NET-30', what='This PC cannot make matches (Start > Tag Team Mod folder).'))
            return
        view = self.local['view']
        lob.resolve_random(view)
        spec = lob.spec(self.local['catalog']['tables_sha256'], mod_build=(self.local.get('install') or {}).get(
            'version'))
        import kit_controller
        try:
            kit_spec.validate(spec, view, kit_controller.ALLOWED_SERVICES)
        except KitError as error:
            lob.clear_ready()
            lob.bump(dict(code=error.code, key='notice.invalid_rule', args=dict(what=error.values.get('what'))))
            self.broadcast()
            return
        seats = lob.seats()
        delay = self.match_delay()
        sha = kit_spec.spec_sha(spec)
        options = dict(self.test_prep) if self.args.test_hooks and self.test_prep else None
        prefetched = getattr(self, 'prefetch_meta', None)
        # A lobby download may have used a slightly larger measured delay.
        # Preserve it when it still covers every current latency/request;
        # otherwise rebuild normally rather than loading an under-buffered VM.
        if prefetched and prefetched.get('spec_sha') == sha and \
                (prefetched.get('options') or None) == options and prefetched.get('max_stall') == self.args.max_stall and \
                type(prefetched.get('delay')) is int and delay <= prefetched['delay'] <= 30:
            delay = prefetched['delay']
        title = kit_spec.title(spec, view)
        self.startup_started_at = time.perf_counter()
        self.match = dict(spec=spec, spec_sha=sha, title=title, delay=delay, seats=seats,
                          slot=seats.get(self.me), mask=kit_spec.slot_mask(spec),
                          max_stall=self.args.max_stall,
                          drop_load_failures=(lob.room.get('drop_load_failures') is True))
        lob.phase = 'preparing'
        lob.delay_hint = delay
        lob.bump(dict(code=None, key='notice.starting', args=dict(title=title)))
        self.broadcast()
        self.send(type='PREPARE', spec=spec, spec_sha=sha)
        self.set_phase('preparing')
        self.keep_rules()
        self.say(f'Starting: {title} (input delay {delay}; players {seats})')
        made = kit_match.made_match(sha, options)
        if made is not None:
            self.say('This match was made earlier: no preparation needed.')
            self.match_made(made)
            return
        self.start_auto(spec, options)

    def start_auto(self, spec, options):
        sha = kit_spec.spec_sha(spec)
        folder = kit_match.made_folder(sha)
        self.progress = dict(step='prep.wait_warm' if self.busy('warm') else 'prep.settings', pct=0, host=True)
        self.prep_gen += 1
        gen = self.prep_gen
        self.match['prep_gen'] = gen
        if self.adopt_prebuild(spec, options, gen):
            return
        controls = kit_match.transport_controls(dict(delay=self.match['delay'], max_stall=self.match['max_stall']))
        self.job('prep', self.prepare_job, self.prep, gen, spec, folder, options, self.match['title'], controls,
                 then=lambda meta, g=gen: self.auto_prepared(meta, g), fail=lambda e, g=gen: self.auto_failed(e, g))

    def prepare_job(self, prep, gen, spec, folder, options, title, controls=None):
        if not prep.lock.acquire(blocking=False):
            self.on_prep_progress('prep.wait_warm' if prep.state in ('cold', 'warming', 'failed') else
                                  'prep.wait_copy', 0, None)
            prep.lock.acquire()
        try:
            if gen != self.prep_gen:
                import kit_prepare_auto
                raise kit_prepare_auto.Cancelled()
            prep.cancel.clear()
            return self._prepare_locked(prep, spec, folder, options, title, controls=controls, deferred_reset=True)
        finally:
            prep.lock.release()

    def _prepare_locked(self, prep, spec, folder, options, title, *, controls=None, deferred_reset=False):
        import kit_ident
        sha = kit_spec.spec_sha(spec)
        made = kit_match.made_match(sha, options)
        if made is not None:
            self.on_prep_progress('prep.cached', 100, 0)
            return made
        if folder.exists():
            shutil.rmtree(folder)
        prepare_options = dict(language=self.host_language(), options=options, controls=controls)
        if deferred_reset:
            prepare_options['deferred_reset'] = True
        report = prep.prepare(spec, folder, **prepare_options)
        meta = dict(schema=2, name=folder.name, title=title, spec=spec, spec_sha=sha, kit=kit_ident.KIT_VERSION,
                    verify_sha=report['verify_sha'], options=options, pnach=report['pnach'], family=report['family'],
                    created=time.strftime('%Y-%m-%d %H:%M:%S'), installation=prep.install.get('root'),
                    build=prep.install.get('version'), seconds=report.get('seconds'), timings=report.get('timings'),
                    online_blocks=report.get('online_blocks'), test_blocks=report.get('test_blocks'),
                    fingerprint=report.get('fingerprint'), netplay_sha256=report['netplay_sha256'],
                    controls=(report.get('netplay') or {}).get('controls'),
                    director=report.get('director'))
        (folder / 'match.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
        kit_match.prune_made(spare={folder.name})
        meta['folder'], meta['file'] = str(folder), str(folder / 'netplay.p2s')
        try:
            import kit_wire
            # Added only after writing disk metadata. Cached match.json and
            # remote descriptors can never supply this process-local object.
            meta['_fresh_proof'] = kit_wire.fresh_preparation_proof(meta['file'], report)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.say(f'Fresh snapshot optimization unavailable ({type(error).__name__}); full checks remain enabled.')
        return meta

    def auto_prepared(self, meta, gen=None):
        if self.prep is not None and self.prep.state == 'warm' and not any(self.busy(n) for n in ('suspend', 'prep', 'prebuild')):
            self.job('suspend', self.prep.suspend, then=self.prep_suspended, fail=lambda e: None)
        if self.phase != 'preparing' or not self.match or self.match.get('spec_sha') != meta['spec_sha'] or \
                (gen is not None and gen != self.prep_gen):
            self.say(f'The match "{meta["title"]}" was made, but it is no longer starting (kept for later).')
            self.sync_warm()
            self.rewarm_if_cold()
            return
        self.say(f'Match made ({meta.get("seconds", 0)} s): {meta["title"]}')
        self.match_made(meta)

    def match_made(self, meta):
        self.match.update(verify_sha=meta.get('verify_sha'), pnach=meta.get('pnach'), base=meta['file'],
                          base_controls=kit_match.prepared_controls(meta))
        self.set_phase('sending')
        self.progress = dict(step='prep.state', pct=0)
        owner = self.match
        self.job('state', self.state_job, meta['file'], dict(owner), meta.get('_fresh_proof'),
                 then=lambda meta, o=owner: self.offer_match(meta) if self.match is o else None,
                 fail=lambda e, o=owner: self.state_failed(e) if self.match is o else None)

    def state_job(self, base, owner=None, fresh_proof=None):
        owner = self.match if owner is None else owner
        meta = kit_match.netplay_state(base, owner['delay'], owner.get('max_stall', self.args.max_stall),
                                      self.states, self.say, base_controls=owner.get('base_controls'))
        import kit_wire
        proved = type(fresh_proof) is kit_wire.FreshArchiveProof and \
            fresh_proof.matches(meta['state_sha256'], meta['size'])
        words = fresh_proof.words() if proved else kit_verify.file_words(meta['state'])
        found = kit_verify.problems(words, owner['spec'], netplay_fixups.fixed_sha256())
        if found:
            raise KitError('TTM-NET-31', what='The match file does not hold the lobby\'s match: ' + '; '.join(found[:5]))
        meta['verify_sha'] = kit_verify.sha(words)
        meta.update(spec=owner['spec'], spec_sha=owner['spec_sha'])
        if hasattr(self, 'wire_artifact'):
            manager = (getattr(self, 'local', None) or {}).get('wire')
            if proved and manager is not None:
                manager.register_fresh(fresh_proof)
            meta['wire'] = self.wire_artifact(meta)
        return meta

    def state_failed(self, error):
        code = error.code if isinstance(error, KitError) and error.code == 'TTM-NET-31' else 'TTM-NET-30'
        what = error.values.get('what') if isinstance(error, KitError) else str(error)
        self.prep_failed(code, what=str(what).splitlines()[0])

    def auto_failed(self, error, gen=None):
        import kit_install
        import kit_prepare_auto
        import re
        if isinstance(error, kit_prepare_auto.Cancelled):
            self.say('The preparation was cancelled.')
            self.sync_warm(force=True)
            self.rewarm_if_cold()
            return
        what = error.values.get('what') if isinstance(error, KitError) else f'{type(error).__name__}: {error}'
        code = error.code if isinstance(error, KitError) else 'TTM-NET-30'
        if code == 'TTM-NET-24' and self.prep is not None:
            root = self.prep.install.get('root')
            found = re.search(r'differs in ([\w, ]+?)\.', str(what))
            kit_install.mark_unusable(root, what, found.group(1) if found else None)
            self.lobby.members[1]['can_prepare'] = False
            self.lobby.warm = dict(state='refused', eta_s=None, why_key='why.refused_code' if found else 'why.refused',
                                   why=found.group(1) if found else None)
            self.prep.close()
            self.prep = None
        if self.phase != 'preparing' or (gen is not None and gen != self.prep_gen):
            self.say(f'(a preparation nobody waits for failed: {what})')
            self.sync_warm()
            return
        detail = f'{code}: {what}' if code not in ('TTM-NET-30', 'TTM-NET-31') else what
        spanish = {}
        what_es = error.values.get('what_es') if isinstance(error, KitError) else None
        if what_es:
            spanish['what_es'] = f'{code}: {what_es}' if code not in ('TTM-NET-30', 'TTM-NET-31') else what_es
        self.prep_failed('TTM-NET-31' if code == 'TTM-NET-31' else 'TTM-NET-30', what=detail,
                         notice='notice.prep_refused' if code == 'TTM-NET-24' else None, **spanish)

    def prep_failed(self, code, notice=None, **values):
        """The match cannot start: PREP_FAILED to every guest, everybody back to the lobby."""
        error = KitError(code, **values)
        if hasattr(self, 'cancel_transfers'):
            self.cancel_transfers()
        self.send(type='PREP_FAILED', **error.payload())
        self.say(str(error))
        if self.lobby:
            self.lobby.phase = 'lobby'
            self.lobby.clear_ready()
            self.lobby.bump(dict(code=code, key=notice or 'notice.prep_failed', args={}))
            self.broadcast()
        self.error = error.payload()
        self.progress = None
        self.match = None
        self.set_phase('lobby')
        if self.prep is not None and self.prep.state in ('cold', 'failed') and not any(self.busy(n) for n in ('prep', 'prebuild')):
            self.start_warm()

    def cmd_cancel_prep(self, c):
        if self.role != 'host' or self.phase not in ('preparing', 'sending', 'loading'):
            return
        self.cancel_prebuild(cancel_running=True)
        if self.prep is not None and self.busy('prep'):
            self.prep.cancel.set()
        self.prep_gen += 1
        self.send(type='TO_LOBBY', why='cancelled')
        self.say('The host cancelled the start.')
        self.back_to_lobby()
        self.lobby.bump(dict(code=None, key='notice.prep_cancelled', args={}))
        self.broadcast()

    def offer_match(self, meta):
        if not self.match or self.phase not in ('preparing', 'sending'):
            return
        self.epoch += 1
        self.match.update(state=meta['state'], sha=meta['state_sha256'], size=meta['size'],
                          verify_sha=meta['verify_sha'], epoch=self.epoch, wire=meta.get('wire'))
        self.loaded = set()
        self.my_loaded = False
        self.go = False
        self.load_started = now()
        self.lobby.phase = 'sending'
        self.lobby.bump()
        self.broadcast()
        for ident in list(self.members):
            self.offer_to(ident)
        self.say(f'Match file ready ({meta["size"] / 1e6:.1f} MB); every member gets it.')
        self.set_phase('loading')
        self.load_match()

    def offer_to(self, ident):
        m = self.match
        transfer = self.make_transfer(ident, dict(state=m['state'], state_sha256=m['sha'], size=m['size'],
                                                   spec=m['spec'], spec_sha=m['spec_sha'], wire=m.get('wire')),
                                      'match', self.epoch) if hasattr(self, 'make_transfer') else None
        self.send_to(ident, type='MATCH', sha256=m['sha'], size=m['size'], delay=m['delay'], epoch=self.epoch,
                     spec=m['spec'], spec_sha=m['spec_sha'], verify_sha=m['verify_sha'], pnach=m['pnach'],
                     title=m['title'], slot=m['seats'].get(ident), seats={str(k): v for k, v in m['seats'].items()},
                     max_stall=self.args.max_stall, transfer=transfer)

    # ---- guest: the offered match ----------------------------------------------------------------------------------------
    def msg_PREPARE(self, ident, m):
        self.startup_started_at = time.perf_counter()
        spec = m.get('spec')
        try:
            import kit_controller
            kit_spec.validate(spec, self.local['view'], kit_controller.ALLOWED_SERVICES)
            if kit_spec.spec_sha(spec) != m.get('spec_sha'):
                raise KitError('TTM-NET-31', what='the spec\'s SHA-256 does not match its text')
        except KitError as error:
            self.send(type='REFUSE', codes=[error.code], **error.payload())
            self.host_gone(error)
            return
        self.match = dict(spec=spec, spec_sha=m['spec_sha'], title=kit_spec.title(spec, self.local['view']))
        self.progress = dict(step='prep.settings', pct=0)
        self.results = None
        self.vote_state = None
        self.set_phase('preparing')

    def msg_PROGRESS(self, ident, m):
        if self.phase != 'preparing':
            return
        self.progress = dict(step=str(m.get('step')), pct=m.get('pct') if isinstance(m.get('pct'), int) else 0,
                             eta_s=m.get('eta_s') if isinstance(m.get('eta_s'), (int, float)) else None)
        self.dirty = True

    def msg_PREP_FAILED(self, ident, m):
        if self.role != 'guest' or self.phase not in ('preparing', 'sending', 'loading'):
            return
        code = str(m.get('code') or 'TTM-NET-30')
        self.error = dict(code=code, en=str(m.get('en') or code), es=str(m.get('es') or m.get('en') or code),
                          remedies=[])
        self.say(self.error['en'])
        self.leave_match_state()
        self.set_phase('lobby')

    def msg_MATCH(self, ident, m):
        import re
        problem = None
        try:
            if not re.fullmatch(r'[0-9a-f]{64}', str(m.get('sha256'))):
                problem = 'its SHA-256 is not 64 hex digits'
            elif not 0 < int(m.get('size')) <= 512 << 20:
                problem = f'size {m.get("size")!r}'
            elif not 1 <= int(m.get('delay')) <= 30 or int(m.get('epoch')) < 1:
                problem = f'delay {m.get("delay")!r} / epoch {m.get("epoch")!r}'
            elif m.get('slot') is not None and int(m['slot']) not in range(10):
                problem = f'slot {m.get("slot")!r}'
            elif not isinstance(m.get('pnach'), str):
                problem = 'no runtime patch named'
        except (TypeError, ValueError):
            problem = 'a field is not a number'
        spec = m.get('spec')
        if problem is None:
            try:
                import kit_controller
                kit_spec.validate(spec, self.local['view'], kit_controller.ALLOWED_SERVICES)
                if kit_spec.spec_sha(spec) != m.get('spec_sha'):
                    problem = 'its spec text does not match its SHA-256'
            except KitError as error:
                problem = error.values.get('what') or error.code
        if problem:
            error = KitError('TTM-NET-13', why=f'it offered a malformed match ({problem})')
            self.send(type='REFUSE', codes=['TTM-NET-13'], **error.payload())
            self.host_gone(error)
            return
        if int(m['epoch']) <= self.epoch and self.match and self.match.get('sha'):
            return
        self.epoch = int(m['epoch'])
        self.match = dict(spec=spec, spec_sha=m['spec_sha'], title=m.get('title') or kit_spec.title(spec,
                                                                                                 self.local['view']),
                          sha=m['sha256'], size=int(m['size']), delay=int(m['delay']), verify_sha=m.get('verify_sha'),
                          pnach=m['pnach'], slot=None if m.get('slot') is None else int(m['slot']),
                          seats={int(k): v for k, v in (m.get('seats') or {}).items()}, epoch=self.epoch,
                          mask=kit_spec.slot_mask(spec))
        self.watch_side = None
        self.results = None
        self.vote_state = None
        self.say(f'Match: {self.match["title"]} (input delay {self.match["delay"]}; '
                 f'{"you play slot " + str(self.match["slot"]) if self.match["slot"] is not None else "you watch"})')
        have = kit_match.have_state(m['sha256'], self.states)
        if have is not None and have.stat().st_size != self.match['size']:
            have = None
        descriptor = m.get('transfer')
        if descriptor is not None and hasattr(self, 'begin_transfer'):
            self.set_phase('sending')
            owner = self.match
            if have is not None:
                self.stop_transfer('prefetch')
                owner['state'] = str(have)
                self.queue_state_verification(have, owner)
            elif not self.promote_transfer(descriptor, owner):
                self.stop_transfer('prefetch')
                if not self.begin_transfer(descriptor, 'match', owner):
                    self.verify_failed(ValueError('Malformed match transfer descriptor'))
            return
        promoted = have is None and self.promote_prefetch(m['sha256'])
        self.send(type='WANT', send=have is None and not promoted)
        self.set_phase('sending')
        if have is not None:
            self.stop_prefetch_receive()
            self.match['state'] = str(have)
            self.job('verify', self.verify_file, have, then=self.verified, fail=self.verify_failed)
        elif not promoted:
            self.start_receive(m['sha256'], int(m['size']), kit_match.received_path(m['sha256'], self.states))

    def start_receive(self, sha, size, target):
        import hashlib
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(f'{target.name}.{os.getpid()}-{self.me}.part')     # never shared by two kits
        box = dict(h=hashlib.sha256(), got=0, size=size, sha=sha, part=part, target=target, file=open(part, 'wb'),
                   started=time.time())
        self.receiving = box

    def on_chunk(self, ident, payload):
        box = self.receiving
        if box is not None:
            box['file'].write(payload)
            box['h'].update(payload)
            box['got'] += len(payload)
            self.progress = dict(step='send.receiving', pct=box['got'] * 100 // max(box['size'], 1),
                                 mb=round(box['size'] / 1e6, 1))
            self.dirty = True
        elif self.resync is not None:
            self.resync.feed(payload)

    def stop_receive(self):
        box, self.receiving = self.receiving, None
        if box is None:
            return
        try:
            box['file'].close()
            box['part'].unlink()
        except OSError:
            pass

    def msg_END(self, ident, m):
        if self.receiving is not None:
            box = self.receiving
            self.receiving = None
            box['file'].close()
            digest = box['h'].hexdigest()
            if digest != box['sha'] or box['got'] != box['size']:
                try:
                    box['part'].unlink()
                except OSError:
                    pass
                self.send(type='GOT', ok=False, why=f'the file arrived damaged ({box["got"]} bytes)')
                self.fail(KitError('TTM-NET-08', what='the match file arrived damaged'), phase='lobby')
                return
            try:
                box['part'].replace(box['target'])
            except OSError:
                # another kit in this folder (a test rig) received the same file at the same moment: use its copy
                if not (box['target'].exists() and box['target'].stat().st_size == box['size']):
                    raise
                try:
                    box['part'].unlink()
                except OSError:
                    pass
            self.say(f'Match file received and checked ({box["got"] / 1e6:.1f} MB in '
                     f'{time.time() - box["started"]:.1f} s).')
            self.match['state'] = str(box['target'])
            self.job('verify', self.verify_file, box['target'], then=self.verified, fail=self.verify_failed)
        elif self.resync is not None:
            self.resync.end()

    def verify_file(self, path, owner=None):
        m = owner if owner is not None else self.match or {}
        manager = (getattr(self, 'local', None) or {}).get('wire')
        snapshot = manager.snapshot_for(path, m.get('sha'), m.get('size')) \
            if manager is not None and hasattr(manager, 'snapshot_for') else None
        words = kit_verify.file_words(path, snapshot=snapshot) if snapshot is not None else kit_verify.file_words(path)
        found = kit_verify.problems(words, m['spec'], netplay_fixups.fixed_sha256())
        if m.get('verify_sha') and kit_verify.sha(words) != m['verify_sha']:
            found.append('its check words differ from the host\'s (verify_sha)')
        if found:
            raise KitError('TTM-NET-31', what='The match file this PC received does not hold the lobby\'s match: ' +
                                              '; '.join(found[:5]))
        self.say('Match file checked against the lobby: fighters, stage, music, rules and the online writes as agreed.')
        return kit_verify.static_of(words)

    def verified(self, static):
        if not self.match or self.phase not in ('sending', 'loading'):
            return
        self.send(type='GOT', ok=True)
        self.set_phase('loading')
        self.load_match()

    def verify_failed(self, error):
        why = error.values.get('what') if isinstance(error, KitError) else str(error)
        self.send(type='GOT', ok=False, code='TTM-NET-31', why=str(why)[:400])
        self.fail(error if isinstance(error, KitError) else KitError('TTM-NET-31', what=str(why)), phase='lobby')

    # ---- host: sending the file ------------------------------------------------------------------------------------------
    def msg_WANT(self, ident, m):
        if self.role != 'host' or not self.match or ident not in self.members:
            return
        if m.get('send'):
            ch = self.members[ident]['channel']
            ch.transfers += 1
            self.job('send', self.send_file, ch, Path(self.match['state']), self.match['sha'],
                     then=lambda _, ch=ch: self.sent_file(ch), fail=lambda e, ch=ch: self.sent_file(ch, e))

    def send_file(self, ch, path, sha):
        size = path.stat().st_size
        sent, started = 0, time.time()
        rate = (self.args.send_rate or 0) * 1000.0
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(kit_net.CHUNK), b''):
                ch.send_chunk(chunk)
                sent += len(chunk)
                if rate:
                    time.sleep(max(0.0, started + sent / rate - time.time()))
        ch.send_json(type='END', sha256=sha, size=size)
        return size

    def sent_file(self, ch, error=None):
        ch.transfers = max(0, ch.transfers - 1)
        if error:
            self.say(f'Sending a file failed: {error}')

    def msg_GOT(self, ident, m):
        if self.role != 'host' or not self.match:
            return
        if m.get('ok'):
            return
        name = self.lobby.members.get(ident, {}).get('name', ident)
        if ident in self.match['seats']:
            if self.phase in ('sending', 'loading') and self.match.get('drop_load_failures') is True:
                self.drop_loading_members([ident], 'the match file could not be used')
            else:
                self.prep_failed('TTM-NET-31' if m.get('code') == 'TTM-NET-31' else 'TTM-NET-08',
                                 what=f'{name}: ' + str(m.get('why') or 'the match file could not be used')[:400])
        else:
            self.say(f'{name} (watching) could not use the match file: {m.get("why")}')

    # ---- loading -----------------------------------------------------------------------------------------------------------
    def load_match(self):
        if self.busy('preboot'):
            self.pending_preboot_load = True
            self.progress = dict(step='load.starting', pct=0)
            return
        self.progress = dict(step='load.starting', pct=0)
        self.my_loaded = False
        self.go = False
        self.rematch_copy = None
        self.load_generation += 1
        changed = self.emulator.install_pnach(self.match['pnach'])
        running = self.emulator.pid and self.emulator.alive() and self.link is not None
        if running and changed:
            self.say('This match needs another runtime patch: PCSX2 starts again.')
            self.emulator.stop()
            self.link = None
            running = False
        if running:
            request = self.load_request()
            self.job('copy', self.build_copy, request,
                     then=lambda result, r=request: self.copy_built_for_load(result) if self.load_current(r) else None,
                     fail=lambda error, r=request: self.load_failed(error) if self.load_current(r) else None)
        else:
            request = self.load_request()
            self.job('launch', self.launch_game, request,
                     then=lambda result, r=request: self.launch_completed(result, r),
                     fail=lambda error, r=request: self.load_failed(error) if self.load_current(r) else None)

    def machine_path(self, name):
        return self.emulator.root / 'sstates' / name

    def load_request(self):
        """Freeze the current load owner and all per-PC inputs before a worker starts."""
        return dict(owner=self.match, epoch=self.epoch, generation=self.load_generation,
                    match=copy.deepcopy(self.match), slot=self.my_slot(), watch=copy.deepcopy(self.watch_side),
                    local=copy.deepcopy(self.profile.get('local')), seal=self.my_seal(), emulator=self.emulator,
                    iso=self.local['iso'], fullscreen=bool(self.cfg.get('fullscreen')),
                    snapshot=self._decoded_load_snapshot())

    def _decoded_load_snapshot(self):
        manager = (getattr(self, 'local', None) or {}).get('wire')
        m = self.match or {}
        return manager.snapshot_for(m['state'], m['sha'], m['size']) \
            if manager is not None and hasattr(manager, 'snapshot_for') and m.get('state') else None

    def load_current(self, request):
        return self.match is request['owner'] and self.epoch == request['epoch'] and \
            self.load_generation == request['generation'] and self.emulator is request['emulator'] and \
            self.phase in ('sending', 'loading', 'fight') and \
            all(self.match.get(key) == request['match'].get(key)
                for key in ('state', 'sha', 'delay', 'mask', 'pnach', 'spec_sha', 'max_stall'))

    def _check_load_current(self, request):
        if not self.load_current(request):
            raise ValueError('The initial match load was canceled or superseded.')

    def _paused_machine_allowed(self, request):
        em = request['emulator']
        return em.START_PAUSED is True and em.CAN_POST_KEYS is True

    def _make_load_copy(self, request, target, fast):
        m = request['match']
        if fast:
            plan = kit_match.paused_machine_copy(m['state'], target, request['slot'], request['watch'],
                request['local'], request['seal'], state_sha=m['sha'], delay=m['delay'], mask=m['mask'],
                snapshot=request.get('snapshot'))
        else:
            kit_match.machine_copy(m['state'], target, request['slot'], request['watch'],
                                   request['local'], request['seal'])
            plan = None
        self._check_load_current(request)
        # The scalar plan remains sufficient after construction; do not retain 128 MiB RAM in Retry records.
        return dict(path=str(target), sha=m['sha'], epoch=request['epoch'],
                    request=dict(request, snapshot=None), plan=plan)

    def build_copy(self, request=None):
        """This PC's copy of the match (its slot, watched side and display settings) in PCSX2 save slot 241."""
        request = self.load_request() if request is None else request
        with self.load_lock:
            self._check_load_current(request)
            em = request['emulator']
            fast = self._paused_machine_allowed(request)
            # Decide fallback before loading or mutating common-state RAM.
            # Background Retry copy construction must not pause an active fight.
            if fast and self.phase != 'fight' and self.link is not None:
                if em.pine_owner() != em.pid or getattr(self.link, 'pid', em.pid) != em.pid:
                    raise ValueError('The match copy PINE owner changed before pausing.')
                fast = em.ensure_paused(self.link)
            return self._make_load_copy(request, em.state_file(REMATCH_SLOT), fast)

    def launch_game(self, request=None):
        request = self.load_request() if request is None else request
        with self.load_lock:
            return self._launch_game(request)

    def _launch_game(self, request):
        from pinelink import nc, PineLink
        import kit_ident
        self._check_load_current(request)
        em = request['emulator']
        if self.link is not None:
            try:
                self.link.close()
            except OSError:
                pass
            self.link = None
        target = em.root / 'sstates' / 'netplay-machine.p2s'
        record = self._make_load_copy(request, target, self._paused_machine_allowed(request))
        self._check_load_current(request)
        pid = em.launch(target, request['iso'], fullscreen=request['fullscreen'])
        process_token = self._load_process_token(em, pid)
        self.remember_pid(pid)
        try:
            info = em.wait_ready(nc.CONTROL, nc.MAGIC, timeout=max(self.args.timeout, 120))
            self._check_load_current(request)
        except BaseException:
            if em.pid == pid:
                em.stop()
            raise
        problems = kit_ident.runtime_problems(info or {})
        if problems:
            if em.pid == pid:
                em.stop()
            code, text = problems[0]
            raise KitError(code, what=text, build=info.get('version'), tested=', '.join(kit_ident.TESTED_PINE))
        em.place()
        link = PineLink(self.args.pine_slot, pid, owner=em.pine_owner).connect()
        em.link = link
        try:
            if record['plan'] is not None:
                self._apply_load_plan(request, record, link, pid,
                                      loaded_path=em.root / 'sstates' / 'netplay.p2s')
            else:
                self.live_check(link, target)
            self._check_load_current(request)
        except BaseException:
            link.close()
            if em.pid == pid:
                em.stop()
            raise
        return dict(pid=pid, info=info, link=link, process_token=process_token)

    @staticmethod
    def _load_process_token(em, pid):
        """The original process identity, for cleaning up a canceled launch only."""
        proc = getattr(em, 'proc', None)
        if proc is not None and getattr(proc, 'pid', None) == pid:
            return ('process', proc)
        if os.name != 'nt' or not pid:
            return None
        import ctypes
        import ctypes.wintypes as wt
        import kit_win
        handle = kit_win.kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return None
        try:
            times = [wt.FILETIME() for _ in range(4)]
            get_times = kit_win.kernel32.GetProcessTimes
            get_times.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
            size, path = wt.DWORD(32768), ctypes.create_unicode_buffer(32768)
            if not get_times(handle, *(ctypes.byref(value) for value in times)) or \
                    not kit_win.kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                return None
            return ('windows', os.path.normcase(path.value), times[0].dwHighDateTime, times[0].dwLowDateTime)
        finally:
            kit_win.kernel32.CloseHandle(handle)

    def launch_completed(self, result, request):
        with self.load_lock:
            if self.load_current(request):
                self.game_launched(result)
                return
            # Cancellation may happen after the worker returns but before its
            # queued callback. Close its own link, never a newer load's link.
            try:
                result['link'].close()
            except (OSError, RuntimeError):
                pass
            em, pid = request['emulator'], result['pid']
            token = result.get('process_token')
            if self.emulator is em and em.pid == pid and em.pine_owner() == pid and token is not None and \
                    self._load_process_token(em, pid) == token:
                em.stop()

    def _apply_load_plan(self, request, record, link, pid, *, loaded_path=None):
        """A source/target/owner-bound plan; failure after loading always closes this VM."""
        em = request['emulator']
        def current():
            return self.load_current(request) and em.pid == pid and em.pine_owner() == pid
        self._check_load_current(request)
        plan = record['plan']
        if record['epoch'] != request['epoch'] or record['sha'] != request['match']['sha'] or \
                plan['sha'] != record['sha'] or kit_match.sha256_file(record['path']) != plan['sha'] or \
                (loaded_path is not None and kit_match.sha256_file(loaded_path) != plan['sha']):
            raise ValueError('The initial loaded machine archive/epoch guard changed.')
        kit_match.apply_paused_machine(link, plan, current=current)
        self._check_load_current(request)

    def my_seal(self):
        """netplay_core sched_sealed of this PC's copy: the host seals its own game (NO_SEAL); a guest's game may run
        the frames below D (the host schedules nothing before its frame + D + 2)."""
        from pinelink import nc
        return nc.NO_SEAL if self.role == 'host' else max(0, int(self.match['delay']) - 1)

    def remember_pid(self, pid):
        try:
            p = kit_paths.DATA / 'processes.json'
            p.write_text(json.dumps(dict(pcsx2=pid, at=time.time(), session=os.getpid())), encoding='utf-8')
        except OSError:
            pass

    def live_check(self, link, path):
        """The STATIC words read over PINE must equal the loaded file's (TTM-NET-31)."""
        want = kit_verify.file_words(path, static=True)
        got = kit_verify.words(link, static=True)
        if got != want:
            diff = kit_verify.differences(want, got)
            raise KitError('TTM-NET-31', what='The game this PC loaded differs from the match file: ' +
                                              '; '.join(diff[:4]))

    def load_failed(self, error):
        self.fail(error if isinstance(error, KitError) else KitError('TTM-NET-22', what=str(error),
                                                                    logs=str(self.run_dir)))
        if self.role == 'guest':
            self.send(type='LOAD_FAILED', epoch=self.epoch, why=str(error)[:300])
            self.leave_match_state()
            self.set_phase('lobby')
        else:
            self.prep_failed('TTM-NET-22', what=f'the host\'s PCSX2 could not load the match: {error}')

    def game_launched(self, r):
        self.link = r['link']
        self.load_mode = 'launch'
        self.loaded_ok()

    def copy_built_for_load(self, copy):
        self.rematch_copy = copy
        self.load_mode = 'pine'
        self.loaded_ok()

    def loaded_ok(self):
        self.my_loaded = True
        self.progress = dict(step='load.waiting', pct=100)
        if self.role == 'guest':
            self.send(type='LOADED', epoch=self.epoch)
            if self.go:
                self.on_go()
        else:
            self.check_go()
        self.dirty = True

    def msg_LOADED(self, ident, m):
        if self.role != 'host' or ident not in self.members or int(m.get('epoch') or 0) != self.epoch:
            return
        self.loaded.add(ident)
        if self.go:                                      # a spectator that is late: it starts now
            self.send_to(ident, type='GO', epoch=self.epoch)
            if self.session is not None and ident not in self.session.members:
                self.session.add_member(ident, None, self.lobby.members.get(ident, {}).get('name', ''))
        self.check_go()

    def msg_LOAD_FAILED(self, ident, m):
        if self.role != 'host' or not self.match or ident not in self.members or int(m.get('epoch') or 0) != self.epoch:
            return
        name = self.lobby.members.get(ident, {}).get('name', ident)
        if ident in self.match['seats'] and self.phase in ('sending', 'loading'):
            if self.match.get('drop_load_failures') is True:
                self.drop_loading_members([ident], 'PCSX2 could not load the match')
            else:
                self.prep_failed('TTM-NET-22', what=f'{name}\'s PCSX2 could not load the match: {m.get("why")}')
        else:
            self.say(f'{name} could not load the match: {m.get("why")}')

    def drop_loading_members(self, targets, reason):
        """Remove failed guests as a batch. A member-left callback must not start halfway through the batch."""
        if self.role != 'host' or not self.match or self.phase not in ('sending', 'loading'):
            return
        targets = [k for k in targets if k != self.me and k in self.members and k in self.match['seats']]
        names = [str(self.lobby.members.get(k, {}).get('name', k)) for k in targets]
        self.dropping_load_failures = True
        try:
            for ident, name in zip(targets, names):
                self.send_to(ident, type='BYE', why='load_failed')
                self.member_gone(ident, said=f'{name} was removed before the start: {reason}; its fighter becomes a CPU.')
        finally:
            self.dropping_load_failures = False
        if names:
            self.lobby.bump(dict(code=None, key='notice.load_players_dropped', args=dict(names=', '.join(names))))
            self.broadcast()
        self.check_go()

    def check_go(self):
        if self.role != 'host' or self.go or self.phase != 'loading' or not self.my_loaded or self.dropping_load_failures:
            return
        players = [k for k in self.match['seats'] if k != self.me]
        missing = [k for k in players if k not in self.loaded and k in self.members]
        if missing:
            if self.load_started is not None and now() - self.load_started >= LOAD_WAIT:
                if self.match.get('drop_load_failures') is True:
                    self.drop_loading_members(missing, f'the {int(LOAD_WAIT)}-second loading deadline expired')
                else:
                    names = ', '.join(str(self.lobby.members.get(k, {}).get('name', k)) for k in missing)
                    self.prep_failed('TTM-NET-22', what=f'{names} did not load the match in {int(LOAD_WAIT)} s')
            return
        self.go = True
        for ident in self.loaded:
            self.send_to(ident, type='GO', epoch=self.epoch)
        self.on_go()

    def msg_GO(self, ident, m):
        if int(m.get('epoch') or 0) != self.epoch:
            return
        self.go = True
        if self.my_loaded and self.phase == 'loading':
            self.on_go()

    def on_go(self):
        self.progress = None
        if self.load_mode == 'launch':
            self.begin_fight(late=False)
            if not self.emulator.ensure_running(self.link):
                self.say('PCSX2 did not start running the match (it stayed paused).')
        else:
            self.schedule_pine_load(self.rematch_copy)

    def schedule_pine_load(self, record):
        request = record['request']
        self.job('pineload', self.pine_load, record,
                 then=lambda _, r=request: self.begin_fight(late=True) if self.load_current(r) else None,
                 fail=lambda error, r=request: self.load_failed(error) if self.load_current(r) else None)

    def pine_load(self, record=None):
        record = self.rematch_copy if record is None else record
        request = record['request']
        with self.load_lock:
            em = request['emulator']
            pid = em.pid
            try:
                return self._pine_load(request, record, pid)
            except BaseException:
                # A rejected paused plan may have applied only part of a batch.
                # Stop this owned VM; never resume or switch to another path.
                if record['plan'] is not None and em.pid == pid and em.pine_owner() == pid:
                    em.stop()
                raise

    def _pine_load(self, request, record, pid):
        self._check_load_current(request)
        link = self.link
        em = request['emulator']
        if em.pine_owner() != pid or pid != getattr(link, 'pid', pid):
            raise ValueError('The match load PINE owner changed.')
        if record['plan'] is not None:
            if record['epoch'] != request['epoch'] or kit_match.sha256_file(record['path']) != record['sha']:
                raise ValueError('The common Retry archive/epoch guard changed.')
            if not em.ensure_paused(link):
                raise ValueError('The common match cannot be loaded into an unpaused VM.')
        link.w32(LOAD_SENTINEL, kit_postmatch.LOADING)
        t0 = time.time()
        link.load_state(REMATCH_SLOT)
        while True:
            self._check_load_current(request)
            try:
                if link.u32(LOAD_SENTINEL) != kit_postmatch.LOADING:
                    break
            except (OSError, RuntimeError):
                pass
            if time.time() - t0 > 60:
                raise KitError('TTM-NET-22', what='PCSX2 did not load the match (PINE load of slot 241).',
                               logs=str(self.run_dir))
            time.sleep(0.005)
        self._check_load_current(request)
        if record['plan'] is not None:
            self._apply_load_plan(request, record, link, pid)
        self._check_load_current(request)
        resumed = em.ensure_running(link)
        self._check_load_current(request)
        if record['plan'] is not None and not resumed:
            raise ValueError('The guarded initial match did not resume after its machine words were verified.')
        return round(time.time() - t0, 3)

    # ---- the fight --------------------------------------------------------------------------------------------------------
    def new_session(self, late):
        self.fight_no += 1
        self.files = dict(hashes=open(self.run_dir / f'hashes-fight{self.fight_no}.jsonl', 'a', encoding='utf-8'),
                          events=open(self.run_dir / 'session.jsonl', 'a', encoding='utf-8'))
        m = self.match
        common = dict(slot=self.my_slot(), mask=m['mask'] or 1, delay=m['delay'], state_sha=m['sha'],
                      epoch=self.epoch, name=self.my_name()[:16], log=self.files['events'],
                      hash_log=self.files['hashes'], linger=4.0, sched=True,
                      startup_started_at=self.startup_started_at)
        if self.role == 'host':
            self.start_cpu_pending = []
            members = [(k, m['seats'].get(k), self.lobby.members.get(k, {}).get('name', ''))
                       for k in sorted(self.loaded) if k in self.members]
            self.session = kit_lockstep.Hub(self.link, self.udp, members=members, member=self.me, **common)
            if not m['mask']:
                self.session.drop_slot(0, m['delay'])        # nobody plays: slot 0 is neutral (host-fed)
            for k in m['seats']:
                if k != self.me and k not in self.loaded:     # a player that left before the start
                    self.session.drop_slot(m['seats'][k], m['delay'])
                    if (m.get('spec') or {}).get('type') != 'hub':
                        self.start_cpu_pending.append(k)
        else:
            self.session = kit_lockstep.Client(self.link, self.udp, member=self.me, **common)
            self.session.bulk_ready = self.bulk_ready
        self.fight = dict(no=self.fight_no, epoch=self.epoch, title=m['title'], spec_sha=m['spec_sha'], sha=m['sha'],
                          delay=m['delay'], slot=self.my_slot(), started=time.time(), resyncs={}, late=late)
        self.nocontest = None
        self.freeze_watch = None
        self.emu_watch = None
        try:
            import kit_emu
            self.emu_watch = kit_emu.EmulatorWatch(self.emulator)
        except Exception:  # noqa: BLE001 - a watch that cannot start never stops a fight
            self.emu_watch = None

    def begin_fight(self, late):
        self.new_session(late)
        self.waiting_late = time.time() if late else None
        if not late:
            self.session.attach()
        self.set_phase('fight')
        if not late:
            self.start_missing_cpus()
        if self.role == 'host':
            self.lobby.phase = 'fight'
            self.lobby.vote = None
            self.lobby.bump()
            self.broadcast()
            if self.prep is not None and self.prep.state == 'warm' and \
                    not any(self.busy(n) for n in ('prep', 'prebuild', 'warm', 'suspend')):
                self.job('suspend', self.prep.suspend, then=self.prep_suspended, fail=lambda e: None)
            for ident in self.members:                       # members outside this match watch it from now on
                if ident not in self.loaded and ident not in self.join_pending:
                    self.join_pending[ident] = now() + 3.0
        self.emulator.front()
        if self.args.bots is not None and self.args.hidden and self.my_slot() is not None:
            self.start_bot()
        self.vote = None
        self.vote_state = None
        self.results = None
        if self.rematch_copy is None or self.rematch_copy.get('epoch') != self.epoch:
            request = self.load_request()
            self.job('copy', self.build_copy, request,
                     then=lambda result, r=request: self.copy_ready(result) if self.load_current(r) else None,
                     fail=lambda e, r=request: self.say(f'retry copy: {e}') if self.load_current(r) else None)
        self.say(f'Fight {self.fight_no} (epoch {self.epoch}) starts'
                 f'{"" if self.my_slot() is None else f", you play slot {self.my_slot()}"}.')

    def copy_ready(self, copy):
        if self.load_current(copy['request']):
            self.rematch_copy = copy

    # ---- host services (kit_services) ------------------------------------------------------------------------------
    def wants_service(self):
        services = ((self.match or {}).get('spec') or {}).get('services') or {}
        return any(services.get(k) for k in ('cpu_transform', 'body_change'))

    def start_service(self):
        """Host: the fighter-update service of this fight (the installation copy's Python and tools)."""
        import kit_services
        import netplay_core as nc
        if self.prep is None:
            self.say('Host services: this PC has no match-making copy; the fight runs without them.')
            return
        base = self.prep.base
        log = self.run_dir / f'service-fight{self.fight_no}.txt' if self.run_dir else None
        try:
            services = ((self.match or {}).get('spec') or {}).get('services') or {}
            on = tuple(k for k in ('cpu_transform', 'body_change') if services.get(k))
            self.service = kit_services.Broker(self, base.python(), base.dest / 'game' / 'tools', nc.w_entry(1), log,
                                               on)
            self.say(f'Host services started ({", ".join(on)}; log {log}).')
        except OSError as error:
            self.say(f'Host services could not start: {error}')

    def tick_service(self):
        if self.service is None:
            if self.session is not None and self.wants_service() and getattr(self, 'service_fight', None) != \
                    self.fight_no and self.session.control and self.session.control.get('state') == 2:
                self.service_fight = self.fight_no
                self.start_service()
            return
        self.service.poll()
        if self.service.failed:
            why = self.service.failed
            self.stop_service()
            if self.phase == 'fight' and self.session is not None and self.session.result is None:
                self.say(f'Host services failed ({why}): the fight ends as No contest.')
                self.end_fight('service', mine=True)

    def stop_service(self):
        if self.service is not None:
            self.say(f'Host services: {self.service.stats}')
            self.service.stop()
            self.service = None

    def msg_BULK(self, ident, m):
        if self.role != 'guest' or self.session is None:
            return
        import kit_services
        if self.guest_bulk is None:
            self.guest_bulk = kit_services.GuestBulk()
        if not self.guest_bulk.add(m):
            self.say('(ignored a malformed BULK from the host)')

    def bulk_ready(self, seq):
        """Guest (kit 2.1): a SCHED entry that needs host-service bulk `seq` waits until this PC wrote it."""
        return self.guest_bulk is not None and self.guest_bulk.ready(seq)

    def msg_BULK_ACK(self, ident, m):
        if self.role == 'host' and self.service is not None:
            try:
                self.service.on_ack(ident, int(m.get('seq')))
            except (TypeError, ValueError):
                pass

    def tick_phase(self):
        self.tick_hub_return()
        if self.resync is not None and self.session is None:
            self.step_guest_resync()                         # a join: no session yet
            return True
        if self.phase == 'fight' and self.session is not None:
            self.tick_fight()
            return True
        if self.phase == 'results':
            self.tick_results()
            return False
        if self.phase == 'loading' and self.role == 'host':
            self.check_go()
        return self.phase in ('loading', 'sending')

    def tick_fight(self):
        s = self.session
        if self.waiting_late is not None:
            c = self.link.control()
            try:
                s.attach()
                self.waiting_late = None
                self.start_missing_cpus()
            except RuntimeError:
                if time.time() - self.waiting_late > 60:
                    self.waiting_late = None
                    self.fail(KitError('TTM-NET-22', what=f'the loaded match did not start: {c}',
                                       logs=str(self.run_dir)))
                    self.end_fight('error', mine=True)
                return
        if self.role == 'host':
            if self.hub_state is None and ((self.match or {}).get('spec') or {}).get('type') == 'hub':
                self.hub_begin()
            self.host_fight_steps()
            self.tick_hub()
            self.tick_service()
        elif self.guest_bulk is not None and self.guest_bulk.waiting:
            c = self.session.control or {}
            self.guest_bulk.tick(self.link, c.get('frame'), self.send)
        elif self.resync is not None:
            self.step_guest_resync()
        try:
            result = s.tick()
        except (OSError, RuntimeError) as error:
            s.event('emulator_gone', error=f'{type(error).__name__}: {error}')
            self.say('The game window was closed.')
            self.my_game_closed()
            return
        st = s.control or {}
        startup = getattr(s, 'startup_seconds', None)
        if startup is not None and self.fight is not None and 'startup_seconds' not in self.fight:
            self.fight['startup_seconds'] = startup
            self.say(f'Combat is interactive ({startup:.1f} s from Start, including the introduction).')
        if st.get('waiting') and st.get('stall_now', 0) > STALL_BANNER * 60 and not self.resync and not self.resyncs:
            if self.overlay is None or self.overlay.get('key') != 'fight.stall':
                self.show_overlay('fight.stall')
        elif self.overlay and self.overlay.get('key') == 'fight.stall':
            self.hide_overlay()
        if self.watch_freeze(st):
            return
        self.watch_emulator(st)
        self.watch_spectator_view()
        t = now()
        if t - getattr(self, 'last_status', 0) >= 0.5:
            self.last_status = t
            self.dirty = True
        if result != 'running':
            self.finish_fight(result)

    # ---- host: resync, joins, departures ------------------------------------------------------------------------------
    def resync_ctx(self):
        ctl = self

        class Ctx:
            hub = ctl.session
            link = ctl.link
            sstates = ctl.emulator.root / 'sstates'

            @staticmethod
            def send(member, message):
                if not ctl.send_to(member, **message):
                    raise OSError('the connection is closed')

            @staticmethod
            def send_file(member, path):
                m = ctl.members.get(member)
                if m is None:
                    raise OSError('the member left')
                ch = m['channel']
                ch.transfers += 1
                try:
                    with open(path, 'rb') as f:
                        for chunk in iter(lambda: f.read(kit_net.CHUNK), b''):
                            ch.send_chunk(chunk)
                            if ctl.args.send_rate:
                                time.sleep(len(chunk) / (ctl.args.send_rate * 1000.0))
                    ch.send_json(type='END', sha256=kit_resync.sha256(path), size=Path(path).stat().st_size)
                finally:
                    ch.transfers = max(0, ch.transfers - 1)

            @staticmethod
            def alive():
                return ctl.emulator.alive()

            @staticmethod
            def log(text):
                ctl.say(text)
        return Ctx

    def host_fight_steps(self):
        hub = self.session
        for ident, worker in list(self.resyncs.items()):
            state = worker.step()
            if state == 'done':
                self.fight['resyncs'][str(ident)] = self.fight['resyncs'].get(str(ident), 0) + \
                    (0 if worker.reason == 'join' else 1)
                del self.resyncs[ident]
                if not self.resyncs:
                    self.hide_overlay()
            elif state == 'failed':
                del self.resyncs[ident]
                self.say(f'Bringing member {ident} back failed: {worker.error}')
                if ident in hub.members:
                    hub.remove_member(ident)
                self.send_to(ident, type='LEFT_FIGHT', why='resync_failed')
                self.hide_overlay()
        if hub.decided is None and not self.resyncs:
            for ident in hub.members_needing_resync():
                done = self.fight['resyncs'].get(str(ident), 0)
                if done >= kit_resync.MAX_RESYNCS:
                    self.say(f'Member {ident}\'s game differed again after {done} resyncs: it leaves this fight.')
                    hub.remove_member(ident)
                    self.send_to(ident, type='LEFT_FIGHT', why='resync_limit')
                    continue
                self.start_host_resync([ident], f'its game differs at frame {hub.members[ident].compare.desync}')
                break
        t = now()
        for ident, at in list(self.join_pending.items()):
            if ident not in self.members:
                del self.join_pending[ident]
            elif t >= at and not self.resyncs and hub.decided is None and (hub.control or {}).get('state') == 2:
                del self.join_pending[ident]
                self.join_running(ident)

    def start_host_resync(self, targets, reason):
        hub = self.session
        players = [t for t in targets if hub.members.get(t) is not None and hub.members[t].slot is not None]
        worker = kit_resync.HostResync(self.resync_ctx(), targets, reason, self.epoch, hold=bool(players))
        for t in targets:
            self.resyncs[t] = worker
        if players:
            self.show_overlay('fight.resync', n=1)
            self.emulator.flash()
        self.say(f'Re-synchronizing {targets} ({reason}).')

    def join_running(self, ident):
        """A member outside this match watches it from now on: JOINFIGHT, then the host's game (no hold)."""
        m = self.match
        hub = self.session
        if ident in hub.members:
            return
        hub.add_member(ident, None, self.lobby.members.get(ident, {}).get('name', ''))
        self.send_to(ident, type='JOINFIGHT', epoch=self.epoch, spec=m['spec'], spec_sha=m['spec_sha'],
                     title=m['title'], delay=m['delay'], sha256=m['sha'], pnach=m['pnach'],
                     seats={str(k): v for k, v in m['seats'].items()})
        self.start_host_resync([ident], 'join')

    def member_joined_during_match(self, ident):
        if self.phase == 'fight' and self.session is not None and self.role == 'host':
            self.join_pending[ident] = now() + 2.0

    def member_left_match(self, ident):
        """Host: a member left the room during a match: a player's fighter becomes a CPU at a scheduled frame
        (drop_to_cpu; neutral input until then)."""
        self.join_pending.pop(ident, None)
        self.loaded.discard(ident)
        if self.session is not None and self.role == 'host' and ident in self.session.members:
            self.session.remove_member(ident)
            self.drop_to_cpu(ident)
        worker = self.resyncs.pop(ident, None)
        if worker is not None and self.session is not None and self.session.hold_at is not None:
            self.session.release()
        if self.vote is not None and self.vote.drop(ident):
            self.publish_vote()
        self.hub_member_left(ident)
        if self.service is not None:
            self.service.member_gone(ident)
        if self.match and ident in self.match.get('seats', {}) and self.phase in ('sending', 'loading'):
            self.check_go()

    def msg_LEFT_FIGHT(self, ident, m):
        if self.role == 'host':
            self.say(f'{self.lobby.members.get(ident, {}).get("name", ident)} left the fight ({m.get("why")}).')
            if self.session is not None and ident in self.session.members:
                self.session.remove_member(ident)
                self.drop_to_cpu(ident)
            if self.vote is not None and self.vote.drop(ident):
                self.publish_vote()
            self.hub_member_left(ident)
            return
        # guest: the host took this PC out of the fight
        self.say(f'You left the fight ({m.get("why")}).')
        if self.session is not None:
            self.abort_game()
        self.leave_match_state()
        self.set_phase('lobby')

    def drop_to_cpu(self, ident):
        """Host (kit 2.1): the fighter of a player who left becomes a CPU on every PC at one scheduled frame K: its
        seat := none, its slot leaves the core's mask (nobody waits for it after K; the host feeds it neutral input
        until then), the actor's CPU flag := 1 and its pad words cleared, as the mod's takeover does; a side leader's
        human takeover port is closed too. Not in the hub (it parks the fighter instead)."""
        import netplay_core as nc
        slot = (self.match or {}).get('seats', {}).get(ident)
        spec = (self.match or {}).get('spec') or {}
        if slot is None or spec.get('type') == 'hub' or self.session is None or not getattr(self.session, 'sched_on',
                                                                                              False):
            return False
        try:
            import struct
            import kit_verify
            actor = struct.unpack('<I', self.link.read(kit_verify.POINTERS + 4 * slot, 4))[0]
            if not 0x100000 <= actor < 0x8000000 - 0x1300:
                raise ValueError('the fighter pointer is not valid')
            writes = [(nc.SEAT_CONTROL + nc.SF['seats'] + 4 * slot, nc.NO_SLOT, 0xFFFFFFFF),
                      (nc.CONTROL + nc.F['mask'], 0, 1 << slot)]
            # The prepared checkpoint may still have the intro/start gate armed. Its saved assignment
            # must agree too, or the gate can restore human control after our CPU write.
            import team_start_gate as gate
            gate_actor = struct.unpack('<I', self.link.read(gate.CONTROL + 0x80 + 4 * slot, 4))[0]
            if gate_actor == actor:
                writes.append((gate.CONTROL + 0x40 + 4 * slot, 1, 0xFFFFFFFF))
            if 0x100000 <= actor < 0x8000000 - 0x1300:
                writes += [(actor + 0x1278, 1, 0xFFFFFFFF), (actor + 0x127C, 0, 0xFFFFFFFF),
                           (actor + 0x1280, 0, 0xFFFFFFFF), (actor + 0x1284, 0, 0xFFFFFFFF)]
            if slot < 2:
                import kit_prepare
                writes.append((kit_prepare.SPECTATOR + kit_prepare.HUMAN_PORTS, 0, 1 << slot))
            seq, k = self.session.schedule(writes)
            self.say(f'Slot {slot}\'s player left: its fighter is a CPU from frame {k} (entry {seq}).')
            self.summary.setdefault('dropped', []).append(dict(member=ident, slot=slot, frame=k))
            return True
        except Exception as error:  # noqa: BLE001 - the fighter then idles (neutral input), as before
            self.say(f'Slot {slot}\'s fighter could not be made a CPU ({type(error).__name__}: {error}); it idles.')
            return False

    def start_missing_cpus(self):
        """Schedule the same CPU handoff on every PC, including a rematch of the original checkpoint."""
        if self.role != 'host':
            return
        for ident in list(self.start_cpu_pending):
            if not self.drop_to_cpu(ident):
                self.end_fight('error', mine=True)
                raise KitError('TTM-NET-22', what='A missing player\'s fighter could not be switched to CPU safely.')
            self.start_cpu_pending.remove(ident)

    def cmd_leave_match(self, c):
        """A guest leaves the running fight (it stays in the room)."""
        if self.role != 'guest' or self.phase not in ('fight', 'loading', 'results'):
            return
        self.send(type='LEFT_FIGHT', why='left')
        if self.session is not None:
            self.abort_game()
        self.leave_match_state()
        self.set_phase('lobby')

    def my_game_closed(self):
        if self.role == 'host':
            self.end_fight('host_closed', mine=True)
        else:
            self.send(type='LEFT_FIGHT', why='closed its game')
            self.leave_match_state()
            self.set_phase('lobby')

    # ---- guest: resync and join -------------------------------------------------------------------------------------------
    def guest_ctx(self):
        ctl = self

        class Ctx:
            client = ctl.session
            link = ctl.link
            sstates = ctl.emulator.root / 'sstates'
            tmp_dir = None

            @staticmethod
            def machine(src, dst):
                kit_match.machine_copy(src, dst, ctl.my_slot(), ctl.watch_side, ctl.profile.get('local'), 0)

            @staticmethod
            def send(message):
                ctl.send(**message)

            @staticmethod
            def log(text):
                ctl.say(text)

            @staticmethod
            def ensure_running():
                return ctl.emulator.ensure_running(ctl.link)

            @staticmethod
            def launch(path):
                return ctl.launch_join(path)
        return Ctx

    def msg_RESYNC(self, ident, m):
        if self.role != 'guest' or self.resync is not None:
            return
        try:
            if int(m['epoch']) != self.epoch or int(m['K']) < 0 or not 0 < int(m['size']) <= 512 << 20:
                raise ValueError('a field is out of range')
            self.resync = kit_resync.GuestResync(self.guest_ctx(), m)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            self.say(f'The host\'s RESYNC message is malformed ({error}).')
            self.send(type='LEFT_FIGHT', why='bad resync')
            return
        if m.get('reason') != 'join':
            self.show_overlay('fight.resync', n=1, mb=round(m.get('size', 0) / 1e6, 1))
        self.say(f'Taking the host\'s game ({m.get("size", 0) / 1e6:.1f} MB; {m.get("reason")}).')

    def step_guest_resync(self):
        r = self.resync
        state = r.step()
        if state == 'done':
            self.resync = None
            self.hide_overlay()
            if self.session is None or self.phase != 'fight':
                self.session = r.ctx.client
                self.link = r.link or self.link
                self.set_phase('fight')
                self.emulator.front()
        elif state == 'failed':
            self.resync = None
            self.hide_overlay()
            self.send(type='LEFT_FIGHT', why=f'resync failed: {r.error}')
            self.leave_match_state()
            self.set_phase('lobby')

    def msg_JOINFIGHT(self, ident, m):
        """Guest: a fight runs: watch it now (the host's game follows as RESYNC)."""
        if self.role != 'guest':
            return
        try:
            import kit_controller
            kit_spec.validate(m.get('spec'), self.local['view'], kit_controller.ALLOWED_SERVICES)
        except KitError as error:
            self.say(f'The running match cannot be watched here: {error}')
            return
        self.epoch = int(m['epoch'])
        spec = m['spec']
        self.match = dict(spec=spec, spec_sha=m['spec_sha'], title=m.get('title'), sha=m['sha256'],
                          delay=int(m['delay']), pnach=m['pnach'], slot=None, epoch=self.epoch,
                          seats={int(k): v for k, v in (m.get('seats') or {}).items()},
                          mask=kit_spec.slot_mask(spec))
        self.watch_side = 0
        if self.session is not None:
            self.abort_game()
        self.session = None
        self.say(f'A match is running: you watch it now ({self.match["title"]}).')
        self.set_phase('loading')
        self.progress = dict(step='load.join', pct=0)

    def launch_join(self, path):
        """(worker) A new PCSX2 with the host's state, and the Client of this PC (watching)."""
        from pinelink import nc, PineLink
        em = self.emulator
        if em.pid and em.alive():
            em.stop()
        self.link = None
        em.install_pnach(self.match['pnach'])
        pid = em.launch(path, self.local['iso'], fullscreen=bool(self.cfg.get('fullscreen')))
        self.remember_pid(pid)
        em.wait_ready(nc.CONTROL, nc.MAGIC, timeout=max(self.args.timeout, 120))
        em.place()
        link = PineLink(self.args.pine_slot, pid, owner=em.pine_owner).connect()
        em.link = link
        self.link = link
        self.fight_no += 1
        self.files = dict(hashes=open(self.run_dir / f'hashes-fight{self.fight_no}.jsonl', 'a', encoding='utf-8'),
                          events=open(self.run_dir / 'session.jsonl', 'a', encoding='utf-8'))
        m = self.match
        client = kit_lockstep.Client(link, self.udp, member=self.me, slot=None, mask=m['mask'] or 1,
                                     delay=m['delay'], state_sha=m['sha'], epoch=self.epoch,
                                     name=self.my_name()[:16], log=self.files['events'],
                                     hash_log=self.files['hashes'], linger=4.0, sched=True)
        client.started_at = client.clock()
        client.bulk_ready = self.bulk_ready
        self.fight = dict(no=self.fight_no, epoch=self.epoch, title=m['title'], joined=True, started=time.time(),
                          resyncs={}, slot=None)
        return link, client

    # ---- watches ---------------------------------------------------------------------------------------------------------
    def watch_emulator(self, st):
        """The emulator-settings policy during a fight (kit_emu module text): a paused game window is resumed, a
        changed settings file or a new per-game file is reported (it changes nothing until PCSX2 starts again)."""
        t = now()
        if t - self.last_watch < WATCH_EVERY:
            return
        self.last_watch = t
        if self.resync is not None or self.resyncs or self.waiting_late is not None:
            return
        status = self.emulator.vm_status(self.link) if self.emulator else None
        if status == 'paused' and st.get('state') == 2:
            self.say('The game window was paused during the fight: resuming it (the other PCs wait meanwhile).')
            self.note('notice.unpaused')
            self.emulator.ensure_running(self.link)
        if self.emu_watch is not None:
            for change in self.emu_watch.changes():
                self.say(f'Emulator settings changed during the fight: {change}. Nothing changes in this fight; the '
                         'kit writes its own settings back when PCSX2 starts again.')
                self.note('notice.settings_changed', what=change)

    def watch_spectator_view(self):
        """A spectator switches the side it watches with its own pad (L1 / R1): render only (netplay_view's watch
        word), never sent anywhere."""
        if self.my_slot() is not None or self.link is None:
            return
        t = now()
        if t - getattr(self, 'last_view_poll', 0) < 0.1:
            return
        self.last_view_poll = t
        try:
            import netplay_core as nc
            c = self.session.control or {}
            found = self.link.outgoing(max(0, c.get('frame', 0)), c.get('frame', 0) + self.match['delay'])
        except (OSError, RuntimeError, AttributeError):
            return
        if not found:
            return
        raw = found[max(found)][0]
        held = (~(raw[0] | raw[1] << 8)) & 0xFFFF
        side = 0 if held & 0x0400 else 1 if held & 0x0800 else None       # L1 / R1
        if side is not None and side != self.watch_side:
            self.cmd_watch(dict(side=side))

    def cmd_watch(self, c):
        """Which side a spectator watches (0 / 1): netplay_view's watch word in this PC's game only."""
        side = c.get('side')
        if side not in (0, 1) or self.my_slot() is not None:
            return
        self.watch_side = side
        if self.link is not None:
            try:
                import netplay_view as nv
                self.link.w32(nv.CONTROL + nv.F['watch'], side)
            except (OSError, RuntimeError):
                pass
        self.dirty = True

    def watch_freeze(self, st):
        """The game itself stopped (not the connection): RUNNING, not waiting, the emulator not paused, the frame not
        moving for FREEZE_REPORT s. Host: after FREEZE_END more seconds the fight ends as No contest."""
        frame = st.get('frame')
        if st.get('state') != 2 or st.get('waiting') or frame is None or self.resync is not None or self.resyncs or \
                self.session is None or self.session.decided is not None:
            self.freeze_watch = None
            return False
        w, t = self.freeze_watch, now()
        if w is None or w['frame'] != frame:
            if w is not None and w.get('reported') and self.overlay and self.overlay.get('key') == 'fight.frozen':
                self.hide_overlay()
            self.freeze_watch = dict(frame=frame, since=t, reported=False)
            return False
        if not w['reported'] and t - w['since'] >= FREEZE_REPORT:
            if self.emulator.vm_status(self.link) == 'paused':
                w['since'] = t
                return False
            w['reported'] = True
            self.fight['frozen'] = dict(frame=frame)
            self.say(f'The game has not moved for {FREEZE_REPORT:.0f} s at frame {frame}: the game itself stopped.')
            self.show_overlay('fight.frozen', frame=frame, seconds=int(FREEZE_END))
            self.job('freeze', self.freeze_capture, frame, self.fight_no, then=lambda i: None,
                     fail=lambda e: self.say(f'The frozen game could not be saved: {e}'))
            return False
        if self.role == 'host' and w['reported'] and not w.get('ended') and t - w['since'] >= FREEZE_REPORT + FREEZE_END:
            w['ended'] = True
            self.end_fight('frozen', mine=True)
            return True
        return False

    def freeze_capture(self, frame, fight_no):
        path = self.emulator.state_file(FREEZE_SLOT)
        before = path.stat().st_mtime_ns if path.exists() else None
        self.link.save_state(FREEZE_SLOT)
        kit_resync.wait_file(path, before, timeout=60)
        target = self.run_dir / f'frozen-fight{fight_no}-frame{frame}.p2s'
        shutil.copyfile(path, target)
        try:
            path.unlink()
        except OSError:
            pass
        return str(target)

    # ---- the end ----------------------------------------------------------------------------------------------------------
    def cmd_end_fight(self, c):
        if self.role == 'host' and self.phase in ('fight', 'loading') and self.session is not None:
            self.end_fight('host', mine=True)
        elif self.role == 'guest':
            self.cmd_leave_match(c)

    def msg_END_FIGHT(self, ident, m):
        if self.role == 'guest' and self.session is not None and self.phase in ('fight', 'loading'):
            self.end_fight(m.get('why') or 'host', mine=False)

    def end_fight(self, why, mine):
        if mine and self.role == 'host':
            self.send(type='END_FIGHT', epoch=self.epoch, why=why)
        self.nocontest = why
        self.say(f'The fight ends as No contest ({why}).')
        self.abort_game()
        self.finish_fight('nocontest')

    def abort_game(self):
        if self.link is None:
            return
        try:
            self.link.abort()
        except (OSError, RuntimeError):
            pass
        if self.session is not None and self.session.result is None:
            try:
                self.session.say_bye()
            except OSError:
                pass
            self.session.result = 'aborted'
        try:
            self.emulator.ensure_paused(self.link)
        except (OSError, RuntimeError):
            pass

    def finish_fight(self, result):
        s = self.session
        self.stop_service()
        self.guest_bulk = None
        self.stop_bot()
        self.hide_overlay()
        self.resync = None
        self.resyncs = {}
        decided = s.decided if s else None
        how, winner, words = 'nocontest', 0, [0, 0]
        if result == 'decided' and decided:
            try:
                words = list(kit_postmatch.read_words(self.link))
            except (OSError, RuntimeError):
                words = [decided.get('result') or 0, 0]
            how = kit_postmatch.how_of(decided.get('result'), words[1])
            winner = (decided.get('result') or 0) & 0x1F
        summary = s.summary() if s else {}
        record = dict({k: v for k, v in (self.fight or {}).items() if k != 'started'}, result=result, how=how,
                      winner=winner, words=words, decided=decided, session=summary, nocontest=self.nocontest,
                      seconds=round(time.time() - (self.fight or {}).get('started', time.time()), 1))
        self.summary.setdefault('fights', []).append(record)
        self.write_summary()
        for f in (self.files or {}).values():
            try:
                f.close()
            except OSError:
                pass
        self.files = {}
        self.session = None
        if self.role == 'host':
            members = summary.get('members') or {}
            compared = sum(v.get('compared') or 0 for v in members.values())
            differing = sum(v.get('differing') or 0 for v in members.values())
            per = ', '.join(f'member {k}: {v.get("compared")} compared, {v.get("differing")} differing'
                            for k, v in members.items())
            self.say(f'State check: {compared} member frames compared, {differing} differing ({per}).')
            message = kit_postmatch.result_message(self.epoch, winner=winner, how=how, words_=words,
                                                   frame=(decided or {}).get('frame'), seconds=record['seconds'],
                                                   compared=compared, differing=differing,
                                                   resyncs=sum(self.fight.get('resyncs', {}).values())
                                                   if self.fight else 0, title=(self.match or {}).get('title'))
            message['nocontest'] = self.nocontest
            self.results = dict(message, members=members)
            self.send(**message)
            self.hub_state = None
            if self.hub_after_fight():
                return
            players = [k for k in (self.match or {}).get('seats', {}) if k == self.me or k in self.members]
            self.vote = kit_postmatch.Vote(self.epoch, players, now())
            self.lobby.phase = 'results'
            self.lobby.vote = self.vote.state(now())
            self.lobby.bump()
            self.broadcast()
            self.send(type='VOTE_STATE', **self.vote.state(now()))
        else:
            self.results = dict(how=how, winner=winner, words=words, frame=(decided or {}).get('frame'),
                                seconds=record['seconds'], title=(self.match or {}).get('title'),
                                nocontest=self.nocontest, mine=summary)
        self.set_phase('results')

    def msg_RESULT(self, ident, m):
        if self.role != 'guest':
            return
        mine = (self.results or {}).get('mine')
        self.results = dict({k: v for k, v in m.items() if k != 'type'}, mine=mine)
        if self.phase in ('fight', 'loading'):
            self.say('The host decided the fight.')
            if self.session is not None and self.session.result is None:
                self.finish_fight('decided' if m.get('how') != 'nocontest' else 'nocontest')
                self.results = dict({k: v for k, v in m.items() if k != 'type'}, mine=self.results.get('mine'))
        self.dirty = True

    # ---- the vote ---------------------------------------------------------------------------------------------------------
    def cmd_vote(self, c):
        choice = c.get('choice')
        if choice not in kit_postmatch.CHOICES or self.phase != 'results':
            return
        if self.role == 'host':
            self.msg_VOTE(self.me, dict(epoch=self.epoch, choice=choice))
        else:
            self.send(type='VOTE', epoch=self.epoch, choice=choice)

    def msg_VOTE(self, ident, m):
        if self.role != 'host' or self.vote is None or int(m.get('epoch', -1)) != self.vote.epoch:
            return
        if self.vote.cast(ident, m.get('choice'), now()):
            self.publish_vote()

    def publish_vote(self):
        state = self.vote.state(now())
        self.lobby.vote = state
        self.send(type='VOTE_STATE', **state)
        self.dirty = True
        if self.vote.decision is not None:
            decision = self.vote.decision
            self.say(f'Vote: {decision}.')
            if decision == 'retry':
                self.epoch += 1
                self.send(type='RETRY', epoch=self.epoch)
                self.start_retry()
            else:
                self.send(type='TO_LOBBY', why='vote')
                self.back_to_lobby()

    def tick_results(self):
        if self.role != 'host' or self.vote is None:
            return
        t = now()
        if self.vote.tick(t):
            self.publish_vote()
        elif self.vote.decision is None and t - getattr(self, 'last_vote_sent', 0) >= 1.0:
            self.last_vote_sent = t
            self.lobby.vote = self.vote.state(t)
            self.send(type='VOTE_STATE', **self.lobby.vote)
            self.dirty = True

    def msg_VOTE_STATE(self, ident, m):
        if self.role == 'guest':
            self.vote_state = {k: v for k, v in m.items() if k != 'type'}
            self.dirty = True

    def msg_RETRY(self, ident, m):
        if self.role != 'guest' or not self.match:
            return
        self.epoch = int(m.get('epoch') or self.epoch + 1)
        self.start_retry()

    def start_retry(self):
        """Every PC: its own copy of the same match again, PINE-loaded into the running PCSX2 (late attach)."""
        self.startup_started_at = time.perf_counter()
        self.vote = None
        self.vote_state = None
        self.results = None
        self.hide_overlay()
        self.match['epoch'] = self.epoch
        self.load_generation += 1
        if self.role == 'host':
            self.loaded = {k for k in self.loaded if k in self.members}
            self.lobby.phase = 'loading'
            self.lobby.vote = None
            self.lobby.bump()
            self.broadcast()
        if not (self.emulator and self.emulator.alive() and self.link is not None):
            self.say('This PC\'s game window is closed: it waits in the lobby.')
            self.leave_match_state()
            self.set_phase('lobby')
            return
        self.set_phase('loading')
        self.load_mode = 'pine'
        self.progress = dict(step='load.retry', pct=0)
        request = self.load_request()
        if self.rematch_copy is not None and self.rematch_copy.get('plan') is None:
            self.rematch_copy = dict(self.rematch_copy, epoch=self.epoch, request=request)
            self.schedule_pine_load(self.rematch_copy)
        else:
            # Recompute the guards from the immutable common archive for this
            # new owner epoch/profile. The already verified file is reused.
            self.job('copy', self.build_copy, request,
                     then=lambda result, r=request: self.retry_copy_built(result) if self.load_current(r) else None,
                     fail=lambda error, r=request: self.load_failed(error) if self.load_current(r) else None)

    def retry_copy_built(self, copy):
        if not self.load_current(copy['request']):
            return
        self.rematch_copy = copy
        self.schedule_pine_load(copy)

    def msg_TO_LOBBY(self, ident, m):
        if self.role == 'guest':
            self.back_to_lobby()

    def back_to_lobby(self):
        """Every PC: back to the lobby (teams and claims kept, Ready cleared); PCSX2 paused and minimised."""
        self.cancel_prebuild(cancel_running=True)
        self.stop_bot()
        self.hide_overlay()
        if self.session is not None:
            self.abort_game()
        self.leave_match_state(keep_match=True)
        self.to_background()
        if self.role == 'host' and self.lobby:
            if self.prep is not None and self.busy('prep'):
                self.prep.cancel.set()
            self.lobby.phase = 'lobby'
            self.lobby.vote = None
            self.lobby.clear_ready()
            self.lobby.bump()
            self.broadcast()
            self.rewarm_if_cold()
        self.set_phase('lobby')

    def leave_match_state(self, keep_match=False):
        self.load_generation += 1
        manager = (getattr(self, 'local', None) or {}).get('wire')
        if manager is not None and hasattr(manager, 'discard_snapshot'):
            manager.discard_snapshot()
        if hasattr(self, 'cancel_transfers'):
            self.cancel_transfers()
        self.stop_prefetch_receive()
        self.pending_preboot_load = False
        self.stop_receive()
        self.session = None
        self.resync = None
        self.resyncs = {}
        self.results = None
        self.vote = None
        self.vote_state = None
        self.progress = None
        self.go = False
        self.join_pending = {}
        self.start_cpu_pending = []
        if not keep_match:
            self.match = None
            self.rematch_copy = None
        for f in (self.files or {}).values():
            try:
                f.close()
            except OSError:
                pass
        self.files = {}

    def to_background(self):
        if self.emulator and self.emulator.pid and self.emulator.alive() and self.link is not None:
            try:
                self.emulator.ensure_paused(self.link)
            except (OSError, RuntimeError):
                pass
            self.emulator.minimise()

    # ---- bots and test hooks -------------------------------------------------------------------------------------------
    def start_bot(self):
        import keypad
        self.stop_bot()
        seed = int(self.args.bots) + 101 * self.fight_no + 7 * (self.me or 0)
        self.bot = keypad.KeyPlayer(self.emulator, self.role, 30000, seed, self.args.bot_profile,
                                    log=self.run_dir / f'bot-keys-fight{self.fight_no}.json')
        self.bot.start()
        self.bot.go.set()

    def stop_bot(self):
        if self.bot is not None:
            self.bot.stop()
            self.bot = None

    def cmd_bots(self, c):
        if not self.args.test_hooks:
            return
        if c.get('on') and self.phase == 'fight':
            self.start_bot()
        else:
            self.stop_bot()

    def cmd_test_inject(self, c):
        """Test only: make THIS PC's game differ on purpose (a desync to recover from)."""
        if not self.args.test_hooks or self.link is None:
            return
        what = c.get('what', 'hp')
        u = self.link.u32
        if what == 'hp':
            actor = u(0xD8040 + 4 * int(c.get('fighter', 1)))
            slot = u(actor + 0x994)
            addr = actor + 0x9E4 + min(slot, 4) * 0xA4
            hp = u(addr)
            new = max(1, hp - int(c.get('amount', 1500)))
            self.link.w32(addr, new)
            self.say(f'TEST: fighter {c.get("fighter", 1)} HP {hp} -> {new} on this PC only')
        elif what == 'rand':
            from native_map import A
            impure = u(A(0x2E9808))
            self.link.w32(impure + 168, u(impure + 168) ^ 0x1234567)
            self.say('TEST: newlib rand state changed on this PC only')

    def cmd_test_key(self, c):
        if not self.args.test_hooks or not self.emulator or not self.emulator.pid:
            return
        import kit_emu
        key = kit_emu.PAD1_KEYS.get(c.get('key', 'cross'))
        if key:
            threading.Thread(target=self.emulator.press, args=(key, float(c.get('hold', 0.12))), daemon=True).start()

    def cmd_test_peek(self, c):
        if not self.args.test_hooks or self.link is None:
            return
        try:
            from native_map import A
            c0 = self.link.control()
            u = self.link.u32
            battle = u(A(0x2FEB38))
            words = dict(frame=c0['frame'], state=c0['state'], local_slot=c0['local_slot'],
                         gate=[hex(c0['gate_seq']), hex(c0['gate_agreed']), hex(c0['gate_local'])],
                         director=u(battle) if 0x100000 <= battle < 0x7FFFE00 else None,
                         result=list(kit_postmatch.read_words(self.link)), pause_count=u(kit_verify.PAUSE_COUNT),
                         bgm=u(A(0x331DC8) + 0x0C))
            import struct
            import netplay_core as nc
            import netplay_view as nv
            count = min(u(0xD8084), 10)
            actors = [u(0xD8040 + 4 * i) for i in range(count)]
            words.update(mask=hex(c0['mask']), seats=[u(nc.SEAT_CONTROL + nc.SF['seats'] + 4 * s) for s in range(10)],
                         resolved=u(nc.SEAT_CONTROL + nc.SF['resolved']),
                         published=u(nc.SEAT_CONTROL + nc.SF['published']),
                         cpu=[u(a + 0x1278) if 0x100000 <= a < 0x8000000 else None for a in actors],
                         pos=[[round(x, 1) for x in struct.unpack('<3f', self.link.read(a + 0x30, 12))]
                              if 0x100000 <= a < 0x8000000 else None for a in actors],
                         cams=hex(u(nv.CAM_LOGIC)), cams_built=u(nv.CAM_LOGIC + 4),
                         view_side=u(nv.CONTROL + nv.F['side']))
            self.test_peek_last = words
            self.dirty = True
            self.say(f'TEST peek: {words}')
        except (OSError, RuntimeError) as error:
            self.say(f'TEST peek failed: {error}')

    def cmd_test_shot(self, c):
        if not self.emulator or not self.emulator.pid:
            return
        png, rect = kit_win.capture_pid(self.emulator.pid, self.emulator.desktop)
        if png:
            path = Path(c.get('path') or (self.run_dir / f'pcsx2-{c.get("name", "shot")}.png'))
            path.write_bytes(png)
            self.ipc.send('shot', path=str(path), rect=rect, name=c.get('name'))

    def cmd_test_gshot(self, c):
        """Test only: PCSX2's own picture of the game (F8 screenshot) into the run folder (works on hidden desktops)."""
        if not self.args.test_hooks or not self.emulator or not self.emulator.pid:
            return
        name = str(c.get('name') or 'game')
        dest = self.run_dir / f'game-{name}.png'
        self.job('gshot', self.emulator.screenshot, dest, then=lambda p: self.say(f'TEST: game picture {p}'),
                 fail=lambda e: self.say(f'TEST: game picture failed: {e}'))
