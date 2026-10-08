"""Offline high-code canary, rendering telemetry and later draw-pool growth.

observe changes no native allocation sizes or actor exposure. grow requires a
snapshot proving observe ran, and is a separate checkpoint-scoped experiment.
Never writes PINE, emulator configuration, or savestates.
"""
from native_map import A, CRC, GPO, SERIAL, elf_path
import argparse
import hashlib
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from team_prototype import make_block, write_manifest

FRAME = 0x07200000
PACKET = 0x07200200
PACKET_TRAMPOLINE = 0x07200400
GROW = 0x07200600
CONTROL = 0x07201000
FRAME_ENTRY = A(0x1C2A28)
PACKET_ENTRY = A(0x100798)
NODE_SIZE, ADD_NODES = 0xE0, 512
GROW_BYTES = NODE_SIZE * ADD_NODES
MAGIC = 0x48313250


def frame_code(previous):
    a = Assembler(FRAME)
    a.addiu(29, 29, -0x20)
    a.i(63, 31, 29, 0)
    a.call(previous)
    a.i(63, 2, 29, 8); a.i(63, 3, 29, 16)
    a.li(2, CONTROL)
    a.lw(3, 2, 8); a.addiu(3, 3, 1); a.sw(3, 2, 8)
    a.addiu(3, 0, 5); a.sw(3, 2, 52)
    a.i(55, 2, 29, 8); a.i(55, 3, 29, 16)
    a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20); a.jr()
    return a.finish()


def packet_code():
    a = Assembler(PACKET)
    a.addiu(29, 29, -0x60)
    registers = (2, 3, 8, 9, 10, 11, 12, 13, 14, 15)
    for index, register in enumerate(registers):
        a.i(63, register, 29, index * 8)
    a.li(8, CONTROL)
    a.lw(9, 8, 48); a.branch(4, 9, 0, 'done')
    a.lw(9, 8, 16); a.addiu(9, 9, 1); a.sw(9, 8, 16)
    a.lw(9, 28, -23004); a.sw(9, 8, 20)
    a.i(11, 10, 9, 2); a.branch(4, 10, 0, 'bad')
    a.r(0, 10, 0, 9, 2)
    a.addiu(11, 28, -23024); a.r(0x21, 11, 11, 10)
    a.lw(12, 11); a.sw(12, 8, 56)
    a.lw(13, 28, -23000); a.sw(13, 8, 60)
    a.lw(14, 28, -23008); a.sw(14, 8, 32)
    a.branch(4, 14, 0, 'bad')
    a.r(0x2B, 15, 13, 12); a.branch(5, 15, 0, 'bad')
    a.lw(15, 11, 8); a.r(0x23, 15, 15, 12)
    a.branch(5, 15, 14, 'bad')
    # 100798 emits 64 terminal bytes before submission but does not advance
    # the cursor to include them. Measure the submitted size, not just cursor.
    a.r(0x23, 13, 13, 12); a.addiu(13, 13, 64); a.sw(13, 8, 24)
    a.lw(15, 8, 28); a.r(0x2B, 15, 15, 13)
    a.branch(4, 15, 0, 'peak_done'); a.sw(13, 8, 28)
    a.label('peak_done')
    a.r(0x2B, 15, 14, 13); a.branch(5, 15, 0, 'overflow')
    a.r(0x23, 14, 14, 13); a.sw(14, 8, 36); a.jump('done')
    a.label('overflow')
    a.sw(0, 8, 36); a.lw(9, 8, 40); a.addiu(9, 9, 1); a.sw(9, 8, 40)
    a.jump('done')
    a.label('bad')
    a.lw(9, 8, 44); a.addiu(9, 9, 1); a.sw(9, 8, 44)
    a.label('done')
    for index, register in enumerate(registers):
        a.i(55, register, 29, index * 8)
    a.addiu(29, 29, 0x60); a.jump(PACKET_TRAMPOLINE)
    return a.finish()


def packet_trampoline(readelf):
    a = Assembler(PACKET_TRAMPOLINE)
    original = struct.unpack('<2I', readelf(PACKET_ENTRY, 8))
    assert original == ((35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x59D8) & 0xFFFF), 0x3C021000)
    for word in original: a.emit(word)
    a.jump(PACKET_ENTRY + 8)
    return a.finish()


