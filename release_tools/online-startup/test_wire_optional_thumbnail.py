"""Portable exact-archive and rejection tests for optional emulator thumbnails."""
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'bt3-multifighter/online/netplay'), str(ROOT)]
import kit_wire_codec as codec


class FakeIso:
    sha256 = '1' * 64
    adapter = SimpleNamespace(name='bt3-usa')
    raw = b'bounded synthetic resource'

    def _fresh(self): pass

    def asset(self, file_id):
        if file_id != 7:
            raise codec.WireRejected('Invalid synthetic resource')
        return self.raw, dict(file_id=7, length=len(self.raw), file_sha256=codec.digest(self.raw))

    def referenced_asset(self, row):
        raw, wanted = self.asset(row['file_id'])
        if any(row.get(name) != value for name, value in wanted.items()):
            raise codec.WireRejected('Changed synthetic resource')
        return raw


def replace_header(wire, change):
    header, payload = codec.header_of(wire)
    change(header)
    raw = json.dumps(header, sort_keys=True, separators=(',', ':')).encode()
    return codec.MAGIC + struct.pack('<I', len(raw)) + raw + payload


class OptionalThumbnail(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.iso = FakeIso()
        self.addCleanup(patch.stopall)
        patch.object(codec, 'EE_SIZE', 2 << 20).start()
        self.ref = dict(file_id=7, destination=0x100000, length=len(self.iso.raw),
                        file_sha256=codec.digest(self.iso.raw))
        patch.object(codec, 'detect_references', side_effect=lambda ram, iso: [dict(self.ref)]).start()
        self.payloads = {name: b'\x01' for name in codec.REQUIRED_ENTRIES}
        ram = bytearray(codec.EE_SIZE)
        ram[0x100000:0x100000 + len(self.iso.raw)] = self.iso.raw
        self.payloads['eeMemory.bin'] = ram

    def archive(self, screenshot=False, remove=None, unknown=None, duplicate=None):
        values = dict(self.payloads)
        if screenshot:
            values['Screenshot.png'] = b'synthetic optional thumbnail'
        if remove:
            values.pop(remove)
        if unknown:
            values[unknown] = b'unknown optional data must not be accepted'
        buffer = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as state:
                for name, raw in values.items():
                    state.writestr(name, raw, compresslevel=1)
                if duplicate:
                    state.writestr(duplicate, values[duplicate], compresslevel=1)
        return buffer.getvalue()

    def encode(self, raw):
        path = self.folder / 'synthetic.p2s'
        path.write_bytes(raw)
        return codec.encode_state(path, self.iso).wire

    def test_with_and_without_thumbnail_roundtrip_exact_zip_and_all_entries(self):
        for screenshot in (False, True):
            with self.subTest(screenshot=screenshot):
                raw = self.archive(screenshot)
                encoded = self.encode(raw)
                header, _ = codec.header_of(encoded)
                self.assertEqual(len(header['entries']), 15 + int(screenshot))
                restored = codec.decode_state(encoded, self.iso, codec.digest(raw))
                self.assertEqual(restored, raw)
                with zipfile.ZipFile(io.BytesIO(restored)) as state:
                    self.assertIsNone(state.testzip())
                    self.assertEqual(set(state.namelist()), set(self.payloads) |
                                     ({'Screenshot.png'} if screenshot else set()))

    def test_each_missing_machine_entry_is_rejected_even_with_thumbnail(self):
        for name in codec.REQUIRED_ENTRIES:
            raw = self.archive(screenshot=True, remove=name)
            with self.subTest(name=name), patch.object(codec.zipfile, 'ZipFile') as inflate:
                with self.assertRaises(codec.WireRejected):
                    codec.load_archive(raw)
                self.assertEqual(inflate.call_count, 0)

    def test_unknown_sixteenth_entry_cannot_replace_thumbnail(self):
        with self.assertRaisesRegex(codec.FallbackRequired, 'entry names'):
            codec.zip_layout(self.archive(unknown='unknown.bin'))

    def test_duplicate_known_entry_is_not_optional(self):
        with self.assertRaisesRegex(codec.WireRejected, 'Duplicate archive entry'):
            codec.zip_layout(self.archive(duplicate='PAD.bin'))

    def test_oversized_thumbnail_rejected_before_zip_inflation(self):
        raw = self.archive(screenshot=True)
        bounds = dict(codec.ENTRY_LIMITS, **{'Screenshot.png': 1})
        with patch.object(codec, 'ENTRY_LIMITS', bounds), patch.object(codec.zipfile, 'ZipFile') as inflate:
            with self.assertRaisesRegex(codec.WireRejected, 'Excessive archive entry'):
                codec.load_archive(raw)
            self.assertEqual(inflate.call_count, 0)

    def test_manifest_cannot_substitute_thumbnail_for_machine_entry(self):
        raw = self.archive(False)
        encoded = self.encode(raw)
        bad = replace_header(encoded, lambda value: next(row for row in value['entries']
                              if row['name'] == 'PAD.bin').update(name='Screenshot.png'))
        with patch.object(codec.zstd, 'ZstdDecompressor') as inflate:
            with self.assertRaisesRegex(codec.WireRejected, 'Missing required machine entry'):
                codec.decode_state(bad, self.iso, codec.digest(raw))
            inflate.assert_not_called()

    def test_skeleton_entry_count_must_match_manifest_count(self):
        raw = self.archive(False)
        encoded = self.encode(raw)
        header, payload = codec.header_of(encoded)
        components = codec.unpack_components(header, payload)
        other = codec.load_archive(self.archive(True))[1]
        thumbnail = next(row for row in other if row['name'] == 'Screenshot.png')
        header['entries'].append(thumbnail)
        components.insert(-1, b'synthetic optional thumbnail')
        bad = codec.pack(header, components)
        with self.assertRaisesRegex(codec.WireRejected, 'skeleton directory differs'):
            codec.decode_state(bad, self.iso, codec.digest(raw))

    def test_optional_thumbnail_payload_is_still_verified(self):
        raw = self.archive(True)
        encoded = self.encode(raw)
        header, payload = codec.header_of(encoded)
        components = codec.unpack_components(header, payload)
        index = next(i for i, row in enumerate(header['entries']) if row['name'] == 'Screenshot.png')
        components[index + 1] = b'x' * len(components[index + 1])
        bad = codec.pack(header, components)
        with self.assertRaisesRegex(codec.WireRejected, 'Reconstructed entry hash'):
            codec.decode_state(bad, self.iso, codec.digest(raw))

    def test_component_count_is_bounded_before_decompression(self):
        raw = self.archive(False)
        encoded = self.encode(raw)
        bad = replace_header(encoded, lambda value: value['components'].pop())
        with patch.object(codec.zstd, 'ZstdDecompressor') as inflate:
            with self.assertRaisesRegex(codec.WireRejected, 'component count'):
                codec.decode_state(bad, self.iso, codec.digest(raw))
            inflate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
