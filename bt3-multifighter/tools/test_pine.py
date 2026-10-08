"""Protocol tests use a fake socket only; they never contact an emulator.

The Unix-socket tests at the end start a fake PINE server in a child process
(under /tmp: the scratch path is longer than sun_path) on Linux only.
"""
import errno
import os
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
import random
from pathlib import Path
from unittest.mock import Mock, patch

import pine
from pine import PineClient, PineError


class FakeSocket:
    def __init__(self):
        self.memory = bytearray(range(256)) * 16
        self.pending = bytearray()
        self.requests = []
        self.states = []
        self.closed = False
        self.fail = False
        self.status = 0
        self.fragment = 3
        self.options = []

    def setsockopt(self, *option):
        self.options.append(option)

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True

    def recv(self, size):
        result = bytes(self.pending[:min(size, self.fragment)])  # Deliberately fragment replies.
        del self.pending[:len(result)]
        return result

    def sendall(self, request):
        assert struct.unpack_from("<I", request)[0] == len(request)
        self.requests.append(bytes(request))
        if self.fail:
            self.pending.extend(b"\x05\x00\x00\x00\xff")
            return
        result, offset = bytearray(), 4
        strings = {8: "PCSX2 fixture", 11: "Dragon Ball Z", 12: "SLUS-21678",
                   13: "428113c2", 14: "1.00"}
        while offset < len(request):
            op = request[offset]
            offset += 1
            if op < 8:
                address = struct.unpack_from("<I", request, offset)[0]
                offset += 4
                width = 1 << (op % 4)
                assert address % width == 0
                if op < 4:
                    result.extend(self.memory[address:address + width])
                else:
                    self.memory[address:address + width] = request[offset:offset + width]
                    offset += width
            elif op in strings:
                value = strings[op].encode() + b"\0"
                result.extend(struct.pack("<I", len(value)) + value)
            elif op in (9, 10):
                self.states.append((op, request[offset]))
                offset += 1
            elif op == 15:
                result.extend(struct.pack("<I", self.status))
            else:
                raise AssertionError(op)
        self.pending.extend(struct.pack("<I", len(result) + 5) + b"\0" + result)


def legacy_read_packets(ranges, batch):
    """Frozen pre-fast-path encoder, including exact range-spanning batches."""
    packets,packet,count= [],bytearray(),0
    for address,length in ranges:
        for current,width in PineClient._spans(address,length):
            packet.extend(bytes([{1:0,2:1,4:2,8:3}[width]])+struct.pack('<I',current))
            count+=1
            if count==batch:
                packets.append(struct.pack('<I',len(packet)+4)+packet)
                packet,count=bytearray(),0
    if packet:packets.append(struct.pack('<I',len(packet)+4)+packet)
    return [bytes(p) for p in packets]


def legacy_write_packets(ranges, batch):
    """Frozen span-loop write encoder, including exact range-spanning batches."""
    packets,packet,count= [],bytearray(),0
    for address,data in ranges:
        for current,width in PineClient._spans(address,len(data)):
            offset=current-address
            packet.extend(bytes([{1:0,2:1,4:2,8:3}[width]+4])+struct.pack('<I',current))
            packet.extend(data[offset:offset+width])
            count+=1
            if count==batch:
                packets.append(struct.pack('<I',len(packet)+4)+packet)
                packet,count=bytearray(),0
    if packet:packets.append(struct.pack('<I',len(packet)+4)+packet)
    return [bytes(p) for p in packets]


