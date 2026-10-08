"""Capture ordinary BT3 selected teams from offline128MB RAM or a save state.

This reads completed native leader roster rows and writes a descriptor JSON.
It neither spawns fighters nor connects to an emulator. Fresh native two-actor
getters are required; exposed prototype checkpoints are intentionally rejected.
"""
from native_map import A, CRC, SERIAL, SERIAL_FILE, elf_path
import argparse
import copy
import hashlib
import json
import os
import struct
from pathlib import Path

from camera_snapshot import read_ram
from prototype import ROOT, elf_reader
from battle_mode_policy import TEAM_CAPACITY
from native_map import FILE_ID

RAM_BYTES = 0x08000000
MANAGER_GLOBAL, MODEL_TABLE, REPLAY_FLAG = A(0x2FEB14), A(0x31C640), A(0x31BE04)
ACTOR_BYTES, MODEL_BYTES = 0x1600, 0x1670
ROW_BASE, ROW_BYTES, SLOT_OFFSET, COUNT_OFFSET = 0x9A4, 0xA4, 0x994, 0x998
NATIVE_RANGES = ((A(0x1DC168), 0x10), (A(0x1DC178), 0x28), (A(0x12B190), 0x40), (A(0x1C02C8), 0x270))



def selected_damage(row):
    """Native roster stats+0x20 (row+0x60) is the starting clothes state.

    Read the native row, not the leader's pending reload flag: teammates can
    equip different Potaras. Older capture files did not export this field.
    """
    raw = row.get('native_row_hex')
    value = struct.unpack_from('<I', bytes.fromhex(raw), 0x60)[0] if raw else int(row.get('damaged', False))
    if value not in (0, 1):
        raise ValueError('Selected member has an invalid starting clothes state')
    damaged = bool(value)
    if 'damaged' in row and (type(row['damaged']) is not bool or row['damaged'] != damaged):
        raise ValueError('Selected member clothes state disagrees with its native row')
    return damaged


class ChosenElf(os.PathLike):
    """The chosen game disc's executable (native_map.elf_path(ROOT)), resolved each time it is opened, never at
    import: a process that imports this module before the disc is known still reads the right executable."""

    def __fspath__(self):
        return str(elf_path(ROOT))

    def __repr__(self):
        return 'ChosenElf()'


