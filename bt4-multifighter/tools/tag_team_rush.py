"""Local tag-rush coordinator. All clocks and consent live in guest RAM.

The director is armed only after its complete disc-backed choreography has been
loaded. A missing clip must never replace the requested move with guessed poses,
spend a fighter's charge, or leave any fighter held. Online preparation leaves this mechanic disabled.
"""
import math
import struct
from dataclasses import dataclass

from prototype import Assembler
from native_map import A, ACTOR_HZ
import fresh_team_combat as core
import battle_mode_policy as modes
import team_participation as participation
import team_start_gate as start
import fusion_partner_lifecycle as full
import extra_throws as actors
import guest_killfeed as feed

BASE, END = 0x06D00000, 0x06DC0000
FRAME, GATE, ELIGIBLE, INPUT, TICK = (BASE, BASE+0x400, BASE+0x800, BASE+0x1000, BASE+0x1800)
START, STEP, FINISH = BASE+0x3000, BASE+0x4000, BASE+0x5000
FRAME_NATIVE = BASE+0x2F00
CONTROL = BASE+0x8000
METERS, METER_STRIDE = CONTROL+0x100, 32
MEMBERS_SAVE = CONTROL+0x400
FX_CLEANUP = MEMBERS_SAVE+156  # Director's asynchronous retirement receipt.
MAGIC = 0x54414731
CHORD = 0x1180  # Charge ki (L2) + Triangle + Left, logical PS2 buttons.
CHORD_BUTTONS = 0x1100
ANALOG_LEFT = 0x10000  # Native122A38: dominant left-stick X strictly below -.5.
LEFT_INPUT = 0x80 | ANALOG_LEFT
CONSUME_INPUT = 0x1000 | LEFT_INPUT
REQUEST_SECONDS = 5
CONFIG = 48
# Common ABI also used by the camera and HUD modules. active is exactly 1 only
# while the director owns the three captured actor/model identities.
C = dict(magic=0, manager=4, count=8, enabled=12, active=16, members=20, shared=24,
         initiator=28, partner=32, victim=36, frame=40, variant=44,
         charge_ticks=48, damage=52, training_full=56, ready=60,
         last_held=64, consumed=68, clock=72, requested=76, start_requests=80,
         completed=84, cancelled=88, training=92, scene_table=96, approaching=100)
T = dict(charge=0, inviter=4, target=8, expiry=12, allies=16)
PRESS_WORDS = (328, 336, 340)


@dataclass(frozen=True)
class Fighter:
    """Host-side reference model used to exercise consent independently of MIPS."""
    index: int
    team: int
    target: int
    alive: bool = True
    present: bool = True
    busy: bool = False
    cpu: bool = False
    ki: bool = True
    giant: bool = False


def variant(first_ki, second_ki):
    return 'dual_beam' if first_ki and second_ki else 'dual_melee' if not first_ki and not second_ki else 'mixed'


