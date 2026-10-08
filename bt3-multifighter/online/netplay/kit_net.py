"""The kit's network pieces: one TCP control channel and one UDP socket per side, on the same port number.

TCP (reliable, ordered): the handshake, the lobby, the match file, READY/GO, results and votes, resync states.
  Stream start: b'TTMNET' + u16 protocol version, sent by both sides first (a different version is TTM-NET-01).
  Then frames: u32 big-endian length + one type byte + payload; type b'J' = a JSON object, b'B' = a binary chunk.
  After the handshake the socket stays blocking: the session's main loop reads it with select() (poll_frames) and
  any thread may send whole frames (a lock keeps frames from interleaving). Liveness: every received frame counts;
  the kit sends PING every 5 s in the lobby and every 2 s otherwise (Channel.silent).
UDP (fast, lossy): the lockstep datagrams of netplay_session (magic 'NPS1') plus the kit's own
  TTMP ping/pong (round-trip time before the match: it also proves UDP gets through) and, with a relay, the
  TTMR registration (room + role) the relay needs to know who is who.

Direct: the host listens on TCP and UDP port P; the guest connects to host:P. The host learns the guest's UDP address
(after NAT) from its first datagram and only accepts datagrams from the guest's IP.
Relay: both sides connect to the relay's TCP port and send to its UDP port; the relay pairs the host and the guest of
the same room and forwards bytes between them (kit_relay.py).
"""
import heapq
import json
import random
import select
import socket
import struct
import threading
import time

import netproto

from kit_codes import KitError

PREAMBLE = b'TTMNET'
PING_MAGIC = b'TTMP'
REG_MAGIC, REG_ACK = b'TTMR', b'TTMA'
PING = struct.Struct('<4sBIQ')                  # magic, kind (1 ping, 2 pong), sequence, sender clock in ns
MAX_FRAME = 4 << 20
CHUNK = 64 * 1024


def address(text, default_port):
    """'host', 'host:port' or '[v6]:port' -> (host, port)."""
    text = text.strip()
    if text.startswith('['):
        host, _, rest = text[1:].partition(']')
        return host, int(rest[1:]) if rest.startswith(':') else default_port
    if text.count(':') == 1:
        host, port = text.rsplit(':', 1)
        return host, int(port)
    return text, default_port


