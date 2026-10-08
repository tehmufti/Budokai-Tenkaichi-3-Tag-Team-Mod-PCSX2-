"""install_linux.py (the Linux setup front end) and Install.sh: mocked on Windows, real on Linux."""
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import install_linux as front
import install_player as installer
import setup_messages as messages
from test_install_player import appimage_bytes, bios_image, iso_image, linux_only, minimum_mentions

HERE = Path(__file__).resolve().parent
TRANSLATIONS = json.loads((HERE/'installer-es.json').read_text(encoding='utf-8'))
# The real file system probes (SetupFlowTests replaces them in setUp).
REAL_CHECKS = dict(check_file_system=front.check_file_system, check_symlinks=front.check_symlinks)


def literal_calls(path, names):
    """Constant string first arguments (the title for pick_*) of calls to the given functions in a source file."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names:
            index = 1 if node.func.id.startswith('pick_') else 0
            if len(node.args) > index and isinstance(node.args[index], ast.Constant) and isinstance(node.args[index].value, str):
                found.append(node.args[index].value)
    return found


class TranslationTests(unittest.TestCase):
    def test_every_linux_setup_message_and_launcher_text_is_translated(self):
        texts = literal_calls(HERE/'install_linux.py', {'L', 'fail', 'pick_file', 'pick_directory'})
        texts += literal_calls(HERE/'install_player.py', {'L'})
        texts += [installer.FLATPAK_REFUSED, installer.NOT_ELF, installer.NOT_X86_64, installer.NOT_APPIMAGE,
                  installer.UNKNOWN_VERSION, *installer.SCRIPT_TEXTS, *front.checker.LINUX_PREREQUISITES,
                  'Tag Team Mod - Mod settings', 'Tag Team Mod - PCSX2 settings']
        texts = [t for t in texts if t not in ('Setup cancelled / Instalacion cancelada.', 'Tag Team Mod')]
        self.assertGreater(len(texts), 40)
        catalog = json.loads((HERE/'messages.json').read_text(encoding='utf-8'))['codes']
        codes = literal_calls(HERE/'install_linux.py', {'stop'})
        self.assertGreater(len(codes), 10)
        for code in codes:
            with self.subTest(code=code): self.assertTrue(catalog[code]['en']['what'] and catalog[code]['es']['what'])
        for text in texts:
            with self.subTest(text=text):
                self.assertIn(text, TRANSLATIONS)
                self.assertNotEqual(TRANSLATIONS[text], text)

    def test_linux_strings_name_the_release_minimum(self):
        minimum = installer.release_info()['pcsx2_minimum']
        texts = [t for t in literal_calls(HERE/'install_linux.py', {'L', 'fail', 'pick_file', 'pick_directory'}) if minimum_mentions(t)]
        self.assertGreaterEqual(len(texts), 1, 'the AppImage chooser names the minimum (the refusal is TTM-PCSX2-02)')
        self.assertTrue(any('AppImage' in t and t.startswith('Choose the PCSX2') for t in texts))
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(set(minimum_mentions(text)), {minimum})
                self.assertEqual(set(minimum_mentions(TRANSLATIONS[text])), {minimum})


class InstallerFilesTests(unittest.TestCase):
    def layout(self, root):
        release = root/'Tag Team Mod Installer'; setup = release/'setup'; setup.mkdir(parents=True)
        (release/'Install.sh').write_bytes(b'#!/bin/sh\n'); (setup/'install_player.py').write_bytes(b'code')
        files = {name: hashlib.sha256((release/name).read_bytes()).hexdigest() for name in ('Install.sh', 'setup/install_player.py')}
        (setup/'installer-files.json').write_text(json.dumps(dict(schema=2, version='x', files=files)))
        return release, setup

    def test_every_listed_file_must_exist_inside_the_release_and_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            release, setup = self.layout(Path(tmp))
            self.assertEqual(len(front.check_installer_files(setup)['files']), 2)
            (setup/'install_player.py').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum failed.*install_player.py'): front.check_installer_files(setup)
            (setup/'install_player.py').unlink()
            with self.assertRaisesRegex(ValueError, 'missing or unsafe'): front.check_installer_files(setup)
            (Path(tmp)/'outside.txt').write_bytes(b'x')
            (setup/'installer-files.json').write_text(json.dumps(dict(schema=2, files={'../outside.txt': hashlib.sha256(b'x').hexdigest()})))
            with self.assertRaisesRegex(ValueError, 'missing or unsafe'): front.check_installer_files(setup)
            (setup/'installer-files.json').unlink()
            with self.assertRaisesRegex(ValueError, 'incomplete'): front.check_installer_files(setup)


class SystemChecksTests(unittest.TestCase):
    def test_platform_architecture_and_python(self):
        with patch.object(front.sys, 'platform', 'win32'), self.assertRaisesRegex(ValueError, 'for Linux'): front.check_platform()
        with patch.object(front.sys, 'platform', 'linux'):
            with patch.object(front.platform, 'machine', return_value='aarch64'), self.assertRaisesRegex(ValueError, 'x86-64'):
                front.check_platform()
            with patch.object(front.platform, 'machine', return_value='x86_64'):
                with patch.object(front.sys, 'version_info', (3, 10, 12)), self.assertRaisesRegex(ValueError, 'Python 3.11'):
                    front.check_platform()
                with patch.object(front.sys, 'version_info', (3, 13, 1)): front.check_platform()

    def test_destination_must_be_new_with_an_existing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(front.resolve_destination(root/'Tag Team Mod'), root.resolve()/'Tag Team Mod')
            (root/'Tag Team Mod').mkdir()
            with self.assertRaisesRegex(ValueError, 'already exists'): front.resolve_destination(root/'Tag Team Mod')
            with self.assertRaisesRegex(ValueError, 'does not exist'): front.resolve_destination(root/'missing/Tag Team Mod')
            with self.assertRaisesRegex(ValueError, 'control characters'): front.resolve_destination(root/'Tag\nTeam')

    def test_options_are_never_abbreviated(self):
        # Install.sh decides from the full names whether the dialogs (and Tk) are needed.
        self.assertEqual(front.parse(['--destination', 'd']).destination, Path('d'))
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            front.parse(['--dest', 'd'])
        self.assertIn('unrecognized arguments: --dest', err.getvalue())

    def test_noexec_and_symlink_free_file_systems_are_refused(self):
        with patch.object(front.os, 'ST_NOEXEC', 8, create=True):
            with patch.object(front.os, 'statvfs', return_value=SimpleNamespace(f_flag=8 | 1), create=True):
                with self.assertRaisesRegex(ValueError, 'noexec'): front.check_file_system('/media/usb')
            with patch.object(front.os, 'statvfs', return_value=SimpleNamespace(f_flag=1), create=True):
                front.check_file_system('/home/player')
        with tempfile.TemporaryDirectory() as tmp, patch.object(front.os, 'symlink', side_effect=OSError(1, 'Operation not permitted')):
            with self.assertRaisesRegex(ValueError, 'symbolic links'): front.check_symlinks(tmp)
            self.assertEqual(os.listdir(tmp), [])

    @linux_only
    def test_real_linux_folder_passes_both_checks_and_resolves_symlinked_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            front.check_file_system(tmp); front.check_symlinks(tmp); self.assertEqual(os.listdir(tmp), [])
            real = Path(tmp)/'var/home'; real.mkdir(parents=True); (Path(tmp)/'home').symlink_to(real)
            self.assertEqual(front.resolve_destination(Path(tmp)/'home/Tag Team Mod'), real.resolve()/'Tag Team Mod')


class SetupFlowTests(unittest.TestCase):
    """The whole front end with the system probes, dialogs and child processes replaced."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = self.tmp/'logs'; self.logs.mkdir()  # the setup log's folder before a destination exists
        self.iso = self.tmp/'bt3.iso'; self.iso.write_bytes(iso_image())
        self.bios = self.tmp/'bios.bin'; self.bios.write_bytes(bios_image())
        self.appimage = self.tmp/'pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage'; self.appimage.write_bytes(appimage_bytes())
        self.commands = []; self.results = {}
        self.version = ('2.8.2', 'AppImage metainfo'); self.prerequisites = ([], ['libSDL2-2.0.so.0 is missing'])
        # No PCSX2 settings of this PC are read: a BIOS the flow does not select comes from this empty home folder.
        self.home = self.tmp/'home'; self.home.mkdir()
        environment = patch.dict(os.environ, HOME=str(self.home)); environment.start(); self.addCleanup(environment.stop)
        os.environ.pop('XDG_CONFIG_HOME', None)
        for target, name, value in ((front, 'check_installer_files', lambda setup=None: {}), (front, 'check_platform', lambda: None),
                                    (front, 'check_file_system', lambda folder: None), (front, 'check_symlinks', lambda folder: None),
                                    (front, 'open_tk', self.no_tk), (front, 'run', self.fake_run),
                                    (front.installer, 'appimage_version', lambda path: self.version),
                                    (front.checker, 'linux_prerequisites', lambda: self.prerequisites)):
            patcher = patch.object(target, name, value); patcher.start(); self.addCleanup(patcher.stop)
        self.addCleanup(front.LANGUAGE.__setitem__, 0, 'en')

    def no_tk(self):
        raise AssertionError('headless setup must not need Tk')

    def fake_run(self, command, **options):
        self.commands.append([str(c) for c in command])
        if len(command)>1 and Path(command[1]).name=='install_player.py':
            destination=Path(command[command.index('--destination')+1])
            missing=self.prerequisites[0]
            (destination/'check-status.json').write_text(json.dumps(dict(ready=not missing,installation_valid=True,
                                                                      missing_runtime_dependencies=missing)))
        return self.results.get(len(self.commands), 0)

    def main(self, *extra, destination=None):
        args = ['--destination', str(destination or self.tmp/'Tag Team Mod'), '--iso', str(self.iso), '--pcsx2', str(self.appimage),
                '--bios', str(self.bios), *extra]
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = front.main(args, log_dir=self.logs)
        return code, out.getvalue(), err.getvalue()

    def test_headless_install_creates_the_venv_offline_and_hands_over(self):
        system_logs = lambda: set(Path(tempfile.gettempdir()).glob('TagTeamMod-Setup-*.log'))
        before = system_logs()
        code, out, err = self.main()
        self.assertEqual(code, 0, out+err)
        self.assertEqual(system_logs()-before, set(), 'the tests keep the setup log out of the system temporary folder')
        self.assertEqual(len(list(self.logs.glob('setup-*.log'))), 1)
        destination = self.tmp.resolve()/'Tag Team Mod'
        self.assertEqual(json.loads((destination/'install-bootstrap.json').read_text())['schema'], 1)
        venv, install, check, handover = self.commands
        self.assertEqual(venv[1:], ['-I', '-m', 'venv', str(destination/'.venv')])
        self.assertEqual(install[0], str(destination/'.venv/bin/python'))
        for flag in ('--no-index', '--require-hashes', '--only-binary=:all:', str(HERE/'wheels-linux'), str(HERE/'requirements-player-linux.lock')):
            self.assertIn(flag, install)
        self.assertEqual(check[1:], ['-I', '-m', 'pip', '--isolated', 'check'])
        self.assertEqual(handover[1:], [str(HERE/'install_player.py'), '--destination', str(destination), '--iso', str(self.iso.absolute()),
                                        '--pcsx2', str(self.appimage.resolve()), '--bios', str(self.bios.absolute()), '--language', 'en',
                                        '--quiet-failure'])
        self.assertIn('Ready. Open '+str(destination/'Play.sh'), out)
        self.assertIn('libSDL2-2.0.so.0 is missing', out)
        log = (destination/'installer.log').read_text(encoding='utf-8')
        self.assertIn('[2/6]', log); self.assertIn('Ready. Open', log)

    def test_failure_keeps_a_receipt_and_the_log_but_no_launcher(self):
        self.results[2] = 1  # pip install fails
        code, out, err = self.main('--language', 'es')
        destination = self.tmp.resolve()/'Tag Team Mod'
        self.assertEqual(code, 40)
        status = json.loads((destination/'install-status.json').read_text(encoding='utf-8'))
        self.assertEqual((status['ready'], status['stage'], status['error_code']), (False, 'FAILED', 'TTM-PY-11'))
        self.assertIn('[2/6]', status['failed_stage'])
        self.assertIn('[TTM-PY-11] INSTALACION DETENIDA', err)
        self.assertIn(' '.join(messages.text('TTM-PY-11', 'what', 'es').split()[:6]), err)
        self.assertNotIn('No se ha cambiado nada.', err, 'the destination was already created')
        self.assertIn('[TTM-PY-11] INSTALACION DETENIDA', (destination/'installer.log').read_text(encoding='utf-8'))
        self.assertFalse((destination/'Play.sh').exists())

    def test_refusals_before_anything_is_created(self):
        destination = self.tmp/'Tag Team Mod'
        cases = [(lambda: setattr(self, 'version', ('2.5.211', 'file name')), 50, 'TTM-PCSX2-02(.|\n)*too old: 2.5.211. Select PCSX2 2.6.0'),
                 (lambda: setattr(self, 'version', ('3.0.1', 'file name')), 50, 'TTM-PCSX2-03(.|\n)*newer than this release supports'),
                 (lambda: setattr(self, 'prerequisites', (['libOpenGL.so.0, which PCSX2 needs'], [])), 20, '--allow-missing-libraries')]
        for prepare, exit_code, message in cases:
            with self.subTest(message=message):
                self.version = ('2.8.2', 'AppImage metainfo'); self.prerequisites = ([], []); prepare()
                code, out, err = self.main()
                self.assertEqual(code, exit_code); self.assertRegex(err, message); self.assertFalse(destination.exists())
                self.assertIn('Nothing was changed.', err)
        def flatpak(path): raise ValueError(installer.FLATPAK_REFUSED)
        with patch.object(front.installer, 'appimage_version', flatpak):
            code, out, err = self.main('--language', 'es')
        self.assertEqual(code, 50); self.assertIn('[TTM-PCSX2-10]', err); self.assertFalse(destination.exists())
        self.assertIn(' '.join(TRANSLATIONS[installer.FLATPAK_REFUSED].split()[:8]), ' '.join(err.split()))
        self.prerequisites = (['libOpenGL.so.0, which PCSX2 needs'], [])
        code, out, err = self.main('--allow-missing-libraries')
        self.assertEqual(code, 0, err); self.assertIn('PCSX2 cannot start until this is installed: libOpenGL.so.0', out)
        self.assertIn('--allow-missing-libraries',self.commands[-1])
        self.assertNotIn('Ready. Open',out)
        self.assertIn('Installed. Install the missing system packages',out)

    def test_missing_system_parts_are_named_in_the_setup_language(self):
        checker = front.checker
        self.prerequisites = ([checker.MISSING_OPENGL, checker.MISSING_FUSERMOUNT], [checker.MISSING_SDL])
        code, out, err = self.main('--language', 'es', '--allow-missing-libraries')
        self.assertEqual(code, 0, err)
        for problem in (checker.MISSING_OPENGL, checker.MISSING_FUSERMOUNT):
            self.assertIn(TRANSLATIONS['PCSX2 cannot start until this is installed:']+' '+TRANSLATIONS[problem], out)
        self.assertIn(TRANSLATIONS['Note:']+' '+TRANSLATIONS[checker.MISSING_SDL], out)
        self.assertNotIn('which PCSX2 needs to start', out, 'no English sentence in the Spanish setup')

    def test_an_unreadable_version_is_decided_from_the_installed_copy(self):
        # e.g. a renamed, non-executable AppImage with /tmp mounted noexec: install_player.py reads its own copy.
        def unknown(path): raise ValueError(installer.UNKNOWN_VERSION)
        with patch.object(front.installer, 'appimage_version', unknown):
            code, out, err = self.main()
        self.assertEqual(code, 0, err); self.assertIn('read again after the AppImage is copied', out)

    def test_dialogs_choose_language_folder_and_files(self):
        picked = iter([self.iso, self.appimage, self.bios]); titles = []
        def pick_file(root, title, filetypes, initialdir=None): titles.append(title); return next(picked)
        with patch.object(front, 'open_tk', return_value='tk-root'), patch.object(front, 'choose_language', return_value='es'), \
             patch.object(front, 'pick_directory', return_value=self.tmp), patch.object(front, 'pick_file', pick_file), \
             patch('tkinter.messagebox.showinfo') as shown, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = front.main([], log_dir=self.logs)
        self.assertEqual(code, 0)
        self.assertEqual(self.commands[-1][-3:], ['--language', 'es', '--quiet-failure'])
        self.assertEqual(self.commands[-1][3], str(self.tmp.resolve()/'Tag Team Mod'))
        self.assertIn('AppImage', titles[1]); shown.assert_called_once()


    def test_a_damaged_installer_opened_from_a_file_manager_is_shown_in_a_window(self):
        """The dialogs open before the installer files are checked, so TTM-ZIP-02/03/04 reach the player without a terminal."""
        order = []
        def broken(setup=None): order.append('files'); raise messages.SetupFailure('TTM-ZIP-03', name='setup/install_player.py')
        with patch.object(front, 'open_tk', lambda: order.append('tk') or 'tk-root'), patch.object(front, 'check_installer_files', broken), \
             patch('tkinter.messagebox.showerror') as shown, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = front.main([], log_dir=self.logs)
        self.assertEqual((code, order), (10, ['tk', 'files']))
        self.assertIn('[TTM-ZIP-03] SETUP STOPPED / INSTALACION DETENIDA', shown.call_args[0][1])

    def test_an_error_no_window_could_show_is_handed_to_install_sh(self):
        handed = self.tmp/'error.txt'; handed.write_text('')
        def no_display(): raise messages.SetupFailure('TTM-OS-05', detail="couldn't connect to display")
        with patch.dict(os.environ, TAGTEAM_SETUP_ERROR_FILE=str(handed)), patch.object(front, 'open_tk', no_display), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = front.main([], log_dir=self.logs)
        self.assertEqual(code, 20)
        self.assertIn('[TTM-OS-05] SETUP STOPPED / INSTALACION DETENIDA', handed.read_text(encoding='utf-8'))
        # Shown in setup's own window: nothing is handed over (Install.sh shows no second dialog).
        handed.write_text('')
        def broken(setup=None): raise messages.SetupFailure('TTM-ZIP-02')
        with patch.dict(os.environ, TAGTEAM_SETUP_ERROR_FILE=str(handed)), patch.object(front, 'open_tk', return_value='tk-root'), \
             patch.object(front, 'check_installer_files', broken), patch('tkinter.messagebox.showerror'), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = front.main([], log_dir=self.logs)
        self.assertEqual((code, handed.read_text()), (10, ''))

    def test_symlink_probe_errors_are_told_apart(self):
        import errno
        with tempfile.TemporaryDirectory() as tmp:
            for number, code in ((errno.EACCES, 'TTM-DEST-01'), (errno.EROFS, 'TTM-DEST-01'), (errno.EPERM, 'TTM-DEST-09'),
                                 (getattr(errno, 'ENOTSUP', 95), 'TTM-DEST-09')):
                with self.subTest(errno=number), patch.object(front.os, 'symlink', side_effect=OSError(number, os.strerror(number))), \
                     self.assertRaises(messages.SetupFailure) as caught:
                    REAL_CHECKS['check_symlinks'](tmp)
                self.assertEqual(caught.exception.code, code)

    @linux_only
    def test_a_folder_the_player_cannot_write_to_is_named_as_such(self):
        if os.geteuid() == 0: self.skipTest('root can write to any folder')
        parent = self.tmp/'read-only'; parent.mkdir(); parent.chmod(0o555); self.addCleanup(parent.chmod, 0o755)
        with patch.object(front, 'check_file_system', REAL_CHECKS['check_file_system']), patch.object(front, 'check_symlinks', REAL_CHECKS['check_symlinks']):
            code, out, err = self.main(destination=parent/'Tag Team Mod')
        self.assertEqual(code, 30); self.assertIn('[TTM-DEST-01]', err); self.assertNotIn('TTM-DEST-09', err + out)

    def test_after_ready_nothing_turns_the_installation_into_a_failure(self):
        """A complete installation stays complete: an error in the optional steps (the import) is a warning, exit 0, and
        install-status.json keeps its '[6/6] Installed' record."""
        existing = self.tmp.resolve()/'Tag Team Mod'; existing.mkdir()
        for name in ('Play.sh', 'installed-files.json'): (existing/name).write_text('{}')
        (existing/'game').mkdir(); (existing/'game/player-install.json').write_text(json.dumps(dict(adapter='bt3-usa')))
        def installed(command, **options):
            code = self.fake_run(command, **options)
            if '--iso' in command:
                destination = Path(command[command.index('--destination')+1])
                (destination/'install-status.json').write_text(json.dumps(dict(stage='[6/6] Installed', ready=True)))
            return code
        picked = iter([self.iso, self.appimage, self.bios])
        with patch.object(front, 'open_tk', return_value='tk-root'), patch.object(front, 'choose_language', return_value='en'), \
             patch.object(front, 'pick_directory', return_value=existing), patch.object(front, 'pick_file', lambda *a, **k: next(picked)), \
             patch.object(front, 'run', installed), patch.object(front.installer, 'same_game', side_effect=RuntimeError('boom')), \
             patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.askyesno', return_value=True), \
             contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = front.main([], log_dir=self.logs)
        self.assertEqual(code, 0, err.getvalue())
        # The chosen folder was itself an installation: the new one went beside it, never inside it.
        new = self.tmp.resolve()/('Tag Team Mod '+installer.release_info()['version'])
        self.assertTrue(new.is_dir()); self.assertFalse((existing/'Tag Team Mod').exists())
        self.assertIn('[WARN] TTM-DEST-27', out.getvalue()); self.assertNotIn('SETUP STOPPED', err.getvalue())
        self.assertEqual(json.loads((new/'install-status.json').read_text())['stage'], '[6/6] Installed')

