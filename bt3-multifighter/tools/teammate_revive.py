"""Opt-in proximity revival through the stock retained-KO/get-up dispatcher.

No actor/model reconstruction or ownership reset. Recovery protection belongs
to this captured actor pointer and expires after the native animation exits.
All installers are offline; the emulator is never opened or contacted here.
"""
from native_map import A, FLAG, elf_path
import math
import struct
import localization
from prototype import Assembler, ROOT, elf_reader
import battle_mode_policy as policy
import fresh_team_combat as core
import fresh_team_camera as camera
import team_participation as part
import team_start_gate as start
import cinematic_contact_guard as contact
import fusion_partner_lifecycle as fusion
import coop_fusion as coop
import extra_reload_requests as reloads
import guest_killfeed as feed
import guest_healthbars as bars
import viewport_hud as hud
import mod_settings as preferences
import spectator_takeover as takeover
import spectator_switch as spectator
from regional import Y_ORIGIN, screen_y
from native_map import ACTOR_HZ

CODE,GATE,ACTOR,PREDICATE,TICK=0x070B0000,0x070B0400,0x070B1000,0x070B2000,0x070B2800
FRAME,CONTACT,DAMAGE,COMMAND,REQUEST=0x070B6000,0x070B6800,0x070B7000,0x070B7800,0x070B8000
DRAW,CONTROL,ROWS,TEXT,END=0x070BB000,0x070BF000,0x070BF100,0x070BD000,0x070C0000
RING,QUAD,ANGLES,BANDS,RING_TEMPLATE=0x070B8800,0x070BA800,0x070BD100,0x070BD300,0x070BD400
WAVE_TABLE=0x070BD500
MAGIC=0x52565631
# 2 is the flat Sept 19 release, 3 added the ring wave and 4 adds only the
# command pre-scan. Version 5 permits locomotion/taunts while channeling.
# Every accepted older version keeps emitting its exact bytes.
OPTIONS_VERSION=5
VERSIONS=(2,3,4,OPTIONS_VERSION)
# The pre-scan walks at most this many rows. The value is fixed (not the
# capacity of the build being emitted) so version 4 has one byte image; any
# larger count takes the full barrier, which remains the authority.
PRESCAN_ROWS=10
CFG=dict(radius=64,radius_squared=68,health=72,recovery=76,ring=80,opacity=84,
         wave_height=88,wave_step=92,wave_phase=96)
STRIDE=64
RADIUS=40.0
RECOVERY_TICKS=ACTOR_HZ
NATIVE=elf_reader(elf_path(ROOT))[2]
JUMP=lambda p:struct.pack('<2I',(2<<26)|(p>>2),0)
F=dict(actor=0,target=4,progress=8,hp=12,lock_target=16,x=20,y=24,z=28,
       corpse_x=32,corpse_y=36,corpse_z=40,recovering=44,recovery_ticks=48,
       revives=52,insufficient=56)
HOOKS=(start.HOOK,contact.PROTECTED,feed.DAMAGE_ENTRY,A(0x1D4F30),A(0x1E0290))
WRAPPERS=(FRAME,CONTACT,DAMAGE,COMMAND,REQUEST)
# These native code dependencies own queue reset, get-up choice/completion,
# health rows and animation timing. Their bytes are not rewritten.
DEPENDENCIES=((A(0x1E23D0),0x1E0),(A(0x1EA920),0x410),(A(0x1DC2D0),0x78),
              (A(0x1C47A8),0x110),(A(0x204DB0),0x48),(A(0x1E02A8),0x68),
              (A(0x1EA1A0),0xF8),(A(0x1210D8),0x90),(A(0x120AB0),0x30),(A(0x120B80),0x20))

def save(a):
    fusion.save(a)
    a.r(16,8,0);a.i(63,8,29,0x290)
    a.r(18,8,0);a.i(63,8,29,0x298)

def restore(a,result=None):
    if result is not None:a.i(31,result,29,fusion.OFFSETS[2])
    a.i(55,8,29,0x290);a.r(17,0,8)
    a.i(55,8,29,0x298);a.r(19,0,8)
    fusion.restore(a)

def pointer(a,r,size,fail):fusion.pointer(a,r,size,fail)

def gate():
    """Installed identity/lifecycle only, valid even during native role aliases."""
    a=Assembler(GATE);core.gate(a,'no');a.li(8,CONTROL);a.lw(9,8)
    a.li(11,MAGIC);a.branch(5,9,11,'no');a.lw(9,8,4);a.lw(11,28,-22364)
    a.branch(5,9,11,'no');a.lw(9,8,8);a.branch(5,9,10,'no')
    a.li(8,part.CONTROL);a.lw(9,8);a.addiu(11,0,5);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no')
    a.li(8,A(0x333700));a.lw(9,8);a.branch(5,9,0,'no')
    a.li(8,A(0x2FEB38));a.lw(12,8);pointer(a,12,0x108,'no')
    a.lw(9,12);a.addiu(11,0,3);a.branch(5,9,11,'no')
    a.li(8,CONTROL);a.lw(9,8,12);a.addiu(11,0,policy.FFA);a.branch(4,9,11,'no')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr();return a.finish()

