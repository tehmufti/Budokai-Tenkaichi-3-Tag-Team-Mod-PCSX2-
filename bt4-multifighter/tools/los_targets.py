"""Per-target line-of-sight obstruction flag for captured teams.

Native sub_1DAE98 runs every battle frame: it clears flag 0xBA on fighters 0
and 1, ray-casts the stage between bone 47 of their models (sub_2058E0,
sub_2398F0, sub_1B2DF0) and sets 0xBA on both when geometry blocks the
segment. sub_1C84A8 rejects every melee contact of an attacker carrying 0xBA.
With six fighters the human's real target is usually an extra, so terrain (or
a fallen leader's body) between the human and the opposing LEADER blocked all
of the human's melee against anyone.

This wrapper clears 0xBA on every captured fighter and ray-casts each fighter
against its own pair-local target, setting the flag on that attacker only.
Offline builder only.
"""
from native_map import A, CRC, SERIAL, elf_path
from native_map import FLAG as NATIVE_FLAG
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
from battle_mode_policy import ACTOR_COUNTS

HOOK = A(0x1DAE98)
CLEAR_FLAG, SET_FLAG, BONE_POSITION, SEGMENT, RAYCAST = A(0x1DAA50), A(0x1DA9D0), A(0x2058E0), A(0x2398F0), A(0x1B2DF0)
CODE, TAIL, CONTROL = 0x073CF000, 0x073CF400, 0x073CF800
FLAG, BONE = NATIVE_FLAG(0xBA), 47
FIELDS = dict(enabled=0, manager=4, frames=8, blocked=16)  # blocked: twelve per-actor counters
POINTERS = core.POINTERS
SAVED = ((16, 0x40), (17, 0x48), (18, 0x50), (19, 0x58), (20, 0x60), (31, 0x68))


def code(free_for_all=False):
    a = Assembler(CODE)
    a.addiu(29, 29, -0x70)
    for reg, off in SAVED: a.i(63, reg, 29, off)
    core.gate(a, 'native')
    a.move(16, 10); a.move(17, 0)
    a.label('clear'); a.r(0x2B, 8, 17, 16); a.branch(4, 8, 0, 'cleared')
    a.li(8, POINTERS); a.r(0, 9, 0, 17, 2); a.r(0x2D, 8, 8, 9); a.lw(4, 8)
    a.branch(4, 4, 0, 'clear_next')
    a.addiu(5, 0, FLAG); a.call(CLEAR_FLAG)
    a.label('clear_next'); a.addiu(17, 17, 1); a.jump('clear')
    a.label('cleared'); a.li(8, CONTROL); a.lw(9, 8, FIELDS['frames']); a.addiu(9, 9, 1); a.sw(9, 8, FIELDS['frames'])
    a.move(17, 0)
    a.label('loop'); a.r(0x2B, 8, 17, 16); a.branch(4, 8, 0, 'done')
    a.li(8, POINTERS); a.r(0, 9, 0, 17, 2); a.r(0x2D, 8, 8, 9); a.lw(18, 8)
    a.branch(4, 18, 0, 'next')
    a.move(4, 18); a.call(core.RESOLVER); a.move(19, 2)
    a.branch(4, 19, 0, 'next'); a.branch(4, 19, 18, 'next')
    if not free_for_all:
        a.lw(8, 18); a.lw(9, 19); a.i(12, 8, 8, 1); a.i(12, 9, 9, 1); a.branch(4, 8, 9, 'next')
    a.lw(4, 18, 12); a.addiu(5, 0, BONE); a.addiu(6, 29, 0x20); a.call(BONE_POSITION)
    a.lw(4, 19, 12); a.addiu(5, 0, BONE); a.addiu(6, 29, 0x30); a.call(BONE_POSITION)
    a.move(4, 29); a.addiu(5, 29, 0x20); a.addiu(6, 29, 0x30); a.call(SEGMENT)
    a.move(4, 29); a.call(RAYCAST); a.branch(4, 2, 0, 'next')
    a.move(4, 18); a.addiu(5, 0, FLAG); a.call(SET_FLAG)
    a.li(8, CONTROL); a.r(0, 9, 0, 17, 2); a.r(0x2D, 8, 8, 9)
    a.lw(9, 8, FIELDS['blocked']); a.addiu(9, 9, 1); a.sw(9, 8, FIELDS['blocked'])
    a.label('next'); a.addiu(17, 17, 1); a.jump('loop')
    a.label('done'); a.move(2, 0)
    for reg, off in SAVED: a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x70); a.jr()
    a.label('native')
    for reg, off in SAVED: a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x70); a.jump(TAIL)
    result = a.finish(); assert len(result) <= TAIL-CODE; return result


def tail(original):
    a = Assembler(TAIL)
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21), 'Branching native prologue'
        a.emit(word)
    a.jump(HOOK+8)
    return a.finish()


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(A(0x2FEB14))
    if not 0x100000 <= manager <= len(ram)-16 or u(manager) != 2: raise ValueError('Requires the native two-row actor manager')
    if config is None:
        if u(core.MODE) != 1 or u(core.MODE+8) != manager or u(core.MODE+4) not in ACTOR_COUNTS:
            raise ValueError('Requires an active captured team or an explicit hidden configuration')
    else:
        import fresh_team_ai
        config = fresh_team_ai.normalize(config)
        fresh_team_ai.validate_world(ram, u, config)
    _, _, native = elf_reader(elf_path(ROOT))
    resolver = core.resolver_code()
    if config is None and ram[core.RESOLVER:core.RESOLVER+len(resolver)] != resolver:
        raise ValueError('Pair-local resolver is not installed')
    original = native(HOOK, 8)
    if ram[HOOK:HOOK+8] != original: raise ValueError('Native line-of-sight routine changed')
    for entry in (CLEAR_FLAG, SET_FLAG, BONE_POSITION, SEGMENT, RAYCAST):
        if ram[entry:entry+8] != native(entry, 8): raise ValueError(f'Native helper changed:{entry:X}')
    if any(ram[CODE:CONTROL+0x100]): raise ValueError('Line-of-sight reservation occupied')
    control = bytearray(0x100); struct.pack_into('<2I', control, 0, 1, manager)
    pieces = [(CODE, code(), 'Per-target line-of-sight obstruction'),
              (TAIL, tail(original), 'Displaced native prologue'),
              (CONTROL, bytes(control), 'Ownership, frames and per-actor blocked counters'),
              (HOOK, struct.pack('<2I', (2<<26)|(CODE>>2), 0), 'Install wrapper')]
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex(), purpose=w) for p, d, w in pieces]
    support = [dict(address=b['address'], data_hex=b['data_hex']) for b in blocks if b['address'] != CONTROL]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks, control=CONTROL,
        status='PER-TARGET LINE-OF-SIGHT MELEE FLAG',
        telemetry=dict(frames=CONTROL+8, blocked=CONTROL+16),
        support={'capacity': 12, 'features': {'los_targets': support}},
        evidence=['1DAE98 clears 0xBA on fighters 0/1 and ray-casts only between them (0x1DAEB0/0x1DAEBC).',
                  '1C84A8 first rejects any attacker carrying 0xBA.'],
        limitations=['Six ray-casts per frame instead of one.', 'Dead targets are tested like native (no HP check).'])


def build(source, config=None):
    return build_memory(read_ram(source), config, source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--config', type=Path); p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source, json.loads(x.config.read_text()) if x.config else None)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
