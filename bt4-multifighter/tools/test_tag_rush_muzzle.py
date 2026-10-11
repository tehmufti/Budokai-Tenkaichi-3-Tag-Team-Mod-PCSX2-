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
