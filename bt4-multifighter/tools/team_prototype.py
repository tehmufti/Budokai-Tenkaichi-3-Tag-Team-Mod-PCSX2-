"""Offline four-actor experiment builder; never connects to the emulator.

Stage 1 creates independent clones of both current leaders. Stage 2 exposes
their physical slots only after matching AI/effects/collision hooks are ready.
The original two-actor allocation and raw manager count remain unchanged.
"""
from __future__ import annotations
from native_map import A, CRC, GPO, SERIAL, elf_path

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

from prototype import (Assembler, ROOT, ACTOR_SIZE, MODEL_SIZE, EXT_SIZE,
                       elf_reader, build_stats_guard, build_audio_guards,
                       build_replay_guards)

CODE = 0xB0000
EXT_CODE = 0xB2000
DESCRIPTORS = (0xB3000, 0xB3040)
HEADER = 0xB3080
EXPOSURE = HEADER + 8
FRAME_ENTRY = A(0x1C2A28)
EXT_ENTRY = A(0x2499C8)
COUNT_ENTRY = A(0x1DC168)
COUNT_CODE = 0xB6000
AI_CONTROL = 0xBD000
ACTOR_GLOBAL = A(0x2FEB14)
MODEL_TABLE = A(0x31C640)
ALLOC_SIZE = 0x20000
ACTOR_OFFSET = 0x1B000
COLLISION_OFFSET = 0x1C800
AUX_OFFSETS = (0x1F000, 0x1F100)


def word(ram, address):
    return struct.unpack_from('<I', ram, address)[0]


def make_block(ram, address, data, purpose):
    expected = ram[address:address + len(data)]
    assert len(expected) == len(data), 'Block outside EE RAM'
    return {'address': address, 'expected_hex': expected.hex(),
            'data_hex': data.hex(), 'purpose': purpose}


def metadata(ram, elf, status, blocks):
    return {'status': status, 'serial': SERIAL, 'crc': CRC,
            'ram_sha256': hashlib.sha256(ram).hexdigest(),
            'elf_sha256': hashlib.sha256(elf).hexdigest(),
            'descriptors': list(DESCRIPTORS), 'header': HEADER,
            'header_fields': {'0': 'pending model-creation descriptor pointer',
                              '4': 'completed extra actors (0..2)',
                              '8': 'physical exposure flag',
                              '12': 'original actor manager',
                              '16': 'original manager auxiliary array A',
                              '20': 'original manager auxiliary array B',
                              '24': 'creation status: 0 pending, 1 working, 5 ready, 250 detached, >=100 error'},
            'blocks': blocks}


def write_manifest(output, manifest, code_regions=()):
    output = Path(output)
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    if code_regions:
        from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
        md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
        lines = []
        for address, data in code_regions:
            decoded = list(md.disasm(data, address))
            assert len(decoded) * 4 == len(data), 'Unrecognized MIPS instruction'
            lines.extend(f'{i.address:08X}: {i.mnemonic} {i.op_str}' for i in decoded)
        output.with_suffix('.asm.txt').write_text('\n'.join(lines) + '\n')
    print(f'{output}: {len(manifest["blocks"])} guarded blocks')
    return manifest


def source_info(ram, side):
    manager = word(ram, ACTOR_GLOBAL)
    assert 0x100000 <= manager < 0x1FFFF00 and word(ram, manager) == 2
    actor = word(ram, manager + 4) + side * ACTOR_SIZE
    assert word(ram, actor) == side and word(ram, actor + 12) == side
    model = word(ram, MODEL_TABLE + side * 4)
    assert 0x100000 <= model < 0x2000000 - MODEL_SIZE
    ext = word(ram, model + 5728)
    assert 0x100000 <= ext < 0x2000000 - EXT_SIZE
    animation = word(ram, actor + 2420)
    assert animation < 414 and struct.unpack_from('<H', ram, model + 2888)[0] == animation
    duration = struct.unpack_from('<f', ram, model + 2884)[0]
    frames = struct.unpack_from('<2f', ram, model + 3192)
    assert math.isfinite(duration) and duration > 0
    assert all(math.isfinite(f) and 0 <= f <= duration + 4 for f in frames)
    collision = word(ram, model + 84)
    assert 0x100000 <= collision < 0x2000000 - 0x2800
    size = 16
    while size + 464 <= AUX_OFFSETS[0] - COLLISION_OFFSET:
        terminal = word(ram, collision + size) & 1
        size += 464
        if terminal:
            break
    else:
        raise ValueError(f'Leader {side} collision descriptor exceeds private region')
    return {'side': side, 'manager': manager, 'actor': actor, 'model': model,
            'ext': ext, 'collision': collision, 'collision_size': size,
            'animation': animation, 'duration': duration, 'frames': frames}