# ---- TCP control channel --------------------------------------------------------------------------------------------------
class Channel:
    """A framed, connected TCP socket (both directions)."""

    def __init__(self, sock, peer_text=''):
        self.sock, self.peer_text = sock, peer_text
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:                          # not a TCP socket (Linux: a socketpair is AF_UNIX, EOPNOTSUPP)
            pass
        self.buffer = b''
        self.closed = False
        self.send_lock = threading.Lock()
        self.last_rx = self.last_tx = time.monotonic()
        self.transfers = 0                       # known transfers running (either direction): silence is expected
        self.sent_bytes = self.received_bytes = 0

    def send_preamble(self, protocol):
        self.sock.sendall(PREAMBLE + struct.pack('>H', protocol))

    def read_preamble(self, timeout):
        data = self._read_exact(len(PREAMBLE) + 2, timeout)
        if data[:len(PREAMBLE)] != PREAMBLE:
            raise ConnectionError('the other side is not a TTM Online Kit')
        return struct.unpack('>H', data[len(PREAMBLE):])[0]

    def _read_exact(self, n, timeout):
        end = time.monotonic() + timeout
        while len(self.buffer) < n:
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError('timed out')
            self.sock.settimeout(left)
            try:
                chunk = self.sock.recv(1 << 16)
            except socket.timeout:
                raise TimeoutError('timed out') from None
            if not chunk:
                self.closed = True
                raise ConnectionError('the connection was closed')
            self.buffer += chunk
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def send_json(self, **message):
        body = json.dumps(message).encode('utf-8')
        self._send(struct.pack('>I', len(body) + 1) + b'J' + body)

    def send_chunk(self, data):
        self._send(struct.pack('>I', len(data) + 1) + b'B' + data)

    def _send(self, frame):
        with self.send_lock:
            try:
                self.sock.sendall(frame)
            except OSError:
                self.closed = True
                raise
            self.last_tx = time.monotonic()
            self.sent_bytes += len(frame)

    def try_send(self, **message):
        """send_json that never raises (a closed channel is only marked closed)."""
        try:
            self.send_json(**message)
            return True
        except (OSError, ValueError):
            self.closed = True
            return False

    def blocking(self):
        """After the handshake: a plain blocking socket (no timeout) for the rest of its life."""
        try:
            self.sock.settimeout(None)
        except OSError:
            self.closed = True
        return self

    def poll_frames(self, limit=1 << 22):
        """Every complete frame available now, without blocking: [('J', dict) | ('B', bytes)]. Reads with select()
        so the socket's blocking mode never changes (another thread may be inside sendall)."""
        out = []
        if self.closed and not self.buffer:
            return out
        got = 0
        while not self.closed and got < limit:
            try:
                ready, _, _ = select.select([self.sock], [], [], 0)
            except (OSError, ValueError):
                self.closed = True
                break
            if not ready:
                break
            try:
                chunk = self.sock.recv(1 << 18)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                self.closed = True
                break
            if not chunk:
                self.closed = True
                break
            self.buffer += chunk
            got += len(chunk)
            self.received_bytes += len(chunk)
        while len(self.buffer) >= 4:
            length = struct.unpack('>I', self.buffer[:4])[0]
            if not 1 <= length <= MAX_FRAME:
                self.closed = True
                self.buffer = b''
                break
            if len(self.buffer) < 4 + length:
                break
            body, self.buffer = self.buffer[4:4 + length], self.buffer[4 + length:]
            self.last_rx = time.monotonic()
            if body[:1] == b'J':
                try:
                    out.append(('J', json.loads(body[1:].decode('utf-8'))))
                except ValueError:
                    pass
            elif body[:1] == b'B':
                out.append(('B', body[1:]))
        return out

    def silent(self, now=None):
        """Seconds since the last received frame (0 while a known transfer runs)."""
        now = time.monotonic() if now is None else now
        if self.transfers:
            self.last_rx = now
            return 0.0
        return now - self.last_rx

    def receive(self, timeout):
        """('J', dict) or ('B', bytes); TimeoutError / ConnectionError."""
        header = self._read_exact(4, timeout)
        length = struct.unpack('>I', header)[0]
        if not 1 <= length <= MAX_FRAME:
            raise ConnectionError(f'bad frame length {length}')
        body = self._read_exact(length, timeout)
        kind, payload = chr(body[0]), body[1:]
        if kind == 'J':
            return 'J', json.loads(payload.decode('utf-8'))
        if kind == 'B':
            return 'B', payload
        raise ConnectionError(f'unknown frame type {kind!r}')

    def expect(self, kind, timeout, step):
        """The next JSON message of type `kind`; a REFUSE from the other side or anything else is an error."""
        try:
            frame, message = self.receive(timeout)
        except TimeoutError:
            raise KitError('TTM-NET-09', seconds=int(timeout), step=step) from None
        except (ConnectionError, OSError) as error:
            raise KitError('TTM-NET-13', why=f'the connection closed during "{step}" ({error})') from None
        if frame != 'J':
            raise KitError('TTM-NET-13', why=f'unexpected data during "{step}"')
        if message.get('type') == 'REFUSE':
            raise RemoteRefusal(message)
        if message.get('type') == 'BYE':
            raise KitError('TTM-NET-13', why=message.get('why') or 'it closed the session')
        if message.get('type') != kind:
            raise KitError('TTM-NET-13', why=f'it sent {message.get("type")} during "{step}" (expected {kind})')
        return message

    def poll(self):
        """Every complete JSON message available now (non-blocking; binary chunks are dropped); [] when none."""
        return [payload for kind, payload in self.poll_frames() if kind == 'J']

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
        self.closed = True

    def close_soon(self, linger=3.0, block=False):
        """Close after a last message (REFUSE, BYE) without losing it: send FIN, read and drop whatever still
        arrives until the other side closes (or `linger` seconds), then close. Closing a socket with unread data at
        once makes Windows reset the connection, and the other PC would lose the message (a background thread, or
        inline with block=True when the process is about to end)."""
        self.closed = True
        sock = self.sock

        def drain():
            try:
                sock.shutdown(socket.SHUT_WR)
                sock.settimeout(0.2)
                end = time.monotonic() + linger
                while time.monotonic() < end:
                    try:
                        if not sock.recv(1 << 16):
                            break
                    except socket.timeout:
                        continue
            except OSError:
                pass
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
        if block:
            drain()
        else:
            threading.Thread(target=drain, daemon=True).start()


