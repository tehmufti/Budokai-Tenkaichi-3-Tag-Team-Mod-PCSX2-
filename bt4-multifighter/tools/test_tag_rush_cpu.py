"""Execute CPU tag admission/output and the real native ultimate selector."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
import tag_rush_cpu as cpu_tags
import tag_team_rush as tag
from test_tag_team_rush_guest import machine as base_machine,run,frame,meter,ACTORS,MANAGER,PARAMS
from prototype import ROOT,Assembler,elf_reader
from native_map import elf_path
from test_tag_team_rush_guest import GuestCpu


class Cpu(GuestCpu):
    def extra_instruction(self,ins,pc):
        if ins>>26==0 and ins&63==0x38:  # Native 1BFC90's DSLL.
            self.r[(ins>>11)&31]=(self.r[(ins>>16)&31]<<((ins>>6)&31))&0xFFFFFFFFFFFFFFFF
            return None
        if ins>>26==33:
            rs,rt=(ins>>21)&31,(ins>>16)&31
            immediate=ins&65535
            if immediate&32768:immediate-=65536
            self.r[rt]=struct.unpack('<h',self.read((self.r[rs]+immediate)&0xFFFFFFFF,2))[0]&0xFFFFFFFFFFFFFFFF
            return None
        return super().extra_instruction(ins,pc)


def machine(cpu=(0,2),count=4):
    c=base_machine(cpu=cpu,count=count)
    c.__class__=Cpu
    for p,b in cpu_tags.pieces():c.write(p,b)
    c.output=[];c.power=0;c.power_calls=[]
    def output(m):
        m.output.append((m.r[4],m.r[5],m.number(12),m.number(13)));m.r[2]=ACTORS[m.r[4]]
    def power(m):m.power_calls.append(m.r[4]);m.r[2]=m.power
    c.callbacks[tag.A(0x208198)]=output;c.callbacks[tag.A(0x20B7C0)]=power
    c.callbacks[tag.A(0x1B8608)]=lambda m:m.r.__setitem__(2,1)
    c.ai_base=0x3200000;c.w(c.r[28]-0x5760,c.ai_base)
    for logical in (0,1):
        context=c.ai_base+0x10+logical*0x520
        c.w(context,logical);c.w(context+44,1);c.w(context+60,63)
    return c


def emit(c,logical=0,word=cpu_tags.ULTIMATE):
    c.r[2]=c.ai_base+0x10+logical*0x520
    c.r[4]=logical;c.r[5]=word;c.set_number(12,.25);c.set_number(13,-.5)
    run(c,cpu_tags.OUTPUT);return c.output[-1][1]


def ready(c,logical=0):c.r[4]=logical;run(c,cpu_tags.READY);return c.r[2]


def decision(c,logical=0):
    context=c.ai_base+0x10+logical*0x520;c.w(context,logical);c.w(context+752,2);c.r[4]=context;c.r[5]=1
    run(c,cpu_tags.DECIDE)


class CpuTagTests(unittest.TestCase):
    def test_approved_cpu_decision_can_follow_launched_target_without_human_cancel_bypass(self):
        for action in (213,214,223):
            c=machine();c.w(ACTORS[0]+2376,62);c.w(ACTORS[1]+2376,action)
            self.assertEqual(ready(c),1);frame(c);self.assertEqual(c.calls,[])
            decision(c);emit(c,word=0);frame(c);self.assertEqual(c.calls,[(0,2,1)])
        c=machine();c.w(ACTORS[0]+2376,62)
        c.w(meter(0,'inviter'),0);c.w(meter(0,'target'),1);c.w(meter(0,'expiry'),100)
        frame(c);self.assertEqual(c.calls,[],'a bare CPU flag or stale offer is not native decision approval')

    def test_full_meter_waits_for_native_decision_then_cpu_accepts(self):
        c=machine()
        for _ in range(20):frame(c)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        for word in (0,0x200,0x204,0x214,0x24):self.assertEqual(emit(c,word=word),word)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        decision(c)
        self.assertEqual(emit(c),0x200);self.assertEqual(c.u(meter(0,'inviter')),0)
        self.assertEqual(c.output[-1][2:],(.25,-.5))
        frame(c);self.assertEqual(c.calls,[(0,2,1)])
        self.assertEqual((c.u(meter(0)),c.u(meter(2))),(0,0))
        self.assertEqual(c.power_calls,[])

    def test_human_consent_timeout_no_spend_and_held_decision_debounce(self):
        c=machine(cpu=(0,));decision(c);emit(c)
        for _ in range(4):frame(c)
        self.assertEqual(c.calls,[]);self.assertEqual(c.u(meter(0)),30)
        frame(c,held=(2,));self.assertEqual(c.calls,[(0,2,1)])
        c=machine(cpu=(0,));decision(c);emit(c)
        for _ in range(tag.REQUEST_SECONDS*tag.ACTOR_HZ+2):
            frame(c)
            self.assertEqual(emit(c,word=0x220),0x200)
            self.assertEqual(emit(c),0x200)
        self.assertEqual(c.calls,[]);self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        self.assertEqual((c.u(meter(0)),c.u(meter(2))),(30,30))
        self.assertEqual(emit(c),0x200)
        c.w(c.ai_base+0x10+60,2);emit(c,word=0)
        c.w(c.ai_base+0x10+60,63);self.assertEqual(emit(c),cpu_tags.ULTIMATE)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF,'a button pulse is not a new native decision')
        emit(c,word=0);decision(c);emit(c);self.assertEqual(c.u(meter(0,'inviter')),0)

    def test_approved_native_action_retries_after_brief_victim_hit_reaction(self):
        c=machine();decision(c)
        c.w(ACTORS[1]+2376,192)
        self.assertEqual(emit(c),0x200)
        self.assertEqual(c.u(meter(0,'cpu_ticket')),2)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        self.assertEqual(emit(c,word=0x220),0x200)
        c.w(ACTORS[1]+2376,11)
        self.assertEqual(emit(c),0x200)
        self.assertEqual(c.u(meter(0,'cpu_ticket')),0)
        self.assertEqual(c.u(meter(0,'inviter')),0)
        frame(c);self.assertEqual(c.calls,[(0,2,1)])

    def test_approved_native_action_offers_without_original_ultimate_buttons(self):
        # Live BT4 Black selected action63 while its original move script
        # produced zero buttons throughout. The native decision itself is
        # sufficient; full meters without that decision are not.
        c=machine();self.assertEqual(emit(c,word=0),0)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        decision(c);self.assertEqual(emit(c,word=0),0)
        self.assertEqual(c.u(meter(0,'inviter')),0)
        self.assertEqual(c.u(meter(0,'cpu_ticket')),0)
        self.assertEqual(c.u(meter(0,'cpu_consumed')),1)
        frame(c);self.assertEqual(c.calls,[(0,2,1)])
        self.assertEqual((c.u(meter(0)),c.u(meter(2))),(0,0))

        # A human partner still must accept. A silent original script cannot
        # keep reopening the invitation after its ordinary timeout.
        c=machine(cpu=(0,));decision(c);emit(c,word=0)
        for _ in range(tag.REQUEST_SECONDS*tag.ACTOR_HZ+2):
            frame(c);self.assertEqual(emit(c,word=0),0)
        self.assertEqual(c.calls,[]);self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        self.assertEqual((c.u(meter(0)),c.u(meter(2))),(30,30))
        self.assertEqual(emit(c),0x200,'later native ultimate pulses stay consumed')

    def test_ticket_waits_for_actual_action63_and_eligible_cast(self):
        c=machine();decision(c);c.w(MANAGER+628,1)
        self.assertEqual(emit(c,word=0),0)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        self.assertEqual(c.u(meter(0,'cpu_ticket')),2)
        c.w(MANAGER+628,0);emit(c,word=0)
        self.assertEqual(c.u(meter(0,'inviter')),0)
        # A cancelled native selection is not a tag offer, even if it later
        # enters action63 without another approved ultimate decision.
        c=machine();decision(c);c.w(c.ai_base+0x10+60,6);emit(c,word=0)
        c.w(c.ai_base+0x10+60,63);emit(c,word=0)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)

    def test_pending_decision_ends_with_native_action_or_invalid_context(self):
        for ended in ('other_action','invalid_depth','wrong_context'):
            with self.subTest(ended=ended):
                c=machine();decision(c);c.w(ACTORS[1]+2376,192);emit(c)
                if ended=='other_action':c.w(c.ai_base+0x10+60,25)
                elif ended=='invalid_depth':c.w(c.ai_base+0x10+44,9)
                else:c.w(c.r[28]-0x5760,c.ai_base+0x1000)
                self.assertEqual(emit(c),cpu_tags.ULTIMATE)
                self.assertEqual(c.u(meter(0,'cpu_ticket')),0)
                self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
                c.w(ACTORS[1]+2376,11);c.w(c.ai_base+0x10+60,63);c.w(c.ai_base+0x10+44,1)
                c.w(c.r[28]-0x5760,c.ai_base)
                self.assertEqual(emit(c),cpu_tags.ULTIMATE)
                self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)

    def test_native_decision_authenticates_both_roles_and_nested_action_stack(self):
        for logical in (0,1):
            for depth in (1,8):
                with self.subTest(logical=logical,depth=depth):
                    c=machine(cpu=(logical,logical+2));context=c.ai_base+0x10+logical*0x520
                    c.w(context+44,depth);c.w(context+52+8*depth,63)
                    decision(c,logical);self.assertEqual(emit(c,logical),0x200)
                    self.assertEqual(c.u(meter(logical,'inviter')),logical)
                    frame(c);self.assertEqual(c.calls,[(logical,logical+2,logical^1)])

    def test_alias_uses_actual_extra_cpu_without_modifying_alias(self):
        c=machine(cpu=(2,4),count=6)
        c.w(tag.core.PAIR,1);c.w(tag.core.PAIR+4,1)
        for off,value in ((8,ACTORS[2]),(12,ACTORS[1]),(16,2),(20,1)):c.w(tag.core.PAIR+off,value)
        c.w(ACTORS[2],0);old=c.read(tag.core.PAIR,24)
        self.assertEqual(ready(c),1);decision(c);emit(c)
        self.assertEqual(c.u(meter(2,'inviter')),2);self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        self.assertEqual(c.read(tag.core.PAIR,24),old);self.assertEqual(c.u(ACTORS[2]),0)
        c.w(ACTORS[2],2);c.w(tag.core.PAIR+4,0);frame(c)
        self.assertEqual(c.calls,[(2,4,1)])

    def test_ineligible_cast_preserves_original_ultimate(self):
        changes=[(meter(0),29),(meter(2),29),(tag.core.TABLE+8,3),
                 (ACTORS[0]+0x1278,0),(ACTORS[2]+0x9E4,0),
                 (tag.CONTROL+tag.C['ready'],0),(tag.CONTROL+tag.C['manager'],MANAGER+4),
                 (tag.CONTROL+tag.C['count'],12),(tag.modes.CONTROL+12,tag.modes.FFA),
                 (tag.A(0x333700),1)]
        for p,v in changes:
            with self.subTest(address=hex(p),value=v):
                c=machine();c.w(p,v);self.assertEqual(ready(c),0);self.assertEqual(emit(c),cpu_tags.ULTIMATE)
                self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)

    def test_online_guard_even_if_tag_control_accidentally_present(self):
        c=machine();c.w(cpu_tags.NETPLAY_CONTROL,cpu_tags.NETPLAY_MAGIC);c.w(cpu_tags.NETPLAY_CONTROL+4,1)
        self.assertEqual(ready(c),0);self.assertEqual(emit(c),cpu_tags.ULTIMATE)

    def test_any_giant_role_is_rejected_but_unrelated_giant_does_not_block(self):
        for i in (0,1,2):
            c=machine();c.write(PARAMS[i]+2,bytes([4]))
            self.assertEqual(ready(c),0);self.assertEqual(emit(c),cpu_tags.ULTIMATE)
        c=machine(count=6);c.write(PARAMS[4]+2,bytes([4]));self.assertEqual(ready(c),1)

    def test_probability_modifier_only_for_selected_ultimate(self):
        for selected,expected in ((0,0),(1,0),(2,1)):
            c=machine();c.r[20]=0x3200000;c.w(c.r[20]+752,selected);c.r[4]=0
            run(c,cpu_tags.PROBABILITY);self.assertEqual(c.r[2],expected)
            self.assertEqual(c.power_calls,[] if selected==2 else [0])

    def test_manager_pause_holds_consumption_but_never_admits_an_offer(self):
        c=machine(cpu=(0,));decision(c);emit(c);c.w(MANAGER+628,1)
        self.assertEqual(ready(c),0)
        for word in (0x220,0x224)*3:self.assertEqual(emit(c,word=word),0x200)
        self.assertEqual(c.u(meter(0,'inviter')),0)
        # Only a receipt for this exact captured world can mask input.
        c.w(tag.CONTROL+tag.C['manager'],MANAGER+4)
        self.assertEqual(emit(c),cpu_tags.ULTIMATE)
        c=machine(cpu=(0,));c.w(MANAGER+628,1);decision(c)
        self.assertEqual(emit(c),cpu_tags.ULTIMATE)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)

    def test_every_hook_matches_the_selected_executable(self):
        native=elf_reader(elf_path(ROOT))[2]
        for address,original,_ in cpu_tags.hooks():
            self.assertEqual(native(address,len(original)),original,hex(address))

    def test_new_decision_ticket_cannot_transfer_to_another_target_or_to_human(self):
        c=machine();decision(c);c.w(tag.core.TABLE,3);c.w(tag.core.TABLE+8,3)
        self.assertEqual(ready(c),1);self.assertEqual(emit(c),cpu_tags.ULTIMATE)
        self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF);self.assertEqual(c.u(meter(0,'cpu_ticket')),0)
        c=machine();decision(c);c.w(ACTORS[0]+0x1278,0)
        self.assertEqual(emit(c),cpu_tags.ULTIMATE);self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)

    def test_no_sparking_override_when_tag_cast_cannot_join(self):
        for field in ('charge','inviter'):
            c=machine();c.w(meter(0,field),0)
            c.r[4]=0;run(c,cpu_tags.POWER);self.assertEqual(c.r[2],0);self.assertEqual(c.power_calls,[0])
            c.power=1;c.r[4]=0;run(c,cpu_tags.POWER);self.assertEqual(c.r[2],1)

    def test_real_native_state_selection_exposes_ultimate_states_only_when_ready(self):
        native=elf_reader(elf_path(ROOT))[2]
        for full in (False,True):
            for distance,ordinary,ultimate in ((0x10,0x80,0x400),(0x20,0x100,0x800),(0x40,0x200,0x1000)):
                with self.subTest(full=full,distance=distance):
                    c=machine();context,manager,root,actions=0x3200000,0x3300000,0x3301000,0x3302000
                    c.write(tag.A(0x1BFC90),native(tag.A(0x1BFC90),0x2E0))
                    for p,_,b in cpu_tags.hooks():c.write(p,b)
                    c.w(c.r[28]-0x5760,manager);c.w(manager,root);c.w(root+164,actions)
                    c.w(context,0);c.w(context+704,distance)
                    for p in (0x208330,0x2099C0,0x207D10,0x1BFBC0):
                        c.callbacks[tag.A(p)]=lambda m:m.r.__setitem__(2,0)
                    if not full:c.w(meter(0),29)
                    c.r[4]=context;run(c,tag.A(0x1BFC90))
                    expected=0x4000|distance|ordinary
                    if full:expected|=0x8000|ultimate
                    self.assertEqual(c.u(context+704),expected)
                    self.assertEqual(c.power,0,'the actor never receives real Sparking')
                    self.assertEqual(c.power_calls,[] if full else [0])

    def test_real_native_action63_pulses_are_consumed_for_the_whole_decision(self):
        native=elf_reader(elf_path(ROOT))[2]
        # Native AI asset action63: held Charge+Down (0x220), pulsed Ki (4).
        # Run the actual output builder and action tick, including 1BCD70's
        # per-button parity toggle; only the action-record dispatcher is a stub.
        action63=bytes.fromhex('1100000000001700200200000400000000000000')
        for offered in (False,True):
            with self.subTest(offered=offered):
                c=machine(cpu=(0,));context,dispatch,record=0x3200000,0x3201000,0x3202000
                c.ai_base=context-0x10;c.w(c.r[28]-0x5760,c.ai_base)
                for p,size in ((0x1B6BA0,0x138),(0x1B6CD8,0x28),(0x1BC918,0x4A0)):
                    c.write(tag.A(p),native(tag.A(p),size))
                for p,_,b in cpu_tags.hooks():c.write(p,b)
                c.w(context,0);c.w(context+44,1);c.w(context+60,63)
                c.w(tag.A(0x2C46B8),dispatch);c.write(record,action63)
                a=Assembler(dispatch);a.li(8,record)
                a.lw(5,8,8);a.lw(6,8,12);a.lw(7,8,16);a.li(8,0)
                a.emit(0x44800000|(12<<11));a.emit(0x44800000|(13<<11))
                a.jump(tag.A(0x1BCB78));c.write(dispatch,a.finish())
                c.power=1  # A real ultimate would be available if a pulse leaked.
                if offered:decision(c)
                raw=[];published=[]
                for _ in range(8):
                    c.r[4]=context;run(c,tag.A(0x1B6BA0));raw.append(c.u(context+616))
                    c.r[4]=context;run(c,tag.A(0x1B6CD8));published.append(c.output[-1][1])
                    self.assertEqual(c.u(context+616),raw[-1])
                self.assertEqual(raw,[0x224,0x220]*4)
                self.assertEqual(published,[0x200]*8 if offered else raw)
                self.assertEqual(c.u(meter(0,'inviter')),0 if offered else 0xFFFFFFFF)
                self.assertEqual(c.calls,[],'the human teammate still has to accept')

    def test_real_native_action63_waits_for_action62_but_ticket_can_offer(self):
        native=elf_reader(elf_path(ROOT))[2]
        c=machine(cpu=(0,));context=c.ai_base+0x10
        root,actions=0x3301000,0x3302000
        c.w(c.ai_base,root);c.w(root+164,actions)
        # The actual common AI asset gives ultimate action63 flags 0xB.
        # Native fighter action62 has category14, so dispatcher 1B44A8
        # waits for that ordinary action to finish and emits no buttons.
        c.write(actions+648+2*63,struct.pack('<H',0xB))
        c.write(actions+904+62,bytes([14]))
        c.w(ACTORS[0]+2376,62)
        for p,size in ((0x1B4140,0xE0),(0x1B44A8,0x5A8),
                       (0x1B6BA0,0x138),(0x1B6CD8,0x28),(0x1BC918,0x4A0)):
            c.write(tag.A(p),native(tag.A(p),size))
        c.w(tag.A(0x2C46B8),tag.A(0x1B44A8))
        for p,_,b in cpu_tags.hooks():c.write(p,b)
        c.callbacks[tag.A(0x207D10)]=lambda m:m.r.__setitem__(2,62)
        c.callbacks[tag.A(0x2095E8)]=lambda m:m.r.__setitem__(2,1)
        c.callbacks[tag.A(0x206D68)]=lambda m:m.r.__setitem__(2,0)
        for approved in (False,True):
            if approved:decision(c)
            c.w(context+616,0x224)
            c.r[4]=context;run(c,tag.A(0x1B6BA0))
            self.assertEqual(c.u(context+616),0,'the real dispatcher clears the input and waits')
            self.assertEqual(c.u(context+48),0,'the ultimate record has not started')
            self.assertEqual(c.u(context+60),63,'the native ultimate decision remains current')
            c.r[4]=context;run(c,tag.A(0x1B6CD8))
            self.assertEqual(c.output[-1][1],0)
            self.assertEqual(c.u(meter(0,'inviter')),0 if approved else 0xFFFFFFFF)
        self.assertEqual(c.u(meter(0,'cpu_ticket')),0)
        self.assertEqual(c.u(meter(0,'cpu_consumed')),1)
        self.assertEqual(c.calls,[],'the human teammate still has to accept')

    def test_real_native_selector_uses_ultimate_roll_without_sparking_or_ki(self):
        native=elf_reader(elf_path(ROOT))[2]
        for allowed in (False,True):
            c=machine();context,params,enemy=0x3200000,0x3300000,0x3301000
            c.write(tag.A(0x1B8B40),native(tag.A(0x1B8B40),0x4B8))
            for p,_,b in cpu_tags.hooks():c.write(p,b)
            c.w(context,0);c.w(context+756,101);c.w(tag.A(0x2EDA70)+4*101,101)
            for i in range(3):c.w(params+412+i*4,100000)
            c.callbacks[tag.A(0x208B58)]=lambda m:m.r.__setitem__(2,params if m.r[4]==0 else enemy)
            for p,result in ((0x20B4E0,0),(0x208C30,10000),(0x2097C0,-1),(0x209E78,0)):
                c.callbacks[tag.A(p)]=lambda m,result=result:m.r.__setitem__(2,result&0xFFFFFFFF)
            decisions=[]
            def decide(m):decisions.append((m.r[4],m.r[5]));m.r[2]=int(allowed)
            c.callbacks[tag.A(0x1B8608)]=decide
            c.r[4]=context;run(c,tag.A(0x1B8B40))
            self.assertEqual(decisions,[(context,1)])
            self.assertEqual(c.r[2],int(allowed));self.assertEqual(c.u(context+752),2 if allowed else 0xFFFFFFFF)
            self.assertEqual(c.power,0);self.assertEqual(c.u(params+420),100000)


if __name__=='__main__':unittest.main()
