"""Compare replacement sprites with the original game's resident node tree (this tree's own game: BT3 or BT4)."""
import struct
import unittest

import viewport_hud as hud
import viewport_hud_art as art
import test_viewport_hud_art as fixture
from test_viewport_hud_final_phase import run


def native_boxes():
    ram = fixture.source()
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    s = lambda p: struct.unpack_from('<i', ram, p)[0]
    manager = u(0x304270 - 0x5728)
    table = u(manager + 4)
    root = u(u(0x304270 - 22324))
    boxes = {}

    def visit(node, x=0, y=0):
        x += s(node + 16) + s(node + 24)
        y += s(node + 20) + s(node + 28)
        for i in range(u(node + 32)):
            ptr = u(u(node + 36) + 4*i)
            x0, x1, y0, y1 = struct.unpack_from('<4h', ram, ptr + 8)
            boxes[ptr-table] = (x+x0, y+y0, x+x1, y+y1)
        for i in range(u(node + 40)):
            visit(u(u(node + 44) + 4*i), x, y)

    visit(root)
    fx, fy, _, _ = boxes[0]
    return {off: (x0-fx, y0-fy, x1-fx, y1-fy)
            for off, (x0, y0, x1, y1) in boxes.items()}


class NativeAlignmentTests(unittest.TestCase):
    def test_gauges_and_portrait_use_authored_frame_relative_positions(self):
        expected = native_boxes()
        # Full and fractional sizes, including the previous 113px regression.
        for width in (113, 120, 148, 256):
            for mirror in (0, 1):
                with self.subTest(width=width, mirror=mirror):
                    c = fixture.machine()
                    actor = fixture.old.feed_test.ACTORS[4]
                    for off, value in ((0, 40000), (12, 100000), (20, 350000)):
                        c.w(actor + 0x9E4 + off, value)
                    c.r[4:9] = [4, 0, 0, width, mirror]
                    run(c, art.NATIVE_PANEL)

                    def check(sprite, native_off, crop=None, dx=0):
                        box = list(expected[native_off])
                        box[0] += dx; box[2] += dx
                        if crop is not None: box[2] = box[0] + crop
                        if box[1] < 0:
                            # A node above the frame's top (BT4's portrait) drops the cell's transparent top rows.
                            self.assertEqual(min(sprite[4], sprite[6]), -box[1]); box[1] = 0
                        x0, y0, x1, y1 = [n*width//16 for n in box]
                        if mirror: x0, x1 = width*16-x1, width*16-x0
                        self.assertEqual(sprite[7:11], (x0, y0, x1, y1))

                    sprites = c.subpixel_sprites
                    check(next(s for s in sprites if s[11]&1), 0x700)
                    self.assertEqual(art.LAYOUTS[art.LAYOUT][0], tuple(expected[0x700][:2]))
                    for s in (s for s in sprites if s[1] == 8 and min(s[3],s[5]) == 0 and s[4] == 0):
                        check(s, 0x54)
                    pips = [s for s in sprites if s[1] == 8 and s[4:7:2] == (16,32)]
                    self.assertEqual(len(pips), 3)
                    for i, s in enumerate(pips): check(s, 0xFC+28*i)
                    ki = [s for s in sprites if s[1:3] == (8,1) and min(s[3],s[5]) == 16]
                    self.assertEqual(len(ki), 5)
                    # Band i is the first band's record moved 8 units right (BT4 parks empty bands off-screen).
                    for i, s in enumerate(ki): check(s, 0x2BC, dx=8*i)
                    check(next(s for s in sprites if s[1] == 15), 0x3F0)
                    check(next(s for s in sprites if s[1] == 14), 0x3D4)
                    check(next(s for s in sprites if s[1] == 8 and min(s[3],s[5]) == 161), 0x428, 13)

    @unittest.skipUnless(art.LAYOUT == 'bt3', "the BT4 fixture's actual-packet path exceeds the emulator's "
                         "instruction budget (also before the BT4 layout)")
    def test_final_gs_packets_keep_ki_bands_equal_at_fractional_scales(self):
        import widescreen_support as wide
        for width in (113, 120, 146):
            for mirror in (0, 1):
                for widescreen in (False, True):
                    with self.subTest(width=width, mirror=mirror, wide=widescreen):
                        c = fixture.machine(actual=True)
                        actor = fixture.old.feed_test.ACTORS[4]
                        c.w(actor+0x9E4+12,100000)
                        c.w(actor+0x9E4+28,0)
                        c.w(actor+0x1085,0);c.w(actor+0x10AD,0)
                        if widescreen:
                            for address,value in wide.WORDS:c.w(address,value)
                        c.r[4:9]=[4,0,0,width,mirror]
                        run(c,art.NATIVE_PANEL)
                        bands=[]
                        for packet in c.packets:
                            if len(packet)!=192:continue
                            u0,v0=struct.unpack_from('<2H',packet,160)
                            u1,v1=struct.unpack_from('<2H',packet,176)
                            if (min(u0,u1),max(u0,u1),v0,v1)!=(264,488,264,536):continue
                            x0,y0=struct.unpack_from('<2H',packet,168)
                            x1,y1=struct.unpack_from('<2H',packet,184)
                            bands.append((x0,y0,x1,y1))
                        self.assertEqual(len(bands),5)
                        widths=[b[2]-b[0]for b in bands]
                        expected=14*width/16*(.75 if widescreen else 1)
                        self.assertTrue(all(abs(w-expected)<=2 for w in widths))
                        self.assertLessEqual(max(widths)-min(widths),2)
                        bands.sort()
                        gaps=[bands[i+1][0]-bands[i][0]for i in range(4)]
                        self.assertLessEqual(max(gaps)-min(gaps),2)
                        if width==120 and not widescreen:
                            self.assertEqual(widths,[105]*5)  # 6.5625px, never 6/7px
                            self.assertEqual(gaps,[60]*4)    # exactly 3.75px apart


if __name__ == '__main__':
    unittest.main()
