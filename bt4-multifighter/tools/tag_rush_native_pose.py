"""Own-character beam-clash poses without the native clash game state.

A reviewed charged-beam slot uses its own firing/charge clips. Other move
styles use the actual fighter's generic native clash pose364. Only animation
helpers run; director roots, damage, camera and native fight actions stay owned.
"""
from prototype import Assembler
from native_map import A, ACTOR_HZ
import tag_team_rush as tag
import tag_rush_camera as camera
import fusion_partner_lifecycle as full
import beam_struggle as fp
import beam_pose

BASE, END = 0x06D8E800, 0x06D91000
SELECT, ENTER, CHARGE_CHECK, PLAY, TICK = BASE, BASE+0x400, BASE+0x800, BASE+0xC00, BASE+0x1000
OWN_CLASH_POSE = 32
CHARGE_BEAM = 128
ACTIVE, CLIP, POINTER = 336, 340, 344
CLOCK, CHARGING, FIRE_CLIP = 348, 352, 356


def select_code():
    """a0 model ->v0 own native clash clip, or-1. No model writes."""
    a=Assembler(SELECT);camera.save(a);a.move(16,4)
    full.pointer(a,16,0x1700,'no');a.lw(17,16,2348);full.pointer(a,17,640,'no')
    beam_pose.emit_select(a,16,17,'beam')
    a.branch(1,2,0,'no')
    # Reviewed clash clips are0x80000040. Refuse a future altered pose which
    # would make1C3E60 decode against another fighter through24D178.
    a.move(17,2);a.move(4,2);a.call(A(0x1C4650));a.li(8,0x20000000)
    a.r(0x24,8,8,2);a.branch(5,8,0,'no');a.move(2,17)
    a.jump('done');a.label('no');a.li(2,-1)
    a.label('done');camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert SELECT+len(data)<=ENTER;return data


def enter_code():
    """a0role,a1capture row,a2descriptor ->0 borrowed,1 own pose,2 invalid."""
    a=Assembler(ENTER);tag.save(a);a.move(20,4);a.move(21,5);a.move(19,6)
    a.sw(0,21,ACTIVE);a.sw(0,21,CLOCK);a.sw(0,21,CHARGING);a.sw(0,21,FIRE_CLIP)
    a.lw(8,19,28);a.i(12,9,8,OWN_CLASH_POSE)
    a.branch(4,9,0,'borrowed');a.i(11,9,20,2);a.branch(4,9,0,'borrowed')
    a.li(9,2);a.r(4,9,20,9);a.r(0x24,8,8,9);a.branch(4,8,0,'borrowed')
    a.lw(22,21,4);a.lw(23,21,8);a.move(4,23);a.call(SELECT)
    a.branch(1,2,0,'no');a.move(18,2);a.sw(18,21,FIRE_CLIP)
    a.lw(8,19,28);a.i(12,8,8,CHARGE_BEAM);a.branch(4,8,0,'selected')
    a.li(8,364);a.branch(4,18,8,'selected');a.move(4,23);a.move(5,18);a.call(CHARGE_CHECK)
    a.branch(4,2,0,'selected');a.addiu(18,18,-3);a.li(8,1);a.sw(8,21,CHARGING)
    a.label('selected')
    # Undo the borrowed index0 entry before native own-bank decoding. The
    # original pose remains cached for native1C3E60's short smooth transition.
    a.lw(8,21,24);a.sw(8,23,192);a.sw(8,21,180)
    a.move(4,21);a.move(5,18);a.call(PLAY);a.branch(4,2,0,'no')
    a.li(8,1);a.sw(8,21,ACTIVE);a.sw(8,21,176)
    a.li(2,1);a.jump('done');a.label('borrowed');a.move(2,0);a.jump('done')
    a.label('no');a.li(2,2);a.label('done');tag.restore(a,2);a.jr()
    data=a.finish();assert ENTER+len(data)<=CHARGE_CHECK;return data


def charge_check_code():
    """a0 model,a1 firing clip ->v0 whether its complete safe charge exists.

    Native1FA498's jump table maps261→262→263→264. A primary rush instead
    keeps the native generic364 clash pose; do not guess a startup for it.
    """
    a=Assembler(CHARGE_CHECK);camera.save(a);a.move(16,4);a.move(19,5)
    for index,clip in enumerate((264,298,332)):
        a.li(8,clip);a.branch(4,19,8,'valid')
    a.jump('no');a.label('valid');a.addiu(17,19,-3)
    a.label('clip');a.r(0,8,0,17,2);a.r(0x21,8,16,8);a.lw(18,8,192)
    full.pointer(a,18,8,'no');a.move(4,17);a.call(A(0x1C4650))
    a.li(8,0x20000000);a.r(0x24,8,8,2);a.branch(5,8,0,'no')
    a.addiu(17,17,1);a.branch(5,17,19,'clip')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert CHARGE_CHECK+len(data)<=PLAY;return data


