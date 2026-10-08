"""Disc identities are scoped to an installation, separate from patch IDs."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import game_profile


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.patch=patch.object(game_profile,'ROOT',self.root);self.patch.start()
        self.addCleanup(self.patch.stop)
        game_profile.pcsx2_crc.cache_clear();self.addCleanup(game_profile.pcsx2_crc.cache_clear)

    def profile(self,**fields):
        (self.root/'game-profile.json').write_text(json.dumps(dict(schema=1,adapter='bt4-b14-rev2-eng',**fields)))

    def test_developer_and_existing_installs_keep_their_identifier(self):
        self.assertEqual(game_profile.pcsx2_crc(),'428113C2')
        game_profile.pcsx2_crc.cache_clear();self.profile()
        self.assertEqual(game_profile.pcsx2_crc(),'428113C2')

    def test_installed_identifier_names_the_hook_without_changing_adapter(self):
        self.profile(pcsx2_crc='abcdef01')
        self.assertEqual(game_profile.pcsx2_crc(),'ABCDEF01')
        self.assertEqual(game_profile.cheat_name('SLUS-21978'),'SLUS-21978_ABCDEF01_BT3Loading.pnach')

    def test_malformed_identifiers_cannot_become_paths(self):
        for value in ('../file','1234',None,15):
            with self.subTest(value=value):
                self.profile(pcsx2_crc=value);game_profile.pcsx2_crc.cache_clear()
                with self.assertRaises(ValueError):game_profile.pcsx2_crc()

if __name__=='__main__':unittest.main()
