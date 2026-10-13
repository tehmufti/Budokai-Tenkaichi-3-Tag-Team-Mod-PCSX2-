"""Authored endpoint fidelity, scoped native writes and smooth acquisition."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest

import tag_rush_authored_hold as authored
import tag_rush_full_nelson_native as native
import tag_rush_scene as scene
import tag_rush_special_pair as special
import tag_rush_staging as staging
import tag_team_rush as tag
from test_tag_rush_scene import SceneCpu


class EESaturatedCpu(SceneCpu):
    """Scalar EE range behavior needed to reproduce the actual q=1e20 fault."""
    def set_number(self,register,value):
        maximum=struct.unpack('<f',struct.pack('<I',0x7F7FFFFF))[0]
        if abs(value)>maximum:value=math.copysign(maximum,value)
        elif 0.<abs(value)<2.**-126:value=math.copysign(0.,value)
        return super().set_number(register,value)


def retired_sqrt_encoding(blob):
    """Reintroduce only the former Fs/Ft mistake for the regression oracle."""
    words=list(struct.unpack('<%dI'%(len(blob)//4),blob));changed=0
    for index,word in enumerate(words):
        if word>>26==17 and (word>>21)&31==16 and word&63==4:
            fd=(word>>6)&31;ft=(word>>16)&31
            if fd==ft and fd in(2,6,7):
                words[index]=(word&~((31<<16)|(31<<11)))|(fd<<11);changed+=1
    if changed!=3:raise AssertionError('Expected the three nlerp square roots')
    return struct.pack('<%dI'%len(words),*words)


class Fixture:
    def __init__(self, template=1, phase=2, ticks=11, yaw=0.):
        self.cpu = c = EESaturatedCpu({'segments':[dict(address=p,data_hex=b.hex()) for p,b in native.pieces()]})
        self.rows=(0x1600000,0x1600200)
        self.models=(0x1800000,0x1804000)
        self.actors=(0x1900000,0x1904000)
        self.nodes={}
        self.anchor=(20.,-50.,80.)
        self.yaw=yaw
        sine,cosine=math.sin(yaw),math.cos(yaw)
        columns=((cosine,0.,-sine),(0.,1.,0.),(sine,0.,cosine))
        for role,(row,model,actor) in enumerate(zip(self.rows,self.models,self.actors)):
            c.w(row+scene.R['model'],model);c.w(row+scene.R['actor'],actor)
            c.w(model+12,0 if role==0 else authored.TEMPLATES[template]['victim_character'])
            c.write(actor+16,struct.pack('<4f',*self.anchor,1.))
            c.write(row+staging.FINAL_ROOT,struct.pack('<4f',*self.anchor,1.))
            for bone in (0,*authored.JOINTS):
                node=0x2000000+role*0x10000+bone*256
                self.nodes[role,bone]=node;c.w(model+3436+bone*4,node)
                c.write(node+144,struct.pack('<3f',0.,0.,0.))
                c.write(node+160,struct.pack('<4f',0.,0.,0.,1.))
                for column,values in enumerate(columns):
                    c.write(node+16+16*column,struct.pack('<4f',*values,0.))
            span=4.307600021362305*(authored.TEMPLATES[template]['shoulder_ratio'] if role else 1.)
            c.fw(self.nodes[role,19]+144,-span/2)
            c.fw(self.nodes[role,33]+144,span/2)
        c.callbacks[native.A(0x1DC298)]=lambda m:m.r.__setitem__(2,m.r[4]+16)
        for address in (0x1D7198,0x24E3F8,0x1D70E8,0x1DABE8):
            c.callbacks[native.A(address)]=lambda m:None
        c.w(tag.CONTROL+tag.C['variant'],special.VARIANT)
        c.w(scene.STATE+scene.S['phase'],phase);c.w(scene.STATE+scene.S['ticks'],ticks)

    def run(self):
        c=self.cpu;c.r[4:6]=self.rows;c.r[31]=0xFEED0000;c.run(native.FIT)
        return c.r[2]

    def pose(self):
        return tuple(self.cpu.read(node+144,32) for node in self.nodes.values())

    def roots(self):
        return tuple(struct.unpack('<3f',self.cpu.read(a+16,12)) for a in self.actors)


class AuthoredHoldTests(unittest.TestCase):
    def test_ee_sqrt_uses_ft_even_when_fs_contains_the_normalization_epsilon(self):
        from prototype import Assembler
        import beam_struggle as fp
        a=Assembler(native.BASE);fp.fconst(a,0,1e-10);fp.fconst(a,1,49.)
        fp.fop(a,4,2,0,1);a.jr()
        c=EESaturatedCpu({'segments':[dict(address=native.BASE,data_hex=a.finish().hex())]})
        c.r[31]=0xFEED0000;c.run(native.BASE)
        self.assertEqual(c.number(2),7.)

    def test_retired_operand_reproduces_captured_quaternion_corruption(self):
        from prototype import Assembler
        a=Assembler(native.BASE);tag.save(a);a.addiu(29,29,-0x2000);m=native.Math(a)
        first,second,gain,target,result=(m.slot()for _ in range(5))
        q=authored.TEMPLATES[1]['holder']['rotations'][authored.JOINTS.index(17)]
        for at in(first,second):
            for index,value in enumerate(q):m.constant(at+4*index,value)
        m.constant(gain,1.);m.nlerp(target,first,second,gain);m.nlerp(result,first,target,gain)
        a.li(10,0x2200000)
        for index in range(4):m.load(result+4*index);a.i(57,0,10,4*index)
        a.li(2,1);a.jump('done');a.label('no');a.move(2,0);a.label('done')
        a.addiu(29,29,0x2000);tag.restore(a,2);a.jr();m.helpers();fixed=a.finish()
        for label,code in(('fixed',fixed),('retired',retired_sqrt_encoding(fixed))):
            with self.subTest(encoding=label):
                c=EESaturatedCpu({'segments':[dict(address=native.BASE,data_hex=code.hex())]})
                c.r[31]=0xFEED0000;c.run(native.BASE);got=struct.unpack('<4f',c.read(0x2200000,16))
                self.assertEqual(c.r[2],1)
                if label=='fixed':
                    self.assertAlmostEqual(sum(x*x for x in got),1.,places=5)
                    self.assertGreater(abs(sum(x*y for x,y in zip(got,q))),1.-2e-6)
                else:
                    # Exactly the order captured in actual Goku/Raditz bones:
                    # two faulty interpolations each multiplied by 1e10.
                    self.assertGreater(abs(got[3]),.9e20);self.assertLess(abs(got[3]),1.1e20)

    def test_unit_output_guard_blocks_the_retired_finite_but_exploding_pose(self):
        f=Fixture();before,roots=f.pose(),f.roots()
        f.cpu.write(native.FIT,retired_sqrt_encoding(native.fit_code()))
        self.assertEqual(f.run(),0)
        self.assertEqual(f.pose(),before);self.assertEqual(f.roots(),roots)

    def test_frozen_receipt_and_reserved_ranges(self):
        self.assertEqual(authored.receipt()['source_sha256'],
            '0a797bc233ebeafccab8ea82c09b157f66d8f2fe902bf032e2654c4ea0ec2cb6')
        self.assertEqual(len(authored.data()),13504)
        self.assertEqual(struct.unpack_from('<4I',authored.data(),48),(33,4,3360,authored.ACQUISITION_FRAMES))
        self.assertLessEqual(native.FIT+len(native.fit_code()),authored.DATA)
        self.assertLessEqual(authored.DATA+len(authored.data()),authored.END)
        self.assertLessEqual(authored.END,native.END)

    def test_template_anchors_reproduce_authored_pose(self):
        for template in authored.TEMPLATES:
            with self.subTest(template=template['name']):
                result=authored.endpoint(template['shoulder_ratio'])
                for role in ('holder','victim'):
                    for got,want in zip(result['actors'][role]['root_translation'],template[role]['root_translation']):
                        self.assertAlmostEqual(got,want,places=12)
                    for bone,q in zip(authored.JOINTS,template[role]['rotations']):
                        got=result['actors'][role]['rotations'][bone]
                        self.assertGreater(abs(sum(a*b for a,b in zip(q,got))),1.-1e-12)

    def test_interpolation_stays_normalized_and_bounded(self):
        for ratio in (.1,.8,.83,.882,1.,1.5,1.824,4.):
            result=authored.endpoint(ratio)
            self.assertTrue(0<=result['weight']<=1)
            for role in ('holder','victim'):
                for q in result['actors'][role]['rotations'].values():
                    self.assertAlmostEqual(sum(x*x for x in q),1.,places=12)
        for value in (0.,-1.,math.nan,math.inf):
            with self.assertRaises(ValueError):authored.endpoint(value)

    def test_native_exact_endpoints_without_ik_or_bone_translation_edits(self):
        for index,template in enumerate(authored.TEMPLATES):
            with self.subTest(template=template['name']):
                f=Fixture(index);before=f.pose()
                self.assertEqual(f.run(),1)
                for role,name in enumerate(('holder','victim')):
                    for bone,q in zip(authored.JOINTS,template[name]['rotations']):
                        got=struct.unpack('<4f',f.cpu.read(f.nodes[role,bone]+160,16))
                        self.assertGreater(abs(sum(a*b for a,b in zip(q,got))),1.-2e-6)
                    for actual,origin,offset in zip(f.roots()[role],f.anchor,template[name]['root_translation']):
                        self.assertAlmostEqual(actual,origin+offset,places=4)
                for old,new in zip(before,f.pose()):self.assertEqual(old[:12],new[:12])

    def test_owned_scope_and_late_bad_pointer_leave_both_actors_untouched(self):
        for kind in ('variant','phase','last_pointer','joint_nan','zero_rotation','table_nan','table_identity'):
            with self.subTest(kind=kind):
                f=Fixture();c=f.cpu
                if kind=='variant':c.w(tag.CONTROL+tag.C['variant'],0)
                elif kind=='phase':c.w(scene.STATE+scene.S['phase'],5)
                elif kind=='last_pointer':c.w(f.models[1]+3436+47*4,0)
                elif kind=='joint_nan':c.w(f.nodes[1,47]+148,0x7FC00000)
                elif kind=='zero_rotation':c.write(f.nodes[1,47]+160,bytes(16))
                elif kind=='table_nan':c.w(authored.DATA+authored.HEADER+authored.STRIDE+authored.ROTATIONS,0x7FC00000)
                else:c.w(authored.DATA+16,0)
                before,roots=f.pose(),f.roots()
                self.assertEqual(f.run(),0)
                self.assertEqual(f.pose(),before);self.assertEqual(f.roots(),roots)

    def test_three_beat_motion_matches_native_at_keys_and_phase_seams(self):
        for template in range(3):
            previous=None
            # Every actual 30 Hz native update through the acquisition, both
            # phase seams and into the hold: no step between ticks may jump.
            import tag_rush_special_pair as special
            seams=(0,special.SEGMENTS[0][4],special.SEGMENTS[0][4]+special.SEGMENTS[1][4])
            for elapsed in range(0,seams[2]+22,2):
                phase=0 if elapsed<seams[1] else 1 if elapsed<seams[2] else 2
                prefix=seams[phase];ticks=1+(elapsed-prefix)//2
                f=Fixture(template,phase=phase,ticks=ticks)
                want=authored.motion(authored.TEMPLATES[template]['shoulder_ratio'],elapsed)
                self.assertEqual(f.run(),1)
                for role,name in enumerate(('holder','victim')):
                    for bone,q in want['actors'][name]['rotations'].items():
                        actual=struct.unpack('<4f',f.cpu.read(f.nodes[role,bone]+160,16))
                        self.assertGreater(abs(sum(a*b for a,b in zip(actual,q))),1.-2e-6,(template,elapsed,role,bone))
                    for actual,origin,offset in zip(f.roots()[role],f.anchor,want['actors'][name]['root_translation']):
                        self.assertAlmostEqual(actual,origin+offset,places=4)
                # Victim body alignment is present from the first cinematic
                # cut: it does not rise through the holder during acquisition.
                if previous is not None:
                    self.assertLess(abs(f.roots()[0][2]-previous[0][2]),3.)
                    self.assertEqual(f.roots()[1],previous[1])
                    self.assertEqual(f.roots()[0][1],previous[0][1])
                previous=f.roots()

    def test_acquisition_approaches_and_staggers_hands_before_exact_endpoint(self):
        for index,template in enumerate(authored.TEMPLATES):
            poses=[authored.motion(template['shoulder_ratio'],frame)for frame in authored.KEYFRAMES]
            holder=[p['actors']['holder']for p in poses]
            victim=[p['actors']['victim']for p in poses]
            self.assertAlmostEqual(holder[0]['root_translation'][2]-holder[-1]['root_translation'][2],5.)
            self.assertTrue(all(a['root_translation'][2]>b['root_translation'][2]for a,b in zip(holder,holder[1:])))
            self.assertTrue(all(p['root_translation']==victim[0]['root_translation']for p in victim))
            self.assertLess(abs(sum(a*b for a,b in zip(holder[0]['rotations'][19],holder[-1]['rotations'][19]))),.95)
            # The first catch bends the victim's left arm substantially sooner
            # than the right, rather than raising both arms in synchrony.
            left=abs(sum(a*b for a,b in zip(victim[1]['rotations'][19],victim[-1]['rotations'][19])))
            right=abs(sum(a*b for a,b in zip(victim[1]['rotations'][33],victim[-1]['rotations'][33])))
            self.assertGreater(left,right)
            endpoint=authored.endpoint(template['shoulder_ratio'])['actors']
            for role in('holder','victim'):
                self.assertEqual(poses[-1]['actors'][role]['root_translation'],endpoint[role]['root_translation'])
                for bone,q in endpoint[role]['rotations'].items():
                    got=poses[-1]['actors'][role]['rotations'][bone]
                    self.assertGreater(abs(sum(a*b for a,b in zip(got,q))),1.-1e-12)

    def test_motion_clock_validation_and_finite_keypose_interpolation(self):
        for ratio in(.1,.8,.83,.882,1.,1.5,1.824,4.):
            for elapsed in(-5.,0.,31.,62.,63.9,64.,118.,179.9,180.,500.):
                result=authored.motion(ratio,elapsed)
                self.assertTrue(0<=result['motion_weight']<=1)
                for role in('holder','victim'):
                    for q in result['actors'][role]['rotations'].values():
                        self.assertAlmostEqual(sum(x*x for x in q),1.,places=12)
        for elapsed in(math.nan,math.inf):
            with self.assertRaises(ValueError):authored.motion(1.,elapsed)

    def test_placements_rotate_with_cinematic_and_fresh_frame_does_not_drift(self):
        f=Fixture(yaw=math.pi/2)
        self.assertEqual(f.run(),1)
        for role,name in enumerate(('holder','victim')):
            x,y,z=authored.TEMPLATES[1][name]['root_translation']
            expected=(f.anchor[0]+z,f.anchor[1]+y,f.anchor[2]-x)
            for got,want in zip(f.roots()[role],expected):self.assertAlmostEqual(got,want,places=4)
        first=f.roots()
        # Unchanged staging marks have SETTLE=0: native actor roots retain
        # the previous fitted output. The helper must not accumulate it.
        self.assertEqual(f.run(),1);self.assertEqual(f.roots(),first)

    def test_preserves_full_guest_registers_and_fpu_state(self):
        f=Fixture();c=f.cpu
        for register in range(1,29):
            c.r[register]=((0x12340000+register)<<96)|(0x55660000+register)
        c.r[30]=(0x76543210<<96)|0x11223344
        for register in range(32):c.f[register]=0x3F000000+register*31
        c.condition=True;c.hi=0xF1234567;c.lo=0x81234567
        c.r[4:6]=f.rows;c.r[31]=0xFEED0000
        before=c.r.copy(),c.f.copy(),c.condition,c.hi,c.lo
        self.assertEqual(f.run(),1)
        for register in range(1,32):
            if register!=2:self.assertEqual(c.r[register],before[0][register],register)
        self.assertEqual(c.f,before[1]);self.assertEqual(c.condition,before[2])
        self.assertEqual((c.hi,c.lo),before[3:])


if __name__=='__main__':unittest.main()
