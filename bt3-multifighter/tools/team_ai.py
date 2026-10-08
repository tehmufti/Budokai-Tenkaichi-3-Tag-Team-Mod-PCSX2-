"""Build offline EE hooks for two independent extra NPCs in a four-actor match.

Requires team_prototype.py mailboxes B3000/B3040 and exposure flag B3088.
This module writes manifests only; it never connects to the emulator.
"""
from native_map import A, CRC, GPO, SERIAL
from pathlib import Path
import argparse
import json
import struct

from ai_shadow import Assembler, AI_GLOBAL, GP, GET_PHYSICAL, GET_LOGICAL, FRAME_HOOK
from ai_expand import ELF, load_segments, word_at

ROOT = Path(__file__).resolve().parents[1]
CODE = 0xBC000
CONTROL = 0xBD000
SHADOWS = (0xBD100, 0xBDC00)
MAILBOXES = (0xB3000, 0xB3040)
EXPOSE = 0xB3088
DESCRIPTORS = (CONTROL + 0x20, CONTROL + 0x40)
PHYSICAL_STUB, LOGICAL_STUB, FRAME_STUB = CODE, CODE + 0x200, CODE + 0x300
ORIGINALS = {
    GET_PHYSICAL: [0x00041040, (35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x575C) & 0xFFFF)],
    GET_LOGICAL: [(35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x575C) & 0xFFFF), 0x27BDFFE0],
    FRAME_HOOK: [(3 << 26) | (A(0x1BB620) >> 2)],
}


def getter_stub(base, original):
    a = Assembler(base)
    if original == GET_PHYSICAL:
        # Permanent mappings remain available during either virtual AI slice.
        for physical, mailbox in zip((2, 3), MAILBOXES):
            a.addiu(3, 0, physical)
            a.branch(4, 3, f"not_{physical}", not_equal=True)
            a.nop()
            a.load_address(3, EXPOSE)
            a.mem(35, 3, 3, 0)
            a.branch(3, 0, "original")
            a.nop()
            a.load_address(2, mailbox + 28)
            a.mem(35, 2, 2, 0)
            a.emit(0x03E00008)
            a.nop()
            a.label(f"not_{physical}")
    a.load_address(3, CONTROL)
    a.mem(35, 2, 3, 0)
    a.branch(2, 0, "original")
    a.nop()
    a.mem(35, 2, 3, 4)
    a.branch(4, 2, "original", not_equal=True)
    a.nop()
    a.mem(35, 2, 3, 8)
    a.emit(0x03E00008)
    a.nop()
    a.label("original")
    for instruction in ORIGINALS[original]:
        a.emit(instruction)
    a.jump(original + 8)
    a.nop()
    return a.finish()


def emit_slice(a, role):
    """s0=alias control, s1=normal manager; own AI context survives every tick."""
    own = 0x10 + 0x520 * role
    enemy = 0x10 + 0x520 * (role ^ 1)
    label = f"slice_{role}_end"
    a.load_address(20, DESCRIPTORS[role])  # s4 descriptor
    for offset in (8, 0, 4):  # enabled, actor, private manager
        a.mem(35, 8, 20, offset)
        a.branch(8, 0, label)
        a.nop()
    a.mem(35, 19, 20, 4)  # s3 shadow
    a.mem(35, 8, 19, own + 24)
    a.branch(8, 0, label)
    a.nop()
    for offset in (0, 8, 0xA50, 0xA58):
        a.mem(55, 8, 17, offset)
        a.mem(63, 8, 19, offset)
    a.addiu(8, 17, enemy)
    a.addiu(9, 19, enemy)
    a.addiu(10, 8, 0x520)
    a.label(f"copy_enemy_{role}")
    a.mem(55, 11, 8, 0)
    a.mem(63, 11, 9, 0)
    a.addiu(8, 8, 8)
    a.branch(8, 10, f"copy_enemy_{role}", not_equal=True)
    a.addiu(9, 9, 8)
    a.mem(35, 8, 20, 0)
    a.mem(35, 21, 8, 0)  # s5 original physical index
    a.addiu(9, 0, role)
    a.mem(43, 9, 8, 0)
    a.mem(43, 9, 16, 4)
    a.mem(43, 8, 16, 8)
    a.mem(43, 19, 28, -0x5760)
    a.addiu(9, 0, 1)
    a.mem(43, 9, 16, 0)
    a.jump(A(0x1BB510), link=True)
    a.nop()
    for target in (A(0x1BFF70), A(0x1BAC30), A(0x1B6BA0), A(0x1B6CD8)):
        a.jump(target, link=True)
        a.addiu(4, 19, own)
    a.mem(35, 8, 20, 0)
    a.mem(43, 21, 8, 0)
    a.mem(43, 0, 16, 0)
    a.mem(43, 0, 16, 8)
    a.mem(43, 17, 28, -0x5760)
    a.mem(35, 8, 20, 12)
    a.addiu(8, 8, 1)
    a.mem(43, 8, 20, 12)
    a.mem(35, 8, 19, own + 0x268)
    a.mem(43, 8, 20, 16)
    a.label(label)


