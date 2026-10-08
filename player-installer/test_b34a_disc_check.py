"""Beta.34: Check installation and setup for the game disc chosen in Mod settings > Game disc. Offline: temporary
installations only, no ISO is read, no emulator starts."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import check_installation as checker
import install_player as installer
import setup_messages as messages

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent/'bt3-multifighter'/'tools'
EU_SHA = 'e6330ee0780e6f2d535bc280d2048bcc74385ae5973dc413755d1b99bf478cfc'
USA_SHA = '93f1f911e9a2bbdf92e5794fc3075ddf3f87db3df4b1cb8cfbb0448721c91172'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value), encoding='utf-8')


def installation(folder, tools=False):
    """<folder>/Tag Team Mod with the USA disc installed; with tools=True its game/tools holds the resolver and
    iso_compatibility sits beside game/ (enough for ISO_CHECK)."""
    root = Path(folder)/'Tag Team Mod'
    game = root/'game'
    write(game/'game-profile.json', dict(schema=1, iso=str(Path(folder)/'usa.iso'), adapter='bt3-usa', iso_sha256=USA_SHA,
                                         serial='SLUS_216.78', members={}, runtime_variant='BT3 USA / code-compatible translations'))
    write(game/'player-install.json', dict(schema=1, adapter='bt3-usa'))
    if tools:
        (game/'tools').mkdir(parents=True, exist_ok=True)
        for name in ('game_profile.py', 'atomic_files.py', 'localization.py', 'player_errors.py'):
            shutil.copyfile(TOOLS/name, game/'tools'/name)
        shutil.copytree(HERE.parent/'iso_compatibility', root/'iso_compatibility',
                        ignore=shutil.ignore_patterns('__pycache__', 'test_*.py'))
    return root


def library(root, iso, damaged=False, state='ready'):
    key = EU_SHA[:16]
    folder = root/'game'/'discs'/key
    profile = dict(schema=1, iso=str(iso), adapter='bt3-pal', iso_sha256=EU_SHA, serial='SLES_549.45',
                   members={'/SLES_549.45;1': sha(b'eu elf'), '/BIN/DBZP.BIN;1': 'd' * 64},
                   runtime_variant='BT3 Europe SLES-54945 (En/Fr/De/Es/It)')
    write(folder/'game-profile.json', profile)
    (folder/'analysis').mkdir(parents=True)
    (folder/'analysis'/'SLES_549.45').write_bytes(b'eu elf')
    files = {name: sha((folder/name).read_bytes()) for name in ('game-profile.json', 'analysis/SLES_549.45')}
    write(folder/'disc-files.json', dict(schema=1, state=state, key=key, iso_sha256=EU_SHA, adapter='bt3-pal', files=files))
    if damaged:
        (folder/'analysis'/'SLES_549.45').write_bytes(b'edited')
    return key, folder


def iso_check(root, refresh=False):
    env = checker.child_environment()
    env['PYTHONPATH'] = ''
    return subprocess.run([sys.executable, '-c', checker.ISO_CHECK.format(refresh=refresh)], cwd=root/'game'/'tools',
                          env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)


class IsoCheckChildTests(unittest.TestCase):
    def test_a_damaged_choice_is_check_19_in_english_and_spanish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = installation(folder, tools=True)
            write(root/'game'/'discs'/'active.json', dict(schema=1, key='not a key'))
            run = iso_check(root)
            self.assertEqual(run.returncode, 1, run.stderr)
            failure = checker.iso_failure(run.stderr, run.returncode)
            self.assertEqual(failure.code, 'TTM-CHECK-19')
            for language, words in (('en', ('[TTM-CHECK-19]', 'Mod settings', 'Game disc')),
                                    ('es', ('[TTM-CHECK-19]', 'Disco del juego'))):
                block = failure.render(language)
                for word in words:
                    self.assertIn(word, block)
                self.assertNotIn('{', block)

    def test_the_child_names_the_chosen_disc_before_checking_its_iso(self):
        """A6: check_installation reads the adapter of the chosen disc (TTM-DISC-ACTIVE), then pins its children."""
        with tempfile.TemporaryDirectory() as folder:
            root = installation(folder, tools=True)
            key, disc = library(root, Path(folder)/'gone.iso')
            write(root/'game'/'discs'/'active.json', dict(schema=1, key=key))
            run = iso_check(root)
            lines = [line for line in run.stdout.splitlines() if line.startswith(checker.DISC_LINE)]
            self.assertEqual(len(lines), 1, run.stdout + run.stderr)
            found = json.loads(lines[0][len(checker.DISC_LINE):])
            self.assertEqual((found['key'], found['adapter'], found['installed']), (key, 'bt3-pal', False))
            self.assertEqual(Path(found['profile']), disc/'game-profile.json')
            self.assertEqual(checker.iso_failure(run.stderr, run.returncode).code, 'TTM-CHECK-10', 'its ISO is gone')
            (disc/'analysis'/'SLES_549.45').write_bytes(b'edited')
            run = iso_check(root)
            self.assertEqual(checker.iso_failure(run.stderr, run.returncode).code, 'TTM-CHECK-19', 'a changed file')


class CheckOrderTests(unittest.TestCase):
    def fixture(self, folder):
        root = Path(folder)/'Tag Team Mod'
        write(root/'release.json', dict(version='0.1.0-beta.34'))
        write(root/'installed-files.json', dict(files={}, adapter='bt3-usa'))
        write(root/'dependencies.json', dict(packages={}))
        (root/'game'/'runtime28').mkdir(parents=True)
        (root/'game'/'runtime28'/'portable.ini').write_text('')
        return root

    def test_the_chosen_disc_decides_the_adapter_and_pins_every_runtime_check(self):
        calls, envs = [], []
        disc = dict(key='e6330ee0780e6f2d', adapter='bt3-pal', installed=False, profile='P/game-profile.json')

        def run(command, **options):
            if '-c' in command:
                calls.append('iso')
                return SimpleNamespace(returncode=0, stdout=checker.DISC_LINE + json.dumps(disc) + '\n', stderr='')
            envs.append(options['env'].get('TAGTEAM_DISC'))
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(folder)
            with mock.patch.object(checker, 'check_emulator', return_value='2.8.2'), \
                    mock.patch.object(checker, 'check_config', side_effect=lambda root, adapter: calls.append(('config', adapter))), \
                    mock.patch.object(checker, 'check_native_map',
                                      side_effect=lambda root, adapter, profile=None: calls.append(('map', adapter, profile))), \
                    mock.patch.object(checker.subprocess, 'run', side_effect=run), mock.patch.object(checker, 'WINDOWS', True), \
                    mock.patch.object(checker.sys, 'version_info', (3, 11, 9)), \
                    mock.patch.object(checker.struct, 'calcsize', return_value=8), \
                    mock.patch.dict(os.environ, {'TAGTEAM_DISC': 'ffffffffffffffff', 'TAGTEAM_ADAPTER': 'bt3-usa'}), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                result = checker.check(root)
        self.assertEqual(calls, ['iso', ('config', 'bt3-pal'), ('map', 'bt3-pal', 'P/game-profile.json')])
        self.assertEqual(envs, ['e6330ee0780e6f2d'], 'autopilot.py --check runs pinned to the checked disc')
        self.assertEqual((result['adapter'], result['disc']), ('bt3-pal', dict(key=disc['key'], adapter='bt3-pal', installed=False)))
        self.assertNotIn(checker.DISC_LINE, output.getvalue())

    def test_the_checks_children_never_inherit_a_pin_or_an_adapter_override(self):
        with mock.patch.dict(os.environ, {'TAGTEAM_DISC': 'x', 'TAGTEAM_ADAPTER': 'bt3-pal'}):
            env = checker.child_environment()
        self.assertNotIn('TAGTEAM_DISC', env)
        self.assertNotIn('TAGTEAM_ADAPTER', env)


class NativeMapAndNotesTests(unittest.TestCase):
    def test_the_address_table_is_checked_against_the_chosen_discs_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = installation(folder)
            key, disc = library(root, Path(folder)/'eu.iso')
            table = dict(schema=1, adapter='bt3-pal', elf_sha256=sha(b'eu elf'), dbzp_sha256='d' * 64)
            write(root/'game'/'tools'/'pal_native_map.json', table)
            checker.check_native_map(root, 'bt3-pal', disc/'game-profile.json')
            write(root/'game'/'tools'/'pal_native_map.json', dict(table, elf_sha256='0' * 64))
            with self.assertRaises(Exception) as caught:
                checker.check_native_map(root, 'bt3-pal', disc/'game-profile.json')
            self.assertEqual(caught.exception.code, 'TTM-CHECK-15')
            fix = messages.render('TTM-CHECK-15', 'en', **messages.platform_values())
            self.assertIn('Game disc', fix)

    def test_a_damaged_disc_that_is_not_chosen_is_only_a_note(self):
        with tempfile.TemporaryDirectory() as folder:
            root = installation(folder)
            key, _ = library(root, Path(folder)/'eu.iso', damaged=True)
            self.assertEqual(checker.library_notes(root, key), [], 'the chosen disc is checked (and fails) elsewhere')
            notes = checker.library_notes(root, USA_SHA[:16])
            self.assertEqual(len(notes), 1)
            self.assertIn(f'game/discs/{key}', notes[0])
            self.assertIn('Game disc', notes[0])
            self.assertIn('Disco del juego', checker.library_notes(root, USA_SHA[:16], 'es')[0])
            library_root = installation(Path(folder)/'intact')
            library(library_root, Path(folder)/'eu.iso')
            self.assertEqual(checker.library_notes(library_root, USA_SHA[:16]), [])


class SetupTests(unittest.TestCase):
    def test_every_platform_names_its_mod_settings_launcher(self):
        self.assertEqual(messages.platform_values(True)['settings'], 'Mod settings.cmd')
        self.assertEqual(messages.platform_values(False)['settings'], 'Mod settings.sh')
        for code in ('TTM-CHECK-10', 'TTM-CHECK-15', 'TTM-CHECK-19'):
            for language in ('en', 'es'):
                with self.subTest(code=code, language=language):
                    block = messages.render(code, language, reason='r')
                    self.assertNotIn('{', block)
                    self.assertIn(messages.platform_values()['settings'], block)
        source = (HERE/'install-player.ps1').read_text(encoding='ascii')
        self.assertIn("settings = 'Mod settings.cmd'", source)

    def test_the_generated_launchers_clear_the_disc_pin_and_the_adapter_override(self):
        """A5: a leftover TAGTEAM_DISC or TAGTEAM_ADAPTER in the player's environment never reaches the tools."""
        windows = installer.windows_scripts('en')
        for name in ('Play.cmd', 'Mod settings.cmd', 'Check installation.cmd', 'Scan compatibility.cmd',
                     'Build expanded maps.cmd'):
            with self.subTest(name=name):
                self.assertIn('set "TAGTEAM_DISC="', windows[name])
                self.assertIn('set "TAGTEAM_ADAPTER="', windows[name])
        linux = installer.linux_scripts('bt3-usa', 'en')
        for name in ('Play.sh', 'Mod settings.sh', 'Check installation.sh', 'Scan compatibility.sh', 'Build expanded maps.sh'):
            with self.subTest(name=name):
                self.assertIn('TAGTEAM_DISC= TAGTEAM_ADAPTER=', linux[name])


class ScannerStepTests(unittest.TestCase):
    def test_the_hash_progress_step_is_the_installers_by_default(self):
        """L7: setup's output is unchanged; the Game disc page asks for a line every 64 MiB."""
        sys.path.insert(0, str(HERE.parent))
        from iso_compatibility.scanner import hash_file
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'x.bin'
            path.write_bytes(os.urandom(3 << 20))
            lines = []
            digest = hash_file(path, lines.append)
            self.assertEqual((digest, lines), (sha(path.read_bytes()), ['Fingerprinting ISO: 100%']))
            lines = []
            hash_file(path, lines.append, step=1 << 20)
            self.assertEqual(len(lines), 1, 'one 8 MiB block: one line')
            path.write_bytes(os.urandom(24 << 20))
            lines = []
            hash_file(path, lines.append, step=8 << 20)
            self.assertEqual(lines, ['Fingerprinting ISO: 33%', 'Fingerprinting ISO: 66%', 'Fingerprinting ISO: 100%'])


if __name__ == '__main__':
    unittest.main()
