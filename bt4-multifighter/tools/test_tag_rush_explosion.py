"""Per-view white finish and the Father-Son Galick's native blast impact."""
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
import tag_rush_camera as camera
import tag_team_rush as tag
import viewport_hud as hud
import fresh_team_camera as follow
import guest_healthbars as bars
import quad_viewports as quad
import test_tag_rush_effects as support
from native_map import A
from regional import Y_ORIGIN,SCISSOR_Y1
from test_tag_rush_camera import run

VIEW=0x3800000


def machine():
    c=support.TagEffectsTests().impact_machine()
    for p,b in camera.pieces():c.write(p,b)
    c.w(scene.STATE+scene.S['descriptor'],assets.BASE)
    c.w(assets.BASE+28,assets.FINISHER|assets.BEAM_LEAD|assets.BEAM_PARTNER)
    c.w(tag.CONTROL+tag.C['start_requests'],7)
    c.w(scene.STATE+scene.S['total_ticks'],600)
    c.w(camera.CAMERA+812,1)
    c.rects=[]
    c.callbacks[bars.RECT]=lambda m:m.rects.append((m.r[4],m.r[5],m.r[6],m.r[7],m.r[8]))
    c.callbacks[hud.ACTIVE]=lambda m:m.r.__setitem__(2,1)
    return c


def start(c):
    c.r[4:6]=[2,17];run(c,fx.EXPLOSION);return c.r[2]


def view(c,subject=0,rect=(0,511,0,SCISSOR_Y1),split=False):
    c.w(c.r[28]-22176,VIEW);c.write(VIEW,c.read(camera.CAMERA,128))
    c.write(VIEW+512,struct.pack('<4I',*rect))
    c.w(follow.SUCCESSOR_CONTROL+8,subject)
    c.write(hud.CONTROL,struct.pack('<4I',hud.MAGIC if split else 0,c.u(tag.CONTROL+4),0,4))
    if split:
        c.write(hud.VIEWS,bytes(hud.MAX_VIEWS*hud.VIEW_STRIDE))
        c.write(hud.VIEWS,struct.pack('<6I',1,*rect,follow.SUCCESSOR_CONTROL+8))


def draw(c,elapsed):
    c.w(scene.STATE+scene.S['total_ticks'],600+elapsed);run(c,fx.WHITE_DRAW)


