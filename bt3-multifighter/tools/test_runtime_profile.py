"""Portable runtime layout: Windows paths are unchanged; a Linux AppImage keeps its data in <runtime>/PCSX2."""
import os
import unittest
from pathlib import Path
from unittest import mock

import runtime_profile as profile

TOOLS = Path(__file__).resolve().parent


class LayoutTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows layout')
    def test_windows_paths_are_unchanged(self):
        folder = profile.ROOT/profile.NAME
        self.assertTrue(profile.WINDOWS)
        self.assertEqual(profile.DIRECTORY, folder)
        self.assertEqual(profile.DATA, profile.DIRECTORY)
        # The exact strings every Windows caller (INI, cheats, savestates, owner check) used before.
        base = str(profile.ROOT) + '\\' + profile.NAME
        self.assertEqual(str(profile.EXECUTABLE), base + '\\pcsx2-qt.exe')
        self.assertEqual(str(profile.CONFIG), base + '\\inis\\PCSX2.ini')
        self.assertEqual(str(profile.STATES), base + '\\sstates')
        self.assertEqual(str(profile.CHEATS), base + '\\cheats')
        self.assertEqual(profile.CHEATS/'SLUS-21678_428113C2_BT3Loading.pnach',
                         profile.DIRECTORY/'cheats/SLUS-21678_428113C2_BT3Loading.pnach')

    @unittest.skipIf(os.name == 'nt', 'Linux layout')
    def test_linux_runs_the_appimage_with_its_portable_data_folder(self):
        self.assertFalse(profile.WINDOWS)
        self.assertEqual(profile.EXECUTABLE, profile.DIRECTORY/'pcsx2-qt.AppImage')
        self.assertEqual(profile.DATA, profile.DIRECTORY/'PCSX2')
        self.assertEqual(profile.CONFIG, profile.DIRECTORY/'PCSX2/inis/PCSX2.ini')
        self.assertEqual(profile.STATES, profile.DIRECTORY/'PCSX2/sstates')
        self.assertEqual(profile.CHEATS, profile.DIRECTORY/'PCSX2/cheats')

    def test_layout_helpers_for_both_platforms(self):
        folder = Path('game')/'runtime28'
        self.assertEqual(profile.executable(folder, True), folder/'pcsx2-qt.exe')
        self.assertEqual(profile.data_directory(folder, True), folder)
        self.assertEqual(profile.executable(folder, False), folder/'pcsx2-qt.AppImage')
        self.assertEqual(profile.data_directory(folder, False), folder/'PCSX2')
        for windows in (True, False):
            with mock.patch.object(profile, 'WINDOWS', windows):
                self.assertEqual(profile.data_directory(str(folder)), profile.data_directory(folder, windows))
                self.assertEqual(profile.executable(str(folder)), profile.executable(folder, windows))

    def test_pcsx2_data_callers_use_the_data_folder(self):
        for name in ('autopilot.py', 'install_boot_hooks.py'):
            source = (TOOLS/name).read_text(encoding='utf-8')
            self.assertNotIn('runtime_profile.DIRECTORY', source, name)
            self.assertIn('runtime_profile.CHEATS', source, name)
        storage = (TOOLS/'player_storage.py').read_text(encoding='utf-8')
        self.assertIn("runtime_profile.data_directory(root/runtime)/'sstates'", storage)


if __name__ == '__main__':
    unittest.main()
