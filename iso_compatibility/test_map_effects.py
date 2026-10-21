"""World-position scaling without changing particle recipes or light vectors."""
import struct
import unittest
from .disc import Disc, FormatError, package, u32
from .adapters import identify
from .map_scaling import ScalePlan, _ambient_and_paths, plan_stage
from . import test_map_liquids as liquids


class EffectScalingTests(unittest.TestCase):
    def test_emitters_and_paths_preserve_non_position_data(self):
        raw=bytearray(240)
        struct.pack_into('<4s7I',raw,0,b'MEF0',0,1,32,0,80,0,80)
        struct.pack_into('<12f',raw,32,*range(1,13))
        struct.pack_into('<5I',raw,96,0,0,1,32,0)
        struct.pack_into('<4I',raw,128,2,48,0,0)
        for p in (144,192):struct.pack_into('<12f',raw,p,*range(1,13))
        entries=[(0,0)]*24;entries[18]=(0,80);entries[23]=(96,240)
        plan=ScalePlan(raw,2);_ambient_and_paths(plan,entries);out=plan.preview()
        self.assertEqual(len(plan.fields),9)
        for p in (32,144,192):
            self.assertEqual(struct.unpack_from('<3f',out,p),(2,4,6))
            self.assertEqual(out[p+12:p+48],raw[p+12:p+48])
        struct.pack_into('<I',raw,132,4)
        with self.assertRaises(FormatError):_ambient_and_paths(ScalePlan(raw,2),entries)

    def test_all_disc_effect_origins_and_lighting(self):
        count=emitters=paths=0
        rejected=set()
        for iso in liquids.DiscLiquidTests().discs():
            with Disc(iso) as disc:
                adapter,_=identify(disc)
                for base in (adapter.stage_base,adapter.split_stage_base):
                    for sid in range(adapter.stage_count):
                        raw=disc.read(base+sid)
                        try:entries=package(raw)
                        except FormatError:continue
                        # Only real stage resources, including optional BT4 slots.
                        if len(entries)<2 or u32(raw,entries[0][0])!=18:continue
                        with self.subTest(disc=iso.name,stage=sid,base=base):
                            # Check the independently loaded effects even on
                            # arenas whose terrain cannot safely be converted.
                            effects=ScalePlan(raw,2);_ambient_and_paths(effects,entries)
                            try:plan=plan_stage(raw,2)
                            except FormatError as error:
                                # These shipped BT4 object-collision tables
                                # already fail the bounded terrain decoder.
                                # The builder keeps both view variants native.
                                self.assertTrue(adapter.name.startswith('bt4-'))
                                self.assertIn(sid,(11,23,46,58))
                                self.assertIn(str(error),('Excessive collision vertex index',
                                                         'Collision child outside tree'))
                                rejected.add(sid)
                                continue
                            out=plan.preview();count+=1
                            emitters+=plan.categories['ambient_emitter_position']
                            paths+=plan.categories['stage_path_position']
                            a,b=entries[1];d=raw[a:b]
                            for row in range(u32(d,28),u32(d,28)+32*u32(d,24),32):
                                self.assertEqual(raw[a+row:a+row+32],out[a+row:a+row+32])
        self.assertGreater(count,100)
        self.assertGreater(emitters,0)
        self.assertGreater(paths,0)


if __name__=='__main__':unittest.main()
