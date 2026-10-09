"""Run emitted tournament rules plus the real native contact/result decisions."""
import support
import struct
import unittest
import tournament_ringout as r
from test_terrain_crossing_guard import ScalarMips

MANAGER, ARRAY, BATTLE = 0x1800000, 0x1900000, 0x1801000


class Cpu(ScalarMips):
    def extra_instruction(self, ins, pc):
        if ins >> 26 == 0 and ins & 63 == 0x27:
            rs, rt, rd = (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
            self.r[rd] = ~(self.r[rs] | self.r[rt]) & 0xFFFFFFFFFFFFFFFF
            return
        return super().extra_instruction(ins, pc)


def run(c, entry, *args):
    c.r[4:4+len(args)] = args; c.r[31] = 0xFEED0000; c.run(entry)


def install(c, count=6, present=None, enabled=True, revive=True):
    # Source-only cases exercise the emitted policy/identity/contact hooks.
    # Actual result and native revival continuations require the user's ELF.
    programs = r.program(revive) if support.HAS_NATIVE else (
        (r.GATE, r.gate()), (r.LOOKUP, r.lookup()), (r.CONTACT, r.contact()))
    for p, data in programs: c.write(p, data)
    c.write(r.CONTROL, struct.pack('<5I', r.MAGIC, r.VERSION, MANAGER, count, int(enabled)))
    c.write(r.core.MODE, struct.pack('<4I', 1, count, MANAGER, count))
    c.w(r.core.ACTORS, MANAGER); c.w(MANAGER, 2); c.w(MANAGER+4, ARRAY)
    c.write(r.participation.CONTROL, struct.pack('<5I', 5, MANAGER, count,
            (1 << count)-1 if present is None else present, 0))
    c.w(r.A(0x2FEB38), BATTLE); c.w(BATTLE, 3)
    c.actors = [ARRAY+0x2000*i for i in range(count)]
    for i, actor in enumerate(c.actors):
        c.w(r.core.POINTERS+4*i, actor); c.w(r.CONTROL+r.F['pointers']+4*i, actor)
        c.w(actor, i); c.w(actor+8, i & 1); c.w(actor+12, i)
        c.w(actor+0x994, 0); c.w(actor+0x998, 1); c.w(actor+0x9AC, 1)
        c.w(actor+0x9E4, 30000); c.w(actor+0x9E8, 30000)
    c.set_calls = []
    def native_set(m):
        m.set_calls.append((m.r[4], m.r[5]))
        m.write(m.r[4]+0x1085, bytes([m.read(m.r[4]+0x1085, 1)[0] | 0x80]))
        m.r[2] = 87
    c.callbacks[r.NATIVE_SET] = native_set
    return c


def machine(**kwargs): return install(Cpu({'segments': []}), **kwargs)


def hp(c, i): return c.u(c.actors[i]+0x9E4+164*c.u(c.actors[i]+0x994))


class RingOutTests(unittest.TestCase):
    def test_every_physical_actor_and_current_row_eliminates_independently(self):
        for count in r.policy.ACTOR_COUNTS:
            for victim in range(count):
                c = machine(count=count); actor = c.actors[victim]
                c.w(actor, victim & 1)  # physical IDs can be aliased during a native slice
                c.w(actor+0x994, 3); c.w(actor+0x998, 5); c.w(actor+0x9E4+164*3, 32100)
                run(c, r.CONTACT, actor, 7)
                self.assertEqual(hp(c, victim), 0)
                self.assertEqual(c.u(actor+0x9E4), 30000)
                self.assertEqual(c.u(r.CONTROL+r.F['eliminated']), 1 << victim)
                self.assertEqual(c.u(r.CONTROL+r.F['contacts']), 1)
                self.assertEqual(c.r[2], 87)
                run(c, r.CONTACT, actor, 7)
                self.assertEqual(c.u(r.CONTROL+r.F['contacts']), 1)
                self.assertTrue(all(hp(c, j) == 30000 for j in range(count) if j != victim))

    def test_setting_off_and_intro_hold_cannot_eliminate(self):
        for field, value in ((r.CONTROL+r.F['enabled'], 0), (r.start.CONTROL, 1),
                             (BATTLE, 2), (r.A(0x333700), 1)):
            c = machine(); c.w(field, value); run(c, r.CONTACT, c.actors[0], 7)
            self.assertEqual(hp(c, 0), 30000); self.assertEqual(c.set_calls, [])
            self.assertEqual(c.u(r.CONTROL+r.F['eliminated']), 0)

    def test_unowned_stale_or_corrupt_rows_keep_native_path_without_hp_writes(self):
        for field, value in ((r.CONTROL+8, MANAGER+16), (r.core.MODE, 0),
                             (r.core.POINTERS, 0), (ARRAY+0x994, 5), (ARRAY+0x998, 6)):
            c = machine(); c.w(field, value); run(c, r.CONTACT, c.actors[0], 7)
            self.assertEqual(c.u(ARRAY+0x9E4), 30000)
            self.assertEqual(c.u(r.CONTROL+r.F['eliminated']), 0)
            self.assertEqual(c.set_calls, [(ARRAY, 7)])
        c = machine(); run(c, r.CONTACT, 0x190F000, 7)
        self.assertEqual(c.u(r.CONTROL+r.F['eliminated']), 0)

    @unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for collision/result/revival instructions")
    def test_native_contact_surface_decisions_grounded_airborne_and_nonring_stage(self):
        # Execute the unmodified stage/material decisions themselves, not a
        # Python recreation. s4 is the native solver's real ground-contact bit.
        for ring_stage, grounded, material, contact, expected in (
                (1, 1, 0, 0, True), (1, 0, 0, 0, False),
                (1, 1, 0x80, 0, False), (1, 1, 0x40, 0, False),
                (0, 1, 0, 0, False), (1, 0, 0, 0x40, True),
                (1, 0, 0, 0x20, True), (1, 0, 0x80, 0x20, False)):
            c = machine(); actor, model, physics, extension = c.actors[4], 0x900000, 0x910000, 0xA00000
            begin, end = 0x1CD8B0, 0x1CD96C
            c.write(begin, r.NATIVE(begin, end-begin))
            for p in r.CONTACT_HOOKS: c.write(p, r.CALL(r.CONTACT))
            c.r[16], c.r[17], c.r[18], c.r[19], c.r[20] = actor, physics, extension+98352, model, grounded
            c.w(model+5728, extension); c.w(extension+98336, contact)
            c.w(extension+98384, material); c.w(extension+98400, material)
            c.fw(physics+180, 0)
            c.callbacks[0x1DC480] = lambda m, value=ring_stage: m.r.__setitem__(2, value)
            c.callbacks[0x1DAA50] = lambda m: None
            c.run(begin, [end])
            self.assertEqual(bool(c.u(r.CONTROL+r.F['eliminated'])), expected,
                             (ring_stage, grounded, material, contact))

    @unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for collision/result/revival instructions")
    def test_native_team_winner_waits_for_all_unequal_team_members(self):
        import team_defeat as defeat
        for count, present in ((4, 7), (6, 31), (10, 0x3FF)):
            c = machine(count=count, present=present)
            c.write(defeat.CODE, defeat.code(r.NATIVE(defeat.ENTRY, 8)))
            c.write(defeat.ENTRY, r.JUMP(defeat.CODE))
            c.write(defeat.CONTROL, struct.pack('<4I', 1, MANAGER, ARRAY, count))
            for i, actor in enumerate(c.actors):
                c.w(defeat.CONTROL+64+4*i, actor)
                if not present & (1 << i): c.w(actor+0x9E4, 0)
            c.write(0x217FA8, r.NATIVE(0x217FA8, 0x120))
            c.callbacks[0x12A9E8] = lambda m: m.r.__setitem__(2, 0)
            c.callbacks[0x217E38] = lambda m: m.w(m.r[4], 4)
            result = 0x1700000
            for i in range(0, count, 2):
                if not present & (1 << i): continue
                run(c, r.CONTACT, c.actors[i], 7)
                c.r[16] = result; c.r[31] = 0xFEED0000
                c.run(0x217FA8, [0x2180C8, 0x2180CC])
                alive = [j for j in range(0, count, 2) if present & (1 << j) and hp(c, j)]
                self.assertEqual(c.u(result), 0 if alive else 2)

    @unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for collision/result/revival instructions")
    def test_healing_or_form_swap_cannot_restore_an_eliminated_body(self):
        c = machine(); run(c, r.CONTACT, c.actors[2], 7)
        c.w(c.actors[2]+0x994, 2); c.w(c.actors[2]+0x998, 3)
        c.w(c.actors[2]+0x9E4+2*164, 70000)
        run(c, r.RESULT, 0); self.assertEqual(hp(c, 2), 0)
        self.assertEqual(hp(c, 0), 30000)

    @unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for collision/result/revival instructions")
    def test_ringed_out_body_never_offers_or_completes_revival(self):
        from revive_fixture import machine as revive_machine, tick, stock
        c = revive_machine(source=2, corpse=0, channel=3)
        # Keep the revival fixture's position/animation/native execution data.
        actors = c.actors[:]
        for p, data in r.program(): c.write(p, data)
        c.write(r.CONTROL, struct.pack('<5I', r.MAGIC, r.VERSION, MANAGER, 6, 1))
        for i, actor in enumerate(actors): c.w(r.CONTROL+r.F['pointers']+4*i, actor)
        c.set_calls = []
        c.callbacks[r.NATIVE_SET] = lambda m: None
        run(c, r.CONTACT, actors[0], 7); tick(c, 20)
        self.assertEqual(c.u(actors[0]+0x9E4), 0); self.assertEqual(stock(c, 2), 500000)
        run(c, r.revival.ACTOR, 0); self.assertEqual((c.r[2], c.r[3]), (0, 0))
        run(c, r.revival.ACTOR, 2); self.assertEqual(c.r[2], actors[2])

    def test_registers_and_native_collision_arguments_survive(self):
        c = machine()
        for reg in range(3, 26): c.r[reg] = 0x12340000+reg
        c.r[4], c.r[5] = c.actors[4], 7
        saved, stack = c.r[3:26], c.r[29]
        c.run(r.CONTACT)
        self.assertEqual(c.r[3:26], saved); self.assertEqual(c.r[29], stack)

    @unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for collision/result/revival instructions")
    def test_builder_guards_dependencies_and_reentry_keeps_eliminations(self):
        c = machine(); ram = bytearray(0x8000000)
        for address, value in c.memory.items(): ram[address] = value
        ram[r.BASE:r.END] = bytes(r.END-r.BASE)
        ram[r.RESULT_HOOK:r.RESULT_HOOK+8] = r.NATIVE(r.RESULT_HOOK, 8)
        for p in r.CONTACT_HOOKS: ram[p:p+8] = r.NATIVE(p, 8)
        ram[r.revival.CONTROL:r.revival.CONTROL+4] = bytes(4)
        build = r.build_memory(ram)
        for block in build['blocks']:
            p, data = block['address'], bytes.fromhex(block['data_hex'])
            self.assertEqual(ram[p:p+len(data)].hex(), block['expected_hex']); ram[p:p+len(data)] = data
        struct.pack_into('<I', ram, r.CONTROL+r.F['eliminated'], 4)
        self.assertEqual(r.build_memory(ram)['blocks'], [])
        change = r.build_memory(ram, {r.KEY: False})['blocks']
        self.assertEqual([b['address'] for b in change], [r.CONTROL+r.F['enabled']])
        self.assertEqual(struct.unpack_from('<I', ram, r.CONTROL+r.F['eliminated'])[0], 4)
        ram[r.CONTACT] ^= 1
        with self.assertRaisesRegex(ValueError, 'program changed'): r.build_memory(ram)


if __name__ == '__main__': unittest.main()
