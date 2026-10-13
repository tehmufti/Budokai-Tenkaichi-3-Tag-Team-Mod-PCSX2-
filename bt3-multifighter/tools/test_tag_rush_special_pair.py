"""Native restraint provenance, exact pair routing and sacrifice handoff."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import copy
import math
import struct
import unittest
from pathlib import Path

import model_animations as animation
import tag_rush_assets as assets
import tag_rush_choreography as choreography
import tag_rush_damage as damage
import tag_rush_recovery as recovery
import tag_rush_scene as scene
import tag_rush_special_pair as special
import tag_team_rush as tag
from test_tag_rush_camera import run
from test_tag_rush_scene import fixture


def special_scene(order=(0,22)):
    c=fixture()
    # This fixture isolates routing/ownership with synthetic six-marker rigs.
    # The hold suite separately runs the authored native poses on real rigs.
    import tag_rush_full_nelson_native as nelson
    c.callbacks[nelson.FIT]=lambda m:m.r.__setitem__(2,1)
    for index,character in zip((0,2),order):
        c.w(c.models[index]+12,character)
        c.write(c.u(scene.ADMISSION)+character,bytes([3]))
    # Selection is exercised with real, already-reviewed ordinary descriptors;
    # the disc tests separately establish the special animation/shot contents.
    address=assets.BASE+0x1000
    c.write(address,c.read(assets.BASE,5*64))
    c.w(tag.CONTROL+special.TABLE_OFFSET,address)
    c.w(tag.CONTROL+special.COUNT_OFFSET,5)
    for i in range(5):c.write(0x3110000+4*80+i*16,bytes(16))
    c.r[4:7]=[0,2,1]
    run(c,scene.START)
    return c


class PairTests(unittest.TestCase):
    def test_only_the_exact_early_pair_is_selected_in_either_order(self):
        for order in ((0,22),(22,0)):
            c=special_scene(order)
            self.assertEqual(c.r[2],1)
            self.assertEqual(c.u(tag.CONTROL+tag.C['variant']),4)
            self.assertEqual(c.u(scene.ROWS+scene.R['character']),0)
            self.assertEqual(c.u(scene.ROWS+scene.STRIDE+scene.R['character']),22)
            self.assertEqual(c.u(scene.ROWS+2*scene.STRIDE+scene.R['index']),1)
            self.assertEqual(c.u(tag.CONTROL+tag.C['members']),0b111)
        for order in ((1,22),(0,23),(22,23),(0,0)):
            c=special_scene(order)
            self.assertEqual(c.r[2],1)
            self.assertEqual(c.u(tag.CONTROL+tag.C['variant']),0,order)

    def test_missing_special_table_rejects_without_consuming_or_interrupting(self):
        c=fixture();c.w(c.models[2]+12,22);c.write(c.u(scene.ADMISSION)+22,bytes([3]))
        meters=c.read(tag.METERS,4*tag.METER_STRIDE)
        c.r[4:7]=[0,2,1];run(c,scene.START)
        self.assertEqual(c.r[2],0)
        self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)
        self.assertEqual(c.read(tag.METERS,4*tag.METER_STRIDE),meters)
        self.assertFalse(c.idle_starts)

    def test_special_has_one_piccolo_beam_and_matched_hold_phases(self):
        phases=special.timeline()
        self.assertEqual([p.source_frames for p in phases],[28,24,45,30,180])
        # The opening lasts exactly the authored acquisition; the hold begins at its endpoint.
        import tag_rush_authored_hold as authored
        self.assertEqual(sum(p.source_frames for p in phases[:2]),authored.ACQUISITION_FRAMES)
        self.assertEqual([record[1]for record in special.records()],[13,13,13,13,15])
        self.assertEqual(len(special.records()),len(phases))
        for i,p in enumerate(phases):
            self.assertTrue(p.flags&special.RESTRAIN)
            self.assertEqual(p.roles[0],assets.ClipSource(special.DONOR,1100+i))
            self.assertEqual(p.roles[2],assets.ClipSource(special.DONOR,1110+i))
            self.assertFalse(p.flags&assets.BEAM_LEAD)
            self.assertEqual(bool(p.flags&assets.BEAM_PARTNER),i==4)
            self.assertEqual(choreography.phase_contacts(special.NAME,i),())
        self.assertEqual(special.records()[-1][1:3],(15,90))

    def test_native_stage_angles_use_degrees_and_cancel_the_model_half_turn(self):
        # staging.APPLY converts metadata degrees to radians; native24E2B0
        # then addsPI to construct the rendered model root. The real captured
        # yaw delta was .054831, precisely math.pi interpreted as degrees.
        self.assertAlmostEqual(2.498296022415161-2.443464994430542,
                               math.radians(math.pi),places=6)
        for phase in special.records():
            goku,piccolo,victim=phase[4:]
            self.assertEqual((goku[3],piccolo[3],victim[3]),(180.,0.,180.))
            for yaw in (0.,2.443464994430542,-.75,math.pi):
                lane=(-58.*math.sin(yaw),-58.*math.cos(yaw))
                lane_length=math.hypot(*lane)
                for mark in (goku,victim):
                    model_yaw=yaw+math.radians(mark[3])+math.pi
                    forward=(-math.sin(model_yaw),-math.cos(model_yaw))
                    self.assertGreater(sum(a*b for a,b in zip(forward,lane))/lane_length,.999999)
                # Piccolo points back toward the held pair, opposite their forward.
                model_yaw=yaw+math.radians(piccolo[3])+math.pi
                forward=(-math.sin(model_yaw),-math.cos(model_yaw))
                self.assertLess(sum(a*b for a,b in zip(forward,lane))/lane_length,-.999999)

    def test_upright_hold_uses_contiguous_native_samples_and_level_shots(self):
        import tag_rush_shots as shots
        self.assertEqual(special.SEGMENTS[0][:3],(356,361,12))
        for current,following in zip(special.SEGMENTS,special.SEGMENTS[1:]):
            self.assertEqual(current[:2],(356,361))
            self.assertEqual(current[3],following[2])
        for shot in (13,14,15):
            for fraction in (0.,.35,.75,1.):
                matrix,focus=shots.custom_sample(shot,fraction)
                self.assertLess(abs(matrix[13]-focus[1]),10.)
        # Piccolo faces the pair along +Z; his charge closeup sees his face.
        matrix,focus=shots.custom_sample(14,0.)
        self.assertGreater(matrix[14],focus[2])

    def test_hold_camera_separates_the_captured_holders_torso_from_the_victim(self):
        import tag_rush_shots as shots
        # Native live posed chest points, expressed in the scene's yaw frame.
        # The original positive-X eye looked through Raditz directly at Goku.
        chests=((1.52,-12.51,1.58),(5.02,-12.47,5.64))
        for fraction in (0.,.25,.5,.75,1.):
            matrix,_=shots.custom_sample(13,fraction)
            projected=[]
            for point in chests:
                delta=tuple(p-e for p,e in zip(point,matrix[12:15]))
                x,z=(sum(a*b for a,b in zip(delta,matrix[off:off+3]))for off in (0,8))
                self.assertGreater(z,20.)
                projected.append(x/z)
            self.assertGreater(abs(projected[1]-projected[0]),.11)
            self.assertLess(matrix[12],0.)

    def test_hold_pan_continues_across_crops_before_one_piccolo_charge_cut(self):
        import tag_rush_shots as shots
        for hz in(25,30):
            for phase in range(3):
                duration=special.SEGMENTS[phase][4]
                before=shots.special_hold_fraction(phase,duration*hz/60,hz)
                after=shots.special_hold_fraction(phase+1,0,hz)
                self.assertAlmostEqual(before,after,places=9)
                self.assertEqual(shots.custom_sample(13,before),shots.custom_sample(13,after))
            self.assertEqual(shots.special_hold_fraction(3,special.SEGMENTS[3][4]*hz/60,hz),1.)
        records=special.records()
        self.assertEqual([r[1]for r in records[:4]],[13]*4)
        self.assertEqual(records[4][1],15)

    def test_full_nelson_is_scoped_and_ordinary_native_contact_is_unchanged(self):
        import tag_rush_full_nelson_native as nelson
        for variant in (0,4):
            c=special_scene();c.w(tag.CONTROL+tag.C['variant'],variant);calls=[]
            def fitted(m):calls.append(tuple(m.r[4:6]));m.r[2]=1
            c.callbacks[nelson.FIT]=fitted
            for model,bone,point in ((c.models[0],52,(20.,-5.,30.)),(c.models[1],3,(2.,-3.,7.))):
                c.write(c.u(model+3436+4*bone)+64,struct.pack('<3f',*point))
            before=struct.unpack('<3f',c.read(c.actors[1]+16,12));run(c,scene.ALIGN)
            self.assertEqual(c.r[2],1)
            after=struct.unpack('<3f',c.read(c.actors[1]+16,12))
            self.assertEqual(tuple(a-b for a,b in zip(after,before)),(0.,0.,0.)if variant==4 else(18.,-2.,23.))
            self.assertEqual(calls,[(scene.ROWS,scene.ROWS+2*scene.STRIDE)]if variant==4 else[])

    def test_sacrifice_control_defaults_and_fractional_multiplier(self):
        options=dict(tag_team_rush_enabled=True,tag_team_rush_shared_camera=False,
                     tag_team_rush_charge_seconds=25,tag_team_rush_damage=15000,
                     tag_team_rush_training_full=False)
        blob=tag.control_bytes(0x1000000,4,options)
        self.assertEqual(struct.unpack_from('<2I',blob,108),(1,2000))
        options.update(tag_team_rush_sacrifice_enabled=False,tag_team_rush_sacrifice_multiplier=1.75)
        self.assertEqual(struct.unpack_from('<2I',tag.control_bytes(0x1000000,4,options),108),(0,1750))

    def test_goku_fall_requires_completed_sacrifice_loss_and_same_hp_bank(self):
        for changed in (None,'variant','sacrifice','finalized','loss','bank','character'):
            c=special_scene();row=scene.ROWS
            c.w(damage.STATE,damage.MAGIC)
            c.w(damage.STATE+4,c.u(tag.CONTROL+4));c.w(damage.STATE+8,4)
            c.w(damage.STATE+damage.C['sacrifice'],1)
            c.w(damage.STATE+damage.C['finalized'],1)
            c.w(damage.STATE+damage.C['goku_loss'],5000)
            c.w(damage.STATE+damage.C['goku_bank'],0)
            c.w(c.models[0]+192,c.u(row+scene.R['clip0']))
            if changed=='variant':c.w(tag.CONTROL+tag.C['variant'],0)
            elif changed in ('sacrifice','finalized'):c.w(damage.STATE+damage.C[changed],0)
            elif changed=='loss':c.w(damage.STATE+damage.C['goku_loss'],0)
            elif changed=='bank':c.w(c.actors[0]+0x994,1)
            elif changed=='character':c.w(c.models[0]+12,1)
            c.r[4:6]=[row,assets.BEAM_PARTNER|assets.FINISHER]
            run(c,recovery.BEGIN)
            self.assertEqual(c.r[2],int(changed is None),changed)
            self.assertEqual(c.u(c.actors[0]+2376),217 if changed is None else 11)
        c=special_scene();c.r[4:6]=[scene.ROWS+scene.STRIDE,assets.BEAM_PARTNER]
        run(c,recovery.BEGIN);self.assertEqual(c.r[2],0,'Piccolo must never acquire sacrifice recovery')


class DiscTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__).resolve().parent)
              else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        cls.iso=Path(__file__).resolve().parents[2]/'games'/name
        if not cls.iso.is_file():raise unittest.SkipTest('Owned local disc unavailable')
        cls.pack=special.build(cls.iso)

    def test_actual_faces_include_the_native_half_turn_and_face_the_firing_lane(self):
        import numpy as np
        import model_assets as models
        import tag_rush_full_nelson_profiles as profiles
        from test_tag_rush_full_nelson import actual_pose
        cache={}
        def root(mark):
            x,y,z,yaw=mark;angle=math.radians(yaw)+math.pi
            return np.array(((math.cos(angle),0,math.sin(angle),x),(0,1,0,y),
                             (-math.sin(angle),0,math.cos(angle),z),(0,0,0,1)))
        for phase,frame in ((1,16),(4,70)):
            marks=special.records()[phase][4:]
            worlds=[]
            for character,role,mark in ((0,0,marks[0]),(77,2,marks[2])):
                _,_,world=actual_pose(self.iso,character,role,phase,frame,cache)
                worlds.append({bone:root(mark)@matrix for bone,matrix in world.items()})
            bank=models.read_animation_bank(self.iso,22)
            clip=animation.AnimationClip.from_decoded(331,animation.decompress_animation(models.package_entry(bank,332)))
            model=models.load_character(self.iso,22)
            world=profiles.world_matrices(model.bones,clip.evaluate((clip.frame_count-1)/3))
            worlds.append({bone:root(marks[1])@matrix for bone,matrix in world.items()})
            for role,world in enumerate(worlds):
                other=worlds[2 if role<2 else 1]
                facing=-world[47][:3,2].copy();toward=other[47][:3,3]-world[47][:3,3]
                facing[1]=toward[1]=0
                self.assertGreater(float(facing@toward/np.linalg.norm(facing)/np.linalg.norm(toward)),.9,
                                   (phase,role,'The rendered head must face the beam lane'))

    def test_native_crop_keeps_the_restraint_contact_and_excludes_yamu_and_events(self):
        original=special.read_sources(self.iso)
        base,blob=self.pack['blocks'][0]
        self.assertLess(base+len(blob),special.END)
        self.assertEqual(len(self.pack['clips']),10)
        for row in self.pack['clips']:
            raw=animation.decompress_animation(blob[row['address']-base:row['address']-base+row['size']])
            clip=animation.AnimationClip.from_decoded(row['animation'],raw)
            index=(row['animation']-1100)%10
            donor=special.SEGMENTS[index][0 if row['animation']<1110 else 1]
            start,end,frames=special.SEGMENTS[index][2:]
            self.assertEqual(clip.frame_count,frames)
            self.assertGreaterEqual(len(clip.tracks),40)
            self.assertEqual(struct.unpack_from('<H',raw)[0]>>8,0)
            self.assertTrue(all(t.bone_id<=52 and t.bone_id!=1 for t in clip.tracks))
            for actual_frame,source_frame in ((0,start),(frames,end)):
                actual=clip.evaluate(actual_frame);source=original[donor].evaluate(source_frame)
                self.assertIn(actual[0].translation,(None,(0.,0.,0.)))
                # Translation of both body and contact marker changes by one
                # common origin only; their relative restraint geometry remains.
                if source[52].translation is None:
                    self.assertIsNone(actual[52].translation)
                else:
                    for axis in range(3):
                        self.assertAlmostEqual(actual[52].translation[axis]-actual[2].translation[axis],
                                               source[52].translation[axis]-source[2].translation[axis],places=3)
                role=0 if row['animation']<1110 else 2
                # The opening keeps the native upper bodies; only the victim root is pinned.
                authored=(() if role==0 else special.OPENING_VICTIM) if index==0 else (special.AUTHORED_HOLDER if role==0 else special.AUTHORED_VICTIM)
                expected=special.upper_body(role,index,actual_frame,frames)
                for bone in actual:
                    q,r=actual[bone].rotation,source[bone].rotation
                    if bone in authored:r=expected[bone]
                    self.assertGreater(abs(sum(a*b for a,b in zip(q,r))),.999)

    def test_authored_hold_on_actual_body_types_has_exact_pose_and_fixed_lengths(self):
        from test_tag_rush_full_nelson import actual_pose,native_fit,authored_reference
        import tag_rush_full_nelson as ik
        import tag_rush_authored_hold as authored
        from native_map import SERIAL
        targets=(25,28,77,80,84,87,112,117,133,156)
        if SERIAL=='SLUS-21978':targets=tuple(190 if c==133 else c for c in targets)
        cache={};g=actual_pose(self.iso,0,0,2,20,cache)
        for character in targets:
            with self.subTest(character=character):
                v=actual_pose(self.iso,character,2,2,20,cache)
                receipt,reference=authored_reference(*g,*v)
                c,_,original=native_fit(*g,*v,phase=2,ticks=11,recompose=True)
                self.assertEqual(c.r[2],1)
                self.assertEqual(receipt['source_sha256'],authored.SOURCE_SHA256)
                for role,(pose,root,world)in enumerate(reference):
                    for bone,q in pose.items():
                        at=0x2300000+role*0x10000+bone*0x100
                        self.assertEqual(c.read(at+144,16),original[role,bone][:16])
                        actual=struct.unpack('<4f',c.read(at+160,16))
                        self.assertGreater(abs(ik.dot(actual,q.rotation)),1.-2e-5)
                        self.assertLess(ik.length(ik.sub(ik.position(c.recomposed[role][bone]),ik.position(world[bone]))),1e-3)
                    source_world=g[2]if role==0 else v[2]
                    for first,last in((19,20),(20,21),(21,31),(33,34),(34,35),(35,45)):
                        self.assertAlmostEqual(ik.length(ik.sub(ik.position(c.recomposed[role][first]),ik.position(c.recomposed[role][last]))),
                            ik.length(ik.sub(ik.position(source_world[first]),ik.position(source_world[last]))),places=4)
                self.assertEqual([row[0]for row in c.native_calls],
                    [0x1D7198,0x1D7198,0x24E3F8,0x24E3F8,0x1D70E8,0x1D70E8,0x1DABE8])

    def test_complete_recipe_rejects_special_bank_and_donor_tampering(self):
        import tag_rush_install as install
        pack=assets.build_assets(self.iso,include_beam=True,include_camera=True)
        install.review_playtest_assets(pack,self.iso)
        self.assertEqual(damage.schedules(pack)[special.NAME],((4,96,10000),))
        for address,reason in ((special.BASE+200,'restraint source'),
                               (pack['special_role_donors_address'],'donor bindings')):
            changed=copy.deepcopy(pack)
            for i,(base,blob) in enumerate(changed['blocks']):
                if base<=address<base+len(blob):
                    blob=bytearray(blob);blob[address-base]^=1
                    changed['blocks'][i]=(base,bytes(blob));break
            else:self.fail('Expected special asset not found')
            with self.assertRaisesRegex(ValueError,reason):install.review_playtest_assets(changed,self.iso)


if __name__=='__main__':unittest.main()
