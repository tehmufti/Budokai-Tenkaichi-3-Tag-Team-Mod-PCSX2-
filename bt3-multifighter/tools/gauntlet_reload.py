"""Fighter Gauntlet: load a different fighter into a hidden enemy extra while the match keeps running.

A mode of the ordinary extra reload Worker (same workspaces, same owned-code bookkeeping, one owner at a time).
The job bodies are the ordinary io -> stage -> commit (-> retire) builders with caller-named owner checks
(extra_reload_quiet.owner_pairs): the gauntlet's slot gate word, the KO action and the hidden model. Nothing takes
the combat hold. The guest gauntlet program installs each body itself (gauntlet_runtime COPIER: allowlisted
workspaces only, expected old bytes first) and calls it from the once-per-update chain (RUNNER).

recycle() is a resumable state machine: the watcher calls step() every loop; each call does at most one short
host action (build + publish, or a status read) and returns. The match never waits for the host.
"""
import os
import struct
import time

import extra_reload_worker as base
import extra_reload_service as io
import extra_reload_stage as stage
import extra_reload_commit as commit
import extra_reload_retire as retire
import native_preparation as native
import gauntlet_runtime as runtime
from native_map import ACTOR_HZ, A
from prototype import Assembler

IO_CALLS = 900            # io deadline in guest updates (its own TIMEOUT word)
RUN_LIMIT = 1200          # runner bound for io/poll jobs (updates)
COPY_SECONDS = 8.0        # running time to wait for a copy/run acknowledgement before retrying
RETRIES = 3


class GauntletError(RuntimeError):
    pass


def owner_pairs(ram, physical):
    """The words every gauntlet job re-checks: slot gate (consumed, hidden, KO'd, generation), KO action, hidden."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    actor = u(base.runner.core.POINTERS + 4 * physical)
    model = u(base.runner.core.MODELS + 4 * u(actor + 12))
    gate = u(runtime.GATES + 4 * physical)
    if gate & 0xFFFF0000 != runtime.GATE_MAGIC or not gate & 0xFFFF:
        raise GauntletError(f'Slot {physical} is not hidden and gated')
    return ((runtime.GATES + 4 * physical, gate), (actor + 0x948, 216), (model + 8, 0))


class Transport:
    """Host side of the gauntlet COPIER/RUNNER (data words and the staging packet only)."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep

    def ready(self, p):
        return p.read_u32(runtime.CONTROL) == runtime.MAGIC

    def publish(self, p, manifest):
        """Start a copy (returns its request id); the guest validates and installs it on a later update."""
        packet, count = native.encode(manifest)
        if len(packet) > runtime.CAPACITY:
            raise GauntletError('Gauntlet job packet exceeds its staging buffer')
        c = runtime.CONTROL
        request, ack = p.read_u32(c + runtime.C['copy_request']), p.read_u32(c + runtime.C['copy_ack'])
        if request != ack:
            raise GauntletError('A gauntlet job copy is already pending')
        p.write(runtime.PACKET, packet)
        p.write(c + runtime.C['copy_blocks'], struct.pack('<2I', count, len(packet)))
        p.write_u32(c + runtime.C['copy_status'], 0)
        request = (request + 1) & 0xFFFFFFFF or 1
        p.write_u32(c + runtime.C['copy_request'], request)
        return request

    def copy_result(self, p, request):
        c = runtime.CONTROL
        if p.read_u32(c + runtime.C['copy_ack']) != request:
            return None
        return p.read_u32(c + runtime.C['copy_status'])

    def start(self, p, entry, control, kind, physical, limit=RUN_LIMIT):
        c = runtime.CONTROL
        request, ack = p.read_u32(c + runtime.C['run_request']), p.read_u32(c + runtime.C['run_ack'])
        if request != ack:
            raise GauntletError('A gauntlet job is already running')
        p.write(c + runtime.C['run_status'], struct.pack('<8I', 0, entry, control, kind, physical, 0, 0, limit))
        request = (request + 1) & 0xFFFFFFFF or 1
        p.write_u32(c + runtime.C['run_request'], request)
        return request

    def run_result(self, p, request):
        c = runtime.CONTROL
        if p.read_u32(c + runtime.C['run_ack']) != request:
            return None
        return p.read_u32(c + runtime.C['run_status'])


