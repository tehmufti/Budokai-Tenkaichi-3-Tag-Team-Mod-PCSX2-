"""The look of the mod's in-battle HUD: the game's own font and HUD art for every mod element.

Every match installs one shared drawing kit at BASE..END and re-points the mod's classic draw calls to it. The
classic routines stay installed underneath as an internal fallback only: an element whose native font or art is not
resident (or a group whose bit is clear in the style word) draws them unchanged. The one player choice left is the
target marker's look (setting lockon_target_look: classic / native, the 'lockon' bit of the style word); online
each PC writes that bit into its own copy of the match (kit_settings LOCAL).

The kit:
- NTEXT draws the game's own resident Latin font ("Fnt5PS2" header, 2-bit anti-aliased glyphs; the font the
  menus and descriptions use). At preparation its glyph pixels are copied from the captured RAM into a private
  4-bit atlas with a baked dark outline, uploaded through the native texture service 224F00 into the portrait
  bank (native portraits re-upload before each draw, 21F480 -> 21F438) and drawn as textured gouraud strips:
  a light-to-deep vertical gradient of the caller's colour and a slight italic slant, the treatment of the
  game's own "Lock on" / "13 Hits!" lettering. Same ABI as guest_killfeed.TEXT (a0 string, a1/a2 GS 12.4
  top-left, a3 ABGR); the extended entry takes t0 = GS units per atlas pixel.
- NART draws any resident native texture descriptor (battle HUD atlases, combo/message art) from a private copy
  of its descriptor, so native upload-cache flags are never touched.
The game's art is read from the player's own disc image in RAM; nothing of it is shipped.
Draw only: no fighter, camera, input or timer state is read for writing; online peers stay identical.
"""
import struct

from native_map import A
from prototype import Assembler
from regional import tbp

BASE, END = 0x07150000, 0x07180000
NTEXT = BASE                  # a0 str, a1 x, a2 y, a3 ABGR (TEXT ABI, 8 units per atlas pixel)
NTEXT_SMALL = BASE + 0x40     # as guest_killfeed.SMALL_TEXT: 75% in 3/4-view matches, else NTEXT
NTEXT_75 = BASE + 0xC0        # always 75% (the tag caption's private renderer)
NTEXT_SCALED = BASE + 0x140   # t0 = GS units per atlas pixel (8 = classic text size)
TRAMPS = BASE + 0xE00         # the classic entries' first two instructions, then a jump back (style word 0)
TRAMP = dict(text=TRAMPS, small=TRAMPS + 0x10, caption=TRAMPS + 0x20)
NART = BASE + 0x1000          # a0 -> ART parameter block (see emit_art)
HELPERS = BASE + 0x27000      # element helpers (gauges, markers) reached from patched classic call sites
SAMPLING = BASE + 0x2A000     # native_hud_sampling page; ends before the sink at +0x2C000
SITES = BASE + 0x2800          # count, then (address, classic word) of every re-pointed classic instruction
SITES_MAX = 255
CONTROL = BASE + 0x3000
FONT_BUNDLE, FONT_DESC = BASE + 0x3100, BASE + 0x3140
ART_BUNDLE, ART_DESC = BASE + 0x3200, BASE + 0x3240     # two scratch descriptors (texture, palette)
METRICS = BASE + 0x3400       # 128 x 16 bytes
TEMPLATES = BASE + 0x3C00
FONT_PIXELS = BASE + 0x4000   # 0x80 header + 32 KiB
FONT_CLUT = BASE + 0xC100     # 0x80 header + 1 KiB
ART_TABLE = BASE + 0xC800     # 32 private descriptors x 64 bytes
ART_DATA, ART_END = BASE + 0xD000, BASE + 0x27000
MAGIC = 0x4E485331            # 'NHS1'
UPLOAD = A(0x224F00)
TEX_TBP, TEX_CBP = tbp(0x2C00), tbp(0x2CD0)   # native portrait bank: re-uploaded before every native use
ATLAS_W, ATLAS_H = 256, 256
SLOT_H, MARGIN, CAP_TOP = 24, 2, 5
SHEAR = 4                     # atlas pixels of italic slant over a slot
MAX_CHARS = 40
REGS = (16, 17, 18, 19, 20, 21, 22, 23, 30, 31)
FRAME = 0x80


# ---------------------------------------------------------------- GS local memory (PSMCT32 upload <-> PSMT4)
_BT32 = ((0, 1, 4, 5, 16, 17, 20, 21), (2, 3, 6, 7, 18, 19, 22, 23), (8, 9, 12, 13, 24, 25, 28, 29),
         (10, 11, 14, 15, 26, 27, 30, 31))
_CT32 = ((0, 1, 4, 5, 8, 9, 12, 13), (2, 3, 6, 7, 10, 11, 14, 15), (16, 17, 20, 21, 24, 25, 28, 29),
         (18, 19, 22, 23, 26, 27, 30, 31), (32, 33, 36, 37, 40, 41, 44, 45), (34, 35, 38, 39, 42, 43, 46, 47),
         (48, 49, 52, 53, 56, 57, 60, 61), (50, 51, 54, 55, 58, 59, 62, 63))
_BT4 = ((0, 2, 8, 10), (1, 3, 9, 11), (4, 6, 12, 14), (5, 7, 13, 15), (16, 18, 24, 26), (17, 19, 25, 27),
        (20, 22, 28, 30), (21, 23, 29, 31))
_R0 = (0, 8, 32, 40, 64, 72, 96, 104, 2, 10, 34, 42, 66, 74, 98, 106, 4, 12, 36, 44, 68, 76, 100, 108, 6, 14, 38,
       46, 70, 78, 102, 110)
_R1 = tuple(v+16 for v in _R0)
_R2 = (65, 73, 97, 105, 1, 9, 33, 41, 67, 75, 99, 107, 3, 11, 35, 43, 69, 77, 101, 109, 5, 13, 37, 45, 71, 79, 103,
       111, 7, 15, 39, 47)
_R3 = tuple(v+16 for v in _R2)
_ROWS = (_R0, _R1, _R2, _R3, tuple(v+127 for v in _R2), tuple(v+127 for v in _R3), tuple(v+129 for v in _R0),
         tuple(v+129 for v in _R1))
_CT4 = _ROWS + tuple(tuple(v+256 for v in r) for r in _ROWS)


