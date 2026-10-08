"""Private online launcher ownership and verified-media guards; no emulator starts."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_paths
import kit_prepare_launch as launch
import kit_selector_cache as cache
import kit_win
import kit_wire_codec as codec


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prep = self.root / 'runtime/prep'
        self.dest = self.prep / 'Tag Team Mod'
        (self.dest / 'game').mkdir(parents=True)
        (self.dest / 'game/player-install.json').write_text('{}')
        self.iso = self.root / 'disc.iso'; self.iso.write_bytes(b'verifiedmedia')
        self.ident = dict(iso='verified', bios=dict(sha256='a' * 64))
        self.copy = SimpleNamespace(slot=29861, iso=self.iso, run_dir=self.root,
            install=dict(root=str(self.root / 'installed'), adapter='bt3-usa'),
            base=SimpleNamespace(dest=self.dest, desktop='private-test', pid=None, cmd_pid=None,
                                 python=lambda: self.root / 'python.exe'),
            check=Mock(), sleep=lambda seconds: None)
        self.exe = (self.dest / 'game/runtime28/pcsx2-qt.exe').resolve()
        self.patches = [patch.object(kit_paths, 'PREP', self.prep),
            patch.object(launch, 'os', SimpleNamespace(name='nt', environ={})),
            patch.object(cache, 'identity', return_value=self.ident),
            patch.object(kit_win, 'listener_pid', side_effect=[None, 222]),
            patch.object(kit_win, 'process_path', return_value=str(self.exe)),
            patch.object(kit_win, 'pid_alive', return_value=True),
            patch.object(kit_win, 'kill_with_me'), patch.object(kit_win, 'kill_tree'),
            patch.object(launch, 'receipt_owned', return_value=True),
            patch.object(kit_win, 'launch', side_effect=self.start)]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)

    def start(self, command, cwd, console, desktop, env):
        request = json.loads(Path(command[-1]).read_text())
        status = dict(pid=111, emulator_pid=222, emulator_created=10,
                      launcher_token=request['token'], native_mode_receipt={}, state='MENU')
        (Path(request['folder']) / 'status.json').write_text(json.dumps(status))
        return 111

    def test_start_uses_private_python_desktop_and_owns_both_instances(self):
        self.assertEqual(launch.launch(self.copy, self.ident), 222)
        self.assertEqual((self.copy.base.pid, self.copy.base.cmd_pid), (222, 111))
        command, cwd, console, desktop = kit_win.launch.call_args.args
        self.assertEqual(command[0], self.root / 'python.exe')
        self.assertEqual(desktop, 'private-test')
        self.assertEqual(cwd, self.dest / 'game')
        self.assertEqual(kit_win.kill_with_me.call_args_list[0].args, (111,))
        self.assertEqual(kit_win.kill_with_me.call_args_list[-1].args, (222,))
        kit_win.kill_tree.assert_not_called()

    def test_original_install_is_never_a_fast_launch_target(self):
        self.copy.install['root'] = str(self.dest)
        with self.assertRaisesRegex(ValueError, 'isolated owned'):
            launch.launch(self.copy, self.ident)
        kit_win.launch.assert_not_called()

    def test_occupied_port_refuses_before_start_and_does_not_kill_owner(self):
        kit_win.listener_pid.side_effect = None; kit_win.listener_pid.return_value = 333
        with self.assertRaises(Exception): launch.launch(self.copy, self.ident)
        kit_win.launch.assert_not_called(); kit_win.kill_tree.assert_not_called()

    def test_changed_immutable_identity_refuses_before_launch(self):
        cache.identity.return_value = {'changed': True}
        with self.assertRaisesRegex(ValueError, 'changed before launch'):
            launch.launch(self.copy, self.ident)
        kit_win.launch.assert_not_called()

    def test_optional_boot_descriptor_is_validated_and_bound_to_owned_request(self):
        descriptor = dict(claim={'signed': True}, mac='a' * 64)
        with patch.object(cache, 'validate_boot') as validate:
            self.assertEqual(launch.launch(self.copy, self.ident, boot=descriptor), 222)
        validate.assert_called_once_with(descriptor, self.dest, self.ident, inflate=False)
        request = json.loads(Path(kit_win.launch.call_args.args[0][-1]).read_text())
        self.assertEqual(request['selector_boot'], descriptor)

    def test_invalid_boot_archive_is_refused_before_worker_is_started(self):
        with patch.object(cache, 'validate_boot', side_effect=ValueError('boot authentication failed')):
            with self.assertRaisesRegex(ValueError, 'boot authentication'):
                launch.launch(self.copy, self.ident, boot={'unverified': True})
        kit_win.launch.assert_not_called()
        kit_win.kill_tree.assert_not_called()

    def test_worker_statefile_command_uses_only_its_revalidated_archive(self):
        state = self.dest / 'game/runtime28/sstates/.ttm-selector-boot-valid.p2s'
        request = dict(iso=str(self.iso), identity=self.ident, selector_boot={'signed': True})
        with patch.object(cache, 'validate_boot', return_value=state) as validate:
            command = launch.emulator_command(request, self.dest, self.exe)
        validate.assert_called_once_with(request['selector_boot'], self.dest, self.ident, inflate=False)
        self.assertEqual(command, [str(self.exe), '-portable', '-fastboot', '-statefile', str(state),
                                   '--', str(self.iso)])

    def test_worker_ordinary_launch_never_invents_or_loads_a_checkpoint(self):
        with patch.object(cache, 'validate_boot') as validate:
            command = launch.emulator_command(dict(iso=str(self.iso)), self.dest, self.exe)
        validate.assert_not_called()
        self.assertEqual(command, [str(self.exe), '-portable', '-fastboot', '--', str(self.iso)])

    def test_only_authenticated_selector_boot_skips_native_menu_checkpoint_owner(self):
        folder = self.dest / 'game/analysis/autopilot/owned'
        request = dict(token='a' * 32, selector_boot={'signed': True})
        command = launch.watcher_command(request, self.dest, folder, 222)
        self.assertIn('--no-menu-checkpoint', command)
        self.assertEqual(command[command.index('--launcher-token') + 1], request['token'])
        self.assertEqual(command[command.index('--emulator-pid') + 1], '222')
        request.pop('selector_boot')
        self.assertNotIn('--no-menu-checkpoint', launch.watcher_command(request, self.dest, folder, 222))

    def test_failed_owned_launch_cleans_only_its_staged_boot_archive(self):
        state = self.dest / 'game/runtime28/sstates/.ttm-selector-boot-test.p2s'
        state.parent.mkdir(parents=True); state.write_bytes(b'owned')
        other = state.with_name('user-state.p2s'); other.write_bytes(b'user')
        self.copy.check.side_effect = [None, RuntimeError('cancelled')]
        with patch.object(cache, 'validate_boot', return_value=state):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                launch.launch(self.copy, self.ident, boot={'signed': True})
        self.assertFalse(state.exists())
        self.assertEqual(other.read_bytes(), b'user')
        kit_win.kill_tree.assert_called_once_with(111)

    def test_foreign_listener_race_stops_only_captured_worker_tree(self):
        kit_win.process_path.return_value = str(self.root / 'user/pcsx2-qt.exe')
        with self.assertRaisesRegex(ValueError, 'foreign process'):
            launch.launch(self.copy, self.ident)
        kit_win.kill_tree.assert_called_once_with(111)
        self.assertEqual((self.copy.base.pid, self.copy.base.cmd_pid), (None, None))

    def test_cancel_during_launch_stops_only_captured_worker_tree(self):
        self.copy.check.side_effect = [None, RuntimeError('cancelled')]
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            launch.launch(self.copy, self.ident)
        kit_win.kill_tree.assert_called_once_with(111)

    def test_invalid_receipt_never_attaches_even_when_expected_pid_listens(self):
        launch.receipt_owned.return_value = False
        kit_win.listener_pid.side_effect = None
        # Initial probe must be empty; after our worker starts, its PINE is alive.
        kit_win.listener_pid.side_effect = lambda slot: 222 if self.copy.base.cmd_pid else None
        with self.assertRaises(TimeoutError): launch.launch(self.copy, self.ident, timeout=.01)
        kit_win.kill_tree.assert_called_once_with(111)
        self.assertIsNone(self.copy.base.pid)

    def test_request_validation_rejects_stale_media_or_foreign_folder(self):
        folder = self.dest / 'game/analysis/autopilot/session'; folder.mkdir(parents=True)
        path = folder / 'request.json'
        row = dict(schema=1, root=str(self.dest), folder=str(folder), token='a' * 32,
                   slot=29861, iso=str(self.iso), iso_stamp=launch.file_stamp(self.iso))
        path.write_text(json.dumps(row)); launch.validate_request(path)
        self.iso.write_bytes(b'different verified media')
        with self.assertRaisesRegex(ValueError, 'ISO changed'): launch.validate_request(path)
        row['iso_stamp'] = launch.file_stamp(self.iso); row['folder'] = str(self.root)
        path.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError, 'does not own'): launch.validate_request(path)


class StartupOverlapTests(unittest.TestCase):
    """Only neutral cached startup may overlap; late failures never authorize a VM."""
    def setUp(self):
        import psutil
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'prep/Tag Team Mod'
        self.folder = self.root / 'game/analysis/autopilot/owned'; self.folder.mkdir(parents=True)
        self.iso = self.root / 'disc.iso'; self.iso.write_bytes(b'checked media')
        self.exe = self.root / 'game/runtime28/pcsx2-qt.exe'
        self.request = dict(slot=29861, iso=str(self.iso), iso_stamp=launch.file_stamp(self.iso),
                            token='a' * 32, identity={'checked': True}, selector_boot={'authenticated': True})
        self.events = []
        self.runtime = SimpleNamespace(EXECUTABLE=self.exe, DIRECTORY=self.exe.parent, CHEATS=self.root/'cheats')
        self.lease = Mock(); self.lease.acquire.return_value = self.lease
        self.launcher = SimpleNamespace(Lease=Mock(return_value=self.lease))
        self.autopilot = SimpleNamespace(main=Mock(side_effect=lambda: self.events.append('watcher') or 0))
        self.process = Mock(); self.process.create_time.return_value = 123
        self.process.exe.return_value = str(self.exe)
        self.child = SimpleNamespace(pid=222)
        self.storage = SimpleNamespace(prune=Mock(side_effect=lambda root: self.events.append('storage')))
        self.hooks = SimpleNamespace(install_cheat=Mock(side_effect=lambda path: self.events.append('hooks')))
        self.presentation = SimpleNamespace(apply=Mock(side_effect=lambda: self.events.append('presentation')),
                                             restore=Mock())
        patches = [patch.dict(sys.modules, {'player_storage':self.storage, 'guest_loading_screen':self.hooks,
                    'game_profile':SimpleNamespace(cheat_name=lambda serial:'checked.pnach'),
                    'native_map':SimpleNamespace(SERIAL='SLUS-21678'),
                    'presentation_settings':self.presentation}),
            patch.object(launch, 'preflight_environment', side_effect=self.environment),
            patch.object(launch, 'preflight_watcher', side_effect=self.watcher),
            patch.object(launch, 'preflight', side_effect=self.complete),
            patch.object(launch.socket, 'create_connection', side_effect=ConnectionRefusedError()),
            patch.object(launch, 'emulator_command', side_effect=self.command),
            patch.object(cache, 'validate_boot'),
            patch.object(cache, 'install_boot_hooks', return_value=False),
            patch.object(launch.subprocess, 'Popen', side_effect=self.spawn),
            patch.object(psutil, 'Process', return_value=self.process),
            patch.object(launch, 'stop_owned_process', wraps=launch.stop_owned_process)]
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        argv = sys.argv
        self.addCleanup(setattr, sys, 'argv', argv)

    def environment(self, *args):
        self.events.append('environment'); return self.runtime, self.launcher

    def watcher(self, *args):
        self.events.append('dependency/native check'); return self.autopilot

    def complete(self, *args):
        self.events.append('complete preflight'); return self.autopilot, self.runtime, self.launcher

    def command(self, *args):
        self.events.append('authenticated command'); return ['owned emulator']

    def spawn(self, *args, **kwargs):
        self.events.append('spawn'); return self.child

    def run_worker(self):
        return launch.run_worker(self.request, self.root, self.folder)

    def test_cached_boot_runs_all_early_guards_then_overlaps_only_watcher_checks(self):
        self.assertEqual(self.run_worker(), 0)
        self.assertEqual(self.events, ['environment', 'storage', 'hooks', 'presentation',
                                      'authenticated command', 'spawn', 'dependency/native check', 'watcher'])
        launch.preflight.assert_not_called()
        launch.stop_owned_process.assert_called_once_with(self.process, 123, self.exe)
        self.process.terminate.assert_called_once()
        self.presentation.restore.assert_called_once(); self.lease.release.assert_called_once()

    def test_ordinary_boot_finishes_complete_preflight_before_any_spawn(self):
        self.request.pop('selector_boot')
        self.assertEqual(self.run_worker(), 0)
        self.assertEqual(self.events, ['complete preflight', 'storage', 'hooks', 'presentation',
                                      'authenticated command', 'spawn', 'watcher'])
        launch.preflight_environment.assert_not_called(); launch.preflight_watcher.assert_not_called()
        cache.install_boot_hooks.assert_not_called(); cache.validate_boot.assert_not_called()

    def test_signed_generated_hooks_skip_generation_before_cached_spawn(self):
        cache.install_boot_hooks.side_effect = lambda *args: self.events.append('cached hooks') or {'bytes': 123}
        self.assertEqual(self.run_worker(), 0)
        self.hooks.install_cheat.assert_not_called()
        self.assertLess(self.events.index('cached hooks'), self.events.index('spawn'))
        self.assertLess(self.events.index('spawn'), self.events.index('dependency/native check'))
        cache.validate_boot.assert_called_once_with(self.request['selector_boot'], self.root,
                                                   self.request['identity'], inflate=False)

    def test_missing_or_damaged_hook_cache_regenerates_from_pinned_native_source(self):
        for error in (FileNotFoundError('missing generated hooks'), ValueError('generated checksum differs')):
            cache.install_boot_hooks.side_effect = error
            phases = []
            launch.prepare_boot_hooks(self.request, self.root, self.runtime,
                                      lambda phase, **values: phases.append((phase, values)))
            self.assertEqual(phases[0][0], 'guest_hooks_rejected')
            self.assertEqual(phases[1], ('guest_hooks_complete', {'cached': False}))
        self.assertEqual(self.hooks.install_cheat.call_count, 2)

    def test_invalid_signed_selector_is_fatal_before_any_hook_write_or_spawn(self):
        cache.validate_boot.side_effect = ValueError('selector authentication failed')
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        cache.install_boot_hooks.assert_not_called(); self.hooks.install_cheat.assert_not_called()
        launch.subprocess.Popen.assert_not_called(); self.lease.release.assert_called_once()

    def test_occupied_private_hooks_are_not_bypassed_by_generation_fallback(self):
        cache.install_boot_hooks.side_effect = cache.OccupiedBootHooks('Loading hook file is occupied')
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        self.hooks.install_cheat.assert_not_called(); launch.subprocess.Popen.assert_not_called()
        self.autopilot.main.assert_not_called(); self.lease.release.assert_called_once()

    def test_late_dependency_failure_after_hook_reuse_still_closes_exact_child(self):
        cache.install_boot_hooks.return_value = {'bytes': 123, 'sha256': 'a' * 64}
        launch.preflight_watcher.side_effect = ValueError('late native check failed')
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        self.hooks.install_cheat.assert_not_called(); self.autopilot.main.assert_not_called()
        self.process.terminate.assert_called_once()
        launch.stop_owned_process.assert_called_once_with(self.process, 123, self.exe)
        self.presentation.restore.assert_called_once(); self.lease.release.assert_called_once()

    def test_late_dependency_or_native_failure_closes_only_exact_spawned_child(self):
        launch.preflight_watcher.side_effect = ValueError('late dependency check failed')
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        self.autopilot.main.assert_not_called()
        launch.stop_owned_process.assert_called_once_with(self.process, 123, self.exe)
        self.process.terminate.assert_called_once()
        self.presentation.restore.assert_called_once(); self.lease.release.assert_called_once()

    def test_early_configuration_rejection_never_starts_an_emulator(self):
        launch.preflight_environment.side_effect = ValueError('private configuration changed')
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        launch.subprocess.Popen.assert_not_called(); self.launcher.Lease.assert_not_called()
        self.autopilot.main.assert_not_called(); launch.stop_owned_process.assert_not_called()

    def test_foreign_port_probe_releases_lease_without_spawning_or_signaling_owner(self):
        foreign = Mock(); launch.socket.create_connection.side_effect = None
        launch.socket.create_connection.return_value = foreign
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        foreign.close.assert_called_once(); self.lease.release.assert_called_once()
        launch.subprocess.Popen.assert_not_called(); launch.stop_owned_process.assert_not_called()

    def test_invalid_authenticated_boot_cannot_reach_overlap_or_watcher(self):
        launch.emulator_command.side_effect = ValueError('cached descriptor changed')
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        launch.subprocess.Popen.assert_not_called(); launch.preflight_watcher.assert_not_called()
        self.presentation.restore.assert_called_once(); self.lease.release.assert_called_once()

    def test_media_change_during_overlapped_import_is_rejected_before_watcher(self):
        def changed(*args):
            self.iso.write_bytes(b'different media'); return self.autopilot
        launch.preflight_watcher.side_effect = changed
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        self.autopilot.main.assert_not_called(); self.process.terminate.assert_called_once()

    def test_recycled_child_after_late_check_is_never_signaled_as_captured_owner(self):
        def recycled(*args):
            self.process.create_time.return_value = 124; return self.autopilot
        launch.preflight_watcher.side_effect = recycled
        with patch('traceback.print_exc'):
            self.assertEqual(self.run_worker(), 1)
        self.autopilot.main.assert_not_called(); self.process.terminate.assert_not_called()
        self.presentation.restore.assert_called_once(); self.lease.release.assert_called_once()


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        import psutil
        self.psutil = psutil
        self.emulator = SimpleNamespace(create_time=lambda: 123)
        self.watcher = SimpleNamespace(parents=lambda: [SimpleNamespace(pid=111)])
        self.status = dict(pid=112, emulator_pid=222, emulator_created=123,
                           launcher_token='a' * 32, state='MENU', native_mode_receipt={})
        self.patch = patch.object(psutil, 'Process', side_effect=lambda pid: self.emulator if pid == 222 else self.watcher)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_redirector_child_is_authenticated(self):
        self.assertTrue(launch.receipt_owned(self.status, 'a' * 32, 222, 111))

    def test_recycled_emulator_pid_refused(self):
        self.emulator.create_time = lambda: 124
        self.assertFalse(launch.receipt_owned(self.status, 'a' * 32, 222, 111))

    def test_alive_unrelated_watcher_pid_refused(self):
        self.watcher.parents = lambda: [SimpleNamespace(pid=999)]
        self.assertFalse(launch.receipt_owned(self.status, 'a' * 32, 222, 111))

    def test_wrong_token_failed_state_or_missing_structured_receipt_refused(self):
        for values in ({'launcher_token': 'b' * 32}, {'state': 'FAILED'}, {'native_mode_receipt': None}):
            self.assertFalse(launch.receipt_owned(dict(self.status, **values), 'a' * 32, 222, 111))

    def test_cleanup_does_not_signal_recycled_or_foreign_process(self):
        process = Mock(); process.create_time.return_value = 124; process.exe.return_value = 'owned.exe'
        self.assertFalse(launch.stop_owned_process(process, 123, 'owned.exe'))
        process.terminate.assert_not_called()
        process.create_time.return_value = 123; process.exe.return_value = 'foreign.exe'
        self.assertFalse(launch.stop_owned_process(process, 123, 'owned.exe'))
        process.terminate.assert_not_called()

    def test_cleanup_terminates_only_exact_captured_instance(self):
        process = Mock(); process.create_time.return_value = 123; process.exe.return_value = 'owned.exe'
        self.assertTrue(launch.stop_owned_process(process, 123, 'owned.exe'))
        process.terminate.assert_called_once(); process.wait.assert_called_once_with(3)


class VerifiedMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'disc.iso'; self.path.write_bytes(b'full verified image' * 100)
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.copy = SimpleNamespace(iso=self.path, install=dict(iso_sha256=self.sha, adapter='bt3-usa'))
        self.adapter = SimpleNamespace(name='bt3-usa')
        self.patches = [patch.object(codec, 'Disc', return_value=SimpleNamespace(close=lambda: None)),
            patch.object(codec, 'runtime_match', return_value=(self.adapter, {'verified': True})),
            patch.object(codec, 'verify_stage_mapping'), patch.object(codec.VerifiedIso, '_allowed_file_ids', return_value=set())]
        for item in self.patches: item.start(); self.addCleanup(item.stop)
        cache._HASHES.clear()
        self.context = codec.VerifiedIso(self.path, self.sha)
        self.addCleanup(self.context.close)

    def test_live_full_verified_context_eliminates_duplicate_file_stream(self):
        self.assertEqual(cache.seed_verified_iso(self.copy, self.context), self.sha)
        with patch.object(Path, 'open', side_effect=AssertionError('duplicate ISO stream')):
            self.assertEqual(cache.sha(self.path, memo=True), self.sha)

    def test_duck_typed_context_cannot_seed_identity(self):
        with self.assertRaisesRegex(ValueError, 'owned full-image verifier'):
            cache.seed_verified_iso(self.copy, SimpleNamespace(**vars(self.context)))
        self.assertEqual(cache._HASHES, {})

    def test_context_for_another_path_hash_or_adapter_is_refused(self):
        other = self.path.with_name('other.iso'); other.write_bytes(self.path.read_bytes())
        for copy in (SimpleNamespace(iso=other, install=self.copy.install),
                     SimpleNamespace(iso=self.path, install=dict(self.copy.install, iso_sha256='0' * 64)),
                     SimpleNamespace(iso=self.path, install=dict(self.copy.install, adapter='bt4-b14-rev2-eng'))):
            with self.assertRaisesRegex(ValueError, 'different installation media'):
                cache.seed_verified_iso(copy, self.context)
        self.assertEqual(cache._HASHES, {})

    def test_closed_context_does_not_seed_an_unchecked_hash(self):
        self.context.close()
        with self.assertRaisesRegex(ValueError, 'closed'): cache.seed_verified_iso(self.copy, self.context)
        self.assertEqual(cache._HASHES, {})

    def test_changed_or_replaced_media_is_refused(self):
        self.path.write_bytes(b'replacement image')
        with self.assertRaisesRegex(ValueError, 'changed'): cache.seed_verified_iso(self.copy, self.context)
        self.assertEqual(cache._HASHES, {})


if __name__ == '__main__': unittest.main()
