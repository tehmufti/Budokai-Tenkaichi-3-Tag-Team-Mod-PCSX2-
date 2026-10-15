"""Offline resident-art render execution and original native texture-upload path."""
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

import functools
import struct
import unittest
from camera_snapshot import read_ram
from prototype import ROOT,elf_reader
import viewport_hud_art as art
import viewport_hud as hud
import test_viewport_hud as old


@functools.lru_cache(maxsize=1)
def source():return read_ram(ROOT/'runtime128/sstates/SLUS-21678 (428113C2).215.p2s')


class Cpu(old.Cpu):
    def extra_instruction(self,ins,pc):
        op,rs,rt,rd,shift=ins>>26,(ins>>21)&31,(ins>>16)&31,(ins>>11)&31,(ins>>6)&31
        if op in (26,27,44,45):
            off=ins&65535;off=off if off<32768 else off-65536;p=self.r[rs]+off
            assert p&7==(7 if op in (26,44)else 0);p&=~7
            if op in (26,27):self.r[rt]=int.from_bytes(self.read(p,8),'little')
            else:self.write(p,(self.r[rt]&0xffffffffffffffff).to_bytes(8,'little'))
            return
        if op==0 and ins&63 in (0x38,0x3C,0x3E,0x3F):
            fn=ins&63
            if fn in (0x38,0x3C):self.r[rd]=(self.r[rt]<<(shift+(32 if fn==0x3C else 0)))&0xffffffffffffffff
            elif fn==0x3E:self.r[rd]=(self.r[rt]&0xffffffffffffffff)>>(shift+32)
            else:
                v=self.r[rt]&0xffffffffffffffff;v=v-(1<<64)if v&(1<<63)else v
                self.r[rd]=(v>>(shift+32))&0xffffffffffffffff
            return
        return super().extra_instruction(ins,pc)


