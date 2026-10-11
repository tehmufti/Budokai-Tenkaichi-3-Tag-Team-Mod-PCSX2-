"""Fusion-buff editor contract, without running or connecting to the game."""
import copy
from pathlib import Path
import tempfile
import unittest

import feature_preferences as preferences
import ingame_settings
import localization
import mod_settings


KINDS=('potara','non_potara')
STATS=('health','damage','defense')


class FusionBuffSettingsTests(unittest.TestCase):
    def test_old_settings_preserve_choices_and_leave_both_buffs_disabled(self):
        original={'language':'es','fusion_duration_seconds':80,'future_option':{'keep':[1,2]}}
        before=copy.deepcopy(original)
        result=mod_settings.validate_settings(original)
        self.assertEqual(original,before)
        for key,value in original.items():self.assertEqual(result[key],value)
        for kind in KINDS:
            self.assertFalse(result[f'fusion_{kind}_buffs_enabled'])
            for stat in STATS:self.assertEqual(result[f'fusion_{kind}_{stat}_multiplier'],1.0)

    def test_separate_buff_settings_roundtrip_and_preserve_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            selected={'fusion_potara_buffs_enabled':True,'fusion_potara_health_multiplier':2.5,
                      'fusion_potara_damage_multiplier':1.75,'fusion_potara_defense_multiplier':2.0,
                      'fusion_non_potara_buffs_enabled':True,'fusion_non_potara_health_multiplier':1.25,
                      'fusion_non_potara_damage_multiplier':1.5,'fusion_non_potara_defense_multiplier':0.75,
                      'fusion_duration_seconds':80,'future_option':{'keep':'unchanged'}}
            saved=mod_settings.save_settings(selected,path)
            self.assertEqual(mod_settings.load_settings(path),saved)
            saved=mod_settings.save_settings({'fusion_potara_buffs_enabled':False},path)
            for key,value in selected.items():
                self.assertEqual(saved[key],False if key=='fusion_potara_buffs_enabled' else value)

    def test_only_finite_bounded_multipliers_and_real_booleans_are_accepted(self):
        for kind in KINDS:
            key=f'fusion_{kind}_buffs_enabled'
            for bad in (0,1,'false',None):
                with self.subTest(key=key,value=bad),self.assertRaises(ValueError):
                    mod_settings.validate_settings({key:bad})
            for stat in STATS:
                key=f'fusion_{kind}_{stat}_multiplier'
                for accepted in (0.25,1,5.0):
                    self.assertEqual(mod_settings.validate_settings({key:accepted})[key],accepted)
                for bad in (0,0.24,5.01,float('inf'),float('nan'),True,'2'):
                    with self.subTest(key=key,value=bad),self.assertRaises(ValueError):
                        mod_settings.validate_settings({key:bad})

    def test_both_editors_expose_separate_multipliers_with_quarter_steps(self):
        controller=ingame_settings.Controller()
        controller.values=mod_settings.validate_settings({})
        fields=dict(controller.fields(controller.groups.index('Fusion')))
        desktop=dict(mod_settings.GROUPS)['Fusion']
        for kind in KINDS:
            enabled=f'fusion_{kind}_buffs_enabled'
            self.assertIn(enabled,desktop);self.assertIn(enabled,fields)
            for stat in STATS:
                key=f'fusion_{kind}_{stat}_multiplier'
                self.assertIn(key,desktop);self.assertIn(key,fields)
                self.assertEqual(preferences.STEPS[key],0.25)
                self.assertTrue(controller.dimmed(key))
                controller.values[enabled]=True
                self.assertFalse(controller.dimmed(key))
                controller.change(key,1);self.assertEqual(controller.values[key],1.25)
                controller.values['fusion_enabled']=False
                self.assertTrue(controller.dimmed(key))
                controller.values['fusion_enabled']=True
                controller.values[enabled]=False

    def test_labels_and_complete_help_are_translated_and_fit(self):
        fields=mod_settings.ui_fields()
        canvas=ingame_settings.Canvas()
        for kind in KINDS:
            for key in (f'fusion_{kind}_buffs_enabled',*(f'fusion_{kind}_{s}_multiplier'for s in STATS)):
                label=fields[key][5]
                self.assertIn(label,localization.ES)
                self.assertNotEqual(localization.tr(label,'es'),label)
        note=mod_settings.notes['Fusion']
        for language in ('en','es'):
            translated=localization.tr(note,language)
            self.assertLessEqual(len(canvas.wrap(translated,size=13)),14)
        self.assertIn('2x defense halves damage taken',note)
        self.assertIn('preselected forms are unaffected',note)


if __name__=='__main__':unittest.main()
