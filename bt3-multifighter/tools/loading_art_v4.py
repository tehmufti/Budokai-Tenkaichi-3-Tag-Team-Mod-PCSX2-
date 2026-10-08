"""Ki Storm loading pictures: the JS scene `analysis/loading-redesign-v4/scenes/kistorm.js`
ported to PIL for every mode, plus the entrance slices and the animation plan the guest
descriptor is encoded from (Phase 2). Offline only: fonts, portraits, numpy.

compose(teams, progress, message, *, mode, humans, portrait_colors=None, decorations=None)
returns dict(background, foreground, atlas_image, slices, lights, text, cards, atlas):
- background: PIL RGB 512x448 (native), foreground: PIL RGBA 512x448 straight alpha (the
  screen), atlas_image: PIL RGBA 256x32 straight alpha, a SEPARATE texture (one PSMT8 page
  row) holding the digits '0'..'9' '%', a soft dot and a streak at atlas-local u/v (see
  `atlas`). All are painted in DESIGN space (640x480, what the TV shows) at 2x with
  premultiplied float compositing and LANCZOS-resampled to native.
- slices: entrance slices in NATIVE px, disjoint and tiling 512x448: dict(index, x, y, w, h,
  u, v (= x, y in the foreground texture), start (frame), dx, dy (native px of slide)).
- text: every text run: dict(text, x0, y0, x1, y1 (native), card (index or None)).
- cards: native card boxes dict(x0, y0, x1, y1, name, form, role, side, hex=(cx, cy)).

Plan schema (`lights`, all coordinates NATIVE px unless stated; colours (r, g, b) 0..255;
angles/phases in 1/256 turn; frames at 60 Hz):
- fade: dict(color, frames=24) - the full-screen fade sprite alpha 128*(frames-f)/frames.
- ribbons: list (6 two-sided, 4 ffa) of dict(side 0/1, x0, x1 (centre line at the bottom y0
  and top y1), y0 > y1, A1, A2 (amplitudes, px; the guest computes (A*sin8)>>7 with sin8 in
  -127..127), f1, f2 (phase per i16 unit, i16 = 16*i for segment i of 16, integer >= 1), w1,
  w2 (per-frame phase speed in 1/8 units: phase += (w*f)>>3), p1, p2 (phase offsets 0..255),
  W (full width px), wf (width phase per i16 unit, (wf*i16)>>4), wp (0..255), fade_start,
  fade_end (frames of the alpha ramp), colors: 17 centre colours from the bottom (i=0) to the
  top (i=16) carrying the deep->bright ramp, the length profile and the ribbon's own alpha.
- sparks: dict(regions=[2 x dict(x0, y0, x1, y1)] (scissor per side; region height maps the
  guest's 512-unit climb), entries=[128 x dict(ribbon, u (0..127, phase*4 & 511 seed), speed
  (climb units per frame), phase (0..127), size (3..6 px), streak (0/1), twinkle (0..255))]).
- orbs: [2 x dict(side, cx, cy, rx, ry, core, team, deep, halo, flight_y (start of the
  flight-in, frames 0..54))].
- seam: dict(cx, cy, rx, ry, color, edge), ring: dict(cx, cy, left, right, inner, life=90,
  first=54, cycle=150), flash: dict(cx, cy, rx, ry, color, start=54, frames=18).
- bolts: [2 x dict(x0, y0, x1, y1, bulge (signed px, negative = up), period=63, duration=8,
  color, glow)] anchored on the orb flanks.
- chevrons: dict(cx, cy, offset (first pitch from cy), pitch, count=4 per side, colors [2],
  period=50, stagger=21).
- ticks: [<= 12 x dict(cx, cy, rx, ry, n, direction (+1 cw / -1 ccw), color, box (bx0, by0,
  bx1, by1 exclusion, all 0 when none), cursor)].
- gauge: dict(x0, x1, y0, y1 (inner fill channel), colors [3] (blue->cyan->white ramp), tip,
  orb=dict(cx, cy, rx, ry, color), pct_x, pct_y (top-left of the first digit sprite)). The
  encoder adds fill/progress/digits per progress step from gauge_digits(progress).
- sheens: [2 x dict(x0, y0, x1, y1)] banner cores; dots: dict(x, y, pitch, size, color).
- atlas (also returned at the top level): dict(digits={ch: dict(u, v, w, h, adv)}, dot=dict(u,
  v, w, h), streak=dict(u, v, w, h)) in the atlas texture (v = 0: one row of cells);
  gauge_digits(progress) -> up to 4 dict(u, v, w, h, x, y) sprite entries (atlas u/v, screen
  x/y) with the real glyph advances.
"""
import math
from localization import tr
import fonts
import os
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from loading_design import design as _design, mode_options

DESIGN, NATIVE, S = (640, 480), (512, 448), 2
ATLAS, ATLAS_DESIGN, ATLAS_ROWS = (256, 32), (320, 32), 30   # native texture; painted at 320x32 design px into 30 rows
COL = ((22, 250), (368, 250))
AREA = (102, 286)
VS = (320, 245)
GAUGE = dict(x0=84, x1=556, y=423, h=18, cx=582, cy=432, r=13, pct_x=22)
HORIZON = (320, 2392, 2000)
FFA_EMBLEM = (556, 44, 16)
FFA_RIBBON_X = (120, 260, 380, 520)
WHITE = (255, 255, 255)
GOLD = ((255, 222, 120), (214, 160, 40))
# Bahnschrift (variable: Weight, Width) and Segoe UI Black on Windows. Off Windows both are
# the bundled Liberation Sans Bold without axes (fonts.py): wider than condensed Bahnschrift,
# so text() compresses a run horizontally when it still overflows at its minimum size
# (SQUEEZE, never on Windows, whose pictures stay byte-identical).
FONTS = dict(cond=(fonts.path('display'), (700, 75)), semi=(fonts.path('display'), (600, 75)),
             wide=(fonts.path('display'), (700, 100)), heading=(fonts.path('heading'), None))
SQUEEZE = fonts.bundled()
# side themes (bright, deep) per the spec's section 4; ffa = pink / violet storm emblem
THEMES = {
    'teams': dict(sides=(((78, 230, 255), (59, 125, 255)), ((255, 138, 61), (255, 61, 90))), centre=(106, 59, 255), glow=(120, 80, 255)),
    'ffa': dict(sides=(((255, 150, 176), (247, 98, 119)), ((196, 150, 255), (160, 90, 255))), centre=(200, 60, 170), glow=(230, 80, 200)),
    'coop': dict(sides=(((150, 255, 230), (70, 214, 181)), ((255, 210, 120), (246, 164, 93))), centre=(60, 150, 160), glow=(80, 210, 200)),
    'training': dict(sides=(((190, 255, 200), (116, 222, 132)), ((160, 240, 235), (70, 200, 190))), centre=(50, 150, 110), glow=(90, 220, 150)),
}
THEMES['training_coop'] = THEMES['training']
# entrance timing in frames (the JS ENT seconds x 60) and slide distances in design px
ENT = dict(header=3, banners=9, cards=13, step=5.4, footer=25, vs=61)
SLIDE = dict(header=-18, banners=26, cards=48, footer=14)
DIGITS = '0123456789%'
CELL = (24, 28)


def nx(x): return int(round(0.8*x))
def ny(y): return int(round(y*448/480))
def mix(a, b, t): return tuple(int(round(a[i]+(b[i]-a[i])*t)) for i in range(3))
def dim(c, t): return mix(c, (0, 0, 0), t)


def rand(seed):
    """H.rand of harness.js: the same LCG so the ribbon/spark constants match the browser."""
    x = (seed*9301+49297) % 233280
    def r():
        nonlocal x
        x = (x*9301+49297) % 233280
        return x/233280
    return r


# ---- premultiplied float canvas ------------------------------------------------------------
class Canvas:
    """(h, w, 4) float32 premultiplied RGBA in paint pixels (design x S); ops clip."""
    def __init__(self, w, h):
        self.a = np.zeros((h, w, 4), np.float32)

    def _clip(self, x, y, src):
        H, W = self.a.shape[:2]; h, w = src.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x+w), min(H, y+h)
        if x1 <= x0 or y1 <= y0: return None, None
        return (slice(y0, y1), slice(x0, x1)), src[y0-y:y1-y, x0-x:x1-x]

    def over(self, x, y, src):
        sl, s = self._clip(int(x), int(y), src)
        if sl is None: return
        d = self.a[sl]; d *= 1-s[..., 3:4]; d += s

    def add(self, x, y, src):
        sl, s = self._clip(int(x), int(y), src)
        if sl is None: return
        d = self.a[sl]; d += s; np.minimum(d, 1, out=d)

    def image(self):
        return Image.fromarray((self.a*255+0.5).astype(np.uint8), 'RGBA')


def solid(mask, color, alpha=1.0):
    m = mask*np.float32(alpha) if alpha != 1 else mask
    out = np.empty(mask.shape+(4,), np.float32)
    for i in range(3): out[..., i] = m*(color[i]/255)
    out[..., 3] = m
    return out


