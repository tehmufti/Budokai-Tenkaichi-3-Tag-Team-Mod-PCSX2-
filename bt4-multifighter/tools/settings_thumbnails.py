"""A small picture beside each visual option of the desktop Mod settings window.

Every card shows one HUD element as the staged (unsaved) value would draw it, over a drawn in-game background
patch: the game's own HUD art, reticle, word art and lettering, decoded in memory from the player's selected disc
(the same reviewed resources settings_preview and native_hud_style use). Nothing is written to disk: no game
artwork, RAM image, screenshot or rendered card is stored; rendered cards live only in a bounded in-memory cache.
Without a readable disc every card is a clean drawn example and says so.

Cards are rendered on one background thread; Tk only receives finished pictures. Clicking a card opens it larger.
"""
from collections import OrderedDict, namedtuple
from functools import lru_cache
import math
import queue
import struct
import threading

import fonts
import localization
import settings_preview

CARD = (168, 84)          # card size in pixels at 100% scaling (2:1)
VW, VH = 672, 336         # the virtual canvas every card is drawn on (four times the card), then downsampled
LARGE = 3                 # the enlarged view: three times the card
# Interface texts (window language). The in-game captions use the game's own strings (localization.guest).
TEXTS = ('Hidden', 'Example', 'Click to enlarge', 'Click or press Esc to close.',
         'Example image: the game art comes from your selected disc.',
         'Example drawing: your game disc could not be read, so the game art is not shown.',
         'Uses your unsaved changes.', 'Battle HUD is off', 'Native style only', 'Swap mode only',
         'No control messages', 'No time limit', 'Revival is off', 'Takeover is off', 'Tag-team rush is off',
         'Beam assists are off', 'Only with one enemy left', 'On', 'Off', 'Fades after {seconds} s',
         'Grows only in 16:9 with 3-4 views')


# ---------------------------------------------------------------- colours and small helpers
def abgr(value):
    """A GS ABGR word as RGBA (GS alpha 0x80 = opaque)."""
    return (value & 255, (value >> 8) & 255, (value >> 16) & 255, min(255, ((value >> 24) & 255)*2))


