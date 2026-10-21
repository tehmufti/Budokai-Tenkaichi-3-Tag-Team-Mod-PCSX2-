"""Visual-only beams for confirmed helpers, independent of tag attacks.

Eight private descriptors share one reviewed disc resource. Each emitter owns
its node, arena and palette; it follows a posed muzzle to the real clash point.
No native technique is started and no extra damage/collision is introduced.
All timing and ownership are guest state, once per simulation update.
"""
import struct
from pathlib import Path
from functools import lru_cache
from prototype import Assembler, ROOT
from native_map import A, SERIAL, CRC
import beam_struggle as fp
import beam_clash as clash
import beam_pose
import fresh_team_combat as core
import fusion_partner_lifecycle as full
import tag_team_rush as tag

BASE, END = 0x06500000, 0x06580000
TICK, INIT, SPAWN, GEOMETRY = BASE, BASE+0x1000, BASE+0x3000, BASE+0x5000
OWNED, STOP, IGNITE = BASE+0x6000, BASE+0x6400, BASE+0x6800
COLOR_INIT, COLOR_APPLY = BASE+0x8000, BASE+0x9000
CONTROL, ROWS, STRIDE, COUNT = BASE+0xA000, BASE+0xB000, 0x1000, 8
ARENAS, ARENA_SIZE = BASE+0x14000, 0x2000
RESOURCE, METADATA = BASE+0x24000, BASE+0x3F000
PALETTES, PALETTE_STRIDE, RECIPES, COLORS = BASE+0x40000, 0x6000, BASE+0x3E400, BASE+0x3E800
MAGIC, PREPARED = 0x42465831, 0x46585031
C=dict(magic=0,manager=4,count=8,ready=12,pool=16,spawned=20,failed=24,init_status=28)
R=dict(node=0,body=4,source=8,target=12,source_model=16,target_model=20,
       source_index=24,target_index=28,manager=32,source_bone=36,pool=40,
       stopping=44,ticks=48,prepared=52,source_character=56,target_character=60,
       ignited=64,serial=68,flavor=72,slot=76,attempted=80)
HEADER, META, DESC, CONTEXT, REQUEST = 0x100, 0x180, 0x220, 0x540, 0x7A0
SOURCE, DIRECTION, TARGET = 0x7E0, 0x7F0, 0x800
NODE_SIZE, BODY_SIZE = 64, 0x620
NATIVE_POOL_OFFSET=-22600
EMIT=A(0x16A7D0); COLLISION=A(0x16ACA8); MOTION=A(0x16AC40)
HARD_RETIRE=A(0x16A6F0); TERMINATE=A(0x16A900); BONE=A(0x2058E0)
CALLBACKS=A(0x2C3AD8); GET_POINT=A(0x174E98)
PALETTE, CELL, PACKET_SIZE, GOLD = 0x40, 0x500, 0x480, (255,196,32)


def row_guard(a, row, fail):
    a.li(8,ROWS);a.r(0x23,9,row,8);a.li(8,COUNT*STRIDE)
    a.r(0x2B,8,9,8);a.branch(4,8,0,fail)
    a.i(12,8,9,STRIDE-1);a.branch(5,8,0,fail)


def bounded(a, base, offsets, fail):
    for off in offsets:
        a.lw(8,base,off);a.li(9,0x7FFFFFFF);a.r(0x24,8,8,9)
        a.li(9,0x49742400);a.r(0x2B,8,9,8);a.branch(5,8,0,fail)


def publish(a, row, body):
    for source,dest in ((SOURCE,1440),(TARGET,1472),(TARGET,1456),(DIRECTION,1376)):
        for off in range(0,16,4):a.lw(8,row,source+off);a.sw(8,body,dest+off)
    fp.fconst(a,0,.25);a.i(57,0,body,1420)


