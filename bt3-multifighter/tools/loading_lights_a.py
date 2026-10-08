"""KS_A: the LIGHT_A emitters of the Ki Storm loading cover (PORT-SPEC 5.2), drawn between
packet A (background) and packet B (foreground register state): the storm behind the cards.

Entry/return convention (shared with loading_lights_b):
- The payload allocates the block through 0x100878 and enters with a plain `j ENTRY`:
  s7 (r23) = arena write cursor: every emitted byte advances it; on return the payload closes
  the allocation from it through 0x100890;
  s4 (r20) = descriptor pointer (loading_protocol layout, magic already verified, never 0);
  s5 (r21) = the surface's frame counter f, already incremented for this frame;
  s6 (r22) = the published buffer (clobbered here: it holds the sine table base);
  s0 (r16) = guest_loading_screen.CONTROL (CONTROL+44 = the clash cycle c, 0..149, already
  advanced for this frame); sp = the payload frame (FRAME 0x100): the return address sits at
  loading_protocol.KS_RETURN(sp); 0xA0..0xF7 are the piece's scratch words (SCRATCH below);
  0x70..0x9F belong to the SUBS strip/bolt helpers (not called here).
- Returns with `lw t8, KS_RETURN(sp); jr t8`. Preserves s0, s1, s3, s4, s5, sp, gp; clobbers
  s2 (element base pointer), s6, v0, v1, a0..a3, t0..t9, ra. Calls the SUBS `prim` and
  `vertex` helpers (they clobber t0/t1 only and write at s7).
- Emits exactly SIZE bytes on every frame: hidden or disabled elements stay in the stream as
  degenerate geometry (every vertex at OFFSCREEN for strips/fans/lines, x0 == x1 for sprites).

Emission table (ORDER): every primitive block = one A+D PRIM write (32 B) + one REGLIST
GIFtag (16 B) + its registers (8 B each, padded to a qword and the pad written), EOP set on
every tag as the v3 emitters do. State on entry: ALPHA 0x44, TEST 0x30000, TEX0 = background.
  alpha_standard   A+D ALPHA_1 STANDARD                                          32
  fade             1 flat sprite PRIM 0x46 (RGBAQ, XYZ2, XYZ2 + pad)             80
  alpha_additive   A+D ALPHA_1 ADDITIVE                                          32
  ribbons          6 x 4 gouraud strips PRIM 0x4C, 34 vertices each          14208
  spark_state      A+D TEX0_1 ATLAS_TEX0, TEX1_1 nearest, CLAMP_1 5                 96
  sparks           128 textured sprites PRIM 0x156 under one tag (NREG 5)     5168
  orbs             2 x (halo fan 26, body fan 26, body ring strip 50)         3552
  seam             1 fan 12 segments (14 vertices)                             272
  flash            1 fan 24 segments (26 vertices)                             464
  ring             1 strip 48 segments (98 vertices) + 49-point line strip    2448
  bolts            2 x 3 line strips of 9 points                              1152
  chevrons         8 three-point line strips                                   768
  alpha_restore    A+D ALPHA_1 STANDARD                                          32
FLAGS gate the elements: FADE (1) the fade, RIBBONS (2) ribbons + sparks, STORM (4) the rest.

Formulas (all integer; f = the frame counter as a 32-bit word, products of f wrap at 32 bits
before a shift; `sin8` = SIN8 (256 x int8, -127..127), cos8[a] = sin8[(a+64)&255]; every
angle is & 255; every packed colour is r|g<<8|b<<16|a<<24):
- fade: alpha FADE25[f] = (24-f)*128/24 while f < 24 (FADE_FRAMES is taken as 24).
- ribbon r, cross-section i (i16 = 16*i, i = 0..16): ramp = 0 if f < fade_start, 255 if
  f - fade_start >= 54, else RAMP54[f - fade_start] (ease-out; fade_end is taken as
  fade_start + 54); x = x0 + ((x1-x0)*i16 >> 8) + (A1*sin8[(f1*i16 + ((w1*f)>>3) + p1)&255]
  + A2*sin8[(f2*i16 - ((w2*f)>>3) + p2)&255]) >> 7; y = y0 + ((y1-y0)*i16 >> 8);
  breath = 80 + (48*sin8[(((wf*i16)>>4) + ((f*3)>>2) + wp)&255] >> 7) (32..127);
  hw = (W*BELL17[i16>>4]*breath) >> 16 (half width, at most W/2); band = 160 +
  (96*sin8[(i16*3 - f*6)&255] >> 7); k = (ramp*band) >> 8; c = colours[i16>>4] with each of
  r, g, b scaled by k >> 8 (alpha 0x80); q = c with r, g, b halved. Strip j (0..3) pairs the
  offsets e = j-2 and j-1 (in half widths): vertex (x + ((hw*e)>>1), y) coloured c for e = 0,
  q for |e| = 1 and 0 (black, alpha 0) for |e| = 2 (edge -> 25% -> centre -> 25% -> edge).
- spark: v = (f*speed + u*4) & 511 (the climb); the ribbon cross-section at i16 = v >> 1
  (so the spark sits on its ribbon's centre line at that height); x += (3*sin8[(((f*11)>>3)
  + phase*2)&255] >> 7) + ((((twinkle>>4) - 8)*hw) >> 3); y = the cross-section y; hidden
  unless region.x0 <= x < region.x1 and region.y0 <= y < region.y1 (the ribbon's side picks
  the region); alpha = ((END16[v>>5]*(77 + (51*sin8[(f*9 + twinkle)&255] >> 7))) >> 7) *
  ramp >> 8; RGB = the ribbon's colours[8] halved plus 0x80 per channel (modulate: white-hot
  centre, tinted fringe); box: dot (size+2) square, streak (size-1) x (size*3), centred on
  (x, y); UV from ATLAS_DOT / ATLAS_STREAK in 1/16 texel.
- orb: f < 54 (flight): cy = flight_y + ((cy - flight_y)*EIN54[f] >> 8), rx = rx*113 >> 7,
  ry = ry*154 >> 7, alpha = min(128, (f*455) >> 6), halo hidden; f >= 54: rs = 128 +
  ((c*13)>>7), rx = rx*rs >> 7, ry = ry*rs >> 7, and when c < 21 rel = 255 - EASE21[c],
  rx = rx*(128 + (32*rel >> 8)) >> 7, ry = ry*(128 - (23*rel >> 8)) >> 7, alpha 128.
  Halo fan (2rx, 2ry): centre halo colour alpha 0x60 -> rim black (alpha 0). Body fan to
  (rx*90 >> 7, ry*90 >> 7): centre core -> rim team, alpha as above. Body ring strip from the
  body radius to (rx, ry): team (alpha) -> deep (alpha >> 2). Fans: 24 segments, angles
  ANG49[2k]; circle point x = cx + (rx*cos8[a] >> 7), y = cy + (ry*sin8[a] >> 7).
- seam (f >= 54): fan 12 segments (ANG49[4k]), centre colour alpha 0x40 + ((c*43)>>7), rim
  edge colour alpha 0. Flash: k = f - 54 < 18: fan 24 segments, centre colour alpha
  FLASH18[k], rim edge alpha 0.
- shockwave (f >= 54): age = (f - 54) mod 150 (the cycle; c is not used), visible while
  age < 90: R = RING_R[age] (design px, 40 + 430*ease_out(age/90)), w = RING_W14[age] for the
  first ring (f - 54 < 150) else RING_W8[age], rin = R - (w>>1), rout = rin + w, per axis
  rx = (r*205)>>8, ry = (r*239)>>8; strip of 48 segments (ANG49[k], inner/outer pairs),
  colour LEFT where cos8[a] < 0 else RIGHT, alpha RING_A[age]; then the 1 px INNER line strip
  (49 points at R, same alpha).
- bolt k (f >= 54): n = f + 37k, life = n & period, burst = (n - life) >> 6, visible when
  life < duration and noise[burst & 127] >= 112; base = (burst*7 + (life>>2)*5 + 64);
  point i (0..8): x = x0 + ((x1-x0)*i >> 3), y = y0 + ((y1-y0)*i >> 3) + (sin8[i*16]*bulge
  >> 7), inner points (1..7) jittered by (noise[(base + 11i)&127] >> 4) - 8 in x and
  (noise[(base + 11i + 5)&127] >> 4) - 8 in y; three strips at y+1, y-1 (glow colour, alpha
  BOLT8[life]*38 >> 7) and y (colour, alpha BOLT8[life]); the end points carry alpha 0.
- chevron k (0..3, f >= 54, count != 0): t = (f + 200 - stagger*k) mod 50 (period taken as
  50), q = t*pitch / 50 (exact), dy = offset + k*pitch - q, alpha CHEV50[t], colour colours
  [k & 1]; above: (cx-7, y-5), (cx, y), (cx+7, y-5) at y = cy - dy; below: (cx-7, y+5),
  (cx, y), (cx+7, y+5) at y = cy + dy. Modulo by a constant uses the multiply-high magic
  MAGIC[d] (exact for every 32-bit n, asserted).
"""
import math
import struct
from regional import Y_ORIGIN, xyz2_y, emit_window_y