def frame_stub():
    a = Assembler(FRAME_STUB)
    saved = [(register, index * 8) for index, register in enumerate((16, 17, 18, 19, 20, 21, 31))]
    a.addiu(29, 29, -0x40)
    for register, offset in saved:
        a.mem(63, register, 29, offset)
    a.load_address(16, CONTROL)
    a.mem(35, 17, 28, -0x5760)
    a.move(18, 0)
    a.branch(17, 0, "native")
    a.nop()
    a.mem(35, 18, 17, 0xA50)
    a.label("native")
    a.jump(A(0x1BB620), link=True)
    a.nop()
    a.mem(35, 17, 28, -0x5760)
    a.branch(17, 0, "exit")
    a.nop()
    a.mem(35, 8, 17, 0xA50)
    a.branch(8, 18, "exit")
    a.nop()
    a.load_address(8, EXPOSE)
    a.mem(35, 8, 8, 0)
    a.branch(8, 0, "exit")
    a.nop()
    emit_slice(a, 0)
    emit_slice(a, 1)
    a.label("exit")
    for register, offset in saved:
        a.mem(55, register, 29, offset)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x40)
    return a.finish()


def initialize_shadow(manager, role):
    if len(manager) != 0xA60 or role not in (0, 1):
        raise ValueError("Expected normal 0xA60 manager and own virtual role0/1")
    result = bytearray(manager)
    own = 0x10 + role * 0x520
    struct.pack_into("<I", result, own, role)
    flags = struct.unpack_from("<I", result, own + 0x24)[0]
    struct.pack_into("<I", result, own + 0x24, flags & ~1)  # borrowed character dataset
    return bytes(result)


def build():
    elf = ELF.read_bytes()
    segments = load_segments(elf)
    for address, values in ORIGINALS.items():
        for i, value in enumerate(values):
            if word_at(elf, segments, address + i * 4) != value:
                raise ValueError(f"USA original instruction mismatch at {address+i*4:08X}")
    control = bytearray(0x60)
    for role in (0, 1):
        struct.pack_into("<5I", control, DESCRIPTORS[role] - CONTROL, 0, SHADOWS[role], 0, 0, 0)
    payloads = [
        (PHYSICAL_STUB, getter_stub(PHYSICAL_STUB, GET_PHYSICAL)),
        (LOGICAL_STUB, getter_stub(LOGICAL_STUB, GET_LOGICAL)),
        (FRAME_STUB, frame_stub()),
        (CONTROL, bytes(control)),
    ]
    intervals = sorted([(address, address + len(data)) for address, data in payloads]
                       + [(address, address + 0xA60) for address in SHADOWS])
    if any(l[1] > r[0] for l, r in zip(intervals, intervals[1:])):
        raise ValueError("Team AI reserved regions overlap")
    if FRAME_STUB + len(payloads[2][1]) > CODE + 0x1000:
        raise ValueError("Team AI exceeded its code reservation")
    hooks = []
    for address, target in ((GET_PHYSICAL, PHYSICAL_STUB), (GET_LOGICAL, LOGICAL_STUB), (FRAME_HOOK, FRAME_STUB)):
        opcode = 3 if address == FRAME_HOOK else 2
        hooks.append({"address": address, "expected_hex": struct.pack("<"+"I"*len(ORIGINALS[address]), *ORIGINALS[address]).hex(),
                      "data_hex": struct.pack("<I", (opcode << 26) | (target >> 2)).hex() + ("00000000" if opcode == 2 else "")})
    return {"status": "OFFLINE FOUR-ACTOR NPC HOOKS", "serial": SERIAL, "crc": CRC,
            "segments": [{"address": address, "data_hex": data.hex()} for address, data in payloads],
            "hooks": hooks, "control": CONTROL, "descriptors": DESCRIPTORS, "shadows": SHADOWS,
            "exposure": EXPOSE, "code_end": FRAME_STUB + len(payloads[2][1]),
            "layout": "control+0 aliasactive,+4virtualrole,+8currentactor. Each32byte descriptor: actor,manager,enabled,ticks,lastmask."}


