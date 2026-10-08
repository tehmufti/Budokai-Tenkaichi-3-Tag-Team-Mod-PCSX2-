"""Execute the new authoring primitives, seat publication and native KO path."""
import copy
import json
import struct
import unittest
from unittest.mock import patch
import story_missions as doc
import story_runtime as story
import story_rules as rules
import story_cast as cast
import story_cinematics as cinema
from native_map import A
from test_story_missions import machine, tick
import test_story_rules as damage_tests
import test_story_cinematics as cine_tests


def battle(actions,when=None,**event):
    d=doc.default_mission()
    d['fighters'].append(dict(id='ally',team=1,slot=2,character=23,reserve=False))
    d['events']=[dict(id='scene',when=when or dict(type='time',seconds=0),actions=actions,**event)]
    return doc.validate(d)


def seats(c,quad=False):
    if quad:
        c.w(cast.pads.CONTROL,cast.pads.MAGIC);c.w(cast.pads.CONTROL+4,c.manager)
        base,fields=cast.quad.CONTROL,cast.quad.F
    else:
        base,fields=cast.spec.CONTROL,cast.seats.F
        c.w(base,cast.spec.MAGIC);c.w(base+cast.spec.FIELDS['manager'],c.manager)
        c.w(base+fields['version'],cast.seats.VERSION)
    c.w(base+fields['human_ports'],1)
    for i in range(4 if quad else 2):c.w(base+fields['owned']+4*i,0 if i==0 else i)
    c.write(cast.TRANSFER,cast.transfer_code())
    return base,fields


