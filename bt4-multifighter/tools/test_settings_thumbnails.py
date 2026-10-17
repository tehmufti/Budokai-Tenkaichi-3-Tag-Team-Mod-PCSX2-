"""The picture beside each visual option of the desktop Mod settings window (settings_thumbnails)."""
import builtins
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import feature_preferences
import localization
import mod_settings
import settings_preview
import settings_thumbnails as thumbs

# Every option of these pages draws something on screen, so each one has a picture.
PICTURED_PAGES = ('HUD', 'Split-screen HUD')


def everything_on():
    """Settings with every pictured element visible (so each option's own change shows)."""
    s = mod_settings.validate_settings(dict(mod_settings.DEFAULTS))
    s.update(show_friendly_healthbars=True, show_enemy_healthbars=True, show_native_hud=True, show_kill_feed=True,
             show_kill_score=True, lockoff_target_hud='show', lockon_target_marker=True, lockon_target_style='both',
             lockon_threat_marks='marks', split_hud_style='native', revive_enabled=True, show_revive_ring=True,
             fusion_enabled=True, coop_fusion_controls='swap_20s', fusion_duration_enabled=True, show_fusion_timer=True,
             beam_assist_enabled=True, spectator_takeover_enabled=True, tag_team_rush_enabled=True,
             widescreen_patch=True)
    return s


def colours(card):
    return len(card.convert('RGB').getcolors(1 << 20) or ())


def other_values(key, value):
    """Values of `key` other than `value`: every other choice, the flipped switch, the range ends."""
    field = mod_settings.ui_fields()[key]
    kind = field[1]
    if kind == 'bool':
        return [not value]
    if kind == 'choice':
        return [v for v in field[2] if v != value]
    low, high = feature_preferences.ui_range(key)
    return [v for v in (low, high) if v != value]


class SettingsThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.art = thumbs.load_art()

    def arts(self):
        return (self.art, None) if self.art is not None else (None,)

    def test_tag_attack_meter_card_shows_the_meter_or_its_hidden_state(self):
        s = everything_on()
        for art in self.arts():
            with self.subTest(art=art is not None):
                shown = thumbs.render_card('tag_team_rush_show_meter', s, art)
                self.assertIsNone(shown.info['hidden'])
                off = thumbs.render_card('tag_team_rush_show_meter', dict(s, tag_team_rush_show_meter=False), art)
                self.assertEqual(off.info['hidden'], 'Hidden')
                rush = thumbs.render_card('tag_team_rush_show_meter', dict(s, tag_team_rush_enabled=False), art)
                self.assertEqual(rush.info['hidden'], 'Tag-team rush is off')
                self.assertNotEqual(shown.tobytes(), off.tobytes())
        self.assertIn('tag_team_rush_show_meter', dict(mod_settings.GROUPS)['HUD'])
        self.assertEqual(localization.tr('Tag attack meter', 'es'), 'Medidor de ataque tag')

    def test_every_visual_option_has_a_picture_of_the_card_size(self):
        fields = mod_settings.ui_fields()
        for page in PICTURED_PAGES:
            for key in dict(mod_settings.GROUPS)[page]:
                self.assertTrue(thumbs.available(key), key)
        for key in ('tag_team_rush_enabled', 'tag_team_rush_training_full', 'show_fusion_control_owner',
                    'show_fusion_control_countdown', 'show_fusion_timer', 'beam_assist_enabled',
                    'beam_assist_multiplier_percent', 'revive_enabled', 'show_revive_ring', 'show_takeover_hints',
                    'show_takeover_confirmation', 'battle_camera_distance_percent'):
            self.assertTrue(thumbs.available(key), key)
        s = everything_on()
        for key, spec in thumbs.SPECS.items():
            self.assertIn(key, fields, 'a picture for an option the window does not have')
            self.assertIn(key, spec.deps, 'a picture must follow its own option')
            for dep in spec.deps:
                self.assertTrue(dep in fields or dep == 'language', (key, dep))
            for art in self.arts():
                for language in localization.LANGUAGES:
                    with self.subTest(key=key, art=art is not None, language=language):
                        card = thumbs.render_card(key, dict(s, language=language), art, thumbs.CARD, language)
                        self.assertEqual(card.size, thumbs.CARD)
                        self.assertEqual(card.mode, 'RGBA')
                        self.assertIsNone(card.info['hidden'])
                        self.assertEqual(card.info['example'], art is None)
                        # A drawn picture, not an empty card: the element adds detail over the background patch.
                        self.assertGreater(colours(card), 400)

    def test_changing_an_option_changes_its_picture(self):
        s = everything_on()
        for art in self.arts():
            for key in thumbs.KEYS:
                before = thumbs.render_card(key, s, art).tobytes()
                for value in other_values(key, s[key]):
                    with self.subTest(key=key, value=value, art=art is not None):
                        after = thumbs.render_card(key, dict(s, **{key: value}), art).tobytes()
                        self.assertNotEqual(before, after)
        # Choices draw distinct pictures; a related option changes a picture too (the look of the indicator).
        for key in ('lockon_target_style', 'lockon_target_look', 'lockon_threat_marks', 'lockoff_target_hud',
                    'split_hud_style', 'split_hud_layout', 'split_hud_filter', 'coop_hud_layout'):
            pictures = {thumbs.render_card(key, dict(s, **{key: v}), self.art).tobytes()
                        for v in mod_settings.ui_fields()[key][2]}
            self.assertEqual(len(pictures), len(mod_settings.ui_fields()[key][2]), key)
        a = thumbs.render_card('lockon_target_style', dict(s, lockon_target_look='native'), self.art).tobytes()
        b = thumbs.render_card('lockon_target_style', dict(s, lockon_target_look='classic'), self.art).tobytes()
        self.assertNotEqual(a, b)

    def test_still_pictures_name_what_a_still_cannot_show(self):
        s = everything_on()
        card = thumbs.render_card('hud_damage_trail_seconds', dict(s, hud_damage_trail_seconds=0), self.art)
        self.assertTrue(card.info['hidden'] is None)
        a = thumbs.render_card('split_hud_scale_percent', dict(s, widescreen_patch=False, split_hud_scale_percent=100),
                               self.art).tobytes()
        b = thumbs.render_card('split_hud_scale_percent', dict(s, widescreen_patch=False, split_hud_scale_percent=140),
                               self.art).tobytes()
        self.assertNotEqual(a, b, 'a 4:3 size above 100% says it only grows in 16:9')

    def test_options_drawing_the_same_element_share_one_picture(self):
        pages = dict(mod_settings.GROUPS)
        self.assertIn(('lockon_target_marker', 'lockon_target_style', 'lockon_target_look'), thumbs.SHARED)
        s = everything_on()
        for members in thumbs.SHARED:
            page = next(keys for keys in pages.values() if members[0] in keys)
            start = page.index(members[0])
            self.assertEqual(tuple(page[start:start+len(members)]), members, 'shared rows are adjacent')
            for key in members:
                self.assertEqual(thumbs.shared(key), members)
            for values in (s, dict(s, lockon_target_style='ring', lockon_target_look='classic', show_revive_ring=False,
                                   fusion_duration_seconds=12)):
                pictures = {thumbs.render_card(key, values, self.art).tobytes() for key in members}
                self.assertEqual(len(pictures), 1, members)
        # One target picture shows all three settings, and the hidden state when marking is off.
        card = lambda **v: thumbs.render_card('lockon_target_style', dict(s, **v), self.art)
        self.assertEqual(len({card(lockon_target_style=a, lockon_target_look=b).tobytes()
                              for a in ('arrow', 'ring', 'both') for b in ('native', 'classic')}), 6)
        self.assertEqual(card(lockon_target_marker=False).info['hidden'], 'Hidden')
        # Any other adjacent pair of pictured options draws different pictures.
        for keys in pages.values():
            for a, b in zip(keys, keys[1:]):
                if thumbs.available(a) and thumbs.available(b) and thumbs.shared(a) != thumbs.shared(b):
                    self.assertNotEqual(thumbs.render_card(a, s, self.art).tobytes(),
                                        thumbs.render_card(b, s, self.art).tobytes(), (a, b))

    def test_spanish_numbers_use_a_decimal_comma(self):
        es, en = {'language': 'es'}, {'language': 'en'}
        self.assertEqual(thumbs.decimal('0.5', es), '0,5')
        self.assertEqual(thumbs.value_text(0.5, es), '0,5')
        self.assertEqual(thumbs.value_text(0.5, en), '0.5')
        shown = []
        with patch.object(thumbs, '_badge', side_effect=lambda card, text, *a, **k: shown.append(text)):
            thumbs.render_card('hud_damage_trail_seconds', everything_on(), self.art, thumbs.CARD, 'es')
            thumbs.render_card('hud_damage_trail_seconds', everything_on(), self.art, thumbs.CARD, 'en')
        self.assertIn('Se desvanece en 0,5 s', shown)
        self.assertIn('Fades after 0.5 s', shown)

    def test_off_shows_a_hidden_state_not_a_blank(self):
        s = everything_on()
        for key, value in (('show_kill_feed', False), ('lockon_threat_marks', 'hide'), ('lockon_target_marker', False),
                           ('show_native_hud', False), ('revive_enabled', False), ('show_takeover_hints', False)):
            card = thumbs.render_card(key, dict(s, **{key: value}), self.art)
            self.assertTrue(card.info['hidden'], key)
            self.assertGreater(colours(card), 400, key)
        # A dependent option says why its element is not drawn.
        card = thumbs.render_card('show_hud_portraits', dict(s, split_hud_style='compact'), self.art)
        self.assertEqual(card.info['hidden'], 'Native style only')
        self.assertIn('Native style only', localization.ES)

    def test_without_a_readable_disc_every_picture_is_a_labelled_example(self):
        with tempfile.TemporaryDirectory() as temp:
            junk = Path(temp)/'damaged.iso'
            junk.write_bytes(b'not a disc'*1000)
            for path in (Path(temp)/'missing.iso', junk):
                with self.subTest(path=path.name), patch.object(settings_preview, 'selected_iso', return_value=path):
                    settings_preview._disc_art.cache_clear()
                    self.assertIsNone(thumbs.load_art())
        settings_preview._disc_art.cache_clear()
        s = everything_on()
        for key in thumbs.KEYS:
            card = thumbs.render_card(key, s, None, thumbs.CARD, 'es')
            self.assertTrue(card.info['example'], key)
        self.assertEqual(localization.tr('Example', {'language': 'es'}), 'Ejemplo')

    def test_pictures_write_nothing_to_disk(self):
        from PIL import Image
        real_open = builtins.open

        def guarded(file, mode='r', *a, **k):
            if any(flag in mode for flag in 'wax+'):
                raise AssertionError(f'settings pictures wrote {file}')
            return real_open(file, mode, *a, **k)
        # The tree and its tools folder (the shared temp folder is left out: other programs write there).
        roots = (Path(mod_settings.ROOT), Path(thumbs.__file__).parent)
        before = {root: set(os.listdir(root)) for root in roots}
        s = everything_on()
        with patch.object(Image.Image, 'save', side_effect=AssertionError('a picture was saved')), \
                patch.object(builtins, 'open', guarded):
            settings_preview._disc_art.cache_clear(); thumbs._disc_extras.cache_clear()
            art = thumbs.load_art()
            for key in thumbs.KEYS:
                thumbs.render_card(key, s, art, thumbs.CARD)
                thumbs.render_card(key, s, None, (thumbs.CARD[0]*3, thumbs.CARD[1]*3))
        for root in roots:
            self.assertEqual(set(os.listdir(root)), before[root], root)
        source = Path(thumbs.__file__).read_text(encoding='utf-8')
        for call in ('.save(', 'write_bytes', 'write_text', "open("):
            self.assertNotIn(call, source, 'the pictures keep no disk cache')

    def test_every_interface_text_has_a_spanish_translation(self):
        for text in thumbs.TEXTS:
            self.assertIn(text, localization.ES, text)


