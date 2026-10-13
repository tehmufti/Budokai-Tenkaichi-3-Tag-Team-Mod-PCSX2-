"""Hand an actual tag victim back to the game's falling/recovery action.

Native action217 (1EA298) starts the fighter's own fall animation, applies
1DED28 gravity, resolves ground contact and accepts its normal recovery input.
A scoped receipt enables the native four-input stunned recovery for a surviving
tag victim, independent of remaining HP. The normal native automatic fallback,
KO and input handling remain unchanged; no borrowed attack events are run.
"""
from prototype import Assembler
import struct
from native_map import A, ACTOR_HZ, FLAG
import fresh_team_combat as core
import fusion_partner_lifecycle as full
import tag_team_rush as tag
import tag_rush_camera as camera
import beam_struggle as fp

BEGIN, STATUS, NATURAL = 0x06D93000, 0x06D94000, 0x06D95000
STATE, END = 0x06D95C00, 0x06D96000
STRIDE, LIMIT = 64, 10*ACTOR_HZ
ACTIVE, MANAGER, COUNT, TICKS = 32, 24, 28, 36
BANK, NATURAL_STATUS, HIT_HP = 40, 44, 48
HOOK = A(0x1C2EE0)
NATIVE_HOOK = struct.pack('<2I',0x0C000000|(A(0x1C2318)>>2),0x0040202D)
INSTALLED_HOOK = struct.pack('<2I',0x0C000000|(STATUS>>2),0x0040202D)
DOWN_ACTIONS = tuple(range(216,223))

FALL_ACTION = 217
SLAM_DOWN = 64


def hp_record(a,actor,out,fail):
    """Exact 1CE1B8 selected row; t0/t1/t2 scratch, no native call."""
    assert out not in (8,9,10) and actor not in (8,9,10)
    a.lw(8,actor,0x994);a.i(11,9,8,5);a.branch(4,9,0,fail)
    a.r(0,9,0,8,7);a.r(0,10,0,8,5);a.r(0x21,9,9,10)
    a.r(0,10,0,8,2);a.r(0x21,9,9,10);a.r(0x21,out,actor,9);a.addiu(out,out,0x9E4)