def shaded(mask, rgb, alpha):
    """mask x per-pixel (h, w, 3) colour 0..1 and (h, w) alpha -> premultiplied patch."""
    m = mask*alpha
    out = np.empty(mask.shape+(4,), np.float32)
    out[..., :3] = rgb*m[..., None]; out[..., 3] = m
    return out


def _mask(im, ss):
    if ss > 1: im = im.reduce(ss)
    return np.asarray(im, np.float32)/255


def poly_mask(pts, width=0, closed=True, ss=2):
    """Anti-aliased polygon (filled) or polyline mask from design coords -> (mask, px, py)."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    pad = width/2+1
    x0, y0 = math.floor(min(xs)-pad), math.floor(min(ys)-pad)
    x1, y1 = math.ceil(max(xs)+pad), math.ceil(max(ys)+pad)
    k = S*ss
    im = Image.new('L', ((x1-x0)*k, (y1-y0)*k)); d = ImageDraw.Draw(im)
    q = [((x-x0)*k, (y-y0)*k) for x, y in pts]
    if width: d.line(q+([q[0]] if closed else []), fill=255, width=max(1, round(width*k)), joint='curve')
    else: d.polygon(q, fill=255)
    return _mask(im, ss), x0*S, y0*S


def ellipse_mask(cx, cy, rx, ry, width=0, ss=2):
    pad = width/2+1
    x0, y0, x1, y1 = math.floor(cx-rx-pad), math.floor(cy-ry-pad), math.ceil(cx+rx+pad), math.ceil(cy+ry+pad)
    k = S*ss
    im = Image.new('L', ((x1-x0)*k, (y1-y0)*k)); d = ImageDraw.Draw(im)
    box = ((cx-rx-x0)*k, (cy-ry-y0)*k, (cx+rx-x0)*k, (cy+ry-y0)*k)
    if width: d.ellipse(box, outline=255, width=max(1, round(width*k)))
    else: d.ellipse(box, fill=255)
    return _mask(im, ss), x0*S, y0*S


def arc_mask(cx, cy, r, a0, a1, width, ss=2):
    """Arc from angle a0 to a1 (radians, canvas orientation) as a stroked mask."""
    pad = width/2+1
    x0, y0, x1, y1 = math.floor(cx-r-pad), math.floor(cy-r-pad), math.ceil(cx+r+pad), math.ceil(cy+r+pad)
    k = S*ss
    im = Image.new('L', ((x1-x0)*k, (y1-y0)*k)); d = ImageDraw.Draw(im)
    d.arc(((cx-r-x0)*k, (cy-r-y0)*k, (cx+r-x0)*k, (cy+r-y0)*k), math.degrees(a0), math.degrees(a1), fill=255, width=max(1, round(width*k)))
    return _mask(im, ss), x0*S, y0*S


def blur_mask(mask, radius):
    """Gaussian blur of a mask (radius in design px, ~ canvas shadowBlur/2); pads so it spreads."""
    pad = int(math.ceil(radius*S*3))+1
    im = Image.fromarray((np.pad(mask, pad)*255+0.5).astype(np.uint8), 'L').filter(ImageFilter.GaussianBlur(radius*S))
    return np.asarray(im, np.float32)/255, pad


def radial(cx, cy, rx, ry, stops, r0=0.0):
    """Radial gradient patch: stops [(t, colour, alpha)] from radius r0*r to r -> (patch, px, py)."""
    x0, y0 = math.floor(cx-rx)-1, math.floor(cy-ry)-1
    x1, y1 = math.ceil(cx+rx)+1, math.ceil(cy+ry)+1
    xs = (np.arange((x1-x0)*S, dtype=np.float32)+0.5)/S+x0-cx
    ys = (np.arange((y1-y0)*S, dtype=np.float32)+0.5)/S+y0-cy
    d = np.sqrt((xs[None, :]/rx)**2+(ys[:, None]/ry)**2)
    t = np.clip((d-r0)/(1-r0), 0, 1) if r0 else np.minimum(d, 1)
    ts = [s[0] for s in stops]
    alpha = np.interp(t, ts, [s[2] for s in stops]).astype(np.float32)
    alpha[d > 1] = 0
    rgb = np.stack([np.interp(t, ts, [s[1][i]/255 for s in stops]) for i in range(3)], -1).astype(np.float32)
    return shaded(np.ones(d.shape, np.float32), rgb, alpha), x0*S, y0*S


def linear(mask, px, py, x0, y0, x1, y1, stops):
    """Linear gradient (design coords) evaluated over a mask at paint origin (px, py)."""
    h, w = mask.shape
    xs = (np.arange(w, dtype=np.float32)+0.5+px)/S; ys = (np.arange(h, dtype=np.float32)+0.5+py)/S
    dx, dy = x1-x0, y1-y0
    L = dx*dx+dy*dy or 1.0
    t = np.clip(((xs[None, :]-x0)*dx+(ys[:, None]-y0)*dy)/L, 0, 1)
    ts = [s[0] for s in stops]
    alpha = np.interp(t, ts, [s[2] for s in stops]).astype(np.float32)
    rgb = np.stack([np.interp(t, ts, [s[1][i]/255 for s in stops]) for i in range(3)], -1).astype(np.float32)
    return shaded(mask, rgb, alpha)


def chamfer(x, y, w, h, c):
    return [(x+c, y), (x+w-c, y), (x+w, y+c), (x+w, y+h-c), (x+w-c, y+h), (x+c, y+h), (x, y+h-c), (x, y+c)]


def hexagon(cx, cy, R):
    return [(cx+R*math.cos(-math.pi/2+i*math.pi/3), cy+R*math.sin(-math.pi/2+i*math.pi/3)) for i in range(6)]


def banner(cx, cy, w, h):
    k = h/2
    return [(cx-w/2, cy-k), (cx+w/2, cy-k), (cx+w/2+k, cy), (cx+w/2, cy+k), (cx-w/2, cy+k), (cx-w/2-k, cy)]


def fill(cv, pts, color, alpha=1.0, width=0, closed=True, add=False):
    m, px, py = poly_mask(pts, width, closed)
    (cv.add if add else cv.over)(px, py, solid(m, color, alpha))


def rect(cv, x, y, w, h, color, alpha=1.0, add=False):
    fill(cv, [(x, y), (x+w, y), (x+w, y+h), (x, y+h)], color, alpha, add=add)


def ellipse(cv, cx, cy, rx, ry, color, alpha=1.0, width=0, add=False):
    m, px, py = ellipse_mask(cx, cy, rx, ry, width)
    (cv.add if add else cv.over)(px, py, solid(m, color, alpha))


def glow(cv, mask, px, py, color, alpha, radius):
    b, pad = blur_mask(mask, radius)
    cv.over(px-pad, py-pad, solid(b, color, alpha))


# ---- fonts and text --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def font(kind, px):
    path, axes = FONTS[kind]
    if not os.path.exists(path): path, axes = FONTS['wide']
    f = fonts.truetype(path, px)
    if axes and fonts.variable('display'): f.set_variation_by_axes(list(axes))
    return f


@lru_cache(maxsize=8192)
def glyph_mask(s, kind, px, spacing, stroke):
    """Text mask at paint resolution: (mask, dx, dy from the baseline-left origin, advance)."""
    f = font(kind, px)
    parts = list(s) if spacing else [s]
    xs, x = [], 0.0
    for part in parts:
        xs.append(x); x += f.getlength(part)+spacing
    advance = x-(spacing if spacing else 0)
    probe = ImageDraw.Draw(Image.new('L', (1, 1)))
    l = t = 1e9; r = b = -1e9
    for part, ox in zip(parts, xs):
        bb = probe.textbbox((ox, 0), part, font=f, anchor='ls', stroke_width=stroke)
        l, t, r, b = min(l, bb[0]), min(t, bb[1]), max(r, bb[2]), max(b, bb[3])
    if r <= l: return np.zeros((1, 1), np.float32), 0, 0, advance
    l, t = math.floor(l)-1, math.floor(t)-1
    im = Image.new('L', (math.ceil(r)-l+2, math.ceil(b)-t+2)); d = ImageDraw.Draw(im)
    for part, ox in zip(parts, xs):
        d.text((ox-l, -t), part, font=f, fill=255, anchor='ls', stroke_width=stroke, stroke_fill=255)
    return np.asarray(im, np.float32)/255, l, t, advance


def squeeze(mask, left, q):
    """A text mask compressed horizontally by q about the text origin (off Windows only, see FONTS)."""
    im = Image.fromarray(mask).resize((max(1, int(round(mask.shape[1]*q))), mask.shape[0]), Image.LANCZOS)
    return np.clip(np.asarray(im, np.float32), 0, 1), left*q


def measure(s, size, spacing=0, kind='cond'):
    return glyph_mask(s, kind, int(round(size*S)), spacing*S, 0)[3]/S


def text(cv, s, x, y, *, size=16, kind='cond', align='left', spacing=0.0, color=WHITE, alpha=1.0, stroke=None,
         stroke_width=3, split=0, shadow=None, blur=8, max_w=None, min_size=11, min_spacing=0, record=None, card=None,
         theme=None):
    """The JS txt(): tracking, stroke, chromatic split, shadow and fit-to-width (tracking first, size last)."""
    if not s: return 0
    px = int(round(size*S))
    w = glyph_mask(s, kind, px, spacing*S, 0)[3]/S
    if max_w:
        while w > max_w and spacing > min_spacing:
            spacing = max(min_spacing, spacing-0.5); w = glyph_mask(s, kind, px, spacing*S, 0)[3]/S
        while w > max_w and size > min_size:
            size -= 0.5; px = int(round(size*S)); w = glyph_mask(s, kind, px, spacing*S, 0)[3]/S
    q = max(0.6, max_w/w) if SQUEEZE and max_w and w > max_w else 1   # last resort, off Windows only
    if q != 1: w *= q
    ox = x-w*{'left': 0, 'center': 0.5, 'right': 1}[align]
    bx, by = ox*S, y*S
    sw = int(round(stroke_width*S)) if stroke else 0
    first, l, t, _ = glyph_mask(s, kind, px, spacing*S, sw)
    if q != 1: first, l = squeeze(first, l, q)
    if shadow: glow(cv, first, bx+l, by+t, shadow[:3], alpha*shadow[3], blur/2)
    if stroke: cv.over(bx+l, by+t, solid(first, stroke[:3], alpha*stroke[3]))
    m, l, t, _ = glyph_mask(s, kind, px, spacing*S, 0)
    if q != 1: m, l = squeeze(m, l, q)
    if split:
        sides = (theme or THEMES['teams'])['sides']
        cv.over(bx+l-split*S, by+t, solid(m, sides[0][0], alpha*0.85)); cv.over(bx+l+split*S, by+t, solid(m, sides[1][1], alpha*0.85))
    cv.over(bx+l, by+t, solid(m, color[:3], alpha*(color[3] if len(color) > 3 else 1)))
    if record is not None:
        h = m.shape[0]
        record.append(dict(text=s, x0=nx((bx+l)/S), y0=ny((by+t)/S), x1=nx((bx+l+m.shape[1])/S), y1=ny((by+t+h)/S), card=card))
    return w


def split_name(base):
    i = base.find(' (')
    return (base, '') if i < 0 else (base[:i], base[i+2:].rstrip(')'))


# ---- portraits ---------------------------------------------------------------------------------
@lru_cache(maxsize=512)
def portrait(character_id, size):
    """Premultiplied (size*S)^2 float patch of the 64x64 RGBA portrait: 1:1 crisp at 64, smooth below."""
    from character_names import character_info
    path = character_info(character_id)['portrait_path']
    try:
        with Image.open(path) as src: im = src.convert('RGBA')
    except (OSError, TypeError, AttributeError):
        im = Image.new('RGBA', (64, 64), (34, 34, 34, 255))
    im = im.resize((size*S, size*S), Image.NEAREST if size == 64 else Image.BILINEAR)
    a = np.asarray(im, np.float32)/255
    a[..., :3] *= a[..., 3:4]
    return a


# ---- layout (design space) ---------------------------------------------------------------------
def state_for(view, message):
    heading, subtitle, footer = (tr(view[k]) for k in ('heading','subtitle','footer'))
    cards = []
    for c in view['cards']:
        info = c['info']
        cards.append(dict(id=info['character_id'], base=info['base_name'], form=info['form'] or '', side=c['side'],
                          slot=c['slot'], physical=c['physical'], role=tr(c['role']), human=c['role'].startswith('PLAYER'), number=c['slot']+1))
    side_names = [tr(g['label']) for g in view['groups']] or [tr('TEAM 1'), tr('TEAM 2')]
    return dict(mode=view['mode'], humans=view['humans'], cards=cards, heading=heading, subtitle=subtitle,
                footer=footer, message=tr(message), detail=tr(view['detail']) if view['detail'] else None, side_names=side_names)


def layout(s):
    """The JS layout(): items, hex centres, tags, entrance strips, rules, banners, message edge."""
    mode = s['mode']
    items, strips = [], []
    if mode == 'ffa':
        cards = sorted(s['cards'], key=lambda c: c['physical'])
        n = len(cards)
        cols, w, h, gx, gy = (3, 180, 120, 14, 14) if n <= 6 else (4, 135, 92, 6, 4)
        rows_n = (n+cols-1)//cols
        total = rows_n*h+(rows_n-1)*gy
        y0 = AREA[0]+(AREA[1]-total)/2
        rows = []
        for i, c in enumerate(cards):
            r, k = divmod(i, cols)
            in_row = min(cols, n-r*cols)
            x = 320-(in_row*w+(in_row-1)*gx)/2+k*(w+gx); y = round(y0+r*(h+gy))
            c = dict(c, number=i+1)   # contestants are numbered in physical order, not per side
            items.append(dict(card=c, side=c['physical'] % 2, compact=n > 6, grid=n <= 6, x=x, y=y, w=w, h=h, mirror=False, row=r))
            rows.append((r, y, h))
        rows = sorted(set(rows))
        for j, (r, y, hh) in enumerate(rows):
            top = AREA[0]-2 if j == 0 else (rows[j-1][1]+rows[j-1][2]+y)/2
            bottom = AREA[0]+AREA[1]+8 if j == len(rows)-1 else (y+hh+rows[j+1][1])/2
            strips.append(dict(x0=0, x1=DESIGN[0], y0=top, y1=bottom, start=int(round(ENT['cards']+ENT['step']*r)),
                               dx=SLIDE['cards']*(-1 if r % 2 == 0 else 1), dy=0))
        compact = n > 6
    else:
        counts = [sum(c['side'] == side for c in s['cards']) for side in (0, 1)]
        compact = max(counts) > 3
        for side in (0, 1):
            cx0, cw = COL[side]; n = counts[side]
            cards = sorted([c for c in s['cards'] if c['side'] == side], key=lambda c: c['slot'])
            rows = []
            if not compact:
                h, gap = 88, 8
                y0 = AREA[0]+(AREA[1]-(n*h+(n-1)*gap))/2
                for i, c in enumerate(cards):
                    y = round(y0+i*(h+gap))
                    items.append(dict(card=c, side=side, compact=False, grid=False, x=cx0, y=y, w=cw, h=h, mirror=side == 1, row=i)); rows.append((y, h))
            else:
                h, gap, gap_x = 92, 4, 6
                w = (cw-gap_x)/2; n_rows = (n+1)//2
                y0 = AREA[0]+(AREA[1]-(n_rows*h+(n_rows-1)*gap))/2
                for i, c in enumerate(cards):
                    r, k = divmod(i, 2); alone = r == n_rows-1 and n % 2 == 1
                    x = cx0+(cw-w)/2 if alone else cx0+k*(w+gap_x); y = round(y0+r*(h+gap))
                    items.append(dict(card=c, side=side, compact=True, grid=False, x=x, y=y, w=w, h=h, mirror=side == 1, row=r))
                    if r == len(rows): rows.append((y, h))
            for r, (y, hh) in enumerate(rows):
                top = AREA[0]-2 if r == 0 else (rows[r-1][0]+rows[r-1][1]+y)/2
                bottom = AREA[0]+AREA[1]+8 if r == len(rows)-1 else (y+hh+rows[r+1][0])/2
                strips.append(dict(x0=COL[1][0] if side else 0, x1=DESIGN[0] if side else COL[0][0]+COL[0][1], y0=top, y1=bottom,
                                   start=int(round(ENT['cards']+ENT['step']*r)), dx=SLIDE['cards']*(1 if side else -1), dy=0))
    for it in items:
        it['start'] = int(round(ENT['cards']+ENT['step']*it['row']))
        if it['compact'] or it['grid']:
            R = 24 if it['compact'] else 28
            it['hex'] = dict(cx=it['x']+it['w']/2, cy=it['y']+(36 if it['compact'] else 44), R=R)
            tw = measure(it['card']['role'], 11, 1)+10
            it['tag'] = dict(x=it['x']+4, y=it['y']-1, w=tw, h=14)
            it['boxes'] = [(it['x']+2, it['y']-3, it['x']+6+tw, it['y']+15)]
        else:
            it['hex'] = dict(cx=it['x']+it['w']-46 if it['mirror'] else it['x']+46, cy=it['y']+it['h']/2, R=32)
            it['tag'] = None; it['boxes'] = []
    sw = measure(s['subtitle'], 12, 3)
    lay = dict(items=items, strips=strips, compact=compact, rule=dict(L=320-sw/2-14, R=320+sw/2+14, y=65), banners=[])
    if mode != 'ffa':
        for side in (0, 1):
            cx0, cw = COL[side]; cx = cx0+cw/2
            n = sum(c['side'] == side for c in s['cards']); label = s['side_names'][side]
            tag = tr(f'{n} FIGHTER' + ('' if n == 1 else 'S'))
            main_w = max(74, measure(label, 13, 2)+22); tag_w = measure(tag, 11, 1)+18
            d = -1 if side else 1; total = main_w+tag_w+8
            lay['banners'].append(dict(cx=cx-d*(total/2-main_w/2), cy=88, w=main_w, tag_cx=cx+d*(total/2-tag_w/2), tag_w=tag_w, tag=tag, label=label))
    else:
        tag_w = measure(s['detail'] or '', 11, 2)+24
        lay['banners'].append(dict(cx=320, cy=88, w=tag_w, tag_cx=320, tag_w=tag_w, tag=s['detail'] or '', label=''))
    lay['msg_right'] = 320+measure(s['message'], 12, 3)/2
    return lay


# ---- background ---------------------------------------------------------------------------------
def nebula(cv, x, y, r, c, a):
    p, px, py = radial(x, y, r, r, [(0, c, a), (0.45, c, a*0.4), (1, c, 0)])
    cv.add(px, py, p)


def horizon_y(x):
    cx, cy, r = HORIZON
    return cy-math.sqrt(r*r-(x-cx)**2)


def planet(cv, theme):
    """Dark body below the limb (r 2000 arc, top y 392), atmosphere rim and surface lights."""
    cx, cy, r = HORIZON
    W, H = DESIGN
    y0 = 380
    xs = (np.arange(W*S, dtype=np.float32)+0.5)/S; ys = (np.arange((H-y0)*S, dtype=np.float32)+0.5)/S+y0
    d = np.sqrt((xs[None, :]-cx)**2+(ys[:, None]-cy)**2)
    body = np.clip(r+0.5-d, 0, 1).astype(np.float32)
    t = np.clip((d-(r-120))/120, 0, 1)
    stops = [(0, (0, 0, 4)), (0.75, (4, 6, 26)), (1, (13, 20, 64))]
    rgb = np.stack([np.interp(t, [s[0] for s in stops], [s[1][i]/255 for s in stops]) for i in range(3)], -1).astype(np.float32)
    cv.over(0, y0*S, shaded(body, rgb, np.ones(d.shape, np.float32)))
    pr = rand(21)
    for _ in range(140):
        x = pr()*W; y = horizon_y(x)+6+pr()*60
        c = (255, 200, 120) if pr() < 0.6 else (140, 200, 255); a = 0.12+pr()*0.3
        rect(cv, x, y, 1, 1, c, a)
    a, b = theme['sides'][0][0], theme['sides'][1][0]
    u = np.clip(xs/W, 0, 1)
    rim_rgb = np.stack([np.interp(u, [0, 0.5, 1], [a[i]/255, (200, 180, 255)[i]/255, b[i]/255]) for i in range(3)], -1).astype(np.float32)
    rim_rgb = np.broadcast_to(rim_rgb[None, :, :], d.shape+(3,))
    for off, width, alpha in ((0, 1.2, 0.9), (3, 8, 0.16), (10, 22, 0.07)):
        m = np.clip(width/2+0.5-np.abs(d-(r+off)), 0, 1).astype(np.float32)
        cv.add(0, y0*S, shaded(m, rim_rgb, np.full(d.shape, alpha, np.float32)))


def reticle(cv, cx, cy, R, theme, scale=1.0):
    a, b = theme['sides'][0][0], theme['sides'][1][0]
    for rr, w in ((R, 1), (R*92/84, 0.7)):
        m, px, py = poly_mask(hexagon(cx, cy, rr), w)
        cv.over(px, py, linear(m, px, py, cx-rr, 0, cx+rr, 0, [(0, a, 0.28), (1, b, 0.28)]))
    ellipse(cv, cx, cy, R*70/84, R*70/84, WHITE, 0.10, width=1)
    r0 = R*74/84
    for i in range(36):
        an = i*2*math.pi/36; L = (4 if i % 6 == 0 else 2)*scale
        fill(cv, [(cx+math.cos(an)*r0, cy+math.sin(an)*r0), (cx+math.cos(an)*(r0+L), cy+math.sin(an)*(r0+L))], WHITE, 0.18, width=1, closed=False)


def background_canvas(mode):
    theme = THEMES[mode]
    T0, T1 = theme['sides']; centre = theme['centre']
    W, H = DESIGN
    cv = Canvas(W*S, H*S)
    m = np.ones((H*S, W*S), np.float32)
    cv.over(0, 0, linear(m, 0, 0, 0, 0, 0, H, [(0, (11, 11, 48), 1), (0.45, (6, 6, 26), 1), (1, (0, 0, 8), 1)]))
    nebula(cv, 120, 230, 300, T0[1], 0.30); nebula(cv, 90, 130, 190, T0[0], 0.14); nebula(cv, 200, 330, 170, dim(T0[1], 0.35), 0.18)
    nebula(cv, 520, 240, 300, T1[1], 0.26); nebula(cv, 560, 130, 190, T1[0], 0.14); nebula(cv, 440, 330, 170, dim(T1[1], 0.35), 0.16)
    nebula(cv, 320, 150, 250, centre, 0.30); nebula(cv, 320, 300, 210, dim(centre, 0.35), 0.16)
    r = rand(7)
    for _ in range(620):
        x = r()*W; y = 20+r()*380; rr = 5+r()*32
        u = x/W
        c = mix(T0[1], centre, u*2) if u < 0.5 else mix(centre, T1[1], (u-0.5)*2)
        if r() < 0.25: c = mix(c, WHITE, 0.5)
        nebula(cv, x, y, rr, c, 0.025+r()*0.045)
    for _ in range(90):
        x = r()*W; y = 200+r()*200; rr = 12+r()*40
        p, px, py = radial(x, y, rr, rr, [(0, (2, 2, 12), 0.22), (1, (2, 2, 12), 0)]); cv.over(px, py, p)
    sr = rand(11)
    for _ in range(760):
        x = sr()*W; y = sr()*400; sz = 0.6+sr()*0.9; a = 0.25+sr()*0.6; tint = sr()
        c = (180, 210, 255) if tint < 0.2 else (255, 220, 190) if tint < 0.35 else WHITE
        rect(cv, x, y, sz, sz, c, a)
    for _ in range(110):
        x = sr()*W; y = sr()*400; rr = 0.9+sr()*0.7
        ellipse(cv, x, y, rr, rr, WHITE, 0.75+sr()*0.25)
    for _ in range(30):
        x = sr()*W; y = sr()*380; L = 5+sr()*9; hue = sr()
        c = (170, 220, 255) if hue < 0.33 else (255, 210, 170) if hue < 0.55 else WHITE
        nebula(cv, x, y, L*0.9, c, 0.55)
        ellipse(cv, x, y, 1.3, 1.3, WHITE, 1, add=True)
        for pts, (gx0, gy0, gx1, gy1) in (([(x-L, y-0.5), (x+L, y-0.5), (x+L, y+0.5), (x-L, y+0.5)], (x-L, y, x+L, y)),
                                          ([(x-0.5, y-L), (x+0.5, y-L), (x+0.5, y+L), (x-0.5, y+L)], (x, y-L, x, y+L))):
            mm, px, py = poly_mask(pts)
            cv.add(px, py, linear(mm, px, py, gx0, gy0, gx1, gy1, [(0, c, 0), (0.5, c, 0.9), (1, c, 0)]))
    if mode == 'ffa': reticle(cv, FFA_EMBLEM[0], FFA_EMBLEM[1], 30, theme, 0.6)
    else: reticle(cv, VS[0], VS[1], 84, theme)
    planet(cv, theme)
    B, M = 26, 10
    for x, y, sx, sy, side in ((M, M, 1, 1, 0), (W-M, M, -1, 1, 1), (M, H-M, 1, -1, 0), (W-M, H-M, -1, -1, 1)):
        fill(cv, [(x, y+sy*B), (x, y), (x+sx*B, y)], (160, 200, 255), 0.6, width=1.5, closed=False)
        fill(cv, [(x+sx*5, y+sy*15), (x+sx*5, y+sy*5), (x+sx*15, y+sy*5)], theme['sides'][side][0], 0.6, width=1, closed=False)
    return cv


@lru_cache(maxsize=8)
def background(mode):
    """Native RGB 512x448 background picture for a mode (static per mode, so cached)."""
    im = background_canvas(mode).image().convert('RGB')
    return im.resize(NATIVE, Image.LANCZOS)


# ---- foreground painters --------------------------------------------------------------------
def header(cv, s, lay, theme, rec):
    T0, T1 = theme['sides']
    text(cv, s['heading'], 320, 50, size=42, kind='heading', align='center', split=3, stroke=(0, 0, 20, 0.9), stroke_width=5,
         color=WHITE, spacing=1, shadow=theme['glow']+(0.6,), blur=14, max_w=560, min_size=30, record=rec, theme=theme)
    text(cv, s['subtitle'], 320, 69, size=12, kind='semi', align='center', spacing=3, color=(196, 214, 244), stroke=(0, 0, 20, 0.7), stroke_width=2,
         max_w=520, min_spacing=1, record=rec)
    L, R, y = lay['rule']['L'], lay['rule']['R'], lay['rule']['y']
    m, px, py = poly_mask([(140, y), (L, y), (L, y+1), (140, y+1)])
    cv.over(px, py, linear(m, px, py, 140, 0, L, 0, [(0, T0[0], 0), (1, T0[0], 0.7)]))
    m, px, py = poly_mask([(R, y), (500, y), (500, y+1), (R, y+1)])
    cv.over(px, py, linear(m, px, py, R, 0, 500, 0, [(0, T1[0], 0.7), (1, T1[0], 0)]))
    for x in (L, R): fill(cv, [(x, 62), (x+3, 65.5), (x, 69), (x-3, 65.5)], (207, 226, 255))


def banners(cv, s, lay, theme, rec):
    for side in (0, 1):
        cx0, cw = COL[side]; T = theme['sides'][side]; b = lay['banners'][side]
        cy, main_w, tag_w, tag_cx, main_cx = b['cy'], b['w'], b['tag_w'], b['tag_cx'], b['cx']
        if side: fill(cv, [(main_cx+main_w/2+10, cy), (cx0+cw, cy)], T[0], 0.55, width=1, closed=False)
        else: fill(cv, [(cx0, cy), (main_cx-main_w/2-10, cy)], T[0], 0.55, width=1, closed=False)
        if side: fill(cv, [(tag_cx-tag_w/2-8, cy), (cx0-2, cy)], T[0], 0.3, width=1, closed=False)
        else: fill(cv, [(tag_cx+tag_w/2+8, cy), (cx0+cw+2, cy)], T[0], 0.3, width=1, closed=False)
        m, px, py = poly_mask(banner(main_cx, cy, main_w, 20))
        glow(cv, m, px, py, T[0], 0.8, 5)
        cv.over(px, py, linear(m, px, py, main_cx-main_w/2, 0, main_cx+main_w/2, 0, [(0, T[1], 1), (1, T[0], 1)]))
        fill(cv, banner(main_cx, cy, main_w, 20), WHITE, 0.7, width=1)
        cv.over(px, py, linear(m, px, py, 0, cy-10, 0, cy, [(0, WHITE, 0.35), (1, WHITE, 0)]))
        text(cv, b['label'], main_cx, cy+5, size=13, align='center', spacing=2, color=WHITE, stroke=(0, 0, 30, 0.6), stroke_width=2.5, record=rec)
        fill(cv, banner(tag_cx, cy, tag_w, 16), (6, 8, 26), 0.85)
        fill(cv, banner(tag_cx, cy, tag_w, 16), T[0], 0.8, width=1)
        text(cv, b['tag'], tag_cx, cy+4, size=11, kind='semi', align='center', spacing=1, color=T[0], record=rec)


def detail_line(cv, s, lay, theme, rec):
    """ffa: the fighter-count detail in a centred tag with rules out to the column edges."""
    T = theme['sides'][0]; b = lay['banners'][0]; cy, w = b['cy'], b['w']
    for x0, x1 in ((22, 320-w/2-16), (320+w/2+16, 618)):
        m, px, py = poly_mask([(x0, cy), (x1, cy), (x1, cy+1), (x0, cy+1)])
        cv.over(px, py, linear(m, px, py, x0, 0, x1, 0, [(0, T[0], 0.55 if x0 > 300 else 0), (0.5, T[0], 0.55), (1, T[0], 0 if x0 > 300 else 0.55)]))
    fill(cv, banner(320, cy, w, 16), (6, 8, 26), 0.85)
    fill(cv, banner(320, cy, w, 16), T[0], 0.8, width=1)
    text(cv, b['tag'], 320, cy+4, size=11, kind='semi', align='center', spacing=2, color=T[0], record=rec)


def panel(cv, it, T):
    x, y, w, h = it['x'], it['y'], it['w'], it['h']; c = 7 if it['compact'] else 9
    pts = chamfer(x, y, w, h, c)
    m, px, py = poly_mask(pts)
    glow(cv, m, px, py, T[0], 0.55, 6)
    cv.over(px, py, solid(m, (6, 8, 28), 0.70))
    cv.over(px, py, linear(m, px, py, 0, y, 0, y+h, [(0, WHITE, 0.07), (0.4, WHITE, 0), (1, (0, 0, 10), 0.25)]))
    fill(cv, pts, T[0], 0.75, width=1.2)
    fill(cv, chamfer(x+3, y+3, w-6, h-6, c-2), WHITE, 0.12, width=1)
    ox = x+w if it['mirror'] else x; d = -1 if it['mirror'] else 1
    fill(cv, [(ox+d*c, y), (ox, y+c)], T[0], 1, width=2, closed=False)
    fill(cv, [(ox, y+h-c), (ox+d*c, y+h)], T[0], 1, width=2, closed=False)
    hx = x if it['mirror'] else x+w
    hatch = np.zeros(m.shape, np.float32)
    for i in range(6):
        o = i*5
        hm, hpx, hpy = poly_mask([(hx, y+h-30+o), (hx-d*(30-o), y+h)], 1, closed=False)
        sub = Canvas(m.shape[1], m.shape[0]); sub.over(hpx-px, hpy-py, solid(hm, WHITE))
        hatch = np.maximum(hatch, sub.a[..., 3])
    cv.over(px, py, solid(hatch*m, T[0], 0.10))


def hex_frame(cv, it, T):
    cx, cy, R = it['hex']['cx'], it['hex']['cy'], it['hex']['R']
    size = 2*R
    m, px, py = poly_mask(hexagon(cx, cy, R))
    cv.over(px, py, solid(m, (16, 18, 40)))
    p = portrait(it['card']['id'], size).copy()
    sub = Canvas(m.shape[1], m.shape[0]); sub.over(round((cx-R)*S)-px, round((cy-R)*S)-py, p)
    cv.over(px, py, sub.a*m[..., None])
    v, vx, vy = radial(cx, cy, R, R, [(0, (0, 0, 10), 0), (1, (0, 0, 10), 0.35)], r0=0.55)
    sub = Canvas(m.shape[1], m.shape[0]); sub.over(vx-px, vy-py, v); cv.over(px, py, sub.a*m[..., None])
    fill(cv, hexagon(cx, cy, R), WHITE, 0.7, width=1)
    n = 18 if it['compact'] else 24
    for i in range(n):
        a = -math.pi/2+i*2*math.pi/n; r0 = R+2; r1 = R+(3.5 if i % 3 else 4.5)
        fill(cv, [(cx+math.cos(a)*r0, cy+math.sin(a)*r0), (cx+math.cos(a)*r1, cy+math.sin(a)*r1)], T[0], 0.8, width=1, closed=False)
    om, opx, opy = poly_mask(hexagon(cx, cy, R+6), 1.6 if it['compact'] else 2)
    glow(cv, om, opx, opy, T[0], 0.9, 3)
    cv.over(opx, opy, solid(om, T[0]))
    for a in (-math.pi/2, math.pi/2):
        ellipse(cv, cx+math.cos(a)*(R+6), cy+math.sin(a)*(R+6), 1.6, 1.6, WHITE)


def role_tag(cv, x, y, role, T, align_right=False, solid_fill=False, pad=14, rec=None, card=None):
    w = measure(role, 11, 1)+pad; h = 14
    x0 = x-w if align_right else x
    pts = chamfer(x0, y, w, h, 3)
    if solid_fill: fill(cv, pts, (6, 8, 28), 0.96)
    fill(cv, pts, T[1], 0.22)
    fill(cv, pts, T[0], 0.85, width=1)
    text(cv, role, x0+w/2, y+11, size=11, kind='semi', align='center', spacing=1, color=WHITE, record=rec, card=card)
    return w


def name_lines(cv, it, T, tx, y_name, y_form, max_w, name_size, form_size, align, rec, idx):
    c = it['card']; main, qual = split_name(c['base'])
    M, Q, F = main.upper(), qual.upper(), c['form'].upper()
    compact = it['compact'] or it['grid']
    name_o = dict(size=name_size, align=align, color=WHITE, stroke=(0, 0, 20, 0.8), stroke_width=2.5 if compact else 3, spacing=0 if compact else 0.5, record=rec, card=idx)
    qual_o = dict(size=12, align=align, color=(255, 255, 255, 0.75), kind='semi', stroke=(0, 0, 20, 0.7), stroke_width=2, spacing=0.5, record=rec, card=idx)
    form_line, drawn = F, False
    if Q:
        mw = measure(M, name_size, name_o['spacing']); qw = measure(Q, 12, 0.5, 'semi')
        if not compact and mw+8+qw <= max_w:
            if it['mirror']: text(cv, Q, tx, y_name, **qual_o); text(cv, M, tx-qw-8, y_name, **name_o)
            else: text(cv, M, tx, y_name, **name_o); text(cv, Q, tx+mw+8, y_name, **qual_o)
            drawn = True
        elif not F:
            text(cv, M, tx, y_name, max_w=max_w, min_size=13, min_spacing=-0.3, **name_o); form_line = Q; drawn = True
        else:
            combo = Q+' / '+F
            if measure(combo, form_size-1, -0.3, 'semi') <= max_w:
                text(cv, M, tx, y_name, max_w=max_w, min_size=13, min_spacing=-0.3, **name_o); form_line = combo; drawn = True
    if not drawn:
        text(cv, c['base'].upper(), tx, y_name, max_w=max_w, min_size=11 if compact else 13, min_spacing=-0.3, **name_o)
    if form_line:
        text(cv, form_line, tx, y_form, size=form_size, align=align, max_w=max_w, min_size=11, min_spacing=-0.3, color=T[0],
             spacing=0.8 if compact else 1.2, kind='semi', stroke=(0, 0, 20, 0.7), stroke_width=2, record=rec, card=idx)
    return bool(form_line)


def card(cv, it, theme, rec, idx):
    T = theme['sides'][it['side']] if it['side'] in (0, 1) else theme['sides'][0]
    if theme is THEMES['ffa']: T = theme['sides'][0]
    c = it['card']; x, y, w, h = it['x'], it['y'], it['w'], it['h']
    tag_T = GOLD if c.get('human',False) else T
    panel(cv, it, T)
    if it['grid']:
        text(cv, str(c['number']).zfill(2), x+w-10, y+h-8, size=22, align='right', color=T[0]+(0.16,), record=rec, card=idx)
        has_form = name_lines(cv, it, T, x+w/2, y+96, y+110, w-14, 15, 11, 'center', rec, idx)
        if not has_form:
            for i in range(9): rect(cv, x+w/2-22+i*5, y+105, 3, 1, T[0], 0.35)
    elif not it['compact']:
        tx = x+w-96 if it['mirror'] else x+96; align = 'right' if it['mirror'] else 'left'; tw = w-104
        text(cv, str(c['number']).zfill(2), x+12 if it['mirror'] else x+w-12, y+h-8, size=30, align='left' if it['mirror'] else 'right',
             color=T[0]+(0.16,), record=rec, card=idx)
        has_form = name_lines(cv, it, T, tx, y+35, y+52, tw, 20, 12, align, rec, idx)
        if not has_form:
            for i in range(12): rect(cv, tx-3-i*5 if it['mirror'] else tx+i*5, y+48, 3, 1, T[0], 0.35)
        role_tag(cv, tx, y+59, c['role'], tag_T, it['mirror'], rec=rec, card=idx)
    else:
        has_form = name_lines(cv, it, T, x+w/2, y+79, y+89, w-4, 13, 11, 'center', rec, idx)
        if not has_form:
            for i in range(7): rect(cv, x+w/2-17+i*5, y+85, 3, 1, T[0], 0.35)
    hex_frame(cv, it, T)
    if it['tag']: role_tag(cv, it['tag']['x'], it['tag']['y'], c['role'], tag_T, False, True, 10, rec=rec, card=idx)


def orb_base(cv, cx, cy, r, T):
    p, px, py = radial(cx, cy, r, r, [(0, (24, 40, 110), 1), (1, (6, 8, 30), 1)]); cv.over(px, py, p)
    ellipse(cv, cx, cy, r, r, WHITE, 0.55, width=1)
    ellipse(cv, cx, cy, r+4, r+4, T[0], 0.8, width=1)
    for i in range(4):
        a = math.pi/4+i*math.pi/2
        fill(cv, [(cx+math.cos(a)*(r+6), cy+math.sin(a)*(r+6)), (cx+math.cos(a)*(r+9), cy+math.sin(a)*(r+9))], T[0], 0.6, width=1, closed=False)


ERROR_RED, ERROR_PALE = (255, 86, 86), (255, 218, 218)


def error_footer(cv, s, theme, rec):
    """The failure state: a dark band with red rules and two red lines, no gauge (additive)."""
    first, second = (list(s['error']) + ['', ''])[:2]
    m, px, py = poly_mask([(0, 398), (640, 398), (640, 478), (0, 478)])
    cv.over(px, py, solid(m, (14, 0, 6), 0.82))
    for y in (398, 477):
        m, px, py = poly_mask([(22, y), (618, y), (618, y+1), (22, y+1)])
        cv.over(px, py, linear(m, px, py, 22, 0, 618, 0, [(0, ERROR_RED, 0), (0.5, ERROR_RED, 0.9), (1, ERROR_RED, 0)]))
    text(cv, first, 320, 431, size=16, align='center', spacing=2, color=ERROR_RED, stroke=(24, 0, 0, 0.9), stroke_width=3,
         max_w=600, min_size=10, min_spacing=0, record=rec)
    text(cv, second, 320, 462, size=12, kind='semi', align='center', spacing=2, color=ERROR_PALE, stroke=(24, 0, 0, 0.7),
         stroke_width=2, max_w=600, min_size=9, min_spacing=0, record=rec)


def footer(cv, s, lay, theme, rec):
    if s.get('error'): return error_footer(cv, s, theme, rec)
    G = GAUGE
    fw = measure(s['footer'], 14, 4)
    text(cv, s['footer'], 320, 411, size=14, align='center', spacing=4, color=(238, 244, 255), stroke=(0, 0, 20, 0.8), stroke_width=3, record=rec)
    L, R = 320-fw/2-12, 320+fw/2+12
    for x0, x1, stops in ((22, L, [(0, (160, 200, 255), 0), (0.5, (160, 200, 255), 0.6), (1, (160, 200, 255), 0.6)]),
                          (R, 618, [(0, (160, 200, 255), 0.6), (0.5, (160, 200, 255), 0.6), (1, (160, 200, 255), 0)])):
        m, px, py = poly_mask([(x0, 406), (x1, 406), (x1, 407), (x0, 407)])
        cv.over(px, py, linear(m, px, py, x0, 0, x1, 0, stops))
    pts = chamfer(G['x0'], G['y'], G['x1']-G['x0'], G['h'], 5)
    m, px, py = poly_mask(pts)
    glow(cv, m, px, py, theme['sides'][0][0], 0.35, 4)
    cv.over(px, py, solid(m, (2, 4, 18), 0.9))
    fill(cv, pts, (140, 200, 255), 0.55, width=1)
    for i in range(21):
        x = G['x0']+3+(G['x1']-G['x0']-6)*i/20; L2 = 6 if i % 5 == 0 else 3
        rect(cv, x, G['y']-2-L2, 1, L2, (160, 200, 255), 0.6); rect(cv, x, G['y']+G['h']+2, 1, L2, (160, 200, 255), 0.6)
    orb_base(cv, G['cx'], G['cy'], G['r'], theme['sides'][0])
    text(cv, s['message'], 320, 463, size=12, kind='semi', align='center', spacing=3, color=(159, 184, 222), stroke=(0, 0, 20, 0.6), stroke_width=2,
         max_w=560, min_spacing=0, record=rec)


VS_SIZE = 112


@lru_cache(maxsize=8)
def vs_sprite(mode):
    """The JS vsSprite: plate, rim glow, dark stroke, chromatic fringe, white->ki-yellow fill, leaned."""
    theme = THEMES[mode]
    cx = cy = VS_SIZE/2
    cv = Canvas(VS_SIZE*S, VS_SIZE*S)
    p, px, py = radial(cx, cy, 42, 42*0.7, [(0, (6, 4, 30), 0.6), (0.55, (6, 4, 30), 0.4), (1, (6, 4, 30), 0)]); cv.over(px, py, p)
    tcv = Canvas(VS_SIZE*S, VS_SIZE*S)
    px_ = 54*S; bx, by = cx*S, (cy+18)*S   # 54 px: the browser's Bahnschrift 46 renders fatter than PIL's
    m, l, t, adv = glyph_mask('VS', 'wide', px_, 0, 0)
    ox = bx-adv/2
    rim, rl, rt, _ = glyph_mask('VS', 'wide', px_, 0, 10*S//2)
    tcv.add(ox+rl, by+rt, solid(rim, WHITE, 0.35))
    dark, dl, dt, _ = glyph_mask('VS', 'wide', px_, 0, 6*S//2)
    tcv.over(ox+dl, by+dt, solid(dark, (8, 4, 32), 0.95))
    tcv.over(ox+l-4.5*S, by+t, solid(m, theme['sides'][0][0], 0.85)); tcv.over(ox+l+4.5*S, by+t, solid(m, theme['sides'][1][1], 0.85))
    tcv.over(ox+l, by+t, linear(m, ox+l, by+t, 0, cy+16-34, 0, cy+16, [(0, WHITE, 1), (1, (255, 224, 138), 1)]))
    im = tcv.image().transform(tcv.image().size, Image.AFFINE, (1, 0.18, -0.18*by, 0, 1, 0), Image.BICUBIC)
    cv.over(0, 0, np.asarray(im, np.float32)/255)
    return cv.a


# ---- atlas -------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def atlas():
    """(premultiplied uint8 RGBA 32 x 256, table) - digits, soft dot and streak, atlas-local u/v."""
    cv = Canvas(ATLAS_DESIGN[0]*S, ATLAS_DESIGN[1]*S)
    table = dict(digits={}, dot=None, streak=None)
    cw, ch = CELL
    px = 22*S
    for i, ch_ in enumerate(DIGITS):
        x = i*cw+6; y = 23   # 6 px inset: the resample spreads the stroke ~2 px, the cell edge must stay clear
        # Off Windows Liberation's digits are wider than condensed Bahnschrift's: compress them to the
        # same widths (SQUEEZE) so '%' stays in its cell and '100%' still ends left of the gauge channel.
        fit = dict(max_w=13 if ch_ == '%' else 9.5, min_size=22) if SQUEEZE else {}
        text(cv, ch_, x, y, size=22, color=WHITE, stroke=(0, 0, 20, 0.85), stroke_width=3, **fit)
        table['digits'][ch_] = dict(u=nx(i*cw), v=0, w=nx(cw), h=ny(ch), adv=0, x_off=nx(6), y_off=ny(23))
    dx = len(DIGITS)*cw
    p, ppx, ppy = radial(dx+8, 8, 8, 8, [(0, WHITE, 1), (0.25, WHITE, 0.55), (0.6, WHITE, 0.12), (1, WHITE, 0)]); cv.over(ppx, ppy, p)
    table['dot'] = dict(u=nx(dx), v=0, w=nx(16), h=ny(16))
    sx = dx+20
    m = np.ones((22*S, 6*S), np.float32)
    v = linear(m, sx*S, 0, 0, 0, 0, 22, [(0, WHITE, 0), (0.35, WHITE, 1), (1, WHITE, 0)])
    u = linear(m, sx*S, 0, sx, 0, sx+6, 0, [(0, WHITE, 0), (0.5, WHITE, 1), (1, WHITE, 0)])
    v *= u[..., 3:4]
    cv.over(sx*S, 0, v)
    table['streak'] = dict(u=nx(sx), v=0, w=nx(6), h=ny(22))
    assert table['streak']['u']+table['streak']['w'] <= ATLAS[0]
    rows = np.zeros((ATLAS[1], ATLAS[0], 4), np.uint8)
    rows[:ATLAS_ROWS] = np.asarray(cv.image().resize((ATLAS[0], ATLAS_ROWS), Image.LANCZOS), np.uint8)
    # Pen advances come from the RESAMPLED ink, not the font's own advance: each glyph carries a
    # 3 px dark stroke, so a cell blitted at the bare advance paints that stroke over the
    # previous digit's bowl (visible at full alpha). The measured ink already includes ~2 px of
    # stroke on each side, so one pixel less lets neighbouring strokes merge - the outlined look -
    # while every fill stays clear, and '100%' still ends left of the gauge channel.
    for ch_, g in table['digits'].items():
        cell = rows[:ATLAS_ROWS, g['u']:g['u']+g['w'], 3]
        columns = np.nonzero(cell.max(axis=0) > 8)[0]
        left, right = (int(columns[0]), int(columns[-1])+1) if len(columns) else (g['x_off'], g['x_off']+1)
        g.update(x_off=left, adv=max(4, right-left-1))
    return rows, table


def gauge_digits(progress):
    """Up to four atlas sprite entries (u, v, w, h, x, y native) for floor(progress)%."""
    p = max(0, min(100, int(progress)))
    table = atlas()[1]['digits']
    x = GAUGE['pct_x']*0.8
    out = []
    for ch in f'{p}%':
        g = table[ch]
        out.append(dict(u=g['u'], v=g['v'], w=g['w'], h=g['h'], x=int(round(x))-g['x_off'], y=ny(GAUGE['cy']+8)-g['y_off']))
        x += g['adv']
    return out[:4]


# ---- native conversion of the painted foreground -------------------------------------------
def straight_alpha(premul, bleed=6):
    """Premultiplied uint8 RGBA -> straight alpha; alpha-0 pixels take their nearest opaque
    neighbour's RGB (up to `bleed` px, 4-connected) so bilinear edges keep the text colour."""
    a = premul[..., 3].astype(np.float32)
    rgb = premul[..., :3].astype(np.float32)
    scale = np.where(a > 0, 255/np.maximum(a, 1), 0)
    rgb = np.minimum(255, rgb*scale[..., None]+0.5).astype(np.uint8)
    filled = a > 0
    for _ in range(bleed):
        if filled.all(): break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src = np.roll(rgb, (dy, dx), axis=(0, 1)); sf = np.roll(filled, (dy, dx), axis=(0, 1))
            take = ~filled & sf
            rgb[take] = src[take]; filled |= take
    out = np.empty(premul.shape, np.uint8); out[..., :3] = rgb; out[..., 3] = premul[..., 3]
    return out