def actor():
    """Physical a0 -> registered present actor v0, native HP row v1.

    Never trusts the transient physical ID inside an aliased native actor.
    Does not impose HP/action eligibility; recovery predicates use this too.
    """
    a=Assembler(ACTOR);a.li(8,CONTROL);a.lw(9,8,8);a.r(0x2B,9,4,9);a.branch(4,9,0,'no')
    a.r(0,12,0,4,6);a.li(8,ROWS);a.r(0x2D,12,12,8);a.lw(2,12)
    pointer(a,2,0x1600,'no');a.r(0,9,0,4,2);a.li(8,core.POINTERS);a.r(0x2D,8,8,9)
    a.lw(8,8);a.branch(5,8,2,'no')
    a.li(8,part.CONTROL);a.lw(9,8,12);a.lw(11,8,16);a.r(0x27,11,11,0)
    a.r(0x24,9,9,11);a.addiu(11,0,1);a.r(4,11,4,11);a.r(0x24,9,9,11);a.branch(4,9,0,'no')
    a.lw(9,2,0x994);a.i(11,8,9,5);a.branch(4,8,0,'no')
    a.lw(8,2,0x998);a.r(0x2B,8,9,8);a.branch(4,8,0,'no')
    a.r(0,3,0,9,7);a.r(0,8,0,9,5);a.r(0x2D,3,3,8)
    a.r(0,8,0,9,2);a.r(0x2D,3,3,8);a.r(0x2D,3,3,2);a.addiu(3,3,0x9E4)
    a.jr();a.label('no');a.move(2,0);a.move(3,0);a.jr();return a.finish()

def predicate():
    """Actual actor pointer a0 -> recovering Boolean v0. Leaf-owned locks only."""
    a=Assembler(PREDICATE);save(a);a.move(16,4);a.call(GATE);a.branch(4,2,0,'no')
    a.li(17,ROWS);a.li(8,CONTROL);a.lw(18,8,8);a.move(19,0)
    a.label('scan');a.lw(8,17);a.branch(4,8,16,'found');a.addiu(17,17,STRIDE)
    a.addiu(19,19,1);a.branch(5,19,18,'scan');a.jump('no')
    a.label('found');a.lw(8,17,F['recovering']);a.branch(4,8,0,'no')
    a.move(4,19);a.call(ACTOR);a.branch(4,2,0,'no');a.lw(8,3);a.branch(6,8,0,'no')
    a.addiu(2,0,1);a.jump('return');a.label('no');a.move(2,0)
    a.label('return');restore(a,2);a.jr();return a.finish()

def stable(a,actor,row,offsets,fail):
    """Squared displacement <=4 from channel start; NaN and infinity rejected."""
    a.emit((17<<26)|(4<<21)|(0<<16)|(0<<11))
    for native,stored in zip((16,20,24),offsets):
        a.i(49,1,actor,native);a.i(49,2,row,stored)
        a.emit((17<<26)|(16<<21)|(2<<16)|(1<<11)|(1<<6)|1)
        a.emit((17<<26)|(16<<21)|(1<<16)|(1<<11)|(1<<6)|2)
        a.emit((17<<26)|(16<<21)|(1<<16)|(0<<11)|(0<<6)|0)
    a.li(8,0x40800000);a.emit((17<<26)|(4<<21)|(8<<16)|(2<<11))
    a.emit((17<<26)|(16<<21)|(2<<16)|(0<<11)|0x36)
    a.branch(17,8,0,fail)

def close(a,source,target,fail):
    a.emit((17<<26)|(4<<21)|(0<<16)|(0<<11))
    for off in (16,20,24):
        a.i(49,1,source,off);a.i(49,2,target,off)
        a.emit((17<<26)|(16<<21)|(2<<16)|(1<<11)|(1<<6)|1)
        a.emit((17<<26)|(16<<21)|(1<<16)|(1<<11)|(1<<6)|2)
        a.emit((17<<26)|(16<<21)|(1<<16)|(0<<11)|(0<<6)|0)
    a.li(8,CONTROL);a.i(49,2,8,CFG['radius_squared'])
    a.emit((17<<26)|(16<<21)|(2<<16)|(0<<11)|0x36);a.branch(17,8,0,fail)

def channel_action(a,fail,*,pending=False):
    """t0 native action: ordinary locomotion 11..26 or the idle taunt 67.

    Native idle handler 1EE968 requests 67 after 90 idle updates; 1ECFC0
    plays animation 385. Pending safe transitions must also be admitted so
    starting/stopping movement or entering/leaving that taunt never resets.
    """
    ready=f'channel_action{len(a.words)}'
    if pending:a.addiu(9,0,-1);a.branch(4,8,9,ready)
    a.addiu(9,8,-11);a.i(11,9,9,16);a.branch(5,9,0,ready)
    a.addiu(9,0,67);a.branch(5,8,9,fail);a.label(ready)

