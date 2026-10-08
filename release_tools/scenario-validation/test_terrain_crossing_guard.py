"""Execute emitted scalar-FPU recovery and the native triangle floor test."""
import math
import struct
import unittest
from prototype import ROOT, elf_reader
from camera_snapshot import read_ram
from test_ai_shadow import Mips
import terrain_crossing_guard as terrain


class ScalarMips(Mips):
    def __init__(self, manifest):
        super().__init__(manifest); self.f=[0]*32; self.condition=False

    def number(self, r): return struct.unpack('<f', struct.pack('<I', self.f[r]))[0]
    def set_number(self, r, v): self.f[r]=struct.unpack('<I',struct.pack('<f',v))[0]
    def fw(self, p, v): self.write(p,struct.pack('<f',v))
    def fr(self, p): return struct.unpack('<f',self.read(p,4))[0]

    def extra_instruction(self, ins, pc):
        op,rs,rt,fs,fd,fn=ins>>26,(ins>>21)&31,(ins>>16)&31,(ins>>11)&31,(ins>>6)&31,ins&63
        imm=ins&65535; signed=imm if imm<32768 else imm-65536
        if op==49:self.f[rt]=self.u(self.r[rs]+signed)
        elif op==57:self.w(self.r[rs]+signed,self.f[rt])
        elif op==17 and rs==4:self.f[fs]=self.r[rt]&0xFFFFFFFF
        elif op==17 and rs==0:self.r[rt]=self.f[fs]
        elif op==17 and rs==8:
            taken=self.condition==bool(rt&1)
            return (pc+4+signed*4 if taken else None, bool(rt&2) and not taken)
        elif op==17 and rs==16:
            x,y=self.number(fs),self.number(rt)
            if fn in (0x34,0x36):self.condition=x<y if fn==0x34 else x<=y
            elif fn==5:self.f[fd]=self.f[fs]&0x7FFFFFFF
            elif fn==6:self.f[fd]=self.f[fs]
            elif fn in (0,1,2,3):
                v=x+y if fn==0 else x-y if fn==1 else x*y if fn==2 else x/y
                self.set_number(fd,v)
            else:return super().extra_instruction(ins,pc)
        else:return super().extra_instruction(ins,pc)


class TerrainCrossingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,_,native=elf_reader(ROOT/'analysis/SLUS_216.78');cls.native=staticmethod(native)

    def machine(self, previous=-15, current=15, dx=0, floor=-15, action=11, cinematic=False):
        c=ScalarMips({'segments':[dict(address=terrain.CODE,data_hex=terrain.payload().hex())]})
        manager,actor,model,sphere=0x1800000,0x1900000,0x900000,0x901100
        c.w(terrain.core.ACTORS,manager);c.w(manager,2)
        for off,v in ((0,1),(4,6),(8,manager),(12,6)):c.w(terrain.core.MODE+off,v)
        for off,v in ((0,1),(4,manager),(8,6)):c.w(terrain.CONTROL+off,v)
        for i in range(6):
            a=actor+i*0x2000;m=model+i*0x2000
            c.w(terrain.core.POINTERS+4*i,a);c.w(a+12,i);c.w(terrain.core.MODELS+4*i,m)
        c.w(model+4,1);c.w(model+8,1);c.w(actor+0x948,action);c.w(model+4000,sphere)
        c.fw(sphere+16,6); c.fw(actor+260,previous)
        c.fw(model+2416,dx);c.fw(model+2420,current);c.fw(model+2388,current)
        calls=[]; queries=[]
        def native(q):calls.append('native');q.r[2]=0x1234;q.r[3]=0x5678
        def query(q):
            queries.append((q.r[4],q.number(12),q.fr(q.r[6]),q.fr(q.r[6]+8)))
            # Actual triangle math is executed separately below. Here this
            # callback isolates native scene enumeration from the new guard.
            q.fw(q.r[6]+4,1e10 if floor is None else floor)
            q.fw(q.r[6]+20,0 if floor is None else -1)
        c.callbacks[terrain.NATIVE]=native
        c.callbacks[0x23DBC0]=lambda q:q.r.__setitem__(2,int(cinematic))
        c.callbacks[0x230B38]=lambda q:None
        c.callbacks[0x1B14C0]=query
        for p in (0x24E2B0,0x24E3F8,0x24DC58):
            c.callbacks[p]=lambda q,p=p:calls.append((p,q.r[4]))
        c.r[4]=model
        return c,actor,model,calls,queries

    def test_deep_new_floor_crossing_corrects_only_vertical_model_translation(self):
        c,actor,model,calls,queries=self.machine()
        original=c.r.copy();fpu=[0x41000000+i for i in range(4)];c.f[20:24]=fpu
        actor_before=c.read(actor,0x1600);c.run(terrain.CODE)
        self.assertEqual(c.fr(model+2388),-15)
        self.assertEqual(c.read(actor,0x1600),actor_before)
        self.assertEqual(c.u(terrain.CONTROL+20),1)
        self.assertEqual(queries,[(0,-15.25,0,0)])
        self.assertEqual(calls,['native',(0x24E2B0,model),(0x24E3F8,model),(0x24DC58,model)])
        self.assertEqual(c.r[2:4],[0x1234,0x5678]);self.assertEqual(c.r[16:],original[16:])
        self.assertEqual(c.f[20:24],fpu)

    def test_legal_aerial_lower_geometry_and_holes_are_untouched(self):
        for args in (dict(current=-100),dict(current=-16),dict(previous=100,current=130,floor=200),
                     dict(floor=None),dict(current=600),dict(dx=30),dict(previous=50,current=55)):
            c,actor,model,_,_=self.machine(**args);before=c.read(actor,0x1600),c.read(model,0x1670)
            c.run(terrain.CODE);self.assertEqual(c.u(terrain.CONTROL+20),0,args)
            self.assertEqual((c.read(actor,0x1600),c.read(model,0x1670)),before,args)

    def test_cinematics_transforms_and_result_scene_do_not_recover(self):
        for action in (1,2,3,183,187,236,243,253,303,315):
            c,_,model,_,queries=self.machine(action=action);c.run(terrain.CODE)
            self.assertEqual((c.fr(model+2388),queries),(15,[]))
        for address,value in ((0x333700,1),(terrain.core.PAIR+4,1),(terrain.core.MODE,0),
                              (terrain.CONTROL,0),(terrain.core.ACTORS,0)):
            c,_,model,_,queries=self.machine();c.w(address,value);c.run(terrain.CODE)
            self.assertEqual((c.fr(model+2388),queries),(15,[]))
        c,_,model,_,queries=self.machine(cinematic=True);c.run(terrain.CODE)
        self.assertEqual((c.fr(model+2388),queries),(15,[]))

    def triangle(self, threshold, x=0, z=0, floor=-15):
        c=ScalarMips({'segments':[]});c.write(0x1B12E0,self.native(0x1B12E0,0x120))
        output,triangle=0x1000000,0x1000100
        # Counterclockwise upward-facing native triangle; normal (0,-1,0).
        verts=[-100,floor,-100,1,100,floor,-100,1,0,floor,100,1,0,-1,0,-floor]
        c.write(triangle,struct.pack('<16f',*verts));c.fw(output,x);c.fw(output+4,1e10);c.fw(output+8,z)
        c.fw(c.r[28]-29360,0.01);c.r[4:7]=[output,triangle,0x11223344];c.set_number(12,threshold)
        c.callbacks[0x121FA8]=lambda q:q.write(q.r[4],q.read(q.r[5],16))
        c.run(0x1B12E0);return c,output

    def test_actual_native_triangle_rejects_above_current_query_but_sweep_finds_it(self):
        for threshold,expected in ((15,0),(-15.25,1)):
            c,p=self.triangle(threshold);self.assertEqual(c.r[2],expected)
            if expected:self.assertEqual(c.fr(p+4),-15);self.assertEqual(c.u(p+32),0x11223344)
        c,p=self.triangle(-15.25,x=1000);self.assertEqual(c.r[2],0)
        # A legal underground level below the starting root remains selected;
        # the ceiling above that root cannot become a recovery floor.
        c,p=self.triangle(99.75,floor=-15);self.assertEqual(c.r[2],0)
        c,p=self.triangle(99.75,floor=200);self.assertEqual(c.r[2],1);self.assertEqual(c.fr(p+4),200)

    def test_production_build_is_guarded_and_does_not_edit_native_query(self):
        ram=read_ram(ROOT/'runtime128/sstates/SLUS-21678 (428113C2).215.p2s')
        manifest=terrain.build_memory(ram);self.assertEqual(len(manifest['blocks']),4)
        self.assertEqual([b['address'] for b in manifest['blocks'] if b['address']<terrain.CODE],[terrain.ENTRY])
        for b in manifest['blocks']:
            p=b['address'];self.assertEqual(ram[p:p+len(bytes.fromhex(b['data_hex']))].hex(),b['expected_hex'])


if __name__=='__main__':unittest.main()