def foreground_image(cv):
    """Foreground canvas -> (native RGBA 512x448 screen, RGBA 256x32 atlas, atlas table)."""
    screen = np.asarray(cv.image().resize(NATIVE, Image.LANCZOS), np.uint8)
    rows, table = atlas()
    return Image.fromarray(straight_alpha(screen), 'RGBA'), Image.fromarray(straight_alpha(rows), 'RGBA'), table


# ---- slices ----------------------------------------------------------------------------------
def slices_for(lay, mode, has_vs):
    """Entrance slices (design rects + timing) -> native, disjoint, tiling 512x448."""
    W, H = DESIGN
    top, bottom = AREA[0]-2, AREA[0]+AREA[1]+8
    out = [dict(box=(0, 0, W, 78), start=ENT['header'], dx=0, dy=SLIDE['header'])]
    if mode == 'ffa': out.append(dict(box=(0, 78, W, top), start=ENT['banners'], dx=0, dy=-12))
    else:
        out.append(dict(box=(0, 78, 320, top), start=ENT['banners'], dx=-SLIDE['banners'], dy=0))
        out.append(dict(box=(320, 78, W, top), start=ENT['banners'], dx=SLIDE['banners'], dy=0))
    for st in lay['strips']:
        out.append(dict(box=(st['x0'], st['y0'], st['x1'], st['y1']), start=st['start'], dx=st['dx'], dy=st['dy']))
    if mode == 'ffa' and not lay['strips']: out.append(dict(box=(0, top, W, bottom), start=0, dx=0, dy=0))
    if mode != 'ffa':
        cx0, cx1 = COL[0][0]+COL[0][1], COL[1][0]
        for side, (x0, x1) in enumerate(((0, cx0), (cx1, W))):
            if not any(st['x0'] == x0 for st in lay['strips']):
                out.append(dict(box=(x0, top, x1, bottom), start=0, dx=0, dy=0))
        if has_vs:
            out.append(dict(box=(cx0, 189, cx1, 301), start=ENT['vs'], dx=0, dy=0))
            out.append(dict(box=(cx0, top, cx1, 189), start=0, dx=0, dy=0)); out.append(dict(box=(cx0, 301, cx1, bottom), start=0, dx=0, dy=0))
        else: out.append(dict(box=(cx0, top, cx1, bottom), start=0, dx=0, dy=0))
    out.append(dict(box=(0, bottom, W, H), start=ENT['footer'], dx=0, dy=SLIDE['footer']))
    slices = []
    for i, sl in enumerate(out):
        x0, y0, x1, y1 = sl['box']
        X0, Y0, X1, Y1 = nx(x0), ny(y0), nx(x1), ny(y1)
        slices.append(dict(index=i, x=X0, y=Y0, w=X1-X0, h=Y1-Y0, u=X0, v=Y0, start=int(sl['start']), dx=nx(sl['dx']), dy=ny(sl['dy'])))
    assert len(slices) <= 14, len(slices)
    return slices


