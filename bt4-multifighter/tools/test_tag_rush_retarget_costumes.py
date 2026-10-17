"""Native single-bind retargeting without touching recipient meshes."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest
from pathlib import Path

from native_map import A,SERIAL,elf_path
from prototype import ROOT,elf_reader
import tag_rush_retarget as helper
import tag_rush_assets as assets
import model_animations as animations
from test_tag_rush_scene import SceneCpu as Cpu
from test_tag_rush_scene import fixture
from test_tag_rush_camera import run


class RetargetGuards(unittest.TestCase):
    def test_malformed_duplicates_and_pointers_refuse_without_model_writes(self):
        for bad in ('valid','local','world','parent_bind','visible','nested','parent','root','unaligned','nan','inf'):
            c=fixture();model=c.models[0];base=c.u(model+68)
            raw=c.read(base,64*5);nodes=[bytearray(raw[i:i+64]) for i in range(0,len(raw),64)]
            # Duplicate hand31 next to its original, under the same root.
            nodes.insert(3,bytearray(nodes[2]))
            if bad in ('local','world','parent_bind'):struct.pack_into('<f',nodes[3],{'local':48,'world':16,'parent_bind':32}[bad],1.)
            elif bad=='visible':struct.pack_into('<H',nodes[3],8,1)
            elif bad=='nested':struct.pack_into('<H',nodes[2],4,0)
            elif bad=='parent':struct.pack_into('<H',nodes[2],4,2)
            elif bad=='root':struct.pack_into('<H',nodes[3],10,2)
            elif bad in ('nan','inf'):
                for n in (2,3):struct.pack_into('<f',nodes[n],48,float(bad))
            c.write(base,b''.join(nodes))
            if bad=='unaligned':c.w(model+68,base+1)
            snapshot=c.read(model,0x1700),c.read(base,64*6)
            c.r[4]=model;run(c,helper.CHECK)
            self.assertEqual(c.r[2],int(bad=='valid'),bad)
            self.assertEqual((c.read(model,0x1700),c.read(base,64*6)),snapshot,bad)

    def test_all_three_scene_roles_check_duplicates_before_any_cleanup(self):
        from test_tag_rush_scene import start
        import tag_team_rush as tag
        for role in (0,2,1):
            for valid in (True,False):
                c=fixture();base=c.u(c.models[role]+68)
                raw=c.read(base,64*5);nodes=[bytearray(raw[i:i+64])for i in range(0,len(raw),64)]
                nodes.insert(3,bytearray(nodes[2]))
                if not valid:struct.pack_into('<f',nodes[3],48,1.)
                c.write(base,b''.join(nodes));original=c.read(base,64*6)
                before=[c.read(a,0x1600)for a in c.actors]
                start(c);self.assertEqual(c.r[2],int(valid),(role,valid))
                self.assertEqual(c.read(base,64*6),original)
                if not valid:
                    self.assertEqual([c.read(a,0x1600)for a in c.actors],before)
                    self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)

    def test_native_approach_uses_proxy_only_for_owned_clip_and_refuses_changed_bind(self):
        import tag_rush_launch as launch
        import tag_rush_approach as rush
        from test_tag_rush_approach import machine,begin
        c=machine();base=c.u(c.models[0]+68);raw=c.read(base,64*5)
        nodes=[bytearray(raw[i:i+64])for i in range(0,len(raw),64)];nodes.insert(3,bytearray(nodes[2]))
        c.write(base,b''.join(nodes));self.assertEqual(begin(c),1)
        for animation,model,proxy in ((329,c.models[0],True),(11,c.models[0],False),(329,c.models[2],False)):
            c.r[20]=animation;c.r[4:9]=[0x3300000,model,model,0,1];run(c,launch.RETARGET)
            self.assertEqual(c.retargets[-1][1]!=model,proxy)
        count=len(c.retargets);c.fw(base+3*64+48,1.)
        c.r[20]=329;c.r[4:9]=[0x3300000,c.models[0],c.models[0],0,1];run(c,launch.RETARGET)
        self.assertEqual(len(c.retargets),count)
        self.assertEqual(c.u(rush.STATE+rush.S['contact']),2)
        self.assertEqual(c.u(rush.STATE+rush.S['reason']),3)

    def test_new_runtime_interval_is_inside_gap_and_never_mutable(self):
        import tag_rush_effects as effects
        import tag_rush_hud as hud
        self.assertLessEqual(effects.END,helper.BASE)
        self.assertLessEqual(helper.END,hud.BASE)
        chunks=helper.pieces()
        for (p,b),(q,_) in zip(chunks,chunks[1:]):self.assertLessEqual(p+len(b),q)
        self.assertLessEqual(chunks[-1][0]+len(chunks[-1][1]),helper.END)


class NativeSingleBindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name='SLUS_219.78.DBZBT4B14REV2ENG.iso' if SERIAL=='SLUS-21978' else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
        cls.iso=ROOT.parent/'games'/name
        if not cls.iso.is_file() or not elf_path(ROOT).is_file():raise unittest.SkipTest('Native disc/executable required')
        cls.native=staticmethod(elf_reader(elf_path(ROOT))[2]);cls.bindings=assets.read_donor_bindings(cls.iso);cls.clips=assets.read_clips(cls.iso)

    def machine(self,skeleton,source,wrapped=True):
        c=Cpu({'segments':[dict(address=p,data_hex=b.hex()) for p,b in helper.pieces()]})
        for address,size in ((0x24BBE8,0x370),(0x250570,0x60)):c.write(A(address),self.native(A(address),size))
        recipients,models,_=assets.pack_donor_bindings({101:skeleton,102:skeleton},0x5000000)
        donors,donor_models,_=assets.pack_donor_bindings(self.bindings,0x5100000)
        c.write(0x5000000,recipients);c.write(0x5100000,donors)
        raw=self.clips[source];scratch=0x5200000;c.write(scratch,raw)
        c.r[4:9]=[scratch,models[101],donor_models[source.character],0,0];c.r[31]=0xFEED0000
        c.run(helper.RETARGET if wrapped else A(0x24BBE8))
        self.assertEqual(c.read(0x5000000,len(recipients)),recipients)
        self.assertEqual(c.read(0x5100000,len(donors)),donors)
        if wrapped:self.assertEqual(c.r[2],1)
        return c.read(scratch,len(raw))

    def test_nonduplicate_native_output_is_byte_exact_for_all_borrowed_sources(self):
        skeleton=assets.read_skeleton(self.iso,0)
        for source in self.clips:
            with self.subTest(source=source):self.assertEqual(self.machine(skeleton,source),self.machine(skeleton,source,False))

    def test_goku_early_and_kid_gohan_outfits_keep_native_retarget_output(self):
        # The reported pairing must work for either attack role and for a
        # victim using either rig, including the damaged costume resources.
        outfits=[dict(character=character,costume=costume,damaged=damaged)
                 for character in (0,13) for costume in range(4) for damaged in (False,True)]
        self.assertTrue(all(row['supported'] for row in assets.character_admission(self.iso,outfits)))
        sources=(assets.ClipSource(101,363),assets.LEAD[352],assets.LEAD[354],
                 assets.PARTNER[414],assets.LEAD[357],assets.LEAD[358],assets.LEAD[359])
        for outfit in outfits:
            skeleton=assets.read_skeleton(self.iso,**outfit)
            for source in sources:
                with self.subTest(outfit=outfit,source=source):
                    actual=self.machine(skeleton,source)
                    self.assertEqual(actual,self.machine(skeleton,source,False))
                    clip=animations.AnimationClip.from_decoded(source.animation,actual)
                    for track in clip.tracks:
                        for key in track.keys:
                            if key.translation is not None:
                                self.assertTrue(all(math.isfinite(value) for value in key.translation))

    def test_requested_bt4_costumes_all_roles_retarget_each_translation_once(self):
        if SERIAL!='SLUS-21978':self.skipTest('BT4 imported costume fixture')
        sources=(assets.ClipSource(101,356),assets.ClipSource(101,363),assets.ClipSource(101,352),assets.PARTNER[414],assets.ClipSource(101,357),assets.ClipSource(101,358),assets.ClipSource(101,359))
        isos=(self.iso,self.iso.with_name('SLUS_219.78.DBZBT4B14REV2.iso'))
        for iso in isos:
            if not iso.is_file():continue
            for character,costume in ((11,2),(63,3)):
                for damaged in (False,True):
                    skeleton=assets.read_skeleton(iso,character,costume,damaged)
                    recipients={row['bone']:row['translation'] for row in skeleton['rows']}
                    for source in sources:
                        with self.subTest(iso=iso.name,character=character,costume=costume,damaged=damaged,source=source):
                            before=animations.AnimationClip.from_decoded(source.animation,self.clips[source])
                            after=animations.AnimationClip.from_decoded(source.animation,self.machine(skeleton,source))
                            donor={row['bone']:row['translation'] for row in self.bindings[source.character]['rows']}
                            ratio=skeleton['height']/self.bindings[source.character]['height']
                            for left,right in zip(before.tracks,after.tracks):
                                for a,b in zip(left.keys,right.keys):
                                    if a.translation is None or left.bone_id not in recipients:continue
                                    bone=left.bone_id
                                    expected=tuple((a.translation[i]-donor[bone][i])*(ratio if i==1 else 1)+recipients[bone][i] for i in range(3))
                                    for actual,want in zip(b.translation,expected):
                                        self.assertTrue(math.isfinite(actual));self.assertAlmostEqual(actual,want,delta=.0002)

if __name__=='__main__':unittest.main()
