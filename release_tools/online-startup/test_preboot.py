"""Lobby VM ownership and cancellation; no real emulator is opened."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bt3-multifighter/online/netplay'))
import kit_controller
import kit_emu


def controller(phase='loading', match=True):
    c = kit_controller.Controller.__new__(kit_controller.Controller)
    c.emulator = SimpleNamespace(alive=Mock(return_value=False), install_pnach=Mock(), stop=Mock(), pid=44,
                                launch_idle=Mock(return_value=44), wait_idle=Mock(return_value={}),
                                minimise=Mock(), pine_owner=Mock(return_value=44))
    c.job = Mock()
    c.busy = Mock(return_value=False)
    c.load_match = Mock()
    c.say = Mock()
    c.link = None
    c.quit = False
    c.role = 'host'
    c.local = {'iso': 'own-disc.iso'}
    c.preboot_lock = threading.Lock()
    c.preboot_owner = None
    c.args = SimpleNamespace(pine_slot=28460)
    c.remember_pid = Mock()
    c.pending_preboot_load = True
    c.phase, c.match = phase, {'sha': 'validated'} if match else None
    return c


def owned(c, *, pid=44, link=None):
    owner = dict(emulator=c.emulator, local=c.local, role=c.role, cancel=threading.Event(),
                 pid=pid, link=link, stopped=False)
    c.preboot_owner = owner
    return owner


class PrebootTests(unittest.TestCase):
    def test_idle_vm_does_not_launch_a_fight(self):
        c = controller()
        with patch.object(kit_controller.os, 'name', 'nt'), patch.object(kit_controller.kit_paths, 'INTEGRATED', True), \
                patch.object(kit_controller.kit_install, 'installation_pnach', return_value='verified-patch'):
            c.preboot_game()
        c.emulator.install_pnach.assert_called_once_with('verified-patch')
        self.assertEqual(c.job.call_args.args[0], 'preboot')
        c.load_match.assert_not_called()

    def test_linux_keeps_statefile_startup(self):
        c = controller()
        with patch.object(kit_controller.os, 'name', 'posix'):
            c.preboot_game()
        c.job.assert_not_called()

    def test_match_waiting_for_vm_continues(self):
        c = controller()
        link = object()
        owner = owned(c, link=link)
        c.preboot_game_ready({'link': link}, owner)
        self.assertIs(c.link, link)
        c.load_match.assert_called_once()
        self.assertFalse(c.pending_preboot_load)

    def test_cancelled_match_is_not_started_by_late_callback(self):
        c = controller(phase='lobby', match=False)
        owner = owned(c, link=object())
        c.preboot_game_ready({'link': owner['link']}, owner)
        c.load_match.assert_not_called()
        self.assertFalse(c.pending_preboot_load)

    def test_failure_uses_normal_start_after_stopping_owned_vm(self):
        c = controller()
        c.preboot_game_failed(RuntimeError('failed init'), owned(c))
        c.emulator.stop.assert_called_once()
        c.load_match.assert_called_once()
        self.assertIsNone(c.link)

    def test_failure_after_cancel_does_not_load(self):
        c = controller(phase='lobby', match=False)
        c.preboot_game_failed(RuntimeError('failed init'), owned(c))
        c.load_match.assert_not_called()

    def test_busy_preboot_defers_match_load(self):
        c = kit_controller.Controller.__new__(kit_controller.Controller)
        c.busy = Mock(return_value=True)
        c.load_match()
        self.assertTrue(c.pending_preboot_load)
        self.assertEqual(c.progress['step'], 'load.starting')

    def test_idle_launch_has_no_statefile_and_owns_pid(self):
        em = kit_emu.Emulator(root=Path('owned-runtime'), run_dir=Path('owned-run'))
        with patch.object(kit_emu.kit_win, 'listener_pid', return_value=None), \
                patch.object(kit_emu.kit_win, 'launch', return_value=44) as launch, \
                patch.object(kit_emu.kit_win, 'kill_with_me', return_value='owned'):
            em.launch_idle('own-disc.iso')
        self.assertEqual(em.pid, 44)
        self.assertNotIn('-statefile', launch.call_args.args[0])
        self.assertEqual(launch.call_args.args[0][-1], 'own-disc.iso')

    def test_stale_success_cannot_replace_new_rooms_link(self):
        c = controller()
        old_em, old_link = c.emulator, Mock()
        owner = owned(c, link=old_link)
        c.emulator = SimpleNamespace(pid=77, stop=Mock())
        c.local = {'iso': 'new-room.iso'}
        current_link = c.link = object()
        c.preboot_game_ready({'link': old_link}, owner)
        self.assertIs(c.link, current_link)
        c.load_match.assert_not_called()
        old_link.close.assert_called_once()
        old_em.stop.assert_called_once()
        c.emulator.stop.assert_not_called()

    def test_stale_failure_stops_only_captured_vm(self):
        c = controller()
        old_em = c.emulator
        owner = owned(c)
        c.emulator = SimpleNamespace(pid=77, stop=Mock())
        c.local = {'iso': 'new-room.iso'}
        current_link = c.link = object()
        c.preboot_game_failed(RuntimeError('old init failed'), owner)
        self.assertIs(c.link, current_link)
        c.load_match.assert_not_called()
        old_em.stop.assert_called_once()
        c.emulator.stop.assert_not_called()

    def test_cancelled_job_cannot_launch_after_shutdown_cleanup(self):
        c = controller()
        owner = owned(c, pid=None)
        c.invalidate_preboot()
        c.quit = True
        result = c.preboot_game_job(owner)
        self.assertTrue(result['cancelled'])
        c.emulator.launch_idle.assert_not_called()
        c.emulator.wait_idle.assert_not_called()

    def test_cancellation_waits_for_short_launch_and_stops_its_pid(self):
        c = controller()
        owner = owned(c, pid=None)
        entered, release = threading.Event(), threading.Event()

        def launch(_iso):
            entered.set()
            self.assertTrue(release.wait(2))
            return 44

        c.emulator.launch_idle.side_effect = launch
        # Leave is waiting behind the launch lock. After launch records its PID,
        # cancellation must close that VM, not miss a late-created process.
        failure = []
        c.emulator.wait_idle.side_effect = RuntimeError('stopped')

        def worker():
            try:
                c.preboot_game_job(owner)
            except RuntimeError as error:
                failure.append(error)

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()
        self.assertTrue(entered.wait(2))
        cancel_thread = threading.Thread(target=c.invalidate_preboot)
        cancel_thread.start()
        release.set()
        worker_thread.join(2)
        cancel_thread.join(2)
        self.assertFalse(worker_thread.is_alive())
        self.assertFalse(cancel_thread.is_alive())
        self.assertTrue(owner['cancel'].is_set())
        c.emulator.stop.assert_called_once()

    def test_stale_record_never_stops_reused_emulator_pid(self):
        c = controller()
        owner = owned(c)
        c.emulator.pid = 99
        c.dispose_preboot(owner)
        c.emulator.stop.assert_not_called()

    def test_cancel_during_connect_closes_late_link(self):
        c = controller()
        owner = owned(c, pid=None)
        late_link = Mock()

        def connect():
            c.invalidate_preboot()
            return late_link

        with patch('pinelink.PineLink') as link_type, \
                patch.object(kit_controller.kit_ident, 'runtime_problems', return_value=[]):
            link_type.return_value.connect.side_effect = connect
            result = c.preboot_game_job(owner)
        self.assertTrue(result['cancelled'])
        late_link.close.assert_called_once()
        c.emulator.stop.assert_called_once()
        self.assertIsNone(c.link)
        c.emulator.minimise.assert_not_called()

    def test_shutdown_refuses_a_new_preboot_job(self):
        c = controller()
        c.quit = True
        with patch.object(kit_controller.os, 'name', 'nt'), patch.object(kit_controller.kit_paths, 'INTEGRATED', True), \
                patch.object(kit_controller.kit_install, 'installation_pnach', return_value='verified-patch'):
            c.preboot_game()
        c.job.assert_not_called()
        c.emulator.install_pnach.assert_not_called()


if __name__ == '__main__':
    unittest.main()
