"""PSMT8 quantisation of the Ki Storm pictures and the CLUT bytes the guest uploads.

- quantise_background(rgb) -> (indices 512x448 uint8, clut 256 x RGBA alpha 0x80):
  MEDIANCUT + Floyd-Steinberg over the whole picture (one CLUT).
- quantise_foreground(rgba 512x448, slices) -> (indices 512x448 uint8, cluts): each entrance
  slice region is quantised on its own (FASTOCTREE 256, alpha kept) so its indices are local
  to its CLUT and a footer change never shifts another slice's palette. Alpha-0 pixels are
  RGB-bled from their nearest opaque neighbour first (loading_art_v4.straight_alpha already
  did this for compose() output; it is repeated here so any RGBA source works). GS alpha =
  (a+1)//2 capped at 0x80.
- quantise_atlas(rgba 256x32) -> (indices 256x32 uint8, clut): the separate atlas texture with
  its own CLUT.
- clut_swizzle_csm1(entries) -> 1024 bytes, entry i stored at (i & ~0x18) | ((i & 8) << 1) |
  ((i & 16) >> 1) (the GS CSM1 block layout).
- composite_quantised(layers) -> RGB 512x448 of the quantised foreground over the quantised
  background: what the GS shows (per-slice CLUT alpha, ATST GREATER 0 drops alpha 0).
- picture_bytes(layers) -> the upload blobs: background/foreground/atlas indices, swizzled CLUTs.
- tv(image) -> 640x480 LANCZOS (design space, what the TV shows).
"""
import hashlib

import numpy as np
from PIL import Image

NATIVE = (512, 448)
ATLAS = (256, 32)
GS_OPAQUE = 0x80
FAINT = 8                       # source alpha at or below this is treated as transparent
ALPHA_WEIGHT_VECTOR = np.array([1, 1, 1, 2], np.float32)   # an alpha mismatch shows over any backdrop


