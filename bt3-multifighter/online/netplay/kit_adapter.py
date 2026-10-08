"""Select one reviewed disc adapter per process, before importing guest-code builders.

Different discs cannot share a room: the existing executable/resource/full-image
handshake still compares their identities. Region support is not cross-region play.
"""
import json
import os
import sys
from pathlib import Path

SUPPORTED = ('bt3-usa', 'bt3-pal', 'bt3-jpn', 'bt4-b14-rev2-eng')


def profile(root):
    game = Path(root) / 'game'
    try:
        active = json.loads((game / 'discs/active.json').read_text(encoding='utf-8'))
        key = active.get('key')
        import re
        if active.get('schema') == 1 and isinstance(key, str) and re.fullmatch('[0-9a-f]{16}', key):
            candidate = game / 'discs' / key / 'game-profile.json'
            if candidate.is_file():
                return json.loads(candidate.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    for name in ('game-profile.json', 'player-install.json'):
        try:
            return json.loads((game / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    raise ValueError('No readable installed game profile')


def bootstrap(paths):
    """Installed profiles are authoritative; standalone developer tests use an explicit adapter."""
    adapter = profile(paths.INSTALL_ROOT).get('adapter') if paths.INTEGRATED else os.environ.get('TTM_ONLINE_ADAPTER', 'bt3-usa')
    if adapter not in SUPPORTED:
        raise ValueError('Online requires a reviewed BT3 USA/Europe/Japan or BT4 B14 REV2 adapter')
    os.environ['TAGTEAM_ADAPTER'] = adapter
    if paths.INTEGRATED:
        root, tool_dir = paths.INSTALL_ROOT, paths.INSTALL_ROOT / 'game' / 'tools'
    else:
        root = paths.KIT.parents[1]
        project = 'bt4-multifighter' if adapter.startswith('bt4') else 'bt3-multifighter'
        tool_dir = root / project / 'tools'
    # The installed adapter's helpers take precedence over the portable USA fallback.
    for directory in (paths.MODTOOLS, root, tool_dir, paths.NETPLAY):
        value = str(directory)
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)
    return adapter


def identity(iso):
    from iso_compatibility.adapters import quick_identify
    adapter, evidence, serial = quick_identify(iso)
    if adapter not in SUPPORTED or not evidence.get('verified'):
        raise ValueError(evidence.get('reason') or 'No reviewed online adapter for this disc')
    return adapter, evidence, serial


def state_name(slot):
    from native_map import SERIAL, CRC
    import kit_paths
    if kit_paths.ADAPTER.startswith('bt4'):
        SERIAL = 'SLUS-21978'
    return f'{SERIAL} ({CRC}).{slot}.p2s'


def pause_value(usa, pal):
    from native_map import PAL
    return pal if PAL else usa


def roster_count():
    import kit_paths
    return 250 if kit_paths.ADAPTER.startswith('bt4') else 161


def stage_count():
    import kit_paths
    return 99 if kit_paths.ADAPTER.startswith('bt4') else 35
