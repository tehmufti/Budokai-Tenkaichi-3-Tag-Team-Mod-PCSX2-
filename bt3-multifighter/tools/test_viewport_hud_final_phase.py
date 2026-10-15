"""Regression for P2 texture corruption, real ki source, damage and co-op HUD."""
# Native execution tests require the developer's extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
_test_root = _TestPath(__file__).resolve().parents[1]
if not _test_elf_path(_test_root).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tests')
if not all((_test_root/'tools'/name).is_file() for name in
           ('test_viewport_hud.py','test_viewport_hud_layers.py')):
    raise _TestUnit.SkipTest('Developer HUD fixtures and execution helpers are required')

import struct
import unittest

import display_settings as display
import viewport_hud as hud
import viewport_hud_art as art
import test_viewport_hud as old
import test_viewport_hud_art as native
from prototype import ROOT,elf_reader


def final_machine(actual=False,coop=False,targets=False):
    c=native.machine(actual=actual)
    c.w(display.CONTROL,display.MAGIC);c.w(display.CONTROL+4,old.feed_test.MANAGER)
    c.w(display.CONTROL+display.FIELDS['hud'],1);c.w(hud.CONTROL+28,hud.POST_MAGIC)
    c.w(art.SETTINGS+12,int(targets))
    if coop:
        for off,value in ((0,hud.modes.MAGIC),(4,old.feed_test.MANAGER),(12,hud.modes.COOP),(24,99)):
            c.w(hud.modes.CONTROL+off,value)
    return c


def run(c,p):c.r[31]=0xFEED0000;c.run(p)


