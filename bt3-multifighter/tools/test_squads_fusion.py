"""Fusion in a match of three to five teams (feature 'fusion'): the native partner search only ever sees fighters
of the owner's own team, never a player's fighter, and nothing while the team table is not live; the free-for-all
build keeps the two fusion entries instead of answering "no"; a fighter consumed by a fusion is left out of the
time-over share. Outside the team flavour, and with the feature off, every byte is the ordinary one."""
import contextlib
import struct
import unittest
from unittest.mock import patch

import battle_mode_policy as policy
import battle_modes
import fresh_team_combat as core
import fusion_partner_lifecycle as fusion
import guest_killfeed as feed
import team_participation as part
import test_fusion_partner_lifecycle as lifecycle
from native_map import GPO
from test_ai_shadow import GP
from test_squads import MANAGER, WideMips

FIVE = (2, 2, 2, 2, 2)          # team_of = 0 1 0 1 2 3 2 3 4 4: native row 0 holds fighters 0, 2 (team 0), 4 (team 2)
ON = policy.SQUAD_FEATURES | {'fusion'}
OFF = policy.SQUAD_FEATURES - {'fusion'}
STUB = struct.pack('<2I', 0x03E00008, 0x0000102D)


@contextlib.contextmanager
def team_build(sizes=FIVE, features=ON):
    with patch.object(policy, 'SQUAD_FEATURES', frozenset(features)), policy.building_squads(policy.squad_layout(sizes)) as squads:
        yield squads


def world(features=ON, table=True, cpu=(2, 4)):
    """The two-team lifecycle machine (leader 0 with row mates 2 and 4), built for five teams of two."""
    with team_build(features=features) as squads:
        c = lifecycle.machine()
    if table: c.write(policy.SQUAD, squads.block(c.manager, ()))
    for i, actor in enumerate(c.actors): c.w(actor+0x1278, 1 if i in cpu else 0)
    return c


def mirrored(c, slot):
    row = c.source+0x9A4+164*slot
    return c.u(row+8), c.u(row+64)


class PartnerSearch(unittest.TestCase):
    def test_only_a_fighter_of_the_owners_team_is_offered(self):
        c = world(); c.run(fusion.SYNC)
        self.assertEqual(mirrored(c, 1), (1, 12000))        # fighter 2: the leader's teammate
        self.assertEqual(mirrored(c, 2), (0, 0))            # fighter 4: same native row, another team

    def test_the_ordinary_build_offers_every_row_mate(self):
        c = lifecycle.machine()
        for i, actor in enumerate(c.actors): c.w(actor+0x1278, 1 if i in (2, 4) else 0)
        c.run(fusion.SYNC)
        self.assertEqual(mirrored(c, 1), (1, 12000)); self.assertEqual(mirrored(c, 2), (1, 14000))

    def test_a_players_fighter_is_never_offered(self):
        c = world(cpu=(4,)); c.run(fusion.SYNC)             # fighter 2 belongs to a player
        self.assertEqual(mirrored(c, 1), (0, 0)); self.assertEqual(mirrored(c, 2), (0, 0))

    def test_nothing_is_offered_while_the_team_table_is_not_live(self):
        c = world(table=False); c.run(fusion.SYNC)
        self.assertEqual(mirrored(c, 1), (0, 0)); self.assertEqual(mirrored(c, 2), (0, 0))
        c = world(); c.w(policy.SQUAD+policy.SQUAD_FIELDS['manager'], c.manager+4); c.run(fusion.SYNC)
        self.assertEqual(mirrored(c, 1), (0, 0))

    def test_registers_survive_and_the_other_side_is_untouched(self):
        c = world(); before = c.read(c.actors[1], 0x1600); saved = c.r.copy(); c.run(fusion.SYNC)
        for i, value in enumerate(saved):
            if i != 2: self.assertEqual(c.r[i], value, i)
        self.assertEqual(c.read(c.actors[1], 0x1600), before)


