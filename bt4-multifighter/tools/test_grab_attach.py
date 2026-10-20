"""Every grabbed fighter is held by its own thrower, however many grabs run at once (grab_attach).

The native hold function 1D7C30 and the native flag helpers run for real (the executable's own bytes in an
emulated EE RAM); only the bone, vector and model-refresh helpers are Python stand-ins, so the tests watch exactly
which victim the native body moves and marks held (flag 0x23), and where it puts it.
"""
# Native execution tests use only the developer's own fixture helpers.
import importlib.util as _TestSpec
import unittest as _TestUnit
if not all(_TestSpec.find_spec(_name) for _name in ('test_ground_locomotion',)):
    raise _TestUnit.SkipTest('The developer ground-locomotion interpreter is required for grab tests')
import struct
import unittest

import grab_attach as fix
import fresh_team_combat as core
from native_map import A, FLAG, GP
from test_ground_locomotion import Cpu as LocomotionCpu

STACK = 0x01F00000


class Cpu(LocomotionCpu):
    """The ground-locomotion interpreter (pool interpreter, scalar FPU, sllv/srlv) plus movn, which the native
    hold loop uses to keep the last flagged fighter."""
    instruction_budget = 2_000_000

    def extra_instruction(self, ins, pc):
        if ins >> 26 == 0 and ins & 63 == 11:
            if self.r[(ins >> 16) & 31]:
                self.r[(ins >> 11) & 31] = self.r[(ins >> 21) & 31]
            return None
        return super().extra_instruction(ins, pc)

    def call(self, pc, gp=GP, registers=None):
        for reg, value in (registers or {}).items():
            self.r[reg] = value & 0xFFFFFFFF
        self.r[28], self.r[29], self.r[31] = gp, STACK, 0xFEED0000
        self.run(pc)

ACTORS = [0x01800000 + i * 0x1600 for i in range(6)]   # the native manager's stride
MODELS = [0x01900000 + i * 0x2000 for i in range(6)]
MANAGER = 0x01700000
HAND, GRIP = (10.0, 0.0, 0.0), (0.0, 5.0, 0.0)     # thrower bone 0x34 / victim grip bone offsets from the root
HELD_FLAG = 0x23
NATIVE_CODE = ((A(0x1D7C30), 0x238), (A(0x1DAC78), 0x38), (A(0x1DABE8), 0x90), (A(0x1DC298), 8),
               (A(0x1DC2C0), 0x0C), (A(0x1DC168), 0x10), (A(0x1DC178), 0x24))
CORE = (core.COUNT, core.PHYSICAL, core.LOGICAL, core.RESOLVER, A(0x1DC168), A(0x1DC178), A(0x1DC1A0))


def vec(c, p):
    return struct.unpack('<3f', c.read(p, 12))


def setvec(c, p, v):
    c.write(p, struct.pack('<4f', *v, 1.0))


def machine(install=True, count=6):
    c = Cpu({'segments': []})
    for p, n in NATIVE_CODE:
        c.write(p, fix.NATIVE(p, n))
    for p, b, _ in core.program():
        if p in CORE:
            c.write(p, b)
    c.write(fix.SITE, fix.NATIVE(fix.SITE, 4))
    if install:
        for p, b in fix.pieces():
            c.write(p, b)
    gp = GP
    c.w(core.ACTORS, MANAGER); c.w(MANAGER, 2); c.w(MANAGER + 4, ACTORS[0])
    c.write(core.MODE, struct.pack('<4I', 1, count, MANAGER, count))
    for pid in range(count):
        actor = ACTORS[pid]
        c.w(core.POINTERS + 4 * pid, actor); c.w(core.TABLE + 4 * pid, pid ^ 1)
        c.w(actor, pid); c.w(actor + 8, pid % 2); c.w(actor + 12, pid)
        setvec(c, actor + 16, (100.0 * pid, 0.0, 0.0))
    c.held = []

    def model(m):
        m.r[2] = MODELS[ACTORS.index(m.r[4])]

    def bone(m):           # 2058E0(model id, bone, out): bone 0x34 is the hand, anything else the grip
        pos = vec(m, ACTORS[m.r[4]] + 16)
        off = HAND if m.r[5] == 0x34 else GRIP
        setvec(m, m.r[6], tuple(p + o for p, o in zip(pos, off)))

    def sub(m):
        a, b = vec(m, m.r[5]), vec(m, m.r[6]); setvec(m, m.r[4], tuple(x - y for x, y in zip(a, b)))

    def add(m):
        a, b = vec(m, m.r[5]), vec(m, m.r[6]); setvec(m, m.r[4], tuple(x + y for x, y in zip(a, b)))

    def scale(m):
        s = m.number(12); setvec(m, m.r[4], tuple(x * s for x in vec(m, m.r[4])))

    c.callbacks.update({A(0x1DC280): model, A(0x2058E0): bone, A(0x121ED8): sub, A(0x121EA8): add,
                        A(0x121F38): scale, A(0x1D7198): lambda m: m.held.append(('root', m.r[4])),
                        A(0x24E3F8): lambda m: None, A(0x1D70E8): lambda m: None})
    for model_ in MODELS:
        c.w(model_ + 0xCB4, 7)         # the victim's grip bone index (1DC280(victim)+0xCB4)
    c.gp = gp
    return c


