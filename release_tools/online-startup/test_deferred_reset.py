"""Committed match delivery never competes with the private selector reset."""
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_controller
import kit_fight
import kit_prepare_auto as auto
from test_prepare_fast import copy_at


class DeferredReset(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.copy = copy_at(directory.name)
        self.copy.slot = 29921
        self.copy.reset_deferred = False
        self.copy.reset_owner = None
        self.copy.suspended_tokens = {}
        self.tokens = {123: ('windows', 'private-emulator', 5), 124: ('windows', 'private-watcher', 6)}
        self.listener = 123
        self.copy.watcher = Mock(return_value={'state': 'ACTIVE'})
        self.suspended, self.resumed = [], []
        for item in (
            patch.object(auto.os, 'name', 'nt'),
            patch.object(auto.kit_win, 'process_tree', return_value=[124, 123]),
            patch.object(auto.kit_win, 'process_path', return_value=str(
                self.copy.base.dest / 'game/runtime28/pcsx2-qt.exe')),
            patch.object(auto.kit_win, 'listener_pid', side_effect=lambda _: self.listener),
            patch.object(auto.kit_win, 'suspend_pids', side_effect=self.suspend),
            patch.object(auto.kit_win, 'resume_pids', side_effect=self.resume),
            patch.object(self.copy, '_private_process_token', side_effect=lambda pid: self.tokens.get(pid)),
        ):
            item.start()
            self.addCleanup(item.stop)

    def suspend(self, pids):
        self.suspended.append(list(pids))
        return list(pids)

    def resume(self, pids):
        self.resumed.append(list(pids))
        return list(pids)

    def cached_reset(self):
        self.copy.cached_selector = Mock(return_value=True)
        self.copy.watcher = Mock(return_value={'state': 'ACTIVE'})
        self.copy.restore_selector = Mock()
        self.copy.sleep = Mock()
        self.copy.check = Mock()
        self.copy.loading_speed = Mock()

    def test_committed_conversion_parks_without_thread_or_false_warm_claim(self):
        with patch.object(auto.threading, 'Thread', side_effect=AssertionError('reset steals delivery CPU')):
            self.copy.schedule_reset(deferred=True)
        self.assertTrue(self.copy.reset_deferred)
        self.assertEqual(self.copy.state, 'resetting')
        self.assertEqual(self.copy.suspended, [124, 123])
        self.assertIsNone(self.copy.reset_thread)

    def test_reset_resumes_then_waits_for_active_before_restoring_selector(self):
        self.cached_reset()
        self.copy.schedule_reset(deferred=True)
        self.copy.watcher.reset_mock()
        self.copy.watcher.side_effect = [{'state': 'PREPARING'}, {'state': 'ACTIVE'}]
        events = []
        self.copy.restore_selector.side_effect = lambda _: events.append(('restore', len(self.resumed)))
        self.copy.suspend = Mock()
        self.assertEqual(self.copy.finish_deferred_reset(), 'warm')
        self.assertEqual(self.copy.watcher.call_count, 2)
        self.assertEqual(events, [('restore', 1)])
        self.copy.suspend.assert_called_once()
        self.assertIsNone(self.copy.reset_token)
        self.assertFalse(self.copy.reset_deferred)
        self.assertEqual(self.copy.loading_speed.call_args_list[0].args, (True,))
        self.assertEqual(self.copy.loading_speed.call_args_list[-1].args, (False,))

    def test_next_owner_can_consume_same_pending_token_exactly_once(self):
        self.cached_reset()
        self.copy.schedule_reset(deferred=True)
        with self.copy.lock:
            self.copy._finish_pending_reset()
            self.copy._finish_pending_reset()
        self.copy.restore_selector.assert_called_once()
        self.assertEqual(len(self.resumed), 1)

    def test_close_invalidates_pending_reset_and_resumes_before_killing_owned_tree(self):
        self.copy.loading_speed = Mock()
        self.copy.schedule_reset(deferred=True)
        self.copy.close()
        self.assertIsNone(self.copy.reset_token)
        self.assertFalse(self.copy.reset_deferred)
        self.assertEqual(self.resumed, [[124, 123]])
        self.copy.base.close.assert_called_once()
        self.assertEqual(self.copy.state, 'cold')
        self.assertFalse(self.copy.suspended)

    def test_replaced_pid_identity_never_receives_resume_or_selector_writes(self):
        self.cached_reset()
        self.copy.schedule_reset(deferred=True)
        self.tokens[123] = ('windows', 'unrelated-reused-pid', 100)
        self.copy.finish_deferred_reset()
        self.copy.restore_selector.assert_not_called()
        self.assertEqual(self.resumed, [[124]])
        self.assertEqual(self.copy.state, 'cold')
        self.assertIsNone(self.copy.reset_token)

    def test_foreign_listener_never_receives_suspend(self):
        self.listener = 900
        self.copy.schedule_reset(deferred=True)
        self.assertFalse(self.suspended)
        self.assertFalse(self.copy.reset_deferred)
        self.assertIsNone(self.copy.reset_token)
        self.assertEqual(self.copy.state, 'cold')

    def test_owner_change_during_suspend_resumes_only_original_processes(self):
        def suspend(pids):
            self.listener = 900
            return list(pids)
        with patch.object(auto.kit_win, 'suspend_pids', side_effect=suspend):
            self.copy.schedule_reset(deferred=True)
        self.assertEqual(self.resumed, [[124, 123]])
        self.assertFalse(self.copy.reset_deferred)
        self.assertIsNone(self.copy.reset_token)

    def test_partial_suspend_falls_back_to_existing_automatic_reset(self):
        with patch.object(auto.kit_win, 'suspend_pids', return_value=[123]), \
                patch.object(auto.threading, 'Thread') as thread:
            self.copy.schedule_reset(deferred=True)
        self.assertEqual(self.resumed, [[123]])
        self.assertFalse(self.copy.reset_deferred)
        thread.return_value.start.assert_called_once()

    def test_standalone_and_prebuild_reset_defaults_still_start_worker(self):
        with patch.object(auto.threading, 'Thread') as thread:
            self.copy.schedule_reset()
        self.assertFalse(self.suspended)
        thread.return_value.start.assert_called_once()

    def test_failed_resume_cannot_restore_or_publish_warm_state(self):
        self.cached_reset()
        self.copy.schedule_reset(deferred=True)
        with patch.object(auto.kit_win, 'resume_pids', return_value=[]):
            self.copy.finish_deferred_reset()
        self.copy.restore_selector.assert_not_called()
        self.copy.base.close.assert_called_once()
        self.assertEqual(self.copy.state, 'cold')
        self.assertFalse(self.copy.suspended)

    def test_failed_watcher_does_not_bypass_active_guard(self):
        self.cached_reset()
        self.copy.schedule_reset(deferred=True)
        self.copy.watcher.side_effect = [{'state': 'FAILED'}]
        self.copy.finish_deferred_reset()
        self.copy.restore_selector.assert_not_called()
        self.copy.base.close.assert_called_once()
        self.assertEqual(self.copy.state, 'cold')
        self.assertEqual(self.copy.loading_speed.call_args_list[-1].args, (False,))

    def test_preparing_worker_is_deferred_but_never_os_suspended(self):
        self.copy.watcher.return_value = {'state': 'PREPARING'}
        with patch.object(auto.threading, 'Thread', side_effect=AssertionError('deferred reset must not run')):
            self.copy.schedule_reset(deferred=True)
        self.assertTrue(self.copy.reset_deferred)
        self.assertEqual(self.copy.state, 'resetting')
        self.assertIsNotNone(self.copy.reset_token)
        self.assertIsNone(self.copy.reset_thread)
        self.assertFalse(self.suspended)
        self.assertFalse(self.copy.suspended)
        self.assertFalse(self.copy.fast_loading)
        self.assertEqual(self.copy.reset_owner['tokens'], self.tokens)

    def test_unfinished_worker_completes_before_selector_restore_without_resume(self):
        self.cached_reset()
        self.copy.watcher.return_value = {'state': 'PREPARING'}
        self.copy.schedule_reset(deferred=True)
        self.copy.watcher.side_effect = [{'state': 'PREPARING'}, {'state': 'ACTIVE'}]
        self.copy.suspend = Mock()
        events=[]
        self.copy.restore_selector.side_effect=lambda _:events.append(('restore',len(self.resumed)))
        self.assertEqual(self.copy.finish_deferred_reset(),'warm')
        self.assertEqual(events,[('restore',0)])
        self.assertFalse(self.suspended)
        self.copy.suspend.assert_called_once()
        self.assertIsNone(self.copy.reset_token)
        self.assertFalse(self.copy.reset_deferred)

    def test_only_explicit_active_state_can_suspend_private_tree(self):
        for state in ({}, {'state':'PREPARING'}, {'state':'FAILED'}, {'state':'MENU'}):
            with self.subTest(state=state),patch.object(auto.threading,'Thread',side_effect=AssertionError('no reset worker')):
                self.copy.watcher.return_value=state
                self.copy.schedule_reset(deferred=True)
                self.assertTrue(self.copy.reset_deferred)
                self.assertFalse(self.suspended)

    def test_owner_replaced_while_reading_worker_state_receives_no_suspend(self):
        def status():
            self.listener=900
            return {'state':'ACTIVE'}
        self.copy.watcher.side_effect=status
        self.copy.schedule_reset(deferred=True)
        self.assertFalse(self.suspended)
        self.assertFalse(self.copy.reset_deferred)
        self.assertIsNone(self.copy.reset_token)
        self.assertEqual(self.copy.state,'cold')

    def test_unparked_preparing_owner_replaced_before_finish_gets_no_native_writes(self):
        self.cached_reset()
        self.copy.watcher.return_value={'state':'PREPARING'}
        self.copy.schedule_reset(deferred=True)
        self.tokens[123]=('replacement',123)
        self.copy.finish_deferred_reset()
        self.copy.restore_selector.assert_not_called()
        self.assertFalse(self.suspended)
        self.assertFalse(self.resumed)
        self.assertEqual(self.copy.state,'cold')

    def test_close_invalidates_running_preparation_reset_without_resume(self):
        self.copy.watcher.return_value={'state':'PREPARING'}
        self.copy.loading_speed=Mock()
        self.copy.schedule_reset(deferred=True)
        self.copy.close()
        self.assertFalse(self.resumed)
        self.assertFalse(self.suspended)
        self.assertIsNone(self.copy.reset_token)
        self.assertIsNone(self.copy.reset_owner)
        self.assertFalse(self.copy.reset_deferred)
        self.copy.base.close.assert_called_once()

    def test_cancellation_before_unfinished_worker_active_cannot_restore_or_suspend(self):
        self.cached_reset()
        self.copy.watcher.return_value={'state':'PREPARING'}
        self.copy.schedule_reset(deferred=True)
        self.copy.check.side_effect=auto.Cancelled()
        self.copy.suspend=Mock()
        self.assertEqual(self.copy.finish_deferred_reset(),'cold')
        self.copy.restore_selector.assert_not_called()
        self.copy.suspend.assert_not_called()
        self.assertFalse(self.resumed)
        self.assertIsNone(self.copy.reset_token)
        self.assertFalse(self.copy.reset_deferred)

    def prepared_copy(self):
        copy = self.copy
        copy.at_map_select = Mock(return_value=True)
        copy.check = copy.loading_speed = Mock()
        copy.newest_checkpoint = Mock(return_value=None)
        copy.write_settings = copy.write_native = copy.confirm = Mock()
        source = copy.run_dir / 'capture-source.p2s'
        source.write_bytes(b'archive verified by mocked converter')
        copy.wait_for_checkpoint = Mock(return_value=source)
        return copy

    def test_prepare_parks_only_after_successful_archive_conversion(self):
        copy = self.prepared_copy()
        phases = []
        def converted(*args, **kwargs):
            phases.append('convert verified')
            self.assertFalse(copy.reset_deferred)
            self.assertFalse(self.suspended)
            return {'verify_sha': 'validated'}
        with patch.object(auto.kit_win, 'pid_alive', return_value=True), \
                patch.object(auto.kit_spec, 'engine_mode', return_value='teams'), \
                patch.object(auto.kit_spec, 'spec_sha', return_value='a' * 64), \
                patch.object(auto.kit_prepare, 'convert', side_effect=converted), \
                patch.object(auto.threading, 'Thread', side_effect=AssertionError('committed reset should wait')):
            result = copy.prepare({}, copy.run_dir / 'match', deferred_reset=True)
        self.assertEqual(phases, ['convert verified'])
        self.assertEqual(result['copy_after'], 'resetting')
        self.assertTrue(copy.reset_deferred)
        self.assertEqual(self.suspended, [[124, 123]])

    def test_invalid_conversion_uses_recovery_without_parking_delivery(self):
        copy = self.prepared_copy()
        with patch.object(auto.kit_win, 'pid_alive', return_value=True), \
                patch.object(auto.kit_spec, 'engine_mode', return_value='teams'), \
                patch.object(auto.kit_spec, 'spec_sha', return_value='a' * 64), \
                patch.object(auto.kit_prepare, 'convert', side_effect=ValueError('wrong archive')), \
                patch.object(auto.threading, 'Thread') as thread:
            with self.assertRaisesRegex(ValueError, 'wrong archive'):
                copy.prepare({}, copy.run_dir / 'match', deferred_reset=True)
        self.assertFalse(self.suspended)
        self.assertFalse(copy.reset_deferred)
        thread.return_value.start.assert_called_once()

    def test_committed_prepare_passes_deferred_mode_without_mutating_controls(self):
        controls = {'delay': 3, 'max_stall': 9000}
        prep = SimpleNamespace(lock=threading.RLock(), cancel=threading.Event())
        session = SimpleNamespace(prep_gen=4, _prepare_locked=Mock(return_value={'verified': True}))
        result = kit_fight.FightMixin.prepare_job(session, prep, 4, {}, Path('.'), None, 'test', controls)
        self.assertEqual(result, {'verified': True})
        self.assertEqual(session._prepare_locked.call_args.kwargs,
                         {'controls': controls, 'deferred_reset': True})


class ResetCoordinator(unittest.TestCase):
    def controller(self, phase, interactive=None):
        prep = SimpleNamespace(reset_deferred=True, state='resetting', finish_deferred_reset=Mock())
        session = SimpleNamespace(role='host', prep=prep, phase=phase, session=SimpleNamespace(interactive=interactive),
            prefetch_meta=None, prep_progress=None, prep_sent=None, jobs=[], busy=lambda _: False,
            rewarm_if_cold=Mock(), tick_engine=Mock(), tick_prebuild=Mock(), tick_prefetch=Mock(), sync_warm=Mock())
        session.job = lambda *a, **k: session.jobs.append((a, k))
        return session

    def test_transfer_load_and_intro_never_resume_deferred_builder(self):
        for phase in ('preparing', 'sending', 'loading', 'fight'):
            with self.subTest(phase=phase):
                session = self.controller(phase)
                kit_controller.Controller.tick_prep(session)
                self.assertFalse(session.jobs)

    def test_interactive_lobby_or_results_can_consume_reset_without_duplicate_jobs(self):
        for phase, interactive in (('lobby', None), ('results', None), ('fight', {'clock': 50})):
            with self.subTest(phase=phase):
                session = self.controller(phase, interactive)
                kit_controller.Controller.tick_prep(session)
                self.assertEqual(session.jobs[0][0], ('reset', session.prep.finish_deferred_reset))
                session.busy = lambda name: name == 'reset'
                kit_controller.Controller.tick_prep(session)
                self.assertEqual(len(session.jobs), 1)

    def test_stale_reset_completion_does_not_update_replacement_worker(self):
        session = self.controller('lobby')
        kit_controller.Controller.tick_prep(session)
        callback = session.jobs[0][1]['then']
        session.prep = None
        session.sync_warm.reset_mock()
        callback('warm')
        session.sync_warm.assert_not_called()


if __name__ == '__main__':
    unittest.main()
