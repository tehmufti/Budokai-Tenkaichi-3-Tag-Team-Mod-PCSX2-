"""Run each curated battle's complete event/control/result chain on the guest CPU.

Native animation/render, resource completion and terrain leaves are callbacks.
This proves the authored choreography and ownership, not in-game appearance.
"""
import struct
import unittest
from pathlib import Path
import story_missions as doc
import story_runtime as story
import story_rules as rules
import story_cinematics as cinema
from native_map import A
from test_story_cinematics import fixture
from test_story_missions import tick
from test_story_authoring import seats

NAMES=('namek-piccolo-arrives','saiyans-goku-arrives','cell-games-gohan-awakens')


def scene_machine(d):
    c,_=fixture();count=2*max(f['slot'] for f in d['fighters'])
    c.actors=[0x1900000+0x2000*i for i in range(count)];c.models=[0x900000+0x2000*i for i in range(count)]
    lookup={story.physical(f):f for f in d['fighters']}
    for i,(actor,model) in enumerate(zip(c.actors,c.models)):
        c.w(story.core.POINTERS+4*i,actor);c.w(story.ACTORS+4*i,actor);c.w(story.core.MODELS+4*i,model)
        f=lookup.get(i,{})
        for off,v in ((0,i),(8,i&1),(12,i),(0x948,11),(0x94C,-1),(0x998,1),(0x9E4,0 if f.get('reserve') else f.get('hp',30000)),
                      (0x9E8,f.get('hp',30000)),(0x9F4,10000),(0x9FC,5),(0x1278,int(i>0))):c.w(actor+off,v)
        for off,v in ((4,1),(8,int(not f.get('reserve'))),(12,f.get('character',i)),(16,i)):c.w(model+off,v)
        c.w(model+4000,model+3936);c.w(model+4004,model+3968)
        c.w(model+0x91C,0x1600000+0x1000*i);c.write(0x1600000+0x1000*i+152,bytes((16,1,2,255)))
    for p in (story.core.MODE+4,story.core.MODE+12,story.CONTROL+8,cinema.CONTROL+8):c.w(p,count)
    c.w(story.CONTROL+56,1);c.w(story.part.CONSUMED,sum(1<<i for i,f in lookup.items() if f.get('reserve')))
    c.write(rules.STATS,rules.stats_data(d));c.w(rules.CONTROL,rules.MAGIC)
    c.callbacks[A(0x1BB478)]=lambda m:None
    import spawn_placement
    c.w(spawn_placement.STAGE,0x1800000)
    c.resets=[]
    def arrival(m):
        actor=m.r[4];model=m.r[5];index=m.u(actor)
        m.resets.append(index);m.write(model+2416,struct.pack('<4f',index*100.,0.,(index%2)*200.,1.));m.r[2]=1
    c.callbacks[story.ARRIVAL]=arrival
    c.callbacks[A(0x1E23D0)]=lambda m:(m.w(m.r[4]+0x948,11),m.w(m.r[4]+0x94C,-1))
    seats(c);program=story.expanded_program(d)
    c.write(story.FRAME,story.frame(program,{i:int(i>0) for i in range(count)}))
    shots=[a for e in program['events'] for a in e['actions'] if a['type']=='cinematic']
    for n,shot in enumerate(shots):
        # One-frame shots exercise the same start/end path without thousands
        # of mocked render ticks. Easing/duration are tested independently.
        addr=cinema.CLIPS+0x100+n*32
        c.write(addr,cinema.camera_samples(shot['camera'],1))
        c.write(cinema.DESCRIPTORS+n*cinema.STRIDE,struct.pack('<IIfiii12f2I',
                cinema.CLIPS if shot.get('animation') else 0,1,shot['speed'],-1,0,100,
                *shot['camera']['eye'],*shot['camera']['target'],*shot['camera'].get('end_eye',shot['camera']['eye']),
                *shot['camera'].get('end_target',shot['camera']['target']),addr,sum(1<<story.physical(f) for f in d['fighters']) if shot.get('reset_positions') else 0))
    return c


def advance(c,n=1):
    for _ in range(n):
        for actor in c.actors:
            pending=c.u(actor+0x94C)
            if pending==216:c.w(actor+0x948,216);c.w(actor+0x94C,-1)
            elif 236<=pending<=239:
                index=c.u(actor+12);c.w(c.models[index]+12,16);c.w(actor+0x94C,-1);c.w(actor+0x948,11)
        if c.u(cinema.CONTROL+12) in (1,2):c.r[31]=0xFEED0000;c.run(cinema.TICK)
        tick(c)