class Coordinator:
    """Deterministic specification: one meter per fighter, one scene at a time.

    Input edges are sampled even while paused/busy. Resuming must not turn a
    button held through a pause or another cinematic into fresh consent.
    """
    def __init__(self, charge_seconds=25, damage=15000, hz=ACTOR_HZ, training_full=False):
        if not math.isfinite(charge_seconds) or not 1 <= charge_seconds <= 600:
            raise ValueError('Tag charge must take 1..600 seconds')
        if type(damage) is not int or not 0 <= damage <= 100000:
            raise ValueError('Tag damage must be 0..100000')
        if not isinstance(hz, (int, float)) or not 1 <= hz <= 120:
            raise ValueError('Invalid actor clock')
        self.limit = math.ceil(charge_seconds*hz)
        self.ttl = math.ceil(REQUEST_SECONDS*hz)
        self.damage = damage
        self.training_full = training_full
        self.charge = {}
        self.offers = {}
        self.down = set()
        self.clock = 0
        self.active = None

    def tick(self, fighters, held=(), *, paused=False, training=False, enabled=True, ready=True, teams=True):
        roster = {f.index: f for f in fighters}
        held = set(held)
        pressed, self.down = held-self.down, held
        if not enabled or not teams or not ready:
            self.offers.clear()
            return None
        if paused:
            return None
        self.clock += 1
        live = [f for f in fighters if f.alive and f.present and not f.giant]
        def eligible(f):
            t = roster.get(f.target)
            return (f.alive and f.present and not f.busy and not f.giant and t and t.alive and t.present
                    and not t.busy and not t.giant and t.team != f.team)
        for who in sorted(fighters,key=lambda f:f.index):
            self.charge.setdefault(who.index,0)
            if self.active and who.index in self.active[:3]:continue
            allies = [f for f in live if f.team == who.team]
            if not who.alive or not who.present or who.giant or len(allies) < 2:
                self.offers.pop(who.index,None)
                continue
            self.charge[who.index] = self.limit if training and self.training_full else min(self.limit,self.charge[who.index]+1)
        if self.active:return None
        for who in sorted(live,key=lambda f:f.index):
            allies = [f for f in live if f.team == who.team]
            if len(allies)<2:continue
            offer = self.offers.get(who.index)
            if offer:
                requester = roster.get(offer[0])
                if (self.clock >= offer[2] or not requester or not eligible(requester)
                        or requester.target != offer[1]):
                    self.offers.pop(who.index,None)
                    continue
            if self.charge[who.index] < self.limit:
                continue
            if offer:
                for other in sorted(allies,key=lambda f:f.index):
                    if (other.index != offer[0] and eligible(other) and other.target == offer[1]
                            and self.charge.get(other.index,0)>=self.limit
                            and (other.index in pressed or other.cpu)):
                        requester = roster[offer[0]]
                        self.active = (requester.index,other.index,offer[1],variant(requester.ki,other.ki))
                        self.offers.clear()
                        self.charge[requester.index] = self.charge[other.index] = 0
                        return self.active
            else:
                if who.index in pressed and eligible(who):
                    self.offers[who.index] = (who.index,who.target,self.clock+self.ttl)
        return None

    def finish(self):
        self.active = None


def save(a):
    full.save(a)
    a.r(16,8,0);a.i(63,8,29,0x290)
    a.r(18,8,0);a.i(63,8,29,0x298)


def restore(a, result=None):
    if result is not None:a.i(31,result,29,full.OFFSETS[2])
    a.i(55,8,29,0x290);a.r(17,0,8)
    a.i(55,8,29,0x298);a.r(19,0,8)
    full.restore(a)


def gate_code():
    a=Assembler(GATE);core.gate(a,'no')
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no')
    for off in (C['enabled'],C['ready']):a.lw(9,8,off);a.branch(4,9,0,'no')
    a.li(8,modes.CONTROL);a.lw(9,8,12);a.li(11,modes.FFA);a.branch(4,9,11,'no')
    a.li(8,start.CONTROL);a.lw(9,8);a.branch(5,9,0,'no')
    a.li(8,A(0x333700));a.lw(9,8);a.branch(5,9,0,'no')
    a.li(8,A(0x3337B8));a.lw(9,8);a.i(12,9,9,0x2100);a.branch(5,9,0,'no')
    a.li(8,A(0x3337C0));a.lw(9,8);a.li(11,1);a.branch(5,9,11,'no')
    a.li(8,A(0x2FEB38));a.lw(8,8);full.pointer(a,8,0x108,'no',temp=11,test=9)
    a.lw(9,8);a.li(11,3);a.branch(5,9,11,'no')
    a.lw(8,28,-22364);a.lw(9,8,628);a.branch(5,9,0,'no')
    a.li(2,1);a.jr();a.label('no');a.move(2,0);a.jr()
    data=a.finish();assert GATE+len(data)<=ELIGIBLE;return data