CODE, END = 0x07474000, 0x07476000
ENTRY = CODE
OFFSCREEN = -64
ORIGIN = (1792, Y_ORIGIN)                 # design rows are stretched onto a 512-line frame (regional)
Q_ONE = 0x3F800000
ALPHA_1, TEX0_1, TEX1_1, CLAMP_1 = 0x42, 0x06, 0x14, 0x08
STRIP, FAN, LINE_STRIP, SPRITE, TSPRITE = 0x4C, 0x4D, 0x4A, 0x46, 0x156
STANDARD, ADDITIVE = 0x44, 0x48
ATLAS_DOT, ATLAS_STREAK = (211, 0, 13, 15), (227, 0, 5, 21)     # pinned against loading_art_v4.atlas() by the tests
N_RIBBONS, N_STRIPS, N_XSECT = 6, 4, 17
N_SPARKS = 128
FIRST, CYCLE, RING_LIFE = 54, 150, 90
SCRATCH = dict(RA=0xA0, RA2=0xA4, X=0xA8, Y=0xAC, HW=0xB0, C=0xB4, RAMP=0xB8, CX=0xBC, CY=0xC0, RXI=0xC4, RYI=0xC8, RXO=0xCC, RYO=0xD0,
               CI=0xD4, CO=0xD8, N=0xDC, STEP=0xE0, HIDDEN=0xE4, MODE=0xE8, T0=0xEC, T1=0xF0, T2=0xF4)
assert all(0xA0 <= v < 0xF8 for v in SCRATCH.values())


# ---- tables (shared by the guest piece and the host model) ---------------------------------------
def _ease_out(u): return 1-(1-u)**3


