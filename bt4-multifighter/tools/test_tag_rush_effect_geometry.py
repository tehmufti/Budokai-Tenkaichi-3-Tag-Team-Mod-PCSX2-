"""Real EE square-root operands and atomic native beam endpoint guards."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest

import tag_rush_effects as fx
from test_tag_rush_effects import machine,spawn,run


class EffectGeometryTests(unittest.TestCase):
    def points(self,c,source,target):
        row=fx.ROWS
        for model,bone,point in ((c.models[0],31,source),(c.models[1],17,target)):
            c.write(c.u(model+3436+bone*4)+64,struct.pack('<4f',*point,1.))
        return row

    def geometry(self,c,row):
        c.r[4]=row;run(c,fx.GEOMETRY);return c.r[2]

    def test_square_root_uses_ee_ft_operand_and_produces_a_unit_direction(self):
        square_roots=[word for word in struct.unpack('<'+'I'*(len(fx.geometry_code())//4),fx.geometry_code())
                      if word>>26==17 and word>>21&31==16 and word&63==4]
        self.assertEqual(len(square_roots),1)
        self.assertEqual((square_roots[0]>>16)&31,3)
        c=machine();self.points(c,(3.,-4.,5.),(103.,-304.,205.))
        self.assertEqual(spawn(c),1);direction=struct.unpack('<4f',c.read(fx.ROWS+fx.DIRECTION,16))
        magnitude=math.sqrt(100**2+300**2+200**2)
        for value,want in zip(direction[:3],(100/magnitude,-300/magnitude,200/magnitude)):
            self.assertAlmostEqual(value,want,places=6)
        self.assertEqual(direction[3],0.)

    def test_finite_corrupt_bone_positions_never_allocate_visuals_or_publish_geometry(self):
        for actor,bone in ((0,31),(1,17)):
            for axis in range(3):
                for value in (2.3016429740440867e38,-4.075005845421349e37,float('nan'),float('inf'),
                              fx.MAX_COORDINATE*2,-fx.MAX_COORDINATE*2):
                    c=machine();raw=c.read(fx.ROWS+fx.SOURCE,48)
                    c.fw(c.u(c.models[actor]+3436+bone*4)+64+4*axis,value)
                    self.assertEqual(spawn(c),0,(actor,axis,value))
                    self.assertEqual(c.requests,[])
                    self.assertEqual(c.read(fx.ROWS+fx.SOURCE,48),raw)

    def test_native_lookup_invalid_output_preserves_all_three_previous_vectors(self):
        for invalid_call in (0,1):
            for value in (2.3016429740440867e38,float('nan'),float('inf')):
                c=machine();self.assertEqual(spawn(c),1);row=fx.ROWS
                before=c.read(row+fx.SOURCE,48);ordinary=c.callbacks[fx.BONE];calls=[]
                def corrupt(m):
                    ordinary(m)
                    if len(calls)==invalid_call:m.fw(m.r[6],value)
                    calls.append(m.r[6])
                c.callbacks[fx.BONE]=corrupt
                self.assertEqual(self.geometry(c,row),0)
                self.assertEqual(len(calls),2)
                self.assertEqual(c.read(row+fx.SOURCE,48),before)

    def test_live_corrupt_target_stops_owned_parent_without_copying_bad_geometry(self):
        c=machine();self.assertEqual(spawn(c),1);row=fx.ROWS;body=c.u(row+fx.R['body'])
        before=[c.read(body+off,16)for off in (1376,1440,1456,1472)]
        c.fw(c.u(c.models[1]+3436+17*4)+64,2.3016429740440867e38)
        run(c,fx.UPDATE)
        self.assertEqual(c.u(row+fx.R['stopping']),1)
        self.assertTrue(c.u(body+1408)&2)
        self.assertEqual([c.read(body+off,16)for off in (1376,1440,1456,1472)],before)
        self.assertEqual(len(c.requests),1)

    def test_large_valid_positions_remain_finite_and_coincident_points_are_atomic(self):
        c=machine();self.points(c,(-fx.MAX_COORDINATE,fx.MAX_COORDINATE,0.),
                                (fx.MAX_COORDINATE,-fx.MAX_COORDINATE,fx.MAX_COORDINATE))
        self.assertEqual(spawn(c),1);row=fx.ROWS
        direction=struct.unpack('<4f',c.read(row+fx.DIRECTION,16))
        self.assertTrue(all(math.isfinite(v)for v in direction))
        self.assertAlmostEqual(sum(v*v for v in direction[:3]),1.,places=6)
        before=c.read(row+fx.SOURCE,48)
        self.points(c,(10.,-20.,30.),(10.,-20.,30.))
        self.assertEqual(self.geometry(c,row),0)
        self.assertEqual(c.read(row+fx.SOURCE,48),before)

    def test_geometry_preserves_full_register_fpu_and_condition_state(self):
        c=machine();self.assertEqual(spawn(c),1)
        for register in range(1,29):
            if register!=28:c.r[register]=((0xCAFE+register)<<96)|(register<<32)|register
        c.r[4]=fx.ROWS;c.condition=True;c.hi=0x1234;c.lo=0x5678
        old=list(c.r);fpu=list(c.f);run(c,fx.GEOMETRY)
        self.assertEqual(c.r[2],1)
        for register in (1,*range(3,29),30):self.assertEqual(c.r[register],old[register],register)
        self.assertEqual(c.f,fpu);self.assertTrue(c.condition)
        self.assertEqual((c.hi,c.lo),(0x1234,0x5678))


if __name__=='__main__':unittest.main()
