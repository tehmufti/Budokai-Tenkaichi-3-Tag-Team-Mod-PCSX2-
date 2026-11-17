"""Team chips and exact row counts on the native Team Select, for Team Battle with three to five teams.

Both parts read the team setup's receipt in the pager control (squad_setup: SQUAD_VALID = the committed choice,
SQUAD_ROWS = fighters per row, SQUAD_TEAM_OF = the team of each slot) and do nothing without it, so every other
selection, the two-team Team Battle included, is untouched.

GUARD (called from the pager's pad wrapper next to roster_selection_guard, a0 = the original pad caller): END on a
row is refused with the native reject sound until that row holds exactly the planned number of fighters, because
the teams are laid out on the slots before anything is picked.

DRAW (called from the selector's draw hook next to the player badges): a small chip in the team's colour with the
team's number beside each slot's player badge on the slot overview. The chips are drawn with a built-in digit
bitmap, never a font, so their packets are the same on every system.
"""
import struct
from functools import lru_cache

import battle_mode_policy as policy
import coop_character_select as selector
import mode_menu
import roster_selection_guard as guard
from native_map import A, GPO
from prototype import Assembler
from regional import MENU_ACCEPT

GUARD, DRAW, DATA, END = 0x06642000, 0x06643000, 0x06644000, 0x06660000
CONTROL, MAGIC = guard.CONTROL, guard.MAGIC
VALID, ROWS, TEAM_OF = 0x160, 0x164, 0x168                    # native_mode_menu.SQUAD_VALID / _ROWS / _TEAM_OF
SOUND = guard.SOUND
CHIP = (24, 13)                                                # pixels
DIGITS = {1: ('010', '110', '010', '010', '111'), 2: ('111', '001', '111', '100', '111'),
          3: ('111', '001', '111', '001', '111'), 4: ('101', '101', '111', '001', '001'),
          5: ('111', '100', '111', '001', '111')}


def guard_code():
    a = Assembler(GUARD)
    # The battle and menu pad path pays a caller check and three temporary saves, as the roster guard does.
    a.addiu(29, 29, -0x30)
    for i, r in enumerate((8, 9, 10)): a.i(31, r, 29, i*16)
    a.li(8, guard.CALLER); a.branch(5, 4, 8, 'quick_done')
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'quick_done')
    a.lw(9, 8, VALID); a.branch(4, 9, 0, 'quick_done')
    a.lw(10, 8, guard.CHOICE); a.branch(5, 9, 10, 'quick_done')
    for i, r in enumerate((8, 9, 10)): a.i(30, r, 29, i*16)
    a.addiu(29, 29, 0x30); a.jump('inspect')
    a.label('quick_done')
    for i, r in enumerate((8, 9, 10)): a.i(30, r, 29, i*16)
    a.addiu(29, 29, 0x30); a.jr()
    a.label('inspect'); guard.save(a)
    a.li(8, mode_menu.SCENE_MANAGER); a.lw(8, 8); guard.pointer(a, 8, 0x20)
    a.lw(9, 8, 0x18); a.addiu(10, 0, 40); a.branch(5, 9, 10, 'done')
    for p, word in guard.SIGNATURES.items():
        a.li(8, p); a.lw(9, 8); a.li(10, word); a.branch(5, 9, 10, 'done')
    a.li(8, guard.TEAM_OBJECT); a.lw(11, 8); guard.pointer(a, 11, 0x3F00)
    a.lw(9, 11, 0x3C); a.i(12, 9, 9, 2); a.branch(4, 9, 0, 'done')
    a.lw(14, 11, 0x3C58); a.i(11, 9, 14, 2); a.branch(4, 9, 0, 'done')          # the row being filled
    a.r(0, 9, 0, 14, 2); a.r(0x21, 9, 9, 11); a.lw(12, 9, 0x8E8); guard.pointer(a, 12, 0x200)
    a.lw(9, 12, 0x13C); a.addiu(10, 0, 6); a.branch(5, 9, 10, 'done')             # the slot overview
    a.lw(9, 12, 0x12C); a.addiu(10, 0, 5); a.branch(5, 9, 10, 'done')             # the cursor is on END
    a.li(8, CONTROL+ROWS); a.r(0x21, 8, 8, 14); a.i(36, 15, 8, 0)
    a.lw(9, 12, 0x134); a.branch(4, 9, 15, 'done')                                # exactly the planned fighters
    a.li(11, mode_menu.PAD); a.lw(9, 11, 0x18C); a.i(12, 10, 9, MENU_ACCEPT)
    a.branch(4, 10, 0, 'done'); a.li(10, 0xFFFFFFFF & ~MENU_ACCEPT); a.r(0x24, 9, 9, 10); a.sw(9, 11, 0x18C)
    a.addiu(4, 0, 1); a.addiu(5, 0, 7); a.call(SOUND)
    a.label('done'); guard.restore(a); a.jr()
    data = a.finish(); assert GUARD+len(data) <= DRAW; return data


