"""Online matches with two to five teams: spec, lobby, preparation checks, hash table, results (no game, emulator or
network peer; synthetic fixtures only).

Run: python -m unittest discover -s release_tools/online-teams-tests -p 'test_*.py'
"""
import json
import os
import random
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_RUNTIME = tempfile.mkdtemp(prefix='ttm-teams-tests-')
os.environ['TTM_KIT_RUNTIME'] = _RUNTIME            # nothing these tests write lands in the source tree
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_paths  # noqa: E402,F401
import kit_fight  # noqa: E402
import kit_lobby  # noqa: E402
import kit_lobby_console  # noqa: E402
import kit_match  # noqa: E402
import kit_postmatch  # noqa: E402
import kit_prepare  # noqa: E402
import kit_selector_cache  # noqa: E402
import kit_spec  # noqa: E402
import kit_text  # noqa: E402
import kit_verify  # noqa: E402
import netplay_finish  # noqa: E402
import netplay_state_hash  # noqa: E402

policy = kit_spec.squad_policy()

# Recorded from the kit as it was before teams (Nov 15 2026): the same two-team spec must keep this text and hash.
TWO_TEAM_SHA = 'ece71d47e29c45522046d2255d92578882ce2b0df13e3a03f9c1d0e3564eeb4d'
TWO_TEAM_TEXT = ('{"bgm":3,"disc":"bt3-usa","family":"bt3","gameplay":{},"kit":"2.4.0","mod_build":"x","mode":"teams",'
                 '"native":{"com":3,"destructible":false,"referee":1,"time":180},"schema":"ttm-online-match",'
                 '"services":{"body_change":false,"cpu_transform":true,"fusion_timer":false},"stage":6,'
                 '"tables_sha256":"abababababababababababababababababababababababababababababababab",'
                 '"teams":[[{"character":29,"costume":1,"potaras":[],"slot":0},{"character":25,"costume":0,"potaras":[],'
                 '"slot":null}],[{"character":3,"costume":2,"potaras":[],"slot":1},{"character":7,"costume":0,'
                 '"potaras":[],"slot":null},{"character":9,"costume":1,"potaras":[],"slot":5}]],"type":"versus","v":2}')


class Catalog:
    selectable = list(range(60))
    chars = {i: dict(selectable=True) for i in range(60)}
    c = dict(tables_sha256='ab' * 32)
    tested = [0]

    def costumes(self, c):
        return 4

    def name(self, c):
        return f'F{c}'

    def stage_name(self, s):
        return f'S{s}'


CATALOG = Catalog()


def room(names=('Bea', 'Cy', 'Dee')):
    rng = random.Random(7)
    lobby = kit_lobby.Lobby('Host', catalog=CATALOG, rng=rng)
    lobby.rng = rng
    return lobby, [lobby.join(name) for name in names]


def team_spec(sizes, humans=()):
    """A valid spec of three to five teams: fighters 0, 1, 2.. by team; humans = physical slots that are players."""
    layout = policy.squad_layout(tuple(sizes))
    columns = [[], []]
    counter = {}
    for i in range(10):
        team = layout.team_of[i]
        if team is None:
            continue
        counter[team] = counter.get(team, 0) + 1
        columns[i & 1].append(dict(character=10 * team + counter[team], costume=0, team=team,
                                   slot=i if i in humans else None))
    return kit_spec.make(tables_sha256='ab' * 32, mode='teams', teams=columns, stage=1, bgm=0, mod_build='x',
                         team_count=len(sizes))