def eligible(a,actor,index,dead,fail,mobile=False):
    """Busy queues/resources and existing hit/bind state must be fully empty."""
    a.lw(8,actor,0x948)
    if dead:a.addiu(9,0,216);a.branch(5,8,9,fail)
    elif mobile:channel_action(a,fail)
    else:
        tag=f'idle{len(a.words)}';a.addiu(9,0,11);a.branch(4,8,9,tag)
        a.addiu(9,0,15);a.branch(5,8,9,fail);a.label(tag)
    for off in (2380,2388,2392,2396,2400):
        a.lw(8,actor,off)
        if mobile and not dead:channel_action(a,fail,pending=True)
        else:a.addiu(9,0,-1);a.branch(5,8,9,fail)
    for off in (3480,3500,3512,0xFE0):a.lw(8,actor,off);a.branch(5,8,0,fail)
    for flag in map(FLAG,(0xB,0xBE,0x94,0x125,0x126,0x135)):
        for bank in (0x1085,0x10AD):
            a.i(36,8,actor,bank+(flag>>3));a.i(12,8,8,1<<(flag&7));a.branch(5,8,0,fail)
    a.lw(8,actor,12);a.i(11,9,8,policy.ENGINE_ACTORS);a.branch(4,9,0,fail)
    a.r(0,9,0,8,2);a.li(11,core.MODELS);a.r(0x2D,11,11,9);a.lw(14,11)
    pointer(a,14,0x1670,fail);a.lw(8,actor,12);a.lw(9,14,16);a.branch(5,8,9,fail)
    a.lw(8,14,4);a.branch(4,8,0,fail);a.lw(8,14,8);a.branch(4,8,0,fail)
    # Explicitly reject a corpse whose character/model reload is in flight.
    tag=f'reload_done{len(a.words)}';a.i(11,8,index,2);a.branch(5,8,0,tag)
    a.addiu(8,index,-2);a.r(0,8,0,8,6);a.li(9,reloads.RECORDS);a.r(0x2D,8,8,9)
    a.lw(8,8,4);a.addiu(8,8,-1);a.i(11,8,8,2);a.branch(5,8,0,fail);a.label(tag)
    a.move(4,actor);a.call(fusion.RESERVED);a.branch(5,2,0,fail)
    # Native director bindings may precede the visible action change.
    tag=f'camera_done{len(a.words)}';active=tag+'_active'
    a.li(8,A(0x2FEBCC));a.lw(14,8);a.branch(4,14,0,tag);pointer(a,14,832,fail)
    a.lw(8,14,812);a.branch(5,8,0,active);a.lw(8,14,704);a.branch(4,8,0,tag)
    a.label(active);a.lw(8,actor,12);a.i(11,9,8,12);a.branch(4,9,0,fail)
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x2D,8,8,9);a.lw(8,8)
    for off in (768,772):a.lw(9,14,off);a.branch(4,8,9,fail)
    a.label(tag)

