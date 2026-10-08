"""Protocol v4: register words decoded field by field, VRAM footprints, the packet A/B walk, the
descriptor layout and its round trip through a real Ki Storm plan. Offline only."""
import struct
import unittest
from functools import lru_cache

import loading_art_v4 as art
import loading_lights_a as ks_a
import loading_lights_b as ks_b
import loading_protocol as protocol
import loading_texture_probe as probe
import loading_textures as textures

THREE = [dict(side=i, fighters=[dict(character_id=c) for c in members]) for i, members in enumerate(((0, 13, 54), (21, 133, 34)))]


@lru_cache(maxsize=1)
def layers():
    return art.compose(THREE, 65, 'LOADING YOUR FIGHTERS')


@lru_cache(maxsize=1)
def quantised():
    return textures.quantise(layers())


def walk(packet):
    """Split a GIF stream per GIFtag: ('ad', nloop, eop, [(value, register)]), ('image', nloop, eop, bytes),
    ('reglist', (nloop, nreg, regs), eop, qwords)."""
    blocks = []; pos = 0
    while pos < len(packet):
        tag, regs = struct.unpack_from('<2Q', packet, pos); nloop = tag & 0x7FFF; eop = bool(tag >> 15 & 1)
        flg = tag >> 58 & 3; nreg = tag >> 60 or 16; pos += 16
        if flg == 2: blocks.append(('image', nloop, eop, packet[pos:pos+16*nloop])); pos += 16*nloop
        elif flg == 0:
            assert nreg == 1 and regs == probe.AD, 'only A+D packed blocks are used'
            blocks.append(('ad', nloop, eop, [struct.unpack_from('<2Q', packet, pos+16*i) for i in range(nloop)])); pos += 16*nloop
        else:
            assert flg == 1; qwords = (nreg*nloop+1)//2
            blocks.append(('reglist', (nloop, nreg, regs), eop, struct.unpack_from(f'<{2*qwords}Q', packet, pos))); pos += 16*qwords
    assert pos == len(packet)
    return blocks


