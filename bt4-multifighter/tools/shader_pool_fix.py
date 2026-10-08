"""Repair missing nested shader allocations in a clean six-actor checkpoint.

Native1146E0 initializes each shader node with a descriptor and two buffers.
The first six_prepare revision only created the outer nodes; rendering through
their null descriptors overwrote low EE kernel memory. This offline builder
allocates those three owned blocks on heap1 before the next render pass.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import hashlib
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from team_prototype import make_block, write_manifest

CODE = 0x07202000
CONTROL = 0x07203000
FRAME_ENTRY = A(0x1C2A28)
PACKET_BYTES = 0x6E10
ENTRY_SIZE = 32
SHADER_OFFSET = 8240


def payload(previous=0xF1000):
    a = Assembler(CODE)
    a.addiu(29, 29, -0x60)
    regs = (16, 17, 18, 19, 20, 21, 22, 31)
    for i, reg in enumerate(regs): a.i(63, reg, 29, i * 8)
    a.call(previous)
    a.i(63, 2, 29, 0x40); a.i(63, 3, 29, 0x48)
    a.li(16, CONTROL)
    a.lw(8, 16, 4); a.addiu(8, 8, 1); a.sw(8, 16, 4)
    a.lw(8, 16); a.branch(5, 8, 0, 'done')
    a.lw(8, 28, -22364); a.lw(9, 16, 28); a.branch(5, 8, 9, 'error102')
    a.lw(8, 28, -22060); a.lw(9, 16, 24); a.branch(5, 8, 9, 'error102')
    # Validate both model/node ownerships before publishing either repair.
    for offset in (0x40, 0x60):
        a.lw(8, 16, offset); a.lw(9, 16, offset + 4)
        a.lw(10, 9, 5736); a.branch(5, 10, 8, 'error103')
        a.lw(10, 8, SHADER_OFFSET); a.branch(5, 10, 0, 'error103')
        a.lw(10, 9, 16); a.lw(11, 16, offset + 28)
        a.branch(5, 10, 11, 'error103')
    # Existing native nodes must retain their already-valid nested allocations.
    a.addiu(17, 16, 0x80); a.addiu(18, 0, 5)
    a.label('original_check')
    a.lw(8, 17); a.lw(9, 17, 4); a.lw(10, 8, SHADER_OFFSET)
    a.branch(5, 9, 10, 'error103')
    for offset in (0, 4):
        a.lw(8, 9, offset); a.lw(10, 17, offset + 8)
        a.branch(5, 8, 10, 'error103')
    a.addiu(17, 17, 16); a.addiu(18, 18, -1)
    a.branch(5, 18, 0, 'original_check')
    a.addiu(8, 0, 10); a.sw(8, 16)
    a.addiu(4, 0, 144); a.call(A(0x113660))
    a.r(0, 2, 0, 2, 2); a.sw(2, 16, 12)
    a.li(8, PACKET_BYTES); a.branch(5, 2, 8, 'error104')
    a.addiu(17, 16, 0x40); a.addiu(18, 0, 2)
    a.label('repair')
    a.lw(19, 17)
    # A descriptor is kept private until both packet buffers are allocated and
    # cleared. Partial allocation failures require a full checkpoint restore.
    for register, field, size, align in ((20, 8, 192, 32), (21, 12, PACKET_BYTES, 64),
                                         (22, 16, PACKET_BYTES, 64)):
        a.li(4, size); a.addiu(5, 0, align); a.move(6, 0); a.addiu(7, 0, 1)
        a.call(A(0x2554D8)); a.branch(4, 2, 0, 'error101')
        a.move(register, 2); a.sw(register, 17, field)
        a.li(8, 0x02000000); a.r(0x2B, 9, register, 8)
        a.branch(5, 9, 0, 'error105')
        a.li(8, 0x06000000 - size); a.r(0x2B, 9, 8, register)
        a.branch(5, 9, 0, 'error105')
        a.i(12, 8, register, align - 1); a.branch(5, 8, 0, 'error105')
        a.move(4, register); a.move(5, 0); a.li(6, size); a.call(A(0x2A9ACC))
    a.sw(21, 20); a.sw(22, 20, 4)
    a.li(8, PACKET_BYTES); a.sw(8, 17, 20)
    a.sw(20, 19, SHADER_OFFSET)
    a.addiu(8, 0, 5); a.sw(8, 17, 24)
    a.lw(8, 16, 8); a.addiu(8, 8, 1); a.sw(8, 16, 8)
    a.addiu(17, 17, ENTRY_SIZE); a.addiu(18, 18, -1)
    a.branch(5, 18, 0, 'repair')
    a.addiu(8, 0, 5); a.sw(8, 16); a.jump('done')
    for error in (101, 102, 103, 104, 105):
        a.label(f'error{error}'); a.addiu(8, 0, error); a.sw(8, 16); a.jump('done')
    a.label('done')
    a.i(55, 2, 29, 0x40); a.i(55, 3, 29, 0x48)
    for i, reg in enumerate(regs): a.i(55, reg, 29, i * 8)
    a.addiu(29, 29, 0x60); a.jr()
    return a.finish()


def prepare(ram, kernel_reference):
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    assert len(ram) == 0x08000000 and u(0xC9400) == 20
    assert u(A(0x2FF084)) == 0x02000000 and u(A(0x2FF08C)) == 0x06000000
    assert ram[0x180:0x700] == kernel_reference[0x180:0x700], 'Kernel already damaged; restore a clean checkpoint'
    assert not any(ram[CODE:CONTROL + 0x100]), 'Repair arena occupied'
    previous = (u(FRAME_ENTRY) & 0x3FFFFFF) << 2
    assert u(FRAME_ENTRY) >> 26 == 2 and u(FRAME_ENTRY + 4) == 0 and previous == 0xF1000
    manager, pool = u(A(0x2FEB14)), u(A(0x2FEC44))
    assert manager and pool and u(manager) == 2
    data = bytearray(0x100)
    for offset, value in ((16, previous), (24, pool), (28, manager)):
        struct.pack_into('<I', data, offset, value)
    existing, spans = [], []
    for i in range(5):
        node = pool + 397792 + i * 8256
        descriptor = u(node + SHADER_OFFSET)
        assert 0x100000 <= descriptor < len(ram) - 192 and not descriptor % 32
        buffers = [u(descriptor), u(descriptor + 4)]
        assert u(descriptor + 12) < 2
        for ptr, size in [(descriptor, 192)] + [(p, PACKET_BYTES) for p in buffers]:
            assert 0x100000 <= ptr <= len(ram) - size
            assert all(ptr + size <= start or ptr >= end for start, end in spans), 'Shader allocation alias'
            spans.append((ptr, ptr + size))
        assert all(not p % 64 for p in buffers)
        struct.pack_into('<4I', data, 0x80 + i * 16, node, descriptor, *buffers)
        existing.append({'node': node, 'descriptor': descriptor, 'buffers': buffers})
    added = []
    for i, mailbox in enumerate((0xF6000, 0xF6040)):
        actor, model, model_id, node = u(mailbox + 28), u(mailbox + 12), u(mailbox + 8), u(mailbox + 48)
        assert actor and model and node and u(actor + 12) == model_id
        assert u(A(0x31C640) + model_id * 4) == model and u(model + 16) == model_id
        assert u(model + 5736) == node and u(node + SHADER_OFFSET) == 0
        assert node not in [item['node'] for item in existing + added]
        struct.pack_into('<2I', data, 0x40 + i * ENTRY_SIZE, node, model)
        struct.pack_into('<I', data, 0x40 + i * ENTRY_SIZE + 28, model_id)
        added.append({'node': node, 'model': model, 'model_id': model_id, 'actor': actor})
    return bytes(data), existing, added, previous


def build(source, output, kernel_reference=ROOT / 'analysis/sixcreated63.bin'):
    ram, reference = read_ram(source), read_ram(kernel_reference)
    data, existing, added, previous = prepare(ram, reference)
    _, _, readelf = elf_reader(elf_path(ROOT))
    for address, size in ((A(0x113660), 0xA0), (A(0x2554D8), 0x80), (A(0x2A9ACC), 0x40)):
        assert ram[address:address + size] == readelf(address, size), f'Native function changed: {address:X}'
    code = payload(previous)
    assert CODE + len(code) < CONTROL
    blocks = [make_block(ram, CODE, code, 'Native-equivalent nested shader allocations on heap1'),
              make_block(ram, CONTROL, data, 'One-shot repair state and checked ownerships'),
              make_block(ram, FRAME_ENTRY, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0),
                         'Repair before next render pass; preserve prior frame wrapper')]
    result = {'serial': SERIAL, 'crc': CRC, 'source': str(Path(source).resolve()),
              'ram_sha256': hashlib.sha256(ram).hexdigest(), 'blocks': blocks,
              'status': 'SHADER NESTED-ALLOCATION REPAIR; ACTORS/CPU/EXPOSURE UNCHANGED',
              'control': CONTROL, 'completed': CONTROL + 8, 'success_status': 5,
              'packet_bytes_per_buffer': PACKET_BYTES, 'heap_selector': 1,
              'native_shader_audit': existing, 'repair_shader_audit': added,
              'requirements': ['Apply only to clean source checkpoint while paused; save/reload to invalidate code caches.',
                               'After running, verify status5, completed2 and intact low kernel vectors.',
                               'Restore full source checkpoint on any failure; partial allocations are intentionally retained.',
                               'Extra nodes and their owned buffers persist until checkpoint restore.'],
              'cause': 'Added shader nodes lacked native1146E0 descriptor+two-buffer initialization; null packet destinations overwrote low kernel memory.'}
    return write_manifest(output, result, [(CODE, code)])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--kernel-reference', type=Path, default=ROOT / 'analysis/sixcreated63.bin')
    a = p.parse_args(); build(a.source, a.output, a.kernel_reference)