def chip_picture(side, slot, team):
    """The chip of one slot on the 512 x 448 menu surface (magenta = not drawn)."""
    from PIL import Image
    key = (255, 0, 255); dark = (18, 25, 42)
    im = Image.new('RGB', (512, 448), key); px = im.load()
    x0 = slot*64+62; y0 = 12 if side == 0 else 356
    w, h = CHIP; color = policy.TEAM_RGB[team]
    for y in range(h):
        for x in range(w):
            edge = x in (0, w-1) or y in (0, h-1)
            corner = (x in (0, w-1)) and (y in (0, h-1))
            if not corner: px[x0+x, y0+y] = dark if edge else color
    rows = DIGITS[team+1]
    for gy, row in enumerate(rows):
        for gx, bit in enumerate(row):
            if bit == '1':
                for dy in (0, 1):
                    for dx in (0, 1):
                        px[x0+9+gx*2+dx, y0+2+gy*2-0+dy-0] = dark
    return im, key


@lru_cache(maxsize=1)
def packets():
    import guest_loading_screen as gs
    out = []
    for side in range(2):
        for slot in range(policy.TEAM_CAPACITY):
            for team in range(policy.MAX_TEAMS):
                im, key = chip_picture(side, slot, team)
                out.append(gs.gif_packet(gs.image_rectangles(im, key=key)))
    return tuple(out)


def data():
    blobs = packets(); offset = DATA+len(blobs)*8; table = bytearray()
    for blob in blobs:
        table += struct.pack('<2I', offset, len(blob)); offset += len(blob)
    out = bytes(table)+b''.join(blobs)
    assert DATA+len(out) <= END and all(len(blob) % 16 == 0 for blob in blobs)
    return out


def draw_code():
    a = Assembler(DRAW); guard.save(a)
    selector.scope(a, drawing=True, require_enabled=False, all_selectors=True)
    a.li(8, CONTROL); a.lw(9, 8, VALID); a.branch(4, 9, 0, 'done')
    a.lw(10, 8, guard.CHOICE); a.branch(5, 9, 10, 'done')
    # Only the slot overview of a row, never the scrolling character gallery (as the player badges).
    a.move(16, 0); a.label('side'); a.li(8, guard.TEAM_OBJECT); a.lw(8, 8)
    a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8, 0x8E8)
    selector.pointer(a, 8, 0x200)
    a.lw(9, 8, 0x13C); a.addiu(10, 0, 6); a.branch(5, 9, 10, 'next_side')
    a.move(17, 0); a.label('slot')
    a.r(0, 18, 0, 17, 1); a.r(0x21, 18, 18, 16)                                   # physical = 2 * slot + row
    a.li(8, CONTROL+TEAM_OF); a.r(0x21, 8, 8, 18); a.i(36, 19, 8, 0)
    a.i(11, 9, 19, policy.MAX_TEAMS); a.branch(4, 9, 0, 'no_chip')
    a.r(0, 8, 0, 16, 2); a.r(0x21, 8, 8, 16); a.r(0x21, 8, 8, 17)                 # row * 5 + slot
    a.r(0, 9, 0, 8, 2); a.r(0x21, 8, 8, 9); a.r(0x21, 8, 8, 19); a.r(0, 8, 0, 8, 3)
    a.li(9, DATA); a.r(0x21, 8, 8, 9); a.lw(20, 8); a.lw(21, 8, 4)
    # The checked arena contract of the player badges (player_slot_labels).
    a.lw(8, 28, -23004); a.i(11, 9, 8, 2); a.branch(4, 9, 0, 'done')
    a.r(0, 8, 0, 8, 2); a.r(0x2D, 8, 28, 8)
    a.lw(9, 8, GPO(-23024)); a.lw(10, 8, GPO(-23016)); a.lw(11, 28, -23008)
    a.r(0x2D, 11, 11, 9); a.branch(5, 11, 10, 'done')
    a.lw(11, 28, -23000); a.r(0x2B, 12, 11, 9); a.branch(5, 12, 0, 'done')
    a.r(0x2D, 12, 11, 21); a.addiu(12, 12, 64); a.r(0x2B, 13, 12, 11); a.branch(5, 13, 0, 'done')
    a.r(0x2B, 13, 10, 12); a.branch(5, 13, 0, 'done')
    a.call(A(0x100878)); a.r(0x21, 9, 20, 21); a.move(10, 2)
    a.label('copy')
    for off in (0, 8): a.i(55, 11, 20, off); a.i(63, 11, 10, off)
    a.addiu(20, 20, 16); a.addiu(10, 10, 16); a.branch(5, 20, 9, 'copy')
    a.move(4, 10); a.call(A(0x100890))
    a.label('no_chip'); a.addiu(17, 17, 1); a.addiu(8, 0, policy.TEAM_CAPACITY); a.branch(5, 17, 8, 'slot')
    a.label('next_side'); a.addiu(16, 16, 1); a.addiu(8, 0, 2); a.branch(5, 16, 8, 'side')
    a.label('inactive'); a.label('done'); guard.restore(a); a.jr()
    out = a.finish(); assert DRAW+len(out) <= DATA; return out


def code_pieces():
    return [(GUARD, guard_code()), (DRAW, draw_code()), (DATA, data())]
