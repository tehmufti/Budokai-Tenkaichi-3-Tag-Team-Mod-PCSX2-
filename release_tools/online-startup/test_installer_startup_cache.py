"""Private installer lifecycle regressions; no emulator or subprocess is started."""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'player-installer/install_player.py'
spec = importlib.util.spec_from_file_location('_startup_installer_review', SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class FakeProcess:
    pid = 424242

    def __init__(self, code=0, timeout=False):
        self.code = code
        self.timeout = timeout
        self.returncode = None
        self.waits = []
        self.kills = 0

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.timeout and len(self.waits) == 1:
            raise subprocess.TimeoutExpired('private builder', timeout)
        self.returncode = self.code
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.kills += 1
        self.returncode = -1


class FakeSocket:
    def __init__(self, busy=False):
        self.busy = busy
        self.address = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def bind(self, address):
        self.address = address
        if self.busy:
            raise OSError('private test port busy')


class StartupCacheInstaller(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for relative, data in {
            'Play.cmd': b'ordinary offline play remains enabled',
            'game/runtime28/inis/PCSX2.ini': b'offline settings',
            'game/runtime28/memcards/Mcd001.ps2': b'offline saved progress',
            'game/runtime28/sstates/slot1.p2s': b'offline user save slot',
            'game/mod-settings.json': b'{"offline_setting":true}',
            'online/netplay/kit_selector_cache.py': b'cache module marker',
        }.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.original = self.snapshot_protected()
        self.capture = io.StringIO()

    def snapshot_protected(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()
                and not path.relative_to(self.root).as_posix().startswith('online/prep/')}

    def run_cache(self, process=None, popen_error=None, socket_factory=None, taskkill=None):
        process = process or FakeProcess()
        factory = socket_factory or (lambda *a, **k: FakeSocket())
        with patch.object(installer, 'WINDOWS', True), \
                patch.object(socket, 'socket', side_effect=factory), \
                patch.object(subprocess, 'Popen', side_effect=popen_error, return_value=process) as start, \
                patch.object(subprocess, 'run', side_effect=taskkill) as kill_tree, \
                contextlib.redirect_stdout(self.capture):
            result = installer.online_startup_cache(self.root)
        self.assertEqual(self.snapshot_protected(), self.original)
        return result, start, kill_tree

    def test_success_stays_inside_online_and_clears_foreign_runtime(self):
        with patch.dict(os.environ, TTM_KIT_RUNTIME='foreign test folder', TAGTEAM_DISC='foreign',
                        TAGTEAM_ADAPTER='foreign', PYTHONPATH='foreign', PYTHONHOME='foreign'):
            result, start, kill_tree = self.run_cache()
        self.assertEqual(result['state'], 'ready')
        args, options = start.call_args
        command = args[0]
        self.assertEqual(command[command.index('--install') + 1], str(self.root))
        self.assertEqual(command[command.index('--out') + 1], str(self.root / 'online/prep/setup-cache'))
        self.assertIn('--build-selector-cache', command)
        self.assertEqual(options['cwd'], self.root)
        self.assertEqual(options['creationflags'], subprocess.CREATE_NO_WINDOW)
        for key in ('TTM_KIT_RUNTIME', 'TAGTEAM_DISC', 'TAGTEAM_ADAPTER', 'PYTHONPATH'):
            self.assertEqual(options['env'][key], '')
        self.assertNotIn('PYTHONHOME', options['env'])
        self.assertFalse(kill_tree.called)
        receipt = json.loads((self.root / 'online/prep/setup-cache/status.json').read_text())
        self.assertEqual(receipt, result)

    def test_builder_failure_keeps_offline_play_and_records_fallback(self):
        result, _, _ = self.run_cache(FakeProcess(code=19))
        self.assertEqual(result['state'], 'unavailable')
        self.assertEqual(result['exit_code'], 19)
        self.assertIn('Fast online startup was not prepared', self.capture.getvalue())

    def test_spawn_error_is_optional(self):
        result, _, _ = self.run_cache(popen_error=OSError('test spawn refused'))
        self.assertEqual(result['state'], 'unavailable')
        self.assertIn('test spawn refused', result['reason'])

    def test_no_free_ports_never_starts_builder(self):
        result, start, _ = self.run_cache(socket_factory=lambda *a, **k: FakeSocket(busy=True))
        self.assertEqual(result['state'], 'unavailable')
        self.assertIn('private preparation port', result['reason'])
        self.assertFalse(start.called)

    def test_timeout_kills_owned_tree_before_parent_disappears(self):
        process = FakeProcess(timeout=True)

        def kill_tree(command, **options):
            self.assertIsNone(process.returncode)
            self.assertEqual(command, ['taskkill', '/PID', str(process.pid), '/T', '/F'])
            process.returncode = -1
            return types.SimpleNamespace(returncode=0)

        result, _, kill = self.run_cache(process, taskkill=kill_tree)
        self.assertEqual(result['state'], 'unavailable')
        self.assertEqual(process.waits, [240, 10])
        self.assertEqual(process.kills, 0)
        self.assertEqual(kill.call_count, 1)

    def test_failed_tree_cleanup_still_reaps_owned_parent(self):
        process = FakeProcess(timeout=True)
        result, _, _ = self.run_cache(process, taskkill=OSError('test taskkill unavailable'))
        self.assertEqual(result['state'], 'unavailable')
        self.assertEqual(process.kills, 1)
        self.assertEqual(process.waits, [240, 10])

    def test_optional_cache_folder_error_cannot_fail_install(self):
        original = Path.mkdir

        def mkdir(path, *args, **kwargs):
            if path == self.root / 'online/prep/setup-cache':
                raise PermissionError('test cache folder denied')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'mkdir', mkdir):
            result, start, _ = self.run_cache()
        self.assertEqual(result['state'], 'unavailable')
        self.assertIn('cache folder denied', result['reason'])
        self.assertFalse(start.called)

    def test_status_receipt_disk_error_cannot_fail_install(self):
        original = Path.write_text

        def write(path, *args, **kwargs):
            if path == self.root / 'online/prep/setup-cache/status.json':
                raise OSError('test receipt disk full')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'write_text', write):
            result, _, _ = self.run_cache(FakeProcess(code=19))
        self.assertEqual(result['state'], 'unavailable')
        self.assertTrue((self.root / 'Play.cmd').is_file())

    def test_linux_does_not_start_windows_builder(self):
        with patch.object(installer, 'WINDOWS', False), patch.object(subprocess, 'Popen') as start:
            result = installer.online_startup_cache(self.root)
        self.assertEqual(result['state'], 'not-built')
        self.assertFalse(start.called)
        self.assertFalse((self.root / 'online/prep').exists())

    def test_locally_derived_selectors_not_in_installed_code_inventory(self):
        for name in ('native-selector-cache/identity/teams.p2s',
                     'native-selector-cache/private-authentication.key', 'setup-cache/setup.log'):
            path = self.root / 'online/prep' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'private generated cache fixture')
        inventory = installer.online_files(self.root)
        self.assertIn('online/netplay/kit_selector_cache.py', inventory)
        self.assertFalse(any('prep/' in path or path.endswith('.p2s') for path in inventory))

    def test_builder_receipt_error_cannot_skip_native_cleanup(self):
        source = ROOT / 'bt3-multifighter/online/netplay/kit_prepare_auto.py'
        module = ast.parse(source.read_text(encoding='utf-8'))
        main = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        copies = []

        class Copy:
            closed = False

            def __init__(self, *args, **kwargs):
                copies.append(self)

            def warm(self): pass
            def switch_engine(self, engine): pass
            def cache_selector(self): pass
            def close(self): self.closed = True

        namespace = dict(Path=Path, json=json, time=__import__('time'), PrepCopy=Copy)
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(source), 'exec'), namespace)
        fake_install = types.SimpleNamespace(read_installation=lambda path: {'iso': 'fixture.iso'})
        fake_match = types.SimpleNamespace(ensure_elf=lambda path: None)
        original = Path.write_text

        def write(path, *args, **kwargs):
            if path.name == 'results.json':
                raise OSError('test results disk full')
            return original(path, *args, **kwargs)

        argv = ['builder', '--install', str(self.root), '--slot', '29971',
                '--out', str(self.root / 'private-builder'), '--build-selector-cache']
        with patch.dict(sys.modules, kit_install=fake_install, kit_match=fake_match), \
                patch.object(sys, 'argv', argv), patch.object(Path, 'write_text', write), \
                self.assertRaisesRegex(OSError, 'results disk full'):
            namespace['main']()
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].closed)


if __name__ == '__main__':
    unittest.main()