class MiniWindow:
    """The window's page layout (label, control, picture) for Tk checks."""
    def __init__(self, test, settings, keys, load=None):
        import tkinter as tk
        from tkinter import ttk
        try:
            self.window = tk.Tk()
        except tk.TclError as error:
            test.skipTest(str(error))
        test.addCleanup(self.close)
        self.window.geometry('1040x700+40+40')
        self.page = ttk.Frame(self.window, padding=8); self.page.pack(fill='both', expand=True)
        self.page.columnconfigure(0, weight=1)
        self.values = copy.deepcopy(settings)
        self.thumbs = thumbs.Thumbnails(self.window, lambda: self.values, 'en', **({'load': load} if load else {}))
        self.page.columnconfigure(2, minsize=self.thumbs.size[0]+16)
        self.rows = {}
        for row, key in enumerate(keys):
            ttk.Label(self.page, text=key).grid(row=row, column=0, sticky='w')
            ttk.Combobox(self.page, width=28).grid(row=row, column=1, sticky='w')
            self.rows[key] = self.thumbs.attach(self.page, row, key, heading=key)

    def set(self, **values):
        self.values.update(values)
        self.thumbs.changed(*values)

    def pump(self, timeout=60):
        end = time.time()+timeout
        t = self.thumbs
        while time.time() < end:
            self.window.update()
            if t.art_ready and t.jobs.empty() and t.results.empty() and all(v is None for v in t.wanted.values()):
                self.window.update()
                return True
            time.sleep(.01)
        return False

    def close(self):
        try:
            self.window.destroy()
        except Exception:
            pass