class AddressPattern:
    """Read-only sparse fixture covering the whole 32-bit address space."""
    def __getitem__(self,key):
        start,stop=key.start,key.stop
        data=bytes(range(256))*((stop-start+start%256+255)//256)
        return data[start%256:start%256+stop-start]


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.sock = FakeSocket()
        # The wire protocol is the same on both transports; pin the TCP connector on every platform.
        transport = patch("pine.WINDOWS", True)
        transport.start()
        self.addCleanup(transport.stop)
        self.connector = patch("pine.socket.create_connection", return_value=self.sock)
        self.connector.start()
        self.addCleanup(self.connector.stop)
        self.client = PineClient(batch_commands=3)
        self.addCleanup(self.client.close)

    def test_connect_is_blocking_but_every_exchange_keeps_the_timeout(self):
        # A timed connect costs ~9 ms per client on Windows; the bound belongs on send/recv.
        self.client.info()
        self.assertEqual(self.connector.target.create_connection.call_args.args, (("127.0.0.1", 28011), None))
        self.assertEqual(self.sock.timeout, self.client.timeout)

    def test_info_and_identity_guard(self):
        info = self.client.require_game("SLUS-21678", "428113C2")
        self.assertEqual(info["status"], "running")
        self.assertEqual(info["game_version"], "1.00")
        with self.assertRaises(PineError):
            self.client.require_game(crc="00000000")

    def test_shutdown_info_has_no_game_commands(self):
        self.sock.status = 2
        self.assertEqual(self.client.info(), {"status": "shutdown"})
        # Only the status request: MsgVersion (0x08) and the game queries need a running VM.
        self.assertEqual([request[4:] for request in self.sock.requests], [b"\x0f"])
        with self.assertRaises(PineError):
            self.client.require_game()

    def test_version_is_asked_only_while_a_game_runs_as_pcsx2_26_requires(self):
        # PCSX2 2.6.x and v2.5.211 answer MsgVersion with IPC_FAIL when no VM exists.
        sendall = self.sock.sendall
        def fail_version_without_vm(request):
            if self.sock.status == 2 and b"\x08" in request[4:5]:
                self.sock.requests.append(bytes(request)); self.sock.pending.extend(b"\x05\x00\x00\x00\xff")
            else:
                sendall(request)
        self.sock.sendall = fail_version_without_vm
        self.sock.status = 2
        self.assertEqual(self.client.info(), {"status": "shutdown"})
        for status, name in ((0, "running"), (1, "paused")):
            self.sock.status = status
            info = self.client.info()
            self.assertEqual((info["status"], info["version"], info["serial"]), (name, "PCSX2 fixture", "SLUS-21678"))
            self.assertEqual(list(info), ["status", "version", "title", "serial", "crc", "game_version"])

    def test_unaligned_ranges_and_batches(self):
        ranges = [(1, 47), (129, 13), (256, 0), (400, 64)]
        expected = [bytes(self.sock.memory[a:a + n]) for a, n in ranges]
        self.assertEqual(self.client.read_ranges(ranges), expected)
        self.assertGreater(len(self.sock.requests), 2)
        self.assertTrue(all(len(r) <= 4 + 3 * 5 for r in self.sock.requests))

    def test_writes_and_u32(self):
        before = bytes(self.sock.memory)
        self.client.write_ranges([(3, b"hello world!"), (64, bytes(range(50)))])
        self.assertEqual(self.sock.memory[3:15], b"hello world!")
        self.assertEqual(self.sock.memory[64:114], bytes(range(50)))
        self.assertEqual(self.sock.memory[15:64], before[15:64])
        self.client.write_u32(129, 0x12345678)
        self.assertEqual(self.client.read_u32(129), 0x12345678)

    def test_slot_commands(self):
        self.client.save_state(9)
        self.client.load_state(255)
        self.assertEqual(self.sock.states, [(9, 9), (10, 255)])
        for slot in (-1, 256):
            with self.assertRaises(ValueError):
                self.client.save_state(slot)

    def test_validate_all_ranges_before_writing(self):
        with self.assertRaises(ValueError):
            self.client.write_ranges([(10, b"abc"), (0xFFFFFFFF, b"ab")])
        self.assertEqual(self.sock.requests, [])
        self.assertEqual(self.client.read(0, 0), b"")
        with self.assertRaises(ValueError):
            self.client.read(0xFFFFFFFF, 2)

    def test_fail_reply(self):
        self.sock.fail = True
        with self.assertRaises(PineError):
            self.client.read(0, 4)

    def assert_wire_read(self,ranges,batch):
        self.client.batch_commands=batch;self.sock.requests.clear()
        expected=[bytes(self.sock.memory[a:a+n])for a,n in ranges]
        packets=legacy_read_packets(ranges,batch)
        self.assertEqual(self.client.read_ranges(iter(ranges)),expected)
        self.assertEqual(self.sock.requests,packets)

    def test_aligned_all_tiny_batch_boundaries_and_empty_ranges_match_old_wire(self):
        for batch in range(1,9):
            for first in range(7):
                for second in range(7):
                    self.assert_wire_read([(256,first*8),(7,0),(0,second*8),(120,8),(0,0)],batch)
        self.assert_wire_read([],1)
        self.assert_wire_read([(1,0),(0xFFFFFFFF,0)],32768)

    def test_large_batch_boundary_and_top_address_keep_exact_protocol(self):
        self.sock.memory=AddressPattern();self.sock.fragment=65536
        for batch in (1,3,127,32768):
            length=(batch+1)*8
            self.assert_wire_read([(0x100000,length),(0xFFFFFFF8,8),(0xFFFFFFFF,0)],batch)
        self.assert_wire_read([(0xFFFFFFFF,1)],3)
        self.assert_wire_read([(0xFFFFFFF7,9),(0xFFFFFFF8,8)],3)
        self.assertTrue(all(len(p)<=650000 for p in self.sock.requests))

    def test_mixed_unaligned_and_duplicate_ranges_keep_old_packet_order(self):
        randomizer=random.Random(1978)
        for batch in (1,2,3,7,32768):
            for _ in range(20):
                ranges=[(randomizer.randrange(256),randomizer.randrange(65))for _ in range(5)]
                ranges.extend(((8,24),(3,17),(8,24)))
                self.assert_wire_read(ranges,batch)
        self.assert_wire_read([(0,40),(56,8)],3.0) # Preserve existing constructor semantics.

    def test_fast_reads_avoid_python_span_loop_but_still_use_guarded_exchange(self):
        with patch.object(PineClient,'_spans',side_effect=AssertionError('slow span loop')):
            self.assertEqual(self.client.read(8,64),bytes(self.sock.memory[8:72]))
        self.sock.requests.clear()
        with patch('pine._runtime_guard',side_effect=RuntimeError('runtime changed')):
            with self.assertRaisesRegex(RuntimeError,'runtime changed'):self.client.read(0,8)
        self.assertEqual(self.sock.requests,[])
        self.sock.fail=True
        with self.assertRaises(PineError):self.client.read(0,8)
        self.sock.fail=False
        with self.assertRaisesRegex(PineError,'Expected 16 reply bytes'):
            self.client.read(4088,16) # Fake memory ends early; reply-size guard remains.

    def test_every_range_is_validated_before_fast_encoding_or_exchange(self):
        for invalid in ((-8,8),(0,-1),(0x100000000,0),(0xFFFFFFF8,16),(0xFFFFFFFF,2),
                        (1.0,8),(0,8.0),('0',8)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):self.client.read_ranges([(0,8),invalid])
                self.assertEqual(self.sock.requests,[])

    def test_big_endian_array_is_normalized_and_unusual_word_size_falls_back(self):
        class BigArray:
            itemsize=4
            def __init__(self,values):self.values=list(values);self.swapped=False
            def byteswap(self):self.swapped=True
            def tobytes(self):return struct.pack(('<'if self.swapped else'>')+'I'*len(self.values),*self.values)
        with patch('pine.array',side_effect=lambda kind,values=():BigArray(values)),patch('pine.sys.byteorder','big'):
            self.assert_wire_read([(0x120,40),(8,32)],3)
        class WideArray:
            itemsize=8
        with patch('pine.array',return_value=WideArray()):self.assert_wire_read([(0,40),(56,8)],3)

    def assert_wire_write(self,ranges,batch):
        self.client.batch_commands=batch;self.sock.requests.clear()
        memory=bytearray(self.sock.memory)
        for address,data in ranges:memory[address:address+len(data)]=data
        packets=legacy_write_packets(ranges,batch)
        self.client.write_ranges(iter(ranges))
        self.assertEqual(self.sock.requests,packets)
        self.assertEqual(self.sock.memory,memory)

    def test_aligned_writes_match_old_wire_across_batches_ranges_and_empty_data(self):
        randomizer=random.Random(2109)
        blob=lambda n:bytes(randomizer.randrange(256)for _ in range(n))
        for batch in range(1,9):
            for first in range(5):
                for second in range(5):
                    self.assert_wire_write([(256,blob(first*8)),(7,b''),(0,blob(second*8)),
                                            (120,blob(8)),(0,b''),(256,blob(16))],batch)
        self.assert_wire_write([],1)
        self.assert_wire_write([(1,b''),(0xFFFFFFFF,b'')],32768)
        self.assert_wire_write([(0,blob(4096))],32768)
        self.assert_wire_write([(8,bytearray(blob(24))),(40,memoryview(blob(8)))],3)

    def test_unaligned_or_float_batch_writes_keep_the_span_loop(self):
        randomizer=random.Random(2110)
        for batch in (1,2,3,7,32768):
            for _ in range(20):
                ranges=[(randomizer.randrange(256),bytes(randomizer.randrange(256)
                         for _ in range(randomizer.randrange(65))))for _ in range(4)]
                ranges.append((8,bytes(24)))
                self.assert_wire_write(ranges,batch)
        self.assert_wire_write([(0,bytes(40)),(56,bytes(8))],3.0)

    def test_fast_writes_avoid_span_loop_and_keep_validation_and_guard(self):
        with patch.object(PineClient,'_spans',side_effect=AssertionError('slow span loop')):
            self.client.write(64,bytes(range(64)))
        self.assertEqual(self.sock.memory[64:128],bytes(range(64)))
        self.sock.requests.clear()
        with self.assertRaises(ValueError):self.client.write_ranges([(0,bytes(8)),(0xFFFFFFF8,bytes(16))])
        with patch('pine._runtime_guard',side_effect=RuntimeError('runtime changed')):
            with self.assertRaisesRegex(RuntimeError,'runtime changed'):self.client.write(0,bytes(8))
        self.assertEqual(self.sock.requests,[])

    def test_big_endian_write_addresses_are_normalized_and_wide_words_fall_back(self):
        class BigArray:
            itemsize=4
            def __init__(self,values):self.values=list(values);self.swapped=False
            def byteswap(self):self.swapped=True
            def tobytes(self):return struct.pack(('<'if self.swapped else'>')+'I'*len(self.values),*self.values)
        with patch('pine.array',side_effect=lambda kind,values=():BigArray(values)),patch('pine.sys.byteorder','big'):
            self.assert_wire_write([(0x120,bytes(range(40))),(8,bytes(range(32)))],3)
        class WideArray:
            itemsize=8
        with patch('pine.array',return_value=WideArray()):
            self.assert_wire_write([(0,bytes(range(40))),(56,bytes(8))],3)


class SocketPathTests(unittest.TestCase):
    """pine.socket_path follows PINEServer::Initialize (PINE.cpp, PCSX2 2.6 and 2.8) exactly."""
    def test_default_slot_is_written_where_the_bt4_slot_rewrite_cannot_reach_it(self):
        self.assertEqual(pine.PCSX2_DEFAULT_SLOT, 0x6D6B)
        self.assertEqual(str(pine.PCSX2_DEFAULT_SLOT), '2801' + '1')

    def test_default_slot_is_the_plain_name_and_other_slots_get_a_suffix(self):
        env = {'XDG_RUNTIME_DIR': '/run/user/1000'}
        self.assertEqual(pine.socket_path(0x6D6B, env), '/run/user/1000/pcsx2.sock')        # BT3
        self.assertEqual(pine.socket_path(0x6D6C, env), '/run/user/1000/pcsx2.sock.28012')  # BT4
        self.assertEqual(pine.socket_path(0, env), '/run/user/1000/pcsx2.sock.0')
        port = PineClient().port   # this adapter's own slot
        self.assertIn(port, (0x6D6B, 0x6D6C))
        self.assertEqual(Path(pine.socket_path(port, env)).name,
                         'pcsx2.sock' if port == 0x6D6B else 'pcsx2.sock.28012')

    def test_directory_fallbacks_and_trailing_slash_match_pcsx2(self):
        self.assertEqual(pine.socket_path(0x6D6B, {}), '/tmp/pcsx2.sock')             # unset
        self.assertEqual(pine.socket_path(0x6D6C, {}), '/tmp/pcsx2.sock.28012')
        self.assertEqual(pine.socket_path(0x6D6B, {'XDG_RUNTIME_DIR': ''}), '/pcsx2.sock')  # set but empty
        # WSL and some desktops export a trailing slash; PCSX2 joins it verbatim, so "//" names the same file.
        self.assertEqual(pine.socket_path(0x6D6B, {'XDG_RUNTIME_DIR': '/run/user/1000/'}),
                         '/run/user/1000//pcsx2.sock')
        with patch('pine.sys.platform', 'darwin'):
            self.assertEqual(pine.socket_path(0x6D6B, {'TMPDIR': '/var/folders/x/', 'XDG_RUNTIME_DIR': '/run'}),
                             '/var/folders/x//pcsx2.sock')

    def test_over_long_names_are_cut_where_pcsx2_cuts_them(self):
        directory = '/run/user/1000/' + 'd' * 100
        path = pine.socket_path(0x6D6C, {'XDG_RUNTIME_DIR': directory})
        self.assertEqual(len(os.fsencode(path)), 107)   # Strlcpy into sockaddr_un.sun_path[108]
        self.assertEqual(path, (directory + '/pcsx2.sock.28012')[:107])

    def test_launcher_override_wins_and_the_default_environment_is_used(self):
        env = {'XDG_RUNTIME_DIR': '/run/user/1000', 'TAGTEAM_PINE_SOCKET': '/tmp/pcsx2.sock'}
        self.assertEqual(pine.socket_path(0x6D6C, env), '/tmp/pcsx2.sock')
        self.assertEqual(pine.socket_path(0x6D6C, dict(env, TAGTEAM_PINE_SOCKET='')), '/run/user/1000/pcsx2.sock.28012')
        with patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/77'}):
            os.environ.pop('TAGTEAM_PINE_SOCKET', None)
            self.assertEqual(pine.socket_path(0x6D6B), '/run/user/77/pcsx2.sock')
        for slot in (True, '28011', 1.0):
            with self.assertRaises(ValueError):
                pine.socket_path(slot, {})


class FakeUnixSocket(FakeSocket):
    def __init__(self, peer=4242):
        super().__init__()
        self.peer, self.connected = peer, None

    def connect(self, path):
        self.connected = path

    def getsockopt(self, level, option, size):
        return struct.pack('=iII', self.peer, 1000, 1000)[:size]


class UnixTransportTests(unittest.TestCase):
    """Linux transport logic with a fake socket; runs on every platform."""
    def setUp(self):
        self.sock = FakeUnixSocket()
        for patcher in (patch('pine.WINDOWS', False),
                        patch.object(pine.socket, 'AF_UNIX', getattr(socket, 'AF_UNIX', 1), create=True),
                        patch.object(pine.socket, 'SO_PEERCRED', getattr(socket, 'SO_PEERCRED', 17), create=True),
                        patch.dict(os.environ, {'TAGTEAM_PINE_SOCKET': '/tmp/fake-pine.sock'})):
            patcher.start(); self.addCleanup(patcher.stop)
        self.create = patch('pine.socket.socket', return_value=self.sock)
        self.factory = self.create.start(); self.addCleanup(self.create.stop)
        self.tcp = patch('pine.socket.create_connection', side_effect=AssertionError('TCP off Windows'))
        self.tcp.start(); self.addCleanup(self.tcp.stop)
        self.addCleanup(pine.set_runtime_guard, None)

    def test_unix_client_connects_to_the_socket_path_without_tcp_options(self):
        client = PineClient(timeout=3.5)
        self.assertEqual(client.require_game('SLUS-21678')['title'], 'Dragon Ball Z')
        self.assertEqual(self.factory.call_args.args, (pine.socket.AF_UNIX, socket.SOCK_STREAM))
        self.assertEqual(self.sock.connected, '/tmp/fake-pine.sock')
        self.assertEqual(self.sock.options, [])   # TCP_NODELAY fails with EOPNOTSUPP on AF_UNIX
        self.assertEqual(self.sock.timeout, 3.5)
        client.close(); self.assertTrue(self.sock.closed)

    def test_listener_must_be_the_owned_emulator(self):
        pine.set_runtime_guard(lambda: None, 4242)
        client = PineClient()
        self.assertEqual(client.read(8, 8), bytes(range(8, 16)))
        client.close()
        other = FakeUnixSocket(peer=5151); self.factory.return_value = other
        with self.assertRaisesRegex(PineError, 'belongs to process 5151.*4242'):
            client.write(8, bytes(8))
        self.assertTrue(other.closed); self.assertEqual(other.requests, []); self.assertIsNone(client.sock)

    def test_a_bound_emulator_lifetime_guard_carries_its_pid(self):
        class Lifetime:
            pid = 5151
            def require_alive(self): pass
        pine.set_runtime_guard(Lifetime().require_alive)
        self.assertEqual(pine._runtime_pid, 5151)
        with self.assertRaisesRegex(PineError, 'belongs to process 4242'):
            PineClient().status()
        self.assertEqual(self.sock.requests, [])
        for guard in (None, lambda: None, Mock()):
            pine.set_runtime_guard(guard); self.assertIsNone(pine._runtime_pid)
        self.assertEqual(PineClient().status(), 'running')   # no owned PID: no peer check

    def test_connect_errors_keep_their_type_and_name_the_socket(self):
        failures = (FileNotFoundError(errno.ENOENT, 'No such file or directory'),
                    ConnectionRefusedError(errno.ECONNREFUSED, 'Connection refused'),
                    PermissionError(errno.EACCES, ''), TimeoutError('timed out'), OSError())
        for failure in failures:
            self.sock = FakeUnixSocket(); self.factory.return_value = self.sock
            self.sock.connect = Mock(side_effect=failure)
            with self.assertRaises(type(failure)) as caught:
                PineClient().status()
            self.assertIn('/tmp/fake-pine.sock', str(caught.exception))
            self.assertIs(caught.exception.__cause__, failure)
            self.assertEqual(caught.exception.errno, failure.errno)
            self.assertTrue(self.sock.closed); self.assertEqual(self.sock.requests, [])
        self.assertEqual(str(caught.exception), "connection failed (PCSX2 PINE socket '/tmp/fake-pine.sock')")

    def test_runtime_guard_runs_before_the_peer_check(self):
        pine.set_runtime_guard(Mock(side_effect=[None, None, RuntimeError('emulator closed')]), 5151)
        with self.assertRaisesRegex(RuntimeError, 'emulator closed'):
            PineClient().status()
        self.assertTrue(self.sock.closed); self.assertEqual(self.sock.requests, [])


@unittest.skipUnless(os.name == 'nt', 'Windows transport')
class WindowsTransportTests(unittest.TestCase):
    def test_windows_keeps_loopback_tcp_with_nodelay_and_ignores_the_socket_override(self):
        self.assertTrue(pine.WINDOWS)
        sock = FakeSocket()
        with patch.dict(os.environ, {'TAGTEAM_PINE_SOCKET': '/tmp/pcsx2.sock'}), \
             patch('pine.socket.create_connection', return_value=sock) as connect:
            pine.set_runtime_guard(lambda: None, 4242)   # a PID never changes the TCP transport
            try:
                client = PineClient(); client.info(); client.close()
            finally:
                pine.set_runtime_guard(None)
        self.assertEqual(connect.call_args.args, (("127.0.0.1", client.port), None))
        self.assertEqual(sock.options, [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)])


