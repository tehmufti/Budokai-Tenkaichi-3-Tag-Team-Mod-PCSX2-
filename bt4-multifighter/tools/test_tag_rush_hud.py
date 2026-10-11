"""Execute the tag meter's emitted draw code and check every viewport band."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
from unittest import mock

import tag_rush_hud as h
import quad_viewports as quad
import multiview_layout
from native_map import A, GP
from regional import SCISSOR_Y1, Y_ORIGIN
from test_extra_special_pools import Cpu

MANAGER, BATTLE, VIEW = 0x1800000, 0x1801000, 0x1810000
ACTORS = tuple(0x1900000+i*0x2000 for i in range(6))
MODELS = tuple(0x2000000+i*0x2000 for i in range(6))
PARAMS = tuple(0x2100000+i*0x100 for i in range(6))


def machine(subject=0, charge=375, language='en', view=(0, 511, 0, SCISSOR_Y1), split=False):
    c=Cpu({'segments': []})
    for address, data in h.pieces({'language': language}): c.write(address, data)
    c.write(h.CONTROL, struct.pack('<5I', h.MAGIC, MANAGER, 6, 1, 0))
    c.w(h.CONTROL+48, 750); c.w(h.CONTROL+60, 1)
    c.w(h.CONTROL+0x3A0,0x3100000);c.w(h.CONTROL+0x3A4,256);c.write(0x3100000,bytes([3])*256)
    for fighter in range(6):
        c.w(h.METERS+fighter*h.METER_STRIDE, charge)
        c.w(h.METERS+fighter*h.METER_STRIDE+4, -1)
    c.write(h.core.MODE, struct.pack('<4I', 1, 6, MANAGER, 6))
    c.w(h.core.ACTORS, MANAGER); c.w(MANAGER, 2)
    c.write(h.participation.CONTROL, struct.pack('<5I', 5, MANAGER, 6, 63, 0))
    c.w(A(0x2FEB38), BATTLE); c.w(BATTLE, 3)
    c.w(GP-22176, VIEW)
    for off, value in zip((512, 516, 520, 524), view): c.w(VIEW+off, value)
    c.w(h.camera.SUCCESSOR_CONTROL+8, subject)
    for i, actor in enumerate(ACTORS):
        c.w(h.core.POINTERS+i*4, actor); c.w(actor,i); c.w(actor+0x994, 0)
        c.w(actor+12,i);c.w(h.core.MODELS+4*i,MODELS[i]);c.w(MODELS[i]+16,i)
        c.w(MODELS[i]+4,1);c.w(MODELS[i]+2332,PARAMS[i])
        c.w(actor+0x998, 1); c.w(actor+0x9E4, 30000); c.w(h.core.TABLE+i*4, i^1)
    if split:
        c.w(h.hud.CONTROL, h.hud.MAGIC)
        c.callbacks[h.hud.ACTIVE]=lambda m: m.r.__setitem__(2, 1)
        c.write(h.hud.VIEWS, struct.pack('<6I', 1, *view, h.camera.SUCCESSOR_CONTROL+8))
    c.texts=[]; c.rects=[]
    c.callbacks[h.CAPTION]=lambda m: m.texts.append((bytes(m.read(m.r[4],32)).split(b'\0')[0].decode(),
                                      m.r[5]/16-1792, m.r[6]/16-Y_ORIGIN, m.r[7]))
    c.callbacks[h.bars.RECT]=lambda m: m.rects.append((m.r[4]/16-1792, m.r[5]/16-Y_ORIGIN,
                                      m.r[6]/16-1792, m.r[7]/16-Y_ORIGIN, m.r[8]))
    return c


def draw(c):
    c.r[31]=0xFEED0000; c.run(h.DRAW)


def intersects(a,b):
    return max(a[0],b[0])<min(a[2],b[2]) and max(a[1],b[1])<min(a[3],b[3])


class TagRushHudTests(unittest.TestCase):
    def test_unadmitted_form_has_no_meter_or_invitation_but_target_keeps_charge_visible(self):
        c=machine(charge=750);c.w(MODELS[0]+12,250);c.write(0x3100000+250,b'\0');draw(c)
        self.assertEqual((c.texts,c.rects),([],[]))
        c=machine(charge=750);c.w(MODELS[1]+12,250);c.write(0x3100000+250,b'\0');draw(c)
        self.assertEqual(c.texts[-1][0],'TAG ATTACK')

    def test_native_giants_have_no_meter_and_cannot_supply_an_invitation_or_only_ally(self):
        c=machine(charge=750);c.write(PARAMS[0]+2,b'\x04');draw(c)
        self.assertEqual((c.texts,c.rects),([],[]))
        c=machine(charge=750)
        for index in (2,4):c.write(PARAMS[index]+2,b'\x04')
        draw(c);self.assertEqual((c.texts,c.rects),([],[]))
        for giant in (0,3):
            c=machine(subject=2,charge=750);c.w(h.METERS+4,0);c.w(h.METERS+8,3)
            c.w(h.METERS+12,150);c.w(h.core.TABLE+8,3);c.write(PARAMS[giant]+2,b'\x04')
            draw(c);self.assertEqual(c.texts[-1][0],'TAG ATTACK' if giant==3 else 'TAG ATTACK')
        c=machine(charge=750);c.w(h.METERS+4,0);c.write(PARAMS[1]+2,b'\x04')
        draw(c);self.assertEqual(c.texts[-1][0],'TAG ATTACK')

    def test_meter_fill_clamps_to_full_without_mutating_runtime(self):
        for charge,width,label in ((0,0,'TAG ATTACK'),(375,32,'TAG ATTACK'),(750,64,'TAG ATTACK'),
                                   (900,64,'TAG ATTACK')):
            with self.subTest(charge=charge):
                c=machine(charge=charge); before=c.read(h.CONTROL,0x400); draw(c)
                self.assertEqual(c.texts[-1][0],label)
                self.assertEqual(len(c.rects),3 if width else 2)
                if width: self.assertEqual(c.rects[-1][2]-c.rects[-1][0],width)
                self.assertEqual(c.read(h.CONTROL,0x400),before)

    def test_caption_stays_simple_for_allied_target_and_expired_or_retargeted_offer(self):
        c=machine(charge=750);c.w(h.core.TABLE,2);draw(c)
        self.assertEqual(c.texts[-1][0],'TAG ATTACK')
        for expired in (False,True):
            c=machine(charge=750);c.w(h.METERS+4,0);c.w(h.METERS+8,1 if expired else 3)
            c.w(h.METERS+12,150);c.w(h.CONTROL+72,150 if expired else 0);draw(c)
            self.assertEqual(c.texts[-1][0],'TAG ATTACK')

    def test_ffa_hides_tag_meter_only_for_captured_mode(self):
        for manager,visible in ((MANAGER,False),(MANAGER+4,True)):
            c=machine(charge=750)
            c.write(h.modes.CONTROL,struct.pack('<4I',h.modes.MAGIC,manager,6,h.modes.FFA));draw(c)
            self.assertEqual(bool(c.rects),visible)

    def test_invitation_states_keep_same_caption_and_individual_meter(self):
        for subject,target,label in ((0,3,'TAG ATTACK'),(2,3,'TAG ATTACK'),
                                      (4,5,'TAG ATTACK'),(1,0,'TAG ATTACK')):
            with self.subTest(subject=subject):
                c=machine(subject=subject,charge=750)
                c.w(h.METERS+4,0);c.w(h.METERS+8,3);c.w(h.METERS+12,150);c.w(h.core.TABLE+4*subject,target)
                draw(c);self.assertEqual(c.texts[-1][0],label)
        c=machine(subject=1,charge=750);c.w(h.METERS+h.METER_STRIDE,375)
        draw(c);self.assertEqual(c.rects[-1][2]-c.rects[-1][0],32)

    def test_no_hint_for_unready_stale_dead_or_one_ally_match(self):
        for address,value in ((h.CONTROL+12,0),(h.CONTROL+60,0),
                              (h.CONTROL+4,MANAGER+4),(h.CONTROL+8,8),
                              (h.participation.CONTROL+12,3),(h.participation.CONTROL+16,20),
                              (ACTORS[0]+0x9E4,0),(ACTORS[0]+0x994,5),(ACTORS[0],2),
                              (BATTLE,2),(A(0x333700),1),(h.CONTROL+48,0)):
            with self.subTest(address=hex(address),value=value):
                c=machine();c.w(address,value);draw(c)
                self.assertEqual((c.texts,c.rects),([],[]))

    def test_private_tag_keeps_uninvolved_fighters_meter_visible(self):
        for subject,shared,visible in ((0,0,False),(1,0,False),(2,0,False),(4,0,True),(4,1,False)):
            c=machine(subject=subject);c.w(h.CONTROL+16,1);c.w(h.CONTROL+20,7);c.w(h.CONTROL+24,shared)
            draw(c);self.assertEqual(bool(c.rects),visible,(subject,shared))

    def test_every_view_uses_its_own_subject_and_scissor(self):
        for humans in (1,2,3,4):
            views=quad.rectangles(humans) if humans>1 else ((0,511,0,SCISSOR_Y1),)
            for seat,view in enumerate(views):
                with self.subTest(humans=humans,seat=seat):
                    c=machine(subject=seat,view=view,split=True);draw(c)
                    x0,x1,y0,y1=view
                    self.assertTrue(c.rects)
                    for left,top,right,bottom,_ in c.rects:
                        self.assertGreaterEqual(left,x0);self.assertLessEqual(right,x1)
                        self.assertGreaterEqual(top,y0);self.assertLessEqual(bottom,y1)
                    self.assertEqual(c.texts[-1][1],x1-h.MARGIN-h.WIDTH)
                    self.assertEqual(c.texts[-1][2],y0+h.screen_y(h.LABEL_TOP))
                    self.assertEqual(c.rects[-1][1],y0+h.screen_y(h.BAR_TOP))
        c=machine(split=True);c.w(h.hud.VIEWS+4,1);draw(c)
        self.assertEqual(c.texts,[],'an unrecognised viewport never borrows the first player')

    def test_near_hud_strip_avoids_captions_in_all_layouts_and_video_heights(self):
        # Compact fusion captions use 75% glyphs; the older generic layout
        # reserves full-size lines, which would overstate their drawn width.
        labels=[f'FUSION - P{i} TAP R3 TO ACCEPT' for i in range(1,5)]
        labels += [f'FUSED - PLAYER {i} HAS CONTROL' for i in range(1,5)]
        labels += [f'P{i} TAKES CONTROL IN {n}' for i in range(1,5) for n in range(1,6)]
        for height in (448,512):
            sy=(lambda n:n) if height==448 else (lambda n:(n*18725)>>14)
            for language in ('en','es'):
                fusion_width=max(len(h.localization.guest(t,{'language':language})) for t in labels)*4.5+1
                for humans in (1,2,3,4):
                    half=height//2
                    if humans==1: views=((0,511,0,height-1),)
                    elif humans==2: views=((0,254,0,height-1),(257,511,0,height-1))
                    else:
                        views=((0,254,0,half-2),(257,511,0,half-2))
                        views+=((128,382,half+1,height-1),) if humans==3 else ((0,254,half+1,height-1),(257,511,half+1,height-1))
                    for view in views:
                        left,right,top,bottom=view
                        occupied={'own status':(left,top,right,top+70),
                                  'target status':(left,bottom-64,right,bottom),
                                  'revive caption':(left+8,bottom+sy(-36),left+202,bottom+sy(-36)+8),
                                  'revive meter':(left+8,bottom+sy(-25),left+128,bottom+sy(-25)+3)}
                        if humans>=3:
                            for i,name in enumerate(('fusion request/owner','control countdown')):
                                y=top+sy(multiview_layout.FUSION_Y)+i*9
                                occupied[name]=(left+8,y,left+8+fusion_width,y+6.25)
                            occupied.update({
                                'fusion timer':(left+8,top+sy(70)+18,left+99,top+sy(70)+30),
                                'kills':(left+8,top+sy(114),left+62,top+sy(114)+7),
                                'kill feed':(left+8,top+sy(128),left+248,top+sy(128)+17),
                                'takeover':(left+8,top+sy(151),left+242,top+sy(151)+8)})
                        else:
                            occupied.update({
                                'fusion request/owner/countdown':(left+8,sy(204),right,sy(217)+8),
                                'fusion timer':(left+8,sy(232),left+130,sy(232)+16),
                                'kills':(left+8,top+sy(88),left+62,top+sy(88)+8),
                                'kill feed':(left+8,top+sy(106),left+248,top+sy(106)+83),
                                'takeover':(left+8,bottom+sy(-22),left+242,bottom+sy(-22)+8)})
                        with mock.patch.object(h,'screen_y',sy):
                            c=machine(view=view,split=humans>1,language=language);draw(c)
                            bounds=h.rectangles(view)
                        self.assertTrue(c.rects)
                        self.assertEqual(c.texts[-1][2],top+sy(h.LABEL_TOP))
                        for name,ours in bounds.items():
                            for other,theirs in occupied.items():
                                self.assertFalse(intersects(ours,theirs),(height,language,humans,view,name,other))

    def test_private_caption_preserves_exact_glyphs_at_three_quarter_size_in_every_view(self):
        c=Cpu({'segments':[]});c.write(h.CAPTION,h.caption_code())
        c.write(h.feed.TEXT,h.feed.text_code());c.write(h.feed.FONT,h.feed.font_data())
        c.write(h.feed.TEMPLATE,bytes(112));c.write(h.TEXT,b'TAG ATTACK\0')
        packet=0x5000000;packets=[]
        c.callbacks[A(0x100878)]=lambda m:m.r.__setitem__(2,packet)
        c.callbacks[A(0x100890)]=lambda m:packets.append(bytes(m.read(packet,m.r[4]-packet)))
        for humans in (1,2,3,4):
            c.w(quad.CONTROL,quad.MAGIC if humans>1 else 0);c.w(quad.CONTROL+quad.VIEW_COUNT,humans)
            origin=((1792+182)*16,(Y_ORIGIN+h.LABEL_TOP)*16)
            def emit(entry):
                packets.clear();c.r[4:8]=[h.TEXT,*origin,0x80FFFFFF];c.r[31]=0xFEED0000;c.run(entry)
                return packets[0]
            full,small=emit(h.feed.TEXT),emit(h.CAPTION)
            self.assertEqual(len(small),len(full));self.assertEqual(small[:112],full[:112])
            for offset in range(112,len(full),8):
                f=struct.unpack_from('<I',full,offset)[0];s=struct.unpack_from('<I',small,offset)[0]
                for shift,start in ((0,origin[0]),(16,origin[1])):
                    self.assertEqual((((s>>shift)&65535)-start)*16,(((f>>shift)&65535)-start)*12)
        self.assertLess(h.CAPTION+len(h.caption_code()),h.END)

    def test_camera_hides_only_bound_running_cinematics_in_this_view(self):
        for track,direct,bound,hidden in ((True,0,True,True),(False,1,True,True),
                                         (False,1,False,False),(False,0,True,False)):
            with self.subTest(track=track,direct=direct,bound=bound):
                c=machine();c.w(VIEW+704,0x1820000 if track else 0)
                c.w(VIEW+776,int(track));c.w(VIEW+812,direct);c.w(VIEW+768,0x1830000 if bound else 0)
                draw(c);self.assertEqual(not bool(c.texts),hidden)

    def test_spanish_labels_fit_and_registers_and_hilo_survive(self):
        for language in ('en','es'):
            for _,data in h.pieces({'language':language})[-1:]:
                for start in range(0,len(data),h.TEXT_STRIDE):
                    label=data[start:start+h.TEXT_STRIDE].split(b'\0')[0]
                    self.assertLessEqual(len(label)*4.5,h.WIDTH)
                    self.assertNotIn(b'?',label)
        c=machine(charge=750,language='es');c.hi=0x11223344;c.lo=0x55667788
        saved={reg:0x123000+reg for reg in range(16,24)}
        for reg,value in saved.items():c.r[reg]=value
        stack=c.r[29];draw(c)
        self.assertEqual(c.texts[-1][0],'ATAQUE TAG')
        self.assertEqual({r:c.r[r] for r in saved},saved)
        self.assertEqual((c.r[29],c.hi,c.lo),(stack,0x11223344,0x55667788))

    def test_normal_and_quad_hud_composition_accept_only_known_bytes(self):
        ram=bytearray(0x8000000)
        struct.pack_into('<I',ram,h.hud.CONTROL,h.hud.MAGIC)
        previous=0x07390000;struct.pack_into('<I',ram,h.hud.CONTROL+16,previous)
        for four in (False,True):
            with self.subTest(four=four):
                struct.pack_into('<I',ram,quad.CONTROL,quad.MAGIC if four else 0)
                address=quad.DRAW if four else h.hud.CODE
                old=quad.draw() if four else h.hud.wrapper(previous,deferred=True)
                ram[address:address+0x1000]=bytes(0x1000);ram[address:address+len(old)]=old
                updates=h.hud_patch(ram);self.assertEqual(updates[0][0],address)
                # Installers may publish our own code/control before rebuilding
                # the caller; recognise both well-defined orders.
                struct.pack_into('<I',ram,h.CONTROL,h.MAGIC)
                for p,data in h.pieces({'language':'en'}):ram[p:p+len(data)]=data
                self.assertEqual(h.hud_patch(ram),updates)
                ram[updates[0][0]:updates[0][0]+len(updates[0][1])]=updates[0][1]
                self.assertEqual(h.hud_patch(ram),[])
                ram[address]^=1
                with self.assertRaises(ValueError):h.hud_patch(ram)
                struct.pack_into('<I',ram,h.CONTROL,0)


if __name__=='__main__':unittest.main()