class PythonProbeTests(unittest.TestCase):
    """Install.sh's Python probe, run here with the values it checks replaced: it names why a Python cannot be used."""
    def probe(self, *patches):
        text = (HERE/'Install.sh').read_text(encoding='utf-8')
        code = text.split("probe='", 1)[1].split("'\n", 1)[0]
        import ensurepip, sysconfig, venv  # noqa: F401  (imported before sys.version_info is replaced)
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()) as out:
            for replacement in patches: stack.enter_context(replacement)
            try: exec(compile(code, 'Install.sh probe', 'exec'), {'__name__': 'probe'})
            except SystemExit as stop: status = stop.code
            else: status = 0
        return status, out.getvalue().strip()

    def test_each_rejection_names_its_reason(self):
        usable = [patch.object(sys, 'version_info', (3, 12, 3)), patch('platform.machine', return_value='x86_64'),
                  patch('struct.calcsize', return_value=8), patch('sysconfig.get_config_var', return_value=None)]
        self.assertEqual(self.probe(*usable), (0, ''))
        for replacement, reason in (
                (patch.object(sys, 'version_info', (3, 15, 0)), 'it is Python 3.15; the bundled packages serve 3.11 to 3.14'),
                (patch.object(sys, 'version_info', (3, 10, 12)), 'it is Python 3.10; the bundled packages serve 3.11 to 3.14'),
                (patch('struct.calcsize', return_value=4), 'it is not a 64-bit x86-64 Python'),
                (patch('platform.machine', return_value='aarch64'), 'it is not a 64-bit x86-64 Python'),
                (patch('sysconfig.get_config_var', side_effect=lambda name: 1 if name == 'Py_GIL_DISABLED' else None),
                 'it is a free-threaded build, which the bundled packages do not serve'),
                (patch.dict(sys.modules, {'ensurepip': None}), 'its venv/ensurepip part is missing')):
            with self.subTest(reason=reason):
                self.assertEqual(self.probe(*usable, replacement), (1, reason))