@unittest.skipIf(policy is None, 'the mod modules of this tree do not know three to five teams')
class Spec(unittest.TestCase):
    def test_a_two_team_spec_is_the_text_and_hash_it_always_was(self):
        spec = kit_spec.make(tables_sha256='ab' * 32, mode='teams',
                             teams=[[(29, 1, 0), (25, 0, None)], [(3, 2, 1), (7, 0, None), (9, 1, 5)]],
                             stage=6, bgm=3, native=dict(time=180, com=3, referee=1, destructible=False),
                             gameplay={}, services=dict(cpu_transform=True), mod_build='x')
        self.assertEqual(kit_spec.canonical(spec), TWO_TEAM_TEXT)
        self.assertEqual(kit_spec.spec_sha(spec), TWO_TEAM_SHA)
        self.assertEqual(kit_spec.problems(spec, CATALOG, ('cpu_transform',)), [])
        self.assertIsNone(kit_spec.squads(spec))

    def test_three_to_five_teams_are_valid_only_where_the_layout_puts_them(self):
        for sizes in ((3, 2, 1), (2, 2, 2), (2, 2, 2, 2, 2), (4, 4, 2), (3, 3, 3, 1), (1, 1, 1), (5, 4, 1)):
            with self.subTest(sizes=sizes):
                spec = team_spec(sizes, humans=(0, 1))
                self.assertEqual(kit_spec.problems(spec, CATALOG), [])
                self.assertEqual(spec['team_count'], len(sizes))
                self.assertEqual(spec['squad_layout'], policy.SQUAD_LAYOUT)
                self.assertEqual(kit_spec.squads(spec), policy.squad_layout(sizes))
                self.assertEqual([len(m) for m in kit_spec.team_members(spec)], list(sizes))
                self.assertEqual(kit_spec.engine_mode(spec), 'teams')

    def test_what_every_peer_refuses(self):
        good = team_spec((3, 2, 1))
        def changed(edit):
            spec = json.loads(json.dumps(good))
            edit(spec)
            return kit_spec.problems(spec, CATALOG)
        self.assertTrue(changed(lambda s: s['teams'][0][0].update(team=1)))             # another team at a position
        self.assertTrue(changed(lambda s: s.update(squad_layout=policy.SQUAD_LAYOUT + 1)))   # another layout function
        self.assertTrue(changed(lambda s: s.pop('squad_layout')))
        self.assertTrue(changed(lambda s: s.pop('team_count')))                          # team fields without a count
        self.assertTrue(changed(lambda s: s['teams'][1][0].pop('team')))
        self.assertTrue(changed(lambda s: s.update(mode='ffa')))
        self.assertTrue(changed(lambda s: (s.update(type='hub', mode='ffa'), s['native'].update(time=0))))
        self.assertTrue(changed(lambda s: s.update(team_count=6)))
        self.assertTrue(changed(lambda s: s.update(team_count=2)))
        two = kit_spec.make(tables_sha256='ab' * 32, teams=[[(1, 0, None)], [(2, 0, None)]], stage=0)
        two['teams'][0][0]['team'] = 0
        self.assertTrue(kit_spec.problems(two, CATALOG))                                 # a team in a two-team spec

    def test_sizes_that_cannot_be_played(self):
        for sizes in ((5, 5, 1), (6, 1, 1), (0, 2, 2), (2, 2), (1, 1, 1, 1, 1, 1)):
            self.assertTrue(kit_spec.team_sizes_problems(list(sizes)), sizes)
        self.assertEqual(kit_spec.team_sizes_problems([3, 3, 3, 1]), [])

    def test_a_mod_without_teams_refuses_them_with_a_reason(self):
        from unittest.mock import patch
        with patch.object(kit_spec, 'squad_policy', lambda: None):
            self.assertIn('update', ' '.join(kit_spec.team_sizes_problems([2, 2, 2])))
            self.assertIn('cannot play three to five teams', ' '.join(kit_spec.problems(team_spec((2, 2, 2)), CATALOG)))
            lobby, _ = room()
            self.assertTrue(lobby.set_team_count(3, CATALOG))
            self.assertEqual(lobby.team_count(), 2)

    def test_the_title_names_every_team(self):
        self.assertEqual(kit_spec.title(team_spec((2, 1, 1)), CATALOG), 'F1 + F2 vs F11 vs F21, S1')


