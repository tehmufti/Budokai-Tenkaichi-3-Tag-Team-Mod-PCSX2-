"""Execute the tag damage scheduler against actual guest receipts and HP banks."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest
from unittest.mock import patch
import tag_rush_damage as damage
import tag_rush_scene as scene
import tag_rush_safety as safety
import tag_rush_assets as assets
import tag_rush_choreography as choreography
import tag_team_rush as tag
from test_tag_rush_scene import fixture,start
from test_tag_rush_camera import run


def pack_fixture():
    mapping={};audio={}
    native={0:((0,19),),2:((2,58),(0,70),(2,97)),3:((0,39),(0,95))}
    for name in damage.VARIANTS:
        phases=[];sounds=[]
        for index,p in enumerate(assets.timeline(name)):
            cues=[] if name=='early_goku_piccolo' else list(native.get(index,()))
            if p.flags&assets.CUSTOM_FINISHER:
                cues=list(choreography.phase_contacts(name,index))
            events=tuple(dict(role=r,frame=f,sound_id=73,effect_kind=16)for r,f in cues)
            phases.append(dict(source_frames=p.source_frames,starts=p.starts,ends=p.ends,flags=p.flags))
            import tag_rush_blue_native as blue
            if name in blue.NAMES and index==blue.burst(name)[0]:
                phases[-1]['burst_frame']=blue.burst(name)[1]
            sounds.append(events)
        mapping[name]=dict(phases=phases);audio[name]=tuple(sounds)
    return dict(variants=mapping,audio_cues=audio)


def machine(variant=0,hz=30,hp=30000,bank=0,*,sacrifice=True,multiplier=2000):
    c=fixture(ki=((True,True),(False,False),(True,False),(False,True),(True,True))[variant])
    pack=pack_fixture();c.write(damage.TABLE,damage.table_data(pack))
    with patch.object(damage,'ACTOR_HZ',hz):c.write(damage.TICK,damage.tick_code())
    c.write(safety.DAMAGE,safety.damage_code());c.callbacks.pop(safety.DAMAGE)
    c.native_damage=[]
    def native(m):
        actor,amount,flags=m.r[4:7];row=actor+0x9E4+164*m.u(actor+0x994)
        before=m.u(row);after=max(1 if flags&0x400 else 0,before-amount)
        m.w(row,after);m.r[2]=before-after
        m.native_damage.append((actor,amount,flags,m.u(scene.STATE+scene.S['phase']),m.u(scene.STATE+scene.S['ticks'])))
    c.callbacks[scene.A(0x1CE630)]=native
    victim=c.actors[1];c.w(victim+0x994,bank);c.w(victim+0x9E4+164*bank,hp)
    start(c);assert c.r[2]==1
    if variant==4:
        # Damage-only fixture: keep the director's authenticated actor receipts,
        # then select the special timeline. Full paired choreography is tested
        # independently with its real descriptors and reversed request order.
        c.w(c.models[2]+12,22);c.w(scene.ROWS+scene.STRIDE+scene.R['character'],22)
        c.w(tag.CONTROL+tag.C['variant'],4)
        c.w(tag.CONTROL+tag.C['sacrifice_enabled'],int(sacrifice))
        c.w(tag.CONTROL+tag.C['sacrifice_multiplier'],multiplier)
        run(c,damage.RESET)
    return c,pack


def at(c,phase,frame,hz=30):
    c.w(scene.STATE+scene.S['phase'],phase);c.w(scene.STATE+scene.S['ticks'],math.ceil(frame*hz/60))
    run(c,damage.TICK)


class DamageTests(unittest.TestCase):
    def test_short_authored_finisher_keeps_its_explicit_hit_and_rejects_invalid_frames(self):
        pack=pack_fixture();name='super_galick_pair'
        import tag_rush_blue_native as blue
        phase,frame=blue.burst(name);row=pack['variants'][name]['phases'][phase]
        self.assertEqual((row['source_frames'],frame),(48,6))
        self.assertEqual(damage.schedules(pack)[name][-1],(phase,frame,10000))
        for bad in (-1,49,None,True):
            row['burst_frame']=bad
            with self.assertRaisesRegex(ValueError,'outside'):damage.schedules(pack)

    def test_each_actual_hit_reduces_hp_exact_budget_and_largest_beam_burst(self):
        for variant,name in enumerate(damage.VARIANTS[:4]):
            for hz in (25,30):
                c,pack=machine(variant,hz);events=damage.schedules(pack)[name];last=30000
                for phase,frame,weight in events:
                    at(c,phase,frame,hz);self.assertEqual(c.r[2],1)
                    hp=c.u(c.actors[1]+0x9E4);self.assertLess(hp,last,(name,phase,frame));last=hp
                    count=len(c.native_damage);at(c,phase,frame,hz);self.assertEqual(len(c.native_damage),count)
                self.assertEqual(sum(row[1]for row in c.native_damage),14999)
                run(c,damage.FINAL);self.assertEqual(c.r[2],1)
                self.assertEqual(sum(row[1]for row in c.native_damage),15000)
                self.assertEqual(c.u(c.actors[1]+0x9E4),15000)
                self.assertEqual(c.native_damage[-1][1:],(1,damage.FINAL_FLAGS,*c.native_damage[-1][3:]))
                if variant!=1:
                    self.assertEqual(c.native_damage[-2][1],9000)
                    self.assertTrue(all(row[1]<9000 for row in c.native_damage[:-2]))
                count=len(c.native_damage);run(c,damage.FINAL);self.assertEqual(len(c.native_damage),count)
                self.assertTrue(all(row[2]&0x2000000 for row in c.native_damage))

    def test_skips_cross_all_due_impacts_once_and_pause_does_not_pay(self):
        c,pack=machine(1);events=damage.schedules(pack)['two_melee']
        c.w(scene.A(0x333700),1);at(c,3,119);self.assertEqual(c.native_damage,[])
        c.w(scene.A(0x333700),0);at(c,3,119)
        self.assertEqual(len(c.native_damage),6);before=list(c.native_damage)
        at(c,3,119);self.assertEqual(c.native_damage,before)
        at(c,events[-1][0],events[-1][1]);self.assertEqual(len(c.native_damage),len(events))
        run(c,damage.FINAL);self.assertEqual(sum(x[1]for x in c.native_damage),15000)

    def test_cancellation_keeps_only_landed_damage_and_does_not_pay_finisher(self):
        c,pack=machine();first=damage.schedules(pack)['two_ki'][0]
        at(c,*first[:2]);paid=list(c.native_damage);self.assertGreater(paid[0][1],0)
        c.w(scene.STATE+scene.S['cancelled'],1);at(c,5,180);run(c,damage.FINAL)
        self.assertEqual(c.r[2],0);self.assertEqual(c.native_damage,paid)
        c.w(scene.STATE+scene.S['cancelled'],0);run(c,damage.FINAL)
        self.assertEqual(c.r[2],0);self.assertEqual(c.native_damage,paid)

    def test_low_hp_selected_bank_stays_alive_until_successful_native_finish(self):
        c,pack=machine(hp=200,bank=2);untouched=c.u(c.actors[1]+0x9E4)
        for phase,frame,_ in damage.schedules(pack)['two_ki']:
            at(c,phase,frame);self.assertEqual(c.r[2],1)
            self.assertGreaterEqual(c.u(c.actors[1]+0x9E4+328),1)
        self.assertEqual(c.u(c.actors[1]+0x9E4),untouched)
        run(c,damage.FINAL);self.assertEqual(c.u(c.actors[1]+0x9E4+328),0)
        self.assertEqual(c.u(damage.STATE+damage.C['loss']),200)
        self.assertEqual(sum(row[1]for row in c.native_damage),15000)

    def test_replaced_victim_manager_or_bank_and_native_reentry_never_damage_again(self):
        for change in ('manager','model','bank'):
            c,pack=machine();first=damage.schedules(pack)['two_ki'][0]
            if change=='manager':c.w(c.r[28]-22364,0x1800000)
            elif change=='model':c.w(c.models[1]+12,99)
            else:c.w(c.actors[1]+0x994,1)
            at(c,*first[:2]);self.assertEqual(c.r[2],0);self.assertEqual(c.native_damage,[])
        c,pack=machine()
        # The safety call-site latch also refuses replay before another
        # authenticated scheduler event reserves a new portion.
        first=damage.schedules(pack)['two_ki'][0];at(c,*first[:2]);count=len(c.native_damage)
        c.r[4:7]=[c.actors[1],15000,damage.HIT_FLAGS];run(c,safety.DAMAGE)
        self.assertEqual(c.r[2],0);self.assertEqual(len(c.native_damage),count)

    def test_zero_small_and_odd_budgets_never_exceed_configured_amount(self):
        for amount in (0,1,2,17,15001,100000):
            c,pack=machine(hp=1000000);c.w(tag.CONTROL+tag.C['damage'],amount);run(c,damage.RESET)
            for phase,frame,_ in damage.schedules(pack)['two_ki']:at(c,phase,frame)
            run(c,damage.FINAL);self.assertEqual(sum(x[1]for x in c.native_damage),amount)
            self.assertEqual(c.u(c.actors[1]+0x9E4),1000000-amount)

    def test_actual_native_damage_keeps_total_with_existing_combo_and_native_nonlethal_floor(self):
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        _,_,native=elf_reader(elf_path(ROOT))
        for hp in (30000,200):
            c,pack=machine(hp=hp)
            c.write(scene.A(0x1CE630),native(scene.A(0x1CE630),0x510))
            c.callbacks.pop(scene.A(0x1CE630))
            def result(value):return lambda m:m.r.__setitem__(2,value)
            def factor(m):m.set_number(0,1.);m.r[2]=0x3F800000
            c.callbacks.update({scene.A(0x1CE1B8):lambda m:m.r.__setitem__(2,m.r[4]+0x9E4+164*m.u(m.r[4]+0x994)),
                scene.A(0x1C4638):result(0),scene.A(0x1C4650):result(0),
                scene.A(0x20F258):factor,scene.A(0x1C3BB8):factor,
                scene.A(0x1DBC10):result(0),scene.A(0x1CF0C8):result(0),
                scene.A(0x1DAC78):result(1),scene.A(0x12AB38):result(0),
                scene.A(0x1296B8):lambda m:None,scene.A(0x1DB770):result(0),scene.A(0x1DAA50):lambda m:None})
            c.fw(c.r[28]-28836,.001);c.fw(c.r[28]-28840,.001)
            c.w(c.actors[1]+3396,9)  # combo scaling would lower later calls
            for phase,frame,_ in damage.schedules(pack)['two_ki']:
                at(c,phase,frame);self.assertEqual(c.r[2],1)
                self.assertGreater(c.u(c.actors[1]+0x9E4),0)
            run(c,damage.FINAL)
            self.assertEqual(c.u(c.actors[1]+0x9E4),max(0,hp-15000))

    def test_scenario_finisher_policy_and_kill_feed_keep_initiator_and_one_ko(self):
        import guest_killfeed as feed
        import story_runtime as story
        import story_rules as rules
        from test_story_rules import document
        for policy,valid in (('hold_at_1_hp',True),('hold_at_1_hp',False),('fail',False)):
            c,pack=machine(hp=200);doc=document(policy)
            if not valid:doc['finish_rules'][0]['form']=99
            c.write(story.DAMAGE,story.protection_code(story.DAMAGE,feed.DAMAGE))
            c.write(rules.DAMAGE,rules.damage_code(doc));c.w(rules.CONTROL,rules.MAGIC)
            c.write(rules.STATS,rules.stats_data(doc))
            c.write(story.CONTROL,struct.pack('<3I',story.MAGIC,c.u(tag.CONTROL+4),4))
            for index,actor in enumerate(c.actors):
                c.w(story.ACTORS+4*index,actor);c.w(actor+0x998,1)
            for address,code in ((feed.GATE,feed.gate_code()),(feed.ROW,feed.row_code()),
                    (feed.IDENTIFY,feed.identify_code()),(feed.RECORD,feed.record_code()),(feed.DAMAGE,feed.damage_code())):
                c.write(address,code)
            c.write(feed.CONTROL,struct.pack('<4I',1,c.u(tag.CONTROL+4),4,100))
            native=c.callbacks.pop(scene.A(0x1CE630));c.callbacks[feed.DAMAGE_NATIVE]=native
            c.write(scene.A(0x1CE630),struct.pack('<2I',0x08000000|(story.DAMAGE>>2),0))
            for phase,frame,_ in damage.schedules(pack)['two_ki']:
                at(c,phase,frame);self.assertEqual(c.r[2],1)
                self.assertEqual(c.u(feed.CONTROL+16),0)
            run(c,damage.FINAL);self.assertEqual(c.r[2],1)
            lethal=valid or policy=='fail'
            self.assertEqual(c.u(c.actors[1]+0x9E4),0 if lethal else 1)
            self.assertEqual(c.u(rules.LAST_INVALID+4),0 if valid else 1)
            self.assertEqual(c.u(feed.CONTROL+16),int(lethal))
            if lethal:self.assertEqual(struct.unpack('<8I',c.read(feed.EVENTS,32))[1:5],(1,0,1,0))
            run(c,damage.FINAL);self.assertEqual(c.u(feed.CONTROL+16),int(lethal))

    def test_full_director_uses_schedule_and_never_charges_twice_at_cleanup(self):
        from test_tag_rush_endings import machine as ending_machine
        for variant,name in enumerate(damage.VARIANTS[:4]):
            c=ending_machine(variant);c.write(damage.TABLE,damage.table_data(pack_fixture()))
            start(c)
            for _ in range(800):
                run(c,scene.STEP)
                if not c.u(tag.CONTROL+tag.C['active']):break
            self.assertEqual(c.u(tag.CONTROL+tag.C['completed']),1)
            self.assertEqual(c.u(tag.CONTROL+tag.C['cancelled']),0)
            self.assertEqual(sum(x[1]for x in c.damage),15000)
            self.assertEqual(len(c.damage),len(damage.schedules(pack_fixture())[name])+1)
            self.assertEqual(c.u(c.actors[1]+2376),217)
            count=len(c.damage);c.r[4]=0;run(c,scene.FINISH)
            self.assertEqual(len(c.damage),count)

    def test_real_disc_impact_schedule_is_complete_and_ordered(self):
        from pathlib import Path
        import native_map
        root=Path(__file__).resolve().parents[2]
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__).parent)
              else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        iso=root/'games'/name
        if not iso.is_file() or native_map.TRANSLATED:self.skipTest('Local identity-layout disc unavailable')
        pack=assets.build_assets(iso);rows=damage.schedules(pack)
        for name,events in rows.items():
            if name in ('blue_galick_kamehameha','super_galick_pair'):
                # The shared opening's contacts share 40%; the burst pays the rest.
                import tag_rush_blue_native as blue
                opening=[e for e in rows['two_ki'] if e[0]<4]
                self.assertEqual([e[:2] for e in events[:-1]],[e[:2] for e in opening])
                self.assertEqual(events[-1],(*blue.burst(name),10000))
                self.assertEqual(events[-2][2],4000);continue
            if name=='early_goku_piccolo':
                self.assertEqual(events,((4,choreography.BEAM_BURST,10000),))
                continue
            self.assertGreaterEqual(len(events),7)
            self.assertEqual(events,tuple(sorted(events)))
            self.assertEqual(events[-1][2],10000)
            self.assertTrue(all(a[2]<b[2] for a,b in zip(events,events[1:])))
            expected_custom=({(4,14),(4,32),(4,54),(5,22),(6,20),(7,24)}
                             if name=='two_melee' else set() if name=='two_ki'
                             else {(4,14),(4,32),(4,54),(5,22)})
            actual_custom={(phase,frame) for phase,frame,_ in events if phase>=4}
            if name!='two_melee':
                actual_custom.remove((len(pack['variants'][name]['phases'])-1,choreography.BEAM_BURST))
            self.assertEqual(actual_custom,expected_custom,name)
            if name!='two_melee':
                self.assertEqual(events[-2][2],4000)
                self.assertEqual(events[-1][1],choreography.BEAM_BURST)
        damage.table_data(pack)

    def test_special_sacrifice_and_normal_modes_charge_exact_selected_bodies(self):
        for enabled,multiplier,expected in ((False,2000,15000),(True,2000,30000),(True,1250,18750)):
            c,pack=machine(4,hp=1000000,sacrifice=enabled,multiplier=multiplier)
            c.w(c.actors[0]+0x9E4,1000000)
            at(c,4,choreography.BEAM_BURST-2);self.assertEqual(c.native_damage,[])
            at(c,4,choreography.BEAM_BURST);self.assertEqual(c.r[2],1)
            run(c,damage.FINAL);self.assertEqual(c.r[2],1)
            for index,total in ((0,expected if enabled else 0),(1,expected),(2,0),(3,0)):
                self.assertEqual(sum(row[1] for row in c.native_damage if row[0]==c.actors[index]),total)
            self.assertEqual(c.u(damage.STATE+damage.C['goku_loss']),expected if enabled else 0)
            self.assertEqual(c.u(damage.STATE+damage.C['loss']),expected)
            before=list(c.native_damage);run(c,damage.FINAL);self.assertEqual(c.native_damage,before)

    def test_sacrifice_low_hp_and_maximum_damage_do_not_overflow(self):
        for hp,amount,multiplier in ((200,15000,2000),(1000000,100000,5000),(1000000,15001,1250)):
            c,_=machine(4,hp=hp,multiplier=multiplier);c.w(c.actors[0]+0x9E4,hp)
            c.w(tag.CONTROL+tag.C['damage'],amount);run(c,damage.RESET)
            at(c,4,choreography.BEAM_BURST);self.assertEqual(c.r[2],1)
            self.assertGreaterEqual(c.u(c.actors[0]+0x9E4),1)
            self.assertGreaterEqual(c.u(c.actors[1]+0x9E4),1)
            run(c,damage.FINAL);self.assertEqual(c.r[2],1)
            expected=amount*multiplier//1000
            for index in (0,1):
                self.assertEqual(c.u(c.actors[index]+0x9E4),max(0,hp-expected))
                self.assertEqual(sum(row[1] for row in c.native_damage if row[0]==c.actors[index]),expected)

    def test_sacrifice_never_damages_replaced_body_or_changed_hp_bank(self):
        for changed in ('character','bank','pointer'):
            c,_=machine(4)
            if changed=='character':c.w(c.models[0]+12,1)
            elif changed=='bank':c.w(c.actors[0]+0x994,1)
            else:c.w(tag.core.POINTERS,c.actors[3])
            at(c,4,choreography.BEAM_BURST)
            self.assertEqual(c.r[2],0)
            self.assertFalse(any(row[0]==c.actors[0] for row in c.native_damage))

    def test_special_cancel_before_beam_does_not_pay_either_fighter(self):
        c,_=machine(4);c.w(scene.STATE+scene.S['cancelled'],1)
        at(c,4,choreography.BEAM_BURST);run(c,damage.FINAL)
        self.assertEqual(c.r[2],0);self.assertEqual(c.native_damage,[])

    def test_rejects_unreviewed_or_late_contact_and_respects_reserved_boundaries(self):
        pack=pack_fixture();phase=pack['audio_cues']['two_ki'][-1]
        pack['audio_cues']['two_ki']=(*pack['audio_cues']['two_ki'][:-1],(*phase,dict(role=2,frame=179,sound_id=73,effect_kind=16)))
        with self.assertRaisesRegex(ValueError,'follows beam'):damage.schedules(pack)
        import tag_rush_colors,tag_rush_beam_audio
        self.assertGreaterEqual(damage.RESET,tag_rush_colors.STORAGE_END)
        self.assertLessEqual(damage.END,tag_rush_beam_audio.INIT)
        blocks=sorted(damage.pieces()+[(damage.TABLE,damage.table_data(pack_fixture()))])
        self.assertTrue(all(p+len(b)<=q for(p,b),(q,_)in zip(blocks,blocks[1:])))


if __name__=='__main__':unittest.main()