class RegisterWordTests(unittest.TestCase):
    def test_every_register_word_decodes_to_its_named_fields(self):
        self.assertEqual(protocol.MAGIC.to_bytes(4, 'little'), b'L4KS'); self.assertEqual(protocol.DESCRIPTOR, 4096)
        self.assertEqual(protocol.BUFFERS, (0x06A00000, 0x06A80000)); self.assertEqual(protocol.CAPACITY, 0x80000)
        self.assertEqual((protocol.STANDARD, protocol.ADDITIVE), (0x44, 0x48))
        self.assertEqual(probe.decode_alpha1(protocol.STANDARD), dict(a=0, b=1, c=0, d=1, fix=0))
        self.assertEqual(probe.decode_alpha1(protocol.ADDITIVE), dict(a=0, b=2, c=0, d=1, fix=0))
        self.assertEqual((protocol.SETUP_TEST, protocol.DRAW_TEST), (0x30000, 0x3000D))
        self.assertEqual(probe.decode_test1(protocol.DRAW_TEST), dict(ate=1, atst=6, aref=0, afail=0, date=0, datm=0, zte=1, ztst=1))
        self.assertEqual(probe.decode_test1(protocol.SETUP_TEST), dict(ate=0, atst=0, aref=0, afail=0, date=0, datm=0, zte=1, ztst=1))
        self.assertEqual(protocol.LINEAR_TEX1, 0x60); self.assertEqual(probe.decode_tex1(0x60), dict(lcm=0, mxl=0, mmag=1, mmin=1, mtba=0, l=0, k=0))
        self.assertEqual(protocol.REGION_CLAMP, 0x000006FC007FC00A)
        self.assertEqual(probe.decode_clamp1(protocol.REGION_CLAMP), dict(wms=2, wmt=2, minu=0, maxu=511, minv=0, maxv=447))
        self.assertEqual(protocol.CLAMP_BOTH, 5); self.assertEqual(probe.decode_clamp1(5), dict(wms=1, wmt=1, minu=0, maxu=0, minv=0, maxv=0))
        self.assertEqual(probe.decode_tex0(protocol.BG_TEX0), dict(tbp=0x2D00, tbw=8, psm=0x13, tw=9, th=9, tcc=1, tfx=1, cbp=protocol.BG_CBP, cpsm=0, csm=0, csa=0, cld=1))
        self.assertEqual(probe.decode_tex0(protocol.ATLAS_TEX0), dict(tbp=0x3400, tbw=4, psm=0x13, tw=8, th=5, tcc=1, tfx=0, cbp=protocol.ATLAS_CBP, cpsm=0, csm=0, csa=0, cld=1))
        for k in range(protocol.MAX_SLICES):
            self.assertEqual(probe.decode_tex0(protocol.fg_tex0(k)), dict(tbp=0x3080, tbw=8, psm=0x13, tw=9, th=9, tcc=1, tfx=0, cbp=protocol.SLICE_CBP(k), cpsm=0, csm=0, csa=0, cld=1))
        with self.assertRaises(ValueError): protocol.fg_tex0(14)
        self.assertEqual(protocol.scissor(0, 511, 0, 447), 0x1FF0000 | (447 << 48)); self.assertEqual(protocol.xyoffset(1792, 1824), (1792*16) | ((1824*16) << 32))
        self.assertEqual(protocol.SETUP, probe.SETUP)
        self.assertEqual([r for _, r in protocol.SETUP], [0x40, 0x18, 0x1A, 0x47, 0x42, 0x49, 0x46, 0x45, 0x4A])
        self.assertEqual((protocol.STRIP, protocol.FAN, protocol.LINE_STRIP, protocol.LINE_LIST, protocol.SPRITE, protocol.TSPRITE, protocol.BG_SPRITE),
                         (0x4C, 0x4D, 0x4A, 0x49, 0x46, 0x156, 0x116))
        for prim in (protocol.STRIP, protocol.FAN, protocol.LINE_STRIP, protocol.LINE_LIST, protocol.SPRITE, protocol.TSPRITE): self.assertTrue(prim & 0x40, hex(prim))
        self.assertFalse(protocol.BG_SPRITE & 0x40); self.assertEqual(protocol.TSPRITE & ~0x40, protocol.BG_SPRITE)
        self.assertEqual((protocol.LIGHT_A, protocol.FGB), (ks_a.SIZE, ks_b.SIZE)); self.assertEqual(protocol.RESERVE, 4*16+ks_a.SIZE+ks_b.SIZE+64)
        self.assertEqual((protocol.KS_RETURN, protocol.KS_SCRATCH), (0xF8, (0xA0, 0xF8)))

    def test_vram_banks_stay_inside_the_transient_zone_and_never_overlap(self):
        self.assertEqual([protocol.CLUT_BANK(i) for i in range(16)],
                         [0x3408, 0x340C, 0x3418, 0x341C, 0x3428, 0x342C, 0x3438, 0x343C, 0x3448, 0x344C, 0x3458, 0x345C, 0x3468, 0x346C, 0x3478, 0x347C])
        self.assertEqual((protocol.BG_CBP, protocol.ATLAS_CBP, protocol.SLICE_CBP(0), protocol.SLICE_CBP(13)), (0x3408, 0x340C, 0x3418, 0x347C))
        with self.assertRaises(ValueError): protocol.SLICE_CBP(14)
        prints = protocol.vram_footprints()
        self.assertEqual(dict(prints)['background'], set(range(0x2D00, 0x3080))); self.assertEqual(dict(prints)['foreground'], set(range(0x3080, 0x3400)))
        self.assertEqual(dict(prints)['atlas'], {page+b for page in (0x3400, 0x3420) for b in (0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 20, 21, 22, 23)})
        self.assertEqual(dict(prints)['bg_clut'], {0x3408, 0x3409, 0x340A, 0x340B})
        seen = set()
        for name, blocks in prints:
            self.assertTrue(all(protocol.VRAM_BASE <= b < protocol.VRAM_FLOOR for b in blocks), name)
            self.assertFalse(seen & blocks, f'{name} overlaps another upload'); seen |= blocks
        # the spec's literal banks (0x3420, 0x3424, 0x3428+4k) sit inside the atlas's second page
        atlas = dict(prints)['atlas']
        self.assertTrue(protocol.vram_blocks(probe.PSMCT32, 0x3420, 1, 16, 16) & atlas)
        self.assertTrue(protocol.vram_blocks(probe.PSMCT32, 0x3430, 1, 16, 16) & atlas)
        self.assertEqual(protocol.vram_blocks(probe.PSMT8, 0x3080, 8, 512, 448), set(range(0x3080, 0x3400)))


