"""Online sync after the multi-team stages 3d (teammate revive) and 3e (tag attacks): the hash rows of teammate
revive in a room of three to five teams, the kit's synced copies, tag attacks offline only (no game, emulator or
network peer).

Run: python -m unittest discover -s release_tools/online-teams-tests -p 'test_*.py'
"""
import hashlib
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('TTM_KIT_RUNTIME', tempfile.mkdtemp(prefix='ttm-sync-tests-'))
NETPLAY = ROOT / 'bt3-multifighter/online/netplay'
TOOLS = ROOT / 'bt3-multifighter/tools'
sys.path.insert(0, str(NETPLAY))
import kit_paths  # noqa: E402,F401
import kit_fight  # noqa: E402
import kit_match  # noqa: E402
import kit_settings  # noqa: E402
import kit_spec  # noqa: E402
import netplay_state_hash  # noqa: E402

policy = kit_spec.squad_policy()
SYNCED = ('battle_mode_policy', 'battle_modes', 'camera_successor', 'ffa_targeting', 'fresh_team_combat',
          'guest_healthbars', 'lockon_queue', 'team_six_ai', 'quad_lifecycle', 'netplay_state_hash',
          'selected_team_capture')


def spec(teams=3, **gameplay):
    """Only what the row choice reads."""
    return dict(mode='teams', gameplay=gameplay, **({'team_count': teams} if teams else {}))


class ReviveRows(unittest.TestCase):
    def test_the_rows_are_the_revive_blocks_a_second_pc_must_agree_on(self):
        import teammate_revive as revive
        rows = netplay_state_hash.revive_rows()
        self.assertEqual(len(rows), 1 + 2 * 10)
        kind, cls, address, offset, words, _ = rows[0]
        self.assertEqual((kind, cls, address, offset, words), (netplay_state_hash.DIRECT, 6, revive.CONTROL, 0, 20))
        # the control row stops before each PC's own ring display settings and the drawing clock
        self.assertEqual(address + 4 * words, revive.CONTROL + 0x50)
        self.assertLess(address + 4 * words, revive.CONTROL + 96)
        F = revive.F
        self.assertEqual([F[k] for k in ('target', 'progress', 'hp', 'lock_target')], [4, 8, 12, 16])
        self.assertEqual([F[k] for k in ('recovering', 'recovery_ticks', 'revives', 'insufficient')], [44, 48, 52, 56])
        for fighter in range(10):
            base = revive.ROWS + revive.STRIDE * fighter
            first, second = rows[1 + 2 * fighter], rows[2 + 2 * fighter]
            self.assertEqual(first[:5], (netplay_state_hash.DIRECT, 6, base + 4, 0, 4))
            self.assertEqual(second[:5], (netplay_state_hash.DIRECT, 6, base + 44, 0, 4))
        covered = {a + 4 * i for _, _, a, _, n, _ in rows for i in range(n)}
        self.assertFalse(any(revive.ROWS + revive.STRIDE * f + off in covered for f in range(10)
                             for off in (0, 20, 24, 28, 32, 36, 40)))          # actor pointer and position floats
        self.assertNotIn(revive.CONTROL + 96, covered)

    @unittest.skipIf(policy is None, 'the mod modules of this tree do not know three to five teams')
    def test_only_a_team_room_with_revive_gets_them(self):
        team = len(netplay_state_hash.squad_rows())
        self.assertEqual(len(kit_match.squad_rows(spec(3))), team)                          # revive off (default)
        self.assertEqual(len(kit_match.squad_rows(spec(5, revive_enabled=False))), team)
        self.assertEqual(len(kit_match.squad_rows(spec(3, revive_enabled=True))), team + 21)
        self.assertEqual(kit_match.squad_rows(spec(3, revive_enabled=True))[:team], list(netplay_state_hash.squad_rows()))
        self.assertEqual(kit_match.squad_rows(spec(0, revive_enabled=True)), [])            # two teams: as it was
        self.assertEqual(kit_match.squad_rows(dict(mode='ffa', gameplay=dict(revive_enabled=True))), [])
        self.assertEqual(kit_match.squad_rows(None), [])
        self.assertFalse(kit_settings.default_gameplay()['revive_enabled'])
        self.assertTrue(kit_match.revive_on(spec(3, revive_enabled=True)))
        self.assertFalse(kit_match.revive_on({}))

    @unittest.skipIf(policy is None, 'no teams in this tree')
    def test_the_table_of_such_a_match_is_built_and_differs_only_by_its_rows(self):
        off, _ = kit_match.current_table(spec(3))
        on, _ = kit_match.current_table(spec(3, revive_enabled=True))
        self.assertGreater(len(on), len(off))
        self.assertEqual(kit_match.current_table(spec(0, revive_enabled=True)), kit_match.current_table(spec(0)))

    def test_a_tree_without_the_rows_cannot_play_teams(self):
        source = inspect.getsource(kit_spec.squad_policy)
        self.assertIn("'revive_rows'", source)
        self.assertIn("'squad_rows'", source)


