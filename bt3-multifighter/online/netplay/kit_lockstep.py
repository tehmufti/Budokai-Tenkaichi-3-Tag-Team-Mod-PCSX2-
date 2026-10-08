"""The lockstep session of kit 2.0: one host (the hub), any number of guests, up to four input slots, spectators.

Every PC runs the whole game from the same savestate; only controller inputs travel (netproto version 3, UDP). The
host is the hub of a star:
  * a PLAYING PC (one input slot s) captures its own pad (netplay_core OUTGOING; the core's self feed already
    committed it to its own INCOMING[s]) and sends it to the host;
  * the host forwards every slot's inputs to every other PC, and writes the guests' slots into its own game;
  * a SPECTATOR PC (no slot) receives every slot and sends none: nobody ever waits for a spectator, and nothing a
    spectator does can reach another game;
  * every PC reports its per-frame state hashes to the host; only the host compares (each guest against its own game).
Frames N < D are neutral on every PC (the core makes them so); every slot's stream starts at frame D.

Host-side controls (the controller and kit_resync use them):
  hold(K)          no input of frame >= K is written into the host's game or forwarded to any PC: every game stops at
                   frame K (a resync's freeze point); release() undoes it.
  drop_slot(s, K)  a player left: the host writes neutral inputs for slot s from frame K on (the authoritative stream
                   every PC consumes), so the others play on.
  restart_member(m, K)  member m loaded the host's state of frame K (a resync, a rejoin or a spectator joining a
                   running fight): its comparison restarts at K with the next generation (header flags), so stray
                   datagrams of its discarded world are ignored.
A guest's Client mirrors it: reload(K) after loading a host state (its counters restart at K, generation + 1).
Desync policy (Hub.needs_resync): a member whose hash differed RESYNC_AFTER compared frames in a row, or whose rng class
differed (the games will not heal).
Logs (JSON lines): hello/attach/desync/stats/end events, one hash line per frame (this PC's own game).
"""
import json
import time

import netproto as proto
from pinelink import nc

RESYNC_AFTER = 30
WINDOW = 1900                     # a guest publishes at most this many frames ahead of its game (INCOMING: 2048)
HISTORY = 6000                    # frames of inputs the host keeps (rejoin / late spectators load newer states)
LIVE = (nc.RUNNING, nc.ABORTED, nc.DECIDED)


def neutral_item():
    return nc.NEUTRAL, 0


class Stats:
    def __init__(self):
        self.sent = self.received = self.bad = self.foreign = self.lost = self.duplicates = 0
        self.rtt = []
        self.last_seq = None

    def packet(self, seq):
        if self.last_seq is not None:
            gap = (seq - self.last_seq) & 0xFFFFFFFF
            if 1 < gap < 0x80000000:
                self.lost += gap - 1
        if self.last_seq is None or 0 < ((seq - self.last_seq) & 0xFFFFFFFF) < 0x80000000:
            self.last_seq = seq

    def add_rtt(self, now_ms, echo, hold):
        if echo:
            rtt = (now_ms - echo - hold) & 0xFFFFFFFF
            if rtt < 60000:
                self.rtt.append(rtt)
                del self.rtt[:-240]

    def rtt_ms(self, last=60):
        r = self.rtt[-last:]
        return round(sum(r) / len(r), 1) if r else None


class Compare:
    """One guest's hash reports against the host's own (host side)."""

    def __init__(self, start=0):
        self.reset(start)

    def reset(self, start):
        self.remote = {}
        self.next_needed = start          # every report below it has arrived (our hash_ack to that guest)
        self.compared = start
        self.desync = None
        self.differing = 0
        self.last_differing = None
        self.run = 0
        self.rng_differed = False

    def add(self, frame, combined, rng):
        if frame >= self.compared:
            self.remote.setdefault(frame, (combined, rng))
        while self.next_needed in self.remote or self.next_needed < self.compared:
            self.next_needed += 1

    def step(self, local, on_event):
        while self.compared in local and self.compared in self.remote:
            f = self.compared
            mine, theirs = local[f], self.remote.pop(f)
            if mine != theirs:
                if self.desync is None:
                    self.desync = f
                    on_event('desync', frame=f, local=dict(combined=mine[0], rng=mine[1]),
                             remote=dict(combined=theirs[0], rng=theirs[1]), rng_differs=mine[1] != theirs[1])
                self.differing += 1
                self.run = self.run + 1 if self.last_differing == f - 1 else 1
                self.last_differing = f
                if mine[1] != theirs[1]:
                    self.rng_differed = True
            else:
                if self.last_differing == f - 1 and self.desync is not None:
                    on_event('identical_again', frame=f, differing=self.differing)
                self.run = 0
            self.compared += 1

    def needs_resync(self):
        return self.desync is not None and (self.rng_differed or self.run >= RESYNC_AFTER)


class Member:
    """The host's view of one guest PC."""

    def __init__(self, ident, slot, name=''):
        self.id, self.slot, self.name = ident, slot, name
        self.hello = None
        self.confirmed = False
        self.acks = [0] * proto.SLOTS     # per slot: the next frame this guest still needs
        self.compare = Compare(0)
        self.stats = Stats()
        self.echo = self.echo_at = None
        self.frame = self.stall = None
        self.sched_through = 0
        self.last_rx = None
        self.bye = None
        self.generation = 0
        self.paused = False               # reloading (a resync / rejoin): reports and inputs are ignored meanwhile
        self.dropped_at = None            # a player that left: its slot is neutral from this frame on
        self.seq = 0
        self.last_send = float('-inf')
        self.last_hello = float('-inf')

    @property
    def role(self):
        return proto.ROLE_SPECTATOR if self.slot is None else proto.ROLE_PLAYER