class CuratedBattleTests(unittest.TestCase):
    def test_formation_reset_skips_reserves_corpses_and_retired_fighters(self):
        d=self.document(NAMES[0]);c=scene_machine(d)
        c.w(c.actors[2]+0x9E4,0)
        c.w(story.CONTROL+112,1<<4)
        self.complete(c,d,'frieza-line')
        self.assertEqual(c.resets,[0,1])
        self.assertEqual(c.u(c.actors[2]+0x9E4),0)
        self.assertEqual(c.u(c.actors[6]+0x9E4),0)

    def test_reset_waits_for_bound_action_without_moving_any_fighter(self):
        d=self.document(NAMES[0]);c=scene_machine(d)
        c.w(c.actors[4]+0x948,239)
        advance(c,5);self.assertEqual(c.resets,[])
        self.assertEqual(c.u(cinema.CONTROL+12),0)
        c.w(c.actors[4]+0x948,11)
        self.complete(c,d,'frieza-line');self.assertEqual(c.resets,[0,1,2,4])

    def test_namek_reinforcements_do_not_stall_when_cpu_ally_is_dead(self):
        d=self.document(NAMES[0]);c=scene_machine(d)
        self.complete(c,d,'frieza-line');c.w(c.actors[2]+0x9E4,0);c.w(c.actors[2]+0x948,216)
        self.clock_to_entrance(c,d);self.complete(c,d,'piccolo-lands')
        self.complete(c,d,'frieza-sizes-up');self.complete(c,d,'allies-withdraw');self.complete(c,d,'duel')
        self.assertEqual(c.u(c.actors[2]+0x9E4),0)
        self.assertEqual(c.u(c.actors[6]+0x1278),0)

    def document(self,name):return doc.load(doc.LIBRARY/'Examples'/(name+'.json'))
    def complete(self,c,d,event):
        offset=story.EVENTS+next(i for i,e in enumerate(d['events']) if e['id']==event)*story.EVENT_STRIDE
        for _ in range(150):
            if c.u(offset)>=2:break
            advance(c)
        self.assertEqual(c.u(offset),2,f'{event} failed or stalled at action {c.u(offset+4)}')
    def clock(self,c,seconds):c.w(story.CONTROL+12,max(c.u(story.CONTROL+12),round(seconds*story.ACTOR_HZ)))
    def clock_to_entrance(self,c,d):
        # Local examples are editable; honor the authored survival duration.
        event=next(e for e in d['events'] if e['id']=='piccolo-lands')
        self.assertEqual(event['when']['type'],'time')
        self.clock(c,event['when']['seconds'])
    def test_namek_handoff_rebalance_exits_and_win(self):
        d=self.document(NAMES[0]);c=scene_machine(d)
        self.complete(c,d,'frieza-line')
        self.assertEqual(c.u(story.core.POINTERS+24),c.actors[6]);self.assertEqual(c.u(story.part.CONSUMED)&64,64)
        self.clock_to_entrance(c,d);self.complete(c,d,'piccolo-lands')
        self.complete(c,d,'frieza-sizes-up');self.complete(c,d,'allies-withdraw');self.complete(c,d,'duel')
        import spectator_switch as spec,spectator_takeover as takeover
        self.assertEqual(c.u(spec.CONTROL+takeover.F['owned']),6)
        self.assertEqual(c.u(c.actors[6]+0x1278),0);self.assertEqual(c.u(c.actors[6]+0x9E4),45000)
        self.assertEqual(c.u(c.actors[1]+0x9E4),45000);self.assertEqual(c.u(rules.STATS+16+12),0)
        for i in (0,2,4):self.assertEqual(c.u(c.models[i]+8),0)
        self.assertEqual(c.u(story.CONTROL+96),0)
        c.w(c.actors[1]+0x9E4,0);advance(c);self.assertEqual(c.u(story.CONTROL+96),1)
    def test_saiyan_sacrifice_two_waves_and_final_win(self):
        d=self.document(NAMES[1]);c=scene_machine(d)
        self.complete(c,d,'nappa-line');self.clock(c,36)
        self.complete(c,d,'piccolos-sacrifice');self.assertEqual(c.u(c.actors[4]+0x9E4),0)
        self.clock(c,c.u(story.CONTROL+12)/story.ACTOR_HZ+9)
        self.complete(c,d,'goku-lands');self.complete(c,d,'nappa-sizes-up');self.complete(c,d,'allies-withdraw')
        self.complete(c,d,'nappa-round')
        self.assertEqual(c.u(c.actors[6]+0x1278),0)
        c.w(c.actors[1]+0x9E4,0);c.w(c.actors[1]+0x948,216)
        self.complete(c,d,'vegeta-steps-in');self.complete(c,d,'goku-faces-vegeta');self.complete(c,d,'nappa-leaves')
        self.complete(c,d,'final-round')
        self.assertEqual(c.u(c.actors[3]+0x9E4),60000)
        self.assertEqual(c.u(c.models[1]+8),0);self.assertEqual(c.u(story.CONTROL+96),0)
        c.w(c.actors[3]+0x9E4,0);advance(c);self.assertEqual(c.u(story.CONTROL+96),1)
    def test_cell_scripted_death_awakening_and_ultimate_requirement(self):
        d=self.document(NAMES[2]);c=scene_machine(d)
        self.complete(c,d,'cell-line');self.clock(c,35)
        self.complete(c,d,'android16-pleads');self.complete(c,d,'cell-strikes')
        self.assertEqual(c.u(c.actors[2]+0x9E4),0)
        self.clock(c,c.u(story.CONTROL+12)/story.ACTOR_HZ+2)
        self.complete(c,d,'gohan-breaks');self.complete(c,d,'android16-leaves')
        self.complete(c,d,'awakening');self.assertEqual(c.u(c.models[0]+12),16)
        self.assertEqual(c.u(c.actors[0]+0x9E4),50000);self.assertEqual(c.u(c.actors[1]+0x9E4),85000)
        self.assertEqual(c.u(rules.STATS+8),0);self.assertEqual(c.u(c.models[2]+8),0)
        self.assertEqual(d['finish_rules'][0]['form'],16)
        c.w(c.actors[1]+0x9E4,0);advance(c);self.assertEqual(c.u(story.CONTROL+96),1)
    def test_nothing_starts_or_counts_under_the_preparation_loading_cover(self):
        import guest_loading_screen as cover
        for name in NAMES:
            d=self.document(name);c=scene_machine(d);c.w(cover.CONTROL,cover.MAGIC)
            advance(c,10)
            self.assertEqual(c.u(story.CONTROL+12),0,name);self.assertEqual(c.u(story.EVENTS),0,name)
            self.assertEqual(c.u(cinema.CONTROL+12),0,name)
            c.w(cover.CONTROL,0);advance(c,story.ACTOR_HZ+3)
            self.assertGreater(c.u(story.CONTROL+12),0,name);self.assertGreater(c.u(story.EVENTS),0,name)
    def test_camera_only_shot_holds_a_busy_fighter_but_an_animated_shot_waits(self):
        base=dict(schema='tag-team-mission',version=1,id='busy',title='Busy',game_family='bt3',
                  fighters=[dict(id='hero',team=1,slot=1,character=0),dict(id='rival',team=2,slot=1,character=29),
                            dict(id='ally',team=1,slot=2,character=1),dict(id='other',team=2,slot=2,character=2)])
        camera=dict(eye=[0,-14,24],target=[0,-10,0])
        for animated in (False,True):
            shot=dict(type='cinematic',fighter='rival',seconds=1,camera=camera)
            if animated:shot['animation']=dict(character=29,clip=384)
            d=doc.validate(dict(base,events=[dict(id='look',when=dict(type='time',seconds=0),actions=[shot])]))
            c=scene_machine(d);c.w(c.actors[1]+0x948,55)  # charging ki: not an idle action window
            advance(c,6)
            self.assertEqual(c.u(story.EVENTS)==2,not animated,animated)
            c.w(c.actors[1]+0x948,11);advance(c,6);self.assertEqual(c.u(story.EVENTS),2,animated)
    def test_early_player_ko_fails_each_scene_without_waiting_for_reserves(self):
        for name in NAMES:
            d=self.document(name);c=scene_machine(d);c.w(c.actors[0]+0x9E4,0);advance(c)
            self.assertEqual(c.u(story.CONTROL+96),2,name)
    def test_cpu_only_scenario_keeps_entrant_under_cpu_control(self):
        import spectator_switch as spec,spectator_takeover as takeover
        d=self.document(NAMES[0]);c=scene_machine(d);c.w(spec.CONTROL+takeover.F['human_ports'],0)
        self.complete(c,d,'frieza-line');self.clock_to_entrance(c,d)
        self.complete(c,d,'piccolo-lands');self.complete(c,d,'allies-withdraw')
        self.assertEqual(c.u(c.actors[6]+0x1278),1);self.assertEqual(c.u(c.models[0]+8),0)
    def test_exact_three_examples_and_no_states_or_code_in_definitions(self):
        self.assertEqual({p.stem for p in (doc.LIBRARY/'Examples').glob('*.json')},set(NAMES))
        for name in NAMES:
            d=self.document(name);story.validate_compilation(d)
            self.assertFalse(d['menus']['character_select']);self.assertFalse(d['player_selection'])
            self.assertTrue(all(not f['transformations']['enabled'] for f in d['fighters']))
            # Story text is being redesigned: the showcase scenes carry no on-screen message actions.
            self.assertFalse([a for e in d['events'] for a in e['actions'] if a['type']=='message'],name)


if __name__=='__main__':unittest.main()
