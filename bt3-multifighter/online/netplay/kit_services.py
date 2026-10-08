"""Frame-scheduled host services (kit 2.0, Stage 4): the Tag Team Mod's own fighter-update worker runs on the host
against the host's game, and every write it makes reaches EVERY PC's game at the same frame.

The service process (kit_service.py, run by the host's installation copy's Python with that copy's tools, so the code
it builds is the code the match holds) talks to the host's session over 127.0.0.1 (one JSON line per request):
  read     [[address, length], ...]            -> the host game's bytes (hex), read now
  write    [[address, hex], ...]               -> queued
  seal                                          -> every queued write leaves: bulk first, then the control words
  status / frame / log TEXT
Writes are split in two (netplay_core OPT_SCHED, kit_lockstep.Hub.schedule):
  BULK     anything inside the service packet area 0x07800000..0x07B00000 (the transport's packet, stage code, data):
           written into the host's game at once and sent to every guest (TCP BULK {seq, host_frame, writes}); a guest
           writes it once its own game has reached host_frame (so it has consumed any earlier packet) and answers
           BULK_ACK (statistics only). The guest transport reads the packet only when the request word arrives, which
           is a control word.
  CONTROL  every other write: split into aligned words with byte masks and scheduled for one frame K on every PC
           (the host's own game included) AT ONCE (kit 2.1, pipelined): the entry names the bulk it needs, and a guest
           writes the entry into its ring only after it wrote that bulk (kit_lockstep Client.bulk_ready); until then
           its seal stays below K, so a late guest stalls at K exactly as for a late input. K = the host's frame + D + 2
           (lead 0): no acknowledgement round trip, no extra lead.
A seal happens before every read the service makes (so its writes are on their way before it waits for an answer).
The service's waits (hold acknowledged, transaction acknowledged) are reads of the host's game, which sees the
scheduled writes at K like every other PC: a hold costs about D + 4 updates more than offline.
"""
import json
import secrets
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

PACKET_LO, PACKET_HI = 0x07800000, 0x07B00000
CORE_LO = 0x07B00000
BULK_TIMEOUT = 8.0
MAX_LINE = 64 << 20


def now():
    return time.monotonic()


def words_of(writes):
    """[(address, bytes)] -> [(word address, value, mask)] (aligned words, byte masks; later writes win)."""
    out = {}
    for address, data in writes:
        for i, byte in enumerate(data):
            a = address + i
            w = a & ~3
            shift = 8 * (a & 3)
            value, mask = out.get(w, (0, 0))
            value = (value & ~(0xFF << shift)) | (byte << shift)
            mask |= 0xFF << shift
            out[w] = (value, mask)
    return [(w, v, m) for w, (v, m) in sorted(out.items())]


def split(writes):
    """(bulk, control) of [(address, bytes)]; ValueError for a write into the netplay core."""
    bulk, control = [], []
    for address, data in writes:
        end = address + len(data)
        if address < CORE_LO < end or CORE_LO <= address < CORE_LO + 0x50000:
            raise ValueError(f'a service write reaches the netplay core ({address:#x})')
        if PACKET_LO <= address and end <= PACKET_HI:
            bulk.append((address, data))
        elif address < PACKET_HI and end > PACKET_LO:
            raise ValueError(f'a service write straddles the packet area ({address:#x}+{len(data)})')
        else:
            control.append((address, data))
    return bulk, control