def ext_stub(original):
    """Prefer completed descriptors before routing an in-progress creation."""
    a = Assembler(EXT_CODE)
    a.i(11, 8, 4, 2)
    a.branch(5, 8, 0, 'original')
    for index, descriptor in enumerate(DESCRIPTORS):
        a.li(8, descriptor)
        a.lw(9, 8, 8)
        a.branch(5, 4, 9, f'next_{index}')
        a.lw(2, 8, 4)
        a.branch(5, 2, 0, 'return')
        a.label(f'next_{index}')
    # Safely initialize any engine model slot before the caller rejects IDs
    # outside {2,3}; returning null here would fault inside model creation.
    a.i(11, 8, 4, 12)
    a.branch(4, 8, 0, 'original')
    a.li(8, HEADER)
    a.lw(8, 8)
    a.branch(4, 8, 0, 'original')
    a.lw(2, 8, 4)
    a.branch(4, 2, 0, 'original')
    a.sw(4, 8, 8)  # Capture the assigned ID before allocator returns to caller.
    a.label('return')
    a.jr()
    a.label('original')
    for instruction in struct.unpack('<2I', original):
        a.emit(instruction)
    a.jump(EXT_ENTRY + 8)
    return a.finish()


def build_creation(ram_path, elf_path, output, distance=90.0):
    ram = Path(ram_path).read_bytes()
    assert len(ram) == 0x2000000
    elf, segments, readelf = elf_reader(Path(elf_path))
    assert not any(ram[CODE:HEADER + 32]), 'Team creation cave is occupied'
    assert not any(va < HEADER + 32 and CODE < va + memsz for va, _, _, memsz in segments)
    for entry in (FRAME_ENTRY, EXT_ENTRY):
        assert ram[entry:entry + 8] == readelf(entry, 8)
        assert struct.unpack('<2I', readelf(entry, 8)) == (0x27BDFFF0, 0xFFB00000)
    assert word(ram, A(0x31BE04)) == 0, 'Use a live match, not replay playback'
    sources = [source_info(ram, side) for side in (0, 1)]
    assert not word(ram, MODEL_TABLE + 8) and not word(ram, MODEL_TABLE + 12)
    assert math.isfinite(distance)
    a = Assembler(CODE)
    a.addiu(29, 29, -0x80)
    for n in range(8):
        a.i(63, 16 + n, 29, n * 8)
    a.i(63, 31, 29, 0x40)
    a.li(16, HEADER)
    a.lw(8, 16, 24)
    a.branch(5, 8, 0, 'finish')
    a.addiu(8, 0, 1)
    a.sw(8, 16, 24)
    a.li(8, A(0x31BE04))
    a.lw(9, 8)
    a.branch(5, 9, 0, 'global_150')
    a.li(8, ACTOR_GLOBAL)
    a.lw(17, 8)
    a.branch(4, 17, 0, 'global_110')
    a.lw(9, 17)
    a.addiu(8, 0, 2)
    a.branch(5, 8, 9, 'global_110')
    a.sw(17, 16, 12)
    for side, source in enumerate(sources):
        tag = f's{side}_'
        descriptor = DESCRIPTORS[side]
        size = source['collision_size']
        a.li(16, descriptor)
        a.addiu(8, 0, 1)
        a.sw(8, 16)
        a.lw(18, 17, 4)
        if side:
            a.addiu(18, 18, ACTOR_SIZE)
        a.lw(8, 18, 12)
        a.addiu(9, 0, side)
        a.branch(5, 8, 9, tag + 'error_112')
        a.li(8, MODEL_TABLE)
        a.lw(19, 8, side * 4)
        a.lw(8, 18, 2420)
        a.i(11, 9, 8, 414)
        a.branch(4, 9, 0, tag + 'error_140')
        a.i(37, 9, 19, 2888)
        a.branch(5, 8, 9, tag + 'error_140')
        a.sw(8, 16, 36)
        a.sw(17, 16, 16)
        a.sw(18, 16, 20)
        a.sw(19, 16, 24)
        a.lw(8, 19, 5728)
        a.sw(8, 16, 40)
        a.li(4, ALLOC_SIZE)
        a.addiu(5, 0, 32)
        a.move(6, 0)
        a.addiu(7, 0, 2)
        a.call(A(0x2554D8))
        a.branch(4, 2, 0, tag + 'error_120')
        a.move(20, 2)
        a.sw(20, 16, 4)
        a.move(4, 20)
        a.move(5, 0)
        a.li(6, ALLOC_SIZE)
        a.call(A(0x2A9ACC))
        a.addiu(8, 0, 2)
        a.sw(8, 16)
        a.lw(8, 19, 84)
        a.sw(8, 16, 48)
        a.li(9, COLLISION_OFFSET)
        a.r(0x21, 9, 20, 9)
        a.sw(9, 16, 44)
        a.addiu(10, 0, size)
        a.sw(10, 16, 52)
        a.label(tag + 'backup_collision')
        a.lw(11, 8)
        a.sw(11, 9)
        a.addiu(8, 8, 4)
        a.addiu(9, 9, 4)
        a.addiu(10, 10, -4)
        a.branch(5, 10, 0, tag + 'backup_collision')
        a.li(8, HEADER)
        a.sw(16, 8)  # Publish only this in-progress allocation to ext getter.
        a.move(4, 0)
        a.lw(5, 19, 20)
        a.addiu(6, 0, 1)
        a.call(A(0x249AB8))
        a.move(21, 2)
        a.li(8, HEADER)
        a.sw(0, 8)
        a.sw(21, 16, 8)
        a.lw(8, 16, 44)
        a.lw(9, 16, 48)
        a.addiu(10, 0, size)
        a.label(tag + 'restore_collision')
        a.lw(11, 8)
        a.sw(11, 9)
        a.addiu(8, 8, 4)
        a.addiu(9, 9, 4)
        a.addiu(10, 10, -4)
        a.branch(5, 10, 0, tag + 'restore_collision')
        a.i(11, 8, 21, 4)
        a.branch(4, 8, 0, tag + 'error_130')
        a.i(11, 8, 21, 2)
        a.branch(5, 8, 0, tag + 'error_130')
        if side:
            a.li(8, DESCRIPTORS[0])
            a.lw(8, 8, 8)
            a.branch(4, 21, 8, tag + 'error_130')
        a.move(4, 21)
        a.call(A(0x2499B0))
        a.move(22, 2)
        a.sw(22, 16, 12)
        a.lw(8, 16, 44)
        a.sw(8, 22, 84)
        a.move(4, 22)
        a.call(A(0x24DB28))
        a.addiu(8, 0, 3)
        a.sw(8, 16)
        a.li(8, ACTOR_OFFSET)
        a.r(0x21, 23, 20, 8)
        a.sw(23, 16, 28)
        a.move(8, 18)
        a.move(9, 23)
        a.addiu(10, 18, ACTOR_SIZE)
        a.lw(14, 16, 40)
        a.label(tag + 'copy_word')
        for branch_tag, source_reg, dest_reg, extent in (
                ('actor', 18, 23, ACTOR_SIZE),
                ('model', 19, 22, MODEL_SIZE), ('ext', 14, 20, EXT_SIZE)):
            if branch_tag == 'actor':
                a.lw(11, 8)
            a.r(0x23, 12, 11, source_reg)
            if extent <= 32767:
                a.i(11, 13, 12, extent)
            else:
                a.li(15, extent)
                a.r(0x2B, 13, 12, 15)
            a.branch(4, 13, 0, tag + 'not_' + branch_tag)
            a.r(0x21, 11, 12, dest_reg)
            a.jump(tag + 'store_word')
            a.label(tag + 'not_' + branch_tag)
        a.label(tag + 'store_word')
        a.sw(11, 9)
        a.addiu(8, 8, 4)
        a.addiu(9, 9, 4)
        a.branch(5, 8, 10, tag + 'copy_word')
        a.sw(21, 23, 12)
        for offset in (4912, 4916, 4920):
            a.sw(0, 23, offset)
        x_offset = distance if side == 0 else -distance
        a.li(8, struct.unpack('<I', struct.pack('<f', x_offset))[0])
        a.emit((0x11 << 26) | (4 << 21) | (8 << 16) | (1 << 11))
        a.i(49, 0, 23, 16)
        a.emit((0x11 << 26) | (16 << 21) | (1 << 16))
        a.i(57, 0, 23, 16)
        a.move(4, 22)
        a.move(5, 0)
        a.lw(6, 16, 36)
        a.addiu(7, 0, 1)
        a.call(A(0x24D038))
        for offset in (3188, 3192, 3196, 3200):
            a.lw(8, 19, offset)
            a.sw(8, 22, offset)
        a.move(4, 23)
        a.addiu(5, 0, 1)
        a.call(A(0x1D7198))
        a.move(4, 22)
        a.call(A(0x24C958))
        a.move(4, 22)
        a.call(A(0x24E3F8))
        a.addiu(8, 0, 5)
        a.sw(8, 16)
        a.li(8, HEADER)
        a.addiu(9, 0, side + 1)
        a.sw(9, 8, 4)
        a.jump(tag + 'success')
        for error in (112, 120, 130, 140):
            a.label(tag + f'error_{error}')
            a.addiu(8, 0, error)
            a.sw(8, 16)
            a.li(9, HEADER)
            a.sw(8, 9, 24)
            a.sw(0, 9)
            a.jump('finish')
        a.label(tag + 'success')
    a.li(16, HEADER)
    a.addiu(8, 0, 5)
    a.sw(8, 16, 24)
    a.jump('finish')
    for error in (110, 150):
        a.label(f'global_{error}')
        a.addiu(8, 0, error)
        a.sw(8, 16, 24)
        a.jump('finish')
    a.label('finish')
    for n in range(8):
        a.i(55, 16 + n, 29, n * 8)
    a.i(55, 31, 29, 0x40)
    a.addiu(29, 29, 0x80)
    for instruction in struct.unpack('<2I', readelf(FRAME_ENTRY, 8)):
        a.emit(instruction)
    a.jump(FRAME_ENTRY + 8)
    payload = a.finish()
    assert len(payload) < EXT_CODE - CODE
    redirect = ext_stub(readelf(EXT_ENTRY, 8))
    descriptor_data = bytearray(0x80)
    for offset in (8, 0x48):
        struct.pack_into('<I', descriptor_data, offset, 0xFFFFFFFF)
    blocks = [make_block(ram, address, data, purpose) for address, data, purpose in (
        (CODE, payload, 'Create two independent leader clones once; no physical exposure'),
        (EXT_CODE, redirect, 'Resolve both private model scratch buffers before native index limit'),
        (DESCRIPTORS[0], bytes(descriptor_data), 'Two independent clone descriptors'),
        (HEADER, bytes(32), 'Creation and exposure header; exposure initially disabled'),
        (EXT_ENTRY, struct.pack('<2I', (2 << 26) | (EXT_CODE >> 2), 0), 'Private scratch getter'),
        (FRAME_ENTRY, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0), 'Install one-shot frame callback last'))]
    result = metadata(ram, elf, 'FOUR-ACTOR STAGE1 CREATION; ONLY TWO NATIVE ACTORS EXPOSED', blocks)
    result['sources'] = sources
    result['requirements'] = ['Apply paused, then save/load to invalidate compiled EE code.',
                              'Require header+24=5, header+4=2, and both descriptor statuses5 before stage2.',
                              'On any creation error restore a full clean state; failed allocations/models are not reclaimed here.',
                              'New model IDs must be distinct members of {2,3} for current collision masks.',
                              'This creates clones of the two loaded leaders, not arbitrary selected roster members.']
    return write_manifest(output, result, [(CODE, payload), (EXT_CODE, redirect)])


