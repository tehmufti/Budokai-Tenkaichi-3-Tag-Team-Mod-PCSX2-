"""Lock-on target selection: circular tap order, right-stick aiming, KO retarget and a target ring.

Installed last, after lockoff_target, and only when at least one of its settings differs from its
legacy value (lockon_cycle_order, lockon_right_stick, lockon_after_ko, lockon_target_marker). With
every one at its legacy value nothing here is installed and prepared matches keep their beta.33 bytes.
lockon_right_stick_mode only matters while lockon_right_stick is True, so it is not a legacy key.

It takes over lock-off's INPUT and APPLY through two 8-byte entry hooks with trampolines (both begin
with the position-independent save() prologue), so the queue emission and every lock-off program stay
byte for byte what beta.33 installs. The queue's safe-point gates still decide when a request runs;
only the target table entry of the human changes (and, from the unlocked state, lock-off's own relock).

Gestures (switch button = the queue's CONTROL+8 word):
- tap: next enemy in the chosen order (a fixed circle by world azimuth around you, nearest first, or
  slot order); the circle's direction is a build constant so "next" is to the right on screen.
- right stick (CONTROL+12: 0 off, 1 with the switch button held, 2 the right stick alone):
  - held (1, the default): hold + flick: left/right step around you, up/down the enemy above/below your target on
    your screen; unlocked, any direction from your view centre. One flick per return to neutral.
    The stick bits (and an R3 click newly pressed during the flick) are cleared in the aiming player's own pad
    record (its held word and both pressed words) from the flick until each is physically released, so the actor
    never sees the aim's press nor a synthetic one.
  - alone (2): the same steps and aims with no button, only while locked on in active combat (battle state 3, no
    result screen, no paired/rush/cinematic owner of the view, not in a paired action or transforming). Every
    deflection that starts from neutral there is masked until neutral, so the stick no longer swings the camera.
    A flick after two neutral updates aims on the next update unless R3 is down then, or was down at the flick or on
    the two updates before it; R3 itself is never masked, so transformations always go through. Unlocked, the
    stick stays the game's camera control and a tap relocks. Lock-off fires while held (beta.33 timing).
- your target defeated (two consecutive updates): the enemy nearest your view centre (lock-off PICK) as the view
  was when the target fell, chosen once per defeat; by the safe point the camera has often turned toward the
  game's own replacement. While a cinematic, shared rush or paired pause owns the view the count waits.
- a target indicator in your own view, in active combat only (lockon_target_style, beta.39): the gold arrow above
  your target's head (beta.37: a bevelled dart in one gouraud packet; it drops in when the target changes or on a
  relock, bobs twice, then rests), a yellow ring around its body (Dragon Ball Z Tenkaichi Tag Team style: two
  circles and an inward chevron on each side; it shrinks in from 1.6x, its chevrons blink while that target attacks
  you (lockon_threat)), or both. The ring's radius follows the target's on-screen size (the projected extent between
  its head and its root), clamped per view (12..34 px for one 448-line view, 6..17 px for a split or quad view).
  Both are drawn before the overhead bars in one- and two-view matches, so they never cover a health bar, and from
  the quad renderer's per-view extension list in three- and four-view matches and two-player matches with a team
  assignment (QMARKER), each view showing its own player's target.
"""
from native_map import A, CRC, SERIAL
import struct
from prototype import Assembler
import fresh_team_combat as core
import battle_mode_policy as modes
import mod_settings
from regional import DISPLAY_H, Y_ORIGIN

BASE, END = 0x06950000, 0x06958000
INPUT2, APPLY2, ORDER = BASE, BASE+0x1000, BASE+0x2000
AIM, MARKER = BASE+0x3000, BASE+0x4000
TAIL_INPUT, TAIL_APPLY = BASE+0x6000, BASE+0x6020
# The target ring's data (RING_HEADER .. +0x1B0; see below), then the arrow's GS packet template (640 bytes) and its
# lift table (80 bytes).
ARROW_PACKET, ARROW_LIFT = BASE+0x6400, BASE+0x6680
# QMARKER: the quad renderer's per-view extension entry (MARKER without the overhead bars); SIZE: the ring radius.
QMARKER, SIZE = BASE+0x5B00, BASE+0x5B40
CONTROL, ROWS = BASE+0x7000, BASE+0x7100
MAGIC = 0x4C4B5331  # 'LKS1'
STRIDE = 64
# Per physical fighter (separate from lock-off's rows, whose clear is inlined into the queue).
STAMP, ARMED, AIM_LATCH, STICK_LATCH, ARG = 0, 4, 8, 12, 16
MASK_BITS, MASK_REC, MASK_SEQ, WATCH, KO_LATCH, DEADN, HOLD2, KO_PICK, KO_SEEN = 20, 24, 28, 32, 36, 40, 44, 48, 52
# R3_GRACE (both stick modes): 2 on an update with R3 down, then counted down to 0. PENDING (the stick alone): the
# aim that commits on the next update. The stick alone uses ARMED as a neutral-update count saturating at 2.
R3_GRACE, PENDING = 56, 60
# Per view seat, 8 bytes, after the rows in the same zero block: the target+1 last drawn in this seat's view and
# the queue update of that change (the ring's drop-in).
MARKS = ROWS+STRIDE*modes.ENGINE_ACTORS
PRESSED = (336, 340)     # the pad record's pressed words (native: edge and auto-repeat; quad: its edge copies)
FIELDS = dict(magic=0, manager=4, order=8, stick=12, confirm=16, after_ko=20, marker=24, colour=28,
              steps=32, aims=36, ko=40, masked=44, markers=48, unchanged=52, viewer=56, side=60,
              reserved2=64, restored=68, release_unlocks=72, result=76, keys=0x80, aim_result=0xB0,
              style=0xB4, quad=0xB8, size_h=0xBC, size_r=0xC0)
ORDERS = {'left_to_right': 0, 'nearest_first': 1, 'selection_order': 2}
AFTER_KO = {'game_default': 0, 'nearest_to_centre': 1}
LEGACY = {'lockon_cycle_order': 'selection_order', 'lockon_right_stick': False,
          'lockon_after_ko': 'game_default', 'lockon_target_marker': False}
# How the right stick picks, while lockon_right_stick is on (CONTROL+12; 0 while it is off): 1 with the switch
# button held, 2 the right stick alone (locked on in combat). Not a legacy key: it only matters while the bool is on.
STICK_MODE_KEY = 'lockon_right_stick_mode'
STICK_MODES = {'with_switch_button': 1, 'right_stick_alone': 2}
# CONTROL+16, a build constant: 1 makes the stick alone commit a pending aim only while the stick is still deflected
# on the commit update (a stricter fallback against brushes; it drops about half of the quickest flicks at 30 Hz).
STICK_CONFIRM = 0
# The indicator (CONTROL+style bits, 0 while the marker is off): 1 the gold arrow (the default), 2 the ring, 3 both.
# Not a legacy key: it only matters while lockon_target_marker is on.
STYLE_KEY = 'lockon_target_style'
STYLES = {'arrow': 1, 'ring': 2, 'both': 3}
KEYS = (*LEGACY, STICK_MODE_KEY, STYLE_KEY)
COLOUR = 0x8037B1F1      # GS ABGR of the settings accent gold (241,177,55), CONTROL+28 (the ring has its own colours)
OUTLINE = 0x80060606     # the health bars' dark outline
# With the side flag 0, "next" follows increasing pseudo-angle of (dx, dz); flag 1 mirrors dx. The world's
# handedness is fixed and the lock-on camera stands behind you facing your target, so one constant makes
# "next" the enemy to the right on screen for every target. It is not calibrated per request: between quick
# taps the camera is still swinging toward the previous target, and a per-request reading flipped the
# direction live and trapped the cycle between two enemies. Measured live (USA, settled lock-on camera, four
# different targets): the quarter turn ahead of the target always projected left of it, so the flag is 1.
SIDE = 1
STICK = 0xF00000
LEFT, RIGHT, DOWN, UP = 0x100000, 0x200000, 0x400000, 0x800000
R3 = 0x4
INVALID = 0xFFFFFFFF
# The target arrow (beta.37): a bevelled gold dart (17 px wide) in one gouraud packet of 11 triangles, in paint order: a
# soft shadow (4), the dark outline (4: 2 px along both top edges, 1.25 px on the sides, the wing corners bevelled
# 2.5 px), the lit face, the shaded face and a glint. ((x, y) in sixteenths of a pixel from the tip, GS ABGR.)
SHADOW = 0x40000000
ARROW_VERTICES = (
    ((16, -144), SHADOW), ((-146, -209), SHADOW), ((-163, -192), SHADOW),
    ((16, -144), SHADOW), ((-163, -192), SHADOW), ((16, 58), SHADOW),
    ((16, -144), SHADOW), ((195, -192), SHADOW), ((178, -209), SHADOW),
    ((16, -144), SHADOW), ((16, 58), SHADOW), ((195, -192), SHADOW),
    ((0, -168), OUTLINE), ((-162, -233), OUTLINE), ((-179, -216), OUTLINE),
    ((0, -168), OUTLINE), ((-179, -216), OUTLINE), ((0, 34), OUTLINE),
    ((0, -168), OUTLINE), ((179, -216), OUTLINE), ((162, -233), OUTLINE),
    ((0, -168), OUTLINE), ((0, 34), OUTLINE), ((179, -216), OUTLINE),
    ((-136, -190), 0x8096EEFF), ((0, -136), 0x8048D4FF), ((0, 0), 0x80149EF2),
    ((0, -136), 0x801CA0E0), ((136, -190), 0x802CB0EC), ((0, 0), 0x800660AA),
    ((-102, -163), 0x70EBFFFF), ((-34, -136), 0x00EBFFFF), ((-41, -82), 0x00EBFFFF))
TIP_GAP = 21             # pixels from the projected (lifted) head up to the dart's tip
# The tip's clamp margins in pixels (left, right, up, down), so the whole dart stays inside its view (the right and
# bottom viewport bounds are inclusive pixels).
MARGIN = (12, 12, 15, 3)
assert all(-16*MARGIN[0] <= x <= 16*(MARGIN[1]+1) and -16*MARGIN[2] <= y <= 16*(MARGIN[3]+1) for (x, y), _ in ARROW_VERTICES)
# Whole-pixel lift by queue update since the target changed (or a relock): an 8-update drop-in, then two bob cycles;
# from len(LIFT) on the arrow rests.
DROP = (10, 8, 6, 4, 3, 2, 1, 0)
BOB = (0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0)
LIFT = DROP+BOB+BOB
# The target ring (Dragon Ball Z Tenkaichi Tag Team style): two yellow circles around the target's body, an inward
# chevron on each side, in one packet: three triangle strips (a dark rim, the outer ring, the inner ring) and one
# triangle list (the chevrons' dark outlines, then their faces). The vertices are generated at draw time. GS ABGR.
RING, CHEV, DARK = 0x8028ECFA, 0x705AF0FF, 0x50060606
RED, WARN_Y = 0x802020E8, 0x8028ECFF
# The radius (SIZE, beta.39) follows the target's on-screen size: (H*SIZE_NUM) >> 8 sixteenths, H the larger
# projected extent (x or y, sixteenths) between its head anchor (bone 48) and its model root, clamped per view to
# [(vs*MIN_NUM) >> 6, (vs*MAX_NUM) >> 6] sixteenths (vs = emit_view_size, min(height, 11/8 width) in lines: 12..34 px
# for one 448-line view, 9..27 px for a side-by-side split view, 6..17 px for a top/bottom split or quad view), times
# the drop-in scale.
SIZE_NUM, MIN_NUM, MAX_NUM = 72, 27, 78
SEGMENTS = 24
# Q8 scale by queue update since the target changed (or a relock): an 8-update drop-in, then the ring rests.
SCALE = (410, 371, 338, 310, 287, 271, 261, 256)
# Ring radii in sixteenths of a pixel from the drawn radius r and the band b = max(BAND_MIN, r >> 4): the rim
# r+b/2..r-b, the outer ring r..r-b, the inner ring ri = (r*INNER_FRAC >> 8) .. ri-max(INNER_MIN, b/2) (0.80 r).
INNER_FRAC, BAND_MIN, INNER_MIN = 205, 16, 12
TIP_FRAC = 287           # the ring chevrons' tips at 1.12 r (Q8)
PRIM_STRIP, PRIM_TRIANGLES = 0x44, 0x43    # TRIANGLE_STRIP | ABE, TRIANGLE | ABE
SAVED = tuple(range(16, 24))+(31,)


