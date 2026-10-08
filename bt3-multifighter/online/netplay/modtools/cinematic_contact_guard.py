"""Bounded contact isolation and unsupported throw suppression for team matches.

This prevents new outside contacts; it does not cancel damage already queued
by an earlier interrupted cinematic or repair throw animation resource binding.
"""
from native_map import A, CRC, FLAG, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram

GATE, PROTECTED, THROW, CONTROL = 0x073C4000, 0x073C4200, 0x073C4A00, 0x073C7F00
MODE, POINTERS, TARGETS = 0xD8080, 0xD8040, 0xD8000
SPECS = ((A(0x1C84A8), 0x073C5000, 'direct', 1),
         (A(0x1C9B50), 0x073C5400, 'queued', 0),
         (A(0x1CA6D0), 0x073C5800, 'direct', 0),
         (A(0x1CB288), 0x073C5C00, 'projectile', 0),
         (A(0x1CC2A0), 0x073C6000, 'reverse', 0),
         (A(0x1D4F30), 0x073C6400, 'throw', 0))
SAVED = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 31)
PAIRED_FIELDS = (2376, 2380, 2388, 2392, 2396, 2400)
PENDING_CAPTURE = False  # Original bootstrap bytes remain stable for old presets.


def paired_pending(a, actor, yes):
    """Current/requested actions or the native pre-action rush flag94.

    Contact1CA6D0 records both identities and flag94 before the action dispatcher
    commits301..303/313..315. Protect that same-update interval too. Previous
    action2384 is excluded because it remains populated after returning idle.
    Clobbers only t0/t1.
    """
    for off in PAIRED_FIELDS:
        a.lw(8,actor,off)
        for first in (301,313):
            a.addiu(9,8,-first);a.i(11,9,9,3);a.branch(5,9,0,yes)
    # Flag94 also marks ordinary hit reactions. Only use it with the native
    # rush victim reaction34 or the attacker's rush-contact flag72; stale pair
    # fields from a previous move must never protect a later ordinary hit.
    tag=f'pending_{len(a.words)}';ready=tag+'_rush';done=tag+'_done'
    a.lw(8,actor,4016);a.addiu(9,0,34);a.branch(4,8,9,ready)
    for bank in (0x1085,0x10AD):
        a.i(36,8,actor,bank+(FLAG(0x72)>>3));a.i(12,8,8,1<<(FLAG(0x72)&7))
        a.branch(5,8,0,ready)
    a.jump(done);a.label(ready)
    for bank in (0x1085,0x10AD):
        a.i(36,8,actor,bank+(FLAG(0x94)>>3));a.i(12,8,8,1<<(FLAG(0x94)&7))
        a.branch(5,8,0,yes)
    a.label(done)


def gate_code():
    a = Assembler(GATE)
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'no')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'no')
    a.branch(4, 9, 0, 'no'); a.lw(11, 9); a.addiu(12, 0, 2); a.branch(5, 11, 12, 'no')
    a.lw(10, 8, 8); a.li(8, MODE); a.lw(9, 8); a.branch(4, 9, 0, 'no')
    a.lw(9, 8, 4); a.branch(5, 9, 10, 'no')
    a.lw(9, 8, 8); a.lw(8, 28, -22364); a.branch(5, 9, 8, 'no')
    a.addiu(2, 0, 1); a.jr()
    a.label('no'); a.move(2, 0); a.jr()
    return a.finish()


def scan(a, pointer, result, label):
    a.li(8, POINTERS); a.li(9, CONTROL); a.lw(9, 9, 8); a.move(result, 0)
    a.label(label); a.lw(10, 8); a.branch(4, 10, pointer, label+'_found')
    a.addiu(result, result, 1); a.addiu(8, 8, 4)
    a.branch(5, result, 9, label); a.jump('no')
    a.label(label+'_found')


