"""Enable shared positional SFX for captured extras without sharing voice banks.

Only native sound types0/1 (banks4/8) bypass the old extra request suppression.
The native four-request budget, spatial attenuation, loop dedupe and all-extra
loop cleanup stay intact. Character banks, streamed voices and white overlays
retain their previous guards. Offline guarded add-on; no emulator connection.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler,ROOT,elf_reader
from camera_snapshot import read_ram
import multifighter_audio_effects as audio
import fresh_team_combat as core
from battle_mode_policy import ACTOR_COUNTS

CODE,CONTROL,END=0x077A0000,0x077AF000,0x077B0000
MAGIC=0x504F5331
HOOK=audio.REQUEST_HOOK
NATIVE=elf_reader(elf_path(ROOT))[2]
SAVED=(5,8,9,10,11,12,13,14,15)


def save(a):
    a.addiu(29,29,-0x50)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)


def restore(a):
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x50)


def counter(a,offset):
    a.li(8,CONTROL);a.lw(9,8,offset);a.addiu(9,9,1);a.sw(9,8,offset)


def payload():
    a=Assembler(CODE);save(a);audio.gate(a,'prior')
    a.li(8,CONTROL);a.lw(9,8);a.li(12,MAGIC);a.branch(5,9,12,'prior')
    a.lw(9,8,4);a.lw(12,28,-22364);a.branch(5,9,12,'prior')
    a.lw(13,8,8);a.li(9,core.MODE+4);a.lw(9,9);a.branch(5,9,13,'prior')
    a.i(11,9,6,2);a.branch(4,9,0,'prior')  # Only common banks0/1.
    a.move(15,5);a.move(14,0)
    a.i(11,9,15,2);a.branch(4,9,0,'physical')
    # Queued owner must be the actual physical actor, even when a native AI
    # slice temporarily gives an extra virtual role0/1. Validate both maps.
    a.li(8,core.PAIR);a.lw(9,8,4);a.branch(4,9,0,'prior')
    a.r(0,9,0,15,2);a.r(0x2D,8,8,9);a.lw(14,8,8);a.lw(15,8,16)
    a.i(12,9,15,1);a.branch(5,9,5,'prior')
    a.label('physical');a.i(11,9,15,2);a.branch(5,9,0,'prior')
    a.r(0x2B,9,15,13);a.branch(4,9,0,'prior')
    a.li(8,core.POINTERS);a.r(0,9,0,15,2);a.r(0x2D,8,8,9);a.lw(12,8)
    a.li(8,CONTROL+0x40);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,12,'prior')
    a.branch(4,14,0,'unalias');a.branch(5,14,12,'prior')
    counter(a,20);a.jump('allow')
    a.label('unalias');a.lw(8,12);a.branch(5,8,15,'prior')
    a.label('allow');counter(a,16)
    a.lw(8,28,-22364);a.lw(9,8,288);a.i(10,9,9,4);a.branch(5,9,0,'room')
    counter(a,24)
    a.label('room');a.i(63,15,29,0)  # Restore native a1 with actual owner ID.
    restore(a)
    for word in struct.unpack('<2I',NATIVE(HOOK,8)):a.emit(word)
    a.jump(HOOK+8)
    a.label('prior');restore(a);a.jump(audio.REQUEST)
    data=a.finish();assert len(data)<CONTROL-CODE;return data


def dependencies(ram):
    required=[(audio.REQUEST,audio.request_code(NATIVE(HOOK,8))),
        (audio.CLEANUP,audio.cleanup_code()),(audio.FLASH,audio.flash_code(NATIVE(audio.FLASH_HOOK,8))),
        (audio.CLEANUP_HOOK,struct.pack('<I',(3<<26)|(audio.CLEANUP>>2))),
        (audio.FLASH_HOOK,struct.pack('<2I',(2<<26)|(audio.FLASH>>2),0)),
        (A(0x1DA098),NATIVE(A(0x1DA098),audio.CLEANUP_HOOK-A(0x1DA098))),
        (audio.CLEANUP_HOOK+4,NATIVE(audio.CLEANUP_HOOK+4,A(0x1DA348)-audio.CLEANUP_HOOK-4)),
        (A(0x1D9A20),NATIVE(A(0x1D9A20),HOOK-A(0x1D9A20))),
        (HOOK+8,NATIVE(HOOK+8,A(0x1D9DB0)-HOOK-8)),
        (A(0x2EF290),struct.pack('<8i',4,8,16,32,-1,-1,-1,-1))]
    for address,data in required:
        if ram[address:address+len(data)]!=data:raise ValueError(f'Audio dependency changed:{address:08X}')


def build_memory(ram,config=None,source='<offline-memory>'):
    if len(ram)!=0x8000000:raise ValueError('Requires128 MiB RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.PAIR+4):
        raise ValueError('Requires active captured four/six team outside AI aliases')
    if not 0x100000<=manager<len(ram)-700 or u(manager)!=2:raise ValueError('Invalid native actor manager')
    aux=u(manager+12)
    if not 0x100000<=aux<=len(ram)-52*count:raise ValueError('Missing expanded loop records')
    if tuple(u(audio.CONTROL+i) for i in (0,4,8,12,28))!=(1,manager,aux,count,1):
        raise ValueError('Prior captured extra suppression/loop cleanup must remain enabled')
    actors=[u(core.POINTERS+4*i) for i in range(count)]
    if len(set(actors))!=count:raise ValueError('Duplicate actor ownership')
    for i,actor in enumerate(actors):
        if not 0x100000<=actor<=len(ram)-0x1600 or u(actor)!=i:raise ValueError('Invalid physical actor identity')
    dependencies(ram)
    code=payload();newhook=struct.pack('<2I',(2<<26)|(CODE>>2),0)
    if ram[HOOK:HOOK+8]==newhook:
        if ram[CODE:CODE+len(code)]!=code or tuple(u(CONTROL+i) for i in (0,4,8,12))!=(MAGIC,manager,count,aux):
            raise ValueError('Installed positional audio code/capture changed')
        if any(u(CONTROL+0x40+4*i)!=actor for i,actor in enumerate(actors)):
            raise ValueError('Installed positional audio actor capture changed')
        pieces=[]
    else:
        if ram[HOOK:HOOK+8]!=struct.pack('<2I',(2<<26)|(audio.REQUEST>>2),0):raise ValueError('Unexpected audio request chain')
        if any(ram[CODE:END]):raise ValueError('Positional audio reservation occupied')
        control=bytearray(0x100);struct.pack_into('<4I',control,0,MAGIC,manager,count,aux)
        for i,actor in enumerate(actors):struct.pack_into('<I',control,0x40+4*i,actor)
        pieces=[(CODE,code),(CONTROL,bytes(control)),(HOOK,newhook)]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        status='COMMON POSITIONAL EXTRA SFX; LIVE AUDIO VERIFICATION REQUIRED',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in pieces],
        telemetry=dict(qualified_requests=CONTROL+16,alias_owner_remaps=CONTROL+20,full_native_queue=CONTROL+24),
        limits=['Only shared types0/1 banks4/8 are enabled for extras.',
                'Native four-request budget, spatial attenuation, loop dedupe and stop cleanup are unchanged.',
                'Character-specific banks, streamed voices, unsafe audio channel IDs and white overlays retain prior guards.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    x=p.parse_args();x.out.write_text(json.dumps(build_memory(read_ram(x.source),source=x.source),indent=2)+'\n')
