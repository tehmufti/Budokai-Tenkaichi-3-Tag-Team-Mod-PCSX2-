"""Grounded Future Trunks + Vegeta exchange: eligibility, shared opening, native sources, schedules."""
import math
import struct
import unittest

import tag_rush_assets as assets
import tag_rush_blue_native as blue
import tag_rush_galick_pair as galick
import tag_rush_scene as scene
import tag_team_rush as tag


def disc():
    import bt4_disc
    from pathlib import Path
    return bt4_disc.ISO if Path(bt4_disc.ISO).exists() else None


class EligibilityTests(unittest.TestCase):
    def test_every_form_of_the_blue_vegeta_line_and_of_future_trunks_super(self):
        for lead in blue.TRUNKS:
            for partner in blue.VEGETA_LINE:
                self.assertEqual(blue.pair(lead,partner),blue.NAMES[1])
                self.assertEqual(blue.pair(partner,lead),blue.NAMES[1])
        self.assertEqual(blue.pair(122,35),blue.NAMES[0])
        # Other Vegetas (Scouter, Majin, SSJ3, GT, Baby) and other Trunks never qualify,
        # nor Goku Blue with a non-Blue Vegeta form (that pair keeps the ordinary variants).
        for other in (29,30,37,38,140,208,217,218,219):
            for lead in blue.TRUNKS:self.assertIsNone(blue.pair(lead,other))
        for other in (39,40,41,42,43,44,45,227,228):self.assertIsNone(blue.pair(other,35))
        for vegeta in (31,32,33,36,68,113):self.assertIsNone(blue.pair(122,vegeta))

    def test_forms_match_the_disc_transformation_graph(self):
        import compatibility_profile
        rows={r['character_id']:r for r in compatibility_profile.profile()['characters']}
        graph={c:set(r['form_targets'])-{3} for c,r in rows.items()}
        def reach(start):
            seen={start};todo=[start]
            while todo:
                for nxt in graph.get(todo.pop(),()):
                    if nxt not in seen:seen.add(nxt);todo.append(nxt)
            return seen
        self.assertEqual(set(blue.VEGETA_LINE),{c for c in graph if blue.VEGETA_BLUE in reach(c)})
        self.assertEqual(set(blue.TRUNKS),reach(225))
        for c in blue.TRUNKS:self.assertEqual(rows[c]['name'],'Trunks (DBS)')
        for c in blue.VEGETA_LINE:self.assertIn('Vegeta',rows[c]['name'])


