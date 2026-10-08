"""Two-layer 'cinematic arena' loading and mode-menu artwork; offline PIL only.

compose() paints a fully covered background layer (mode-tinted gradient bands
and stepped ambient beams; no text, portraits or cards) and a foreground layer
whose KEY pixels let the background and the guest's animated lights show
through. `lights` tells the guest where to animate: a header sweep, glow
pillars behind the fighter columns, rising particles and post-foreground sheen
lanes (progress fill and thin edge strips that never touch text).

Every pixel is an axis-aligned rectangle for the existing sprite transport:
few wide gradient bands, chamfers/shadows only on scale>=2 text and panels,
40x40 portraits with 16 colours once a side has more than three fighters or a
free-for-all has more than six contestants. decorations=False drops shadows,
chamfers, rings, frames and bevels; it supplements the portrait colour tiers
rather than replacing them: twelve compact Tambourine portraits alone cost
about 7,000 rectangles, so only the 8-colour tier brings that worst case under
the guest's 10,240-sprite packet limit.

compose() and menu_compose() also return `text`, the bounding boxes of every
text run (shadow included), for lane validation; the guest ignores it. The
sweep starts at SWEEP x0 and travels across the whole frame (the guest reads
x1 only for validation), repainting the band under it with the colours sampled
at x0+1, so the header beam is washed out while the light passes: deliberate.
"""
from functools import lru_cache
from PIL import Image, ImageChops, ImageDraw

KEY = (255, 0, 255)
SIZE = (512, 448)
MARGIN, RIGHT = 28, 484
TOP_STRIP = (0, 0, 512, 6)
HEADING_Y, UNDERLINE_Y, SUBTITLE_Y = 16, 43, 51
EMBLEM_BOX = (432, 14, 484, 62)
FOOTER_Y = 348
BAR_BOX = (28, 370, 428, 398)
BAR_SEGMENTS = 20
FOOTER_STRIP = (0, 406, 512, 448)
FOOTER_EDGE = (0, 406, 512, 408)
MESSAGE_Y, MESSAGE_MAX = 423, 75
LANE_MIN_WIDTH = 14  # the guest sheen needs a lane at least this wide
# Header light band: x0/x1 exclude the dimmed 14px gutters so the guest samples
# its fade colours from the plain interior band at (x0+1, y0) and (x0+1, y1-1).
SWEEP = dict(x0=14, x1=498, y0=8, y1=66, width=64, speed=3)
WHITE, MUTED = (233, 239, 248), (153, 172, 201)
MENU_ROW_Y, MENU_ROW_STEP, MENU_ROW_BOX = 105, 49, (24, 488)
MENU_DETAILS = (
    ('PICK ONE TO FIVE FIGHTERS ON EACH SIDE.', 'NORMAL TEAMS / ONE OR TWO HUMAN PLAYERS.'),
    ('EVERY FIGHTER IS AN OPPONENT.', 'PICK ONE TO FIVE ON EACH SELECTION SIDE.'),
    ('PLAYER 1 AND PLAYER 2 ARE OPPONENTS.', 'PICK ONE TO FIVE ON EACH SELECTION SIDE.'),
    ('LEFT  TWO HUMANS + OPTIONAL CPUS.', 'RIGHT  UP TO FIVE CPUS. FIRST TWO LEFT PICKS ARE HUMAN.'),
    ('EVERY FIGHTER IS A CPU. YOU WATCH.', 'SWITCH WHO YOU FOLLOW WITH THE TARGET BUTTON.'),
    ('RETURN TO THE ORIGINAL GAME MENUS.', 'SIMULTANEOUS TEAM BATTLES STAY AVAILABLE.'))
# The fallback mode list takes the disc's own accept / back buttons (mode_menu: regional.RAW_ACCEPT / RAW_BACK).
from native_map import JPN as _JAPANESE_MENUS
MENU_HINT = ('D-PAD CHOOSE   O CONFIRM   X ORIGINAL MENU' if _JAPANESE_MENUS else
             'D-PAD CHOOSE   X CONFIRM   TRIANGLE ORIGINAL MENU')

