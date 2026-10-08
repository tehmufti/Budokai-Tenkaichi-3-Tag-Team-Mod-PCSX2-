"""Two independent spectator seats, corpse viewing, and safe allied takeover.

An optional upgrade of spectator_switch's exact legacy emission. No identity,
team, target or resources are rewritten. The native human/CPU input flag and
pad resolver change only after an originally human seat has been defeated.
"""
from native_map import A, FLAG
import struct
from prototype import Assembler
import spectator_switch as spec
import battle_mode_policy as modes
import fresh_team_combat as core
import fresh_team_camera as fresh
import team_participation as part
import guest_killfeed as feed
import extra_specials as specials
import coop_controller as pads
import team_start_gate as start
import fusion_partner_lifecycle as fusion
import extra_reload_requests as reloads
import lockon_queue as queue

LOOKUP, TAKE, PAD, NATIVE_PAD = 0x07282000,0x07283000,0x07285000,0x07286000
VERSION=2
OPTION_MAGIC=0x53544F31
OPTIONS=120
TAKE_ENABLED=124
F=dict(version=40,previous=44,include_dead=48,ports=52,human_ports=56,
       original=60,owned=68,held=76,buttons=84,watching=92,takeovers=100,
       battle_mode=104,pad_tail=108,view_side=112)
SQUARE=0x8000
REGS=tuple(range(2,28))+(30,31)
# payload()'s view side and lock row. beta.33 kept them in k0/k1, which belong to the EE kernel: its interrupt
# entry overwrites both and never restores them. A spectator update interrupted after the lock row was computed
# stored through k1 = COP0 Status (0x70030C1x), a TLB miss the match never left. fp and t5 are saved by save(),
# and neither LOOKUP nor TAKE (which saves every register) writes them.
SIDE,ROW=30,13
KERNEL_SIDE,KERNEL_ROW=26,27   # the beta.33 emission (kernel_scratch=True), accepted for an in-place upgrade

def save(a):
    a.addiu(29,29,-0x100)
    for i,r in enumerate(REGS):a.i(63,r,29,8*i)

def restore(a,skip=()):
    for i,r in enumerate(REGS):
        if r not in skip:a.i(55,r,29,8*i)
    a.addiu(29,29,0x100)

def pointer(a,r,size,fail):
    a.li(8,0x100000);a.r(0x2B,9,r,8);a.branch(5,9,0,fail)
    a.li(8,0x8000000-size);a.r(0x2B,9,8,r);a.branch(5,9,0,fail)
    a.i(12,9,r,3);a.branch(5,9,0,fail)

def lookup():
    """Physical a0 -> model v0, valid v1, team a1 (continuity LOOKUP ABI).

    Include dead but registered visible bodies. Absent and fusion-consumed
    reservations are never selectable; living authored vanishes remain valid.
    """
    a=Assembler(LOOKUP);core.gate(a,'no')
    a.r(0x2B,8,4,10);a.branch(4,8,0,'no')
    a.li(8,part.CONTROL);a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no')
    a.addiu(12,0,1);a.r(4,12,4,12);a.lw(9,8,12);a.r(0x24,9,9,12);a.branch(4,9,0,'no')
    a.lw(9,8,16);a.r(0x24,9,9,12);a.branch(5,9,0,'no')
    a.r(0,12,0,4,2);a.li(8,core.POINTERS);a.r(0x2D,8,8,12);a.lw(14,8);pointer(a,14,0x1600,'no')
    a.lw(9,14);a.branch(5,9,4,'no');a.lw(5,14,8);a.i(11,9,5,2);a.branch(4,9,0,'no')
    a.lw(2,14,12);a.i(11,9,2,12);a.branch(4,9,0,'no')
    a.r(0,8,0,2,2);a.li(9,core.MODELS);a.r(0x2D,8,8,9);a.lw(15,8);pointer(a,15,0x1670,'no')
    a.lw(9,15,16);a.branch(5,9,2,'no');a.lw(9,15,4);a.branch(4,9,0,'no')
    a.li(8,feed.CONTROL+spec.DEAD);a.r(0x2D,8,8,12);a.lw(9,8);a.branch(4,9,0,'yes')
    a.li(8,spec.CONTROL);a.lw(9,8,F['include_dead']);a.branch(4,9,0,'no')
    a.lw(9,15,8);a.branch(4,9,0,'no')
    a.label('yes');a.addiu(3,0,1);a.jr()
    a.label('no');a.addiu(2,0,-1);a.move(3,0);a.addiu(5,0,-1);a.jr()
    return a.finish()

