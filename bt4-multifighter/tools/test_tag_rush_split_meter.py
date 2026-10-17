"""The split-screen tag meter sits in empty space inside its own native panel.

Executes viewport_hud_art's panel for this tree's game (BT3 or BT4) and rasterises every sprite it emits with the
alpha of the game's own resident art (frame, portrait, gauges, digit, stock gauge) from the captured fixture RAM. The
meter (bar and backing) and its label, measured with the game's resident font as the native kit draws it, may not
cover a visible pixel, must stay inside the panel and the label must fit the meter: every panel size the layouts give,
both mirrors, 4:3 and anamorphic 16:9, English and Spanish.
"""
import functools
import struct
import unittest

import localization
import native_hud_style as kit
import tag_rush_hud as tag
import test_viewport_hud_art as fixture
import viewport_hud_art as art
import widescreen_support as wide
from test_viewport_hud_final_phase import run

SAMPLES = 4          # sub-samples per logical pixel
VISIBLE = 24         # alpha (0..128) that counts as drawn


def _u(ram, p):
    return struct.unpack_from('<I', ram, p)[0]


@functools.lru_cache(maxsize=None)
def _alpha(table, index, palette):
    """Alpha rows of an 8-bit indexed resident atlas (CSM1 palette), as the native HUD samples it."""
    ram = fixture.source()
    d, pd = table+64*index, table+64*(index+palette)
    tex0, high = _u(ram, d+48), _u(ram, d+52)
    width, height = 1 << ((tex0 >> 26) & 15), 1 << (((tex0 >> 30) & 3) | ((high & 3) << 2))
    pixels, colours = _u(ram, d+56)+0x60, _u(ram, pd+60)+0x60
    rows = []
    for y in range(height):
        row = bytearray(width)
        for x in range(width):
            source = ((y & ~15)*width+(x & ~15)*2+((((y & ~3) >> 1)+(y & 1)) & 7)*width*2
                      + ((x+(((y+2) >> 2) & 1)*4) & 7)*4+((y >> 1) & 1)+((x >> 2) & 2))
            i = ram[pixels+source]
            j = (i & 0xE7) | ((i & 8) << 1) | ((i & 16) >> 1)
            row[x] = ram[colours+4*j+3]
        rows.append(bytes(row))
    return tuple(rows)


