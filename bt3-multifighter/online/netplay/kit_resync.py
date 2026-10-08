"""Bringing a guest's game back to the host's (kit 2.0): desync recovery, and a member joining a running fight.

Host-authoritative state transfer, per member (kit_lockstep.Hub):
  * a PLAYER whose game differs (Hub.members_needing_resync: a difference lasting 30 compared frames, or the rng class
    differing): every game must stop at one frame K first, because the frames K..K+D-1 every PC consumes after the
    load must be agreed: K = max(host frame, newest guest frame written into the host's game + 1) + D + MARGIN;
    Hub.hold(K) (no input >= K is written or forwarded: every game waits at K), the member's hash reports are ignored
    (pause_member), its gate words of K..K+D-1 become the host's (adopt_host_aux: it will run a copy of the host's
    world), the host saves its state (a token at CONTROL+0xF0 identifies it), sends RESYNC {K, token, table, sha256,
    size} plus the file, restarts the member's comparison at K (next generation) and releases the hold;
  * a SPECTATOR (desynced, or joining a fight that is already running) needs no hold: nobody waits for it. The host
    saves its state wherever its game is (frame F, read back from the file), and the member continues from F with
    every slot's inputs from F on (the host keeps them all).
At most MAX_RESYNCS per member and fight; one more makes that member leave the fight (a player's fighter idles from
then on, a spectator's window closes) - the others play on, never unchecked.
The guest (GuestResync): receives the file, writes ITS per-machine words into it (kit_match.machine_copy: slot, watched
side, display settings: nothing can run with the host's words), loads it (a PINE load into the running PCSX2, or a new
PCSX2 when it has none: a join or a rejoin), waits for the token, then Client.reload(K, table) and RESYNC_LOADED.
Table entries: hex24 = raw8 (16 hex) + aux (8 hex) per slot and frame K..K+D-1.
"""
import hashlib
import secrets
import struct
import threading
import time
from pathlib import Path

from pinelink import nc

MARGIN = 4
MAX_RESYNCS = 3
NEUTRAL_AFTER = 2.0
TOKEN_WORD = nc.CONTROL + 0xF0
STATE_NAME = 'SLUS-21678 (428113C2).{slot}.p2s'
SLOT = 240
JOIN_SLOT = 242


def choose_k(own_frame, highest_written, delay, margin=MARGIN):
    return max(own_frame, highest_written + 1) + delay + margin


def encode_table(table, K, D):
    """{slot: {frame: (raw8, aux) or None}} -> {'s': [hex24 ...]} for frames K..K+D-1 (None: neutral)."""
    out = {}
    for s, rows in table.items():
        items = []
        for f in range(K, K + D):
            item = rows.get(f) or (nc.NEUTRAL, 0)
            items.append(bytes(item[0]).hex() + f'{item[1] & 0xFFFFFFFF:08x}')
        out[str(s)] = items
    return out


def decode_table(data, K, D):
    out = {}
    for s, rows in data.items():
        if len(rows) != D or any(len(r) != 24 for r in rows) or int(s) not in range(10):
            raise ValueError('bad resync table')
        out[int(s)] = {K + i: (bytes.fromhex(r[:16]), int(r[16:], 16)) for i, r in enumerate(rows)}
    return out


class Worker:
    """A blocking step in a thread; the session loop polls done/error/value."""

    def __init__(self, fn, *args):
        self.done, self.error, self.value = False, None, None
        self.thread = threading.Thread(target=self._run, args=(fn,) + args, daemon=True)
        self.thread.start()

    def _run(self, fn, *args):
        try:
            self.value = fn(*args)
        except BaseException as error:  # noqa: BLE001 - handed to the session loop
            self.error = error
        self.done = True


def wait_file(path, before_mtime, timeout=60, alive=None):
    """Seconds until PCSX2 finished writing `path` (mtime changed, size stable for 0.3 s)."""
    t0 = time.perf_counter()
    last = -1
    while time.perf_counter() - t0 < timeout:
        if alive is not None and not alive():
            raise RuntimeError('PCSX2 closed while saving')
        try:
            st = path.stat()
        except OSError:
            time.sleep(0.02)
            continue
        if st.st_mtime_ns != before_mtime and st.st_size > 0:
            if st.st_size == last:
                return time.perf_counter() - t0
            last = st.st_size
            time.sleep(0.15)
            continue
        time.sleep(0.02)
    raise TimeoutError(f'{path.name} was not written')