def ordinary_action(a,fail,*,pending=False):
    """t0 ordinary locomotion, charge and melee/ki actions; no paired states.

    180+ includes grabs, clashes, hurt/KO, transformations and specials.
    Keep native pending actions intact, but refuse any cinematic queued there.
    """
    ready=f'take_action{len(a.words)}'
    if pending:a.addiu(9,0,-1);a.branch(4,8,9,ready)
    a.addiu(9,8,-11);a.i(11,9,9,169);a.branch(4,9,0,fail)
    a.label(ready)

def take(*,base=TAKE,commit=True,configurable=True,quad=False,ordinary=True):
    """a0 pad port, a1 selected physical. No queues, implicit requests or revive."""
    if quad:
        import quad_lifecycle as q
        fields,control,ports=q.F,q.CONTROL,4
    else:fields,control,ports=F,spec.CONTROL,2
    a=Assembler(base);save(a);a.move(16,4);a.move(17,5);core.gate(a,'no');a.move(18,10)
    if configurable:
        a.li(8,control);a.lw(9,8,q.OPTIONS if quad else OPTIONS);a.li(11,OPTION_MAGIC);a.branch(5,9,11,'default_takeover')
        a.lw(9,8,q.TAKE_ENABLED if quad else TAKE_ENABLED);a.branch(4,9,0,'no');a.label('default_takeover')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'no')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x3900);a.branch(5,8,0,'no')
    a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'no')
    a.li(8,start.CONTROL);a.lw(8,8);a.branch(5,8,0,'no')
    a.li(8,specials.CONTROL);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,'no')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'no')
    a.li(19,control);a.lw(8,19,fields['battle_mode']);a.addiu(9,0,modes.FFA);a.branch(4,8,9,'no')
    a.addiu(9,0,modes.COOP);a.branch(5,8,9,'mode_ready')
    a.li(8,modes.CONTROL);a.lw(9,8,24);a.r(0x2B,9,9,18);a.branch(5,9,0,'no')
    a.lw(9,8,64);a.branch(5,9,0,'no')
    a.label('mode_ready');a.i(11,8,16,ports);a.branch(4,8,0,'no');a.addiu(8,0,1);a.r(4,8,16,8)
    a.lw(9,19,fields['human_ports']);a.r(0x24,9,9,8);a.branch(4,9,0,'no')
    a.r(0,8,0,16,2);a.r(0x2D,19,19,8);a.lw(20,19,fields['owned'])
    a.r(0x2B,8,20,18);a.branch(4,8,0,'no');a.r(0x2B,8,17,18);a.branch(4,8,0,'no')
    a.li(8,feed.CONTROL+spec.DEAD);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(4,8,0,'no')
    a.r(0x26,8,20,17);a.i(12,8,8,1);a.branch(5,8,0,'no')
    a.move(4,17);a.call(LOOKUP);a.branch(4,3,0,'no')
    a.li(8,feed.CONTROL+spec.DEAD);a.r(0,9,0,17,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,0,'no')
    a.li(8,core.POINTERS);a.r(0,9,0,17,2);a.r(0x2D,8,8,9);a.lw(21,8)
    a.lw(8,21,spec.CPU_DRIVEN);a.branch(4,8,0,'no')
    # The feed latch trails damage by an update. Check native health too so
    # a fighter killed this frame cannot briefly be adopted as a living CPU.
    a.lw(8,21,0x994);a.i(11,9,8,5);a.branch(4,9,0,'no')
    a.r(0,9,0,8,7);a.r(0,10,0,8,5);a.r(0x2D,9,9,10)
    a.r(0,10,0,8,2);a.r(0x2D,9,9,10);a.r(0x2D,9,9,21)
    a.lw(8,9,0x9E4);a.branch(6,8,0,'no')
    a.lw(8,21,2376)
    if ordinary:ordinary_action(a,'no')
    else:
        a.addiu(9,0,11);a.branch(4,8,9,'idle');a.addiu(9,0,15);a.branch(5,8,9,'no')
        a.label('idle')
    a.move(4,21);a.call(fusion.RESERVED);a.branch(5,2,0,'no')
    a.i(11,8,17,2);a.branch(5,8,0,'no_reload')
    a.addiu(8,17,-2);a.r(0,8,0,8,6);a.li(9,reloads.RECORDS);a.r(0x2D,8,8,9)
    a.lw(8,8,4);a.addiu(9,8,-1);a.i(11,9,9,2);a.branch(5,9,0,'no')
    a.label('no_reload')
    # Refuse even idle-looking actors still bound to the native director.
    a.li(8,A(0x2FEBCC));a.lw(14,8);a.branch(4,14,0,'no_camera')
    pointer(a,14,832,'no');a.lw(8,14,812);a.branch(5,8,0,'camera_active')
    a.lw(8,14,704);a.branch(4,8,0,'no_camera')
    a.label('camera_active');a.lw(8,21,12);a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x2D,8,8,9);a.lw(8,8)
    a.lw(9,14,768);a.branch(4,8,9,'no');a.lw(9,14,772);a.branch(4,8,9,'no')
    a.label('no_camera')
    for off in (2380,2388,2392,2396,2400):
        a.lw(8,21,off)
        if ordinary:ordinary_action(a,'no',pending=True)
        else:a.addiu(9,0,-1);a.branch(5,8,9,'no')
    for off in (3480,3500,3512):a.lw(8,21,off);a.branch(5,8,0,'no')
    for bank in (0x1085,0x10AD):
        a.i(36,8,21,bank+(FLAG(0x94)>>3));a.i(12,8,8,1<<(FLAG(0x94)&7));a.branch(5,8,0,'no')
        if ordinary:
            # Actor-authored cameras may be active without a bound director.
            a.i(36,8,21,bank+(FLAG(0xD3)>>3));a.i(12,8,8,1<<(FLAG(0xD3)&7));a.branch(5,8,0,'no')
    if not commit:
        # The on-screen offer uses the exact admission path, without changing
        # ownership, clearing input, queuing requests or touching fighter data.
        a.addiu(2,0,1);a.jump('return');a.label('no');a.move(2,0)
        a.label('return');restore(a,skip=(2,));a.jr();return a.finish()
    # Retain every native identity and target. Clear only the old CPU's input.
    a.li(8,core.POINTERS);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(22,8)
    a.addiu(8,0,1);a.sw(8,22,spec.CPU_DRIVEN);a.sw(0,21,spec.CPU_DRIVEN)
    for actor in (21,22):
        for off in (0x127C,0x1280,0x1284):a.sw(0,actor,off)
    a.sw(17,19,fields['owned']);a.sw(0,19,fields['held']);a.sw(0,19,fields['watching'])
    if quad:
        import quad_viewports as views
        import quad_controller as controllers
        a.r(0,9,0,16,2);a.li(8,views.SUBJECTS);a.r(0x2D,8,8,9);a.sw(17,8)
        a.li(8,controllers.CONTROL+0x40);a.r(0x2D,8,8,9);a.sw(17,8)
    else:
        a.lw(23,19,fields['view_side']);a.r(0,9,0,23,2);a.li(8,control);a.r(0x2D,8,8,9)
        a.addiu(10,17,1);a.sw(10,8,spec.FIELDS['lock'])
        a.li(8,fresh.SUCCESSOR_CONTROL);a.r(0x2D,8,8,9);a.sw(17,8,8)
        a.sw(21,8,0x30);a.addiu(9,0,1);a.sw(9,8,0x20)
    # Extra dispatch has an explicit human whitelist in addition to CPU flag.
    a.li(8,specials.CONTROL);a.lw(9,8,20);a.addiu(10,0,1);a.r(4,10,17,10);a.r(0x25,9,9,10);a.sw(9,8,20)
    a.li(8,control);a.lw(9,8,fields['takeovers']);a.addiu(9,9,1);a.sw(9,8,fields['takeovers'])
    a.addiu(2,0,1);a.jump('return');a.label('no');a.move(2,0)
    a.label('return');restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<PAD-TAKE;return data

