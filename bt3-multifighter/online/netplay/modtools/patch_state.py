"""Apply guarded EE RAM patches to a new 128 MiB PCSX2 state copy.

Each state is checked by the layout its save version names in pcsx2_versions.json:
v2.5.211 (developer) and 2.6.x share state128's layout, 2.8.x uses state28's.

This module never accesses the emulator. Outputs are exclusive new archives
under analysis/prepared-states. All non-EE entry payloads, entry order and archive
comments are preserved; ZIP compression is normalized to DEFLATE. The caller
must separately load the verified copy into the matching ExtraMemory=true VM.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import struct
import uuid
import zipfile
from pathlib import Path

import pcsx2_versions
import state128

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / 'analysis' / 'prepared-states'
from native_map import SERIAL, CRC  # the selected disc
require = state128.require


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def inspect_payload(version, internal, memory_size):
    """Route by save version to its independently verified exact layout, without changing payloads.

    Unknown save versions raise a ValueError naming the version, the emulator tag and the
    tested PCSX2 releases. Every route returns the same keys, including `emulator`.
    """
    family = pcsx2_versions.state_family(version)
    require(memory_size == state128.TOTAL_RAM, 'Input must contain exactly 128 MiB EE RAM')
    if family['layout'] == 'state28':
        from state28 import inspect_payload as inspect28
        return inspect28(version, internal, memory_size)
    return state128.inspect_state(version, internal, memory_size)


def _json_object(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, f'Duplicate manifest key: {name}')
        result[name] = value
    return result


def load_manifest(manifest):
    if isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text(encoding='utf-8-sig'),
                              object_pairs_hook=_json_object)
    require(isinstance(manifest, dict), 'Manifest must be a JSON object')
    require(manifest.get('serial') == SERIAL, f'Manifest serial must be {SERIAL}')
    require(manifest.get('crc') == CRC, f'Manifest CRC must be {CRC}')
    raw_blocks = manifest.get('blocks')
    require(isinstance(raw_blocks, list) and raw_blocks, 'Manifest blocks must be a nonempty list')
    blocks = []
    for index, raw in enumerate(raw_blocks):
        require(isinstance(raw, dict), f'Block {index} must be an object')
        address = raw.get('address')
        require(type(address) is int and 0 <= address < state128.TOTAL_RAM,
                f'Block {index} address is outside physical EE RAM')
        values = []
        for field in ('expected_hex', 'data_hex'):
            value = raw.get(field)
            require(isinstance(value, str), f'Block {index} needs {field}')
            try:
                values.append(bytes.fromhex(value))
            except ValueError as error:
                raise ValueError(f'Block {index} has invalid {field}') from error
        expected, data = values
        require(bool(data) and len(data) == len(expected),
                f'Block {index} must have equal, nonempty expected and replacement bytes')
        require(address + len(data) <= state128.TOTAL_RAM,
                f'Block {index} extends beyond physical EE RAM')
        blocks.append((address, expected, data, index))
    ordered = sorted(blocks)
    for left, right in zip(ordered, ordered[1:]):
        require(left[0] + len(left[2]) <= right[0],
                f'Overlapping blocks {left[3]} and {right[3]}')
    return manifest, ordered


def patch_memory(ram, manifest):
    """Validate every guard against original RAM before creating a patched copy."""
    require(len(ram) == state128.TOTAL_RAM, 'Patch source must be exactly 128 MiB EE RAM')
    manifest, blocks = load_manifest(manifest)
    original_hash = state128.digest(ram)
    if 'ram_sha256' in manifest:
        require(manifest['ram_sha256'] == original_hash, 'Manifest RAM SHA256 mismatch')
    for address, expected, _, index in blocks:
        actual = ram[address:address + len(expected)]
        if actual != expected:
            first = next(i for i, (a, b) in enumerate(zip(actual, expected)) if a != b)
            raise ValueError(f'Block {index} guard mismatch at EE 0x{address + first:08X}')
    result = bytearray(ram)
    changed = 0
    for address, expected, data, _ in blocks:
        changed += sum(a != b for a, b in zip(expected, data))
        result[address:address + len(data)] = data
    return result, dict(serial=SERIAL, crc=CRC, block_count=len(blocks),
        guarded_bytes=sum(len(b[1]) for b in blocks), changed_bytes=changed,
        source_ram_sha256=original_hash, patched_ram_sha256=state128.digest(result),
        ranges=[dict(address=b[0], size=len(b[2])) for b in blocks])


def _without_zip64(extra):
    """Retain other entry metadata while allowing ZIP64 sizes to be regenerated."""
    output = bytearray()
    cursor = 0
    while cursor < len(extra):
        require(cursor + 4 <= len(extra), 'Malformed ZIP extra field header')
        kind, size = struct.unpack_from('<HH', extra, cursor)
        end = cursor + 4 + size
        require(end <= len(extra), 'Malformed ZIP extra field size')
        if kind != 1:
            output.extend(extra[cursor:end])
        cursor = end
    return bytes(output)


def patch(source, manifest, output=None):
    """Return a verified new archive report; validation failures raise ValueError."""
    source = Path(source).resolve(strict=True)
    manifest, _ = load_manifest(manifest)
    output = (Path(output) if output is not None else
              OUTPUT_ROOT / f'{source.stem}-patched-{uuid.uuid4().hex[:12]}.p2s').resolve()
    require(output.is_relative_to(OUTPUT_ROOT.resolve()),
            f'Output must be inside the isolated directory {OUTPUT_ROOT}')
    require(output.suffix.lower() == '.p2s', 'Output must be a .p2s archive')
    require(source != output and not output.exists(), 'Output must be a new file; replacement is refused')
    source_hash = file_digest(source)
    with zipfile.ZipFile(source) as archive, source.open('rb') as raw:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        require(len(names) == len(set(names)), 'Duplicate archive entry names')
        require({state128.VERSION, state128.INTERNAL, state128.MEMORY}.issubset(names),
                'Missing required state entries')
        require(archive.getinfo(state128.MEMORY).file_size == state128.TOTAL_RAM,
                'Input must contain exactly 128 MiB EE RAM')
        # read_entry verifies CRC and supports native PCSX2 Zstandard ZIP93/20.
        payloads = {info.filename: state128.read_entry(archive, raw, info) for info in infos}
        comment = archive.comment
    require(file_digest(source) == source_hash, 'Source changed while reading')
    layout = inspect_payload(payloads[state128.VERSION], payloads[state128.INTERNAL],
                             len(payloads[state128.MEMORY]))
    before_hashes = {name: state128.digest(data) for name, data in payloads.items()}
    patched, report = patch_memory(payloads[state128.MEMORY], manifest)
    payloads[state128.MEMORY] = patched
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with output.open('xb') as stream:
            created = True
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=1, allowZip64=True) as archive:
                archive.comment = comment
                for old in infos:
                    info = copy.copy(old)
                    info.extra = _without_zip64(info.extra)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, payloads[info.filename],
                                     compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
        # Verify all entries after reopening, not merely the replacement ranges.
        with zipfile.ZipFile(output) as archive, output.open('rb') as raw:
            require(archive.namelist() == names, 'Output entry names/order changed')
            require(archive.comment == comment, 'Output archive comment changed')
            for info in archive.infolist():
                actual = state128.read_entry(archive, raw, info)
                require(actual == payloads[info.filename],
                        f'Output verification failed: {info.filename}')
                if info.filename != state128.MEMORY:
                    require(state128.digest(actual) == before_hashes[info.filename],
                            f'Non-EE payload changed: {info.filename}')
        require(file_digest(source) == source_hash, 'Source changed during patching')
    except BaseException:
        # Remove only this call's exclusively created, workspace-confined file.
        if created:
            output.unlink(missing_ok=True)
        raise
    report.update(source=str(source), output=str(output), source_sha256=source_hash,
        output_sha256=file_digest(output), entry_count=len(infos),
        changed_entries=[state128.MEMORY] if report['changed_bytes'] else [],
        original_entry_sha256=before_hashes, layout=layout,
        status='Offline copy patched and archive-verified; not loaded into the emulator')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--out', type=Path, help='New .p2s within analysis/prepared-states')
    args = parser.parse_args()
    print(json.dumps(patch(args.source, args.manifest, args.out), indent=2))
