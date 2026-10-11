"""Ordinary regional hooks build without arming the unsupported tag director."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import os
from pathlib import Path
import subprocess
import sys
import unittest


class DormantTagImports(unittest.TestCase):
    def test_normal_pal_and_japanese_hooks_do_not_require_tag_effect_mappings(self):
        analysis=Path(__file__).resolve().parent.parent/'analysis'
        if not all((analysis/name).is_file() for name in ('SLES_549.45','SLPS_258.15')):
            self.skipTest('Regional native executables are not present in this adapter tree')
        source='''import sys
import inactive_actor_guard as guard, cinematic_policy as cinema
import quad_viewports as quad, guest_killfeed as feed, viewport_hud as hud
import story_rules as rules, story_missions as story, split_borders as borders
from native_map import A,elf_path
from prototype import ROOT,elf_reader
from prototype import Assembler
from test_ai_shadow import Mips
import tag_rush_camera as tag_camera,tag_rush_safety as tag_safety
assert guard.code()
assert cinema.program(participants=True)
assert cinema.selector(quad_support=True)
assert quad.pieces()
assert feed.damage_code()
assert hud.pieces(feed.DRAW)
assert rules.damage_code(story.default_mission())
assert borders.code()
native=elf_reader(elf_path(ROOT))[2]
assert native(borders.HOOK,8)==borders.ORIGINAL
draw=native(A(0x12B9C0),0x300)
assert [i for i in range(0,len(draw)-8,4) if draw[i:i+8]==borders.ORIGINAL]==[0x154]
# With no tag payload installed, these inlined probes must reject before
# calling any absent tag code, even when the damage return address matches.
for kind in ('camera','shared','damage'):
    a=Assembler(0x60000)
    if kind=='camera':tag_camera.emit_camera(a,2,16,'dormant','probe')
    elif kind=='shared':
        tag_camera.emit_shared(a,'unexpected','probe');a.jump('dormant');a.label('unexpected')
    else:
        a.li(12,tag_safety.DAMAGE_RETURN)
        tag_safety.emit_damage_attacker(a,4,4,12,'dormant','probe')
    a.li(2,1);a.jr();a.label('dormant');a.li(2,0);a.jr()
    cpu=Mips({'segments':[dict(address=0x60000,data_hex=a.finish().hex())]})
    cpu.run(0x60000);assert cpu.r[2]==0
assert 'tag_rush_scene' not in sys.modules
assert 'tag_rush_effects' not in sys.modules
'''
        for adapter in ('bt3-pal','bt3-jpn'):
            env=dict(os.environ,TAGTEAM_ADAPTER=adapter)
            result=subprocess.run([sys.executable,'-c',source],cwd=Path(__file__).parent,env=env,
                                  capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,adapter+' '+result.stderr)


if __name__=='__main__':unittest.main()
