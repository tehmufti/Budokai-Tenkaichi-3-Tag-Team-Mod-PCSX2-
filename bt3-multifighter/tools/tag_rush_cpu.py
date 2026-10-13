"""Offline CPU tags reuse the native ultimate candidate and decision pipeline.

Only ultimate readiness, its native decision, and the AI output tail are wrapped.
The native candidate categories, distances, difficulty roll, ultimate bias,
random calls and AI cadence are untouched. Full tag meters substitute for
Sparking/ultimate ki cost; they never grant real ki or enable a free ultimate.
"""
import struct
from prototype import Assembler
from native_map import A
import tag_team_rush as tag

BASE, END = 0x06DD0000, 0x06DE0000
IDENTIFY, ELIGIBLE, READY = BASE, BASE+0x1000, BASE+0x1800
POWER, PROBABILITY, COST, OUTPUT = BASE+0x2800, BASE+0x3000, BASE+0x3800, BASE+0x4000
DECIDE = BASE+0x4800
PAUSED_GATE, OUTPUT_IDENTITY = BASE+0x5800, BASE+0x6000
CURRENT_ACTION = BASE+0x7000
VICTIM_ELIGIBLE = BASE+0x7800
ULTIMATE = 0x224  # Native AI logical Charge + Ki attack + Down.
NETPLAY_CONTROL, NETPLAY_MAGIC = 0x07B01000, 0x4E504631


def identify_code(base=IDENTIFY, *, output=False):
    """a0 current AI logical role -> v0 captured CPU actor, v1 physical ID."""
    a=Assembler(base);tag.save(a);a.move(16,4)
    a.call(PAUSED_GATE if output else tag.GATE);a.branch(4,2,0,'no')
    a.li(8,NETPLAY_CONTROL);a.lw(9,8);a.li(10,NETPLAY_MAGIC);a.branch(5,9,10,'offline')
    a.lw(9,8,4);a.branch(5,9,0,'no');a.label('offline')
    # This runs within the native private AI slice, where only logical 0/1
    # are meaningful. Resolve through its authenticated captured alias pair.
    a.i(11,8,16,2);a.branch(4,8,0,'no');a.li(8,tag.core.PAIR)
    a.lw(9,8);a.branch(4,9,0,'direct');a.lw(9,8,4);a.branch(4,9,0,'direct')
    a.r(0,9,0,16,2);a.r(0x21,8,8,9);a.lw(17,8,8);a.lw(18,8,16);a.jump('check')
    a.label('direct');a.move(18,16);a.li(8,tag.core.POINTERS);a.r(0,9,0,16,2);a.r(0x21,8,8,9);a.lw(17,8)
    a.label('check');a.li(8,tag.CONTROL);a.lw(9,8,tag.C['count']);a.r(0x2B,9,18,9);a.branch(4,9,0,'no')
    tag.full.pointer(a,17,0x1600,'no');a.li(8,tag.core.POINTERS);a.r(0,9,0,18,2);a.r(0x21,8,8,9)
    a.lw(9,8);a.branch(5,9,17,'no');a.lw(9,17,0x1278);a.branch(4,9,0,'no')
    a.move(2,17);a.move(3,18);a.jump('done')
    a.label('no');a.move(2,0);a.li(3,-1)
    a.label('done');a.i(31,3,29,tag.full.OFFSETS[3]);tag.restore(a,2);a.jr()
    b=a.finish();assert len(b)<=ELIGIBLE-IDENTIFY;return b


def ready_code():
    """a0 AI logical role -> v0=1 only with a fully eligible three-person cast.

    A human teammate may be the candidate, but this is only permission to
    OFFER. The ordinary coordinator still requires that human's input.
    """
    a=Assembler(READY);tag.save(a);a.call(IDENTIFY);a.branch(4,2,0,'no');a.move(16,3)
    a.li(17,tag.CONTROL)
    for field in ('active','approaching'):
        a.lw(8,17,tag.C[field]);a.branch(5,8,0,'no')
    a.move(4,16);a.call(ELIGIBLE);a.branch(4,2,0,'no');a.move(18,3)
    a.r(0x26,8,16,18);a.i(12,8,8,1);a.branch(4,8,0,'no')
    a.li(19,tag.METERS);a.r(0,8,0,16,5);a.r(0x21,19,19,8)
    a.lw(20,17,tag.C['charge_ticks']);a.lw(8,19,tag.T['charge']);a.r(0x2B,8,8,20);a.branch(5,8,0,'no')
    a.lw(8,19,tag.T['inviter']);a.li(9,-1);a.branch(5,8,9,'no')
    a.move(4,18);a.call(VICTIM_ELIGIBLE);a.branch(4,2,0,'no')
    a.i(12,21,16,1);a.lw(22,17,tag.C['count'])
    a.label('scan');a.r(0x2B,8,21,22);a.branch(4,8,0,'no');a.branch(4,21,16,'next')
    a.move(4,21);a.call(ELIGIBLE);a.branch(4,2,0,'next');a.branch(5,3,18,'next')
    a.li(8,tag.METERS);a.r(0,9,0,21,5);a.r(0x21,8,8,9);a.lw(8,8,tag.T['charge'])
    a.r(0x2B,8,8,20);a.branch(4,8,0,'yes')
    a.label('next');a.addiu(21,21,2);a.jump('scan')
    a.label('yes');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();b=a.finish();assert len(b)<=POWER-READY;return b


