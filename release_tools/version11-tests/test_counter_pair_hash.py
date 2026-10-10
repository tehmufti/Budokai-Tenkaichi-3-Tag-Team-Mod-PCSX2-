"""Online desync detection includes counter opponents and lifetime, not counters."""
import support
import struct
import unittest
import vanish_pair_guard as vanish
from test_netplay_movement_ringout import MovementRingoutHashTests


class CounterPairHashTests(MovementRingoutHashTests):
    def test_counter_bindings_and_clock_are_hashed(self):
        for profile in ('lean','full'):
            for address in (vanish.CLOCK, vanish.ROWS, vanish.ROWS+7*vanish.STRIDE+40,
                            vanish.ROWS+11*vanish.STRIDE+44):
                with self.subTest(profile=profile,address=hex(address)):
                    self.changed_word(address,profile,[6])

    def test_counter_telemetry_is_not_hashed(self):
        for profile in ('lean','full'):
            for address in (vanish.CAPTURED,vanish.REJECTED):
                with self.subTest(profile=profile,address=hex(address)):
                    self.changed_word(address,profile,[])


if __name__=='__main__':unittest.main()
