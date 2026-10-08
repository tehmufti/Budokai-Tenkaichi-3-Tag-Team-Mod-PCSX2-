"""Loading protocol v4 (Ki Storm, PORT-SPEC 5.1): everything the host packet builders, the guest
payload (guest_loading_screen) and the KS light emitters (loading_lights_a/_b) agree on.

Buffer: header <4I (size, generation, foreground offset, descriptor offset), packet A, packet
B, then the DESCRIPTOR (4096 B, magic 'L4KS'). packet_a() = ONE arena allocation copied
verbatim: GS setup, the background/foreground/atlas IMAGE uploads, every CLUT, TEXFLUSH and
the full-screen background sprite. packet_b() = the foreground register state only.

VRAM (64-word blocks; PSMT8 page 128x64 px = 32 blocks, CT32 page 64x32): BG_TBP 0x2D00..
0x3080 and FG_TBP 0x3080..0x3400 (512x448, 7 page rows each); the 256x32 atlas at ATLAS_TBP
0x3400 spans TWO pages horizontally (0x3400 x 0..127, 0x3420 x 128..255) and only their row
0..31 blocks {0..7, 16..23}. The CLUT banks therefore sit in the row 32..63 blocks {8..15,
24..31} of the four page-row-7 pages, as vram-survey.md section 7 derives (the spec's literal
0x3420/0x3424/0x3428+4k banks would be overwritten by the atlas's second page):
CLUT_BANK(i) = 0x3400 + 0x20*(i//4) + (8, 12, 24, 28)[i%4]; BG_CBP = bank 0, ATLAS_CBP =
bank 1, SLICE_CBP(k) = bank k+2. vram_blocks() computes every footprint from the block
tables and the tests assert they are disjoint and inside 0x2D00..0x3480 (VRAM_FLOOR).

Descriptor layout (offsets in bytes; every field a 32-bit little-endian word unless noted;
colours packed r|g<<8|b<<16|0x80<<24; signed fields two's complement):
  HEADER 0: MAGIC, FLAGS, N_SLICES, N_RIBBONS, N_TICKS, FADE_COLOR, FADE_FRAMES, reserved.
  SLICES 32: 14 x SLICE_STRIDE 48 (SLICE_WORDS: x, y, w, h, u, v, cbp, start, dx, dy,
    tex0_lo, tex0_hi = the ready TEX0_1 word for that slice); unused slices are all zero.
  RIBBONS 704: 6 x RIBBON_STRIDE 144 (RIBBON_WORDS, then 17 packed centre colours at +72).
  SPARK_REGIONS 1568: 2 x 16 (x0, y0, x1, y1). SPARK_ENTRIES 1600: 128 x 8: word 0 =
    ribbon | u<<8 | speed<<16 | phase<<24, word 1 = size | streak<<8 | twinkle<<16.
  ORBS 2624: 2 x 40 (ORB_WORDS). SEAM 2704 (24 B), RING 2736, FLASH 2768 (32 B each).
  BOLTS 2800: 2 x 40 (BOLT_WORDS). CHEVRONS 2880 (36 B). TICKS 2928: 12 x 48 (TICK_WORDS).
  GAUGE 3504: GAUGE_WORDS (fill 0..255 and orb_alpha 0..255 derived from progress 0..100),
    then at +68 four digit entries x 24 B (u, v, w, h, x, y; unused ones zero).
  SHEENS 3680: 2 x 16. DOTS 3712 (24 B). NOISE 3744: 128 bytes. DESCRIPTOR = 4096.
FLAGS bits: FADE 1, RIBBONS 2 (ribbons + sparks), STORM 4 (orbs, seam, ring, flash, bolts,
chevrons), TICKS 8, GAUGE 16, SHEENS 32, DOTS 64.
"""
import struct

from loading_texture_probe import (tex0, bitbltbuf, trxpos, trxreg, test1, alpha1, clamp1, tex1,
                                   ad_block, image_blocks, upload_image, textured_sprite, uv,
                                   PSMCT32, PSMT8, MAX_NLOOP, ATST, Q_ONE_WHITE, SPRITE_REGS,
                                   PRIM, RGBAQ, UV, XYZ2, TEX0_1, CLAMP_1, TEX1_1, XYOFFSET_1, PRMODECONT,
                                   TEXFLUSH, SCISSOR_1, ALPHA_1, DTHE, COLCLAMP, TEST_1, PABE, FBA_1,
                                   BITBLTBUF, TRXPOS, TRXREG, TRXDIR, AD)