def _outline(points, width):
    """The triangle grown by width on every side (each edge moved outward, adjacent edges intersected)."""
    import math
    cx, cy = sum(p[0] for p in points)/3, sum(p[1] for p in points)/3
    lines = []
    for i in range(3):
        (x0, y0), (x1, y1) = points[i], points[(i+1) % 3]
        nx, ny = y1-y0, x0-x1; n = math.hypot(nx, ny); nx, ny = nx/n, ny/n
        if (x0-cx)*nx+(y0-cy)*ny < 0: nx, ny = -nx, -ny
        lines.append((x0+nx*width, y0+ny*width, x1-x0, y1-y0))
    out = []
    for i in range(3):
        (ax, ay, adx, ady), (bx, by, bdx, bdy) = lines[i-1], lines[i]
        t = ((bx-ax)*bdy-(by-ay)*bdx)/(adx*bdy-ady*bdx)
        out.append((round(ax+adx*t), round(ay+ady*t)))
    return tuple(out)


# Chevrons pointing +x with the tip at (0, 0): the ring's in units of r/256 (0.30 r long, 0.24 r half height; outline
# 1.5 px at Rv 58), the marks' in sixteenths of a pixel at scale 256 (14 px long, 9 px half height; outline 1.5 px).
RING_CHEVRON = ((0, 0), (-77, -61), (-77, 61))
MARK_CHEVRON = ((0, 0), (-224, -144), (-224, 144))
CHEVRONS = (_outline(RING_CHEVRON, 7), RING_CHEVRON, _outline(MARK_CHEVRON, 24), MARK_CHEVRON)
# The ring's data: the packet header, the circle table (cos, sin in Q14 words, SEGMENTS+1 points), SCALE (words) and
# the four chevron tables (outline, face; 3 (x, y) word pairs each).
RING_HEADER = BASE+0x6100
RING_TABLE, RING_SCALE = RING_HEADER+0x60, RING_HEADER+0x130
RING_OUTLINE, RING_FILL, MARK_OUTLINE, MARK_FILL = (RING_HEADER+0x150+24*k for k in range(4))
# The shared GS emitters (used by the ring here and by lockon_threat's marks).
SEG, STRIP, TRI = BASE+0x5800, BASE+0x5900, BASE+0x5A00
# MARKER's stack words.
M_RADIUS, M_TIP, M_X, M_Y, M_COLOUR, M_EOP = 0xB0, 0xB4, 0xB8, 0xBC, 0xC0, 0xC4
M_NATIVE, M_STYLE, M_AGE, M_BAND, M_MODEL, M_FRAMES = 0xC8, 0xCC, 0xD0, 0xD4, 0xD8, 0xDC
ONE, FOUR = 0x3F800000, 0x40800000


def save(a, size=0x100):
    a.addiu(29, 29, -size)
    for i, r in enumerate(SAVED): a.i(63, r, 29, 8*i)


def restore(a, size=0x100):
    for i, r in enumerate(SAVED): a.i(55, r, 29, 8*i)
    a.addiu(29, 29, size); a.jr()


def fop(a, fn, fd, fs, ft=0):
    """COP1 single-precision arithmetic (add 0, sub 1, mul 2, div 3, abs 5, c.lt 0x34)."""
    a.emit((17 << 26) | (16 << 21) | (ft << 16) | (fs << 11) | (fd << 6) | fn)


def mtc1(a, rt, fs): a.emit((17 << 26) | (4 << 21) | (rt << 16) | (fs << 11))
def mfc1(a, rt, fs): a.emit((17 << 26) | (rt << 16) | (fs << 11))
def lwc1(a, ft, base, offset): a.i(49, ft, base, offset)
def swc1(a, ft, base, offset): a.i(57, ft, base, offset)
def jump(target): return struct.pack('<2I', (2 << 26) | (target >> 2), 0)
def jal(target): return struct.pack('<I', (3 << 26) | (target >> 2))


def emit_row(a, index, dest, table=ROWS, shift=6):
    a.r(0, 8, 0, index, shift); a.li(dest, table); a.r(0x21, dest, dest, 8)


def emit_actor(a, index, dest, fail):
    """dest = captured actor of physical index (valid pointer). t0/t1."""
    from guest_healthbars import valid_pointer
    a.li(8, core.POINTERS); a.r(0, 9, 0, index, 2); a.r(0x21, 8, 8, 9); a.lw(dest, 8)
    valid_pointer(a, dest, fail, 0x1600)


def emit_model(a, actor, dest, fail, drawn=True):
    """dest = the actor's actual model (valid pointer, and drawn: +4/+8 set). t0/t1."""
    from guest_healthbars import valid_pointer
    a.lw(8, actor, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, fail)
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(dest, 8)
    valid_pointer(a, dest, fail, 0x1670)
    if drawn:
        for off in (4, 8): a.lw(8, dest, off); a.branch(4, 8, 0, fail)


def emit_health(a, actor, fail, alive=True):
    """Active-form health row (+0x994 form, 164-byte rows at +0x9E4). alive: fail unless HP > 0;
    otherwise fail unless HP <= 0 (a defeated fighter). An invalid form fails either way. t0..t2."""
    a.lw(8, actor, 0x994); a.i(11, 9, 8, 5); a.branch(4, 9, 0, fail)
    a.r(0, 9, 0, 8, 7); a.r(0, 10, 0, 8, 5); a.r(0x21, 9, 9, 10)
    a.r(0, 10, 0, 8, 2); a.r(0x21, 9, 9, 10); a.r(0x21, 9, 9, actor)
    a.lw(8, 9, 0x9E4); a.branch(6 if alive else 7, 8, 0, fail)


def emit_present(a, index, fail):
    """Present and not fusion-consumed (team_participation +12/+16). t0..t2."""
    import team_participation as part
    a.li(8, part.CONTROL); a.lw(9, 8, 12); a.lw(10, 8, 16); a.r(0x27, 10, 10, 0); a.r(0x24, 9, 9, 10)
    a.addiu(10, 0, 1); a.r(4, 10, index, 10); a.r(0x24, 9, 9, 10); a.branch(4, 9, 0, fail)


def emit_candidate(a, index, viewer, actor, model, fail, tag):
    """Exactly lock-off PICK's candidate predicate, without projection: an enemy of viewer, present and
    not consumed, valid actor, living active form, valid drawn model. t0..t2; actor/model outputs."""
    modes.emit_enemy(a, index, viewer, fail, tag)
    emit_present(a, index, fail)
    emit_actor(a, index, actor, fail)
    emit_health(a, actor, fail)
    emit_model(a, actor, model, fail)


def emit_camera(a, viewer, dest, fail):
    """dest = lock-off CAMERA(viewer) with PICK's viewport checks. Calls CAMERA (t0..t3, a0)."""
    import lockoff_target as off
    from guest_healthbars import valid_pointer
    a.move(4, viewer); a.call(off.CAMERA); a.move(dest, 2)
    valid_pointer(a, dest, fail, 656)
    emit_viewport(a, dest, fail)


def emit_viewport(a, cam, fail):
    for off, upper in ((512, 512), (516, 512), (520, DISPLAY_H), (524, DISPLAY_H)):
        a.lw(8, cam, off); a.i(11, 9, 8, upper); a.branch(4, 9, 0, fail)
    for lo, hi in ((512, 516), (520, 524)):
        a.lw(8, cam, lo); a.lw(9, cam, hi); a.r(0x2B, 8, 8, 9); a.branch(4, 8, 0, fail)


def emit_push(a, cam):
    a.call(A(0x120AB0)); a.addiu(4, cam, 320); a.call(A(0x120B80))


def emit_anchor(a, model, bone, fail):
    """a1 = the bone's world point (bone 47 root / 48 head) or the model root. t0/t1."""
    from guest_healthbars import valid_pointer
    a.lw(5, model, 3436+bone*4); a.branch(4, 5, 0, fail+'_root'); valid_pointer(a, 5, fail+'_root', 0xE0)
    a.addiu(5, 5, 64); a.jump(fail+'_point'); a.label(fail+'_root'); a.addiu(5, model, 2416)
    a.label(fail+'_point')


def emit_project(a, fail, out=0x80):
    """Project a1 into sp+out (x16, y16, flag, depth); fail when behind or not projected."""
    a.addiu(4, 29, out); a.call(A(0x1210D8))
    a.branch(4, 2, 0, fail); a.lw(8, 29, out+12); a.branch(6, 8, 0, fail)
    a.lw(8, 29, out+8); a.branch(1, 8, 0, fail)


def emit_body_centre(a, model, point, tag):
    """sp+point = the body centre: the midpoint of the head anchor (bone 48, no bar lift) and the model root, w 1.0;
    a1 = sp+point. t0/t1, f0..f2."""
    emit_anchor(a, model, 48, tag)
    a.li(8, 0x3F000000); mtc1(a, 8, 2)
    for k in range(3):
        lwc1(a, 0, 5, 4*k); lwc1(a, 1, model, 2416+4*k); fop(a, 0, 0, 0, 1); fop(a, 2, 0, 0, 2)
        swc1(a, 0, 29, point+4*k)
    a.li(8, ONE); a.sw(8, 29, point+12); a.addiu(5, 29, point)


def emit_packet_begin(a, cursor, tag):
    """cursor (an s register) = a new allocation with the ring header copied in, positioned after it. t0..t3."""
    a.call(A(0x100878)); a.move(cursor, 2)
    a.li(8, RING_HEADER); a.addiu(10, 8, 96)
    a.label(tag); a.lw(11, 8, 0); a.sw(11, cursor, 0); a.addiu(8, 8, 4); a.addiu(cursor, cursor, 4)
    a.branch(5, 8, 10, tag)


def emit_packet_end(a, cursor, eop):
    """Set EOP on the last REGLIST tag (its address at sp+eop) and submit up to cursor."""
    a.lw(8, 29, eop); a.lw(9, 8, 0); a.i(13, 9, 9, 0x8000); a.sw(9, 8, 0)
    a.move(4, cursor); a.call(A(0x100890))


def emit_segment(a, cursor, prim, count, colour=None, colour_slot=None, eop=None):
    """SEG at cursor: PRIM and the colour (a constant, or the word at sp+colour_slot), then a tag for count XYZ2;
    a0 = the vertex position (cursor not yet moved), sp+eop = the tag."""
    a.move(4, cursor); a.addiu(5, 0, prim)
    if colour_slot is None: a.li(6, colour)
    else: a.lw(6, 29, colour_slot)
    a.addiu(7, 0, count); a.call(SEG); a.move(4, 2)
    if eop is not None: a.sw(3, 29, eop)


def emit_chevron(a, cursor, x, y, tip, scale, orient, table, sign=0):
    """TRI at cursor (a0 already there): the chevron table from the tip at (sp+x - or + sp+tip (sign -1 / +1), sp+y),
    scale sp+scale, orientation a constant or ('sp', slot). The cursor follows."""
    a.lw(5, 29, x)
    if sign: a.lw(8, 29, tip); a.r(0x23 if sign < 0 else 0x21, 5, 5, 8)
    a.lw(6, 29, y); a.lw(7, 29, scale); a.li(8, table)
    if isinstance(orient, tuple): a.lw(9, 29, orient[1])
    else: a.addiu(9, 0, orient)
    a.call(TRI); a.move(cursor, 2); a.move(4, 2)


def emit_chevron_pair(a, cursor, x, y, tip, scale, outline, fill, colour_slot, eop):
    """Two inward chevrons either side of (sp+x, sp+y), tips sp+tip from it: dark outlines first, then the faces in
    the colour at sp+colour_slot. sp+eop = the last tag."""
    for table, slot in ((outline, None), (fill, colour_slot)):
        emit_segment(a, cursor, PRIM_TRIANGLES, 6, DARK, slot, eop)
        emit_chevron(a, cursor, x, y, tip, scale, 0, table, -1)
        emit_chevron(a, cursor, x, y, tip, scale, 1, table, 1)


def segment_code():
    """a0 dst, a1 PRIM, a2 RGBA, a3 vertex count -> v0 dst+64 (the vertices go there), v1 dst+48 (the tag).

    An A+D tag (PRIM, then RGBAQ with Q 1.0), then a REGLIST tag of XYZ2 with EOP clear. t0 only."""
    a = Assembler(SEG)
    a.addiu(8, 0, 2); a.sw(8, 4, 0); a.li(8, 0x10000000); a.sw(8, 4, 4)
    a.addiu(8, 0, 0xE); a.sw(8, 4, 8); a.sw(0, 4, 12)
    a.sw(5, 4, 16); a.sw(0, 4, 20); a.sw(0, 4, 24); a.sw(0, 4, 28)
    a.sw(6, 4, 32); a.li(8, ONE); a.sw(8, 4, 36); a.addiu(8, 0, 1); a.sw(8, 4, 40); a.sw(0, 4, 44)
    a.sw(7, 4, 48); a.li(8, 0x14000000); a.sw(8, 4, 52); a.addiu(8, 0, 5); a.sw(8, 4, 56); a.sw(0, 4, 60)
    a.addiu(3, 4, 48); a.addiu(2, 4, 64); a.jr()
    data = a.finish(); assert len(data) <= STRIP-SEG; return data