# Actor words that hold no pointers: a byte table +0x7A0..+0x8C0 (0x64 per byte for a fighter in play, 5 or 6 for
# an unused physical; the button rings from +0x8C0 are excluded by retire itself), two 0x50-byte flag records
# (+0x1080, +0x10D0) and a byte table up to +0x1260 (values 0..12). Read live (g7, g8): 0x02008000, 0x05030303 and
# 0x05050505 there matched freshly allocated bundles at 0x02000000 and 0x05000000, which kept such bundles from
# retiring until the 12 resource records ran out.
ACTOR_DATA = ((0x7A0, 0x8C0), (0x1080, 0x1270))


# ---------------------------------------------------------------- rollback of a failed load
UNSTAGE_RELEASE = A(0x249B58)    # native: return a model ID's draw nodes (commit retire_staged uses it the same way)


def unstage_code(guards, model_id, model):
    """Release a staged replacement model that no actor uses (the load failed before its commit). Runs once in
    the retire workspace. Status 5 done, 110 a guard changed, 160 the native release refused."""
    a = Assembler(retire.ENTRY); a.addiu(29, 29, -0x150)
    for i, r in enumerate(retire.SAVED):
        a.i(63, r, 29, 8 * i)
    a.li(16, retire.CONTROL); a.lw(8, 16); a.branch(4, 8, 0, 'done')
    a.lw(8, 16, 4); a.addiu(9, 0, 5); a.branch(4, 8, 9, 'done'); a.i(11, 9, 8, 100); a.branch(4, 9, 0, 'done')
    for at, value in guards:
        a.li(8, at); a.lw(8, 8); a.li(9, value); a.branch(5, 8, 9, 'error110')
    a.addiu(4, 0, model_id); a.call(UNSTAGE_RELEASE); a.addiu(8, 0, 1); a.branch(5, 2, 8, 'error160')
    a.li(8, model); a.lw(8, 8, 4); a.branch(5, 8, 0, 'error160')
    a.addiu(8, 0, 5); a.sw(8, 16, 4); a.jump('done')
    for name, status in (('error110', 110), ('error160', 160)):
        a.label(name); a.addiu(8, 0, status); a.sw(8, 16, 4); a.jump('done')
    a.label('done')
    for i, r in enumerate(retire.SAVED):
        a.i(55, r, 29, 8 * i)
    a.addiu(29, 29, 0x150); a.jr()
    data = a.finish(); assert len(data) < retire.CONTROL - retire.ENTRY; return data


