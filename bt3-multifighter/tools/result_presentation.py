"""Return camera/body presentation to native result actors after team defeat.

Battle successor cameras intentionally follow surviving extras. Native result
scripts still request actions2/3 on original actors0/1. Hand back only after
the native result contains winner1/2; retain all combat behavior beforehand.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import fresh_team_camera as camera
from battle_mode_policy import ACTOR_COUNTS

GATE, SUBJECT, SELECTOR, BODY = 0x07404000, 0x07404500, 0x07404800, 0x07404B00
CONTROL, END, RESULT = 0x07404F00, 0x07405000, A(0x333700)
SAVED = (2, 3, 8, 9, 10, 11, 31)


def gate():
    a = Assembler(GATE)
    core.gate(a, 'no')
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'no')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'no')
    a.li(8, RESULT); a.lw(9, 8)
    # Exclude draw/abort/special result flags; only native winner1 or2.
    a.addiu(9, 9, -1); a.i(11, 9, 9, 2); a.branch(4, 9, 0, 'no')
    a.addiu(2, 0, 1); a.jr()
    a.label('no'); a.move(2, 0); a.jr()
    return a.finish()


def wrapper(base, entry, target, original, counter, subject=False):
    a = Assembler(base); a.addiu(29, 29, -0x40)
    for i, r in enumerate(SAVED): a.i(63, r, 29, 8*i)
    a.call(GATE); a.branch(4, 2, 0, 'fallback')
    if subject:
        a.i(11, 9, 4, 2); a.branch(4, 9, 0, 'fallback')
        a.li(8, camera.SUCCESSOR_CONTROL)
        a.r(0, 9, 0, 4, 2); a.r(0x2D, 8, 8, 9)
        # Native cinematic participation and HUD camera ownership agree with
        # the native result actor, including when that leader was defeated.
        a.sw(4, 8, 8)
    a.li(8, CONTROL); a.lw(9, 8, counter); a.addiu(9, 9, 1); a.sw(9, 8, counter)
    for i, r in enumerate(SAVED): a.i(55, r, 29, 8*i)
    a.addiu(29, 29, 0x40); a.jump(target)
    a.label('fallback')
    for i, r in enumerate(SAVED): a.i(55, r, 29, 8*i)
    a.addiu(29, 29, 0x40)
    for w in struct.unpack('<2I', original): a.emit(w)
    a.jump(entry+8)
    data = a.finish(); assert len(data) <= 0x300
    return data


def program(manager, count):
    entries = (
        (SUBJECT, camera.SUCCESSOR, camera.successor.NATIVE,
         camera.scope(camera.SUCCESSOR, camera.SUCCESSOR_INNER, camera.successor.NATIVE), 16, True),
        (SELECTOR, camera.LEADER, camera.LEADER_NATIVE,
         camera.scope(camera.LEADER, camera.LEADER_INNER, camera.LEADER_NATIVE), 20, False),
        (BODY, camera.BODY, camera.BODY_NATIVE,
         camera.scope(camera.BODY, camera.BODY_INNER, camera.BODY_NATIVE), 24, False),
    )
    control = bytearray(0x100); struct.pack_into('<3I', control, 0, 1, manager, count)
    parts = [(GATE, gate()), (CONTROL, bytes(control))]
    for base, entry, target, old, counter, subject in entries:
        parts += [(base, wrapper(base, entry, target, old[:8], counter, subject)),
                  (entry, struct.pack('<2I', (2<<26)|(base>>2), 0))]
    return parts, entries


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('128MiB EE RAM required')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(core.ACTORS); count = len(config['actors']) if config else u(core.MODE+4)
    if (count not in ACTOR_COUNTS or not 0x100000 <= manager < len(ram)-0x1000
            or u(manager) != 2 or u(core.MODE+8) != manager or u(core.MODE+12) != count):
        raise ValueError('Captured native two-row4/6 match required')
    if any(ram[GATE:END]): raise ValueError('Result presentation reservation occupied')
    parts, entries = program(manager, count)
    for _, entry, _, old, _, _ in entries:
        if ram[entry:entry+len(old)] != old: raise ValueError(f'Existing camera/body scope changed:{entry:X}')
    _, _, native = elf_reader(elf_path(ROOT))
    if ram[camera.LEADER_NATIVE:camera.LEADER_NATIVE+8] != native(A(0x23EFF0), 8):
        raise ValueError('Native camera fallback changed')
    if ram[camera.BODY_NATIVE:camera.BODY_NATIVE+20] != native(A(0x1E0290), 20):
        raise ValueError('Native body request fallback changed')
    blocks = [dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex()) for p, b in parts]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
        status='NATIVE RESULT CAMERA AND BODY HANDOFF; LIVE PRESENTATION VALIDATION REQUIRED', control=CONTROL,
        telemetry=dict(subject_handoffs=CONTROL+16, selector_handoffs=CONTROL+20, body_handoffs=CONTROL+24),
        evidence=['Native209F58/209F90 flag original actors for result actions2/3.',
                  'Native23EFF0 retains result priority/cinematic selection; combat successor no longer overrides it.'],
        limitations=['Winner presentation still uses its original native leader, including a defeated leader on the winning team.',
                     'This changes neither winner selection nor fighter HP, positions, or result animation resources.'])


def build(source): return build_memory(read_ram(source), source=source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True); args = p.parse_args()
    result = build(args.source); args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'{args.out}: {len(result["blocks"])} guarded blocks')
