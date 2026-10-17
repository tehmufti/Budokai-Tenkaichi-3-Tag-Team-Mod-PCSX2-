"""Expanded liquid surfaces use their own world-space mesh archive."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from .adapters import identify
from .disc import Disc,FormatError,package,u32
from .expanded_maps import BUILD_VERSION,installed
from .map_scaling import ScalePlan,_surface_meshes,plan_stage

ROOT=Path(__file__).resolve().parents[1]
DISCS=(
    'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso',
    'Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) (Versus Fighting) (ISO) (PS2).iso',
    'Dragon Ball Z - Sparking! Meteor (Japan).iso',
    'SLUS_219.78.DBZBT4B14REV2ENG.iso',
    'SLUS_219.78.DBZBT4B14REV2.iso',
)


class SurfaceSafetyTests(unittest.TestCase):
    def archive(self):
        # One material, one mesh and one triangle, with visibly different
        # position, W, UV and color values to catch an overbroad float patch.
        data=bytearray(64+336)
        struct.pack_into('<8I',data,64,int.from_bytes(b'mdl3','little'),4,0,32,1,32,1,96)
        struct.pack_into('<3I',data,64+96,0,1,192)
        for off in (48,64,80):struct.pack_into('<4f',data,64+96+off,1,2,3,1)
        for vertex in range(192,336,48):
            struct.pack_into('<12f',data,64+vertex,10,20,30,1,.25,.5,1,0,64,64,64,128)
        return data,[(0,0)]*12+[(0,len(data))]

    def test_only_mesh_positions_and_bounds_scale(self):
        raw,entries=self.archive();plan=ScalePlan(raw,2);_surface_meshes(plan,entries);out=plan.preview()
        self.assertEqual(len(plan.fields),18)
        for vertex in range(192,336,48):
            self.assertEqual(struct.unpack_from('<3f',out,64+vertex),(20,40,60))
            self.assertEqual(raw[64+vertex+12:64+vertex+48],out[64+vertex+12:64+vertex+48])
        for off in (48,64,80):
            self.assertEqual(struct.unpack_from('<4f',out,64+96+off),(2,4,6,1))
        self.assertEqual(raw[:64+96+48],out[:64+96+48])

    def test_malformed_surface_is_rejected_before_preview(self):
        for offset,value in ((68,5),(64+28,0xfffffff0),(64+96,1),
                             (64+96+4,0xffffffff),(64+96+8,64),
                             (64+96+8,193),(64+192,0x7fc00000)):
            with self.subTest(offset=offset,value=value):
                raw,entries=self.archive();struct.pack_into('<I',raw,offset,value)
                with self.assertRaises(FormatError):_surface_meshes(ScalePlan(raw,2),entries)

    def test_generated_water_texture_does_not_require_authored_material(self):
        raw,entries=self.archive();struct.pack_into('<I',raw,64+16,0)
        struct.pack_into('<I',raw,64+96+32,0x807)
        plan=ScalePlan(raw,2);_surface_meshes(plan,entries)
        self.assertEqual(len(plan.fields),18)
        struct.pack_into('<I',raw,64+96+32,7)
        with self.assertRaises(FormatError):_surface_meshes(ScalePlan(raw,2),entries)

    def test_old_generated_isos_require_rebuild(self):
        self.assertGreater(BUILD_VERSION,2)
        with tempfile.TemporaryDirectory()as folder:
            manifest=Path(folder)/'maps.json';manifest.write_text(json.dumps(dict(build_version=2)))
            with patch('iso_compatibility.expanded_maps.cached_profile')as profile:
                self.assertIsNone(installed(manifest=manifest));profile.assert_not_called()


class DiscLiquidTests(unittest.TestCase):
    def discs(self):
        found=[ROOT/'games'/name for name in DISCS if (ROOT/'games'/name).exists()]
        if not found:self.skipTest('Local game discs are unavailable')
        return found

    def test_all_local_surface_archives_have_bounded_geometry(self):
        # Include both native view variants and all stages, not just Namek.
        checked=0
        for path in self.discs():
            with Disc(path)as disc:
                adapter,_=identify(disc)
                for base in (adapter.stage_base,adapter.split_stage_base):
                    for sid in range(adapter.stage_count):
                        try:raw=disc.read(base+sid);entries=package(raw)
                        except FormatError:continue  # unused/non-stage BT4 slots
                        with self.subTest(disc=path.name,file_id=base+sid):
                            plan=ScalePlan(raw,2);_surface_meshes(plan,entries)
                            checked+=bool(plan.fields)
        self.assertGreater(checked,0)

    def test_namek_and_dying_planet_meshes_and_water_physics_scale_together(self):
        for path in self.discs():
            with Disc(path)as disc:
                adapter,_=identify(disc)
                for base in (adapter.stage_base,adapter.split_stage_base):
                    for sid in (2,15):
                        with self.subTest(disc=path.name,file_id=base+sid):
                            raw=disc.read(base+sid);plan=plan_stage(raw,2);out=plan.preview();entries=package(raw)
                            self.assertEqual(len(out),len(raw))
                            self.assertGreater(plan.categories['surface_mesh_vertices'],0)
                            self.assertGreater(plan.categories['surface_mesh_bounds'],0)
                            a,b=entries[12];model=raw[a+64:b]
                            for mesh in range(u32(model,28),u32(model,28)+u32(model,24)*96,96):
                                for vertex in range(u32(model,mesh+8),u32(model,mesh+8)+144*u32(model,mesh+4),48):
                                    at=a+64+vertex
                                    self.assertEqual(struct.unpack_from('<3f',out,at),tuple(v*2 for v in struct.unpack_from('<3f',raw,at)))
                                    self.assertEqual(raw[at+12:at+48],out[at+12:at+48])
                            a,b=entries[1];mapd=raw[a:b]
                            for row in range(u32(mapd,20),u32(mapd,20)+16*u32(mapd,16),16):
                                at=a+row+8
                                if u32(mapd,row+4)&2:
                                    self.assertEqual(struct.unpack_from('<f',out,at)[0],2*struct.unpack_from('<f',raw,at)[0])
                                else:self.assertEqual(raw[at:at+4],out[at:at+4])


if __name__=='__main__':unittest.main()
