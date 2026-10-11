"""Execute native event dispatch for the tag beam's charge/fire handoff."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import unittest
import math
import struct
from test_tag_rush_effects import machine, run, A, fx
from test_tag_rush_scene import fixture
import tag_rush_scene as scene
import tag_rush_assets as assets


class ChargeTests(unittest.TestCase):
    def configured(self):
        c=machine();row=fx.ROWS;d=row+fx.DESC
        rules,group=0x3600000,0x3610000
        c.w(d+8,rules);c.w(d+12+5*16,group)
        c.write(group,bytes((5,5,0,0)));c.write(d+20+5*16,b'\0')
        # Two hand charge children, a fire child, and unrelated event rules.
        for i,(kind,end,phase) in enumerate(((0,2,0),(0,6,0),(1,3,1),(1,3,0),(3,4,1))):
            c.write(rules+64*i+8,bytes((kind,end,phase)))
        c.rendered=[]
        def render(m):
            i,flags=m.r[10],m.r[11];m.rendered.append((i,flags))
            at=m.r[5]+320+i;bits=m.read(at,1)[0]
            m.write(at,bytes([bits | (2 if flags&1 else 0) | (4 if flags&2 else 0)]))
        c.callbacks[A(0x14FF50)]=render
        c.r[4:6]=[0,90];run(c,fx.CHARGE_SPAWN)
        self.assertEqual(c.r[2],1)
        return c

    def test_charge_uses_native_start_rules_without_firing_or_damage(self):
        c=self.configured()
        self.assertEqual(c.rendered,[(0,1),(1,1)])
        self.assertEqual(c.u(fx.ROWS+fx.R['charged']),1)
        self.assertEqual(c.u(fx.ROWS+fx.R['ignited']),0)
        self.assertEqual([c.u(a+0x9E4) for a in c.actors],[30000]*4)
        c.r[4]=fx.ROWS;run(c,fx.CHARGE)
        self.assertEqual(len(c.rendered),2)

    def test_fire_reuses_emitter_and_retires_native_charge_children(self):
        c=self.configured();node=c.u(fx.ROWS+fx.R['node'])
        c.rendered.clear();c.r[4]=fx.ROWS;run(c,fx.IGNITE)
        self.assertEqual(c.r[2],1)
        self.assertEqual([(i,flags&3) for i,flags in c.rendered],[(0,2),(2,1)])
        self.assertEqual(c.u(fx.ROWS+fx.R['node']),node)
        self.assertEqual(len(c.requests),1)
        c.r[4]=fx.ROWS;run(c,fx.IGNITE)
        self.assertEqual(len(c.rendered),2)

    def test_cancel_during_charge_stops_only_owned_node(self):
        c=self.configured();body=c.u(fx.ROWS+fx.R['body'])
        run(c,fx.STOP)
        self.assertTrue(c.u(body+1408)&2)
        self.assertEqual(c.u(fx.ROWS+fx.R['ignited']),0)

    def test_native_parent_keeps_updating_charge_children_as_hands_move(self):
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        c=self.configured();row=fx.ROWS;body=c.u(row+fx.R['body']);d=row+fx.DESC
        native=elf_reader(elf_path(ROOT))[2]
        for address,size in ((0x169F48,0x1C0),(0x14D7A0,0x108)):
            c.write(A(address),native(A(address),size))
        # The ordinary constructor admits firing(1,1). Our private extension
        # must also admit charge(0,0), otherwise native169F48 skips its anchor
        # updates and the glow remains at the pose used when it was created.
        c.w(body+32,1);c.w(body+36,1)
        self.assertEqual(c.u(body+1412),2)
        self.assertEqual(c.read(body+40,8),bytes(8))
        mask=0x3620000;c.w(d,mask);c.w(mask,1<<5)
        def no_new_animation_event(m):m.r[2]=0
        c.callbacks[A(0x14A8C0)]=no_new_animation_event
        c.rendered.clear()
        c.r[4:8]=[0,c.u(row+fx.R['node']),d,0]
        run(c,A(0x169F48))
        self.assertEqual(c.rendered,[(0,0x50),(1,0x50)])
        self.assertEqual(len(c.requests),1,'Following hands must not allocate another emitter')

    def test_fire_reselects_hand_once_after_charge_pose_changes(self):
        c=self.configured();model=c.models[0];row=fx.ROWS
        c.write(model+2416,struct.pack('<4f',0.,0.,0.,1.))
        c.write(c.u(c.models[1]+3436+17*4)+64,struct.pack('<4f',0.,0.,100.,1.))
        def hand(bone,z):c.write(c.u(model+3436+bone*4)+64,struct.pack('<4f',0.,0.,z,1.))
        hand(31,-10.);hand(45,10.)
        c.r[4]=row;run(c,fx.IGNITE)
        self.assertEqual(c.u(row+fx.R['source_bone']),45)
        body=c.u(row+fx.R['body'])
        self.assertEqual(c.u(body+64+16+64),45)
        self.assertEqual(c.read(body+1440,16),c.read(c.u(model+3436+45*4)+64,16))
        hand(31,20.);hand(45,-20.)
        c.r[4]=row;run(c,fx.IGNITE)
        self.assertEqual(c.u(row+fx.R['source_bone']),45,'Recoil must not swap hands every update')

    def test_scene_charges_before_firing_and_does_not_allocate_twice(self):
        for hz in (30,25):
            c=fixture(hz=hz);descriptor=assets.BASE;placement=assets.BASE+0x2000
            c.w(descriptor,180)
            c.w(descriptor+28,assets.CUSTOM_FINISHER|assets.BEAM_LEAD|assets.BEAM_PARTNER)
            c.w(scene.STATE+scene.S['placement'],placement);c.w(placement+8,90)
            calls=[]
            def record(name):
                def callback(m):calls.append((name,m.r[4]));m.r[2]=1
                return callback
            c.callbacks[fx.CHARGE_SPAWN]=record('charge')
            c.callbacks[fx.IGNITE]=record('fire')
            def tick(at):
                c.w(scene.STATE+scene.S['ticks'],at)
                c.r[17]=scene.STATE;c.r[19]=descriptor;run(c,scene.FX_BODY)
                self.assertEqual(c.r[2],1)
            tick(1);tick(math.ceil(90*hz/60)-1)
            self.assertEqual(calls,[('charge',0),('charge',1)])
            tick(math.ceil(90*hz/60));tick(math.ceil(90*hz/60)+1)
            self.assertEqual(calls,[('charge',0),('charge',1),('fire',fx.ROWS),('fire',fx.ROWS+fx.STRIDE)])
            self.assertEqual(c.beams,[],'No second emitter is allocated at fire')


if __name__=='__main__':unittest.main()