class Broker:
    """Host side: the service process's link into this session. ctl: the kit controller (link, session, members,
    send_to, say). poll() runs from the controller's loop; a seal that waits for guests answers later."""

    def __init__(self, ctl, python, tools, w1, log_path=None, services=('cpu_transform',)):
        self.ctl = ctl
        self.token = secrets.token_hex(16)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.setblocking(False)
        self.port = self.listener.getsockname()[1]
        self.conn = None
        self.buffer = b''
        self.queue = []                   # writes waiting for the next seal
        self.bulk_seq = 0
        self.acks = {}                    # bulk seq -> set of members that still owe BULK_ACK
        self.pending = None               # (kit 2.0) a seal waiting for bulk acks; kit 2.1 schedules at once
        self.failed = None
        self.done = None                  # the service ended by itself (the fight is over): why
        self.events = []
        self.stats = dict(reads=0, bulk=0, bulk_bytes=0, scheduled=0, words=0)
        here = Path(__file__).resolve().parent
        args = [str(python), '-B', str(here / 'kit_service.py'), '--port', str(self.port), '--token', self.token,
                '--tools', str(tools), '--w1', f'{w1:#x}', '--services', ','.join(services)]
        out = open(log_path, 'ab') if log_path else subprocess.DEVNULL
        self.process = subprocess.Popen(args, cwd=str(tools), stdin=subprocess.DEVNULL, stdout=out,
                                        stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.started = now()

    # ---- the link ------------------------------------------------------------------------------------------------
    def poll(self):
        if self.failed or (self.done is not None and self.conn is None):
            return
        if self.conn is None:
            try:
                conn, _ = self.listener.accept()
            except (BlockingIOError, OSError):
                if now() - self.started > 60 and self.process.poll() is not None:
                    self.fail('the service process ended before it connected')
                return
            conn.setblocking(False)
            self.conn = conn
        try:
            while True:
                chunk = self.conn.recv(1 << 20)
                if not chunk:
                    if self.done is None:
                        self.fail('the service process closed its link')
                    self.conn.close()
                    self.conn = None
                    self.listener.close()
                    return
                self.buffer += chunk
                if len(self.buffer) > MAX_LINE:
                    self.fail('the service sent too much at once')
                    return
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as error:
            self.fail(f'service link: {error}')
            return
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                self.handle(json.loads(line))
            except Exception as error:  # noqa: BLE001 - one bad request ends the service, never the match
                self.fail(f'{type(error).__name__}: {error}')
                return
        self.check_pending()

    def reply(self, rid, **fields):
        if self.conn is None:
            return
        data = (json.dumps(dict(id=rid, **fields), separators=(',', ':')) + '\n').encode()
        self.conn.setblocking(True)
        try:
            self.conn.sendall(data)
        finally:
            self.conn.setblocking(False)

    def handle(self, m):
        op, rid = m.get('op'), m.get('id')
        if op == 'hello':
            if m.get('token') != self.token:
                raise ValueError('wrong token')
            self.reply(rid, ok=True)
        elif op == 'read':
            if self.queue:
                raise ValueError('a read with unsealed writes (the service seals before every read)')
            self.stats['reads'] += 1
            data = self.ctl.link.read_ranges([(int(a), int(n)) for a, n in m['ranges']])
            self.reply(rid, data=[d.hex() for d in data])
        elif op == 'write':
            self.queue += [(int(a), bytes.fromhex(h)) for a, h in m['writes']]
            self.reply(rid, ok=True)
        elif op == 'seal':
            self.seal(rid)
        elif op == 'status':
            self.reply(rid, status=self.ctl.link.status())
        elif op == 'frame':
            c = self.ctl.session.control or {}
            self.reply(rid, frame=c.get('frame'), state=c.get('state'))
        elif op == 'log':
            self.ctl.say(f'Service: {m.get("text")}')
            self.reply(rid, ok=True)
        elif op == 'done':
            if self.queue:
                self.seal(None)
            self.done = str(m.get('why') or 'done')
            self.reply(rid, ok=True)
        else:
            raise ValueError(f'unknown op {op!r}')

    # ---- sealing ----------------------------------------------------------------------------------------------------
    def seal(self, rid):
        writes, self.queue = self.queue, []
        bulk, control = split(writes)
        if bulk:
            self.send_bulk(bulk)
        k = self.schedule(control, self.bulk_seq if bulk else 0)
        if rid is not None:
            self.reply(rid, ok=True, k=k)

    def send_bulk(self, bulk):
        self.ctl.link.write_ranges(bulk)                           # the host's game: at once (it is past every K)
        self.bulk_seq += 1
        c = self.ctl.session.control or {}
        frame = c.get('frame') or 0
        members = [k for k in self.ctl.session.members]
        message = dict(type='BULK', seq=self.bulk_seq, host_frame=frame,
                       writes=[[a, d.hex()] for a, d in bulk])
        for ident in members:
            self.ctl.send_to(ident, **message)
        if members:
            self.acks[self.bulk_seq] = set(members)
        self.stats['bulk'] += 1
        self.stats['bulk_bytes'] += sum(len(d) for _, d in bulk)

    def on_ack(self, ident, seq):
        left = self.acks.get(seq)
        if left is not None:
            left.discard(ident)
            if not left:
                del self.acks[seq]
        self.check_pending()

    def member_gone(self, ident):
        for seq in list(self.acks):
            self.on_ack(ident, seq)

    def check_pending(self):
        if self.pending is None:
            return
        rid, control, deadline = self.pending
        if self.acks and now() < deadline:
            return
        if self.acks:
            late = sorted({m for left in self.acks.values() for m in left})
            self.ctl.say(f'Service: {late} did not take the bulk in time (they will be re-synchronized if needed).')
            self.acks = {}
        self.pending = None
        k = self.schedule(control)
        if rid is not None:
            self.reply(rid, ok=True, k=k)

    def schedule(self, control, bulk=0):
        """Schedule the control words (after `bulk` on every guest); returns the frame K they land at (None: nothing
        to schedule)."""
        words = words_of(control)
        if not words:
            return None
        _, k = self.ctl.session.schedule(words, lead=0, bulk=bulk)
        self.stats['scheduled'] += 1
        self.stats['words'] += len(words)
        return k

    # ---- end ----------------------------------------------------------------------------------------------------------
    def fail(self, why):
        if self.failed is None:
            self.failed = why
            self.ctl.say(f'Service failed: {why}')

    def stop(self):
        try:
            if self.conn is not None:
                self.conn.close()
            self.listener.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()


class GuestBulk:
    """Guest side: BULK messages are written into this PC's game once its frame reached the host's frame."""

    def __init__(self):
        self.waiting = []
        self.written = 0                  # the newest bulk seq written into this PC's game (in order)

    def ready(self, seq):
        return self.written >= seq

    def add(self, m):
        try:
            writes = [(int(a), bytes.fromhex(h)) for a, h in m['writes']]
            for a, d in writes:
                if not (PACKET_LO <= a and a + len(d) <= PACKET_HI):
                    return False
            self.waiting.append((int(m['seq']), int(m.get('host_frame') or 0), writes))
            return True
        except (KeyError, TypeError, ValueError):
            return False

    def tick(self, link, frame, send):
        while self.waiting and (frame is None or frame >= self.waiting[0][1]):
            seq, _, writes = self.waiting.pop(0)
            link.write_ranges(writes)
            self.written = max(self.written, seq)
            send(type='BULK_ACK', seq=seq)
