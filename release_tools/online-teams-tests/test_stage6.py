"""Online stage 6: the wait for the first fighters seen from the kit, a leaver's bit in the team table, a single
local player on the unpaused load path (no game, emulator or network peer; synthetic fixtures only).

Run: python -m unittest discover -s release_tools/online-teams-tests -p 'test_*.py'
"""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('TTM_KIT_RUNTIME', tempfile.mkdtemp(prefix='ttm-stage6-tests-'))
NETPLAY = ROOT / 'bt3-multifighter/online/netplay'
TOOLS = ROOT / 'bt3-multifighter/tools'
sys.path.insert(0, str(NETPLAY))
import kit_paths  # noqa: E402,F401
import kit_fight  # noqa: E402
import kit_lockstep  # noqa: E402
import kit_prepare  # noqa: E402
import kit_prepare_auto  # noqa: E402
import kit_spec  # noqa: E402
import kit_text  # noqa: E402
from pinelink import nc  # noqa: E402

policy = kit_spec.squad_policy()


class LeaderWait(unittest.TestCase):
    """The mod waits for the two native leaders' models inside the host's copy (fresh_team_trainer
    StreamingSession.settled_leaders); the kit shows that wait and logs how it ended."""

    def mod_lines(self, language):
        import localization
        with localization.using(language):
            return (localization.tr('Waiting for the game to finish setting up the first fighters...'),
                    localization.tr('First fighters ready after 0.4 s (memory read 2 times).'),
                    localization.tr('First fighters not ready after 8.0 s: Leader0 model pointer is outside valid '
                                    'aligned game RAM'))

    def test_the_mods_three_lines_are_read_in_english_and_spanish(self):
        for language in ('en', 'es'):
            waiting, ready, late = self.mod_lines(language)
            with self.subTest(language=language):
                self.assertEqual(kit_prepare.leader_wait(['Loading selected character resources...', waiting]),
                                 dict(state='waiting'))
                self.assertEqual(kit_prepare.leader_wait([waiting, '  ' + ready + '  ']),
                                 dict(state='ready', seconds=0.4, reads=2))
                found = kit_prepare.leader_wait([waiting, late])
                self.assertEqual((found['state'], found['seconds']), ('late', 8.0))
                self.assertIn('Leader0', found['reason'])
        self.assertNotEqual(self.mod_lines('en'), self.mod_lines('es'))
        self.assertIsNone(kit_prepare.leader_wait(['18:57:24 INFO: New 2v4 match: getting every fighter ready.']))
        self.assertIsNone(kit_prepare.leader_wait([]))

    def copy(self, lines):
        prep = kit_prepare_auto.PrepCopy.__new__(kit_prepare_auto.PrepCopy)
        prep.said, prep.events, prep.lang = [], [], 'en'
        prep.say = prep.said.append
        prep.event = lambda what, **fields: prep.events.append((what, fields))
        prep.watcher_lines = lambda: list(lines)
        return prep

    def test_the_wait_is_shown_while_it_lasts_and_logged_once_when_it_ends(self):
        waiting, ready, _ = self.mod_lines('en')
        lines = ['an older match', ready]                    # a line of the PREVIOUS preparation in the same log
        prep = self.copy(lines)
        seen = dict(mark=len(lines), state=None, looked=0.0)
        self.assertIsNone(prep.leader_wait(seen, every=0))
        lines.append(waiting)
        self.assertEqual(prep.leader_wait(seen, every=0), 'waiting')
        self.assertEqual(prep.leader_wait(seen, every=0), 'waiting')
        lines.append(ready.replace('0.4', '1.2').replace('read 2', 'read 3'))
        self.assertEqual(prep.leader_wait(seen, every=0), 'ready')
        self.assertEqual(prep.leader_wait(seen, every=0), 'ready')
        self.assertEqual(prep.said, ['First fighters ready after 1.2 s (memory read 3 times).'])
        self.assertEqual([e[0] for e in prep.events], ['leaders waiting', 'leaders settled'])
        self.assertEqual(prep.events[1][1], dict(seconds=1.2, reads=3))

    def test_spanish_pc_spanish_line_and_a_restarted_copy(self):
        waiting, _, late = self.mod_lines('es')
        lines = ['x'] * 30
        prep = self.copy(lines)
        prep.lang = 'es'
        seen = dict(mark=30, state=None, looked=0.0)
        del lines[:]                                          # the copy was started again: a new, shorter log
        lines += [waiting, late]
        self.assertEqual(prep.leader_wait(seen, every=0), 'late')
        self.assertTrue(prep.said[0].startswith('Los primeros luchadores no están listos tras 8.0 s: '))
        self.assertEqual(prep.events[-1][0], 'leaders not settled')

    def test_the_looks_are_paced(self):
        prep = self.copy([self.mod_lines('en')[0]])
        seen = dict(mark=0, state=None, looked=0.0)
        self.assertEqual(prep.leader_wait(seen), 'waiting')
        prep.watcher_lines = lambda: self.fail('looked again within the half second')
        self.assertEqual(prep.leader_wait(seen), 'waiting')

    def test_texts_and_the_kit_copy_of_the_capture_module(self):
        for key in ('prep.leaders', 'prep.leaders_ready', 'prep.leaders_late'):
            self.assertEqual(set(kit_text.TEXT[key]) if hasattr(kit_text, 'TEXT') else {'en', 'es'}, {'en', 'es'})
            self.assertNotEqual(kit_text.t(key, 'en', seconds='1.0', reads=2, reason='r'),
                                kit_text.t(key, 'es', seconds='1.0', reads=2, reason='r'))
        copy, tools = NETPLAY / 'modtools/selected_team_capture.py', TOOLS / 'selected_team_capture.py'
        self.assertEqual(hashlib.sha256(copy.read_bytes()).hexdigest(), hashlib.sha256(tools.read_bytes()).hexdigest())
        self.assertIn('def leader_models_pending', copy.read_text(encoding='utf-8'))
        trainer = (TOOLS / 'fresh_team_trainer.py').read_text(encoding='utf-8')
        self.assertIn('def settled_leaders', trainer)         # the wait itself is the mod's, in the host's copy
        for path, edits in kit_prepare.patches(29221).items():   # ...and the kit's private edits still fit it
            if path.endswith('fresh_team_trainer.py'):
                for old, _ in edits:
                    self.assertEqual(trainer.replace('\r\n', '\n').count(old), 1, old[:60])


