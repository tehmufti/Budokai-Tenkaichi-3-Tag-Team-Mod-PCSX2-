"""Bounded authoritative savestate reconstruction from a verified local ISO.

Callers obtain the expected archive hash and ISO hash from the room handshake.
The wire carries integer disc file IDs, never paths. All entry bytes and the
entire original archive must match after reconstruction; otherwise callers
fall back to the ordinary snapshot transfer.
"""
from dataclasses import dataclass
import hashlib
import io
import json
import struct
import threading
import time
import zlib
import zipfile
from pathlib import Path

import numpy as np
import zstandard as zstd

from iso_compatibility.adapters import BY_NAME, runtime_match, verify_stage_mapping
from iso_compatibility.disc import Disc, package

MAGIC = b'TTMISOR1'
SCHEMA = 'ttm-isoref-wire-1'
MiB = 1 << 20
EE_SIZE = 128 * MiB
MAX_ARCHIVE = 64 * MiB
MAX_HEADER = 1 * MiB
MAX_WIRE = 64 * MiB
MAX_EXPANDED = 384 * MiB
MAX_REFERENCES = 64
ENTRY_LIMITS = {
    'PCSX2 Savestate Version.id': 4096,
    'PCSX2 Internal Structures.dat': 8 * MiB,
    'eeMemory.bin': EE_SIZE,
    'iopMemory.bin': 8 * MiB,
    'eeHwRegs.bin': 65536,
    'iopHwRegs.bin': 65536,
    'Scratchpad.bin': 65536,
    'vu0Memory.bin': 65536,
    'vu1Memory.bin': 65536,
    'vu0MicroMem.bin': 65536,
    'vu1MicroMem.bin': 65536,
    'SPU2.bin': 8 * MiB,
    'USB.bin': 1 * MiB,
    'PAD.bin': 1 * MiB,
    'GS.bin': 8 * MiB,
    'Screenshot.png': 4 * MiB,
}
# The screenshot is an emulator thumbnail, not part of the simulated machine.
# Some ordinary PCSX2 configurations omit it; all machine entries stay required.
OPTIONAL_ENTRIES = frozenset({'Screenshot.png'})
REQUIRED_ENTRIES = frozenset(ENTRY_LIMITS) - OPTIONAL_ENTRIES


class WireRejected(ValueError):
    """Corrupt or unsafe packet; never load its reconstructed state."""


class FallbackRequired(WireRejected):
    """Valid environment/state outside the prototype; use ordinary transfer."""


def require(ok, message, error=WireRejected):
    if not ok:
        raise error(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def unchanged_stamp(path):
    value = Path(path).stat()
    return value.st_size, value.st_mtime_ns, value.st_ctime_ns


def file_digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * MiB), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


