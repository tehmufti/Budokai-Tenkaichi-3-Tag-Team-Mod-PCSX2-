"""Normal settings integration must never leak offline attacks into netplay."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tag_rush_availability as availability
import mod_settings
import localization


class ReleaseAdmissionTests(unittest.TestCase):
    def test_private_builder_marker_blocks_before_ram_has_network_hooks(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{availability.ONLINE_PREPARATION_ENV:'0'}):
            root=Path(folder)
            self.assertEqual(availability.preparation_reason({},'teams',root,adapter='bt3-usa'),'')
            (root/availability.ONLINE_PREPARATION_MARKER).write_text('{}')
            self.assertIn('online',availability.preparation_reason({},'teams',root,adapter='bt3-usa'))

    def test_regional_admission_imports_no_tag_guest_modules(self):
        script=('import sys; import tag_rush_availability as t; '
                'assert t.preparation_reason({}, "teams", "."); '
                'assert "tag_rush_effects" not in sys.modules; '
                'assert "tag_rush_scene" not in sys.modules')
        for adapter in ('bt3-pal','bt3-jpn'):
            env=dict(os.environ,TAGTEAM_ADAPTER=adapter)
            result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).parent,env=env,
                                  capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,adapter+' '+result.stderr)

    def test_normal_ui_defaults_and_both_language_help_are_complete(self):
        self.assertTrue(mod_settings.DEFAULTS['tag_team_rush_enabled'])
        self.assertEqual(mod_settings.DEFAULTS['tag_team_rush_damage'],15000)
        self.assertEqual(mod_settings.DEFAULTS['tag_team_rush_charge_seconds'],25)
        self.assertFalse(mod_settings.DEFAULTS['tag_team_rush_training_full'])
        self.assertFalse(mod_settings.DEFAULTS['tag_team_rush_shared_camera'])
        note=mod_settings.notes['Tag-team rush']
        for language in ('en','es'):
            translated=localization.tr(note,language)
            self.assertNotIn('playtest',translated.lower())
            self.assertNotIn('test settings',translated.lower())
            self.assertIn('BT4',translated)
        self.assertNotEqual(localization.tr(note,'es'),note)

    def test_online_forces_tag_off_and_strips_private_test_profile(self):
        kit=Path(__file__).resolve().parents[2]/'bt3-multifighter/online/netplay'
        if not kit.is_dir():self.skipTest('Shared online source is not present')
        script=('import os; import kit_settings as s; import kit_prepare_launch as launch; '
                'from unittest.mock import patch; '
                'keys=("tag_team_rush_enabled","tag_team_rush_damage",'
                '"tag_team_rush_charge_seconds","tag_team_rush_training_full","tag_team_rush_shared_camera"); '
                'assert not s.match_settings({"tag_team_rush_enabled":True},{},"en")[keys[0]]; '
                'assert all(k in s.CLASS for k in keys); '
                'assert all(k not in s.GAMEPLAY for k in keys); '
                'os.environ["TAGTEAM_TAG_RUSH_PLAYTEST"]="1"; '
                'os.environ["TAGTEAM_TAG_RUSH_ROOT"]="test"; '
                'os.environ["TAGTEAM_TAG_RUSH_SETTINGS"]="test.json"; '
                'env=launch.clean_environment(); '
                'assert env["TAGTEAM_ONLINE_PREPARATION"]=="1"; '
                'assert not any(k.startswith("TAGTEAM_TAG_RUSH_") for k in env)')
        result=subprocess.run([sys.executable,'-c',script],cwd=kit,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
