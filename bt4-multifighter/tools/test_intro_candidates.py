"""Opponent-specific entrance choices, independent of a saved match."""
from pathlib import Path as _Path
import unittest as _Unit
from native_map import elf_path as _elf
if not _elf(_Path(__file__).resolve().parents[1]).is_file():
    raise _Unit.SkipTest('An extracted game executable is required for native intro tests')

import struct
import unittest
import extra_intros as f

class DialogueCandidates(unittest.TestCase):
    def setUp(self):
        self.ram=bytearray(0x8000000)
        self.put=lambda p,v:struct.pack_into('<I',self.ram,p,v)
        self.table=0x1600000
        self.ram[self.table:self.table+1024]=bytes([255])*1024
        self.put(f.core.ACTORS,0x1700000)
        for i,chara in enumerate((1,2,3,4,5,4)):
            actor=0x1400000+i*0x2000; model=0x1500000+i*0x2000
            self.put(f.core.POINTERS+4*i,actor);self.put(actor+12,i)
            self.put(f.core.MODELS+4*i,model);self.put(model+12,chara)
            self.put(model+0x93C,self.table)
        for chara,line in ((1,5),(2,7),(4,9),(5,11)):
            self.ram[self.table+4*chara]=line
    def test_only_present_distinct_enemy_characters(self):
        self.assertEqual(f.custom_intro_lines(self.ram,2,6,63),(13,15))
        self.assertEqual(f.custom_intro_lines(self.ram,2,6,7),(13,))
        self.assertEqual(f.custom_intro_lines(self.ram,2,6,5),())
    def test_free_for_all_allows_other_former_team_members(self):
        for off,value in ((0,f.policy.MAGIC),(4,0x1700000),(12,f.policy.FFA)):
            self.put(f.policy.CONTROL+off,value)
        self.assertEqual(f.custom_intro_lines(self.ram,2,6,63),(11,13,15,17))
    def test_missing_table_or_no_interaction_falls_back(self):
        self.put(0x1500000+2*0x2000+0x93C,0)
        self.assertEqual(f.custom_intro_lines(self.ram,2,6,63),())
        self.put(0x1500000+2*0x2000+0x93C,self.table)
        self.ram[self.table:self.table+1024]=bytes([255])*1024
        self.assertEqual(f.custom_intro_lines(self.ram,2,6,63),())
if __name__=='__main__':unittest.main()