def identity(a,row,fail):
    """Validate slot serial, physical actor and model before touching bones."""
    row_guard(a,row,fail)
    a.lw(12,row,R['slot']);a.li(8,fp.CONTROL+fp.SLOTS)
    a.r(0x23,9,12,8);a.i(11,8,9,COUNT*fp.SLOT_STRIDE);a.branch(4,8,0,fail)
    a.i(12,8,9,fp.SLOT_STRIDE-1);a.branch(5,8,0,fail)
    a.lw(8,12,fp.S['state']);a.li(9,fp.P_CONFIRMED);a.branch(5,8,9,fail)
    a.lw(8,12,fp.S['serial']);a.lw(9,row,R['serial']);a.branch(5,8,9,fail)
    a.li(10,clash.CONTROL);a.lw(9,10,24);a.branch(5,8,9,fail)
    a.lw(8,10,16);a.branch(4,8,0,fail)
    a.lw(8,12,fp.S['actor']);a.lw(9,row,R['source']);a.branch(5,8,9,fail)
    a.lw(22,row,R['source']);full.pointer(a,22,0x1600,fail)
    a.lw(8,22,2376);a.addiu(8,8,-304);a.i(11,8,8,3);a.branch(4,8,0,fail)
    fp.hp_row(a,12,22,fail,temp=13);a.lw(8,12);a.branch(6,8,0,fail)
    for indexoff,actoroff,modeloff,charoff in (
        (R['source_index'],R['source'],R['source_model'],R['source_character']),
        (R['target_index'],R['target'],R['target_model'],R['target_character'])):
        a.lw(10,row,indexoff);a.li(8,CONTROL);a.lw(8,8,C['count']);a.r(0x2B,8,10,8);a.branch(4,8,0,fail)
        a.lw(22,row,actoroff);full.pointer(a,22,0x1600,fail)
        a.lw(8,22);a.branch(5,8,10,fail)
        a.r(0,10,0,10,2);a.li(8,core.POINTERS);a.r(0x21,8,8,10);a.lw(8,8);a.branch(5,8,22,fail)
        a.lw(23,row,modeloff);full.pointer(a,23,0x1700,fail)
        a.lw(10,22,12);a.i(11,8,10,12);a.branch(4,8,0,fail)
        a.lw(8,23,16);a.branch(5,8,10,fail)
        a.r(0,10,0,10,2);a.li(8,core.MODELS);a.r(0x21,8,8,10);a.lw(8,8);a.branch(5,8,23,fail)
        a.lw(8,23,12);a.lw(9,row,charoff);a.branch(5,8,9,fail)
        for off in (4,8):a.lw(8,23,off);a.li(9,1);a.branch(5,8,9,fail)


def geometry_code():
    a=Assembler(GEOMETRY);tag.save(a);a.move(16,4);identity(a,16,'no')
    source,target,direction=0x300,0x310,0x320
    a.lw(17,16,R['source_model']);a.lw(19,16,R['source_bone'])
    a.li(8,31);a.branch(4,19,8,'bone');a.li(8,45);a.branch(4,19,8,'bone')
    a.li(8,54);a.branch(5,19,8,'no')
    a.label('bone');a.r(0,8,0,19,2);a.r(0x21,8,17,8);a.lw(10,8,3436)
    full.pointer(a,10,80,'no');bounded(a,10,(64,68,72),'no')
    a.lw(4,17,16);a.move(5,19);a.addiu(6,29,source);a.call(BONE)
    # The native getter leaves its output untouched if the clash has ended.
    for off in (0,4,8):a.li(8,0x7FC00000);a.sw(8,29,target+off)
    a.addiu(4,29,target);a.call(GET_POINT)
    bounded(a,29,(source,source+4,source+8,target,target+4,target+8),'no')
    fp.fconst(a,3,0.)
    for off in (0,4,8):
        a.i(49,0,29,target+off);a.i(49,1,29,source+off);fp.fop(a,1,0,0,1)
        a.i(57,0,29,direction+off);fp.fop(a,2,0,0,0);fp.fop(a,0,3,3,0)
    fp.fconst(a,1,.0001);fp.fop(a,0x34,0,1,3);a.branch(17,8,0,'no');fp.fop(a,4,3,3,3)
    for off in (0,4,8):
        a.i(49,0,29,direction+off);fp.fop(a,3,0,0,3);a.i(57,0,29,direction+off)
    a.sw(0,29,direction+12)
    for off in (source+12,target+12):a.li(8,0x3F800000);a.sw(8,29,off)
    for src,dst in ((source,SOURCE),(target,TARGET),(direction,DIRECTION)):
        for off in range(0,16,4):a.lw(8,29,src+off);a.sw(8,16,dst+off)
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();return a.finish()


