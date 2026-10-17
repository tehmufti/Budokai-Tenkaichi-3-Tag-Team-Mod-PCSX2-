"""Run the real native queue reset/dispatch around deferred tag sounds."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
from native_map import A, elf_path
from prototype import ROOT,elf_reader
import tag_rush_audio_queue as queue
import tag_rush_audio as audio
import tag_rush_scene as scene
import tag_rush_assets as assets
import tag_rush_staging as staging
import tag_team_rush as tag
import fresh_team_combat as core
from test_tag_rush_audio import machine
from test_tag_rush_camera import run


def native_machine(c=None):
    c=c or machine();native=elf_reader(elf_path(ROOT))[2]
    for address,data in queue.pieces():
        if address!=queue.STATE:c.write(address,data)
    c.write(A(0x2EF290),native(A(0x2EF290),32))
    for address,size in ((0x1DA058,0x40),(0x1D9B78,0xB0),(0x1DA098,0x2B0),(0x1DA370,0x60),
                         (0x1DA348,0x28),(0x1F5FF8,0x38)):
        c.write(A(address),native(A(address),size));c.callbacks.pop(A(address),None)
    c.played=[];c.records=[];c.cleanup=[]
    c.callbacks[A(0x121FA8)]=lambda m:m.write(m.r[4],m.read(m.r[5],16))
    c.callbacks[A(0x1DC178)]=lambda m:m.r.__setitem__(2,m.u(core.POINTERS+4*m.r[4]))
    c.callbacks[A(0x1DC280)]=lambda m:m.r.__setitem__(2,m.u(core.MODELS+4*m.u(m.r[4]+12)))
    c.callbacks[A(0x1DC348)]=lambda m:m.r.__setitem__(2,0)
    def spatial(m):m.w(m.r[5],64);m.w(m.r[6],0)
    c.callbacks[A(0x1D9DB0)]=spatial
    def play(m):m.played.append(tuple(m.r[4:8]));m.r[2]=100+len(m.played)
    c.callbacks[A(0x124F88)]=play
    c.callbacks[A(0x1D9A20)]=lambda m:m.r.__setitem__(2,0x3700000)
    c.callbacks[A(0x1D9A58)]=lambda m:m.r.__setitem__(2,0x3700000)
    c.callbacks[A(0x1D9A90)]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[A(0x1D9C28)]=lambda m:c.records.append(tuple(m.r[4:10]))
    c.callbacks[A(0x1D9D28)]=lambda m:c.cleanup.append(m.r[4])
    c.callbacks[A(0x1252D8)]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[A(0x1251E8)]=lambda m:m.r.__setitem__(2,0)
    return c


def enqueue(c,sound=73,position=(10.,-30.,20.,1.)):
    at=0x3710000;c.write(at,struct.pack('<4f',*position));c.r[4:7]=[at,0,sound]
    c.set_number(12,200.);c.set_number(13,1500.);run(c,queue.ENQUEUE)


class DeferredAudioTests(unittest.TestCase):
    def test_paired_attacks_open_with_the_same_native_startup_as_every_tag(self):
        from test_tag_rush_approach import machine as approach_machine
        import tag_rush_approach as rush
        import tag_rush_blue_native as blue
        for character in (blue.GOKU,*blue.TRUNKS):
            # Their dash belongs to variant5's own pursuit after the opening.
            for reverse in (False,True):
                c=native_machine(approach_machine());manager=c.u(tag.CONTROL+tag.C['manager'])
                for index,ident in zip((0,2),(35,character) if reverse else (character,35)):
                    c.w(c.models[index]+12,ident)
                    c.write(c.u(scene.ADMISSION)+ident,b'\x03')
                c.r[4:7]=[0,2,1];run(c,rush.BEGIN);self.assertEqual(c.r[2],1)
                run(c,A(0x1DA058));run(c,queue.FLUSH)
                self.assertEqual([r[1]for r in c.played],[rush.NATIVE_START_SOUND],(character,reverse))

    def test_native_prelude_sound_survives_frame_clear_once_for_actual_owner(self):
        from test_tag_rush_approach import machine as approach_machine
        import tag_rush_approach as rush
        native=elf_reader(elf_path(ROOT))[2]
        self.assertEqual(struct.unpack('<I',native(A(0x1FB4A0),4))[0],(3<<26)|(A(0x1F5FF8)>>2))
        self.assertEqual(struct.unpack('<I',native(A(0x1F6008),4))[0],0x24050000|rush.NATIVE_START_SOUND)
        for owner,partner in ((0,2),(2,0)):
            c=native_machine(approach_machine());manager=c.u(tag.CONTROL+tag.C['manager'])
            c.r[4:7]=[owner,partner,1];run(c,rush.BEGIN);self.assertEqual(c.r[2],1)
            self.assertEqual(c.u(rush.STATE+rush.S['sound_pending']),1)
            # Run actual1F5FF8 exactly as native261 phase0. This first request
            # is cleared by1C2B30, before the patched late dispatch runs.
            c.r[4:7]=[c.actors[owner],4,1];run(c,A(0x1F5FF8))
            self.assertEqual(c.u(manager+288),1);run(c,A(0x1DA058));run(c,queue.FLUSH)
            self.assertEqual(c.played,[(4,rush.NATIVE_START_SOUND,64,0)])
            self.assertEqual(c.read(manager+160+28,1)[0],owner)
            self.assertEqual(c.u(rush.STATE+rush.S['sound_delivered']),1)
            for _ in range(8):
                c.r[4:7]=[owner,partner,1];run(c,rush.BEGIN);self.assertEqual(c.r[2],0)
                run(c,A(0x1DA058));run(c,queue.FLUSH)
            self.assertEqual(len(c.played),1)
            # Native285 uses slot4 without the prelude flag and does not
            # request43 again; the original rush action remains unchanged.
            c.r[4:7]=[c.actors[owner],4,0];run(c,A(0x1F5FF8))
            self.assertEqual(c.u(manager+288),0)

    def test_prelude_receipt_pause_backlog_duplicate_and_cancellation(self):
        from test_tag_rush_approach import machine as approach_machine,begin
        import tag_rush_approach as rush
        import tag_rush_launch as launch
        for kind in ('pause','full','already_native','cancel','world','identity','params','expired','bank','not_accepted'):
            c=native_machine(approach_machine());manager=c.u(tag.CONTROL+tag.C['manager'])
            if kind=='not_accepted':
                c.callbacks[A(0x1E23D0)]=lambda m:None
            self.assertEqual(begin(c),1)
            if kind=='pause':c.w(A(0x333700),1)
            elif kind=='full':c.w(manager+288,4)
            elif kind=='already_native':c.r[4:7]=[c.actors[0],4,1];run(c,A(0x1F5FF8))
            elif kind=='cancel':c.r[4]=1;run(c,rush.CANCEL)
            elif kind=='world':c.w(c.r[28]-22364,manager+0x10000)
            elif kind=='identity':c.w(c.models[0]+12,99)
            elif kind=='params':c.w(c.models[0]+2348,launch.PARAMS+16)
            elif kind=='expired':c.w(rush.STATE+rush.S['ticks'],5)
            elif kind=='bank':c.callbacks[A(0x1252D8)]=lambda m:m.r.__setitem__(2,0)
            # Call only the new late helper where full/stale native context
            # intentionally cannot safely run the original sound dispatcher.
            run(c,rush.START_SOUND)
            self.assertEqual(c.u(rush.STATE+rush.S['sound_pending']),int(kind in ('pause','full')),kind)
            if kind in ('pause','full'):
                c.w(A(0x333700),0);run(c,A(0x1DA058));run(c,queue.FLUSH)
                self.assertEqual([r[1]for r in c.played],[rush.NATIVE_START_SOUND],kind)
            elif kind=='already_native':
                self.assertEqual(c.u(manager+288),1);run(c,queue.DISPATCH)
                self.assertEqual([r[1]for r in c.played],[rush.NATIVE_START_SOUND])
            else:self.assertFalse(c.played,kind)

    def test_early_native_request_is_erased_but_deferred_request_reaches_playback(self):
        c=native_machine();manager=c.u(tag.CONTROL+tag.C['manager'])
        at=0x3710000;c.write(at,struct.pack('<4f',10.,-30.,20.,1.));c.r[4:7]=[at,0,73]
        c.set_number(12,200.);c.set_number(13,1500.);run(c,queue.SOUND)
        self.assertEqual(c.u(manager+288),1)
        run(c,A(0x1DA058));run(c,queue.DISPATCH);self.assertFalse(c.played)
        enqueue(c);self.assertEqual(c.r[2],1);self.assertEqual(c.u(manager+288),0)
        run(c,A(0x1DA058));run(c,queue.FLUSH)
        self.assertEqual(c.played,[(4,73,64,0)])
        self.assertEqual(c.u(queue.STATE+queue.F['pending']),0)
        self.assertEqual(c.u(queue.STATE+queue.F['delivered']),1)
        self.assertEqual(c.records[0][1],101)

    def test_existing_native_requests_are_not_overwritten_and_backlog_is_bounded(self):
        c=native_machine();manager=c.u(tag.CONTROL+tag.C['manager'])
        for sound in (24,30,31):enqueue(c,sound)
        run(c,A(0x1DA058))
        for sound in (1,2,3):
            c.r[4:7]=[0x3710000,0,sound];c.set_number(12,200.);c.set_number(13,1500.);run(c,queue.SOUND)
        run(c,queue.FLUSH)
        self.assertEqual([r[1] for r in c.played],[1,2,3,24])
        self.assertEqual(c.u(queue.STATE+queue.F['pending']),2)
        run(c,A(0x1DA058));run(c,queue.FLUSH)
        self.assertEqual([r[1] for r in c.played],[1,2,3,24,30,31])
        self.assertEqual(c.u(manager+288),2)
        for _ in range(queue.CAPACITY+1):enqueue(c)
        self.assertEqual(c.u(queue.STATE+queue.F['pending']),queue.CAPACITY)
        self.assertEqual(c.u(queue.STATE+queue.F['overflow']),1)

    def test_cancel_stale_world_pause_unloaded_bank_and_expired_events_are_safe(self):
        for kind in ('cancel','world','pause','bank','expired'):
            c=native_machine();enqueue(c)
            if kind=='cancel':c.w(tag.CONTROL+tag.C['active'],0)
            elif kind=='world':c.w(c.r[28]-22364,0x1901000)
            elif kind=='pause':c.w(A(0x333700),1)
            elif kind=='bank':c.callbacks[A(0x1252D8)]=lambda m:m.r.__setitem__(2,0)
            else:c.w(scene.STATE+scene.S['total_ticks'],5)
            run(c,queue.FLUSH);self.assertFalse(c.played,kind)
            self.assertEqual(c.u(queue.STATE+queue.F['pending']),int(kind=='pause'))

    def test_charge_loop_renews_actual_actor_owners_and_stops_on_fire_or_cancel(self):
        c=native_machine();manager=c.u(tag.CONTROL+tag.C['manager'])
        descriptor=assets.BASE;metadata=assets.BASE+0x1000
        c.w(descriptor+28,assets.OWN_CLASH_POSE|assets.BEAM_LEAD|assets.BEAM_PARTNER)
        c.w(metadata+8,90);c.callbacks[staging.QUERY]=lambda m:m.r.__setitem__(2,metadata)
        c.callbacks[A(0x1251E8)]=lambda m:m.r.__setitem__(2,int(m.r[5]==21))
        for frame in (0,1):
            c.w(scene.STATE+scene.S['ticks'],frame);run(c,A(0x1DA058));run(c,queue.FLUSH)
            self.assertEqual(c.u(manager+288),2)
            self.assertEqual(tuple(c.read(manager+160+i*32+28,1)[0] for i in range(2)),(0,2))
        self.assertEqual([r[1] for r in c.played],[21]*4)
        self.assertEqual(c.u(queue.STATE+queue.F['charge_requests']),4)
        c.w(scene.STATE+scene.S['ticks'],45);run(c,A(0x1DA058));run(c,queue.FLUSH)
        self.assertEqual(c.u(manager+288),0)
        c.w(tag.CONTROL+tag.C['active'],0);run(c,queue.FLUSH)
        self.assertEqual(len(c.played),4)
        # Native dispatch still reaches cleanup when no charge is renewed.
        self.assertTrue(c.cleanup)

    def test_exact_native_hook_and_disjoint_audio_reservation(self):
        import tag_rush_effects as effects
        import tag_rush_recovery as recovery
        native=elf_reader(elf_path(ROOT))[2]
        self.assertEqual(native(queue.HOOK,4),queue.NATIVE_HOOK)
        blocks=queue.pieces()
        self.assertTrue(all(p+len(b)<=q for (p,b),(q,_)in zip(blocks,blocks[1:])))
        self.assertLessEqual(recovery.END,queue.BASE)
        self.assertLessEqual(effects.CHARGE_END,queue.BASE)
        self.assertEqual(queue.RECORDS+queue.CAPACITY*queue.STRIDE,queue.END)


if __name__=='__main__':unittest.main()