def staged_model(ram, physical, resource):
    """(model id, model) of a staged replacement for `resource` that is still registered and used by no actor,
    else None."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    core = base.runner.core
    mid, model = u(stage.CONTROL + 40), u(stage.CONTROL + 44)
    if not 0 <= mid < 12 or u(core.MODELS + 4 * mid) != model or not 0x100000 <= model <= len(ram) - 0x1670:
        return None
    if u(model + 4) != 1 or u(model + 20) != resource or u(model + 8) != 0 or u(model + 16) != mid:
        return None
    for i in range(u(core.MODE + 4)):
        actor = u(core.POINTERS + 4 * i)
        if u(actor + 12) == mid:
            return None
    return mid, model


def discard_capture(ram, physical, resource, handle, quiet_checks, actor_data=()):
    """retire.capture for a bundle that was loaded but never committed: no receipt, no owner AI rebinding, nothing
    may point into it (every actor, registered model and private AI context), its texture group untouched (none
    was assigned, or the staged model's release returned it)."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    require = retire.require
    w = retire.prior.capture(ram, physical, allow_leaders=True)
    for p, v in quiet_checks:
        require(u(p) == v, 'Discard hold changed')
    require(2 <= handle < 14 and resource == w['registry'] + (handle - 2) * 56 and u(resource + 48) == 3
            and u(resource + 52) == handle, 'The failed load left no complete resource record')
    require(resource != w['old_resource'], 'The failed load is the owner\'s current resource')
    guards = list(quiet_checks) + [(retire.prior.core.ACTORS, w['manager']), (retire.prior.core.MODE, 1),
        (retire.prior.core.MODE + 4, w['count']), (retire.prior.core.MODE + 8, w['manager']),
        (retire.prior.core.MODE + 12, w['count']), (retire.prior.core.PAIR + 4, 0),
        (retire.prior.REGISTRY_GLOBAL, w['registry'] - retire.prior.REGISTRY_OFFSET),
        (resource + 48, 3), (resource + 52, handle), (w['model'] + 20, w['old_resource'])]
    buffers, ranges = [], []
    for i in range(3):
        q, n, f = u(resource + 16 * i), u(resource + 16 * i + 4), u(resource + 16 * i + 8)
        require(0x100000 <= q <= len(ram) - n and 0 < n <= 0x800000, 'Invalid loaded heap buffer')
        for off, val in ((0, q), (4, n), (8, f)):
            guards.append((resource + 16 * i + off, val))
        buffers.append(dict(pointer=q, size=n, file=f)); ranges.append((q, n))
    require(all(p + n <= q or q + m <= p for i, (p, n) in enumerate(ranges) for q, m in ranges[i + 1:]),
            'Loaded buffers must be independent')
    inside = lambda v: any(p <= v < p + n for p, n in ranges)
    for actor in w['actors']:
        require(not any(inside(u(actor + off)) for off in range(0, 0x1600, 4) if not 0x8C0 <= off < 0x910 and
                        not any(lo <= off < hi for lo, hi in actor_data)), 'An actor points into the failed load')
    vacant = []
    for mid in range(12):
        model = u(retire.prior.core.MODELS + 4 * mid)
        if not model or u(model + 4) != 1:
            vacant.append(mid); continue
        require(u(model + 20) != resource, 'A registered model still uses the failed load')
        require(not any(inside(u(model + off)) for off in range(0, 0x1670, 4)),
                'A registered model points into the failed load')
        guards += [(retire.prior.core.MODELS + 4 * mid, model), (model + 4, 1), (model + 20, u(model + 20))]
    for i in range(w['count']):
        base_ = retire.commit.fresh.SHADOWS[i] + 0x10
        for half in (0, 0x520):
            require(not any(inside(u(base_ + half + off)) for off in range(0, 0x520, 4) if off not in (0x2C0, 0x2C4)),
                    'A private AI context points into the failed load')
    queue = u(retire.texture.QUEUE)
    require(0x100000 <= queue <= len(ram) - 2060, 'Invalid texture upload queue')
    guards.append((retire.texture.QUEUE, queue))
    owned = dict(physical=physical, manager=w['manager'], resource=resource, handle=handle, buffers=buffers, group=0)
    return dict(world=w, owned=owned, guards=guards, ranges=ranges, queue=queue, owner=0, copies=[], vacant=vacant,
                preserve_texture=True, defer_busy=True)


def injection(spec):
    """TTM_GAUNTLET_INJECT (tests only): 'stage' or 'io' (optionally ':count') fails that many loads right after
    that step completed, to exercise the rollback. Empty: never."""
    spec = (spec or '').strip()
    if not spec:
        return None
    step, _, count = spec.partition(':')
    if step not in ('io', 'stage'):
        raise ValueError('TTM_GAUNTLET_INJECT names io or stage')
    return dict(step=step, count=int(count or 1))

class GauntletWorker(base.Worker):
    """The ordinary Worker plus unheld gauntlet slot jobs. While a gauntlet job runs, ordinary claims wait."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.transport = Transport(self.clock, self.sleep)
        self.job = None            # current gauntlet job (dict) or None
        self.log = []              # (time, message)
        self.completed = []        # finished jobs (dict with timings)
        self.tolerated = set()      # workspaces whose last gauntlet job refused (see _analysis_view)
        self.inject = injection(os.environ.get('TTM_GAUNTLET_INJECT'))
        self.rollbacks = []         # finished rollback jobs (diagnostics)

    # ---------------------------------------------------------------- ordinary worker coexistence
    def _poll(self, p):
        if self.job is not None:
            return False
        return super()._poll(p)

    def idle(self):
        return self.job is None and self.form_job is None

    def note(self, message):
        self.log.append((time.time(), message))
        self.progress(message)

    # ---------------------------------------------------------------- job control
    def recycle(self, p, physical, character, costume=0, tag=None):
        """Queue the load of `character` into hidden enemy extra `physical`. Returns False when busy."""
        if self.job is not None or self.form_job is not None:
            return False
        self.job = dict(physical=physical, character=character, costume=costume, tag=tag, phase='io-build',
                        started=time.perf_counter(), timings=[], attempts=0, request=None, run=None)
        return True

    def step(self, p):
        """Advance the current job by at most one short host action. Returns the job when it just finished."""
        job = self.job
        if job is None:
            return None
        try:
            with base.policy.building_for(self.capacity), base.lazy_ram.patched():
                return self._step(p, job)
        except GauntletError as error:
            return self._fail(job, str(error))
        except ValueError as error:
            # A builder refused (torn snapshot, owner moved): retry a few times from the current phase's build.
            job['attempts'] += 1
            if job['attempts'] > RETRIES:
                return self._fail(job, f'{job["phase"]}: {error}')
            job['retry_at'] = self.clock() + 0.25
            return None

    def _fail(self, job, reason):
        job['phase'] = 'failed'; job['reason'] = reason
        P = job['physical']
        if job.get('rollback'):
            # The rollback itself refused: what it could not free stays loaded (logged; the slot stays usable).
            self.note(f'Gauntlet slot {P}: the failed load could not be rolled back ({reason}); its bundle stays loaded')
            self.tolerated.update(name for name in ('io', 'stage', 'commit', 'retire') if name in self.owned)
            self.job = None; self.rollbacks.append(job); return job
        self.note(f'Gauntlet load for physical {P} failed: {reason}')
        # A job body that refused before touching anything (io 110..133 before its files were queued, stage and
        # commit guards) leaves its workspace with a final error status: the next build may replace it.
        self.tolerated.update(name for name in ('io', 'stage', 'commit', 'retire') if name in self.owned)
        self.job = None; self.completed.append(job)
        if job.get('io_done') and not job.get('committed'):
            # Its io loaded a bundle (and maybe a staged model) that nothing will use: give them back first, so
            # the retry and the later waves still find a resource record and a staging model slot.
            self.job = dict(physical=P, character=None, costume=0, tag=None, phase='rollback-plan', rollback=True,
                            io_done=dict(job['io_done']), stage_tried=bool(job.get('stage_tried')),
                            started=time.perf_counter(), timings=[], attempts=0, request=None, run=None,
                            failed_reason=reason)
        return job

    def _rollback(self, p, job):
        """One rollback step: release the staged model (unstage), then free the io bundle (discard)."""
        P = job['physical']; resource, handle = job['io_done']['resource'], job['io_done']['handle']
        ram, view = self._view(p, ('retire',))
        pairs = owner_pairs(ram, P)
        staged = staged_model(view, P, resource) if job['stage_tried'] and not job.get('unstaged') else None
        if staged is not None:
            mid, model = staged
            guards = list(pairs) + [(base.runner.core.MODELS + 4 * mid, model), (model + 4, 1), (model + 8, 0),
                                    (model + 16, mid), (model + 20, resource)]
            control = bytearray(0x100)
            manifest = dict(blocks=[dict(address=q, expected_hex=view[q:q + len(d)].hex(), data_hex=d.hex())
                                    for q, d in ((retire.ENTRY, unstage_code(guards, mid, model)),
                                                 (retire.CONTROL, bytes(control)))],
                            entry=retire.ENTRY, control=retire.CONTROL)
            job['rollback_step'] = 'unstage'; job['staged'] = dict(model_id=mid, model=model)
            self._publish(p, job, 'retire', ram, manifest, retire.ENTRY, retire.CONTROL, runtime.RUN_ONCE)
            return None
        c = discard_capture(view, P, resource, handle, pairs, ACTOR_DATA)
        control = bytearray(0x100)
        struct.pack_into('<4I', control, 8, c['world']['manager'], c['world']['actor'], resource, handle)
        manifest = dict(blocks=[dict(address=q, expected_hex=view[q:q + len(d)].hex(), data_hex=d.hex())
                                for q, d in ((retire.ENTRY, retire.payload(c)), (retire.CONTROL, bytes(control)))],
                        entry=retire.ENTRY, control=retire.CONTROL)
        job['rollback_step'] = 'discard'
        self._publish(p, job, 'retire', ram, manifest, retire.ENTRY, retire.CONTROL, runtime.RUN_POLL)
        return None

    def _rollback_done(self, p, job):
        P = job['physical']
        if job['rollback_step'] == 'unstage':
            job['unstaged'] = True; job['phase'] = 'rollback-plan'
            return None
        if p.read_u32(retire.CONTROL + 32):
            # The renderer was busy: nothing was freed; try again shortly.
            job['attempts'] += 1
            if job['attempts'] > 20:
                raise GauntletError('the renderer stayed busy')
            job['retry_at'] = self.clock() + 0.5; job['phase'] = 'rollback-plan'
            return None
        job['phase'] = 'done'; job['seconds'] = time.perf_counter() - job['started']
        self.note(f'Gauntlet slot {P}: the failed load was rolled back (resource record {job["io_done"]["handle"]} '
                  f'freed{", staged model " + str(job["staged"]["model_id"]) + " released" if job.get("staged") else ""}; '
                  f'{job["seconds"]:.2f} s)')
        self.job = None; self.rollbacks.append(job)
        return job

    def _analysis_view(self, ram):
        """Worker._analysis_view, except that a workspace whose gauntlet job refused (final status >= 100) is
        reset like a completed one; the ordinary worker's own jobs keep the strict status-5 rule."""
        relaxed = {}
        for name in list(self.tolerated):
            module = {'io': io, 'stage': stage, 'commit': commit, 'retire': retire}[name]
            status = base.u(ram, module.CONTROL + 4)
            if name in self.owned and status != 5:
                if status < 100:
                    raise GauntletError(f'{name} workspace is still busy (status {status})')
                relaxed[name] = module
        if not relaxed:
            return super()._analysis_view(ram)
        owned = self.owned
        try:
            self.owned = {k: v for k, v in owned.items() if k not in relaxed}
            view = super()._analysis_view(ram)
        finally:
            self.owned = owned
        # Restore the refused workspaces' original bytes in the view as well.
        overrides = {}
        for name in relaxed:
            for block in owned[name]['blocks']:
                overrides[block['address']] = bytes.fromhex(block.get('restore_hex', block['expected_hex']))
        if isinstance(view, base.lazy_ram.LazyRam):
            return view.view(overrides)
        view = bytearray(view)
        for at, old in overrides.items():
            view[at:at + len(old)] = old
        return view

    def _view(self, p, names):
        ram = self._snapshot(p)
        return ram, self._analysis_view_for(ram, names)

    def _publish(self, p, job, name, ram, manifest, entry, control, kind):
        self._prepare_blocks(name, ram, manifest)
        block = next(b for b in manifest['blocks'] if b['address'] == control)
        data = bytearray.fromhex(block['data_hex']); struct.pack_into('<I', data, 0, 1); block['data_hex'] = data.hex()
        job['request'] = self.transport.publish(p, manifest)
        job['pending'] = (name, manifest, entry, control, kind)
        job['since'] = self.clock()
        job['phase'] = name + '-copy'

    def _step(self, p, job):
        if self.clock() < job.get('retry_at', 0):
            return None
        phase = job['phase']
        P, X, costume = job['physical'], job['character'], job['costume']
        if phase == 'io-build':
            ram, view = self._view(p, ('io',))
            pairs = owner_pairs(ram, P)
            manifest = self._build('io', io.build_memory, view, P, X, costume, False, timeout=IO_CALLS, quiet=True,
                                   allow_forms=True, background=True, owner_checks=pairs)
            job['pairs'] = pairs
            self._publish(p, job, 'io', ram, manifest, io.ENTRY, io.CONTROL, runtime.RUN_IO)
            return None
        if phase == 'meta-wait':
            status = self.transport.copy_result(p, job['request'])
            if status is None:
                if self.clock() - job['since'] > COPY_SECONDS:
                    raise GauntletError('metadata: the guest did not install it')
                return None
            if status == 103:                    # the copier was busy: publish again shortly
                job['request'] = self.transport.publish(p, job['meta']); job['since'] = self.clock()
                return None
            if status != 1:
                raise GauntletError(f'metadata: installation refused with status {status}')
            job['timings'].append(('metadata installed', time.perf_counter() - job['started']))
            return self._next(p, job, 'meta')
        if phase.endswith('-copy'):
            status = self.transport.copy_result(p, job['request'])
            if status is None:
                if self.clock() - job['since'] > COPY_SECONDS:
                    raise GauntletError(f'{phase}: the guest did not install the job')
                return None
            name, manifest, entry, control, kind = job['pending']
            if status == 103:                    # a workspace or runner was busy: publish again shortly
                job['retry_at'] = self.clock() + 0.1
                job['request'] = None
                job['phase'] = name + '-republish'
                return None
            if status != 1:
                raise GauntletError(f'{name}: job installation refused with status {status}')
            self.owned[name] = manifest
            job['timings'].append((name + ' installed', time.perf_counter() - job['started']))
            job['run'] = self.transport.start(p, entry, control, kind, P,
                                              RUN_LIMIT if kind != runtime.RUN_ONCE else 1)
            job['since'] = self.clock(); job['phase'] = name + '-run'
            return None
        if phase.endswith('-republish'):
            name, manifest, entry, control, kind = job['pending']
            job['request'] = self.transport.publish(p, manifest)
            job['since'] = self.clock(); job['phase'] = name + '-copy'
            return None
        if phase.endswith('-run'):
            name = phase[:-4]
            status = self.transport.run_result(p, job['run'])
            if status is None:
                limit = 60.0 if name in ('io', 'retire') else COPY_SECONDS
                if self.clock() - job['since'] > limit:
                    raise GauntletError(f'{name}: the job did not finish')
                return None
            job['timings'].append((name + ' done', time.perf_counter() - job['started']))
            if status != 5:
                raise GauntletError(f'{name}: job ended with status {status}')
            return self._next(p, job, name)
        if phase == 'retire-next':
            return self._retire_next(p, job)
        if phase == 'rollback-plan':
            return self._rollback(p, job)
        raise GauntletError(f'Unknown gauntlet job phase {phase}')

    def _next(self, p, job, finished):
        P, X = job['physical'], job['character']
        if job.get('rollback'):
            return self._rollback_done(p, job)
        if finished == 'io':
            job['io_done'] = dict(resource=p.read_u32(io.CONTROL + 32), handle=p.read_u32(io.CONTROL + 36))
        if self.inject and self.inject['step'] == finished and self.inject['count'] > 0:
            self.inject['count'] -= 1
            raise GauntletError(f'injected failure after {finished} (TTM_GAUNTLET_INJECT)')
        if finished == 'io' and runtime.METADATA is not None:
            # BT4: the new resource's character metadata first (as Worker._bt4_metadata), through the copier.
            ram = self._snapshot(p)
            u = lambda q: struct.unpack_from('<I', ram, q)[0]
            manifest = runtime.METADATA.build_memory(ram, [dict(resource=u(io.CONTROL + 32),
                                                                resource_handle=u(io.CONTROL + 36))])
            for block in manifest['blocks']:
                at, size = block['address'], len(block['data_hex']) // 2
                if not any(lo <= at and at + size <= hi for lo, hi in runtime.METADATA_REGIONS):
                    raise GauntletError('The BT4 character metadata bridge is not installed in this match')
            if manifest['blocks']:
                job['meta'] = manifest
                job['request'] = self.transport.publish(p, manifest)
                job['since'] = self.clock(); job['phase'] = 'meta-wait'
                return None
        if finished in ('io', 'meta'):
            ram, view = self._view(p, ('stage', 'commit'))
            pairs = owner_pairs(ram, P)
            manifest = self._build('stage', stage.build_memory, view, quiet=True, allow_forms=True, owner_checks=pairs)
            job['stage_tried'] = True
            self._publish(p, job, 'stage', ram, manifest, stage.ENTRY, stage.CONTROL, runtime.RUN_ONCE)
            return None
        if finished == 'stage':
            ram, view = self._view(p, ('commit',))
            pairs = owner_pairs(ram, P)
            manifest = self._build('commit', commit.build_memory, view, quiet=True, retire_staged=True,
                                   gauntlet=dict(owner_checks=pairs))
            self._publish(p, job, 'commit', ram, manifest, commit.ENTRY, commit.CONTROL, runtime.RUN_ONCE)
            return None
        if finished == 'commit':
            job['committed'] = True
            ram = self._snapshot(p)
            u = lambda q: struct.unpack_from('<I', ram, q)[0]
            actor = u(base.runner.core.POINTERS + 4 * P); model = u(base.runner.core.MODELS + 4 * u(actor + 12))
            if u(commit.AI_META) != 5 or u(commit.CONTROL + 36) != 1 or u(model + 12) != X:
                raise GauntletError('Final identity check failed after the commit')
            new = retire.receipt(ram, P)
            old = self.resources.get(P); self.resources[P] = new
            if old is not None:
                self.retained.setdefault(P, []).append(old)
            job['phase'] = 'retire-next'
            return self._retire_next(p, job)
        if finished == 'retire':
            pending = self.retained.get(P, [])
            if p.read_u32(retire.CONTROL + 32):
                # The renderer was busy: the payload deferred and freed nothing; the bundle stays kept for the sweep.
                job.setdefault('skipped', []).append(job.get('retiring'))
                self.note(f'Gauntlet slot {P}: an old bundle stays loaded for now (renderer busy)')
            else:
                job['retired'] = job.get('retired', 0) + 1
                if job.get('retiring') in pending:
                    pending.remove(job['retiring'])
            job['phase'] = 'retire-next'
            return self._retire_next(p, job)
        raise GauntletError(f'Unexpected finished stage {finished}')

    def sweep(self, p, physical):
        """Retire the superseded bundles still kept for hidden enemy slot `physical` (no load). False when busy."""
        if self.job is not None or self.form_job is not None or not self.retained.get(physical):
            return False
        self.job = dict(physical=physical, character=None, costume=0, tag=None, phase='retire-next', sweep=True,
                        started=time.perf_counter(), timings=[], attempts=0, request=None, run=None)
        return True

    def kept(self):
        """How many superseded bundles are still loaded (each holds one of the 12 resource records)."""
        return sum(len(v) for v in self.retained.values())

    def _retire_next(self, p, job):
        """Retire the slot's superseded worker bundles, unheld; a reference still alive keeps one retained."""
        P = job['physical']
        for owned in list(self.retained.get(P, [])):
            if owned in job.setdefault('skipped', []):
                continue
            ram, view = self._view(p, ('retire',))
            pairs = owner_pairs(ram, P)
            context = dict(quiet_checks=list(pairs), commit_guards=[(commit.CONTROL + 4, 5), (commit.AI_META, 5),
                                                                    (commit.CONTROL + 36, 1)], actor_data=ACTOR_DATA)
            try:
                try:
                    c = retire.capture(view, owned, body_context=context)
                except ValueError as error:
                    if 'still owns the retired bundle or texture group' not in str(error):
                        raise
                    # A newer model took this bundle's texture group number: free the bundle, keep the group.
                    c = retire.capture(view, owned, body_context=dict(context, preserve_texture=True))
            except ValueError as error:
                job['skipped'].append(owned); self.retirement_notes.append(str(error))
                self.note(f'Gauntlet slot {P}: an old bundle stays loaded for now ({error})'); continue
            # Another AI may still look at the old body: its stale context is refreshed by the guest only while it
            # still shows the retired body (guard_copies), never over a newer target.
            c['guard_copies'] = True
            c['defer_busy'] = True
            control = bytearray(0x100)
            struct.pack_into('<4I', control, 8, c['world']['manager'], c['world']['actor'], owned['resource'],
                             owned['handle'])
            manifest = dict(blocks=[dict(address=q, expected_hex=view[q:q + len(d)].hex(), data_hex=d.hex())
                                    for q, d in ((retire.ENTRY, retire.payload(c)), (retire.CONTROL, bytes(control)))],
                            entry=retire.ENTRY, control=retire.CONTROL)
            job['retiring'] = owned
            self._publish(p, job, 'retire', ram, manifest, retire.ENTRY, retire.CONTROL, runtime.RUN_POLL)
            return None
        job['phase'] = 'done'
        job['seconds'] = time.perf_counter() - job['started']
        if job.get('sweep'):
            self.note(f'Gauntlet slot {P}: {job.get("retired", 0)} old bundle(s) retired, '
                      f'{len(self.retained.get(P, []))} kept ({job["seconds"]:.2f} s)')
            self.job = None; self.completed.append(job)
            return job
        self.note(f'Gauntlet slot {P} loaded {job["character"]} in {job["seconds"]:.2f} s '
                  + ', '.join(f'{n} {t:.2f}' for n, t in job['timings']))
        self.job = None; self.completed.append(job)
        return job