def flag(c, pid, number, value=True):
    p = ACTORS[pid] + 0x1085 + (number >> 3)
    current = c.read(p, 1)[0]
    c.write(p, bytes([current | (1 << (number & 7)) if value else current & ~(1 << (number & 7))]))


def held(c, pid):
    n = FLAG(HELD_FLAG)
    return bool(c.read(ACTORS[pid] + 0x10AD + (n >> 3), 1)[0] & (1 << (n & 7)))


def grab(c, thrower, victim):
    flag(c, thrower, fix.HOLDING); flag(c, victim, fix.HELD)
    c.w(core.TABLE + 4 * thrower, victim); c.w(core.TABLE + 4 * victim, thrower)


def update(c, through_site=True):
    """One hold update: the per-update loop's call at 1C2D20 (the patched jal), or native 1D7C30 directly."""
    if through_site:
        word = c.u(fix.SITE); target = (word & 0x3FFFFFF) << 2
    else:
        target = fix.HOLD
    c.call(target, gp=c.gp)


def at_hand(c, thrower, victim):
    t, v = vec(c, ACTORS[thrower] + 16), vec(c, ACTORS[victim] + 16)
    want = tuple(x + h - g for x, h, g in zip(t, HAND, GRIP))
    return all(abs(a - b) < 1e-3 for a, b in zip(v, want))