def count_stub(original):
    a = Assembler(COUNT_CODE)
    a.li(2, HEADER)
    a.lw(3, 2, 8)
    a.branch(4, 3, 0, 'original')
    a.lw(2, 2, 4)
    a.addiu(2, 2, 2)
    a.jr()
    a.label('original')
    assert struct.unpack('<3I', original) == ((35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x575C) & 0xFFFF), 0x03E00008, 0x8C620000)
    for instruction in struct.unpack('<3I', original):
        a.emit(instruction)
    return a.finish()


def build_exposure(ram_path, elf_path, output):
    ram = Path(ram_path).read_bytes()
    assert len(ram) == 0x2000000
    elf, _, readelf = elf_reader(Path(elf_path))
    assert word(ram, HEADER + 24) == 5 and word(ram, HEADER + 4) == 2
    assert word(ram, EXPOSURE) == 0
    manager = word(ram, HEADER + 12)
    assert manager == word(ram, ACTOR_GLOBAL) and word(ram, manager) == 2
    allocations, actors, ids = [], [], []
    for side, descriptor in enumerate(DESCRIPTORS):
        assert word(ram, descriptor) == 5
        allocation, actor = word(ram, descriptor + 4), word(ram, descriptor + 28)
        assert actor == allocation + ACTOR_OFFSET and word(ram, actor) == side
        assert word(ram, descriptor + 44) + word(ram, descriptor + 52) <= allocation + AUX_OFFSETS[0]
        model_id = word(ram, actor + 12)
        assert model_id in (2, 3) and model_id == word(ram, descriptor + 8)
        assert word(ram, MODEL_TABLE + model_id * 4) == word(ram, descriptor + 12)
        assert word(ram, word(ram, descriptor + 12) + 5728) == allocation
        allocations.append(allocation)
        actors.append(actor)
        ids.append(model_id)
    assert set(ids) == {2, 3} and abs(allocations[0] - allocations[1]) >= ALLOC_SIZE
    assert not any(ram[COUNT_CODE:COUNT_CODE + 0x80])
    assert ram[COUNT_ENTRY:COUNT_ENTRY + 12] == readelf(COUNT_ENTRY, 12)
    count = count_stub(readelf(COUNT_ENTRY, 12))
    blocks = [make_block(ram, COUNT_CODE, count, 'Virtual actor count4 while exposed; raw count remains2'),
              make_block(ram, COUNT_ENTRY, struct.pack('<2I', (2 << 26) | (COUNT_CODE >> 2), 0), 'Count getter hook')]
    for field, offset, backup in ((8, AUX_OFFSETS[0], 16), (12, AUX_OFFSETS[1], 20)):
        old = word(ram, manager + field)
        new = allocations[0] + offset
        data = bytearray(ram[old:old + 104])
        for _ in range(2):
            extra = bytearray(52)
            for empty_handle in (0, 12, 24, 36):
                struct.pack_into('<I', extra, empty_handle, 0xFFFFFFFF)
            data.extend(extra)
        assert len(data) == 208 and not any(ram[new:new + len(data)])
        blocks.extend([make_block(ram, new, bytes(data), 'Four actor audio/event records, existing two preserved'),
                       make_block(ram, HEADER + backup, struct.pack('<I', old), 'Back up actual allocation pointer for lifecycle guard'),
                       make_block(ram, manager + field, struct.pack('<I', new), 'Use expanded auxiliary records')])
    for side, actor in enumerate(actors):
        blocks.append(make_block(ram, actor, struct.pack('<I', side + 2), f'Expose independent physical actor {side + 2}'))
    blocks.append(make_block(ram, EXPOSURE, struct.pack('<I', 1), 'Enable all mappings only after matching AI/effects/collision/guard hooks'))
    result = metadata(ram, elf, 'FOUR-ACTOR EXPOSURE; REQUIRES TEAM AI AND COMBAT HOOKS', blocks)
    result['requirements'] = ['Install team_ai.py getter and both private NPC contexts before final exposure write.',
                              'Install opposing-leader selectors, team effects/collision, and team baseline guards before running count4.',
                              'If combining manifests, put exposure write last and validate all bytes against the same paused snapshot.',
                              'Save/load to invalidate the EE recompiler; use a full clean state for recovery.']
    return write_manifest(output, result, [(COUNT_CODE, count)])