def machine(side=0,actual=False):
    c=old.machine(side,actual_packets=actual);c.__class__=Cpu
    c.sprites=[];c.transfers=[];s=source();u=lambda p:struct.unpack_from('<I',s,p)[0]
    def copy(p,n):c.write(p,s[p:p+n])
    def bundle(b):
        copy(b,32);table=u(b+16);copy(table,64*u(b))
        for i in range(u(b)):
            d=table+64*i
            for size_off,pointer_off in ((8,56),(12,60)):
                size=u(d+size_off)
                if size:copy(u(d+pointer_off),size)
    manager=u(0x304270-0x5728);copy(manager,0x200);c.w(0x304270-0x5728,manager)
    bundle(u(manager));c.hud_bundle=u(manager)
    for i,m in enumerate(old.feed_test.MODELS):
        native_model=u(hud.core.MODELS+4*old.feed_test.MODEL_IDS[i])
        b=u(native_model+80)
        # The capture may use different model IDs: use either native leader's
        # actual resident portrait for an absent test mapping, never guessed art.
        if not 0x100000<b<0x8000000:b=u(u(manager+0x1F0+4*(i&1))+80)
        bundle(b);c.w(m+80,b)
    for p,d in art.pieces():c.write(p,d)
    c.write(hud.PANEL,art.dispatch());c.write(art.SETTINGS,art.settings_data())
    native=elf_reader(ROOT/'analysis/SLUS_216.78')[2]
    for p,n in ((art.UPLOAD,0x1C8),(art.INVALIDATE,0x48),(0x2F1DD0,0x30)):c.write(p,native(p,n))
    if actual:
        def dma(m):c.transfers.append(('packet',m.read(m.r[4],m.r[5])))
        def image(m):c.transfers.append(('image',m.r[4],m.r[5]))
        c.callbacks[0x1006E8]=dma;c.callbacks[0x100738]=image
    else:
        c.subpixel_sprites=[]
        c.callbacks[hud.A(0x225790)]=lambda m:None
        def capture_sprite(m):
            row=list(struct.unpack('<13I',m.read(m.r[4],52)))
            if row[11]&2:
                m.subpixel_sprites.append(tuple(row))
                row[7:11]=[v//16 for v in row[7:11]]
                row[11]&=1
            m.sprites.append(tuple(row))
        c.callbacks[art.SPRITE]=capture_sprite
    return c


class NativeHudArtTests(unittest.TestCase):
    def test_four_view_native_art_stays_inside_the_matching_view(self):
        c=machine();views=((1,0,254,0,222,hud.camera.SUCCESSOR_CONTROL+8),
                          (1,257,511,0,222,hud.camera.SUCCESSOR_CONTROL+12),
                          (1,0,254,225,447,hud.CONTROL+40),
                          (1,257,511,225,447,hud.CONTROL+44))
        c.w(hud.CONTROL+12,4);c.w(hud.CONTROL+40,0);c.w(hud.CONTROL+44,5)
        c.w(hud.core.TABLE+20,3);c.write(hud.VIEWS,b''.join(struct.pack('<6I',*v)for v in views))
        for off,value in zip((512,516,520,524),views[3][1:5]):c.w(old.feed_test.CAMERA+off,value)
        old.draw(c);self.assertTrue(c.sprites)
        for s in c.sprites:
            self.assertGreaterEqual(s[7],257);self.assertLessEqual(s[9],511)
            self.assertGreaterEqual(s[8],225);self.assertLessEqual(s[10],447)

    def test_real_resident_frame_portrait_and_gauges_preserve_registers_and_fit_both_halves(self):
        for side in (0,1):
            c=machine(side);before=c.r.copy();old.draw(c)
            self.assertEqual(c.r,before);self.assertEqual((c.hi,c.lo),(123,456))
            self.assertTrue(any(s[1]==6 for s in c.sprites))
            self.assertEqual(sum(bool(s[11])for s in c.sprites),2)
            x0,x1,y0,y1=hud.DEFAULT_VIEWS[side][1:5]
            for s in c.sprites:
                self.assertLessEqual(x0,s[7]);self.assertLessEqual(s[9],x1)
                self.assertLessEqual(y0,s[8]);self.assertLessEqual(s[10],y1)
            self.assertTrue(any(s[3]>s[5]for s in c.sprites))

    def test_hp_pips_and_exact_layer_boundaries_follow_native_rules(self):
        for hp,pips,palette,end in ((0,0,None,None),(1,0,3,3),(10000,0,3,160),
                                    (10200,1,4,3),(25000,2,1,80),(80000,6,5,160)):
            c=machine();c.w(old.feed_test.ACTORS[4]+0x9E4,hp);old.draw(c)
            own=[s for s in c.sprites if s[3]<s[5]]
            hp_sprites=[s for s in own if s[1]==8 and s[3:5]==(0,0)]
            count=sum(s[1]==8 and s[3:7]==(0,16,16,32)for s in own)
            self.assertEqual(count,pips,hp)
            if hp:self.assertEqual((hp_sprites[-1][2],hp_sprites[-1][5]),(palette,end),hp)
            else:self.assertEqual(hp_sprites,[])

    def test_normal_ki_sparking_overfill_stock_fraction_and_options(self):
        actor=old.feed_test.ACTORS[4]
        for ki,charge,yellow,blue in ((0,0,0,0),(10000,0,1,0),(100000,0,5,0),(100000,15000,5,3),(100000,30000,5,5),(150000,0,5,0)):
            c=machine();c.w(actor+0x9E4+12,ki);c.w(actor+0x9E4+28,charge);c.w(actor+0x9E4+20,350000);old.draw(c)
            own=[s for s in c.sprites if s[3]<s[5]]
            for palette,count in ((1,yellow),(5,blue)):
                self.assertEqual(sum(s[1:4]==(8,palette,16)for s in own),count,ki)
            stock=[s for s in own if s[1:5]==(8,1,161,0)][0]
            self.assertEqual(stock[5],174)
        c=machine();c.w(art.SETTINGS+4,0);c.w(actor+0x1085,64);old.draw(c)
        self.assertFalse(any(s[11]for s in c.sprites));self.assertTrue(any(s[1]==7 for s in c.sprites))
        c.sprites=[];c.w(art.SETTINGS+8,0);old.draw(c);self.assertFalse(any(s[1]==7 for s in c.sprites))
        c=machine();c.w(art.SETTINGS,0);old.draw(c);self.assertEqual(c.sprites,[]);self.assertTrue(c.texts)

    def test_native_texture_upload_and_final_gif_packet_keep_native_banks_and_scissor(self):
        c=machine(actual=True);before=c.r.copy();old.draw(c)
        self.assertEqual(c.r,before);self.assertEqual((c.hi,c.lo),(123,456))
        self.assertGreater(len(c.transfers),10);self.assertGreater(len(c.packets),10)
        for p in c.packets:
            if len(p)!=192:continue
            words=struct.unpack('<24Q',p)
            self.assertEqual(words[0],0x1000000000000008)
            self.assertEqual(words[20-2:20],(0x4400000000008001,0x5353))
            self.assertNotIn(0x40,words[3:18:2]) # never replace per-world SCISSOR
            self.assertEqual(words[13],0)
            tex0=words[16];self.assertGreaterEqual(tex0&0x3FFF,0x2A00)
            self.assertLess(tex0&0x3FFF,0x2C80)
        # All current portrait resources remain marked dirty; native subsequent
        # users must upload their own image after this panel borrowed the bank.
        for m in old.feed_test.MODELS:
            b=c.u(m+80);self.assertEqual(c.u(c.u(b+16)+40),0)

    def test_complete_previous_styled_release_upgrades_and_explicit_settings_persist(self):
        import mod_settings
        c=old.captured_machine(split=True);c.write(hud.feed.WORLD,hud.feed.world_code())
        for b in hud.build_memory(c.buffer)['blocks']:c.write(b['address'],bytes.fromhex(b['data_hex']))
        for p,d in hud.pieces(hud.feed.DRAW):c.write(p,bytes(len(d)))
        c.write(art.SETTINGS,bytes(20))
        for p,d in hud.pieces(hud.feed.DRAW,native=False):c.write(p,d)
        old_views=c.read(hud.VIEWS,hud.MAX_VIEWS*hud.VIEW_STRIDE);c.w(hud.CONTROL+20,71)
        settings=dict(mod_settings.DEFAULTS,split_hud_style='compact',show_hud_portraits=False,show_hud_sparking_effects=False)
        for b in hud.build_memory(c.buffer,settings=settings)['blocks']:c.write(b['address'],bytes.fromhex(b['data_hex']))
        self.assertEqual(c.u(hud.CONTROL+20),71);self.assertEqual(c.read(hud.VIEWS,len(old_views)),old_views)
        self.assertEqual(c.read(art.SETTINGS,12),bytes(12))
        self.assertEqual(hud.build_memory(c.buffer)['blocks'],[])
        self.assertEqual(hud.build_memory(c.buffer,settings=settings)['blocks'],[])
        changes=hud.build_memory(c.buffer,settings=dict(mod_settings.DEFAULTS))['blocks']
        self.assertEqual([b['address']for b in changes],[art.SETTINGS])
        for address in (art.SPRITE,art.TEMPLATE,art.NATIVE_PANEL,art.COMPACT):
            c.buffer[address]^=1
            with self.subTest(address=hex(address)),self.assertRaisesRegex(ValueError,'payload changed'):
                hud.build_memory(c.buffer)
            c.buffer[address]^=1

    def test_linear_sampling_cannot_bleed_neighboring_atlas_cells_on_either_side(self):
        c=machine(actual=True);old.draw(c)
        sprites=[packet for packet in c.packets if len(packet)==192]
        self.assertTrue(sprites)
        for packet in sprites:
            clamp=struct.unpack_from('<Q',packet,80)[0]
            u0,v0=struct.unpack_from('<2H',packet,160)
            u1,v1=struct.unpack_from('<2H',packet,176)
            u0,u1,v0,v1=(v//16 for v in (u0,u1,v0,v1))
            self.assertEqual(clamp&15,10)
            for shift,expected in ((4,min(u0,u1)),(14,max(min(u0,u1),max(u0,u1)-1)),
                                   (24,min(v0,v1)),(34,max(min(v0,v1),max(v0,v1)-1))):
                self.assertEqual((clamp>>shift)&1023,expected)

    def test_bad_portrait_reload_resource_omits_only_that_sprite(self):
        c=machine(actual=True);actor=old.feed_test.ACTORS[4];model=c.u(hud.core.MODELS+4*c.u(actor+12))
        c.w(model+80,0xFFFFFFFC);before=c.r.copy();old.draw(c)
        self.assertEqual(c.r,before);self.assertGreater(len(c.packets),5)


if __name__=='__main__':unittest.main()
