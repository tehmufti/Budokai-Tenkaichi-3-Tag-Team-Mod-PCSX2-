"""Use native shared leader dialogue cameras only during a held replay intro.

Combat participant filtering is appropriate for unrelated concurrent specials,
but rejects the second leader's opening line in a player-one view. The native
selector binds the current dialogue camera after selecting the normal view.
This wrapper preserves the existing result/combat chain outside intro phases1/2.
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
import cinematic_camera_state as state
import result_presentation as result
import team_intro as intro
import team_start_gate as start
from battle_mode_policy import ACTOR_COUNTS

CODE, TRAMPOLINE, CONTROL, END = 0x07432000, 0x07432C00, 0x07432D00, 0x07433000
SAVED = (2, 3, 8, 9, 10, 11)


def payload(previous):
    a = Assembler(CODE); a.addiu(29, 29, -0x30)
    for i, r in enumerate(SAVED): a.i(63, r, 29, i*8)
    core.gate(a, 'previous')
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'previous')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'previous')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'previous')
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'previous')
    a.li(8, result.RESULT); a.lw(8, 8); a.branch(5, 8, 0, 'previous')
    a.li(8, intro.CONTROL); a.addiu(3, 0, 1)
    a.lw(9, 8); a.branch(5, 9, 3, 'previous')
    a.lw(9, 8, 4); a.branch(4, 9, 0, 'previous')
    a.lw(9, 8, 8); a.branch(5, 9, 11, 'previous')
    a.lw(9, 8, 12); a.branch(5, 9, 10, 'previous')
    a.lw(9, 8, 20); a.branch(5, 9, 3, 'previous')
    a.lw(9, 8, 16); a.li(8, intro.BATTLE); a.lw(8, 8)
    a.branch(4, 8, 0, 'previous'); a.branch(5, 8, 9, 'previous')
    a.lw(9, 8); a.addiu(9, 9, -1); a.i(11, 9, 9, 2)
    a.branch(4, 9, 0, 'previous')
    a.li(8, start.CONTROL); a.lw(9, 8); a.branch(5, 9, 3, 'previous')
    a.lw(9, 8, 8); a.branch(5, 9, 11, 'previous')
    a.lw(9, 8, 4); a.branch(5, 9, 0, 'previous')
    a.lw(9, 8, 20); a.branch(5, 9, 0, 'previous')
    a.li(8, CONTROL); a.lw(9, 8, 16); a.addiu(9, 9, 1); a.sw(9, 8, 16)
    for i, r in enumerate(SAVED): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30); a.jump(camera.LEADER_NATIVE)
    a.label('previous')
    for i, r in enumerate(SAVED): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30); a.jump(previous)
    data = a.finish(); assert len(data) < TRAMPOLINE-CODE; return data


def build_memory(ram, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if count not in ACTOR_COUNTS or u(core.MODE) != 1 or u(core.MODE+8) != manager or u(core.MODE+12) != count:
        raise ValueError('Requires an active captured4/6 team')
    if any(ram[CODE:END]): raise ValueError('Intro camera reservation occupied')
    if (u(intro.CONTROL) != 1 or u(intro.CONTROL+8) != manager or u(intro.CONTROL+12) != count
            or u(intro.CONTROL+20) not in (0, 1) or u(intro.CONTROL+16) != u(intro.BATTLE)):
        raise ValueError('Requires the captured unreleased replay intro')
    if u(start.CONTROL) != 1 or u(start.CONTROL+8) != manager or u(start.REQUEST) or u(start.CONTROL+20):
        raise ValueError('Requires the input start gate still held')
    _, _, native = elf_reader(elf_path(ROOT))
    expected_native = native(A(0x23EFF0), 8)+struct.pack('<2I',(2<<26)|(A(0x23EFF8)>>2),0)
    if ram[camera.LEADER_NATIVE:camera.LEADER_NATIVE+16] != expected_native:
        raise ValueError('Native camera trampoline changed')
    if ram[A(0x23EFF8):A(0x23F0B0)] != native(A(0x23EFF8), 0xB8):
        raise ValueError('Native camera selection changed')
    if ram[state.CODE:state.CODE+len(state.wrapper())] != state.wrapper():
        raise ValueError('Complete camera state wrapper differs')
    if ram[A(0x23EFF0):A(0x23EFF8)] != struct.pack('<2I',(2<<26)|(state.CODE>>2),0):
        raise ValueError('Camera entry chain differs')
    old_scope = camera.scope(camera.LEADER, camera.LEADER_INNER, camera.LEADER_NATIVE)
    existing = ram[camera.LEADER:camera.LEADER+len(old_scope)]
    result_jump = struct.pack('<2I',(2<<26)|(result.SELECTOR>>2),0)
    extra = []
    if existing == old_scope:
        previous = TRAMPOLINE
        extra.append((TRAMPOLINE, old_scope[:8]+struct.pack('<2I',(2<<26)|((camera.LEADER+8)>>2),0)))
    elif existing == result_jump+old_scope[8:]:
        expected = result.wrapper(result.SELECTOR, camera.LEADER, camera.LEADER_NATIVE, old_scope[:8], 20)
        if ram[result.SELECTOR:result.SELECTOR+len(expected)] != expected:
            raise ValueError('Result camera wrapper changed')
        previous = result.SELECTOR
    else: raise ValueError('Unknown camera scope chain')
    control = bytearray(0x100); struct.pack_into('<3I', control, 0, 1, manager, count)
    pieces = extra+[(CODE,payload(previous)),(CONTROL,bytes(control)),
                     (camera.LEADER,struct.pack('<2I',(2<<26)|(CODE>>2),0))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),
        status='NATIVE INTRO CAMERA HANDOFF; LIVE BOTH-SPEAKER CHECK REQUIRED',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces],
        control=CONTROL,previous=previous,telemetry={'native_intro_views':CONTROL+16},
        behavior=['Only held captured intro phases1/2 use native shared cinematic/priority camera selection.',
                  'Cinematic time advances once; existing complete camera state binding remains in place.',
                  'Combat, result, actor positions, animations, targets and resource ownership are unchanged.'])


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    x=p.parse_args(); manifest=build_memory(read_ram(x.source),x.source)
    x.out.write_text(json.dumps(manifest,indent=2)+'\n');print(f'{x.out}: {len(manifest["blocks"])} blocks')
