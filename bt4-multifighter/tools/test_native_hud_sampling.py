"""Execute the HUD clamp wrapper and check prepared-kit ownership/upgrade paths."""
import struct
import unittest
from unittest.mock import patch

from native_map import A, elf_path
from prototype import ROOT, elf_reader
from test_ai_shadow import Mips
import native_hud_sampling as sample
import native_hud_style as style


class Cpu(Mips):
    def extra_instruction(self, ins, pc):
        op, rs, rt, rd = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
        fn, shift = ins & 63, (ins >> 6) & 31
        if op == 33:
            offset = ins & 65535
            if offset >= 32768:
                offset -= 65536
            self.r[rt] = int.from_bytes(self.read(self.r[rs]+offset, 2), 'little', signed=True) & 0xFFFFFFFF
            return
        if op == 0 and fn in (0x38, 0x3C):
            self.r[rd] = (self.r[rt] << (shift + (32 if fn == 0x3C else 0))) & 0xFFFFFFFFFFFFFFFF
            return
        return super().extra_instruction(ins, pc)


def machine(uv=(0, 32, 0, 16), *, context=0, bundle=True, texture=24, hidden=False):
    c = Cpu({'segments': [dict(address=sample.BASE, data_hex=sample.payload().hex())]})
    c.r[4:9] = [0x1000000, 0x1100000 if bundle else 0x1110000, context, 0x2A00, 0x2C80]
    c.r[16:19] = [0x1234567800000000+i for i in range(3)]
    c.w(sample.HUD_MANAGER, 0x1200000); c.w(0x1200000, 0x1100000)
    c.write(c.r[4], struct.pack('<I10h4B', int(hidden), texture, 0, -1, 31, 0, 16,
                              *uv, 128, 128, 128, 128))
    c.packets, c.events, c.native = [], [], []

    def begin(m):
        m.r[2] = 0x1300000

    def end(m):
        packet = m.read(0x1300000, m.r[4]-0x1300000)
        m.packets.append(packet); m.events.append(('packet', packet))
        # The game is allowed to clobber all caller-saved argument registers.
        for i in range(2, 16):
            m.r[i] = 0xDEAD0000+i

    def normal(m):
        m.native.append(m.r[4:9].copy()); m.events.append(('native', m.read(m.r[4], 28)))
        m.r[2:4] = [0x9999, 0x8888]

    c.callbacks = {A(0x100878): begin, A(0x100890): end, sample.TRAMP: normal}
    return c


class Rendering(unittest.TestCase):
    def test_native_geometry_filtering_and_arguments_are_unchanged_in_both_contexts(self):
        for context in (0, 1, 3, 256):
            for uv in ((0, 32, 0, 16), (32, 0, 16, 0), (64, 80, 16, 32)):
                with self.subTest(context=context, uv=uv):
                    c = machine(uv, context=context)
                    before = c.r.copy(); record = c.read(c.r[4], 28)
                    c.run(sample.BASE)
                    self.assertEqual(c.native, [before[4:9]])
                    self.assertEqual(c.read(before[4], 28), record)
                    self.assertEqual(c.r[16:19], before[16:19])
                    self.assertEqual(c.r[29], before[29])
                    self.assertEqual(c.r[2:4], [0x9999, 0x8888])
                    self.assertEqual([e[0] for e in c.events], ['packet', 'native', 'packet'])
                    lo_u, hi_u = sorted(uv[:2]); lo_v, hi_v = sorted(uv[2:])
                    clamp = 10 | lo_u << 4 | (hi_u-1) << 14 | lo_v << 24 | (hi_v-1) << 34
                    tag, regs, value, target = struct.unpack('<4Q', c.packets[0])
                    self.assertEqual((tag, regs), (0x1000000000008001, 14))
                    self.assertEqual((value, target), (clamp, 8+bool(context & 255)))
                    # Only CLAMP is written. TEX1/filtering, UV/XY, alpha and
                    # primitives remain native; no region clamp leaks afterward.
                    self.assertEqual(struct.unpack('<4Q', c.packets[1]), (tag, regs, 0, target))

    def test_non_hud_untextured_hidden_and_empty_or_invalid_cells_bypass_sampling(self):
        cases = [dict(bundle=False), dict(texture=-1), dict(hidden=True), dict(uv=(0, 0, 0, 16)),
                 dict(uv=(0, 32, 0, 0)), dict(uv=(-1, 32, 0, 16)), dict(uv=(0, 1025, 0, 16))]
        for options in cases:
            with self.subTest(options=options):
                c = machine(**options); args = c.r[4:9].copy(); c.run(sample.BASE)
                self.assertEqual(c.native, [args]); self.assertEqual(c.packets, [])

    def test_unavailable_battle_manager_keeps_menu_draw_native(self):
        for manager in (0, 0x12345, 0x1200001, 0x8000000):
            c = machine(); c.w(sample.HUD_MANAGER, manager); c.run(sample.BASE)
            self.assertEqual(len(c.native), 1); self.assertEqual(c.packets, [])

    def test_wrapper_page_is_inside_explicit_style_reservation(self):
        self.assertEqual(sample.BASE, style.SAMPLING)
        self.assertLessEqual(sample.END, style.SINK_BUFFER)
        self.assertEqual(len(sample.payload()), sample.SIZE)

    @unittest.skipUnless(elf_path(ROOT).is_file(), 'the disc executable is required')
    def test_native_helpers_fit_before_wrapper_page(self):
        self.assertLessEqual(style.HELPERS + len(style.helpers_code()), sample.BASE)

    @unittest.skipUnless(elf_path(ROOT).is_file(), 'the disc executable is required')
    def test_selected_disc_native_prologue_matches_the_guard(self):
        self.assertEqual(elf_reader(elf_path(ROOT))[2](sample.HOOK, 8), sample.ORIGINAL)


