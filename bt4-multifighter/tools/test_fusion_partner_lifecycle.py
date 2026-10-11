# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

from test_extra_special_pools import Cpu
import fusion_partner_lifecycle as fix
import team_participation as participation

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
    c.write(0x334C00,(fix.ROOT/'analysis/DBZP.BIN').read_bytes())
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