def owned_code():
    """a0 exact private row -> v0 native body or0, no global battle gate.

    Node reuse is authenticated against its pool, exact body, private header
    and descriptor. A stale pointer can never stop a different native attack.
    """
    a=Assembler(OWNED);row_guard(a,4,'no')
    a.lw(10,4,R['node']);full.pointer(a,10,NODE_SIZE,'no')
    a.lw(11,4,R['pool']);a.lw(8,28,NATIVE_POOL_OFFSET);a.branch(5,11,8,'no')
    a.lw(8,10,32);a.branch(5,8,11,'no')
    a.lw(8,10,40);a.li(9,CALLBACKS);a.branch(5,8,9,'no')
    a.lw(2,10,56);full.pointer(a,2,BODY_SIZE,'no');a.lw(8,4,R['body']);a.branch(5,8,2,'no')
    a.lw(8,2);a.addiu(9,4,HEADER);a.branch(5,8,9,'no')
    a.lw(8,2,48);a.addiu(9,4,DESC);a.branch(5,8,9,'no')
    a.lw(8,2,1408);a.i(12,8,8,1);a.branch(4,8,0,'no');a.jr()
    a.label('no');a.move(2,0);a.jr();return a.finish()

def init_code(beam=None):
    """Parse the reviewed donor under eight bounded private bump arenas.

    Only the known 1/6/0/1 shape recipe is emitted. Its four shape arrays need
    2176 raw bytes per descriptor, well below each 8192-byte private arena.
    Original allocator rows/selector and model parameters are restored before
    any error is reported. The arena receipt is never a live-appearance claim.
    """
    if beam is None:
        a=Assembler(INIT);a.move(2,0);a.jr();return a.finish()
    if not beam.get('reviewed') or tuple(beam.get('descriptor_counts',()))!=(1,6,0,1) or beam.get('descriptor_raw_bytes')!=2176:
        raise ValueError('Native tag-beam descriptor has not been reviewed')
    resource,metadata=beam['resource_address'],beam['metadata_address']
    for p,size in ((resource,107456),(metadata,640)):
        if type(p) is not int or p%16 or not RESOURCE<=p<p+size<=PALETTES:
            raise ValueError('Native tag-beam resources escaped the asset reservation')
    a=Assembler(INIT);tag.save(a);core.gate(a,'no');a.li(16,CONTROL)
    a.lw(8,16,C['init_status']);a.branch(5,8,0,'no')
    for index in range(COUNT):
        a.li(8,ROWS+index*STRIDE);a.lw(8,8,R['node']);a.branch(5,8,0,'no')
    a.li(8,core.POINTERS);a.lw(21,8);full.pointer(a,21,0x1600,'no')
    a.lw(8,21);a.branch(5,8,0,'no')
    a.lw(20,21,12);a.i(11,8,20,12);a.branch(4,8,0,'no')
    a.r(0,8,0,20,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(21,8);full.pointer(a,21,0x1700,'no')
    a.lw(8,21,16);a.branch(5,8,20,'no')
    for offset in (4,8):a.lw(8,21,offset);a.li(9,1);a.branch(5,8,9,'no')
    a.lw(17,28,-22416);full.pointer(a,17,156,'no')
    a.lw(8,17,152);a.li(9,0x3FE);a.branch(5,8,9,'no')
    a.lw(22,28,NATIVE_POOL_OFFSET);full.pointer(a,22,24,'no')
    a.li(8,1);a.sw(8,16,C['init_status']);a.sw(0,16,C['ready'])
    a.li(8,MAGIC);a.sw(8,16,C['magic']);a.lw(8,28,-22364);a.sw(8,16,C['manager'])
    a.li(8,core.MODE);a.lw(8,8,4);a.sw(8,16,C['count']);a.sw(22,16,C['pool'])
    for off in (80,84,88,92,148):a.lw(8,17,off);a.sw(8,29,0x340+off-80 if off<148 else 0x350)
    a.lw(8,21,2348);a.sw(8,29,0x354)
    a.move(18,0);a.li(19,ROWS)
    a.label('descriptor')
    a.addiu(4,19,HEADER);a.move(5,0);a.li(6,0x720);a.call(A(0x2A9ACC))
    a.sw(20,19,HEADER);a.li(8,2);a.sw(8,19,HEADER+4);a.sw(20,19,HEADER+32)
    a.li(8,resource);a.sw(8,19,HEADER+28);a.addiu(8,19,META);a.sw(8,19,HEADER+36)
    a.li(8,metadata);a.sw(8,21,2348)
    a.move(4,20);a.li(5,2);a.addiu(6,19,META);a.move(7,0);a.call(A(0x14B108))
    a.lw(8,29,0x354);a.sw(8,21,2348)
    a.r(0,8,0,18,13);a.li(9,ARENAS);a.r(0x21,8,8,9)
    a.sw(8,17,80);a.sw(8,17,84);a.li(8,ARENA_SIZE);a.sw(8,17,88);a.sw(0,17,92)
    a.li(8,5);a.sw(8,17,148)
    a.addiu(4,19,HEADER);a.addiu(5,19,DESC);a.move(6,0);a.li(7,resource);a.move(8,0);a.li(9,4);a.call(A(0x14CEB0))
    a.lw(22,17,92)
    for off in (80,84,88,92,148):a.lw(8,29,0x340+off-80 if off<148 else 0x350);a.sw(8,17,off)
    a.li(8,ARENA_SIZE);a.r(0x2B,8,8,22);a.branch(5,8,0,'failed')
    a.lw(8,19,DESC+796);a.addiu(9,19,HEADER);a.branch(5,8,9,'failed')
    for group,count in enumerate((1,6,0,1)):
        a.lw(8,19,DESC+780+4*group);a.li(9,count);a.branch(5,8,9,'failed')
        if count:
            # Every parsed array must lie wholly in this descriptor's arena.
            # This also catches allocation failure before any emitter uses it.
            length=(520,1584,0,72)[group]
            a.lw(10,19,DESC+764+4*group);a.r(0,8,0,18,13);a.li(9,ARENAS);a.r(0x21,8,8,9)
            a.r(0x2B,9,10,8);a.branch(5,9,0,'failed');a.addiu(8,8,ARENA_SIZE-length)
            a.r(0x2B,9,8,10);a.branch(5,9,0,'failed');a.i(12,8,10,15);a.branch(5,8,0,'failed')
    if beam.get('color_plan'):
        a.move(4,19);a.call(COLOR_INIT);a.branch(4,2,0,'failed')
    a.li(8,31);a.sw(8,19,R['source_bone']);a.li(8,PREPARED);a.sw(8,19,R['prepared'])
    a.addiu(19,19,STRIDE);a.addiu(18,18,1);a.li(8,COUNT);a.branch(5,18,8,'descriptor')
    a.li(8,2);a.sw(8,16,C['init_status']);a.li(2,1);a.sw(2,16,C['ready']);a.jump('done')
    a.label('failed');a.li(8,100);a.sw(8,16,C['init_status'])
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();return a.finish()

def color_init_code(count):
    """a0 exact FX row -> clone headers/CLUTs and redirect PRIVATE arrays."""

    a=Assembler(COLOR_INIT);tag.save(a);a.move(16,4)
    row_guard(a,16,'no');a.li(8,ROWS);a.r(0x23,17,16,8);a.r(2,17,0,17,12)
    a.li(8,PALETTE_STRIDE);a.r(0x19,0,17,8);a.r(0x12,18,0,0);a.li(8,PALETTES);a.r(0x21,18,18,8)
    a.label('base');a.li(19,RECIPES);a.move(20,0)
    a.label('texture');a.lw(8,19);a.r(0,8,0,8,2);a.r(0x21,8,8,16);a.lw(21,8,DESC+764)
    a.lw(8,19,4);a.r(0x21,21,21,8);a.lw(8,19,8);a.r(0x21,21,21,8)
    a.lw(22,19,12);a.lw(8,21,8);a.branch(5,8,22,'no')
    a.lw(8,22,60);a.lw(9,19,16);a.branch(5,8,9,'no')
    a.move(8,22);a.move(9,18);a.li(10,16)
    a.label('header');a.lw(11,8);a.sw(11,9);a.addiu(8,8,4);a.addiu(9,9,4);a.addiu(10,10,-1);a.branch(5,10,0,'header')
    a.lw(8,22,60);a.addiu(9,18,PALETTE);a.li(10,PACKET_SIZE//4)
    a.label('packet');a.lw(11,8);a.sw(11,9);a.addiu(8,8,4);a.addiu(9,9,4);a.addiu(10,10,-1);a.branch(5,10,0,'packet')
    a.addiu(8,18,PALETTE);a.sw(8,18,60);a.sw(18,21,8)
    a.addiu(18,18,CELL);a.addiu(19,19,32);a.addiu(20,20,1);a.li(8,count);a.branch(5,20,8,'texture')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr()
    b=a.finish();assert len(b)<=COLOR_APPLY-COLOR_INIT;return b

def color_apply_code(count):
    """a0 exact FX row; fresh colors from immutable source at each spawn."""

    a=Assembler(COLOR_APPLY);tag.save(a);a.move(16,4);row_guard(a,16,'no');a.li(8,ROWS);a.r(0x23,17,16,8);a.r(2,17,0,17,12)
    a.li(8,PALETTE_STRIDE);a.r(0x19,0,17,8);a.r(0x12,18,0,0);a.li(8,PALETTES);a.r(0x21,18,18,8)
    a.label('row');a.lw(8,16,R['source_character']);a.i(11,9,8,256);a.li(17,GOLD[0]|GOLD[1]<<8|GOLD[2]<<16)
    a.branch(4,9,0,'color');a.r(0,8,0,8,2);a.li(9,COLORS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(4,8,0,'color');a.move(17,8)
    a.label('color');a.li(19,RECIPES);a.move(20,0)
    a.label('texture');a.lw(8,19,12);a.lw(21,8,60);a.lw(9,19,16);a.branch(5,21,9,'no');a.addiu(21,21,96);a.addiu(22,18,PALETTE+96);a.li(23,256)
    a.label('pixel');a.i(36,8,21,0);a.i(36,9,21,1);a.i(36,10,21,2);a.move(11,8);a.move(12,8)
    for reg in (9,10):
        label='min%d'%reg;a.r(0x2B,13,reg,11);a.branch(4,13,0,label);a.move(11,reg);a.label(label)
        label='max%d'%reg;a.r(0x2B,13,12,reg);a.branch(4,13,0,label);a.move(12,reg);a.label(label)
    a.r(0x23,12,12,11);a.move(14,17)
    for off in range(3):
        a.i(12,13,14,255);a.r(0x19,0,12,13);a.r(0x12,13,0,0);a.addiu(13,13,127);a.li(15,255)
        a.r(0x1B,0,13,15);a.r(0x12,13,0,0);a.r(0x21,13,13,11);a.i(40,13,22,off);a.r(2,14,0,14,8)
    a.i(36,8,21,3);a.i(40,8,22,3)
    a.addiu(21,21,4);a.addiu(22,22,4);a.addiu(23,23,-1);a.branch(5,23,0,'pixel')
    a.addiu(18,18,CELL);a.addiu(19,19,32);a.addiu(20,20,1);a.li(8,count);a.branch(5,20,8,'texture')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr()
    b=a.finish();assert len(b)<=CONTROL-COLOR_APPLY;return b


def ignite_code():
    a=Assembler(IGNITE);tag.save(a);a.move(16,4);a.call(OWNED)
    a.branch(4,2,0,'no');a.move(17,2);a.addiu(18,16,DESC);a.move(19,0)
    a.label('group');a.r(0,8,0,19,4);a.r(0x21,8,18,8)
    a.lw(10,8,12);a.branch(4,10,0,'next_group');a.i(36,22,8,20);full.pointer(a,10,16,'no')
    a.i(36,21,10,1);a.r(0x21,9,21,22);a.i(11,9,9,20);a.branch(4,9,0,'no')
    a.move(20,0);a.branch(4,21,0,'next_group')
    a.label('rule');a.r(0x21,8,22,20);a.r(0,8,0,8,6);a.lw(9,18,8);a.r(0x21,10,9,8)
    full.pointer(a,10,64,'no');a.i(36,8,10,8);a.li(9,1);a.branch(5,8,9,'next_rule')
    a.i(36,8,10,10);a.branch(4,8,9,'fire');a.li(9,5);a.branch(5,8,9,'next_rule')
    a.label('fire');a.move(4,18);a.addiu(5,17,656);a.move(6,0);a.move(7,19);a.move(8,20)
    a.move(9,0);a.move(10,0);a.li(11,2);a.call(A(0x14D8A8));a.branch(4,2,0,'next_rule')
    a.move(11,2);a.move(4,18);a.addiu(5,17,656);a.addiu(6,17,64);a.addiu(7,17,1456)
    a.addiu(8,17,1376);a.move(9,19);a.move(10,20);a.i(49,12,17,1420);a.call(A(0x14FF50))
    a.label('next_rule');a.addiu(20,20,1);a.branch(5,20,21,'rule')
    a.label('next_group');a.addiu(19,19,1);a.li(8,19);a.branch(5,19,8,'group')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();return a.finish()


def stop_code():
    """a0 row: retire only this row's authenticated emitter and children."""
    a=Assembler(STOP);tag.save(a);a.move(16,4);row_guard(a,16,'done');a.call(OWNED)
    a.branch(4,2,0,'clear');a.addiu(4,16,DESC);a.call(A(0x14D460))
    a.lw(4,16,R['node']);a.call(TERMINATE);a.lw(4,16,R['node']);a.call(HARD_RETIRE)
    a.li(8,1);a.sw(8,16,R['stopping']);a.jump('done')
    a.label('clear')
    for key in ('node','body','stopping'):a.sw(0,16,R[key])
    a.label('done');tag.restore(a);a.jr();return a.finish()


def spawn_code():
    """a0 private row/a1 confirmed assist slot; at most one attempt per serial."""
    a=Assembler(SPAWN);tag.save(a);a.move(16,4);a.move(17,5);row_guard(a,16,'no')
    a.lw(8,16,R['prepared']);a.li(9,PREPARED);a.branch(5,8,9,'no')
    a.lw(8,16,R['node']);a.branch(5,8,0,'no')
    a.sw(17,16,R['slot']);a.lw(8,17,fp.S['serial']);a.sw(8,16,R['serial'])
    a.lw(19,17,fp.S['phys']);a.lw(20,17,fp.S['k'])
    # Slot order determines the clash side, independently of player number.
    a.li(8,fp.CONTROL+fp.SLOTS);a.r(0x23,8,17,8);a.r(2,8,0,8,8);a.i(14,8,8,1)
    a.r(0,8,0,8,2);a.li(9,clash.INDICES);a.r(0x21,8,8,9);a.lw(20,8)
    a.li(8,CONTROL);a.lw(10,8,C['count']);a.branch(4,19,20,'no')
    for index,actoroff,modeloff,indexoff,charoff in (
        (19,R['source'],R['source_model'],R['source_index'],R['source_character']),
        (20,R['target'],R['target_model'],R['target_index'],R['target_character'])):
        a.r(0x2B,9,index,10);a.branch(4,9,0,'no')
        a.r(0,8,0,index,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(21,8)
        full.pointer(a,21,0x1600,'no');a.lw(8,21);a.branch(5,8,index,'no')
        a.sw(21,16,actoroff);a.sw(index,16,indexoff)
        a.lw(22,21,12);a.i(11,8,22,12);a.branch(4,8,0,'no')
        a.r(0,8,0,22,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(23,8);full.pointer(a,23,0x1700,'no')
        a.lw(8,23,16);a.branch(5,8,22,'no');a.sw(23,16,modeloff);a.lw(8,23,12);a.sw(8,16,charoff)
    a.lw(21,16,R['source_model']);a.lw(22,21,2348);full.pointer(a,22,640,'no')
    beam_pose.emit_select(a,21,22,'muzzle');a.branch(1,2,0,'no')
    a.li(19,45);a.branch(4,3,0,'hands');a.addiu(8,3,-2);a.r(0,8,0,8,2)
    a.r(0x21,8,22,8);a.lw(8,8);a.i(12,8,8,0x2000);a.branch(4,8,0,'hands')
    a.li(19,54);a.jump('selected')
    a.label('hands');a.lw(22,16,R['target_model'])
    for reg,bone in ((12,31),(13,45)):
        a.lw(reg,21,3436+4*bone);full.pointer(a,reg,80,'no');bounded(a,reg,(64,68,72),'no')
    bounded(a,21,(2416,2420,2424),'no');bounded(a,22,(2416,2420,2424),'no')
    fp.fconst(a,3,0.)
    for off in (0,4,8):
        a.i(49,0,13,64+off);a.i(49,1,12,64+off);fp.fop(a,1,0,0,1)
        a.i(49,1,22,2416+off);a.i(49,2,21,2416+off);fp.fop(a,1,1,1,2)
        fp.fop(a,2,0,0,1);fp.fop(a,0,3,3,0)
    a.li(19,31);fp.fconst(a,0,0.);fp.fop(a,0x34,0,0,3)
    a.branch(17,8,0,'selected');a.li(19,45)
    a.label('selected');a.sw(19,16,R['source_bone'])
    a.move(4,16);a.call(GEOMETRY);a.branch(4,2,0,'no')
    a.move(4,16);a.call(COLOR_APPLY);a.branch(4,2,0,'no')
    a.lw(19,28,NATIVE_POOL_OFFSET);full.pointer(a,19,24,'no');a.lw(10,19,12)
    full.pointer(a,10,64,'no');a.lw(8,10,32);a.branch(5,8,19,'no')
    a.lw(8,16,R['source_model']);a.lw(8,8,16);a.sw(8,16,HEADER);a.sw(8,16,HEADER+32)
    a.addiu(4,16,CONTEXT);a.move(5,0);a.li(6,592);a.call(A(0x2A9ACC))
    for phase in (0,1):
        a.addiu(4,16,CONTEXT);a.li(5,phase);a.lw(6,16,R['source_bone']);a.move(7,0);a.call(A(0x1517A0))
    a.addiu(4,16,HEADER);a.addiu(5,16,CONTEXT);a.call(A(0x1512C8))
    for off,ptr in ((0,HEADER),(4,DESC),(8,CONTEXT),(12,SOURCE),(16,DIRECTION)):
        a.addiu(8,16,ptr);a.sw(8,16,REQUEST+off)
    # Zero native lifetime means the owner explicitly retires this emitter.
    # A timed ten-second projectile disappears before a long clash finishes.
    for off,value in ((20,0),(24,1),(28,1),(32,1),(36,0),(40,0x3E800000),(44,0),(48,0)):
        a.li(8,value);a.sw(8,16,REQUEST+off)
    a.addiu(4,16,REQUEST);a.call(EMIT);a.branch(4,2,0,'no');a.sw(2,16,R['node'])
    full.pointer(a,2,NODE_SIZE,'unknown');a.lw(8,2,56);a.sw(8,16,R['body']);a.sw(19,16,R['pool'])
    a.move(4,16);a.call(OWNED);a.branch(4,2,0,'unknown')
    a.lw(4,16,R['node']);a.li(5,1);a.call(COLLISION);a.branch(4,2,0,'stop')
    a.lw(4,16,R['node']);a.li(5,1);a.call(MOTION);a.branch(4,2,0,'stop')
    a.lw(21,16,R['body']);publish(a,16,21)
    for phase in (0,1):
        a.addiu(4,21,64);a.li(5,phase);a.lw(6,16,R['source_bone']);a.move(7,0);a.call(A(0x1517A0))
    a.addiu(4,16,HEADER);a.addiu(5,21,64);a.call(A(0x1512C8))
    a.move(4,16);a.call(IGNITE);a.branch(4,2,0,'stop')
    a.li(8,CONTROL);a.lw(9,8,C['spawned']);a.addiu(9,9,1);a.sw(9,8,C['spawned'])
    a.li(2,1);a.jump('done')
    a.label('stop');a.move(4,16);a.call(STOP);a.jump('no')
    a.label('unknown');a.li(8,CONTROL);a.sw(0,8,C['ready'])
    a.label('no');a.li(8,CONTROL);a.lw(9,8,C['failed']);a.addiu(9,9,1);a.sw(9,8,C['failed']);a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();return a.finish()


def tick_code():
    a=Assembler(TICK);tag.save(a);a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done')
    core.gate(a,'done');a.li(16,CONTROL);a.lw(8,16,C['count']);a.branch(5,8,10,'done')
    a.lw(8,16,C['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'done')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    a.lw(8,16,C['init_status']);a.branch(5,8,0,'ready');a.call(INIT)
    a.label('ready');a.lw(8,16,C['ready']);a.li(9,1);a.branch(5,8,9,'done')
    a.lw(8,16,C['pool']);a.lw(9,28,NATIVE_POOL_OFFSET);a.branch(5,8,9,'done')
    a.call(fp.RUNNING);a.move(20,2);a.li(8,fp.CONTROL);a.lw(8,8,fp.C['assist'])
    a.branch(5,8,0,'slots');a.move(20,0)
    a.label('slots');a.li(16,ROWS);a.li(17,fp.CONTROL+fp.SLOTS);a.move(18,0)
    a.label('slot');a.branch(4,20,0,'stop')
    a.lw(8,17,fp.S['state']);a.li(9,fp.P_CONFIRMED);a.branch(5,8,9,'stop')
    a.move(4,16);a.call(OWNED);a.branch(4,2,0,'start');a.move(19,2)
    a.addiu(4,16,DESC);a.call(A(0x14D460));a.lw(8,16,R['stopping']);a.branch(5,8,0,'stop')
    a.move(4,16);a.call(GEOMETRY);a.branch(4,2,0,'stop');publish(a,16,19);a.jump('next')
    a.label('start');a.sw(0,16,R['node']);a.sw(0,16,R['body']);a.sw(0,16,R['stopping'])
    a.lw(8,17,fp.S['serial']);a.lw(9,16,R['attempted']);a.branch(4,8,9,'next');a.sw(8,16,R['attempted'])
    a.move(4,16);a.move(5,17);a.call(SPAWN);a.jump('next')
    a.label('stop');a.move(4,16);a.call(STOP)
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(17,17,fp.SLOT_STRIDE);a.addiu(18,18,1)
    a.li(8,COUNT);a.branch(5,18,8,'slot')
    a.label('done');tag.restore(a);a.jr();return a.finish()


@lru_cache(maxsize=5)
def _assets(path, size, modified):
    import tag_rush_assets, tag_rush_colors
    beam=tag_rush_assets.read_native_beam_asset(Path(path))
    plan=tag_rush_colors.recipe(beam['resource'],RESOURCE,{i:{} for i in range(256)})
    return dict(beam,resource_address=RESOURCE,metadata_address=METADATA,color_plan=plan)


def pieces(beam):
    plan=beam['color_plan'];count=len(plan['textures'])
    from tag_rush_colors import STRIDES
    recipes=b''.join(struct.pack('<8I',g,STRIDES[g]*i,16*t,p,pal,0,0,0) for g,i,t,p,pal in plan['textures'])
    programs=[(TICK,tick_code()),(INIT,init_code(beam)),(SPAWN,spawn_code()),(GEOMETRY,geometry_code()),
              (OWNED,owned_code()),(STOP,stop_code()),(IGNITE,ignite_code()),
              (COLOR_INIT,color_init_code(count)),(COLOR_APPLY,color_apply_code(count))]
    limits=(INIT,SPAWN,GEOMETRY,OWNED,STOP,IGNITE,COLOR_INIT,COLOR_APPLY,CONTROL)
    for (p,data),limit in zip(programs,limits):
        if p+len(data)>limit:raise ValueError('Beam-assist effect program exceeded its reservation')
    return programs+[(RECIPES,recipes),(COLORS,plan['colors'])]


def build_memory(ram,source='<prepared>',iso=None):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if len(ram)!=0x8000000:raise ValueError('Beam-assist effects require 128 MiB captured RAM')
    if u(fp.CONTROL)!=fp.MAGIC or not u(fp.CONTROL+fp.C['assist']):return dict(blocks=[])
    # Older/custom prepared states can use the struggle-handler input fallback
    # without the frame chain. Do not install persistent emitters without their
    # once-per-frame owner, which also retires them after the clash has ended.
    if not u(fp.CONTROL+fp.C['frame_prev']):return dict(blocks=[])
    if iso is None:
        from tag_rush_install import selected_iso
        iso=selected_iso()
    path=Path(iso).resolve(strict=True);st=path.stat();beam=_assets(str(path),st.st_size,st.st_mtime_ns)
    import beam_assist_texture_cache as texture_cache
    code=pieces(beam)+texture_cache.pieces(ram)
    manager=u(fp.CONTROL+fp.C['manager']);count=u(fp.CONTROL+fp.C['count'])
    if u(CONTROL)==MAGIC:
        if (u(CONTROL+4),u(CONTROL+8))!=(manager,count):raise ValueError('Beam-assist effects belong to another match')
        for p,data in code:
            if bytes(ram[p:p+len(data)])!=data:raise ValueError('Beam-assist effect program changed')
        cursor=0
        for off,size in sorted(beam['mutable_ranges']):
            if bytes(ram[RESOURCE+cursor:RESOURCE+off])!=beam['resource'][cursor:off]:
                raise ValueError('Beam-assist effect resource changed')
            cursor=off+size
        if bytes(ram[RESOURCE+cursor:RESOURCE+len(beam['resource'])])!=beam['resource'][cursor:]:
            raise ValueError('Beam-assist effect resource changed')
        if bytes(ram[METADATA:METADATA+len(beam['metadata'])])!=beam['metadata']:
            raise ValueError('Beam-assist effect metadata changed')
        return dict(blocks=[])
    if any(ram[BASE:END]):raise ValueError('Beam-assist effect reservation is occupied')
    data=code+[(CONTROL,struct.pack('<3I',MAGIC,manager,count)),
               (RESOURCE,beam['resource']),(METADATA,beam['metadata'])]
    spans=sorted((p,p+len(b)) for p,b in data if p>=BASE)
    if any(a<BASE or b>END for a,b in spans) or any(b>c for (_,b),(c,_) in zip(spans,spans[1:])):
        raise ValueError('Beam-assist effect assets overlap or leave their reservation')
    return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[dict(address=p,
        expected_hex=bytes(ram[p:p+len(b)]).hex(),data_hex=b.hex()) for p,b in data])