@unittest.skipIf(policy is None, 'the mod modules of this tree do not know three to five teams')
class Lobby(unittest.TestCase):
    def test_three_teams_and_back_to_two_lose_nobody(self):
        lobby, (b, c, d) = room()
        lobby.set_sizes([2, 2], CATALOG, lobby.rng)
        lobby.claim(1, 0, 0), lobby.claim(b, 1, 0), lobby.claim(c, 1, 1)
        self.assertEqual(lobby.set_team_count(3, CATALOG, lobby.rng), [])
        self.assertEqual((lobby.team_count(), lobby.match['mode']), (3, 'teams'))
        self.assertEqual([len(t) for t in lobby.logical()], [2, 2, 2])
        self.assertEqual(sorted(lobby.players()), [1, b, c])                    # everybody kept their fighter
        self.assertEqual(lobby.claim_team(d, 2), [])
        self.assertEqual(lobby.label_of(*lobby.slot_of(d)), (3, 1))
        self.assertEqual(lobby.notice['args'], dict(name='Dee', team=3, index=1))
        self.assertEqual(lobby.set_sizes([3, 2, 1], CATALOG, lobby.rng), [])
        self.assertEqual(sorted(lobby.players()), [1, b, c, d])
        self.assertIsNone(kit_lobby.snapshot_problem(json.loads(json.dumps(lobby.snapshot()))))
        self.assertEqual(kit_spec.problems(lobby.spec('ab' * 32), CATALOG), [])
        self.assertEqual(lobby.set_team_count(2, CATALOG, lobby.rng), [])
        self.assertEqual(sorted(lobby.players()), [1, b, c, d])                 # the player of team 3 moved over
        self.assertFalse(any('team' in f for team in lobby.match['teams'] for f in team))
        self.assertNotIn('team_count', lobby.match)
        spec = lobby.spec('ab' * 32)
        self.assertEqual(sorted(spec), sorted(json.loads(TWO_TEAM_TEXT)))        # no team key in the spec either
        self.assertFalse(any('team' in f for team in spec['teams'] for f in team))

    def test_a_guest_sees_the_hosts_lobby_exactly(self):
        lobby, (b, c, d) = room()
        lobby.set_team_count(5, CATALOG, lobby.rng)
        lobby.set_sizes([2, 2, 2, 2, 2], CATALOG, lobby.rng)
        lobby.claim_team(b, 4), lobby.claim_team(c, 4), lobby.claim_team(d, 1)
        snap = json.loads(json.dumps(lobby.snapshot()))
        guest = kit_lobby.Lobby.from_snapshot(snap)
        self.assertEqual(guest.snapshot(), snap)
        self.assertEqual(guest.logical(), lobby.logical())
        self.assertEqual(kit_lobby_console.team_members(snap['match']), kit_spec.team_members(lobby.match))
        split = policy.squad_layout((2, 2, 2, 2, 2)).split()
        self.assertEqual(split, 4)                                               # team 5 stands on both native rows
        self.assertEqual({lobby.slot_of(b)[0], lobby.slot_of(c)[0]}, {0, 1})     # its two players: one per row

    def test_two_members_claiming_the_last_free_fighter(self):
        lobby, (b, c, d) = room()
        lobby.set_team_count(3, CATALOG, lobby.rng)
        lobby.set_sizes([2, 2, 1], CATALOG, lobby.rng)
        self.assertEqual(lobby.claim_team(b, 2), [])
        self.assertEqual(lobby.claim_team(c, 2), ['team 3 has no free fighter'])
        self.assertIsNone(lobby.slot_of(c))
        self.assertEqual(lobby.claim_team(b, 2), [])                             # already there: nothing changes
        column, index = lobby.slot_of(b)
        self.assertTrue(lobby.claim(c, column, index))                           # the same fighter by hand: refused
        lobby.leave(b)                                                           # the player leaves: the seat is free
        self.assertEqual(lobby.claim_team(c, 2), [])

    def test_a_locked_fighter_is_never_given_to_a_joining_player(self):
        lobby, (b, c, d) = room()
        lobby.set_team_count(3, CATALOG, lobby.rng)
        lobby.set_sizes([2, 2, 2], CATALOG, lobby.rng)
        column, index = kit_spec.team_members(lobby.match)[1][0]
        lobby.lock(column, index)
        self.assertEqual(lobby.claim_team(b, 1), [])
        self.assertEqual(lobby.label_of(*lobby.slot_of(b)), (2, 2))

    def test_the_host_changes_sizes_under_seated_players(self):
        lobby, (b, c, d) = room()
        lobby.set_team_count(3, CATALOG, lobby.rng)
        lobby.set_sizes([3, 2, 2], CATALOG, lobby.rng)
        lobby.claim_team(b, 0), lobby.claim_team(c, 0)
        lobby.set_ready(b, True)
        self.assertEqual(lobby.set_sizes([2, 2, 2], CATALOG, lobby.rng), [])     # the CPU fighter of team 1 goes
        self.assertEqual(sorted(lobby.players()), [b, c])
        self.assertFalse(lobby.members[b]['ready'])                              # a change by the host clears Ready
        self.assertEqual(lobby.set_sizes([1, 2, 2], CATALOG, lobby.rng), [])     # no CPU left: the last player goes
        self.assertEqual(lobby.players(), [b])
        self.assertIn(c, lobby.spectators())
        self.assertTrue(lobby.set_sizes([5, 5, 1], CATALOG, lobby.rng))          # eleven fighters: refused, unchanged
        self.assertEqual([len(t) for t in lobby.logical()], [1, 2, 2])
        self.assertTrue(lobby.set_sizes([2, 2], CATALOG, lobby.rng))             # two sizes for three teams
        self.assertEqual(lobby.notice['code'], 'TTM-NET-29')

    def test_growing_past_ten_fighters_drops_cpu_fighters_first(self):
        lobby, (b, c, d) = room()
        lobby.set_sizes([5, 5], CATALOG, lobby.rng)
        for member, (team, index) in zip((1, b, c, d), ((0, 0), (0, 4), (1, 0), (1, 4))):
            lobby.claim(member, team, index)
        self.assertEqual(lobby.set_team_count(4, CATALOG, lobby.rng), [])
        sizes = [len(t) for t in lobby.logical()]
        self.assertEqual(len(sizes), 4)
        self.assertLessEqual(sum(sizes), 10)
        self.assertTrue(all(n >= 1 for n in sizes))
        self.assertEqual(sorted(lobby.players()), [1, b, c, d])                  # every player kept a fighter
        self.assertEqual(kit_spec.team_problems(lobby.match), [])

    def test_free_for_all_and_the_hub_have_no_teams(self):
        lobby, (b, c, d) = room()
        lobby.set_team_count(4, CATALOG, lobby.rng)
        lobby.claim_team(b, 3)
        self.assertEqual(lobby.set_mode('ffa', CATALOG), [])
        self.assertEqual((lobby.match['mode'], lobby.team_count()), ('ffa', 2))
        self.assertIn(b, lobby.players())
        lobby.set_mode('teams', CATALOG)
        lobby.set_team_count(3, CATALOG, lobby.rng)
        self.assertEqual(lobby.set_type('hub'), [])
        self.assertEqual((lobby.match['type'], lobby.team_count()), ('hub', 2))
        self.assertTrue(lobby.set_team_count(3, CATALOG, lobby.rng))             # the hub is free-for-all
        self.assertEqual(lobby.set_team_count(7, CATALOG), ['two to five teams can be played'])

    def test_a_dissolved_team_a_leaving_player_and_a_late_joiner(self):
        lobby, (b, c, d) = room()
        lobby.set_team_count(4, CATALOG, lobby.rng)
        self.assertEqual(lobby.set_sizes([2, 2, 2, 1], CATALOG, lobby.rng), [])
        lobby.claim_team(1, 0), lobby.claim_team(b, 3), lobby.claim_team(c, 1)
        self.assertEqual(lobby.set_sizes([2, 1, 2, 1], CATALOG, lobby.rng), [])  # team 2: its CPU goes, c stays
        self.assertEqual(lobby.label_of(*lobby.slot_of(c)), (2, 1))
        self.assertEqual(lobby.set_team_count(3, CATALOG, lobby.rng), [])        # team 4 is dissolved
        self.assertEqual([len(t) for t in lobby.logical()], [2, 2, 2])
        self.assertEqual(lobby.label_of(*lobby.slot_of(b)), (2, 2))              # its player: the smallest team
        self.assertEqual(sorted(lobby.players()), [1, b, c])
        late = lobby.join('Late')                                               # joins after all of that
        self.assertIn(late, lobby.spectators())
        snap = json.loads(json.dumps(lobby.snapshot()))
        self.assertIsNone(kit_lobby.snapshot_problem(snap))
        self.assertEqual(kit_lobby.Lobby.from_snapshot(snap).logical(), lobby.logical())
        self.assertEqual(lobby.claim_team(late, 2), [])
        column, index = lobby.slot_of(c)
        lobby.leave(c)                                                          # its fighter stays, as a CPU
        self.assertEqual([len(t) for t in lobby.logical()], [2, 2, 2])
        self.assertIsNone(lobby.match['teams'][column][index].get('owner'))
        self.assertEqual(lobby.match['teams'][column][index]['team'], 1)        # ...of the same team
        self.assertEqual(lobby.set_team_count(2, CATALOG, lobby.rng), [])
        self.assertEqual(sorted(lobby.players()), [1, b, late])                 # two columns, nobody lost
        self.assertEqual(lobby.set_team_count(3, CATALOG, lobby.rng), [])
        self.assertEqual(sorted(lobby.players()), [1, b, late])
        self.assertEqual(kit_spec.problems(lobby.spec('ab' * 32), CATALOG), [])

    def test_the_people_list_numbers_fighters_as_the_team_panels_do(self):
        lobby, (b, c, d) = room()
        lobby.set_team_count(3, CATALOG, lobby.rng)
        lobby.set_sizes([3, 2, 1], CATALOG, lobby.rng)
        lobby.claim_team(b, 2), lobby.claim_team(c, 1)
        match = json.loads(json.dumps(lobby.snapshot()))['match']
        for member in (b, c):
            team, index = lobby.label_of(*lobby.slot_of(member))
            self.assertEqual(kit_lobby_console.label_of(match, *kit_lobby_console.slot_of(match, member)),
                             (team - 1, index - 1))
        self.assertEqual(kit_lobby_console.slot_of(match, b), (1, 2))            # native column 2, third
        self.assertEqual(kit_lobby_console.label_of(match, 1, 2), (2, 0))        # = team 3, first fighter
        lobby.set_team_count(2, CATALOG, lobby.rng)
        match = json.loads(json.dumps(lobby.snapshot()))['match']
        at = kit_lobby_console.slot_of(match, c)
        self.assertEqual(kit_lobby_console.label_of(match, *at), at)             # two teams: the columns

    def test_the_saved_rules_never_carry_teams(self):
        lobby, _ = room()
        lobby.set_team_count(3, CATALOG, lobby.rng)
        self.assertNotIn('team_count', json.dumps(lobby.rules()))

    def test_a_snapshot_whose_teams_are_not_where_the_layout_puts_them_is_refused(self):
        lobby, _ = room()
        lobby.set_team_count(3, CATALOG, lobby.rng)
        snap = json.loads(json.dumps(lobby.snapshot()))
        snap['match']['teams'][0][0]['team'] = 2
        self.assertEqual(kit_lobby.snapshot_problem(snap), 'team layout')