# Glyphs the shared kill-feed font lacks; drawn here as plain rectangles only.
SUPPLEMENT = {
    '%': ['11001', '11010', '00010', '00100', '01000', '01011', '10011'],
    '+': ['00000', '00100', '00100', '11111', '00100', '00100', '00000'],
    ',': ['00000', '00000', '00000', '00000', '00110', '00100', '01000'],
    ':': ['00000', '00100', '00100', '00000', '00100', '00100', '00000'],
    '!': ['00100', '00100', '00100', '00100', '00100', '00000', '00100'],
    '&': ['01000', '10100', '10100', '01000', '10101', '10010', '01101'],
}

PALETTES = {
    'teams': dict(top=(24, 36, 64), upper=(14, 22, 40), lower=(7, 11, 20), bottom=(3, 5, 10),
                  beam=(46, 60, 104), footer=(6, 9, 17), accent=(234, 174, 61), glow=(255, 215, 132),
                  card=(18, 29, 47), edge=(48, 68, 100), shadow=(3, 5, 10), track=(12, 20, 33),
                  sides=((68, 179, 246), (245, 116, 97))),
    'ffa': dict(top=(52, 16, 46), upper=(30, 11, 30), lower=(14, 5, 14), bottom=(5, 2, 6),
                beam=(92, 34, 84), footer=(12, 4, 12), accent=(247, 98, 119), glow=(255, 178, 190),
                card=(31, 20, 40), edge=(88, 52, 92), shadow=(6, 2, 7), track=(22, 12, 28),
                sides=((247, 98, 119), (247, 98, 119))),
    'coop': dict(top=(10, 48, 56), upper=(8, 26, 32), lower=(4, 13, 16), bottom=(2, 5, 7),
                 beam=(22, 86, 96), footer=(3, 10, 12), accent=(70, 214, 181), glow=(176, 255, 232),
                 card=(14, 34, 42), edge=(34, 84, 92), shadow=(2, 6, 8), track=(9, 24, 30),
                 sides=((70, 214, 181), (246, 164, 93))),
    'menu': dict(top=(22, 34, 66), upper=(12, 19, 38), lower=(7, 11, 20), bottom=(3, 5, 10),
                 beam=(44, 58, 104), footer=(6, 9, 17), accent=(234, 174, 61), glow=(255, 222, 144),
                 card=(17, 27, 44), edge=(46, 66, 98), shadow=(3, 5, 10), track=(12, 20, 33),
                 selected=(39, 59, 83), text=(216, 230, 246), detail=(157, 180, 207)),
}


def _safe(color):
    color = tuple(int(c) for c in color)
    return (255, 0, 254) if color == KEY else color


def _mix(a, b, t):
    return _safe(tuple(round(a[i] + (b[i]-a[i])*t) for i in range(3)))


def _dim(color, t):
    return _mix(color, (0, 0, 0), t)


@lru_cache(maxsize=1)
def glyph_table():
    from guest_killfeed import GLYPHS
    return {**GLYPHS, **SUPPLEMENT}


def text_width(value, scale=1):
    return max(0, len(value)*6*scale - scale)


@lru_cache(maxsize=483*3)
def portrait(character_id, size=56, colors=32):
    """Real ISO portrait, resized and colour-bounded; never contains KEY."""
    from character_names import character_info
    with Image.open(character_info(character_id)['bitmap_path']) as source:
        image = source.convert('RGB').resize((size, size)).quantize(colors=colors).convert('RGB')
    if KEY in [color for _, color in image.getcolors(size*size)]:
        image.putdata([_safe(px) for px in image.getdata()])
    return image


