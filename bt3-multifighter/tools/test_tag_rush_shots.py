"""Native camera resource, authored cuts, regional clocks and scoped guest calls."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import hashlib
import math
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import tag_rush_shots as shots
import tag_rush_assets as assets
import tag_rush_camera as camera
from native_map import A
from test_tag_rush_camera import cpu,run,RENDERER,ORDINARY,AUTHORED,CameraCpu


def raw_track():
    raw=bytearray(80+6*16+6*3*32)
    struct.pack_into('<4s3I2f3I',raw,0,b'CMAn',6,80,6,0.,4.,48,len(raw),0)
    for channel in range(6):
        start=176+96*channel;struct.pack_into('<4I',raw,80+16*channel,channel,start,3,0)
        for j,(flag,frame,value) in enumerate(((0x22,0.,0.),(0x12,2.,10.),(0x22,4.,30.))):
            struct.pack_into('<I2f',raw,start+32*j,flag,frame,value if channel<3 else value/10)
    return raw


class CameraSourceTests(unittest.TestCase):
    def test_linear_keys_and_exact_hold_cut_follow_native_evaluator(self):
        t=shots.parse_track(raw_track())
        self.assertEqual(t.sample(1)[:3],(5.,)*3)
        self.assertEqual(t.sample(2)[:3],(10.,)*3)
        self.assertEqual(t.sample(3.999)[:3],(10.,)*3)
        self.assertEqual(t.sample(4)[:3],(30.,)*3)
        for frame in (-1,5,float('nan')):
            with self.assertRaises(shots.CameraFormatError):t.sample(frame)

    def test_invalid_offsets_keys_and_nonfinite_values_are_rejected(self):
        for offset,value in ((8,4),(12,5),(28,32),(32,1),(84,0xFFFFFFF0),(88,100000),
                             (176,0),(180,0x7FC00000),(184,0x7F800000),(212,0)):
            raw=raw_track();struct.pack_into('<I',raw,offset,value)
            with self.assertRaises(shots.CameraFormatError,msg=(offset,value)):shots.parse_track(raw)

    def test_sample_clock_keeps_native_phase_gaps_and_pal_fractional_frames(self):
        seen=[]
        class RecordingTrack:
            def sample(self,frame):seen.append(frame);return (frame,0.,0.,0.,0.,0.)
        for hz in (25,30):
            seen.clear()
            with patch.object(shots,'read_track',return_value=RecordingTrack()):
                data,info=shots.build_samples('unused.iso',assets.BASE,hz)
            cursor=0
            for row,start,frames in zip(info['phases'],shots.PHASE_STARTS,shots.PHASE_FRAMES):
                count=math.ceil(frames*hz/60)
                self.assertEqual(row['count'],count)
                self.assertEqual(seen[cursor],shots.f32(start+shots.f32(60/hz)))
                self.assertEqual(seen[cursor+count-1],start+frames)
                self.assertEqual(struct.unpack_from('<f',data,row['address']-assets.BASE)[0],seen[cursor])
                cursor+=count
            self.assertEqual(cursor,len(seen));self.assertEqual(len(data),80+cursor*32)

    def test_local_discs_have_the_reviewed_camera_and_safe_stage_envelope(self):
        try:import bt4_resources
        except ImportError:names=['Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso']
        else:names=['SLUS_219.78.DBZBT4B14REV2ENG.iso','SLUS_219.78.DBZBT4B14REV2.iso']
        from prototype import ROOT
        paths=[ROOT.parent/'games'/name for name in names]
        if not all(p.exists() for p in paths):self.skipTest('Local disc resources unavailable')
        for iso in paths:
            track=shots.read_track(iso);self.assertEqual(track.end,701)
            self.assertEqual(tuple(len(keys) for _,keys in track.channels),(75,)*6)
            for before,after in zip((68,168,318,438),shots.PHASE_STARTS[1:]):
                self.assertEqual(track.sample(before+.5),track.sample(before))
                self.assertNotEqual(track.sample(before),track.sample(after))
            data,info=shots.build_samples(iso,assets.BASE,30)
            self.assertEqual(info['source_sha256'],shots.SOURCE_SHA256)
            self.assertLess(info['max_horizontal'],80)
            for phase,row in enumerate(info['phases']):
                for tick in range(row['count']):
                    y=struct.unpack_from('<f',data,row['address']-assets.BASE+32*tick+4)[0]
                    self.assertLessEqual(-y+(160 if phase<4 else 0),220)


MODEL,SCALES,TABLE,SAMPLES=0x02600000,0x02602000,assets.BASE+0x100,assets.BASE+0x200
PARAMS,DONOR,DONOR_PARAMS=0x02603000,0x02604000,0x02605000
DESCRIPTOR,DONORS=assets.BASE+0x600,assets.BASE+0x700
PARTNER,PARTNER_PARAMS,PARTNER_DONOR,PARTNER_DONOR_PARAMS=0x02606000,0x02608000,0x02609000,0x0260A000


def guest():
    class ShotCpu(CameraCpu):
        def extra_instruction(self,ins,pc):
            if ins>>26==17 and (ins>>21)&31==16 and ins&63==4:
                self.set_number((ins>>6)&31,math.sqrt(self.number((ins>>11)&31)));return
            return super().extra_instruction(ins,pc)
    c=cpu();c.write(shots.UPDATE,shots.update_code());c.r[4:10]=[2,2,MODEL,SCALES,DESCRIPTOR,PARTNER]
    c.__class__=ShotCpu
    c.w(camera.CONTROL+shots.TABLE_OFFSET,TABLE);c.w(camera.CONTROL+shots.MAGIC_OFFSET,shots.MAGIC)
    c.write(SCALES,struct.pack('<2f',1.,1.))
    c.w(MODEL+2332,PARAMS);c.w(DONOR+2332,DONOR_PARAMS)
    c.fw(PARAMS+4,.9);c.fw(DONOR_PARAMS+4,.9)
    c.w(DESCRIPTOR+60,DONORS);c.w(DESCRIPTOR+28,assets.BEAM_LEAD|assets.BEAM_PARTNER|assets.FINISHER)
    c.write(DONORS,struct.pack('<3I',DONOR,PARTNER_DONOR,DONOR))
    c.w(PARTNER+2332,PARTNER_PARAMS);c.w(PARTNER_DONOR+2332,PARTNER_DONOR_PARAMS)
    c.fw(PARTNER_PARAMS+4,.83);c.fw(PARTNER_DONOR_PARAMS+4,.83)
    c.write(MODEL+2464,struct.pack('<16f',1,0,0,0,0,1,0,0,0,0,1,0,100,-200,300,1))
    c.write(PARTNER+2464,c.read(MODEL+2464,64))
    for phase in range(5):c.write(TABLE+phase*16,struct.pack('<4I',SAMPLES,3,0,68))
    for frame in range(3):c.write(SAMPLES+frame*32,struct.pack('<8f',frame+1,-5,8,1,.1,.2,.3,1))
    c.events=[]
    identity=struct.pack('<16f',1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1)
    def cb(address,fn):
        def call(m):
            m.events.append((address,tuple(m.r[4:8])));fn(m)
            for r in (*range(8,16),24,25):m.r[r]=0xBADD0000+r
            for r in range(20):m.set_number(r,3000+r)
        c.callbacks[A(address)]=call
    cb(0x120098,lambda m:m.write(m.r[4],identity))
    for addr in (0x120398,0x120428,0x120308):cb(addr,lambda m:None)
    def multiply(m):
        # Intermediate rotations are checked by call order. Only the final
        # root composition translates the posed eye in this neutral basis.
        if m.r[5]==m.r[29]+0xC0:
            basis=struct.unpack('<16f',m.read(m.r[5],64));m.copied_basis=basis
            local=struct.unpack('<4f',m.read(m.r[6]+48,16))
            for col in range(3):
                m.fw(m.r[4]+48+4*col,sum(local[row]*basis[row*4+col] for row in range(3))+basis[12+col])
    cb(0x1201B8,multiply)
    cb(0x1202A0,lambda m:m.write(m.r[4],m.read(m.r[5],64)))
    cb(0x120230,lambda m:m.write(m.r[4],m.read(m.r[5],64)))
    cb(0x121408,lambda m:None)
    def project(m):
        m.w(m.r[28]-22176,camera.CAMERA);m.w(RENDERER+0xC40,camera.CAMERA)
    cb(0x23E598,project)
    cb(0x23E6A0,lambda m:None)
    return c


class CameraGuestTests(unittest.TestCase):
    def test_partner_only_beam_ignores_recovered_melee_lead_root(self):
        c=guest();c.r[4]=4;c.w(DESCRIPTOR+28,assets.BEAM_PARTNER|assets.FINISHER)
        c.fw(PARAMS+4,1.05);c.fw(MODEL+2516,-350)
        run(c,shots.UPDATE);self.assertEqual(c.r[2],1)
        self.assertEqual(struct.unpack('<4f',c.read(camera.CAMERA+720,16)),(102.,-205.,308.,1.))

    def test_partner_owner_is_limited_to_the_partner_only_finishing_phase(self):
        for phase,flags in ((2,assets.BEAM_PARTNER),(4,assets.BEAM_LEAD),
                            (4,assets.BEAM_LEAD|assets.BEAM_PARTNER),(4,assets.FINISHER)):
            c=guest();c.r[4]=phase;c.w(DESCRIPTOR+28,flags);c.fw(PARTNER+2516,-350)
            run(c,shots.UPDATE);self.assertEqual(c.r[2],1)
            self.assertEqual(c.fr(camera.CAMERA+724),-205.,(phase,flags))

    def test_taller_victim_cannot_lift_a_lead_authored_beam_closeup(self):
        c=guest();c.write(SCALES,struct.pack('<2f',1.,1.1111111640930176))
        c.write(SAMPLES+32,struct.pack('<8f',14.871516227722168,-130.083984375,4.43240213394165,1.,-.1150613,-1.1292883,0.,1.))
        run(c,shots.UPDATE);self.assertEqual(c.r[2],1)
        self.assertAlmostEqual(c.fr(camera.CAMERA+724),-330.083984375,places=4)

    def test_camera_height_tracks_lead_retargeting_not_maximum_cast_clearance(self):
        c=guest();c.write(SCALES,struct.pack('<2f',4.,8.))
        c.fw(PARAMS+4,1.8)
        run(c,shots.UPDATE);self.assertEqual(c.r[2],1)
        self.assertEqual(struct.unpack('<4f',c.read(camera.CAMERA+720,16)),(102.,-210.,308.,1.))

    def test_scaled_rotated_root_is_private_and_camera_scale_is_applied_once(self):
        c=guest();root=(0.,0.,-2.,0.,0.,2.,0.,0.,2.,0.,0.,0.,100.,-200.,300.,1.)
        c.write(MODEL+2464,struct.pack('<16f',*root));c.write(SCALES,struct.pack('<2f',2,2))
        run(c,shots.UPDATE);self.assertEqual(c.r[2],1)
        self.assertEqual(struct.unpack('<4f',c.read(camera.CAMERA+720,16)),(116.,-210.,296.,1.))
        self.assertEqual(c.read(MODEL+2464,64),struct.pack('<16f',*root))
        self.assertEqual(c.copied_basis,(0.,0.,-1.,0.,0.,1.,0.,0.,1.,0.,0.,0.,100.,-200.,300.,1.))

    def test_native_matrix_order_eye_and_render_ownership_are_preserved(self):
        c=guest();before=c.r.copy();run(c,shots.UPDATE)
        self.assertEqual(c.r[2],1);self.assertEqual(c.r[4:31],before[4:31])
        self.assertEqual([p for p,_ in c.events],[0x120098,0x120098,0x120398,0x1201B8,
            0x120098,0x120428,0x1201B8,0x120098,0x120308,0x1201B8,0x1201B8,
            0x1202A0,0x121408,0x120230,0x23E598,0x23E6A0])
        self.assertEqual(struct.unpack('<4f',c.read(camera.CAMERA+720,16)),(102.,-205.,308.,1.))
        self.assertEqual((c.u(c.r[28]-22180),c.u(c.r[28]-22176),c.u(RENDERER+0xC40)),
            (AUTHORED,ORDINARY,ORDINARY+16))

    def test_end_clamps_but_bad_receipts_and_wrapped_pointers_make_no_native_calls(self):
        c=guest();c.r[5]=1000;run(c,shots.UPDATE)
        self.assertEqual(c.r[2],1);self.assertEqual(c.fr(camera.CAMERA+720),103.)
        for at,value in ((camera.CONTROL+16,0),(camera.CONTROL+4,0),
                         (camera.CONTROL+shots.MAGIC_OFFSET,0),
                         (camera.CONTROL+shots.TABLE_OFFSET,assets.END-16),
                         (TABLE+32,0xFFFFFFE0),(TABLE+36,0),(TABLE+36,10000),
                         (SAMPLES+32,0x7FC00000),(SCALES,0),
                         (MODEL+2332,0),(DONOR+2332,0),(PARAMS+4,0),
                         (DONOR_PARAMS+4,0),(PARAMS+4,0x7F800000)):
            c=guest();c.w(at,value);before=c.read(camera.CAMERA,832);run(c,shots.UPDATE)
            self.assertEqual(c.r[2],0,(hex(at),value));self.assertFalse(c.events)
            self.assertEqual(c.read(camera.CAMERA,832),before)


if __name__=='__main__':unittest.main()
