# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import test_guest_killfeed as feed_test

class Cpu(feed_test.CPU):
    hi=lo=0
    def extra_instruction(self,i,pc):
        rs,rt,rd=(i>>21)&31,(i>>16)&31,(i>>11)&31;fn=i&63
        if i>>26==0:
            if fn==16:self.r[rd]=self.hi;return
            if fn==18:self.r[rd]=self.lo;return
            if fn==17:self.hi=self.r[rs];return
            if fn==19:self.lo=self.r[rs];return
            if fn==25:
                v=(self.r[rs]&0xffffffff)*(self.r[rt]&0xffffffff);self.lo=v&0xffffffff;self.hi=v>>32;return
            if fn==27:
                self.lo=(self.r[rs]&0xffffffff)//(self.r[rt]&0xffffffff);self.hi=(self.r[rs]&0xffffffff)%(self.r[rt]&0xffffffff);return
            if fn==2:self.r[rd]=(self.r[rt]&0xffffffff)>>((i>>6)&31);return
        return super().extra_instruction(i,pc)