def emit_vertex(a, x, y):
    """Store XYZ2 (x | y << 16, Z 0) at a0 and advance it. x and y are clobbered."""
    a.i(12, x, x, 0xFFFF); a.r(0, y, 0, y, 16); a.r(0x25, x, x, y)
    a.sw(x, 4, 0); a.sw(0, 4, 4); a.addiu(4, 4, 8)


def strip_code():
    """a0 dst, a1 x16, a2 y16 (the centre), a3 outer radius, t0 inner radius (sixteenths) -> v0 dst+8*2*(SEGMENTS+1).

    One closed annulus as a triangle strip, outer and inner points alternating. t0..t6, LO/HI."""
    a = Assembler(STRIP)
    a.li(9, RING_TABLE); a.addiu(10, 9, 8*(SEGMENTS+1))
    a.label('loop'); a.lw(11, 9, 0); a.lw(12, 9, 4)
    for radius in (7, 8):
        a.r(24, 0, 11, radius); a.r(18, 13, 0, 0); a.r(3, 13, 0, 13, 14); a.r(0x21, 13, 13, 5)
        a.r(24, 0, 12, radius); a.r(18, 14, 0, 0); a.r(3, 14, 0, 14, 14); a.r(0x21, 14, 14, 6)
        emit_vertex(a, 13, 14)
    a.addiu(9, 9, 8); a.branch(5, 9, 10, 'loop')
    a.move(2, 4); a.jr()
    data = a.finish(); assert len(data) <= TRI-STRIP; return data


def triangle_code():
    """a0 dst, a1 x16, a2 y16 (the tip), a3 scale (Q8), t0 table (3 word pairs, pointing +x), t1 orientation (0 +x,
    1 -x, 2 +y, 3 -y) -> v0 dst+24. Each vertex is the tip plus the turned (u*scale) >> 8. t0..t5, LO/HI."""
    a = Assembler(TRI)
    a.addiu(10, 8, 24)
    a.label('loop'); a.lw(11, 8, 0); a.lw(12, 8, 4)
    a.r(24, 0, 11, 7); a.r(18, 11, 0, 0); a.r(3, 11, 0, 11, 8)
    a.r(24, 0, 12, 7); a.r(18, 12, 0, 0); a.r(3, 12, 0, 12, 8)
    a.i(12, 13, 9, 1); a.branch(4, 13, 0, 'forward'); a.r(0x23, 11, 0, 11)
    a.label('forward'); a.i(12, 13, 9, 2); a.branch(4, 13, 0, 'placed')
    a.move(13, 11); a.move(11, 12); a.move(12, 13)
    a.label('placed'); a.r(0x21, 11, 11, 5); a.r(0x21, 12, 12, 6)
    emit_vertex(a, 11, 12)
    a.addiu(8, 8, 8); a.branch(5, 8, 10, 'loop')
    a.move(2, 4); a.jr()
    data = a.finish(); assert len(data) <= 0x100; return data


def emit_centre(a, cam, dest, lo, hi, origin):
    a.lw(8, cam, lo); a.lw(9, cam, hi); a.r(0x21, 8, 8, 9); a.addiu(8, 8, 2*origin); a.r(0, dest, 0, 8, 3)


def emit_view_owned(a, owned, tag):
    """Branch to owned while a paired pause, the shared rush or a cinematic camera owns the view (the marker's
    and the queue's owners; an invalid cinematic pointer counts as owned). t0/t1/t3; may call the rush owner."""
    import rush_cinematics as rush
    from guest_healthbars import valid_pointer
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, owned)
    rush.emit_hud_gate(a, owned, tag+'_rush')
    a.li(8, A(0x2FEBCC)); a.lw(11, 8); a.branch(4, 11, 0, tag+'_free')
    valid_pointer(a, 11, owned, 816); a.lw(8, 11, 812); a.branch(5, 8, 0, owned)
    a.label(tag+'_free')


def emit_rewatch(a, value, tag):
    """Own row (s4) WATCH = value (target+1); watching another target clears KO_LATCH and KO_SEEN. t1."""
    a.lw(9, 20, WATCH); a.branch(4, 9, value, tag)
    a.sw(value, 20, WATCH); a.sw(0, 20, KO_LATCH); a.sw(0, 20, KO_SEEN)
    a.label(tag)


def emit_gate(a, closed, tag):
    """The stick-alone gate (s0 actor, s3 lock-off row): locked on (unlocked, the right stick keeps turning the
    camera), battle state 3, no result screen, the view not owned (paired pause, shared rush, cinematic camera) and
    the fighter neither in a paired action nor transforming (236..243). Branches to closed. t0..t3; may call the
    rush owner."""
    import lockoff_target as off
    import lockon_switch as ls
    from guest_healthbars import valid_pointer
    from result_presentation import RESULT
    a.lw(8, 19, off.OFF); a.branch(5, 8, 0, closed)
    a.li(8, A(0x2FEB38)); a.lw(11, 8); valid_pointer(a, 11, closed, 0x200)
    a.lw(9, 11); a.addiu(10, 0, 3); a.branch(5, 9, 10, closed)
    a.li(8, RESULT); a.lw(8, 8); a.branch(5, 8, 0, closed)
    emit_view_owned(a, closed, tag+'_view')
    a.lw(8, 16, 0x948)
    for start, span in ls.PAIRED_STATES+((236, 8),):
        a.addiu(9, 8, -start); a.i(11, 9, 9, span); a.branch(5, 9, 0, closed)


