import struct
from ai_shadow import GP

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
