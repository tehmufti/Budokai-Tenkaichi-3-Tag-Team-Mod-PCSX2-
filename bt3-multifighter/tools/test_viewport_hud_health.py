"""Split-screen native HP panels: tiers, pips, trail and resets pinned against executed native 21C5B0/21CA60."""
# Native execution tests require the developer's extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
_test_root = _TestPath(__file__).resolve().parents[1]
if not _test_elf_path(_test_root).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tests')
if not all((_test_root/'tools'/name).is_file() for name in
           ('test_viewport_hud.py','test_viewport_hud_layers.py')):
    raise _TestUnit.SkipTest('Developer HUD fixtures and execution helpers are required')

import struct
import unittest
from prototype import ROOT, elf_reader
from native_map import elf_path
import viewport_hud as hud
import viewport_hud_art as art
import test_viewport_hud as old
import test_viewport_hud_art as native
import test_viewport_hud_layers as layers

PHYSICAL = 4
ACTOR = old.feed_test.ACTORS[PHYSICAL]
RECORD = art.METERS+24*PHYSICAL


def record(c, p): return struct.unpack('<I12H', c.read(p, 28))


class FpuCpu(layers.NativeCpu):
    """Single-precision subset used by native 21CA60's fading-pip check (mtc1/lwc1/c.cond.s/bc1x/mul/sub/cvt/mfc1)."""
    def extra_instruction(self, ins, pc):
        op, rs, rt, rd, fn = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31, ins & 63
        f = getattr(self, 'f', None)
        if f is None: f = self.f = [0]*32; self.cond = False
        value = lambda k: struct.unpack('<f', struct.pack('<I', f[k] & 0xFFFFFFFF))[0]
        bits = lambda v: struct.unpack('<I', struct.pack('<f', v))[0]
        if op == 49:
            off = ins & 65535; off = off-65536 if off >= 32768 else off; f[rt] = self.u(self.r[rs]+off); return None
        if op == 17 and rs == 4: f[rd] = self.r[rt] & 0xFFFFFFFF; return None
        if op == 17 and rs == 0: self.r[rt] = f[rd]; return None
        if op == 17 and rs == 8:
            if bool(self.cond) == bool(rt & 1):
                off = ins & 65535; off = off-65536 if off >= 32768 else off; return pc+4+4*off
            return None
        if op == 17 and rs == 16:
            ft, fs, fd = rt, rd, (ins >> 6) & 31
            if fn == 0x32: self.cond = value(fs) == value(ft); return None
            if fn == 0x36: self.cond = value(fs) <= value(ft); return None
            if fn == 2: f[fd] = bits(value(fs)*value(ft)); return None
            if fn == 1: f[fd] = bits(value(fs)-value(ft)); return None
            if fn == 0x24: f[fd] = int(value(fs)) & 0xFFFFFFFF; return None
        return super().extra_instruction(ins, pc)


def native_state(t, h):
    """Executed native 21C5B0 + 21CA60 for trail t / HP h: what each HP record shows."""
    c, manager, table, actor = layers.source_machine(); c.__class__ = FpuCpu
    rd = elf_reader(elf_path(ROOT))[2]
    c.write(0x21CA60, rd(0x21CA60, 0x1A8))
    c.w(manager+0x28, t); c.w(manager+0x30, h); layers.run(c, 0x21C5B0); layers.run(c, 0x21CA60)
    shown = lambda off: not record(c, table+off)[0] & 1
    out = dict(under=record(c, table+0x54)[2] if shown(0x54) else None, mask=shown(0x70),
               lost=record(c, table+0x38)[3] if shown(0x1C) else None,
               trail=record(c, table+0x8C)[3] if shown(0xA8) else None,
               fill=(record(c, table+0xE0)[2], record(c, table+0xC4)[3]),
               pips=sum(shown(252+28*k) for k in range(6)))
    if not out['fill'][1]: out['fill'] = None
    if out['lost'] is not None and out['lost'] >= 160: out['lost'] = None
    return out


