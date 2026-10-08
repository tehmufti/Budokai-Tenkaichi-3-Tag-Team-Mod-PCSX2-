"""Capture ordinary extra damaged-costume requests for a bounded reload worker.

The reviewed skip/ready behavior remains in force until a worker claims and
commits the request. No transformation/fusion/tag gate is removed. The hook is
dormant by default; a later reviewed host/native worker must enable it.
"""
from native_map import CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

import extra_loader_guard as previous
from prototype import Assembler,ROOT,elf_reader
from camera_snapshot import read_ram
import extra_reload_preload as preloader
import battle_mode_policy as policy

CODE,CONTROL,RECORDS,END=0x07640000,0x0764F000,0x0764F100,0x07650000
STRIDE=64
# One row per extra (physical 2..count-1); the host reads every row it may hold.
ROWS=policy.MAX_ACTORS-2
assert RECORDS+ROWS*STRIDE<=END,'Request rows overrun their reservation'
FUSION_CONTROL,FUSION_RESERVED=0x077DF000,0x077D9000
# Row: generation,status,actor,actualID,model,char,costume,damaged,anim,combat,
# sound,physical,oldresource,result,reserved,reserved. Status1 pending,2 claimed.


def payload():
    a=Assembler(CODE);a.addiu(29,29,-0x70)
    for i,r in enumerate((11,12,13,14,15,16,17,24,25)):a.i(63,r,29,8*i)
    for off,r in ((0x48,31),(0x50,2),(0x58,4)):a.i(63,r,29,off)
    a.li(16,CONTROL);a.lw(11,16);a.branch(4,11,0,'done')
    a.lw(11,16,4);a.lw(12,28,-22364);a.branch(5,11,12,'done')
    a.li(11,previous.MODE)
    for off in (0,):a.lw(12,11,off);a.branch(4,12,0,'done')
    a.lw(12,11,8);a.lw(13,16,4);a.branch(5,12,13,'done')
    a.lw(12,11,4);a.lw(13,11,12);a.branch(5,12,13,'done')
    a.lw(13,16,8);a.branch(5,12,13,'done')
    a.i(11,11,4,2);a.branch(5,11,0,'done')
    a.r(0x2B,11,4,12);a.branch(4,11,0,'done')
    a.r(0,11,0,4,2);a.li(12,preloader.core.POINTERS);a.r(0x2D,12,12,11)
    a.lw(14,12);a.branch(4,14,0,'done');a.lw(11,14);a.branch(5,11,4,'done')
    a.lw(15,14,12);a.i(11,11,15,12);a.branch(4,11,0,'done')
    a.r(0,11,0,15,2);a.li(12,preloader.core.MODELS);a.r(0x2D,12,12,11)
    a.lw(17,12);a.branch(4,17,0,'done');a.lw(11,17,16);a.branch(5,11,15,'done')
    a.lw(11,17,12);a.branch(5,11,5,'unsupported')
    a.addiu(11,0,1);a.branch(5,7,11,'unsupported')
    a.i(11,11,6,9);a.branch(4,11,0,'unsupported')
    # Native damage reloads may borrow animation/combat/sound (-1), or repeat
    # the same character. They must never request a different form here.
    for reg in (8,9,10):
        a.r(0,12,0,reg,0);a.addiu(11,0,-1)
        a.branch(4,12,11,f'ok{reg}');a.branch(5,12,5,'unsupported');a.label(f'ok{reg}')
    # A native leader fusion owns its chosen real teammate during its queued
    # and running animation. Do not start a competing serial costume job.
    a.li(11,FUSION_CONTROL);a.lw(12,11);a.addiu(13,0,1);a.branch(5,12,13,'not_reserved')
    a.lw(12,11,4);a.lw(13,28,-22364);a.branch(5,12,13,'not_reserved')
    a.move(4,14);a.call(FUSION_RESERVED);a.i(55,4,29,0x58);a.branch(5,2,0,'done')
    a.label('not_reserved')
    a.addiu(11,4,-2);a.r(0,11,0,11,6);a.li(12,RECORDS);a.r(0x2D,24,12,11)
    a.lw(11,24,4);a.addiu(12,0,2);a.branch(4,11,12,'busy')
    a.sw(0,24,4)  # Invalidate the old snapshot before replacing its payload.
    a.lw(11,24);a.addiu(11,11,1);a.branch(5,11,0,'generation');a.addiu(11,0,1)
    a.label('generation');a.sw(11,24)
    for off,r in ((8,14),(12,15),(16,17),(20,5),(24,6),(28,7),(32,8),(36,9),(40,10),(44,4)):
        a.sw(r,24,off)
    a.lw(11,17,20);a.sw(11,24,48);a.sw(0,24,52);a.sw(0,24,56);a.sw(0,24,60)
    a.addiu(11,0,1);a.sw(11,24,4)  # Publish the complete request last.
    a.lw(11,16,12);a.addiu(11,11,1);a.sw(11,16,12);a.jump('done')
    a.label('unsupported');a.lw(11,16,16);a.addiu(11,11,1);a.sw(11,16,16);a.jump('done')
    a.label('busy');a.lw(11,16,20);a.addiu(11,11,1);a.sw(11,16,20)
    a.label('done')
    for i,r in enumerate((11,12,13,14,15,16,17,24,25)):a.i(55,r,29,8*i)
    for off,r in ((0x48,31),(0x50,2),(0x58,4)):a.i(55,r,29,off)
    a.addiu(29,29,0x70);a.jump(previous.PUSH)
    code=a.finish();assert len(code)<0x1000;return code


def build_memory(ram,source='<offline-captured>'):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    world=preloader.capture(ram,2)
    if any(ram[CODE:END]):raise ValueError('Reload request reservation occupied')
    if u(previous.PUSH_HOOK)!=(2<<26)|(previous.PUSH>>2) or u(previous.PUSH_HOOK+4):
        raise ValueError('Expected reviewed extra reload push guard')
    if ram[previous.PUSH:previous.PUSH+len(previous.push_code())]!=previous.push_code():
        raise ValueError('Prior skip/ready semantics changed')
    control=struct.pack('<6I',0,world['manager'],world['count'],0,0,0)
    pieces=[(CODE,payload()),(CONTROL,control),(RECORDS,bytes((policy.emitted_actors()-2)*STRIDE)),
            (previous.PUSH_HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,records=RECORDS,
                stride=STRIDE,world=world,status='DORMANT DAMAGE REQUEST CAPTURE; NO AUTOMATIC COMMIT ENABLED',
                blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);x=p.parse_args()
    x.out.write_text(json.dumps(build_memory(read_ram(x.source),x.source),indent=2)+'\n');print(x.out)
