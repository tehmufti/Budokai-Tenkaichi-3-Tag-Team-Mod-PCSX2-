"""Native leader fusion eligibility/commit and actual partner ownership."""
import copy
import struct
import unittest

import fusion_partner_lifecycle as fix
import team_participation as participation
from test_extra_special_pools import Cpu


class FusionCpu(Cpu):
    def __init__(self):
        super().__init__({'segments':[]});self.fcr31=0
    def extra_instruction(self,ins,pc):
        op,rs,rt,rd=ins>>26,(ins>>21)&31,(ins>>16)&31,(ins>>11)&31
        if op==17 and rs in (2,6):
            if rs==2:self.r[rt]=self.fcr31
            else:self.fcr31=self.r[rt]&0xFFFFFFFF
            return None
        if op==28 and ins&63==24:
            value=self.signed_word(self.r[rs])*self.signed_word(self.r[rt])
            self.r[rd]=value&0xFFFFFFFF;return None
        return super().extra_instruction(ins,pc)


def machine(side=0,slot=1,mask=63):
    c=FusionCpu();c.events=[]
    for p,b in fix.pieces():c.write(p,b)
    for p,n in ((0x203788,0x178),(0x2039B0,0x168),(0x1C0538,0x570),
                (0x1DC0B8,0x28),(0x1E02A8,0x68),(0x1E0290,0x18),(0x2EE2D0,0x140)):
        c.write(p,fix.NATIVE(p,n))
    c.manager=0x1800000;c.actors=[0x1900000+i*0x2000 for i in range(6)]
    c.models=[0x900000+i*0x2000 for i in range(6)];c.ids=[0,1,7,10,3,8]
    for p,v in ((fix.core.ACTORS,c.manager),(c.manager,2),
                (fix.CONTROL,1),(fix.CONTROL+4,c.manager),(fix.CONTROL+8,6),
                (fix.PART_CONTROL,5),(fix.PART_CONTROL+4,c.manager),(fix.PART_CONTROL+8,6),
                (fix.PART_CONTROL+12,mask),(fix.core.MODE,1),(fix.core.MODE+4,6),
                (fix.core.MODE+8,c.manager),(fix.core.MODE+12,6),
                (fix.transport.CONTROL,fix.transport.MAGIC)):
        c.w(p,v)
    c.w(c.manager+4,c.actors[0]);c.w(c.manager+48,0x1700000)
    for i,actor in enumerate(c.actors):
        c.w(fix.core.POINTERS+4*i,actor);c.w(fix.core.MODELS+4*c.ids[i],c.models[i])
        for off,v in ((0,i),(8,i&1),(12,c.ids[i]),(0x994,i//2),(0x998,3),(2376,11),(2380,-1)):
            c.w(actor+off,v)
        row=actor+0x9A4+164*(i//2)
        for off,v in ((0,3 if i==side else 34+i),(4,0),(8,1),(12,i),(64,10000+i*1000),
                      (68,30000),(76,100),(80,100),(84,10),(88,10000),(112,0)):
            c.w(row+off,v)
        c.w(c.models[i]+4,1);c.w(c.models[i]+12,c.u(row));c.w(c.models[i]+16,c.ids[i]);c.w(c.models[i]+8,1)
        c.w(fix.PART_ROWS+64*i,actor);c.w(fix.PART_ROWS+64*i+4,c.models[i])
        c.w(fix.PART_ROWS+64*i+8,c.ids[i]);c.w(fix.PART_ROWS+64*i+12,i)
        c.w(fix.PART_ROWS+64*i+16,row);c.w(fix.PART_ROWS+64*i+24,i&1)
        for s in range(3):
            bench=actor+0x9A4+164*s
            if s!=i//2:
                c.w(bench,199);c.w(bench+8,1);c.w(bench+64,99999)
    source=c.actors[side];partner=2*slot+side;own=source+0x9A4
    c.source,c.partner,c.slot=source,partner,slot
    c.w(source+1216*4,1);c.w(source+4856,slot);c.w(source+4816,48)
    c.w(0x1700000+16*3+12,1)
    for p in (0x1CF0C8,0x1DAC78,0x1DC348):c.callbacks[p]=lambda m:m.r.__setitem__(2,0)
    for p in (0x12B4F0,0x1CED60):c.callbacks[p]=lambda m:m.r.__setitem__(2,1)
    for p,v in ((0x20E340,48),(0x20E3E8,2),(0x20E450,1),(0x20E370,0)):
        c.callbacks[p]=lambda m,v=v:m.r.__setitem__(2,v)
    c.callbacks[0x20E3A0]=lambda m:m.r.__setitem__(2,m.u(fix.PART_ROWS+64*partner+16) and m.u(m.u(fix.PART_ROWS+64*partner+16)))
    def find(m):
        rows=[m.r[4]+0x9A4+164*s for s in range(m.u(m.r[4]+0x998))]
        m.r[2]=next((i for i,p in enumerate(rows) if m.u(p)==m.r[5]),0xFFFFFFFF)
    c.callbacks[0x1CE108]=find
    c.callbacks[0x1CE030]=lambda m:m.r.__setitem__(2,m.r[4]+0x9A4+164*m.r[5])
    c.callbacks[0x1CE198]=lambda m:m.r.__setitem__(2,m.r[4]+0x9E4+164*m.r[5])
    c.callbacks[0x1CE050]=lambda m:m.r.__setitem__(2,m.r[4]+0x9A4+164*m.u(m.r[4]+0x994))
    c.callbacks[0x1CE1B8]=lambda m:m.r.__setitem__(2,m.r[4]+0x9E4+164*m.u(m.r[4]+0x994))
    for p in (0x1C0058,0x1DABE8,0x1C42A8,0x24C958,0x1D7198,0x24E3F8,0x1DA9D0,0x24FE78):
        c.callbacks[p]=lambda m:None
    c.callbacks[0x1DC280]=lambda m:m.r.__setitem__(2,m.u(fix.core.MODELS+4*m.u(m.r[4]+12)))
    c.callbacks[0x1E0358]=lambda m:m.r.__setitem__(2,m.u(m.r[4]+2376))
    c.callbacks[0x20E280]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x20E480]=lambda m:m.r.__setitem__(2,0)
    def drain(m):m.events.append(('drain',m.r[4]));m.r[2]=1
    c.callbacks[fix.CLEANUP]=drain
    c.write(fix.CONSUME,participation.consume_code())
    c.w(participation.feed.CONTROL+4,c.manager)
    c.r[4:9]=[source,0,1,0,0x1600000];c.r[16:24]=[0xABCDEF0000000000+i for i in range(8)]
    return c


class RamCpu(FusionCpu):
    def __init__(self,ram):self.buffer=bytearray(ram);super().__init__()
    def read(self,p,n):
        assert 0<=p<=len(self.buffer)-n,hex(p)
        return bytes(self.buffer[p:p+n])
    def write(self,p,data):
        assert 0<=p<=len(self.buffer)-len(data),hex(p)
        self.buffer[p:p+len(data)]=data


class FusionTests(unittest.TestCase):
    def test_sync_actual_partner_scalars_preserves_pointer_fields_and_other_side(self):
        c=machine();source=c.source;before=c.read(c.actors[1],0x1600)
        c.w(source+0x9A4+164+120,0xDEADC0DE);saved=c.r.copy();c.run(fix.SYNC)
        self.assertEqual(c.r[2],1)
        for i,r in enumerate(saved):
            if i!=2:self.assertEqual(c.r[i],r,i)
        self.assertEqual(c.u(source+0x9A4+164+64),12000)
        self.assertEqual(c.u(source+0x9A4+164+120),0xDEADC0DE)
        self.assertEqual(c.read(c.actors[1],0x1600),before)

    def test_transformed_partner_resolves_current_slot_and_actual_model(self):
        c=machine();actor=c.actors[2];old=c.read(actor+0x9A4+164,164)
        c.write(actor+0x9A4,old);c.w(actor+0x994,0)
        c.w(actor+12,11);c.w(fix.core.MODELS+44,c.models[2]);c.w(c.models[2]+16,11)
        c.w(actor+0x9A4+64,22222);c.run(fix.SYNC)
        self.assertEqual(c.u(c.source+0x9A4+164+64),22222)
        c.w(c.source+2376,241);c.run(fix.COMMIT)
        self.assertEqual(c.events,[('drain',11)])
        self.assertEqual(c.u(fix.PART_CONTROL+16),4)

    def test_native_eligibility_selects_actual_slot_and_rejects_dead_absent_consumed(self):
        for kind in ('alive','dead','absent','consumed'):
            c=machine(side=1,slot=2);row=c.u(fix.PART_ROWS+64*c.partner+16)
            if kind=='dead':c.w(row+64,0)
            if kind=='absent':c.w(fix.PART_CONTROL+12,63&~(1<<c.partner))
            if kind=='consumed':c.w(fix.PART_CONTROL+16,1<<c.partner)
            c.run(fix.ELIGIBILITY)
            self.assertEqual(c.r[2],int(kind=='alive'),kind)
            if kind=='alive':self.assertEqual(c.u(0x1600000),2)
            self.assertFalse(c.events)

    def test_begin_actual_native_queue_and_scripted_dead_rejection(self):
        for dead in (False,True):
            c=machine();c.r[6]=1
            if dead:c.w(c.u(fix.PART_ROWS+64*c.partner+16)+64,0)
            c.run(fix.BEGIN)
            self.assertEqual(c.r[2],int(not dead))
            if not dead:
                self.assertEqual(c.u(c.source+4856),1)
                self.assertEqual(c.u(c.source+2388),241)
            self.assertFalse(c.events)

    def test_native_fusion_merge_then_only_matched_npc_consumed(self):
        for side,slot in ((0,1),(1,2)):
            c=machine(side,slot);c.w(c.source+2376,241)
            hp=c.u(c.source+0x9E4)+c.u(c.u(fix.PART_ROWS+64*c.partner+16)+64)
            other={i:c.read(a,0x1600) for i,a in enumerate(c.actors) if i not in (side,c.partner)}
            c.run(fix.COMMIT)
            self.assertEqual(c.u(c.source+0x9A4),48)
            self.assertEqual(c.u(c.source+0x9E4),hp)
            self.assertEqual(c.u(fix.CONTROL+16),1)
            self.assertEqual(c.events,[('drain',c.ids[c.partner])])
            self.assertEqual(c.u(fix.PART_CONTROL+16),1<<c.partner)
            self.assertEqual(c.u(participation.feed.CONTROL+0x40+4*c.partner),1)
            self.assertEqual(c.u(c.actors[c.partner]+2376),216)
            self.assertEqual(c.u(c.models[c.partner]+8),0)
            self.assertEqual(c.u(c.models[side]+8),1)
            for i,data in other.items():self.assertEqual(c.read(c.actors[i],0x1600),data)

    def test_nonfusion_and_extra_initiation_keep_native_paths(self):
        c=machine();c.w(c.source+2376,11);before=c.read(c.source,0x1600);c.run(fix.COMMIT)
        self.assertEqual(c.read(c.source,0x1600),before);self.assertFalse(c.events)
        c=machine();c.r[4]=c.actors[2];before=c.read(c.actors[2],0x1600);c.run(fix.BEGIN)
        self.assertEqual(c.r[2],0);self.assertEqual(c.read(c.actors[2],0x1600),before)

    def test_busy_partner_and_invalid_model_rejected_before_native_queue(self):
        for field,value in [(fix.requests.RECORDS+4,x) for x in range(1,5)]+[(None,x) for x in (180,183,187,236,240,241,242,243)]:
            c=machine();c.r[6]=1
            c.w(c.actors[2]+2388 if field is None else field,value)
            c.run(fix.BEGIN);self.assertEqual(c.r[2],0,(field,value))
            self.assertEqual(c.u(c.source+2388),0)
        for pointer in (0,0xFFFFFFFC,0x7FFFFFF,0x900003):
            c=machine();c.w(fix.core.MODELS+4*c.ids[2],pointer);c.run(fix.ELIGIBILITY)
            self.assertEqual(c.r[2],0)

    def test_reservation_and_contact_follow_native_sequence_without_persistent_lock(self):
        for side,slot in ((0,1),(1,2)):
            for off in (2376,2380,2388,2392,2396,2400):
                c=machine(side,slot);c.w(c.source+off,242);c.r[4]=c.actors[c.partner]
                before=c.r.copy();c.run(fix.RESERVED)
                self.assertEqual(c.r[2],1)
                self.assertEqual(c.r[:2]+c.r[3:],before[:2]+before[3:])
                c.w(c.source+off,11);c.run(fix.RESERVED);self.assertEqual(c.r[2],0)
            c=machine(side,slot);c.w(c.source+2388,241)
            calls=[];c.callbacks[0x07522C00]=lambda q:(calls.append(1),q.r.__setitem__(2,47))
            for source,target,blocked in ((c.partner,1-side,True),(1-side,c.partner,True),(side,1-side,False)):
                c.r[4:6]=[c.actors[source],c.actors[target]];before=c.r.copy();c.run(fix.CONTACT)
                self.assertEqual(c.r[2],1 if blocked else 47)
                self.assertEqual(c.r[4:32],before[4:32])
            self.assertEqual(calls,[1])

    def test_real_native_effect_subtree_cleanup_only_selected_owner(self):
        # Actual saved native callback trees run, including1ADA80/1AD6A8,
        # ordinary/giant/afterimage destructors and bump-allocator frees.
        # No native callback is mocked in this test.
        ram=(fix.ROOT/'analysis/native-form-repeated-3/final.bin').read_bytes()
        for physical in range(2,6):
            c=RamCpu(ram)
            for p,data in fix.pieces():c.write(p,data)
            manager=c.u(fix.core.ACTORS);c.w(fix.CONTROL,1);c.w(fix.CONTROL+4,manager);c.w(fix.CONTROL+8,6)
            actors=[c.u(fix.core.POINTERS+4*i) for i in range(6)]
            for i,actor in enumerate(actors):c.w(fix.PART_ROWS+64*i,actor)
            mid=c.u(actors[physical]+12);models=[c.u(fix.core.MODELS+4*c.u(a+12)) for a in actors]
            untouched=[(a,c.read(a,0x1600)) for a in actors]+[(m,c.read(m,0x1670)) for m in models]
            allocator=c.u(fix.special.ALLOC_GLOBAL);saved=c.read(allocator,156);kernel=c.read(0,0x1000)
            other_rows=[(p,c.read(p,n)) for i,a in enumerate(actors) if i!=physical for p,n in
                        ((fix.special.ROWS+1344*c.u(a+12),1344),(fix.generic.ROWS+48*c.u(a+12),48))]
            c.r[4]=mid;c.run(fix.CLEANUP)
            self.assertEqual(c.r[2],1);self.assertEqual(c.read(allocator,156),saved)
            self.assertEqual(c.read(0,0x1000),kernel)
            self.assertEqual(c.u(fix.special.ROWS+1344*mid+1324),0)
            self.assertEqual(c.u(fix.generic.ROWS+48*mid),0)
            for p,data in untouched+other_rows:self.assertEqual(c.read(p,len(data)),data,hex(p))

    def test_cleanup_rejects_foreign_visual_before_first_destructor(self):
        ram=(fix.ROOT/'analysis/native-form-repeated-3/final.bin').read_bytes();c=RamCpu(ram)
        for p,data in fix.pieces():c.write(p,data)
        manager=c.u(fix.core.ACTORS);c.w(fix.CONTROL,1);c.w(fix.CONTROL+4,manager);c.w(fix.CONTROL+8,6)
        for i in range(6):c.w(fix.PART_ROWS+64*i,c.u(fix.core.POINTERS+4*i))
        mid=c.u(c.u(fix.core.POINTERS+8)+12);node,body=0x6800000,0x6800100
        c.w(fix.ordinary.TABLE+4*mid,node);c.w(node+56,body);c.w(body+100,mid)
        c.w(node+32,0xBAD0);c.w(node+40,0x2C3A48)
        calls=[];c.callbacks[0x1ADA80]=lambda q:calls.append(q.r[4]);c.callbacks[fix.ground.CLEANUP]=lambda q:calls.append('ground')
        c.r[4]=mid;c.run(fix.CLEANUP);self.assertEqual(c.r[2],0);self.assertEqual(calls,[])

    def test_native_diagnostic_calls_eligibility_and_begin_once_and_keeps_registers(self):
        import live_fusion_check as diagnostic
        c=machine();previous=0x7730000;c.write(diagnostic.CODE,diagnostic.payload(previous))
        c.callbacks[previous]=lambda q:None
        c.write(diagnostic.CONTROL,struct.pack('<6I',1,c.manager,6,0,0,1))
        c.w(diagnostic.CONTROL+44,c.source)
        for off in (2380,2388,2392,2396,2400):c.w(c.source+off,-1)
        for p,to in ((0x203788,fix.ELIGIBILITY),(0x2039B0,fix.BEGIN)):
            c.write(p,struct.pack('<2I',(2<<26)|(to>>2),0))
        saved=c.r.copy();c.run(diagnostic.CODE)
        self.assertEqual(c.r,saved)
        self.assertEqual([c.u(diagnostic.CONTROL+off) for off in (20,28,32,36,40)],[0,1,1,1,1])
        self.assertEqual(c.u(c.source+2388),241)
        c.run(diagnostic.CODE);self.assertEqual(c.u(diagnostic.CONTROL+28),1)

    def test_cleanup_failure_holds_instead_of_consuming_partial_result(self):
        c=machine();c.w(c.source+2376,242)
        c.callbacks[fix.CLEANUP]=lambda m:m.r.__setitem__(2,0)
        c.run(fix.COMMIT)
        self.assertEqual(c.u(fix.CONTROL+28),110)
        self.assertEqual(c.u(fix.transport.CONTROL+16),1)
        self.assertFalse(c.events);self.assertEqual(c.u(fix.PART_CONTROL+16),0)


if __name__=='__main__':unittest.main()
