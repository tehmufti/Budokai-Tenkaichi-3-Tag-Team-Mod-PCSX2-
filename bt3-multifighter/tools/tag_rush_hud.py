"""Compact per-view tag meter beneath the normal fighter HUD.

The right-hand strip sits below either status-panel style and to the right of
compact fusion captions. Drawing reads captured identities; it never changes
fighter charge, invitations or input.
"""
import struct

from prototype import Assembler
from native_map import A
from regional import Y_ORIGIN, screen_y
import fresh_team_combat as core
import fresh_team_camera as camera
import team_participation as participation
import battle_mode_policy as modes
import viewport_hud as hud
import guest_killfeed as feed
import guest_healthbars as bars
import localization

BASE, END = 0x06D74000, 0x06D78000
DRAW, ALIVE, TEXT = BASE, BASE+0x1000, BASE+0x1800
CAPTION = BASE+0x2000
# The 'Tag attack meter' HUD setting (tag_team_rush_show_meter): 1 draws the meter, 0 hides it. Draw only, nothing
# else reads it: online each PC writes its own value into its copy (kit_settings LOCAL). A match built with the meter
# off installs no meter code at all (draw_code(meter=False)): its draw entry keeps only the beam-ending white fade.
SHOW, SHOW_KEY = TEXT+0x7F0, 'tag_team_rush_show_meter'
CONTROL, MAGIC = 0x06D08000, 0x54414731
METERS, METER_STRIDE = CONTROL+0x100, 32
WIDTH, MARGIN, LABEL_TOP, BAR_TOP, HEIGHT = 64, 8, 72, 80, 2
REGS, STACK = (*range(16, 24), 31), 0x70
LABEL, COMPACT_LABEL = 'TAG ATTACK', 'TAG'   # TEXT, TEXT+TEXT_STRIDE
TEXT_STRIDE = 32
BLUE, GOLD, BLACK = 0x80FFC050, 0x8050D8FF, 0x80000000
# One full view: just below the subject's own main gauge, under its middle third and right of the ki bars (mirrored
# for a right-hand status), in the native status of the subject's side (logical 512 x 448, the right one mirrored).
FULL_X, FULL_LABEL, LABEL_GAP = 123, 38, 9
# Split views: inside each view's own viewport_hud panel, in the empty space under its main gauge and right of its
# second row, mirrored for a right-facing panel. SPLIT_X/SPLIT_Y are the label's top-left and SPLIT_ROOM the free width,
# in units of the 256 x 64 native frame (atlas 6) as viewport_hud_art draws it: scaled to the panel, 3/4 as wide in
# anamorphic 16:9. The meter is that room wide, at most WIDTH px. Its label is at most the 75% it always had (6 units
# per kit atlas pixel); a narrower meter takes the first smaller size it fits (LABEL_UNITS: minimum meter px, units),
# below COMPACT_BELOW px the COMPACT_LABEL (smaller full labels were unreadable live). The bar sits 1.5 label sizes
# below the label's top (9 px at 75%).
SPLIT_X, SPLIT_Y, SPLIT_ROOM = 122, 30, 122    # BT3: right of the ki bars (frame rows 26+ are free from x 117)
LABEL_UNITS, COMPACT_BELOW = ((54, 6), (45, 5)), 45
# BT4's status has a second row under the main gauge's middle third (ki bars, the stock digit in its housing and the
# blast-stock gauge beside it, frame rows 20..46). One view: the meter goes beside the reserve portrait (x <= 109),
# below that row. Split panels: below the blast-stock gauge (frame 132..180 x 25..37), right of the digit housing.
import mod_settings as _settings   # the tree's adapter fact ('BT3' / 'BT4'); native_map maps BT4 to bt3-usa
if _settings.ADAPTER == 'BT4':
    FULL_X, FULL_LABEL = 111, 66
    SPLIT_X, SPLIT_Y, SPLIT_ROOM = 140, 40, 100
SPLIT_SLOT = 0x58     # stack word: split view index + 1 (0 = one full view)
METER_W, UNITS, LABEL_AT = 0x64, 0x68, 0x6C   # stack words: meter width (px), label size (units), label address
OWN_PASSES = 4        # an own-panel record from this many HUD passes ago is still the current layout