def gs_alpha(a):
    return min(GS_OPAQUE, (int(a)+1)//2)


def _palette(image, mode):
    flat = image.getpalette(mode) or []
    n = len(mode)
    entries = [tuple(flat[i:i+n]) for i in range(0, len(flat)-n+1, n)]
    entries = entries[:256]+[(0,)*n]*(256-len(entries))
    return entries


_BACKGROUNDS = {}


def quantise_background(rgb, kmeans=2):
    """RGB 512x448 -> (indices uint8 (448, 512), 256 x (r, g, b, 0x80)). Two k-means passes
    after the median cut halve the error on the thin bright rim and glints (max 120 -> 70);
    the picture is static per mode, so the 0.7 s result is cached by content."""
    if rgb.mode != 'RGB' or rgb.size != NATIVE: raise ValueError('background must be RGB 512x448')
    data = rgb.tobytes(); key = (hashlib.sha1(data).digest(), kmeans)
    if key not in _BACKGROUNDS:
        q = rgb.quantize(256, method=Image.Quantize.MEDIANCUT, kmeans=kmeans, dither=Image.Dither.FLOYDSTEINBERG)
        clut = [(r, g, b, GS_OPAQUE) for r, g, b in _palette(q, 'RGB')]
        if len(_BACKGROUNDS) >= 8: _BACKGROUNDS.clear()
        _BACKGROUNDS[key] = (np.asarray(q, np.uint8).copy(), clut)
    indices, clut = _BACKGROUNDS[key]
    return indices.copy(), list(clut)


def alpha_bleed(rgba, passes=6):
    """Copy the RGB of the nearest opaque neighbour (4-connected, up to `passes` px) into alpha-0 pixels."""
    a = np.asarray(rgba, np.uint8).copy()
    rgb = a[..., :3]; filled = a[..., 3] > 0
    for _ in range(passes):
        if filled.all(): break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src = np.roll(rgb, (dy, dx), axis=(0, 1)); sf = np.roll(filled, (dy, dx), axis=(0, 1))
            take = ~filled & sf
            rgb[take] = src[take]; filled |= take
    return Image.fromarray(a, 'RGBA')


def _nearest(colours, palette, candidates, channels):
    """Index of the nearest candidate palette entry for every colour over the given channels."""
    best = np.zeros(len(colours), np.int64); best_d = np.full(len(colours), np.inf, np.float32)
    for c0 in range(0, len(candidates), 32):
        sub = candidates[c0:c0+32]
        d = ((colours[:, None, channels]-palette[None, sub][..., channels])**2).sum(2)
        j = d.argmin(1); dj = d[np.arange(len(colours)), j]
        better = dj < best_d; best[better] = sub[j[better]]; best_d[better] = dj[better]
    return best


def _assign(pixels, palette):
    """Palette index per pixel. FASTOCTREE assigns by octree node (portrait errors near 45)
    and merges bled alpha-0 colours with faint edge entries (alpha ~20 haze over every
    transparent texel); re-assigning the region's distinct colours by distance fixes both:
    alpha-0 pixels only ever take an alpha-0 entry (RGB distance, so bilinear fringes keep
    their colour), every other pixel an entry with alpha > 0 (RGBA distance)."""
    flat = pixels.reshape(-1, 4)
    unique, inverse = np.unique(flat.view(np.uint32).ravel(), return_inverse=True)
    colours = unique.view(np.uint8).reshape(-1, 4).astype(np.float32)
    clear = np.flatnonzero(palette[:, 3] == 0); solid_ = np.flatnonzero(palette[:, 3] > 0)
    best = np.zeros(len(colours), np.int64)
    # alpha <= FAINT (GS alpha <= 4, a 3% blend) counts as transparent: a glow tail forced onto
    # the nearest visible entry would otherwise land on a much denser one and show as a blotch
    transparent = colours[:, 3] <= FAINT
    weighted = palette*ALPHA_WEIGHT_VECTOR; colours = colours*ALPHA_WEIGHT_VECTOR
    if transparent.any(): best[transparent] = _nearest(colours[transparent], weighted, clear, slice(0, 3))
    if (~transparent).any() and len(solid_): best[~transparent] = _nearest(colours[~transparent], weighted, solid_, slice(0, 4))
    return best[inverse].reshape(pixels.shape[:2]).astype(np.uint8)


_REGIONS = {}


def _quantise_region(image, box):
    """Slices that did not change since the last picture (the stage, a fighter who stays in
    the same place) reuse their result; FASTOCTREE and the assignment are deterministic in the
    cropped bytes, so the cache is keyed by exactly those and returns copies."""
    crop = image.crop(box)
    key = (crop.mode, crop.size, hashlib.sha1(crop.tobytes()).digest())
    cached = _REGIONS.get(key)
    if cached is None:
        q = crop.quantize(255, method=Image.Quantize.FASTOCTREE)   # 255: one entry is reserved fully transparent
        raw = [e for e in _palette(q, 'RGBA')[:255] if e != (0, 0, 0, 0)]
        raw = (raw+[(0, 0, 0, 0)]*256)[:256]
        idx = _assign(np.asarray(crop, np.uint8), np.asarray(raw, np.float32))
        cached = (idx, tuple((r, g, b, gs_alpha(a)) for r, g, b, a in raw))
        if len(_REGIONS) >= 64: _REGIONS.clear()
        _REGIONS[key] = cached
    idx, clut = cached
    return idx.copy(), list(clut)


def quantise_foreground(rgba, slices):
    """RGBA 512x448 + entrance slices -> (indices uint8 (448, 512), [clut per slice])."""
    if rgba.mode != 'RGBA' or rgba.size != NATIVE: raise ValueError('foreground must be RGBA 512x448')
    if not slices: raise ValueError('the foreground needs at least one slice')
    image = alpha_bleed(rgba)
    indices = np.zeros((NATIVE[1], NATIVE[0]), np.uint8)
    cluts = []
    for sl in slices:
        box = (sl['x'], sl['y'], sl['x']+sl['w'], sl['y']+sl['h'])
        idx, clut = _quantise_region(image, box)
        indices[box[1]:box[3], box[0]:box[2]] = idx; cluts.append(clut)
    return indices, cluts


def quantise_atlas(rgba):
    """RGBA 256x32 -> (indices uint8 (32, 256), clut): the atlas texture with its own CLUT."""
    if rgba.mode != 'RGBA' or rgba.size != ATLAS: raise ValueError('atlas must be RGBA 256x32')
    return _quantise_region(alpha_bleed(rgba), (0, 0, ATLAS[0], ATLAS[1]))


def clut_swizzle_csm1(entries):
    out = bytearray(1024)
    for i, (r, g, b, a) in enumerate(entries[:256]):
        j = (i & ~0x18) | ((i & 8) << 1) | ((i & 16) >> 1)
        out[j*4:j*4+4] = bytes((r, g, b, a))
    return bytes(out)


def clut_unswizzle_csm1(data):
    entries = [None]*256
    for i in range(256):
        j = (i & ~0x18) | ((i & 8) << 1) | ((i & 16) >> 1)
        entries[i] = tuple(data[j*4:j*4+4])
    return entries


def quantise(layers):
    """compose() output -> dict(background=(indices, clut), foreground=(indices, cluts), atlas=(indices, clut), slices)."""
    bg = quantise_background(layers['background'])
    fg = quantise_foreground(layers['foreground'], layers['slices'])
    return dict(background=bg, foreground=fg, atlas=quantise_atlas(layers['atlas_image']), slices=list(layers['slices']))


def is_quantised(layers):
    return 'background' in layers and isinstance(layers['background'], tuple)


def reconstruct(quantised):
    """(background RGB uint8 (448, 512, 3), foreground RGBA uint8 (448, 512, 4), atlas RGBA uint8 (32, 256, 4)), GS alpha 0..128."""
    idx, clut = quantised['background']
    bg = np.asarray(clut, np.uint8)[idx][..., :3]
    idx, cluts = quantised['foreground']
    fg = np.zeros((NATIVE[1], NATIVE[0], 4), np.uint8)
    for sl, clut in zip(quantised['slices'], cluts):
        box = (sl['x'], sl['y'], sl['x']+sl['w'], sl['y']+sl['h'])
        fg[box[1]:box[3], box[0]:box[2]] = np.asarray(clut, np.uint8)[idx[box[1]:box[3], box[0]:box[2]]]
    idx, clut = quantised['atlas']
    return bg, fg, np.asarray(clut, np.uint8)[idx]


def composite_quantised(layers):
    """What the GS shows: quantised foreground over the quantised background, RGB 512x448."""
    quantised = layers if is_quantised(layers) else layers.get('quantised') or quantise(layers)
    bg, fg, _ = reconstruct(quantised)
    fg = fg.astype(np.float32)
    a = fg[..., 3:4]/GS_OPAQUE
    out = bg.astype(np.float32)*(1-a)+fg[..., :3]*a
    return Image.fromarray((out+0.5).astype(np.uint8), 'RGB')


def picture_bytes(layers):
    """Upload blobs: background/foreground indices (229376 B each), atlas indices (8192 B), CSM1 CLUTs (1024 B each)."""
    quantised = layers if is_quantised(layers) else quantise(layers)
    (bg_idx, bg_clut), (fg_idx, cluts), (atlas_idx, atlas_clut) = quantised['background'], quantised['foreground'], quantised['atlas']
    return dict(background=bg_idx.tobytes(), foreground=fg_idx.tobytes(), atlas=atlas_idx.tobytes(), clut_background=clut_swizzle_csm1(bg_clut),
                clut_atlas=clut_swizzle_csm1(atlas_clut), clut_slices=[clut_swizzle_csm1(c) for c in cluts])


def tv(image):
    return image.resize((640, 480), Image.LANCZOS)
