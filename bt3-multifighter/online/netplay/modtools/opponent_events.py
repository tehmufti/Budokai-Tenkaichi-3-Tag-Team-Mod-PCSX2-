"""Route the opponent-model helper and widen the animation-event rows.

Native sub_1DB7B0 returns the opponent's registered model id by the two-fighter
rule (own id nonzero -> fighter 0, otherwise fighter 1). Effects that react to
the opponent's animation events read that model's row of the event table
(gp-22644 object: +0 pool, +4 rows of 16 bytes, +8 count 2) through
sub_158438; the impact flash and the five delayed punch sounds of rush
specials (sub_156F08/sub_156FF0 and siblings) are gated by event bit 0x40 of
that row. In a simultaneous match the real target is usually an extra, so the
effects watched the wrong fighter's row and, whenever that row carried the
bit, spawned a white flash and rescheduled the sounds every frame.

This module resolves the opponent through the pair-local resolver, moves the
event rows to a twelve-row copy indexed by model id, fills the extras' rows
every frame from their model animation flags (the same sub_1C4740 tests the
native monitor applies to rows 0/1), bounds the row reader, and restores the
native rows before the object is freed. Offline builder only.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
from battle_mode_policy import ACTOR_COUNTS

GP = 0x304270
EVENT_GLOBAL = A(GP-22644)
OPPONENT_HOOK, CLEAR_HOOK, READ_HOOK, FREE_HOOK = A(0x1DB7B0), A(0x158690), A(0x158438), A(0x158648)
FLAG_TEST = A(0x1C4740)
OPPONENT, OPPONENT_TAIL = 0x073CC000, 0x073CC100
CLEAR, CLEAR_TAIL = 0x073CC200, 0x073CC4C0
READ, READ_TAIL = 0x073CC500, 0x073CC600
FREE, FREE_TAIL = 0x073CC700, 0x073CC800
CONTROL, ROWS = 0x073CD000, 0x073CD100
ROW_COUNT, ROW_BYTES = 12, 16
# (model animation flag mask, event row bit) as set by the native monitor loop.
EVENT_BITS = ((0x200, 2), (0x400, 4), (0x1000, 0x10), (0x2000, 0x20), (0x4000, 0x40),
              (0x200000, 0x80), (0x400000, 0x100), (0x800000, 0x200))
POINTERS, MODE = core.POINTERS, core.MODE
FIELDS = dict(enabled=0, manager=4, native_rows=8, event_object=12,
              routed_lookups=16, fill_frames=20, bounded_reads=24, restores=28)


def tail(entry, original, at):
    a = Assembler(at)
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21), 'Branching native prologue'
        a.emit(word)
    a.jump(entry+8)
    return a.finish()


def opponent_code():
    """a0 = actor -> v0 = model id of its pair-local target; native otherwise."""
    a = Assembler(OPPONENT)
    a.addiu(29, 29, -0x30)
    for i, r in enumerate((31, 8, 9, 10)): a.i(63, r, 29, i*8)
    core.gate(a, 'native')
    a.branch(4, 4, 0, 'native')
    a.call(core.RESOLVER)
    a.branch(4, 2, 0, 'native')
    a.lw(2, 2, 12)
    a.li(8, CONTROL); a.lw(9, 8, FIELDS['routed_lookups']); a.addiu(9, 9, 1); a.sw(9, 8, FIELDS['routed_lookups'])
    for i, r in enumerate((31, 8, 9, 10)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30); a.jr()
    a.label('native')
    for i, r in enumerate((31, 8, 9, 10)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30); a.jump(OPPONENT_TAIL)
    result = a.finish(); assert len(result) <= OPPONENT_TAIL-OPPONENT; return result


def clear_code():
    """Native per-frame clear of rows 0..1, then fill the extras' rows."""
    a = Assembler(CLEAR)
    a.addiu(29, 29, -0x40)
    for i, r in enumerate((31, 16, 17, 18, 19)): a.i(63, r, 29, i*8)
    a.call(CLEAR_TAIL)
    a.lw(8, 28, -22644); a.branch(4, 8, 0, 'done')
    a.lw(9, 8, 4); a.li(10, ROWS); a.branch(5, 9, 10, 'done')
    core.gate(a, 'done')
    a.move(16, 10); a.addiu(17, 0, 2)
    a.label('loop'); a.r(0x2B, 8, 17, 16); a.branch(4, 8, 0, 'filled')
    a.li(8, POINTERS); a.r(0, 9, 0, 17, 2); a.r(0x2D, 8, 8, 9); a.lw(18, 8)
    a.branch(4, 18, 0, 'next')
    a.lw(9, 18, 12); a.i(11, 10, 9, ROW_COUNT); a.branch(4, 10, 0, 'next')
    a.r(0, 9, 0, 9, 4); a.li(19, ROWS); a.r(0x2D, 19, 19, 9)
    a.sw(0, 19)
    for mask, bit in EVENT_BITS:
        a.move(4, 18); a.li(5, mask); a.call(FLAG_TEST); a.branch(4, 2, 0, f'skip{bit:x}')
        a.lw(8, 19); a.i(13, 8, 8, bit); a.sw(8, 19)
        a.label(f'skip{bit:x}')
    a.label('next'); a.addiu(17, 17, 1); a.jump('loop')
    a.label('filled'); a.li(8, CONTROL); a.lw(9, 8, FIELDS['fill_frames']); a.addiu(9, 9, 1); a.sw(9, 8, FIELDS['fill_frames'])
    a.label('done')
    for i, r in enumerate((31, 16, 17, 18, 19)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x40); a.jr()
    result = a.finish(); assert len(result) <= CLEAR_TAIL-CLEAR; return result