class Console(unittest.TestCase):
    def state(self, lobby):
        return dict(lobby=json.loads(json.dumps(lobby.snapshot())), me=1, phase='lobby')

    @unittest.skipIf(policy is None, 'no teams in this tree')
    def test_commands_name_teams_as_the_players_see_them(self):
        lobby, (b, c, d) = room()
        lobby.set_team_count(3, CATALOG, lobby.rng)
        lobby.set_sizes([3, 2, 1], CATALOG, lobby.rng)
        state = self.state(lobby)
        members = kit_spec.team_members(lobby.match)
        self.assertEqual(kit_lobby_console.command('teams 4', state), ('teams', dict(count=4)))
        self.assertEqual(kit_lobby_console.command('team 3', state), ('claim_team', dict(team=2)))
        self.assertEqual(kit_lobby_console.command('sizes 2 2 2', state), ('sizes', dict(sizes=[2, 2, 2])))
        column, index = members[2][0]
        self.assertEqual(kit_lobby_console.command('claim 3 1', state), ('claim', dict(team=column, index=index)))
        column, index = members[0][2]
        self.assertEqual(kit_lobby_console.command('fighter 1 3 5:2', state),
                         ('fighter', dict(team=column, index=index, character=5, costume=1)))
        with self.assertRaises(ValueError):
            kit_lobby_console.command('claim 3 2', state)                        # team 3 has one fighter
        facts = kit_lobby_console.facts(dict(state, me=1))
        self.assertEqual((facts.teams, facts.team_sizes, facts.my_team), (3, [3, 2, 1], None))
        lobby.claim_team(1, 1)
        self.assertEqual(kit_lobby_console.facts(self.state(lobby)).my_team, 1)

    def test_two_team_commands_are_what_they_were(self):
        lobby, _ = room()
        lobby.set_sizes([2, 3], CATALOG, lobby.rng)
        state = self.state(lobby)
        self.assertEqual(kit_lobby_console.command('claim 2 3', state), ('claim', dict(team=1, index=2)))
        self.assertEqual(kit_lobby_console.command('sizes 2 3', state), ('sizes', dict(sizes=[2, 3])))
        self.assertEqual(kit_lobby_console.facts(state).team_sizes, [2, 3])

    def test_every_new_text_has_both_languages(self):
        for key in ('room.mode.team_battle', 'room.teams', 'room.teams_why', 'room.join_team', 'room.my_team',
                    'results.no_team', 'rule.teams'):
            self.assertTrue(kit_text.TEXT[key]['en'] and kit_text.TEXT[key]['es'], key)
        self.assertNotIn('room.mode.three', kit_text.TEXT)


