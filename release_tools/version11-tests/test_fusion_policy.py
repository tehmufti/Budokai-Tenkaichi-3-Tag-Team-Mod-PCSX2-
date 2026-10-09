"""Source-only execution of the fusion opt-out and pending-consent branches."""
import support
import struct
import unittest
import fusion_partner_lifecycle as fusion
import coop_fusion as coop
import multiplayer_fusion as multi
import battle_mode_policy as mode
from test_fusion_partner_lifecycle import FusionCpu


def run(cpu, entry):
    cpu.r[31] = 0xFEED0000
    cpu.run(entry)


class FusionPolicyTests(unittest.TestCase):
    def test_scoped_disabled_eligibility_and_both_begin_variants_never_enter_native(self):
        for entry, code in ((fusion.ELIGIBILITY, fusion.eligibility_code()),
                            (fusion.BEGIN, fusion.begin_code()), (fusion.BEGIN, fusion.begin_code(True))):
            c = FusionCpu(); c.write(entry, code); c.w(fusion.DISABLED, 1)
            c.callbacks[fusion.SYNC] = lambda m: m.r.__setitem__(2, 1)
            c.r[4:9] = [0x1900000, 2, 1, 0, 0x1700000]
            before = c.r[4:]; run(c, entry)
            self.assertEqual(c.r[2], 0)
            self.assertEqual(c.r[4:], before)

    def test_default_and_stale_scope_preserve_their_original_eligibility_path(self):
        for scoped, disabled, destination in ((True, 0, fusion.EXTRA_ELIGIBILITY),
                                               (False, 1, fusion.OLD_ELIGIBILITY)):
            c = FusionCpu(); c.write(fusion.ELIGIBILITY, fusion.eligibility_code())
            c.w(fusion.DISABLED, disabled); called = []
            c.callbacks[fusion.SYNC] = lambda m: m.r.__setitem__(2, int(scoped))
            c.callbacks[destination] = lambda m: (called.append(destination), m.r.__setitem__(2, 71))
            run(c, fusion.ELIGIBILITY)
            self.assertEqual(c.r[2], 71); self.assertEqual(called, [destination])

    def test_live_setting_changes_one_word_and_rejects_unrecognized_guard(self):
        ram = bytearray(0x8000000); manager, count = 0x1800000, 6
        for at, value in ((fusion.core.ACTORS, manager), (fusion.core.MODE, 1),
                          (fusion.core.MODE+4, count), (fusion.core.MODE+8, manager),
                          (fusion.core.MODE+12, count), (fusion.CONTROL, 1),
                          (fusion.CONTROL+4, manager), (fusion.CONTROL+8, count)):
            struct.pack_into('<I', ram, at, value)
        code = fusion.eligibility_code(); ram[fusion.ELIGIBILITY:fusion.ELIGIBILITY+len(code)] = code
        for enabled in (False, True):
            blocks = fusion.settings_plan(ram, enabled)['blocks']
            self.assertEqual(len(blocks), 1); self.assertEqual(blocks[0]['address'], fusion.DISABLED)
            self.assertEqual(bytes.fromhex(blocks[0]['data_hex']), struct.pack('<I', not enabled))
            ram[fusion.DISABLED:fusion.DISABLED+4] = bytes.fromhex(blocks[0]['data_hex'])
        ram[fusion.ELIGIBILITY] ^= 1
        with self.assertRaisesRegex(ValueError, 'admission guards'):
            fusion.settings_plan(ram, False)

    def test_coop_unanswered_offer_is_cancelled_without_any_native_call(self):
        c = FusionCpu(); previous = 0x0714FF00
        c.write(coop.TICK, coop.tick(previous)); c.callbacks[coop.GATE] = lambda m:m.r.__setitem__(2, 1)
        c.callbacks[previous] = lambda m: None
        battle = 0x1802000; c.w(fusion.A(0x2FEB38), battle); c.w(battle, 3)
        c.w(battle+260, fusion.A(0x2C6070)); c.w(fusion.A(0x3337C0), 1)
        c.w(mode.CONTROL+48, 0); c.w(mode.CONTROL+52, 2); c.w(mode.CONTROL+60, 120)
        c.w(fusion.DISABLED, 1); run(c, coop.TICK)
        self.assertEqual(c.u(mode.CONTROL+48), 0xFFFFFFFF)
        self.assertEqual(c.u(mode.CONTROL+52), 0xFFFFFFFF)
        self.assertEqual(c.u(mode.CONTROL+60), 0)
        self.assertEqual(c.u(mode.CONTROL+64), 0)
