"""Tag Team Mod setup for Linux x86-64: the counterpart of install-player.ps1.

Install.sh runs this with a system Python 3.11-3.14 (standard library only). It checks the installer files,
asks for the language, the parent folder, the ISO and the official PCSX2 AppImage (Tk dialogs, or
--destination --iso --pcsx2 [--bios] [--language] for a headless install). The BIOS is the one that PCSX2 is set up
with; setup asks for one only when PCSX2's settings give none it can use (headless: a coded failure; --bios chooses
one). It checks every selected file and the system in one list before it changes anything. It then creates a private
Python environment from the bundled Linux wheels (offline, hash-checked) and hands over to install_player.py. No
emulator is started: the AppImage's own runtime only reports its size and unpacks its version file. An unfinished
earlier attempt in the chosen folder is renamed aside and an existing installation is kept: the new one goes beside it.
Setup never deletes a folder.
"""
import argparse
import contextlib
import datetime
import errno
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import traceback
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # Install.sh runs Python with -I, which leaves this folder off sys.path
import check_installation as checker  # noqa: E402  (standard library only)
import install_player as installer  # noqa: E402  (standard library only at import time)
import setup_messages as messages  # noqa: E402  (standard library only)

TRANSLATIONS = {}
LANGUAGE = ['en']
# Before the language is chosen, failure blocks are shown in English, then Spanish.
CHOSEN = [False]
PYTHON_HINTS = ('Debian/Ubuntu: sudo apt install python3-venv python3-tk; Fedora: sudo dnf install python3-tkinter; '
                'Arch: sudo pacman -S tk; openSUSE: sudo zypper install python3-tk. See README.md for other systems.')
# Free space the installation and match preparation need (the ISO stays where it is).
NEEDED_SPACE = 3584 << 20


class SetupError(ValueError):
    """A translatable message plus an untranslated detail (a path or a version)."""
    def __init__(self, message, detail=''):
        super().__init__(message + detail)
        self.message, self.detail = message, detail


class Cancelled(SetupError):
    """The player closed a dialog: nothing to report, nothing was changed."""


def L(text):
    return TRANSLATIONS.get(text, text) if LANGUAGE[0] == 'es' else text


def fail(message, detail=''):
    raise SetupError(message, detail)


def stop(code, **values):
    """A coded failure (messages.json)."""
    raise messages.SetupFailure(code, **values)


class Tee:
    """Everything printed also goes to the setup log (the Windows installer keeps a transcript)."""
    def __init__(self, stream, log):
        self.stream, self.log = stream, log
    def write(self, text):
        self.stream.write(text); self.log.write(text); return len(text)
    def flush(self):
        self.stream.flush(); self.log.flush()
    def __getattr__(self, name):
        return getattr(self.stream, name)


