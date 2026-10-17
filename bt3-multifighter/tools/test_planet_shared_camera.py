"""One native planet-destruction view, followed by ordinary split restoration."""
import struct
import unittest
import camera_continuity as stage
import cinematic_policy as cinema
import quad_viewports as quad
from native_map import A, GP
from test_terrain_crossing_guard import ScalarMips

MANAGER, VIEWS, BATTLE = 0x1870400, 0x1840000, 0x1860000
CINE, STAGE, DIRECTOR, ANIMATION = 0x1900000, 0x4000000, 0x4100000, 0x4200000


class PrivateViews(Exception):pass


def machine():
    c=ScalarMips({'segments':[]});c.r[28]=GP
    c.w(cinema.core.ACTORS,MANAGER);c.w(MANAGER,2)
    c.write(cinema.core.MODE,struct.pack('<4I',1,6,MANAGER,6))
    c.write(stage.CONTROL,struct.pack('<4I',1,MANAGER,6,1))
    c.write(stage.camera.CONTROL,struct.pack('<2I',1,MANAGER))
    c.write(cinema.CONTROL,struct.pack('<6I',cinema.MAGIC,MANAGER,6,BATTLE,0,0))
    c.w(cinema.team_intro.BATTLE,BATTLE);c.w(BATTLE,3)
    c.w(GP-22172,VIEWS);c.w(GP-22180,CINE);c.w(GP-22176,VIEWS+0x720)
    c.w(stage.STAGE,STAGE);c.w(stage.DIRECTOR,DIRECTOR)
    c.w(stage.STAGE_ANIMATION,ANIMATION);c.w(stage.STAGE_ENDED,0);c.w(stage.SCENE_FLAGS,0x2000)
    for off,value in ((24,ANIMATION),(28,0xffffffff),(32,0xffffffff)):c.w(STAGE+off,value)
    for off,value in ((0,ANIMATION),(4,0xffffffff),(8,0xffffffff),(12,1),(20,1),(24,0xffffffff)):
        c.w(DIRECTOR+off,value)
    c.w(CINE+704,ANIMATION);c.w(CINE+776,1)
    c.write(quad.CONTROL,struct.pack('<4I',quad.MAGIC,MANAGER,6,1))
    c.w(quad.CONTROL+quad.VIEW_COUNT,4)
    c.calls=[];c.advances=0
    def original(m):
        m.advances+=1;m.r[2]=1;m.r[3]=0xabcde0001234
    def select(m):
        body=VIEWS+(0x720 if m.r[4]==0 else 0x9b0)
        m.w(GP-22176,body);m.calls.append(('select',m.r[4]))
    c.callbacks[cinema.camera.CODE]=original
    for address,value in ((0x12AB10,1),(0x12A9E8,0),(0x23EE08,0),(0x23DBC0,1)):
        c.callbacks[A(address)]=lambda m,value=value:m.r.__setitem__(2,value)
    c.callbacks[A(0x23EF98)]=select
    c.callbacks[A(0x23EFD0)]=lambda m:None
    c.callbacks[A(0x23EE78)]=lambda m:m.calls.append(('viewport',m.r[4],m.r[5]))
    c.callbacks[A(0x23E6A0)]=lambda m:m.calls.append(('bind',m.r[4],m.r[5]))
    c.callbacks[cinema.VIEW]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[quad.TAILS]=lambda m:m.calls.append(('native_draw',))
    def private(m):raise PrivateViews()
    c.callbacks[quad.PREPARE]=private
    return c


class SharedPlanetTests(unittest.TestCase):
    def test_two_player_planet_ignores_special_camera_preferences_then_restores_split(self):
        for quad_support in (False,True):
            for ultimate,transform in ((0,0),(1,0),(0,1),(1,1)):
                c=machine();c.write(cinema.CODE,cinema.selector(quad_support=quad_support))
                c.w(cinema.CONTROL+16,ultimate);c.w(cinema.CONTROL+20,transform)
                before=c.read(CINE,832);registers=list(c.r[4:29]);c.run(cinema.CODE)
                self.assertEqual(c.r[2],1);self.assertEqual(c.r[3],0xabcde0001234)
                self.assertEqual(c.calls,[('select',0),('viewport',0,1),('bind',CINE,1)])
                self.assertEqual(c.u(VIEWS+0xc40),CINE);self.assertEqual(c.read(CINE,832),before)
                self.assertEqual(c.r[4:29],registers);self.assertEqual(c.advances,1)
                c.w(stage.STAGE_ENDED,1);c.calls=[]
                # Neither category has an owner in this ordinary-combat fixture.
                c.w(cinema.CONTROL+16,0);c.w(cinema.CONTROL+20,0)
                c.run(cinema.CODE)
                self.assertEqual(c.r[2],0);self.assertEqual(c.advances,2)
                self.assertEqual(c.calls,[('select',0),('viewport',1,0),('select',1),('viewport',1,0),('select',0)])

    def test_a_fused_alias_cannot_duplicate_the_global_planet_camera(self):
        c=machine();c.write(cinema.CODE,cinema.selector(quad_support=True))
        c.w(cinema.core.PAIR+4,0x2000000);c.run(cinema.CODE)
        self.assertEqual(c.r[2],1)
        self.assertIn(('bind',CINE,1),c.calls)

    def test_three_and_four_players_draw_planet_once_then_restore_private_views(self):
        for humans in (3,4):
            c=machine();c.write(quad.DRAW,quad.draw());c.w(quad.CONTROL+quad.VIEW_COUNT,humans)
            before=list(c.r[2:29]);c.run(quad.DRAW)
            self.assertEqual(c.calls,[('native_draw',)]);self.assertEqual(c.r[2:29],before)
            c.w(stage.STAGE_ENDED,1)
            with self.assertRaises(PrivateViews):c.run(quad.DRAW)

    def test_stale_or_fighter_bound_camera_never_merges_the_views(self):
        cases=((stage.CONTROL+4,MANAGER+4),(stage.CONTROL+8,4),(stage.STAGE,0),
               (stage.STAGE_ENDED,1),(stage.SCENE_FLAGS,0),(stage.STAGE_ANIMATION,ANIMATION+4),
               (STAGE+28,0),(DIRECTOR+24,0),(DIRECTOR+20,0),(CINE+768,0x3000000),
               (CINE+772,0x3000000),(CINE+776,0),(CINE+812,1),(CINE+704,ANIMATION+4))
        for address,value in cases:
            c=machine();c.write(cinema.CODE,cinema.selector());c.w(address,value);c.run(cinema.CODE)
            self.assertEqual(c.r[2],0,(hex(address),value));self.assertNotIn(('bind',CINE,1),c.calls)
            c=machine();c.write(quad.DRAW,quad.draw());c.w(address,value)
            with self.assertRaises(PrivateViews,msg=(hex(address),value)):c.run(quad.DRAW)


if __name__=='__main__':unittest.main()
