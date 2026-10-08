"""KS_B: the foreground slice draw (FG_DRAW) and the LIGHT_B emitters of the Ki Storm loading
cover (PORT-SPEC 5.2), drawn after packet B (foreground register state: TEX1 0x60, CLAMP 5,
ALPHA 0x44, TEST 0x3000D, PRIM 0x156).

Entry/return convention (shared with loading_lights_a, set up by guest_loading_screen.payload):
entered by `j ENTRY` with s7 = arena write cursor, s4 = descriptor (loading_protocol layout),
s5 = the surface's frame counter f (u32, already incremented), s6 = the published buffer, s0 =
CONTROL; returns with `lw t8, KS_RETURN(sp); jr t8`; preserves s0, s1, s3, s4, s5, sp, gp and
clobbers s2, s6, v0, v1, a0..a3, t0..t9, ra; scratch words at sp+0xA0..0xF7. The piece never
calls SUBS: its own leaf helpers (ad, tag, vtx, spr, tspr, point, inbox) write at s7.

Emission table (fixed: every frame writes exactly SIZE bytes; hidden or unused elements emit
degenerate geometry - sprites with both corners at OFFSCREEN, every line/strip/fan vertex at
OFFSCREEN (-64, -64) - so the arena reserve never changes; ORDER lists every block):
  FG_DRAW  14 x (A+D TEX0_1 32 B + REGLIST RGBAQ,UV,XYZ2,UV,XYZ2 1 sprite: tag 16 + 3 qw incl.
           the written zero pad) = 1344 B. p = ease[min(20, f - start)] (0 while f < start,
           unsigned), x = sx + ((dx*(255-p)) >> 8), y likewise, RGBAQ (0x80, 0x80, 0x80,
           (p+1)>>1) Q 1.0, UV (u, v)..(u+w, v+h) in 1/16 texel; a slot with w == 0 writes
           loading_protocol.fg_tex0(k) from FG_TEX0 and the (0,0) degenerate sprite, so the
           block equals loading_protocol.foreground_draw(slices, p, eop=False) byte for byte.
  TICKS    A+D ALPHA_1 ADDITIVE 32 B; 12 rings x (A+D PRIM LINE_LIST 32 + tag 16 + 60 lines x
           2 vertices RGBAQ,XYZ2 = 960) = 12096 B. Ring i (TICKS + 48 i): 24 tick lines then the
           6 cursor segments. Angles are 1/65536 of a turn: a16 = (k*STEP[n] + rot) & 0xFFFF,
           STEP[n] = round(65536/n), rot = (f << 6)*direction (RATE 64 = 0.25/256 turn per
           frame = 0.37 rad/s), a = a16 >> 8 indexes SIN8 (cos = SIN8[(a+64)&255]); base =
           (cx + (rx*cos >> 7), cy + (ry*sin >> 7)), tip with rx+L, ry+L, L = 3 for k % 4 ==
           0 else 2 (the JS tickRing); colour = ring colour, alpha 0x50. A tick is OFFSCREEN
           when the TICKS flag is clear, n == 0, k >= n or its base lies inside the exclusion
           box (bx0 <= x <= bx1 and by0 <= y <= by1). Cursor: 6 segments of CURSOR_SEG (40
           degrees in all) at radius rx+2, ry+2 (the JS r+1..r+2: rx+6 would leave the card
           panel), rotating the other way at CURSOR_RATE = 109 per frame (1.7 RATE), cursor
           colour alpha 0x60; a segment is OFFSCREEN when hidden or either end is in the box.
  GAUGE    (all OFFSCREEN/degenerate when the GAUGE flag is clear)
           A+D ALPHA STANDARD 32; fill: PRIM STRIP 32 + tag 16 + 6 vertices 96 = 144 B, columns
           x0 -> xm -> xf with colours color0 -> color1 -> color2 (alpha 0x80), xf = x0 +
           ((w*fill*257 + 32768) >> 16) (w = x1-x0: fill 255 lands exactly on x1), xm = x0 +
           ((xf-x0)*179 >> 8); cells: PRIM SPRITE 32 + tag 16 + 20 sprites RGBAQ,XYZ2,XYZ2 480 =
           528 B: 19 dividers 1 px wide at x0 + (k*w*3277 >> 16) (= k*w/20), colour (0,0,20)
           alpha 0x3A, degenerate unless x < xf-2; the 2 px tip (xf-2..xf, tip colour, alpha
           0x80) when xf-x0 >= 2; A+D ALPHA ADDITIVE 32; 3 pulses: PRIM STRIP + tag + 6 vertices
           = 144 B each, xb = x0 + ((((f*speed + offset) & 511)*(xf-x0)) >> 9) with speeds
           2, 3, 4 and offsets 0, 131, 262, columns xb-6 (black) -> xb (white) -> xb+6 (black),
           alpha 0x60, OFFSCREEN unless xb-6 >= x0 and xb+6 <= xf; A+D TEX0_1 ATLAS_TEX0 32;
           soft dots: PRIM TSPRITE 32 + tag 16 + 12 textured sprites 480 = 528 B from the atlas
           soft dot (DOT rect): the tip glow 16 px centred on (xf, (y0+y1)>>1) with alpha 0x40 +
           (0x38*SIN8[((f*19)>>2)&255] >> 7) (54-frame pulse), 8 escaping sparks at x = x0 +
           (SPARK_U[k]*(xf-x0) >> 8), y = y0-1-RISE[i], alpha LIFE[i], i = (f + 8k) & 63 (a
           64-frame ease-in rise of 32 px, alpha (1-life)^0.6), size SPARK_SIZE[k]; glow and
           sparks degenerate while xf-x0 < 4; 3 motes orbiting the ki orb at (orb_rx+4, orb_ry+2),
           angle (f*13 >> 3) + 85k, size 5, alpha min(0x70, (progress-50)*9 >> 1), degenerate
           unless progress > 50; orb light: PRIM FAN 32 + tag 16 + 18 vertices 288 = 336 B at
           radius orb_rx*3/2, orb_ry*3/2, centre = the orb colour half way to white with alpha
           (orb_alpha*breathe) >> 7, breathe = 104 + (24*SIN8[a_b] >> 7), a_b = ((f*862) >> 8)
           & 255 (76-frame period), rim black; rays: PRIM LINE_LIST 32 + tag 16 + 12 vertices
           192 = 240 B, 6 lines from radius orb_r+6 to orb_r+16 at angle ((f*13) >> 5) + 43k,
           white alpha 0x60 + (0x20*SIN8[a_b] >> 7), OFFSCREEN unless progress == 100; A+D
           ALPHA STANDARD 32; percentage: PRIM TSPRITE 32 + tag 16 + 4 textured sprites 160 =
           208 B from the DIGITS entries (u, v, w, h, x, y; w == 0 degenerate), white alpha 0x80.
  SHEENS   A+D ALPHA ADDITIVE 32; 2 x (PRIM STRIP 32 + tag 16 + 6 vertices 96) = 288 B: a 12 px
           band leaning SHEEN_LEAN px, pos = (((f*2) + 256k) & 511) - 16, columns clamped to the
           banner rect (x0..x1) so it enters and leaves gradually; black/white/black alpha 0x40;
           OFFSCREEN when the SHEENS flag is clear.
  DOTS     A+D ALPHA STANDARD 32; PRIM SPRITE 32 + tag 16 + 3 sprites 72 + zero pad 8 = 128 B:
           size x size at (x + k*pitch, y), alpha 0x80 when ((f >> 4) mod 3) == k else 0x20
           (mod 3 by the 0xAAAB multiply), OFFSCREEN when the DOTS flag is clear.
  RESTORE  one A+D block, 2 writes, EOP: TEST_1 SETUP_TEST (0x30000), ALPHA_1 STANDARD = 48 B.
Every PRIM word carries ABE (STRIP 0x4C, FAN 0x4D, LINE_LIST 0x49, SPRITE 0x46, TSPRITE 0x156).
Colours are packed r | g<<8 | b<<16 | a<<24 and rebuilt whenever an alpha is scaled. Frame
arithmetic is 32-bit (mult low word, shifts and masks), never a division; the host model()
mirrors it word for word and decode() parses a block back for the tests.
"""
import math
import struct
from regional import Y_ORIGIN, xyz2_y, emit_window_y