@linux_only
class InstallShTests(unittest.TestCase):
    """Install.sh's Python selection with stand-in interpreters on an otherwise empty PATH."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.release = self.tmp/'Tag Team Mod Installer'; (self.release/'setup').mkdir(parents=True)
        shutil.copy(HERE/'Install.sh', self.release/'Install.sh')
        (self.release/'setup/install_linux.py').write_text('# stand-in: the fake Pythons never run it\n')
        self.bin = self.tmp/'bin'; self.bin.mkdir()
        for tool in ('uname', 'dirname', 'env'): (self.bin/tool).symlink_to(shutil.which(tool))
        real = sys.executable
        # python3.13: a Python without Tk. python3: a Python without venv/ensurepip.
        self.fake('python3.13', f'case "$*" in *tkinter*) exit 1 ;; *install_linux.py*) echo "RAN ${{0##*/}} [$PYTHONNOUSERSITE] [$PYTHONPATH] $*"; exit 0 ;; esac\nexec {real} "$@"\n')
        self.fake('python3', f'case "$*" in *ensurepip*) echo "its venv/ensurepip part is missing"; exit 1 ;; esac\nexec {real} "$@"\n')

    def fake(self, name, body, folder=None):
        path = (folder or self.bin)/name; path.write_text('#!/bin/sh\n'+body); path.chmod(0o755); return path

    def install(self, *args, **env):
        return subprocess.run([shutil.which('sh'), str(self.release/'Install.sh'), *args], capture_output=True, text=True, timeout=120,
                              stdin=subprocess.DEVNULL, env=dict(PATH=str(self.bin), HOME=str(self.tmp), PYTHONPATH='/guard', **env))

    def test_script_is_lf_posix_sh(self):
        data = (HERE/'Install.sh').read_bytes()
        self.assertTrue(data.startswith(b'#!/bin/sh\n')); self.assertNotIn(b'\r', data)
        self.assertEqual(subprocess.run(['sh', '-n', str(HERE/'Install.sh')], capture_output=True).returncode, 0)

    def test_dialogs_need_tk_and_missing_parts_print_package_hints(self):
        result = self.install()
        self.assertEqual(result.returncode, 40)
        self.assertIn('[TTM-PY-20] SETUP STOPPED / INSTALACION DETENIDA', result.stderr)
        self.assertIn('No se ha cambiado nada.', result.stderr)
        self.assertIn('sudo apt install python3 python3-venv python3-tk', result.stderr)
        self.assertIn('Pythons tried that cannot be used:\n  python3.13: its Tk part (tkinter), needed for the setup dialogs, is missing\n'
                      '  python3: its venv/ensurepip part is missing\n', result.stderr)
        self.assertIn('uv python install 3.12', result.stderr)

    def test_a_rejected_tagteam_python_is_named(self):
        flags = ['--destination', '/d', '--iso', '/i.iso', '--pcsx2', '/p.AppImage', '--bios', '/b.bin']
        missing = self.tmp/'missing-python'
        result = self.install(*flags, TAGTEAM_PYTHON=str(missing))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'Note: TAGTEAM_PYTHON={missing}: not found. Using python3.13 instead.', result.stderr)
        other = self.tmp/'uv'; other.mkdir()
        newer = self.fake('python', 'case "$*" in *sysconfig*) echo "it is Python 3.15; the bundled packages serve 3.11 to 3.14"; exit 1 ;; esac\n'
                                    'echo "RAN uv-python"; exit 0\n', other)
        result = self.install(*flags, TAGTEAM_PYTHON=str(newer))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'Note: TAGTEAM_PYTHON={newer}: it is Python 3.15; the bundled packages serve 3.11 to 3.14. Using python3.13 instead.',
                      result.stderr)
        self.assertIn('RAN python3.13', result.stdout); self.assertNotIn('RAN uv-python', result.stdout)
        result = self.install(TAGTEAM_PYTHON=str(newer))  # the dialogs: no usable Python at all
        self.assertEqual(result.returncode, 40)
        self.assertIn(f'  TAGTEAM_PYTHON={newer}: it is Python 3.15; the bundled packages serve 3.11 to 3.14\n', result.stderr)

    def test_complete_flags_or_help_do_not_need_tk(self):
        flags = ['--destination', '/d', '--iso', '/i.iso', '--pcsx2=/p.AppImage', '--bios', '/b.bin']
        result = self.install(*flags)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RAN python3.13 [1] [] -I -X utf8 '+str(self.release/'setup/install_linux.py')+' '+' '.join(flags), result.stdout)
        self.assertIn('RAN python3.13', self.install('--help').stdout)

    def test_a_missing_setup_folder_is_explained_in_both_languages(self):
        (self.release/'setup/install_linux.py').unlink()
        result = self.install()
        self.assertEqual(result.returncode, 10)
        for text in ('[TTM-ZIP-01] SETUP STOPPED / INSTALACION DETENIDA', 'Extract the whole linux-x86_64.tar.gz archive',
                     'Extrae el archivo linux-x86_64.tar.gz completo', str(self.release/'setup/install_linux.py')):
            self.assertIn(text, result.stderr)
        self.assertNotIn('RAN', result.stdout)

    def test_without_a_terminal_the_error_is_also_a_dialog(self):
        record = self.tmp/'zenity.txt'
        self.fake('zenity', f'printf "%s\\n" "$@" > "{record}"\n')
        result = self.install(DISPLAY=':0')
        self.assertEqual(result.returncode, 40)
        shown = record.read_text()
        self.assertTrue(shown.startswith('--error\n--no-markup\n--title=Tag Team Mod\n--text='))
        self.assertIn('[TTM-PY-20]', shown); self.assertIn('sudo apt install python3 python3-venv python3-tk', shown)

    def test_an_error_setup_could_not_show_becomes_a_dialog(self):
        """Started from a file manager: an error install_linux.py could not show in its own window (no display for Tk yet)
        is left in the file Install.sh names, shown with zenity, and the file is removed."""
        record = self.tmp/'zenity.txt'; temporary = self.tmp/'t'; temporary.mkdir()
        self.fake('zenity', f'printf "%s\\n" "$@" > "{record}"\n')
        for tool in ('mktemp', 'cat', 'rm'): (self.bin/tool).symlink_to(shutil.which(tool))
        flags = ['--destination', '/d', '--iso', '/i.iso', '--pcsx2', '/p.AppImage', '--bios', '/b.bin']
        for handed, code in (('[TTM-OS-05] SETUP STOPPED / INSTALACION DETENIDA', 20), ('', 30)):
            with self.subTest(handed=handed):
                record.unlink(missing_ok=True)
                self.fake('python3.13', 'case "$*" in *install_linux.py*) '+(f'printf "%s\\n" "{handed}" > "$TAGTEAM_SETUP_ERROR_FILE"; ' if handed else '')+
                          f'exit {code} ;; esac\nexec {sys.executable} "$@"\n')
                result = self.install(*flags, DISPLAY=':0', TMPDIR=str(temporary))
                self.assertEqual(result.returncode, code, result.stderr)
                if handed: self.assertIn(handed, record.read_text())
                else: self.assertFalse(record.exists(), 'setup showed the error itself: no second dialog')
                self.assertEqual(list(temporary.iterdir()), [], 'the hand-over file is removed')

    def test_tagteam_python_is_tried_first(self):
        other = self.tmp/'uv'; other.mkdir()
        chosen = self.fake('python', f'case "$*" in *install_linux.py*) echo "RAN uv-python"; exit 0 ;; esac\nexec {sys.executable} "$@"\n', other)
        result = self.install(TAGTEAM_PYTHON=str(chosen))
        self.assertEqual(result.returncode, 0, result.stderr); self.assertIn('RAN uv-python', result.stdout)


if __name__ == '__main__': unittest.main()
