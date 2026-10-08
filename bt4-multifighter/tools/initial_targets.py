"""Seed matching opposing roster slots only in a captured, unreleased team.

Fresh actor configuration already uses this plan. Preserved presets need these
target data words updated because their original AI target table is retained.
No frame hook is installed: later player and CPU target choices stay owned by
the existing lock-on, survivor and retaliation paths.
"""
from native_map import CRC, SERIAL
import struct

import fresh_team_ai as ai
import fresh_team_combat as core
import fresh_memory
import team_participation as participation
import team_start_gate as start
from battle_mode_policy import ACTOR_COUNTS


def build_memory(ram, source='<held-prepared>'):
    if len(ram) != 0x8000000:
        raise ValueError('Requires128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if (not 0x100000 <= manager < len(ram)-16 or u(manager) != 2 or
            count not in ACTOR_COUNTS or
            tuple(u(core.MODE+o) for o in (0, 8, 12)) != (1, manager, count) or
            u(core.PAIR+4) != 0):
        raise ValueError('Requires a captured expanded team without AI aliases')
    if (tuple(u(start.CONTROL+o) for o in (0, 8, 12, 20)) != (1, manager, count, 0) or
            u(start.REQUEST) not in (0, 1) or u(fresh_memory.CONTROL+80) != 1):
        raise ValueError('Initial targets require the unreleased preparation hold')
    if (u(participation.CONTROL) not in (0, 5) or
            (u(participation.CONTROL+4), u(participation.CONTROL+8)) != (manager, count) or
            u(participation.CONSUMED) != 0):
        raise ValueError('Initial targets require the original selected participation')
    mask = u(participation.PRESENT)
    targets = participation.target_plan(count, mask)
    actors = []
    for i in range(count):
        actor = u(core.POINTERS+4*i)
        if (not 0x100000 <= actor < len(ram)-0x1600 or
                (u(actor), u(actor+8)) != (i, i&1) or
                u(start.CONTROL+0x80+4*i) != actor):
            raise ValueError('Changed captured actor identity')
        if any(u(actor+o) for o in (0x1278, 0x127C, 0x1280, 0x1284)):
            raise ValueError('Initial targets require all fighter inputs held')
        if mask & (1 << i):
            slot, slots = u(actor+0x994), u(actor+0x998)
            if (not 0 <= slot < slots <= 5 or not u(actor+0x9E4+164*slot) or
                    u(actor+0x948) != 11):
                raise ValueError('Initial targets require living idle selected fighters')
        descriptor = ai.DESCRIPTORS[i]
        if tuple(u(descriptor+o) for o in (0, 4, 8, 20)) != (actor, ai.SHADOWS[i], i&1, i):
            raise ValueError('Changed private AI descriptor identity')
        actors.append(actor)
    if len(set(actors)) != count:
        raise ValueError('Aliased captured actors')
    pieces = [(core.TABLE, struct.pack(f'<{count}I', *targets))]
    pieces += [(ai.DESCRIPTORS[i]+24, struct.pack('<I', ai.DESCRIPTORS[target]))
               for i, target in enumerate(targets)]
    return dict(serial=SERIAL, crc=CRC, source=str(source),
                initial_leader_targets=[1, 0],
                initial_targets=targets,
                blocks=[dict(address=p, expected_hex=ram[p:p+len(data)].hex(), data_hex=data.hex())
                        for p, data in pieces if ram[p:p+len(data)] != data])
