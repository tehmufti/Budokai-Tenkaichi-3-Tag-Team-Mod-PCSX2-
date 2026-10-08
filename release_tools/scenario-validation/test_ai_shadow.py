"""Behavior checks for generated MIPS hooks (not a game-engine emulator)."""
import struct
import unittest

from ai_shadow import AI_GLOBAL, GP, GET_LOGICAL, GET_PHYSICAL, build


class Mips:
    """Interpret the emitted integer subset with real MIPS delay slots."""
    instruction_budget = 10000
    def __init__(self, manifest):
        self.memory = {}
        self.r = [0] * 32
        self.r[28], self.r[29], self.r[31] = GP, 0x2000000 - 0x100, 0xFEED0000
        self.callbacks = {}
        for segment in manifest["segments"]:
            self.write(segment["address"], bytes.fromhex(segment["data_hex"]))

    def write(self, address, data):
        self.memory.update((address + index, value) for index, value in enumerate(data))

    def read(self, address, length):
        return bytes(self.memory.get(address + index, 0) for index in range(length))

    def w(self, address, value):
        self.write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def u(self, address):
        return int.from_bytes(self.read(address, 4), "little")

    @staticmethod
    def signed_word(value):
        # Native routines tested here compare values produced by LW/ADDIU.
        # Their architectural sign extension is deferred in this small harness.
        value &= 0xFFFFFFFF
        return value if value < 0x80000000 else value - 0x100000000

    def extra_instruction(self, ins, pc):
        """Return delayed target, or (target, annul_untaken_delay) for likely."""
        raise AssertionError(f"Unsupported instruction {ins:08X} at {pc:08X}")

    def run(self, pc, stops=()):
        pending = None
        for _ in range(self.instruction_budget):
            if pc in stops or pc == 0xFEED0000:
                return pc
            if pc in self.callbacks:
                self.callbacks[pc](self)
                pc = self.r[31]
                continue
            ins = self.u(pc)
            op, rs, rt, rd = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
            imm = ins & 65535
            signed = imm if imm < 32768 else imm - 65536
            previous, pending = pending, None
            if ins == 0:
                pass
            elif op == 9:
                self.r[rt] = (self.r[rs] + signed) & 0xFFFFFFFF
            elif op == 15:
                self.r[rt] = imm << 16
            elif op == 13:
                self.r[rt] = self.r[rs] | imm
            elif op == 12:
                self.r[rt] = self.r[rs] & imm
            elif op == 14:
                self.r[rt] = self.r[rs] ^ imm
            elif op == 11:
                self.r[rt] = int((self.r[rs] & 0xFFFFFFFFFFFFFFFF) < (signed & 0xFFFFFFFFFFFFFFFF))
            elif op == 10:
                self.r[rt] = int(self.signed_word(self.r[rs]) < signed)
            elif op in [35, 55]:
                self.r[rt] = int.from_bytes(self.read(self.r[rs] + signed, 8 if op == 55 else 4), "little")
            elif op in [32, 36]:
                value = self.read(self.r[rs] + signed, 1)[0]
                self.r[rt] = (value-256 if op == 32 and value >= 128 else value) & 0xFFFFFFFF
            elif op in [40, 43, 63]:
                size = 1 if op == 40 else 8 if op == 63 else 4
                self.write(self.r[rs] + signed, (self.r[rt] & ((1 << (size * 8)) - 1)).to_bytes(size, "little"))
            elif op in [4, 5]:
                equal = self.r[rs] == self.r[rt]
                if equal == (op == 4):
                    pending = pc + 4 + signed * 4
            elif op == 6:
                if self.signed_word(self.r[rs]) <= 0:
                    pending = pc + 4 + signed * 4
            elif op == 7:
                if self.signed_word(self.r[rs]) > 0:
                    pending = pc + 4 + signed * 4
            elif op in (22, 23):
                taken = self.signed_word(self.r[rs]) <= 0
                if taken == (op == 22):
                    pending = pc + 4 + signed * 4
                else:
                    pc += 4
            elif op == 1 and rt in (0, 1, 2, 3):
                negative = self.signed_word(self.r[rs]) < 0
                if negative == (rt in (0, 2)):
                    pending = pc + 4 + signed * 4
                elif rt in (2, 3):
                    pc += 4  # REGIMM branch-likely annuls the untaken slot.
            elif op in [20, 21]:
                equal = self.r[rs] == self.r[rt]
                if equal == (op == 20):
                    pending = pc + 4 + signed * 4
                else:
                    pc += 4  # Untaken branch-likely annuls its delay slot.
            elif op in [2, 3]:
                if op == 3:
                    self.r[31] = pc + 8
                pending = ((pc + 4) & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
            elif op == 0 and (ins & 63) == 8:
                pending = self.r[rs]
            elif op == 0 and (ins & 63) == 9:
                pending = self.r[rs]
                self.r[rd] = pc + 8
            elif op == 0 and (ins & 63) == 0x2D:
                self.r[rd] = self.r[rs] + self.r[rt]
            elif op == 0 and (ins & 63) == 0x2A:
                self.r[rd] = int(self.signed_word(self.r[rs]) < self.signed_word(self.r[rt]))
            elif op == 0 and (ins & 63) == 0x2B:
                self.r[rd] = int((self.r[rs] & 0xFFFFFFFFFFFFFFFF) < (self.r[rt] & 0xFFFFFFFFFFFFFFFF))
            elif op == 0 and (ins & 63) == 0x0B:
                if self.r[rt] != 0:
                    self.r[rd] = self.r[rs]
            elif op == 0 and (ins & 63) == 0x21:
                self.r[rd] = (self.r[rs] + self.r[rt]) & 0xFFFFFFFF
            elif op == 0 and (ins & 63) == 0x23:
                self.r[rd] = (self.r[rs] - self.r[rt]) & 0xFFFFFFFF
            elif op == 0 and (ins & 63) == 0x25:
                self.r[rd] = self.r[rs] | self.r[rt]
            elif op == 0 and (ins & 63) == 0x26:
                self.r[rd] = self.r[rs] ^ self.r[rt]
            elif op == 0 and (ins & 63) == 0x24:
                self.r[rd] = self.r[rs] & self.r[rt]
            elif op == 0 and (ins & 63) == 4:
                self.r[rd] = (self.r[rt] << (self.r[rs] & 31)) & 0xFFFFFFFF
            elif op == 0 and (ins & 63) == 3:
                self.r[rd] = (self.signed_word(self.r[rt]) >> ((ins >> 6) & 31)) & 0xFFFFFFFF
            elif op == 0 and (ins & 63) == 0:
                self.r[rd] = (self.r[rt] << ((ins >> 6) & 31)) & 0xFFFFFFFF
            else:
                extension = self.extra_instruction(ins, pc)
                if isinstance(extension, tuple):
                    pending, annul = extension
                    if annul: pc += 4
                else:
                    pending = extension
            self.r[0] = 0
            pc = previous if previous is not None else pc + 4
        raise AssertionError("Instruction budget exceeded")


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.manifest = build()

    def test_getter_gates_preserve_original_path(self):
        for original, stub in [(GET_PHYSICAL, 0xB4000), (GET_LOGICAL, 0xB4100)]:
            for active in [0, 1]:
                for exposed in [0, 1]:
                    for argument in range(5):
                        cpu = Mips(self.manifest)
                        cpu.w(0xB4800, active)
                        cpu.w(0xB4804, 0x1800000)
                        cpu.w(0xB4818, exposed)
                        cpu.w(0xB301C, 0x1800000)
                        cpu.r[4] = argument
                        stop = cpu.run(stub, [original + 8])
                        redirect = (active and argument == 0) or (original == GET_PHYSICAL and argument == 2 and exposed)
                        if redirect:
                            self.assertEqual(stop, 0xFEED0000)
                            self.assertEqual(cpu.r[2], 0x1800000)
                        else:
                            self.assertEqual(stop, original + 8)
                        self.assertEqual(cpu.r[4], argument)

    def test_frame_shadow_is_private_and_restores_globals(self):
        cpu = Mips(self.manifest)
        real, shadow, actor = 0x1873460, 0xB4900, 0x1800000
        cpu.w(AI_GLOBAL, real)
        cpu.w(real + 0xA50, 123)
        cpu.w(real + 0x10, 0x12345678)
        cpu.w(real + 0x530, 0xABCDEF00)
        cpu.w(shadow + 0x28, 0x777000)
        cpu.w(actor, 2)
        cpu.w(0xB4804, actor)
        cpu.w(0xB480C, 1)
        saved = [0xA000000000000000 + index for index in range(4)]
        cpu.r[16:20] = saved
        seen = []

        def normal(c):
            self.assertEqual(c.u(AI_GLOBAL), real)
            c.w(real + 0xA50, c.u(real + 0xA50) + 1)

        def extra(c):
            self.assertEqual(c.u(AI_GLOBAL), shadow)
            self.assertEqual(c.u(0xB4800), 1)
            self.assertEqual(c.u(actor), 0)
            self.assertEqual(c.u(shadow + 0xA50), c.u(real + 0xA50))
            seen.append(True)

        def emit(c):
            extra(c)
            c.w(shadow + 0x278, c.u(shadow + 0x278) + 8)
            c.w(actor + 0x127C, c.u(shadow + 0x278))

        cpu.callbacks[0x1BB620] = normal
        for target in [0x1BB510, 0x1BFF70, 0x1BAC30, 0x1B6BA0]:
            cpu.callbacks[target] = extra
        cpu.callbacks[0x1B6CD8] = emit
        for tick in range(2):
            cpu.run(0xB4180)
            self.assertEqual(cpu.u(AI_GLOBAL), real)
            self.assertEqual(cpu.u(actor), 2)
            self.assertEqual(cpu.u(0xB4800), 0)
            self.assertEqual(cpu.u(0xB4810), tick + 1)
            self.assertEqual(cpu.u(0xB4814), 8 * (tick + 1))
            self.assertEqual(cpu.u(actor + 0x127C), 8 * (tick + 1))
            self.assertEqual(cpu.u(real + 0x10), 0x12345678)
            self.assertEqual(cpu.u(shadow + 0x530), 0xABCDEF00)
            self.assertEqual(cpu.r[16:20], saved)
        self.assertEqual(len(seen), 10)
        # An unchanged normal tick counter must suppress every extra call.
        cpu.callbacks[0x1BB620] = lambda c: None
        cpu.run(0xB4180)
        self.assertEqual(len(seen), 10)
        self.assertEqual(cpu.u(0xB4810), 2)


if __name__ == "__main__":
    unittest.main()