def eligible_code():
    """a0 physical -> v0 registered free actor, v1 target index; else v0=0.

    Never interrupts a native bound move, reload, corpse, hit reaction, or a
    pending transition. The caller separately checks ally/enemy relationships.
    """
    import tag_rush_safety as safety
    a=Assembler(ELIGIBLE);a.li(8,CONTROL);a.lw(10,8,8)
    a.r(0x2B,9,4,10);a.branch(4,9,0,'no')
    a.li(8,participation.CONTROL);a.lw(9,8,12);a.lw(11,8,16);a.r(0x27,11,11,0);a.r(0x24,9,9,11)
    a.li(11,1);a.r(4,11,4,11);a.r(0x24,9,9,11);a.branch(4,9,0,'no')
    a.li(8,core.POINTERS);a.r(0,9,0,4,2);a.r(0x21,8,8,9);a.lw(2,8)
    full.pointer(a,2,0x1600,'no');a.lw(9,2);a.branch(5,9,4,'no')
    actors.hp(a,2,'no')
    actors.model(a,2,12,'no');safety.emit_non_giant_model(a,12,'no');emit_admitted_model(a,12,'no')
    # Broad ordinary actions include movement, charge, punching and taunting;
    # the outgoing native cleanup is run before the director borrows any clip.
    a.lw(8,2,2376);a.addiu(8,8,-11);a.i(11,9,8,169);a.branch(4,9,0,'no')
    for off in actors.ACTION_FIELDS[1:]:
        a.lw(8,2,off);a.li(9,-1);a.branch(5,8,9,'no')
    for off in (3480,3500,3512):a.lw(8,2,off);a.branch(5,8,0,'no')
    a.li(8,core.TABLE);a.r(0,9,0,4,2);a.r(0x21,8,8,9);a.lw(3,8)
    a.jr();a.label('no');a.move(2,0);a.move(3,0);a.jr()
    data=a.finish();assert ELIGIBLE+len(data)<=INPUT;return data


def emit_admitted_model(a,model,fail):
    """Require this current form's captured skeleton admission before consent.

    Matches the director's own final check. Unknown transformations do not
    inherit their base form's approval. Clobbers t0..t3 and t5 only.
    """
    assert model not in (8,9,10,11,13)
    a.li(13,CONTROL+0x3A0);a.lw(10,13);full.pointer(a,10,4096,fail)
    a.lw(8,model,12);a.lw(9,13,4);a.addiu(11,9,-1);a.i(11,11,11,4096)
    a.branch(4,11,0,fail);a.r(0x2B,9,8,9);a.branch(4,9,0,fail)
    a.r(0x21,10,10,8);a.i(36,8,10,0);a.i(12,9,8,1);a.branch(4,9,0,fail)