def code():
    """a0 exact captured victim row, a1 descriptor flags ->v0 accepted."""
    import tag_rush_scene as scene
    a=Assembler(BEGIN);tag.save(a);a.move(21,4);a.move(20,5)
    camera.emit_active(a,'no');a.li(8,scene.ROWS+2*scene.STRIDE)
    a.branch(5,21,8,'special_goku');scene.identity(a,21,'no','victim')
    a.li(8,tag.CONTROL);a.lw(8,8,tag.C['victim']);a.lw(9,21,scene.R['index'])
    a.branch(5,8,9,'no');a.jump('admitted')
    # Only the selected Early Goku/Piccolo sacrifice may admit an attacker.
    # Require the exact body/bank and recorded damage from the completed move;
    # other attackers and ordinary tags retain the victim-only contract.
    a.label('special_goku')
    import tag_rush_damage as damage
    import tag_rush_special_pair as special
    a.li(8,scene.ROWS);a.branch(5,21,8,'no');scene.identity(a,21,'no','goku')
    a.lw(8,21,scene.R['character']);a.branch(5,8,0,'no')
    a.li(8,tag.CONTROL);a.lw(9,8,tag.C['variant']);a.li(10,special.VARIANT);a.branch(5,9,10,'no')
    a.lw(9,8,tag.C['initiator']);a.lw(10,21,scene.R['index']);a.branch(5,9,10,'no')
    a.li(18,damage.STATE);a.lw(9,18);a.li(10,damage.MAGIC);a.branch(5,9,10,'no')
    for off in (4,8):
        a.lw(9,18,off);a.lw(10,8,off);a.branch(5,9,10,'no')
    a.li(10,1)
    for field in ('sacrifice','finalized'):
        a.lw(9,18,damage.C[field]);a.branch(5,9,10,'no')
    a.lw(9,18,damage.C['goku_loss']);a.branch(6,9,0,'no')
    a.lw(9,18,damage.C['goku_bank']);a.lw(10,22,0x994);a.branch(5,9,10,'no')
    a.label('admitted')
    # The restored own animation directory must precede the native entry.
    a.lw(8,21,scene.R['clip0']);a.lw(9,23,192);a.branch(5,8,9,'no')
    # Native low-HP recovery status is recomputed every frame. Keep a receipt
    # for this exact body so STATUS may enable that same native path only
    # throughout this one down-action chain. KO never acquires a receipt.
    a.lw(8,21,scene.R['index']);a.r(0,8,0,8,6);a.li(18,STATE);a.r(0x21,18,18,8)
    a.sw(0,18,ACTIVE);hp_record(a,22,19,'no');a.lw(8,19);a.branch(6,8,0,'enter')
    for off in range(0,24,4):a.lw(8,21,off);a.sw(8,18,off)
    a.li(8,tag.CONTROL)
    for dest,source in ((MANAGER,tag.C['manager']),(COUNT,tag.C['count'])):
        a.lw(9,8,source);a.sw(9,18,dest)
    a.lw(8,22,0x994);a.sw(8,18,BANK);a.lw(8,19,40);a.sw(8,18,NATURAL_STATUS)
    a.lw(8,19);a.sw(8,18,HIT_HP)
    a.sw(0,18,TICKS);a.li(8,1);a.sw(8,18,ACTIVE);a.sw(8,19,40)
    a.label('enter');a.move(4,22);a.li(5,FALL_ACTION);a.call(A(0x1E0290))
    a.move(4,22);a.call(A(0x1E23D0))
    # A scenario or native callback may have replaced the fighter. Never
    # write physics to a new form or override another requested transition.
    scene.identity(a,21,'no','after');a.lw(8,22,2376);a.li(9,FALL_ACTION)
    a.branch(5,8,9,'release')
    # +0xAC is the native vertical gravity accumulator (1DED28), Y down.
    # The slam begins faster; native gravity/terrain own every later update.
    fp.fconst(a,0,120.0/ACTOR_HZ);a.i(12,8,20,SLAM_DOWN)
    a.branch(4,8,0,'velocity');fp.fconst(a,0,360.0/ACTOR_HZ)
    a.label('velocity');a.i(57,0,22,0xAC)
    a.i(12,8,20,SLAM_DOWN);a.branch(4,8,0,'accepted')
    # Native217 calls1DE080(actor,6,5,7,0,deceleration): mode7 preserves
    # root+128 direction, while +152 speed decelerates naturally to zero.
    # Seed a single horizontal away impulse; native collision/arena handling
    # then owns travel. Never move the victim directly or add another hit.
    # The victim leaves the holder; a sacrifice Goku leaves Piccolo's beam.
    a.move(17,22);a.move(16,23);a.li(19,scene.ROWS);a.branch(5,21,19,'slam_row')
    a.li(19,scene.ROWS+scene.STRIDE);a.label('slam_row')
    scene.identity(a,19,'accepted','slam_source')
    for f,off in ((0,2384),(2,2392)):
        a.i(49,f,16,off);a.i(49,f+1,23,off);fp.fop(a,1,f,f,f+1)
    fp.fop(a,2,4,0,0);fp.fop(a,2,5,2,2);fp.fop(a,0,4,4,5)
    fp.fconst(a,5,.001);fp.fop(a,0x34,0,5,4);a.branch(17,8,0,'accepted')
    # EE SQRT reads Ft, unlike the usual MIPS Fs spelling. Normalize the
    # horizontal vector itself, not whichever value remains in f0.
    fp.fop(a,4,4,0,4);fp.fop(a,3,0,0,4);fp.fop(a,3,2,2,4)
    a.i(57,0,17,0x90);a.sw(0,17,0x94);a.i(57,2,17,0x98);a.sw(0,17,0x9C)
    fp.fconst(a,0,480.0/ACTOR_HZ);a.i(57,0,17,0xA8)
    a.label('accepted');a.li(2,1);a.jump('done')
    a.label('release');a.sw(0,18,ACTIVE);a.move(4,22);a.call(NATURAL)
    a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,result=2);a.jr()
    data=a.finish();assert BEGIN+len(data)<=STATUS;return data


