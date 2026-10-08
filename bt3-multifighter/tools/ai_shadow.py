"""Offline builder for a third fighter's independent, virtualized CPU context.

The JSON contains EE address/data segments, original-byte guards and addresses
for initialization. No emulator writes are performed. See ai_extension.md.
"""
from native_map import A, CRC, GPO, GP_RELATIVE_OPS, SERIAL
from pathlib import Path
import argparse
import json
import struct

from ai_expand import ELF, load_segments, word_at

ROOT = Path(__file__).resolve().parents[1]
GP = 0x304270
AI_GLOBAL = A(GP - 0x5760)
GET_PHYSICAL = A(0x1DC178)
GET_LOGICAL = A(0x1DC1A0)
FRAME_HOOK = A(0x12BC8C)

# Control: active +0, actor pointer +4, shadow-manager pointer +8,
# enabled +12, completed shadow ticks +16, latest input mask +20,
# physical actor2 getter mapping enabled +24. The last flag is independent
# of AI enable and must only be set after the extended scheduler is ready.


class Assembler:
    def __init__(self, base):
        self.base, self.words, self.labels, self.fixups = base, [], {}, []

    @property
    def pc(self):
        return self.base + len(self.words) * 4

    def emit(self, value):
        self.words.append(value)

    def label(self, name):
        self.labels[name] = self.pc

    def mem(self, opcode, rt, rs, immediate):
        if rs == 28 and opcode in GP_RELATIVE_OPS:
            immediate = GPO(immediate)  # the European $gp reaches the same variable at another offset
        self.emit((opcode << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF))

    def addiu(self, rt, rs, immediate):
        self.mem(9, rt, rs, immediate)

    def move(self, rd, rs):
        self.emit((rs << 21) | (rd << 11) | 0x2D)

    def load_address(self, rt, value):
        self.mem(15, rt, 0, value >> 16)
        self.mem(13, rt, rt, value & 0xFFFF)

    def jump(self, target, link=False):
        assert target % 4 == 0 and (target >> 28) == ((self.pc + 4) >> 28)
        self.emit(((3 if link else 2) << 26) | ((target >> 2) & 0x3FFFFFF))

    def branch(self, rs, rt, label, not_equal=False):
        self.fixups.append((len(self.words), label))
        self.emit(((5 if not_equal else 4) << 26) | (rs << 21) | (rt << 16))

    def nop(self):
        self.emit(0)

    def finish(self):
        for index, label in self.fixups:
            delta = (self.labels[label] - (self.base + index * 4 + 4)) // 4
            assert -32768 <= delta <= 32767
            self.words[index] |= delta & 0xFFFF
        return struct.pack("<" + "I" * len(self.words), *self.words)


def getter_stub(base, control, original, displaced):
    """Virtualize logical/physical leader0 only while shadow AI is running."""
    a = Assembler(base)
    if original == GET_PHYSICAL:
        a.addiu(3, 0, 2)
        a.branch(4, 3, "shadow_gate", not_equal=True)
        a.nop()
        a.load_address(3, control)
        a.mem(35, 3, 3, 24)
        a.branch(3, 0, "original")
        a.nop()
        a.load_address(2, 0xB301C)  # prototype mailbox: private actor pointer
        a.mem(35, 2, 2, 0)
        a.emit(0x03E00008)
        a.nop()
        a.label("shadow_gate")
    a.load_address(3, control)       # v1 is overwritten by both originals.
    a.mem(35, 3, 3, 0)            # active flag
    a.branch(3, 0, "original")
    a.nop()
    a.branch(4, 0, "original", not_equal=True)
    a.nop()
    a.load_address(2, control)
    a.mem(35, 2, 2, 4)            # extra actor pointer
    a.emit(0x03E00008)            # jr ra
    a.nop()
    a.label("original")
    for word in displaced:
        a.emit(word)
    a.jump(original + 8)
    a.nop()
    return a.finish()


