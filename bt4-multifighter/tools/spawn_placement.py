"""Plan an initial team formation using authored stage anchors and native geometry.

Version3 prefers a shallow V and searches compact alternatives on narrow maps,
checks complete footprints and body clearance, then commits once while held.
Historical payload/query/ready_manifest remain byte-stable for old archives.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import math
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from terrain_crossing_guard import fp, constant
import fresh_team_combat as core
import team_start_gate as start
import team_intro as intro
import fresh_memory
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy

CODE, QUERY, TRAMPOLINE = 0x07450000, 0x07453000, 0x0745D000
CONTROL, ROWS, END = 0x0745E000, 0x0745E100, 0x07460000
STRIDE, HOOK = 0x80, start.HOOK
ERRORS = {101: 'Captured identity changed', 102: 'Actors must remain idle and held',
          103: 'Native leader floor unavailable', 104: 'No nearby walkable spawn floor'}
# A fighter left its standing idle pose (native action 11) before the formation could be placed (P-1). The
# player's next step is a fresh match: this watcher stays stopped, so PCSX2 and Play start again (Spanish in
# localization.ES; {play} is this installation's launcher).
NOT_IDLE = ('One of the fighters was still moving when the extra fighters were placed, so this match could not be '
            'set up. '
            'Close PCSX2, start {play} again, then choose the teams again in character selection.')
SAVED = tuple(range(2, 26)) + (31,)


def query_code():
    """a0=XYZ vector, f12=top Y. Return v0=valid, f0=floor Y."""
    a=Assembler(QUERY); a.addiu(29,29,-0x90)
    a.i(63,16,29,0x70);a.i(63,31,29,0x78);a.i(57,20,29,0x80)
    a.move(16,4);fp(a,6,20,12)
    for off in (0,8):a.lw(8,16,off);a.sw(8,29,0x20+off);a.sw(8,29,0x40+off)
    a.i(57,20,29,0x24);constant(a,0,1)
    for off in (0x2C,0x34,0x3C):a.i(57,0,29,off)
    constant(a,0,.1)
    for off in (0x30,0x38):a.i(57,0,29,off)
    a.sw(0,29,0x4C);a.sw(0,29,0x54)
    a.addiu(4,29,0);a.addiu(5,29,0x20);a.addiu(6,29,0x30);a.call(A(0x230B38))
    # -1 forces23FF78's native global sector lookup at this X/Z. A copied
    # leader sector index is not assumed valid at the lateral spawn position.
    a.addiu(4,0,-1);a.addiu(5,29,0);a.addiu(6,29,0x40);fp(a,6,12,20)
    a.call(A(0x1B14C0));a.li(8,CONTROL);a.lw(9,8,16);a.addiu(9,9,1);a.sw(9,8,16)
    a.move(2,0);a.i(49,0,29,0x44);a.i(49,1,29,0x54);constant(a,2,-.5)
    fp(a,0x36,0,1,2);a.branch(17,8,0,'done')
    fp(a,0x34,0,20,0);a.branch(17,8,0,'done')
    fp(a,1,1,0,20);constant(a,2,8000);fp(a,0x34,0,1,2);a.branch(17,8,0,'done')
    a.addiu(2,0,1)
    a.label('done');a.i(49,20,29,0x80);a.i(55,16,29,0x70);a.i(55,31,29,0x78)
    a.addiu(29,29,0x90);a.jr();return a.finish()


def payload(previous):
    a=Assembler(CODE);a.addiu(29,29,-0x140)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0xD0+4*i)
    a.li(16,CONTROL);a.lw(8,16);a.addiu(9,0,1);a.branch(5,8,9,'done')
    core.gate(a,'error101')
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'error101')
    a.lw(17,16,8);a.branch(5,17,10,'error101')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'error102')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'error102')
    a.li(8,fresh_memory.CONTROL+80);a.lw(8,8);a.branch(4,8,0,'error102')
    # Validate every participant before querying or editing any actor.
    a.move(18,0);a.li(19,ROWS)
    a.label('validate');a.sw(18,16,24)
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.lw(20,19);a.branch(5,8,20,'error101');a.lw(8,20);a.branch(5,8,18,'error101')
    a.lw(8,20,12);a.lw(9,19,8);a.branch(5,8,9,'error101')
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x2D,9,9,8);a.lw(9,9)
    a.lw(21,19,4);a.branch(5,9,21,'error101')
    a.lw(8,21,4);a.addiu(9,0,1);a.branch(5,8,9,'error101')
    a.lw(8,20,0x948);a.addiu(9,0,11);a.branch(5,8,9,'error102')
    for off in (0x1278,0x127C,0x1280,0x1284):a.lw(8,20,off);a.branch(5,8,0,'error102')
    for off in (4000,4004):
        a.lw(8,21,off);a.addiu(9,21,3936);a.branch(4,8,9,f'sphere{off}')
        a.addiu(9,21,3968);a.branch(5,8,9,'error101');a.label(f'sphere{off}')
    for off in (0,4,8):a.lw(8,21,2416+off);a.sw(8,19,0x30+off)
    a.addiu(18,18,1);a.addiu(19,19,STRIDE);a.branch(5,18,17,'validate')
    # Native leader floor measured from just above its current world root.
    # This preserves legal aerial starts and the leader's actual floor level.
    a.addiu(18,0,2);a.li(19,ROWS+2*STRIDE)
    a.label('plan');a.sw(18,16,24);a.i(12,8,18,1);a.r(0,8,0,8,7)
    a.li(22,ROWS);a.r(0x2D,22,22,8);a.lw(23,22,4)
    a.addiu(4,23,2416);a.i(49,20,23,2420);constant(a,0,.25);fp(a,1,12,20,0)
    a.call(QUERY);a.branch(4,2,0,'error103')
    fp(a,6,21,0);a.i(57,21,19,0x20);fp(a,1,22,21,20)
    # Finite positive clearance is guaranteed by the query threshold. Round
    # the sub-quarter-unit foot penetration of a native idle to zero.
    constant(a,0,0);fp(a,0x34,0,22,0);a.branch(17,8,0,'clearance')
    fp(a,6,22,0);a.label('clearance')
    # Attempt count lives in s4, not caller-saved t8, across native queries.
    a.move(20,0);constant(a,23,1)
    a.label('candidate')
    for off in (0,8):
        a.i(49,0,19,0x30+off);a.i(49,1,23,2416+off)
        fp(a,1,0,0,1);fp(a,2,0,0,23);fp(a,0,0,0,1);a.i(57,0,19,0x10+off)
    a.sw(20,19,0x40);a.addiu(4,19,0x10);constant(a,0,512);fp(a,1,12,21,0)
    a.call(QUERY);a.branch(4,2,0,'retry')
    # Reject a distant lower level at an edge; halve the lateral displacement
    # twice, then use the leader's verified footprint as the last fallback.
    fp(a,1,1,0,21);fp(a,5,1,1);constant(a,2,512)
    fp(a,0x36,0,1,2);a.branch(17,8,0,'retry')
    a.i(57,0,19,0x24);fp(a,1,0,0,22);constant(a,1,.25);fp(a,1,0,0,1)
    a.i(57,0,19,0x14);a.addiu(8,0,1);a.sw(8,19,0x44)
    a.branch(4,20,0,'next_plan');a.lw(8,16,20);a.addiu(8,8,1);a.sw(8,16,20)
    a.label('next_plan');a.addiu(18,18,1);a.addiu(19,19,STRIDE)
    a.branch(5,18,17,'plan');a.jump('apply_begin')
    a.label('retry');a.addiu(20,20,1);a.i(11,8,20,4);a.branch(4,8,0,'error104')
    a.addiu(8,0,3);a.branch(4,20,8,'leader_position')
    constant(a,0,.5);fp(a,2,23,23,0);a.jump('candidate')
    a.label('leader_position');constant(a,23,0);a.jump('candidate')
    # Planning succeeded for every extra. Correct model translation using
    # actual root delta, then native transforms/sphere/model→actor sync.
    a.label('apply_begin');a.addiu(18,0,2);a.li(19,ROWS+2*STRIDE)
    a.label('apply');a.lw(20,19);a.lw(21,19,4)
    for off in (0,4,8):
        a.i(49,0,19,0x10+off);a.i(49,1,21,2416+off);fp(a,1,0,0,1)
        a.i(49,1,21,2384+off);fp(a,0,0,0,1);a.i(57,0,21,2384+off)
    for function in (A(0x24E2B0),A(0x24E3F8)):a.move(4,21);a.call(function)
    a.move(4,21);a.move(5,0);a.call(A(0x24DC58))
    a.move(4,20);a.call(A(0x1D70E8))
    for off in range(0,48,4):a.lw(8,20,16+off);a.sw(8,20,256+off)
    # Both native sphere buffers describe the new position, avoiding a sweep
    # from the copied leader location when the first combat frame swaps them.
    a.lw(8,21,4000);a.lw(9,21,4004)
    for off in range(0,32,4):a.lw(10,8,off);a.sw(10,9,off)
    a.addiu(4,0,-1);a.addiu(5,21,2416);a.call(A(0x23FF78));a.sw(2,21,2596)
    a.lw(8,16,12);a.addiu(8,8,1);a.sw(8,16,12)
    a.addiu(18,18,1);a.addiu(19,19,STRIDE);a.branch(5,18,17,'apply')
    a.addiu(8,0,5);a.sw(8,16);a.sw(0,16,24);a.jump('done')
    for error in ERRORS:
        a.label(f'error{error}');a.addiu(8,0,error);a.sw(8,16);a.jump('done')
    a.label('done')
    # Exported presets may arm start before their first frame. Failed or
    # unfinished placement must never consume that request through the tail.
    # Cancel only this captured match's enabled holds, including replay intro.
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(4,9,10,'restore')
    a.lw(11,8,4);a.lw(9,28,-22364);a.branch(5,11,9,'restore')
    for name,control in (('start',start.CONTROL),('intro',intro.CONTROL)):
        a.li(8,control);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,f'skip_{name}_cancel')
        a.lw(9,8,8);a.branch(5,9,11,f'skip_{name}_cancel');a.sw(0,8,4)
        a.label(f'skip_{name}_cancel')
    a.label('restore')
    for i in range(12):a.i(49,20+i,29,0xD0+4*i)
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x140);a.jump(previous)
    result=a.finish();assert len(result)<QUERY-CODE;return result


def legacy_build_memory(ram, source='<offline-memory>'):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,n=u(core.ACTORS),u(core.MODE+4)
    if (n not in ACTOR_COUNTS or not 0x100000<=manager<len(ram)-16 or u(manager)!=2
            or u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.MODE+12)!=n):
        raise ValueError('Requires virtually activated captured4/6 team')
    if u(fresh_memory.CONTROL+80)!=1:raise ValueError('Preparation input hold required')
    if any(ram[CODE:END]):raise ValueError('Spawn placement reservation occupied')
    rows=bytearray(STRIDE*n); identities=[]
    for i in range(n):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<len(ram)-0x1600 or u(actor)!=i:raise ValueError('Actor identity mismatch')
        model_id=u(actor+12)
        if model_id>=12:raise ValueError('Model ID outside native table')
        model=u(core.MODELS+4*model_id)
        if not 0x100000<=model<len(ram)-0x1670 or u(model+4)!=1:raise ValueError('Invalid registered model')
        if u(actor+0x948)!=11 or any(u(actor+off) for off in (0x1278,0x127C,0x1280,0x1284)):
            from native_preparation import launcher
            raise ValueError(NOT_IDLE.format(play=launcher()))
        if any(u(model+off) not in (model+3936,model+3968) for off in (4000,4004)):
            raise ValueError('Invalid native collision sphere buffers')
        for off in (0,4,8):
            value=struct.unpack_from('<f',ram,model+2416+off)[0]
            if not math.isfinite(value) or abs(value)>1e6:raise ValueError('Invalid world position')
        struct.pack_into('<4I',rows,i*STRIDE,actor,model,model_id,i&1)
        identities.append(dict(physical=i,actor=actor,model=model,model_id=model_id))
    if len({x['actor'] for x in identities})!=n or len({x['model'] for x in identities})!=n:
        raise ValueError('Duplicate actor/model identity')
    _,_,native=elf_reader(elf_path(ROOT))
    for address,size in ((A(0x1B14C0),0xF8),(A(0x1B12E0),0x120),(A(0x23FF78),0x198),
                         (A(0x230B38),0x40),(A(0x1D70E8),0xB0),(A(0x24DC58),0x60)):
        if ram[address:address+size]!=native(address,size):raise ValueError(f'Native terrain helper changed{address:08X}')
    word=u(HOOK)
    if word>>26!=2 or u(HOOK+4)!=0:raise ValueError('Expected reviewed team frame chain')
    previous=(word&0x3FFFFFF)<<2
    # Existing ordinary prepared frames plus the reviewed replay-intro wrapper.
    if not (0x07000000<=previous<0x07400000 or previous==0x07430000):
        raise ValueError(f'Unreviewed frame chain{previous:08X}')
    control=struct.pack('<7I',1,manager,n,0,0,0,0)+bytes(0x100-28)
    pieces=[(CODE,payload(previous)),(QUERY,query_code()),(ROWS,bytes(rows)),(CONTROL,control),
            (HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,previous=previous,
        ready_status=5,errors=ERRORS,actors=identities,
        blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in pieces],
        requirements=['Install while every captured actor is held in idle11; compose last after start gate/intro.',
                      'Wait CONTROL==5 before uncover/start request; any error retains the preparation hold.',
                      'Prearmed start/intro requests are cancelled on any non-success status, scoped to the captured hold.',
                      'This one-shot initial placement is not an in-combat teleport or an already-stuck-match repair.'],
        telemetry=dict(placed=CONTROL+12,queries=CONTROL+16,fallbacks=CONTROL+20,error_actor=CONTROL+24,rows=ROWS))



# Version 2 keeps the historical payload/query bytes above for exact released
# checkpoint validation. New preparation uses only formation_payload().
FOOTPRINT, BODY = 0x07454000, 0x07455000
CANDIDATES, ANCHORS = 0x07456000, 0x07457400
VERSION, MAX_CANDIDATES = 3, 64
STAGE = A(0x2FEBE0)
QUERY_GLOBALS = (-0x50B8,-0x4FE8,-0x56D0,-0x56CC,-0x50A0,-0x56DC)
ERRORS_V2 = dict(ERRORS, **{})
ERRORS_V2.update({105: 'Authored spawn or stage identity changed',
                  106: 'Start gate already released or not owned'})


def stage_anchors(ram):
    """Read the same original two records as native 2427A0(a3=0)."""
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    def ptr(p,size):
        if p&3 or not 0x100000<=p<=len(ram)-size:raise ValueError('Invalid authored spawn pointer')
        return p
    stage=ptr(u(STAGE),64);header=ptr(u(stage+4),64);records=ptr(u(header+44),64)
    data=ram[records:records+64];values=struct.unpack('<16f',data)
    if not all(math.isfinite(v) and abs(v)<1e6 for v in values):raise ValueError('Invalid authored spawn coordinates')
    anchors=[(values[i*8],values[i*8+2]) for i in range(2)]
    distance=math.dist(*anchors)
    if not 1<=distance<=10000:raise ValueError('Degenerate authored spawn anchors')
    count=u(stage+56);sectors=ptr(u(stage+60),64*count)
    if not 1<=count<=4096:raise ValueError('Invalid native sector table')
    return dict(stage=stage,header=header,records=records,data=data,anchors=anchors,distance=distance,sector_count=count,sectors=sectors)


def candidate_plan(anchors,radii,present_mask):
    """Prefer a shallow V, then fit narrow terrain without weakening collision checks."""
    n=len(radii);gap=math.dist(*anchors)
    forward=((anchors[1][0]-anchors[0][0])/gap,(anchors[1][1]-anchors[0][1])/gap)
    largest=max(r for i,r in enumerate(radii) if present_mask>>i&1)
    minimum=max(48.,radii[0]+radii[1]+32.)
    retreat=max(0.,(minimum-gap)/2)
    bases=[(x-forward[0]*retreat*(1 if side==0 else -1),
            z-forward[1]*retreat*(1 if side==0 else -1)) for side,(x,z) in enumerate(anchors)]
    wing=max(80.,min(180.,gap*.6),2*largest+32.)
    result=[]
    for i in range(n):
        side=i&1;sign=1 if side==0 else -1;fx,fz=(v*sign for v in forward);rx,rz=fz,-fx
        x,z=bases[side];rank=i//2
        if not present_mask>>i&1:result.append([]);continue
        if rank==0:
            # Keep a valid authored anchor first. Small backwards alternatives
            # handle an authored root whose larger selected body touches a wall.
            offsets=[(0,0),(0,16),(0,32),(0,64),(-16,24),(16,24)]
        else:
            # Odd ranks take one flank, even ranks the other; ranks 3 and 4
            # form a second, deeper V behind ranks 1 and 2 (row 1), so no two
            # fighters of a side share a candidate list. Ranks 1..2 are row 0,
            # exactly as before.
            hand=-1 if rank%2 else 1;row=(rank-1)//2
            offsets=[(hand*wing*w,wing*b+row*wing*.9) for w,b in
                     ((1,.6),(.8,.8),(.65,1),(1,1.2),(1.2,.6),(.65,1.5),
                      (.5,1.8),(1.4,1),(1.6,.6),(.8,2),(1.2,1.8),(1.6,1.6))]
            # A road or ledge may have no ground under any of the outward V
            # candidates. Search smaller, rearward columns as well as both
            # lateral directions. The guest still checks all nine floor
            # points, solid geometry and every already-planned fighter.
            spacing=max(32.,2*largest+20.)
            for depth in (1.,2.,3.,4.):
                for lateral in (0.,.5,1.,-.5,-1.):
                    offsets.append((hand*spacing*lateral,spacing*depth))
            for depth in (0.,.5,1.5):
                for lateral in (1.,-1.,1.5,-1.5,2.,-2.):
                    offsets.append((hand*spacing*lateral,spacing*depth))
        # Preserve preference order and keep the native candidate array bounded.
        offsets=list(dict.fromkeys(offsets))
        if len(offsets)>MAX_CANDIDATES:raise ValueError('Spawn candidate budget exceeded')
        result.append([(x+rx*lr-fx*back,z+rz*lr-fz*back) for lr,back in offsets])
    return dict(candidates=result,minimum_opposing=minimum,wing=wing,back=wing*.6,anchors=bases)


def footprint_code():
    """a0=row -> v0=valid; native nine-point floor footprint; writes only its plan."""
    a=Assembler(FOOTPRINT);a.addiu(29,29,-0x80)
    for i,r in enumerate((16,17,18,31)):a.i(63,r,29,0x30+i*8)
    for i in range(4):a.i(57,20+i,29,0x50+i*4)
    a.move(16,4);a.move(17,0)
    a.i(49,22,16,0x20);a.i(49,23,16,0x5C)
    for i,(dx,dz) in enumerate(((0,0),(1,0),(-1,0),(0,1),(0,-1),(.707,.707),(-.707,.707),(.707,-.707),(-.707,-.707))):
        for off,factor in ((0,dx),(8,dz)):
            a.i(49,0,16,0x10+off);constant(a,1,factor);fp(a,2,1,1,22);fp(a,0,0,0,1);a.i(57,0,29,off)
        a.move(4,29);a.call(A(0x23FDB0));a.branch(1,2,0,'invalid')
        a.move(4,29);fp(a,6,12,23);a.call(QUERY);a.branch(4,2,0,'invalid')
        if i==0:
            fp(a,6,20,0);fp(a,6,21,0);a.i(57,0,16,0x54)
        else:
            fp(a,0x34,0,0,20);a.branch(17,8,0,f'min{i}');fp(a,6,20,0);a.label(f'min{i}')
            fp(a,0x34,0,21,0);a.branch(17,8,0,f'max{i}');fp(a,6,21,0);a.label(f'max{i}')
    fp(a,1,0,21,20);constant(a,1,1.5);fp(a,2,1,1,22);constant(a,2,2);fp(a,0,1,1,2)
    fp(a,0x36,0,0,1);a.branch(17,8,0,'invalid')
    # Highest supporting point (negative Y is up), never a global floor clamp.
    constant(a,0,.25);fp(a,1,20,20,0);a.i(57,20,16,0x14)
    a.addiu(2,0,1);a.jump('done');a.label('invalid');a.move(2,0)
    a.label('done')
    for i in range(4):a.i(49,20+i,29,0x50+i*4)
    for i,r in enumerate((16,17,18,31)):a.i(55,r,29,0x30+i*8)
    a.addiu(29,29,0x80);a.jr();result=a.finish();assert len(result)<BODY-FOOTPRINT;return result


def body_code():
    """a0=row -> v0=clear. Native read-only sphere/triangle visitor, private scratch."""
    a=Assembler(BODY);a.addiu(29,29,-0x170)
    for i,r in enumerate((16,17,31)):a.i(63,r,29,0x140+i*8)
    a.move(16,4)
    for i,off in enumerate(QUERY_GLOBALS):a.lw(8,28,off);a.sw(8,29,0x158+4*i)
    for off in range(0,0x140,4):a.sw(0,29,off)
    for off in (0,8):a.lw(8,16,0x10+off);a.sw(8,29,0x40+off)
    a.i(49,0,16,0x14);a.i(49,1,16,0x24);fp(a,0,0,0,1);a.i(57,0,29,0x44)
    constant(a,0,1);a.i(57,0,29,0x4C)
    a.i(49,0,16,0x20);a.i(57,0,29,0x50);fp(a,2,1,0,0);a.i(57,1,29,0x54)
    for off in (0x10,0x14,0x18):a.i(57,0,29,off)
    a.addiu(4,29,0x110);a.addiu(5,29,0x40);a.addiu(6,29,0x10);a.call(A(0x230B38))
    a.addiu(4,29,0x40);a.call(A(0x23FDB0));a.li(8,CONTROL);a.lw(9,8,64)
    a.r(0x2B,8,2,9);a.branch(4,8,0,'invalid');a.move(4,2);a.call(A(0x240110));a.move(17,2)
    a.i(12,8,17,15);a.branch(5,8,0,'invalid');a.li(8,0x100000);a.r(0x2B,8,17,8);a.branch(5,8,0,'invalid')
    a.li(8,0x8000000-64);a.r(0x2B,8,8,17);a.branch(5,8,0,'invalid')
    a.call(A(0x1B16F0))
    a.move(4,29);a.move(5,17);a.addiu(6,29,0x110);a.addiu(7,29,0x40);a.li(8,A(0x1B26E0));a.call(A(0x1B1708))
    a.li(8,CONTROL);a.lw(9,8,60);a.addiu(9,9,1);a.sw(9,8,60)
    a.lw(8,29,0x108);a.i(11,2,8,1);a.jump('restore')
    a.label('invalid');a.move(2,0);a.label('restore')
    for i,off in enumerate(QUERY_GLOBALS):a.lw(8,29,0x158+4*i);a.sw(8,28,off)
    for i,r in enumerate((16,17,31)):a.i(55,r,29,0x140+i*8)
    a.addiu(29,29,0x170);a.jr();result=a.finish();assert len(result)<CANDIDATES-BODY;return result


def formation_payload(previous):
    a=Assembler(CODE);a.addiu(29,29,-0x280)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    a.i(63,1,29,0xC8)
    for i in range(12):a.i(57,20+i,29,0xD0+4*i)
    for i,off in enumerate(QUERY_GLOBALS):a.lw(8,28,off);a.sw(8,29,0x260+4*i)
    a.li(16,CONTROL);a.lw(8,16);a.addiu(9,0,1);a.branch(5,8,9,'done')
    core.gate(a,'error101');a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'error101')
    a.lw(17,16,8);a.branch(5,17,10,'error101')
    for address,expected in ((core.PAIR+4,0),(A(0x333700),0),(fresh_memory.CONTROL+80,1)):
        a.li(8,address);a.lw(8,8);a.addiu(9,0,expected);a.branch(5,8,9,'error102')
    a.li(8,start.CONTROL);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,'error106')
    a.lw(9,8,8);a.lw(10,16,4);a.branch(5,9,10,'error106')
    a.lw(9,8,12);a.branch(5,9,17,'error106');a.lw(9,8,20);a.branch(5,9,0,'error106')
    a.li(8,STAGE);a.lw(8,8);a.lw(9,16,36);a.branch(5,8,9,'error105')
    a.lw(8,8,4);a.lw(9,16,40);a.branch(5,8,9,'error105');a.lw(8,8,44)
    a.lw(9,16,44);a.branch(5,8,9,'error105')
    a.lw(11,16,36)
    for off,field in ((56,64),(60,68)):
        a.lw(9,11,off);a.lw(10,16,field);a.branch(5,9,10,'error105')
    for off in range(0,64,4):a.lw(9,8,off);a.lw(10,16,0x80+off);a.branch(5,9,10,'error105')
    a.move(18,0);a.li(19,ROWS)
    a.label('validate');a.sw(18,16,24)
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.lw(20,19);a.branch(5,8,20,'error101');a.lw(8,20);a.branch(5,8,18,'error101')
    a.lw(8,20,12);a.lw(9,19,8);a.branch(5,8,9,'error101');a.r(0,8,0,8,2)
    a.li(9,core.MODELS);a.r(0x2D,9,9,8);a.lw(9,9);a.lw(21,19,4);a.branch(5,9,21,'error101')
    a.lw(8,21,4);a.addiu(9,0,1);a.branch(5,8,9,'error101')
    a.lw(8,19,0x48);a.branch(4,8,0,'next_validate')
    a.lw(8,20,0x948);a.addiu(9,0,11);a.branch(5,8,9,'error102')
    for off in (0x1278,0x127C,0x1280,0x1284):a.lw(8,20,off);a.branch(5,8,0,'error102')
    for off in (4000,4004):
        a.lw(8,21,off);a.addiu(9,21,3936);a.branch(4,8,9,f'sphere{off}');a.addiu(9,21,3968)
        a.branch(5,8,9,'error101');a.label(f'sphere{off}')
    for off in (0,4,8):a.lw(8,21,2416+off);a.sw(8,19,0x30+off)
    a.lw(8,20,36);a.sw(8,19,0x3C)
    # Native sphere constructor reads actual bones and writes only private scratch.
    a.lw(8,21,0x1004);a.lw(9,19,0x64);a.branch(5,8,9,'error101')
    for off,field in ((0xD6C,0x68),(0xDB0,0x6C)):
        a.lw(8,21,off);a.lw(9,19,field);a.branch(5,8,9,'error101')
    a.addiu(8,29,0x240);a.sw(8,29,0x1B0);a.lw(8,21,0x1004);a.sw(8,29,0x214)
    a.move(4,21);a.addiu(5,29,0x160);a.call(A(0x24D920))
    a.i(49,0,29,0x240);a.i(49,1,21,2416);fp(a,1,0,0,1);fp(a,5,0,0)
    a.i(49,1,29,0x248);a.i(49,2,21,2424);fp(a,1,1,1,2);fp(a,5,1,1);fp(a,0,0,0,1)
    a.i(49,1,29,0x250);fp(a,0,1,1,0);a.i(57,1,19,0x20)
    a.i(49,1,29,0x244);a.i(49,2,21,2420);fp(a,1,1,1,2);fp(a,1,1,1,0);a.i(57,1,19,0x24)
    constant(a,0,.1);a.i(49,1,19,0x20);fp(a,0x34,0,0,1);a.branch(17,8,0,'error101')
    constant(a,0,1024);fp(a,0x34,0,1,0);a.branch(17,8,0,'error101')
    a.i(49,1,19,0x24);fp(a,5,1,1);fp(a,0x34,0,1,0);a.branch(17,8,0,'error101')
    a.label('next_validate')
    a.addiu(18,18,1);a.addiu(19,19,STRIDE);a.branch(5,18,17,'validate')
    # The game's own stage-specific anchor and facing lookup. No actor reset.
    for side in range(2):
        a.addiu(4,0,side);a.li(5,ANCHORS+side*32);a.addiu(6,5,16);a.move(7,0);a.call(A(0x2427A0))
        a.li(8,ANCHORS+side*32);a.i(49,0,8,4);constant(a,1,-700);fp(a,0x34,0,1,0)
        a.branch(17,8,0,'error103');constant(a,1,7000);fp(a,0x34,0,0,1);a.branch(17,8,0,'error103')
    a.move(18,0);a.li(19,ROWS)
    a.label('plan');a.sw(18,16,24);a.lw(8,19,0x48);a.branch(4,8,0,'next_plan')
    a.move(20,0);a.lw(21,19,0x50)
    a.label('candidate');a.sw(20,19,0x40)
    a.lw(8,21);a.sw(8,19,0x10);a.lw(8,21,4);a.sw(8,19,0x18)
    a.i(12,8,18,1);a.r(0,8,0,8,5);a.li(9,ANCHORS);a.r(0x2D,9,9,8)
    a.i(49,20,9,4);constant(a,0,256);fp(a,1,0,20,0);a.i(57,0,19,0x5C)
    a.move(4,19);a.call(FOOTPRINT);a.branch(4,2,0,'retry')
    a.i(49,0,19,0x14);fp(a,1,0,0,20);fp(a,5,0,0);constant(a,1,128)
    fp(a,0x36,0,0,1);a.branch(17,8,0,'retry')
    # Horizontal clearance includes every already planned real participant.
    a.move(22,0);a.li(23,ROWS)
    a.label('separation');a.branch(4,22,18,'body');a.lw(8,23,0x44);a.branch(4,8,0,'next_other')
    a.i(49,0,19,0x10);a.i(49,1,23,0x10);fp(a,1,0,0,1);fp(a,2,0,0,0)
    a.i(49,1,19,0x18);a.i(49,2,23,0x18);fp(a,1,1,1,2);fp(a,2,1,1,1);fp(a,0,0,0,1)
    a.i(49,1,19,0x20);a.i(49,2,23,0x20);fp(a,0,1,1,2);constant(a,2,20);fp(a,0,1,1,2)
    a.lw(8,19,12);a.lw(9,23,12);a.branch(4,8,9,'same_side')
    constant(a,2,12);fp(a,0,1,1,2);constant(a,2,48);fp(a,0x34,0,1,2)
    a.branch(17,8,0,'same_side');fp(a,6,1,2);a.label('same_side')
    fp(a,2,1,1,1);fp(a,0x34,0,0,1);a.branch(17,8,1,'retry')
    a.label('next_other');a.addiu(22,22,1);a.addiu(23,23,STRIDE);a.jump('separation')
    a.label('body');a.move(4,19);a.call(BODY);a.branch(4,2,0,'retry')
    a.addiu(8,0,1);a.sw(8,19,0x44);a.branch(4,20,0,'next_plan')
    a.lw(8,16,20);a.addiu(8,8,1);a.sw(8,16,20)
    a.label('next_plan');a.addiu(18,18,1);a.addiu(19,19,STRIDE);a.branch(5,18,17,'plan');a.jump('apply_begin')
    a.label('retry');a.addiu(20,20,1);a.addiu(21,21,8);a.lw(8,19,0x4C);a.branch(5,20,8,'candidate');a.jump('error104')
    # All geometry queries succeed before the first actor/model edit.
    a.label('apply_begin');a.move(18,0);a.li(19,ROWS)
    a.label('apply');a.lw(8,19,0x48);a.branch(4,8,0,'next_apply')
    a.lw(20,19);a.lw(21,19,4)
    a.i(12,8,18,1);a.i(14,8,8,1);a.r(0,8,0,8,7);a.li(22,ROWS);a.r(0x2D,22,22,8)
    a.i(49,12,19,0x10);a.i(49,13,19,0x18);a.i(49,14,22,0x10);a.i(49,15,22,0x18);a.call(A(0x241F10))
    a.i(57,0,19,0x60);a.sw(0,29,0x140);a.i(57,0,29,0x144);a.sw(0,29,0x148)
    constant(a,0,1);a.i(57,0,29,0x14C);a.i(57,0,19,0x1C)
    a.addiu(4,0,-1);a.addiu(5,19,0x10);a.call(A(0x23FF78));a.move(7,2)
    a.move(4,20);a.addiu(5,19,0x10);a.addiu(6,29,0x140);a.call(A(0x1D7418))
    for function in (A(0x24E2B0),A(0x24E3F8)):a.move(4,21);a.call(function)
    a.move(4,21);a.move(5,0);a.call(A(0x24DC58));a.move(4,20);a.call(A(0x1D70E8))
    for off in range(0,240,4):a.lw(8,20,16+off);a.sw(8,20,256+off)
    a.lw(8,21,4000);a.lw(9,21,4004)
    for off in range(0,32,4):a.lw(10,8,off);a.sw(10,9,off)
    a.lw(8,16,12);a.addiu(8,8,1);a.sw(8,16,12)
    a.label('next_apply');a.addiu(18,18,1);a.addiu(19,19,STRIDE);a.branch(5,18,17,'apply')
    a.addiu(8,0,5);a.sw(8,16);a.sw(0,16,24);a.jump('done')
    for error in ERRORS_V2:a.label(f'error{error}');a.addiu(8,0,error);a.sw(8,16);a.jump('done')
    a.label('done');a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(4,9,10,'restore')
    a.lw(11,8,4);a.lw(9,28,-22364);a.branch(5,11,9,'restore')
    for name,control in (('start',start.CONTROL),('intro',intro.CONTROL)):
        a.li(8,control);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,f'skip_{name}')
        a.lw(9,8,8);a.branch(5,9,11,f'skip_{name}');a.sw(0,8,4);a.label(f'skip_{name}')
    a.label('restore')
    for i,off in enumerate(QUERY_GLOBALS):a.lw(8,29,0x260+4*i);a.sw(8,28,off)
    a.i(55,1,29,0xC8)
    for i in range(12):a.i(49,20+i,29,0xD0+4*i)
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x280);a.jump(previous);result=a.finish();assert len(result)<QUERY-CODE;return result


def formation_build_memory(ram, source='<offline-memory>', present_mask=None):
    """Requires an initial unreleased hold, never active combat."""
    old=legacy_build_memory(ram,source);u=lambda p:struct.unpack_from('<I',ram,p)[0]
    f=lambda p:struct.unpack_from('<f',ram,p)[0]
    manager,n=u(core.ACTORS),len(old['actors'])
    if (u(start.CONTROL),u(start.CONTROL+8),u(start.CONTROL+12),u(start.CONTROL+20))!=(1,manager,n,0):
        raise ValueError('Initial unreleased start gate required')
    mask=(1<<n)-1 if present_mask is None else present_mask
    if type(mask) is not int or mask&3!=3 or mask>>n or mask<0:raise ValueError('Invalid participating fighter mask')
    counts=[sum((mask>>i)&1 for i in range(side,n,2)) for side in (0,1)]
    if any(not 1<=v<=policy.TEAM_CAPACITY for v in counts):
        raise ValueError(f'Requires one to {policy.TEAM_CAPACITY} fighters per side')
    anchor=stage_anchors(ram);rows=bytearray(STRIDE*n);radii=[]
    bias=f(A(0x304270-0x5C24))
    if not math.isfinite(bias) or not 0<=bias<=10:raise ValueError('Invalid native sphere bias')
    for i,item in enumerate(old['actors']):
        actor,model=item['actor'],item['model'];radius=f(model+0x1004)
        bones=[u(model+o) for o in (0xD6C,0xDB0)]
        if any(p&15 or not 0x100000<=p<=len(ram)-0x80 for p in bones):raise ValueError('Invalid native sphere bone')
        root=struct.unpack_from('<3f',ram,model+2416)
        center=(f(bones[0]+0x40),min(f(bones[0]+0x44)-radius-bias,f(bones[1]+0x44)-bias),f(bones[0]+0x48))
        if not all(math.isfinite(x) and abs(x)<1e6 for x in center) or not .1<=radius<=512:
            raise ValueError('Invalid native body radius or center')
        inflation=abs(center[0]-root[0])+abs(center[2]-root[2]);radii.append(radius+inflation)
        if inflation>radius*2+16:raise ValueError('Unbounded idle body offset')
        struct.pack_into('<4I',rows,i*STRIDE,actor,model,item['model_id'],i&1)
        struct.pack_into('<2f',rows,i*STRIDE+0x20,radii[-1],center[1]-root[1]-inflation)
        struct.pack_into('<I',rows,i*STRIDE+0x48,(mask>>i)&1)
        struct.pack_into('<3I',rows,i*STRIDE+0x64,u(model+0x1004),*bones)
        item.update(present=bool(mask>>i&1),radius=radii[-1],native_radius=radius)
    plan=candidate_plan(anchor['anchors'],radii,mask);candidates=bytearray()
    for i,points in enumerate(plan['candidates']):
        struct.pack_into('<2I',rows,i*STRIDE+0x4C,len(points),CANDIDATES+len(candidates))
        for x,z in points:candidates+=struct.pack('<2f',x,z)
    if CANDIDATES+len(candidates)>ANCHORS:raise ValueError('Spawn candidates exceed their reservation')
    _,_,native=elf_reader(elf_path(ROOT))
    for address,size in ((A(0x2427A0),0x118),(A(0x2426E0),0xC0),(A(0x241F10),0x140),(A(0x23FDB0),0xC0),(A(0x1D7418),0x158),
                         (A(0x24D920),0xB0),(A(0x2505A8),0x10),(A(0x24E2B0),0x108),(A(0x24E3F8),0x104),(A(0x24DD20),0x60),(A(0x1B26E0),0x108),(A(0x1B1708),0x1B0),
                         (A(0x1B16F0),0x18),(A(0x238310),0x78),(A(0x240110),0x28),(A(0x2FE5EC),16),(A(0x2FE64C),4)):
        if ram[address:address+size]!=native(address,size):raise ValueError(f'Native formation helper changed {address:08X}')
    control=bytearray(256)
    struct.pack_into('<12I',control,0,1,manager,n,0,0,0,0,VERSION,mask,anchor['stage'],anchor['header'],anchor['records'])
    struct.pack_into('<3f',control,48,plan['minimum_opposing'],plan['wing'],plan['back'])
    struct.pack_into('<2I',control,64,anchor['sector_count'],anchor['sectors'])
    control[0x80:0xC0]=anchor['data']
    previous=old['previous']
    pieces=[(CODE,formation_payload(previous)),(QUERY,query_code()),(FOOTPRINT,footprint_code()),
            (BODY,body_code()),(CANDIDATES,bytes(candidates)),(ANCHORS,bytes(64)),
            (ROWS,bytes(rows)),(CONTROL,bytes(control)),(HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))]
    return dict(serial=old['serial'],crc=old['crc'],source=str(source),version=VERSION,control=CONTROL,
        previous=previous,ready_status=5,errors=ERRORS_V2,actors=old['actors'],present_mask=mask,
        anchors=anchor['anchors'],formation=plan,
        blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in pieces],
        requirements=['All real fighters held idle before initial start; no running-match reset.',
                      'Native authored anchors, local nine-point floors and native solid-triangle body checks.',
                      'All real positions planned before any actor/model edit; reserved slots remain untouched.',
                      'No safe bounded alternative means status104 and the preparation hold stays active.'],
        telemetry=dict(placed=CONTROL+12,queries=CONTROL+16,fallbacks=CONTROL+20,error_actor=CONTROL+24,
                       body_queries=CONTROL+60,rows=ROWS,row_stride=STRIDE,
                       row_fields={'planned_xyz':0x10,'radius':0x20,'center_y_offset':0x24,'original_xyz':0x30,
                                   'original_yaw':0x3C,'candidate_index':0x40,'planned':0x44,'present':0x48,
                                   'candidate_count':0x4C,'center_floor':0x54,'yaw':0x60}))


def upgrade_memory(ram, source='<offline-pending-preset>', present_mask=None):
    """Replace exact historical placement only while its original start is pending."""
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,n=u(core.ACTORS),u(core.MODE+4)
    if n not in ACTOR_COUNTS or (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(1,manager,n):
        raise ValueError('Only untouched pending legacy placement can be upgraded')
    if (u(start.CONTROL),u(start.CONTROL+8),u(start.CONTROL+12),u(start.CONTROL+20))!=(1,manager,n,0):
        raise ValueError('Initial unreleased start gate required')
    length=len(payload(0));tail=u(CODE+length-8)
    if tail>>26!=2:raise ValueError('Changed legacy placement continuation')
    previous=(tail&0x3FFFFFF)<<2
    if previous!=start.CODE:raise ValueError('Changed legacy placement continuation')
    # The preserved releases have one exact pool -> placement -> start chain.
    # Run this upgrade before adding new preset wrappers, never after them.
    import extra_special_pools as pools
    if (u(HOOK),u(HOOK+4))!=((2<<26)|(pools.CODE>>2),0):raise ValueError('Changed legacy outer frame hook')
    if (u(pools.CONTROL),u(pools.CONTROL+4),u(pools.CONTROL+8),u(pools.CONTROL+12))!=(0,manager,n,0):
        raise ValueError('Private pool initializer must remain pending')
    actors=[u(core.POINTERS+4*i) for i in range(n)]
    if any(not 0x100000<=p<=len(ram)-0x1600 for p in actors):raise ValueError('Invalid legacy actor pointer')
    mids=[u(p+12) for p in actors]
    if any(p>=12 for p in mids):raise ValueError('Invalid legacy actual model ID')
    models=[u(core.MODELS+4*mid) for mid in mids]
    primary,allocator=u(pools.GLOBAL),u(pools.ALLOC_GLOBAL)
    if not 0x100000<=primary<=len(ram)-12 or not 0x100000<=allocator<=len(ram)-156:
        raise ValueError('Invalid legacy special manager')
    rootpool=u(primary)
    if (u(pools.CONTROL+28),u(pools.CONTROL+36),u(pools.CONTROL+40))!=(primary,rootpool,allocator):
        raise ValueError('Changed private pool ownership')
    code=pools.payload(CODE,actors,mids,models,allocator,primary,rootpool)
    if ram[pools.CODE:pools.CODE+len(code)]!=code:raise ValueError('Changed legacy pool continuation')
    start_code=start.code(0x073D7000)
    if ram[start.CODE:start.CODE+len(start_code)]!=start_code:raise ValueError('Changed legacy start chain')
    for i,actor in enumerate(actors):
        if u(start.CONTROL+0x80+4*i)!=actor or u(start.CONTROL+0x40+4*i) not in (0,1):
            raise ValueError('Changed legacy start ownership')
    expected=bytearray(END-CODE)
    rows=bytearray(n*STRIDE)
    for i in range(n):
        actor=u(core.POINTERS+4*i);mid=u(actor+12);model=u(core.MODELS+4*mid)
        struct.pack_into('<4I',rows,i*STRIDE,actor,model,mid,i&1)
    for p,b in ((CODE,payload(previous)),(QUERY,query_code()),(ROWS,rows),
                (CONTROL,struct.pack('<7I',1,manager,n,0,0,0,0)+bytes(228))):
        expected[p-CODE:p-CODE+len(b)]=b
    if ram[CODE:END]!=expected:raise ValueError('Changed legacy placement code, descriptors or execution state')
    virtual=bytearray(ram);virtual[CODE:END]=bytes(END-CODE)
    struct.pack_into('<2I',virtual,HOOK,(2<<26)|(previous>>2),0)
    result=formation_build_memory(virtual,source,present_mask)
    # The existing outer pool/effect chain still calls CODE. Never replace it.
    result['blocks']=[dict(address=b['address'],expected_hex=ram[b['address']:b['address']+len(bytes.fromhex(b['data_hex']))].hex(),data_hex=b['data_hex'])
                      for b in result['blocks'] if b['address']!=HOOK]
    return result


# Public fresh preparation uses the reviewed formation implementation.
build_memory = formation_build_memory

def ready_manifest(ram, source='<offline-ready>'):
    """Historical archive reproduction: install the original start/placement pair."""
    held=start.build_memory(ram,source);virtual=bytearray(ram)
    for block in held['blocks']:
        p=block['address'];data=bytes.fromhex(block['data_hex']);virtual[p:p+len(data)]=data
    placement=legacy_build_memory(virtual,source); changed={}
    for manifest in (held,placement):
        for block in manifest['blocks']:
            p=block['address']
            for i,b in enumerate(bytes.fromhex(block['data_hex'])):changed[p+i]=b
    blocks=[]
    for p in sorted(changed):
        if not blocks or p!=blocks[-1][0]+len(blocks[-1][1]):blocks.append((p,bytearray()))
        blocks[-1][1].append(changed[p])
    placement['blocks']=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in blocks]
    placement['start_request']=start.REQUEST
    return placement


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--hold-ready',action='store_true')
    x=p.parse_args();ram=read_ram(x.source);r=(ready_manifest if x.hold_ready else build_memory)(ram,str(x.source))
    x.out.write_text(json.dumps(r,indent=2)+'\n');print(f'{x.out}: {len(r["blocks"])} guarded blocks; status{CONTROL:08X}')
