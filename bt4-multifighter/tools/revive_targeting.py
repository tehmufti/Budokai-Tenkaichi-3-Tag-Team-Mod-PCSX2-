"""Downed, revivable allies join human targeting without becoming combat enemies.

The normal selectors consult this read-only predicate. CPU target selection,
contact/damage exclusions and revival itself keep their existing rules. An
absent or stale installation always answers false, including native matches.
"""
import struct
from prototype import Assembler
from native_map import A, CRC, SERIAL
import battle_mode_policy as policy
import fresh_team_combat as core

# Between battle_camera_zoom and outnumbered; no native addresses are borrowed.
BASE, END = 0x06961000, 0x06964000
ELIGIBLE, CONTROL = BASE, BASE+0x1000
MAGIC, VERSION = 0x52565431, 1


def emit_check(a, viewer, candidate):
    """v0 = downed ally. Preserve every other register and the caller's RA.

    The cheap identity check avoids calling an uninstalled reservation. The
    helper repeats the full match/revival checks before dereferencing actors.
    """
    writer=a
    a=Assembler(writer.pc)
    done='revive_target_done'
    a.addiu(29,29,-0x30)
    for i,reg in enumerate((4,5,8,9,31)):a.i(63,reg,29,8*i)
    # Inputs may themselves live in a0/a1/t0/t1: copy before the guard.
    a.move(2,viewer);a.move(5,candidate);a.move(4,2)
    a.move(2,0);a.li(8,CONTROL);a.lw(8,8);a.li(9,MAGIC)
    a.branch(5,8,9,done);a.call(ELIGIBLE)
    a.label(done)
    for i,reg in enumerate((4,5,8,9,31)):a.i(55,reg,29,8*i)
    a.addiu(29,29,0x30)
    for word in struct.unpack('<'+'I'*len(a.words),a.finish()):writer.emit(word)


def eligible_code():
    import teammate_revive as revive
    saved=tuple(range(3,26))+(31,)
    a=Assembler(ELIGIBLE)
    # Enemy targets are the common per-update path. They need no native call
    # or stack traffic from this additional eligibility check.
    a.branch(4,4,5,'no_leaf');a.r(0x26,2,4,5);a.i(12,2,2,1);a.branch(5,2,0,'no_leaf')
    a.addiu(29,29,-0xC0)
    for i,reg in enumerate(saved):a.i(63,reg,29,i*8)
    a.move(16,4);a.move(17,5)
    a.li(18,CONTROL);a.lw(8,18);a.li(9,MAGIC);a.branch(5,8,9,'no')
    a.lw(8,18,4);a.addiu(9,0,VERSION);a.branch(5,8,9,'no')
    a.lw(8,18,8);a.lw(9,28,-22364);a.branch(5,8,9,'no')
    a.call(revive.GATE);a.branch(4,2,0,'no')
    a.li(8,core.MODE);a.lw(8,8,4);a.lw(9,18,12);a.branch(5,8,9,'no')
    for reg in (16,17):a.r(0x2B,9,reg,8);a.branch(4,9,0,'no')
    # ACTOR includes presence, fusion consumption, registered pointer, form
    # bounds and the tournament wrapper's permanent-elimination exclusion.
    a.move(4,16);a.call(revive.ACTOR);a.branch(4,2,0,'no')
    a.lw(8,2,0x1278);a.branch(5,8,0,'no')
    a.lw(8,3);a.branch(6,8,0,'no')
    a.move(4,17);a.call(revive.ACTOR);a.branch(4,2,0,'no')
    a.lw(8,3);a.branch(7,8,0,'no');a.lw(8,3,4);a.branch(6,8,0,'no')
    a.lw(8,2,0x948);a.addiu(9,0,216);a.branch(5,8,9,'no')
    # Hidden/unbound/reloading models are not selectable bodies.
    a.lw(8,2,12);a.i(11,9,8,policy.ENGINE_ACTORS);a.branch(4,9,0,'no')
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(19,8)
    revive.pointer(a,19,0x1670,'no')
    for off in (4,8):a.lw(8,19,off);a.branch(4,8,0,'no')
    a.addiu(2,0,1);a.jump('return')
    a.label('no');a.move(2,0)
    a.label('return')
    for i,reg in enumerate(saved):a.i(55,reg,29,i*8)
    a.addiu(29,29,0xC0);a.jr()
    a.label('no_leaf');a.move(2,0);a.jr()
    data=a.finish();assert len(data)<CONTROL-ELIGIBLE;return data


@policy.matching_install
def build_memory(ram,settings=None,source='<prepared>'):
    import teammate_revive as revive
    if len(ram)!=0x8000000:raise ValueError('Revival targeting requires full captured memory')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(revive.CONTROL)!=revive.MAGIC:return dict(blocks=[])
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if (u(revive.CONTROL+4),u(revive.CONTROL+8))!=(manager,count):
        raise ValueError('Revival targeting belongs to another match')
    if u(revive.CONTROL+12)==policy.FFA:return dict(blocks=[])
    if count not in policy.ACTOR_COUNTS:raise ValueError('Invalid revival targeting actor count')
    code=eligible_code();control=struct.pack('<4I',MAGIC,VERSION,manager,count)
    if u(CONTROL)==MAGIC:
        if ram[CONTROL:CONTROL+len(control)]!=control or ram[ELIGIBLE:ELIGIBLE+len(code)]!=code:
            raise ValueError('Revival targeting installation changed')
        return dict(blocks=[],control=CONTROL,status='REVIVABLE ALLY TARGETS VERIFIED')
    if any(ram[BASE:END]):raise ValueError('Revival targeting reservation occupied')
    pieces=((ELIGIBLE,code),(CONTROL,control))
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in pieces],
        status='REVIVABLE ALLIES IN NORMAL TARGET SELECTION',
        support={'capacity':count,'features':{'revive_targeting':[
            dict(address=ELIGIBLE,data_hex=code.hex())]}})
