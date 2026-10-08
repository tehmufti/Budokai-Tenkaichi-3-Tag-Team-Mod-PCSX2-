"""Guard the native two-fighter afterimage table against expanded indices.

The exact failed96 path was1713A8(8): table[8] was an adjacent pool header,
whose+56 wasNULL. Its16F7A0(0,0x4C) wrote leader0 bones over guest vectors.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram

PREDICATE, CLEAN_PREDICATE = 0x07230000, 0x07230200
WRAPPERS, CONTROL = 0x07230400, 0x07232000
FAMILY_GLOBAL, MANAGER_GLOBAL = A(0x2FEA38), A(0x2FEB14)
ENTRIES = ((A(0x1713A8), 0), (A(0x171428), 1), (A(0x1714A0), 1),
           (A(0x1714E8), 1), (A(0x171570), 0), (A(0x170EE0), 0))


def captured_gate(a, cleanup=False):
    a.li(2, CONTROL); a.lw(2, 2); a.branch(4, 2, 0, 'native')
    # Stop commands run after exposure withdrawal too. This captured table
    # remains the same bounded allocation until its manager changes.
    a.li(2, CONTROL); a.lw(3, 2, 4); a.lw(2, 28, -22364)
    a.branch(5, 2, 3, 'native')
    a.li(2, CONTROL); a.lw(3, 2, 8); a.lw(2, 28, -22584)
    a.branch(5, 2, 3, 'native')


def pointer_bound(a, reg, upper):
    a.li(3, 0x100000); a.r(0x2B, 3, reg, 3); a.branch(5, 3, 0, 'skip')
    a.li(3, upper); a.r(0x2B, 3, 3, reg); a.branch(5, 3, 0, 'skip')


def predicate_code(cleanup=False):
    a = Assembler(CLEAN_PREDICATE if cleanup else PREDICATE)
    captured_gate(a, cleanup)
    if cleanup:
        pointer_bound(a, 4, 0x8000000-64)
        a.lw(2, 4, 56)
        pointer_bound(a, 2, 0x8000000-736)
        a.lw(2, 2, 76)  # Native payload's fighter/effect index.
        a.lw(3, 28, -22584); a.lw(3, 3)
        a.r(0x2B, 2, 2, 3); a.branch(4, 2, 0, 'skip')
    else:
        a.lw(3, 2)  # The family's actual allocated row count, normally2.
        a.r(0x2B, 2, 4, 3); a.branch(4, 2, 0, 'skip')
    a.label('native'); a.move(2, 0); a.jr()
    a.label('skip')
    a.li(2, CONTROL); a.lw(3, 2, 16 if cleanup else 12)
    a.addiu(3, 3, 1); a.sw(3, 2, 16 if cleanup else 12)
    a.sw(4, 2, 24 if cleanup else 20)
    a.addiu(2, 0, 1); a.jr()
    code = a.finish(); assert len(code) <= 0x200
    return code


def wrapper_code(index, original):
    entry, absent = ENTRIES[index]
    a = Assembler(WRAPPERS+index*0x100)
    a.addiu(29, 29, -0x10); a.i(63, 31, 29, 0); a.i(63, 3, 29, 8)
    a.call(CLEAN_PREDICATE if entry == A(0x170EE0) else PREDICATE)
    a.i(55, 31, 29, 0); a.i(55, 3, 29, 8); a.addiu(29, 29, 0x10)
    a.branch(4, 2, 0, 'native'); a.addiu(2, 0, absent); a.jr()
    a.label('native')
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in (1, 2, 3, 4, 5, 6, 7)
        a.emit(word)
    a.jump(entry+8)
    code = a.finish(); assert len(code) <= 0x100
    return code


def build(source):
    ram = read_ram(source); assert len(ram) == 0x8000000
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    _, _, native = elf_reader(elf_path(ROOT))
    manager, family = u(MANAGER_GLOBAL), u(FAMILY_GLOBAL)
    assert manager == u(0xD8088) and manager and family and u(family) == 2
    assert u(family+1776) >= 0x100000
    control = struct.pack('<8I', 1, manager, family, 0, 0, 0, 0, 0)
    payloads = [(PREDICATE, predicate_code()), (CLEAN_PREDICATE, predicate_code(True)),
                (CONTROL, control)]
    hooks = []
    for i, (entry, _) in enumerate(ENTRIES):
        original = native(entry, 8); assert ram[entry:entry+8] == original
        address = WRAPPERS+i*0x100
        payloads.append((address, wrapper_code(i, original)))
        hooks.append((entry, struct.pack('<2I', (2 << 26) | (address >> 2), 0)))
    for p, data in payloads:
        assert not any(ram[p:p+len(data)]), f'Occupied afterimage cave{p:08X}'
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status='CAPTURED AFTERIMAGE TABLE BOUNDS; OFFLINE TESTED', control=CONTROL,
                blocks=[dict(address=p, expected_hex=ram[p:p+len(data)].hex(), data_hex=data.hex())
                        for p, data in payloads+hooks],
                behavior=['Use native allocated family row count, not physical/model identity equality.',
                          'Valid leader indices0/1 retain original native paths.',
                          'Out-of-range create/query returns0; stop/kill/control returns the native absent-effect success1.',
                          'Destructor skips null or invalid payloads and out-of-range payload identities without unlinking or freeing unrelated memory.',
                          'All bounds remain active while exposure is withdrawn in the same captured world.'],
                evidence=['171128 allocates4*familycount bytes for table+1776; paused count is2.',
                          '1713A8(8) reads neighboring01987A80 withNULLpayload, then16F7A0(0,0x4C) overwrites low memory.',
                          '1D0508 passes actor+0 to1714E8, so the family index is a fighter/effect index.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    x = p.parse_args(); x.out.write_text(json.dumps(build(x.source), indent=2)+'\n')
    print(x.out)