class PacketTests(unittest.TestCase):
    def test_packet_a_walk(self):
        q = quantised(); packet = protocol.packet_a(q); n = len(q['slices'])
        self.assertEqual(len(packet), protocol.packet_a_size(n)); self.assertEqual(len(packet) % 16, 0); self.assertLess(len(packet), protocol.PACKET_LIMIT)
        blocks = walk(packet)
        kinds = [b[0] for b in blocks]
        self.assertEqual(kinds, ['ad']+['ad', 'image']*(3+2+n)+['ad', 'ad', 'reglist'])
        self.assertEqual([b[2] for b in blocks], [False]*(len(blocks)-1)+[True], 'EOP only on the last tag')
        self.assertEqual([(v, r) for v, r in blocks[0][3]], list(protocol.SETUP))
        uploads = blocks[1:1+2*(5+n)]
        images = [(probe.decode_bitbltbuf(ad[3][0][0]), probe.decode_trxreg(ad[3][2][0]), [r for _, r in ad[3]], img) for ad, img in zip(uploads[::2], uploads[1::2])]
        expected = [(0x2D00, 8, 0x13, 512, 448), (0x3080, 8, 0x13, 512, 448), (0x3400, 4, 0x13, 256, 32), (protocol.BG_CBP, 1, 0, 16, 16),
                    (protocol.ATLAS_CBP, 1, 0, 16, 16)]+[(protocol.SLICE_CBP(k), 1, 0, 16, 16) for k in range(n)]
        for (bb, tr, regs, img), (dbp, dbw, dpsm, w, h) in zip(images, expected, strict=True):
            self.assertEqual((bb['dbp'], bb['dbw'], bb['dpsm'], tr['w'], tr['h']), (dbp, dbw, dpsm, w, h))
            self.assertEqual(regs, [probe.BITBLTBUF, probe.TRXPOS, probe.TRXREG, probe.TRXDIR], 'TRXDIR written last')
            self.assertLessEqual(img[1], 32767); self.assertEqual(len(img[3]), 16*img[1])
        self.assertEqual([img[1] for _, _, _, img in images], [14336, 14336, 512]+[64]*(2+n))
        self.assertEqual(images[0][3][3], q['background'][0].tobytes()); self.assertEqual(images[1][3][3], q['foreground'][0].tobytes())
        self.assertEqual(images[2][3][3], q['atlas'][0].tobytes())
        self.assertEqual(images[3][3][3], textures.clut_swizzle_csm1(q['background'][1])); self.assertEqual(textures.clut_unswizzle_csm1(images[3][3][3]), q['background'][1])
        self.assertEqual(images[4][3][3], textures.clut_swizzle_csm1(q['atlas'][1]))
        for k in range(n): self.assertEqual(textures.clut_unswizzle_csm1(images[5+k][3][3]), q['foreground'][1][k])
        self.assertEqual(blocks[-3][3], [(0, probe.TEXFLUSH)])
        draw = dict((r, v) for v, r in blocks[-2][3])
        self.assertEqual(list(draw), [probe.TEX0_1, probe.TEX1_1, probe.CLAMP_1, probe.PRIM])
        self.assertEqual((draw[probe.TEX0_1], draw[probe.TEX1_1], draw[probe.CLAMP_1], draw[probe.PRIM]), (protocol.BG_TEX0, protocol.NEAREST_TEX1, protocol.REGION_CLAMP, 0x116))
        kind, (nloop, nreg, regs), eop, words = blocks[-1]
        self.assertEqual((nloop, nreg, regs, eop), (1, 5, probe.SPRITE_REGS, True))
        self.assertEqual(words, (probe.Q_ONE_WHITE, 0, probe.xyz2(0, 0), 8192 | (7168 << 16), probe.xyz2(512, 448), 0))
        with self.assertRaises(ValueError): protocol.packet_a(dict(q, foreground=(q['foreground'][0], q['foreground'][1][:-1])))

    def test_packet_b_is_the_foreground_register_state(self):
        packet = protocol.packet_b(); self.assertEqual(len(packet), 96)
        (kind, nloop, eop, writes), = walk(packet)
        self.assertEqual((kind, nloop, eop), ('ad', 5, True))
        self.assertEqual(writes, [(protocol.NEAREST_TEX1, probe.TEX1_1), (5, probe.CLAMP_1), (0x44, probe.ALPHA_1), (0x3000D, probe.TEST_1), (0x156, probe.PRIM)])

    def test_foreground_draw_reference_is_fixed_size_with_degenerate_unused_slices(self):
        slices = layers()['slices']
        rest = protocol.foreground_draw(slices); self.assertEqual(len(rest), protocol.MAX_SLICES*96)
        blocks = walk(rest); self.assertEqual([b[0] for b in blocks], ['ad', 'reglist']*protocol.MAX_SLICES)
        self.assertEqual([b[2] for b in blocks], [False]*(2*protocol.MAX_SLICES-1)+[True])
        for k in range(protocol.MAX_SLICES):
            self.assertEqual(blocks[2*k][3], [(protocol.fg_tex0(k), probe.TEX0_1)])
            words = blocks[2*k+1][3]
            if k < len(slices):
                s = slices[k]
                self.assertEqual(words, (0x3F80000080808080, probe.uv(s['u']*16, s['v']*16), probe.xyz2(s['x'], s['y']),
                                         probe.uv((s['u']+s['w'])*16, (s['v']+s['h'])*16), probe.xyz2(s['x']+s['w'], s['y']+s['h']), 0))
            else: self.assertEqual(words, (probe.Q_ONE_WHITE, 0, probe.xyz2(0, 0), 0, probe.xyz2(0, 0), 0))
        start = walk(protocol.foreground_draw(slices, 0))
        header = slices[0]; words = start[1][3]
        self.assertEqual(words[0] >> 24 & 255, 0); self.assertEqual(words[2], protocol.xyz2(header['x'], header['y']+header['dy']))
        self.assertEqual(protocol.xyz2(-17, -17), ((1792-17)*16) | (((1824-17)*16) << 16)); self.assertEqual(protocol.xyz2(512, 448), probe.xyz2(512, 448))
        with self.assertRaises(ValueError): protocol.xyz2(-1793, 0)


