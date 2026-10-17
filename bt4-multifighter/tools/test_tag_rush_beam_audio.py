"""Private SFX allocation, dispatch and teardown without touching other banks."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')
import struct
import unittest
from unittest.mock import patch
import tag_rush_beam_audio as beam
import tag_rush_scene as scene
import tag_rush_assets as assets
import tag_rush_staging as staging
import tag_team_rush as tag
import tag_rush_bootstrap as boot
from tag_rush_install import selected_iso
from test_tag_rush_audio_queue import native_machine
from test_tag_rush_camera import run
from native_map import A,ACTOR_HZ,elf_path
from prototype import ROOT,elf_reader


def machine():
    c=native_machine();manager=c.u(tag.CONTROL+tag.C['manager'])
    import tag_rush_blue_native as blue
    address=blue.build(selected_iso())['beam_audio_address']
    for p,data in beam.pieces(selected_iso(),manager,address=address):c.write(p,data)
    address=c.u(beam.STATE+beam.S['bank_data'])
    c.write(address,beam.disc_bank(str(selected_iso()))['data'])
    c.audio=0x3720000;c.r[28]=0x304270;c.w(c.r[28]-20708,c.audio)
    c.w(c.r[28]-20712,0x3740000)
    c.write(beam.SPU_TABLE,struct.pack('<6I',1,0x1C1000,0x34000,0,0,0))
    c.allocations=[];c.freed=[];c.registered=[];c.stopped=[];c.unloaded=[];c.fail_alloc=0
    def allocate(m):
        m.allocations.append(m.r[4]);m.r[2]=0 if m.fail_alloc==len(m.allocations)else 0x130000+0x2000*len(m.allocations)
    c.callbacks[A(0x11EC28)]=allocate
    c.callbacks[A(0x11EC40)]=lambda m:m.freed.append(m.r[4])
    c.callbacks[A(0x11EDC8)]=lambda m:m.r.__setitem__(2,0x1C1000)
    # Execute the real header bind/loop-bitmap parser (allocation flag0).
    native=elf_reader(elf_path(ROOT))[2]
    for p,n in ((0x1246E0,0x1C0),(0x1253F8,0x170)):
        c.write(A(p),native(A(p),n));c.callbacks.pop(A(p),None)
    c.callbacks[A(0x1248A0)]=lambda m:m.w(m.r[4]+48,1)
    c.callbacks[A(0x1240F0)]=lambda m:m.registered.append(tuple(m.r[4:8]))
    c.callbacks[A(0x125188)]=lambda m:m.stopped.append(m.r[4])
    def unload(m):
        m.unloaded.append(m.r[4]);row=m.audio+76*(6 if m.r[4]==64 else 7)
        for off in (0,4,8):m.w(row+off,0)
    c.callbacks[A(0x124DC0)]=unload
    def drain(m):
        for i in range(8):m.w(m.audio+76*i+48,0);m.w(m.audio+76*i+52,0)
    c.callbacks[A(0x124A28)]=drain
    return c


def initialize(c):
    run(c,beam.INIT);assert c.r[2]==0
    row=c.u(beam.STATE+beam.S['row']);c.w(row+48,0);run(c,beam.INIT);assert c.r[2]==1


class BeamAudioTests(unittest.TestCase):
    def test_blue_pair_uses_the_same_ultimate_impact_and_other_variants_do_not(self):
        c=machine();initialize(c)
        for variant in range(7):
            c.w(tag.CONTROL+tag.C['variant'],variant);before=len(c.played)
            run(c,beam.IMPACT)
            self.assertEqual(len(c.played)-before,int(variant in (5,6)))
            if variant in (5,6):self.assertEqual(c.played[-1][1],55)

    def test_galick_ultimate_sounds_follow_the_emitters_across_camera_cuts_once(self):
        import tag_rush_blue_native as blue
        c=machine();initialize(c);meta=assets.BASE+0x1000;c.w(meta+8,0)
        c.callbacks[staging.QUERY]=lambda m:m.r.__setitem__(2,meta)
        c.w(tag.CONTROL+tag.C['variant'],6)
        c.w(assets.BASE+28,assets.CUSTOM_FINISHER|blue.FLAG|assets.BEAM_LEAD)
        for phase,states in((4,(2,0)),(4,(1,0)),(5,(1,2)),(6,(1,1)),(7,(1,1)),(8,(1,1)),(9,(1,1))):
            c.w(scene.STATE+scene.S['phase'],phase)
            for role,state in enumerate(states):c.w(scene.ROWS+role*scene.STRIDE+blue.FX_STATE,state)
            run(c,beam.TICK);run(c,beam.TICK)
        self.assertEqual([v[1]for v in c.played],[45,54,45,54])
        self.assertEqual(c.u(beam.STATE+beam.S['charge']),2);self.assertEqual(c.u(beam.STATE+beam.S['fire']),2)
        run(c,beam.IMPACT);self.assertEqual(c.played[-1][1],55)
        self.assertLessEqual(beam.disc_bank(str(selected_iso()))['sizes'][0],61840)

    def test_bank_contains_only_reviewed_beams_impacts_and_silence(self):
        import fusion_audio_restore as original
        source=original.bank_file(0,False);plan=beam.disc_bank(str(selected_iso()));data=plan['data']
        self.assertLess(len(data),96*1024);self.assertEqual(beam.isolate_bank(source,original.bank_file(16,False)),plan)
        self.assertEqual(set(plan['sample_sha256']),{45,46,54,55})
        ultimate=original.bank_file(16,False);uh=ultimate[beam._u(ultimate,8):beam._u(ultimate,12)];ut=beam._u(uh,48)
        uo=[beam._u(uh,ut+beam._u(uh,ut+16+4*i))for i in range(57)]+[beam._u(uh,32)]
        for bank in (source,data):
            h=bank[beam._u(bank,8):beam._u(bank,12)];t=beam._u(h,48);rows=[t+beam._u(h,t+16+4*i)for i in range(57)]
            offsets=[beam._u(h,p)for p in rows]+[beam._u(h,32)]
            waves=[bank[64+a:64+b]for a,b in zip(offsets,offsets[1:])]
            if bank is source:original_waves=waves
            else:
                for i,wave in enumerate(waves):
                    start=beam._u(ultimate,4)
                    expected=ultimate[start+uo[i]:start+uo[i+1]]if i in(54,55)else original_waves[i if i in(45,46)else 47]
                    if i==55:
                        from tag_rush_sound_sample import at_rate,decode
                        rate=struct.unpack_from('<H',h,rows[i]+4)[0];self.assertEqual(rate,12000)
                        self.assertLess(abs(len(decode(wave))/rate-len(decode(expected))/16000),.004)
                        expected=at_rate(expected,16000,12000)
                    self.assertEqual(wave,expected,i)
                self.assertTrue(all(h[p+6]==0 for p in rows))

    def test_checked_allocation_real_header_bind_and_async_readiness(self):
        c=machine();run(c,beam.INIT);self.assertEqual(c.r[2],0)
        self.assertEqual(c.u(beam.STATE+beam.S['status']),beam.UPLOADING)
        self.assertEqual(len(c.allocations),2);self.assertEqual(c.registered[0][0],64)
        row=c.u(beam.STATE+beam.S['row']);self.assertEqual(c.u(row+36),beam.disc_bank(str(selected_iso()))['sizes'][0])
        self.assertEqual(c.read(row+57,16),bytes(16));self.assertEqual(c.read(row+56,1),bytes([56]))
        run(c,beam.INIT);self.assertEqual(c.r[2],0);self.assertEqual(len(c.allocations),2)
        c.w(row+48,0);run(c,beam.INIT);self.assertEqual(c.r[2],1)
        run(c,beam.INIT);self.assertEqual(len(c.allocations),2)

    def test_occupied_bank_fallback_and_no_space_or_iop_failure_are_safe(self):
        c=machine();c.w(c.audio+76*6,1);initialize(c);self.assertEqual(c.registered[0][0],128)
        self.assertEqual(c.u(c.audio+76*6),1)
        for reason in ('occupied','space','rows','iop'):
            c=machine()
            if reason=='occupied':c.w(c.audio+76*6,1);c.w(c.audio+76*7,1)
            elif reason=='space':c.w(beam.SPU_TABLE+8,0x1000)
            elif reason=='rows':
                for i in range(1,17):c.w(beam.SPU_TABLE+12*i,2)
            else:c.fail_alloc=2
            run(c,beam.INIT);self.assertEqual(c.r[2]&0xFFFFFFFF,0xFFFFFFFF,reason)
            self.assertFalse(c.registered,reason)
            self.assertEqual(c.freed,[0x132000]if reason=='iop'else[],reason)

    def test_native_upload_is_not_interrupted_and_foreign_receipts_are_ignored(self):
        c=machine();c.w(c.audio+48,1);run(c,beam.INIT);self.assertEqual(c.r[2],0);self.assertFalse(c.allocations)
        c=machine();initialize(c);row=c.u(beam.STATE+beam.S['row']);c.w(row+4,0x555555)
        run(c,beam.RELEASE);self.assertFalse(c.stopped);self.assertFalse(c.unloaded)
        c=machine();initialize(c);c.w(c.r[28]-20708,c.audio+0x1000);run(c,beam.RELEASE);self.assertFalse(c.unloaded)

    def test_two_actual_actors_charge_fire_once_and_private_sounds_stop(self):
        c=machine();initialize(c);descriptor=assets.BASE;meta=assets.BASE+0x1000
        c.w(descriptor+28,assets.OWN_CLASH_POSE|assets.BEAM_LEAD|assets.BEAM_PARTNER)
        c.w(meta+8,90);c.callbacks[staging.QUERY]=lambda m:m.r.__setitem__(2,meta)
        for ticks in (0,1,44):c.w(scene.STATE+scene.S['ticks'],ticks);run(c,beam.TICK)
        self.assertEqual(c.played,[(64,45,64,0)]*2)
        c.w(scene.STATE+scene.S['ticks'],45);run(c,beam.TICK);run(c,beam.TICK)
        self.assertEqual(c.played,[(64,45,64,0)]*2+[(64,46,64,0)]*2)
        self.assertEqual(c.u(beam.STATE+beam.S['charge']),2);self.assertEqual(c.u(beam.STATE+beam.S['fire']),2)
        c.w(tag.CONTROL+tag.C['active'],0);run(c,beam.TICK);run(c,beam.TICK)
        self.assertEqual(c.stopped,[64]);self.assertFalse(c.unloaded)
        c.w(tag.CONTROL+tag.C['active'],1);c.w(scene.STATE+scene.S['ticks'],0);run(c,beam.TICK)
        self.assertEqual(len(c.played),6)

    def test_pause_mixed_roles_failed_play_and_exact_firing_boundary(self):
        for flags,expected in ((assets.BEAM_LEAD,1),(assets.BEAM_PARTNER,1),(0,0)):
            c=machine();initialize(c);meta=assets.BASE+0x1000;c.w(meta+8,90)
            c.w(assets.BASE+28,assets.OWN_CLASH_POSE|flags);c.callbacks[staging.QUERY]=lambda m:m.r.__setitem__(2,meta)
            c.w(A(0x333700),1);run(c,beam.TICK);self.assertFalse(c.played)
            c.w(A(0x333700),0)
            with patch.object(beam,'ACTOR_HZ',25):c.write(beam.TICK,beam.tick_code())
            c.w(scene.STATE+scene.S['ticks'],37);run(c,beam.TICK);self.assertEqual([x[1]for x in c.played],[45]*expected)
            c.w(scene.STATE+scene.S['ticks'],38);run(c,beam.TICK);self.assertEqual([x[1]for x in c.played],[45]*expected+[46]*expected)

    def test_exit_waits_for_native_drain_then_frees_only_private_bank(self):
        c=machine();initialize(c);row=c.u(beam.STATE+beam.S['row']);c.w(row+48,1)
        run(c,beam.RELEASE);self.assertFalse(c.unloaded)
        run(c,beam.EXIT);self.assertEqual(c.unloaded,[64]);self.assertEqual(c.read(row,76),bytes(76))
        self.assertEqual(c.u(beam.STATE+beam.S['status']),beam.CLOSED)
        run(c,beam.EXIT);self.assertEqual(c.unloaded,[64])
        native=elf_reader(elf_path(ROOT))[2];self.assertEqual(native(beam.HOOK,4),beam.NATIVE_HOOK)

    def test_real_native_play_queues_private_bank_sample_without_voice_dispatch(self):
        c=machine();initialize(c);native=elf_reader(elf_path(ROOT))[2]
        for address,length in ((0x124F88,0x1A0),(0x1245F0,0x48),(0x124150,0xA0)):
            c.write(A(address),native(A(address),length));c.callbacks.pop(A(address),None)
        c.callbacks[A(0x124638)]=lambda m:m.r.__setitem__(2,64)
        c.callbacks[A(0x124688)]=lambda m:m.r.__setitem__(2,64)
        c.callbacks[A(0x1246A8)]=lambda m:m.r.__setitem__(2,0)
        meta=assets.BASE+0x1000;c.w(meta+8,90)
        c.w(assets.BASE+28,assets.OWN_CLASH_POSE|assets.BEAM_LEAD|assets.BEAM_PARTNER)
        c.callbacks[staging.QUERY]=lambda m:m.r.__setitem__(2,meta)
        run(c,beam.TICK);c.w(scene.STATE+scene.S['ticks'],45);run(c,beam.TICK)
        queue=c.u(c.r[28]-20712);self.assertEqual(c.u(queue+104),4)
        self.assertEqual([tuple(c.read(queue+108+12*i+4,2))for i in range(4)],[(64,45),(64,45),(64,46),(64,46)])
        self.assertEqual([c.read(queue+108+12*i+1,1)[0]for i in range(4)],[0]*4)
        self.assertEqual(c.u(beam.STATE+beam.S['fire']),2)

    def test_bootstrap_waits_for_sound_receipt_and_reports_safe_failure(self):
        from test_tag_rush_bootstrap import machine as bootstrap_machine
        c=bootstrap_machine();c.write(boot.CODE,boot.code(beam_audio=True))
        c.callbacks[beam.INIT]=lambda m:m.r.__setitem__(2,0);run(c,boot.CODE)
        self.assertEqual(c.init_calls,0);self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0)
        c.callbacks[beam.INIT]=lambda m:m.r.__setitem__(2,0xFFFFFFFF);run(c,boot.CODE)
        self.assertEqual(c.u(boot.STATE+boot.S['error']),5);self.assertEqual(c.init_calls,0)


if __name__=='__main__':unittest.main()
