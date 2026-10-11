# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
from test_ai_shadow import Mips

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
