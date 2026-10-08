"""Offline selected-target routing for six actors, with capacity through twelve.

Separates physical actor IDs from registered model IDs and retains temporary
pair AI aliases. Installs disabled; scheduler/getter activation is separate.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
import team_targets as old

RESOLVER, COLLISION, PROJECTILE = 0xD5000, 0xD6000, 0xD7000
TARGETS, POINTERS, CONTROL = 0xD8000, 0xD8040, 0xD8080
COUNTERS = 0xD80A0
CAPACITY = 12
PAIR = 0xC4000
NEW_EXPOSURE = 0xF609C
NEW_DESCRIPTORS = (0xF6000, 0xF6040)
INITIAL_TARGETS = (3, 2, 1, 0, 5, 4)


def gate(a, fail):
    """Validate active layout; retain active count in t2 without native calls."""
    a.li(8, CONTROL)
    a.lw(9, 8)
    a.branch(4, 9, 0, fail)
    a.lw(10, 8, 4)
    a.branch(4, 10, 0, fail)
    a.i(11, 9, 10, CAPACITY + 1)
    a.branch(4, 9, 0, fail)
    a.lw(9, 8, 8)
    a.branch(4, 9, 0, fail)
    a.li(8, old.ACTORS)
    a.lw(8, 8)
    a.branch(5, 8, 9, fail)
    for address in (old.ENABLED, old.HEADER + 8):
        a.li(8, address)
        a.lw(8, 8)
        a.branch(4, 8, 0, fail)
    a.i(11, 9, 10, 5)
    a.branch(5, 9, 0, 'gate_ready')
    a.li(8, NEW_EXPOSURE)
    a.lw(8, 8)
    a.branch(4, 8, 0, fail)
    a.label('gate_ready')


def resolver_code():
    a = Assembler(RESOLVER)
    gate(a, 'legacy')
    a.li(8, PAIR)
    for offset in (0, 4):
        a.lw(9, 8, offset)
        a.branch(4, 9, 0, 'global')
    a.lw(9, 8, 8)
    a.branch(4, 4, 9, 'role0')
    a.lw(9, 8, 12)
    a.branch(5, 4, 9, 'global')
    a.lw(2, 8, 8)
    a.lw(3, 8, 16)
    a.jump('pair_check')
    a.label('role0')
    a.lw(2, 8, 12)
    a.lw(3, 8, 20)
    a.label('pair_check')
    a.branch(4, 2, 0, 'global')
    a.r(0x2B, 9, 3, 10)
    a.branch(4, 9, 0, 'global')
    a.li(8, POINTERS)
    a.r(0, 9, 0, 3, 2)
    a.r(0x2D, 8, 8, 9)
    a.lw(9, 8)
    a.branch(5, 2, 9, 'global')
    a.jr()
    a.label('global')
    a.li(8, POINTERS)
    a.move(3, 0)
    a.label('find')
    a.lw(2, 8)
    a.branch(4, 4, 2, 'found')
    a.addiu(8, 8, 4)
    a.addiu(3, 3, 1)
    a.r(0x2B, 9, 3, 10)
    a.branch(5, 9, 0, 'find')
    a.jump('legacy')
    a.label('found')
    a.i(12, 2, 3, 1)
    a.li(8, TARGETS)
    a.r(0, 9, 0, 3, 2)
    a.r(0x2D, 8, 8, 9)
    a.lw(3, 8)
    a.r(0x2B, 9, 3, 10)
    a.branch(4, 9, 0, 'legacy')
    a.i(12, 9, 3, 1)
    a.branch(4, 9, 2, 'legacy')
    a.li(8, POINTERS)
    a.r(0, 9, 0, 3, 2)
    a.r(0x2D, 8, 8, 9)
    a.lw(2, 8)
    a.branch(4, 2, 0, 'legacy')
    a.jr()
    a.label('legacy')
    # D3000 can resolve unpublished actor4/5 aliases during native AI init.
    a.jump(0xD3000)
    code = a.finish()
    assert len(code) < COLLISION - RESOLVER
    return code


def model_argument(a, argument, actor, fail):
    a.lw(9, actor, 12)
    a.i(11, 11, 9, CAPACITY)
    a.branch(4, 11, 0, fail)
    a.li(8, old.MODELS)
    a.r(0, 11, 0, 9, 2)
    a.r(0x2D, 8, 8, 11)
    a.lw(argument, 8)
    a.branch(4, argument, 0, fail)
    a.lw(11, argument, 16)
    a.branch(5, 9, 11, fail)
    for offset in (4, 8, 5728):
        a.lw(8, argument, offset)
        a.branch(4, 8, 0, fail)


def alive_argument(a, actor, fail):
    """Native current-roster HP layout, without calls or identity aliases.

    1DC320 -> 1CE1B8 -> 1CE050 -> 1CE030 reads signed HP at
    actor + 0x9E4 + 164 * current_slot. Native rosters contain at most five.
    Only t0/t1 are clobbered; actor may be a0, v0, or t3.
    """
    a.lw(9, actor, 0x994)
    a.i(11, 8, 9, 5)
    a.branch(4, 8, 0, fail)
    a.r(0, 8, 0, 9, 2)
    a.r(0x2D, 8, 8, 9)
    a.r(0, 8, 0, 8, 3)
    a.r(0x2D, 8, 8, 9)
    a.r(0, 8, 0, 8, 2)
    a.r(0x2D, 8, 8, actor)
    a.lw(9, 8, 0x9E4)
    a.i(10, 9, 9, 1)
    a.branch(5, 9, 0, fail)


def collision_code(alive=False):
    a = Assembler(COLLISION)
    gate(a, 'legacy')
    a.addiu(29, 29, -0x30)
    saved = [(16, 0), (17, 8), (18, 16), (19, 24), (20, 32), (31, 40)]
    for reg, offset in saved:
        a.i(63, reg, 29, offset)
    a.move(20, 10)
    a.move(16, 0)
    a.label('loop')
    a.li(8, POINTERS)
    a.r(0, 9, 0, 16, 2)
    a.r(0x2D, 8, 8, 9)
    a.lw(19, 8)
    a.branch(4, 19, 0, 'next')
    if alive:
        alive_argument(a, 19, 'next')
    a.move(4, 19)
    a.call(old.RESOLVER)
    a.branch(4, 2, 0, 'next')
    a.move(17, 2)
    if alive:
        alive_argument(a, 17, 'next')
    a.li(8, CONTROL)
    a.sw(16, 8, 16)
    a.sw(3, 8, 20)
    model_argument(a, 4, 19, 'next')
    model_argument(a, 5, 17, 'next')
    a.li(18, COUNTERS)
    a.r(0, 8, 0, 16, 3)
    a.r(0x2D, 18, 18, 8)
    a.lw(8, 18)
    a.addiu(8, 8, 1)
    a.sw(8, 18)
    a.call(A(0x1AF650))
    a.branch(4, 2, 0, 'next')
    a.lw(8, 18, 4)
    a.addiu(8, 8, 1)
    a.sw(8, 18, 4)
    a.label('next')
    a.addiu(16, 16, 1)
    a.r(0x2B, 8, 16, 20)
    a.branch(5, 8, 0, 'loop')
    a.move(2, 0)
    for reg, offset in saved:
        a.i(55, reg, 29, offset)
    a.addiu(29, 29, 0x30)
    a.jr()
    a.label('legacy')
    for word in struct.unpack('<2I', old.collision_code()[:8]):
        a.emit(word)
    a.jump(old.COLLISION + 8)
    code = a.finish()
    assert len(code) < PROJECTILE - COLLISION
    return code


def projectile_code(alive=False):
    a = Assembler(PROJECTILE)
    saved = [(4, 0), (8, 8), (9, 16), (10, 24), (11, 32), (31, 40), (17, 48)]
    a.addiu(29, 29, -0x40)
    for reg, offset in saved:
        a.i(63, reg, 29, offset)
    gate(a, 'legacy')
    a.lw(2, 18, -0x130)
    a.lw(9, 18, -200)
    a.branch(5, 9, 0, 'model_source')
    a.lw(9, 18, -204)
    a.branch(4, 9, 0, 'model_source')
    a.r(0x2B, 9, 2, 10)
    a.branch(4, 9, 0, 'skip')
    a.li(8, POINTERS)
    a.r(0, 9, 0, 2, 2)
    a.r(0x2D, 8, 8, 9)
    a.lw(4, 8)
    a.branch(4, 4, 0, 'skip')
    a.jump('found')
    a.label('model_source')
    a.li(8, POINTERS)
    a.move(11, 0)
    a.label('scan')
    a.lw(4, 8)
    a.branch(4, 4, 0, 'next')
    a.lw(9, 4, 12)
    a.branch(4, 2, 9, 'found')
    a.label('next')
    a.addiu(8, 8, 4)
    a.addiu(11, 11, 1)
    a.r(0x2B, 9, 11, 10)
    a.branch(5, 9, 0, 'scan')
    a.jump('skip')
    a.label('found')
    if alive:
        alive_argument(a, 4, 'skip')
    a.call(old.RESOLVER)
    a.branch(4, 2, 0, 'skip')
    a.move(11, 2)
    if alive:
        alive_argument(a, 11, 'skip')
    a.lw(17, 11, 12)
    # Validate the same physical-to-model identity used by melee.
    model_argument(a, 2, 11, 'skip')
    for reg, offset in saved:
        if reg != 17:  # Native callbacks need the selected target model ID.
            a.i(55, reg, 29, offset)
    a.addiu(29, 29, 0x40)
    a.jump(A(0x1B00E8))
    a.label('skip')
    for reg, offset in saved:
        a.i(55, reg, 29, offset)
    a.addiu(29, 29, 0x40)
    # Native no-contact continuation loads projectile count and advances loop.
    a.jump(A(0x1B01FC))
    a.label('legacy')
    for reg, offset in saved:
        a.i(55, reg, 29, offset)
    a.addiu(29, 29, 0x40)
    for word in struct.unpack('<2I', old.projectile_code()[:8]):
        a.emit(word)
    a.jump(old.PROJECTILE + 8)
    code = a.finish()
    assert len(code) < TARGETS - PROJECTILE
    return code


def build(source, output):
    ram = Path(source).read_bytes()
    assert len(ram) == 0x8000000, 'Six-actor creation requires the128 MiB checkpoint'
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    assert not any(ram[RESOLVER:0xD8100]), 'Target expansion reservation occupied'
    _, segments, readelf = elf_reader(elf_path(ROOT))
    assert not any(va < 0xD8100 and RESOLVER < va + size for va, _, _, size in segments)
    assert u(0xF6080) == 20 and u(0xF6088) == 2, 'Third bench actors not created'
    assert u(0xB3088) and not u(PAIR + 4), 'Require intact four actors outside AI alias slice'
    manager = u(old.ACTORS)
    assert manager and manager == u(old.HEADER + 12) and u(manager) == 2
    actors = [u(manager + 4), u(manager + 4) + 0x1600, u(0xB301C), u(0xB305C)]
    actors += [u(p + 28) for p in NEW_DESCRIPTORS]
    assert len(set(actors)) == 6
    models = []
    for physical, actor in enumerate(actors):
        assert 0x100000 <= actor <= len(ram) - 0x1600 and u(actor) == physical
        model_id = u(actor + 12)
        assert model_id < CAPACITY
        model = u(old.MODELS + model_id * 4)
        assert model and u(model + 16) == model_id
        assert all(u(model + offset) for offset in (4, 8, 5728))
        if physical >= 4:
            descriptor = NEW_DESCRIPTORS[physical - 4]
            assert u(descriptor) == 20 and u(descriptor + 8) == model_id and u(descriptor + 12) == model
        models.append({'physical': physical, 'model_id': model_id, 'model': model})
    assert len(set(row['model_id'] for row in models)) == 6
    assert ram[old.RESOLVER:old.RESOLVER + 8] == struct.pack('<2I', (2 << 26) | (0xD3000 >> 2), 0)
    assert ram[old.COLLISION:old.COLLISION + len(old.collision_code())] == old.collision_code()
    # The applied pair checkpoint predates the later metadata-aware variant.
    # Both versions share the displaced first two instructions and native frame.
    applied_pair = json.loads((ROOT / 'analysis/team-pairs-combined.json').read_text())
    applied_projectile = next(bytes.fromhex(block['data_hex']) for block in applied_pair['blocks']
                              if block['address'] == old.PROJECTILE)
    assert len(applied_projectile) == 312 and applied_projectile[:8] == old.projectile_code()[:8]
    assert any(ram[old.PROJECTILE:old.PROJECTILE + len(code)] == code
               for code in (applied_projectile, old.projectile_code())), 'Unknown legacy projectile hook'
    assert u(A(0x1AF740)) == (2 << 26) | (0xD0200 >> 2), 'Require active contact-matrix pass wrapper'
    assert u(A(0x1B00C4)) == (2 << 26) | (old.PROJECTILE >> 2)
    assert u(0xD1000) == 1, 'Twelve-model contact encoding must be enabled before widening model IDs'
    assert readelf(A(0x1B01FC), 4) == struct.pack('<I', 0x8E826400)
    data = bytearray(0x100)
    struct.pack_into('<12I', data, 0, *INITIAL_TARGETS, *([0xFFFFFFFF] * 6))
    struct.pack_into('<12I', data, 0x40, *actors, *([0] * 6))
    struct.pack_into('<4I', data, 0x80, 0, 6, manager, 0)
    blocks = []
    for address, blob, purpose in (
        (RESOLVER, resolver_code(), 'Physical pointer target resolver with current pair aliases'),
        (COLLISION, collision_code(), 'Selected-target melee using actual registered model IDs'),
        (PROJECTILE, projectile_code(), 'Projectile owner and defender resolution for up to twelve models'),
        (TARGETS, bytes(data), 'Twelve-capacity targets/pointers/counters; initially six actors disabled'),
        (old.RESOLVER, struct.pack('<2I', (2 << 26) | (RESOLVER >> 2), 0), 'Route existing27 selectors through expanded resolver'),
        (old.COLLISION, struct.pack('<2I', (2 << 26) | (COLLISION >> 2), 0), 'Retain contact-matrix wrapper while expanding its pass'),
        (old.PROJECTILE, struct.pack('<2I', (2 << 26) | (PROJECTILE >> 2), 0), 'Expand existing projectile hook'),
    ):
        blocks.append({'address': address, 'expected_hex': ram[address:address + len(blob)].hex(),
                       'data_hex': blob.hex(), 'purpose': purpose})
    result = {'serial': SERIAL, 'crc': CRC,
              'status': 'SIX-ACTOR TARGET ROUTING INSTALLED DISABLED; LIVE TEST REQUIRED',
              'source_ram': str(Path(source).resolve()), 'actors': actors, 'models': models,
              'target_table': TARGETS, 'actor_table': POINTERS, 'control': CONTROL,
              'control_fields': {'enabled': 0, 'active_count': 4, 'captured_manager': 8,
                                 'last_source_physical': 16, 'last_target_physical': 20},
              'counters': COUNTERS, 'counter_format': 'twelve pairs of u32 attempts,contacts per physical actor',
              'requirements': ['Apply paused with all exact guards; save/reload to invalidate EE code caches.',
                               'D8080 remains0 until matching getters, actor scheduler and six-context AI are ready.',
                               'For counts above4, F609C must be the coordinated exposure flag.',
                               'Keep the D1000 contact matrix enabled for model IDs above3.',
                               'Six AI must update D8000 targets while retaining pending-hit recipient stability.',
                               'No gameplay actor/model IDs or leader camera sources are changed by this patch.'],
              'blocks': blocks}
    output = Path(output)
    output.write_text(json.dumps(result, indent=2) + '\n')
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
    lines = []
    for address, blob in ((RESOLVER, resolver_code()), (COLLISION, collision_code()), (PROJECTILE, projectile_code())):
        decoded = list(md.disasm(blob, address))
        assert len(decoded) * 4 == len(blob)
        lines.extend(f'{i.address:08X}: {i.mnemonic} {i.op_str}' for i in decoded)
    output.with_suffix('.asm.txt').write_text('\n'.join(lines) + '\n')
    print(f'{output}: resolver{len(resolver_code())},melee{len(collision_code())},projectile{len(projectile_code())}bytes')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--out', type=Path, default=ROOT / 'analysis/team-targets6.json')
    args = ap.parse_args()
    build(args.source, args.out)
