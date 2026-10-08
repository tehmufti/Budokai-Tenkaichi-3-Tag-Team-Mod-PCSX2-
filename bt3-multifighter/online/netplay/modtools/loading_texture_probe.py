"""Live texture probe for the UNCHANGED v3 loading guest (Ki Storm port, Phase 0c).

The v3 payload copies packet A verbatim into the native GIF arena (one DMA
CNT + VIF1 DIRECT allocation, GIF path 2) and only checks its size, so a packet
that carries IMAGE uploads, CLUTs and textured sprites validates the GS side of
PORT-SPEC 5.1 before a single guest instruction changes: IMAGE transfers over
path 2, the TEX0/CLUT/TEST/ALPHA/CLAMP words, and the VRAM placement (BG_TBP
0x2D00, FG_TBP 0x3080, CLUTs 0x3440/0x3444) against everything the game keeps
resident (spec section 8).

Running the probe (the user drives the emulator; nothing here touches it):
  1. In the shell that starts the launcher set the variable, e.g. PowerShell
     `$env:BT3_LOADING_PROBE = '1'` (cmd: `set BT3_LOADING_PROBE=1`).
     launch-autopilot.ps1 starts the watcher with Start-Process, which
     inherits the environment, and `guest_loading_screen.render()` then
     returns this probe instead of the loading artwork.
  2. Start the launcher as usual and start any match. While the cover is up
     compare the TV with analysis/loading-redesign-v4/captures/
     texture-probe-expected.png (written by `--preview`): the gradient,
     nebula, stars, grid, colour bars and title must be crisp and in the right
     colours (IMAGE path, CLUT swizzle, TEX0); the white foreground title,
     the two portraits and the 1 px outline must sit over the background; the
     four red squares must fade 100/75/50/25 % (ALPHA 0x44 with CLUT alpha);
     the window cut into the blue panel must show the background through it
     (TEST 0x3000D alpha test). Ghost images, wrong colours or garbage mean the
     path/word/placement in question is wrong.
  3. During the load run `python tools/loading_texture_probe.py --status`:
     it prints the CONTROL words, in particular no_space (frames the payload
     skipped because the 1 MiB arena had no room) and whether the published
     size is this probe's.
  4. After the match starts check the HUD, the pause menu, the results screen,
     the character select and the main menu for corrupted 2D art: anything
     broken there was resident inside 0x2D00..0x3480 and needs a new bank.
  5. Remove the variable afterwards (`Remove-Item Env:BT3_LOADING_PROBE`).
"""
import argparse
import random
import struct
from functools import lru_cache
from PIL import Image, ImageDraw

from prototype import ROOT
from character_names import assets_folder
from regional import tbp, SCISSOR_Y1, Y_ORIGIN, xyz2_y

EXPECTED = ROOT/'analysis/loading-redesign-v4/captures/texture-probe-expected.png'
PORTRAITS = (0, 54)                    # assets/portraits/NNN.png pasted with their alpha
WIDTH, HEIGHT = 512, 224               # both textures; the sprites stretch the rows 2x
BG_TBP, FG_TBP, BG_CBP, FG_CBP = tbp(0x2D00), tbp(0x3080), tbp(0x3440), tbp(0x3444)
PSMCT32, PSMT8 = 0x00, 0x13
BYTES_PER_PIXEL = {PSMCT32: 4, PSMT8: 1}
MAX_NLOOP = 32767


def limit():
    """The guest's size bound (payload(): sltiu against CAPACITY-15-DESCRIPTOR). Imported lazily:
    loading_protocol reuses this module's register builders, and guest_loading_screen imports
    loading_protocol, so a module-level import here would be circular."""
    import guest_loading_screen as g
    return g.CAPACITY-15-g.DESCRIPTOR