class WhiteFinishTests(unittest.TestCase):
    def galick_machine(self):
        c=machine();c.w(tag.CONTROL+tag.C['variant'],6)
        c.w(0x2450000+0x12C8,0x2462000);c.w(0x2450000+0x12D0,0x2463000)
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        native=elf_reader(elf_path(ROOT))[2]
        c.write(fx.NATIVE_BURST,native(fx.NATIVE_BURST,0x70))
        import tag_rush_beam_audio as sound
        c.impact_sounds=[]
        c.callbacks[sound.IMPACT]=lambda m:c.impact_sounds.append(1)
        return c

    def test_galick_blast_and_white_fade_start_once_without_extra_damage(self):
        c=self.galick_machine();before=[c.read(a,0x1600)for a in c.actors]
        self.assertEqual(start(c),1);self.assertEqual(start(c),1)
        self.assertEqual(c.u(fx.CONTROL+fx.W['burst']),1)
        self.assertEqual(c.impact_sounds,[1]);self.assertEqual(len(c.requests),1)
        pool,callbacks,request=c.requests[0]
        self.assertEqual((pool,callbacks),(0x2440000,A(0x2C3F20)))
        self.assertEqual(struct.unpack_from('<Iff',request),(1,1.25,0.))
        torso=c.u(c.models[1]+3436+17*4)
        self.assertEqual(request[16:32],c.read(torso+64,16))
        self.assertEqual(struct.unpack_from('<4I',request,48),(0,4,0,0))
        self.assertEqual([c.read(a,0x1600)for a in c.actors],before)
        view(c);draw(c,fx.galick_flash_delay()+fx.WHITE_RISE)
        self.assertEqual(c.rects[-1][4],0x80FFFFFF)

    def test_galick_has_one_opaque_ultimate_flash_as_beams_clear_then_fades_before_release(self):
        c=self.galick_machine();start(c);view(c);alphas=[]
        delay=fx.galick_flash_delay()
        for ticks in range(delay+fx.WHITE_TICKS+4):
            before=len(c.rects);draw(c,ticks)
            alphas.append(c.rects[-1][4]>>24 if len(c.rects)>before else 0)
        self.assertEqual(alphas,[0]*delay+[a*4 for a in fx.white_alphas()]+[0]*3)
        self.assertEqual(max(alphas),fx.WHITE_ULTIMATE_PEAK)
        opaque=[i for i,a in enumerate(alphas) if a==fx.WHITE_ULTIMATE_PEAK]
        self.assertEqual(opaque,list(range(opaque[0],opaque[-1]+1)),
                         'rounded peak must remain one continuous flash')
        self.assertEqual(alphas[-1],0)
        import tag_rush_galick_pair as galick
        peak_source=galick.EDGES[5]+galick.BURST_FRAME+(delay+fx.WHITE_RISE)*60/fx.ACTOR_HZ
        self.assertEqual(peak_source,galick.BEAM_END)
        self.assertLessEqual(galick.EDGES[5]+galick.BURST_FRAME+(delay+fx.WHITE_TICKS)*60/fx.ACTOR_HZ,galick.EDGES[-1])

    def test_missing_native_burst_resources_still_allow_white_and_audio(self):
        for address in (0x2450000+0x12C8,0x2450000+0x12D0):
            c=self.galick_machine();c.w(address,0)
            self.assertEqual(start(c),1);self.assertFalse(c.requests)
            self.assertEqual(c.u(fx.CONTROL+fx.W['burst']),0)
            self.assertEqual(c.impact_sounds,[1])

    def test_every_beam_ending_starts_one_receipt_without_native_cloud_or_combat_writes(self):
        for flags in (assets.BEAM_LEAD,assets.BEAM_PARTNER,
                      assets.BEAM_LEAD|assets.BEAM_PARTNER,assets.BEAM_PARTNER|256):
            c=machine();c.w(assets.BASE+28,assets.FINISHER|assets.CUSTOM_FINISHER|flags)
            before=[c.read(a,0x1600) for a in c.actors]
            self.assertEqual(start(c),1)
            self.assertEqual(c.u(fx.CONTROL+fx.W['magic']),fx.WHITE_MAGIC)
            self.assertEqual(c.u(fx.CONTROL+fx.W['start']),600)
            c.w(scene.STATE+scene.S['total_ticks'],608)
            self.assertEqual(start(c),1)
            self.assertEqual(c.u(fx.CONTROL+fx.W['start']),600,'second call cannot restart fade')
            self.assertFalse(c.requests,'no explosion or emitter allocation')
            self.assertEqual([c.read(a,0x1600) for a in c.actors],before)

    def test_soft_curve_has_one_peak_smooth_rise_decay_and_no_repeat(self):
        c=machine();self.assertEqual(start(c),1);view(c)
        alphas=[]
        for t in range(fx.WHITE_TICKS+8):
            before=len(c.rects);draw(c,t)
            alphas.append(c.rects[-1][4]>>24 if len(c.rects)>before else 0)
        expected=list(fx.white_alphas())+[0]*7
        self.assertEqual(alphas,expected)
        self.assertEqual(max(alphas),32)
        self.assertEqual(alphas[:fx.WHITE_RISE+1],sorted(alphas[:fx.WHITE_RISE+1]))
        self.assertEqual(alphas[fx.WHITE_RISE:],sorted(alphas[fx.WHITE_RISE:],reverse=True))
        self.assertLessEqual(max(abs(b-a)for a,b in zip(alphas,alphas[1:])),12)
        self.assertEqual((alphas[0],alphas[-1]),(0,0))

    def test_one_to_four_views_are_scoped_to_participants_and_clip_each_rectangle(self):
        for count in (1,2,3,4):
            rects=((0,511,0,SCISSOR_Y1),) if count==1 else quad.rectangles(count)
            for shared in (False,True):
                c=machine();start(c);c.w(tag.CONTROL+tag.C['shared'],int(shared))
                for subject in range(4):
                    rect=rects[subject%count];view(c,subject,rect,count>1)
                    before=len(c.rects);draw(c,fx.WHITE_RISE)
                    visible=subject<3 or shared
                    self.assertEqual(len(c.rects)-before,int(visible),(count,subject,shared))
                    if visible:
                        x0,x1,y0,y1=rect
                        self.assertEqual(c.rects[-1],((x0+1792)*16,(y0+Y_ORIGIN)*16,
                          (x1+1793)*16,(y1+Y_ORIGIN+1)*16,0x20FFFFFF))

    def test_fitted_portrait_eye_and_native_pause_keep_same_fade_without_draw_clock(self):
        c=machine();start(c);view(c,0,quad.TWO_RECTS[0],True)
        c.fw(VIEW+728,-400.)  # legitimate viewport fit only changes the eye.
        state=c.read(fx.CONTROL+32,32)
        for _ in range(8):draw(c,fx.WHITE_RISE)
        self.assertEqual(len(c.rects),8)
        self.assertEqual(len(set(c.rects)),1)
        self.assertEqual(c.read(fx.CONTROL+32,32),state)

    def test_settle_and_retirement_advance_the_same_fade_before_camera_return(self):
        c=machine();start(c);view(c)
        c.w(scene.STATE+scene.S['settle_ticks'],5)
        c.w(scene.STATE+scene.S['retirement_ticks'],4)
        draw(c,1);self.assertEqual(c.rects[-1][4]>>24,fx.white_alphas()[10])
        c.w(scene.STATE+scene.S['retirement_ticks'],fx.WHITE_TICKS)
        before=len(c.rects);draw(c,1);self.assertEqual(len(c.rects),before)

    def test_changed_or_cancelled_world_never_flashes_again(self):
        cases=((tag.CONTROL+tag.C['active'],0),(tag.CONTROL+tag.C['start_requests'],8),
          (tag.CONTROL+tag.C['manager'],0),(tag.CONTROL+tag.C['count'],6),
          (scene.STATE,0),(scene.STATE+scene.S['cancelled'],1),
          (scene.STATE+scene.S['descriptor'],assets.BASE+64),
          (fx.CONTROL+fx.W['manager'],0),(fx.CONTROL+fx.W['count'],6),
          (camera.CAMERA+812,0),(VIEW,0x3F800000),(VIEW+516,512),(VIEW+520,SCISSOR_Y1+1),
          (A(0x333700),1))
        for address,value in cases:
            c=machine();start(c);view(c);c.w(address,value);draw(c,fx.WHITE_RISE)
            self.assertFalse(c.rects,(hex(address),value))
        c=machine();start(c);view(c);draw(c,-1);self.assertFalse(c.rects)

    def test_nonbeam_stale_role_or_reload_does_not_arm(self):
        for bad in ('nonbeam','nonfinisher','cancelled','retiring','victim model','stale effect'):
            c=machine()
            if bad=='nonbeam':c.w(assets.BASE+28,assets.FINISHER)
            elif bad=='nonfinisher':c.w(assets.BASE+28,assets.BEAM_PARTNER)
            elif bad in ('cancelled','retiring'):c.w(scene.STATE+scene.S[bad],1)
            elif bad=='victim model':c.w(c.models[1]+12,999)
            else:c.w(fx.CONTROL+fx.C['manager'],0)
            self.assertEqual(start(c),0,bad);self.assertEqual(c.u(fx.CONTROL+fx.W['magic']),0,bad)
        c=machine();c.r[4:6]=[0,17];run(c,fx.EXPLOSION);self.assertEqual(c.r[2],0)

    def test_native_sprite_packet_is_untextured_translucent_white(self):
        c=machine();start(c);view(c);del c.callbacks[bars.RECT]
        c.write(bars.RECT,bars.rectangle_code());c.write(bars.TEMPLATE,bars.sprite_template())
        packet=0x3900000;c.callbacks[A(0x100878)]=lambda m:m.r.__setitem__(2,packet)
        submitted=[];c.callbacks[A(0x100890)]=lambda m:submitted.append(m.r[4])
        draw(c,fx.WHITE_RISE)
        self.assertEqual(submitted,[packet+128])
        self.assertEqual(c.u(packet+80),0x20FFFFFF)
        self.assertEqual(c.u(packet+16),68,'Cs*As + Cd*(1-As), not additive flashes')
        self.assertEqual(c.u(packet+64),70,'sprite with blending and no texture')

    def test_hud_calls_white_before_cinematic_meter_is_hidden(self):
        import tag_rush_hud as th
        c=machine();start(c);view(c)
        for p,b in th.pieces():c.write(p,b)
        c.w(scene.STATE+scene.S['total_ticks'],600+fx.WHITE_RISE)
        run(c,th.DRAW)
        self.assertEqual(len(c.rects),1)
        self.assertEqual(c.rects[0][4],0x20FFFFFF)

    def test_unknown_split_rectangle_or_nonfinite_camera_does_not_flash(self):
        c=machine();start(c);view(c,0,quad.TWO_RECTS[0],True)
        c.w(VIEW+516,252);draw(c,fx.WHITE_RISE);self.assertFalse(c.rects)
        c=machine();start(c);view(c)
        c.w(VIEW,0x7FC00000);c.w(camera.CAMERA,0x7FC00000)
        draw(c,fx.WHITE_RISE);self.assertFalse(c.rects)

    def test_owned_effect_reservation_covers_receipt_and_static_parts(self):
        self.assertTrue(fx.CONTROL+max(fx.W.values())+4<=fx.ROWS)
        self.assertIn((fx.CONTROL,fx.END),fx.installation()['mutable_ranges'])
        self.assertLessEqual(fx.WHITE_DRAW+len(fx.white_draw_code()),fx.WHITE_ALPHA)
        self.assertLess(fx.WHITE_ALPHA+len(fx.white_alphas()),fx.UPDATE)
        self.assertFalse(hasattr(fx,'EXPLOSION_CORE'))


if __name__=='__main__':unittest.main()
