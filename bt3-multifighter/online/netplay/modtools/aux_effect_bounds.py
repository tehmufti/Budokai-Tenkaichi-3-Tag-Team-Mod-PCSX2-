"""Bound the two-entry16B effect tracker, preserving valid payload release."""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from afterimage_bounds import pointer_bound

PREDICATES = (0x07238000, 0x07238200, 0x07238400)
WRAPPERS, TAIL, CONTROL = 0x07238800, 0x07238C00, 0x07238F00
ENTRIES, FAMILY_GLOBAL = (A(0x16B418), A(0x16B4A0), A(0x16B118)), A(0x2FEA2C)


def captured_gate(a):
    a.li(2, CONTROL); a.lw(3, 2); a.branch(4, 3, 0, 'native')
    a.lw(3, 2, 4); a.lw(2, 28, -22364); a.branch(5, 2, 3, 'native')
    a.li(2, CONTROL); a.lw(3, 2, 8); a.lw(2, 28, -22596)
    a.branch(5, 2, 3, 'native')


def predicate_code(kind):
    a = Assembler(PREDICATES[kind]); captured_gate(a)
    if kind == 0:  # Creator takes a pointer to a12-byte request record.
        pointer_bound(a, 4, 0x8000000-12); a.lw(2, 4)
    elif kind == 1:
        a.move(2, 4)
    else:
        pointer_bound(a, 4, 0x8000000-64); a.lw(2, 4, 56)
        pointer_bound(a, 2, 0x8000000-1392)
        a.jump('native')  # Resource release must still run for a valid payload.
    a.i(11, 2, 2, 2); a.branch(5, 2, 0, 'native')
    a.label('skip')
    a.li(2, CONTROL); a.lw(3, 2, 12+kind*4); a.addiu(3, 3, 1)
    a.sw(3, 2, 12+kind*4); a.sw(4, 2, 28)
    a.addiu(2, 0, 1); a.jr()
    a.label('native'); a.move(2, 0); a.jr()
    b = a.finish(); assert len(b) <= 0x200; return b


def wrapper_code(i, original):
    a = Assembler(WRAPPERS+i*0x100)
    a.addiu(29, 29, -16); a.i(63, 31, 29, 0); a.i(63, 3, 29, 8)
    a.call(PREDICATES[i])
    a.i(55, 31, 29, 0); a.i(55, 3, 29, 8); a.addiu(29, 29, 16)
    a.branch(4, 2, 0, 'native'); a.move(2, 0); a.jr()
    a.label('native')
    for w in struct.unpack('<2I', original):
        assert w >> 26 not in (1, 2, 3, 4, 5, 6, 7); a.emit(w)
    a.jump(ENTRIES[i]+8)
    return a.finish()


def tail_code():
    # Native has released resource and restored its callee-saved registers.
    # Only v0/v1 are used temporarily; the native return-address value remains.
    a = Assembler(TAIL)
    a.addiu(29, 29, -16); a.i(63, 2, 29, 0); a.i(63, 3, 29, 8)
    captured_gate(a)
    a.lw(3, 28, -22596); a.i(55, 2, 29, 0)
    a.r(0x23, 2, 2, 3); a.i(11, 2, 2, 8)
    a.branch(5, 2, 0, 'native')
    a.li(2, CONTROL); a.lw(3, 2, 24); a.addiu(3, 3, 1); a.sw(3, 2, 24)
    a.jump('skip')
    a.label('native')
    a.i(55, 2, 29, 0); a.i(55, 3, 29, 8); a.addiu(29, 29, 16)
    a.sw(0, 2, 800); a.emit(0x03E00008); a.addiu(29, 29, 32)
    a.label('skip')
    a.i(55, 2, 29, 0); a.i(55, 3, 29, 8); a.addiu(29, 29, 16)
    a.emit(0x03E00008); a.addiu(29, 29, 32)
    b = a.finish(); assert TAIL+len(b) < CONTROL; return b


def build(source):
    r = read_ram(source); assert len(r) == 0x8000000
    u = lambda p: struct.unpack_from('<I', r, p)[0]
    _, _, native = elf_reader(elf_path(ROOT))
    manager, family = u(A(0x2FEB14)), u(FAMILY_GLOBAL)
    assert manager and manager == u(0xD8088) and family
    # Exact native allocation proves the static two-row capacity:808-800=8.
    assert r[A(0x16B354):A(0x16B378)] == native(A(0x16B354), 0x24)
    assert u(A(0x16B35C)) == 0x24050328 and u(A(0x16B368)) == 0x24060328
    payloads = [(p, predicate_code(i)) for i, p in enumerate(PREDICATES)]
    payloads += [(TAIL, tail_code()), (CONTROL, struct.pack('<8I', 1, manager, family, 0, 0, 0, 0, 0))]
    hooks = []
    for i, entry in enumerate(ENTRIES):
        old = native(entry, 8); assert r[entry:entry+8] == old
        p = WRAPPERS+i*0x100; payloads.append((p, wrapper_code(i, old)))
        hooks.append((entry, struct.pack('<2I', (2 << 26) | (p >> 2), 0)))
    assert r[A(0x16B15C):A(0x16B168)] == struct.pack('<3I', 0xAC400320, 0x03E00008, 0x27BD0020)
    hooks.append((A(0x16B15C), struct.pack('<2I', (2 << 26) | (TAIL >> 2), 0)))
    for p, b in payloads:
        assert not any(r[p:p+len(b)]), f'Occupied effect cave{p:08X}'
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status='CAPTURED16B TWO-ENTRY EFFECT BOUNDS; OFFLINE TESTED', control=CONTROL,
                blocks=[dict(address=p, expected_hex=r[p:p+len(b)].hex(), data_hex=b.hex()) for p, b in payloads+hooks],
                evidence=['16B340 allocates808bytes; tracker occupies only800..807.',
                          '16B418 takes request pointer,16B4A0 takes scalar fighter/effect index.',
                          '16B118 calls14D798 to release its valid payload resource before final indexed table clear.'],
                behavior=['Create/stop skips indices>=2 while captured actor and effect manager match.',
                          'Null/invalid cleanup payload skips before native resource access.',
                          'Valid cleanup payload always retains native14D798 release and payload flag reset.',
                          'Only an out-of-range final table clear is suppressed; native return value and stack are retained.',
                          'Bounds remain active after team exposure is withdrawn.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args(); x.out.write_text(json.dumps(build(x.source), indent=2)+'\n'); print(x.out)