class VerifiedIso:
    """Room-scoped identity and bounded file-ID reader; verifies the full ISO once.

    The selected path comes only from local installation settings. The remote
    packet cannot select a filesystem path. A changed file invalidates this
    context; create a fresh context and verify its complete hash before reuse.
    """

    def __init__(self, local_path, expected_sha256, *, adapter='bt3-usa'):
        require(valid_digest(expected_sha256), 'Invalid expected ISO hash')
        require(adapter == 'bt3-usa', 'Only BT3 USA is prototyped', FallbackRequired)
        self.path = Path(local_path)
        self._lock = threading.RLock()
        self.stamp = unchanged_stamp(self.path)
        start = time.perf_counter()
        actual = file_digest(self.path)
        require(unchanged_stamp(self.path) == self.stamp, 'ISO changed during identity verification')
        require(actual == expected_sha256, 'Full ISO identity mismatch')
        self.sha256 = actual
        self.verification_seconds = time.perf_counter() - start
        self.disc = None
        try:
            self.disc = Disc(self.path)
            found, evidence = runtime_match(self.disc)
            require(found is not None and evidence.get('verified') and found.name == adapter,
                    'ISO executable/add-on adapter is unsupported', FallbackRequired)
            verify_stage_mapping(self.disc, found)
            self.adapter = found
            self.allowed = self._allowed_file_ids()
            self._fresh()
        except BaseException:
            self.close()
            raise

    def _allowed_file_ids(self):
        adapter = self.adapter
        raw = self.disc.read(adapter.character_table_file)
        lo, hi = package(raw)[0]
        table = raw[lo:hi]
        require(adapter.characters * 60 <= len(table) < (adapter.characters + 1) * 60,
                'Changed character selection table', FallbackRequired)
        counts = [struct.unpack_from('<H', table, 60 * c + 10)[0] for c in range(adapter.characters)]
        require(all(1 <= count <= 4 for count in counts), 'Changed costume counts', FallbackRequired)
        files = set()
        for c, count in enumerate(counts):
            for costume in range(count):
                for damaged in (False, True):
                    files.update(adapter.files(c, costume, damaged, counts))
        for stage in range(adapter.stage_count):
            files.update((adapter.stage_base + stage, adapter.split_stage_base + stage,
                          adapter.stage_effect_base + stage))
        return files

    def _fresh(self):
        require(self.disc is not None, 'Verified ISO context is closed')
        require(unchanged_stamp(self.path) == self.stamp, 'Verified ISO changed; reverify its identity')

    def asset(self, file_id):
        require(integer(file_id, 1, 3399) and file_id in self.allowed, 'Unapproved or invalid disc file ID')
        # Disc caches seekable volume streams. Concurrent encoding/decoding
        # must not interleave seeks and reads on one persistent room context.
        with self._lock:
            self._fresh()
            member, offset, size = self.disc.locate(file_id)
            require(member == '/DATA/PZS3US1.AFS;1' and 0 < size <= 32 * MiB,
                    'Unapproved resource volume or size')
            raw = self.disc.read(file_id)
            self._fresh()
        require(len(raw) == size, 'Truncated local resource')
        return raw, dict(file_id=file_id, volume=1, iso_offset=offset, length=size, file_sha256=digest(raw))

    def referenced_asset(self, reference):
        require(isinstance(reference, dict) and set(reference) == {
            'file_id', 'volume', 'iso_offset', 'length', 'file_sha256', 'destination', 'overlay_offset'},
            'Invalid reference fields')
        require(integer(reference['volume'], 1, 1), 'Unapproved resource volume')
        require(integer(reference['iso_offset'], 0, self.stamp[0]), 'Invalid ISO extent')
        require(integer(reference['length'], 1, 32 * MiB), 'Invalid referenced resource size')
        require(valid_digest(reference['file_sha256']), 'Invalid resource hash')
        raw, wanted = self.asset(reference['file_id'])
        for name, value in wanted.items():
            require(reference[name] == value, 'Local resource identity/extent differs from the host')
        return raw

    def close(self):
        with self._lock:
            if self.disc is not None:
                self.disc.close()
                self.disc = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def detect_references(ram, iso):
    """Original file bindings plus the native loaded MAPD pointer, not scans."""
    require(len(ram) == EE_SIZE, 'Expected 128 MiB EE image')
    u = lambda address: struct.unpack_from('<I', ram, address)[0]
    count = u(0xD8084)
    require(2 <= count <= 10 and u(0xD8080) == 1, 'Unsupported native fighter table', FallbackRequired)
    refs, seen = [], set()
    for slot in range(count):
        actor = u(0xD8040 + slot * 4)
        require(0x100000 <= actor <= EE_SIZE - 0x1600 and actor % 16 == 0,
                'Invalid actor pointer', FallbackRequired)
        model_id = u(actor + 12)
        require(model_id < 12, 'Unsupported model slot', FallbackRequired)
        model = u(0x31C640 + model_id * 4)
        require(0x100000 <= model <= EE_SIZE - 0x1700, 'Invalid model pointer', FallbackRequired)
        resource = u(model + 20)
        require(0x100000 <= resource <= EE_SIZE - 56, 'Invalid resource pointer', FallbackRequired)
        for entry in range(3):
            destination, allocated, file_id = struct.unpack_from('<3I', ram, resource + entry * 16)
            if destination == 0 and allocated == 0 and file_id == 0xFFFFFFFF:
                continue
            raw, ref = iso.asset(file_id)
            require(allocated >= len(raw) and allocated - len(raw) < 2048,
                    'Resource allocation differs from its disc file', FallbackRequired)
            key = destination, len(raw), file_id
            if key in seen:
                continue
            seen.add(key)
            ref['destination'] = destination
            refs.append(ref)
    # The converted single-view snapshot can retain either stage representation.
    # Accept a uniquely identified package header; ambiguity simply omits this
    # optional optimization and retains the complete authoritative stage bytes.
    stage_id = u(0x331DC8 + 0x28)
    require(stage_id < iso.adapter.stage_count, 'Invalid selected stage', FallbackRequired)
    stage_ptr = u(0x2FEBE0)
    candidates = []
    for first in (iso.adapter.stage_base, iso.adapter.split_stage_base):
        raw, ref = iso.asset(first + stage_id)
        try:
            first_entry = package(raw)[0][0]
        except ValueError:
            continue
        destination = stage_ptr - first_entry
        if (0x100000 <= destination <= EE_SIZE - len(raw)
                and ram[destination:destination + 32] == raw[:32]):
            ref['destination'] = destination
            candidates.append(ref)
    if len(candidates) == 1:
        refs.append(candidates[0])
    elif candidates and all(r['file_sha256'] == candidates[0]['file_sha256'] for r in candidates):
        refs.append(candidates[0])
    return refs


