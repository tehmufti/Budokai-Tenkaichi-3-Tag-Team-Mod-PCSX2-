"""Where this PC's game ISO and PS2 BIOS are: the command line, a Tag Team Mod installation (read only), the kit's
saved settings, or one question each (then saved in data/kit-settings.json).

A Tag Team Mod installation (--install PATH or Start > Tag Team Mod folder, the folder with Play.cmd) is only READ:
  game/player-install.json     confirms a player installation for BT3 USA (adapter bt3-usa): 0.1.0-beta.35 to
                               beta.42 are known builds (kit 2.0); a later 0.1.0-beta.N is a candidate. The version
                               string is
                               not decisive: the match conversion compares the installed game code with
                               data/guest-fingerprint.json and refuses another code (TTM-NET-24), and the kit then
                               marks that installation unusable (data/kit-settings.json 'install_refused').
  game/discs/active.json       the disc chosen in Mod settings > Game disc (else the installed one)
  game-profile.json            that disc's ISO path and the whole ISO's SHA-256; iso-location.json when the ISO was
                               moved (the same rule as the mod's game_profile.iso_path)
  game/runtime28/inis/PCSX2.ini  [Folders] Bios + [Filenames] BIOS: the BIOS the mod's PCSX2 uses
  .venv/Scripts/python.exe     its private Python (Play online.cmd prefers it when --install is given)
Nothing is written there; the BIOS is copied into the kit's own pcsx2/bios folder.
"""
import json
import re
import time
from pathlib import Path

import kit_paths
from kit_codes import KitError

VERSION = '0.1.0-beta.35'                      # the build the kit's data were recorded from
KNOWN_BUILDS = tuple(f'0.1.0-beta.{n}' for n in range(35, 43))      # kit 2.0: beta.35 .. beta.42
# The public series restarted at Version 7. Candidates still have to pass the
# guest-code fingerprint checks; a version number never certifies their code.
FIRST_CANDIDATE = 7
BUILD = re.compile(r'0\.1\.0-beta\.(\d+)(?:\.(\d+))?')
KEY = re.compile('[0-9a-f]{16}')


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return None


def _ini(path):
    values, section = {}, None
    try:
        text = Path(path).read_text(encoding='utf-8-sig', errors='replace')
    except OSError:
        return values
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1]
        elif '=' in s and section:
            k, v = s.split('=', 1)
            values[f'{section}/{k.strip()}'] = v.strip()
    return values


def installation_root(path):
    """The installation folder (the one with Play.cmd and game/) for PATH = that folder or its game folder."""
    p = Path(path).expanduser()
    for candidate in (p, p.parent):
        if (candidate / 'game' / 'player-install.json').is_file():
            return candidate.resolve()
    raise KitError('TTM-NET-24', what=f'{p} is not a Tag Team Mod installation (no game\\player-install.json there).')


def disc_profile(game):
    """(profile, folder) of the disc the installation plays: discs/active.json's disc, else the installed one."""
    folder = game
    active = _json(game / 'discs' / 'active.json')
    key = active.get('key') if isinstance(active, dict) and active.get('schema') == 1 else None
    if isinstance(key, str) and KEY.fullmatch(key) and (game / 'discs' / key / 'game-profile.json').is_file():
        folder = game / 'discs' / key
    profile = _json(folder / 'game-profile.json')
    if not isinstance(profile, dict):
        raise KitError('TTM-NET-24', what=f'{folder / "game-profile.json"} is missing or damaged.')
    return profile, folder


def iso_of(profile, folder):
    """The mod's game_profile.iso_path rule: iso-location.json when it names the same ISO (same SHA-256) and the file
    exists, else the profile's own path."""
    path = profile.get('iso')
    expected = str(profile.get('iso_sha256') or '').lower()
    location = _json(folder / 'iso-location.json')
    if (expected and isinstance(location, dict) and isinstance(location.get('path'), str)
            and str(location.get('sha256', '')).lower() == expected and Path(location['path']).is_file()):
        path = location['path']
    return path


