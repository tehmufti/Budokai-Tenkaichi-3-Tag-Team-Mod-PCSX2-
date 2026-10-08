"""Read-only player installation check. No emulator, uploads, or save edits."""
import argparse
import configparser
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent
WINDOWS = os.name == 'nt'
# Linux: the Pythons the bundled wheels-linux set serves (Install.sh and install_player.py use the same list).
LINUX_PYTHONS = ((3,11), (3,12), (3,13), (3,14))
# What linux_prerequisites() reports. install_linux.py shows them in the setup language (installer-es.json keys).
MISSING_OPENGL = ('libOpenGL.so.0, which PCSX2 needs to start (package libopengl0 on Debian/Ubuntu, '
                  'libglvnd-opengl on Fedora, libglvnd on Arch)')
MISSING_FUSERMOUNT = 'a setuid-root fusermount3 (package fuse3), which mounts the PCSX2 AppImage'
MISSING_FUSE_DEVICE = 'the FUSE device /dev/fuse, which the PCSX2 AppImage needs'
MISSING_SDL = ('libSDL2-2.0.so.0 is missing: 3-4 player controller input needs it (package libsdl2-2.0-0 on '
               'Debian/Ubuntu, SDL2 or sdl2-compat on Fedora and Arch); 1-2 players work without it')
LINUX_PREREQUISITES = (MISSING_OPENGL, MISSING_FUSERMOUNT, MISSING_FUSE_DEVICE, MISSING_SDL)
# adapter -> (PINE slot, extra offline check in game/tools, address table in game/tools). The same contract as
# install_player.ADAPTERS (test_install_player checks that they agree); this file is installed on its own.
ADAPTERS = {'bt3-usa': (28011, None, None),
            'bt3-pal': (28011, None, 'pal_native_map.json'),
            'bt3-jpn': (28011, None, 'jpn_native_map.json'),
            'bt4-b14-rev2-eng': (28012, 'bt4_preflight.py', None)}
# setup_messages.py and messages.json are installed beside this file; without them (an older installation) failures
# are printed in plain English.
try:
    import setup_messages
except ImportError:
    setup_messages = None
CODE = re.compile(r'TTM-[A-Z0-9]+-\d\d')
# This checker's own lines in Spanish (its failures come from messages.json).
SPANISH = {
    'PASS: files, dependencies, ISO, hooks and isolated settings checked. No emulator was opened.':
        'CORRECTO: se han comprobado los archivos, las dependencias, la ISO, los parches y los ajustes '
        'independientes. No se ha abierto ningún emulador.',
    'NOT READY: install the missing system packages listed above, then run Check installation.sh again.':
        'NO ESTÁ LISTO: instala los paquetes del sistema indicados arriba y vuelve a ejecutar Check installation.sh.',
    'Report saved to check-installation.log and check-status.json':
        'Informe guardado en check-installation.log y check-status.json',
    'Checking the installation (this can take a minute)...':
        'Comprobando la instalación (puede tardar un minuto)...',
    'The installed PCSX2 version policy does not match release.json. Install a fresh copy.':
        'La política de versiones de PCSX2 instalada no coincide con release.json. Instala una copia nueva.',
    'The recorded PCSX2 version is not supported by this release':
        'Esta versión del mod no admite la versión de PCSX2 registrada',
    'This installation was not made for the Linux PCSX2 AppImage.':
        'Esta instalación no se hizo para el AppImage de PCSX2 para Linux.',
    'The PCSX2 AppImage is not executable (a file system mounted noexec?)':
        'El AppImage de PCSX2 no es ejecutable (¿un sistema de archivos montado con noexec?)',
    'the ISO is no longer at its installed path': 'la ISO ya no está en la ruta instalada',
    'Note: the game disc added in {folder} is damaged; add its ISO again in {settings} > Game disc before you choose it.':
        'Nota: el disco del juego añadido en {folder} está dañado; vuelve a añadir su ISO en {settings} > Disco del juego '
        'antes de elegirlo.',
    # TTM-CHECK-19 {reason}: what is wrong with the chosen game disc (game_profile.DiscError.kind); the English message
    # with the path stays in DETAILS and the path in FILE.
    'one of its extracted files is missing': 'falta uno de sus archivos extraídos',
    'one of its extracted files was changed or is damaged': 'uno de sus archivos extraídos se modificó o está dañado',
    'one of its extracted files cannot be read': 'no se puede leer uno de sus archivos extraídos',
    'its folder is reached through a link, which the mod never follows':
        'se llega a su carpeta a través de un enlace, que el mod nunca sigue',
    'the selection file game/discs/active.json is damaged': 'el archivo de selección game/discs/active.json está dañado',
    'it belongs to another game than this installation': 'pertenece a otro juego distinto al de esta instalación',
    'it was not added completely': 'no se añadió por completo',
}
DISC_REASONS = {'missing': 'one of its extracted files is missing',
                'changed': 'one of its extracted files was changed or is damaged',
                'unreadable': 'one of its extracted files cannot be read',
                'link': 'its folder is reached through a link, which the mod never follows',
                'selection': 'the selection file game/discs/active.json is damaged',
                'family': 'it belongs to another game than this installation',
                'incomplete': 'it was not added completely'}
