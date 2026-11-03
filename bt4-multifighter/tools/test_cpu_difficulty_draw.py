"""Execute the real difficulty draw hook and inspect its submitted GS packet."""
import struct
import unittest
import cpu_difficulty_select as d
import native_mode_menu as menu
from guest_policy_fixture import Cpu
from test_concurrent_cinematic_progress import run


class DifficultyDrawTests(unittest.TestCase):
    def draw(self,level=2,language=0,scene_id=40,room=0x80000,active=2):
        c=Cpu({'segments':[]});c.write(d.DRAW,d.draw_code())
        c.write(d.CONTROL,struct.pack('<3I',d.MAGIC,active,level))
        scene,start=0x1800000,0x1900000
        c.w(d.mode_menu.SCENE_MANAGER,scene);c.w(scene+0x18,scene_id)
        c.w(menu.CONTROL+0xd8,language)
        c.w(c.r[28]+d.GPO(-23004),0);c.w(c.r[28]+d.GPO(-23024),start)
        c.w(c.r[28]+d.GPO(-23016),start+room);c.w(c.r[28]+d.GPO(-23008),room)
        c.w(c.r[28]+d.GPO(-23000),start+0x100)
        packets=d.packets();offset=d.DATA
        for i,packet in enumerate(packets):
            c.write(offset,packet);c.write(d.TABLE+8*i,struct.pack('<2I',offset,len(packet)));offset+=len(packet)
        sent=[]
        c.callbacks[d.A(0x100878)]=lambda m:m.r.__setitem__(2,start+0x100)
        c.callbacks[d.A(0x100890)]=lambda m:sent.append(m.r[4])
        before=c.r.copy();run(c,d.DRAW)
        self.assertEqual(c.r[:31],before[:31])
        return c,sent,start+0x100

    def test_all_levels_and_languages_submit_the_visible_selection(self):
        for language in (0,1):
            for level in range(5):
                c,sent,start=self.draw(level,language)
                packet=d.packets()[level+5*language]
                self.assertEqual(sent,[start+len(packet)],(level,language))
                self.assertEqual(c.read(start,len(packet)),packet)

    def test_inactive_wrong_scene_invalid_level_and_full_arena_submit_nothing(self):
        for args in ({'active':0},{'scene_id':35},{'level':5},{'room':0x100}):
            self.assertEqual(self.draw(**args)[1],[],args)


if __name__=='__main__':unittest.main()