def tick(waves=True,quad_support=False,mobile=True):
    a=Assembler(TICK);save(a);a.call(GATE);a.branch(4,2,0,'reset_all')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,start.CONTROL);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x3900);a.branch(5,8,0,'done')
    a.li(8,A(0x3337C0));a.lw(8,8);a.addiu(9,0,1);a.branch(5,8,9,'done')
    a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'done')
    if waves:
        # One clock per active world update, shared by every corpse/viewport.
        # Rendering a second co-op view must not advance the animation twice.
        a.li(10,CONTROL);a.lw(8,10,CFG['wave_phase']);a.lw(9,10,CFG['wave_step'])
        a.r(0x21,8,8,9);a.i(12,8,8,0xFFFF);a.sw(8,10,CFG['wave_phase'])
    a.li(16,CONTROL);a.lw(17,16,8);a.move(18,0);a.li(19,ROWS)
    a.label('source');a.move(4,18);a.call(ACTOR);a.branch(4,2,0,'clear')
    a.move(20,2);a.move(21,3);a.lw(8,19,F['recovering']);a.branch(4,8,0,'not_recovering')
    a.lw(8,21);a.branch(6,8,0,'clear');a.lw(8,20,0x948)
    for act in (216,225,230):a.addiu(9,0,act);a.branch(4,8,9,'recovery_tick')
    a.jump('clear')
    a.label('recovery_tick');a.lw(8,19,F['recovery_ticks']);a.i(11,9,8,0x7FFF)
    a.branch(4,9,0,'next');a.addiu(8,8,1);a.sw(8,19,F['recovery_ticks']);a.jump('next')
    a.label('not_recovering');a.lw(8,21);a.branch(6,8,0,'clear')
    # Only a current human assignment may channel. This includes adopted CPU
    # teammates and both co-op seats, and excludes abandoned original bodies.
    a.lw(8,20,spectator.CPU_DRIVEN);a.branch(5,8,0,'clear')
    a.li(11,spectator.CONTROL);a.lw(8,11);a.li(9,spectator.MAGIC);a.branch(5,8,9,'clear')
    a.lw(8,11,takeover.F['version']);a.addiu(9,0,takeover.VERSION);a.branch(5,8,9,'clear')
    a.lw(8,11,spectator.FIELDS['manager']);a.lw(9,16,4);a.branch(5,8,9,'clear')
    if quad_support:
        # Four-seat ownership lives in a separate reservation. Do not extend the
        # packed two-seat arrays (the next words have unrelated meanings).
        import quad_controller as quad
        import quad_lifecycle as seats
        a.li(8,quad.CONTROL);a.lw(9,8);a.li(10,quad.MAGIC);a.branch(5,9,10,'two_seat_owner')
        a.lw(9,8,4);a.lw(10,16,4);a.branch(5,9,10,'clear')
        a.li(11,seats.CONTROL)
        for port in range(4):
            a.lw(8,11,seats.F['owned']+4*port);a.branch(4,8,18,'human')
        a.jump('clear');a.label('two_seat_owner')
    for port in range(2):
        nxt=f'port{port}';a.lw(8,11,takeover.F['human_ports']);a.i(12,8,8,1<<port);a.branch(4,8,0,nxt)
        a.lw(8,11,takeover.F['owned']+4*port);a.branch(4,8,18,'human');a.label(nxt)
    a.jump('clear');a.label('human')
    eligible(a,20,18,False,'clear',mobile=mobile)
    # Find a retained teammate in reach; first physical ID is deterministic if
    # several bodies overlap. The HP write prevents a second ally double-charge.
    a.move(22,0)
    a.label('body');a.branch(4,22,18,'next_body');a.r(0x26,8,22,18);a.i(12,8,8,1)
    a.branch(5,8,0,'next_body');a.move(4,22);a.call(ACTOR);a.branch(4,2,0,'next_body')
    a.move(23,2);a.move(24,3);a.lw(8,24);a.branch(7,8,0,'next_body')
    a.lw(8,24,4);a.branch(6,8,0,'next_body');eligible(a,23,22,True,'next_body')
    close(a,20,23,'next_body');a.jump('candidate')
    a.label('next_body');a.addiu(22,22,1);a.branch(5,22,17,'body');a.jump('clear')
    a.label('candidate');a.lw(8,16,16);a.lw(9,21,20);a.branch(1,9,0,'clear');a.r(0x2B,8,9,8)
    a.branch(4,8,0,'enough');a.addiu(8,0,1);a.sw(8,19,F['insufficient'])
    a.sw(0,19,F['progress']);a.sw(0,19,F['target']);a.jump('next')
    a.label('enough');a.sw(0,19,F['insufficient']);a.addiu(25,22,1)
    a.lw(8,19,F['target']);a.branch(5,8,25,'begin');a.lw(8,21);a.lw(9,19,F['hp']);a.branch(5,8,9,'begin')
    a.r(0,8,0,18,2);a.li(9,core.TABLE);a.r(0x2D,8,8,9);a.lw(26,8)
    a.lw(9,19,F['lock_target']);a.branch(5,26,9,'begin')
    # Admission always uses the corpse's live position above. A supported or
    # sliding KO body and its helper may move while remaining in reach;
    # never pin the interaction to either one's starting position.
    if not mobile:stable(a,20,19,(20,24,28),'begin')
    a.lw(8,19,F['progress']);a.addiu(8,8,1);a.sw(8,19,F['progress'])
    a.lw(9,16,20);a.r(0x2B,9,8,9);a.branch(5,9,0,'next')
    # Atomic commit on the EE thread: all eligibility and stock checks above
    # precede any debit or HP mutation. Native dispatch performs every reset.
    a.lw(8,21,20);a.lw(9,16,16);a.r(0x23,8,8,9);a.sw(8,21,20)
    a.lw(8,24,4);a.lw(9,16,CFG['health']);a.r(0x2B,10,8,9);a.branch(5,10,0,'health_ready')
    a.move(8,9);a.label('health_ready');a.sw(8,24)
    a.addiu(8,0,91);a.sw(8,23,0x964)
    a.r(0,8,0,22,6);a.li(9,ROWS);a.r(0x2D,8,8,9)
    a.addiu(9,0,1);a.sw(9,8,F['recovering']);a.sw(0,8,F['recovery_ticks'])
    a.sw(0,8,F['progress']);a.sw(0,8,F['target']);a.sw(0,8,F['insufficient'])
    a.lw(8,19,F['revives']);a.addiu(8,8,1);a.sw(8,19,F['revives'])
    a.sw(0,19,F['target']);a.sw(0,19,F['progress']);a.jump('next')
    a.label('begin');a.sw(25,19,F['target']);a.sw(0,19,F['progress']);a.lw(8,21);a.sw(8,19,F['hp'])
    a.r(0,8,0,18,2);a.li(9,core.TABLE);a.r(0x2D,8,8,9);a.lw(8,8);a.sw(8,19,F['lock_target'])
    for act,base in ((20,20),(23,32)):
        for native,off in zip((16,20,24),(base,base+4,base+8)):a.lw(8,act,native);a.sw(8,19,off)
    a.jump('next')
    a.label('clear')
    for field in ('target','progress','recovering','recovery_ticks','insufficient'):a.sw(0,19,F[field])
    a.label('next');a.addiu(18,18,1);a.addiu(19,19,STRIDE);a.branch(5,18,17,'source');a.jump('done')
    a.label('reset_all');a.li(19,ROWS)
    for i in range(policy.ENGINE_ACTORS):
        for field in ('target','progress','recovering','recovery_ticks','insufficient'):a.sw(0,19,i*STRIDE+F[field])
    a.label('done');restore(a);a.jr();data=a.finish();assert len(data)<FRAME-TICK;return data

