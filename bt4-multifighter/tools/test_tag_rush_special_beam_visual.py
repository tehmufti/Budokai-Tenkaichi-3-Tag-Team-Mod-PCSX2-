"""Execute the actual native SBC spiral dispatch and placement contract."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import math
import unittest
from pathlib import Path

from prototype import ROOT,elf_reader
from native_map import A,elf_path
import tag_rush_effects as fx
import tag_rush_special_beam as sbc
from test_tag_rush_effects import machine,spawn,run

ISO=ROOT.parent/'games'/('SLUS_219.78.DBZBT4B14REV2ENG.iso'
    if 'bt4' in str(Path(__file__)) else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')


class NativeSpiralTests(unittest.TestCase):
    def configured(self,flavor=1):
        c=machine();self.assertEqual(spawn(c),1)
        row=fx.ROWS;body=c.u(row+fx.R['body'])
        # The shared fake allocator authenticates ownership only. Native16A108
        # also copies request40's unit scale and14D6B0 seeds each rule'sscale.
        c.write(body+1420,struct.pack('<f',1.))
        c.write(body+656+0x168+12*4,struct.pack('<f',1.))
        c.w(row+fx.R['flavor'],flavor);c.w(row+fx.R['ignited'],0)
        run(c,fx.UPDATE)
        return c,row,body

    def test_selected_special_charge_publishes_muzzle_origin_before_ignition(self):
        c=machine();c.w(c.models[0]+12,22)
        c.write(fx.CHARGE_SPAWN,fx.spawn_code(charging=True,special=True))
        def select(m):m.r[2]=1;m.r[3]=1
        c.callbacks[sbc.SELECT]=select
        # Refuse the native SBC object: this pins the scoped private fallback.
        c.callbacks[sbc.NATIVE_SPAWN]=lambda m:m.r.__setitem__(2,0)
        c.r[4:6]=[0,90];run(c,fx.CHARGE_SPAWN)
        self.assertEqual(c.r[2],1);row=fx.ROWS;body=c.u(row+fx.R['body'])
        self.assertEqual(c.u(row+fx.R['flavor']),1)
        self.assertEqual(c.read(body+1456,16),c.read(row+fx.SOURCE,16))
        self.assertEqual(c.read(body+1472,16),c.read(row+fx.TARGET,16))

    def test_special_parent_fallback_origin_tracks_muzzle_while_target_stays_separate(self):
        for flavor in (0,1):
            c,row,body=self.configured(flavor)
            for source,target in (((5.,-25.,10.,1.),(120.,-25.,75.,1.)),
                                  ((10.,-30.,20.,1.),(200.,-60.,180.,1.))):
                c.write(c.u(c.models[0]+3436+31*4)+64,struct.pack('<4f',*source))
                c.write(c.u(c.models[1]+3436+17*4)+64,struct.pack('<4f',*target))
                run(c,fx.UPDATE)
                self.assertEqual(c.read(body+1440,16),struct.pack('<4f',*source))
                self.assertEqual(c.read(body+1456,16),struct.pack('<4f',*(source if flavor else target)))
                self.assertEqual(c.read(body+1472,16),struct.pack('<4f',*target))
                row_axis=struct.unpack('<4f',c.read(row+fx.DIRECTION,16))
                self.assertEqual(struct.unpack('<4f',c.read(body+1376,16)),
                    tuple((-value if flavor and index<3 else value)for index,value in enumerate(row_axis)))

    def test_fire_rebinding_keeps_special_spiral_at_new_firing_hand(self):
        c,row,body=self.configured();c.w(row+fx.R['charged'],1)
        target=struct.pack('<4f',0.,0.,100.,1.)
        c.write(c.models[0]+2416,struct.pack('<4f',0.,0.,0.,1.))
        c.write(c.u(c.models[1]+3436+17*4)+64,target)
        for bone,z in ((31,-10.),(45,10.)):
            c.write(c.u(c.models[0]+3436+bone*4)+64,struct.pack('<4f',0.,-10.,z,1.))
        c.r[4]=row;run(c,fx.IGNITE)
        self.assertEqual(c.r[2],1)
        self.assertEqual(c.u(row+fx.R['source_bone']),45)
        self.assertEqual(c.read(body+1456,16),c.read(row+fx.SOURCE,16))
        self.assertEqual(c.read(body+1472,16),target)

    def test_special_firing_scale_fits_distance_but_charge_and_other_beams_keep_native_size(self):
        for flavor in (0,1):
            for target in ((0.,-31.,10.,1.),(0.,-31.,40.,1.),(30.,-31.,40.,1.),(0.,-31.,1000.,1.)):
                c,row,body=self.configured(flavor)
                c.write(c.u(c.models[1]+3436+17*4)+64,struct.pack('<4f',*target))
                run(c,fx.UPDATE)
                self.assertEqual(struct.unpack('<f',c.read(body+1420,4))[0],1.)
                c.r[4]=row;run(c,fx.IGNITE);self.assertEqual(c.r[2],1)
                expected=(max(.025,min(.20,math.hypot(target[0],target[2])/600.)) if flavor else 1.)
                self.assertAlmostEqual(struct.unpack('<f',c.read(body+1420,4))[0],expected,places=6)
                c.write(c.u(c.models[1]+3436+17*4)+64,struct.pack('<4f',0.,-31.,60.,1.))
                run(c,fx.UPDATE)
                self.assertAlmostEqual(struct.unpack('<f',c.read(body+1420,4))[0],.1 if flavor else 1.,places=6)

    def test_scale_reference_matches_native_spiral_opacity_and_velocity(self):
        if not ISO.is_file():self.skipTest('Reviewed local disc unavailable')
        from model_assets import package_entry
        resource=sbc.build_assets(ISO)['blocks'][0][1][:sbc.RESOURCE_SIZE]
        command=package_entry(resource,32)
        value=lambda off:struct.unpack_from('<f',command,off)[0]
        #194678 maps raw60 tochild2B4;191498 maps it toparticle108. Raw22C
        #is particle104.191D28 advances by their product (60units/update).
        velocity=value(0x60)*value(0x22c)
        lifetime=30.*value(0x1f4)
        fade_in=lifetime*value(0x218)
        self.assertEqual(velocity,60.)
        self.assertEqual(velocity*(math.ceil(fade_in)+1),fx.SBC_OPAQUE_TRAVEL)

    def test_real_spiral_rule_uses_native_source_fallback_and_original_orientation(self):
        if not ISO.is_file():self.skipTest('Reviewed local disc unavailable')
        c,row,body=self.configured()
        plan=sbc.build_assets(ISO)
        for address,data in plan['blocks']:c.write(address,data)
        desc=row+fx.DESC
        c.w(desc+8,sbc.RESOURCE+plan['script_offset']+320)
        # The native resource's group9 spiral rule12 uses selector5. That
        # selector maps to -1, so 14FF90 must use its emitter point, not any
        # of the hand-bound contexts. Execute those actual native branches.
        c.w(desc+12+16*9,sbc.RESOURCE+plan['script_offset']+64+32*2)
        c.write(desc+20+16*9,b'\x0c')
        native=elf_reader(elf_path(ROOT))[2]
        for address,size in ((0x14FF50,0xC04),(0x2C37E8,28),(0x2EC990,24),(0x2EC9B0,76)):
            c.write(A(address),native(A(address),size))
        self.assertEqual(struct.unpack('<i',c.read(A(0x2C37E8)+5*4,4))[0],-1)
        del c.callbacks[A(0x14FF50)]
        c.callbacks[A(0x121FA8)]=lambda m:m.write(m.r[4],m.read(m.r[5],16))
        def scale(m):
            point=struct.unpack('<4f',m.read(m.r[5],16))
            m.write(m.r[4],struct.pack('<4f',*(v*m.number(12)for v in point)))
        c.callbacks[A(0x121F50)]=scale
        emitted=[]
        def spiral(m):
            emitted.append((m.r[4],m.r[6],m.r[9],m.read(m.r[10],16),m.read(m.r[11],16),m.number(12)))
        c.callbacks[A(0x14F230)]=spiral
        c.r[4]=row;run(c,fx.IGNITE)
        self.assertEqual(c.r[2],1);self.assertEqual(len(emitted),1)
        descriptor,flags,rule,origin,direction,scale=emitted[0]
        self.assertEqual((descriptor,flags&1,rule),(desc,1,0))
        self.assertEqual(origin,c.read(row+fx.SOURCE,16))
        self.assertNotEqual(origin,c.read(row+fx.TARGET,16))
        # The real rule reverses its native parent axis. Supply that backward
        # parent axis so the original spiral finally travels toward the target.
        self.assertEqual(struct.unpack('<4f',direction),struct.unpack('<4f',c.read(row+fx.DIRECTION,16)))
        source,target=struct.unpack('<4f',origin),struct.unpack('<4f',c.read(row+fx.TARGET,16))
        self.assertAlmostEqual(scale,min(.2,max(.025,math.dist(source[:3],target[:3])/600.)),places=6)


if __name__=='__main__':unittest.main()
