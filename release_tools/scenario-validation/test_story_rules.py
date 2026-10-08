"""Execute the compiled scenario rules with real caller provenance/ABI frames."""
import copy
import struct
import unittest
from native_map import A
from test_story_missions import machine,tick,DependencyTests
import story_missions as doc
import story_runtime as story
import story_rules as rules


def document(outcome='hold_at_1_hp'):
    d=doc.default_mission()
    d['finish_rules']=[dict(victim='rival',attacker='hero',attack='ultimate',otherwise=outcome)]
    return doc.validate(d)


class RuleTests(unittest.TestCase):
    def hit(self,d,damage=50000,flags=0,attacker=0,caller=None):
        c=machine(d);c.write(rules.DAMAGE,rules.damage_code(d));c.w(rules.CONTROL,rules.MAGIC)
        previous=0x110000;c.write(story.DAMAGE,story.protection_code(story.DAMAGE,previous))
        # Emulate only the final native HP store, with native 0400 semantics.
        seen=[]
        def apply(m):
            hp=m.u(m.r[4]+0x9E4);seen.append(tuple(m.r[4:7]))
            m.w(m.r[4]+0x9E4,max(1 if m.r[6]&0x400 else 0,hp-m.r[5]))
        c.callbacks[previous]=apply
        pc=next(iter(story.abi.ATTRIBUTION)) if caller is None else caller
        if pc in story.abi.ATTRIBUTION:c.r[story.abi.ATTRIBUTION[pc]]=c.actors[attacker]
        c.r[4:7]=[c.actors[1],damage,flags];c.r[31]=pc
        c.run(story.DAMAGE,stops=(pc,))
        return c,seen

    def test_wrong_finisher_clamps_in_native_damage_path(self):
        for flags in (0,0x800000,0x1000000):
            c,seen=self.hit(document(),flags=flags)
            self.assertEqual(c.u(c.actors[1]+0x9E4),1)
            self.assertEqual(seen[0][2],flags|0x400)
            self.assertEqual(c.u(rules.LAST_INVALID+4),1)

    def test_delayed_ultimate_uses_hit_category_not_current_animation(self):
        for pc in story.abi.ATTRIBUTION:
            c,seen=self.hit(document(),flags=0x2000000,caller=pc)
            self.assertEqual(c.u(c.actors[1]+0x9E4),0,hex(pc))
            self.assertEqual(c.u(rules.LAST_INVALID+4),0)
        c,_=self.hit(document(),flags=0x2000000,attacker=3)
        self.assertEqual(c.u(c.actors[1]+0x9E4),1)
        c,_=self.hit(document(),flags=0x2000000,caller=0x123450)
        self.assertEqual(c.u(c.actors[1]+0x9E4),1)

    def test_fail_only_after_invalid_hit_kills_and_overrides_immediate_result(self):
        d=document('fail');c,_=self.hit(d,damage=100)
        tick(c);self.assertEqual(c.u(story.CONTROL+96),0)
        c,_=self.hit(d);previous=0x110100
        c.callbacks[previous]=lambda m:m.r.__setitem__(2,1)
        c.write(story.RESULT,story.result_code(d,previous))
        # Results queried before another frame update must still fail Team 1.
        for side,wanted in ((1,0),(0,1)):
            c.r[4]=side;c.r[31]=0xFEED0000;c.run(story.RESULT)
            self.assertEqual(c.r[2],wanted)
        self.assertEqual(c.u(story.CONTROL+96),2)
        self.assertEqual(c.u(story.CONTROL+100),1)

    def test_required_form_and_special_category(self):
        d=document();d['finish_rules'][0]['form']=1
        c,_=self.hit(d,flags=0x2000000);self.assertEqual(c.u(c.actors[1]+0x9E4),1)
        d=document();d['finish_rules'][0]['attack']='special'
        for flag in (0x800000,0x1000000,0x2000000):
            c,_=self.hit(d,flags=flag);self.assertEqual(c.u(c.actors[1]+0x9E4),0)

    def test_authored_fail_has_priority_and_is_latched(self):
        d=doc.default_mission();d['win_when']=d['fail_when']=dict(type='time',seconds=0)
        c=machine(d);tick(c);self.assertEqual(c.u(story.CONTROL+96),2)
        tick(c,3);self.assertEqual(c.u(story.CONTROL+96),2)

    def test_authored_win_waits_for_its_condition_but_native_player_defeat_still_loses(self):
        d=doc.default_mission();d['win_when']=dict(type='time',seconds=60)
        c=machine(d);previous=0x110100;c.callbacks[previous]=lambda m:m.r.__setitem__(2,1)
        c.write(story.RESULT,story.result_code(d,previous))
        for side,expected in ((1,0),(0,1)):
            c.r[4]=side;c.r[31]=0xFEED0000;c.run(story.RESULT);self.assertEqual(c.r[2],expected)
        c.w(story.CONTROL+12,60*story.ACTOR_HZ)
        c.r[4]=1;c.r[31]=0xFEED0000;c.run(story.RESULT);self.assertEqual(c.r[2],1)

    def test_forms_limits_apply_to_humans_and_cpus_but_scripted_form_bypasses(self):
        for index in (0,1):
            d=doc.default_mission();d['fighters'][index]['transformations']=dict(enabled=False)
            c=machine(d);c.write(rules.FORMS,rules.forms_code(d));c.w(rules.CONTROL,rules.MAGIC)
            c.write(story.CHANCE,story.chance_code({}));c.callbacks[story.CHANCE_NATIVE]=lambda m:m.r.__setitem__(2,0)
            c.r[4]=c.actors[index];c.r[5]=0;c.r[31]=0xFEED0000;c.run(story.CHANCE);self.assertEqual(c.r[2],1)
            c.w(story.CONTROL+36,1<<index);c.r[31]=0xFEED0000;c.run(story.CHANCE);self.assertEqual(c.r[2],0)
        d=doc.default_mission();d['fighters'][0]['transformations']=dict(allowed_forms=[2],limit=1)
        c=machine(d);c.write(rules.FORMS,rules.forms_code(d))
        for slot,count,denied in ((0,0,1),(1,0,0),(1,1,1),(4,0,1)):
            c.w(story.ACTORS+0x204,count);c.r[4]=c.actors[0];c.r[5]=slot;c.r[31]=0xFEED0000
            c.run(rules.FORMS);self.assertEqual(c.r[2],denied)

    def test_authored_hp_and_difficulty_are_applied_to_private_actor_rows(self):
        ram,d=DependencyTests().prepared();d['fighters'][1].update(hp=80000,difficulty=4)
        plan=story.build_memory(ram,d);blocks={b['address']:bytes.fromhex(b['data_hex']) for b in plan['blocks']}
        actor=struct.unpack_from('<I',ram,story.core.POINTERS+4)[0]
        self.assertEqual(blocks[actor+0x9E4],struct.pack('<2I',80000,80000))
        self.assertGreater(len(blocks[story.CPU_INIT]),len(story.cpu_init([])))

    def test_portable_document_checks_both_outcomes_and_bad_camera_paths(self):
        for mode in ('hold_at_1_hp','fail'):doc.validate(document(mode))
        d=document();d['finish_rules'][0]['otherwise']='ignore'
        with self.assertRaises(ValueError):doc.validate(d)
        d=doc.default_mission();d['events']=[dict(id='shot',when=dict(type='time',seconds=0),actions=[dict(type='cinematic',fighter='hero',animation=dict(character=1,clip=413),voice=dict(character=0,line=77))])]
        checked=doc.validate(d);self.assertEqual(checked['events'][0]['actions'][0]['voice']['character'],0)
        d['events'][0]['actions'][0]['camera']=dict(eye=[0,0,10],target=[0,0,0],end_eye=[0,0,-10])
        with self.assertRaisesRegex(ValueError,'look-at'):doc.validate(d)


if __name__=='__main__':unittest.main()
