"""In-game overhead health bars for captured four/six fighter matches.

Native render callsites 12B8DC/12BADC each finish one world viewport. Wrapping
their 102708 call keeps the active camera and GS scissor correct in split view.
1210D8 projects the actual model's head; 100878/100890 submit ordinary GS
sprites, so bars are part of the game output, not a desktop overlay.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import math
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
from battle_mode_policy import ACTOR_COUNTS
from regional import DISPLAY_H, Y_ORIGIN

HOOKS = (A(0x12B8DC), A(0x12BADC))
CODE, DRAW, RECT = 0x073DA000, 0x073DA200, 0x073DC000
TEMPLATE, CONTROL = 0x073DE000, 0x073DF000
CAMERA = A(0x2FEBD0)
WIDTH, HEIGHT, GAP = 48, 5, 14
HEAD_LIFT = 3.0  # native world units; negative Y is above the fighter
COLORS = (0x80FFBC48, 0x804878FF)  # GS ABGR: blue / red
SAVED = tuple((r, (r-16)*8) for r in range(16, 24))+((31, 0x40),)


def wrapper():
    a = Assembler(CODE); a.addiu(29, 29, -0x20); a.i(63, 31, 29, 0)
    a.call(A(0x102708)); a.i(63, 2, 29, 8); a.call(DRAW)
    a.i(55, 2, 29, 8); a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20); a.jr()
    return a.finish()


def valid_pointer(a, reg, fail, tail=0x200):
    a.li(8, 0x100000); a.r(0x2B, 9, reg, 8); a.branch(5, 9, 0, fail)
    a.li(8, 0x08000000-tail); a.r(0x2B, 9, reg, 8); a.branch(4, 9, 0, fail)


def draw_code(hide_view_subject=False, visibility_filter=None, entry=None):
    a = Assembler(DRAW if entry is None else entry); a.addiu(29, 29, -0xC0)
    for r, off in SAVED: a.i(63, r, 29, off)
    core.gate(a, 'return'); a.move(17, 10)
    a.li(16, CONTROL); a.lw(8, 16); a.branch(4, 8, 0, 'return')
    a.lw(8, 16, 4); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'return')
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'return')
    a.lw(19, 28, -22176); valid_pointer(a, 19, 'return', 0x300)
    # Only the native display's inclusive 512x448 (European 512x512) viewport bounds are accepted.
    for off, upper in ((512, 512), (516, 512), (520, DISPLAY_H), (524, DISPLAY_H)):
        a.lw(8, 19, off); a.i(11, 9, 8, upper); a.branch(4, 9, 0, 'return')
    for lo, hi in ((512, 516), (520, 524)):
        a.lw(8, 19, lo); a.lw(9, 19, hi); a.r(0x2B, 8, 8, 9); a.branch(4, 8, 0, 'return')
    a.lw(8, 16, 8); a.addiu(8, 8, 1); a.sw(8, 16, 8)
    a.sw(19, 16, 20)
    a.call(A(0x120AB0)); a.addiu(4, 19, 320); a.call(A(0x120B80))
    a.move(18, 0)
    a.label('actor')
    a.r(0x2B, 8, 18, 17); a.branch(4, 8, 0, 'finish')
    if visibility_filter is not None:
        # Optional late display policy; a0 physical fighter / a1 active camera.
        # The original emission remains byte-identical when no policy is set.
        a.move(4, 18); a.move(5, 19); a.call(visibility_filter)
        a.branch(4, 2, 0, 'next')
    if hide_view_subject:
        # The installed camera bridge records actual model subjects for each
        # native viewport. It can be a surviving NPC after a human is defeated.
        import fresh_team_camera as camera
        a.li(8, camera.SUCCESSOR_CONTROL); a.lw(9, 8, 8)
        a.lw(10, 19, 512); a.branch(4, 10, 0, 'bar_view_ready')
        a.lw(9, 8, 12)
        a.label('bar_view_ready'); a.branch(4, 18, 9, 'next')
    a.li(8, core.POINTERS); a.r(0, 9, 0, 18, 2); a.r(0x2D, 8, 8, 9); a.lw(20, 8)
    valid_pointer(a, 20, 'next', 0x1600)
    a.lw(8, 20); a.branch(5, 8, 18, 'next')
    a.lw(8, 20, 0x994); a.i(11, 9, 8, 5); a.branch(4, 9, 0, 'next')
    a.r(0, 9, 0, 8, 7); a.r(0, 10, 0, 8, 5); a.r(0x2D, 9, 9, 10)
    a.r(0, 10, 0, 8, 2); a.r(0x2D, 9, 9, 10); a.r(0x2D, 9, 9, 20)
    a.lw(21, 9, 0x9E4); a.lw(22, 9, 0x9E8)
    a.branch(6, 21, 0, 'next'); a.branch(6, 22, 0, 'next')
    a.li(8, 0x02000000); a.r(0x2B, 9, 22, 8); a.branch(4, 9, 0, 'next')
    a.r(0x2B, 8, 22, 21); a.branch(4, 8, 0, 'hp_ok'); a.move(21, 22)
    a.label('hp_ok')
    a.lw(8, 20, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, 'next')
    a.r(0, 9, 0, 8, 2); a.li(8, core.MODELS); a.r(0x2D, 8, 8, 9); a.lw(23, 8)
    valid_pointer(a, 23, 'next', 0x1670)
    for off in (4, 8):
        a.lw(8, 23, off); a.branch(4, 8, 0, 'next')
    a.lw(5, 23, 3436+48*4); a.branch(4, 5, 0, 'root_anchor')
    valid_pointer(a, 5, 'root_anchor', 0xE0); a.addiu(5, 5, 64); a.jump('project')
    a.label('root_anchor'); a.addiu(5, 23, 2416)
    a.label('project')
    a.addiu(4, 29, 0x80); a.addiu(6, 16, 0x80); a.call(A(0x121ED8))
    a.addiu(4, 29, 0x50); a.addiu(5, 29, 0x80); a.call(A(0x1210D8))
    a.branch(4, 2, 0, 'next'); a.lw(8, 29, 0x5C); a.branch(6, 8, 0, 'next')
    a.lw(8, 29, 0x58); a.branch(1, 8, 0, 'next')  # BLTZ projected depth
    # Check the actual head point before moving the bar above it.
    for coord, lo, hi, origin in ((0x50, 512, 516, 1792), (0x54, 520, 524, Y_ORIGIN)):
        a.lw(10, 29, coord)
        a.lw(8, 19, lo); a.addiu(8, 8, origin); a.r(0, 8, 0, 8, 4)
        a.r(0x2A, 9, 10, 8); a.branch(5, 9, 0, 'next')
        a.lw(8, 19, hi); a.addiu(8, 8, origin+1); a.r(0, 8, 0, 8, 4)
        a.r(0x2A, 9, 10, 8); a.branch(4, 9, 0, 'next')
    # Clamp complete rectangle inside the current viewport (including split gap).
    a.lw(10, 29, 0x50); a.addiu(10, 10, -(WIDTH//2)*16)
    a.lw(8, 19, 512); a.addiu(8, 8, 1793); a.r(0, 8, 0, 8, 4)
    a.r(0x2A, 9, 10, 8); a.branch(4, 9, 0, 'x_min'); a.move(10, 8)
    a.label('x_min'); a.lw(8, 19, 516); a.addiu(8, 8, 1792-WIDTH); a.r(0, 8, 0, 8, 4)
    a.r(0x2A, 9, 8, 10); a.branch(4, 9, 0, 'x_max'); a.move(10, 8)
    a.label('x_max'); a.sw(10, 29, 0x60)
    a.lw(10, 29, 0x54); a.addiu(10, 10, -GAP*16)
    a.lw(8, 19, 520); a.addiu(8, 8, Y_ORIGIN+1); a.r(0, 8, 0, 8, 4)
    a.r(0x2A, 9, 10, 8); a.branch(4, 9, 0, 'y_min'); a.move(10, 8)
    a.label('y_min'); a.lw(8, 19, 524); a.addiu(8, 8, Y_ORIGIN-HEIGHT); a.r(0, 8, 0, 8, 4)
    a.r(0x2A, 9, 8, 10); a.branch(4, 9, 0, 'y_max'); a.move(10, 8)
    a.label('y_max'); a.sw(10, 29, 0x64)
    a.lw(8, 20, 8); a.i(12, 8, 8, 1); a.r(0, 8, 0, 8, 2); a.r(0x2D, 8, 16, 8); a.lw(8, 8, 0x30); a.sw(8, 29, 0x6C)
    # floor(HP*48/max), bounded to 48 iterations with no hardware division.
    a.r(0, 8, 0, 21, 5); a.r(0, 9, 0, 21, 4); a.r(0x2D, 8, 8, 9); a.move(10, 0)
    a.label('ratio'); a.r(0x2B, 9, 8, 22); a.branch(5, 9, 0, 'ratio_done')
    a.r(0x23, 8, 8, 22); a.addiu(10, 10, 1); a.jump('ratio')
    a.label('ratio_done'); a.branch(5, 10, 0, 'nonzero'); a.addiu(10, 0, 1)
    a.label('nonzero'); a.r(0, 10, 0, 10, 4); a.sw(10, 29, 0x68)
    # One pixel dark outline, gray empty track, then team-colored health.
    for style in range(3):
        a.lw(4, 29, 0x60); a.lw(5, 29, 0x64)
        a.addiu(6, 4, WIDTH*16); a.addiu(7, 5, HEIGHT*16)
        if style == 0:
            a.addiu(4, 4, -16); a.addiu(5, 5, -16); a.addiu(6, 6, 16); a.addiu(7, 7, 16); a.li(8, 0x80060606)
        elif style == 1: a.li(8, 0x80404040)
        else:
            a.lw(8, 29, 0x68); a.r(0x2D, 6, 4, 8); a.lw(8, 29, 0x6C)
        a.call(RECT)
    a.lw(8, 16, 12); a.addiu(8, 8, 1); a.sw(8, 16, 12)
    a.r(0, 9, 0, 18, 2); a.r(0x2D, 9, 16, 9); a.lw(8, 9, 0x40); a.addiu(8, 8, 1); a.sw(8, 9, 0x40)
    a.label('next'); a.addiu(18, 18, 1); a.jump('actor')
    a.label('finish'); a.call(A(0x120AC8))
    a.label('return')
    for r, off in SAVED: a.i(55, r, 29, off)
    a.addiu(29, 29, 0xC0); a.jr()
    result = a.finish(); assert len(result) <= RECT-DRAW; return result


def rectangle_code():
    a = Assembler(RECT); a.addiu(29, 29, -0x40)
    for i, reg in enumerate((16, 17, 18, 19, 20, 31)): a.i(63, reg, 29, i*8)
    for dst, src in zip(range(16, 21), range(4, 9)): a.move(dst, src)
    a.call(A(0x100878)); a.li(8, TEMPLATE)
    for off in range(0, 128, 4): a.lw(9, 8, off); a.sw(9, 2, off)
    a.sw(20, 2, 80)
    a.r(0, 8, 0, 17, 16); a.r(0x25, 8, 8, 16); a.sw(8, 2, 112)
    a.r(0, 8, 0, 19, 16); a.r(0x25, 8, 8, 18); a.sw(8, 2, 120)
    a.addiu(4, 2, 128); a.call(A(0x100890))
    for i, reg in enumerate((16, 17, 18, 19, 20, 31)): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x40); a.jr(); return a.finish()


def sprite_template():
    return struct.pack('<16Q', 0x1000000000000005, 14, 68, 66, 196608, 71,
                       0, 74, 70, 0, 0x3F80000000000000, 1,
                       0x2400000000008001, 85, 0, 0)


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE memory')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if not 0x100000 <= manager < len(ram)-16 or u(manager) != 2: raise ValueError('Invalid captured native actor manager')
    if u(core.MODE) != 1 or u(core.MODE+8) != manager or u(core.MODE+12) != count or count not in ACTOR_COUNTS:
        raise ValueError('Install after captured4/6 fighter activation')
    for i in range(count):
        actor = u(core.POINTERS+i*4)
        if not 0x100000 <= actor < len(ram)-0x1600 or u(actor) != i: raise ValueError('Physical fighter table mismatch')
        mid = u(actor+12)
        if mid >= 12 or not u(core.MODELS+4*mid): raise ValueError('Actual model mapping missing')
    if any(ram[CODE:CONTROL+0x100]): raise ValueError('Health-bar code reservation occupied')
    _, _, native = elf_reader(elf_path(ROOT))
    for hook in HOOKS:
        if ram[hook:hook+8] != native(hook, 8): raise ValueError(f'Render callsite changed at{hook:08X}')
        if u(hook) != (3<<26)|(A(0x102708)>>2): raise ValueError('Unexpected native world render call')
    control = bytearray(0x100); struct.pack_into('<2I', control, 0, 1, manager); struct.pack_into('<2I', control, 0x30, *COLORS)
    struct.pack_into('<4f', control, 0x80, 0, HEAD_LIFT, 0, 0)
    pieces = [(CODE, wrapper(), 'Native per-viewport render call plus overhead bars'),
              (DRAW, draw_code(), 'Captured fighter head projection and viewport-safe health bars'),
              (RECT, rectangle_code(), 'Untextured GS sprite using native DMA packet submission'),
              (TEMPLATE, sprite_template(), 'Native101878-compatible sprite GIF packet'),
              (CONTROL, bytes(control), 'Enabled,captured manager,draw counters and team colors')]
    pieces += [(h, struct.pack('<I', (3<<26)|(CODE>>2)), 'Render one health-bar pass for this active camera') for h in HOOKS]
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex(), purpose=w) for p, d, w in pieces]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
                control=CONTROL, status='IN-GAME OVERHEAD HEALTH BARS',
                telemetry=dict(view_passes=CONTROL+8, bars=CONTROL+12, camera=CONTROL+20, per_actor=CONTROL+0x40),
                limitations=['Bars intentionally draw through scenery; behind-camera and offscreen fighters are skipped.',
                             'Only the currently active roster HP row is shown; dead fighters have no bar.'])


def build(source): return build_memory(read_ram(source), source=source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True); x = p.parse_args()
    result = build(x.source); x.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'{x.out}: {len(result["blocks"])} guarded blocks')
