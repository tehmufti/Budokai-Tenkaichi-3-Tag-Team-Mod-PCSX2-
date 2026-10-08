"""Scenario-only cast changes, using existing seat, camera and AI ownership tables.

No actor identities, original roster slots or allocation pointers are exchanged.
An exit retires the body without inventing a kill; a handoff is published before
the former player body can leave. All functions authenticate the captured world.
"""
import struct
from prototype import Assembler
from native_map import A
import guest_killfeed as abi
import story_rules as rules
import story_runtime as story
import fresh_team_combat as core
import spectator_switch as spec
import spectator_takeover as seats
import quad_controller as pads
import quad_lifecycle as quad
import quad_viewports as views
import team_participation as part
import team_start_gate as start
import extra_specials as specials
import fresh_team_camera as camera

TRANSFER, RETIRE = rules.BASE+0x6000, rules.BASE+0x8000
RETIRED = story.CONTROL+112


def seat_table(a,fail,tag):
    # s5 table, s6 fields offset. s7=1 for the unified multi-view lifecycle.
    a.li(8,pads.CONTROL);a.lw(9,8);a.li(10,pads.MAGIC)
    a.branch(5,9,10,tag+'legacy');a.lw(9,8,4);a.lw(10,16,4);a.branch(5,9,10,fail)
    a.li(21,quad.CONTROL);a.addiu(23,0,1);a.jump(tag+'ready')
    a.label(tag+'legacy');a.li(21,spec.CONTROL);a.lw(9,21);a.li(10,spec.MAGIC);a.branch(5,9,10,fail)
    a.lw(9,21,spec.FIELDS['manager']);a.lw(10,16,4);a.branch(5,9,10,fail)
    a.lw(9,21,seats.F['version']);a.li(10,seats.VERSION);a.branch(5,9,10,fail);a.move(23,0)
    a.label(tag+'ready')


