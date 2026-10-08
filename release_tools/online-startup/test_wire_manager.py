"""Immutable wire-cache integrity and graceful codec availability checks."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_wire


class Codec:
    SCHEMA = 'portable-test-codec'

    def __init__(self):
        self.encodes, self.decodes = 0, 0

    def encode_state(self, path, iso):
        self.encodes += 1
        raw = Path(path).read_bytes()
        header = dict(archive_sha256=hashlib.sha256(raw).hexdigest(), archive_length=len(raw),
                      iso_sha256=iso.sha256, schema=self.SCHEMA)
        return SimpleNamespace(wire=json.dumps(header).encode() + b'\n' + raw,
                               archive_sha256=header['archive_sha256'], seconds=0.001)

    def header_of(self, data):
        text, raw = data.split(b'\n', 1)
        return json.loads(text), raw

    def decode_state(self, data, iso, expected_sha):
        self.decodes += 1
        header, raw = self.header_of(data)
        if header['archive_sha256'] != expected_sha or hashlib.sha256(raw).hexdigest() != expected_sha:
            raise ValueError('Invalid test archive')
        return raw


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.p2s'
        self.raw = b'complete authoritative archive payload'
        self.source.write_bytes(self.raw)
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.manager = kit_wire.Manager.__new__(kit_wire.Manager)
        self.manager.lock = threading.RLock()
        self.manager.cache = self.root / 'cache'
        self.manager.say = lambda _: None
        self.manager.iso = SimpleNamespace(sha256='1' * 64, adapter=SimpleNamespace(name='bt3-usa'), close=lambda: None)
        self.manager.codec = Codec()

    def artifact(self):
        return self.manager.artifact(self.source, self.sha, len(self.raw))

    def test_matching_cache_hit_reuses_verified_artifact(self):
        first = self.artifact()
        second = self.artifact()
        self.assertEqual(first, second)
        self.assertEqual(self.manager.codec.encodes, 1)
        self.assertEqual(kit_wire.sha(second['path']), second['sha256'])

    def test_corrupt_payload_with_unchanged_header_is_rebuilt(self):
        first = self.artifact()
        path = Path(first['path'])
        changed = bytearray(path.read_bytes()); changed[-1] ^= 1; path.write_bytes(changed)
        second = self.artifact()
        self.assertEqual(first, second)
        self.assertEqual(self.manager.codec.encodes, 2)

    def test_missing_or_wrong_receipt_is_rebuilt(self):
        first = self.artifact()
        receipt = Path(first['path']).with_suffix('.json')
        receipt.unlink()
        self.artifact()
        value = json.loads(receipt.read_text()); value['archive_sha256'] = '0' * 64
        receipt.write_text(json.dumps(value))
        self.artifact()
        self.assertEqual(self.manager.codec.encodes, 3)

    def test_changed_original_is_not_treated_as_codec_fallback(self):
        self.source.write_bytes(self.raw[:-1] + b'x')
        with self.assertRaisesRegex(ValueError, 'Authoritative source changed'):
            self.artifact()
        self.assertEqual(self.manager.codec.encodes, 0)

    def test_unsupported_adapter_stays_available_for_ordinary_transfer(self):
        for adapter in ('bt3-pal', 'bt3-jpn', 'bt4-b14-rev2-eng'):
            manager = kit_wire.Manager('not-opened.iso', '1' * 64, adapter, self.root)
            self.assertIsNone(manager.capability())
            self.assertEqual(manager.artifact(self.source, self.sha, len(self.raw))['codec'], 'archive')

    def test_restore_checks_wire_hash_before_decoding_and_keeps_old_target(self):
        artifact = self.artifact()
        d = dict(artifact, archive_sha256=self.sha, archive_size=len(self.raw))
        part = self.root / 'incoming.part'
        part.write_bytes(Path(artifact['path']).read_bytes()[:-1] + b'x')
        target = self.root / 'restored.p2s'; target.write_bytes(b'previous valid cache')
        with self.assertRaisesRegex(ValueError, 'representation identity'):
            self.manager.restore(d, part, target)
        self.assertEqual(target.read_bytes(), b'previous valid cache')
        self.assertEqual(self.manager.codec.decodes, 0)

    def test_restore_exact_archive_and_no_decoded_partial_left(self):
        artifact = self.artifact()
        d = dict(artifact, archive_sha256=self.sha, archive_size=len(self.raw))
        part = self.root / 'incoming.part'; part.write_bytes(Path(artifact['path']).read_bytes())
        target = self.root / 'restored.p2s'
        self.manager.restore(d, part, target)
        self.assertEqual(target.read_bytes(), self.raw)
        self.assertFalse(part.with_name(part.name + '.decoded').exists())

    def test_ordinary_restore_requires_original_sha_and_size(self):
        descriptor = dict(codec='archive', archive_sha256=self.sha, archive_size=len(self.raw))
        part = self.root / 'incoming.part'; part.write_bytes(self.raw[:-1] + b'x')
        target = self.root / 'restored.p2s'
        with self.assertRaisesRegex(ValueError, 'Ordinary snapshot identity'):
            self.manager.restore(descriptor, part, target)
        self.assertFalse(target.exists())
        part.write_bytes(self.raw)
        self.manager.restore(descriptor, part, target)
        self.assertEqual(target.read_bytes(), self.raw)

    def test_capability_requires_exact_iso_schema_and_runtime(self):
        cap = self.manager.capability()
        self.assertTrue(self.manager.compatible(cap))
        self.assertFalse(self.manager.compatible(dict(cap, iso_sha256='2' * 64)))
        self.assertFalse(self.manager.compatible(dict(cap, zlib='another runtime')))
        self.manager.close()
        self.assertIsNone(self.manager.capability())


if __name__ == '__main__':
    unittest.main()