class Layer:
    """An RGB layer painted with exclusive-end rectangles; records text boxes."""
    def __init__(self, fill):
        # KEY is only ever the whole-layer clear colour, never a painted one.
        self.image = Image.new('RGB', SIZE, KEY if fill == KEY else _safe(fill))
        self.draw = ImageDraw.Draw(self.image)
        self.text_boxes = []

    def fill(self, box, color):
        x0, y0, x1, y1 = (int(v) for v in box)
        if x1 > x0 and y1 > y0:
            self.draw.rectangle((x0, y0, x1-1, y1-1), fill=_safe(color))

    def panel(self, box, color, chamfer=0, edge=None):
        x0, y0, x1, y1 = box
        c = max(0, min(chamfer, (y1-y0)//2, x1-x0))
        for i in range(c):
            self.fill((x0, y0+i, x1-(c-i), y0+i+1), color)
            self.fill((x0, y1-1-i, x1-(c-i), y1-i), color)
        self.fill((x0, y0+c, x1, y1-c), color)
        if edge:
            self.fill((x0, y0, x1-c, y0+1), edge)
            self.fill((x0, y1-1, x1-c, y1), edge)
            self.fill((x1-1, y0+c, x1, y1-c), edge)

    def paste(self, image, x, y):
        self.image.paste(image, (int(x), int(y)))

    def text(self, value, x, y, color, scale=1, maxlen=70, shadow=None):
        table = glyph_table()
        value = str(value).upper()[:max(0, maxlen)]
        if not value:
            return 0
        if shadow is not None:
            self._glyphs(value, x+scale, y+scale, shadow, scale, table)
        self._glyphs(value, x, y, color, scale, table)
        width = text_width(value, scale)
        extra = scale if shadow is not None else 0
        self.text_boxes.append((x, y, x+width+extra, y+7*scale+extra))
        return width

    def _glyphs(self, value, x, y, color, scale, table):
        color = _safe(color)
        for ch in value:
            for yy, bits in enumerate(table.get(ch, table['?'])):
                xx = 0
                while xx < 5:
                    if bits[xx] == '0':
                        xx += 1; continue
                    start = xx
                    while xx < 5 and bits[xx] == '1':
                        xx += 1
                    self.draw.rectangle((x+start*scale, y+yy*scale, x+xx*scale-1, y+(yy+1)*scale-1), fill=color)
            x += 6*scale


def _wrapped(text, maxlen, lines=2):
    result = ['']
    for word in str(text).upper().replace('SUPER SAIYAN', 'SS').split():
        if result[-1] and len(result[-1])+len(word)+1 > maxlen:
            result.append(word)
        else:
            result[-1] = ' '.join((result[-1], word)).strip()
    return [line[:maxlen] for line in result[:lines]]


def _band_color(palette, y):
    stops = ((0, palette['top']), (108, palette['upper']), (346, palette['lower']), (448, palette['bottom']))
    for (y0, a), (y1, b) in zip(stops, stops[1:]):
        if y0 <= y <= y1:
            return _mix(a, b, (y-y0)/(y1-y0))
    return palette['bottom']


def background_layer(palette, columns=(), strip=True):
    """Fourteen 32px gradient bands, side gutters, two stepped beams, a faint
    column wash behind the fighter columns and the footer strip. No text."""
    layer = Layer(palette['bottom'])
    beam = palette['beam']
    for band in range(14):
        y0, y1 = band*32, band*32+32
        base = _band_color(palette, y0+16)
        layer.fill((0, y0, 512, y1), base)
        layer.fill((0, y0, 14, y1), _dim(base, .35))
        layer.fill((498, y0, 512, y1), _dim(base, .35))
    for x0, x1 in columns:
        for band in range(3, 11):
            y0, y1 = max(band*32, 98), min(band*32+32, 346)
            layer.fill((x0, y0, x1, y1), _mix(_band_color(palette, band*32+16), beam, .12))
    # Two stepped diagonal beams: one behind the header, one behind the bar.
    for k in range(13):
        y0 = k*8
        x0 = 300 - k*14
        layer.fill((x0, y0, x0+150, y0+8), _mix(_band_color(palette, y0+4), beam, .32))
        layer.fill((x0+40, y0, x0+110, y0+8), _mix(_band_color(palette, y0+4), beam, .5))
    for k in range(7):
        y0 = 350 + k*8
        x0 = 452 - k*22
        layer.fill((x0, y0, min(498, x0+200), y0+8), _mix(_band_color(palette, y0+4), beam, .3))
    if strip:
        layer.fill(FOOTER_STRIP, palette['footer'])
    return layer.image


def _heading(fg, palette, heading, subtitle, decorations):
    accent, glow = palette['accent'], palette['glow']
    fg.fill(TOP_STRIP, accent)
    fg.fill((0, 6, 512, 7), _dim(accent, .5))
    width = fg.text(heading, MARGIN, HEADING_Y, WHITE, 3, maxlen=22,
                    shadow=palette['shadow'] if decorations else None)
    fg.fill((MARGIN, UNDERLINE_Y, MARGIN+width+18, UNDERLINE_Y+4), accent)
    fg.fill((MARGIN+width+18, UNDERLINE_Y+1, 424, UNDERLINE_Y+3), _dim(accent, .55))
    fg.text(subtitle, MARGIN+1, SUBTITLE_Y, MUTED, 1, maxlen=64)
    return dict(x0=MARGIN, y0=UNDERLINE_Y, x1=MARGIN+width+18, y1=UNDERLINE_Y+4, color=glow)


def _emblem(fg, palette, mode, decorations):
    x0, y0, x1, y1 = EMBLEM_BOX
    accent = palette['accent']
    if decorations:
        fg.panel(EMBLEM_BOX, palette['card'], chamfer=4, edge=palette['edge'])
    cx, cy = (x0+x1)//2, (y0+y1)//2
    if mode == 'ffa':
        fg.draw.polygon([(cx, cy-17), (cx+17, cy), (cx, cy+17), (cx-17, cy)], outline=_safe(accent), width=2)
        for x, y in ((cx, cy-17), (cx+17, cy), (cx, cy+17), (cx-17, cy)):
            fg.fill((x-2, y-2, x+3, y+3), accent)
    elif mode == 'coop':
        fg.draw.rectangle((cx-15, cy-15, cx+3, cy+3), outline=_safe(accent), width=3)
        fg.draw.rectangle((cx-3, cy-3, cx+15, cy+15), outline=_safe(accent), width=3)
    else:
        for dx, color in ((-11, palette['sides'][0]), (3, palette['sides'][1])):
            for dy in (-15, -3, 9):
                fg.fill((cx+dx, cy+dy, cx+dx+8, cy+dy+8), color)


def _team_bar(fg, palette, box, label, color, right_text, decorations, maxlen=12):
    x0, y0, x1, y1 = box
    fg.panel(box, _mix(palette['card'], color, .22), chamfer=3 if decorations else 0,
             edge=_mix(palette['edge'], color, .3) if decorations else None)
    fg.fill((x0, y0, x0+5, y1), color)
    fg.text(label, x0+13, y0+3, color, 2, maxlen=maxlen, shadow=palette['shadow'] if decorations else None)
    if right_text:
        fg.text(right_text, x1-10-text_width(right_text), y0+7, MUTED, 1, maxlen=14)


def _card(fg, palette, card, colors, decorations):
    x, y, w, h = card['x'], card['y'], card['width'], card['height']
    color, info, size = card['accent'], card['info'], card['portrait']
    small = card.get('small', False)
    if decorations:
        fg.fill((x+2, y+h, x+w+2, y+h+2), palette['shadow'])
        fg.fill((x+w, y+2, x+w+2, y+h, ), palette['shadow'])
    fg.panel((x, y, x+w, y+h), palette['card'], chamfer=3 if decorations else 0,
             edge=palette['edge'] if decorations else None)
    fg.fill((x, y, x+4, y+h), color)
    px, py = (x+6, y+6) if small else (x+8, y+8)
    if decorations:
        fg.fill((px-2, py-2, px+size+2, py+size+2), _mix(palette['edge'], color, .5))
    fg.paste(portrait(info['character_id'], size, min(colors, 16) if small else colors), px, py)
    form = info['form'].replace('Super Saiyan', 'SS')
    number = str(card.get('number', 0)).zfill(2)
    if small:
        maxlen = (w-12)//6
        # 'PLAYER 1' is eight glyphs (47px): x+52+47 stays inside the 102px card
        # and clear of the right edge line; the chamfer never reaches this row.
        fg.text(card['role'], x+52, y+9, color, 1, maxlen=(w-53)//6)
        fg.text(number, x+52, y+21, WHITE, 2, maxlen=2)
        for j, line in enumerate(_wrapped(info['base_name'], maxlen)):
            fg.text(line, x+6, y+50+j*9, WHITE, 1, maxlen=maxlen)
        if form:
            fg.text(form, x+6, y+68, color, 1, maxlen=maxlen)
    elif card['compact']:
        fg.text(card['role'], x+72, y+12, color, 1, maxlen=11)
        fg.text('FIGHTER', x+72, y+31, MUTED, 1, maxlen=11)
        fg.text(number, x+72, y+44, WHITE, 2, maxlen=2)
        for j, line in enumerate(_wrapped(info['base_name'], 21)):
            fg.text(line, x+8, y+72+j*10, WHITE, 1, maxlen=21)
        if form:
            fg.text(form, x+8, y+94, color, 1, maxlen=21)
    else:
        for j, line in enumerate(_wrapped(info['base_name'], 22)):
            fg.text(line, x+74, y+10+j*10, WHITE, 1, maxlen=22)
        if form:
            fg.text(form, x+74, y+34, color, 1, maxlen=22)
        fg.text(card['role'], x+74, y+54, MUTED, 1, maxlen=22)


def _vs_badge(fg, palette, cy, span, decorations):
    accent = palette['accent']
    x0, x1 = 242, 270
    if decorations:
        fg.fill((255, span[0]+6, 257, cy-20), _dim(accent, .6))
        fg.fill((255, cy+20, 257, span[1]-6), _dim(accent, .6))
    fg.panel((x0, cy-12, x1, cy+12), palette['card'], chamfer=3 if decorations else 0,
             edge=accent if decorations else None)
    fg.text('VS', 245, cy-7, accent, 2, maxlen=2)


def _progress(fg, palette, p, decorations):
    """Segmented energy gauge: framed track, twenty 5% cells, a graded fill with
    a bright cap, ticks and the percentage. Returns the sheen lane over the fill
    plus the tip flare and spark bolt the guest animates."""
    x0, y0, x1, y1 = BAR_BOX
    accent, glow, track, edge = palette['accent'], palette['glow'], palette['track'], palette['edge']
    fg.fill(BAR_BOX, edge)
    fg.fill((x0+1, y0+1, x1-1, y1-1), track)
    if decorations:
        fg.fill((x0+1, y0+1, x1-1, y0+2), _dim(track, .55))
        fg.fill((x0+1, y1-2, x1-1, y1-1), _mix(track, edge, .6))
        fg.fill((x0-2, y0-2, x1+2, y0), _dim(accent, .55))
        fg.fill((x0-2, y1, x1+2, y1+2), _dim(accent, .55))
        fg.fill((x0-2, y0, x0, y1), _dim(accent, .55))
        fg.fill((x1, y0, x1+2, y1), _dim(accent, .55))
    inner = x1-x0-4
    end = x0+2+round(inner*p/100)
    rows = ((y0+2, y0+8, glow), (y0+8, y1-9, accent), (y1-9, y1-5, _mix(accent, palette['shadow'], .3)),
            (y1-5, y1-2, _dim(accent, .45)))
    if p > 0:
        for ry0, ry1, color in rows:
            fg.fill((x0+2, ry0, end, ry1), color)
    # Cell dividers over track and fill alike; the filled ones read as segments.
    for k in range(1, BAR_SEGMENTS):
        tx = x0+2+round(inner*k/BAR_SEGMENTS)
        fg.fill((tx, y0+2, tx+1, y1-2), _dim(track, .5) if tx >= end else _dim(accent, .5))
    if p > 0:
        fg.fill((max(x0+2, end-2), y0+2, end, y1-2), (255, 255, 255))
    if decorations:
        for k in range(0, 11):
            tx = x0+2+round(inner*k/10)
            fg.fill((tx, y1+2, tx+1, y1+5 if k % 5 == 0 else y1+4), edge)
    label = f'{p}%'
    fg.text(label, RIGHT-text_width(label, 2), y0+7, WHITE, 2, maxlen=4)
    lane = None
    if p > 0 and end-(x0+2) >= LANE_MIN_WIDTH:
        lane = dict(x0=x0+2, y0=y0+2, x1=end, y1=y1-2, color=glow)
    flare = None; spark = None
    if p > 0 and end+4 <= x1-2:
        flare = dict(x=end, y0=y0+2, y1=y1-2, amplitude=12,
                     left_top=glow, left_bottom=_dim(accent, .45), center_top=(255, 255, 255), center_bottom=(255, 250, 220),
                     right_top=_dim(track, .55), right_bottom=_mix(track, edge, .6))
        spark = _bolt(max(0, end-18), max(0, y0-6), min(512, end+18), min(448, y1+6), palette, 31, 6)
    return lane, flare, spark


def _footer(fg, palette, footer, message, decorations):
    fg.text(footer, MARGIN, FOOTER_Y, WHITE, 2, maxlen=30, shadow=palette['shadow'] if decorations else None)
    fg.fill(FOOTER_EDGE, _dim(palette['accent'], .45))
    fg.text(message, MARGIN, MESSAGE_Y, MUTED, 1, maxlen=MESSAGE_MAX)
    return dict(x0=0, y0=FOOTER_EDGE[1], x1=512, y1=FOOTER_EDGE[3], color=palette['glow'])


def _lights(palette, sweep, pillars, particles, lanes, bolts=()):
    return dict(accent=_safe(palette['accent']), glow=_safe(palette['glow']), background=_safe(palette['upper']),
                sweep=sweep, pillars=pillars[:4], particles=particles, lanes=[lane for lane in lanes if lane][:4],
                bolts=list(bolts)[:4])


def _bolt(x0, y0, x1, y1, palette, period, duration, core=(255, 255, 255)):
    """A lightning anchor: the guest jitters the inner points and flickers it."""
    return dict(x0=x0, y0=y0, x1=x1, y1=y1, color=_safe(core), glow=_safe(palette['glow']),
                period=period, duration=duration)


def compose(teams=(), progress=0, message='GETTING YOUR FIGHTERS READY', *, mode='teams', humans=1,
            portrait_colors=32, decorations=True):
    """Background and foreground layers plus light descriptors for one screen."""
    from loading_design import design
    view = design(teams, mode, humans)
    mode = view['mode']
    palette = PALETTES[mode]
    p = max(0, min(100, int(progress)))
    columns = [(c['x0'], c['x1']) for c in view['columns']]
    background = background_layer(palette, columns)
    fg = Layer(KEY)
    lanes = [dict(x0=0, y0=0, x1=512, y1=TOP_STRIP[3], color=palette['glow'])]
    lanes.append(_heading(fg, palette, view['heading'], view['subtitle'], decorations))
    _emblem(fg, palette, mode, decorations)
    if mode == 'ffa':
        _team_bar(fg, palette, (MARGIN, 70, RIGHT, 90), view['detail'], palette['accent'], None,
                  decorations, maxlen=30)
    else:
        for group in view['groups']:
            count = sum(card['side'] == group['side'] for card in view['cards'])
            _team_bar(fg, palette, group['box'], group['label'], group['accent'],
                      f'{count} FIGHTER' + ('' if count == 1 else 'S') if count else None, decorations)
    for card in view['cards']:
        _card(fg, palette, card, portrait_colors, decorations)
    if mode != 'ffa' and view['cards']:
        _vs_badge(fg, palette, view['vs_y'], view['vs_span'], decorations)
    lane, flare, spark = _progress(fg, palette, p, decorations)
    lanes.append(lane)
    lanes.append(_footer(fg, palette, view['footer'], message, decorations))
    pillars = [dict(x0=c['x0'], y0=c['y0'], x1=c['x1'], y1=c['y1'],
                    color=_mix(palette['upper'], c['accent'], .35)) for c in view['columns']]
    particles = dict(count=12, x0=14, x1=498, y0=8, y1=400, color=_safe(palette['glow']))
    # Lightning: along the top strip, under the heading, down the VS divider
    # (or across the FFA detail bar) and just above the progress bar.
    bolts = [_bolt(0, 2, 512, 4, palette, 127, 10),
             _bolt(MARGIN, UNDERLINE_Y+1, 424, UNDERLINE_Y+3, palette, 255, 12, core=(255, 250, 220))]
    if mode != 'ffa' and view['cards']:
        bolts.append(_bolt(255, view['vs_span'][0]+6, 257, view['vs_span'][1]-6, palette, 63, 9))
    else:
        bolts.append(_bolt(MARGIN, 79, RIGHT, 81, palette, 63, 9))
    if spark: bolts.append(spark)
    lights = _lights(palette, dict(SWEEP), pillars, particles, lanes, bolts)
    lights['flares'] = [flare] if flare else []
    return dict(background=background, foreground=fg.image, lights=lights, text=list(fg.text_boxes))


def composite(layers):
    """Foreground over background; KEY pixels are transparent."""
    foreground, background = layers['foreground'], layers['background']
    difference = ImageChops.difference(foreground, Image.new('RGB', foreground.size, KEY))
    mask = None
    for band in difference.split():
        band = band.point(lambda v: 255 if v else 0)
        mask = band if mask is None else ImageChops.lighter(mask, band)
    return Image.composite(foreground, background, mask)


def picture(teams=(), progress=0, message='GETTING YOUR FIGHTERS READY', *, mode='teams', humans=1):
    return composite(compose(teams, progress, message, mode=mode, humans=humans))


def menu_compose(choice, decorations=True):
    """Mode-menu panel layers: five option rows, the selected one highlighted."""
    from mode_menu import OPTIONS
    if isinstance(choice, bool) or choice not in range(len(OPTIONS)):
        raise ValueError('Invalid in-game mode selection')
    palette = PALETTES['menu']
    accent, glow = palette['accent'], palette['glow']
    background = background_layer(palette)
    fg = Layer(KEY)
    lanes = []
    fg.fill(TOP_STRIP, accent)
    fg.fill((0, 6, 512, 7), _dim(accent, .5))
    width = fg.text('MULTIFIGHTER', MARGIN, HEADING_Y, glow, 3, maxlen=12,
                    shadow=palette['shadow'] if decorations else None)
    fg.fill((MARGIN, UNDERLINE_Y, MARGIN+width+18, UNDERLINE_Y+4), accent)
    fg.fill((MARGIN+width+18, UNDERLINE_Y+1, RIGHT, UNDERLINE_Y+3), _dim(accent, .55))
    fg.text('CHOOSE YOUR BATTLE', MARGIN+1, SUBTITLE_Y+2, MUTED, 2, maxlen=20)
    x0, x1 = MENU_ROW_BOX
    bolts = [_bolt(0, 2, 512, 4, palette, 127, 10),
             _bolt(MARGIN, UNDERLINE_Y+1, RIGHT, UNDERLINE_Y+3, palette, 255, 12, core=(255, 250, 220))]
    for i, label in enumerate(OPTIONS):
        y = MENU_ROW_Y + MENU_ROW_STEP*i
        selected = i == choice
        if selected:
            bolts.append(_bolt(x0, y+1, x1, y+2, palette, 63, 8))
            bolts.append(_bolt(x0, y+37, x1, y+38, palette, 63, 8))
        fg.panel((x0, y, x1, y+39), palette['selected'] if selected else palette['card'],
                 chamfer=3 if decorations else 0,
                 edge=(_mix(palette['edge'], accent, .4) if selected else palette['edge']) if decorations else None)
        if selected:
            fg.fill((x0, y, x1, y+3), accent)
            fg.fill((x0, y+36, x1, y+39), accent)
            fg.fill((x0, y, x0+6, y+39), accent)
            fg.text('>', x0+14, y+12, accent, 2, maxlen=1)
            lanes.append(dict(x0=x0, y0=y, x1=x1, y1=y+3, color=glow))
            lanes.append(dict(x0=x0, y0=y+36, x1=x1, y1=y+39, color=glow))
        else:
            fg.fill((x0, y, x0+3, y+39), _dim(accent, .6))
        fg.text(label, x0+30, y+12, glow if selected else palette['text'], 2, maxlen=36)
    for i, line in enumerate(MENU_DETAILS[choice]):
        fg.text(line, MARGIN, 356+i*15, palette['detail'], 1, maxlen=75)
    fg.fill(FOOTER_EDGE, _dim(accent, .45))
    fg.text(MENU_HINT, MARGIN, MESSAGE_Y, glow, 1, maxlen=MESSAGE_MAX)
    lights = _lights(palette, dict(SWEEP), [], None, lanes, bolts)
    return dict(background=background, foreground=fg.image, lights=lights, text=list(fg.text_boxes))


def menu_picture(choice):
    return composite(menu_compose(choice))
