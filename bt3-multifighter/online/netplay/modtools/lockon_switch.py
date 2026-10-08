"""Manual lock-on switching for human leaders in captured team matches.

This legacy layer moves the human's
entry in the target table 0xD8000 to the next living opposing fighter in
physical order. Facing, camera look-at and melee geometry all follow that
table through the routed selectors, so the switch is immediate. The switch is
deferred while the fighter is inside a paired special or throw (its partner is
resolved through the same table) and while its delayed damage is still being
transferred (mirroring the private AI picker).

The wrapper is prepended to the actor-update chain at 0x1C2A28 and runs after
pad polling and after the AI frame. Offline builder only.

R3 is also the native transformation control. Current releases always install
lockon_queue over this legacy body: short taps retain native forms, and a plain
R3 hold of15 updates followed by release requests a target switch.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
from input_script import chain_head, RECORDS
from battle_mode_policy import ACTOR_COUNTS

HOOK = A(0x1C2A28)
CODE, TRAMPOLINE, CONTROL = 0x073D6000, 0x073D6600, 0x073D6800
DEFAULT_BUTTON = 0x4  # R3
FIELDS = dict(enabled=0, manager=4, button=8, frames=12, switches=16, previous=0x20, per_actor=0x60)
POINTERS, TABLE = core.POINTERS, core.TABLE
PAIRED_STATES = ((301, 3), (313, 3), (183, 5))
PENDING = (3480, 3500, 3512)
SAVED = ((16, 0), (17, 8), (18, 16), (19, 24), (20, 32))


def code(previous):
    a = Assembler(CODE)
    a.addiu(29, 29, -0x40)
    for reg, off in SAVED: a.i(63, reg, 29, off)
    core.gate(a, 'done')
    a.li(16, CONTROL); a.lw(8, 16); a.branch(4, 8, 0, 'done')
    a.lw(8, 16, FIELDS['frames']); a.addiu(8, 8, 1); a.sw(8, 16, FIELDS['frames'])
    a.move(17, 10); a.move(18, 0)
    a.label('actor'); a.r(0x2B, 8, 18, 17); a.branch(4, 8, 0, 'done')
    a.li(8, POINTERS); a.r(0, 9, 0, 18, 2); a.r(0x2D, 8, 8, 9); a.lw(19, 8)
    a.branch(4, 19, 0, 'next')
    a.lw(8, 19, 0x1278); a.branch(5, 8, 0, 'next')            # humans only
    a.lw(8, 19, 4); a.i(11, 9, 8, 2); a.branch(4, 9, 0, 'next')
    a.r(0, 9, 0, 8, 6); a.r(0, 10, 0, 8, 7); a.r(0x2D, 9, 9, 10)
    a.r(0, 10, 0, 8, 8); a.r(0x2D, 9, 9, 10); a.li(10, RECORDS); a.r(0x2D, 9, 9, 10)
    a.lw(12, 9, 328)                                             # raw buttons this frame
    a.r(0, 11, 0, 18, 2); a.r(0x2D, 11, 16, 11)
    a.lw(13, 11, FIELDS['previous']); a.sw(12, 11, FIELDS['previous'])
    a.lw(14, 16, FIELDS['button']); a.r(0x24, 12, 12, 14); a.r(0x24, 13, 13, 14)
    a.branch(4, 12, 0, 'next'); a.branch(5, 13, 0, 'next')      # press edge only
    a.lw(8, 19, 0x948)
    for start, span in PAIRED_STATES:
        a.addiu(9, 8, -start); a.i(11, 9, 9, span); a.branch(5, 9, 0, 'next')
    for offset in PENDING:
        a.lw(8, 19, offset); a.branch(5, 8, 0, 'next')
    a.li(8, TABLE); a.r(0, 9, 0, 18, 2); a.r(0x2D, 15, 8, 9); a.lw(20, 15)  # t7 = table slot, s4 = current
    a.move(14, 20); a.move(11, 0)
    a.label('search')
    a.addiu(11, 11, 1); a.r(0x2B, 8, 11, 17); a.branch(4, 8, 0, 'next')   # every slot tried
    a.addiu(14, 14, 1); a.r(0x2B, 8, 14, 17); a.branch(5, 8, 0, 'wrapped'); a.move(14, 0)
    a.label('wrapped')
    a.branch(4, 14, 20, 'next')                                 # back at the current target
    a.i(12, 8, 14, 1); a.i(12, 9, 18, 1); a.branch(4, 8, 9, 'search')
    a.li(8, POINTERS); a.r(0, 9, 0, 14, 2); a.r(0x2D, 8, 8, 9); a.lw(9, 8)
    a.branch(4, 9, 0, 'search')
    a.lw(8, 9, 0x994); a.i(11, 10, 8, 5); a.branch(4, 10, 0, 'search')
    a.r(0, 10, 0, 8, 7); a.r(0, 12, 0, 8, 5); a.r(0x2D, 10, 10, 12)
    a.r(0, 12, 0, 8, 2); a.r(0x2D, 10, 10, 12); a.r(0x2D, 10, 10, 9)
    a.lw(10, 10, 0x9E4); a.branch(6, 10, 0, 'search')           # dead: keep looking
    a.sw(14, 15)
    a.lw(8, 16, FIELDS['switches']); a.addiu(8, 8, 1); a.sw(8, 16, FIELDS['switches'])
    a.r(0, 9, 0, 18, 2); a.r(0x2D, 9, 16, 9)
    a.lw(8, 9, FIELDS['per_actor']); a.addiu(8, 8, 1); a.sw(8, 9, FIELDS['per_actor'])
    a.label('next'); a.addiu(18, 18, 1); a.jump('actor')
    a.label('done')
    for reg, off in SAVED: a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x40); a.jump(previous)
    result = a.finish(); assert len(result) <= TRAMPOLINE-CODE; return result


def build_memory(ram, config=None, source='<offline-memory>', button=DEFAULT_BUTTON):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(A(0x2FEB14))
    if not 0x100000 <= manager <= len(ram)-16 or u(manager) != 2: raise ValueError('Requires the native two-row actor manager')
    if config is None:
        if u(core.MODE) != 1 or u(core.MODE+8) != manager or u(core.MODE+4) not in ACTOR_COUNTS:
            raise ValueError('Requires an active captured team or an explicit hidden configuration')
    else:
        import fresh_team_ai
        config = fresh_team_ai.normalize(config)
        fresh_team_ai.validate_world(ram, u, config)
    if not 0 < button <= 0xFFFF: raise ValueError('Button mask must be a raw pad bit')
    _, _, native = elf_reader(elf_path(ROOT))
    previous, extra = chain_head(ram, HOOK, TRAMPOLINE, native)
    if any(ram[CODE:CONTROL+0x100]): raise ValueError('Lock-on reservation occupied')
    control = bytearray(0x100); struct.pack_into('<3I', control, 0, 1, manager, button)
    pieces = extra+[(CODE, code(previous), 'Human lock-on switching on a press edge'),
                    (CONTROL, bytes(control), 'Enabled, manager, button, counters, previous pad words'),
                    (HOOK, struct.pack('<2I', (2<<26)|(CODE>>2), 0), 'Prepend to the actor-update chain')]
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex(), purpose=w) for p, d, w in pieces]
    support = [dict(address=b['address'], data_hex=b['data_hex']) for b in blocks if b['address'] != CONTROL]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks, control=CONTROL,
        previous=previous, button=button, status='HUMAN LOCK-ON SWITCH (R3)',
        telemetry=dict(frames=CONTROL+12, switches=CONTROL+16, per_actor=CONTROL+0x60),
        support={'capacity': 12, 'features': {'lockon_switch': support}},
        limitations=['Switching is deferred inside paired specials/throws and while delayed damage is pending.',
                     'Only living opposing fighters are cycled; with one living enemy the press does nothing.'])


def build(source, config=None, button=DEFAULT_BUTTON):
    return build_memory(read_ram(source), config, source, button)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--config', type=Path); p.add_argument('--button', type=lambda v: int(v, 0), default=DEFAULT_BUTTON)
    p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source, json.loads(x.config.read_text()) if x.config else None, x.button)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