def identity(c, actor=ACTOR):
    value = c.u(actor+0x9A4) & 0xFFFF; index = c.u(actor+12)
    if index < 12:
        model = c.u(hud.core.MODELS+4*index)
        if 0x100000 <= model <= 0x08000000-0x10 and not model & 3: value |= (c.u(model+12) & 0xFFFF) << 16
    return value


def prime(c, t, h, clock=40):
    """This fighter's own settled record: trail t, HP h, drawn by the previous pass at `clock`."""
    c.w(ACTOR+0x9E4, h); c.w(hud.feed.CONTROL+12, clock)
    c.write(RECORD, struct.pack('<6I', ACTOR, ACTOR+0x9E4, t, clock, 1, h))
    c.write(art.IDENTITY+8*PHYSICAL, struct.pack('<2I', identity(c), 0)); c.write(art.PASSES, struct.pack('<2I', clock, clock-1))


def draw(c): c.sprites = []; old.draw(c)


def own_bars(c):
    """(palette, u0, u1) of the own panel's atlas-8 HP strips in draw order."""
    return [(s[2], s[3], s[5]) for s in c.sprites if s[3] < s[5] and s[1] == 8 and s[4] == 0 and s[6] == 16]


def expected_bars(n):
    """Native records -> the strips the split panel draws, in its draw order."""
    out = []
    if n['under'] is not None:
        out.append((n['under'], 0, 160))
        if n['lost'] is not None: out.append((2, n['lost'], 160))
        out.append((0, 0, 160))
    if n['trail']: out.append((2, 0, n['trail']))
    if n['fill']: out.append((n['fill'][0], 0, n['fill'][1]))
    return out


CASES = sorted({(h, h) for h in [1, 100, 187, 188, 5000, 9999, 10000, 10001, 10188, 15000, 19999, 20000, 20001]
                + list(range(25000, 130001, 5000))} |
               {(45000, 38000), (45000, 25000), (35000, 25000), (40000, 30000), (40001, 40000), (70000, 58000),
                (62650, 33000), (5000, 1), (10000, 100), (20000, 10000), (12000, 9000), (80280, 80000),
                (75000, 74999), (100000, 61000), (30500, 30100), (9000, 200)})


