"""Savestate files with the Python standard library only (zipfile + zlib).

A netplay match differs between input delays (and stall limits) in one netplay_core CONTROL word each, so the kit
ships / prepares one netplay state per match (input delay 1) and makes the state for any other delay by rewriting
those words in eeMemory.bin, guarded (the old value must be the expected one) and verified (every entry is read
back; only eeMemory.bin may change, and only in those words). PCSX2 reads the Deflate archive this writes.
"""
import hashlib
import struct
import zipfile
from pathlib import Path

MEMORY = 'eeMemory.bin'
EE_SIZE = 0x8000000
_MEMORY_TOKEN = object()


class VerifiedMemory:
    """Immutable, path/SHA/size-bound RAM from a fully checked compact decode.

    Nothing on disk, in metadata, or supplied by a peer can enable this path.
    Every reuse still hashes the complete current archive. The corresponding
    decoder proved every machine entry, ZIP CRC and original archive byte.
    """

    __slots__ = ('_path', '_sha', '_size', '_memory')

    def __init__(self, path, decoded, token):
        if token is not _MEMORY_TOKEN:
            raise ValueError('Verified memory requires the complete decoder receipt')
        object.__setattr__(self, '_path', Path(path).resolve())
        object.__setattr__(self, '_sha', decoded.archive_sha256)
        object.__setattr__(self, '_size', len(decoded.archive))
        object.__setattr__(self, '_memory', decoded.memory)

    def __setattr__(self, name, value):
        raise AttributeError('Verified memory is immutable')

    def read(self, path, expected_sha=None, expected_size=None):
        path = Path(path)
        if path.resolve() != self._path or expected_sha is not None and expected_sha != self._sha or \
                expected_size is not None and expected_size != self._size or \
                path.stat().st_size != self._size or sha256(path) != self._sha:
            raise ValueError('The verified decoded archive identity changed')
        return self._memory


def decoded_memory(path, decoded):
    """Bind only a decoder-created receipt to its fully hashed published file."""
    import kit_wire_codec
    if type(decoded) is not kit_wire_codec.DecodedState or type(decoded.memory) is not bytes or \
            len(decoded.memory) != EE_SIZE or type(decoded.archive) is not bytes or \
            hashlib.sha256(decoded.archive).hexdigest() != decoded.archive_sha256:
        raise ValueError('Invalid complete decoded archive receipt')
    value = VerifiedMemory(path, decoded, _MEMORY_TOKEN)
    value.read(path)
    return value


def _read_all(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        for info in infos:
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError(f'{Path(path).name}: entry {info.filename} uses compression method '
                                 f'{info.compress_type} (only Deflate states can be changed here)')
        return infos, {info.filename: archive.read(info.filename) for info in infos}, archive.comment


class StateArchive:
    """An immutable source archive decoded once for selection and guarded edits.

    Every payload is still read through zipfile's CRC checks. Reusing this
    snapshot lets machine-copy selection and its write use exactly the same
    bytes, rather than inflating 128 MiB twice.
    """

    def __init__(self, source):
        self.source = Path(source)
        self.source_sha256 = sha256(self.source)
        self.infos, self.payloads, self.comment = _read_all(self.source)
        if sha256(self.source) != self.source_sha256:
            raise ValueError(f'{self.source.name} changed while reading')
        self.memory = self.payloads.get(MEMORY)
        if self.memory is None or len(self.memory) != EE_SIZE:
            raise ValueError(f'{self.source.name} has no 128 MiB eeMemory.bin')
        if len(self.payloads) != len(self.infos):
            raise ValueError(f'{self.source.name} has duplicate archive entries')

    def words(self, addresses):
        return {a: struct.unpack_from('<I', self.memory, a)[0] for a in addresses}


def _verify_all(path, infos, payloads, comment):
    """Read back every byte and CRC without allocating another full EE image."""
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != [i.filename for i in infos] or archive.comment != comment:
            return False
        for info in infos:
            expected = memoryview(payloads[info.filename])
            offset = 0
            with archive.open(info.filename) as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    if chunk != expected[offset:offset + len(chunk)]:
                        return False
                    offset += len(chunk)
            if offset != len(expected):
                return False
    return True


def read_words(path, addresses):
    """{address: u32} of eeMemory.bin words of a Deflate (or stored) state."""
    with zipfile.ZipFile(path) as archive:
        data = archive.read(MEMORY)
    return {a: struct.unpack_from('<I', data, a)[0] for a in addresses}


def read_memory(path):
    """The whole eeMemory.bin (128 MiB) of a Deflate (or stored) state."""
    with zipfile.ZipFile(path) as archive:
        data = archive.read(MEMORY)
    if len(data) != EE_SIZE:
        raise ValueError(f'{Path(path).name} has no 128 MiB eeMemory.bin')
    return data


def read_bytes(path, address, length):
    with zipfile.ZipFile(path) as archive:
        data = archive.read(MEMORY)
    return bytes(data[address:address + length])


def patch_words(source, target, words, blocks=None, *, archive=None):
    """Write `target` = `source` with eeMemory words {address: (expected, new)} and byte blocks {address:
    (expected bytes, new bytes)} changed (guarded: every old value must be the expected one). Returns the target
    SHA-256. `archive`, when supplied, must be a StateArchive of this source;
    it avoids a second decode after deriving the exact edits from its memory."""
    source, target = Path(source), Path(target)
    state = StateArchive(source) if archive is None else archive
    if not isinstance(state, StateArchive) or state.source.resolve() != source.resolve():
        raise ValueError('The decoded archive does not belong to this source')
    if sha256(source) != state.source_sha256:
        raise ValueError(f'{source.name} changed after reading')
    infos, payloads, comment = state.infos, dict(state.payloads), state.comment
    ram = bytearray(state.memory)
    for address, (expected, new) in sorted(words.items()):
        if address % 4 or not 0 <= address < EE_SIZE:
            raise ValueError(f'bad word address {address:#x}')
        actual = struct.unpack_from('<I', ram, address)[0]
        if actual != expected:
            raise ValueError(f'{source.name}: word {address:#010x} is {actual:#x}, expected {expected:#x}')
        struct.pack_into('<I', ram, address, new)
    for address, (expected, new) in sorted((blocks or {}).items()):
        if len(expected) != len(new) or not 0 <= address <= EE_SIZE - len(new):
            raise ValueError(f'bad block at {address:#x}')
        if bytes(ram[address:address + len(expected)]) != bytes(expected):
            raise ValueError(f'{source.name}: the bytes at {address:#010x} are not the expected ones')
        ram[address:address + len(new)] = new
    payloads[MEMORY] = bytes(ram)
    tmp = target.with_name(target.name + '.part')
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.comment = comment
        for old in infos:
            info = zipfile.ZipInfo(old.filename, date_time=old.date_time)
            info.compress_type = zipfile.ZIP_STORED if old.compress_type == zipfile.ZIP_STORED else \
                zipfile.ZIP_DEFLATED
            info.external_attr = old.external_attr
            # ZipFile's compresslevel is NOT inherited by explicit ZipInfo
            # objects: omitting this silently uses the much slower level 6.
            archive.writestr(info, payloads[old.filename], compresslevel=1)
    if not _verify_all(tmp, infos, payloads, comment):               # read back: every entry, every byte
        tmp.unlink()
        raise ValueError(f'{target.name}: verification after writing failed')
    if sha256(source) != state.source_sha256:
        tmp.unlink()
        raise ValueError(f'{source.name} changed during patching')
    tmp.replace(target)
    return sha256(target)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()
