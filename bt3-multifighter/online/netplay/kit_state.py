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


def _read_all(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        for info in infos:
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError(f'{Path(path).name}: entry {info.filename} uses compression method '
                                 f'{info.compress_type} (only Deflate states can be changed here)')
        return infos, {info.filename: archive.read(info.filename) for info in infos}, archive.comment


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


def patch_words(source, target, words, blocks=None):
    """Write `target` = `source` with eeMemory words {address: (expected, new)} and byte blocks {address:
    (expected bytes, new bytes)} changed (guarded: every old value must be the expected one). Returns the target
    SHA-256."""
    source, target = Path(source), Path(target)
    infos, payloads, comment = _read_all(source)
    memory = payloads.get(MEMORY)
    if memory is None or len(memory) != EE_SIZE:
        raise ValueError(f'{source.name} has no 128 MiB eeMemory.bin')
    ram = bytearray(memory)
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
            archive.writestr(info, payloads[old.filename])
    _, check, _ = _read_all(tmp)                                     # read back: every entry, every byte
    if list(check) != [i.filename for i in infos] or any(check[k] != payloads[k] for k in check):
        tmp.unlink()
        raise ValueError(f'{target.name}: verification after writing failed')
    tmp.replace(target)
    return sha256(target)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()
