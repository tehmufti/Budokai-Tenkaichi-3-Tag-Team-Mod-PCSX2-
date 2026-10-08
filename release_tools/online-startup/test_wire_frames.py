"""Real socket framing keeps compact, legacy prefetch and resync bytes isolated."""
import socket
import struct
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_net
import kit_transfer


class FramingTests(unittest.TestCase):
    def setUp(self):
        left, right = socket.socketpair()
        self.sender, self.receiver = kit_net.Channel(left), kit_net.Channel(right)
        self.addCleanup(self.sender.close)
        self.addCleanup(self.receiver.close)

    def test_interleaved_control_prefetch_resync_and_compact_frames(self):
        token = '1' * 32
        self.sender.send_transfer_chunk(token, 0, b'first compact bytes')
        self.sender.send_chunk(b'resync bytes')
        self.sender.send_prefetch_chunk('2' * 64, b'legacy prefetch bytes')
        self.sender.send_json(type='PING', t=1)
        self.sender.send_transfer_chunk(token, 19, b'compact tail')
        frames = self.receiver.poll_frames()
        self.assertEqual([kind for kind, _ in frames], ['W', 'B', 'P', 'J', 'W'])
        self.assertEqual(kit_transfer.TAG.unpack_from(frames[0][1]), (bytes.fromhex(token), 0))
        self.assertEqual(frames[0][1][kit_transfer.TAG.size:], b'first compact bytes')
        self.assertEqual(frames[1][1], b'resync bytes')
        self.assertEqual(frames[2][1], bytes.fromhex('2' * 64) + b'legacy prefetch bytes')
        self.assertEqual(frames[3][1], dict(type='PING', t=1))
        self.assertEqual(kit_transfer.TAG.unpack_from(frames[4][1]), (bytes.fromhex(token), 19))

    def test_fragmented_compact_frame_waits_for_complete_bounded_body(self):
        body = b'W' + kit_transfer.TAG.pack(b'x' * 16, 4) + b'payload'
        frame = struct.pack('>I', len(body)) + body
        for fragment in (frame[:3], frame[3:20], frame[20:-1]):
            self.sender.sock.sendall(fragment)
            self.assertEqual(self.receiver.poll_frames(), [])
        self.sender.sock.sendall(frame[-1:])
        self.assertEqual(self.receiver.poll_frames(), [('W', body[1:])])

    def test_blocking_parser_and_frame_limit_cover_new_type(self):
        self.sender.send_transfer_chunk('a' * 32, 9, b'body')
        kind, value = self.receiver.receive(1)
        self.assertEqual(kind, 'W')
        self.assertEqual(kit_transfer.TAG.unpack_from(value), (bytes.fromhex('a' * 32), 9))
        self.sender.sock.sendall(struct.pack('>I', kit_net.MAX_FRAME + 1))
        self.assertEqual(self.receiver.poll_frames(), [])
        self.assertTrue(self.receiver.closed)



class DecodedArchiveChecks(unittest.TestCase):
    def setUp(self):
        from test_fresh_proven import FreshProven
        self.fixture = FreshProven('test_fresh_wire_is_identical_and_decoder_still_reconstructs_exact_archive')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.codec = self.fixture.__class__.__module__
        import kit_wire_codec
        self.codec = kit_wire_codec
        self.encoded = self.codec.encode_state(self.fixture.path, self.fixture.iso)

    def test_complete_memory_receipt_preserves_every_original_archive_byte(self):
        import zipfile
        import io
        decoded = self.codec.decode_state_with_memory(self.encoded.wire, self.fixture.iso,
            self.encoded.archive_sha256)
        self.assertEqual(decoded.archive, self.fixture.raw)
        with zipfile.ZipFile(io.BytesIO(decoded.archive)) as archive:
            self.assertEqual(decoded.memory, archive.read('eeMemory.bin'))

    def test_final_crc_reader_wrong_bytes_in_later_entry_cannot_create_receipt(self):
        import zipfile
        from unittest.mock import patch
        original = zipfile.ZipFile
        changed = []
        class Stream:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def read(self, n):
                data = self.stream.read(n)
                if data and not changed:
                    changed.append(True)
                    return bytes([data[0] ^ 1]) + data[1:]
                return data
        class Reader(original):
            def open(self, name, *args, **kwargs):
                stream = super().open(name, *args, **kwargs)
                return Stream(stream) if name == 'vu1MicroMem.bin' else stream
        with patch.object(self.codec.zipfile, 'ZipFile', Reader), self.assertRaisesRegex(self.codec.WireRejected, 'entry differs'):
            self.codec.decode_state_with_memory(self.encoded.wire, self.fixture.iso,
                self.encoded.archive_sha256)
        self.assertEqual(changed, [True])

    def test_later_crc_failure_does_not_become_a_verified_memory_receipt(self):
        import zipfile
        from unittest.mock import patch
        original = zipfile.ZipFile
        class Reader(original):
            def open(self, name, *args, **kwargs):
                if name == 'vu1MicroMem.bin':
                    raise zipfile.BadZipFile('later CRC error')
                return super().open(name, *args, **kwargs)
        with patch.object(self.codec.zipfile, 'ZipFile', Reader), self.assertRaisesRegex(self.codec.WireRejected, 'CRC'):
            self.codec.decode_state_with_memory(self.encoded.wire, self.fixture.iso,
                self.encoded.archive_sha256)

    def test_truncated_final_entry_cannot_satisfy_receipt_validation(self):
        import zipfile
        from unittest.mock import patch
        original = zipfile.ZipFile
        class Stream:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def read(self, n):
                self.stream.read(n)  # genuine CRC reader still consumes its payload
                return b''
        class Reader(original):
            def open(self, name, *args, **kwargs):
                stream = super().open(name, *args, **kwargs)
                return Stream(stream) if name == 'vu1MicroMem.bin' else stream
        with patch.object(self.codec.zipfile, 'ZipFile', Reader), self.assertRaisesRegex(self.codec.WireRejected, 'length differs'):
            self.codec.decode_state_with_memory(self.encoded.wire, self.fixture.iso,
                self.encoded.archive_sha256)


if __name__ == '__main__':
    unittest.main()
