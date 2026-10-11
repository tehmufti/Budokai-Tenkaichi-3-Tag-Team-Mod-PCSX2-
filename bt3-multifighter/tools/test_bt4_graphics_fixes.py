"""Version-derived BT4 aliases and reversible Play/installer ownership."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bt4_graphics_fixes as g
import presentation_settings as presentation


def database(scaling=4, newline='\n'):
    return newline.join(['# PCSX2 fixture', 'SLUS-21678:', '  name: "BT3"',
        '  gsHWFixes:', '    halfPixelOffset: 5 # Alignment',
        f'    nativeScaling: {scaling}', '    beforeDraw: "OI_DBZBTGames"',
        '  patches:', '    default:', '      content: |', '        NOT COPIED',
        'OTHER-00000:', '  name: "Preserved"', '']).encode()


def runtime(root, raw=None):
    root = Path(root); (root/'resources').mkdir(parents=True)
    (root/'pcsx2-qt.exe').write_bytes(b'fixture')
    (root/g.RESOURCE).write_bytes(database() if raw is None else raw)
    return root


class GraphicsTests(unittest.TestCase):
    def test_uses_selected_emulators_enums_and_copies_only_gs_fixes(self):
        for scaling in (2, 4):
            for newline in ('\n', '\r\n'):
                with self.subTest(scaling=scaling, newline=newline):
                    raw = database(scaling, newline)
                    result = g.plan(raw, g.ADAPTER)
                    self.assertEqual(result['data'][:len(raw)], raw)
                    block = result['inserted']
                    self.assertIn(f'nativeScaling: {scaling}'.encode(), block)
                    self.assertIn(b'OI_DBZBTGames', block)
                    self.assertNotIn(b'patches:', block)
                    self.assertNotIn(b'NOT COPIED', block)
                    self.assertEqual(g.plan(result['data'], g.ADAPTER),
                                     dict(state='existing-alignment', ready=True))

    def test_bt3_and_other_adapters_are_not_changed(self):
        for adapter in ('bt3-usa', 'bt3-pal', 'bt3-jpn', 'unknown'):
            self.assertEqual(g.plan(b'not even YAML', adapter)['state'], 'not-bt4')

    def test_custom_bt4_entry_is_preserved_case_insensitively(self):
        for serial in (g.TARGET, g.TARGET.lower()):
            raw = database()+f'{serial}:\n  name: "User entry"\n'.encode()
            result = g.plan(raw, g.ADAPTER)
            self.assertEqual(result, dict(state='existing-entry-preserved', ready=False))

    def test_duplicate_missing_and_malformed_source_refuse_without_guessing(self):
        bad = [database()+database(), database().replace(b'SLUS-21678:', b'OTHER-1:'),
               database().replace(b'nativeScaling: 4', b'nativeScaling: 0'),
               database().replace(b'OI_DBZBTGames', b'AnotherGame'),
               database().replace(b'halfPixelOffset: 5', b'halfPixelOffset: *guess'),
               database()+b'SLUS-21978:\n  name: A\nslus-21978:\n  name: B\n']
        for raw in bad:
            with self.subTest(raw=raw[-40:]), self.assertRaises(ValueError):
                g.plan(raw, g.ADAPTER)

    def test_session_restores_exact_bytes_and_preserves_unrelated_edits(self):
        for raw in (database(), b'\xef\xbb\xbf'+database(2, '\r\n'), database().rstrip()):
            with tempfile.TemporaryDirectory() as tmp:
                folder = runtime(tmp, raw); receipt = folder/'receipt.json'
                g.apply(folder, g.ADAPTER, receipt)
                path = folder/g.RESOURCE
                extra = b'\nOTHER-00001:\n  name: Added during play\n'
                path.write_bytes(path.read_bytes()+extra)
                self.assertTrue(g.restore(folder, receipt))
                self.assertEqual(path.read_bytes(), raw+extra)
                self.assertFalse(receipt.exists())

    def test_repeated_launch_recovers_abandoned_session_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = runtime(tmp); receipt = folder/'receipt.json'
            for _ in range(3): g.apply(folder, g.ADAPTER, receipt)
            self.assertEqual((folder/g.RESOURCE).read_bytes().count(b'SLUS-21978:'), 1)
            self.assertTrue(g.restore(folder, receipt))
            self.assertEqual((folder/g.RESOURCE).read_bytes(), database())

    def test_owned_alias_edited_during_play_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = runtime(tmp); receipt = folder/'receipt.json'
            g.apply(folder, g.ADAPTER, receipt)
            path = folder/g.RESOURCE
            changed = path.read_bytes().replace(b'name: "Dragon Ball Z - Budokai Tenkaichi 4"', b'name: "My BT4"')
            path.write_bytes(changed)
            self.assertFalse(g.restore(folder, receipt))
            self.assertEqual(path.read_bytes(), changed)

    def test_receipt_cannot_remove_unrelated_resource_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = runtime(tmp); receipt = folder/'receipt.json'
            receipt.write_text(json.dumps(dict(schema=1, resource=g.RESOURCE,
                inserted=database().decode())))
            with self.assertRaises(ValueError): g.restore(folder, receipt)
            self.assertEqual((folder/g.RESOURCE).read_bytes(), database())

    def test_install_is_idempotent_and_source_emulator_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = runtime(root/'source')
            target = runtime(root/'copied', (source/g.RESOURCE).read_bytes())
            self.assertTrue(g.apply(target, g.ADAPTER)['ready'])
            fixed = (target/g.RESOURCE).read_bytes()
            self.assertTrue(g.apply(target, g.ADAPTER)['ready'])
            self.assertEqual((target/g.RESOURCE).read_bytes(), fixed)
            self.assertEqual((source/g.RESOURCE).read_bytes(), database())

    def test_appimage_and_missing_resources_are_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'pcsx2-qt.AppImage').write_bytes(b'fixture')
            self.assertEqual(g.apply(root, g.ADAPTER)['state'], 'no-writable-windows-resources')
            (root/'pcsx2-qt.exe').write_bytes(b'fixture')
            self.assertEqual(g.apply(root, g.ADAPTER)['state'], 'missing-game-database')

    def test_recognized_spanish_and_english_profiles_use_same_adapter(self):
        for language in ('en', 'es'):
            # The ISO scanner proves both variants and exposes one stable adapter.
            with self.subTest(language=language), patch('game_profile.installed_adapter', return_value=g.ADAPTER):
                self.assertEqual(g.selected_adapter(), g.ADAPTER)
        with patch('game_profile.installed_adapter', return_value=None), \
                patch('native_map.SERIAL', 'SLUS-21978'), patch('native_map.CRC', '428113C2'), \
                patch('native_map.ADAPTER', 'bt3-usa'):
            self.assertEqual(g.selected_adapter(), g.ADAPTER)
        with patch('game_profile.installed_adapter', return_value='bt3-pal'):
            self.assertEqual(g.selected_adapter(), 'bt3-pal')

    def test_play_changes_only_manual_fix_switch_and_restores_profile_and_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = runtime(tmp); config = root/'inis/PCSX2.ini'; config.parent.mkdir()
            profile = (b'[EmuCore]\n[EmuCore/GS]\nUserHacks = true\nupscale_multiplier = 4\n'
                       b'UserHacks_TCOffsetX = 17\nUserHacks_TCOffsetY = 23\n')
            config.write_bytes(profile); receipt = root/'analysis/presentation.json'
            with patch.object(g, 'selected_adapter', return_value=g.ADAPTER), \
                    patch('mod_settings.load_settings', return_value={'widescreen_patch': False}), \
                    patch('widescreen_support.embedded', return_value=False), \
                    contextlib.redirect_stdout(io.StringIO()):
                presentation.apply(config, receipt)
                self.assertIn(b'UserHacks = false', config.read_bytes())
                self.assertIn(b'upscale_multiplier = 4', config.read_bytes())
                self.assertIn(b'UserHacks_TCOffsetX = 17', config.read_bytes())
                self.assertIn(b'SLUS-21978:', (root/g.RESOURCE).read_bytes())
                presentation.restore(config, receipt)
            self.assertEqual(config.read_bytes(), profile)
            self.assertEqual((root/g.RESOURCE).read_bytes(), database())


if __name__ == '__main__': unittest.main()