def frame_stub(base, control):
    a = Assembler(base)
    a.addiu(29, 29, -0x30)
    for register, offset in [(16, 0), (17, 8), (18, 16), (19, 24), (31, 32)]:
        a.mem(63, register, 29, offset)  # sd
    a.load_address(16, control)     # s0 control
    a.mem(35, 17, 28, -0x5760)    # s1 real manager
    a.move(18, 0)                 # s2 previous frame counter
    a.branch(17, 0, "original_tick")
    a.nop()
    a.mem(35, 18, 17, 0xA50)
    a.label("original_tick")
    a.jump(A(0x1BB620), link=True)
    a.nop()
    a.mem(35, 17, 28, -0x5760)
    a.branch(17, 0, "exit")
    a.nop()
    for offset in [12, 4]:        # enabled, extra actor pointer
        a.mem(35, 8, 16, offset)
        a.branch(8, 0, "exit")
        a.nop()
    a.mem(35, 8, 17, 0xA50)
    a.branch(8, 18, "exit")       # preserve all original pause/mode gates
    a.nop()
    a.mem(35, 19, 16, 8)          # s3 shadow manager
    a.branch(19, 0, "exit")
    a.nop()
    a.mem(35, 8, 19, 0x28)       # context0+24 CPU character data
    a.branch(8, 0, "exit")
    a.nop()
    for offset in [0, 8, 0xA50, 0xA58]:  # header, frame counter and shared flags
        a.mem(55, 8, 17, offset)
        a.mem(63, 8, 19, offset)
    # Mirror enemy AI state; own context0 remains private and persistent.
    a.addiu(8, 17, 0x530)
    a.addiu(9, 19, 0x530)
    a.addiu(10, 8, 0x520)
    a.label("copy_enemy")
    a.mem(55, 11, 8, 0)
    a.mem(63, 11, 9, 0)
    a.addiu(8, 8, 8)
    a.branch(8, 10, "copy_enemy", not_equal=True)
    a.addiu(9, 9, 8)
    a.mem(35, 8, 16, 4)          # extra actor
    a.mem(35, 18, 8, 0)          # preserve its physical index in s2
    a.mem(43, 0, 8, 0)           # use virtual leader0 while AI is active
    a.mem(43, 19, 28, -0x5760)
    a.addiu(8, 0, 1)
    a.mem(43, 8, 16, 0)          # active = 1
    a.jump(A(0x1BB510), link=True)   # recompute own/enemy spatial context
    a.nop()
    for target in [A(0x1BFF70), A(0x1BAC30), A(0x1B6BA0), A(0x1B6CD8)]:
        a.jump(target, link=True)
        a.addiu(4, 19, 0x10)
    a.mem(35, 8, 16, 4)
    a.mem(43, 18, 8, 0)          # restore physical index before actor scheduler
    a.mem(43, 0, 16, 0)          # active = 0
    a.mem(43, 17, 28, -0x5760)
    a.mem(35, 8, 16, 16)
    a.addiu(8, 8, 1)
    a.mem(43, 8, 16, 16)
    a.mem(35, 8, 19, 0x278)      # context0+616: last CPU mask
    a.mem(43, 8, 16, 20)
    a.label("exit")
    for register, offset in [(16, 0), (17, 8), (18, 16), (19, 24), (31, 32)]:
        a.mem(55, register, 29, offset)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x30)
    return a.finish()


def initialize_shadow(manager_bytes):
    """Clone an intact normal manager before enabling the wrapper."""
    if len(manager_bytes) != 0xA60:
        raise ValueError("Expected one complete normal AI manager")
    shadow = bytearray(manager_bytes)
    struct.pack_into("<I", shadow, 0x10, 0)   # virtual leader0 context ID
    flags = struct.unpack_from("<I", shadow, 0x34)[0]
    struct.pack_into("<I", shadow, 0x34, flags & ~1)  # borrowed dataset
    return bytes(shadow)


def build(code_base=0xB4000, control_base=0xB4800, shadow_base=0xB4900):
    if code_base % 16 or control_base % 16 or shadow_base % 16:
        raise ValueError("All bases must be 16-byte aligned")
    elf = ELF.read_bytes()
    elf_segments = load_segments(elf)
    expected = {
        GET_PHYSICAL: [0x00041040, (35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x575C) & 0xFFFF)],
        GET_LOGICAL: [(35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x575C) & 0xFFFF), 0x27BDFFE0],
        FRAME_HOOK: [(3 << 26) | (A(0x1BB620) >> 2)],
    }
    for address, words in expected.items():
        for index, word in enumerate(words):
            if word_at(elf, elf_segments, address + 4 * index) != word:
                raise ValueError(f"Original instruction mismatch at {address + 4 * index:08X}")
    physical_stub = code_base
    logical_stub = code_base + 0x100
    tick_stub = code_base + 0x180
    segments = [
        (physical_stub, getter_stub(physical_stub, control_base, GET_PHYSICAL, expected[GET_PHYSICAL])),
        (logical_stub, getter_stub(logical_stub, control_base, GET_LOGICAL, expected[GET_LOGICAL])),
        (tick_stub, frame_stub(tick_stub, control_base)),
        (control_base, struct.pack("<7I", 0, 0, shadow_base, 0, 0, 0, 0)),
    ]
    intervals = sorted((address, address + len(data)) for address, data in segments)
    intervals.append((shadow_base, shadow_base + 0xA60))
    intervals.sort()
    if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
        raise ValueError("Code, control and shadow-manager ranges overlap")
    hooks = []
    for address, target in [(GET_PHYSICAL, physical_stub), (GET_LOGICAL, logical_stub), (FRAME_HOOK, tick_stub)]:
        word = ((3 if address == FRAME_HOOK else 2) << 26) | (target >> 2)
        hooks.append({
            "address": address, "expected_words": expected[address],
            "replacement_words": [word] if address == FRAME_HOOK else [word, 0],
        })
    return {
        "status": "OFFLINE BUILT; EMULATOR EXECUTION UNTESTED",
        "serial": SERIAL, "crc": CRC,
        "control": control_base, "shadow_manager": shadow_base,
        "real_manager_global": AI_GLOBAL,
        "required_code_end": max(address + len(data) for address, data in segments[:3]),
        "segments": [{"address": address, "data_hex": data.hex()} for address, data in segments],
        "hooks": hooks,
        "initialization": [
            "Disable control+12. Require clean original instructions and reserved cave.",
            "Copy initialize_shadow(read(real_manager_global pointer,0xA60)) to shadow_manager.",
            "Set control+4 to valid distinct actor pointer; preserve valid actor+12 resource ID.",
            "Set extra actor+0x1278 CPU-enabled flag to1 before actor update.",
            "Install payload and instruction hooks with EE recompilation invalidated.",
            "Set control+12 to1 to enable. Inspect completed ticks at+16 and CPU mask at+20.",
            "Independently set control+24 to1 only when actor count3/aux state are initialized; this maps physical actor2 to prototype mailbox0xB301C.",
        ],
    }