class _Base:
    """What the host and a guest share: the game, this PC's own captures and hashes, logs."""

    def __init__(self, guest, transport, *, member, slot, mask, delay, state_sha, layout=None, epoch=0, name='',
                 redundancy=32, resend=0.016, hello_every=0.1, linger=5.0, clock=time.perf_counter, log=None,
                 hash_log=None, sched=False):
        if slot is not None and not (0 <= slot < proto.SLOTS and mask >> slot & 1):
            raise ValueError('a playing PC needs a slot inside the slot mask')
        if not mask or mask >> proto.SLOTS:
            raise ValueError(f'the slot mask names slots 0..{proto.SLOTS - 1}')
        self.guest, self.transport = guest, transport
        self.member, self.slot, self.mask, self.delay = member, slot, mask, delay
        self.slots = [s for s in range(proto.SLOTS) if mask >> s & 1]
        self.state_sha, self.layout = state_sha, nc.LAYOUT if layout is None else layout
        self.epoch = epoch
        self.session = proto.session_id(state_sha, delay, self.layout, epoch)
        self.name = name or f'member{member}'
        self.redundancy, self.resend, self.hello_every, self.linger = redundancy, resend, hello_every, linger
        self.clock, self.log_file, self.hash_file = clock, log, hash_log
        self.inputs = {s: {} for s in self.slots}             # slot -> {frame: (raw8, aux)}
        self.have = {s: delay for s in self.slots}            # slot -> every frame below it is in self.inputs
        self.written = {s: delay for s in self.slots}         # slot -> next frame to commit into this PC's game
        self.local_next = delay                               # next own capture to read from OUTGOING
        self.hash_next = 0
        self.hashes = {}                                      # frame -> (combined, rng) of this PC's game
        self.control = None
        self.events = []
        self.started_at = self.running_at = None
        self.decided = None
        self.result = None
        self.finish_at = None
        self.hold_at = None
        self.window = dict(t=None)
        self.generation = 0
        self.own_aux = {}                                     # frame -> this PC's gate word (a PC without a slot)
        self.sched_on = bool(sched)                           # netplay_core OPT_SCHED (frame-scheduled host writes)

    # ---- logging
    def event(self, kind, **fields):
        row = dict(t=round(self.clock(), 4), wall=round(time.time(), 3), event=kind, member=self.member,
                   epoch=self.epoch)
        row.update(fields)
        self.events.append(row)
        del self.events[:-400]
        if self.log_file:
            self.log_file.write(json.dumps(row) + '\n')
            self.log_file.flush()

    def ms(self, now):
        return int(now * 1000) & 0xFFFFFFFF

    # ---- this PC's game
    def attach(self):
        """Write this PC's per-machine words into the game waiting paused before the fight (or accept a late attach:
        a per-machine copy loaded unpaused, waiting at a frame <= D). Returns CONTROL."""
        c = self.guest.control()
        want_slot = nc.NO_SLOT if self.slot is None else self.slot
        late = (c['state'] == nc.RUNNING and 0 < c['frame'] <= self.delay and c['local_slot'] == want_slot
                and c['magic'] == nc.MAGIC and c['layout'] == self.layout and c['mode'] == nc.LOCKSTEP
                and c['enable'] and c['delay'] == self.delay)
        if not late:
            problems = []
            if c['magic'] != nc.MAGIC or c['layout'] != self.layout:
                problems.append(f'no netplay core (magic {c["magic"]:08X}, layout {c["layout"]})')
            elif c['mode'] != nc.LOCKSTEP or not c['enable']:
                problems.append(f'core mode {c["mode"]} enable {c["enable"]}: lockstep needed')
            elif c['delay'] != self.delay:
                problems.append(f'core delay {c["delay"]} != session delay {self.delay}')
            elif c['mask'] != self.mask:
                problems.append(f'core slot mask {c["mask"]:#x} != session mask {self.mask:#x}')
            elif c['state'] not in (nc.ARMED, nc.RUNNING) or (c['state'] == nc.RUNNING and c['frame'] > 0):
                problems.append(f'core state {c["state"]} frame {c["frame"]}: attach before the fight starts')
            if problems:
                raise RuntimeError('; '.join(problems))
            self.guest.configure(local_slot=want_slot, self_feed=0 if self.slot is None else 1)
        self.started_at = self.clock()
        self.event('attach', late=late, slot=self.slot, mask=self.mask, session=self.session,
                   control={k: c[k] for k in ('state', 'frame', 'delay', 'mask', 'mode', 'local_slot')})
        return c

    def read_local(self, n):
        """This PC's new captures (OUTGOING) of its own slot (a PC without a slot keeps only their aux words: the
        host's gate words stand for a reloaded guest's in a resync table)."""
        found = self.guest.outgoing(self.local_next, n + self.delay)
        if self.slot is None:
            while self.local_next in found:
                self.own_aux[self.local_next] = found[self.local_next][1] if self.layout >= 2 else 0
                self.local_next += 1
            for f in [f for f in self.own_aux if f < self.local_next - HISTORY]:
                del self.own_aux[f]
            return 0
        before = self.local_next
        own = self.inputs[self.slot]
        while self.local_next in found:
            raw, aux = found[self.local_next]
            own[self.local_next] = (raw, aux if self.layout >= 2 else 0)
            self.local_next += 1
        self.advance_have(self.slot)
        return self.local_next - before

    def advance_have(self, s):
        got = self.inputs[s]
        while self.have[s] in got:
            self.have[s] += 1

    # ---- kit 2.1: a player joins a running hub
    def add_slot(self, s, K):
        """Slot s exists from frame K on (a frame-scheduled entry of frame K seats it and adds it to every game's
        mask): its inputs are needed from K."""
        if s in self.slots:
            return
        self.slots = sorted(self.slots + [s])
        self.mask |= 1 << s
        self.inputs[s] = {}
        self.have[s] = self.written[s] = max(K, self.delay)
        self.event('slot_added', slot=s, K=K)

    def become_player(self, s, K):
        """This PC (a spectator) plays slot s from frame K: its captures (OUTGOING, already made every update) are
        its slot's inputs from K on - frames it captured before it knew stay neutral - and this kit writes them into
        its own game like any other slot (no self feed: the core's local slot only picks the view)."""
        self.add_slot(s, K)
        own = self.inputs[s]
        start = max(K, self.delay)
        for f in range(start, max(start, self.local_next)):
            own[f] = neutral_item()
        self.local_next = max(self.local_next, start)
        self.slot = s
        self.self_commit = True
        self.joined_at = start                    # the host's (neutral) inputs of this slot below it are still taken
        self.guest.configure(local_slot=s, self_feed=0)
        self.advance_have(s)
        self.event('became_player', slot=s, K=K, first_capture=self.local_next)

    def read_hashes(self, n):
        found = self.guest.hashes(self.hash_next, n)
        while self.hash_next in found:
            e = found[self.hash_next]
            self.hashes[self.hash_next] = (e['combined'], e['classes'][0])
            if self.hash_file:
                self.hash_file.write(json.dumps(dict(f=self.hash_next, h=e['combined'], c=e['classes'],
                                                     g=e['game_frame'], w=e['words'], k=e['clock'],
                                                     e=self.epoch)) + '\n')
            self.hash_next += 1

    def commit(self, limit):
        """Write every slot this PC does not capture itself into its game, frames below `limit` (and below hold_at)."""
        for s in self.slots:
            if s == self.slot and not getattr(self, 'self_commit', False):
                continue
            frames = {}
            got = self.inputs[s]
            f = self.written[s]
            top = min(self.have[s], limit if self.hold_at is None else min(limit, self.hold_at))
            while f < top:
                frames[f] = got[f]
                f += 1
            if frames:
                self.guest.publish(s, frames)
                self.written[s] = f

    def blocks_for(self, acks, skip, cap=None, skip_from=None):
        """[(slot, first, items)] of every slot but `skip` from the receiver's acks on (contiguous, below cap); kit 2.1:
        with skip_from (the frame a member joined a running hub with that slot), `skip`'s frames below it too."""
        out = []
        for s in self.slots:
            if s == skip and skip_from is None:
                continue
            first = max(acks[s], self.delay)
            top = self.have[s] if cap is None else min(self.have[s], cap)
            if s == skip:
                top = min(top, skip_from)
            if first < top and first not in self.inputs[s]:
                continue                                      # older than the kept history: that PC needs a state
            if first >= top:
                continue
            items = [self.inputs[s][f] for f in range(first, min(top, first + proto.MAX_BLOCK))]
            out.append((s, first, items))
        return out

    def track_decided(self, c, now):
        if c['state'] == nc.DECIDED and self.decided is None:
            self.decided = dict(frame=c['decided_frame'], state=c['decided_state'], result=c['decided_result'], t=now)
            self.event('decided', frame=c['decided_frame'], director=c['decided_state'], result=c['decided_result'])

    def flush(self):
        flush = getattr(self.transport, 'flush', None)
        if flush:
            flush()


