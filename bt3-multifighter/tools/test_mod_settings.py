"""Settings persistence and UI transaction behavior, without creating windows."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import atomic_files
import mod_settings as settings


class ModSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'mod-settings.json'

    def test_retired_genocide_option_cannot_be_reenabled_by_an_old_settings_file(self):
        import feature_preferences
        result=settings.save_settings({'buu_ultimate_all_enemies':True},self.path)
        self.assertNotIn('buu_ultimate_all_enemies',result)
        self.assertNotIn('buu_ultimate_all_enemies',self.path.read_text())
        self.assertNotIn('buu_ultimate_all_enemies',feature_preferences.OPTIONS)

    def test_missing_file_defaults_all_without_creating_it(self):
        self.assertEqual(settings.load_settings(self.path), settings.DEFAULTS)
        self.assertFalse(self.path.exists())

    def test_corpse_safety_default_enabled_optional_and_strict(self):
        self.assertTrue(settings.load_settings(self.path)[settings.CORPSE_SAFETY_KEY])
        result=settings.SettingsController(self.path).save('none',corpse_safety=False)
        self.assertFalse(result[settings.CORPSE_SAFETY_KEY])
        self.assertFalse(settings.save_settings({'future':42},self.path)[settings.CORPSE_SAFETY_KEY])
        original=self.path.read_bytes()
        for bad in (0,1,'false',None,[]):
            with self.assertRaises(ValueError):settings.save_settings({settings.CORPSE_SAFETY_KEY:bad},self.path)
        self.assertEqual(self.path.read_bytes(),original)

    def test_revival_opt_in_cost_and_duration_roundtrip_are_separate_from_ki(self):
        self.assertFalse(settings.load_settings(self.path)[settings.REVIVE_KEY])
        choices={settings.REVIVE_KEY:True,settings.REVIVE_COST_KEY:4,settings.REVIVE_CHANNEL_KEY:1.5}
        got=settings.SettingsController(self.path).save('none',revival=choices)
        self.assertTrue(all(got[k]==v for k,v in choices.items()))
        got=settings.save_settings({'future':42},self.path)
        self.assertTrue(all(got[k]==v for k,v in choices.items()))
        original=self.path.read_bytes()
        for key,values in ((settings.REVIVE_KEY,(1,'yes',None)),
                (settings.REVIVE_COST_KEY,(-1,101,True,1.5,'4')),
                (settings.REVIVE_CHANNEL_KEY,(0,0.1,61,True,float('nan'),float('inf'),'4'))):
            for value in values:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    settings.save_settings({key:value},self.path)
        with self.assertRaises(ValueError):settings.SettingsController(self.path).save('none',revival={'ki_cost':4})
        self.assertEqual(self.path.read_bytes(),original)

    def test_explicit_false_round_trips_and_preserves_unrelated_fields(self):
        atomic_files.write_json(self.path, {'version': 1, 'future': {'scale': [1, 2], 'enabled': False}})
        result = settings.save_settings({settings.PAUSE_KEY: False}, self.path)
        self.assertEqual(result[settings.MODE_KEY],'target')
        self.assertNotIn(settings.PAUSE_KEY,result)
        self.assertEqual(result['version'],2)
        self.assertEqual(result['future'], {'scale': [1, 2], 'enabled': False})
        self.assertEqual(settings.load_settings(self.path), result)

    def test_strict_boolean_and_version_reject_truthy_values(self):
        for value in (0, 1, 'false', None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.save_settings({settings.PAUSE_KEY: value}, self.path)
        for value in (True, 0, 3, '1', None):
            with self.subTest(version=value), self.assertRaises(ValueError):
                settings.save_settings({'version': value}, self.path)
        self.assertFalse(self.path.exists())

    def test_the_right_stick_mode_is_its_own_choice_and_the_stick_switch_stays_a_bool(self):
        # beta.35: lockon_right_stick stays true/false (so a beta.34 install still reads the file) and the separate
        # lockon_right_stick_mode says how it picks; a file without the mode gets its default, with no migration.
        result = settings.save_settings({'lockon_right_stick_mode': 'right_stick_alone'}, self.path)
        self.assertEqual((result['lockon_right_stick'], result['lockon_right_stick_mode']), (True, 'right_stick_alone'))
        self.assertEqual(settings.load_settings(self.path)['lockon_right_stick_mode'], 'right_stick_alone')
        for key, value in (('lockon_right_stick_mode', 'off'), ('lockon_right_stick_mode', True),
                           ('lockon_right_stick_mode', None), ('lockon_right_stick_mode', 2),
                           ('lockon_right_stick', 'right_stick_alone'), ('lockon_right_stick', 1)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                settings.validate_settings({key: value})
        self.assertEqual(settings.validate_settings({'lockon_right_stick': False})['lockon_right_stick_mode'],
                         'with_switch_button')
        self.assertEqual((settings.DEFAULTS['lockon_right_stick'], settings.DEFAULTS['lockon_right_stick_mode']),
                         (True, 'with_switch_button'))
        self.assertEqual(settings.VERSION, 2)

    def test_malformed_or_ambiguous_existing_data_is_not_reset(self):
        samples = [b'{', b'[]', b'{"version":3}', b'{"version":1,"version":1}',
                   b'{"future":NaN}', b'\xff']
        for raw in samples:
            self.path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                settings.save_settings({settings.PAUSE_KEY: False}, self.path)
            self.assertEqual(self.path.read_bytes(), raw)

    def test_ui_cancel_and_window_close_do_not_write(self):
        controller = settings.SettingsController(self.path)
        controller.cancel()
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            controller.save('target')
        self.path.write_text('{"version":1,"future":42}')
        original = self.path.read_bytes()
        settings.SettingsController(self.path).cancel()
        self.assertEqual(self.path.read_bytes(), original)

    def test_ui_save_merges_latest_unrelated_edit_since_window_opened(self):
        controller = settings.SettingsController(self.path)
        atomic_files.write_json(self.path, {'version': 1, 'future': {'changed': True}})
        result = controller.save('target')
        self.assertEqual(result['future'], {'changed': True})
        self.assertEqual(result[settings.MODE_KEY],'target')
        self.assertTrue(controller.closed)

    def test_failed_atomic_save_preserves_file_and_keeps_ui_retryable(self):
        settings.save_settings({settings.PAUSE_KEY: True}, self.path)
        original = self.path.read_bytes()
        controller = settings.SettingsController(self.path)
        with mock.patch.object(atomic_files, 'write_json', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                controller.save('none')
        self.assertFalse(controller.closed)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(controller.save('none')[settings.MODE_KEY],'none')

    def test_version1_migration_is_read_only_and_keeps_both_old_meanings(self):
        for old,mode in ((True,'all'),(False,'target')):
            self.path.write_text(json.dumps({'version':1,settings.PAUSE_KEY:old,'future':{'x':[1,2]}}))
            raw=self.path.read_bytes();result=settings.load_settings(self.path)
            self.assertEqual(result,{**settings.DEFAULTS,settings.MODE_KEY:mode,'future':{'x':[1,2]}})
            self.assertEqual(self.path.read_bytes(),raw)

    def test_three_modes_round_trip_and_invalid_or_mixed_schemas_are_rejected(self):
        for mode in ('all','target','none'):
            result=settings.save_settings({settings.MODE_KEY:mode},self.path)
            self.assertEqual(result[settings.MODE_KEY],mode)
            self.assertEqual(settings.load_settings(self.path),result)
        original=self.path.read_bytes()
        for bad in ('off',None,False,0,2,[],{}):
            with self.assertRaises(ValueError):settings.save_settings({settings.MODE_KEY:bad},self.path)
        for bad in ({'version':1,settings.MODE_KEY:'none'},
                    {'version':2,settings.PAUSE_KEY:False},
                    {settings.MODE_KEY:'none',settings.PAUSE_KEY:False}):
            with self.assertRaises(ValueError):settings.save_settings(bad,self.path)
        self.assertEqual(self.path.read_bytes(),original)

    def test_unrelated_or_version_only_update_preserves_selected_none(self):
        settings.save_settings({settings.MODE_KEY:'none','future':1},self.path)
        result=settings.save_settings({'version':1,'future':2},self.path)
        self.assertEqual(result,{**settings.DEFAULTS,settings.MODE_KEY:'none','future':2})
        self.assertEqual(settings.save_settings({'other':3},self.path)[settings.MODE_KEY],'none')

    def test_show_outputs_json_without_ui_or_disk_changes(self):
        output = io.StringIO()
        with mock.patch.object(settings, 'SETTINGS_PATH', self.path), \
             mock.patch.object(settings, 'show_ui') as ui, contextlib.redirect_stdout(output):
            self.assertEqual(settings.main(['--show']), 0)
        self.assertEqual(json.loads(output.getvalue()), settings.DEFAULTS)
        self.assertFalse(self.path.exists())
        ui.assert_not_called()

    def test_new_cinematic_and_coop_controls_are_independent_and_strict(self):
        self.path.write_text('{"version":2,"special_pause_mode":"none"}')
        original=self.path.read_bytes()
        loaded=settings.load_settings(self.path)
        self.assertFalse(loaded[settings.ULTIMATE_KEY])
        self.assertFalse(loaded[settings.TRANSFORMATION_KEY])
        self.assertEqual(self.path.read_bytes(),original)
        for fusion in settings.FUSION_MODES:
            got=settings.SettingsController(self.path).save('none',ultimate=True,transformation=False,fusion=fusion)
            self.assertTrue(got[settings.ULTIMATE_KEY]);self.assertFalse(got[settings.TRANSFORMATION_KEY])
            self.assertEqual(got[settings.COOP_FUSION_KEY],fusion)
            self.assertTrue(settings.save_settings({'future':3},self.path)[settings.ULTIMATE_KEY])
        original=self.path.read_bytes()
        for key in (settings.ULTIMATE_KEY,settings.TRANSFORMATION_KEY):
            for value in (0,1,'false',None):
                with self.assertRaises(ValueError):settings.save_settings({key:value},self.path)
        for value in ('swap',False,20,None):
            with self.assertRaises(ValueError):settings.save_settings({settings.COOP_FUSION_KEY:value},self.path)
        self.assertEqual(self.path.read_bytes(),original)

    def test_lockon_button_defaults_to_r3_round_trips_and_is_strict(self):
        self.path.write_text('{"version":2,"special_pause_mode":"none"}')
        original=self.path.read_bytes()
        loaded=settings.load_settings(self.path)
        self.assertEqual(loaded[settings.LOCKON_KEY],'r3')
        self.assertEqual(settings.lockon_mask(loaded),4)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(settings.DEFAULTS[settings.LOCKON_KEY],'r3')
        self.assertEqual(settings.lockon_mask({'version':1,settings.PAUSE_KEY:False}),4)
        for button,mask in (('l3',2),('r3',4)):
            got=settings.SettingsController(self.path).save('none',lockon=button)
            self.assertEqual(got[settings.LOCKON_KEY],button)
            self.assertEqual(got[settings.MODE_KEY],'none')
            self.assertEqual(settings.lockon_mask(got),mask)
            self.assertEqual(settings.load_settings(self.path),got)
            # Unrelated edits and a save without the keyword keep the selection.
            self.assertEqual(settings.save_settings({'future':3},self.path)[settings.LOCKON_KEY],button)
            self.assertEqual(settings.SettingsController(self.path).save('all')[settings.LOCKON_KEY],button)
        self.assertEqual(settings.save_settings({settings.LOCKON_KEY:'l3'},self.path)[settings.LOCKON_KEY],'l3')
        original=self.path.read_bytes()
        for value in ('R3',4,2,None,True,'unknown',''):
            with self.subTest(value=value),self.assertRaises(ValueError):
                settings.save_settings({settings.LOCKON_KEY:value},self.path)
            with self.subTest(value=value),self.assertRaises(ValueError):
                settings.lockon_mask({'version':2,settings.LOCKON_KEY:value})
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(settings.load_settings(self.path)[settings.LOCKON_KEY],'l3')
        output=io.StringIO()
        with mock.patch.object(settings,'SETTINGS_PATH',self.path),contextlib.redirect_stdout(output):
            self.assertEqual(settings.main(['--show']),0)
        self.assertEqual(json.loads(output.getvalue())[settings.LOCKON_KEY],'l3')


PLAYER_DEFAULTS = Path(settings.__file__).resolve().parents[2] / 'player-installer' / 'player-defaults.json'
PAGES = ('Menus', 'Players and controllers', 'Controls', 'Movement', 'Cinematics', 'Fusion', 'Fighters', 'Giants', 'HUD',
         'Split-screen HUD', 'Spectating', 'Revival', 'Outnumbered', 'Beam struggles', 'Training',
         'Launch options (restart)',
         'Diagnostics')
# The desktop window lists its own pages after the settings pages (beta.34: Game disc); the in-game screens do not.
DESKTOP_PAGES = PAGES + ('Game disc',)


class OrganisationTests(unittest.TestCase):
    """Pages, restore/repair and adapter facts of the reorganised settings."""
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'mod-settings.json'
        self.defaults_path = Path(self.directory.name) / 'mod-settings-defaults.json'
        patcher = mock.patch.object(settings, 'DEFAULTS_PATH', self.defaults_path)
        patcher.start(); self.addCleanup(patcher.stop)
        self.code_defaults = {k: v for k, v in settings.DEFAULTS.items() if k not in ('language', 'version')}

    def installed(self):
        if not PLAYER_DEFAULTS.is_file(): self.skipTest('player-installer is not beside this adapter')
        return json.loads(PLAYER_DEFAULTS.read_text(encoding='utf-8'))

    def test_pages_cover_every_editable_key_once_in_the_agreed_order(self):
        import feature_preferences as features
        self.assertEqual(settings.ui_groups(), PAGES)
        keys = [key for _, page in settings.GROUPS for key in page]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(list(settings.ui_fields()), keys)
        self.assertEqual(set(keys), set(settings.DEFAULTS) - {'version', settings.NPC_OVERRIDES_KEY})
        pages = dict(settings.GROUPS)
        for key, row in settings.ui_fields().items():
            self.assertEqual(len(row), 6)
            self.assertIn(key, pages[row[4]])
            if key in features.OPTIONS: self.assertEqual(features.OPTIONS[key][4], row[4], key)
        self.assertEqual(pages['Revival'], settings.REVIVE_KEYS)
        self.assertEqual(len(settings.REVIVE_KEYS), 11)
        self.assertEqual(pages['HUD'], (*settings.DISPLAY_KEYS, 'lockoff_target_hud', 'lockon_target_marker', 'lockon_target_style',
                                        'lockon_threat_marks'))
        self.assertEqual(pages['Fusion'][:3], (settings.COOP_FUSION_KEY, 'show_fusion_control_owner',
                                               'show_fusion_control_countdown'))
        self.assertIn(settings.EXCEPTIONS_GROUP, pages)
        # Paths the player README/LEEME cite: Menus -> Language / Idioma, Controls.
        self.assertEqual(settings.ui_fields()['language'][4:], ('Menus', 'Language / Idioma'))
        self.assertEqual(pages['Controls'], (settings.LOCKON_KEY, settings.LOCKON_HOLD_KEY, 'lockoff_enabled', 'lockoff_button', 'lockoff_hold_seconds',
                                             'lockon_right_stick', 'lockon_right_stick_mode', 'lockon_cycle_order',
                                             'lockon_attacker_switch', 'lockon_after_ko'))
        # "(restart)" marks exactly the four launch options.
        restart = {key for key, row in settings.ui_fields().items() if '(restart' in row[5]}
        self.assertEqual(restart, set(features.RESTART_KEYS))
        # Every revival option still saves through the controller seam.
        choices = {key: settings.DEFAULTS[key] for key in settings.REVIVE_KEYS}
        choices['revive_ring_opacity'] = 0.5; choices[settings.CORPSE_SAFETY_KEY] = False
        got = settings.SettingsController(self.path).save('none', revival=choices)
        self.assertEqual({key: got[key] for key in choices}, choices)

    def test_battle_camera_zoom_is_the_last_cinematics_row(self):
        import feature_preferences as features
        key = 'battle_camera_distance_percent'
        self.assertEqual(dict(settings.GROUPS)['Cinematics'][-1], key)
        self.assertEqual(features.OPTIONS[key], (100, 'int', 100, 200, 'Cinematics', 'Battle camera zoom-out (%; 100 = normal)'))
        self.assertEqual(features.STEPS[key], 5)
        self.assertNotIn(key, features.UI_LIMITS)
        self.assertEqual(settings.DEFAULTS[key], 100)
        # A settings file saved before the option existed loads as the game's camera.
        self.path.write_text(json.dumps({'version': settings.VERSION, 'extra_character_intros': True}), encoding='utf-8')
        self.assertEqual(settings.load_settings(self.path)[key], 100)
        for value in (100, 105, 150, 200): self.assertEqual(settings.validate_settings({key: value})[key], value)
        for value in (99, 201, 205, 150.0, True):
            with self.subTest(value=value), self.assertRaises(ValueError): settings.validate_settings({key: value})

    def test_restore_defaults_prefers_valid_installed_defaults_and_never_changes_language(self):
        self.assertEqual(settings.default_settings(), self.code_defaults)
        installed = self.installed()
        self.defaults_path.write_text(json.dumps(dict(installed, language='es')), encoding='utf-8')
        restored = settings.default_settings()
        expected = settings.validate_settings(installed)
        self.assertEqual(restored, {k: expected[k] for k in settings.DEFAULTS if k not in ('language', 'version')})
        # Exactly the editable settings plus the per-character exceptions.
        self.assertEqual(set(restored), (set(settings.ui_fields()) - {'language'}) | {settings.NPC_OVERRIDES_KEY})
        self.assertEqual((restored['lockon_switch_button'], restored['fusion_duration_seconds']), ('l3', 80))
        self.assertEqual(restored[settings.NPC_OVERRIDES_KEY], {})
        for bad in (b'{', b'[]', b'{"revive_radius":"far"}', b'{"version":2,"version":2}', b'\xff'):
            self.defaults_path.write_bytes(bad)
            with self.subTest(bad=bad): self.assertEqual(settings.default_settings(), self.code_defaults)
        # Restoring commits only the keys that differ; language, overrides and
        # unrelated fields behave like any other changed-keys save.
        self.defaults_path.write_text(json.dumps(installed), encoding='utf-8')
        settings.save_settings({'language': 'es', 'revive_radius': 65.0, 'future': 1,
                                settings.NPC_OVERRIDES_KEY: {'3': True}}, self.path)
        controller = settings.SettingsController(self.path)
        restored = settings.default_settings()
        values = {key: restored.get(key, controller.settings[key]) for key in settings.ui_fields()}
        patch = settings.form_changes(controller.settings, values, restored[settings.NPC_OVERRIDES_KEY])
        self.assertNotIn('language', patch)
        self.assertEqual(patch['revive_radius'], 40.0); self.assertEqual(patch[settings.NPC_OVERRIDES_KEY], {})
        saved = controller.save_all(patch)
        self.assertEqual(saved, dict(settings.validate_settings(installed), language='es', future=1))

    def test_repair_replaces_an_unreadable_file_and_keeps_a_readable_language(self):
        samples = ((b'{"language":"es","revive_radius":"far","future":1}', 'es'),
                   (b'{"language":"es",', 'en'), (b'\xff\xfe', 'en'),
                   (b'{"language":"xx","version":9}', 'en'), (b'[1]', 'en'))
        names = ['mod-settings.broken.json'] + [f'mod-settings.broken-{n}.json' for n in range(2, len(samples) + 1)]
        for (raw, language), name in zip(samples, names):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError): settings.load_settings(self.path)
                self.assertEqual(settings.broken_copy_path(self.path).name, name)
                repaired = settings.repair_settings(self.path)
                self.assertEqual(repaired, dict(settings.DEFAULTS, language=language))
                self.assertEqual(settings.load_settings(self.path), repaired)
                # Every repair keeps its own copy; an earlier copy is never overwritten.
                self.assertEqual(self.path.with_name(name).read_bytes(), raw)
        self.assertEqual([self.path.with_name(name).read_bytes() for name in names], [raw for raw, _ in samples])
        # Atomic: a failed replace leaves the unreadable file as it was.
        self.path.write_bytes(b'{')
        with mock.patch.object(atomic_files, 'write_json', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError): settings.repair_settings(self.path)
        self.assertEqual(self.path.read_bytes(), b'{')
        self.assertEqual(self.path.with_name(names[0]).read_bytes(), samples[0][0])
        missing = Path(self.directory.name) / 'new' / 'mod-settings.json'
        missing.parent.mkdir()
        self.assertEqual(settings.repair_settings(missing)['language'], 'en')
        self.assertFalse(missing.with_name('mod-settings.broken.json').exists())

    def test_repair_keeps_a_copy_under_the_next_name_when_one_appears_meanwhile(self):
        self.path.write_bytes(b'{')
        self.path.with_name('mod-settings.broken.json').write_bytes(b'first')
        taken = self.path.with_name('mod-settings.broken-2.json')
        real = settings.broken_copy_path
        def racing(path=None):
            candidate = real(path)
            if not taken.exists(): taken.write_bytes(b'other')   # created after the check
            return candidate
        with mock.patch.object(settings, 'broken_copy_path', racing):
            settings.repair_settings(self.path)
        self.assertEqual([self.path.with_name(n).read_bytes() for n in
                          ('mod-settings.broken.json', 'mod-settings.broken-2.json', 'mod-settings.broken-3.json')],
                         [b'first', b'other', b'{'])

    def test_repair_uses_valid_installed_defaults_and_keeps_the_language_without_version_drift(self):
        installed = self.installed()
        self.defaults_path.write_text(json.dumps(dict(installed, version=settings.VERSION)), encoding='utf-8')
        self.path.write_bytes(b'{"language":"es","version":2,"revive_radius":"far","future":1}')
        repaired = settings.repair_settings(self.path)
        expected = dict(settings.validate_settings(installed), language='es')
        self.assertEqual(repaired, expected)
        self.assertEqual(repaired['version'], settings.VERSION)
        self.assertEqual(set(repaired), set(settings.DEFAULTS))
        self.assertEqual(settings.load_settings(self.path), expected)
        self.assertEqual((repaired['lockon_switch_button'], repaired['fusion_duration_seconds']), ('l3', 80))
        # An unusable installed file falls back to the code defaults.
        self.defaults_path.write_text('{"version":7}', encoding='utf-8')
        self.path.write_bytes(b'{')
        self.assertEqual(settings.repair_settings(self.path), settings.DEFAULTS)

    def test_expanded_maps_are_refused_when_the_build_check_cannot_run(self):
        import sys
        import localization
        import map_scale_launch
        refusal = localization.tr('Run Build expanded maps.cmd first.', 'es')
        for error in (KeyError('expanded'), ImportError('iso_compatibility'), OSError('locked'), ValueError('bad')):
            with self.subTest(error=error), mock.patch.object(map_scale_launch, 'expanded_ready', side_effect=error):
                self.assertEqual(settings.can_enable('expanded_maps', {'language': 'es'}), (False, refusal))
        with mock.patch.dict(sys.modules, {'map_scale_launch': None}):   # the module itself cannot be imported
            self.assertEqual(settings.can_enable('expanded_maps', 'en'), (False, 'Run Build expanded maps.cmd first.'))
        with mock.patch.object(map_scale_launch, 'expanded_ready', return_value=True):
            self.assertEqual(settings.can_enable('expanded_maps', 'en'), (True, ''))
        self.assertEqual(settings.can_enable('revive_enabled', 'en'), (True, ''))

    def test_character_exception_ids_come_from_one_adapter_constant(self):
        ids = settings.NPC_OVERRIDE_IDS
        self.assertEqual((ids.start, ids.step, ids.stop), (0, 1, {'BT3': 161, 'BT4': 250}[settings.ADAPTER]))
        value = settings.validate_settings({settings.NPC_OVERRIDES_KEY: {'0': True, str(ids[-1]): False}})
        self.assertEqual(value[settings.NPC_OVERRIDES_KEY], {'0': True, str(ids[-1]): False})
        for bad in ({str(ids.stop): True}, {'-1': True}, {'01': True}, {'5': 1}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, f'0..{ids[-1]} '):
                settings.validate_settings({settings.NPC_OVERRIDES_KEY: bad})

    def test_desktop_pages_fit_the_minimum_window_width_in_both_languages(self):
        import tkinter as tk
        from tkinter import ttk
        import localization
        try:
            # Idle work runs before destroy, so Tk reports no background error.
            probe = tk.Tk(); probe.withdraw(); probe.update_idletasks(); probe.destroy()
        except tk.TclError as error:
            self.skipTest(f'Tk is unavailable: {error}')
        seen = []

        def run(window, *_):
            # Never shown: measured on the withdrawn window, then destroyed.
            window.update_idletasks()
            widgets, stack = [], [window]
            while stack:
                widget = stack.pop(); widgets.append(widget); stack.extend(widget.winfo_children())
            listbox = next(w for w in widgets if isinstance(w, tk.Listbox))
            scrollbar = next(w for w in widgets if isinstance(w, ttk.Scrollbar))
            canvases = [w for w in widgets if isinstance(w, tk.Canvas)]
            available = (int(window.wm_minsize()[0]) - 2 * 16 - listbox.winfo_reqwidth() - 14
                         - scrollbar.winfo_reqwidth())
            for canvas in canvases: canvas.event_generate('<Configure>', width=available, height=300)
            window.update_idletasks()
            seen.append((available, max(c.winfo_children()[0].winfo_reqwidth() for c in canvases), len(canvases),
                         tuple(int(v) for v in window.wm_minsize())))
            window.destroy()

        refuse = mock.Mock(side_effect=AssertionError('unexpected dialog'))
        for language in ('en', 'es'):
            settings.save_settings({'language': language}, self.path)
            with mock.patch.object(localization, 'SETTINGS', self.path), \
                 mock.patch.object(tk.Tk, 'deiconify', lambda self: None), \
                 mock.patch.object(tk.Tk, 'mainloop', run), \
                 mock.patch('tkinter.messagebox.showerror', refuse), \
                 mock.patch('tkinter.messagebox.askyesno', refuse):
                localization.invalidate()
                try:
                    self.assertEqual(settings.show_ui(self.path), 0)
                finally:
                    localization.invalidate()
        self.assertEqual(len(seen), 2)
        for available, widest, pages, minimum in seen:
            self.assertEqual(pages, len(DESKTOP_PAGES))
            # The help note wraps to the page; rows and controls are never clipped.
            self.assertLessEqual(widest, available)
            # Windows keeps its fixed minimum; wider Linux Tk fonts widen it instead of clipping a row.
            if os.name == 'nt':self.assertEqual(minimum, (860, 520))
            else:self.assertGreaterEqual(minimum, (860, 520))

    def test_desktop_drop_downs_fit_and_the_wheel_scrolls_only_the_settings_window(self):
        import tkinter as tk
        from tkinter import font as tkfont, ttk
        from types import SimpleNamespace
        import localization
        try:
            probe = tk.Tk(); probe.withdraw(); probe.update_idletasks(); probe.destroy()
        except tk.TclError as error:
            self.skipTest(f'Tk is unavailable: {error}')
        wheels, seen = [], {}
        real_wheel = settings.PageWheel

        def capture(*args):
            wheels.append(real_wheel(*args)); return wheels[-1]

        def run(window, *_):
            widgets, stack = [], [window]
            while stack:
                widget = stack.pop(); widgets.append(widget); stack.extend(widget.winfo_children())
            boxes = [w for w in widgets if isinstance(w, ttk.Combobox)]
            seen['widths'] = {int(str(box.cget('width'))) for box in boxes}
            # ttk sizes an entry's text area as width x the width of '0' in its font.
            text_font = tkfont.nametofont(str(boxes[0].cget('font')) or 'TkTextFont', root=window)
            room = int(str(boxes[0].cget('width'))) * text_font.measure('0')
            seen['clipped'] = [label for box in boxes for label in box.cget('values') if text_font.measure(label) > room]
            seen['labels'] = {label for box in boxes for label in box.cget('values')}
            wheel = wheels[0]
            page = next(w for w in widgets if isinstance(w, ttk.Label) and str(w.cget('text')) == localization.tr('Menus'))
            spin = next(w for w in widgets if isinstance(w, ttk.Spinbox))
            box = boxes[0]; spun, chosen = spin.get(), box.get()
            dialog = tk.Toplevel(window); dialog.withdraw(); other = ttk.Label(dialog)   # never shown
            scrolled = []
            with mock.patch.object(tk.Canvas, 'yview_scroll', lambda canvas, n, what: scrolled.append((n, what))):
                event = lambda widget, delta: wheel(SimpleNamespace(widget=widget, delta=delta))
                for _ in range(2): event(page, -40)
                seen['partial'] = list(scrolled)
                event(page, -40); seen['touchpad'] = list(scrolled)       # three thirds make one notch
                scrolled.clear(); event(page, 240); seen['notches'] = list(scrolled)
                scrolled.clear()
                for widget in (other, dialog, '.!combobox.popdown.f.l', spin, box, next(
                        w for w in widgets if isinstance(w, tk.Listbox))):
                    event(widget, -360)
                seen['ignored'] = list(scrolled)
                page.event_generate('<MouseWheel>', delta=-120); seen['bound'] = list(scrolled)
                if settings.x11_wheel_buttons(window):   # Tk 8.6 on X11: the wheel arrives as buttons 4/5
                    scrolled.clear()
                    for button in (5, 4, 4):
                        page.event_generate(f'<ButtonPress-{button}>'); page.event_generate(f'<ButtonRelease-{button}>')
                    seen['buttons'] = list(scrolled)
                else:
                    seen['buttons'] = [(1, 'units'), (-1, 'units'), (-1, 'units')]
            seen['values'] = (spin.get() == spun, box.get() == chosen)
            window.update_idletasks(); window.destroy()

        refuse = mock.Mock(side_effect=AssertionError('unexpected dialog'))
        for language in ('en', 'es'):
            wheels.clear(); seen.clear()
            settings.save_settings({'language': language}, self.path)
            with mock.patch.object(localization, 'SETTINGS', self.path), \
                 mock.patch.object(settings, 'PageWheel', side_effect=capture), \
                 mock.patch.object(tk.Tk, 'deiconify', lambda self: None), \
                 mock.patch.object(tk.Tk, 'mainloop', run), \
                 mock.patch('tkinter.messagebox.showerror', refuse), \
                 mock.patch('tkinter.messagebox.askyesno', refuse):
                localization.invalidate()
                try:
                    self.assertEqual(settings.show_ui(self.path), 0)
                finally:
                    localization.invalidate()
            with self.subTest(language=language):
                self.assertEqual(seen['widths'], {28})
                self.assertEqual(seen['clipped'], [])
                if language == 'es': self.assertIn('Jugador arriba, objetivo abajo', seen['labels'])
                self.assertEqual((seen['partial'], seen['touchpad'], seen['notches']), ([], [(1, 'units')], [(-2, 'units')]))
                self.assertEqual(seen['ignored'], [], 'other windows, drop-down lists and value widgets')
                self.assertEqual(seen['bound'], [(1, 'units')], 'the handler is bound to the wheel')
                self.assertEqual(seen['buttons'], [(1, 'units'), (-1, 'units'), (-1, 'units')], 'X11 wheel buttons')
                self.assertEqual(seen['values'], (True, True), 'the wheel handler never changes a value')

    def test_wheel_buttons_are_bound_only_for_x11_tk_before_8_7(self):
        import tkinter
        from types import SimpleNamespace
        cases = (('win32', 8.6, False), ('aqua', 8.6, False), ('x11', 8.6, True), ('x11', 8.7, False), ('x11', 9.0, False))
        for system, version, buttons in cases:
            bound = {}; handled = []; handler = handled.append
            window = SimpleNamespace(tk=SimpleNamespace(call=lambda *args, s=system: s),
                                     bind_all=lambda sequence, function: bound.__setitem__(sequence, function))
            with self.subTest(system=system, version=version), mock.patch.object(tkinter, 'TkVersion', version):
                settings.bind_wheel(window, handler)
                self.assertEqual(sorted(bound), sorted(['<MouseWheel>'] + (['<Button-4>', '<Button-5>'] if buttons else [])))
                self.assertIs(bound['<MouseWheel>'], handler)
                if buttons:
                    bound['<Button-4>'](SimpleNamespace(widget='w4', delta=0))
                    bound['<Button-5>'](SimpleNamespace(widget='w5', delta=0))
                    self.assertEqual([(e.widget, e.delta) for e in handled], [('w4', 120), ('w5', -120)])
        broken = SimpleNamespace(tk=SimpleNamespace(call=mock.Mock(side_effect=tkinter.TclError('no display'))))
        self.assertFalse(settings.x11_wheel_buttons(broken))

    def test_dialog_grab_retries_until_the_window_is_viewable_and_stays_bounded(self):
        import tkinter
        import input_binding
        dialog = mock.Mock()
        dialog.grab_set.side_effect = [tkinter.TclError('grab failed: window not viewable')] * 2 + [None]
        self.assertTrue(input_binding.grab_dialog(dialog))
        self.assertEqual((dialog.grab_set.call_count, dialog.update.call_count), (3, 2))
        dialog = mock.Mock(); dialog.grab_set.side_effect = tkinter.TclError('grab failed: window not viewable')
        self.assertFalse(input_binding.grab_dialog(dialog, attempts=5))   # never waits forever, never raises
        self.assertEqual(dialog.grab_set.call_count, 5); dialog.wait_visibility.assert_not_called()
        dialog = mock.Mock(); self.assertTrue(input_binding.grab_dialog(dialog))   # Windows: first attempt
        self.assertEqual((dialog.grab_set.call_count, dialog.update.call_count, dialog.after.call_count), (1, 0, 0))

    def test_window_title_names_the_adapter_through_one_constant(self):
        import inspect
        import localization
        self.assertEqual(localization.tr(settings.WINDOW_TITLE, 'en', adapter=settings.ADAPTER),
                         f'{settings.ADAPTER} mod settings')
        self.assertEqual(localization.tr(settings.WINDOW_TITLE, 'es', adapter=settings.ADAPTER),
                         f'Ajustes del mod {settings.ADAPTER}')
        self.assertNotIn('BT3', inspect.getsource(settings.show_ui))
        self.assertNotIn('BT4', inspect.getsource(settings.show_ui))

    def test_desktop_window_builds_every_page_steps_refuses_restores_and_saves(self):
        import tkinter as tk
        from tkinter import ttk
        import localization
        import map_scale_launch
        try:
            probe = tk.Tk(); probe.withdraw(); probe.update_idletasks(); probe.destroy()
        except tk.TclError as error:
            self.skipTest(f'Tk is unavailable: {error}')
        installed = self.installed()
        self.defaults_path.write_text(json.dumps(installed), encoding='utf-8')
        settings.save_settings({'language': 'es', 'revive_radius': 65.0, 'lockon_switch_button': 'cross',
                                'future': 1}, self.path)
        es = lambda text, **values: localization.tr(text, 'es', **values)
        seen = {}

        def run(window, *_):
            widgets, stack = [], [window]
            while stack:
                widget = stack.pop(); widgets.append(widget); stack.extend(widget.winfo_children())
            seen['title'] = window.title()
            seen['pages'] = [w.get(0, 'end') for w in widgets if isinstance(w, tk.Listbox)][0]
            texts = [str(w.cget('text')) for w in widgets if isinstance(w, (ttk.Label, ttk.Checkbutton, ttk.Button))]
            seen['texts'] = texts
            buttons = {str(w.cget('text')): w for w in widgets if isinstance(w, ttk.Button)}
            checks = {str(w.cget('text')): w for w in widgets if isinstance(w, ttk.Checkbutton)}
            spins = [w for w in widgets if isinstance(w, ttk.Spinbox)]
            seen['spins'] = len(spins)
            with mock.patch.object(map_scale_launch, 'installed', return_value=None), \
                 mock.patch('tkinter.messagebox.showwarning') as warn:
                maps = checks[es('Experimental 2x maps (restart)')]
                maps.invoke()
                seen['maps'] = window.getvar(str(maps.cget('variable')))
                seen['warning'] = warn.call_args.args[1] if warn.call_args else None
                buttons[es('Restore defaults')].invoke()
            fusion = [w for w in spins if w.get() == '80']
            self.assertEqual(len(fusion), 1)
            # Off the grid, the arrows go to the next stop (Tk's own increment would give 88).
            fusion[0].set('83')
            fusion[0].event_generate('<<Increment>>'); seen['up'] = fusion[0].get()
            fusion[0].event_generate('<<Decrement>>'); fusion[0].event_generate('<<Decrement>>')
            seen['down'] = fusion[0].get()
            # Page Up/Down (ten stops) need keyboard focus; check they are bound.
            seen['big'] = all(w.bind('<Prior>') and w.bind('<Next>') for w in spins)
            window.update_idletasks(); buttons[es('Save')].invoke()

        # No dialog may ever block the test run: an error box fails it instead.
        refuse = mock.Mock(side_effect=AssertionError('unexpected dialog'))
        with mock.patch.object(localization, 'SETTINGS', self.path), \
             mock.patch.object(tk.Tk, 'deiconify', lambda self: None), \
             mock.patch.object(tk.Tk, 'mainloop', run), \
             mock.patch('tkinter.messagebox.showerror', refuse), \
             mock.patch('tkinter.messagebox.askyesno', refuse):
            localization.invalidate()
            try:
                self.assertEqual(settings.show_ui(self.path), 0)
            finally:
                localization.invalidate()
        self.assertEqual(seen['title'], es(settings.WINDOW_TITLE, adapter=settings.ADAPTER))
        self.assertEqual(tuple(page.strip() for page in seen['pages']), tuple(es(page) for page in DESKTOP_PAGES))
        for group in PAGES:
            self.assertIn(es(group), seen['texts']); self.assertIn(settings.help_note(group, 'es'), seen['texts'])
        self.assertIn(es('Per-character transformation exceptions…'), seen['texts'])
        self.assertEqual(seen['spins'], sum(row[1] in ('int', 'float') for row in settings.ui_fields().values()))
        self.assertEqual((seen['maps'], seen['warning']), (0, 'Ejecuta primero Build expanded maps.cmd.'))
        self.assertEqual((seen['up'], seen['down'], seen['big']), ('85', '75', True))
        saved = settings.load_settings(self.path)
        expected = dict(settings.validate_settings(installed), language='es', future=1, fusion_duration_seconds=75)
        self.assertEqual(saved, expected)


if __name__ == '__main__':
    unittest.main()
