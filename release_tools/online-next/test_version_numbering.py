"""Renumbered public installs must reach the existing guest-code checks."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'bt3-multifighter/online/netplay'))
import kit_install
from kit_codes import KitError


class ReleaseNumbering(unittest.TestCase):
    def test_renumbered_and_future_releases_remain_candidates(self):
        for version in ('0.1.0-beta.7', '0.1.0-beta.8', '0.1.0-beta.46'):
            with self.subTest(version=version):
                self.assertEqual(kit_install.build_status(version), 'candidate')
        self.assertEqual(kit_install.build_status('0.1.0-beta.35'), 'known')
        for version in (None, '', '0.1.0-beta.6', '0.1.0-beta.bad', '0.1.0-beta.7-extra'):
            with self.subTest(version=version):
                self.assertEqual(kit_install.build_status(version), 'refused')

    def test_version_seven_installation_can_be_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            game=root/'game'
            game.mkdir()
            (game/'player-install.json').write_text(json.dumps(dict(schema=1,adapter='bt3-usa',version='0.1.0-beta.7')))
            (game/'game-profile.json').write_text(json.dumps(dict(adapter='bt3-usa',iso=str(root/'game.iso'),iso_sha256='a'*64)))
            with patch.object(kit_install,'load_settings',return_value={}):
                result=kit_install.read_installation(root)
                self.assertEqual(result['version'],'0.1.0-beta.7')
                self.assertEqual(result['build'],'candidate')
                self.assertEqual(result['adapter'],'bt3-usa')
                (game/'player-install.json').write_text(json.dumps(dict(adapter='bt3-usa',version='0.1.0-beta.6')))
                with self.assertRaises(KitError):
                    kit_install.read_installation(root)


if __name__=='__main__':
    unittest.main()