class FakeRam(bytearray):
    def __init__(self):
        super().__init__(0x0712F300)


def installed(sizes, seats=(0,), manager=0x00400000):
    """A RAM image holding the mode block and the team table the mod installs for these sizes."""
    layout = policy.squad_layout(tuple(sizes))
    ram = FakeRam()
    struct.pack_into('<4I', ram, policy.CONTROL, policy.MAGIC, manager, layout.count(), policy.FFA)
    ram[policy.SQUAD:policy.SQUAD_END] = layout.block(manager, seats)
    return ram, layout


@unittest.skipIf(policy is None, 'the mod modules of this tree do not know three to five teams')
class PreparedMatch(unittest.TestCase):
    def test_the_team_table_must_be_the_rooms_and_gets_the_rooms_players(self):
        spec = team_spec((3, 2, 1), humans=(1, 5))
        ram, layout = installed((3, 2, 1))
        problems = []
        blocks = kit_prepare.squad_blocks(ram, spec, {1, 5}, problems)
        self.assertEqual(problems, [])
        self.assertEqual(blocks, [(policy.SQUAD + policy.SQUAD_FIELDS['humans'],
                                   struct.pack('<I', (1 << 1) | (1 << 5)))])      # that one word, nothing else
        self.assertEqual(layout.block(0x00400000, (1, 5))[policy.SQUAD_FIELDS['humans']:][:4], blocks[0][1])
        for address, data in blocks:
            ram[address:address + len(data)] = data
        self.assertEqual(kit_prepare.squad_blocks(ram, spec, {1, 5}, problems), [])     # nothing left to write

    def test_another_layout_no_table_or_another_engine_is_refused(self):
        spec = team_spec((3, 2, 1))
        for ram in (installed((2, 2, 2))[0], FakeRam()):
            problems = []
            self.assertEqual(kit_prepare.squad_blocks(ram, spec, set(), problems), [])
            self.assertEqual(len(problems), 1)
        ram, _ = installed((3, 2, 1))
        struct.pack_into('<I', ram, policy.CONTROL + 12, policy.TEAMS)
        problems = []
        kit_prepare.squad_blocks(ram, spec, set(), problems)
        self.assertIn('free-for-all engine', problems[0])

    def test_a_two_team_match_may_not_hold_a_team_table(self):
        two = kit_spec.make(tables_sha256='ab' * 32, teams=[[(1, 0, None)], [(2, 0, None)]], stage=0)
        problems = []
        self.assertEqual(kit_prepare.squad_blocks(FakeRam(), two, set(), problems), [])
        self.assertEqual(problems, [])
        kit_prepare.squad_blocks(installed((2, 2, 2))[0], two, set(), problems)
        self.assertEqual(problems, ['a team table is installed in a match without teams'])

    def test_the_private_watcher_must_report_exactly_the_teams(self):
        import native_mode_menu as menu
        choice = menu.SELECTIONS.index(('teams', 1))
        status = dict(battle_mode='teams', humans=1,
                      native_mode_receipt=dict(epoch=4, choice=choice, custom=True, squads=[3, 2, 1]))
        layout = policy.squad_layout((3, 2, 1))
        self.assertTrue(kit_selector_cache.mode_receipt(status, 'teams', after=3, squads=layout))
        self.assertFalse(kit_selector_cache.mode_receipt(status, 'teams', after=3))             # a left-over setup
        self.assertFalse(kit_selector_cache.mode_receipt(status, 'teams', after=3,
                                                         squads=policy.squad_layout((2, 2, 2))))
        plain = dict(status, native_mode_receipt=dict(epoch=4, choice=choice, custom=True))     # an older watcher
        self.assertTrue(kit_selector_cache.mode_receipt(plain, 'teams', after=3))
        self.assertFalse(kit_selector_cache.mode_receipt(plain, 'teams', after=3, squads=layout))

    def test_the_receipt_is_the_mods_own_and_only_for_a_team_battle(self):
        import native_mode_menu as menu
        import squad_setup
        written = {}
        client = SimpleNamespace(write_u32=lambda a, v: written.__setitem__(a, struct.pack('<I', v)),
                                 write=lambda a, d: written.__setitem__(a, bytes(d)))
        layout = policy.squad_layout((2, 2, 2, 2, 2))
        kit_selector_cache.publish_squads(client, 'teams', layout)
        self.assertEqual(written[menu.CONTROL + squad_setup.VALID], struct.pack('<I', 1))
        self.assertEqual(written[menu.CONTROL + squad_setup.ROWS], bytes([5, 5, 5, 0]))
        self.assertEqual(written[menu.CONTROL + squad_setup.TEAM_OF][:10], bytes(layout.team_of[:10]))
        written.clear()
        kit_selector_cache.publish_squads(client, 'teams', None)
        self.assertEqual(written, {})
        with self.assertRaises(ValueError):
            kit_selector_cache.publish_squads(client, 'ffa', layout)

    def test_the_private_patch_reports_the_team_sizes(self):
        rows = kit_prepare.patches(29221)['game/tools/autopilot.py']
        text = next(new for old, new in rows if 'native_mode_receipt' in new)
        self.assertIn("squads=(list(self.squads.sizes())", text)

    def test_the_ko_shortcut_keeps_one_team_healthy(self):
        spec = team_spec((2, 2, 2))
        ram = bytearray(0x200000)
        actors = []
        team_of = policy.squad_layout((2, 2, 2)).team_of
        present = [i for i in range(10) if team_of[i] is not None]       # 2 + 4 on the two rows: seats 4, 6 absent
        for i in present:
            actor = 0x100000 + i * 0x2000
            struct.pack_into('<I', ram, actor + kit_prepare.HP_SLOT, 0)
            struct.pack_into('<I', ram, actor + kit_prepare.HP_ROW, 40000)
            actors.append(dict(index=i, actor=actor))
        for keep in (0, 2):
            blocks = dict(kit_prepare.test_ko_blocks(ram, actors, 8, spec, keep))
            health = {a['index']: struct.unpack('<I', blocks[a['actor'] + kit_prepare.HP_ROW])[0]
                      if a['actor'] + kit_prepare.HP_ROW in blocks else 40000 for a in actors}
            self.assertEqual({i for i, hp in health.items() if hp == 40000},
                             {i for i in present if team_of[i] == keep})
            self.assertEqual(sorted(hp for hp in health.values() if hp != 40000), [1, 1, 5000, 5000])
        two = kit_spec.make(tables_sha256='ab' * 32, teams=[[(1, 0, None)] * 3, [(2, 0, None)] * 3], stage=0)
        self.assertEqual({a for a, _ in kit_prepare.test_ko_blocks(ram, actors, 8, two)},
                         {a['actor'] + kit_prepare.HP_ROW for a in actors if a['index'] & 1})   # two teams: as before


