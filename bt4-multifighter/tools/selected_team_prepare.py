"""Build hidden parity slots for fresh selected teams of up to three per side.

The input capture and loaded-resource bindings are read-only. Output contains
an offline guarded MIPS manifest; no emulator connection or actor exposure.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from selected_team_capture import capture, selected_damage
from team_prototype import make_block, write_manifest
from roster_models import private_initializers
from twelve_prepare import copy_words
from battle_mode_policy import ACTOR_COUNTS, MAX_ACTORS, TEAM_CAPACITY
from native_map import FILE_ID

CODE, NATIVE_FRAME = 0x07340000, 0x0734F000
CACHE, REFRESH, EXT_CODE = 0x07350000, 0x07350200, 0x07351000
# One descriptor per created extra: every fighter beyond the two native leaders.
DESCS = tuple(0x07358000 + i * 0x80 for i in range(MAX_ACTORS - 2))
HEADER = 0x07358400
assert DESCS[-1] + 0x80 <= HEADER, 'Creation descriptors overrun the status header'
HOOK, EXT_ENTRY = 0x1C2A28, 0x2499C8
ALLOC_SIZE, ACTOR_OFF, COLLISION_OFF = 0x40000, 0x1B000, 0x30000
COLLISION_CAPACITY = 0x6000
# Native draw-node pool: list at pool+397312, free count at +8, 0xE0-byte nodes.
# A fresh two-leader match has about 384 free and every created fighter takes
# its model's 55..74 at creation, before the render stage adds its 512. Three
# extras a side (six to eight) no longer fit, so creation first inserts enough
# zeroed heap1 nodes to leave DRAW_RESERVE free, exactly as that stage does.
DRAW_LIST, DRAW_NODE, DRAW_RESERVE, DRAW_STEP = 397312, 0xE0, 64, 64
SHADER_OFF, FX_OFF, AUX_OFFSETS = 0x20000, 0x22100, (0x23000, 0x23400)
PACKET_BYTES = 0x6E10
# Native1CEDC8/1CEE10 update stats+28 (row+92), the bounded MAX gauge.
ROW_DYNAMIC_FIELDS = frozenset((64, 72, 76, 84, 92, 160))  # HP, pending, ki, stock, MAX, activation


def begin(a, previous):
    a.addiu(29, 29, -0x60)
    for index, reg in enumerate(range(16, 24)): a.i(63, reg, 29, index * 8)
    a.i(63, 31, 29, 0x40); a.call(previous)
    a.i(63, 2, 29, 0x48); a.i(63, 3, 29, 0x50)
    a.li(16, HEADER)


def finish(a):
    a.label('done')
    a.i(55, 2, 29, 0x48); a.i(55, 3, 29, 0x50)
    for index, reg in enumerate(range(16, 24)): a.i(55, reg, 29, index * 8)
    a.i(55, 31, 29, 0x40); a.addiu(29, 29, 0x60); a.jr()


def error_labels(a, errors):
    for error in errors:
        a.label(f'error{error}'); a.addiu(8, 0, error); a.sw(8, 16)
        a.sw(0, 16, 20); a.jump('done')


def world_guards(a, rows, actors, manager, pool):
    a.lw(8, 28, -22364); a.li(9, manager); a.branch(5, 8, 9, 'error110')
    a.lw(8, 8, 4); a.li(9, actors[0]); a.branch(5, 8, 9, 'error110')
    a.lw(8, 28, -22060); a.li(9, pool); a.branch(5, 8, 9, 'error110')
    for index, actor in enumerate(actors):
        a.li(8, actor)
        for offset, value in ((0, index), (12, index), (0x994, 0),
                               (0x948, 11), (0x1278, 0), (0x127C, 0)):
            a.lw(9, 8, offset); a.li(10, value); a.branch(5, 9, 10, 'error110')
    for row in rows:
        a.li(8, row['source_model'])
        for field, value in ((20, row['source_resource']), (12, row['source_character'])):
            a.lw(9, 8, field); a.li(10, value); a.branch(5, 9, 10, 'error110')
        a.li(8, row['native_row_address'])
        for offset, value in enumerate(struct.unpack('<41I', bytes.fromhex(row['native_row_hex']))):
            if offset * 4 in ROW_DYNAMIC_FIELDS: continue
            a.lw(9, 8, offset * 4); a.li(10, value); a.branch(5, 9, 10, 'error110')
        a.li(8, row['resource'])
        for field, value in ((48, row['resource_flags']), (52, row['resource_handle'])):
            a.lw(9, 8, field); a.li(10, value); a.branch(5, 9, 10, 'error110')
        for index, value in enumerate(row['file_ids']):
            a.lw(9, 8, index * 16); a.branch(4, 9, 0, 'error110')
            a.lw(9, 8, index * 16 + 8); a.li(10, value); a.branch(5, 9, 10, 'error110')


def ext_code(existing_model_ids, original):
    a = Assembler(EXT_CODE)
    a.li(8, HEADER); a.lw(9, 8, 12); a.lw(10, 28, -22364)
    a.branch(5, 9, 10, 'old')
    a.lw(9, 8, 56); a.lw(10, 10, 4)
    a.branch(5, 9, 10, 'old')
    a.i(11, 8, 4, 12); a.branch(4, 8, 0, 'old')
    for model_id in existing_model_ids:
        a.addiu(8, 0, model_id); a.branch(4, 4, 8, 'old')
    for index, desc in enumerate(DESCS):
        a.li(8, desc); a.lw(9, 8, 8)
        a.branch(5, 4, 9, f'next{index}')
        a.lw(2, 8, 4); a.branch(5, 2, 0, 'return')
        a.label(f'next{index}')
    a.li(8, HEADER); a.lw(8, 8, 20); a.branch(4, 8, 0, 'old')
    a.lw(2, 8, 4); a.branch(4, 2, 0, 'old'); a.sw(4, 8, 8)
    a.label('return'); a.jr()
    a.label('old')
    for word in struct.unpack('<2I', original): a.emit(word)
    a.jump(EXT_ENTRY + 8)
    return a.finish()


def draw_growth(free, rows):
    """Nodes creation inserts so DRAW_RESERVE stay free after every model."""
    short = sum(r['draw_nodes'] for r in rows) + DRAW_RESERVE - free
    return 0 if short <= 0 else -(-short // DRAW_STEP) * DRAW_STEP


def create_code(previous, rows, actors, manager, pool, existing_model_ids, grow=0):
    a = Assembler(CODE); begin(a, previous)
    a.lw(8, 16); a.branch(5, 8, 0, 'done')
    world_guards(a, rows, actors, manager, pool)
    if grow:
        # Same insertion as capacity_stage.grow_code: zeroed heap1 nodes pushed
        # through the native list insert, before any model claims its nodes.
        a.li(4, grow * DRAW_NODE); a.addiu(5, 0, 64); a.move(6, 0); a.addiu(7, 0, 1)
        a.call(A(0x2554D8)); a.branch(4, 2, 0, 'error152'); a.move(18, 2)
        a.li(8, 0x02000000); a.r(0x2B, 9, 18, 8); a.branch(5, 9, 0, 'error152')
        a.li(8, 0x06000000 - grow * DRAW_NODE); a.r(0x2B, 9, 8, 18); a.branch(5, 9, 0, 'error152')
        a.move(4, 18); a.move(5, 0); a.li(6, grow * DRAW_NODE); a.call(A(0x2A9ACC))
        a.addiu(19, 0, grow)
        a.label('draw_grow')
        a.li(4, pool + DRAW_LIST); a.move(5, 18); a.call(A(0x255CF0))
        a.addiu(18, 18, DRAW_NODE); a.addiu(19, 19, -1); a.branch(5, 19, 0, 'draw_grow')
    for address, required in ((pool + 397320, sum(r['draw_nodes'] for r in rows)), (pool + 69128, len(rows))):
        a.li(8, address); a.lw(8, 8); a.li(9, required); a.r(0x2B, 8, 8, 9)
        a.branch(5, 8, 0, 'error150')
    a.addiu(8, 0, 10); a.sw(8, 16)
    a.addiu(4, 0, 144); a.call(A(0x113660)); a.r(0, 2, 0, 2, 2)
    a.li(8, PACKET_BYTES); a.branch(5, 2, 8, 'error151')
    for index, (row, desc) in enumerate(zip(rows, DESCS)):
        tag = f'actor{index}_'
        a.li(17, desc)
        a.li(4, ALLOC_SIZE); a.addiu(5, 0, 64); a.move(6, 0); a.addiu(7, 0, 1)
        a.call(A(0x2554D8)); a.branch(4, 2, 0, 'error160')
        a.move(18, 2); a.sw(18, 17, 4)
        a.move(4, 18); a.move(5, 0); a.li(6, ALLOC_SIZE); a.call(A(0x2A9ACC))
        # The native shader factory owns descriptor + two independent buffers.
        for reg, size, align, field in ((19, 192, 32, 84), (20, PACKET_BYTES, 64, 88),
                                        (21, PACKET_BYTES, 64, 92)):
            a.li(4, size); a.addiu(5, 0, align); a.move(6, 0); a.addiu(7, 0, 1)
            a.call(A(0x2554D8)); a.branch(4, 2, 0, 'error161')
            a.move(reg, 2); a.sw(reg, 17, field)
            a.move(4, reg); a.move(5, 0); a.li(6, size); a.call(A(0x2A9ACC))
        a.sw(20, 19); a.sw(21, 19, 4)
        a.li(8, SHADER_OFF); a.r(0x21, 8, 18, 8); a.sw(19, 8, 8240)
        for node_offset, list_offset, field in ((SHADER_OFF, 439072, 48), (FX_OFF, 397776, 52)):
            a.li(8, node_offset); a.r(0x21, 5, 18, 8); a.sw(5, 17, field)
            a.li(4, pool + list_offset); a.call(A(0x255CF0))
        # Model initialization rewrites shared collision bone pointers. Restore
        # the source immediately, then initialize the new model's private copy.
        a.li(20, row['collision']); a.li(8, COLLISION_OFF); a.r(0x21, 21, 18, 8)
        if not row['collision_size']:a.move(21,0)
        a.sw(21, 17, 56)
        copy_words(a, tag + 'backup', 20, 21, row['collision_size'])
        a.sw(17, 16, 20)
        a.move(4, 0); a.li(5, row['resource']); a.addiu(6, 0, 1); a.call(A(0x249AB8))
        a.move(22, 2); a.sw(0, 16, 20)
        copy_words(a, tag + 'restore', 21, 20, row['collision_size'])
        a.i(11, 8, 22, 12); a.branch(4, 8, 0, 'error170')
        for old_id in existing_model_ids:
            a.addiu(8, 0, old_id); a.branch(4, 22, 8, 'error170')
        for prior in DESCS[:index]:
            a.li(8, prior); a.lw(8, 8, 8); a.branch(4, 22, 8, 'error170')
        a.sw(22, 17, 8); a.move(4, 22); a.call(A(0x2499B0))
        a.branch(4, 2, 0, 'error171'); a.move(19, 2); a.sw(19, 17, 12)
        a.lw(8, 19, 16); a.branch(5, 8, 22, 'error171')
        # Direct initialization/pose helpers work while this outer draw gate is
        # disabled. Hide now so later metadata/pool failures cannot expose it.
        a.sw(0, 19, 8)
        for field, expected in ((5728, None), (12, row['character']), (20, row['resource'])):
            a.lw(8, 19, field)
            if expected is None: a.move(9, 18)
            else: a.li(9, expected)
            a.branch(5, 8, 9, 'error172')
        a.sw(21, 19, 84); a.move(4, 19); a.call(A(0x24DB28))
        for model_field, descriptor_field in ((5736, 48), (5732, 52)):
            a.lw(8, 19, model_field); a.lw(9, 17, descriptor_field)
            a.branch(5, 8, 9, 'error173')
        a.li(8, ACTOR_OFF); a.r(0x21, 20, 18, 8); a.sw(20, 17, 28)
        a.li(21, row['source_actor']); a.addiu(22, 21, 0x1600)
        a.move(10, 21); a.move(11, 20)
        a.label(tag + 'clone')
        a.lw(8, 10); a.r(0x2B, 9, 8, 21); a.branch(5, 9, 0, tag + 'store')
        a.r(0x2B, 9, 8, 22); a.branch(4, 9, 0, tag + 'store')
        a.r(0x23, 8, 8, 21); a.r(0x21, 8, 8, 20)
        a.label(tag + 'store'); a.sw(8, 11)
        a.addiu(10, 10, 4); a.addiu(11, 11, 4); a.branch(5, 10, 22, tag + 'clone')
        for field, value in ((0, row['physical_id']), (4, row['side']), (8, row['side']),
                              (0x994, row['slot']), (0x12E0, int(selected_damage(row))), (0x1278, 0), (0x127C, 0),
                              (4912, 0), (4916, 0), (4920, 0), (5608, 0), (5612, 0), (5616, 0)):
            a.li(8, value); a.sw(8, 20, field)
        a.lw(8, 17, 8); a.sw(8, 20, 12)
        # Begin in native idle, with no queued or previous source move.
        for field, value in ((2376, 11), (2380, -1), (2384, 11), (2388, -1), (2392, -1), (2396, -1), (2400, -1), (2404, 0), (2408, 0)):
            a.li(8, value); a.sw(8, 20, field)
        bits = struct.unpack('<I', struct.pack('<f', row['x_offset']))[0]
        a.li(8, bits); a.emit((17 << 26) | (4 << 21) | (8 << 16) | (1 << 11))
        a.i(49, 0, 20, 16); a.emit((17 << 26) | (16 << 21) | (1 << 16)); a.i(57, 0, 20, 16)
        a.move(4, 20); a.call(REFRESH)
        a.move(4, 20); a.move(5, 0); a.emit((17 << 26) | (4 << 21) | (12 << 11)); a.call(A(0x1C3E60))
        a.move(4, 20); a.addiu(5, 0, 1); a.call(A(0x1D7198))
        for function in (A(0x24C958), A(0x24CC88), A(0x24E3F8)): a.move(4, 19); a.call(function)
        a.sw(0, 19, 3184); a.addiu(8, 0, 2); a.sw(8, 19, 3188)
        # Native render/update loops require model+8 (the249AB8 enabled flag).
        # Keep new models hidden until main packet buffers have been expanded;
        # Activation will independently verify graphics and scheduler capacity.
        a.sw(0, 19, 8)
        a.lw(8, 19, 2356); a.sw(8, 17, 60)
        a.addiu(8, 0, 20); a.sw(8, 17)
        a.addiu(8, 0, index + 1); a.sw(8, 16, 8)
    # Aux rows remain unpublished until the independent activation stage.
    a.li(17, DESCS[0]); a.lw(18, 17, 4); a.li(21, manager)
    for table, aux_offset in enumerate(AUX_OFFSETS):
        a.li(8, aux_offset); a.r(0x21, 19, 18, 8); a.sw(19, 16, 32 + table * 4)
        a.lw(22, 21, 8 + table * 4); a.sw(22, 16, 40 + table * 4)
        copy_words(a, f'aux{table}', 22, 19, 2 * 52)
        a.addiu(8, 0, -1)
        for actor_index in range(2, 2 + len(rows)):
            for handle_offset in (0, 12, 24, 36): a.sw(8, 19, actor_index * 52 + handle_offset)
    a.addiu(8, 0, 20); a.sw(8, 16); a.jump('done')
    error_labels(a, (110, 150, 151, 152, 160, 161, 170, 171, 172, 173)); finish(a)
    return a.finish()


def resource_info(ram, resource, handle, character, costume, pool, *, damaged=False, mesh_only=False):
    """Audit the actual intact/damaged PAK and native geometry chain.

    Reloads use the same parser as fresh selection. Taking the damage flag
    explicitly avoids copying a full EE image just to spoof the intact file ID;
    the live file identity and every payload bound are still checked here.
    """
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    h = lambda p: struct.unpack_from('<H', ram, p)[0]
    import bt4_resources
    bt4_resources.request_files(character,costume,damaged)
    assert type(damaged) is bool, 'Damage state must be Boolean'
    assert type(mesh_only) is bool, 'Mesh-only mode must be Boolean'
    assert 0 <= handle < 14, 'Resource handle outside native registry'
    registry = pool + 439276
    expected = registry + (672 + handle * 56 if handle < 2 else (handle - 2) * 56)
    assert resource == expected, 'Resource binding does not match its native registry handle'
    assert u(resource + 52) == handle
    flags = 1 if handle < 2 else 3
    assert u(resource + 48) == flags, 'Resource loading has not completed'
    files = bt4_resources.request_files(character,costume,damaged)
    if mesh_only:files[1:]=[0xFFFFFFFF,0xFFFFFFFF]
    payloads = []
    for index, file_id in enumerate(files):
        p, size, actual = (u(resource + index * 16 + n) for n in (0, 4, 8))
        assert actual == file_id, 'Loaded resource does not match selected character/costume'
        if mesh_only and index:
            assert p==0 and size==0 and u(resource+index*16+12)==0, 'Absent auxiliary resource section must be empty'
            continue
        assert 0x100000 <= p < len(ram) and 0 < size <= len(ram) - p
        payloads.append((p, size))
    main, size = payloads[0]
    def entry(index):
        assert (index + 2) * 4 <= size
        start, end = u(main + index * 4), u(main + (index + 1) * 4)
        assert 0 < start < end <= size, f'Missing or invalid PAK entry{index}'
        pointer, limit = main + (start & ~3), main + (end & ~3)
        assert pointer >= main + (index + 2) * 4 and pointer < limit
        return pointer, limit
    assert size>=16 and 2<=u(main)<=4096 and (u(main)+2)*4<=size, 'Invalid mesh package header'
    if u(main+8)==u(main+12):
        offset=u(main+8)&~3
        assert (u(main)+2)*4<=offset<=size, 'Absent collision entry outside package'
        collision=collision_size=0
    else:
        collision, collision_end = entry(2)
        collision_size = 16
        while collision_size + 464 <= min(COLLISION_CAPACITY, collision_end - collision):
            terminal = u(collision + collision_size) & 1
            collision_size += 464
            if terminal: break
        else: raise AssertionError('Collision chain exceeds its PAK entry or private capacity')
    geometry, geometry_end = entry(3)
    assert geometry_end - geometry >= 112
    part = geometry + u(geometry + 108)
    nodes = 0
    seen = set()
    while True:
        assert geometry + 112 <= part <= geometry_end - 12 and part not in seen, 'Invalid geometry part chain'
        seen.add(part); nodes += 1
        assert nodes <= 512, 'Geometry requires more than the native draw-node pool'
        if h(part + 6): break
        step = u(part)
        assert step >= 12 and step % 4 == 0, 'Geometry part does not advance'
        part += step
    return dict(resource=resource, resource_handle=handle, resource_flags=flags,
                file_ids=files, collision=collision, collision_size=collision_size,
                geometry=geometry, geometry_initialized=bool(u(geometry + 12) & 0x80000000),
                texture_group=u(geometry + 40), draw_nodes=nodes)


def configuration(ram, captured, bindings):
    current = capture(ram,minimum_members=captured.get('minimum_members',1))
    assert current['intended_fighter_count'] in ACTOR_COUNTS, f'Fresh creation requires two native leaders and up to {TEAM_CAPACITY} selected members per side'
    # Native idle updates regenerate reserve gauges even with CPU/input held.
    # Preserve the latest row, while requiring every non-runtime word to match.
    for key in ('schema', 'serial', 'native_manager', 'native_actor_array',
                'members_per_side', 'intended_fighter_count'):
        assert captured[key] == current[key], f'Selection capture no longer matches: {key}'
    assert len(captured['roster']) == len(current['roster'])
    assert captured.get('team_counts', [captured['members_per_side']]*2) == current['team_counts'], 'Selected team sizes changed'
    assert captured.get('participation_mask', (1 << len(captured['roster']))-1) == current['participation_mask'], 'Selected participation changed'
    for old, new in zip(captured['roster'], current['roster']):
        assert old.get('participating', True) == new['participating'], 'Selected member participation changed'
        for key in ('physical_id', 'side', 'slot', 'character', 'costume', 'source_leader',
                    'source_model', 'source_resource', 'native_row_address'):
            assert old[key] == new[key], f'Selected member changed after capture: {key}'
        old_words = struct.unpack('<41I', bytes.fromhex(old['native_row_hex']))
        new_words = struct.unpack('<41I', bytes.fromhex(new['native_row_hex']))
        for index, (before, after) in enumerate(zip(old_words, new_words)):
            if index * 4 not in ROW_DYNAMIC_FIELDS:
                assert before == after, f'Selected member changed after capture: row+{index * 4}'
        assert new_words[19] <= new_words[20] and new_words[21] <= new_words[22], 'Invalid native resource gauges'
        assert new_words[23] <= 30000, 'Invalid native MAX gauge'
        assert new_words[40] <= 1, 'Invalid selected-row activation marker'
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    assert u(A(0x2FF084)) == 0x02000000 and u(A(0x2FF08C)) == 0x06000000, 'Initialize verified extended heap1 first'
    manager, pool = current['native_manager'], u(A(0x2FEC44))
    assert 0x100000 <= pool <= len(ram) - 440200
    actors = [leader['actor'] for leader in current['leaders']]
    assert all(u(p + 0x948) == 11 for p in actors), 'Pause a fresh idle match before preparation'
    assert all(u(p + offset) == 0 for p in actors for offset in (0x1278, 0x127C)), 'Freeze both native CPU/input masks first'
    existing_ids = [i for i in range(12) if u(A(0x31C640) + 4 * i)]
    rows = current['roster'][2:]
    assert set(existing_ids) >= {0, 1} and u(pool + 69128) >= len(rows), 'Insufficient native model slots'
    by_id = {int(b['physical_id']): b for b in bindings['bindings']}
    assert len(by_id) == len(bindings['bindings']) == len(rows)
    assert set(by_id) == {r['physical_id'] for r in rows}, 'One resource binding per selected extra is required'
    normalized = []
    for row in rows:
        binding = by_id[row['physical_id']]
        info = resource_info(ram, int(binding['resource']), int(binding['resource_handle']),
                             row['character'], row['costume'], pool, damaged=selected_damage(row))
        leader = current['leaders'][row['side']]
        offset = float(binding.get('x_offset', (1 if row['side'] == 0 else -1) * row.get('formation_slot',row['slot']) * 90.0))
        assert math.isfinite(offset) and abs(offset) <= 1000
        normalized.append(dict(row, **info, source_actor=row['source_leader'],
                               source_character=leader['character'], x_offset=offset))
    grow = draw_growth(u(pool + DRAW_LIST + 8), normalized)
    assert u(pool + DRAW_LIST + 8) + grow >= sum(r['draw_nodes'] for r in normalized), 'Grow native draw-node pool before creation'
    new_geometry = {r['geometry'] for r in normalized if not r['geometry_initialized']}
    free_textures = 15 - (u(pool + 439156) & 0x7FFF).bit_count()
    assert free_textures >= len(new_geometry), 'Insufficient free native texture groups'
    return current, manager, pool, actors, existing_ids, normalized


def build_memory(ram, captured, bindings, source='<offline-memory-fixture>', output=None):
    current, manager, pool, actors, existing_ids, rows = configuration(ram, captured, bindings)
    grow = draw_growth(struct.unpack_from('<I', ram, pool + DRAW_LIST + 8)[0], rows)
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    elf, _, native = elf_reader(elf_path(ROOT))
    for entry, size in ((EXT_ENTRY, 0x30), (A(0x249AB8), 0xA0), (A(0x2554D8), 0x80),
                         (A(0x255CF0), 0x30), (A(0x113660), 0xA0), (A(0x24DB28), 0x70),
                         (A(0x1C0058), 0xD0), (A(0x1C0538), 0x570), (A(0x1C3E60), 0x1B0)):
        assert ram[entry:entry + size] == native(entry, size), f'Native creation helper changed: {entry:X}'
    assert not any(ram[CODE:0x07360000]), 'Fresh selected creation arena occupied'
    regions = []
    if ram[HOOK:HOOK + 8] == native(HOOK, 8):
        original = native(HOOK, 8)
        assert struct.unpack('<2I', original) == (0x27BDFFF0, 0xFFB00000)
        trampoline = original + struct.pack('<2I', (2 << 26) | ((HOOK + 8) >> 2), 0)
        previous = NATIVE_FRAME
        regions.append((NATIVE_FRAME, trampoline, 'Replay displaced native frame prologue'))
    else:
        assert u(HOOK) >> 26 == 2 and u(HOOK + 4) == 0
        previous = (u(HOOK) & 0x3FFFFFF) << 2
        assert 0x07360000 <= previous < 0x07368000, 'Unreviewed fresh bootstrap/loader frame chain'
    cache, old_refresh = private_initializers(native)
    refresh = bytearray(old_refresh)
    struct.pack_into('<I', refresh, 0x24, (3 << 26) | (CACHE >> 2))
    assert len(rows) <= len(DESCS), 'More selected extras than creation descriptors'
    descriptors = bytearray(len(DESCS) * 0x80)
    for index, row in enumerate(rows):
        fields = {8: 0xFFFFFFFF, 16: manager, 20: row['source_actor'], 24: row['source_model'],
                  32: row['resource_handle'], 36: row['resource'], 40: row['character'], 44: row['slot'],
                  64: row['side'], 68: row['side'], 72: row['collision'],
                  76: row['collision_size'], 80: row['draw_nodes'], 96: row['costume']}
        for field, value in fields.items(): struct.pack_into('<I', descriptors, index * 0x80 + field, value)
    for index in range(len(rows), len(DESCS)): struct.pack_into('<I', descriptors, index * 0x80 + 8, 0xFFFFFFFF)
    header = bytearray(0x100)
    for offset, value in ((4, 1), (12, manager), (16, previous), (24, pool),
                          (48, sum(r['draw_nodes'] for r in rows)), (52, 2 + len(rows)), (56, actors[0])):
        struct.pack_into('<I', header, offset, value)
    generated = create_code(previous, rows, actors, manager, pool, existing_ids, grow)
    assert len(generated) < NATIVE_FRAME - CODE
    regions += [(CODE, generated, 'Create independently allocated selected extra actors; keep models hidden'),
                (CACHE, cache, 'Native model cache initializer preserving assigned model ID'),
                (REFRESH, bytes(refresh), 'Native selected-character refresh with private cache call'),
                (EXT_CODE, ext_code(existing_ids, native(EXT_ENTRY, 8)), 'Route new actual model IDs to independent scratch')]
    payloads = regions + [(DESCS[0], bytes(descriptors), 'Captured selected members and resource identities'),
                          (HEADER, bytes(header), 'Fresh creation status; count/exposure remain unpublished'),
                          (HOOK, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0), 'Chain hidden selected actor creation'),
                          (EXT_ENTRY, struct.pack('<2I', (2 << 26) | (EXT_CODE >> 2), 0), 'Install scoped extra model scratch routing')]
    # configuration() captured this same, unmodified image and already hashed it.
    manifest = dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                    ram_sha256=current['ram_sha256'], elf_sha256=hashlib.sha256(elf).hexdigest(),
                    status='FRESH SELECTED HIDDEN ACTORS ONLY; NO AI/EXPOSURE',
                    blocks=[make_block(ram, p, data, purpose) for p, data, purpose in payloads],
                    rows=rows, descriptors=list(DESCS[:len(rows)]), header=HEADER, previous=previous,
                    existing_model_ids=existing_ids, leaders=current['leaders'],
                    required_draw_nodes=sum(r['draw_nodes'] for r in rows), draw_growth=grow,
                    requirements=[f'Fresh native2-actor match with selected teams of up to {TEAM_CAPACITY} per side.',
                                  'Both leaders must be idle with CPU flags/input masks frozen; extended heap1 must already be initialized.',
                                  'All selected character/costume/clothes-state bundles must be loaded into verified native resource records.',
                                  'Creation status20/completed count is required before private AI initialization.',
                                  'New model+8 remains0. Root activation must install getters, targets, collision, effects, KO/camera guards and graphics capacity before exposing.',
                                  'Restore source checkpoint on any failure; guest allocations are retained and do not support ordinary menu teardown.'])
    if output is not None:
        return write_manifest(output, manifest, [(p, data) for p, data, _ in regions])
    return manifest


def build(source, capture_path, bindings_path, output=None):
    return build_memory(read_ram(source), json.loads(Path(capture_path).read_text()),
                        json.loads(Path(bindings_path).read_text()), source, output)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--capture', required=True, type=Path)
    p.add_argument('--bindings', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    x = p.parse_args(); build(x.source, x.capture, x.bindings, x.out)

