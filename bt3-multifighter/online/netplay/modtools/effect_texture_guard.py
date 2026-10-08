"""Reject stale effect texture metadata before native DMA packet construction.

Leader form changes reuse combat resource storage. A surviving particle can
retain a texture-row pointer into that storage; floats then become DMA lengths.
This is a captured-match upload guard, independent of the primary reload cleanup.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import fresh_team_safety as safety
from battle_mode_policy import ACTOR_COUNTS

HOOK, CODE, CONTROL, END = A(0x1AE4E0), 0x07400000, 0x07401000, 0x07402000
QUEUE = A(0x304270-22396)
RAM_BYTES, MAX_TRANSFER = 0x08000000, 0xFFFF0
SAVED = tuple((8+i, i*8) for i in range(8))


def payload(original):
    a = Assembler(CODE); a.addiu(29, 29, -0x40)
    for reg, off in SAVED: a.i(63, reg, 29, off)
    core.gate(a, 'native')
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'native')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'native')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'native')
    a.lw(9, 8, 12); a.lw(10, 28, -22396); a.branch(5, 9, 10, 'native')
    # Both negative destinations request no transfer; retain the native result.
    a.branch(1, 5, 1, 'inspect'); a.branch(1, 6, 0, 'native')
    a.label('inspect'); a.move(11, 0)
    a.li(8, 0x100000); a.r(0x2B, 9, 4, 8); a.branch(5, 9, 0, 'bad_entry')
    a.li(8, RAM_BYTES-12); a.r(0x2B, 9, 8, 4); a.branch(5, 9, 0, 'bad_entry')
    a.i(12, 9, 4, 3); a.branch(5, 9, 0, 'bad_entry')
    a.lw(11, 4, 8)
    a.li(8, 0x100000); a.r(0x2B, 9, 11, 8); a.branch(5, 9, 0, 'bad_row')
    a.li(8, RAM_BYTES-64); a.r(0x2B, 9, 8, 11); a.branch(5, 9, 0, 'bad_row')
    a.i(12, 9, 11, 3); a.branch(5, 9, 0, 'bad_row')
    for label, argument, length, fmt, pointer in (('image', 5, 8, 24, 56), ('palette', 6, 12, 28, 60)):
        a.branch(1, argument, 0, label+'_done')
        a.lw(12, 11, length); a.branch(4, 12, 0, label+'_done')
        # Native100738 stores a16-bit QWC without masking. Values beyond this
        # range corrupt the tag ID; nonmultiples also truncate native transfers.
        a.li(8, MAX_TRANSFER); a.r(0x2B, 9, 8, 12); a.branch(5, 9, 0, 'bad_length')
        a.i(12, 9, 12, 15); a.branch(5, 9, 0, 'bad_length')
        # BITBLTBUF's destination format is a six-bit field. Avoid guessing a
        # narrower list of valid native texture/depth formats.
        a.lw(13, 11, fmt); a.i(11, 9, 13, 64); a.branch(4, 9, 0, 'bad_format')
        a.lw(14, 11, pointer); a.li(8, 0x100000)
        a.r(0x2B, 9, 14, 8); a.branch(5, 9, 0, 'bad_pointer')
        a.i(12, 9, 14, 15); a.branch(5, 9, 0, 'bad_pointer')
        a.li(8, RAM_BYTES); a.r(0x2B, 9, 8, 14); a.branch(5, 9, 0, 'bad_pointer')
        a.r(0x2D, 15, 14, 12); a.r(0x2B, 9, 8, 15); a.branch(5, 9, 0, 'bad_pointer')
        a.label(label+'_done')
    a.jump('native')
    for name, reason in (('bad_entry', 1), ('bad_row', 2), ('bad_length', 3), ('bad_format', 4), ('bad_pointer', 5)):
        a.label(name); a.addiu(12, 0, reason); a.jump('rejected')
    a.label('rejected'); a.li(8, CONTROL); a.lw(9, 8, 16); a.addiu(9, 9, 1)
    a.sw(9, 8, 16); a.sw(4, 8, 20); a.sw(11, 8, 24); a.sw(12, 8, 28)
    for reg, off in SAVED: a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x40); a.move(2, 0); a.jr()
    a.label('native')
    for reg, off in SAVED: a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x40); safety.native_tail(a, HOOK, original)
    result = a.finish(); assert CODE+len(result) < CONTROL; return result


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != RAM_BYTES: raise ValueError('Requires128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count, queue = u(core.ACTORS), u(core.MODE+4), u(QUEUE)
    if (not 0x100000 <= manager < len(ram)-0x1000 or u(manager) != 2
            or u(core.MODE) != 1 or u(core.MODE+8) != manager
            or count not in ACTOR_COUNTS or u(core.MODE+12) != count):
        raise ValueError('Captured active4/6 match required')
    if not 0x100000 <= queue <= len(ram)-2060: raise ValueError('Native effect texture queue required')
    _, _, native = elf_reader(elf_path(ROOT))
    if ram[HOOK:HOOK+0x118] != native(HOOK, 0x118): raise ValueError('Native effect upload routine changed')
    if ram[A(0x100738):A(0x100788)] != native(A(0x100738), 0x50): raise ValueError('Native DMA REF builder changed')
    if any(ram[CODE:END]): raise ValueError('Effect texture guard reservation occupied')
    control = bytearray(0x40); struct.pack_into('<4I', control, 0, 1, manager, count, queue)
    pieces = [(CODE, payload(native(HOOK, 8))), (CONTROL, bytes(control)),
              (HOOK, struct.pack('<2I', (2<<26)|(CODE>>2), 0))]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                blocks=[dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex()) for p, d in pieces],
                control=CONTROL, status='CAPTURED EFFECT TEXTURE UPLOAD VALIDATION',
                telemetry=dict(rejected=CONTROL+16, last_entry=CONTROL+20, last_row=CONTROL+24, reason=CONTROL+28),
                limitations=['Drops a whole effect texture upload when any requested component is invalid.',
                             'Does not reclaim surviving effects or recover an already halted DMA channel.',
                             'Native valid uploads and inactive or differently owned matches retain their original path.'])


def build(source): return build_memory(read_ram(source), source=source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args(); result = build(x.source)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
