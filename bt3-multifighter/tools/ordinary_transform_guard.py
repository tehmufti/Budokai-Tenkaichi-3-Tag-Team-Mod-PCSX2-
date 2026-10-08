"""Bound ordinary extra form changes while preserving native leader forms.

Commands99..103 use2033C8/203610 and actions236..240; commands104..106
instead use the already guarded fusion path. This offline upgrade preserves
the existing Spirit Bomb queue guards and extends installed admission scope.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import fresh_team_safety as safety
import extra_transform_guard as previous
import cinematic_admission as admission
from battle_mode_policy import ACTOR_COUNTS

ENTRIES = ((A(0x2033C8), 0x073F8000, 'Ordinary form eligibility commands99..103'),
           (A(0x203610), 0x073F8400, 'Ordinary form initiation including scripted116..119'))
END = 0x073F8800


def entry_parts(native):
    parts = []
    for index, (entry, cave, purpose) in enumerate(ENTRIES, 7):
        original = native(entry, 8); owned = cave+0x200
        parts += [(cave, admission.wrapper(entry, cave, owned, original, index), purpose+' with early cinematic admission'),
                  (owned, safety.owned_code(entry, owned, 2, original), purpose+' captured-extra bound'),
                  (entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0), purpose)]
    return parts


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if not 0x100000 <= manager < len(ram)-0x1000 or u(manager) != 2:
        raise ValueError('Native captured actor manager required')
    if (u(core.MODE) != 1 or count not in ACTOR_COUNTS or u(core.MODE+8) != manager
            or u(core.MODE+12) != count or u(core.PAIR+4)):
        raise ValueError('Active captured4/6 team with restored actor IDs required')
    actors = [u(core.POINTERS+4*i) for i in range(count)]
    if len(set(actors)) != count: raise ValueError('Duplicate captured actors')
    for i, actor in enumerate(actors):
        if not 0x100000 <= actor < len(ram)-0x1600 or u(actor) != i:
            raise ValueError('Captured actor identity changed')
    _, _, native = elf_reader(elf_path(ROOT))
    # The earlier admission layer may wrap203BA0. Validate its preserved body,
    # both queue hooks and their complete payloads without replacing that chain.
    for address, data in previous.loader_guard_segments(native):
        if address == previous.loader.TRANSFORM_HOOK: continue
        if ram[address:address+len(data)] != data:
            raise ValueError(f'Preserve Spirit Bomb loader guard at{address:08X}')
    if any(ram[ENTRIES[0][1]:END]): raise ValueError('Ordinary-transform reservation occupied')
    for entry, cave, purpose in ENTRIES:
        original = native(entry, 8)
        if ram[entry:entry+8] != original:
            raise ValueError(f'Ordinary-transform entry changed at{entry:08X}')
    pieces = entry_parts(native)
    old = admission.predicate_code(ordinary_forms=False)
    new = admission.predicate_code()
    installed = ram[admission.PREDICATE:admission.PREDICATE+len(new)]
    if installed == old:
        pieces.append((admission.PREDICATE, new, 'Include ordinary236..240 in active cinematic admission'))
    elif installed != new:
        raise ValueError('Installed cinematic admission predicate missing or changed')
    if tuple(u(admission.CONTROL+off) for off in (0, 4, 8)) != (1, manager, count):
        raise ValueError('Active matching cinematic admission control required')
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex(), purpose=why)
              for p, d, why in pieces]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
                status='ORDINARY EXTRA FORMS BOUNDED; NATIVE LEADERS PRESERVED',
                support={'features': {'ordinary_extra_transform_bounds': [
                    dict(address=b['address'], data_hex=b['data_hex']) for b in blocks]}},
                evidence=['2034F0 routes commands99..103 through2033C8 then203610.',
                          '203610 queues236..240; scripted204918 also calls it directly.',
                          '2033C8 indexes fixed scene rows through12B4F0, before queuing any reload.'],
                limitations=['This closes unsupported extra form entry; it does not implement extra reloads.',
                             'The native leader reload transaction is unchanged and requires separate live verification.',
                             'Admission rejects a new leader form while another cinematic owns the sequence; ordinary melee protection is separate.'])


def build(source): return build_memory(read_ram(source), source=source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args(); result = build(x.source)
    x.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'{x.out}: {len(result["blocks"])} guarded blocks')