@unittest.skipIf(policy is None, 'the mod modules of this tree do not know three to five teams')
class HashAndWords(unittest.TestCase):
    def test_only_a_team_match_gets_the_team_rows(self):
        plain, plain_sha = kit_match.current_table()
        again, again_sha = kit_match.current_table(kit_spec.make(tables_sha256='x', teams=[[(1, 0, None)],
                                                                                       [(2, 0, None)]], stage=0))
        self.assertEqual((plain, plain_sha), (again, again_sha))
        teams, teams_sha = kit_match.current_table(team_spec((2, 2, 2)))
        rows = netplay_state_hash.squad_rows()
        import netplay_core as nc
        import netplay_view as nv
        built = netplay_state_hash.table_bytes(rows=nc.table_rows('lean', list(nv.hash_rows())))
        self.assertEqual(teams, built[:-16] + netplay_state_hash.table_bytes(rows=rows))   # the same rows, then the team rows
        self.assertNotEqual(teams_sha, plain_sha)
        self.assertEqual(kit_match.core_options(1)['extra_rows'], kit_match.core_options(1, spec=None)['extra_rows'])
        self.assertEqual(kit_match.core_options(1, spec=team_spec((2, 2, 2)))['extra_rows'][-len(rows):], rows)

    def test_the_rows_cover_the_table_through_the_winner_and_the_two_mode_words(self):
        rows = netplay_state_hash.squad_rows()
        covered = set()
        for kind, cls, address, offset, words, _ in rows:
            self.assertEqual((kind, cls, offset), (netplay_state_hash.DIRECT, 6, 0))
            covered |= {address + 4 * i for i in range(words)}
        fields = policy.SQUAD_FIELDS
        self.assertEqual({a for a in covered if policy.SQUAD <= a < policy.SQUAD_END},
                         set(range(policy.SQUAD, policy.SQUAD + fields['winner'] + 4, 4)))
        self.assertNotIn(policy.SQUAD + fields['colors'], covered)
        self.assertIn(policy.CONTROL + policy.FIELDS['mode'], covered)
        self.assertIn(policy.CONTROL + policy.FIELDS['winner'], covered)

    def words(self, spec, table):
        """The verification words of a match as far as the team check reads them."""
        sides = [dict(count=len(team)) for team in spec['teams']]
        return dict(squads=table, _sides=sides)

    def table_of(self, spec):
        layout = kit_spec.squads(spec)
        block = layout.block(0x400000, tuple(s for s, _, _ in kit_spec.humans(spec)))
        return dict(teams=struct.unpack_from('<I', block, 8)[0], count=struct.unpack_from('<I', block, 12)[0],
                    team_of=list(block[16:28]), layout=struct.unpack_from('<I', block, 28)[0],
                    members=list(struct.unpack_from('<5I', block, 32)), humans=struct.unpack_from('<I', block, 52)[0])

    def test_the_words_of_the_mods_own_block_are_what_the_spec_expects(self):
        from unittest.mock import patch
        for sizes, humans in (((3, 2, 1), (0, 5)), ((2, 2, 2, 2, 2), (8, 9)), ((4, 4, 2), ())):
            spec = team_spec(sizes, humans=humans)
            table = self.table_of(spec)
            ram = bytearray(0x0712F200)
            ram[policy.SQUAD:policy.SQUAD_END] = kit_spec.squads(spec).block(0x400000, humans)
            read = dict(teams=kit_verify._u(ram, policy.SQUAD + 8), count=kit_verify._u(ram, policy.SQUAD + 12),
                        team_of=list(ram[policy.SQUAD + 16:policy.SQUAD + 28]), layout=kit_verify._u(ram, policy.SQUAD + 28),
                        members=list(struct.unpack_from('<5I', ram, policy.SQUAD + 32)),
                        humans=kit_verify._u(ram, policy.SQUAD + 52))
            self.assertEqual(read, table)
            self.assertEqual((kit_verify.SQUAD, kit_verify.SQUAD_MAGIC), (policy.SQUAD, policy.SQUAD_MAGIC))
            # the check itself, isolated from the rest of the words
            want_of = [kit_verify.ABSENT] * 12
            for i, f in kit_spec.placed(spec):
                want_of[i] = f['team']
            self.assertEqual(table['team_of'], want_of)
            self.assertEqual(table['humans'], kit_spec.slot_mask(spec))
            self.assertEqual(table['count'], kit_verify.engine_count(spec))

    def test_unequal_columns_end_like_a_free_for_all(self):
        import netplay_view as nv
        spec = team_spec((3, 1, 1))                                               # three on one row, two on the other
        self.assertNotEqual(len(spec['teams'][0]), len(spec['teams'][1]))
        site = nv.natives().render_site
        ram = bytearray(0x08000000)
        view = [dict(address=site, data_hex=struct.pack('<I', nv.jal(nv.SWAP)).hex())]
        control = next(b for b in netplay_finish.blocks(ram, spec, view) if b['address'] == netplay_finish.CONTROL)
        self.assertEqual(struct.unpack('<4I', bytes.fromhex(control['data_hex']))[3], 0)
        two = kit_spec.make(tables_sha256='x', teams=[[(1, 0, None)] * 3, [(2, 0, None)] * 2], stage=0)
        view = [dict(address=site, data_hex=struct.pack('<I', nv.jal(nv.SWAP)).hex())]
        control = next(b for b in netplay_finish.blocks(ram, two, view) if b['address'] == netplay_finish.CONTROL)
        self.assertEqual(struct.unpack('<4I', bytes.fromhex(control['data_hex']))[3], 1)


