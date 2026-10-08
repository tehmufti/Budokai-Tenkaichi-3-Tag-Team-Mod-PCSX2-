"""A host-visible model of tools/netplay_core for offline tests and dry runs of the session and the relay.

FakeGuest keeps the core's real memory layout (CONTROL, OUTGOING, HASHES, INCOMING at their guest addresses, in a
bytearray covering the reservation) and answers read_ranges/write_ranges like a PINE client, so the session code
cannot tell it from PineLink. step() is one battle-loop pass with the core's rules: ARMED -> RUNNING, the hash of
frame N written before any wait, a lockstep wait when a masked slot lacks frame N (one call = one vblank slept),
frames N < D neutral, capture of the 'physical pad' into OUTGOING[N + D] (and INCOMING[local_slot] with self feed),
abort and the stall limit. Its 'game state' is a rolling hash of every consumed input, so two fake guests agree
exactly when they consumed the same inputs frame by frame; perturb() makes one of them diverge on purpose.
Kit 2.0: sched=True models OPT_SCHED: a pass waits until CONTROL.sched_sealed >= N, then applies the ring entries of
frame N in seq order (writes inside the reservation land in memory; every applied write is mixed into the game state
with its frame, so an entry applied at different frames on two PCs reads as a desync); a pending entry of an earlier
frame aborts (SCHED_LATE).
Core layout 2: the model also runs the native IO gate (channel 0). io_waits = {frame: pump steps}: at the pass of that
frame a 'FIFO task' starts waiting for the disc pump, which drains after that many passes ON THIS PC (two fake guests
given different steps drain at different frames, as two PCs under different stalls do). The task runner step at the
top of each pass applies W's rules (local, seq, agreed, opened), the capture carries gate_local as aux (OUTGOING and
the self-fed entry), and POLL computes gate_agreed from every masked slot's aux; the frame a wait completes is mixed
into the game state, so a gate that opened at different frames on two PCs reads as a desync.
The guest code itself is tested in the MIPS interpreter (tools/test_netplay_core.py); this model is only a peer.
"""
import struct
import threading

from pinelink import CoreView, nc


def _mix(h, *words):
    for w in words:
        h = (((h * 33) & 0xFFFFFFFF) ^ (w & 0xFFFFFFFF)) & 0xFFFFFFFF
    return h


