"""Offline poser/profile geometry utilities and authored payload ownership.

The F000 diagnostic profile table no longer controls native gameplay poses.
Native endpoint fidelity is covered by authored-hold and actual-rig tests.
"""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest

import tag_rush_full_nelson as ik
import tag_rush_full_nelson_profiles as profiles
from test_tag_rush_full_nelson import actual_pose,discs,native_fit


class HeadProfileTests(unittest.TestCase):
    def test_contact_uses_triangle_surface_and_ignores_degenerate_seed_faces(self):
        import numpy as np
        triangle=np.array([[(0.,0.,0.),(2.,0.,0.),(0.,2.,0.)]])
        self.assertAlmostEqual(profiles.closest_surface_distance(triangle,np.array([(.25,.25,1.)])),1.)
        self.assertAlmostEqual(profiles.closest_surface_distance(triangle,np.array([(3.,0.,0.)])),1.)
        dangling=np.array([[ (.25,.25,5.) ]*3])
        self.assertAlmostEqual(profiles.closest_surface_distance(np.concatenate((dangling,triangle)),np.array([(.25,.25,5.)])),5.)

    def rigs(self,character=156):
        paths=discs()
        if not paths:self.skipTest('User-owned game disc unavailable')
        cache={};g=actual_pose(paths[0],0,0,2,20,cache);v=actual_pose(paths[0],character,2,2,20,cache)
        return paths[0],g,v

    def test_authored_endpoint_payload_is_immutable_and_has_no_runtime_profile_lookup(self):
        import tag_rush_authored_hold as authored
        _,g,v=self.rigs()
        c,_,_=native_fit(*g,*v,phase=2,ticks=11)
        self.assertEqual(c.r[2],1)
        self.assertEqual(c.read(authored.DATA,len(authored.data())),authored.data())
        self.assertFalse(any(authored.DATA<=at<authored.END for at,_ in c.nonstack_writes))
        self.assertFalse(any(profiles.DATA<=at<profiles.END for at,_ in c.nonstack_writes))
        # This is the authored payload reservation. The old diagnostic profile
        # builder remains an offline geometry tool and is not an active input.
        self.assertLessEqual(authored.DATA+len(authored.data()),profiles.DATA)
        self.assertEqual(struct.unpack_from('<4I',authored.data()),
            (authored.MAGIC,authored.VERSION,3,authored.STRIDE))

    def test_offline_geometry_profile_inventory_is_diagnostic_and_bounded(self):
        paths=discs()
        if not paths:self.skipTest('User-owned game disc unavailable')
        for iso in paths:
            with self.subTest(iso=iso.name):
                plan=profiles.build_assets(iso,[dict(character=c) for c in (25,27,133)])
                # BT4's imported DBS Broly currently has duplicate texture
                # bindings; the geometry reader must report that explicitly,
                # while the native bone-width fallback still works (below).
                from native_map import SERIAL
                for unavailable in plan['unavailable']:
                    self.assertEqual(SERIAL,'SLUS-21978')
                    self.assertEqual(unavailable['character'],133)
                    self.assertEqual(unavailable['reason'],'Missing or ambiguous model texture binding')
                rows={(r['character'],r['damaged']):r for r in plan['rows']}
                for c in (25,27,133) if (133,False) in rows else (25,27):
                    for damaged in (False,True):
                        row=rows[c,damaged];self.assertTrue(math.isfinite(row['residual']))
                        self.assertEqual(len(row['source_sha256']),64)
                        self.assertTrue(0<=row['head_clearance']<=3.5)
                        self.assertEqual(row['limitations'],[name+' intersection' for name,value in row['residuals'].items() if value>=.015])
                        self.assertTrue(math.isfinite(row['contact']))
                        if row['skin_intersections'] is None:
                            self.assertEqual(row['style'],1)  # Offline wide-hook audit does not run the nape-solid oracle.
                        else:self.assertGreaterEqual(row['skin_intersections'],0)
                        self.assertIn(row['style'],(0,1))
                for row in rows.values():
                    self.assertTrue(-1.5<=row['palm_height']<=3.)
                    self.assertTrue(0<=row['body_clearance']<=2.)
                p,b=plan['blocks'][0];self.assertEqual(p,profiles.DATA);self.assertLessEqual(p+len(b),profiles.END)
                self.assertEqual(struct.unpack_from('<3I',b),(profiles.MAGIC,len(rows),32))
                for offset,row in enumerate(plan['rows']):
                    unpacked=struct.unpack_from('<3I4fI',b,16+32*offset)
                    self.assertEqual(unpacked[:3],(row['character'],row['costume'],int(row['damaged'])))
                    self.assertEqual(unpacked[-1],row['style'])

    def test_wide_style_rigid_subtrees_match_local_recomposition(self):
        from model_animations import BoneTransform
        _,g,v=self.rigs(133);model,pose,world=v
        original={b:tuple(tuple(float(x) for x in row) for row in m) for b,m in world.items()}
        for gain in (0.,.25,.5,1.):
            fitted,local=ik.adjusted_victim(world,style=1,gain=gain)
            adjusted=dict(pose)
            for b,q in local.items():adjusted[b]=BoneTransform(adjusted[b].translation,q)
            rebuilt=profiles.world_matrices(model.bones,adjusted)
            for b,m in rebuilt.items():
                for i in range(4):
                    for j in range(4):self.assertAlmostEqual(float(m[i][j]),float(fitted[b][i][j]),places=5)
            for a,b in ((18,19),(19,20),(20,21),(32,33),(33,34),(34,35)):
                self.assertAlmostEqual(ik.length(ik.sub(ik.position(world[b]),ik.position(world[a]))),
                    ik.length(ik.sub(ik.position(fitted[b]),ik.position(fitted[a]))),places=6)
            self.assertEqual(set(local),{18,19,32,33})
        for b,m in world.items():self.assertEqual(original[b],tuple(tuple(float(x) for x in row) for row in m))

    def test_fitter_style_and_palm_height_are_bounded(self):
        _,g,v=self.rigs()
        for options in (dict(style=2),dict(palm_height=math.nan),dict(palm_height=-2.),dict(palm_height=3.5)):
            with self.subTest(options=options),self.assertRaises(ValueError):ik.fit_pair(g[2],v[2],**options)
        ordinary=ik.fit_pair(g[2],v[2]);self.assertEqual(set(ordinary.victim_rotations),{18,19,20,32,33,34})

    def test_unknown_transformed_body_uses_width_fallback_but_exact_style_wins(self):
        _,g,v=self.rigs(133)
        fallback=ik.fit_pair(g[2],v[2]);wide=ik.fit_pair(g[2],v[2],style=1)
        self.assertEqual(fallback,wide)
        self.assertEqual(set(fallback.victim_rotations),{18,19,32,33})
        self.assertEqual(set(ik.fit_pair(g[2],v[2],style=0).victim_rotations),{18,19,20,32,33,34})
        for gain in (0.,.25,.5,1.):
            fitted,_=ik.adjusted_victim(v[2],style=1,gain=gain)
            for a,b in ((19,20),(20,21),(33,34),(34,35)):
                self.assertAlmostEqual(ik.length(ik.sub(ik.position(fitted[a]),ik.position(fitted[b]))),
                    ik.length(ik.sub(ik.position(v[2][a]),ik.position(v[2][b]))),places=6)


if __name__=='__main__':unittest.main()
