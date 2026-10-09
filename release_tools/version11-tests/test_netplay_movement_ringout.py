"""New gameplay fields participate in the emitted online desync probe."""
import support
import struct
import unittest

import ground_locomotion as ground
import tournament_ringout as ringout
import netplay_state_hash as nh
from test_netplay_state_hash import image, run


class MovementRingoutHashTests(unittest.TestCase):
    def state(self):
        ram = bytearray(image())
        struct.pack_into('<6I', ram, ringout.CONTROL, ringout.MAGIC, ringout.VERSION,
                         0x01870400, 6, 1, 0)
        struct.pack_into('<4I', ram, ground.CONTROL, ground.MAGIC, 0x01870400, 6, 1)
        struct.pack_into('<I', ram, ground.CONTROL + ground.C['style'], 1)
        return ram

    def probe(self, ram, profile):
        stop, manifest, before, cpu, entry, _ = run(ram, profile)
        self.assertEqual(stop, manifest['previous'])
        self.assertEqual(cpu.r, before)
        self.assertEqual((entry['classes'], entry['words']), nh.reference(ram, profile=profile))
        return entry['classes']

    def changed_word(self, address, profile, changed):
        ram = self.state()
        before = self.probe(ram, profile)
        word = struct.unpack_from('<I', ram, address)[0]
        struct.pack_into('<I', ram, address, word ^ 1)
        after = self.probe(ram, profile)
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b], changed)

    def test_ringout_elimination_and_ground_style_are_hashed_in_both_profiles(self):
        for profile in ('lean', 'full'):
            for address in (ringout.CONTROL + ringout.F['eliminated'],
                            ringout.CONTROL + ringout.F['enabled'],
                            ground.CONTROL + ground.C['style'],
                            ground.CONTROL + ground.C['run13']):
                with self.subTest(profile=profile, address=hex(address)):
                    self.changed_word(address, profile, [6])

    def test_debug_counters_never_change_gameplay_hashes(self):
        for profile in ('lean', 'full'):
            for address in (ringout.CONTROL + ringout.F['contacts'],
                            ringout.CONTROL + ringout.F['last_actor'],
                            ground.CONTROL + ground.COUNTERS['substitutions']):
                with self.subTest(profile=profile, address=hex(address)):
                    self.changed_word(address, profile, [])

    def test_full_profile_adds_per_fighter_movement_state(self):
        address = ground.ACTORS + 7 * ground.ROW + ground.R['step']
        self.changed_word(address, 'full', [6])
        self.changed_word(address, 'lean', [])


if __name__ == '__main__':
    unittest.main()
