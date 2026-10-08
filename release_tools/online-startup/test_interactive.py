"""Combat-readiness timing regressions; the diagnostic never writes game memory."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_lockstep as lockstep
from pinelink import nc

NATIVE = SimpleNamespace(battle=0x2FEB38, result=0x333700)
BATTLE = 0x200000


class ReadOnlyGuest:
    def __init__(self):
        self.memory = {}
        self.reads = 0
        self.error = None
        self.set(NATIVE.battle, BATTLE)
        self.set(BATTLE, nc.FIGHT)
        self.set(BATTLE + 264, 10)

    def set(self, address, value):
        for i, byte in enumerate(struct.pack('<I', value)):
            self.memory[address + i] = byte

    def read_ranges(self, ranges):
        self.reads += 1
        if self.error:
            raise self.error
        return [bytes(self.memory.get(a + i, 0) for i in range(n)) for a, n in ranges]

    # Intentionally no write/configure methods: measurements must remain read-only.


def session(cls=lockstep._Base, started=1.0):
    guest = ReadOnlyGuest()
    value = cls(guest, None, member=1, slot=0, mask=3, delay=2, state_sha='0' * 64,
                clock=lambda: 9.0, startup_started_at=started)
    value.started_at = 5.0
    return value, guest


def running(waiting=False):
    return dict(state=nc.RUNNING, frame=360, waiting=waiting)


class InteractiveTiming(unittest.TestCase):
    def setUp(self):
        self.native_patch = patch.object(nc, 'natives', return_value=NATIVE)
        self.native_patch.start()
        self.addCleanup(self.native_patch.stop)

    def test_full_intro_does_not_count_as_usable_combat(self):
        s, g = session()
        for now, director in ((5.0, 0), (6.0, 1), (7.0, 2)):
            g.set(BATTLE, director); g.set(BATTLE + 264, int(now * 30))
            s.watch_interactive(now, running())
        self.assertIsNone(s.interactive)
        g.set(BATTLE, nc.FIGHT)
        s.watch_interactive(8.0, running())
        g.set(BATTLE + 264, 211)
        s.watch_interactive(8.1, running())
        self.assertEqual(s.startup_seconds, 7.1)
        self.assertEqual(s.interactive['intro_seconds'], 3.1)
        self.assertEqual(s.events[-1]['event'], 'interactive')

    def test_stationary_clock_is_not_playable(self):
        s, _ = session()
        for now in (5.0, 5.1, 7.0):
            s.watch_interactive(now, running())
        self.assertIsNone(s.interactive)

    def test_each_start_hold_blocks_measurement(self):
        for hold in (lockstep.PREPARATION_CONTROL + 16, lockstep.TEAM_START_CONTROL,
                     lockstep.FIGHTER_START_HOLD):
            with self.subTest(hold=hex(hold)):
                s, g = session()
                g.set(lockstep.PREPARATION_CONTROL, lockstep.PREPARATION_MAGIC)
                g.set(hold, 1)
                s.watch_interactive(5.0, running())
                g.set(BATTLE + 264, 11); s.watch_interactive(5.1, running())
                self.assertIsNone(s.interactive)
                g.set(hold, 0); s.watch_interactive(5.2, running())
                self.assertIsNone(s.interactive)
                g.set(BATTLE + 264, 12); s.watch_interactive(5.3, running())
                self.assertEqual(s.startup_seconds, 4.3)

    def test_inactive_preparation_record_does_not_hold_the_fight(self):
        s, g = session()
        g.set(lockstep.PREPARATION_CONTROL + 16, 1)
        s.watch_interactive(5.0, running())
        g.set(BATTLE + 264, 11); s.watch_interactive(5.1, running())
        self.assertIsNotNone(s.interactive)

    def test_brief_input_wait_defers_until_input_is_available(self):
        s, g = session()
        s.watch_interactive(5.0, running(True))
        g.set(BATTLE + 264, 11); s.watch_interactive(5.1, running(True))
        self.assertIsNone(s.interactive)
        s.watch_interactive(5.2, running(False))
        self.assertEqual(s.startup_seconds, 4.2)

    def test_stale_motion_during_a_long_wait_cannot_count(self):
        s, g = session()
        s.watch_interactive(5.0, running(True))
        g.set(BATTLE + 264, 11); s.watch_interactive(5.1, running(True))
        s.watch_interactive(6.0, running(False))
        self.assertIsNone(s.interactive)
        g.set(BATTLE + 264, 12); s.watch_interactive(6.1, running(False))
        self.assertEqual(s.startup_seconds, 5.1)

    def test_result_or_non_running_core_never_marks_combat(self):
        for state, result in ((nc.ARMED, 0), (nc.DECIDED, 0), (nc.RUNNING, 1)):
            with self.subTest(state=state, result=result):
                s, g = session(); g.set(NATIVE.result, result)
                c = running(); c['state'] = state
                s.watch_interactive(5.0, c)
                g.set(BATTLE + 264, 11); s.watch_interactive(5.1, c)
                self.assertIsNone(s.interactive)

    def test_bad_pointer_and_read_errors_are_diagnostic_only(self):
        for pointer in (0, 0xFFFFFFFC, 0x200001, 0x8000000 - 264):
            with self.subTest(pointer=hex(pointer)):
                s, g = session(); g.set(NATIVE.battle, pointer)
                s.watch_interactive(5.0, running())
                self.assertIsNone(s.interactive)
        s, g = session(); g.error = OSError('PINE busy')
        s.watch_interactive(5.0, running())
        self.assertIsNone(s.interactive)
        g.error = None; s.watch_interactive(5.1, running())
        g.set(BATTLE + 264, 11); s.watch_interactive(5.2, running())
        self.assertIsNotNone(s.interactive)

    def test_clock_reset_and_battle_replacement_reset_evidence(self):
        s, g = session(); s.watch_interactive(5.0, running())
        g.set(BATTLE + 264, 0); s.watch_interactive(5.1, running())
        self.assertIsNone(s.interactive)
        g.set(BATTLE + 264, 1); s.watch_interactive(5.2, running(True))
        newer = BATTLE + 0x1000
        g.set(NATIVE.battle, newer); g.set(newer, nc.FIGHT); g.set(newer + 264, 4)
        s.watch_interactive(5.3, running())
        self.assertIsNone(s.interactive)
        g.set(newer + 264, 5); s.watch_interactive(5.4, running())
        self.assertEqual(s.startup_seconds, 4.4)

    def test_unsigned_battle_clock_wrap_is_valid_forward_motion(self):
        s, g = session(); g.set(BATTLE + 264, 0xFFFFFFFF)
        s.watch_interactive(5.0, running())
        g.set(BATTLE + 264, 0); s.watch_interactive(5.1, running())
        self.assertIsNotNone(s.interactive)

    def test_diagnostic_polls_are_bounded_and_stop_after_marker(self):
        s, g = session(); s.watch_interactive(5.0, running())
        calls = g.reads
        s.watch_interactive(5.01, running())
        self.assertEqual(g.reads, calls)
        g.set(BATTLE + 264, 11); s.watch_interactive(5.1, running())
        calls = g.reads
        s.watch_interactive(50.0, running())
        self.assertEqual(g.reads, calls)
        self.assertEqual(sum(e['event'] == 'interactive' for e in s.events), 1)

    def test_legacy_sessions_do_not_add_pine_reads(self):
        s, g = session(started=None); s.watch_interactive(5.0, running())
        self.assertEqual(g.reads, 0)

    def test_both_client_and_host_expose_the_actual_startup_marker(self):
        for cls in (lockstep.Hub, lockstep.Client):
            with self.subTest(cls=cls.__name__):
                s, g = session(cls); s.watch_interactive(5.0, running())
                g.set(BATTLE + 264, 11); s.watch_interactive(5.1, running())
                self.assertEqual(s.status()['startup_seconds'], 4.1)
                self.assertEqual(s.summary()['interactive'], s.interactive)


if __name__ == '__main__':
    unittest.main()
