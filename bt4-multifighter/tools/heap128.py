"""Offline guest-memory canary and second-heap smoke-test builders."""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import hashlib
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from team_prototype import make_block, write_manifest

CODE = 0xC9000
CONTROL = 0xC9400
HOOK = A(0x1C2A28)
PREVIOUS = 0xB0000
START = 0x02000000
END = 0x06000000
SIZE = END - START
START1 = A(0x2FF084)
END1 = A(0x2FF08C)
PROBES = (0x020C9480, 0x040C9484, 0x060C9488)
MIRRORS = tuple(pointer & 0x01FFFFFF for pointer in PROBES)
PATTERNS = (0x13572468, 0x24681357, 0x12345678)


def emit_check(a, pointer, offset, expected, failure):
    a.li(8, pointer)
    a.lw(9, 8, offset)
    a.li(10, expected)
    a.branch(5, 9, 10, failure)


def emit_canary(a):
    # Capture all original high and possible 32 MB mirror words before writes.
    for index, (high, low) in enumerate(zip(PROBES, MIRRORS)):
        for pointer, output in ((high, 32 + index * 4), (low, 44 + index * 4)):
            a.li(8, pointer)
            a.lw(9, 8)
            a.sw(9, 16, output)
    for high, pattern in zip(PROBES, PATTERNS):
        a.li(8, high)
        a.li(9, pattern)
        a.sw(9, 8)
    a.move(17, 0)
    for index, (high, low, pattern) in enumerate(zip(PROBES, MIRRORS, PATTERNS)):
        a.li(8, high)
        a.lw(9, 8)
        a.sw(9, 16, 56 + index * 4)
        a.li(10, pattern)
        a.branch(4, 9, 10, f'high_ok_{index}')
        a.addiu(17, 0, 101)
        a.label(f'high_ok_{index}')
        a.li(8, low)
        a.lw(9, 8)
        a.sw(9, 16, 68 + index * 4)
        a.lw(10, 16, 44 + index * 4)
        a.branch(4, 9, 10, f'low_ok_{index}')
        a.addiu(17, 0, 102)
        a.label(f'low_ok_{index}')
    # Always restore high words and low mirrors, including on failed reads.
    for index, high in enumerate(PROBES):
        a.li(8, high)
        a.lw(9, 16, 32 + index * 4)
        a.sw(9, 8)
    for index, low in enumerate(MIRRORS):
        a.li(8, low)
        a.lw(9, 16, 44 + index * 4)
        a.sw(9, 8)
    a.branch(5, 17, 0, 'result')
    a.addiu(17, 0, 5)


def emit_heap(a):
    emit_check(a, START1, 0, 0, 'error_110')
    emit_check(a, END1, 0, 0, 'error_110')
    a.li(4, START)
    a.li(5, SIZE)
    a.call(A(0x254E30))
    for offset, value in ((0, 0x53484254), (4, 0), (16, SIZE), (24, SIZE - 32)):
        emit_check(a, START, offset, value, 'error_111')
    emit_check(a, END - 4, 0, SIZE, 'error_111')
    a.li(8, END1)
    a.li(9, END)
    a.sw(9, 8)
    a.li(8, START1)
    a.li(9, START)
    a.sw(9, 8)
    a.li(4, 0x1000)
    a.addiu(5, 0, 64)
    a.move(6, 0)
    a.addiu(7, 0, 1)
    a.call(A(0x2554D8))
    a.sw(2, 16, 8)
    a.li(8, START + 64)
    a.branch(5, 2, 8, 'error_120')
    a.move(18, 2)
    for offset, value in ((0, 0x12345678), (0xFFC, 0x34567812)):
        a.li(8, value)
        a.sw(8, 18, offset)
        a.lw(9, 18, offset)
        a.branch(5, 8, 9, 'error_121')
        a.sw(0, 18, offset)
    a.move(4, 18)
    a.call(A(0x255508))
    for offset, value in ((0, 0x53484254), (4, 0), (16, SIZE), (24, SIZE - 32)):
        emit_check(a, START, offset, value, 'error_122')
    emit_check(a, END - 4, 0, SIZE, 'error_122')
    a.addiu(17, 0, 20)
    a.jump('result')
    for error in (110, 111, 120, 121, 122):
        a.label(f'error_{error}')
        a.addiu(17, 0, error)
        a.jump('result')