def input_code():
    """a0 actor, a1 routed held word, a2 physical -> v0 kind (0, 1 next, 2 unlock, 4 aim, 5 after KO).

    Same ABI as lock-off INPUT, which it wraps (TAIL_INPUT runs the unchanged beta.33 logic).
    """
    import lockoff_target as off
    import lockon_queue as queue
    import quad_controller as quad
    import coop_controller as coop
    from input_script import RECORDS
    a = Assembler(INPUT2); save(a)
    a.move(16, 4); a.move(17, 5); a.move(18, 6)
    a.li(21, CONTROL); a.lw(8, 21); a.li(9, MAGIC); a.branch(5, 8, 9, 'legacy')
    a.lw(8, 21, 4); a.lw(9, 28, -22364); a.branch(4, 8, 9, 'owned')
    a.label('legacy'); a.move(4, 16); a.move(5, 17); a.move(6, 18); a.call(TAIL_INPUT); a.jump('return')
    a.label('owned')
    emit_row(a, 18, 19, off.ROWS, 5)                      # s3 lock-off row
    emit_row(a, 18, 20)                                   # s4 own row
    # A gap in this human's updates (death, takeover, cancelled captures) resets every latch.
    a.li(8, queue.CONTROL); a.lw(8, 8, queue.FIELDS['frames']); a.lw(9, 20, STAMP)
    a.addiu(9, 9, 1); a.branch(4, 8, 9, 'stamped')
    for field in range(4, STRIDE, 4): a.sw(0, 20, field)
    a.label('stamped'); a.sw(8, 20, STAMP)
    a.li(8, queue.CONTROL); a.lw(22, 8, queue.FIELDS['button'])   # s6 switch button
    a.move(23, 17)                                        # s7 gesture word (physical estimate)
    # A stale P3/P4 record still holds the word this code masked; the input is still physically held.
    a.lw(10, 20, MASK_BITS); a.branch(4, 10, 0, 'fresh')
    a.lw(9, 20, MASK_SEQ); a.addiu(8, 0, -1); a.branch(4, 9, 8, 'fresh')
    a.li(8, quad.CONTROL); a.lw(11, 8, 20); a.branch(5, 9, 11, 'fresh')
    a.lw(11, 8, 24); a.i(11, 11, 11, quad.LEASE); a.branch(4, 11, 0, 'fresh')
    a.r(0x25, 23, 23, 10)
    a.lw(8, 21, FIELDS['restored']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['restored'])
    a.label('fresh')
    a.move(15, 0); a.sw(15, 29, 0x48)                     # sp+0x48: aim direction this update
    a.lw(8, 21, FIELDS['stick']); a.branch(4, 8, 0, 'gesture_done')
    # R3 history (both modes): sp+0x64 keeps the value before this update (2: R3 was down on the last update).
    a.lw(9, 20, R3_GRACE); a.sw(9, 29, 0x64)
    a.i(12, 10, 23, R3); a.branch(4, 10, 0, 'r3_up'); a.addiu(9, 0, 2); a.jump('r3_kept')
    a.label('r3_up'); a.branch(4, 9, 0, 'r3_kept'); a.addiu(9, 9, -1)
    a.label('r3_kept'); a.sw(9, 20, R3_GRACE)
    a.addiu(9, 0, 2); a.branch(5, 8, 9, 'hold_mode')
    # The right stick alone (2). A deflection that starts from neutral while the gate is open is owned: all its stick
    # bits are masked until neutral, so the camera never twitches; one that starts with the gate closed, or without
    # a neutral update first, stays native until neutral. An owned flick after two neutral updates, with R3 up now
    # and on the two updates before, pends and aims on the next update, unless R3 is down then or the gate closed
    # (with CONTROL+16 set, only while the stick is still deflected). R3 itself is never masked.
    a.li(13, STICK); a.r(0x24, 13, 23, 13)                # t5 stick direction, first
    a.sw(0, 29, 0x68)                                     # sp+0x68: the gate is open (evaluated only when needed)
    a.lw(8, 20, PENDING); a.branch(5, 8, 0, 'alone_gate')
    a.branch(4, 13, 0, 'alone_neutral')
    a.lw(8, 20, STICK_LATCH); a.branch(5, 8, 0, 'alone_deflected')
    a.lw(8, 20, ARMED); a.branch(4, 8, 0, 'alone_deflected')
    a.label('alone_gate')
    emit_gate(a, 'alone_gated', 'alone')
    a.addiu(8, 0, 1); a.sw(8, 29, 0x68)
    a.label('alone_gated')
    a.li(13, STICK); a.r(0x24, 13, 23, 13)                # t5 again (the gate may call the rush owner)
    # Commit the aim that started on the last update, unless R3 arrived or the gate closed.
    a.lw(8, 20, PENDING); a.branch(4, 8, 0, 'alone_edge'); a.sw(0, 20, PENDING)
    a.lw(9, 29, 0x68); a.branch(4, 9, 0, 'alone_edge')
    a.i(12, 9, 23, R3); a.branch(5, 9, 0, 'alone_edge')
    a.lw(9, 21, FIELDS['confirm']); a.branch(4, 9, 0, 'commit'); a.branch(4, 13, 0, 'alone_edge')
    a.label('commit'); a.sw(8, 29, 0x48)
    # The switch button held at the commit (the hold-mode habit): one aim, and its release neither switches nor unlocks.
    a.r(0x24, 9, 23, 22); a.branch(4, 9, 0, 'alone_edge'); a.addiu(9, 0, 1); a.sw(9, 20, AIM_LATCH)
    a.label('alone_edge')
    a.branch(4, 13, 0, 'alone_neutral')
    a.lw(8, 20, STICK_LATCH); a.branch(5, 8, 0, 'alone_deflected')
    a.lw(8, 20, ARMED); a.branch(4, 8, 0, 'alone_deflected')      # not from neutral: native until neutral
    a.lw(9, 29, 0x68); a.branch(4, 9, 0, 'alone_deflected')       # gate closed: native until neutral
    a.addiu(9, 0, 1); a.sw(9, 20, STICK_LATCH)                    # owned until neutral
    a.i(11, 9, 8, 2); a.branch(5, 9, 0, 'alone_deflected')        # one neutral update only: owned, no aim
    a.i(12, 9, 23, R3); a.branch(5, 9, 0, 'alone_deflected')
    a.lw(9, 29, 0x64); a.branch(5, 9, 0, 'alone_deflected')       # R3 down on one of the two updates before
    a.sw(13, 20, PENDING)
    a.label('alone_deflected'); a.sw(0, 20, ARMED); a.jump('alone_mask')
    a.label('alone_neutral'); a.sw(0, 20, STICK_LATCH)
    a.lw(8, 20, ARMED); a.i(11, 9, 8, 2); a.branch(4, 9, 0, 'alone_mask'); a.addiu(8, 8, 1); a.sw(8, 20, ARMED)
    a.label('alone_mask')
    a.lw(14, 20, MASK_BITS); a.r(0x24, 14, 14, 23)
    a.lw(8, 20, STICK_LATCH); a.branch(4, 8, 0, 'mask_ready'); a.r(0x25, 14, 14, 13); a.jump('mask_ready')
    # Hold mode (1): the switch button held and a flick, one aim per return to neutral.
    a.label('hold_mode')
    a.r(0x24, 12, 23, 22)                                 # t4 held switch button
    a.li(13, STICK); a.r(0x24, 13, 23, 13)               # t5 stick direction
    a.branch(4, 12, 0, 'not_held')
    a.branch(5, 13, 0, 'deflected'); a.addiu(8, 0, 1); a.sw(8, 20, ARMED); a.jump('armed_done')
    a.label('deflected'); a.lw(8, 20, ARMED); a.branch(4, 8, 0, 'armed_done')
    a.sw(0, 20, ARMED); a.sw(13, 29, 0x48); a.addiu(8, 0, 1); a.sw(8, 20, AIM_LATCH); a.sw(8, 20, STICK_LATCH)
    a.jump('armed_done')
    a.label('not_held'); a.i(11, 8, 13, 1); a.sw(8, 20, ARMED)
    a.label('armed_done')
    a.branch(5, 13, 0, 'stick_kept'); a.sw(0, 20, STICK_LATCH); a.label('stick_kept')
    # Mask set: keep each suppressed bit until it is physically released; after an aim in this press
    # every stick direction is the aim's; from the flick until the stick is neutral, also R3 when it is newly pressed
    # there (an R3 already held at the aim is never hidden, so the actor never sees a false release).
    a.lw(14, 20, MASK_BITS); a.r(0x24, 14, 14, 23)
    a.lw(8, 20, AIM_LATCH); a.branch(4, 8, 0, 'no_aim_mask'); a.branch(4, 12, 0, 'no_aim_mask')
    a.r(0x25, 14, 14, 13); a.label('no_aim_mask')
    a.lw(8, 20, STICK_LATCH); a.branch(4, 8, 0, 'mask_ready'); a.i(12, 8, 23, R3); a.branch(4, 8, 0, 'mask_ready')
    a.lw(9, 29, 0x64); a.addiu(10, 0, 2); a.branch(4, 9, 10, 'mask_ready')
    a.r(0x25, 14, 14, 8)
    a.label('mask_ready')
    a.sw(14, 29, 0x50)
    a.branch(4, 14, 0, 'unmasked')
    a.move(4, 16); a.call(A(0x1DC2A0)); a.move(8, 2)     # the record the actor update reads
    a.li(9, coop.MERGED); a.branch(5, 8, 9, 'record')
    a.li(8, RECORDS)                                      # merged co-op control takes these bits from pad 0
    a.label('record')
    a.lw(9, 20, MASK_BITS); a.branch(4, 9, 0, 'latch_record')
    a.lw(9, 20, MASK_REC); a.branch(4, 9, 8, 'latch_record')
    # The resolved record changed: drop the latch (and an owned stick-alone flick and its pending aim).
    a.sw(0, 29, 0x50); a.sw(0, 20, STICK_LATCH); a.sw(0, 20, PENDING); a.jump('unmasked')
    a.label('latch_record'); a.sw(8, 20, MASK_REC)
    a.lw(14, 29, 0x50); a.lw(9, 8, 328); a.r(0x27, 10, 14, 0); a.r(0x24, 9, 9, 10); a.sw(9, 8, 328)
    for word in PRESSED: a.lw(9, 8, word); a.r(0x24, 9, 9, 10); a.sw(9, 8, word)
    a.addiu(10, 0, -1); a.li(9, quad.PADS); a.r(0x2B, 11, 8, 9); a.branch(5, 11, 0, 'sequence')
    a.addiu(9, 9, 2*quad.RECORD_STRIDE); a.r(0x2B, 11, 8, 9); a.branch(4, 11, 0, 'sequence')
    a.li(9, quad.CONTROL); a.lw(10, 9, 20)
    a.label('sequence'); a.sw(10, 20, MASK_SEQ)
    a.lw(9, 21, FIELDS['masked']); a.addiu(9, 9, 1); a.sw(9, 21, FIELDS['masked'])
    a.label('unmasked')
    a.lw(14, 29, 0x50); a.sw(14, 20, MASK_BITS); a.branch(5, 14, 0, 'mask_kept'); a.sw(0, 20, MASK_REC)
    a.label('mask_kept')
    # A release after an aim neither switches nor locks off.
    a.lw(8, 20, AIM_LATCH); a.branch(4, 8, 0, 'hold_rule'); a.sw(0, 19, off.SWITCH_HELD); a.sw(0, 20, HOLD2)
    a.li(8, off.CONTROL); a.lw(9, 8, 8); a.branch(5, 9, 22, 'hold_rule'); a.sw(0, 19, off.HELD)
    # Hold mode only: with a shared lock-off button, lock-off fires on release (after its hold time), so a flick
    # that starts late never unlocks first. The unchanged INPUT never reaches its threshold. With the stick alone,
    # lock-off fires while held (beta.33 timing).
    a.label('hold_rule')
    a.lw(8, 21, FIELDS['stick']); a.addiu(9, 0, 1); a.branch(5, 8, 9, 'gesture_done')
    a.li(8, off.CONTROL); a.lw(9, 8, 8); a.branch(5, 9, 22, 'gesture_done')
    a.lw(10, 8, 12); a.i(11, 11, 10, 2); a.branch(5, 11, 0, 'gesture_done')
    a.addiu(10, 10, -2); a.lw(9, 19, off.HELD); a.r(0x2B, 11, 10, 9); a.branch(4, 11, 0, 'held_ok')
    a.sw(10, 19, off.HELD); a.label('held_ok')
    a.r(0x24, 12, 23, 22); a.branch(4, 12, 0, 'gesture_done')
    a.lw(9, 20, HOLD2); a.lw(10, 8, 12); a.r(0x2B, 11, 9, 10); a.branch(4, 11, 0, 'gesture_done')
    a.addiu(9, 9, 1); a.sw(9, 20, HOLD2)
    a.label('gesture_done')
    a.lw(14, 20, MASK_BITS); a.r(0x27, 14, 14, 0); a.r(0x24, 5, 23, 14)
    a.move(4, 16); a.move(6, 18); a.call(TAIL_INPUT); a.move(17, 2)   # s1 kind from here on
    # Release decisions (only when this row owns the shared-button rule: hold mode).
    a.r(0x24, 12, 23, 22); a.branch(5, 12, 0, 'still_held')
    a.lw(8, 21, FIELDS['stick']); a.addiu(9, 0, 1); a.branch(5, 8, 9, 'released')
    a.li(8, off.CONTROL); a.lw(9, 8, 8); a.branch(5, 9, 22, 'released')
    a.lw(10, 8, 12); a.i(11, 11, 10, 2); a.branch(5, 11, 0, 'released')
    a.lw(9, 20, HOLD2); a.r(0x2B, 11, 9, 10); a.branch(5, 11, 0, 'released')
    a.lw(9, 20, AIM_LATCH); a.branch(5, 9, 0, 'released')
    a.addiu(17, 0, 2); a.sw(17, 19, off.KIND)
    a.lw(9, 21, FIELDS['release_unlocks']); a.addiu(9, 9, 1); a.sw(9, 21, FIELDS['release_unlocks'])
    a.label('released'); a.sw(0, 20, HOLD2); a.sw(0, 20, AIM_LATCH)
    a.label('still_held')
    a.lw(13, 29, 0x48); a.branch(4, 13, 0, 'no_aim'); a.addiu(8, 0, 2); a.branch(4, 17, 8, 'no_aim')
    a.addiu(17, 0, 4); a.sw(17, 19, off.KIND); a.sw(13, 20, ARG)
    a.label('no_aim')
    # After KO: a watched target that is defeated (present, not consumed, active-form health 0) on two
    # consecutive free-camera updates asks once for the enemy nearest this view's centre, chosen on the first
    # of them (before the camera turns to the game's replacement) and never re-chosen for the same defeat.
    # While a paired pause, shared rush or cinematic camera owns the view the count waits, so no choice is
    # measured on a cinematic frame. Transformation reads and fusion consumption are not defeats; an unlocked
    # player is never relocked. A target seen alive again (revived), or a watch on another target, makes its
    # next defeat a new KO.
    a.lw(8, 21, FIELDS['after_ko']); a.branch(4, 8, 0, 'return_kind')
    core.gate(a, 'return_kind'); a.sw(10, 29, 0x58)
    a.li(8, core.TABLE); a.r(0, 9, 0, 18, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.sw(8, 29, 0x5C)
    a.lw(9, 20, WATCH); a.branch(5, 9, 0, 'watching')
    a.addiu(9, 8, 1); a.sw(9, 20, WATCH); a.sw(0, 20, DEADN); a.sw(0, 20, KO_LATCH); a.sw(0, 20, KO_SEEN)
    a.jump('return_kind')
    a.label('watching'); a.addiu(9, 9, -1); a.sw(9, 29, 0x60)
    a.lw(10, 29, 0x58); a.r(0x2B, 10, 9, 10); a.branch(4, 10, 0, 'not_defeated')
    a.branch(4, 9, 18, 'not_defeated')
    a.lw(12, 29, 0x60); emit_present(a, 12, 'not_defeated')
    a.lw(12, 29, 0x60); emit_actor(a, 12, 11, 'not_defeated')
    emit_health(a, 11, 'watched_alive', alive=False)
    emit_view_owned(a, 'return_kind', 'ko_view')          # the count waits for a free camera
    a.lw(8, 20, DEADN); a.i(11, 9, 8, 2); a.branch(4, 9, 0, 'confirmed'); a.branch(5, 8, 0, 'counted')
    a.lw(9, 20, KO_SEEN); a.branch(5, 9, 0, 'counted')   # chosen once per defeat
    a.move(4, 18); a.call(off.PICK); a.addiu(2, 2, 1); a.sw(2, 20, KO_SEEN)
    # Nobody was visible when this defeat was confirmed: a request still waiting for its safe point takes this.
    a.lw(8, 20, WATCH); a.lw(9, 20, KO_LATCH); a.branch(5, 8, 9, 'seen'); a.sw(2, 20, KO_PICK)
    a.label('seen'); a.lw(8, 20, DEADN)
    a.label('counted'); a.addiu(8, 8, 1); a.sw(8, 20, DEADN)
    a.i(11, 9, 8, 2); a.branch(5, 9, 0, 'return_kind')
    a.label('confirmed')
    a.lw(8, 20, WATCH); a.lw(9, 20, KO_LATCH); a.branch(4, 8, 9, 'follow_table')
    a.sw(8, 20, KO_LATCH)
    a.branch(5, 17, 0, 'follow_table'); a.lw(8, 19, off.OFF); a.branch(5, 8, 0, 'follow_table')
    a.addiu(17, 0, 5); a.sw(17, 19, off.KIND); a.lw(8, 20, KO_SEEN); a.sw(8, 20, KO_PICK)
    a.label('follow_table'); a.lw(8, 29, 0x5C); a.addiu(8, 8, 1); emit_rewatch(a, 8, 'followed'); a.sw(0, 20, DEADN)
    a.jump('return_kind')
    a.label('watched_alive'); emit_health(a, 11, 'not_defeated')   # alive, not an invalid form row
    a.sw(0, 20, KO_LATCH)
    a.label('not_defeated'); a.sw(0, 20, DEADN); a.sw(0, 20, KO_SEEN)
    a.lw(8, 29, 0x5C); a.lw(9, 29, 0x60); a.branch(4, 8, 9, 'return_kind')
    a.addiu(8, 8, 1); a.sw(8, 20, WATCH); a.sw(0, 20, KO_LATCH)
    a.label('return_kind'); a.move(2, 17)
    a.label('return'); restore(a); data = a.finish(); assert len(data) <= APPLY2-INPUT2; return data


def apply_code():
    """a0 actor, a1 physical -> v0 1 (always consumed; the queue's own inline search is not used)."""
    import lockoff_target as off
    import lockon_queue as queue
    a = Assembler(APPLY2); save(a)
    a.move(16, 4); a.move(17, 5)
    a.li(21, CONTROL); a.lw(8, 21); a.li(9, MAGIC); a.branch(5, 8, 9, 'legacy')
    a.lw(8, 21, 4); a.lw(9, 28, -22364); a.branch(4, 8, 9, 'owned')
    a.label('legacy'); a.move(4, 16); a.move(5, 17); a.call(TAIL_APPLY); a.jump('return')
    a.label('owned')
    emit_row(a, 17, 19, off.ROWS, 5); emit_row(a, 17, 20)
    a.lw(18, 19, off.KIND)
    a.addiu(8, 0, 2); a.branch(4, 18, 8, 'native')          # unlock: the beta.33 path
    a.lw(8, 19, off.OFF); a.branch(4, 8, 0, 'locked')
    a.addiu(8, 0, 1); a.branch(4, 18, 8, 'native')          # unlocked tap: nearest the view centre
    a.addiu(8, 0, 4); a.branch(5, 18, 8, 'consumed')        # a KO retarget never relocks
    a.move(4, 17); a.lw(5, 20, ARG); a.addiu(6, 0, 1); a.call(AIM); a.branch(1, 2, 0, 'unchanged')
    a.move(22, 2)
    a.li(8, core.TABLE); a.r(0, 9, 0, 17, 2); a.r(0x21, 8, 8, 9); a.sw(22, 8)
    a.sw(0, 19, off.OFF); a.addiu(8, 0, 2); a.sw(8, 19, off.QUIET)
    a.move(4, 16); a.addiu(5, 0, 5); a.call(A(0x1DA9D0))
    a.jump('changed_aim')
    a.label('native'); a.move(4, 16); a.move(5, 17); a.call(TAIL_APPLY)
    a.addiu(8, 0, 1); a.branch(5, 18, 8, 'watch_table')
    a.lw(8, 19, off.OFF); a.branch(5, 8, 0, 'watch_table')   # the reacquire found nobody
    a.lw(8, 21, FIELDS['aims']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['aims'])
    a.label('watch_table')
    a.li(8, core.TABLE); a.r(0, 9, 0, 17, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.addiu(8, 8, 1)
    emit_rewatch(a, 8, 'watched'); a.sw(0, 20, DEADN); a.jump('consumed')
    a.label('locked')
    a.li(8, core.TABLE); a.r(0, 9, 0, 17, 2); a.r(0x21, 8, 8, 9); a.lw(23, 8)   # s7 current target
    a.addiu(8, 0, 1); a.branch(5, 18, 8, 'stick')
    a.move(4, 17); a.addiu(5, 0, 1); a.lw(6, 21, FIELDS['order']); a.call(ORDER); a.jump('decided')
    a.label('stick'); a.addiu(8, 0, 4); a.branch(5, 18, 8, 'after_ko')
    a.lw(9, 20, ARG); a.li(8, RIGHT); a.r(0x24, 8, 9, 8); a.branch(5, 8, 0, 'step_right')
    a.li(8, LEFT); a.r(0x24, 8, 9, 8); a.branch(5, 8, 0, 'step_left')
    a.move(4, 17); a.move(5, 9); a.move(6, 0); a.call(AIM); a.jump('aimed')
    a.label('step_right'); a.move(4, 17); a.addiu(5, 0, 1); a.move(6, 0); a.call(ORDER); a.jump('decided')
    a.label('step_left'); a.move(4, 17); a.addiu(5, 0, -1); a.move(6, 0); a.call(ORDER); a.jump('decided')
    a.label('after_ko'); a.addiu(8, 0, 5); a.branch(5, 18, 8, 'unchanged')
    # The choice made when the target fell, if that enemy is still a valid living enemy; otherwise PICK now.
    a.lw(22, 20, KO_PICK); a.sw(0, 20, KO_PICK); a.branch(4, 22, 0, 'fresh_pick'); a.addiu(22, 22, -1)
    core.gate(a, 'fresh_pick'); a.r(0x2B, 8, 22, 10); a.branch(4, 8, 0, 'fresh_pick')
    emit_candidate(a, 22, 17, 11, 13, 'fresh_pick', 'ko_enemy')
    a.move(2, 22); a.jump('ko_picked')
    a.label('fresh_pick'); a.move(4, 17); a.call(off.PICK)
    a.label('ko_picked')
    a.branch(1, 2, 0, 'unchanged'); a.branch(4, 2, 23, 'unchanged'); a.move(22, 2)
    a.lw(8, 21, FIELDS['ko']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['ko']); a.jump('change')
    a.label('aimed'); a.branch(1, 2, 0, 'unchanged'); a.branch(4, 2, 23, 'unchanged'); a.move(22, 2)
    a.label('changed_aim')
    a.lw(8, 21, FIELDS['aims']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['aims']); a.jump('change')
    a.label('decided'); a.branch(1, 2, 0, 'unchanged'); a.branch(4, 2, 23, 'unchanged'); a.move(22, 2)
    a.lw(8, 21, FIELDS['steps']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['steps'])
    a.label('change')
    a.li(8, core.TABLE); a.r(0, 9, 0, 17, 2); a.r(0x21, 8, 8, 9); a.sw(22, 8)
    a.addiu(8, 22, 1); emit_rewatch(a, 8, 'changed'); a.sw(0, 20, DEADN)
    a.li(8, queue.CONTROL); a.lw(9, 8, queue.FIELDS['switches']); a.addiu(9, 9, 1); a.sw(9, 8, queue.FIELDS['switches'])
    a.r(0, 9, 0, 17, 2); a.r(0x21, 8, 8, 9)
    a.lw(9, 8, queue.FIELDS['per_actor']); a.addiu(9, 9, 1); a.sw(9, 8, queue.FIELDS['per_actor'])
    a.jump('consumed')
    a.label('unchanged'); a.lw(8, 21, FIELDS['unchanged']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['unchanged'])
    a.label('consumed'); a.addiu(2, 0, 1)
    a.label('return'); restore(a); data = a.finish(); assert len(data) <= ORDER-APPLY2; return data


def emit_key(a, model, viewer_model, index, tag):
    """t4 = unique rank of candidate at index for this viewer (s2 order mode; sp+0x74 side flag).

    circle (0): pseudo-angle of (±dx, dz) on the horizontal plane, one division, read from the float bits
    of 4 + quadrant + fraction in [4, 8): monotonic, no conversion instruction; |dx|+|dz| < 1 is angle 0.
    nearest (1): squared straight-line distance, float bits 30..9 (positive floats order as integers).
    slot (2): the slot. Every key is (22-bit rank << 4) | slot.
    """
    a.addiu(8, 0, 2); a.branch(4, 18, 8, tag+'_slot')
    lwc1(a, 0, model, 2416); lwc1(a, 1, viewer_model, 2416); fop(a, 1, 0, 0, 1)
    lwc1(a, 2, model, 2424); lwc1(a, 3, viewer_model, 2424); fop(a, 1, 2, 2, 3)
    a.branch(5, 18, 0, tag+'_nearest')
    a.lw(8, 29, 0x74); a.branch(4, 8, 0, tag+'_signed'); mtc1(a, 0, 6); fop(a, 1, 0, 6, 0)
    a.label(tag+'_signed')
    fop(a, 5, 4, 0); fop(a, 5, 5, 2); fop(a, 0, 4, 4, 5)
    a.li(8, ONE); mtc1(a, 8, 6); fop(a, 0x34, 0, 4, 6); a.branch(17, 8, 1, tag+'_zero')
    mfc1(a, 8, 0); mfc1(a, 9, 2)
    a.branch(1, 9, 0, tag+'_below')
    a.branch(1, 8, 0, tag+'_second')
    fop(a, 6, 5, 2); a.li(8, FOUR); a.jump(tag+'_divide')
    a.label(tag+'_second'); fop(a, 5, 5, 0); a.li(8, FOUR+0x200000); a.jump(tag+'_divide')
    a.label(tag+'_below'); a.branch(1, 8, 1, tag+'_fourth')
    fop(a, 5, 5, 2); a.li(8, FOUR+0x400000); a.jump(tag+'_divide')
    a.label(tag+'_fourth'); fop(a, 6, 5, 0); a.li(8, FOUR+0x600000)
    a.label(tag+'_divide'); fop(a, 3, 7, 5, 4); mtc1(a, 8, 8); fop(a, 0, 7, 7, 8)
    mfc1(a, 12, 7); a.r(0, 12, 0, 12, 9); a.r(2, 12, 0, 12, 10); a.jump(tag+'_rank')
    a.label(tag+'_zero'); a.move(12, 0); a.jump(tag+'_rank')
    a.label(tag+'_nearest')
    lwc1(a, 4, model, 2420); lwc1(a, 5, viewer_model, 2420); fop(a, 1, 4, 4, 5)
    fop(a, 2, 0, 0, 0); fop(a, 2, 2, 2, 2); fop(a, 2, 4, 4, 4); fop(a, 0, 0, 0, 2); fop(a, 0, 0, 0, 4)
    mfc1(a, 12, 0); a.r(2, 12, 0, 12, 9); a.jump(tag+'_rank')
    a.label(tag+'_slot'); a.move(12, index)
    a.label(tag+'_rank'); a.r(0, 12, 0, 12, 4); a.r(0x25, 12, 12, index)


def order_code():
    """a0 viewer, a1 step (1 next / -1 previous), a2 mode -> v0 new target or -1.

    Candidates are exactly PICK's (without projection). The current target keeps its key even as a
    fresh corpse; next is the smallest key above it (wrapping), previous the largest below it.
    """
    a = Assembler(ORDER); save(a)
    a.move(16, 4); a.move(17, 5); a.move(18, 6); a.addiu(2, 0, -1)
    core.gate(a, 'return'); a.move(19, 10)
    a.li(8, core.TABLE); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(22, 8)   # s6 current target
    a.li(21, CONTROL); a.sw(16, 21, FIELDS['viewer'])
    a.addiu(8, 0, 2); a.branch(4, 18, 8, 'modelled')
    emit_actor(a, 16, 20, 'slot_order'); emit_model(a, 20, 23, 'slot_order', drawn=False)
    a.jump('modelled')
    a.label('slot_order'); a.addiu(18, 0, 2)
    a.label('modelled')
    a.lw(8, 21, FIELDS['side']); a.sw(8, 29, 0x74)
    # Keys (sp+0x80.. 12 words) of every candidate, and of the current target from its position.
    a.addiu(8, 0, -1); a.sw(8, 29, 0x78)
    a.move(20, 0)
    a.label('keys'); a.r(0x2B, 8, 20, 19); a.branch(4, 8, 0, 'current')
    a.addiu(12, 0, -1); a.branch(4, 20, 16, 'store')
    emit_candidate(a, 20, 16, 13, 11, 'store_invalid', 'order_enemy')
    emit_key(a, 11, 23, 20, 'candidate')
    a.jump('store')
    a.label('store_invalid'); a.addiu(12, 0, -1)
    a.label('store'); a.r(0, 8, 0, 20, 2); a.r(0x21, 8, 8, 29); a.sw(12, 8, 0x80)
    a.r(0x21, 8, 8, 21); a.r(0x23, 8, 8, 29); a.sw(12, 8, FIELDS['keys'])
    a.addiu(20, 20, 1); a.jump('keys')
    a.label('current')
    for i in range(modes.ENGINE_ACTORS):   # clear keys of slots past the count for the readout
        a.addiu(8, 0, i); a.r(0x2B, 8, 8, 19); a.branch(5, 8, 0, f'kept{i}')
        a.addiu(8, 0, -1); a.sw(8, 21, FIELDS['keys']+4*i); a.label(f'kept{i}')
    a.r(0x2B, 8, 22, 19); a.branch(4, 8, 0, 'select'); a.branch(4, 22, 16, 'select')
    a.move(20, 22); a.addiu(8, 0, 2); a.branch(4, 18, 8, 'current_key')   # slot order needs no position
    emit_actor(a, 20, 13, 'select'); emit_model(a, 13, 11, 'select', drawn=False)
    a.label('current_key')
    emit_key(a, 11, 23, 20, 'current')
    a.sw(12, 29, 0x78)
    # Select: t4 current key; above-min (s4), global-min (s5), below-max+1 (s6..sp), global-max+1.
    a.label('select')
    a.lw(12, 29, 0x78); a.addiu(20, 0, -1); a.addiu(21, 0, -1); a.sw(0, 29, 0x70); a.sw(0, 29, 0x6C)
    a.move(13, 0)
    a.label('scan'); a.r(0x2B, 8, 13, 19); a.branch(4, 8, 0, 'pick')
    a.r(0, 8, 0, 13, 2); a.r(0x21, 8, 8, 29); a.lw(14, 8, 0x80)
    a.addiu(8, 0, -1); a.branch(4, 14, 8, 'scanned'); a.branch(4, 14, 12, 'scanned')
    a.r(0x2B, 8, 14, 21); a.branch(4, 8, 0, 'global_min'); a.move(21, 14)
    a.label('global_min')
    a.addiu(15, 14, 1); a.lw(9, 29, 0x6C); a.r(0x2B, 8, 9, 15); a.branch(4, 8, 0, 'global_max'); a.sw(15, 29, 0x6C)
    a.label('global_max')
    a.r(0x2B, 8, 12, 14); a.branch(4, 8, 0, 'below')
    a.r(0x2B, 8, 14, 20); a.branch(4, 8, 0, 'scanned'); a.move(20, 14); a.jump('scanned')
    a.label('below'); a.lw(9, 29, 0x70); a.r(0x2B, 8, 9, 15); a.branch(4, 8, 0, 'scanned'); a.sw(15, 29, 0x70)
    a.label('scanned'); a.addiu(13, 13, 1); a.jump('scan')
    a.label('pick'); a.addiu(2, 0, -1); a.branch(6, 17, 0, 'previous')
    a.move(8, 20); a.addiu(9, 0, -1); a.branch(5, 8, 9, 'found'); a.move(8, 21); a.jump('found')
    a.label('previous'); a.lw(8, 29, 0x70); a.branch(5, 8, 0, 'found_max'); a.lw(8, 29, 0x6C)
    a.label('found_max'); a.addiu(8, 8, -1)
    a.label('found'); a.addiu(9, 0, -1); a.branch(4, 8, 9, 'result')
    a.i(12, 2, 8, 15); a.branch(5, 2, 22, 'result'); a.addiu(2, 0, -1)
    a.label('result'); a.li(21, CONTROL); a.sw(2, 21, FIELDS['result'])
    a.label('return'); restore(a); data = a.finish(); assert len(data) <= AIM-ORDER; return data


def aim_code():
    """a0 viewer, a1 stick direction bits, a2 from the view centre -> v0 enemy or -1.

    Reference: the current target's projected point (locked, in front) or the viewport centre. A
    candidate in front of the camera (off the viewport allowed) must lie along the direction within
    +-60 degrees (4*perp <= 7*along); the lowest along + 2*perp wins, ties by the lower slot.
    """
    from lockoff_target import CAMERA  # noqa: F401  (emit_camera)
    a = Assembler(AIM); save(a)
    a.move(16, 4); a.move(17, 5); a.move(18, 6); a.addiu(21, 0, -1)
    core.gate(a, 'return'); a.move(19, 10)
    emit_camera(a, 16, 22, 'return')
    emit_push(a, 22)
    emit_centre(a, 22, 8, 512, 516, 1792); a.sw(8, 29, 0xB0)
    emit_centre(a, 22, 8, 520, 524, Y_ORIGIN); a.sw(8, 29, 0xB4)
    a.branch(5, 18, 0, 'referenced')
    a.li(8, core.TABLE); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(20, 8)
    a.r(0x2B, 8, 20, 19); a.branch(4, 8, 0, 'referenced'); a.branch(4, 20, 16, 'referenced')
    emit_actor(a, 20, 23, 'referenced'); emit_model(a, 23, 23, 'referenced')
    emit_anchor(a, 23, 47, 'reference'); emit_project(a, 'referenced')
    a.lw(8, 29, 0x80); a.sw(8, 29, 0xB0); a.lw(8, 29, 0x84); a.sw(8, 29, 0xB4)
    a.label('referenced')
    a.li(8, 0x7FFFFFFF); a.sw(8, 29, 0xB8)
    a.move(20, 0)
    a.label('loop'); a.r(0x2B, 8, 20, 19); a.branch(4, 8, 0, 'pop'); a.branch(4, 20, 16, 'next')
    emit_candidate(a, 20, 16, 13, 23, 'next', 'aim_enemy')
    emit_anchor(a, 23, 47, 'anchor'); emit_project(a, 'next')
    a.lw(12, 29, 0x80); a.lw(8, 29, 0xB0); a.r(0x23, 12, 12, 8)     # t4 dx
    a.lw(13, 29, 0x84); a.lw(8, 29, 0xB4); a.r(0x23, 13, 13, 8)     # t5 dy
    a.li(8, RIGHT); a.r(0x24, 8, 17, 8); a.branch(4, 8, 0, 'not_right'); a.move(14, 12); a.move(15, 13)
    a.jump('axis')
    a.label('not_right'); a.li(8, LEFT); a.r(0x24, 8, 17, 8); a.branch(4, 8, 0, 'not_left')
    a.r(0x23, 14, 0, 12); a.move(15, 13); a.jump('axis')
    a.label('not_left'); a.li(8, DOWN); a.r(0x24, 8, 17, 8); a.branch(4, 8, 0, 'up')
    a.move(14, 13); a.move(15, 12); a.jump('axis')
    a.label('up'); a.r(0x23, 14, 0, 13); a.move(15, 12)
    a.label('axis')                                               # t6 along, t7 perpendicular
    a.branch(6, 14, 0, 'next')
    a.branch(1, 15, 1, 'positive'); a.r(0x23, 15, 0, 15); a.label('positive')
    a.r(0, 8, 0, 15, 2); a.r(0, 9, 0, 14, 3); a.r(0x23, 9, 9, 14); a.r(0x2A, 9, 9, 8); a.branch(5, 9, 0, 'next')
    a.r(0x21, 8, 15, 15); a.r(0x21, 8, 8, 14)
    a.lw(9, 29, 0xB8); a.r(0x2A, 9, 8, 9); a.branch(4, 9, 0, 'next'); a.sw(8, 29, 0xB8); a.move(21, 20)
    a.label('next'); a.addiu(20, 20, 1); a.jump('loop')
    a.label('pop'); a.call(A(0x120AC8))
    a.label('return'); a.li(8, CONTROL); a.sw(21, 8, FIELDS['aim_result']); a.move(2, 21); restore(a)
    data = a.finish(); assert len(data) <= MARKER-AIM; return data


def marker_code():
    """Per-view pass: MARKER is called by the overhead-bar wrapper instead of display_settings.BAR_DRAW (one or two
    native views; the bars are drawn last), QMARKER (a0 = 0, entering at MARKER+4) by the quad renderer's per-view
    extension list (three and four views, two players with a team assignment; no bars there).

    In active combat only (battle state 3, no result screen, no paired/rush/cinematic camera owner), this view's own
    seat (quad CAMERAS by rectangle, otherwise display_settings.SUBJECT of the active camera) is found and its target
    validated before any projection; a locked living human's enemy target gets the style's indicator: the gold arrow
    above its lifted head (the ARROW_PACKET template copied and moved to the tip) and/or the target ring around its
    body centre (the vertices generated from RING_TABLE, sized by SIZE); one allocation and submission each.
    """
    import display_settings as display
    import guest_healthbars as bars
    import lockoff_target as off
    import lockon_queue as queue
    import quad_viewports as views
    import rush_cinematics as rush
    from guest_healthbars import valid_pointer
    from result_presentation import RESULT
    import lockon_threat as threat
    a = Assembler(MARKER); a.addiu(4, 0, 1); save(a); a.sw(4, 29, M_NATIVE)
    a.li(21, CONTROL); a.lw(8, 21); a.li(9, MAGIC); a.branch(5, 8, 9, 'return')
    a.lw(8, 21, 4); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'return')
    a.lw(8, 21, FIELDS['marker']); a.branch(4, 8, 0, 'return')
    a.li(8, A(0x2FEB38)); a.lw(11, 8); valid_pointer(a, 11, 'return', 0x200)
    a.lw(9, 11); a.addiu(10, 0, 3); a.branch(5, 9, 10, 'return')
    a.li(8, RESULT); a.lw(8, 8); a.branch(5, 8, 0, 'return')
    core.gate(a, 'return'); a.move(19, 10)
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'return')
    rush.emit_hud_gate(a, 'return', 'marker_rush')
    a.li(8, A(0x2FEBCC)); a.lw(11, 8); a.branch(4, 11, 0, 'free_camera')
    valid_pointer(a, 11, 'return', 816); a.lw(8, 11, 812); a.branch(5, 8, 0, 'return')
    a.label('free_camera')
    a.lw(22, 28, -22176); valid_pointer(a, 22, 'return', 0x300); emit_viewport(a, 22, 'return')
    # This view's seat.
    a.li(8, views.CONTROL); a.lw(9, 8); a.li(10, views.MAGIC); a.branch(5, 9, 10, 'single')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'single')
    a.lw(12, 8, views.VIEW_COUNT); a.i(11, 9, 12, 5); a.branch(4, 9, 0, 'return')
    a.move(13, 0); a.li(14, views.CAMERAS)
    a.label('views'); a.branch(4, 13, 12, 'return')
    for off_ in (512, 516, 520, 524):
        a.lw(9, 14, off_); a.lw(10, 22, off_); a.branch(5, 9, 10, 'other_view')
    a.r(0, 9, 0, 13, 2); a.li(10, views.SUBJECTS); a.r(0x21, 9, 9, 10); a.lw(16, 9); a.jump('seat')
    a.label('other_view'); a.addiu(13, 13, 1); a.addiu(14, 14, 1024); a.jump('views')
    a.label('single'); a.move(4, 22); a.call(display.SUBJECT); a.move(16, 2)
    a.label('seat')
    a.r(0x2B, 8, 16, 19); a.branch(4, 8, 0, 'return')
    emit_actor(a, 16, 17, 'return'); a.lw(8, 17, 0x1278); a.branch(5, 8, 0, 'return')
    emit_health(a, 17, 'return')
    a.move(4, 16); a.call(off.IS_OFF); a.branch(5, 2, 0, 'unmark')    # unlocked: a relock drops in again
    a.li(8, core.TABLE); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(18, 8)
    a.r(0x2B, 8, 18, 19); a.branch(4, 8, 0, 'return')
    emit_candidate(a, 18, 16, 17, 23, 'return', 'marker_enemy')
    emit_push(a, 22)
    a.sw(23, 29, M_MODEL)
    # This seat's mark: the target last drawn and the queue update when it changed (drop-in, bob and ring scale).
    a.r(0, 8, 0, 16, 3); a.li(17, MARKS); a.r(0x21, 17, 17, 8)                # s1 this seat's mark
    a.li(8, queue.CONTROL); a.lw(20, 8, queue.FIELDS['frames'])                 # s4 queue updates
    a.lw(8, 17, 0); a.addiu(9, 18, 1); a.branch(4, 8, 9, 'marked'); a.sw(9, 17, 0); a.sw(20, 17, 4)
    a.label('marked'); a.lw(8, 17, 4); a.r(0x23, 8, 20, 8); a.sw(8, 29, M_AGE)  # age (unsigned)
    a.sw(20, 29, M_FRAMES)
    a.lw(8, 21, FIELDS['style']); a.sw(8, 29, M_STYLE)
    a.i(12, 9, 8, 1); a.branch(4, 9, 0, 'ring')
    # The arrow: above the lifted head (the overhead bars' lift), its tip clamped so the whole dart stays in view.
    emit_anchor(a, 23, 48, 'head')
    a.addiu(4, 29, 0xA0); a.li(6, bars.CONTROL+0x80); a.call(A(0x121ED8))
    a.addiu(5, 29, 0xA0); emit_project(a, 'ring')
    for coord, lo, hi, origin in ((0x80, 512, 516, 1792), (0x84, 520, 524, Y_ORIGIN)):
        a.lw(10, 29, coord)
        a.lw(8, 22, lo); a.addiu(8, 8, origin); a.r(0, 8, 0, 8, 4); a.r(0x2A, 9, 10, 8); a.branch(5, 9, 0, 'ring')
        a.lw(8, 22, hi); a.addiu(8, 8, origin+1); a.r(0, 8, 0, 8, 4); a.r(0x2A, 9, 10, 8); a.branch(4, 9, 0, 'ring')
    a.lw(8, 29, M_AGE)
    a.move(10, 0); a.i(11, 9, 8, len(LIFT)); a.branch(4, 9, 0, 'lifted')
    a.li(9, ARROW_LIFT); a.r(0x21, 9, 9, 8); a.i(36, 10, 9, 0)                 # lbu t2, LIFT[age]
    a.label('lifted'); a.r(0, 10, 0, 10, 4)                                     # sixteenths
    left, right, up, down = MARGIN
    a.lw(12, 29, 0x80)
    a.lw(8, 22, 512); a.addiu(8, 8, 1792+left); a.r(0, 8, 0, 8, 4)
    a.r(0x2A, 9, 12, 8); a.branch(4, 9, 0, 'x_min'); a.move(12, 8)
    a.label('x_min'); a.lw(8, 22, 516); a.addiu(8, 8, 1792-right); a.r(0, 8, 0, 8, 4)
    a.r(0x2A, 9, 8, 12); a.branch(4, 9, 0, 'x_max'); a.move(12, 8)
    a.label('x_max')
    a.lw(13, 29, 0x84); a.addiu(13, 13, -TIP_GAP*16); a.r(0x23, 13, 13, 10)
    a.lw(8, 22, 520); a.addiu(8, 8, Y_ORIGIN+up); a.r(0, 8, 0, 8, 4)
    a.r(0x2A, 9, 13, 8); a.branch(4, 9, 0, 'y_min'); a.move(13, 8)
    a.label('y_min'); a.lw(8, 22, 524); a.addiu(8, 8, Y_ORIGIN-down); a.r(0, 8, 0, 8, 4)
    a.r(0x2A, 9, 8, 13); a.branch(4, 9, 0, 'y_max'); a.move(13, 8)
    a.label('y_max'); a.r(0, 13, 0, 13, 16); a.r(0x21, 20, 13, 12)             # s4 (tipy << 16) + tipx
    # Copy the template and add the tip to every XYZ2 low word (its packed halves stay within 0..65535).
    a.call(A(0x100878))
    size, count = len(packet_template()), len(ARROW_VERTICES)
    a.li(8, ARROW_PACKET); a.move(9, 2); a.addiu(10, 8, size)
    a.label('copy'); a.lw(11, 8, 0); a.sw(11, 9, 0); a.addiu(8, 8, 4); a.addiu(9, 9, 4)
    a.branch(5, 8, 10, 'copy')
    a.addiu(9, 2, 112+8); a.addiu(10, 9, 16*count)
    a.label('patch'); a.lw(11, 9, 0); a.r(0x21, 11, 11, 20); a.sw(11, 9, 0); a.addiu(9, 9, 16)
    a.branch(5, 9, 10, 'patch')
    a.addiu(4, 2, size); a.call(A(0x100890))
    a.lw(8, 21, FIELDS['markers']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['markers'])
    # The ring: around the body centre, its radius from the target's on-screen size.
    a.label('ring')
    a.lw(8, 29, M_STYLE); a.i(12, 9, 8, 2); a.branch(4, 9, 0, 'pop')
    a.lw(23, 29, M_MODEL)
    emit_body_centre(a, 23, 0xA0, 'body')
    emit_project(a, 'pop')
    for coord, lo, hi, origin in ((0x80, 512, 516, 1792), (0x84, 520, 524, Y_ORIGIN)):
        a.lw(10, 29, coord)
        a.lw(8, 22, lo); a.addiu(8, 8, origin); a.r(0, 8, 0, 8, 4); a.r(0x2A, 9, 10, 8); a.branch(5, 9, 0, 'pop')
        a.lw(8, 22, hi); a.addiu(8, 8, origin+1); a.r(0, 8, 0, 8, 4); a.r(0x2A, 9, 10, 8); a.branch(4, 9, 0, 'pop')
    a.lw(4, 29, M_MODEL); a.move(5, 22); a.call(SIZE); a.move(11, 2)          # t3 Rv16 (this target, this view)
    a.sw(3, 21, FIELDS['size_h']); a.sw(2, 21, FIELDS['size_r'])               # telemetry: the last H and Rv
    a.lw(8, 29, M_AGE)
    a.addiu(10, 0, 256); a.i(11, 9, 8, len(SCALE)); a.branch(4, 9, 0, 'scaled')
    a.li(9, RING_SCALE); a.r(0, 8, 0, 8, 2); a.r(0x21, 9, 9, 8); a.lw(10, 9)
    a.label('scaled')
    # The drawn radius r (s7), the band, and the chevron tips at 1.12 r.
    a.r(24, 0, 11, 10); a.r(18, 23, 0, 0); a.r(3, 23, 0, 23, 8); a.sw(23, 29, M_RADIUS)
    a.r(3, 8, 0, 23, 4); a.addiu(9, 0, BAND_MIN); a.r(0x2A, 10, 8, 9); a.branch(4, 10, 0, 'banded'); a.move(8, 9)
    a.label('banded'); a.sw(8, 29, M_BAND)
    a.addiu(8, 0, TIP_FRAC); a.r(24, 0, 23, 8); a.r(18, 8, 0, 0); a.r(3, 8, 0, 8, 8); a.sw(8, 29, M_TIP)
    # The centre, kept inside this view by Rv/2 (the scissor clips the rest of the ring).
    a.r(3, 11, 0, 11, 1)
    for coord, lo, hi, origin, slot in ((0x80, 512, 516, 1792, M_X), (0x84, 520, 524, Y_ORIGIN, M_Y)):
        a.lw(12, 29, coord)
        a.lw(8, 22, lo); a.addiu(8, 8, origin); a.r(0, 8, 0, 8, 4); a.r(0x21, 8, 8, 11)
        a.r(0x2A, 9, 12, 8); a.branch(4, 9, 0, f'min{slot}'); a.move(12, 8)
        a.label(f'min{slot}')
        a.lw(8, 22, hi); a.addiu(8, 8, origin+1); a.r(0, 8, 0, 8, 4); a.r(0x23, 8, 8, 11)
        a.r(0x2A, 9, 8, 12); a.branch(4, 9, 0, f'max{slot}'); a.move(12, 8)
        a.label(f'max{slot}'); a.sw(12, 29, slot)
    # The chevrons' colour: pale yellow; while this target attacks you (lockon_threat's marks and warning, a fresh
    # record) they blink like its marks (warn_a when queue.frames & BLINK, else warn_b). The rings stay yellow.
    a.lw(20, 29, M_FRAMES)
    a.li(8, CHEV); a.sw(8, 29, M_COLOUR)
    threat.emit_owned(a, 'coloured')
    a.lw(9, 8, threat.FIELDS['marks']); a.addiu(10, 0, 2); a.branch(5, 9, 10, 'coloured')
    emit_row(a, 16, 9, threat.ROWS)
    a.lw(10, 9, threat.STAMP); a.r(0x23, 10, 20, 10); a.i(11, 10, 10, 2); a.branch(4, 10, 0, 'coloured')
    a.lw(10, 9, threat.ATK); a.addiu(11, 0, 1); a.r(4, 11, 18, 11); a.r(0x24, 10, 10, 11)
    a.branch(4, 10, 0, 'coloured')
    a.li(8, threat.CONTROL); a.lw(9, 8, threat.FIELDS['blink']); a.r(0x24, 9, 9, 20)
    a.lw(10, 8, threat.FIELDS['warn_a']); a.branch(5, 9, 0, 'warned'); a.lw(10, 8, threat.FIELDS['warn_b'])
    a.label('warned'); a.sw(10, 29, M_COLOUR)
    a.label('coloured')
    # One packet: the dark rim, the outer ring and the inner ring (strips), then the two chevrons.
    emit_packet_begin(a, 19, 'ring_header')
    for colour, part in ((DARK, 'rim'), (RING, 'outer'), (RING, 'inner')):
        emit_segment(a, 19, PRIM_STRIP, 2*(SEGMENTS+1), colour)
        a.lw(9, 29, M_BAND)
        if part == 'rim':
            a.r(3, 7, 0, 9, 1); a.r(0x21, 7, 7, 23); a.r(0x23, 8, 23, 9)
        elif part == 'outer':
            a.move(7, 23); a.r(0x23, 8, 23, 9)
        else:
            a.addiu(8, 0, INNER_FRAC); a.r(24, 0, 23, 8); a.r(18, 7, 0, 0); a.r(3, 7, 0, 7, 8)
            a.r(3, 9, 0, 9, 1); a.addiu(10, 0, INNER_MIN); a.r(0x2A, 11, 9, 10); a.branch(4, 11, 0, 'inner_band')
            a.move(9, 10)
            a.label('inner_band'); a.r(0x23, 8, 7, 9)
        a.lw(5, 29, M_X); a.lw(6, 29, M_Y); a.call(STRIP); a.move(19, 2)
    emit_chevron_pair(a, 19, M_X, M_Y, M_TIP, M_RADIUS, RING_OUTLINE, RING_FILL, M_COLOUR, M_EOP)
    emit_packet_end(a, 19, M_EOP)
    a.lw(8, 21, FIELDS['markers']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['markers'])
    a.label('pop'); a.call(A(0x120AC8)); a.jump('return')
    a.label('unmark'); a.r(0, 8, 0, 16, 3); a.li(9, MARKS); a.r(0x21, 8, 8, 9); a.sw(0, 8, 0)
    # The overhead bars draw last, over the indicator (and alone on every other path); never from a quad view.
    a.label('return'); a.lw(8, 29, M_NATIVE); a.branch(4, 8, 0, 'quad')
    a.call(display.BAR_DRAW)
    a.label('quad'); restore(a)
    data = a.finish(); assert len(data) <= SEG-MARKER
    return data