@unittest.skipIf(policy is None, 'the mod modules of this tree do not know three to five teams')
class Flavour(unittest.TestCase):
    def test_everything_inside_is_built_for_the_specs_teams(self):
        spec = team_spec((2, 2, 2))
        self.assertIsNone(policy.emitted_squads())
        with kit_spec.flavour(spec):
            self.assertEqual(policy.emitted_squads(), policy.squad_layout((2, 2, 2)))
            with kit_spec.flavour(None):                                         # (the same thread may nest)
                self.assertIsNone(policy.emitted_squads())
            self.assertEqual(policy.emitted_squads(), policy.squad_layout((2, 2, 2)))
        self.assertIsNone(policy.emitted_squads())

    def test_another_thread_waits_instead_of_building_in_the_wrong_flavour(self):
        spec = team_spec((3, 2, 1))
        seen = []
        inside, release = threading.Event(), threading.Event()

        def squads_match():
            with kit_spec.flavour(spec):
                inside.set()
                release.wait(5)

        def plain_match():
            with kit_spec.flavour({}):
                seen.append(policy.emitted_squads())
        first = threading.Thread(target=squads_match)
        first.start()
        inside.wait(5)
        second = threading.Thread(target=plain_match)
        second.start()
        second.join(0.3)
        self.assertEqual(seen, [])                                               # it waits for the other scope
        release.set()
        first.join(5), second.join(5)
        self.assertEqual(seen, [None])

    def test_the_takeover_prompt_code_differs_with_teams(self):
        self.assertNotEqual(kit_spec.fixup_code(team_spec((2, 2, 2))), kit_spec.fixup_code({}))
        self.assertEqual(kit_spec.fixup_code({}), kit_spec.fixup_code(None))