# GS register numbers used by the probe.
PRIM, RGBAQ, UV, XYZ2, TEX0_1, CLAMP_1, TEX1_1, XYOFFSET_1, PRMODECONT = 0x00, 0x01, 0x03, 0x05, 0x06, 0x08, 0x14, 0x18, 0x1A
TEXFLUSH, SCISSOR_1, ALPHA_1, DTHE, COLCLAMP, TEST_1, PABE, FBA_1 = 0x3F, 0x40, 0x42, 0x45, 0x46, 0x47, 0x49, 0x4A
BITBLTBUF, TRXPOS, TRXREG, TRXDIR, AD = 0x50, 0x51, 0x52, 0x53, 0x0E
SPRITE_REGS = 0x53531                  # REGLIST descriptors RGBAQ, UV, XYZ2, UV, XYZ2 (low nibble first)
BG_PRIM, FG_PRIM = 0x116, 0x156        # sprite+TME+FST, plus ABE for the foreground
Q_ONE_WHITE = 0x3F80000080808080       # RGBAQ 0x80 x4, Q = 1.0

# Register bit layouts: (field, low bit, high bit), from the GS user's manual.
TEX0 = (('tbp',0,13),('tbw',14,19),('psm',20,25),('tw',26,29),('th',30,33),('tcc',34,34),('tfx',35,36),
        ('cbp',37,50),('cpsm',51,54),('csm',55,55),('csa',56,60),('cld',61,63))
BITBLTBUF_BITS = (('sbp',0,13),('sbw',16,21),('spsm',24,29),('dbp',32,45),('dbw',48,53),('dpsm',56,61))
TRXPOS_BITS = (('ssax',0,10),('ssay',16,26),('dsax',32,42),('dsay',48,58),('dir',59,60))
TRXREG_BITS = (('w',0,11),('h',32,43))
TEST = (('ate',0,0),('atst',1,3),('aref',4,11),('afail',12,13),('date',14,14),('datm',15,15),('zte',16,16),('ztst',17,18))
ALPHA = (('a',0,1),('b',2,3),('c',4,5),('d',6,7),('fix',32,39))
CLAMP = (('wms',0,1),('wmt',2,3),('minu',4,13),('maxu',14,23),('minv',24,33),('maxv',34,43))
TEX1 = (('lcm',0,0),('mxl',2,4),('mmag',5,5),('mmin',6,8),('mtba',9,9),('l',19,20),('k',32,43))
ATST = dict(NEVER=0, ALWAYS=1, LESS=2, LEQUAL=3, EQUAL=4, GEQUAL=5, GREATER=6, NOTEQUAL=7)


def _pack(layout, values):
    word = 0
    for (name, lo, hi), value in zip(layout, values, strict=True):
        value = int(value)
        if not 0 <= value < 1 << (hi-lo+1): raise ValueError(f'{name}={value} does not fit bits {lo}..{hi}')
        word |= value << lo
    return word


def _unpack(layout, word):
    word = int(word); fields = {name: (word >> lo) & ((1 << (hi-lo+1))-1) for name, lo, hi in layout}
    if _pack(layout, fields.values()) != word: raise ValueError(f'Stray bits in {word:#x}')
    return fields


def tex0(tbp, tbw, psm, tw, th, tcc, tfx, cbp, cpsm, csm, csa, cld): return _pack(TEX0, (tbp, tbw, psm, tw, th, tcc, tfx, cbp, cpsm, csm, csa, cld))
def bitbltbuf(sbp, sbw, spsm, dbp, dbw, dpsm): return _pack(BITBLTBUF_BITS, (sbp, sbw, spsm, dbp, dbw, dpsm))
def trxpos(ssax=0, ssay=0, dsax=0, dsay=0, dir=0): return _pack(TRXPOS_BITS, (ssax, ssay, dsax, dsay, dir))
def trxreg(w, h): return _pack(TRXREG_BITS, (w, h))
def test1(ate, atst, aref, afail, date, datm, zte, ztst): return _pack(TEST, (ate, atst, aref, afail, date, datm, zte, ztst))
def alpha1(a, b, c, d, fix): return _pack(ALPHA, (a, b, c, d, fix))
def clamp1(wms, wmt, minu, maxu, minv, maxv): return _pack(CLAMP, (wms, wmt, minu, maxu, minv, maxv))
def tex1(lcm, mxl, mmag, mmin, mtba, l, k): return _pack(TEX1, (lcm, mxl, mmag, mmin, mtba, l, k))
def decode_tex0(word): return _unpack(TEX0, word)
def decode_bitbltbuf(word): return _unpack(BITBLTBUF_BITS, word)
def decode_trxpos(word): return _unpack(TRXPOS_BITS, word)
def decode_trxreg(word): return _unpack(TRXREG_BITS, word)
def decode_test1(word): return _unpack(TEST, word)
def decode_alpha1(word): return _unpack(ALPHA, word)
def decode_clamp1(word): return _unpack(CLAMP, word)
def decode_tex1(word): return _unpack(TEX1, word)


