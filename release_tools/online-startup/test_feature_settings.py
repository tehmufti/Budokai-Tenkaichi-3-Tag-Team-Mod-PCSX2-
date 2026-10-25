"""New match settings must reach online rules and each player's own HUD."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_settings as settings
import netplay_state_hash as hashes


class FeatureSettings(unittest.TestCase):
    def test_every_runtime_option_has_one_online_policy(self):
        self.assertEqual(settings.unclassified(), [])

    def test_clash_sequence_is_a_host_rule_and_defaults_off(self):
        self.assertFalse(settings.default_gameplay()['clash_button_sequence'])
        rule = {'clash_button_sequence': True}
        self.assertEqual(settings.gameplay_problems(rule), [])
        self.assertEqual(settings.gameplay_diff(rule), rule)
        self.assertTrue(settings.match_settings(rule, {}, 'es')['clash_button_sequence'])
        self.assertEqual(settings.CLASS['three_player_wide_bottom'], 'na')

    def test_local_counter_preferences_are_independent_and_inverted(self):
        built = settings.match_settings({}, {}, 'en')
        # False installs the draw filter; every peer then sets its own flags.
        self.assertFalse(built['show_combo_hits'])
        self.assertFalse(built['show_combo_damage'])
        for hits, damage in ((True, True), (False, True), (True, False), (False, False)):
            memory = {settings.DISPLAY: settings.DISPLAY_MAGIC,
                      settings.DISPLAY + 0x1C: 1, settings.DISPLAY + 0x20: 1}
            def read(address):
                return memory.get(address, 0)
            for address, data in settings.local_blocks(read, {'show_combo_hits': hits, 'show_combo_damage': damage}):
                memory[address] = struct.unpack('<I', data)[0]
            self.assertEqual(memory[settings.DISPLAY + 0x1C], int(not hits))
            self.assertEqual(memory[settings.DISPLAY + 0x20], int(not damage))
        self.assertFalse(settings.local_blocks(lambda _: 0, {'show_combo_hits': False}))

    def test_clash_progress_is_hashed_but_local_counters_are_not(self):
        rows = hashes.descriptors()
        spans = [(address + offset, address + offset + words * 4)
                 for kind, _, address, offset, words, _ in rows if kind == hashes.DIRECT]
        for address in (0x077E7000, 0x077E7010, 0x077E7100, 0x077E7158):
            self.assertTrue(any(start <= address < end for start, end in spans))
        for address in (settings.DISPLAY + 0x1C, settings.DISPLAY + 0x20):
            self.assertFalse(any(start <= address < end for start, end in spans))


if __name__ == '__main__':
    unittest.main()