def split_panel(view, column, settings, coop, views=2, wide=False):
    """(x, y, width, faces_right) of a split view's own status panel, as viewport_hud.post_code places it.
    settings: viewport_hud_art.SETTINGS words (native style, portraits, sparks, coop targets, trail, scale, filter,
    top_bottom); coop: every view's subject is on one team; wide: anamorphic 16:9 (widescreen_support)."""
    x0, x1, y0, _y1 = view
    vw = x1-x0
    if settings[7] == 1:
        w = min(vw-2, 256); return (x0+1 if not column else x1-1-w), y0+2, w, bool(column)
    if settings[3] == 0 and coop:
        return x0+4, y0+5, vw-8, bool(column)
    fit = (vw-14) >> 1
    w = fit
    inset = 1 if views < 3 else 7          # post_code: 2 views x0+4 shifted 3 outward; 3/4 views (4:3) x0+7
    if settings[0] == 1:
        scale = settings[5] if 80 <= settings[5] <= 140 else 100
        limit = fit
        if views >= 3 and wide:
            limit, inset = 148, 4          # post_code (quad support): 16:9 3/4-view panels may grow to 148, inset 4
        w = min(limit, (((vw-11) >> 1)*scale)//100)
    return (x0+inset if not column else x1-inset-w), y0+2, w, bool(column)


def frame_units(value, w, wide=False):
    """Pixels of `value` native frame units across a panel w px wide (draw_code's integer arithmetic)."""
    return (value*w*3) >> 10 if wide else (value*w) >> 8


def meter(view, split=None, subject=0, settings=(1, 1, 1, 1, 15, 100, 1, 0), coop=False, views=2, wide=False, own=None):
    """The meter as draw_code computes it: dict(x, y (label top), bar (bar top), width, units, label).
    split: None (one full view) or the view index; units: kit units per atlas pixel (6 = 75% of the classic size);
    own: (x, y, width, mirrored, wide) of a recent viewport_hud_art.OWN record for this view, which wins."""
    x0, x1, y0, _y1 = view
    if split is None:
        x = x0+FULL_X if not subject & 1 else x1-FULL_X-WIDTH
        y = y0+screen_y(FULL_LABEL)
        return dict(x=x, y=y, bar=y+LABEL_GAP, width=WIDTH, units=6, label=LABEL)
    if settings[0] != 1:
        # Compact text panels (64 px tall, no gauge art): the strip right of the fusion captions, below both panels.
        y = y0+screen_y(LABEL_TOP)
        return dict(x=x1-MARGIN-WIDTH, y=y, bar=y+LABEL_GAP, width=WIDTH, units=6, label=LABEL)
    px, py, w, right = split_panel(view, split & 1, settings, coop, views, wide)
    if own is not None:
        px, py, w, right, wide = own
    m = panel_meter(w, right, wide)
    return dict(m, x=px+m['x'], y=py+m['y'], bar=py+m['bar'])


def panel_meter(w, right=False, wide=False):
    """meter() relative to the top-left of a native split panel w px wide (right: mirrored)."""
    width = min(WIDTH, frame_units(SPLIT_ROOM, w, wide))
    units, label = LABEL_UNITS[-1][1], LABEL
    for need, size in LABEL_UNITS:
        if width >= need:
            units = size; break
    if width < COMPACT_BELOW:
        label = COMPACT_LABEL
    off = frame_units(SPLIT_X, w, wide)
    x = off if not right else w-off-width
    y = (SPLIT_Y*w) >> 8
    return dict(x=x, y=y, bar=y+((3*units) >> 1), width=width, units=units, label=label)


def placement(view, **where):
    """(meter x, caption y, bar y) as draw_code computes them (see meter)."""
    m = meter(view, **where)
    return m['x'], m['y'], m['bar']


def rectangles(view, **where):
    """Design bounds used by layout checks (native coordinates, inclusive view). The caption box is its cap height
    (6.25 px at 75%) at most the meter wide: draw_code only picks a label size that fits the meter."""
    m = meter(view, **where)
    x, y, bar, width = m['x'], m['y'], m['bar'], m['width']
    return {'caption': (x, y, x+width, y+6.25*m['units']/6),
            'meter': (x-1, bar-1, x+width+1, bar+HEIGHT+1)}


def _frame_units(a, dest, value):
    """dest = frame_units(value, t2 = panel width, t8 = anamorphic 16:9); uses t9."""
    tag = f'frame_units_{a.pc:x}'
    a.addiu(dest, 0, value); a.r(24, 0, dest, 10); a.r(18, dest, 0)
    a.branch(4, 24, 0, tag)
    a.r(0, 25, 0, dest, 1); a.r(0x21, dest, dest, 25); a.r(2, dest, 0, dest, 2)
    a.label(tag); a.r(2, dest, 0, dest, 8)


def _place(a):
    """t-registers only (with t8/t9). s1 camera, s2 physical subject -> s5 meter x, s3 caption y, s6 bar y (pixels);
    the meter width, label size and label address in the METER_W / UNITS / LABEL_AT stack words."""
    import viewport_hud_art as art
    import widescreen_support as wide
    a.addiu(8, 0, WIDTH); a.sw(8, 29, METER_W); a.addiu(8, 0, 6); a.sw(8, 29, UNITS)
    a.li(8, TEXT); a.sw(8, 29, LABEL_AT)
    a.lw(8, 29, SPLIT_SLOT); a.branch(5, 8, 0, 'split_place')
    a.lw(19, 17, 520); a.addiu(19, 19, screen_y(FULL_LABEL))
    a.lw(21, 17, 512); a.addiu(21, 21, FULL_X)
    a.i(12, 9, 18, 1); a.branch(4, 9, 0, 'placed')
    a.lw(21, 17, 516); a.addiu(21, 21, -FULL_X-WIDTH); a.jump('placed')
    a.label('split_place')
    a.addiu(8, 8, -1); a.i(12, 13, 8, 1)                                    # t5 = column parity: faces right
    a.li(14, art.SETTINGS)
    a.lw(11, 14); a.addiu(12, 0, 1); a.branch(5, 11, 12, 'text_panel')
    # viewport_hud_art draws the frame 3/4 as wide in anamorphic 16:9: t8 = 1 there.
    a.move(24, 0); wide.emit_detection(a, 24, 'aspect_ready'); a.label('aspect_ready')
    a.lw(9, 17, 516); a.lw(10, 17, 512); a.r(0x23, 9, 9, 10)                # t1 = view width
    a.lw(11, 14, 28); a.addiu(12, 0, 1); a.branch(5, 11, 12, 'not_full_width')
    a.addiu(10, 9, -2); a.addiu(11, 0, 256); a.r(0x2A, 12, 11, 10); a.branch(4, 12, 0, 'fw_ready'); a.move(10, 11)
    a.label('fw_ready'); a.addiu(11, 0, 1); a.addiu(12, 0, 2); a.jump('panel_x')
    a.label('not_full_width')
    a.lw(11, 14, 12); a.branch(5, 11, 0, 'not_coop')
    # Co-op: every view's subject on one team (team parity of the captured physical subjects).
    a.li(11, hud.CONTROL); a.lw(11, 11, 12); a.li(12, hud.VIEWS); a.lw(15, 12, 20); a.lw(15, 15); a.i(12, 15, 15, 1)
    a.label('coop_scan'); a.branch(4, 11, 0, 'coop')
    a.li(10, hud.VIEWS); a.addiu(11, 11, -1)
    a.addiu(8, 0, hud.VIEW_STRIDE); a.r(24, 0, 11, 8); a.r(18, 8, 0); a.r(0x21, 10, 10, 8)
    a.lw(10, 10, 20); a.lw(10, 10); a.i(12, 10, 10, 1); a.branch(5, 10, 15, 'not_coop'); a.jump('coop_scan')
    a.label('coop')
    a.addiu(10, 9, -8); a.lw(21, 17, 512); a.addiu(21, 21, 4); a.addiu(12, 0, 5); a.jump('panel_y')
    a.label('not_coop')
    a.addiu(10, 9, -14); a.r(3, 10, 0, 10, 1)                               # t2 = fit = (vw-14) >> 1
    a.lw(11, 14, 20); a.addiu(12, 11, -80); a.i(11, 15, 12, 61); a.branch(5, 15, 0, 'scale_ok'); a.addiu(11, 0, 100)
    a.label('scale_ok')
    a.addiu(15, 9, -11); a.r(3, 15, 0, 15, 1); a.r(24, 0, 15, 11); a.r(18, 15, 0)
    a.addiu(11, 0, 100); a.r(27, 0, 15, 11); a.r(18, 15, 0)                # t7 = scaled width
    # Inset 1 (two views); 3/4 views 7, or in 16:9 4 with the width limit 148 instead of the fit (post_code).
    a.addiu(11, 0, 1)
    a.li(8, hud.CONTROL); a.lw(8, 8, 12); a.i(10, 8, 8, 3); a.branch(5, 8, 0, 'limit_ready')
    a.addiu(11, 0, 7); a.branch(4, 24, 0, 'limit_ready')
    a.addiu(11, 0, 4); a.addiu(10, 0, 148)
    a.label('limit_ready')
    a.r(0x2A, 12, 15, 10); a.branch(4, 12, 0, 'width_ready'); a.move(10, 15)
    a.label('width_ready'); a.addiu(12, 0, 2)
    a.label('panel_x')                                                      # t3 inset, t2 width
    a.lw(21, 17, 512); a.r(0x21, 21, 21, 11); a.branch(4, 13, 0, 'panel_y')
    a.lw(21, 17, 516); a.r(0x23, 21, 21, 11); a.r(0x23, 21, 21, 10)
    a.label('panel_y'); a.lw(19, 17, 520); a.r(0x21, 19, 19, 12)            # s5 panel x, s3 panel y
    # Where this view's own fighter panel was actually drawn by a recent HUD pass (viewport_hud_art.OWN) wins over
    # the layout rule above: the meter always sits beside that player's own HP, left or right, top or bottom.
    a.lw(8, 29, SPLIT_SLOT); a.addiu(8, 8, -1); a.r(0, 8, 0, 8, 4); a.li(9, art.OWN); a.r(0x21, 8, 8, 9)
    a.lw(9, 8, 8); a.branch(4, 9, 0, 'own_ready')
    a.li(11, hud.CONTROL); a.lw(11, 11, 20); a.lw(12, 8, 12); a.r(0x23, 11, 11, 12); a.i(11, 11, 11, OWN_PASSES)
    a.branch(4, 11, 0, 'own_ready')
    a.lw(21, 8); a.lw(19, 8, 4); a.i(12, 10, 9, 0xFFFF)
    a.r(2, 13, 0, 9, 16); a.i(12, 13, 13, 1); a.r(2, 24, 0, 9, 17); a.i(12, 24, 24, 1)
    a.label('own_ready')
    # The meter: SPLIT_ROOM wide (at most WIDTH), its label sized to fit it.
    _frame_units(a, 11, SPLIT_ROOM)
    a.addiu(8, 0, WIDTH); a.r(0x2A, 9, 11, 8); a.branch(5, 9, 0, 'room_ready'); a.move(11, 8)
    a.label('room_ready'); a.sw(11, 29, METER_W)
    a.addiu(12, 0, LABEL_UNITS[0][1])
    for (need, _size), (_next, smaller) in zip(LABEL_UNITS, LABEL_UNITS[1:]):
        a.i(10, 9, 11, need); a.branch(4, 9, 0, 'units_ready'); a.addiu(12, 0, smaller)
    a.label('units_ready'); a.sw(12, 29, UNITS)
    a.i(10, 9, 11, COMPACT_BELOW); a.branch(4, 9, 0, 'label_ready')
    a.li(9, TEXT+TEXT_STRIDE); a.sw(9, 29, LABEL_AT)
    a.label('label_ready')
    _frame_units(a, 8, SPLIT_X)
    a.branch(4, 13, 0, 'meter_left')
    a.r(0x21, 21, 21, 10); a.r(0x23, 21, 21, 8); a.r(0x23, 21, 21, 11); a.jump('meter_y')
    a.label('meter_left'); a.r(0x21, 21, 21, 8)
    a.label('meter_y')
    a.addiu(8, 0, SPLIT_Y); a.r(24, 0, 8, 10); a.r(18, 8, 0); a.r(2, 8, 0, 8, 8); a.r(0x21, 19, 19, 8)
    a.r(0, 8, 0, 12, 1); a.r(0x21, 8, 8, 12); a.r(2, 8, 0, 8, 1)          # bar: 1.5 label sizes lower
    a.r(0x21, 22, 19, 8); a.jump('place_done')
    a.label('text_panel')
    a.lw(21, 17, 516); a.addiu(21, 21, -MARGIN-WIDTH); a.lw(19, 17, 520); a.addiu(19, 19, screen_y(LABEL_TOP))
    a.label('placed'); a.addiu(22, 19, LABEL_GAP)
    a.label('place_done')


def caption_code():
    """The existing native glyph runs at 75% in every view, including solo; smaller in a narrow split meter.

    feed.SMALL_TEXT deliberately falls back to full size outside 3/4 views.
    A private renderer keeps this caption small without changing other text.
    t0 = size as the kit's NTEXT_75 takes it (4..6 units per atlas pixel, 8 = classic; anything else 6 = 75%):
    2*t0 GS units per font pixel. All geometry stays in GS 12.4 units; no reduced bitmap is stretched back up.
    """
    a=Assembler(CAPTION)
    def units(reg):
        a.r(24,0,reg,15);a.r(18,reg,0)
    a.addiu(29,29,-0x60)
    saved=(*range(16,24),31)
    for i,r in enumerate(saved):a.i(63,r,29,i*8)
    for d,s in zip(range(16,20),range(4,8)):a.move(d,s)
    a.sw(8,29,0x50)
    a.call(A(0x100878));a.move(20,2)
    a.lw(15,29,0x50);a.addiu(9,15,-4);a.i(11,9,9,3);a.branch(5,9,0,'size_ok');a.addiu(15,0,6)
    a.label('size_ok');a.r(0,15,0,15,1)                       # t7 = GS units per font pixel (12 = 75%)
    a.r(0,24,0,15,1);a.r(0x21,24,24,15);a.r(0,24,0,24,1)      # t8 = 6 font pixels: the glyph advance
    a.li(8,feed.TEMPLATE)
    for off in range(0,112,4):a.lw(9,8,off);a.sw(9,20,off)
    a.sw(19,20,80);a.addiu(21,20,112);a.move(22,0);a.move(23,0)
    a.label('char');a.i(36,8,16,0);a.branch(4,8,0,'finish')
    a.i(12,8,8,127);a.r(0,8,0,8,7);a.li(9,feed.FONT);a.r(0x2D,8,8,9);a.lw(9,8)
    a.addiu(8,8,4)
    a.label('run');a.branch(4,9,0,'next');a.lw(10,8)
    a.i(12,11,10,255);units(11);a.r(0x2D,11,11,17)
    a.r(3,12,0,10,8);a.i(12,12,12,255);units(12);a.r(0x2D,12,12,18)
    a.r(3,13,0,10,16);units(13);a.r(0x2D,13,13,11);a.r(0x21,14,12,15)
    a.r(0,12,0,12,16);a.r(0x25,11,11,12);a.sw(11,21);a.sw(0,21,4)
    a.r(0,14,0,14,16);a.r(0x25,13,13,14);a.sw(13,21,8);a.sw(0,21,12)
    a.addiu(21,21,16);a.addiu(22,22,1);a.addiu(8,8,4);a.addiu(9,9,-1);a.jump('run')
    a.label('next');a.addiu(16,16,1);a.r(0x21,17,17,24);a.addiu(23,23,1)
    a.i(11,8,23,TEXT_STRIDE-1);a.branch(5,8,0,'char')
    a.label('finish');a.i(13,8,22,0x8000);a.sw(8,20,96);a.move(4,21);a.call(A(0x100890))
    for i,r in enumerate(saved):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60);a.jr()
    data=a.finish();assert len(data)<=END-CAPTION
    return data