class ConnectRetryTests(unittest.TestCase):
    """Beta.34: a loopback connect Windows refuses for want of ports (WinError 10048/10055) is tried again. Live on
    Sept 28 the first 10048 failed a ten-fighter match setup at Ready, although nothing had been sent."""
    def setUp(self):
        transport = patch("pine.WINDOWS", True); transport.start(); self.addCleanup(transport.stop)
        self.sleeps = []
        sleep = patch("pine.time.sleep", side_effect=self.sleeps.append); sleep.start(); self.addCleanup(sleep.stop)

    def test_a_refusal_for_want_of_ports_is_tried_again_and_the_request_then_goes_through(self):
        sock = FakeSocket()
        refusals = [OSError(10048, "Only one usage of each socket address"), OSError(10055, "No buffer space")]
        with patch("pine.socket.create_connection", side_effect=[*refusals, sock]) as connect:
            with PineClient() as client:
                self.assertEqual(client.status(), "running")
        self.assertEqual(connect.call_count, 3)
        self.assertEqual(self.sleeps, list(pine.CONNECT_RETRY[:2]))
        self.assertEqual(len(sock.requests), 1)
        self.assertTrue(sock.closed)

    def test_other_errors_and_a_refusal_that_lasts_still_reach_the_caller(self):
        with patch("pine.socket.create_connection", side_effect=ConnectionRefusedError(10061, "refused")) as connect:
            with self.assertRaises(ConnectionRefusedError):
                PineClient().connect()
        self.assertEqual((connect.call_count, self.sleeps), (1, []))   # a closed port is never waited for
        with patch("pine.socket.create_connection", side_effect=OSError(10048, "in use")) as connect:
            with self.assertRaises(OSError) as caught:
                PineClient().connect()
        self.assertEqual((connect.call_count, caught.exception.errno), (len(pine.CONNECT_RETRY) + 1, 10048))
        self.assertLessEqual(sum(pine.CONNECT_RETRY), 2.0)

    def test_a_closed_emulator_ends_the_waiting(self):
        class Closed(Exception):
            pass
        checks = []
        def guard():
            checks.append(1)
            if len(checks) > 1:   # the first check is connect()'s own, before any try
                raise Closed()
        pine.set_runtime_guard(guard)
        self.addCleanup(pine.set_runtime_guard, None)
        with patch("pine.socket.create_connection", side_effect=OSError(10048, "in use")) as connect:
            with self.assertRaises(Closed):
                PineClient().connect()
        self.assertEqual(connect.call_count, 1)


