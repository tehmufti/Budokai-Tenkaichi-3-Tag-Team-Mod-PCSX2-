"""Offline guest soak: run a prepared match's installed guest code without an emulator (developer tooling).

A real prepared match (the EE RAM of a 17-playable-team.p2s, a .bin RAM image, or an image composed here from a
captured AI-ready fixture) carries a few hundred mod hooks in the BT3 executable and the guest code they jump
to. This module runs that guest code in a self-contained MIPS interpreter, frame after frame:

- chain_soak(): the per-frame actor-update chain at A(0x1C2A28) for N frames, optionally knocking fighters out.
- drive_hooks(): every function-entry hook (a native prologue 'addiu sp,sp,-N' replaced by 'j guest') and every
  call replacement ('jal native' replaced by 'jal guest'), a few frames each, with the leaders as a0. Mid-function
  hooks need the native register context of their exact point and are only counted.
- fuzz(): random plausible mutations of native scalar fields (HP, action, slot including one past the end, pad
  words, the AI digital word) before each frame of the chain.
- compose()/compose_matrix(): rebuild the final prepared-match manifest on a captured AI-ready fixture
  (14-ai-ready.bin + ai-installation.json + support.json) for each battle mode and human count, then soak it.

Native BT3 code is never run for the guest: a call from guest code into the executable returns v0=v1=0 (plus
any semantic stub registered), and a trampoline's displaced prologue ('addiu sp,sp,-N') is undone when it jumps
back into the executable. A run fails on an unsupported instruction, a runaway loop (instruction budget), an
access outside EE RAM, and it records every guest write into native text and into the boot-resident mod code
(guest_loading_screen.code_pieces(), the machine code sync() verifies) as findings.

Fidelity limits (see the p8 simulation report): registers are 32-bit zero-extended (the EE sign-extends to 64
bits), there is no COP0/COP2/VU0, DMA, VIF/GIF or IOP, and native behaviour is stubbed, so this finds guest-code
crashes, runaway loops and stray writes, not gameplay bugs. Gameplay needs the emulator. FPU: cvt.w.s follows
the EE (truncate toward zero; an operand of 2**31 or more, or exponent 255, saturates to 0x7FFFFFFF/0x80000000
by sign), but add/sub/mul/div are IEEE single precision: the EE's clamping to +-max, its denormal flush and its
rounding mode are not modelled, and div by zero gives 0.

Live stress phase: health()/Monitor read the same guest telemetry (render heartbeat, cinematic hold overruns,
DBR1 counters, extra-reload refusals, the menu-return flags and the boot code check) from any reader with
read(address, size): a RAM image here, a pine.PineClient in a live run (whose running game's serial and CRC are
checked first: another disc's memory is never interpreted).

The European disc: run in a process started with TAGTEAM_ADAPTER=bt3-pal (native_map resolves the adapter once
per process) and --root naming a folder whose analysis/SLES_549.45 is the European executable.

Not part of the player payload: no runtime module imports this file, and it imports no test module.

    python guest_soak.py soak  <image> [--frames 600] [--ko 120:2,240:3]
    python guest_soak.py hooks <image>
    python guest_soak.py fuzz  <image> [--frames 3000] [--seed 1]
    python guest_soak.py compose <ai-ready folder> [...]
    python guest_soak.py health <image>
    python guest_soak.py suite <image> [...]          (soak + hooks + short fuzz, one JSON report)
    python guest_soak.py monitor --port 28011 --seconds 600 [--interval 1] [--freeze 5] [--crc A422BB13]
        (live, read-only PINE sampling; Ctrl+C ends it early, and the --json report is written either way)
  common options: --root <game dir holding analysis/<executable>>, --json <report path>, --no-pieces
"""
import collections
import json
import math
import os
import random
import struct
import sys
import time
from pathlib import Path

RAM_BYTES = 0x8000000
SENTINEL = 0xFEED0000          # return address that ends a harness call
STACK = 0x01F00000             # harness stack top (ordinary EE RAM below the 32 MiB native image end)
GUEST_LO, GUEST_HI = 0x06000000, 0x08000000   # the reviewed guest reservations above heap1
LOW_GUEST = 0x00080000        # low guest code below the executable (0xDB000 and 0xE8000 wrappers)
SCRATCH = 0x01F80000          # zeroed harness scratch for synthetic caller context
POINTERS = 0xD8040             # fresh_team_combat.POINTERS: the guest actor table (guest memory, not translated)
PAD_STRIDE, PAD_BUTTONS = 448, 328
AI_WORD = 0x127C               # an actor's AI-written digital word (input_script mode 1)
ACTOR_STRIDE, SLOT, ROWS, ACTION, HP, ROW_STRIDE = 0x1600, 0x994, 0x998, 0x948, 0x9E4, 0xA4


def _native():
    """native_map values, imported late so a caller can point prototype.ROOT at a game folder first."""
    import native_map
    return native_map


def set_root(root):
    """Build against the game folder `root` (its analysis/<serial file> is the executable)."""
    import prototype
    prototype.ROOT = Path(root)
    return prototype.ROOT


def elf(root=None):
    """(blob, segments, read) of the selected disc's executable under root (default prototype.ROOT)."""
    import prototype
    return prototype.elf_reader(_native().elf_path(root or prototype.ROOT))


def load_image(path):
    """A 128 MiB EE RAM image from a .p2s savestate or a raw .bin."""
    from camera_snapshot import read_ram
    ram = read_ram(Path(path))
    if len(ram) != RAM_BYTES:
        raise ValueError(f'{path}: expected a 128 MiB EE RAM image, got {len(ram):#x} bytes')
    return bytes(ram)


def u32(buf, p):
    return struct.unpack_from('<I', buf, p)[0]


class Unsupported(Exception):
    """An instruction the interpreter does not implement."""


class Budget(Exception):
    """A call did not return within the instruction budget (a runaway loop)."""


