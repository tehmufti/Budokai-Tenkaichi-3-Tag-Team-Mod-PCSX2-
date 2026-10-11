"""Narrow imported-rig admission and actual native retarget regressions."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

from pathlib import Path
import math
import struct
import unittest
from unittest.mock import patch

import tag_rush_assets as assets
import model_animations as animations


def node(bone, pop=1, *, vertices=0, local=(0.,0.,0.),size=64):
    raw=bytearray(size)
    struct.pack_into('<IHHHH',raw,0,size,pop,0,vertices,bone)
    struct.pack_into('<3f',raw,48,*local)
    return raw


def parse(nodes, imported=True, declared=None):
    geometry=bytearray(144)
    geometry[:4]=b'pmdl'
    struct.pack_into('<I',geometry,8,len(nodes) if declared is None else declared);struct.pack_into('<I',geometry,108,144)
    for i,source in enumerate(nodes):
        raw=bytearray(source);struct.pack_into('<H',raw,6,int(i==len(nodes)-1));geometry.extend(raw)
    params=struct.pack('<If',0,1.)
    with patch('model_assets.package_entry',side_effect=lambda _p,index:bytes(geometry) if index==3 else params):
        return assets.skeleton_from_package(bytes(16),params if imported else None)


class ImportedSkeletonTests(unittest.TestCase):
    def test_imported_declared_count_is_advisory_but_chain_and_limits_are_strict(self):
        valid=[node(0,0),node(10),node(52),node(53),node(54,2)]
        for declared in (1,2,3,5,8):
            self.assertEqual(len(parse(valid,declared=declared)['rows']),5)
        self.assertEqual(len(parse([node(0,0),node(10)])['rows']),2)
        for entries,declared,imported in ((valid,0,True),(valid,257,True),(valid,2,False),
                ([node(0,0),node(1,0),node(10)],3,True),([node(7)],1,True)):
            with self.assertRaises(assets.TagRushAssetError):parse(entries,imported,declared)

    def test_only_invisible_sibling_accessory_duplicates_are_accepted(self):
        valid=[node(0,0),node(49),node(49,2)]
        self.assertEqual([r['bone']for r in parse(valid)['rows']],[0,49,49])
        for entries,imported in ((valid,False),([node(0,0),node(19),node(19,2)],True),
                ([node(0,0),node(49),node(49,2,vertices=1)],True),
                ([node(0,0),node(49,0),node(49,3)],True)):
            with self.subTest(entries=entries,imported=imported),self.assertRaises(assets.TagRushAssetError):
                parse(entries,imported)

    def test_segmented_drawables_require_safe_channels_and_same_parent(self):
        valid=[node(0,0),node(19,1,vertices=1,size=80),
               node(19,0,vertices=2,size=80),node(20,3)]
        self.assertEqual(len(parse(valid,declared=3)['rows']),4)
        for bone in (8,12,17,18,21,32,35,47,48):
            segments=[node(0,0),node(bone,1,vertices=1,size=80),node(bone,2,vertices=2,size=80)]
            self.assertEqual(len(parse(segments)['rows']),3)
        for entries in ([node(0,0),node(19,0,vertices=1,size=80),node(19,0,vertices=2,size=80),node(20,4)],
                        [node(0,0),node(31,1,vertices=1,size=80),node(31,2,vertices=2,size=80)],
                        [node(0,0),node(2,1,vertices=1,size=80),node(2,2,vertices=2,size=80)]):
            with self.assertRaises(assets.TagRushAssetError):parse(entries)
        with self.assertRaises(assets.TagRushAssetError):parse(valid,False,declared=3)

    def test_contact_marker_can_follow_unanimated_motion_root_but_not_a_joint(self):
        reference=[dict(bone=0,parent=-1),dict(bone=1,parent=0),dict(bone=52,parent=0)]
        for parent,offset,drawable,supported in ((1,0.,0,True),(0,0.,0,True),
                (2,0.,0,False),(1,1.,0,False),(1,0.,1,False)):
            marker=dict(bone=52,parent=parent,translation=(0.,offset,0.),header=bytes(node(52,vertices=drawable)))
            actual=reference[:2]+[dict(bone=2,parent=1),marker]
            with self.subTest(parent=parent,offset=offset,drawable=drawable), \
                 patch.object(assets,'read_donor_bindings',return_value={101:dict(rows=reference,height=1.)}), \
                 patch.object(assets,'read_skeleton',return_value=dict(rows=actual,height=1.)):
                self.assertEqual(assets.character_admission('unused',[118])[0]['supported'],supported)

    def test_truncated_parts_nonfinite_translation_and_bad_parent_stack_still_fail(self):
        for entries in ([node(0,2)],[node(0,local=(float('nan'),0.,0.))]):
            with self.assertRaises(assets.TagRushAssetError):parse(entries)


class NativeImportedSkeletonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native_map import SERIAL,elf_path
        from prototype import ROOT,elf_reader
        if SERIAL!='SLUS-21978':raise unittest.SkipTest('BT4 native imported-rig fixture')
        cls.iso=ROOT.parent/'games/SLUS_219.78.DBZBT4B14REV2ENG.iso'
        if not cls.iso.is_file() or not elf_path(ROOT).is_file():
            raise unittest.SkipTest('The selected game disc and executable are required')
        cls.native=staticmethod(elf_reader(elf_path(ROOT))[2])
        cls.bindings=assets.read_donor_bindings(cls.iso);cls.clips=assets.read_clips(cls.iso)

    def test_reviewed_exclusive_forms_are_admitted_with_the_actual_iso(self):
        result=assets.character_admission(self.iso,[34,54,118,119,125,135,200,238,240,
            dict(character=98,costume=0,damaged=True),dict(character=98,costume=4)])
        self.assertTrue(all(row['supported']for row in result),result)
        sorbet=assets.read_skeleton(self.iso,240)
        self.assertEqual(len(sorbet['rows']),63)
        self.assertEqual(len(set(r['bone']for r in sorbet['rows'])),61)
        spanish=self.iso.with_name('SLUS_219.78.DBZBT4B14REV2.iso')
        if spanish.is_file():
            self.assertEqual(sorbet,assets.read_skeleton(spanish,240))
            self.assertEqual(assets.read_skeleton(self.iso,54),assets.read_skeleton(spanish,54))
        gogeta=assets.read_skeleton(self.iso,54)
        self.assertEqual(len(gogeta['rows']),70)
        self.assertEqual([r['bone']for r in gogeta['rows'][-3:]],[52,53,54])

    def test_native_retarget_keeps_every_imported_translation_finite_and_matches_first_bind(self):
        from native_map import A
        import test_tag_rush_retarget as fixture
        for character,costume,damaged in ((34,0,False),(54,0,False),(118,0,False),(119,0,False),
                (135,0,False),(200,0,False),(240,0,False),(2,1,False),(17,4,True),
                (63,3,False),(74,0,False),(184,1,False),(14,0,False),(38,0,False),
                (98,0,True),(98,4,False),(125,0,False),(238,0,False)):
            self.recipient=assets.read_skeleton(self.iso,character,costume,damaged)
            expected_binds={}
            for row in self.recipient['rows']:expected_binds.setdefault(row['bone'],row['translation'])
            for source in (assets.ClipSource(101,363),assets.LEAD[352],assets.PARTNER[414]):
                with self.subTest(character=character,source=source):
                    raw=self.clips[source]
                    cpu,scratch=fixture.NativeRetargetTests.machine(self,source.character,raw)
                    cpu.run(A(0x24BBE8))
                    original=animations.AnimationClip.from_decoded(source.animation,raw)
                    actual=animations.AnimationClip.from_decoded(source.animation,cpu.read(scratch,len(raw)))
                    donor={r['bone']:r['translation']for r in self.bindings[source.character]['rows']}
                    ratio=self.recipient['height']/self.bindings[source.character]['height']
                    for before,after in zip(original.tracks,actual.tracks):
                        if before.bone_id not in donor or before.bone_id not in expected_binds:continue
                        for left,right in zip(before.keys,after.keys):
                            self.assertEqual(left.rotation,right.rotation)
                            if left.translation is None:continue
                            self.assertTrue(all(math.isfinite(v) and abs(v)<10000 for v in right.translation))
                            for axis in range(3):
                                expected=(left.translation[axis]-donor[before.bone_id][axis])
                                expected*=ratio if axis==1 else 1
                                expected+=expected_binds[before.bone_id][axis]
                                self.assertAlmostEqual(right.translation[axis],expected,delta=.0002)

    def test_all_authored_tag_clips_leave_motion_root1_unanimated(self):
        for source,raw in assets.prepared_clips(self.iso).items():
            clip=animations.AnimationClip.from_decoded(source.animation,raw)
            self.assertNotIn(1,[t.bone_id for t in clip.tracks])
            self.assertFalse(any(t.bone_id not in assets.TRANSLATED_BONES and any(k.translation is not None for k in t.keys)
                                 for t in clip.tracks))
            self.assertTrue(all(t.bone_id<=assets.LAST_AUTHORED_BONE for t in clip.tracks))


if __name__=='__main__':unittest.main()
