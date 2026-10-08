"""Keep captured defeated fighters in the visible native KO state, offline only.

Native action235 sets hidden flag0xB each tick. When a captured fighter has
already reached HP0, convert a request for235 into ordinary falling/grounded
KO action216. Existing KO/tag guards retain the actor and model allocation.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

from ai_shadow import Assembler

ROOT = Path(__file__).resolve().parents[1]
ENTRY, CODE, CONTROL = A(0x1E0290), 0xE8A00, 0xE8F00
MODE, POINTERS, EXPOSURE = 0xD8080, 0xD8040, 0xB3088
NATIVE = bytes.fromhex('ffff02240100a254')


def stub():
    a = Assembler(CODE)
    a.addiu(2, 0, 235)
    a.branch(5, 2, 'native', not_equal=True)
    a.nop()
    a.addiu(29, 29, -0x20)
    saved = ((3, 0), (8, 8), (9, 16), (10, 24))
    for reg, offset in saved:
        a.mem(63, reg, 29, offset)
    for address in (CONTROL, EXPOSURE, MODE):
        a.load_address(8, address)
        a.mem(35, 8, 8, 0)
        a.branch(8, 0, 'restore_native')
        a.nop()
    a.load_address(8, MODE)
    a.mem(35, 9, 8, 8)
    a.mem(35, 10, 28, -22364)
    a.branch(9, 10, 'restore_native', not_equal=True)
    a.nop()
    a.mem(35, 9, 8, 4)
    a.addiu(10, 9, -1)
    a.mem(11, 10, 10, 12)
    a.branch(10, 0, 'restore_native')
    a.nop()
    a.mem(11, 10, 9, 5)
    a.branch(10, 0, 'scan', not_equal=True)
    a.nop()
    a.load_address(8, 0xF609C)
    a.mem(35, 8, 8, 0)
    a.branch(8, 0, 'restore_native')
    a.nop()
    a.label('scan')
    a.load_address(8, POINTERS)
    a.label('next')
    a.mem(35, 10, 8, 0)
    a.branch(10, 4, 'captured')
    a.nop()
    a.addiu(9, 9, -1)
    a.branch(9, 0, 'next', not_equal=True)
    a.addiu(8, 8, 4)
    a.branch(0, 0, 'restore_native')
    a.nop()
    a.label('captured')
    a.branch(4, 0, 'restore_native')
    a.nop()
    a.mem(35, 8, 4, 0x994)
    a.mem(11, 9, 8, 5)
    a.branch(9, 0, 'restore_native')
    a.nop()
    # 164-byte native roster row: actor+0x9E4+164*activeSlot.
    a.emit((8 << 16) | (9 << 11) | (7 << 6))
    a.emit((8 << 16) | (10 << 11) | (5 << 6))
    a.emit((9 << 21) | (10 << 16) | (9 << 11) | 0x21)
    a.emit((8 << 16) | (10 << 11) | (2 << 6))
    a.emit((9 << 21) | (10 << 16) | (9 << 11) | 0x21)
    a.emit((9 << 21) | (4 << 16) | (9 << 11) | 0x21)
    a.mem(35, 10, 9, 0x9E4)
    a.mem(10, 9, 10, 1)
    a.branch(9, 0, 'restore_native')
    a.nop()
    a.addiu(2, 0, 216)
    a.mem(43, 2, 4, 0x94C)
    a.load_address(8, CONTROL)
    a.mem(35, 9, 8, 4)
    a.addiu(9, 9, 1)
    a.mem(43, 9, 8, 4)
    a.mem(43, 4, 8, 8)
    a.mem(43, 10, 8, 12)
    for reg, offset in saved:
        a.mem(55, reg, 29, offset)
    a.addiu(29, 29, 0x20)
    a.emit(0x03E00008)
    a.addiu(2, 0, -1)
    a.label('restore_native')
    for reg, offset in saved:
        a.mem(55, reg, 29, offset)
    a.addiu(29, 29, 0x20)
    a.label('native')
    a.addiu(2, 0, -1)
    a.branch(5, 2, 'return')
    a.nop()
    a.mem(43, 5, 4, 0x94C)
    a.label('return')
    a.emit(0x03E00008)
    a.nop()
    return a.finish()


def build(source=None):
    code = stub()
    if CODE + len(code) > CONTROL:
        raise ValueError('Fallen-body code exceeds reserved cave')
    control = struct.pack('<4I', 1, 0, 0, 0)
    hook = struct.pack('<2I', (2 << 26) | (CODE >> 2), 0)
    payloads = ((CODE, code), (CONTROL, control))
    blocks = []
    if source:
        ram = Path(source).read_bytes()
        if len(ram) not in (0x2000000, 0x8000000):
            raise ValueError('Expected full EE RAM')
        if ram[ENTRY:ENTRY+8] != NATIVE:
            raise ValueError('Action-request native entry changed')
        for address, data in payloads:
            old = ram[address:address+len(data)]
            if any(old):
                raise ValueError(f'Occupied fallen-body reservation {address:08X}')
            blocks.append({'address': address, 'expected_hex': old.hex(), 'data_hex': data.hex()})
        blocks.append({'address': ENTRY, 'expected_hex': NATIVE.hex(), 'data_hex': hook.hex()})
    return {'serial': SERIAL, 'crc': CRC,
            'status': 'DEAD CAPTURED FIGHTERS USE VISIBLE NATIVE KO STATE',
            'source_ram': str(Path(source).resolve()) if source else None,
            'segments': [{'address': p, 'data_hex': b.hex()} for p, b in payloads],
            'blocks': blocks, 'control': CONTROL,
            'control_fields': {'enabled': 0, 'converted_requests': 4, 'last_actor': 8, 'last_hp': 12},
            'evidence': 'Action235 table2C4980+235*4 dispatches1EB070, which sets hidden flag0xB at1EB0E0. Actor rendering1C0EB8 clears model+2624 bit2 for this flag. Action216 dispatches1E9EC8 and uses native falling/grounded KO without this hide flag.',
            'requirements': ['Apply before the next KO; existing state235 is not retroactively changed.',
                             'Existing automatic KO/tag guards must remain enabled to prevent native roster replacement.',
                             'D8080 mode, captured actor table/count, manager identity, B3088 and expanded exposure must match.'],
            'limitations': ['Round-end victory behavior remains separate.',
                            'Ordinary action216 has prior long-running retention proof; converted action235 needs live validation.',
                            'No HP, damage, movement, camera, model allocation, or living-fighter action is modified.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ram', type=Path)
    p.add_argument('--out', type=Path, default=ROOT/'analysis/team-fallen-bodies.json')
    args = p.parse_args()
    result = build(args.ram)
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(f"{args.out}: {len(result['blocks'])} guarded blocks")
