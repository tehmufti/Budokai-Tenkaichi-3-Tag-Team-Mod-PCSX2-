"""Airborne native finisher sources, real root placement and private framing."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import json
import struct
import unittest
from pathlib import Path
import tag_rush_assets as assets,tag_rush_choreography as choreography
import tag_rush_staging as staging,tag_rush_shots as shots,tag_rush_camera as camera
import tag_team_rush as tag
from native_map import A
from test_tag_rush_camera import cpu,run
from test_tag_rush_scene import SceneCpu

STATE=tag.MEMBERS_SAVE
ROWS=STATE+0x100
TABLE=assets.BASE+0x100
MODEL=0x2800000
ACTOR=0x2900000
BONE=0x2A00000


def machine(variant=0,phase=4):
    c=cpu();c.__class__=SceneCpu
    for p,b in staging.pieces():c.write(p,b)
    names=choreography.VARIANTS
    data,_=choreography.pack_records(names,TABLE);c.write(TABLE,data)
    c.w(tag.CONTROL+staging.TABLE_OFFSET,TABLE);c.w(tag.CONTROL+tag.C['variant'],variant)
    c.w(STATE+4,phase);c.w(STATE+8,1)
    c.w(staging.fp.arena_bounds.STAGE,0x2B00000);c.w(0x2B00000+64,0x2B00100)
    c.write(0x2B00100,struct.pack('<3f',1000.,-350.,100.))
    c.write(STATE+104,struct.pack('<2f',1.,1.));c.fw(STATE+36,-40.)
    c.write(STATE+112,struct.pack('<8f',100.,-40.,200.,1.,0.,0.,0.,0.))
    for role in range(3):
        row=ROWS+role*0x200;model=MODEL+role*0x2000;actor=ACTOR+role*0x2000;bone=BONE+role*0x100
        c.w(row+4,actor);c.w(row+8,model);c.w(model+3436+12,bone)
        c.write(model+2384,struct.pack('<4f',100.,-100.,200.,1.))
        c.write(bone+64,struct.pack('<4f',100.,-110.,200.,1.))
    c.callbacks[A(0x11F588)]=lambda m:m.set_number(0,math.sin(m.number(12)))
    c.callbacks[A(0x11F620)]=lambda m:m.set_number(0,math.cos(m.number(12)))
    def query(m):
        if m.number(12)!=-350.:raise AssertionError('Terrain query must start at the arena ceiling')
        for off in staging.fp.terrain.QUERY_GLOBALS:m.w(m.r[28]+off,0xBAD)
        m.set_number(0,5.);m.r[2]=1
    c.callbacks[staging.safety.QUERY]=query
    # Real FLOOR's airborne result is zero; APPLY must not mistake that for
    # an absence of terrain beneath the grounded finisher marks.
    c.callbacks[staging.safety.FLOOR]=lambda m:m.r.__setitem__(2,0)
    def place(m):
        role=(m.r[4]-ACTOR)//0x2000;model=MODEL+role*0x2000;bone=BONE+role*0x100
        old=struct.unpack('<3f',m.read(model+2384,12));new=struct.unpack('<3f',m.read(m.r[5],12))
        hip=struct.unpack('<3f',m.read(bone+64,12))
        c.write(bone+64,struct.pack('<3f',*(p+n-o for p,n,o in zip(hip,new,old))))
        m.write(model+2384,m.read(m.r[5],16));m.write(model+2400,m.read(m.r[6],16))
    c.callbacks[A(0x1D7418)]=place
    for addr in (0x24E2B0,0x24E3F8):c.callbacks[A(addr)]=lambda m:None
    return c


def apply(c,role):
    c.r[4]=c.u(STATE+4);run(c,staging.QUERY);record=c.r[2]
    c.r[4:8]=[role,ROWS+role*0x200,record,STATE];run(c,staging.APPLY)
    return c.r[2]


class ChoreographyTests(unittest.TestCase):
    def test_beam_burst_uses_firing_time_for_clearance_without_changing_opening(self):
        import tag_rush_scene as scene
        native_marks=[(0,0,0,0,choreography.ZERO,choreography.ZERO,choreography.ZERO)]*4
        for name in choreography.VARIANTS:
            if name in ('blue_galick_kamehameha','super_galick_pair'):continue  # Independent full cinematic, covered by its bank tests.
            timeline=assets.timeline(name)
            if name!='early_goku_piccolo':
                self.assertEqual([p.source_frames for p in timeline[:4]],[68,99,149,119])
                self.assertEqual(choreography.records(name)[:4],native_marks)
            if name=='two_melee':continue
            self.assertEqual(timeline[-1].source_frames,choreography.BEAM_FRAMES)
            burst=choreography.beam_burst_frame(timeline[-1].source_frames,custom=True)
            self.assertEqual(burst-choreography.BEAM_START,6)
            for hz in (25,30):
                clearance=(choreography.BEAM_FRAMES-burst)/60+scene.burst_settle_ticks(hz,custom=True)/hz
                self.assertGreaterEqual(clearance,2.1-1e-9)
                self.assertLess(clearance,2.14)
                self.assertGreaterEqual(scene.burst_settle_ticks(hz)/hz-scene.burst_settle_ticks(hz,custom=True)/hz,.87)
        self.assertEqual(choreography.beam_burst_frame(262),232)
        for duration in (None,True,30,90,96,1001):
            with self.assertRaises(ValueError):choreography.beam_burst_frame(duration,custom=True)

    def test_native_set_root_faces_each_attacker_toward_the_victim(self):
        # Execute the real native setter, not the preview quaternion. The
        # live mixed capture showed hand45 extending away under the old yaw0.
        from extra_throws import NATIVE
        for variant_index,name in enumerate(choreography.VARIANTS):
            if name in ('blue_galick_kamehameha','super_galick_pair'):continue
            for phase in range(4,len(choreography.records(name))):
                c=machine(variant_index,phase);c.fw(STATE+132,.6981317)
                c.write(A(0x1D7418),NATIVE(A(0x1D7418),0x158))
                del c.callbacks[A(0x1D7418)]
                c.callbacks[A(0x1DC298)]=lambda m:m.r.__setitem__(2,m.r[4]+16)
                c.callbacks[A(0x1DC280)]=lambda m:m.r.__setitem__(2,MODEL+(m.r[4]-ACTOR))
                c.callbacks[A(0x121FA8)]=lambda m:m.write(m.r[4],m.read(m.r[5],16))
                c.callbacks[A(0x204EA0)]=lambda m:m.set_number(0,0.)
                for fn in (0x1DABE8,0x24DD20):c.callbacks[A(fn)]=lambda m:None
                for role in range(3):self.assertEqual(apply(c,role),1)
                victim=struct.unpack('<3f',c.read(ACTOR+0x4000+16,12))
                entry=assets.timeline(name)[phase]
                attackers={role for role,source in enumerate(entry.roles[:2])
                           if source.animation in choreography.PHRASE_IDS.values()
                           or entry.flags&(assets.BEAM_LEAD<<role)}
                if name=='two_ki':attackers.update((0,1))
                # Waiting partners and departing fighters have their own
                # marks; only a fighter actually striking must aim at the hit.
                for role in attackers:
                    actor=ACTOR+role*0x2000
                    origin=struct.unpack('<3f',c.read(actor+16,12))
                    forward=struct.unpack('<3f',c.read(actor+16+128,12))
                    dx,dz=victim[0]-origin[0],victim[2]-origin[2]
                    alignment=(forward[0]*dx+forward[2]*dz)/math.hypot(dx,dz)
                    self.assertGreater(alignment,.98,(name,phase,role,origin,forward,victim))

    def test_cache_key_sorting_preserves_runtime_variant_order(self):
        variants={name:dict(phases=[]) for name in choreography.VARIANTS}
        cached=json.loads(json.dumps(variants,sort_keys=True))
        self.assertNotEqual(tuple(variants),tuple(cached))
        self.assertEqual(choreography.pack_records(variants,TABLE),
                         choreography.pack_records(cached,TABLE))
        for names in (choreography.VARIANTS[:-1],
                      choreography.VARIANTS+('unknown',),
                      choreography.VARIANTS[:-1]+('two_ki',)):
            with self.assertRaisesRegex(ValueError,'exactly once'):
                choreography.pack_records(names,TABLE)

    def test_opposing_roots_stay_airborne_and_sample_actual_floor(self):
        c=machine();run(c,staging.BEGIN)
        globals_before=[c.u(c.r[28]+off) for off in staging.fp.terrain.QUERY_GLOBALS]
        for role in range(3):self.assertEqual(apply(c,role),1)
        self.assertEqual(struct.unpack('<3f',c.read(MODEL+2384,12)),(100.,-200.,263.))
        self.assertEqual(struct.unpack('<3f',c.read(MODEL+0x2000+2384,12)),(100.,-200.,137.))
        self.assertAlmostEqual(c.fr(MODEL+2404),math.pi,places=6)
        self.assertAlmostEqual(c.fr(MODEL+0x2000+2404),0.,places=6)
        self.assertEqual(c.fr(STATE+116),-200.)
        self.assertEqual([c.u(c.r[28]+off) for off in staging.fp.terrain.QUERY_GLOBALS],globals_before)

    def test_role_spacing_rotates_with_shared_yaw(self):
        c=machine();c.fw(STATE+132,math.pi/2)
        self.assertEqual(apply(c,0),1)
        self.assertAlmostEqual(c.fr(MODEL+2384),163.,places=5)
        self.assertAlmostEqual(c.fr(MODEL+2392),200.,places=5)

    def test_settle_moves_real_hips_smoothly_without_restarting_unchanged_marks(self):
        c=machine();run(c,staging.BEGIN)
        for role in range(3):apply(c,role)
        c.w(STATE+8,6);run(c,staging.TICK)
        # 12/24sourceframes ->smoothstep .5; actualhip approaches fromair.
        self.assertAlmostEqual(c.fr(BONE+68),(-110.+(-210.))/2,places=4)
        self.assertAlmostEqual(c.fr(BONE+72),231.5,places=4)
        c.w(STATE+8,12);run(c,staging.TICK)
        self.assertAlmostEqual(c.fr(MODEL+2388),-200.,places=4)
        c.w(STATE+4,5);run(c,staging.BEGIN)
        self.assertEqual([c.u(ROWS+r*0x200+staging.SETTLE) for r in range(3)],[0,0,0])

    def test_final_slam_moves_victim_down_and_away_for_its_entire_phase(self):
        c=machine(variant=1,phase=7)
        for role in range(3):apply(c,role)
        victim=MODEL+0x4000;before=struct.unpack('<3f',c.read(victim+2384,12))
        c.w(STATE+4,8);run(c,staging.BEGIN)
        for role in range(3):self.assertEqual(apply(c,role),1)
        positions=[]
        for tick in (0,3,6,9,12,15):
            c.w(STATE+8,tick);run(c,staging.TICK)
            positions.append(struct.unpack('<3f',c.read(victim+2384,12)))
        self.assertEqual(positions[0],before)
        self.assertAlmostEqual(positions[-1][1]-before[1],66.)
        self.assertAlmostEqual(positions[-1][2]-before[2],-44.)
        self.assertTrue(all(a[1]<b[1] and a[2]>b[2] for a,b in zip(positions,positions[1:])))

    def test_beam_charge_closeup_pulls_back_continuously_before_firing(self):
        for shot in (2,6):
            eye,focus=shots.custom_sample(shot,0.)
            own_focus=(0.,-10.,63.) if shot==2 else (-42.,-38.,0.)
            self.assertEqual(focus,own_focus)
            self.assertLess(math.dist(eye[12:15],focus),50.)
            for frame in (60.,90.):
                before,_=shots.custom_sample(shot,(frame-.001)/180.)
                after,_=shots.custom_sample(shot,(frame+.001)/180.)
                self.assertLess(math.dist(before[12:15],after[12:15]),.001)
            wide,_=shots.custom_sample(shot,.5)
            self.assertGreater(math.dist(wide[12:15],own_focus),60.)

    def test_unavailable_floor_or_invalid_record_never_places_actor(self):
        c=machine();before=c.read(MODEL+2384,32)
        c.callbacks[staging.safety.QUERY]=lambda m:m.r.__setitem__(2,0)
        self.assertEqual(apply(c,0),0);self.assertEqual(c.read(MODEL+2384,32),before)
        c.w(tag.CONTROL+staging.TABLE_OFFSET,0);c.r[4]=4;run(c,staging.QUERY);self.assertEqual(c.r[2],0)

    def test_airborne_marks_clear_hills_and_refuse_insufficient_vertical_space(self):
        c=machine()
        def hill(m):m.set_number(0,-180.);m.r[2]=1
        c.callbacks[staging.safety.QUERY]=hill
        self.assertEqual(apply(c,0),1)
        self.assertEqual(c.fr(MODEL+2388),-240.)
        c=machine();before=c.read(MODEL+2384,16)
        def too_high(m):m.set_number(0,-300.);m.r[2]=1
        c.callbacks[staging.safety.QUERY]=too_high
        self.assertEqual(apply(c,0),0)
        self.assertEqual(c.read(MODEL+2384,16),before)

    def test_mixed_retreat_stays_outside_the_beam_composition(self):
        for variant in ('mixed_ki_lead','mixed_ki_partner'):
            record=choreography.records(variant)[-1]
            nonki=1 if variant=='mixed_ki_lead' else 0
            point=record[4+nonki][:3]
            for fraction in (.35,.65,1.):
                matrix,_=shots.custom_sample(6,fraction)
                delta=tuple(p-e for p,e in zip(point,matrix[12:15]))
                right=sum(x*y for x,y in zip(delta,matrix[:3]))
                forward=sum(x*y for x,y in zip(delta,matrix[8:11]))
                # Even a wide 100-degree horizontal view cannot include it.
                self.assertTrue(forward<=0 or abs(right)>forward*math.tan(math.radians(50)))

    def test_mixed_beam_camera_leaves_room_around_both_full_bodies(self):
        # The mixed finisher uses a separate side-on lane above the melee
        # exchange. Fit the actual shooter/victim marks, not the old crossfire.
        record=choreography.records('mixed_ki_lead')[-1]
        for fraction in (.5,.65,.75,1.):
            matrix,_=shots.custom_sample(6,fraction)
            for root in (record[4][:3],record[6][:3]):
                for point in ((root[0]+x,root[1]+y,root[2]+z)
                              for x in (-10.,10.) for y in (-25.,5.) for z in (-10.,10.)):
                    delta=tuple(p-e for p,e in zip(point,matrix[12:15]))
                    projected=[sum(x*y for x,y in zip(delta,matrix[off:off+3]))for off in (0,4,8)]
                    self.assertGreater(projected[2],25.)
                    self.assertLess(abs(projected[0]),projected[2]*math.tan(math.radians(34)))
                    self.assertLess(abs(projected[1]),projected[2]*math.tan(math.radians(24)))

    def test_widened_crossfire_keeps_both_attackers_and_center_victim_in_frame(self):
        record=choreography.records('two_ki')[-1]
        self.assertEqual(math.dist(record[4][:3],record[5][:3]),126.)
        for fraction in (.5,.65,.8,1.):
            matrix,_=shots.custom_sample(2,fraction)
            for root in (row[:3] for row in record[4:]):
                for point in ((root[0]+x,root[1]+y,root[2]+z)
                              for x in (-10.,10.) for y in (-25.,5.) for z in (-10.,10.)):
                    delta=tuple(p-e for p,e in zip(point,matrix[12:15]))
                    projected=[sum(x*y for x,y in zip(delta,matrix[off:off+3]))for off in (0,4,8)]
                    self.assertGreater(projected[2],25.)
                    self.assertLess(abs(projected[0]),projected[2]*math.tan(math.radians(34)))
                    self.assertLess(abs(projected[1]),projected[2]*math.tan(math.radians(24)))

    def test_mixed_firing_lane_is_a_side_on_intercept_not_half_of_the_crossfire(self):
        crossfire=choreography.records('two_ki')[-1]
        self.assertEqual(crossfire[1:3],(2,90))
        self.assertEqual([row[:3] for row in crossfire[4:]],
                         [(0.,0.,63.),(0.,0.,-63.),(0.,0.,0.)])
        for variant in ('mixed_ki_lead','mixed_ki_partner'):
            ki=0 if variant=='mixed_ki_lead' else 1
            records=choreography.records(variant)
            launch,relay,beam=records[5:8]
            self.assertEqual(beam[1:3],(6,90))
            shooter,victim=beam[4+ki],beam[6]
            self.assertEqual(shooter,(-42.,-28.,0.,90.))
            self.assertEqual(victim,(0.,-28.,0.,270.))
            # The shooter is already waiting at the interception point while
            # the victim rises into its lane; no last-frame beam teleport.
            self.assertEqual(launch[4+ki],shooter)
            self.assertEqual(relay[4+ki],shooter)
            self.assertEqual(relay[6],victim)
            self.assertLess(relay[6][1],launch[6][1])
            self.assertGreater(math.dist(beam[4+1-ki][:3],victim[:3]),100.)
            close,focus=shots.custom_sample(6,0.)
            self.assertAlmostEqual(focus[0],shooter[0])
            self.assertAlmostEqual(focus[2],shooter[2])
            self.assertNotEqual(close,shots.custom_sample(2,0.)[0])

    def test_beam_reaction_hits_once_then_sustains_hurt_until_native_fall(self):
        recipe=choreography.DERIVED['beam_reaction'][2]
        self.assertTrue(all(source==175 and 0<=start<=end<=46
                            for source,start,end,_ in recipe))
        self.assertEqual(recipe,((175,0,0,90),(175,0,10,4),(175,10,40,56),(175,40,46,30)))
        self.assertEqual(sum(row[3]for row in recipe),180)
        self.assertEqual([row[2] for row in recipe[:-1]],[row[1] for row in recipe[1:]])

    def test_crossfire_positioning_does_not_invent_a_hit_before_the_beams(self):
        wait=choreography.DERIVED['crossfire_wait']
        self.assertEqual(wait[1],24)
        self.assertTrue(all(start==end for _,start,end,_ in wait[2]))
        self.assertEqual(wait[2][-1][:3],(175,0,0))
        self.assertEqual(assets.timeline('two_ki')[4].roles[2].animation,wait[0])

    def test_victim_sources_are_selected_by_real_native_hurt_and_fall_handlers(self):
        from extra_throws import NATIVE
        cases=((192,0x1E8178,1,0,162),(192,0x1E8178,1,1,163),
               (192,0x1E8178,1,2,164),(192,0x1E8178,1,3,165),
               (203,0x1E8438,0,0,174),(204,0x1E8438,1,0,175),
               (217,0x1EA298,0,0,198))
        for action,handler,posture,variation,expected in cases:
            c=machine();c.write(A(handler),NATIVE(A(handler),0x300))
            c.r[4:6]=[ACTOR,0]
            c.callbacks[A(0x1E0A20)]=lambda m,p=posture:m.r.__setitem__(2,p)
            c.callbacks[A(0x1E0358)]=lambda m,v=action:m.r.__setitem__(2,v)
            c.callbacks[A(0x1E0368)]=lambda m:m.r.__setitem__(2,11)
            c.callbacks[A(0x1E7E98)]=lambda m,v=variation:m.r.__setitem__(2,v)
            c.write(A(0x2EF8A0),NATIVE(A(0x2EF8A0),56))
            c.run(A(handler),stops=(A(0x1C3E60),))
            self.assertEqual(c.r[5],expected,(action,posture,variation))
        victim_sources={r[0]for name in ('recoil','fall','beam_reaction','air_fall')
                        for r in choreography.DERIVED[name][2]}
        self.assertEqual(victim_sources,{162,164,175,198})

    def test_custom_camera_pans_track_focus_with_orthonormal_basis(self):
        self.assertEqual(len(shots.custom_shot_data()),15*64)
        for shot in range(1,16):
            first,_=shots.custom_sample(shot,0.);last,_=shots.custom_sample(shot,1.)
            self.assertGreater(math.dist(first[12:15],last[12:15]),4.)
            for fraction in (0.,.25,.5,.75,1.):
                row,target=shots.custom_sample(shot,fraction);axes=(row[:3],row[4:7],row[8:11])
                for axis in axes:self.assertAlmostEqual(sum(v*v for v in axis),1.,places=6)
                for a,b in ((axes[0],axes[1]),(axes[1],axes[2]),(axes[0],axes[2])):
                    self.assertAlmostEqual(sum(x*y for x,y in zip(a,b)),0.,places=6)
                direction=tuple(t-e for t,e in zip(target,row[12:15]))
                self.assertAlmostEqual(sum(x*y for x,y in zip(direction,axes[0])),0.,places=5)
                self.assertAlmostEqual(sum(x*y for x,y in zip(direction,axes[1])),0.,places=5)

    def test_emitted_custom_camera_uses_common_air_frame_and_restores_view_binding(self):
        for variant,phase,shot in ((0,5,2),(2,7,6),(3,7,6),
                                   (1,5,8),(1,6,9),(1,7,10),(2,6,11),
                                   (4,0,13),(4,1,13),(4,2,13),(4,3,13),(4,4,15)):
            with self.subTest(variant=variant,phase=phase,shot=shot):
                self._assert_emitted_custom_camera(variant,phase,shot)

    def _assert_emitted_custom_camera(self,variant,phase,shot):
        c=machine(variant=variant,phase=phase)
        for p,b in shots.pieces():c.write(p,b)
        c.fw(STATE+116,-200.);descriptor=assets.BASE+0x2000
        entry=assets.timeline(choreography.VARIANTS[variant])[phase]
        duration=entry.source_frames
        c.w(descriptor,duration);c.w(descriptor+28,entry.flags)
        identity=(1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.)
        def read(m,p):return struct.unpack('<16f',m.read(p,64))
        def write(m,p,v):m.write(p,struct.pack('<16f',*v))
        c.callbacks[A(0x120098)]=lambda m:write(m,m.r[4],identity)
        def rotate(m):
            y=m.number(12);co,si=math.cos(y),math.sin(y)
            write(m,m.r[4],(co,0.,-si,0.,0.,1.,0.,0.,si,0.,co,0.,0.,0.,0.,1.))
        c.callbacks[A(0x120428)]=rotate
        def multiply(m):
            left,right=read(m,m.r[6]),read(m,m.r[5])
            write(m,m.r[4],tuple(sum(left[r*4+k]*right[k*4+col]for k in range(4))for r in range(4)for col in range(4)))
        c.callbacks[A(0x1201B8)]=multiply
        def inverse(m):
            v=read(m,m.r[5]);inv=list(identity)
            for r in range(3):
                for col in range(3):inv[r*4+col]=v[col*4+r]
            for col in range(3):inv[12+col]=-sum(v[12+k]*inv[k*4+col]for k in range(3))
            write(m,m.r[4],inv)
        c.callbacks[A(0x1202A0)]=inverse
        c.callbacks[A(0x120230)]=lambda m:m.write(m.r[4],m.read(m.r[5],64))
        c.callbacks[A(0x121408)]=lambda m:None
        def project(m):m.w(m.r[28]-22176,camera.CAMERA)
        c.callbacks[A(0x23E598)]=project;c.callbacks[A(0x23E6A0)]=lambda m:None
        old=c.u(c.r[28]-22176)
        samples=((12,58,60,74,88,90,150,180) if shot in (2,6,15)
                 else (0,2,12,2*(duration//4),duration))
        for source_frame in samples:
            yaw=.7 if source_frame%4 else 0.
            uniform,height=(1.5,1.2) if source_frame>90 else (1.,1.)
            c.fw(STATE+132,yaw);c.fw(STATE+104,uniform);c.fw(STATE+108,height)
            c.r[4:10]=[phase,source_frame//2,MODEL,STATE+104,descriptor,MODEL+0x2000]
            before=c.r.copy();run(c,shots.UPDATE)
            self.assertEqual(c.r[2],1);self.assertEqual(c.r[4:31],before[4:31])
            self.assertEqual(c.u(c.r[28]-22176),old)
            fraction=shots.special_hold_fraction(phase,source_frame//2) if variant==4 and shot==13 else (2*(source_frame//2))/duration
            row,focus=shots.custom_sample(shot,fraction)
            def world(point):
                x,y,z=point;x*=uniform;y*=height;z*=uniform
                return (100.+x*math.cos(yaw)+z*math.sin(yaw),-200.+y,
                        200.-x*math.sin(yaw)+z*math.cos(yaw))
            expected=world(row[12:15])
            for i,v in enumerate(expected):self.assertAlmostEqual(c.fr(camera.CAMERA+720+i*4),v,places=4)
            # The target remains centered as the shot moves inward.
            view=read(c,camera.CAMERA+64);target=(*world(focus),1.)
            for i,value in enumerate(target):self.assertAlmostEqual(c.fr(STATE+64+i*4),value,places=4)
            projected=[sum(target[k]*view[k*4+j]for k in range(4))for j in range(3)]
            self.assertAlmostEqual(projected[0],0.,places=4);self.assertAlmostEqual(projected[1],0.,places=4)
            self.assertGreater(projected[2],0.)

    def test_disc_derived_finishers_keep_limbs_remove_only_root_horizontal_travel(self):
        from prototype import ROOT
        import model_animations as animation
        try:import bt4_resources
        except ImportError:name='Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
        else:name='SLUS_219.78.DBZBT4B14REV2ENG.iso'
        iso=ROOT.parent/'games'/name
        if not iso.exists():self.skipTest('Local disc unavailable')
        clips=assets.prepared_clips(iso);original=assets.read_clips(iso)
        for phase in assets.OPENING:
            for role in phase.roles:
                if role and role not in tuple(assets.LEAD[i] for i in (353,354,357,358)):self.assertEqual(clips[role],original[role])
        self.assertNotEqual(clips[assets.LEAD[357]],original[assets.LEAD[357]])
        self.assertNotEqual(clips[assets.LEAD[358]],original[assets.LEAD[358]])
        for source,raw in clips.items():
            if source.animation<1000:continue
            clip=animation.AnimationClip.from_decoded(source.animation,raw)
            self.assertGreaterEqual(len(clip.tracks),40)
            for frame in (0,clip.frame_count//2,clip.frame_count):
                values=clip.evaluate(frame)
                for bone in (0,2):
                    p=values[bone].translation
                    if p:self.assertEqual((p[0],p[2]),(0.,0.))
        pack=assets.build_assets(iso,include_beam=True,include_camera=True)
        self.assertLess(pack['bytes_used'],assets.END-assets.BASE)

        native=choreography.read_sources(iso)
        for name,phrase in choreography.STRIKE_PHRASES.items():
            number,_,recipe=choreography.DERIVED[name]
            clip=animation.AnimationClip.from_decoded(number,clips[assets.ClipSource(101,number)])
            cursor=0
            for (source,start,end,duration),(strike,span,contact) in zip(recipe,phrase):
                self.assertEqual((source,duration),(strike,span))
                donor=animation.AnimationClip.from_decoded(source,native[source])
                actual=clip.evaluate(cursor+contact)
                expected=donor.evaluate(choreography.STRIKE_CONTACT[source])
                for bone in (3,5,11,17,31,45):
                    dot=sum(x*y for x,y in zip(actual[bone].rotation,expected[bone].rotation))
                    self.assertGreater(abs(dot),.9998,(name,cursor+contact,bone))
                cursor+=duration
        # Each physical hit begins its own native directional reaction at the
        # contact, peaks two source frames later, then recovers continuously.
        directions={'body_combo':(162,163,165),'relay_kick':(164,),
                    'chase_strike':(165,)}
        for phrase,sources in directions.items():
            name=choreography.REACTION_NAMES[phrase]
            number,frames,recipe=choreography.DERIVED[name]
            self.assertEqual(sum(row[3]for row in recipe),frames)
            clip=animation.AnimationClip.from_decoded(number,clips[assets.ClipSource(101,number)])
            for contact,source in zip(choreography.phrase_contacts(phrase),sources):
                donor=animation.AnimationClip.from_decoded(source,native[source])
                actual=clip.evaluate(contact+2);expected=donor.evaluate(choreography.HURT_PEAK[source])
                for bone in (3,5,11,17,31,45):
                    dot=sum(x*y for x,y in zip(actual[bone].rotation,expected[bone].rotation))
                    self.assertGreater(abs(dot),.9998,(name,contact+2,bone))
                    # The held pre-impact pose must not anticipate the blow.
                    before=clip.evaluate(contact-1)[bone]
                    onset=clip.evaluate(contact)[bone]
                    self.assertGreater(abs(sum(x*y for x,y in zip(before.rotation,onset.rotation))),.9999999)
        # The last kick and recipient are a matched native pair, not a generic
        # jab recoil; the recipient tumbles once through the end of the crop.
        slam=animation.AnimationClip.from_decoded(1018,clips[assets.ClipSource(101,1018)])
        donor=animation.AnimationClip.from_decoded(360,native[360])
        for frame,source_frame in ((0,75),(24,95),(36,119)):
            actual=slam.evaluate(frame);expected=donor.evaluate(source_frame)
            for bone in (3,5,11,17,31,45):
                self.assertGreater(abs(sum(x*y for x,y in zip(actual[bone].rotation,expected[bone].rotation))),.9998)
        self.assertEqual(choreography.DERIVED['air_fall'][2],((198,0,19,30),))
        # A single forward-playing frontal impact carries on through the
        # explosion, rather than rewinding or freezing a standing hurt pose.
        beam=animation.AnimationClip.from_decoded(1009,clips[assets.ClipSource(101,1009)])
        donor=animation.AnimationClip.from_decoded(175,native[175])
        wait=animation.AnimationClip.from_decoded(1021,clips[assets.ClipSource(101,1021)])
        for frame,source_frame in ((0,0),(90,0),(94,10),(150,40),(180,46)):
            actual=beam.evaluate(frame);expected=donor.evaluate(source_frame)
            for bone in (3,5,11,17,31,45):
                self.assertGreater(abs(sum(x*y for x,y in zip(actual[bone].rotation,expected[bone].rotation))),.9998)
        for bone,value in wait.evaluate(24).items():
            self.assertEqual(value.translation,beam.evaluate(0)[bone].translation)
            self.assertGreater(abs(sum(x*y for x,y in zip(value.rotation,beam.evaluate(0)[bone].rotation))),.9999999)
        self.assertGreater(sum(abs(sum(x*y for x,y in zip(beam.evaluate(108)[bone].rotation,
                                 beam.evaluate(150)[bone].rotation)))<.9998 for bone in (3,5,11,17,31,45)),0)

    def test_entrance_victim_recovers_without_changing_contact_roots_or_next_hit(self):
        from prototype import ROOT
        from model_animations import AnimationClip
        try:import bt4_resources
        except ImportError:name='Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
        else:name='SLUS_219.78.DBZBT4B14REV2ENG.iso'
        iso=ROOT.parent/'games'/name
        if not iso.exists():self.skipTest('Local disc unavailable')
        originals=assets.read_clips(iso)
        launch_raw=choreography.stabilize_opening_victim(originals[assets.LEAD[357]],originals[assets.LEAD[359]])
        launch=AnimationClip.from_decoded(357,launch_raw)
        raw=choreography.recover_entrance_victim(originals[assets.LEAD[358]],originals[assets.LEAD[359]],launch_raw)
        flat=AnimationClip.from_decoded(358,originals[assets.LEAD[358]])
        hurt=AnimationClip.from_decoded(359,originals[assets.LEAD[359]])
        fixed=AnimationClip.from_decoded(358,raw)
        self.assertEqual(fixed.frame_count,99)
        self.assertEqual(len(fixed.tracks),len(flat.tracks))
        self.assertEqual(assets.source_audio_cues(raw),())
        # Beginning matches the actual launched body; the24-frame recovery
        # ends upright/hurt and the final frame joins the next strike exactly.
        for frame,reference in ((0,launch.evaluate(68)),(24,hurt.evaluate(0)),(99,hurt.evaluate(0))):
            actual=fixed.evaluate(frame)
            for bone in (3,5,11,17,31,45):
                dot=sum(a*b for a,b in zip(actual[bone].rotation,reference[bone].rotation))
                self.assertGreater(abs(dot),.9998,(frame,bone))
        self.assertLess(abs(sum(a*b for a,b in zip(fixed.evaluate(24)[3].rotation,flat.evaluate(24)[3].rotation))),.8)
        for frame in range(100):
            actual=fixed.evaluate(frame);native=flat.evaluate(frame)
            for bone in actual:
                self.assertEqual(actual[bone].translation,native[bone].translation,(frame,bone))
            for bone in (0,2,52):
                self.assertGreater(abs(sum(a*b for a,b in zip(actual[bone].rotation,native[bone].rotation))),.9998)
            if frame:
                previous=fixed.evaluate(frame-1)
                self.assertGreater(abs(sum(a*b for a,b in zip(actual[3].rotation,previous[3].rotation))),.995)
        bad=bytearray(originals[assets.LEAD[358]]);struct.pack_into('<H',bad,2,98)
        with self.assertRaises(ValueError):choreography.recover_entrance_victim(bad,originals[assets.LEAD[359]],launch_raw)

    def test_opening_hit_preserves_native_contact_then_recovers_the_whole_body(self):
        from prototype import ROOT
        from model_animations import AnimationClip
        try:import bt4_resources
        except ImportError:name='Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
        else:name='SLUS_219.78.DBZBT4B14REV2ENG.iso'
        iso=ROOT.parent/'games'/name
        if not iso.exists():self.skipTest('Local disc unavailable')
        originals=assets.read_clips(iso);original=originals[assets.LEAD[357]]
        raw=choreography.stabilize_opening_victim(original,originals[assets.LEAD[359]])
        native=AnimationClip.from_decoded(357,original);fixed=AnimationClip.from_decoded(357,raw)
        hurt=AnimationClip.from_decoded(359,originals[assets.LEAD[359]])
        # Original channel/event storage remains intact. Only body rotation
        # pointers change; no camera or actor contact root is reconstructed.
        self.assertEqual(raw[:6],original[:6]);self.assertEqual(raw[148:len(original)],original[148:])
        for bone in (0,2,52):self.assertEqual(raw[6+2*bone:8+2*bone],original[6+2*bone:8+2*bone])
        self.assertEqual(assets.source_audio_cues(raw),assets.source_audio_cues(original))
        for quarter in range(28*4+1):
            self.assertEqual(fixed.evaluate(quarter/4),native.evaluate(quarter/4),quarter)
        moving_body=set()
        for frame in range(69):
            current=fixed.evaluate(frame);expected=native.evaluate(frame)
            for bone in current:
                self.assertEqual(current[bone].translation,expected[bone].translation)
                if bone in (0,2,52):self.assertEqual(current[bone],expected[bone])
                elif frame in (44,68):
                    want=hurt.evaluate(0)[bone].rotation
                    self.assertGreater(abs(sum(a*b for a,b in zip(current[bone].rotation,want))),.999999,(frame,bone))
                if frame>28:
                    prior=fixed.evaluate(frame-1)[bone].rotation
                    dot=abs(sum(a*b for a,b in zip(current[bone].rotation,prior)))
                    self.assertGreater(dot,.99,(frame,bone))
                    if frame>44 and dot<.9999999:moving_body.add(bone)
        self.assertTrue({17,33,46}<=moving_body,'native chest, arm and neck recoil must keep moving after recovery')
        bad=bytearray(originals[assets.LEAD[359]]);struct.pack_into('<H',bad,2,148)
        with self.assertRaises(ValueError):choreography.stabilize_opening_victim(original,bad)


if __name__=='__main__':unittest.main()