def frame(previous):
    a=Assembler(FRAME);save(a);a.call(TICK);restore(a);a.jump(previous);return a.finish()

def command_prescan(a,previous):
    """Leave the command barrier early when PREDICATE must return 0.

    PREDICATE can return 1 only when the FIRST row whose actor equals a0 is
    recovering (it also needs the gate, the actor lookup and positive HP).
    Otherwise the full barrier ends in the continuation with every register
    restored, so jump there directly with every register as on entry: only
    t0..t2 are used, spilled and reloaded as full quadwords. They go into the
    frame slots save() fills next with the same values, so the full path starts
    from the identical machine and stack state. Reads only CONTROL and ROWS.
    """
    temporaries=(8,9,10)
    a.addiu(29,29,-fusion.FRAME)
    for reg in temporaries:a.i(31,reg,29,fusion.OFFSETS[reg])
    a.li(8,CONTROL);a.lw(9,8,8);a.i(11,10,9,PRESCAN_ROWS+1);a.branch(4,10,0,'full')
    a.li(8,ROWS)
    a.label('prescan');a.branch(4,9,0,'unprotected')
    a.lw(10,8);a.branch(4,10,4,'first_match')
    a.addiu(8,8,STRIDE);a.addiu(9,9,-1);a.jump('prescan')
    a.label('first_match');a.lw(10,8,F['recovering']);a.branch(5,10,0,'full')
    a.label('unprotected')
    for reg in temporaries:a.i(30,reg,29,fusion.OFFSETS[reg])
    a.addiu(29,29,fusion.FRAME);a.jump(previous)
    a.label('full')
    for reg in temporaries:a.i(30,reg,29,fusion.OFFSETS[reg])
    a.addiu(29,29,fusion.FRAME)

def barrier(base,previous,kind,prescan=False):
    a=Assembler(base)
    if prescan:
        assert kind=='command'
        command_prescan(a,previous)
    save(a)
    if kind=='contact':
        # Either side is protected: no recovery actor can inflict a contact.
        a.call(PREDICATE);a.branch(5,2,0,'blocked')
        a.lw(4,29,fusion.OFFSETS[5]);a.call(PREDICATE)
    else:a.call(PREDICATE)
    a.branch(4,2,0,'native')
    if kind=='request':
        a.lw(5,29,fusion.OFFSETS[5]);a.lw(4,29,fusion.OFFSETS[4])
        a.lw(8,4,0x948);a.addiu(9,0,216);a.branch(5,8,9,'getup')
        for act in (225,230):a.addiu(9,0,act);a.branch(4,5,9,'native')
        a.jump('blocked');a.label('getup')
        # Only the authored animation-complete branch can unlock recovery.
        a.lw(8,29,fusion.OFFSETS[31]);a.li(9,A(0x1EAAAC));a.branch(4,8,9,'completion')
        a.li(9,A(0x1EAC30));a.branch(5,8,9,'blocked');a.label('completion')
        for act in (11,15,17):a.addiu(9,0,act);a.branch(4,5,9,'idle')
        a.jump('blocked')
        a.label('idle');a.li(8,ROWS);a.li(9,CONTROL);a.lw(10,9,8)
        a.label('scan');a.lw(9,8);a.branch(4,9,4,'found');a.addiu(8,8,STRIDE)
        a.addiu(10,10,-1);a.branch(5,10,0,'scan');a.jump('blocked')
        a.label('found');a.lw(9,8,F['recovery_ticks']);a.li(10,CONTROL);a.lw(10,10,CFG['recovery'])
        a.r(0x2B,9,9,10);a.branch(5,9,0,'blocked')
        a.jump('native')
    a.label('blocked');a.addiu(2,0,1 if kind=='contact' else -1 if kind=='request' else 0)
    restore(a,2);a.jr();a.label('native');restore(a);a.jump(previous)
    data=a.finish();assert len(data)<0x800;return data

