"""Preserve the native 16 KiB memory-card payload across menu rewinds.

USA native1177B8 writes *(gp-20452), length0x4000; native load11ABD0 copies
the same length back after checksum verification. These are serialized values,
not scene pointers. Never copy the card IO state machine or touch card files.
"""
from native_map import A
import configparser
import runtime_profile
import struct
from pathlib import Path

POINTER, SIZE, RAM_END = A(0x2FF28C), 0x4000, 0x2000000
ROOT = Path(__file__).resolve().parents[1]


def read(source, address, size):
    result = source.read(address,size) if hasattr(source,'read') else source[address:address+size]
    if len(result)!=size: raise ValueError('Incomplete native save-data read')
    return bytes(result)


def pointer(source):
    at=struct.unpack('<I',read(source,POINTER,4))[0]
    if at and (at%16 or not 0x100000<=at<=RAM_END-SIZE):
        raise ValueError('Native save-data pointer is invalid')
    return at


def preserve(source, target):
    """Guarded patch for an archive; source is a stable live read or RAM image."""
    live, archived=pointer(source),pointer(target)
    if not live and not archived:return {'blocks':[]}
    if not live or not archived:raise ValueError('Native save data is not loaded in both worlds')
    data=read(source,live,SIZE)
    if pointer(source)!=live or read(source,live,SIZE)!=data:
        raise ValueError('Native save data changed during capture; retry the menu return')
    old=read(target,archived,SIZE)
    return dict(blocks=[] if old==data else [dict(address=archived,expected_hex=old.hex(),data_hex=data.hex())])


def card_signature(config=None):
    """Read only metadata; configurable file and folder cards are supported."""
    config=Path(config) if config else runtime_profile.CONFIG
    parser=configparser.ConfigParser(strict=False,interpolation=None)
    parser.read(config,encoding='utf-8-sig')
    folder=Path(parser.get('Folders','MemoryCards',fallback='memcards'))
    if not folder.is_absolute():folder=config.parent.parent/folder
    cards=[]
    if parser.has_section('MemoryCards'):
        for key,value in parser.items('MemoryCards'):
            if not key.endswith('_filename'):continue
            if not parser.getboolean('MemoryCards',key[:-9]+'_enable',fallback=True):continue
            path=Path(value)
            if not path.is_absolute():path=folder/path
            if path.is_dir():paths=sorted(p for p in path.rglob('*') if p.is_file())
            else:paths=[path]
            for p in paths:
                try:s=p.stat();cards.append((str(p.resolve()),s.st_size,s.st_mtime_ns))
                except FileNotFoundError:cards.append((str(p.resolve()),None,None))
    return tuple(cards)
