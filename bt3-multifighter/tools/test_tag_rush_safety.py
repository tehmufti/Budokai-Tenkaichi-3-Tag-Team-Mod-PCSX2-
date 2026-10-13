"""Execute generated tag contact/damage/placement routines without PCSX2."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest
from prototype import Assembler
from native_map import FLAG
import tag_rush_safety as tag
import tag_rush_camera as cam
import cinematic_contact_guard as contact
import beam_struggle as beam
import guest_killfeed as feed
import team_participation as part
from test_tag_rush_camera import CameraCpu, MANAGER, run
from test_guest_killfeed import make as feed_cpu, ACTORS, event

ACTOR=0x2200000
MODEL=0x2300000
OLD_CONTACT=0x070B6800
JUMP=lambda p:struct.pack('<2I',0x08000000|(p>>2),0)


def control(c,*,active=1,initiator=0,victim=1,count=6,members=7):
    manager=getattr(c,'manager',MANAGER)
    c.w(c.r[28]-22364,manager);c.w(manager,2)
    c.write(cam.core.MODE,struct.pack('<4I',1,count,manager,count))
    c.write(cam.CONTROL,struct.pack('<10I',cam.MAGIC,manager,count,1,active,members,0,initiator,2,victim))


class SafetyCpu(CameraCpu):
    def extra_instruction(self,ins,pc):
        op,rs,rt,rd,fn=ins>>26,(ins>>21)&31,(ins>>16)&31,(ins>>11)&31,ins&63
        if op==0 and fn==6:self.r[rd]=(self.r[rt]&0xFFFFFFFF)>>(self.r[rs]&31);return
        if op==0 and fn==0x27:self.r[rd]=~(self.r[rs]|self.r[rt])&0xFFFFFFFF;return
        if op==17 and rs==16 and fn==4:self.set_number((ins>>6)&31,math.sqrt(self.number(rt)));return
        return super().extra_instruction(ins,pc)


def machine():
    c=SafetyCpu({'segments':[dict(address=p,data_hex=b.hex()) for p,b in tag.pieces(JUMP(OLD_CONTACT))]})
    control(c)
    for i in range(6):
        actor=ACTOR+0x2000*i;model=MODEL+0x2000*i
        c.w(cam.core.POINTERS+4*i,actor);c.w(actor,i);c.w(actor+12,i)
        c.w(cam.core.MODELS+4*i,model);c.w(model+16,i);c.w(model+4,1);c.w(model+8,1)
        c.w(model+2332,0x2500000+0x100*i)
        c.w(actor+0x994,0);c.w(actor+0x9E4,30000);c.w(actor+2376,11)
        for off in (2380,2388,2392,2396,2400):c.w(actor+off,0xFFFFFFFF)
    c.w(part.CONTROL+12,63);c.w(part.CONTROL+16,0)
    c.callbacks[OLD_CONTACT]=lambda m:m.r.__setitem__(2,99)
    return c


class SafetyTests(unittest.TestCase):
    def test_only_victim_knockback_flight_is_admitted_with_all_native_guards(self):
        for action in (11,55,213,214,223,180,181,183,188,192,212,215,216,217,224,261,285,303,314):
            for entry,expected in ((tag.PREFLIGHT,action in (11,55)),
                                   (tag.VICTIM_PREFLIGHT,action in (11,55,213,214,217,223))):
                c=machine();c.w(ACTOR+2376,action)
                flag=FLAG(0xE);c.write(ACTOR+0x1085+(flag>>3),bytes([1<<(flag&7)]))
                before=c.read(ACTOR,0x1600);c.r[4]=ACTOR;run(c,entry)
                self.assertEqual(c.r[2],int(expected),(action,entry));self.assertEqual(c.read(ACTOR,0x1600),before)
        for off,value in ((2380,11),(2388,261),(3480,1),(3500,1),(3512,1),(0xFE0,1),(4896,1),(0x9E4,0)):
            c=machine();c.w(ACTOR+2376,213);c.w(ACTOR+off,value);before=c.read(ACTOR,0x1600)
            c.r[4]=ACTOR;run(c,tag.VICTIM_PREFLIGHT);self.assertEqual(c.r[2],0,off);self.assertEqual(c.read(ACTOR,0x1600),before)
        for original in (0x94,0xB,0xBE,0x125,0x126,0x135):
            for bank in (0x1085,0x10AD):
                c=machine();c.w(ACTOR+2376,214);flag=FLAG(original);c.write(ACTOR+bank+(flag>>3),bytes([1<<(flag&7)]))
                c.r[4]=ACTOR;run(c,tag.VICTIM_PREFLIGHT);self.assertEqual(c.r[2],0,(original,bank))

    def test_victim_native_fall_transition_is_not_mistaken_for_a_pending_hit(self):
        for action in tag.LAUNCHED_ACTIONS:
            c=machine();c.w(ACTOR+2376,action);c.w(ACTOR+2380,217)
            before=c.read(ACTOR,0x1600);c.r[4]=ACTOR;run(c,tag.VICTIM_PREFLIGHT)
            self.assertEqual(c.r[2],1);self.assertEqual(c.read(ACTOR,0x1600),before)
            c.r[4]=ACTOR;run(c,tag.PREFLIGHT);self.assertEqual(c.r[2],0)
        for action,pending,queue in ((11,217,None),(217,217,None),(213,192,None),(213,215,None),
                                     (213,225,None),(213,303,None),(213,217,2388),(214,217,2392),
                                     (223,217,2396),(213,217,2400)):
            c=machine();c.w(ACTOR+2376,action);c.w(ACTOR+2380,pending)
            if queue:c.w(ACTOR+queue,217)
            before=c.read(ACTOR,0x1600);c.r[4]=ACTOR;run(c,tag.VICTIM_PREFLIGHT)
            self.assertEqual(c.r[2],0,(action,pending,queue));self.assertEqual(c.read(ACTOR,0x1600),before)
        for off,value in ((4896,1),(3500,1),(0xFE0,1),(0x9E4,0)):
            c=machine();c.w(ACTOR+2376,213);c.w(ACTOR+2380,217);c.w(ACTOR+off,value)
            c.r[4]=ACTOR;run(c,tag.VICTIM_PREFLIGHT);self.assertEqual(c.r[2],0,off)
        for original in (0x94,0xB,0xBE,0x125,0x126,0x135):
            for bank in (0x1085,0x10AD):
                c=machine();c.w(ACTOR+2376,213);c.w(ACTOR+2380,217);flag=FLAG(original)
                c.write(ACTOR+bank+(flag>>3),bytes([1<<(flag&7)]));c.r[4]=ACTOR
                run(c,tag.VICTIM_PREFLIGHT);self.assertEqual(c.r[2],0,(original,bank))

    def test_preflight_rejects_native_giant_in_every_role_without_writes(self):
        import giant_options as giants
        for index in (0,2,1):
            for enabled in (0,1):
                c=machine();c.write(giants.CONTROL,struct.pack('<4If',giants.MAGIC,MANAGER,6,enabled,3.0))
                c.write(0x2500000+0x100*index+2,b'\x04');actor=ACTOR+0x2000*index
                before=c.read(actor,0x1600);c.r[4]=actor;run(c,tag.PREFLIGHT)
                self.assertEqual(c.r[2],0);self.assertEqual(c.read(actor,0x1600),before)
        for size_class in (0,1,2,3,5):
            c=machine();c.write(0x2500002,bytes([size_class]));c.r[4]=ACTOR;run(c,tag.PREFLIGHT)
            self.assertEqual(c.r[2],1)

    def test_preflight_rejects_individual_native_hit_stop_without_clearing_it(self):
        c=machine();c.w(ACTOR+4896,2);before=c.read(ACTOR,0x1600)
        c.r[4]=ACTOR;run(c,tag.PREFLIGHT)
        self.assertEqual(c.r[2],0);self.assertEqual(c.read(ACTOR,0x1600),before)

    def test_protected_members_block_both_contact_directions_not_bystanders(self):
        for source,target,expected in ((0,4,1),(4,0,1),(1,2,1),(4,5,99)):
            c=machine();c.r[4:6]=[ACTOR+source*0x2000,ACTOR+target*0x2000]
            run(c,tag.CONTACT);self.assertEqual(c.r[2],expected)
            c.w(cam.CONTROL+16,0);run(c,tag.CONTACT);self.assertEqual(c.r[2],99)
        c=machine();c.w(cam.CONTROL+4,MANAGER+16);c.r[4:6]=[ACTOR,ACTOR+0x2000]
        run(c,tag.CONTACT);self.assertEqual(c.r[2],99)
        c=machine();c.w(cam.CONTROL+cam.SHARED,1);c.r[4:6]=[ACTOR+4*0x2000,ACTOR+5*0x2000]
        run(c,tag.CONTACT);self.assertEqual(c.r[2],1)

    def test_native_or_previous_contact_chain_is_preserved(self):
        self.assertEqual(tag.trampoline_code(JUMP(OLD_CONTACT)),JUMP(OLD_CONTACT))
        code=tag.trampoline_code(contact.protected_code());self.assertLess(len(code),tag.DAMAGE-tag.TRAMPOLINE)
        for bad in (bytes(8),JUMP(tag.CONTACT),JUMP(0x100000)):
            with self.assertRaises(ValueError):tag.trampoline_code(bad)
        ram=bytearray(0x8000000);ram[contact.PROTECTED:contact.PROTECTED+8]=JUMP(OLD_CONTACT)
        plan=tag.build_memory(ram)
        self.assertEqual(plan['blocks'][-1]['expected_hex'],JUMP(OLD_CONTACT).hex())
        self.assertEqual(plan['blocks'][-1]['data_hex'],JUMP(tag.CONTACT).hex())

    def test_preflight_waits_for_existing_damage_and_preserves_pending_state(self):
        c=machine();c.r[4]=ACTOR;run(c,tag.PREFLIGHT);self.assertEqual(c.r[2],1)
        for off,value in ((2380,34),(2388,301),(3480,1),(3500,1),(3512,1),(0xFE0,1),(2376,314)):
            c=machine();c.w(ACTOR+off,value);before=c.read(ACTOR,0x1300);c.r[4]=ACTOR
            run(c,tag.PREFLIGHT);self.assertEqual(c.r[2],0,off);self.assertEqual(c.read(ACTOR,0x1300),before)
        for flag in (0x94,0xB,0xBE,0x125,0x126,0x135):
            c=machine();f=FLAG(flag);c.write(ACTOR+0x1085+(f>>3),bytes([1<<(f&7)]));c.r[4]=ACTOR
            run(c,tag.PREFLIGHT);self.assertEqual(c.r[2],0,hex(flag))
        c=machine();c.w(part.CONTROL+16,1);c.r[4]=ACTOR;run(c,tag.PREFLIGHT);self.assertEqual(c.r[2],0)

    def test_finisher_uses_existing_damage_and_credits_initiator_once(self):
        c=feed_cpu();control(c,initiator=2,victim=3,members=(1<<2)|(1<<3)|(1<<4))
        c.write(tag.DAMAGE,tag.damage_code());c.write(feed.DAMAGE_ENTRY,JUMP(feed.DAMAGE))
        c.r[4:7]=[ACTORS[3],15000,0x2000000];run(c,tag.DAMAGE)
        self.assertEqual(c.r[2],1);self.assertEqual(c.u(ACTORS[3]+0x9E4),0)
        self.assertEqual(event(c)[1:5],(3,2,3,2));self.assertEqual(c.u(feed.CONTROL+16),1)
        self.assertEqual(c.u(feed.CONTROL+20),0);self.assertEqual(c.u(tag.DAMAGE_DONE),1)
        c.r[4:7]=[ACTORS[3],15000,0x2000000];run(c,tag.DAMAGE)
        self.assertEqual(c.r[2],0);self.assertEqual(c.u(feed.CONTROL+16),1)
        # A different victim cannot borrow this attribution.
        c.w(tag.DAMAGE_DONE,0);c.r[4:7]=[ACTORS[5],15000,0x2000000];run(c,tag.DAMAGE)
        self.assertEqual(c.r[2],0);self.assertEqual(c.u(ACTORS[5]+0x9E4),100)

    def test_tag_damage_respects_scenario_nonlethal_and_attacker_stats(self):
        from test_story_rules import document
        from test_story_missions import machine as story_cpu
        import story_rules as rules
        import story_runtime as story
        for valid in (False,True):
            d=document();d['fighters'][0]['stats']={'damage':2}
            c=story_cpu(d);control(c,initiator=0,victim=1,count=len(c.actors))
            c.write(tag.DAMAGE,tag.damage_code());c.write(rules.DAMAGE,rules.damage_code(d));c.w(rules.CONTROL,rules.MAGIC)
            c.write(rules.STATS,rules.stats_data(d));c.write(feed.DAMAGE_ENTRY,JUMP(story.DAMAGE))
            previous=0x110000;c.write(story.DAMAGE,story.protection_code(story.DAMAGE,previous));seen=[]
            def apply(m):
                seen.append(tuple(m.r[4:7]));hp=m.u(m.r[4]+0x9E4)
                m.w(m.r[4]+0x9E4,max(1 if m.r[6]&0x400 else 0,hp-m.r[5]))
            c.callbacks[previous]=apply;c.r[4:7]=[c.actors[1],15000,0x2000000 if valid else 0]
            run(c,tag.DAMAGE);self.assertEqual(len(seen),1);self.assertEqual(seen[0][1],30000)
            self.assertEqual(bool(seen[0][2]&0x400),not valid)

    def test_placement_clamps_live_arena_terrain_and_resets_sweep(self):
        for requested,floor,height in (((2000,-50,0),None,-50),((10,2000,20),None,490),((10,50,20),-5,-5)):
            c=machine();pos,rot=0x2410000,0x2410100;stage,bounds=0x2420000,0x2430000
            c.write(pos,struct.pack('<4f',*requested,1));c.write(rot,struct.pack('<4f',0,1.2,0,1))
            c.w(beam.arena_bounds.STAGE,stage);c.w(stage+64,bounds);c.write(bounds,struct.pack('<3f',1000,-500,500))
            seen=[]
            def query(m):
                m.r[2]=int(floor is not None)
                if floor is not None:m.fw(m.r[4]+12,floor)
            def place(m):
                xyz=struct.unpack('<4f',m.read(m.r[5],16));seen.append(xyz)
                m.write(m.r[4]+16,m.read(m.r[5],16));self.assertAlmostEqual(m.fr(m.r[6]+4),1.2,places=5)
            c.callbacks[tag.FLOOR]=query;c.callbacks[beam.SECTOR]=lambda m:m.r.__setitem__(2,7)
            c.callbacks[beam.SET_ROOT]=place
            for addr in (*beam.MODEL_REFRESH,beam.MODEL_SPHERES,beam.ROOT_SYNC):c.callbacks[addr]=lambda m:None
            c.r[4:7]=[ACTOR,pos,rot];run(c,tag.PLACE);self.assertEqual(c.r[2],1)
            self.assertLessEqual(math.hypot(seen[0][0],seen[0][2]),890.001);self.assertEqual(seen[0][1],height)
            self.assertEqual(c.read(ACTOR+16,240),c.read(ACTOR+256,240))
        c=machine();c.r[4:7]=[ACTOR,0,0];run(c,tag.PLACE);self.assertEqual(c.r[2],0)


if __name__=='__main__':unittest.main()