class DescriptorTests(unittest.TestCase):
    def test_layout_offsets_are_pinned_for_the_emitters(self):
        p = protocol
        self.assertEqual((p.FLAGS, p.N_SLICES, p.N_RIBBONS, p.N_TICKS, p.FADE_COLOR, p.FADE_FRAMES), (4, 8, 12, 16, 20, 24))
        self.assertEqual((p.SLICES, p.SLICE_STRIDE, p.RIBBONS, p.RIBBON_STRIDE, p.RIBBON_COLORS), (32, 48, 704, 144, 72))
        self.assertEqual((p.SPARK_REGIONS, p.SPARK_ENTRIES, p.SPARK_STRIDE, p.ORBS, p.ORB_STRIDE), (1568, 1600, 8, 2624, 40))
        self.assertEqual((p.SEAM, p.RING, p.FLASH, p.BOLTS, p.BOLT_STRIDE, p.CHEVRONS), (2704, 2736, 2768, 2800, 40, 2880))
        self.assertEqual((p.TICKS, p.TICK_STRIDE, p.GAUGE, p.GAUGE_DIGITS, p.DIGIT_STRIDE, p.GAUGE_STRIDE), (2928, 48, 3504, 3572, 24, 3680-3504))
        self.assertEqual((p.SHEENS, p.DOTS, p.NOISE, p.NOISE_BYTES, p.LAYOUT_END), (3680, 3712, 3744, 128, 3872))
        self.assertLessEqual(p.LAYOUT_END, p.DESCRIPTOR)
        self.assertEqual(len(p.SLICE_WORDS)*4, 48); self.assertEqual(len(p.RIBBON_WORDS)*4, p.RIBBON_COLORS); self.assertLessEqual(p.RIBBON_COLORS+17*4, p.RIBBON_STRIDE)
        self.assertEqual(len(p.TICK_WORDS)*4, p.TICK_STRIDE); self.assertLessEqual(len(p.ORB_WORDS)*4, p.ORB_STRIDE); self.assertLessEqual(len(p.BOLT_WORDS)*4, p.BOLT_STRIDE)
        self.assertEqual(p.GAUGE_DIGITS, p.GAUGE+4*len(p.GAUGE_WORDS))
        self.assertEqual(p.packed_color((1, 2, 3)), 0x80030201); self.assertEqual(p.unpack_color(0x80030201), (1, 2, 3))
        with self.assertRaises(ValueError): p.unpack_color(0x00030201)
        self.assertEqual(len(p.noise_table()), 128); self.assertEqual(p.gauge_fill(0), (0, 32)); self.assertEqual(p.gauge_fill(100), (255, 128)); self.assertEqual(p.gauge_fill(65), (166, 94))

    def test_encode_decode_round_trip_of_a_real_plan(self):
        L = layers(); plan = L['lights']; digits = art.gauge_digits(65)
        data = protocol.encode_lights(L, 65, digits)
        self.assertEqual(len(data), protocol.DESCRIPTOR); self.assertEqual(data[:4], b'L4KS')
        self.assertEqual(data, protocol.encode_lights(plan, 65, digits, slices=L['slices']))
        d = protocol.decode_lights(data)
        self.assertEqual(d['flags'], 127)
        self.assertEqual(len(d['slices']), len(L['slices']))
        for k, (got, s) in enumerate(zip(d['slices'], L['slices'])):
            self.assertEqual({n: got[n] for n in ('x', 'y', 'w', 'h', 'u', 'v', 'start', 'dx', 'dy')}, {n: s[n] for n in ('x', 'y', 'w', 'h', 'u', 'v', 'start', 'dx', 'dy')})
            self.assertEqual(got['cbp'], protocol.SLICE_CBP(k)); self.assertEqual(got['tex0_lo'] | (got['tex0_hi'] << 32), protocol.fg_tex0(k))
        self.assertEqual(d['fade'], dict(color=(0, 0, 4), frames=24))
        self.assertEqual(len(d['ribbons']), len(plan['ribbons']))
        for got, rb in zip(d['ribbons'], plan['ribbons']):
            self.assertEqual(got, {n: rb[n] for n in got})
        self.assertEqual(d['sparks']['regions'], plan['sparks']['regions'])
        self.assertEqual(d['sparks']['entries'], plan['sparks']['entries'])
        for got, orb in zip(d['orbs'], plan['orbs']): self.assertEqual(got, {n: orb[n] for n in got})
        for got, bolt in zip(d['bolts'], plan['bolts']): self.assertEqual(got, {n: bolt[n] for n in got})
        for name in ('seam', 'ring', 'flash'): self.assertEqual(d[name], {n: plan[name][n] for n in d[name]})
        self.assertEqual(d['chevrons'], {n: protocol._flat_chevrons(plan['chevrons'])[n] for n in d['chevrons']})
        self.assertEqual(len(d['ticks']), len(plan['ticks']))
        for got, tick in zip(d['ticks'], plan['ticks']): self.assertEqual(got, {n: protocol._flat_tick(tick)[n] for n in got})
        g, G = d['gauge'], plan['gauge']
        self.assertEqual({n: g[n] for n in ('x0', 'x1', 'y0', 'y1', 'tip')}, {n: G[n] for n in ('x0', 'x1', 'y0', 'y1', 'tip')})
        self.assertEqual((g['color0'], g['color1'], g['color2']), tuple(G['colors']))
        self.assertEqual((g['orb_cx'], g['orb_cy'], g['orb_rx'], g['orb_ry'], g['orb_color']), (G['orb']['cx'], G['orb']['cy'], G['orb']['rx'], G['orb']['ry'], G['orb']['color']))
        self.assertEqual((g['fill'], g['progress'], g['orb_alpha'], g['n_digits']), (166, 65, 94, 3)); self.assertEqual(g['digits'], digits)
        self.assertEqual(d['sheens'], plan['sheens']); self.assertEqual(d['dots'], dict(plan['dots'], count=3)); self.assertEqual(d['noise'], protocol.noise_table())
        # progress only changes the gauge section
        other = protocol.encode_lights(L, 100, art.gauge_digits(100))
        self.assertEqual(other[:protocol.GAUGE], data[:protocol.GAUGE]); self.assertEqual(other[protocol.SHEENS:], data[protocol.SHEENS:])
        o = protocol.decode_lights(other)['gauge']; self.assertEqual((o['fill'], o['progress'], o['orb_alpha'], o['n_digits']), (255, 100, 128, 4))
        # the ffa plan (4 ribbons, no VS) and an empty plan
        ffa = art.compose(THREE, 10, 'X', mode='ffa', humans=2); e = protocol.decode_lights(protocol.encode_lights(ffa, 10, art.gauge_digits(10)))
        self.assertEqual((len(e['ribbons']), len(e['slices']), e['gauge']['n_digits']), (4, len(ffa['slices']), 3))
        self.assertEqual(protocol.encode_lights(dict(lights=None)), b'')

    def test_descriptor_validation(self):
        L = layers(); plan = L['lights']
        with self.assertRaises(ValueError): protocol.encode_lights(plan, 0, (), slices=L['slices']*2)
        with self.assertRaises(ValueError): protocol.encode_lights(plan, 0, (), slices=[dict(L['slices'][0], w=600)])
        bad = dict(plan, bolts=[dict(plan['bolts'][0], period=100), plan['bolts'][1]])
        with self.assertRaises(ValueError): protocol.encode_lights(bad, 0, (), slices=L['slices'])
        bad = dict(plan, ribbons=plan['ribbons']*2)
        with self.assertRaises(ValueError): protocol.encode_lights(bad, 0, (), slices=L['slices'])
        bad = dict(plan, sparks=dict(plan['sparks'], entries=[dict(plan['sparks']['entries'][0], ribbon=9)]))
        with self.assertRaises(ValueError): protocol.encode_lights(bad, 0, (), slices=L['slices'])
        with self.assertRaises(ValueError): protocol.decode_lights(b'XXXX'+protocol.encode_lights(L, 0, ())[4:])
        with self.assertRaises(ValueError): protocol.decode_lights(bytes(16))


if __name__ == '__main__': unittest.main()
