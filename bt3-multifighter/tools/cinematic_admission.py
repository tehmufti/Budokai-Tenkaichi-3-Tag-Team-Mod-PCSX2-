"""Serialize new special/transform admission around BT3's single cinematic camera.

The eligibility hooks run before resource consumption or action queue writes.
An existing sequence can continue; a different living fighter's current,
requested, or queued special/transform holds back new requests. This is a
conservative special-sequence limit, not independent cinematic cameras.
Offline captured4/6 builder. Existing extra-transform and loader guards remain.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import fresh_team_safety as safety
import extra_transform_guard as transforms
from battle_mode_policy import ACTOR_COUNTS

PREDICATE, CONTROL, END = 0x073F4000, 0x073F7F00, 0x073F8000
CINEMATIC = A(0x2FEBCC)
ACTION_FIELDS = (2376, 2380, 2388, 2392, 2396, 2400)
SAVED = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 31)
# entry, new wrapper, exact preceding wrapper (None means native first8)
ENTRIES = ((A(0x203CE0), 0x073F5000, None, 'Blast2/ultimate eligibility'),
           (A(0x203FB0), 0x073F5400, None, 'Blast1 eligibility'),
           (A(0x203788), 0x073F5800, 0x073E0000, 'Forward transform eligibility104..106'),
           (A(0x203BA0), 0x073F5C00, 0x073CE400, 'Reverse transform command107'),
           (A(0x2039B0), 0x073F6000, 0x073E0400, 'Direct/scripted forward transform start'),
           (A(0x203C08), 0x073F6400, 0x073E0800, 'Direct/scripted reverse transform start'),
           (A(0x203168), 0x073F6800, None, 'MAX POWER command80 special follow-up admission'))


def busy(a, actor, label, ordinary_forms=True):
    """Only t0/t1. Previous2384 is deliberately excluded: it persists at idle."""
    for offset in ACTION_FIELDS:
        a.lw(8, actor, offset)
        for first, length in ((253, 63), (236, 8) if ordinary_forms else (241, 3)):
            a.addiu(9, 8, -first); a.i(11, 9, 9, length)
            a.branch(5, 9, 0, label)


def predicate_code(ordinary_forms=True):
    # a0 actual actor pointer; v0 blocked, v1 reason. Leaf, volatile GPRs only.
    a = Assembler(PREDICATE)
    core.gate(a, 'allow'); a.move(15, 10)
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'allow')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'allow')
    a.lw(9, 8, 8); a.branch(5, 9, 15, 'allow')
    # Pointer identity works while the AI temporarily aliases actor+0.
    a.li(13, core.POINTERS); a.move(12, 0)
    a.label('find'); a.lw(11, 13); a.branch(4, 11, 4, 'owned')
    a.addiu(13, 13, 4); a.addiu(12, 12, 1); a.branch(5, 12, 15, 'find')
    a.jump('allow')
    a.label('owned')
    # Own in-flight setup and continuation never competes with its defender.
    busy(a, 4, 'allow', ordinary_forms)
    a.li(13, core.POINTERS); a.move(12, 0)
    a.label('others'); a.lw(11, 13)
    a.branch(4, 11, 4, 'next'); a.branch(4, 11, 0, 'next')
    # Current roster HP, not a fixed leader/bench slot or copied initial value.
    a.lw(8, 11, 0x994); a.i(11, 9, 8, 5); a.branch(4, 9, 0, 'next')
    a.r(0, 9, 0, 8, 2); a.r(0x2D, 9, 9, 8); a.r(0, 9, 0, 9, 3)
    a.r(0x2D, 9, 9, 8); a.r(0, 9, 0, 9, 2); a.r(0x2D, 9, 9, 11)
    a.lw(8, 9, 0x9E4); a.r(0x2A, 9, 0, 8); a.branch(4, 9, 0, 'next')
    busy(a, 11, 'sequence', ordinary_forms)
    a.label('next'); a.addiu(13, 13, 4); a.addiu(12, 12, 1)
    a.branch(5, 12, 15, 'others')
    # A native track can outlast the action transition by a few updates.
    a.lw(11, 28, -22180); a.branch(4, 11, 0, 'allow')
    a.lw(8, 11, 812); a.branch(5, 8, 0, 'bound')
    a.lw(8, 11, 704); a.branch(4, 8, 0, 'allow')
    a.lw(8, 11, 776); a.i(12, 8, 8, 3); a.addiu(9, 0, 1)
    a.branch(5, 8, 9, 'allow')
    a.label('bound'); a.lw(8, 4, 12); a.i(11, 9, 8, 12)
    a.branch(4, 9, 0, 'camera'); a.r(0, 8, 0, 8, 2)
    a.li(9, core.MODELS); a.r(0x2D, 8, 8, 9); a.lw(8, 8)
    a.branch(4, 8, 0, 'camera')
    for offset in (768, 772):
        a.lw(9, 11, offset); a.branch(4, 8, 9, 'allow')
    a.label('camera'); a.addiu(3, 0, 2); a.jump('blocked')
    a.label('sequence'); a.addiu(3, 0, 1)
    a.label('blocked'); a.addiu(2, 0, 1); a.jr()
    a.label('allow'); a.move(2, 0); a.move(3, 0); a.jr()
    result = a.finish(); assert len(result) <= 0x1000; return result


def wrapper(entry, cave, previous, original, index):
    a = Assembler(cave); a.addiu(29, 29, -0x90)
    for i, register in enumerate(SAVED): a.i(63, register, 29, i*8)
    a.call(PREDICATE); a.branch(4, 2, 0, 'native')
    a.li(8, CONTROL); a.lw(9, 8, 16); a.addiu(9, 9, 1); a.sw(9, 8, 16)
    a.sw(4, 8, 20); a.sw(3, 8, 24)
    a.lw(9, 8, 32+index*4); a.addiu(9, 9, 1); a.sw(9, 8, 32+index*4)
    for i, register in enumerate(SAVED): a.i(55, register, 29, i*8)
    a.addiu(29, 29, 0x90); a.move(2, 0); a.jr()
    a.label('native')
    for i, register in enumerate(SAVED): a.i(55, register, 29, i*8)
    a.addiu(29, 29, 0x90)
    if previous is not None:
        a.jump(previous)
    else:
        safety.native_tail(a, entry, original)
    result = a.finish(); assert len(result) <= 0x400; return result


def prior_segments(native):
    result = transforms.loader_guard_segments(native)
    for entry, cave, _ in transforms.ENTRIES:
        result += [(cave, safety.owned_code(entry, cave, 2, native(entry, 8))),
                   (entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0))]
    return result


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE memory')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if not 0x100000 <= manager < len(ram)-0x1000 or u(manager) != 2:
        raise ValueError('Native captured manager required')
    if (u(core.MODE) != 1 or u(core.MODE+8) != manager or count not in ACTOR_COUNTS
            or u(core.MODE+12) != count):
        raise ValueError('Active captured4/6 team required')
    actors = [u(core.POINTERS+i*4) for i in range(count)]
    if len(set(actors)) != count: raise ValueError('Duplicate captured actors')
    for i, actor in enumerate(actors):
        if not 0x100000 <= actor < len(ram)-0x1600 or u(actor) != i:
            raise ValueError('Captured actor identity is invalid or AI-aliased')
        mid = u(actor+12)
        if mid >= 12 or not 0x100000 <= u(core.MODELS+mid*4) < len(ram)-0x1670:
            raise ValueError('Captured actor model is not registered')
    _, _, native = elf_reader(elf_path(ROOT))
    for p, data in prior_segments(native):
        if ram[p:p+len(data)] != data:
            raise ValueError(f'Prior extra-transform/Spirit Bomb loader guard changed at{p:08X}')
    if any(ram[PREDICATE:END]): raise ValueError('Cinematic admission reservation occupied')
    control = bytearray(0x100); struct.pack_into('<3I', control, 0, 1, manager, count)
    pieces = [(PREDICATE, predicate_code(), 'Pointer-owned early cinematic admission predicate'),
              (CONTROL, bytes(control), 'Enabled,captured manager/count,denials,last actor/reason,per-hook denials')]
    for index, (entry, cave, previous, purpose) in enumerate(ENTRIES):
        original = native(entry, 8)
        expected = struct.pack('<2I', (2 << 26) | (previous >> 2), 0) if previous else original
        if ram[entry:entry+8] != expected:
            raise ValueError(f'Admission entry changed at{entry:08X}')
        pieces += [(cave, wrapper(entry, cave, previous, original, index), purpose),
                   (entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0), purpose)]
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex(), purpose=w)
              for p, d, w in pieces]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
                status='EARLY SERIALIZED SPECIAL AND TRANSFORM ADMISSION', control=CONTROL,
                telemetry=dict(denials=CONTROL+16, last_actor=CONTROL+20, reason=CONTROL+24,
                               per_entry_denials=CONTROL+32),
                scope=['Current/requested/queued actions253..315 and236..243 reserve the shared cinematic sequence.',
                       'Native eligibility rejects competing new requests before spending resources or queuing actions.',
                       'Own continuation, ordinary attacks and existing extra-transform restrictions are preserved.'],
                limitations=['Conservative: includes special attacks that do not use a paired cinematic.',
                             'A blocked scripted transform flag from204918 is consumed, not deferred; normal controls can retry.',
                             'Install before starting a sequence; already concurrent sequences are not interrupted.',
                             'This serializes covered starts; it does not create more cinematic camera objects.'])


def build(source): return build_memory(read_ram(source), source=source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args(); result = build(x.source)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
