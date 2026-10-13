"""Tag cinematic routing in generated guest code; no emulator access."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
import tag_rush_camera as tag
import cinematic_policy as cinema
import quad_viewports as quad
import inactive_actor_guard as inactive
from test_terrain_crossing_guard import ScalarMips

MANAGER, DIRECTOR, RENDERER = 0x1900000, 0x1910000, 0x2400000
ORDINARY, AUTHORED = 0x2500000, 0x2510000


class CameraCpu(ScalarMips):
    def extra_instruction(self,ins,pc):
        op,rs,rt=ins>>26,(ins>>21)&31,(ins>>16)&31
        if op in (30,31):
            off=ins&65535;off=off if off<32768 else off-65536
            at=(self.r[rs]+off)&0xFFFFFFFF
            if op==30:self.r[rt]=int.from_bytes(self.read(at,16),'little')
            else:self.write(at,(self.r[rt]&((1<<128)-1)).to_bytes(16,'little'))
            return None
        return super().extra_instruction(ins,pc)


def cpu(active=1,shared=0,members=0b100101):
    import tag_team_rush as rush
    import tag_rush_assets as assets
    c=CameraCpu({'segments':[dict(address=p,data_hex=b.hex()) for p,b in tag.pieces()]})
    c.w(c.r[28]-22364,MANAGER);c.w(MANAGER,2)
    c.write(tag.core.MODE,struct.pack('<4I',1,6,MANAGER,6))
    c.write(tag.CONTROL,struct.pack('<7I',tag.MAGIC,MANAGER,6,1,active,members,shared))
    c.w(c.r[28]-22172,RENDERER);c.w(c.r[28]-22176,ORDINARY);c.w(c.r[28]-22180,AUTHORED)
    c.w(RENDERER+0xC40,ORDINARY+16)
    c.write(tag.CAMERA,bytes((i%251 for i in range(832))))
    c.w(tag.follow.SUCCESSOR_CONTROL+8,0);c.w(tag.follow.SUCCESSOR_CONTROL+12,2)
    c.w(rush.MEMBERS_SAVE,0x54534331);c.w(rush.MEMBERS_SAVE+20,assets.BASE+0x40)
    c.w(assets.BASE+0x40+28,assets.CUSTOM_FINISHER)
    return c


def run(c,entry):
    c.r[31]=0xFEED0000;c.run(entry)


def straight_shot(c):
    import tag_team_rush as rush
    view=(1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,50.,1.)
    c.write(tag.CAMERA,struct.pack('<32f',*view,*view))
    c.write(tag.CAMERA+720,struct.pack('<4f',0.,0.,-50.,1.))
    c.write(rush.MEMBERS_SAVE+64,struct.pack('<4f',0.,0.,0.,1.))


def camera_tail(c):
    """An ended beam scene: gameplay ownership is gone, the wide shot remains."""
    import tag_team_rush as rush
    c.write(tag.TAIL,c.read(tag.CONTROL,28));c.w(tag.TAIL,tag.TAIL_MAGIC)
    c.w(tag.TAIL+tag.ACTIVE,tag.TAIL_TICKS)
    c.w(tag.CONTROL+tag.ACTIVE,0);c.w(tag.CONTROL+tag.MEMBERS,0)
    c.w(rush.MEMBERS_SAVE,0)
    c.w(tag.A(0x2FEB38),DIRECTOR);c.w(DIRECTOR,3)
    c.w(tag.A(0x3337C0),1)


class TagCameraTests(unittest.TestCase):
    def test_burst_tail_keeps_only_camera_members_and_never_freezes_fighters(self):
        for shared in (0,1):
            c=cpu(shared=shared);camera_tail(c);c.write(inactive.ENTRY,inactive.code())
            controls=c.read(tag.CONTROL,104)
            for physical in range(8):
                c.r[4]=physical;run(c,tag.QUERY)
                expected=physical<6 and (shared or physical in (0,2,5))
                self.assertEqual(c.r[2],tag.CAMERA if expected else 0)
                actor=0x1920000+physical*0x2000;c.w(actor,physical)
                c.w(tag.core.POINTERS+4*physical,actor)
                c.r[4]=actor;c.r[31]=inactive.CALLERS[0]
                c.run(inactive.ENTRY,stops=(inactive.CALLERS[0],))
                self.assertEqual(c.r[2],0)
            self.assertEqual(c.read(tag.CONTROL,104),controls)
            self.assertEqual(c.u(tag.TAIL+tag.ACTIVE),tag.TAIL_TICKS)

    def test_burst_tail_expires_per_update_not_per_view_or_render_query(self):
        c=cpu();camera_tail(c)
        controls=c.read(tag.CONTROL,104);binding=c.u(RENDERER+0xC40)
        for remaining in range(tag.TAIL_TICKS,0,-1):
            for _ in range(4):
                c.r[4]=0;run(c,tag.QUERY);self.assertEqual(c.r[2],tag.CAMERA)
            self.assertEqual(c.u(tag.TAIL+tag.ACTIVE),remaining)
            run(c,tag.TAIL_TICK)
        self.assertEqual(c.u(tag.TAIL),0)
        c.r[4]=0;run(c,tag.QUERY);self.assertEqual(c.r[2],0)
        self.assertEqual(c.read(tag.CONTROL,104),controls)
        self.assertEqual(c.u(RENDERER+0xC40),binding)

    def test_pause_holds_tail_but_new_cinematics_and_match_transitions_cancel_it(self):
        import tag_team_rush as rush
        c=cpu();camera_tail(c);c.w(tag.A(0x333700),1)
        for _ in range(10):run(c,tag.TAIL_TICK)
        self.assertEqual(c.u(tag.TAIL+tag.ACTIVE),tag.TAIL_TICKS)
        c.w(tag.A(0x333700),0);run(c,tag.TAIL_TICK)
        self.assertEqual(c.u(tag.TAIL+tag.ACTIVE),tag.TAIL_TICKS-1)
        cases=((tag.A(0x3337B8),0x100),(tag.A(0x3337B8),0x2000),
               (MANAGER+628,1),(DIRECTOR,4),(tag.A(0x3337C0),0),
               (tag.core.MODE,0),(tag.CONTROL+12,0),(tag.CONTROL+4,MANAGER+16),
               (tag.CONTROL+tag.ACTIVE,1),(tag.CONTROL+rush.C['approaching'],1))
        for address,value in cases:
            c=cpu();camera_tail(c);c.w(address,value);before=c.read(tag.CONTROL,104)
            run(c,tag.TAIL_TICK)
            self.assertEqual(c.u(tag.TAIL),0,hex(address))
            self.assertEqual(c.read(tag.CONTROL,104),before)

    def test_burst_tail_retains_final_portrait_fit_after_actor_release(self):
        c=cpu();camera_tail(c);straight_shot(c);clone=cinema.CLONES[0]
        c.write(clone,c.read(tag.CAMERA,832));c.write(clone+512,struct.pack('<4I',*quad.TWO_RECTS[0]))
        c.r[4:6]=[clone,tag.CAMERA];run(c,tag.FIT_VIEW)
        self.assertEqual(c.r[2],clone+720);self.assertEqual(c.fr(clone+728),-100.)
        c.w(tag.TAIL,0);c.r[4:6]=[clone,tag.CAMERA];run(c,tag.FIT_VIEW)
        self.assertEqual(c.r[2],tag.CAMERA+544)

    def test_render_yields_to_native_cinematic_started_after_tail_tick(self):
        # An actor's native update follows tag.TICK. The camera query must
        # reject a cinematic started during that update, without waiting for
        # the next tag tick or overwriting the native renderer's binding.
        for address,value in ((MANAGER+628,1),(tag.A(0x3337B8),0x100),
                              (tag.A(0x3337B8),0x2000)):
            c=cpu();camera_tail(c);run(c,tag.TAIL_TICK)
            self.assertEqual(c.u(tag.TAIL+tag.ACTIVE),tag.TAIL_TICKS-1)
            c.w(address,value);c.w(c.r[28]-22176,AUTHORED)
            c.w(RENDERER+0xC40,AUTHORED+16);c.r[4]=0;run(c,tag.QUERY)
            self.assertEqual(c.r[2],0);self.assertEqual(c.u(tag.TAIL),0)
            self.assertEqual(c.u(c.r[28]-22176),AUTHORED)
            self.assertEqual(c.u(RENDERER+0xC40),AUTHORED+16)
            c.w(address,0);c.r[4]=0;run(c,tag.QUERY)
            self.assertEqual(c.r[2],0)  # the old view cannot resume afterward

    def test_render_cancels_tail_when_match_identity_changes_before_next_tick(self):
        cases=((tag.CONTROL+4,MANAGER+16),(tag.CONTROL+8,4),
               (tag.core.MODE+8,MANAGER+16),(tag.core.MODE,0),
               (tag.core.MODE+12,4),(MANAGER,3))
        for address,value in cases:
            c=cpu();camera_tail(c);c.w(address,value);c.r[4]=0
            run(c,tag.QUERY)
            self.assertEqual(c.r[2],0,hex(address));self.assertEqual(c.u(tag.TAIL),0)

    def test_coordinator_retires_tail_even_when_ordinary_gate_refuses_update(self):
        import tag_team_rush as rush
        from test_tag_rush_scene import SceneCpu
        # The coordinator uses the full register ABI; a closed menu gate must
        # still run the cosmetic cleanup before leaving that frame.
        initial=cpu();camera_tail(initial)
        c=SceneCpu({'segments':[dict(address=p,data_hex=b.hex()) for p,b in tag.pieces()]})
        for address in (tag.CONTROL,tag.TAIL,tag.core.MODE,MANAGER,DIRECTOR):
            c.write(address,initial.read(address,0x300 if address==MANAGER else 104))
        c.w(c.r[28]-22364,MANAGER);c.w(tag.A(0x2FEB38),DIRECTOR);c.w(DIRECTOR,4)
        c.write(rush.TICK,rush.tick_code())
        c.callbacks[rush.GATE]=lambda m:m.r.__setitem__(2,0)
        run(c,rush.TICK);self.assertEqual(c.u(tag.TAIL),0)
        self.assertEqual(c.u(tag.CONTROL+tag.ACTIVE),0)

    def test_bad_initial_camera_or_renderer_leaves_private_state_untouched(self):
        for global_offset,bad in ((-22176,0),(-22176,ORDINARY+1),(-22172,0),(-22172,0x7FFFF00)):
            c=cpu(active=0);before=c.read(tag.CAMERA,832);c.w(c.r[28]+global_offset,bad)
            run(c,tag.INIT);self.assertEqual(c.r[2],0);self.assertEqual(c.read(tag.CAMERA,832),before)

    def test_selective_hold_preserves_global_queries_and_releases_on_completion(self):
        for shared in (0,1):
            for physical in range(6):
                c=cpu(shared=shared);c.write(inactive.ENTRY,inactive.code())
                actor=0x1920000+physical*0x2000;c.w(actor,physical);c.w(tag.core.POINTERS+4*physical,actor)
                c.r[4]=actor;c.r[31]=inactive.CALLERS[0];c.run(inactive.ENTRY,stops=(inactive.CALLERS[0],))
                self.assertEqual(c.r[2],int(bool(shared or physical in (0,2,5))))
                c.r[4]=actor;run(c,inactive.ENTRY);self.assertEqual(c.r[2],0)
                c.w(tag.CONTROL+tag.ACTIVE,0);c.r[4]=actor;c.r[31]=inactive.CALLERS[0]
                c.run(inactive.ENTRY,stops=(inactive.CALLERS[0],));self.assertEqual(c.r[2],0)

    def test_initialization_keeps_existing_render_binding(self):
        c=cpu(active=0);c.write(ORDINARY,bytes((i%253 for i in range(832))))
        def template(m):
            self.assertEqual((m.r[4],m.r[5]),(tag.CAMERA,0));m.w(m.r[28]-22176,tag.CAMERA)
        c.callbacks[tag.A(0x23E950)]=template;run(c,tag.INIT)
        self.assertEqual(c.r[2],1);self.assertEqual(c.u(tag.CAMERA+812),1)
        self.assertEqual(c.u(c.r[28]-22176),ORDINARY)
        self.assertEqual(c.u(RENDERER+0xC40),ORDINARY+16)
        self.assertEqual(c.u(c.r[28]-22180),AUTHORED)

    def test_only_members_follow_unless_shared(self):
        for shared in (0,1):
            c=cpu(shared=shared)
            for physical in range(8):
                c.r[4]=physical;run(c,tag.QUERY)
                expected=physical<6 and (shared or physical in (0,2,5))
                self.assertEqual(c.r[2],tag.CAMERA if expected else 0)

    def test_stale_disabled_or_inactive_control_never_routes(self):
        for address,value in ((tag.CONTROL,0),(tag.CONTROL+4,MANAGER+16),(tag.CONTROL+8,4),
                              (tag.CONTROL+12,0),(tag.CONTROL+16,0),(tag.CONTROL+16,2)):
            c=cpu(shared=1);c.w(address,value);c.r[4]=0;run(c,tag.QUERY)
            self.assertEqual(c.r[2],0)

    def test_update_restores_native_track_active_view_and_renderer_pointer(self):
        c=cpu();before=(c.u(c.r[28]-22180),c.u(c.r[28]-22176),c.u(RENDERER+0xC40))
        seen=[]
        def update(m):
            seen.append(m.r[4]);self.assertEqual(m.r[4:8],[tag.CAMERA,tag.CAMERA+64,tag.CAMERA+720,tag.CAMERA+736])
            self.assertEqual(m.u(m.r[28]-22180),AUTHORED);m.write(tag.CAMERA,bytes(range(128)))
            m.w(m.r[28]-22176,tag.CAMERA);m.w(RENDERER+0xC40,tag.CAMERA)
        c.callbacks[tag.A(0x23E608)]=update
        c.callbacks[tag.A(0x23E598)]=lambda m:None
        c.callbacks[tag.A(0x23E6A0)]=lambda m:self.assertEqual((m.r[4],m.r[5]),(ORDINARY,1))
        run(c,tag.UPDATE)
        self.assertEqual(seen,[tag.CAMERA])
        self.assertEqual((c.u(c.r[28]-22180),c.u(c.r[28]-22176),c.u(RENDERER+0xC40)),before)
        c.w(tag.CONTROL+tag.ACTIVE,0);run(c,tag.UPDATE);self.assertEqual(len(seen),1)

    def test_single_player_private_camera_and_uninvolved_view(self):
        for member in (True,False):
            c=cpu();c.w(tag.follow.SUCCESSOR_CONTROL+8,0 if member else 1);bound=[]
            for address in (0x12AB10,0x12A9E8,0x23EE08):
                c.callbacks[tag.A(address)]=lambda m:m.r.__setitem__(2,0)
            c.callbacks[tag.A(0x23E6A0)]=lambda m:bound.append(m.r[4])
            run(c,tag.SELECT)
            self.assertEqual(c.r[2],1 if member else 0xFFFFFFFF)
            self.assertEqual(bound,[tag.CAMERA] if member else [])

    def test_two_views_keep_split_or_share_by_setting(self):
        for shared in (0,1):
            c=cpu(shared=shared);bound=[]
            c.callbacks[tag.A(0x12AB10)]=lambda m:m.r.__setitem__(2,1)
            c.callbacks[tag.A(0x12A9E8)]=lambda m:m.r.__setitem__(2,0)
            for address in (0x23EF98,0x23EE78):c.callbacks[tag.A(address)]=lambda m:None
            c.callbacks[tag.A(0x23E6A0)]=lambda m:bound.append(m.r[4])
            run(c,tag.SELECT)
            self.assertEqual(c.r[2],int(bool(shared)))
            self.assertEqual(bound,[tag.CAMERA] if shared else [])

    def test_two_player_binding_keeps_pose_and_uses_each_side_projection(self):
        for side in range(2):
            c=cpu();c.write(cinema.BIND,cinema.bind());c.write(cinema.CONTROL,struct.pack('<4I',cinema.MAGIC,MANAGER,6,DIRECTOR))
            c.w(cinema.team_intro.BATTLE,DIRECTOR);c.w(DIRECTOR,3)
            c.w(c.r[28]-22176,RENDERER+(0x720 if side==0 else 0x9B0))
            c.callbacks[cinema.ULTIMATE_OWNER]=lambda m:m.r.__setitem__(2,0)
            c.callbacks[tag.A(0x12AB10)]=lambda m:m.r.__setitem__(2,1)
            c.callbacks[tag.A(0x12A9E8)]=lambda m:m.r.__setitem__(2,0)
            c.fw(tag.CAMERA+568,.75);c.fw(tag.CAMERA+572,1.)
            straight_shot(c)
            source=c.read(tag.CAMERA,832);clones=[];order=[]
            def template(m):
                clones.append((m.r[4],m.r[5]));m.write(m.r[4],bytes(128))
                m.write(m.r[4]+512,struct.pack('<4I',*quad.TWO_RECTS[side]))
                m.fw(m.r[4]+568,.75);m.fw(m.r[4]+572,1.);order.append('template')
            c.callbacks[tag.A(0x23E950)]=template
            c.callbacks[tag.A(0x23E040)]=lambda m:order.append('projection')
            c.callbacks[tag.A(0x23E598)]=lambda m:order.append('view')
            c.callbacks[tag.A(0x23E6A0)]=lambda m:None
            c.r[4]=1;run(c,cinema.BIND)
            clone=cinema.CLONES[side]
            self.assertEqual(clones,[(clone,side+1)])
            expected=bytearray(c.read(tag.CAMERA,128))
            for off in (56,120):struct.pack_into('<f',expected,off,100.)
            self.assertEqual(c.read(clone,128),expected)
            self.assertEqual(c.u(c.r[28]-22180),AUTHORED)
            self.assertEqual(c.u(c.r[28]-22176),clone)
            self.assertEqual((c.fr(clone+568),c.fr(clone+572)),(.75,1.))
            self.assertEqual(order,['template','view'])
            self.assertEqual(c.fr(clone+728),-100.)
            self.assertEqual(c.read(tag.CAMERA,832),source)

    def test_split_dolly_preserves_lens_and_never_compounds(self):
        for lens in ((1.,1.),(.75,1.),(.81,.96)):
            for rect in quad.TWO_RECTS:
                c=cpu();clone=cinema.CLONES[0];straight_shot(c)
                c.write(clone,c.read(tag.CAMERA,128))
                c.write(clone+512,struct.pack('<4I',*rect))
                for off,value in zip((568,572),lens):
                    c.fw(tag.CAMERA+off,value);c.fw(clone+off,value)
                source=c.read(tag.CAMERA,832)
                for _ in range(2):
                    c.r[4:6]=[clone,tag.CAMERA];run(c,tag.FIT_VIEW)
                    for off,value in zip((568,572),lens):
                        self.assertAlmostEqual(c.fr(clone+off),value,places=6)
                    self.assertEqual(c.r[2],clone+720)
                    self.assertEqual(c.fr(clone+728),-100.)
                    for off in (56,120):self.assertEqual(c.fr(clone+off),100.)
                self.assertEqual(c.read(tag.CAMERA,832),source)
                self.assertEqual(struct.unpack('<4I',c.read(clone+512,16)),rect)
                self.assertEqual(c.u(c.r[28]-22176),ORDINARY)
                self.assertEqual(c.u(c.r[28]-22180),AUTHORED)
                self.assertEqual(c.u(RENDERER+0xC40),ORDINARY+16)

    def test_split_dolly_preserves_rotated_and_rolled_camera_axes(self):
        import tag_team_rush as rush
        c=cpu();clone=cinema.CLONES[0]
        # Forward +X, rolled right/down; the focal point remains at camera Z100.
        view=(0.,0.,1.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,50.,1.)
        c.write(tag.CAMERA,struct.pack('<32f',*view,*view));c.write(clone,c.read(tag.CAMERA,128))
        c.write(tag.CAMERA+720,struct.pack('<4f',-50.,0.,0.,1.))
        c.write(rush.MEMBERS_SAVE+64,struct.pack('<4f',0.,0.,0.,1.))
        c.write(clone+512,struct.pack('<4I',*quad.TWO_RECTS[1]))
        c.r[4:6]=[clone,tag.CAMERA];run(c,tag.FIT_VIEW)
        self.assertEqual(struct.unpack('<3f',c.read(clone+720,12)),(-100.,0.,0.))
        self.assertEqual(c.read(clone+64,48),c.read(tag.CAMERA+64,48))
        self.assertEqual(c.fr(clone+120),100.)

    def test_split_fit_rejects_fullscreen_quarters_foreign_and_source_itself(self):
        full=(0,511,0,quad.SCISSOR_Y1)
        cases=[(cinema.CLONES[0],tag.CAMERA,rect) for rect in (full,*quad.RECTS,*quad.THREE_RECTS)]
        cases.extend(((cinema.CLONES[0],AUTHORED,quad.TWO_RECTS[0]),
                      (tag.CAMERA,tag.CAMERA,quad.TWO_RECTS[0]),
                      (cinema.CLONES[0],tag.CAMERA,(10,264,0,quad.SCISSOR_Y1))))
        for clone,source,rect in cases:
            c=cpu();c.write(clone+512,struct.pack('<4I',*rect));before=c.read(clone,832)
            c.r[4:6]=[clone,source];run(c,tag.FIT_VIEW)
            self.assertEqual(c.read(clone,832),before,(source,rect))

    def test_native_opening_cuts_and_invalid_descriptors_never_get_dollied(self):
        import tag_team_rush as rush
        import tag_rush_assets as assets
        for address,value in ((assets.BASE+0x40+28,0),(assets.BASE+0x40+28,assets.BEAM_LEAD),
                              (rush.MEMBERS_SAVE,0),(rush.MEMBERS_SAVE+20,0),
                              (rush.MEMBERS_SAVE+20,assets.BASE+1),
                              (rush.MEMBERS_SAVE+20,assets.END-48)):
            c=cpu();straight_shot(c);clone=cinema.CLONES[0]
            c.write(clone,c.read(tag.CAMERA,832));c.write(clone+512,struct.pack('<4I',*quad.TWO_RECTS[0]))
            c.w(address,value);before=c.read(clone,832)
            c.r[4:6]=[clone,tag.CAMERA];run(c,tag.FIT_VIEW)
            self.assertEqual(c.r[2],tag.CAMERA+544)
            self.assertEqual(c.read(clone,832),before)

    def test_custom_dolly_uses_translated_authored_focus_not_world_origin(self):
        import tag_team_rush as rush
        c=cpu();straight_shot(c);clone=cinema.CLONES[0]
        c.write(tag.CAMERA+720,struct.pack('<4f',62.,-278.,-133.,1.))
        c.write(rush.MEMBERS_SAVE+64,struct.pack('<4f',62.,-278.,-103.,1.))
        c.write(clone,c.read(tag.CAMERA,832));c.write(clone+512,struct.pack('<4I',*quad.TWO_RECTS[0]))
        c.r[4:6]=[clone,tag.CAMERA];run(c,tag.FIT_VIEW)
        self.assertEqual(struct.unpack('<3f',c.read(clone+720,12)),(62.,-278.,-163.))

    def test_charge_closeup_stays_close_then_smoothly_rejoins_wide_fit(self):
        import tag_team_rush as rush
        import tag_rush_assets as assets
        from native_map import ACTOR_HZ
        from test_tag_rush_scene import SceneCpu
        for frame in (2,30,60,74,90,120,180):
            c=cpu();c.__class__=SceneCpu;straight_shot(c);clone=cinema.CLONES[0]
            c.w(assets.BASE+0x40+28,assets.CUSTOM_FINISHER|assets.CHARGE_BEAM|assets.BEAM_LEAD)
            ticks=round(frame*ACTOR_HZ/60);c.w(rush.MEMBERS_SAVE+8,ticks)
            c.write(clone,c.read(tag.CAMERA,832));c.write(clone+512,struct.pack('<4I',*quad.TWO_RECTS[0]))
            c.r[4:6]=[clone,tag.CAMERA];run(c,tag.FIT_VIEW)
            fraction=max(0.,min(1.,(ticks*60/ACTOR_HZ-60)/30))
            weight=fraction*fraction*(3-2*fraction)
            self.assertAlmostEqual(c.fr(clone+728),-50.*(1+weight),places=4)
            self.assertAlmostEqual(c.fr(clone+120),50.*(1+weight),places=4)
            self.assertEqual(c.r[2],tag.CAMERA+544 if weight==0 else clone+720)

    def test_split_fit_reservation_precedes_authored_camera_builder(self):
        import tag_rush_shots as shots
        pieces=tag.pieces()
        self.assertLessEqual(tag.QUERY+len(tag.query_code()),tag.FIT_VIEW)
        self.assertLessEqual(tag.FIT_VIEW+len(tag.fit_view_code()),shots.UPDATE)
        self.assertEqual(pieces[-1][0],tag.FIT_VIEW)

    def test_every_multiview_member_gets_private_camera_without_changing_rect(self):
        for humans in (2,3,4):
            for view,rect in enumerate(quad.rectangles(humans)):
                c=cpu();c.write(quad.PREPARE,quad.prepare());c.w(quad.CONTROL+quad.VIEW_COUNT,humans)
                straight_shot(c)
                c.w(quad.SUBJECTS+view*4,view);actor=0x1920000+view*0x2000
                c.w(quad.core.POINTERS+4*view,actor);c.w(actor,view);c.w(actor+12,view)
                for base in (RENDERER,tag.CAMERA):
                    c.fw(base+568,.75);c.fw(base+572,1.)
                for address in (0x23E040,0x207DD0,0x207E78,0x23E598):c.callbacks[tag.A(address)]=lambda m:m.r.__setitem__(2,0)
                follow=[]
                c.callbacks[cinema.VIEW]=lambda m:m.r.__setitem__(2,0)
                c.callbacks[tag.A(0x23EAD0)]=lambda m:follow.append(m.r[4])
                before=c.u(tag.follow.SUCCESSOR_CONTROL+8);c.r[4]=view;run(c,quad.PREPARE)
                at=quad.CAMERAS+view*1024
                self.assertEqual(struct.unpack('<4I',c.read(at+512,16)),rect)
                self.assertEqual(c.u(tag.follow.SUCCESSOR_CONTROL+8),before)
                self.assertEqual(c.u(c.r[28]-22180),AUTHORED)
                if view in (0,2):
                    expected=bytearray(c.read(tag.CAMERA,128))
                    if humans==2:
                        for off in (56,120):struct.pack_into('<f',expected,off,100.)
                    self.assertEqual(c.read(at,128),expected);self.assertFalse(follow)
                else:self.assertEqual(follow,[at])
                scale=1. if humans==2 else .5
                self.assertEqual((c.fr(at+568),c.fr(at+572)),(.75*scale,scale))


if __name__=='__main__':unittest.main()