def natural_code():
    """Recompute only the native A0C predicate from 1C2318; never touch HP."""
    a=Assembler(NATURAL);tag.save(a);a.move(16,4);hp_record(a,16,17,'done');a.sw(0,17,40)
    a.lw(8,17);a.li(9,10000);a.r(0x2A,8,8,9);a.branch(4,8,0,'done')
    a.call(A(0x20E108));a.i(12,8,2,0x80);a.branch(5,8,0,'done')
    for off in (3604,3608):a.lw(8,16,off);a.branch(7,8,0,'done')
    a.move(4,16);a.li(5,FLAG(6));a.call(A(0x1DAC78));a.branch(5,2,0,'done')
    a.li(8,1);a.sw(8,17,40)
    a.label('done');tag.restore(a);a.jr();data=a.finish()
    assert NATURAL+len(data)<=STATE;return data


def status_code():
    """One native per-actor status call, followed by an exact owned override.

    Native status is always called first. Therefore dropping a stale receipt
    never writes an old actor and automatically leaves its natural HP status.
    Pause returns before the override; no counter or timeout advances paused.
    """
    import tag_rush_scene as scene
    a=Assembler(STATUS);tag.save(a);a.move(16,4);a.call(A(0x1C2318));a.move(17,2)
    full.pointer(a,16,0x1600,'done');a.lw(8,16);a.i(11,9,8,10);a.branch(4,9,0,'done')
    a.r(0,8,0,8,6);a.li(21,STATE);a.r(0x21,21,21,8)
    a.lw(8,21,ACTIVE);a.branch(4,8,0,'done')
    a.li(19,tag.CONTROL);a.lw(8,19);a.li(9,tag.MAGIC);a.branch(5,8,9,'release')
    a.lw(8,21,MANAGER);a.lw(9,19,tag.C['manager']);a.branch(5,8,9,'release')
    a.lw(9,28,-22364);a.branch(5,8,9,'release')
    a.lw(8,21,COUNT);a.lw(9,19,tag.C['count']);a.branch(5,8,9,'release')
    a.li(9,core.MODE+4);a.lw(9,9);a.branch(5,8,9,'release')
    a.lw(8,19,tag.C['enabled']);a.branch(4,8,0,'release')
    scene.identity(a,21,'release','held');a.branch(5,22,16,'release')
    hp_record(a,22,20,'release');a.lw(8,22,0x994);a.lw(9,21,BANK)
    a.branch(5,8,9,'changed_bank')
    a.lw(8,20);a.branch(6,8,0,'release')
    a.lw(9,21,HIT_HP);a.r(0x2A,9,8,9);a.branch(5,9,0,'release')
    a.lw(8,22,2376)
    for action in DOWN_ACTIONS:a.li(9,action);a.branch(4,8,9,'down')
    a.jump('release')
    a.label('down');a.move(4,22);a.call(A(0x1DC2C0));a.branch(5,2,0,'done')
    a.lw(8,22,0x1000);a.branch(6,8,0,'release')
    a.lw(8,21,TICKS);a.addiu(8,8,1);a.sw(8,21,TICKS)
    a.i(11,9,8,LIMIT);a.branch(4,9,0,'release')
    a.lw(8,20,40);a.sw(8,21,NATURAL_STATUS)
    a.li(8,1);a.sw(8,20,40);a.jump('done')
    # Switching the actor's native reserve bank ends this receipt. Restore
    # only the last native-derived status for the previous exact bank.
    a.label('changed_bank');a.i(11,8,9,5);a.branch(4,8,0,'release')
    a.r(0,8,0,9,7);a.r(0,10,0,9,5);a.r(0x21,8,8,10)
    a.r(0,10,0,9,2);a.r(0x21,8,8,10);a.r(0x21,8,8,22)
    a.lw(9,21,NATURAL_STATUS);a.sw(9,8,0xA0C)
    a.label('release');a.sw(0,21,ACTIVE)
    a.label('done');tag.restore(a,result=17);a.jr();data=a.finish()
    assert STATUS+len(data)<=NATURAL;return data


def pieces():
    return [(BEGIN,code()),(STATUS,status_code()),(NATURAL,natural_code()),(STATE,bytes(END-STATE))]