def qmarker_code():
    """The quad renderer's per-view extension entry: MARKER's pass with a0 = 0 (no overhead bars)."""
    a = Assembler(QMARKER); a.move(4, 0); a.jump(MARKER+4)
    data = a.finish(); assert len(data) <= SIZE-QMARKER; return data


def emit_view_size(a, cam, dest, scratch):
    """dest = this view's size in lines: min(height, width*11/8) (a full or top/bottom split view: its height; a
    side-by-side split view: 11/8 of its width). Registers cam, dest, scratch (all distinct)."""
    a.lw(dest, cam, 520); a.lw(scratch, cam, 524); a.r(0x23, dest, scratch, dest); a.addiu(dest, dest, 1)
    a.lw(scratch, cam, 512); a.lw(1, cam, 516); a.r(0x23, scratch, 1, scratch); a.addiu(scratch, scratch, 1)
    a.r(0, 1, 0, scratch, 3); a.r(0x21, 1, 1, scratch); a.r(0, scratch, 0, scratch, 1); a.r(0x21, scratch, scratch, 1)
    a.r(2, scratch, 0, scratch, 3)                                                    # 11/8 of the width
    tag = f'view_size_{a.pc:x}'
    a.r(0x2A, 1, scratch, dest); a.branch(4, 1, 0, tag); a.move(dest, scratch)
    a.label(tag)