def code(mode):
    a = Assembler(CODE)
    a.addiu(29, 29, -0x30)
    for reg, offset in ((16, 0), (17, 8), (18, 16), (31, 24)):
        a.i(63, reg, 29, offset)
    a.call(PREVIOUS)  # Existing creation shim completes the original actor tick.
    a.i(63, 2, 29, 32)
    a.li(16, CONTROL)
    a.lw(8, 16)
    a.branch(5, 8, 0, 'done')
    a.addiu(8, 0, 1)
    a.sw(8, 16)
    if mode == 'canary':
        emit_canary(a)
    else:
        emit_heap(a)
    a.label('result')
    a.sw(17, 16)
    a.label('done')
    a.i(55, 2, 29, 32)
    for reg, offset in ((16, 0), (17, 8), (18, 16), (31, 24)):
        a.i(55, reg, 29, offset)
    a.addiu(29, 29, 0x30)
    a.jr()
    result = a.finish()
    assert len(result) < CONTROL - CODE, 'Guest test exceeds reserved cave'
    return result


def build(mode, source, output):
    ram = read_ram(source)
    assert len(ram) in (0x2000000, 0x8000000)
    u = lambda address: struct.unpack_from('<I', ram, address)[0]
    assert u(0xB3098) == 5 and u(0xB3084) == 2 and u(0xB3088) == 1
    assert not u(START1) and not u(END1), 'Heap1 already exists'
    _, _, readelf = elf_reader(elf_path(ROOT))
    for address, size in ((A(0x254E30), 0x38), (A(0x2554D8), 0x30), (A(0x255508), 0x68)):
        assert ram[address:address + size] == readelf(address, size), 'Allocator helper changed'
    if mode == 'canary':
        assert u(HOOK) == (2 << 26) | (PREVIOUS >> 2) and not u(HOOK + 4)
        assert not any(ram[CODE:CONTROL + 0x90]), 'Canary reservation occupied'
        control = bytearray(0x90)
        struct.pack_into('<4I', control, 4, 1, 0, START, END)
    else:
        assert len(ram) == 0x8000000, 'Heap initialization requires a full 128 MB dump/state'
        assert u(HOOK) == (2 << 26) | (CODE >> 2) and not u(HOOK + 4)
        assert ram[CODE:CODE + len(code('canary'))] == code('canary')
        assert u(CONTROL) == 5 and u(CONTROL + 4) == 1, 'Guest canary has not passed'
        assert not any(ram[START:END]), 'Proposed heap region is not empty'
        assert tuple(u(CONTROL + 56 + i * 4) for i in range(3)) == PATTERNS
        control = bytearray(ram[CONTROL:CONTROL + 0x90])
        struct.pack_into('<3I', control, 0, 0, 2, 0)
    payload = code(mode)
    blocks = [make_block(ram, CODE, payload, 'Guest high-memory test, chained after existing actor tick'),
              make_block(ram, CONTROL, bytes(control), 'Command and diagnostic mailbox')]
    if mode == 'canary':
        blocks.append(make_block(ram, HOOK, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0),
                                 'Install one-shot diagnostic wrapper last'))
    result = {'serial': SERIAL, 'crc': CRC, 'status': 'EXPERIMENTAL GUEST ' + mode.upper(),
              'source': str(Path(source).resolve()), 'source_sha256': hashlib.sha256(ram).hexdigest(),
              'blocks': blocks, 'code': CODE, 'mailbox': CONTROL,
              'mailbox_fields': {'0': 'status:0pending,1running,5canarypassed,20heappassed,>=100error',
                                 '4': 'command:1canary,2heap', '8': 'allocated test pointer (freed on success)',
                                 '12': 'heap start', '16': 'heap end', '32': 'three original high words',
                                 '44': 'three original mirror words', '56': 'three observed high words',
                                 '68': 'three observed mirror words'},
              'requirements': ['Only apply in a verified 128 MB VM; source32 MB may be used only for canary byte guards.',
                               'Apply paused with expected-byte checks, save/reload to invalidate EE code.',
                               'Run canary first and require status5, then build heap stage from full128 MB saved state.',
                               'Require status20 after heap stage. Restore the prior full state on any failure.',
                               'Heap1 remains registered after success; do not remove while allocations remain owned.']}
    return write_manifest(output, result, [(CODE, payload)])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('canary', 'heap'))
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    build(args.mode, args.source, args.out)