def input_code():
    """Frame-start edges and consumption, through each actor's routed pad."""
    a=Assembler(INPUT);save(a);a.li(16,CONTROL)
    a.lw(8,16);a.li(9,MAGIC);a.branch(5,8,9,'done')
    a.sw(0,16,C['requested'])
    a.li(8,core.MODE);a.lw(8,8,8);a.lw(9,16,4);a.branch(5,8,9,'done')
    a.lw(8,28,-22364);a.branch(5,8,9,'done')
    a.lw(19,16,8);a.move(20,0)
    a.addiu(8,19,-1);a.i(11,8,8,modes.emitted_actors());a.branch(4,8,0,'done')
    a.li(8,core.MODE);a.lw(9,8,4);a.branch(5,9,19,'done');a.lw(9,8,12);a.branch(5,9,19,'done')
    a.label('scan');a.branch(4,20,19,'done')
    a.li(8,core.POINTERS);a.r(0,9,0,20,2);a.r(0x21,8,8,9);a.lw(21,8)
    full.pointer(a,21,0x1300,'next');a.lw(8,21,0x1278);a.branch(5,8,0,'next')
    a.move(4,21);a.call(A(0x1DC2A0));a.branch(4,2,0,'next');a.move(22,2)
    # The shared movement/attack fusion controller regenerates this synthetic
    # record for every query. Its split ownership cannot supply one person's
    # consent yet; do not consume a chord that the native decoder would rebuild.
    import coop_controller
    a.li(8,coop_controller.MERGED);a.branch(4,22,8,'next')
    a.li(23,1);a.r(4,23,20,23);a.lw(24,22,328)
    a.i(12,8,24,CHORD_BUTTONS);a.li(9,CHORD_BUTTONS);a.branch(5,8,9,'not_held')
    # Native polling and the extra-pad encoder already apply the same
    # half-tilt/dominant-axis rule. Use that left-stick alias, never the
    # independent right-stick0x100000 bit or a new arbitrary deadzone.
    a.li(9,LEFT_INPUT);a.r(0x24,8,24,9);a.branch(5,8,0,'held')
    a.label('not_held')
    # Keep the latch through a partially released chord. It rearms only when
    # Triangle and Left are both released (holding Charge itself is fine).
    a.li(9,CONSUME_INPUT);a.r(0x24,8,24,9);a.branch(5,8,0,'masked')
    a.r(0x27,9,23,0)
    for off in (C['last_held'],C['consumed']):a.lw(8,16,off);a.r(0x24,8,8,9);a.sw(8,16,off)
    a.jump('next')
    a.label('held');a.lw(8,16,C['last_held']);a.r(0x24,9,8,23)
    a.r(0x25,8,8,23);a.sw(8,16,C['last_held']);a.branch(5,9,0,'masked')
    a.call(GATE);a.branch(4,2,0,'next');a.lw(8,16,C['active']);a.branch(5,8,0,'masked')
    a.lw(8,16,C['approaching']);a.branch(5,8,0,'masked')
    a.r(0,8,0,20,5);a.li(9,METERS);a.r(0x21,8,8,9)
    a.lw(9,8,T['allies']);a.i(11,9,9,2);a.branch(5,9,0,'next')
    # Reserve the tag gesture even before the meter fills. An early press must
    # not fall through to the native L2+Triangle special or queue a later tag.
    a.lw(9,16,C['consumed']);a.r(0x25,9,9,23);a.sw(9,16,C['consumed'])
    a.lw(9,8);a.lw(10,16,C['charge_ticks']);a.r(0x2B,9,9,10);a.branch(5,9,0,'masked')
    a.lw(8,16,C['requested']);a.r(0x25,8,8,23);a.sw(8,16,C['requested'])
    a.label('masked');a.lw(8,16,C['consumed']);a.r(0x24,8,8,23);a.branch(4,8,0,'next')
    # Keep Charge, consume direction+attack so a declined offer cannot turn
    # into an accidental native Blast2 or movement on the following update.
    # The gesture owns only a currently-left movement stick. Neutralize its
    # two axes together so a diagonal left gesture cannot drift vertically;
    # right-stick/camera input and later non-left movement remain available.
    a.lw(8,22,328);a.li(9,ANALOG_LEFT);a.r(0x24,8,8,9);a.branch(4,8,0,'digital_only')
    for off in (304,308):a.sw(0,22,off)
    a.label('digital_only');a.li(9,~CONSUME_INPUT)
    for off in PRESS_WORDS:a.lw(8,22,off);a.r(0x24,8,8,9);a.sw(8,22,off)
    a.label('next');a.addiu(20,20,1);a.jump('scan')
    a.label('done');restore(a);a.jr();data=a.finish();assert INPUT+len(data)<=TICK;return data


