"""Reject generic projectile requests routed into incompatible effect pools.

The borrowed Hercule pool contains480-byte bodies and an88-byte descriptor.
176788 needs1504-byte bodies and an804-byte descriptor; using the wrong pool
overwrites neighboring objects before any later resource check can help.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram

CODE, CONTROL, HOOK, NATIVE = 0x07320000, 0x07321000, A(0x176EEC), A(0x1AD7B8)
PARENT_CALLBACKS, CHILD_CALLBACKS, SIZE = A(0x2C3D70), A(0x2C3D88), 1504
RESOURCE_GLOBAL = A(0x2FEA48)


def bound(a, reg, size, label='bad_pointer'):
    a.li(2, 0x100000); a.r(0x2B, 3, reg, 2); a.branch(5, 3, 0, label)
    a.li(2, 0x8000000-size); a.r(0x2B, 3, 2, reg); a.branch(5, 3, 0, label)


def payload(code=CODE, control=CONTROL, parent_callbacks=PARENT_CALLBACKS,
            child_callbacks=CHILD_CALLBACKS, size=SIZE, descriptor_size=804,
            check_header=True):
    a = Assembler(code)
    saved = (3, 8, 9, 10, 11)
    a.addiu(29, 29, -0x30)
    for i, reg in enumerate(saved): a.i(63, reg, 29, i*8)
    a.li(2, control); a.lw(3, 2); a.branch(4, 3, 0, 'native')
    a.lw(3, 2, 4); a.lw(2, 28, -22364); a.branch(5, 2, 3, 'native')
    a.li(2, control); a.lw(3, 2, 8); a.lw(2, 28, -22568)
    a.branch(5, 2, 3, 'native')
    bound(a, 4, 32)
    a.lw(8, 4); bound(a, 8, 64)
    a.lw(9, 8, 40); a.li(2, parent_callbacks); a.branch(5, 9, 2, 'bad_family')
    a.li(2, child_callbacks); a.branch(5, 5, 2, 'bad_family')
    # All audited generic pools contain10 or20 nodes. Their static node base
    # is pool+16; node size64 and payload pointers at+56 prove storage stride.
    a.lw(9, 4, 16); bound(a, 9, 128)
    a.lw(10, 9, 56); a.lw(11, 9, 120)
    bound(a, 10, size); bound(a, 11, size)
    a.r(0x23, 11, 11, 10); a.addiu(2, 0, size); a.branch(5, 11, 2, 'bad_layout')
    a.lw(9, 8, 56); bound(a, 9, 4)
    a.lw(11, 9); bound(a, 11, descriptor_size)
    if check_header:
        a.lw(10, 11); bound(a, 10, 4, 'bad_resource')
    a.li(2, control); a.lw(3, 2, 16); a.addiu(3, 3, 1); a.sw(3, 2, 16)
    a.jump('native')
    for label, reason in (('bad_family', 1), ('bad_layout', 2), ('bad_resource', 3), ('bad_pointer', 4)):
        a.label(label); a.addiu(3, 0, reason); a.jump('blocked')
    a.label('blocked')
    a.li(2, control); a.sw(3, 2, 20); a.sw(4, 2, 24); a.sw(6, 2, 28)
    a.lw(3, 2, 12); a.addiu(3, 3, 1); a.sw(3, 2, 12)
    for i, reg in enumerate(saved): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x30); a.move(2, 0); a.jr()
    a.label('native')
    for i, reg in enumerate(saved): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x30); a.jump(NATIVE)
    b = a.finish(); assert len(b) < 0x400; return b


def build(source):
    r = read_ram(source); assert len(r) == 0x8000000
    u = lambda p: struct.unpack_from('<I', r, p)[0]
    _, _, native = elf_reader(elf_path(ROOT))
    original = native(HOOK, 8)
    assert original == struct.pack('<2I', (3 << 26) | (NATIVE >> 2), 0x03A0302D)
    assert r[HOOK:HOOK+8] == original
    manager, resources = u(A(0x2FEB14)), u(RESOURCE_GLOBAL)
    assert manager and manager == u(0xD8088) and resources
    assert r[A(0x176D00):A(0x176DD8)] == native(A(0x176D00), 0xD8)
    assert r[A(0x178AF8):A(0x178BB8)] == native(A(0x178AF8), 0xC0)
    control = struct.pack('<8I', 1, manager, resources, 0, 0, 0, 0, 0)
    blocks = []
    for p, b in ((CODE, payload()), (CONTROL, control)):
        assert not any(r[p:p+len(b)]), f'Occupied projectile pool cave{p:08X}'
        blocks.append(dict(address=p, expected_hex=r[p:p+len(b)].hex(), data_hex=b.hex()))
    hook = struct.pack('<I', (3 << 26) | (CODE >> 2))+original[4:]
    blocks.append(dict(address=HOOK, expected_hex=original.hex(), data_hex=hook.hex()))
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status='GENERIC PROJECTILE POOL COMPATIBILITY; OFFLINE TESTED', control=CONTROL, blocks=blocks,
                evidence=['176E70 chooses callback2C3D88 whose176788 initializer clears1504bytes.',
                          'The borrowed Hercule kind1 pool uses parent2C3E00,480-byte payloads and88-byte metadata.',
                          'Mismatch is present in clean six83 and twelve97;99 contains generic callbacks inside480-byte pool nodes.'],
                behavior=['Before allocation, require generic parent callbacks2C3D70, childcallbacks2C3D88,1504-byte payload stride and valid descriptor/header pointers.',
                          'Compatible generic requests execute native allocation with original arguments and caller frame.',
                          'Incompatible requests return native allocation failure0 without writing pool/resource/actor memory.',
                          'Captured ownership protects only this selected fight; no count-specific restriction.'],
                limitations=['Generic ki projectiles cannot spawn through an incompatible borrowed character pool.',
                             'Existing corrupted effects require restoration of an intact source checkpoint.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args(); x.out.write_text(json.dumps(build(x.source), indent=2)+'\n'); print(x.out)
