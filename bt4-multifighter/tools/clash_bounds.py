"""Prevent extra fighters entering native clashes that only leaders can resolve.

Offline manifest builder. The hook skips a single eligible pair inside1C9010,
then continues its actor loop; it does not suppress the battle/contact pass.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from camera_snapshot import read_ram
from prototype import Assembler, ROOT, elf_reader

HOOK, CODE, CONTROL = A(0x1C9128), 0x07240000, 0x07242000
MANAGER_GLOBAL = A(0x2FEB14)


def code():
    a = Assembler(CODE)
    a.addiu(29, 29, -0x20)
    for register, offset in ((8, 0), (9, 8), (10, 16)):
        a.i(63, register, 29, offset)
    a.li(8, CONTROL); a.lw(9, 8)
    a.branch(4, 9, 0, 'native')
    a.lw(9, 8, 4); a.lw(10, 28, -22364)
    a.branch(5, 9, 10, 'native')
    a.lw(9, 8, 8); a.lw(10, 10, 4)
    a.branch(5, 9, 10, 'native')
    # Identity is pointer-based because AI temporarily aliases actor+0.
    a.branch(4, 16, 9, 'source_zero')
    a.lw(10, 8, 12)
    a.branch(5, 16, 10, 'skip')
    a.branch(5, 17, 9, 'skip')
    a.jump('allowed')
    a.label('source_zero')
    a.lw(10, 8, 12)
    a.branch(5, 17, 10, 'skip')
    a.label('allowed')
    a.lw(9, 8, 20); a.addiu(9, 9, 1); a.sw(9, 8, 20)
    a.label('native')
    for register, offset in ((8, 0), (9, 8), (10, 16)):
        a.i(55, register, 29, offset)
    a.addiu(29, 29, 0x20)
    # BT4 adds its own eligibility path in DBZP.BIN. Keep it for leaders.
    a.jump(0x3BE7E8)
    a.label('skip')
    a.lw(9, 8, 16); a.addiu(9, 9, 1); a.sw(9, 8, 16)
    a.sw(16, 8, 24); a.sw(17, 8, 28)
    for register, offset in ((8, 0), (9, 8), (10, 16)):
        a.i(55, register, 29, offset)
    a.addiu(29, 29, 0x20)
    a.jump(A(0x1C9218))  # Native increment/continue, before any clash flags.
    result = a.finish()
    assert len(result) <= 0x1000
    return result


def build(source):
    ram = read_ram(source)
    assert len(ram) == 0x8000000, 'Requires128MB prototype RAM/state'
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    _, _, native = elf_reader(elf_path(ROOT))
    assert ram[HOOK:HOOK+8] == native(HOOK, 8), 'Clash entry already changed'
    assert struct.unpack('<2I', native(HOOK, 8)) == ((2<<26)|(0x3BE7E8>>2), 0)
    manager = u(MANAGER_GLOBAL)
    assert 0x100000 <= manager < len(ram)-640 and u(manager) == 2
    leader = u(manager+4)
    assert 0x100000 <= leader < len(ram)-0x2C00 and leader % 16 == 0
    assert u(leader) == 0 and u(leader+0x1600) == 1
    count = u(0xD8084)
    assert u(0xD8088) == manager and count in (6, 12)
    assert u(0xD8040) == leader and u(0xD8044) == leader+0x1600
    data = struct.pack('<9I', 1, manager, leader, leader+0x1600,
                       0, 0, 0, 0, count)
    payloads = [(CODE, code()), (CONTROL, data)]
    for address, blob in payloads:
        assert not any(ram[address:address+len(blob)]), f'Occupied cave{address:08X}'
    payloads.append((HOOK, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0)))
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status='PREVENT EXTRA-ACTOR CLASH250/251 ENTRY; OFFLINE TESTED',
                control=CONTROL, captured_count=count,
                blocks=[dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex())
                        for p, b in payloads],
                counters={'skipped_pairs': CONTROL+16, 'native_pairs': CONTROL+20,
                          'last_source': CONTROL+24, 'last_target': CONTROL+28},
                behavior=['Guard runs only in the captured manager and original actor array.',
                          'Allow original leader0/leader1 pointer pair in either direction.',
                          'Any other eligible pair continues the native actor loop without writing clash flags0x61/0x62.',
                          'Normal contact processing and all other battle update functions are unchanged.',
                          'Prevention only: restore a pre-clash checkpoint before applying.'],
                evidence=['1C9010 writes flags0x61/0x62 and shared clash flags only after1C9128.',
                          '1E12D0 maps those flags to actions250/251.',
                          '1D87D8 and1D8880 require both original leaders in250/251;1D9330 resolves only getters0/1.',
                          'Snapshot98 extras4/5 had366 state ticks and looping animation372 despite live frames.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    x = p.parse_args()
    x.out.write_text(json.dumps(build(x.source), indent=2)+'\n')
    print(x.out)