def size_code():
    """a0 model, a1 this view's camera (viewport words +512..+524), the view matrix pushed -> v0 the ring radius in
    sixteenths: (H*SIZE_NUM) >> 8, H the larger projected extent (x or y) between the head anchor (bone 48) and the
    model root (0 when either does not project), clamped to [(vh*MIN_NUM) >> 6, (vh*MAX_NUM) >> 6]; v1 = H. Writes
    nothing. Saves ra, s0..s2; t0..t3, a0..a3, LO/HI."""
    a = Assembler(SIZE)
    a.addiu(29, 29, -0x80); a.i(63, 31, 29, 0); a.i(63, 16, 29, 8); a.i(63, 17, 29, 16); a.i(63, 18, 29, 24)
    a.move(16, 4); a.move(17, 5); a.move(18, 0)
    emit_anchor(a, 16, 48, 'size_head')
    a.addiu(4, 29, 0x20); a.call(A(0x1210D8))
    a.branch(4, 2, 0, 'measured'); a.lw(8, 29, 0x2C); a.branch(6, 8, 0, 'measured')
    a.lw(8, 29, 0x28); a.branch(1, 8, 0, 'measured')
    for k in range(3):
        a.lw(8, 16, 2416+4*k); a.sw(8, 29, 0x50+4*k)
    a.li(8, ONE); a.sw(8, 29, 0x5C)
    a.addiu(4, 29, 0x30); a.addiu(5, 29, 0x50); a.call(A(0x1210D8))
    a.branch(4, 2, 0, 'measured'); a.lw(8, 29, 0x3C); a.branch(6, 8, 0, 'measured')
    a.lw(8, 29, 0x38); a.branch(1, 8, 0, 'measured')
    for k, tag in ((0, 'dx'), (4, 'dy')):
        a.lw(8, 29, 0x20+k); a.lw(9, 29, 0x30+k); a.r(0x23, 8, 8, 9)
        a.branch(1, 8, 1, tag); a.r(0x23, 8, 0, 8); a.label(tag)
        a.r(0x2A, 9, 18, 8); a.branch(4, 9, 0, tag+'_max'); a.move(18, 8); a.label(tag+'_max')
    a.label('measured')
    a.addiu(8, 0, SIZE_NUM); a.r(24, 0, 18, 8); a.r(18, 2, 0, 0); a.r(3, 2, 0, 2, 8)
    emit_view_size(a, 17, 9, 8)                                                        # t1 view size (lines)
    a.addiu(8, 0, MIN_NUM); a.r(24, 0, 9, 8); a.r(18, 10, 0, 0); a.r(3, 10, 0, 10, 6)
    a.r(0x2A, 11, 2, 10); a.branch(4, 11, 0, 'above'); a.move(2, 10)
    a.label('above')
    a.addiu(8, 0, MAX_NUM); a.r(24, 0, 9, 8); a.r(18, 10, 0, 0); a.r(3, 10, 0, 10, 6)
    a.r(0x2A, 11, 10, 2); a.branch(4, 11, 0, 'below'); a.move(2, 10)
    a.label('below')
    a.move(3, 18)
    a.i(55, 31, 29, 0); a.i(55, 16, 29, 8); a.i(55, 17, 29, 16); a.i(55, 18, 29, 24); a.addiu(29, 29, 0x80); a.jr()
    data = a.finish(); assert len(data) <= ARROW_PACKET-SIZE and SIZE+len(data) <= TAIL_INPUT; return data


