"""Tag attacks in a match of three to five teams (feature 'tag_attacks'): the emitted coordinator of the two-team
tests, built for a team layout. The helper is a teammate by the team table (whatever its native row), the victim a
fighter of another team (same native row included); nobody of another team helps and no teammate is a victim.
Outside the team flavour, and with the feature off, every byte is the ordinary one."""
import contextlib
import struct
import unittest
from unittest.mock import patch

import battle_mode_policy as policy
import tag_team_rush as tag
import test_tag_team_rush_guest as guest
from test_tag_team_rush_guest import ACTORS, MANAGER, frame

FIVE = (2, 2, 2, 2, 2)          # team_of = 0 1 0 1 2 3 2 3 4 4
ON = policy.SQUAD_FEATURES | {'tag_attacks'}


@contextlib.contextmanager
def team_build(sizes=FIVE, features=ON):
    with patch.object(policy, 'SQUAD_FEATURES', frozenset(features)), policy.building_squads(policy.squad_layout(sizes)) as squads:
        yield squads


def machine(sizes=FIVE, players=(0,), targets=None):
    """The coordinator for these teams; every fighter but `players` is CPU driven; targets: {fighter: target}."""
    with team_build(sizes) as squads:
        count = squads.count()
        c = guest.machine(count=count, cpu=tuple(i for i in range(count) if i not in players))
    c.write(policy.SQUAD, squads.block(MANAGER, players))
    c.w(tag.participation.CONTROL+12, squads.present())
    for fighter, target in (targets or {}).items(): c.w(tag.core.TABLE+4*fighter, target)
    c.squads = squads
    return c


def rounds(c, held, n=6):
    for _ in range(n): frame(c, held)
    return c.calls


class CoordinatorTests(unittest.TestCase):
    def test_teammate_helps_against_a_fighter_of_another_team_on_the_same_row(self):
        c = machine(targets={0: 4, 2: 4})                           # fighters 0 and 2 are team 1; 4 is team 3, row 0
        self.assertEqual(rounds(c, [0]), [(0, 2, 4)])

    def test_the_victim_may_be_on_either_row(self):
        c = machine(targets={0: 5, 2: 5})
        self.assertEqual(rounds(c, [0]), [(0, 2, 5)])

    def test_the_split_pair_is_a_team_across_the_rows(self):
        c = machine(players=(8,), targets={8: 1, 9: 1})
        self.assertEqual(rounds(c, [8]), [(8, 9, 1)])
        c = machine(players=(9,), targets={8: 0, 9: 0})
        self.assertEqual(rounds(c, [9]), [(9, 8, 0)])

    def test_nobody_of_another_team_helps(self):
        # the teammate is down; fighters 4, 6 and 8 of the same native row are charged and aim at the same victim
        c = machine(targets={0: 1, 2: 1, 4: 1, 6: 1, 8: 1})
        c.w(ACTORS[2]+0x9E4, 0)
        self.assertEqual(rounds(c, [0], 10), [])
        # the teammate stands but aims elsewhere: still nobody else
        c = machine(targets={0: 1, 2: 3, 4: 1, 6: 1, 8: 1})
        self.assertEqual(rounds(c, [0], 10), [])

    def test_a_teammate_is_never_the_victim(self):
        c = machine(targets={0: 2, 2: 2})
        self.assertEqual(rounds(c, [0], 10), [])
        c = machine(players=(8,), targets={8: 9, 9: 9})             # the split pair's other half
        self.assertEqual(rounds(c, [8], 10), [])

    def test_a_team_of_one_has_no_tag_attack_and_its_meter_does_not_charge(self):
        c = machine(sizes=(1, 2, 2), players=(0,), targets={0: 1})
        frame(c)
        self.assertEqual(c.u(guest.meter(0, 'allies')), 1)
        self.assertEqual(rounds(c, [0], 8), [])

    def test_the_living_teammate_count_is_the_team_s(self):
        c = machine(sizes=(3, 3, 2, 2)); frame(c)                   # team_of from the layout, rows mixed
        for fighter in range(c.squads.count()):
            if c.squads.team_of[fighter] is None: continue
            mates = sum(1 for other in range(c.squads.count()) if c.squads.team_of[other] == c.squads.team_of[fighter])
            self.assertEqual(c.u(guest.meter(fighter, 'allies')), mates, fighter)

    def test_without_the_live_team_table_nothing_starts(self):
        for case in ('no table', 'another match'):
            with self.subTest(case=case):
                c = machine(targets={0: 4, 2: 4})
                if case == 'no table': c.write(policy.SQUAD, bytes(policy.SQUAD_END-policy.SQUAD))
                else: c.w(policy.SQUAD+policy.SQUAD_FIELDS['manager'], MANAGER+0x100)
                self.assertEqual(rounds(c, [0], 10), [])

    def test_a_cpu_teammate_initiates_with_its_ticket_like_in_two_teams(self):
        # a player's chord on fighter 2 while fighter 0 (the other player) only has to agree by its own chord
        c = machine(players=(0, 2), targets={0: 5, 2: 5})
        self.assertEqual(rounds(c, [0], 4), [])                    # a human helper must press too
        self.assertEqual(rounds(c, [0, 2], 6), [(0, 2, 5)])


