"""Read-only native-disc HUD previews and settings navigation."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ingame_settings as menu
import localization
import mod_settings
import settings_preview as preview
from native_map import elf_path


class SettingsPreviewTests(unittest.TestCase):
    def test_installed_game_directory_keeps_its_adapter_tag_meter_position(self):
        installed = Path('installed')/'game'
        with patch.object(preview, 'ROOT', installed), patch.object(mod_settings, 'ROOT', installed):
            expected = (111, 66, 75) if mod_settings.ADAPTER == 'BT4' else (123, 38, 47)
            self.assertEqual(preview.tag_meter_placement((0, 512, 0, 448), self.settings()), expected)

    def test_preview_needs_no_native_gameplay_import_or_executable(self):
        blocked = dict.fromkeys(('tag_rush_hud', 'viewport_hud_art', 'coop_controller'))
        with patch.dict('sys.modules', blocked):
            for language in ('en', 'es'):
                for players in (1, 2, 3, 4):
                    for group in preview.GROUPS:
                        with self.subTest(language=language, players=players, group=group):
                            image = preview.render(dict(self.settings(), language=language), players=players,
                                                   group=group, art=None, size=(512, 288))
                            self.assertEqual(image.size, (512, 288))

    @unittest.skipUnless(elf_path(mod_settings.ROOT).is_file(), 'the disc executable is required')
    def test_tag_meter_geometry_matches_native_for_every_layout_scale_and_view(self):
        import itertools
        import struct
        import tag_rush_hud as tag
        import viewport_hud_art as art
        self.assertEqual((preview.TAG_METER_WIDTH, preview.TAG_METER_HEIGHT), (tag.WIDTH, tag.HEIGHT))
        for style, layout, coop_layout, wide, scale in itertools.product(
                ('native', 'compact'), ('top', 'top_bottom'), ('players', 'targets'), (False, True), range(80, 141)):
            settings = dict(self.settings(), split_hud_style=style, split_hud_layout=layout,
                            coop_hud_layout=coop_layout, widescreen_patch=wide, split_hud_scale_percent=scale)
            native_settings = struct.unpack('<8I', art.settings_data(settings))
            for players, coop in itertools.product((1, 2, 3, 4), (False, True)):
                for seat, (left, top, right, bottom) in enumerate(preview.viewports(players)):
                    for subject in ((0, 1) if players == 1 else (seat,)):
                        view = (left, right, top, bottom)
                        where = dict(split=seat if players > 1 else None, subject=subject, coop=coop, views=players)
                        self.assertEqual(preview.tag_meter_placement(view, settings, **where),
                                         tag.placement(view, settings=native_settings, wide=preview.aspect_wide(settings),
                                                       **where),
                                         (mod_settings.ADAPTER, style, layout, coop_layout, wide, scale, players, seat, subject, coop))

    def settings(self):
        s=mod_settings.validate_settings(dict(mod_settings.DEFAULTS))
        s.update(show_kill_score=True,show_kill_feed=True,revive_enabled=True,fusion_duration_enabled=True,
                 tag_team_rush_enabled=True,widescreen_patch=True,coop_hud_layout='targets')
        return s

    def test_training_meter_stays_one_setting_and_moves_to_training(self):
        fields=mod_settings.ui_fields()
        self.assertEqual(fields['tag_team_rush_training_full'][4],'Training')
        keys=[key for _,group in mod_settings.GROUPS for key in group]
        self.assertEqual(keys.count('tag_team_rush_training_full'),1)
        self.assertNotIn('tag_team_rush_training_full',dict(mod_settings.GROUPS)['Tag-team rush'])
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'settings.json'
            mod_settings.save_settings({'tag_team_rush_training_full':True},path)
            before=path.read_bytes()
            preview.render(mod_settings.load_settings(path),players=3,group='Training',size=(512,288))
            self.assertEqual(path.read_bytes(),before)
            self.assertTrue(mod_settings.load_settings(path)['tag_team_rush_training_full'])

    def test_every_preview_label_has_a_spanish_translation(self):
        for text in (*preview.TEXTS,'Visual preview…'):
            self.assertIn(text,localization.ES,text)

    def test_preview_changes_are_visible_and_do_not_edit_preferences(self):
        s=self.settings();before=copy.deepcopy(s)
        normal=preview.render(s,players=4,group='Fusion',size=(512,288)).tobytes()
        for key in ('show_native_hud','show_friendly_healthbars','show_enemy_healthbars','show_kill_feed',
                    'show_kill_score','show_fusion_control_owner','show_fusion_control_countdown','show_fusion_timer'):
            changed=dict(s,**{key:False})
            with self.subTest(key=key):
                self.assertNotEqual(preview.render(changed,players=4,group='Fusion',size=(512,288)).tobytes(),normal)
        self.assertEqual(s,before)
        self.assertEqual(preview.viewports(3)[2],(128,225,383,448))

    def test_single_player_has_no_friendly_overhead_preview(self):
        s=self.settings()
        a=preview.render(s,players=1,size=(512,288))
        b=preview.render(dict(s,show_friendly_healthbars=False),players=1,size=(512,288))
        self.assertEqual(a.tobytes(),b.tobytes())
        art=preview.disc_art()
        a=preview.render(s,players=1,art=art,size=(512,288))
        b=preview.render(dict(s,split_hud_scale_percent=80,split_hud_layout='top_bottom',
                             show_hud_portraits=False,split_hud_style='compact'),players=1,art=art,size=(512,288))
        self.assertEqual(a.tobytes(),b.tobytes(),'split-screen choices must not resize the normal one-player HUD')

    def test_unlock_policy_example_and_ring_opacity_are_visible(self):
        s=self.settings()
        a=preview.render(dict(s,lockoff_target_hud='show'),phase='Locked off',size=(512,288))
        b=preview.render(dict(s,lockoff_target_hud='hide'),phase='Locked off',size=(512,288))
        self.assertNotEqual(a.tobytes(),b.tobytes())
        a=preview.render(dict(s,revive_ring_opacity=0),group='Revival',size=(512,288))
        b=preview.render(dict(s,revive_ring_opacity=1),group='Revival',size=(512,288))
        self.assertNotEqual(a.tobytes(),b.tobytes())

    def test_local_selected_disc_art_and_presentation_options(self):
        art=preview.disc_art()
        if art is None:self.skipTest('The selected game ISO is unavailable')
        s=self.settings();a=preview.native_panel(art,s)
        self.assertEqual(a.size,(512,128))
        self.assertNotEqual(a.tobytes(),preview.native_panel(art,dict(s,show_hud_portraits=False)).tobytes())
        self.assertNotEqual(a.tobytes(),preview.native_panel(art,s,'Taking damage').tobytes())
        self.assertNotEqual(a.tobytes(),preview.native_panel(art,s,'Charging to Sparking').tobytes())
        x=preview.render(s,players=2,art=art,size=(512,288))
        for settings in (dict(s,split_hud_layout='top_bottom'),dict(s,split_hud_scale_percent=80),
                         dict(s,coop_hud_layout='players'),dict(s,split_hud_style='compact')):
            y=preview.render(settings,players=2,art=art,coop=True,size=(512,288))
            self.assertNotEqual(x.tobytes(),y.tobytes())

    def test_ingame_preview_controls_stage_edits_without_saving_and_stay_bounded(self):
        c=menu.Controller();c.saved=self.settings();c.values=copy.deepcopy(c.saved)
        c.group=c.groups.index('Split-screen HUD');c.view='page';c.row=0
        art=preview.disc_art()
        import threading
        done=threading.Event();done.set();job={'art':art,'done':done}
        with patch.object(preview,'art_job',return_value=job),patch.object(mod_settings,'save_settings') as save:
            c.press(menu.SELECT);self.assertEqual(c.view,'preview')
            c.press(menu.RIGHT);self.assertEqual(c.values['split_hud_style'],'compact')
            self.assertEqual(c.saved['split_hud_style'],'native');save.assert_not_called()
            c.press(menu.LEFT);c.preview_art=art;c.preview_job=None
            for language in ('en','es'):
                c.values['language']=language
                for group in preview.GROUPS:
                    c.group=c.groups.index(group);c.row=0
                    for players in (1,2,3,4):
                        c.preview_players=players;c.preview_phase=3
                        with self.subTest(language=language,group=group,players=players):
                            image=c.picture()
                            self.assertFalse(c.trimmed)
                            self.assertLessEqual(len(menu.rectangles(image)),menu.BUDGET)
            c.press(menu.SELECT);self.assertEqual(c.view,'page');save.assert_not_called()

    def test_preview_respects_other_menu_switch_buttons(self):
        c=menu.Controller();c.saved=self.settings();c.values=copy.deepcopy(c.saved);c.view='page'
        c.group=c.groups.index('HUD');self.assertEqual(c.back_button(),0)
        c.group=c.groups.index('Controls');self.assertEqual(c.back_button(),menu.SELECT)


if __name__=='__main__':unittest.main()