# The words of spec 5.1, built from named fields (the spec's literals are cross-checks only).
SETUP_TEST, DRAW_TEST = test1(0, 0, 0, 0, 0, 0, 1, 1), test1(1, ATST['GREATER'], 0, 0, 0, 0, 1, 1)
STANDARD_ALPHA = alpha1(0, 1, 0, 1, 0)                        # (Cs-Cd)*As+Cd
LINEAR_TEX1 = tex1(0, 0, 1, 1, 0, 0, 0)
REGION_CLAMP = clamp1(2, 2, 0, WIDTH-1, 0, HEIGHT-1)
BG_TEX0 = tex0(BG_TBP, 8, PSMT8, 9, 8, 1, 1, BG_CBP, 0, 0, 0, 1)   # decal: the CLUT colour as is
FG_TEX0 = tex0(FG_TBP, 8, PSMT8, 9, 8, 1, 0, FG_CBP, 0, 0, 0, 1)   # modulate by RGBAQ 0x80 (x1.0)
SETUP = ((0x1FF0000 | (SCISSOR_Y1 << 48), SCISSOR_1), ((1792*16) | ((Y_ORIGIN*16) << 32), XYOFFSET_1), (1, PRMODECONT),
         (SETUP_TEST, TEST_1), (STANDARD_ALPHA, ALPHA_1), (0, PABE), (1, COLCLAMP), (0, DTHE), (0, FBA_1))


def ad_block(writes, eop=False):
    """PACKED GIFtag with the single A+D descriptor: one (value, register) per loop."""
    writes = list(writes)
    if not 1 <= len(writes) <= MAX_NLOOP: raise ValueError('A+D block size')
    out = bytearray(struct.pack('<2Q', len(writes) | (int(bool(eop)) << 15) | (1 << 60), AD))
    for value, register in writes: out += struct.pack('<2Q', value, register)
    return bytes(out)


def image_blocks(data, eop=False):
    """IMAGE GIFtags (FLG 2) over 16-byte padded data; NLOOP <= 32767 each, EOP on the last if asked."""
    data = bytes(data); data += bytes((-len(data)) % 16); qwords = len(data)//16; out = bytearray()
    if not qwords: raise ValueError('Empty image')
    for start in range(0, qwords, MAX_NLOOP):
        n = min(MAX_NLOOP, qwords-start); last = start+n == qwords
        out += struct.pack('<2Q', n | (int(bool(eop and last)) << 15) | (2 << 58), 0) + data[start*16:(start+n)*16]
    return bytes(out)


def upload_image(dbp, dbw, dpsm, width, height, data, eop=False):
    """Host->local transfer of a row-major image: BITBLTBUF, TRXPOS, TRXREG, TRXDIR (last), then the IMAGE data."""
    if len(data) != width*height*BYTES_PER_PIXEL[dpsm]: raise ValueError('Image data does not match its rectangle')
    return ad_block([(bitbltbuf(0, 0, 0, dbp, dbw, dpsm), BITBLTBUF), (trxpos(), TRXPOS), (trxreg(width, height), TRXREG), (0, TRXDIR)]) + image_blocks(data, eop)


def clut_position(index):
    """CSM1: a 256-entry CLUT is a 16x16 PSMCT32 image whose entries 8..15 and 16..23 of every 32 are swapped."""
    return (index & ~0x18) | ((index & 8) << 1) | ((index & 16) >> 1)


