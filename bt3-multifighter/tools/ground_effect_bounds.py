"""Bound three native cosmetic commands whose owner tables have two rows.

196F88/197148 track dust effects in the last sixteen bytes of a25408-byte
manager. 140358 controls the two surface-effect rows consumed by1418D8.
These guards only affect the captured prototype world and do no live writes.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram

BASE, CONTROL = 0x0723C000, 0x0723C800
ENTRIES = (A(0x196F88), A(0x197148), A(0x140358))
GLOBALS = (A(0x2FEAA0), A(0x2FEAA0), A(0x2FF1A8))


def wrapper(index, original):
    a = Assembler(BASE+index*0x200)
    # Only v0 is caller-clobbered; save v1 so relocated native instructions
    # see all original inputs, including floating-point arguments.
    a.addiu(29, 29, -16); a.i(63, 3, 29, 0)
    a.i(11, 2, 4, 2); a.branch(5, 2, 0, 'native')
    a.li(2, CONTROL); a.lw(3, 2); a.branch(4, 3, 0, 'native')
    a.lw(3, 2, 4); a.lw(2, 28, -22364); a.branch(5, 2, 3, 'native')
    a.li(2, CONTROL); a.lw(3, 2, 8+4*index)
    a.li(2, GLOBALS[index]); a.lw(2, 2); a.branch(5, 2, 3, 'native')
    # Bounds persist through exposure withdrawal until this world's managers
    # change. No unsupported row is ever touched by a late stop command.
    a.li(2, CONTROL); a.lw(3, 2, 32+4*index); a.addiu(3, 3, 1)
    a.sw(3, 2, 32+4*index); a.sw(4, 2, 48+4*index)
    a.i(55, 3, 29, 0); a.addiu(29, 29, 16); a.move(2, 0); a.jr()
    a.label('native'); a.i(55, 3, 29, 0); a.addiu(29, 29, 16)
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21)
        a.emit(word)
    a.jump(ENTRIES[index]+8)
    code = a.finish(); assert len(code) <= 0x200
    return code


def build(source):
    ram = read_ram(source)
    if len(ram) != 0x8000000:
        raise ValueError('Expected128MiB captured team checkpoint')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(A(0x2FEB14))
    if not manager or u(0xD8088) != manager or u(0xC4004):
        raise ValueError('Captured team manager required outside a virtual AI slice')
    if any(ram[BASE:CONTROL+64]):
        raise ValueError('Ground effect reservation occupied')
    _, _, native = elf_reader(elf_path(ROOT))
    # Fixed allocation and two-iteration consumer, independently checked in
    # native ELF. Managers may be absent on maps without these effects.
    control = struct.pack('<16I', 1, manager, *(u(p) for p in GLOBALS), *([0]*11))
    payloads = [(CONTROL, control)]
    for index, entry in enumerate(ENTRIES):
        original = native(entry, 8)
        if ram[entry:entry+8] != original:
            raise ValueError(f'Changed native entry{entry:08X}')
        address = BASE+index*0x200
        payloads.append((address, wrapper(index, original)))
        payloads.append((entry, struct.pack('<2I', (2<<26)|(address>>2), 0)))
    return {'serial':SERIAL, 'crc':CRC, 'source':str(Path(source).resolve()),
        'status':'CAPTURED TWO-ROW GROUND EFFECT BOUNDS; OFFLINE TESTED',
        'control':CONTROL,
        'blocks':[{'address':p,'expected_hex':ram[p:p+len(data)].hex(),'data_hex':data.hex()}
                  for p,data in payloads],
        'evidence':['197810 allocates25408bytes.196F88 uses25392+4*id;197148 adds8: exactly two rows per effect.',
                    '140358 writes12*id into the array whose1418D8 consumer iterates exactly two rows.'],
        'behavior':['Captured extra indices skip these cosmetic commands, including late stop commands.',
                    'Indices0/1 keep native command behavior, floating arguments and allocation/cleanup.'],
        'limitations':['Does not repair an already corrupted table. Install from an intact checkpoint.']}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path); p.add_argument('--out',required=True,type=Path)
    x=p.parse_args(); result=build(x.source)
    x.out.write_text(json.dumps(result,indent=2)+'\n')
    print(f"{x.out}: {len(result['blocks'])} guarded blocks")