def packet_template():
    """ARROW_PACKET: the bars' A+D header (PRIM: gouraud, alpha-blended triangles), then a REGLIST tag (RGBAQ, XYZ2;
    EOP) and the vertices; each XYZ2 low word holds ((dy << 16) + dx) & 0xFFFFFFFF, so adding the packed tip
    ((tipy << 16) + tipx) places the dart."""
    import guest_healthbars as bars
    header = bytearray(bars.sprite_template()[:96])
    struct.pack_into('<Q', header, 64, 0x4B)                  # PRIM: TRIANGLE | IIP | ABE
    count = len(ARROW_VERTICES)
    header += struct.pack('<2Q', 0x2400000000008000 | count, 0x51)
    body = b''.join(struct.pack('<4I', colour, ONE, ((dy << 16)+dx) & 0xFFFFFFFF, 0) for (dx, dy), colour in ARROW_VERTICES)
    return bytes(header)+body


def lift_table():
    """ARROW_LIFT: LIFT in bytes (read with lbu), zero-padded to 80."""
    return bytes(LIFT).ljust(80, b'\0')


def ring_data():
    """RING_HEADER: the bars' A+D header (alpha on, Z test always); RING_TABLE: cos, sin (Q14 words) of SEGMENTS+1
    points; RING_SCALE: SCALE (words); then the four chevron tables (x, y words)."""
    import math
    import guest_healthbars as bars
    header = bytearray(bars.sprite_template()[:96])
    struct.pack_into('<Q', header, 64, PRIM_TRIANGLES)
    table = b''.join(struct.pack('<2i', round(16384*math.cos(2*math.pi*i/SEGMENTS)),
                                 round(16384*math.sin(2*math.pi*i/SEGMENTS))) for i in range(SEGMENTS+1))
    data = bytes(header)+table.ljust(RING_SCALE-RING_TABLE, b'\0')+struct.pack(f'<{len(SCALE)}I', *SCALE)
    data += b''.join(struct.pack('<6i', *(v for point in shape for v in point)) for shape in CHEVRONS)
    assert len(data) == RING_OUTLINE+4*24-RING_HEADER
    return data


