"""Execute the real native beam-hit request wrapper without rendering or damage."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest

import tag_rush_assets as assets
import tag_rush_effects as fx
import tag_rush_scene as scene
import test_tag_rush_effects as support
from native_map import A, elf_path
from prototype import ROOT, elf_reader
from test_tag_rush_camera import run


def machine():
    c=support.TagEffectsTests().impact_machine()
    c.write(fx.NATIVE_EXPLOSION,elf_reader(elf_path(ROOT))[2](fx.NATIVE_EXPLOSION,0x70))
    c.w(scene.STATE+scene.S['descriptor'],assets.BASE)
    c.w(assets.BASE+28,assets.FINISHER|assets.BEAM_LEAD|assets.BEAM_PARTNER)
    c.w(0x2450000+7208,0x2462000);c.w(0x2450000+7216,0x2463000)
    return c


def explode(c):
    c.r[4:6]=[2,17];run(c,fx.EXPLOSION);return c.r[2]


class ExplosionTests(unittest.TestCase):
    def test_native_beam_hit_copies_victim_position_and_leaves_combat_untouched(self):
        c=machine();actors=[c.read(p,0x1600)for p in c.actors]
        self.assertEqual(explode(c),1)
        self.assertEqual(len(c.requests),1)
        pool,callbacks,request=c.requests[0]
        self.assertEqual((pool,callbacks),(0x2440000,A(0x2C3F20)))
        self.assertEqual(struct.unpack_from('<Iff',request),(1,4.5,0.))
        victim=c.models[1];bone=c.u(victim+3436+17*4)
        self.assertEqual(request[16:32],c.read(bone+64,16))
        self.assertEqual(struct.unpack_from('<4I',request,48),(3,c.u(victim+16),0,0))
        self.assertEqual([c.read(p,0x1600)for p in c.actors],actors)

    def test_changed_phase_pool_or_actor_skips_visual(self):
        for kind in ('melee','not final','descriptor low','descriptor high','pool','empty',
                     'resource','retiring','actor','paused'):
            c=machine()
            if kind=='melee':c.w(assets.BASE+28,assets.FINISHER)
            elif kind=='not final':c.w(assets.BASE+28,assets.BEAM_LEAD)
            elif kind=='descriptor low':c.w(scene.STATE+scene.S['descriptor'],0x100000)
            elif kind=='descriptor high':c.w(scene.STATE+scene.S['descriptor'],assets.END-32)
            elif kind=='pool':c.w(c.r[28]-22512,0)
            elif kind=='empty':c.w(0x2440000+12,0)
            elif kind=='resource':c.w(0x2450000+7208,0)
            elif kind=='retiring':c.w(scene.STATE+scene.S['retiring'],1)
            elif kind=='actor':c.w(scene.ROWS+2*scene.STRIDE+scene.R['model'],0)
            elif kind=='paused':c.w(A(0x333700),1)
            self.assertEqual(explode(c),0,kind);self.assertFalse(c.requests,kind)

    def test_full_pool_does_not_allocate_elsewhere_or_damage_anyone(self):
        c=machine();c.callbacks[A(0x1AD7B8)]=lambda m:m.r.__setitem__(2,0)
        old=c.read(support.REGISTRY,156);hp=[c.u(p+0x9E4)for p in c.actors]
        self.assertEqual(explode(c),0)
        self.assertEqual(c.read(support.REGISTRY,156),old)
        self.assertEqual([c.u(p+0x9E4)for p in c.actors],hp)


if __name__=='__main__':unittest.main()