class LeaverBit(unittest.TestCase):
    @unittest.skipIf(policy is None, 'the mod modules of this tree do not know three to five teams')
    def test_a_leaver_loses_its_bit_in_the_team_tables_human_mask(self):
        writes = kit_fight.FightMixin.squad_leaver_writes(dict(team_count=3), 5)
        self.assertEqual(writes, [(policy.SQUAD + policy.SQUAD_FIELDS['humans'], 0, 1 << 5)])
        address = writes[0][0]
        self.assertTrue(policy.SQUAD <= address < policy.SQUAD + 0x4C)       # inside the hashed team row
        import netplay_state_hash
        row = netplay_state_hash.squad_rows()[0]
        self.assertTrue(row[2] <= address < row[2] + 4 * row[4])

    def test_every_other_match_gets_no_such_write(self):
        self.assertEqual(kit_fight.FightMixin.squad_leaver_writes({}, 1), [])
        self.assertEqual(kit_fight.FightMixin.squad_leaver_writes(None, 1), [])
        self.assertEqual(kit_fight.FightMixin.squad_leaver_writes(dict(mode='ffa'), 1), [])

    def test_it_travels_in_the_same_scheduled_entry_as_the_hand_over(self):
        import inspect
        source = inspect.getsource(kit_fight.FightMixin.drop_to_cpu)
        self.assertLess(source.index('self.squad_leaver_writes(spec, slot)'), source.index('self.session.schedule(writes)'))
        self.assertEqual(source.count('self.session.schedule('), 1)


