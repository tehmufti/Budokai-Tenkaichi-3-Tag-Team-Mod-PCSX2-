"""Execute the selected disc's real retargeter with the packaged donor data."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

from pathlib import Path
import math
import struct
import unittest

from native_map import A, SERIAL, elf_path
from prototype import ROOT, elf_reader
import model_animations as animations
import tag_rush_assets as assets
from test_extra_special_pools import Cpu


class NativeRetargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = ('SLUS_219.78.DBZBT4B14REV2ENG.iso' if SERIAL == 'SLUS-21978'
                else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        cls.iso = ROOT.parent/'games'/name
        if not cls.iso.is_file() or not elf_path(ROOT).is_file():
            raise unittest.SkipTest('The selected game disc and executable are required')
        cls.native = staticmethod(elf_reader(elf_path(ROOT))[2])
        cls.bindings = assets.read_donor_bindings(cls.iso)
        cls.recipient = assets.read_skeleton(cls.iso, 0)
        cls.clips = assets.read_clips(cls.iso)

    def machine(self, donor_character, raw):
        c = Cpu({'segments': []})
        c.write(A(0x24BBE8), self.native(A(0x24BBE8), 0x370))
        c.write(A(0x250570), self.native(A(0x250570), 0x60))
        recipient_bytes, recipients, _ = assets.pack_donor_bindings(
            {101: self.recipient, 102: self.recipient}, 0x5000000)
        donor_bytes, donors, _ = assets.pack_donor_bindings(self.bindings, 0x5100000)
        c.write(0x5000000, recipient_bytes); c.write(0x5100000, donor_bytes)
        scratch = 0x5200000
        c.write(scratch, raw)
        c.r[4:9] = [scratch, recipients[101], donors[donor_character], 0, 0]
        c.r[31] = 0xFEED0000
        return c, scratch

    def test_both_native_height_layouts_are_populated_for_every_donor(self):
        data, models, _ = assets.pack_donor_bindings(self.bindings, 0x5000000)
        for character, model in models.items():
            at = model-0x5000000
            original = struct.unpack_from('<I', data, at+2332)[0]-0x5000000+4
            bt4 = struct.unpack_from('<I', data, at+24)[0]-0x5000000+0x74
            self.assertGreaterEqual(bt4, at)
            self.assertLess(bt4, at+0x920)
            self.assertEqual(struct.unpack_from('<f', data, original), struct.unpack_from('<f', data, bt4))
            self.assertAlmostEqual(struct.unpack_from('<f', data, bt4)[0], self.bindings[character]['height'])

    def test_native_startup_and_partner_retarget_match_finite_bind_reference(self):
        for source in (assets.ClipSource(101,363), assets.PARTNER[414]):
            with self.subTest(source=source):
                raw = self.clips[source]
                c, scratch = self.machine(source.character, raw)
                c.run(A(0x24BBE8))
                result = animations.AnimationClip.from_decoded(source.animation, c.read(scratch, len(raw)))
                original = animations.AnimationClip.from_decoded(source.animation, raw)
                donor = {row['bone']: row['translation'] for row in self.bindings[source.character]['rows']}
                recipient = {row['bone']: row['translation'] for row in self.recipient['rows']}
                ratio = self.recipient['height']/self.bindings[source.character]['height']
                for before, after in zip(original.tracks, result.tracks):
                    if before.bone_id not in donor or before.bone_id not in recipient:
                        continue
                    for left, right in zip(before.keys, after.keys):
                        if left.translation is None:
                            continue
                        self.assertTrue(all(math.isfinite(v) and abs(v)<10000 for v in right.translation))
                        for axis in range(3):
                            expected = ((left.translation[axis]-donor[before.bone_id][axis])
                                        *(ratio if axis == 1 else 1)+recipient[before.bone_id][axis])
                            self.assertAlmostEqual(right.translation[axis], expected, delta=0.0002)

    def test_selected_native_height_loads_are_the_reviewed_layout(self):
        instructions = struct.unpack('<3I', self.native(A(0x24BC78), 12))
        expected = ((0x8EE30018,0xC4410074,0xC4600074) if SERIAL == 'SLUS-21978'
                    else (0x8EE3091C,0xC4410004,0xC4600004))
        self.assertEqual(instructions, expected)


if __name__ == '__main__':
    unittest.main()
