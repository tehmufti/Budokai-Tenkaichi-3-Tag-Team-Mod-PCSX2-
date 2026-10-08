"""Offline optional melee contact producer supporting model IDs0..11.

Preserves selected-pair behavior; records a separate matrix and exposes a
Boolean native contact sentinel, never shifts model IDs into terrain flags.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader

PRODUCER = A(0x1AF6CC)
RESUME = A(0x1AF720)
ENTRY = A(0x1AF740)
RECORD = 0xD0000
BEGIN = 0xD0200
ORIGINAL = 0xD0300
CONTROL = 0xD1000
ROWS = CONTROL + 0x40
OLD_PASS = 0xC0400


def record_code():
    a = Assembler(RECORD)
    a.lw(4, 20, 16)  # s4 attacker model, s1 defender model.
    a.lw(5, 17, 16)
    a.li(2, CONTROL)
    a.lw(3, 2)
    a.branch(4, 3, 0, 'disabled')
    for reg in (4, 5):
        a.i(11, 3, reg, 12)
        a.branch(4, 3, 0, 'invalid')
    a.r(0, 4, 0, 4, 2)
    a.li(2, ROWS)
    a.r(0x2D, 2, 2, 4)
    a.lw(4, 2)
    a.addiu(3, 0, 1)
    a.r(4, 3, 5, 3)  # 32-bit SLLV; shift count now restricted0..11.
    a.r(0x25, 4, 4, 3)
    a.sw(4, 2)
    a.li(2, CONTROL)
    a.lw(4, 2, 4)
    a.addiu(4, 4, 1)
    a.sw(4, 2, 4)
    a.li(3, 98336)
    a.r(0x2D, 3, 3, 16)  # s0 attacker scratch.
    a.lw(4, 3)
    a.li(5, 0x01000000)
    a.r(0x25, 4, 4, 5)
    a.sw(4, 3)  # A Boolean outgoing-contact sentinel; low24bits preserved.
    a.addiu(2, 0, 1)
    a.jump(RESUME)
    a.label('disabled')
    # The old ID encoding is safe only for the original four model slots.
    for reg in (4, 5):
        a.i(11, 3, reg, 4)
        a.branch(4, 3, 0, 'invalid')
    a.addiu(5, 0, 1)  # Native tail shifts its original a1=1 input.
    a.jump(ORIGINAL)
    a.label('invalid')
    a.li(2, CONTROL)
    a.lw(3, 2, 12)
    a.addiu(3, 3, 1)
    a.sw(3, 2, 12)
    a.move(2, 0)
    a.jump(RESUME)
    code = a.finish()
    assert len(code) <= BEGIN - RECORD
    return code


def begin_code():
    a = Assembler(BEGIN)
    a.addiu(29, 29, -16)
    a.i(63, 31, 29, 0)
    a.li(8, CONTROL)
    a.lw(9, 8)
    a.branch(4, 9, 0, 'call')
    a.lw(9, 8, 8)
    a.addiu(9, 9, 1)
    a.sw(9, 8, 8)
    a.li(8, ROWS)
    a.addiu(9, 8, 48)
    a.label('clear')
    a.sw(0, 8)
    a.addiu(8, 8, 4)
    a.branch(5, 8, 9, 'clear')
    a.label('call')
    a.call(OLD_PASS)
    a.i(55, 31, 29, 0)
    a.addiu(29, 29, 16)
    a.jr()
    code = a.finish()
    assert len(code) <= ORIGINAL - BEGIN
    return code


def build(ram_path, output):
    ram = Path(ram_path).read_bytes()
    assert len(ram) == 0x2000000
    _, segments, readelf = elf_reader(elf_path(ROOT))
    assert not any(va < CONTROL + 0x100 and RECORD < va + memsz for va, _, _, memsz in segments)
    assert not any(ram[RECORD:CONTROL + 0x100]), 'Contact reservation occupied'
    original_tail = readelf(PRODUCER, RESUME - PRODUCER)
    assert ram[PRODUCER:RESUME] == original_tail, 'Melee contact producer changed'
    old_hook = struct.pack('<2I', (2 << 26) | (OLD_PASS >> 2), 0)
    assert ram[ENTRY:ENTRY + 8] == old_hook, 'Requires reciprocal selected-pair pass at C0400'
    u = lambda address: struct.unpack_from('<I', ram, address)[0]
    assert u(0xC1020) == 1 and u(0xB3088) == 1
    trampoline = Assembler(ORIGINAL)
    for word in struct.unpack('<' + 'I' * (len(original_tail) // 4), original_tail):
        trampoline.emit(word)
    trampoline.jump(RESUME)
    controls = bytearray(0x100)
    struct.pack_into('<I', controls, 0, 1)
    blocks = []
    for address, data, purpose in (
        (RECORD, record_code(), 'Record real model contact matrix; expose Boolean native contact'),
        (BEGIN, begin_code(), 'Clear twelve rows once per selected-pair melee pass'),
        (ORIGINAL, trampoline.finish(), 'Native four-model producer tail for disabled fallback'),
        (CONTROL, bytes(controls), 'enabled,total contacts,pass epoch,rejected IDs; matrix rows at+40'),
        (PRODUCER, struct.pack('<2I', (2 << 26) | (RECORD >> 2), 0), 'Replace only successful-geometry contact encoding'),
        (ENTRY, struct.pack('<2I', (2 << 26) | (BEGIN >> 2), 0), 'Wrap existing reciprocal collision pass'),
    ):
        blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                       'data_hex': data.hex(), 'purpose': purpose})
    result = {'serial': SERIAL, 'crc': CRC,
              'status': 'OPTIONAL CONTACT MATRIX; LIVE EXECUTION UNTESTED',
              'source_ram': str(Path(ram_path).resolve()), 'control': CONTROL, 'rows': ROWS,
              'control_fields': {'0': 'enabled', '4': 'successful geometry records',
                                 '8': 'matrix pass epoch', '12': 'rejected model ID pairs'},
              'row_format': '12u32; row[attackerModelID] bit defenderModelID records contact in the latest pass',
              'requirements': ['Apply while paused with all expected bytes verified; save/reload to flush EE caches.',
                               'The existing four-actor selected-pair scheduler remains unchanged.',
                               'Matrix encoding supports IDs0..11; model allocation, AI, resources and target scheduler still support four actors.',
                               'Do not add arbitrary enemy pairs without choosing/latching the contacted defender for native hit resolution.',
                               'The matrix is telemetry for the latest collision pass; native sentinels retain native reset timing.'],
              'blocks': blocks}
    output = Path(output)
    output.write_text(json.dumps(result, indent=2) + '\n')
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
    lines = []
    for address, data in ((RECORD, record_code()), (BEGIN, begin_code()), (ORIGINAL, trampoline.finish())):
        decoded = list(md.disasm(data, address))
        assert len(decoded) * 4 == len(data)
        lines.extend(f'{ins.address:08X}: {ins.mnemonic} {ins.op_str}' for ins in decoded)
    output.with_suffix('.asm.txt').write_text('\n'.join(lines) + '\n')
    print(f'{output}: record{len(record_code())},pass{len(begin_code())},native{len(trampoline.finish())}bytes')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ram', type=Path, default=ROOT / 'analysis/pairs35.bin')
    ap.add_argument('--out', type=Path, default=ROOT / 'analysis/contact-matrix.json')
    args = ap.parse_args()
    build(args.ram, args.out)
