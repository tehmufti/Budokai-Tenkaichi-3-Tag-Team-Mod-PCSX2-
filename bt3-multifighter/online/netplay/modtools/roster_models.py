"""Offline selected-bench model replacement, retaining both leader models.

Requires loaded dynamic bundles, all CPU flags/input masks zero, and four valid
actors. Reuses model slots2/3 and their private animation memory. No AI enable.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import hashlib
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from team_prototype import make_block, write_manifest
from native_map import FILE_ID

CODE, CACHE, REFRESH, MAIL = 0xE4000, 0xE6000, 0xE6200, 0xE7000
HOOK, PREVIOUS = A(0x1C2A28), 0xE0000
DESCRIPTORS = (0xB3000, 0xB3040)


def private_initializers(readelf):
    cache = bytearray(readelf(A(0x1C0058), 0xD0))
    changes = {0x14: 0x0C000000|(A(0x12B1D0)>>2), 0x18: 0x8E040000, 0x24: 0xAE02000C}
    for offset, expected in changes.items():
        assert struct.unpack_from('<I', cache, offset)[0] == expected
        struct.pack_into('<I', cache, offset, 0)
    # Native prologue preserves all its normal saved registers and f20. The
    # original suffix handles character-dependent properties and returns using
    # the same frame. Only its first cache-init call uses our private version.
    refresh = bytearray(readelf(A(0x1C0538), 0x2C))
    assert struct.unpack_from('<I', refresh, 0x24)[0] == 0x0C000000|(A(0x1C0058)>>2)
    struct.pack_into('<I', refresh, 0x24, (3 << 26) | (CACHE >> 2))
    refresh.extend(struct.pack('<2I', (2 << 26) | (A(0x1C0564) >> 2), 0))
    return bytes(cache), bytes(refresh)


def build(source, output):
    ram = read_ram(source)
    assert len(ram) == 0x8000000, 'Full128 MB source required'
    u = lambda address: struct.unpack_from('<I', ram, address)[0]
    assert not any(ram[CODE:MAIL + 0x100]), 'Distinct-model cave occupied'
    assert u(HOOK) == (2 << 26) | (PREVIOUS >> 2) and not u(HOOK + 4)
    assert u(0xE2004) == 5 and u(0xC9400) == 20, 'Resources/extended heap not ready'
    assert u(0xB3084) == 2 and u(0xB3088) == 1
    manager = u(A(0x2FEB14))
    assert manager == u(0xB308C) and u(manager) == 2
    native = [u(manager + 4), u(manager + 4) + 0x1600]
    actors = native + [u(descriptor + 28) for descriptor in DESCRIPTORS]
    assert len(set(actors)) == 4 and all(u(actor) == i for i, actor in enumerate(actors))
    assert all(u(actor + 0x1278) == 0 and u(actor + 0x127C) == 0 for actor in actors)
    elf, _, readelf = elf_reader(elf_path(ROOT))
    for address, size in ((A(0x249BD8), 0x70), (A(0x1135F0), 0x70), (A(0x249000), 0x58),
                          (A(0x1C0058), 0xD0), (A(0x1C0538), 0x570), (A(0x1C3E60), 0x1B0)):
        assert ram[address:address + size] == readelf(address, size), f'Native helper changed: {address:X}'
    leaders = []
    rows = []
    for side in range(2):
        leader_model = u(A(0x31C640) + side * 4)
        geometry = u(leader_model + 64)
        group = u(geometry + 40)
        assert group < 15
        leaders.append({'model': leader_model, 'resource': u(leader_model + 20),
                        'geometry': geometry, 'group': group})
        descriptor = DESCRIPTORS[side]
        actor, model_id, model, ext = (u(descriptor + field) for field in (28, 8, 12, 4))
        assert model_id in (2, 3) and u(actor + 12) == model_id
        assert u(A(0x31C640) + model_id * 4) == model and u(model + 5728) == ext
        assert u(model + 64) == geometry and u(model + 20) == leaders[-1]['resource']
        assert u(actor + 2376) < 236, 'Use an extra actor outside transformation/tag action states'
        slot = u(actor + 0x994) + 1
        assert slot < u(actor + 0x998) <= 5
        character = u(actor + 0x9A4 + slot * 0xA4)
        off = 0xE2040 + side * 32
        handle, resource = u(off + 4), u(off + 8)
        assert u(off) == character and 2 <= handle < 14
        assert u(resource + 48) == 3 and u(resource + 52) == handle
        for file_index, suffix in enumerate((1424, 1432, 1433)):
            record = resource + file_index * 16
            pointer, size = u(record), u(record + 4)
            assert u(record + 8) == FILE_ID(10 * character + suffix)
            assert pointer and size and pointer + size <= len(ram)
        assert resource not in [u(leader['model'] + 20) for leader in leaders]
        rows.append({'actor': actor, 'model_id': model_id, 'model': model, 'ext': ext,
                     'handle': handle, 'resource': resource, 'character': character,
                     'slot': slot, 'old_group': group, 'old_resource': u(model + 20)})
    assert rows[0]['model_id'] != rows[1]['model_id'] and rows[0]['resource'] != rows[1]['resource']
    cache, refresh = private_initializers(readelf)
    mail = bytearray(0x100)
    struct.pack_into('<3I', mail, 4, 1, 0, manager)
    for side, row in enumerate(rows):
        struct.pack_into('<8I', mail, 0x40 + side * 0x40, row['actor'], row['model_id'], row['model'],
                         row['handle'], row['resource'], row['character'], row['slot'], row['old_group'])

    a = Assembler(CODE)
    a.addiu(29, 29, -0x50)
    for n, reg in enumerate((16, 17, 18, 19, 20, 21, 22, 31)):
        a.i(63, reg, 29, n * 8)
    a.call(PREVIOUS)
    a.i(63, 2, 29, 0x40)
    a.li(16, MAIL)
    a.lw(8, 16)
    a.branch(5, 8, 0, 'done')
    a.addiu(8, 0, 1)
    a.sw(8, 16)
    for actor in actors:
        a.li(8, actor)
        for offset in (0x1278, 0x127C):
            a.lw(9, 8, offset)
            a.branch(5, 9, 0, 'error110')
    for side, row in enumerate(rows):
        record = 0x40 + side * 0x40
        a.li(17, row['actor'])
        a.li(18, row['model'])
        # A shared resource group has no reference count: preserve the leader's
        # reservation after destroying the clone, before creating a new group.
        a.move(4, 18)
        a.call(A(0x1135F0))
        a.addiu(4, 0, row['old_group'])
        a.call(A(0x249000))
        a.addiu(4, 0, row['model_id'])
        a.addiu(5, 0, row['handle'])
        a.call(A(0x249BD8))
        for offset, expected in ((16, row['model_id']), (20, row['resource']),
                                 (12, row['character']), (5728, row['ext'])):
            a.lw(8, 18, offset)
            a.li(9, expected)
            a.branch(5, 8, 9, 'error120')
        a.lw(8, 18, 64)
        a.lw(19, 8, 40)
        a.i(11, 9, 19, 15)
        a.branch(4, 9, 0, 'error121')
        for leader in leaders:
            a.addiu(9, 0, leader['group'])
            a.branch(4, 19, 9, 'error121')
        a.sw(19, 16, record + 36)
        a.addiu(8, 0, row['slot'])
        a.sw(8, 17, 0x994)
        for offset in (5608, 5612, 5616):
            a.sw(0, 17, offset)
        a.move(4, 17)
        a.call(REFRESH)
        a.move(4, 17)
        a.move(5, 0)
        a.emit((17 << 26) | (4 << 21) | (12 << 11))  # mtc1 zero,f12: frame0
        a.call(A(0x1C3E60))
        a.move(4, 17)
        a.addiu(5, 0, 1)
        a.call(A(0x1D7198))
        for function in (A(0x24C958), A(0x24CC88), A(0x24E3F8)):
            a.move(4, 18)
            a.call(function)
        for field, offset in ((12, 32), (5728, 40), (2356, 44), (84, 48)):
            a.lw(8, 18, field)
            a.sw(8, 16, record + offset)
        a.li(8, row['old_resource'])
        a.sw(8, 16, record + 52)
        a.addiu(8, 0, 5)
        a.sw(8, 16, record + 56)
        a.addiu(8, 0, side + 1)
        a.sw(8, 16, 8)
    for leader in leaders:
        a.li(8, leader['model'])
        for field, expected in ((20, leader['resource']), (64, leader['geometry'])):
            a.lw(9, 8, field)
            a.li(10, expected)
            a.branch(5, 9, 10, 'error130')
    a.addiu(8, 0, 5)
    a.sw(8, 16)
    a.jump('done')
    for error in (110, 120, 121, 130):
        a.label(f'error{error}')
        a.addiu(8, 0, error)
        a.sw(8, 16)
        a.jump('done')
    a.label('done')
    a.i(55, 2, 29, 0x40)
    for n, reg in enumerate((16, 17, 18, 19, 20, 21, 22, 31)):
        a.i(55, reg, 29, n * 8)
    a.addiu(29, 29, 0x50)
    a.jr()
    payload = a.finish()
    assert len(payload) < CACHE - CODE
    blocks = [make_block(ram, address, data, purpose) for address, data, purpose in (
        (CODE, payload, 'Replace both extra models with selected bench resources'),
        (CACHE, cache, 'Native actor model cache initializer preserving existing model ID'),
        (REFRESH, refresh, 'Native actor refresh prologue using private cache initializer'),
        (MAIL, bytes(mail), 'Distinct model conversion evidence; all CPU flags remain zero'),
        (HOOK, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0), 'Chain conversion after loader'))]
    return write_manifest(output, {'serial': SERIAL, 'crc': CRC,
        'status': 'EXPERIMENTAL SELECTED-BENCH MODELS; NO AI ENABLE',
        'source': str(Path(source).resolve()), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
        'rows': rows, 'leaders': leaders, 'mailbox': MAIL, 'blocks': blocks,
        'requirements': ['Apply paused with exact expected bytes; save/reload to flush EE code.',
                         'Require mailboxE7000=5 and completed+8=2; inspect model/actor identity and animation.',
                         'CPU flags remain zero. Distinct AI datasets and effects need a later stage.',
                         'Restore source checkpoint on any failure; no automatic rollback is attempted.']},
        [(CODE, payload), (CACHE, cache), (REFRESH, refresh)])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    build(args.source, args.out)
