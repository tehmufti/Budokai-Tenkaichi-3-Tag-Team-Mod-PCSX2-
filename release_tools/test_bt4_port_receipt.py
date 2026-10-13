"""The BT4 port audit covers the Linux work: the launcher, the font resolver, the bundled fonts, the Linux
developer launchers and the shared runtime modules the Linux support changed are all in the inventory, and
BT4's copies equal BT3's after the adapter rewrite (SLUS-21678 -> SLUS-21978, 28011 -> 28012)."""
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_bt4_port as port

# Modules the Linux support changed that carry no adapter facts: BT4 must hold the same code.
SHARED_LINUX = ('play_launcher', 'fonts', 'pine', 'runtime_profile', 'runtime_owner', 'presentation_settings',
                'input_binding', 'loading_audio', 'player_storage', 'install_boot_hooks', 'quad_menu_input',
                'controller_mailbox', 'coop_character_select', 'ingame_settings', 'loading_art_v4',
                'native_menu_loading', 'player_slot_labels', 'team_assignment')


class AdapterNormalizationTests(unittest.TestCase):
    def test_reviewed_text_hashes_ignore_checkout_line_endings(self):
        for suffix in ('.py','.json','.ps1','.cmd','.sh','.md','.txt'):
            with self.subTest(suffix=suffix):
                name='reviewed'+suffix
                self.assertEqual(port.normalized_file_digest(name,b'first\nsecond\n'),
                                 port.normalized_file_digest(name,b'first\r\nsecond\r\n'))

    def test_binary_hashes_keep_original_line_ending_bytes(self):
        for suffix in ('.bin','.png','.ttf','.pnach'):
            with self.subTest(suffix=suffix):
                name='resource'+suffix
                self.assertEqual(port.normalize_reviewed_text(name,b'\x00\r\n\xff'),b'\x00\r\n\xff')
                self.assertNotEqual(port.normalized_file_digest(name,b'\x00\r\n\xff'),
                                    port.normalized_file_digest(name,b'\x00\n\xff'))

    def test_file_hashes_preserve_semantic_and_adapter_changes(self):
        before=b"PINE_SLOT = 28011\nserial = 'SLUS-21678'\n"
        after=b"PINE_SLOT = 28012\nserial = 'SLUS-21978'\n"
        self.assertNotEqual(port.normalized_file_digest('pine.py',before),
                            port.normalized_file_digest('pine.py',after))
        self.assertNotEqual(port.normalized_file_digest('data.json',b'{"rows":12}\n'),
                            port.normalized_file_digest('data.json',b'{"rows":24}\n'))

    def test_port_literals_and_regional_identifiers_are_normalized(self):
        source=b"PINE_SLOT = 28011\r\nslot = '28011'\r\nserial = 'SLUS-21678'\r\nelf = 'SLUS_216.78'\r\n"
        expected=b"PINE_SLOT = 28012\nslot = '28012'\nserial = 'SLUS-21978'\nelf = 'SLUS_219.78'\n"
        self.assertEqual(port.normalize_bt3_python(source), expected)

    def test_shared_pose_decimals_and_other_numeric_values_are_preserved(self):
        source=b'pose = (-0.034866280114735505, 0.034866280114735505)\nvalues = (128011, 280110, 28011.0, .28011, 28011e3, 0x28011)\nport28011 = 0\n'
        self.assertEqual(port.normalize_bt3_python(source), source)


class Bt4PortInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = port.inventory()['files']

    def test_linux_runtime_modules_are_audited_and_shared(self):
        for module in SHARED_LINUX:
            name = f'tools/{module}.py'
            with self.subTest(name=name):
                self.assertIn(name, self.files)
                self.assertTrue(self.files[name]['shared'], name)

    def test_bundled_fonts_are_audited_byte_for_byte(self):
        for name in ('LiberationSans-Regular.ttf', 'LiberationSans-Bold.ttf', 'LICENSE', 'README.md'):
            row = self.files['tools/vendor/fonts/'+name]
            with self.subTest(name=name):
                self.assertTrue(row['shared']); self.assertEqual(row['bt3'], row['bt4'])

    def test_linux_developer_launchers_are_shared_entry_points(self):
        for name in ('Play.sh', 'Mod settings.sh'):
            self.assertEqual(port.ENTRYPOINTS[name], name)
            with self.subTest(name=name):
                self.assertTrue(self.files[name]['shared']); self.assertEqual(self.files[name]['bt3_path'], name)

    def test_bt4_keeps_its_own_preflight(self):
        row = self.files['tools/bt4_preflight.py']
        self.assertFalse(row['shared']); self.assertNotIn('bt3', row)

    def test_entire_receipt_survives_text_checkout_line_endings(self):
        original=Path.read_bytes
        def alternate_checkout(path):
            data=original(path)
            if path.suffix.lower() in port.REVIEWED_TEXT_SUFFIXES:
                return data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            return data
        with patch.object(Path,'read_bytes',alternate_checkout):
            self.assertEqual(port.inventory()['files'],self.files)


if __name__ == '__main__':
    unittest.main()