def lifecycle_stub(entry, cave, original):
    a = Assembler(cave)
    a.li(8, HEADER)
    a.lw(9, 8, 12)
    a.lw(10, 28, -22364)
    a.branch(5, 9, 10, 'original')
    a.branch(4, 10, 0, 'original')
    for field, backup in ((8, 16), (12, 20)):
        a.lw(11, 8, backup)
        a.branch(4, 11, 0, f'next_{field}')
        a.sw(11, 10, field)
        a.label(f'next_{field}')
    for offset in (0, 4, 8, 12):
        a.sw(0, 8, offset)
    a.addiu(9, 0, 250)
    a.sw(9, 8, 24)
    a.li(8, AI_CONTROL)
    for offset in (0, 0x28, 0x48):  # active alias, extra2 enabled, extra3 enabled
        a.sw(0, 8, offset)
    for descriptor in DESCRIPTORS:
        a.li(8, descriptor)
        a.sw(9, 8)
        a.sw(0, 8, 32)
        a.addiu(10, 0, -1)
        a.sw(10, 8, 8)
    a.label('original')
    instructions = struct.unpack('<2I', original)
    assert all(i >> 26 not in (1, 2, 3, 4, 5, 6, 7) for i in instructions)
    for instruction in instructions:
        a.emit(instruction)
    a.jump(entry + 8)
    code = a.finish()
    assert len(code) <= 0x100
    return code


