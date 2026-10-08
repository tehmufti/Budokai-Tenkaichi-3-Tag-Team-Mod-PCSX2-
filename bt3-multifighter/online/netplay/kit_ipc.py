"""The kit's two processes on one PC talk JSON lines over 127.0.0.1 (standard library only).

  UI process (Tk lobby or console)  <->  SESSION process (its child: the network, PINE and PCSX2)

The session listens on an ephemeral 127.0.0.1 port and writes data/session.json {port, token, pid}; the first line a
UI sends is {"hello": token} (128-bit, given to the session in the environment TTM_IPC_TOKEN), anything else closes
the connection. One UI at a time: a new UI that knows the token replaces the old one (Play online.cmd re-attaches a
UI after a crash; the match goes on meanwhile). Then:
  UI -> session  {"cmd": name, ...}
  session -> UI  {"ev": name, ...}     the first one after a hello is "snapshot" (everything a fresh UI needs)
Why two processes: no GIL contention between the session's 1-5 ms tick and Tk, and a UI crash does not end a match.
"""
import json
import os
import secrets
import select
import socket
import time
from pathlib import Path

MAX_LINE = 1 << 20
TOKEN_ENV = 'TTM_IPC_TOKEN'


def new_token():
    return secrets.token_hex(16)


MAX_PENDING = 16 << 20                # bytes the session keeps for a UI that does not read (then it is let go)


class _Lines:
    """JSON lines over a socket. nonblocking=True (the session's end): send() never waits for the other process; what
    the socket cannot take now waits in `out` and leaves on the next send()/poll(). A lobby window that hangs (Tk does
    not run while its window is dragged on Windows) must never stall the session's lockstep loop."""

    def __init__(self, sock, nonblocking=False):
        self.sock = sock
        self.buffer = b''
        self.closed = False
        self.nonblocking = nonblocking
        self.out = bytearray()
        if nonblocking:
            sock.setblocking(False)

    def send(self, obj):
        data = (json.dumps(obj, separators=(',', ':'), default=str) + '\n').encode('utf-8')
        if self.closed:
            return False
        if not self.nonblocking:
            try:
                self.sock.sendall(data)
                return True
            except OSError:
                self.closed = True
                return False
        self.out += data
        return self.flush()

    def flush(self):
        while self.out and not self.closed:
            try:
                n = self.sock.send(self.out[:1 << 16])
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                self.closed = True
                return False
            del self.out[:n]
        if len(self.out) > MAX_PENDING:
            self.close()
            return False
        return not self.closed

    def poll(self, timeout=0.0):
        out = []
        if self.closed:
            return out
        if self.out:
            self.flush()
        while True:
            try:
                ready, _, _ = select.select([self.sock], [], [], timeout)
            except (OSError, ValueError):
                self.closed = True
                break
            timeout = 0.0
            if not ready:
                break
            try:
                chunk = self.sock.recv(1 << 16)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                self.closed = True
                break
            if not chunk:
                self.closed = True
                break
            self.buffer += chunk
            if len(self.buffer) > MAX_LINE and b'\n' not in self.buffer:
                self.closed = True
                break
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                value = json.loads(line.decode('utf-8'))
            except ValueError:
                continue
            if isinstance(value, dict):
                out.append(value)
        return out

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
        self.closed = True


class Server:
    """The session process's end: accept()s UIs, poll() gives their commands, send() emits events."""

    def __init__(self, token, port=0):
        self.token = token
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(('127.0.0.1', port))
        self.listener.listen(4)
        self.listener.setblocking(False)
        self.port = self.listener.getsockname()[1]
        self.pending = []                     # (lines, since) not yet authenticated
        self.ui = None
        self.attached_at = None
        self.detached_at = time.monotonic()
        self.on_attach = None                 # callable(): send the snapshot

    def write_info(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(port=self.port, token=self.token, pid=os.getpid(), at=time.time())),
                       encoding='utf-8')
        tmp.replace(path)

    def poll(self):
        """Commands from the attached UI (authenticating new connections on the way)."""
        now = time.monotonic()
        while True:
            try:
                conn, _ = self.listener.accept()
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            self.pending.append((_Lines(conn, nonblocking=True), now))
        keep = []
        for lines, since in self.pending:
            msgs = lines.poll()
            if msgs:
                if msgs[0].get('hello') == self.token:
                    if self.ui is not None:
                        self.ui.send(dict(ev='replaced'))
                        self.ui.close()
                    self.ui = lines
                    self.attached_at = now
                    if self.on_attach:
                        self.on_attach()
                    rest = msgs[1:]
                    if rest:
                        self._early = rest
                else:
                    lines.close()
            elif not lines.closed and now - since < 10:
                keep.append((lines, since))
            else:
                lines.close()
        self.pending = keep
        out = list(getattr(self, '_early', []))
        self._early = []
        if self.ui is not None:
            out += self.ui.poll()
            if self.ui.closed:
                self.ui = None
                self.detached_at = now
        return out

    def send(self, ev, **fields):
        if self.ui is None:
            return False
        ok = self.ui.send(dict(ev=ev, **fields))
        if not ok:
            self.ui = None
            self.detached_at = time.monotonic()
        return ok

    def attached(self):
        return self.ui is not None

    def detached_for(self):
        return 0.0 if self.ui is not None else time.monotonic() - self.detached_at

    def close(self):
        if self.ui:
            self.ui.close()
        for lines, _ in self.pending:
            lines.close()
        try:
            self.listener.close()
        except OSError:
            pass


class Client:
    """The UI's end."""

    def __init__(self, port, token, timeout=10.0):
        sock = socket.create_connection(('127.0.0.1', int(port)), timeout=timeout)
        sock.settimeout(None)
        self.lines = _Lines(sock)
        self.lines.send(dict(hello=token))

    def send(self, cmd, **fields):
        return self.lines.send(dict(cmd=cmd, **fields))

    def poll(self, timeout=0.0):
        return self.lines.poll(timeout)

    @property
    def closed(self):
        return self.lines.closed

    def close(self):
        self.lines.close()


def read_info(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
