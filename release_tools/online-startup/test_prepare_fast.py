"""Fast preparation regressions, without starting PCSX2 or requiring game media."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_prepare_auto as auto
import native_map


def copy_at(root):
    copy = auto.PrepCopy.__new__(auto.PrepCopy)
    copy.base = SimpleNamespace(dest=Path(root), pid=123, cmd_pid=124, desktop='test-private',
                                python=Mock(return_value='private-python'), close=Mock())
    copy.run_dir = Path(root)
    copy.state, copy.engine = 'warm', 'teams'
    copy.lock = threading.RLock()
    copy.cancel = threading.Event()
    copy.reset_token = copy.reset_thread = None
    copy.reset_running = False
    copy.warming = False
    copy.suspended = []
    copy.fast_loading = False
    copy.exports_before = set()
    copy.checkpoint_before = None
    copy.test = copy.capture_shots = False
    copy.progress = copy.say = copy.event = Mock()
    return copy


def receipt(root, name='current', data=b'fully-written-match', **changes):
    folder = Path(root) / 'game/analysis/prepared-states' / name
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / '17-playable-team.p2s'
    output.write_bytes(data)
    record = dict(output=str(output), output_sha256=hashlib.sha256(data).hexdigest(),
                  serial=native_map.SERIAL, crc=native_map.CRC,
                  status='Offline copy patched and archive-verified; not loaded into the emulator')
    record.update(changes)
    path = folder / 'playable-export.json'
    path.write_text(json.dumps(record), encoding='utf-8')
    return path, output


class EarlyExport(unittest.TestCase):
    def test_accepts_complete_export_before_native_intro_log(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            _, output = receipt(folder)
            self.assertEqual(copy.early_checkpoint(), output.resolve())

    def test_never_accepts_export_from_previous_match(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            path, _ = receipt(folder)
            copy.exports_before = {str(path.resolve())}
            self.assertIsNone(copy.early_checkpoint())

    def test_changed_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            _, output = receipt(folder)
            output.write_bytes(b'different-match')
            self.assertIsNone(copy.early_checkpoint())

    def test_output_cannot_escape_current_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            outside = Path(folder) / 'foreign.p2s'
            outside.write_bytes(b'fully-written-match')
            receipt(folder, output=str(outside))
            self.assertIsNone(copy.early_checkpoint())

    def test_wrong_disc_and_partial_receipts_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            path, _ = receipt(folder, serial='OTHER-GAME')
            self.assertIsNone(copy.early_checkpoint())
            path.write_text('{"output":', encoding='utf-8')
            self.assertIsNone(copy.early_checkpoint())

    def test_wait_returns_verified_export_without_waiting_for_fight(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            _, output = receipt(folder)
            copy.check = Mock()
            copy.watcher_failed = Mock(return_value=None)
            copy.newest_checkpoint = Mock(side_effect=AssertionError('late checkpoint must not be read'))
            self.assertEqual(copy.wait_for_checkpoint(), output.resolve())


class PreparationCriticalPath(unittest.TestCase):
    def test_intro_and_reset_are_not_required_before_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.check = Mock()
            copy.at_map_select = Mock(return_value=True)
            copy.newest_checkpoint = Mock(return_value=None)
            copy.write_settings = copy.write_native = copy.confirm = Mock()
            copy.loading_speed = Mock()
            copy.schedule_reset = Mock()
            checkpoint = Path(folder) / 'checkpoint.p2s'
            checkpoint.write_bytes(b'archive')
            copy.wait_for_checkpoint = Mock(return_value=checkpoint)
            copy.wait_for_fight = Mock(side_effect=AssertionError('intro is not in startup path'))
            copy.return_to_select = Mock(side_effect=AssertionError('reset is not in startup path'))
            copy.test = True  # KO/failure hooks must not enable screenshot delays.
            copy.test_shot = Mock(side_effect=AssertionError('screenshots are opt-in'))
            with patch.object(auto.kit_win, 'pid_alive', return_value=True), \
                    patch.object(auto.kit_spec, 'engine_mode', return_value='teams'), \
                    patch.object(auto.kit_spec, 'spec_sha', return_value='a' * 64), \
                    patch.object(auto.kit_prepare, 'convert', return_value=dict(verify_sha='verified')) as convert:
                result = copy.prepare(dict(teams=[[{}], [{}]]), Path(folder) / 'made')
            self.assertEqual(result['verify_sha'], 'verified')
            convert.assert_called_once()
            self.assertIn('convert', result['timings'])
            self.assertNotIn('convert_and_back', result['timings'])
            copy.wait_for_fight.assert_not_called()
            copy.schedule_reset.assert_called_once()

    def test_fault_hook_is_preserved_without_screenshot_waits(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.check = Mock()
            copy.at_map_select = Mock(return_value=True)
            copy.newest_checkpoint = Mock(return_value=None)
            copy.write_settings = copy.write_native = Mock()
            copy.loading_speed = Mock()
            copy.test = True
            copy.confirm = Mock(side_effect=ValueError('injected costume'))
            with patch.object(auto.kit_win, 'pid_alive', return_value=True), \
                    patch.object(auto.kit_spec, 'engine_mode', return_value='teams'):
                with self.assertRaisesRegex(ValueError, 'injected costume'):
                    copy.prepare(dict(teams=[[{'costume': 0}], [{'costume': 0}]]),
                                 Path(folder) / 'made', options=dict(bad_costume=True))
            self.assertEqual(copy.confirm.call_args.args[0]['teams'][1][-1]['costume'], 3)
            copy.loading_speed.assert_called_with(False)

    def test_reset_worker_cannot_race_second_lock_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.loading_speed = Mock()
            copy.wait_for_fight = Mock(return_value=dict(clock=1, fighters=4))
            copy.return_to_select = copy.native_picks = copy.check = Mock()
            with copy.lock:
                copy.schedule_reset()
                # The thread is waiting on this RLock. A new nested owner can
                # consume the pending reset instead of joining and deadlocking.
                copy._finish_pending_reset()
            copy.reset_thread.join(timeout=2)
            self.assertFalse(copy.reset_thread.is_alive())
            copy.wait_for_fight.assert_called_once()
            self.assertEqual(copy.state, 'warm')
            self.assertIsNone(copy.reset_token)

    def test_close_invalidates_pending_reset_before_emulator_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.loading_speed = Mock()
            copy.wait_for_fight = Mock(side_effect=AssertionError('cancelled reset must not run'))
            with copy.lock:
                copy.schedule_reset()
                copy.close()
            copy.reset_thread.join(timeout=2)
            copy.wait_for_fight.assert_not_called()
            copy.base.close.assert_called_once()
            self.assertEqual(copy.state, 'cold')

    def test_engine_change_reuses_healthy_emulator(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.loading_speed = Mock()
            copy.check = Mock()
            copy.sample = Mock(return_value=dict(scene=auto.MAIN_MENU, pager=True))
            copy.commit_mode = Mock()
            copy.native_picks = Mock()
            copy.close = Mock(side_effect=AssertionError('healthy switch must not reboot'))
            with patch.object(auto.kit_win, 'pid_alive', return_value=True):
                self.assertEqual(copy.switch_engine('ffa'), 'warm')
            self.assertEqual(copy.engine, 'ffa')
            copy.commit_mode.assert_called_once()

    def test_commit_waits_for_owned_live_pager_and_resets_remembered_submenu(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            pointer = 0x600000
            main = dict(scene=auto.MAIN_MENU, pager=True, pager_state=2, pager_page=2,
                        main_object=pointer, pager_owner=pointer)
            selected = dict(scene=auto.TEAM_SELECT, loop=0)
            copy.sample = Mock(return_value=dict(main, pager_page=0))
            copy.watcher = Mock(return_value=dict(battle_mode='teams', humans=1))
            copy.check = Mock()
            calls = []
            copy.keys = lambda keys, gap=0: calls.append(keys)
            count = 0
            def wait(pred, timeout, what):
                nonlocal count
                count += 1
                if count == 1:
                    self.assertFalse(pred(dict(main, pager_state=0)))
                    self.assertFalse(pred(dict(main, pager_owner=pointer + 4)))
                    self.assertTrue(pred(main))
                    return main
                self.assertTrue(pred(selected))
                return selected
            copy.wait = wait
            words = {auto.MAIN_OBJECT: pointer, auto.PAGER + 20: pointer,
                     pointer + 0x144: 5, pointer + 0x148: 4, pointer + 0x10C: 0}
            client = Mock()
            client.__enter__ = Mock(return_value=client)
            client.__exit__ = Mock(return_value=False)
            copy.pine = Mock(return_value=client)
            with patch.object(auto, 'u32', side_effect=lambda c, a: words[a]):
                copy.commit_mode()
            self.assertEqual(calls[0], ['triangle'])
            self.assertEqual(calls[-2:], [['cross'], ['cross']])

    def test_private_speed_is_held_and_released_without_toggle(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            with patch.object(auto.kit_win, 'post_key') as key:
                copy.loading_speed(True)
                copy.loading_speed(True)  # idempotent: no repeated key-down.
                copy.loading_speed(False)
            self.assertEqual([c.args[2] for c in key.call_args_list], [True, False])
            self.assertFalse(copy.fast_loading)

    def test_headless_speed_key_never_targets_a_visible_user_emulator(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.base.desktop = None
            with patch.object(auto.kit_win, 'post_key') as key:
                copy.loading_speed(True)
            key.assert_not_called()

    def test_warm_failure_releases_private_turbo(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.state = 'cold'
            copy.base.pid = None
            copy.make_copy = Mock()
            copy.check = Mock()
            def launch():
                copy.base.pid = 123
            copy.launch = launch
            copy.boot = Mock(side_effect=ValueError('bad boot'))
            copy.close = Mock()
            with patch.object(auto.kit_win, 'post_key') as key:
                with self.assertRaisesRegex(ValueError, 'bad boot'):
                    copy.warm()
            self.assertEqual([c.args[2] for c in key.call_args_list], [True, False])
            self.assertEqual(copy.state, 'failed')


class PrivateDependencySharing(unittest.TestCase):
    def test_only_known_read_only_dependencies_share_storage(self):
        sharing = auto.kit_prepare.immutable_dependency
        for path in ('.venv/Lib/site-packages/numpy/__init__.py', '.venv/Scripts/python.exe',
                     'game/runtime28/pcsx2-qt.exe', 'game/runtime28/Qt6Core.dll'):
            self.assertTrue(sharing(Path(path)), path)
        for path in ('game/tools/pine.py', 'game/runtime28/inis/PCSX2.ini', 'game/runtime28/memcards/Mcd001.ps2',
                     'game/analysis/example.json', '.venv/pyvenv.cfg', 'game/launcher-lifecycle.ps1'):
            self.assertFalse(sharing(Path(path)), path)

    def test_patch_breaks_hardlink_without_changing_original_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source', Path(folder) / 'copy'
            source.write_bytes(b'original')
            try:
                os.link(source, target)
            except OSError:
                self.skipTest('filesystem does not support hardlinks')
            auto.kit_prepare.independent_write(target, b'private')
            self.assertEqual(source.read_bytes(), b'original')
            self.assertEqual(target.read_bytes(), b'private')
            self.assertFalse(os.path.samefile(source, target))


if __name__ == '__main__':
    unittest.main()