class SharedOpeningTests(unittest.TestCase):
    def test_both_variants_open_with_the_exact_native_sadistic_dance_phases(self):
        import tag_rush_choreography as choreography
        two_ki=assets.timeline('two_ki')[:4];records=choreography.records('two_ki')[:4]
        for name in blue.NAMES:
            phases=assets.timeline(name)
            self.assertEqual(phases[:blue.INTRO],assets.OPENING)
            self.assertEqual(phases[:4],two_ki)
            self.assertEqual(choreography.records(name)[:4],records)
            self.assertEqual(blue.placements(name,assets.NATIVE_STAGING)[:4],assets.NATIVE_STAGING[:4])
            self.assertTrue(all(p.flags&blue.FLAG for p in phases[blue.INTRO:]))
            self.assertFalse(any(p.flags&(blue.FLAG|assets.CUSTOM_FINISHER) for p in phases[:blue.INTRO]))
            self.assertLessEqual(len(phases),choreography.MAX_PHASES)
            pack=dict(role_donors=111,bindings=(222,333))
            self.assertEqual([blue.phase_donors(name,i,pack) for i in range(len(phases))],
                             [111]*4+[(222,333)[blue.NAMES.index(name)]]*(len(phases)-4))

    def test_fx_keeps_one_emitter_per_role_across_phases_on_the_native_clock(self):
        from test_tag_rush_scene import SceneCpu
        from test_tag_rush_camera import run
        import tag_rush_effects as effects
        for variant,name in zip(blue.VARIANTS,blue.NAMES):
            c=SceneCpu({'segments':[dict(address=a,data_hex=b.hex()) for a,b in blue.pieces()]})
            fx=blue.DATA+0x400;edges=blue.DATA+0x300;own=blue.own_edges(name)
            c.write(blue.DATA,struct.pack('<4I',blue.MAGIC,2,fx,0))
            c.write(edges,struct.pack('<%dI'%len(own),*own))
            c.write(blue.TABLES+blue.TABLE_SIZE*(variant-5),struct.pack('<9I',own[-1]//2+1,len(own)-1,0,0,0,0,0,edges,0))
            hit=blue.burst(name)
            c.write(fx+32*(variant-5),struct.pack('<8I',*(v for row in blue.beam_schedule(name) for v in row),
                                                  blue._absolute(name,*hit),0))
            c.w(tag.CONTROL+tag.C['variant'],variant);c.w(scene.STATE,scene.SCENE_MAGIC)
            events=[]
            def log(kind):
                def call(m):
                    now=own[m.u(scene.STATE+scene.S['phase'])-blue.INTRO]+m.u(scene.STATE+scene.S['ticks'])*2
                    events.append((kind,m.r[4] if kind!='ignite' else (m.r[4]-effects.ROWS)//effects.STRIDE,now));m.r[2]=1
                return call
            for entry,kind in ((effects.CHARGE_SPAWN,'charge'),(effects.SPAWN,'spawn'),(effects.IGNITE,'ignite'),(effects.EXPLOSION,'burst')):
                c.callbacks[entry]=log(kind)
            c.callbacks[effects.UPDATE]=lambda m:m.r.__setitem__(2,1)
            for phase in range(len(own)-1):
                for ticks in range(0,(own[phase+1]-own[phase])//2+1):
                    c.w(scene.STATE+scene.S['phase'],blue.INTRO+phase);c.w(scene.STATE+scene.S['ticks'],ticks)
                    run(c,blue.FX);self.assertEqual(c.r[2],1)
            schedule=blue.beam_schedule(name);burst=blue._absolute(name,*hit)
            expected=[]
            for role,(charge,fire,end) in enumerate(schedule):
                expected+=[('charge',role,charge),('ignite',role,fire)]
            expected.append(('burst',2,burst))
            # Charges/ignitions happen on the first tick at or after their frame.
            got=sorted(events,key=lambda e:(e[0],e[1]))
            self.assertEqual(sorted((k,r) for k,r,_ in events),sorted((k,r) for k,r,_ in expected),name)
            for kind,role,frame in expected:
                at=next(t for k,r,t in events if (k,r)==(kind,role))
                self.assertTrue(frame<=at<frame+2,(name,kind,role,frame,at))


class NativeSourceTests(unittest.TestCase):
    def test_victim_finishes_the_blowaway_without_the_old_frozen_tail(self):
        victim=[phase[2][1]for phase in galick.plans()]
        self.assertEqual(victim[5],[(361,36,112,48)])
        self.assertEqual(victim[6],[(361,112,112,12)])
        self.assertEqual(galick.FRAMES[5:],(48,12))
        self.assertLessEqual(sum(galick.FRAMES[5:])-galick.BURST_FRAME,54)

    def test_native_beam_growth_is_smooth_bounded_and_only_writes_its_body_scale(self):
        from test_tag_rush_effects import machine
        from test_tag_rush_camera import run
        import tag_rush_effects as effects
        c=machine();body=0x3700000;c.r[4]=body
        c.w(tag.CONTROL+tag.C['variant'],6)
        c.w(body+1416,0x12345678);c.w(body+1424,0x87654321)
        values=[]
        for phase in (3,4,5,6):
            for ticks in range(36):
                c.w(scene.STATE+scene.S['phase'],blue.INTRO+phase)
                c.w(scene.STATE+scene.S['ticks'],ticks)
                run(c,effects.BALL_GROW)
                actual=struct.unpack('<f',c.read(body+1420,4))[0]
                self.assertAlmostEqual(actual,galick.beam_scale(phase,ticks),places=5)
                self.assertTrue(1.<=actual<=galick.BEAM_FINAL_SCALE+1e-6)
                if phase==4:values.append(actual)
        self.assertEqual(values,sorted(values))
        self.assertEqual(c.u(body+1416),0x12345678);self.assertEqual(c.u(body+1424),0x87654321)

    def test_plan_uses_gohans_ultimate_victim_clips_and_the_galick_gun_pose(self):
        plan=galick.plans();victim={a for phase in plan for a,*_ in phase[2][1]}
        self.assertEqual(victim,{357,358,359,360,361})
        self.assertTrue(all(phase[2][0]==16 for phase in plan))
        attackers={a for phase in plan for role in (0,1) for a,*_ in phase[role][1]}
        self.assertEqual(attackers,{38,43,45,261,262,263,264,267})
        self.assertEqual(galick.DONORS,(29,29,0))
        self.assertEqual([sum(s[3] for s in row[1]) for phase in plan for row in phase],
                         [f for f in galick.FRAMES for _ in range(3)])
        # The beat order of the native ultimate: catch, hold, push back, the
        # second beam, deadlock, overpowered and blown away.
        firsts=[phase[2][1][-1][0] for phase in plan]
        self.assertEqual(firsts,[357,358,358,359,361,361,361])

    def test_beam_schedule_trunks_first_vegeta_after_landing_one_burst(self):
        (c0,f0,e0),(c1,f1,e1)=galick.beam_schedule()
        self.assertEqual((c0,f0),(0,galick.TRUNKS_FIRE))
        self.assertGreater(c1,galick.EDGES[1]+galick.LANDING)
        self.assertLess(c1,f1);self.assertLess(f1,galick.EDGES[3])
        burst=galick.EDGES[galick.BURST_PHASE]+galick.BURST_FRAME
        self.assertLess(f1,burst);self.assertLess(burst,e0);self.assertEqual(e0,e1)
        self.assertLess(e0,galick.EDGES[6])
        phases=galick.timeline()
        self.assertEqual([bool(p.flags&assets.FINISHER) for p in phases],[i==galick.BURST_PHASE for i in range(7)])
        self.assertTrue(phases[0].flags&assets.BEAM_LEAD and phases[2].flags&assets.BEAM_PARTNER)
        self.assertEqual(blue.burst(blue.NAMES[1]),(blue.INTRO+galick.BURST_PHASE,galick.BURST_FRAME))
        self.assertEqual(blue.charge_cues(blue.NAMES[1],blue.INTRO),((0,0),))
        self.assertEqual(blue.charge_cues(blue.NAMES[1],blue.INTRO+1),((1,c1-galick.EDGES[1]),))
        self.assertEqual(blue.charge_cues(blue.NAMES[1],blue.INTRO+3),())

    def test_everyone_stands_on_the_ground_and_vegeta_lands_beside_trunks(self):
        travel=[[(0.,0.,0.)]*(galick.EDGES[-1]+1) for _ in range(3)]
        for frame in range(0,galick.EDGES[-1]+1,2):
            t,v,x=galick.roots_at(frame,travel)
            self.assertEqual((t[1][3],x[1][3]),(0.,0.))
            if frame>=galick.EDGES[1]+galick.LANDING:self.assertEqual(v[1][3],0.)
            if frame<galick.EDGES[1]:self.assertLess(v[1][3],-200.)
        _,v,_=galick.roots_at(galick.EDGES[-1],travel)
        self.assertAlmostEqual(math.hypot(v[0][3],v[2][3]-galick.DISTANCE),math.hypot(galick.SIDE,galick.BEHIND))

    def test_native_forward_axes_aim_at_the_opponent_instead_of_a_half_turn_away(self):
        import numpy as np
        travel=[[(0.,0.,-frame*.1 if role==2 else 0.) for frame in range(galick.EDGES[-1]+1)] for role in range(3)]
        for frame in range(0,galick.EDGES[-1]+1,2):
            roots=[np.asarray(m) for m in galick.roots_at(frame,travel)]
            for role in range(3):
                direction=roots[role][:3,:3]@np.asarray((0.,0.,-1. if role<2 else 1.))
                delta=roots[2 if role<2 else 0][:3,3]-roots[role][:3,3];delta[1]=0.
                delta/=np.linalg.norm(delta)
                self.assertGreater(float(direction@delta),.99999,(frame,role))

    def test_vegeta_descends_lands_and_then_enters_the_charge_pose(self):
        phase=galick.plans()[1][1][1]
        self.assertEqual([s[0] for s in phase],[38,43,43,45,261,262])
        at=0;starts={}
        for animation,_,_,duration in phase:
            starts.setdefault(animation,at);at+=duration
        self.assertEqual(starts[45],galick.LANDING)
        self.assertEqual(starts[261],galick.LANDING+galick.LAND_FRAMES)
        self.assertEqual(starts[262]+galick.EDGES[1],galick.VEGETA_CHARGE)
        self.assertEqual(set(galick.ENTRANCE_BLENDS),{(38,43),(43,45),(45,261)})

    def test_arrival_camera_tracks_vegeta_through_the_whole_descent_shot(self):
        import numpy as np
        travel=[[(0.,0.,0.)]*(galick.EDGES[-1]+1) for _ in range(3)]
        for frame in range(galick.EDGES[1],galick.EDGES[1]+50,2):
            (right,down,forward,eye),focus=galick.camera_at(frame,travel)
            position=galick.vegeta_position(frame)
            self.assertAlmostEqual(focus[1],position[1]-12.,places=5)
            self.assertLess(math.dist(eye,focus),55.)
            np.testing.assert_allclose(np.cross(down,forward),right,atol=1e-6)

    @unittest.skipUnless(disc(),'BT4 disc not available')
    def test_disc_clips_decode_within_native_scratch_and_root_travel_moves_the_actor(self):
        from model_animations import AnimationClip
        clips=galick.prepared_clips(disc())
        self.assertEqual(len(clips),21)
        for source,raw in clips.items():
            self.assertLessEqual(len(raw),0xC000)
            clip=AnimationClip.from_decoded(source.animation,raw)
            self.assertNotIn(1,{t.bone_id for t in clip.tracks})
            root=next(t for t in clip.tracks if t.bone_id==0).evaluate(clip.frame_count/2)
            self.assertIn(root.translation,(None,(0.,0.,0.)))
        _,travel=galick._build(disc())
        victim=travel[2]
        self.assertEqual(len(victim),galick.EDGES[-1]+1)
        self.assertAlmostEqual(victim[galick.EDGES[3]][2],0.,places=3)
        self.assertLess(victim[galick.EDGES[4]][2],-15.)   # 359 slides back about 20
        self.assertLess(victim[galick.EDGES[6]][2],-95.)   # 361 blows the victim away about 100
        self.assertTrue(all(b[2]<=a[2]+.5 for a,b in zip(victim,victim[1:])))

    @unittest.skipUnless(disc(),'BT4 disc not available')
    def test_built_tables_and_fx_schedule_are_published_for_variant6(self):
        built=blue.build(disc());data=built['blocks'][0][1]
        self.assertEqual(struct.unpack_from('<4I',data,0)[:2],(blue.MAGIC,2))
        table=struct.unpack_from('<9I',data,blue.TABLES-blue.DATA+blue.TABLE_SIZE)
        self.assertEqual(table[:3],(galick.EDGES[-1]//2+1,7,blue.GROUND))
        self.assertEqual(struct.unpack_from('<8I',data,table[7]-blue.DATA),galick.EDGES)
        fx=struct.unpack_from('<8I',data,built['fx_table']-blue.DATA+32)
        self.assertEqual(fx[:6],tuple(v for row in galick.beam_schedule() for v in row))
        self.assertEqual(fx[6],galick.EDGES[galick.BURST_PHASE]+galick.BURST_FRAME)
        self.assertLessEqual(blue.DATA+built['bytes_used'],blue.END)


if __name__=='__main__':unittest.main()