class AuthoringRuntimeTests(unittest.TestCase):
    def test_wait_advances_on_combat_time_once_and_pauses_with_game(self):
        d=battle([dict(type='wait',seconds=.1),dict(type='heal',fighter='hero',health_percent=50)])
        c=machine(d);tick(c)
        c.w(A(0x3337B8),0x100);tick(c,20);self.assertEqual(c.u(story.EVENTS+4),0)
        c.w(A(0x3337B8),0);tick(c,story.ACTOR_HZ//10)
        self.assertEqual(c.u(story.EVENTS+4),1);self.assertEqual(c.u(c.actors[0]+0x9E4),30000)
        tick(c,2);self.assertEqual(c.u(c.actors[0]+0x9E4),15000)
        c.w(c.actors[0]+0x9E4,100);tick(c,5);self.assertEqual(c.u(c.actors[0]+0x9E4),100)

    def test_relative_delay_starts_after_event_completes(self):
        d=battle([dict(type='wait',seconds=.1)])
        d['events'].append(dict(id='later',when=dict(type='event',event='scene',delay_seconds=.1),actions=[dict(type='heal',fighter='hero',health_percent=50)]))
        c=machine(doc.validate(d));tick(c,story.ACTOR_HZ//10+2)
        completed=c.u(story.EVENTS+16);self.assertEqual(c.u(story.EVENTS),2)
        self.assertEqual(c.u(story.EVENTS+story.EVENT_STRIDE),0)
        tick(c,story.ACTOR_HZ//10);self.assertGreaterEqual(c.u(story.CONTROL+12)-completed,story.ACTOR_HZ//10)
        self.assertEqual(c.u(c.actors[0]+0x9E4),15000)

    def test_failed_event_branches_and_fail_scenario_latches(self):
        d=battle([dict(type='transform',fighter='hero',character=99)],on_failure='fail_scenario')
        c=machine(d);tick(c);self.assertEqual(c.u(story.EVENTS),3)
        self.assertEqual(c.u(story.CONTROL+96),2);self.assertEqual(c.u(story.CONTROL+128),0)
        d['events'][0]['on_failure']='continue'
        d['events'].append(dict(id='fallback',when=dict(type='event_failed',event='scene'),actions=[dict(type='message',text='Fallback',seconds=1)]))
        c=machine(doc.validate(d));tick(c,2);self.assertEqual(c.u(story.EVENTS+story.EVENT_STRIDE),2)

    def test_partial_stats_keep_other_values_and_private_ai_pointer(self):
        d=battle([dict(type='set_stats',fighter='ally',stats=dict(max_hp=45000,health_percent=80,damage=1.8,defense=1.3,ki_percent=50,blast_stocks=99,difficulty=3))])
        c=machine(d);c.w(c.actors[2]+0x9F4,10000);c.w(c.actors[2]+0x9FC,4)
        from ai_shadow import AI_GLOBAL
        c.w(AI_GLOBAL,0x1550000);calls=[]
        c.callbacks[A(0x1BB478)]=lambda m:calls.append(tuple(m.r[4:6]))
        tick(c)
        self.assertEqual(c.u(c.actors[2]+0x9E4),36000);self.assertEqual(c.u(c.actors[2]+0x9E8),45000)
        self.assertEqual(c.u(c.actors[2]+0x9F0),5000);self.assertEqual(c.u(c.actors[2]+0x9F8),4)
        self.assertEqual(c.u(c.actors[2]+0x9DC),3);self.assertEqual(c.u(AI_GLOBAL),0x1550000)
        self.assertEqual(calls,[(0,3)])
        self.assertEqual(c.read(rules.STATS+2*16,8),struct.pack('<2I',1800,1300))

    def test_control_handoff_publishes_legacy_and_quad_then_retires_leader(self):
        d=battle([dict(type='take_control',fighter='ally',player=1),dict(type='despawn',fighter='hero')])
        for quad in (False,True):
            c=machine(d);base,fields=seats(c,quad);c.w(story.part.CONSUMED,0)
            tick(c,3)
            self.assertEqual(c.u(base+fields['owned']),2)
            self.assertEqual(c.u(c.actors[2]+0x1278),0)
            self.assertEqual(c.u(c.actors[0]+0x9E4),0);self.assertEqual(c.u(c.models[0]+8),0)
            self.assertEqual(c.u(story.part.CONSUMED)&3,0)
            self.assertEqual(c.u(cast.RETIRED),1);self.assertEqual(c.u(story.EVENTS),2)
            self.assertEqual(c.u(cast.specials.CONTROL+20)&5,4)
            if quad:self.assertEqual(c.u(cast.views.SUBJECTS),2)
            else:self.assertEqual(c.u(cast.camera.SUCCESSOR_CONTROL+8),2)
            c.w(c.models[0]+8,1);tick(c);self.assertEqual(c.u(c.models[0]+8),0)

    def test_handoff_cannot_steal_another_humans_body_or_cross_stale_world(self):
        c=machine(battle([dict(type='wait',seconds=1)]));base,fields=seats(c,True)
        c.w(base+fields['human_ports'],3);c.w(base+fields['owned']+4,2)
        c.r[4:6]=[0,2];c.r[31]=0xFEED0000;c.run(cast.TRANSFER)
        self.assertEqual(c.r[2],0);self.assertEqual(c.u(base+fields['owned']),0)
        c.w(base+fields['human_ports'],1);c.w(cast.pads.CONTROL+4,c.manager+4)
        c.r[4:6]=[0,2];c.r[31]=0xFEED0000;c.run(cast.TRANSFER);self.assertEqual(c.r[2],0)

    def test_exit_cannot_hide_a_body_still_owned_by_human(self):
        c=machine(battle([dict(type='despawn',fighter='hero')]));seats(c)
        tick(c,3);self.assertEqual(c.u(story.EVENTS),1)
        self.assertEqual(c.u(c.models[0]+8),1);self.assertEqual(c.u(cast.RETIRED),0)

    def test_extra_exit_not_a_fake_kill_and_retired_trigger_is_distinct(self):
        d=battle([dict(type='despawn',fighter='ally')])
        d['events'].append(dict(id='gone',when=dict(type='retired',fighter='ally'),actions=[dict(type='heal',fighter='hero',health_percent=50)]))
        d['events'].append(dict(id='killed',when=dict(type='defeated',fighter='ally'),actions=[dict(type='heal',fighter='hero',health_percent=25)]))
        c=machine(doc.validate(d));seats(c);c.w(story.part.CONSUMED,0);tick(c,3)
        self.assertEqual(c.u(story.part.CONSUMED),4)
        self.assertEqual(c.u(story.abi.CONTROL+cast.spec.DEAD+8),1)
        self.assertEqual(c.u(story.EVENTS+story.EVENT_STRIDE),2)
        self.assertEqual(c.u(story.EVENTS+2*story.EVENT_STRIDE),0)
        self.assertEqual(c.u(c.actors[0]+0x9E4),15000)

    def test_inverted_active_condition_and_target_update(self):
        d=battle([dict(type='target',fighter='hero',target='rival')],dict(type='not',condition=dict(type='health_above',fighter='hero',percent=50)))
        c=machine(d);tick(c);self.assertEqual(c.u(story.EVENTS),0)
        c.w(c.actors[0]+0x9E4,15000);tick(c);self.assertEqual(c.u(story.core.TABLE),1)
        import fresh_team_ai as ai
        self.assertEqual(c.u(ai.DESCRIPTORS[0]+24),ai.DESCRIPTORS[1])

    def test_authored_defeat_uses_real_native_action_queue(self):
        import test_revive_native_path as native
        d=battle([dict(type='defeat',fighter='hero')]);c=machine(d)
        class NativeStoryCpu(type(c),native.Cpu):pass
        c.__class__=NativeStoryCpu;n=native.fixture()
        c.memory.update(n.memory);c.callbacks.update(n.callbacks);c.events=[]
        c.w(native.ACTOR+0x948,11);c.w(native.ACTOR+0x9E4,30000);c.w(native.ACTOR+0x994,0);c.w(native.ACTOR+0x998,1)
        tick(c);self.assertEqual(c.u(native.ACTOR+0x9E4),0)
        self.assertEqual(c.u(native.ACTOR+0x94C),216)
        native.dispatch(c);self.assertEqual(c.u(native.ACTOR+0x948),216)

    def test_frozen_wait_is_camera_only_and_keeps_the_preceding_endpoint(self):
        d=battle([dict(type='cinematic',fighter='hero',seconds=1,camera=dict(eye=[0,-16,55],target=[0,-9,0],end_eye=[8,-16,55])),dict(type='wait',seconds=.5,freeze=True)])
        actions=story.expanded_program(d)['events'][0]['actions']
        self.assertEqual(actions[1]['type'],'cinematic');self.assertNotIn('animation',actions[1])
        self.assertEqual(actions[1]['camera']['eye'],[8,-16,55])


class AuthoringDamageTests(unittest.TestCase):
    def hit(self,d,**kwargs):
        original=damage_tests.machine
        def initialized(document):
            c=original(document);c.write(rules.STATS,rules.stats_data(document));c.hi=17;c.lo=19;return c
        with patch.object(damage_tests,'machine',side_effect=initialized):return damage_tests.RuleTests().hit(d,**kwargs)
    def test_outgoing_and_defense_multipliers_unknown_attackers_and_hilo(self):
        d=doc.default_mission();d['fighters'][0]['stats']=dict(damage=2);d['fighters'][1]['stats']=dict(defense=4)
        c,seen=self.hit(d,damage=4000);self.assertEqual(seen[0][1],2000)
        self.assertEqual((c.hi,c.lo),(17,19))
        c,seen=self.hit(d,damage=4000,caller=0x123450);self.assertEqual(seen[0][1],1000)
    def test_invulnerability_and_unbeatable_floor_are_native_damage_guards(self):
        d=doc.default_mission();d['fighters'][1]['stats']=dict(invulnerable=True)
        c,_=self.hit(d);self.assertEqual(c.u(c.actors[1]+0x9E4),30000)
        d['fighters'][1]['stats']=dict(cannot_be_defeated=True)
        c,seen=self.hit(d);self.assertEqual(c.u(c.actors[1]+0x9E4),1);self.assertTrue(seen[0][2]&0x400)
    def test_invulnerable_contact_refuses_incoming_only(self):
        d=doc.default_mission();d['fighters'][1]['stats']=dict(invulnerable=True)
        c=machine(d);c.write(rules.STATS,rules.stats_data(d));c.w(rules.CONTROL,rules.MAGIC)
        c.write(story.CONTACT,story.protection_code(story.CONTACT,0x110000,'contact'))
        c.callbacks[0x110000]=lambda m:m.r.__setitem__(2,7)
        for source,target,wanted in ((0,1,1),(1,0,7)):
            c.r[4:6]=[c.actors[source],c.actors[target]];c.r[31]=0xFEED0000;c.run(story.CONTACT);self.assertEqual(c.r[2],wanted)


class AuthoringCameraTests(unittest.TestCase):
    def test_camera_only_does_not_replace_or_advance_animation(self):
        c,_=cine_tests.fixture();c.w(cinema.DESCRIPTORS,0);tick(c)
        before=(c.read(c.actors[0],0x1600),c.u(c.models[0]+192),c.u(c.models[0]+3200))
        for _ in range(3):c.r[31]=0xFEED0000;c.run(cinema.TICK)
        self.assertEqual((c.read(c.actors[0],0x1600),c.u(c.models[0]+192),c.u(c.models[0]+3200)),before)
        self.assertNotIn(0x24D038,[x[0] for x in c.calls])
        self.assertEqual(c.u(cinema.CONTROL+12),3)
    def test_camera_position_and_aim_share_smooth_easing_and_endpoints(self):
        camera=dict(eye=[0,-16,55],end_eye=[40,-16,55],target=[0,-9,0],end_target=[8,-5,0])
        smooth=cinema.camera_samples(camera,5);linear=cinema.camera_samples(dict(camera,easing='linear'),5)
        self.assertEqual(len(smooth),160)
        self.assertEqual(smooth[:32],linear[:32]);self.assertEqual(smooth[-32:],linear[-32:])
        self.assertAlmostEqual(struct.unpack_from('<f',smooth,32)[0],6.25)
        self.assertAlmostEqual(struct.unpack_from('<f',linear,32)[0],10)


class AuthoringValidationTests(unittest.TestCase):
    def test_bad_stats_delays_and_camera_easing_rejected(self):
        for s in (dict(defense=0),dict(damage=float('nan')),dict(invulnerable=1),dict(max_hp=0),dict(code=1)):
            with self.assertRaises(ValueError):doc.validate_stats(s)
        with self.assertRaisesRegex(ValueError,'wait'):battle([dict(type='wait',seconds=30)],timeout_seconds=10)
        with self.assertRaises(ValueError):battle([dict(type='wait',seconds=31,freeze=True)])
        with self.assertRaises(ValueError):battle([dict(type='cinematic',fighter='hero',camera=dict(eye=[0,-16,55],target=[0,-9,0],easing='bounce'))])
    def test_initial_stat_code_has_a_checked_reservation(self):
        d=doc.default_mission()
        d['fighters']=[dict(id=f'f{i}',team=i%2+1,slot=i//2+1,character=0,stats=dict(max_hp=50000,health_percent=100,ki_percent=100,blast_stocks=5,difficulty=4)) for i in range(10)]
        with self.assertRaisesRegex(ValueError,'initialization space'):story.validate_compilation(doc.validate(d))


if __name__=='__main__':unittest.main()
