"""An extra (CPU teammate) that picks its own team leader as fusion partner.

Leaders are never consumed, so before the fix such a pair began with the extra as the survivor and its private
reload commit could not consume the partner: TTM-MATCH-08 status 145, match held (Vegeta + Goku (End) -> Vegito).
Now the pair restarts as the leader's own BEGIN with the extra as partner, and the native leader commit consumes
the extra. Runs the emitted guest code with the native eligibility/BEGIN/merge bodies.
"""
# Native execution tests use only the developer's own extracted executable and fixture helpers.
import importlib.util as _TestSpec
import unittest as _TestUnit
if not all(_TestSpec.find_spec(_name) for _name in ('test_extra_fusion', 'test_fusion_duration',
                                                    'test_multiplayer_fusion')):
    raise _TestUnit.SkipTest('The developer fusion fixture helpers are required for native leader-fusion tests')

import unittest

import fusion_partner_lifecycle as fusion
import fusion_duration as timer
from test_extra_fusion import prepare
from test_fusion_duration import timed_machine
from test_multiplayer_fusion import run

QUEUE = (2380, 2388, 2392, 2396, 2400)


def leader_pair(side=0, extra=None):
    """Extra `extra` (default side+2) whose only matching partner is its leader. Distinct characters: leader 3,
    extra 34+physical; the native partner list of each names the other's current character."""
    extra = side + 2 if extra is None else extra
    c = prepare(timed_machine(side, 1), extra, side)
    c.leader, c.extra = c.actors[side], c.actors[extra]
    c.w(c.extra + 0x9A4 + 164 * (extra // 2), 34 + extra)
    for actor in c.actors:
        for off in QUEUE: c.w(actor + off, -1)

    def live(m, actor): return m.u(actor + 0x9A4 + 164 * m.u(actor + 0x994))
    c.callbacks[0x20E3A0] = lambda q: q.r.__setitem__(2, live(q, c.extra) if q.r[4] == c.leader else live(q, c.leader))
    c.r[4:9] = [c.extra, 0, 0, 0, 0x1600000]
    return c


class ExtraLeaderFusionTests(unittest.TestCase):
    def test_extra_choosing_its_leader_fuses_through_the_leader_and_consumes_the_extra(self):
        for side in (0, 1):
            for partner_argument in (0, -1):        # 203900 passes the found slot; scripted 0x11A..C passes -1
                c = leader_pair(side); c.r[6] = partner_argument & 0xFFFFFFFF
                run(c, fusion.BEGIN)
                self.assertEqual(c.r[2], 1, (side, partner_argument))
                self.assertEqual(c.u(c.leader + 2388), 241)
                self.assertEqual(c.u(c.leader + 4856), 1)                    # the extra's row slot
                self.assertNotIn(241, [c.u(c.extra + o) for o in (2376,) + QUEUE])
                self.assertEqual(c.u(timer.RECORDS + side * timer.STRIDE), 1)  # timed receipt on the survivor
                self.assertEqual(c.u(timer.RECORDS + (side + 2) * timer.STRIDE), 0)
                c.w(c.leader + 2376, 241); c.r[4] = c.leader; run(c, fusion.COMMIT)
                self.assertEqual(c.u(c.leader + 0x9A4), 48)
                self.assertEqual(c.u(fusion.PART_CONTROL + 16), 1 << (side + 2))
                self.assertEqual(c.u(fusion.CONTROL + 24), c.leader)
                self.assertEqual(c.u(fusion.CONTROL + 28), 0)

    def test_stale_initial_leader_row_never_begins_the_extra_as_survivor(self):
        # Native seating copies the side roster into every extra: its row 0 is the leader as selected (alive, base
        # form). The leader later falls or transforms; the extra must never fuse with that stale copy (live repro:
        # CPU Vegeta (End) + KO'd Goku (End) -> Vegito -> status 145, match held).
        for leader_state in ('defeated', 'alive'):
            c = leader_pair()
            c.write(c.extra + 0x9A4, c.read(c.leader + 0x9A4, 164))          # the native initial copy
            if leader_state == 'defeated':
                c.w(c.leader + 0x9A4 + 64, 0); c.w(c.leader + 2376, 216)
            c.r[6] = 0xFFFFFFFF; run(c, fusion.BEGIN)
            self.assertNotIn(c.u(c.extra + 2388), (241, 242), leader_state)
            self.assertNotEqual((c.u(c.extra + 2388), c.u(c.extra + 4856)), (241, 0), leader_state)
            if leader_state == 'defeated':
                self.assertEqual(c.r[2], 0); self.assertEqual(c.u(c.extra + 0x9A4 + 64), 0)
            else:
                self.assertEqual(c.r[2], 1); self.assertEqual(c.u(c.leader + 2388), 241)

    def test_extra_never_begins_as_the_survivor_of_its_leader(self):
        # The leader has no recipe giving the same character: refuse instead of queueing a fusion that only the
        # extra's private commit would see (status 145, match held).
        c = leader_pair()
        c.callbacks[0x20E340] = lambda q: q.r.__setitem__(2, 48 if q.r[4] == c.extra else 52)
        run(c, fusion.BEGIN)
        self.assertEqual(c.r[2], 0)
        for actor in (c.leader, c.extra):
            self.assertNotIn(c.u(actor + 2388), (241, 242))
        self.assertEqual(c.u(timer.RECORDS), 0); self.assertEqual(c.u(timer.RECORDS + 2 * timer.STRIDE), 0)

    def test_leader_is_offered_to_an_extra_only_alive_idle_and_unqueued(self):
        row0 = lambda c: c.extra + 0x9A4
        for case in ('idle', 'air', 'attacking', 'queued', 'dead', 'fusing'):
            c = leader_pair()
            if case == 'air': c.w(c.leader + 2376, 15)
            if case == 'attacking': c.w(c.leader + 2376, 25)
            if case == 'queued': c.w(c.leader + 2388, 30)
            if case == 'dead': c.w(c.leader + 0x9A4 + 64, 0)
            if case == 'fusing': c.w(c.leader + 2388, 242)
            run(c, fusion.ELIGIBILITY)
            offered = case in ('idle', 'air')
            self.assertEqual(c.r[2], int(offered), case)
            # The leader is mirrored as it is (character, HP); a busy one leaves the native partner search (+8 = 0),
            # a defeated one is refused through its HP.
            self.assertEqual(c.u(row0(c)), 3, case)
            self.assertEqual(c.u(row0(c) + 8), int(case not in ('attacking', 'queued', 'fusing')), case)
            self.assertEqual(c.u(row0(c) + 64), 0 if case == 'dead' else c.u(c.leader + 0x9A4 + 64), case)
            self.assertEqual(c.u(row0(c) + 112), 0, case)
            run(c, fusion.BEGIN)
            self.assertEqual(c.r[2], int(offered), case)
            self.assertEqual(c.u(c.leader + 2388), 241 if offered else
                             {'queued': 30, 'fusing': 242}.get(case, 0xFFFFFFFF), case)

    def test_busy_leader_of_the_same_character_never_hides_an_extra_partner(self):
        # Native 1CE108 stops at the first row holding the partner character: a Goku (End) leader in row 0 must not
        # shadow a Goku (End) extra in row 2 while the leader cannot fuse (BT4 recipe test, Vegeta + Goku extras).
        c = prepare(timed_machine(), 2, 4)
        for actor in c.actors:
            for off in QUEUE: c.w(actor + off, -1)
        c.w(c.actors[0] + 2376, 25)                                    # the leader is attacking
        c.w(c.source + 0x9A4 + 164, 36)                                # the requesting extra: another character
        partner = c.actors[4]; c.w(partner + 0x9A4 + 164 * 2, 3)       # extra partner: same character as leader
        c.w(c.models[4] + 12, 3)
        c.callbacks[0x20E3A0] = lambda q: q.r.__setitem__(2, 3)
        run(c, fusion.BEGIN)
        self.assertEqual(c.r[2], 1); self.assertEqual(c.u(c.source + 2388), 241)
        self.assertEqual(c.u(c.source + 4856), 2); self.assertEqual(c.u(c.actors[0] + 2388), 0xFFFFFFFF)

    def test_human_leader_survives_and_keeps_its_controller(self):
        c = leader_pair(); c.w(c.leader + 0x1278, 0)
        run(c, fusion.BEGIN)
        self.assertEqual(c.r[2], 1); self.assertEqual(c.u(c.leader + 2388), 241)
        self.assertEqual(c.u(c.leader + 0x1278), 0)

    def test_human_extra_request_is_never_routed_into_the_leader(self):
        # Co-op P2 / a taken-over extra: routing would consume that player's body without consent.
        c = leader_pair(); c.w(c.extra + 0x1278, 0)
        run(c, fusion.BEGIN)
        self.assertEqual(c.r[2], 0)
        for actor in (c.leader, c.extra): self.assertNotIn(c.u(actor + 2388), (241, 242))

    def test_reserved_partner_busy_at_commit_is_still_consumed(self):
        # A move or pending damage that slips in while the survivor loads must not turn the commit into a silent
        # no-op (duplicate partner) or, for an extra survivor, status 145.
        for field, value in ((2376, 183), (2388, 25), (3480, 1)):
            c = timed_machine()
            for actor in c.actors:
                for off in QUEUE: c.w(actor + off, -1)
            c.r[6] = 1; run(c, fusion.BEGIN); self.assertEqual(c.r[2], 1)
            partner = c.actors[c.partner]; c.w(partner + field, value)
            c.w(c.source + 2376, 241); c.r[4] = c.source; run(c, fusion.COMMIT)
            self.assertEqual(c.u(fusion.PART_CONTROL + 16), 1 << c.partner, field)
            self.assertEqual(c.u(fusion.CONTROL + 16), 1)

    def test_extra_survivor_commit_counts_once_and_names_itself(self):
        # extra_reload_commit's status-145 check reads these: the commit counter must move by exactly one and +24
        # must name this survivor, so a stale +24 from an earlier fusion can never pass a refused commit.
        c = prepare(timed_machine(), 2, 4)
        for actor in c.actors:
            for off in QUEUE: c.w(actor + off, -1)
        run(c, fusion.BEGIN); self.assertEqual(c.r[2], 1)
        # The private refresh (extra_reload_commit REFRESH, a copy of native 1C0538) publishes the fused character
        # in the live row and clears the partner's bench row.
        def refresh(q):
            a = q.r[4]; q.w(a + 0x9A4 + 164 * q.u(a + 0x994), q.u(a + 4816))
            bench = a + 0x9A4 + 164 * q.u(a + 4856); q.w(bench + 8, 0); q.w(bench + 64, 0)
        c.callbacks[0x07623200] = refresh
        c.w(fusion.CONTROL + 24, c.actors[0])            # stale survivor of an earlier fusion
        c.w(c.source + 2376, 241); c.r[4] = c.source; run(c, fusion.EXTRA_COMMIT)
        self.assertEqual(c.u(fusion.CONTROL + 16), 1); self.assertEqual(c.u(fusion.CONTROL + 24), c.source)
        self.assertEqual(c.u(fusion.PART_CONTROL + 16), 1 << 4)

    def test_extra_to_extra_fusion_is_unchanged_and_leader_sync_is_untouched(self):
        c = prepare(timed_machine(), 2, 4)
        for actor in c.actors:
            for off in QUEUE: c.w(actor + off, -1)
        run(c, fusion.BEGIN)
        self.assertEqual(c.r[2], 1); self.assertEqual(c.u(c.source + 2388), 241)
        self.assertEqual(c.u(c.source + 4856), 2)
        c = timed_machine(); before = c.read(c.source + 0x9A4, 164)
        c.r[4] = c.source; run(c, fusion.SYNC)
        self.assertEqual(c.read(c.source + 0x9A4, 164), before)     # a leader's own row 0 is never mirrored

    def test_an_extra_is_never_offered_itself(self):
        # After a reload an extra's live row can be slot 0; its old slot must not mirror the extra itself.
        c = leader_pair(); own = c.extra + 0x9A4
        c.write(own, c.read(own + 164, 164)); c.w(c.extra + 0x994, 0)
        c.r[4] = c.extra; run(c, fusion.SYNC)
        self.assertEqual(c.u(own + 164 + 8), 0); self.assertEqual(c.u(own + 164 + 64), 0)

    def test_router_preserves_registers_and_stays_inside_its_reservation(self):
        self.assertLess(fusion.ROUTE + len(fusion.route_code()), fusion.CONTROL)
        spans = sorted((p, p + len(b)) for p, b in fusion.pieces())
        self.assertTrue(all(end <= start for (_, end), (start, _) in zip(spans, spans[1:])))
        c = leader_pair(); c.r[4:6] = [c.extra, 0]; before = c.r.copy(); run(c, fusion.ROUTE)
        self.assertEqual(c.r[2], c.leader); self.assertEqual(c.r[3], 0)
        self.assertEqual(c.r[16:24], before[16:24]); self.assertEqual(c.r[29], before[29])


if __name__ == '__main__':
    unittest.main()
