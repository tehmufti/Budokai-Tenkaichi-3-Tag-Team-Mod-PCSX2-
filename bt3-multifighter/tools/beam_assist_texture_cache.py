"""Deduplicate effect uploads while the helper-beam renderer owns this match.

The native image-only and palette-only producers often upload the same header
twice. Helpers multiply that waste and overflow the 256-block palette gap.
Merge requests for the same header, allocate both components from one cursor,
and retain the existing bounded queue and its native flush/reset functions.
Outside this match, the installed texture_queue_guard remains the predecessor.
"""
import struct
from prototype import Assembler
import tag_team_rush as tag
import texture_queue_guard as guard
import fresh_team_combat as core

BASE, END = 0x06570000, 0x06580000
STRIDE, TELEMETRY = 0x2000, BASE+0x7F00


def code(index):
    import beam_assist_effects as fx
    a=Assembler(BASE+index*STRIDE);tag.save(a)
    core.gate(a,'native');a.li(8,fx.CONTROL);a.lw(9,8);a.li(11,fx.MAGIC);a.branch(5,9,11,'native')
    a.lw(9,8,fx.C['manager']);a.lw(11,28,-22364);a.branch(5,9,11,'native')
    a.lw(9,8,fx.C['count']);a.branch(5,9,10,'native')
    a.lw(9,8,fx.C['ready']);a.li(11,1);a.branch(5,9,11,'native')
    a.move(16,4);a.move(17,5);a.move(18,6);a.lw(19,28,guard.QUEUE_GP)
    a.lw(20,19,guard.COUNT);a.li(8,guard.CAPACITY);a.r(0x2B,8,8,20);a.branch(5,8,0,'native')
    a.lw(21,16,8);a.move(22,19);a.move(23,0)
    a.label('search');a.branch(4,23,20,'new')
    a.lw(8,22);a.lw(8,8,8);a.branch(4,8,21,'found')
    a.addiu(22,22,16);a.addiu(23,23,1);a.jump('search')
    a.label('new');a.li(8,guard.CAPACITY);a.branch(4,20,8,'native')
    a.sw(16,22);a.li(8,-1);a.sw(8,22,4);a.sw(8,22,8);a.sw(0,22,12)
    a.addiu(20,20,1);a.sw(20,19,guard.COUNT)
    a.label('found')
    a.lw(8,19,0x804);a.lw(9,19,0x808);a.r(0x2B,10,8,9);a.branch(4,10,0,'cursor');a.move(8,9)
    a.label('cursor');a.lw(23,22,12)
    for flag,entryoff,headeroff in ((1,4,16),(2,8,20)):
        if not (flag & (3,1,2)[index]):continue
        a.i(12,9,23,flag);a.branch(5,9,0,f'have{flag}')
        if flag==1:
            # Different beam colours share immutable image pixels. Only their
            # palettes differ; upload aliases can reuse the image's GS blocks.
            a.lw(24,21,56);a.branch(4,24,0,'allocate_image')
            a.move(10,19);a.move(11,0)
            a.label('image_search');a.branch(4,11,20,'allocate_image')
            a.lw(12,10,12);a.i(12,12,12,1);a.branch(4,12,0,'next_image')
            a.lw(12,10);a.lw(12,12,8);a.lw(13,12,56);a.branch(5,13,24,'next_image')
            for off in (8,16,24):
                a.lw(13,12,off);a.lw(14,21,off);a.branch(5,13,14,'next_image')
            a.lw(12,10,4);a.sw(12,22,4);a.i(13,23,23,1);a.sw(23,22,12);a.jump('have1')
            a.label('next_image');a.addiu(10,10,16);a.addiu(11,11,1);a.jump('image_search')
            a.label('allocate_image')
        a.sw(8,22,entryoff);a.lw(9,21,headeroff);a.r(0x21,8,8,9)
        a.i(13,23,23,flag);a.sw(23,22,12)
        a.label(f'have{flag}')
    a.sw(8,19,0x804);a.sw(8,19,0x808)
    # Identical TEX0 arithmetic to the original producers, including the
    # descriptor mask and caller's TCC/TFX. AddClut returns only its block.
    if index==2:a.i(39,2,22,8)
    else:
        a.i(55,2,16,0)
        a.li(8,0xFFF80003);a.r(0x3C,8,0,8,0);a.li(9,0xFFFFC000)
        a.r(0x3C,9,0,9,0);a.r(0x3E,9,0,9,0);a.r(0x25,8,8,9)
        a.r(0x24,2,2,8);a.i(63,2,16,0)
        a.r(0x3C,8,0,17,2);a.r(0x25,2,2,8)
        a.r(0x3C,8,0,18,3);a.r(0x25,2,2,8)
        a.i(39,8,22,4);a.r(0x25,2,2,8)
        if index==0:
            a.i(39,8,22,8);a.r(0x3C,8,0,8,5);a.r(0x25,2,2,8)
    a.li(8,TELEMETRY);a.lw(9,8);a.addiu(9,9,1);a.sw(9,8)
    for value,off in ((20,4),(None,8)):
        if value is None:a.lw(10,19,0x804)
        else:a.move(10,value)
        a.lw(9,8,off);a.r(0x2B,11,9,10);a.branch(4,11,0,f'peak{off}');a.sw(10,8,off);a.label(f'peak{off}')
    tag.restore(a,2);a.jr()
    a.label('native');tag.restore(a);a.jump(guard.CODE+index*guard.STRIDE)
    result=a.finish();assert len(result)<STRIDE;return result


def pieces(ram):
    result=[]
    for i,entry in enumerate(guard.PRODUCERS[:3]):
        previous=struct.pack('<2I',(2<<26)|((guard.CODE+i*guard.STRIDE)>>2),0)
        installed=struct.pack('<2I',(2<<26)|((BASE+i*STRIDE)>>2),0)
        if bytes(ram[entry:entry+8]) not in (previous,installed):
            raise ValueError('Beam-assist texture cache needs the installed native queue guard')
        original=guard.wrapper_code(i)
        if bytes(ram[guard.CODE+i*guard.STRIDE:guard.CODE+i*guard.STRIDE+len(original)])!=original:
            raise ValueError('Texture queue guard predecessor changed')
        result.extend(((BASE+i*STRIDE,code(i)),(entry,installed)))
    return result