def build_install(ram_path):
    ram = Path(ram_path).read_bytes()
    if len(ram) != 0x2000000:
        raise ValueError("Expected complete 32 MiB EE RAM snapshot")
    u32 = lambda address: struct.unpack_from("<I", ram, address)[0]
    if u32(0xB3084) != 2 or u32(0xB3098) != 5 or any(u32(mailbox) != 5 for mailbox in MAILBOXES):
        raise ValueError("Team stage1 must finish both extra actors successfully")
    manager = u32(AI_GLOBAL)
    if not 0x100000 <= manager < len(ram) - 0xA60:
        raise ValueError("Invalid normal AI manager")
    actors = tuple(u32(mailbox + 28) for mailbox in MAILBOXES)
    if actors[0] == actors[1] or any(not 0x100000 <= actor < len(ram) - 0x1600 for actor in actors):
        raise ValueError("Two distinct initialized extra actors are required")
    model_ids = []
    for role, actor in enumerate(actors):
        if u32(manager + 0x10 + role * 0x520) != role or not u32(manager + 0x28 + role * 0x520):
            raise ValueError(f"Missing normal role{role} character AI dataset")
        model_id = u32(actor + 12)
        model_ids.append(model_id)
        if model_id not in (2, 3) or not u32(A(0x31C640) + model_id * 4):
            raise ValueError(f"Extra actor{role+2} has no valid model")
        if u32(actor) not in (role, role + 2):
            raise ValueError(f"Extra actor{role+2} physical role is inconsistent")
    if set(model_ids) != {2, 3}:
        raise ValueError("Extra actors must use distinct model slots2/3")
    manifest, blocks = build(), []

    def append(address, data, purpose, zero=False):
        expected = ram[address:address+len(data)]
        if len(expected) != len(data) or (zero and any(expected)):
            raise ValueError(f"Unavailable reserved memory at {address:08X}")
        blocks.append({"address": address, "expected_hex": expected.hex(), "data_hex": data.hex(), "purpose": purpose})

    for segment in manifest["segments"]:
        address, data = segment["address"], bytes.fromhex(segment["data_hex"])
        if address == CONTROL:
            data = bytearray(data)
            for role in (0, 1):
                struct.pack_into("<5I", data, DESCRIPTORS[role]-CONTROL, actors[role], SHADOWS[role], 1, 0, 0)
            data = bytes(data)
        append(address, data, "four-actor AI code/control", zero=True)
    for role, actor in enumerate(actors):
        append(SHADOWS[role], initialize_shadow(ram[manager:manager+0xA60], role), f"extra{role+2} independent CPU context", zero=True)
        append(actor + 0x1278, struct.pack("<I", 1), f"extra{role+2} CPU input enabled")
    for hook in manifest["hooks"]:
        expected = bytes.fromhex(hook["expected_hex"])
        if ram[hook["address"]:hook["address"]+len(expected)] != expected:
            raise ValueError(f"Original hook already modified at {hook['address']:08X}")
        append(hook["address"], bytes.fromhex(hook["data_hex"]), "guarded executable hook")
    return {"status": "FOUR-ACTOR AI INSTALLER; REQUIRES SEPARATE COUNT/AUX/COLLISION EXPOSURE",
            "serial": SERIAL, "crc": CRC, "source_ram": str(Path(ram_path).resolve()),
            "actors": actors, "normal_manager": manager, "control": CONTROL, "descriptors": DESCRIPTORS,
            "shadows": SHADOWS, "blocks": blocks,
            "note": "Native leader CPUs run unchanged. Extra2 targets leader1; extra3 targets leader0. Shared B3088 exposure gate is owned by team_prototype.py."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ram", type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "analysis" / "team_ai.json")
    args = p.parse_args()
    result = build_install(args.ram) if args.ram else build()
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