SIN8 = [max(-127, min(127, int(round(127*math.sin(2*math.pi*a/256))))) for a in range(256)]
EASE21 = [int(round(255*_ease_out(k/20))) for k in range(21)]
BELL17 = [int(round(255*(0.45+0.55*math.sin(math.pi*i/16)))) for i in range(17)]
FADE25 = [((24-f)*128)//24 for f in range(25)]
RAMP54 = [int(round(255*_ease_out(d/54))) for d in range(54)]
EIN54 = [int(round(256*(f/54)**2.2)) for f in range(54)]
END16 = [int(round(128*math.sin(math.pi*(k+0.5)/16))) for k in range(16)]
ANG49 = [int(round(k*256/48)) & 255 for k in range(49)]
FLASH18 = [int(round(128*(18-k)/18)) for k in range(18)]
BOLT8 = [int(round(128*(1-k/8)**0.7)) for k in range(8)]
CHEV50 = [int(round(128*0.85*math.sin(math.pi*t/50)**2)) for t in range(50)]
RING_R = [int(round(40+430*_ease_out(age/90))) for age in range(90)]
RING_W8 = [int(round(8*(1-age/90)+1)) for age in range(90)]
RING_W14 = [int(round(14*(1-age/90)+1)) for age in range(90)]
RING_A = [int(round(128*(1-age/90)**1.6)) for age in range(90)]
assert EASE21[20] == 255 and RAMP54[0] == 0 and FADE25[24] == 0 and ANG49[24] == 128 and ANG49[48] == 0
assert all(0 <= v < 256 for t in (EASE21, BELL17, FADE25, RAMP54, EIN54, END16, FLASH18, BOLT8, CHEV50, RING_W8, RING_W14, RING_A) for v in t)
assert all(0 <= v < 65536 for v in RING_R)


def magic(d, s):
    """(m, s): floor(n/d) == (n*m >> (32+s)) for every 32-bit n (m fits 32 bits, e <= 2^s)."""
    m = -(-(1 << (32+s))//d); e = m*d-(1 << (32+s))
    if not (0 < m < 1 << 32 and 0 <= e <= 1 << s): raise ValueError('no exact magic')
    return m, s


MAGIC = {50: magic(50, 5), 150: magic(150, 7)}


def _mod(n, d):
    """Exactly what the guest computes: n - (mulhu(n, m) >> s)*d for the 32-bit word n."""
    n &= 0xFFFFFFFF; m, s = MAGIC[d]; q = ((n*m) >> 32) >> s
    assert q == n//d
    return n-q*d


def u32(x): return x & 0xFFFFFFFF


def s32(x): x &= 0xFFFFFFFF; return x-(1 << 32) if x >> 31 else x


def circle(cx, cy, rx, ry, a):
    return cx+((rx*SIN8[(a+64) & 255]) >> 7), cy+((ry*SIN8[a]) >> 7)


def with_alpha(color, a): return (color & 0xFFFFFF) | ((a & 255) << 24)


def scale_rgb(color, k):
    """r, g, b scaled by k/256 (k 0..255), alpha 0x80: the guest's per-channel mult + srl 8."""
    r, g, b = color & 255, (color >> 8) & 255, (color >> 16) & 255
    return ((r*k) >> 8) | (((g*k) >> 8) << 8) | (((b*k) >> 8) << 16) | 0x80000000


# ---- emission table ---------------------------------------------------------------------------------
PRIM_BYTES, TAG_BYTES = 32, 16


def _block(vertices): return PRIM_BYTES+TAG_BYTES+16*vertices


ORDER = (('alpha_standard', 32), ('fade', PRIM_BYTES+TAG_BYTES+32), ('alpha_additive', 32),
         ('ribbons', N_RIBBONS*N_STRIPS*_block(2*N_XSECT)), ('spark_state', 3*32), ('sparks', PRIM_BYTES+TAG_BYTES+N_SPARKS*40),
         ('orbs', 2*(_block(26)+_block(26)+_block(50))), ('seam', _block(14)), ('flash', _block(26)), ('ring', _block(98)+_block(49)),
         ('bolts', 2*3*_block(9)), ('chevrons', 8*_block(3)), ('alpha_restore', 32))
SIZE = sum(n for _, n in ORDER)
assert SIZE % 16 == 0


# ---- host model --------------------------------------------------------------------------------------
class _Desc:
    """Descriptor words the way the guest reads them (lw from s4)."""
    def __init__(self, data):
        import loading_protocol as protocol
        if isinstance(data, dict): data = protocol.encode_lights(data)
        if len(data) != protocol.DESCRIPTOR: raise ValueError('descriptor size')
        self.data = bytes(data); self.p = protocol

    def w(self, off): return struct.unpack_from('<I', self.data, off)[0]
    def s(self, off): return s32(self.w(off))
    def noise(self, i): return self.data[self.p.NOISE+(i & 127)]

    def fields(self, base, names, signed=('x0', 'x1', 'y0', 'y1', 'bulge', 'cx', 'cy', 'flight_y', 'offset', 'direction')):
        return {name: (self.s if name in signed else self.w)(base+4*i) for i, name in enumerate(names)}


def _hidden_verts(n): return [(OFFSCREEN, OFFSCREEN, 0)]*n


def ribbon_ramp(f, fade_start):
    if u32(f) < u32(fade_start): return 0
    d = u32(f-fade_start)
    return 255 if d >= 54 else RAMP54[d]


def xsect(rb, i16, f):
    """(x, y, hw, c, ramp) of a ribbon cross-section at i16 (0..256): the guest's `xsect`."""
    f = u32(f)
    ramp = ribbon_ramp(f, rb['fade_start'])
    a1 = (rb['f1']*i16+(u32(rb['w1']*f) >> 3)+rb['p1']) & 255
    a2 = (rb['f2']*i16-(u32(rb['w2']*f) >> 3)+rb['p2']) & 255
    x = rb['x0']+(((rb['x1']-rb['x0'])*i16) >> 8)+((rb['A1']*SIN8[a1]+rb['A2']*SIN8[a2]) >> 7)
    y = rb['y0']+(((rb['y1']-rb['y0'])*i16) >> 8)
    breath = 80+((48*SIN8[(((rb['wf']*i16) >> 4)+(u32(f*3) >> 2)+rb['wp']) & 255]) >> 7)
    hw = (rb['W']*BELL17[i16 >> 4]*breath) >> 16
    band = 160+((96*SIN8[(i16*3-u32(f*6)) & 255]) >> 7)
    c = scale_rgb(rb['colors'][i16 >> 4], (ramp*band) >> 8)
    return x, y, hw, c, ramp


def _ribbon(d, r):
    p = d.p; base = p.RIBBONS+r*p.RIBBON_STRIDE
    rb = d.fields(base, p.RIBBON_WORDS)
    rb['colors'] = [d.w(base+p.RIBBON_COLORS+4*j) for j in range(17)]
    return rb


def model(descriptor, f, c):
    """The exact primitive list the guest emits for descriptor bytes (or a plan), frame f, cycle c."""
    d = _Desc(descriptor); p = d.p; f = u32(f); c = u32(c)
    flags = d.w(p.FLAGS); n_ribbons = d.w(p.N_RIBBONS)
    storm = bool(flags & p.FLAG_STORM); settled = storm and f >= FIRST
    out = [('ad', ALPHA_1, STANDARD)]
    # fade
    if flags & p.FLAG_FADE and f < 24:
        out.append(('sprite', SPRITE, [(with_alpha(d.w(p.FADE_COLOR), FADE25[f]), 0, 0, 512, 448)]))
    else: out.append(('sprite', SPRITE, [(0, OFFSCREEN, OFFSCREEN, OFFSCREEN, OFFSCREEN)]))
    out.append(('ad', ALPHA_1, ADDITIVE))
    # ribbons
    ribbons = [_ribbon(d, r) for r in range(N_RIBBONS)]
    for r in range(N_RIBBONS):
        visible = bool(flags & p.FLAG_RIBBONS) and r < n_ribbons
        for j in range(N_STRIPS):
            verts = []
            for i in range(N_XSECT):
                if not visible: verts += _hidden_verts(2); continue
                x, y, hw, col, _ = xsect(ribbons[r], 16*i, f)
                q = ((col & 0xFEFEFE) >> 1) | 0x80000000
                for e in (j-2, j-1):
                    verts.append((x+((hw*e) >> 1), y, col if e == 0 else q if e*e == 1 else 0))
            out.append(('verts', STRIP, verts))
    # sparks
    out += [('ad', TEX0_1, p.ATLAS_TEX0), ('ad', TEX1_1, p.NEAREST_TEX1), ('ad', CLAMP_1, p.CLAMP_BOTH)]
    sprites = []
    for i in range(N_SPARKS):
        w0, w1 = d.w(p.SPARK_ENTRIES+8*i), d.w(p.SPARK_ENTRIES+8*i+4)
        rb, u, speed, phase = w0 & 255, (w0 >> 8) & 255, (w0 >> 16) & 255, w0 >> 24
        size, streak, tw = w1 & 255, (w1 >> 8) & 255, (w1 >> 16) & 255
        sprites.append(spark(d, ribbons, flags & p.FLAG_RIBBONS and rb < n_ribbons, rb, u, speed, phase, size, streak, tw, f))
    out.append(('tsprite', TSPRITE, sprites))
    # orbs
    for k in range(2):
        orb = d.fields(p.ORBS+k*p.ORB_STRIDE, p.ORB_WORDS)
        cx, cy, rx, ry = orb['cx'], orb['cy'], orb['rx'], orb['ry']
        if f < FIRST:
            cy = orb['flight_y']+(((cy-orb['flight_y'])*EIN54[f]) >> 8); rx = (rx*113) >> 7; ry = (ry*154) >> 7
            alpha = min(128, u32(f*455) >> 6); halo_hidden = True
        else:
            rs = 128+(u32(c*13) >> 7); rx = (rx*rs) >> 7; ry = (ry*rs) >> 7
            if c < 21:
                rel = 255-EASE21[c]; rx = (rx*(128+((32*rel) >> 8))) >> 7; ry = (ry*(128-((23*rel) >> 8))) >> 7
            alpha = 128; halo_hidden = False
        out.append(fan(cx, cy, 2*rx, 2*ry, with_alpha(orb['halo'], 0x60), with_alpha(orb['halo'], 0), 24, 2, not storm or halo_hidden))
        bx, by = (rx*90) >> 7, (ry*90) >> 7
        out.append(fan(cx, cy, bx, by, with_alpha(orb['core'], alpha), with_alpha(orb['team'], alpha), 24, 2, not storm))
        out.append(ring(cx, cy, bx, by, rx, ry, with_alpha(orb['team'], alpha), with_alpha(orb['deep'], alpha >> 2), 24, 2, 0, not storm))
    # seam, flash
    seam = d.fields(p.SEAM, p.SEAM_WORDS)
    out.append(fan(seam['cx'], seam['cy'], seam['rx'], seam['ry'], with_alpha(seam['color'], 0x40+(u32(c*43) >> 7)), with_alpha(seam['edge'], 0), 12, 4, not settled))
    flash = d.fields(p.FLASH, p.FLASH_WORDS); k = u32(f-FIRST)
    out.append(fan(flash['cx'], flash['cy'], flash['rx'], flash['ry'], with_alpha(flash['color'], FLASH18[k] if k < 18 else 0), with_alpha(flash['edge'], 0), 24, 2, not settled or k >= 18))
    # shockwave ring + inner line
    rg = d.fields(p.RING, p.RING_WORDS); age = _mod(u32(f-FIRST), CYCLE); shown = settled and age < RING_LIFE
    if shown:
        R = RING_R[age]; w = (RING_W14 if u32(f-FIRST) < CYCLE else RING_W8)[age]; rin = R-(w >> 1); rout = rin+w; a = RING_A[age]
        out.append(ring(rg['cx'], rg['cy'], (rin*205) >> 8, (rin*239) >> 8, (rout*205) >> 8, (rout*239) >> 8, with_alpha(rg['left'], a), with_alpha(rg['right'], a), 48, 1, 1, False))
        out.append(fan(rg['cx'], rg['cy'], (R*205) >> 8, (R*239) >> 8, 0, with_alpha(rg['inner'], a), 48, 1, False, LINE_STRIP))
    else:
        out.append(ring(0, 0, 0, 0, 0, 0, 0, 0, 48, 1, 1, True)); out.append(fan(0, 0, 0, 0, 0, 0, 48, 1, True, LINE_STRIP))
    # bolts
    for k in range(2):
        b = d.fields(p.BOLTS+k*p.BOLT_STRIDE, p.BOLT_WORDS)
        n = u32(f+37*k); life = n & b['period']; burst = u32(n-life) >> 6
        visible = settled and life < b['duration'] and d.noise(burst) >= 112
        base = burst*7+(life >> 2)*5+64
        alpha = BOLT8[min(life, 7)] if visible else 0; glow_a = (alpha*38) >> 7
        for dy, color in ((1, with_alpha(b['glow'], glow_a)), (-1, with_alpha(b['glow'], glow_a)), (0, with_alpha(b['color'], alpha))):
            verts = []
            for i in range(9):
                if not visible: verts.append((OFFSCREEN, OFFSCREEN, 0)); continue
                x = b['x0']+(((b['x1']-b['x0'])*i) >> 3); y = b['y0']+(((b['y1']-b['y0'])*i) >> 3)+((SIN8[i*16]*b['bulge']) >> 7)
                if 1 <= i <= 7: x += (d.noise(base+11*i) >> 4)-8; y += (d.noise(base+11*i+5) >> 4)-8
                verts.append((x, y+dy, color if 1 <= i <= 7 else with_alpha(color, 0)))
            out.append(('verts', LINE_STRIP, verts))
    # chevrons
    ch = d.fields(p.CHEVRONS, p.CHEVRON_WORDS); visible = settled and ch['count'] != 0
    for k in range(4):
        t = _mod(u32(f+200-ch['stagger']*k), 50); q = (t*ch['pitch'])//50; dy = ch['offset']+k*ch['pitch']-q
        color = with_alpha(ch['color1'] if k & 1 else ch['color0'], CHEV50[t]); cx, cy = ch['cx'], ch['cy']
        for sign in (-1, 1):
            if not visible: out.append(('verts', LINE_STRIP, _hidden_verts(3))); continue
            y = cy+sign*dy
            out.append(('verts', LINE_STRIP, [(cx-7, y+sign*5, color), (cx, y, color), (cx+7, y+sign*5, color)]))
    out.append(('ad', ALPHA_1, STANDARD))
    return out


def spark(d, ribbons, visible, rb, u, speed, phase, size, streak, tw, f):
    hidden = (0, 0, 0, OFFSCREEN, OFFSCREEN, 0, 0, OFFSCREEN, OFFSCREEN)
    if not visible: return hidden
    p = d.p; ribbon = ribbons[rb]; f = u32(f)
    v = u32(f*speed+u*4) & 511
    x, y, hw, _, ramp = xsect(ribbon, v >> 1, f)
    x += ((3*SIN8[((u32(f*11) >> 3)+phase*2) & 255]) >> 7)+((((tw >> 4)-8)*hw) >> 3)
    region = d.fields(p.SPARK_REGIONS+16*(ribbon['side'] & 1), p.SPARK_REGION_WORDS)
    if not (region['x0'] <= x < region['x1'] and region['y0'] <= y < region['y1']): return hidden
    twk = 77+((51*SIN8[u32(f*9+tw) & 255]) >> 7)
    a = (((END16[v >> 5]*twk) >> 7)*ramp) >> 8
    tint = ((ribbon['colors'][8] & 0xFEFEFE) >> 1)+0x808080
    if streak: bw, bh, (au, av, aw, ah) = size-1, size*3, ATLAS_STREAK
    else: bw, bh, (au, av, aw, ah) = size+2, size+2, ATLAS_DOT
    x0, y0 = x-(bw >> 1), y-(bh >> 1)
    return (tint | (a << 24), au*16, av*16, x0, y0, (au+aw)*16, (av+ah)*16, x0+bw, y0+bh)


def fan(cx, cy, rx, ry, ci, co, n, step, hidden, prim=FAN):
    """Centre (unless a line strip) + n+1 rim vertices at ANG49[k*step]."""
    verts = [] if prim == LINE_STRIP else [(OFFSCREEN, OFFSCREEN, 0) if hidden else (cx, cy, ci)]
    for k in range(n+1):
        if hidden: verts.append((OFFSCREEN, OFFSCREEN, 0)); continue
        x, y = circle(cx, cy, rx, ry, ANG49[k*step]); verts.append((x, y, co))
    return ('verts', prim, verts)


def ring(cx, cy, rxi, ryi, rxo, ryo, ci, co, n, step, mode, hidden):
    """Inner/outer vertex pairs; mode 1 colours both by the side of the circle (ci left, co right)."""
    verts = []
    for k in range(n+1):
        if hidden: verts += _hidden_verts(2); continue
        a = ANG49[k*step]
        if mode: ci_, co_ = (ci, ci) if SIN8[(a+64) & 255] < 0 else (co, co)
        else: ci_, co_ = ci, co
        verts.append(circle(cx, cy, rxi, ryi, a)+(ci_,)); verts.append(circle(cx, cy, rxo, ryo, a)+(co_,))
    return ('verts', STRIP, verts)


# ---- decoder -------------------------------------------------------------------------------------------
def _xy(word):
    return (word & 0xFFFF)//16-ORIGIN[0], ((word >> 16) & 0xFFFF)//16-ORIGIN[1]


def decode(block):
    """The guest block back as model() items; every tag and pad is checked."""
    out = []; pos = 0; block = bytes(block)
    while pos < len(block):
        tag, regs = struct.unpack_from('<2Q', block, pos)
        assert tag == 0x8001 | (1 << 60) and regs == 0xE, f'A+D tag at {pos}'
        value, register = struct.unpack_from('<2Q', block, pos+16); pos += 32
        if register != 0: out.append(('ad', register, value)); continue
        prim = value
        tag, regs = struct.unpack_from('<2Q', block, pos); pos += 16
        nloop, eop, flg, nreg = tag & 0x7FFF, tag >> 15 & 1, tag >> 58 & 3, tag >> 60
        assert eop == 1 and flg == 1 and tag & ~(0x7FFF | 1 << 15 | 3 << 58 | 15 << 60) == 0, f'REGLIST tag at {pos-16}'
        if regs == 0x51 and nreg == 2:
            verts = []
            for i in range(nloop):
                col, xyz = struct.unpack_from('<2Q', block, pos); pos += 16
                assert col >> 32 == Q_ONE and xyz >> 32 == 0
                verts.append(_xy(xyz)+(col & 0xFFFFFFFF,))
            out.append(('verts', prim, verts))
        elif regs == 0x551 and nreg == 3:
            items = []
            for i in range(nloop):
                col, a, b = struct.unpack_from('<3Q', block, pos); pos += 24
                assert col >> 32 == Q_ONE and a >> 32 == 0 and b >> 32 == 0
                items.append((col & 0xFFFFFFFF,)+_xy(a)+_xy(b))
            if nloop & 1: assert block[pos:pos+8] == bytes(8), 'pad qword'; pos += 8
            out.append(('sprite', prim, items))
        elif regs == 0x53531 and nreg == 5:
            items = []
            for i in range(nloop):
                col, uv0, a, uv1, b = struct.unpack_from('<5Q', block, pos); pos += 40
                assert col >> 32 == Q_ONE and a >> 32 == 0 and b >> 32 == 0 and uv0 >> 32 == 0 and uv1 >> 32 == 0
                items.append((col & 0xFFFFFFFF, uv0 & 0xFFFF, uv0 >> 16, *_xy(a), uv1 & 0xFFFF, uv1 >> 16, *_xy(b)))
            if nloop & 1: assert block[pos:pos+8] == bytes(8), 'pad qword'; pos += 8
            out.append(('tsprite', prim, items))
        else: raise AssertionError(f'unknown REGLIST {regs:#x}/{nreg}')
    assert pos == len(block)
    return out


# ---- guest piece -------------------------------------------------------------------------------------------
def code():
    from prototype import Assembler
    from guest_loading_screen import SUB
    import loading_protocol as protocol
    S = SCRATCH; sub = SUB()
    a = Assembler(CODE)
    ZERO, V0, V1, A0, A1, A2, A3 = 0, 2, 3, 4, 5, 6, 7
    T0, T1, T2, T3, T4, T5, T6, T7, T8, T9 = 8, 9, 10, 11, 12, 13, 14, 15, 24, 25
    S0, S2, S4, S5, S6, S7, SP, RA = 16, 18, 20, 21, 22, 23, 29, 31
    tables = {}

    def mult(rd, rs, rt): a.r(24, rd, rs, rt)          # EE three-operand mult: rd = lo
    def sll(rd, rt, n): a.r(0, rd, 0, rt, n)
    def srl(rd, rt, n): a.r(2, rd, 0, rt, n)
    def sra(rd, rt, n): a.r(3, rd, 0, rt, n)
    def addu(rd, rs, rt): a.r(0x21, rd, rs, rt)
    def subu(rd, rs, rt): a.r(0x23, rd, rs, rt)
    def or_(rd, rs, rt): a.r(0x25, rd, rs, rt)
    def and_(rd, rs, rt): a.r(0x24, rd, rs, rt)
    def slt(rd, rs, rt): a.r(0x2A, rd, rs, rt)
    def sltu(rd, rs, rt): a.r(0x2B, rd, rs, rt)
    def lbu(rt, rs, off=0): a.i(36, rt, rs, off)
    def lb(rt, rs, off=0): a.i(32, rt, rs, off)
    def lhu(rt, rs, off=0): a.i(37, rt, rs, off)
    def sc(rt, name): a.sw(rt, SP, S[name])
    def lc(rt, name): a.lw(rt, SP, S[name])
    def sin(rd, angle, tmp=None):
        """rd = sin8[angle & 255] (s6 = table base); angle may be rd."""
        a.i(12, rd, angle, 255); addu(rd, rd, S6); lb(rd, rd)
    def table(rt, name, index, loader=lbu, tmp=None):
        """rt = name[index] (byte or halfword table in the piece); rt may equal index."""
        tmp = (T1 if index == T0 else T0) if tmp is None else tmp
        a.fixups.append((len(a.words), 'tbl_'+name, 'lui')); a.emit(15 << 26 | tmp << 16)
        a.fixups.append((len(a.words), 'tbl_'+name, 'ori')); a.emit(13 << 26 | tmp << 21 | tmp << 16)
        if loader is lhu: sll(index, index, 1)
        addu(tmp, tmp, index); loader(rt, tmp)
    def call(label): a.jump(label, True)
    def offv():
        a.addiu(A0, ZERO, OFFSCREEN); a.addiu(A1, ZERO, OFFSCREEN); a.move(A2, ZERO); a.call(sub['vertex'])
    def ad(reg, value):
        a.addiu(A0, ZERO, reg); a.li(A1, value & 0xFFFFFFFF); a.li(A2, value >> 32); call('ad')
    def prim(word): a.addiu(A0, ZERO, word); a.call(sub['prim'])
    def tag2(n): a.addiu(A0, ZERO, n); call('tag2')
    def set_alpha(rd, color, alpha, tmp=None):
        """rd = (color & 0xFFFFFF) | alpha << 24; the scratch must outlive rd's own write."""
        tmp = (T1 if rd == T0 else T0) if tmp is None else tmp
        assert tmp not in (rd, color, alpha), 'set_alpha scratch collides with an operand'
        a.li(tmp, 0xFFFFFF); and_(rd, color, tmp); sll(tmp, alpha, 24); or_(rd, rd, tmp)
    def bytes_table(name, values, half=False):
        tables[name] = (bytes(values) if not half else b''.join(struct.pack('<H', v) for v in values))

    # ---- entry ----------------------------------------------------------------------------------------------
    a.fixups.append((len(a.words), 'tbl_SIN8', 'lui')); a.emit(15 << 26 | S6 << 16)
    a.fixups.append((len(a.words), 'tbl_SIN8', 'ori')); a.emit(13 << 26 | S6 << 21 | S6 << 16)
    ad(ALPHA_1, STANDARD)
    # fade: one flat sprite (RGBAQ, XYZ2, XYZ2 + pad)
    prim(SPRITE)
    a.li(T0, 0x8001); a.sw(T0, S7, 0); a.li(T0, 0x34000000); a.sw(T0, S7, 4); a.li(T0, 0x551); a.sw(T0, S7, 8); a.sw(ZERO, S7, 12)
    a.addiu(S7, S7, 16)
    a.lw(T0, S4, protocol.FLAGS); a.i(12, T0, T0, protocol.FLAG_FADE); a.branch(4, T0, ZERO, 'fade_hidden')
    a.i(11, T0, S5, 24); a.branch(4, T0, ZERO, 'fade_hidden')
    table(T1, 'FADE25', S5); a.lw(T2, S4, protocol.FADE_COLOR); set_alpha(A2, T2, T1)
    a.li(T0, (ORIGIN[0]*16) | (xyz2_y(0) << 16)); a.li(T1, ((ORIGIN[0]+512)*16) | (xyz2_y(448) << 16)); a.jump('fade_emit')
    a.label('fade_hidden'); a.move(A2, ZERO); a.li(T0, ((ORIGIN[0]+OFFSCREEN)*16) | (xyz2_y(OFFSCREEN) << 16)); a.move(T1, T0)
    a.label('fade_emit')
    a.sw(A2, S7, 0); a.li(T2, Q_ONE); a.sw(T2, S7, 4); a.sw(T0, S7, 8); a.sw(ZERO, S7, 12); a.sw(T1, S7, 16); a.sw(ZERO, S7, 20)
    a.sw(ZERO, S7, 24); a.sw(ZERO, S7, 28); a.addiu(S7, S7, 32)
    ad(ALPHA_1, ADDITIVE)

    # ---- ribbons: t8 = ribbon, t7 = strip, t6 = cross-section, t9 = visible ---------------------------------------
    a.move(T8, ZERO)
    a.label('rb_loop')
    sll(S2, T8, 7); sll(T0, T8, 4); addu(S2, S2, T0); a.addiu(S2, S2, protocol.RIBBONS); addu(S2, S2, S4)
    a.lw(T0, S4, protocol.FLAGS); a.i(12, T0, T0, protocol.FLAG_RIBBONS); a.lw(T1, S4, protocol.N_RIBBONS); sltu(T9, T8, T1)
    a.branch(5, T0, ZERO, 'rb_flag_ok'); a.move(T9, ZERO)
    a.label('rb_flag_ok'); a.move(T7, ZERO)
    a.label('rb_strip')
    prim(STRIP); tag2(2*N_XSECT); a.move(T6, ZERO)
    a.label('rb_xsect')
    a.branch(5, T9, ZERO, 'rb_visible'); offv(); offv(); a.jump('rb_next')
    a.label('rb_visible')
    sll(A0, T6, 4); call('xsect')
    for delta in (-2, -1):
        a.addiu(T2, T7, delta); lc(T0, 'HW'); mult(T0, T0, T2); sra(T0, T0, 1); lc(A0, 'X'); addu(A0, A0, T0); lc(A1, 'Y')
        mult(T3, T2, T2); lc(A2, 'C'); a.branch(4, T3, ZERO, f'rb_col{delta}')
        a.addiu(T4, ZERO, 1); a.branch(5, T3, T4, f'rb_black{delta}')
        a.li(T4, 0xFEFEFE); and_(A2, A2, T4); srl(A2, A2, 1); a.i(15, T4, 0, 0x8000); or_(A2, A2, T4); a.jump(f'rb_col{delta}')
        a.label(f'rb_black{delta}'); a.move(A2, ZERO)
        a.label(f'rb_col{delta}'); a.call(sub['vertex'])
    a.label('rb_next'); a.addiu(T6, T6, 1); a.addiu(T0, ZERO, N_XSECT); a.branch(5, T6, T0, 'rb_xsect')
    a.addiu(T7, T7, 1); a.addiu(T0, ZERO, N_STRIPS); a.branch(5, T7, T0, 'rb_strip')
    a.addiu(T8, T8, 1); a.addiu(T0, ZERO, N_RIBBONS); a.branch(5, T8, T0, 'rb_loop')

    # ---- sparks: t8 = index, t9 = entry pointer ----------------------------------------------------------------------
    ad(TEX0_1, protocol.ATLAS_TEX0); ad(TEX1_1, protocol.NEAREST_TEX1); ad(CLAMP_1, protocol.CLAMP_BOTH)
    prim(TSPRITE)
    a.li(T0, 0x8000 | N_SPARKS); a.sw(T0, S7, 0); a.li(T0, 0x54000000); a.sw(T0, S7, 4); a.li(T0, 0x53531); a.sw(T0, S7, 8); a.sw(ZERO, S7, 12)
    a.addiu(S7, S7, 16)
    a.move(T8, ZERO); a.addiu(T9, S4, protocol.SPARK_ENTRIES)
    a.label('sp_loop')
    a.lw(T0, S4, protocol.FLAGS); a.i(12, T0, T0, protocol.FLAG_RIBBONS); a.branch(4, T0, ZERO, 'sp_hidden')
    a.lw(T0, T9, 0); a.i(12, T1, T0, 255); a.lw(T2, S4, protocol.N_RIBBONS); sltu(T2, T1, T2); a.branch(4, T2, ZERO, 'sp_hidden')
    sll(S2, T1, 7); sll(T2, T1, 4); addu(S2, S2, T2); a.addiu(S2, S2, protocol.RIBBONS); addu(S2, S2, S4)
    srl(T1, T0, 16); a.i(12, T1, T1, 255); mult(T1, T1, S5); srl(T2, T0, 8); a.i(12, T2, T2, 255); sll(T2, T2, 2); addu(T1, T1, T2)
    a.i(12, T1, T1, 511); sc(T1, 'T0'); srl(A0, T1, 1); call('xsect')
    # x wobble and side offset
    a.lw(T0, T9, 0); srl(T1, T0, 24); sll(T1, T1, 1); a.addiu(T2, ZERO, 11); mult(T2, T2, S5); srl(T2, T2, 3); addu(T1, T1, T2)
    sin(T1, T1); a.addiu(T2, ZERO, 3); mult(T1, T1, T2); sra(T1, T1, 7); lc(T3, 'X'); addu(T3, T3, T1)
    a.lw(T0, T9, 4); srl(T1, T0, 16); a.i(12, T1, T1, 255); srl(T2, T1, 4); a.addiu(T2, T2, -8); lc(T4, 'HW'); mult(T2, T2, T4); sra(T2, T2, 3)
    addu(T3, T3, T2)                                                   # t3 = x
    lc(T4, 'Y')                                                        # t4 = y
    a.lw(T2, S2, 0); a.i(12, T2, T2, 1); sll(T2, T2, 4); addu(T2, T2, S4)
    a.lw(T5, T2, protocol.SPARK_REGIONS); slt(T5, T3, T5); a.branch(5, T5, ZERO, 'sp_hidden')
    a.lw(T5, T2, protocol.SPARK_REGIONS+8); slt(T5, T3, T5); a.branch(4, T5, ZERO, 'sp_hidden')
    a.lw(T5, T2, protocol.SPARK_REGIONS+4); slt(T5, T4, T5); a.branch(5, T5, ZERO, 'sp_hidden')
    a.lw(T5, T2, protocol.SPARK_REGIONS+12); slt(T5, T4, T5); a.branch(4, T5, ZERO, 'sp_hidden')
    # alpha
    a.addiu(T2, ZERO, 9); mult(T2, T2, S5); addu(T2, T2, T1); sin(T2, T2); a.addiu(T5, ZERO, 51); mult(T2, T2, T5); sra(T2, T2, 7); a.addiu(T2, T2, 77)
    lc(T5, 'T0'); srl(T5, T5, 5); table(T5, 'END16', T5); mult(T2, T2, T5); srl(T2, T2, 7); lc(T5, 'RAMP'); mult(T2, T2, T5); srl(T2, T2, 8)
    a.lw(T5, S2, protocol.RIBBON_COLORS+32); a.li(T1, 0xFEFEFE); and_(T5, T5, T1); srl(T5, T5, 1); a.li(T1, 0x808080); addu(T5, T5, T1)
    sll(T2, T2, 24); or_(T5, T5, T2)                                   # t5 = rgbaq low
    # box and uv (the alpha block's table() lookups use t0 as their address scratch)
    a.lw(T0, T9, 4)
    a.i(12, T1, T0, 255); srl(T2, T0, 8); a.i(12, T2, T2, 255); a.branch(4, T2, ZERO, 'sp_dot')
    a.addiu(T6, T1, -1); sll(T7, T1, 1); addu(T7, T7, T1)
    a.li(T0, (ATLAS_STREAK[0]*16) | ((ATLAS_STREAK[1]*16) << 16)); a.li(T2, ((ATLAS_STREAK[0]+ATLAS_STREAK[2])*16) | (((ATLAS_STREAK[1]+ATLAS_STREAK[3])*16) << 16))
    a.jump('sp_box')
    a.label('sp_dot'); a.addiu(T6, T1, 2); a.move(T7, T6)
    a.li(T0, (ATLAS_DOT[0]*16) | ((ATLAS_DOT[1]*16) << 16)); a.li(T2, ((ATLAS_DOT[0]+ATLAS_DOT[2])*16) | (((ATLAS_DOT[1]+ATLAS_DOT[3])*16) << 16))
    a.label('sp_box')
    srl(T1, T6, 1); subu(T3, T3, T1); srl(T1, T7, 1); subu(T4, T4, T1)   # x0, y0
    a.sw(T5, S7, 0); a.li(T1, Q_ONE); a.sw(T1, S7, 4); a.sw(T0, S7, 8); a.sw(ZERO, S7, 12); a.sw(T2, S7, 24); a.sw(ZERO, S7, 28)
    a.addiu(T1, T3, ORIGIN[0]); sll(T1, T1, 4); emit_window_y(a, T2, T4, 20); or_(T1, T1, T2); a.sw(T1, S7, 16); a.sw(ZERO, S7, 20)
    addu(T3, T3, T6); addu(T4, T4, T7)
    a.addiu(T1, T3, ORIGIN[0]); sll(T1, T1, 4); emit_window_y(a, T2, T4, 20); or_(T1, T1, T2); a.sw(T1, S7, 32); a.sw(ZERO, S7, 36)
    a.jump('sp_next')
    a.label('sp_hidden')
    a.li(T1, ((ORIGIN[0]+OFFSCREEN)*16) | (xyz2_y(OFFSCREEN) << 16))
    a.sw(ZERO, S7, 0); a.li(T2, Q_ONE); a.sw(T2, S7, 4); a.sw(ZERO, S7, 8); a.sw(ZERO, S7, 12); a.sw(T1, S7, 16); a.sw(ZERO, S7, 20)
    a.sw(ZERO, S7, 24); a.sw(ZERO, S7, 28); a.sw(T1, S7, 32); a.sw(ZERO, S7, 36)
    a.label('sp_next'); a.addiu(S7, S7, 40); a.addiu(T9, T9, 8); a.addiu(T8, T8, 1); a.addiu(T0, ZERO, N_SPARKS); a.branch(5, T8, T0, 'sp_loop')

    # ---- orbs: t8 = orb index; s2 = orb base ---------------------------------------------------------------------------
    a.lw(T0, S4, protocol.FLAGS); a.i(12, T0, T0, protocol.FLAG_STORM); sltu(T0, ZERO, T0); a.i(14, T0, T0, 1); sc(T0, 'T2')   # T2 = storm hidden
    a.move(T8, ZERO)
    a.label('orb_loop')
    a.addiu(S2, T8, 0); sll(S2, S2, 3); sll(T0, T8, 5); addu(S2, S2, T0); a.addiu(S2, S2, protocol.ORBS); addu(S2, S2, S4)
    O = {n: 4*i for i, n in enumerate(protocol.ORB_WORDS)}
    a.lw(T0, S2, O['cx']); sc(T0, 'CX'); a.lw(T1, S2, O['cy']); a.lw(T2, S2, O['rx']); a.lw(T3, S2, O['ry'])
    a.i(11, T0, S5, FIRST); a.branch(4, T0, ZERO, 'orb_settled')
    a.lw(T4, S2, O['flight_y']); subu(T1, T1, T4); table(T5, 'EIN54', S5); mult(T1, T1, T5); sra(T1, T1, 8); addu(T1, T1, T4)
    a.addiu(T5, ZERO, 113); mult(T2, T2, T5); sra(T2, T2, 7); a.addiu(T5, ZERO, 154); mult(T3, T3, T5); sra(T3, T3, 7)
    a.addiu(T5, ZERO, 455); mult(T4, S5, T5); srl(T4, T4, 6); a.i(11, T5, T4, 128); a.branch(5, T5, ZERO, 'orb_alpha_ok'); a.addiu(T4, ZERO, 128)
    a.label('orb_alpha_ok'); a.addiu(T5, ZERO, 1); sc(T5, 'T1'); a.jump('orb_shape')
    a.label('orb_settled')
    a.lw(T4, S0, 44); a.addiu(T5, ZERO, 13); mult(T5, T4, T5); srl(T5, T5, 7); a.addiu(T5, T5, 128); mult(T2, T2, T5); sra(T2, T2, 7); mult(T3, T3, T5); sra(T3, T3, 7)
    a.i(11, T5, T4, 21); a.branch(4, T5, ZERO, 'orb_no_squash')
    table(T5, 'EASE21', T4); a.addiu(T6, ZERO, 255); subu(T5, T6, T5)
    sll(T6, T5, 5); srl(T6, T6, 8); a.addiu(T6, T6, 128); mult(T2, T2, T6); sra(T2, T2, 7)
    a.addiu(T6, ZERO, 23); mult(T6, T6, T5); srl(T6, T6, 8); a.addiu(T7, ZERO, 128); subu(T6, T7, T6); mult(T3, T3, T6); sra(T3, T3, 7)
    a.label('orb_no_squash'); a.addiu(T4, ZERO, 128); sc(ZERO, 'T1')
    a.label('orb_shape')                                                # t1 = cy, t2 = rx, t3 = ry, t4 = alpha, T1 = flight
    sc(T1, 'CY'); sc(T2, 'X'); sc(T3, 'Y'); sc(T4, 'T0')
    # halo fan to 2 r
    sll(T5, T2, 1); sc(T5, 'RXO'); sll(T5, T3, 1); sc(T5, 'RYO')
    a.lw(T5, S2, O['halo']); a.addiu(T6, ZERO, 0x60); set_alpha(T7, T5, T6); sc(T7, 'CI'); set_alpha(T7, T5, ZERO); sc(T7, 'CO')
    lc(T5, 'T2'); lc(T6, 'T1'); or_(T5, T5, T6); sc(T5, 'HIDDEN'); a.addiu(T5, ZERO, 24); sc(T5, 'N'); a.addiu(T5, ZERO, 2); sc(T5, 'STEP')
    a.addiu(T5, ZERO, FAN); sc(T5, 'MODE'); call('fan')
    # body fan to 0.7 r
    lc(T2, 'X'); a.addiu(T5, ZERO, 90); mult(T2, T2, T5); sra(T2, T2, 7); sc(T2, 'RXO'); sc(T2, 'RXI'); lc(T3, 'Y'); mult(T3, T3, T5); sra(T3, T3, 7); sc(T3, 'RYO'); sc(T3, 'RYI')
    lc(T4, 'T0'); a.lw(T5, S2, O['core']); set_alpha(T7, T5, T4); sc(T7, 'CI'); a.lw(T5, S2, O['team']); set_alpha(T7, T5, T4); sc(T7, 'CO')
    lc(T5, 'T2'); sc(T5, 'HIDDEN'); call('fan')
    # body ring 0.7 r -> r
    lc(T2, 'X'); sc(T2, 'RXO'); lc(T3, 'Y'); sc(T3, 'RYO')
    lc(T4, 'T0'); a.lw(T5, S2, O['team']); set_alpha(T7, T5, T4); sc(T7, 'CI'); srl(T4, T4, 2); a.lw(T5, S2, O['deep']); set_alpha(T7, T5, T4); sc(T7, 'CO')
    sc(ZERO, 'MODE'); call('ring')
    a.addiu(T8, T8, 1); a.addiu(T0, ZERO, 2); a.branch(5, T8, T0, 'orb_loop')

    # ---- seam and flash --------------------------------------------------------------------------------------------------
    a.i(11, T0, S5, FIRST); lc(T1, 'T2'); or_(T0, T0, T1); sc(T0, 'T1')   # T1 = not settled
    SE = {n: protocol.SEAM+4*i for i, n in enumerate(protocol.SEAM_WORDS)}
    a.lw(T0, S4, SE['cx']); sc(T0, 'CX'); a.lw(T0, S4, SE['cy']); sc(T0, 'CY'); a.lw(T0, S4, SE['rx']); sc(T0, 'RXO'); a.lw(T0, S4, SE['ry']); sc(T0, 'RYO')
    a.lw(T4, S0, 44); a.addiu(T5, ZERO, 43); mult(T4, T4, T5); srl(T4, T4, 7); a.addiu(T4, T4, 0x40)
    a.lw(T5, S4, SE['color']); set_alpha(T7, T5, T4); sc(T7, 'CI'); a.lw(T5, S4, SE['edge']); set_alpha(T7, T5, ZERO); sc(T7, 'CO')
    lc(T0, 'T1'); sc(T0, 'HIDDEN'); a.addiu(T5, ZERO, 12); sc(T5, 'N'); a.addiu(T5, ZERO, 4); sc(T5, 'STEP'); a.addiu(T5, ZERO, FAN); sc(T5, 'MODE'); call('fan')
    FL = {n: protocol.FLASH+4*i for i, n in enumerate(protocol.FLASH_WORDS)}
    a.lw(T0, S4, FL['cx']); sc(T0, 'CX'); a.lw(T0, S4, FL['cy']); sc(T0, 'CY'); a.lw(T0, S4, FL['rx']); sc(T0, 'RXO'); a.lw(T0, S4, FL['ry']); sc(T0, 'RYO')
    a.addiu(T4, S5, -FIRST); a.i(11, T5, T4, 18); a.i(14, T5, T5, 1); lc(T0, 'T1'); or_(T5, T5, T0); sc(T5, 'HIDDEN')
    a.branch(5, T5, ZERO, 'flash_dim'); table(T4, 'FLASH18', T4); a.jump('flash_col')
    a.label('flash_dim'); a.move(T4, ZERO)
    a.label('flash_col'); a.lw(T5, S4, FL['color']); set_alpha(T7, T5, T4); sc(T7, 'CI'); a.lw(T5, S4, FL['edge']); set_alpha(T7, T5, ZERO); sc(T7, 'CO')
    a.addiu(T5, ZERO, 24); sc(T5, 'N'); a.addiu(T5, ZERO, 2); sc(T5, 'STEP'); call('fan')

    # ---- shockwave ring ----------------------------------------------------------------------------------------------------
    RG = {n: protocol.RING+4*i for i, n in enumerate(protocol.RING_WORDS)}
    a.addiu(T4, S5, -FIRST); a.li(T0, MAGIC[CYCLE][0]); a.r(25, 0, T4, T0); a.r(16, T1, 0, 0); srl(T1, T1, MAGIC[CYCLE][1])
    a.addiu(T0, ZERO, CYCLE); mult(T1, T1, T0); subu(T4, T4, T1)         # t4 = age
    a.i(11, T5, T4, RING_LIFE); a.i(14, T5, T5, 1); lc(T0, 'T1'); or_(T5, T5, T0); sc(T5, 'HIDDEN')
    a.addiu(T5, ZERO, 48); sc(T5, 'N'); a.addiu(T5, ZERO, 1); sc(T5, 'STEP'); sc(T5, 'MODE')
    lc(T5, 'HIDDEN'); a.branch(5, T5, ZERO, 'ring_hidden')
    a.lw(T0, S4, RG['cx']); sc(T0, 'CX'); a.lw(T0, S4, RG['cy']); sc(T0, 'CY')
    a.move(T5, T4); table(T6, 'RING_R', T5, lhu)                          # t6 = R (t5 = 2*age)
    a.addiu(T0, S5, -FIRST); a.i(11, T0, T0, CYCLE); a.branch(4, T0, ZERO, 'ring_later'); table(T7, 'RING_W14', T4); a.jump('ring_width')
    a.label('ring_later'); table(T7, 'RING_W8', T4)
    a.label('ring_width'); srl(T0, T7, 1); subu(T2, T6, T0); addu(T3, T2, T7)   # t2 = rin, t3 = rout
    for src, rx, ry in ((T2, 'RXI', 'RYI'), (T3, 'RXO', 'RYO'), (T6, 'X', 'Y')):
        a.addiu(T0, ZERO, 205); mult(T0, src, T0); srl(T0, T0, 8); sc(T0, rx); a.addiu(T0, ZERO, 239); mult(T0, src, T0); srl(T0, T0, 8); sc(T0, ry)
    table(T7, 'RING_A', T4); sc(T7, 'T0')
    a.lw(T5, S4, RG['left']); set_alpha(T0, T5, T7); sc(T0, 'CI'); a.lw(T5, S4, RG['right']); set_alpha(T0, T5, T7); sc(T0, 'CO')
    a.label('ring_hidden'); call('ring')
    # inner 1 px line strip at R
    lc(T0, 'X'); sc(T0, 'RXO'); lc(T0, 'Y'); sc(T0, 'RYO'); lc(T7, 'T0'); a.lw(T5, S4, RG['inner']); set_alpha(T0, T5, T7); sc(T0, 'CO')
    a.addiu(T5, ZERO, LINE_STRIP); sc(T5, 'MODE'); call('fan')

    # ---- bolts: t8 = bolt, t9 = strip, s2 = bolt base ------------------------------------------------------------------------
    B = {n: 4*i for i, n in enumerate(protocol.BOLT_WORDS)}
    a.move(T8, ZERO)
    a.label('bolt_loop')
    sll(S2, T8, 3); sll(T0, T8, 5); addu(S2, S2, T0); a.addiu(S2, S2, protocol.BOLTS); addu(S2, S2, S4)
    a.addiu(T0, ZERO, 37); mult(T0, T0, T8); addu(T0, T0, S5)              # n
    a.lw(T1, S2, B['period']); and_(T1, T0, T1)                             # life
    subu(T2, T0, T1); srl(T2, T2, 6)                                        # burst
    a.lw(T3, S2, B['duration']); sltu(T3, T1, T3); a.i(14, T3, T3, 1); lc(T4, 'T1'); or_(T3, T3, T4)
    a.i(12, T4, T2, 127); addu(T4, T4, S4); lbu(T4, T4, protocol.NOISE); a.i(11, T4, T4, 112); or_(T3, T3, T4); sc(T3, 'HIDDEN')
    a.addiu(T4, ZERO, 7); mult(T4, T4, T2); srl(T5, T1, 2); a.addiu(T6, ZERO, 5); mult(T5, T5, T6); addu(T4, T4, T5); a.addiu(T4, T4, 64); sc(T4, 'T0')   # base
    a.i(11, T5, T1, 8); a.branch(5, T5, ZERO, 'bolt_idx'); a.addiu(T5, ZERO, 7); a.jump('bolt_tbl')
    a.label('bolt_idx'); a.move(T5, T1)
    a.label('bolt_tbl'); table(T5, 'BOLT8', T5); a.branch(4, T3, ZERO, 'bolt_alpha'); a.move(T5, ZERO)
    a.label('bolt_alpha'); sc(T5, 'CX'); a.addiu(T6, ZERO, 38); mult(T6, T5, T6); srl(T6, T6, 7); sc(T6, 'CY')
    a.move(T9, ZERO)
    a.label('bolt_strip')
    prim(LINE_STRIP); tag2(9)
    a.addiu(T0, ZERO, 2); a.branch(4, T9, T0, 'bolt_core'); a.lw(T5, S2, B['glow']); lc(T6, 'CY'); set_alpha(T5, T5, T6); a.jump('bolt_colour')
    a.label('bolt_core'); a.lw(T5, S2, B['color']); lc(T6, 'CX'); set_alpha(T5, T5, T6)
    a.label('bolt_colour'); sc(T5, 'CI'); a.move(T7, ZERO)                # t7 = point i
    a.label('bolt_point')
    lc(T0, 'HIDDEN'); a.branch(4, T0, ZERO, 'bolt_shown'); offv(); a.jump('bolt_pnext')
    a.label('bolt_shown')
    a.lw(T0, S2, B['x0']); a.lw(T1, S2, B['x1']); subu(T1, T1, T0); mult(T1, T1, T7); sra(T1, T1, 3); addu(A0, T0, T1)
    a.lw(T0, S2, B['y0']); a.lw(T1, S2, B['y1']); subu(T1, T1, T0); mult(T1, T1, T7); sra(T1, T1, 3); addu(A1, T0, T1)
    sll(T1, T7, 4); sin(T1, T1); a.lw(T2, S2, B['bulge']); mult(T1, T1, T2); sra(T1, T1, 7); addu(A1, A1, T1)
    lc(A2, 'CI'); a.addiu(T0, T7, -1); a.i(11, T0, T0, 7); a.branch(4, T0, ZERO, 'bolt_end')
    a.addiu(T0, ZERO, 11); mult(T0, T0, T7); lc(T1, 'T0'); addu(T0, T0, T1)
    a.i(12, T1, T0, 127); addu(T1, T1, S4); lbu(T1, T1, protocol.NOISE); srl(T1, T1, 4); a.addiu(T1, T1, -8); addu(A0, A0, T1)
    a.addiu(T0, T0, 5); a.i(12, T1, T0, 127); addu(T1, T1, S4); lbu(T1, T1, protocol.NOISE); srl(T1, T1, 4); a.addiu(T1, T1, -8); addu(A1, A1, T1)
    a.jump('bolt_dy')
    a.label('bolt_end'); set_alpha(A2, A2, ZERO)
    a.label('bolt_dy')
    a.branch(4, T9, ZERO, 'bolt_plus'); a.addiu(T0, ZERO, 1); a.branch(4, T9, T0, 'bolt_minus'); a.jump('bolt_emit')
    a.label('bolt_plus'); a.addiu(A1, A1, 1); a.jump('bolt_emit')
    a.label('bolt_minus'); a.addiu(A1, A1, -1)
    a.label('bolt_emit'); a.call(sub['vertex'])
    a.label('bolt_pnext'); a.addiu(T7, T7, 1); a.addiu(T0, ZERO, 9); a.branch(5, T7, T0, 'bolt_point')
    a.addiu(T9, T9, 1); a.addiu(T0, ZERO, 3); a.branch(5, T9, T0, 'bolt_strip')
    a.addiu(T8, T8, 1); a.addiu(T0, ZERO, 2); a.branch(5, T8, T0, 'bolt_loop')

    # ---- chevrons: t8 = k, t9 = sign flag ------------------------------------------------------------------------------------
    CH = {n: protocol.CHEVRONS+4*i for i, n in enumerate(protocol.CHEVRON_WORDS)}
    a.lw(T0, S4, CH['count']); sltu(T0, ZERO, T0); a.i(14, T0, T0, 1); lc(T1, 'T1'); or_(T0, T0, T1); sc(T0, 'HIDDEN')
    a.move(T8, ZERO)
    a.label('chev_loop')
    a.lw(T0, S4, CH['stagger']); mult(T0, T0, T8); a.addiu(T1, S5, 200); subu(T0, T1, T0)
    a.li(T1, MAGIC[50][0]); a.r(25, 0, T0, T1); a.r(16, T1, 0, 0); srl(T1, T1, MAGIC[50][1]); a.addiu(T2, ZERO, 50); mult(T1, T1, T2); subu(T0, T0, T1)   # t0 = t
    a.lw(T2, S4, CH['pitch']); mult(T1, T0, T2); a.li(T3, MAGIC[50][0]); a.r(25, 0, T1, T3); a.r(16, T1, 0, 0); srl(T1, T1, MAGIC[50][1])   # q
    mult(T3, T2, T8); a.lw(T4, S4, CH['offset']); addu(T3, T3, T4); subu(T3, T3, T1); sc(T3, 'T0')     # dy
    table(T4, 'CHEV50', T0); a.i(12, T5, T8, 1); a.branch(4, T5, ZERO, 'chev_c0'); a.lw(T5, S4, CH['color1']); a.jump('chev_col')
    a.label('chev_c0'); a.lw(T5, S4, CH['color0'])
    a.label('chev_col'); set_alpha(T5, T5, T4); sc(T5, 'CI')
    a.move(T9, ZERO)
    a.label('chev_strip')
    prim(LINE_STRIP); tag2(3)
    lc(T0, 'HIDDEN'); a.branch(4, T0, ZERO, 'chev_shown'); offv(); offv(); offv(); a.jump('chev_next')
    a.label('chev_shown')
    a.lw(T6, S4, CH['cy']); lc(T3, 'T0'); a.branch(4, T9, ZERO, 'chev_above'); addu(T6, T6, T3); a.addiu(T7, ZERO, 5); a.jump('chev_pts')
    a.label('chev_above'); subu(T6, T6, T3); a.addiu(T7, ZERO, -5)
    a.label('chev_pts')                                                      # t6 = y, t7 = arm offset
    a.lw(A0, S4, CH['cx']); a.addiu(A0, A0, -7); addu(A1, T6, T7); lc(A2, 'CI'); a.call(sub['vertex'])
    a.lw(A0, S4, CH['cx']); a.move(A1, T6); lc(A2, 'CI'); a.call(sub['vertex'])
    a.lw(A0, S4, CH['cx']); a.addiu(A0, A0, 7); addu(A1, T6, T7); lc(A2, 'CI'); a.call(sub['vertex'])
    a.label('chev_next'); a.addiu(T9, T9, 1); a.addiu(T0, ZERO, 2); a.branch(5, T9, T0, 'chev_strip')
    a.addiu(T8, T8, 1); a.addiu(T0, ZERO, 4); a.branch(5, T8, T0, 'chev_loop')

    ad(ALPHA_1, STANDARD)
    a.lw(T8, SP, protocol.KS_RETURN); a.jr(T8)

    # ---- subroutines ---------------------------------------------------------------------------------------------------------
    # ad: A+D write of register a0 = (a1, a2), 32 bytes.
    a.label('ad'); a.li(T0, 0x8001); a.sw(T0, S7, 0); a.li(T0, 0x10000000); a.sw(T0, S7, 4); a.addiu(T0, ZERO, 0xE); a.sw(T0, S7, 8); a.sw(ZERO, S7, 12)
    a.sw(A1, S7, 16); a.sw(A2, S7, 20); a.sw(A0, S7, 24); a.sw(ZERO, S7, 28); a.addiu(S7, S7, 32); a.jr()
    # tag2: REGLIST tag RGBAQ/XYZ2 for a0 vertices, EOP.
    a.label('tag2'); a.i(13, T0, A0, 0x8000); a.sw(T0, S7, 0); a.li(T0, 0x24000000); a.sw(T0, S7, 4); a.addiu(T0, ZERO, 0x51); a.sw(T0, S7, 8); a.sw(ZERO, S7, 12)
    a.addiu(S7, S7, 16); a.jr()
    # xsect: a0 = i16, s2 = ribbon base -> X, Y, HW, C, RAMP (scratch); clobbers t0..t5.
    R = {n: 4*i for i, n in enumerate(protocol.RIBBON_WORDS)}
    a.label('xsect')
    a.lw(T0, S2, R['fade_start']); subu(T1, S5, T0); sltu(T2, S5, T0); a.branch(5, T2, ZERO, 'xs_ramp0')
    a.i(11, T2, T1, 54); a.branch(5, T2, ZERO, 'xs_ramp_tbl'); a.addiu(T1, ZERO, 255); a.jump('xs_ramp')
    a.label('xs_ramp_tbl'); table(T1, 'RAMP54', T1); a.jump('xs_ramp')
    a.label('xs_ramp0'); a.move(T1, ZERO)
    a.label('xs_ramp'); sc(T1, 'RAMP')
    a.lw(T0, S2, R['x0']); a.lw(T1, S2, R['x1']); subu(T1, T1, T0); mult(T1, T1, A0); sra(T1, T1, 8); addu(V0, T0, T1)
    a.lw(T2, S2, R['f1']); mult(T2, T2, A0); a.lw(T3, S2, R['w1']); mult(T3, T3, S5); srl(T3, T3, 3); addu(T2, T2, T3); a.lw(T3, S2, R['p1']); addu(T2, T2, T3)
    sin(T2, T2); a.lw(T3, S2, R['A1']); mult(T2, T2, T3)
    a.lw(T3, S2, R['f2']); mult(T3, T3, A0); a.lw(T4, S2, R['w2']); mult(T4, T4, S5); srl(T4, T4, 3); subu(T3, T3, T4); a.lw(T4, S2, R['p2']); addu(T3, T3, T4)
    sin(T3, T3); a.lw(T4, S2, R['A2']); mult(T3, T3, T4); addu(T2, T2, T3); sra(T2, T2, 7); addu(V0, V0, T2); sc(V0, 'X')
    a.lw(T0, S2, R['y0']); a.lw(T1, S2, R['y1']); subu(T1, T1, T0); mult(T1, T1, A0); sra(T1, T1, 8); addu(V1, T0, T1); sc(V1, 'Y')
    a.lw(T2, S2, R['wf']); mult(T2, T2, A0); srl(T2, T2, 4); sll(T3, S5, 1); addu(T3, T3, S5); srl(T3, T3, 2); addu(T2, T2, T3); a.lw(T3, S2, R['wp']); addu(T2, T2, T3)
    sin(T2, T2); a.addiu(T3, ZERO, 48); mult(T2, T2, T3); sra(T2, T2, 7); a.addiu(T2, T2, 80)
    srl(T3, A0, 4); table(T3, 'BELL17', T3); a.lw(T4, S2, R['W']); mult(T4, T4, T3); mult(T4, T4, T2); srl(T4, T4, 16); sc(T4, 'HW')
    sll(T2, A0, 1); addu(T2, T2, A0); sll(T3, S5, 1); addu(T3, T3, S5); sll(T3, T3, 1); subu(T2, T2, T3); sin(T2, T2); a.addiu(T3, ZERO, 96); mult(T2, T2, T3); sra(T2, T2, 7); a.addiu(T2, T2, 160)
    lc(T3, 'RAMP'); mult(T2, T2, T3); srl(T2, T2, 8)                          # k
    srl(T3, A0, 4); sll(T3, T3, 2); addu(T3, T3, S2); a.lw(T3, T3, protocol.RIBBON_COLORS)
    a.i(12, T4, T3, 255); mult(T4, T4, T2); srl(T4, T4, 8); a.move(T5, T4)
    srl(T4, T3, 8); a.i(12, T4, T4, 255); mult(T4, T4, T2); srl(T4, T4, 8); sll(T4, T4, 8); or_(T5, T5, T4)
    srl(T4, T3, 16); a.i(12, T4, T4, 255); mult(T4, T4, T2); srl(T4, T4, 8); sll(T4, T4, 16); or_(T5, T5, T4)
    a.i(15, T4, 0, 0x8000); or_(T5, T5, T4); sc(T5, 'C'); a.jr()
    # fan: PRIM MODE (0x4D fan with a centre vertex CI, or 0x4A line strip without), N segments at ANG49[k*STEP],
    # rim (RXO, RYO) coloured CO; HIDDEN -> every vertex OFFSCREEN. Clobbers t0..t7.
    a.label('fan'); a.sw(RA, SP, S['RA'])
    lc(A0, 'MODE'); a.call(sub['prim']); lc(A0, 'N'); a.addiu(A0, A0, 1); lc(T0, 'MODE'); a.addiu(T1, ZERO, LINE_STRIP); a.branch(4, T0, T1, 'fan_tag'); a.addiu(A0, A0, 1)
    a.label('fan_tag'); call('tag2'); lc(T0, 'MODE'); a.addiu(T1, ZERO, LINE_STRIP)
    a.branch(4, T0, T1, 'fan_rim'); lc(T2, 'HIDDEN'); a.branch(4, T2, ZERO, 'fan_centre'); offv(); a.jump('fan_rim')
    a.label('fan_centre'); lc(A0, 'CX'); lc(A1, 'CY'); lc(A2, 'CI'); a.call(sub['vertex'])
    a.label('fan_rim'); a.move(T6, ZERO)
    a.label('fan_k')
    lc(T2, 'HIDDEN'); a.branch(4, T2, ZERO, 'fan_point'); offv(); a.jump('fan_next')
    a.label('fan_point'); lc(T7, 'STEP'); mult(T7, T7, T6); table(T7, 'ANG49', T7)
    a.addiu(T2, T7, 64); sin(T2, T2); lc(T3, 'RXO'); mult(T2, T2, T3); sra(T2, T2, 7); lc(A0, 'CX'); addu(A0, A0, T2)
    sin(T2, T7); lc(T3, 'RYO'); mult(T2, T2, T3); sra(T2, T2, 7); lc(A1, 'CY'); addu(A1, A1, T2); lc(A2, 'CO'); a.call(sub['vertex'])
    a.label('fan_next'); a.addiu(T6, T6, 1); lc(T0, 'N'); sltu(T2, T0, T6); a.branch(4, T2, ZERO, 'fan_k')
    a.lw(RA, SP, S['RA']); a.jr()
    # ring: strip of N segments between (RXI, RYI) and (RXO, RYO); MODE 0: inner CI, outer CO; MODE 1: both CI where cos < 0 else CO.
    a.label('ring'); a.sw(RA, SP, S['RA'])
    prim(STRIP); lc(A0, 'N'); a.addiu(A0, A0, 1); sll(A0, A0, 1); call('tag2'); a.move(T6, ZERO)
    a.label('ring_k')
    lc(T2, 'HIDDEN'); a.branch(4, T2, ZERO, 'ring_point'); offv(); offv(); a.jump('ring_next')
    a.label('ring_point'); lc(T7, 'STEP'); mult(T7, T7, T6); table(T7, 'ANG49', T7)
    a.addiu(T4, T7, 64); sin(T4, T4); sin(T5, T7)                              # t4 = cos, t5 = sin
    lc(A2, 'CI'); lc(T3, 'CO'); lc(T2, 'MODE'); a.branch(4, T2, ZERO, 'ring_inner')
    a.i(10, T2, T4, 0); a.branch(5, T2, ZERO, 'ring_side'); a.move(A2, T3)
    a.label('ring_side'); a.move(T3, A2)
    a.label('ring_inner'); sc(T3, 'C')
    lc(T2, 'RXI'); mult(T2, T2, T4); sra(T2, T2, 7); lc(A0, 'CX'); addu(A0, A0, T2); lc(T2, 'RYI'); mult(T2, T2, T5); sra(T2, T2, 7); lc(A1, 'CY'); addu(A1, A1, T2)
    a.call(sub['vertex'])
    lc(T2, 'RXO'); mult(T2, T2, T4); sra(T2, T2, 7); lc(A0, 'CX'); addu(A0, A0, T2); lc(T2, 'RYO'); mult(T2, T2, T5); sra(T2, T2, 7); lc(A1, 'CY'); addu(A1, A1, T2)
    lc(A2, 'C'); a.call(sub['vertex'])
    a.label('ring_next'); a.addiu(T6, T6, 1); lc(T0, 'N'); sltu(T2, T0, T6); a.branch(4, T2, ZERO, 'ring_k')
    a.lw(RA, SP, S['RA']); a.jr()

    # ---- tables ----------------------------------------------------------------------------------------------------------
    bytes_table('SIN8', [v & 255 for v in SIN8]); bytes_table('FADE25', FADE25); bytes_table('RAMP54', RAMP54); bytes_table('EIN54', EIN54)
    bytes_table('END16', END16); bytes_table('BELL17', BELL17); bytes_table('EASE21', EASE21); bytes_table('ANG49', ANG49)
    bytes_table('FLASH18', FLASH18); bytes_table('BOLT8', BOLT8); bytes_table('CHEV50', CHEV50); bytes_table('RING_A', RING_A)
    bytes_table('RING_W8', RING_W8); bytes_table('RING_W14', RING_W14); bytes_table('RING_R', RING_R, half=True)
    blob = b''
    for name, data in tables.items():
        a.labels['tbl_'+name] = a.pc+len(blob); blob += data; blob += bytes((-len(blob)) % 4)
    # resolve the table fixups (lui/ori pairs) before finish() handles the branches and jumps
    remaining = []
    for index, label, kind in a.fixups:
        if kind == 'lui': a.words[index] |= (a.labels[label] >> 16) & 0xFFFF
        elif kind == 'ori': a.words[index] |= a.labels[label] & 0xFFFF
        else: remaining.append((index, label, kind))
    a.fixups = remaining
    data = a.finish()+blob
    assert len(data) <= END-CODE, len(data)
    return data