# ---- lights plan ------------------------------------------------------------------------------
def ribbon_profile(f):
    return f/0.2 if f < 0.2 else 1-0.1*(f-0.2)/0.35 if f < 0.55 else 0.9-0.5*(f-0.55)/0.3 if f < 0.85 else 0.4*(1-f)/0.15


def ribbons_for(mode, theme):
    """The JS RIBBONS constants (seed 101), in guest integer units; ffa uses fixed centres."""
    r = rand(101)
    out = []
    if mode == 'ffa': specs = [(k % 2, x) for k, x in enumerate(FFA_RIBBON_X)]
    else: specs = [(side, COL[side][0]+COL[side][1]/2+(10 if side else -10)) for side in (0, 1) for _ in range(3)]
    for k, (side, cx) in enumerate(specs):
        cx = cx+(r()-0.5)*40 if mode != 'ffa' else cx+(r()-0.5)*20
        A1 = 55+r()*50; f1 = 0.010+r()*0.008; w1 = 0.55+r()*0.5; p1 = r()
        A2 = 26+r()*24; f2 = 0.022+r()*0.012; w2 = 0.9+r()*0.7; p2 = r()
        width = (84, 60, 40)[k % 3]+r()*10; wf = 0.015+r()*0.01; wp = r(); alpha = (0.6, 0.66, 0.75)[k % 3]; r()
        T = theme['sides'][side]
        deep, bright = T[1], mix(T[0], WHITE, 0.2)
        colors = []
        for i in range(17):
            f = i/16; m = max(0, min(1, (f-0.15)/0.4)); k_ = ribbon_profile(f)*alpha
            colors.append(tuple(int(round(v*k_)) for v in mix(deep, bright, m)))
        length = 430-56
        per_i16 = 256/(2*math.pi)*length/16/16     # radians per design px -> 1/256 turn per i16 unit
        out.append(dict(side=side, x0=nx(cx), x1=nx(cx), y0=ny(430), y1=ny(56), A1=nx(A1), A2=nx(A2),
                        f1=max(1, int(round(f1*per_i16))), f2=max(1, int(round(f2*per_i16))),
                        w1=max(1, int(round(w1*256/(2*math.pi)/60*8))), w2=max(1, int(round(w2*256/(2*math.pi)/60*8))),
                        p1=int(p1*256) & 255, p2=int(p2*256) & 255, W=nx(width), wf=max(1, int(round(wf*per_i16*16))),
                        wp=int(wp*256) & 255, fade_start=21, fade_end=75, colors=colors))
    return out


