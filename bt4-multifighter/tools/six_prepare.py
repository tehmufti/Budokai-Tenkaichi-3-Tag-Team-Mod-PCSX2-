"""Offline third-bench loader/private actor creation; no six-actor exposure.

AI, scheduling/getters, collision pairing, effects routing and lifecycle for
actors4/5 are separate stages. Actual model IDs may be any free IDs4..11.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import hashlib
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from team_prototype import make_block, write_manifest
from roster_models import private_initializers
from native_map import FILE_ID

CODE, EXT_CODE, HOOK, EXT_ENTRY = 0xF1000, 0xD4000, A(0x1C2A28), A(0x2499C8)
DESCS, HEADER = (0xF6000, 0xF6040), 0xF6080
ALLOC_SIZE, ACTOR_OFF, SHADER_OFF, FX_OFF = 0x20000, 0x1B000, 0x1D000, 0x1F100
AUX_OFFSETS = (0x1F200, 0x1F340)
CACHE, REFRESH = 0xE6000, 0xE6200


def begin(a, previous):
    a.addiu(29, 29, -0x60)
    for n in range(8):
        a.i(63, 16 + n, 29, n * 8)
    a.i(63, 31, 29, 0x40)
    a.call(previous)
    a.i(63, 2, 29, 0x48)
    a.li(16, HEADER)


def finish(a):
    a.label('done')
    a.i(55, 2, 29, 0x48)
    for n in range(8):
        a.i(55, 16 + n, 29, n * 8)
    a.i(55, 31, 29, 0x40)
    a.addiu(29, 29, 0x60)
    a.jr()


def errors(a, values):
    for value in values:
        a.label(f'error{value}')
        a.addiu(8, 0, value)
        a.sw(8, 16)
        a.sw(0, 16, 20)
        a.jump('done')


def input_guards(a, actors, error):
    for actor in actors:
        a.li(8, actor)
        for offset in (0x1278, 0x127C):
            a.lw(9, 8, offset)
            a.branch(5, 9, 0, error)


def ext_code():
    a = Assembler(EXT_CODE)
    a.i(11, 8, 4, 4)
    a.branch(5, 8, 0, 'old')
    a.i(11, 8, 4, 12)
    a.branch(4, 8, 0, 'old')
    for index, desc in enumerate(DESCS):
        a.li(8, desc)
        a.lw(9, 8, 8)
        a.branch(5, 4, 9, f'next{index}')
        a.lw(2, 8, 4)
        a.branch(5, 2, 0, 'return')
        a.label(f'next{index}')
    a.li(8, HEADER)
    a.lw(8, 8, 20)
    a.branch(4, 8, 0, 'old')
    a.lw(2, 8, 4)
    a.branch(4, 2, 0, 'old')
    a.sw(4, 8, 8)
    a.label('return')
    a.jr()
    a.label('old')
    a.jump(0xB2000)
    return a.finish()


def validate(ram):
    assert len(ram) == 0x8000000
    u = lambda address: struct.unpack_from('<I', ram, address)[0]
    assert u(A(0x2FF084)) == 0x02000000 and u(A(0x2FF08C)) == 0x06000000
    assert u(0xC9400) == 20 and u(0xE7000) == 5
    assert u(0xB3084) == 2 and u(0xB3088) == 1
    manager = u(A(0x2FEB14))
    assert manager == u(0xB308C) and u(manager) == 2
    actors = [u(manager + 4), u(manager + 4) + 0x1600, u(0xB301C), u(0xB305C)]
    assert all(u(actor) == index for index, actor in enumerate(actors))
    assert all(u(actor + 0x1278) == 0 and u(actor + 0x127C) == 0 for actor in actors)
    pool = u(A(0x2FEC44))
    registry = pool + 439276
    assert u(pool + 69120 + 8) >= 2, 'Need two free model slots'
    assert u(pool + 397312 + 8) >= 134, 'Need134 native draw nodes for characters133/54'
    rows = []
    for side, actor in enumerate(actors[2:]):
        slot = u(actor + 0x994) + 1
        assert slot == 2 and slot < u(actor + 0x998) <= 5
        character = u(actor + 0x9A4 + slot * 0xA4)
        assert character == (133, 54)[side], 'Current draw-node preflight is specific to selected133/54'
        model_id = u(actor + 12)
        model = u(A(0x31C640) + model_id * 4)
        assert model_id in (2, 3) and u(model + 4) and u(model + 8)
        assert u(actor + 2376) < 236
        rows.append({'source_actor': actor, 'source_model': model, 'side': side,
                     'physical_id': side + 4, 'slot': slot, 'character': character,
                     'file_ids': [FILE_ID(10 * character + value) for value in (1424, 1432, 1433)]})
    _, _, readelf = elf_reader(elf_path(ROOT))
    cache, refresh = private_initializers(readelf)
    assert ram[CACHE:CACHE + len(cache)] == cache and ram[REFRESH:REFRESH + len(refresh)] == refresh
    for address, size in ((A(0x24B7A8), 0xF8), (A(0x2651C0), 0xD8), (A(0x24B910), 0xA8),
                          (A(0x249AB8), 0xA0), (A(0x255CF0), 0x30), (A(0x2554D8), 0x30),
                          (A(0x113660), 0xA0)):
        assert ram[address:address + size] == readelf(address, size), f'Native helper changed:{address:X}'
    return u, manager, actors, pool, registry, rows


def load_code(previous, actors, rows):
    a = Assembler(CODE)
    begin(a, previous)
    a.lw(8, 16)
    a.addiu(9, 0, 1)
    a.branch(4, 8, 9, 'poll')
    a.branch(5, 8, 0, 'done')
    input_guards(a, actors, 'error110')
    a.call(A(0x265298))
    a.branch(4, 2, 0, 'done')
    for index, row in enumerate(rows):
        a.move(4, 0)
        for register, value in zip((5, 6, 7), row['file_ids']):
            a.li(register, value)
        a.call(A(0x24B7A8))
        a.li(17, DESCS[index])
        a.sw(2, 17, 32)
        a.i(11, 8, 2, 2)
        a.branch(5, 8, 0, 'error120')
        a.i(11, 8, 2, 14)
        a.branch(4, 8, 0, 'error120')
    a.addiu(8, 0, 1)
    a.sw(8, 16)
    a.jump('done')
    a.label('poll')
    a.call(A(0x265298))
    a.branch(4, 2, 0, 'done')
    for index, row in enumerate(rows):
        a.li(17, DESCS[index])
        a.lw(4, 17, 32)
        a.call(A(0x24B910))
        a.branch(4, 2, 0, 'error130')
        a.sw(2, 17, 36)
        a.lw(8, 2, 48)
        a.addiu(9, 0, 3)
        a.branch(5, 8, 9, 'error130')
        for file_index, file_id in enumerate(row['file_ids']):
            a.lw(8, 2, file_index * 16)
            a.branch(4, 8, 0, 'error140')
            a.lw(8, 2, file_index * 16 + 8)
            a.addiu(9, 0, file_id)
            a.branch(5, 8, 9, 'error140')
        a.addiu(8, 0, 5)
        a.sw(8, 17)
    a.addiu(8, 0, 5)
    a.sw(8, 16)
    a.jump('done')
    errors(a, (110, 120, 130, 140))
    finish(a)
    return a.finish()


def create_code(previous, actors, pool, rows, offset):
    a = Assembler(CODE)
    begin(a, previous)
    a.lw(8, 16)
    a.addiu(9, 0, 5)
    a.branch(5, 8, 9, 'done')
    input_guards(a, actors, 'error110')
    a.li(8, pool + 397320)
    a.lw(8, 8)
    a.i(11, 9, 8, 134)
    a.branch(5, 9, 0, 'error150')
    a.addiu(8, 0, 10)
    a.sw(8, 16)
    for index, row in enumerate(rows):
        a.li(17, DESCS[index])
        a.li(4, ALLOC_SIZE)
        a.addiu(5, 0, 64)
        a.move(6, 0)
        a.addiu(7, 0, 1)
        a.call(A(0x2554D8))
        a.branch(4, 2, 0, 'error160')
        a.move(18, 2)
        a.sw(18, 17, 4)
        a.move(4, 18)
        a.move(5, 0)
        a.li(6, ALLOC_SIZE)
        a.call(A(0x2A9ACC))
        # Native1146E0 owns three further allocations per shader node. A zero
        # outer node alone is unsafe: packet writers follow node+8240 without
        # a null check and would overwrite EE kernel memory through address0.
        a.addiu(4, 0, 144)
        a.call(A(0x113660))
        a.r(0, 2, 0, 2, 2)
        a.li(8, 0x6E10)
        a.branch(5, 2, 8, 'error161')
        for register, size, align in ((19, 192, 32), (20, 0x6E10, 64), (21, 0x6E10, 64)):
            a.li(4, size)
            a.addiu(5, 0, align)
            a.move(6, 0)
            a.addiu(7, 0, 1)
            a.call(A(0x2554D8))
            a.branch(4, 2, 0, 'error162')
            a.move(register, 2)
            a.move(4, register)
            a.move(5, 0)
            a.li(6, size)
            a.call(A(0x2A9ACC))
        a.sw(20, 19)
        a.sw(21, 19, 4)
        a.li(8, SHADER_OFF)
        a.r(0x21, 8, 18, 8)
        a.sw(19, 8, 8240)
        # Append persistent nodes to the two native pools with insufficient
        # capacity. Native destructors can return these nodes to the same lists.
        for node_offset, list_offset, mailbox_offset in ((SHADER_OFF, 439072, 48),
                                                       (FX_OFF, 397776, 52)):
            a.li(8, node_offset)
            a.r(0x21, 5, 18, 8)
            a.sw(5, 17, mailbox_offset)
            a.li(4, pool + list_offset)
            a.call(A(0x255CF0))
        a.sw(17, 16, 20)
        a.move(4, 0)
        a.lw(5, 17, 36)
        a.addiu(6, 0, 1)
        a.call(A(0x249AB8))
        a.sw(0, 16, 20)
        a.i(11, 8, 2, 4)
        a.branch(5, 8, 0, 'error170')
        a.i(11, 8, 2, 12)
        a.branch(4, 8, 0, 'error170')
        a.sw(2, 17, 8)
        a.move(4, 2)
        a.call(A(0x2499B0))
        a.branch(4, 2, 0, 'error171')
        a.move(19, 2)
        a.sw(19, 17, 12)
        a.lw(8, 19, 5728)
        a.branch(5, 8, 18, 'error172')
        a.lw(8, 19, 12)
        a.addiu(9, 0, row['character'])
        a.branch(5, 8, 9, 'error173')
        a.lw(8, 19, 5736)
        a.branch(4, 8, 0, 'error174')
        a.li(8, ACTOR_OFF)
        a.r(0x21, 20, 18, 8)
        a.sw(20, 17, 28)
        a.li(21, row['source_actor'])
        a.addiu(22, 21, 0x1600)
        a.move(10, 21)
        a.move(11, 20)
        a.label(f'copy{index}')
        a.lw(8, 10)
        a.r(0x2B, 9, 8, 21)
        a.branch(5, 9, 0, f'store{index}')
        a.r(0x2B, 9, 8, 22)
        a.branch(4, 9, 0, f'store{index}')
        a.r(0x23, 8, 8, 21)
        a.r(0x21, 8, 8, 20)
        a.label(f'store{index}')
        a.sw(8, 11)
        a.addiu(10, 10, 4)
        a.addiu(11, 11, 4)
        a.branch(5, 10, 22, f'copy{index}')
        for actor_offset, value in ((0, row['physical_id']), (4, row['side']),
                                    (0x994, row['slot']), (0x1278, 0), (0x127C, 0),
                                    (4912, 0), (4916, 0), (4920, 0), (5608, 0), (5612, 0), (5616, 0)):
            a.addiu(8, 0, value)
            a.sw(8, 20, actor_offset)
        a.lw(8, 17, 8)
        a.sw(8, 20, 12)
        # Keep the spawn near the existing extra on its side.
        bits = struct.unpack('<I', struct.pack('<f', offset if index == 0 else -offset))[0]
        a.li(8, bits)
        a.emit((17 << 26) | (4 << 21) | (8 << 16) | (1 << 11))
        a.i(49, 0, 20, 16)
        a.emit((17 << 26) | (16 << 21) | (1 << 16))
        a.i(57, 0, 20, 16)
        a.move(4, 20)
        a.call(REFRESH)
        a.move(4, 20)
        a.move(5, 0)
        a.emit((17 << 26) | (4 << 21) | (12 << 11))
        a.call(A(0x1C3E60))
        a.move(4, 20)
        a.addiu(5, 0, 1)
        a.call(A(0x1D7198))
        for function in (A(0x24C958), A(0x24CC88), A(0x24E3F8)):
            a.move(4, 19)
            a.call(function)
        a.sw(0, 19, 3184)
        a.addiu(8, 0, 2)
        a.sw(8, 19, 3188)  # Generic model loop animates while actor is unexposed.
        for field, mailbox_offset in ((84, 56), (2356, 60)):
            a.lw(8, 19, field)
            a.sw(8, 17, mailbox_offset)
        a.addiu(8, 0, 20)
        a.sw(8, 17)
        a.addiu(8, 0, index + 1)
        a.sw(8, 16, 8)
    # Prepare six-entry auxiliary tables without publishing them to the actor
    # manager. The activation stage owns manager/count/lifecycle changes.
    a.li(17, DESCS[0])
    a.lw(18, 17, 4)
    a.li(8, A(0x2FEB14))
    a.lw(21, 8)
    for table, aux_offset in enumerate(AUX_OFFSETS):
        a.li(8, aux_offset)
        a.r(0x21, 19, 18, 8)
        a.sw(19, 16, 32 + table * 4)
        a.lw(9, 21, 8 + table * 4)
        a.sw(9, 16, 40 + table * 4)
        a.move(10, 19)
        a.addiu(11, 0, 208)
        a.label(f'aux_copy{table}')
        a.lw(8, 9)
        a.sw(8, 10)
        a.addiu(9, 9, 4)
        a.addiu(10, 10, 4)
        a.addiu(11, 11, -4)
        a.branch(5, 11, 0, f'aux_copy{table}')
        a.addiu(8, 0, -1)
        for actor_index in (4, 5):
            for handle_offset in (0, 12, 24, 36):
                a.sw(8, 19, actor_index * 52 + handle_offset)
    a.addiu(8, 0, 20)
    a.sw(8, 16)
    a.jump('done')
    errors(a, (110, 150, 160, 161, 162, 170, 171, 172, 173, 174))
    finish(a)
    return a.finish()


def build(mode, source, output, offset=90.0):
    ram = read_ram(source)
    u, manager, actors, pool, registry, rows = validate(ram)
    if mode == 'load':
        assert not any(ram[CODE:HEADER + 0x40]), 'Six-actor cave occupied'
        assert sum(not u(registry + i * 56 + 48) & 1 for i in range(12)) >= 2
        previous_word = u(HOOK)
        assert previous_word >> 26 == 2 and not u(HOOK + 4)
        previous = (previous_word & 0x3FFFFFF) << 2
        assert previous == 0xE4000, 'Regenerate chain support explicitly for a different wrapper'
        descriptors = bytearray(0x80)
        for index, row in enumerate(rows):
            d = index * 64
            struct.pack_into('<I', descriptors, d + 8, 0xFFFFFFFF)
            for field, value in ((16, manager), (20, row['source_actor']), (24, row['source_model']),
                                 (40, row['character']), (44, row['slot'])):
                struct.pack_into('<I', descriptors, d + field, value)
        header = bytearray(0x40)
        struct.pack_into('<4I', header, 4, 1, 0, manager, previous)
        payload = load_code(previous, actors, rows)
        blocks = [make_block(ram, CODE, payload, 'Load both third selected character bundles'),
                  make_block(ram, DESCS[0], bytes(descriptors), 'Two pending private actor descriptors'),
                  make_block(ram, HEADER, bytes(header), 'Six-actor preparation state; exposure remains zero'),
                  make_block(ram, HOOK, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0), 'Chain loader after four-actor conversion')]
        regions = [(CODE, payload)]
    else:
        assert u(HEADER) == 5 and u(HEADER + 8) == 0 and u(HEADER + 28) == 0
        previous = u(HEADER + 16)
        assert previous == 0xE4000
        assert u(HOOK) == (2 << 26) | (CODE >> 2) and not u(HOOK + 4)
        original = load_code(previous, actors, rows)
        assert ram[CODE:CODE + len(original)] == original
        assert not any(ram[EXT_CODE:EXT_CODE + len(ext_code())])
        assert u(EXT_ENTRY) == (2 << 26) | (0xB2000 >> 2) and not u(EXT_ENTRY + 4)
        for index, row in enumerate(rows):
            d = DESCS[index]
            assert u(d) == 5 and u(d + 40) == row['character'] and not u(d + 4)
            resource = u(d + 36)
            assert u(resource + 48) == 3 and u(resource + 52) == u(d + 32)
            for file_index, file_id in enumerate(row['file_ids']):
                p = resource + file_index * 16
                assert u(p) and u(p + 4) and u(p) + u(p + 4) <= len(ram)
                assert u(p + 8) == file_id
        payload = create_code(previous, actors, pool, rows, offset)
        redirect = ext_code()
        blocks = [make_block(ram, CODE, payload, 'Create two private third-bench actors and render models'),
                  make_block(ram, EXT_CODE, redirect, 'Private animation scratch for actual new model IDs'),
                  make_block(ram, EXT_ENTRY, struct.pack('<2I', (2 << 26) | (EXT_CODE >> 2), 0), 'Extend scratch getter before creation')]
        regions = [(CODE, payload), (EXT_CODE, redirect)]
    assert len(payload) < DESCS[0] - CODE
    result = {'serial': SERIAL, 'crc': CRC, 'status': 'EXPERIMENTAL SIX-ACTOR ' + mode.upper() + '; NO EXPOSURE',
              'source': str(Path(source).resolve()), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
              'rows': rows, 'descriptors': list(DESCS), 'header': HEADER, 'previous': previous, 'blocks': blocks,
              'auxiliary_tables': {'new_A_pointer': HEADER + 32, 'new_B_pointer': HEADER + 36,
                                   'old_A_pointer': HEADER + 40, 'old_B_pointer': HEADER + 44,
                                   'entries': 6, 'stride': 52, 'manager_pointers_modified': False},
              'pool_evidence': {'free_model_nodes': u(pool + 69128), 'free_draw_nodes': u(pool + 397320),
                                'free_fx_nodes': u(pool + 397784), 'free_shader_nodes': u(pool + 439080)},
              'requirements': ['All four current CPU flags/input masks must remain zero during preparation.',
                               'Load requires headerF6080=5; create requires header20 and completed+8=2.',
                               'Newphysical IDs4/5 have dynamic model IDs4..11 stored descriptor+8.',
                               'Private actors are not scheduled, targetable, or AI-controlled until separate integration.',
                               'Effects/scheduler/AI/contact/lifecycle updates for six actors remain separate.',
                               'Restore full source state on failure; added pool nodes depend on persistent allocations.']}
    return write_manifest(output, result, regions)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode', choices=('load', 'create'))
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--offset', type=float, default=90.0)
    args = ap.parse_args()
    build(args.mode, args.source, args.out, args.offset)