CODE, END = 0x07476000, 0x0747A000     # 16 KiB: the emitter table needs ~9 KiB, KS_A only 8
ENTRY = CODE
OFFSCREEN = -64
MAX_SLICES, MAX_TICKS, TICKS_PER_RING, CURSOR_SEGMENTS = 14, 12, 24, 6
LINES_PER_RING = TICKS_PER_RING+CURSOR_SEGMENTS
RATE, CURSOR_RATE, CURSOR_SEG, CURSOR_RADIUS = 64, 109, 1214, 2      # 1/65536 turn per frame; 6 x 1214 = 40 degrees
TICK_ALPHA, CURSOR_ALPHA = 0x50, 0x60
DIVIDER_COLOR = (0, 0, 20) ; DIVIDER_ALPHA = 0x3A
PULSE_SPEEDS, PULSE_OFFSETS, PULSE_HALF, PULSE_ALPHA = (2, 3, 4), (0, 131, 262), 6, 0x60
GLOW_SIZE, GLOW_ALPHA, GLOW_SWING = 16, 0x40, 0x38
SPARK_U = (28, 123, 218, 56, 151, 246, 84, 179)                     # ((k*37+11) % 100) * 256/100
SPARK_SIZE = (4, 5, 4, 5, 4, 5, 4, 5)
SPARK_PHASE, SPARK_LOOP, SPARK_RISE = 8, 64, 32
MOTE_DX, MOTE_DY, MOTE_SIZE, MOTE_ALPHA = 4, 2, 5, 0x70
ORB_BREATHE, ORB_BREATHE_BASE, ORB_BREATHE_SWING = 862, 104, 24
RAY_IN, RAY_OUT, RAY_ALPHA, RAY_SWING, RAY_RATE = 6, 16, 0x60, 0x20, 13
SHEEN_SPEED, SHEEN_STAGGER, SHEEN_WIDTH, SHEEN_LEAN, SHEEN_ALPHA, SHEEN_LEAD, SHEEN_PHASE = 2, 256, 12, 6, 0x40, 16, 176
TICK_FADE_START, TICK_FADE_FRAMES = 18, 32          # loading_art_v4.ENT cards + 5, ramp 4/frame to 128 (the JS arrive 0.36 s)
GAUGE_START = 25                                    # loading_art_v4.ENT footer: the gauge follows the footer slice's ease
DOT_LIT, DOT_DIM = 0x80, 0x20
Q_ONE = 0x3F800000
A_TAG_HIGH = 0x10000000                                              # PACKED, 1 register
REGLIST_HIGH = {2: 0x24000000, 3: 0x34000000, 5: 0x54000000}         # REGLIST, NREG
REGS = {2: 0x51, 3: 0x551, 5: 0x53531}                               # RGBAQ,XYZ2 / +XYZ2 / RGBAQ,UV,XYZ2,UV,XYZ2
PRIM_REG, TEX0_REG, ALPHA_REG, TEST_REG = 0x00, 0x06, 0x42, 0x47

SIN8 = bytes((round(127*math.sin(2*math.pi*i/256)) & 255) for i in range(256))
EASE = bytes(round(255*(1-(1-i/20)**3)) for i in range(21))          # harness.js easeOut
STEP = [0]+[min(65535, round(65536/n)) for n in range(1, 32)]           # halfwords: 1/65536 turn per tick
RISE = bytes((SPARK_RISE*i*i) >> 12 for i in range(SPARK_LOOP))
LIFE = bytes(round(128*(1-i/SPARK_LOOP)**0.6) for i in range(SPARK_LOOP))


def sin8(a): v = SIN8[a & 255]; return v-256 if v >= 128 else v
def cos8(a): return sin8(a+64)


ORDER = (
    ('fg_draw', MAX_SLICES*(32+16+48)),
    ('ticks_alpha', 32), ('ticks', MAX_TICKS*(32+16+LINES_PER_RING*32)),
    ('gauge_alpha', 32), ('gauge_fill', 32+16+6*16), ('gauge_cells', 32+16+20*24), ('gauge_alpha_add', 32),
    ('gauge_pulses', 3*(32+16+6*16)), ('gauge_tex0', 32), ('gauge_dots', 32+16+12*40), ('gauge_orb', 32+16+18*16),
    ('gauge_rays', 32+16+12*16), ('percent_alpha', 32), ('percent', 32+16+4*40),
    ('sheens_alpha', 32), ('sheens', 2*(32+16+6*16)),
    ('dots_alpha', 32), ('dots', 32+16+3*24+8),
    ('restore', 16+2*16),
)
SIZE = sum(n for _, n in ORDER)
FG_DRAW_BYTES = ORDER[0][1]
assert SIZE % 16 == 0


# ---- tables placed at CODE+8 (after the entry jump) ---------------------------------------------
def _fg_tex0_words():
    import loading_protocol as protocol
    return [protocol.fg_tex0(k) for k in range(MAX_SLICES)]


def _tables():
    """(name -> offset from TABLES, bytes): SIN8, EASE, STEP halfwords, FG_TEX0 qwords, spark constants."""
    out, layout = bytearray(), {}
    def put(name, data, align=4):
        while len(out) % align: out.append(0)
        layout[name] = len(out); out.extend(data)
    put('sin8', SIN8); put('ease', EASE); put('step', b''.join(struct.pack('<H', v) for v in STEP))
    put('fgtex', b''.join(struct.pack('<Q', w) for w in _fg_tex0_words()), 8)
    put('spark_u', bytes(SPARK_U)); put('spark_size', bytes(SPARK_SIZE)); put('rise', RISE); put('life', LIFE)
    while len(out) % 16: out.append(0)
    return layout, bytes(out)


TABLES = CODE+8


# ---- host model ------------------------------------------------------------------------------------
def _u(data, off): return struct.unpack_from('<I', data, off)[0]
def _s(data, off): return struct.unpack_from('<i', data, off)[0]
def _color(word, alpha): return (word & 0xFFFFFF) | ((alpha & 255) << 24)
def _m32(v): return v & 0xFFFFFFFF
def _sra(v, n): return (v-(1 << 32) if v & 0x80000000 else v) >> n     # sra of a 32-bit product


def _mul(a, b):
    """The low 32 bits of a signed product read back as a signed word (mult + mflo)."""
    v = _m32(a*b); return v-(1 << 32) if v & 0x80000000 else v


def _off(n): return [(OFFSCREEN, OFFSCREEN, c) for c in n]
def _uv(u, v): return (u*16) | ((v*16) << 16)


