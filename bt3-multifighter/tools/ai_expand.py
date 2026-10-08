"""Build an offline, byte-guarded BT3 USA AI-manager expansion manifest.

This does not connect to PCSX2, enable cheats, or modify the game ELF. Expanding
AI state alone does not spawn fighters. See analysis/ai_extension.md.
"""
from native_map import A, CRC, SERIAL, elf_path
from pathlib import Path
import argparse
import hashlib
import json
import struct

ROOT = Path(__file__).resolve().parents[1]
ELF = elf_path(ROOT)

# Every manager trailer use in the executable, manually checked against its
# surrounding loads from gp-0x5760. Other executable immediates with the same
# numerical value belong to unrelated structures and must not be patched.
TRAILER = {
    A(0x1BAD8C): 0xAC400A50,
    A(0x1BADA8): 0x8C620A54,
    A(0x1BADB0): 0xAC620A54,
    A(0x1BAE34): 0x8C620A54,
    A(0x1BAE3C): 0xAC620A54,
    A(0x1BB138): 0x8C620A54,
    A(0x1BB16C): 0x24620A50,
    A(0x1BB1AC): 0x24620A50,
    A(0x1BB260): 0x8C620A54,
    A(0x1BB294): 0x24620A50,
    A(0x1BB2D4): 0x24620A50,
    A(0x1BB618): 0x8C620A50,
    A(0x1BB69C): 0x8C620A50,
    A(0x1BB6A8): 0xAC620A50,
}
ALLOCATION = {A(0x1BB218): 0x24040A60, A(0x1BB234): 0x24060A60}
BOUNDS = {A(0x1BB1D4): 0x2A020002, A(0x1BB704): 0x2A230002}


def load_segments(blob):
    assert blob[:7] == b"\x7fELF\x01\x01\x01"
    phoff = struct.unpack_from("<I", blob, 28)[0]
    phentsize, phnum = struct.unpack_from("<HH", blob, 42)
    segments = []
    for index in range(phnum):
        kind, off, va, _, filesz, *_ = struct.unpack_from(
            "<8I", blob, phoff + index * phentsize
        )
        if kind == 1:
            segments.append((va, off, filesz))
    return segments


def word_at(blob, segments, address):
    for va, off, length in segments:
        if va <= address and address + 4 <= va + length:
            return struct.unpack_from("<I", blob, off + address - va)[0]
    raise ValueError(f"Unmapped ELF address {address:08X}")


def build_manifest(count, blob=None):
    if count not in range(3, 13):
        raise ValueError("AI capacity must be between 3 and 12")
    if blob is None:
        blob = ELF.read_bytes()
    segments = load_segments(blob)
    trailer = 0x10 + count * 0x520
    allocation = trailer + 0x10
    patches = []
    for group, label in [(TRAILER, "trailer"), (ALLOCATION, "allocation"), (BOUNDS, "bound")]:
        for address, old in group.items():
            actual = word_at(blob, segments, address)
            if actual != old:
                raise ValueError(f"ELF mismatch at {address:08X}: {actual:08X} != {old:08X}")
            immediate = (
                trailer + (old & 0xFFFF) - 0xA50
                if label == "trailer"
                else allocation if label == "allocation" else count
            )
            patches.append({
                "address": address, "expected": old,
                "replacement": (old & 0xFFFF0000) | immediate,
                "purpose": label,
            })
    return {
        "status": "OFFLINE VERIFIED BYTE PATCHES; LIVE EXECUTION UNTESTED",
        "serial": SERIAL, "crc": CRC,
        "elf_sha256": hashlib.sha256(blob).hexdigest(),
        "capacity": count, "manager_global": A(0x2FEB10),
        "context_offset": 0x10, "context_stride": 0x520,
        "trailer_offset": trailer, "allocation_size": allocation,
        "patches": sorted(patches, key=lambda p: p["address"]),
        "live_migration": {
            "old_size": 0xA60,
            "copy_regions": [
                {"source_offset": 0, "destination_offset": 0, "size": 0xA50},
                {"source_offset": 0xA50, "destination_offset": trailer, "size": 0x10},
            ],
            "zero_region": {"offset": 0xA50, "size": (count - 2) * 0x520},
            "allocate_function": A(0x2554D8),
            "initialize_context_function": A(0x1BAF68),
            "initialize_context_arguments": "a0=logical actor/resource ID, a1=0",
            "note": "Publish the new manager pointer only while emulation is paused; flush EE code caches using emulator reload/restart or supported debugger invalidation. Do not initialize IDs without valid actor/resource entries.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capacity", type=int, default=4)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.capacity)
    out = args.out or ROOT / "analysis" / f"ai_capacity_{args.capacity}.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Validated {len(manifest['patches'])} instruction guards.")
    print(f"Capacity {args.capacity}; allocation {manifest['allocation_size']:#x}; trailer {manifest['trailer_offset']:#x}.")
    print(out)


if __name__ == "__main__":
    main()