class FinalPhaseTests(unittest.TestCase):
    def test_world_passes_never_upload_hud_art_only_final_native_hud_phase_does(self):
        c=final_machine(actual=True);events=[]
        c.callbacks[hud.feed.DRAW]=lambda m:events.append('world')
        upload=c.callbacks[0x100738]
        c.callbacks[0x100738]=lambda m:(events.append('upload'),upload(m))
        for side in (0,1):
            for off,value in zip((512,516,520,524),hud.DEFAULT_VIEWS[side][1:5]):c.w(old.feed_test.CAMERA+off,value)
            run(c,hud.CODE)
        self.assertEqual(events,['world','world']);self.assertEqual(c.transfers,[])
        c.write(display.HUD_FILTER,display.hud_filter_code())
        c.write(display.HUD_DRAW_FILTER,display.hud_draw_filter_code())
        c.callbacks[display.HUD_ENTRY+8]=lambda m:events.append('native_hud')
        # The filter replays the native function's stack prologue; this callback
        # balances that original frame, as the native epilogue would.
        def native_root(m):events.append('native_hud');m.r[29]+=16
        c.callbacks[display.HUD_ENTRY+8]=native_root
        c.w(hud.hud_subject.CONTROL+hud.hud_subject.FIELDS['active'],1)
        root=0x500000;c.w(0x304270-22324,root);c.w(root,0x500100);c.w(root+8,0x500200)
        run(c,display.HUD_FILTER);c.r[4]=0x500100;run(c,display.HUD_DRAW_FILTER)
        self.assertEqual(events[:3],['world','world','native_hud']);self.assertIn('upload',events)
        count=len(c.transfers);run(c,display.HUD_DRAW_FILTER);self.assertEqual(len(c.transfers),count)
        # A new render (including pause) can draw again even at the same tick.
        run(c,display.HUD_FILTER);run(c,display.HUD_DRAW_FILTER);self.assertGreater(len(c.transfers),count)
        # Other root children, e.g. native clash prompts, are still traversed.
        c.callbacks[display.HUD_DRAW_ENTRY+8]=lambda m:(events.append('prompt'),setattr(m,'r',m.r[:29]+[m.r[29]+0xB0]+m.r[30:]))
        c.r[4]=0x500300;run(c,display.HUD_DRAW_FILTER);self.assertEqual(events[-1],'prompt')

    def test_coop_two_player_panels_or_four_target_panels_follow_actual_subjects(self):
        for targets,count in ((False,2),(True,4)):
            c=final_machine(coop=True,targets=targets);before=c.r.copy();run(c,hud.POST)
            self.assertEqual(c.r[2:31],before[2:31]);self.assertEqual((c.hi,c.lo),(123,456))
            portraits=[s for s in c.sprites if s[11]];self.assertEqual(len(portraits),count)
            self.assertEqual(portraits[0][0],c.u(old.feed_test.MODELS[4]+80))
            self.assertEqual(portraits[-1 if not targets else 2][0],c.u(old.feed_test.MODELS[2]+80))
            for s in c.sprites:self.assertTrue(0<=s[7]<=s[9]<=511)
            if not targets:
                self.assertGreater(portraits[0][9]-portraits[0][7],50)
                self.assertGreater(portraits[1][3],portraits[1][5])

    def test_damage_drains_current_bar_and_trail_then_healing_and_revive_reset_it(self):
        c=native.machine();actor=old.feed_test.ACTORS[4]
        # Past the first appearance's settle window, so the hit is damage rather than a new form's HP.
        c.w(actor+0x9E4,38000)
        for tick in range(art.SETTLE+1):c.w(hud.feed.CONTROL+12,tick);old.draw(c)
        c.sprites=[];c.w(actor+0x9E4,34000);c.w(hud.feed.CONTROL+12,art.SETTLE+1);old.draw(c)
        own=[s for s in c.sprites if s[3]<s[5]and s[1]==8 and s[3:5]==(0,0)]
        self.assertEqual([(s[2],s[5])for s in own],[(1,160),(0,160),(2,123),(1,64)])
        # Same fighter watched by a second panel must not advance the trail twice.
        at=art.METERS+24*4;trail=c.u(at+8);old.draw(c);self.assertEqual(c.u(at+8),trail)
        for tick in range(art.SETTLE+2,art.SETTLE+45):c.w(hud.feed.CONTROL+12,tick);old.draw(c)
        self.assertEqual(c.u(at+8),34000)
        c.w(actor+0x9E4,36000);old.draw(c);self.assertEqual(c.u(at+8),36000)
        c.w(actor+0x9E4,0);old.draw(c);self.assertEqual(c.u(at),0)
        c.w(actor+0x9E4,20000);old.draw(c);self.assertEqual(c.u(at+8),20000)

    def test_damage_trail_can_be_disabled_or_timed_in_native_battle_ticks(self):
        for ticks in (0,3,15,90):
            c=native.machine();actor=old.feed_test.ACTORS[4];at=art.METERS+24*4
            c.w(art.SETTINGS+16,ticks);c.w(actor+0x9E4,38000)
            for tick in range(art.SETTLE+1):c.w(hud.feed.CONTROL+12,tick);old.draw(c)
            c.w(actor+0x9E4,34000);c.sprites=[]
            for tick in range(art.SETTLE+1,art.SETTLE+max(1,ticks)+1):
                c.w(hud.feed.CONTROL+12,tick);old.draw(c)
                trail=c.u(at+8);old.draw(c);self.assertEqual(c.u(at+8),trail)
            self.assertEqual(c.u(at+8),34000,ticks)
            if not ticks:
                self.assertFalse(any(s[1:5]==(8,2,0,0)for s in c.sprites))

    def test_native_damage_palette_keeps_transparent_contour_including_unused_uv_rows(self):
        c=native.machine();table=c.u(c.hud_bundle+16);image=table+8*64
        def pixel(palette,x,y):
            # Same PSMT8 texture swizzle and CLUT CSM1 mapping used by the GS.
            at=(y&~15)*256+(x&~15)*2+((((y&~3)>>1)+(y&1))&7)*512+((x+(((y+2)>>2)&1)*4)&7)*4+((y>>1)&1)+((x>>2)&2)
            k=c.read(c.u(image+56)+96+at,1)[0];k=(k&0xE7)|((k&8)<<1)|((k&16)>>1)
            return c.read(c.u(table+(8+palette)*64+60)+96+4*k,4)
        for y in range(16):
            for x in range(160):self.assertEqual(pixel(1,x,y)[3],pixel(2,x,y)[3])
        for x,y in ((50,0),(50,3),(70,15),(120,13),(150,15)):
            self.assertEqual(pixel(2,x,y)[3],0,(x,y))
        # The tall part starts at the original UV step, not at an opaque box.
        self.assertGreater(pixel(2,70,0)[3],0)
        # Immutable native sprite record uses this exact flat-red palette.
        source=native.source();u=lambda p:struct.unpack_from('<I',source,p)[0]
        table=u(u(0x304270-0x5728)+4)
        self.assertEqual(struct.unpack_from('<2H',source,table+28+4),(8,2))

    def test_former_display_release_upgrades_without_losing_scores(self):
        c=old.feed_test.make();c.write(hud.bars.CODE,hud.bars.wrapper());c.write(hud.bars.DRAW,hud.bars.draw_code())
        c.write(display.HUD_ENTRY,display.HUD_ORIGINAL);c.write(display.HUD_DRAW_ENTRY,display.HUD_DRAW_ORIGINAL)
        ram=bytearray(0x8000000)
        for p,v in c.memory.items():ram[p]=v
        for b in display.build_memory(ram)['blocks']:
            p=b['address'];d=bytes.fromhex(b['data_hex']);ram[p:p+len(d)]=d
        for p,d in display.owned_pieces():ram[p:p+len(d)]=bytes(len(d))
        for p,d in display.owned_pieces(deferred=False):ram[p:p+len(d)]=d
        struct.pack_into('<I',ram,display.COUNTS+8,11)
        for b in display.build_memory(ram)['blocks']:
            p=b['address'];d=bytes.fromhex(b['data_hex']);ram[p:p+len(d)]=d
        self.assertEqual(struct.unpack_from('<I',ram,display.COUNTS+8)[0],11)
        self.assertEqual(display.build_memory(ram)['blocks'],[])

    def test_selected_native_row_overcharge_is_blue_and_stale_palette_is_reuploaded(self):
        c=final_machine(actual=True);actor=old.feed_test.ACTORS[4]
        c.w(actor+0x994,1);c.w(actor+0x9E4+164,30000);c.w(actor+0x9E4+164+12,100000);c.w(actor+0x9E4+164+28,22500)
        original=elf_reader(ROOT/'analysis/SLUS_216.78')[2]
        for p,n in ((0x20B588,0x38),(0x1CE1B8,0x20),(0x1CE050,0x18),(0x1CE030,0x20)):c.write(p,original(p,n))
        c.callbacks[0x1DC210]=lambda m:setattr(m,'r',m.r[:2]+[actor]+m.r[3:])
        run(c,0x20B588);self.assertEqual(c.r[2],22500)
        table=c.u(c.hud_bundle+16)
        for i in range(c.u(c.hud_bundle)):c.w(table+64*i+40,1)
        run(c,hud.POST)
        # Actual native upload executes; the blue CLUT is not trusted merely
        # because its flag survived a preceding world pass.
        blue=table+13*64
        self.assertIn(('image',c.u(blue+60),c.u(blue+12)),c.transfers)
        wanted_cbp=0x2C80+c.u(blue+36)
        tex0s=[struct.unpack_from('<Q',p,128)[0]for p in c.packets if len(p)==192]
        self.assertTrue(any((t>>37)&0x3FFF==wanted_cbp for t in tex0s))

    def test_previous_native_release_upgrades_exactly_preserving_options(self):
        c=old.captured_machine(split=True);c.write(hud.feed.WORLD,hud.feed.world_code())
        for b in hud.build_memory(c.buffer)['blocks']:c.write(b['address'],bytes.fromhex(b['data_hex']))
        for p,d in hud.pieces(hud.feed.DRAW):c.write(p,bytes(len(d)))
        for p,d in hud.pieces(hud.feed.DRAW,repaired=False):c.write(p,d)
        c.write(art.SETTINGS,struct.pack('<5I',0,1,0,0,0));c.w(hud.CONTROL+28,0);c.w(hud.CONTROL+20,99)
        for b in hud.build_memory(c.buffer)['blocks']:c.write(b['address'],bytes.fromhex(b['data_hex']))
        self.assertEqual(c.read(art.SETTINGS,16),struct.pack('<4I',0,1,0,0))
        self.assertEqual(c.u(hud.CONTROL+20),99);self.assertEqual(c.u(hud.CONTROL+28),hud.POST_MAGIC)
        self.assertEqual(hud.build_memory(c.buffer)['blocks'],[])


if __name__=='__main__':unittest.main()