def gs_alpha(alpha): return min(0x80, (int(alpha)+1)//2)


def clut_image(entries):
    """1024 bytes of PSMCT32 CLUT from 256 (r, g, b, a) entries with 8-bit alpha."""
    entries = list(entries)
    if len(entries) != 256: raise ValueError('A PSMT8 CLUT has 256 entries')
    out = bytearray(1024)
    for i, (r, gg, b, a) in enumerate(entries): struct.pack_into('<4B', out, 4*clut_position(i), r, gg, b, gs_alpha(a))
    return bytes(out)


def xyz2(x, y, z=0):
    """(x, y) of the 512x448 design frame; the European 512-line frame stretches y (regional.screen_y)."""
    if not (0 <= x <= 512 and 0 <= y <= 448): raise ValueError('Vertex outside the native frame')
    return ((x+1792)*16) | (xyz2_y(y) << 16) | (z << 32)


def uv(u, v):
    if not (0 <= u < 1 << 14 and 0 <= v < 1 << 14): raise ValueError('UV outside the register range')
    return u | (v << 16)


def textured_sprite(x0, y0, x1, y1, u0, v0, u1, v1, rgbaq=Q_ONE_WHITE, eop=False):
    """REGLIST RGBAQ, UV, XYZ2, UV, XYZ2 (UV in 1/16 texel): five registers pad to three qwords."""
    tag = struct.pack('<2Q', 1 | (int(bool(eop)) << 15) | (1 << 58) | (5 << 60), SPRITE_REGS)
    return tag + struct.pack('<6Q', rgbaq, uv(u0, v0), xyz2(x0, y0), uv(u1, v1), xyz2(x1, y1), 0)


def _font(size):
    from PIL import ImageFont
    for name in ('bahnschrift.ttf', 'arialbd.ttf'):
        try: font = ImageFont.truetype(name, size)
        except OSError: continue
        try: font.set_variation_by_name('Bold')
        except (OSError, AttributeError, ValueError): pass
        return font
    return ImageFont.load_default(size)


def _tall_text(target, text, xy, size, fill):
    """Draw in screen space (512x448) and squash into the texture so the TV shows undistorted glyphs."""
    layer = Image.new('RGBA', (WIDTH, 2*HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=_font(size), fill=fill)
    target.alpha_composite(layer.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS))


def background_picture():
    """512x224 RGB: gradient, nebula glows, 200 stars, a grid, 8 colour bars and the title."""
    import numpy as np
    y, x = (a.astype(np.float32) for a in np.mgrid[0:HEIGHT, 0:WIDTH])
    t = (y/(HEIGHT-1))[..., None]
    rgb = np.array((6, 10, 46), np.float32)*(1-t) + np.array((58, 18, 92), np.float32)*t
    # Elliptical glows: the rows are shown at 2x, so half the vertical radius keeps them round on the TV.
    rgb += np.exp(-1.4*(((x-336)/150)**2 + ((y-84)/70)**2))[..., None]*np.array((150, 60, 170), np.float32)
    rgb += np.exp(-1.8*(((x-150)/120)**2 + ((y-140)/60)**2))[..., None]*np.array((40, 90, 160), np.float32)
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB').convert('RGBA'); d = ImageDraw.Draw(image)
    rng = random.Random(0x50524F42)
    for _ in range(200):
        sx, sy, v = rng.randrange(WIDTH), rng.randrange(HEIGHT-32), rng.randrange(120, 256)
        d.point((sx, sy), (v, v, min(255, v+20), 255))
        if v > 230: d.point((min(sx+1, WIDTH-1), sy), (v//2, v//2, v//2, 255))
    for gx in range(0, WIDTH, 64): d.line((gx, 0, gx, HEIGHT-1), (96, 96, 108, 255))
    for gy in range(0, HEIGHT, 32): d.line((0, gy, WIDTH-1, gy), (96, 96, 108, 255))   # 32 texels = 64 TV rows
    bars = ((255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255), (40, 40, 40))
    for k, color in enumerate(bars): d.rectangle((64*k, HEIGHT-24, 64*k+63, HEIGHT-1), fill=color+(255,))
    _tall_text(image, f'TEXTURE PROBE  BG 0x{BG_TBP:04X}  CLUT 0x{BG_CBP:04X}', (16, 12), 24, (255, 255, 255, 255))
    return image.convert('RGB')


def foreground_picture():
    """512x224 RGBA, mostly transparent: title, alpha squares, a panel with a window, portraits, outline."""
    image = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    _tall_text(image, f'FG 0x{FG_TBP:04X} ALPHA TEST', (16, 78), 30, (255, 255, 255, 255))
    d = ImageDraw.Draw(image)
    for k, alpha in enumerate((255, 192, 128, 64)):
        x = 32+56*k; d.rectangle((x, 70, x+39, 89), fill=(230, 30, 40, alpha))          # 40x40 on the TV
    d.rectangle((272, 60, 463, 111), fill=(24, 40, 120, 208))                           # panel...
    d.rectangle((300, 70, 435, 101), fill=(0, 0, 0, 0))                                 # ...with a keyed window
    for k, character in enumerate(PORTRAITS):
        with Image.open(assets_folder()/f'portraits/{character:03d}.png') as portrait:
            image.alpha_composite(portrait.convert('RGBA').resize((64, 32), Image.Resampling.LANCZOS), (296+80*k, 130))
    d.rectangle((0, 0, WIDTH-1, HEIGHT-1), outline=(255, 255, 255, 255), width=1)
    return image


def bleed(image):
    """Alpha-0 pixels take the RGB of their nearest opaque neighbours so filtered edges keep the colour."""
    import numpy as np
    px = np.array(image.convert('RGBA')); rgb = px[..., :3].astype(np.float32); known = px[..., 3] > 0
    h, w = known.shape
    while known.any() and not known.all():
        k = np.pad(known, 1); c = np.pad(rgb, ((1, 1), (1, 1), (0, 0))); total = np.zeros_like(rgb); count = np.zeros((h, w), np.float32)
        for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
            n = k[dy:dy+h, dx:dx+w]; total += c[dy:dy+h, dx:dx+w]*n[..., None]; count += n
        fill = ~known & (count > 0); rgb[fill] = total[fill]/count[fill][:, None]; known |= fill
    px[..., :3] = np.rint(rgb).astype(np.uint8)
    return Image.fromarray(px, 'RGBA')


def _palette(indexed, mode):
    values = indexed.getpalette(mode) or []; n = len(mode); values += [0]*(256*n-len(values))
    return [tuple(values[n*i:n*i+n]) + ((255,) if n == 3 else ()) for i in range(256)]


def quantise_background(image):
    """(indices, 256 RGBA entries, P image): MEDIANCUT + Floyd-Steinberg, opaque CLUT."""
    q = image.convert('RGB').quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    return q.tobytes(), _palette(q, 'RGB'), q


def quantise_foreground(image):
    """(indices, 256 RGBA entries, P image): alpha bleed, then FASTOCTREE keeps the alpha channel."""
    q = bleed(image).quantize(256, method=Image.Quantize.FASTOCTREE)
    return q.tobytes(), _palette(q, 'RGBA'), q


@lru_cache(maxsize=1)
def quantised():
    return quantise_background(background_picture()), quantise_foreground(foreground_picture())


def decoded_layers():
    """What the GS samples: the quantised background (RGB) and foreground (RGBA with the GS alpha)."""
    (_, bg_entries, bg), (_, fg_entries, fg) = quantised()
    bg_image = Image.new('RGB', (WIDTH, HEIGHT)); bg_image.putdata([bg_entries[i][:3] for i in bg.tobytes()])
    fg_image = Image.new('RGBA', (WIDTH, HEIGHT))
    fg_image.putdata([fg_entries[i][:3]+(min(255, 2*gs_alpha(fg_entries[i][3])),) for i in fg.tobytes()])
    return bg_image, fg_image


def composite_picture():
    """The TV in native space: both textures stretched 2x vertically (bilinear), foreground blended over."""
    bg, fg = decoded_layers(); size = (WIDTH, 2*HEIGHT)
    out = bg.resize(size, Image.Resampling.BILINEAR).convert('RGBA')
    out.alpha_composite(fg.resize(size, Image.Resampling.BILINEAR))
    return out.convert('RGB')


def expected_composite(): return composite_picture().resize((640, 480), Image.Resampling.LANCZOS)


# Setup, two images with their CLUTs, TEXFLUSH, two A+D/sprite pairs, the restore.
PACKET_BYTES = (16+9*16) + 2*(16+4*16+16+WIDTH*HEIGHT) + 2*(16+4*16+16+1024) + 32 + (16+4*16+64) + (16+3*16+64) + (16+2*16)


def probe_packet():
    """ONE GIF packet the v3 guest copies verbatim: uploads, then the stretched textured sprites."""
    (bg_indices, bg_entries, _), (fg_indices, fg_entries, _) = quantised()
    out = bytearray(ad_block(SETUP))
    out += upload_image(BG_TBP, 8, PSMT8, WIDTH, HEIGHT, bg_indices)
    out += upload_image(BG_CBP, 1, PSMCT32, 16, 16, clut_image(bg_entries))
    out += upload_image(FG_TBP, 8, PSMT8, WIDTH, HEIGHT, fg_indices)
    out += upload_image(FG_CBP, 1, PSMCT32, 16, 16, clut_image(fg_entries))
    out += ad_block([(0, TEXFLUSH)])
    out += ad_block([(BG_TEX0, TEX0_1), (LINEAR_TEX1, TEX1_1), (REGION_CLAMP, CLAMP_1), (BG_PRIM, PRIM)])
    out += textured_sprite(0, 0, 512, 448, 0, 0, WIDTH*16, HEIGHT*16)
    out += ad_block([(FG_TEX0, TEX0_1), (DRAW_TEST, TEST_1), (FG_PRIM, PRIM)])
    out += textured_sprite(0, 0, 512, 448, 0, 0, WIDTH*16, HEIGHT*16)
    out += ad_block([(SETUP_TEST, TEST_1), (STANDARD_ALPHA, ALPHA_1)], eop=True)
    assert len(out) == PACKET_BYTES and len(out) % 16 == 0 and len(out) <= limit(), len(out)
    return bytes(out)


def render(*args, **kwargs):
    """`guest_loading_screen.render` substitute: (picture, layers, packets) with packet A only."""
    picture = composite_picture()
    return picture, dict(background=picture, foreground=None, lights=None), (probe_packet(), b'', b'')


CONTROL_WORDS = ('magic', 'buffer', 'size', 'drawn', 'age', 'generation', 'consumed', 'no_space', 'surface', 'menu_frames')


def status(client=None):
    from contextlib import nullcontext
    from pine import PineClient
    import guest_loading_screen as g
    with nullcontext(client) if client is not None else PineClient(timeout=3) as p:
        words = dict(zip(CONTROL_WORDS, struct.unpack('<10I', p.read(g.CONTROL, 40))))
    words['cover_active'] = words['magic'] == g.MAGIC
    # the guest references the run behind its VIF prologue, so the published size includes it
    # the guest references the run behind its 16-byte VIF prologue, so the published
    # size is the prologue plus the packet
    words['probe_published'] = words['size'] == 16+PACKET_BYTES
    return words


def main(argv=None):
    p = argparse.ArgumentParser(description='Ki Storm Phase 0c texture probe for the v3 loading guest.')
    p.add_argument('--preview', action='store_true', help=f'write {EXPECTED} and print the packet size')
    p.add_argument('--status', action='store_true', help='print the guest CONTROL words over PINE')
    args = p.parse_args(argv)
    if not (args.preview or args.status): p.error('choose --preview and/or --status')
    if args.preview:
        packet = probe_packet(); EXPECTED.parent.mkdir(parents=True, exist_ok=True); expected_composite().save(EXPECTED)
        print(f'packet A: {len(packet)} bytes (limit {limit()}); expected picture: {EXPECTED}')
    if args.status:
        words = status()
        for name in CONTROL_WORDS:
            value = words[name]; print(f'{name:12} {value:#010x}' if name in ('magic', 'buffer', 'consumed') else f'{name:12} {value}')
        print(f"cover_active {words['cover_active']}  probe_published {words['probe_published']} (probe size {PACKET_BYTES})")


if __name__ == '__main__': main()