def grow_code():
    a = Assembler(GROW)
    a.addiu(29, 29, -0x40)
    for index, register in enumerate((16, 17, 18, 19, 31)):
        a.i(63, register, 29, index * 8)
    a.call(FRAME)
    a.i(63, 2, 29, 0x28); a.i(63, 3, 29, 0x30)
    a.li(16, CONTROL)
    a.lw(8, 16, 64); a.addiu(9, 0, 1); a.branch(5, 8, 9, 'done')
    a.lw(8, 16, 68); a.branch(5, 8, 0, 'done')
    a.lw(8, 16, 52); a.addiu(9, 0, 5); a.branch(5, 8, 9, 'error102')
    a.lw(8, 16, 16); a.branch(4, 8, 0, 'error102')
    a.lw(8, 16, 40); a.branch(5, 8, 0, 'error102')
    a.lw(8, 16, 44); a.branch(5, 8, 0, 'error102')
    a.lw(8, 28, -22364); a.lw(9, 16, 100); a.branch(5, 8, 9, 'error103')
    a.lw(17, 28, -22060); a.lw(9, 16, 88); a.branch(5, 17, 9, 'error103')
    a.li(8, 397312); a.r(0x21, 17, 17, 8)
    a.lw(8, 17, 8); a.sw(8, 16, 80)
    a.addiu(8, 0, 10); a.sw(8, 16, 68)
    a.li(4, GROW_BYTES); a.addiu(5, 0, 64); a.move(6, 0); a.addiu(7, 0, 1)
    a.call(A(0x2554D8)); a.branch(4, 2, 0, 'error101')
    a.move(18, 2); a.sw(18, 16, 72)
    a.li(8, 0x02000000); a.r(0x2B, 9, 18, 8); a.branch(5, 9, 0, 'error104')
    a.li(8, 0x06000000 - GROW_BYTES); a.r(0x2B, 9, 8, 18)
    a.branch(5, 9, 0, 'error104')
    a.move(4, 18); a.move(5, 0); a.li(6, GROW_BYTES); a.call(A(0x2A9ACC))
    a.addiu(19, 0, ADD_NODES)
    a.label('insert')
    a.move(4, 17); a.move(5, 18); a.call(A(0x255CF0))
    a.addiu(18, 18, NODE_SIZE); a.addiu(19, 19, -1)
    a.branch(5, 19, 0, 'insert')
    a.lw(8, 17, 8); a.sw(8, 16, 84)
    a.addiu(9, 0, ADD_NODES); a.sw(9, 16, 76)
    a.lw(9, 16, 80); a.addiu(9, 9, ADD_NODES)
    a.branch(5, 8, 9, 'error105')
    a.addiu(8, 0, 20); a.sw(8, 16, 68); a.sw(0, 16, 64); a.jump('done')
    for error in (101, 102, 103, 104, 105):
        a.label(f'error{error}'); a.addiu(8, 0, error); a.sw(8, 16, 68); a.jump('done')
    a.label('done')
    a.i(55, 2, 29, 0x28); a.i(55, 3, 29, 0x30)
    for index, register in enumerate((16, 17, 18, 19, 31)):
        a.i(55, register, 29, index * 8)
    a.addiu(29, 29, 0x40); a.jr()
    return a.finish()