def sparks_for(n_ribbons):
    r = rand(202)
    out = []
    for i in range(128):
        u = r(); speed = 0.10+r()*0.28; r(); sz = 1.6+r()*2.4; streak = r() < 0.4; tw = r(); ph = r()
        out.append(dict(ribbon=i % n_ribbons, u=int(u*128) & 127, speed=max(1, int(round(speed*512/60))), phase=int(ph*128) & 127,
                        size=max(3, min(6, int(round((3+sz*1.6)*0.8)))), streak=int(streak), twinkle=int(tw*256) & 255))
    return out


def lights_for(s, lay, mode, theme, table):
    T0, T1 = theme['sides']
    W, H = DESIGN
    if mode == 'ffa': ox, oy, R = FFA_EMBLEM
    else: ox, oy, R = VS[0], VS[1], 36
    off = 26*R/36
    orbs = []
    for side, (cx, fy) in enumerate(((ox-off, 106 if mode != 'ffa' else 0), (ox+off, 384 if mode != 'ffa' else 88))):
        T = theme['sides'][side]
        orbs.append(dict(side=side, cx=nx(cx), cy=ny(oy), rx=nx(R), ry=ny(R), core=WHITE, team=T[0], deep=T[1], halo=T[1], flight_y=ny(fy)))
    ribbons = ribbons_for(mode, theme)
    if mode == 'ffa': regions = [dict(x0=0, y0=ny(56), x1=nx(320), y1=ny(430)), dict(x0=nx(320), y0=ny(56), x1=W*4//5, y1=ny(430))]
    else: regions = [dict(x0=0, y0=ny(56), x1=nx(320), y1=ny(430)), dict(x0=nx(320), y0=ny(56), x1=nx(W), y1=ny(430))]
    flank = 0.9*R; a0 = 1.15
    bolts = []
    for top in (-1, 1):
        y = oy+top*math.sin(a0)*flank
        bolts.append(dict(x0=nx(ox-off-math.cos(a0)*flank), y0=ny(y), x1=nx(ox+off+math.cos(a0)*flank), y1=ny(y), bulge=ny(top*39*R/36),
                          period=63, duration=8, color=WHITE, glow=(170, 150, 255)))
    ticks = []
    for it in lay['items'][:12]:
        T = theme['sides'][it['side']] if mode != 'ffa' else theme['sides'][0]
        hx = it['hex']; rr = hx['R']+(8 if it['compact'] else 9)
        box = it['boxes'][0] if it['boxes'] else (0, 0, 0, 0)
        ticks.append(dict(cx=nx(hx['cx']), cy=ny(hx['cy']), rx=nx(rr), ry=ny(rr), n=16 if it['compact'] else 24,
                          direction=-1 if it['side'] else 1, color=tuple(int(v*0.85) for v in T[0]),
                          box=(nx(box[0]), ny(box[1]), nx(box[2]), ny(box[3])), cursor=WHITE))
    G = GAUGE
    gauge = dict(x0=nx(G['x0']+3), x1=nx(G['x1']-3), y0=ny(G['y']+3), y1=ny(G['y']+G['h']-3), colors=[T0[1], T0[0], WHITE], tip=WHITE,
                 orb=dict(cx=nx(G['cx']), cy=ny(G['cy']), rx=nx(G['r']), ry=ny(G['r']), color=T0[0]),
                 pct_x=nx(G['pct_x'])-table['digits']['0']['x_off'], pct_y=ny(G['cy']+8)-table['digits']['0']['y_off'])
    sheens = [dict(x0=nx(b['cx']-b['w']/2), y0=ny(b['cy']-10), x1=nx(b['cx']+b['w']/2), y1=ny(b['cy']+10)) for b in lay['banners'][:2]]
    if len(sheens) == 1: sheens.append(dict(sheens[0]))
    return dict(
        fade=dict(color=(0, 0, 4), frames=24),
        ribbons=ribbons, sparks=dict(regions=regions, entries=sparks_for(len(ribbons))), orbs=orbs,
        seam=dict(cx=nx(ox), cy=ny(oy), rx=nx(22*R/36), ry=ny(40*R/36), color=WHITE, edge=(220, 200, 255)),
        ring=dict(cx=nx(ox), cy=ny(oy), left=T0[0], right=T1[0], inner=WHITE, life=90, first=54, cycle=150),
        flash=dict(cx=nx(ox), cy=ny(oy), rx=nx(150*R/36), ry=ny(150*R/36), color=WHITE, edge=(200, 190, 255), start=54, frames=18),
        bolts=bolts,
        chevrons=dict(cx=nx(ox), cy=ny(oy), offset=ny(66*R/36), pitch=ny(22*R/36), count=4, colors=[T0[0], T1[0]], period=50, stagger=21),
        ticks=ticks, gauge=gauge, sheens=sheens,
        dots=dict(x=nx(lay['msg_right']+8), y=ny(459), pitch=nx(7), size=2, color=(160, 200, 255)),
        atlas=table)


# ---- compose ----------------------------------------------------------------------------------
def compose(teams=(), progress=0, message='LOADING YOUR FIGHTERS', *, mode='teams', humans=1, portrait_colors=None, decorations=None,
            error=None):
    """Pictures, entrance slices, the lights plan and text boxes for one screen.

    error=(line 1, line 2) draws the failure state instead of the gauge: red text, translated first
    and then fitted to the width (never cut), no gauge and no loading dots."""
    view = _design(teams, mode, humans)
    mode = view['mode']; theme = THEMES[mode]
    s = state_for(view, str(message).upper()[:60])
    if error: s = dict(s, error=tuple(tr(str(line)).upper() for line in tuple(error)[:2]))
    lay = layout(s)
    rec = []
    cv = Canvas(DESIGN[0]*S, DESIGN[1]*S)
    header(cv, s, lay, theme, rec)
    if mode == 'ffa': detail_line(cv, s, lay, theme, rec)
    else: banners(cv, s, lay, theme, rec)
    for i, it in enumerate(lay['items']): card(cv, it, theme, rec, i)
    has_vs = mode != 'ffa'
    if has_vs:
        sprite = vs_sprite(mode)
        x0, y0 = (VS[0]-VS_SIZE/2)*S, (VS[1]-VS_SIZE/2)*S
        cx0, cx1 = (COL[0][0]+COL[0][1])*S, COL[1][0]*S
        clip = sprite[:, int(cx0-x0):int(cx1-x0)]
        cv.over(cx0, y0, clip)
    footer(cv, s, lay, theme, rec)
    fg, atlas_image, table = foreground_image(cv)
    slices = slices_for(lay, mode, has_vs)
    cards = []
    for it in lay['items']:
        c = it['card']
        cards.append(dict(x0=nx(it['x']), y0=ny(it['y']-3), x1=nx(it['x']+it['w']), y1=ny(it['y']+it['h']), name=c['base'], form=c['form'],
                          role=c['role'], side=it['side'], hex=(nx(it['hex']['cx']), ny(it['hex']['cy']))))
    lights = lights_for(s, lay, mode, theme, table)
    if error: lights = dict(lights, gauge=None, dots=None)   # a stopped setup shows no progress
    return dict(background=background(mode), foreground=fg, atlas_image=atlas_image, slices=slices, lights=lights,
                text=rec, cards=cards, atlas=table, mode=mode, humans=view['humans'], progress=max(0, min(100, int(progress))))


def composite(layers):
    """Straight (unquantised) foreground over the background, RGB 512x448."""
    return Image.alpha_composite(layers['background'].convert('RGBA'), layers['foreground']).convert('RGB')