def emit_pad(a,fail):
    """Emit assignment lookup without altering actor +4 (native role)."""
    a.li(8,spec.CONTROL);a.lw(9,8);a.li(10,spec.MAGIC);a.branch(5,9,10,fail)
    a.lw(9,8,F['version']);a.addiu(10,0,VERSION);a.branch(5,9,10,fail)
    a.lw(9,8,spec.FIELDS['manager']);a.lw(10,28,-22364);a.branch(5,9,10,fail)
    for port in range(2):
        nxt=f'pad_next_{port}';a.lw(9,8,F['human_ports']);a.i(12,9,9,1<<port);a.branch(4,9,0,nxt)
        a.lw(9,8,F['owned']+4*port);a.li(10,core.MODE);a.lw(10,10,4);a.r(0x2B,10,9,10);a.branch(4,10,0,nxt)
        a.r(0,9,0,9,2);a.li(10,core.POINTERS);a.r(0x2D,9,9,10);a.lw(9,9);a.branch(5,4,9,nxt)
        a.li(2,pads.RECORDS+port*pads.RECORD_STRIDE);a.jump('return');a.label(nxt)
    a.jump(fail)

def pad():
    a=Assembler(PAD);save(a);emit_pad(a,'native');a.label('return');restore(a,skip=(2,));a.jr()
    a.label('native');restore(a);a.jump(NATIVE_PAD);return a.finish()