def mtime(path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def state_frame(path):
    import kit_state
    return kit_state.read_words(path, [nc.CONTROL + nc.F['frame']])[nc.CONTROL + nc.F['frame']]


class HostResync:
    """ctx: hub (kit_lockstep.Hub), link (PineLink-like), sstates (Path of PCSX2's sstates folder, or None in tests:
    link.save_state returns the path), send(member, message), send_file(member, path) (blocking: B chunks + END),
    alive(), log(text). targets: member ids; hold: True for players (False: spectators only, no hold)."""

    def __init__(self, ctx, targets, reason, epoch, hold=True, now=None):
        self.ctx, self.targets, self.reason, self.epoch, self.hold = ctx, list(targets), reason, epoch, hold
        self.state, self.K, self.table, self.token = 'start', None, None, None
        self.sched_count = None
        self.worker = None
        self.started = time.perf_counter() if now is None else now
        self.m = dict(reason=reason, targets=self.targets, hold=hold)
        self.error = None

    def step(self, now=None):
        now = time.perf_counter() if now is None else now
        ctx, hub = self.ctx, self.ctx.hub
        D = hub.delay
        if self.state == 'start':
            for t in self.targets:
                if t in hub.members:
                    hub.pause_member(t)
            if not self.hold:
                self.token = secrets.randbits(31) | 1
                self.state = 'save'
                self.sched_count = hub.sched_count() if hasattr(hub, 'sched_count') else None
                self.worker = Worker(self._save)
                return self.state
            c = hub.control or hub.guest.control()
            self.K = choose_k(c['frame'], hub.highest_written(), D)
            hub.hold(self.K)
            self.t_hold = now
            self.m.update(K=self.K, frame=c['frame'])
            self.state = 'hold'
            ctx.log(f'resync: hold at K={self.K} for {self.targets} ({self.reason})')
            return self.state
        if self.state == 'hold':
            K = self.K
            c = hub.control or {}
            held = c.get('state') == nc.RUNNING and c.get('frame') == K and bool(c.get('waiting'))
            if c.get('state') != nc.RUNNING:
                return self.fail('the fight is over (the host\'s game no longer runs)')
            late = now - self.t_hold > NEUTRAL_AFTER
            if late and not hub.complete(K):
                hub.neutral_fill(K)
                self.m['neutral'] = True
            if held and hub.complete(K):
                for t in self.targets:
                    if t in hub.members:
                        hub.adopt_host_aux(t, K)
                self.table = hub.table(K)
                self.token = secrets.randbits(31) | 1
                self.m['hold_s'] = round(now - self.t_hold, 3)
                self.state = 'save'
                self.sched_count = hub.sched_count() if hasattr(hub, 'sched_count') else None
                self.worker = Worker(self._save)
            elif now - self.t_hold > 30:
                return self.fail('the games did not stop at the resync frame')
            return self.state
        if self.state == 'save':
            if not self.worker.done:
                return self.state
            if self.worker.error:
                return self.fail(f'saving the state failed: {self.worker.error}')
            path, sha, size = self.worker.value
            if not self.hold:
                self.K = state_frame(path)
                self.table = None
            self.m.update(size=size, sha256=sha, K=self.K)
            for t in self.targets:
                if t in hub.members:
                    hub.restart_member(t, self.K, self.sched_count)
            self.state = 'send'
            self.worker = Worker(self._send, path, sha, size)
            return self.state
        if self.state == 'send':
            if not self.worker.done:
                return self.state
            if self.hold and hub.hold_at is not None:
                hub.release()
            if self.worker.error:
                return self.fail(f'sending the state failed: {self.worker.error}')
            self.m['total_s'] = round(now - self.started, 3)
            self.state = 'done'
            ctx.log(f'resync: state sent to {self.targets} in {self.m["total_s"]} s ({self.m.get("size", 0) / 1e6:.1f} '
                    'MB)')
            return self.state
        return self.state

    def fail(self, why):
        self.error = why
        self.state = 'failed'
        hub = self.ctx.hub
        if self.hold and hub.hold_at is not None:
            hub.release()
        self.ctx.log(f'resync of {self.targets} failed: {why}')
        return self.state

    def _save(self):
        ctx = self.ctx
        ctx.link.w32(TOKEN_WORD, self.token)
        if ctx.sstates is None:
            path = Path(ctx.link.save_state(SLOT))
        else:
            path = Path(ctx.sstates) / STATE_NAME.format(slot=SLOT)
            before = mtime(path)
            ctx.link.save_state(SLOT)
            wait_file(path, before, alive=ctx.alive)
        return path, sha256(path), path.stat().st_size

    def _send(self, path, sha, size):
        ctx, hub = self.ctx, self.ctx.hub
        message = dict(type='RESYNC', epoch=self.epoch, K=self.K, token=self.token, hold=self.hold,
                       table=encode_table(self.table, self.K, hub.delay) if self.table else None, sha256=sha,
                       size=size, reason=self.reason, delay=hub.delay, sched=self.sched_count)
        for t in self.targets:
            ctx.send(t, message)
            ctx.send_file(t, path)
        return True


class GuestResync:
    """The guest's side: RESYNC meta, then the file (feed() each B chunk, end() at END), then the load. ctx: client
    (kit_lockstep.Client, or None for a join: then launch(path) starts PCSX2 and returns (link, client)), link,
    sstates, machine(path_in, path_out) (writes this PC's per-machine copy), send(message), log(text),
    ensure_running(), launch(path)."""

    def __init__(self, ctx, message, now=None):
        self.ctx, self.msg = ctx, message
        self.epoch, self.K, self.token = message['epoch'], message['K'], message['token']
        self.delay = message['delay']
        self.table = decode_table(message['table'], self.K, self.delay) if message.get('table') else None
        self.state = 'receive'
        self.started = time.perf_counter() if now is None else now
        self.got = 0
        self.h = hashlib.sha256()
        base = Path(ctx.sstates) if ctx.sstates else Path(ctx.tmp_dir)
        base.mkdir(parents=True, exist_ok=True)
        self.received = base / 'resync-received.p2s'
        self.path = base / STATE_NAME.format(slot=SLOT)
        self.part = self.received.with_name(self.received.name + '.part')
        self.file = open(self.part, 'wb')
        self.worker = None
        self.error = None
        self.link = None
        self.m = dict(K=self.K)
        if ctx.client is not None:
            ctx.client.frozen = True

    def feed(self, chunk):
        self.file.write(chunk)
        self.h.update(chunk)
        self.got += len(chunk)

    def end(self):
        self.file.close()
        if self.h.hexdigest() != self.msg['sha256'] or self.got != self.msg['size']:
            try:
                self.part.unlink()
            except OSError:
                pass
            return self.fail('the state did not arrive intact')
        self.part.replace(self.received)
        self.m['received_s'] = round(time.perf_counter() - self.started, 3)
        self.state = 'load'
        self.worker = Worker(self._load)
        return self.state

    def step(self, now=None):
        now = time.perf_counter() if now is None else now
        if self.state != 'load' or not self.worker.done:
            return self.state
        if self.worker.error:
            return self.fail(f'loading the state failed: {self.worker.error}')
        self.m['total_s'] = round(now - self.started, 3)
        self.state = 'done'
        self.ctx.send(dict(type='RESYNC_LOADED', epoch=self.epoch, frame=self.K))
        self.ctx.log(f'resync: loaded the host\'s state at frame {self.K} in {self.m["total_s"]} s')
        return self.state

    def fail(self, why):
        self.error = why
        self.state = 'failed'
        try:
            self.file.close()
        except OSError:
            pass
        self.ctx.log(f'resync failed: {why}')
        return self.state

    def _load(self):
        ctx = self.ctx
        self.ctx.machine(self.received, self.path)
        t0 = time.perf_counter()
        if ctx.client is None:                            # a join / rejoin: a new PCSX2 starts with the state
            self.link, client = ctx.launch(self.path)
            ctx.client = client
            if self.link.u32(TOKEN_WORD) != self.token:
                raise RuntimeError('the started game is not the host\'s state')
        else:
            link = self.link = ctx.link
            link.w32(TOKEN_WORD, self.token ^ 0x5A5A5A5A)
            if ctx.sstates is None:
                link.load_state(str(self.path))
            else:
                link.load_state(SLOT)
            while link.u32(TOKEN_WORD) != self.token:
                if time.perf_counter() - t0 > 60:
                    raise TimeoutError('the loaded state did not appear')
                time.sleep(0.005)
        c = self.link.control()
        if self.msg.get('hold') and not (c['state'] == nc.RUNNING and c['frame'] == self.K):
            raise RuntimeError(f'the loaded game is not at K={self.K} (state {c["state"]}, frame {c["frame"]})')
        ctx.client.reload(self.K, self.table, self.msg.get('sched'))
        ctx.client.frozen = False
        if ctx.ensure_running:
            ctx.ensure_running()
        self.m['load_s'] = round(time.perf_counter() - t0, 3)
        return True


def parse_u32(data):
    return struct.unpack('<I', data)[0]
