"""Form/disc-specific tag presentation, with optional user-disc source checks."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
from pathlib import Path
import unittest

import tag_beam_profiles as profiles


class TagBeamProfileTests(unittest.TestCase):
    def test_same_roster_id_never_crosses_disc_roles(self):
        cases = (
            (34, 'galick_gun', 'dark_kamehameha'),
            (59, 'native_beam', 'kamehameha'),
            (64, 'native_beam', 'kamehameha'),
            (68, 'kamehameha', 'one_handed_gold'),
            (85, 'native_beam', 'kamehameha'),
            (98, 'native_beam', 'kamehameha'),
            (99, 'native_beam', 'dark_kamehameha'),
            (104, 'native_beam', 'native_beam'),
            (110, 'native_beam', 'kamehameha'),
            (113, 'kamehameha', 'galick_gun'),
            (149, 'native_beam', 'gold_clash'),
            (158, 'auto', 'kamehameha'),
        )
        for character, bt3, bt4 in cases:
            with self.subTest(character=character):
                self.assertEqual(profiles.profile(character)['family'], bt3)
                self.assertEqual(profiles.profile(character, bt4=True)['family'], bt4)
        self.assertEqual(profiles.profile(104)['color'], profiles.PINK)
        self.assertEqual(profiles.profile(104, bt4=True)['color'], profiles.GREEN)
        self.assertEqual(profiles.profile(38)['slot'], 4)
        self.assertEqual(profiles.profile(38, bt4=True)['slot'], 2)

    def test_current_forms_keep_explicit_colors_and_donors(self):
        for bt4 in (False, True):
            with self.subTest(bt4=bt4):
                for character in (0, 14, 17, 21, 25, 53, 63, 105, 112, 116, 159, 160):
                    self.assertEqual(profiles.profile(character, bt4=bt4)['color'], profiles.BLUE)
                self.assertEqual(profiles.profile(10, bt4=bt4)['color'], profiles.RED)
                self.assertEqual(profiles.profile(13, bt4=bt4)['family'], 'masenko')
                self.assertEqual(profiles.profile(14, bt4=bt4)['family'], 'kamehameha')
                for character in (27, 28):
                    row = profiles.profile(character, bt4=bt4)
                    self.assertEqual((row['family'], row['color']), ('dodon_ray', profiles.ORANGE))
                for character in (24, 39, 45, 77):
                    self.assertEqual(profiles.profile(character, bt4=bt4)['mode'], 'generic')
                self.assertEqual(profiles.profile(106, bt4=bt4)['donor'], 0)
                self.assertEqual(profiles.profile(159, bt4=bt4)['slot'], 4)
                future = profiles.profile(160, bt4=bt4)
                self.assertEqual((future['donor'], future['slot']), (159, 4))
                buu = profiles.profile(114, bt4=bt4)
                self.assertEqual((buu['donor'], buu['slot'], buu['color']), (80, 4, profiles.PINK))
        for character in (34, 99):
            self.assertEqual(profiles.profile(character, bt4=True)['color'], profiles.DARK_PINK)
        for character in (32, 33, 36, 208, 218, 219):
            row = profiles.profile(character, bt4=True)
            self.assertEqual((row['donor'], row['color']), (29, profiles.GOLD))
        for character in (35, 113, 217):
            row = profiles.profile(character, bt4=True)
            self.assertEqual((row['donor'], row['color']), (29, profiles.PURPLE))
        self.assertEqual(profiles.profile(68, bt4=True)['donor'], 37)
        for character in (51, 52):
            self.assertEqual(profiles.profile(character, bt4=True)['donor'], 0)
        self.assertEqual(profiles.profile(139, bt4=True)['donor'], 53)
        self.assertEqual(profiles.profile(139, bt4=True)['slot'], 2)

    def test_reviewed_native_beams_keep_their_own_slot_and_palette(self):
        cases = (
            (False, 64, 2, profiles.BLUE), (True, 196, 2, profiles.BLUE),
            (False, 79, 2, profiles.PURPLE), (True, 184, 2, profiles.PURPLE),
            (False, 99, 3, profiles.PURPLE), (True, 223, 3, profiles.PURPLE),
            (False, 154, 2, profiles.GOLD), (True, 180, 2, profiles.GOLD),
            (False, 131, 2, profiles.GREEN), (True, 188, 2, profiles.GREEN),
            (True, 78, 2, profiles.CYAN), (True, 199, 2, profiles.GREEN),
            (True, 200, 4, profiles.GREEN), (True, 209, 3, profiles.GREEN),
            (True, 71, 2, profiles.PURPLE), (True, 76, 4, profiles.GOLD),
            (True, 126, 2, profiles.BLUE), (True, 127, 2, profiles.PURPLE),
            (True, 118, 2, profiles.RED), (True, 119, 2, profiles.GOLD),
        )
        for bt4, character, slot, color in cases:
            with self.subTest(bt4=bt4, character=character):
                row = profiles.profile(character, bt4=bt4)
                self.assertEqual((row['mode'], row['slot'], row['color']), ('own', slot, color))
                self.assertIsNone(row['donor'])

    def test_unreviewed_projectiles_and_arale_do_not_get_forced_beam_slots(self):
        for bt4, characters in (
            (False, (132, 133, 158, 250, 255)),
            (True, (70, 74, 81, 94, 95, 128, 131, 132, 133, 138, 156, 189, 190, 250, 255)),
        ):
            for character in characters:
                with self.subTest(bt4=bt4, character=character):
                    self.assertEqual(profiles.profile(character, bt4=bt4)['mode'], 'auto')

    def test_profile_records_are_independent_and_inputs_are_bounded(self):
        row = profiles.profile(71, bt4=True)
        row['color'] = (0, 0, 0)
        row['slot'] = 4
        self.assertEqual(profiles.profile(71, bt4=True)['color'], profiles.PURPLE)
        self.assertEqual(profiles.profile(71, bt4=True)['slot'], 2)
        for invalid in (-1, 256, True, None, 1.0, '0'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                profiles.profile(invalid)
        for bt4 in (False, True):
            for character in range(256):
                row = profiles.profile(character, bt4=bt4)
                self.assertIn(row['mode'], ('auto', 'generic', 'own', 'donor'))
                if row['mode'] in ('own', 'donor'):
                    self.assertIn(row['slot'], (2, 3, 4))
                if row['color'] is not None:
                    self.assertEqual(len(row['color']), 3)
                    self.assertTrue(all(type(channel) is int and 0 <= channel <= 255 for channel in row['color']))

    def test_localized_names_do_not_change_id_selected_colors(self):
        from tag_rush_colors import character_color
        for bt4, character in ((False, 99), (True, 99), (True, 104), (False, 104)):
            expected = profiles.profile(character, bt4=bt4)['color']
            for name in ('Freezer', 'Frieza', 'Celula', '\u30d5\u30ea\u30fc\u30b6', ''):
                self.assertEqual(character_color({'name': name}, character, bt4=bt4), expected)


class UserDiscBeamSourceTests(unittest.TestCase):
    def test_every_explicit_sequence_decodes_in_selected_disc(self):
        from native_map import SERIAL
        bt4 = SERIAL == 'SLUS-21978'
        filenames = {
            'SLUS-21678': ('Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso',),
            'SLES-54945': ('Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) (Versus Fighting) (ISO) (PS2).iso',),
            'SLPS-25815': ('Dragon Ball Z - Sparking! Meteor (Japan).iso',),
            'SLUS-21978': ('SLUS_219.78.DBZBT4B14REV2ENG.iso', 'SLUS_219.78.DBZBT4B14REV2.iso'),
        }.get(SERIAL, ())
        games = Path(__file__).resolve().parents[2] / 'games'
        discs = [games / filename for filename in filenames if (games / filename).is_file()]
        if not discs:
            self.skipTest('User-owned game disc not present')
        for iso in discs:
            with self.subTest(disc=iso.name):
                self._check_iso(iso, bt4)

    def _check_iso(self, iso, bt4):
        import model_assets
        from model_animations import AnimationClip, BONE_COUNT, MAX_DECODED_SIZE, decompress_animation
        banks, checked = {}, set()
        for character in range(250 if bt4 else 161):
            row = profiles.profile(character, bt4=bt4)
            if row['mode'] == 'auto':
                continue
            source = row['donor'] if row['mode'] == 'donor' else character
            fire = 364 if row['mode'] == 'generic' else 196 + 34 * row['slot']
            if source not in banks:
                banks[source] = model_assets.read_animation_bank(iso, source)
            animations = (fire,) if row['mode'] == 'generic' else range(fire - 3, fire + 1)
            for animation in animations:
                if (source, animation) in checked:
                    continue
                checked.add((source, animation))
                with self.subTest(character=character, source=source, animation=animation, bt4=bt4):
                    raw = decompress_animation(model_assets.package_entry(banks[source], animation + 1))
                    self.assertTrue(148 <= len(raw) <= MAX_DECODED_SIZE)
                    clip = AnimationClip.from_decoded(animation, raw)
                    self.assertTrue(1 <= clip.frame_count <= 3600)
                    self.assertTrue(clip.tracks)
                    self.assertLessEqual(len(clip.tracks), BONE_COUNT)
                    for track in clip.tracks:
                        self.assertTrue(0 <= track.bone_id < BONE_COUNT)
                        self.assertEqual(len(track.times), len(track.keys))
                    for frame in (0, clip.frame_count / 2, clip.frame_count):
                        for transform in clip.evaluate(frame).values():
                            values = (*transform.rotation, *(transform.translation or ()))
                            self.assertTrue(all(math.isfinite(value) for value in values))


if __name__ == '__main__':
    unittest.main()
