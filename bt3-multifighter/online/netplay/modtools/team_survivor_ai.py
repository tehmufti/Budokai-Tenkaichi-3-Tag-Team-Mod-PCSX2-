"""Offline four-fighter survivor targeting using the existing private AI contexts.

An actor keeps its current living enemy. After that enemy is defeated, it
selects the other opposing survivor once native deferred damage has drained.
No camera ownership or model identities are changed. Requires the pair-local
geometry resolver upgrade for safe many-to-one CPU slices.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

from ai_shadow import Assembler, AI_GLOBAL, FRAME_HOOK
import team_pair_ai as pair

ROOT = Path(__file__).resolve().parents[1]
PICKER, FRAME, CONTROL = 0xF0000, 0xF0800, 0xF7000
TARGETS = 0xC1000
# enable, frames, alive mask, target changes, deferred retarget checks
DEFERRED_DAMAGE = (3480, 3500, 3512)


def picker_stub():
    a = Assembler(PICKER)
    a.addiu(29, 29, -0x30)
    for reg, off in ((16, 0), (17, 8), (18, 16), (19, 24), (31, 32)):
        a.mem(63, reg, 29, off)
    a.load_address(16, CONTROL)
    a.move(17, 0)  # s1 alive bitset
    for physical in range(4):
        a.load_address(8, pair.DESCRIPTORS[physical])
        a.mem(35, 4, 8, 0)
        a.branch(4, 0, f"dead{physical}")
        a.nop()
        a.jump(A(0x1DC320), link=True)
        a.nop()
        a.branch(2, 0, f"dead{physical}", not_equal=True)
        a.nop()
        a.mem(13, 17, 17, 1 << physical)
        a.label(f"dead{physical}")
    a.mem(43, 17, 16, 8)
    for physical in range(4):
        enemies = (1, 3) if not physical & 1 else (0, 2)
        preferred = pair.PAIRS[physical]
        alternate = next(i for i in enemies if i != preferred)
        a.load_address(18, pair.DESCRIPTORS[physical])
        a.mem(35, 19, 18, 0)
        a.load_address(8, TARGETS + physical * 4)
        a.mem(35, 9, 8, 0)  # previous physical target
        a.move(10, 9)  # candidate, initially unchanged
        for target in enemies:
            a.addiu(11, 0, target)
            a.branch(9, 11, f"current{physical}_{target}")
            a.nop()
        a.branch(0, 0, f"choose{physical}")
        a.nop()
        for target in enemies:
            a.label(f"current{physical}_{target}")
            a.mem(12, 11, 17, 1 << target)
            a.branch(11, 0, f"store{physical}", not_equal=True)
            a.nop()
            a.branch(19, 0, f"choose{physical}")
            a.nop()
            # 1CF220 looks up the current opponent every deferred-damage tick.
            # Keep that opponent until pending HP/absorption/ki totals drain.
            for offset in DEFERRED_DAMAGE:
                a.mem(35, 11, 19, offset)
                a.branch(11, 0, f"deferred{physical}", not_equal=True)
                a.nop()
            a.branch(0, 0, f"choose{physical}")
            a.nop()
        a.label(f"choose{physical}")
        a.addiu(10, 0, preferred)
        a.mem(12, 11, 17, 1 << preferred)
        a.branch(11, 0, f"store{physical}", not_equal=True)
        a.nop()
        a.mem(12, 11, 17, 1 << alternate)
        a.branch(11, 0, f"store{physical}")
        a.nop()
        a.addiu(10, 0, alternate)
        a.branch(0, 0, f"store{physical}")
        a.nop()
        a.label(f"deferred{physical}")
        a.mem(35, 11, 16, 16)
        a.addiu(11, 11, 1)
        a.mem(43, 11, 16, 16)
        a.label(f"store{physical}")
        a.branch(10, 9, f"unchanged{physical}")
        a.nop()
        a.mem(35, 11, 16, 12)
        a.addiu(11, 11, 1)
        a.mem(43, 11, 16, 12)
        a.label(f"unchanged{physical}")
        a.mem(43, 10, 8, 0)
        a.emit((10 << 16) | (11 << 11) | (5 << 6))  # sll t3,target,5
        a.load_address(12, pair.DESCRIPTORS[0])
        a.emit((11 << 21) | (12 << 16) | (11 << 11) | 0x2D)
        a.mem(43, 11, 18, 24)
    for reg, off in ((16, 0), (17, 8), (18, 16), (19, 24), (31, 32)):
        a.mem(55, reg, 29, off)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x30)
    data = a.finish()
    if PICKER + len(data) > FRAME:
        raise ValueError("Survivor picker exceeds reservation")
    return data


def emit_slice(a, physical):
    role = physical & 1
    own, enemy = 0x10 + role * 0x520, 0x10 + (role ^ 1) * 0x520
    end, clear = f"slice{physical}_end", f"slice{physical}_clear"
    a.load_address(19, pair.DESCRIPTORS[physical])
    a.mem(35, 21, 19, 0)
    a.branch(21, 0, end)
    a.nop()
    a.mem(35, 8, 21, 0x1278)
    a.branch(8, 0, end)  # Human input is untouched.
    a.nop()
    a.load_address(8, CONTROL)
    a.mem(35, 8, 8, 8)
    a.mem(12, 9, 8, 1 << physical)
    a.branch(9, 0, clear)
    a.nop()
    a.mem(35, 20, 19, 4)
    a.branch(20, 0, clear)
    a.nop()
    a.mem(35, 9, 20, own + 24)
    a.branch(9, 0, clear)
    a.nop()
    a.mem(35, 9, 19, 24)  # Dynamic target descriptor chosen by picker.
    a.mem(35, 22, 9, 0)
    a.branch(22, 0, clear)
    a.nop()
    a.mem(35, 10, 9, 20)  # Target's actual physical ID.
    a.addiu(11, 0, 1)
    a.emit((10 << 21) | (11 << 16) | (11 << 11) | 4)  # sllv t3,1,target
    a.emit((8 << 21) | (11 << 16) | (11 << 11) | 0x24)  # and t3,alive,bit
    a.branch(11, 0, clear)
    a.nop()
    a.mem(35, 23, 9, 4)
    a.branch(23, 0, clear)
    a.nop()
    for offset in (0, 8, 0xA50, 0xA58):
        a.mem(55, 8, 17, offset)
        a.mem(63, 8, 20, offset)
    a.addiu(8, 23, enemy)
    a.addiu(9, 20, enemy)
    a.addiu(10, 8, 0x520)
    a.label(f"copy{physical}")
    a.mem(55, 11, 8, 0)
    a.mem(63, 11, 9, 0)
    a.addiu(8, 8, 8)
    a.branch(8, 10, f"copy{physical}", not_equal=True)
    a.addiu(9, 9, 8)
    for reg, offset in ((21, 0x50), (22, 0x54)):
        a.mem(35, 8, reg, 0)
        a.mem(43, 8, 29, offset)
    a.addiu(8, 0, role)
    a.mem(43, 8, 21, 0)
    a.addiu(8, 0, role ^ 1)
    a.mem(43, 8, 22, 0)
    a.mem(43, 21, 16, 8 + role * 4)
    a.mem(43, 22, 16, 8 + (role ^ 1) * 4)
    a.mem(35, 8, 29, 0x50)
    a.mem(43, 8, 16, 16 + role * 4)
    a.mem(35, 8, 29, 0x54)
    a.mem(43, 8, 16, 16 + (role ^ 1) * 4)
    a.mem(43, 20, 28, -0x5760)
    a.addiu(8, 0, 1)
    a.mem(43, 8, 16, 4)
    a.jump(A(0x1BB510), link=True)
    a.nop()
    for target in (A(0x1BFF70), A(0x1BAC30), A(0x1B6BA0), A(0x1B6CD8)):
        a.jump(target, link=True)
        a.addiu(4, 20, own)
    for reg, offset in ((21, 0x50), (22, 0x54)):
        a.mem(35, 8, 29, offset)
        a.mem(43, 8, reg, 0)
    a.mem(43, 0, 16, 4)
    a.mem(43, 0, 16, 8)
    a.mem(43, 0, 16, 12)
    a.mem(43, 17, 28, -0x5760)
    a.mem(35, 8, 19, 12)
    a.addiu(8, 8, 1)
    a.mem(43, 8, 19, 12)
    a.mem(35, 8, 20, own + 0x268)
    a.mem(43, 8, 19, 16)
    a.branch(0, 0, end)
    a.nop()
    a.label(clear)
    for offset in (0x127C, 0x1280, 0x1284):
        a.mem(43, 0, 21, offset)
    a.mem(43, 0, 19, 16)
    a.label(end)


def frame_stub():
    a = Assembler(FRAME)
    for address in (CONTROL, pair.CONTROL, pair.EXPOSURE, pair.TARGET_ENABLED):
        a.load_address(2, address)
        a.mem(35, 2, 2, 0)
        a.branch(2, 0, "fallback")
        a.nop()
    a.load_address(2, pair.ACTOR_HEADER)
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
    a.load_address(16, pair.CONTROL)
    a.mem(35, 17, 28, -0x5760)
    a.branch(17, 0, "exit")
    a.nop()
    a.mem(35, 18, 17, 0xA50)
    for reg, descriptor in ((21, pair.DESCRIPTORS[0]), (22, pair.DESCRIPTORS[1])):
        a.load_address(8, descriptor)
        a.mem(35, reg, 8, 0)
        a.branch(reg, 0, "exit")
        a.nop()
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
    a.jump(PICKER, link=True)
    a.nop()
    for physical in range(4):
        emit_slice(a, physical)
    for base in (pair.CONTROL, CONTROL):
        a.load_address(9, base)
        offset = 0x1C if base == pair.CONTROL else 4
        a.mem(35, 8, 9, offset)
        a.addiu(8, 8, 1)
        a.mem(43, 8, 9, offset)
    a.label("exit")
    for register, offset in saved:
        a.mem(55, register, 29, offset)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x60)
    a.label("fallback")
    # Old pair AI has compile-time reciprocal pairs, so restore that table
    # before using it. These private tables remain mapped during teardown.
    for physical, target in enumerate(pair.PAIRS):
        a.load_address(2, TARGETS + physical * 4)
        a.addiu(3, 0, target)
        a.mem(43, 3, 2, 0)
        a.load_address(2, pair.DESCRIPTORS[physical])
        a.load_address(3, pair.DESCRIPTORS[target])
        a.mem(43, 3, 2, 24)
    a.jump(pair.FRAME_STUB)
    a.nop()
    return a.finish()


def build():
    payloads = ((PICKER, picker_stub()), (FRAME, frame_stub()),
                (CONTROL, struct.pack("<8I", 1, 0, 0, 0, 0, 0, 0, 0)))
    if FRAME + len(payloads[1][1]) >= CONTROL:
        raise ValueError("Survivor frame code overlaps control")
    hook = {"address": FRAME_HOOK,
            "expected_hex": struct.pack("<I", (3 << 26) | (pair.FRAME_STUB >> 2)).hex(),
            "data_hex": struct.pack("<I", (3 << 26) | (FRAME >> 2)).hex()}
    return {"status": "OFFLINE FOUR-FIGHTER SURVIVOR AI; LIVE VALIDATION REQUIRED",
            "serial": SERIAL, "crc": CRC, "segments": [{"address": p, "data_hex": b.hex()} for p, b in payloads],
            "hooks": [hook], "code_end": FRAME + len(payloads[1][1]), "control": CONTROL,
            "control_fields": {"enabled": 0, "completed_frames": 4, "alive_mask": 8,
                               "target_changes": 12, "deferred_retarget_checks": 16},
            "requirements": ["Four existing pair AI contexts and target table at C1000/C4000.",
                             "Install target_pair_local.py resolver override for many-to-one virtual CPU slices.",
                             "Install KO/tag preservation guards to retain actors and borrowed model resources.",
                             "Save/reload after guarded code changes to invalidate EE caches."],
            "behavior": "Keep each living target; switch to the other opposing survivor only after native deferred damage drains. Skip dead NPCs and NPCs without living targets. Human input and camera ownership are unchanged.",
            "limitations": ["Four actors with parity teams only; no general twelve-actor scheduler.",
                            "No end-of-round announcement or victory transition; defeated teams remain in native KO states.",
                            "Pending HP/absorption/ki damage delays retargeting; outstanding projectiles and cinematics require live verification.",
                            "Disabling F7000 restores the fixed reciprocal target table before falling back to the old pair AI."]}


def build_install(ram_path):
    ram = Path(ram_path).read_bytes()
    if len(ram) not in (0x2000000, 0x8000000):
        raise ValueError("Expected complete 32 or128 MiB EE RAM")
    u = lambda p: struct.unpack_from("<I", ram, p)[0]
    if not u(pair.EXPOSURE) or not u(pair.CONTROL) or u(pair.CONTROL + 4):
        raise ValueError("Requires intact exposed pair AI checkpoint outside a virtual slice")
    if not u(pair.TARGET_ENABLED) or u(pair.ACTOR_HEADER) != u(pair.ACTOR_GLOBAL):
        raise ValueError("Target mode or actor manager mismatch")
    for physical, descriptor in enumerate(pair.DESCRIPTORS):
        actor, manager = u(descriptor), u(descriptor + 4)
        if not (0x100000 <= actor < len(ram) - 0x1600) or u(actor) != physical:
            raise ValueError(f"Invalid actor{physical}; restore before roster replacement")
        if manager != pair.SHADOWS[physical] or not u(manager + 0x10 + (physical & 1) * 0x520 + 24):
            raise ValueError(f"Missing private AI for actor{physical}")
    manifest, blocks = build(), []
    for segment in manifest["segments"]:
        address, data = segment["address"], bytes.fromhex(segment["data_hex"])
        old = ram[address:address + len(data)]
        if any(old):
            raise ValueError(f"Occupied survivor code/control at{address:08X}")
        blocks.append({"address": address, "expected_hex": old.hex(), "data_hex": data.hex(), "purpose": "Survivor targeting/frame code and control"})
    for hook in manifest["hooks"]:
        address, expected = hook["address"], bytes.fromhex(hook["expected_hex"])
        if ram[address:address + len(expected)] != expected:
            raise ValueError("Requires current reciprocal pair AI frame hook")
        blocks.append({**hook, "purpose": "Upgrade pair AI to dynamic survivor targets"})
    return {**manifest, "source_ram": str(Path(ram_path).resolve()), "blocks": blocks}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ram", type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "analysis" / "team-survivor-ai.json")
    args = p.parse_args()
    result = build_install(args.ram) if args.ram else build()
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out}: code ends at{result['code_end']:08X}")