def model(descriptor, f, c=0):
    """Every entry the guest writes for frame f: ('ad', register, value) or ('prim', PRIM word,
    kind, vertices) with vertices (x, y, colour) for RGBAQ,XYZ2 blocks, (x, y, colour) pairs
    for sprites and (x, y, colour, uv word) pairs for textured sprites. c (the clash cycle)
    is unused by LIGHT_B. descriptor = loading_protocol.encode_lights() bytes (or None: no
    descriptor is never the case, KS_B only runs with one)."""
    import loading_protocol as P
    d = descriptor; f = _m32(f); out = []
    flags = _u(d, P.FLAGS)
    fgtex = _fg_tex0_words()
    # FG_DRAW
    for k in range(MAX_SLICES):
        base = P.SLICES+k*P.SLICE_STRIDE
        x, y, w, h, u, v = (_s(d, base+4*i) for i in range(6)); start = _u(d, base+28); dx, dy = _s(d, base+32), _s(d, base+36)
        tex0 = _u(d, base+40) | (_u(d, base+44) << 32)
        if w == 0:
            out.append(('ad', TEX0_REG, fgtex[k])); out.append(('prim', 0x156, 'tsprite', [(0, 0, 0x80808080, 0), (0, 0, 0x80808080, 0)])); continue
        out.append(('ad', TEX0_REG, tex0))
        dd = 0 if f < start else min(20, f-start); p = EASE[dd]
        colour = 0x808080 | (((p+1) >> 1) << 24); q = 255-p
        sx, sy = x+_sra(_m32(dx*q), 8), y+_sra(_m32(dy*q), 8)
        out.append(('prim', 0x156, 'tsprite', [(sx, sy, colour, _uv(u, v)), (sx+w, sy+h, colour, _uv(u+w, v+h))]))
    # TICKS
    out.append(('ad', ALPHA_REG, P.ADDITIVE))
    dd = 0 if f < TICK_FADE_START else f-TICK_FADE_START; scale = dd*4 if dd < TICK_FADE_FRAMES else 128
    for i in range(MAX_TICKS):
        base = P.TICKS+i*P.TICK_STRIDE
        cx, cy, rx, ry, n, direction = (_s(d, base+4*j) for j in range(6)); colour, cursor = _u(d, base+24), _u(d, base+44)
        bx0, by0, bx1, by1 = (_s(d, base+28+4*j) for j in range(4))
        hidden = not (flags & P.FLAG_TICKS) or n == 0
        rot = _m32(f << 6)
        if direction < 0: rot = _m32(-rot)
        cur = _m32(f*CURSOR_RATE)
        if direction > 0: cur = _m32(-cur)
        inbox = lambda x, y: bx0 <= x <= bx1 and by0 <= y <= by1
        step = STEP[n] if 0 <= n < 32 else 0
        verts = []; tick_colour = _color(colour, (TICK_ALPHA*scale) >> 7); cursor_colour = _color(cursor, (CURSOR_ALPHA*scale) >> 7)
        for k in range(TICKS_PER_RING):
            a = ((_m32(k*step)+rot) & 0xFFFF) >> 8; co, si = cos8(a), sin8(a)
            bx, by = cx+_sra(_m32(rx*co), 7), cy+_sra(_m32(ry*si), 7)
            L = 3 if k % 4 == 0 else 2
            tx, ty = cx+_sra(_m32((rx+L)*co), 7), cy+_sra(_m32((ry+L)*si), 7)
            if hidden or k >= n or inbox(bx, by): bx = by = tx = ty = OFFSCREEN
            verts += [(bx, by, tick_colour), (tx, ty, tick_colour)]
        for j in range(CURSOR_SEGMENTS):
            pts = []
            for e in (j, j+1):
                a = ((_m32(e*CURSOR_SEG)+cur) & 0xFFFF) >> 8
                pts.append((cx+_sra(_m32((rx+CURSOR_RADIUS)*cos8(a)), 7), cy+_sra(_m32((ry+CURSOR_RADIUS)*sin8(a)), 7)))
            if hidden or any(inbox(*pt) for pt in pts): pts = [(OFFSCREEN, OFFSCREEN)]*2
            verts += [(x, y, cursor_colour) for x, y in pts]
        out.append(('ad', PRIM_REG, P.LINE_LIST)); out.append(('prim', P.LINE_LIST, 'lines', verts))
    # GAUGE
    G = P.GAUGE; names = P.GAUGE_WORDS
    g = {name: _s(d, G+4*i) for i, name in enumerate(names)}
    hidden = not (flags & P.FLAG_GAUGE)
    dd = 0 if f < GAUGE_START else min(20, f-GAUGE_START); ga = (EASE[dd]+1) >> 1
    x0, x1, y0, y1, fill = g['x0'], g['x1'], g['y0'], g['y1'], g['fill'] & 0xFFFFFFFF
    w = x1-x0; xf = x0+(_m32(_m32(_m32(w*fill)*257)+32768) >> 16); W = xf-x0; xm = x0+(_m32(W*179) >> 8); ym = (y0+y1) >> 1
    c0, c1, c2 = (_color(g[n], ga) for n in ('color0', 'color1', 'color2'))
    out.append(('ad', ALPHA_REG, P.STANDARD)); out.append(('ad', PRIM_REG, P.STRIP))
    fill_verts = [(x0, y0, c0), (x0, y1, c0), (xm, y0, c1), (xm, y1, c1), (xf, y0, c2), (xf, y1, c2)]
    out.append(('prim', P.STRIP, 'strip', _off([v[2] for v in fill_verts]) if hidden else fill_verts))
    out.append(('ad', PRIM_REG, P.SPRITE)); cells = []
    div = _color(P.packed_color(DIVIDER_COLOR), (DIVIDER_ALPHA*ga) >> 7)
    for k in range(1, 20):
        x = x0+(_m32(_m32(k*w)*3277) >> 16)
        if hidden or not x < xf-2: cells += _off([div, div])
        else: cells += [(x, y0, div), (x+1, y1, div)]
    tip = _color(g['tip'], ga)
    cells += _off([tip, tip]) if hidden or W < 2 else [(xf-2, y0, tip), (xf, y1, tip)]
    out.append(('prim', P.SPRITE, 'sprite', cells))
    out.append(('ad', ALPHA_REG, P.ADDITIVE))
    dark, white = _color(0, (PULSE_ALPHA*ga) >> 7), _color(0xFFFFFF, (PULSE_ALPHA*ga) >> 7)
    for k in range(3):
        xb = x0+(_m32(((_m32(f*PULSE_SPEEDS[k])+PULSE_OFFSETS[k]) & 511)*W) >> 9); xa, xc = xb-PULSE_HALF, xb+PULSE_HALF
        verts = [(xa, y0, dark), (xa, y1, dark), (xb, y0, white), (xb, y1, white), (xc, y0, dark), (xc, y1, dark)]
        if hidden or xa < x0 or xc > xf: verts = _off([v[2] for v in verts])
        out.append(('ad', PRIM_REG, P.STRIP)); out.append(('prim', P.STRIP, 'strip', verts))
    out.append(('ad', TEX0_REG, P.ATLAS_TEX0)); out.append(('ad', PRIM_REG, P.TSPRITE))
    dot = _dot_rect(); uv0, uv1 = _uv(dot[0], dot[1]), _uv(dot[0]+dot[2], dot[1]+dot[3]); sprites = []
    def tsp(x0_, y0_, x1_, y1_, colour, visible):
        if visible: sprites.extend([(x0_, y0_, colour, uv0), (x1_, y1_, colour, uv1)])
        else: sprites.extend([(OFFSCREEN, OFFSCREEN, colour, uv0), (OFFSCREEN, OFFSCREEN, colour, uv1)])
    pulse = (_m32(f*19) >> 2) & 255; glow = _color(0xFFFFFF, ((GLOW_ALPHA+_sra(_m32(GLOW_SWING*sin8(pulse)), 7))*ga) >> 7); h = GLOW_SIZE >> 1
    tsp(xf-h, ym-h, xf+h, ym+h, glow, not hidden and W >= 4)
    for k in range(8):
        i = (f+SPARK_PHASE*k) & (SPARK_LOOP-1); x = x0+(_m32(SPARK_U[k]*W) >> 8); y = y0-1-RISE[i]; s = SPARK_SIZE[k]; hs = s >> 1
        tsp(x-hs, y-hs, x-hs+s, y-hs+s, _color(0xFFFFFF, (LIFE[i]*ga) >> 7), not hidden and W >= 4)
    progress = g['progress']; ocx, ocy, orx, ory = g['orb_cx'], g['orb_cy'], g['orb_rx'], g['orb_ry']
    mote_alpha = ((min(MOTE_ALPHA, (_m32((progress-50)*9)) >> 1)*ga) >> 7) if progress > 50 and not hidden else 0
    for k in range(3):
        an = ((_m32(f*13) >> 3)+85*k) & 255
        mx, my = ocx+_sra(_m32((orx+MOTE_DX)*cos8(an)), 7), ocy+_sra(_m32((ory+MOTE_DY)*sin8(an)), 7); hs = MOTE_SIZE >> 1
        tsp(mx-hs, my-hs, mx-hs+MOTE_SIZE, my-hs+MOTE_SIZE, _color(0xFFFFFF, mote_alpha), not hidden and progress > 50)
    out.append(('prim', P.TSPRITE, 'tsprite', sprites))
    ab = (_m32(f*ORB_BREATHE) >> 8) & 255; breathe = ORB_BREATHE_BASE+_sra(_m32(ORB_BREATHE_SWING*sin8(ab)), 7)
    oalpha = ((_m32((g['orb_alpha'] & 0xFFFFFFFF)*breathe) >> 7)*ga) >> 7
    oc = g['orb_color'] & 0xFFFFFF; bright = sum((((oc >> s) & 255)+((255-((oc >> s) & 255)) >> 1)) << s for s in (0, 8, 16))
    centre = _color(bright, oalpha); rim = 0
    frx, fry = orx+(orx >> 1), ory+(ory >> 1)
    fan = [(ocx, ocy, centre)]+[(ocx+_sra(_m32(frx*cos8(j*16)), 7), ocy+_sra(_m32(fry*sin8(j*16)), 7), rim) for j in range(17)]
    out.append(('ad', PRIM_REG, P.FAN)); out.append(('prim', P.FAN, 'fan', _off([v[2] for v in fan]) if hidden else fan))
    ralpha = _color(0xFFFFFF, ((RAY_ALPHA+_sra(_m32(RAY_SWING*sin8(ab)), 7))*ga) >> 7); rays = []
    for k in range(6):
        an = ((_m32(f*RAY_RATE) >> 5)+43*k) & 255
        for r in (RAY_IN, RAY_OUT): rays.append((ocx+_sra(_m32((orx+r)*cos8(an)), 7), ocy+_sra(_m32((ory+r)*sin8(an)), 7), ralpha))
    if hidden or progress != 100: rays = _off([v[2] for v in rays])
    out.append(('ad', PRIM_REG, P.LINE_LIST)); out.append(('prim', P.LINE_LIST, 'lines', rays))
    out.append(('ad', ALPHA_REG, P.STANDARD)); out.append(('ad', PRIM_REG, P.TSPRITE)); digits = []; white80 = _color(0xFFFFFF, ga)
    for k in range(4):
        base = P.GAUGE_DIGITS+k*P.DIGIT_STRIDE; u, v, dw, dh, x, y = (_s(d, base+4*j) for j in range(6))
        if hidden or dw == 0: digits += [(OFFSCREEN, OFFSCREEN, white80, _uv(u, v)), (OFFSCREEN, OFFSCREEN, white80, _uv(u+dw, v+dh))]
        else: digits += [(x, y, white80, _uv(u, v)), (x+dw, y+dh, white80, _uv(u+dw, v+dh))]
    out.append(('prim', P.TSPRITE, 'tsprite', digits))
    # SHEENS
    out.append(('ad', ALPHA_REG, P.ADDITIVE)); hidden = not (flags & P.FLAG_SHEENS)
    dark, white = _color(0, SHEEN_ALPHA), _color(0xFFFFFF, SHEEN_ALPHA)
    for k in range(2):
        base = P.SHEENS+16*k; sx0, sy0, sx1, sy1 = (_s(d, base+4*j) for j in range(4))
        pos = ((_m32(f*SHEEN_SPEED)+SHEEN_PHASE+SHEEN_STAGGER*k) & 511)-SHEEN_LEAD; xa = sx0+pos; xb, xc = xa+SHEEN_WIDTH//2, xa+SHEEN_WIDTH
        cl = lambda x: max(sx0, min(sx1, x))
        verts = [(cl(xa), sy1, dark), (cl(xa+SHEEN_LEAN), sy0, dark), (cl(xb), sy1, white), (cl(xb+SHEEN_LEAN), sy0, white), (cl(xc), sy1, dark), (cl(xc+SHEEN_LEAN), sy0, dark)]
        if hidden: verts = _off([v[2] for v in verts])
        out.append(('ad', PRIM_REG, P.STRIP)); out.append(('prim', P.STRIP, 'strip', verts))
    # DOTS
    out.append(('ad', ALPHA_REG, P.STANDARD)); out.append(('ad', PRIM_REG, P.SPRITE)); hidden = not (flags & P.FLAG_DOTS)
    dx, dy, pitch, size, colour = (_s(d, P.DOTS+4*j) for j in range(5))
    m = (f >> 4) & 0xFFFF; m3 = m-3*((m*0xAAAB) >> 17); dots = []
    for k in range(3):
        cc = _color(colour, ((DOT_LIT if m3 == k else DOT_DIM)*ga) >> 7); x = dx+k*pitch
        dots += _off([cc, cc]) if hidden else [(x, dy, cc), (x+size, dy+size, cc)]
    out.append(('prim', P.SPRITE, 'sprite', dots))
    out.append(('ad', TEST_REG, P.SETUP_TEST)); out.append(('ad', ALPHA_REG, P.STANDARD))
    return out