def _pointer(a, reg, size, fail):
    a.li(8, 0x100000); a.r(0x2B, 9, reg, 8); a.branch(5, 9, 0, fail)
    a.li(8, 0x08000000-size+1); a.r(0x2B, 9, reg, 8); a.branch(4, 9, 0, fail)
    a.i(12, 9, reg, 3); a.branch(5, 9, 0, fail)


def alive_code():
    """Physical a0 -> its captured actor while it takes part and is not defeated, else zero; leaf.

    Draw-only, so it deliberately reads no model, form or admission data: a transformation (including a giant form),
    fusion, Body Change or a model reload keeps the fighter and its team's meter on screen (live: the form slot stays
    valid through transformations, fusion and extra-fighter reloads). The current form's attack admission stays with
    the director (tag_team_rush.ELIGIBLE); the participation mask already drops consumed fusion partners. An invalid
    form slot still counts as absent, as before, so a fighter whose health cannot be read never supplies an ally."""
    a=Assembler(ALIVE)
    a.li(8, CONTROL); a.lw(9, 8, 8); a.r(0x2B, 9, 4, 9); a.branch(4, 9, 0, 'no')
    a.li(8, participation.CONTROL); a.lw(9, 8, 12); a.lw(10, 8, 16)
    a.r(0x27, 10, 10, 0); a.r(0x24, 9, 9, 10)
    a.addiu(10, 0, 1); a.r(4, 10, 4, 10); a.r(0x24, 9, 9, 10); a.branch(4, 9, 0, 'no')
    a.r(0, 8, 0, 4, 2); a.li(2, core.POINTERS); a.r(0x21, 2, 2, 8); a.lw(2, 2)
    _pointer(a, 2, 0x1600, 'no')
    a.lw(9,2);a.branch(5,9,4,'no')
    a.lw(9, 2, 0x994); a.i(11, 8, 9, 5); a.branch(4, 8, 0, 'no')
    a.lw(10, 2, 0x998); a.r(0x2B, 10, 9, 10); a.branch(4, 10, 0, 'no')
    a.r(0, 3, 0, 9, 7); a.r(0, 8, 0, 9, 5); a.r(0x21, 3, 3, 8)
    a.r(0, 8, 0, 9, 2); a.r(0x21, 3, 3, 8); a.r(0x21, 3, 3, 2)
    a.lw(8, 3, 0x9E4); a.branch(6, 8, 0, 'no')
    a.jr()
    a.label('no'); a.move(2, 0); a.jr()
    data=a.finish(); assert len(data)<=TEXT-ALIVE
    return data