def power_code(base=POWER,probability=False):
    a=Assembler(base);tag.save(a)
    if probability:
        # The final roll's Sparking modifier is borrowed only for ultimate,
        # never for Blast2 candidates selected by the same native function.
        a.lw(8,20,752);a.li(9,2);a.branch(5,8,9,'native')
    a.call(READY);a.branch(5,2,0,'done')
    a.label('native');a.i(30,4,29,tag.full.OFFSETS[4]);a.call(A(0x20B7C0))
    a.label('done');tag.restore(a,2);a.jr();b=a.finish();assert len(b)<=0x800;return b


def cost_code():
    # Exact two overwritten instructions: LW v0,0(v1); LW v1,0x10(sp).
    # Preserve the caller's stack/registers and all ordinary move costs.
    a=Assembler(COST);tag.save(a);a.lw(17,3);a.li(8,2);a.branch(5,16,8,'original')
    a.lw(4,20);a.call(READY);a.branch(4,2,0,'original');a.move(17,0)
    a.label('original');a.move(2,17);tag.restore(a,2);a.lw(3,29,0x10);a.jump(A(0x1B8ED0))
    b=a.finish();assert len(b)<=0x800;return b


def output_code():
    a=Assembler(OUTPUT);tag.save(a);a.move(16,4);a.move(17,5);a.move(22,2)
    # A manager-only native pause can still update AI. Keep consuming an
    # existing decision through it, while READY still refuses every new offer.
    a.call(OUTPUT_IDENTITY);a.branch(4,2,0,'native');a.move(18,3)
    a.li(19,tag.METERS);a.r(0,8,0,18,5);a.r(0x21,19,19,8)
    a.move(4,16);a.move(5,22);a.call(CURRENT_ACTION);a.branch(4,2,0,'ended')
    a.i(12,8,17,ULTIMATE);a.li(9,ULTIMATE);a.r(0x26,8,8,9);a.i(11,8,8,1)
    a.sw(8,19,tag.T['cpu_held'])
    a.lw(8,19,tag.T['cpu_consumed']);a.branch(5,8,0,'mask')
    a.lw(20,19,tag.T['cpu_ticket']);a.branch(4,20,0,'native')
    a.li(8,tag.core.TABLE);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(9,8)
    a.addiu(8,9,1);a.branch(5,8,20,'ended')
    # Convert the actual approved ultimate ACTION, not its original move's
    # controller script. That script can remain zero while it waits for the
    # original move's animation/state prerequisites, even after action63 is
    # selected. No new roll occurs here: DECIDE supplies exactly one ticket,
    # and CURRENT_ACTION proves that native AI really entered that action.
    # Brief hit-stun can retry while this same action remains current.
    a.move(4,16);a.call(READY);a.branch(4,2,0,'mask')
    a.sw(0,19,tag.T['cpu_ticket']);a.addiu(9,20,-1)
    a.sw(18,19,tag.T['inviter']);a.sw(9,19,tag.T['target'])
    a.li(8,tag.CONTROL);a.lw(9,8,tag.C['clock']);a.addiu(9,9,tag.REQUEST_SECONDS*tag.ACTOR_HZ)
    a.sw(9,19,tag.T['expiry']);a.li(9,1);a.sw(9,19,tag.T['cpu_consumed'])
    a.label('mask')
    a.i(12,8,17,0x220);a.li(9,0x220);a.branch(5,8,9,'publish')
    # Remove only Triangle/Down. Preserve charging and unrelated input axes.
    # Keep consuming the same held decision after timeout/start so it cannot
    # accidentally become the CPU's original ultimate on a later update.
    # Both 0x224 and its alternating 0x220 half-cycle belong to this same
    # consumed decision; zero input neither resets nor reopens the offer.
    a.li(8,~0x24);a.r(0x24,17,17,8);a.jump('publish')
    a.label('ended')
    for field in ('cpu_held','cpu_consumed','cpu_ticket'):a.sw(0,19,tag.T[field])
    a.label('publish');a.i(31,17,29,tag.full.OFFSETS[5])
    a.label('native');tag.restore(a);a.jump(A(0x208198))
    b=a.finish();assert len(b)<=DECIDE-OUTPUT;return b


