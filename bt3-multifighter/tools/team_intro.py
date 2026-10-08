"""Play the native leader dialogue after a prepared team's loading cover.

The separate start request holds every CPU and player input until phase3.
This does not recreate actors, resources, or the battle manager.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
from input_script import chain_head
import fresh_team_combat as core
import team_start_gate as start
import guest_healthbars as bars
from battle_mode_policy import ACTOR_COUNTS

CODE, TRAMPOLINE, CONTROL = 0x07430000, 0x07431C00, 0x07431D00
HOOK, REQUEST = start.HOOK, CONTROL+4
BATTLE = A(0x2FEB38)
SAVED = ((16, 0), (17, 8), (18, 16), (31, 24))


def payload(previous):
    a = Assembler(CODE); a.addiu(29, 29, -0x30)
    for r, off in SAVED: a.i(63, r, 29, off)
    core.gate(a, 'tail')
    a.li(16, CONTROL); a.lw(8, 16); a.branch(4, 8, 0, 'tail')
    a.lw(8, 16, 8); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'tail')
    a.lw(8, 16, 12); a.branch(5, 8, 10, 'tail')
    a.li(18, start.CONTROL); a.lw(8, 18); a.addiu(9, 0, 1)
    a.branch(5, 8, 9, 'tail')
    a.lw(8, 18, 8); a.lw(9, 16, 8); a.branch(5, 8, 9, 'tail')
    a.lw(17, 16, 16); a.li(8, BATTLE); a.lw(8, 8)
    a.branch(5, 8, 17, 'tail')
    a.lw(8, 16, 4); a.branch(4, 8, 0, 'tail')
    a.lw(8, 16, 20); a.branch(5, 8, 0, 'playing')
    a.lw(8, 17); a.addiu(9, 8, -2); a.i(11, 9, 9, 2)
    a.branch(4, 9, 0, 'tail')
    a.addiu(8, 0, 1); a.sw(8, 16, 20); a.sw(8, 17)
    a.li(8, bars.CONTROL); a.lw(9, 8); a.sw(9, 16, 24); a.sw(0, 8)
    # Native transition dispatcher initializes obj+4's callback and calls the
    # ordinary phase1 entry. No full battle/actor reset occurs here.
    a.li(4, A(0x217398)); a.addiu(5, 0, 1); a.call(A(0x216AF8))
    a.jump('tail')
    a.label('playing'); a.lw(8, 17); a.addiu(9, 0, 3)
    a.branch(5, 8, 9, 'tail')
    a.li(8, bars.CONTROL); a.lw(9, 16, 24); a.sw(9, 8)
    a.addiu(8, 0, 1); a.sw(8, 18, 4)
    a.addiu(8, 0, 2); a.sw(8, 16, 20); a.sw(0, 16)
    a.label('tail')
    for r, off in SAVED: a.i(55, r, 29, off)
    a.addiu(29, 29, 0x30); a.jump(previous)
    result = a.finish(); assert len(result) < TRAMPOLINE-CODE; return result


def build_memory(ram, source='<offline>', *, preset=False):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if any(ram[CODE:CONTROL+0x100]): raise ValueError('Intro reservation occupied')
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if count not in ACTOR_COUNTS or u(core.MODE) != 1 or u(core.MODE+8) != manager:
        raise ValueError('Requires a prepared team')
    if u(start.CONTROL) != 1 or u(start.REQUEST) != 0 or u(start.CONTROL+8) != manager:
        raise ValueError('Requires an unreleased start gate')
    phase = u(BATTLE)
    if not 0x100000 <= phase <= len(ram)-300 or u(phase) not in (2, 3) or u(phase+260) != A(0x2C6070):
        raise ValueError('Requires the native Duel battle phase table')
    _, _, native = elf_reader(elf_path(ROOT))
    for address, size in ((A(0x216AF8), 0x50), (A(0x217398), 0x78), (A(0x2C6088), 24)):
        if ram[address:address+size] != native(address, size):
            raise ValueError(f'Changed native intro routine{address:08X}')
    if preset:
        from extra_intros import preset_chain_head
        previous,extra=preset_chain_head(ram),[]
    else:
        previous, extra = chain_head(ram, HOOK, TRAMPOLINE, native)
    control = bytearray(0x100); struct.pack_into('<5I', control, 0, 1, 0, manager, count, phase)
    pieces = [(p,d) for p,d,*_ in extra] + [(CODE,payload(previous)),(CONTROL,bytes(control)),
        (HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces],
        control=CONTROL,request=REQUEST,previous=previous)
