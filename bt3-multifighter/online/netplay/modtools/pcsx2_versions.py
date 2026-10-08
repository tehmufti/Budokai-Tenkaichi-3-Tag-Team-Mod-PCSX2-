"""PCSX2 versions the mod runs on, read from pcsx2_versions.json (launch-autopilot.ps1 reads it too).

The player runtime accepts every PCSX2 2.x from the minimum on, nightlies and later releases
included. Savestates are routed by their save version, which PCSX2 changes whenever the saved
data changes (SaveState.h), so a build with an unknown format is refused by structure, not by
name. `tested` lists the stable releases verified so far; others only get an untested notice.
Adapter-neutral: BT3 and BT4 share this file unchanged.
"""
import json
import re
import struct
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().with_name('pcsx2_versions.json')
LAYOUTS = ('state128', 'state28')
# 'PCSX2 v2.8.2' (PINE), 'v2.7.361' (savestate tag), '2.8.2.0' (file version), '-nightly'/'-dirty' suffixes.
_VERSION = re.compile(r'\s*(?:PCSX2\s+)?v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})(?!\d)', re.IGNORECASE)


def parse(version):
    """(major, minor, patch) of a PCSX2 version string or savestate tag; None when unreadable."""
    if isinstance(version, (bytes, bytearray)):
        version = bytes(version).decode('ascii', 'replace')
    match = _VERSION.match(version) if isinstance(version, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def text(version):
    return '.'.join(map(str, version))


def _required(value, name):
    parsed = parse(value)
    if parsed is None or text(parsed) != value:
        raise ValueError(f'pcsx2_versions.json: {name} must be a plain version such as 2.6.0')
    return parsed


def load(path=DATA):
    """Read and check a policy file; the cached policy() is the shipped one."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise ValueError('pcsx2_versions.json: unsupported schema')
    minimum = _required(data.get('player_minimum'), 'player_minimum')
    developer = _required(data.get('developer'), 'developer')
    tested = [_required(value, 'tested') for value in data.get('tested', ())]
    if not tested or tested != sorted(set(tested)) or any(v[0] != minimum[0] or v < minimum for v in tested):
        raise ValueError('pcsx2_versions.json: tested must be sorted, unique and accepted for players')
    families = []
    for family in data.get('save_versions', ()):
        start, end = _required(family['tags_from'], 'tags_from'), _required(family['tags_below'], 'tags_below')
        save = int(family['save_version'], 16)
        if family['layout'] not in LAYOUTS or not start < end or save in (f['save_version'] for f in families):
            raise ValueError('pcsx2_versions.json: invalid save_versions entry')
        families.append(dict(family, save_version=save, tags_from=start, tags_below=end))
    if not families:
        raise ValueError('pcsx2_versions.json: save_versions is empty')
    return dict(player_minimum=minimum, developer=developer, tested=tuple(tested), save_versions=tuple(families))


@lru_cache(maxsize=None)
def policy():
    return load()


def player_accepts(version):
    """Any PCSX2 2.x (the minimum's major version) from the minimum on, nightlies included."""
    parsed, minimum = parse(version), policy()['player_minimum']
    return parsed is not None and parsed[0] == minimum[0] and parsed >= minimum


def developer_accepts(version):
    return parse(version) == policy()['developer']


def is_tested(version):
    return parse(version) in policy()['tested']


def tested_text():
    return ', '.join(text(v) for v in policy()['tested'])


def player_requirement():
    minimum = policy()['player_minimum']
    return f'PCSX2 {text(minimum)} or newer ({minimum[0]}.x)'


def _players_text():
    return '; '.join(f"0x{f['save_version']:08X} ({f['releases']})" for f in policy()['save_versions']
                     if not f.get('developer_only'))


def state_family(version_entry):
    """Route a savestate's 36-byte version entry (u32 save version + char[32] git tag).

    Returns the save_versions entry plus the tag and `emulator` (the tag without its 'v').
    Unknown save versions and tags that do not belong to their save version raise ValueError.
    """
    if len(version_entry) != 36:
        raise ValueError('Unexpected savestate version entry size')
    save = struct.unpack_from('<I', version_entry)[0]
    tag = bytes(version_entry[4:]).split(b'\0', 1)[0].decode('ascii', 'replace')
    shown = tag or '(no version tag)'
    family = next((f for f in policy()['save_versions'] if f['save_version'] == save), None)
    if family is None:
        raise ValueError(
            f'This savestate has save version 0x{save:08X} from PCSX2 {shown}: a savestate format the mod '
            f'does not know. PCSX2 changes that number whenever it changes its savestate format, so this '
            f'PCSX2 build cannot prepare modded matches. The mod reads {_players_text()}. '
            f'Use a tested PCSX2 release: {tested_text()}.')
    parsed = parse(tag)
    if parsed is None or not family['tags_from'] <= parsed < family['tags_below']:
        raise ValueError(
            f'Savestate version tag {shown} does not belong to save version 0x{save:08X} '
            f"({family['releases']}); the savestate is inconsistent or from an unofficial build.")
    return dict(family, tag=tag, emulator=tag[1:] if tag[:1] in 'vV' else tag)