def protected_code():
    # Caller supplies actual source/defender pointers. No actor-ID alias reads.
    a = Assembler(PROTECTED)
    a.branch(4, 4, 0, 'no'); a.branch(4, 5, 0, 'no')
    scan(a, 4, 14, 'source'); scan(a, 5, 15, 'target')
    # During native throw execution183..187, only the original two actors
    # remain supported. Their own scripted damage bypasses these new contacts.
    a.lw(10, 5, 0x948); a.addiu(11, 10, -183); a.i(11, 11, 11, 5)
    a.branch(4, 11, 0, 'special')
    a.i(11, 11, 14, 2); a.branch(4, 11, 0, 'yes')
    a.i(11, 11, 15, 2); a.branch(4, 11, 0, 'yes')
    a.jump('camera')
    # Native206C20 classifies paired special actors301..303/313..315.
    # 1CA6D0 and1CC2A0 copy the physical pair into both participants.
    a.label('special')
    if PENDING_CAPTURE:
        paired_pending(a, 5, 'pair'); a.jump('camera')
    else:
        a.addiu(11, 10, -301); a.i(11, 11, 11, 3); a.branch(5, 11, 0, 'pair')
        a.addiu(11, 10, -313); a.i(11, 11, 11, 3); a.branch(4, 11, 0, 'camera')
    a.label('pair'); a.lw(11, 5, 3732); a.lw(12, 5, 3736)
    if PENDING_CAPTURE:a.li(9, CONTROL); a.lw(9, 9, 8)
    a.r(0x2B, 13, 11, 9); a.branch(4, 13, 0, 'camera')
    a.r(0x2B, 13, 12, 9); a.branch(4, 13, 0, 'camera')
    a.branch(4, 11, 12, 'camera')
    a.branch(4, 15, 11, 'member'); a.branch(5, 15, 12, 'camera')
    a.label('member'); a.branch(4, 14, 11, 'no'); a.branch(4, 14, 12, 'no'); a.jump('yes')
    # Side-camera overrides are independent. Use the still-updated native
    # cinematic clock and actual bound model objects, without selecting it.
    a.label('camera'); a.lw(8, 28, -22180); a.branch(4, 8, 0, 'no')
    a.lw(10, 8, 812); a.branch(5, 10, 0, 'bound')
    a.lw(10, 8, 704); a.branch(4, 10, 0, 'no')
    a.lw(10, 8, 776); a.i(12, 10, 10, 3); a.addiu(11, 0, 1); a.branch(5, 10, 11, 'no')
    a.label('bound'); a.lw(11, 8, 768); a.lw(12, 8, 772)
    a.branch(4, 11, 0, 'no'); a.branch(4, 12, 0, 'no'); a.branch(4, 11, 12, 'no')
    a.lw(10, 5, 12); a.r(0, 10, 0, 10, 2); a.li(8, A(0x31C640)); a.r(0x2D, 8, 8, 10); a.lw(10, 8)
    a.branch(4, 10, 11, 'bound_target'); a.branch(5, 10, 12, 'no')
    a.label('bound_target'); a.lw(10, 4, 12); a.r(0, 10, 0, 10, 2)
    a.li(8, A(0x31C640)); a.r(0x2D, 8, 8, 10); a.lw(10, 8)
    a.branch(4, 10, 11, 'no'); a.branch(4, 10, 12, 'no')
    a.label('yes'); a.addiu(2, 0, 1); a.jr()
    a.label('no'); a.move(2, 0); a.jr()
    return a.finish()


def throw_code():
    a = Assembler(THROW)
    a.addiu(8, 0, 92); a.branch(4, 5, 8, 'check')
    a.addiu(8, 0, 94); a.branch(5, 5, 8, 'no')
    a.label('check'); a.branch(4, 4, 0, 'no'); scan(a, 4, 14, 'source')
    a.i(11, 10, 14, 2); a.branch(4, 10, 0, 'yes')
    # A human leader can target an extra too; retain throws only0<->1.
    a.li(8, TARGETS); a.r(0, 10, 0, 14, 2); a.r(0x2D, 8, 8, 10); a.lw(10, 8)
    a.i(14, 11, 14, 1); a.branch(4, 10, 11, 'no')
    a.label('yes'); a.addiu(2, 0, 1); a.jr()
    a.label('no'); a.move(2, 0); a.jr()
    return a.finish()