class Guest:
    def __init__(self, **control):
        self.c = dict(magic=nc.MAGIC, layout=nc.LAYOUT, mode=nc.LOCKSTEP, enable=1, delay=1, state=nc.RUNNING,
                      frame=1, mask=1 << 7, local_slot=7, self_feed=1)
        self.c.update(control)
        self.configured = []

    def control(self):
        return dict(self.c)

    def configure(self, **values):
        self.configured.append(values)


def session(slot, own_mask, **control):
    s = kit_lockstep.Hub.__new__(kit_lockstep.Hub)
    s.guest = Guest(**control)
    s.slot, s.mask, s.delay, s.layout, s.session = slot, own_mask, 1, nc.LAYOUT, 1
    s.clock = lambda: 0.0
    s.events = []
    s.event = lambda kind, **fields: s.events.append((kind, fields))
    return s


class SoloLateAttach(unittest.TestCase):
    """A copy loaded into the running game without a pause (the only way on Linux) whose one player is this PC's
    own runs on by itself: the session may attach while the game's rings still hold everything from frame 0."""

    def test_one_local_player_is_attached_to_past_frame_d(self):
        self.assertEqual(kit_lockstep.SOLO_LATE, min(nc.OUT_SLOTS, nc.HASH_SLOTS) // 4)
        for frame in (1, 2, 17, kit_lockstep.SOLO_LATE):
            s = session(7, 1 << 7, frame=frame)
            s.attach()
            kind, fields = s.events[-1]
            self.assertEqual((kind, fields['late'], fields['alone']), ('attach', True, frame > 1))
            self.assertEqual(s.guest.configured, [])           # the copy's own words: nothing is written

    def test_beyond_the_rings_quarter_it_is_refused_with_the_reason(self):
        s = session(7, 1 << 7, frame=kit_lockstep.SOLO_LATE + 1)
        with self.assertRaisesRegex(RuntimeError, 'attach before the fight starts'):
            s.attach()

    def test_with_another_player_or_no_slot_nothing_changed(self):
        two = (1 << 7) | (1 << 2)
        session(7, two, mask=two, frame=1).attach()                      # waiting at D, as always
        with self.assertRaises(RuntimeError):
            session(7, two, mask=two, frame=2).attach()                  # past D with another player: refused
        with self.assertRaises(RuntimeError):
            session(None, 1 << 7, local_slot=nc.NO_SLOT, self_feed=0, frame=2).attach()      # a spectator
        with self.assertRaises(RuntimeError):
            session(7, 1 << 7, self_feed=0, frame=2).attach()            # not feeding itself: it waits at D
        with self.assertRaises(RuntimeError):
            session(7, 1 << 7, state=nc.DECIDED, frame=5).attach()       # the fight is over already
        armed = session(7, 1 << 7, state=nc.ARMED, frame=0, local_slot=nc.NO_SLOT, self_feed=0)
        armed.attach()                                                   # the paused start: words written
        self.assertEqual(armed.guest.configured, [dict(local_slot=7, self_feed=1)])

    def test_the_unpaused_path_can_be_forced_only_with_the_test_hooks(self):
        em = SimpleNamespace(START_PAUSED=True, CAN_POST_KEYS=True)

        class Controller(kit_fight.FightMixin):
            pass
        c = Controller.__new__(Controller)
        old = os.environ.get('TTM_TEST_UNPAUSED_LOAD')
        os.environ['TTM_TEST_UNPAUSED_LOAD'] = '1'
        try:
            self.assertTrue(c._paused_machine_allowed(dict(emulator=em)))            # no args at all
            c.args = SimpleNamespace(test_hooks=False)
            self.assertTrue(c._paused_machine_allowed(dict(emulator=em)))            # a real session
            c.args = SimpleNamespace(test_hooks=True)
            self.assertFalse(c._paused_machine_allowed(dict(emulator=em)))
            os.environ.pop('TTM_TEST_UNPAUSED_LOAD')
            self.assertTrue(c._paused_machine_allowed(dict(emulator=em)))
        finally:
            if old is not None:
                os.environ['TTM_TEST_UNPAUSED_LOAD'] = old
            else:
                os.environ.pop('TTM_TEST_UNPAUSED_LOAD', None)


if __name__ == '__main__':
    unittest.main()