def draw():
    a=Assembler(DRAW);save(a);a.call(GATE);a.branch(4,2,0,'done')
    a.lw(17,28,-22176);pointer(a,17,832,'done');a.li(18,camera.SUCCESSOR_CONTROL+8)
    a.call(hud.ACTIVE);a.branch(4,2,0,'subject');a.li(19,hud.VIEWS);a.move(20,0)
    a.label('view')
    for off,desc in ((512,4),(516,8),(520,12),(524,16)):
        a.lw(8,17,off);a.lw(9,19,desc);a.branch(5,8,9,'next_view')
    a.lw(18,19,20);a.jump('subject');a.label('next_view');a.addiu(19,19,hud.VIEW_STRIDE)
    a.addiu(20,20,1);a.addiu(8,0,hud.MAX_VIEWS);a.branch(5,20,8,'view');a.jump('done')
    a.label('subject');a.lw(4,18);a.move(5,17);a.call(RING)
    a.call(ACTOR);a.branch(4,2,0,'done')
    a.r(0,8,0,4,6);a.li(9,ROWS);a.r(0x2D,16,8,9)
    a.lw(8,16,F['recovering']);a.branch(4,8,0,'channel');a.li(4,TEXT);a.jump('text')
    a.label('channel');a.lw(8,16,F['insufficient']);a.branch(4,8,0,'progress');a.li(4,TEXT+64);a.jump('text')
    a.label('progress');a.lw(8,16,F['target']);a.branch(4,8,0,'done');a.li(4,TEXT+128)
    a.label('text');a.lw(5,17,512);a.addiu(5,5,1792+8);a.r(0,5,0,5,4)
    a.lw(6,17,524);a.addiu(6,6,Y_ORIGIN+screen_y(-36));a.r(0,6,0,6,4)
    a.li(7,0x80A0FFFF);a.addiu(8,0,1);a.addiu(9,0,32);a.call(feed.TEXT)
    # Draw a proportional channel bar without changing any stock HUD option.
    a.lw(8,16,F['target']);a.branch(4,8,0,'done');a.lw(8,16,F['progress'])
    a.addiu(9,0,120);a.r(24,0,8,9);a.r(18,8,0);a.li(9,CONTROL);a.lw(9,9,20)
    a.r(27,0,8,9);a.r(18,6,0);a.lw(4,17,512);a.addiu(4,4,1792+8)
    a.lw(5,17,524);a.addiu(5,5,Y_ORIGIN+screen_y(-25));a.r(0x2D,6,6,4);a.addiu(7,5,3)
    for reg in (4,5,6,7):a.r(0,reg,0,reg,4)
    a.li(8,0x80A0FFFF);a.call(bars.RECT)
    a.label('done');restore(a);a.jr();data=a.finish();assert len(data)<TEXT-DRAW;return data

def program(previous,version=OPTIONS_VERSION):
    import teammate_revive_ring
    if version not in VERSIONS:raise ValueError('Unknown revival executable version')
    waves=version>=3
    pieces=[(GATE,gate()),(ACTOR,actor()),(PREDICATE,predicate()),(TICK,tick(waves,mobile=version>=5)),
            (FRAME,frame(previous[0])),(DRAW,draw())]
    pieces+=teammate_revive_ring.pieces(waves)
    for base,tail,kind in zip(WRAPPERS[1:],previous[1:],('contact','damage','command','request')):
        pieces.append((base,barrier(base,tail,kind,prescan=kind=='command' and version>=4)))
    pieces += list(zip(HOOKS,map(JUMP,WRAPPERS)))
    return pieces

def dependency_override(ram,address,expected):
    """Exact optional hook overlay for existing strict dependency validators."""
    if address not in HOOKS:return expected
    if struct.unpack_from('<I',ram,CONTROL)[0]!=MAGIC:return expected
    validate_memory(ram)
    i=HOOKS.index(address);previous=struct.unpack_from('<I',ram,CONTROL+32+4*i)[0]
    if expected[:8]!=JUMP(previous)[:len(expected[:8])]:
        raise ValueError(f'Revival continuation mismatch at {address:08X}')
    # Body Change is the only reviewed outer contact guard. validate_memory
    # has authenticated its entire program and this exact continuation.
    actual=bytes(ram[address:address+8]) if address==HOOKS[1] else JUMP(WRAPPERS[i])
    return actual[:len(expected)]+expected[8:]

