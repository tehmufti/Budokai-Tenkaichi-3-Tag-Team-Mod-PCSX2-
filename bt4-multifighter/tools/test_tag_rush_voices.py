# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import unittest
import tag_rush_voices as voices
import tag_rush_audio as audio
import tag_rush_scene as scene
import tag_team_rush as tag
import extra_voice
from native_map import A
from test_tag_rush_audio import machine as audio_machine
from test_tag_rush_camera import run


def machine():
    c=audio_machine();manager=c.u(voices.STATE+voices.C['manager'])
    c.w(extra_voice.CONTROL,extra_voice.MAGIC);c.w(extra_voice.CONTROL+4,manager);c.w(extra_voice.CONTROL+8,4)
    c.w(extra_voice.PLAY_ENTRY,(2<<26)|(extra_voice.PLAY>>2));c.w(extra_voice.PLAY_ENTRY+4,0)
    c.w(manager+40,0x3700000);c.write(0x3700000+20*8,b'\x32\x00\x02\x00')
    c.voice_requests=[];c.busy=False
    c.callbacks[voices.IDLE]=lambda m:m.r.__setitem__(2,not c.busy)
    def play(m):
        c.voice_requests.append(tuple(m.r[4:9]));c.busy=True
        for r in (*range(8,16),24,25):m.r[r]=0xABC00000+r
        for r in range(20):m.set_number(r,123.)
    c.callbacks[voices.PLAY]=play
    return c


def tick(c,phase=0,ticks=12):
    c.w(scene.STATE+scene.S['phase'],phase);c.w(scene.STATE+scene.S['ticks'],ticks);run(c,voices.TICK)


class VoiceTests(unittest.TestCase):
    def test_two_actual_owners_are_staggered_and_never_stop_or_overlap(self):
        c=machine();tick(c)
        self.assertEqual(c.voice_requests,[(0,40,50,100,0)])
        for _ in range(voices.ACTOR_HZ+2):tick(c,2)
        self.assertEqual(len(c.voice_requests),1,'occupied stream preserves the first line')
        c.busy=False;tick(c,2)
        self.assertEqual(c.voice_requests,[(0,40,50,100,0),(2,41,50,100,0)])
        for _ in range(60):tick(c,6)
        self.assertEqual(len(c.voice_requests),2)
        self.assertEqual(c.u(voices.STATE+voices.C['played']),2)

    def test_async_idle_cannot_submit_both_lines_at_once(self):
        c=machine();tick(c);c.busy=False
        for _ in range(voices.ACTOR_HZ):tick(c,2)
        self.assertEqual(len(c.voice_requests),1)
        tick(c,2);self.assertEqual(len(c.voice_requests),2)

    def test_stale_missing_and_foreign_owner_routes_are_silent(self):
        for kind in ('hook','arbiter','manager','pause','retiring','model','character','line','count','blocker'):
            c=machine()
            if kind=='hook':c.w(extra_voice.PLAY_ENTRY,0)
            elif kind=='arbiter':c.w(extra_voice.CONTROL,0)
            elif kind=='manager':c.w(extra_voice.CONTROL+4,0)
            elif kind=='pause':c.w(A(0x333700),1)
            elif kind=='retiring':c.w(scene.STATE+scene.S['retiring'],1)
            elif kind=='model':c.w(c.models[0]+8,0)
            elif kind=='character':c.w(c.models[0]+12,999)
            elif kind=='line':c.write(0x3700000+20*8,b'\x64\x00')
            elif kind=='count':c.write(0x3700000+20*8+2,b'\x00\x00')
            elif kind=='blocker':c.w(A(0x334788),1)
            tick(c);self.assertFalse(c.voice_requests,kind)

    def test_partner_waits_until_joining_choreography(self):
        c=machine();tick(c);c.busy=False
        for _ in range(voices.ACTOR_HZ+3):tick(c,1)
        self.assertEqual(len(c.voice_requests),1)
        tick(c,2);self.assertEqual(len(c.voice_requests),2)

    def test_new_scene_resets_voice_ownership_without_stopping_streams(self):
        c=machine();tick(c);run(c,audio.RESET)
        self.assertEqual(c.u(voices.STATE+voices.C['played']),0)
        tick(c);self.assertEqual(len(c.voice_requests),1)
        c.busy=False;tick(c);self.assertEqual(len(c.voice_requests),2)

if __name__=='__main__':unittest.main()