def _rect(a, width, dy, height, color, *, dx=0):
    # s5/s6 retain the top-left of the bar; s7 is the scaled fill width; width: px beyond the meter's (METER_W).
    a.addiu(4, 21, 1792+dx); a.r(0, 4, 0, 4, 4)
    a.addiu(5, 22, Y_ORIGIN+dy); a.r(0, 5, 0, 5, 4)
    if width is None: a.r(0x21, 6, 21, 23); a.addiu(6, 6, 1792)
    else: a.lw(6, 29, METER_W); a.r(0x21, 6, 6, 21); a.addiu(6, 6, 1792+dx+width)
    a.r(0, 6, 0, 6, 4)
    a.addiu(7, 22, Y_ORIGIN+dy+height); a.r(0, 7, 0, 7, 4)
    if color is None: a.lw(8, 29, 0x60)
    else: a.li(8, color)
    a.call(bars.RECT)


def draw_code(meter=True):
    a=Assembler(DRAW); a.addiu(29, 29, -STACK)
    for i, reg in enumerate(REGS): a.i(63, reg, 29, i*8)
    a.r(16, 8, 0); a.i(63, 8, 29, 0x48)
    a.r(18, 8, 0); a.i(63, 8, 29, 0x50)
    a.sw(0, 29, SPLIT_SLOT)
    # Draw the scoped beam-ending white fade before hiding cinematic meters.
    import tag_rush_effects as effects
    a.li(8,effects.CONTROL);a.lw(9,8);a.li(10,effects.MAGIC)
    a.branch(5,9,10,'white_done');a.call(effects.WHITE_DRAW);a.label('white_done')
    if not meter:
        return _epilogue(a)
    a.li(8, SHOW); a.lw(9, 8); a.branch(4, 9, 0, 'done')
    core.gate(a, 'done')
    a.li(16, CONTROL); a.lw(9, 16); a.li(8, MAGIC); a.branch(5, 9, 8, 'done')
    a.lw(9, 16, 4); a.lw(8, 28, -22364); a.branch(5, 9, 8, 'done')
    a.lw(9, 16, 8); a.branch(5, 9, 10, 'done')
    for off in (12, 60):
        a.lw(9, 16, off); a.addiu(8, 0, 1); a.branch(5, 9, 8, 'done')
    # A captured free-for-all has no allies, regardless of physical slot parity.
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(11,modes.MAGIC);a.branch(5,9,11,'team_mode')
    a.lw(9,8,4);a.lw(11,16,4);a.branch(5,9,11,'team_mode')
    a.lw(9,8,12);a.li(11,modes.FFA);a.branch(4,9,11,'done')
    a.label('team_mode')
    a.li(8, participation.CONTROL); a.lw(9, 8); a.addiu(11, 0, 5); a.branch(5, 9, 11, 'done')
    a.lw(9, 8, 4); a.lw(11, 16, 4); a.branch(5, 9, 11, 'done')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'done')
    a.li(8, A(0x333700)); a.lw(9, 8); a.branch(5, 9, 0, 'done')
    a.li(8, A(0x2FEB38)); a.lw(11, 8); _pointer(a, 11, 4, 'done')
    a.lw(8, 11); a.addiu(9, 0, 3); a.branch(5, 8, 9, 'done')
    a.lw(17, 28, -22176); _pointer(a, 17, 832, 'done')
    # Apply to the camera actually drawn in this viewport: an unrelated
    # bystander's follow camera must not hide its meter for someone else's move.
    import cinematic_policy
    cinematic_policy.camera_running(a, 17, 'ordinary_camera', 'tag_hud_camera')
    a.lw(8, 17, 768); a.lw(9, 17, 772); a.r(0x25, 8, 8, 9); a.branch(5, 8, 0, 'done')
    a.label('ordinary_camera')
    a.li(19, camera.SUCCESSOR_CONTROL+8)
    a.li(8, hud.CONTROL); a.lw(9, 8); a.li(10, hud.MAGIC); a.branch(5, 9, 10, 'subject')
    a.call(hud.ACTIVE); a.branch(4, 2, 0, 'subject')
    a.li(20, hud.VIEWS); a.move(21, 0)
    a.label('view')
    for off, desc in ((512, 4), (516, 8), (520, 12), (524, 16)):
        a.lw(8, 17, off); a.lw(9, 20, desc); a.branch(5, 8, 9, 'next_view')
    a.addiu(8, 21, 1); a.sw(8, 29, SPLIT_SLOT); a.lw(19, 20, 20); a.jump('subject')
    a.label('next_view'); a.addiu(20, 20, hud.VIEW_STRIDE); a.addiu(21, 21, 1)
    a.addiu(8, 0, hud.MAX_VIEWS); a.branch(5, 21, 8, 'view'); a.jump('done')
    a.label('subject'); a.lw(18, 19); a.move(4, 18); a.call(ALIVE); a.branch(4, 2, 0, 'done')
    a.lw(8,16,16);a.branch(4,8,0,'free_subject')
    a.lw(8,16,24);a.branch(5,8,0,'done')
    a.lw(8,16,20);a.li(9,1);a.r(4,9,18,9);a.r(0x24,8,8,9);a.branch(5,8,0,'done')
    a.label('free_subject')
    # Team parity comes from the captured physical subject, not an actor role alias.
    a.i(12, 19, 18, 1); a.move(20, 19); a.move(21, 0); a.lw(22, 16, 8)
    a.label('ally'); a.move(4, 20); a.call(ALIVE); a.branch(4, 2, 0, 'next_ally')
    a.addiu(21, 21, 1); a.addiu(8, 0, 2); a.branch(4, 21, 8, 'team_ready')
    a.label('next_ally'); a.addiu(20, 20, 2); a.r(0x2B, 8, 20, 22); a.branch(5, 8, 0, 'ally'); a.jump('done')
    a.label('team_ready'); a.r(0, 19, 0, 18, 5); a.li(8, METERS); a.r(0x21, 19, 19, 8)
    a.lw(20, 16, 48); a.branch(6, 20, 0, 'done'); a.lw(23, 19)
    a.r(0x2B, 8, 23, 20); a.branch(5, 8, 0, 'charging'); a.move(23, 20)
    a.li(8, GOLD); a.sw(8, 29, 0x60); a.jump('chosen')
    a.label('charging'); a.li(8, BLUE); a.sw(8, 29, 0x60)
    a.label('chosen'); _place(a)
    # Never outside this view: left and right edges, and the bar's foot above its bottom.
    a.lw(8, 17, 512); a.r(0x2A, 8, 21, 8); a.branch(5, 8, 0, 'done')
    a.lw(8, 17, 516); a.lw(9, 29, METER_W); a.r(0x21, 9, 9, 21); a.addiu(9, 9, 1); a.r(0x2A, 8, 8, 9)
    a.branch(5, 8, 0, 'done')
    a.lw(8, 17, 524); a.addiu(9, 22, HEIGHT+5); a.r(0x2A, 8, 8, 9); a.branch(5, 8, 0, 'done')
    for dx, dy, color in ((1, 1, BLACK), (0, 0, None)):
        a.lw(4, 29, LABEL_AT); a.addiu(5, 21, 1792+dx); a.r(0, 5, 0, 5, 4)
        a.addiu(6, 19, Y_ORIGIN+dy); a.r(0, 6, 0, 6, 4)
        if color is None: a.lw(7, 29, 0x60)
        else: a.li(7, color)
        a.lw(8, 29, UNITS)                                    # t0: label size (caption_code / the kit's NTEXT_75)
        a.call(CAPTION)
    a.lw(8, 29, METER_W); a.r(24, 0, 23, 8); a.r(18, 23, 0)
    a.r(27, 0, 23, 20); a.r(18, 23, 0)
    _rect(a, 2, -1, HEIGHT+2, BLACK, dx=-1)
    _rect(a, 0, 0, HEIGHT, 0x80403020)
    a.branch(4, 23, 0, 'done'); _rect(a, None, 0, HEIGHT, None)
    return _epilogue(a)


