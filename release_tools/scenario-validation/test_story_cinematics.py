"""Cinematic handoff, held-world isolation and restoring native render context."""
import struct
import unittest
from unittest.mock import patch
from native_map import A
from test_story_missions import machine,StoryCpu,tick
import story_missions as doc
import story_runtime as story
import story_cinematics as cinema
import native_preparation as prep


class CineCpu(StoryCpu):
    def extra_instruction(self,ins,pc):
        if ins>>26==17 and (ins>>21)&31==20 and ins&63==32:
            self.set_number((ins>>6)&31,self.signed_word(self.f[(ins>>11)&31]));return
        return super().extra_instruction(ins,pc)


def fixture(seconds=.1):
    d=doc.default_mission();d['events']=[dict(id='cue',when=dict(type='time',seconds=0),actions=[dict(type='cinematic',fighter='hero',animation=dict(character=2,clip=32),seconds=seconds,voice=dict(character=0,line=71))])]
    d=doc.validate(d);c=machine(d);c.__class__=CineCpu
    c.w(prep.CONTROL,prep.MAGIC)
    c.cine=0x1500000;c.active=0x1501000;c.calls=[]
    c.w(c.r[28]-22180,c.cine);c.w(c.r[28]-22176,c.active)
    c.write(c.cine,bytes((i%256 for i in range(832))));c.w(c.cine+812,0);c.w(c.cine+776,0)
    c.camera_before=c.read(c.cine,832)
    for off,value in ((0,cinema.MAGIC),(4,c.manager),(8,4)):c.w(cinema.CONTROL+off,value)
    c.write(cinema.FORMATION,cinema.formation_code());c.write(cinema.START,cinema.start_code());c.write(cinema.TICK,cinema.tick_code());c.write(cinema.VOICE,cinema.voice_code())
    c.write(cinema.DESCRIPTORS,struct.pack('<IIfiii12f2I',cinema.CLIPS,3,1,0,71,80,0,-150,350,0,-100,0,60,-150,350,0,-100,0,cinema.CLIPS+0x100,0))
    c.write(cinema.CLIPS+0x100,cinema.camera_samples(dict(eye=[0,-150,350],target=[0,-100,0],end_eye=[60,-150,350]),3))
    model=c.models[0];c.w(model+192,0x180000);c.w(c.actors[0]+2420,42)
    c.write(model+2416,struct.pack('<4f',100,-20,300,1));c.write(model+2384,c.read(model+2416,16))
    for at in (0x24D038,0x1C47A8,0x24C958,0x24E3F8,0x1C3E60,0x1D70E8):
        c.callbacks[A(at)]=lambda m,at=at:m.calls.append((at,tuple(m.r[4:8])))
    c.callbacks[A(0x24E2B0)]=lambda m:m.write(m.r[4]+2416,m.read(m.r[4]+2384,16))
    c.callbacks[A(0x23E950)]=lambda m:m.calls.append(('viewport',tuple(m.r[4:6])))
    c.callbacks[A(0x23D510)]=lambda m:m.w(m.r[28]-22176,m.cine)
    c.callbacks[A(0x23E6A0)]=lambda m:m.w(m.r[28]-22176,m.r[4])
    c.callbacks[A(0x265970)]=lambda m:m.calls.append(('stop_voice',m.r[4]))
    def voice(m):
        m.calls.append(('voice',tuple(m.r[4:9])));m.hi=555;m.lo=666;m.f[5]=123;m.fcr31=999
    c.callbacks[A(0x265E38)]=voice
    return c,d


