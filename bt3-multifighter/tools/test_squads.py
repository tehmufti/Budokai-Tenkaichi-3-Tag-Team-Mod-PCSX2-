"""Team Battle with three to five teams: layout, relation emission, the build scope and the win predicate."""
import itertools
import struct
import unittest

import battle_mode_policy as policy
import battle_modes
import fresh_team_combat as core
import guest_killfeed as feed
from native_map import GPO
from prototype import Assembler
from test_ai_shadow import GP, Mips

MANAGER = 0x1870400
CODE = 0x07A00000


def relation_program(emit):
    a = Assembler(CODE)
    emit(a, 4, 5, 'fail', 'x')
    a.addiu(2, 0, 1); a.jr()
    a.label('fail'); a.move(2, 0); a.jr()
    return a.finish()


def run_relation(code, squads, left, right, live=MANAGER, block=True, control=True):
    m = Mips(dict(segments=[dict(address=CODE, data_hex=code.hex())]))
    m.w((GP+GPO(-22364)) & 0xFFFFFFFF, live)
    if control:
        m.write(policy.CONTROL, struct.pack('<4I', policy.MAGIC, MANAGER, squads.count(), policy.FFA))
    if block:
        m.write(policy.SQUAD, squads.block(MANAGER))
    m.r[4], m.r[5] = left, right
    m.run(CODE)
    return m.r[2]


class Layout(unittest.TestCase):
    def test_every_size_combination_keeps_the_invariants(self):
        cases = splits = 0
        for n in range(2, policy.MAX_TEAMS+1):
            for sizes in itertools.product(range(1, policy.TEAM_CAPACITY+1), repeat=n):
                if sum(sizes) > policy.MAX_ACTORS: continue
                squads = policy.squad_layout(sizes); cases += 1
                left, right = squads.counts()
                self.assertTrue(1 <= left <= 5 and 1 <= right <= 5 and left+right == sum(sizes), sizes)
                self.assertEqual(squads.sizes(), sizes)
                self.assertEqual(squads.members(0)[0], 0, sizes)
                self.assertNotEqual(squads.team_of[0], squads.team_of[1], sizes)
                self.assertEqual(squads.present() & 3, 3, sizes)
                straddling = [t for t in range(n) if len({i & 1 for i in squads.members(t)}) == 2]
                self.assertLessEqual(len(straddling), 1, sizes)
                self.assertEqual(squads.split(), straddling[0] if straddling else None, sizes)
                self.assertNotEqual(squads.split(), 0, sizes)
                splits += bool(straddling)
                if n == 2:
                    self.assertEqual([squads.members(0), squads.members(1)],
                                     [tuple(range(0, 2*sizes[0], 2)), tuple(range(1, 2*sizes[1], 2))], sizes)
        self.assertEqual((cases, splits), (552, 16))

    def test_known_layouts(self):
        five = policy.squad_layout((2, 2, 2, 2, 2))
        self.assertEqual(five.team_of[:10], (0, 1, 0, 1, 2, 3, 2, 3, 4, 4))
        self.assertEqual(five.split(), 4)
        self.assertEqual(policy.squad_layout((2, 2, 2)).team_of[:8], (0, 1, 0, 1, None, 2, None, 2))
        self.assertEqual(policy.squad_layout((3, 3, 3)).split(), 2)
        for bad in ((1,), (2, 2, 2, 2, 2, 2), (6, 1, 1), (5, 5, 1), (0, 2, 2), (2, '2', 2)):
            with self.assertRaises(ValueError): policy.squad_layout(bad)

    def test_seats_follow_the_teams(self):
        squads = policy.squad_layout((2, 2, 2))
        self.assertEqual(policy.squad_seats(squads, (0, 0, 1, 2)), (0, 2, 1, 5))
        self.assertEqual(policy.squad_seats(squads, (0, 1)), (0, 1))
        with self.assertRaisesRegex(ValueError, 'no fighter left'): policy.squad_seats(squads, (2, 2, 2))
        with self.assertRaises(ValueError): policy.squad_seats(squads, (3,))
        self.assertEqual(policy.human_seats('ffa', 3, squads.present(), (0, 2, 5), squads), (0, 2, 5))
        with self.assertRaises(ValueError): policy.human_seats('ffa', 2, squads.present(), (0, 4), squads)
        with self.assertRaises(ValueError): policy.human_seats('teams', 2, squads.present(), (0, 1), squads)

    def test_block_round_trips_through_ram(self):
        squads = policy.squad_layout((3, 3, 3)); ram = bytearray(policy.SQUAD_END)
        self.assertIsNone(policy.installed_squads(ram))
        ram[policy.SQUAD:policy.SQUAD_END] = squads.block(MANAGER, (0, 1))
        self.assertIsNone(policy.installed_squads(ram))        # no mode control for this manager
        struct.pack_into('<2I', ram, policy.CONTROL, policy.MAGIC, MANAGER)
        self.assertEqual(policy.installed_squads(ram), squads)
        struct.pack_into('<I', ram, policy.SQUAD+4, MANAGER+0x100)
        self.assertIsNone(policy.installed_squads(ram))
        block = squads.block(MANAGER, (0, 4))
        self.assertEqual(struct.unpack_from('<2I', block, policy.SQUAD_FIELDS['humans']), (0b10001, 1))
        self.assertEqual(struct.unpack_from('<5I', block, policy.SQUAD_FIELDS['colors']), policy.TEAM_COLORS)


