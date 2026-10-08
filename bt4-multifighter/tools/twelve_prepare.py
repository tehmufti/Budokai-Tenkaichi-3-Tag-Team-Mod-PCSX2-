"""Checkpoint-scoped twelve-fighter preparation using explicit loaded characters.

bind freezes the existing six CPU actors and binds six configured characters to
already-loaded bundles. create adds private models/actors without exposure. The
initial proof reuses selected character bundles; no ISO or emulator is modified.
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
from team_prototype import make_block, write_manifest
from roster_models import private_initializers
from six_prepare import ext_code as six_ext_code
from native_map import FILE_ID

CODE, EXT_CODE = 0x07300000, 0x07310000
DESCS = tuple(0x07318000 + i * 0x80 for i in range(6))
HEADER = 0x07318400
HOOK, EXT_ENTRY, PREVIOUS_EXT = A(0x1C2A28), A(0x2499C8), 0xD4000
ALLOC_SIZE, ACTOR_OFF, COLLISION_OFF = 0x30000, 0x1B000, 0x1C800
SHADER_OFF, FX_OFF, AUX_OFFSETS = 0x20000, 0x22100, (0x23000, 0x23400)
PACKET_BYTES, REFRESH = 0x6E10, 0xE6200


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
    a.lw(8, 28, -22060); a.li(9, pool); a.branch(5, 8, 9, 'error110')
    for index, actor in enumerate(actors):
        a.li(8, actor)
        a.lw(9, 8); a.addiu(10, 0, index); a.branch(5, 9, 10, 'error110')
        for offset in (0x1278, 0x127C):
            a.lw(9, 8, offset); a.branch(5, 9, 0, 'error110')
    for row in rows:
        a.li(8, row['source_model']); a.lw(9, 8, 20); a.li(10, row['resource'])
        a.branch(5, 9, 10, 'error110')
        a.lw(9, 8, 12); a.addiu(10, 0, row['character']); a.branch(5, 9, 10, 'error110')


def copy_words(a, tag, source_register, destination_register, size):
    if type(size) is not int or size<0 or size%4:raise ValueError('Word copy requires a nonnegative aligned size')
    if size==0:return
    a.move(8, source_register); a.move(9, destination_register); a.li(10, size)
    a.label(tag)
    a.lw(11, 8); a.sw(11, 9)
    a.addiu(8, 8, 4); a.addiu(9, 9, 4); a.addiu(10, 10, -4)
    a.branch(5, 10, 0, tag)


def ext_code(existing_model_ids):
    a = Assembler(EXT_CODE)
    a.i(11, 8, 4, 12); a.branch(4, 8, 0, 'old')
    for index, model_id in enumerate(existing_model_ids):
        a.addiu(8, 0, model_id); a.branch(4, 4, 8, 'old')
    for index, desc in enumerate(DESCS):
        a.li(8, desc); a.lw(9, 8, 8)
        a.branch(5, 4, 9, f'next{index}')
        a.lw(2, 8, 4); a.branch(5, 2, 0, 'return')
        a.label(f'next{index}')
    a.li(8, HEADER); a.lw(8, 8, 20); a.branch(4, 8, 0, 'old')
    a.lw(2, 8, 4); a.branch(4, 2, 0, 'old'); a.sw(4, 8, 8)
    a.label('return'); a.jr()
    a.label('old'); a.jump(PREVIOUS_EXT)
    return a.finish()


def bind_code(previous, rows, actors, manager, pool):
    a = Assembler(CODE); begin(a, previous)
    a.lw(8, 16); a.branch(5, 8, 0, 'done')
    world_guards(a, rows, actors, manager, pool)
    for row, desc in zip(rows, DESCS):
        a.li(17, desc); a.li(8, row['resource'])
        a.lw(9, 8, 48); a.addiu(10, 0, row['resource_flags']); a.branch(5, 9, 10, 'error120')
        for i, file_id in enumerate(row['file_ids']):
            a.lw(9, 8, i * 16); a.branch(4, 9, 0, 'error120')
            a.lw(9, 8, i * 16 + 8); a.li(10, file_id); a.branch(5, 9, 10, 'error120')
        a.addiu(8, 0, 5); a.sw(8, 17)
    a.addiu(8, 0, 5); a.sw(8, 16); a.jump('done')
    error_labels(a, (110, 120)); finish(a)
    return a.finish()


def create_code(previous, rows, actors, manager, pool, existing_model_ids):
    a = Assembler(CODE); begin(a, previous)
    a.lw(8, 16); a.addiu(9, 0, 5); a.branch(5, 8, 9, 'done')
    world_guards(a, rows, actors, manager, pool)
    for address, required in ((pool + 397320, sum(r['draw_nodes'] for r in rows)), (pool + 69128, 6)):
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
                              (0x994, row['slot']), (0x1278, 0), (0x127C, 0),
                              (4912, 0), (4916, 0), (4920, 0), (5608, 0), (5612, 0), (5616, 0)):
            a.li(8, value); a.sw(8, 20, field)
        a.lw(8, 17, 8); a.sw(8, 20, 12)
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
        # six existing split-view models already use over600KiB of the1MiB arena.
        a.sw(0, 19, 8)
        a.lw(8, 19, 2356); a.sw(8, 17, 60)
        a.addiu(8, 0, 20); a.sw(8, 17)
        a.addiu(8, 0, index + 1); a.sw(8, 16, 8)
    # Aux rows remain unpublished until the independent activation stage.
    a.li(17, DESCS[0]); a.lw(18, 17, 4); a.li(21, manager)
    for table, aux_offset in enumerate(AUX_OFFSETS):
        a.li(8, aux_offset); a.r(0x21, 19, 18, 8); a.sw(19, 16, 32 + table * 4)
        a.lw(22, 21, 8 + table * 4); a.sw(22, 16, 40 + table * 4)
        copy_words(a, f'aux{table}', 22, 19, 6 * 52)
        a.addiu(8, 0, -1)
        for actor_index in range(6, 12):
            for handle_offset in (0, 12, 24, 36): a.sw(8, 19, actor_index * 52 + handle_offset)
    a.addiu(8, 0, 20); a.sw(8, 16); a.jump('done')
    error_labels(a, (110, 150, 151, 160, 161, 170, 171, 172, 173)); finish(a)
    return a.finish()


def configuration(ram, config):
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    assert len(ram) == 0x08000000 and u(0xC9400) == 20
    with (ROOT / 'analysis/sixcreated63.bin').open('rb') as reference:
        reference.seek(0x200)
        assert ram[0x200:0x600] == reference.read(0x400), 'Kernel vectors differ from intact baseline'
    assert u(A(0x2FF084)) == 0x02000000 and u(A(0x2FF08C)) == 0x06000000
    manager, pool = u(A(0x2FEB14)), u(A(0x2FEC44))
    assert u(manager) == 2 and u(0xD8080) == 1 and u(0xD8084) == 6
    actors = [u(0xD8040 + i * 4) for i in range(6)]
    assert len(set(actors)) == 6 and all(u(actor) == i for i, actor in enumerate(actors))
    models = [u(A(0x31C640) + u(actor + 12) * 4) for actor in actors]
    assert len(set(models)) == 6 and all(models)
    assert all(u(actor + 2376) not in (216, 217, 218) for actor in actors), 'Use pre-KO checkpoint'
    existing_ids = [u(actor + 12) for actor in actors]
    assert len(set(existing_ids)) == 6 and all(v < 12 for v in existing_ids)
    assert u(pool + 69128) == 6, 'Exactly six free native model slots required'
    additions = config['additions']
    assert len(additions) == 6
    rows = []
    for index, wanted in enumerate(additions):
        physical, side, character = index + 6, (index + 6) & 1, int(wanted['character'])
        assert int(wanted.get('side', side)) == side, 'Initial team assignment uses physical parity'
        candidates = [i for i, model in enumerate(models) if u(model + 12) == character]
        assert candidates, f'Character{character} is not loaded; this proof reuses loaded characters only'
        source = int(wanted.get('source_physical', next((i for i in candidates if i % 2 == side), candidates[0])))
        assert source in candidates
        actor, model = actors[source], models[source]
        slot = u(actor + 0x994)
        assert slot < min(5, u(actor + 0x998)) and u(actor + 0x9A4 + slot * 164) == character
        assert 0 < u(actor + 0x9E4 + slot * 164) <= u(actor + 0x9E8 + slot * 164)
        resource, collision = u(model + 20), u(model + 84)
        assert u(resource + 48) == (1 if u(resource + 52) < 2 else 3)
        assert 0x100000 <= collision < len(ram) - 0x3800
        size = 16
        while size + 464 <= 0x3800:
            terminal = u(collision + size) & 1; size += 464
            if terminal: break
        else: raise AssertionError('Collision data exceeds private copy capacity')
        files = [u(resource + i * 16 + 8) for i in range(3)]
        assert files == [FILE_ID(10 * character + n) for n in (1424, 1432, 1433)]
        assert all(u(resource + i * 16) and u(resource + i * 16 + 4) for i in range(3))
        rows.append({'physical_id': physical, 'side': side, 'character': character,
                     'source_physical': source, 'source_actor': actor, 'source_model': model,
                     'slot': slot, 'resource': resource, 'resource_handle': u(resource + 52),
                     'resource_flags': u(resource + 48),
                     'file_ids': files, 'collision': collision, 'collision_size': size,
                     'draw_nodes': u(model + 3424 + 8),
                     'x_offset': float(wanted.get('x_offset', 90.0 if side == 0 else -90.0))})
        assert math.isfinite(rows[-1]['x_offset']) and rows[-1]['draw_nodes'] > 0
    return u, manager, pool, actors, existing_ids, rows


def build(mode, source, config_path, output):
    ram = read_ram(source); config = json.loads(Path(config_path).read_text())
    u, manager, pool, actors, model_ids, rows = configuration(ram, config)
    _, _, readelf = elf_reader(elf_path(ROOT))
    for address, size in ((A(0x249AB8), 0xA0), (A(0x2554D8), 0x80), (A(0x255CF0), 0x30),
                          (A(0x113660), 0xA0), (A(0x24DB28), 0x70)):
        assert ram[address:address + size] == readelf(address, size)
    cache, refresh = private_initializers(readelf)
    assert ram[0xE6000:0xE6000 + len(cache)] == cache and ram[REFRESH:REFRESH + len(refresh)] == refresh
    assert ram[PREVIOUS_EXT:PREVIOUS_EXT + len(six_ext_code())] == six_ext_code()
    assert u(EXT_ENTRY) == (2 << 26) | (PREVIOUS_EXT >> 2) and not u(EXT_ENTRY + 4)
    blocks, regions = [], []
    def block(address, data, purpose): blocks.append(make_block(ram, address, data, purpose))
    if mode == 'bind':
        assert not any(ram[CODE:HEADER + 0x100]), 'Twelve preparation arena occupied'
        assert u(HOOK) >> 26 == 2 and u(HOOK + 4) == 0
        previous = (u(HOOK) & 0x3FFFFFF) << 2
        assert previous in (0x07200000, 0x07200600, 0x07202000), 'Review new frame chain before binding'
        data = bytearray(6 * 0x80)
        for index, row in enumerate(rows):
            fields = {8: 0xFFFFFFFF, 16: manager, 20: row['source_actor'], 24: row['source_model'],
                      32: row['resource_handle'], 36: row['resource'], 40: row['character'], 44: row['slot'],
                      64: row['source_physical'], 68: row['side'], 72: row['collision'],
                      76: row['collision_size'], 80: row['draw_nodes']}
            for field, value in fields.items(): struct.pack_into('<I', data, index * 0x80 + field, value)
        header = bytearray(0x100)
        for offset, value in ((4, 1), (12, manager), (16, previous), (24, pool),
                              (48, sum(r['draw_nodes'] for r in rows)), (52, 12)):
            struct.pack_into('<I', header, offset, value)
        code = bind_code(previous, rows, actors, manager, pool)
        block(DESCS[0], bytes(data), 'Explicit configured loaded-character bindings')
        block(HEADER, bytes(header), 'Twelve creation state; exposure disabled')
        for actor in actors:
            block(actor + 0x1278, bytes(8), 'Freeze current CPU and input during preparation')
        block(HOOK, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0), 'Chain twelve resource binding')
    else:
        assert u(HEADER) == 5 and not u(HEADER + 8) and not u(HEADER + 28)
        assert all(not u(actor + 0x1278) and not u(actor + 0x127C) for actor in actors)
        assert u(0x07201000 + 68) == 20 and u(0x07201000 + 76) >= 512, 'Grow draw pool before creation'
        assert not u(0x07201000 + 40) and not u(0x07201000 + 44), 'Resolve packet telemetry errors'
        assert u(pool + 397320) >= sum(r['draw_nodes'] for r in rows)
        previous = u(HEADER + 16)
        original = bind_code(previous, rows, actors, manager, pool)
        assert ram[CODE:CODE + len(original)] == original
        assert u(HOOK) == (2 << 26) | (CODE >> 2) and not u(HOOK + 4)
        for row, desc in zip(rows, DESCS):
            assert u(desc) == 5 and u(desc + 36) == row['resource'] and not u(desc + 4)
        code = create_code(previous, rows, actors, manager, pool, model_ids)
        redirect = ext_code(model_ids)
        block(EXT_CODE, redirect, 'Scratch ownership for any six newly allocated model IDs')
        block(EXT_ENTRY, struct.pack('<2I', (2 << 26) | (EXT_CODE >> 2), 0), 'Route new model scratch; delegate existing six')
        regions.append((EXT_CODE, redirect))
    assert len(code) < EXT_CODE - CODE
    block(CODE, code, 'Bind configured resources' if mode == 'bind' else 'Create six additional independent actors and models')
    regions.append((CODE, code))
    result = {'serial': SERIAL, 'crc': CRC, 'source': str(Path(source).resolve()),
              'ram_sha256': hashlib.sha256(ram).hexdigest(), 'mode': mode, 'blocks': blocks,
              'status': 'TWELVE PREPARATION; NEW MODELS HIDDEN; NO EXPOSURE/AI/SCHEDULING', 'config': config,
              'rows': rows, 'descriptors': DESCS, 'header': HEADER, 'previous': previous,
              'existing_model_ids': model_ids, 'required_draw_nodes': sum(r['draw_nodes'] for r in rows),
              'auxiliary': {'entries': 12, 'stride': 52, 'new_A': HEADER + 32, 'new_B': HEADER + 36,
                            'original_A': HEADER + 40, 'original_B': HEADER + 44},
              'requirements': ['Use a clean six-fighter checkpoint before any KO.',
                               'Bind freezes existing CPU flags and input; create keeps all twelve CPU flags disabled.',
                               'Grow draw pool and verify main packet telemetry before create.',
                               'All models remain allocated for this checkpoint; restore full source on failure.',
                               'Newmodel+8 remains0; expand main packet buffers before separately enabling visible models.',
                               'Only separately reviewed activation may publish the12-actor table, auxiliaries and exposure.'],
              'limitations': ['Initial proof can choose only already-loaded character bundles.',
                              'All12 native model slots are consumed; auxiliary cinematic models need separate guards.',
                              'Main packet telemetry does not measure every graphics allocation.']}
    return write_manifest(output, result, regions)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('bind', 'create'))
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(); build(args.mode, args.source, args.config, args.out)
