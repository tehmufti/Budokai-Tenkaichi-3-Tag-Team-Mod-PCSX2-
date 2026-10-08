"""Validate the PCSX2 v2.5.211 / 2.6.x savestate layout; convert a COPY of a v2.5.211 32 MB state to 128 MB.

PCSX2 2.6.0-2.6.3 (save version 0x9A550000) serialize exactly the v2.5.211 layout
(0x9A540000): their Counters, Memory, GS and cycle sources are identical and only
g_SaveVersion changed, so inspect_state() checks both with the same offsets.
Conversion stays v2.5.211-only. Offline archive conversion only: no emulator,
configuration, PINE or game-heap changes. Output is restricted to
analysis/converted-states and never replaced. The converted checkpoint requires a
separately booted ExtraMemory=true VM. Preserved guest TLBs and high-memory access
still require a runtime canary test.
"""
from __future__ import annotations

import argparse
import binascii
import copy
import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path

import pcsx2_versions

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / 'analysis' / 'converted-states'
VERSION = 'PCSX2 Savestate Version.id'
INTERNAL = 'PCSX2 Internal Structures.dat'
MEMORY = 'eeMemory.bin'
SAVE_VERSION = 0x9A540000  # PCSX2 v2.5.211, the developer runtime and the only conversion source
MAIN_RAM = 0x02000000
TOTAL_RAM = 0x08000000
# Memory modes each save version of this layout is checked in: (EE RAM bytes, ExtraMemory flag).
# v2.5.211 has 32 MB conversion sources and 128 MiB developer states; 2.6.x states come from the
# player runtime, which always runs with ExtraMemory on.
MEMORY_MODES = {
    0x9A540000: ((MAIN_RAM, 0), (TOTAL_RAM, 1)),
    0x9A550000: ((TOTAL_RAM, 1),),
}
# ZIP methods a savestate entry may use: PCSX2 writes Store (0), Deflate (8) or Zstandard (93;
# 20 is the older zstd id); patch_state writes Deflate. PCSX2 2.6 also offers Deflate64 (9) and
# LZMA2 (33), which Python cannot read, so Play.cmd pins SavestateCompressionType = 2 (Zstandard).
READABLE_METHODS = (0, 8, 20, 93)
METHOD_NAMES = {9: 'Deflate64', 12: 'BZIP2', 14: 'LZMA', 33: 'LZMA2', 95: 'XZ'}
COUNTER_BYTES = 4 * 28 + 2 * 12 + 2 * 4 + 40 + 4 + 1  # 189
MEMORY_DEVICE_BYTES = 2 * (0xFF * 2) + 1 + 1 + 2       # 1024
SOURCE_BASE = 'https://github.com/PCSX2/pcsx2/blob/v2.5.211/pcsx2/'
SOURCES = {
    'raw_serialization': SOURCE_BASE + 'SaveState.h#L101-L105',
    'section_order_and_tags': SOURCE_BASE + 'SaveState.cpp#L119-L135',
    'subsystem_order': SOURCE_BASE + 'SaveState.cpp#L181-L218',
    'counter_fields': SOURCE_BASE + 'Counters.h#L55-L72',
    'counter_timing_structure': SOURCE_BASE + 'Counters.cpp#L151-L166',
    'counter_serialization': SOURCE_BASE + 'Counters.cpp#L1040-L1053',
    'video_enum_and_bool': SOURCE_BASE + 'GS.h#L215-L233',
    'memory_fields': SOURCE_BASE + 'Memory.cpp#L70-L75',
    'memory_flag_and_rejection': SOURCE_BASE + 'Memory.cpp#L1229-L1247',
    'gs_boundary_validation': SOURCE_BASE + 'GS.cpp#L337-L343',
    'memory_entry_size': SOURCE_BASE + 'SaveState.cpp#L517-L529',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tag(name):
    return name.encode('ascii').ljust(32, b'\0')


def unique_tag(data, name):
    needle = tag(name)
    require(data.count(needle) == 1, f'Missing or ambiguous {name} section tag')
    return data.index(needle)


def inspect_layout(internals):
    """Cross-checked offsets of the v2.5.211 / 2.6.x internal structures (memory mode unchecked)."""
    bios = unique_tag(internals, 'BIOS')
    cpu = unique_tag(internals, 'cpuRegs')
    cycles = unique_tag(internals, 'Cycles')
    ee = unique_tag(internals, 'EE-Subsystems')
    iop = unique_tag(internals, 'IOP-Subsystems')
    require(bios == 0 and bios < cpu < cycles < ee < iop, 'Unexpected section order')
    require(ee == cycles + 32 + 6 * 4, 'Unexpected cycle timer section size')
    rcnt = ee + 32
    mem = rcnt + COUNTER_BYTES
    flag = mem + MEMORY_DEVICE_BYTES
    gs = flag + 1
    require(gs + 0x2000 + 4 < iop <= len(internals) - 32,
            'Truncated or inconsistent EE subsystem boundaries')
    # Counter timers are serialized once in Cycles and again in rcntFreeze.
    require(internals[cycles + 40:cycles + 48] == internals[rcnt + 136:rcnt + 144],
            'Duplicate timer fields disagree; counter layout is not validated')
    framerate = struct.unpack_from('<d', internals, rcnt + 144)[0]
    require(math.isfinite(framerate) and 1 <= framerate <= 240,
            'Counter timing structure has an invalid frame rate')
    mode = struct.unpack_from('<I', internals, rcnt + 184)[0]
    gs_mode = struct.unpack_from('<I', internals, gs + 0x2000)[0]
    require(1 <= mode <= 11 and mode == gs_mode,
            'Duplicate GS video modes disagree; memory flag boundary is not validated')
    require(internals[rcnt + 188] in (0, 1), 'Invalid interlace boolean')
    require(internals[mem + 1020] in (0, 1) and internals[mem + 1021] in (0, 1),
            'Invalid memory-device boolean fields')
    return {'extra_memory_offset': flag, 'ee_subsystems_offset': ee,
            'counter_bytes': COUNTER_BYTES, 'memory_device_bytes': MEMORY_DEVICE_BYTES,
            'gs_offset': gs, 'video_mode': mode, 'framerate': framerate}


def inspect_state(version, internals, memory_size):
    """Check a state of this layout (save version and tag per pcsx2_versions.json) in a memory mode
    its save version allows; the report adds ee_memory_size and emulator (the version tag)."""
    family = pcsx2_versions.state_family(version)
    save = family['save_version']
    require(family['layout'] == 'state128' and save in MEMORY_MODES,
            f'Save version 0x{save:08X} does not use the v2.5.211 / 2.6 layout')
    modes = MEMORY_MODES[save]
    require(memory_size in {size for size, _ in modes},
            f'Input must contain exactly {" or ".join(f"{size >> 20} MiB" for size, _ in modes)} EE RAM')
    report = inspect_layout(internals)
    extra = internals[report['extra_memory_offset']]
    require((memory_size, extra) in modes,
            'Input must be an ExtraMemory=true state' if memory_size == TOTAL_RAM
            else 'Input is not a 32 MB memory-mode state')
    report.update(ee_memory_size=memory_size, emulator=family['emulator'])
    return report


def inspect_payload(version, internals, memory_size):
    """A conversion source: an exact official v2.5.211 32 MB state (ExtraMemory off)."""
    require(len(version) == 36, 'Unexpected version entry size')
    require(struct.unpack_from('<I', version)[0] == SAVE_VERSION,
            'Only save version 0x9A540000 (PCSX2 v2.5.211) can be converted')
    require(memory_size == MAIN_RAM, 'Input must contain exactly 32 MB EE RAM')
    return inspect_state(version, internals, memory_size)


def require_readable(info):
    """Refuse a ZIP method read_entry cannot decode, naming the PCSX2 setting that chooses it."""
    method = info.compress_type
    if method not in READABLE_METHODS:
        name = METHOD_NAMES.get(method, 'unknown')
        raise ValueError(
            f'Savestate entry {info.filename} uses ZIP compression method {method} ({name}), which the mod '
            'cannot read. Set PCSX2 savestate compression to Zstandard ([EmuCore] SavestateCompressionType = 2; '
            'Play sets it for each session), then save the state again.')


def read_entry(archive, raw_file, info):
    require(not info.flag_bits & 1, 'Encrypted archive entries are unsupported')
    require_readable(info)
    if info.compress_type in (20, 93):
        import zstandard
        raw_file.seek(info.header_offset)
        header = raw_file.read(30)
        require(len(header) == 30 and header[:4] == b'PK\x03\x04', 'Invalid local ZIP header')
        name_size, extra_size = struct.unpack_from('<HH', header, 26)
        raw_file.seek(name_size + extra_size, 1)
        compressed = raw_file.read(info.compress_size)
        require(len(compressed) == info.compress_size, 'Truncated compressed entry')
        value = zstandard.ZstdDecompressor().decompress(compressed, max_output_size=info.file_size)
    else:
        value = archive.read(info)
    require(len(value) == info.file_size, f'Entry size mismatch: {info.filename}')
    require(binascii.crc32(value) & 0xFFFFFFFF == info.CRC, f'Entry CRC mismatch: {info.filename}')
    return value


def inspect_archive(source):
    source = Path(source).resolve(strict=True)
    with zipfile.ZipFile(source) as archive, source.open('rb') as raw:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        require(len(names) == len(set(names)), 'Duplicate archive entry names')
        require({VERSION, INTERNAL, MEMORY}.issubset(names), 'Missing required state entries')
        version = read_entry(archive, raw, archive.getinfo(VERSION))
        internals = read_entry(archive, raw, archive.getinfo(INTERNAL))
        report = inspect_payload(version, internals, archive.getinfo(MEMORY).file_size)
        report.update({'source': str(source), 'source_sha256': digest(source.read_bytes()),
                       'entry_count': len(infos), 'status': 'Validated layout; not converted'})
        return report


def convert(source, output):
    source = Path(source).resolve(strict=True)
    output = Path(output).resolve()
    require(output.is_relative_to(OUTPUT_ROOT.resolve()),
            f'Output must be inside the isolated directory {OUTPUT_ROOT}')
    require(source != output and not output.exists(), 'Output must be a new file; replacement is refused')
    report = inspect_archive(source)
    with zipfile.ZipFile(source) as archive, source.open('rb') as raw:
        infos = archive.infolist()
        payloads = {info.filename: read_entry(archive, raw, info) for info in infos}
        archive_comment = archive.comment
    require(digest(source.read_bytes()) == report['source_sha256'], 'Source changed while reading')
    before_hashes = {name: digest(data) for name, data in payloads.items()}
    original_ram = payloads[MEMORY]
    original_internal = payloads[INTERNAL]
    internal = bytearray(original_internal)
    internal[report['extra_memory_offset']] = 1
    payloads[INTERNAL] = bytes(internal)
    payloads[MEMORY] = original_ram + bytes(TOTAL_RAM - MAIN_RAM)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing any runtime state or previous output.
    with output.open('xb') as out_file:
        with zipfile.ZipFile(out_file, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as archive:
            archive.comment = archive_comment
            for old_info in infos:
                info = copy.copy(old_info)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.extra = b''  # Recreate ZIP size/checksum metadata for changed entries.
                archive.writestr(info, payloads[info.filename], compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=1)
    # Reopen and compare every uncompressed entry, including all 96 MB of padding.
    with zipfile.ZipFile(output) as archive:
        require(archive.namelist() == [info.filename for info in infos], 'Output entry order changed')
        require(archive.testzip() is None, 'Output ZIP checksum validation failed')
        for name, expected in payloads.items():
            actual = archive.read(name)
            require(actual == expected, f'Output entry verification failed: {name}')
        require(archive.read(MEMORY)[:MAIN_RAM] == original_ram, 'Original EE RAM changed')
    require(digest(source.read_bytes()) == report['source_sha256'], 'Source changed during conversion')
    differences = [i for i, (a, b) in enumerate(zip(original_internal, payloads[INTERNAL])) if a != b]
    require(differences == [report['extra_memory_offset']], 'Unexpected internal structure changes')
    report.update({'output': str(output), 'output_sha256': digest(output.read_bytes()),
                   'status': 'Converted and archive-verified; emulator loading remains untested',
                   'new_ee_memory_size': TOTAL_RAM,
                   'changed_internal_bytes': differences,
                   'original_entry_sha256': before_hashes,
                   'sources': SOURCES,
                   'requirements': [
                       'Boot a separate v2.5.211 VM with [EmuCore/CPU] ExtraMemory=true.',
                       'Load only this converted copy; the original requires 32 MB mode.',
                       'Verify the battle, extended-memory guest canaries, and save/reload before adding heap1.',
                       'Guest CPU/TLB state is preserved. This does not initialize or expand the BT3 heap.',
                   ]})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, help='New .p2s inside analysis/converted-states')
    args = parser.parse_args()
    result = convert(args.source, args.out) if args.out else inspect_archive(args.source)
    print(json.dumps(result, indent=2))