def gradient(colour):
    """The kit's lettering gradient (native_hud_style._gradient): lighter top, a warm colour deepens to orange-red."""
    r, g, b = colour[:3]
    top = tuple(min(255, c + (255-c)*c//512) for c in (r, g, b))
    k = (14, 8, 6) if b < r else (11, 11, 11)
    return top, tuple(c*f//16 for c, f in zip((r, g, b), k))


@lru_cache(maxsize=16)
def _ui_font(size):
    return fonts.truetype('sans-bold', max(6, int(size)))


def _lang(language):
    return {'language': language if language in localization.LANGUAGES else 'en'}


# ---------------------------------------------------------------- the disc's art
class GameFont:
    """The game's resident Latin font ("Fnt5PS2", 2-bit glyphs), read from the disc's font package."""
    MAGIC = b'5tnF 2SP'

    def __init__(self, entry):
        import native_hud_style as kit
        if entry[:8] != self.MAGIC:
            raise ValueError('The disc has no game font here')
        desc, table = struct.unpack_from('<I', entry, 12)[0], struct.unpack_from('<I', entry, 20)[0]
        count, cw, ch = struct.unpack_from('<3I', entry, 24)
        if (cw, ch) != (20, 20) or not 0 < count < 4096 or table+6*count > len(entry) or desc+64 > len(entry):
            raise ValueError('The disc has an unrecognized game font')
        tex0 = struct.unpack_from('<Q', entry, desc+48)[0]
        width, height, tbw = 1 << ((tex0 >> 26) & 15), 1 << ((tex0 >> 30) & 15), (tex0 >> 14) & 63
        packet = struct.unpack_from('<I', entry, desc)[0]          # on disc the descriptor words are offsets
        trx = struct.unpack_from('<Q', entry, packet+48)[0]
        rw, rh = trx & 0xFFF, (trx >> 32) & 0xFFF
        if (tex0 >> 20) & 63 != 20 or rw*rh*4 != width*height//2 or packet+96+rw*rh*4 > len(entry):
            raise ValueError('The disc has an unrecognized game font texture')
        self.width, self.height = width, height
        self.indices = kit.psmt4_from_upload(entry[packet+96:packet+96+rw*rh*4], rw, rh, width, height, max(2, tbw))
        self.glyphs = {}
        for i in range(count):
            e = entry[table+6*i:table+6*i+6]
            self.glyphs[e[0] | e[1] << 8] = (e[2] | (e[3] & 3) << 8, e[4], (e[3] >> 2) & 31, e[3] >> 7)
        if sum(c in self.glyphs for c in range(0x41, 0x5B)) < 26:
            raise ValueError('The disc font has no Latin capitals')
        self.lock = threading.Lock()

    @lru_cache(maxsize=128)
    def glyph(self, code):
        """(L mask 0..255 of one 20-pixel cell, advance)."""
        from PIL import Image
        gx, gy, w, plane = self.glyphs.get(code, self.glyphs.get(ord('?')))
        data = bytearray(max(1, w)*20)
        for row in range(20):
            for col in range(w):
                x, y = gx+col, gy+row
                if 0 <= x < self.width and 0 <= y < self.height:
                    v = self.indices[y*self.width+x]
                    data[row*max(1, w)+col] = ((v >> 2) & 3 if plane else v & 3)*85
        return Image.frombytes('L', (max(1, w), 20), bytes(data)), w

    def mask(self, text):
        from PIL import Image
        with self.lock:
            cells = [self.glyph(ord(c)) for c in text]
        out = Image.new('L', (max(1, sum(w for _, w in cells)), 20))
        x = 0
        for image, w in cells:
            out.paste(image, (x, 0)); x += w
        return out


Art = namedtuple('Art', 'hud font prompt combo')


def _textures(bundle, count=None):
    from PIL import Image
    import model_assets
    n, words = struct.unpack_from('<2I', bundle)
    if count is not None and n != count:
        raise ValueError('The disc has an unrecognized texture table')
    out = {}
    for i in range(n):
        try:
            out[i] = Image.fromarray(model_assets.decode_texture(bundle, words*4+64*i).rgba, 'RGBA')
        except (ValueError, KeyError):
            pass
    return out


@lru_cache(maxsize=2)
def _disc_extras(path, size, modified):
    """The word art (combo), reticle bundle (prompt) and game font: the same common UI file the HUD art comes from,
    and the font package just before it, in the selected disc's own file numbering."""
    del size, modified
    import sys
    from model_assets import package_entry
    parent = str(settings_preview.ROOT.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    from iso_compatibility.disc import Disc
    with Disc(path) as disc:
        hud_file = 7 if disc.region == 'EU' else 6
        package = disc.read(hud_file)
        prompt, combo = _textures(package_entry(package, 2), 9), _textures(package_entry(package, 5), 8)
        try:
            font = GameFont(package_entry(disc.read(hud_file-1), 1))
        except (ValueError, struct.error, KeyError, IndexError, OSError):
            font = None
    return prompt, combo, font


def load_art():
    """The selected disc's art, or None (no disc, a damaged disc or missing image libraries never raise)."""
    try:
        hud = settings_preview.disc_art()
        if hud is None:
            return None
        path = settings_preview.selected_iso(); stamp = path.stat()
        prompt, combo, font = _disc_extras(str(path), stamp.st_size, stamp.st_mtime_ns)
        if 8 not in prompt or not {2, 5} <= set(combo):
            return None
        return Art(hud, font, prompt, combo)
    except Exception:   # a damaged or unsupported disc must never stop the settings window
        return None


# ---------------------------------------------------------------- background patches (drawn, never captured)
@lru_cache(maxsize=4)
def background(kind):
    """A drawn stand-in for the default grassland stage: sky, soft clouds and hills ('field' shows the ground)."""
    from PIL import Image, ImageDraw, ImageFilter
    import random
    rnd = random.Random(7 if kind == 'sky' else 11)
    w, h = VW, VH
    horizon = h*(1.25 if kind == 'sky' else .52)
    img = Image.new('RGBA', (w, h))
    px = ImageDraw.Draw(img)
    top, low = (34, 92, 176), (128, 186, 236)
    for y in range(h):
        t = min(1, max(0, y/max(1, horizon)))
        px.line((0, y, w, y), fill=tuple(round(a+(b-a)*t**1.4) for a, b in zip(top, low))+(255,))
    clouds = Image.new('RGBA', (w, h))
    cd = ImageDraw.Draw(clouds)
    for _ in range(9):
        cx, cy = rnd.uniform(-40, w+40), rnd.uniform(h*.05, min(horizon*.85, h*.9))
        for _ in range(5):
            rx, ry = rnd.uniform(40, 110), rnd.uniform(14, 34)
            ox, oy = rnd.uniform(-70, 70), rnd.uniform(-10, 10)
            cd.ellipse((cx+ox-rx, cy+oy-ry, cx+ox+rx, cy+oy+ry), fill=(255, 255, 255, 120))
    img.alpha_composite(clouds.filter(ImageFilter.GaussianBlur(14)))
    if kind == 'field':
        ground = Image.new('RGBA', (w, h))
        gd = ImageDraw.Draw(ground)
        far = [(x, horizon-18-22*math.sin(x/97)-12*math.sin(x/41+1)) for x in range(0, w+8, 8)]
        gd.polygon(far+[(w, h), (0, h)], fill=(88, 128, 92, 255))
        near = [(x, horizon+6-10*math.sin(x/130+2)) for x in range(0, w+8, 8)]
        gd.polygon(near+[(w, h), (0, h)], fill=(78, 140, 62, 255))
        for y in range(int(horizon), h):
            t = (y-horizon)/max(1, h-horizon)
            gd.line((0, y, w, y), fill=(round(84-34*t), round(146-52*t), round(64-22*t), 150))
        img.alpha_composite(ground.filter(ImageFilter.GaussianBlur(2)))
    shade = Image.new('RGBA', (w, h), (6, 12, 24, 64))   # a little darker so HUD art reads as in a match
    img.alpha_composite(shade)
    return img


# ---------------------------------------------------------------- drawing context
class Ctx:
    def __init__(self, art, values):
        from PIL import Image, ImageDraw
        self.art, self.values = art, values
        self.layer = Image.new('RGBA', (VW, VH))
        self.draw = ImageDraw.Draw(self.layer)
        self.game = {'language': values.get('language', 'en')}

    @property
    def native(self):
        return self.art is not None

    # -- lettering
    def caption_image(self, text, colour, cell, translated=False):
        """The kit's NTEXT look: the game font (else a drawn sans), a dark baked rim, a light-to-deep gradient of
        the caption colour and a slight italic slant; `cell` = virtual pixels per 20-pixel font cell."""
        from PIL import Image, ImageFilter
        data = text if translated else localization.guest(text, self.game).decode('ascii')
        font = self.art.font if self.art is not None else None
        if font is not None:
            mask = font.mask(data)
        else:
            face = _ui_font(15)
            box = face.getbbox(data or ' ')
            mask = Image.new('L', (max(1, box[2]+2), 20))
            from PIL import ImageDraw
            ImageDraw.Draw(mask).text((1, 18), data, font=face, fill=255, anchor='ls')
        pad = 3
        base = Image.new('L', (mask.width+2*pad, 20+2*pad)); base.paste(mask, (pad, pad))
        rim = Image.blend(base.filter(ImageFilter.MaxFilter(3)), base.filter(ImageFilter.MaxFilter(5)), .35)
        top, bottom = gradient(colour)
        fill = Image.new('RGBA', base.size)
        for y in range(base.height):
            t = min(1, max(0, (y-pad-3)/13))
            fill.paste(tuple(round(a+(b-a)*t) for a, b in zip(top, bottom))+(255,), (0, y, base.width, y+1))
        out = Image.new('RGBA', base.size, (22, 22, 26, 0))
        out.putalpha(rim)
        fill.putalpha(base)
        out.alpha_composite(fill)
        slant = 4*base.height/24
        out = out.transform((base.width+math.ceil(slant), base.height), Image.Transform.AFFINE,
                            (1, slant/base.height, -slant, 0, 1, 0), Image.Resampling.BICUBIC)
        k = cell/20
        return out.resize((max(1, round(out.width*k)), max(1, round(out.height*k))), Image.Resampling.LANCZOS)

    def caption_lines(self, lines, *, cell=66, width=620, gap=4, align='left', x=None, y=None, height=VH-56):
        """Lines [(text, colour, size factor)], wrapped at spaces when wider than `width` and shrunk until the block
        fits `height`; a centred block by default. Returns the block's bounding box."""
        for _ in range(6):
            images = self._caption_images(lines, cell, width)
            total = sum(i.height for i in images)+gap*(len(images)-1)
            if total <= height:
                break
            cell *= .86
        total = sum(i.height for i in images)+gap*(len(images)-1)
        widest = max(i.width for i in images)
        left = x if x is not None else (VW-widest)//2
        cy = y if y is not None else (VH-total)//2
        top = cy
        for image in images:
            px = left if align == 'left' else left+(widest-image.width)//2
            self.layer.alpha_composite(image, (int(px), int(cy)))
            cy += image.height+gap
        return left, top, left+widest, cy-gap

    def _caption_images(self, lines, cell, width):
        from PIL import Image
        images = []
        for text, colour, factor in lines:
            size = cell*factor
            text = localization.guest(text, self.game).decode('ascii')
            image = self.caption_image(text, colour, size, True)
            if width < image.width <= width/.9 or (image.width > width and ' ' not in text):
                image = image.resize((width, max(1, round(image.height*width/image.width))), Image.Resampling.LANCZOS)
            if image.width > width:
                words = text.split(' '); best = None
                for cut in range(1, len(words)):
                    a, b = ' '.join(words[:cut]), ' '.join(words[cut:])
                    wide = max(self.caption_image(a, colour, size, True).width,
                               self.caption_image(b, colour, size, True).width)
                    if best is None or wide < best[0]:
                        best = (wide, a, b)
                parts = [self.caption_image(best[1], colour, size, True), self.caption_image(best[2], colour, size, True)]
            else:
                parts = [image]
            for part in parts:
                if part.width > width:
                    part = part.resize((width, max(1, round(part.height*width/part.width))), Image.Resampling.LANCZOS)
                images.append(part)
        return images

    # -- the native gauge (hud atlas 8) and its fallback
    def gauge(self, box, fraction, palette, backing=True, shear=True):
        """native_hud_style's gauge: slanted dark backing, empty track (palette 0) and the fill cut at `fraction`
        in a native palette (1 green, 2 red, 3 orange, 4 yellow, 5 blue)."""
        from PIL import Image, ImageDraw
        x0, y0, x1, y1 = (round(v) for v in box)
        w, h = x1-x0, y1-y0
        slant = h//2 if shear else 0
        layer = Image.new('RGBA', (w+slant+8, h+8))
        if self.native:
            hud = self.art.hud
            def piece(index, palette, uv, size, alpha=255):
                tile = hud.texture(index, palette).crop(uv).resize(size, Image.Resampling.BICUBIC)
                if alpha < 255:
                    tile.putalpha(tile.getchannel('A').point(lambda v: v*alpha//255))
                return tile
            if backing:
                layer.alpha_composite(piece(8, 0, (64, 48, 160, 60), (w+6, h+6), 192), (1, 1))
            layer.alpha_composite(piece(8, 0, (66, 0, 156, 12), (w, h)), (4, 4))
            cut = max(0, min(1, fraction))
            if cut > 0:
                fill = hud.texture(8, palette).crop((66, 0, 66+max(1, round(90*cut)), 12))
                fill = fill.resize((max(1, round(w*cut)), h), Image.Resampling.BICUBIC)
                layer.alpha_composite(fill, (4, 4))
        else:
            d = ImageDraw.Draw(layer)
            colours = {1: (70, 220, 90), 2: (220, 40, 40), 3: (240, 140, 50), 4: (240, 230, 70), 5: (70, 140, 240)}
            if backing:
                d.rectangle((1, 1, w+6, h+6), fill=(0, 0, 0, 170))
            d.rectangle((4, 4, w+3, h+3), fill=(28, 44, 70, 255))
            cut = max(0, min(1, fraction))
            if cut > 0:
                c = colours.get(palette, (200, 200, 200))
                for y in range(h):
                    t = y/max(1, h-1)
                    shade = tuple(min(255, round(v*(1.35-.55*t))) for v in c)
                    d.line((4, 4+y, 4+round(w*cut)-1, 4+y), fill=shade+(255,))
        if slant:
            layer = layer.transform(layer.size, Image.Transform.AFFINE,
                                    (1, slant/layer.height, -slant, 0, 1, 0), Image.Resampling.BICUBIC)
        self.layer.alpha_composite(layer, (x0-4, y0-4))

    # -- textures
    def tex(self, which, index):
        return getattr(self.art, which)[index] if self.native else None

    def paste(self, image, centre):
        self.layer.alpha_composite(image, (round(centre[0]-image.width/2), round(centre[1]-image.height/2)))


# ---------------------------------------------------------------- figures (drawn in code)
def figure(size, colour=(22, 30, 46), rim=(92, 118, 160)):
    """A fighter silhouette in a guard stance (spiky hair), `size` virtual pixels tall, with a rim light."""
    from PIL import Image, ImageDraw
    s = size/100
    img = Image.new('RGBA', (round(84*s)+8, round(104*s)+8))
    def shape(d, dx, fill):
        def P(points): return [(dx+4+x*s, 4+y*s) for x, y in points]
        def limb(points, width):
            pts = P(points)
            d.line(pts, fill=fill, width=max(1, round(width*s)), joint='curve')
            for x, y in pts:
                r = width*s/2
                d.ellipse((x-r, y-r, x+r, y+r), fill=fill)
        d.polygon(P([(33, 20), (28, 6), (37, 12), (40, 0), (45, 10), (52, 2), (52, 13), (60, 9), (55, 21)]), fill=fill)
        d.ellipse(P([(34, 9), (53, 30)]), fill=fill)
        d.polygon(P([(38, 28), (49, 28), (50, 34), (37, 34)]), fill=fill)
        d.polygon(P([(26, 33), (61, 33), (56, 50), (52, 62), (35, 62), (31, 50)]), fill=fill)
        limb([(29, 36), (19, 50), (28, 42)], 8)
        limb([(58, 36), (67, 49), (60, 58)], 8)
        d.ellipse(P([(23, 36), (33, 46)]), fill=fill)
        limb([(38, 60), (29, 80), (23, 99)], 10)
        limb([(50, 60), (60, 79), (66, 99)], 10)
        d.polygon(P([(16, 96), (28, 96), (30, 102), (14, 102)]), fill=fill)
        d.polygon(P([(61, 96), (73, 96), (75, 102), (59, 102)]), fill=fill)
    d = ImageDraw.Draw(img)
    shape(d, 2, rim+(255,))
    shape(d, 0, colour+(255,))
    return img


def ground_shadow(ctx, centre, width):
    from PIL import Image, ImageDraw, ImageFilter
    shadow = Image.new('RGBA', (VW, VH))
    ImageDraw.Draw(shadow).ellipse((centre[0]-width/2, centre[1]-width/9, centre[0]+width/2, centre[1]+width/9),
                                   fill=(0, 0, 0, 90))
    ctx.layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))


def place_figure(ctx, cx, feet, size, **kw):
    f = figure(size, **kw)
    ground_shadow(ctx, (cx, feet), size*.7)
    ctx.layer.alpha_composite(f, (round(cx-f.width/2), round(feet-f.height+3)))
    return dict(head=(cx+3*size/100, feet-f.height+3+22*size/100), body=(cx, feet-f.height*.48),
                top=feet-f.height+3, height=f.height)


# ---------------------------------------------------------------- HUD panels
def native_panel(ctx, values, phase='Normal', portrait=0, mirror=False):
    """The native status panel (512 x 128) from the disc art, else a drawn one."""
    from PIL import Image, ImageDraw, ImageOps
    if ctx.native:
        panel = settings_preview.native_panel(ctx.art.hud, values, phase, portrait)
    else:
        panel = Image.new('RGBA', (512, 128))
        d = ImageDraw.Draw(panel)
        d.polygon(((20, 10), (500, 10), (470, 64), (300, 64), (280, 92), (230, 112), (20, 112)), fill=(26, 34, 48, 235),
                  outline=(150, 166, 190, 255), width=3)
        if values.get('show_hud_portraits', True):
            d.ellipse((34, 18, 126, 108), fill=(214, 168, 120, 255), outline=(30, 30, 30, 255), width=3)
        sub = Ctx(None, {})
        sub.layer = panel
        sub.gauge((150, 22, 470, 46), .64, 1, backing=False)
        if phase == 'Taking damage' and values.get('hud_damage_trail_seconds', .5) > 0:
            sub.gauge((150+round(320*.64), 22, 150+round(320*.8), 46), 1, 2, backing=False, shear=False)
        for k in range(5):
            d.polygon(((152+24*k, 82), (166+24*k, 56), (176+24*k, 56), (162+24*k, 82)),
                      fill=(110, 220, 240, 255) if k < 3 or phase in ('Sparking',) else (40, 70, 90, 255))
        if phase == 'Sparking' and values.get('show_hud_sparking_effects', True):
            for k in range(6):
                x = 170+k*48
                d.line(((x, 12), (x+10, 26), (x+2, 32), (x+16, 50)), fill=(120, 240, 255, 255), width=3)
    if mirror:
        panel = ImageOps.mirror(panel)
    return panel


def compact_panel(ctx, width, values, label='GOKU'):
    """viewport_hud's compact panel: a dark translucent box, the fighter name and HP, KI and STOCKS rows."""
    from PIL import Image
    h = round(width*.42)
    layer = Image.new('RGBA', (width, h), (4, 8, 12, 112))
    sub = Ctx(ctx.art, values)
    sub.layer = Image.new('RGBA', (width, h))
    cell = h/4.4
    name = sub.caption_image(label, (240, 240, 240), cell)
    sub.layer.alpha_composite(name, (round(width*.04), round(h*.03)))
    rows = (('HP', (144, 224, 128), 1, .72), ('KI', (255, 207, 80), 4, .55), ('STOCKS', (240, 208, 144), 5, .4))
    for k, (text, colour, palette, fill) in enumerate(rows):
        y = round(h*(.30+.23*k))
        sub.layer.alpha_composite(sub.caption_image(text, colour, cell*.8), (round(width*.04), y))
        sub.gauge((width*.36, y+cell*.22, width*.93, y+cell*.22+max(4, h*.09)), fill, palette, backing=False)
    layer.alpha_composite(sub.layer)
    return layer


def fit_into(ctx, image, box, keep=True):
    from PIL import Image
    x0, y0, x1, y1 = box
    if keep:
        k = min((x1-x0)/image.width, (y1-y0)/image.height)
        size = (max(1, round(image.width*k)), max(1, round(image.height*k)))
    else:
        size = (max(1, round(x1-x0)), max(1, round(y1-y0)))
    image = image.resize(size, Image.Resampling.LANCZOS)
    ctx.layer.alpha_composite(image, (round((x0+x1-size[0])/2), round((y0+y1-size[1])/2)))


def tight(image):
    box = image.getchannel('A').getbbox()
    return image.crop(box) if box else image


def scene_panel(phase='Normal', crop=None, portrait=0, mirror=False):
    def draw(ctx, v):
        if v.get('split_hud_style', 'native') == 'compact' and phase == 'Normal' and not mirror and crop is None:
            panel = compact_panel(ctx, 420, v)
            fit_into(ctx, panel, (60, 40, VW-60, VH-40))
            return
        panel = tight(native_panel(ctx, v, phase, portrait, mirror))
        if crop:
            panel = panel.crop(crop)
        fit_into(ctx, panel, (24, 24, VW-24, VH-24))
    return draw


def scene_lockoff(ctx, v):
    panel = tight(native_panel(ctx, v, 'Normal', 1, True))
    fit_into(ctx, panel, (24, 24, VW-24, VH-24))


def scene_filter(ctx, v):
    """The split-screen panel drawn at its small in-view size, magnified: Sharp keeps square texels, Smooth
    filtering blends them."""
    from PIL import Image
    panel = tight(native_panel(ctx, v, 'Normal'))
    small = panel.resize((panel.width*2//7, panel.height*2//7),
                         Image.Resampling.NEAREST if v.get('split_hud_filter', 'linear') == 'nearest' else Image.Resampling.BILINEAR)
    part = small.crop((0, 0, round(small.width*.42), small.height))
    k = min((VW-40)/part.width, (VH-40)/part.height)
    big = part.resize((round(part.width*k), round(part.height*k)), Image.Resampling.NEAREST)
    ctx.layer.alpha_composite(big, ((VW-big.width)//2, (VH-big.height)//2))


def _mini_screen(ctx, v, coop=False, players=2, outline=True):
    """The split views (logical 512 x 448) with their panels where settings_preview.panel_boxes puts them."""
    from PIL import Image, ImageDraw
    screen = Image.new('RGBA', (512, 448), (10, 14, 20, 255))
    boxes = settings_preview.panel_boxes(v, players, coop)
    native = v.get('split_hud_style', 'native') == 'native'
    sub = Ctx(ctx.art, v)
    field = background('field')
    d = ImageDraw.Draw(screen)
    for seat, (left, top, right, bottom) in enumerate(settings_preview.viewports(players)):
        w, h = right-left, bottom-top
        k = max(w/VW, h/VH)
        view = field.resize((max(w, round(VW*k)), max(h, round(VH*k))), Image.Resampling.LANCZOS).crop((0, 0, w, h))
        view.alpha_composite(Image.new('RGBA', view.size, (4, 8, 16, 90)))
        screen.alpha_composite(view, (left, top))
        f = figure(h*.33, colour=(30, 38, 56))
        screen.alpha_composite(f, (round((left+right)/2-f.width/2), round(bottom-f.height-h*.08)))
        for role, box in enumerate(boxes[seat]):
            if box is None:
                continue
            x, y, w, h, mirror = box
            if native:
                panel = tight(native_panel(sub, v, 'Normal', role if not coop or v.get('coop_hud_layout') == 'targets'
                                           else seat % 2, mirror))
                panel = panel.resize((max(1, round(w)), max(1, round(h))), Image.Resampling.LANCZOS)
            else:
                panel = compact_panel(sub, max(40, round(w*2)), v, 'P'+str(seat+1) if role == 0 else 'CPU')
                panel = panel.resize((max(1, round(w)), max(1, round(w*.42))), Image.Resampling.LANCZOS)
            glow = Image.new('RGBA', screen.size) if outline else None
            if glow is not None:
                ImageDraw.Draw(glow).rounded_rectangle((x-2, y-2, x+panel.width+1, y+panel.height+1), radius=3,
                                                   outline=(255, 236, 160, 150) if role == 0 else (170, 210, 255, 150),
                                                   width=2)
            if glow is not None:
                screen.alpha_composite(glow)
            screen.alpha_composite(panel, (round(x), round(y)))
    for left, top, right, bottom in settings_preview.viewports(players):
        d.rectangle((left, top, right-1, bottom-1), outline=(0, 0, 0, 255), width=2)
    return screen


def scene_layout(coop=False):
    def draw(ctx, v):
        from PIL import Image, ImageDraw
        screen = _mini_screen(ctx, v, coop)
        k = (VH-16)/screen.height
        screen = screen.resize((round(screen.width*k), VH-16), Image.Resampling.LANCZOS)
        x = (VW-screen.width)//2
        ctx.layer.alpha_composite(screen, (x, 8))
        ImageDraw.Draw(ctx.layer).rectangle((x-2, 6, x+screen.width+1, 8+screen.height+1), outline=(0, 0, 0, 220),
                                            width=3)
    return draw


def scene_scale(ctx, v):
    """The top of one quarter view (four players): the two panels at the chosen size."""
    from PIL import Image, ImageDraw
    screen = _mini_screen(ctx, v, False, 4, outline=False).crop((0, 0, 255, 76))
    k = (VW-40)/screen.width
    screen = screen.resize((VW-40, round(screen.height*k)), Image.Resampling.LANCZOS)
    y = (VH-screen.height)//2
    ctx.layer.alpha_composite(screen, (20, y))
    ImageDraw.Draw(ctx.layer).rectangle((18, y-2, 20+screen.width+1, y+screen.height+1), outline=(0, 0, 0, 220),
                                        width=3)


# ---------------------------------------------------------------- markers
def _native_arrow(ctx, angle, size, tint=None):
    """The reticle's top-left arrow (pointing down-right) turned to point at `angle` degrees (0 right, 90 down)."""
    from PIL import Image
    arrow = ctx.tex('prompt', 8).crop((0, 0, 32, 32))
    arrow = arrow.rotate(45-angle, Image.Resampling.BICUBIC, expand=True)
    arrow = tight(arrow)
    if tint:
        r, g, b, a = arrow.split()
        r, g, b = (ch.point(lambda v, k=k: min(255, v*k//128)) for ch, k in zip((r, g, b), tint))
        arrow = Image.merge('RGBA', (r, g, b, a))
    k = size/max(arrow.size)
    return arrow.resize((max(1, round(arrow.width*k)), max(1, round(arrow.height*k))), Image.Resampling.LANCZOS)


def _drawn_arrow(angle, size, colour):
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (size+8, size+8))
    c = (size+8)/2
    pts = [(size*.5, 0), (-size*.45, -size*.42), (-size*.2, 0), (-size*.45, size*.42)]
    t = math.radians(angle)
    rot = [(c+x*math.cos(t)-y*math.sin(t), c+x*math.sin(t)+y*math.cos(t)) for x, y in pts]
    d = ImageDraw.Draw(img)
    d.polygon(rot, fill=colour+(255,), outline=(20, 16, 10, 255), width=max(2, size//12))
    return img


def arrow(ctx, angle, size, tint=None, drawn=(250, 214, 40)):
    if ctx.native:
        return _native_arrow(ctx, angle, size, tint)
    colour = drawn if tint is None else (230, 40, 40)
    return _drawn_arrow(angle, size, colour)


def _classic_dart(ctx, tip, k):
    """lockon_select's classic gold dart (its 11 gouraud triangles), tip at `tip`, k virtual pixels per pixel."""
    import numpy as np
    from PIL import Image
    try:
        import lockon_select
        vertices = lockon_select.ARROW_VERTICES
    except Exception:
        vertices = (((-136, -190), 0x8096EEFF), ((0, -136), 0x8048D4FF), ((0, 0), 0x80149EF2),
                    ((0, -136), 0x801CA0E0), ((136, -190), 0x802CB0EC), ((0, 0), 0x800660AA))
    for t in range(0, len(vertices), 3):
        tri = vertices[t:t+3]
        pts = np.array([(tip[0]+x*k/16, tip[1]+y*k/16) for (x, y), _ in tri])
        cols = np.array([abgr(c) for _, c in tri], dtype=float)
        x0, y0 = np.floor(pts.min(0)).astype(int); x1, y1 = np.ceil(pts.max(0)).astype(int)
        if x1 <= x0 or y1 <= y0:
            continue
        ys, xs = np.mgrid[y0:y1, x0:x1]+.5
        (ax, ay), (bx, by), (cx, cy) = pts
        den = (by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
        if abs(den) < 1e-6:
            continue
        w0 = ((by-cy)*(xs-cx)+(cx-bx)*(ys-cy))/den
        w1 = ((cy-ay)*(xs-cx)+(ax-cx)*(ys-cy))/den
        w2 = 1-w0-w1
        inside = (w0 >= -.02) & (w1 >= -.02) & (w2 >= -.02)
        rgba = w0[..., None]*cols[0]+w1[..., None]*cols[1]+w2[..., None]*cols[2]
        rgba[..., 3] *= inside
        tile = Image.fromarray(np.clip(rgba, 0, 255).astype('uint8'), 'RGBA')
        ctx.layer.alpha_composite(tile, (int(x0), int(y0)))


def _classic_ring(ctx, centre, r):
    from PIL import Image, ImageDraw
    try:
        import lockon_select as sel
        ring_c, chev_c, dark_c = abgr(sel.RING), abgr(sel.CHEV), abgr(sel.DARK)
        chevron, inner, tip = sel.RING_CHEVRON, sel.INNER_FRAC/256, sel.TIP_FRAC/256
    except Exception:
        ring_c, chev_c, dark_c = (250, 236, 40, 255), (255, 240, 90, 224), (6, 6, 6, 160)
        chevron, inner, tip = ((0, 0), (-77, -61), (-77, 61)), .8, 1.12
    layer = Image.new('RGBA', (VW, VH))
    d = ImageDraw.Draw(layer)
    cx, cy = centre
    b = max(4, r/16*1.6)
    def ring(rr, width, colour):
        d.ellipse((cx-rr, cy-rr, cx+rr, cy+rr), outline=colour, width=max(1, round(width)))
    ring(r+b/2, b*1.5+2, dark_c)
    ring(r, b, ring_c)
    ri = r*inner
    ring(ri, max(3, b/2), ring_c)
    for side in (-1, 1):
        tri = [(cx-side*(tip*r+(x/256)*r), cy+(y/256)*r) for x, y in chevron]
        d.polygon(tri, fill=chev_c, outline=dark_c, width=3)
    ctx.layer.alpha_composite(layer)


def scene_marker(ctx, v):
    fig = place_figure(ctx, VW/2, VH-24, 196, colour=(44, 26, 52), rim=(150, 104, 170))
    style = v.get('lockon_target_style', 'arrow')
    look = v.get('lockon_target_look', 'native')
    cx, cy = fig['body']
    if style in ('ring', 'both'):
        r = fig['height']*.42
        if look == 'native' and ctx.native:
            reticle = ctx.tex('prompt', 8)
            from PIL import Image
            size = round(r*2.25)
            ctx.paste(reticle.resize((size, size), Image.Resampling.LANCZOS), (cx, cy))
        elif look == 'native':
            for angle, (dx, dy) in ((45, (-1, -1)), (135, (1, -1)), (225, (1, 1)), (315, (-1, 1))):
                ctx.paste(_drawn_arrow(angle, 46, (250, 214, 40)), (cx+dx*r*.78, cy+dy*r*.78))
        else:
            _classic_ring(ctx, (cx, cy), r*.92)
    if style in ('arrow', 'both'):
        tip_y = min(fig['top']-12, cy-fig['height']*.42*1.05-8) if style == 'both' else fig['top']-14
        if look == 'native':
            a = arrow(ctx, 90, 88)
            ctx.layer.alpha_composite(a, (round(cx-a.width/2), round(tip_y-a.height)))
        else:
            _classic_dart(ctx, (cx, tip_y), 4.6)


def scene_threat(ctx, v):
    mode = v.get('lockon_threat_marks', 'marks_and_warning')
    fig = place_figure(ctx, VW/2+40, VH-26, 176, colour=(44, 26, 52), rim=(150, 104, 170))
    cx, cy = fig['body']
    warn = mode == 'marks_and_warning'
    size = 70 if warn else 58
    red = (0x90, 0x18, 0x18)
    tint = None if warn else red
    gap = fig['height']*.34
    left = arrow(ctx, 0, size, tint); right = arrow(ctx, 180, size, tint)
    ctx.paste(left, (cx-gap-left.width/2, cy)); ctx.paste(right, (cx+gap+right.width/2, cy))
    edge = arrow(ctx, 180, 46, red)
    ctx.paste(edge, (12+edge.width/2, VH*.42))
    if warn:
        if ctx.native:
            from PIL import Image
            fist = ctx.tex('combo', 2).crop((14, 32, 52, 64))
            fist = fist.resize((round(fist.width*2.4), round(fist.height*2.4)), Image.Resampling.LANCZOS)
        else:
            from PIL import Image, ImageDraw
            fist = Image.new('RGBA', (80, 70))
            pts = [(40+36*math.cos(k*math.pi/6)*(1 if k % 2 else .55), 35+30*math.sin(k*math.pi/6)*(1 if k % 2 else .55))
                   for k in range(12)]
            ImageDraw.Draw(fist).polygon(pts, fill=(230, 60, 40, 255), outline=(40, 10, 10, 255), width=3)
        ctx.paste(fist, (cx, fig['top']-fist.height/2+6))


def scene_bar(friendly):
    def draw(ctx, v):
        if friendly:
            fig = place_figure(ctx, VW/2, VH-18, 170, colour=(24, 36, 64), rim=(96, 150, 220))
        else:
            fig = place_figure(ctx, VW/2, VH-18, 170, colour=(44, 26, 52), rim=(150, 104, 170))
        w, h = 300, 34
        y = fig['top']-h-26
        ctx.gauge((VW/2-w/2, y, VW/2+w/2, y+h), .68 if friendly else .42, 5 if friendly else 3)
    return draw


# ---------------------------------------------------------------- captions
BLUE_TEAM, RED_TEAM = abgr(0x80FFBC48)[:3], abgr(0x804878FF)[:3]
PALE = abgr(0x80A0FFFF)[:3]


def scene_text(lines_of):
    def draw(ctx, v):
        lines = lines_of(ctx, v)
        ctx.caption_lines(lines, x=None)
    return draw


def _name(ctx, en, es):
    return es if ctx.game.get('language') == 'es' else en


def lines_feed(ctx, v):
    return [(_name(ctx, 'GOKU', 'GOKU'), BLUE_TEAM, 1), ('> '+_name(ctx, 'FRIEZA', 'FREEZER'), RED_TEAM, 1)]


def lines_kills(ctx, v):
    return [(localization.tr('KILLS', ctx.game)+' 002', (238, 238, 238), 1.35)]


def lines_owner(ctx, v):
    return [('FUSED - PLAYER 1 HAS CONTROL', abgr(0x80D0FFFF)[:3], 1)]


def lines_countdown(ctx, v):
    return [('P2 TAKES CONTROL IN 3', abgr(0x8050CFFF)[:3], 1)]


def lines_fusion_controls(ctx, v):
    out = []
    if v.get('show_fusion_control_owner', True):
        out += lines_owner(ctx, v)
    if v.get('show_fusion_control_countdown', True):
        out += lines_countdown(ctx, v)
    return out or lines_owner(ctx, v)


def scene_timer(ctx, v):
    limit = max(1, int(v.get('fusion_duration_seconds', 40) or 40))
    left = max(1, round(limit*.6))
    box = ctx.caption_lines([(f'FUSION {left}S', PALE, 1.05)], y=86, x=86)
    ctx.gauge((86, box[3]+14, 86+480, box[3]+40), left/limit, 4)


def scene_tag(ctx, v):
    full = bool(v.get('tag_team_rush_training_full', False))
    colour = abgr(0x8050D8FF if full else 0x80FFC050)[:3]
    box = ctx.caption_lines([('TAG ATTACK', colour, 1.05)], x=110, y=100)
    ctx.gauge((110, box[3]+12, 110+420, box[3]+34), 1 if full else .58, 4 if full else 5)


def scene_meter(ctx, v):
    """The tag attack meter where the match draws it: under the player's own status panel (one view, the selected
    game's layout, settings_preview.tag_meter), its label in the game font and its bar in the native meter art."""
    from PIL import Image
    s = dict(v, split_hud_style='native')
    if hasattr(settings_preview, 'tag_meter'):
        m = settings_preview.tag_meter((0, 512, 0, 448), s)
    else:                                                       # an older settings_preview: placement only
        x, y, bar = settings_preview.tag_meter_placement((0, 512, 0, 448), s)
        m = dict(x=x, y=y, bar=bar, width=64, units=6, label='TAG ATTACK')
    k = 2                                                       # native_panel is drawn at twice the 256 x 64 frame
    canvas = Ctx(ctx.art, s)
    height = max(128, k*m['bar']+24)                           # BT4's meter sits below the 64-row frame
    canvas.layer = Image.new('RGBA', (512, height))
    if v.get('show_native_hud', True):
        canvas.layer.alpha_composite(native_panel(ctx, s))
    colour = abgr(0x80FFC050)[:3]                               # charging (tag_rush_hud.BLUE)
    # In a match the caption is about 6 frame pixels tall at 75% and never wider than its meter (tag_rush_hud).
    label = tight(canvas.caption_image(m['label'], colour, 9.5*k*m['units']/6))
    if label.width > k*m['width']:
        label = label.resize((k*m['width'], max(1, round(label.height*k*m['width']/label.width))), Image.Resampling.LANCZOS)
    canvas.layer.alpha_composite(label, (round(k*m['x']), round(k*m['bar'])-label.height-3))
    canvas.gauge((k*m['x'], k*m['bar'], k*(m['x']+m['width']), k*(m['bar']+3)), .62, 5)
    x0 = max(0, k*m['x']-110)
    fit_into(ctx, canvas.layer.crop((x0, 0, min(512, x0+340), height)), (24, 24, VW-24, VH-24))


def lines_beam(ctx, v):
    step = int(v.get('beam_assist_multiplier_percent', 150))-100
    try:
        import beam_struggle
        mult = beam_struggle.multiplier_text(step, 1)
    except Exception:
        mult = f'{(100+step)/100:.2f}'.rstrip('0').rstrip('.')
    return [(f'BEAM ASSIST X{mult}', PALE, 1.3)]


def lines_beam_hint(ctx, v):
    return [('R3 - BEAM ASSIST', PALE, 1)]+lines_beam(ctx, v)


def lines_takeover_hint(ctx, v):
    return [('PRESS L2 AND SQUARE TO TAKE OVER', abgr(0x80E0F0FF)[:3], 1)]


def lines_takeover_confirm(ctx, v):
    return [(localization.tr('CONTROLLING ', ctx.game)+'GOKU', abgr(0x80E0F0FF)[:3], 1.15)]


def lines_takeover(ctx, v):
    out = []
    if v.get('show_takeover_hints', True):
        out += lines_takeover_hint(ctx, v)
    if v.get('show_takeover_confirmation', True):
        out += lines_takeover_confirm(ctx, v)
    return out or lines_takeover_hint(ctx, v)


def lines_revive_cost(ctx, v):
    cost = int(v.get('revive_stock_cost', 4))
    return [(f'NEED {cost} BLAST STOCKS', PALE, 1.1)]


# ---------------------------------------------------------------- revival ring and camera
def _ring(ctx, v, centre):
    from PIL import Image, ImageDraw, ImageFilter
    radius = float(v.get('revive_radius', 40))
    rx = min(318, 40+radius*3.2); ry = rx*.27
    opacity = max(0, min(1, float(v.get('revive_ring_opacity', .45))))
    wave = max(0, min(80, float(v.get('revive_ring_wave_height', 8))))
    colour = (112, 255, 160)
    cx, cy = centre
    layer = Image.new('RGBA', (VW, VH))
    d = ImageDraw.Draw(layer)
    pts = [(cx+rx*math.cos(t*math.pi/64), cy+ry*math.sin(t*math.pi/64)) for t in range(129)]
    if wave > 0:
        crest = Image.new('RGBA', (VW, VH))
        cd = ImageDraw.Draw(crest)
        for t in range(128):
            a0, a1 = t*math.pi/64, (t+1)*math.pi/64
            h0 = wave*2.6*(.35+.65*(.5+.5*math.sin(3*a0+.6))); h1 = wave*2.6*(.35+.65*(.5+.5*math.sin(3*a1+.6)))
            p0, p1 = pts[t], pts[t+1]
            cd.polygon((p0, p1, (p1[0], p1[1]-h1), (p0[0], p0[1]-h0)), fill=colour+(round(110*opacity),))
            cd.line(((p0[0], p0[1]-h0), (p1[0], p1[1]-h1)), fill=colour+(round(255*opacity),), width=3)
        layer.alpha_composite(crest.filter(ImageFilter.GaussianBlur(1.2)))
    for width, alpha in ((22, .25), (12, .5), (5, 1)):
        d.line(pts, fill=colour+(round(255*opacity*alpha),), width=width, joint='curve')
    ctx.layer.alpha_composite(layer)


def _fallen(ctx, cx, cy, size=210):
    from PIL import Image
    f = figure(size, colour=(24, 36, 64), rim=(96, 150, 220)).rotate(90, expand=True)
    f = f.resize((f.width, round(f.height*.42)), Image.Resampling.LANCZOS)
    ground_shadow(ctx, (cx, cy+6), f.width*1.0)
    ctx.layer.alpha_composite(f, (round(cx-f.width/2), round(cy-f.height/2)))


def scene_ring(ctx, v):
    centre = (VW/2, VH*.72)
    _fallen(ctx, *centre)
    if v.get('show_revive_ring', True):
        _ring(ctx, v, centre)


def scene_revive(ctx, v):
    centre = (VW/2, VH*.78)
    _fallen(ctx, centre[0], centre[1], 170)
    if v.get('show_revive_ring', True):
        _ring(ctx, dict(v, revive_radius=min(60, float(v.get('revive_radius', 40)))), centre)
    box = ctx.caption_lines([('REVIVING TEAMMATE', PALE, .95)], y=28)
    ctx.gauge((VW/2-200, box[3]+10, VW/2+200, box[3]+32), .55, 1)


def scene_camera(ctx, v):
    from PIL import ImageDraw
    k = 100/max(100, int(v.get('battle_camera_distance_percent', 100)))
    hx, hy = VW/2, VH*.52
    def at(x, y):
        return hx+(x-hx)*k, hy+(y-hy)*k
    ex, ey = at(VW*.62, VH*.66)
    place_figure(ctx, ex, ey, 150*k, colour=(44, 26, 52), rim=(150, 104, 170))
    px, py = at(VW*.34, VH*1.32)
    place_figure(ctx, px, py, 380*k, colour=(24, 36, 64), rim=(96, 150, 220))
    if k < .999:
        d = ImageDraw.Draw(ctx.layer)
        x0, y0 = at(0, 0); x1, y1 = at(VW, VH)
        for t in range(0, 100, 4):
            for (a, b), (c, e) in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
                s0, s1 = t/100, min(1, (t+2)/100)
                d.line(((a+(c-a)*s0, b+(e-b)*s0), (a+(c-a)*s1, b+(e-b)*s1)), fill=(255, 255, 255, 200), width=3)


def scene_widescreen(ctx, v):
    from PIL import Image, ImageDraw
    wide = bool(v.get('widescreen_patch', False))
    frame = (40, 14, VW-40, VH-14)
    d = ImageDraw.Draw(ctx.layer)
    d.rectangle(frame, fill=(0, 0, 0, 255))
    fw, fh = frame[2]-frame[0], frame[3]-frame[1]
    gw = fw if wide else round(fh*4/3)
    gx = frame[0]+(fw-gw)//2
    game = background('field').resize((gw, fh), Image.Resampling.LANCZOS)
    sub = Ctx(ctx.art, v); sub.layer = Image.new('RGBA', (gw, fh))
    f = figure(fh*.55, colour=(24, 36, 64), rim=(96, 150, 220))
    sub.layer.alpha_composite(f, (round(gw*.5-f.width/2), round(fh*.92-f.height)))
    panel = tight(native_panel(sub, v))
    pw = round(gw*(.36 if wide else .46))
    panel = panel.resize((pw, max(1, round(panel.height*pw/panel.width))), Image.Resampling.LANCZOS)
    sub.layer.alpha_composite(panel, (round(gw*.02), round(fh*.03)))
    from PIL import ImageOps
    sub.layer.alpha_composite(ImageOps.mirror(panel), (gw-pw-round(gw*.02), round(fh*.03)))
    game.alpha_composite(sub.layer)
    ctx.layer.alpha_composite(game, (gx, frame[1]))
    d.rectangle(frame, outline=(70, 76, 90, 255), width=4)


# ---------------------------------------------------------------- which option draws what
Spec = namedtuple('Spec', 'deps scene bg hidden ghost chip', defaults=(None,))


def _off(key, reason='Hidden'):
    return lambda v: reason if not v.get(key, True) else None


def _all(*checks):
    def hidden(v):
        for check in checks:
            reason = check(v)
            if reason:
                return reason
        return None
    return hidden


def _hud_on(v):
    return 'Battle HUD is off' if not v.get('show_native_hud', True) else None


def _native_style(v):
    return 'Native style only' if v.get('split_hud_style', 'native') != 'native' else None


def _swap(v):
    if not v.get('fusion_enabled', True):
        return 'Off'
    return 'Swap mode only' if v.get('coop_fusion_controls', 'swap_20s') != 'swap_20s' else None


def _timed(v):
    if not v.get('fusion_enabled', True):
        return 'Off'
    return 'No time limit' if not v.get('fusion_duration_enabled', False) else None


def _revive(v):
    return 'Revival is off' if not v.get('revive_enabled', False) else None


def _takeover(v):
    return 'Takeover is off' if not v.get('spectator_takeover_enabled', True) else None


def _beam(v):
    return 'Beam assists are off' if not v.get('beam_assist_enabled', False) else None


def _tag(v):
    return 'Tag-team rush is off' if not v.get('tag_team_rush_enabled', True) else None


def _lockoff(v):
    return 'Hidden' if v.get('lockoff_target_hud') == 'hide' else None


def _lockoff_chip(v):
    return 'Only with one enemy left' if v.get('lockoff_target_hud', 'single_enemy') == 'single_enemy' else None


def _marker(v):
    return 'Hidden' if not v.get('lockon_target_marker', True) else None


def _threat(v):
    return 'Hidden' if v.get('lockon_threat_marks', 'marks_and_warning') == 'hide' else None


def _trail_chip(v):
    seconds = float(v.get('hud_damage_trail_seconds', .5) or 0)
    return ('Fades after {seconds} s', dict(seconds=f'{seconds:g}')) if seconds > 0 else None


def _scale_chip(v):
    if int(v.get('split_hud_scale_percent', 100)) > 100 and not settings_preview.aspect_wide(v):
        return 'Grows only in 16:9 with 3-4 views'
    return None


def _feed(v):
    return _off('show_kill_feed')(v)


PANEL = ('show_native_hud', 'split_hud_style')
SPECS = {
    # HUD
    'show_friendly_healthbars': Spec(('show_friendly_healthbars',), scene_bar(True), 'field',
                                     _off('show_friendly_healthbars'), {'show_friendly_healthbars': True}),
    'show_enemy_healthbars': Spec(('show_enemy_healthbars',), scene_bar(False), 'field',
                                  _off('show_enemy_healthbars'), {'show_enemy_healthbars': True}),
    'show_native_hud': Spec(('show_native_hud', 'split_hud_style', 'show_hud_portraits'), scene_panel(), 'sky',
                            _off('show_native_hud'), {'show_native_hud': True}),
    'show_kill_feed': Spec(('show_kill_feed', 'language'), scene_text(lines_feed), 'sky', _feed,
                           {'show_kill_feed': True}),
    'show_kill_score': Spec(('show_kill_score', 'language'), scene_text(lines_kills), 'sky',
                            _off('show_kill_score'), {'show_kill_score': True}),
    'lockoff_target_hud': Spec(('lockoff_target_hud', 'show_native_hud', 'show_hud_portraits'), scene_lockoff, 'sky',
                               _all(_hud_on, _lockoff), {'show_native_hud': True}, _lockoff_chip),
    'lockon_target_marker': Spec(('lockon_target_marker', 'lockon_target_style', 'lockon_target_look'), scene_marker,
                                 'field', _marker, {'lockon_target_marker': True}),
    'lockon_target_style': Spec(('lockon_target_marker', 'lockon_target_style', 'lockon_target_look'), scene_marker,
                                'field', _marker, {'lockon_target_marker': True}),
    'lockon_target_look': Spec(('lockon_target_marker', 'lockon_target_style', 'lockon_target_look'), scene_marker,
                               'field', _marker, {'lockon_target_marker': True}),
    'lockon_threat_marks': Spec(('lockon_threat_marks',), scene_threat, 'field', _threat,
                                {'lockon_threat_marks': 'marks'}),
    'tag_team_rush_show_meter': Spec(('tag_team_rush_show_meter', 'tag_team_rush_enabled', 'show_native_hud',
                                      'show_hud_portraits', 'language'), scene_meter, 'sky',
                                     _all(_tag, _off('tag_team_rush_show_meter')),
                                     {'tag_team_rush_enabled': True, 'tag_team_rush_show_meter': True}),
    # Split-screen HUD
    'split_hud_style': Spec(('split_hud_style', 'show_native_hud', 'show_hud_portraits'), scene_panel(), 'sky',
                            _hud_on, {'show_native_hud': True}),
    'split_hud_scale_percent': Spec(('split_hud_scale_percent', 'split_hud_layout', 'split_hud_style', 'show_native_hud',
                                     'widescreen_patch'), scene_scale, 'sky', _hud_on,
                                    {'show_native_hud': True}, _scale_chip),
    'split_hud_layout': Spec(('split_hud_layout', 'split_hud_scale_percent', 'split_hud_style', 'show_native_hud',
                              'widescreen_patch'), scene_layout(), 'sky', _hud_on, {'show_native_hud': True}),
    'split_hud_filter': Spec(('split_hud_filter', 'show_native_hud', 'split_hud_style', 'show_hud_portraits'),
                             scene_filter, 'sky', _all(_hud_on, _native_style), {'show_native_hud': True,
                                                                                 'split_hud_style': 'native'}),
    'coop_hud_layout': Spec(('coop_hud_layout', 'split_hud_layout', 'split_hud_scale_percent', 'split_hud_style',
                             'show_native_hud', 'widescreen_patch'), scene_layout(coop=True), 'sky', _hud_on,
                            {'show_native_hud': True}),
    'show_hud_portraits': Spec(('show_hud_portraits', 'show_native_hud', 'split_hud_style'),
                               scene_panel(crop=(0, 0, 300, 128)), 'sky', _all(_hud_on, _native_style),
                               {'show_native_hud': True, 'split_hud_style': 'native'}),
    'show_hud_sparking_effects': Spec(('show_hud_sparking_effects', 'show_native_hud', 'split_hud_style',
                                       'show_hud_portraits'), scene_panel('Sparking'), 'sky',
                                      _all(_hud_on, _native_style), {'show_native_hud': True, 'split_hud_style': 'native'}),
    'hud_damage_trail_seconds': Spec(('hud_damage_trail_seconds', 'show_native_hud', 'split_hud_style'),
                                     scene_panel('Taking damage', crop=(120, 0, 512, 70)), 'sky',
                                     _all(_hud_on, _native_style), {'show_native_hud': True, 'split_hud_style': 'native'},
                                     _trail_chip),
    # Tag-team rush and Training
    'tag_team_rush_enabled': Spec(('tag_team_rush_enabled', 'language'), scene_tag, 'sky', _tag,
                                  {'tag_team_rush_enabled': True, 'tag_team_rush_training_full': False}),
    'tag_team_rush_training_full': Spec(('tag_team_rush_training_full', 'tag_team_rush_enabled', 'language'),
                                        scene_tag, 'sky', _tag, {'tag_team_rush_enabled': True}),
    # Fusion
    'coop_fusion_controls': Spec(('coop_fusion_controls', 'fusion_enabled', 'show_fusion_control_owner',
                                  'show_fusion_control_countdown', 'language'), scene_text(lines_fusion_controls), 'sky',
                                 lambda v: 'No control messages' if _swap(v) else None,
                                 {'coop_fusion_controls': 'swap_20s', 'fusion_enabled': True}),
    'show_fusion_control_owner': Spec(('show_fusion_control_owner', 'coop_fusion_controls', 'fusion_enabled', 'language'),
                                      scene_text(lines_owner), 'sky', _all(_swap, _off('show_fusion_control_owner')),
                                      {'show_fusion_control_owner': True}),
    'show_fusion_control_countdown': Spec(('show_fusion_control_countdown', 'coop_fusion_controls', 'fusion_enabled',
                                           'language'), scene_text(lines_countdown), 'sky',
                                          _all(_swap, _off('show_fusion_control_countdown')),
                                          {'show_fusion_control_countdown': True}),
    'fusion_duration_enabled': Spec(('fusion_duration_enabled', 'fusion_enabled', 'fusion_duration_seconds',
                                     'show_fusion_timer'), scene_timer, 'sky',
                                    _all(_timed, _off('show_fusion_timer')), {'fusion_duration_enabled': True}),
    'fusion_duration_seconds': Spec(('fusion_duration_seconds', 'fusion_duration_enabled', 'fusion_enabled',
                                     'show_fusion_timer'), scene_timer, 'sky', _all(_timed, _off('show_fusion_timer')),
                                    {'fusion_duration_enabled': True}),
    'show_fusion_timer': Spec(('show_fusion_timer', 'fusion_duration_enabled', 'fusion_enabled',
                               'fusion_duration_seconds'), scene_timer, 'sky', _all(_timed, _off('show_fusion_timer')),
                              {'show_fusion_timer': True}),
    # Spectating
    'spectator_takeover_enabled': Spec(('spectator_takeover_enabled', 'show_takeover_hints',
                                        'show_takeover_confirmation', 'language'), scene_text(lines_takeover), 'sky',
                                       _takeover, {'spectator_takeover_enabled': True}),
    'show_takeover_hints': Spec(('show_takeover_hints', 'spectator_takeover_enabled', 'language'),
                                scene_text(lines_takeover_hint), 'sky', _all(_takeover, _off('show_takeover_hints')),
                                {'show_takeover_hints': True}),
    'show_takeover_confirmation': Spec(('show_takeover_confirmation', 'spectator_takeover_enabled', 'language'),
                                       scene_text(lines_takeover_confirm), 'sky',
                                       _all(_takeover, _off('show_takeover_confirmation')),
                                       {'show_takeover_confirmation': True}),
    # Revival
    'revive_enabled': Spec(('revive_enabled', 'show_revive_ring', 'revive_ring_opacity', 'revive_ring_wave_height',
                            'language'), scene_revive, 'field', _revive, {'revive_enabled': True}),
    'revive_stock_cost': Spec(('revive_stock_cost', 'revive_enabled', 'language'), scene_text(lines_revive_cost), 'sky',
                              _revive, {'revive_enabled': True}),
    'revive_radius': Spec(('revive_radius', 'revive_enabled', 'show_revive_ring', 'revive_ring_opacity',
                           'revive_ring_wave_height'), scene_ring, 'field', _revive, {'revive_enabled': True}),
    'show_revive_ring': Spec(('show_revive_ring', 'revive_enabled', 'revive_radius', 'revive_ring_opacity',
                              'revive_ring_wave_height'), scene_ring, 'field', _all(_revive, _off('show_revive_ring')),
                             {'revive_enabled': True, 'show_revive_ring': True}),
    'revive_ring_opacity': Spec(('revive_ring_opacity', 'revive_enabled', 'show_revive_ring', 'revive_radius',
                                 'revive_ring_wave_height'), scene_ring, 'field', _all(_revive, _off('show_revive_ring')),
                                {'revive_enabled': True, 'show_revive_ring': True}),
    'revive_ring_wave_height': Spec(('revive_ring_wave_height', 'revive_enabled', 'show_revive_ring', 'revive_radius',
                                     'revive_ring_opacity'), scene_ring, 'field',
                                    _all(_revive, _off('show_revive_ring')),
                                    {'revive_enabled': True, 'show_revive_ring': True}),
    # Beam struggles
    'beam_assist_enabled': Spec(('beam_assist_enabled', 'beam_assist_multiplier_percent', 'language'),
                                scene_text(lines_beam_hint), 'sky', _beam, {'beam_assist_enabled': True}),
    'beam_assist_multiplier_percent': Spec(('beam_assist_multiplier_percent', 'beam_assist_enabled', 'language'),
                                           scene_text(lines_beam), 'sky', _beam, {'beam_assist_enabled': True}),
    # Cinematics and launch options
    'battle_camera_distance_percent': Spec(('battle_camera_distance_percent',), scene_camera, 'field',
                                           lambda v: None, {}),
    'widescreen_patch': Spec(('widescreen_patch', 'show_hud_portraits'), scene_widescreen, 'sky', lambda v: None, {}),
}
# Adjacent options whose pictures would be identical share one picture, spanned over their rows: it shows all of
# their values at once (and the hidden state when the switch among them is off).
SHARED = (('lockon_target_marker', 'lockon_target_style', 'lockon_target_look'),
          ('fusion_duration_enabled', 'fusion_duration_seconds', 'show_fusion_timer'),
          ('show_revive_ring', 'revive_ring_opacity', 'revive_ring_wave_height'))
for _members in SHARED:
    _first = SPECS[_members[0]]
    assert all(SPECS[k].scene is _first.scene and SPECS[k].bg == _first.bg for k in _members), _members
    _shared = _first._replace(deps=tuple(dict.fromkeys(d for k in _members for d in SPECS[k].deps)),
                              ghost={k: v for m in _members for k, v in SPECS[m].ghost.items()})
    for _key in _members:
        SPECS[_key] = _shared
del _members, _first, _shared, _key
KEYS = tuple(SPECS)


def available(key):
    return key in SPECS


def shared(key):
    """The options that share `key`'s picture (in page order), or just (key,)."""
    return next((members for members in SHARED if key in members), (key,))


def decimal(text, ui):
    """A number as the language writes it (0,5 in Spanish)."""
    return str(text).replace('.', ',') if localization.language(ui) == 'es' else str(text)


def value_text(value, ui):
    """A staged value as the window shows it (On/Off, a choice's label, a number)."""
    if isinstance(value, bool):
        return localization.tr('On' if value else 'Off', ui)
    if isinstance(value, str):
        return localization.value_label(value, ui)
    if isinstance(value, float):
        return decimal(f'{value:g}', ui)
    return str(value)


# ---------------------------------------------------------------- the card
def _rounded(image, radius):
    from PIL import Image, ImageDraw
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width-1, image.height-1), radius=radius, fill=255)
    out = Image.new('RGBA', image.size)
    out.paste(image, (0, 0), mask)
    return out


def _badge(card, text, scale, centre=True, colour=(14, 20, 30, 210), bottom=False, corner=False):
    """A rounded pill with an eye-slash glyph (hidden) or a small corner tag."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(card)
    size = max(8, round(11*scale))
    face = _ui_font(size)
    tw = d.textlength(text, font=face)
    room = card.width-round(14*scale)-(round(size*1.3) if centre and not bottom else 0)
    while tw > room and size > 7:
        size -= 1; face = _ui_font(size); tw = d.textlength(text, font=face)
    icon = round(size*1.3) if centre and not bottom else 0
    pad = round(7*scale)
    w, h = round(tw+icon+2*pad), round(size*1.9)
    if corner:
        x0, y0 = card.width-w-round(4*scale), card.height-h-round(4*scale)
    elif bottom:
        x0, y0 = (card.width-w)//2, card.height-h-round(5*scale)
    elif centre:
        x0, y0 = (card.width-w)//2, (card.height-h)//2
    else:
        x0, y0 = round(5*scale), round(5*scale)
    d.rounded_rectangle((x0, y0, x0+w, y0+h), radius=h//2, fill=colour, outline=(255, 255, 255, 60))
    if centre and not bottom:
        ex, ey, er = x0+pad+icon/2-1, y0+h/2, size*.5
        d.ellipse((ex-er, ey-er*.62, ex+er, ey+er*.62), outline=(230, 236, 245, 255), width=max(1, round(scale*1.3)))
        d.ellipse((ex-er*.3, ey-er*.3, ex+er*.3, ey+er*.3), fill=(230, 236, 245, 255))
        d.line((ex-er, ey+er*.85, ex+er, ey-er*.85), fill=(230, 236, 245, 255), width=max(1, round(scale*1.6)))
    d.text((x0+pad+icon, y0+h/2), text, font=face, fill=(240, 244, 250, 255), anchor='lm')


def render_card(key, values, art, size=CARD, ui_language='en'):
    """The card for `key` with these (staged) values: an RGBA image of `size` pixels. Pure: reads nothing but
    the given art and values, writes nothing."""
    from PIL import Image, ImageEnhance
    spec = SPECS[key]
    v = dict(values)
    ui = _lang(ui_language)
    reason = spec.hidden(v)
    drawn = dict(v, **spec.ghost) if reason else v
    ctx = Ctx(art, drawn)
    spec.scene(ctx, drawn)
    layer = ctx.layer
    if reason:
        alpha = layer.getchannel('A').point(lambda a: a*30//100)
        layer = ImageEnhance.Color(layer).enhance(.15)
        layer.putalpha(alpha)
    canvas = background(spec.bg).copy()
    canvas.alpha_composite(layer)
    card = canvas.resize(size, Image.Resampling.LANCZOS)
    scale = size[1]/CARD[1]
    if reason:
        dim = Image.new('RGBA', size, (8, 12, 20, 70))
        card.alpha_composite(dim)
        _badge(card, localization.tr(reason, ui), scale)
    chip = spec.chip(v) if spec.chip and not reason else None
    if chip:
        text, values = chip if isinstance(chip, tuple) else (chip, {})
        values = {k: decimal(v, ui) for k, v in values.items()}
        _badge(card, localization.tr(text, ui, **values), scale*.85, bottom=True)
    if art is None:
        _badge(card, localization.tr('Example', ui).upper(), scale*.72, centre=False, colour=(160, 72, 24, 215),
               corner=True)
    card = _rounded(card, max(3, round(6*scale)))
    from PIL import ImageDraw
    ImageDraw.Draw(card).rounded_rectangle((0, 0, size[0]-1, size[1]-1), radius=max(3, round(6*scale)),
                                           outline=(40, 52, 70, 255), width=1)
    card.info['hidden'] = reason
    card.info['example'] = art is None
    return card


def placeholder(size=CARD):
    """The card shown until the first picture is ready: the background patch, softly dimmed."""
    from PIL import Image, ImageDraw
    card = background('sky').resize(size, Image.Resampling.LANCZOS)
    card.alpha_composite(Image.new('RGBA', size, (8, 12, 20, 120)))
    d = ImageDraw.Draw(card)
    r = max(2, size[1]//28)
    for k in range(3):
        x = size[0]/2+(k-1)*r*4
        d.ellipse((x-r, size[1]/2-r, x+r, size[1]/2+r), fill=(230, 236, 245, 110+50*k))
    card = _rounded(card, max(3, round(6*size[1]/CARD[1])))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, size[0]-1, size[1]-1), radius=max(3, round(6*size[1]/CARD[1])),
                                           outline=(40, 52, 70, 255), width=1)
    return card


def cache_key(key, values, size, ui_language, art):
    return (key, size, ui_language, id(art) if art is not None else None,
            tuple(repr(values.get(d)) for d in SPECS[key].deps))


# ---------------------------------------------------------------- Tk: the thumbnail column and enlarged view
class Thumbnails:
    """Thumbnails beside settings rows. values() returns the staged values; every picture is rendered on one
    background thread and cached in memory (never on disk)."""
    LIMIT = 256

    def __init__(self, window, values, ui_language='en', load=load_art):
        import tkinter as tk
        self.tk = tk
        self.window, self.values, self.ui_language = window, values, ui_language
        try:
            self.scale = max(1., float(window.tk.call('tk', 'scaling'))/(96/72))
        except (tk.TclError, ValueError):
            self.scale = 1.
        self.size = (round(CARD[0]*self.scale), round(CARD[1]*self.scale))
        self.labels, self.photos, self.wanted, self.headings = {}, {}, {}, {}
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.jobs, self.results = queue.Queue(), queue.Queue()
        self.art, self.art_ready = None, False
        self.closed = False
        self.popup = None
        self.polling = False
        self.after_id = None
        self.blank = None
        self.worker = threading.Thread(target=self._work, args=(load,), daemon=True, name='settings-thumbnails')
        self.worker.start()
        window.bind('<Destroy>', self._destroyed, add='+')
        self._poll()

    # -- rows
    def attach(self, parent, row, key, column=2, heading='', rowspan=1):
        """The picture of `key` at `row`; `heading`: its option label, or {member: label} for a shared picture
        spanning `rowspan` rows."""
        from PIL import ImageTk
        if self.blank is None:
            self.blank = ImageTk.PhotoImage(placeholder(self.size), master=self.window)
        from tkinter import ttk
        background = ttk.Style(parent).lookup('TFrame', 'background') or None
        label = self.tk.Label(parent, image=self.blank, borderwidth=0, highlightthickness=0, cursor='hand2',
                              width=self.size[0], height=self.size[1])
        if background:
            label.configure(background=background)
        label.grid(row=row, column=column, rowspan=rowspan, sticky='e', padx=(14, 2), pady=4)
        label.bind('<Button-1>', lambda _event, k=key: self.enlarge(k))
        self.labels[key] = label
        self.headings[key] = heading
        self.request(key)
        return label

    def changed(self, *keys):
        """A staged value changed: re-render every card that depends on it (the enlarged one too)."""
        for key, label in self.labels.items():
            if not keys or any(k in SPECS[key].deps for k in keys):
                self.request(key)
        if self.popup is not None and (not keys or any(k in SPECS[self.popup['key']].deps for k in keys)):
            self.request(self.popup['key'], large=True)

    def _snapshot(self):
        try:
            return dict(self.values())
        except Exception:
            return None

    def request(self, key, large=False):
        if self.closed:
            return
        values = self._snapshot()
        if values is None:
            return
        size = self.large_size() if large else self.size
        tag = (key, large)
        if not self.art_ready:
            self.wanted[tag] = None   # rendered once the disc art is read
            return
        ck = cache_key(key, values, size, self.ui_language, self.art)
        self.wanted[tag] = ck
        with self.lock:
            image = self.cache.get(ck)
            if image is not None:
                self.cache.move_to_end(ck)
        if image is not None:
            self._show(tag, image)
            return
        self.jobs.put((tag, ck, key, values, size))
        self._poll()

    def large_size(self):
        return (self.size[0]*LARGE, self.size[1]*LARGE)

    # -- the worker
    def _work(self, load):
        art = load()
        self.results.put(('art', art))
        while True:
            job = self.jobs.get()
            if job is None:
                return
            tag, ck, key, values, size = job
            if self.wanted.get(tag) != ck:
                continue                       # superseded before it started
            with self.lock:
                cached = self.cache.get(ck)
            if cached is None:
                try:
                    cached = render_card(key, values, self.art, size, self.ui_language)
                except Exception:              # a picture must never break the settings window
                    try:
                        cached = render_card(key, values, None, size, self.ui_language)
                    except Exception:
                        continue
                with self.lock:
                    self.cache[ck] = cached
                    while len(self.cache) > self.LIMIT:
                        self.cache.popitem(last=False)
            self.results.put((tag, ck, cached))

    def _poll(self):
        if self.polling or self.closed:
            return
        self.polling = True
        self.after_id = self.window.after(30, self._drain)

    def _drain(self):
        self.polling = False
        if self.closed:
            return
        try:
            while True:
                item = self.results.get_nowait()
                if item[0] == 'art':
                    self.art, self.art_ready = item[1], True
                    for tag in list(self.wanted):
                        self.request(*tag)
                    continue
                tag, ck, image = item
                if self.wanted.get(tag) == ck:
                    self._show(tag, image)
        except queue.Empty:
            pass
        if not self.art_ready or not self.jobs.empty() or any(v is not None for v in self.wanted.values()):
            self._poll()

    def _show(self, tag, image):
        from PIL import ImageTk
        key, large = tag
        self.wanted[tag] = None
        try:
            if large:
                if self.popup is None or self.popup['key'] != key:
                    return
                photo = ImageTk.PhotoImage(image, master=self.popup['window'])
                self.popup['label'].configure(image=photo)
                self.popup['photo'] = photo
                self.popup['note'].configure(text=self.note())
                self.popup['heading'].configure(text=self.heading(key))
                return
            label = self.labels.get(key)
            if label is None or not label.winfo_exists():
                return
            photo = ImageTk.PhotoImage(image, master=label)
            label.configure(image=photo)
            self.photos[key] = photo
            label.hidden = image.info.get('hidden')
        except self.tk.TclError:
            pass

    def heading(self, key):
        values = self._snapshot() or {}
        heading = self.headings.get(key, '')
        labels = heading if isinstance(heading, dict) else {key: heading}
        lines = []
        for member, text in labels.items():
            if member in values:
                text += ': '+value_text(values[member], _lang(self.ui_language))
            lines.append(text)
        return '\n'.join(lines)

    def title(self, key):
        heading = self.headings.get(key, '')
        return next(iter(heading.values()), '') if isinstance(heading, dict) else heading

    def note(self):
        ui = _lang(self.ui_language)
        if not self.art_ready:
            return ''
        text = ('Example image: the game art comes from your selected disc.' if self.art is not None else
                'Example drawing: your game disc could not be read, so the game art is not shown.')
        return localization.tr(text, ui)+' '+localization.tr('Uses your unsaved changes.', ui)

    # -- the enlarged view
    def enlarge(self, key):
        key = next((k for k in shared(key) if k in self.labels), key)   # a shared picture opens once, for all
        tk = self.tk
        from tkinter import ttk
        from PIL import ImageTk
        ui = _lang(self.ui_language)
        if self.popup is not None:
            try:
                self.popup['window'].destroy()
            except tk.TclError:
                pass
        top = tk.Toplevel(self.window)
        top.title(self.title(key) or localization.tr('Click to enlarge', ui))
        top.transient(self.window)
        top.resizable(False, False)
        frame = ttk.Frame(top, padding=12); frame.pack(fill='both', expand=True)
        heading = ttk.Label(frame, text=self.heading(key), font=('Segoe UI', 11, 'bold'))
        heading.pack(anchor='w', pady=(0, 8))
        start = placeholder(self.large_size())
        photo = ImageTk.PhotoImage(start, master=top)
        label = tk.Label(frame, image=photo, borderwidth=0, highlightthickness=0, cursor='hand2')
        label.pack()
        note = ttk.Label(frame, text=self.note(), foreground='#555555', wraplength=self.large_size()[0])
        note.pack(anchor='w', pady=(8, 0))
        hint = ttk.Label(frame, text=localization.tr('Click or press Esc to close.', ui), foreground='#777777')
        hint.pack(anchor='w')
        self.popup = dict(window=top, key=key, label=label, photo=photo, note=note, heading=heading)
        def close(_=None):
            if self.popup is not None and self.popup['window'] is top:
                self.popup = None
            try:
                top.destroy()
            except tk.TclError:
                pass
        label.bind('<Button-1>', close); top.bind('<Escape>', close); top.protocol('WM_DELETE_WINDOW', close)
        top.bind('<Destroy>', lambda e: close() if e.widget is top and self.popup and self.popup['window'] is top else None)
        self.request(key, large=True)
        try:
            top.update_idletasks()
            x = self.window.winfo_rootx()+max(0, (self.window.winfo_width()-top.winfo_reqwidth())//2)
            y = self.window.winfo_rooty()+max(0, (self.window.winfo_height()-top.winfo_reqheight())//3)
            top.geometry(f'+{x}+{y}')
            top.focus_set()
        except tk.TclError:
            pass
        return top

    def _destroyed(self, event):
        if event.widget is self.window and not self.closed:
            self.closed = True
            self.jobs.put(None)
            if self.after_id is not None:
                try:
                    self.window.after_cancel(self.after_id)
                except self.tk.TclError:
                    pass
            # The worker owns this instance until its current disc read/render finishes.
            # Release Tk objects and the staged-control closure on the Tk thread now;
            # otherwise the worker can become their last owner and finalize Tcl there.
            self.photos.clear()
            self.labels.clear()
            self.popup = None
            self.blank = None
            self.values = None
            self.window = None
