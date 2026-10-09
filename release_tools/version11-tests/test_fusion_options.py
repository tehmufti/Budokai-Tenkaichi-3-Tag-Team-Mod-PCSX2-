"""Execute the opt-out against leader, private-extra and human consent paths."""
import support
import struct
import unittest

import fusion_partner_lifecycle as fusion
import coop_fusion as coop
import multiplayer_fusion as multi
import battle_mode_policy as mode
from test_fusion_partner_lifecycle import machine
from fusion_fixture import timed_machine
from fusion_fixture import prepare
from fusion_fixture import coop_machine, coop_request, confirm
from fusion_fixture import multi_machine, request, accept, commit, run, pad


@unittest.skipUnless(support.HAS_FUSION_NATIVE, 'Provide native ELF and BT4 DBZP.BIN for full fusion lifecycle checks')
class FusionOptionTests(unittest.TestCase):
    def test_generated_guard_blocks_fit_the_reserved_code_layout(self):
        pieces=sorted(fusion.pieces())
        for (address,data),(next_address,_) in zip(pieces,pieces[1:]):
            self.assertLessEqual(address+len(data),next_address,hex(address))
        self.assertLessEqual(pieces[-1][0]+len(pieces[-1][1]),fusion.CONTROL)

    def test_disabled_blocks_every_leader_entry_without_native_queue_or_stock_cost(self):
        for side in (0,1):
            for cpu in (0,1):
                for entry in (fusion.ELIGIBILITY,fusion.EXTRA_ELIGIBILITY,fusion.BEGIN,fusion.EXTRA_BEGIN):
                    with self.subTest(side=side,cpu=cpu,entry=hex(entry)):
                        c=machine(side=side);c.w(c.source+0x1278,cpu);c.w(fusion.DISABLED,1)
                        before=c.read(c.source+0x9A4,164);registers=c.r.copy()
                        c.run(entry)
                        self.assertEqual(c.r[2],0)
                        self.assertEqual(c.read(c.source+0x9A4,164),before)
                        self.assertNotEqual(c.u(c.source+2388),241)
                        self.assertEqual(c.r[4:],registers[4:])
                        self.assertFalse(c.events)

    def test_disabled_blocks_all_extra_to_extra_pair_orders_and_reenable_works(self):
        for source,partner in ((2,4),(3,5),(4,2),(5,3)):
            c=prepare(timed_machine(),source,partner);c.w(fusion.DISABLED,1)
            for entry in (fusion.ELIGIBILITY,fusion.EXTRA_ELIGIBILITY,fusion.BEGIN,fusion.EXTRA_BEGIN):
                c.r[4:9]=[c.source,0,partner//2,0,0x1600000];run(c,entry)
                self.assertEqual(c.r[2],0,(source,partner,entry))
                self.assertNotEqual(c.u(c.source+2388),241)
                self.assertEqual(c.u(c.record),0)
            c.w(fusion.DISABLED,0);c.r[4:9]=[c.source,0,partner//2,0,0x1600000]
            run(c,fusion.BEGIN);self.assertEqual(c.r[2],1)
            self.assertEqual(c.u(c.source+2388),241)

    def test_stale_mod_owner_does_not_disable_native_fusion(self):
        c=machine();c.w(fusion.DISABLED,1);c.w(fusion.CONTROL+4,c.manager+4)
        c.callbacks[fusion.OLD_ELIGIBILITY]=lambda m:m.r.__setitem__(2,17)
        c.run(fusion.ELIGIBILITY);self.assertEqual(c.r[2],17)
        c.callbacks[fusion.OLD_BEGIN]=lambda m:m.r.__setitem__(2,19)
        c.run(fusion.BEGIN);self.assertEqual(c.r[2],19)

    def test_coop_pending_offer_is_cancelled_and_both_initiators_are_denied(self):
        for seat in (0,1):
            c=coop_machine();coop_request(c,seat);self.assertEqual(c.u(mode.CONTROL+48),0)
            c.w(fusion.DISABLED,1);c.run(coop.TICK)
            self.assertEqual(c.u(mode.CONTROL+48),0xFFFFFFFF)
            self.assertEqual(c.u(mode.CONTROL+60),0)
            self.assertEqual(c.u(mode.CONTROL+64),0)
            coop_request(c,seat);confirm(c,1-seat)
            self.assertEqual(c.u(mode.CONTROL+48),0xFFFFFFFF)
            self.assertNotEqual(c.u(c.source+2388),241)

    def test_coop_accepted_transaction_keeps_consent_and_commits_after_disable(self):
        c=coop_machine();coop_request(c);confirm(c,1);c.w(fusion.DISABLED,1)
        c.run(coop.TICK);self.assertEqual(c.u(mode.CONTROL+64),1)
        c.w(c.source+2376,241);c.r[4]=c.source;c.run(coop.COMMIT)
        self.assertEqual(c.u(fusion.PART_CONTROL+16),4)
        self.assertEqual(c.u(mode.CONTROL+24),0)
        self.assertEqual(c.u(mode.CONTROL+28),2)

    def test_three_four_player_pending_offer_cancels_without_changing_existing_fusion(self):
        for subjects,partner_seat in (((0,2,4),1),((0,1,2,3),2)):
            c=multi_machine(subjects=subjects);request(c,0)
            self.assertEqual(c.u(multi.ROWS),1)
            c.w(fusion.DISABLED,1);run(c,multi.TICK)
            self.assertEqual(c.u(multi.ROWS),0)
            request(c,partner_seat);accept(c,0)
            self.assertEqual(c.u(multi.ROWS),0)
            self.assertNotEqual(c.u(c.source+2388),241)
            c.w(fusion.DISABLED,0);c.w(pad(partner_seat)+328,0)
            request(c,0);accept(c,partner_seat)
            self.assertEqual(c.u(multi.ROWS),2)
            c.w(fusion.DISABLED,1);run(c,multi.TICK)
            self.assertEqual(c.u(multi.ROWS),2)
            commit(c);self.assertEqual(c.u(multi.ROWS),3)
            run(c,multi.TICK);self.assertEqual(c.u(multi.ROWS),3)
            c.r[4]=2;run(c,multi.FOLLOW);self.assertEqual(c.r[2],0)

    def test_private_extra_human_offer_cannot_bypass_disabled_leader_recipe(self):
        c=prepare(multi_machine(subjects=(0,2,4,1)));c.w(fusion.DISABLED,1)
        c.callbacks[0x20E340]=lambda m:m.r.__setitem__(2,255 if m.r[4]==c.actors[0] else 48)
        for seat in (1,2):
            request(c,seat)
            self.assertEqual(c.u(multi.ROWS+2*multi.STRIDE),0)
            self.assertNotEqual(c.u(c.source+2388),241)

    def test_live_settings_plan_changes_only_policy_and_rejects_old_or_foreign_code(self):
        ram=bytearray(0x8000000);manager=0x1800000;count=6
        for at,value in ((fusion.core.ACTORS,manager),(fusion.core.MODE,1),(fusion.core.MODE+4,count),
                         (fusion.core.MODE+8,manager),(fusion.core.MODE+12,count),
                         (fusion.CONTROL,1),(fusion.CONTROL+4,manager),(fusion.CONTROL+8,count)):
            struct.pack_into('<I',ram,at,value)
        code=fusion.eligibility_code();ram[fusion.ELIGIBILITY:fusion.ELIGIBILITY+len(code)]=code
        for enabled,expected in ((False,1),(True,0)):
            plan=fusion.settings_plan(ram,enabled)
            self.assertEqual(len(plan['blocks']),1)
            block=plan['blocks'][0];self.assertEqual(block['address'],fusion.DISABLED)
            self.assertEqual(bytes.fromhex(block['data_hex']),struct.pack('<I',expected))
            ram[fusion.DISABLED:fusion.DISABLED+4]=bytes.fromhex(block['data_hex'])
        for value in (None,0,1,'false'):
            with self.assertRaisesRegex(ValueError,'Boolean'):fusion.settings_plan(ram,value)
        struct.pack_into('<I',ram,fusion.DISABLED,2)
        with self.assertRaisesRegex(ValueError,'option state'):fusion.settings_plan(ram,True)
        struct.pack_into('<I',ram,fusion.DISABLED,0)
        ram[fusion.ELIGIBILITY]^=1
        with self.assertRaisesRegex(ValueError,'admission guards'):fusion.settings_plan(ram,True)
        ram[fusion.ELIGIBILITY]^=1;struct.pack_into('<I',ram,fusion.CONTROL+4,manager+4)
        with self.assertRaisesRegex(ValueError,'owner changed'):fusion.settings_plan(ram,True)


if __name__=='__main__':unittest.main()