def run(command, **options):
    """Run a child process, streaming its combined output into the console and the log."""
    child = subprocess.Popen([str(c) for c in command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL, **options)
    for line in child.stdout: print(line, end='', flush=True)
    return child.wait()


def check_installer_files(setup=HERE):
    """installer-files.json (schema 2, rooted at the release folder): every listed file exists and matches."""
    manifest_path = setup/'installer-files.json'
    if not manifest_path.is_file(): stop('TTM-ZIP-02', detail='The installer is incomplete: setup/installer-files.json is missing')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    root = (setup.parent if manifest.get('schema') == 2 else setup).resolve()
    for name, digest in manifest['files'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            stop('TTM-ZIP-03', name=name, detail='Installer file is missing or unsafe: '+name)
        if installer.file_hash(path) != digest:
            stop('TTM-ZIP-04', name=name, file=str(path), detail='Installer checksum failed: '+name)
    return manifest


def check_platform():
    if not sys.platform.startswith('linux'):
        stop('TTM-OS-01', needed='Linux x86-64', found=sys.platform, detail='This installer is for Linux. On Windows, open Install.cmd.')
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        stop('TTM-OS-01', needed='Linux x86-64', found=platform.machine(), detail='This installer requires a 64-bit x86-64 Linux system')
    if sys.version_info[:2] not in installer.LINUX_PYTHONS or struct.calcsize('P') != 8:
        stop('TTM-PY-22', version=sys.version.split()[0], detail='Run Install.sh with a 64-bit Python 3.11, 3.12, 3.13 or 3.14.')


def open_tk():
    """The Tk root for the dialogs, hidden; a clear message when Tk or a display is missing."""
    try:
        import tkinter
        root = tkinter.Tk()
    except ImportError: stop('TTM-PY-21', detail=PYTHON_HINTS)
    except Exception as error: stop('TTM-OS-05', detail=str(error))
    root.withdraw()
    return root


def choose_language(tk_root):
    import tkinter
    window = tkinter.Toplevel(tk_root); window.title('Tag Team Mod - Language / Idioma'); window.resizable(False, False)
    choice = []
    tkinter.Label(window, text='Language / Idioma', padx=24, pady=14).pack()
    row = tkinter.Frame(window, padx=24, pady=14); row.pack()
    for text, code in (('English', 'en'), ('Español', 'es')):
        tkinter.Button(row, text=text, width=12, command=lambda c=code: (choice.append(c), window.destroy())).pack(side='left', padx=6)
    window.protocol('WM_DELETE_WINDOW', window.destroy)
    window.wait_window()
    if not choice: raise Cancelled('Setup cancelled / Instalacion cancelada.')
    return choice[0]


def pick_directory(tk_root, title):
    from tkinter import filedialog
    chosen = filedialog.askdirectory(parent=tk_root, title=L(title), initialdir=str(Path.home()), mustexist=True)
    if not chosen: raise Cancelled('Setup cancelled.')
    return Path(chosen)


def pick_file(tk_root, title, filetypes, initialdir=None):
    from tkinter import filedialog
    chosen = filedialog.askopenfilename(parent=tk_root, title=L(title), initialdir=str(initialdir or Path.home()), filetypes=filetypes)
    if not chosen: raise Cancelled('Setup cancelled; existing games are unchanged.')
    return Path(chosen)


def resolve_destination(path, allow_existing=False):
    """Install into the resolved parent folder: a symlinked /home (Fedora Atomic) or /run/media (Steam Deck) is fine;
    the installer only refuses symlinks inside the folders it creates."""
    path = Path(path).expanduser().absolute()
    parent = path.parent
    if not parent.is_dir(): stop('TTM-DEST-03', file=str(parent))
    destination = parent.resolve()/path.name
    if os.path.lexists(destination) and not allow_existing: stop('TTM-DEST-06', file=str(destination))
    try: installer.desktop_string(destination)
    except ValueError: stop('TTM-DEST-10', file=repr(str(destination)))
    return destination


def check_file_system(folder):
    """The installation folder must allow running programs (PCSX2 and the Python environment live there)."""
    if os.statvfs(folder).f_flag & os.ST_NOEXEC:
        stop('TTM-DEST-08', file=str(folder))


def check_symlinks(folder):
    """The private Python environment is made of symbolic links: FAT, exFAT and similar file systems cannot hold it.
    A folder setup may not write to (EACCES) or a read-only file system (EROFS) is TTM-DEST-01, not a file system
    without links (EPERM or ENOTSUP from FAT/exFAT: TTM-DEST-09)."""
    probe = Path(folder)/('.symlink-probe-'+uuid.uuid4().hex)
    try:
        os.symlink('install-bootstrap.json', probe)
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EROFS): stop('TTM-DEST-01', file=str(folder), detail=f'{type(error).__name__}: {error}')
        stop('TTM-DEST-09', file=str(folder), detail=f'{type(error).__name__}: {error}')
    finally:
        with contextlib.suppress(OSError): probe.unlink()


def parse(argv=None):
    # No abbreviations: Install.sh decides whether Tk is needed from the full option names.
    parser = argparse.ArgumentParser(prog='Install.sh', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument('--language', choices=('en', 'es'), help='setup and mod language (default: asked, or en with --destination)')
    parser.add_argument('--destination', type=Path, help='the installation folder (new, or an unfinished earlier attempt, which is '
                                                         'renamed aside); its parent must exist')
    parser.add_argument('--iso', type=Path, help='your uncompressed BT3 USA / Europe / Japan or BT4 B14 REV2 English / Spanish .iso')
    parser.add_argument('--pcsx2', type=Path, help='the official PCSX2 2.6.0 or newer AppImage (pcsx2-vX.Y.Z-linux-appimage-x64-Qt.AppImage)')
    parser.add_argument('--bios', type=Path, help='your PS2 BIOS ROM (default: the BIOS your PCSX2 is set up with)')
    parser.add_argument('--allow-missing-libraries', action='store_true',
                        help='install even though libOpenGL.so.0 or FUSE, which PCSX2 needs to start, are missing now')
    return parser.parse_args(argv)


def show_bios_notes(tk_root, found, notes):
    """Install.sh started from a file manager has no terminal: what the PCSX2 settings said (a configured BIOS setup
    cannot use, several BIOS files and none selected) is also shown in a window, before the BIOS dialog or before the
    only PS2 BIOS of that folder is used. Nothing for a PCSX2 without a BIOS set up: the dialog title says it."""
    if tk_root is None or not (found['rejected'] or len(found['choices']) > 1): return
    with contextlib.suppress(Exception):
        from tkinter import messagebox
        messagebox.showinfo('Tag Team Mod', '\n'.join(notes), parent=tk_root)


def mark(kind, text):
    """One line of the preflight checklist."""
    label = messages.labels(LANGUAGE[0] if CHOSEN[0] else 'en')[kind]
    print(f'  [{label}] {text}', flush=True)


def preflight(destination, iso, bios, pcsx2, release, allow_missing, found=None, bios_failure=None):
    """Check every selected file and the system before anything is changed. Prints one checklist, returns
    (failures, version, source); failures are coded (messages.SetupFailure). found: what installer.configured_bios
    found for a BIOS that was not selected; bios_failure: the coded failure when it found none (bios is then None)."""
    lang = LANGUAGE[0]
    failures = []
    def failed(code, **values):
        failure = messages.SetupFailure(code, **values); failures.append(failure)
        mark('fail', f'{code} {messages.text(code, "what", lang, **failure.values)}')
    print(L('Checking your files before changing anything:'), flush=True)
    parent = destination.parent
    try:
        # Write access first: the link probe below writes, and a refused write is not a file system without links.
        if not os.access(parent, os.W_OK): stop('TTM-DEST-01', file=str(parent))
        check_file_system(parent); check_symlinks(parent)
        mark('ok', L('Installation folder:')+' '+str(destination))
    except messages.SetupFailure as failure:
        failures.append(failure); mark('fail', f'{failure.code} {messages.text(failure.code, "what", lang, **failure.values)}')
    try: free = shutil.disk_usage(parent).free
    except OSError: free = None
    if free is not None and free < NEEDED_SPACE:
        failed('TTM-DEST-05', file=str(parent), free=installer.size_text(free), needed=installer.size_text(NEEDED_SPACE))
    elif free is not None: mark('ok', L('Free space:')+f' {installer.size_text(free)}')
    problem = installer.iso_problem(iso)
    if problem: failed(problem[0], file=str(iso), **problem[1])
    else: mark('ok', 'ISO: '+str(iso))
    # TTM-BIOS-07/08 describe the settings of the selected PCSX2: when setup refuses that PCSX2 too, its failure is the
    # main one (the player replaces it and runs setup again anyway), so they are added after the PCSX2 check.
    settings_failure = None
    if bios_failure is not None:
        if bios_failure.code in ('TTM-BIOS-07', 'TTM-BIOS-08'): settings_failure = bios_failure
        else: failures.append(bios_failure)
        mark('fail', f'{bios_failure.code} {messages.text(bios_failure.code, "what", lang, **bios_failure.values)}')
    elif iso.resolve() == bios.resolve(): failed('TTM-BIOS-05', file=str(bios))
    else:
        problem = installer.bios_problem(bios)
        if problem: failed(problem[0], file=str(bios), **problem[1])
        else: mark('ok', 'BIOS: '+str(bios)+installer.bios_origin(found, L))
    version = source = None
    try: version, source = installer.appimage_version(pcsx2)
    except ValueError as error:
        # A renamed AppImage that cannot run from the temporary folder (noexec /tmp) is read again from its copy
        # in the installation, where install_player.py makes the final decision.
        if str(error) != installer.UNKNOWN_VERSION:
            failure = installer.failure_for(error); failure.file = str(pcsx2); failures.append(failure)
            mark('fail', f'{failure.code} {messages.text(failure.code, "what", lang, **failure.values)}')
        else: print(L('The PCSX2 version is read again after the AppImage is copied into the installation.'), flush=True)
    if version:
        accepted, tested = installer.pcsx2_support(version, release)
        if not accepted:
            failure = installer.pcsx2_refusal(version, release, 'Linux x86-64 (AppImage)'); failure.file = str(pcsx2); failures.append(failure)
            mark('fail', f'{failure.code} {messages.text(failure.code, "what", lang, **failure.values)}')
        else:
            mark('ok', 'PCSX2 '+version+' ('+source+')')
            if not tested:
                print(L('This PCSX2 version is not one of the supported stable releases; setup continues. Supported stable releases:')+' '+
                      ', '.join(release['pcsx2_supported'])+' (PCSX2 '+version+')', flush=True)
    if settings_failure is not None: failures.append(settings_failure)
    missing, warnings = checker.linux_prerequisites()
    for problem in missing: print(L('PCSX2 cannot start until this is installed:')+' '+L(problem), flush=True)
    for problem in warnings: print(L('Note:')+' '+L(problem), flush=True)
    if missing and not allow_missing: failed('TTM-OS-06', detail='--allow-missing-libraries')
    return failures, version, source


def backend_failure(destination, code):
    """The coded failure install_player.py recorded in install-status.json (TTM-PAYLOAD-91 when it recorded none)."""
    try: status = json.loads((destination/'install-status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): status = {}
    error_code = status.get('error_code')
    if isinstance(error_code, str) and messages.CODE.fullmatch(error_code):
        failure = messages.SetupFailure.from_details(error_code, status.get('error_details'))
        failure.unchanged = False
        return failure
    return messages.SetupFailure('TTM-PAYLOAD-91', exit=code, unchanged=False)


def offer_import(tk_root, private, old, new, env):
    """Offer to copy the memory cards (and the mod settings of the same game) of the installation the new one went
    beside. Optional: a failure is one warning line, never a setup failure."""
    try:
        from tkinter import messagebox
        question = ('Copy your memory cards and mod settings from the existing installation?' if installer.same_game(old, new) else
                    'Copy your memory cards from the existing installation? (Its mod settings are for the other game and are not copied.)')
        if not messagebox.askyesno('Tag Team Mod', L(question)+'\n\n'+str(old), parent=tk_root): return False
        if run([private, HERE/'install_player.py', '--destination', new, '--import-from', old, '--language', LANGUAGE[0],
                '--quiet-failure'], env=env) == 0:
            return True
    except Exception as error:  # noqa: BLE001 (optional step)
        print(f'{type(error).__name__}: {error}', file=sys.stderr, flush=True)
    mark('warn', messages.line('TTM-DEST-27', LANGUAGE[0]))
    return False


def hand_to_launcher(block):
    """Install.sh started without a terminal (from a file manager) names a file in TAGTEAM_SETUP_ERROR_FILE: the block
    goes there when no setup window could show it, and Install.sh shows it with zenity, kdialog or xmessage."""
    target = os.environ.get('TAGTEAM_SETUP_ERROR_FILE')
    if target:
        with contextlib.suppress(OSError): Path(target).write_text(block+'\n', encoding='utf-8')


def setup(args, log_path):
    """The installation itself; returns the destination. Raises SetupError/ValueError on refusal."""
    state = dict(stage='Checking installer files', destination=None, owned=False, tk=None)
    CHOSEN[0] = False  # blocks show English, then Spanish, until the language is chosen
    try:
        # Headless: no dialog opens (the BIOS comes from --bios or from PCSX2's settings, else a coded failure).
        headless = all((args.destination, args.iso, args.pcsx2))
        # The dialogs first: a damaged or incomplete installer below is then also shown in a window (Install.sh started
        # from a file manager has no terminal).
        if not headless: state['tk'] = open_tk()
        check_installer_files()
        release = json.loads((HERE/'release.json').read_text(encoding='utf-8'))
        print('Tag Team Mod '+release['version']+' - BT3 and BT4 player setup for Linux', flush=True)
        check_platform()
        LANGUAGE[0] = args.language or ('en' if args.destination else choose_language(state['tk']))
        TRANSLATIONS.update(json.loads((HERE/'installer-es.json').read_text(encoding='utf-8')))
        CHOSEN[0] = True
        state['stage'] = 'Choosing installation inputs'
        if args.destination: chosen, explicit = Path(args.destination), True
        else:
            picked = pick_directory(state['tk'], 'Choose the parent folder for a new Tag Team Mod installation')
            # The chosen folder is the parent, unless it is itself a complete installation (then the new one goes beside it).
            chosen, explicit = (picked if installer.folder_state(picked) == 'complete' else picked/'Tag Team Mod'), False
        destination = resolve_destination(chosen, allow_existing=True)
        destination, aside, beside = installer.plan_destination(destination, explicit, release['version'])
        iso = args.iso or pick_file(state['tk'], 'Choose BT3 USA / Europe / Japan or BT4 B14 REV2 English / Spanish (see README for supported discs)',
                                    [('Disc images', '*.iso *.ISO *.img *.bin *.chd *.cso *.zso *.7z *.zip *.rar *.gz'), ('All files', '*')])
        pcsx2 = args.pcsx2 or pick_file(state['tk'], 'Choose the PCSX2 2.6.0 or newer AppImage for Linux - download link is in README.md',
                                        [('PCSX2 AppImage', '*.AppImage *.appimage'), ('All files', '*')])
        for path in (iso, pcsx2):
            if not Path(path).is_file(): fail('Missing input:', ' '+str(path))
        # Without --bios: the BIOS this PCSX2 is set up with; setup asks only when its settings give none it can use.
        bios, found, bios_failure = args.bios, None, None
        if not bios:
            found = installer.find_configured_bios(Path(pcsx2), windows=False)
            notes = installer.bios_notes(found, LANGUAGE[0])
            if found['bios']:
                # A configured file setup could not use is named before the only PS2 BIOS of its folder is taken.
                for line in notes: print(line, flush=True)
                show_bios_notes(state['tk'], found, notes)
                bios = Path(found['bios'])
            elif headless: bios_failure = installer.configured_bios_failure(found)
            else:
                for line in notes: print(line, flush=True)
                show_bios_notes(state['tk'], found, notes)
                bios = pick_file(state['tk'], 'Choose your PlayStation 2 BIOS ROM',
                                 [('BIOS files', '*.bin *.BIN *.rom *.ROM *.rom0 *.ROM0 *.zip *.7z'), ('All files', '*')],
                                 initialdir=found['folder'])
                found = None
        if bios and not Path(bios).is_file(): fail('Missing input:', ' '+str(bios))
        iso, bios = Path(iso).absolute(), (Path(bios).absolute() if bios else None)
        pcsx2 = Path(pcsx2).resolve()  # the real file: its own name is the version fallback
        state['stage'] = 'Checking the system'
        failures, version, source = preflight(destination, iso, bios, pcsx2, release, args.allow_missing_libraries, found=found,
                                              bios_failure=bios_failure)
        for failure in failures[1:]: print(failure.render(LANGUAGE[0]), file=sys.stderr, flush=True)
        if failures: raise failures[0]
        # Nothing was changed until here.
        if aside is not None:
            renamed = installer.aside_name(aside); os.rename(aside, renamed)
            print(messages.line('TTM-DEST-25', LANGUAGE[0], name=renamed.name), flush=True)
        if beside is not None: print(messages.line('TTM-DEST-26', LANGUAGE[0], name=destination.name), flush=True)
        destination.mkdir(); state['destination'] = destination; state['owned'] = True
        (destination/'install-bootstrap.json').write_text(json.dumps(dict(
            schema=1, version=release['version'], created=datetime.datetime.now(datetime.timezone.utc).isoformat()), indent=2)+'\n', encoding='utf-8')
        state['stage'] = '[1/6] Checking Python and system libraries'
        print(L(state['stage']), flush=True)
        print('Python '+sys.version.split()[0]+' ('+sys.executable+')', flush=True)
        state['stage'] = '[2/6] Creating private Python environment and installing verified bundled dependencies'
        print(L(state['stage']), flush=True)
        env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONPATH='', PYTHONUTF8='1')
        env.pop('PYTHONHOME', None)
        if run([sys.executable, '-I', '-m', 'venv', destination/'.venv'], env=env):
            stop('TTM-PY-10', unchanged=False, detail=PYTHON_HINTS)
        private = destination/'.venv/bin/python'
        if run([private, '-I', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check', '--no-cache-dir', '--no-index',
                '--find-links', HERE/'wheels-linux', '--only-binary=:all:', '--require-hashes', '-r', HERE/'requirements-player-linux.lock'], env=env):
            stop('TTM-PY-11', unchanged=False, detail='Bundled dependency installation failed. Extract a complete installer and check installer.log.')
        if run([private, '-I', '-m', 'pip', '--isolated', 'check'], env=env): stop('TTM-PY-12', unchanged=False)
        state['stage'] = 'Installing and verifying game adapter'
        offline_args = ['--allow-missing-libraries'] if args.allow_missing_libraries else []
        code = run([private, HERE/'install_player.py', '--destination', destination, '--iso', iso, '--pcsx2', pcsx2, '--bios', bios,
                    '--language', LANGUAGE[0], '--quiet-failure', *offline_args], env=env)
        if code: raise backend_failure(destination, code)
        # Use the final check, not just the early probe: system packages can change during setup.
        checked = json.loads((destination/'check-status.json').read_text(encoding='utf-8'))
        missing = checked.get('missing_runtime_dependencies', [])
        summary = (L('Installed. Install the missing system packages, then run Check installation.sh before playing.')
                   if missing else L('Ready. Open')+' '+str(destination/'Play.sh'))
        print(summary, flush=True)
        print(L('Press Select at the main menu for Modded Modes. Existing games, BIOS, emulator profiles and saves were not changed.'), flush=True)
        for problem in missing: print(L('PCSX2 cannot start until this is installed:')+' '+L(problem), flush=True)
        # The installation is complete: what follows is optional and never turns it into a failure.
        state['installed'] = True
        if beside is not None and state['tk'] is not None:
            offer_import(state['tk'], private, beside, destination, env)
        if state['tk'] is not None:
            with contextlib.suppress(Exception):
                from tkinter import messagebox
                # The BIOS copied into the installation and where it came from (a terminal shows it in the checklist).
                messagebox.showinfo('Tag Team Mod', summary+'\n\n'+'BIOS: '+str(bios)+installer.bios_origin(found, L)+'\n\n'+
                                    L('Press Select at the main menu for Modded Modes. Existing games, BIOS, emulator profiles and saves were not changed.'),
                                    parent=state['tk'])
        return destination
    except Cancelled as error:
        print(L(error.message), file=sys.stderr, flush=True)
        raise
    except Exception as error:
        if state.get('installed'):
            # After "Ready" the installation and its status are complete: an error here is a warning, never a failure.
            print(messages.labels(LANGUAGE[0])['warn']+': '+str(error), file=sys.stderr, flush=True)
            return state['destination']
        failure = installer.failure_for(error)
        if state['owned'] and failure.unchanged is None: failure.unchanged = False
        if not isinstance(error, ValueError): traceback.print_exc()
        block = failure.render(LANGUAGE[0] if CHOSEN[0] else 'both', log=log_path)
        print(block, file=sys.stderr, flush=True)
        if state['owned']:
            status = state['destination']/'install-status.json'
            try:
                old = json.loads(status.read_text(encoding='utf-8'))
                # A recorded failure is kept, and so is a finished installation ('[6/6] Installed' is never overwritten).
                recorded = old.get('error_code') or old.get('stage') == '[6/6] Installed'
            except (OSError, ValueError, AttributeError): recorded = None
            if not recorded:
                with contextlib.suppress(OSError): messages.write_status(status, failure, failed_stage=state['stage'])
        shown = False
        if state['tk'] is not None:
            with contextlib.suppress(Exception):
                from tkinter import messagebox
                messagebox.showerror('Tag Team Mod', block, parent=state['tk'])
                shown = True
        if not shown: hand_to_launcher(block)
        error.setup_failure = failure
        raise
    finally:
        state['log_destination'] = state['destination'] if state['owned'] else None
        setup.last_state = state


def main(argv=None, log_dir=None):
    """log_dir: where the setup log is kept (default: ~/.local/state/tagteammod/logs, or the temporary folder)."""
    args = parse(argv)
    log_path = messages.new_log_path('setup', log_dir)
    exit_code = 1
    with open(log_path, 'w', encoding='utf-8') as log:
        out, err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = Tee(out, log), Tee(err, log)
        try:
            setup(args, log_path); exit_code = 0
        except Cancelled:
            exit_code = 1
        except Exception as error:
            failure = getattr(error, 'setup_failure', None)
            exit_code = messages.exit_code(failure.code) if failure is not None else 1
        finally:
            sys.stdout, sys.stderr = out, err
    destination = getattr(setup, 'last_state', {}).get('log_destination')
    if destination is not None:
        with contextlib.suppress(OSError): (destination/'installer.log').write_bytes(log_path.read_bytes())
    return exit_code


if __name__ == '__main__': raise SystemExit(main())