def wrapper(entry, cave, kind, rejected, original, index):
    a = Assembler(cave); a.addiu(29, 29, -0x90)
    for i, reg in enumerate(SAVED): a.i(63, reg, 29, i*8)
    a.call(GATE); a.branch(4, 2, 0, 'native')
    if kind == 'queued':
        a.lw(8, 4, 3904); a.li(9, CONTROL); a.lw(9, 9, 8)
        a.r(0x2B, 10, 8, 9); a.branch(4, 10, 0, 'native')
        a.r(0, 8, 0, 8, 2); a.li(9, POINTERS); a.r(0x2D, 8, 8, 9); a.lw(5, 8)
    elif kind == 'projectile':
        a.branch(4, 5, 0, 'native'); a.lw(8, 5, 100); a.branch(4, 8, 0, 'native')
        a.lw(8, 8); a.li(9, CONTROL); a.lw(9, 9, 8)
        a.r(0x2B, 10, 8, 9); a.branch(4, 10, 0, 'native')
        a.move(5, 4); a.r(0, 8, 0, 8, 2); a.li(9, POINTERS); a.r(0x2D, 8, 8, 9); a.lw(4, 8)
    elif kind == 'reverse': a.move(8, 4); a.move(4, 5); a.move(5, 8)
    a.call(THROW if kind == 'throw' else PROTECTED); a.branch(4, 2, 0, 'native')
    a.li(8, CONTROL); a.lw(9, 8, 16+4*index); a.addiu(9, 9, 1); a.sw(9, 8, 16+4*index)
    for i, reg in enumerate(SAVED): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x90); a.addiu(2, 0, rejected); a.jr()
    a.label('native')
    for i, reg in enumerate(SAVED): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x90)
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21)
        a.emit(word)
    a.jump(entry+8)
    code = a.finish(); assert len(code) <= 0x400; return code


def build_memory(ram, config=None, source='<offline-memory>'):
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB captured EE RAM')
    manager = u(A(0x2FEB14))
    if not 0x100000 <= manager <= len(ram)-0x1000 or u(manager) != 2:
        raise ValueError('Requires the native two-row actor manager')
    if config is None:
        count = u(MODE+4)
        if not u(MODE) or u(MODE+8) != manager or not 4 <= count <= 12:
            raise ValueError('Requires a captured exposed team or explicit hidden configuration')
        actors = [u(POINTERS+i*4) for i in range(count)]
    else:
        import fresh_team_ai
        config = fresh_team_ai.normalize(config)
        fresh_team_ai.validate_world(ram, u, config)
        actors = [row['actor'] for row in config['actors']]; count = len(actors)
    for i, actor in enumerate(actors):
        if not 0x100000 <= actor <= len(ram)-0x1600 or u(actor) != i or u(actor+12) >= 12:
            raise ValueError('Invalid or aliased captured actor')
    if len(set(actors)) != count: raise ValueError('Duplicate actor pointers')
    _, _, native = elf_reader(elf_path(ROOT))
    pieces = [(GATE, gate_code()), (PROTECTED, protected_code()), (THROW, throw_code()),
              (CONTROL, struct.pack('<16I', 1, manager, count, 0, *([0]*12)))]
    for index, (entry, cave, kind, rejected) in enumerate(SPECS):
        original = native(entry, 8)
        if ram[entry:entry+8] != original: raise ValueError(f'Native contact entry changed:{entry:X}')
        pieces += [(cave, wrapper(entry, cave, kind, rejected, original, index)),
                   (entry, struct.pack('<2I', (2<<26)|(cave>>2), 0))]
    blocks = []
    for p, data in pieces:
        old = ram[p:p+len(data)]
        if p >= GATE and any(old): raise ValueError(f'Occupied cinematic reservation:{p:X}')
        blocks.append(dict(address=p, expected_hex=old.hex(), data_hex=data.hex()))
    intervals = sorted((b['address'], b['address']+len(bytes.fromhex(b['data_hex']))) for b in blocks)
    assert all(end <= q for (_, end), (q, _) in zip(intervals, intervals[1:]))
    support = [dict(address=b['address'], data_hex=b['data_hex']) for b in blocks if b['address'] != CONTROL]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
        control=CONTROL, status='SCOPED CINEMATIC CONTACT ISOLATION AND EXTRA-PAIR THROW SUPPRESSION',
        support={'capacity': count, 'features': {'cinematic_contact_isolation': support, 'throw_limits': support}},
        scope=['Reject outside new melee, queued melee, projectile, and special contact against captured paired states.',
               'Preserve contact from the bound pair and all unrelated fights.',
               'Throw commands92/94 remain available only for the original physical0/1 pair.'],
        limitations=['Apply before reproducing the interruption; already queued damage is not cancelled.',
                     'Throw animation resource routing is not repaired; unsupported pair initiation is suppressed.',
                     'Paired-state/entry coverage has offline tests; live interruption reproduction remains required.'])


def build(source, config=None):
    return build_memory(read_ram(source), config, source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source); x.out.write_text(json.dumps(result, indent=2)+'\n'); print(x.out)