def _epilogue(a):
    a.label('done')
    a.i(55, 8, 29, 0x48); a.r(17, 0, 8); a.i(55, 8, 29, 0x50); a.r(19, 0, 8)
    for i, reg in enumerate(REGS): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, STACK); a.jr()
    data=a.finish(); assert len(data)<=ALIVE-DRAW
    return data


def shows_meter(settings=None):
    """The 'Tag attack meter' HUD setting (default on)."""
    return (settings or {}).get(SHOW_KEY, True) is not False


def pieces(settings=None):
    """Off: only the draw entry (the white fade) and a zero SHOW word; no meter, caption or label is installed."""
    if not shows_meter(settings):
        return [(DRAW, draw_code(meter=False)), (SHOW, struct.pack('<I', 0))]
    return [(DRAW, draw_code()), (ALIVE, alive_code()), (CAPTION, caption_code()),
            (TEXT, localization.slot(LABEL, TEXT_STRIDE, settings)+localization.slot(COMPACT_LABEL, TEXT_STRIDE, settings)),
            (SHOW, struct.pack('<I', 1))]


def hud_extension(ram):
    if len(ram)<END or struct.unpack_from('<I', ram, CONTROL)[0]!=MAGIC: return None
    if ram[DRAW:DRAW+8]!=draw_code()[:8]: return None   # both variants share this prologue
    return (CONTROL, MAGIC, DRAW)