def play_code():
    """a0 row,a1 own clip ->v0 success; animation blend only, no attack state."""
    a=Assembler(PLAY);camera.save(a);a.move(16,4);a.move(17,5)
    a.lw(18,16,8);a.r(0,8,0,17,2);a.r(0x21,8,18,8);a.lw(19,8,192)
    full.pointer(a,19,8,'no');a.move(4,17);a.call(A(0x1C4650))
    a.li(8,0x20000000);a.r(0x24,8,8,2);a.branch(5,8,0,'no')
    a.sw(19,16,POINTER);a.sw(17,16,CLIP)
    a.lw(4,16,4);a.move(5,17);fp.fconst(a,12,.2);a.call(A(0x1C3E60))
    fp.fconst(a,0,1/(.2*ACTOR_HZ));a.i(57,0,18,3208)
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert PLAY+len(data)<=TICK;return data


def tick_code():
    """a0role,a1capture row ->0 borrowed,1 advanced,2 lost ownership."""
    a=Assembler(TICK);tag.save(a);a.move(21,5);a.lw(8,21,ACTIVE)
    a.branch(4,8,0,'borrowed');a.lw(22,21,4);a.lw(23,21,8)
    a.lw(8,21,CLIP);a.lw(9,22,2420);a.branch(5,8,9,'no')
    a.r(0,9,0,8,2);a.r(0x21,9,23,9);a.lw(9,9,192)
    a.lw(10,21,POINTER);a.branch(5,9,10,'no')
    a.lw(8,23,192);a.lw(9,21,24);a.branch(5,8,9,'no')
    a.lw(8,21,CLOCK);a.addiu(8,8,1);a.sw(8,21,CLOCK)
    a.lw(8,21,CHARGING);a.branch(4,8,0,'speed')
    a.lw(8,21,CLOCK);a.emit((17<<26)|(4<<21)|(8<<16)|(0<<11))
    a.emit((17<<26)|(20<<21)|(0<<11)|(0<<6)|32)
    fp.fconst(a,1,60.0/ACTOR_HZ);fp.fop(a,2,0,0,1)
    fp.fconst(a,1,90.);fp.fop(a,0x34,0,0,1);a.lw(18,21,FIRE_CLIP)
    a.branch(17,8,0,'desired');fp.fconst(a,1,60.);fp.fop(a,0x34,0,0,1)
    a.lw(18,21,FIRE_CLIP);a.addiu(18,18,-1);a.branch(17,8,0,'desired')
    a.lw(18,21,CLIP);a.lw(8,21,FIRE_CLIP);a.addiu(8,8,-3);a.branch(5,18,8,'desired')
    a.i(49,0,23,3192);a.i(49,1,23,2884);fp.fconst(a,2,60.0/ACTOR_HZ+1.)
    fp.fop(a,0,0,0,2);fp.fop(a,0x34,0,0,1);a.branch(17,8,1,'desired')
    a.lw(18,21,FIRE_CLIP);a.addiu(18,18,-2)
    a.label('desired');a.lw(8,21,CLIP);a.branch(4,8,18,'speed')
    a.move(4,21);a.move(5,18);a.call(PLAY);a.branch(4,2,0,'no')
    a.label('speed')
    # 1C4920 is the native animation-only loop helper. No fight-action/event
    # dispatcher, clash participants or native damage entries are invoked.
    fp.fconst(a,0,60.0/ACTOR_HZ);a.lw(8,21,CHARGING);a.branch(4,8,0,'speed_ready')
    a.lw(8,21,CLIP);a.lw(9,21,FIRE_CLIP);a.addiu(9,9,-1);a.branch(5,8,9,'speed_ready')
    a.i(49,0,23,2884);fp.fconst(a,1,1.);fp.fop(a,1,0,0,1)
    fp.fconst(a,1,(90.-60.)*ACTOR_HZ/60.);fp.fop(a,3,0,0,1)
    a.label('speed_ready');a.i(57,0,23,3200)
    a.move(4,22);a.move(5,0);a.call(A(0x1C4920))
    for fn in (0x24C958,0x24E2B0,0x24E3F8):a.move(4,23);a.call(A(fn))
    a.li(2,1);a.jump('done');a.label('borrowed');a.move(2,0);a.jump('done')
    a.label('no');a.li(2,2);a.label('done');tag.restore(a,2);a.jr()
    data=a.finish();assert TICK+len(data)<=END;return data


def pieces():return [(SELECT,select_code()),(ENTER,enter_code()),(CHARGE_CHECK,charge_check_code()),(PLAY,play_code()),(TICK,tick_code())]
