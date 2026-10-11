# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
from test_terrain_crossing_guard import ScalarMips

class Cpu(ScalarMips):
    instruction_budget=400000
    hi=lo=0
    def extra_instruction(self,ins,pc):
        if ins>>26 in (30,31,37):
            op=ins>>26;rs,rt=(ins>>21)&31,(ins>>16)&31;imm=ins&65535;imm=imm if imm<32768 else imm-65536
            address=(self.r[rs]+imm)&0xFFFFFFFF
            if op==31:self.write(address,(self.r[rt]&((1<<128)-1)).to_bytes(16,'little'))
            else:self.r[rt]=int.from_bytes(self.read(address,2 if op==37 else 16),'little')
            return None
        if ins>>26 in (26,27,44,45):
            op=ins>>26;rs,rt=(ins>>21)&31,(ins>>16)&31;imm=ins&65535;imm=imm if imm<32768 else imm-65536
            address=(self.r[rs]+imm)&0xFFFFFFFF
            # Native14B9B0 uses paired unaligned operations for its aligned
            # 28-byte stack record. These cases each transfer a full doubleword.
            assert address&7==(7 if op in (26,44) else 0)
            address&=~7
            if op in (26,27):self.r[rt]=int.from_bytes(self.read(address,8),'little')
            else:self.write(address,(self.r[rt]&0xFFFFFFFFFFFFFFFF).to_bytes(8,'little'))
            return None
        if ins>>26==17 and (ins>>21)&31==16 and ins&63==36:
            self.f[(ins>>6)&31]=int(round(self.number((ins>>11)&31)))&0xFFFFFFFF;return None
        if ins>>26==0 and ins&63==2:
            self.r[(ins>>11)&31]=(self.r[(ins>>16)&31]&0xFFFFFFFF)>>((ins>>6)&31);return None
        if ins>>26==0 and ins&63==24:
            value=self.signed_word(self.r[(ins>>21)&31])*self.signed_word(self.r[(ins>>16)&31])
            self.lo=value&0xFFFFFFFF;self.hi=(value>>32)&0xFFFFFFFF;return None
        if ins>>26==0 and ins&63==27:
            left,right=self.r[(ins>>21)&31]&0xFFFFFFFF,self.r[(ins>>16)&31]&0xFFFFFFFF
            if right:self.lo,self.hi=left//right,left%right
            return None
        if ins>>26==0 and ins&63 in (16,18):
            self.r[(ins>>11)&31]=self.hi if ins&63==16 else self.lo;return None
        if ins>>26==0 and ins&63 in (17,19):
            value=self.r[(ins>>21)&31]&0xFFFFFFFF
            if ins&63==17:self.hi=value
            else:self.lo=value
            return None
        if ins>>26==0 and ins&63==39:
            self.r[(ins>>11)&31]=~(self.r[(ins>>21)&31]|self.r[(ins>>16)&31])&0xFFFFFFFFFFFFFFFF;return None
        if ins>>26==0 and ins&63==10:
            if not self.r[(ins>>16)&31]:self.r[(ins>>11)&31]=self.r[(ins>>21)&31]
            return None
        if ins>>26==41:
            rs,rt=(ins>>21)&31,(ins>>16)&31;imm=ins&65535;imm=imm if imm<32768 else imm-65536
            self.write((self.r[rs]+imm)&0xFFFFFFFF,struct.pack('<H',self.r[rt]&65535));return None
        return super().extra_instruction(ins,pc)