def no_overlap(spans, limit, message):
    end = 0
    for start, length in spans:
        require(integer(start, 0, limit) and integer(length, 1, limit) and start + length <= limit,
                message + ': outside bounds')
    for start, length in sorted(spans):
        require(start >= end, message + ': overlaps')
        end = start + length


def deflate(raw):
    compressor = zlib.compressobj(1, zlib.DEFLATED, -15)
    return compressor.compress(raw) + compressor.flush()


def zip_layout(archive):
    """Bound the directory before ZipFile allocates or inflates any entries.

    This prototype deliberately supports the ordinary, single-disc, non-ZIP64
    Deflate archives the online state writer produces. Unexpected extensions
    use the original snapshot instead of being guessed at. The same check is
    valid for the skeleton because it reads no compressed payload bytes.
    """
    require(isinstance(archive, (bytes, bytearray)) and 22 <= len(archive) <= MAX_ARCHIVE,
            'Invalid ZIP archive bounds')
    # EOCD can occur inside the comment. Accept exactly one candidate whose
    # declared comment ends at EOF; arbitrary trailing data is unsupported.
    candidates = []
    lo = max(0, len(archive) - 22 - 65535)
    for offset in range(len(archive) - 22, lo - 1, -1):
        if archive[offset:offset + 4] == b'PK\x05\x06':
            fields = struct.unpack_from('<4s4H2IH', archive, offset)
            if offset + 22 + fields[-1] == len(archive):
                candidates.append((offset, fields))
    require(len(candidates) == 1, 'Missing or ambiguous ZIP directory')
    end, fields = candidates[0]
    _, disk, directory_disk, disk_count, count, directory_size, directory_offset, _ = fields
    require(disk == directory_disk == 0 and disk_count == count,
            'Multi-disc ZIP state is unsupported', FallbackRequired)
    require(len(REQUIRED_ENTRIES) <= count <= len(ENTRY_LIMITS), 'Invalid archive entry count')
    require(0 < directory_size <= end and 0 <= directory_offset < end
            and directory_offset + directory_size == end,
            'ZIP directory outside bounds or unsupported extension')
    entries, local_spans, names, position = [], [], set(), directory_offset
    for _ in range(count):
        require(position + 46 <= end and archive[position:position + 4] == b'PK\x01\x02',
                'Invalid ZIP central header')
        f = struct.unpack_from('<4s6H3I5H2I', archive, position)
        (_, _, needed, flags, compression, _, _, crc, packed, size,
         name_size, extra_size, comment_size, member_disk, _, _, local) = f
        require(flags == 0 and compression in (0, 8),
                'Unsupported ZIP flags/compression', FallbackRequired)
        require(needed <= 20 and member_disk == 0,
                'ZIP64 or advanced ZIP state is unsupported', FallbackRequired)
        next_position = position + 46 + name_size + extra_size + comment_size
        require(0 < name_size <= 128 and next_position <= end, 'ZIP central metadata outside bounds')
        name_bytes = archive[position + 46:position + 46 + name_size]
        try:
            name = name_bytes.decode('ascii')
        except UnicodeError as error:
            raise FallbackRequired('Unsupported archive entry name encoding') from error
        require(name in ENTRY_LIMITS, 'Unsupported archive entry names', FallbackRequired)
        require(name not in names, 'Duplicate archive entry')
        names.add(name)
        require(0 < size <= ENTRY_LIMITS[name] and 0 < packed <= MAX_ARCHIVE,
                'Excessive archive entry')
        require(name != 'eeMemory.bin' or size == EE_SIZE, 'Expected 128 MiB EE image')
        require(compression != 0 or packed == size, 'Stored ZIP entry lengths disagree')
        require(0 <= local <= directory_offset - 30 and archive[local:local + 4] == b'PK\x03\x04',
                'Invalid ZIP local header')
        lf = struct.unpack_from('<4s5H3I2H', archive, local)
        require(lf[1] == needed and lf[2] == flags and lf[3] == compression
                and lf[6:9] == (crc, packed, size), 'ZIP header/central-directory mismatch')
        offset = local + 30 + lf[-2] + lf[-1]
        require(offset <= directory_offset and offset + packed <= directory_offset,
                'ZIP local entry overlaps its directory or lies outside bounds')
        require(lf[-2] == name_size and archive[local + 30:local + 30 + name_size] == name_bytes,
                'ZIP local entry name differs from its directory')
        entries.append(dict(name=name, length=size, compression=compression,
                            zip_offset=offset, zip_length=packed))
        local_spans.append((local, offset + packed - local))
        position = next_position
    require(position == end and REQUIRED_ENTRIES.issubset(names), 'ZIP directory length or entries differ')
    no_overlap(local_spans, directory_offset, 'ZIP local header/payload regions')
    return entries