def build_guards(ram_path, elf_path, output):
    ram = Path(ram_path).read_bytes()
    elf, _, readelf = elf_reader(Path(elf_path))
    output = Path(output)
    blocks = []
    for name, builder in (('stats', build_stats_guard), ('audio', build_audio_guards),
                          ('replay', build_replay_guards)):
        component = builder(Path(ram_path), Path(elf_path), output.with_suffix(f'.{name}.json'))
        blocks.extend(component['blocks'])
    regions = []
    for entry, cave in ((A(0x1C2810), 0xB6600), (A(0x1C2858), 0xB6700)):
        assert ram[entry:entry + 8] == readelf(entry, 8)
        assert not any(ram[cave:cave + 0x100])
        code = lifecycle_stub(entry, cave, readelf(entry, 8))
        regions.append((cave, code))
        blocks.append(make_block(ram, cave, code, 'Detach both extras before reset/free; restore true auxiliary allocations'))
        blocks.append(make_block(ram, entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0), 'Team lifecycle entry'))
    result = metadata(ram, elf, 'FOUR-ACTOR STATS/AUDIO/REPLAY AND LIFECYCLE GUARDS', blocks)
    result['requirements'] = ['These guards share the team descriptor layout; do not combine with legacy single-extra lifecycle hooks.',
                              'Reset detaches both extras and does not reclaim the experiment allocations or auto-spawn next match.',
                              'Save/load to invalidate compiled EE code after applying.']
    return write_manifest(output, result, regions)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('create', 'expose', 'guards'))
    parser.add_argument('--ram', type=Path, default=ROOT / 'analysis/fresh.bin')
    parser.add_argument('--elf', type=Path, default=elf_path(ROOT))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--distance', type=float, default=90.0)
    args = parser.parse_args()
    if args.stage == 'create':
        build_creation(args.ram, args.elf, args.out, args.distance)
    elif args.stage == 'expose':
        build_exposure(args.ram, args.elf, args.out)
    else:
        build_guards(args.ram, args.elf, args.out)
