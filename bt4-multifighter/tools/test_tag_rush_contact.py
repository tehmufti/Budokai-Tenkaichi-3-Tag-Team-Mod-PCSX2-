"""Native contact-anchor correction, height retarget and repeated alignment."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest

import model_animations as animation
import tag_rush_assets as assets
import tag_rush_choreography as choreography
import tag_rush_scene as scene
import tag_rush_shots as shots
from native_map import A
import test_tag_rush_retarget as native_retarget
from test_tag_rush_scene import fixture, start
from test_tag_rush_camera import run


class EntranceContactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native_retarget.NativeRetargetTests.setUpClass()
        cls.native_case = native_retarget.NativeRetargetTests()
        cls.original = native_retarget.NativeRetargetTests.clips

    def test_only_invisible_anchor_changes_and_native_events_survive(self):
        for phase,number in ((1,353),(2,354)):
            raw=self.original[assets.LEAD[number]]
            derived=choreography.raise_entrance_contact(raw,phase)
            before=animation.AnimationClip.from_decoded(number,raw)
            after=animation.AnimationClip.from_decoded(number,derived)
            # Appending one channel leaves every original payload byte intact;
            # the only old-byte edit is its two-byte pointer in the header.
            pointer=6+2*52
            self.assertEqual(derived[:pointer],raw[:pointer])
            self.assertEqual(derived[pointer+2:len(raw)],raw[pointer+2:])
            self.assertLess(len(derived),0xC000)
            self.assertEqual(before.frame_count,after.frame_count)
            for frame in (q/4 for q in range(4*before.frame_count+1)):
                left,right=before.evaluate(frame),after.evaluate(frame)
                for bone,value in left.items():
                    if bone!=52:self.assertEqual(right[bone],value,(number,frame,bone))
                self.assertEqual(left[52].rotation,right[52].rotation)

    def test_raise_is_smooth_holds_through_reported_shot_and_rejoins_before_contact(self):
        contact={}
        for phase,number in ((1,353),(2,354)):
            raw=self.original[assets.LEAD[number]]
            before=animation.AnimationClip.from_decoded(number,raw)
            after=animation.AnimationClip.from_decoded(number,choreography.raise_entrance_contact(raw,phase))
            contact[phase]=(before,after)
        raised=contact[1][1]
        for frame,y in ((0,0.),(6,-12.),(12,-24.),(88,-24.),(99,-24.)):
            self.assertAlmostEqual(raised.evaluate(frame)[52].translation[1],y,places=5)
            self.assertAlmostEqual(raised.evaluate(frame)[52].translation[2],y*100/24,places=4)
        values=[raised.evaluate(frame)[52].translation[1] for frame in range(13)]
        self.assertTrue(all(a>b for a,b in zip(values,values[1:])))
        self.assertLess(abs(values[1]-values[0]),.5)
        self.assertLess(abs(values[-1]-values[-2]),.5)
        before,after=contact[2]
        delta=lambda frame:after.evaluate(frame)[52].translation[1]-before.evaluate(frame)[52].translation[1]
        self.assertAlmostEqual(delta(0),-24.,places=4)
        self.assertAlmostEqual(delta(10),-12.,places=4)
        for frame in (q/4 for q in range(80,4*before.frame_count+1)):
            self.assertEqual(after.evaluate(frame)[52],before.evaluate(frame)[52],frame)
        # Native victim359's first paired impact is58; settlement is complete
        # well beforehand, including original compressed contact samples.
        self.assertEqual(after.evaluate(58)[52],before.evaluate(58)[52])

    def retarget(self,height):
        case=self.native_case
        original=case.recipient
        try:
            case.recipient=dict(original,height=height)
            raw=choreography.raise_entrance_contact(self.original[assets.LEAD[353]],1)
            cpu,scratch=case.machine(101,raw)
            cpu.run(A(0x24BBE8))
            return animation.AnimationClip.from_decoded(353,cpu.read(scratch,len(raw)))
        finally:case.recipient=original

    def test_real_native_retarget_scales_lift_by_lead_height(self):
        donor=self.native_case.bindings[101]['height']
        for height in (.6,.9,1.02,1.35):
            clip=self.retarget(height)
            beginning=clip.evaluate(0)[52].translation[1]
            for frame,source in ((6,-12.),(12,-24.),(88,-24.),(99,-24.)):
                difference=clip.evaluate(frame)[52].translation[1]-beginning
                self.assertAlmostEqual(difference,source*height/donor,delta=.0002)
                self.assertAlmostEqual(clip.evaluate(frame)[52].translation[2]-clip.evaluate(0)[52].translation[2],source*100/24,delta=.0002)

    def test_preserved_native_shot_keeps_actual_victim_mesh_behind_camera_after_ramp(self):
        import numpy as np
        import model_assets
        from native_map import SERIAL
        iso=self.native_case.iso
        victim=151 if SERIAL=='SLUS-21978' else 0
        mesh=model_assets.load_character(iso,victim)
        raw=choreography.recover_entrance_victim(
            self.original[assets.LEAD[358]],self.original[assets.LEAD[359]],
            choreography.stabilize_opening_victim(self.original[assets.LEAD[357]],self.original[assets.LEAD[359]]))
        clip=animation.AnimationClip.from_decoded(358,raw)
        donor=self.native_case.bindings[101]
        heights=assets.read_skeleton(iso,victim)['height']/donor['height']
        binds={row['bone']:np.array(row['translation']) for row in donor['rows']}
        track=shots.read_track(iso)
        def rotation(q):
            x,y,z,w=q
            return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),0],
                [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),0],
                [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),0],[0,0,0,1.]])
        original_positions=np.column_stack((mesh.positions,np.ones(len(mesh.positions))))
        weights={bone.native_id:np.sum(np.where(mesh.bone_indices==bone.native_id,mesh.bone_weights,0),axis=1)
                 for bone in mesh.bones}
        inverses={bone.native_id:np.linalg.inv(bone.bind_world) for bone in mesh.bones}
        for frame in range(12,100):
            pose=clip.evaluate(frame);world={}
            for bone in mesh.bones:
                value=pose.get(bone.native_id)
                matrix=rotation(value.rotation) if value else np.eye(4)
                translation=np.array(bone.bind_translation)
                if value and value.translation is not None:
                    translation=np.array(value.translation)-binds.get(bone.native_id,np.zeros(3))
                    translation[1]*=heights;translation+=bone.bind_translation
                matrix[:3,3]=translation
                world[bone.native_id]=world.get(bone.parent_id,np.eye(4))@matrix
            vertices=np.zeros((len(mesh.positions),3))
            for bone in mesh.bones:
                weight=weights[bone.native_id];mask=weight>0
                if np.any(mask):
                    matrix=world[bone.native_id]@inverses[bone.native_id]
                    vertices[mask]+=(original_positions[mask]@matrix.T)[:,:3]*weight[mask,None]
            vertices-=world[3][:3,3]
            native=track.sample(shots.PHASE_STARTS[1]+frame)
            rx,ry,rz=native[3:];self.assertEqual(rz,0.)
            # Native camera's forward basis is near +Z throughout this shot.
            # Use the larger possible pitch/yaw sign contributions as an
            # additional bound: even that puts the complete mesh behind Z=0.
            for lead_ratio in (2/3,1.,1.7):
                eye=np.array(native[:3]);eye[1]*=lead_ratio
                for victim_scale in (.55,1.,2.):
                    delta=vertices*victim_scale+np.array((0.,-24.*lead_ratio,-100.))-eye
                    depth=(delta[:,2]*math.cos(rx)*math.cos(ry)
                           +np.abs(delta[:,0]*math.sin(ry))
                           +np.abs(delta[:,1]*math.sin(rx)))
                    self.assertLess(float(depth.max()),-1.,(frame,lead_ratio,victim_scale))

    def test_emitted_alignment_moves_only_victim_without_accumulating_or_using_victim_height(self):
        for height in (.6,1.02,1.35):
            retargeted=self.retarget(height)
            expected_lift=retargeted.evaluate(88)[52].translation[1]-retargeted.evaluate(0)[52].translation[1]
            for victim_height in (.55,1.5):
                c=fixture();start(c);self.assertEqual(c.r[2],1)
                victim=c.models[1];actor=c.actors[1]
                lead52=c.u(c.models[0]+3436+4*52)+64
                victim3=c.u(victim+3436+4*3)+64
                c.fw(c.u(victim+2332)+4,victim_height)
                def victim_pose(m):
                    model=m.r[4]
                    self.assertEqual(model,victim)
                    x,y,z,w=struct.unpack('<4f',m.read(model+2384,16))
                    m.write(victim3,struct.pack('<4f',x,y-25.*victim_height,z,w))
                c.callbacks[A(0x24E3F8)]=victim_pose
                attackers=[(c.read(c.actors[i],0x1800),c.read(c.models[i],0x1800)) for i in (0,2,3)]
                baseline=None
                for frame in (0,6,12,88,99):
                    local=retargeted.evaluate(frame)[52].translation
                    point=(160.,-180.+local[1],50.+local[2],1.)
                    c.write(lead52,struct.pack('<4f',*point))
                    c.r[4]=victim;victim_pose(c)
                    run(c,scene.ALIGN);self.assertEqual(c.r[2],1)
                    placed=struct.unpack('<4f',c.read(actor+16,16))
                    self.assertTrue(all(math.isfinite(v) and abs(v)<1000 for v in placed))
                    self.assertAlmostEqual(c.fr(victim3+4),point[1],places=4)
                    if baseline is None:baseline=placed
                    if frame==88:
                        self.assertAlmostEqual(placed[1]-baseline[1],expected_lift,places=4)
                        self.assertAlmostEqual(placed[2]-baseline[2],-100.,places=4)
                    for _ in range(12):run(c,scene.ALIGN)
                    self.assertEqual(c.read(actor+16,16),struct.pack('<4f',*placed))
                self.assertEqual(attackers,[(c.read(c.actors[i],0x1800),c.read(c.models[i],0x1800)) for i in (0,2,3)])


if __name__=='__main__':unittest.main()