class Hub(_Base):
    """The host's session: its own game plus one Member per guest PC."""

    def __init__(self, guest, transport, *, members=(), **kwargs):
        kwargs.setdefault('member', 1)
        super().__init__(guest, transport, **kwargs)
        self.members = {}
        for m in members:
            self.add_member(*m)
        self.dropped = {}                                     # slot -> frame from which the host writes neutral
        self.sched_log = []                                   # [(seq, K, writes)] every entry this fight scheduled

    def add_member(self, ident, slot, name=''):
        if slot is not None and (slot not in self.slots or slot == self.slot or
                                 any(m.slot == slot for m in self.members.values())):
            raise ValueError(f'slot {slot} is not free')
        m = Member(ident, slot, name)
        self.members[ident] = m
        return m

    def seat_member(self, ident, s, K):
        """Kit 2.1: spectator `ident` plays slot s from frame K (a player who joins a running hub)."""
        m = self.members.get(ident)
        if m is None or m.slot is not None or any(o.slot == s for o in self.members.values()) or s == self.slot:
            raise ValueError(f'member {ident} cannot take slot {s}')
        self.dropped.pop(s, None)
        if s in self.slots:                                   # a slot a player left (neutral so far): its new player
            got = self.inputs[s]                              # from K on (K is beyond every neutral frame sent)
            if self.have[s] > K or any(f >= K for f in got):
                raise ValueError(f'slot {s} already has inputs at frame {K}')
            for f in range(self.have[s], K):
                got[f] = neutral_item()
            self.advance_have(s)
        else:
            self.add_slot(s, K)
        m.slot = s
        m.joined_at = max(K, self.delay)                     # its frames below K still go to it (blocks_for)

    def remove_member(self, ident, frame=None):
        """A guest left: a spectator just goes; a player's slot turns neutral from `frame` (default: the newest frame
        any PC could still need, so nothing already consumed changes)."""
        m = self.members.pop(ident, None)
        if m is not None and m.slot is not None:
            self.drop_slot(m.slot, frame)
        return m

    # ---- frame-scheduled host writes (netplay_core OPT_SCHED)
    def schedule(self, writes, lead=2, bulk=0):
        """Write [(address, value, mask)] into every PC's game at one agreed frame K: at least D + 2 + lead updates
        after the host's own game (no PC can be further than D frames ahead of the host), written into the host's ring
        now and sent to every guest until it acknowledges. Returns (seq, K). Before the fight starts and after it
        ended every game applies it at once. bulk (kit 2.1, host services): the bulk message every guest writes before
        it writes this entry (so the host never waits for the guests' acknowledgements); lead 0 is enough then: a
        guest that is late only stalls at K, as for a late input."""
        if not self.sched_on:
            raise RuntimeError('this match has no SCHED ring (OPT_SCHED)')
        writes = [(int(a), int(v) & 0xFFFFFFFF, int(m) & 0xFFFFFFFF) for a, v, m in writes]
        out = []
        for i in range(0, len(writes), nc.SCHED_WRITES):
            chunk = writes[i:i + nc.SCHED_WRITES]
            c = self.guest.control()
            f = c['frame'] if c['state'] in LIVE else 0
            K = f + self.delay + 2 + lead
            seq = len(self.sched_log)
            if seq - min([m.sched_through for m in self.members.values()] + [seq]) >= nc.SCHED_ENTRIES - 1:
                raise RuntimeError('the SCHED ring is full (a guest acknowledges nothing)')
            self.guest.write_sched(seq, K, chunk)
            self.sched_log.append((seq, K, chunk, bulk & 0xFFFF) if bulk else (seq, K, chunk))
            self.event('scheduled', seq=seq, K=K, frame=f, writes=[[f'{a:#010x}', v, m] for a, v, m in chunk])
            out.append((seq, K))
        return out[-1] if out else None

    def sched_count(self):
        return len(self.sched_log)

    def drop_slot(self, s, frame=None):
        if frame is None:
            frame = self.have[s]
        frame = max(frame, self.have[s])
        self.dropped[s] = frame
        self.event('slot_dropped', slot=s, frame=frame)

    # ---- one iteration
    def tick(self):
        now = self.clock()
        if self.result is not None:
            return self.result
        c = self.control = self.guest.control()
        n = c['frame'] if c['state'] in LIVE else 0
        if c['state'] == nc.RUNNING and self.running_at is None:
            self.running_at = now
            self.event('running', start_game_frame=c['start_game_frame'])
        self.track_decided(c, now)
        new_local = self.read_local(n) if c['state'] == nc.RUNNING else 0
        for source, datagram in self.transport.recv():
            self.receive(source, datagram, now)
        self.fill_dropped(n)
        self.commit(1 << 62)
        if c['state'] in LIVE:
            self.read_hashes(n)
        for m in self.members.values():
            m.compare.step(self.hashes, lambda kind, **f: self.event(kind, guest=m.id, **f))
        self.prune()
        for m in list(self.members.values()):
            self.send_to(m, now, new_local, c)
        self.periodic(now, c)
        return self.finish(now, c, n)

    def fill_dropped(self, n):
        """Neutral inputs for every dropped slot up to the frames the others could need (n + D + window)."""
        for s, start in self.dropped.items():
            got = self.inputs[s]
            top = max(n, start) + self.delay + 2          # never runs ahead of the host's own game
            f = max(self.have[s], start)
            while f < top:
                got.setdefault(f, neutral_item())
                f += 1
            self.advance_have(s)

    def prune(self):
        low = min([m.compare.compared for m in self.members.values()] + [self.hash_next]) - 64
        for f in [f for f in self.hashes if f < low]:
            del self.hashes[f]
        for s in self.slots:
            cut = self.have[s] - HISTORY
            if cut > self.delay:
                got = self.inputs[s]
                for f in [f for f in got if f < cut]:
                    del got[f]

    def receive(self, source, datagram, now):
        try:
            msg = proto.parse(datagram)
        except proto.ProtocolError:
            return
        m = self.members.get(msg['member'])
        if m is None or (source is not None and source != m.id):
            return
        if msg['kind'] == proto.HELLO:
            self.on_hello(m, msg)
            return
        if msg['session'] != self.session or m.hello is None or (msg['flags'] & 0xFF) != (m.generation & 0xFF):
            m.stats.foreign += 1
            return
        m.stats.received += 1
        m.stats.packet(msg['seq'])
        m.last_rx = now
        m.echo, m.echo_at = msg['t_send'], now
        m.stats.add_rtt(self.ms(now), msg['echo'], msg['hold'])
        if msg['kind'] == proto.BYE:
            if m.bye is None:
                m.bye = msg['reason']
                self.event('member_bye', guest=m.id, reason=msg['reason'])
            return
        m.confirmed = True
        m.frame, m.stall = msg['frame'], msg['stall']
        m.sched_through = max(m.sched_through, msg['sched_through'])
        m.acks = [max(a, b) for a, b in zip(m.acks, msg['acks'])]
        if m.slot is not None and m.slot not in self.dropped:
            got = self.inputs[m.slot]
            for s, first, items in msg['blocks']:
                if s != m.slot:
                    continue                                  # a guest only ever sends its own slot
                for i, (raw, aux) in enumerate(items):
                    f = first + i
                    if f < self.delay or (self.hold_at is not None and f >= self.hold_at + self.delay):
                        continue
                    if f in got:
                        m.stats.duplicates += 1
                        continue
                    got[f] = (raw, aux if self.layout >= 2 else 0)
            self.advance_have(m.slot)
        if m.paused:
            return                                            # its world is being replaced: no comparison
        for frame, combined, rng in msg['hashes']:
            m.compare.add(frame, combined, rng)

    def on_hello(self, m, msg):
        mine = dict(delay=self.delay, layout=self.layout, state_tag=self.state_sha[:16], epoch=self.epoch & 0xFFFF,
                    mask=self.mask)
        theirs = dict(delay=msg['delay'], layout=msg['layout'], state_tag=msg['state_tag'], epoch=msg['epoch'],
                      mask=msg['mask'])
        if mine != theirs or msg['slot'] != m.slot:
            if theirs['epoch'] != mine['epoch']:
                m.stats.foreign += 1
                return
            self.event('hello_mismatch', guest=m.id, mine=mine, theirs=theirs, slot=msg['slot'], want_slot=m.slot)
            return
        if m.hello is None:
            m.hello = msg
            self.event('hello', guest=m.id, name=msg['name'], slot=m.slot)

    def packet(self, m, kind, now, c=None, reason=0):
        hold = int((now - m.echo_at) * 1000) if m.echo_at is not None else 0
        common = dict(echo=m.echo or 0, hold=hold)
        if kind == proto.HELLO:
            return proto.hello(self.member, self.session, 0, self.ms(now), delay=self.delay, layout=self.layout,
                               redundancy=self.redundancy, state_sha=self.state_sha, epoch=self.epoch, name=self.name,
                               slot=self.slot, role=proto.ROLE_HUB, mask=self.mask, **common)
        m.seq += 1
        if kind == proto.BYE:
            return proto.bye(self.member, self.session, m.seq, self.ms(now), reason, **common)
        m.stats.sent += 1
        acks = [0] * proto.SLOTS
        if m.slot is not None:
            acks[m.slot] = self.have[m.slot]
        sched = proto.sched_fit(self.sched_log[m.sched_through:]) if self.sched_on else []
        datagram = proto.data(self.member, self.session, m.seq, self.ms(now), frame=c['frame'] if c else 0,
                              stall=c['stall_total'] if c else 0, acks=acks,
                              blocks=self.blocks_for(m.acks, m.slot, self.hold_at, getattr(m, 'joined_at', None)),
                              hash_ack=m.compare.next_needed, sealed=self.sealed_for(m, c),
                              sched_through=len(self.sched_log), sched=sched, **common)
        return self._flag(datagram, m.generation)

    @staticmethod
    def _flag(datagram, generation):
        return datagram[:7] + bytes([generation & 0xFF]) + datagram[8:]

    def sealed_for(self, m, c=None):
        """The newest frame every PC may run: the host schedules nothing below its frame + D + 2."""
        if not self.sched_on:
            return proto.NO_SCHED
        f = c['frame'] if c and c['state'] in LIVE else 0
        return f + self.delay + 1

    def send_to(self, m, now, new_local, c):
        if m.hello is None or not m.confirmed:
            if now - m.last_hello >= self.hello_every:
                m.last_hello = now
                self.transport.send(m.id, self.packet(m, proto.HELLO, now))
            if m.hello is None:
                return
        if new_local or now - m.last_send >= self.resend:
            m.last_send = now
            self.transport.send(m.id, self.packet(m, proto.DATA, now, c))

    # ---- resync / rejoin support
    def hold(self, K):
        self.hold_at = K
        self.event('hold', K=K)

    def release(self):
        self.event('release', K=self.hold_at)
        self.hold_at = None

    def highest_written(self):
        """The newest frame of any guest slot written into the host's game."""
        return max([self.written[s] - 1 for s in self.slots if s != self.slot] or [self.delay - 1])

    def pause_member(self, ident):
        m = self.members[ident]
        m.paused = True
        self.event('member_paused', guest=ident)

    def restart_member(self, ident, K, sched_count=None):
        """Member `ident` now runs the host's world from frame K: its comparison restarts at K, its acks at K, the
        next generation; sched_count = the entries the host had scheduled when it saved that world (all of them are
        in it)."""
        m = self.members[ident]
        if sched_count is not None:
            m.sched_through = sched_count
        m.generation += 1
        m.compare.reset(K)
        m.acks = [min(a, K) for a in m.acks]
        m.paused = False
        m.confirmed = False
        self.event('member_restart', guest=ident, K=K, generation=m.generation)

    def host_aux(self, f):
        if self.slot is not None:
            item = self.inputs[self.slot].get(f)
            return item[1] if item else 0
        return self.own_aux.get(f, 0)

    def adopt_host_aux(self, ident, K):
        """Member `ident` will run a copy of the host's world from frame K: the gate words of its frames
        K..K+D-1 become the host's (its own were captured in the world it discards). Done before release(), so the
        host's game and every other PC consume the same words."""
        m = self.members[ident]
        if m.slot is None or self.layout < 2:
            return
        got = self.inputs[m.slot]
        for f in range(K, K + self.delay):
            if f in got:
                got[f] = (got[f][0], self.host_aux(f))

    def table(self, K):
        """{slot: {frame: (raw8, aux)}} for frames K..K+D-1 (None where a frame has not arrived)."""
        return {s: {f: self.inputs[s].get(f) for f in range(K, K + self.delay)} for s in self.slots}

    def complete(self, K):
        return all(self.have[s] >= K + self.delay for s in self.slots)

    def neutral_fill(self, K):
        """Make every missing frame below K + D neutral (the host is authoritative)."""
        for s in self.slots:
            for f in range(self.delay, K + self.delay):
                self.inputs[s].setdefault(f, neutral_item())
            self.advance_have(s)

    def members_needing_resync(self):
        return [m.id for m in self.members.values() if not m.paused and m.compare.needs_resync()]

    # ---- end
    def periodic(self, now, c):
        w = self.window
        if w['t'] is None:
            w['t'] = now
            return
        if now - w['t'] < 1.0:
            return
        self.window = dict(t=now)
        self.event('stats', frame=c['frame'], state=c['state'], waiting=c['waiting'], stall_total=c['stall_total'],
                   have={str(s): self.have[s] for s in self.slots}, hold=self.hold_at,
                   members={str(m.id): dict(slot=m.slot, frame=m.frame, rtt=m.stats.rtt_ms(), lost=m.stats.lost,
                                            compared=m.compare.compared, desync=m.compare.desync,
                                            acks=m.acks) for m in self.members.values()},
                   udp_bytes=getattr(self.transport, 'sent_bytes', None),
                   udp_datagrams=getattr(self.transport, 'sent_datagrams', None))

    def finish(self, now, c, n):
        if self.result is not None:
            return self.result
        reason = None
        if c['state'] == nc.ABORTED:
            reason = 'aborted'
        elif c['state'] == nc.DECIDED:
            d = self.decided['frame']
            players = [m for m in self.members.values() if m.slot is not None and m.bye is None]
            done = all(m.compare.compared > d for m in players)
            if done or now - self.decided['t'] > self.linger:
                reason = 'decided'
        if reason is None:
            return 'running'
        if self.finish_at is None:
            self.finish_at = now + (0.3 if reason == 'decided' else 0.0)
        if now < self.finish_at:
            return 'running'
        for m in self.members.values():
            for _ in range(3):
                self.transport.send(m.id, self.packet(m, proto.DATA, now, c))
            for _ in range(3):
                self.transport.send(m.id, self.packet(m, proto.BYE, now,
                                                      reason=proto.BYE_DONE if reason == 'decided' else
                                                      proto.BYE_ABORTED))
        self.flush()
        self.result = reason
        self.event('end', reason=reason, **self.summary())
        return reason

    def say_bye(self, reason=proto.BYE_ABORTED):
        now = self.clock()
        for m in self.members.values():
            for _ in range(3):
                self.transport.send(m.id, self.packet(m, proto.BYE, now, reason=reason))
        self.flush()

    def summary(self):
        c = self.control or {}
        return dict(frame=c.get('frame'), state=c.get('state'), stall_total=c.get('stall_total'),
                    hashes=self.hash_next, decided=self.decided, epoch=self.epoch,
                    members={str(m.id): dict(slot=m.slot, compared=m.compare.compared, desync=m.compare.desync,
                                             differing=m.compare.differing, rtt=m.stats.rtt_ms(), lost=m.stats.lost,
                                             received=m.stats.received, bye=m.bye)
                             for m in self.members.values()},
                    seconds=round(self.clock() - self.started_at, 2) if self.started_at is not None else None)

    def status(self):
        c = self.control or {}
        return dict(frame=c.get('frame'), state=c.get('state'), waiting=c.get('waiting'),
                    stall_now=c.get('stall_now'), stall_total=c.get('stall_total'), decided=self.decided,
                    hold=self.hold_at, members={str(m.id): dict(slot=m.slot, name=m.name, frame=m.frame,
                                                                 rtt_ms=m.stats.rtt_ms(), compared=m.compare.compared,
                                                                 desync=m.compare.desync,
                                                                 differing=m.compare.differing,
                                                                 lost=m.stats.lost, connected=m.hello is not None,
                                                                 silent=None if m.last_rx is None else
                                                                 round(self.clock() - m.last_rx, 1))
                                                for m in self.members.values()})


