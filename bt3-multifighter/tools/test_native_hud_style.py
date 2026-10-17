import re
import struct
import unittest
from pathlib import Path

import native_hud_style as nhs
from native_map import elf_path
from prototype import ROOT

# Guest code is assembled against the game's own executable (native addresses); without it those tests skip.
NEEDS_ELF = unittest.skipUnless(elf_path(ROOT).is_file(), 'the extracted game executable is required')

# A prepared battle (read only): BT3 slot 215, BT4 slot 220.
SOURCE = next((p for p in (ROOT/'runtime128/sstates/SLUS-21678 (428113C2).215.p2s',
                           ROOT/'runtime128/sstates/SLUS-21978 (428113C2).220.p2s') if p.exists()),
              ROOT/'runtime128/sstates/SLUS-21678 (428113C2).215.p2s')


def ram215():
    from camera_snapshot import read_ram
    return read_ram(SOURCE)


class OneLook(unittest.TestCase):
    """Version 12: every match installs the kit; only the target marker keeps a classic choice."""

    def test_without_a_captured_image_nothing_is_installed(self):
        manifest = nhs.build_memory(bytes(16), settings={})
        self.assertEqual(manifest['blocks'], [])
        self.assertIn('skipped', manifest)

    def test_style_word_follows_the_target_marker_look(self):
        self.assertEqual(nhs.style_word({}), nhs.ALL_BITS)
        self.assertEqual(nhs.style_word({'lockon_target_look': 'native'}), nhs.ALL_BITS)
        self.assertEqual(nhs.style_word({'lockon_target_look': 'classic'}), nhs.ALL_BITS & ~nhs.BIT['lockon'])
        self.assertEqual(struct.unpack_from('<I', nhs.control_block(style=nhs.style_word({'lockon_target_look': 'classic'})), 4)[0],
                         nhs.ALL_BITS & ~nhs.BIT['lockon'])

    def test_option_labels_and_old_saves(self):
        import feature_preferences
        import localization
        import mod_settings
        self.assertNotIn('hud_style', feature_preferences.OPTIONS)
        self.assertNotIn('hud_style', mod_settings.DEFAULTS)
        self.assertEqual(feature_preferences.OPTIONS['lockon_target_look'][:3], ('native', 'choice', ('classic', 'native')))
        hud = dict(mod_settings.GROUPS)['HUD']
        self.assertEqual(hud.index('lockon_target_look'), hud.index('lockon_target_style') + 1)
        self.assertEqual(localization.tr('Target marker look', {'language': 'es'}), 'Aspecto del indicador')
        self.assertEqual([localization.value_label(v, {'language': language}) for language in ('en', 'es')
                          for v in ('classic', 'native')], ['Classic', 'Native', 'Clásico', 'Original'])
        validate = mod_settings.validate_settings
        for saved, look in (({}, 'native'), ({'hud_style': 'classic'}, 'classic'), ({'hud_style': 'native'}, 'native'),
                            ({'hud_style': 'classic', 'lockon_target_look': 'native'}, 'native'),
                            ({'hud_style': 'shiny'}, 'native')):
            with self.subTest(saved=saved):
                result = validate(dict(saved))
                self.assertNotIn('hud_style', result)
                self.assertEqual(result['lockon_target_look'], look)
        with self.assertRaises(ValueError):
            validate({'lockon_target_look': 'shiny'})


@NEEDS_ELF
class FeedPlacement(unittest.TestCase):
    """Kill feed lines (one/two views) start below the native combo counter; only the three newest events show."""

    def test_feed_lines_move_down_and_the_fourth_event_is_left_out(self):
        import guest_killfeed as feed
        from regional import Y_ORIGIN, screen_y
        from test_extra_special_pools import Cpu
        seen = []
        c = Cpu({'segments': [dict(address=nhs.NTEXT, data_hex=nhs.ntext_code().hex())]})
        c.callbacks[nhs.TRAMP['text']] = lambda m: seen.append(m.r[6])      # style word 0: the classic entry
        for caller in (feed.DRAW + 0x40, 0x07274000 + 0x40, 0x01000000):
            for k in range(4):
                for line in (0, 9):
                    seen.clear()
                    y = (Y_ORIGIN + screen_y(106) + 22*k + line)*16
                    c.r[6] = y; c.r[31] = caller; c.run(nhs.NTEXT, stops=(caller,))
                    if caller == 0x01000000:
                        self.assertEqual(seen, [y])                          # any other text: unchanged
                    elif k < 3:
                        self.assertEqual(seen, [y + nhs.feed_shift()*16])    # one/two views: rows 250 onward
                    else:
                        self.assertEqual(seen, [])                           # the fourth event is left out
        self.assertGreater(screen_y(nhs.FEED_TOP), 248)
        self.assertLess(nhs.feed_limit() - Y_ORIGIN + 8, screen_y(448 - 130))


