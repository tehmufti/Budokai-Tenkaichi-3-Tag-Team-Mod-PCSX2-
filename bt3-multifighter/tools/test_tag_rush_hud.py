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


def machine(subject=0, charge=375, language='en', view=(0, 511, 0, SCISSOR_Y1), split=False, show=True):
    c=Cpu({'segments': []})
    for address, data in h.pieces({'language': language, h.SHOW_KEY: show}): c.write(address, data)
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
                                      m.r[5]/16-1792, m.r[6]/16-Y_ORIGIN, m.r[7], m.r[8]))
    c.callbacks[h.bars.RECT]=lambda m: m.rects.append((m.r[4]/16-1792, m.r[5]/16-Y_ORIGIN,
                                      m.r[6]/16-1792, m.r[7]/16-Y_ORIGIN, m.r[8]))
    return c


def draw(c):
    c.r[31]=0xFEED0000; c.run(h.DRAW)


def intersects(a,b):
    return max(a[0],b[0])<min(a[2],b[2]) and max(a[1],b[1])<min(a[3],b[3])


class TagRushHudTests(unittest.TestCase):
    def full_meter(self, c):
        draw(c)
        self.assertEqual(c.texts[-1][0],'TAG ATTACK')
        self.assertEqual(c.rects[-1][2]-c.rects[-1][0],64)

    def test_transformed_unadmitted_forms_keep_the_meter_and_its_charge(self):
        # A transformation reloads a form the preparation never assessed (admission 0): the subject's own meter and
        # an ally's both stay, with the same charge. Starting the attack is still the director's decision.
        for fighter in (0,2,1):
            with self.subTest(fighter=fighter):
                c=machine(charge=750);c.w(MODELS[fighter]+12,250);c.write(0x3100000+250,b'\0');self.full_meter(c)

    def test_giant_forms_keep_the_meter_for_the_giant_and_its_team(self):
        for giants in ((0,),(2,4),(0,2,4),(1,)):
            with self.subTest(giants=giants):
                c=machine(charge=750)
                for index in giants:c.write(PARAMS[index]+2,b'\x04')
                self.full_meter(c)

    def test_reloading_or_swapped_models_keep_the_meter(self):
        # Mid-reload (model not ready, model slot changed or out of range, another model's identity) and Body Change
        # (actors exchange model slots) read no model data at all. An invalid form slot still counts as absent.
        cases=((MODELS[0]+4,0),(ACTORS[0]+12,12),(ACTORS[2]+12,0x40),(MODELS[2]+16,7),(h.core.MODELS,0))
        for address,value in cases:
            with self.subTest(address=hex(address),value=value):
                c=machine(charge=750);c.w(address,value);self.full_meter(c)
        c=machine(charge=750);c.w(ACTORS[0]+12,2);c.w(ACTORS[2]+12,0);self.full_meter(c)

    def test_fusion_partner_consumption_and_revival_follow_the_team(self):
        # Consumed fusion partner (participation CONSUMED bit): one ally fewer; with only the subject left, no meter.
        c=machine(charge=750);c.w(h.participation.CONTROL+16,1<<2);self.full_meter(c)
        c=machine(charge=750);c.w(h.participation.CONTROL+16,(1<<2)|(1<<4));draw(c)
        self.assertEqual((c.texts,c.rects),([],[]))
        # Defusion clears the bit again; a revived ally (health above zero) counts again.
        c=machine(charge=750);c.w(h.participation.CONTROL+16,0);c.w(ACTORS[4]+0x9E4,0);self.full_meter(c)
        c.w(ACTORS[2]+0x9E4,0);c.texts.clear();c.rects.clear();draw(c);self.assertEqual((c.texts,c.rects),([],[]))
        c.w(ACTORS[2]+0x9E4,500);self.full_meter(c)

    def test_meter_setting_off_installs_no_meter_and_the_show_word_hides_it(self):
        off=dict(h.pieces({'language':'en',h.SHOW_KEY:False}))
        self.assertEqual(set(off),{h.DRAW,h.SHOW})
        self.assertEqual(off[h.SHOW],bytes(4))
        self.assertEqual(off[h.DRAW],h.draw_code(meter=False))
        self.assertLess(len(off[h.DRAW]),len(h.draw_code()))
        self.assertEqual(off[h.DRAW][:8],h.draw_code()[:8])
        c=machine(charge=750,show=False);draw(c)
        self.assertEqual((c.texts,c.rects),([],[]))
        self.assertFalse(any(c.read(h.ALIVE,0x100)) or any(c.read(h.CAPTION,0x100)))
        on=dict(h.pieces({'language':'en'}));self.assertEqual(on[h.SHOW],struct.pack('<I',1))
        c=machine(charge=750);c.w(h.SHOW,0);draw(c);self.assertEqual((c.texts,c.rects),([],[]))
        c.w(h.SHOW,1);self.full_meter(c)
        self.assertTrue(h.TEXT+2*h.TEXT_STRIDE<=h.SHOW<h.SHOW+4<=h.CAPTION)

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
                              (ACTORS[0]+0x9E4,0),(ACTORS[0]+0x994,5),(ACTORS[0]+0x998,0),(ACTORS[0],2),
                              (BATTLE,2),(A(0x333700),1),(h.CONTROL+48,0)):
            with self.subTest(address=hex(address),value=value):
                c=machine();c.w(address,value);draw(c)
                self.assertEqual((c.texts,c.rects),([],[]))

    def test_private_tag_keeps_uninvolved_fighters_meter_visible(self):
        for subject,shared,visible in ((0,0,False),(1,0,False),(2,0,False),(4,0,True),(4,1,False)):
            c=machine(subject=subject);c.w(h.CONTROL+16,1);c.w(h.CONTROL+20,7);c.w(h.CONTROL+24,shared)
            draw(c);self.assertEqual(bool(c.rects),visible,(subject,shared))

    LAYOUTS = {'top': (1, 1, 1, 1, 15, 100, 1, 0), 'top 140%': (1, 1, 1, 1, 15, 140, 1, 0),
               'top 80%': (1, 1, 1, 1, 15, 80, 1, 0), 'top_bottom': (1, 1, 1, 1, 15, 100, 1, 1),
               'co-op players': (1, 1, 1, 0, 15, 100, 1, 0), 'compact text': (0, 1, 1, 1, 15, 100, 1, 0)}
    SUBJECTS = 0x2200000

    def split_machine(self, humans, seat, words, coop, language='en', views=None):
        import viewport_hud_art as art
        views = views or quad.rectangles(humans)
        subjects = [(2*i) % 6 for i in range(humans)] if coop else list(range(humans))
        c = machine(subject=subjects[seat], view=views[seat], split=True, language=language)
        c.w(h.hud.CONTROL+12, humans)
        for i, v in enumerate(views):
            c.write(h.hud.VIEWS+i*h.hud.VIEW_STRIDE, struct.pack('<6I', 1, *v, self.SUBJECTS+4*i))
            c.w(self.SUBJECTS+4*i, subjects[i])
        c.write(art.SETTINGS, struct.pack('<8I', *words))
        return c

    def test_every_view_places_the_meter_below_its_own_status(self):
        # One full view: below the subject's own main gauge, under its middle third and right of the ki bars
        # (Version 12); a right-hand (team 2) subject gets the mirror image. Split views: inside the view's own panel.
        full = (0, 511, 0, SCISSOR_Y1)
        expected_x, expected_y = (111, 66) if h._settings.ADAPTER == 'BT4' else (123, 38)
        self.assertEqual(h.placement(full)[:2], (expected_x, h.screen_y(expected_y)))
        self.assertEqual(h.placement(full, subject=1)[0], 511-expected_x-h.WIDTH)
        for subject in (0, 1):
            c = machine(subject=subject); draw(c)
            x, y, bar = h.placement(full, subject=subject)
            self.assertEqual(c.texts[-1][1:3], (x, y)); self.assertEqual(c.rects[-1][1], bar)
        # Split views: below each view's own viewport_hud panel, wherever its layout puts it.
        for humans in (2, 3, 4):
            views = quad.rectangles(humans)
            for seat in range(humans):
                for name, words in self.LAYOUTS.items():
                    for coop in (False, True):
                        with self.subTest(humans=humans, seat=seat, layout=name, coop=coop):
                            c = self.split_machine(humans, seat, words, coop); draw(c)
                            m = h.meter(views[seat], split=seat, settings=words, coop=coop, views=humans)
                            self.assertEqual(c.texts[-1][1:3], (m['x'], m['y']))
                            self.assertEqual((c.texts[-1][0], c.texts[-1][4]), (m['label'], m['units']))
                            self.assertEqual(c.rects[-1][1], m['bar'])
                            self.assertEqual(c.rects[1][2]-c.rects[1][0], m['width'])
                            x0, x1, y0, y1 = views[seat]
                            for left, top, right, bottom, _ in c.rects:
                                self.assertGreaterEqual(left, x0); self.assertLessEqual(right, x1)
                                self.assertGreaterEqual(top, y0); self.assertLessEqual(bottom, y1)
        c=machine(split=True);c.w(h.hud.VIEWS+4,1);draw(c)
        self.assertEqual(c.texts,[],'an unrecognised viewport never borrows the first player')

    def test_bt4_one_view_meter_sits_below_its_second_status_row(self):
        # BT4's status (measured from a live B14 REV2 frame, logical 512 x 448): portrait, main gauge, then a second
        # row of ki bars, stocks and its own small gauge under the main gauge's middle third, and the partner panel.
        parts = {'portrait': (5, 8, 62, 63), 'main gauge': (65, 15, 228, 30), 'ki bars': (63, 33, 111, 51),
                 'stocks': (112, 33, 128, 51), 'small gauge': (130, 33, 192, 51), 'partner panel': (10, 66, 109, 83),
                 'timer': (228, 13, 283, 35), 'kills': (8, 86, 62, 96)}
        with mock.patch.multiple(h, FULL_X=111, FULL_LABEL=66):
            for subject in (0, 1):
                bounds = h.rectangles((0, 511, 0, SCISSOR_Y1), subject=subject)
                for name, (a, b, c, d) in parts.items():
                    theirs = (a, b, c, d) if not subject else (511-c, b, 511-a, d)
                    for ours in bounds.values():
                        self.assertFalse(intersects(ours, theirs), (subject, name, ours))

    def test_anamorphic_split_meter_follows_the_three_quarter_frame_and_compacts_its_label(self):
        # 16:9 draws each panel 3/4 as wide (BT4 B14 ships the widescreen patch): the meter, its size and the 3/4-view
        # 148 px width limit follow it exactly; the label shrinks to fit and a narrow meter shows the compact label.
        import widescreen_support as wide
        seen = set()
        for humans in (2, 3, 4):
            views = quad.rectangles(humans)
            for seat in range(humans):
                for name, words in self.LAYOUTS.items():
                    for coop in (False, True):
                        with self.subTest(humans=humans, seat=seat, layout=name, coop=coop):
                            c = self.split_machine(humans, seat, words, coop)
                            for address, value in wide.WORDS: c.w(address, value)
                            draw(c)
                            m = h.meter(views[seat], split=seat, settings=words, coop=coop, views=humans, wide=True)
                            self.assertEqual(c.texts[-1], (m['label'], m['x'], m['y'], c.texts[-1][3], m['units']))
                            self.assertEqual((c.rects[-1][1], c.rects[1][2]-c.rects[1][0]), (m['bar'], m['width']))
                            seen.add((m['units'], m['label']))
        self.assertIn((5, h.COMPACT_LABEL), seen)
        self.assertIn((6, h.LABEL), seen)
        # Two 16:9 views at 100%: the meter shrinks with the 3/4-wide frame, not the logical panel width.
        px, _py, w, _ = h.split_panel(quad.rectangles(2)[0], 0, self.LAYOUTS['top'], False, 2, True)
        narrow = h.meter(quad.rectangles(2)[0], split=0, settings=self.LAYOUTS['top'], views=2, wide=True)
        self.assertEqual(narrow['width'], min(h.WIDTH, (h.SPLIT_ROOM*w*3) >> 10))
        self.assertEqual(narrow['x']-px, (h.SPLIT_X*w*3) >> 10)

    def test_meter_clears_status_art_and_captions_in_all_layouts_and_video_heights(self):
        # Compact fusion captions use 75% glyphs; the older generic layout
        # reserves full-size lines, which would overstate their drawn width.
        labels=[f'FUSION - P{i} TAP R3 TO ACCEPT' for i in range(1,5)]
        labels += [f'FUSED - PLAYER {i} HAS CONTROL' for i in range(1,5)]
        labels += [f'P{i} TAKES CONTROL IN {n}' for i in range(1,5) for n in range(1,6)]

        # The drawn parts of each game's native panel, in 256 x 64 frame units (viewport_hud_art.LAYOUTS and the
        # opaque rows of the atlas6 frame): main gauge housing, second row (ki bars, BT4's digit housing), stocks.
        if h._settings.ADAPTER == 'BT4':
            parts = (('portrait', (1, 0, 69, 64)), ('gauge', (52, 3, 240, 27)), ('second row', (4, 27, 137, 37)),
                     ('second row foot', (4, 37, 134, 47)), ('stock gauge', (132, 25, 176, 36)))
        else:
            parts = (('portrait', (14, 1, 82, 69)), ('gauge', (52, 3, 240, 25)), ('second row', (14, 25, 117, 31)),
                     ('ki bars', (62, 26, 112, 45)), ('stocks', (14, 44, 77, 60)))

        def panel(px, py, w, right):
            """The drawn parts of a viewport_hud panel (256-unit native frame scaled to w; mirrored facing right)."""
            out = {}
            for part, (a, b, c_, d) in parts:
                l, r = (a*w/256, c_*w/256) if not right else (w-c_*w/256, w-a*w/256)
                out[part] = (px+l, py+b*w/256, px+r, py+d*w/256)
            return out

        def native_full(left, right):
            """The native one-view status of each side (logical 512 x 448, measured from the game's frame)."""
            parts = {'gauge frame': (14, 6, 240, 32), 'ki bars': (60, 30, 116, 52), 'stocks': (14, 30, 62, 64),
                     'partner panel': (10, 66, 109, 83) if h._settings.ADAPTER == 'BT4' else (12, 64, 114, 86),
                     'timer': (232, 6, 280, 34)}
            out = {}
            for name, (a, b, c_, d) in parts.items():
                out['own '+name] = (left+a, b, left+c_, d)
                out['other '+name] = (right-c_, b, right-a, d)
            return out

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
                    for seat,view in enumerate(views):
                        left,right,top,bottom=view
                        captions={'revive caption':(left+8,bottom+sy(-36),left+202,bottom+sy(-36)+8),
                                  'revive meter':(left+8,bottom+sy(-25),left+128,bottom+sy(-25)+3)}
                        if humans>=3:
                            for i,name in enumerate(('fusion request/owner','control countdown')):
                                y=top+sy(multiview_layout.FUSION_Y)+i*9
                                captions[name]=(left+8,y,left+8+fusion_width,y+6.25)
                            captions.update({
                                'fusion timer':(left+8,top+sy(70)+18,left+99,top+sy(70)+30),
                                'kills':(left+8,top+sy(114),left+62,top+sy(114)+7),
                                'kill feed':(left+8,top+sy(128),left+248,top+sy(128)+17),
                                'takeover':(left+8,top+sy(151),left+242,top+sy(151)+8)})
                        else:
                            captions.update({
                                'fusion request/owner/countdown':(left+8,sy(204),right,sy(217)+8),
                                'fusion timer':(left+8,sy(232),left+130,sy(232)+16),
                                'kills':(left+8,top+sy(88),left+62,top+sy(88)+8),
                                'kill feed':(left+8,top+sy(250),left+248,top+sy(250)+83),
                                'takeover':(left+8,bottom+sy(-22),left+242,bottom+sy(-22)+8)})
                        cases = []
                        if humans == 1:
                            for subject in (0, 1):
                                occupied = dict(captions, **native_full(left, right))
                                cases.append((dict(subject=subject), occupied, (lambda c, s=subject: machine(subject=s, view=view, language=language))))
                        else:
                            for name, words in self.LAYOUTS.items():
                                for coop in (False, True):
                                    occupied = dict(captions)
                                    if words[0] == 1:
                                        px, py, w, faces = h.split_panel(view, seat & 1, words, coop, humans)
                                        occupied.update({'own '+k: v for k, v in panel(px, py, w, faces).items()})
                                        if not coop or words[3]:
                                            mid = (left+right)/2
                                            # The target panel: the other half of the top row, 85 % of the own
                                            # panel's width (post_code), so its height is a quarter of that.
                                            foot = top+2+w*85/100/4+2
                                            occupied['target panel'] = ((left, bottom-66, right, bottom) if words[7] else
                                                                        (mid, top, right, foot) if not faces else (left, top, mid, foot))
                                    else:
                                        occupied['compact panels'] = (left, top, right, top+66)
                                    cases.append((dict(split=seat, settings=words, coop=coop, views=humans), occupied,
                                                  (lambda c, n=humans, s=seat, w_=words, co=coop: self.split_machine(n, s, w_, co, language, views))))
                        for where, occupied, make in cases:
                            with mock.patch.object(h,'screen_y',sy):
                                c=make(None);draw(c)
                                bounds=h.rectangles(view, **where)
                            self.assertTrue(c.rects)
                            self.assertEqual(c.texts[-1][2], bounds['caption'][1])
                            for name,ours in bounds.items():
                                for other,theirs in occupied.items():
                                    self.assertFalse(intersects(ours,theirs),(height,language,humans,view,where,name,other))

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
