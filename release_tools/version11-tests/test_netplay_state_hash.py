"""netplay_state_hash: the emitted probe, run in guest_soak's MIPS interpreter over a synthetic EE image, must
equal the Python reference for both profiles, for captured and native fighter lists, and restore every register.
A real prepared match can be added with TAGTEAM_NETPLAY_FIXTURE (a 17-playable-team.p2s or a 128 MiB .bin)."""
import support
import ast
import os
import random
import struct
import unittest

import guest_soak as soak
import netplay_state_hash as nh
import fresh_team_combat as core
from native_map import A


class Cpu(soak.Cpu):
    """guest_soak's interpreter plus mfc0 Count (the instruction count so far)."""
    def extra_instruction(self, ins, pc):
        if ins >> 26 == 16 and (ins >> 21) & 31 == 0 and (ins >> 11) & 31 == 9:
            self.r[(ins >> 16) & 31] = self.instructions & 0xFFFFFFFF
            return None
        return super().extra_instruction(ins, pc)


def put(ram, address, *words):
    struct.pack_into('<%dI' % len(words), ram, address, *words)


def image(captured=True, fighters=6, seed=1):
    rng = random.Random(seed)
    ram = bytearray(0x8000000)
    manager, battle, cameras, cinematic = 0x01870400, 0x0187A420, 0x01873F00, 0x01874B80
    put(ram, A(0x1C2A28), *struct.unpack('<2I', nh.NATIVE_PROLOGUE))
    put(ram, A(0x2E9808), 0x2E9518)
    ram[0x2E9518 + 168:0x2E9518 + 176] = rng.randbytes(8)
    put(ram, A(0x2FF060), 101)
    ram[A(0x31DBB0):A(0x31DBB0) + 16] = rng.randbytes(16)
    put(ram, A(0x2FEB38), battle)
    put(ram, battle, 3, 0, 1)
    ram[battle + 264:battle + 296] = rng.randbytes(32)
    put(ram, A(0x2FEB14), manager)
    put(ram, A(0x2FEBCC), cinematic, cameras + 1824, cameras)
    ram[cameras + 1824:cameras + 1824 + 1400] = rng.randbytes(1400)
    ram[cinematic + 700:cinematic + 820] = rng.randbytes(120)
    array = 0x018706C0
    put(ram, manager, 2, array)
    actors = [array + i * 0x1600 for i in range(2)] + [0x02565300 + i * 0x3DE40 for i in range(fighters - 2)]
    for i, actor in enumerate(actors[:fighters]):
        ram[actor:actor + 0x1600] = rng.randbytes(0x1600)
        put(ram, actor, i, i & 1, i & 1, i)
        put(ram, actor + 0x994, rng.choice((0, 1, 2, 4, 7)), 3)
    if captured:
        put(ram, core.MODE, 1, fighters, manager, fighters)
        put(ram, core.POINTERS, *actors[:fighters])
        put(ram, nh.cap.CONTROL, nh.cap.MAGIC, 0, 777)
    return bytes(ram)


def run(ram, profile, sweep=False):
    manifest = nh.build_memory(ram, sweep=sweep, profile=profile)
    buffer = bytearray(ram)
    for b in manifest['blocks']:
        data = bytes.fromhex(b['data_hex'])
        assert buffer[b['address']:b['address'] + len(data)].hex() == b['expected_hex']
        buffer[b['address']:b['address'] + len(data)] = data
    cpu = Cpu(buffer, (0x100000, 0x2C0000))
    rng = random.Random(7)
    cpu.r = [0] * 32
    for reg in range(1, 32):
        if reg not in (26, 27, 28, 29):
            cpu.r[reg] = rng.getrandbits(32)
    cpu.r[28], cpu.r[29] = 0x304270, soak.STACK
    before = list(cpu.r)
    stop = cpu.run(nh.CODE, stops=(manifest['previous'],))
    captured = struct.unpack_from('<I', ram, nh.cap.CONTROL)[0] == nh.cap.MAGIC
    key = struct.unpack_from('<I', ram, nh.cap.CONTROL + 8)[0] if captured else 1
    at = nh.RING + (key & (nh.RING_ENTRIES - 1)) * nh.ENTRY
    return stop, manifest, before, cpu, nh.parse_entry(bytes(cpu.buffer[at:at + nh.ENTRY])), key