class GrabAttachTests(unittest.TestCase):
    def test_native_hold_reproduces_the_slide_with_two_grabs(self):
        # The bug: only the last thrower/victim pair (3 -> 2) is held; victim 1 misses flag 0x23 and slides.
        c = machine(install=False)
        grab(c, 0, 1); grab(c, 3, 2)
        update(c, through_site=False)
        self.assertTrue(at_hand(c, 3, 2)); self.assertTrue(held(c, 2))
        self.assertFalse(held(c, 1)); self.assertFalse(at_hand(c, 0, 1))

    def test_two_grabs_are_both_held_by_their_own_throwers(self):
        c = machine()
        grab(c, 0, 1); grab(c, 3, 2)
        update(c)
        for thrower, victim in ((0, 1), (3, 2)):
            self.assertTrue(at_hand(c, thrower, victim), (thrower, victim))
            self.assertTrue(held(c, victim), victim)
        self.assertEqual(c.u(fix.CONTROL + fix.C['multi']), 1)
        self.assertEqual(c.u(fix.CONTROL + fix.C['held']), 2)
        self.assertEqual(c.u(fix.CONTROL + fix.C['unpaired']), 0)

    def test_crossed_indices_no_longer_pin_a_victim_to_the_other_thrower(self):
        # Native: last thrower 2 and last victim 3 -> victim 3 teleports to thrower 2's hand.
        c = machine(install=False); grab(c, 0, 3); grab(c, 2, 1); update(c, through_site=False)
        self.assertTrue(at_hand(c, 2, 3)); self.assertFalse(held(c, 1))
        c = machine(); grab(c, 0, 3); grab(c, 2, 1); update(c)
        self.assertTrue(at_hand(c, 0, 3)); self.assertTrue(at_hand(c, 2, 1))
        self.assertTrue(held(c, 1)); self.assertTrue(held(c, 3))

    def test_the_actual_pair_wins_over_proximity(self):
        c = machine(); grab(c, 0, 3); grab(c, 2, 1)
        # Thrower 0 stands right next to victim 1, thrower 2 next to victim 3: the records still decide.
        setvec(c, ACTORS[0] + 16, (101.0, 0.0, 0.0)); setvec(c, ACTORS[2] + 16, (301.0, 0.0, 0.0))
        update(c)
        self.assertTrue(at_hand(c, 0, 3)); self.assertTrue(at_hand(c, 2, 1))
        self.assertEqual(c.u(fix.CONTROL + fix.C['resolved']), 2)
        self.assertEqual(c.u(fix.CONTROL + fix.C['nearest']), 0)

    def test_thrower_side_record_pairs_when_the_victim_points_elsewhere(self):
        c = machine(); grab(c, 0, 1); grab(c, 3, 2)
        c.w(core.TABLE + 4 * 1, 5); c.w(core.TABLE + 4 * 2, 4)   # the victims' own targets moved on
        update(c)
        self.assertTrue(at_hand(c, 0, 1)); self.assertTrue(at_hand(c, 3, 2))
        self.assertEqual(c.u(fix.CONTROL + fix.C['resolved']), 2)

    def test_nearest_thrower_is_the_last_resort(self):
        c = machine(); grab(c, 0, 1); grab(c, 3, 2)
        # every target a valid enemy that holds nobody: no record names a thrower for these victims
        for pid, target in ((0, 5), (1, 4), (2, 5), (3, 4)):
            c.w(core.TABLE + 4 * pid, target)
        setvec(c, ACTORS[0] + 16, (110.0, 0.0, 0.0)); setvec(c, ACTORS[3] + 16, (210.0, 0.0, 0.0))
        update(c)
        self.assertTrue(at_hand(c, 0, 1)); self.assertTrue(at_hand(c, 3, 2))
        self.assertEqual(c.u(fix.CONTROL + fix.C['nearest']), 2)

    def test_nearest_never_pulls_back_a_victim_that_was_let_go(self):
        # Thrower 3 holds victim 2 with no record naming either; victim 1 (lower index) was let go far away and
        # still carries 0x97 for a few updates (its thrower's release animation no longer sets 0x8B).
        c = machine(); flag(c, 3, fix.HOLDING); flag(c, 2, fix.HELD); flag(c, 1, fix.HELD); flag(c, 0, fix.HOLDING)
        for pid, target in ((0, 5), (1, 4), (2, 5), (3, 4)):
            c.w(core.TABLE + 4 * pid, target)
        setvec(c, ACTORS[3] + 16, (300.0, 0.0, 0.0)); setvec(c, ACTORS[2] + 16, (290.0, 0.0, 0.0))
        setvec(c, ACTORS[1] + 16, (900.0, 0.0, 0.0)); setvec(c, ACTORS[0] + 16, (-400.0, 0.0, 0.0))
        before = vec(c, ACTORS[1] + 16)
        update(c)
        self.assertTrue(at_hand(c, 3, 2)); self.assertTrue(held(c, 2))
        self.assertFalse(held(c, 1)); self.assertEqual(vec(c, ACTORS[1] + 16), before)
        self.assertEqual(c.u(fix.CONTROL + fix.C['unpaired']), 1)

    def test_nearest_takes_the_closest_pair_overall(self):
        c = machine(); flag(c, 3, fix.HOLDING); flag(c, 0, fix.HOLDING); flag(c, 1, fix.HELD); flag(c, 2, fix.HELD)
        for pid, target in ((0, 5), (1, 4), (2, 5), (3, 4)):
            c.w(core.TABLE + 4 * pid, target)
        # victim 1 is 20 from thrower 3 and 30 from thrower 0; victim 2 is 5 from thrower 3: 3 holds 2, 0 holds 1
        setvec(c, ACTORS[3] + 16, (300.0, 0.0, 0.0)); setvec(c, ACTORS[2] + 16, (305.0, 0.0, 0.0))
        setvec(c, ACTORS[1] + 16, (320.0, 0.0, 0.0)); setvec(c, ACTORS[0] + 16, (350.0, 0.0, 0.0))
        update(c)
        self.assertTrue(at_hand(c, 3, 2)); self.assertTrue(at_hand(c, 0, 1))
        self.assertEqual(c.u(fix.CONTROL + fix.C['nearest']), 2)

    def test_rush_pair_fields_win_over_crossed_lock_on(self):
        c = machine()
        for thrower, victim in ((1, 0), (3, 2)):
            flag(c, thrower, fix.HOLDING); flag(c, victim, fix.HELD)
            for pid, action in ((thrower, 302), (victim, 314)):
                c.w(ACTORS[pid] + 0x948, action); c.w(ACTORS[pid] + 3732, thrower); c.w(ACTORS[pid] + 3736, victim)
        for a, b in ((0, 3), (2, 1)):          # reciprocal lock-on of the wrong fighters
            c.w(core.TABLE + 4 * a, b); c.w(core.TABLE + 4 * b, a)
        update(c)
        self.assertTrue(at_hand(c, 1, 0)); self.assertTrue(at_hand(c, 3, 2))
        # the same lock-on without the rush fields pairs by the records (here: wrongly) - pass 0 is what decided
        c2 = machine()
        for thrower, victim in ((1, 0), (3, 2)):
            flag(c2, thrower, fix.HOLDING); flag(c2, victim, fix.HELD)
        for a, b in ((0, 3), (2, 1)):
            c2.w(core.TABLE + 4 * a, b); c2.w(core.TABLE + 4 * b, a)
        update(c2)
        self.assertTrue(at_hand(c2, 3, 0))

    def test_rush_fields_need_both_fighters_and_rush_actions(self):
        c = machine()
        for thrower, victim in ((1, 0), (3, 2)):
            flag(c, thrower, fix.HOLDING); flag(c, victim, fix.HELD)
            for pid, action in ((thrower, 302), (victim, 184)):   # a throw victim: fields are stale, not used
                c.w(ACTORS[pid] + 0x948, action); c.w(ACTORS[pid] + 3732, thrower); c.w(ACTORS[pid] + 3736, victim)
        for a, b in ((0, 3), (2, 1)):
            c.w(core.TABLE + 4 * a, b); c.w(core.TABLE + 4 * b, a)
        update(c)
        self.assertTrue(at_hand(c, 3, 0)); self.assertTrue(at_hand(c, 1, 2))

    def test_a_victim_without_a_free_thrower_is_left_to_the_native_release(self):
        c = machine(); grab(c, 0, 1); flag(c, 2, fix.HELD)     # a second held flag with no second thrower
        update(c)
        self.assertTrue(at_hand(c, 0, 1)); self.assertTrue(held(c, 1)); self.assertFalse(held(c, 2))
        self.assertEqual(c.u(fix.CONTROL + fix.C['unpaired']), 1)

    def test_one_grab_is_exactly_the_native_hold(self):
        for pair in ((0, 1), (4, 3), (2, 5)):
            native, ours = machine(install=False), machine()
            for c in (native, ours):
                grab(c, *pair)
                flag(c, pair[1], 0x34)                       # the native scale branch too
                c.write(MODELS[pair[1]] + 0xC84, struct.pack('<f', 0.25))
            update(native, through_site=False); update(ours)
            for pid in range(6):
                self.assertEqual(native.read(ACTORS[pid], 0x1600), ours.read(ACTORS[pid], 0x1600), (pair, pid))
            self.assertEqual(ours.u(fix.CONTROL + fix.C['multi']), 0)

    def test_thrower_follows_victim_with_flag_9b(self):
        c = machine(); grab(c, 0, 1); grab(c, 3, 2); flag(c, 3, 0x9B)
        v2 = vec(c, ACTORS[2] + 16)
        update(c)
        self.assertTrue(at_hand(c, 0, 1))
        self.assertEqual(vec(c, ACTORS[2] + 16), v2)                 # 0x9B moves the thrower, not the victim
        t3 = vec(c, ACTORS[3] + 16)
        self.assertTrue(all(abs(t + h - (v + g)) < 1e-3 for t, h, v, g in zip(t3, HAND, v2, GRIP)))

    def test_gone_fighters_and_self_pairs_are_skipped(self):
        c = machine(); grab(c, 0, 1); grab(c, 3, 2)
        c.w(ACTORS[3] + 0x1320, 1)                                   # 1DC2C0: fighter 3 is gone
        update(c)
        self.assertTrue(at_hand(c, 0, 1)); self.assertFalse(held(c, 2))

    def test_outside_a_team_match_the_native_function_runs(self):
        for words in ((0, 6, MANAGER, 6), (1, 6, MANAGER, 5)):
            native, ours = machine(install=False), machine()
            for c in (native, ours):
                c.write(core.MODE, struct.pack('<4I', *words)); grab(c, 0, 1); grab(c, 3, 2)
            update(native, through_site=False); update(ours)
            for pid in range(6):
                self.assertEqual(native.read(ACTORS[pid], 0x1600), ours.read(ACTORS[pid], 0x1600))
            self.assertEqual(ours.u(fix.CONTROL + fix.C['multi']), 0)

    def test_many_simultaneous_grabs(self):
        c = machine(); grab(c, 0, 1); grab(c, 3, 2); grab(c, 4, 5)
        update(c)
        for thrower, victim in ((0, 1), (3, 2), (4, 5)):
            self.assertTrue(at_hand(c, thrower, victim)); self.assertTrue(held(c, victim))

    def test_registers_and_stack_are_preserved_for_the_native_caller(self):
        c = machine(); grab(c, 0, 1); grab(c, 3, 2)
        regs = {r: 0x11110000 + r for r in range(16, 24)}
        regs[30] = 0x3030
        c.call((c.u(fix.SITE) & 0x3FFFFFF) << 2, gp=c.gp, registers=regs)
        self.assertEqual({r: c.r[r] for r in regs}, regs)
        self.assertEqual(c.r[29], STACK)