def hud_patch(ram):
    """Compose our draw entry into a known normal or three/four-view renderer.

    Installation follows four_player_mode. Its wrapper suppresses the normal
    extensions; in that case the quad renderer owns all per-view calls instead.
    Unknown bytes are never overwritten.
    """
    if struct.unpack_from('<I', ram, hud.CONTROL)[0]!=hud.MAGIC: return []
    import quad_viewports as quad
    entry=(CONTROL, MAGIC, DRAW)
    before=hud.hud_extensions(ram)
    without=tuple(e for e in before if e!=entry)
    candidates=(before, without) if before!=without else (without,)
    after=without+(entry,)
    previous=struct.unpack_from('<I', ram, hud.CONTROL+16)[0]
    if struct.unpack_from('<I', ram, quad.CONTROL)[0]==quad.MAGIC:
        address, limit=quad.DRAW, quad.SELECT
        for extensions in candidates:
            old=quad.draw(extensions)
            if ram[address:address+len(old)]==old: break
        else: raise ValueError('Unknown per-view HUD renderer for tag-team rush')
        new=quad.draw(after)
    else:
        address, limit=hud.CODE, hud.ACTIVE
        for extensions, kwargs in ((e,k) for e in candidates for k in (dict(deferred=True), dict())):
            old=hud.wrapper(previous, extensions=extensions, **kwargs)
            if ram[address:address+len(old)]==old:
                new=hud.wrapper(previous, extensions=after, **kwargs); break
        else: raise ValueError('Unknown viewport HUD wrapper for tag-team rush')
    if ram[address:address+len(old)]!=old: raise ValueError('Unknown per-view HUD renderer for tag-team rush')
    if old==new: return []
    if len(new)>limit-address: raise ValueError('Tag-team rush HUD exceeds its drawing reservation')
    if any(ram[address+len(old):address+len(new)]): raise ValueError('Tag-team rush HUD extension tail occupied')
    return [(address, new)]