SERVER = r'''
import os, socket, struct, sys
path = sys.argv[1]
try: os.unlink(path)   # as PCSX2 does before bind(): a second server takes the path over
except FileNotFoundError: pass
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(path); server.listen(8)
print(os.getpid(), flush=True)
memory = bytearray(range(256)) * 16
strings = {8: "PCSX2 fixture", 11: "Dragon Ball Z", 12: "SLUS-21678", 13: "428113c2", 14: "1.00"}
def receive(connection, count):
    data = b""
    while len(data) < count:
        part = connection.recv(count - len(data))
        if not part: return None
        data += part
    return data
while True:
    connection, _ = server.accept()
    with connection:
        while True:
            header = receive(connection, 4)
            request = header and receive(connection, struct.unpack("<I", header)[0] - 4)
            if not request: break
            result, offset = bytearray(), 0
            while offset < len(request):
                op = request[offset]; offset += 1
                if op < 8:
                    address = struct.unpack_from("<I", request, offset)[0]; offset += 4
                    width = 1 << (op % 4)
                    if op < 4: result += memory[address:address + width]
                    else: memory[address:address + width] = request[offset:offset + width]; offset += width
                elif op in strings:
                    value = strings[op].encode() + b"\0"; result += struct.pack("<I", len(value)) + value
                elif op == 15: result += struct.pack("<I", 0)
            connection.sendall(struct.pack("<I", len(result) + 5) + b"\0" + result)
'''