def read_installation(path):
    """dict(root, version, adapter, iso, iso_sha256, bios, python) of a beta.35 BT3 USA installation (read only)."""
    root = installation_root(path)
    game = root / 'game'
    marker = _json(game / 'player-install.json')
    if not isinstance(marker, dict):
        raise KitError('TTM-NET-24', what=f'{game / "player-install.json"} cannot be read.',
                       what_es=f'No se puede leer {game / "player-install.json"}.')
    if marker.get('adapter') not in __import__('kit_adapter').SUPPORTED:
        raise KitError('TTM-NET-24', what=f'{root} is for {marker.get("adapter")}; no reviewed online adapter is installed.',
                       what_es=f'{root} es para {marker.get("adapter")}; no hay un adaptador revisado en línea.')
    build = build_status(marker.get('version'))
    if build == 'refused':
        raise KitError('TTM-NET-24', what=f'{root} is Tag Team Mod {marker.get("version")}; making online matches '
                                          'needs Version 7 or later, or a reviewed legacy build.',
                       what_es=f'{root} es Tag Team Mod {marker.get("version")}; crear combates en línea necesita '
                               'la versión 7 o posterior, o una versión anterior revisada.')
    profile, folder = disc_profile(game)
    if profile.get('adapter') not in __import__('kit_adapter').SUPPORTED:
        raise KitError('TTM-NET-24', what=f'The game disc chosen in that installation is {profile.get("adapter")}, '
                                          'not a reviewed online adapter.',
                       what_es=f'El disco elegido en esa instalación es {profile.get("adapter")}, no un adaptador revisado en línea.')
    ini = _ini(game / 'runtime28' / 'inis' / 'PCSX2.ini')
    bios = None
    name = ini.get('Filenames/BIOS')
    if name:
        bios_dir = Path(ini.get('Folders/Bios') or 'bios')
        if not bios_dir.is_absolute():
            bios_dir = game / 'runtime28' / bios_dir
        bios = bios_dir / name
    python = root / '.venv' / 'Scripts' / 'python.exe'
    refused = (load_settings().get('install_refused') or {}).get(str(root))
    return dict(root=str(root), version=marker.get('version'), adapter=profile.get('adapter'), build=build,
                refused=refused.get('reason') if isinstance(refused, dict) else None,
                refused_regions=refused.get('regions') if isinstance(refused, dict) else None,
                iso=iso_of(profile, folder), iso_sha256=str(profile.get('iso_sha256') or '').lower() or None,
                bios=str(bios) if bios else None, python=str(python) if python.is_file() else None,
                game=str(game))


def build_status(version):
    """Reviewed legacy build, Version 7+ candidate (code checks decide), or refused."""
    if version in KNOWN_BUILDS:
        return 'known'
    m = BUILD.fullmatch(str(version or ''))
    return 'candidate' if m and int(m[1]) >= FIRST_CANDIDATE else 'refused'


def mark_unusable(root, reason, regions=None):
    """Remember that this installation's game code was refused (TTM-NET-24); choosing it again clears the mark.
    regions: the guest-code regions that differ ('feedback_draw, ...'), shown in either language."""
    current = load_settings().get('install_refused') or {}
    current[str(Path(root))] = dict(reason=str(reason)[:400], regions=regions,
                                    at=time.strftime('%Y-%m-%d %H:%M:%S'))
    save_settings(install_refused=current)


def clear_unusable(root):
    current = load_settings().get('install_refused') or {}
    if current.pop(str(Path(root)), None) is not None:
        save_settings(install_refused=current)


def _short(text, folder, lang='en'):
    """A refusal reason without the installation's own path (the Start screen shows it on the same row)."""
    out = str(text)
    for p in {str(folder), str(Path(folder).resolve())}:
        out = out.replace(p, '').strip()
    if lang == 'en' and out.startswith('is '):
        out = 'It ' + out                            # '... is for bt4-...' -> 'It is for bt4-...'
    return out[:1].upper() + out[1:]                 # ES: '... es para ...' -> 'Es para ...'