def read_code():
    """a0 = model id. Rows 0/1 stay native; extra rows need the widened table."""
    a = Assembler(READ)
    a.i(11, 8, 4, 2); a.branch(5, 8, 0, 'native')
    a.i(11, 8, 4, ROW_COUNT); a.branch(4, 8, 0, 'bounded')
    a.lw(8, 28, -22644); a.branch(4, 8, 0, 'bounded')
    a.lw(8, 8, 4); a.li(9, ROWS); a.branch(4, 8, 9, 'native')
    a.label('bounded'); a.li(8, CONTROL); a.lw(9, 8, FIELDS['bounded_reads']); a.addiu(9, 9, 1); a.sw(9, 8, FIELDS['bounded_reads'])
    a.move(2, 0); a.jr()
    a.label('native'); a.jump(READ_TAIL)
    result = a.finish(); assert len(result) <= READ_TAIL-READ; return result


def free_code():
    """Give the native rows back before the object frees them."""
    a = Assembler(FREE)
    a.lw(8, 28, -22644); a.branch(4, 8, 0, 'native')
    a.lw(9, 8, 4); a.li(10, ROWS); a.branch(5, 9, 10, 'native')
    a.li(10, CONTROL); a.lw(11, 10, FIELDS['native_rows']); a.sw(11, 8, 4)
    a.lw(11, 10, FIELDS['restores']); a.addiu(11, 11, 1); a.sw(11, 10, FIELDS['restores'])
    a.label('native'); a.jump(FREE_TAIL)
    result = a.finish(); assert len(result) <= FREE_TAIL-FREE; return result


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    valid = lambda p, n: 0x100000 <= p <= len(ram)-n
    manager = u(A(0x2FEB14))
    if not valid(manager, 16) or u(manager) != 2: raise ValueError('Requires the native two-row actor manager')
    if config is None:
        count = u(MODE+4)
        if u(MODE) != 1 or u(MODE+8) != manager or count not in ACTOR_COUNTS:
            raise ValueError('Requires an active captured team or an explicit hidden configuration')
    else:
        import fresh_team_ai
        config = fresh_team_ai.normalize(config)
        fresh_team_ai.validate_world(ram, u, config)
    event = u(EVENT_GLOBAL)
    if not valid(event, 12): raise ValueError('Animation-event object is not allocated (no battle)')
    rows, count = u(event+4), u(event+8)
    if not valid(rows, 2*ROW_BYTES) or count != 2: raise ValueError('Expected the native two-row animation-event table')
    if rows == ROWS: raise ValueError('Widened animation-event rows are already installed')
    _, _, native = elf_reader(elf_path(ROOT))
    resolver = core.resolver_code()
    if config is None and ram[core.RESOLVER:core.RESOLVER+len(resolver)] != resolver:
        raise ValueError('Pair-local resolver is not installed')
    if ram[FLAG_TEST:FLAG_TEST+8] != native(FLAG_TEST, 8): raise ValueError('Native flag test changed')
    if any(ram[OPPONENT:ROWS+ROW_COUNT*ROW_BYTES]): raise ValueError('Opponent-events reservation occupied')
    control = bytearray(0x100)
    struct.pack_into('<4I', control, 0, 1, manager, rows, event)
    table = bytearray(ROW_COUNT*ROW_BYTES); table[:2*ROW_BYTES] = ram[rows:rows+2*ROW_BYTES]
    pieces = [(OPPONENT, opponent_code(), 'Opponent model id through the pair-local resolver'),
              (CLEAR, clear_code(), 'Native row clear plus per-frame extra rows'),
              (READ, read_code(), 'Bounded event row reader'),
              (FREE, free_code(), 'Restore native rows before release'),
              (CONTROL, bytes(control), 'Ownership, native rows pointer and counters'),
              (ROWS, bytes(table), 'Twelve animation-event rows indexed by model id')]
    hooks = [(OPPONENT_HOOK, OPPONENT, OPPONENT_TAIL), (CLEAR_HOOK, CLEAR, CLEAR_TAIL),
             (READ_HOOK, READ, READ_TAIL), (FREE_HOOK, FREE, FREE_TAIL)]
    for entry, cave, at in hooks:
        original = native(entry, 8)
        if ram[entry:entry+8] != original: raise ValueError(f'Native entry changed:{entry:X}')
        pieces += [(at, tail(entry, original, at), 'Displaced native prologue'),
                   (entry, struct.pack('<2I', (2<<26)|(cave>>2), 0), 'Install wrapper')]
    pieces.append((event+4, struct.pack('<I', ROWS), 'Point the event object at the widened rows'))
    blocks = []
    for p, data, why in pieces:
        old = ram[p:p+len(data)]
        if OPPONENT <= p < ROWS+ROW_COUNT*ROW_BYTES and any(old): raise ValueError(f'Occupied reservation:{p:X}')
        blocks.append(dict(address=p, expected_hex=old.hex(), data_hex=data.hex(), purpose=why))
    intervals = sorted((b['address'], b['address']+len(bytes.fromhex(b['data_hex']))) for b in blocks)
    assert all(end <= q for (_, end), (q, _) in zip(intervals, intervals[1:]))
    data_addresses = {CONTROL, ROWS, event+4}
    support = [dict(address=b['address'], data_hex=b['data_hex']) for b in blocks if b['address'] not in data_addresses]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
        control=CONTROL, rows=ROWS, event_object=event, native_rows=rows,
        status='OPPONENT MODEL ROUTING AND TWELVE ANIMATION-EVENT ROWS',
        telemetry={k: CONTROL+v for k, v in FIELDS.items() if k.endswith('s')},
        support={'capacity': ROW_COUNT, 'features': {'opponent_events': support}},
        evidence=['1DB7B0 picks fighter 0 when the own id is nonzero, otherwise fighter 1, and returns model id +12.',
                  '158438 reads row 16*model_id; 158690 clears count rows; the monitor 158C70 fills rows below count from 207A90.',
                  '156F08/156FF0 and 15B930/15BA00 create the impact flash and five delayed sounds (id 71) on event bit 0x40.'],
        limitations=['Rows for extras carry the eight monitor-loop bits only; owner-specific bits 8/0x400 are not produced.',
                     'Fight Again allocates a fresh native table; extra rows are then reported empty until the trainer reinstalls.'])


def build(source, config=None):
    return build_memory(read_ram(source), config, source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--config', type=Path); p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source, json.loads(x.config.read_text()) if x.config else None)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
