"""Independent accepted transformations/rushes keep advancing; no savestates."""
import struct
import unittest
from unittest.mock import patch

import cinematic_policy as p
import cinematic_admission as admission
import rush_cinematics as rush
from test_fused_shared_cinematic import Cpu, MANAGER, BATTLE, CINE, ACTORS, MODELS


def run(c, address):
    c.r[31]=0xFEED0000;c.run(address);return c.r[2]


def machine(independent=True, shared_rush=True):
    c=Cpu({'segments':[]})
    for address,data in ((p.ULTIMATE_STOP,p.ultimate_stop(participants=True)),
                         (p.PROTECT,p.protect(independent)),(p.PROTECT_ACTIVE,p.protect_active()),
                         (p.PENDING,p.pending()),(p.CLASSIFY,p.classify()),
                         (p.SHARED_FORM,p.shared_form_owner()),(rush.OWNER,rush.owner()),
                         (p.continuity.LOOKUP,p.continuity.lookup_code())):c.write(address,data)
    c.w(p.core.ACTORS,MANAGER);c.w(MANAGER,2)
    c.write(p.core.MODE,struct.pack('<4I',1,6,MANAGER,6))
    c.w(p.team_intro.BATTLE,BATTLE);c.w(BATTLE,3)
    c.write(p.CONTROL,struct.pack('<6I',p.MAGIC,MANAGER,6,BATTLE,0,1))
    c.w(p.CONTROL+p.TRANSFORM_VIEW,1)
    c.write(rush.CONTROL,struct.pack('<3I',rush.MAGIC,MANAGER,int(shared_rush)))
    c.w(c.r[28]-22180,CINE);c.w(CINE+812,1)
    for index,(actor,model) in enumerate(zip(ACTORS,MODELS)):
        c.w(p.core.POINTERS+4*index,actor);c.w(actor,index);c.w(actor+8,index&1);c.w(actor+12,index)
        for offset in admission.ACTION_FIELDS:c.w(actor+offset,0xFFFFFFFF)
        c.w(actor+2376,11);c.w(actor+0x9E4,30000)
        c.w(p.core.MODELS+4*index,model);c.w(model+16,index);c.w(model+4,1);c.w(model+8,1)
    return c


def pair(c,attacker=0,victim=1,field=2376):
    for index,action in ((attacker,302),(victim,314)):
        c.w(ACTORS[index]+field,action);c.w(ACTORS[index]+3732,attacker);c.w(ACTORS[index]+3736,victim)


