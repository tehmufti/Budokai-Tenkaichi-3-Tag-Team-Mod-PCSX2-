"""Bound extra transformations until a complete private reload transaction exists.

The older extra_loader_guard protects command107 and the shared reload queue.
Commands104..106 use a different eligibility function, and scripted transforms
can bypass both command functions. These entry guards preserve native leaders
and match extras by captured pointer, including while AI aliases actor IDs.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from camera_snapshot import read_ram
from prototype import ROOT, elf_reader
import fresh_team_combat as core
import fresh_team_safety as safety
import extra_loader_guard as loader
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy

ENTRIES = ((A(0x203788), 0x073E0000, 'Forward transform eligibility for commands104..106'),
           (A(0x2039B0), 0x073E0400, 'Forward transform initiation, including scripted flags11A..11C'),
           (A(0x203C08), 0x073E0800, 'Reverse transform initiation, including scripted flag11D'))
END = 0x073E0C00


def loader_guard_segments(native):
    """Complete immutable payloads of the preceding Spirit Bomb freeze fix."""
    segments = [(loader.PUSH, loader.push_code()), (loader.READY, loader.ready_code()),
                (loader.TRANSFORM, safety.owned_code(loader.TRANSFORM_HOOK, loader.TRANSFORM, 2,
                                                     native(loader.TRANSFORM_HOOK, 8)))]
    for entry, code, tail in ((loader.PUSH_HOOK, loader.PUSH, loader.PUSH_TAIL),
                              (loader.READY_HOOK, loader.READY, loader.READY_TAIL)):
        segments += [(tail, loader.tail(entry, native(entry, 8), tail)),
                     (entry, struct.pack('<2I', (2 << 26) | (code >> 2), 0))]
    segments.append((loader.TRANSFORM_HOOK, struct.pack('<2I', (2 << 26) | (loader.TRANSFORM >> 2), 0)))
    return segments


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x08000000:
        raise ValueError('Requires128MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(core.ACTORS)
    if not 0x100000 <= manager < len(ram)-640 or u(manager) != 2:
        raise ValueError('Requires the native two-row actor manager')
    if config is None:
        if (u(core.MODE) != 1 or u(core.MODE+8) != manager or
                u(core.MODE+4) not in ACTOR_COUNTS or u(core.MODE+4) != u(core.MODE+12)):
            raise ValueError('Requires an active captured team or an explicit hidden configuration')
    else:
        import fresh_team_ai
        fresh_team_ai.validate_world(ram, u, fresh_team_ai.normalize(config))
    _, _, native = elf_reader(elf_path(ROOT))
    for p, data in loader_guard_segments(native):
        if ram[p:p+len(data)] != data:
            raise ValueError(f'Preserve the installed extra-loader/Spirit Bomb guard at{p:08X}')
    if any(ram[ENTRIES[0][1]:END]):
        raise ValueError('Extra transformation reservation occupied')
    blocks = []
    for entry, cave, purpose in ENTRIES:
        original = native(entry, 8)
        if ram[entry:entry+8] != original:
            raise ValueError(f'Native transform entry changed:{entry:08X}')
        code = safety.owned_code(entry, cave, 2, original)
        for address, data in ((cave, code), (entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0))):
            blocks.append(dict(address=address, expected_hex=ram[address:address+len(data)].hex(),
                               data_hex=data.hex(), purpose=purpose))
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status='EXTRA FORWARD/REVERSE TRANSFORM LIMIT; NATIVE LEADERS PRESERVED', blocks=blocks,
                support={'capacity': policy.emitted_actors(), 'features': {'extra_transform_bounds': [
                    dict(address=b['address'], data_hex=b['data_hex']) for b in blocks]}},
                evidence=['203900 handles104..106 through203788;203BA0 alone does not cover these commands.',
                          '204918 can call2039B0/203C08 directly after scripted flags11A..11D.',
                          '24B9A8 accepts only reserved resource handles0/1; dynamic extra handles are unsupported.'],
                limitations=['Extra transformations remain intentionally unavailable until staged model/AI commit is implemented.',
                             'This leaves the existing damaged-costume skip/ready guard unchanged.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--config', type=Path)
    p.add_argument('--out', required=True, type=Path)
    x = p.parse_args()
    result = build_memory(read_ram(x.source), json.loads(x.config.read_text()) if x.config else None, x.source)
    x.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'{x.out}: {len(result["blocks"])} guarded blocks')
