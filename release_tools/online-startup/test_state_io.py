"""Guard and archive preservation regressions for faster online state copies."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_state
import kit_match
import patch_state


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'source.p2s'
        self.target = Path(self.directory.name) / 'target.p2s'
        self.memory = bytearray(512)
        struct.pack_into('<I', self.memory, 32, 8)
        self.size = patch.object(kit_state, 'EE_SIZE', len(self.memory))
        self.size.start()
        self.addCleanup(self.size.stop)
        self.write_source()

    def write_source(self, other=b'native state data'):
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b'preserved comment'
            archive.writestr('other.bin', other)
            archive.writestr(kit_state.MEMORY, self.memory)

    def test_cached_source_decodes_once_and_preserves_all_payloads(self):
        with patch.object(kit_state, '_read_all', wraps=kit_state._read_all) as decode:
            state = kit_state.StateArchive(self.source)
            self.assertEqual(state.words([32]), {32: 8})
            digest = kit_state.patch_words(self.source, self.target, {32: (8, 9)}, archive=state)
        self.assertEqual(decode.call_count, 1)
        self.assertEqual(digest, kit_state.sha256(self.target))
        with zipfile.ZipFile(self.target) as archive:
            self.assertEqual(archive.namelist(), ['other.bin', kit_state.MEMORY])
            self.assertEqual(archive.comment, b'preserved comment')
            self.assertEqual(archive.read('other.bin'), b'native state data')
            expected = bytearray(self.memory)
            struct.pack_into('<I', expected, 32, 9)
            self.assertEqual(archive.read(kit_state.MEMORY), expected)

    def test_wrong_word_guard_never_creates_target(self):
        with self.assertRaisesRegex(ValueError, 'expected'):
            kit_state.patch_words(self.source, self.target, {32: (10, 9)})
        self.assertFalse(self.target.exists())

    def test_wrong_block_guard_never_creates_target(self):
        with self.assertRaisesRegex(ValueError, 'expected ones'):
            kit_state.patch_words(self.source, self.target, {}, {32: (b'xxxx', b'yyyy')})
        self.assertFalse(self.target.exists())

    def test_cached_source_change_is_rejected(self):
        state = kit_state.StateArchive(self.source)
        self.write_source(other=b'changed native state data')
        with self.assertRaisesRegex(ValueError, 'changed after reading'):
            kit_state.patch_words(self.source, self.target, {32: (8, 9)}, archive=state)
        self.assertFalse(self.target.exists())

    def test_different_source_is_rejected(self):
        state = kit_state.StateArchive(self.source)
        different = self.source.with_name('other.p2s')
        different.write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            kit_state.patch_words(different, self.target, {32: (8, 9)}, archive=state)

    def test_readback_checks_non_ee_bytes(self):
        state = kit_state.StateArchive(self.source)
        self.write_source(other=b'another payload')
        self.assertFalse(kit_state._verify_all(self.source, state.infos, state.payloads, state.comment))

    def test_corrupt_source_crc_is_rejected(self):
        data = bytearray(self.source.read_bytes())
        central = data.index(b'PK\x01\x02')
        data[central + 16] ^= 1                 # central-directory CRC-32
        self.source.write_bytes(data)
        with self.assertRaises(zipfile.BadZipFile):
            kit_state.StateArchive(self.source)

    def test_duplicate_source_entries_are_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.source, 'a') as archive:
                archive.writestr('other.bin', b'duplicate')
        with self.assertRaisesRegex(ValueError, 'duplicate archive entries'):
            kit_state.StateArchive(self.source)


class SequentialGuardTests(unittest.TestCase):
    def setUp(self):
        size = patch.object(patch_state.state128, 'TOTAL_RAM', 512)
        size.start()
        self.addCleanup(size.stop)
        self.original = bytes(range(256)) * 2

    def manifest(self, address, expected, data):
        return dict(serial=patch_state.SERIAL, crc=patch_state.CRC,
                    blocks=[dict(address=address, expected_hex=expected.hex(), data_hex=data.hex())])

    def prefix(self):
        value = self.manifest(32, self.original[32:40], b'abcdefgh')
        ram, report = patch_state.patch_memory(self.original, value)
        value['ram_sha256'] = report['source_ram_sha256']
        return value, ram

    def test_overlapping_stages_match_sequential_bytes_with_original_guards(self):
        prefix, ram = self.prefix()
        core = self.manifest(36, bytes(ram[36:44]), b'12345678')
        sequential, _ = patch_state.patch_memory(ram, core)
        combined = kit_match._combined_manifest(self.original, prefix, ram, core)
        actual, _ = patch_state.patch_memory(self.original, combined)
        self.assertEqual(actual, sequential)
        self.assertEqual(len(combined['blocks']), 1)
        self.assertEqual(combined['blocks'][0]['address'], 32)
        self.assertEqual(combined['ram_sha256'], hashlib.sha256(self.original).hexdigest())

    def test_second_stage_does_not_accept_original_guard_after_prefix_changed_it(self):
        prefix, ram = self.prefix()
        core = self.manifest(36, self.original[36:40], b'1234')
        with self.assertRaisesRegex(ValueError, 'guard mismatch'):
            kit_match._combined_manifest(self.original, prefix, ram, core)

    def test_first_stage_wrong_guard_is_rejected(self):
        wrong = self.manifest(32, b'1234', b'abcd')
        with self.assertRaisesRegex(ValueError, 'guard mismatch'):
            patch_state.patch_memory(self.original, wrong)

    def test_stale_source_ram_full_hash_rejected_outside_written_ranges(self):
        prefix, ram = self.prefix()
        core = self.manifest(36, bytes(ram[36:40]), b'1234')
        combined = kit_match._combined_manifest(self.original, prefix, ram, core)
        altered = bytearray(self.original)
        altered[400] ^= 1
        with self.assertRaisesRegex(ValueError, 'RAM SHA256 mismatch'):
            patch_state.patch_memory(altered, combined)


class StateCacheConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'base.p2s'
        self.states = Path(self.directory.name) / 'states'
        memory = bytearray(512)
        struct.pack_into('<III', memory, 16, 0x4E504331, 4, 2)
        struct.pack_into('<II', memory, 32, kit_match.BUILT_DELAY, kit_match.BUILT_MAX_STALL)
        struct.pack_into('<II', memory, 64, 0, 5)
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('other.bin', b'unchanged state payload')
            archive.writestr(kit_state.MEMORY, memory)
        self.patches = [patch.object(kit_state, 'EE_SIZE', 512),
                        patch.object(kit_match, 'QUEUE_CONTROL', 64),
                        patch.object(kit_match, '_control_guard_words', return_value={16: 0x4E504331, 20: 4, 24: 2}),
                        patch.object(kit_match, 'control_words', return_value=(32, 36))]
        for mock in self.patches:
            mock.start()
            self.addCleanup(mock.stop)

    def build(self, delay=2):
        return kit_match.netplay_state(self.source, delay, states=self.states, say=lambda text: None)

    def assert_cache(self, result, delay):
        output = Path(result['state'])
        self.assertEqual(kit_state.sha256(output), result['state_sha256'])
        meta = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(meta, result)
        self.assertEqual(kit_state.read_words(output, [32, 36]), {32: delay, 36: kit_match.BUILT_MAX_STALL})
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.read('other.bin'), b'unchanged state payload')
        self.assertFalse(list(self.states.glob('*.part')))

    def test_same_key_builders_have_one_writer_and_recheck_completed_cache(self):
        entered, release, second_lock = threading.Event(), threading.Event(), threading.Event()
        lock_requests = [0]
        guard = threading.Lock()
        original_writer, original_lock = kit_state.patch_words, kit_match._state_lock

        def request_lock(path):
            with guard:
                lock_requests[0] += 1
                if lock_requests[0] == 2:
                    second_lock.set()
            return original_lock(path)

        def slow_writer(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise OSError('test writer was not released')
            return original_writer(*args, **kwargs)

        with patch.object(kit_match, '_state_lock', side_effect=request_lock), \
                patch.object(kit_state, 'patch_words', side_effect=slow_writer) as writer, \
                ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.build)
            try:
                self.assertTrue(entered.wait(3))
                second = pool.submit(self.build)
                self.assertTrue(second_lock.wait(3))
                self.assertFalse(second.done())
                self.assertEqual(writer.call_count, 1)
                self.assertFalse(list(self.states.glob('*.p2s')))
            finally:
                release.set()
            a, b = first.result(timeout=3), second.result(timeout=3)
            self.assertEqual(a, b)
            self.assertEqual(writer.call_count, 1)
        self.assert_cache(a, 2)

    def test_failed_owner_releases_lock_and_next_owner_rebuilds_without_half_state(self):
        entered, release, second_lock = threading.Event(), threading.Event(), threading.Event()
        calls, requests = [0], [0]
        guard = threading.Lock()
        original_writer, original_lock = kit_state.patch_words, kit_match._state_lock

        def request_lock(path):
            with guard:
                requests[0] += 1
                if requests[0] == 2:
                    second_lock.set()
            return original_lock(path)

        def failed_then_valid(source, output, *args, **kwargs):
            with guard:
                calls[0] += 1
                first = calls[0] == 1
            if first:
                Path(str(output) + '.part').write_bytes(b'incomplete archive')
                entered.set()
                if not release.wait(3):
                    raise OSError('test writer was not released')
                raise OSError('forced first-writer failure')
            return original_writer(source, output, *args, **kwargs)

        with patch.object(kit_match, '_state_lock', side_effect=request_lock), \
                patch.object(kit_state, 'patch_words', side_effect=failed_then_valid), \
                ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.build)
            try:
                self.assertTrue(entered.wait(3))
                second = pool.submit(self.build)
                self.assertTrue(second_lock.wait(3))
                self.assertFalse(second.done())
                self.assertFalse(list(self.states.glob('*.p2s')))
            finally:
                release.set()
            with self.assertRaisesRegex(kit_match.KitError, 'forced first-writer failure'):
                first.result(timeout=3)
            result = second.result(timeout=3)
        self.assertEqual(calls[0], 2)
        self.assert_cache(result, 2)

    def test_different_outputs_do_not_wait_on_the_same_lock(self):
        entered, release = threading.Event(), threading.Event()
        original = kit_state.patch_words

        def slow_one(source, output, words, *args, **kwargs):
            if words[32][1] == 2:
                entered.set()
                if not release.wait(3):
                    raise OSError('test writer was not released')
            return original(source, output, words, *args, **kwargs)

        with patch.object(kit_state, 'patch_words', side_effect=slow_one), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.build, 2)
            try:
                self.assertTrue(entered.wait(3))
                second = pool.submit(self.build, 3)
                result = second.result(timeout=3)
                self.assertFalse(first.done())
            finally:
                release.set()
            first.result(timeout=3)
        self.assert_cache(result, 3)



class DecodedMemoryTests(unittest.TestCase):
    setUp = ArchiveTests.setUp
    write_source = ArchiveTests.write_source

    def proof(self):
        import kit_wire_codec
        archive = self.source.read_bytes()
        decoded = kit_wire_codec.DecodedState(archive, bytes(self.memory),
            hashlib.sha256(archive).hexdigest(), kit_wire_codec._DECODE_TOKEN)
        return kit_state.decoded_memory(self.source, decoded)

    def test_decoded_memory_cannot_be_enabled_by_metadata_or_direct_constructor(self):
        with self.assertRaises(ValueError):
            kit_state.VerifiedMemory(self.source, {}, None)
        with self.assertRaises(ValueError):
            kit_state.decoded_memory(self.source, {'archive_sha256': kit_state.sha256(self.source)})

    def test_decoder_receipt_constructor_rejects_unproved_input(self):
        import kit_wire_codec
        with self.assertRaises(ValueError):
            kit_wire_codec.DecodedState(b'archive', bytes(self.memory), '0' * 64, None)

    def test_snapshot_preserves_ram_and_requires_current_full_file_hash(self):
        proof = self.proof()
        self.assertEqual(proof.read(self.source, kit_state.sha256(self.source), self.source.stat().st_size), self.memory)
        original_size = self.source.stat().st_size
        data = bytearray(self.source.read_bytes())
        data[20] ^= 1
        self.source.write_bytes(data)
        self.assertEqual(self.source.stat().st_size, original_size)
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            proof.read(self.source)

    def test_snapshot_rejects_another_path_even_with_identical_bytes(self):
        proof = self.proof()
        self.target.write_bytes(self.source.read_bytes())
        with self.assertRaises(ValueError):
            proof.read(self.target)

    def test_snapshot_rejects_wrong_expected_sha_or_size(self):
        proof = self.proof()
        for sha, size in [('0' * 64, self.source.stat().st_size), (kit_state.sha256(self.source), 1)]:
            with self.subTest(sha=sha, size=size), self.assertRaises(ValueError):
                proof.read(self.source, sha, size)

    def test_snapshot_is_immutable_and_memory_is_bytes(self):
        proof = self.proof()
        with self.assertRaises(AttributeError):
            proof._sha = '0' * 64
        self.assertIs(type(proof.read(self.source)), bytes)

    def test_invalid_decoder_ram_shape_or_archive_hash_is_rejected(self):
        import kit_wire_codec
        archive = self.source.read_bytes()
        for memory, sha in [(b'short', hashlib.sha256(archive).hexdigest()), (bytes(self.memory), '0' * 64)]:
            decoded = kit_wire_codec.DecodedState(archive, memory, sha, kit_wire_codec._DECODE_TOKEN)
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                kit_state.decoded_memory(self.source, decoded)

    def test_verify_uses_only_proved_ram_and_retains_word_reader(self):
        import kit_verify
        proof = self.proof()
        def words(ram, static=False):
            return {32: struct.unpack('<I', ram.read_ranges([(32, 4)])[0])[0], 'static': static}
        with patch.object(kit_verify, 'FileRam', side_effect=AssertionError('redundant decode')), \
                patch.object(kit_verify, 'words', side_effect=words):
            self.assertEqual(kit_verify.file_words(self.source, static=True, snapshot=proof), {32: 8, 'static': True})
        with self.assertRaises(ValueError):
            kit_verify.file_words(self.source, snapshot={'sha': kit_state.sha256(self.source)})

    def test_manager_bounds_proof_to_one_snapshot_and_invalidates_changed_file(self):
        import kit_wire
        manager = kit_wire.Manager.__new__(kit_wire.Manager)
        manager.lock = threading.RLock()
        manager.decoded_memory = self.proof()
        sha, size = kit_state.sha256(self.source), self.source.stat().st_size
        self.assertIs(manager.snapshot_for(self.source, sha, size), manager.decoded_memory)
        self.assertIsNone(manager.snapshot_for(self.source, None, size))
        self.assertIsNone(manager.snapshot_for(self.source, sha, True))
        self.write_source(other=b'changed native state')
        self.assertIsNone(manager.snapshot_for(self.source, sha, size))
        self.assertIsNone(manager.decoded_memory)

    def test_room_cleanup_discards_receipt(self):
        import kit_wire
        manager = kit_wire.Manager.__new__(kit_wire.Manager)
        manager.lock = threading.RLock()
        manager.iso = None
        manager.decoded_memory = self.proof()
        manager.discard_snapshot()
        self.assertIsNone(manager.decoded_memory)
        manager.decoded_memory = self.proof()
        manager.close()
        self.assertIsNone(manager.decoded_memory)

    def test_canceled_decode_cannot_publish_memory_into_the_new_room(self):
        import types
        import kit_wire
        import kit_wire_codec
        archive = self.source.read_bytes()
        decoded = kit_wire_codec.DecodedState(archive, bytes(self.memory), hashlib.sha256(archive).hexdigest(),
            kit_wire_codec._DECODE_TOKEN)
        manager = kit_wire.Manager.__new__(kit_wire.Manager)
        manager.lock = threading.RLock()
        manager.iso = types.SimpleNamespace(sha256='a' * 64)
        manager.codec = types.SimpleNamespace(decode_state_with_memory=lambda *a: decoded)
        manager.decoded_memory = None
        part = self.target.with_suffix('.wire.part')
        part.write_bytes(b'wire')
        descriptor = dict(codec=kit_wire.CODEC, iso_sha256='a' * 64, size=4,
            sha256=hashlib.sha256(b'wire').hexdigest(), archive_sha256=decoded.archive_sha256,
            archive_size=len(archive))
        result = manager.restore(descriptor, part, self.target, current=lambda: False)
        self.assertEqual(result, str(self.target))  # immutable checked disk cache is allowed
        self.assertEqual(self.target.read_bytes(), archive)
        self.assertIsNone(manager.decoded_memory)


if __name__ == '__main__':
    unittest.main()