@policy.matching_install
def validate_memory(ram):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(CONTROL)!=MAGIC:raise ValueError('Revival identity missing')
    version=u(CONTROL+24)
    if version not in VERSIONS:raise ValueError('Revival upgrade requires a newly prepared match')
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if (u(CONTROL+4),u(CONTROL+8))!=(manager,count) or count not in policy.ACTOR_COUNTS:
        raise ValueError('Revival capture identity mismatch')
    mode=u(policy.CONTROL+12) if u(policy.CONTROL)==policy.MAGIC else policy.TEAMS
    if u(CONTROL+12)!=mode or mode not in (policy.TEAMS,policy.COOP):raise ValueError('Revival mode changed')
    if u(CONTROL+16)>10000000 or u(CONTROL+16)%100000 or not 8<=u(CONTROL+20)<=1800:
        raise ValueError('Invalid revival preference values')
    radius,radius2=struct.unpack_from('<2f',ram,CONTROL+CFG['radius'])
    if not math.isfinite(radius) or not 5<=radius<=200 or struct.pack('<f',radius*radius)!=ram[CONTROL+CFG['radius_squared']:CONTROL+CFG['radius_squared']+4]:
        raise ValueError('Invalid revival radius')
    if (not 2500<=u(CONTROL+CFG['health'])<=100000 or not 8<=u(CONTROL+CFG['recovery'])<=300
        or u(CONTROL+CFG['ring']) not in (0,1) or u(CONTROL+CFG['opacity'])>128):
        raise ValueError('Invalid revival recovery or marker preference')
    if version>=3:
        height=struct.unpack_from('<f',ram,CONTROL+CFG['wave_height'])[0]
        if (not math.isfinite(height) or not 0<=height<=80 or u(CONTROL+CFG['wave_step'])>10923
            or u(CONTROL+CFG['wave_phase'])>65535):raise ValueError('Invalid revival wave preferences')
    previous=struct.unpack_from('<5I',ram,CONTROL+32)
    if previous[1] not in (fusion.CONTACT,coop.CONTACT) or previous[2]!=feed.DAMAGE:
        raise ValueError('Unknown revival contact/damage continuation')
    if previous[3]!=next(cave for entry,cave,*_ in contact.SPECS if entry==A(0x1D4F30)) or previous[4]!=camera.BODY:
        raise ValueError('Unknown revival command/body continuation')
    if previous[0]!=(coop.TICK if mode==policy.COOP else part.FRAME):
        import extra_intros
        if mode!=policy.TEAMS or previous[0]!=extra_intros.PRESET_READY:
            raise ValueError('Unknown revival frame continuation')
        extra_intros.validate_preset_ready(ram,manager,count)
    for p,b in program(previous,version):
        import four_player_mode
        b=four_player_mode.dependency_override(ram,p,b)
        import story_runtime
        b=story_runtime.dependency_override(ram,p,b)
        if ram[p:p+len(b)]!=b:
            if p==HOOKS[1]:
                import body_swap_runner as bodies
                expected_contact=story_runtime.dependency_override(ram,p,JUMP(bodies.PROTECTED))
                if ram[p:p+len(b)]==expected_contact:
                    if bodies.validate_memory(ram,previous_chain=False)!=CONTACT:
                        raise ValueError('Body Change revival continuation changed')
                    continue
            raise ValueError(f'Revival executable changed {p:08X}')
    for p,n in DEPENDENCIES:
        if ram[p:p+n]!=NATIVE(p,n):raise ValueError(f'Revival native dependency changed {p:08X}')
    for i in range(count):
        if u(ROWS+i*STRIDE)!=u(core.POINTERS+4*i):raise ValueError('Revival actor pointer changed')
    return previous

def base_view(ram):
    """Expose exact prior hooks to older validators, never applied to a match."""
    if struct.unpack_from('<I',ram,CONTROL)[0]!=MAGIC:return ram
    previous=validate_memory(ram);copy=bytearray(ram)
    for p,tail in zip(HOOKS,previous):copy[p:p+8]=JUMP(tail)
    # This is a dependency view of the unwrapped chain, not another installed
    # revival image. Prevent recursive overlay validation in old mode guards.
    struct.pack_into('<I',copy,CONTROL,0)
    return copy

