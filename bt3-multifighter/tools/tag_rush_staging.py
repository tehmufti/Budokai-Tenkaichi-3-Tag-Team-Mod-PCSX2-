"""Private airborne placements for the revised tag-rush finishers."""
import math
from native_map import A,ACTOR_HZ
from prototype import Assembler
import tag_team_rush as tag
import tag_rush_camera as camera
import tag_rush_safety as safety
import tag_rush_assets as assets
import tag_rush_choreography as choreography
import fusion_partner_lifecycle as full
import beam_struggle as fp

BASE,END=0x06D86800,0x06D88000
QUERY,APPLY=BASE,BASE+0x400
BEGIN,TICK=BASE+0xA00,BASE+0xE00
TABLE_OFFSET=0xAC
OUTGOING_HIP,FINAL_ROOT,SETTLE=272,288,304


def query_code():
    """a0 phase -> v0 immutable64byte record, or0. All other GPRs preserved."""
    a=Assembler(QUERY);camera.save(a)
    a.i(11,8,4,choreography.MAX_PHASES);a.branch(4,8,0,'no')
    a.li(8,tag.CONTROL);a.lw(16,8,tag.C['variant']);a.i(11,10,16,len(choreography.VARIANTS));a.branch(4,10,0,'no')
    a.lw(17,8,TABLE_OFFSET);full.pointer(a,17,8*len(choreography.VARIANTS),'no')
    a.li(10,assets.BASE);a.r(0x2B,11,17,10);a.branch(5,11,0,'no')
    a.li(10,assets.END-32);a.r(0x2B,11,10,17);a.branch(5,11,0,'no')
    a.r(0,9,0,16,3);a.r(0x21,8,17,9);a.lw(9,8,4)
    a.r(0x2B,10,4,9);a.branch(4,10,0,'no');a.i(11,10,9,choreography.MAX_PHASES+1)
    a.branch(4,10,0,'no');a.lw(8,8)
    a.r(0,9,0,4,6);a.r(0x21,2,8,9);full.pointer(a,2,64,'no')
    a.li(10,assets.BASE);a.r(0x2B,11,2,10);a.branch(5,11,0,'no')
    a.li(10,assets.END-64);a.r(0x2B,11,10,2);a.branch(5,11,0,'no')
    a.lw(9,2);a.i(11,10,9,2);a.branch(4,10,0,'no');a.jump('done')
    a.label('no');a.move(2,0);a.label('done');camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<=APPLY-QUERY;return data