import loading_textures
import loading_lights_a
import loading_lights_b
from regional import tbp, SCISSOR_Y1, Y_ORIGIN, window_y, xyz2_y

BUFFERS, CAPACITY = (0x06A00000, 0x06A80000), 0x80000
MAGIC, DESCRIPTOR = 0x534B344C, 4096                  # 'L4KS' little-endian, like the v3 'L3AN'
# The European 512-line buffers push every native bank +0x600 blocks (regional.tbp): the zone keeps its place
# between the shifted HUD/stream banks and the resident textures.
BG_TBP, FG_TBP, ATLAS_TBP = tbp(0x2D00), tbp(0x3080), tbp(0x3400)
ATLAS_TBW, ATLAS_TW, ATLAS_TH, ATLAS_SIZE = 4, 8, 5, (256, 32)
MAX_SLICES = 14
VRAM_FLOOR, VRAM_BASE = tbp(0x3480), tbp(0x2D00)     # resident textures above, HUD banks below
NATIVE = (512, 448)
KS_RETURN = 0xF8                                      # payload frame word holding the KS return address
KS_SCRATCH = (0xA0, 0xF8)                             # payload frame words free for the KS emitters
LIGHT_A, FGB = loading_lights_a.SIZE, loading_lights_b.SIZE
N_TAGS = 4                                            # arena allocations per drawn frame: A, KS_A, B, KS_B
RESERVE = N_TAGS*16+LIGHT_A+FGB+64                    # plus the copied packets (runtime, from the header)