def load_archive(archive, *, fresh_proof=None):
    require(0 < len(archive) <= MAX_ARCHIVE, 'Archive size exceeds bounds')
    from kit_wire import FreshArchiveProof
    canonical = type(fresh_proof) is FreshArchiveProof and fresh_proof.matches(digest(archive), len(archive))
    layout = zip_layout(archive)
    skeleton = bytearray(archive)
    entries, payloads, spans = [], [], []
    try:
        state = zipfile.ZipFile(io.BytesIO(archive))
    except (zipfile.BadZipFile, ValueError, struct.error) as error:
        raise WireRejected('Invalid ZIP archive') from error
    with state:
        infos = state.infolist()
        require(len(REQUIRED_ENTRIES) <= len(infos) <= len(ENTRY_LIMITS), 'Invalid archive entry count')
        require(len({i.filename for i in infos}) == len(infos), 'Duplicate archive entry')
        names = {i.filename for i in infos}
        require(REQUIRED_ENTRIES.issubset(names) and names.issubset(ENTRY_LIMITS),
                'Unsupported archive entry names', FallbackRequired)
        for info, row in zip(infos, layout):
            require(info.filename == row['name'] and info.file_size == row['length']
                    and info.compress_size == row['zip_length'], 'ZIP directory parser disagreement')
            require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                    'Unsupported savestate compression', FallbackRequired)
            require(info.flag_bits == 0, 'Unsupported ZIP flags/encryption/descriptors', FallbackRequired)
            require(0 < info.file_size <= ENTRY_LIMITS[info.filename], 'Excessive archive entry')
            require(info.filename != 'eeMemory.bin' or info.file_size == EE_SIZE, 'Expected 128 MiB EE image')
            h = info.header_offset
            require(0 <= h <= len(archive) - 30 and archive[h:h + 4] == b'PK\x03\x04', 'Invalid ZIP local header')
            fields = struct.unpack_from('<I5H3I2H', archive, h)
            offset = h + 30 + fields[-2] + fields[-1]
            require(fields[2] == info.flag_bits and fields[3] == info.compress_type,
                    'ZIP header/central-directory mismatch')
            require(fields[6] == info.CRC and fields[7] == info.compress_size and fields[8] == info.file_size,
                    'ZIP entry lengths/CRC disagree')
            require(offset + info.compress_size <= len(archive), 'ZIP payload outside archive')
            try:
                raw = state.read(info)  # Includes CRC verification.
            except (zipfile.BadZipFile, RuntimeError, EOFError, ValueError, zlib.error) as error:
                raise WireRejected('Invalid ZIP payload or CRC') from error
            if not canonical:
                encoded = raw if info.compress_type == zipfile.ZIP_STORED else deflate(raw)
                require(encoded == archive[offset:offset + info.compress_size],
                        'ZIP Deflate representation is not reproducible by this runtime', FallbackRequired)
            skeleton[offset:offset + info.compress_size] = bytes(info.compress_size)
            entries.append(dict(name=info.filename, length=len(raw), sha256=digest(raw),
                                compression=info.compress_type, zip_offset=offset, zip_length=info.compress_size))
            payloads.append(raw)
            spans.append((offset, info.compress_size))
    no_overlap(spans, len(archive), 'ZIP compressed payload regions')
    return bytes(skeleton), entries, payloads


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON field')
        result[key] = value
    return result


