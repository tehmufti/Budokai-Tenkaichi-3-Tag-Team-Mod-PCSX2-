"""Native effect pause predicates and active-director clock agreement."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
import tag_rush_pause as pause
import tag_rush_scene as scene
import tag_team_rush as tag
from native_map import A, elf_path
from prototype import ROOT, elf_reader
from test_tag_rush_effects import machine as effects_machine
from test_tag_rush_camera import run


def machine():
    c=effects_machine();c.write(pause.CHECK,pause.code());c.w(scene.STATE,scene.SCENE_MAGIC)
    c.w(A(0x3337C0),1);c.w(A(0x2FEB38),0x2470000);c.w(0x2470000,3)
    for role,index in enumerate((0,2,1)):
        row=scene.ROWS+role*scene.STRIDE;actor,model=c.actors[index],c.models[index]
        for key,value in (('index',index),('actor',actor),('model',model),('model_id',c.u(model+16)),
                          ('character',c.u(model+12)),('skeleton',0)):
            c.w(row+scene.R[key],value)
    native=elf_reader(elf_path(ROOT))[2]
    for p,size in ((0x12CE88,0x48),(0x205E00,0x38),(0x1DC2C0,0x10)):
        c.write(A(p),native(A(p),size))
    def actor(m):
        m.r[2]=next((a for a in c.actors if c.u(a+12)==m.r[4]),0)
    c.callbacks[A(0x1DC1A0)]=actor
    c.callbacks[A(0x126EC8)]=lambda m:m.r.__setitem__(2,A(0x3337B8)-6640)
    return c


def capture(c):return [(c.read(a,0x1600),c.read(m,0x1700))for a,m in zip(c.actors,c.models)]


class ActivePauseTests(unittest.TestCase):
    def test_exact_native_pause_answers_hold_all_free_advance_and_mixed_cancel(self):
        for mask in range(8):
            c=machine()
            for role,index in enumerate((0,2,1)):c.w(c.actors[index]+4896,(mask>>role)&1)
            before=capture(c);old=c.r.copy();floats=c.f.copy()
            run(c,pause.CHECK)
            self.assertEqual(c.r[2],pause.ADVANCE if mask==0 else pause.HOLD if mask==7 else pause.CANCEL)
            self.assertEqual(capture(c),before)
            self.assertEqual(c.r[3:31],old[3:31]);self.assertEqual(c.f,floats)

    def test_unrelated_form_manager_stop_does_not_stop_free_group_but_world_reload_cancels(self):
        c=machine();manager=c.u(tag.core.ACTORS);c.w(manager+628,1)
        c.w(c.actors[3]+4896,1)
        before=capture(c);run(c,pause.CHECK)
        self.assertEqual(c.r[2],pause.ADVANCE);self.assertEqual(capture(c),before)
        c.w(A(0x3337B8),0x100);run(c,pause.CHECK)
        self.assertEqual(c.r[2],pause.HOLD)
        for flags in (0x2000,0x2100):
            c.w(A(0x3337B8),flags);run(c,pause.CHECK)
            self.assertEqual(c.r[2],pause.CANCEL);self.assertEqual(capture(c),before)

    def test_native_start_menu_holds_until_native_resume_not_diagnostic_quiet_release(self):
        c=machine();manager=c.u(tag.core.ACTORS);before=capture(c)
        c.w(A(0x3337B8),0x4100)
        for value in (1,0):
            for field,word in ((0,pause.preparation.MAGIC),(16,value),(24,manager)):
                c.w(pause.preparation.CONTROL+field,word)
            run(c,pause.CHECK)
            self.assertEqual(c.r[2],pause.HOLD)
            self.assertEqual(c.u(A(0x3337B8)),0x4100)
            self.assertEqual(capture(c),before)
        # The native pause-menu return path clears 0x4100. The director
        # continues without resetting its phase or altering fighter state.
        c.w(A(0x3337B8),0);run(c,pause.CHECK)
        self.assertEqual(c.r[2],pause.ADVANCE)
        self.assertEqual(capture(c),before)

    def test_native_quiet_holds_only_matching_capture_without_actor_writes(self):
        c=machine();manager=c.u(tag.core.ACTORS)
        for field,value in ((0,pause.preparation.MAGIC),(16,1),(24,manager)):
            c.w(pause.preparation.CONTROL+field,value)
        c.w(A(0x3337B8),0x2100)
        before=capture(c);run(c,pause.CHECK);self.assertEqual(c.r[2],pause.HOLD)
        self.assertEqual(capture(c),before)
        c.w(pause.preparation.CONTROL+24,manager+16);run(c,pause.CHECK)
        self.assertEqual(c.r[2],pause.CANCEL)

    def test_stale_model_capture_cancels_and_menu_pause_holds(self):
        for offset in ('actor','model','index','model_id','character','skeleton'):
            c=machine();p=scene.ROWS+scene.STRIDE+scene.R[offset];c.w(p,c.u(p)^0x40000000)
            run(c,pause.CHECK);self.assertEqual(c.r[2],pause.CANCEL,offset)
        c=machine();c.w(c.models[2]+8,0);run(c,pause.CHECK);self.assertEqual(c.r[2],pause.CANCEL)
        c=machine();c.w(A(0x333700),1);run(c,pause.CHECK);self.assertEqual(c.r[2],pause.HOLD)
        c=machine();c.w(tag.CONTROL+tag.C['ready'],0);run(c,pause.CHECK);self.assertEqual(c.r[2],pause.CANCEL)
        c=machine();c.w(pause.modes.CONTROL+12,pause.modes.FFA);run(c,pause.CHECK);self.assertEqual(c.r[2],pause.CANCEL)

    def test_coordinator_continues_unrelated_form_holds_common_pause_and_cancels_partial(self):
        for kind,expected in (('form',[('step',)]),('all',[]),('partial',[('finish',1)]),('quiet',[])):
            c=machine();c.write(tag.TICK,tag.tick_code());c.write(tag.GATE,tag.gate_code())
            c.w(tag.CONTROL+tag.C['shared'],1);manager=c.u(tag.core.ACTORS);c.w(manager+628,1)
            events=[];c.callbacks[tag.STEP]=lambda m:events.append(('step',))
            c.callbacks[tag.FINISH]=lambda m:events.append(('finish',m.r[4]))
            if kind=='all':
                for index in (0,2,1):c.w(c.actors[index]+4896,1)
            elif kind=='partial':c.w(c.actors[1]+4896,1)
            elif kind=='quiet':
                for field,value in ((0,pause.preparation.MAGIC),(16,1),(24,manager)):
                    c.w(pause.preparation.CONTROL+field,value)
            before=capture(c);run(c,tag.TICK)
            self.assertEqual(events,expected,kind);self.assertEqual(capture(c),before)


if __name__=='__main__':unittest.main()
