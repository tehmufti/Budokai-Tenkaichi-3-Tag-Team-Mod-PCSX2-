"""Fighter Gauntlet split screen (p94): a wave intro is one full-screen view, so the per-view split HUD panels stay off.

Live (BT3 USA, 2 humans, hidden rig): the wave 2 intro showed four small split-view panels across the top of the
full-screen shot (p87 saw a pair in mid-screen with three views): viewport_hud.ACTIVE did not know SELECT presented
one view. HUDGATE answers 0 for exactly SELECT's condition and otherwise runs ACTIVE unchanged.
"""
import struct
import unittest

import gauntlet_runtime as g
import viewport_hud as hud
from test_ai_shadow import Mips


class SnapshotCpu(Mips):
    """Blank 128 MiB RAM (no capture needed)."""
    instruction_budget = 30000

    def read(self, address, length):
        return bytes(self.memory.get(p, 0) for p in range(address, address+length))


def machine():
    c = SnapshotCpu({'segments': []})
    c.r[28] = 0x304270
    head = hud.active()[:8]
    c.write(g.HUDGATE, g.hud_gate_code(head))
    # ACTIVE: its own prologue, then a stand-in body that undoes the frame and answers 0x55.
    stub = struct.pack('<4I', 0x27BD0240, 0x24020055, 0x03E00008, 0)      # addiu sp,0x240; li v0,0x55; jr ra; nop
    c.write(hud.ACTIVE, g.jump(g.HUDGATE) + stub)
    manager = 0x01870400
    c.w(c.r[28]-22364, manager); c.w(c.r[28]-22180, 0x01874B80)
    c.w(g.CONTROL, g.MAGIC); c.w(g.CONTROL+g.C['manager'], manager)
    return c


def call(c):
    for r in range(8, 16):
        c.r[r] = 0x1000+r
    c.r[2] = 0x1002; c.r[29] = 0x01F00000; c.r[31] = 0xFEED0000
    c.run(hud.ACTIVE)
    return c.r[2]


class GauntletHudGateTests(unittest.TestCase):
    def test_a_wave_intro_turns_the_split_panels_off_and_preserves_registers(self):
        c = machine(); c.w(g.CONTROL+g.C['intro_camera'], 3)
        self.assertEqual(call(c), 0)
        self.assertEqual([c.r[r] for r in range(8, 16)], [0x1000+r for r in range(8, 16)])
        self.assertEqual(c.r[29], 0x01F00000)

    def test_otherwise_active_runs_with_its_own_prologue(self):
        for case in ('no_intro', 'no_camera', 'other_manager', 'not_installed'):
            c = machine(); c.w(g.CONTROL+g.C['intro_camera'], 0 if case == 'no_intro' else 3)
            if case == 'no_camera': c.w(c.r[28]-22180, 0)
            if case == 'other_manager': c.w(g.CONTROL+g.C['manager'], 0x01990000)
            if case == 'not_installed': c.w(g.CONTROL, 0)
            self.assertEqual(call(c), 0x55, case)
            self.assertEqual([c.r[r] for r in range(8, 16)], [0x1000+r for r in range(8, 16)], case)
            self.assertEqual(c.r[29], 0x01F00000, case)
            self.assertEqual(c.u(0x01F00000-0x240), 0x1002, case)   # ACTIVE's own `sd v0,0(sp)` ran

    def test_install_only_over_the_known_prologue(self):
        ram = bytearray(0x08000000)
        self.assertEqual(g.hud_gate_blocks(ram), [])
        struct.pack_into('<I', ram, hud.CONTROL, hud.MAGIC)
        ram[hud.ACTIVE:hud.ACTIVE+8] = hud.active()[:8]
        blocks = dict(g.hud_gate_blocks(ram))
        self.assertEqual(blocks[hud.ACTIVE], g.jump(g.HUDGATE))
        for at, data in blocks.items():
            ram[at:at+len(data)] = data
        self.assertEqual(dict(g.hud_gate_blocks(ram)), blocks)      # idempotent
        ram[hud.ACTIVE] ^= 1
        with self.assertRaises(ValueError):
            g.hud_gate_blocks(ram)


if __name__ == '__main__':
    unittest.main()