def current_action_code():
    """a0 logical role, a1 native output context -> current action is63.

    1B6CD8 keeps its context in v0 through the output tail. Authenticate it
    against the currently bound private AI block before reading its stack.
    No pending tag decision survives an unrelated native action.
    """
    a=Assembler(CURRENT_ACTION);tag.save(a)
    a.i(11,8,4,2);a.branch(4,8,0,'no')
    a.lw(8,28,-0x5760);tag.full.pointer(a,8,0xA60,'no',temp=9,test=10)
    a.i(12,9,8,15);a.branch(5,9,0,'no')
    a.r(0,9,0,4,10);a.r(0,10,0,4,8);a.r(0x21,9,9,10)
    a.r(0,10,0,4,5);a.r(0x21,9,9,10);a.r(0x21,8,8,9);a.addiu(8,8,0x10)
    a.branch(5,8,5,'no');a.lw(9,8);a.branch(5,9,4,'no')
    a.lw(9,8,44);a.addiu(10,9,-1);a.i(11,10,10,8);a.branch(4,10,0,'no')
    a.r(0,9,0,9,3);a.r(0x21,8,8,9);a.lw(9,8,52);a.li(10,63);a.branch(5,9,10,'no')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();b=a.finish();assert CURRENT_ACTION+len(b)<=END;return b


def decide_code():
    """Keep the native roll/result; ticket one approved ultimate decision.

    Some native actions pulse their buttons repeatedly. A consumed decision
    cannot reopen invitations after a human declines or the offer expires.
    """
    a=Assembler(DECIDE);tag.save(a);a.move(16,4)
    a.call(A(0x1B8608));a.move(17,2);a.lw(4,16);a.call(IDENTIFY);a.branch(4,2,0,'done')
    a.move(18,3);a.li(19,tag.METERS);a.r(0,8,0,18,5);a.r(0x21,19,19,8)
    a.sw(0,19,tag.T['cpu_ticket']);a.branch(4,17,0,'done')
    a.lw(8,16,752);a.li(9,2);a.branch(5,8,9,'done')
    a.lw(4,16);a.call(READY);a.branch(4,2,0,'done')
    a.li(8,tag.core.TABLE);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(9,8);a.addiu(9,9,1)
    a.sw(9,19,tag.T['cpu_ticket'])
    a.sw(0,19,tag.T['cpu_held']);a.sw(0,19,tag.T['cpu_consumed'])
    a.label('done');a.move(2,17);tag.restore(a,2);a.jr()
    b=a.finish();assert DECIDE+len(b)<=PAUSED_GATE;return b


def _jal(p):return struct.pack('<I',0x0C000000|(p>>2))
def _jump(p):return struct.pack('<I',0x08000000|(p>>2))


def hooks():
    # 1BFC90 selects ordinary states7..9 or ultimate states10..12. Merely
    # adding slot2 to 1B8B40 is insufficient: ordinary action62 rejects it.
    return ((A(0x1BFD40),_jal(A(0x20B7C0)),_jal(POWER)),
            (A(0x1B8CC4),_jal(A(0x20B7C0)),_jal(POWER)),
            (A(0x1B8F9C),_jal(A(0x20B7C0)),_jal(PROBABILITY)),
            (A(0x1B8EC8),struct.pack('<2I',0x8C620000,0x8FA30010),_jump(COST)+bytes(4)),
            (A(0x1B8FA8),_jal(A(0x1B8608)),_jal(DECIDE)),
            (A(0x1B6CF8),_jump(A(0x208198)),_jump(OUTPUT)))


def pieces():
    return [(IDENTIFY,identify_code()),(ELIGIBLE,tag.eligible_code(ELIGIBLE,ai_alias=True)),
            (READY,ready_code()),(POWER,power_code()),(PROBABILITY,power_code(PROBABILITY,True)),
            (COST,cost_code()),(OUTPUT,output_code()),(DECIDE,decide_code()),
            (PAUSED_GATE,tag.gate_code(PAUSED_GATE,allow_manager_pause=True)),
            (OUTPUT_IDENTITY,identify_code(OUTPUT_IDENTITY,output=True)),
            (CURRENT_ACTION,current_action_code()),
            (VICTIM_ELIGIBLE,tag.eligible_code(VICTIM_ELIGIBLE,ai_alias=True,victim=True))]
