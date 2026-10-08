"""Offline four-actor reciprocal fixed-target upgrade. No live writes.

Physical pairs0<->3 and1<->2 share target selection, melee geometry and
projectile model selection. Source pointers retain identity during AI aliases.
"""
from native_map import A, CRC, SERIAL, TRANSLATED, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from selector_complete import BLOCKS as MISSING, block_code as parity_code

RESOLVER = 0xC0000
COLLISION = 0xC0400
PROJECTILE = 0xC0C00
TARGETS = 0xC1000
POINTERS = 0xC1010
ENABLED = 0xC1020
COUNTERS = 0xC1040
HEADER = 0xB3080
ACTORS = A(0x2FEB14)
MODELS = A(0x31C640)


def emit_gate(a, fail):
    for address, offset in ((ENABLED, 0), (HEADER, 8)):
        a.li(8, address)
        a.lw(8, 8, offset)
        a.branch(4, 8, 0, fail)
    a.li(8, ACTORS)
    a.lw(8, 8)
    a.li(9, HEADER)
    a.lw(9, 9, 12)
    a.branch(5, 8, 9, fail)


def resolver_code():
    a = Assembler(RESOLVER)
    emit_gate(a, 'fallback')
    a.li(8, POINTERS)
    for physical in range(4):
        a.lw(9, 8, 4 * physical)
        a.branch(4, 4, 9, f'actor_{physical}')
    a.jump('fallback')
    for physical in range(4):
        a.label(f'actor_{physical}')
        a.li(8, TARGETS + 4 * physical)
        a.lw(3, 8)
        a.i(11, 9, 3, 4)
        a.branch(4, 9, 0, 'fallback')
        a.i(12, 9, 3, 1)
        a.addiu(10, 0, physical & 1)
        a.branch(4, 9, 10, 'fallback')
        a.jump('lookup')
    a.label('lookup')
    a.li(8, POINTERS)
    a.r(0, 9, 0, 3, 2)
    a.r(0x2D, 8, 8, 9)
    a.lw(2, 8)
    a.branch(4, 2, 0, 'fallback')
    a.jr()
    a.label('fallback')
    a.lw(3, 4)
    a.i(12, 3, 3, 1)
    a.i(14, 3, 3, 1)
    a.li(8, ACTORS)
    a.lw(8, 8)
    a.lw(2, 8, 4)
    a.branch(4, 3, 0, 'return')
    a.addiu(2, 2, 0x1600)
    a.label('return')
    a.jr()
    code = a.finish()
    assert len(code) < COLLISION - RESOLVER
    return code


def selector_code(address, source, destination=None):
    a = Assembler(address)
    a.move(4, source)
    a.call(RESOLVER)
    while len(a.words) < 9:
        a.emit(0)
    a.move(destination, 2) if destination is not None else a.emit(0)
    return a.finish()


def collision_code():
    a = Assembler(COLLISION)
    a.addiu(29, 29, -0x20)
    for reg, offset in ((16, 0), (17, 8), (31, 16)):
        a.i(63, reg, 29, offset)
    emit_gate(a, 'fallback')
    for physical in range(4):
        next_pair = f'next_{physical}'
        a.li(8, POINTERS + physical * 4)
        a.lw(4, 8)
        a.branch(4, 4, 0, next_pair)
        a.move(16, 4)
        a.call(RESOLVER)
        a.branch(4, 2, 0, next_pair)
        for argument, actor in ((4, 16), (5, 2)):
            a.lw(9, actor, 12)
            a.i(11, 10, 9, 4)
            a.branch(4, 10, 0, next_pair)
            a.li(8, MODELS)
            a.r(0, 10, 0, 9, 2)
            a.r(0x2D, 8, 8, 10)
            a.lw(argument, 8)
            a.branch(4, argument, 0, next_pair)
            a.lw(10, argument, 16)
            a.branch(5, 9, 10, next_pair)
            for offset in (4, 8, 5728):
                a.lw(8, argument, offset)
                a.branch(4, 8, 0, next_pair)
        a.li(17, COUNTERS + physical * 12)
        a.lw(8, 17)
        a.addiu(8, 8, 1)
        a.sw(8, 17)
        a.call(A(0x1AF650))
        a.sw(2, 17, 8)
        a.branch(4, 2, 0, next_pair)
        a.lw(8, 17, 4)
        a.addiu(8, 8, 1)
        a.sw(8, 17, 4)
        a.label(next_pair)
    a.move(2, 0)
    a.jump('done')
    a.label('fallback')
    a.call(0xBB000)  # Existing proven four-actor opposing-leader wrapper.
    a.label('done')
    for reg, offset in ((16, 0), (17, 8), (31, 16)):
        a.i(55, reg, 29, offset)
    a.addiu(29, 29, 0x20)
    a.jr()
    code = a.finish()
    assert len(code) < PROJECTILE - COLLISION
    return code