def payload(previous,automatic=False,revival=True,kernel_scratch=False):
    side,row=(KERNEL_SIDE,KERNEL_ROW) if kernel_scratch else (SIDE,ROW)
    a=Assembler(spec.CODE);save(a);a.li(16,spec.CONTROL)
    a.lw(8,16);a.li(9,spec.MAGIC);a.branch(5,8,9,'done')
    a.lw(8,16,spec.FIELDS['enabled']);a.branch(4,8,0,'done');core.gate(a,'done');a.move(17,10)
    a.lw(8,16,spec.FIELDS['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'done')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,start.CONTROL);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x3900);a.branch(5,8,0,'done')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'done')
    a.li(8,A(0x2FEB38));a.lw(14,8);pointer(a,14,0x108,'done')
    a.lw(8,14);a.addiu(9,0,3);a.branch(5,8,9,'done')
    # A fused seat keeps the existing shared control policy, never takeover.
    a.lw(8,16,F['battle_mode']);a.addiu(9,0,modes.COOP);a.branch(5,8,9,'ports')
    a.li(8,modes.CONTROL);a.lw(9,8,24);a.r(0x2B,9,9,17);a.branch(5,9,0,'done')
    a.lw(9,8,64);a.branch(5,9,0,'done')
    a.label('ports');a.move(18,0)
    a.label('port');a.r(0,8,0,18,2);a.r(0x2D,19,16,8)
    a.move(side,18);a.li(8,spec.SCENE);a.lw(9,8,spec.SPLIT_OFF);a.addiu(8,0,spec.SPLIT_VALUE)
    a.branch(4,8,9,'view_side_ready');a.branch(5,18,0,'next')
    a.li(8,fresh.LEADER_CONTROL);a.lw(side,8,spec.LEADER_SIDE);a.i(11,9,side,2);a.branch(5,9,0,'view_side_ready');a.move(side,0)
    a.label('view_side_ready');a.sw(side,19,F['view_side'])
    a.r(0,8,0,side,2);a.r(0x2D,row,16,8)
    a.addiu(8,0,1);a.r(4,8,18,8);a.lw(9,16,F['ports']);a.r(0x24,9,9,8);a.branch(4,9,0,'next')
    a.li(8,spec.pad_buttons());a.r(0,9,0,18,6);a.r(0,10,0,18,7);a.r(0x2D,9,9,10)
    a.r(0,10,0,18,8);a.r(0x2D,9,9,10);a.r(0x2D,8,8,9);a.lw(20,8)
    a.lw(21,19,F['buttons']);a.sw(20,19,F['buttons'])
    a.lw(22,19,F['owned']);a.r(0x2B,8,22,17);a.branch(4,8,0,'next')
    a.lw(9,16,F['human_ports']);a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,9,9,8);a.branch(4,9,0,'watch')
    a.li(8,feed.CONTROL+spec.DEAD);a.r(0,9,0,22,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,0,'watch')
    if revival:
        # A positive-HP human seat may have just been revived. Merely clearing
        # its spectator lock leaves the living successor camera on whichever
        # teammate was watched during the KO (especially co-op's second view).
        # Return only this viewport to its CURRENT owned body, never the old
        # original body abandoned by an explicit CPU takeover.
        a.lw(8,19,F['watching']);a.branch(4,8,0,'already_alive')
        a.sw(0,19,F['held']);a.sw(0,19,F['watching'])
        a.addiu(8,22,1);a.sw(8,row,spec.FIELDS['lock'])
        a.r(0,8,0,side,2);a.li(9,fresh.SUCCESSOR_CONTROL);a.r(0x2D,8,8,9)
        a.sw(22,8,8);a.r(0,9,0,22,2);a.li(10,core.POINTERS)
        a.r(0x2D,9,9,10);a.lw(9,9);a.sw(9,8,0x30)
        a.addiu(9,0,1);a.sw(9,8,0x20);a.jump('next')
        a.label('already_alive')
    a.sw(0,19,F['held']);a.sw(0,19,F['watching']);a.lw(8,19,F['original']);a.branch(5,8,22,'next')
    a.sw(0,row,spec.FIELDS['lock']);a.jump('next')
    a.label('watch');a.addiu(8,0,1);a.sw(8,19,F['watching'])
    a.i(12,8,20,SQUARE);a.branch(4,8,0,'gesture');a.i(12,8,21,SQUARE);a.branch(5,8,0,'gesture')
    # Square may itself be the user's target binding. In that one case use
    # L2+Square for takeover, leaving a plain Square free to cycle spectators.
    a.li(8,spec.lock.CONTROL);a.lw(9,8,spec.lock.FIELDS['button']);a.li(8,SQUARE)
    a.branch(5,9,8,'take_key_ready');a.i(12,8,20,0x100);a.branch(4,8,0,'gesture')
    a.label('take_key_ready')
    a.lw(5,row,spec.FIELDS['lock'])
    if automatic:
        # Automatic successor cameras are genuine spectator views too. An
        # explicit cycle is no longer required before taking over that body.
        a.branch(5,5,0,'chosen_takeover');a.r(0,8,0,side,2)
        a.li(9,fresh.SUCCESSOR_CONTROL);a.r(0x2D,8,8,9);a.lw(5,8,8)
        a.jump('candidate_ready');a.label('chosen_takeover');a.addiu(5,5,-1)
        a.label('candidate_ready')
    else:
        a.branch(4,5,0,'gesture');a.addiu(5,5,-1)
    a.move(4,18);a.call(TAKE);a.branch(5,2,0,'next')
    a.label('gesture');a.li(8,spec.lock.CONTROL);a.lw(8,8,spec.lock.FIELDS['button'])
    a.r(0x24,9,20,8);a.i(13,10,8,spec.STICK_CHORDS);a.r(0x26,10,10,8);a.r(0x24,10,20,10)
    a.addiu(25,0,spec.HOLD_UPDATES)
    a.li(8,queue.CONTROL);a.lw(11,8,queue.TIMING_MAGIC);a.li(12,queue.TIMING_TAG)
    a.branch(5,11,12,'timing_ready');a.lw(25,8,queue.TIMING_UPDATES)
    a.addiu(11,25,-1);a.li(12,queue.MAX_HOLD_UPDATES);a.r(0x2B,11,11,12);a.branch(4,11,0,'cancel')
    a.move(10,0) # The configurable gesture may be used while moving.
    a.label('timing_ready');a.lw(11,19,F['held']);a.branch(4,9,0,'released');a.branch(5,10,0,'cancel')
    a.r(0x2B,8,11,25);a.branch(4,8,0,'next');a.addiu(11,11,1);a.sw(11,19,F['held']);a.jump('next')
    a.label('cancel');a.sw(0,19,F['held']);a.jump('next')
    a.label('released');a.sw(0,19,F['held']);a.r(0x2B,8,11,25);a.branch(5,8,0,'next')
    a.li(8,fresh.SUCCESSOR_CONTROL);a.r(0,9,0,side,2);a.r(0x2D,8,8,9);a.lw(22,8,8)
    a.r(0x2B,8,22,17);a.branch(5,8,0,'current');a.move(22,0)
    a.label('current');a.move(23,0)
    a.label('scan');a.addiu(23,23,1);a.r(0x2B,8,23,17);a.branch(4,8,0,'next')
    a.r(0x21,24,22,23);a.r(0x2B,8,24,17);a.branch(5,8,0,'bounded');a.r(0x23,24,24,17)
    a.label('bounded');a.move(4,24);a.call(LOOKUP);a.branch(4,3,0,'scan')
    a.addiu(8,24,1);a.sw(8,row,spec.FIELDS['lock'])
    a.li(8,fresh.SUCCESSOR_CONTROL);a.r(0,9,0,side,2);a.r(0x2D,8,8,9);a.sw(24,8,8)
    a.sw(24,16,spec.FIELDS['subject']);a.lw(8,16,spec.FIELDS['switches']);a.addiu(8,8,1);a.sw(8,16,spec.FIELDS['switches'])
    a.label('next');a.addiu(18,18,1);a.addiu(8,0,2);a.branch(5,18,8,'port')
    a.label('done');restore(a);a.jump(previous)
    data=a.finish();assert len(data)<LOOKUP-spec.CODE;return data

def pieces(previous,coop=False,automatic=True,configurable=True,revival=True,ordinary=True,kernel_scratch=False):
    result=[(spec.CODE,payload(previous,automatic,revival,kernel_scratch)),(LOOKUP,lookup()),(TAKE,take(configurable=configurable,ordinary=ordinary))]
    if coop:result.append((pads.ACTOR_PAD,pads.payload(takeover=True)))
    else:result.extend(((PAD,pad()),(NATIVE_PAD,pads.NATIVE(pads.HOOK,0x20)),
                       (pads.HOOK,struct.pack('<2I',(2<<26)|(PAD>>2),0))))
    return result

def validate_memory(ram):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if (u(spec.CONTROL),u(spec.CONTROL+4),u(spec.CONTROL+F['version']))!=(spec.MAGIC,1,VERSION):
        raise ValueError('Unknown spectator upgrade header')
    if u(spec.CONTROL+F['battle_mode']) not in modes.MODES.values():raise ValueError('Unknown captured spectator mode')
    if u(spec.CONTROL+F['human_ports'])&~3 or u(spec.CONTROL+F['ports']) not in (1,3):raise ValueError('Invalid spectator port mask')
    previous=u(spec.CONTROL+F['previous']);coop=u(spec.CONTROL+F['battle_mode'])==modes.COOP
    if not 0x100000<=previous<0x8000000 or previous==spec.CODE:raise ValueError('Invalid spectator chain receipt')
    current=dict(pieces(previous,coop))
    found=None
    for kernel_scratch,automatic,configurable,revival,ordinary in ((k,a,c,r,o) for k in (False,True)
            for o in (True,False) for r in (True,False)
            for a,c in ((True,True),(True,False),(False,True),(False,False))):
        former=pieces(previous,coop,automatic,configurable,revival,ordinary,kernel_scratch)
        if all(ram[p:p+len(data)]==data and not any(ram[p+len(data):p+len(current[p])]) for p,data in former):
            found=(automatic,configurable,revival,kernel_scratch);break
    if found is None:raise ValueError('Spectator upgrade code changed')
    automatic,configurable,revival,kernel_scratch=found
    if u(spec.CONTROL+OPTIONS) not in (0,OPTION_MAGIC):raise ValueError('Spectator preferences changed')
    if u(spec.CONTROL+OPTIONS)==OPTION_MAGIC and u(spec.CONTROL+TAKE_ENABLED) not in (0,1):
        raise ValueError('Invalid takeover preference')
    if coop:
        for at,data in pads.pieces()[1:]:
            if ram[at:at+len(data)]!=data:raise ValueError('Co-op native pad chain changed')
    if u(spec.CONTROL+spec.FIELDS['manager'])!=u(core.ACTORS):raise ValueError('Spectator upgrade manager changed')
    return dict(version=VERSION,previous=previous,automatic=automatic,configurable=configurable,revival=revival,
                kernel_scratch=kernel_scratch)

def build_memory(ram,*,battle_mode='teams',source='<prepared>',settings=None):
    if battle_mode not in modes.MODES:raise ValueError('Unknown spectator mode')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(spec.CONTROL+F['version'])==VERSION:
        installed=validate_memory(ram)
        if u(spec.CONTROL+F['battle_mode'])!=modes.MODES[battle_mode]:raise ValueError('Spectator upgrade belongs to another mode')
        blocks=[]
        for at,data in pieces(installed['previous'],battle_mode=='coop'):
            if ram[at:at+len(data)]!=data:blocks.append(dict(address=at,expected_hex=ram[at:at+len(data)].hex(),data_hex=data.hex()))
        if settings is not None:blocks+=option_blocks(ram,settings)
        return dict(source=str(source),blocks=blocks)
    # Validate exact old bytes, not just a nonzero header or chain pointer.
    legacy_size=len(spec.payload(0));tail=spec.CODE+legacy_size-8
    if u(tail)>>26!=2 or u(tail+4):raise ValueError('Unknown legacy spectator tail')
    previous=(u(tail)&0x3ffffff)<<2
    expected=spec.payload(previous)
    if ram[spec.CODE:spec.CODE+len(expected)]!=expected:raise ValueError('Legacy spectator code changed')
    if u(spec.CONTROL)!=spec.MAGIC or u(spec.CONTROL+4)!=1 or u(spec.CONTROL+8)!=u(core.ACTORS):raise ValueError('Missing captured spectator')
    manager=u(core.ACTORS);count=u(core.MODE+4);original=(0,2 if battle_mode=='coop' else 1)
    humans=0
    for port,physical in enumerate(original):
        actor=u(core.POINTERS+4*physical)
        if not 0x100000<=actor<=len(ram)-0x1600:raise ValueError('Invalid spectator seat actor')
        cpu=u(actor+spec.CPU_DRIVEN)
        if u(start.CONTROL):
            if (u(start.CONTROL),u(start.CONTROL+8),u(start.CONTROL+12))!=(1,manager,count):
                raise ValueError('Stale held start-gate assignment')
            if u(start.CONTROL+0x80+4*physical)!=actor:raise ValueError('Held start-gate seat changed')
            cpu=u(start.CONTROL+0x40+4*physical)
        if cpu not in (0,1):raise ValueError('Invalid captured CPU assignment')
        if cpu==0:humans|=1<<port
    extension=bytearray(120-40)
    for key,value in (('version',VERSION),('previous',previous),('include_dead',1),
            ('ports',3 if humans==3 or u(spec.SCENE+spec.SPLIT_OFF)==spec.SPLIT_VALUE else 1),
            ('human_ports',humans),('battle_mode',modes.MODES[battle_mode])):
        struct.pack_into('<I',extension,F[key]-40,value)
    for port,physical in enumerate(original):
        for key in ('original','owned'):struct.pack_into('<I',extension,F[key]-40+4*port,physical)
    parts=pieces(previous,battle_mode=='coop')
    for at,data in parts:
        if at==spec.CODE:
            if len(data)>len(expected) and any(ram[at+len(expected):at+len(data)]):raise ValueError('Spectator extension occupied')
        elif at==pads.ACTOR_PAD:
            old=pads.payload()
            if ram[at:at+len(old)]!=old:raise ValueError('Unknown co-op pad router')
            if len(data)>len(old) and any(ram[at+len(old):at+len(data)]):raise ValueError('Co-op pad extension occupied')
        elif at==pads.HOOK:
            if ram[at:at+len(data)]!=pads.NATIVE(at,len(data)):raise ValueError('Native pad entry changed')
        elif any(ram[at:at+len(data)]):raise ValueError(f'Spectator helper reservation occupied:{at:08X}')
    if any(ram[spec.CONTROL+40:spec.CONTROL+128]):raise ValueError('Spectator descriptor extension occupied')
    parts.append((spec.CONTROL+40,bytes(extension)))
    import mod_settings
    opts=mod_settings.validate_settings(settings or {})
    updated=bytearray(parts[-1][1]);struct.pack_into('<I',updated,F['include_dead']-40,int(opts['spectate_fallen_fighters']))
    parts[-1]=(spec.CONTROL+40,bytes(updated))
    configured=option_blocks(ram,opts,fresh=True)
    return dict(source=str(source),control=spec.CONTROL,status='INDEPENDENT SPECTATORS WITH ALLIED TAKEOVER',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in parts]+configured)


def option_blocks(ram,settings,fresh=False):
    import mod_settings
    opts=mod_settings.validate_settings(settings)
    desired=[(spec.CONTROL+OPTIONS,struct.pack('<2I',OPTION_MAGIC,int(opts['spectator_takeover_enabled'])))]
    if not fresh:desired.append((spec.CONTROL+F['include_dead'],struct.pack('<I',int(opts['spectate_fallen_fighters']))))
    return [dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in desired if ram[p:p+len(d)]!=d]
