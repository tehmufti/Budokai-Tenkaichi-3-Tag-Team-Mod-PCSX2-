"""Hold a fully prepared team until its loading presentation has disappeared.

All code is installed as part of the final guarded state. Starting requires
only a data-word write, so it does not trigger another save/load or JIT change.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
from input_script import chain_head, RECORDS
import fresh_team_combat as core
import fresh_memory
from battle_mode_policy import ACTOR_COUNTS

CODE, TRAMPOLINE, CONTROL = 0x073E1000, 0x073E1B00, 0x073E1C00
HOOK, REQUEST = A(0x1C2A28), CONTROL+4
SAVED = ((16, 0), (17, 8), (18, 16), (19, 24), (20, 32))


def code(previous):
    a = Assembler(CODE); a.addiu(29, 29, -0x40)
    for reg, off in SAVED: a.i(63, reg, 29, off)
    core.gate(a, 'done')
    a.li(16, CONTROL); a.lw(8, 16); a.branch(4, 8, 0, 'done')
    a.lw(8, 16, 8); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'done')
    a.lw(17, 16, 12); a.branch(5, 17, 10, 'done')
    # Validate the entire captured pointer table before changing any actor.
    a.move(18, 0)
    a.label('validate'); a.r(0x2B, 8, 18, 17); a.branch(4, 8, 0, 'validated')
    a.r(0, 9, 0, 18, 2); a.r(0x2D, 20, 16, 9); a.lw(19, 20, 0x80)
    a.li(8, core.POINTERS); a.r(0x2D, 8, 8, 9); a.lw(8, 8)
    a.branch(5, 8, 19, 'done'); a.lw(8, 19); a.branch(5, 8, 18, 'done')
    a.addiu(18, 18, 1); a.jump('validate')
    a.label('validated'); a.move(18, 0); a.lw(17, 16, 12)
    a.label('actor'); a.r(0x2B, 8, 18, 17); a.branch(4, 8, 0, 'after_actors')
    a.r(0, 9, 0, 18, 2); a.r(0x2D, 20, 16, 9); a.lw(19, 20, 0x80)
    a.lw(8, 16, 4); a.branch(4, 8, 0, 'held_cpu')
    a.lw(8, 20, 0x40); a.jump('cpu')
    a.label('held_cpu'); a.move(8, 0)
    a.label('cpu'); a.sw(8, 19, 0x1278)
    for off in (0x127C, 0x1280, 0x1284): a.sw(0, 19, off)
    a.addiu(18, 18, 1); a.jump('actor')
    a.label('after_actors')
    # Clear the two polled human records as well as actor/AI input.
    for player in (0, 1):
        a.li(8, RECORDS+448*player)
        for off in (304, 308, 328): a.sw(0, 8, off)
    a.lw(8, 16, 4); a.branch(4, 8, 0, 'held')
    a.li(8, fresh_memory.CONTROL+80); a.sw(0, 8)
    a.sw(0, 16); a.addiu(8, 0, 1); a.sw(8, 16, 20); a.jump('done')
    a.label('held'); a.lw(8, 16, 16); a.addiu(8, 8, 1); a.sw(8, 16, 16)
    a.label('done')
    for reg, off in SAVED: a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x40); a.jump(previous)
    result = a.finish(); assert len(result) < TRAMPOLINE-CODE; return result


def build_memory(ram, source='<offline>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, n = u(core.ACTORS), u(core.MODE+4)
    if not 0x100000 <= manager < len(ram)-16 or u(manager) != 2:
        raise ValueError('Invalid native actor manager')
    if u(core.MODE) != 1 or u(core.MODE+8) != manager or u(core.MODE+12) != n or n not in ACTOR_COUNTS:
        raise ValueError('Requires virtually activated selected team')
    if any(ram[CODE:CONTROL+0x100]): raise ValueError('Start-gate reservation occupied')
    _, _, native = elf_reader(elf_path(ROOT))
    previous, extra = chain_head(ram, HOOK, TRAMPOLINE, native)
    control = bytearray(0x100); struct.pack_into('<4I', control, 0, 1, 0, manager, n)
    pieces = [(p, d) for p, d, *_ in extra]
    for i in range(n):
        actor = u(core.POINTERS+4*i)
        if not 0x100000 <= actor < len(ram)-0x1600 or u(actor) != i: raise ValueError('Actor identity mismatch')
        cpu = u(actor+0x1278)
        if cpu not in (0, 1): raise ValueError('Invalid CPU assignment')
        struct.pack_into('<I', control, 0x40+4*i, cpu)
        struct.pack_into('<I', control, 0x80+4*i, actor)
        for off in (0x1278, 0x127C, 0x1280, 0x1284): pieces.append((actor+off, bytes(4)))
    pieces += [(CODE, code(previous)), (CONTROL, bytes(control)),
               (fresh_memory.CONTROL+80, struct.pack('<I', 1)),
               (HOOK, struct.pack('<2I', (2<<26)|(CODE>>2), 0))]
    return dict(serial=SERIAL, crc=CRC, source=str(source),
                blocks=[dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex()) for p,d in pieces],
                control=CONTROL, request=REQUEST, previous=previous)
