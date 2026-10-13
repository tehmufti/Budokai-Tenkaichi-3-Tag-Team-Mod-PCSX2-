"""Poser arm math and actual-disc fidelity of the authored native restraint."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import copy
import math
from pathlib import Path
import struct
import unittest
from types import SimpleNamespace

import tag_rush_full_nelson as ik


def matrix(point=(0.,0.,0.),q=(0.,0.,0.,1.)):
    columns=[ik.rotate(q,axis) for axis in ((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))]
    return tuple(tuple(columns[j][i] for j in range(3))+(float(point[i]),) for i in range(3))+((0.,0.,0.,1.),)


def simple_arm(offset=.5):
    return {bone:matrix(point) for bone,point in ((18,(0,0,0)),(19,(0,0,0)),
            (20,(2,0,0)),(21,(4,0,0)),(31,(4+offset,0,0)))}


def solve(world,**kwargs):
    return ik.solve_arm(world,shoulder=19,elbow=20,wrist=21,palm=31,parent=18,**kwargs)


class ArmMathTests(unittest.TestCase):
    def assertPoint(self,actual,expected,tolerance=1e-6):
        self.assertLessEqual(ik.length(ik.sub(actual,expected)),tolerance,(actual,expected))

    def test_contact_preserves_lengths_marker_offset_and_elbow_pole(self):
        world=simple_arm();before=copy.deepcopy(world)
        result=solve(world,target_palm=(2.8,2.,0.),elbow_pole=(0.,0.,3.))
        self.assertPoint(result.palm,(2.8,2.,0.))
        self.assertAlmostEqual(ik.length(ik.sub(result.elbow,result.shoulder)),2.)
        self.assertAlmostEqual(ik.length(ik.sub(result.wrist,result.elbow)),2.)
        self.assertAlmostEqual(ik.length(ik.sub(result.palm,result.wrist)),.5)
        self.assertGreater(result.elbow[2],0.)
        self.assertEqual(world,before)

    def test_native_inward_wrist_target_and_parent_rotation_are_equivariant(self):
        world=simple_arm();target=(2.5,2.,.5);wrist=(2.8,2.4,.5);pole=(-1.,0.,3.)
        a=solve(world,target_palm=target,target_wrist=wrist,elbow_pole=pole)
        self.assertPoint(a.palm,target)
        q=ik.qnorm((.2,.5,.3,.7));shift=(14.,-8.,3.)
        move=lambda p:ik.add(ik.rotate(q,p),shift)
        transformed={bone:matrix(move(ik.position(m)),ik.qmul(q,ik.rotation(m))) for bone,m in world.items()}
        b=solve(transformed,target_palm=move(target),target_wrist=move(wrist),elbow_pole=move(pole))
        for name in ('shoulder','elbow','wrist','palm'):self.assertPoint(getattr(b,name),move(getattr(a,name)))

    def test_unreachable_and_degenerate_poles_remain_finite_without_stretching(self):
        for point in ((30.,0.,0.),(0.,0.,0.),(-4.,0.,0.)):
            with self.subTest(point=point):
                result=solve(simple_arm(),target_palm=point,target_wrist=point,elbow_pole=(10.,0.,0.))
                self.assertAlmostEqual(ik.length(ik.sub(result.elbow,result.shoulder)),2.)
                self.assertAlmostEqual(ik.length(ik.sub(result.wrist,result.elbow)),2.)
                for q in result.local_rotations.values():
                    self.assertTrue(all(math.isfinite(x) for x in q));self.assertAlmostEqual(ik.dot(q,q),1.)
        self.assertTrue(solve(simple_arm(),target_palm=(30.,0.,0.),elbow_pole=(0.,2.,0.)).clamped)

    def test_zero_palm_offset_is_valid_but_degenerate_arms_and_nonfinite_inputs_are_not(self):
        result=solve(simple_arm(0.),target_palm=(2.,2.,0.),elbow_pole=(0.,0.,3.))
        self.assertPoint(result.palm,(2.,2.,0.))
        world=simple_arm();world[20]=world[19]
        with self.assertRaises(ValueError):solve(world,target_palm=(1,1,1),elbow_pole=(0,0,3))
        with self.assertRaises(ValueError):solve(simple_arm(),target_palm=(math.nan,0,0),elbow_pole=(0,0,3))
        with self.assertRaises(ValueError):solve(simple_arm(),target_palm=(1,1,1),elbow_pole=(0,0,3),gain=2)

    def test_acquisition_starts_at_original_pose_and_moves_continuously(self):
        world=simple_arm();previous=None
        for i in range(101):
            gain=i/100.;result=solve(world,target_palm=(2.,2.,0.),elbow_pole=(0.,0.,3.),gain=gain)
            if i==0:self.assertPoint(result.palm,ik.position(world[31]))
            if previous is not None:self.assertLess(ik.length(ik.sub(result.palm,previous)),.15)
            previous=result.palm
        self.assertPoint(result.palm,(2.,2.,0.))


def discs():
    from native_map import SERIAL
    names={'SLUS-21678':('Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso',),
           'SLUS-21978':('SLUS_219.78.DBZBT4B14REV2ENG.iso','SLUS_219.78.DBZBT4B14REV2.iso')}.get(SERIAL,())
    games=Path(__file__).resolve().parents[2]/'games'
    return [games/name for name in names if (games/name).is_file()]


def actual_pose(iso,character,role,phase,frame,cache):
    """Same private crop + native bind-delta translation retarget as the scene."""
    import model_viewer as viewer
    import tag_rush_assets as assets
    import tag_rush_special_pair as special
    from model_animations import AnimationClip,BoneTransform
    if 'donor' not in cache:
        cache['donor']=assets.read_skeleton(iso,special.DONOR)
        cache['sources']=special.read_sources(iso)
    donor=cache['donor'];sources=cache['sources'];db={r['bone']:r['translation'] for r in donor['rows']}
    if character not in cache:
        recipient=assets.read_skeleton(iso,character)
        # Geometry/texture parsing is unrelated to pose fitting. Read the real
        # native hierarchy directly, including imported meshes the previewer
        # cannot texture yet (BT4 DBS Broly currently has duplicate bindings).
        unique={row['bone']:row for row in recipient['rows']}
        model=SimpleNamespace(character=character,bones=tuple(
            SimpleNamespace(native_id=key,parent_id=row['parent'],bind_translation=row['translation'])
            for key,row in unique.items()))
        cache[character]=(model,recipient)
    model,recipient=cache[character];tb={r['bone']:r['translation'] for r in recipient['rows']}
    lead,victim,start,end,frames=special.SEGMENTS[phase]
    shift=ik.sub(sources[356].evaluate(24)[2].translation,db[2]) if role==0 else None
    raw=special._crop(sources[lead if role==0 else victim],start,end,frames,shift,role=role,phase=phase)
    pose={}
    for bone,t in AnimationClip.from_decoded(0,raw).evaluate(frame).items():
        translation=t.translation
        if translation is not None and bone in db and bone in tb:
            delta=list(ik.sub(translation,db[bone]));delta[1]*=recipient['height']/donor['height']
            translation=ik.add(delta,tb[bone])
        pose[bone]=BoneTransform(translation,t.rotation)
    return model,pose,viewer.pose_matrices(model.bones,pose)


def native_fit(holder_model,holder_pose,holder,victim_model,victim_pose,victim,*,phase=3,ticks=1,
               before_run=None,recompose=False):
    """Execute emitted guest arithmetic against actual FK data, no emulator."""
    import tag_rush_full_nelson_native as native
    import tag_rush_scene as scene
    import tag_rush_special_pair as special
    import tag_team_rush as tag
    from test_tag_rush_scene import SceneCpu
    c=SceneCpu({'segments':[dict(address=a,data_hex=b.hex()) for a,b in native.pieces()]})
    rows=(scene.ROWS,scene.ROWS+2*scene.STRIDE)
    c.w(scene.STATE+scene.S['phase'],phase);c.w(scene.STATE+scene.S['ticks'],ticks)
    c.w(tag.CONTROL+tag.C['variant'],special.VARIANT)
    original={};models=(holder_model,victim_model);poses=(holder_pose,victim_pose)
    for index,(model,pose,world,row) in enumerate(((holder_model,holder_pose,holder,rows[0]),
                                                (victim_model,victim_pose,victim,rows[1]))):
        address=0x2100000+index*0x10000;actor=0x2200000+index*0x10000
        c.w(row+scene.R['model'],address);c.w(row+scene.R['actor'],actor);c.w(address+12,0 if index==0 else model.character)
        c.write(actor+16,bytes(16))
        for bone in model.bones:
            at=0x2300000+index*0x10000+bone.native_id*0x100
            c.w(address+3436+bone.native_id*4,at)
            c.write(at+16,struct.pack('<16f',*(float(world[bone.native_id][j][i]) for i in range(4) for j in range(4))))
            transform=pose.get(bone.native_id)
            xyz=transform.translation if transform and transform.translation is not None else bone.bind_translation
            q=transform.rotation if transform else (0,0,0,1)
            c.write(at+144,struct.pack('<4f',*xyz,0.));c.write(at+160,struct.pack('<4f',*q))
            original[index,bone.native_id]=c.read(at+144,32)
    c.native_calls=[];c.recomposed={}
    c.callbacks[scene.A(0x1DC298)]=lambda m:m.r.__setitem__(2,m.r[4]+16)
    def compose(m):
        import model_viewer as viewer
        from model_animations import BoneTransform
        index=(m.r[4]-0x2100000)//0x10000
        pose={}
        for bone in models[index].bones:
            at=m.u(m.r[4]+3436+bone.native_id*4)
            pose[bone.native_id]=BoneTransform(struct.unpack('<3f',m.read(at+144,12)),
                                               struct.unpack('<4f',m.read(at+160,16)))
        world=viewer.pose_matrices(models[index].bones,pose)
        shift=struct.unpack('<3f',m.read(0x2200000+index*0x10000+16,12))
        for bone,matrix in world.items():
            matrix[:3,3]+=shift
        c.recomposed[index]=world
    for address in (0x1D7198,0x24E3F8,0x1D70E8,0x1DABE8):
        def callback(m,address=address):
            c.native_calls.append((address,m.r[4],m.r[5]))
            if recompose and address==0x24E3F8:compose(m)
        c.callbacks[scene.A(address)]=callback
    # Nonzero high lanes reveal accidental scalar-only register restoration.
    for register in range(1,29):c.r[register]=((0x12340000+register)<<96)|(0x55660000+register)
    c.r[30]=(0x76543210<<96)|0x11223344
    for register in range(32):c.f[register]=0x3F000000+register*31
    c.condition=True;c.hi=0xF1234567;c.lo=0x81234567
    c.r[4:6]=rows;c.r[31]=0xFEED0000
    if before_run:before_run(c)
    c.before_registers=c.r.copy();c.before_fpu=c.f.copy();c.before_hilo=(c.hi,c.lo)
    c.before_condition=c.condition
    # Stack and code are not actors. Everything else is an input object that
    # rejection must leave byte-for-byte intact, including invalid pointers.
    c.input_before={p:v for p,v in c.memory.items() if 0x2100000<=p<0x2400000}
    c.nonstack_writes=[];write=c.write;stack=c.r[29]
    def tracked_write(address,data):
        if not stack-0x2400<=address<stack:c.nonstack_writes.append((address,len(data)))
        write(address,data)
    c.write=tracked_write
    c.run(native.FIT)
    result={}
    for bone in (19,20,21,33,34,35):
        at=0x2300000+bone*0x100;result[bone]=struct.unpack('<4f',c.read(at+160,16))
    return c,result,original


def authored_reference(holder_model,holder_pose,holder,victim_model,victim_pose,victim,*,phase=2,frame=20.,anchor=(0.,0.,0.)):
    """Independent FK from the approved endpoints and native lower-body base.

    This performs no fitting, palm targeting, collision correction or geometry
    optimization. The expected actor placements are the authored pair offsets.
    """
    import numpy as np
    import tag_rush_authored_hold as authored
    import tag_rush_special_pair as special
    import model_viewer as viewer
    from model_animations import BoneTransform
    def complete(model,pose):
        return {b.native_id:BoneTransform(
            tuple(pose[b.native_id].translation) if b.native_id in pose and pose[b.native_id].translation is not None else tuple(b.bind_translation),
            tuple(pose[b.native_id].rotation) if b.native_id in pose else (0.,0.,0.,1.))for b in model.bones}
    poses=tuple(complete(model,pose)for model,pose in ((holder_model,holder_pose),(victim_model,victim_pose)))
    spans=tuple(abs(p[33].translation[0]-p[19].translation[0])for p in poses)
    elapsed=sum(row[4]for row in special.SEGMENTS[:phase])+frame
    selected=authored.motion(spans[1]/spans[0],elapsed)
    basis=np.asarray(holder[0],float)[:3,:3]
    outputs=[]
    for role,model,original in zip(('holder','victim'),(holder_model,victim_model),poses):
        expected=dict(original)
        for bone,q in selected['actors'][role]['rotations'].items():
            old=original[bone];expected[bone]=BoneTransform(old.translation,q)
        root=np.asarray(anchor)+basis@np.asarray(selected['actors'][role]['root_translation'])
        world=viewer.pose_matrices(model.bones,expected)
        for matrix in world.values():matrix[:3,3]+=root
        outputs.append((expected,tuple(root),world))
    return selected,outputs


class ActualRigTests(unittest.TestCase):
    def assertAbi(self,c):
        for register in range(1,32):
            if register!=2:self.assertEqual(c.r[register],c.before_registers[register],register)
        self.assertEqual(c.f,c.before_fpu)
        self.assertEqual((c.hi,c.lo),c.before_hilo)
        self.assertEqual(c.condition,c.before_condition)

    def rigs(self,iso,target=27,phase=2,frame=20,cache=None):
        cache={}if cache is None else cache
        return actual_pose(iso,0,0,phase,frame,cache),actual_pose(iso,target,2,phase,frame,cache)

    def test_authored_acquisition_and_held_endpoints_on_real_body_types(self):
        import tag_rush_authored_hold as authored
        import tag_team_rush as tag
        from native_map import SERIAL
        paths=discs()
        if not paths:self.skipTest('User-owned game disc unavailable')
        # Classic Legendary Broly133 moves to190 in BT4. The DBS body133 also
        # gets interpolation coverage without requiring its texture binding.
        targets=(25,27,133)if SERIAL=='SLUS-21678'else(25,27,133,190)
        for iso in paths:
            cache={}
            for target in targets:
                for phase,frame in ((0,0),(0,8),(0,14),(0,22),(1,0),(1,16),(2,20),(4,70)):
                    ticks=1+frame*tag.ACTOR_HZ/60
                    if ticks!=int(ticks):continue  # Only representable native update clocks.
                    with self.subTest(iso=iso.name,target=target,phase=phase,frame=frame):
                        g,v=self.rigs(iso,target,phase,frame,cache)
                        receipt,expected=authored_reference(*g,*v,phase=phase,frame=frame)
                        c,_,original=native_fit(*g,*v,phase=phase,ticks=int(ticks),recompose=True)
                        self.assertEqual(c.r[2],1);self.assertAbi(c)
                        self.assertEqual(receipt['source_sha256'],authored.SOURCE_SHA256)
                        for role,(pose,root,world)in enumerate(expected):
                            actor=0x2200000+role*0x10000
                            actual_root=struct.unpack('<3f',c.read(actor+16,12))
                            self.assertLess(ik.length(ik.sub(actual_root,root)),1e-4)
                            for bone in (g[0]if role==0 else v[0]).bones:
                                key=bone.native_id;at=0x2300000+role*0x10000+key*0x100
                                self.assertEqual(c.read(at+144,16),original[role,key][:16])
                                q=struct.unpack('<4f',c.read(at+160,16))
                                self.assertGreater(abs(ik.dot(q,pose[key].rotation)),1.-2e-5,(role,key))
                                if key not in authored.JOINTS:self.assertEqual(c.read(at+160,16),original[role,key][16:])
                                for i in range(4):
                                    for j in range(4):self.assertAlmostEqual(float(c.recomposed[role][key][i,j]),float(world[key][i,j]),places=3)

    def test_actor_offsets_are_stable_when_hold_records_have_no_settle_reset(self):
        import tag_rush_staging as staging
        paths=discs()
        if not paths:self.skipTest('User-owned game disc unavailable')
        g,v=self.rigs(paths[0]);anchor=(35.,-80.,72.)
        def configure(c):
            c.write(0x2200000+16,struct.pack('<4f',-100.,5.,-200.,1.))
            c.write(0x2210000+16,struct.pack('<4f',-300.,10.,-400.,1.))
            c.write(__import__('tag_rush_scene').ROWS+staging.FINAL_ROOT,struct.pack('<4f',*anchor,1.))
        c,_,_=native_fit(*g,*v,phase=2,ticks=11,before_run=configure)
        self.assertEqual(c.r[2],1)
        roots=tuple(c.read(0x2200000+role*0x10000+16,12)for role in(0,1))
        import tag_rush_full_nelson_native as native
        import tag_rush_scene as scene
        c.r[4:6]=(scene.ROWS,scene.ROWS+2*scene.STRIDE);c.r[31]=0xFEED0000;c.run(native.FIT)
        self.assertEqual(c.r[2],1)
        self.assertEqual(tuple(c.read(0x2200000+role*0x10000+16,12)for role in(0,1)),roots)

    def test_guest_rejects_owned_scope_incomplete_rigs_and_bad_endpoint_before_publishing(self):
        paths=discs()
        if not paths:self.skipTest('User-owned game disc unavailable')
        g,v=self.rigs(paths[0],77)
        import tag_rush_scene as scene
        import tag_rush_staging as staging
        import tag_team_rush as tag
        import tag_rush_authored_hold as authored
        bone=lambda index,key:0x2300000+index*0x10000+key*0x100
        cases={
            'non-special variant':lambda c:c.w(tag.CONTROL+tag.C['variant'],0),
            'unowned phase':lambda c:c.w(scene.STATE+scene.S['phase'],5),
            'null model':lambda c:c.w(scene.ROWS+scene.R['model'],0),
            'null victim actor':lambda c:c.w(scene.ROWS+2*scene.STRIDE+scene.R['actor'],0),
            'NaN actor position':lambda c:c.fw(0x2210000+16,math.nan),
            'NaN immutable anchor':lambda c:c.fw(scene.ROWS+staging.FINAL_ROOT,math.nan),
            'null bone':lambda c:c.w(0x2100000+3436+19*4,0),
            'unaligned bone':lambda c:c.w(0x2100000+3436+19*4,bone(0,19)+1),
            'bone past RAM':lambda c:c.w(0x2110000+3436+46*4,0x7FFFFF0),
            'NaN root orientation matrix':lambda c:c.fw(bone(0,0)+16,math.nan),
            'NaN local translation':lambda c:c.fw(bone(1,47)+148,math.nan),
            'NaN local quaternion':lambda c:c.fw(bone(0,19)+160,math.nan),
            'infinite local quaternion':lambda c:c.fw(bone(0,19)+172,math.inf),
            'zero local quaternion':lambda c:c.write(bone(0,19)+160,bytes(16)),
            'null finger bone':lambda c:c.w(0x2100000+3436+23*4,0),
            'nonfinite finger rotation':lambda c:c.fw(bone(0,30)+168,math.nan),
            'zero finger rotation':lambda c:c.write(bone(0,23)+160,bytes(16)),
            'nonfinite head rotation':lambda c:c.fw(bone(0,47)+172,math.inf),
            'zero shoulder span':lambda c:c.write(bone(1,33)+144,c.read(bone(1,19)+144,4)),
            'wrong holder':lambda c:c.w(0x2100000+12,25),
            'wrong authored source':lambda c:c.w(authored.DATA+16,0),
            'NaN selected endpoint':lambda c:c.w(authored.DATA+authored.HEADER+authored.STRIDE+authored.ROTATIONS,0x7FC00000),
        }
        for label,change in cases.items():
            with self.subTest(label=label):
                c,_,_=native_fit(*g,*v,before_run=change)
                self.assertEqual(c.r[2],0)
                self.assertEqual(c.native_calls,[])
                self.assertEqual(c.nonstack_writes,[])
                self.assertEqual({p:v for p,v in c.memory.items()if 0x2100000<=p<0x2400000},c.input_before)
                self.assertAbi(c)

    def test_unreviewed_body_dimensions_use_bounded_template_interpolation(self):
        paths=discs()
        if not paths:self.skipTest('User-owned game disc unavailable')
        cache={}
        for target in(77,87,156):
            with self.subTest(target=target):
                g,v=self.rigs(paths[0],target,2,20,cache)
                receipt,expected=authored_reference(*g,*v)
                c,_,_=native_fit(*g,*v,phase=2,ticks=11,recompose=True)
                self.assertEqual(c.r[2],1);self.assertAbi(c)
                self.assertTrue(0.<=receipt['weight']<=1.)
                for role,(pose,root,world)in enumerate(expected):
                    for key,q in pose.items():
                        actual=struct.unpack('<4f',c.read(0x2300000+role*0x10000+key*256+160,16))
                        self.assertGreater(abs(ik.dot(actual,q.rotation)),1-2e-5)


class PoserRigMathTests(unittest.TestCase):
    def test_actual_local_arm_ik_recomposes_without_stretching(self):
        import model_viewer as viewer
        from model_animations import BoneTransform
        paths=discs()
        if not paths:self.skipTest('User-owned game disc unavailable')
        cache={}
        for target in(25,27,87):
            with self.subTest(target=target):
                gm,gp,gw=actual_pose(paths[0],0,0,2,20,cache)
                vm,vp,vw=actual_pose(paths[0],target,2,2,20,cache)
                fitted=ik.fit_pair(gw,vw,elapsed=50)
                adjusted=dict(gp)
                for arm in fitted.arms:
                    for bone,q in arm.local_rotations.items():
                        old=gp.get(bone);adjusted[bone]=BoneTransform(old.translation if old else None,q)
                world=viewer.pose_matrices(gm.bones,adjusted)
                for arm,chain in zip(fitted.arms,ik.ARMS):
                    _,shoulder,elbow,wrist,palm=chain
                    for key,want in((shoulder,arm.shoulder),(elbow,arm.elbow),(wrist,arm.wrist),(palm,arm.palm)):
                        self.assertLess(ik.length(ik.sub(ik.position(world[key]),want)),3e-5)
                    self.assertAlmostEqual(ik.length(ik.sub(arm.elbow,arm.shoulder)),arm.upper_length,places=5)
                    self.assertAlmostEqual(ik.length(ik.sub(arm.wrist,arm.elbow)),arm.forearm_length,places=5)


if __name__=='__main__':unittest.main()
