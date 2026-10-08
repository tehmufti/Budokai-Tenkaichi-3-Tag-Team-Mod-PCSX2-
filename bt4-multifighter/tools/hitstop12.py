"""Offline native hitstop relocation with twelve initialized temporary words.

Preserves native flag priority, delayed timers, and tie behavior. No live writes.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader

ENTRY, END = A(0x1C0CB8), A(0x1C0EB8)
CODE, COUNT = 0xF8000, 0xF8400
RESERVATION_END = 0xFC000
NATIVE_COUNT = A(0x1DC168)
MAX_ACTORS = 12


def count_code():
    a = Assembler(COUNT)
    a.addiu(29, 29, -16)
    a.i(63, 31, 29, 0)
    a.call(NATIVE_COUNT)
    # A malformed negative count retains the native empty-loop behavior.
    a.i(10, 3, 2, 0)
    a.branch(5, 3, 0, 'negative')
    a.i(11, 3, 2, MAX_ACTORS + 1)
    a.branch(5, 3, 0, 'done')
    a.addiu(2, 0, MAX_ACTORS)
    a.jump('done')
    a.label('negative')
    a.move(2, 0)
    a.label('done')
    a.i(55, 31, 29, 0)
    a.addiu(29, 29, 16)
    a.jr()
    return a.finish()


def relocated_code():
    _, _, readelf = elf_reader(elf_path(ROOT))
    native = readelf(ENTRY, END - ENTRY)
    words = list(struct.unpack('<' + 'I' * (len(native) // 4), native))
    edits = {}
    def replace(address, expected, replacement, reason):
        index = (address - ENTRY) // 4
        assert words[index] == expected, f'Unexpected native instruction at{address:X}'
        words[index] = replacement
        edits[address] = reason
    replace(ENTRY, 0x27BDFFB0, 0x27BDFF90, 'Increase frame from0x50 to0x70 bytes')
    replace(A(0x1C0CC4), 0x24060008, 0x24060030, 'Clear twelve local words (48bytes)')
    replace(A(0x1C0EB0), 0x27BD0050, 0x27BD0070, 'Restore enlarged stack frame')
    for index, word in enumerate(tuple(words)):
        address = ENTRY + index * 4
        op, base, offset = word >> 26, (word >> 21) & 31, word & 65535
        if op in (55, 63) and base == 29:
            assert offset in (0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40)
            replace(address, word, (word & 0xFFFF0000) | (offset + 32),
                    'Move saved-register slot beyond enlarged local array')
        if op == 3 and ((word & 0x3FFFFFF) << 2) == NATIVE_COUNT:
            replace(address, word, (3 << 26) | (COUNT >> 2), 'Cap native actor count to0..12')
        if op in (2, 3):
            destination = (word & 0x3FFFFFF) << 2
            assert not ENTRY <= destination < END, 'Absolute internal jump needs relocation'
        if op in (4, 5, 6, 7, 20, 21):
            signed = offset if offset < 32768 else offset - 65536
            destination = address + 4 + signed * 4
            assert ENTRY <= destination < END, 'Relative external branch needs relocation'
    assert len(edits) == 21  # 3 frame/clear,14 saves/restores,4 count calls.
    return struct.pack('<' + 'I' * len(words), *words), edits


def build(source, output):
    ram = Path(source).read_bytes()
    assert len(ram) in (0x2000000, 0x8000000)
    _, segments, readelf = elf_reader(elf_path(ROOT))
    expected_native = bytearray(readelf(ENTRY, END - ENTRY))
    old_clear = struct.unpack_from('<I', ram, A(0x1C0CC4))[0]
    assert old_clear in (0x24060008, 0x24060010), 'Unexpected hitstop initializer'
    struct.pack_into('<I', expected_native, A(0x1C0CC4) - ENTRY, old_clear)
    assert ram[ENTRY:END] == expected_native, 'Native hitstop routine already changed'
    assert not any(ram[CODE:RESERVATION_END]), 'F8000..FBFFF reservation occupied'
    assert not any(va < RESERVATION_END and CODE < va + size for va, _, _, size in segments)
    code, edits = relocated_code()
    assert CODE + len(code) <= COUNT
    assert COUNT + len(count_code()) < RESERVATION_END
    blocks = []
    for address, data, purpose in (
        (CODE, code, 'Relocated native hitstop routine with48-byte temporary array'),
        (COUNT, count_code(), 'Bound native count to0..12 inside hitstop only'),
        (ENTRY, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0), 'Redirect hitstop entry to enlarged native frame'),
    ):
        blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                       'data_hex': data.hex(), 'purpose': purpose})
    result = {'serial': SERIAL, 'crc': CRC,
              'status': 'TWELVE-ACTOR HITSTOP FRAME; LIVE EXECUTION UNTESTED',
              'source_ram': str(Path(source).resolve()), 'max_actors': MAX_ACTORS,
              'native_frame': 0x50, 'new_frame': 0x70, 'local_array_bytes': 48,
              'native_edits': {f'{address:08X}': reason for address, reason in edits.items()},
              'requirements': ['Apply paused with exact expected bytes and save/reload to invalidate EE caches.',
                               'Native actor getters must resolve every exposed physical actor up to the advertised count.',
                               'All native hitstop behavior is retained, including global freezing and the first highest-priority exemption.',
                               'Only hitstop local capacity is increased; collision, actors, AI, effects and resource pools have separate limits.'],
              'blocks': blocks}
    output = Path(output)
    output.write_text(json.dumps(result, indent=2) + '\n')
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
    lines = []
    for address, data in ((CODE, code), (COUNT, count_code())):
        decoded = list(md.disasm(data, address))
        assert len(decoded) * 4 == len(data)
        lines.extend(f'{i.address:08X}: {i.mnemonic} {i.op_str}' for i in decoded)
    output.with_suffix('.asm.txt').write_text('\n'.join(lines) + '\n')
    print(f'{output}: native{len(code)}bytes, count{len(count_code())}bytes; three guarded blocks')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=ROOT / 'analysis/distinct53.bin')
    ap.add_argument('--out', type=Path, default=ROOT / 'analysis/hitstop12.json')
    args = ap.parse_args()
    build(args.source, args.out)
