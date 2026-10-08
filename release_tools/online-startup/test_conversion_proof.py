"""Full archive proof guards for online conversion without redundant EE reads."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_state
import kit_match
import patch_state


class GuardedFinalRamTests(unittest.TestCase):
    def setUp(self):
        import netplay_core as nc
        import netplay_view as nv
        import kit_verify
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.source, self.output = self.folder / 'source.p2s', self.folder / 'output.p2s'
        memory = bytearray(512)
        struct.pack_into('<III', memory, 16, 11, 4, 2)
        struct.pack_into('<II', memory, 32, kit_match.BUILT_DELAY, kit_match.BUILT_MAX_STALL)
        struct.pack_into('<II', memory, 64, 0, 5)
        self.table = b'known-hash-table'
        memory[96:96 + len(self.table)] = self.table
        self.memory = bytes(memory)
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b'readback retained'
            archive.writestr(patch_state.state128.VERSION, b'version')
            archive.writestr(patch_state.state128.INTERNAL, b'native layout')
            archive.writestr(patch_state.state128.MEMORY, self.memory)
            archive.writestr('unchanged.bin', b'unchanged non-EE bytes')
        self.manifest = dict(serial=patch_state.SERIAL, crc=patch_state.CRC,
            blocks=[dict(address=128, expected_hex='00000000', data_hex=b'core'.hex())])
        self.words = dict(native_checks=[1, 2, 3])
        self.verify = Mock(return_value=self.words)
        patches = [patch.object(patch_state.state128, 'TOTAL_RAM', 512),
            patch.object(patch_state, 'inspect_payload', return_value={'synthetic_layout': True}),
            patch.object(kit_match, 'core_options', return_value={'mask': 1, 'options': 77}),
            patch.object(nc, 'TABLE', 96), patch.object(nc, 'build_memory', return_value=self.manifest),
            patch.object(nv, 'build_memory', return_value={'blocks': []}),
            patch.object(kit_match, 'QUEUE_CONTROL', 64),
            patch.object(kit_match, '_control_guard_words', return_value={16: 11, 20: 4, 24: 2}),
            patch.object(kit_match, 'control_words', return_value=(32, 36)),
            patch.object(kit_match, 'current_table', return_value=(self.table, hashlib.sha256(self.table).hexdigest())),
            patch.object(kit_state, 'read_memory', side_effect=AssertionError('redundant EE inflation')),
            patch.object(kit_verify, 'words', self.verify)]
        for mocked in patches:
            mocked.start(); self.addCleanup(mocked.stop)

    def build(self, **kwargs):
        return kit_match.build_netplay(self.source, self.output, 1, prefix_blocks=[(120, b'prep')],
                                      source_ram=self.memory, **kwargs)

    def test_checked_final_words_match_complete_archive_readback_without_extra_inflation(self):
        result = self.build(include_words=True)
        self.assertEqual(result['verified_words'], self.words)
        checked = self.verify.call_args.args[0].data
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read(patch_state.state128.MEMORY), checked)
            self.assertEqual(archive.read('unchanged.bin'), b'unchanged non-EE bytes')
            self.assertEqual(archive.comment, b'readback retained')
        self.assertEqual(checked[120:124], b'prep')
        self.assertEqual(checked[128:132], b'core')
        self.assertEqual(result['sha256'], kit_state.sha256(self.output))

    def test_default_return_contract_does_not_retain_ram_or_add_verification_words(self):
        result = self.build()
        self.assertNotIn('verified_words', result)
        self.assertFalse(any(isinstance(value, (bytes, bytearray)) for value in result.values()))
        self.verify.assert_not_called()

    def test_missing_or_changed_ram_proof_cannot_publish_verification_words(self):
        real_patch = patch_state.patch
        for missing in (True, False):
            self.output.unlink(missing_ok=True)
            def wrong_report(*args, **kwargs):
                report = real_patch(*args, **kwargs)
                if missing: report.pop('patched_ram_sha256')
                else: report['patched_ram_sha256'] = '0' * 64
                return report
            with patch.object(patch_state, 'patch', side_effect=wrong_report):
                with self.assertRaisesRegex(ValueError, 'archive proof differs'):
                    self.build(include_words=True)
        self.verify.assert_not_called()

    def test_missing_complete_readback_status_is_not_a_native_proof(self):
        real_patch = patch_state.patch
        def incomplete(*args, **kwargs):
            report = real_patch(*args, **kwargs); report.pop('status'); return report
        with patch.object(patch_state, 'patch', side_effect=incomplete):
            with self.assertRaisesRegex(ValueError, 'archive proof differs'):
                self.build(include_words=True)
        self.verify.assert_not_called()

    def test_archive_change_during_word_checks_cannot_return_state(self):
        def change_output(ram):
            self.output.write_bytes(b'changed after readback')
            return self.words
        self.verify.side_effect = change_output
        with self.assertRaisesRegex(ValueError, 'archive changed during'):
            self.build(include_words=True)

    def test_noncombined_path_also_uses_full_guarded_final_ram(self):
        result = kit_match.build_netplay(self.source, self.output, 1, source_ram=self.memory, include_words=True)
        self.assertEqual(result['verified_words'], self.words)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read(patch_state.state128.MEMORY), self.verify.call_args.args[0].data)


if __name__ == '__main__':
    unittest.main()
