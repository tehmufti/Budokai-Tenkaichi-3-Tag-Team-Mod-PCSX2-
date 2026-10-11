# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import story_missions as d
import story_runtime as r
import fresh_team_combat as core
import native_preparation as prep
from native_map import A
from test_fusion_partner_lifecycle import FusionCpu

class StoryCpu(FusionCpu):
    def extra_instruction(self,ins,pc):
        if ins >> 26 == 0 and ins & 63 == 25:
            left=self.r[(ins>>21)&31]&0xffffffff;right=self.r[(ins>>16)&31]&0xffffffff
            product=left*right;self.lo=product&0xffffffff;self.hi=product>>32
            return
        return super().extra_instruction(ins,pc)

def machine(document):
    c=StoryCpu();c.r[28]=0x304270;c.manager=0x1800000
    c.actors=[0x1900000+0x2000*i for i in range(4)];c.models=[0x900000+0x2000*i for i in range(4)]
    c.w(core.ACTORS,c.manager);c.w(c.manager,2);c.w(c.manager+4,c.actors[0])
    for off,v in ((0,1),(4,4),(8,c.manager),(12,4)):c.w(core.MODE+off,v)
    for off,v in ((0,r.MAGIC),(4,c.manager),(8,4),(52,0xffffffff),(56,1)):c.w(r.CONTROL+off,v)
    c.w(A(0x2FEB38),0x1700000);c.w(0x1700000,3);c.w(r.part.CONSUMED,8)
    import spawn_placement
    c.w(spawn_placement.CONTROL,5)
    for i,(actor,model) in enumerate(zip(c.actors,c.models)):
        c.w(core.POINTERS+4*i,actor);c.w(r.ACTORS+4*i,actor);c.w(core.MODELS+4*i,model)
        for off,v in ((0,i),(8,i&1),(12,i),(0x948,11),(0x94C,0xffffffff),(0x964,47),(0x998,1),(0x9E4,30000),(0x9E8,30000),
                      (0x9FC,5),(0x1278,int(i>0))):c.w(actor+off,v)
        c.w(model+4,1);c.w(model+8,1);c.w(model+16,i);c.w(model+12,i)
        c.w(model+0x91C,0x1600000+i*0x1000);c.write(0x1600000+i*0x1000+152,bytes((1,2,3,255)))
    c.callbacks[r.ORIGINAL]=lambda m:None
    c.callbacks[r.ARRIVAL]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[A(0x1E0290)]=lambda m:m.w(m.r[4]+0x94C,m.r[5])
    c.callbacks[A(0x2033C8)]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[A(0x203610)]=lambda m:m.w(m.r[4]+0x94C,236+m.r[5])
    for f in document['fighters']:c.w(r.ACTORS+0x200+8*r.physical(f),c.u(c.models[r.physical(f)]+12))
    c.write(r.FRAME,r.frame(document,{i:int(i>0) for i in range(4)}));c.write(r.CPU_INIT,r.cpu_init([]))
    return c