def header_of(wire):
    require(isinstance(wire, bytes) and 12 <= len(wire) <= MAX_WIRE, 'Wire size/type exceeds bounds')
    require(wire[:8] == MAGIC, 'Unknown wire format', FallbackRequired)
    size = struct.unpack_from('<I', wire, 8)[0]
    require(0 < size <= MAX_HEADER and 12 + size <= len(wire), 'Invalid wire header size')
    try:
        manifest = json.loads(wire[12:12 + size], object_pairs_hook=strict_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(WireRejected('Invalid JSON number')))
    except WireRejected:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise WireRejected('Invalid wire header JSON') from error
    require(isinstance(manifest, dict), 'Wire header is not an object')
    return manifest, wire[12 + size:]


def pack(manifest, component_data):
    """Used by encoder and negative tests; all lengths/hashes are self-describing."""
    manifest = dict(manifest)
    components, encoded, position = [], [], 0
    for raw in component_data:
        compressed = zstd.ZstdCompressor(level=10, write_checksum=True).compress(raw)
        components.append(dict(offset=position, packed=len(compressed), length=len(raw), sha256=digest(raw),
                               packed_sha256=digest(compressed)))
        encoded.append(compressed); position += len(compressed)
    manifest['components'] = components
    header = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')
    require(len(header) <= MAX_HEADER, 'Wire metadata exceeds bounds')
    wire = MAGIC + struct.pack('<I', len(header)) + header + b''.join(encoded)
    require(len(wire) <= MAX_WIRE, 'Encoded wire exceeds bounds')
    return wire


@dataclass(frozen=True)
class EncodedState:
    wire: bytes
    archive_sha256: str
    seconds: float
    reference_count: int
    referenced_bytes: int