def apply_code():
    """a0 role,a1 savedrow,a2 record,a3 sceneSTATE ->v0 success.

    Native mode0 does nothing. Custom mode keeps the stage-relative air height
    and samples terrain only to avoid hills/ceilings at each independent mark.
    XY offsets rotate with the shared cinematic yaw; metadata yaw is degrees,
    converted once to the game's radians. No clone or substitute actor exists.
    """
    a=Assembler(APPLY);camera.save(a);a.addiu(29,29,-0x60)
    a.move(16,4);a.move(17,5);a.move(18,6);a.move(19,7)
    a.i(11,8,16,3);a.branch(4,8,0,'no')
    for reg,size in ((17,256),(18,64),(19,160)):full.pointer(a,reg,size,'no')
    a.lw(8,18);a.branch(4,8,0,'yes');a.li(9,1);a.branch(5,8,9,'no')
    a.r(0,8,0,16,4);a.r(0x21,18,18,8);a.addiu(18,18,16)
    for ptr,offs in ((18,(0,4,8,12)),(19,(104,108,112,116,120,132))):
        for off in offs:
            a.lw(8,ptr,off);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,'no')
    a.i(49,12,19,132);a.call(A(0x11F588));a.i(57,0,29,0x40)
    a.i(49,12,19,132);a.call(A(0x11F620));a.i(57,0,29,0x44)
    a.i(49,0,18,0);a.i(49,1,18,8);a.i(49,2,29,0x40);a.i(49,3,29,0x44)
    fp.fop(a,2,4,0,3);fp.fop(a,2,5,1,2);fp.fop(a,0,4,4,5)
    fp.fop(a,2,5,1,3);fp.fop(a,2,6,0,2);fp.fop(a,1,5,5,6)
    a.i(49,6,19,104);fp.fop(a,2,4,4,6);fp.fop(a,2,5,5,6)
    a.i(49,0,19,112);a.i(49,1,19,120);fp.fop(a,0,4,4,0);fp.fop(a,0,5,5,1)
    a.i(57,4,29,0);a.i(57,5,29,8);a.lw(8,19,116);a.sw(8,29,4)
    a.li(8,0x3F800000);a.sw(8,29,12)
    # FLOOR only reports buried roots. Query actual terrain without grounding
    # the finisher: the whole combination must remain visibly airborne.
    a.li(8,fp.arena_bounds.STAGE);a.lw(20,8);full.pointer(a,20,68,'no')
    a.lw(20,20,64);full.pointer(a,20,12,'no')
    for i,off in enumerate(fp.terrain.QUERY_GLOBALS):a.lw(8,28,off);a.sw(8,29,0x20+4*i)
    a.i(49,12,20,4);a.move(4,29);a.call(safety.QUERY)
    for i,off in enumerate(fp.terrain.QUERY_GLOBALS):a.lw(8,29,0x20+4*i);a.sw(8,28,off)
    a.branch(4,2,0,'no')
    a.i(49,2,19,108);fp.fconst(a,1,choreography.MIN_CLEARANCE)
    fp.fop(a,2,1,1,2);fp.fop(a,1,3,0,1)  # Maximum safe Y above terrain.
    a.i(49,0,19,36);fp.fconst(a,1,choreography.AIR_HEIGHT)
    fp.fop(a,2,1,1,2);fp.fop(a,1,0,0,1)
    a.i(49,1,18,4);fp.fop(a,2,1,1,2);fp.fop(a,0,0,0,1)
    fp.fop(a,0x34,0,3,0);a.branch(17,8,0,'above_terrain');fp.fop(a,6,0,3)
    a.label('above_terrain');a.i(49,1,20,4);fp.fconst(a,4,20.)
    fp.fop(a,2,4,4,2);fp.fop(a,0,1,1,4)
    fp.fop(a,0x34,0,3,1);a.branch(17,8,1,'no')
    fp.fop(a,0x34,0,0,1);a.branch(17,8,0,'below_ceiling');fp.fop(a,6,0,1)
    a.label('below_ceiling');a.i(57,0,29,4)
    a.li(8,0x3F800000);a.sw(8,29,12)
    for off in range(0,16,4):a.lw(8,29,off);a.sw(8,17,FINAL_ROOT+off)
    # The victim supplies a stable airborne origin for custom camera shots.
    a.li(8,2);a.branch(5,16,8,'rotation')
    # Keep the camera origin at the common airborne plane when the final
    # slam sends the victim below it; its shot already tracks that motion.
    a.i(49,1,18,4);a.i(49,2,19,108);fp.fop(a,2,1,1,2)
    fp.fop(a,1,0,0,1);a.i(57,0,19,116)
    a.label('rotation')
    for off in range(0,16,4):a.lw(8,19,128+off);a.sw(8,29,16+off)
    a.i(49,0,18,12);fp.fconst(a,1,math.pi/180);fp.fop(a,2,0,0,1)
    a.i(49,1,19,132);fp.fop(a,0,0,0,1);a.i(57,0,29,20)
    a.lw(4,17,4);a.move(5,29);a.addiu(6,29,16);a.lw(8,17,8);a.lw(7,8,2596)
    a.call(A(0x1D7418));a.label('yes');a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');a.addiu(29,29,0x60);camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert APPLY+len(data)<=BEGIN;return data


def begin_code():
    """No args: retain real outgoing hip positions before a custom phase cut."""
    a=Assembler(BEGIN);camera.save(a);a.li(16,tag.MEMBERS_SAVE)
    a.lw(4,16,4);a.call(QUERY);a.branch(4,2,0,'no');a.lw(8,2)
    a.branch(4,8,0,'yes');a.move(21,2);a.lw(4,16,4);a.addiu(4,4,-1);a.call(QUERY);a.move(22,2)
    a.li(17,tag.MEMBERS_SAVE+0x100);a.move(18,0)
    a.label('role');a.lw(19,17,8);full.pointer(a,19,0x1700,'no')
    a.lw(20,19,3436+3*4);full.pointer(a,20,80,'no')
    for off in range(0,16,4):a.lw(8,20,64+off);a.sw(8,17,OUTGOING_HIP+off)
    a.li(10,1);a.branch(4,22,0,'settle_decided');a.lw(8,22);a.branch(4,8,0,'settle_decided')
    a.r(0,8,0,18,4);a.r(0x21,23,21,8);a.r(0x21,24,22,8)
    for off in (16,20,24,28):
        a.lw(8,23,off);a.lw(9,24,off);a.branch(5,8,9,'settle_decided')
    a.move(10,0);a.label('settle_decided');a.sw(10,17,SETTLE)
    a.addiu(17,17,0x200);a.addiu(18,18,1);a.li(8,3);a.branch(5,18,8,'role')
    a.label('yes');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert BEGIN+len(data)<=TICK;return data