class FlavourTests(unittest.TestCase):
    def emitted(self):
        import tag_rush_approach as approach
        import tag_rush_cpu as cpu
        import tag_rush_hud as hud
        import tag_rush_pause as pause
        import tag_rush_scene as scene
        return dict(gate=tag.gate_code(), buffer=tag.buffer_input_code(), tick=tag.tick_code(), begin=approach.begin_code(),
                    start=scene.start_code(), ready=cpu.ready_code(), pause=tuple(pause.pieces()), hud=hud.draw_code())

    def test_the_team_flavour_changes_the_eight_caves_and_fits_them(self):
        plain = self.emitted()
        with team_build(): teams = self.emitted()
        self.assertEqual(sorted(name for name in plain if plain[name] != teams[name]), sorted(plain))
        self.assertLessEqual(tag.TICK+len(teams['tick']), tag.BUFFER_INPUT)

    def test_with_the_feature_off_a_team_build_emits_the_ordinary_bytes(self):
        import squad_hud
        plain = self.emitted()
        with team_build(features=policy.SQUAD_FEATURES-{'tag_attacks'}):
            self.assertEqual(self.emitted(), plain)
            chips = squad_hud.draw_code()
        with team_build(): self.assertNotEqual(squad_hud.draw_code(), chips)     # the chip row follows the meter

    def test_the_team_flavour_reads_the_team_table(self):
        # lui reg, <high half> then ori reg, reg, <low half of the team_of row>: present in the team tick only
        low = (policy.SQUAD+policy.SQUAD_FIELDS['team_of']) & 0xFFFF
        table = {struct.pack('<I', 0x34000000 | (reg << 21) | (reg << 16) | low) for reg in range(8, 16)}
        words = lambda data: {data[i:i+4] for i in range(0, len(data), 4)}
        self.assertFalse(table & words(tag.tick_code()))
        with team_build(): self.assertTrue(table & words(tag.tick_code()))


class AvailabilityTests(unittest.TestCase):
    def test_a_team_match_is_admitted_and_a_free_for_all_is_not(self):
        import tag_rush_availability as availability
        settings = dict(tag_team_rush_enabled=True)
        ask = lambda: availability.preparation_reason(settings, 'ffa', policy.__file__+'-nowhere', adapter='bt3-usa')
        with policy.building_squads(None): self.assertEqual(ask(), 'Tag-team rush requires teammates.')
        with team_build(): self.assertEqual(ask(), '')
        with team_build(features=policy.SQUAD_FEATURES-{'tag_attacks'}): self.assertEqual(ask(), 'Tag-team rush requires teammates.')
        with team_build():
            self.assertEqual(availability.preparation_reason(dict(tag_team_rush_enabled=False), 'ffa', '.', adapter='bt3-usa'),
                             'Tag-team rush is disabled.')
            self.assertIn('unavailable online', availability.preparation_reason(settings, 'ffa', '.', adapter='bt3-usa', online=True))


if __name__ == '__main__':
    unittest.main()
