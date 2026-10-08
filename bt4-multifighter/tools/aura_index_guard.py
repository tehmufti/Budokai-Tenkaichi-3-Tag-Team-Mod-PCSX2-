"""Bound the native two-entry aura effect table during captured team combat.

These effect commands and queries accept a scalar fighter/model index, while
native164C40 allocates only original_count*4 table bytes. No live writes occur.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram

PREDICATE, CONTROL, WRAPPERS = 0x07234000, 0x07234200, 0x07234400
EFFECT_GLOBAL, ACTOR_GLOBAL = A(0x2FEA00), A(0x2FEB14)
ENTRIES = (A(0x165020), A(0x1650B8), A(0x165138), A(0x165180), A(0x1651B0), A(0x165210),
           A(0x165278), A(0x1652C0), A(0x165308), A(0x165368), A(0x1653C0), A(0x165418), A(0x1656A8))


def predicate_code():
    a = Assembler(PREDICATE)
    a.i(11, 2, 4, 2); a.branch(5, 2, 0, 'native')
    a.li(2, CONTROL); a.lw(3, 2); a.branch(4, 3, 0, 'native')
    a.lw(3, 2, 4); a.lw(2, 28, -22364); a.branch(5, 2, 3, 'native')
    a.li(2, CONTROL); a.lw(3, 2, 8); a.lw(2, 28, -22640)
    a.branch(5, 2, 3, 'native'); a.branch(4, 2, 0, 'native')
    a.lw(2, 2); a.addiu(3, 0, 2); a.branch(5, 2, 3, 'native')
    # Teardown may withdraw exposure before issuing effect stop commands.
    # The captured effect table remains two entries until its manager changes.
    a.li(2, CONTROL); a.lw(3, 2, 16); a.addiu(3, 3, 1)
    a.sw(3, 2, 16); a.sw(4, 2, 20)
    a.addiu(2, 0, 1); a.jr()
    a.label('native'); a.move(2, 0); a.jr()
    code = a.finish(); assert PREDICATE+len(code) <= CONTROL
    return code


def wrapper_code(index, original):
    a = Assembler(WRAPPERS+index*0x100)
    a.addiu(29, 29, -0x10); a.i(63, 31, 29, 0); a.i(63, 3, 29, 8)
    a.call(PREDICATE)
    a.i(55, 31, 29, 0); a.i(55, 3, 29, 8); a.addiu(29, 29, 0x10)
    a.branch(4, 2, 0, 'native'); a.move(2, 0); a.jr()
    a.label('native')
    if ENTRIES[index] == A(0x165180):
        load, branch, delay = struct.unpack('<3I', original)
        assert branch == 0x10400008 and delay == 0x00042080
        a.emit(load)
        a.branch(4, 2, 0, 'native_zero')
        a.words[-1] = delay  # Original SLL executes on both BEQ outcomes.
        a.jump(A(0x16518C))
        a.label('native_zero'); a.jump(A(0x1651A8))
    else:
        for word in struct.unpack('<2I', original):
            assert word>>26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21), 'Branching native prologue'
            a.emit(word)
        a.jump(ENTRIES[index]+8)
    code = a.finish(); assert len(code) <= 0x100
    return code


def build(source):
    ram = read_ram(source)
    if len(ram) != 0x8000000:
        raise ValueError('Expected128MiB team checkpoint')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, effect = u(ACTOR_GLOBAL), u(EFFECT_GLOBAL)
    if not manager or u(0xD8088) != manager or not effect or u(effect) != 2:
        raise ValueError('Expected captured team manager and native two-entry aura table')
    if not u(effect+1168) or u(0xC4004):
        raise ValueError('Missing effect table or active virtual AI slice')
    end = WRAPPERS+len(ENTRIES)*0x100
    if any(ram[PREDICATE:end]):
        raise ValueError('Aura guard reservation occupied')
    _, _, readelf = elf_reader(elf_path(ROOT))
    control = struct.pack('<6I', 1, manager, effect, 2, 0, 0)
    payloads = [(PREDICATE, predicate_code()), (CONTROL, control)]
    hooks = []
    for i, entry in enumerate(ENTRIES):
        original = readelf(entry, 12 if entry == A(0x165180) else 8)
        if ram[entry:entry+len(original)] != original:
            raise ValueError(f'Changed native aura entry{entry:08X}')
        address = WRAPPERS+i*0x100
        payloads.append((address, wrapper_code(i, original)))
        hooks.append((entry, struct.pack('<2I', (2<<26)|(address>>2), 0)+original[8:]))
    return {'serial': SERIAL, 'crc': CRC, 'source': str(Path(source).resolve()),
        'status': 'CAPTURED TWO-ENTRY AURA BOUNDS; OFFLINE TESTED',
        'blocks': [{'address': p, 'expected_hex': ram[p:p+len(data)].hex(),
                    'data_hex': data.hex()} for p, data in payloads+hooks],
        'control': CONTROL, 'control_fields': {'enabled': 0, 'actor_manager': 4,
            'effect_manager': 8, 'native_capacity': 12, 'suppressed_calls': 16, 'last_index': 20},
        'evidence': ['164C40 captures12CF48 native count2 and allocates count*4 bytes at164DC4.',
            'Native table is effect manager+1168; every guarded entry uses an unchecked scalar index.',
            '1D0508 sends physical IDs to165418 commands5/6; other aura callers pass model IDs.',
            'These commands mutate effect-private state;1651B0/165210 query effect activity for visual rendering.'],
        'behavior': ['Indices0/1 retain native operations. Unsupported indices return0 without table access.',
            'Bounds remain active after exposure withdrawal while both captured managers still match.',
            'Native effect destructors and their resource-release behavior are unchanged.'],
        'limitations': ['Additional fighters lose this native aura effect family.',
            'This does not repair earlier out-of-bounds writes; install from an intact checkpoint.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ram', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = build(args.ram)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f"{args.out}: {len(result['blocks'])} guarded blocks")