def tick_code():
    """Blend only real root positions, retaining the authored limb poses."""
    a=Assembler(TICK);camera.save(a);a.addiu(29,29,-0x60)
    a.li(16,tag.MEMBERS_SAVE);a.lw(4,16,4);a.call(QUERY)
    a.branch(4,2,0,'no');a.lw(8,2);a.branch(4,8,0,'yes')
    a.lw(8,16,8);a.emit((17<<26)|(4<<21)|(8<<16)|(0<<11));a.emit((17<<26)|(20<<21)|(0<<11)|(0<<6)|32)
    fp.fconst(a,1,60/ACTOR_HZ);fp.fop(a,2,0,0,1)
    a.lw(8,16,4);a.li(9,4);a.branch(5,8,9,'short_blend');fp.fconst(a,1,24.)
    a.jump('blend_limit');a.label('short_blend');fp.fconst(a,1,12.)
    a.label('blend_limit')
    # An authored fall continues moving for the complete aftermath rather
    # than snapping to its down/away endpoint and hanging before recovery.
    a.lw(8,2,12);a.branch(4,8,0,'duration_ready');a.i(11,9,8,121)
    a.branch(4,9,0,'no');a.emit((17<<26)|(4<<21)|(8<<16)|(1<<11))
    a.emit((17<<26)|(20<<21)|(1<<11)|(1<<6)|32)
    a.label('duration_ready');fp.fop(a,3,0,0,1);fp.fconst(a,1,1.)
    fp.fop(a,0x34,0,1,0);a.branch(17,8,0,'curve');fp.fop(a,6,0,1)
    a.label('curve');fp.fop(a,2,2,0,0);fp.fconst(a,1,2.);fp.fop(a,2,0,0,1)
    fp.fconst(a,1,3.);fp.fop(a,1,0,1,0);fp.fop(a,2,0,0,2);a.i(57,0,29,0x40)
    a.li(17,tag.MEMBERS_SAVE+0x100);a.move(18,0)
    a.label('role');a.lw(8,17,SETTLE);a.branch(4,8,0,'next_role')
    a.lw(19,17,8);full.pointer(a,19,0x1700,'no')
    a.lw(20,19,3436+3*4);full.pointer(a,20,80,'no')
    for off in (0,4,8):
        # posedHip-currentRoot+finalRoot gives this frame's grounded hip.
        a.i(49,0,20,64+off);a.i(49,1,19,2384+off);fp.fop(a,1,2,0,1)
        a.i(49,3,17,FINAL_ROOT+off);fp.fop(a,0,2,2,3)
        a.i(49,3,17,OUTGOING_HIP+off);fp.fop(a,1,2,2,3)
        a.i(49,4,29,0x40);fp.fop(a,2,2,2,4);fp.fop(a,0,2,2,3)
        fp.fop(a,1,2,2,0);fp.fop(a,0,2,2,1);a.i(57,2,29,off)
    a.li(8,0x3F800000);a.sw(8,29,12)
    a.lw(4,17,4);a.move(5,29);a.addiu(6,19,2400);a.lw(7,19,2596);a.call(A(0x1D7418))
    a.move(4,19);a.call(A(0x24E2B0));a.move(4,19);a.call(A(0x24E3F8))
    a.label('next_role');a.addiu(17,17,0x200);a.addiu(18,18,1);a.li(8,3);a.branch(5,18,8,'role')
    a.label('yes');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');a.addiu(29,29,0x60);camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert TICK+len(data)<=END;return data


def pieces():return [(QUERY,query_code()),(APPLY,apply_code()),(BEGIN,begin_code()),(TICK,tick_code())]
