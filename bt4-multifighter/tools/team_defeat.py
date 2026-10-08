"""Native team-defeat predicate for captured simultaneous 2v2/3v3 matches.

Native217EF0 already selects the winner and starts the result sequence. Its
20B878 predicate reads stale leader bench HP; this replacement reads each real
same-side actor's current selected row instead. No result/menu state is forced.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import ROOT, Assembler, elf_reader
from camera_snapshot import read_ram
from battle_mode_policy import ACTOR_COUNTS

ENTRY, CODE, CONTROL = A(0x20B878), 0x073C8000, 0x073CB000
ACTORS, POINTERS, MODE = A(0x2FEB14), 0xD8040, 0xD8080


def code(original):
    a = Assembler(CODE)
    a.addiu(29, 29, -0x40)
    for i, reg in enumerate(range(8, 15)): a.i(63, reg, 29, i*8)
    a.li(8, CONTROL); a.lw(9, 8)
    a.branch(4, 9, 0, 'native')
    a.i(11, 9, 4, 2); a.branch(4, 9, 0, 'native')
    a.lw(9, 8, 4); a.lw(10, 28, -22364)
    a.branch(5, 9, 10, 'native')
    a.lw(11, 10); a.addiu(12, 0, 2); a.branch(5, 11, 12, 'native')
    a.lw(11, 10, 4); a.lw(12, 8, 8); a.branch(5, 11, 12, 'native')
    a.li(10, MODE); a.lw(11, 10); a.branch(4, 11, 0, 'native')
    a.lw(11, 10, 8); a.branch(5, 11, 9, 'native')
    a.lw(11, 10, 4); a.lw(12, 8, 12); a.branch(5, 11, 12, 'native')
    a.lw(9, 8, 16); a.addiu(9, 9, 1); a.sw(9, 8, 16)
    a.sw(4, 8, 32)
    # t1 physical index; t4 captured count; t5 actor; t6 row/current HP.
    a.move(9, 4)
    a.label('scan')
    a.r(0, 10, 0, 9, 2); a.r(0x2D, 11, 8, 10); a.lw(13, 11, 64)
    a.li(11, POINTERS); a.r(0x2D, 11, 11, 10); a.lw(14, 11)
    a.branch(5, 13, 14, 'invalid')
    a.branch(4, 13, 0, 'invalid')
    a.lw(14, 13, 8); a.branch(5, 14, 4, 'invalid')
    a.lw(14, 13, 0x994); a.i(11, 10, 14, 5); a.branch(4, 10, 0, 'invalid')
    a.lw(11, 13, 0x998); a.i(11, 10, 11, 6); a.branch(4, 10, 0, 'invalid')
    a.r(0x2B, 10, 14, 11); a.branch(4, 10, 0, 'invalid')
    # slot*164 = slot*(128+32+4), then HP at actor+9E4.
    a.r(0, 10, 0, 14, 7); a.r(0, 11, 0, 14, 5)
    a.r(0x2D, 10, 10, 11); a.r(0, 14, 0, 14, 2)
    a.r(0x2D, 10, 10, 14); a.r(0x2D, 13, 13, 10)
    a.lw(14, 13, 0x9AC); a.branch(4, 14, 0, 'invalid')
    a.lw(14, 13, 0x9E4); a.r(0x2A, 10, 0, 14)
    a.branch(5, 10, 0, 'alive')
    a.addiu(9, 9, 2); a.r(0x2B, 10, 9, 12)
    a.branch(5, 10, 0, 'scan')
    a.addiu(2, 0, 1)
    a.r(0, 10, 0, 4, 2); a.r(0x2D, 10, 8, 10)
    a.lw(11, 10, 20); a.addiu(11, 11, 1); a.sw(11, 10, 20)
    a.jump('return')
    a.label('invalid')
    a.lw(9, 8, 28); a.addiu(9, 9, 1); a.sw(9, 8, 28)
    a.label('alive'); a.move(2, 0)
    a.label('return'); a.sw(2, 8, 36)
    for i, reg in enumerate(range(8, 15)): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x40); a.jr()
    a.label('native')
    for i, reg in enumerate(range(8, 15)): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x40)
    for word in struct.unpack('<2I', original): a.emit(word)
    a.jump(ENTRY+8)
    result = a.finish()
    assert len(result) < 0x1000
    return result


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Full128MiB EE RAM required')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    valid = lambda p, n: 0x100000 <= p <= len(ram)-n
    manager = u(ACTORS)
    if not valid(manager, 16) or u(manager) != 2: raise ValueError('Expected native two-row actor manager')
    native_array = u(manager+4)
    if not valid(native_array, 0x2C00): raise ValueError('Invalid native actor array')
    if config is None:
        count = u(MODE+4)
        if u(MODE) != 1 or u(MODE+8) != manager:
            raise ValueError('An active captured match or explicit hidden-actor configuration is required')
        actors = [u(POINTERS+4*i) for i in range(count)] if count in ACTOR_COUNTS else []
    else:
        rows = config['actors']; count = len(rows)
        if [r['physical_id'] for r in rows] != list(range(count)):
            raise ValueError('Configuration must contain consecutive physical actors')
        actors = [r['actor'] for r in rows]
        if any(r['team'] != i&1 for i, r in enumerate(rows)):
            raise ValueError('Only equal interleaved teams are supported')
    if count not in ACTOR_COUNTS or len(set(actors)) != count:
        raise ValueError('Expected four or six independent captured actors')
    if actors[:2] != [native_array, native_array+0x1600]:
        raise ValueError('Original leader pointers changed')
    for i, actor in enumerate(actors):
        if not valid(actor, 0x1600) or u(actor) != i or u(actor+8) != i&1:
            raise ValueError(f'Invalid/aliased actor{i}')
        slot, rows = u(actor+0x994), u(actor+0x998)
        if not 0 <= slot < rows <= 5 or not u(actor+0x9AC+slot*164):
            raise ValueError(f'Actor{i} has invalid selected row')
    _, _, native = elf_reader(elf_path(ROOT))
    if ram[ENTRY:ENTRY+8] != native(ENTRY, 8): raise ValueError('Native defeat predicate changed')
    if ram[A(0x217EF0):A(0x2180DC)] != native(A(0x217EF0), 0x1EC):
        raise ValueError('Native winner/result selection changed')
    control = bytearray(0x100)
    struct.pack_into('<4I', control, 0, 1, manager, native_array, count)
    for i, actor in enumerate(actors): struct.pack_into('<I', control, 64+4*i, actor)
    blocks = []
    for address, payload, purpose in (
        (CODE, code(native(ENTRY, 8)), 'Check every real same-side fighter before native defeat'),
        (CONTROL, control, 'Captured match ownership and defeat counters'),
        (ENTRY, struct.pack('<2I', (2<<26)|(CODE>>2), 0), 'Use actual team HP in native winner predicate')):
        old = ram[address:address+len(payload)]
        if address != ENTRY and any(old): raise ValueError(f'Team defeat reservation occupied:{address:X}')
        blocks.append(dict(address=address, expected_hex=old.hex(), data_hex=payload.hex(), purpose=purpose))
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
        status='NATIVE TEAM DEFEAT PREDICATE; LIVE RESULT TRANSITION REQUIRES VALIDATION',
        blocks=blocks, control=CONTROL, actor_manager=manager, actors=actors,
        support={'capacity': count, 'features': {'team_defeat': [
            {'address': b['address'], 'data_hex': b['data_hex']} for b in blocks if b['address'] != CONTROL]}},
        evidence='Native217EF0 calls20B878(0/1), writes winner1/2 and reason1; only its stale-bench predicate is replaced.',
        limitations=['Native time/ring-out and simultaneous-defeat tiebreak policies remain unchanged.',
            'Native winner presentation may still show the original leader if that leader was defeated.',
            'Restore a playable checkpoint for another match; ordinary menu cleanup remains experimental.'])


def build(source, config=None):
    return build_memory(read_ram(source), config, source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source, json.loads(args.config.read_text()) if args.config else None)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'{args.out}: {len(result["blocks"])} guarded blocks')