def build(mode, source, output):
    ram = read_ram(source)
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    assert len(ram) == 0x08000000 and u(0xC9400) == 20
    assert u(A(0x2FF084)) == 0x02000000 and u(A(0x2FF08C)) == 0x06000000
    manager, pool = u(A(0x2FEB14)), u(A(0x2FEC44))
    assert manager and pool and u(manager) == 2
    _, _, readelf = elf_reader(elf_path(ROOT))
    regions, blocks = [], []
    def block(address, data, purpose):
        blocks.append(make_block(ram, address, data, purpose))
    if mode == 'observe':
        assert not any(ram[FRAME:CONTROL + 0x100]), 'High observation arena occupied'
        assert u(FRAME_ENTRY) >> 26 == 2 and not u(FRAME_ENTRY + 4)
        previous = (u(FRAME_ENTRY) & 0x3FFFFFF) << 2
        assert previous in (0xF1000, 0x07202000), 'Review chain before observing a different frame wrapper'
        if previous == 0x07202000:
            from shader_pool_fix import payload as shader_fix_payload, CONTROL as SHADER_CONTROL
            shader_fix = shader_fix_payload()
            assert ram[previous:previous + len(shader_fix)] == shader_fix
            assert u(SHADER_CONTROL) == 5 and u(SHADER_CONTROL + 8) == 2
        assert ram[PACKET_ENTRY:PACKET_ENTRY + 0xB8] == readelf(PACKET_ENTRY, 0xB8)
        data = bytearray(0x100)
        for offset, value in ((0, MAGIC), (4, 1), (48, 1), (88, pool),
                              (96, previous), (100, manager), (104, u(manager))):
            struct.pack_into('<I', data, offset, value)
        for address, code, purpose in ((FRAME, frame_code(previous), 'High-memory execution canary; chain prior frame'),
                                       (PACKET, packet_code(), 'Peak submitted packet bytes including terminal tags'),
                                       (PACKET_TRAMPOLINE, packet_trampoline(readelf), 'Preserve native submission prologue')):
            block(address, code, purpose); regions.append((address, code))
        block(CONTROL, bytes(data), 'Observation mailbox; growth command disabled')
        block(FRAME_ENTRY, struct.pack('<2I', (2 << 26) | (FRAME >> 2), 0), 'Execute high-memory canary during frame')
        block(PACKET_ENTRY, struct.pack('<2I', (2 << 26) | (PACKET >> 2), 0), 'Observe native packet submission')
    else:
        assert u(CONTROL) == MAGIC and u(CONTROL + 52) == 5
        assert u(CONTROL + 8) > 0 and u(CONTROL + 16) > 0, 'High code and telemetry not yet proved'
        assert not u(CONTROL + 40) and not u(CONTROL + 44), 'Resolve packet telemetry failure first'
        assert not u(CONTROL + 64) and not u(CONTROL + 68) and not u(CONTROL + 72)
        assert u(CONTROL + 88) == pool and u(CONTROL + 100) == manager
        previous = u(CONTROL + 96)
        for address, code in ((FRAME, frame_code(previous)), (PACKET, packet_code()),
                               (PACKET_TRAMPOLINE, packet_trampoline(readelf))):
            assert ram[address:address + len(code)] == code
        assert u(FRAME_ENTRY) == (2 << 26) | (FRAME >> 2) and not u(FRAME_ENTRY + 4)
        assert u(PACKET_ENTRY) == (2 << 26) | (PACKET >> 2) and not u(PACKET_ENTRY + 4)
        for address, size in ((A(0x255CF0), 0x30), (A(0x2554D8), 0x30)):
            assert ram[address:address + size] == readelf(address, size)
        code = grow_code()
        assert not any(ram[GROW:GROW + len(code)])
        block(GROW, code, 'One-shot persistent 512-node draw pool extension'); regions.append((GROW, code))
        block(CONTROL + 64, struct.pack('<I', 1), 'Request growth exactly once')
        block(FRAME_ENTRY, struct.pack('<2I', (2 << 26) | (GROW >> 2), 0), 'Chain growth after proved high-memory observer')
    assert FRAME + len(frame_code(0xF1000)) <= PACKET
    assert PACKET + len(packet_code()) <= PACKET_TRAMPOLINE
    assert GROW + len(grow_code()) <= CONTROL
    result = {'serial': SERIAL, 'crc': CRC, 'mode': mode,
              'source': str(Path(source).resolve()), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
              'status': 'CAPACITY ' + mode.upper() + '; ACTOR COUNT/EXPOSURE UNCHANGED',
              'blocks': blocks, 'control': CONTROL, 'previous_frame': previous,
              'fields': {'frame_ticks': CONTROL + 8, 'packet_ticks': CONTROL + 16,
                         'last_submitted_bytes': CONTROL + 24, 'peak_submitted_bytes': CONTROL + 28,
                         'packet_capacity': CONTROL + 32, 'remaining_bytes': CONTROL + 36,
                         'packet_overflow_count': CONTROL + 40, 'bad_packet_state_count': CONTROL + 44,
                         'canary_success_5': CONTROL + 52, 'growth_status_20': CONTROL + 68,
                         'growth_allocation': CONTROL + 72, 'added_nodes': CONTROL + 76,
                         'free_nodes_before': CONTROL + 80, 'free_nodes_after': CONTROL + 84},
              'requirements': ['Apply paused, save and reload an isolated checkpoint to invalidate code caches.',
                               'Observe must prove both frame and packet counters before grow.',
                               'Root must validate stable six-fighter combat before choosing grow.',
                               'Restore the full source checkpoint on failure; grown nodes remain persistently allocated.'],
              'limitations': ['Observe records packet pressure but does not prevent native overflow.',
                              'This measures the main100798 packet arena; other graphics arenas are not measured.',
                              'No twelve-actor creation, scheduling or team selection is installed.']}
    return write_manifest(output, result, regions)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('observe', 'grow'))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); build(args.mode, args.source, args.out)