def _dot_rect():
    """(u, v, w, h) of the atlas soft dot, pinned from loading_art_v4 so the guest constant is checked."""
    return DOT_RECT


DOT_RECT = (211, 0, 13, 15)


def decode(block, prim=0x156):
    """Parse a KS_B block back into model() entries; asserts the fixed layout (SIZE, 16-byte tags,
    Q = 1.0, Z = 0, zero pads, EOP only on the last tag). `prim` = the PRIM packet B left."""
    if len(block) != SIZE: raise ValueError(f'KS_B block is {len(block)} bytes, SIZE is {SIZE}')
    out = []; pos = 0; eops = []
    while pos < len(block):
        low, high = struct.unpack_from('<2Q', block, pos); nloop = low & 0x7FFF; eops.append(bool(low >> 15 & 1))
        flg = low >> 58 & 3; nreg = low >> 60 or 16; pos += 16
        if flg == 0:
            if nreg != 1 or high != 0xE: raise ValueError('only A+D packed blocks are used')
            for _ in range(nloop):
                value, reg = struct.unpack_from('<2Q', block, pos); pos += 16
                if reg == PRIM_REG: prim = value
                out.append(('ad', reg, value))
            continue
        if flg != 1 or high != REGS.get(nreg): raise ValueError(f'unexpected REGLIST tag {low:#x} {high:#x}')
        qwords = (nreg*nloop+1)//2; words = struct.unpack_from(f'<{2*qwords}Q', block, pos); pos += 16*qwords
        if nreg*nloop & 1 and words[-1] != 0: raise ValueError('REGLIST pad qword must be zero')
        words = words[:nreg*nloop]; verts = []
        def vertex(rgbaq, xyz, uv=None):
            if rgbaq >> 32 != Q_ONE: raise ValueError('Q must be 1.0')
            if xyz >> 32: raise ValueError('Z must be 0')
            xw, yw = xyz & 0xFFFF, xyz >> 16 & 0xFFFF
            if xw % 16 or yw % 16: raise ValueError('fractional vertex')
            v = (xw//16-1792, yw//16-Y_ORIGIN, rgbaq & 0xFFFFFFFF)
            return v if uv is None else v+(uv,)
        if nreg == 2:
            for i in range(nloop): verts.append(vertex(words[2*i], words[2*i+1]))
            kind = {4: 'strip', 5: 'fan', 1: 'lines', 2: 'line_strip'}[prim & 7]
        elif nreg == 3:
            for i in range(nloop): verts += [vertex(words[3*i], words[3*i+1]), vertex(words[3*i], words[3*i+2])]
            kind = 'sprite'
        else:
            for i in range(nloop): verts += [vertex(words[5*i], words[5*i+2], words[5*i+1]), vertex(words[5*i], words[5*i+4], words[5*i+3])]
            kind = 'tsprite'
        out.append(('prim', prim, kind, verts))
    if eops != [False]*(len(eops)-1)+[True]: raise ValueError('EOP must be set on the last tag only')
    return out


def primitives(entries):
    """Only the drawing entries of a model()/decode() list, as (kind, PRIM word, vertices)."""
    return [(e[2], e[1], e[3]) for e in entries if e[0] == 'prim']


# ---- guest code --------------------------------------------------------------------------------
def code():
    from prototype import Assembler
    import loading_protocol as protocol
    from guest_loading_screen import PRIM_BYTES
    assert PRIM_BYTES == 32 and OFFSCREEN == __import__('guest_loading_screen').OFFSCREEN
    P = protocol
    zero, v0, v1, a0, a1, a2, a3 = 0, 2, 3, 4, 5, 6, 7
    t0, t1, t2, t3, t4, t5, t6, t7, t8, t9 = 8, 9, 10, 11, 12, 13, 14, 15, 24, 25
    s2, s4, s5, s6, s7, sp, ra = 18, 20, 21, 22, 23, 29, 31
    SCR = P.KS_SCRATCH[0]
    K, ROT, CUR, HID, TX, TY, XF, WW, GA, AX, AY, T6, T7, XB, SCALE = (SCR+4*i for i in range(15))
    assert SCALE+4 <= P.KS_SCRATCH[1]
    layout, tables = _tables()
    T = {name: TABLES+off for name, off in layout.items()}
    a = Assembler(CODE)

    def lb(rt, rs, off): a.i(32, rt, rs, off)
    def lbu(rt, rs, off): a.i(36, rt, rs, off)
    def lhu(rt, rs, off): a.i(37, rt, rs, off)
    def andi(rt, rs, imm): a.i(12, rt, rs, imm)
    def xori(rt, rs, imm): a.i(14, rt, rs, imm)
    def sltiu(rt, rs, imm): a.i(11, rt, rs, imm)
    def sll(rd, rt, sh): a.r(0, rd, 0, rt, sh)
    def srl(rd, rt, sh): a.r(2, rd, 0, rt, sh)
    def sra(rd, rt, sh): a.r(3, rd, 0, rt, sh)
    def addu(rd, rs, rt): a.r(33, rd, rs, rt)
    def subu(rd, rs, rt): a.r(35, rd, rs, rt)
    def and_(rd, rs, rt): a.r(36, rd, rs, rt)
    def or_(rd, rs, rt): a.r(37, rd, rs, rt)
    def slt(rd, rs, rt): a.r(42, rd, rs, rt)
    def sltu(rd, rs, rt): a.r(43, rd, rs, rt)
    def movn(rd, rs, rt): a.r(11, rd, rs, rt)
    def mullo(rd, rs, rt): a.r(24, 0, rs, rt); a.r(18, rd, 0, 0)
    def beq(rs, rt, l): a.branch(4, rs, rt, l)
    def bne(rs, rt, l): a.branch(5, rs, rt, l)
    def blez(rs, l): a.branch(6, rs, 0, l)
    def bgtz(rs, l): a.branch(7, rs, 0, l)
    def bgez(rs, l): a.branch(1, rs, 1, l)
    def call(l): a.jump(l, True)
    def li(rt, v):
        if -32768 <= v < 32768: a.addiu(rt, 0, v)
        else: a.li(rt, v)
    def AD(reg, lo, hi=0): li(a0, reg); li(a1, lo); li(a2, hi); call('ad')
    def PRIM(word): AD(PRIM_REG, word)
    def TAG(nloop, nreg): li(a0, nloop); li(a1, REGLIST_HIGH[nreg]); li(a2, REGS[nreg]); call('tag')
    def offscreen4(): li(a0, OFFSCREEN); a.move(a1, a0); a.move(a2, a0); a.move(a3, a0)
    def color_alpha(rd, word_reg, imm=None, reg=None):
        """rd = (word & 0xFFFFFF) | alpha << 24 with alpha an immediate (imm) or a register (reg); scratch t8 only."""
        a.li(t8, 0xFFFFFF); and_(rd, word_reg, t8)
        if reg is None: a.i(15, t8, 0, imm << 8)
        else: sll(t8, reg, 24)
        or_(rd, rd, t8)
    def ramp(start, slot):
        """slot = (EASE[min(20, f-start)]+1) >> 1 (0 while f < start): the same ease as the entrance slices."""
        li(t0, start); subu(t1, s5, t0); sltu(t2, s5, t0); movn(t1, zero, t2); sltiu(t2, t1, 21); xori(t2, t2, 1); li(t3, 20); movn(t1, t3, t2)
        a.li(t2, T['ease']); addu(t2, t2, t1); lbu(t2, t2, 0); a.addiu(t2, t2, 1); srl(t2, t2, 1); a.sw(t2, sp, slot)
    def scaled(rd, imm, slot):
        """rd = (imm * slot) >> 7; scratch t8."""
        a.lw(rd, sp, slot); li(t8, imm); mullo(rd, rd, t8); srl(rd, rd, 7)
    def pad_zero(n):
        for i in range(0, n, 4): a.sw(zero, s7, i)
        a.addiu(s7, s7, n)

    a.jump('start')
    assert a.pc == TABLES
    for i in range(0, len(tables), 4): a.emit(struct.unpack_from('<I', tables, i)[0])

    # ---- leaf helpers (write at s7, advance it, jr ra) --------------------------------------
    a.label('ad')                                    # a0 = register, a1 = lo, a2 = hi -> 32 B
    li(t0, 1); a.sw(t0, s7, 0); li(t0, A_TAG_HIGH); a.sw(t0, s7, 4); li(t0, 0xE); a.sw(t0, s7, 8); a.sw(zero, s7, 12)
    a.sw(a1, s7, 16); a.sw(a2, s7, 20); a.sw(a0, s7, 24); a.sw(zero, s7, 28); a.addiu(s7, s7, 32); a.jr()
    a.label('tag')                                   # a0 = nloop (+EOP), a1 = high word, a2 = regs -> 16 B
    a.sw(a0, s7, 0); a.sw(a1, s7, 4); a.sw(a2, s7, 8); a.sw(zero, s7, 12); a.addiu(s7, s7, 16); a.jr()
    def xyz(rd, x, y, tmp):                          # rd = ((x+1792)*16) | ((y+1824)*16 << 16) (y stretched on 512 lines)
        a.addiu(rd, x, 1792); sll(rd, rd, 4); emit_window_y(a, tmp, y, 20); or_(rd, rd, tmp)
    a.label('vtx')                                   # a0 = x, a1 = y, a2 = colour -> RGBAQ, XYZ2 (16 B)
    xyz(t0, a0, a1, t1); a.sw(a2, s7, 0); li(t1, Q_ONE); a.sw(t1, s7, 4); a.sw(t0, s7, 8); a.sw(zero, s7, 12); a.addiu(s7, s7, 16); a.jr()
    a.label('spr')                                   # a0,a1 -> a2,a3, colour t9 -> RGBAQ, XYZ2, XYZ2 (24 B)
    a.sw(t9, s7, 0); li(t1, Q_ONE); a.sw(t1, s7, 4); xyz(t0, a0, a1, t1); a.sw(t0, s7, 8); a.sw(zero, s7, 12)
    xyz(t0, a2, a3, t1); a.sw(t0, s7, 16); a.sw(zero, s7, 20); a.addiu(s7, s7, 24); a.jr()
    a.label('tspr')                                  # a0,a1 -> a2,a3, colour t9, uv t6 / t7 -> 5 regs (40 B)
    a.sw(t9, s7, 0); li(t1, Q_ONE); a.sw(t1, s7, 4); a.sw(t6, s7, 8); a.sw(zero, s7, 12); xyz(t0, a0, a1, t1); a.sw(t0, s7, 16); a.sw(zero, s7, 20)
    a.sw(t7, s7, 24); a.sw(zero, s7, 28); xyz(t0, a2, a3, t1); a.sw(t0, s7, 32); a.sw(zero, s7, 36); a.addiu(s7, s7, 40); a.jr()
    a.label('point')                                 # a0 = angle, t4 = cx, t5 = cy, t6 = rx, t7 = ry -> a0 = x, a1 = y; v0 = cos, v1 = sin
    andi(a0, a0, 255); a.li(t0, T['sin8']); addu(t1, t0, a0); lb(v1, t1, 0); a.addiu(t1, a0, 64); andi(t1, t1, 255); addu(t1, t0, t1); lb(v0, t1, 0)
    mullo(t0, t6, v0); sra(t0, t0, 7); addu(a0, t4, t0); mullo(t0, t7, v1); sra(t0, t0, 7); addu(a1, t5, t0); a.jr()
    a.label('inbox')                                 # a0 = x, a1 = y, s6 = ring -> v0 = 1 inside the exclusion box
    a.lw(t0, s6, 28); slt(v0, a0, t0); a.lw(t0, s6, 36); slt(t1, t0, a0); or_(v0, v0, t1)
    a.lw(t0, s6, 32); slt(t1, a1, t0); or_(v0, v0, t1); a.lw(t0, s6, 40); slt(t1, t0, a1); or_(v0, v0, t1); xori(v0, v0, 1); a.jr()

    # ---- FG_DRAW ------------------------------------------------------------------------------
    a.label('start')
    a.addiu(s6, s4, P.SLICES); a.move(s2, zero)
    a.label('slice')
    a.lw(t0, s6, 8); bne(t0, zero, 'slice_used')
    a.li(t1, T['fgtex']); sll(t2, s2, 3); addu(t1, t1, t2); a.lw(a1, t1, 0); a.lw(a2, t1, 4); li(a0, TEX0_REG); call('ad')
    TAG(1, 5)
    a.li(t0, 0x80808080); a.sw(t0, s7, 0); li(t0, Q_ONE); a.sw(t0, s7, 4); a.sw(zero, s7, 8); a.sw(zero, s7, 12)
    a.li(t0, (1792*16) | (xyz2_y(0) << 16)); a.sw(t0, s7, 16); a.sw(zero, s7, 20); a.sw(zero, s7, 24); a.sw(zero, s7, 28)
    a.sw(t0, s7, 32); a.sw(zero, s7, 36); a.sw(zero, s7, 40); a.sw(zero, s7, 44); a.addiu(s7, s7, 48)
    a.jump('slice_next')
    a.label('slice_used')
    a.lw(a1, s6, 40); a.lw(a2, s6, 44); li(a0, TEX0_REG); call('ad')
    TAG(1, 5)
    a.lw(t0, s6, 28); subu(t1, s5, t0); sltu(t2, s5, t0); movn(t1, zero, t2)          # d = f - start, 0 while f < start
    sltiu(t2, t1, 21); xori(t2, t2, 1); li(t3, 20); movn(t1, t3, t2)                   # min(d, 20)
    a.li(t2, T['ease']); addu(t2, t2, t1); lbu(t2, t2, 0)                             # p
    a.addiu(t3, t2, 1); srl(t3, t3, 1); sll(t3, t3, 24); a.li(t4, 0x808080); or_(t9, t3, t4)
    li(t3, 255); subu(t3, t3, t2)                                                      # 255 - p
    a.lw(t4, s6, 32); mullo(t4, t4, t3); sra(t4, t4, 8); a.lw(a0, s6, 0); addu(a0, a0, t4)
    a.lw(t4, s6, 36); mullo(t4, t4, t3); sra(t4, t4, 8); a.lw(a1, s6, 4); addu(a1, a1, t4)
    a.lw(t0, s6, 8); addu(a2, a0, t0); a.lw(t0, s6, 12); addu(a3, a1, t0)
    a.lw(t0, s6, 16); sll(t0, t0, 4); a.lw(t1, s6, 20); sll(t1, t1, 20); or_(t6, t0, t1)
    a.lw(t0, s6, 16); a.lw(t1, s6, 8); addu(t0, t0, t1); sll(t0, t0, 4); a.lw(t1, s6, 20); a.lw(t2, s6, 12); addu(t1, t1, t2); sll(t1, t1, 20); or_(t7, t0, t1)
    call('tspr'); pad_zero(8)
    a.label('slice_next')
    a.addiu(s6, s6, P.SLICE_STRIDE); a.addiu(s2, s2, 1); sltiu(t0, s2, MAX_SLICES); bne(t0, zero, 'slice')

    # ---- TICKS --------------------------------------------------------------------------------
    AD(ALPHA_REG, P.ADDITIVE)
    li(t0, TICK_FADE_START); subu(t1, s5, t0); sltu(t2, s5, t0); movn(t1, zero, t2)
    sltiu(t2, t1, TICK_FADE_FRAMES); xori(t2, t2, 1); sll(t1, t1, 2); li(t3, 128); movn(t1, t3, t2); a.sw(t1, sp, SCALE)
    a.addiu(s6, s4, P.TICKS); a.move(s2, zero)
    a.label('ring')
    a.lw(t0, s4, P.FLAGS); andi(t0, t0, P.FLAG_TICKS); sltiu(t0, t0, 1); a.lw(t1, s6, 16); sltiu(t1, t1, 1); or_(t0, t0, t1); a.sw(t0, sp, HID)
    sll(t0, s5, 6); a.lw(t1, s6, 20); bgez(t1, 'rot_ok'); subu(t0, zero, t0)
    a.label('rot_ok'); a.sw(t0, sp, ROT)
    li(t1, CURSOR_RATE); mullo(t0, s5, t1); a.lw(t1, s6, 20); blez(t1, 'cur_ok'); subu(t0, zero, t0)
    a.label('cur_ok'); a.sw(t0, sp, CUR)
    PRIM(P.LINE_LIST); TAG(2*LINES_PER_RING, 2)
    a.sw(zero, sp, K)
    a.label('tick')
    a.lw(t0, sp, K); a.lw(t1, s6, 16); a.li(t2, T['step']); sll(t3, t1, 1); addu(t2, t2, t3); lhu(t2, t2, 0)
    mullo(t3, t0, t2); a.lw(t4, sp, ROT); addu(t3, t3, t4); andi(t3, t3, 0xFFFF); srl(a0, t3, 8)
    a.lw(t4, s6, 0); a.lw(t5, s6, 4); a.lw(t6, s6, 8); a.lw(t7, s6, 12); call('point')
    a.sw(a0, sp, AX); a.sw(a1, sp, AY)                                                # base
    a.lw(t0, sp, K); andi(t0, t0, 3); li(t2, 3); li(t3, 2); movn(t2, t3, t0)          # L
    a.lw(t6, s6, 8); addu(t6, t6, t2); a.lw(t7, s6, 12); addu(t7, t7, t2)
    mullo(t0, t6, v0); sra(t0, t0, 7); addu(a2, t4, t0); mullo(t0, t7, v1); sra(t0, t0, 7); addu(a3, t5, t0)   # tip
    a.lw(a0, sp, AX); a.lw(a1, sp, AY); call('inbox')
    a.lw(t0, sp, HID); or_(v0, v0, t0); a.lw(t0, sp, K); a.lw(t1, s6, 16); sltu(t2, t0, t1); xori(t2, t2, 1); or_(v0, v0, t2)
    beq(v0, zero, 'tick_emit'); offscreen4()
    a.label('tick_emit')
    a.sw(a2, sp, TX); a.sw(a3, sp, TY); a.lw(t0, s6, 24); scaled(t1, TICK_ALPHA, SCALE); color_alpha(t9, t0, reg=t1)
    a.move(a2, t9); call('vtx'); a.lw(a0, sp, TX); a.lw(a1, sp, TY); a.move(a2, t9); call('vtx')
    a.lw(t0, sp, K); a.addiu(t0, t0, 1); a.sw(t0, sp, K); sltiu(t1, t0, TICKS_PER_RING); bne(t1, zero, 'tick')
    a.sw(zero, sp, K)
    a.label('cursor')
    for end, (X, Y) in ((0, (AX, AY)), (1, (TX, TY))):
        a.lw(t0, sp, K); a.addiu(t0, t0, end); li(t1, CURSOR_SEG); mullo(t3, t0, t1); a.lw(t4, sp, CUR); addu(t3, t3, t4); andi(t3, t3, 0xFFFF); srl(a0, t3, 8)
        a.lw(t4, s6, 0); a.lw(t5, s6, 4); a.lw(t6, s6, 8); a.addiu(t6, t6, CURSOR_RADIUS); a.lw(t7, s6, 12); a.addiu(t7, t7, CURSOR_RADIUS); call('point')
        a.sw(a0, sp, X); a.sw(a1, sp, Y)
    a.lw(a0, sp, AX); a.lw(a1, sp, AY); call('inbox'); a.move(t9, v0)
    a.lw(a0, sp, TX); a.lw(a1, sp, TY); call('inbox'); or_(t9, t9, v0); a.lw(t0, sp, HID); or_(t9, t9, t0)
    beq(t9, zero, 'cursor_emit'); li(t0, OFFSCREEN); a.sw(t0, sp, AX); a.sw(t0, sp, AY); a.sw(t0, sp, TX); a.sw(t0, sp, TY)
    a.label('cursor_emit')
    a.lw(t0, s6, 44); scaled(t1, CURSOR_ALPHA, SCALE); color_alpha(t9, t0, reg=t1)
    a.lw(a0, sp, AX); a.lw(a1, sp, AY); a.move(a2, t9); call('vtx'); a.lw(a0, sp, TX); a.lw(a1, sp, TY); a.move(a2, t9); call('vtx')
    a.lw(t0, sp, K); a.addiu(t0, t0, 1); a.sw(t0, sp, K); sltiu(t1, t0, CURSOR_SEGMENTS); bne(t1, zero, 'cursor')
    a.addiu(s6, s6, P.TICK_STRIDE); a.addiu(s2, s2, 1); sltiu(t0, s2, MAX_TICKS); bne(t0, zero, 'ring')

    # ---- GAUGE --------------------------------------------------------------------------------
    G = {name: P.GAUGE+4*i for i, name in enumerate(P.GAUGE_WORDS)}
    a.lw(t0, s4, P.FLAGS); andi(t0, t0, P.FLAG_GAUGE); sltiu(t0, t0, 1); a.sw(t0, sp, HID); ramp(GAUGE_START, GA)
    a.lw(t0, s4, G['x1']); a.lw(t1, s4, G['x0']); subu(t0, t0, t1); a.lw(t2, s4, G['fill']); mullo(t0, t0, t2)
    li(t2, 257); mullo(t0, t0, t2); a.li(t2, 32768); addu(t0, t0, t2); srl(t0, t0, 16); addu(t0, t0, t1)   # xf
    a.sw(t0, sp, XF); subu(t0, t0, t1); a.sw(t0, sp, WW)                                                  # W = xf - x0
    AD(ALPHA_REG, P.STANDARD); PRIM(P.STRIP); TAG(6, 2)
    a.lw(t0, sp, WW); li(t1, 179); mullo(t2, t0, t1); srl(t2, t2, 8); a.lw(t1, s4, G['x0']); addu(t2, t2, t1); a.sw(t2, sp, XB)   # xm
    for col, (xword, cname) in enumerate(((G['x0'], 'color0'), (None, 'color1'), (G['x1'], 'color2'))):
        for yname in ('y0', 'y1'):
            if col == 1: a.lw(a0, sp, XB)
            elif col == 0: a.lw(a0, s4, G['x0'])
            else: a.lw(a0, sp, XF)
            a.lw(a1, s4, G[yname]); a.lw(t0, s4, G[cname]); scaled(t1, 0x80, GA); color_alpha(a2, t0, reg=t1)
            a.lw(t0, sp, HID); beq(t0, zero, f'fill_{col}_{yname}'); li(a0, OFFSCREEN); a.move(a1, a0)
            a.label(f'fill_{col}_{yname}'); call('vtx')
    PRIM(P.SPRITE); TAG(20, 3)
    a.lw(t0, s4, G['x1']); a.lw(t1, s4, G['x0']); subu(t0, t0, t1); a.sw(t0, sp, T6)      # w = x1 - x0
    li(t0, 1); a.sw(t0, sp, K)
    a.label('divider')
    a.lw(t0, sp, K); a.lw(t1, sp, T6); mullo(t0, t0, t1); li(t1, 3277); mullo(t0, t0, t1); srl(t0, t0, 16); a.lw(t1, s4, G['x0']); addu(a0, t0, t1)
    a.lw(a1, s4, G['y0']); a.addiu(a2, a0, 1); a.lw(a3, s4, G['y1'])
    a.lw(t0, sp, XF); a.addiu(t0, t0, -2); slt(t1, a0, t0); xori(t1, t1, 1); a.lw(t0, sp, HID); or_(t1, t1, t0)
    beq(t1, zero, 'divider_emit'); offscreen4()
    a.label('divider_emit'); scaled(t1, DIVIDER_ALPHA, GA); a.li(t9, P.packed_color(DIVIDER_COLOR)); color_alpha(t9, t9, reg=t1); call('spr')
    a.lw(t0, sp, K); a.addiu(t0, t0, 1); a.sw(t0, sp, K); sltiu(t1, t0, 20); bne(t1, zero, 'divider')
    a.lw(a2, sp, XF); a.addiu(a0, a2, -2); a.lw(a1, s4, G['y0']); a.lw(a3, s4, G['y1'])
    a.lw(t0, sp, WW); sltiu(t1, t0, 2); a.lw(t0, sp, HID); or_(t1, t1, t0); beq(t1, zero, 'tip_emit'); offscreen4()
    a.label('tip_emit'); a.lw(t0, s4, G['tip']); scaled(t1, 0x80, GA); color_alpha(t9, t0, reg=t1); call('spr')
    AD(ALPHA_REG, P.ADDITIVE)
    for k in range(3):
        PRIM(P.STRIP); TAG(6, 2)
        li(t1, PULSE_SPEEDS[k]); mullo(t0, s5, t1); a.addiu(t0, t0, PULSE_OFFSETS[k]); andi(t0, t0, 511); a.lw(t1, sp, WW); mullo(t0, t0, t1); srl(t0, t0, 9)
        a.lw(t1, s4, G['x0']); addu(t0, t0, t1); a.sw(t0, sp, XB)                                  # xb
        a.addiu(t2, t0, -PULSE_HALF); slt(t3, t2, t1); a.addiu(t2, t0, PULSE_HALF); a.lw(t1, sp, XF); slt(t4, t1, t2); or_(t3, t3, t4)
        a.lw(t0, sp, HID); or_(t3, t3, t0); a.sw(t3, sp, T7)                                       # hidden pulse
        for col, (dx, cw) in enumerate(((-PULSE_HALF, 0), (0, 0xFFFFFF), (PULSE_HALF, 0))):
            for yname in ('y0', 'y1'):
                a.lw(a0, sp, XB); a.addiu(a0, a0, dx); a.lw(a1, s4, G[yname]); scaled(t1, PULSE_ALPHA, GA); a.li(a2, cw); color_alpha(a2, a2, reg=t1)
                a.lw(t0, sp, T7); beq(t0, zero, f'pulse_{k}_{col}_{yname}'); li(a0, OFFSCREEN); a.move(a1, a0)
                a.label(f'pulse_{k}_{col}_{yname}'); call('vtx')
    AD(TEX0_REG, P.ATLAS_TEX0 & 0xFFFFFFFF, P.ATLAS_TEX0 >> 32); PRIM(P.TSPRITE); TAG(12, 5)
    u, v, dw, dh = DOT_RECT
    a.li(t6, _uv(u, v)); a.li(t7, _uv(u+dw, v+dh))
    # tip glow
    li(t1, 19); mullo(t0, s5, t1); srl(t0, t0, 2); andi(a0, t0, 255)
    a.li(t0, T['sin8']); addu(t0, t0, a0); lb(t0, t0, 0); li(t1, GLOW_SWING); mullo(t0, t0, t1); sra(t0, t0, 7); a.addiu(t0, t0, GLOW_ALPHA); a.lw(t1, sp, GA); mullo(t0, t0, t1); srl(t0, t0, 7)
    a.li(t9, 0xFFFFFF); color_alpha(t9, t9, reg=t0)
    a.lw(t0, s4, G['y0']); a.lw(t1, s4, G['y1']); addu(t0, t0, t1); sra(t0, t0, 1); a.lw(t1, sp, XF)
    a.addiu(a0, t1, -(GLOW_SIZE >> 1)); a.addiu(a1, t0, -(GLOW_SIZE >> 1)); a.addiu(a2, t1, GLOW_SIZE >> 1); a.addiu(a3, t0, GLOW_SIZE >> 1)
    a.lw(t0, sp, WW); sltiu(t2, t0, 4); a.lw(t0, sp, HID); or_(t2, t2, t0); a.sw(t2, sp, T7)      # sparks and glow hidden while W < 4
    beq(t2, zero, 'glow_emit'); offscreen4()
    a.label('glow_emit'); call('tspr')
    # escaping sparks
    a.sw(zero, sp, K)
    a.label('spark')
    a.lw(t0, sp, K); sll(t1, t0, 3); addu(t1, t1, s5); andi(t1, t1, SPARK_LOOP-1)                   # i
    a.li(t2, T['life']); addu(t2, t2, t1); lbu(t2, t2, 0); a.lw(t3, sp, GA); mullo(t2, t2, t3); srl(t2, t2, 7); a.li(t9, 0xFFFFFF); color_alpha(t9, t9, reg=t2)
    a.li(t2, T['rise']); addu(t2, t2, t1); lbu(t2, t2, 0); a.lw(t3, s4, G['y0']); a.addiu(t3, t3, -1); subu(t3, t3, t2)   # y
    a.li(t2, T['spark_u']); addu(t2, t2, t0); lbu(t2, t2, 0); a.lw(t4, sp, WW); mullo(t2, t2, t4); srl(t2, t2, 8); a.lw(t4, s4, G['x0']); addu(t2, t2, t4)  # x
    a.li(t4, T['spark_size']); addu(t4, t4, t0); lbu(t4, t4, 0); srl(t5, t4, 1)
    subu(a0, t2, t5); subu(a1, t3, t5); addu(a2, a0, t4); addu(a3, a1, t4)
    a.lw(t0, sp, T7); beq(t0, zero, 'spark_emit'); offscreen4()
    a.label('spark_emit'); call('tspr')
    a.lw(t0, sp, K); a.addiu(t0, t0, 1); a.sw(t0, sp, K); sltiu(t1, t0, 8); bne(t1, zero, 'spark')
    # motes
    a.lw(t0, s4, G['progress']); li(t1, 50); slt(t1, t1, t0); xori(t1, t1, 1); a.lw(t2, sp, HID); or_(t1, t1, t2); a.sw(t1, sp, T7)   # hidden unless progress > 50
    a.addiu(t0, t0, -50); li(t2, 9); mullo(t0, t0, t2); srl(t0, t0, 1); sltiu(t2, t0, MOTE_ALPHA+1); xori(t2, t2, 1); li(t3, MOTE_ALPHA); movn(t0, t3, t2)
    a.lw(t2, sp, GA); mullo(t0, t0, t2); srl(t0, t0, 7); movn(t0, zero, t1); a.sw(t0, sp, T6)                                                              # mote alpha (0 when hidden)
    a.sw(zero, sp, K)
    a.label('mote')
    li(t1, 13); mullo(t0, s5, t1); srl(t0, t0, 3); a.lw(t1, sp, K); li(t2, 85); mullo(t1, t1, t2); addu(a0, t0, t1)
    a.lw(t4, s4, G['orb_cx']); a.lw(t5, s4, G['orb_cy']); a.lw(t6, s4, G['orb_rx']); a.addiu(t6, t6, MOTE_DX); a.lw(t7, s4, G['orb_ry']); a.addiu(t7, t7, MOTE_DY); call('point')
    a.addiu(a0, a0, -(MOTE_SIZE >> 1)); a.addiu(a1, a1, -(MOTE_SIZE >> 1)); a.addiu(a2, a0, MOTE_SIZE); a.addiu(a3, a1, MOTE_SIZE)
    a.lw(t0, sp, T6); a.li(t9, 0xFFFFFF); color_alpha(t9, t9, reg=t0)
    a.li(t6, _uv(u, v)); a.li(t7, _uv(u+dw, v+dh))
    a.lw(t0, sp, T7); beq(t0, zero, 'mote_emit'); offscreen4()
    a.label('mote_emit'); call('tspr')
    a.lw(t0, sp, K); a.addiu(t0, t0, 1); a.sw(t0, sp, K); sltiu(t1, t0, 3); bne(t1, zero, 'mote')
    # ki orb light
    PRIM(P.FAN); TAG(18, 2)
    li(t1, ORB_BREATHE); mullo(t0, s5, t1); srl(t0, t0, 8); andi(t0, t0, 255); a.li(t1, T['sin8']); addu(t1, t1, t0); lb(t1, t1, 0); a.sw(t1, sp, T6)   # sin8[a_b]
    li(t2, ORB_BREATHE_SWING); mullo(t2, t1, t2); sra(t2, t2, 7); a.addiu(t2, t2, ORB_BREATHE_BASE); a.lw(t3, s4, G['orb_alpha']); mullo(t2, t2, t3); srl(t2, t2, 7); a.lw(t3, sp, GA); mullo(t2, t2, t3); srl(t2, t2, 7)
    a.lw(t0, s4, G['orb_color']); a.li(t1, 0xFFFFFF); and_(t0, t0, t1); xori(t3, t0, 0xFFFF); a.li(t1, 0xFF0000); a.r(38, t3, t3, t1)   # 0xFFFFFF - c per channel
    srl(t3, t3, 1); a.li(t1, 0x7F7F7F); and_(t3, t3, t1); addu(t0, t0, t3); sll(t2, t2, 24); or_(a2, t0, t2)   # centre colour: c + ((255-c)>>1), alpha
    a.lw(a0, s4, G['orb_cx']); a.lw(a1, s4, G['orb_cy']); a.lw(t0, sp, HID); beq(t0, zero, 'orb_centre'); li(a0, OFFSCREEN); a.move(a1, a0)
    a.label('orb_centre'); call('vtx')
    a.sw(zero, sp, K)
    a.label('orb_rim')
    a.lw(t0, sp, K); sll(a0, t0, 4)
    a.lw(t4, s4, G['orb_cx']); a.lw(t5, s4, G['orb_cy']); a.lw(t6, s4, G['orb_rx']); sra(t0, t6, 1); addu(t6, t6, t0); a.lw(t7, s4, G['orb_ry']); sra(t0, t7, 1); addu(t7, t7, t0); call('point')
    a.move(a2, zero); a.lw(t0, sp, HID); beq(t0, zero, 'orb_rim_emit'); li(a0, OFFSCREEN); a.move(a1, a0)
    a.label('orb_rim_emit'); call('vtx')
    a.lw(t0, sp, K); a.addiu(t0, t0, 1); a.sw(t0, sp, K); sltiu(t1, t0, 17); bne(t1, zero, 'orb_rim')
    # rays
    PRIM(P.LINE_LIST); TAG(12, 2)
    a.lw(t1, sp, T6); li(t2, RAY_SWING); mullo(t2, t1, t2); sra(t2, t2, 7); a.addiu(t2, t2, RAY_ALPHA); a.lw(t3, sp, GA); mullo(t2, t2, t3); srl(t2, t2, 7); a.li(t9, 0xFFFFFF); color_alpha(t9, t9, reg=t2)
    a.lw(t0, s4, G['progress']); xori(t0, t0, 100); sltiu(t0, t0, 1); xori(t0, t0, 1); a.lw(t1, sp, HID); or_(t0, t0, t1); a.sw(t0, sp, T7)   # hidden unless progress == 100
    a.sw(zero, sp, K)
    a.label('ray')
    for r in (RAY_IN, RAY_OUT):
        li(t1, RAY_RATE); mullo(t0, s5, t1); srl(t0, t0, 5); a.lw(t1, sp, K); li(t2, 43); mullo(t1, t1, t2); addu(a0, t0, t1)
        a.lw(t4, s4, G['orb_cx']); a.lw(t5, s4, G['orb_cy']); a.lw(t6, s4, G['orb_rx']); a.addiu(t6, t6, r); a.lw(t7, s4, G['orb_ry']); a.addiu(t7, t7, r); call('point')
        a.move(a2, t9); a.lw(t0, sp, T7); beq(t0, zero, f'ray_emit_{r}'); li(a0, OFFSCREEN); a.move(a1, a0)
        a.label(f'ray_emit_{r}'); call('vtx')
    a.lw(t0, sp, K); a.addiu(t0, t0, 1); a.sw(t0, sp, K); sltiu(t1, t0, 6); bne(t1, zero, 'ray')
    # percentage
    AD(ALPHA_REG, P.STANDARD); PRIM(P.TSPRITE); TAG(4, 5)
    a.addiu(s6, s4, P.GAUGE_DIGITS); a.sw(zero, sp, K)
    a.label('digit')
    a.lw(t0, s6, 0); sll(t0, t0, 4); a.lw(t1, s6, 4); sll(t1, t1, 20); or_(t6, t0, t1)
    a.lw(t0, s6, 0); a.lw(t1, s6, 8); addu(t0, t0, t1); sll(t0, t0, 4); a.lw(t1, s6, 4); a.lw(t2, s6, 12); addu(t1, t1, t2); sll(t1, t1, 20); or_(t7, t0, t1)
    a.lw(a0, s6, 16); a.lw(a1, s6, 20); a.lw(t0, s6, 8); addu(a2, a0, t0); a.lw(t1, s6, 12); addu(a3, a1, t1)
    sltiu(t0, t0, 1); a.lw(t1, sp, HID); or_(t0, t0, t1); beq(t0, zero, 'digit_emit'); offscreen4()
    a.label('digit_emit'); scaled(t1, 0x80, GA); a.li(t9, 0xFFFFFF); color_alpha(t9, t9, reg=t1); call('tspr')
    a.addiu(s6, s6, P.DIGIT_STRIDE); a.lw(t0, sp, K); a.addiu(t0, t0, 1); a.sw(t0, sp, K); sltiu(t1, t0, 4); bne(t1, zero, 'digit')

    # ---- SHEENS -------------------------------------------------------------------------------
    AD(ALPHA_REG, P.ADDITIVE)
    a.lw(t0, s4, P.FLAGS); andi(t0, t0, P.FLAG_SHEENS); sltiu(t0, t0, 1); a.sw(t0, sp, HID)
    for k in range(2):
        PRIM(P.STRIP); TAG(6, 2); base = P.SHEENS+16*k
        li(t1, SHEEN_SPEED); mullo(t0, s5, t1); a.addiu(t0, t0, SHEEN_PHASE+SHEEN_STAGGER*k); andi(t0, t0, 511); a.addiu(t0, t0, -SHEEN_LEAD); a.lw(t1, s4, base); addu(t0, t0, t1); a.sw(t0, sp, XB)   # xa
        for col, (dx, cw) in enumerate(((0, _color(0, SHEEN_ALPHA)), (SHEEN_WIDTH//2, _color(0xFFFFFF, SHEEN_ALPHA)), (SHEEN_WIDTH, _color(0, SHEEN_ALPHA)))):
            for lean, yoff in ((0, 12), (SHEEN_LEAN, 4)):
                a.lw(a0, sp, XB); a.addiu(a0, a0, dx+lean)
                a.lw(t0, s4, base); slt(t1, a0, t0); movn(a0, t0, t1); a.lw(t0, s4, base+8); slt(t1, t0, a0); movn(a0, t0, t1)   # clamp to x0..x1
                a.lw(a1, s4, base+yoff); a.li(a2, cw)
                a.lw(t0, sp, HID); beq(t0, zero, f'sheen_{k}_{col}_{lean}'); li(a0, OFFSCREEN); a.move(a1, a0)
                a.label(f'sheen_{k}_{col}_{lean}'); call('vtx')

    # ---- DOTS ---------------------------------------------------------------------------------
    AD(ALPHA_REG, P.STANDARD); PRIM(P.SPRITE); TAG(3, 3)
    a.lw(t0, s4, P.FLAGS); andi(t0, t0, P.FLAG_DOTS); sltiu(t0, t0, 1); a.sw(t0, sp, HID)
    srl(t0, s5, 4); andi(t0, t0, 0xFFFF); a.li(t1, 0xAAAB); mullo(t1, t0, t1); srl(t1, t1, 17); sll(t2, t1, 1); addu(t1, t1, t2); subu(t0, t0, t1); a.sw(t0, sp, T6)   # (f>>4) mod 3
    for k in range(3):
        a.lw(t0, s4, P.DOTS+16); a.lw(t1, sp, T6); xori(t1, t1, k); li(t2, DOT_LIT); li(t3, DOT_DIM); movn(t2, t3, t1); a.lw(t3, sp, GA); mullo(t2, t2, t3); srl(t2, t2, 7); color_alpha(t9, t0, reg=t2)
        a.lw(a0, s4, P.DOTS); a.lw(t0, s4, P.DOTS+8); li(t1, k); mullo(t0, t0, t1); addu(a0, a0, t0); a.lw(a1, s4, P.DOTS+4); a.lw(t0, s4, P.DOTS+12); addu(a2, a0, t0); addu(a3, a1, t0)
        a.lw(t0, sp, HID); beq(t0, zero, f'dot_{k}'); offscreen4()
        a.label(f'dot_{k}'); call('spr')
    pad_zero(8)

    # ---- RESTORE ------------------------------------------------------------------------------
    a.li(t0, 2 | 0x8000); a.sw(t0, s7, 0); li(t0, A_TAG_HIGH); a.sw(t0, s7, 4); li(t0, 0xE); a.sw(t0, s7, 8); a.sw(zero, s7, 12)
    a.li(t0, P.SETUP_TEST); a.sw(t0, s7, 16); a.sw(zero, s7, 20); li(t0, TEST_REG); a.sw(t0, s7, 24); a.sw(zero, s7, 28)
    li(t0, P.STANDARD); a.sw(t0, s7, 32); a.sw(zero, s7, 36); li(t0, ALPHA_REG); a.sw(t0, s7, 40); a.sw(zero, s7, 44); a.addiu(s7, s7, 48)
    a.lw(t8, sp, P.KS_RETURN); a.jr(t8)
    data = a.finish(); assert len(data) < END-CODE, len(data); return data
