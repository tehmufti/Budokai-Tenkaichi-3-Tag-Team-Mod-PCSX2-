"""Select a surviving camera subject without changing game/AI ownership.

Only the camera call23EBEC to scene-side model lookup12B1D0 is redirected.
The ordinary game lookup remains untouched everywhere else.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

from ai_shadow import Assembler

ROOT = Path(__file__).resolve().parents[1]
HOOK, NATIVE = A(0x23EBEC), A(0x12B1D0)
CODE, LOOKUP, CONTROL = 0xFD000, 0xFDC00, 0xFDF00
MODE, POINTERS, MODELS = 0xD8080, 0xD8040, A(0x31C640)


def lookup_stub(require_visibility=True):
    """Physical index a0 -> model v0, alive v1, native team a1; -1 invalid.

    The default retains the original emitted bytes for guarded upgrades.
    False permits a living authored vanish; fallen bodies must still be visible.
    """
    a = Assembler(LOOKUP)
    a.load_address(8, MODE)
    a.mem(35, 8, 8, 4)
    a.emit((4 << 21) | (8 << 16) | (9 << 11) | 0x2B)
    a.branch(9, 0, 'invalid')
    a.nop()
    a.emit((4 << 16) | (9 << 11) | (2 << 6))
    a.load_address(8, POINTERS)
    a.emit((8 << 21) | (9 << 16) | (8 << 11) | 0x21)
    a.mem(35, 10, 8, 0)
    for bound, lower in ((0x100000, True), (0x8000000-0x1600, False)):
        a.load_address(8, bound)
        a.emit(((10 if lower else 8) << 21) | ((8 if lower else 10) << 16) | (9 << 11) | 0x2B)
        a.branch(9, 0, 'invalid', not_equal=True)
        a.nop()
    a.mem(35, 5, 10, 8)
    a.mem(11, 9, 5, 2)
    a.branch(9, 0, 'invalid')
    a.nop()
    a.mem(35, 2, 10, 12)
    a.mem(11, 9, 2, 12)
    a.branch(9, 0, 'invalid')
    a.nop()
    a.emit((2 << 16) | (9 << 11) | (2 << 6))
    a.load_address(8, MODELS)
    a.emit((8 << 21) | (9 << 16) | (8 << 11) | 0x21)
    a.mem(35, 8, 8, 0)
    a.branch(8, 0, 'invalid')
    a.nop()
    a.mem(35, 9, 8, 16)
    a.branch(9, 2, 'invalid', not_equal=True)
    a.nop()
    if not require_visibility:
        a.move(11, 8)  # Keep the registered model for the fallen-body check.
    for offset in ((4, 8) if require_visibility else (4,)):
        a.mem(35, 9, 8, offset)
        a.branch(9, 0, 'invalid')
        a.nop()
    a.mem(35, 8, 10, 0x994)
    a.mem(11, 9, 8, 5)
    a.branch(9, 0, 'invalid')
    a.nop()
    a.emit((8 << 16) | (9 << 11) | (2 << 6))
    a.emit((9 << 21) | (8 << 16) | (9 << 11) | 0x21)
    a.emit((9 << 16) | (9 << 11) | (3 << 6))
    a.emit((9 << 21) | (8 << 16) | (9 << 11) | 0x21)
    a.emit((9 << 16) | (9 << 11) | (2 << 6))
    a.emit((9 << 21) | (10 << 16) | (9 << 11) | 0x21)
    a.mem(35, 9, 9, 0x9E4)
    a.mem(10, 3, 9, 1)
    if require_visibility:
        a.emit(0x03E00008)
        a.mem(14, 3, 3, 1)
    else:
        a.mem(14, 3, 3, 1)
        a.branch(3, 0, 'valid', not_equal=True)
        a.nop()
        a.mem(35, 9, 11, 8)
        a.branch(9, 0, 'invalid')
        a.nop()
        a.label('valid')
        a.emit(0x03E00008)
        a.nop()
    a.label('invalid')
    a.addiu(2, 0, -1)
    a.move(3, 0)
    a.emit(0x03E00008)
    a.addiu(5, 0, -1)
    return a.finish()


def stub():
    a = Assembler(CODE)
    a.addiu(29, 29, -0x90)
    saved = [(16+i, i*8) for i in range(8)] + [(31, 0x40)]
    saved += [(4+i, 0x48+i*8) for i in range(4)]
    saved += [(8+i, 0x68+i*8) for i in range(4)] + [(3, 0x88)]
    for reg, offset in saved:
        a.mem(63, reg, 29, offset)
    a.move(16, 4)
    a.mem(11, 8, 16, 2)
    a.branch(8, 0, 'fallback')
    a.nop()
    for address in (CONTROL, 0xB3088, MODE):
        a.load_address(8, address)
        a.mem(35, 8, 8, 0)
        a.branch(8, 0, 'fallback')
        a.nop()
    a.load_address(8, MODE)
    a.mem(35, 18, 8, 4)
    a.addiu(9, 18, -1)
    a.mem(11, 9, 9, 12)
    a.branch(9, 0, 'fallback')
    a.nop()
    a.mem(35, 9, 8, 8)
    a.mem(35, 10, 28, -22364)
    a.branch(9, 10, 'fallback', not_equal=True)
    a.nop()
    a.load_address(8, CONTROL)
    a.mem(35, 9, 8, 4)
    a.branch(9, 10, 'fallback', not_equal=True)
    a.nop()
    a.mem(11, 9, 18, 5)
    a.branch(9, 0, 'ready', not_equal=True)
    a.nop()
    a.load_address(8, 0xF609C)
    a.mem(35, 8, 8, 0)
    a.branch(8, 0, 'fallback')
    a.nop()
    a.label('ready')
    a.emit((16 << 16) | (9 << 11) | (2 << 6))
    a.load_address(17, CONTROL)
    a.emit((17 << 21) | (9 << 16) | (17 << 11) | 0x21)
    a.mem(35, 19, 17, 8)
    a.jump(LOOKUP, link=True)
    a.move(4, 19)
    a.move(20, 2)  # Existing owner's valid body model, or-1.
    a.move(22, 3)
    a.move(23, 5)
    a.branch(3, 0, 'scan_own')
    a.nop()
    a.branch(5, 16, 'stable_own')
    a.nop()
    a.label('scan_own')
    a.move(21, 0)
    a.label('own_loop')
    a.jump(LOOKUP, link=True)
    a.move(4, 21)
    a.branch(3, 0, 'own_next')
    a.nop()
    a.branch(5, 16, 'own_next', not_equal=True)
    a.nop()
    a.move(19, 21)
    a.move(20, 2)
    a.addiu(23, 0, 1)
    a.branch(0, 0, 'chosen')
    a.nop()
    a.label('own_next')
    a.addiu(21, 21, 1)
    a.emit((21 << 21) | (18 << 16) | (8 << 11) | 0x2B)
    a.branch(8, 0, 'own_loop', not_equal=True)
    a.nop()
    # No teammate lives: preserve a living opponent already being followed.
    a.branch(22, 0, 'enemy_owner', not_equal=True)
    a.nop()
    a.move(21, 0)
    a.label('any_loop')
    a.jump(LOOKUP, link=True)
    a.move(4, 21)
    a.branch(3, 0, 'any_next')
    a.nop()
    a.move(19, 21)
    a.move(20, 2)
    a.branch(0, 0, 'enemy_owner')
    a.nop()
    a.label('any_next')
    a.addiu(21, 21, 1)
    a.emit((21 << 21) | (18 << 16) | (8 << 11) | 0x2B)
    a.branch(8, 0, 'any_loop', not_equal=True)
    a.nop()
    a.addiu(8, 0, -1)
    a.branch(20, 8, 'body_owner', not_equal=True)
    a.nop()
    # Everyone is defeated: prefer the side's original body if owner vanished.
    a.jump(LOOKUP, link=True)
    a.move(4, 16)
    a.addiu(8, 0, -1)
    a.branch(2, 8, 'scan_body')
    a.nop()
    a.move(19, 16)
    a.move(20, 2)
    a.branch(0, 0, 'body_owner')
    a.nop()
    a.label('scan_body')
    a.move(21, 0)
    a.label('body_loop')
    a.jump(LOOKUP, link=True)
    a.move(4, 21)
    a.addiu(8, 0, -1)
    a.branch(2, 8, 'body_next')
    a.nop()
    a.move(19, 21)
    a.move(20, 2)
    a.branch(0, 0, 'body_owner')
    a.nop()
    a.label('body_next')
    a.addiu(21, 21, 1)
    a.emit((21 << 21) | (18 << 16) | (8 << 11) | 0x2B)
    a.branch(8, 0, 'body_loop', not_equal=True)
    a.nop()
    a.branch(0, 0, 'fallback')
    a.nop()
    for label, reason in (('stable_own', 0), ('enemy_owner', 2), ('body_owner', 3)):
        a.label(label)
        a.addiu(23, 0, reason)
        a.branch(0, 0, 'chosen')
        a.nop()
    a.label('chosen')
    a.mem(35, 8, 17, 8)
    a.branch(8, 19, 'same_owner')
    a.nop()
    a.mem(35, 8, 17, 0x18)
    a.addiu(8, 8, 1)
    a.mem(43, 8, 17, 0x18)
    a.label('same_owner')
    a.mem(43, 19, 17, 8)
    a.mem(43, 20, 17, 0x10)
    a.mem(43, 23, 17, 0x28)
    a.mem(35, 8, 17, 0x20)
    a.addiu(8, 8, 1)
    a.mem(43, 8, 17, 0x20)
    a.emit((19 << 16) | (9 << 11) | (2 << 6))
    a.load_address(8, POINTERS)
    a.emit((8 << 21) | (9 << 16) | (8 << 11) | 0x21)
    a.mem(35, 8, 8, 0)
    a.mem(43, 8, 17, 0x30)
    a.move(2, 20)
    for reg, offset in saved:
        a.mem(55, reg, 29, offset)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x90)
    a.label('fallback')
    for reg, offset in saved:
        a.mem(55, reg, 29, offset)
    a.jump(NATIVE)
    a.addiu(29, 29, 0x90)
    return a.finish()


def build(source=None):
    code, helper = stub(), lookup_stub()
    assert CODE+len(code) < LOOKUP and LOOKUP+len(helper) < CONTROL
    ram = Path(source).read_bytes() if source else None
    manager = struct.unpack_from('<I', ram, MODE+8)[0] if ram else 0x1800100
    if ram:
        assert len(ram) == 0x8000000 and manager != 0
        assert struct.unpack_from('<I', ram, A(0x2FEB14))[0] == manager
    control = bytearray(0x40)
    struct.pack_into('<6I', control, 0, 1, manager, 0, 1, 0xFFFFFFFF, 0xFFFFFFFF)
    payloads = ((CODE, code), (LOOKUP, helper), (CONTROL, bytes(control)))
    old = struct.pack('<I', (3 << 26) | (NATIVE >> 2))
    new = struct.pack('<I', (3 << 26) | (CODE >> 2))
    blocks = []
    if ram:
        for address, data in payloads:
            prior = ram[address:address+len(data)]
            assert not any(prior), f'Occupied camera successor reservation{address:08X}'
            blocks.append({'address': address, 'expected_hex': prior.hex(), 'data_hex': data.hex()})
        assert ram[HOOK:HOOK+4] == old
        assert ram[HOOK+4:HOOK+8] == bytes.fromhex('400c508c'), 'Native camera delay slot changed'
        blocks.append({'address': HOOK, 'expected_hex': old.hex(), 'data_hex': new.hex()})
    return {'serial': SERIAL, 'crc': CRC, 'status': 'CAMERA SURVIVOR SUCCESSION; OFFLINE TESTED',
            'source_ram': str(Path(source).resolve()) if source else None,
            'segments': [{'address': p, 'data_hex': b.hex()} for p, b in payloads], 'blocks': blocks,
            'control': CONTROL, 'control_fields': {'enabled': 0, 'captured_manager': 4,
                'owner0': 8, 'owner1': 12, 'model0': 16, 'model1': 20, 'switches0': 24,
                'switches1': 28, 'calls0': 32, 'calls1': 36, 'reason0': 40, 'reason1': 44,
                'actor0': 48, 'actor1': 52},
            'reasons': {0: 'stable living teammate', 1: 'next living teammate', 2: 'surviving opponent', 3: 'retained fallen body'},
            'behavior': ['Keep the current living teammate; otherwise choose the first living teammate.',
                         'When own team is eliminated, retain or choose a living opposing fighter.',
                         'When everyone is defeated, retain a valid body; if none exist use native scene lookup.',
                         'Return the actual model ID, including7/10, without changing character IDs, targets, AI roles, or ownership.'],
            'requirements': ['Expanded D8080/D8040 captured actor routing with current manager identity.',
                             'FC000 leader-camera ownership/clock patch remains separate and unchanged.',
                             'Apply paused and save/reload to invalidate code caches.'],
            'limitations': ['Camera successor behavior needs live visual validation.',
                            'Human controller ownership does not transfer with the camera.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ram', type=Path)
    p.add_argument('--out', type=Path, default=ROOT/'analysis/camera-successor.json')
    args = p.parse_args()
    result = build(args.ram)
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(f"{args.out}: {len(result['blocks'])} guarded blocks")
