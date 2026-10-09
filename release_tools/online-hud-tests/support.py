"""Synthetic hook tests: native callees are stubs, never fabricated executable bytes."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'bt3-multifighter/online/netplay/modtools'),str(root/'bt3-multifighter/tools')]
import prototype
from native_map import elf_path
if not elf_path(prototype.ROOT).is_file():
    def unavailable(*args):
        raise AssertionError('This synthetic test attempted to read a native executable')
    prototype.elf_reader=lambda *args:(b'',(),unavailable)

import struct
def sp_adjustments(code):
    """Every 'addiu/daddiu sp,sp,imm' immediate in an assembled blob."""
    out = []
    for i in range(0, len(code) - 3, 4):
        w = struct.unpack_from('<I', code, i)[0]
        if w >> 26 in (0x09, 0x19) and (w >> 21) & 31 == 29 and (w >> 16) & 31 == 29:
            imm = w & 0xFFFF
            out.append(imm - 0x10000 if imm & 0x8000 else imm)
    return out