def scan(roots=None, depth=3, limit=40):
    """[dict(root, version, build, adapter, ok, why)] of the Tag Team Mod installations found under the Desktop,
    Documents and Program Files (a few folder levels deep; only game/player-install.json files are read)."""
    import os
    home = Path.home()
    roots = roots or [home / 'Desktop', home / 'Documents', home / 'OneDrive' / 'Desktop',
                      Path(os.environ.get('ProgramFiles', 'C:/Program Files')),
                      Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)'))]
    found, seen = [], set()
    for top in roots:
        if not top.is_dir():
            continue
        stack = [(top, 0)]
        while stack and len(found) < limit:
            folder, level = stack.pop()
            marker = folder / 'game' / 'player-install.json'
            if marker.is_file():
                key = str(folder.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                row = dict(root=str(folder), version=None, build='refused', adapter=None, ok=False, why=None)
                try:
                    info = read_installation(folder)
                    row.update(version=info['version'], build=info['build'], adapter=info['adapter'],
                               ok=not info.get('refused'), why=info.get('refused'))
                except KitError as error:
                    m = _json(marker) or {}
                    what = error.values.get('what') or error.code
                    row.update(version=m.get('version'), adapter=m.get('adapter'), why=_short(what, folder),
                               why_es=_short(error.values.get('what_es') or what, folder, 'es'))
                found.append(row)
                continue
            if level >= depth:
                continue
            try:
                children = [p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(('.', '$'))]
            except OSError:
                continue
            stack += [(p, level + 1) for p in children]
    order = {'known': 0, 'candidate': 1, 'refused': 2}
    found.sort(key=lambda r: (not r['ok'], order.get(r['build'], 3), r['root'].lower()))
    return found


# ---- the kit's saved settings ---------------------------------------------------------------------------------------------
def load_settings():
    value = _json(kit_paths.SETTINGS)
    return value if isinstance(value, dict) else {}


def save_settings(**values):
    current = load_settings()
    current.update({k: v for k, v in values.items() if v is not None})
    kit_paths.DATA.mkdir(parents=True, exist_ok=True)
    tmp = kit_paths.SETTINGS.with_suffix('.tmp')
    tmp.write_text(json.dumps(current, indent=1), encoding='utf-8')
    tmp.replace(kit_paths.SETTINGS)
    return current


def remember_python(path):
    """Play online.cmd starts the kit with the Python named in data/python-path.txt next time."""
    if not path:
        return
    try:
        kit_paths.DATA.mkdir(parents=True, exist_ok=True)
        kit_paths.PYTHON_TXT.write_text(str(path) + '\n', encoding='utf-8')
    except OSError:
        pass


def ask_path(question, check, interactive=True):
    """Ask once on the console (a dragged-in file arrives with quotes); None when there is no console."""
    if not interactive:
        return None
    while True:
        try:
            answer = input(question).strip().strip('"').strip()
        except EOFError:
            return None
        if not answer:
            return None
        try:
            return check(answer)
        except KitError as error:
            print(error)


def resolve(args, say, interactive):
    """(iso, bios, install, iso_sha256) for this run; KitError 20/21/24 when one cannot be found."""
    settings = load_settings()
    install = None
    if args.install:
        install = read_installation(args.install)
        say(f'Tag Team Mod installation: {install["root"]} ({install["version"]}, read only)')
    elif settings.get('install') and not (args.iso and args.bios):
        try:
            install = read_installation(settings['install'])
        except KitError:
            install = None
    iso = args.iso or (install or {}).get('iso') or settings.get('iso')
    bios = args.bios or (install or {}).get('bios') or settings.get('bios')
    named = 'named by the Tag Team Mod installation'
    iso_from = 'given with --iso' if args.iso else named if install and install.get('iso') else 'saved in this kit'
    bios_from = 'given with --bios' if args.bios else named if install and install.get('bios') else 'saved in this kit'
    if not iso or not Path(iso).is_file():
        missing = f'There is no game ISO at {iso} ({iso_from}).' if iso else 'No game ISO was given yet.'
        if iso:
            say(missing)
        iso = ask_path('Drag your Dragon Ball Z Budokai Tenkaichi 3 (USA) ISO into this window and press Enter: ',
                       lambda a: a if Path(a).is_file() else _missing('TTM-NET-20', 'ISO', a), interactive)
        if not iso:
            raise KitError('TTM-NET-20', what=missing)
    if not bios or not Path(bios).is_file():
        missing = f'There is no BIOS file at {bios} ({bios_from}).' if bios else 'No BIOS file was given yet.'
        if bios:
            say(missing)
        bios = ask_path('Drag your PlayStation 2 BIOS file (.bin) into this window and press Enter: ',
                        lambda a: a if Path(a).is_file() else _missing('TTM-NET-21', 'BIOS file', a), interactive)
        if not bios:
            raise KitError('TTM-NET-21', what=missing)
    iso, bios = str(Path(iso).resolve()), str(Path(bios).resolve())
    iso_sha = install.get('iso_sha256') if install and Path(install['iso']).resolve() == Path(iso) else None
    save_settings(iso=iso, bios=bios, install=install['root'] if install else None)
    if install and install.get('python'):
        remember_python(install['python'])
    return iso, bios, install, iso_sha


def _missing(code, what, path):
    raise KitError(code, what=f'There is no {what} at {path}.')

def installation_pnach():
    """Kit 2.1 (the online part of an installation): the SHA-256 of the installation's own runtime patch for its reviewed disc
    (game/runtime28/.../cheats/SLUS-21678_428113C2_BT3Loading.pnach, written by its installer), copied into the kit's
    runtime pnach folder (match/runtime/pnach/<sha256>.pnach) when it is not there yet; None outside an installation."""
    import hashlib
    import shutil
    if not kit_paths.INTEGRATED:
        return None
    runtime = kit_paths.INSTALL_ROOT / 'game' / 'runtime28'
    for path in sorted(runtime.rglob(__import__('kit_adapter').state_name(0).split(' (')[0] + '_' + __import__('native_map').CRC + '_BT3Loading.pnach')):
        if path.parent.name.lower() != 'cheats':
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        target = kit_paths.RUNTIME / 'pnach' / f'{sha}.pnach'
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        return sha
    return None