def drawn(width, mirror, widescreen):
    """Set of (x, y) sub-samples (panel-relative, SAMPLES per px) covered by visible panel art."""
    c = fixture.machine()
    actor = fixture.old.feed_test.ACTORS[4]
    for off, value in ((0, 40000), (12, 100000), (20, 350000)):
        c.w(actor+0x9E4+off, value)
    if widescreen:
        for address, value in wide.WORDS:
            c.w(address, value)
    c.r[4:9] = [4, 0, 0, width, mirror]
    run(c, art.NATIVE_PANEL)
    ram = fixture.source()
    covered = set()
    for bundle, index, palette, u0, v0, u1, v1, x0, y0, x1, y1, _flags, color in c.subpixel_sprites:
        if (color >> 24) < 0x20:
            continue
        rows = _alpha(_u(ram, bundle+16), index, palette)
        left, right = sorted((x0, x1))
        for sy in range(y0*SAMPLES//16, -(-y1*SAMPLES//16)):
            fy = (sy+.5)*16/SAMPLES
            if not y0 <= fy < y1:
                continue
            v = int(v0+(fy-y0)*(v1-v0)/(y1-y0))
            for sx in range(left*SAMPLES//16, -(-right*SAMPLES//16)):
                fx = (sx+.5)*16/SAMPLES
                if not left <= fx < right:
                    continue
                t = (fx-x0)/(x1-x0)
                uu = int(u0+t*(u1-u0)) if u1 > u0 else int(u0-1-t*(u0-u1)) if u0 > u1 else u0
                if 0 <= v < len(rows) and 0 <= uu < len(rows[0]) and rows[v][uu] > VISIBLE:
                    covered.add((sx, sy))
    return covered


@functools.lru_cache(maxsize=None)
def label_extent(text, units):
    """(left, top, right, bottom) of the label in px relative to its pen (x, y), as NTEXT draws it: glyph advances
    and rows of the resident font, its italic shear and the baked ~1.5-texel outline."""
    ram = fixture.source()
    font = kit.find_font(ram)
    width, height, indices = kit.font_planes(ram, font)
    advance, top, bottom = 0, 99, -1
    for ch in text:
        gx, gy, w, plane = font['glyphs'][ord(ch)]
        advance += w
        for row in range(20):
            for col in range(w):
                v = indices[(gy+row)*width+gx+col]
                if ((v >> 2) & 3 if plane else v & 3):
                    top, bottom = min(top, row), max(bottom, row)
    scale = units/16
    outline = 2
    return (-outline*scale, (top-kit.CAP_TOP-outline)*scale,
            (advance+kit.SHEAR+outline)*scale, (bottom+1-kit.CAP_TOP+outline)*scale)


class SplitTagMeterTests(unittest.TestCase):
    # Every panel width the layouts produce: 2/3/4 views at 80..140% (4:3 fit 120, 16:9 3/4-view limit 148), co-op
    # player panels and top/bottom full-width panels.
    WIDTHS = (96, 100, 104, 108, 110, 116, 120, 121, 130, 140, 148, 246, 253, 256)

    def test_meter_and_label_sit_in_empty_space_inside_their_own_panel(self):
        for widescreen in (False, True):
            k = .75 if widescreen else 1
            for width in self.WIDTHS:
                for mirror in (0, 1):
                    covered = drawn(width, mirror, widescreen)
                    m = tag.panel_meter(width, bool(mirror), widescreen)
                    for language in ('en', 'es'):
                        with self.subTest(width=width, mirror=mirror, wide=widescreen, language=language):
                            text = localization.guest(m['label'], {'language': language}).decode()
                            l, t, r, b = label_extent(text, m['units'])
                            boxes = {'label': (m['x']+l, m['y']+t, m['x']+r, m['y']+b),
                                     'meter': (m['x']-1, m['bar']-1, m['x']+m['width']+1, m['bar']+tag.HEIGHT+1)}
                            # The label fits its meter (one outline pixel of slack) and both stay in the panel.
                            self.assertLessEqual(r-l-2*m['units']/16*2, m['width']+1)
                            for name, (x0, y0, x1, y1) in boxes.items():
                                self.assertGreaterEqual(x0, -1, name)
                                self.assertLessEqual(x1, width*k+1 if not mirror else width+1, name)
                                if mirror:
                                    self.assertGreaterEqual(x0, width-width*k-1, name)
                                self.assertLessEqual(y1, width/4+1, name)
                                hits = [(sx, sy) for sx in range(int(x0*SAMPLES), int(x1*SAMPLES))
                                        for sy in range(int(y0*SAMPLES), int(y1*SAMPLES)) if (sx, sy) in covered]
                                self.assertEqual(hits[:3], [], name)

    def test_label_sizes_step_down_with_the_meter_and_never_grow_past_three_quarters(self):
        sizes = [tag.panel_meter(w, False, ws)['units'] for ws in (False, True) for w in range(80, 257)]
        self.assertEqual(max(sizes), 6)
        self.assertEqual(set(sizes), {5, 6})
        for w in range(80, 257):
            for ws in (False, True):
                m = tag.panel_meter(w, False, ws)
                self.assertLessEqual(m['width'], tag.WIDTH)
                self.assertEqual(m['label'] == tag.COMPACT_LABEL, m['width'] < tag.COMPACT_BELOW)


class OwnPanelTests(unittest.TestCase):
    SUBJECTS = 0x2200000

    def test_panel_records_where_it_shows_each_views_own_fighter_and_nothing_for_a_target(self):
        import viewport_hud as hud
        c = fixture.machine()
        views = ((1, 0, 254, 0, 447, self.SUBJECTS), (1, 257, 511, 0, 447, self.SUBJECTS+4))
        c.w(hud.CONTROL+12, 2); c.w(hud.CONTROL+20, 7); c.w(self.SUBJECTS, 3); c.w(self.SUBJECTS+4, 4)
        c.write(hud.VIEWS, b''.join(struct.pack('<6I', *v) for v in views))
        c.write(art.OWN, bytes(art.OWN_STRIDE*hud.MAX_VIEWS))
        for subject, x, y, width, mirror in ((4, 10, 2, 120, 0),      # fighter 4 drawn in view 0: a target there
                                             (4, 300, 2, 120, 0),     # view 1's own fighter, left-facing on its left
                                             (3, 380, 330, 102, 1)):  # fighter 3 in view 1 (bottom target)
            c.r[4:9] = [subject, x, y, width, mirror]; run(c, art.NATIVE_PANEL)
        rows = [struct.unpack_from('<4I', c.read(art.OWN, 32), 16*i) for i in range(2)]
        self.assertEqual(rows[0], (0, 0, 0, 0))
        self.assertEqual(rows[1], (300, 2, 120, 7))
        for address, value in wide.WORDS: c.w(address, value)
        c.r[4:9] = [4, 389, 2, 120, 1]; run(c, art.NATIVE_PANEL)
        self.assertEqual(struct.unpack_from('<4I', c.read(art.OWN+16, 16)), (389, 2, 120 | 1 << 16 | 1 << 17, 7))

    def test_meter_follows_its_views_own_panel_record_wherever_it_is_drawn(self):
        import test_tag_rush_hud as base
        import quad_viewports as quad
        import viewport_hud as hud
        case = base.TagRushHudTests('test_every_view_places_the_meter_below_its_own_status')
        words = case.LAYOUTS['top']
        for humans in (2, 3, 4):
            views = quad.rectangles(humans)
            for seat in range(humans):
                x0, x1, y0, y1 = views[seat]
                # The own panel on the side the layout rule would not choose, and lower in the view.
                right = not seat & 1
                w = 110
                own = (x1-1-w if right else x0+1, y0+40, w, right, False)
                for stale in (False, True):
                    with self.subTest(humans=humans, seat=seat, stale=stale):
                        c = case.split_machine(humans, seat, words, False)
                        c.w(hud.CONTROL+20, 50)
                        c.write(art.OWN+art.OWN_STRIDE*seat, struct.pack('<4I', own[0], own[1], w | right << 16,
                                                                     50-tag.OWN_PASSES if stale else 49))
                        base.draw(c)
                        m = tag.meter(views[seat], split=seat, settings=words, views=humans,
                                      own=None if stale else own)
                        self.assertEqual(c.texts[-1][1:3], (m['x'], m['y']))
                        self.assertEqual(c.rects[-1][1], m['bar'])


if __name__ == '__main__':
    unittest.main()