class CinematicTests(unittest.TestCase):
    def test_second_wind_runs_native_getup_voice_shot_heal_then_form(self):
        import test_revive_native_path as native
        class NativeCineCpu(CineCpu,native.Cpu):pass
        c,d=fixture();c.__class__=NativeCineCpu
        original=native.fixture();c.memory.update(original.memory);c.callbacks.update(original.callbacks);c.events=[]
        d['events']=[dict(id='second-wind',when=dict(type='defeated',fighter='hero'),timeout_seconds=30,actions=[
            dict(type='recover',fighter='hero',health_percent=1),
            dict(type='cinematic',fighter='hero',animation=dict(character=0,clip=212),seconds=.1,voice=dict(character=0,line=71,volume=80)),
            dict(type='heal',fighter='hero',health_percent=100),dict(type='transform',fighter='hero',character=2)])]
        d=doc.validate(d);c.write(story.FRAME,story.frame(d,{i:int(i>0) for i in range(4)}))
        native.dispatch(c);tick(c);self.assertEqual(c.u(native.ACTOR+0x9E4),300)
        for _ in range(32):native.dispatch(c);tick(c)
        self.assertEqual(c.u(native.ACTOR+0x948),11);self.assertEqual(c.u(prep.CONTROL+16),1)
        self.assertEqual(c.u(story.CONTROL+48),1)
        for _ in range(3):c.r[31]=0xFEED0000;c.run(cinema.TICK)
        self.assertIn(('voice',(0,0,71,102,0)),c.calls)
        tick(c,3);self.assertEqual(c.u(native.ACTOR+0x9E4),30000)
        self.assertEqual(c.u(native.ACTOR+0x94C),237) # Destination 2 is route slot 1 in fixture.
        self.assertEqual(c.u(story.EVENTS),1)
        # The resource loader completes asynchronously; the event waits for it.
        c.w(c.models[0]+12,2);c.w(native.ACTOR+0x94C,0xffffffff);tick(c,2)
        self.assertEqual(c.u(story.EVENTS),2);self.assertEqual(c.u(story.CONTROL+48),0)

    def test_complete_shot_restores_camera_animation_and_registers(self):
        c,d=fixture();tick(c);self.assertEqual(c.u(cinema.CONTROL+12),1);self.assertEqual(c.u(prep.CONTROL+16),1)
        before=(c.read(c.actors[0],0x1600),c.read(c.actors[1],0x1600),c.camera_before)
        c.r[16]=0x99887766554433221122334455667788;c.hi=7;c.lo=9;c.fcr31=17;c.f[5]=456
        preserved=(c.r[16],c.hi,c.lo,c.fcr31,c.f[5])
        for n in range(3):c.r[31]=0xFEED0000;c.run(cinema.TICK)
        self.assertEqual((c.r[16],c.hi,c.lo,c.fcr31,c.f[5]),preserved)
        self.assertEqual(c.u(cinema.CONTROL+12),3);self.assertEqual(c.u(prep.CONTROL+16),0)
        self.assertEqual(c.read(c.cine,832),before[2]);self.assertEqual(c.u(c.r[28]-22176),c.active)
        self.assertEqual(c.u(c.models[0]+192),0x180000)
        self.assertEqual(c.read(c.actors[0],0x1600),before[0]);self.assertEqual(c.read(c.actors[1],0x1600),before[1])
        self.assertIn(('voice',(0,0,71,102,0)),c.calls)
        tick(c,2);self.assertEqual(c.u(story.EVENTS),2)

    def test_camera_interpolates_relative_to_actor_and_root_is_anchored(self):
        c,_=fixture();tick(c);c.r[31]=0xFEED0000;c.run(cinema.TICK)
        self.assertEqual(struct.unpack('<3f',c.read(c.cine+720,12)),(100,-170,650))
        c.fw(c.models[0]+2416,170);c.fw(c.models[0]+2384,170)
        c.r[31]=0xFEED0000;c.run(cinema.TICK)
        self.assertEqual(c.fr(c.models[0]+2416),100)
        self.assertAlmostEqual(c.fr(c.cine+720),130,places=4)

    def test_start_waits_for_native_cinematic_or_reload_and_changed_world_aborts(self):
        import extra_reload_requests as reloads
        for addr in (lambda c:c.cine+812,lambda c:reloads.RECORDS+4):
            c,_=fixture();c.w(addr(c),1);tick(c);self.assertEqual(c.u(cinema.CONTROL+12),0)
            self.assertEqual(c.u(prep.CONTROL+16),0)
            c.w(addr(c),0);tick(c);self.assertEqual(c.u(cinema.CONTROL+12),1)
        c,_=fixture();tick(c);before=c.read(c.actors[0],0x1600);c.w(c.r[28]-22364,0x1800100)
        c.r[31]=0xFEED0000;c.run(cinema.TICK)
        self.assertEqual(c.u(cinema.CONTROL+12),100);self.assertEqual(c.read(c.actors[0],0x1600),before)

    def test_held_gate_calls_scene_tick_and_restores_split_on_completion(self):
        c,_=fixture();tick(c);c.write(prep.GATE,prep.gate_code());c.w(prep.CONTROL,prep.MAGIC)
        c.callbacks[prep.NATIVE]=lambda m:None
        for n in range(3):
            c.r[31]=0x100000;c.run(prep.GATE,stops=(0x100018,))
            self.assertEqual(c.r[2],int(n==2))
        self.assertEqual(c.u(cinema.CONTROL+12),3)

    def test_pause_does_not_advance_shot(self):
        # The whole battle loop is paused by the native pause dispatcher. The
        # scripted event clock remains frame-based, not host wall-clock based.
        c,_=fixture();c.w(A(0x3337B8),0x100);tick(c,30)
        self.assertEqual(c.u(cinema.CONTROL+12),0)

    def test_unarmed_transport_cannot_strand_a_pending_scene(self):
        c,_=fixture();c.w(prep.CONTROL,0);tick(c)
        self.assertEqual(c.u(cinema.CONTROL+12),0);self.assertEqual(c.u(prep.CONTROL+16),0)

    def test_borrowed_root_motion_is_removed_without_changing_other_keys(self):
        # Minimal legal native clip with two translation keys on bone zero.
        import model_animations as animation
        raw=bytearray(200);struct.pack_into('<HHH',raw,0,0,30,0)
        struct.pack_into('<H',raw,6,37);struct.pack_into('<HH',raw,148,0,2)
        for i,(time,x) in enumerate(((0,4.),(30,100.))):
            struct.pack_into('<3fIQ',raw,152+24*i,x,-10.,8.,time,0x3800008000080000)
        packet=b'\xff\x80\xfe'+struct.pack('>H',len(raw))+raw
        packed=struct.pack('<II',len(raw),len(packet))+packet
        result=animation.decompress_animation(cinema.anchored_animation(packed))
        expected=bytearray(raw)
        for i in range(2):struct.pack_into('<3f',expected,152+24*i,0,0,0)
        self.assertEqual(result,expected)

    def test_voice_calls_native_volume_and_pitch_abi(self):
        c,_=fixture();c.r[4]=3;c.r[5]=cinema.DESCRIPTORS+12;c.r[31]=0xFEED0000
        c.run(cinema.VOICE)
        self.assertIn(('stop_voice',5),c.calls)
        self.assertIn(('voice',(1,0,71,102,0)),c.calls)


if __name__=='__main__':unittest.main()
