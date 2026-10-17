"""Execute crossed-source-frame sound routing and the native world wrapper."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path
from native_map import A, GP, GPO, SERIAL, elf_path
from prototype import ROOT, elf_reader
import tag_rush_audio as audio
import tag_rush_scene as scene
import tag_rush_assets as assets
import tag_team_rush as tag
import fresh_team_combat as core
import tag_rush_effects as effects
import tag_rush_audio_queue as deferred
from test_tag_rush_scene import SceneCpu
from test_tag_rush_camera import run
from test_tag_rush_safety import control, ACTOR, MODEL


def cue(role,frame,sound=30):
    return dict(role=role,frame=frame,bank=0,sound_id=sound,bone=3,near=200.,far=1500.,
                alternate_sound_id=11 if sound==51 else None,parameter_flag=0x8000 if sound==51 else 0)


def pack():
    phases=((cue(0,0),cue(0,2,31),cue(2,1,24)),(),(cue(1,10,51),),(),(cue(0,38,24),cue(0,67,51)))
    return {'audio_cues':{name:deepcopy(phases)for name in audio.VARIANTS}}


def machine(hz=30,data=None):
    with patch.object(audio,'ACTOR_HZ',hz):blocks=audio.pieces(data or pack())
    c=SceneCpu({'segments':[dict(address=p,data_hex=b.hex())for p,b in blocks]})
    import tag_rush_approach as approach
    c.write(approach.START_SOUND,approach.start_sound_code())
    control(c,active=1,count=4,members=7);c.w(tag.CONTROL+tag.C['variant'],0)
    c.w(scene.STATE,scene.SCENE_MAGIC);c.w(scene.STATE+scene.S['descriptor'],assets.BASE)
    c.requests=[];c.bones=[];c.models=[];c.actors=[];c.impacts=[]
    for role,(index,mid)in enumerate(((0,0),(2,7),(1,4))):
        row=scene.ROWS+role*scene.STRIDE;actor=ACTOR+index*0x2000;model=MODEL+index*0x2000
        c.models.append(model);c.actors.append(actor)
        c.w(core.POINTERS+index*4,actor);c.w(actor,index);c.w(actor+12,mid)
        c.w(core.MODELS+mid*4,model);c.w(model+16,mid);c.w(model+12,40+role)
        c.w(model+4,1);c.w(model+8,1);c.w(model+2332,0x3500000+role*0x100)
        for key,value in (('index',index),('actor',actor),('model',model),('character',40+role),('model_id',mid)):
            c.w(row+scene.R[key],value)
        bone=0x3600000+role*0x100;c.w(model+3436+3*4,bone)
        c.write(bone+64,struct.pack('<4f',10.*role,-25.,100.*role,1.))
    for phase in range(12):
        c.write(assets.BASE+phase*64,struct.pack('<16I',100,0x6D20000,0x6D21000,0x6D22000,0,0,0,0,1,2,3,100,100,100,60,0))
    native=elf_reader(elf_path(ROOT))[2]
    c.write(deferred.SOUND,native(deferred.SOUND,0x28))
    def clobber(m):
        for reg in (*range(8,16),24,25):m.r[reg]=0xABCD0000+reg
        for reg in range(20):m.set_number(reg,1000.+reg)
        m.hi=0xAABB;m.lo=0xCCDD
    def bone(m):
        model=m.u(core.MODELS+m.r[4]*4);p=m.u(model+3436+3*4)
        m.bones.append((m.r[4],m.r[5]));m.write(m.r[6],m.read(p+64,16));clobber(m)
    def request(m):
        m.requests.append((m.r[5]&0xFFFFFFFF,m.r[6],m.r[7],m.number(12),m.number(13),struct.unpack('<4f',m.read(m.r[4],16))))
        manager=m.u(tag.CONTROL+tag.C['manager']);m.w(manager+288,m.u(manager+288)+1);m.r[2]=m.u(manager+288)
        clobber(m)
    c.callbacks[A(0x2058E0)]=bone;c.callbacks[A(0x1D9B78)]=request
    c.callbacks[A(0x1252D8)]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[A(0x1251E8)]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[effects.IMPACT]=lambda m:c.impacts.append(tuple(m.r[4:6]))
    c.callbacks[deferred.DISPATCH]=lambda m:None
    run(c,audio.RESET)
    return c


def tick(c,phase,ticks):
    c.w(scene.STATE+scene.S['phase'],phase);c.w(scene.STATE+scene.S['ticks'],ticks)
    c.w(scene.STATE+scene.S['descriptor'],assets.BASE+phase*64);run(c,audio.TICK)
    # The real frame discards early native requests before our dispatch hook.
    c.w(c.u(tag.CONTROL+tag.C['manager'])+288,0);run(c,deferred.FLUSH)


class AudioTests(unittest.TestCase):
    def test_disc_relay_pose_contacts_play_once_at_the_attacker_and_hit_the_victim(self):
        import math
        import tag_rush_choreography as choreography
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__).parent)
              else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        iso=Path(__file__).resolve().parents[2]/'games'/name
        if not iso.is_file():self.skipTest('Local reviewed disc unavailable')
        data=assets.build_assets(iso)
        rows=audio.cue_rows(data)
        self.assertLessEqual(len(rows)*24,audio.STATE-audio.TABLE)
        for variant,name in enumerate(choreography.VARIANTS):
            expected=[(phase,role,frame) for phase in range(4,len(assets.timeline(name)))
                      for role,frame in choreography.phase_contacts(name,phase)]
            actual=[(phase,role,frame) for mask,phase,role,frame,sound,_ in rows
                    if mask&(1<<variant) and phase>=4 and sound==73]
            self.assertEqual(sorted(actual),sorted(expected),name)
            if not expected:continue
            for hz in (25,30):
                c=machine(hz,data);c.w(tag.CONTROL+tag.C['variant'],variant)
                for phase,p in enumerate(assets.timeline(name)):
                    c.w(assets.BASE+phase*64,p.source_frames)
                    c.w(assets.BASE+phase*64+28,p.flags)
                    for role in range(3):c.w(assets.BASE+phase*64+44+role*4,p.ends[role])
                for phase,role,frame in expected:
                    before=len(c.requests)
                    tick(c,phase,(frame*hz-1)//60)
                    self.assertEqual(len(c.requests),before,(name,hz,phase,frame))
                    tick(c,phase,math.ceil(frame*hz/60))
                    self.assertEqual(len(c.requests),before+1)
                    self.assertEqual(c.requests[-1][2],73)
                    self.assertEqual(c.requests[-1][5],(10.*role,-25.,100.*role,1.))
                    self.assertEqual(c.impacts[-1][0],2)
                    tick(c,phase,math.ceil(frame*hz/60))
                    self.assertEqual(len(c.requests),before+1)

    def test_explosion_cue_matches_native_primary_beam_final_hit(self):
        import model_assets as models
        import tag_rush_install as installer
        iso=installer.selected_iso()
        if not Path(iso).is_file():self.skipTest('Local reviewed disc unavailable')
        native=elf_reader(elf_path(ROOT))[2]
        # Case2 of the actual contact dispatcher: copied hit position, common
        # bank kind0, native near200/far1500, and sample71 in the call's delay slot.
        expected=(0x12000007,0x26040020,0x3C014348,0x44816000,
                  0xC78D0000|(GPO(-28960)&0xFFFF),0x0000282D,
                  (3<<26)|(A(0x1DA348)>>2),0x24060000|audio.EXPLOSION_SOUND)
        self.assertEqual(struct.unpack('<8I',native(A(0x1CAE18),32)),expected)
        far=native(GP+GPO(-28960),4)
        self.assertEqual(struct.unpack('<f',far)[0],1500.)
        for character in (0,23,101):
            if SERIAL=='SLUS-21978':
                params=models.package_entry(models.read_archive_entry(iso,4150+character),2)[0x29D0:0x2C50]
            else:params=models.package_entry(assets._mesh_package(iso,character),24)
            self.assertEqual(len(params),640)
            c=machine();model=c.models[0];address=0x3700000
            c.write(address,params);c.w(model+2348,address)
            c.write(A(0x2111D0),native(A(0x2111D0),0x48))
            c.callbacks[A(0x1DC280)]=lambda m:m.r.__setitem__(2,model)
            c.r[4]=c.actors[0];c.r[5]=2;c.r[6]=1
            run(c,A(0x2111D0));self.assertEqual(c.r[2],2,character)
            # Execute the native case selected by that real move parameter.
            # a0=0 avoids unrelated rumble/gameplay; a1 is the hit record.
            hit=0x3710000;c.write(hit+32,struct.pack('<4f',12.,-30.,44.,1.))
            c.write(A(0x1CAD68),native(A(0x1CAD68),0x188))
            c.write(A(0x2EEB10),native(A(0x2EEB10),20))
            c.write(c.r[28]+GPO(-28960),far);requests=[]
            c.callbacks[A(0x1DA348)]=lambda m:requests.append((m.r[4],m.r[5],m.r[6],m.number(12),m.number(13)))
            c.r[4]=0;c.r[5]=hit;c.r[6]=2;run(c,A(0x1CAD68))
            self.assertEqual(requests,[(hit+32,0,audio.EXPLOSION_SOUND,200.,1500.)],character)

    def test_final_beam_explosion_is_one_victim_cue_even_with_two_beams(self):
        import tag_rush_choreography as choreography
        for custom in (False,True):
            data={'audio_cues':{name:((),(),(),(),())for name in audio.VARIANTS}}
            data['variants']={name:dict(phases=[dict(flags=0)]*4+[dict(
                flags=assets.FINISHER|(assets.CUSTOM_FINISHER if custom else 0)|(0 if name=='two_melee' else
                    assets.BEAM_PARTNER if name in ('mixed_ki_partner','early_goku_piccolo') else
                    assets.BEAM_LEAD|assets.BEAM_PARTNER if name=='two_ki' else assets.BEAM_LEAD),
                source_frames=180)])for name in audio.VARIANTS}
            burst=choreography.beam_burst_frame(180,custom=custom)
            self.assertEqual(burst,96 if custom else 150)
            for hz in (30,25):
                for variant in range(len(audio.VARIANTS)):
                    c=machine(hz,data);c.w(tag.CONTROL+tag.C['variant'],variant)
                    for off in (0,44,48,52):c.w(assets.BASE+4*64+off,180)
                    before=(burst*hz-1)//60;after=(burst*hz+59)//60
                    tick(c,4,before);self.assertFalse(c.requests)
                    c.w(A(0x333700),1);tick(c,4,after);self.assertFalse(c.requests)
                    c.w(A(0x333700),0)
                    for frame in (after+2,after+2,after+5):tick(c,4,frame)
                    self.assertEqual([r[2]for r in c.requests],[] if variant in(1,6) else [audio.EXPLOSION_SOUND])
                    if variant not in(1,6):self.assertEqual(c.requests[0][5],(20.,-25.,200.,1.))

    def test_own_clash_charge_onset_is_once_per_beam_role_and_never_a_loop(self):
        data=pack()
        data['variants']={name:dict(phases=[dict(flags=0)]*4+[dict(flags=assets.OWN_CLASH_POSE|
            (assets.BEAM_PARTNER if name in ('mixed_ki_partner','early_goku_piccolo') else assets.BEAM_LEAD))])
            for name in audio.VARIANTS}
        data['variants']['two_ki']['phases'][4]=dict(flags=assets.OWN_CLASH_POSE|assets.BEAM_LEAD|assets.BEAM_PARTNER)
        data['variants']['two_melee']['phases'][4]=dict(flags=assets.CUSTOM_FINISHER)
        for variant,roles in ((0,(0,1)),(1,()),(2,(0,)),(3,(1,)),(4,(1,))):
            c=machine(data=data);c.w(tag.CONTROL+tag.C['variant'],variant)
            probes=[]
            def one_shot(m):
                probes.append((m.r[4],m.r[5]));m.r[2]=0
                for reg in (*range(8,16),24,25):m.r[reg]=0xABCD0000+reg
            c.callbacks[A(0x1251E8)]=one_shot
            tick(c,4,0);tick(c,4,0);tick(c,4,1)
            self.assertEqual([r[2] for r in c.requests],[21]*len(roles))
            self.assertEqual([r[5][0] for r in c.requests],[10.*role for role in roles])
            self.assertEqual(probes,[(4,21)]*len(roles))
        for unavailable in ('unloaded','loop'):
            c=machine(data=data)
            if unavailable=='unloaded':c.callbacks[A(0x1252D8)]=lambda m:m.r.__setitem__(2,0)
            else:c.callbacks[A(0x1251E8)]=lambda m:m.r.__setitem__(2,1)
            tick(c,4,0);tick(c,4,1);self.assertFalse(c.requests,unavailable)

    def test_variant_masks_survive_alphabetical_json_cache_order(self):
        import json
        data={'audio_cues':{name:((cue(variant%3,10+variant),),)
                           for variant,name in enumerate(audio.VARIANTS)}}
        cached=json.loads(json.dumps(data,sort_keys=True))
        self.assertNotEqual(list(data['audio_cues']),list(cached['audio_cues']))
        self.assertEqual(audio.cue_rows(data),audio.cue_rows(cached))
        self.assertEqual(audio.pieces(data),audio.pieces(cached))
        for variant in range(len(audio.VARIANTS)):
            event=[row for row in audio.cue_rows(cached) if row[3]==10+variant]
            self.assertEqual(len(event),1)
            self.assertEqual(event[0][0],1<<variant)

    def test_crossed_frames_include_zero_once_and_each_role_has_native_world_position(self):
        c=machine();tick(c,0,1)
        self.assertEqual([(r[1],r[2])for r in c.requests],[(0,30),(0,31),(0,24)])
        self.assertTrue(all(r[0]==0xFFFFFFFF and r[3:5]==(200.,1500.)for r in c.requests))
        self.assertEqual(c.requests[0][5],(0.,-25.,0.,1.));self.assertEqual(c.requests[2][5],(20.,-25.,200.,1.))
        tick(c,0,1);tick(c,0,2);self.assertEqual(len(c.requests),3)

    def test_frame_skips_clamps_and_rewinds_do_not_replay(self):
        c=machine();c.w(assets.BASE+4*64+44,40)
        tick(c,4,30);self.assertEqual([r[2]for r in c.requests],[24])
        for n in (31,100,10,20,100):tick(c,4,n)
        self.assertEqual([r[2]for r in c.requests],[24])
        tick(c,3,30);self.assertEqual(len(c.requests),1)

    def test_partner_source_params_choose_native_alternate_without_affecting_lead(self):
        c=machine();c.w(c.u(c.models[1]+2332)+16,0x8000)
        tick(c,2,5);self.assertEqual([r[2]for r in c.requests],[11])
        self.assertEqual(c.requests[0][5],(10.,-25.,100.,1.))
        tick(c,4,34);self.assertEqual([r[2]for r in c.requests],[11,24,51])
        self.assertIn((7,3),c.bones)

    def test_pause_inactive_retiring_stale_actor_and_bad_model_do_not_play(self):
        for kind in ('pause','inactive','retiring','actor','model','reload','bone','parameters','manager'):
            c=machine()
            if kind=='pause':c.w(A(0x333700),1)
            elif kind=='inactive':c.w(tag.CONTROL+tag.C['active'],0)
            elif kind=='retiring':c.w(scene.STATE+scene.S['retiring'],1)
            elif kind=='actor':c.w(core.POINTERS+8,0)
            elif kind=='model':c.w(core.MODELS+7*4,0)
            elif kind=='reload':c.w(c.models[1]+8,0)
            elif kind=='bone':c.w(c.models[1]+3436+3*4,0)
            elif kind=='parameters':c.w(c.models[1]+2332,3)
            else:c.w(audio.STATE+audio.C['manager'],0)
            tick(c,2,5);self.assertFalse(c.requests,kind)

    def test_restart_resets_cursors_and_preserves_cpu_registers(self):
        c=machine();tick(c,0,1);self.assertEqual(len(c.requests),3)
        run(c,audio.RESET);saved=list(c.r);floating=list(c.f);hilo=(c.hi,c.lo)
        tick(c,0,1);self.assertEqual(len(c.requests),6)
        # run() intentionally sets PC/RA, but all ordinary registers and FPU survive.
        self.assertEqual(c.r[1:31],saved[1:31]);self.assertEqual(c.f,floating);self.assertEqual((c.hi,c.lo),hilo)

    def test_pal_crossing_uses_source60hz_not_integer_native_tick(self):
        data=pack();data['audio_cues']={name:((cue(0,5),),(),(),(),())for name in audio.VARIANTS}
        c=machine(25,data);tick(c,0,2);self.assertFalse(c.requests)
        tick(c,0,3);self.assertEqual([r[2]for r in c.requests],[30])

    def test_variant_masks_and_invalid_recipe_are_guarded(self):
        data=pack();data['audio_cues']['two_melee']=((),(),(),(),())
        c=machine(data=data);c.w(tag.CONTROL+tag.C['variant'],1);tick(c,0,1);self.assertFalse(c.requests)
        self.assertFalse(audio.installation(data)['usable'])
        for change in ({'bank':2},{'sound_id':55},{'near':0},{'role':3},{'parameter_flag':1},{'frame':-1}):
            data=pack();data['audio_cues']['two_ki'][0][0].update(change)
            with self.assertRaises(ValueError):audio.pieces(data)

    def test_strike_visual_and_sound_share_exact_crossed_frame_without_native_damage(self):
        row=cue(1,5,73);row.update(effect_kind=16,impact_bone=12)
        data={'audio_cues':{name:((),(),(deepcopy(row),),(),())for name in audio.VARIANTS}}
        c=machine(data=data);tick(c,2,2);self.assertFalse(c.impacts)
        tick(c,2,3);tick(c,2,3);tick(c,2,10)
        self.assertEqual(c.impacts,[(1,12)]);self.assertEqual([r[2]for r in c.requests],[73])
        for change in ({'effect_kind':3},{'impact_bone':32},{'sound_id':55},{'parameter_flag':1}):
            bad=deepcopy(data);bad['audio_cues']['two_ki'][2][0].update(change)
            with self.assertRaises(ValueError):audio.pieces(bad)

    def test_custom_combo_flashes_on_victim_but_sounds_stay_at_each_attacker(self):
        rows=[cue(role,5,73) for role in (0,1)]
        for row in rows:row.update(effect_kind=16,impact_bone=12)
        data={'audio_cues':{name:((),(),(),(),tuple(deepcopy(rows))) for name in audio.VARIANTS}}
        for variant in range(4):
            c=machine(data=data);c.w(tag.CONTROL+tag.C['variant'],variant)
            c.w(assets.BASE+4*64+28,assets.CUSTOM_FINISHER)
            tick(c,4,2);self.assertFalse(c.impacts)
            tick(c,4,3);tick(c,4,3)
            self.assertEqual(c.impacts,[(2,17),(2,17)])
            self.assertEqual([r[2] for r in c.requests],[73,73])
            self.assertEqual([r[5] for r in c.requests],[(0.,-25.,0.,1.),(10.,-25.,100.,1.)])

    def test_actual_disc_cues_fit_gap_and_skip_unreviewed_voice_or_beam_banks(self):
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__)) else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        iso=Path(__file__).resolve().parents[2]/'games'/name
        if not iso.is_file():self.skipTest('Local reviewed disc unavailable')
        result=assets.build_assets(iso);rows=audio.cue_rows(result)
        self.assertEqual(len([r for r in rows if r[1]<4 and r[0]&31]),18)
        # Both paired variants share the exact native opening cues of the
        # other tag attacks; only variant5's flying pursuit adds the dash cue.
        opening=[(r[1],r[2],r[3],r[4])for r in rows if r[1]<4 and r[0]&1]
        self.assertEqual([(r[1],r[2],r[3],r[4])for r in rows if r[1]<4 and r[0]&96],opening)
        self.assertTrue(all(r[0]&96==96 for r in rows if r[1]<4 and r[0]&1))
        self.assertEqual([(r[1],r[2],r[3],r[4])for r in rows if r[0]&96 and r[4]==28],
                         [(4,0,0,28),(5,1,0,28),(6,0,0,28),(7,1,0,28)])
        self.assertFalse([r for r in rows if r[0]&64 and r[4]==28])
        self.assertTrue(all(r[4]in(21,24,28,30,31,51,71,73)for r in rows))
        self.assertTrue(any(r[1]>=4 and r[2]==0 for r in rows));self.assertTrue(any(r[1]>=4 and r[2]==1 for r in rows))
        blocks=audio.pieces(result)
        import tag_rush_voices as voices
        self.assertTrue(all(audio.BASE<=p<=p+len(b)<=audio.END or voices.BASE<=p<=p+len(b)<=voices.END
                            or deferred.BASE<=p<=p+len(b)<=deferred.END for p,b in blocks))


if __name__=='__main__':unittest.main()
