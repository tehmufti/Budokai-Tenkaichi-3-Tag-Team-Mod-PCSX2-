"""Run the guest floor correction with grounded and airborne clash owners."""
import struct
import unittest
from pathlib import Path as _TestPath
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise unittest.SkipTest('An extracted game executable is required for native assist tests')
import beam_struggle as b
from test_tag_rush_scene import SceneCpu


class GroundedAssistTests(unittest.TestCase):
    def run_floor(self, ally_y, ally_floor, helper_y, helper_floor):
        c=SceneCpu({'segments':[]});c.write(b.FLOOR,b.floor_code())
        stage,bounds,ally,pos=0x1800000,0x1801000,0x1802000,0x1803000
        c.w(b.arena_bounds.STAGE,stage);c.w(stage+64,bounds)
        c.write(bounds,struct.pack('<3f',1000,-200,200))
        c.write(ally,struct.pack('<4f',0,ally_y,0,1))
        c.write(pos,struct.pack('<4f',12,helper_y,3,1))
        before=[]
        for i,off in enumerate(b.terrain.QUERY_GLOBALS):c.w(c.r[28]+off,100+i);before.append(100+i)
        def query(m):
            value=ally_floor if m.r[4]==ally else helper_floor
            m.r[2]=int(value is not None)
            m.set_number(0,value or 0)
            for off in b.terrain.QUERY_GLOBALS:m.w(m.r[28]+off,0xbad)
        c.callbacks[b.QUERY]=query
        c.r[4],c.r[5],c.r[31]=pos,ally,0xFEED0000
        c.run(b.FLOOR,[0xFEED0000])
        self.assertEqual([c.u(c.r[28]+off)for off in b.terrain.QUERY_GLOBALS],before)
        return c.r[2],struct.unpack('<f',bytes(c.read(pos+12,4)))[0]

    def test_grounded_owner_snaps_helper_to_lower_floor(self):
        self.assertEqual(self.run_floor(0,0,0,8),(1,8))

    def test_airborne_owner_keeps_helper_airborne(self):
        self.assertEqual(self.run_floor(-30,0,-30,8)[0],0)

    def test_buried_helper_is_still_lifted(self):
        self.assertEqual(self.run_floor(0,0,0,-6),(1,-6))

    def test_no_floor_or_deep_drop_never_snaps_down(self):
        for a,h in ((None,8),(0,None),(0,60)):
            with self.subTest(ally=a,helper=h):self.assertEqual(self.run_floor(0,a,0,h)[0],0)


if __name__=='__main__':unittest.main()