class Twins(unittest.TestCase):
    def test_enemy_and_targets(self):
        for sizes in ((2, 2, 2), (2, 2, 2, 2, 2), (3, 3, 3), (1, 1, 1), (5, 4, 1), (1, 2, 5)):
            squads = policy.squad_layout(sizes); n = squads.count(); present = squads.present()
            for i, j in itertools.product(range(n), repeat=2):
                if squads.team_of[i] is None or squads.team_of[j] is None: continue
                self.assertEqual(policy.enemy('ffa', i, j, squads), i != j and squads.team_of[i] != squads.team_of[j])
            targets = policy.targets('ffa', n, present, squads)
            for i, target in enumerate(targets):
                self.assertTrue(present & (1 << target))
                if squads.team_of[i] is not None:
                    self.assertNotEqual(squads.team_of[i], squads.team_of[target], (sizes, i, target))
            # every team is somebody's opening target
            self.assertEqual({squads.team_of[t] for i, t in enumerate(targets) if squads.team_of[i] is not None},
                             set(range(squads.teams)), sizes)
            self.assertEqual(policy.validate_roster('ffa', n, present, 0, None, squads), squads.counts())
            with self.assertRaises(ValueError): policy.validate_roster('ffa', n, present ^ 2, 0, None, squads)
        self.assertEqual(policy.targets('ffa', 6, 63), [1, 0, 3, 2, 5, 4])     # the ordinary build is untouched
        self.assertTrue(policy.enemy('ffa', 0, 2)); self.assertFalse(policy.enemy('teams', 0, 2))