class RemoteRefusal(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message.get('text') or message.get('code'))


def relay_hello(sock, room, role, timeout=None):
    """Register with a relay on a connected TCP socket (once) and wait until it pairs us (b'OK') or refuses;
    timeout None = as long as it takes (Ctrl+C still works: the socket wakes up every second)."""
    sock.sendall(f'TTMR1 {room} {role}\n'.encode('utf-8'))
    end = None if timeout is None else time.monotonic() + timeout
    line = b''
    while not line.endswith(b'\n'):
        left = 1.0 if end is None else end - time.monotonic()
        if left <= 0:
            raise TimeoutError('the relay did not pair us in time')
        sock.settimeout(min(left, 1.0))
        try:
            chunk = sock.recv(1)
        except socket.timeout:
            continue
        if not chunk:
            raise ConnectionError('the relay closed the connection')
        line += chunk
        if len(line) > 512:
            raise ConnectionError('the relay sent garbage')
    text = line.decode('utf-8', 'replace').strip()
    if text != 'OK':
        raise RelayRefused(text)
    sock.settimeout(None)


class RelayRefused(Exception):
    pass


# ---- UDP --------------------------------------------------------------------------------------------------------------------
class Impairment:
    """Test option (--latency/--jitter/--loss): every datagram this PC SENDS is delayed by latency +- jitter ms and
    dropped with probability `loss` (seeded), like the demo's relay did for each direction."""

    def __init__(self, latency=0.0, jitter=0.0, loss=0.0, seed=1):
        self.latency, self.jitter, self.loss = latency, jitter, loss
        self.rng = random.Random(seed)
        self.active = bool(latency or jitter or loss)
        self.dropped = 0

    def due(self, now):
        if self.loss and self.rng.random() < self.loss:
            self.dropped += 1
            return None
        delay = self.latency + (self.rng.uniform(-self.jitter, self.jitter) if self.jitter else 0.0)
        return now + max(delay, 0.0) / 1000.0


