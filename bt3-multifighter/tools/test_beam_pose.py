"""Actual special metadata and own-bank cooperative beam presentation."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
import beam_pose
import tag_rush_native_pose as pose
from test_tag_rush_scene import fixture
from test_tag_rush_camera import run


class BeamPoseTests(unittest.TestCase):
    def test_nonzero_empty_or_oversized_bank_entries_are_not_poses(self):
        for size in (0,31,49153,0xFFFFFFFF):
            c=fixture();model=c.models[0];params=c.u(model+2348)
            c.write(params+315,b'\x06\x00\x00\x00\x00\x00')
            c.w(c.u(model+192+364*4),size)
            c.r[4]=model;run(c,pose.SELECT)
            self.assertEqual(c.r[2],264,size)
            c.w(c.u(model+192+264*4),size)
            c.r[4]=model;run(c,pose.SELECT)
            self.assertEqual(c.r[2],0xFFFFFFFF,size)

    def test_selector_skips_nonbeams_and_invalid_own_banks_without_actor_writes(self):
        c=fixture();model=c.models[0];params=c.u(model+2348)
        c.write(params+315,b'\x00\x00\x00\x00\x02\x02')
        c.w(model+192+298*4,3) # invalid aligned/bounded pointer, try slot4
        before=c.read(model,0x1700)
        c.r[4]=model;run(c,pose.SELECT);self.assertEqual(c.r[2],332)
        self.assertEqual(c.read(model,0x1700),before)
        c.w(model+192+332*4,0x8000000)
        c.r[4]=model;run(c,pose.SELECT);self.assertEqual(c.r[2],364)
        c.w(model+192+364*4,0)
        c.r[4]=model;run(c,pose.SELECT);self.assertEqual(c.r[2],0xFFFFFFFF)

    def test_native_subtype_two_routes_to_the_charged_beam_action_family(self):
        from extra_throws import NATIVE
        from native_map import A
        c=fixture()
        c.write(A(0x203C40),NATIVE(A(0x203C40),0xE0))
        c.write(A(0x2F1360),NATIVE(A(0x2F1360),44))
        c.callbacks[A(0x211050)]=lambda m:m.r.__setitem__(2,2)
        for slot in (2,3,4):
            c.r[4:6]=[c.actors[0],slot];run(c,A(0x203C40))
            self.assertEqual(c.r[2],271+slot-2)

    def test_actual_bt4_black_uses_its_native_generic_clash_not_the_lifted_leg_move(self):
        from prototype import ROOT
        from native_map import SERIAL
        import model_assets,model_animations
        if SERIAL!='SLUS-21978':self.skipTest('BT4 exclusive source fixture')
        iso=ROOT.parent/'games/SLUS_219.78.DBZBT4B14REV2ENG.iso'
        if not iso.is_file():self.skipTest('The user-owned game disc is required')
        def parameters(character):
            return model_assets.package_entry(model_assets.read_archive_entry(iso,4150+character),2)[0x29D0:0x2C50]
        def clip(character,index):
            bank=model_assets.read_animation_bank(iso,character)
            return model_animations.decompress_animation(model_assets.package_entry(bank,index+1))
        for character,expected in ((0,264),(23,264),(34,264),(99,364),(112,298),(156,264),(157,364)):
            metadata=parameters(character);c=fixture();model=c.models[0]
            c.write(c.u(model+2348),metadata)
            for index,slot in beam_pose.candidates(metadata):
                decoded=clip(character,index)
                if not decoded:
                    self.assertEqual((character,index),(156,364))
                    c.w(model+192+4*index,0);continue
                self.assertGreater(model_animations.AnimationClip.from_decoded(index,decoded).frame_count,0)
                c.w(model+192+4*index,0x3800000+index*4);c.w(0x3800000+index*4,len(decoded))
            c.r[4]=model;run(c,pose.SELECT)
            self.assertEqual(c.r[2],expected,character)
        self.assertEqual(clip(99,364),clip(0,364))
        self.assertNotEqual(clip(99,264),clip(99,364))
        # Black's special is not corrupted: its beam-like alternate was reused
        # as Rosé's charged beam. Untyped moves still use the safe native fallback.
        self.assertEqual(clip(99,332),clip(34,264))


if __name__=='__main__':unittest.main()