class Emission(unittest.TestCase):
    def test_ordinary_build_is_the_recorded_emission(self):
        code = relation_program(policy.emit_enemy)
        self.assertEqual((len(code)-24)//4, 25)
        self.assertIsNone(policy.emitted_squads())

    def test_squads_build_reads_the_team_table(self):
        tables = ((2, 2, 2), (2, 2, 2, 2, 2), (3, 3, 3), (1, 1, 1, 1, 1), (4, 4, 2))
        with policy.building_squads(policy.squad_layout((2, 2, 2))):
            code = relation_program(policy.emit_enemy)
        self.assertEqual((len(code)-24)//4, 20)
        for sizes in tables:
            squads = policy.squad_layout(sizes)
            for left, right in itertools.product(range(squads.count()), repeat=2):
                if squads.team_of[left] is None or squads.team_of[right] is None: continue
                want = int(policy.enemy('ffa', left, right, squads))
                self.assertEqual(run_relation(code, squads, left, right), want, (sizes, left, right))
                # another actor manager or no table at all: parity, never a guess
                parity = int(left != right and (left & 1) != (right & 1))
                self.assertEqual(run_relation(code, squads, left, right, live=MANAGER+0x40), parity)
                self.assertEqual(run_relation(code, squads, left, right, block=False), parity)

    def test_team_and_ally_helpers(self):
        squads = policy.squad_layout((2, 2, 2, 2, 2))
        a = Assembler(CODE); policy.emit_team(a, 2, 4); a.jr(); ordinary = a.finish()
        self.assertEqual(struct.unpack('<I', ordinary[:4])[0], (12 << 26) | (4 << 21) | (2 << 16) | 1)
        with policy.building_squads(squads):
            a = Assembler(CODE); policy.emit_team(a, 2, 4); a.jr(); table = a.finish()
            a = Assembler(CODE); policy.emit_team(a, 4, 4, scratch=9); a.move(2, 4); a.jr(); in_place = a.finish()
            with self.assertRaises(ValueError):
                policy.emit_team(Assembler(CODE), 4, 4)
            ally = relation_program(lambda a, l, r, fail, tag: policy.emit_ally(a, l, r, fail))
        with self.assertRaises(ValueError):
            relation_program(lambda a, l, r, fail, tag: policy.emit_ally(a, l, r, fail))
        for code in (table, in_place):
            for index in range(10):
                m = Mips(dict(segments=[dict(address=CODE, data_hex=code.hex())]))
                m.write(policy.SQUAD, squads.block(MANAGER)); m.r[4] = index; m.run(CODE)
                self.assertEqual(m.r[2], squads.team_of[index])
        for left, right in itertools.product(range(10), repeat=2):
            self.assertEqual(run_relation(ally, squads, left, right),
                             int(left != right and squads.team_of[left] == squads.team_of[right]))

    def test_seats_come_from_a_build_scope_only(self):
        squads = policy.squad_layout((2, 2, 2, 2, 2)).with_seats((8, 1))
        present = squads.present()
        self.assertEqual(policy.human_seats('ffa', 2, present, None, squads), (8, 1))
        with policy.building_squads(squads):
            self.assertEqual(policy.human_seats('ffa', 2, present), (8, 1))          # the four-seat modules' question
            self.assertEqual(policy.human_seats('teams', 2, present), (0, 1))        # another mode: the usual rule
        policy.session_squads(squads)
        try:
            self.assertEqual(policy.human_seats('ffa', 2, present), (0, 1))          # the session default never decides
            self.assertEqual(policy.human_seats('ffa', 3, 0x3FF), (0, 2, 4))
        finally:
            policy.session_squads(None)
        block = squads.block(MANAGER)
        self.assertEqual(block[policy.SQUAD_FIELDS['seats']:policy.SQUAD_FIELDS['seats']+4], bytes([8, 1, 0xFF, 0xFF]))
        ram = bytearray(policy.SQUAD_END)
        ram[policy.SQUAD:policy.SQUAD_END] = block
        struct.pack_into('<2I', ram, policy.CONTROL, policy.MAGIC, MANAGER)
        self.assertEqual(policy.installed_squads(ram).seats, (8, 1))
        with self.assertRaises(ValueError): squads.with_seats((8, 8))
        with self.assertRaises(ValueError): policy.squad_layout((2, 2, 2)).with_seats((4,))    # no fighter stands there

    def test_scope_nesting_and_session_default(self):
        a, b = policy.squad_layout((2, 2, 2)), policy.squad_layout((3, 3, 3))
        self.assertIsNone(policy.emitted_squads())
        try:
            policy.session_squads(a)
            self.assertEqual(policy.emitted_squads(), a)
            with policy.building_squads(b):
                self.assertEqual(policy.emitted_squads(), b)
                with policy.building_squads(None):
                    self.assertIsNone(policy.emitted_squads())
                self.assertEqual(policy.emitted_squads(), b)
            self.assertEqual(policy.emitted_squads(), a)
        finally:
            policy.session_squads(None)
        self.assertIsNone(policy.emitted_squads())
        with self.assertRaises(ValueError): policy.building_squads((0, 1, 2))

    def test_matching_install_builds_what_the_ram_holds(self):
        squads = policy.squad_layout((2, 2, 2)); ram = bytearray(0x8000000)
        seen = policy.matching_install(lambda r: policy.emitted_squads())
        self.assertIsNone(seen(ram))
        struct.pack_into('<2I', ram, policy.CONTROL, policy.MAGIC, MANAGER)
        ram[policy.SQUAD:policy.SQUAD_END] = squads.block(MANAGER)
        self.assertEqual(seen(ram), squads)
        other = policy.squad_layout((3, 3, 3))
        with policy.building_squads(other):
            self.assertEqual(seen(ram), other)          # an explicit scope rules

    def test_free_for_all_variants_change_only_inside_the_scope(self):
        import fresh_team_ai as ai, ffa_targeting as ffa, guest_healthbars as bars, lockon_queue as queue
        squads = policy.squad_layout((2, 2, 2, 2, 2))
        build = lambda: (battle_modes.defeat_code(), core.resolver_code(True), bars.draw_code(True),
                         queue.payload(0x073D0000, free_for_all=True), tuple(d for _, d in ffa.program('ffa')),
                         tuple(s['data_hex'] for s in ai.program(10, policy.targets('ffa', 10, 1023), free_for_all=True)['segments']))
        ordinary = build()
        with policy.building_squads(squads): inside = build()
        self.assertEqual(build(), ordinary)
        for before, after in zip(ordinary, inside): self.assertNotEqual(before, after)
        # teams and co-op flavours never depend on the scope
        with policy.building_squads(squads):
            teams = (core.resolver_code(), bars.draw_code() == bars.draw_code(), queue.payload(0x073D0000))
        self.assertEqual(teams[0], core.resolver_code()); self.assertEqual(teams[2], queue.payload(0x073D0000))

    def test_picker_lists_are_the_relation(self):
        import team_six_ai as six
        for sizes in ((2, 2, 2), (2, 2, 2, 2, 2), (1, 1, 1)):
            squads = policy.squad_layout(sizes); n = squads.count()
            targets = policy.targets('ffa', n, squads.present(), squads)
            import fresh_team_ai as ai
            from unittest.mock import patch as mock
            with policy.building_squads(squads):
                keeping = bytes.fromhex(ai.program(n, targets, free_for_all=True)['segments'][1]['data_hex'])
                with mock.object(policy, 'SQUAD_FEATURES', policy.SQUAD_FEATURES-{'revive_lockon'}):
                    picker = bytes.fromhex(ai.program(n, targets, free_for_all=True)['segments'][1]['data_hex'])
            ordinary = bytes.fromhex(ai.program(n, policy.targets('ffa', n, squads.present()), free_for_all=True)['segments'][1]['data_hex'])
            # teammates are left out of each fighter's list; with one fighter per team nothing is
            (self.assertLess if max(sizes) > 1 else self.assertEqual)(len(picker), len(ordinary))
            # the keep of a downed teammate for its player (feature revive_lockon) only adds, and the picker still fits
            self.assertGreater(len(keeping), len(picker))
            self.assertLessEqual(len(keeping), 0x4000)


class TeamFeatures(unittest.TestCase):
    """Converted team features: on in a match of three to five teams, untouched everywhere else."""

    def own_side(self, squads, side, candidate, row, equal):
        import ai_shadow
        import camera_successor as successor
        a = ai_shadow.Assembler(CODE)
        successor.own_side(a, 21, 'taken', equal)
        a.move(2, 0); a.emit(0x03E00008); a.nop()
        a.label('taken'); a.addiu(2, 0, 1); a.emit(0x03E00008); a.nop()
        m = Mips(dict(segments=[dict(address=CODE, data_hex=a.finish().hex())]))
        m.write(policy.SQUAD, squads.block(MANAGER))
        m.r[16], m.r[21], m.r[5] = side, candidate, row
        m.run(CODE)
        return m.r[2]

    def test_camera_side_is_the_row_in_other_matches_and_the_team_here(self):
        squads = policy.squad_layout((2, 2, 2, 2, 2))
        for side, candidate in itertools.product(range(2), range(10)):
            self.assertEqual(self.own_side(squads, side, candidate, candidate & 1, True), int(candidate & 1 == side))
            self.assertEqual(self.own_side(squads, side, candidate, candidate & 1, False), int(candidate & 1 != side))
        with policy.building_squads(squads):
            for side, candidate in itertools.product(range(2), range(10)):
                same = squads.team_of[candidate] == squads.team_of[side]
                self.assertEqual(self.own_side(squads, side, candidate, candidate & 1, True), int(same))
                self.assertEqual(self.own_side(squads, side, candidate, candidate & 1, False), int(not same))
            # A fighter of another team on the camera's own row is no successor; that is the whole point.
            self.assertEqual(self.own_side(squads, 0, 4, 0, True), 0)
            self.assertEqual(self.own_side(squads, 0, 2, 0, True), 1)

    def camera(self, code, squads, side, alive, owner=None):
        """Run cinematic_policy.subject for one view of a synthetic match; returns the published owner or 'old'."""
        import camera_continuity as continuity
        import cinematic_policy as cinema
        import fresh_team_camera as fresh
        import result_presentation as result
        import team_intro
        m = Mips(dict(segments=[dict(address=cinema.SUBJECT, data_hex=code.hex())]))
        count = squads.count(); battle = 0x01900000
        m.w((GP+GPO(-22364)) & 0xFFFFFFFF, MANAGER); m.w(MANAGER, 2)
        m.write(core.MODE, struct.pack('<4I', 1, count, MANAGER, count))
        m.write(cinema.CONTROL, struct.pack('<4I', cinema.MAGIC, MANAGER, count, battle))
        m.w(team_intro.BATTLE, battle); m.w(battle, 3)
        m.write(policy.CONTROL, struct.pack('<4I', policy.MAGIC, MANAGER, count, policy.FFA))
        m.w(policy.CONTROL+44, 0xFFFFFFFF)
        m.write(policy.SQUAD, squads.block(MANAGER))
        m.w(fresh.SUCCESSOR_CONTROL+8+4*side, side if owner is None else owner)
        seen = []
        def lookup(machine):
            index = machine.r[4]; seen.append(index)
            machine.r[2], machine.r[3], machine.r[5] = index, int(index in alive), index & 1
        def old(machine): machine.r[2] = 0xDEAD
        m.callbacks[continuity.LOOKUP] = lookup; m.callbacks[fresh.SUCCESSOR] = old
        m.r[4] = side; m.run(cinema.SUBJECT)
        return 'old' if m.r[2] == 0xDEAD else m.u(fresh.SUCCESSOR_CONTROL+8+4*side)

    def test_first_camera_authority_prefers_a_living_teammate(self):
        import cinematic_policy as cinema
        squads = policy.squad_layout((2, 2, 2, 2, 2))
        everyone = set(range(10))
        ordinary = cinema.subject()
        with policy.building_squads(squads):
            team = cinema.subject()
        self.assertNotEqual(ordinary, team)
        self.assertEqual(cinema.subject(), ordinary)
        # the free-for-all rule: the first living fighter, whoever it is
        self.assertEqual(self.camera(ordinary, squads, 0, everyone-{0}), 1)
        # three to five teams: the view of row 0 belongs to team 1 (fighters 0 and 2)
        self.assertEqual(self.camera(team, squads, 0, everyone), 0)
        self.assertEqual(self.camera(team, squads, 0, everyone-{0}), 2)
        self.assertEqual(self.camera(team, squads, 1, everyone-{1}), 3)
        # no teammate left: anyone living, as in a free-for-all; nobody living: the old chain
        self.assertEqual(self.camera(team, squads, 0, everyone-{0, 2}), 1)
        self.assertEqual(self.camera(team, squads, 0, {7}), 7)
        self.assertEqual(self.camera(team, squads, 0, set()), 'old')
        # every team and every survivor set of that team: never an enemy while a teammate lives
        for sizes in ((2, 2, 2), (3, 2, 1), (4, 3, 3), (2, 2, 2, 2, 2)):
            layout = policy.squad_layout(sizes)
            with policy.building_squads(layout):
                code = cinema.subject()
            present = {i for i in range(10) if layout.team_of[i] is not None}
            for side in (0, 1):
                mates = [i for i in layout.members(layout.team_of[side]) if i != side]
                for survivor in mates:
                    owner = self.camera(code, layout, side, present-{side}-(set(mates)-{survivor}))
                    self.assertEqual(owner, survivor, (sizes, side, survivor))

    def test_takeover_and_its_offer_change_only_in_a_squads_build(self):
        import spectator_feedback as feedback
        import spectator_takeover as takeover
        emitters = [lambda: takeover.take(), lambda: takeover.take(commit=False), lambda: takeover.take(quad=True)]
        ordinary = [emit() for emit in emitters]
        refusal = struct.pack('<I', (9 << 26) | (9 << 16) | policy.FFA)        # addiu t1, zero, FFA
        with policy.building_squads(policy.squad_layout((2, 2, 2))):
            a = Assembler(CODE); policy.emit_ally(a, 20, 17, 'no', t0=8, t1=9); a.label('no'); a.jr()
            ally = a.finish()[4:20]                                              # past the equality branch
            for emit, before in zip(emitters, ordinary):
                squads = emit()
                self.assertNotEqual(squads, before)
                self.assertIn(refusal, before); self.assertNotIn(ally, before)
                self.assertIn(ally, squads)
                # with the split pair opened the row test is gone and the team test alone decides
                row = struct.pack('<2I', (20 << 21) | (17 << 16) | (8 << 11) | 0x26, (12 << 26) | (8 << 21) | (8 << 16) | 1)
                self.assertIn(row, before)
                self.assertEqual(row in squads, 'takeover_split' not in policy.SQUAD_FEATURES)
        self.assertEqual([emit() for emit in emitters], ordinary)
        self.assertTrue({'successor', 'takeover'} <= policy.SQUAD_FEATURES)


class Predicate(unittest.TestCase):
    def machine(self, squads, alive, humans=()):
        with policy.building_squads(squads): code = battle_modes.defeat_code()
        self.assertEqual(code, battle_modes.squad_defeat_code())
        m = Mips(dict(segments=[dict(address=battle_modes.FFA_DEFEAT, data_hex=code.hex()),
                                dict(address=feed.ROW, data_hex=feed.row_code().hex())]))
        n = squads.count(); present = squads.present()
        for offset, value in ((0, 1), (4, n), (8, MANAGER), (12, n)): m.w(core.MODE+offset, value)
        m.w((GP+GPO(-22364)) & 0xFFFFFFFF, MANAGER); m.w(MANAGER, 2)
        m.write(policy.CONTROL, struct.pack('<6I', policy.MAGIC, MANAGER, n, policy.FFA, len(humans), present))
        m.w(policy.CONTROL+44, 0xFFFFFFFF)
        m.write(policy.SQUAD, squads.block(MANAGER, humans))
        for i in range(n):
            if not present & (1 << i): continue
            actor = 0x01000000+i*0x2000
            m.w(core.POINTERS+4*i, actor); m.w(actor, i); m.w(actor+12, 12); m.w(actor+0x994, 0)
            m.w(actor+0x9E4, 1000 if i in alive else 0)
        return m

    def ask(self, squads, alive, humans=()):
        answers = []
        for side in (0, 1):
            m = self.machine(squads, alive, humans); m.r[4] = side
            m.run(battle_modes.FFA_DEFEAT)
            F = policy.SQUAD_FIELDS
            answers.append((m.r[2], m.u(policy.CONTROL+44), m.u(policy.SQUAD+F['alive']),
                            m.u(policy.SQUAD+F['winner_team']), m.u(policy.SQUAD+F['winner'])))
        return answers

    def test_every_alive_set(self):
        none = 0xFFFFFFFF
        for sizes, humans in (((2, 2, 2), ()), ((2, 2, 2, 2, 2), ()), ((3, 3, 3), (0, 9)), ((2, 2, 2, 2, 2), (2, 9))):
            squads = policy.squad_layout(sizes)
            fighters = [i for i in range(10) if squads.team_of[i] is not None]
            for size in range(len(fighters)+1):
                for alive in itertools.combinations(fighters, size):
                    if len(fighters) > 6 and size not in (0, 1, 2, 3, len(fighters)): continue
                    teams = {squads.team_of[i] for i in alive}
                    mask = sum(1 << t for t in teams)
                    (v0, w0, m0, t0, s0), (v1, w1, m1, t1, s1) = self.ask(squads, set(alive), humans)
                    self.assertEqual((m0, m1), (mask, mask))
                    if len(teams) >= 2:
                        self.assertEqual((v0, v1, w0, w1, t0, s0), (0, 0, none, none, none, none), (sizes, alive))
                    elif not teams:
                        self.assertEqual((v0, v1, w0, w1), (1, 1, none, none), (sizes, alive))
                    else:
                        players = [i for i in alive if i in humans]
                        winner = players[0] if players else alive[0]
                        self.assertEqual((w0, w1, s0, s1), (winner,)*4, (sizes, alive))
                        self.assertEqual((t0, t1), (squads.team_of[winner],)*2)
                        # the other native side is the defeated one, whoever still stands there
                        self.assertEqual((v0, v1), (winner & 1, 1-(winner & 1)), (sizes, alive))

    def test_split_team_wins_from_either_side(self):
        squads = policy.squad_layout((2, 2, 2, 2, 2)); pair = squads.members(4)
        self.assertEqual({i & 1 for i in pair}, {0, 1})
        (v0, w, *_), (v1, *_) = self.ask(squads, set(pair))
        self.assertEqual((v0, v1, w), (0, 1, pair[0]))          # the first living member is on side 0
        (v0, w, *_), (v1, *_) = self.ask(squads, {pair[1]})
        self.assertEqual((v0, v1, w), (1, 0, pair[1]))
        (v0, w, *_), (v1, *_) = self.ask(squads, set(pair), humans=(pair[1],))
        self.assertEqual((v0, v1, w), (1, 0, pair[1]))          # a player's fighter is preferred

    def test_other_matches_fall_back(self):
        squads = policy.squad_layout((2, 2, 2))
        m = self.machine(squads, {0, 1}); m.w(policy.SQUAD+4, MANAGER+0x40); m.r[4] = 0
        import team_defeat
        m.callbacks[team_defeat.CODE] = lambda machine: machine.r.__setitem__(2, 77)
        m.run(battle_modes.FFA_DEFEAT)
        self.assertEqual(m.r[2], 77)

    def test_fits_its_cave_and_the_ordinary_predicate_is_unchanged(self):
        self.assertLess(len(battle_modes.squad_defeat_code()), 0x1000)
        ordinary = battle_modes.defeat_code()
        self.assertNotEqual(ordinary, battle_modes.squad_defeat_code())
        self.assertEqual(len(ordinary), 712)


class WideMips(Mips):
    """The test interpreter plus MULTU / MFHI / MFLO (the time-over rule compares 64-bit products)."""
    hi = lo = 0

    def extra_instruction(self, ins, pc):
        if ins >> 26 == 0 and ins & 63 == 0x19:
            product = (self.r[(ins >> 21) & 31] & 0xFFFFFFFF)*(self.r[(ins >> 16) & 31] & 0xFFFFFFFF)
            self.hi, self.lo = product >> 32, product & 0xFFFFFFFF
            return None
        if ins >> 26 == 0 and ins & 63 in (0x10, 0x12):
            self.r[(ins >> 11) & 31] = self.hi if ins & 63 == 0x10 else self.lo
            return None
        return super().extra_instruction(ins, pc)


class TimeOver(unittest.TestCase):
    """217E38 for three to five teams: the team with the largest share of its full health left, ties to the lower
    team; fallen fighters count with no health and their full maximum."""
    RESULT = 0x01F00000

    def machine(self, squads, health, humans=(), block=True):
        with policy.building_squads(squads): code = battle_modes.squad_timeover_code()
        m = WideMips(dict(segments=[dict(address=battle_modes.TIME_OVER, data_hex=code.hex()),
                                    dict(address=feed.ROW, data_hex=feed.row_code().hex())]))
        n = squads.count(); present = squads.present()
        for offset, value in ((0, 1), (4, n), (8, MANAGER), (12, n)): m.w(core.MODE+offset, value)
        m.w((GP+GPO(-22364)) & 0xFFFFFFFF, MANAGER); m.w(MANAGER, 2)
        m.write(policy.CONTROL, struct.pack('<6I', policy.MAGIC, MANAGER, n, policy.FFA, len(humans), present))
        m.w(policy.CONTROL+44, 0xFFFFFFFF)
        if block: m.write(policy.SQUAD, squads.block(MANAGER, humans))
        for i in range(n):
            if not present & (1 << i): continue
            actor = 0x01000000+i*0x2000
            m.w(core.POINTERS+4*i, actor); m.w(actor, i); m.w(actor+12, 12); m.w(actor+0x994, 0)
            m.w(actor+0x9E4, health[i][0]); m.w(actor+0x9E8, health[i][1])
        native = []
        m.callbacks[battle_modes.TIME_HOOK+8] = lambda machine: native.append(1) or machine.r.__setitem__(31, 0xFEED0000)
        m.w(self.RESULT, 0x55); m.r[4] = self.RESULT; m.instruction_budget = 60000
        m.run(battle_modes.TIME_OVER)
        return m, bool(native)

    def decided(self, squads, health, humans=()):
        m, native = self.machine(squads, health, humans)
        F = policy.SQUAD_FIELDS
        if native: return None
        return (m.u(policy.SQUAD+F['winner_team']), m.u(policy.SQUAD+F['winner']), m.u(policy.CONTROL+44), m.u(self.RESULT))

    def test_guest_and_python_twin_agree(self):
        import random
        rng = random.Random(1115)
        F = policy.SQUAD_FIELDS
        for sizes in ((2, 2, 2), (2, 2, 2, 2, 2), (3, 2, 1), (1, 1, 1), (4, 3, 3), (1, 1, 1, 1, 1), (5, 4, 1)):
            squads = policy.squad_layout(sizes)
            fighters = [i for i in range(10) if squads.team_of[i] is not None]
            for case in range(40):
                health = {}
                for i in fighters:
                    top = rng.choice((10000, 30000, 40000, 120000, 200000))
                    health[i] = (rng.choice((0, 0, 1, top//3, top//2, top-1, top, rng.randrange(top+1))), top)
                humans = tuple(sorted(rng.sample(fighters, rng.randrange(0, 3))))
                want = policy.timeover_winner(squads, health, humans)
                got = self.decided(squads, health, humans)
                if want is None:
                    self.assertIsNone(got, (sizes, health)); continue
                team, w = want
                self.assertEqual(got, (team, w, w, (w & 1)+1), (sizes, health, humans))

    def test_the_whole_team_counts_and_ties_go_to_the_lower_team(self):
        squads = policy.squad_layout((2, 2, 2, 2, 2))
        full = {i: (30000, 30000) for i in range(10)}
        self.assertEqual(self.decided(squads, full), (0, 0, 0, 1))
        # one healthy survivor does not beat a wounded but complete team: 30000/60000 against 36000/60000
        health = dict(full); health[4] = (0, 30000); health[6] = (30000, 30000)
        for i in (0, 2): health[i] = (18000, 30000)
        for i in (1, 3, 5, 7, 8, 9): health[i] = (9000, 30000)
        self.assertEqual(self.decided(squads, health)[:2], (0, 0))
        self.assertEqual(policy.timeover_winner(squads, health), (0, 0))
        # the split team (fighters 8 and 9) ahead with its row-0 fighter down: the winner sits on row 1
        health = {i: (9000, 30000) for i in range(10)}; health[8] = (0, 30000); health[9] = (29000, 30000)
        self.assertEqual(self.decided(squads, health), (4, 9, 9, 2))
        # a player of the winning team is named before its other fighters
        health = {i: (10000, 30000) for i in range(10)}; health[1] = health[3] = (30000, 30000)
        self.assertEqual(self.decided(squads, health, humans=(3,)), (1, 3, 3, 2))
        # different maxima: shares decide, not points (team 2: 40000 of 240000; team 1: 15000 of 60000)
        health = {i: (1, 30000) for i in range(10)}
        health[0] = (7000, 30000); health[2] = (8000, 30000); health[1] = (20000, 120000); health[3] = (20000, 120000)
        self.assertEqual(self.decided(squads, health)[:1], (0,))
        # products beyond 32 bits: 900000 * 1000000 against 899999 * 1000000 (five fighters of 200000 each)
        squads = policy.squad_layout((5, 4, 1))
        health = {i: (180000, 200000) for i in range(10)}
        health[1] = (179999, 200000)
        want = policy.timeover_winner(squads, health)
        self.assertEqual(self.decided(squads, health)[:2], want)
        self.assertEqual(want[0], 0)

    def test_a_team_without_a_living_fighter_cannot_win_and_nobody_alive_is_native(self):
        squads = policy.squad_layout((2, 2, 2))
        health = {i: (0, 30000) for i in range(10)}; health[7] = (1, 30000)
        self.assertEqual(self.decided(squads, health)[:2], (2, 7))
        health[7] = (0, 30000)
        m, native = self.machine(squads, health)
        self.assertTrue(native); self.assertEqual(m.u(self.RESULT), 0x55)
        self.assertIsNone(policy.timeover_winner(squads, health))

    def test_other_matches_and_a_missing_table_run_the_native_routine(self):
        squads = policy.squad_layout((2, 2, 2))
        health = {i: (1000, 1000) for i in range(10)}
        m, native = self.machine(squads, health, block=False)
        self.assertTrue(native); self.assertEqual(m.u(self.RESULT), 0x55)
        self.assertEqual(m.r[29], 0x2000000-0x100-16)            # the displaced prologue ran: addiu sp,sp,-16

    def test_cave_and_hook(self):
        with policy.building_squads(policy.squad_layout((2, 2, 2))):
            code = battle_modes.squad_timeover_code()
        self.assertLess(battle_modes.FFA_DEFEAT+len(battle_modes.squad_defeat_code()), battle_modes.TIME_OVER)
        self.assertLessEqual(battle_modes.TIME_OVER+len(code), policy.CONTROL)
        self.assertEqual(len(battle_modes.TIME_NATIVE), 8)
        self.assertIn('timeover', policy.SQUAD_FEATURES)


if __name__ == '__main__':
    unittest.main()
