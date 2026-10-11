"""Guest readiness is earned by native receipts, never host-published."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
import tag_rush_bootstrap as boot
import tag_team_rush as tag
import tag_rush_effects as fx
import fresh_team_combat as core
from test_tag_rush_effects import machine as effects_machine, POOL
from test_tag_rush_camera import run


def machine():
    c=effects_machine(prepared=False);c.init_calls=0;c.decline=False;c.bad=None
    manager=c.u(core.ACTORS)
    c.w(boot.A(0x2FEB38),0x2470000);c.w(0x2470000,3)
    for address,data in boot.pieces(manager,4):c.write(address,data)
    c.w(tag.CONTROL+tag.C['active'],0);c.w(tag.CONTROL+tag.C['ready'],0)
    def initialize(m):
        m.init_calls+=1
        if m.decline:m.r[2]=0;return
        m.write(fx.CONTROL,struct.pack('<8I',fx.MAGIC,manager,4,1,POOL,0,0,2))
        for index in range(2):
            row=fx.ROWS+index*fx.STRIDE
            m.w(row+fx.R['prepared'],fx.PREPARED)
            m.w(row+fx.HEADER+36,row+fx.META);m.w(row+fx.DESC+796,row+fx.HEADER)
        if m.bad is not None:m.w(m.bad,0)
        m.r[2]=1
    c.callbacks[fx.INIT]=initialize
    return c


class BootstrapTests(unittest.TestCase):
    def test_success_publishes_after_both_receipts_and_initializes_once(self):
        c=machine();old=c.r.copy();floats=c.f.copy()
        run(c,boot.CODE)
        self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),1)
        self.assertEqual(c.u(boot.STATE+boot.S['phase']),boot.READY)
        self.assertEqual(c.u(boot.STATE+boot.S['pool']),POOL)
        self.assertEqual(c.r[1:31],old[1:31]);self.assertEqual(c.f,floats)
        for _ in range(4):run(c,boot.CODE)
        self.assertEqual(c.init_calls,1)

    def test_failed_or_incomplete_descriptor_never_publishes_and_never_retries(self):
        for address in (fx.CONTROL+fx.C['init_status'],fx.CONTROL+fx.C['ready'],
                        fx.CONTROL+fx.C['pool'],fx.ROWS+fx.R['prepared'],
                        fx.ROWS+fx.STRIDE+fx.R['prepared'],fx.ROWS+fx.DESC+796):
            c=machine();c.bad=address;run(c,boot.CODE)
            self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0,hex(address))
            self.assertEqual(c.u(boot.STATE+boot.S['phase']),boot.FAILED)
            for _ in range(3):run(c,boot.CODE)
            self.assertEqual(c.init_calls,1)

    def test_stale_battle_online_and_bad_count_skip_native_initialization(self):
        for address,value in ((tag.CONTROL+tag.C['manager'],0),(core.MODE+12,6),
                              (boot.STATE+boot.S['count'],6)):
            c=machine();c.w(address,value);run(c,boot.CODE)
            self.assertEqual(c.init_calls,0);self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0)
            self.assertEqual(c.u(boot.STATE+boot.S['phase']),boot.FAILED)
        c=machine();c.write(boot.NETPLAY_CONTROL,struct.pack('<2I',boot.NETPLAY_MAGIC,1))
        run(c,boot.CODE);self.assertEqual(c.init_calls,0)
        self.assertEqual(c.u(boot.STATE+boot.S['error']),2)

    def test_consistent_invalid_capture_is_rejected_before_native_dereference(self):
        for manager in (0,3,0xFFFFFFFC,0x7FFFFFC):
            c=machine()
            for address in (boot.STATE+boot.S['manager'],tag.CONTROL+tag.C['manager'],
                            core.MODE+8,c.r[28]-22364):c.w(address,manager)
            run(c,boot.CODE)
            self.assertEqual(c.init_calls,0)
            self.assertEqual(c.u(boot.STATE+boot.S['phase']),boot.FAILED)
            self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0)
        c=machine()
        for address in (boot.STATE+boot.S['count'],tag.CONTROL+tag.C['count'],core.MODE+4,core.MODE+12):c.w(address,0x40000004)
        run(c,boot.CODE);self.assertEqual(c.init_calls,0)
        self.assertEqual(c.u(boot.STATE+boot.S['phase']),boot.FAILED)

    def test_pause_does_not_initialize_or_spend_timeout(self):
        c=machine();c.w(boot.A(0x333700),1)
        for _ in range(boot.TIMEOUT+1):run(c,boot.CODE)
        self.assertEqual(c.init_calls,0);self.assertEqual(c.u(boot.STATE+boot.S['age']),0)
        c.w(boot.A(0x333700),0);run(c,boot.CODE)
        self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),1)

    def test_long_intro_loading_hold_or_cinematic_does_not_spend_prerequisite_budget(self):
        for address,value,normal in ((0x2470000,2,3),(boot.start.CONTROL,1,0)):
            c=machine();c.w(address,value)
            for _ in range(boot.TIMEOUT+2):run(c,boot.CODE)
            self.assertEqual(c.init_calls,0);self.assertEqual(c.u(boot.STATE+boot.S['age']),0)
            c.w(address,normal);run(c,boot.CODE)
            self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),1)
        c=machine();manager=c.u(core.ACTORS);c.w(manager+628,1)
        for _ in range(boot.TIMEOUT+2):run(c,boot.CODE)
        self.assertEqual(c.init_calls,0);self.assertEqual(c.u(boot.STATE+boot.S['age']),0)
        c.w(manager+628,0);run(c,boot.CODE)
        self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),1)

    def test_missing_native_prerequisites_time_out_without_retrying_allocations(self):
        c=machine();c.decline=True
        for _ in range(boot.TIMEOUT+2):run(c,boot.CODE)
        self.assertEqual(c.init_calls,boot.TIMEOUT)
        self.assertEqual(c.u(boot.STATE+boot.S['error']),3)
        self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0)
        c=machine();c.w(fx.CONTROL+fx.C['init_status'],100);run(c,boot.CODE)
        self.assertEqual(c.init_calls,0);self.assertEqual(c.u(boot.STATE+boot.S['error']),4)

    def test_scene_disarm_is_not_undone_and_replaced_pool_is_rejected(self):
        c=machine();run(c,boot.CODE);c.w(tag.CONTROL+tag.C['ready'],0)
        run(c,boot.CODE);self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0)
        self.assertEqual(c.init_calls,1)
        c=machine();run(c,boot.CODE);c.w(c.r[28]+fx.NATIVE_POOL_OFFSET,POOL+0x10000)
        run(c,boot.CODE);self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0)
        self.assertEqual(c.init_calls,1)

    def test_frame_initializes_before_input_and_preserves_previous_hook(self):
        c=machine();previous=0x07254000;events=[]
        c.write(tag.FRAME,tag.frame_code(previous,bootstrap=True))
        for address,name in ((tag.INPUT,'input'),(tag.TICK,'tick'),(previous,'previous')):
            c.callbacks[address]=lambda m,label=name:events.append((label,m.u(tag.CONTROL+tag.C['ready'])))
        run(c,tag.FRAME)
        self.assertEqual(events,[('input',1),('tick',1),('previous',1)])


if __name__=='__main__':unittest.main()