def CLUT_BANK(i):
    if not 0 <= i < 16: raise ValueError('CLUT bank index')
    return tbp(0x3400)+0x20*(i//4)+(8, 12, 24, 28)[i % 4]


BG_CBP, ATLAS_CBP = CLUT_BANK(0), CLUT_BANK(1)


def SLICE_CBP(k):
    if not 0 <= k < MAX_SLICES: raise ValueError('slice index')
    return CLUT_BANK(k+2)


# PRIM words (spec 5.2): every emitted primitive has ABE except the background sprite.
STRIP, FAN, LINE_STRIP, LINE_LIST, SPRITE, TSPRITE, BG_SPRITE = 0x4C, 0x4D, 0x4A, 0x49, 0x46, 0x156, 0x116
STANDARD, ADDITIVE = alpha1(0, 1, 0, 1, 0), alpha1(0, 2, 0, 1, 0)       # (Cs-Cd)*As+Cd ; Cs*As+Cd
SETUP_TEST, DRAW_TEST = test1(0, 0, 0, 0, 0, 0, 1, 1), test1(1, ATST['GREATER'], 0, 0, 0, 0, 1, 1)
LINEAR_TEX1 = tex1(0, 0, 1, 1, 0, 0, 0)
# Every picture sprite maps one texel to one pixel, so bilinear costs four taps per pixel for
# the same result: point sampling is what the pictures and the atlas use. LINEAR_TEX1 stays for
# anything that ever scales.
NEAREST_TEX1 = tex1(0, 0, 0, 0, 0, 0, 0)
CLAMP_BOTH = clamp1(1, 1, 0, 0, 0, 0)


def scissor(x0, x1, y0, y1):
    if not (0 <= x0 <= x1 < 2048 and 0 <= y0 <= y1 < 2048): raise ValueError('scissor')
    return x0 | (x1 << 16) | (y0 << 32) | (y1 << 48)


def xyoffset(x, y):
    """XYOFFSET_1 in 1/16 px; the mod's vertices carry the same (1792, 1824) origin."""
    return (x*16) | ((y*16) << 32)


# The GS origin of this disc's frame: USA (1792, 1824) for 448 lines, European (1792, 1792) for 512. Positions
# stay in the 512x448 design frame (NATIVE, also the texture size); vertices stretch them (regional.screen_y).
ORIGIN = (1792, Y_ORIGIN)
REGION_CLAMP = clamp1(2, 2, 0, NATIVE[0]-1, 0, NATIVE[1]-1)
BG_TEX0 = tex0(BG_TBP, 8, PSMT8, 9, 9, 1, 1, BG_CBP, 0, 0, 0, 1)          # decal: the CLUT colour as is
ATLAS_TEX0 = tex0(ATLAS_TBP, ATLAS_TBW, PSMT8, ATLAS_TW, ATLAS_TH, 1, 0, ATLAS_CBP, 0, 0, 0, 1)


def fg_tex0(k):
    """TEX0_1 for foreground slice k: modulate by the vertex colour (alpha ramps), that slice's CLUT."""
    return tex0(FG_TBP, 8, PSMT8, 9, 9, 1, 0, SLICE_CBP(k), 0, 0, 0, 1)


SETUP = ((scissor(0, NATIVE[0]-1, 0, SCISSOR_Y1), SCISSOR_1), (xyoffset(*ORIGIN), XYOFFSET_1), (1, PRMODECONT),
         (SETUP_TEST, TEST_1), (STANDARD, ALPHA_1), (0, PABE), (1, COLCLAMP), (0, DTHE), (0, FBA_1))
PACKET_LIMIT = 65536*16-16                            # one DMA CNT + VIF1 DIRECT allocation

# The guest does not copy the pictures into the GIF arena: it appends a DMA REF tag (the native
# sub_100738 builder) that points the DMA at the published buffer, so 470+ KiB a frame stay
# where the host put them and the arena only has to hold the KS blocks. A REF tag carries no VIF
# code of its own, so each referenced run begins with this qword: three VIF NOPs and a DIRECT
# whose NUM counts the GIF qwords that follow (the native REF runs are built the same way).
VIF_HEADER = 16
VIF_DIRECT = 0x50000000


def vif_header(packet):
    """The 16-byte VIF prologue for a referenced GIF run (NOP, NOP, NOP, DIRECT num)."""
    if len(packet) % 16: raise ValueError('a referenced packet must be a whole number of qwords')
    qwords = len(packet)//16
    if not 1 <= qwords <= 65536: raise ValueError('DIRECT NUM is a 16-bit field')
    return struct.pack('<4I', 0, 0, 0, VIF_DIRECT | (qwords & 0xFFFF))


def referenced(packet):
    return vif_header(packet)+packet


# ---- VRAM footprints ---------------------------------------------------------------------------
# Block table of a page for PSMT8 (128x64 px, 16x16 blocks) and PSMCT32 (64x32 px, 8x8 blocks).
BLOCK_TABLE = ((0, 1, 4, 5, 16, 17, 20, 21), (2, 3, 6, 7, 18, 19, 22, 23),
               (8, 9, 12, 13, 24, 25, 28, 29), (10, 11, 14, 15, 26, 27, 30, 31))
PAGE = {PSMT8: (128, 64, 16, 16), PSMCT32: (64, 32, 8, 8)}


def vram_blocks(psm, dbp, dbw, width, height, x=0, y=0):
    """Set of block addresses a width x height image at (x, y) in a buffer of dbw*64 px touches."""
    page_w, page_h, block_w, block_h = PAGE[psm]
    pages_per_row = max(1, dbw*64//page_w)
    blocks = set()
    for py in range(y, y+height, block_h):
        for px in range(x, x+width, block_w):
            page = (py//page_h)*pages_per_row+px//page_w
            blocks.add(dbp+page*32+BLOCK_TABLE[(py % page_h)//block_h][(px % page_w)//block_w])
    return blocks


def vram_footprints(n_slices=MAX_SLICES):
    """(name, blocks) of every upload of packet A: the tests assert disjointness inside the zone."""
    out = [('background', vram_blocks(PSMT8, BG_TBP, 8, *NATIVE)), ('foreground', vram_blocks(PSMT8, FG_TBP, 8, *NATIVE)),
           ('atlas', vram_blocks(PSMT8, ATLAS_TBP, ATLAS_TBW, *ATLAS_SIZE)),
           ('bg_clut', vram_blocks(PSMCT32, BG_CBP, 1, 16, 16)), ('atlas_clut', vram_blocks(PSMCT32, ATLAS_CBP, 1, 16, 16))]
    out += [(f'slice_clut_{k}', vram_blocks(PSMCT32, SLICE_CBP(k), 1, 16, 16)) for k in range(n_slices)]
    return out


# ---- packets -------------------------------------------------------------------------------------
def _check_packet(packet):
    if len(packet) % 16 or len(packet) > PACKET_LIMIT: raise ValueError('Loading packet size')
    return bytes(packet)


def packet_a(quantised):
    """ONE GIF packet: setup, every upload, TEXFLUSH, the background draw (EOP on the last tag).

    quantised = loading_textures.quantise(layers): background (indices, clut), foreground
    (indices, clut per slice), atlas (indices, clut), slices.
    """
    (bg_idx, bg_clut), (fg_idx, cluts), (atlas_idx, atlas_clut) = quantised['background'], quantised['foreground'], quantised['atlas']
    slices = quantised['slices']
    if len(cluts) != len(slices) or not 1 <= len(slices) <= MAX_SLICES: raise ValueError('one CLUT per slice, at most 14 slices')
    out = bytearray(ad_block(SETUP))
    out += upload_image(BG_TBP, 8, PSMT8, NATIVE[0], NATIVE[1], bg_idx.tobytes())
    out += upload_image(FG_TBP, 8, PSMT8, NATIVE[0], NATIVE[1], fg_idx.tobytes())
    out += upload_image(ATLAS_TBP, ATLAS_TBW, PSMT8, ATLAS_SIZE[0], ATLAS_SIZE[1], atlas_idx.tobytes())
    out += upload_image(BG_CBP, 1, PSMCT32, 16, 16, loading_textures.clut_swizzle_csm1(bg_clut))
    out += upload_image(ATLAS_CBP, 1, PSMCT32, 16, 16, loading_textures.clut_swizzle_csm1(atlas_clut))
    for k, clut in enumerate(cluts): out += upload_image(SLICE_CBP(k), 1, PSMCT32, 16, 16, loading_textures.clut_swizzle_csm1(clut))
    out += ad_block([(0, TEXFLUSH)])
    out += ad_block([(BG_TEX0, TEX0_1), (NEAREST_TEX1, TEX1_1), (REGION_CLAMP, CLAMP_1), (BG_SPRITE, PRIM)])
    out += textured_sprite(0, 0, NATIVE[0], NATIVE[1], 0, 0, NATIVE[0]*16, NATIVE[1]*16, eop=True)
    return _check_packet(out)


def packet_a_size(n_slices):
    return 16+9*16+2*(80+16+NATIVE[0]*NATIVE[1])+(80+16+ATLAS_SIZE[0]*ATLAS_SIZE[1])+(2+n_slices)*(80+16+1024)+32+80+64


def packet_b():
    """Foreground register state; the guest writes TEX0 per slice (each slice has its own CBP)."""
    return _check_packet(ad_block([(NEAREST_TEX1, TEX1_1), (CLAMP_BOTH, CLAMP_1), (STANDARD, ALPHA_1), (DRAW_TEST, TEST_1), (TSPRITE, PRIM)], eop=True))


def xyz2(x, y):
    """XYZ2 for a native position, off-screen allowed (the scissor clips slid slices and hidden geometry)."""
    if not (-ORIGIN[0] <= x < 4096-ORIGIN[0] and 0 <= window_y(y) < 4096): raise ValueError('Vertex outside the GS window')
    return ((x+ORIGIN[0])*16) | (xyz2_y(y) << 16)


def foreground_draw(slices, p=255, eop=True):
    """Host reference of the KS_B FG_DRAW at entrance progress p (0..255, 255 = at rest): per slice
    one A+D TEX0_1 (that slice's CLUT) and one textured sprite REGLIST (RGBAQ, UV, XYZ2, UV, XYZ2),
    RGBAQ (0x80, 0x80, 0x80, (p+1)>>1), position slid by dx, dy*(255-p)>>8; unused slots up to
    MAX_SLICES are degenerate (x0 == x1) so the size is fixed."""
    out = bytearray()
    for k in range(MAX_SLICES):
        tag = struct.pack('<2Q', 1 | (int(bool(eop and k == MAX_SLICES-1)) << 15) | (1 << 58) | (5 << 60), SPRITE_REGS)
        out += ad_block([(fg_tex0(k), TEX0_1)])+tag
        if k < len(slices):
            s = slices[k]
            x, y = s['x']+(s['dx']*(255-p) >> 8), s['y']+(s['dy']*(255-p) >> 8)
            rgbaq = 0x80 | (0x80 << 8) | (0x80 << 16) | (((p+1) >> 1) << 24) | (0x3F800000 << 32)
            out += struct.pack('<6Q', rgbaq, uv(s['u']*16, s['v']*16), xyz2(x, y), uv((s['u']+s['w'])*16, (s['v']+s['h'])*16), xyz2(x+s['w'], y+s['h']), 0)
        else:
            out += struct.pack('<6Q', Q_ONE_WHITE, 0, xyz2(0, 0), 0, xyz2(0, 0), 0)
    return bytes(out)


# ---- descriptor layout -----------------------------------------------------------------------------
HEADER = 0
FLAGS, N_SLICES, N_RIBBONS, N_TICKS, FADE_COLOR, FADE_FRAMES = 4, 8, 12, 16, 20, 24
FLAG_FADE, FLAG_RIBBONS, FLAG_STORM, FLAG_TICKS, FLAG_GAUGE, FLAG_SHEENS, FLAG_DOTS = 1, 2, 4, 8, 16, 32, 64
SLICES, SLICE_STRIDE = 32, 48
SLICE_WORDS = ('x', 'y', 'w', 'h', 'u', 'v', 'cbp', 'start', 'dx', 'dy', 'tex0_lo', 'tex0_hi')
RIBBONS, RIBBON_STRIDE, RIBBON_COLORS, MAX_RIBBONS = SLICES+MAX_SLICES*SLICE_STRIDE, 144, 72, 6
RIBBON_WORDS = ('side', 'x0', 'x1', 'y0', 'y1', 'A1', 'f1', 'w1', 'p1', 'A2', 'f2', 'w2', 'p2', 'W', 'wf', 'wp', 'fade_start', 'fade_end')
SPARK_REGIONS, SPARK_REGION_WORDS = RIBBONS+MAX_RIBBONS*RIBBON_STRIDE, ('x0', 'y0', 'x1', 'y1')
SPARK_ENTRIES, SPARK_STRIDE, MAX_SPARKS = SPARK_REGIONS+32, 8, 128
ORBS, ORB_STRIDE = SPARK_ENTRIES+MAX_SPARKS*SPARK_STRIDE, 40
ORB_WORDS = ('side', 'cx', 'cy', 'rx', 'ry', 'core', 'team', 'deep', 'halo', 'flight_y')
SEAM, SEAM_WORDS = ORBS+2*ORB_STRIDE, ('cx', 'cy', 'rx', 'ry', 'color', 'edge')
RING, RING_WORDS = SEAM+32, ('cx', 'cy', 'left', 'right', 'inner', 'life', 'first', 'cycle')
FLASH, FLASH_WORDS = RING+32, ('cx', 'cy', 'rx', 'ry', 'color', 'edge', 'start', 'frames')
BOLTS, BOLT_STRIDE, BOLT_WORDS = FLASH+32, 40, ('x0', 'y0', 'x1', 'y1', 'bulge', 'period', 'duration', 'color', 'glow')
CHEVRONS, CHEVRON_WORDS = BOLTS+2*BOLT_STRIDE, ('cx', 'cy', 'offset', 'pitch', 'count', 'color0', 'color1', 'period', 'stagger')
TICKS, TICK_STRIDE, MAX_TICKS = CHEVRONS+48, 48, 12
TICK_WORDS = ('cx', 'cy', 'rx', 'ry', 'n', 'direction', 'color', 'bx0', 'by0', 'bx1', 'by1', 'cursor')
GAUGE = TICKS+MAX_TICKS*TICK_STRIDE
GAUGE_WORDS = ('x0', 'x1', 'y0', 'y1', 'fill', 'color0', 'color1', 'color2', 'tip', 'orb_cx', 'orb_cy', 'orb_rx', 'orb_ry', 'orb_color',
               'progress', 'orb_alpha', 'n_digits')
GAUGE_DIGITS, DIGIT_STRIDE, MAX_DIGITS, DIGIT_WORDS = GAUGE+4*len(GAUGE_WORDS), 24, 4, ('u', 'v', 'w', 'h', 'x', 'y')
GAUGE_STRIDE = 176
SHEENS, SHEEN_WORDS = GAUGE+GAUGE_STRIDE, ('x0', 'y0', 'x1', 'y1')
DOTS, DOTS_WORDS = SHEENS+32, ('x', 'y', 'pitch', 'size', 'color', 'count')
NOISE, NOISE_BYTES = DOTS+32, 128
LAYOUT_END = NOISE+NOISE_BYTES
assert LAYOUT_END <= DESCRIPTOR and GAUGE_DIGITS+MAX_DIGITS*DIGIT_STRIDE <= GAUGE+GAUGE_STRIDE
assert all(v % 16 == 0 for v in (SLICES, RIBBONS, SPARK_REGIONS, SPARK_ENTRIES, ORBS, SEAM, RING, FLASH, BOLTS, CHEVRONS, TICKS, GAUGE, SHEENS, DOTS, NOISE))
COLOR_FIELDS = {'core', 'team', 'deep', 'halo', 'color', 'edge', 'left', 'right', 'inner', 'glow', 'color0', 'color1', 'color2', 'tip',
                'orb_color', 'cursor'}
SECTIONS = dict(seam=(SEAM, SEAM_WORDS), ring=(RING, RING_WORDS), flash=(FLASH, FLASH_WORDS), chevrons=(CHEVRONS, CHEVRON_WORDS),
                dots=(DOTS, DOTS_WORDS))


def packed_color(rgb):
    r, g, b = (int(v) & 255 for v in rgb[:3]); return r | (g << 8) | (b << 16) | (0x80 << 24)


def unpack_color(word):
    if word >> 24 != 0x80: raise ValueError('packed colour alpha')
    return (word & 255, (word >> 8) & 255, (word >> 16) & 255)


def noise_table(seed=0x4C494748):
    """Deterministic pseudo-random bytes for bolt jitter and flicker (the v3 table, unchanged)."""
    out = bytearray(); x = seed & 0xFFFFFFFF
    for _ in range(NOISE_BYTES):
        x = (x*1103515245+12345) & 0xFFFFFFFF; out.append((x >> 16) & 255)
    return bytes(out)


def gauge_fill(progress):
    """Fill 0..255 and ki-orb alpha 0..255 the encoder derives from progress 0..100."""
    p = max(0, min(100, int(progress)))
    return (p*255+50)//100, 32+96*p//100


def _words(data, offset, names, values):
    for i, name in enumerate(names):
        v = values[name]
        struct.pack_into('<I', data, offset+4*i, (packed_color(v) if name in COLOR_FIELDS else int(v)) & 0xFFFFFFFF)


def _read(data, offset, names):
    out = {}
    for i, name in enumerate(names):
        word = struct.unpack_from('<I', data, offset+4*i)[0]
        out[name] = unpack_color(word) if name in COLOR_FIELDS else (word-(1 << 32) if word >= 1 << 31 else word)
    return out


def _flat_chevrons(c): return dict(c, color0=c['colors'][0], color1=c['colors'][1])


def _flat_tick(t): return dict(t, bx0=t['box'][0], by0=t['box'][1], bx1=t['box'][2], by1=t['box'][3])


def encode_lights(plan, progress=0, gauge_digits=(), slices=None):
    """Descriptor bytes. `plan` is loading_art_v4.compose() output (keys lights, slices) or the
    lights plan itself with `slices` given; `gauge_digits` = loading_art_v4.gauge_digits(progress)."""
    lights = plan['lights'] if 'lights' in plan else plan
    slices = list(plan.get('slices', ()) if slices is None else slices)
    if not lights: return b''
    data = bytearray(DESCRIPTOR); flags = 0
    if len(slices) > MAX_SLICES: raise ValueError('Too many entrance slices')
    for k, s in enumerate(slices):
        if not (0 <= s['x'] < s['x']+s['w'] <= NATIVE[0] and 0 <= s['y'] < s['y']+s['h'] <= NATIVE[1]): raise ValueError('Slice outside the native frame')
        word = fg_tex0(k)
        _words(data, SLICES+k*SLICE_STRIDE, SLICE_WORDS, dict(s, u=s['u'], v=s['v'], cbp=SLICE_CBP(k), tex0_lo=word & 0xFFFFFFFF, tex0_hi=word >> 32))
    fade = lights.get('fade')
    if fade:
        struct.pack_into('<2I', data, FADE_COLOR, packed_color(fade['color']), int(fade.get('frames', 24))); flags |= FLAG_FADE
    ribbons = list(lights.get('ribbons') or ())
    if len(ribbons) > MAX_RIBBONS: raise ValueError('Too many ribbons')
    for i, rb in enumerate(ribbons):
        if len(rb['colors']) != 17: raise ValueError('A ribbon carries 17 centre colours')
        base = RIBBONS+i*RIBBON_STRIDE; _words(data, base, RIBBON_WORDS, rb)
        for j, c in enumerate(rb['colors']): struct.pack_into('<I', data, base+RIBBON_COLORS+4*j, packed_color(c))
    sparks = lights.get('sparks')
    if ribbons and sparks:
        regions = list(sparks['regions']); entries = list(sparks['entries'])
        if len(regions) != 2 or len(entries) > MAX_SPARKS: raise ValueError('Sparks: two regions, at most 128 entries')
        for i, region in enumerate(regions): _words(data, SPARK_REGIONS+16*i, SPARK_REGION_WORDS, region)
        for i, e in enumerate(entries):
            if not (e['ribbon'] < len(ribbons) and 0 <= e['u'] < 256 and 0 < e['speed'] < 256 and 0 <= e['phase'] < 256
                    and 0 < e['size'] < 256 and e['streak'] in (0, 1) and 0 <= e['twinkle'] < 256): raise ValueError('Spark entry out of range')
            struct.pack_into('<2I', data, SPARK_ENTRIES+SPARK_STRIDE*i, e['ribbon'] | (e['u'] << 8) | (e['speed'] << 16) | (e['phase'] << 24),
                             e['size'] | (e['streak'] << 8) | (e['twinkle'] << 16))
        flags |= FLAG_RIBBONS
    orbs = list(lights.get('orbs') or ())
    if orbs:
        if len(orbs) != 2 or len(lights.get('bolts') or ()) != 2: raise ValueError('The storm has two orbs and two bolts')
        for i, orb in enumerate(orbs): _words(data, ORBS+i*ORB_STRIDE, ORB_WORDS, orb)
        for i, bolt in enumerate(lights['bolts']):
            if bolt['period'] not in (31, 63, 127, 255, 511) or not 1 <= bolt['duration'] < bolt['period']: raise ValueError('Bolt period must be 2^n-1 and longer than its duration')
            _words(data, BOLTS+i*BOLT_STRIDE, BOLT_WORDS, bolt)
        for name in ('seam', 'ring', 'flash'): _words(data, SECTIONS[name][0], SECTIONS[name][1], lights[name])
        _words(data, CHEVRONS, CHEVRON_WORDS, _flat_chevrons(lights['chevrons']))
        flags |= FLAG_STORM
    ticks = list(lights.get('ticks') or ())
    if len(ticks) > MAX_TICKS: raise ValueError('Too many tick rings')
    for i, tick in enumerate(ticks): _words(data, TICKS+i*TICK_STRIDE, TICK_WORDS, _flat_tick(tick))
    if ticks: flags |= FLAG_TICKS
    gauge = lights.get('gauge')
    if gauge:
        fill, orb_alpha = gauge_fill(progress); digits = list(gauge_digits or ())[:MAX_DIGITS]
        values = dict(gauge, color0=gauge['colors'][0], color1=gauge['colors'][1], color2=gauge['colors'][2],
                      orb_cx=gauge['orb']['cx'], orb_cy=gauge['orb']['cy'], orb_rx=gauge['orb']['rx'], orb_ry=gauge['orb']['ry'],
                      orb_color=gauge['orb']['color'], fill=fill, progress=max(0, min(100, int(progress))), orb_alpha=orb_alpha, n_digits=len(digits))
        _words(data, GAUGE, GAUGE_WORDS, values)
        for i, d in enumerate(digits): _words(data, GAUGE_DIGITS+i*DIGIT_STRIDE, DIGIT_WORDS, d)
        flags |= FLAG_GAUGE
    sheens = list(lights.get('sheens') or ())
    if len(sheens) > 2: raise ValueError('Two banner sheens')
    for i, sheen in enumerate(sheens): _words(data, SHEENS+16*i, SHEEN_WORDS, sheen)
    if sheens: flags |= FLAG_SHEENS
    dots = lights.get('dots')
    if dots: _words(data, DOTS, DOTS_WORDS, dict(dots, count=dots.get('count', 3))); flags |= FLAG_DOTS
    data[NOISE:NOISE+NOISE_BYTES] = noise_table()
    struct.pack_into('<5I', data, 0, MAGIC, flags, len(slices), len(ribbons), len(ticks))
    return bytes(data)


def decode_lights(data):
    """The descriptor back as plain dicts (colours as (r, g, b)); the tests round-trip a real plan."""
    if len(data) != DESCRIPTOR: raise ValueError('descriptor size')
    magic, flags, n_slices, n_ribbons, n_ticks = struct.unpack_from('<5I', data, 0)
    if magic != MAGIC: raise ValueError('descriptor magic')
    out = dict(flags=flags, slices=[_read(data, SLICES+k*SLICE_STRIDE, SLICE_WORDS) for k in range(n_slices)])
    color, frames = struct.unpack_from('<2I', data, FADE_COLOR)
    out['fade'] = dict(color=unpack_color(color), frames=frames) if flags & FLAG_FADE else None
    ribbons = []
    for i in range(n_ribbons):
        base = RIBBONS+i*RIBBON_STRIDE; rb = _read(data, base, RIBBON_WORDS)
        rb['colors'] = [unpack_color(struct.unpack_from('<I', data, base+RIBBON_COLORS+4*j)[0]) for j in range(17)]
        ribbons.append(rb)
    out['ribbons'] = ribbons
    if flags & FLAG_RIBBONS:
        entries = []
        for i in range(MAX_SPARKS):
            w0, w1 = struct.unpack_from('<2I', data, SPARK_ENTRIES+SPARK_STRIDE*i)
            entries.append(dict(ribbon=w0 & 255, u=(w0 >> 8) & 255, speed=(w0 >> 16) & 255, phase=w0 >> 24, size=w1 & 255, streak=(w1 >> 8) & 255, twinkle=(w1 >> 16) & 255))
        out['sparks'] = dict(regions=[_read(data, SPARK_REGIONS+16*i, SPARK_REGION_WORDS) for i in range(2)], entries=entries)
    if flags & FLAG_STORM:
        out['orbs'] = [_read(data, ORBS+i*ORB_STRIDE, ORB_WORDS) for i in range(2)]
        out['bolts'] = [_read(data, BOLTS+i*BOLT_STRIDE, BOLT_WORDS) for i in range(2)]
        for name in ('seam', 'ring', 'flash', 'chevrons'): out[name] = _read(data, SECTIONS[name][0], SECTIONS[name][1])
    out['ticks'] = [_read(data, TICKS+i*TICK_STRIDE, TICK_WORDS) for i in range(n_ticks)]
    if flags & FLAG_GAUGE:
        gauge = _read(data, GAUGE, GAUGE_WORDS)
        gauge['digits'] = [_read(data, GAUGE_DIGITS+i*DIGIT_STRIDE, DIGIT_WORDS) for i in range(gauge['n_digits'])]
        out['gauge'] = gauge
    if flags & FLAG_SHEENS: out['sheens'] = [_read(data, SHEENS+16*i, SHEEN_WORDS) for i in range(2)]
    if flags & FLAG_DOTS: out['dots'] = _read(data, DOTS, DOTS_WORDS)
    out['noise'] = bytes(data[NOISE:NOISE+NOISE_BYTES])
    return out