DISC_KEY = re.compile(r'[0-9a-f]{16}')


def language(root=None):
    """The mod's language (game/mod-settings.json), for the check's own messages."""
    root = ROOT if root is None else root
    try:
        value = json.loads((Path(root)/'game/mod-settings.json').read_text(encoding='utf-8')).get('language')
    except (OSError, ValueError, AttributeError):
        return 'en'
    return value if value in ('en', 'es') else 'en'


def L(text, lang='en'):
    return SPANISH.get(text, text) if lang == 'es' else text


def both(text):
    """A reason in both languages, for a placeholder of a coded failure."""
    return dict(en=text, es=SPANISH.get(text, text))


class CheckFailure(ValueError):
    """A coded failure without setup_messages (plain English)."""
    def __init__(self, code, detail='', **values):
        self.code, self.values, self.detail = code, values, detail
        shown = ', '.join(f'{k}={v["en"] if isinstance(v, dict) else v}' for k, v in values.items() if k != 'file')
        super().__init__(' '.join(part for part in (code, shown, detail) if part))

    def details(self):
        return dict(self.values, **({'detail': self.detail} if self.detail else {}))


def failure(code, detail='', **values):
    if setup_messages is not None: return setup_messages.SetupFailure(code, detail=detail, **values)
    return CheckFailure(code, detail, **values)


def require(ok, message, **details):
    """message: a messages.json code (raises a coded failure with details) or plain text (ValueError)."""
    if not ok:
        if CODE.fullmatch(message): raise failure(message, **details)
        raise ValueError(message)


