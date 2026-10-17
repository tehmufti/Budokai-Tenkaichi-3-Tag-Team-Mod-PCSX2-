"""The playtest cannot overwrite the ordinary settings or user test edits."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import mod_settings
import tag_rush_playtest as trial


class ProfileTests(unittest.TestCase):
    def test_first_run_copies_settings_and_keeps_original(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            normal = root / 'mod-settings.json'
            normal.write_text(json.dumps({'tag_team_rush_enabled': False,
                'tag_team_rush_training_full': False, 'tag_team_rush_damage': 18000}))
            before = normal.read_bytes()
            with patch.object(trial, 'ROOT', root), patch.object(trial, 'PROFILE', root/'test.json'):
                result = mod_settings.load_settings(trial.prepare_profile())
            self.assertTrue(result['tag_team_rush_enabled'])
            self.assertTrue(result['tag_team_rush_training_full'])
            self.assertEqual(result['tag_team_rush_damage'], 18000)
            self.assertEqual(normal.read_bytes(), before)

    def test_existing_test_profile_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            target = Path(directory)/'test.json'
            target.write_text(json.dumps({'tag_team_rush_charge_seconds': 8}))
            before = target.read_bytes()
            with patch.object(trial, 'PROFILE', target):
                self.assertEqual(trial.prepare_profile(), target)
            self.assertEqual(target.read_bytes(), before)

    def test_first_copy_keeps_shipped_defaults_with_test_profile_already_selected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            normal, target = root/'mod-settings.json', root/'test.json'
            normal.write_text(json.dumps({'language': 'es', 'future_setting': 42}))
            shipped = root/'player-defaults.json'
            shipped.write_text(json.dumps({'fusion_duration_seconds': 80,
                'lockon_switch_button': 'l3', 'revive_radius': 65.0}))
            before = normal.read_bytes()
            with patch.object(trial, 'ROOT', root), patch.object(trial, 'PROFILE', target), \
                    patch.object(mod_settings, 'ROOT', root), \
                    patch.object(mod_settings, 'SETTINGS_PATH', target), \
                    patch.object(mod_settings, 'DEFAULTS_PATH', root/'mod-settings-defaults.json'), \
                    patch.object(mod_settings, 'SHIPPED_DEFAULTS', shipped):
                trial.prepare_profile()
                self.assertEqual(mod_settings.SETTINGS_PATH, target)
                settings = mod_settings.load_settings(target)
            self.assertEqual(settings['fusion_duration_seconds'], 80)
            self.assertEqual(settings['lockon_switch_button'], 'l3')
            self.assertEqual(settings['revive_radius'], 65.0)
            self.assertEqual(settings['language'], 'es')
            self.assertEqual(settings['future_setting'], 42)
            self.assertEqual(normal.read_bytes(), before)

    def test_failed_copy_restores_selected_profile(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            target = root/'test.json'
            (root/'mod-settings.json').write_text('{')
            with patch.object(trial, 'ROOT', root), patch.object(trial, 'PROFILE', target), \
                    patch.object(mod_settings, 'SETTINGS_PATH', target):
                with self.assertRaises(ValueError):
                    trial.prepare_profile()
                self.assertEqual(mod_settings.SETTINGS_PATH, target)
                self.assertFalse(target.exists())

    def test_profile_override_needs_explicit_matching_root(self):
        root = Path(mod_settings.__file__).resolve().parents[1]
        for enabled, pin, expected in (('0', root, root/'mod-settings.json'),
                ('1', root/'online', root/'mod-settings.json'),
                ('1', root, root/'tag-rush-test-settings.json')):
            with self.subTest(enabled=enabled, pin=pin):
                env = dict(os.environ, TAGTEAM_TAG_RUSH_PLAYTEST=enabled,
                    TAGTEAM_TAG_RUSH_ROOT=str(pin),
                    TAGTEAM_TAG_RUSH_SETTINGS=str(root/'tag-rush-test-settings.json'))
                out = subprocess.check_output([sys.executable, '-c',
                    'import mod_settings;print(mod_settings.SETTINGS_PATH)'],
                    cwd=Path(mod_settings.__file__).parent, env=env, text=True).strip()
                self.assertEqual(Path(out), expected)


if __name__ == '__main__':
    unittest.main()