class ThumbnailWindowTests(unittest.TestCase):
    def test_closing_during_disc_loading_releases_pictures_on_the_tk_thread(self):
        import threading
        from PIL import ImageTk
        started, release = threading.Event(), threading.Event()
        main_thread = threading.get_ident()
        finalized = []
        real_del = ImageTk.PhotoImage.__del__

        def load():
            started.set()
            release.wait(10)
            return None

        def finalize(photo):
            finalized.append(threading.get_ident())
            real_del(photo)

        with patch.object(ImageTk.PhotoImage, '__del__', finalize):
            w = MiniWindow(self, everything_on(), ('show_kill_feed',), load=load)
            worker = w.thumbs.worker
            try:
                self.assertTrue(started.wait(2))
                w.window.update()
                w.close()
                self.assertTrue(worker.is_alive(), 'closing must not wait for the disc reader')
                self.assertTrue(finalized, 'closing must release the Tk pictures before the worker exits')
                self.assertEqual(set(finalized), {main_thread})
            finally:
                release.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_a_picture_renders_off_the_tk_thread_and_follows_its_option(self):
        keys = ('lockon_target_style', 'lockon_target_look', 'show_kill_feed', 'split_hud_layout')
        w = MiniWindow(self, everything_on(), keys)
        self.assertTrue(w.pump())
        self.assertEqual(w.thumbs.worker.name, 'settings-thumbnails')
        first = {k: str(w.rows[k].cget('image')) for k in keys}
        self.assertTrue(all(first.values()))
        w.set(lockon_target_look='classic')
        self.assertTrue(w.pump())
        after = {k: str(w.rows[k].cget('image')) for k in keys}
        # The look changes both marker pictures, never the unrelated ones.
        self.assertNotEqual(after['lockon_target_style'], first['lockon_target_style'])
        self.assertNotEqual(after['lockon_target_look'], first['lockon_target_look'])
        self.assertEqual(after['show_kill_feed'], first['show_kill_feed'])
        # A value seen before comes from the in-memory cache, without another render.
        renders = []
        real = thumbs.render_card
        with patch.object(thumbs, 'render_card', side_effect=lambda *a, **k: renders.append(a[0]) or real(*a, **k)):
            w.set(lockon_target_look='native')
            self.assertTrue(w.pump())
        self.assertEqual(renders, [])

    def test_click_enlarges_and_escape_closes(self):
        w = MiniWindow(self, everything_on(), ('lockon_target_style',))
        self.assertTrue(w.pump())
        top = w.thumbs.enlarge('lockon_target_style')
        self.assertTrue(w.pump())
        label = w.thumbs.popup['label']
        self.assertEqual((label.winfo_reqwidth(), label.winfo_reqheight()), w.thumbs.large_size())
        self.assertIn(localization.value_label('both'), w.thumbs.popup['heading'].cget('text'))
        w.set(lockon_target_style='ring')
        self.assertTrue(w.pump())
        self.assertIn(localization.value_label('ring'), w.thumbs.popup['heading'].cget('text'))
        self.assertTrue(top.bind('<Escape>'))
        label.event_generate('<Button-1>')   # a click on the large picture closes it, as Esc does
        w.window.update()
        self.assertIsNone(w.thumbs.popup)
        self.assertFalse(top.winfo_exists())

    def test_fallback_window_never_errors(self):
        w = MiniWindow(self, everything_on(), thumbs.KEYS, load=lambda: None)
        self.assertTrue(w.pump())
        self.assertIsNone(w.thumbs.art)
        self.assertIn(localization.tr('Example drawing: your game disc could not be read, so the game art is not shown.'),
                      w.thumbs.note())

    def test_pictures_keep_their_size_and_column_when_resized_and_scaled(self):
        import tkinter as tk
        keys = tuple(dict(mod_settings.GROUPS)['HUD'])
        w = MiniWindow(self, everything_on(), keys)
        self.assertTrue(w.pump())
        for geometry in ('860x520', '1400x900', '1040x700'):
            w.window.geometry(geometry); w.window.update(); w.pump()
            xs = {w.rows[k].winfo_x() for k in keys}
            self.assertEqual(len(xs), 1, f'pictures aligned in one column at {geometry}')
            for k in keys:
                self.assertEqual((w.rows[k].winfo_width(), w.rows[k].winfo_height()), w.thumbs.size)
                self.assertLessEqual(w.rows[k].winfo_x()+w.rows[k].winfo_width(), w.page.winfo_width())
        # 125% and 150% scaling: the cards grow with the window's own scaling, still one size for every row.
        for factor in (1.25, 1.5):
            root = tk.Tk()
            scaling = root.tk.call('tk', 'scaling')
            try:
                root.tk.call('tk', 'scaling', factor*96/72)
                t = thumbs.Thumbnails(root, lambda: everything_on(), 'en', load=lambda: None)
                self.assertEqual(t.size, (round(thumbs.CARD[0]*factor), round(thumbs.CARD[1]*factor)))
            finally:
                root.tk.call('tk', 'scaling', scaling)
                root.destroy()

    def test_the_mod_settings_window_puts_a_picture_beside_every_visual_option(self):
        import tkinter as tk
        seen = {}
        real_attach = thumbs.Thumbnails.attach

        def attach(self, parent, row, key, *a, **k):
            seen[key] = (parent, row, k.get('rowspan', 1))
            return real_attach(self, parent, row, key, *a, **k)

        from tkinter import ttk

        def drive(window):
            try:
                window.update()
                for key, (page, row, span) in seen.items():
                    picture = [w for w in page.grid_slaves(row=row, column=2) if isinstance(w, tk.Label)]
                    self.assertEqual(len(picture), 1, key)
                    self.assertEqual(int(picture[0].grid_info()['column']), 2)
                    self.assertEqual(int(picture[0].grid_info()['rowspan']), len(thumbs.shared(key)), key)
                    # A shared picture spans its options' own rows (label or control in column 0 of each).
                    for offset, member in enumerate(thumbs.shared(key)):
                        self.assertTrue([w for w in page.grid_slaves(row=row+offset, column=0)
                                         if not isinstance(w, ttk.Separator)], member)
                results['ok'] = True
            finally:
                window.destroy()

        results = {}
        real_mainloop = tk.Misc.mainloop
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'mod-settings.json'
            path.write_text(json.dumps({'language': 'es'}), encoding='utf-8')
            before = path.read_bytes()

            def mainloop(window, n=0):
                window.after(300, drive, window)
                return real_mainloop(window, n)
            try:
                with patch.object(thumbs.Thumbnails, 'attach', attach), patch.object(tk.Misc, 'mainloop', mainloop), \
                        patch.object(mod_settings, 'SETTINGS_PATH', path):
                    self.assertEqual(mod_settings.show_ui(path), 0)
            except tk.TclError as error:
                self.skipTest(str(error))
            self.assertEqual(path.read_bytes(), before, 'closing the window saves nothing')
        self.assertTrue(results.get('ok'))
        # Every pictured option has a picture: its own, or the one it shares (one target picture, not three).
        self.assertEqual(set(seen), {thumbs.shared(key)[0] for key in thumbs.KEYS})
        self.assertEqual({k for key in seen for k in thumbs.shared(key)}, set(thumbs.KEYS))
        self.assertNotIn('lockon_target_style', seen)


if __name__ == '__main__':
    unittest.main()