class Results(unittest.TestCase):
    def test_the_result_line(self):
        line = kit_postmatch.result_line
        self.assertEqual(line('ko', 1), 'Result: team 1 won by KO.')
        self.assertEqual(line('time', 2), 'Result: team 2 won on time.')
        self.assertEqual(line('ko', 2, 5, 5), 'Result: team 5 won by KO (5 teams).')
        self.assertEqual(line('time', 1, 3, None),
                         'Result: time is up with 3 teams, no team was the last one standing.')
        self.assertEqual(line('nocontest', 0, 3, None, 'host_closed'), 'Result: no contest (host_closed).')

    def test_a_guest_says_the_hosts_result_once(self):
        class Guest(kit_fight.FightMixin):
            pass
        g = Guest.__new__(Guest)
        g.role, g.phase, g.results, g.session, g.dirty, g.lines = 'guest', 'results', {'mine': {'x': 1}}, None, False, []
        g.say = g.lines.append
        message = dict(type='RESULT', epoch=4, winner=2, how='time', frame=5400, teams=3, team=3, nocontest=None)
        g.msg_RESULT(1, message)
        g.msg_RESULT(1, dict(message))                                        # sent again: said once
        self.assertEqual(g.lines, ['Result: team 3 won on time (3 teams).'])
        self.assertEqual((g.results['team'], g.results['mine']), (3, {'x': 1}))
        g.msg_RESULT(1, dict(message, epoch=5, how='ko', winner=1, team=None, teams=None))
        self.assertEqual(g.lines[-1], 'Result: team 1 won by KO.')
        host = Guest.__new__(Guest)
        host.role, host.lines = 'host', []
        host.say = host.lines.append
        host.msg_RESULT(2, message)                                           # only a guest listens
        self.assertEqual(host.lines, [])

    def test_the_winning_team_is_read_from_the_team_table(self):
        def link(value):
            return SimpleNamespace(read_ranges=lambda ranges: [struct.pack('<I', value)] if
                                   ranges == [(kit_postmatch.SQUAD_WINNER_TEAM, 4)] else None)
        self.assertEqual(kit_postmatch.read_team(link(2)), 3)
        self.assertIsNone(kit_postmatch.read_team(link(0xFFFFFFFF)))
        if policy is not None:
            self.assertEqual(kit_postmatch.SQUAD_WINNER_TEAM, policy.SQUAD + policy.SQUAD_FIELDS['winner_team'])


class SoloStart(unittest.TestCase):
    """A match loaded into the running game (every start since the game opens in the lobby, and every Retry)
    stays paused until its session attached. With ONE player who is this PC's own, nobody else's input holds
    the game at its first frames: resumed by the load it ran on, and the attach was refused for ever
    (TTM-NET-22 after 60 s; found with a four-team room of one player and a spectator)."""

    def controller(self, plan, resumes=True):
        link = SimpleNamespace(pid=7, status='running', loads=0)
        link.w32 = lambda address, value: None
        link.u32 = lambda address: 0                                  # the load finished
        link.load_state = lambda slot: setattr(link, 'loads', link.loads + 1)

        def to(status, ok=True):
            def press(target):
                if ok:
                    target.status = status
                return ok
            return press
        em = SimpleNamespace(pid=7, pine_owner=lambda: 7, ensure_paused=to('paused'),
                             ensure_running=to('running', resumes), stop=lambda: None)

        class Controller(kit_fight.FightMixin):
            pass
        c = Controller.__new__(Controller)
        c.link, c.emulator, c.load_lock, c.run_dir = link, em, threading.RLock(), '.'
        c.resume_after_attach = None
        c.failed, c.ended = [], []
        c.fail = lambda error: c.failed.append(error.code)
        c.end_fight = lambda why, mine=False: c.ended.append(why)
        c._check_load_current = lambda request: None
        c._apply_load_plan = lambda request, record, link, pid: None
        record = dict(plan=plan, epoch=1, sha='s', path='p', request=dict(emulator=em, epoch=1))
        return c, record

    def test_the_guarded_load_stays_paused_until_the_session_attached(self):
        c, record = self.controller(plan=dict(sha='s'))
        with patch.object(kit_fight.kit_match, 'sha256_file', return_value='s'):
            c.pine_load(record)
        self.assertEqual((c.link.loads, c.link.status), (1, 'paused'))
        self.assertIs(c.resume_after_attach, c.emulator)
        c.resume_loaded_game()                                        # what tick_fight does after attach()
        self.assertEqual(c.link.status, 'running')
        self.assertIsNone(c.resume_after_attach)
        c.link.status = 'paused'
        c.resume_loaded_game()                                        # nothing pending: nothing is pressed
        self.assertEqual((c.link.status, c.failed), ('paused', []))

    def test_a_copy_loaded_without_the_guarded_plan_runs_at_once_as_before(self):
        c, record = self.controller(plan=None)
        c.pine_load(record)
        self.assertEqual((c.link.loads, c.link.status), (1, 'running'))
        self.assertIsNone(c.resume_after_attach)

    def test_a_game_that_does_not_resume_ends_the_fight_with_the_reason(self):
        c, record = self.controller(plan=dict(sha='s'), resumes=False)
        with patch.object(kit_fight.kit_match, 'sha256_file', return_value='s'):
            c.pine_load(record)
        c.resume_loaded_game()
        self.assertEqual((c.failed, c.ended), (['TTM-NET-22'], ['error']))

    def test_the_attach_is_tried_before_the_game_runs(self):
        import inspect
        source = inspect.getsource(kit_fight.FightMixin.tick_fight)
        attach, resume = source.index('s.attach()'), source.index('self.resume_loaded_game()')
        self.assertLess(attach, resume)
        self.assertLess(resume, source.index('self.start_missing_cpus()'))
        self.assertIn('did not start ({error})', source)                 # the refusal's reason is shown


if __name__ == '__main__':
    unittest.main()