class FakeGuest(CoreView):
    def __init__(self, *, mode=nc.LOCKSTEP, delay=3, mask=0b11, start=nc.ANY, max_stall=0, physical=None,
                 name='fake', io_waits=None, decide_at=None, sched=False, sealed=0):
        self.lock = threading.Lock()
        self.mem = bytearray(nc.END - nc.BASE)
        self.write_ranges([(nc.CONTROL, nc.control(mode=mode, delay=delay, mask=mask, start_state=start,
                                                   max_stall=max_stall, self_feed=False, sealed=sealed,
                                                   options=(nc.OPT_MAILBOX if mask & 0b1100 else 0) |
                                                   (nc.OPT_SCHED if sched else 0)))])
        self.physical = physical or (lambda frame: nc.NEUTRAL)
        self.state = 0x6E70636F                                   # the model's 'game state'
        self.consumed = {}
        self.hashed = -1
        self.name = name
        self.vblanks = 0
        self.io_waits = dict(io_waits or {})                     # frame -> pump steps until this PC drains
        self.io_left = None                                       # the waiting task's pump steps left (None: idle)
        self.tasked = -1                                          # the frame whose task-runner step already ran
        self.opened = []                                          # frames at which a gate wait completed
        self.decide_at = decide_at                                # kit 2.0 tests: the fight is decided at this frame
        self.gate_stalls = 0                                      # vblanks a non-contributing PC waited in W
        self.applied = []                                         # (frame, seq) of every applied SCHED entry

    # -- PINE-like access
    def _at(self, address, length):
        if not nc.BASE <= address <= nc.END - length:
            raise IndexError(f'{address:08X}+{length} is outside the netplay reservation')
        return address - nc.BASE

    def read_ranges(self, ranges):
        with self.lock:
            return [bytes(self.mem[self._at(a, n):self._at(a, n) + n]) for a, n in ranges]

    def write_ranges(self, ranges):
        with self.lock:
            for address, data in ranges:
                at = self._at(address, len(data))
                self.mem[at:at + len(data)] = data

    def read(self, address, length):
        return self.read_ranges([(address, length)])[0]

    def status(self):
        return 'running'

    def close(self):
        pass

    # -- guest model
    def _u(self, address):
        return struct.unpack_from('<I', self.mem, address - nc.BASE)[0]

    def _w(self, address, value):
        struct.pack_into('<I', self.mem, address - nc.BASE, value & 0xFFFFFFFF)

    def _c(self, name):
        return self._u(nc.CONTROL + nc.F[name])

    def _set(self, name, value):
        self._w(nc.CONTROL + nc.F[name], value)

    def _entry(self, slot, frame):
        at = nc.incoming_address(slot, frame)
        if self._u(at + 8) != frame + 1:
            return None
        return bytes(self.mem[at - nc.BASE:at - nc.BASE + 8])

    def perturb(self, value=1):
        with self.lock:
            self.state ^= value

    # -- savestates (kit 1.3.0 resync tests): a pickle of the whole model, written where save_state_dir says
    save_state_dir = None

    def save_state(self, slot):
        import os
        import pickle
        import tempfile
        with self.lock:
            blob = pickle.dumps((bytes(self.mem), self.state, dict(self.consumed), self.hashed, self.io_left,
                                 self.tasked))
        folder = self.save_state_dir or tempfile.gettempdir()
        path = os.path.join(folder, f'fake-{self.name}-{slot}.state')
        with open(path, 'wb') as f:
            f.write(blob)
        return path

    def load_state(self, path):
        import pickle
        with open(path, 'rb') as f:
            mem, state, consumed, hashed, io_left, tasked = pickle.loads(f.read())
        with self.lock:
            self.mem[:] = mem
            self.state, self.consumed, self.hashed = state, consumed, hashed
            self.io_left, self.tasked = io_left, tasked              # the PC's IO state travels in a savestate

    def step(self):
        """One battle-loop pass; False when it slept a vblank waiting for input (call again)."""
        with self.lock:
            self.vblanks += 1
            if self._c('magic') != nc.MAGIC or not self._c('enable') or not self._c('mode'):
                return True
            state = self._c('state')
            if state == nc.ARMED:
                self._set('state', nc.RUNNING)
                self._set('frame', 0)
            elif state != nc.RUNNING:
                return True
            n, delay, mode = self._c('frame'), self._c('delay'), self._c('mode')
            if self._c('abort'):
                self._set('abort_reason', nc.ABORT_HOST); self._set('abort_frame', n); self._set('state', nc.ABORTED)
                self._set('waiting', 0)
                return True
            if self.tasked != n:                                  # the task runner (top of the pass, before POLL)
                if not self._task(n):
                    return False                                  # W waits for this PC's own drain (kit 2.0)
                self.tasked = n
            if self.decide_at is not None and n >= self.decide_at:
                self._set('state', nc.DECIDED); self._set('decided_frame', n); self._set('decided_state', 4)
                self._set('decided_result', 1); self._set('waiting', 0)
                return True
            if self.hashed != n:
                self._hash(n)
                self.hashed = n
            mask = self._c('mask')
            slots = [s for s in range(nc.SLOTS) if mask >> s & 1]
            unsealed = self._c('sched_enable') and self._c('sched_sealed') < n
            if mode == nc.LOCKSTEP and (unsealed or (n >= delay and any(self._entry(s, n) is None for s in slots))):
                self._set('waiting', 1)
                stall = self._c('stall_now') + 1
                self._set('stall_now', stall)
                limit = self._c('max_stall')
                if limit and stall >= limit:
                    self._set('abort_reason', nc.ABORT_STALL); self._set('abort_frame', n)
                    self._set('state', nc.ABORTED); self._set('waiting', 0)
                    return True
                return False
            if self._c('waiting'):
                stall = self._c('stall_now')
                self._set('stall_total', self._c('stall_total') + stall)
                self._set('stalled_updates', self._c('stalled_updates') + 1)
                self._set('stall_longest', max(self._c('stall_longest'), stall))
                self._set('waiting', 0); self._set('stall_now', 0)
            self._agree(n, slots, delay)
            if self._sched(n):
                self._set('sched_fail_frame', n); self._set('abort_reason', nc.ABORT_SCHED_LATE)
                self._set('abort_frame', n); self._set('state', nc.ABORTED)
                return True
            inputs = []
            for s in range(nc.SLOTS):
                raw = self._entry(s, n) if n >= delay and mask >> s & 1 else None
                if raw is None and n >= delay and mask >> s & 1:
                    self._set('missing', self._c('missing') + 1)
                inputs.append(raw or nc.NEUTRAL)
            capture = bytes(self.physical(n))
            target = n + delay
            out = nc.OUTGOING + (target % nc.OUT_SLOTS) * nc.OUT_ENTRY - nc.BASE
            self.mem[out:out + 8] = capture
            aux = self._c('gate_local')
            struct.pack_into('<I', self.mem, out + 12, aux)
            struct.pack_into('<I', self.mem, out + 8, target + 1)    # tag last
            self._set('captures', self._c('captures') + 1)
            local = self._c('local_slot')
            if mode == nc.LOCKSTEP and self._c('self_feed') and local < nc.SLOTS:
                at = nc.incoming_address(local, target) - nc.BASE
                self.mem[at:at + 8] = capture
                struct.pack_into('<2I', self.mem, at + 8, target + 1, aux)
            self.consumed[n] = tuple(inputs)
            self.state = _mix(self.state, n, *struct.unpack(f'<{2 * len(inputs)}I', b''.join(inputs)))
            self._set('frame', n + 1)
            return True

    def _task(self, n):
        """W(0) at the waiting FIFO task's pump call (spec 9); a new wait starts at the frames of io_waits. Kit 2.0:
        when the wait is agreed but this PC has not drained yet (a spectator, or a host that does not play: its aux is
        not part of the agreement), W stalls in the vblank sleep until it has, so the wait still opens at the agreed
        frame. Returns False for one stalled vblank."""
        if self.io_left is None and n in self.io_waits:
            self.io_left = self.io_waits[n]
        if self.io_left is None:
            return True
        if self.io_left > 0:
            self.io_left -= 1
        drained = self.io_left <= 0
        gated = self._c('state') == nc.RUNNING and self._c('gate_enable')
        if not gated:
            if drained:
                self.io_left = None
            return True
        local, seq, agreed = self._c('gate_local') & 0xFF, self._c('gate_seq') & 0xFF, self._c('gate_agreed') & 0xFF
        if drained and local == seq:
            self._set('gate_local', (self._c('gate_local') & ~0xFF) | ((local + 1) & 0xFF))
            local = (local + 1) & 0xFF
        if agreed == (seq + 1) & 0xFF and local != agreed:
            self.gate_stalls += 1
            return False
        if agreed == (seq + 1) & 0xFF:
            self._set('gate_seq', (self._c('gate_seq') & ~0xFF) | ((seq + 1) & 0xFF))
            self._set('gate_opened', self._c('gate_opened') + 1)
            self.io_left = None
            self.opened.append(n)
            self.state = _mix(self.state, 0x6F70656E, n)          # what the game does next depends on the frame
        return True

    def _sched(self, n):
        """Apply the ring entries of frame n (seq order); True when an earlier frame's entry is still pending."""
        if not self._c('sched_enable'):
            return False
        while True:
            seq = self._c('sched_next_seq')
            at = nc.SCHED + (seq % nc.SCHED_ENTRIES) * nc.SCHED_ENTRY
            tag, eseq, count = self._u(at), self._u(at + 4), self._u(at + 8)
            if tag == 0 or eseq != seq:
                return False
            if tag > n + 1:
                return False
            if tag < n + 1:
                return True
            for i in range(min(count, nc.SCHED_WRITES)):
                address, value, mask = (self._u(at + 16 + 12 * i + 4 * k) for k in range(3))
                if nc.BASE <= address < nc.END - 4:
                    self._w(address, (self._u(address) & ~mask) | (value & mask))
                self.state = _mix(self.state, 0x53434844, n, address, value, mask)
            self.applied.append((n, seq))
            self._set('sched_next_seq', seq + 1)

    def _agree(self, n, slots, delay):
        seq = self._c('gate_seq')
        target = ((seq & 0x7F7F7F7F) + 0x01010101) ^ (seq & 0x80808080)
        agreed = seq
        if n >= delay:
            auxes = []
            for s in slots:
                at = nc.incoming_address(s, n)
                if self._u(at + 8) != n + 1:
                    auxes = None
                    break
                auxes.append(self._u(at + 12))
            if auxes is not None:
                agreed = 0
                for c in range(4):
                    byte = (target if all((x >> 8 * c) & 0xFF == (target >> 8 * c) & 0xFF for x in auxes)
                            else seq) >> 8 * c & 0xFF
                    agreed |= byte << 8 * c
        self._set('gate_agreed', agreed)

    def _hash(self, n):
        gate = [self._c('gate_seq'), self._c('gate_agreed'), self._c('gate_opened'), self._c('sched_next_seq')]
        classes = [_mix(self.state, i, *(gate if i == 1 else ())) for i in range(8)]
        combined = _mix(0, *classes)
        at = nc.HASHES + (n % nc.HASH_SLOTS) * nc.HASH_ENTRY - nc.BASE
        struct.pack_into('<16I', self.mem, at, 0, combined, 1000 + n, 64, *classes, n, self.vblanks,
                         self._c('stall_total'), 0)
        struct.pack_into('<I', self.mem, at, n + 1)
        self._set('hash_last', combined); self._set('hash_tag', n + 1)
