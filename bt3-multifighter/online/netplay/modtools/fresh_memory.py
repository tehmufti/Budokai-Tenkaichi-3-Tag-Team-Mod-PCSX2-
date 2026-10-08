"""Initialize the verified extended heap in a fresh, native two-actor match.

The game runs its original update while CPU input is held during preparation.
An address-mirroring canary passes before the native heap allocator is invoked.
Only builds guarded manifests; the caller performs paused install/save/reload.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from selected_team_capture import capture
from heap128 import emit_canary, emit_heap, START, END, START1, END1

CODE, TRAMPOLINE, CONTROL, HOOK = 0x07360000, 0x07361000, 0x07361800, A(0x1C2A28)


def payload():
    a=Assembler(CODE)
    a.addiu(29,29,-0x40)
    for reg,off in ((16,0),(17,8),(18,16),(31,24)):
        a.i(63,reg,29,off)
    a.li(16,CONTROL)
    a.lw(8,16,80);a.branch(4,8,0,'original')
    a.lw(8,16,84);a.lw(9,28,-22364);a.branch(5,8,9,'original')
    a.lw(8,9);a.addiu(9,0,2);a.branch(5,8,9,'original')
    # CPU, digital and analog inputs remain off until later explicit activation.
    for off in (88,92):
        a.lw(8,16,off)
        for field in (0x1278,0x127C,0x1280,0x1284):a.sw(0,8,field)
    a.label('original');a.call(TRAMPOLINE);a.i(63,2,29,32)
    a.li(16,CONTROL)
    a.lw(8,16,80);a.branch(4,8,0,'done')
    a.lw(8,16,84);a.lw(9,28,-22364);a.branch(5,8,9,'done')
    a.lw(8,9);a.addiu(9,0,2);a.branch(5,8,9,'done')
    a.lw(8,16);a.branch(4,8,0,'canary')
    a.addiu(9,0,5);a.branch(5,8,9,'done')
    a.addiu(8,0,2);a.sw(8,16,4)
    emit_heap(a)
    a.label('canary');a.addiu(8,0,1);a.sw(8,16,4)
    emit_canary(a);a.jump('result')
    a.label('result');a.sw(17,16)
    a.label('done');a.i(55,2,29,32)
    for reg,off in ((16,0),(17,8),(18,16),(31,24)):
        a.i(55,reg,29,off)
    a.addiu(29,29,0x40);a.jr()
    code=a.finish();assert CODE+len(code)<TRAMPOLINE
    return code


def heap_region_used(r):
    """Exactly any(r[START:END]): count zero bytes in place instead of copying
    and iterating 64 MiB (about 167 ms down to 14 ms on a 128 MiB image)."""
    return r.count(0,START,END)!=max(0,min(END,len(r))-START)


def build(source):
    r=read_ram(source);selection=capture(r)
    u=lambda p:struct.unpack_from('<I',r,p)[0]
    if u(START1) or u(END1) or heap_region_used(r):
        raise ValueError('Fresh extended heap region must be entirely unused')
    if any(r[CODE:CONTROL+128]):raise ValueError('Fresh memory reservation occupied')
    _,_,native=elf_reader(elf_path(ROOT))
    for p,n in ((HOOK,8),(A(0x254E30),0x38),(A(0x2554D8),0x30),(A(0x255508),0x68)):
        if r[p:p+n]!=native(p,n):raise ValueError(f'Changed native helper {p:08X}')
    original=native(HOOK,8)
    for word in struct.unpack('<2I',original):
        if word>>26 in(1,2,3,4,5,6,7,20,21):raise ValueError('Native prologue requires branch relocation')
    trampoline=original+struct.pack('<2I',(2<<26)|((HOOK+8)>>2),0)
    control=bytearray(128)
    struct.pack_into('<4I',control,80,1,selection['native_manager'],
                     selection['leaders'][0]['actor'],selection['leaders'][1]['actor'])
    for i,row in enumerate(selection['leaders']):
        struct.pack_into('<I',control,96+4*i,u(row['actor']+0x1278))
    payloads=[(TRAMPOLINE,trampoline),(CODE,payload()),(CONTROL,bytes(control))]
    for row in selection['leaders']:
        for off in(0x1278,0x127C,0x1280,0x1284):payloads.append((row['actor']+off,bytes(4)))
    payloads.append((HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0)))
    return {'serial':SERIAL,'crc':CRC,'source':str(Path(source).resolve()),
            'status':'FRESH EXTENDED HEAP BOOTSTRAP; EXPOSURE REMAINS NATIVE TWO',
            'control':CONTROL,'trampoline':TRAMPOLINE,'code':CODE,
            'blocks':[{'address':p,'expected_hex':r[p:p+len(b)].hex(),'data_hex':b.hex()} for p,b in payloads],
            'control_fields':{'status':0,'command':4,'preparation_enabled':80,'captured_manager':84,'leader0':88,'leader1':92,
                              'original_cpu0':96,'original_cpu1':100},
            'requirements':['Require status20 before loading resources or creating actors.',
                            'Clear control+80 when activating combat; while enabled it holds both leader inputs off.',
                            'Restore the pre-install checkpoint on error; do not reinitialize an owned heap.']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path);x=p.parse_args()
    x.out.write_text(json.dumps(build(x.source),indent=2)+'\n');print(x.out)