def apply(ram, blocks):
    for b in blocks:
        p = b['address']; d = bytes.fromhex(b['data_hex']); old = bytes.fromhex(b['expected_hex'])
        assert bytes(ram[p:p+len(old)]) == old
        ram[p:p+len(d)] = d


class Installation(unittest.TestCase):
    def setUp(self):
        self.ram = bytearray(0x8000000)
        self.ram[sample.HOOK:sample.HOOK+8] = sample.ORIGINAL

    def legacy(self):
        self.ram[style.CONTROL:style.CONTROL+0x100] = style.control_block(style=31)
        struct.pack_into('<3I', self.ram, style.SITES, 1, 0x100000, 0x12345678)

    def test_fresh_install_is_idempotent_and_classic_view_restores_native_entry(self):
        kit = [(style.CONTROL, style.control_block())]
        with patch.object(style, 'pieces', return_value=(kit, {'art': []})), \
                patch.object(style, 'available_patches', return_value=[]):
            first = style.build_memory(self.ram)
        apply(self.ram, first['blocks'])
        self.assertEqual(bytes(self.ram[sample.HOOK:sample.HOOK+8]), sample.redirect())
        self.assertEqual(bytes(style.classic_view(self.ram)[sample.HOOK:sample.HOOK+8]), sample.ORIGINAL)
        self.assertEqual(style.build_memory(self.ram)['blocks'], [])

    def test_legacy_upgrade_preserves_settings_and_existing_sites(self):
        self.legacy(); control = bytes(self.ram[style.CONTROL:style.CONTROL+0x100])
        first = style.build_memory(self.ram); apply(self.ram, first['blocks'])
        self.assertEqual(bytes(self.ram[style.CONTROL:style.CONTROL+0x100]), control)
        self.assertEqual(style.installed_sites(self.ram)[0], (0x100000, 0x12345678))
        self.assertEqual(len(style.installed_sites(self.ram)), 3)
        self.assertEqual(style.build_memory(self.ram)['blocks'], [])

    def test_exact_existing_hook_can_acquire_missing_restoration_records(self):
        self.legacy()
        self.ram[sample.BASE:sample.END] = sample.payload()
        self.ram[sample.HOOK:sample.HOOK+8] = sample.redirect()
        first = style.build_memory(self.ram)
        self.assertEqual([b['address'] for b in first['blocks']], [style.SITES])
        apply(self.ram, first['blocks'])
        self.assertEqual(bytes(style.classic_view(self.ram)[sample.HOOK:sample.HOOK+8]), sample.ORIGINAL)

    def test_unknown_hook_or_partial_page_is_not_overwritten(self):
        self.legacy()
        self.ram[sample.HOOK] ^= 1
        first = style.build_memory(self.ram)
        self.assertEqual(first['blocks'], []); self.assertIn('entry changed', first['sampling'])
        self.ram[sample.HOOK:sample.HOOK+8] = sample.ORIGINAL
        self.ram[sample.BASE] = 1
        first = style.build_memory(self.ram)
        self.assertEqual(first['blocks'], []); self.assertIn('occupied', first['sampling'])
        self.ram[sample.BASE:sample.END] = sample.payload()
        self.ram[sample.HOOK:sample.HOOK+8] = sample.redirect()
        self.ram[sample.BASE+12] ^= 1
        self.assertEqual(style.build_memory(self.ram)['blocks'], [])

    def test_sampling_requires_reservation_ownership(self):
        self.assertEqual(sample.plan(self.ram)['pieces'], [])
        self.assertEqual(sample.plan(bytes(16), reservation_owned=True)['pieces'], [])


if __name__ == '__main__':
    unittest.main()
