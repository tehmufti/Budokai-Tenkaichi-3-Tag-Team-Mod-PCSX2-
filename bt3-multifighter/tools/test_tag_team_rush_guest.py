"""Run the actual emitted per-fighter consent/meter/pad coordinator."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
import tag_team_rush as tag
from test_fusion_partner_lifecycle import FusionCpu

MANAGER,BATTLE=0x1900000,0x1910000
ACTORS=[0x2200000+0x2000*i for i in range(10)]
MODELS=[0x2700000+0x2000*i for i in range(10)]
PARAMS=[0x2800000+0x100*i for i in range(10)]
PADS=[0x2500000+0x200*i for i in range(10)]
LIMIT=30


def meter(index,field='charge'):
    return tag.METERS+index*tag.METER_STRIDE+tag.T[field]


class GuestCpu(FusionCpu):
    def extra_instruction(self,ins,pc):
        if ins>>26==0 and ins&63==6:
            self.r[(ins>>11)&31]=(self.r[(ins>>16)&31]&0xFFFFFFFF)>>(self.r[(ins>>21)&31]&31);return
        return super().extra_instruction(ins,pc)


def machine(count=6,full=True,cpu=()):
    import tag_rush_safety as safety
    c=GuestCpu();c.calls=[];c.pad_reads=[]
    for p,b in ((tag.GATE,tag.gate_code()),(tag.ELIGIBLE,tag.eligible_code()),
                (tag.VICTIM_ELIGIBLE,tag.eligible_code(tag.VICTIM_ELIGIBLE,victim=True)),
                (tag.BUFFER_TARGET,tag.eligible_code(tag.BUFFER_TARGET,victim=True,buffered=True)),
                (tag.BUFFER_INPUT,tag.buffer_input_code()),(tag.INPUT_GATE,tag.gate_code(tag.INPUT_GATE,allow_manager_pause=True)),
                (tag.INPUT,tag.input_code()),(tag.TICK,tag.tick_code()),(tag.FRAME,tag.frame_code(0x110000))):c.write(p,b)
    c.write(safety.PREFLIGHT,safety.preflight_code());c.write(safety.VICTIM_PREFLIGHT,safety.victim_preflight_code())
    c.w(c.r[28]-22364,MANAGER);c.w(MANAGER,2)
    c.write(tag.core.MODE,struct.pack('<4I',1,count,MANAGER,count))
    settings=dict(tag_team_rush_enabled=True,tag_team_rush_shared_camera=False,
                  tag_team_rush_charge_seconds=1,tag_team_rush_damage=15000,tag_team_rush_training_full=False)
    c.write(tag.CONTROL,tag.control_bytes(MANAGER,count,settings,ready=True));c.w(tag.CONTROL+tag.C['charge_ticks'],LIMIT)
    c.w(tag.CONTROL+0x3A0,0x3100000);c.w(tag.CONTROL+0x3A4,256);c.write(0x3100000,bytes([3])*256)
    c.w(tag.A(0x2FEB38),BATTLE);c.w(BATTLE,3);c.w(tag.A(0x3337C0),1)
    c.w(tag.participation.CONTROL+12,(1<<count)-1);c.w(tag.participation.CONTROL+16,0)
    for i in range(count):
        actor=ACTORS[i];c.w(tag.core.POINTERS+4*i,actor);c.w(actor,i)
        c.w(tag.core.MODELS+4*i,MODELS[i]);c.w(MODELS[i]+4,1);c.w(MODELS[i]+8,1)
        c.w(MODELS[i]+16,i);c.w(MODELS[i]+2332,PARAMS[i])
        c.w(actor+12,i);c.w(actor+2376,11);c.w(actor+0x9E4,30000);c.w(actor+0x1278,int(i in cpu))
        for off in tag.actors.ACTION_FIELDS[1:]:c.w(actor+off,0xFFFFFFFF)
        c.w(tag.core.TABLE+4*i,1 if i%2==0 else 0)
        c.w(meter(i),LIMIT if full else 0);c.w(meter(i,'allies'),(count+1-i%2)//2)
    def pad(m):
        index=m.u(m.r[4]);m.pad_reads.append(index);m.r[2]=PADS[index]
    def start(m):
        first,partner,victim=m.r[4:7];m.calls.append((first,partner,victim))
        # This coordinator-only fixture admits contact immediately; the real
        # approach tests cover delayed partner cost and missed attempts.
        m.w(meter(first),0);m.w(meter(partner),0)
        m.w(tag.CONTROL+tag.C['active'],1)
        m.w(tag.CONTROL+tag.C['members'],(1<<first)|(1<<partner)|(1<<victim))
        for i in range(count):m.w(meter(i,'inviter'),-1);m.w(meter(i,'expiry'),0)
        m.r[2]=1
    import tag_rush_approach
    c.callbacks[tag.A(0x1DC2A0)]=pad;c.callbacks[tag_rush_approach.BEGIN]=start
    import tag_rush_pause
    c.callbacks[tag_rush_pause.CHECK]=lambda m:m.r.__setitem__(2,0 if m.u(tag.A(0x333700)) else 1)
    c.callbacks[tag.STEP]=lambda m:None;c.callbacks[0x110000]=lambda m:None
    return c


def run(c,entry):
    c.r[31]=0xFEED0000;c.run(entry)


def frame(c,held=(),extra=None):
    held=set(held)
    for i,pad in enumerate(PADS):
        value=tag.CHORD if i in held else 0
        if extra is not None:value=extra.get(i,value)
        for off in tag.PRESS_WORDS:c.w(pad+off,value)
    run(c,tag.FRAME)


def analog_frame(c,entries):
    """Execute the real poller's directional alias section on normalized axes.

    122C40..122D08 selects a dominant direction for each stick with the native
    +/-.5 threshold. This tests the actual game format, not a duplicated
    Python comparison that could agree with an incorrect input handler.
    """
    from prototype import ROOT,elf_reader
    from native_map import elf_path
    native=elf_reader(elf_path(ROOT))[2]
    c.write(0x122C40,native(0x122C40,0xC8))
    for i,pad in enumerate(PADS):
        buttons,x,y,rx,ry=entries.get(i,(0,0.,0.,0.,0.))
        c.write(pad+304,struct.pack('<4f',x,y,rx,ry))
        c.r[16]=buttons;c.r[17]=pad
        c.set_number(3,x);c.set_number(2,y);c.set_number(21,-.5);c.set_number(22,.5)
        c.run(0x122C40,stops=(0x122D08,))
        for off in tag.PRESS_WORDS:c.w(pad+off,c.r[16])
    run(c,tag.FRAME)


class GuestCoordinatorTests(unittest.TestCase):
    def test_smash_chord_survives_hitstop_then_native_recovery_exactly_once(self):
        c=machine(cpu=(2,));c.w(ACTORS[0]+2376,71);c.w(ACTORS[1]+2376,213)
        c.w(MANAGER+628,3);frame(c,[0])
        ttl=tag.INPUT_BUFFERS+16
        self.assertEqual(c.u(ttl)&255,tag.SMASH_BUFFER_TICKS);self.assertEqual(c.calls,[])
        for _ in range(20):frame(c)
        self.assertEqual(c.u(ttl)&255,tag.SMASH_BUFFER_TICKS)
        c.w(MANAGER+628,0);frame(c);self.assertEqual(c.calls,[])
        c.w(ACTORS[0]+2376,11);c.w(ACTORS[0]+2380,11);frame(c)
        self.assertEqual(c.calls,[])
        c.w(ACTORS[0]+2380,-1);frame(c);frame(c)
        self.assertEqual(c.calls,[(0,2,1)]);self.assertEqual(c.u(ttl),0)
        for _ in range(12):frame(c,[0])
        self.assertEqual(c.calls,[(0,2,1)])

    def test_live_smash_followthrough_keeps_one_chord_for_twenty_five_updates(self):
        for action in range(71,77):
            with self.subTest(action=action):
                c=machine(cpu=(2,));c.w(ACTORS[0]+2376,action);c.w(ACTORS[1]+2376,213)
                frame(c,[0])
                for _ in range(25):frame(c)
                self.assertEqual(c.calls,[])
                self.assertEqual(c.u(tag.INPUT_BUFFERS+16)&255,tag.SMASH_BUFFER_TICKS-26)
                c.w(ACTORS[0]+2376,11);frame(c);frame(c)
                self.assertEqual(c.calls,[(0,2,1)])
        c=machine(cpu=(2,));c.w(ACTORS[0]+2376,60);c.w(ACTORS[1]+2376,213)
        frame(c,[0])
        for _ in range(tag.INPUT_BUFFER_TICKS):frame(c)
        c.w(ACTORS[0]+2376,11);frame(c);frame(c)
        self.assertEqual(c.calls,[],"Unrelated actions do not gain the longer smash wait")

    def test_waiting_chord_authenticates_victim_and_discards_cinematic_or_reload(self):
        for smash in (False,True):
            for change in ('actor','model','character','cinematic','reload','cinematic_flag','landed'):
                with self.subTest(smash=smash,change=change):
                    c=machine(cpu=(2,));c.w(ACTORS[0]+2376,71 if smash else 60)
                    c.w(ACTORS[1]+2376,213 if smash else 11);frame(c,[0])
                    addr=ACTORS[1]+2376;value=285
                    if change=='actor':
                        addr=tag.core.POINTERS+4;value=0x2B00000;c.write(value,c.read(ACTORS[1],0x1600))
                    elif change=='model':
                        addr=tag.core.MODELS+4;value=0x2B02000;c.write(value,c.read(MODELS[1],0x1700))
                    elif change=='character':addr=MODELS[1]+12;value=42
                    elif change=='reload':addr=ACTORS[1]+3500;value=1
                    elif change=='cinematic_flag':
                        import tag_rush_safety as safety
                        flag=safety.FLAG(0x125);addr=ACTORS[1]+0x1085+(flag>>3);value=1<<(flag&7)
                    elif change=='landed':
                        if not smash:continue
                        value=11
                    old=c.u(addr);c.w(addr,value);frame(c);c.w(addr,old)
                    self.assertEqual(c.u(tag.INPUT_BUFFERS+16),0)
                    c.w(ACTORS[0]+2376,11);frame(c);frame(c)
                    self.assertEqual(c.calls,[],"Restoring an old victim cannot resurrect consumed intent")

    def test_buffer_expires_and_cannot_survive_changed_identity_target_or_menu(self):
        for change in ('expiry','long_hitstop','model','character','actor','target','death','giant','pause','cinematic','cinematic_flag'):
            with self.subTest(change=change):
                c=machine(cpu=(2,));c.w(ACTORS[0]+2376,71);c.w(ACTORS[1]+2376,213);frame(c,[0])
                if change=='expiry':
                    for _ in range(tag.SMASH_BUFFER_TICKS):frame(c)
                elif change=='long_hitstop':
                    c.w(MANAGER+628,1)
                    for _ in range(tag.ACTOR_HZ+1):frame(c)
                    c.w(MANAGER+628,0)
                elif change=='model':
                    c.write(0x3000000,c.read(MODELS[0],0x2000));c.w(tag.core.MODELS,0x3000000)
                elif change=='character':c.w(MODELS[0]+12,99)
                elif change=='actor':
                    c.write(0x3102000,c.read(ACTORS[0],0x1600));c.w(tag.core.POINTERS,0x3102000)
                elif change=='target':c.w(tag.core.TABLE,3)
                elif change=='death':c.w(ACTORS[0]+0x9E4,0)
                elif change=='giant':c.write(PARAMS[0]+2,b'\x04')
                elif change=='pause':c.w(tag.A(0x333700),1)
                elif change=='cinematic':c.w(ACTORS[0]+2376,285)
                elif change=='cinematic_flag':
                    from native_map import FLAG
                    flag=FLAG(0x125);c.write(ACTORS[0]+0x1085+(flag>>3),bytes([1<<(flag&7)]))
                frame(c);self.assertEqual(c.u(tag.INPUT_BUFFERS+16),0)
                c.w(ACTORS[0]+2376,11);c.w(tag.A(0x333700),0)
                frame(c);frame(c);self.assertEqual(c.calls,[])

    def test_native_initiator_windows_and_ordinary_helper_acceptance(self):
        for action,current,previous,allowed in ((11,54,54,True),(13,0,0,True),(14,0,0,True),
                (55,52,52,True),(55,54,52,False),(55,52,54,False),(71,0,0,False),(76,0,0,False),(62,0,0,False)):
            c=machine(cpu=(2,));c.w(ACTORS[0]+2376,action);c.w(ACTORS[0]+2420,current);c.w(ACTORS[0]+2424,previous)
            c.w(ACTORS[1]+2376,214);frame(c,[0]);frame(c)
            self.assertEqual(bool(c.calls),allowed,(action,current,previous))
        c=machine();c.w(ACTORS[1]+2376,223);frame(c,[0]);c.w(ACTORS[2]+2376,71)
        frame(c,[2]);self.assertEqual(c.calls,[(0,2,1)])

    def test_launched_victim_does_not_make_launched_attackers_eligible(self):
        for action in (213,214,223):
            for index in (0,2,1):
                c=machine(cpu=(2,));c.w(ACTORS[index]+2376,action);frame(c,[0]);frame(c)
                self.assertEqual(bool(c.calls),index==1,(action,index))

    def test_native_analog_left_uses_half_tilt_dominance_and_not_right_stick(self):
        for x,y,rx,ry,accepted in ((-.5001,0.,0.,0.,True),(-1.,0.,0.,0.,True),
                (-.5,0.,0.,0.,False),(-.49,0.,0.,0.,False),(0.,0.,0.,0.,False),
                (.8,0.,0.,0.,False),(0.,-.8,0.,0.,False),(-.6,.8,0.,0.,False),
                (-.6,.6,0.,0.,False),(-.8,.5,0.,0.,True),(0.,0.,-1.,0.,False)):
            with self.subTest(axes=(x,y,rx,ry)):
                c=machine();analog_frame(c,{0:(tag.CHORD_BUTTONS,x,y,rx,ry)})
                self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),int(accepted))
                self.assertEqual(c.u(meter(0,'inviter')),0 if accepted else 0xFFFFFFFF)
                self.assertEqual(struct.unpack('<4f',c.read(PADS[0]+304,16)),
                                 struct.unpack('<4f',struct.pack('<4f',0. if accepted else x,
                                     0. if accepted else y,rx,ry)))

    def test_both_players_can_request_and_accept_with_either_left_input(self):
        for requester_stick,partner_stick in ((True,True),(True,False),(False,True)):
            c=machine()
            first=(tag.CHORD_BUTTONS,-1.,0.,0.,0.) if requester_stick else (tag.CHORD,0.,0.,0.,0.)
            second=(tag.CHORD_BUTTONS,-1.,0.,0.,0.) if partner_stick else (tag.CHORD,0.,0.,0.,0.)
            analog_frame(c,{0:first});analog_frame(c,{2:second})
            self.assertEqual(c.calls,[(0,2,1)])
            self.assertEqual((c.u(meter(0)),c.u(meter(2))),(0,0))

    def test_analog_consumption_debounces_across_stick_and_dpad_and_preserves_other_input(self):
        c=machine();analog_frame(c,{0:(tag.CHORD_BUTTONS|0x8800,-.8,.2,.4,-.7)})
        for off in tag.PRESS_WORDS:self.assertEqual(c.u(PADS[0]+off),0x800000|0x8900)
        self.assertEqual(struct.unpack('<4f',c.read(PADS[0]+304,16)),
                         struct.unpack('<4f',struct.pack('<4f',0.,0.,.4,-.7)))
        for buttons,x in ((tag.CHORD_BUTTONS,-1.),(0x100,-1.),(tag.CHORD,0.),(0x1000,1.)):
            analog_frame(c,{0:(buttons,x,0.,0.,0.)})
            self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),0)
            self.assertEqual(c.u(PADS[0]+328)&tag.CONSUME_INPUT,0)
            if x==1.:self.assertEqual(c.fr(PADS[0]+304),1.)
        analog_frame(c,{0:(0x100,0.,0.,0.,0.)})
        analog_frame(c,{0:(tag.CHORD_BUTTONS,-1.,0.,0.,0.)})
        self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),1)

    def test_analog_early_press_and_pause_do_not_queue_a_later_tag(self):
        for blocked in ('meter','pause'):
            c=machine(full=blocked!='meter')
            if blocked=='pause':c.w(tag.A(0x333700),1)
            analog_frame(c,{0:(tag.CHORD_BUTTONS,-1.,0.,0.,0.)})
            self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),0)
            if blocked=='meter':self.assertEqual(c.fr(PADS[0]+304),0.)
            c.w(meter(0),LIMIT);c.w(tag.A(0x333700),0)
            analog_frame(c,{0:(tag.CHORD_BUTTONS,-1.,0.,0.,0.)})
            self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),0)
            analog_frame(c,{})
            analog_frame(c,{0:(tag.CHORD_BUTTONS,-1.,0.,0.,0.)})
            self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),1)

    def test_unadmitted_current_forms_cannot_offer_accept_or_be_targeted(self):
        for index in (0,2,1):
            c=machine();c.w(MODELS[index]+12,250);c.write(0x3100000+250,b'\0')
            frame(c,[0]);frame(c,[2]);self.assertEqual(c.calls,[])
            self.assertEqual([c.u(meter(i))for i in range(6)],[LIMIT]*6)
        for address,value in ((tag.CONTROL+0x3A0,0),(tag.CONTROL+0x3A0,0x7FFFFFF),
                              (tag.CONTROL+0x3A4,0),(tag.CONTROL+0x3A4,4097)):
            c=machine();c.w(address,value);frame(c,[0]);frame(c,[2])
            self.assertEqual(c.calls,[])

    def test_giant_in_any_role_or_after_invitation_never_starts_or_spends(self):
        import giant_options as giants
        for index in (0,2,1):
            for enlarged in (0,1):
                for after_offer in (False,True):
                    with self.subTest(index=index,enlarged=enlarged,after_offer=after_offer):
                        c=machine();c.write(giants.CONTROL,struct.pack('<4If',giants.MAGIC,MANAGER,6,enlarged,3.0))
                        if after_offer:frame(c,[0])
                        c.write(PARAMS[index]+2,b'\x04')
                        if not after_offer:frame(c,[0])
                        frame(c,[2]);self.assertEqual(c.calls,[])
                        self.assertEqual([c.u(meter(i)) for i in range(6)],[LIMIT]*6)
                        self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)

    def test_normal_size_classes_ignore_enlargement_and_visual_scale(self):
        import giant_options as giants
        for size_class in (0,1,2,3,5):
            c=machine();c.write(giants.CONTROL,struct.pack('<4If',giants.MAGIC,MANAGER,6,1,3.0))
            for index in (0,2,1):
                c.write(PARAMS[index]+2,bytes([size_class]));c.w(MODELS[index]+2592,0x40400000)
            frame(c,[0]);frame(c,[2]);self.assertEqual(c.calls,[(0,2,1)])

    def test_giants_do_not_charge_or_count_as_the_only_available_teammate(self):
        c=machine(count=4,full=False);c.write(PARAMS[2]+2,b'\x04')
        for _ in range(3):frame(c)
        self.assertEqual([c.u(meter(i)) for i in range(4)],[0,3,0,3])
        c=machine(full=False);c.write(PARAMS[0]+2,b'\x04')
        frame(c);self.assertEqual([c.u(meter(i)) for i in (0,2,4)],[0,1,1])

    def test_uninvolved_giants_do_not_disable_three_normal_participants(self):
        c=machine()
        for index in (3,4,5):c.write(PARAMS[index]+2,b'\x04')
        frame(c,[0]);frame(c,[2]);self.assertEqual(c.calls,[(0,2,1)])
        self.assertEqual([c.u(meter(i)) for i in range(6)],[0,LIMIT,0,LIMIT,LIMIT,LIMIT])

    def test_slow_effect_retirement_continues_after_controls_released_and_gate_closed(self):
        import tag_rush_effects as effects
        c=machine(full=False);c.w(tag.CONTROL+tag.C['ready'],0);c.w(BATTLE,4)
        c.w(tag.FX_CLEANUP,1);c.w(effects.CONTROL,effects.MAGIC)
        calls=[]
        def stop(m):calls.append(True);m.r[2]=1 if len(calls)<3 else 0
        c.callbacks[effects.STOP]=stop
        for _ in range(2):
            frame(c);self.assertEqual(c.u(tag.FX_CLEANUP),1)
            self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)
        frame(c);self.assertEqual(c.u(tag.FX_CLEANUP),0)
        frame(c);self.assertEqual(len(calls),3)
        self.assertEqual(c.calls,[]);self.assertEqual([c.u(meter(i)) for i in range(6)],[0]*6)

    def test_active_scene_cleans_up_when_battle_ends_but_not_while_paused(self):
        for exit_kind in ('phase','manager','disabled','pause'):
            with self.subTest(exit_kind=exit_kind):
                c=machine(cpu=(2,));frame(c,[0]);frame(c)
                calls=[]
                c.callbacks[tag.FINISH]=lambda m:calls.append(('finish',m.r[4]))
                c.callbacks[tag.STEP]=lambda m:calls.append(('step',))
                if exit_kind=='phase':c.w(BATTLE,4)
                elif exit_kind=='manager':c.w(c.r[28]-22364,MANAGER+16)
                elif exit_kind=='disabled':c.w(tag.CONTROL+tag.C['enabled'],0)
                else:c.w(tag.A(0x333700),1)
                frame(c)
                self.assertEqual(calls,[] if exit_kind=='pause' else [('finish',1)])

    def test_each_fighter_charges_and_only_two_spend(self):
        c=machine(full=False)
        for _ in range(LIMIT):frame(c)
        self.assertEqual([c.u(meter(i)) for i in range(6)],[LIMIT]*6)
        frame(c,[0]);frame(c,[2]);self.assertEqual(c.calls,[(0,2,1)])
        self.assertEqual([c.u(meter(i)) for i in range(6)],[0,LIMIT,0,LIMIT,LIMIT,LIMIT])

    def test_dead_and_consumed_do_not_charge_when_two_other_allies_live(self):
        for consumed in (False,True):
            c=machine(full=False)
            if consumed:c.w(tag.participation.CONTROL+16,1)
            else:c.w(ACTORS[0]+0x9E4,0)
            for _ in range(3):frame(c)
            self.assertEqual((c.u(meter(0)),c.u(meter(2)),c.u(meter(4))),(0,3,3))

    def test_same_target_and_full_partner_required_human_or_cpu(self):
        for cpus in ((),(2,)):
            for changed in ('target','charge'):
                c=machine(cpu=cpus)
                if changed=='target':c.w(tag.core.TABLE+8,3)
                else:c.w(meter(2),0)
                frame(c,[0]);frame(c,[2]);self.assertEqual(c.calls,[])
                self.assertEqual(c.u(meter(0)),LIMIT)

    def test_cpu_accepts_one_frame_after_human_invitation(self):
        c=machine(cpu=(2,));frame(c,[0]);self.assertEqual(c.calls,[])
        frame(c);self.assertEqual(c.calls,[(0,2,1)])

    def test_simultaneous_press_does_not_accept_without_a_fresh_edge(self):
        c=machine();frame(c,[0,2])
        for _ in range(3):frame(c,[0,2])
        self.assertEqual(c.calls,[])
        frame(c,[0]);frame(c,[0,2]);self.assertEqual(c.calls,[(0,2,1)])

    def test_consumed_chord_is_masked_until_triangle_and_direction_release(self):
        c=machine();frame(c,[0]);self.assertEqual(c.u(PADS[0]+328),0x100)
        self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),1)
        for partial in (tag.CHORD,0x1000,0x80,0x1080):
            frame(c,extra={0:partial})
            self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),0)
            for off in tag.PRESS_WORDS:self.assertEqual(c.u(PADS[0]+off)&0x1080,0)
        frame(c,extra={0:0x100});frame(c,[0])
        self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),1)
        # An early tag press must not accidentally dispatch a native special.
        c=machine(full=False);frame(c,[0]);self.assertEqual(c.u(PADS[0]+328),0x100)
        self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),0)
        c.w(meter(0),LIMIT);frame(c,[0])
        self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),0)
        frame(c);frame(c,[0]);self.assertEqual(c.u(tag.CONTROL+tag.C['requested']),1)

    def test_refused_director_does_not_spend_either_fighter_meter(self):
        import tag_rush_approach
        c=machine(cpu=(2,));c.callbacks[tag_rush_approach.BEGIN]=lambda m:m.r.__setitem__(2,0)
        frame(c,[0]);frame(c)
        self.assertEqual([c.u(meter(i)) for i in range(6)],[LIMIT]*6)
        self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)

    def test_pause_does_not_charge_or_create_resume_edge_and_ffa_is_inert(self):
        c=machine();c.w(tag.A(0x333700),1);frame(c,[0])
        self.assertEqual(c.calls,[]);self.assertEqual(c.u(tag.CONTROL+tag.C['clock']),0)
        c.w(tag.A(0x333700),0);frame(c,[0]);self.assertEqual(c.u(meter(0,'inviter')),0xFFFFFFFF)
        frame(c);frame(c,[0]);self.assertEqual(c.u(meter(0,'inviter')),0)
        c=machine(full=False);c.w(tag.modes.CONTROL+12,tag.modes.FFA);frame(c,[0,2])
        self.assertEqual([c.u(meter(i)) for i in range(6)],[0]*6);self.assertEqual(c.calls,[])

    def test_active_scene_holds_only_participant_meters_unless_shared(self):
        for shared in (False,True):
            c=machine(full=False);c.w(tag.CONTROL+tag.C['active'],1)
            c.w(tag.CONTROL+tag.C['members'],7);c.w(tag.CONTROL+tag.C['shared'],int(shared))
            steps=[];c.callbacks[tag.STEP]=lambda m:steps.append(True)
            frame(c,[3,4]);self.assertEqual(steps,[True]);self.assertEqual(c.calls,[])
            self.assertEqual([c.u(meter(i)) for i in range(6)],[0]*6 if shared else [0,0,0,1,1,1])

    def test_synthetic_fusion_pad_is_not_consumed(self):
        import coop_controller
        c=machine();c.callbacks[tag.A(0x1DC2A0)]=lambda m:m.r.__setitem__(2,coop_controller.MERGED)
        for off in tag.PRESS_WORDS:c.w(coop_controller.MERGED+off,tag.CHORD)
        frame(c,[0]);self.assertEqual(c.calls,[])
        for off in tag.PRESS_WORDS:self.assertEqual(c.u(coop_controller.MERGED+off),tag.CHORD)

    def test_stale_identity_and_bad_count_never_read_controller_records(self):
        for address,value in ((tag.CONTROL,0),(tag.CONTROL+4,MANAGER+4),
                              (tag.CONTROL+8,0),(tag.CONTROL+8,11),
                              (tag.core.MODE+4,4),(tag.core.MODE+12,4)):
            c=machine();c.w(address,value);frame(c,[0,2])
            self.assertEqual(c.pad_reads,[],hex(address));self.assertEqual(c.calls,[])

    def test_training_fill_is_only_for_training_and_uneven_roster_supported(self):
        # The engine captures four slots for2v1; the unused fourth slot is
        # absent in participation, as in the real uneven-roster preparer.
        c=machine(count=4,full=False);c.w(tag.participation.CONTROL+12,7)
        c.w(tag.CONTROL+tag.C['training_full'],1)
        frame(c);self.assertEqual([c.u(meter(i)) for i in range(3)],[1,0,1])
        c.w(tag.CONTROL+tag.C['training'],1);frame(c)
        self.assertEqual([c.u(meter(i)) for i in range(3)],[LIMIT,0,LIMIT])
        frame(c,[0]);frame(c,[2]);self.assertEqual(c.calls,[(0,2,1)])


if __name__=='__main__':unittest.main()