class Copies(unittest.TestCase):
    def test_the_synced_kit_copies_are_the_tools_files(self):
        for name in SYNCED:
            copy, tools = NETPLAY / 'modtools' / (name + '.py'), TOOLS / (name + '.py')
            with self.subTest(module=name):
                self.assertEqual(hashlib.sha256(copy.read_bytes()).hexdigest(),
                                 hashlib.sha256(tools.read_bytes()).hexdigest())

    def test_the_kit_carries_no_copy_of_the_team_hud_revive_or_tag_modules(self):
        for name in ('squad_hud', 'teammate_revive', 'teammate_revive_ring', 'tag_team_rush', 'tag_rush_scene',
                     'tag_rush_availability'):
            self.assertFalse((NETPLAY / 'modtools' / (name + '.py')).exists(), name)


class Fusion(unittest.TestCase):
    """Stage 3f: fusion between teammates in a match of three to five teams, BT3 discs only."""

    def features(self, path):
        import re
        text = Path(path).read_text(encoding='utf-8')
        found = re.search(r'^SQUAD_FEATURES\s*=\s*frozenset\(\{([^}]*)\}\)', text, re.M)
        self.assertIsNotNone(found, path)
        return set(re.findall(r"'(\w+)'", found.group(1)))

    def test_the_kits_copy_is_the_bt3_module_with_the_feature(self):
        kit = self.features(NETPLAY / 'modtools/battle_mode_policy.py')
        self.assertEqual(kit, self.features(TOOLS / 'battle_mode_policy.py'))
        self.assertIn('fusion', kit)
        for name in ('revive', 'timeover', 'hud', 'takeover', 'successor'):
            self.assertIn(name, kit)

    def test_the_bt4_tree_keeps_its_own_module_without_it(self):
        bt4 = ROOT / 'bt4-multifighter/tools/battle_mode_policy.py'
        if not bt4.is_file():
            self.skipTest('no BT4 tree next to this one')
        self.assertNotIn('fusion', self.features(bt4))
        # an installation runs its own game/tools copy: it comes before the kit's modtools on the path
        import kit_adapter
        order = inspect.getsource(kit_adapter.bootstrap)
        self.assertIn('for directory in (paths.MODTOOLS, root, tool_dir, paths.NETPLAY)', order)

    def test_no_row_was_needed_and_the_hook_is_a_test_hook(self):
        source = inspect.getsource(kit_fight.FightMixin.cmd_test_fusion)
        self.assertIn('if not self.args.test_hooks or self.link is None', source)
        self.assertIn("if self.role == 'host' and self.session is not None", source)
        self.assertIn('self.session.schedule(writes)', source)
        self.assertNotIn('write_ranges', source)
        self.assertNotIn('.w32(', source)
        rows = netplay_state_hash.squad_rows() + netplay_state_hash.revive_rows()
        self.assertEqual(len(rows), 3 + 21)                       # unchanged by the fusion stage


class TagAttacks(unittest.TestCase):
    def test_they_stay_off_in_the_hosts_copy_and_have_no_rows(self):
        self.assertIs(kit_settings.FORCED['tag_team_rush_enabled'], False)
        rows = netplay_state_hash.squad_rows() + netplay_state_hash.revive_rows()
        for _, _, address, _, words, _ in rows:
            self.assertFalse(0x06D00000 <= address < 0x06D80000, hex(address))             # the tag reservation
            self.assertFalse(0x06D00000 <= address + 4 * words - 1 < 0x06D80000)


class Hook(unittest.TestCase):
    def test_the_revive_set_up_is_a_test_hook_of_the_host_and_only_schedules_data(self):
        source = inspect.getsource(kit_fight.FightMixin.cmd_test_revive)
        self.assertIn("if not self.args.test_hooks or self.role != 'host'", source)
        self.assertIn('self.session.schedule(writes)', source)
        self.assertNotIn('write_ranges', source)
        self.assertNotIn('.w32(', source)


if __name__ == '__main__':
    unittest.main()