def capture(ram, elf_path=ChosenElf(), *, minimum_members=1):
    """Return validated interleaved selection descriptors without modifying ram."""
    if type(minimum_members) is not int or minimum_members not in (1,2):
        raise ValueError('The captured minimum must be one native or two reserved members per side')
    if len(ram) != RAM_BYTES:
        raise ValueError('Expected a full 128 MB EE RAM image for the isolated prototype runtime')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    def require(condition, reason):
        if not condition: raise ValueError(reason)
    def address(pointer, size, label, alignment=4):
        require(0x100000 <= pointer <= len(ram) - size and pointer % alignment == 0,
                f'{label} pointer is outside valid aligned game RAM')
        return pointer
    elf, _, readelf = elf_reader(Path(elf_path))
    for pointer, size in NATIVE_RANGES:
        require(ram[pointer:pointer + size] == readelf(pointer, size),
                f'Native routine {pointer:08X} changed; capture requires a fresh ordinary two-actor match')
    require(u(REPLAY_FLAG) == 0, 'Replay playback cannot be used as a fresh team selection')
    manager = address(u(MANAGER_GLOBAL), 640, 'Actor manager')
    require(u(manager) == 2, 'Native actor manager must contain exactly two leaders')
    actor_array = address(u(manager + 4), ACTOR_BYTES * 2, 'Native actor array', 16)
    for offset in (8, 12): address(u(manager + offset), 52 * 2, 'Native auxiliary array')
    leaders = []
    team_rows = []
    for side in range(2):
        actor = actor_array + side * ACTOR_BYTES
        require(u(actor) == side and u(actor + 8) == side, f'Leader{side} has inconsistent native side identity')
        count, slot = u(actor + COUNT_OFFSET), u(actor + SLOT_OFFSET)
        require(1 <= count <= 5, f'Team {side} must have between 1 and 5 selected members')
        require(slot < count, f'Team {side} active slot is outside its selected roster')
        require(slot == 0, f'Team{side} has already changed its active member; capture a fresh match before a KO/tag')
        model_id = u(actor + 12)
        require(model_id == side, f'Leader{side} must retain its native model slot')
        model = address(u(MODEL_TABLE + model_id * 4), MODEL_BYTES, f'Leader{side} model', 16)
        require(u(model + 16) == model_id and u(model + 4) == 1 and u(model + 8) == 1,
                f'Leader{side} model has not completed initialization')
        resource = address(u(model + 20), 56, f'Leader{side} resource')
        require(u(resource + 52) == side and u(resource + 48) == 1,
                f'Leader{side} is not using its native reserved loaded resource record')
        files = []
        for index in range(3):
            record = resource + index * 16
            pointer, size, file_id = u(record), u(record + 4), u(record + 8)
            require(size > 0, f'Leader{side} resource file{index} is empty')
            address(pointer, size, f'Leader{side} resource file{index}')
            files.append({'pointer': pointer, 'size': size, 'file_id': file_id})
        rows = []
        for selected_slot in range(count):
            row_pointer = actor + ROW_BASE + selected_slot * ROW_BYTES
            require(row_pointer + ROW_BYTES <= actor + ACTOR_BYTES, 'Selected roster row exceeds its native actor')
            row = bytes(ram[row_pointer:row_pointer + ROW_BYTES])
            character, costume, present = struct.unpack_from('<3I', row)
            hp, max_hp = struct.unpack_from('<2I', row, 64)
            require(character < 250, f'Team{side} slot{selected_slot} character ID is outside the USA native roster')
            require(costume < 0x80000000, f'Team{side} slot{selected_slot} has an uninitialized costume value')
            require(present == 1, f'Team{side} slot{selected_slot} is not an initialized selected member')
            require(0 < hp <= max_hp, f'Team{side} slot{selected_slot} has invalid or defeated health state')
            rows.append({'side': side, 'physical_id': selected_slot * 2 + side,
                         'participating': True, 'formation_slot': selected_slot,
                         'source_leader': actor, 'slot': selected_slot, 'character': character,
                         'costume': costume, 'damaged': selected_damage({'native_row_hex': row.hex()}),
                         'native_row_address': row_pointer,
                         'native_row_hex': row.hex(), 'hp': hp, 'max_hp': max_hp,
                         'source_model_id': model_id, 'source_model': model,
                         'source_resource': resource, 'source_resource_handle': side,
                         'is_native_active_member': selected_slot == slot,
                         'loaded_resource': None, 'loaded_resource_handle': None,
                         'actor_created': selected_slot == slot})
        require(u(model + 12) == rows[slot]['character'], f'Leader{side} model character does not match its selected active row')
        import bt4_resources
        expected_files=bt4_resources.request_files(rows[slot]['character'],rows[slot]['costume'],rows[slot]['damaged'])
        require([file['file_id'] for file in files] == expected_files,
                f'Leader{side} main bundle does not match its selected active character/costume')
        leaders.append({'side': side, 'actor': actor, 'model_id': model_id, 'model': model,
                        'resource': resource, 'resource_handle': side, 'resource_flags': 1,
                        'character': rows[slot]['character'], 'costume': rows[slot]['costume'],
                        'damaged': rows[slot]['damaged'],
                        'active_slot': slot, 'member_count': count, 'files': files})
        team_rows.append(rows)
    require(leaders[0]['model'] != leaders[1]['model'] and leaders[0]['resource'] != leaders[1]['resource'],
            'Native leaders alias the same model or reserved resource record')
    counts = [len(rows) for rows in team_rows]
    require(counts[0] == counts[1] or max(counts) <= TEAM_CAPACITY,
            f'Unequal teams support at most {TEAM_CAPACITY} selected members per side')
    # Only a leader's OWN active row stands on its native bundle. Any other
    # fighter that happens to share its character and costume must not: a native
    # leader reload overwrites the animation and combat files in place, and the
    # next reload by either leader overwrites the spare main buffer too, so a
    # sharer loses its animation, geometry and AI dataset mid-match. Such
    # fighters take their own load through the resource queue instead, which
    # still dedupes identical extras among themselves - safe, because the mod's
    # own extra reload retains the old buffers and re-claims the texture group.
    # Binding to the row's own side also removes the old first-match ambiguity
    # when both leaders are the same character. The active slot is always row 0
    # (checked above), so parity reservations copied from row 0 stay bound.
    for side, rows in enumerate(team_rows):
        for row in rows:
            if row['is_native_active_member']:
                row['loaded_resource'] = leaders[side]['resource']
                row['loaded_resource_handle'] = leaders[side]['resource_handle']
    interleaved = []
    reserved_members=max(minimum_members,max(counts))
    for slot in range(reserved_members):
        for side in range(2):
            if slot < counts[side]:
                row = team_rows[side][slot]
            else:
                # Reserve the parity slot using an ACTUAL leader row; never
                # read an absent bench member or infer its resource files.
                row = copy.deepcopy(team_rows[side][0])
                row.update(physical_id=2*slot+side, formation_slot=slot,
                           participating=False, is_native_active_member=False,
                           actor_created=False)
            interleaved.append(row)
    mask = sum(1 << r['physical_id'] for r in interleaved if r['participating'])
    return {'schema': 'bt3-selected-teams-v1', 'serial': SERIAL, 'crc': CRC,
            'status': 'SELECTION CAPTURE ONLY; NO FIGHTERS SPAWNED',
            'ram_bytes': len(ram), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
            'elf_sha256': hashlib.sha256(elf).hexdigest(), 'native_manager': manager,
            'native_actor_count': 2, 'native_actor_array': actor_array,
            'members_per_side': reserved_members, 'minimum_members': minimum_members,
            'intended_fighter_count': len(interleaved),
            'team_counts': counts, 'selected_fighter_count': sum(counts), 'participation_mask': mask,
            'native_row_bytes': ROW_BYTES, 'physical_order': 'slot0side0,slot0side1,slot1side0,slot1side1,...',
            'leaders': leaders, 'roster': interleaved,
            'requirements': ['Captured pointers and embedded row pointers belong to this exact checkpoint.',
                             'Resolve/load missing complete character bundles before model creation.',
                             'Allocate independent actor/model/animation/AI state for every bench member.',
                             'This is a selection schema, not the installed AI schema with completed actor pointers.'],
            'limitations': [f'Unequal teams up to {TEAM_CAPACITY} per side use explicit inactive reservation slots; a two-member minimum can reserve inactive slots for FFA1v1.',
                            'The costume field is preserved from native row+4; no additional costumes or resources are inferred.',
                            'Repeated selected characters may reuse a loaded bundle but still need independent actors/models.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='Offline128MB EE RAM image or PCSX2 save state')
    parser.add_argument('--out', type=Path, help='OutputJSON; defaults to source filename plus.selected-team.json')
    parser.add_argument('--elf', type=Path, default=elf_path(ROOT))
    args = parser.parse_args()
    result = capture(read_ram(args.source), args.elf)
    result['source'] = str(args.source.resolve())
    output = args.out or args.source.with_name(args.source.name + '.selected-team.json')
    if output.resolve() == args.source.resolve():
        raise ValueError('Output must differ from the source RAM/state file')
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(f'{output}: captured{result["team_counts"][0]}v{result["team_counts"][1]} selections; no spawning')


if __name__ == '__main__': main()
