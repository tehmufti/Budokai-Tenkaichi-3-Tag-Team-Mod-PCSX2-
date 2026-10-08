"""Fast CDVD and EE overclock from Mod Settings: applied for the launcher's session, restored exactly."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import presentation_settings as settings

PROFILE = (b'[EmuCore]\r\nEnableWideScreenPatches = false\r\n'
           b'[EmuCore/GS]\r\nOsdShowMessages = true\r\nOsdShowIndicators = true\r\nOther = keep\r\n'
           b'[Pad1]\r\nSquare = Keyboard/X\r\n')


class SpeedSettingsTests(unittest.TestCase):
    def cycle(self, original, choices, during=None, adapter='bt3-usa'):
        """apply -> (optional edit while PCSX2 runs) -> restore; return (applied text, restored bytes, printed)."""
        with tempfile.TemporaryDirectory() as directory:
            config, receipt = Path(directory)/'PCSX2.ini', Path(directory)/'receipt.json'
            config.write_bytes(original)
            mod = dict(widescreen_patch=False, **choices)
            out = io.StringIO()
            with patch('mod_settings.load_settings', return_value=mod), \
                    patch('widescreen_support.embedded', return_value=False), \
                    patch('native_map.ADAPTER', adapter), contextlib.redirect_stdout(out):
                settings.apply(config, receipt)
                applied = config.read_bytes()
                if during: config.write_bytes(during(applied))
                settings.restore(config, receipt)
            return applied.decode('utf-8'), config.read_bytes(), out.getvalue()

    def test_defaults_turn_on_fast_disc_loading_and_leave_the_cpu_rate_alone(self):
        applied, restored, printed = self.cycle(PROFILE, {})
        self.assertIn('[EmuCore/Speedhacks]\r\nfastCDVD = true\r\n', applied)
        self.assertNotIn('EECycleRate', applied)
        self.assertEqual(restored, PROFILE, 'the section the launcher created is removed again')
        self.assertIn('fastCDVD = true', printed); self.assertIn('EECycleRate = PCSX2 setting', printed)

    def test_manual_graphics_fixes_are_disabled_temporarily_without_changing_their_values(self):
        # Auto GameDB alignment fixes must be selected by the emulator version. Leave
        # manual tuning stored but inactive; do not copy 2.8.x enum values into 2.5.x.
        tuning = (b'UserHacks = true\r\nupscale_multiplier = 3\r\n'
                  b'UserHacks_HalfPixelOffset = 2\r\nUserHacks_native_scaling = 2\r\n'
                  b'UserHacks_TCOffsetX = 17\r\nUserHacks_TCOffsetY = 23\r\n')
        original = PROFILE.replace(b'[EmuCore/GS]\r\n', b'[EmuCore/GS]\r\n'+tuning)
        applied, restored, printed = self.cycle(original, {})
        self.assertIn('UserHacks = false\r\n', applied)
        self.assertNotIn('UserHacks = true', applied)
        self.assertIn(tuning.replace(b'UserHacks = true', b'UserHacks = false').decode(), applied)
        self.assertEqual(restored, original)
        self.assertIn('internal resolution = 3', printed)

    def test_missing_manual_graphics_switch_is_removed_again_on_exit(self):
        applied, restored, _ = self.cycle(PROFILE, {})
        self.assertEqual(applied.count('UserHacks = false'), 1)
        self.assertEqual(restored, PROFILE)

    def test_duplicate_manual_graphics_switches_are_healed_and_remembered(self):
        original = PROFILE.replace(b'[EmuCore/GS]\r\n',
                                   b'[EmuCore/GS]\r\nUserHacks = true\r\nUserHacks = true\r\n')
        applied, restored, _ = self.cycle(original, {})
        self.assertEqual(applied.count('UserHacks ='), 1)
        self.assertIn('UserHacks = false', applied)
        self.assertEqual(restored, original)

    def test_manual_graphics_switch_changed_while_playing_is_not_overwritten(self):
        change = lambda data: data.replace(b'UserHacks = false', b'UserHacks = true')
        _, restored, _ = self.cycle(PROFILE, {}, during=change)
        self.assertIn(b'UserHacks = true\r\n', restored)
        self.assertEqual(restored.replace(b'UserHacks = true\r\n', b''), PROFILE)

    def test_older_receipt_without_manual_graphics_switch_still_restores(self):
        original = PROFILE.replace(b'[EmuCore/GS]\r\n', b'[EmuCore/GS]\r\nUserHacks = true\r\n')
        with tempfile.TemporaryDirectory() as directory:
            config, receipt = Path(directory)/'PCSX2.ini', Path(directory)/'receipt.json'
            config.write_bytes(original)
            with patch.dict(settings.VALUES, {k:v for k,v in settings.VALUES.items() if k!='UserHacks'}, clear=True), \
                    patch('mod_settings.load_settings', return_value={'widescreen_patch':False}), \
                    patch('widescreen_support.embedded', return_value=False), contextlib.redirect_stdout(io.StringIO()):
                settings.apply(config, receipt)
            self.assertNotIn('UserHacks', json.loads(receipt.read_text())['values'])
            self.assertTrue(settings.restore(config, receipt))
            self.assertEqual(config.read_bytes(), original)

    def test_bt4_manual_graphics_fixes_are_kept_without_an_automatic_database_replacement(self):
        for switch in (b'', b'UserHacks = true\r\n', b'UserHacks = false\r\n'):
            with self.subTest(switch=switch):
                original=PROFILE.replace(b'[EmuCore/GS]\r\n', b'[EmuCore/GS]\r\n'+switch)
                applied, restored, printed=self.cycle(original, {}, adapter='bt4-b14-rev2-eng')
                self.assertEqual(applied.count('UserHacks ='), int(bool(switch)))
                if switch: self.assertIn(switch.decode(), applied)
                self.assertEqual(restored, original)
                self.assertIn('existing hardware fix preferences', printed)

    def test_fast_disc_loading_can_be_switched_off(self):
        applied, restored, _ = self.cycle(PROFILE, dict(fast_disc_loading=False))
        self.assertIn('fastCDVD = false', applied)
        self.assertEqual(restored, PROFILE)

    def test_each_overclock_choice_maps_to_the_pcsx2_cycle_rate(self):
        for choice, rate in (('130', '1'), ('180', '2'), ('300', '3')):
            with self.subTest(choice=choice):
                applied, restored, printed = self.cycle(PROFILE, dict(emulated_cpu_speed=choice))
                self.assertIn(f'EECycleRate = {rate}', applied)
                self.assertEqual(restored, PROFILE)

    def test_existing_values_are_restored_and_default_never_touches_a_chosen_rate(self):
        original = PROFILE + b'[EmuCore/Speedhacks]\r\nEECycleRate = 3\r\nfastCDVD = false\r\nvuThread = true\r\n'
        applied, restored, _ = self.cycle(original, dict(emulated_cpu_speed='default'))
        self.assertIn('EECycleRate = 3', applied, "'default' keeps the user's own PCSX2 choice")
        self.assertIn('fastCDVD = true', applied)
        self.assertEqual(restored, original)
        applied, restored, _ = self.cycle(original, dict(emulated_cpu_speed='130', fast_disc_loading=False))
        self.assertIn('EECycleRate = 1', applied)
        self.assertEqual(restored, original)

    def test_a_section_pcsx2_wrote_into_during_the_session_is_kept(self):
        add = lambda data: data.replace(b'fastCDVD = true\r\n', b'fastCDVD = true\r\nvuThread = true\r\n')
        _, restored, _ = self.cycle(PROFILE, {}, during=add)
        text = restored.decode('utf-8')
        self.assertIn('[EmuCore/Speedhacks]\r\nvuThread = true\r\n', text)
        self.assertNotIn('fastCDVD', text)

    def test_lf_profiles_and_a_missing_final_newline_survive_the_round_trip(self):
        for original in (PROFILE.replace(b'\r\n', b'\n'), PROFILE.rstrip(b'\r\n'), PROFILE.replace(b'\r\n', b'\n').rstrip(b'\n')):
            with self.subTest(original=original[-12:]):
                applied, restored, _ = self.cycle(original, dict(emulated_cpu_speed='300'))
                self.assertIn('fastCDVD = true', applied); self.assertIn('EECycleRate = 3', applied)
                self.assertEqual(restored, original)

    def test_savestate_compression_is_zstandard_for_the_session_and_the_players_choice_returns(self):
        # PCSX2 2.6 offers Deflate64 (1) and LZMA2 (3); the mod's state readers need Zstandard (2).
        for chosen in (None, b'0', b'1', b'2', b'3'):
            with self.subTest(chosen=chosen):
                original = PROFILE if chosen is None else PROFILE.replace(
                    b'[EmuCore]\r\n', b'[EmuCore]\r\nSavestateCompressionType = '+chosen+b'\r\n')
                applied, restored, printed = self.cycle(original, {})
                core = applied.split('[EmuCore]\r\n', 1)[1].split('[', 1)[0]
                self.assertEqual(core.count('SavestateCompressionType'), 1)
                self.assertIn('SavestateCompressionType = 2\r\n', core)
                self.assertEqual(restored, original)
                self.assertIn('SavestateCompressionType = 2', printed)

    def test_compression_changed_during_the_session_is_left_alone(self):
        change = lambda data: data.replace(b'SavestateCompressionType = 2', b'SavestateCompressionType = 3')
        _, restored, _ = self.cycle(PROFILE, {}, during=change)
        self.assertIn(b'SavestateCompressionType = 3\r\n', restored)
        self.assertEqual(restored.replace(b'SavestateCompressionType = 3\r\n', b''), PROFILE)

    def test_a_profile_without_emucore_gets_one_for_the_session_only(self):
        bare = b'[EmuCore/GS]\r\nOsdShowMessages = true\r\n[Pad1]\r\nSquare = Keyboard/X\r\n'
        for original in (bare, bare.rstrip(b'\r\n'), bare.replace(b'\r\n', b'\n'), bare.replace(b'\r\n', b'\n').rstrip(b'\n')):
            with self.subTest(original=original[-14:]):
                applied, restored, _ = self.cycle(original, dict(emulated_cpu_speed='180'))
                self.assertRegex(applied, r'\[EmuCore\]\r?\nSavestateCompressionType = 2\r?\n')
                self.assertIn('EECycleRate = 2', applied)
                self.assertEqual(restored, original)
        # Keys PCSX2 saves into that section while it runs keep the section.
        keep = lambda data: data.replace(b'SavestateCompressionType = 2\r\n', b'SavestateCompressionType = 2\r\nEnableCheats = true\r\n')
        _, restored, _ = self.cycle(bare, {}, during=keep)
        self.assertIn(b'[EmuCore]\r\nEnableCheats = true\r\n', restored)
        self.assertNotIn(b'SavestateCompressionType', restored)

    def test_receipts_only_accept_known_emulator_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            config, receipt = Path(directory)/'PCSX2.ini', Path(directory)/'receipt.json'
            config.write_bytes(PROFILE)
            receipt.write_text('{"config": "%s", "values": {}, "applied": {}, "extra": '
                               '[{"section": "EmuCore/Speedhacks", "key": "vuThread", "prior": null, "applied": "true"}]}'
                               % str(config.resolve()).replace('\\', '\\\\'))
            with self.assertRaisesRegex(ValueError, 'Unexpected'): settings.restore(config, receipt)
            self.assertEqual(config.read_bytes(), PROFILE)
            receipt.write_text('{"config": "%s", "values": {}, "applied": {}, "extra": [], '
                               '"created_sections": [{"section": "Pad1", "terminated": false}]}'
                               % str(config.resolve()).replace('\\', '\\\\'))
            with self.assertRaisesRegex(ValueError, 'Unexpected created section'): settings.restore(config, receipt)
            self.assertEqual(config.read_bytes(), PROFILE)


if __name__ == '__main__':
    unittest.main()