def encode_state(source, iso, *, fresh_proof=None):
    """Return compact wire bytes; source is a local path, never sent remotely."""
    start = time.perf_counter()
    before = unchanged_stamp(source)
    require(0 < before[0] <= MAX_ARCHIVE, 'Source archive size exceeds bounds')
    with Path(source).open('rb') as stream:
        archive = stream.read(MAX_ARCHIVE + 1)
    require(0 < len(archive) <= MAX_ARCHIVE, 'Source archive size exceeds bounds')
    require(unchanged_stamp(source) == before, 'State changed while reading')
    archive_sha = digest(archive)
    skeleton, entries, payloads = load_archive(archive, fresh_proof=fresh_proof)
    del archive
    ram_index = next(i for i, entry in enumerate(entries) if entry['name'] == 'eeMemory.bin')
    ram = payloads[ram_index]
    references = detect_references(ram, iso)
    require(0 < len(references) <= MAX_REFERENCES, 'Invalid reference count')
    no_overlap([(r['destination'], r['length']) for r in references], EE_SIZE, 'Resource destination')
    residual = bytearray(ram)
    overlays, overlay_offset = [], 0
    for reference in references:
        raw, expected = iso.asset(reference['file_id'])
        require(all(reference[name] == value for name, value in expected.items()), 'Resource changed during encoding')
        p, size = reference['destination'], len(raw)
        require(p >= 0x100000, 'Resource overlaps low code memory')
        overlay = np.bitwise_xor(np.frombuffer(raw, np.uint8), np.frombuffer(ram[p:p + size], np.uint8)).tobytes()
        overlays.append(overlay)
        reference['overlay_offset'] = overlay_offset
        overlay_offset += size
        residual[p:p + size] = bytes(size)
    # The compressor accepts buffer objects; avoid another 128 MiB EE copy.
    payloads[ram_index] = residual
    del ram
    manifest = dict(schema=SCHEMA, iso_sha256=iso.sha256, adapter=iso.adapter.name,
                    archive_sha256=archive_sha, archive_length=len(skeleton),
                    zlib_version=zlib.ZLIB_RUNTIME_VERSION, entries=entries, references=references)
    overlay_bytes = b''.join(overlays)
    overlays.clear()
    wire = pack(manifest, [skeleton] + payloads + [overlay_bytes])
    iso._fresh()
    require(unchanged_stamp(source) == before, 'State changed during encoding')
    return EncodedState(wire, manifest['archive_sha256'], time.perf_counter()-start,
                        len(references), overlay_offset)


def unpack_components(manifest, payload):
    components = manifest.get('components')
    require(isinstance(components, list) and isinstance(manifest.get('entries'), list)
            and len(REQUIRED_ENTRIES) + 2 <= len(components) <= len(ENTRY_LIMITS) + 2
            and len(components) == len(manifest['entries']) + 2,
            'Invalid component count')
    raw_total, packed_end = 0, 0
    for row in components:
        require(isinstance(row, dict) and set(row) == {'offset', 'packed', 'length', 'sha256', 'packed_sha256'},
                'Invalid component fields')
        require(integer(row['offset'], 0, MAX_WIRE) and row['offset'] == packed_end,
                'Component offset does not match stream')
        require(integer(row['packed'], 1, MAX_WIRE) and integer(row['length'], 1, EE_SIZE),
                'Invalid component lengths')
        require(valid_digest(row['sha256']) and valid_digest(row['packed_sha256']), 'Invalid component hash')
        packed_end += row['packed']; raw_total += row['length']
        require(packed_end <= len(payload) and raw_total <= MAX_EXPANDED, 'Component sizes exceed bounds')
    require(packed_end == len(payload), 'Trailing or truncated wire payload')
    raw_components = []
    for row in components:
        compressed = payload[row['offset']:row['offset'] + row['packed']]
        require(digest(compressed) == row['packed_sha256'], 'Corrupt compressed component')
        try:
            params = zstd.get_frame_parameters(compressed)
            require(params.content_size == row['length'] and params.window_size <= EE_SIZE,
                    'Unbounded or unexpected Zstandard frame')
            raw = zstd.ZstdDecompressor().decompress(compressed, max_output_size=row['length'], allow_extra_data=False)
        except zstd.ZstdError as error:
            raise WireRejected('Invalid compressed component') from error
        require(len(raw) == row['length'] and digest(raw) == row['sha256'], 'Expanded component differs')
        raw_components.append(raw)
    return raw_components


