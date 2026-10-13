"""Sacrifice controls across saved settings and both settings editors."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import copy
from pathlib import Path
import tempfile
import unittest

import feature_preferences as preferences
import ingame_settings
import localization
import mod_settings
from test_ingame_settings import Harness


ENABLED='tag_team_rush_sacrifice_enabled'
MULTIPLIER='tag_team_rush_sacrifice_multiplier'
MASTER='tag_team_rush_enabled'


class SacrificeSettingsTests(unittest.TestCase):
    def test_older_settings_gain_enabled_double_damage_without_changing_choices(self):
        original={'language':'es',MASTER:False,'tag_team_rush_damage':17000,
                  'future_option':{'keep':[1,2]}}
        before=copy.deepcopy(original)
        values=mod_settings.validate_settings(original)
        self.assertEqual(original,before)
        for key,value in original.items():self.assertEqual(values[key],value)
        self.assertIs(values[ENABLED],True)
        self.assertEqual(values[MULTIPLIER],2.0)

    def test_disabled_setting_and_fractional_multiplier_survive_other_saves(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            choices={ENABLED:False,MULTIPLIER:1.75,'language':'es',
                     'future_option':{'keep':'unchanged'}}
            mod_settings.save_settings(choices,path)
            mod_settings.save_settings({'tag_team_rush_damage':22000},path)
            loaded=mod_settings.load_settings(path)
            for key,value in choices.items():self.assertEqual(loaded[key],value)
            self.assertEqual(loaded['tag_team_rush_damage'],22000)

    def test_invalid_persisted_values_are_rejected_and_editor_stops_at_bounds(self):
        for bad in (0,1,'false',None):
            with self.subTest(toggle=bad),self.assertRaises(ValueError):
                mod_settings.validate_settings({ENABLED:bad})
        for bad in (.99,5.01,float('inf'),float('nan'),True,'2',None):
            with self.subTest(multiplier=bad),self.assertRaises(ValueError):
                mod_settings.validate_settings({MULTIPLIER:bad})
        self.assertEqual(preferences.ui_range(MULTIPLIER),(1.0,5.0))
        self.assertEqual(preferences.STEPS[MULTIPLIER],.25)
        for value in (1.0,1.75,2.0,5.0):
            self.assertEqual(mod_settings.validate_settings({MULTIPLIER:value})[MULTIPLIER],value)
        self.assertEqual(preferences.step_value(MULTIPLIER,2.0,1,anchors=[]),2.25)
        for big in (False,True):
            for start,direction,end in ((2.0,-1,1.0),(2.0,1,5.0)):
                value=start
                for _ in range(24):
                    value=preferences.step_value(MULTIPLIER,value,direction,big,anchors=[])
                    self.assertGreaterEqual(value,1.0);self.assertLessEqual(value,5.0)
                self.assertEqual(value,end)

    def test_editor_registration_and_transitive_toggle_dependency(self):
        c=ingame_settings.Controller()
        desktop=dict(mod_settings.GROUPS)['Tag-team rush']
        c.values=mod_settings.validate_settings({})
        guest=dict(c.fields(c.groups.index('Tag-team rush')))
        for key in (ENABLED,MULTIPLIER):
            self.assertIn(key,desktop);self.assertIn(key,guest)
            self.assertEqual(guest[key],mod_settings.ui_fields()[key])
        for enabled in (False,True):
            for master in (False,True):
                c.values.update({MASTER:master,ENABLED:enabled})
                self.assertEqual(c.dimmed(ENABLED),not master)
                self.assertEqual(c.dimmed(MULTIPLIER),not(master and enabled))

    def test_multiplier_and_toggle_save_in_both_languages(self):
        for language in ('en','es'):
            with self.subTest(language=language):
                h=Harness(self,{'language':language}).ready()
                h.open_group('Tag-team rush');h.select(MULTIPLIER)
                self.assertEqual(h.c.fields()[h.c.row][0],MULTIPLIER)
                self.assertEqual(h.c.values[MULTIPLIER],2.0)
                h.tick(ingame_settings.RIGHT);h.tick(ingame_settings.SQUARE)
                self.assertEqual(h.saved()[MULTIPLIER],2.25)
                h.select(ENABLED);h.tick(ingame_settings.LEFT);h.tick(ingame_settings.SQUARE)
                self.assertIs(h.saved()[ENABLED],False)
                self.assertEqual(h.saved()[MULTIPLIER],2.25)
                self.assertTrue(h.c.dimmed(MULTIPLIER))
                self.assertEqual(h.saved()['language'],language)

    def test_labels_and_sacrifice_help_are_translated_and_fit(self):
        fields=mod_settings.ui_fields();canvas=ingame_settings.Canvas()
        for key in (ENABLED,MULTIPLIER):
            label=fields[key][5]
            self.assertIn(label,localization.ES)
            self.assertNotEqual(localization.tr(label,'es'),label)
            for language in ('en','es'):
                self.assertLessEqual(canvas.width(localization.tr(label,language)),ingame_settings.LABEL_WIDTH)
        self.assertIn('Goku and enemy',fields[MULTIPLIER][5])
        note=mod_settings.notes['Tag-team rush']
        self.assertIn('off keeps normal damage without hurting Goku',note)
        self.assertIn(note,localization.ES)
        for language in ('en','es'):
            self.assertLessEqual(len(canvas.wrap(localization.tr(note,language),size=13,lines=99)),14)


if __name__=='__main__':unittest.main()
