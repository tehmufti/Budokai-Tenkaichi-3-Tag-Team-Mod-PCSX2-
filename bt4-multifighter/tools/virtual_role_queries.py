"""Optional narrow AI-context height/radius callsite redirects, offline only.

Each argument comes directly from an AI context's virtual-role word. The
existing alias-scoped E8 bridges translate that role to the actor's model ID.
Global204EA0/2062F0 implementations and all non-AI callsites remain untouched.
"""
from native_map import A, CRC, JPN, SERIAL
import argparse
import json
import struct
from pathlib import Path

from distinct_ai import HEIGHT_BRIDGE, RADIUS_BRIDGE, role_bridge

ROOT = Path(__file__).resolve().parents[1]
# call, native helper, bridge, address of proven lw a0,0(context), base register,
# containing native AI-context routine. The Japanese 1BB9A8 keeps the context in s1, not s2 (jpn_reviewed.json).
S_1BB9A8 = 17 if JPN else 18
SPECS = (
    (A(0x1B424C), A(0x204EA0), HEIGHT_BRIDGE, A(0x1B4248), 16, A(0x1B4220)),
    (A(0x1B9400), A(0x204EA0), HEIGHT_BRIDGE, A(0x1B9404), 17, A(0x1B93D8)),
    (A(0x1BBB10), A(0x204EA0), HEIGHT_BRIDGE, A(0x1BBB14), S_1BB9A8, A(0x1BB9A8)),
    (A(0x1B94F0), A(0x2062F0), RADIUS_BRIDGE, A(0x1B94EC), 17, A(0x1B93D8)),
    (A(0x1BBBDC), A(0x2062F0), RADIUS_BRIDGE, A(0x1BBBE0), S_1BB9A8, A(0x1BB9A8)),
    (A(0x1BC1A4), A(0x2062F0), RADIUS_BRIDGE, A(0x1BC1A0), 18, A(0x1BC0B8)),
    (A(0x1BC1B8), A(0x2062F0), RADIUS_BRIDGE, A(0x1BC1BC), 18, A(0x1BC0B8)),
    (A(0x1BCB00), A(0x2062F0), RADIUS_BRIDGE, A(0x1BCAFC), 18, A(0x1BCAA8)),
    (A(0x1BE6EC), A(0x2062F0), RADIUS_BRIDGE, A(0x1BE6E8), 16, A(0x1BE680)),
    (A(0x1BE984), A(0x2062F0), RADIUS_BRIDGE, A(0x1BE988), 18, A(0x1BE8C0)),
    (A(0x1BE9B8), A(0x2062F0), RADIUS_BRIDGE, A(0x1BE9BC), 18, A(0x1BE8C0)),
)


def build(source):
    ram = Path(source).read_bytes()
    if len(ram) not in (0x2000000, 0x8000000):
        raise ValueError("Expected complete EE RAM")
    u = lambda address: struct.unpack_from('<I', ram, address)[0]
    for bridge, native in ((HEIGHT_BRIDGE, A(0x204EA0)), (RADIUS_BRIDGE, A(0x2062F0))):
        code = role_bridge(bridge, native)
        if ram[bridge:bridge + len(code)] != code:
            raise ValueError("Existing virtual-role bridge differs from the audited code")
    blocks, evidence = [], []
    for call, native, bridge, load, base, function in SPECS:
        expected = (3 << 26) | (native >> 2)
        if u(call) != expected or u(load) != (35 << 26) | (base << 21) | (4 << 16):
            raise ValueError(f"Call or virtual-context argument load changed at{call:08X}")
        blocks.append({"address": call, "expected_hex": struct.pack('<I', expected).hex(),
                       "data_hex": struct.pack('<I', (3 << 26) | (bridge >> 2)).hex(),
                       "purpose": "AI virtual-context " + ("height" if native == A(0x204EA0) else "radius") + " query uses actual selected model"})
        evidence.append({"call": call, "function": function, "argument_load": load,
                         "context_register": f"s{base - 16}", "role_field_offset": 0,
                         "proof": "Decomp takes int* AI context and calls helper(*context); native argument load is lw a0,0(context register)."})
    return {"serial": SERIAL, "crc": CRC, "source_ram": str(Path(source).resolve()),
            "status": "OPTIONAL KNOWN-VIRTUAL-ROLE AI GEOMETRY QUERIES",
            "blocks": blocks, "evidence": evidence,
            "scope": "Three remaining AI height queries and eight runtime radius queries only. Their delay slots and native floating-point functions remain unchanged.",
            "requirements": ["E8100/E8200 alias-scoped role bridges must already match the distinct-AI initializer installation.",
                             "C4000 pair mode and C4004 alias-active gate remapping; inactive calls preserve native arguments.",
                             "Apply paused and save/reload to invalidate EE code caches."],
            "limitation": "Corrects model selection for these known role queries; complete AI quality and character-specific behavior still need runtime validation."}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ram', type=Path, required=True)
    p.add_argument('--out', type=Path, default=ROOT / 'analysis/virtual-role-queries.json')
    args = p.parse_args()
    result = build(args.ram)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f"{args.out}: {len(result['blocks'])} individually guarded native calls")