class ProbeTests(unittest.TestCase):
    def check(self, ram, profile, sweep=False):
        stop, manifest, before, cpu, entry, key = run(ram, profile, sweep)
        self.assertEqual(stop, manifest['previous'])
        self.assertEqual(cpu.r, before, 'every register is restored before the chain continues')
        hashes, words = nh.reference(ram, profile=profile)
        self.assertEqual(entry['key'], key)
        self.assertEqual(entry['classes'], hashes)
        self.assertEqual(entry['words'], words)
        if sweep:
            chunk = key & (nh.SWEEP_CHUNKS - 1)
            base = chunk << 16
            expected = nh.hash_words(bytes(cpu.buffer[base:base + nh.SWEEP_BYTES])) if base >= 0x80000 else 0
            self.assertEqual((entry['chunk'], entry['sweep']), (chunk, expected))
        return entry, cpu

    def test_captured_lean_and_full(self):
        ram = image(True, 6)
        lean, _ = self.check(ram, 'lean')
        full, _ = self.check(ram, 'full')
        self.assertLess(lean['words'], full['words'])
        self.assertEqual(lean['classes'][0], full['classes'][0], 'the rng class is the same in both profiles')

    def test_native_pair_fallback_uses_own_key(self):
        ram = image(False, 2)
        self.assertEqual(len(nh.fighters(ram)), 2)
        entry, _ = self.check(ram, 'lean')
        self.assertEqual(entry['key'], 1)

    def test_sweep(self):
        self.check(image(True, 4, seed=3), 'lean', sweep=True)

    def test_lean_budget(self):
        _, _, _, cpu, entry, _ = run(image(True, 10, seed=5), 'lean')
        self.assertLess(cpu.instructions, 10000, 'under 10k EE instructions with ten fighters and counter-pair safety state')

    def test_disabled_probe_only_counts(self):
        ram = bytearray(image(True, 2))
        manifest = nh.build_memory(bytes(ram), enabled=False)
        self.assertEqual(struct.unpack_from('<3I', bytes.fromhex(next(b['data_hex'] for b in manifest['blocks']
                                                                       if b['address'] == nh.CONTROL)))[2], 0)

    def test_reservation_and_chain(self):
        ram = bytearray(image(True, 2))
        ram[nh.BASE + 0x100] = 1
        with self.assertRaises(ValueError):
            nh.build_memory(bytes(ram))
        ram = bytearray(image(True, 2))
        put(ram, A(0x1C2A28), (2 << 26) | (0x070B6000 >> 2), 0)
        self.assertEqual(nh.chain_previous(ram), (0x070B6000, []))
        put(ram, A(0x1C2A28), 0x12345678, 0)
        with self.assertRaises(ValueError):
            nh.chain_previous(ram)

    def test_excluded_host_words_are_not_in_the_lean_table(self):
        import native_preparation as preparation
        import guest_loading_screen as cover
        import quad_controller as quad
        import controller_assignment as assignment
        import fusion_duration as fusion
        # Importing the trainer executes native-instruction assertions. Read its
        # declared mailbox constant without importing the whole runtime.
        tree = ast.parse((support.TOOLS / 'fresh_team_trainer.py').read_text(encoding='utf-8-sig'))
        ACK_ADDRESS = next(ast.literal_eval(node.value) for node in tree.body
                           if isinstance(node, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == 'ACK_ADDRESS' for t in node.targets))
        spans = [(address, address + 4 * words) for kind, _, address, _, words, _ in nh.descriptors('lean')
                 if kind == nh.DIRECT]
        for lo, hi in ((A(0x333800), A(0x333800) + 896), (preparation.CONTROL, preparation.CONTROL + 0x100),
                       (preparation.PACKET, preparation.PACKET + preparation.CAPACITY), (cover.CONTROL, cover.CONTROL + 0x100),
                       (quad.BASE, quad.END), (assignment.CODE, assignment.END), (fusion.CONTROL + 12, fusion.CONTROL + 16),
                       (ACK_ADDRESS, ACK_ADDRESS + 16)):
            self.assertFalse(any(a < hi and lo < b for a, b in spans), hex(lo))

    @unittest.skipUnless(os.environ.get('TAGTEAM_NETPLAY_FIXTURE'), 'TAGTEAM_NETPLAY_FIXTURE names a prepared match')
    def test_real_prepared_match(self):
        from camera_snapshot import read_ram
        ram = read_ram(os.environ['TAGTEAM_NETPLAY_FIXTURE'])
        for profile in ('lean', 'full'):
            self.check(ram, profile)


if __name__ == '__main__':
    unittest.main()