class PeerSocket:
    """One UDP socket to the other PC (direct) or through a relay.

    peer: where to send (the host's address for a guest, the relay's address with a relay, None for a host that has
    not heard from its guest yet). allowed_ip: datagrams from other IPs are ignored. learn: a host takes the source
    address of the first datagram from allowed_ip as the peer (that is the guest's address after its NAT)."""

    def __init__(self, bind, peer=None, allowed_ip=None, learn=False, relay=None, impairment=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(bind)
        except OSError as error:
            self.sock.close()
            raise KitError('TTM-NET-14', what='UDP', port=bind[1], details=str(error)) from None
        self.sock.setblocking(False)
        self.peer, self.allowed_ip, self.learn = peer, allowed_ip, learn
        self.relay = relay                                   # (room, role) when the peer is a relay
        self.registered = False
        self.last_register = 0.0
        self.impair = impairment or Impairment()
        self.queue, self.counter = [], 0
        self.ignored = 0
        self.received = 0

    def local_port(self):
        return self.sock.getsockname()[1]

    def _raw_send(self, data, to=None):
        target = to or self.peer
        if target is None:
            return
        self.sent_bytes = getattr(self, 'sent_bytes', 0) + len(data)        # kit 2.1: bandwidth (stats)
        self.sent_datagrams = getattr(self, 'sent_datagrams', 0) + 1
        try:
            self.sock.sendto(data, target)
        except (BlockingIOError, ConnectionResetError, OSError):
            pass

    def send(self, data):
        if self.peer is None:
            return
        if not self.impair.active:
            self._raw_send(data)
            return
        due = self.impair.due(time.perf_counter())
        if due is not None:
            self.counter += 1
            heapq.heappush(self.queue, (due, self.counter, data))

    def pump(self):
        """Send the delayed datagrams that are due, and the relay registration (every 2 s, faster until acked)."""
        now = time.perf_counter()
        while self.queue and self.queue[0][0] <= now:
            _, _, data = heapq.heappop(self.queue)
            self._raw_send(data)
        if self.relay and now - self.last_register >= (2.0 if self.registered else 0.25):
            self.last_register = now
            room, role = self.relay
            self._raw_send(REG_MAGIC + bytes([1, 0 if role == 'host' else 1]) + room.encode('utf-8')[:64])

    def flush(self, limit=2.0):
        """Send every delayed datagram now that is still queued (test impairment), waiting until each is due (at most
        `limit` seconds): the last datagrams of a session (its final hashes, BYE) must not stay in the queue."""
        end = time.perf_counter() + limit
        while self.queue and time.perf_counter() < end:
            wait = self.queue[0][0] - time.perf_counter()
            if wait > 0:
                time.sleep(min(wait, 0.01))
            self.pump()

    def recv(self):
        """New datagrams from the peer (relay acks and foreign datagrams are consumed here)."""
        self.pump()
        out = []
        while True:
            try:
                data, source = self.sock.recvfrom(4096)
            except (BlockingIOError, InterruptedError):
                return out
            except ConnectionResetError:          # Windows: an earlier ICMP 'port unreachable'
                continue
            except OSError:
                return out
            if self.relay:
                if source != self.peer:
                    self.ignored += 1
                    continue
                if data[:4] == REG_ACK:
                    self.registered = True
                    continue
            else:
                if self.allowed_ip and source[0] != self.allowed_ip:
                    self.ignored += 1
                    continue
                if self.learn:
                    if self.peer != source:
                        if self.peer is None or data[:4] in (PING_MAGIC, b'NPS1'):
                            self.peer = source          # the guest's address after its NAT (or a new mapping)
                        else:
                            self.ignored += 1
                            continue
                elif self.peer is not None and source != self.peer and source[0] != self.allowed_ip:
                    self.ignored += 1                 # (a host whose router answers from another port is accepted
                    continue                          #  by its address; we keep sending to the forwarded port)
            self.received += 1
            out.append(data)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def ping_packet(kind, seq, clock_ns):
    return PING.pack(PING_MAGIC, kind, seq & 0xFFFFFFFF, clock_ns & 0xFFFFFFFFFFFFFFFF)


def parse_ping(data):
    if len(data) != PING.size or data[:4] != PING_MAGIC:
        return None
    _, kind, seq, clock = PING.unpack(data)
    return kind, seq, clock


def answer_pings(udp, datagrams):
    """Host side: PONG every PING (same sequence and clock), return the other datagrams."""
    rest = []
    for data in datagrams:
        p = parse_ping(data)
        if p and p[0] == 1:
            udp.send(ping_packet(2, p[1], p[2]))
        elif p is None:
            rest.append(data)
    return rest


def measure_rtt(udp, seconds=3.0, interval=0.05, first_answer=6.0, on_wait=None, extra=None):
    """Guest side: PING every `interval` for `seconds` once the first PONG came (giving up after `first_answer`
    seconds without any). Returns dict(samples, rtt_ms stats) or None when no PONG ever came (UDP blocked).
    `extra` is called each loop (the host-side control channel is polled there)."""
    seq, sent, rtts = 0, {}, []
    start = time.perf_counter()
    first = None
    last_ping = 0.0
    while True:
        now = time.perf_counter()
        if first is None and now - start > first_answer:
            return None
        if first is not None and now - first > seconds:
            break
        if now - last_ping >= interval:
            last_ping = now
            seq += 1
            sent[seq] = now
            udp.send(ping_packet(1, seq, time.perf_counter_ns()))
        for data in udp.recv():
            p = parse_ping(data)
            if p and p[0] == 2:
                rtt = (time.perf_counter_ns() - p[2]) / 1e6
                if 0 <= rtt < 5000:
                    rtts.append(rtt)
                    if first is None:
                        first = time.perf_counter()
        if extra:
            extra()
        if on_wait and first is None:
            on_wait(now - start)
        time.sleep(0.002)
    rtts.sort()
    if not rtts:
        return None
    pick = lambda q: rtts[min(len(rtts) - 1, int(q * (len(rtts) - 1) + 0.5))]
    return dict(samples=len(rtts), sent=seq, min=round(rtts[0], 1), median=round(pick(0.5), 1),
                p95=round(pick(0.95), 1), max=round(rtts[-1], 1))


def auto_delay(rtt):
    """Input delay in updates (33.4 ms each) from a measured round trip: E2's rule ceil((one way + jitter + 5) / 33.4)
    with one way = median / 2 and jitter = (p95 - min) / 2. 0 ms -> 1, 30 ms -> 2, 80 ms -> 3, 80 +- 20 ms -> 4."""
    import math
    one_way = rtt['median'] / 2.0
    jitter = max(0.0, (rtt['p95'] - rtt['min']) / 2.0)
    return max(1, min(12, math.ceil((one_way + jitter + 5.0) / 33.4)))


class HubSocket:
    """The host's one UDP socket for every guest (kit 2.0): TTMP pings from any allowed IP are answered at once (the
    handshake's round-trip measurement); lockstep datagrams (netproto MAGIC) carry the sender's member id, and are
    accepted only from that member's IP (the TCP connection's); the member's UDP address (after its NAT) is learned
    from them. send(member, data) goes to the learned address (with the test impairment)."""

    def __init__(self, bind, impairment=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(bind)
        except OSError as error:
            self.sock.close()
            raise KitError('TTM-NET-14', what='UDP', port=bind[1], details=str(error)) from None
        self.sock.setblocking(False)
        self.ips = {}                    # member -> IP (from its TCP connection)
        self.addr = {}                   # member -> (ip, port) learned from its datagrams
        self.pending = set()             # IPs of connections still in their handshake (pings only)
        self.impair = impairment or Impairment()
        self.queue, self.counter = [], 0
        self.ignored = self.received = 0

    def local_port(self):
        return self.sock.getsockname()[1]

    def allow(self, member, ip):
        self.ips[member] = ip

    def forget(self, member):
        self.ips.pop(member, None)
        self.addr.pop(member, None)

    def _raw(self, data, to):
        self.sent_bytes = getattr(self, 'sent_bytes', 0) + len(data)        # kit 2.1: bandwidth (stats)
        self.sent_datagrams = getattr(self, 'sent_datagrams', 0) + 1
        try:
            self.sock.sendto(data, to)
        except (BlockingIOError, ConnectionResetError, OSError):
            pass

    def send(self, member, data):
        to = self.addr.get(member)
        if to is None:
            return
        if not self.impair.active:
            self._raw(data, to)
            return
        due = self.impair.due(time.perf_counter())
        if due is not None:
            self.counter += 1
            heapq.heappush(self.queue, (due, self.counter, data, to))

    def pump(self):
        now = time.perf_counter()
        while self.queue and self.queue[0][0] <= now:
            _, _, data, to = heapq.heappop(self.queue)
            self._raw(data, to)

    def flush(self, limit=2.0):
        end = time.perf_counter() + limit
        while self.queue and time.perf_counter() < end:
            wait = self.queue[0][0] - time.perf_counter()
            if wait > 0:
                time.sleep(min(wait, 0.01))
            self.pump()

    def recv(self):
        """[(member, datagram)] of lockstep datagrams; pings are answered here."""
        self.pump()
        out = []
        while True:
            try:
                data, source = self.sock.recvfrom(4096)
            except (BlockingIOError, InterruptedError):
                return out
            except ConnectionResetError:
                continue
            except OSError:
                return out
            p = parse_ping(data)
            if p is not None:
                if p[0] == 1 and (source[0] in self.pending or source[0] in self.ips.values()):
                    self._raw(ping_packet(2, p[1], p[2]), source)
                continue
            if len(data) < 8 or data[:4] != netproto.MAGIC:
                self.ignored += 1
                continue
            member = data[6]
            if self.ips.get(member) != source[0]:
                self.ignored += 1
                continue
            self.addr[member] = source
            self.received += 1
            out.append((member, data))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def pair_delay(rtts, forced=None):
    """Input delay for a room: the worst one-way path between two players (a guest's datagram reaches another guest
    through the host: half of each one's round trip; the host's own half is 0), plus jitter, as auto_delay does.
    rtts: [rtt dict of each playing guest] (the host plays or not: it relays anyway)."""
    import math
    if forced:
        return max(1, min(12, int(forced)))
    if not rtts:
        return 1
    halves = sorted((r['median'] / 2.0, max(0.0, (r['p95'] - r['min']) / 2.0)) for r in rtts)
    worst = halves[-1][0] + (halves[-2][0] if len(halves) > 1 else 0.0)
    jitter = max(j for _, j in halves)
    return max(1, min(12, math.ceil((worst + jitter + 5.0) / 33.4)))