def tick_code():
    import tag_rush_safety as safety
    import tag_rush_approach as approach
    a=Assembler(TICK);save(a);a.li(16,CONTROL)
    a.lw(8,16);a.li(9,MAGIC);a.branch(5,8,9,'done')
    a.lw(8,16,C['approaching']);a.branch(4,8,0,'not_approaching')
    a.call(approach.TICK);a.jump('done');a.label('not_approaching')
    # A slow native effect may outlive a cancelled cinematic. Keep retiring
    # only our authenticated nodes after releasing controls, even with READY
    # off or the battle gate closed. Never free or reuse their descriptors.
    import tag_rush_effects as effects
    a.lw(8,16,C['active']);a.branch(5,8,0,'scene_cleanup')
    a.li(12,FX_CLEANUP);a.lw(8,12);a.branch(4,8,0,'scene_cleanup')
    a.li(8,effects.CONTROL);a.lw(8,8);a.li(9,effects.MAGIC);a.branch(5,8,9,'scene_cleanup')
    a.call(effects.STOP);a.branch(5,2,0,'scene_cleanup')
    a.li(12,FX_CLEANUP);a.sw(0,12)
    a.label('scene_cleanup')
    # Leaving a battle must return borrowed clips even though the ordinary
    # charging/consent gate has already closed. Pausing keeps the scene held.
    a.lw(8,16,C['active']);a.branch(4,8,0,'gate')
    a.lw(8,16,C['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'cancel_scene')
    a.li(12,core.MODE);a.lw(9,12,8);a.branch(5,8,9,'cancel_scene')
    a.lw(8,12);a.li(9,1);a.branch(5,8,9,'cancel_scene')
    for off in (C['enabled'],C['ready']):a.lw(8,16,off);a.branch(4,8,0,'cancel_scene')
    a.li(12,A(0x2FEB38));a.lw(12,12);full.pointer(a,12,0x108,'cancel_scene')
    a.lw(8,12);a.li(9,3);a.branch(5,8,9,'cancel_scene')
    import tag_rush_pause as active_pause
    a.call(active_pause.CHECK);a.li(8,active_pause.CANCEL);a.branch(4,2,8,'cancel_scene')
    a.branch(4,2,0,'done');a.jump('active_gate_passed')
    a.label('gate');a.call(GATE);a.branch(4,2,0,'done')
    a.label('active_gate_passed')
    a.lw(8,16,C['active']);a.branch(4,8,0,'idle');a.lw(8,16,C['shared']);a.branch(5,8,0,'scene_step')
    a.label('idle');a.lw(8,16,C['clock']);a.addiu(8,8,1);a.sw(8,16,C['clock'])
    a.move(17,0);a.li(18,METERS);a.lw(19,16,C['count'])
    a.label('team');a.sw(0,18,T['allies']);a.i(12,20,17,1)
    # Charge follows actual participating living teammates, not padded slots.
    a.label('count');a.r(0x2B,8,20,19);a.branch(4,8,0,'counted')
    a.li(8,participation.CONTROL);a.lw(9,8,12);a.lw(10,8,16);a.r(0x27,10,10,0);a.r(0x24,9,9,10)
    a.li(10,1);a.r(4,10,20,10);a.r(0x24,9,9,10);a.branch(4,9,0,'count_next')
    a.li(8,core.POINTERS);a.r(0,9,0,20,2);a.r(0x21,8,8,9);a.lw(21,8)
    a.branch(4,21,0,'count_next');actors.hp(a,21,'count_next')
    actors.model(a,21,12,'count_next');safety.emit_non_giant_model(a,12,'count_next')
    a.lw(8,18,T['allies']);a.addiu(8,8,1);a.sw(8,18,T['allies'])
    a.label('count_next');a.addiu(20,20,2);a.jump('count')
    a.label('counted');a.lw(8,18,T['allies']);a.i(11,8,8,2);a.branch(5,8,0,'cancel')
    a.lw(8,16,C['active']);a.branch(4,8,0,'owner_live');a.lw(8,16,C['members'])
    a.li(9,1);a.r(4,9,17,9);a.r(0x24,8,8,9);a.branch(5,8,0,'next_team')
    a.label('owner_live')
    # An eliminated or consumed fighter must not charge because two *other*
    # members of their team are still alive.
    a.li(8,participation.CONTROL);a.lw(9,8,12);a.lw(10,8,16);a.r(0x27,10,10,0);a.r(0x24,9,9,10)
    a.li(10,1);a.r(4,10,17,10);a.r(0x24,9,9,10);a.branch(4,9,0,'cancel')
    a.li(8,core.POINTERS);a.r(0,9,0,17,2);a.r(0x21,8,8,9);a.lw(21,8)
    a.branch(4,21,0,'cancel');actors.hp(a,21,'cancel')
    actors.model(a,21,12,'cancel');safety.emit_non_giant_model(a,12,'cancel')
    a.lw(8,18,T['charge']);a.lw(9,16,C['charge_ticks'])
    a.lw(10,16,C['training_full']);a.branch(4,10,0,'fill');a.lw(10,16,C['training']);a.branch(4,10,0,'fill');a.move(8,9)
    a.label('fill');a.r(0x2B,10,8,9);a.branch(4,10,0,'charged');a.addiu(8,8,1)
    a.label('charged');a.sw(8,18,T['charge']);a.r(0x2B,8,8,9);a.branch(5,8,0,'next_team')
    a.lw(8,16,C['active']);a.branch(5,8,0,'next_team')
    a.lw(21,18,T['inviter']);a.li(9,-1);a.branch(4,21,9,'offer')
    a.lw(8,16,C['clock']);a.lw(9,18,T['expiry']);a.r(0x2B,8,8,9);a.branch(4,8,0,'cancel')
    a.move(4,21);a.call(ELIGIBLE);a.branch(4,2,0,'cancel');a.lw(22,18,T['target']);a.branch(5,3,22,'cancel')
    a.move(4,22);a.call(ELIGIBLE);a.branch(4,2,0,'cancel')
    a.i(12,20,17,1)
    a.label('accept');a.r(0x2B,8,20,19);a.branch(4,8,0,'next_team');a.branch(4,20,21,'accept_next')
    a.move(4,20);a.call(ELIGIBLE);a.branch(4,2,0,'accept_next');a.branch(5,3,22,'accept_next')
    a.r(0,8,0,20,5);a.li(9,METERS);a.r(0x21,8,8,9);a.lw(9,8,T['charge']);a.lw(10,16,C['charge_ticks'])
    a.r(0x2B,9,9,10);a.branch(5,9,0,'accept_next')
    a.lw(8,2,0x1278);a.branch(5,8,0,'accepted')
    a.li(8,1);a.r(4,8,20,8);a.lw(9,16,C['requested']);a.r(0x24,8,8,9);a.branch(4,8,0,'accept_next')
    a.label('accepted');a.move(4,21);a.move(5,20);a.move(6,22);a.call(approach.BEGIN)
    a.branch(4,2,0,'next_team');a.sw(0,18,T['charge'])
    a.r(0,8,0,20,5);a.li(9,METERS);a.r(0x21,8,8,9);a.sw(0,8,T['charge']);a.jump('done')
    a.label('accept_next');a.addiu(20,20,2);a.jump('accept')
    a.label('offer');a.move(20,17)
    a.li(8,1);a.r(4,8,20,8);a.lw(9,16,C['requested']);a.r(0x24,8,8,9);a.branch(4,8,0,'offer_next')
    a.move(4,20);a.call(ELIGIBLE);a.branch(4,2,0,'offer_next');a.move(22,3)
    a.r(0x26,8,20,22);a.i(12,8,8,1);a.branch(4,8,0,'offer_next')
    a.move(4,22);a.call(ELIGIBLE);a.branch(4,2,0,'offer_next')
    a.sw(20,18,T['inviter']);a.sw(22,18,T['target']);a.lw(8,16,C['clock']);a.addiu(8,8,REQUEST_SECONDS*ACTOR_HZ);a.sw(8,18,T['expiry']);a.jump('next_team')
    a.label('offer_next');a.jump('next_team')
    a.label('cancel');a.li(8,-1);a.sw(8,18,T['inviter']);a.sw(0,18,T['expiry'])
    a.label('next_team');a.addiu(18,18,METER_STRIDE);a.addiu(17,17,1);a.branch(5,17,19,'team')
    a.lw(8,16,C['active']);a.branch(4,8,0,'done');a.label('scene_step');a.call(STEP);a.jump('done')
    a.label('cancel_scene');a.li(4,1);a.call(FINISH)
    a.label('done');restore(a);a.jr();data=a.finish();assert TICK+len(data)<=FRAME_NATIVE;return data


def frame_code(previous,bootstrap=False):
    a=Assembler(FRAME);save(a)
    if bootstrap:
        import tag_rush_bootstrap
        a.call(tag_rush_bootstrap.CODE)
    a.call(INPUT);a.call(TICK);restore(a);a.jump(previous)
    data=a.finish();assert FRAME+len(data)<=GATE;return data


def control_bytes(manager,count,settings,training=False,ready=False):
    if type(count) is not int or not 2 <= count <= modes.ENGINE_ACTORS:raise ValueError('Invalid tag fighter capacity')
    data=bytearray(0x400)
    vals={**{k:0 for k in C},'magic':MAGIC,'manager':manager,'count':count,
          'enabled':int(settings['tag_team_rush_enabled']),'shared':int(settings['tag_team_rush_shared_camera']),
          'charge_ticks':math.ceil(settings['tag_team_rush_charge_seconds']*ACTOR_HZ),
          'damage':settings['tag_team_rush_damage'],'training_full':int(settings['tag_team_rush_training_full']),
          'training':int(training),'ready':int(ready)}
    for k,v in vals.items():struct.pack_into('<I',data,C[k],v)
    for index in range(count):struct.pack_into('<i',data,0x100+index*METER_STRIDE+T['inviter'],-1)
    return bytes(data)


def hud_extension(ram):
    if len(ram)>=END and struct.unpack_from('<I',ram,CONTROL)[0]==MAGIC:
        import tag_rush_hud
        return CONTROL,MAGIC,tag_rush_hud.DRAW
    return None