_DECODE_TOKEN = object()


@dataclass(frozen=True, init=False)
class DecodedState:
    """An ephemeral complete decode, created only after archive/entry verification."""
    archive: bytes
    memory: bytes
    archive_sha256: str

    def __init__(self, archive, memory, sha256, token):
        if token is not _DECODE_TOKEN:
            raise ValueError('A decoded receipt requires the verified decoder')
        object.__setattr__(self, 'archive', archive)
        object.__setattr__(self, 'memory', memory)
        object.__setattr__(self, 'archive_sha256', sha256)


def decode_state(wire, iso, expected_archive_sha256):
    return _decode_state(wire, iso, expected_archive_sha256, retain_memory=False)


def decode_state_with_memory(wire, iso, expected_archive_sha256):
    """Same complete checks as decode_state; retain the already proved EE image."""
    return _decode_state(wire, iso, expected_archive_sha256, retain_memory=True)


def _decode_state(wire, iso, expected_archive_sha256, *, retain_memory):
    """Return exact original archive bytes or raise; never writes/loads anything."""
    require(valid_digest(expected_archive_sha256), 'Invalid expected state hash')
    manifest, payload = header_of(wire)
    require(set(manifest) == {'schema', 'iso_sha256', 'adapter', 'archive_sha256', 'archive_length',
                             'zlib_version', 'entries', 'references', 'components'}, 'Unexpected manifest fields')
    require(manifest['schema'] == SCHEMA, 'Unsupported wire schema', FallbackRequired)
    require(manifest['iso_sha256'] == iso.sha256 and manifest['adapter'] == iso.adapter.name,
            'Wire ISO identity differs')
    require(manifest['archive_sha256'] == expected_archive_sha256, 'Wire state identity differs')
    require(manifest['zlib_version'] == zlib.ZLIB_RUNTIME_VERSION,
            'Different zlib runtime; ordinary transfer required', FallbackRequired)
    require(integer(manifest['archive_length'], 1, MAX_ARCHIVE), 'Invalid archive length')
    entries, references = manifest['entries'], manifest['references']
    require(isinstance(entries, list) and len(REQUIRED_ENTRIES) <= len(entries) <= len(ENTRY_LIMITS),
            'Invalid entry count')
    names, spans = set(), []
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {'name', 'length', 'sha256', 'compression', 'zip_offset', 'zip_length'},
                'Invalid entry fields')
        name = entry['name']
        require(isinstance(name, str) and name in ENTRY_LIMITS and name not in names, 'Invalid or duplicate entry name')
        names.add(name)
        require(integer(entry['length'], 1, ENTRY_LIMITS[name]) and valid_digest(entry['sha256']), 'Invalid entry size/hash')
        require(name != 'eeMemory.bin' or entry['length'] == EE_SIZE, 'Invalid EE image size')
        require(integer(entry['compression'], 0, 8) and entry['compression'] in (0, 8),
                'Unsupported entry compression', FallbackRequired)
        spans.append((entry['zip_offset'], entry['zip_length']))
    require(REQUIRED_ENTRIES.issubset(names), 'Missing required machine entry')
    no_overlap(spans, manifest['archive_length'], 'ZIP compressed regions')
    require(isinstance(references, list) and 0 < len(references) <= MAX_REFERENCES, 'Invalid reference count')
    refs_spans, overlay_end = [], 0
    for ref in references:
        require(isinstance(ref, dict) and integer(ref.get('destination'), 0x100000, EE_SIZE - 1)
                and integer(ref.get('length'), 1, 32 * MiB), 'Invalid resource destination/length')
        require(type(ref.get('overlay_offset')) is int and ref['overlay_offset'] == overlay_end,
                'Invalid XOR overlay offset')
        refs_spans.append((ref['destination'], ref['length'])); overlay_end += ref['length']
    no_overlap(refs_spans, EE_SIZE, 'Resource destinations')
    components = manifest.get('components')
    require(isinstance(components, list) and len(components) == len(entries) + 2, 'Invalid component count')
    # Check shape agreement before accepting any compressed allocation.
    wanted_lengths = [manifest['archive_length']] + [e['length'] for e in entries] + [overlay_end]
    require(all(isinstance(c, dict) and c.get('length') == wanted for c, wanted in zip(components, wanted_lengths)),
            'Component size does not match its semantic content')
    # Validate every disc reference before decompressing large packet buffers.
    for ref in references:
        iso.referenced_asset(ref)
    raw_components = unpack_components(manifest, payload)
    skeleton, payloads, overlays = raw_components[0], raw_components[1:-1], raw_components[-1]
    require(len(skeleton) == manifest['archive_length'] and len(overlays) == overlay_end,
            'Skeleton/XOR length differs')
    layout = zip_layout(skeleton)
    require(len(layout) == len(entries)
            and all(all(entry[name] == row[name] for name in row) for entry, row in zip(entries, layout)),
            'ZIP skeleton directory differs from the wire entries')
    ram_index = next(i for i, entry in enumerate(entries) if entry['name'] == 'eeMemory.bin')
    ram = bytearray(payloads[ram_index])
    payloads[ram_index] = ram
    del raw_components
    for reference in references:
        source = iso.referenced_asset(reference)
        p, size, off = reference['destination'], reference['length'], reference['overlay_offset']
        require(not np.any(np.frombuffer(ram, np.uint8, count=size, offset=p)),
                'Resource holes contain unexpected bytes')
        ram[p:p + size] = np.bitwise_xor(np.frombuffer(source, np.uint8),
                                       np.frombuffer(overlays, np.uint8, count=size, offset=off)).tobytes()
    archive = bytearray(skeleton)
    del skeleton
    for entry, raw in zip(entries, payloads):
        require(len(raw) == entry['length'] and digest(raw) == entry['sha256'], 'Reconstructed entry hash differs')
        encoded = raw if entry['compression'] == zipfile.ZIP_STORED else deflate(raw)
        require(len(encoded) == entry['zip_length'], 'Deflate output length differs', FallbackRequired)
        p, size = entry['zip_offset'], len(encoded)
        require(not any(archive[p:p + size]), 'Archive skeleton payload holes contain bytes')
        archive[p:p + size] = encoded
    require(digest(archive) == expected_archive_sha256, 'Reconstructed whole archive hash differs', FallbackRequired)
    # Read every reconstructed entry through ZIP CRC checks and compare all
    # payload hashes again; no CPU/GS/SPU/IOP bytes are omitted or normalized.
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as state:
            require(state.namelist() == [e['name'] for e in entries], 'Reconstructed archive entry order differs')
            for entry, raw in zip(entries, payloads):
                # raw already passed the entry SHA above. Compare the actual
                # reconstructed ZIP payload byte for byte and read to EOF so
                # ZIP checks its full CRC; no entry hash/CRC proof is omitted.
                expected, offset = raw, 0
                with state.open(entry['name']) as stream:
                    for chunk in iter(lambda: stream.read(MiB), b''):
                        require(chunk == expected[offset:offset + len(chunk)], 'Final archive entry differs')
                        offset += len(chunk)
                require(offset == len(expected), 'Final archive entry length differs')
    except WireRejected:
        raise
    except (zipfile.BadZipFile, RuntimeError, EOFError, ValueError, zlib.error) as error:
        raise WireRejected('Invalid reconstructed ZIP payload or CRC') from error
    iso._fresh()
    archive = bytes(archive)
    if retain_memory:
        return DecodedState(archive, bytes(ram), expected_archive_sha256, _DECODE_TOKEN)
    return archive