@unittest.skipUnless(os.name != 'nt' and hasattr(socket, 'AF_UNIX'), 'PCSX2 serves PINE on a Unix socket off Windows')
class RealUnixSocketTests(unittest.TestCase):
    """A fake PINE server in another process, like PCSX2: real AF_UNIX, real SO_PEERCRED."""
    def setUp(self):
        # sun_path holds 107 bytes; the scratch/test tree path is longer, so sockets live under /tmp.
        self.directory = tempfile.mkdtemp(prefix='ttm-pine-', dir='/tmp')
        self.servers = []
        environment = patch.dict(os.environ, {'XDG_RUNTIME_DIR': self.directory + '/'})
        environment.start(); self.addCleanup(environment.stop)
        os.environ.pop('TAGTEAM_PINE_SOCKET', None)
        self.addCleanup(self.cleanup)
        self.addCleanup(pine.set_runtime_guard, None)

    def cleanup(self):
        for child in self.servers:
            child.kill(); child.wait(timeout=5); child.stdout.close()
        for name in os.listdir(self.directory):
            os.unlink(os.path.join(self.directory, name))
        os.rmdir(self.directory)

    def serve(self, name):
        child = subprocess.Popen([sys.executable, '-c', SERVER, os.path.join(self.directory, name)],
                                 stdout=subprocess.PIPE, text=True)
        self.servers.append(child)
        pid = int(child.stdout.readline())
        self.assertEqual(pid, child.pid)
        return pid

    def test_each_slot_reaches_the_socket_pcsx2_would_create(self):
        self.serve('pcsx2.sock'); self.serve('pcsx2.sock.28012')
        for slot in (0x6D6B, 0x6D6C):
            with PineClient(port=slot, timeout=5) as client:
                self.assertEqual(client.sock.family, socket.AF_UNIX)
                client.write(16, b'slot%05d' % slot)
            with PineClient(port=slot, timeout=5) as client:
                self.assertEqual(client.read(16, 9), b'slot%05d' % slot)
                self.assertEqual(client.info()['serial'], 'SLUS-21678')
        with self.assertRaises(FileNotFoundError) as caught:   # nothing listens on this slot
            PineClient(port=28013, timeout=5).status()
        self.assertIn(repr(pine.socket_path(28013)), str(caught.exception))   # the exact path PCSX2 would use

    def test_launcher_socket_override_is_used(self):
        self.serve('custom.sock')
        with patch.dict(os.environ, {'TAGTEAM_PINE_SOCKET': os.path.join(self.directory, 'custom.sock'),
                                     'XDG_RUNTIME_DIR': '/nonexistent'}):
            with PineClient(timeout=5) as client:
                self.assertEqual(client.status(), 'running')

    def test_a_second_emulator_that_takes_over_the_socket_is_refused(self):
        name = Path(pine.socket_path(PineClient().port)).name
        owned = self.serve(name)
        pine.set_runtime_guard(lambda: None, owned)
        with PineClient(timeout=5) as client:
            self.assertEqual(client.read(0, 8), bytes(range(8)))
        intruder = self.serve(name)   # unlinks and rebinds the same path, as a second PCSX2 does
        self.assertNotEqual(intruder, owned)
        client = PineClient(timeout=5)
        with self.assertRaisesRegex(PineError, f'belongs to process {intruder}.*{owned}'):
            client.write(0, bytes(8))
        self.assertIsNone(client.sock)
        pine.set_runtime_guard(lambda: None, intruder)
        with PineClient(timeout=5) as client:   # the refused write never reached the intruder
            self.assertEqual(client.read(0, 8), bytes(range(8)))


if __name__ == "__main__":
    unittest.main()
