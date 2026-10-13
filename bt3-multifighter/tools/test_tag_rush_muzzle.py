"""Native mouth-muzzle metadata follows the exact own beam pose, not identity."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
from pathlib import Path
import tag_rush_assets as assets
import tag_rush_scene as scene
import tag_rush_native_pose as pose
from test_tag_rush_effects import machine, run, fx, A, ROOT, elf_reader, elf_path


def own_beam(clip=264,slot=0,flags=0x2000):
    c=machine();model=c.models[0 if slot==0 else 2]
    c.w(scene.STATE,scene.SCENE_MAGIC);c.w(scene.STATE+scene.S['descriptor'],assets.BASE)
    c.w(assets.BASE+28,assets.CUSTOM_FINISHER|assets.OWN_CLASH_POSE|assets.BEAM_LEAD|assets.BEAM_PARTNER)
    capture=scene.ROWS+slot*scene.STRIDE
    c.w(capture+scene.R['model'],model);c.w(capture+pose.ACTIVE,1);c.w(capture+pose.FIRE_CLIP,clip)
    params=c.u(model+2348)
    c.w(params+({264:0,298:4,332:8}.get(clip,0)),flags)
    bone=0x37F0000+slot*128;c.w(model+3436+54*4,bone)
    c.write(bone+64,struct.pack('<4f',10.,-15.,20.,1.))
    return c,model,fx.ROWS+slot*fx.STRIDE


class MuzzleTests(unittest.TestCase):
    def test_piccolo_charge_and_fire_keep_the_native_event_hand_during_blends(self):
        for character,clip in ((22,332),(23,264)):
            for slot in (0,1):
                c,model,row=own_beam(clip,slot,flags=0)
                c.w(model+12,character)
                c.write(model+2416,struct.pack('<4f',0.,0.,0.,1.))
                target=c.models[1]
                c.write(c.u(target+3436+17*4)+64,struct.pack('<4f',0.,0.,100.,1.))
                for bone,z in ((31,-10.),(45,10.)):
                    c.write(c.u(model+3436+bone*4)+64,struct.pack('<4f',0.,-10.,z,1.))
                # The preceding stance deliberately has the wrong arm forward.
                # Native Piccolo's own charge/fire event still binds hand31.
                c.r[4:6]=[slot,90];run(c,fx.CHARGE_SPAWN)
                self.assertEqual(c.r[2],1,(character,slot));body=c.u(row+fx.R['body'])
                self.assertEqual(c.u(row+fx.R['source_bone']),31)
                for context in (row+fx.CONTEXT,body+64):
                    for phase in (0,1):self.assertEqual(c.u(context+16+phase*64),31)
                self.assertEqual(c.read(body+1440,16),c.read(c.u(model+3436+31*4)+64,16))
                c.r[4]=row;run(c,fx.IGNITE)
                self.assertEqual(c.r[2],1);self.assertEqual(c.u(row+fx.R['source_bone']),31)
                self.assertEqual(c.u(body+64+16+64),31)
                moved=struct.pack('<4f',4.,-12.,-15.,1.)
                c.write(c.u(model+3436+31*4)+64,moved);run(c,fx.UPDATE)
                self.assertEqual(c.read(body+1440,16),moved)
                self.assertEqual(len(c.requests),1)

    def test_piccolo_binding_requires_the_exact_own_pose_and_valid_live_geometry(self):
        for invalid in ('wrong character','wrong slot','generic','inactive','wrong capture','missing31','nan31','nanroot'):
            c,model,row=own_beam(332,flags=0);c.w(model+12,22)
            c.write(c.u(c.models[1]+3436+17*4)+64,struct.pack('<4f',0.,0.,100.,1.))
            for bone,z in ((31,-10.),(45,10.)):
                c.write(c.u(model+3436+bone*4)+64,struct.pack('<4f',0.,0.,z,1.))
            if invalid=='wrong character':c.w(model+12,24)
            elif invalid=='wrong slot':c.w(scene.ROWS+pose.FIRE_CLIP,264)
            elif invalid=='generic':c.w(scene.ROWS+pose.FIRE_CLIP,364)
            elif invalid=='inactive':c.w(scene.ROWS+pose.ACTIVE,0)
            elif invalid=='wrong capture':c.w(scene.ROWS+scene.R['model'],c.models[2])
            elif invalid=='missing31':c.w(model+3436+31*4,0)
            elif invalid=='nan31':c.w(c.u(model+3436+31*4)+64,0x7FC00000)
            else:c.w(model+2416,0x7FC00000)
            c.r[4:6]=[0,90];run(c,fx.CHARGE_SPAWN)
            if invalid in ('missing31','nan31','nanroot'):
                self.assertEqual(c.r[2],0,invalid);self.assertEqual(c.requests,[],invalid)
            else:
                self.assertEqual(c.r[2],1,invalid);self.assertEqual(c.u(row+fx.R['source_bone']),45,invalid)

    def test_real_piccolo_charge_and_fire_events_use_hand31_on_available_discs(self):
        from model_assets import read_animation_bank,package_entry,load_character
        from model_animations import AnimationClip,decompress_animation
        from model_viewer import pose_matrices
        bt4='bt4' in str(Path(__file__))
        names=(('SLUS_219.78.DBZBT4B14REV2ENG.iso','SLUS_219.78.DBZBT4B14REV2.iso') if bt4 else
               ('Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso',
                'Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) (Versus Fighting) (ISO) (PS2).iso',
                'Dragon Ball Z - Sparking! Meteor (Japan).iso'))
        found=0
        for name in names:
            iso=ROOT.parent/'games'/name
            if not iso.is_file():continue
            found+=1
            for character,fire in ((22,332),(23,264)):
                if not bt4 and name!=names[0]:
                    import sys
                    from unittest.mock import patch
                    sys.path.insert(0,str(ROOT.parent))
                    from iso_compatibility.disc import Disc
                    with Disc(iso) as disc:
                        # Native FILE_ID maps all of these character files
                        # by +247 for Europe and -82 for Japan.
                        shift={'EU':247,'JP':-82}[disc.region]
                        with patch('model_assets.read_archive_entry',lambda path,file_id:disc.read(file_id+shift)):
                            model=load_character(iso,character);bank=read_animation_bank(iso,character)
                else:model=load_character(iso,character);bank=read_animation_bank(iso,character)
                for animation,events_wanted in ((fire-3,(0x200,)),(fire-1,(0x400,0x4000))):
                    raw=decompress_animation(package_entry(bank,animation+1))
                    records=[struct.unpack_from('<QHHI',raw,148+16*i) for i in range(raw[1])]
                    for flag in events_wanted:
                        matches=[event for event in records if event[0]&flag]
                        self.assertTrue(matches,(name,character,animation,flag))
                        self.assertTrue(all(event[3]==0x10000 for event in matches),matches)
                # Charge hand is by the head; this same marker extends forward
                # in the firing clip, exactly as the native event binding says.
                charge=AnimationClip.from_decoded(fire-2,decompress_animation(package_entry(bank,fire-1)))
                firing=AnimationClip.from_decoded(fire,decompress_animation(package_entry(bank,fire+1)))
                charged=pose_matrices(model.bones,charge.evaluate(10))
                fired=pose_matrices(model.bones,firing.evaluate(10))
                import numpy as np
                self.assertLess(np.linalg.norm(charged[31][:3,3]-charged[47][:3,3]),3.,name)
                self.assertLess(fired[31][2,3],fired[45][2,3]-10.,name)
        if not found:self.skipTest('User-owned reviewed game discs unavailable')

    def test_charge_fire_and_native_contexts_follow_selected_mouth_muzzle(self):
        for clip in (264,298,332):
            for slot in (0,1):
                c,model,row=own_beam(clip,slot)
                c.r[4:6]=[slot,90];run(c,fx.CHARGE_SPAWN)
                self.assertEqual(c.r[2],1,(clip,slot));body=c.u(row+fx.R['body'])
                self.assertEqual(c.u(row+fx.R['source_bone']),54)
                for context in (row+fx.CONTEXT,body+64):
                    for phase in (0,1):self.assertEqual(c.u(context+16+phase*64),54)
                mouth=c.u(model+3436+54*4)
                moved=struct.pack('<4f',15.,-18.,24.,1.);c.write(mouth+64,moved)
                c.r[4]=row;run(c,fx.IGNITE)
                self.assertEqual(c.r[2],1);self.assertEqual(c.u(row+fx.R['source_bone']),54)
                self.assertEqual(c.read(body+1440,16),moved)
                self.assertEqual(len(c.requests),1)
                later=struct.pack('<4f',18.,-20.,25.,1.);c.write(mouth+64,later)
                run(c,fx.UPDATE);self.assertEqual(c.read(body+1440,16),later)

    def test_generic_clash_or_other_slots_flags_keep_forward_hand(self):
        for clip,own_flags,other_slot in ((364,0x2000,None),(264,0,4),(298,0,0),(332,0,4)):
            c,model,row=own_beam(clip,flags=own_flags)
            if other_slot is not None:c.w(c.u(model+2348)+other_slot,0x2000)
            c.w(model+3436+54*4,0)  # Invalid mouth is irrelevant to a hand pose.
            c.r[4:6]=[0,90];run(c,fx.CHARGE_SPAWN)
            self.assertEqual(c.r[2],1,clip);self.assertIn(c.u(row+fx.R['source_bone']),(31,45))
            c.r[4]=row;run(c,fx.IGNITE)
            self.assertEqual(c.r[2],1);self.assertIn(c.u(row+fx.R['source_bone']),(31,45))

    def test_missing_or_nonfinite_mouth_never_allocates_or_rebinds_invalid_geometry(self):
        for invalid in ('missing','unaligned','nan','infinity'):
            c,model,row=own_beam();mouth=c.u(model+3436+54*4)
            if invalid=='missing':c.w(model+3436+54*4,0)
            elif invalid=='unaligned':c.w(model+3436+54*4,mouth+1)
            else:c.w(mouth+64,0x7FC00000 if invalid=='nan' else 0x7F800000)
            c.r[4:6]=[0,90];run(c,fx.CHARGE_SPAWN)
            self.assertEqual(c.r[2],0,invalid);self.assertEqual(c.requests,[])
        c,model,row=own_beam();c.r[4:6]=[0,90];run(c,fx.CHARGE_SPAWN)
        self.assertEqual(c.r[2],1);body=c.u(row+fx.R['body'])
        before=c.read(body+64,592);c.w(c.u(model+3436+54*4)+64,0x7FC00000)
        c.r[4]=row;run(c,fx.FIRE_BIND)
        self.assertEqual(c.r[2],0);self.assertEqual(c.read(body+64,592),before)

    def test_stale_capture_does_not_apply_another_fighters_mouth_flag(self):
        for invalid in ('inactive','wrong model'):
            c,model,row=own_beam()
            c.w(scene.ROWS+(pose.ACTIVE if invalid=='inactive' else scene.R['model']),0)
            c.w(model+3436+54*4,0)
            c.r[4:6]=[0,90];run(c,fx.CHARGE_SPAWN)
            self.assertEqual(c.r[2],1);self.assertIn(c.u(row+fx.R['source_bone']),(31,45))

    def test_actual_arale_and_goku_match_native_parameter_conversion_and_muzzle_rule(self):
        import model_assets
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__))
              else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        iso=ROOT.parent/'games'/name
        if not iso.is_file():self.skipTest('The user-owned game disc is required')
        native=elf_reader(elf_path(ROOT))[2]
        for character,expected in ((156,54),(0,31)):
            if 'bt4' in str(Path(__file__)):
                metadata=model_assets.package_entry(model_assets.read_archive_entry(iso,4150+character),2)[0x29D0:0x2C50]
            else:metadata=model_assets.package_entry(assets._mesh_package(iso,character),24)
            c,model,row=own_beam();params=c.u(model+2348);c.write(params,metadata)
            for address,size in ((0x14B108,0x7D8),(0x14AA18,0x48),(0x14A958,0xC0)):
                c.write(A(address),native(A(address),size))
            c.callbacks[A(0x205330)]=lambda m:m.r.__setitem__(2,params)
            converted=0x37E0000;c.r[4:8]=[0,2,converted,0];run(c,A(0x14B108))
            self.assertEqual(c.u(converted+60),struct.unpack_from('<I',metadata)[0])
            self.assertEqual(bool(c.u(converted+60)&0x2000),character==156)
            manager,table=0x37D0000,0x37D1000
            c.w(c.r[28]-22648,manager);c.w(manager+4,table);c.w(table+80*2+36,converted)
            c.r[4:6]=[0,2];run(c,A(0x14AA18));self.assertEqual(c.r[2],int(character==156))
            c.callbacks[A(0x14ABD8)]=lambda m:m.r.__setitem__(2,2)
            c.callbacks[A(0x14AA60)]=lambda m:m.r.__setitem__(2,0)
            c.callbacks[A(0x14A828)]=lambda m:m.r.__setitem__(2,0)
            c.callbacks[A(0x207A90)]=lambda m:m.r.__setitem__(2,1)
            c.callbacks[A(0x207B60)]=lambda m:m.r.__setitem__(2,31)
            c.r[4:6]=[0,1];run(c,A(0x14A958));self.assertEqual(c.r[2],expected)
            c.r[4:6]=[0,90];run(c,fx.CHARGE_SPAWN)
            self.assertEqual(c.r[2],1)
            self.assertEqual(c.u(row+fx.R['source_bone'])==54,character==156)


if __name__=='__main__':unittest.main()
