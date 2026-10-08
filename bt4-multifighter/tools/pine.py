"""Small standard-library PCSX2 PINE client (TCP on Windows, a Unix socket elsewhere).

Protocol: https://github.com/PCSX2/pcsx2/blob/master/pcsx2/PINE.cpp
Addresses are emulated EE addresses, not Windows process addresses. Batches are
not atomic snapshots. Save/load replies acknowledge queuing, not completion.
PCSX2 handles one connected PINE client at a time: always close the client.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import sys
import time
from array import array
from pathlib import Path

U32 = struct.Struct("<I")
MAX_REQUEST = 650000
MAX_REPLY = 450000
WIDTH_OP = {1: 0, 2: 1, 4: 2, 8: 3}
# PCSX2 serves PINE on loopback TCP only on Windows; on Linux (and macOS) it is an AF_UNIX socket.
WINDOWS = os.name == "nt"
# PINE_DEFAULT_SLOT (PINE.h). Hexadecimal, so the BT4 port's slot rewrite never changes PCSX2's rule.
PCSX2_DEFAULT_SLOT = 0x6D6B
# The launcher's final socket path (it may have to drop an unusable XDG_RUNTIME_DIR for PCSX2).
SOCKET_ENV = "TAGTEAM_PINE_SOCKET"
SUN_PATH_BYTES = 107  # PCSX2 Strlcpy()s the name into sockaddr_un.sun_path[108]
UCRED = struct.Struct("=iII")  # SO_PEERCRED: pid_t pid, uid_t uid, gid_t gid
# Windows may refuse a new loopback connection for a moment when its short-lived ports run low (WSAEADDRINUSE
# 10048, WSAENOBUFS 10055; a watcher opens several a second). Nothing was sent yet, so the connection is tried
# again after these pauses (1.6 s in all) before the error reaches the caller (live, Sept 28: a match setup
# failed at Ready on the first 10048).
CONNECT_RETRY = (0.05, 0.15, 0.4, 1.0)
TRANSIENT_CONNECT = frozenset({10048, 10055})
_runtime_guard = None
_runtime_pid = None


def set_runtime_guard(guard, pid=None):
    """Bind all clients in this host (including trainer threads) to its runtime.

    On a Unix socket the listener must also be process `pid` (SO_PEERCRED): PCSX2
    unlinks the socket path before binding, so a second emulator can take it over.
    A bound EmulatorLifetime.require_alive carries its emulator's PID itself.
    """
    global _runtime_guard, _runtime_pid
    if pid is None:
        pid = getattr(getattr(guard, "__self__", None), "pid", None)
    _runtime_guard = guard
    _runtime_pid = pid if type(pid) is int else None


def require_runtime():
    if _runtime_guard is not None:
        _runtime_guard()


class PineError(RuntimeError):
    pass


def transient_connect(error):
    """A refused loopback connect that another try can pass (TRANSIENT_CONNECT), never a closed PCSX2."""
    return getattr(error, "winerror", None) in TRANSIENT_CONNECT or getattr(error, "errno", None) in TRANSIENT_CONNECT


def connect_tcp(port, retry=None, sleep=None):
    """Blocking loopback connect (see PineClient.connect), tried again after each pause in `retry`
    (CONNECT_RETRY) while Windows refuses it for want of ports; a closed emulator (require_runtime)
    ends the waiting."""
    for pause in (*(CONNECT_RETRY if retry is None else retry), None):
        try:
            return socket.create_connection(("127.0.0.1", port), None)
        except OSError as error:
            if pause is None or not transient_connect(error):
                raise
        (sleep or time.sleep)(pause)
        require_runtime()


def socket_path(slot, environ=None):
    """The Unix socket PCSX2 serves PINE `slot` on (PINEServer::Initialize, PCSX2 2.6 to 2.8).

    $XDG_RUNTIME_DIR/pcsx2.sock ($TMPDIR on macOS), or /tmp/pcsx2.sock when the variable
    is unset, plus ".<slot>" for every slot but PCSX2's default. The folder is joined as
    PCSX2 joins it, so a trailing slash gives "//" (the same file), and a name longer than
    sun_path is cut where PCSX2 cuts it. TAGTEAM_PINE_SOCKET, when set, is used as is.
    """
    environ = os.environ if environ is None else environ
    override = environ.get(SOCKET_ENV)
    if override:
        return override
    if type(slot) is not int:
        raise ValueError("The PINE slot must be an integer")
    folder = environ.get("TMPDIR" if sys.platform == "darwin" else "XDG_RUNTIME_DIR")
    path = "/tmp/pcsx2.sock" if folder is None else folder + "/pcsx2.sock"
    if slot != PCSX2_DEFAULT_SLOT:
        path += f".{slot}"
    encoded = os.fsencode(path)
    return os.fsdecode(encoded[:SUN_PATH_BYTES]) if len(encoded) > SUN_PATH_BYTES else path


def peer_pid(sock):
    """PID of the process that made the connected Unix socket listen, or None if unsupported."""
    option = getattr(socket, "SO_PEERCRED", None)
    if option is None:
        return None
    return UCRED.unpack(sock.getsockopt(socket.SOL_SOCKET, option, UCRED.size))[0]


def require_peer(sock, path):
    expected = _runtime_pid
    if expected is None:
        return
    actual = peer_pid(sock)
    if actual is not None and actual != expected:
        raise PineError(f"The PINE socket {path} belongs to process {actual}, not to the emulator this "
                        f"launcher started (process {expected}). Close the other PCSX2 and start again.")


class PineClient:
    def __init__(self, port=28012, timeout=5.0, batch_commands=32768):
        if not 1 <= batch_commands <= 32768:
            raise ValueError("batch_commands must be 1..32768")
        self.port, self.timeout, self.batch_commands = port, timeout, batch_commands
        self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    def connect(self):
        require_runtime()
        if self.sock is None:
            if not WINDOWS:
                return self._connect_unix()
            # Connect blocking, then bound every send/recv with the timeout. On Windows a
            # timed connect costs ~9 ms even on loopback (0.2 ms blocking), and the watcher
            # opens a client per poll. A loopback handshake cannot hang: a closed or
            # saturated port is refused by the kernel in the same ~2 s either way.
            self.sock = connect_tcp(self.port)
            try:
                self.sock.settimeout(self.timeout)
                require_runtime()
            except BaseException:
                self.close()
                raise
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return self

    def _connect_unix(self):
        # No TCP_NODELAY: it fails with EOPNOTSUPP on AF_UNIX, where writes are not coalesced.
        path = socket_path(self.port)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            # A Unix listener with a full backlog blocks connect(), so it is bounded too.
            self.sock.settimeout(self.timeout)
            try:
                self.sock.connect(path)
            except OSError as error:
                # Same error type (callers tell a missing socket from a refused one), naming the path.
                if error.errno is not None:
                    raise type(error)(error.errno, error.strerror or os.strerror(error.errno), path) from error
                raise type(error)(f"{str(error) or 'connection failed'} (PCSX2 PINE socket {path!r})") from error
            require_runtime()
            require_peer(self.sock, path)
        except BaseException:
            self.close()
            raise
        return self

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _receive(self, count):
        result = bytearray()
        while len(result) < count:
            part = self.sock.recv(count - len(result))
            if not part:
                raise PineError("PCSX2 closed the PINE connection")
            result.extend(part)
        return bytes(result)

    def _exchange(self, commands, expected=None):
        require_runtime()
        if not commands or len(commands) + 4 > MAX_REQUEST:
            raise ValueError("Empty or oversized PINE request")
        self.connect()
        try:
            self.sock.sendall(U32.pack(len(commands) + 4) + commands)
            size = U32.unpack(self._receive(4))[0]
            if not 5 <= size <= MAX_REPLY:
                raise PineError(f"Invalid PINE reply length: {size}")
            reply = self._receive(size - 4)
        except (OSError, PineError):
            self.close()
            raise
        if reply[0] != 0:
            raise PineError("PCSX2 rejected the PINE request (a game may not be running)")
        data = reply[1:]
        if expected is not None and len(data) != expected:
            raise PineError(f"Expected {expected} reply bytes, received {len(data)}")
        return data

    @staticmethod
    def _range(address, length):
        if not isinstance(address, int) or not isinstance(length, int):
            raise ValueError("Address and length must be integers")
        if not 0 <= address <= 0xFFFFFFFF or not 0 <= length <= 0x100000000 - address:
            raise ValueError("Range must fit the 32-bit EE address space")

    @staticmethod
    def _spans(address, length):
        end = address + length
        while address < end:
            width = next(w for w in (8, 4, 2, 1) if address % w == 0 and address + w <= end)
            yield address, width
            address += width

    def read_ranges(self, ranges):
        """Read [(EE address, byte count), ...], batching across range boundaries."""
        ranges = list(ranges)
        for address, length in ranges:
            self._range(address, length)
        result, packet, expected, count = bytearray(), bytearray(), 0, 0
        if (isinstance(self.batch_commands, int) and array('I').itemsize == 4
                and all(not length or (address % 8 == 0 and length % 8 == 0)
                        for address, length in ranges)):
            # Lazy RAM audits use aligned 64 KiB reads. Encode the same op3 /
            # little-endian-address records in bulk instead of making thousands
            # of Python span generators and individual pack/extend operations.
            # Batch boundaries and ordering still span the caller's ranges.
            for address, length in ranges:
                while length:
                    commands = min(length // 8, self.batch_commands - count)
                    addresses = array('I', range(address, address + commands * 8, 8))
                    if sys.byteorder != 'little':
                        addresses.byteswap()
                    packed = addresses.tobytes()
                    chunk = bytearray(b'\x03') * (commands * 5)
                    for byte in range(4):
                        chunk[byte + 1::5] = packed[byte::4]
                    packet.extend(chunk)
                    expected += commands * 8
                    count += commands
                    address += commands * 8
                    length -= commands * 8
                    if count == self.batch_commands:
                        result.extend(self._exchange(packet, expected))
                        packet, expected, count = bytearray(), 0, 0
        else:
            # Keep the general mixed-width protocol path byte-for-byte for
            # unaligned ranges, including odd leading/trailing bytes.
            for address, length in ranges:
                for current, width in self._spans(address, length):
                    packet.extend(bytes([WIDTH_OP[width]]) + U32.pack(current))
                    expected += width
                    count += 1
                    if count == self.batch_commands:
                        result.extend(self._exchange(packet, expected))
                        packet, expected, count = bytearray(), 0, 0
        if packet:
            result.extend(self._exchange(packet, expected))
        offset, values = 0, []
        for _, length in ranges:
            values.append(bytes(result[offset:offset + length]))
            offset += length
        return values

    def read(self, address, length):
        return self.read_ranges([(address, length)])[0]

    def write_ranges(self, ranges):
        """Write [(EE address, bytes), ...]. Failure can leave partial writes."""
        ranges = [(address, bytes(data)) for address, data in ranges]
        for address, data in ranges:
            self._range(address, len(data))
        packet, count = bytearray(), 0
        if (isinstance(self.batch_commands, int) and array('I').itemsize == 4
                and all(not data or (address % 8 == 0 and len(data) % 8 == 0)
                        for address, data in ranges)):
            # Loading pictures and manifests are aligned; encode the same op7 records
            # (op, little-endian address, 8 data bytes) in bulk, exactly like reads,
            # with the batch boundaries carried across ranges as the span loop does.
            for address, data in ranges:
                offset, length = 0, len(data)
                while length:
                    commands = min(length // 8, self.batch_commands - count)
                    addresses = array('I', range(address, address + commands * 8, 8))
                    if sys.byteorder != 'little':
                        addresses.byteswap()
                    packed = addresses.tobytes()
                    chunk = bytearray(b'\x07') * (commands * 13)
                    for byte in range(4):
                        chunk[byte + 1::13] = packed[byte::4]
                    for byte in range(8):
                        chunk[byte + 5::13] = data[offset + byte:offset + commands * 8:8]
                    packet.extend(chunk)
                    count += commands
                    address += commands * 8
                    offset += commands * 8
                    length -= commands * 8
                    if count == self.batch_commands:
                        self._exchange(packet, 0)
                        packet, count = bytearray(), 0
            if packet:
                self._exchange(packet, 0)
            return
        for address, data in ranges:
            for current, width in self._spans(address, len(data)):
                offset = current - address
                packet.extend(bytes([WIDTH_OP[width] + 4]) + U32.pack(current))
                packet.extend(data[offset:offset + width])
                count += 1
                if count == self.batch_commands:
                    self._exchange(packet, 0)
                    packet, count = bytearray(), 0
        if packet:
            self._exchange(packet, 0)

    def write(self, address, data):
        self.write_ranges([(address, data)])

    def read_u32(self, address):
        return U32.unpack(self.read(address, 4))[0]

    def write_u32(self, address, value):
        self.write(address, U32.pack(value))

    @staticmethod
    def _strings(data, count):
        values, offset = [], 0
        for _ in range(count):
            if offset + 4 > len(data):
                raise PineError("Truncated PINE string length")
            size = U32.unpack_from(data, offset)[0]
            offset += 4
            if size < 1 or offset + size > len(data) or data[offset + size - 1] != 0:
                raise PineError("Invalid PINE string")
            values.append(data[offset:offset + size - 1].decode("utf-8", errors="replace"))
            offset += size
        if offset != len(data):
            raise PineError("Unexpected trailing PINE string bytes")
        return values

    def status(self):
        value = U32.unpack(self._exchange(b"\x0f", 4))[0]
        return {0: "running", 1: "paused", 2: "shutdown"}.get(value, f"unknown:{value}")

    def info(self):
        # PCSX2 2.6.x and v2.5.211 fail MsgVersion (0x08) while no game runs (2.8.x answers), so a
        # shut-down emulator reports only its status; "version" is present whenever a game is.
        info = {"status": self.status()}
        if info["status"] != "shutdown":
            info["version"] = self._strings(self._exchange(b"\x08"), 1)[0]
            values = self._strings(self._exchange(b"\x0b\x0c\x0d\x0e"), 4)
            info.update(zip(("title", "serial", "crc", "game_version"), values))
        return info

    def require_game(self, serial=None, crc=None):
        info = self.info()
        if info["status"] == "shutdown":
            raise PineError("No game is running")
        for key, expected in (("serial", serial), ("crc", crc)):
            if expected is not None and info.get(key, "").lower() != expected.lower():
                raise PineError(f"Wrong game {key}: expected {expected}, received {info.get(key)!r}")
        return info

    def _state(self, opcode, slot):
        if not isinstance(slot, int) or not 0 <= slot <= 255:
            raise ValueError("PINE state slot must be 0..255")
        self._exchange(bytes([opcode, slot]), 0)

    def save_state(self, slot):
        """Queue saving a slot; PCSX2 may still be writing after this returns."""
        self._state(9, slot)

    def load_state(self, slot):
        """Queue loading a slot; PCSX2 may still be loading after this returns."""
        self._state(10, slot)


def main():
    number = lambda value: int(value, 0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=28012)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--expect-serial")
    parser.add_argument("--expect-crc")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info")
    read = commands.add_parser("read", help="Read EE memory to a file or hexadecimal stdout")
    read.add_argument("address", type=number)
    read.add_argument("length", type=number)
    read.add_argument("--out", type=Path)
    write = commands.add_parser("write", help="Write explicitly supplied bytes to EE memory")
    write.add_argument("address", type=number)
    source = write.add_mutually_exclusive_group(required=True)
    source.add_argument("--hex")
    source.add_argument("--file", type=Path)
    for command in ("save", "load"):
        sub = commands.add_parser(command, help=f"Queue {command} of a savestate slot")
        sub.add_argument("slot", type=number)
    args = parser.parse_args()
    try:
        with PineClient(args.port, args.timeout) as client:
            if args.expect_serial or args.expect_crc:
                client.require_game(args.expect_serial, args.expect_crc)
            if args.command == "info":
                print(json.dumps(client.info(), indent=2))
            elif args.command == "read":
                data = client.read(args.address, args.length)
                if args.out:
                    args.out.write_bytes(data)
                    print(f"Read {len(data)} bytes to {args.out}")
                else:
                    print(data.hex(" "))
            elif args.command == "write":
                data = args.file.read_bytes() if args.file else bytes.fromhex(args.hex)
                client.write(args.address, data)
                print(f"Wrote {len(data)} bytes at 0x{args.address:08X}")
            else:
                getattr(client, f"{args.command}_state")(args.slot)
                print(f"Queued {args.command} of slot {args.slot}; completion is asynchronous")
    except (OSError, ValueError, PineError) as error:
        print(f"PINE: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
