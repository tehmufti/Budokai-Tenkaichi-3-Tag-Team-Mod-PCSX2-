"""Shared rush camera ownership, proven by the live reciprocal participant pair.

The native hit actions outlive activation priority. Never infer their victim
from the lock-on target: both actors must agree on the current attack pair.
"""
import struct
from prototype import Assembler
import cinematic_policy as cinema
import fresh_team_combat as core

OWNER, CONTROL, END = 0x06BA0000, 0x06BAF000, 0x06BB0000
MAGIC = 0x52555331


def emit_hud_gate(a, hidden, prefix='rush_hud'):
    """Optional installed owner; caller saves registers, including ra.

    Query the live pair, not the previous frame's cinematic telemetry. This
    preference is independent of shared ultimates and shared transformations.
    """
    import story_cinematics as story
    story.emit_active(a,hidden,prefix+'_story')
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC)
    a.branch(5,9,11,prefix+'_done')
    a.call(OWNER);a.branch(5,2,0,hidden)
    a.label(prefix+'_done')


def owner(disabled_exit=True):
    """v0 the authored rush actor or 0, v1 1 if owned; everything else restored.

    With CONTROL+8 (enabled) zero every path below answers v0=v1=0 before any
    store other than its own frame, so disabled_exit answers first, without
    saving 28 registers or running the gates. The enabled path only enters with
    v0 holding that word; the body never reads v0 before writing it.
    disabled_exit=False emits the earlier bytes for the equivalence tests.
    """
    a=Assembler(OWNER)
    if disabled_exit:
        a.li(2,CONTROL);a.lw(2,2,8);a.branch(5,2,0,'enabled')
        a.move(3,0);a.jr()
        a.label('enabled')
    cinema.save(a);cinema.gate(a,'no');a.move(16,10)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(4,9,0,'no');a.move(18,0);a.move(21,0);a.move(22,0)
    a.label('scan');a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(19,8)
    a.branch(4,19,0,'next');a.lw(8,19,2376);a.addiu(9,8,-301);a.i(11,9,9,3);a.branch(4,9,0,'next')
    a.sw(8,29,224);a.lw(8,19,3732);a.branch(5,8,18,'next');a.lw(23,19,3736)
    a.r(0x2B,8,23,16);a.branch(4,8,0,'next');a.branch(4,23,18,'next')
    a.li(8,core.POINTERS);a.r(0,9,0,23,2);a.r(0x2D,8,8,9);a.lw(24,8)
    a.branch(4,24,0,'next');a.lw(8,24,2376);a.lw(9,29,224);a.addiu(9,9,12);a.branch(5,8,9,'next')
    a.lw(8,24,3732);a.branch(5,8,18,'next');a.lw(8,24,3736);a.branch(5,8,23,'next')
    for reg in (18,23):
        a.move(4,reg);a.call(cinema.continuity.LOOKUP);a.branch(4,3,0,'next')
    # All concurrent pairs keep advancing, even though one authored view wins.
    for reg in (18,23):
        a.addiu(8,0,1);a.r(4,8,reg,8);a.r(0x25,21,21,8)
    a.branch(5,22,0,'next');a.move(22,19)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,16,'scan')
    a.branch(4,22,0,'no');a.li(8,cinema.CONTROL);a.sw(21,8,cinema.ULTIMATE_MEMBERS)
    a.addiu(3,0,1);a.sw(3,8,cinema.ULTIMATE_KIND)
    a.move(2,22);a.jump('done')
    a.label('no');a.move(2,0);a.move(3,0)
    a.label('done');cinema.restore(a,skip=(2,3));a.jr()
    data=a.finish();assert len(data)<CONTROL-OWNER;return data


def build_memory(ram,enabled=False):
    if type(enabled) is not bool:raise ValueError('Rush cinematics must be Boolean')
    if any(ram[OWNER:END]):raise ValueError('Rush camera reservation occupied')
    manager=struct.unpack_from('<I',ram,core.ACTORS)[0]
    return dict(blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex())
        for p,b in ((OWNER,owner()),(CONTROL,struct.pack('<3I',MAGIC,manager,int(enabled))))])
