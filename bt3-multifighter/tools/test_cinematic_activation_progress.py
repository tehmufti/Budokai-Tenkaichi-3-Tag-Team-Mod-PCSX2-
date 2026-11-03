"""Concurrent native activations must release their own pause handshakes."""
import struct
import unittest
from unittest.mock import patch
from native_map import GPO
import cinematic_policy as p
import four_player_mode as four
from guest_policy_fixture import ACTORS,MODELS,MANAGER,BATTLE
from test_concurrent_cinematic_progress import machine,run


def current_machine():
    c=machine(shared_rush=False)
    for at,data in p.program(participants=True,form_gate=True,view_grace=True,concurrent=True):c.write(at,data)
    c.write(p.continuity.LOOKUP,p.continuity.lookup_code())
    # The pause capture and battle manager are valid and not loading a stage.
    c.w(c.r[28]+GPO(-22364),MANAGER)
    for i,actor in enumerate(ACTORS):c.w(p.pause.CONTROL+0x80+4*i,actor)
    return c


def action(c,who,value,flag=True):
    c.w(ACTORS[who]+2376,value)
    if flag:
        c.write(ACTORS[who]+p.PRIORITY_FLAG_BYTES[0],bytes([p.PRIORITY_FLAG_BIT]))
        c.write(ACTORS[who]+p.ULTIMATE_FLAG_BYTES[0],bytes([p.ULTIMATE_FLAG_MASK]))


class ActivationProgressTests(unittest.TestCase):
    def test_leader_form_with_leader_ultimate_and_extra_special(self):
        c=current_machine()
        for i,value in enumerate((284,236,263)):action(c,i,value)
        run(c,p.PREPARE)
        self.assertEqual(c.u(p.CONTROL+p.FORM_FORCE),1)
        self.assertEqual(c.u(p.pause.CONTROL+52)&7,7)
        for i,actor in enumerate(ACTORS):
            c.r[16]=actor;c.r[17]=i+1;c.r[18]=7;run(c,p.STORE)
        self.assertEqual([c.u(a+4900)for a in ACTORS],[0,0,0,7,7,7])
        run(c,p.ULTIMATE_STOP)
        self.assertEqual([c.u(a+4896)for a in ACTORS],[0,0,0,1,1,1])
        # The form finishes; none of the old holds survive the next update.
        for i in range(3):
            action(c,i,11,False)
            for off in p.PRIORITY_FLAG_BYTES+p.ULTIMATE_FLAG_BYTES:c.write(ACTORS[i]+off,b'\0')
        # Native actor update consumes the one-tick hold before this hook.
        for actor in ACTORS:c.w(actor+4896,max(0,c.u(actor+4896)-1))
        run(c,p.PREPARE);run(c,p.ULTIMATE_STOP)
        self.assertEqual(c.u(p.CONTROL+p.FORM_FORCE),0)
        self.assertEqual([c.u(a+4896)for a in ACTORS],[0]*6)

    def test_every_live_special_and_both_native_flag_banks(self):
        for value in range(253,316):
            for off,bit in [(o,p.ULTIMATE_FLAG_MASK)for o in p.ULTIMATE_FLAG_BYTES]+[(o,p.PRIORITY_FLAG_BIT)for o in p.PRIORITY_FLAG_BYTES]:
                c=current_machine();action(c,4,value,False);c.write(ACTORS[4]+off,bytes([bit]))
                self.assertEqual(run(c,p.PROTECT_ACTIVE),1<<4,(value,off))

    def test_stale_flags_idle_unloaded_or_dead_fighters_are_not_exempt(self):
        for fault in ('idle','history','unflagged','dead','unloaded','actor','model'):
            c=current_machine();action(c,4,263)
            if fault=='idle':c.w(ACTORS[4]+2376,11)
            if fault=='history':c.w(ACTORS[4]+2376,11);c.w(ACTORS[4]+2384,263)
            if fault=='unflagged':
                for off in p.PRIORITY_FLAG_BYTES+p.ULTIMATE_FLAG_BYTES:c.write(ACTORS[4]+off,b'\0')
            if fault=='dead':c.w(ACTORS[4]+0x9e4,0)
            if fault=='unloaded':c.w(MODELS[4]+4,0)
            if fault=='actor':c.w(ACTORS[4],1)
            if fault=='model':c.w(MODELS[4]+16,1)
            self.assertEqual(run(c,p.PROTECT_ACTIVE),0,fault)

    def test_current_and_previous_emissions_upgrade_without_overwriting_other_code(self):
        ram=bytearray(0x8000000)
        def w(at,value):struct.pack_into('<I',ram,at,value)
        w(p.core.ACTORS,MANAGER);w(p.core.MODE+4,6);w(p.team_intro.BATTLE,BATTLE)
        struct.pack_into('<4I',ram,p.CONTROL,p.MAGIC,MANAGER,6,BATTLE);w(p.CONTROL+p.TRANSFORM_VIEW,1)
        prior=p.program(participants=True,form_gate=True,view_grace=True)+p.hooks()
        for at,data in prior:ram[at:at+len(data)]=data
        frame=p.pause.frame_code();ram[p.pause.FRAME+8:p.pause.FRAME+len(frame)]=frame[8:]
        with patch.object(four,'dependency_override',side_effect=lambda r,a,b:b), \
             patch.object(p.pause,'identity',return_value=(MANAGER,6,BATTLE,ACTORS)), \
             patch.object(p,'elf_reader',return_value=(b'',[],lambda a,n:bytes(n))):
            self.assertEqual(dict(p.validate_memory(ram)),dict(prior))
            result=p.build_memory(ram)
            self.assertEqual({b['address']for b in result['blocks']},{p.PREPARE,p.PROTECT_ACTIVE})
            for block in result['blocks']:
                at=block['address'];data=bytes.fromhex(block['data_hex']);ram[at:at+len(data)]=data
            self.assertEqual(p.build_memory(ram)['blocks'],[])
            ram[p.PROTECT_ACTIVE+24]^=1
            with self.assertRaises(ValueError):p.validate_memory(ram)
        parts=sorted(p.program(participants=True,form_gate=True,view_grace=True,concurrent=True)+p.hooks())
        self.assertTrue(all(at+len(data)<=end for (at,data),(end,_)in zip(parts,parts[1:])))


if __name__=='__main__':unittest.main()