class ConcurrentCinematicProgressTests(unittest.TestCase):
    def test_shared_rush_does_not_hold_an_accepted_ordinary_form(self):
        for field in admission.ACTION_FIELDS:
            for action in range(236,241):
                for independent in (False,True):
                    c=machine(independent);pair(c);c.w(CINE+768,MODELS[0])
                    c.w(ACTORS[2]+field,action);c.w(MODELS[2]+8,0)
                    run(c,p.ULTIMATE_STOP)
                    self.assertEqual([c.u(a+4896)for a in ACTORS],
                                     [0,0,int(not independent),1,1,1],(field,action,independent))
                    self.assertEqual(c.u(ACTORS[2]+field),action)

    def test_shared_form_does_not_hold_a_different_live_rush(self):
        for field in admission.ACTION_FIELDS:
            for independent in (False,True):
                c=machine(independent,shared_rush=False);pair(c,field=field)
                c.w(ACTORS[2]+2376,236);c.write(ACTORS[2]+p.PRIORITY_FLAG_BYTES[0],bytes([p.PRIORITY_FLAG_BIT]))
                c.w(CINE+768,MODELS[2]);run(c,p.ULTIMATE_STOP)
                self.assertEqual([c.u(a+4896)for a in ACTORS],
                                 [int(not independent),int(not independent),0,1,1,1],(field,independent))
                self.assertEqual(c.u(p.CONTROL+p.ULTIMATE_MEMBERS),1<<2)

    def test_finished_stale_foreign_or_dead_bodies_do_not_gain_protection(self):
        for fault in ('historical','fusion','dead','actor_id','model_id','model_unloaded','foreign_model'):
            c=machine();c.w(ACTORS[2]+2376,236)
            if fault=='historical':c.w(ACTORS[2]+2376,11);c.w(ACTORS[2]+2384,236)
            elif fault=='fusion':c.w(ACTORS[2]+2376,241)
            elif fault=='dead':c.w(ACTORS[2]+0x9E4,0)
            elif fault=='actor_id':c.w(ACTORS[2],4)
            elif fault=='model_id':c.w(MODELS[2]+16,4)
            elif fault=='model_unloaded':c.w(MODELS[2]+4,0)
            else:c.w(p.core.MODELS+8,0x08000000)
            self.assertEqual(run(c,p.PROTECT_ACTIVE),0,fault)
        for fault in ('idle','unilateral','self','out_of_range','allied','dead_partner','ordinary_hit'):
            c=machine();pair(c)
            if fault=='idle':c.w(ACTORS[0]+2376,11);c.w(ACTORS[1]+2376,11)
            elif fault=='unilateral':c.w(ACTORS[1]+3732,2)
            elif fault=='self':c.w(ACTORS[0]+3736,0)
            elif fault=='out_of_range':c.w(ACTORS[0]+3736,6)
            elif fault=='allied':pair(c,0,2);c.w(ACTORS[1]+2376,11)
            elif fault=='dead_partner':c.w(ACTORS[1]+0x9E4,0)
            else:
                for actor in ACTORS[:2]:
                    c.w(actor+2376,34);c.w(actor+4016,1)
                    from native_map import FLAG
                    c.write(actor+0x1085+(FLAG(0x94)>>3),bytes([1<<(FLAG(0x94)&7)]))
            self.assertEqual(run(c,p.PROTECT_ACTIVE),0,fault)

    def test_accepted_pair_flags_before_action_commit_are_protected(self):
        from native_map import FLAG
        c=machine();pair(c)
        for actor in ACTORS[:2]:
            c.w(actor+2376,11);c.w(actor+4016,34)
            c.write(actor+0x1085+(FLAG(0x94)>>3),bytes([1<<(FLAG(0x94)&7)]))
        self.assertEqual(run(c,p.PROTECT_ACTIVE),3)

    def test_same_parity_pair_requires_captured_free_for_all(self):
        for manager in (MANAGER,MANAGER+4):
            c=machine();pair(c,0,2)
            c.write(p.modes.CONTROL,struct.pack('<4I',p.modes.MAGIC,manager,6,p.modes.FFA))
            self.assertEqual(run(c,p.PROTECT_ACTIVE),5 if manager==MANAGER else 0)

    def test_helper_preserves_registers_actors_camera_loader_and_native_stops(self):
        c=machine();pair(c);c.w(ACTORS[2]+2380,240)
        for reg in range(1,31):
            if reg not in (28,29):c.r[reg]=0xABCD0000+reg
        before=c.r.copy()
        watched=[(actor,0x1600)for actor in ACTORS]+[(model,0x1700)for model in MODELS]+[(MANAGER,700),(CINE,832)]
        old=[c.read(at,size)for at,size in watched]
        self.assertEqual(run(c,p.PROTECT_ACTIVE),7)
        self.assertEqual(c.r[:2]+c.r[3:31],before[:2]+before[3:31])
        self.assertEqual(old,[c.read(at,size)for at,size in watched])

    def test_preceding_protection_upgrades_only_exact_emission(self):
        import four_player_mode as four
        ram=bytearray(0x8000000)
        def w(at,value):struct.pack_into('<I',ram,at,value)
        w(p.core.ACTORS,MANAGER);w(p.core.MODE+4,6);w(p.team_intro.BATTLE,BATTLE)
        struct.pack_into('<4I',ram,p.CONTROL,p.MAGIC,MANAGER,6,BATTLE);w(p.CONTROL+p.TRANSFORM_VIEW,1)
        prior=p.program(participants=True,independent=False)+p.hooks()
        for at,data in prior:ram[at:at+len(data)]=data
        frame=p.pause.frame_code();ram[p.pause.FRAME+8:p.pause.FRAME+len(frame)]=frame[8:]
        with patch.object(four,'dependency_override',side_effect=lambda r,a,b:b), \
             patch.object(p.pause,'identity',return_value=(MANAGER,6,BATTLE,ACTORS)), \
             patch.object(p,'elf_reader',return_value=(b'',[],lambda a,n:bytes(n))):
            self.assertEqual(dict(p.validate_memory(ram)),dict(prior))
            ram[p.PROTECT_ACTIVE+20]=1
            with self.assertRaisesRegex(ValueError,'upgrade extension occupied'):
                p.build_memory(ram)
            ram[p.PROTECT_ACTIVE+20]=0
            result=p.build_memory(ram)
            # The same upgrade also installs the admitted-form gate (FORM_GATE/FORM_TRACK and its three call sites).
            self.assertEqual({b['address']for b in result['blocks']},{p.PROTECT,p.PROTECT_ACTIVE,p.PREPARE,p.STORE,p.SHARED_FORM,
                                                                  p.ULTIMATE_FRAME,p.FORM_GATE,p.FORM_TRACK})
            for block in result['blocks']:
                at=block['address'];data=bytes.fromhex(block['data_hex']);ram[at:at+len(data)]=data
            self.assertEqual(p.build_memory(ram)['blocks'],[])
            ram[p.PROTECT_ACTIVE+20]^=1
            with self.assertRaises(ValueError):p.validate_memory(ram)

    def test_new_helpers_fit_all_existing_cinematic_reservations(self):
        parts=sorted(p.program(participants=True)+p.hooks())
        self.assertTrue(all(a+len(data)<=b for (a,data),(b,_)in zip(parts,parts[1:])))
        self.assertLessEqual(p.COOP_FUSION+len(p.coop_fusion()),p.PROTECT_ACTIVE)
        self.assertLessEqual(p.PROTECT_ACTIVE+len(p.protect_active()),p.OLD_PREPARE)


if __name__=='__main__':unittest.main()
