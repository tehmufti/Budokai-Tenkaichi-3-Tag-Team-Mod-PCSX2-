"""Grow both main graphics-packet arenas after submission, before buffer swap.

Old allocations remain live because the PS2 DMA engine can still reference
them. No current packet is copied or redirected midway through construction.
"""
from native_map import A, CRC, GPO, SERIAL
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler
from camera_snapshot import read_ram

CODE, CONTROL, HOOK = 0x07220000, 0x07222000, A(0x100824)
SIZE, GP = 0x400000, 0x304270
BASES, ENDS, CAPACITY, INDEX, CURSOR = (A(GP+p) for p in (-23024, -23016, -23008, -23004, -23000))
ORIGINAL = struct.pack('<2I', (35 << 26) | (28 << 21) | (2 << 16) | (GPO(-0x59DC) & 0xFFFF), 0xDFBF0000)


def payload():
    a = Assembler(CODE)
    a.addiu(29, 29, -0x30)
    for i, reg in enumerate((16, 17, 18, 19, 31)):
        a.i(63, reg, 29, i*8)
    a.li(16, CONTROL)
    a.lw(8, 16)
    a.branch(5, 8, 0, 'done')
    a.lw(8, 16, 4)
    a.branch(4, 8, 0, 'done')
    a.lw(8, 16, 56)
    a.lw(9, 28, -22364)
    a.branch(5, 8, 9, 'error102')
    # Every published arena field must still describe the audited old pair.
    for offset, field in ((-23024, 32), (-23020, 36), (-23016, 40),
                          (-23012, 44), (-23008, 48)):
        a.lw(8, 28, offset)
        a.lw(9, 16, field)
        a.branch(5, 8, 9, 'error103')
    a.lw(8, 28, -23004)
    a.i(11, 9, 8, 2)
    a.branch(4, 9, 0, 'error104')
    a.sw(8, 16, 52)
    a.addiu(8, 0, 10)
    a.sw(8, 16)
    for i, reg in enumerate((17, 18)):
        a.li(4, SIZE)
        a.addiu(5, 0, 64)
        a.move(6, 0)
        a.addiu(7, 0, 1)
        a.call(A(0x2554D8))
        a.branch(4, 2, 0, 'error101')
        a.move(reg, 2)
        a.sw(reg, 16, 24+i*4)
        a.li(8, 0x02000000)
        a.r(0x2b, 9, reg, 8)
        a.branch(5, 9, 0, 'error105')
        a.li(8, 0x06000000-SIZE)
        a.r(0x2b, 9, 8, reg)
        a.branch(5, 9, 0, 'error105')
        a.i(12, 8, reg, 63)
        a.branch(5, 8, 0, 'error105')
        a.move(4, reg)
        a.move(5, 0)
        a.li(6, SIZE)
        a.call(A(0x2A9ACC))
        a.addiu(8, 0, i+1)
        a.sw(8, 16, 8)
    # No rendering runs between these stores: the old packet was submitted
    # before the hook, and the native tail selects the next buffer afterwards.
    a.li(19, SIZE)
    for reg, offset in ((17, -23024), (18, -23020)):
        a.sw(reg, 28, offset)
        a.r(0x21, 8, reg, 19)
        a.sw(8, 28, offset+8)
    a.sw(19, 28, -23008)
    a.sw(19, 16, 12)
    a.addiu(8, 0, 5)
    a.sw(8, 16)
    a.jump('done')
    for error in (101, 102, 103, 104, 105):
        a.label(f'error{error}')
        a.addiu(8, 0, error)
        a.sw(8, 16)
        a.jump('done')
    a.label('done')
    for i, reg in enumerate((16, 17, 18, 19, 31)):
        a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x30)
    for word in struct.unpack('<2I', ORIGINAL):
        a.emit(word)
    a.jump(HOOK+8)
    code = a.finish()
    assert len(code) < CONTROL-CODE
    return code


def build(source):
    r = read_ram(source)
    assert len(r) == 0x8000000
    u = lambda p: struct.unpack_from('<I', r, p)[0]
    assert r[HOOK:HOOK+8] == ORIGINAL
    assert u(CAPACITY) == 0x100000 and u(INDEX) < 2
    assert u(A(0x2FF084)) == 0x02000000 and u(A(0x2FF08C)) == 0x06000000
    assert u(0x07201034) == 5 and u(0x07201010) > 0
    assert not u(0x07201028) and not u(0x0720102C)
    assert all(u(ENDS+i*4)-u(BASES+i*4) == u(CAPACITY) for i in range(2))
    control = bytearray(64)
    struct.pack_into('<I', control, 4, 1)
    for field, p in ((32, BASES), (36, BASES+4), (40, ENDS), (44, ENDS+4), (48, CAPACITY), (56, A(0x2FEB14))):
        struct.pack_into('<I', control, field, u(p))
    blocks = []
    for p, b in ((CODE, payload()), (CONTROL, bytes(control))):
        assert not any(r[p:p+len(b)]), 'Occupied packet growth arena'
        blocks.append(dict(address=p, expected_hex=r[p:p+len(b)].hex(), data_hex=b.hex()))
    blocks.append(dict(address=HOOK, expected_hex=ORIGINAL.hex(),
                       data_hex=struct.pack('<2I', (2 << 26) | (CODE >> 2), 0).hex()))
    return dict(serial=SERIAL, crc=CRC, source=str(source), blocks=blocks,
                status='POST-SUBMISSION PACKET GROWTH; FIGHTER EXPOSURE UNCHANGED',
                control=CONTROL, new_capacity=SIZE,
                requirements=['Success requires control status5/completed2 and later packet telemetry without errors.',
                              'Any failure leaves the original arena globals intact; restore the source before retrying.'],
                limitations=['Original packet allocations remain live to preserve outstanding DMA references.',
                             'Only the main graphics-packet arena is expanded.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    x = p.parse_args()
    x.out.write_text(json.dumps(build(x.source), indent=2)+'\n')
    print(x.out)
