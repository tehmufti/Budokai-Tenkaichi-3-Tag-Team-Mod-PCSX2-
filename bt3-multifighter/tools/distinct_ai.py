"""Offline native initialization for the distinct extra fighters' private AI.

One-shot initialization uses the game's1BAF68 routine in each private manager,
with temporary pair aliases. Known virtual-role model/radius/height callsites
receive actual model IDs. Native global getters and camera ownership are intact.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

from ai_shadow import Assembler, AI_GLOBAL, FRAME_HOOK
import team_pair_ai as pair
import team_survivor_ai as survivor

ROOT = Path(__file__).resolve().parents[1]
MODEL_BRIDGE, HEIGHT_BRIDGE, RADIUS_BRIDGE = 0xE8000, 0xE8100, 0xE8200
FRAME, CONTROL = 0xE8400, 0xEF000
RECORDS = (CONTROL + 0x40, CONTROL + 0x60)
CALLS = ((A(0x1BAFF4), A(0x2499B0), MODEL_BRIDGE, "Native AI dataset from virtual own actor's actual model"),
         (A(0x1BB534), A(0x204EA0), HEIGHT_BRIDGE, "Spatial role0 height from actual model"),
         (A(0x1BB55C), A(0x204EA0), HEIGHT_BRIDGE, "Spatial role1 height from actual model"),
         (A(0x1BB074), A(0x2062F0), RADIUS_BRIDGE, "AI initializer own radius"),
         (A(0x1BB084), A(0x2062F0), RADIUS_BRIDGE, "AI initializer enemy radius"),
         (A(0x1BB0B0), A(0x2062F0), RADIUS_BRIDGE, "AI initializer own range radius"))


def role_bridge(base, native):
    a = Assembler(base)
    a.load_address(8, pair.CONTROL)
    for offset in (0, 4):
        a.mem(35, 9, 8, offset)
        a.branch(9, 0, "native")
        a.nop()
    a.mem(11, 9, 4, 2)
    a.branch(9, 0, "native")
    a.nop()
    a.emit((4 << 16) | (9 << 11) | (2 << 6))  # sll t1,role,2
    a.emit((8 << 21) | (9 << 16) | (8 << 11) | 0x2D)
    a.mem(35, 8, 8, 8)
    a.branch(8, 0, "native")
    a.nop()
    a.mem(35, 8, 8, 12)
    a.mem(11, 9, 8, 12)
    a.branch(9, 0, "native")
    a.nop()
    a.move(4, 8)
    a.label("native")
    a.jump(native)
    a.nop()
    data = a.finish()
    assert len(data) <= 0x100
    return data


def emit_initialize(a, physical, descriptor=None, record=None, control=CONTROL):
    role = physical & 1
    own, enemy = 0x10 + role * 0x520, 0x10 + (role ^ 1) * 0x520
    descriptor = pair.DESCRIPTORS[physical] if descriptor is None else descriptor
    record = RECORDS[physical - 2] if record is None else record
    a.load_address(19, descriptor)
    a.load_address(10, record)
    a.mem(35, 21, 19, 0)
    a.mem(35, 8, 10, 0)
    a.branch(21, 8, "invalid", not_equal=True)
    a.nop()
    a.mem(35, 8, 21, 0)
    a.addiu(9, 0, physical)
    a.branch(8, 9, "invalid", not_equal=True)
    a.nop()
    a.mem(35, 8, 21, 12)
    a.mem(35, 9, 10, 4)
    a.branch(8, 9, "invalid", not_equal=True)
    a.nop()
    a.emit((8 << 16) | (8 << 11) | (2 << 6))
    a.load_address(9, A(0x31C640))
    a.emit((8 << 21) | (9 << 16) | (8 << 11) | 0x2D)
    a.mem(35, 8, 8, 0)
    a.mem(35, 9, 10, 8)
    a.branch(8, 9, "invalid", not_equal=True)
    a.nop()
    a.mem(35, 8, 8, 2356)
    a.mem(35, 9, 10, 12)
    a.branch(8, 9, "invalid", not_equal=True)
    a.nop()
    a.mem(35, 20, 19, 4)
    a.mem(35, 8, 10, 16)
    a.branch(20, 8, "invalid", not_equal=True)
    a.nop()
    a.mem(35, 8, 20, own + 36)
    a.mem(12, 8, 8, 1)
    a.branch(8, 0, "owned", not_equal=True)
    a.nop()
    a.mem(35, 8, 19, 24)
    a.mem(35, 22, 8, 0)
    a.mem(35, 23, 8, 4)
    for reg in (22, 23):
        a.branch(reg, 0, "invalid")
        a.nop()
    # Keep native shared data and the actual selected enemy's own AI context.
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
    for source, destination in ((0x50, 16 + role * 4), (0x54, 16 + (role ^ 1) * 4)):
        a.mem(35, 8, 29, source)
        a.mem(43, 8, 16, destination)
    a.mem(43, 20, 28, -0x5760)
    a.addiu(8, 0, 1)
    a.mem(43, 8, 16, 4)
    a.load_address(8, control)
    a.addiu(9, 0, physical)
    a.mem(43, 9, 8, 12)
    a.jump(A(0x1BB510), link=True)
    a.nop()
    a.addiu(4, 0, role)
    a.jump(A(0x1BAF68), link=True)
    a.move(5, 0)  # native borrowed model dataset initialization
    a.load_address(10, record)
    a.mem(43, 2, 10, 24)
    a.mem(35, 8, 20, own + 24)
    a.mem(43, 8, 10, 20)
    a.mem(35, 8, 20, own + 36)
    a.mem(43, 8, 10, 28)
    # Every exit after native init first restores both IDs and the real global.
    for reg, offset in ((21, 0x50), (22, 0x54)):
        a.mem(35, 8, 29, offset)
        a.mem(43, 8, reg, 0)
    a.mem(43, 0, 16, 4)
    a.mem(43, 0, 16, 8)
    a.mem(43, 0, 16, 12)
    a.mem(43, 17, 28, -0x5760)
    a.mem(35, 8, 10, 12)
    a.mem(35, 9, 10, 20)
    a.branch(8, 9, "dataset_failed", not_equal=True)
    a.nop()
    a.mem(35, 8, 20, own)
    a.addiu(9, 0, role)
    a.branch(8, 9, "dataset_failed", not_equal=True)
    a.nop()
    a.load_address(8, control)
    a.mem(35, 9, 8, 4)
    a.addiu(9, 9, 1)
    a.mem(43, 9, 8, 4)


def frame_stub(forward):
    a = Assembler(FRAME)
    a.load_address(2, CONTROL)
    a.mem(35, 2, 2, 0)
    a.branch(2, 0, "forward", not_equal=True)
    a.nop()
    for address in (pair.EXPOSURE, pair.CONTROL, pair.TARGET_ENABLED):
        a.load_address(2, address)
        a.mem(35, 2, 2, 0)
        a.branch(2, 0, "forward")
        a.nop()
    a.load_address(2, pair.CONTROL + 4)
    a.mem(35, 2, 2, 0)
    a.branch(2, 0, "forward", not_equal=True)
    a.nop()
    a.addiu(29, 29, -0x60)
    saved = [(16 + i, i * 8) for i in range(8)] + [(31, 0x40)]
    for reg, off in saved:
        a.mem(63, reg, 29, off)
    a.load_address(16, pair.CONTROL)
    a.mem(35, 17, 28, -0x5760)
    a.branch(17, 0, "invalid")
    a.nop()
    a.load_address(8, pair.ACTOR_HEADER)
    a.mem(35, 8, 8, 0)
    a.mem(35, 9, 28, -22364)
    a.branch(8, 9, "invalid", not_equal=True)
    a.nop()
    a.load_address(18, CONTROL)
    a.mem(43, 17, 18, 8)
    a.addiu(8, 0, 1)
    a.mem(43, 8, 18, 0)
    for physical in (2, 3):
        emit_initialize(a, physical)
    a.addiu(8, 0, 5)
    a.branch(0, 0, "status")
    a.nop()
    for label, value in (("invalid", 101), ("owned", 102), ("dataset_failed", 103)):
        a.label(label)
        a.addiu(8, 0, value)
        a.branch(0, 0, "status")
        a.nop()
    a.label("status")
    a.load_address(9, CONTROL)
    a.mem(43, 8, 9, 0)
    for reg, off in saved:
        a.mem(55, reg, 29, off)
    a.addiu(29, 29, 0x60)
    a.label("forward")
    a.jump(forward)
    a.nop()
    return a.finish()


def build(actors, models, datasets, with_survivors=True):
    data = bytearray(0x80)
    for index in range(2):
        struct.pack_into("<8I", data, 0x40 + index * 32,
                         actors[index], index + 2, models[index], datasets[index],
                         pair.SHADOWS[index + 2], 0, 0, 0)
    forward = survivor.FRAME if with_survivors else pair.FRAME_STUB
    payloads = [(MODEL_BRIDGE, role_bridge(MODEL_BRIDGE, A(0x2499B0))),
                (HEIGHT_BRIDGE, role_bridge(HEIGHT_BRIDGE, A(0x204EA0))),
                (RADIUS_BRIDGE, role_bridge(RADIUS_BRIDGE, A(0x2062F0))),
                (FRAME, frame_stub(forward)), (CONTROL, bytes(data))]
    if FRAME + len(payloads[3][1]) >= CONTROL:
        raise ValueError("Distinct AI code overlaps control")
    return {"serial": SERIAL, "crc": CRC, "status": "DISTINCT AI NATIVE INITIALIZATION; LIVE TEST REQUIRED",
            "segments": [{"address": p, "data_hex": b.hex()} for p, b in payloads],
            "control": CONTROL, "records": RECORDS, "forward": forward, "code_end": FRAME + len(payloads[3][1]),
            "control_fields": {"status": 0, "completed_actors": 4, "normal_ai": 8, "last_actor": 12},
            "status_values": {"0": "pending", "1": "initializing", "5": "complete", "101": "identity/model/manager mismatch", "102": "refused owned AI dataset", "103": "native initialization failed verification"},
            "record_fields": {"actor": 0, "model_id": 4, "model": 8, "expected_dataset": 12, "private_manager": 16,
                              "initialized_dataset": 20, "native_return": 24, "dataset_flags": 28},
            "scope": "Native1BAF68 initializes private own slots for physical2/3, with both pair actors aliased only during synchronous initialization. CPU flags and model IDs are preserved.",
            "requirements": ["Existing distinct model2/3 and active roster records, plus C4000 private pair AI and D3000 pair-local resolver.",
                             "Original context data ownership bits must be clear; owned datasets are rejected before any native free.",
                             "CPU flags remain disabled from the supplied checkpoint. Observe EF000=5/completed2 before enabling them.",
                             "The six narrow callsite redirects remain active to resolve virtual-role height and initializer model/radius queries.",
                             "Apply paused, then save/reload before running the one-shot initializer."],
            "limitations": ["Native initializer execution and new characters' CPU behavior still require live validation.",
                            "Extra specials remain limited by separate guards; no automatic team victory transition."]}


def build_install(ram_path, with_survivors=True):
    ram = Path(ram_path).read_bytes()
    if len(ram) not in (0x2000000, 0x8000000):
        raise ValueError("Expected full EE RAM")
    u = lambda p: struct.unpack_from("<I", ram, p)[0]
    if not u(pair.EXPOSURE) or not u(pair.CONTROL) or u(pair.CONTROL + 4):
        raise ValueError("Requires exposed pair mode paused outside a virtual slice")
    if u(0xC0000) != (2 << 26) | (0xD3000 >> 2):
        raise ValueError("Pair-local resolver must already be installed")
    if u(FRAME_HOOK) != (3 << 26) | (pair.FRAME_STUB >> 2):
        raise ValueError("Requires original reciprocal pair frame hook before combined upgrade")
    actors, models, datasets = [], [], []
    for physical in range(4):
        actor = u(pair.DESCRIPTORS[physical])
        if u(actor) != physical or u(actor + 0x1278):
            raise ValueError("Require four intact physical actors with CPUs disabled for initialization")
        if physical < 2:
            continue
        model_id = u(actor + 12)
        if model_id != physical:
            raise ValueError("This checkpoint initializer expects model2/3")
        model = u(A(0x31C640) + model_id * 4)
        dataset = u(model + 2356)
        if not 0x100000 <= dataset < len(ram):
            raise ValueError("Distinct AI dataset missing")
        own = pair.SHADOWS[physical] + 0x10 + (physical & 1) * 0x520
        if u(own + 36) & 1:
            raise ValueError("Refusing to let native initializer free an owned AI dataset")
        actors.append(actor)
        models.append(model)
        datasets.append(dataset)
    manifest = build(actors, models, datasets, with_survivors)
    blocks = []
    for segment in manifest["segments"]:
        address, data = segment["address"], bytes.fromhex(segment["data_hex"])
        old = ram[address:address + len(data)]
        if any(old):
            raise ValueError(f"Distinct AI reservation occupied at{address:08X}")
        blocks.append({"address": address, "expected_hex": old.hex(), "data_hex": data.hex(), "purpose": "Distinct native AI initializer/model-role bridges"})
    for address, native, bridge, purpose in CALLS:
        expected = struct.pack("<I", (3 << 26) | (native >> 2))
        if ram[address:address + 4] != expected:
            raise ValueError(f"Native callsite already changed at{address:08X}")
        blocks.append({"address": address, "expected_hex": expected.hex(), "data_hex": struct.pack("<I", (3 << 26) | (bridge >> 2)).hex(), "purpose": purpose})
    if with_survivors:
        for segment in survivor.build()["segments"]:
            address, data = segment["address"], bytes.fromhex(segment["data_hex"])
            old = ram[address:address + len(data)]
            if any(old):
                raise ValueError(f"Survivor reservation occupied at{address:08X}")
            blocks.append({"address": address, "expected_hex": old.hex(), "data_hex": data.hex(), "purpose": "Survivor target picker and dynamic private AI"})
    blocks.append({"address": FRAME_HOOK, "expected_hex": ram[FRAME_HOOK:FRAME_HOOK + 4].hex(),
                   "data_hex": struct.pack("<I", (3 << 26) | (FRAME >> 2)).hex(),
                   "purpose": "One-shot distinct AI initialization then survivor/pair frame wrapper"})
    return {**manifest, "source_ram": str(Path(ram_path).resolve()), "with_survivors": with_survivors, "blocks": blocks}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ram", type=Path, required=True)
    p.add_argument("--without-survivors", action="store_true")
    p.add_argument("--out", type=Path, default=ROOT / "analysis" / "distinct-ai-with-survivors.json")
    args = p.parse_args()
    result = build_install(args.ram, not args.without_survivors)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(result['blocks'])} guarded blocks, code ends at{result['code_end']:08X}")