def views_control():
    import quad_viewports as views
    return views.CONTROL


def views_magic():
    import quad_viewports as views
    return views.MAGIC


def tail(entry, original):
    return original+jump(entry+8)


def originals():
    import lockoff_target as off
    return {off.INPUT: off.input_code()[:8], off.APPLY: off.apply_code()[:8]}


def code_parts():
    import lockoff_target as off
    first = originals()
    return [(INPUT2, input_code()), (APPLY2, apply_code()), (ORDER, order_code()),
            (AIM, aim_code()), (MARKER, marker_code()),
            (SEG, segment_code()), (STRIP, strip_code()), (TRI, triangle_code()),
            (TAIL_INPUT, tail(off.INPUT, first[off.INPUT])), (TAIL_APPLY, tail(off.APPLY, first[off.APPLY])),
            (RING_HEADER, ring_data()), (QMARKER, qmarker_code()), (SIZE, size_code()),
            (ARROW_PACKET, packet_template()), (ARROW_LIFT, lift_table())]


def hooks():
    import lockoff_target as off
    return [(off.INPUT, jump(INPUT2)), (off.APPLY, jump(APPLY2))]


def programs():
    """Code, the ring's and arrow's data and the entry hooks (settings live in CONTROL, so these bytes never depend on
    them)."""
    return code_parts()+hooks()


def marker_site():
    """(address, beta.33 word, marker word) of the overhead-bar wrapper's display call."""
    import display_settings as display
    import guest_healthbars as bars
    wrapper = bars.wrapper(); needle = jal(bars.DRAW)
    offsets = [i for i in range(0, len(wrapper), 4) if wrapper[i:i+4] == needle]
    if len(offsets) != 1: raise ValueError('Unknown overhead-bar wrapper')
    return bars.CODE+offsets[0], jal(display.BAR_DRAW), jal(MARKER)


def effective(settings):
    """The values the guest uses. Aiming with the switch button held needs a switch button other than R3 (the
    stick's own click); the right stick alone works with any switch button."""
    options = mod_settings.validate_settings({} if settings is None else settings)
    stick = STICK_MODES[options[STICK_MODE_KEY]] if options['lockon_right_stick'] else 0
    if stick == 1 and options[mod_settings.LOCKON_KEY] == 'r3':
        stick = 0
    marker = int(options['lockon_target_marker'])
    return dict(order=ORDERS[options['lockon_cycle_order']], stick=stick,
                after_ko=AFTER_KO[options['lockon_after_ko']], marker=marker,
                style=STYLES[options[STYLE_KEY]] if marker else 0)


def wanted(settings):
    """False exactly when every setting is at its legacy value (aiming with R3 held counts as off), and so are
    lockon_threat's two settings: its wrappers run in front of INPUT2/APPLY2."""
    import lockon_threat
    values = effective(settings)
    return bool(values['order'] != ORDERS['selection_order'] or values['stick'] or values['after_ko'] or values['marker']
                or lockon_threat.wanted(settings))


def installed(ram):
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    return u(CONTROL) == MAGIC and u(CONTROL+4) == u(core.ACTORS)


def validate_memory(ram):
    """Own programs, hooks and marker call. Never calls lockoff_target.validate_memory (which calls
    dependency_override below); lock-off's remaining bytes are validated by it. lockon_threat, installed after this,
    re-points the two entry hooks and the marker call; its own override recognises them."""
    import lockon_threat
    if not installed(ram): raise ValueError('Target selection belongs to another capture')
    for p, b in programs():
        b = lockon_threat.dependency_override(ram, p, b)
        if ram[p:p+len(b)] != b: raise ValueError(f'Target selection executable changed at {p:X}')
    site, before, after = marker_site()
    marker = struct.unpack_from('<I', ram, CONTROL+FIELDS['marker'])[0]
    # Without the marker the overhead-bar call is not ours; the display validators own it.
    if marker not in (0, 1) or (marker and ram[site:site+4] != lockon_threat.dependency_override(ram, site, after)):
        raise ValueError('Target marker call changed')
    style, quad = (struct.unpack_from('<I', ram, CONTROL+FIELDS[k])[0] for k in ('style', 'quad'))
    if style != (style & 3) or bool(style) != bool(marker) or quad not in (0, 1) or (quad and not marker):
        raise ValueError('Target marker style changed')
    if quad and quad_calls(ram) != 2: raise ValueError('Target marker quad view calls changed')


def quad_calls(ram):
    """The quad renderer's per-view calls of QMARKER."""
    import quad_viewports as views
    data = bytes(ram[views.DRAW:views.SELECT])
    return sum(1 for i in range(0, len(data), 4) if data[i:i+4] == jal(QMARKER))


def quad_patch(ram):
    """The quad renderer's DRAW with QMARKER appended to its per-view extension list, or None when the quad views are
    not installed for this match or their DRAW is not the known emission."""
    import quad_viewports as views
    import viewport_hud as hud
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if (u(views.CONTROL), u(views.CONTROL+4)) != (views.MAGIC, u(core.ACTORS)): return None
    extensions = hud.hud_extensions(ram)
    old, new = views.draw(extensions), views.draw(extensions+((CONTROL, MAGIC, QMARKER),))
    if ram[views.DRAW:views.DRAW+len(old)] != old or len(new) > views.SELECT-views.DRAW: return None
    if any(ram[views.DRAW+len(old):views.DRAW+len(new)]): return None
    return new


def dependency_override(ram, address, expected):
    """Recognise the hooked lock-off entries and the marker call inside existing strict validators."""
    import lockoff_target as off
    first = originals()
    if address in first:
        if not installed(ram) or expected[:8] != first[address]: return expected
        validate_memory(ram)
        return jump(INPUT2 if address == off.INPUT else APPLY2)+expected[8:]
    site, before, after = marker_site()
    if address == site and expected == before and installed(ram):
        validate_memory(ram)
        if struct.unpack_from('<I', ram, CONTROL+FIELDS['marker'])[0]: return after
    return expected


@modes.matching_install
def build_memory(ram, settings=None, source='<prepared>'):
    import display_settings as display
    import lockoff_target as off
    import lockon_queue as queue
    options = mod_settings.validate_settings({} if settings is None else settings)
    if not wanted(options): return dict(blocks=[])
    values = effective(options)
    if len(ram) != 0x8000000: raise ValueError('Target selection requires full captured memory')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE), u(core.MODE+8), u(core.MODE+12)) != (1, manager, count):
        raise ValueError('Target selection requires the prepared captured match')
    if (u(off.CONTROL), u(off.CONTROL+4)) != (off.MAGIC, manager):
        raise ValueError('Target selection requires the lock-off program of this match')
    if any(ram[BASE:END]): raise ValueError('Target selection reservation occupied')
    off.validate_memory(ram)
    mode = u(modes.CONTROL+12) if u(modes.CONTROL) == modes.MAGIC and u(modes.CONTROL+4) == manager else modes.TEAMS
    found = queue.installed_configuration(ram, queue.legacy_previous(ram), free_for_all=mode == modes.FFA,
                                          coop_controls=mode == modes.COOP)
    if found is None or found[0] != queue.CONFIGURABLE:
        raise ValueError('Target selection needs the lock-off target queue')
    for hook, original in originals().items():
        if ram[hook:hook+8] != original: raise ValueError(f'Lock-off entry changed at {hook:X}')
    quad_draw = quad_patch(ram) if values['marker'] else None
    control = bytearray(0x100)
    struct.pack_into('<8I', control, 0, MAGIC, manager, values['order'], values['stick'], STICK_CONFIRM,
                     values['after_ko'], values['marker'], COLOUR)
    struct.pack_into('<I', control, FIELDS['side'], SIDE)
    struct.pack_into('<2I', control, FIELDS['style'], values['style'], int(quad_draw is not None))
    struct.pack_into('<12I', control, FIELDS['keys'], *(INVALID,)*12)
    # The rows, then MARKS (8 bytes per seat) in the same zero block.
    parts = code_parts()+[(CONTROL, bytes(control)), (ROWS, bytes(STRIDE*modes.ENGINE_ACTORS+8*modes.ENGINE_ACTORS))]
    ordered = sorted(parts)
    if any(p+len(b) > n for (p, b), (n, _) in zip(ordered, ordered[1:])) or ordered[-1][0]+len(ordered[-1][1]) > END:
        raise ValueError('Target selection code overlaps')
    parts += hooks()
    limitations = ['Allies are not in the cycle; paired moves take their recipient from the target table.',
                   'Spectators keep slot-order camera switching.',
]
    if not values['stick'] and options['lockon_right_stick']:
        limitations.append('Aiming with the switch button held is off with R3 as the switch button (it is the stick\'s '
                           'own click); \'Stick alone\' works with R3.')
    if values['stick'] == 2:
        limitations.append('Right stick alone: while locked on in combat, flicks pick targets and the stick no longer '
                           'reaches the game (no camera side swing); unlocked, it turns the camera as before.')
    if values['marker']:
        site, before, after = marker_site()
        if u(display.CONTROL) != display.MAGIC or u(display.CONTROL+4) != manager or ram[site:site+4] != before:
            raise ValueError('Target marker requires the display settings program of this match')
        parts.append((site, after))
        if quad_draw is not None:
            import quad_viewports as views
            parts.append((views.DRAW, quad_draw))
        elif u(views_control()) == views_magic():
            limitations.append('The target indicator is not drawn in this match\'s quad views (unknown renderer).')
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL, rows=ROWS,
                status='LOCK-ON ORDER, STICK AIM, KO RETARGET AND TARGET MARKER',
                settings={k: options[k] for k in KEYS}, effective=values,
                blocks=[dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex()) for p, b in parts],
                limitations=limitations)