def transfer_code():
    # a0 zero-based controller, a1 physical destination. Does not require a KO.
    a=Assembler(TRANSFER);abi.prologue(a);story.guard(a,'no');a.move(24,4);a.move(25,5)
    a.i(11,8,24,4);a.branch(4,8,0,'no')
    seat_table(a,'no','table_')
    a.branch(4,23,0,'legacy')
    a.lw(8,21,quad.F['human_ports']);a.li(22,quad.F['owned']);a.jump('ports')
    a.label('legacy');a.i(11,8,24,2);a.branch(4,8,0,'no')
    a.lw(8,21,seats.F['human_ports']);a.li(22,seats.F['owned'])
    a.label('ports');a.branch(4,8,0,'cpu_only');a.addiu(9,0,1);a.r(4,9,24,9);a.r(0x24,9,9,8);a.branch(4,9,0,'no')
    a.jump('human_destination')
    a.label('cpu_only')
    # The in-game scenario browser also offers CPU Only. A scripted handoff
    # becomes a no-op there; the entrant resumes its saved CPU role when the
    # event ends. An absent numbered player in a human match is still an error.
    a.lw(9,16,8);a.r(0x2B,9,25,9);a.branch(4,9,0,'no');a.jump('yes')
    a.label('human_destination')
    # Never steal a second human's fighter, even if that human is spectating it.
    for port in range(4):
        nxt=f'seat{port}';a.i(12,9,8,1<<port);a.branch(4,9,0,nxt)
        a.li(9,port);a.branch(4,9,24,nxt);a.addiu(9,21,4*port);a.r(0x21,9,9,22);a.lw(9,9);a.branch(4,9,25,'no');a.label(nxt)
    a.lw(8,16,8);a.r(0x2B,8,25,8);a.branch(4,8,0,'no')
    # Resolve a dynamic index through the document's authenticated actor set.
    a.r(0,8,0,25,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(18,9)
    a.li(9,story.ACTORS);a.r(0x21,9,9,8);a.lw(9,9);a.branch(5,9,18,'no')
    a.lw(9,18,0x994);a.i(11,10,9,5);a.branch(4,10,0,'no')
    a.r(0,10,0,9,7);a.r(0,11,0,9,5);a.r(0x21,10,10,11);a.r(0,11,0,9,2);a.r(0x21,10,10,11)
    a.r(0x21,10,10,18);a.lw(9,10,0x9E4);a.branch(6,9,0,'no')
    a.li(9,RETIRED);a.lw(9,9);a.addiu(10,0,1);a.r(4,10,25,10);a.r(0x24,9,9,10);a.branch(5,9,0,'no')
    a.li(9,part.CONSUMED);a.lw(9,9);a.r(0x24,9,9,10);a.branch(5,9,0,'no')
    a.r(0,8,0,24,2);a.r(0x21,21,21,8);a.r(0x21,22,21,22);a.lw(20,22)
    a.branch(4,20,25,'yes');a.lw(9,16,8);a.r(0x2B,9,20,9);a.branch(4,9,0,'no')
    a.r(0,9,0,20,2);a.li(10,core.POINTERS);a.r(0x21,10,10,9);a.lw(19,10)
    a.addiu(10,0,1);a.sw(10,19,0x1278);a.sw(0,18,0x1278)
    for actor in (18,19):
        for off in (0x127C,0x1280,0x1284):a.sw(0,actor,off)
    # Keep the scenario event's entrance/recovery restoration consistent.
    for index,flag in ((20,1),(25,0)):
        a.r(0,9,0,index,2);a.li(10,story.ACTORS+0x100);a.r(0x21,10,10,9);a.li(11,flag);a.sw(11,10)
        a.li(10,start.CONTROL+0x40);a.r(0x21,10,10,9);a.sw(11,10)
    a.sw(25,22)
    a.branch(4,23,0,'legacy_publish')
    for field in ('held','watching','buttons'):a.sw(0,21,quad.F[field])
    a.r(0,9,0,24,2)
    for address in (views.SUBJECTS,pads.CONTROL+0x40):a.li(10,address);a.r(0x21,10,10,9);a.sw(25,10)
    a.jump('whitelist')
    a.label('legacy_publish')
    for field in ('held','watching','buttons'):a.sw(0,21,seats.F[field])
    a.lw(9,21,seats.F['view_side']);a.r(0,9,0,9,2);a.li(10,spec.CONTROL);a.r(0x21,10,10,9)
    a.addiu(11,25,1);a.sw(11,10,spec.FIELDS['lock'])
    a.li(10,camera.SUCCESSOR_CONTROL);a.r(0x21,10,10,9);a.sw(25,10,8);a.sw(18,10,0x30);a.addiu(11,0,1);a.sw(11,10,0x20)
    a.label('whitelist');a.li(9,specials.CONTROL);a.lw(10,9,20)
    a.addiu(11,0,1);a.r(4,11,20,11);a.r(0x27,11,11,0);a.r(0x24,10,10,11)
    a.addiu(11,0,1);a.r(4,11,25,11);a.r(0x25,10,10,11);a.sw(10,9,20)
    a.label('yes');a.addiu(8,0,1);a.i(63,8,29,abi.REG_OFFSET[2]);a.jump('done')
    a.label('no');a.i(63,0,29,abi.REG_OFFSET[2]);a.label('done');abi.epilogue(a)
    code=a.finish()
    if TRANSFER+len(code)>RETIRE:raise ValueError('Scenario seat transfer exceeds its reservation')
    return code


def emit_retire(a,index,fail,tag):
    story.current(a,index,fail)
    # Both legacy and four-seat tables may exist; reject a body still owned by
    # any participating player. Transfer control before staging their exit.
    a.li(11,pads.CONTROL);a.lw(12,11);a.li(8,pads.MAGIC);a.branch(4,8,12,tag+'quad')
    for control,fields,ports,route in ((spec.CONTROL,seats.F,2,'legacy'),(quad.CONTROL,quad.F,4,'quad')):
        a.label(tag+route)
        a.li(11,control);a.lw(12,11,fields['human_ports'])
        for port in range(ports):
            nxt=tag+str(control)+str(port);a.i(12,8,12,1<<port);a.branch(4,8,0,nxt)
            a.lw(8,11,fields['owned']+4*port);a.li(9,index);a.branch(4,8,9,fail);a.label(nxt)
        a.jump(tag+'admitted')
    a.label(tag+'admitted')
    a.li(8,RETIRED);a.lw(9,8);a.li(10,1<<index);a.r(0x25,9,9,10);a.sw(9,8)
    if index>=2:
        a.li(8,part.CONSUMED);a.lw(9,8);a.r(0x25,9,9,10);a.sw(9,8)
    # Leaders keep their mandatory native participation slots, but become
    # invisible, noncombatant zero-HP bodies. Never pass their bits to CONSUME.
    a.li(8,abi.CONTROL+spec.DEAD+4*index);a.addiu(9,0,1);a.sw(9,8)
    a.sw(0,19);a.sw(0,20,8)
    for off in (0x1278,0x127C,0x1280,0x1284):a.sw(0,18,off)
    for off,value in ((0x948,216),(0x94C,-1),(0x950,216),(0x954,-1),(0x958,-1),(0x95C,-1),(0x960,-1),(0x964,0)):
        a.li(8,value);a.sw(8,18,off)
    a.li(8,start.CONTROL+0x40+4*index);a.sw(0,8)
    a.li(8,story.ACTORS+0x100+4*index);a.sw(0,8)


def blocks():return [(TRANSFER,transfer_code())]
