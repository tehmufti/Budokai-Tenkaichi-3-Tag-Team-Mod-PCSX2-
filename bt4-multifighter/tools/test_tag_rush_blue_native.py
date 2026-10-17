"""Local paired-beam registration, authored-bank and guest-clock contracts."""
import math
import struct
import unittest
from unittest.mock import patch
import numpy as np
import tag_rush_blue_native as blue
import tag_rush_assets as assets
import tag_rush_scene as scene
import tag_rush_damage as damage
import tag_team_rush as tag
from model_animations import AnimationClip
from test_tag_rush_endings import machine
from test_tag_rush_scene import start
from test_tag_rush_camera import run


class BluePairTests(unittest.TestCase):
    def test_successful_galick_release_keeps_aim_but_cancel_and_other_pairs_keep_original(self):
        import tag_rush_safety as safety
        for variant,cancel in ((6,0),(6,1),(5,0)):
            c=machine(0);start(c);c.w(tag.CONTROL+tag.C['variant'],variant);placed={}
            for role in range(3):
                row=scene.ROWS+role*scene.STRIDE
                c.write(row+scene.R['rotation'],struct.pack('<4f',0.,.25,0.,0.))
                c.write(row+blue.END_ROTATION,struct.pack('<4f',0.,1.5,0.,0.));c.w(row+blue.END_FACING,blue.MAGIC if role<2 else 0)
            def place(m):
                placed[m.r[4]]=struct.unpack('<4f',m.read(m.r[6],16));m.r[2]=1
            c.callbacks[safety.PLACE]=place
            c.r[4]=cancel;run(c,scene.FINISH)
            for role,index in enumerate((0,2,1)):
                expected=1.5 if variant==6 and not cancel and role<2 else .25
                self.assertAlmostEqual(placed[c.actors[index]][1],expected)

    def test_compressed_ground_roots_preserve_every_sample_and_final_idle_direction(self):
        import tag_rush_galick_pair as galick
        from tag_rush_install import selected_iso
        plan=blue.build(selected_iso());motion=galick.motion(selected_iso());base,data=plan['blocks'][0]
        table=blue.TABLES+blue.TABLE_SIZE-base
        roots=struct.unpack_from('<3I',data,table+blue.T['roots'])
        maps=struct.unpack_from('<3I',data,struct.unpack_from('<I',data,table+blue.T['root_indices'])[0]-base)
        yaws=struct.unpack_from('<3f',data,struct.unpack_from('<I',data,table+blue.T['final_yaws'])[0]-base)
        for role in range(3):
            indices=struct.unpack_from('<%dH'%motion['samples'],data,maps[role]-base)
            rebuilt=b''.join(data[roots[role]-base+64*i:roots[role]-base+64*(i+1)]for i in indices)
            self.assertEqual(rebuilt,motion['roots'][role])
            final=struct.unpack('<16f',rebuilt[-64:])
            self.assertAlmostEqual(yaws[role],math.atan2(final[8],final[10])+math.pi,places=5)
        self.assertLess(blue.DATA+len(data),blue.END)

    def test_exact_forms_in_either_order_and_no_other_pair_is_selected(self):
        for lead in (122,*blue.TRUNKS):
            expected=blue.NAMES[lead!=122]
            self.assertEqual(blue.pair(lead,35),expected)
            self.assertEqual(blue.pair(35,lead),expected)
        for pair in ((0,35),(122,34),(225,122),(35,35),(True,35),(122,None)):
            self.assertIsNone(blue.pair(*pair))

    def test_native_start_keeps_exact_story_roles_for_either_initiator(self):
        # Full native START executes with adversarial volatile-register calls.
        # Pose/camera helpers are isolated here; their sample math is below.
        for lead,partner in ((122,35),*((t,v) for t in blue.TRUNKS for v in blue.VEGETA_LINE)):
            for reverse in (False,True):
                c=machine(0);roles=(partner,lead) if reverse else (lead,partner)
                for index,character in zip((0,2),roles):
                    c.w(c.models[index]+12,character);c.write(c.u(scene.ADMISSION)+character,b'\x03')
                #The fixture has valid dummy donor buffers; use them for each
                #new seven-phase descriptor without changing their admission.
                variant=5 if lead==122 else 6;name=blue.NAMES[variant-5]
                base=assets.BASE+0x7000
                c.w(tag.CONTROL+blue.TABLE_OFFSETS[variant-5],base)
                c.w(tag.CONTROL+blue.TABLE_OFFSETS[variant-5]+4,len(blue.timeline(name)))
                for i,p in enumerate(blue.timeline(name)):
                    c.write(base+64*i,struct.pack('<16I',p.source_frames,0x06D20000,0x06D21000,0x06D22000,
                        0,0,0,p.flags,0,0,0,*p.ends,60,0x06D25000))
                for entry in (blue.ANCHOR,blue.AURA_START,blue.ROOT_STEP,blue.CAMERA_STEP):
                    c.callbacks[entry]=lambda m:m.r.__setitem__(2,1)
                start(c);self.assertEqual(c.r[2],1,(lead,reverse))
                self.assertEqual(c.u(tag.CONTROL+tag.C['variant']),variant)
                self.assertEqual(c.u(scene.ROWS+scene.R['character']),lead)
                self.assertEqual(c.u(scene.ROWS+scene.STRIDE+scene.R['character']),partner)
                self.assertEqual(c.u(tag.CONTROL+tag.C['members']),7)

    def test_bank_has_bounded_native_clips_and_the_accepted_user_pose(self):
        header,payload=blue.bank()
        self.assertEqual(header['pose_sha256'],'3fd595ebf276b102780e0ebd16a23685982f4c0f24c0568d3ff3c46f49e7304f')
        clips=blue.prepared_clips();self.assertEqual(len(clips),21)
        for source,raw in clips.items():
            self.assertLessEqual(len(raw),0xC000)
            clip=AnimationClip.from_decoded(source.animation,raw)
            self.assertEqual(clip.flags,0)
            for time in (0,clip.frame_count/2,clip.frame_count):
                for pose in clip.evaluate(time).values():
                    self.assertTrue(all(math.isfinite(x)for x in pose.rotation))
                    self.assertAlmostEqual(sum(x*x for x in pose.rotation),1.,places=4)
        for pointer in header['roots']:
            matrices=np.frombuffer(payload[pointer:pointer+213*64],dtype='<f4').reshape(-1,4,4)
            self.assertTrue(np.isfinite(matrices).all())
            for m in matrices:
                np.testing.assert_allclose(m[:3,:3]@m[:3,:3].T,np.eye(3),atol=2e-6)
                self.assertAlmostEqual(np.linalg.det(m[:3,:3]),1.,places=5)
        self.assertEqual(sum(p.source_frames for p in blue.own_timeline(blue.NAMES[0])),424)

    def test_guest_uses_half_source_frames_without_running_motion_four_times_fast(self):
        from prototype import Assembler
        from test_tag_rush_scene import SceneCpu
        a=Assembler(blue.BASE);blue._sample(a,'no');a.jr();a.label('no');a.li(2,-1);a.jr()
        c=SceneCpu({'segments':[dict(address=blue.BASE,data_hex=a.finish().hex())]})
        c.w(scene.STATE,scene.SCENE_MAGIC);c.w(blue.DATA,blue.MAGIC);c.w(tag.CONTROL+tag.C['variant'],5)
        c.write(blue.TABLES,struct.pack('<9I',213,7,blue.LANE,0,0,0,0,blue.DATA+0x200,0))
        c.write(blue.DATA+0x200,struct.pack('<8I',*blue.EDGES))
        for phase,ticks in ((0,1),(0,10),(3,5),(5,28),(5,74),(6,25)):
            c.w(scene.STATE+scene.S['phase'],blue.INTRO+phase);c.w(scene.STATE+scene.S['ticks'],ticks)
            run(c,blue.BASE);self.assertEqual(c.r[2],min(212,(blue.EDGES[phase]+ticks*2)//2))
        # The shared opening never samples the authored tables.
        for phase in range(blue.INTRO):
            c.w(scene.STATE+scene.S['phase'],phase);run(c,blue.BASE);self.assertEqual(c.r[2]&0xFFFFFFFF,0xFFFFFFFF)

    def test_each_pair_delivers_one_finishing_damage_budget_at_its_own_impact(self):
        pack=dict(variants={},audio_cues={})
        # Only these schedules are selected for this independent cinematic.
        for name in damage.VARIANTS:
            if name not in blue.NAMES:
                pack['variants'][name]={'phases':[]};pack['audio_cues'][name]=[];continue
            phases=[dict(source_frames=p.source_frames,starts=p.starts,ends=p.ends,flags=p.flags,
                         **({'burst_frame':blue.burst(name)[1]}if i==blue.burst(name)[0] else {})) for i,p in enumerate(blue.timeline(name))]
            pack['variants'][name]={'phases':phases};pack['audio_cues'][name]=[() for _ in phases]
        with patch.object(damage,'VARIANTS',blue.NAMES):
            self.assertEqual(damage.schedules(pack),{name:((*blue.burst(name),10000),)for name in blue.NAMES})

    def test_native_root_and_three_axis_muzzle_survive_matrix_calls(self):
        c=machine(0);header,payload=blue.bank()
        c.write(blue.DATA,struct.pack('<4I',blue.MAGIC,2,0,0))
        roots=(blue.DATA+0x1000,blue.DATA+0x5000,blue.DATA+0x9000)
        c.write(blue.TABLES,struct.pack('<9I',213,7,blue.LANE,*roots,0,blue.DATA+0x200,blue.DATA+0xD000))
        c.write(blue.DATA+0x200,struct.pack('<8I',*blue.EDGES))
        for role,at in enumerate(roots):c.write(at,payload[header['roots'][role]:header['roots'][role]+213*64])
        gap=(1.5,0.,-2.)
        for index in range(213):c.write(blue.DATA+0xD000+16*index,struct.pack('<4f',*gap,0.))
        c.w(tag.CONTROL+tag.C['variant'],5);c.w(scene.STATE,scene.SCENE_MAGIC)
        c.w(scene.STATE+scene.S['phase'],blue.INTRO+5);c.w(scene.STATE+scene.S['ticks'],30)
        c.write(scene.STATE+scene.S['origin'],struct.pack('<4f',100.,-300.,50.,1.))
        c.write(scene.STATE+scene.S['rotation'],struct.pack('<4f',0.,.7,0.,0.))
        c.fw(scene.STATE+blue.SPATIAL_SCALE,1.)
        for role,index in enumerate((0,2,1)):
            c.w(scene.ROWS+role*scene.STRIDE+scene.R['actor'],c.actors[index])
            c.w(scene.ROWS+role*scene.STRIDE+scene.R['model'],c.models[index])
            c.w(scene.ROWS+role*scene.STRIDE+scene.R['model_id'],index)
        def matrix(address):return np.frombuffer(c.read(address,64),dtype='<f4').reshape(4,4).T
        def put(address,m):c.write(address,np.asarray(m,dtype='<f4').T.tobytes())
        c.callbacks[scene.A(0x120098)]=lambda m:put(m.r[4],np.eye(4))
        def rotate(m):
            angle=m.number(12);co,si=math.cos(angle),math.sin(angle)
            r=np.array(((co,0,si,0),(0,1,0,0),(-si,0,co,0),(0,0,0,1)))
            put(m.r[4],matrix(m.r[5])@r)
        c.callbacks[scene.A(0x120428)]=rotate
        c.callbacks[scene.A(0x1201B8)]=lambda m:put(m.r[4],matrix(m.r[5])@matrix(m.r[6]))
        for call in (0x165418,0x2500E8):c.callbacks[scene.A(call)]=lambda m:None
        c.r[4:6]=[0,scene.ROWS];run(c,blue.ROOT_STEP);self.assertEqual(c.r[2],1)
        sample=np.frombuffer(payload[header['roots'][0]+99*64:header['roots'][0]+100*64],dtype='<f4').reshape(4,4).T.astype(float)
        other=np.frombuffer(payload[header['roots'][1]+99*64:header['roots'][1]+100*64],dtype='<f4').reshape(4,4).T
        # Unit arena scale: the lane offset vanishes, the body spacing remains.
        sample[:3,3]+=np.asarray(blue.lane_offset(sample[:3,3],other[:3,3],1.))+np.asarray(gap)
        co,si=math.cos(.7),math.sin(.7)
        world=np.array(((co,0,si,100),(0,1,0,-300),(-si,0,co,50),(0,0,0,1)))@sample
        np.testing.assert_allclose(matrix(c.models[0]+2464),world,atol=3e-5)
        hands=[np.frombuffer(c.read(c.u(c.models[0]+3436+bone*4)+64,12),dtype='<f4')for bone in (31,45)]
        midpoint=np.frombuffer(c.read(c.u(c.models[0]+3436+52*4)+64,12),dtype='<f4')
        np.testing.assert_allclose(midpoint,(hands[0]+hands[1])*.5,atol=1e-5)

    def test_dash_shells_are_scoped_smaller_and_retire_without_touching_victim(self):
        c=machine(0);start(c);self.assertEqual(c.r[2],1)
        aura,trail=0x03E00000,0x03E01000
        c.w(c.r[28]-22640,aura);c.w(aura+1168,aura+0x500)
        c.w(c.r[28]-22584,trail);c.w(trail+1776,trail+0x800)
        nodes={};original={};calls=[];ordinary_calls=[]
        for role,index in enumerate((0,2)):
            node=aura+0x1000+index*0x100;body=node+64
            c.w(aura+0x500+index*4,node);c.w(node+56,body)
            for off,value in ((40,0),(44,0),(64,0),(68,0x3F800000),(76,0)):
                c.w(body+off,value);original[index,off]=value
            node=trail+0x1000+index*0x1000;body=node+64;nodes[index]=(node,body)
        def dash(m):
            index,command=m.r[4:6];calls.append((index,command))
            node,body=nodes[index]
            if command==0:
                m.w(trail+0x800+index*4,node);m.w(node+56,body)
                for k,off in enumerate(blue.DASH_SIZE_FIELDS):m.fw(body+off,4.+k)
        c.callbacks[scene.A(0x1714E8)]=dash
        c.callbacks[scene.A(0x165418)]=lambda m:ordinary_calls.append(tuple(m.r[4:6]))
        c.callbacks[scene.A(0x2500E8)]=lambda m:None
        run(c,blue.AURA_START)
        self.assertEqual(calls,[(0,0),(2,0)])
        for index,(node,body) in nodes.items():
            for k,off in enumerate(blue.DASH_SIZE_FIELDS):
                self.assertAlmostEqual(struct.unpack('<f',c.read(body+off,4))[0],(4.+k)*blue.DASH_PARTICLE_SCALE,places=5)
            ordinary=c.u(c.u(aura+0x500+index*4)+56)
            for off in (40,44,64,68,76):c.w(ordinary+off,123)
        run(c,blue.AURA_STOP)
        self.assertEqual(calls,[(0,0),(2,0),(0,2),(2,2)])
        self.assertEqual(ordinary_calls,[(0,6),(2,6),(0,5),(2,5)],
                         'ordinary aura must fade back in after the rush faded it out')
        for (index,off),value in original.items():
            body=c.u(c.u(aura+0x500+index*4)+56)
            self.assertEqual(c.u(body+off),value)
        run(c,blue.AURA_STOP)
        self.assertEqual(len(calls),4,'cleanup must be idempotent')

    def test_render_size_reduction_only_affects_the_owned_shells_while_active(self):
        c=machine(0);c.write(blue.AURA_SIZE,blue.aura_size_code())
        c.w(tag.CONTROL+tag.C['active'],1);c.w(tag.CONTROL+tag.C['variant'],5)
        c.w(scene.STATE,scene.SCENE_MAGIC)
        for role in range(2):
            c.w(scene.ROWS+role*scene.STRIDE+380,blue.MAGIC)
            c.w(scene.ROWS+role*scene.STRIDE+408,0x3F00000+role*0x1000)
        for variant,active,body,expected in ((5,1,0x3F00000,.256),(6,1,0x3F01000,.256),
                (0,1,0x3F00000,1.),(5,0,0x3F00000,1.),(5,1,0x3F02000,1.)):
            c.w(tag.CONTROL+tag.C['variant'],variant);c.w(tag.CONTROL+tag.C['active'],active)
            c.r[4]=body;c.set_number(1,3.);c.set_number(2,7.);before=c.r.copy()
            run(c,blue.AURA_SIZE)
            self.assertAlmostEqual(c.number(0),3.*expected,places=5)
            self.assertAlmostEqual(c.number(2),7.,places=5)
            self.assertEqual(c.r[4:29],before[4:29])


if __name__=='__main__':unittest.main()
