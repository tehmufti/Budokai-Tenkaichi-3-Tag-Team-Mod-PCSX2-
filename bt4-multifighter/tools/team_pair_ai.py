"""Offline upgrade: four private NPC contexts with fixed reciprocal opponents.

Pairs are physical0<->3 and1<->2. Uses team_targets.py C1000 target table and
C1020 enable flag. Existing team_ai.py code remains intact as a disabled-mode
fallback. No emulator connections or writes are performed.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

from ai_shadow import Assembler, AI_GLOBAL, GET_PHYSICAL, GET_LOGICAL, FRAME_HOOK
from team_ai import (PHYSICAL_STUB as OLD_PHYSICAL, LOGICAL_STUB as OLD_LOGICAL,
                     FRAME_STUB as OLD_FRAME, SHADOWS as OLD_SHADOWS,
                     initialize_shadow)

ROOT = Path(__file__).resolve().parents[1]
CODE, CONTROL = 0xC2000, 0xC4000
PHYSICAL_STUB, LOGICAL_STUB, FRAME_STUB = CODE, CODE + 0x100, CODE + 0x200
DESCRIPTORS = tuple(CONTROL + 0x40 + i * 0x20 for i in range(4))
SHADOWS = (0xC5000, 0xC6000, 0xC7000, 0xC8000)
PAIRS = (3, 2, 1, 0)
EXPOSURE, TARGET_ENABLED = 0xB3088, 0xC1020
ACTOR_GLOBAL, ACTOR_HEADER = A(0x2FEB14), 0xB308C


def getter_stub(base, fallback):
    a = Assembler(base)
    a.load_address(3, CONTROL)
    a.mem(35, 2, 3, 4)
    a.branch(2, 0, "fallback")
    a.nop()
    a.branch(4, 0, "role0")
    a.nop()
    a.addiu(2, 0, 1)
    a.branch(4, 2, "fallback", not_equal=True)
    a.nop()
    a.mem(35, 2, 3, 12)
    a.emit(0x03E00008)
    a.nop()
    a.label("role0")
    a.mem(35, 2, 3, 8)
    a.emit(0x03E00008)
    a.nop()
    a.label("fallback")
    a.jump(fallback)
    a.nop()
    return a.finish()


def emit_slice(a, physical):
    role, enemy_physical = physical & 1, PAIRS[physical]
    own, enemy = 0x10 + role * 0x520, 0x10 + (role ^ 1) * 0x520
    end = f"slice{physical}_end"
    a.load_address(19, DESCRIPTORS[physical])  # s3 own descriptor
    a.mem(35, 21, 19, 0)  # s5 own actor
    a.branch(21, 0, end)
    a.nop()
    a.mem(35, 8, 21, 0x1278)
    a.branch(8, 0, end)  # Human-controlled leaders retain human input.
    a.nop()
    a.mem(35, 20, 19, 4)  # s4 own manager
    a.branch(20, 0, end)
    a.nop()
    a.mem(35, 8, 20, own + 24)
    a.branch(8, 0, end)
    a.nop()
    a.load_address(8, DESCRIPTORS[enemy_physical])
    a.mem(35, 22, 8, 0)  # s6 selected enemy actor
    a.branch(22, 0, end)
    a.nop()
    a.mem(35, 23, 8, 4)  # s7 enemy private manager
    a.branch(23, 0, end)
    a.nop()
    for offset in (0, 8, 0xA50, 0xA58):
        a.mem(55, 8, 17, offset)
        a.mem(63, 8, 20, offset)
    # Enemy own context has the opposite team role and lands in that same
    # virtual slot here. Copying it never overwrites the persistent own slot.
    a.addiu(8, 23, enemy)
    a.addiu(9, 20, enemy)
    a.addiu(10, 8, 0x520)
    a.label(f"copy{physical}")
    a.mem(55, 11, 8, 0)
    a.mem(63, 11, 9, 0)
    a.addiu(8, 8, 8)
    a.branch(8, 10, f"copy{physical}", not_equal=True)
    a.addiu(9, 9, 8)
    a.mem(35, 8, 21, 0)
    a.mem(43, 8, 29, 0x50)
    a.mem(35, 8, 22, 0)
    a.mem(43, 8, 29, 0x54)
    a.addiu(8, 0, role)
    a.mem(43, 8, 21, 0)
    a.addiu(8, 0, role ^ 1)
    a.mem(43, 8, 22, 0)
    a.mem(43, 21, 16, 8 + role * 4)
    a.mem(43, 22, 16, 8 + (role ^ 1) * 4)
    a.addiu(8, 0, physical)
    a.mem(43, 8, 16, 16 + role * 4)
    a.addiu(8, 0, enemy_physical)
    a.mem(43, 8, 16, 16 + (role ^ 1) * 4)
    a.mem(43, 20, 28, -0x5760)
    a.addiu(8, 0, 1)
    a.mem(43, 8, 16, 4)
    a.jump(A(0x1BB510), link=True)
    a.nop()
    for target in (A(0x1BFF70), A(0x1BAC30), A(0x1B6BA0), A(0x1B6CD8)):
        a.jump(target, link=True)
        a.addiu(4, 20, own)
    a.mem(35, 8, 29, 0x50)
    a.mem(43, 8, 21, 0)
    a.mem(35, 8, 29, 0x54)
    a.mem(43, 8, 22, 0)
    a.mem(43, 0, 16, 4)
    a.mem(43, 0, 16, 8)
    a.mem(43, 0, 16, 12)
    a.mem(43, 17, 28, -0x5760)
    a.mem(35, 8, 19, 12)
    a.addiu(8, 8, 1)
    a.mem(43, 8, 19, 12)
    a.mem(35, 8, 20, own + 0x268)
    a.mem(43, 8, 19, 16)
    a.label(end)


def frame_stub():
    a = Assembler(FRAME_STUB)
    for address in (CONTROL, EXPOSURE, TARGET_ENABLED):
        a.load_address(2, address)
        a.mem(35, 2, 2, 0)
        a.branch(2, 0, "fallback")
        a.nop()
    a.load_address(2, ACTOR_HEADER)
    a.mem(35, 2, 2, 0)
    a.mem(35, 3, 28, -22364)
    a.branch(2, 3, "fallback", not_equal=True)
    a.nop()
    a.branch(3, 0, "fallback")
    a.nop()
    a.addiu(29, 29, -0x60)
    saved = [(16 + i, i * 8) for i in range(8)] + [(31, 0x40)]
    for register, offset in saved:
        a.mem(63, register, 29, offset)
    a.load_address(16, CONTROL)
    a.mem(35, 17, 28, -0x5760)
    a.branch(17, 0, "exit")
    a.nop()
    a.mem(35, 18, 17, 0xA50)
    a.load_address(8, DESCRIPTORS[0])
    a.mem(35, 21, 8, 0)
    a.load_address(8, DESCRIPTORS[1])
    a.mem(35, 22, 8, 0)
    a.branch(21, 0, "exit")
    a.nop()
    a.branch(22, 0, "exit")
    a.nop()
    # Retain native pause/mode/frame gates without ticking leader CPUs twice.
    # The only native CPU eligibility check reads these actor fields.
    for reg, offset in ((21, 0x48), (22, 0x4C)):
        a.mem(35, 8, reg, 0x1278)
        a.mem(43, 8, 29, offset)
        a.mem(43, 0, reg, 0x1278)
    a.jump(A(0x1BB620), link=True)
    a.nop()
    for reg, offset in ((21, 0x48), (22, 0x4C)):
        a.mem(35, 8, 29, offset)
        a.mem(43, 8, reg, 0x1278)
    a.mem(35, 8, 17, 0xA50)
    a.branch(8, 18, "exit")
    a.nop()
    for physical in range(4):
        emit_slice(a, physical)
    a.mem(35, 8, 16, 0x1C)
    a.addiu(8, 8, 1)
    a.mem(43, 8, 16, 0x1C)
    a.label("exit")
    for register, offset in saved:
        a.mem(55, register, 29, offset)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x60)
    a.label("fallback")
    a.jump(OLD_FRAME)
    a.nop()
    return a.finish()


def build():
    control = bytearray(0xC0)
    for i in range(4):
        struct.pack_into("<8I", control, DESCRIPTORS[i] - CONTROL,
                         0, SHADOWS[i], i & 1, 0, 0, i, DESCRIPTORS[PAIRS[i]], 0)
    payloads = [(PHYSICAL_STUB, getter_stub(PHYSICAL_STUB, OLD_PHYSICAL)),
                (LOGICAL_STUB, getter_stub(LOGICAL_STUB, OLD_LOGICAL)),
                (FRAME_STUB, frame_stub()), (CONTROL, bytes(control))]
    spans = sorted([(a, a + len(d)) for a, d in payloads] + [(a, a+0xA60) for a in SHADOWS])
    if any(l[1] > r[0] for l, r in zip(spans, spans[1:])):
        raise ValueError("Pair AI memory reservations overlap")
    if FRAME_STUB + len(payloads[2][1]) > CODE + 0x2000:
        raise ValueError("Pair AI code exceeds its reservation")
    hooks = []
    for entry, old, new in ((GET_PHYSICAL, OLD_PHYSICAL, PHYSICAL_STUB),
                            (GET_LOGICAL, OLD_LOGICAL, LOGICAL_STUB),
                            (FRAME_HOOK, OLD_FRAME, FRAME_STUB)):
        op = 3 if entry == FRAME_HOOK else 2
        extra = [] if op == 3 else [0]
        hooks.append({"address": entry,
                      "expected_hex": struct.pack("<"+"I"*(1+len(extra)), (op << 26) | (old >> 2), *extra).hex(),
                      "data_hex": struct.pack("<"+"I"*(1+len(extra)), (op << 26) | (new >> 2), *extra).hex()})
    return {"status": "OFFLINE FOUR-CPU RECIPROCAL TARGET UPGRADE", "serial": SERIAL, "crc": CRC,
            "segments": [{"address": a, "data_hex": d.hex()} for a, d in payloads], "hooks": hooks,
            "control": CONTROL, "descriptors": DESCRIPTORS, "shadows": SHADOWS, "pairs": PAIRS,
            "code_end": FRAME_STUB + len(payloads[2][1]), "target_enabled": TARGET_ENABLED,
            "control_fields": {"enabled": 0, "alias_active": 4, "virtual0_actor": 8, "virtual1_actor": 12,
                               "virtual0_physical_id": 16, "virtual1_physical_id": 20, "completed_frames": 28},
            "descriptor_fields": {"actor": 0, "manager": 4, "virtual_role": 8, "completed_ticks": 12,
                                  "last_mask": 16, "physical_id": 20, "enemy_descriptor": 24},
            "scope": "Human actors skip CPU slices. Both actors in each AI pair temporarily use virtual team IDs0/1; all identities/globals restore before actor and camera updates."}


def build_install(ram_path):
    ram = Path(ram_path).read_bytes()
    if len(ram) != 0x2000000:
        raise ValueError("Expected full32 MiB EE RAM")
    u32 = lambda address: struct.unpack_from("<I", ram, address)[0]
    manager, actor_manager = u32(AI_GLOBAL), u32(ACTOR_GLOBAL)
    if not (0x100000 <= manager < len(ram)-0xA60 and actor_manager == u32(ACTOR_HEADER)):
        raise ValueError("Team AI/actor managers are missing or changed")
    if not u32(EXPOSURE) or u32(0xBD000):
        raise ValueError("Require exposed team paused outside an old AI alias slice")
    actors = (u32(actor_manager + 4), u32(actor_manager + 4) + 0x1600,
              u32(0xB301C), u32(0xB305C))
    if len(set(actors)) != 4 or any(not 0x100000 <= a < len(ram)-0x1600 for a in actors):
        raise ValueError("Four distinct valid actor allocations are required")
    sources = (manager, manager, *OLD_SHADOWS)
    for i, actor in enumerate(actors):
        own = 0x10 + (i & 1) * 0x520
        if u32(actor) != i or u32(sources[i]+own) != (i & 1) or not u32(sources[i]+own+24):
            raise ValueError(f"Invalid physical/virtual actor{i} state")
    manifest, blocks = build(), []
    def append(address, data, purpose, zero=False):
        old = ram[address:address+len(data)]
        if len(old) != len(data) or (zero and any(old)):
            raise ValueError(f"Unavailable pair AI memory at{address:08X}")
        blocks.append({"address": address, "expected_hex": old.hex(), "data_hex": data.hex(), "purpose": purpose})
    for segment in manifest["segments"]:
        address, data = segment["address"], bytes.fromhex(segment["data_hex"])
        if address == CONTROL:
            data = bytearray(data)
            struct.pack_into("<I", data, 0, 1)
            for i, actor in enumerate(actors):
                struct.pack_into("<I", data, DESCRIPTORS[i]-CONTROL, actor)
            data = bytes(data)
        append(address, data, "reciprocal pair AI code/control", zero=True)
    for i, source in enumerate(sources):
        append(SHADOWS[i], initialize_shadow(ram[source:source+0xA60], i & 1), f"persistent private actor{i} AI", zero=True)
    for hook in manifest["hooks"]:
        address, expected = hook["address"], bytes.fromhex(hook["expected_hex"])
        if ram[address:address+len(expected)] != expected:
            raise ValueError(f"Expected previous team AI hook at{address:08X}")
        append(address, bytes.fromhex(hook["data_hex"]), "upgrade old team AI hook")
    return {**{k: v for k, v in manifest.items() if k not in ("segments", "hooks")},
            "source_ram": str(Path(ram_path).resolve()), "actors": actors,
            "normal_manager": manager, "blocks": blocks,
            "requirements": ["Install matching team_targets.py fixedtable[3,2,1,0] and reciprocal collision pairs.",
                             "Apply paused and save/reload to invalidate EE code.",
                             "Original team_ai payload remains available when C4000 or C1020 is disabled."]}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ram", type=Path)
    p.add_argument("--out", type=Path, default=ROOT/"analysis"/"team-pair-ai.json")
    args = p.parse_args()
    result = build_install(args.ram) if args.ram else build()
    args.out.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(f"{args.out}: code ends at{result['code_end']:08X}")