def build_install(ram_path, code_base=0xB4000, control_base=0xB4800, shadow_base=0xB4900):
    """Prepare the apply_experiment format from an already successful stage1."""
    ram = Path(ram_path).read_bytes()
    if len(ram) != 0x2000000:
        raise ValueError("Expected one complete 32 MiB EE RAM snapshot")
    u32 = lambda address: struct.unpack_from("<I", ram, address)[0]
    manifest = build(code_base, control_base, shadow_base)
    manager = u32(AI_GLOBAL)
    actor = u32(0xB301C)
    if not (0x100000 <= manager < 0x2000000 - 0xA60):
        raise ValueError("Invalid AI manager pointer")
    if not (0x100000 <= actor < 0x2000000 - 0x1600):
        raise ValueError("Stage1 extra actor pointer is missing or invalid")
    if u32(manager + 0x10) != 0 or not u32(manager + 0x28):
        raise ValueError("Expected a valid normal leader0 AI context")
    model_id = u32(actor + 12)
    if model_id >= 12 or not u32(A(0x31C640) + model_id * 4):
        raise ValueError("Extra actor has no initialized model")
    blocks = []

    def append(address, data, label, zero=False):
        expected = ram[address:address + len(data)]
        if len(expected) != len(data):
            raise ValueError("Install block outside EE RAM")
        if zero and any(expected):
            raise ValueError(f"Reserved region is not clear at {address:08X}")
        blocks.append({"address": address, "expected_hex": expected.hex(), "data_hex": data.hex(), "purpose": label})

    for segment in manifest["segments"]:
        address, data = segment["address"], bytes.fromhex(segment["data_hex"])
        if address == control_base:
            data = struct.pack("<7I", 0, actor, shadow_base, 1, 0, 0, 0)
        append(address, data, "shadow AI payload/control", zero=True)
    append(shadow_base, initialize_shadow(ram[manager:manager + 0xA60]), "private independent AI manager", zero=True)
    append(actor + 0x1278, struct.pack("<I", 1), "enable extra actor CPU input consumption")
    for hook in manifest["hooks"]:
        address = hook["address"]
        expected = struct.pack("<" + "I" * len(hook["expected_words"]), *hook["expected_words"])
        if ram[address:address + len(expected)] != expected:
            raise ValueError(f"Hook was already modified at {address:08X}")
        data = struct.pack("<" + "I" * len(hook["replacement_words"]), *hook["replacement_words"])
        append(address, data, "guarded executable hook")
    return {
        "status": "STAGE2 SHADOW AI ONLY; NORMAL ACTOR COUNT STILL2",
        "serial": manifest["serial"], "crc": manifest["crc"],
        "source_ram": str(Path(ram_path).resolve()),
        "extra_actor": actor, "extra_model_id": model_id, "normal_ai_manager": manager,
        "control": control_base, "shadow_manager": shadow_base,
        "blocks": blocks,
        "validation": "Generated hooks passed offline MIPS delay-slot/control-flow tests; live AI still needs evaluation.",
        "note": "Exposure flag remains0. Extra AI writes independent inputs but the normal actor scheduler still needs the separate stage2 actor-count patch.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-base", type=lambda s: int(s, 0), default=0xB4000)
    parser.add_argument("--control-base", type=lambda s: int(s, 0), default=0xB4800)
    parser.add_argument("--shadow-base", type=lambda s: int(s, 0), default=0xB4900)
    parser.add_argument("--ram", type=Path, help="Produce guarded installer blocks from a successful stage1 RAM snapshot")
    parser.add_argument("--out", type=Path, default=ROOT / "analysis" / "ai_shadow.json")
    args = parser.parse_args()
    result = (build_install(args.ram, args.code_base, args.control_base, args.shadow_base)
              if args.ram else build(args.code_base, args.control_base, args.shadow_base))
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.ram:
        print(f"Prepared {len(result['blocks'])} guarded blocks for extra actor {result['extra_actor']:#x}, modelID{result['extra_model_id']}.")
    else:
        print(f"Guarded {len(result['hooks'])} hooks; code ends at {result['required_code_end']:#x}.")
    print(args.out)


if __name__ == "__main__":
    main()