def _addr32(x, y, dbw):
    """Byte address of a PSMCT32 pixel, buffer width dbw*64."""
    page = (y//32)*dbw + x//64
    return ((page*32 + _BT32[(y % 32)//8][(x % 64)//8])*64 + _CT32[y % 8][x % 8])*4


def _addr4(x, y, tbw):
    """Nibble address of a PSMT4 pixel, buffer width tbw*64 (tbw even)."""
    page = (y//128)*(tbw//2) + x//128
    return (page*32 + _BT4[(y % 128)//16][(x % 128)//32])*512 + _CT4[y % 16][x % 32]


def psmt4_from_upload(data, rw, rh, width, height, tbw):
    """Indices of a PSMT4 texture that the game uploads as a rw x rh PSMCT32 rectangle."""
    mem = bytearray(max(len(data), (width*height+1)//2) + 0x8000)
    dbw = max(1, rw//64)
    for y in range(rh):
        for x in range(rw):
            a = _addr32(x, y, dbw); s = (y*rw + x)*4
            mem[a:a+4] = data[s:s+4]
    out = bytearray(width*height)
    for y in range(height):
        for x in range(width):
            n = _addr4(x, y, tbw); b = mem[n >> 1]
            out[y*width + x] = (b >> 4) if n & 1 else (b & 15)
    return bytes(out)


def upload_from_psmt4(indices, width, height, tbw):
    """The PSMCT32 rectangle (width/2 x height/4 for tbw = width/64) that writes these PSMT4 indices."""
    mem = bytearray(width*height//2)
    for y in range(height):
        for x in range(width):
            n = _addr4(x, y, tbw); v = indices[y*width + x] & 15
            mem[n >> 1] |= (v << 4) if n & 1 else v
    rw, rh, dbw = width//2, height//4, tbw//2
    out = bytearray(rw*rh*4)
    for y in range(rh):
        for x in range(rw):
            a = _addr32(x, y, dbw); s = (y*rw + x)*4
            out[s:s+4] = mem[a:a+4]
    return bytes(out), rw, rh


# ---------------------------------------------------------------- the resident native font
FONT_MAGIC = b'5tnF 2SP'


def _u32(ram, p):
    # Slicing (not struct.unpack_from) so a lazily fetched RAM image (lazy_ram.LazyRam) reads real bytes too.
    return int.from_bytes(bytes(ram[p:p+4]), 'little')


def find_font(ram):
    """The resident Latin game font: (header, descriptor, glyphs {code: (x, y, w, plane)}, cell) or None."""
    best = None
    pos = ram.find(FONT_MAGIC, 0x100000)
    while pos != -1:
        if pos % 16 == 0 and pos+0x24 < len(ram):
            desc, table, count, cw, ch = (_u32(ram, pos+12), _u32(ram, pos+20), _u32(ram, pos+24),
                                          _u32(ram, pos+28), _u32(ram, pos+32))
            if (0x100000 <= desc < len(ram)-64 and 0x100000 <= table < len(ram)-6*count and 0 < count < 4096
                    and (cw, ch) == (20, 20)):
                glyphs = {}
                for i in range(count):
                    e = ram[table+6*i:table+6*i+6]
                    code = e[0] | e[1] << 8
                    glyphs[code] = (e[2] | (e[3] & 3) << 8, e[4], (e[3] >> 2) & 31, e[3] >> 7)
                score = sum(chr(c) in glyphs for c in range(0x41, 0x5B))
                score += sum(c in glyphs for c in range(0x61, 0x7B))
                if score >= 26 and (best is None or score > best[0]):
                    best = (score, pos, desc, glyphs)
        pos = ram.find(FONT_MAGIC, pos+8)
    if best is None:
        return None
    return dict(header=best[1], descriptor=best[2], glyphs=best[3], cell=(20, 20))


def font_planes(ram, font):
    """(width, height, nibble indices) of the resident font texture; glyph planes are bits 0-1 / 2-3."""
    d = font['descriptor']
    tex0 = int.from_bytes(bytes(ram[d+48:d+56]), 'little')
    if (tex0 >> 20) & 63 != 20:
        raise ValueError('Native font texture is not PSMT4')
    width, height, tbw = 1 << ((tex0 >> 26) & 15), 1 << ((tex0 >> 30) & 15), (tex0 >> 14) & 63
    packet = _u32(ram, d+56)
    if not 0x100000 <= packet < len(ram)-0x60:
        raise ValueError('Native font upload packet changed')
    trx = int.from_bytes(bytes(ram[packet+48:packet+56]), 'little')
    rw, rh = trx & 0xFFF, (trx >> 32) & 0xFFF
    if rw*rh*4 != width*height//2 or not 0x100000 <= packet < len(ram)-rw*rh*4-96:
        raise ValueError('Native font upload packet changed')
    return width, height, psmt4_from_upload(ram[packet+96:packet+96+rw*rh*4], rw, rh, width, height, max(2, tbw))


CHARSET = tuple(range(0x20, 0x7F))
OUTLINE = ((-1, 0, 3), (1, 0, 3), (0, -1, 3), (0, 1, 3), (-1, -1, 2), (1, -1, 2), (-1, 1, 2), (1, 1, 2),
           (-2, 0, 1), (2, 0, 1), (0, -2, 1), (0, 2, 1), (1, 2, 2), (2, 1, 1), (2, 2, 1))


def build_atlas(ram):
    """Private outline-baked atlas from the resident font: (upload bytes, clut bytes, metrics bytes, info)."""
    font = find_font(ram)
    if font is None:
        raise ValueError('Resident game font not found')
    width, height, idx = font_planes(ram, font)
    glyphs = font['glyphs']
    fill = bytearray(ATLAS_W*ATLAS_H)
    metrics = bytearray(128*16)
    placed = {}
    x = y = 0
    for code in CHARSET:
        if code not in glyphs:
            continue
        gx, gy, w, plane = glyphs[code]
        sw = w + 2*MARGIN
        if x + sw > ATLAS_W:
            x, y = 0, y + SLOT_H
        if y + SLOT_H > ATLAS_H:
            raise ValueError('Native font atlas overflow')
        for row in range(20):
            for col in range(w):
                sx, sy = gx+col, gy+row
                if not (0 <= sx < width and 0 <= sy < height):
                    continue
                v = idx[sy*width+sx]
                level = (v >> 2) & 3 if plane else v & 3
                fill[(y+MARGIN+row)*ATLAS_W + x+MARGIN+col] = level
        placed[code] = (x, y, sw, w)
        x += sw
    # Outline level: strongest neighbour fill, weighted by distance (a ~1.5 pixel dark rim).
    outline = bytearray(ATLAS_W*ATLAS_H)
    for py in range(ATLAS_H):
        for px in range(ATLAS_W):
            best = 0
            for dx, dy, weight in OUTLINE:
                qx, qy = px+dx, py+dy
                if 0 <= qx < ATLAS_W and 0 <= qy < ATLAS_H:
                    best = max(best, min(3, fill[qy*ATLAS_W+qx]*weight//3 + (weight == 3 and fill[qy*ATLAS_W+qx] > 0)))
            outline[py*ATLAS_W+px] = best
    indices = bytes((fill[i] << 2) | outline[i] for i in range(ATLAS_W*ATLAS_H))
    upload, rw, rh = upload_from_psmt4(indices, ATLAS_W, ATLAS_H, ATLAS_W//64)
    fallback = placed.get(ord('?'))
    for code in range(128):
        x0, y0, sw, w = placed.get(code, fallback)
        struct.pack_into('<4H3bB', metrics, code*16, x0*16, y0*16, (x0+sw)*16, (y0+SLOT_H)*16,
                         sw, w, -MARGIN, int(code in placed))
    return upload, rw, rh, clut_bytes(), bytes(metrics), dict(font=hex(font['header']), glyphs=len(placed),
                                                              atlas_rows=y//SLOT_H + 1)


def clut_entry(i):
    """Index = fill(2 bits) << 2 | outline(2 bits): white fill over a dark rim, GS alpha 0..0x80."""
    f, o = (i >> 2) / 3, (i & 3) / 3
    alpha = f + o*(1-f)
    if alpha <= 0:
        return (0, 0, 0, 0)
    grey = round(0x80*f/alpha)
    rim = 0x0C
    level = grey + round(rim*(1-f/alpha))
    return (min(0x80, level), min(0x80, level), min(0x80, level), round(0x80*alpha))


def clut_bytes():
    """16x16 PSMCT32 CLUT image; a PSMT4 CSA 0 palette reads columns 0-7 of rows 0-1."""
    image = bytearray(16*16*4)
    for i in range(16):
        row, col = divmod(i, 8)
        image[(row*16+col)*4:(row*16+col)*4+4] = bytes(clut_entry(i))
    return bytes(image)


def _packet(data, rw, rh):
    """A native image packet: VIF DIRECT, GIF A+D TRXPOS/TRXREG/TRXDIR, IMAGE tag, data, two pad quadwords."""
    qwc = len(data)//16
    body = struct.pack('<12Q', 0, (0x50000000 | (qwc+7)) << 32, 0x1000000000008003, 0xE, 0, 0x51,
                       (rh << 32) | rw, 0x52, 0, 0x53, 0x0800000000008000 | qwc, 0)
    return body + data + bytes(32)


def tex0():
    """TEX0_1 of the private atlas: PSMT4 256x256, TBW 4, TCC, MODULATE, CT32 CLUT, CSM1, CSA 0, CLD 1."""
    return (TEX_TBP | (4 << 14) | (20 << 20) | (8 << 26) | (8 << 30) | (1 << 34) | (TEX_CBP << 37) | (1 << 61))


def font_descriptor(upload_len, clut_len):
    d = bytearray(64)
    struct.pack_into('<10I', d, 0, 0, 0, upload_len+0x80, clut_len+0x80, 0x202, 0x12, 2, 1, 0, 0)
    struct.pack_into('<Q', d, 48, tex0() & ~(0x3FFF | (0x3FFF << 37)))   # TBP/CBP come from the upload call
    struct.pack_into('<2I', d, 56, FONT_PIXELS, FONT_CLUT)
    return bytes(d)


def bundle(descriptor):
    b = bytearray(64)
    struct.pack_into('<I', b, 0, 2)
    struct.pack_into('<I', b, 16, descriptor)
    return bytes(b)


# ---------------------------------------------------------------- guest code
def _prologue(a):
    a.addiu(29, 29, -FRAME)
    for k, r in enumerate(REGS):
        a.i(63, r, 29, k*8)


def _epilogue(a):
    for k, r in enumerate(REGS):
        a.i(55, r, 29, k*8)
    a.addiu(29, 29, FRAME)
    a.jr()


SETUP_QW = 6
GLYPH_TAG = (4 | (1 << 46) | ((4 | 8 | 0x10 | 0x40 | 0x100) << 47) | (3 << 60), 0x531)


def setup_template():
    """A+D: TEX0_1, TEX1_1 (bilinear), CLAMP_1 (clamp), ALPHA_1, TEST_1, FBA_1; then the closing A+D tag."""
    regs = ((tex0(), 0x06), (0x60, 0x14), (5, 0x08), (0x44, 0x42), (0x30000, 0x47), (0, 0x4A))
    out = struct.pack('<2Q', len(regs) | (1 << 60), 0xE) + b''.join(struct.pack('<2Q', v, r) for v, r in regs)
    # Close: CLAMP_1 and TEX1_1 back to the HUD defaults, then TEX0_1 with CLD 2 and CLD 3. Those make the GS
    # remember OUR palette address as CBP0 and CBP1, so any later texture that loads its palette only when its
    # address differs from CBP0/CBP1 (CLD 4/5: the character models) reloads it instead of drawing with the
    # palette this packet left in the CLUT buffer.
    clut_reset = [(tex0() & ~(7 << 61)) | (k << 61) for k in (2, 3)]
    out += struct.pack('<2Q', len(CLOSE_REGS) | 0x8000 | (1 << 60), 0xE)
    out += b''.join(struct.pack('<2Q', v, r) for v, r in zip((5, 0, *clut_reset), CLOSE_REGS))
    return out


CLOSE_REGS = (0x08, 0x14, 0x06, 0x06)
CLOSE_BYTES = 16 + 16*len(CLOSE_REGS)


TEMPLATE_SETUP = TEMPLATES
TEMPLATE_CLOSE = TEMPLATES + 16*(1+SETUP_QW)
TEMPLATE_GLYPH = TEMPLATES + 0x100


WARM_BOTTOM, COOL_BOTTOM = (14, 8, 6), (11, 11, 11)   # sixteenths of R, G, B at the glyph's foot


def _gradient(a, src, top, bottom):
    """ABGR in src -> RGBAQ packed quadwords at sp+top (lighter) and sp+bottom (deeper). A warm colour (red above
    blue) deepens toward orange-red at the foot like the game's own lettering ("Lock on", "Hits!"); a cool or grey one
    only darkens."""
    a.i(12, 12, src, 255); a.r(2, 13, 0, src, 16); a.i(12, 13, 13, 255); a.r(0x2A, 12, 13, 12)   # t4 = B < R
    for ch in range(4):
        a.r(2, 8, 0, src, 8*ch)                      # srl t0, src, 8*ch
        a.i(12, 8, 8, 255)
        if ch == 3:
            a.sw(8, 29, top+12); a.sw(8, 29, bottom+12)
            continue
        a.addiu(9, 0, 255); a.r(0x23, 9, 9, 8)       # 255 - c
        a.r(24, 0, 9, 8); a.r(18, 9, 0)              # (255-c)*c  (mult, mflo)
        a.r(2, 9, 0, 9, 9); a.r(0x21, 9, 9, 8)       # top = c + (255-c)*c/512
        a.sw(9, 29, top+4*ch)
        tag = f'grad_{a.pc:x}'
        a.addiu(10, 0, COOL_BOTTOM[ch]); a.branch(4, 12, 0, tag); a.addiu(10, 0, WARM_BOTTOM[ch])
        a.label(tag)
        a.r(24, 0, 8, 10); a.r(18, 10, 0); a.r(2, 10, 0, 10, 4)   # bottom = c * k / 16
        a.sw(10, 29, bottom+4*ch)


FEED_TOP, FEED_EVENTS = 250, 3   # rows (one/two views): below the native combo counter (~134-194), the co-op
#                                  fusion captions (204-225) and the fusion timer (232-248); 3 events end above
#                                  the beam-struggle captions (130 rows above the bottom).


def feed_ranges():
    """Code ranges that call the text entry for kill feed lines: the feed's own draw code and its relocated copy."""
    import guest_killfeed as feed
    import display_settings as display
    return ((feed.DRAW, feed.TEXT), (display.FEED_DRAW, display.RECORD_NATIVE))


def feed_shift():
    from regional import screen_y
    return screen_y(FEED_TOP) - screen_y(106)          # guest_killfeed draws its first line at screen_y(106)


def feed_limit():
    """GS rows (12.4 / 16): a feed line whose top (shadow included) is below this is not drawn."""
    from regional import Y_ORIGIN, screen_y
    return Y_ORIGIN + screen_y(FEED_TOP) + 22*(FEED_EVENTS-1) + 9 + 1


def ntext_code():
    """NTEXT entries plus the shared body. Registers: s0 string, s1 pen x, s2 top y, s3 colour, s4 units/px,
    s5 packet pointer, s6 glyph count, s7 metrics row; fp shear."""
    a = Assembler(NTEXT)
    # Each classic entry names its trampoline in t2: with the style word 0 the call continues as classic.
    a.li(10, TRAMP['text']); a.addiu(8, 0, 8); a.addiu(11, 0, BIT['text']); a.jump('feed_check')   # NTEXT
    assert a.pc <= NTEXT_SMALL
    while a.pc < NTEXT_SMALL: a.emit(0)
    import quad_viewports as views
    a.li(10, TRAMP['small']); a.addiu(8, 0, 8); a.addiu(11, 0, BIT['text'])   # NTEXT_SMALL
    a.li(9, views.CONTROL); a.lw(12, 9); a.li(13, views.MAGIC); a.branch(5, 12, 13, 'styled')
    a.lw(12, 9, views.VIEW_COUNT); a.addiu(12, 12, -3); a.i(11, 12, 12, 2); a.branch(4, 12, 0, 'styled')
    a.addiu(8, 0, 6); a.jump('styled')
    assert a.pc <= NTEXT_75
    while a.pc < NTEXT_75: a.emit(0)
    # NTEXT_75: the tag caption (tag_rush_hud places it; no offset here).
    a.li(10, TRAMP['caption']); a.addiu(8, 0, 6); a.addiu(11, 0, BIT['tag']); a.jump('styled')
    assert a.pc <= NTEXT_SCALED
    while a.pc < NTEXT_SCALED: a.emit(0)
    a.move(10, 0)                                                         # NTEXT_SCALED (t0 = units)
    a.label('styled')
    a.li(9, CONTROL); a.lw(9, 9, 4); a.r(0x24, 9, 9, 11); a.branch(5, 9, 0, 'body'); a.branch(4, 10, 0, 'body')
    a.jr(10)
    a.label('body')
    _prologue(a)
    a.move(16, 4); a.move(17, 5); a.move(18, 6); a.move(19, 7); a.move(20, 8)
    a.li(9, CONTROL); a.lw(10, 9); a.li(11, MAGIC); a.branch(5, 10, 11, 'done')
    a.i(36, 9, 16, 0); a.branch(4, 9, 0, 'done')
    _gradient(a, 19, 0x50, 0x60)
    # Upload the private atlas into the portrait bank (uncached: native portraits upload before use).
    a.li(9, FONT_DESC); a.sw(0, 9, 0x28)
    a.li(4, FONT_BUNDLE); a.move(5, 0); a.move(6, 0); a.addiu(7, 0, TEX_TBP); a.addiu(8, 0, TEX_CBP)
    a.call(UPLOAD)
    a.call(A(0x100878)); a.move(21, 2)
    a.li(8, TEMPLATE_SETUP)
    for off in range(0, 16*(1+SETUP_QW), 8):
        a.i(55, 9, 8, off); a.i(63, 9, 21, off)
    a.addiu(21, 21, 16*(1+SETUP_QW))
    # Cap top at the caller's y: slot top = y - (MARGIN+CAP_TOP)*units.
    a.addiu(9, 0, MARGIN+CAP_TOP); a.r(24, 0, 9, 20); a.r(18, 9, 0); a.r(0x23, 18, 18, 9)
    a.addiu(9, 0, SHEAR); a.r(24, 0, 9, 20); a.r(18, 30, 0)                # fp = shear in GS units
    a.move(22, 0)
    a.label('char')
    a.i(36, 8, 16, 0); a.branch(4, 8, 0, 'finish')
    a.i(12, 8, 8, 127); a.r(0, 8, 0, 8, 4); a.li(9, METRICS); a.r(0x21, 23, 8, 9)
    a.i(36, 9, 23, 8)                                                     # slot width
    a.i(36, 10, 23, 9)                                                    # advance
    a.branch(4, 9, 0, 'advance')
    a.i(32, 11, 23, 10)                                                   # xoff (signed byte)
    a.r(24, 0, 11, 20); a.r(18, 11, 0); a.r(0x21, 11, 11, 17)             # x0
    a.r(24, 0, 9, 20); a.r(18, 12, 0); a.r(0x21, 12, 12, 11)              # x1
    a.addiu(13, 0, SLOT_H); a.r(24, 0, 13, 20); a.r(18, 13, 0); a.r(0x21, 13, 13, 18)   # y1
    a.li(14, TEMPLATE_GLYPH); a.i(55, 15, 14, 0); a.i(63, 15, 21, 0); a.i(55, 15, 14, 8); a.i(63, 15, 21, 8)
    a.addiu(21, 21, 16)
    a.i(37, 14, 23, 0); a.i(37, 15, 23, 2); a.i(37, 24, 23, 4); a.i(37, 25, 23, 6)   # u0 v0 u1 v1 (lhu)
    for colour, u, v, x, y, slant in ((0x50, 14, 15, 11, 18, True), (0x60, 14, 25, 11, 13, False),
                                      (0x50, 24, 15, 12, 18, True), (0x60, 24, 25, 12, 13, False)):
        a.i(55, 8, 29, colour); a.i(63, 8, 21, 0); a.i(55, 8, 29, colour+8); a.i(63, 8, 21, 8)
        a.sw(u, 21, 16); a.sw(v, 21, 20); a.i(63, 0, 21, 24)
        if slant:
            a.r(0x21, 8, x, 30); a.sw(8, 21, 32)
        else:
            a.sw(x, 21, 32)
        a.sw(y, 21, 36); a.i(63, 0, 21, 40)
        a.addiu(21, 21, 48)
    a.label('advance')
    a.r(24, 0, 10, 20); a.r(18, 10, 0); a.r(0x21, 17, 17, 10)
    a.addiu(16, 16, 1); a.addiu(22, 22, 1)
    a.addiu(9, 0, MAX_CHARS); a.branch(5, 22, 9, 'char')
    a.label('finish')
    a.li(8, TEMPLATE_CLOSE)
    for off in range(0, CLOSE_BYTES, 8):
        a.i(55, 9, 8, off); a.i(63, 9, 21, off)
    a.addiu(4, 21, CLOSE_BYTES); a.call(A(0x100890))
    a.li(9, CONTROL); a.lw(10, 9, 8); a.addiu(10, 10, 1); a.sw(10, 9, 8)
    a.label('done')
    _epilogue(a)
    # Kill feed lines (their caller is the feed's draw code): FEED_SHIFT rows lower, the fourth event left out.
    a.label('feed_check')
    for lo, hi in feed_ranges():
        a.li(9, lo); a.r(0x2B, 12, 31, 9); a.branch(5, 12, 0, f'not_feed_{lo:x}')
        a.li(9, hi); a.r(0x2B, 12, 31, 9); a.branch(5, 12, 0, 'feed_line')
        a.label(f'not_feed_{lo:x}')
    a.jump('styled')
    a.label('feed_line')
    a.li(9, feed_shift()*16); a.r(0x21, 6, 6, 9)
    a.li(9, feed_limit()*16); a.r(0x2B, 12, 9, 6); a.branch(4, 12, 0, 'styled')
    a.move(2, 0); a.jr()
    data = a.finish(); assert len(data) <= NART-NTEXT, len(data)
    return data


def templates():
    out = bytearray(0x200)
    s = setup_template(); out[:len(s)] = s
    struct.pack_into('<2Q', out, 0x100, *GLYPH_TAG)
    return bytes(out)


# ---------------------------------------------------------------- native art (private descriptor copies)
# name: (source, index, palette-only). Sources: 'hud' = the battle HUD bundle (*A(0x2FEB48)), 'combo' = the
# combo/word-art bundle (*A(0x2FEB58)), 'prompt' = the button-prompt bundle (*A(0x2FEB60)).
ART = (('hud8', 'hud', 8, False), ('hud8p1', 'hud', 9, True), ('hud8p2', 'hud', 10, True), ('hud8p3', 'hud', 11, True),
       ('hud8p4', 'hud', 12, True), ('hud8p5', 'hud', 13, True), ('frame', 'hud', 23, False),
       ('timer', 'hud', 0, False), ('panel', 'hud', 3, False), ('stock', 'hud', 15, False), ('glow', 'hud', 17, False),
       ('fist', 'hud', 19, False), ('bolt', 'hud', 20, False), ('swap', 'hud', 24, False),
       ('arrows', 'prompt', 8, False), ('lockon', 'combo', 5, False), ('hits', 'combo', 2, False),
       ('digits', 'combo', 1, False), ('bigdigits', 'combo', 0, False), ('burst', 'prompt', 0, False))
SLOT = {name: k for k, (name, *_rest) in enumerate(ART)}
# Expected (psm, width, height) of each piece; anything else is left out (its element keeps the classic look).
SHAPES = dict(hud8=(19, 256, 64), frame=(19, 128, 32), timer=(20, 128, 128), panel=(19, 64, 64), stock=(19, 64, 64),
              glow=(19, 64, 64), fist=(20, 32, 32), bolt=(20, 32, 32), swap=(19, 128, 32), arrows=(20, 64, 64),
              lockon=(19, 128, 64), hits=(19, 128, 64), digits=(20, 128, 128), bigdigits=(20, 128, 128),
              burst=(19, 64, 64))
def _bundle_pointer(source):
    """The native static holding each art bundle's manager (literal A() arguments for the regional maps)."""
    return {'hud': lambda: A(0x2FEB48), 'combo': lambda: A(0x2FEB58), 'prompt': lambda: A(0x2FEB60)}[source]()


def _bundle(ram, source):
    manager = _u32(ram, _bundle_pointer(source))
    if not 0x100000 <= manager < len(ram)-64:
        return None
    b = _u32(ram, manager)
    if not 0x100000 <= b < len(ram)-32 or not 0 < _u32(ram, b) < 65:
        return None
    return b


def art_pieces(ram):
    """(table bytes, data blocks [(address, bytes)], available names) of private copies of native art."""
    table = bytearray(len(ART)*64)
    data, cursor, available = [], ART_DATA, []
    for k, (name, source, index, palette_only) in enumerate(ART):
        b = _bundle(ram, source)
        if b is None or index >= _u32(ram, b):
            continue
        d = _u32(ram, b+16) + index*64
        if not 0x100000 <= d < len(ram)-64:
            continue
        desc = bytearray(ram[d:d+64])
        size, clut = _u32(ram, d+8), _u32(ram, d+12)
        if palette_only:
            size = 0
        else:
            tex = struct.unpack_from('<Q', desc, 48)[0]
            if (((tex >> 20) & 63), 1 << ((tex >> 26) & 15), 1 << ((tex >> 30) & 15)) != SHAPES.get(name):
                continue
        ok, pending = True, []
        for off, length in ((56, size), (60, clut)):
            src = _u32(ram, d+off)
            if not length:
                struct.pack_into('<I', desc, off, 0)
                continue
            if not (0x100000 <= src < len(ram)-length and length <= 0x10080 and length % 16 == 0):
                ok = False
                break
            if cursor + length > ART_END:
                ok = False
                break
            pending.append((cursor, bytes(ram[src:src+length])))
            struct.pack_into('<I', desc, off, cursor)
            cursor += (length + 15) & ~15
        if not ok:
            continue
        data += pending
        struct.pack_into('<2I', desc, 8, size, clut)
        struct.pack_into('<2I', desc, 32, 0, 0)
        struct.pack_into('<I', desc, 40, 0)
        table[k*64:k*64+64] = desc
        available.append(name)
    return bytes(table), data, available


def nart_code():
    """NART: a0 -> param block (slot, palette slot or -1, u0 v0 u1 v1 in texels*16, x0 y0 x1 y1 in GS 12.4,
    top ABGR, bottom ABGR, flags (bit0 nearest, bit1 no region clamp), shear in GS units)."""
    a = Assembler(NART)
    _prologue(a)
    a.move(16, 4)
    a.li(9, CONTROL); a.lw(10, 9); a.li(11, MAGIC); a.branch(5, 10, 11, 'done')
    a.lw(8, 16, 0); a.i(11, 9, 8, len(ART)); a.branch(4, 9, 0, 'done')
    a.r(0, 8, 0, 8, 6); a.li(9, ART_TABLE); a.r(0x21, 17, 8, 9)             # s1 = descriptor
    a.lw(8, 17, 8); a.branch(4, 8, 0, 'done')                              # unavailable piece
    a.li(18, ART_DESC)
    for off in range(0, 64, 8):
        a.i(55, 9, 17, off); a.i(63, 9, 18, off)
    a.i(63, 0, 18, 0x20); a.sw(0, 18, 0x28)
    a.move(6, 0)
    a.lw(8, 16, 4); a.branch(1, 8, 0, 'no_palette')                       # bltz: none
    a.i(11, 9, 8, len(ART)); a.branch(4, 9, 0, 'no_palette')
    a.r(0, 8, 0, 8, 6); a.li(9, ART_TABLE); a.r(0x21, 8, 8, 9)
    a.lw(9, 8, 12); a.branch(4, 9, 0, 'no_palette')
    for off in range(0, 64, 8):
        a.i(55, 9, 8, off); a.i(63, 9, 18, 64+off)
    a.i(63, 0, 18, 64+0x20); a.sw(0, 18, 64+0x28); a.addiu(6, 0, 1)
    a.label('no_palette')
    a.li(4, ART_BUNDLE); a.move(5, 0); a.addiu(7, 0, TEX_TBP); a.addiu(8, 0, TEX_CBP)
    a.call(UPLOAD)
    a.call(A(0x100878)); a.move(19, 2)
    # GIF tag: A+D x6 (TEX0, TEX1, CLAMP, ALPHA, TEST, FBA).
    a.addiu(8, 0, 6); a.sw(8, 19, 0); a.li(8, 1 << 28); a.sw(8, 19, 4)
    a.addiu(8, 0, 0xE); a.sw(8, 19, 8); a.sw(0, 19, 12)
    a.lw(8, 17, 48); a.li(9, 0xFFFFC000); a.r(0x24, 8, 8, 9); a.i(13, 8, 8, TEX_TBP); a.sw(8, 19, 16)
    a.lw(8, 17, 52); a.li(9, ~((0x3FFF << 5) | (7 << 29)) & 0xFFFFFFFF); a.r(0x24, 8, 8, 9); a.li(9, (TEX_CBP << 5) | (1 << 29) | 4)   # CBP, CLD 1, TCC (the texel alpha)
    a.r(0x25, 8, 8, 9); a.sw(8, 19, 20); a.addiu(8, 0, 0x06); a.i(63, 8, 19, 24)
    a.lw(8, 16, 48); a.i(12, 8, 8, 1); a.addiu(9, 0, 0x60); a.branch(4, 8, 0, 'filter'); a.move(9, 0)
    a.label('filter'); a.i(63, 9, 19, 32); a.addiu(8, 0, 0x14); a.i(63, 8, 19, 40)
    # CLAMP_1: region clamp around the source rectangle (no bleeding from neighbouring atlas cells).
    a.addiu(12, 0, 5); a.move(13, 0)
    a.lw(8, 16, 48); a.i(12, 8, 8, 2); a.branch(5, 8, 0, 'clamp_ready')
    for lo, hi, shift_lo, tag in ((8, 16, 4, 'u'), (12, 20, 24, 'v')):
        a.lw(8, 16, lo); a.lw(9, 16, hi)
        a.r(0x2A, 10, 9, 8); a.branch(4, 10, 0, tag+'_sorted'); a.move(10, 8); a.move(8, 9); a.move(9, 10)
        a.label(tag+'_sorted')
        a.r(2, 8, 0, 8, 4); a.addiu(9, 9, 15); a.r(2, 9, 0, 9, 4); a.addiu(9, 9, -1)
        if tag == 'u':
            a.addiu(12, 0, 0xA); a.r(0, 8, 0, 8, 4); a.r(0x25, 12, 12, 8); a.r(0, 9, 0, 9, 14); a.r(0x25, 12, 12, 9)
        else:
            a.i(12, 10, 8, 0xFF); a.r(0, 10, 0, 10, 24); a.r(0x25, 12, 12, 10)
            a.r(2, 13, 0, 8, 8); a.r(0, 9, 0, 9, 2); a.r(0x25, 13, 13, 9)
    a.label('clamp_ready')
    a.sw(12, 19, 48); a.sw(13, 19, 52); a.addiu(8, 0, 0x08); a.i(63, 8, 19, 56)
    for k, (value, reg) in enumerate(((0x44, 0x42), (0x30000, 0x47), (0, 0x4A))):
        a.li(8, value); a.i(63, 8, 19, 64+16*k); a.addiu(8, 0, reg); a.i(63, 8, 19, 72+16*k)
    a.addiu(19, 19, 16*7)
    a.li(14, TEMPLATE_GLYPH); a.i(55, 15, 14, 0); a.i(63, 15, 19, 0); a.i(55, 15, 14, 8); a.i(63, 15, 19, 8)
    a.addiu(19, 19, 16)
    # Colours: RGBAQ quadwords at sp+0x50 (top) and sp+0x60 (bottom).
    for src, dst in ((40, 0x50), (44, 0x60)):
        a.lw(9, 16, src)
        for ch in range(4):
            a.r(2, 8, 0, 9, 8*ch); a.i(12, 8, 8, 255); a.sw(8, 29, dst+4*ch)
    a.lw(30, 16, 52)
    a.lw(8, 16, 48); a.i(12, 9, 8, 8); a.branch(5, 9, 0, 'free')
    a.i(12, 8, 8, 4); a.branch(5, 8, 0, 'rotated')
    # Vertex order TL, BL, TR, BR; rotated (flag 4) maps the source a quarter turn clockwise; free (flag 8) takes
    # each vertex's (u, v) from the block (+56..+84: TL, BL, TR, BR), any affine turn of the source.
    for order in ('plain', 'rotated', 'free'):
        if order == 'rotated':
            a.label('rotated')
            uvs = ((8, 20), (16, 20), (8, 12), (16, 12))
        elif order == 'free':
            a.label('free')
            uvs = ((56, 60), (64, 68), (72, 76), (80, 84))
        else:
            uvs = ((8, 12), (8, 20), (16, 12), (16, 20))
        for (u, v), (colour, x, y, slant) in zip(uvs, ((0x50, 24, 28, True), (0x60, 24, 36, False),
                                                      (0x50, 32, 28, True), (0x60, 32, 36, False))):
            a.i(55, 8, 29, colour); a.i(63, 8, 19, 0); a.i(55, 8, 29, colour+8); a.i(63, 8, 19, 8)
            a.lw(8, 16, u); a.sw(8, 19, 16); a.lw(8, 16, v); a.sw(8, 19, 20); a.i(63, 0, 19, 24)
            a.lw(8, 16, x)
            if slant:
                a.r(0x21, 8, 8, 30)
            a.sw(8, 19, 32); a.lw(8, 16, y); a.sw(8, 19, 36); a.i(63, 0, 19, 40)
            a.addiu(19, 19, 48)
        if order != 'free':
            a.jump('vertices_done')
    a.label('vertices_done')
    a.li(8, TEMPLATE_CLOSE)
    for off in range(0, CLOSE_BYTES, 8):
        a.i(55, 9, 8, off); a.i(63, 9, 19, off)
    a.addiu(4, 19, CLOSE_BYTES); a.call(A(0x100890))
    a.li(9, CONTROL); a.lw(10, 9, 12); a.addiu(10, 10, 1); a.sw(10, 9, 12)
    a.label('done')
    _epilogue(a)
    data = a.finish(); assert NART + len(data) <= SITES, len(data)
    return data


ART_PARAMS = 88


def emit_art(a, frame, slot, uv, box, top=0x80808080, bottom=None, palette=-1, flags=0, shear=0, corners=None):
    """Fill a NART param block at sp+frame and call NART. uv: texels (ints) or ('r', n) registers already in
    texels*16; box: GS 12.4 values or ('r', n); top/bottom/shear: constants or ('r', n). Uses t0."""
    bottom = top if bottom is None else bottom

    def put(value, off, scale=1):
        if isinstance(value, tuple) and value[0] == 's':
            a.lw(8, 29, value[1]); a.sw(8, 29, frame+off)
        elif isinstance(value, tuple):
            a.sw(value[1], 29, frame+off)
        else:
            a.li(8, (value*scale) & 0xFFFFFFFF); a.sw(8, 29, frame+off)
    put(SLOT[slot] if isinstance(slot, str) else slot, 0)
    put(SLOT[palette] if isinstance(palette, str) else palette, 4)
    for k, value in enumerate(uv):
        put(value, 8+4*k, 16)
    for k, value in enumerate(box):
        put(value, 24+4*k)
    put(top, 40); put(bottom, 44); put(flags | (8 if corners else 0), 48); put(shear, 52)
    for k, (u, v) in enumerate(corners or ()):
        put(round(u*16), 56+8*k); put(round(v*16), 60+8*k)
    a.addiu(4, 29, frame); a.call(NART)


# ---------------------------------------------------------------- element helpers (called from patched sites)
HFRAME, HBLOCK = 0xC0, 0x50
TEAM_BLUE = 0x80FFBC48
# HUD atlas 8: the tall bevelled part of the native health gauge, and its black slanted backing.
GAUGE_UV = (66, 0, 156, 12)
BACKING_UV = (64, 48, 160, 60)
MIN_GAUGE = 5            # pixels: thinner classic bars are drawn this tall
GAUGE_WIDTH = CONTROL + 0x20   # the last track's width (GS units), for the following fill
# Last drawn anchors (GS 12.4), read by diagnostics: arrow tip x/y, ring centre x/y and radius, threat pair centre.
TELEMETRY = CONTROL + 0x40


def _hprologue(a):
    a.addiu(29, 29, -HFRAME)
    for k, r in enumerate(REGS):
        a.i(63, r, 29, k*8)


def _hepilogue(a):
    for k, r in enumerate(REGS):
        a.i(55, r, 29, k*8)
    a.addiu(29, 29, HFRAME)
    a.jr()


def _rect_in(a):
    """s0..s3 = a0..a3 (x0, y0, x1, y1 GS 12.4), s3 raised to at least MIN_GAUGE pixels; s4 = t0; s7 = slant."""
    for r, s in zip((16, 17, 18, 19, 20), (4, 5, 6, 7, 8)):
        a.move(r, s)
    a.addiu(9, 17, MIN_GAUGE*16); a.r(0x2A, 10, 19, 9); tag = f'tall_{a.pc:x}'; a.branch(4, 10, 0, tag); a.move(19, 9)
    a.label(tag)
    a.r(0x23, 23, 19, 17); a.r(3, 23, 0, 23, 1)              # slant: half the height


def _palette(a, colour, dest):
    """dest = a native gauge palette slot for a classic ABGR colour: blue-ish -> blue, bright yellow -> yellow,
    anything else -> orange."""
    tag = f'pal_{a.pc:x}'
    a.i(12, 8, colour, 255); a.r(2, 9, 0, colour, 8); a.i(12, 9, 9, 255); a.r(2, 10, 0, colour, 16); a.i(12, 10, 10, 255)
    a.addiu(dest, 0, SLOT['hud8p5'])
    a.i(10, 11, 10, 0xC0); a.branch(5, 11, 0, tag+'_not_blue')
    a.i(10, 11, 8, 0x80); a.branch(5, 11, 0, tag)
    a.label(tag+'_not_blue')
    a.addiu(dest, 0, SLOT['hud8p4'])
    a.i(10, 11, 8, 0xC0); a.branch(5, 11, 0, tag+'_orange')
    a.i(10, 11, 9, 0xC0); a.branch(4, 11, 0, tag)
    a.label(tag+'_orange')
    a.addiu(dest, 0, SLOT['hud8p3'])
    a.label(tag)


def _backing(a, x0, y0, x1, y1):
    emit_art(a, HBLOCK, 'hud8', BACKING_UV, (('r', x0), ('r', y0), ('r', x1), ('r', y1)), 0x60808080,
             shear=('r', 23))


def _bar_back(a):
    """A classic outline rectangle (one pixel around the bar) -> the native gauge's black slanted backing."""
    _rect_in(a)
    a.addiu(18, 18, 16)
    _backing(a, 16, 17, 18, 19)


def _bar_track(a):
    """A classic track -> the empty native gauge (atlas 8, palette 0); remembers its width for the fill."""
    _rect_in(a)
    a.r(0x23, 8, 18, 16); a.li(9, GAUGE_WIDTH); a.sw(8, 9, 0)
    emit_art(a, HBLOCK, 'hud8', GAUGE_UV, (('r', 16), ('r', 17), ('r', 18), ('r', 19)), 0x80808080,
             shear=('r', 23))


def _gauge_fill(a, width=None, palette=None):
    """Fill rectangle s0..s3 of a gauge `width` GS units wide (default: the last track's): the native gauge, its
    texture cut at the same fraction so the bevel and slanted end stay intact."""
    if width is None:
        a.li(9, GAUGE_WIDTH); a.lw(9, 9, 0)
    else:
        a.li(9, width)
    tag = f'fill_{a.pc:x}'
    a.branch(4, 9, 0, tag+'_done')
    a.r(0x23, 21, 18, 16); a.addiu(10, 0, (GAUGE_UV[2]-GAUGE_UV[0])*16); a.r(24, 0, 21, 10); a.r(18, 21, 0)
    a.r(27, 0, 21, 9); a.r(18, 21, 0); a.addiu(21, 21, GAUGE_UV[0]*16)
    if palette is None:
        _palette(a, 20, 22)
    else:
        a.addiu(22, 0, SLOT[palette])
    emit_art(a, HBLOCK, 'hud8', (GAUGE_UV[0], GAUGE_UV[1], ('r', 21), GAUGE_UV[3]),
             (('r', 16), ('r', 17), ('r', 18), ('r', 19)), 0x80808080, palette=('r', 22), shear=('r', 23))
    a.label(tag+'_done')


def _bar_fill(a):
    """A classic fill (t0 its colour) -> the native gauge in the matching palette."""
    _rect_in(a)
    _gauge_fill(a)


def _gauge120(a, palette=None):
    """A lone classic progress bar (fusion timer, revival channel: fill only, at most 120 px in every view) ->
    backing, empty 120 px gauge and native fill (clamped to the track)."""
    _rect_in(a)
    a.li(9, 120*16)
    a.r(0x21, 10, 16, 9); a.r(0x2A, 11, 10, 18); a.branch(4, 11, 0, f'fill_inside_{palette}'); a.move(18, 10)
    a.label(f'fill_inside_{palette}')
    a.li(10, GAUGE_WIDTH); a.sw(9, 10, 0)
    a.r(0x21, 9, 16, 9); a.sw(9, 29, T0)
    a.addiu(8, 16, -16); a.sw(8, 29, T1); a.addiu(8, 17, -16); a.sw(8, 29, T2); a.lw(8, 29, T0); a.addiu(8, 8, 32)
    a.sw(8, 29, T3); a.addiu(8, 19, 16); a.sw(8, 29, 0xB8)
    emit_art(a, HBLOCK, 'hud8', BACKING_UV, (('s', T1), ('s', T2), ('s', T3), ('s', 0xB8)),
             0x60808080, shear=('r', 23))
    emit_art(a, HBLOCK, 'hud8', GAUGE_UV, (('r', 16), ('r', 17), ('s', T0), ('r', 19)), 0x80808080, shear=('r', 23))
    _gauge_fill(a, palette=palette)


def _beam_caption(a):
    """beam_struggle's caption (its four black outline passes are sunk): an assist's 'BEAM ASSIST Xm' half again as
    large in gold, a failure in red, the R3 hint as given."""
    import beam_struggle as bs
    a.move(4, 4)
    a.addiu(8, 0, 8)
    a.li(9, bs.TEXT); a.r(0x2B, 10, 4, 9); a.branch(5, 10, 0, 'beam_plain')
    a.li(9, bs.HINT_TEXT); a.r(0x2B, 10, 4, 9); a.branch(4, 10, 0, 'beam_not_bonus')
    a.addiu(8, 0, 12); a.li(7, 0x8030C8FF); a.jump('beam_plain')
    a.label('beam_not_bonus')
    a.li(9, bs.FAIL_TEXT); a.r(0x2B, 10, 4, 9); a.branch(5, 10, 0, 'beam_plain')
    a.li(7, 0x803848FF)
    a.label('beam_plain')
    a.call(NTEXT_SCALED)


BAR_HELPERS = (('beam_caption', _beam_caption), ('bar_back', _bar_back), ('bar_track', _bar_track), ('bar_fill', _bar_fill),
               ('gauge120', _gauge120), ('revive_gauge', lambda a: _gauge120(a, 'hud8p1')),
               # The tag meter keeps its own group bit; tag_rush_hud places it (below the subject's own gauge).
               ('tag_back', _bar_back), ('tag_track', _bar_track), ('tag_fill', _bar_fill))


def _passthrough(a, target, tag, bit):
    """With the element's bit clear in the style word (classic), continue at the classic target with every argument
    untouched."""
    a.li(9, CONTROL); a.lw(9, 9, 4); a.i(12, 9, 9, bit); a.branch(5, 9, 0, 'native_'+tag); a.jump(target)
    a.label('native_'+tag)


def trampolines(ram):
    """{name: 16 bytes}: each classic text entry's first two instructions and a jump to the instruction after."""
    import guest_killfeed as feed
    out = {}
    sites = dict(text=feed.TEXT, small=feed.SMALL_TEXT)
    try:
        import tag_rush_hud as tag
        sites['caption'] = tag.CAPTION
    except ImportError:
        pass
    for name, site in sites.items():
        head = bytes(ram[site:site+8])
        if _u32(ram, site) and head[:4] not in [struct.pack('<I', (2 << 26) | (t >> 2)) for t in (NTEXT, NTEXT_SMALL, NTEXT_75)]:
            out[name] = head + struct.pack('<2I', (2 << 26) | ((site+8) >> 2), 0)
    return out


# The style word (CONTROL+4) holds one bit per element group; a clear bit draws that group the classic way. The
# installation sets every bit except 'lockon' when the target marker look is classic (style_word); online each PC
# writes its own target look into its copy (kit_settings LOCAL 'lockon_target_look').
BIT = dict(text=1, bars=2, lockon=4, threat=8, tag=16, gauges=32, beam=64)
ALL_BITS = 0x7F
GROUP = dict(beam_caption='beam', bar_back='bars', bar_track='bars', bar_fill='bars', gauge120='gauges',
             revive_gauge='gauges', tag_back='tag', tag_track='tag', tag_fill='tag', arrow_begin='lockon',
             ring_begin='lockon', threat_pair='threat', threat_edge='threat')


def _helpers():
    a = Assembler(HELPERS)
    entries = {}
    import guest_killfeed as feed
    import guest_healthbars as bars
    classic = dict(beam_caption=feed.TEXT, bar_back=bars.RECT, bar_track=bars.RECT, bar_fill=bars.RECT,
                   gauge120=bars.RECT, revive_gauge=bars.RECT, tag_back=bars.RECT, tag_track=bars.RECT,
                   tag_fill=bars.RECT)
    classic.update({name: A(0x100878) for name, _body in MARKER_HELPERS})
    for name, body in BAR_HELPERS + MARKER_HELPERS:
        entries[name] = a.pc
        _passthrough(a, classic[name], name, BIT[GROUP[name]])
        _hprologue(a); body(a)
        if name in dict(MARKER_HELPERS):
            for k, r in enumerate(REGS):
                a.i(55, r, 29, k*8)
            a.addiu(29, 29, HFRAME); _sink_return(a); a.jr()
        else:
            _hepilogue(a)
    for name, target, group in (('sink_lockon', A(0x100890), 'lockon'), ('sink_threat', A(0x100890), 'threat'),
                                ('sink_text', feed.TEXT, 'beam')):
        entries[name] = a.pc
        _passthrough(a, target, name, BIT[group])
        a.jr()
    data = a.finish(); assert len(data) <= SAMPLING - HELPERS, len(data)
    return data, entries


def helpers_code():
    return _helpers()[0]


def helper(name):
    return _helpers()[1][name]


def _jal(target):
    return struct.pack('<I', (3 << 26) | (target >> 2))


def _calls(ram, start, end, target):
    word = _jal(target)
    return [p for p in range(start, end, 4) if ram[p:p+4] == word]


# The native art each element needs; an element whose art is not resident keeps its classic drawing.
NEEDS = dict(text=(), healthbars=('hud8', 'hud8p3', 'hud8p5'), tag_meter=('hud8', 'hud8p3', 'hud8p4', 'hud8p5'),
             fusion_timer=('hud8', 'hud8p3', 'hud8p4', 'hud8p5'), revive=('hud8', 'hud8p1'),
             beam_caption=(), lockon=('arrows', 'lockon'), threat=('arrows', 'hits'))


def available_patches(ram, available):
    return [(p, d, e) for p, d, e in overlay_patches(ram) if all(name in available for name in NEEDS[e])]


def overlay_patches(ram):
    """Patches re-pointing the installed classic draw calls to the native helpers: [(address, bytes, element)]."""
    import guest_killfeed as feed
    import guest_healthbars as bars
    out = []
    jump = lambda t: struct.pack('<2I', (2 << 26) | (t >> 2), 0)
    if _u32(ram, feed.TEXT) != 0:
        out.append((feed.TEXT, jump(NTEXT), 'text'))
    if _u32(ram, feed.SMALL_TEXT) != 0:
        out.append((feed.SMALL_TEXT, jump(NTEXT_SMALL), 'text'))
    try:
        import tag_rush_hud as tag
        if _u32(ram, tag.CAPTION) != 0:
            out.append((tag.CAPTION, jump(NTEXT_75), 'text'))
    except ImportError:
        pass
    import display_settings as display
    # Only display_settings' BAR_DRAW: the original bars.DRAW is dead once the wrapper calls BAR_DRAW, and battle
    # mode checks (free-for-all rematch) compare it byte for byte.
    for start, end in ((display.BAR_DRAW, display.FEED_DRAW),):
        sites = _calls(ram, start, end, bars.RECT)
        if len(sites) == 3:
            for site, name in zip(sites, ('bar_back', 'bar_track', 'bar_fill')):
                out.append((site, _jal(helper(name)), 'healthbars'))
    try:
        import tag_rush_hud as tag
        sites = _calls(ram, tag.DRAW, tag.ALIVE, bars.RECT)
        if len(sites) == 3:
            for site, name in zip(sites, ('tag_back', 'tag_track', 'tag_fill')):
                out.append((site, _jal(helper(name)), 'tag_meter'))
    except ImportError:
        pass
    import fusion_duration as timer
    import teammate_revive as revive
    for start, end, name, element in ((timer.DRAW, timer.DRAW+0x1800, 'gauge120', 'fusion_timer'),
                                      (revive.DRAW, revive.TEXT, 'revive_gauge', 'revive')):
        sites = _calls(ram, start, end, bars.RECT)
        if len(sites) == 1:
            out.append((sites[0], _jal(helper(name)), element))
    import beam_struggle as bs
    sites = _calls(ram, bs.DRAW, bs.ASSIST, feed.TEXT)
    if len(sites) == 5:
        for site in sites[:4]:
            out.append((site, _jal(helper('sink_text')), 'beam_caption'))
        out.append((sites[4], _jal(helper('beam_caption')), 'beam_caption'))
    import lockon_select as sel
    import lockon_threat as thr
    for start, end, names in ((sel.MARKER, sel.SEG, ('arrow_begin', 'ring_begin')),
                              (thr.DRAW, thr.ENTRY, ('threat_pair', 'threat_edge'))):
        begins, ends = _calls(ram, start, end, A(0x100878)), _calls(ram, start, end, A(0x100890))
        if len(begins) == 2 and len(ends) == 2 and begins[0] < ends[0] < begins[1] < ends[1]:
            element = 'lockon' if start == sel.MARKER else 'threat'
            for site, name in zip(begins, names):
                out.append((site, _jal(helper(name)), element))
            for site in ends:
                out.append((site, _jal(helper('sink_'+element)), element))
    return out


# ---------------------------------------------------------------- lock-on and threat markers (packet hooks)
# The classic marker code allocates a GS packet (jal 100878), writes its triangles and submits it (jal 100890).
# In the Native style those two calls are re-pointed: the first to a helper that draws the native art from the
# values the classic code has just computed (its stack words) and returns a private sink buffer for the classic
# triangles, the second to SINK, so the classic packet is built but never submitted.
SINK_BUFFER, SINK_END = BASE + 0x2C000, END
PIP_UV = (0, 16, 8, 24)            # atlas 8: the native health-layer pip (a bevelled chevron pointing right)
ARROWS_UV = (0, 0, 64, 64)         # the native four-arrow reticle (tips about 7.5 texels from its centre)
LOCKON_UV = (24, 7, 104, 27)       # the native "Lock on" lettering
FIST_UV = (14, 32, 52, 64)         # the red fist burst beside the native "Hits!" counter
T0, T1, T2, T3 = 0xA8, 0xAC, 0xB0, 0xB4   # helper stack temporaries (inside HFRAME)
LOCKON_FLASH = 36                  # queue updates the "Lock on" lettering shows after a new target (1.2 s)


ARROW_CENTRE, ARROW_REACH, ARROW_ANGLE = (17.2, 18.2), 16.4, 45   # the reticle's top-left arrow (pointing down-right)


def arrow_corners(angle):
    """Source (u, v) of the TL, BL, TR, BR destination corners that turn the native reticle arrow to point at
    `angle` degrees (0 right, 90 down): an affine quarter-diamond around the arrow, inside its own quadrant."""
    import math
    t = math.radians(ARROW_ANGLE - angle)
    c, s_ = math.cos(t), math.sin(t)
    h = ARROW_REACH/math.sqrt(2)
    out = []
    for dx, dy in ((-h, -h), (-h, h), (h, -h), (h, h)):
        out.append((ARROW_CENTRE[0] + dx*c - dy*s_, ARROW_CENTRE[1] + dx*s_ + dy*c))
    return tuple(out)


ARROW_BOX = (0, 0, 32, 32)


def _sink_return(a):
    a.li(2, SINK_BUFFER)


def _arrow_begin(a):
    """Lock-on arrow: caller s4 = tip (y << 16 | x, GS 12.4), caller sp+M_AGE = updates since the target changed."""
    import lockon_select as sel
    caller = HFRAME
    a.i(12, 16, 20, 0xFFFF); a.r(2, 17, 0, 20, 16)                   # s0 tip x, s1 tip y
    a.li(8, TELEMETRY); a.sw(16, 8, 0); a.sw(17, 8, 4)
    # The native reticle arrow turned to point down (18 px), its point on the tip.
    a.addiu(18, 16, -11*16); a.addiu(19, 16, 11*16); a.addiu(20, 17, -21*16-8); a.addiu(21, 17, 8)
    emit_art(a, HBLOCK, 'arrows', ARROW_BOX, (('r', 18), ('r', 20), ('r', 19), ('r', 21)), 0x80808080,
             corners=arrow_corners(90))
    # The game's own "Lock on" lettering above it for a moment after each new target.
    a.lw(8, 29, caller+sel.M_AGE); a.i(11, 9, 8, LOCKON_FLASH); a.branch(4, 9, 0, 'arrow_done')
    a.addiu(18, 16, -30*16); a.addiu(19, 16, 30*16); a.addiu(20, 17, -31*16); a.addiu(21, 17, -16*16)
    emit_art(a, HBLOCK, 'lockon', LOCKON_UV, (('r', 18), ('r', 20), ('r', 19), ('r', 21)), 0x80808080)
    a.label('arrow_done')


def _ring_begin(a):
    """Lock-on ring: caller sp+M_X/M_Y = centre (GS 12.4), M_RADIUS (sixteenths), M_COLOUR (chevron colour)."""
    import lockon_select as sel
    caller = HFRAME
    a.lw(16, 29, caller+sel.M_X); a.lw(17, 29, caller+sel.M_Y); a.lw(18, 29, caller+sel.M_RADIUS)
    a.li(8, TELEMETRY); a.sw(16, 8, 8); a.sw(17, 8, 12); a.sw(18, 8, 16)
    # The arrows' tips (7.5 texels from the texture centre) at 0.95 r: half size = r * 32 / 7.5 * 0.95 ~ r * 4.
    a.r(0, 19, 0, 18, 2)
    # The game's reticle keeps a modest screen size: half-size clamped to 18..48 pixels (the arrows' tips at 0.95 r
    # for an ordinary target, never a screen-filling reticle for a target next to the camera).
    for bound, test, tag in ((18*16, 0x2A, 'ring_min'), (48*16, None, 'ring_max')):
        a.addiu(8, 0, bound)
        if test:
            a.r(0x2A, 9, 19, 8)
        else:
            a.r(0x2A, 9, 8, 19)
        a.branch(4, 9, 0, tag); a.move(19, 8)
        a.label(tag)
    a.r(0x23, 20, 16, 19); a.r(0x21, 21, 16, 19); a.r(0x23, 22, 17, 19); a.r(0x21, 23, 17, 19)
    a.lw(8, 29, caller+sel.M_COLOUR); a.li(9, sel.CHEV); a.li(10, 0x80808080); a.branch(4, 8, 9, 'tint')
    a.li(9, 0x00FFFFFF); a.r(0x24, 10, 8, 9); a.li(9, 0x80000000); a.r(0x25, 10, 10, 9)
    a.label('tint')
    a.move(30, 10)
    emit_art(a, HBLOCK, 'arrows', ARROWS_UV, (('r', 20), ('r', 22), ('r', 21), ('r', 23)), ('r', 30))


THREAT_RED, THREAT_WARN = 0x80181890, 0x80808080   # modulate tints of the native arrow: red, untinted yellow


def _threat_tint(a, caller, dest):
    """dest = red, or (while it attacks you, on the blink's warning frames) the arrow's own yellow."""
    import lockon_threat as thr
    tag = f'tint_{a.pc:x}'
    a.li(dest, THREAT_RED)
    a.lw(8, 29, caller+thr.D_COLOUR); a.li(9, thr.WARN_A); a.branch(5, 8, 9, tag)
    a.li(dest, THREAT_WARN)
    a.label(tag)


def _threat_pair(a):
    """Threat marks around an enemy that targets you: caller sp+D_X16/D_Y16 centre, D_TIP (sixteenths from the
    centre to each tip), D_SCALE (Q8 of 14 x 18 px), D_COLOUR: two native arrows pointing in at it, red (blinking
    yellow while it attacks you), and the native red fist above it while it attacks."""
    import lockon_threat as thr
    caller = HFRAME
    a.lw(16, 29, caller+thr.D_X16); a.lw(17, 29, caller+thr.D_Y16); a.lw(18, 29, caller+thr.D_TIP)
    a.li(8, TELEMETRY); a.sw(16, 8, 20); a.sw(17, 8, 24)
    a.lw(8, 29, caller+thr.D_SCALE); a.addiu(9, 0, 30*16); a.r(24, 0, 8, 9); a.r(18, 19, 0); a.r(3, 19, 0, 19, 8)   # s3 size
    a.r(3, 20, 0, 19, 1)                                                                                         # s4 half
    _threat_tint(a, caller, 22)
    a.r(0x23, 21, 17, 20); a.r(0x21, 23, 17, 20)
    # The arrow's point sits about 0.47 of its size from the box centre (arrow_corners), so each box is placed with
    # its pointing edge at the classic chevron's tip.
    a.r(0x23, 9, 16, 18); a.r(0x23, 8, 9, 19); a.sw(8, 29, T0); a.sw(9, 29, T1)
    a.r(0x21, 9, 16, 18); a.r(0x21, 8, 9, 19); a.sw(9, 29, T2); a.sw(8, 29, T3)
    emit_art(a, HBLOCK, 'arrows', ARROW_BOX, (('s', T0), ('r', 21), ('s', T1), ('r', 23)), ('r', 22),
             corners=arrow_corners(0))
    emit_art(a, HBLOCK, 'arrows', ARROW_BOX, (('s', T2), ('r', 21), ('s', T3), ('r', 23)), ('r', 22),
             corners=arrow_corners(180))
    a.lw(8, 29, caller+thr.D_ISWARN); a.branch(4, 8, 0, 'pair_done')
    a.r(0x23, 20, 17, 18); a.addiu(20, 20, -28*16); a.addiu(21, 20, 17*16); a.addiu(18, 16, -10*16); a.addiu(19, 16, 10*16)
    emit_art(a, HBLOCK, 'hits', FIST_UV, (('r', 18), ('r', 20), ('r', 19), ('r', 21)), 0x80808080)
    a.label('pair_done')


def _threat_edge(a):
    """Off-screen threat: one native arrow at sp+D_X16/D_Y16 pointing D_ORIENT (0 right, 1 left, 2 down, 3 up)."""
    import lockon_threat as thr
    caller = HFRAME
    a.lw(16, 29, caller+thr.D_X16); a.lw(17, 29, caller+thr.D_Y16); a.lw(18, 29, caller+thr.D_ORIENT)
    a.lw(8, 29, caller+thr.D_SCALE); a.addiu(9, 0, 14*16); a.r(24, 0, 8, 9); a.r(18, 19, 0); a.r(3, 19, 0, 19, 8)
    _threat_tint(a, caller, 22)
    a.r(0x23, 20, 16, 19); a.r(0x21, 21, 16, 19); a.r(0x23, 23, 17, 19); a.r(0x21, 30, 17, 19)
    for k, angle in enumerate((0, 180, 90, 270)):
        a.addiu(8, 0, k); a.branch(5, 18, 8, f'edge_{k}')
        emit_art(a, HBLOCK, 'arrows', ARROW_BOX, (('r', 20), ('r', 23), ('r', 21), ('r', 30)), ('r', 22),
                 corners=arrow_corners(angle))
        a.label(f'edge_{k}')


MARKER_HELPERS = (('arrow_begin', _arrow_begin), ('ring_begin', _ring_begin), ('threat_pair', _threat_pair),
                  ('threat_edge', _threat_edge))


def style_word(settings=None):
    """Every element group native, except the target marker when its look is set to classic."""
    return ALL_BITS if target_look(settings) == 'native' else ALL_BITS & ~BIT['lockon']


def control_block(enabled=True, style=ALL_BITS):
    c = bytearray(0x100)
    struct.pack_into('<I', c, 0, MAGIC if enabled else 0)
    struct.pack_into('<I', c, 4, style)
    return bytes(c)


def pieces(ram, style=ALL_BITS):
    """Guest blocks of the shared kit for this RAM (font copied from the resident native font)."""
    upload, rw, rh, clut, metrics, info = build_atlas(ram)
    table, art, available = art_pieces(ram)
    blocks = [(NTEXT, ntext_code()), (NART, nart_code()), (HELPERS, helpers_code()), (CONTROL, control_block(style=style)),
              (FONT_BUNDLE, bundle(FONT_DESC)), (FONT_DESC, font_descriptor(len(upload), len(clut))),
              (ART_BUNDLE, bundle(ART_DESC)), (METRICS, metrics), (TEMPLATES, templates()),
              (FONT_PIXELS, _packet(upload, rw, rh)), (FONT_CLUT, _packet(clut, 16, 16)), (ART_TABLE, table)] + art
    blocks += [(TRAMP[name], data) for name, data in trampolines(ram).items()]
    info['art'] = available
    return blocks, info


# ---------------------------------------------------------------- installation
LOOK_KEY = 'lockon_target_look'        # the target arrow / ring: the only element with a classic choice left
LOOKS = ('classic', 'native')


def target_look(settings):
    look = (settings or {}).get(LOOK_KEY, 'native')
    return look if look in LOOKS else 'native'


def _blocks(ram, pieces_):
    return [dict(address=p, expected_hex=bytes(ram[p:p+len(d)]).hex(), data_hex=bytes(d).hex()) for p, d in pieces_]


def build_memory(ram, settings=None, source='<prepared>'):
    """The shared kit plus the re-pointed classic call sites, for every match.

    The kit's font and art are copies of what the game itself has resident in this RAM; without the resident font
    (or without a captured 128 MiB image) the match keeps the classic drawing (no blocks) rather than failing its
    preparation."""
    if len(ram) != 0x8000000:
        return dict(blocks=[], skipped='no captured 128 MiB RAM')
    import native_hud_sampling as sampling
    assert sampling.BASE == SAMPLING and sampling.END <= SINK_BUFFER
    if _u32(ram, CONTROL) == MAGIC and installed_sites(ram):
        # Already installed (a re-preparation of the same match): keep the kit, its runtime words and the site
        # table recorded from the classic code; recomputing from the patched RAM would lose the classic words.
        # Older prepared matches can acquire the isolated atlas clamp without
        # rebuilding their fonts, resetting their settings or changing any art.
        extra = sampling.plan(ram, reservation_owned=True)
        blocks = extra['pieces'] + extra['patches']
        if extra.get('installed'):
            previous = installed_sites(ram)
            addresses = {p for p, _word in previous}
            missing = [(sampling.HOOK + 4*k, word) for k, word in
                       enumerate(struct.unpack('<2I', sampling.ORIGINAL)) if sampling.HOOK + 4*k not in addresses]
            if missing:
                blocks.append((SITES, sites_table(ram, [], previous + missing)))
        return dict(blocks=_blocks(ram, blocks), status='NATIVE HUD STYLE (already installed)',
                    sampling=extra.get('skipped', 'atlas cells isolated'))
    if any(ram[BASE:END]):
        raise ValueError('Native HUD style reservation occupied')
    try:
        kit, info = pieces(ram, style_word(settings))
    except (ValueError, struct.error, TypeError, KeyError, IndexError) as error:
        # A missing or unexpected resident font or art keeps the classic look; the match is unaffected.
        return dict(blocks=[], skipped=str(error) or type(error).__name__)
    chosen = available_patches(ram, info['art'])
    patches = [(p, d) for p, d, _element in chosen]
    extra = sampling.plan(ram, reservation_owned=True)
    kit += extra['pieces']; patches += extra['patches']
    info['sampling'] = extra.get('skipped', 'atlas cells isolated')
    table = sites_table(ram, patches)
    return dict(blocks=_blocks(ram, kit + patches + [(SITES, table)]), status='NATIVE HUD STYLE',
                elements=sorted({e for _p, _d, e in chosen}), info=info)


def sites_table(ram, patches, previous=()):
    """The SITES block: every patched word's address and its classic value (classic_view restores them)."""
    records = list(previous)
    for p, d in patches:
        for k in range(0, len(d), 4):
            records.append((p+k, _u32(ram, p+k)))
    if len(records) > SITES_MAX:
        raise ValueError('Too many native HUD style sites')
    return struct.pack('<I', len(records)) + b''.join(struct.pack('<2I', a, w) for a, w in records)


def installed_sites(ram):
    if len(ram) < END or _u32(ram, CONTROL) != MAGIC:
        return []
    n = _u32(ram, SITES)
    if n > SITES_MAX:
        return []
    raw = bytes(ram[SITES+4:SITES+4+8*n])
    return [struct.unpack_from('<2I', raw, 8*k) for k in range(n)]


def classic_view(ram):
    """`ram` as the classic HUD would have it: every word the native style re-pointed holds its classic value again.
    Validators of the classic programs read through this, so a native match passes the same checks (same object
    returned when the native style is not installed)."""
    sites = installed_sites(ram)
    if not sites:
        return ram
    if hasattr(ram, 'view') and hasattr(ram, 'fetched'):
        # lazy_ram.LazyRam: never copy (unfetched chunks would read as poison); an override view instead.
        return ram.view({address: struct.pack('<I', word) for address, word in sites})
    view = bytearray(ram)
    for address, word in sites:
        struct.pack_into('<I', view, address, word)
    return view


def dependency_override(ram, at, expected):
    """`expected` (classic bytes another module's strict check wants at `at`) as this match really holds them: each
    re-pointed word inside it is replaced by the installed one when `expected` has the recorded classic word."""
    sites = installed_sites(ram)
    if not sites:
        return expected
    out = bytearray(expected)
    for address, word in sites:
        k = address - at
        if 0 <= k and k+4 <= len(out) and struct.unpack_from('<I', out, k)[0] == word:
            out[k:k+4] = bytes(ram[address:address+4])
    return bytes(out)


def splice_plan(ram, plan):
    """A later plan (the tag-rush install) composed onto `ram`, with its classic tag caption and meter re-pointed
    to the kit when the kit is installed. The patches land inside the plan's own blocks (never a second block)."""
    if len(ram) < END or _u32(ram, CONTROL) != MAGIC or not plan.get('blocks'):
        return plan
    virtual = bytearray(ram)
    for b in plan['blocks']:
        p = int(b['address'], 0) if isinstance(b['address'], str) else b['address']
        data = bytes.fromhex(b['data_hex']); virtual[p:p+len(data)] = data
    table_ = bytes(ram[ART_TABLE:ART_TABLE+64*len(ART)])
    available = [name for k, (name, *_r) in enumerate(ART) if any(table_[64*k:64*k+64])]
    import tag_rush_hud as tag
    found = [(p, d, e) for p, d, e in available_patches(virtual, available) if e in ('text', 'tag_meter')]
    meter = [(p, d) for p, d, e in found if e == 'tag_meter']
    # The caption moves under the native partner panel with its meter: never one without the other.
    patches = meter + ([(p, d) for p, d, e in found if e == 'text' and p == tag.CAPTION] if meter else [])
    recorded = {a for a, _w in installed_sites(ram)}
    out = []
    tramp = trampolines(virtual).get('caption')
    if tramp and patches and not any(ram[TRAMP['caption']:TRAMP['caption']+16]):
        out.append(dict(address=TRAMP['caption'], expected_hex=bytes(16).hex(), data_hex=tramp.hex()))
    applied = []
    for b in plan['blocks']:
        b = dict(b)
        p = int(b['address'], 0) if isinstance(b['address'], str) else b['address']
        data = bytearray.fromhex(b['data_hex'])
        for site, word in patches:
            if p <= site and site+len(word) <= p+len(data) and data[site-p:site-p+len(word)] != word:
                if site not in recorded:
                    applied.append((site, bytes(word)))
                data[site-p:site-p+len(word)] = word
        b['data_hex'] = data.hex()
        out.append(b)
    if applied:
        table = sites_table(virtual, applied, installed_sites(ram))
        out.append(dict(address=SITES, expected_hex=bytes(ram[SITES:SITES+len(table)]).hex(), data_hex=table.hex()))
    return dict(plan, blocks=out)