class Client(_Base):
    """A guest's session: its own game and one link to the host."""

    def __init__(self, guest, transport, **kwargs):
        super().__init__(guest, transport, **kwargs)
        self.hub_hello = None
        self.hub_confirmed = False
        self.hub_need = self.delay        # the next frame of our slot the host still needs
        self.hub_hash_need = 0            # the next hash report the host still needs
        self.hub_frame = None
        self.hub_bye = None
        self.sealed = proto.NO_SCHED
        self.sched_written = 0            # entries written into this PC's SCHED ring (seq order)
        self.sched_k = {}                 # seq -> K of entries seen but not written yet
        self.bulk_ready = None            # kit 2.1: bulk seq -> True once this PC wrote that host-service bulk
        self.sealed_written = None        # the newest sched_sealed this kit wrote into its game
        self.stats = Stats()
        self.echo = self.echo_at = None
        self.seq = 0
        self.last_send = self.last_hello = float('-inf')
        self.last_rx = None
        self.frozen = False               # a resync is replacing this PC's game: nothing touches it meanwhile

    def tick(self):
        now = self.clock()
        if self.result is not None:
            return self.result
        if self.frozen:
            return 'running'
        c = self.control = self.guest.control()
        n = c['frame'] if c['state'] in LIVE else 0
        if c['state'] == nc.RUNNING and self.running_at is None:
            self.running_at = now
            self.event('running', start_game_frame=c['start_game_frame'])
        self.track_decided(c, now)
        new_local = self.read_local(n) if c['state'] == nc.RUNNING else 0
        for datagram in self.transport.recv():
            self.receive(datagram, now)
        self.commit(max(n, self.delay) + WINDOW)
        if c['state'] in LIVE:
            self.read_hashes(n)
        for f in [f for f in self.hashes if f < self.hub_hash_need - 64]:
            del self.hashes[f]
        self.send(now, new_local, c)
        self.periodic(now, c)
        return self.finish(now, c, n)

    def receive(self, datagram, now):
        try:
            msg = proto.parse(datagram)
        except proto.ProtocolError:
            self.stats.bad += 1
            return
        if msg['member'] != 1:
            self.stats.foreign += 1
            return
        if msg['kind'] == proto.HELLO:
            mine = dict(delay=self.delay, layout=self.layout, state_tag=self.state_sha[:16],
                        epoch=self.epoch & 0xFFFF, mask=self.mask)
            theirs = dict(delay=msg['delay'], layout=msg['layout'], state_tag=msg['state_tag'], epoch=msg['epoch'],
                          mask=msg['mask'])
            if mine != theirs:
                if theirs['epoch'] != mine['epoch']:
                    self.stats.foreign += 1
                elif self.result is None:
                    self.event('hello_mismatch', mine=mine, theirs=theirs)
                    self.result = 'mismatch'
                return
            if self.hub_hello is None:
                self.hub_hello = msg
                self.event('hello', name=msg['name'])
            return
        if msg['session'] != self.session or self.hub_hello is None or \
                (msg['flags'] & 0xFF) != (self.generation & 0xFF):
            self.stats.foreign += 1
            return
        self.stats.received += 1
        self.stats.packet(msg['seq'])
        self.last_rx = now
        self.echo, self.echo_at = msg['t_send'], now
        self.stats.add_rtt(self.ms(now), msg['echo'], msg['hold'])
        if msg['kind'] == proto.BYE:
            if self.hub_bye is None:
                self.hub_bye = msg['reason']
                self.event('hub_bye', reason=msg['reason'])
            return
        self.hub_confirmed = True
        self.hub_frame = msg['frame']
        self.sealed = msg['sealed']
        if self.sched_on:
            self.take_sched(msg)
        if self.slot is not None and msg['acks'][self.slot] > self.hub_need:
            self.hub_need = msg['acks'][self.slot]
        if msg['hash_ack'] > self.hub_hash_need:
            self.hub_hash_need = msg['hash_ack']
        for s, first, items in msg['blocks']:
            joined = getattr(self, 'joined_at', None) if s == self.slot else None
            if (s == self.slot and joined is None) or s not in self.inputs:
                continue
            got = self.inputs[s]
            for i, (raw, aux) in enumerate(items):
                f = first + i
                if joined is not None and f >= joined:
                    break                                     # this PC's own inputs from the frame it joined
                if f >= self.delay and f not in got:
                    got[f] = (raw, aux if self.layout >= 2 else 0)
            self.advance_have(s)

    def take_sched(self, msg):
        """Write the host's scheduled entries into this PC's ring (seq order, tag last), then raise sched_sealed to the
        host's seal, never past the frame of an entry this PC has not written yet."""
        for e in sorted(msg.get('sched') or [], key=lambda e: e[0]):
            seq, K, writes = e[:3]
            bulk = e[3] if len(e) > 3 else 0
            if seq < self.sched_written:
                continue
            self.sched_k[seq] = K
            if seq == self.sched_written and bulk and self.bulk_ready is not None and not self.bulk_ready(bulk):
                self.event('sched_waits_bulk', seq=seq, K=K, bulk=bulk)
                continue
            if seq == self.sched_written:
                self.guest.write_sched(seq, K, writes)
                self.sched_k.pop(seq, None)
                self.sched_written += 1
                self.event('sched_written', seq=seq, K=K)
        S = msg['sealed']
        if S == proto.NO_SCHED:
            return
        if self.sched_written < msg['sched_through']:
            K = self.sched_k.get(self.sched_written)
            if K is None:
                return                    # an entry this PC has not even seen: keep the old seal
            S = min(S, K - 1)
        if self.sealed_written is None or S > self.sealed_written:
            self.guest.set_sealed(S)
            self.sealed_written = S

    def packet(self, kind, now, c=None, reason=0):
        hold = int((now - self.echo_at) * 1000) if self.echo_at is not None else 0
        common = dict(echo=self.echo or 0, hold=hold)
        if kind == proto.HELLO:
            return proto.hello(self.member, self.session, 0, self.ms(now), delay=self.delay, layout=self.layout,
                               redundancy=self.redundancy, state_sha=self.state_sha, epoch=self.epoch, name=self.name,
                               slot=self.slot, role=proto.ROLE_SPECTATOR if self.slot is None else proto.ROLE_PLAYER,
                               mask=self.mask, **common)
        self.seq += 1
        if kind == proto.BYE:
            datagram = proto.bye(self.member, self.session, self.seq, self.ms(now), reason, **common)
        else:
            self.stats.sent += 1
            acks = [self.have.get(s, 0) for s in range(proto.SLOTS)]
            blocks = []
            if self.slot is not None:
                first = max(self.hub_need, self.delay)
                own = self.inputs[self.slot]
                items = [own[f] for f in range(first, min(self.have[self.slot], first + proto.MAX_BLOCK))]
                if items:
                    blocks.append((self.slot, first, items))
            hashes = []
            for f in range(self.hub_hash_need, self.hub_hash_need + proto.MAX_HASHES):
                if f not in self.hashes:
                    break
                hashes.append((f,) + self.hashes[f])
            datagram = proto.data(self.member, self.session, self.seq, self.ms(now), frame=c['frame'] if c else 0,
                                  stall=c['stall_total'] if c else 0, acks=acks, blocks=blocks, hashes=hashes,
                                  sched_through=self.sched_written, **common)
        return Hub._flag(datagram, self.generation)

    def send(self, now, new_local, c):
        if self.hub_hello is None or not self.hub_confirmed:
            if now - self.last_hello >= self.hello_every:
                self.last_hello = now
                self.transport.send(self.packet(proto.HELLO, now))
            if self.hub_hello is None:
                return
        if new_local or now - self.last_send >= self.resend:
            self.last_send = now
            self.transport.send(self.packet(proto.DATA, now, c))

    def reload(self, K, table=None, sched_count=None):
        """This PC loaded the host's state of frame K: own captures continue from K + D, every slot's frames
        K..K+D-1 come from the table (and are written now), the comparison restarts at K, next generation;
        sched_count = the entries the host had scheduled when it saved that state (they are all in it)."""
        self.generation += 1
        if sched_count is not None:
            self.sched_written = sched_count
            self.sched_k = {}
            self.sealed_written = None
        D = self.delay
        for s in self.slots:
            got = self.inputs[s]
            for f in [f for f in got if f >= K]:
                del got[f]
            if table is not None:
                for f, item in table[s].items():
                    got[f] = item if item is not None else neutral_item()
            self.have[s] = K
            self.advance_have(s)
            self.written[s] = K
        if self.slot is not None:
            self.local_next = K + D
            # this PC's own frames K..K+D-1 were self-fed in the discarded world: write them again
            frames = {f: self.inputs[self.slot][f] for f in range(K, K + D) if f in self.inputs[self.slot]}
            if frames:
                self.guest.publish(self.slot, frames)
        self.hash_next = K
        self.hashes = {f: v for f, v in self.hashes.items() if f < K}
        self.hub_need = max(self.delay, K) if self.slot is None else K + D
        self.hub_hash_need = K
        self.hub_confirmed = False
        self.event('reload', K=K, generation=self.generation)

    def periodic(self, now, c):
        w = self.window
        if w['t'] is None:
            w['t'] = now
            return
        if now - w['t'] < 1.0:
            return
        self.window = dict(t=now)
        self.event('stats', frame=c['frame'], state=c['state'], waiting=c['waiting'], stall_total=c['stall_total'],
                   have={str(s): self.have[s] for s in self.slots}, hub_frame=self.hub_frame,
                   rtt=self.stats.rtt_ms(), lost=self.stats.lost, received=self.stats.received,
                   udp_bytes=getattr(self.transport, 'sent_bytes', None))

    def finish(self, now, c, n):
        if self.result is not None:
            return self.result
        reason = None
        if c['state'] == nc.ABORTED:
            reason = 'aborted'
        elif self.hub_bye is not None:
            reason = 'decided' if c['state'] == nc.DECIDED or self.hub_bye == proto.BYE_DONE else 'hub_bye'
        elif c['state'] == nc.DECIDED and now - self.decided['t'] > self.linger + 10:
            reason = 'decided'
        if reason is None:
            return 'running'
        if self.finish_at is None:
            self.finish_at = now + (0.2 if reason == 'decided' else 0.0)
        if now < self.finish_at:
            return 'running'
        for _ in range(3):
            self.transport.send(self.packet(proto.DATA, now, c))
        self.flush()
        self.result = reason
        self.event('end', reason=reason, **self.summary())
        return reason

    def say_bye(self, reason=proto.BYE_LEFT):
        now = self.clock()
        for _ in range(3):
            self.transport.send(self.packet(proto.BYE, now, reason=reason))
        self.flush()

    def summary(self):
        c = self.control or {}
        return dict(frame=c.get('frame'), state=c.get('state'), stall_total=c.get('stall_total'),
                    hashes=self.hash_next, decided=self.decided, epoch=self.epoch, rtt=self.stats.rtt_ms(),
                    lost=self.stats.lost, received=self.stats.received, sent=self.stats.sent,
                    seconds=round(self.clock() - self.started_at, 2) if self.started_at is not None else None)

    def status(self):
        c = self.control or {}
        return dict(frame=c.get('frame'), state=c.get('state'), waiting=c.get('waiting'),
                    stall_now=c.get('stall_now'), stall_total=c.get('stall_total'), decided=self.decided,
                    hub_frame=self.hub_frame, rtt_ms=self.stats.rtt_ms(), lost=self.stats.lost,
                    connected=self.hub_hello is not None,
                    silent=None if self.last_rx is None else round(self.clock() - self.last_rx, 1))