class Flavour(unittest.TestCase):
    def test_the_ordinary_build_and_the_feature_off_are_byte_identical(self):
        plain = fusion.sync_code()
        with patch.object(policy, 'SQUAD_FEATURES', frozenset(ON)): self.assertEqual(fusion.sync_code(), plain)
        with team_build(features=OFF): self.assertEqual(fusion.sync_code(), plain)
        with team_build(): self.assertNotEqual(fusion.sync_code(), plain)

    def overrides(self, squads):
        n, present = squads.count(), squads.present()
        return battle_modes.static_overrides('ffa', n, policy.targets('teams', n, present), 0x07000000, present)

    def test_the_fusion_entries_stay_only_with_the_feature(self):
        hooks = (fusion.ELIGIBILITY_HOOK, fusion.BEGIN_HOOK)
        with team_build(features=OFF) as squads:
            self.assertEqual(sorted(p for p, old, new in self.overrides(squads) if p in hooks and new == STUB), sorted(hooks))
        with team_build() as squads:
            self.assertEqual([p for p, old, new in self.overrides(squads) if p in hooks], [])

    def test_the_time_over_rule_changes_only_with_the_feature(self):
        with team_build(features=OFF): off = battle_modes.squad_timeover_code()
        with team_build(): on = battle_modes.squad_timeover_code()
        self.assertEqual(len(on)-len(off), 5*4)


class TimeOverWhileFused(unittest.TestCase):
    RESULT = 0x01F00000

    def decided(self, health, consumed=0, features=ON, sizes=(2, 2, 2)):
        with team_build(sizes, features) as squads: code = battle_modes.squad_timeover_code()
        m = WideMips(dict(segments=[dict(address=battle_modes.TIME_OVER, data_hex=code.hex()),
                                    dict(address=feed.ROW, data_hex=feed.row_code().hex())]))
        n = squads.count(); present = squads.present()
        for offset, value in ((0, 1), (4, n), (8, MANAGER), (12, n)): m.w(core.MODE+offset, value)
        m.w((GP+GPO(-22364)) & 0xFFFFFFFF, MANAGER); m.w(MANAGER, 2)
        m.write(policy.CONTROL, struct.pack('<6I', policy.MAGIC, MANAGER, n, policy.FFA, 0, present))
        m.w(policy.CONTROL+44, 0xFFFFFFFF); m.write(policy.SQUAD, squads.block(MANAGER, ()))
        m.w(part.CONSUMED, consumed)
        for i in range(n):
            if not present & (1 << i): continue
            actor = 0x01000000+i*0x2000
            m.w(core.POINTERS+4*i, actor); m.w(actor, i); m.w(actor+12, 12); m.w(actor+0x994, 0)
            m.w(actor+0x9E4, health[i][0]); m.w(actor+0x9E8, health[i][1])
        m.callbacks[battle_modes.TIME_HOOK+8] = lambda machine: machine.r.__setitem__(31, 0xFEED0000)
        m.w(self.RESULT, 0x55); m.r[4] = self.RESULT; m.instruction_budget = 60000
        m.run(battle_modes.TIME_OVER)
        F = policy.SQUAD_FIELDS
        return m.u(policy.SQUAD+F['winner_team']), m.u(policy.SQUAD+F['winner'])

    def test_a_consumed_partner_is_left_out_of_the_share(self):
        squads = policy.squad_layout((2, 2, 2))
        # team 0: the fused fighter 0 at 60 %, its consumed partner 2 with no health; team 1 at 50 %; team 2 at 33 %
        health = {0: (18000, 30000), 2: (0, 30000), 1: (15000, 30000), 3: (15000, 30000), 5: (10000, 30000), 7: (10000, 30000)}
        self.assertEqual(self.decided(health, consumed=1 << 2), (0, 0))
        self.assertEqual(policy.timeover_winner(squads, health, consumed=(2,)), (0, 0))
        # without the consumed mark (or with the feature off) the partner counts as a fallen fighter: 30 % < 50 %
        self.assertEqual(self.decided(health), (1, 1))
        self.assertEqual(self.decided(health, consumed=1 << 2, features=OFF), (1, 1))
        self.assertEqual(policy.timeover_winner(squads, health), (1, 1))

    def test_after_the_fusion_ends_both_count_again(self):
        squads = policy.squad_layout((2, 2, 2))
        health = {0: (9000, 30000), 2: (9000, 30000), 1: (15000, 30000), 3: (15000, 30000), 5: (10000, 30000), 7: (10000, 30000)}
        self.assertEqual(self.decided(health), (1, 1))
        self.assertEqual(policy.timeover_winner(squads, health), (1, 1))

    def test_a_fused_team_whose_fighter_fell_cannot_win(self):
        health = {0: (0, 30000), 2: (0, 30000), 1: (1, 30000), 3: (0, 30000), 5: (0, 30000), 7: (0, 30000)}
        self.assertEqual(self.decided(health, consumed=1 << 2), (1, 1))


if __name__ == '__main__':
    unittest.main()