class GrabAttachBuildTests(unittest.TestCase):
    def ram(self):
        ram = bytearray(0x8000000)
        for p, n in ((fix.HOLD, 0x238), (fix.SITE, 4)):
            ram[p:p + n] = fix.NATIVE(p, n)
        return ram

    def test_build_installs_once_and_verifies(self):
        ram = self.ram()
        manifest = fix.build_memory(ram)
        self.assertEqual({int(b['address']) for b in manifest['blocks']},
                         {fix.ENTRY, fix.ATTACH, fix.CONTROL, fix.SITE})
        for b in manifest['blocks']:
            self.assertEqual(bytes.fromhex(b['expected_hex']), bytes(ram[b['address']:b['address'] + len(b['data_hex']) // 2]))
            data = bytes.fromhex(b['data_hex']); ram[b['address']:b['address'] + len(data)] = data
        self.assertEqual(ram[fix.SITE:fix.SITE + 4], struct.pack('<I', (3 << 26) | (fix.ENTRY >> 2)))
        again = fix.build_memory(ram)
        self.assertEqual(again['blocks'], []); self.assertEqual(again['status'], 'GRAB HOLD PAIRS INSTALLED')

    def test_build_refuses_changed_site_or_occupied_reservation(self):
        ram = self.ram(); ram[fix.SITE:fix.SITE + 4] = b'\0\0\0\0'
        with self.assertRaises(ValueError):
            fix.build_memory(ram)
        ram = self.ram(); ram[fix.CODE + 0x40] = 1
        with self.assertRaises(ValueError):
            fix.build_memory(ram)
        ram = self.ram(); ram[fix.HOLD + 0x100] ^= 1
        with self.assertRaises(ValueError):
            fix.build_memory(ram)

    def test_layout(self):
        fix.native_check()
        (entry, code), (attach, stub) = fix.pieces()[:2]
        self.assertLessEqual(entry + len(code), attach)
        self.assertLessEqual(attach + len(stub), fix.CONTROL)
        self.assertLessEqual(fix.DONE + 4 * fix.SLOTS, fix.END)
        words = struct.unpack('<%dI' % (len(code) // 4), code) + struct.unpack('<%dI' % (len(stub) // 4), stub)
        for w in words:   # no k0/k1 (26/27) as any register operand of these programs
            op = w >> 26
            if op in (0, 9, 15, 13, 35, 43, 55, 63, 4, 5, 12, 14):
                self.assertNotIn((w >> 21) & 31, (26, 27), hex(w)); self.assertNotIn((w >> 16) & 31, (26, 27), hex(w))
                if op == 0:
                    self.assertNotIn((w >> 11) & 31, (26, 27), hex(w))
        # the stub saves exactly the native slots, in a 16-byte aligned frame
        self.assertEqual(stub[:4], struct.pack('<I', 0x27BDFF90))
        frame = struct.unpack('<I', code[(code.index(struct.pack('<I', 0x27BDFFA0))):][:4])[0]
        self.assertEqual((0x10000 - (frame & 0xFFFF)) % 16, 0)


if __name__ == '__main__':
    unittest.main()