def projectile_code():
    a = Assembler(PROJECTILE)
    saved = [(4, 0), (8, 8), (9, 16), (10, 24), (11, 32), (31, 40)]
    a.addiu(29, 29, -0x30)
    for reg, offset in saved:
        a.i(63, reg, 29, offset)
    emit_gate(a, 'fallback')
    a.lw(2, 18, -0x130)
    # 12DEA8 takes basic-shot ownership from descriptor+18 (model ID), but
    # attack-record ownership from metadata[0] (physical ID). Basic wins if
    # both metadata pointers exist, matching the original construction order.
    a.lw(9, 18, -200)
    a.branch(5, 9, 0, 'model_source')
    a.lw(9, 18, -204)
    a.branch(4, 9, 0, 'model_source')
    a.i(11, 9, 2, 4)
    a.branch(4, 9, 0, 'fallback')
    a.li(8, POINTERS)
    a.r(0, 9, 0, 2, 2)
    a.r(0x2D, 8, 8, 9)
    a.lw(4, 8)
    a.branch(4, 4, 0, 'fallback')
    a.jump('found')
    a.label('model_source')
    a.li(8, POINTERS)
    for physical in range(4):
        a.lw(4, 8, 4 * physical)
        a.branch(4, 4, 0, f'next_{physical}')
        a.lw(9, 4, 12)
        a.branch(4, 2, 9, 'found')
        a.label(f'next_{physical}')
    a.jump('fallback')
    a.label('found')
    a.call(RESOLVER)
    a.lw(17, 2, 12)  # Callbacks use logical/model ID, not physical actor ID.
    a.move(4, 17)
    a.call(A(0x2499B0))
    for reg, offset in saved:
        a.i(55, reg, 29, offset)
    a.addiu(29, 29, 0x30)
    a.jump(A(0x1B00E8))  # v0=model pointer; bypass two-leader roster lookup.
    a.label('fallback')
    for reg, offset in saved:
        a.i(55, reg, 29, offset)
    a.addiu(29, 29, 0x30)
    a.jump(0xBB400)
    code = a.finish()
    assert len(code) < TARGETS - PROJECTILE
    return code