def file_hash(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(root, name):
    """An installation record; a missing or damaged one is TTM-CHECK-13."""
    try:
        return json.loads((Path(root)/name).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise failure('TTM-CHECK-13', name=name, file=str(Path(root)/name), detail=f'{type(error).__name__}: {error}') from error


def data_folder(root):
    """PCSX2's data folder: game/runtime28 on Windows; the Linux AppImage started with -portable uses
    game/runtime28/PCSX2 (dirname($APPIMAGE)/PCSX2, runtime_profile.DATA)."""
    runtime = Path(root)/'game/runtime28'
    return runtime if WINDOWS else runtime/'PCSX2'


def linux_prerequisites():
    """(missing, warnings) for running the PCSX2 AppImage and 3-4 player input on this Linux system.
    The installer refuses missing items unless told otherwise; this checker only reports them."""
    import ctypes, shutil, stat
    def loads(name):
        try: ctypes.CDLL(name); return True
        except OSError: return False
    missing, warnings = [], []
    if not loads('libOpenGL.so.0'):
        missing.append(MISSING_OPENGL)
    fusermount = [path for path in (shutil.which('fusermount3'), shutil.which('fusermount')) if path]
    if not any(os.stat(path).st_mode & stat.S_ISUID and os.stat(path).st_uid == 0 for path in fusermount):
        missing.append(MISSING_FUSERMOUNT)
    if not os.path.exists('/dev/fuse'):
        missing.append(MISSING_FUSE_DEVICE)
    if not loads('libSDL2-2.0.so.0'):
        warnings.append(MISSING_SDL)
    return missing, warnings


def contract(adapter):
    require(adapter in ADAPTERS, 'TTM-CHECK-18', adapter=adapter)
    return ADAPTERS[adapter]


def check_native_map(root, adapter, profile=None):
    """The European or Japanese address table must still be the one made from the chosen disc's executable and DBZP.BIN
    (profile: that disc's game-profile.json; the installed disc's by default)."""
    name = contract(adapter)[2]
    if name is None: return
    table = json.loads((Path(root)/'game/tools'/name).read_text(encoding='utf-8'))
    profile = json.loads(Path(profile or Path(root)/'game/game-profile.json').read_text(encoding='utf-8'))
    members = profile.get('members', {})
    require(profile.get('adapter') == adapter == table.get('adapter') and
            table.get('elf_sha256') == members.get('/'+str(profile.get('serial'))+';1') and
            table.get('dbzp_sha256') == members.get('/BIN/DBZP.BIN;1'),
            'TTM-CHECK-15', file=str(Path(root)/'game/tools'/name))


def check_config(root, adapter):
    runtime = data_folder(root)
    ini = runtime/'inis/PCSX2.ini'
    require(ini.is_file(), 'TTM-CHECK-05', file=str(ini))
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(ini, encoding='utf-8-sig')
    for section in ('Folders', 'Filenames', 'MemoryCards'):
        require(config.has_section(section), 'TTM-CHECK-07', section=section, file=str(ini))
    for section, key, value in [('EmuCore','EnablePINE','true'),('EmuCore','EnableCheats','true'),
                               ('EmuCore','PINESlot',str(contract(adapter)[0])),
                               ('EmuCore/CPU','ExtraMemory','true')]:
        require(config.get(section,key,fallback='').lower() == value, 'TTM-CHECK-06', section=section, key=key, value=value,
                file=str(ini), detail=f'PCSX2 setting must be {section} / {key} = {value}')
    for key, value in config['Folders'].items():
        require((runtime/value).resolve().is_relative_to(runtime.resolve()), 'TTM-CHECK-08', key=key, file=str(ini),
                detail=f'PCSX2 folder escapes its private profile: {key}')
    cards = runtime/config['Folders'].get('MemoryCards', 'memcards')
    for key, value in config['MemoryCards'].items():
        if key.endswith('_filename'):
            require((cards/value).resolve().is_relative_to(cards.resolve()), 'TTM-CHECK-08', key=key, file=str(ini),
                    detail='Memory card must stay in the private profile: '+key)
    require('BIOS' in config['Filenames'] or 'bios' in config['Filenames'], 'TTM-CHECK-07', section='Filenames', file=str(ini))
    bios = runtime/config['Folders'].get('Bios', 'bios')/config['Filenames']['BIOS']
    require(bios.is_file(), 'TTM-CHECK-09', file=str(bios), detail='The configured PS2 BIOS is missing')


def check_emulator(root, receipt, release):
    """The recorded PCSX2 build must pass the installed runtime's own policy (game/tools/pcsx2_versions.json,
    which must match release.json). The runtime folder itself is hash-locked with the other files."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('installed_pcsx2_versions', root/'game/tools/pcsx2_versions.py')
    versions = importlib.util.module_from_spec(spec); spec.loader.exec_module(versions)
    policy = versions.policy()
    require(versions.text(policy['player_minimum']) == release.get('pcsx2_minimum') and
            [versions.text(v) for v in policy['tested']] == release.get('pcsx2_supported'),
            'TTM-CHECK-14', reason=both('The installed PCSX2 version policy does not match release.json. Install a fresh copy.'))
    recorded = receipt.get('emulator_version')
    prefix = 'The recorded PCSX2 version is not supported by this release'
    require(versions.player_accepts(recorded), 'TTM-CHECK-14',
            reason=dict(en=f'{prefix} (needs {versions.player_requirement()}): {recorded}',
                        es=f'{SPANISH[prefix]} (necesita {versions.player_requirement()}): {recorded}'))
    if not versions.is_tested(recorded):
        print(f'Note: PCSX2 {recorded} is not one of the supported stable releases ({versions.tested_text()}).')
    return recorded


# Runs game_profile.check in the installed runtime for the game disc chosen in Mod settings > Game disc: it names that
# disc on one TTM-DISC-ACTIVE line (and pins itself to it), and reports a failure as one JSON line the checker reads.
ISO_CHECK = ('import json, os, sys, game_profile\n'
             'try:\n'
             '    record = game_profile.resolve() if hasattr(game_profile, "resolve") else None\n'
             '    if record is not None:\n'
             '        os.environ[game_profile.PIN] = record["key"] or ""\n'
             '        print("TTM-DISC-ACTIVE " + json.dumps(dict(key=record["key"], adapter=record["adapter"], installed=record["installed"],\n'
             '              profile=str(record["folder"] / "game-profile.json"))), flush=True)\n'
             '    game_profile.check(refresh={refresh})\n'
             'except Exception as error:\n'
             '    details = {{k: v for k, v in (getattr(error, "details", None) or {{}}).items() if isinstance(v, (str, int, float))}}\n'
             '    missing = getattr(error, "filename", None) if isinstance(error, FileNotFoundError) else None\n'
             '    print("TTM-ISO-RESULT " + json.dumps(dict(code=getattr(error, "code", None), message=str(error) or type(error).__name__,\n'
             '          type=type(error).__name__, details=details, missing=missing, disc=type(error).__name__ == "DiscError",\n'
             '          file=getattr(error, "file", None), kind=getattr(error, "kind", None))), file=sys.stderr)\n'
             '    raise SystemExit(1)\n')
DISC_LINE = 'TTM-DISC-ACTIVE '
# autopilot.py --check names the private Python in English; Play hides this line too (play_launcher).
DEPENDENCIES_LINE = 'Autopilot dependencies ready'


def iso_failure(output, code):
    """TTM-CHECK-10 with the reason the installed runtime gave (in both languages when it carries a TTM-ISO code)."""
    result = {}
    for line in output.splitlines():
        if line.startswith('TTM-ISO-RESULT '):
            try: result = json.loads(line[len('TTM-ISO-RESULT '):])
            except ValueError: result = {}
    message = result.get('message') or f'the ISO check ended with exit code {code}'
    reason = dict(en=message, es=message)
    if result.get('disc'):
        # The chosen game disc's own files or its selection (game_profile.DiscError): Mod settings > Game disc repairs it.
        # The reason is a fixed phrase in the player's language; the English message (with its path) is the detail.
        reason = both(DISC_REASONS.get(result.get('kind'), DISC_REASONS['changed']))
        return failure('TTM-CHECK-19', reason=reason, file=result.get('file') or '', detail=message)
    if result.get('missing'):
        reason = both('the ISO is no longer at its installed path')
        return failure('TTM-CHECK-10', reason=reason, file=str(result['missing']), detail=message)
    inner = result.get('code')
    if setup_messages is not None and isinstance(inner, str) and CODE.fullmatch(inner):
        values = result.get('details') or {}
        reason = {lang: setup_messages.text(inner, 'what', lang, **values) for lang in ('en', 'es')}
        return failure('TTM-CHECK-10', reason=reason, detail=f'{inner}: {message}')
    return failure('TTM-CHECK-10', reason=reason, detail=result.get('type', ''))


def child_environment():
    env = dict(os.environ, BT3_RUNTIME_PROFILE='runtime28', PYTHONNOUSERSITE='1', PYTHONPATH='', PYTHONUTF8='1',
               PYTHONIOENCODING='utf-8')
    # The check resolves the game disc itself (ISO_CHECK) and pins its children: never another session's pin, and
    # never a developer adapter override.
    for name in ('PYTHONHOME', 'TAGTEAM_DISC', 'TAGTEAM_ADAPTER'):
        env.pop(name, None)
    return env


def check(root=ROOT, full_iso=False):
    root = Path(root).resolve()
    lang = language(root)
    if WINDOWS: require(sys.version_info[:2] == (3,11) and struct.calcsize('P') == 8, 'TTM-CHECK-12', version=sys.version.split()[0])
    else: require(sys.version_info[:2] in LINUX_PYTHONS and struct.calcsize('P') == 8, 'TTM-CHECK-12', version=sys.version.split()[0])
    release = read_json(root, 'release.json')
    print('Tag Team Mod '+release['version'], flush=True)
    receipt = read_json(root, 'installed-files.json')
    cards = 'game/runtime28/memcards' if WINDOWS else 'game/runtime28/PCSX2/memcards'
    missing_files, changed = [], []
    for name, digest in receipt['files'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file(): missing_files.append(name)
        elif file_hash(path) != digest: changed.append(name)
    listed = missing_files+changed
    detail = ('Missing or changed installation files: '+', '.join(listed[:15])+'. Install a fresh copy; retain your memory cards '
              'and settings.') if listed else ''
    require(not missing_files, 'TTM-CHECK-02', count=len(missing_files), files=', '.join(missing_files[:5]), cards=cards, detail=detail)
    require(not changed, 'TTM-CHECK-03', count=len(changed), files=', '.join(changed[:5]), cards=cards, detail=detail)
    for name, row in read_json(root, 'dependencies.json')['packages'].items():
        try: found = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: found = 'missing'
        require(found == row['version'], 'TTM-CHECK-04', name=name, expected=row['version'], found=found,
                detail=f'Dependency version changed: {name}')
    require((root/'game/runtime28/portable.ini').is_file(), 'TTM-CHECK-16', file=str(root/'game/runtime28/portable.ini'))
    missing = []
    if not WINDOWS:
        require(receipt.get('emulator_kind') == 'appimage', 'TTM-CHECK-17',
                reason=both('This installation was not made for the Linux PCSX2 AppImage.'))
        appimage = root/'game/runtime28/pcsx2-qt.AppImage'
        require(os.access(appimage, os.X_OK), 'TTM-CHECK-17', file=str(appimage),
                reason=both('The PCSX2 AppImage is not executable (a file system mounted noexec?)'))
        missing, warnings = linux_prerequisites()
        for problem in missing: print('Note: PCSX2 cannot start until this is installed: '+problem)
        # SDL2 (3-4 players) is reported once, by the runtime check below (autopilot.py --check prints
        # "Three/four-player input: ..." with the loader's own answer and the distribution packages).
        for problem in warnings:
            if problem != MISSING_SDL: print('Note: '+problem)
    emulator = check_emulator(root, receipt, release)
    env = child_environment()
    programs = [('autopilot.py', ['--check'])]
    # The game disc first: the disc chosen in Mod settings > Game disc (the installed disc unless another was chosen)
    # decides the adapter, the address table and the runtime checks below, and every child is pinned to it, so a
    # switch made during this check can never pass a mix of two discs. Its ISO identity is checked through the
    # validated compatibility cache.
    run = subprocess.run([sys.executable, '-c', ISO_CHECK.format(refresh=bool(full_iso))], cwd=root/'game/tools', env=env,
                         capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    disc = None
    for line in run.stdout.splitlines():
        if line.startswith(DISC_LINE):
            try: disc = json.loads(line[len(DISC_LINE):])
            except ValueError: disc = None
    print(''.join(line for line in run.stdout.splitlines(True) if not line.startswith(DISC_LINE)), end='')
    print(''.join(line for line in run.stderr.splitlines(True) if not line.startswith('TTM-ISO-RESULT ')), end='')
    if run.returncode != 0: raise iso_failure(run.stderr, run.returncode)
    adapter = disc['adapter'] if isinstance(disc, dict) and disc.get('adapter') else receipt['adapter']
    if isinstance(disc, dict):
        env['TAGTEAM_DISC'] = str(disc.get('key') or '')
    check_config(root, adapter)
    check_native_map(root, adapter, disc.get('profile') if isinstance(disc, dict) else None)
    if contract(adapter)[1]: programs.append((contract(adapter)[1], []))
    for name, arguments in programs:
        run = subprocess.run([sys.executable,str(root/'game/tools'/name),*arguments], cwd=root/'game', env=env,
                             capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
        print(''.join(line for line in run.stdout.splitlines(True) if not line.startswith(DEPENDENCIES_LINE)), end='')
        print(run.stderr, end='')
        require(run.returncode == 0, 'TTM-CHECK-11', script=name, detail='Runtime check failed: '+name)
    for note in library_notes(root, disc.get('key') if isinstance(disc, dict) else None, lang): print(note)
    print(L('PASS: files, dependencies, ISO, hooks and isolated settings checked. No emulator was opened.', lang))
    if missing: print(L('NOT READY: install the missing system packages listed above, then run Check installation.sh again.', lang))
    return dict(ready=not missing, installation_valid=True, missing_runtime_dependencies=missing,
                version=release['version'], adapter=adapter, full_iso=full_iso,
                gameplay_verified=False, emulator_version=emulator, pcsx2_tested=receipt.get('pcsx2_tested'),
                disc=dict(key=disc.get('key'), adapter=disc.get('adapter'), installed=disc.get('installed'))
                if isinstance(disc, dict) else None)


def library_notes(root, active, lang='en'):
    """Note lines for game discs added in Mod settings > Game disc that are not the chosen one and whose files are
    damaged: they are not used until chosen, and adding their ISO again repairs them (never a failure here)."""
    import hashlib as _hashlib, stat as _stat
    discs = Path(root)/'game/discs'
    notes = []
    try:
        children = sorted(discs.iterdir()) if discs.is_dir() else []
    except OSError:
        return notes
    settings = setup_messages.platform_values().get('settings', 'Mod settings') if setup_messages else 'Mod settings'
    for child in children:
        if not DISC_KEY.fullmatch(child.name) or child.name == active:
            continue
        damaged = bool(getattr(os.lstat(child), 'st_file_attributes', 0) & _stat.FILE_ATTRIBUTE_REPARSE_POINT) or child.is_symlink()
        if not damaged:
            try:
                receipt = json.loads((child/'disc-files.json').read_text(encoding='utf-8'))
                for name, digest in receipt['files'].items():
                    path = (child/name)
                    if '..' in Path(name).parts or not path.is_file() or file_hash(path) != digest:
                        damaged = True; break
                damaged = damaged or receipt.get('state') != 'ready'
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                damaged = True
        if damaged:
            notes.append(L('Note: the game disc added in {folder} is damaged; add its ISO again in {settings} > Game disc '
                           'before you choose it.', lang).format(folder=f'game/discs/{child.name}', settings=settings))
    return notes


def coded(error):
    """The coded failure to show for any exception (unexpected ones are TTM-CHECK-90)."""
    code = getattr(error, 'code', None)
    if isinstance(code, str) and CODE.fullmatch(code) and hasattr(error, 'details'): return error
    if setup_messages is not None and isinstance(error, OSError):
        classified = setup_messages.classify(error, unexpected='TTM-CHECK-90')
        if classified.code != 'TTM-CHECK-90': return classified
    if isinstance(error, ValueError):  # a plain message (tests, or a mocked check)
        return failure('TTM-CHECK-90', detail=str(error))
    return failure('TTM-CHECK-90', detail=f'{type(error).__name__}: {error}')


def show(error, lang, log=None):
    """The failure block on stderr (plain English 'CHECK FAILED: ...' without setup_messages)."""
    if setup_messages is not None and hasattr(error, 'render'):
        print(error.render(lang, log=log), file=sys.stderr, flush=True)
    else:
        print('CHECK FAILED: '+str(error), file=sys.stderr, flush=True)


class Tee:
    def __init__(self, stream, log): self.stream, self.log = stream, log
    def write(self, text):
        self.stream.write(text)
        try: self.log.write(text)
        except (OSError, ValueError): pass
        return len(text)
    def flush(self):
        self.stream.flush()
        try: self.log.flush()
        except (OSError, ValueError): pass
    def __getattr__(self, name): return getattr(self.stream, name)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-iso',action='store_true',help='Rehash the entire ISO rather than reuse a validated scan')
    parser.add_argument('--allow-missing-libraries',action='store_true',
                        help='Allow an offline installation check to succeed with missing Linux system libraries; readiness stays false')
    parser.add_argument('--log',type=Path,help='Also write this run (and any traceback) to this file (Check installation.cmd)')
    parser.add_argument('--quiet-failure',action='store_true',
                        help='print no failure block; check-status.json records it (setup draws the block itself)')
    args=parser.parse_args(argv)
    lang = language()
    log = None
    if args.log:
        try: log = args.log.open('w', encoding='utf-8')
        except OSError: log = None
    out, err = sys.stdout, sys.stderr
    if log: sys.stdout, sys.stderr = Tee(out, log), Tee(err, log)
    try:
        if log: print(L('Checking the installation (this can take a minute)...', lang), flush=True)
        try: result=check(full_iso=args.full_iso)
        except Exception as error:
            problem = coded(error)
            if not args.quiet_failure: show(problem, lang, log=args.log if log else None)
            expected = problem is error and not str(getattr(problem, 'code', '')).endswith('-90')
            if not expected:
                # Unexpected: the traceback goes to the log (Check installation.cmd), else to stderr.
                if log: log.write(traceback.format_exc())
                else: traceback.print_exc()
            result=dict(ready=False,error=str(error),error_code=problem.code,error_details=problem.details())
        (ROOT/'check-status.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        if log: print(L('Report saved to check-installation.log and check-status.json', lang))
    finally:
        sys.stdout, sys.stderr = out, err
        if log: log.close()
    offline_ok = (not WINDOWS and args.allow_missing_libraries and result.get('installation_valid')
                  and result.get('missing_runtime_dependencies'))
    return 0 if result['ready'] or offline_ok else 1


if __name__ == '__main__': raise SystemExit(main())