class Cpu:
    """The tests' interpreter subset (test_ai_shadow.Mips, ScalarMips FPU, test_extra_special_pools and
    test_fusion_partner_lifecycle extensions), self-contained, with native-call stubbing and write accounting."""
    instruction_budget = 3_000_000

    def __init__(self, ram, text, guards=()):
        self.buffer = bytearray(ram)
        self.text = text                      # (start, end) of the executable's text
        self.guards = tuple(guards)           # (start, end) of boot-resident mod code
        self._guard_pages = frozenset(page for lo, hi in self.guards for page in range(lo >> 12, ((hi - 1) >> 12) + 1))
        self.r = [0] * 32; self.f = [0] * 32; self.hi = self.lo = 0; self.condition = False; self.fcr31 = 0
        self.callbacks = {}                   # pc -> callable(cpu); returns to $ra
        self.semantic = {}                    # native address -> callable(cpu) run after the v0=v1=0 stub
        self.continuations = {}               # site+8 -> N for function-entry hooks (learn_continuations)
        self.stub_sentinel = False            # True: a jump into native text straight from the harness is stubbed too
        self.instructions = 0
        self.native_calls = collections.Counter()
        self.native_callers = collections.defaultdict(set)
        self.blocks = collections.Counter()
        self.text_writes = collections.Counter()
        self.guard_writes = collections.Counter()
        self.page_writes = collections.Counter()
        self.pc = 0

    # ---- memory
    def in_text(self, p):
        return self.text[0] <= p < self.text[1]

    def read(self, p, n):
        p &= 0x1FFFFFFF if p >= 0x80000000 else 0xFFFFFFFF
        if not 0 <= p <= len(self.buffer) - n:
            raise IndexError(f'read outside EE RAM at {p:#x}+{n} (pc {self.pc:08X})')
        return bytes(self.buffer[p:p + n])

    def write(self, p, data):
        p &= 0x1FFFFFFF if p >= 0x80000000 else 0xFFFFFFFF
        if not 0 <= p <= len(self.buffer) - len(data):
            raise IndexError(f'write outside EE RAM at {p:#x}+{len(data)} (pc {self.pc:08X})')
        if self.in_text(p):
            self.text_writes[(p & ~3, self.pc)] += 1
        if p >> 12 in self._guard_pages or (p + len(data) - 1) >> 12 in self._guard_pages:
            for lo, hi in self.guards:
                if lo < p + len(data) and p < hi:
                    self.guard_writes[(p & ~3, self.pc)] += 1
        self.page_writes[p >> 12] += 1
        self.buffer[p:p + len(data)] = data

    def u(self, p):
        return int.from_bytes(self.read(p, 4), 'little')

    def w(self, p, v):
        self.write(p, struct.pack('<I', v & 0xFFFFFFFF))

    @staticmethod
    def signed_word(value):
        value &= 0xFFFFFFFF
        return value if value < 0x80000000 else value - 0x100000000

    def number(self, r):
        return struct.unpack('<f', struct.pack('<I', self.f[r] & 0xFFFFFFFF))[0]

    def set_number(self, r, v):
        self.f[r] = struct.unpack('<I', struct.pack('<f', v))[0]

    @staticmethod
    def ee_cvt_w(bits):
        """cvt.w.s as the EE FPU does it (it only rounds toward zero; PCSX2's CVT_W): truncate toward zero, and
        saturate by sign once the magnitude reaches 2**31 (exponent field above 0x9D), which includes the bit
        patterns IEEE calls inf and NaN (ordinary large numbers on the EE)."""
        bits &= 0xFFFFFFFF
        if (bits & 0x7F800000) <= 0x4E800000:
            value = struct.unpack('<f', struct.pack('<I', bits))[0]
            return math.trunc(value) & 0xFFFFFFFF
        return 0x80000000 if bits & 0x80000000 else 0x7FFFFFFF

    # ---- execution
    def call(self, pc, a0=0, sp=STACK, gp=None, registers=None):
        """Run from pc with a fresh register file until it returns to the sentinel."""
        self.r = [0] * 32
        for reg, value in (registers or {}).items():
            self.r[reg] = value & 0xFFFFFFFF
        self.r[28] = _native().GP if gp is None else gp
        self.r[29] = sp; self.r[31] = SENTINEL; self.r[4] = a0 & 0xFFFFFFFF
        return self.run(pc)

    def run(self, pc, stops=()):
        pending = None
        for _ in range(self.instruction_budget):
            if pc in stops or pc == SENTINEL:
                return pc
            if pc in self.callbacks:
                self.callbacks[pc](self); pc = self.r[31] & 0xFFFFFFFF; continue
            ra = self.r[31] & 0xFFFFFFFF
            if self.in_text(pc) and not self.in_text(ra) and (self.stub_sentinel or ra != SENTINEL):
                # Called from guest code: never run BT3 itself.
                self.native_calls[pc] += 1; self.native_callers[pc].add((ra - 8) & 0xFFFFFFFF)
                self.r[2] = self.r[3] = 0
                if pc in self.continuations:
                    # A trampoline ran the hooked function's displaced 'addiu sp,sp,-N' before jumping here.
                    self.r[29] = (self.r[29] + self.continuations[pc]) & 0xFFFFFFFF
                if pc in self.semantic:
                    self.semantic[pc](self)
                pc = ra; continue
            if not self.in_text(pc):
                self.blocks[pc & ~0xFF] += 1
            self.instructions += 1
            holder = [pending]
            pc = self.step(pc, holder)
            pending = holder[0]
        raise Budget(f'instruction budget exceeded near {pc:#x}')

    def step(self, pc, holder):
        """One instruction; holder[0] carries a pending delayed branch target in and out."""
        self.pc = pc
        ins = self.u(pc)
        op, rs, rt, rd = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
        imm = ins & 65535; signed = imm if imm < 32768 else imm - 65536
        previous, pending = holder[0], None
        r = self.r
        fn = ins & 63
        if ins == 0: pass
        elif op == 9: r[rt] = (r[rs] + signed) & 0xFFFFFFFF
        elif op == 15: r[rt] = imm << 16
        elif op == 13: r[rt] = r[rs] | imm
        elif op == 12: r[rt] = r[rs] & imm
        elif op == 14: r[rt] = r[rs] ^ imm
        elif op == 11: r[rt] = int((r[rs] & 0xFFFFFFFFFFFFFFFF) < (signed & 0xFFFFFFFFFFFFFFFF))
        elif op == 10: r[rt] = int(self.signed_word(r[rs]) < signed)
        elif op in (35, 55): r[rt] = int.from_bytes(self.read((r[rs] + signed) & 0xFFFFFFFF, 8 if op == 55 else 4), 'little')
        elif op in (32, 36):
            v = self.read((r[rs] + signed) & 0xFFFFFFFF, 1)[0]; r[rt] = (v - 256 if op == 32 and v >= 128 else v) & 0xFFFFFFFF
        elif op == 33:
            v = int.from_bytes(self.read((r[rs] + signed) & 0xFFFFFFFF, 2), 'little'); r[rt] = (v - 65536 if v >= 32768 else v) & 0xFFFFFFFF
        elif op in (40, 43, 63):
            size = 1 if op == 40 else 8 if op == 63 else 4
            self.write((r[rs] + signed) & 0xFFFFFFFF, (r[rt] & ((1 << (size * 8)) - 1)).to_bytes(size, 'little'))
        elif op in (4, 5):
            if (r[rs] == r[rt]) == (op == 4): pending = pc + 4 + signed * 4
        elif op == 6:
            if self.signed_word(r[rs]) <= 0: pending = pc + 4 + signed * 4
        elif op == 7:
            if self.signed_word(r[rs]) > 0: pending = pc + 4 + signed * 4
        elif op in (22, 23):
            taken = self.signed_word(r[rs]) <= 0
            if taken == (op == 22): pending = pc + 4 + signed * 4
            else: pc += 4
        elif op == 1 and rt in (0, 1, 2, 3):
            negative = self.signed_word(r[rs]) < 0
            if negative == (rt in (0, 2)): pending = pc + 4 + signed * 4
            elif rt in (2, 3): pc += 4
        elif op in (20, 21):
            if (r[rs] == r[rt]) == (op == 20): pending = pc + 4 + signed * 4
            else: pc += 4
        elif op in (2, 3):
            if op == 3: r[31] = pc + 8
            pending = ((pc + 4) & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
        elif op == 0 and fn == 8: pending = r[rs] & 0xFFFFFFFF
        elif op == 0 and fn == 9: pending = r[rs] & 0xFFFFFFFF; r[rd] = pc + 8
        elif op == 0 and fn == 0x2D: r[rd] = (r[rs] + r[rt]) & 0xFFFFFFFFFFFFFFFF
        elif op == 0 and fn == 0x2A: r[rd] = int(self.signed_word(r[rs]) < self.signed_word(r[rt]))
        elif op == 0 and fn == 0x2B: r[rd] = int((r[rs] & 0xFFFFFFFFFFFFFFFF) < (r[rt] & 0xFFFFFFFFFFFFFFFF))
        elif op == 0 and fn == 0x0B:
            if r[rt] != 0: r[rd] = r[rs]
        elif op == 0 and fn == 0x21: r[rd] = (r[rs] + r[rt]) & 0xFFFFFFFF
        elif op == 0 and fn == 0x23: r[rd] = (r[rs] - r[rt]) & 0xFFFFFFFF
        elif op == 0 and fn == 0x25: r[rd] = r[rs] | r[rt]
        elif op == 0 and fn == 0x26: r[rd] = r[rs] ^ r[rt]
        elif op == 0 and fn == 0x24: r[rd] = r[rs] & r[rt]
        elif op == 0 and fn == 4: r[rd] = (r[rt] << (r[rs] & 31)) & 0xFFFFFFFF
        elif op == 0 and fn == 3: r[rd] = (self.signed_word(r[rt]) >> ((ins >> 6) & 31)) & 0xFFFFFFFF
        elif op == 0 and fn == 0: r[rd] = (r[rt] << ((ins >> 6) & 31)) & 0xFFFFFFFF
        else:
            extension = self.extra_instruction(ins, pc)
            if isinstance(extension, tuple):
                pending, annul = extension
                if annul: pc += 4
            else:
                pending = extension
        r[0] = 0
        holder[0] = pending
        return previous if previous is not None else pc + 4

    def extra_instruction(self, ins, pc):
        op, rs, rt, rd = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
        fs, fd, fn = rd, (ins >> 6) & 31, ins & 63
        imm = ins & 65535; signed = imm if imm < 32768 else imm - 65536
        address = (self.r[rs] + signed) & 0xFFFFFFFF
        r = self.r
        if op == 17 and rs in (2, 6):
            if rs == 2: r[rt] = self.fcr31
            else: self.fcr31 = r[rt] & 0xFFFFFFFF
            return None
        if op == 28 and fn == 24:
            r[rd] = (self.signed_word(r[rs]) * self.signed_word(r[rt])) & 0xFFFFFFFF; return None
        if op in (30, 31, 37):
            if op == 31: self.write(address, (r[rt] & ((1 << 128) - 1)).to_bytes(16, 'little'))
            else: r[rt] = int.from_bytes(self.read(address, 2 if op == 37 else 16), 'little')
            return None
        if op in (26, 27, 44, 45):
            if address & 7 != (7 if op in (26, 44) else 0):
                raise Unsupported(f'unaligned ldl/ldr/sdl/sdr {ins:08X} at {pc:08X}')
            address &= ~7
            if op in (26, 27): r[rt] = int.from_bytes(self.read(address, 8), 'little')
            else: self.write(address, (r[rt] & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little'))
            return None
        if op == 17 and rs == 16 and fn == 36:
            self.f[fd] = self.ee_cvt_w(self.f[fs]); return None
        if op == 0 and fn == 2: r[rd] = (r[rt] & 0xFFFFFFFF) >> ((ins >> 6) & 31); return None
        if op == 0 and fn == 24:
            v = self.signed_word(r[rs]) * self.signed_word(r[rt]); self.lo = v & 0xFFFFFFFF; self.hi = (v >> 32) & 0xFFFFFFFF
            if rd: r[rd] = self.lo       # EE mult also writes rd
            return None
        if op == 0 and fn == 27:
            a, b = r[rs] & 0xFFFFFFFF, r[rt] & 0xFFFFFFFF
            if b: self.lo, self.hi = a // b, a % b
            return None
        if op == 0 and fn in (16, 18): r[rd] = self.hi if fn == 16 else self.lo; return None
        if op == 0 and fn in (17, 19):
            if fn == 17: self.hi = r[rs] & 0xFFFFFFFF
            else: self.lo = r[rs] & 0xFFFFFFFF
            return None
        if op == 0 and fn == 39: r[rd] = ~(r[rs] | r[rt]) & 0xFFFFFFFFFFFFFFFF; return None
        if op == 0 and fn == 10:
            if not r[rt]: r[rd] = r[rs]
            return None
        if op == 0 and fn == 6: r[rd] = (r[rt] & 0xFFFFFFFF) >> (r[rs] & 31); return None
        if op == 0 and fn == 7: r[rd] = (self.signed_word(r[rt]) >> (r[rs] & 31)) & 0xFFFFFFFF; return None
        if op == 41: self.write(address, struct.pack('<H', r[rt] & 65535)); return None
        if op == 49: self.f[rt] = self.u(address); return None
        if op == 57: self.w(address, self.f[rt]); return None
        if op == 17 and rs == 4: self.f[fs] = r[rt] & 0xFFFFFFFF; return None
        if op == 17 and rs == 0: r[rt] = self.f[fs]; return None
        if op == 17 and rs == 8:
            taken = self.condition == bool(rt & 1)
            return (pc + 4 + signed * 4 if taken else None, bool(rt & 2) and not taken)
        if op == 17 and rs == 16:
            x, y = self.number(fs), self.number(rt)
            if fn in (0x32, 0x34, 0x36):
                self.condition = x == y if fn == 0x32 else x < y if fn == 0x34 else x <= y; return None
            if fn == 5: self.f[fd] = self.f[fs] & 0x7FFFFFFF; return None
            if fn == 6: self.f[fd] = self.f[fs]; return None
            if fn == 7: self.f[fd] = self.f[fs] ^ 0x80000000; return None
            if fn in (0, 1, 2, 3):
                if fn == 3 and y == 0:
                    self.set_number(fd, 0.0); return None
                self.set_number(fd, x + y if fn == 0 else x - y if fn == 1 else x * y if fn == 2 else x / y); return None
        if op == 17 and rs == 20 and fn == 32:
            self.set_number(fd, float(self.signed_word(self.f[fs]))); return None
        raise Unsupported(f'unsupported instruction {ins:08X} at {pc:08X}')


# ------------------------------------------------------------------------------------------------ image facts

def text_range(segments):
    """The executable's text: its first loadable segment (the European text is longer than the USA text)."""
    va, _, filesz, _ = segments[0]
    return va, va + filesz


def guard_ranges():
    """Boot-resident mod code (guest_loading_screen.code_pieces(): what its sync() compares before publishing)."""
    import guest_loading_screen
    return tuple((a, a + len(d)) for a, d in guest_loading_screen.code_pieces())


def learn_continuations(ram, native, text):
    """site+8 -> N for every native function whose prologue 'addiu sp,sp,-N' the image replaced with 'j guest'."""
    out = {}
    for p in range(text[0], text[1] & ~3, 4):
        new = u32(ram, p)
        if new >> 26 != 2:
            continue
        old = struct.unpack('<I', native(p, 4))[0]
        if old == new or old >> 16 != 0x27BD or not old & 0x8000:
            continue
        out[p + 8] = 0x10000 - (old & 0xFFFF)
    return out


def hook_sites(ram, blob, segments):
    """Every changed executable word that jumps (j/jal) into guest memory: (site, target, kind, original)."""
    va, off, fs, _ = segments[0]
    sites = []
    for i in range(0, fs & ~3, 4):
        p = va + i; old = u32(blob, off + i); new = u32(ram, p)
        if old == new or (new >> 26) not in (2, 3):
            continue
        target = (new & 0x3FFFFFF) << 2
        if not (GUEST_LO <= target < GUEST_HI or LOW_GUEST <= target < va):
            continue
        if new >> 26 == 3:
            kind = 'call'
        elif old >> 16 == 0x27BD and old & 0x8000:
            kind = 'entry'
        else:
            kind = 'mid'
        sites.append((p, target, kind, old))
    return sites


def caller_context():
    """Call replacements that read their native caller's saved registers: target -> registers to point at a
    zeroed scratch row. beam_clash's READY bridges read 'first/second contact+0x20' from s3/s2 of 12E458."""
    import beam_clash
    return {beam_clash.READY0: (19,), beam_clash.READY1: (18,)}


def actors(ram, limit=12):
    """The prepared match's actors from the guest actor table."""
    found = []
    for i in range(limit):
        p = u32(ram, POINTERS + 4 * i)
        if 0x100000 <= p < RAM_BYTES - ACTOR_STRIDE:
            found.append(p)
    return found


class Context:
    """What every run needs from one image: the executable, its text range, guards and continuations."""
    def __init__(self, ram, *, root=None, pieces=True):
        if len(ram) != RAM_BYTES:
            raise ValueError('A 128 MiB EE RAM image is required')
        self.ram = bytes(ram)
        self.blob, self.segments, self.native = elf(root)
        self.text = text_range(self.segments)
        self.guards = guard_ranges() if pieces else ()
        self.continuations = learn_continuations(self.ram, self.native, self.text)
        nm = _native()
        self.hook = nm.A(0x1C2A28)
        self.manager = u32(self.ram, nm.A(0x2FEB14))

    def cpu(self, ram=None, budget=None):
        cpu = Cpu(self.ram if ram is None else ram, self.text, self.guards)
        cpu.continuations = self.continuations
        if budget:
            cpu.instruction_budget = budget
        return cpu

    def chain_cpu(self, ram=None):
        """A cpu set up for the frame chain: the trampoline's displaced 'addiu sp,-16; sd s0,0(sp)' is undone
        when it jumps back to the native body at hook+8."""
        cpu = self.cpu(ram)
        def native_rest(c):
            c.r[16] = int.from_bytes(c.read(c.r[29], 8), 'little'); c.r[29] = (c.r[29] + 16) & 0xFFFFFFFF
        cpu.callbacks[self.hook + 8] = native_rest
        return cpu


def _findings(cpu):
    return dict(text_writes=sorted({f'{p:08X}<-{pc:08X}' for p, pc in cpu.text_writes})[:20],
                guard_writes=sorted({f'{p:08X}<-{pc:08X}' for p, pc in cpu.guard_writes})[:20])


def _error(error):
    return f'{type(error).__name__}: {error}'


# ------------------------------------------------------------------------------------------------ runs

def chain_soak(context, frames=600, kos=None):
    """Run the per-frame chain for `frames` frames. kos: {frame: [actor index, ...]} zeroes that actor's HP."""
    cpu = context.chain_cpu()
    per_frame, failure = [], None
    head = u32(context.ram, context.hook)
    for frame in range(frames):
        for index in (kos or {}).get(frame, ()):
            table = actors(cpu.buffer)
            if index < len(table):
                actor = table[index]; slot = min(u32(cpu.buffer, actor + SLOT), 4)
                struct.pack_into('<I', cpu.buffer, actor + HP + ROW_STRIDE * slot, 0)
        before = cpu.instructions
        try:
            cpu.call(context.hook, a0=context.manager)
        except Exception as error:   # the finding itself: report, never raise
            failure = f'frame {frame}: {_error(error)}'
            break
        per_frame.append(cpu.instructions - before)
    return dict(kind='chain', frames=len(per_frame), failure=failure,
                head=f'{head:08X}', chain_head=f'{(head & 0x3FFFFFF) << 2:08X}' if head >> 26 == 2 else None,
                instructions=dict(first=per_frame[0] if per_frame else 0, last=per_frame[-1] if per_frame else 0,
                                  low=min(per_frame, default=0), high=max(per_frame, default=0)),
                guest_blocks=len(cpu.blocks), regions=len({b & ~0xFFF for b in cpu.blocks}),
                natives=len(cpu.native_calls), **_findings(cpu))


def drive_hooks(context, frames=3, leaders=3, budget=400_000, ram=None):
    """Drive every entry and call hook `frames` times with each of the first `leaders` actors (and 0) as a0.

    Each hook starts at its guest target (the site's word is 'j/jal target'), and every jump or call back into
    the executable is stubbed, including a displaced-prologue continuation of another hook that shares the
    wrapper (buu_ultimate_fanout's UPDATE serves 0x14C970 and 0x15DFD8): the learned continuation gives back
    that prologue's stack. A hook that fails only with a0=0 is counted as 'ok except a0=0' (a native caller
    never passes 0 there)."""
    image = context.ram if ram is None else ram
    sites = hook_sites(image, context.blob, context.segments)
    table = actors(image)[:leaders]
    callers = caller_context()
    counts = collections.Counter(); problems = []
    text_writes, guard_writes = set(), set()
    for site, target, kind, old in sites:
        if kind == 'mid':
            counts['mid (not driven)'] += 1; continue
        outcome, null_only = 'ok', None
        for a0 in table + [0]:
            cpu = context.cpu(image, budget); cpu.stub_sentinel = True
            try:
                for _ in range(frames):
                    if target in callers:
                        cpu.buffer[SCRATCH:SCRATCH + 0x100] = bytes(0x100)
                    registers = {reg: SCRATCH + 0x20 for reg in callers.get(target, ())}
                    cpu.call(target, a0=a0, registers=registers)
            except Exception as error:   # the finding itself
                if a0 == 0:
                    null_only = _error(error)
                else:
                    outcome = _error(error)[:160]; break
            finally:
                text_writes |= {f'{p:08X}<-{pc:08X}' for p, pc in cpu.text_writes}
                guard_writes |= {f'{p:08X}<-{pc:08X}' for p, pc in cpu.guard_writes}
        key = 'ok' if outcome == 'ok' and not null_only else 'ok except a0=0' if outcome == 'ok' else 'failed'
        counts[f'{kind}: {key}'] += 1
        if key == 'failed':
            problems.append(dict(site=f'{site:08X}', target=f'{target:08X}', kind=kind, outcome=outcome))
    return dict(kind='hooks', sites=len(sites), results=dict(counts), failures=problems,
                text_writes=sorted(text_writes)[:20], guard_writes=sorted(guard_writes)[:20])


def fuzz(context, frames=3000, seed=1, max_failures=5):
    """Mutate plausible native scalar fields before each chain frame; restart from the image after a failure."""
    nm = _native()
    records = nm.A(0x333800)
    cpu = context.chain_cpu(); rng = random.Random(seed)
    table = actors(context.ram)
    if not table:
        raise ValueError('The image has no prepared actors (guest actor table is empty)')
    history, failures = [], []
    started = time.monotonic(); frame = -1
    for frame in range(frames):
        for _ in range(rng.randint(0, 3)):
            actor = rng.choice(table); rows = max(1, min(u32(cpu.buffer, actor + ROWS), 5))
            kind = rng.choice(('hp', 'action', 'slot', 'pad', 'ai'))
            slot = min(u32(cpu.buffer, actor + SLOT), 4)
            if kind == 'hp': at, v = actor + HP + ROW_STRIDE * slot, rng.choice((0, 1, rng.randint(-100, 70000)))
            elif kind == 'action': at, v = actor + ACTION, rng.randint(0, 400)
            elif kind == 'slot': at, v = actor + SLOT, rng.randint(0, rows)          # rows = one past the end
            elif kind == 'pad': at, v = records + PAD_STRIDE * rng.randint(0, 3) + PAD_BUTTONS, rng.getrandbits(16)
            else: at, v = actor + AI_WORD, rng.getrandbits(16)
            struct.pack_into('<I', cpu.buffer, at, v & 0xFFFFFFFF); history.append((frame, kind, f'{at:08X}', v))
        try:
            cpu.call(context.hook, a0=context.manager)
        except Exception as error:   # the finding itself
            failures.append(dict(frame=frame, error=_error(error), last=history[-4:]))
            if len(failures) >= max_failures:
                break
            cpu.buffer[:] = context.ram
    return dict(kind='fuzz', seed=seed, frames=frame + 1, seconds=round(time.monotonic() - started, 1),
                instructions=cpu.instructions, mutations=len(history), failures=failures,
                guest_blocks=len(cpu.blocks), natives=len(cpu.native_calls), **_findings(cpu))


# ------------------------------------------------------------------------------------------------ composition

CASES = (('teams', 0), ('teams', 1), ('teams', 2), ('teams', 4), ('ffa', 0), ('ffa', 2), ('ffa', 4),
         ('coop', 2), ('coop', 4), ('training', 1), ('training_coop', 2),
         # (mode, humans, settings): the Outnumbered help installed on top (its hooks then run in every soak).
         ('teams', 1, {'outnumbered_preset': 'strong'}))


def participation_mask(actors_count, mode, humans):
    """Every captured actor takes part; four-human co-op needs the 8-actor seating (None when it cannot)."""
    if mode in ('coop', 'training_coop') and humans == 4:
        return 0x57 if actors_count >= 8 else None
    return (1 << actors_count) - 1


class Fixture:
    """A captured AI-ready preparation folder: 14-ai-ready.bin, ai-installation.json and support.json."""
    def __init__(self, folder):
        self.folder = Path(folder)
        self.source = (self.folder / '14-ai-ready.bin').read_bytes()
        if len(self.source) != RAM_BYTES:
            raise ValueError(f'{self.folder}: 14-ai-ready.bin is not a 128 MiB image')
        self.installation = json.loads((self.folder / 'ai-installation.json').read_text(encoding='utf-8'))
        self.support = json.loads((self.folder / 'support.json').read_text(encoding='utf-8'))
        self.actors = len(self.installation['config']['actors'])
        import battle_mode_policy as policy
        self.capacity = policy.installed_capacity(self.source)


def compose(fixture, mode, humans, mask=None, settings=None, assignment=None):
    """(ram, final manifest) of the prepared match the current builders make on this fixture.

    The same steps as a live preparation's last stage: regenerate the AI program for the chosen plan, build the
    activation, then trainer.final_team_manifest; every block's expected bytes must match the image."""
    import copy
    import battle_mode_policy as policy
    import camera_snapshot
    import fresh_team_ai as ai
    import fresh_team_trainer as trainer
    import team_participation as participation
    from legacy_fixtures import current_loader_fixture
    nm = _native()
    mask = participation_mask(fixture.actors, mode, humans) if mask is None else mask
    if mask is None:
        raise ValueError(f'{mode} with {humans} humans needs at least 8 captured actors')
    with policy.building_for(fixture.capacity):
        ram = bytearray(fixture.source)
        installation = copy.deepcopy(fixture.installation); support = copy.deepcopy(fixture.support)
        config = installation['config']; n = len(config['actors'])
        before = ai.program(n, config['targets'])
        config['targets'] = participation.target_plan(n, mask)
        humans_ids = policy.human_seats(mode, humans, mask, assignment)
        for row in config['actors']:
            i = row['physical_id']; row['cpu'] = i not in humans_ids and bool(mask & (1 << i))
        after = ai.program(n, config['targets'])
        for old, new in zip(before['segments'], after['segments']):
            p = new['address']; old_bytes = bytes.fromhex(old['data_hex']); data = bytes.fromhex(new['data_hex'])
            if ram[p:p + len(old_bytes)] != old_bytes:
                raise ValueError('AI-ready fixture code changed')
            ram[p:p + len(data)] = data
            for entries in support['features'].values():
                for entry in entries:
                    if entry['address'] == p:
                        entry['data_hex'] = new['data_hex']
        # build_activation reads its source through camera_snapshot's published images: serve this one.
        key = str(fixture.folder / 'guest-soak-ai-ready.bin')
        camera_snapshot.publish(key, bytes(ram))
        try:
            activation = ai.build_activation(key, installation, support)
        finally:
            camera_snapshot.retract(key)
        ram = bytearray(current_loader_fixture(bytes(ram)))
        if humans != 1:
            activation['blocks'].append(ai.block(ram, nm.A(0x331DC8) + 36, struct.pack('<I', int(humans >= 2)),
                                                 'Selected views'))
        final = trainer.final_team_manifest(ram, activation, key, play_intro=True, pause_mode='none',
                                            present_mask=mask, battle_mode=mode, humans=humans, settings=settings,
                                            assignment=assignment)
        for block in final['blocks']:
            p = block['address']; data = bytes.fromhex(block['data_hex'])
            if ram[p:p + len(data)].hex() != block['expected_hex']:
                raise ValueError(f'Final guard differs from the captured image at {p:08X}')
            ram[p:p + len(data)] = data
    return bytes(ram), final


def compose_matrix(folders, cases=CASES, frames=60, pieces=False):
    """Compose each case on each fixture and soak the composed image's chain for `frames` frames."""
    rows = []
    for folder in folders:
        fixture = Fixture(folder)
        for mode, humans, *extra in cases:
            settings = extra[0] if extra else None
            row = dict(fixture=fixture.folder.name, actors=fixture.actors, capacity=fixture.capacity,
                       mode=mode, humans=humans, **({'settings': settings} if settings else {}))
            mask = participation_mask(fixture.actors, mode, humans)
            if mask is None:
                rows.append(dict(row, result='skipped: needs 8 or more actors')); continue
            started = time.monotonic()
            try:
                ram, final = compose(fixture, mode, humans, mask, settings=settings)
            except Exception as error:   # the finding itself
                rows.append(dict(row, result=_error(error)[:300])); continue
            row.update(result='composed', blocks=len(final['blocks']), seconds=round(time.monotonic() - started, 1))
            try:
                row['soak'] = chain_soak(Context(ram, pieces=pieces), frames)
            except Exception as error:   # the finding itself
                row['soak'] = dict(failure=_error(error))
            rows.append(row)
    return rows


def problems(report):
    """Every failure or stray write in a report (a chain/hooks/fuzz dict, a matrix row list, or a suite)."""
    found = []
    if isinstance(report, list):
        for row in report:
            if row.get('result') not in ('composed',) and not str(row.get('result', '')).startswith('skipped'):
                found.append(f"compose {row.get('fixture')} {row.get('mode')}/{row.get('humans')}: {row.get('result')}")
            if isinstance(row.get('soak'), dict):
                found += [f"{row['fixture']} {row['mode']}/{row['humans']}: {p}" for p in problems(row['soak'])]
        return found
    if report.get('kind') == 'suite':
        for key in ('chain', 'hooks', 'fuzz'):
            if key in report:
                found += [f'{key}: {p}' for p in problems(report[key])]
        return found
    if report.get('failure'):
        found.append(report['failure'])
    for failure in report.get('failures', ()):
        found.append(json.dumps(failure))
    for key in ('text_writes', 'guard_writes'):
        if report.get(key):
            found.append(f'{key}: {report[key][:5]}')
    return found


# ------------------------------------------------------------------------------------------------ live phase

def expected_game():
    """(serial, PCSX2 CRC) of the selected disc: native_map's, with an installed profile's recorded CRC."""
    nm = _native(); crc = nm.CRC
    try:
        import game_profile
        crc = game_profile.pcsx2_crc()
    except (OSError, ValueError):   # a damaged profile: the adapter's own CRC still names the disc
        pass
    return nm.SERIAL, crc


def game_identity(reader, expect=None):
    """The running game as PINE reports it, checked against `expect` (serial, crc); None for a RAM image."""
    info = getattr(reader, 'info', None)
    if not callable(info):
        return None
    values = info()
    serial, crc = expect or expected_game()
    game = dict(status=values.get('status'), serial=values.get('serial'), crc=values.get('crc'))
    game['matches'] = (game['status'] != 'shutdown' and str(game['serial'] or '').upper() == serial.upper()
                       and str(game['crc'] or '').upper() == crc.upper())
    if not game['matches']:
        game['expected'] = dict(serial=serial, crc=crc)
    return game


def health(reader, expect=None):
    """Guest telemetry of a prepared match from any reader with read(address, size) (image or PINE client).

    A PINE reader is asked for the running game first; when it is not the selected disc (or no game runs),
    only {'game': ...} comes back: that memory belongs to another executable."""
    game = game_identity(reader, expect)
    if game is not None and not game['matches']:
        return dict(game=game)
    import capacity_stage
    import cinematic_policy
    import extra_reload_forms as forms
    import extra_reload_heap
    import guest_loading_screen
    import menu_return
    import stage_debris_guard as debris
    word = lambda p: struct.unpack('<I', reader.read(p, 4))[0]
    out = dict(game=game, loop=word(menu_return.LOOP_FLAG), result_flags=word(menu_return.RESULT_FLAGS),
               reason_flags=word(menu_return.REASON_FLAGS))
    scene = menu_return.read_scene(reader)
    out['scene'] = dict(id=scene.scene, kind=scene.kind, ready=scene.ready, manager=f'{scene.manager:08X}')
    if word(capacity_stage.CONTROL) == capacity_stage.MAGIC:
        out['render'] = dict(packets=word(capacity_stage.CONTROL + 8), heartbeat=word(capacity_stage.CONTROL + 16),
                             counting=word(capacity_stage.CONTROL + 48))
    if word(cinematic_policy.CONTROL) == cinematic_policy.MAGIC:
        out['holds'] = dict(overruns=word(cinematic_policy.CONTROL + cinematic_policy.HOLD_OVERRUNS),
                            longest=word(cinematic_policy.CONTROL + cinematic_policy.HOLD_LONGEST))
    if word(debris.CONTROL) == debris.MAGIC:
        out['debris'] = {name: word(debris.CONTROL + offset) for name, offset in debris.FIELDS.items() if name != 'magic'}
    # extra_reload_forms keeps a cumulative refusal count, the last refusal's reason and its actor.
    out['reload'] = dict(count=word(forms.CONTROL + forms.REFUSALS),
                         last_reason=word(forms.CONTROL + forms.REFUSED_REASON),
                         last_actor=f'{word(forms.CONTROL + forms.REFUSED_ACTOR):08X}',
                         heap_reason=word(extra_reload_heap.REASON))
    stale = [f'{a:08X}' for a, d in guest_loading_screen.code_pieces() if reader.read(a, len(d)) != d]
    out['boot_code'] = dict(current=not stale, differs_at=stale[:8])
    return out


class ImageReader:
    """read(address, size) over a RAM image, the same call a PINE client answers."""
    def __init__(self, ram):
        self.ram = ram

    def read(self, address, size):
        return bytes(self.ram[address:address + size])


class Monitor:
    """Poll health() during a live stress run and record every invariant a sample breaks.

    Invariants: the render heartbeat advances while the loop runs and the emulator is not paused (a stall of
    `freeze_seconds` is a freeze), hold overruns and DBR1 gp repairs never grow, the extra-reload refusal count
    does not grow and the heap reason stays 0, the boot code stays current (one differing read is transient, two
    in a row are stale), and the running game is the selected disc. Each condition is one event when it starts,
    not one per sample; INFORMATIONAL events (edges and recoveries) are not findings."""
    INFORMATIONAL = ('battle loop ended', 'boot code transient', 'boot code current again', 'render resumed',
                     'reads resumed')

    def __init__(self, freeze_seconds=5.0, clock=time.monotonic, expect=None):
        self.freeze_seconds, self.clock, self.expect = freeze_seconds, clock, expect
        self.samples, self.events = [], []
        self.failed_reads = 0
        self._previous = None; self._last_beat = None; self._frozen = False; self._stale = 0
        self._failing = None; self._game = None

    def event(self, t, name, **fields):
        self.events.append(dict(t=t, event=name, **fields))

    def failure(self, error):
        """A sample whose connection or read failed: one event per run of identical failures."""
        text = _error(error)
        self.failed_reads += 1
        if self._failing is None or self._failing[0] != text:
            self.event(round(self.clock(), 3), 'read failed', error=text)
            self._failing = (text, self._failing[1] if self._failing else 0)
        self._failing = (text, self._failing[1] + 1)
        self._last_beat = None; self._frozen = False

    def sample(self, reader):
        now = self.clock(); state = health(reader, self.expect); state['t'] = t = round(now, 3)
        self.samples.append(state)
        if self._failing is not None:
            self.event(t, 'reads resumed', failed=self._failing[1]); self._failing = None
        game = state.get('game')
        if game is not None and not game['matches']:
            key = (game.get('status'), game.get('serial'), game.get('crc'))
            if key != self._game:
                self.event(t, 'no game running' if game.get('status') == 'shutdown' else 'wrong game', game=game)
                self._game = key
            self._last_beat = None; self._frozen = False
            return state
        self._game = None
        previous = self._previous
        render = state.get('render')
        paused = game is not None and game.get('status') == 'paused'
        if render and state['loop'] == 1 and not paused:
            beat = render['heartbeat']
            if self._last_beat is None or beat != self._last_beat[0]:
                if self._frozen:
                    self.event(t, 'render resumed', stalled=round(now - self._last_beat[1], 1))
                self._last_beat = (beat, now); self._frozen = False
            elif not self._frozen and now - self._last_beat[1] >= self.freeze_seconds:
                self.event(t, 'freeze', heartbeat=beat, stalled=round(now - self._last_beat[1], 1))
                self._frozen = True
        else:
            self._last_beat = None; self._frozen = False
        if previous:
            for group, key in (('holds', 'overruns'), ('debris', 'gp_repairs')):
                if state.get(group, {}).get(key, 0) > previous.get(group, {}).get(key, 0):
                    self.event(t, f'{group}.{key} grew', value=state[group][key])
            if previous['loop'] == 1 and state['loop'] == 0:
                self.event(t, 'battle loop ended', scene=state['scene'],
                           result_flags=state['result_flags'], reason_flags=state['reason_flags'])
        reload = state['reload']
        before = previous['reload'] if previous else dict(count=0, heap_reason=0)
        if reload['count'] > before['count'] or (reload['heap_reason'] and reload['heap_reason'] != before['heap_reason']):
            self.event(t, 'extra reload refused', reload=reload, new=max(0, reload['count'] - before['count']))
        if state['boot_code']['current']:
            if self._stale > 1:
                self.event(t, 'boot code current again', stale_samples=self._stale)
            self._stale = 0
        else:
            self._stale += 1
            if self._stale <= 2:
                self.event(t, 'boot code stale' if self._stale == 2 else 'boot code transient',
                           differs_at=state['boot_code']['differs_at'])
        self._previous = state
        return state

    def findings(self):
        """Every event that is a finding (not an edge or a recovery)."""
        return [e for e in self.events if e['event'] not in self.INFORMATIONAL]

    def report(self):
        return dict(samples=len(self.samples), failed_reads=self.failed_reads, events=self.events,
                    first=self.samples[0] if self.samples else None, last=self.samples[-1] if self.samples else None)


# What a lost or changed emulator raises mid-sample: a socket error (OSError), pine.PineError (a RuntimeError:
# the game stopped, PCSX2 closed the connection), a short or malformed reply (ValueError, struct.error).
READ_FAILURES = (OSError, ValueError, RuntimeError, struct.error)


def watch(connect, seconds=60.0, interval=1.0, monitor=None, sleep=time.sleep, clock=time.monotonic):
    """Sample a live match for `seconds`: connect() returns a context-managed reader (pine.PineClient).

    Read-only: nothing is written to the guest. A failed connection or read is recorded and the watch goes on
    (the stress phase wants to see the emulator stop, not a traceback). The samples live in `monitor`, so a
    caller that passes its own keeps them even when the watch is interrupted."""
    monitor = monitor or Monitor(clock=clock)
    end = clock() + seconds
    while clock() < end:
        try:
            with connect() as reader:
                monitor.sample(reader)
        except READ_FAILURES as error:
            monitor.failure(error)
        sleep(interval)
    return monitor.report()


# ------------------------------------------------------------------------------------------------ command line

def suite(ram, *, frames=600, fuzz_frames=300, seed=1, pieces=True):
    context = Context(ram, pieces=pieces)
    started = time.monotonic()
    result = dict(kind='suite', adapter=_native().ADAPTER, chain=chain_soak(context, frames),
                  hooks=drive_hooks(context), fuzz=fuzz(context, fuzz_frames, seed))
    result['seconds'] = round(time.monotonic() - started, 1)
    result['problems'] = problems(result)
    return result


def _kos(text):
    out = {}
    for item in filter(None, (text or '').split(',')):
        frame, index = map(int, item.split(':')); out.setdefault(frame, []).append(index)
    return out


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('command', choices=('soak', 'hooks', 'fuzz', 'compose', 'health', 'suite', 'monitor'))
    parser.add_argument('paths', nargs='*', type=Path, help='images (.p2s/.bin) or, for compose, AI-ready folders')
    parser.add_argument('--root', type=Path, help='game folder whose analysis/ holds the executable')
    parser.add_argument('--frames', type=int)
    parser.add_argument('--fuzz-frames', type=int, default=300)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--ko', help='frame:actor[,frame:actor] knock-outs during soak')
    parser.add_argument('--no-pieces', action='store_true', help='skip the boot-resident code write check')
    parser.add_argument('--json', type=Path, help='write the report here')
    parser.add_argument('--port', type=int, default=28011, help='monitor: the PINE port of the running emulator')
    parser.add_argument('--seconds', type=float, default=60.0, help='monitor: how long to sample')
    parser.add_argument('--interval', type=float, default=1.0, help='monitor: seconds between samples')
    parser.add_argument('--freeze', type=float, default=5.0,
                        help='monitor: seconds without a render heartbeat that count as a freeze')
    parser.add_argument('--crc', help='monitor: the PCSX2 CRC to expect (default: the installed profile, else the adapter)')
    args = parser.parse_args(argv)
    if args.command != 'monitor' and not args.paths:
        parser.error('name at least one image or folder')
    if args.root:
        set_root(args.root)
    pieces = not args.no_pieces
    found = []
    if args.command == 'monitor':
        return _monitor(args)
    if args.command == 'compose':
        output = compose_matrix(args.paths, frames=args.frames or 60, pieces=pieces)
        found += problems(output)
    else:
        output = []
        for path in args.paths:
            ram = load_image(path)
            if args.command == 'health':
                report = health(ImageReader(ram))
            elif args.command == 'suite':
                report = suite(ram, frames=args.frames or 600, fuzz_frames=args.fuzz_frames, seed=args.seed, pieces=pieces)
            else:
                context = Context(ram, pieces=pieces)
                if args.command == 'soak':
                    report = chain_soak(context, args.frames or 600, _kos(args.ko))
                elif args.command == 'hooks':
                    report = drive_hooks(context)
                else:
                    report = fuzz(context, args.frames or 3000, args.seed)
            if args.command != 'health':
                found += problems(report)
            output.append(dict(image=str(path), report=report))
    _write_report(args, output, found)
    return 1 if found else 0


def _write_report(args, output, found, **extra):
    text = json.dumps(dict(adapter=_native().ADAPTER, command=args.command, output=output, problems=found, **extra),
                      indent=1)
    if args.json:
        args.json.write_text(text + '\n', encoding='utf-8')
    print(text[:6000])


def _monitor(args):
    """monitor: sample until --seconds pass or Ctrl+C. The report (every sample and event so far) is written
    whatever ends the watch; an unexpected error is re-raised after it is saved."""
    from pine import PineClient
    monitor = Monitor(freeze_seconds=args.freeze, expect=(_native().SERIAL, args.crc) if args.crc else None)
    ended = 'deadline'
    try:
        watch(lambda: PineClient(port=args.port, timeout=5), args.seconds, args.interval, monitor=monitor)
    except KeyboardInterrupt:
        ended = 'interrupted'
    except BaseException as error:
        ended = f'stopped by {_error(error)}'
        raise
    finally:
        found = [json.dumps(e) for e in monitor.findings()]
        _write_report(args, monitor.report(), found, ended=ended)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