@policy.matching_install
def build_memory(ram,settings=None,source='<prepared>'):
    options=preferences.validate_settings(settings or {})
    if not options[preferences.REVIVE_KEY]:
        if len(ram)==0x8000000 and struct.unpack_from('<I',ram,CONTROL)[0]==MAGIC:
            raise ValueError('Disabling installed revival requires a newly prepared match')
        return dict(source=str(source),blocks=[],status='REVIVAL DISABLED')
    if len(ram)!=0x8000000:raise ValueError('Revival requires original 128MiB BT3 RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    mode=u(policy.CONTROL+12) if u(policy.CONTROL)==policy.MAGIC else policy.TEAMS
    if mode==policy.FFA:return dict(source=str(source),blocks=[],status='REVIVAL NOT USED IN FREE FOR ALL')
    cost=options[preferences.REVIVE_COST_KEY]*100000
    channel=max(1,math.ceil(options[preferences.REVIVE_CHANNEL_KEY]*ACTOR_HZ))
    radius=struct.unpack('<f',struct.pack('<f',options['revive_radius']))[0]
    configured=struct.pack('<2f4I',radius,radius*radius,round(options['revive_health_bars']*10000),
                           math.ceil(options['revive_recovery_seconds']*ACTOR_HZ),int(options['show_revive_ring']),
                           round(options['revive_ring_opacity']*128))
    wave_options=struct.pack('<fI',options['revive_ring_wave_height'],round(options['revive_ring_wave_speed']*65536/ACTOR_HZ))
    if u(CONTROL)==MAGIC:
        previous=validate_memory(ram)
        if (u(CONTROL+12),u(CONTROL+16),u(CONTROL+20))!=(mode,cost,channel):
            raise ValueError('Revival preference changes require a newly prepared match')
        if ram[CONTROL+64:CONTROL+88]!=configured:raise ValueError('Revival preference changes require a newly prepared match')
        if u(CONTROL+24)==2:
            # Upgrade only an exact recognized flat release. Runtime actor,
            # channel, recovery and ownership records remain untouched.
            old=dict(program(previous,2));blocks=[]
            for p,b in program(previous):
                prior=old.get(p,b'')
                if any(ram[p+len(prior):p+len(b)]):raise ValueError('Revival wave expansion reservation occupied')
                if ram[p:p+len(b)]!=b:blocks.append((p,b))
            if any(ram[CONTROL+88:CONTROL+100]):raise ValueError('Revival wave control reservation occupied')
            blocks.extend(((CONTROL+88,wave_options+bytes(4)),(CONTROL+24,struct.pack('<I',OPTIONS_VERSION))))
            check=bytearray(ram)
            for p,b in blocks:check[p:p+len(b)]=b
            validate_memory(check)
            return dict(source=str(source),blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in blocks],
                        status='REVIVAL WAVE MARKER UPGRADED',control=CONTROL)
        if ram[CONTROL+88:CONTROL+96]!=wave_options:raise ValueError('Revival preference changes require a newly prepared match')
        return dict(source=str(source),blocks=[],status='REVIVAL VERIFIED',control=CONTROL)
    if any(ram[CODE:END]):raise ValueError('Revival code reservation occupied')
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if (count not in policy.ACTOR_COUNTS or u(core.MODE+8)!=manager or u(core.MODE+12)!=count
        or not 0x100000<=manager<0x7FFF000 or u(manager)!=2):raise ValueError('Captured revival world invalid')
    if u(part.CONTROL) not in (0,5) or (u(part.CONTROL+4),u(part.CONTROL+8))!=(manager,count):
        raise ValueError('Revival requires current participation masks')
    takeover.validate_memory(ram)
    previous=[]
    for p in HOOKS:
        if u(p)>>26!=2 or u(p+4):raise ValueError(f'Revival requires a known prior jump at {p:08X}')
        previous.append((u(p)&0x3FFFFFF)<<2)
    control=bytearray(0x100);struct.pack_into('<6I',control,0,MAGIC,manager,count,mode,cost,channel)
    struct.pack_into('<I',control,24,OPTIONS_VERSION);control[64:88]=configured
    control[88:96]=wave_options
    struct.pack_into('<5I',control,32,*previous)
    rows=bytearray(policy.ENGINE_ACTORS*STRIDE)
    for i in range(count):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<=0x8000000-0x1600 or u(actor)!=i:raise ValueError('Invalid revival actor')
        struct.pack_into('<I',rows,i*STRIDE,actor)
    texts=bytearray(192)
    for off,value in ((0,'GETTING UP'),(64,f'NEED {options[preferences.REVIVE_COST_KEY]} BLAST STOCKS'),(128,'REVIVING TEAMMATE')):
        b=localization.slot(value,64);texts[off:off+len(b)]=b
    pieces=program(previous)+[(CONTROL,bytes(control)),(ROWS,bytes(rows)),(TEXT,bytes(texts))]
    check=bytearray(ram)
    for p,b in pieces:check[p:p+len(b)]=b
    validate_memory(check)
    return dict(source=str(source),blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in pieces],
        control=CONTROL,status='OPTIONAL NATIVE TEAMMATE REVIVAL',
        scope=f'Remain within {radius:g} native units of a current allied KO216; movement and taunts retain progress, spend blast stocks once.',
        recovery=f'Stock get-up 225/230; invulnerable and command-locked for at least {math.ceil(options["revive_recovery_seconds"]*ACTOR_HZ)} active ticks and until its animation-complete native exit.',
        limitations=['Revival cannot resume a match after the native result has begun.',
                     'Existing hidden235, absent, consumed, busy, falling or out-of-reach bodies are ineligible.',
                     'Player/CPU ownership is retained, including bodies abandoned by spectator takeover.'])
