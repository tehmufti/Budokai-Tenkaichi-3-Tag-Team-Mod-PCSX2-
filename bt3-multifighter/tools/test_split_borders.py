"""Pixel coverage and actual emitted border packets for native/quad layouts."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
from unittest.mock import patch
import split_borders as border
import quad_viewports as quad
import viewport_hud as hud
import guest_healthbars as bars
from test_viewport_hud import Cpu as HudCpu
from test_terrain_crossing_guard import ScalarMips

MANAGER,CAMERA,PACKETS=0x1900000,0x2400000,0x2500000


class Cpu(ScalarMips,HudCpu):
    pass


def machine(rect=None):
    c=Cpu({'segments':[]});c.hi=0x123;c.lo=0x456
    for p,b in ((border.CODE,border.code()),(hud.SCISSOR,hud.scissor_code()),
                (bars.RECT,bars.rectangle_code()),(bars.TEMPLATE,bars.sprite_template()),
                (quad.MATTE,quad.matte())):c.write(p,b)
    c.w(c.r[28]-22364,MANAGER);c.w(MANAGER,2)
    c.write(border.core.MODE,struct.pack('<4I',1,4,MANAGER,4))
    c.write(hud.CONTROL,struct.pack('<3I',hud.MAGIC,MANAGER,1))
    c.w(c.r[28]-22176,CAMERA);c.w(CAMERA+640,1)
    c.write(CAMERA+512,struct.pack('<4I',*(rect or quad.TWO_RECTS[1])))
    c.packets=[];c.calls=[];c.r[31]=0xFEED0000
    def native(m):
        m.calls.append('native');m.r[2]=0x1234;m.r[3]=0x5678
    c.callbacks[border.NATIVE]=native
    c.callbacks[border.A(0x100878)]=lambda m:m.r.__setitem__(2,PACKETS)
    def submit(m):m.packets.append(m.read(PACKETS,m.r[4]-PACKETS))
    c.callbacks[border.A(0x100890)]=submit
    c.callbacks[quad.A(0x101400)]=lambda m:m.calls.append(('scissor',tuple(m.r[4:8])))
    return c


def rectangles(packets):
    result=[]
    for packet in packets:
        if len(packet)!=128:continue
        x0,y0=struct.unpack_from('<HH',packet,112);x1,y1=struct.unpack_from('<HH',packet,120)
        result.append((x0//16-1792,y0//16-border.Y_ORIGIN,x1//16-1792,y1//16-border.Y_ORIGIN))
    return result


class SplitBorderTests(unittest.TestCase):
    def test_trainer_installs_border_after_hud_and_multiview_for_all_multiplayer_modes(self):
        import ast,inspect,textwrap
        import fresh_team_trainer as trainer
        tree=ast.parse(textwrap.dedent(inspect.getsource(trainer.final_team_manifest)))
        rows=sorted((node.lineno,node.body.func.value.id) for node in ast.walk(tree)
                    if isinstance(node,ast.Lambda) and isinstance(node.body,ast.Call)
                    and isinstance(node.body.func,ast.Attribute) and isinstance(node.body.func.value,ast.Name))
        names=[name for _,name in rows]
        self.assertEqual(names.count('split_borders'),1)
        self.assertLess(names.index('viewport_hud'),names.index('split_borders'))
        self.assertLess(names.index('four_player_mode'),names.index('split_borders'))
        guards=[node for node in ast.walk(tree) if isinstance(node,ast.If)
                and any(isinstance(child,ast.Name) and child.id=='split_borders' for body in node.body for child in ast.walk(body))]
        self.assertEqual([ast.unparse(node.test) for node in guards],['humans >= 2'])

    def test_actual_trainer_composition_selects_native_border_builder_only_for_multiplayer(self):
        import fresh_team_trainer as trainer
        calls=[]
        def compose(ram,builders):
            for builder in builders:
                if 'split_borders' in builder.__code__.co_freevars:builder(ram)
            return {'blocks':[]}
        with patch.object(trainer.battle_mode_policy,'known_capacity',return_value=None), \
                patch.object(trainer,'compose_manifests',side_effect=compose), \
                patch.object(border,'build_memory',side_effect=lambda ram:calls.append(ram) or {'blocks':[]}):
            for mode in ('teams','ffa','training','coop','training_coop'):
                for humans in ((2,3,4) if 'coop' in mode else (1,2,3,4)):
                    calls.clear()
                    trainer.final_team_manifest(bytes(32),{'blocks':[]},'border composition',battle_mode=mode,humans=humans)
                    self.assertEqual(len(calls),int(humans>=2),(mode,humans))

    def test_mattes_cover_exactly_unoccupied_pixels_on_ntsc_and_pal(self):
        for height in (448,512):
            with patch.multiple(quad,DISPLAY_H=height,TOP_LAST=height//2-2,BOTTOM_FIRST=height//2+1):
                for humans in (2,3,4):
                    upper=height if humans==2 else height//2-1
                    views=[(0,0,255,upper),(257,0,512,upper)]
                    if humans==3:views.append((128,height//2+1,383,height))
                    if humans==4:views.extend(((0,height//2+1,255,height),(257,height//2+1,512,height)))
                    for y in range(height):
                        rendered={x for l,t,r,b in views if t<=y<b for x in range(l,r)}
                        matte={x for l,t,r,b in quad.matte_rectangles(humans) if t<=y<b for x in range(l,r)}
                        self.assertFalse(rendered&matte,(humans,height,y))
                        self.assertEqual(rendered|matte,set(range(512)),(humans,height,y))

    def test_emitted_quad_matte_draws_once_without_mutating_view_templates(self):
        for humans in (2,3,4):
            c=machine();c.w(quad.CONTROL+quad.VIEW_COUNT,humans)
            before=c.read(CAMERA,656);c.run(quad.MATTE)
            self.assertEqual(rectangles(c.packets),list(quad.matte_rectangles(humans)))
            self.assertEqual(c.calls,[('scissor',(0,511,0,quad.SCISSOR_Y1))])
            self.assertTrue(all(struct.unpack_from('<I',p,80)[0]==0x80000000 for p in c.packets))
            self.assertEqual(c.read(CAMERA,656),before)

    def test_native_two_view_draws_after_effects_and_preserves_native_result(self):
        for rect in quad.TWO_RECTS:
            c=machine(rect);c.run(border.CODE)
            self.assertEqual(c.calls,['native'])
            self.assertEqual(rectangles(c.packets),[(255,0,257,border.DISPLAY_H)])
            self.assertEqual(len(c.packets),2)
            self.assertEqual(struct.unpack_from('<Q',c.packets[0],16)[0],511<<16|border.SCISSOR_Y1<<48)
            self.assertEqual(c.r[2:4],[0x1234,0x5678]);self.assertEqual((c.hi,c.lo),(0x123,0x456))

    def test_shared_cinematics_and_foreign_or_short_views_get_no_separator(self):
        for case in ('full','quarter','splitoff','stale','no_hud','no_match'):
            c=machine()
            if case=='full':c.write(CAMERA+512,struct.pack('<4I',0,511,0,border.SCISSOR_Y1))
            elif case=='quarter':c.w(CAMERA+524,quad.TOP_LAST)
            elif case=='splitoff':c.w(CAMERA+640,0)
            elif case=='stale':c.w(hud.CONTROL+4,MANAGER+4)
            elif case=='no_hud':c.w(hud.CONTROL,0)
            else:c.w(border.core.MODE+4,0)
            c.run(border.CODE)
            self.assertEqual(c.calls,['native'],case);self.assertFalse(c.packets,case)

    def test_install_authenticates_predecessor_dependencies_and_code_gap(self):
        ram=bytearray(0x8000000)
        def put(p,b):ram[p:p+len(b)]=b
        put(border.core.ACTORS,struct.pack('<I',MANAGER))
        put(MANAGER,struct.pack('<I',2))
        put(border.core.MODE,struct.pack('<4I',1,4,MANAGER,4))
        put(hud.CONTROL,struct.pack('<3I',hud.MAGIC,MANAGER,1))
        for p,b in ((hud.SCISSOR,hud.scissor_code()),(bars.RECT,bars.rectangle_code()),
                    (bars.TEMPLATE,bars.sprite_template()),(border.HOOK,border.ORIGINAL)):put(p,b)
        plan=border.build_memory(ram);self.assertEqual(len(plan['blocks']),2)
        self.assertEqual(quad.NATIVE(border.HOOK,8),border.ORIGINAL)
        ram[border.CODE]=1
        with self.assertRaisesRegex(ValueError,'reservation'):border.build_memory(ram)
        ram[border.CODE]=0;ram[border.HOOK]^=1
        with self.assertRaisesRegex(ValueError,'overlay call'):border.build_memory(ram)
        ram[border.HOOK]^=1
        ram[border.HOOK+4]=1
        with self.assertRaisesRegex(ValueError,'overlay call'):border.build_memory(ram)
        ram[border.HOOK+4]=0
        for block in plan['blocks']:put(block['address'],bytes.fromhex(block['data_hex']))
        self.assertFalse(border.build_memory(ram)['blocks'])
        ram[bars.TEMPLATE]^=1
        with self.assertRaisesRegex(ValueError,'GS dependency'):border.build_memory(ram)


if __name__=='__main__':unittest.main()