class GsMemory(unittest.TestCase):
    def test_psmt4_upload_round_trip(self):
        indices = bytes((x*7 + y*3) & 15 for y in range(256) for x in range(256))
        data, rw, rh = nhs.upload_from_psmt4(indices, 256, 256, 4)
        self.assertEqual((rw, rh, len(data)), (128, 64, 32768))
        self.assertEqual(nhs.psmt4_from_upload(data, rw, rh, 256, 256, 4), indices)

    def test_clut_entries(self):
        self.assertEqual(nhs.clut_entry(0), (0, 0, 0, 0))
        self.assertEqual(nhs.clut_entry(12)[3], 0x80)         # full fill
        self.assertLess(nhs.clut_entry(3)[0], 0x20)           # rim only: dark
        self.assertEqual(len(nhs.clut_bytes()), 1024)


class Layout(unittest.TestCase):
    @NEEDS_ELF
    def test_code_fits_its_slots(self):
        self.assertLessEqual(nhs.NTEXT + len(nhs.ntext_code()), nhs.TRAMPS)
        self.assertLessEqual(nhs.NART + len(nhs.nart_code()), nhs.CONTROL)
        data, entries = nhs._helpers()
        self.assertLessEqual(nhs.HELPERS + len(data), nhs.SAMPLING)
        self.assertLessEqual(nhs.ART_TABLE + 64*len(nhs.ART), nhs.ART_DATA)
        self.assertEqual(set(entries), {'beam_caption', 'bar_back', 'bar_track', 'bar_fill', 'gauge120', 'revive_gauge',
                                        'arrow_begin', 'ring_begin', 'threat_pair', 'threat_edge', 'sink_lockon', 'sink_threat', 'sink_text', 'tag_back', 'tag_track', 'tag_fill'})

    def test_reservation_is_owned(self):
        """Only the sampling child module can use its explicitly reserved page."""
        pattern = re.compile(r'0x0?(7[0-9A-Fa-f]{6})\b')
        for path in Path(nhs.__file__).parent.glob('*.py'):
            if path.name in ('native_hud_style.py', 'test_native_hud_style.py'):
                continue
            for m in pattern.finditer(path.read_text(encoding='utf-8', errors='ignore')):
                value = int(m.group(1), 16)
                if path.name == 'native_hud_sampling.py' and nhs.BASE <= value < nhs.END:
                    self.assertTrue(nhs.SAMPLING <= value < nhs.SAMPLING + 0x1000)
                    continue
                self.assertFalse(nhs.BASE <= value < nhs.END, (path.name, hex(value)))

    def test_arrow_corners_stay_in_the_texture(self):
        for angle in (0, 90, 180, 270):
            for u, v in nhs.arrow_corners(angle):
                self.assertTrue(0 <= u <= 64 and 0 <= v <= 64, (angle, u, v))


