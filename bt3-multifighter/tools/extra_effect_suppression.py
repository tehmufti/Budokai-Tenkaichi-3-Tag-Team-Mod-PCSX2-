"""Suppress cosmetic families whose native trackers only contain two models.

Offline only. Six creation front doors and all fifteen tracker set/get/clear
helpers are guarded. Native destructor resource release still executes before
its tracker-clear tail, so this does not skip required payload cleanup.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram

PREDICATE, CLEAR_PREDICATE, CONTROL, WRAPPERS = 0xDA000, 0xDA200, 0xDA400, 0xDB000
CREATORS = ((A(0x1762A8),0),(A(0x177480),16),(A(0x171C78),16),(A(0x1749F0),0),(A(0x15EDF0),0),(A(0x15EEC0),0))
TRACKERS = ((A(0x19BA98),A(0x19BAD8),A(0x19BAC0)), (A(0x19BAF0),A(0x19BB38),A(0x19BB18)),
            (A(0x19BB50),A(0x19BB98),A(0x19BB78)), (A(0x19BBB0),A(0x19BBF8),A(0x19BBD8)),
            (A(0x19BC10),A(0x19BC58),A(0x19BC38)))
ROWS = [(p,'create',offset) for p,offset in CREATORS]
ROWS += [(p,kind,None) for row in TRACKERS for p,kind in zip(row,('set','get','clear'))]


def predicate_code(clear=False):
    a=Assembler(CLEAR_PREDICATE if clear else PREDICATE)
    a.i(11,2,4,2);a.branch(5,2,0,'native')
    a.li(2,CONTROL);a.lw(3,2);a.branch(4,3,0,'native')
    a.lw(3,2,4);a.lw(2,28,-22364);a.branch(5,2,3,'native')
    if not clear:
        for address in (0xD8080,0xB3088,0xF609C):
            a.li(2,address);a.lw(2,2);a.branch(4,2,0,'native')
    # Clear remains suppressed while this captured manager tears down. Its
    # native table still has two rows after exposure is withdrawn.
    a.addiu(2,0,1);a.jr()
    a.label('native');a.move(2,0);a.jr()
    return a.finish()


def wrapper_code(index, original):
    entry,kind,offset=ROWS[index];a=Assembler(WRAPPERS+index*0x100)
    a.addiu(29,29,-0x20)
    for reg,disp in ((31,0),(4,8),(3,16)):a.i(63,reg,29,disp)
    if offset is not None:
        a.branch(4,4,0,'native_restore');a.lw(4,4,offset)
    a.call(CLEAR_PREDICATE if kind=='clear' else PREDICATE)
    a.branch(4,2,0,'native_restore')
    for reg,disp in ((31,0),(4,8),(3,16)):a.i(55,reg,29,disp)
    a.addiu(29,29,0x20);a.move(2,0);a.jr()
    a.label('native_restore')
    for reg,disp in ((31,0),(4,8),(3,16)):a.i(55,reg,29,disp)
    a.addiu(29,29,0x20)
    for word in struct.unpack('<2I',original):
        assert word>>26 not in (1,2,3,4,5,6,7), 'Cannot relocate a branching prologue'
        a.emit(word)
    a.jump(entry+8)
    code=a.finish();assert len(code)<=0x100;return code


def build(source):
    ram=read_ram(source);assert len(ram)==0x8000000
    _,_,readelf=elf_reader(elf_path(ROOT))
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager=u(A(0x2FEB14));assert manager and u(0xD8088)==manager
    assert not any(ram[PREDICATE:WRAPPERS+len(ROWS)*0x100])
    payloads=[(PREDICATE,predicate_code(),'Active extra-model predicate'),
              (CLEAR_PREDICATE,predicate_code(True),'Preserve bounds while captured manager cleans up'),
              (CONTROL,struct.pack('<2I',1,manager),'Enable only for this captured actor manager')]
    hooks=[]
    for i,(entry,kind,_) in enumerate(ROWS):
        original=readelf(entry,8);assert ram[entry:entry+8]==original,f'Changed native helper{entry:x}'
        p=WRAPPERS+i*0x100;payloads.append((p,wrapper_code(i,original),f'Bound cosmetic {kind} at{entry:x}'))
        hooks.append((entry,struct.pack('<2I',(2<<26)|(p>>2),0),f'Install cosmetic {kind} guard'))
    blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex(),purpose=why) for p,b,why in payloads+hooks]
    return dict(serial=SERIAL,crc=CRC,source=str(Path(source).resolve()),
                status='OPTIONAL SCOPED EXTRA COSMETIC SUPPRESSION; OFFLINE TESTED',blocks=blocks,
                helper_rows=[dict(entry=p,kind=k,argument_offset=o) for p,k,o in ROWS],
                evidence=['19BA20 allocates only80 tracker bytes: five kinds times two models times8bytes.',
                          'Native destruction tails175F38/1771D0/171938/174584/15E944 call the five guarded clear helpers.'],
                requirements=['Restore a pre-stall snapshot; this does not repair earlier out-of-bounds effects.',
                              'Apply paused and save/reload to invalidate EE code caches.'],
                limitations=['Extra models lose these five tracked cosmetic effect families.',
                             'Leaders0/1 retain their native effects.',
                             'Other effect systems and shader-node initialization are separate.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ram',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    x=p.parse_args();x.out.write_text(json.dumps(build(x.ram),indent=2)+'\n');print(x.out)