class NativeHealthTests(unittest.TestCase):
    def test_blue_layer_matches_this_disc_native_executable(self):
        rd = elf_reader(elf_path(ROOT))[2]
        for at in (0x21C7E0, 0x21C940):
            word = struct.unpack('<I', rd(at, 4))[0]
            self.assertEqual(word >> 26, 10, hex(at)); self.assertEqual(word & 0xFFFF, art.BLUE_LAYER, hex(at))

    def test_tier_colours_trail_fill_and_pips_match_native_for_every_layer(self):
        # 1..13 bars, settled and mid-trail (also across one or several layers): palette per tier (BT3 blue from
        # the 8th bar, BT4 from the 5th), next-layer underlay and mask, lost-part red, trail, fill and pip count.
        for t, h in CASES:
            n = native_state(t, h); c = native.machine(); prime(c, t, h); draw(c)
            self.assertEqual(own_bars(c), expected_bars(n), (t, h, n))
            pips = [s[2] for s in c.sprites if s[3] < s[5] and s[1] == 8 and s[3:7] == (0, 16, 16, 32)]
            self.assertEqual(pips, list(art.PIP_PALETTES[:n['pips']]), (t, h))
            self.assertEqual(c.u(RECORD+8), t, (t, h))

    def test_pip_palettes_are_this_disc_native_pip_records(self):
        # BT3 shows every pip green; BT4's layout colours pip k like HP layer k.
        c, manager, table, actor = layers.source_machine()
        self.assertEqual(tuple(record(c, table+252+28*k)[2] for k in range(6)), art.PIP_PALETTES)
        self.assertEqual(tuple(record(c, table+252+28*k)[1] for k in range(6)), (8,)*6)

    def test_fill_palette_per_tier(self):
        blue = art.BLUE_LAYER
        for bars in range(1, 14):
            c = native.machine(); prime(c, bars*10000, bars*10000); draw(c)
            layer = bars-1
            want = 5 if layer >= blue else 1 if layer >= 2 else 4 if layer == 1 else 3
            self.assertEqual(own_bars(c)[-1], (want, 0, 160), bars)

    def test_target_switch_or_swap_never_inherits_a_stale_trail(self):
        c = native.machine(); c.w(hud.core.TABLE+4*4, 3)
        for tick in range(0, 20): c.w(hud.feed.CONTROL+12, tick); draw(c)
        target = old.feed_test.ACTORS[3]; at = art.METERS+24*3
        self.assertEqual(c.u(at+8), c.u(target+0x9E4))
        # Look away (the target panel shows fighter 2), the old target is hurt meanwhile, then switch back.
        c.w(hud.core.TABLE+4*4, 2)
        for tick in range(20, 26): c.w(hud.feed.CONTROL+12, tick); draw(c)
        c.w(target+0x9E4, 5000); c.w(hud.core.TABLE+4*4, 3); c.w(hud.feed.CONTROL+12, 26); draw(c)
        self.assertEqual(c.u(at+8), 5000)
        self.assertFalse([s for s in c.sprites if s[3] > s[5] and s[1] == 8 and s[2] == 2])
        # A fighter the previous pass drew keeps its live trail when it becomes this view's target.
        c.w(target+0x9E4, 4000); c.w(hud.feed.CONTROL+12, 27); draw(c)
        self.assertGreater(c.u(at+8), 4000)
        # A swap: this view watches fighter 0 for a while, then fighter 4 while fighter 0 is hurt, then 0 again.
        other = old.feed_test.ACTORS[0]; c.w(hud.camera.SUCCESSOR_CONTROL+8, 0)
        for tick in range(28, 32): c.w(hud.feed.CONTROL+12, tick); draw(c)
        c.w(hud.camera.SUCCESSOR_CONTROL+8, 4)
        for tick in range(32, 36): c.w(hud.feed.CONTROL+12, tick); draw(c)
        c.w(other+0x9E4, 3000); c.w(hud.camera.SUCCESSOR_CONTROL+8, 0); c.w(hud.feed.CONTROL+12, 36); draw(c)
        self.assertEqual(c.u(art.METERS+8), 3000)
        self.assertFalse([s for s in c.sprites if s[3] < s[5] and s[1] == 8 and s[2] == 2])

    def test_short_hud_absence_keeps_live_trails_long_absence_and_clock_rewind_reset(self):
        c = native.machine()
        for tick in range(0, 20): c.w(hud.feed.CONTROL+12, tick); draw(c)
        c.w(ACTOR+0x9E4, 34000); c.w(hud.feed.CONTROL+12, 20); draw(c); trail = c.u(RECORD+8)
        self.assertGreater(trail, 34000)
        # A short gap in HUD passes (a brief single view): the trail carries on afterwards.
        c.w(hud.feed.CONTROL+12, 20+art.SETTLE-2); draw(c); self.assertGreater(c.u(RECORD+8), 34000)
        self.assertLess(c.u(RECORD+8), trail)
        # A gap longer than the trail (co-op fusion's merged view, an ultimate): that trail has run out, and HP lost
        # meanwhile (a defusion's split) is shown as it is, with the same fighter and form as before.
        c.w(ACTOR+0x9E4, 21000); c.w(hud.feed.CONTROL+12, 20+art.SETTLE-2+art.SETTLE+1); draw(c)
        self.assertEqual(c.u(RECORD+8), 21000)
        self.assertFalse([s for s in c.sprites if s[3] < s[5] and s[1] == 8 and s[2] == 2])
        # A rewound clock (a reloaded rematch image without its records) starts over at the current HP.
        for tick in range(60, 80): c.w(hud.feed.CONTROL+12, tick); draw(c)
        c.w(ACTOR+0x9E4, 15000); c.w(hud.feed.CONTROL+12, 80); draw(c); self.assertGreater(c.u(RECORD+8), 15000)
        c.w(hud.feed.CONTROL+12, 5); draw(c); self.assertEqual(c.u(RECORD+8), 15000)

    def test_form_fusion_defusion_body_and_revival_changes_show_no_damage(self):
        for change in ('row_character', 'model_character', 'form', 'revival'):
            c = native.machine()
            c.w(ACTOR+0x9E4, 80000); c.w(ACTOR+0x9E4+4, 80000)
            for tick in range(0, 20): c.w(hud.feed.CONTROL+12, tick); draw(c)
            if change == 'row_character': c.w(ACTOR+0x9A4, c.u(ACTOR+0x9A4)+1); c.w(ACTOR+0x9E4, 27000)
            elif change == 'model_character':
                model = c.u(hud.core.MODELS+4*c.u(ACTOR+12)); c.w(model+12, c.u(model+12)+1); c.w(ACTOR+0x9E4, 27000)
            elif change == 'form':
                c.w(ACTOR+0x994, 1); c.w(ACTOR+0x9E4+164, 27000); c.w(ACTOR+0x9E4+164+4, 40000)
            else:
                c.w(ACTOR+0x9E4, 0); c.w(hud.feed.CONTROL+12, 20); draw(c); c.w(ACTOR+0x9E4, 27000)
            c.w(hud.feed.CONTROL+12, 21); draw(c)
            self.assertFalse([s for s in c.sprites if s[3] < s[5] and s[1] == 8 and s[2] == 2], change)
            row = ACTOR+0x9E4+164*c.u(ACTOR+0x994)
            self.assertEqual(c.u(RECORD+8), c.u(row), change)
            # The new form's HP settling a few ticks later is not damage either.
            c.w(row, c.u(row)-2000); c.w(hud.feed.CONTROL+12, 21+art.SETTLE-1); draw(c)
            self.assertEqual(c.u(RECORD+8), c.u(row), change)
            # Real damage afterwards trails again.
            c.w(row, c.u(row)-3000); c.w(hud.feed.CONTROL+12, 21+art.SETTLE+1); draw(c)
            self.assertGreater(c.u(RECORD+8), c.u(row), change)
            self.assertTrue([s for s in c.sprites if s[3] < s[5] and s[1] == 8 and s[2] == 2], change)

    def test_heal_and_rematch_refill_never_trail(self):
        c = native.machine()
        for tick in range(0, 20): c.w(hud.feed.CONTROL+12, tick); draw(c)
        c.w(ACTOR+0x9E4, 21000)
        for tick in range(20, 40): c.w(hud.feed.CONTROL+12, tick); draw(c)
        self.assertEqual(c.u(RECORD+8), 21000)
        for value, tick in ((26000, 40), (50000, 41)):
            c.w(ACTOR+0x9E4, value); c.w(hud.feed.CONTROL+12, tick); draw(c)
            self.assertEqual(c.u(RECORD+8), value)
            self.assertFalse([s for s in c.sprites if s[3] < s[5] and s[1] == 8 and s[2] == 2])

    def test_records_stay_inside_the_viewport_hud_reservation(self):
        self.assertLessEqual(art.PASSES+8, hud.CONTROL)
        self.assertGreaterEqual(art.IDENTITY, art.METERS+art.METER_BYTES)
        self.assertLess(len(art.panel_code()), art.COMPACT-art.NATIVE_PANEL)
        self.assertEqual(art.SETTLE, round(.5*art.ACTOR_HZ))

    def test_previous_hp_section_is_kept_byte_for_byte_for_prepared_upgrades(self):
        c = old.captured_machine(split=True); c.write(hud.feed.WORLD, hud.feed.world_code())
        for b in hud.build_memory(c.buffer)['blocks']: c.write(b['address'], bytes.fromhex(b['data_hex']))
        for p, d in hud.pieces(hud.feed.DRAW): c.write(p, bytes(len(d)))
        for p, d in hud.pieces(hud.feed.DRAW, native_hp=False): c.write(p, d)
        c.write(art.METERS, bytes(range(24))); before = c.read(art.METERS, art.METER_BYTES)
        for b in hud.build_memory(c.buffer)['blocks']: c.write(b['address'], bytes.fromhex(b['data_hex']))
        self.assertEqual(c.read(art.METERS, art.METER_BYTES), before)
        self.assertEqual(c.read(art.NATIVE_PANEL, len(art.panel_code())), art.panel_code())
        self.assertEqual(hud.build_memory(c.buffer)['blocks'], [])


if __name__ == '__main__': unittest.main()
