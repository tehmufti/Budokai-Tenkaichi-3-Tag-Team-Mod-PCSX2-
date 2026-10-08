"""Offline six-fighter private AI, survivor targets, and native initialization.

Uses a fixed arena in128MiB EE RAM beyond heap1's06000000 limit. Existing
four private contexts are copied intact; only newly created actors4/5 receive
native initialization. The root installer publishes six actors after status5.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

from ai_shadow import Assembler, AI_GLOBAL, FRAME_HOOK
import team_pair_ai as pair
import distinct_ai

ROOT = Path(__file__).resolve().parents[1]
FRAME, PICKER, INITIALIZE = 0xE9000, 0xEA800, 0xEC000
CONTROL = 0x07000000
DESCRIPTORS = tuple(CONTROL + 0x100 + i * 64 for i in range(12))
SHADOWS = tuple(CONTROL + 0x1000 + i * 0x1000 for i in range(12))
RECORDS = tuple(CONTROL + 0x400 + i * 32 for i in range(12))
TARGETS, POINTERS = 0xD8000, 0xD8040
MODE, COUNT, CAPTURED_MANAGER = 0xD8080, 0xD8084, 0xD8088
N = 6
DEFAULTS = (3, 2, 1, 0, 5, 4)
DEFERRED = (3480, 3500, 3512)


def initialize_stub():
    a = Assembler(INITIALIZE)
    a.addiu(29, 29, -0x60)
    saved = [(16 + i, i * 8) for i in range(8)] + [(31, 0x40)]
    for r, o in saved:
        a.mem(63, r, 29, o)
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
    for physical in (4, 5):
        distinct_ai.emit_initialize(a, physical, DESCRIPTORS[physical], RECORDS[physical], CONTROL)
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
    for r, o in saved:
        a.mem(55, r, 29, o)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x60)
    return a.finish()


def picker_stub(free_for_all=False):
    a = Assembler(PICKER)
    a.addiu(29, 29, -0x50 if free_for_all else -0x30)
    saved = ((16, 0), (17, 8), (18, 16), (19, 24), (31, 32))
    for r, o in saved:
        a.mem(63, r, 29, o)
    a.load_address(16, CONTROL)
    a.move(17, 0)
    for i in range(N):
        a.load_address(8, DESCRIPTORS[i])
        a.mem(35, 4, 8, 0)
        a.jump(A(0x1DC320), link=True)
        a.nop()
        a.branch(2, 0, f"dead{i}", not_equal=True)
        a.nop()
        a.mem(13, 17, 17, 1 << i)
        a.label(f"dead{i}")
    a.mem(43, 17, 16, 0x14)
    for i in range(N):
        enemies = [j for j in range(N) if j != i and (free_for_all or j % 2 != i % 2)]
        preferred = DEFAULTS[i]
        choices = [preferred] + [j for j in enemies if j != preferred]
        a.load_address(18, DESCRIPTORS[i])
        a.mem(35, 19, 18, 0)
        a.mem(12, 11, 17, 1 << i)
        a.mem(43, 11, 18, 0x1C)
        a.load_address(8, TARGETS + i * 4)
        a.mem(35, 9, 8, 0)
        a.move(10, 9)
        for enemy in enemies:
            a.addiu(11, 0, enemy)
            a.branch(9, 11, f"current{i}_{enemy}")
            a.nop()
        a.branch(0, 0, f"choose{i}")
        a.nop()
        for enemy in enemies:
            a.label(f"current{i}_{enemy}")
            a.mem(12, 11, 17, 1 << enemy)
            a.branch(11, 0, f"store{i}", not_equal=True)
            a.nop()
            if free_for_all:
                # A defeated recipient can remain bound until the native rush,
                # grab or clash finishes. Preserve that authored target for
                # human and CPU actors alike; a different living opponent's
                # sequence does not delay this actor's ordinary fallback.
                import ffa_targeting
                for r,o in ((8,0x28),(9,0x30),(10,0x38)):a.mem(63,r,29,o)
                a.move(4,19);a.addiu(5,0,i)
                a.jump(ffa_targeting.SAFE,link=True);a.nop()
                for r,o in ((8,0x28),(9,0x30),(10,0x38)):a.mem(55,r,29,o)
                a.branch(2,0,f"store{i}");a.nop()
            for offset in DEFERRED:
                a.mem(35, 11, 19, offset)
                a.branch(11, 0, f"deferred{i}", not_equal=True)
                a.nop()
            a.branch(0, 0, f"choose{i}")
            a.nop()
        a.label(f"choose{i}")
        for enemy in choices:
            a.mem(12, 11, 17, 1 << enemy)
            a.branch(11, 0, f"use{i}_{enemy}", not_equal=True)
            a.nop()
        a.addiu(10, 0, preferred)  # No living enemy: retain a valid opposing ID.
        a.branch(0, 0, f"store{i}")
        a.nop()
        for enemy in choices:
            a.label(f"use{i}_{enemy}")
            a.addiu(10, 0, enemy)
            a.branch(0, 0, f"store{i}")
            a.nop()
        a.label(f"deferred{i}")
        a.mem(35, 11, 16, 0x1C)
        a.addiu(11, 11, 1)
        a.mem(43, 11, 16, 0x1C)
        a.label(f"store{i}")
        a.branch(10, 9, f"same{i}")
        a.nop()
        a.mem(35, 11, 16, 0x18)
        a.addiu(11, 11, 1)
        a.mem(43, 11, 16, 0x18)
        a.label(f"same{i}")
        a.mem(43, 10, 8, 0)
        a.emit((10 << 16) | (11 << 11) | (6 << 6))
        a.load_address(12, DESCRIPTORS[0])
        a.emit((11 << 21) | (12 << 16) | (11 << 11) | 0x2D)
        a.mem(43, 11, 18, 24)
    for r, o in saved:
        a.mem(55, r, 29, o)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x50 if free_for_all else 0x30)
    return a.finish()


def emit_slice(a, physical, free_for_all=False):
    role = physical & 1
    own, enemy = 0x10 + role * 0x520, 0x10 + (role ^ 1) * 0x520
    end, clear = f"slice{physical}_end", f"slice{physical}_clear"
    a.load_address(19, DESCRIPTORS[physical])
    a.mem(35, 21, 19, 0)
    a.mem(35, 8, 21, 0x1278)
    a.branch(8, 0, end)
    a.nop()
    a.load_address(8, CONTROL)
    a.mem(35, 8, 8, 0x14)
    a.mem(12, 9, 8, 1 << physical)
    a.branch(9, 0, clear)
    a.nop()
    a.mem(35, 20, 19, 4)
    a.mem(35, 9, 20, own + 24)
    a.branch(9, 0, clear)
    a.nop()
    a.mem(35, 9, 19, 24)
    a.mem(35, 22, 9, 0)
    a.mem(35, 10, 9, 20)
    a.addiu(11, 0, 1)
    a.emit((10 << 21) | (11 << 16) | (11 << 11) | 4)
    a.emit((8 << 21) | (11 << 16) | (11 << 11) | 0x24)
    a.branch(11, 0, clear)
    a.nop()
    a.mem(35, 23, 9, 4)
    for offset in (0, 8, 0xA50, 0xA58):
        a.mem(55, 8, 17, offset)
        a.mem(63, 8, 20, offset)
    if free_for_all:
        # The target can occupy our own native parity. Copy its actual private
        # own row into our opposite logical role, not its stale enemy scratch.
        a.mem(35, 8, 9, 8)
        a.branch(8, 0, f"source_even{physical}"); a.nop()
        a.addiu(8, 23, 0x530)
        a.branch(0, 0, f"source_ready{physical}"); a.nop()
        a.label(f"source_even{physical}"); a.addiu(8, 23, 0x10)
        a.label(f"source_ready{physical}")
    else:
        a.addiu(8, 23, enemy)
    a.addiu(9, 20, enemy)
    a.addiu(10, 8, 0x520)
    a.label(f"copy{physical}")
    a.mem(55, 11, 8, 0)
    a.mem(63, 11, 9, 0)
    a.addiu(8, 8, 8)
    a.branch(8, 10, f"copy{physical}", not_equal=True)
    a.addiu(9, 9, 8)
    if free_for_all:
        a.addiu(8, 0, role ^ 1); a.mem(43, 8, 20, enemy)
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
    a.jump(A(0x1BB510), link=True)
    a.nop()
    for target in (A(0x1BFF70), A(0x1BAC30), A(0x1B6BA0), A(0x1B6CD8)):
        a.jump(target, link=True)
        a.addiu(4, 20, own)
    for reg, offset in ((21, 0x50), (22, 0x54)):
        a.mem(35, 8, 29, offset)
        a.mem(43, 8, reg, 0)
    for offset in (4, 8, 12):
        a.mem(43, 0, 16, offset)
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
    for address in (pair.EXPOSURE, pair.CONTROL, pair.TARGET_ENABLED):
        a.load_address(2, address)
        a.mem(35, 2, 2, 0)
        a.branch(2, 0, "fallback")
        a.nop()
    a.load_address(2, pair.CONTROL + 4)
    a.mem(35, 2, 2, 0)
    a.branch(2, 0, "fallback", not_equal=True)
    a.nop()
    a.addiu(29, 29, -0x60)
    saved = [(16 + i, i * 8) for i in range(8)] + [(31, 0x40)]
    for r, o in saved:
        a.mem(63, r, 29, o)
    a.load_address(8, CONTROL)
    a.mem(35, 9, 8, 0)
    a.branch(9, 0, "initialized", not_equal=True)
    a.nop()
    a.jump(INITIALIZE, link=True)
    a.nop()
    a.label("initialized")
    a.load_address(8, CONTROL)
    a.mem(35, 9, 8, 0)
    a.addiu(10, 0, 5)
    a.branch(9, 10, "restore_fallback", not_equal=True)
    a.nop()
    a.load_address(8, 0xF609C)
    a.mem(35, 9, 8, 0)
    a.branch(9, 0, "restore_fallback")
    a.nop()
    a.load_address(8, MODE)
    a.mem(35, 9, 8, 0)
    a.branch(9, 0, "restore_fallback")
    a.nop()
    a.mem(35, 9, 8, 4)
    a.addiu(10, 0, N)
    a.branch(9, 10, "restore_fallback", not_equal=True)
    a.nop()
    a.mem(35, 9, 8, 8)
    a.mem(35, 10, 28, -22364)
    a.branch(9, 10, "restore_fallback", not_equal=True)
    a.nop()
    # Published actor pointers must match the private contexts before any tick.
    for i in range(N):
        a.load_address(8, DESCRIPTORS[i])
        a.mem(35, 9, 8, 0)
        a.load_address(8, POINTERS + i * 4)
        a.mem(35, 10, 8, 0)
        a.branch(9, 10, "restore_fallback", not_equal=True)
        a.nop()
    a.load_address(16, pair.CONTROL)
    a.mem(35, 17, 28, -0x5760)
    a.branch(17, 0, "restore_fallback")
    a.nop()
    a.mem(35, 18, 17, 0xA50)
    for reg, descriptor in ((21, DESCRIPTORS[0]), (22, DESCRIPTORS[1])):
        a.load_address(8, descriptor)
        a.mem(35, reg, 8, 0)
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
    a.branch(8, 18, "return")
    a.nop()
    a.jump(PICKER, link=True)
    a.nop()
    for physical in range(N):
        emit_slice(a, physical)
    a.load_address(9, CONTROL)
    a.mem(35, 8, 9, 0x10)
    a.addiu(8, 8, 1)
    a.mem(43, 8, 9, 0x10)
    a.label("return")
    for r, o in saved:
        a.mem(55, r, 29, o)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x60)
    a.label("restore_fallback")
    for r, o in saved:
        a.mem(55, r, 29, o)
    a.addiu(29, 29, 0x60)
    a.label("fallback")
    a.jump(distinct_ai.FRAME)
    a.nop()
    return a.finish()


def build():
    payloads = ((FRAME, frame_stub()), (PICKER, picker_stub()), (INITIALIZE, initialize_stub()))
    if FRAME + len(payloads[0][1]) > PICKER or PICKER + len(payloads[1][1]) > INITIALIZE:
        raise ValueError("Six AI code sections overlap")
    if INITIALIZE + len(payloads[2][1]) >= distinct_ai.CONTROL:
        raise ValueError("Six initializer overlaps previous distinct AI control")
    hook = {"address": FRAME_HOOK,
            "expected_hex": struct.pack("<I", (3 << 26) | (distinct_ai.FRAME >> 2)).hex(),
            "data_hex": struct.pack("<I", (3 << 26) | (FRAME >> 2)).hex()}
    return {"serial": SERIAL, "crc": CRC, "status": "SIX PRIVATE AI CONTEXTS; ROOT ACTIVATES COUNT AFTER NATIVE INIT",
            "segments": [{"address": p, "data_hex": b.hex()} for p, b in payloads], "hooks": [hook],
            "control": CONTROL, "descriptors": DESCRIPTORS, "shadows": SHADOWS,
            "control_fields": {"status": 0, "initialized_new_actors": 4, "normal_ai": 8, "last_actor": 12,
                               "frames": 16, "alive_mask": 20, "target_changes": 24, "deferred_retarget_checks": 28},
            "descriptor_stride": 64, "descriptor_fields": {"actor": 0, "manager": 4, "role": 8, "ticks": 12,
                "mask": 16, "physical_id": 20, "enemy_descriptor": 24, "alive_bit": 28, "model_id": 32,
                "model": 36, "dataset": 40, "source_context": 44},
            "requirements": ["128MiB EE RAM; fixed07000000 arena stays outside heap1 ending06000000.",
                             "Six created actors, distinct datasets, pair aliases/getters, narrow E8 role bridges, and D3000 fallback resolver.",
                             "Initializes actors4/5 while D8080 is still0; then requires status07000000=5 before root enables D8080/count6.",
                             "Root must extend getters, scheduler arrays, KO/special/audio/replay/stat guards before activation.",
                             "D8000 targets, D8040 actor pointers, D8080 enable/D8084count6/D8088manager must match.",
                             "Four existing contexts are copied intact; firstfour actors are not reinitialized."],
            "limitations": ["Six actors, parity teams, stable survivor targets; no completed team victory transition.",
                            "Arena reserves twelve contexts but only six are initialized or scheduled.",
                            "More native virtual-role height/radius queries and projectile/cinematic behavior need continued validation."]}


def build_install(ram_path):
    ram = Path(ram_path).read_bytes()
    if len(ram) != 0x8000000:
        raise ValueError("Requires full128MiB EE RAM")
    u = lambda p: struct.unpack_from("<I", ram, p)[0]
    if not u(pair.EXPOSURE) or not u(pair.CONTROL) or u(pair.CONTROL + 4):
        raise ValueError("Requires active four-actor pair mode outside a virtual slice")
    if u(distinct_ai.CONTROL) != 5:
        raise ValueError("Distinct firstfour initialization must have completed")
    for address, _, bridge, _ in distinct_ai.CALLS:
        if u(address) != (3 << 26) | (bridge >> 2):
            raise ValueError("Missing narrow virtual-role model/height/radius bridge")
    if any(ram[CONTROL:CONTROL + 0xD000]):
        raise ValueError("Reserved high AI arena is occupied")
    actors = [u(d) for d in pair.DESCRIPTORS] + [u(0xF601C), u(0xF605C)]
    if len(set(actors)) != N:
        raise ValueError("Requires six distinct actor allocations")
    sources = list(pair.SHADOWS) + [pair.SHADOWS[0], pair.SHADOWS[1]]
    header = bytearray(0x600)
    contexts = []
    models = []
    for i, actor in enumerate(actors):
        if not 0x100000 <= actor < len(ram) - 0x1600 or u(actor) != i or u(actor + 0x1278):
            raise ValueError(f"Invalid actor{i} or CPU not disabled")
        model_id = u(actor + 12)
        if model_id >= 12:
            raise ValueError("Model exceeds native twelve-slot table")
        model = u(A(0x31C640) + model_id * 4)
        dataset = u(model + 2356)
        if not 0x100000 <= dataset < len(ram):
            raise ValueError(f"Missing actor{i} model AI data")
        own = 0x10 + (i & 1) * 0x520
        context = ram[sources[i]:sources[i] + 0xA60]
        if struct.unpack_from("<I", context, own + 36)[0] & 1:
            raise ValueError("Owned source dataset would be unsafe to clone")
        if i < 4 and struct.unpack_from("<I", context, own + 24)[0] != dataset:
            raise ValueError("Firstfour AI source no longer matches distinct model")
        contexts.append(context)
        models.append((model_id, model, dataset))
        struct.pack_into("<12I", header, DESCRIPTORS[i] - CONTROL,
                         actor, SHADOWS[i], i & 1, 0, 0, i, DESCRIPTORS[DEFAULTS[i]], 0,
                         model_id, model, dataset, sources[i])
        struct.pack_into("<8I", header, RECORDS[i] - CONTROL,
                         actor, model_id, model, dataset, SHADOWS[i], 0, 0, 0)
    manifest = build()
    payloads = [(s['address'], bytes.fromhex(s['data_hex'])) for s in manifest['segments']]
    payloads += [(CONTROL, bytes(header))] + [(SHADOWS[i], contexts[i]) for i in range(N)]
    blocks = []
    for address, data in payloads:
        old = ram[address:address + len(data)]
        if any(old):
            raise ValueError(f"Six AI code/context reservation occupied at{address:08X}")
        blocks.append({"address": address, "expected_hex": old.hex(), "data_hex": data.hex(), "purpose": "Six private AI code, descriptors, and preserved/seed contexts"})
    for hook in manifest['hooks']:
        expected = bytes.fromhex(hook['expected_hex'])
        if ram[hook['address']:hook['address'] + len(expected)] != expected:
            raise ValueError("Current distinct-init frame hook changed")
        blocks.append({**hook, "purpose": "Initialize new actors privately, then six-actor scheduler when enabled"})
    return {**manifest, "source_ram": str(Path(ram_path).resolve()), "actors": actors, "models": models,
            "blocks": blocks, "activation": "No D8080/count write included. Initialize with exposure still4; root activates6 after all supporting hooks are ready."}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ram', type=Path)
    p.add_argument('--out', type=Path, default=ROOT / 'analysis/team-six-ai.json')
    args = p.parse_args()
    result = build_install(args.ram) if args.ram else build()
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f"{args.out}: {len(result.get('blocks', []))} guarded blocks")
