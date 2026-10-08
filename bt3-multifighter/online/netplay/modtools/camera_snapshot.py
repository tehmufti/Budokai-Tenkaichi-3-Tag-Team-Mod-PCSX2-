"""Read camera ownership from an offline EE RAM dump or PCSX2 save state.

No emulator connection, process-memory access or game mutation.
"""
from native_map import A, FLAG
import argparse
import json
import os
import struct
import zipfile
from pathlib import Path

GP = 0x304270
SCENE = A(0x331DC8)
CAMERA_MANAGER = A(GP - 22172)
ACTIVE_CAMERA = A(GP - 22176)
CINEMATIC_CAMERA = A(GP - 22180)

# Stage images a preparation already holds in memory, under the file path its
# builders are given. An entry is exactly what that path holds (or would hold),
# so reading it skips a 128 MiB file round-trip and nothing else. The owner
# retracts it; a path it never wrote then reads as missing, never stale.
PUBLISHED_LIMIT = 2
_published = {}


def _published_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def publish(path, data):
    """Serve data as the contents of path to read_ram() until retract(path)."""
    if type(data) is not bytes:
        raise TypeError('Only an immutable bytes image can be published')
    key = _published_key(path)
    _published.pop(key, None)
    _published[key] = data
    while len(_published) > PUBLISHED_LIMIT:
        del _published[next(iter(_published))]


def published(path):
    """The image published for path, or None."""
    return _published.get(_published_key(path)) if _published else None


def retract(path):
    if _published:
        _published.pop(_published_key(path), None)


def read_ram(path):
    data = published(path)
    if data is not None:
        return data
    path = Path(path)
    if not path.name.lower().endswith(('.p2s','.p2s.backup')):
        return path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo('eeMemory.bin')
        # Deflate64/LZMA2 (PCSX2 2.6 options) would otherwise fail as NotImplementedError.
        from state128 import require_readable
        require_readable(info)
        if info.compress_type not in (20, 93):
            return archive.read(info)
        import zstandard
        with path.open('rb') as stream:
            stream.seek(info.header_offset)
            header = stream.read(30)
            name_size, extra_size = struct.unpack_from('<HH', header, 26)
            stream.seek(name_size + extra_size, 1)
            raw = stream.read(info.compress_size)
        return zstandard.ZstdDecompressor().decompress(raw, max_output_size=info.file_size)


def inspect(ram):
    assert len(ram) in (0x2000000, 0x8000000)
    u = lambda address: struct.unpack_from('<I', ram, address)[0]
    signed = lambda address: struct.unpack_from('<i', ram, address)[0]
    vec = lambda address: list(struct.unpack_from('<3f', ram, address))
    # index: a USA native actor-flag number (keys below stay USA numbers); FLAG gives this disc's number.
    flag = lambda actor, index: bool((ram[actor + 4229 + (FLAG(index) >> 3)] |
                                     ram[actor + 4269 + (FLAG(index) >> 3)]) & (1 << (FLAG(index) & 7)))
    manager, active, cinematic = u(CAMERA_MANAGER), u(ACTIVE_CAMERA), u(CINEMATIC_CAMERA)
    actor_manager = u(A(0x2FEB14))
    actor_pointers = [u(actor_manager + 4), u(actor_manager + 4) + 0x1600,
                      u(0xB301C), u(0xB305C)]
    labels = ('leader0', 'leader1', 'extra2', 'extra3')
    actors = []
    for label, pointer in zip(labels, actor_pointers):
        if not 0x100000 <= pointer < len(ram) - 0x1600:
            continue
        model_id = u(pointer + 12)
        model = u(A(0x31C640) + model_id * 4)
        actors.append({'label': label, 'pointer': hex(pointer), 'physical_id': u(pointer),
                       'model_id': model_id, 'model': hex(model),
                       'world_position': [base + offset for base, offset in zip(vec(pointer + 16), vec(pointer + 48))],
                       'camera_eye': vec(pointer + 1072), 'camera_angles': vec(pointer + 1088),
                       'camera_priority_flag_D3': flag(pointer, 0xD3),
                       'camera_flags': {hex(i): flag(pointer, i) for i in (5, 0xB8, 0xCC, 0xDC)},
                       'model_height': struct.unpack_from('<f', ram, model + 4084)[0]})
    normal = [manager + 1824 + side * 656 for side in range(2)]
    camera_rows = []
    for side, camera in enumerate(normal):
        owner_model = u(SCENE + 808 + side * 624)
        owners = [item['label'] for item in actors if item['model_id'] == owner_model]
        copied = [item['label'] for item in actors
                  if ram[camera + 608:camera + 620] == ram[int(item['pointer'], 16) + 1072:int(item['pointer'], 16) + 1084]]
        camera_rows.append({'side': side, 'pointer': hex(camera), 'roster_owner_model': owner_model,
                            'expected_owner': owners, 'copied_eye_matches': copied,
                            'priority': signed(camera + 648), 'viewport_mode': u(camera + 640),
                            'eye': vec(camera + 608), 'angles': vec(camera + 624),
                            'render_eye': vec(camera + 544)})
    flags = u(cinematic + 776)
    enabled = bool(u(cinematic + 812) or (u(cinematic + 704) and flags & 1 and not flags & 2))
    bounds = []
    for offset in (768, 772):
        pointer = u(cinematic + offset)
        model_id = u(pointer + 16) if 0x100000 <= pointer < len(ram) - 20 else None
        bounds.append({'field': offset, 'pointer': hex(pointer), 'model_id': model_id,
                       'actor_matches': [item['label'] for item in actors if item['model_id'] == model_id]})
    priority = [row['priority'] for row in camera_rows]
    priority_side = priority.index(max(priority)) if priority[0] != priority[1] else None
    active_owner = ('cinematic' if active == cinematic else
                    f'leader_camera_{normal.index(active)}' if active in normal else 'other')
    return {'camera_globals': {'manager_global': hex(CAMERA_MANAGER), 'manager': hex(manager),
                               'render_current_global': hex(ACTIVE_CAMERA), 'render_current': hex(active),
                               'manager_selected': hex(u(manager + 3136)),
                               'cinematic_global': hex(CINEMATIC_CAMERA), 'cinematic': hex(cinematic)},
            'active_camera_kind': active_owner, 'battle_mode': u(SCENE + 8),
            'two_viewport_mode': u(SCENE + 36) == 1, 'replay_mode': u(A(0x31BE04)),
            'side_cpu_config': [u(SCENE + 712 + side * 624) for side in range(2)],
            'cpu_view_preference': signed(A(GP - 20464)), 'higher_priority_side': priority_side,
            'pair_ai_alias_active': u(0xC4004), 'old_ai_alias_active': u(0xBD000),
            'normal_cameras': camera_rows,
            'cinematic': {'active_predicate_23DBC0': enabled, 'direct_override': u(cinematic + 812),
                          'animation_data': hex(u(cinematic + 704)), 'flags': hex(flags),
                          'animation_time': struct.unpack_from('<f', ram, cinematic + 752)[0],
                          'render_eye': vec(cinematic + 544), 'bound_models': bounds},
            'actors': actors}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    result = inspect(read_ram(args.source))
    text = json.dumps(result, indent=2) + '\n'
    if args.out:
        args.out.write_text(text)
    else:
        print(text, end='')