def build(ram_path, output):
    if TRANSLATED:
        raise ValueError('The four-actor research target upgrade reads the USA-only September research patch')
    ram = Path(ram_path).read_bytes()
    assert len(ram) == 0x2000000
    u = lambda address: struct.unpack_from('<I', ram, address)[0]
    assert u(HEADER + 4) == 2 and u(HEADER + 8) == 1
    manager = u(ACTORS)
    assert u(manager) == 2 and u(HEADER + 12) == manager
    actors = [u(manager + 4), u(manager + 4) + 0x1600, u(0xB301C), u(0xB305C)]
    assert len(set(actors)) == 4 and all(u(pointer) == index for index, pointer in enumerate(actors))
    assert sorted(u(pointer + 12) for pointer in actors) == [0, 1, 2, 3]
    assert not any(ram[RESOLVER:0xC1100]), 'Fixed-target reservation occupied'
    _, _, readelf = elf_reader(elf_path(ROOT))
    old = json.loads((ROOT / 'analysis/research_opponent_patches.json').read_text())['patches']
    selectors = [(int(item['address'], 16), None) for item in old]
    selectors += [(address, destination) for address, _, destination in MISSING]
    expected_selectors = {int(item['address'], 16): struct.pack('<10I', *[int(word, 16) for word in item['new_words']]) for item in old}
    expected_selectors.update({address: parity_code(address, source, destination)
                              for address, source, destination in MISSING})
    assert len(selectors) == 27 and len(set(address for address, _ in selectors)) == 27
    blocks = []
    def block(address, data, purpose):
        blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                       'data_hex': data.hex(), 'purpose': purpose})
    for address, code, purpose in (
        (RESOLVER, resolver_code(), 'Pointer-identity target actor resolver'),
        (COLLISION, collision_code(), 'Test only reciprocal selected melee pairs'),
        (PROJECTILE, projectile_code(), 'Use selected target model for geometry and callbacks'),
        (TARGETS, struct.pack('<4I', 3, 2, 1, 0), 'Fixed physical target table'),
        (POINTERS, struct.pack('<4I', *actors), 'Captured physical actor pointers; manager/exposure gated'),
        (COUNTERS, bytes(48), 'Per physical actor attempts, contacts, last native result'),
    ):
        block(address, code, purpose)
    for address, destination in selectors:
        source = (struct.unpack('<I', readelf(address, 4))[0] >> 21) & 31
        assert source in (4, 17)
        assert ram[address:address + 40] == expected_selectors[address], f'Unexpected selector at {address:08X}'
        block(address, selector_code(address, source, destination), 'Use common fixed target actor in opponent helper')
    for address, expected, target in ((A(0x1AF740), 0xBB000, COLLISION), (A(0x1B00C4), 0xBB400, PROJECTILE)):
        assert u(address) == (2 << 26) | (expected >> 2) and u(address + 4) == 0
        block(address, struct.pack('<2I', (2 << 26) | (target >> 2), 0), 'Upgrade existing melee/projectile hook')
    block(ENABLED, struct.pack('<I', 1), 'Enable fixed reciprocal targets last')
    result = {'serial': SERIAL, 'crc': CRC,
              'status': 'EXPERIMENTAL RECIPROCAL FOUR-ACTOR TARGETS; LIVE EXECUTION UNTESTED',
              'source_ram': str(Path(ram_path).resolve()), 'target_table': TARGETS,
              'physical_pointers': POINTERS, 'enabled': ENABLED, 'counters': COUNTERS,
              'actors': actors, 'blocks': blocks,
              'requirements': ['Apply while paused against all expected bytes; save/reload to flush EE caches.',
                               'Pair-specific AI update required for CPU leaders to pursue the new targets.',
                               'Camera roster and leader camera copying remain unchanged.',
                               'Targets stay fixed during delayed attacks; dynamic retargeting is not implemented.']}
    Path(output).write_text(json.dumps(result, indent=2) + '\n')
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
    disassembly = []
    for address, code in ((RESOLVER, resolver_code()), (COLLISION, collision_code()), (PROJECTILE, projectile_code())):
        decoded = list(md.disasm(code, address))
        assert len(decoded) * 4 == len(code)
        disassembly.extend(f'{ins.address:08X}: {ins.mnemonic} {ins.op_str}' for ins in decoded)
    Path(output).with_suffix('.asm.txt').write_text('\n'.join(disassembly) + '\n')
    print(f'{output}: {len(blocks)} blocks; resolver {len(resolver_code())}, melee {len(collision_code())}, projectile {len(projectile_code())} bytes')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ram', type=Path, default=ROOT / 'analysis/team-basic-ready.bin')
    ap.add_argument('--out', type=Path, default=ROOT / 'analysis/team-targets.json')
    args = ap.parse_args()
    build(args.ram, args.out)
