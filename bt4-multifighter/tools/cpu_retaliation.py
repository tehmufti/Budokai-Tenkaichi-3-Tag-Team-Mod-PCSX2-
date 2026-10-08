"""Damage-driven target changes for living captured CPUs, installed offline.

Observe the reviewed kill-feed native-damage call so its original caller and
fatal attribution remain intact. Each CPU tracks damage per opposing attacker
over a bounded window. Target writes occur only after deferred damage processing
and outside special/transform/camera ownership, with a per-CPU cooldown.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import guest_killfeed as feed
import cinematic_admission as admission
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy

CODE, GATE, ACCUMULATE, SCENE_SAFE = 0x07460000, 0x07461000, 0x07462000, 0x07463000
APPLY, TICK, NATIVE = 0x07464000, 0x07467000, 0x07467E00
CONTROL, ROWS, MATRIX, END = 0x0746F000, 0x0746F100, 0x0746F400, 0x07470000
# One damage row per victim, one 8-byte cell per attacker, for every fighter the
# engine can hold (12 x 8 = 96 = 64 + 32). Three-a-side installs carry six-wide
# rows (48 = 32 + 16); layout() follows the build being emitted.
MAX_ACTORS, FRAME = policy.ENGINE_ACTORS, 0x160
ROW_STRIDE = MAX_ACTORS * 8
ROW_SHIFTS = policy.stride_shifts(ROW_STRIDE)
assert MATRIX + MAX_ACTORS * ROW_STRIDE <= END, 'Damage matrix overruns its reservation'


def layout():
    """(actors, row stride, row shifts) of the matrix for the build being emitted."""
    actors = policy.emitted_tables()
    return actors, actors * 8, policy.stride_shifts(actors * 8)
THRESHOLD, WINDOW, COOLDOWN = 2000, 90, 120
DEFERRED = (3480, 3500, 3512)


def feed_return():
    words=struct.unpack('<'+'I'*(len(feed.damage_code())//4),feed.damage_code())
    offsets=[i*4 for i,w in enumerate(words) if w==(3<<26)|(feed.DAMAGE_NATIVE>>2)]
    if len(offsets)!=1:raise ValueError('Expected one audited native call inside kill feed')
    return feed.DAMAGE+offsets[0]+8


def gate_code():
    a=Assembler(GATE);core.gate(a,'no')
    a.li(8,CONTROL);a.lw(9,8);a.branch(4,9,0,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no')
    a.li(8,feed.CONTROL);a.lw(9,8);a.branch(4,9,0,'no')
    a.lw(9,8,4);a.branch(5,9,11,'no');a.lw(9,8,8);a.branch(5,9,10,'no')
    a.li(8,core.PAIR+4);a.lw(9,8);a.branch(5,9,0,'no')
    a.li(8,A(0x333700));a.lw(9,8);a.branch(5,9,0,'no')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr();return a.finish()


def damage_code():
    a=Assembler(CODE);a.addiu(29,29,-FRAME);feed.save(a);a.i(63,31,29,feed.RETURN)
    # Only the exact normal kill-feed call has initialized F0/F4/F8/FC fields.
    # Fallback calls jump here with their original callerRA and bypass observation.
    a.li(8,feed_return());a.branch(5,31,8,'fallback')
    a.call(GATE);a.branch(4,2,0,'fallback')
    for own,parent in ((0xF0,0xF0),(0xF4,0xF4),(0xF8,0xF8),(0xFC,0xFC)):
        a.lw(8,29,FRAME+parent);a.sw(8,29,own)
    feed.restore(a);a.call(NATIVE);feed.save(a)
    a.lw(8,29,0xFC);a.branch(6,8,0,'done');a.lw(9,29,0xF8);a.lw(9,9)
    a.branch(1,9,0,'done');a.r(0x2B,10,9,8);a.branch(4,10,0,'done')
    a.r(0x23,6,8,9);a.lw(4,29,0xF0);a.lw(5,29,0xF4);a.call(ACCUMULATE)
    a.label('done');feed.restore(a);a.i(55,31,29,feed.RETURN);a.addiu(29,29,FRAME);a.jr()
    a.label('fallback');feed.restore(a);a.i(55,31,29,feed.RETURN)
    a.addiu(29,29,FRAME);a.jump(NATIVE)
    data=a.finish();assert len(data)<GATE-CODE;return data


def saved(a,regs,restore=False):
    for i,r in enumerate(regs):a.i(55 if restore else 63,r,29,i*8)


def matrix_row(a,out,physical):
    shifts=layout()[2]
    a.r(0,8,0,physical,shifts[0]);a.r(0,9,0,physical,shifts[1]);a.r(0x2D,8,8,9)
    a.li(out,MATRIX);a.r(0x2D,out,out,8)


def accumulate_code(free_for_all=False):
    a=Assembler(ACCUMULATE);regs=tuple(range(16,24))+(31,)
    a.addiu(29,29,-0x50);saved(a,regs)
    a.move(17,4);a.move(18,5);a.move(19,6);a.call(GATE);a.branch(4,2,0,'done')
    a.branch(6,19,0,'done')
    for r in (17,18):a.r(0x2B,8,r,10);a.branch(4,8,0,'done')
    if free_for_all:a.branch(4,17,18,'done')
    else:a.i(12,8,17,1);a.i(12,9,18,1);a.branch(4,8,9,'done')
    a.li(8,core.POINTERS);a.r(0,9,0,17,2);a.r(0x2D,9,9,8);a.lw(20,9)
    a.r(0,9,0,18,2);a.r(0x2D,9,9,8);a.lw(21,9)
    for actor,physical in ((20,17),(21,18)):
        a.branch(4,actor,0,'done');a.lw(8,actor);a.branch(5,8,physical,'done')
    a.lw(8,20,0x1278);a.addiu(9,0,1);a.branch(5,8,9,'done')
    a.li(8,core.TABLE);a.r(0,9,0,17,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.branch(4,8,18,'done')
    for actor in (20,21):
        a.move(4,actor);a.call(feed.ROW);a.branch(4,2,0,'done');a.lw(8,2);a.branch(6,8,0,'done')
    a.li(16,CONTROL);a.li(8,feed.CONTROL);a.lw(22,8,12)
    a.r(0,8,0,17,4);a.li(9,ROWS);a.r(0x2D,9,9,8)
    a.lw(8,9);a.branch(4,8,0,'ready');a.lw(8,9,4);a.r(0x23,8,22,8)
    a.lw(9,16,20);a.r(0x2B,8,8,9);a.branch(5,8,0,'done')
    a.label('ready');matrix_row(a,23,17);a.r(0,8,0,18,3);a.r(0x2D,23,23,8)
    a.lw(11,23,4);a.branch(4,11,0,'new');a.lw(8,23);a.r(0x23,8,22,8)
    a.lw(9,16,16);a.r(0x2B,8,8,9);a.branch(5,8,0,'add')
    a.label('new');a.sw(22,23);a.move(11,0)
    a.label('add');a.r(0x2D,11,11,19);a.li(9,1000000);a.r(0x2B,8,11,9)
    a.branch(5,8,0,'store');a.move(11,9)
    a.label('store');a.sw(11,23,4);a.lw(8,16,24);a.addiu(8,8,1);a.sw(8,16,24)
    a.label('done');saved(a,regs,True);a.addiu(29,29,0x50);a.jr()
    data=a.finish();assert len(data)<SCENE_SAFE-ACCUMULATE;return data


def scene_safe_code():
    a=Assembler(SCENE_SAFE);regs=(16,17,18,31)
    a.addiu(29,29,-0x30);saved(a,regs);a.move(17,4)
    a.call(A(0x23DBC0));a.branch(5,2,0,'no');a.move(16,0)
    a.label('actor');a.li(8,core.POINTERS);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(18,8)
    a.branch(4,18,0,'no');a.move(4,18);a.call(feed.ROW);a.branch(4,2,0,'no')
    a.lw(8,2);a.branch(6,8,0,'next')
    # Previous action+2384 persists at idle and is intentionally excluded.
    for offset in admission.ACTION_FIELDS:
        a.lw(8,18,offset)
        for first,length in ((183,5),(236,80)):
            a.addiu(9,8,-first);a.i(11,9,9,length);a.branch(5,9,0,'no')
    a.label('next');a.addiu(16,16,1);a.branch(5,16,17,'actor')
    a.addiu(2,0,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');saved(a,regs,True);a.addiu(29,29,0x30);a.jr()
    data=a.finish();assert len(data)<APPLY-SCENE_SAFE;return data


def clear_matrix(a,base):
    for i in range(layout()[0]):a.sw(0,base,i*8+4)


def apply_code(free_for_all=False):
    a=Assembler(APPLY);regs=tuple(range(16,24))+(31,)
    a.addiu(29,29,-0x60);saved(a,regs);a.call(GATE);a.branch(4,2,0,'inactive')
    a.move(17,10);a.move(4,17);a.call(SCENE_SAFE);a.branch(4,2,0,'blocked')
    a.li(8,feed.CONTROL);a.lw(18,8,12);a.move(16,0)
    a.label('victim');matrix_row(a,20,16)
    a.li(8,core.POINTERS);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(19,8)
    a.branch(4,19,0,'clear');a.lw(8,19);a.branch(5,8,16,'clear')
    a.lw(8,19,0x1278);a.addiu(9,0,1);a.branch(5,8,9,'clear')
    a.move(4,19);a.call(feed.ROW);a.branch(4,2,0,'clear');a.lw(8,2);a.branch(6,8,0,'clear')
    a.lw(8,19,0x948);a.i(11,9,8,4);a.branch(5,9,0,'next_victim')
    for offset in DEFERRED:a.lw(8,19,offset);a.branch(5,8,0,'next_victim')
    a.li(8,ROWS);a.r(0,9,0,16,4);a.r(0x2D,8,8,9);a.lw(9,8)
    a.branch(4,9,0,'search');a.lw(9,8,4);a.r(0x23,9,18,9)
    a.li(8,CONTROL);a.lw(8,8,20);a.r(0x2B,8,9,8);a.branch(5,8,0,'clear')
    a.label('search');a.addiu(21,0,-1);a.move(22,0);a.move(23,0)
    a.label('candidate');a.r(0,8,0,23,3);a.r(0x2D,11,20,8);a.lw(12,11,4)
    a.branch(4,12,0,'next_candidate');a.lw(8,11);a.r(0x23,8,18,8)
    a.li(9,CONTROL);a.lw(9,9,16);a.r(0x2B,8,8,9);a.branch(4,8,0,'expired')
    if free_for_all:a.branch(4,16,23,'clear_candidate')
    else:a.i(12,8,16,1);a.i(12,9,23,1);a.branch(4,8,9,'clear_candidate')
    a.li(8,core.TABLE);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.branch(4,8,23,'clear_candidate')
    a.li(8,core.POINTERS);a.r(0,9,0,23,2);a.r(0x2D,8,8,9);a.lw(4,8)
    a.branch(4,4,0,'clear_candidate');a.lw(8,4);a.branch(5,8,23,'clear_candidate')
    a.call(feed.ROW);a.branch(4,2,0,'clear_candidate');a.lw(8,2);a.branch(6,8,0,'clear_candidate')
    a.li(8,CONTROL);a.lw(8,8,12);a.r(0x2B,8,12,8);a.branch(5,8,0,'next_candidate')
    a.r(0x2B,8,22,12);a.branch(4,8,0,'next_candidate');a.move(21,23);a.move(22,12)
    a.jump('next_candidate')
    a.label('expired');a.li(8,CONTROL);a.lw(9,8,32);a.addiu(9,9,1);a.sw(9,8,32)
    a.label('clear_candidate');a.r(0,8,0,23,3);a.r(0x2D,8,20,8);a.sw(0,8,4)
    a.label('next_candidate');a.addiu(23,23,1);a.branch(5,23,17,'candidate')
    a.branch(1,21,0,'next_victim')
    a.li(8,core.TABLE);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.sw(21,8)
    a.li(8,ROWS);a.r(0,9,0,16,4);a.r(0x2D,8,8,9);a.addiu(9,0,1)
    a.sw(9,8);a.sw(18,8,4);a.sw(21,8,12);a.lw(9,8,8);a.addiu(9,9,1);a.sw(9,8,8)
    a.li(8,CONTROL);a.lw(9,8,28);a.addiu(9,9,1);a.sw(9,8,28)
    a.label('clear');clear_matrix(a,20)
    a.label('next_victim');a.addiu(16,16,1);a.branch(5,16,17,'victim');a.jump('done')
    a.label('blocked');a.li(8,CONTROL);a.lw(9,8,36);a.addiu(9,9,1);a.sw(9,8,36);a.jump('done')
    a.label('inactive');a.li(8,MATRIX)
    actors=layout()[0]
    for i in range(actors*actors):a.sw(0,8,i*8+4)
    a.li(8,ROWS)
    for i in range(actors):a.sw(0,8,i*16)
    a.label('done');saved(a,regs,True);a.addiu(29,29,0x60);a.jr()
    data=a.finish();assert len(data)<TICK-APPLY;return data


def tick_code():
    a=Assembler(TICK);a.addiu(29,29,-0x100);feed.save(a);a.i(63,31,29,feed.RETURN)
    feed.restore(a);a.call(feed.TICK);feed.save(a);a.call(APPLY)
    feed.restore(a);a.i(55,31,29,feed.RETURN);a.addiu(29,29,0x100);a.jr()
    data=a.finish();assert len(data)<NATIVE-TICK;return data


def payloads(native):
    original=native(feed.DAMAGE_ENTRY,8)
    return [(CODE,damage_code()),(GATE,gate_code()),(ACCUMULATE,accumulate_code()),
            (SCENE_SAFE,scene_safe_code()),(APPLY,apply_code()),(TICK,tick_code()),
            (NATIVE,original+struct.pack('<2I',(2<<26)|((feed.DAMAGE_ENTRY+8)>>2),0))]


def build_memory(ram,config=None,source='<offline-memory>',*,threshold=THRESHOLD,window=WINDOW,cooldown=COOLDOWN):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB captured EE RAM')
    for value,minimum,maximum in ((threshold,1,1000000),(window,1,3600),(cooldown,0,3600)):
        if type(value) is not int or not minimum<=value<=maximum:raise ValueError('Invalid retaliation timing/damage setting')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if (count not in ACTOR_COUNTS or u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.MODE+12)!=count
            or not 0x100000<=manager<len(ram)-0x1000 or u(manager)!=2 or u(core.PAIR+4)):
        raise ValueError('Requires active captured4/6 match with restored physical IDs')
    if (u(feed.CONTROL),u(feed.CONTROL+4),u(feed.CONTROL+8))!=(1,manager,count):
        raise ValueError('Requires the active captured kill-feed attribution service')
    if any(ram[CODE:END]):raise ValueError('CPU retaliation reservation occupied')
    _,_,native=elf_reader(elf_path(ROOT))
    for p,data in feed.payloads(native):
        if ram[p:p+len(data)]!=data:raise ValueError(f'Kill-feed implementation changed:{p:08X}')
    for pc in feed.ATTRIBUTION:
        if ram[pc-16:pc]!=native(pc-16,16):raise ValueError('Audited attacker callsite changed')
    if ram[feed.DAMAGE_ENTRY:feed.DAMAGE_ENTRY+8]!=struct.pack('<2I',(2<<26)|(feed.DAMAGE>>2),0):
        raise ValueError('Kill-feed damage hook changed')
    if ram[feed.TICK_CALL:feed.TICK_CALL+8]!=struct.pack('<I',(3<<26)|(feed.TICK>>2))+native(feed.TICK_CALL+4,4):
        raise ValueError('Kill-feed update call changed')
    actors=[]
    for i in range(count):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<len(ram)-0x1600 or (u(actor),u(actor+8))!=(i,i&1):
            raise ValueError('Captured physical/team identity mismatch')
        actors.append(actor)
    if len(set(actors))!=count:raise ValueError('Aliased actor pointers')
    control=bytearray(0x100);struct.pack_into('<6I',control,0,1,manager,count,threshold,window,cooldown)
    actors=layout()[0]
    rows=bytearray(actors*16)
    for i in range(actors):struct.pack_into('<I',rows,i*16+12,0xFFFFFFFF)
    pieces=payloads(native)+[(CONTROL,bytes(control)),(ROWS,bytes(rows)),(MATRIX,bytes(actors*actors*8)),
        (feed.DAMAGE_NATIVE,struct.pack('<2I',(2<<26)|(CODE>>2),0)),
        (feed.TICK_CALL,struct.pack('<I',(3<<26)|(TICK>>2)))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),
        status='BOUNDED DAMAGE-DRIVEN CPU RETALIATION; LIVE BEHAVIOR VALIDATION REQUIRED',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces],
        control=CONTROL,rows=ROWS,matrix=MATRIX,threshold=threshold,window_updates=window,cooldown_updates=cooldown,
        telemetry=dict(eligible_hits=CONTROL+24,switches=CONTROL+28,expired_windows=CONTROL+32,unsafe_updates=CONTROL+36),
        behavior=['Only living actors whose actual CPU flag equals1 can switch.',
                  'Actual HP damage accumulates separately for each living opposing non-target attacker.',
                  'Unknown/self/teammate/dead-source/fatal-victim events do not request a switch.',
                  'Existing native damage, fatal attribution, human input and camera owners are preserved.',
                  'Requests expire and target writes wait for shared cinematics/queued special or transform actions and own pending hits.'])


def build(source,**kwargs):return build_memory(read_ram(source),source=source,**kwargs)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    x=p.parse_args();m=build(x.source);x.out.write_text(json.dumps(m,indent=2)+'\n');print(f'{x.out}: {len(m["blocks"])} blocks')