@unittest.skipUnless(SOURCE.exists(), 'prepared battle state 215 not present')
class Prepared(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ram = ram215()

    def test_resident_font_found(self):
        font = nhs.find_font(self.ram)
        self.assertIsNotNone(font)
        self.assertEqual(font['cell'], (20, 20))
        for ch in 'AZaz09!?':
            self.assertIn(ord(ch), font['glyphs'])

    def test_atlas_and_metrics(self):
        upload, rw, rh, clut, metrics, info = nhs.build_atlas(self.ram)
        self.assertEqual((rw, rh, len(upload)), (128, 64, 32768))
        self.assertEqual(info['glyphs'], len(nhs.CHARSET))
        u0, v0, u1, v1, sw, adv, xoff, ok = struct.unpack_from('<4H3bB', metrics, ord('A')*16)
        self.assertEqual((ok, xoff, sw - adv), (1, -nhs.MARGIN, 2*nhs.MARGIN))
        self.assertEqual(v1 - v0, nhs.SLOT_H*16)

    def test_art_copies(self):
        table, data, available = nhs.art_pieces(self.ram)
        for name in ('hud8', 'hud8p3', 'hud8p5', 'arrows', 'lockon', 'hits'):
            self.assertIn(name, available)
        for address, chunk in data:
            self.assertTrue(nhs.ART_DATA <= address and address + len(chunk) <= nhs.ART_END)

    def test_native_build(self):
        manifest = nhs.build_memory(self.ram, settings={})
        self.assertTrue(manifest['blocks'])
        spans = sorted((b['address'], b['address'] + len(b['data_hex'])//2) for b in manifest['blocks'])
        self.assertTrue(all(end <= start for (_, end), (start, _) in zip(spans, spans[1:])))
        for b in manifest['blocks']:
            p = b['address']
            if nhs.BASE <= p < nhs.END:
                self.assertFalse(any(bytes.fromhex(b['expected_hex'])))
        self.assertLessEqual(set(manifest['elements']), set(nhs.NEEDS))

    def installed(self):
        ram = bytearray(self.ram)
        # A synthetic re-pointable site: a classic TEXT head (as an installed kill feed has it) and one jal RECT.
        import guest_killfeed as feed
        import display_settings as display
        import guest_healthbars as bars
        if not any(ram[feed.TEXT:feed.TEXT+8]):
            ram[feed.TEXT:feed.TEXT+8] = feed.text_code()[:8]
        manifest = nhs.build_memory(bytes(ram), settings={})
        for b in manifest['blocks']:
            d = bytes.fromhex(b['data_hex']); ram[b['address']:b['address']+len(d)] = d
        return ram, manifest

    def test_classic_view_restores_every_site(self):
        ram, manifest = self.installed()
        sites = nhs.installed_sites(ram)
        self.assertTrue(sites)
        view = nhs.classic_view(ram)
        for address, word in sites:
            self.assertEqual(struct.unpack_from('<I', view, address)[0], word)
            self.assertNotEqual(struct.unpack_from('<I', ram, address)[0], word)
        self.assertIs(nhs.classic_view(self.ram), self.ram)          # nothing installed: the same object

    def test_dependency_override_maps_classic_to_installed(self):
        import guest_killfeed as feed
        ram, _ = self.installed()
        classic = feed.text_code()
        self.assertEqual(nhs.dependency_override(ram, feed.TEXT, classic)[:8], bytes(ram[feed.TEXT:feed.TEXT+8]))
        self.assertEqual(nhs.dependency_override(ram, feed.TEXT, classic)[8:], classic[8:])
        self.assertEqual(nhs.dependency_override(self.ram, feed.TEXT, classic), classic)

    def test_lazy_ram_gets_an_override_view_never_a_copy(self):
        import lazy_ram
        ram, _ = self.installed()
        class Client:
            def read(self, address, length): return bytes(ram[address:address+length])
        lazy = lazy_ram.LazyRam(Client())
        view = nhs.classic_view(lazy)
        self.assertIsInstance(view, lazy_ram.LazyRam)
        for address, word in nhs.installed_sites(ram):
            self.assertEqual(bytes(view[address:address+4]), struct.pack('<I', word))

    def test_re_preparation_keeps_the_installed_kit(self):
        ram, _ = self.installed()
        self.assertEqual(nhs.build_memory(bytes(ram), settings={})['blocks'], [])

    def test_classic_target_look_clears_only_the_lockon_bit(self):
        manifest = nhs.build_memory(self.ram, settings={'lockon_target_look': 'classic'})
        control = next(b for b in manifest['blocks'] if b['address'] == nhs.CONTROL)
        self.assertEqual(struct.unpack_from('<I', bytes.fromhex(control['data_hex']), 4)[0], nhs.ALL_BITS & ~nhs.BIT['lockon'])

    def test_a_malformed_font_keeps_the_classic_look(self):
        ram = bytearray(self.ram)
        font = nhs.find_font(ram)
        struct.pack_into('<I', ram, font['descriptor']+56, 0xFFFFFFF0)
        self.assertEqual(nhs.build_memory(bytes(ram), settings={})['blocks'], [])


if __name__ == '__main__':
    unittest.main()
