"""The tag finisher borrows each actual fighter's native clash pose only."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import unittest
from unittest.mock import patch
import tag_rush_native_pose as pose
import tag_rush_scene as scene
import tag_rush_assets as assets
from test_tag_rush_scene import fixture as scene_fixture,start
from test_tag_rush_camera import run


def fixture():
    c=scene_fixture()
    for model in c.models:c.write(c.u(model+2348)+318,b'\x02')
    return c


def enter(c,role=0):
    c.r[4:7]=[role,scene.ROWS+role*scene.STRIDE,assets.BASE]
    run(c,pose.ENTER);return c.r[2]


class NativePoseTests(unittest.TestCase):
    def test_piccolo_holds_actual_two_finger_firing_endpoint_through_the_beam(self):
        for hz in (25,30):
            for character,fire in ((22,332),(23,264)):
                with patch.object(pose,'ACTOR_HZ',hz):
                    c=fixture();model=c.models[0];start(c);row=scene.ROWS
                    c.w(model+12,character);c.w(row+scene.R['character'],character)
                    for clip in range(fire-3,fire+1):
                        pointer=0x3B00000+clip*4;c.w(model+192+clip*4,pointer);c.w(pointer,256)
                    def selected(m):m.r[2]=fire;m.r[3]=0
                    c.callbacks[pose.profiles.QUERY]=selected
                    original=c.callbacks[scene.A(0x1C3E60)]
                    def lengths(m):
                        original(m);m.fw(model+2884,{fire-3:14.,fire-2:30.,fire-1:19.,fire:30.}.get(m.r[5],30.))
                    c.callbacks[scene.A(0x1C3E60)]=lengths
                    c.w(assets.BASE+28,pose.OWN_CLASH_POSE|pose.CHARGE_BEAM|2)
                    self.assertEqual(enter(c),1)
                    ignition=(90*hz+59)//60
                    for tick in range(1,ignition+40):
                        c.r[4:6]=[0,row];run(c,pose.TICK);self.assertEqual(c.r[2],1)
                        if tick>=ignition:
                            self.assertEqual(c.u(row+pose.CLIP),fire-1)
                            self.assertEqual(c.u(c.actors[0]+2420),fire-1)
                            self.assertEqual(c.fr(model+3192),18.)
                            self.assertEqual(c.fr(model+3200),0.)
                            self.assertEqual(c.u(row+pose.FIRE_CLIP),fire)
                    self.assertFalse(any(clip==fire for _,clip,_ in c.idle_starts))
                    self.assertEqual(c.u(c.actors[0]+2376),11)
                    self.assertEqual(c.damage,[])
                    c.r[4]=1;run(c,scene.FINISH)
                    self.assertEqual(c.u(row+pose.ACTIVE),0)
                    self.assertEqual(c.u(c.actors[0]+2420),0)
                    self.assertNotEqual(c.fr(model+3200),0.)

    def test_charge_uses_the_native_startup_charge_windup_and_fire_sequence(self):
        from extra_throws import NATIVE
        import struct
        self.assertEqual(struct.unpack('<4I',NATIVE(0x2F0B10,16)),
                         (0x1FA5E0,0x1FA600,0x1FA648,0x1FA6C0))
        c=fixture();start(c);model=c.models[0];row=scene.ROWS
        for clip in (261,262,263):c.w(model+192+clip*4,0x3B00000+clip*4);c.w(0x3B00000+clip*4,256)
        original=c.callbacks[scene.A(0x1C3E60)]
        def actual_lengths(m):
            requested=m.r[5];original(m)
            m.fw(model+2884,{261:12.,262:30.,263:17.,264:30.}[requested])
        c.callbacks[scene.A(0x1C3E60)]=actual_lengths
        c.w(assets.BASE+28,assets.CUSTOM_FINISHER|pose.OWN_CLASH_POSE|pose.CHARGE_BEAM|2)
        self.assertEqual(enter(c),1);self.assertEqual(c.u(row+pose.CLIP),261)
        seen=[]
        for tick in range(91):
            # STEP increments the public phase tick before evaluating poses.
            c.w(scene.STATE+scene.S['ticks'],tick+1)
            c.r[4:6]=[0,row];run(c,pose.TICK);self.assertEqual(c.r[2],1)
            self.assertEqual(c.u(row+pose.CLOCK),c.u(scene.STATE+scene.S['ticks']))
            seen.append(c.u(row+pose.CLIP))
        self.assertEqual(list(dict.fromkeys(seen)),[261,262,263,264])
        self.assertTrue(all(clip==262 for clip in seen[6:29]))
        self.assertTrue(all(clip==263 for clip in seen[29:44]))
        self.assertTrue(all(clip==264 for clip in seen[44:]))
        self.assertEqual(seen[43:45],[263,264]) # The first FX fire tick is45.
        self.assertEqual(c.u(c.actors[0]+2376),11)
        self.assertEqual(c.damage,[])

    def test_long_native_windup_is_fitted_before_the_same_fire_boundary(self):
        c=fixture();start(c);model=c.models[0];row=scene.ROWS
        for clip in (261,262,263):c.w(model+192+clip*4,0x3B00000+clip*4);c.w(0x3B00000+clip*4,256)
        original=c.callbacks[scene.A(0x1C3E60)]
        def long_windup(m):
            requested=m.r[5];original(m)
            m.fw(model+2884,160. if requested==263 else 150. if requested==261 else 30.)
        c.callbacks[scene.A(0x1C3E60)]=long_windup
        c.w(assets.BASE+28,pose.OWN_CLASH_POSE|pose.CHARGE_BEAM|2)
        self.assertEqual(enter(c),1)
        seen=[]
        for tick in range(1,46):
            seen.append(c.u(row+pose.CLIP))
            c.r[4:6]=[0,row];run(c,pose.TICK);self.assertEqual(c.r[2],1)
            if tick==30:
                self.assertEqual(c.u(row+pose.CLIP),263)
                self.assertAlmostEqual(c.fr(model+3200),159./15.,places=5)
        self.assertEqual(c.u(row+pose.CLIP),264)
        self.assertEqual(c.u(row+pose.CLOCK),45)
        self.assertIn(262,seen)  # Even a150-frame anticipation reaches its own charge loop.

    def test_unavailable_or_paired_charge_preserves_safe_clash_fallback(self):
        for bad in ('missing','paired','primary rush'):
            c=fixture();start(c);model=c.models[0]
            for clip in (261,262,263):c.w(model+192+clip*4,0x3B00000+clip*4);c.w(0x3B00000+clip*4,256)
            if bad=='missing':c.w(model+192+262*4,0)
            elif bad=='paired':
                c.callbacks[scene.A(0x1C4650)]=lambda m:m.r.__setitem__(2,0xA0000040 if m.r[4]==263 else 0x80000040)
            else:c.write(c.u(model+2348)+315,b'\x01')
            c.w(assets.BASE+28,pose.OWN_CLASH_POSE|pose.CHARGE_BEAM|2)
            self.assertEqual(enter(c),1)
            self.assertEqual(c.u(scene.ROWS+pose.CLIP),364 if bad=='primary rush' else 264)
            self.assertEqual(c.u(scene.ROWS+pose.CHARGING),0)

    def test_actual_native_slot2_type_selects_own_clip_without_mutation(self):
        c=fixture();model=c.models[0];parameters=c.u(model+2348)
        before=c.read(model,0x1700)
        for kind,expected in ((0,264),(1,364),(2,264),(255,264)):
            c.write(parameters+315,bytes([kind]));c.r[4]=model;run(c,pose.SELECT)
            self.assertEqual(c.r[2],expected)
        self.assertEqual(c.read(model,0x1700),before)
        for bad in ('parameters','clip','paired flags'):
            c=fixture();model=c.models[0]
            if bad=='paired flags':c.callbacks[scene.A(0x1C4650)]=lambda m:m.r.__setitem__(2,0xA0000040)
            else:
                c.w(model+2348 if bad=='parameters' else model+192+264*4,0)
                if bad=='clip':c.w(model+192+364*4,0)
            c.r[4]=model;run(c,pose.SELECT);self.assertEqual(c.r[2],0xFFFFFFFF)

    def test_nonbeam_primary_uses_generic_and_later_real_beam_uses_its_own_charge(self):
        for slot in (0,3,4):
            c=fixture();start(c);model=c.models[0];parameters=c.u(model+2348)
            c.write(parameters+318,bytes(3))
            if slot:
                c.write(parameters+316+slot,b'\x02')
                for clip in range(193+34*slot,197+34*slot):
                    c.w(model+192+clip*4,0x3B00000+clip*4);c.w(0x3B00000+clip*4,256)
            c.w(assets.BASE+28,pose.OWN_CLASH_POSE|pose.CHARGE_BEAM|2)
            self.assertEqual(enter(c),1)
            self.assertEqual(c.u(scene.ROWS+pose.CLIP),193+34*slot if slot else 364)
            for _ in range(45):
                c.r[4:6]=[0,scene.ROWS];run(c,pose.TICK);self.assertEqual(c.r[2],1)
            self.assertEqual(c.u(scene.ROWS+pose.CLIP),196+34*slot if slot else 364)
            self.assertEqual(c.u(c.actors[0]+2376),11)

    def test_two_actual_own_poses_blend_loop_and_cleanup_without_attack_dispatch(self):
        c=fixture();start(c);original=[c.u(scene.ROWS+i*scene.STRIDE+24) for i in range(3)]
        c.write(c.u(c.models[2]+2348)+315,b'\x01')
        c.w(assets.BASE+28,assets.CUSTOM_FINISHER|pose.OWN_CLASH_POSE|6)
        calls=len(c.calls)
        for role,index,clip in ((0,0,264),(1,2,364)):
            self.assertEqual(enter(c,role),1)
            row=scene.ROWS+role*scene.STRIDE;model=c.models[index]
            self.assertEqual(c.u(c.actors[index]+2420),clip)
            self.assertEqual(c.u(model+192),original[role])
            self.assertEqual(c.u(row+pose.CLIP),clip)
            self.assertAlmostEqual(c.idle_starts[-1][2],.2,places=6)
            for _ in range(20):
                c.r[4:6]=[role,row];run(c,pose.TICK);self.assertEqual(c.r[2],1)
            self.assertEqual(c.fr(model+3204),0.)
            self.assertLess(c.fr(model+3192),c.fr(model+2884))
            self.assertEqual(c.u(c.actors[index]+2376),11)
        allowed={scene.A(x) for x in (0x1C4650,0x1C3E60,0x1C4920,0x24C958,0x24E2B0,0x24E3F8)}
        self.assertTrue(all(addr in allowed for addr,_ in c.calls[calls:]))
        self.assertEqual(c.damage,[])
        c.r[4]=1;run(c,scene.FINISH)
        for role,index in ((0,0),(1,2)):
            self.assertEqual(c.u(c.models[index]+192),original[role])
            self.assertEqual(c.u(scene.ROWS+role*scene.STRIDE+pose.ACTIVE),0)
            self.assertEqual(c.u(c.actors[index]+2420),0)

    def test_new_capture_clears_stale_own_pose_from_a_replaced_waiting_helper(self):
        c=fixture();row=scene.ROWS+scene.STRIDE
        c.w(row+pose.ACTIVE,1);c.w(row+pose.CLIP,99);c.w(row+pose.POINTER,0xDEADBEEF)
        start(c)
        self.assertEqual(c.r[2],1);self.assertEqual(c.u(scene.CONTROL+16),1)
        self.assertEqual([c.u(row+off) for off in (pose.ACTIVE,pose.CLIP,pose.POINTER)],[0,0,0])
        self.assertEqual(c.u(scene.STATE+scene.S['cancelled']),0)
        self.assertFalse(any(clip==99 for _,clip,_ in c.idle_starts))

    def test_only_flagged_beam_role_uses_own_pose_and_lost_clip_cancels(self):
        c=fixture();start(c)
        for flags in (0,assets.CUSTOM_FINISHER|2,pose.OWN_CLASH_POSE):
            c.w(assets.BASE+28,flags);self.assertEqual(enter(c),0)
        c.w(assets.BASE+28,assets.CUSTOM_FINISHER|pose.OWN_CLASH_POSE|2)
        self.assertEqual(enter(c,1),0);self.assertEqual(enter(c,2),0)
        self.assertEqual(enter(c),1);c.w(c.actors[0]+2420,99)
        before=c.read(c.models[0],0x1700);c.r[4:6]=[0,scene.ROWS];run(c,pose.TICK)
        self.assertEqual(c.r[2],2);self.assertEqual(c.read(c.models[0],0x1700),before)


if __name__=='__main__':unittest.main()
