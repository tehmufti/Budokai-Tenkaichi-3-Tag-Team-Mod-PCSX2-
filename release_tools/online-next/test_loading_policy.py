"""Start-barrier regressions: failed clients, host authority and synchronized CPU handoff."""
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'bt3-multifighter/online/netplay'))
import kit_controller as controller
import kit_fight as fight
import kit_lobby
import kit_lobby_console
import kit_lockstep
import kit_prepare
import kit_verify
import netplay_core as nc
import team_start_gate as gate


def host(drop=False):
    h = controller.Controller.__new__(controller.Controller)
    h.init_fight(); h.init_hub()
    h.role, h.me, h.phase, h.epoch = 'host', 1, 'loading', 7
    h.cfg = {}; h.lobby = kit_lobby.Lobby()
    for name in ('Loaded', 'Slow', 'Slower'):
        h.lobby.join(name)
    h.members = {k: dict(channel=Mock()) for k in (2, 3, 4)}
    h.udp = Mock()
    h.loaded = {2}; h.my_loaded = True; h.load_started = fight.now(); h.run_dir = Path('unused-test-run')
    h.match = dict(seats={1: 0, 2: 1, 3: 2, 4: 3}, spec=dict(type='versus'), drop_load_failures=drop)
    h.lobby.phase = 'loading'
    h.sent = []; h.send_to = lambda k, **m: h.sent.append((k, m))
    h.say = Mock(); h.broadcast = Mock(); h.on_go = Mock(); h.prep_failed = Mock()
    return h


class LoadingPolicy(unittest.TestCase):
    def test_default_cancels_without_removing_players(self):
        h = host()
        h.load_started = 0.0
        with patch.object(fight, 'now', return_value=121): h.check_go()
        h.prep_failed.assert_called_once()
        self.assertFalse(h.go); self.assertEqual(set(h.members), {2, 3, 4})

    def test_enabled_waits_until_deadline(self):
        h = host(True)
        h.load_started = 0.0
        with patch.object(fight, 'now', return_value=119): h.check_go()
        self.assertFalse(h.go); h.on_go.assert_not_called()
        self.assertEqual(set(h.members), {2, 3, 4})

    def test_timeout_drops_entire_batch_then_starts_once(self):
        h = host(True)
        h.load_started = 0.0
        def started():
            self.assertEqual(set(h.members), {2})
            self.assertEqual(set(h.lobby.members), {1, 2})
        h.on_go.side_effect = started
        with patch.object(fight, 'now', return_value=120): h.check_go()
        self.assertTrue(h.go); h.on_go.assert_called_once(); h.prep_failed.assert_not_called()
        self.assertEqual([(k, m['type']) for k, m in h.sent], [(3, 'BYE'), (4, 'BYE'), (2, 'GO')])
        # Seats stay in the checkpoint's mapping for synchronized CPU conversion.
        self.assertEqual(h.match['seats'][3], 2)

    def test_host_must_load_before_any_start(self):
        h = host(True); h.my_loaded = False
        with patch.object(fight, 'now', return_value=500): h.check_go()
        self.assertFalse(h.go); h.on_go.assert_not_called()
        self.assertEqual(set(h.members), {2, 3, 4})

    def test_explicit_failure_drops_only_failed_guest(self):
        h = host(True)
        h.msg_LOAD_FAILED(3, dict(epoch=7, why='failed'))
        self.assertEqual(set(h.members), {2, 4}); self.assertFalse(h.go)
        h.msg_LOADED(4, dict(epoch=7))
        self.assertTrue(h.go); h.on_go.assert_called_once()

    def test_explicit_failure_default_aborts(self):
        h = host(); h.msg_LOAD_FAILED(3, dict(epoch=7, why='failed'))
        h.prep_failed.assert_called_once(); self.assertIn(3, h.members)

    def test_stale_load_failure_and_removed_loaded_are_ignored(self):
        h = host(True)
        h.msg_LOAD_FAILED(3, dict(epoch=6, why='previous match failed'))
        self.assertIn(3, h.members)
        h.msg_LOAD_FAILED(3, dict(epoch=7, why='failed'))
        h.msg_LOADED(3, dict(epoch=7))
        self.assertNotIn(3, h.loaded)

    def test_bad_match_file_obeys_policy(self):
        h = host(True); h.msg_GOT(3, dict(ok=False, why='checksum mismatch'))
        self.assertNotIn(3, h.members); h.prep_failed.assert_not_called()

    def test_policy_is_host_only_and_cannot_change_during_start(self):
        h = host(); h.save_settings = Mock()
        h.cmd_load_policy(dict(drop=True)); self.assertNotIn('drop_load_failures', h.cfg)
        h.lobby.phase = 'lobby'
        h.role = 'guest'; h.cmd_load_policy(dict(drop=True)); self.assertNotIn('drop_load_failures', h.cfg)
        h.role = 'host'; h.cmd_load_policy(dict(drop='true')); self.assertNotIn('drop_load_failures', h.cfg)
        h.cmd_load_policy(dict(drop=True))
        self.assertTrue(h.cfg['drop_load_failures']); h.save_settings.assert_called_once()
        guest = kit_lobby.Lobby.from_snapshot(h.lobby.snapshot())
        self.assertTrue(guest.room['drop_load_failures'])

    def test_console_policy_and_invalid_input(self):
        self.assertEqual(kit_lobby_console.command('loadpolicy drop', {}), ('load_policy', dict(drop=True)))
        self.assertEqual(kit_lobby_console.command('loadpolicy cancel', {}), ('load_policy', dict(drop=False)))
        self.assertEqual(kit_lobby_console.command('loadpolicy wat', {})[0], 'local')

    def test_guest_load_failure_includes_epoch(self):
        h = host(); h.role = 'guest'; h.send = Mock(); h.fail = Mock()
        h.stop_receive = Mock(); h.set_phase = Mock(); h.load_failed(RuntimeError('failed'))
        self.assertEqual(h.send.call_args.kwargs['epoch'], 7)
        h.set_phase.assert_called_once_with('lobby')

    def test_host_load_failure_always_aborts(self):
        h = host(True); h.fail = Mock()
        h.load_failed(RuntimeError('host emulator failed'))
        h.prep_failed.assert_called_once(); self.assertFalse(h.go)

    def test_missing_player_cpu_writes_are_frame_scheduled(self):
        h = host(True); h.summary = {}; h.link = Mock(); h.link.read.return_value = struct.pack('<I', 0x200000)
        h.session = SimpleNamespace(sched_on=True, schedule=Mock(return_value=(0, 6)))
        h.start_cpu_pending = [3]
        h.start_missing_cpus()
        writes = h.session.schedule.call_args.args[0]
        self.assertIn((0x200000 + 0x1278, 1, 0xFFFFFFFF), writes)
        self.assertIn((nc.CONTROL + nc.F['mask'], 0, 1 << 2), writes)
        self.assertIn((nc.SEAT_CONTROL + nc.SF['seats'] + 4*2, nc.NO_SLOT, 0xFFFFFFFF), writes)
        self.assertIn((gate.CONTROL + 0x40 + 4*2, 1, 0xFFFFFFFF), writes)
        self.assertEqual(h.start_cpu_pending, [])
        h.start_missing_cpus(); h.session.schedule.assert_called_once()

    def test_missing_side_leader_also_closes_human_port(self):
        h = host(True); h.summary = {}; h.link = Mock(); h.link.read.return_value = struct.pack('<I', 0x200000)
        h.session = SimpleNamespace(sched_on=True, schedule=Mock(return_value=(0, 6)))
        self.assertTrue(h.drop_to_cpu(2))
        self.assertIn((kit_prepare.SPECTATOR + kit_prepare.HUMAN_PORTS, 0, 2), h.session.schedule.call_args.args[0])

    def test_invalid_actor_does_not_silently_start_with_idle_fighter(self):
        h = host(True); h.summary = {}; h.link = Mock(); h.link.read.return_value = b'\0'*4
        h.session = SimpleNamespace(sched_on=True, schedule=Mock()); h.end_fight = Mock(); h.start_cpu_pending = [3]
        with self.assertRaises(controller.KitError): h.start_missing_cpus()
        h.session.schedule.assert_not_called(); h.end_fight.assert_called_once_with('error', mine=True)

    def test_every_rematch_reapplies_missing_seat_handoff(self):
        h = host(True); h.members = {2: dict(channel=Mock())}; h.run_dir = Path(tempfile.mkdtemp(prefix='ttm-start-test-'))
        h.match.update(mask=15, delay=2, sha='a'*64, slot=0, title='Test', spec_sha='b'*64); h.my_name = lambda: 'Host'
        h.link = Mock(); h.udp = Mock()
        try:
            for late in (False, True):
                with patch.object(kit_lockstep, 'Hub') as hub:
                    h.new_session(late)
                    self.assertEqual(h.start_cpu_pending, [3, 4])
                    self.assertEqual(hub.return_value.drop_slot.call_count, 2)
                for f in h.files.values(): f.close()
        finally:
            import shutil
            for f in h.files.values(): f.close()
            self.assertEqual(h.run_dir.parent.resolve(), Path(tempfile.gettempdir()).resolve())
            self.assertTrue(h.run_dir.name.startswith('ttm-start-test-'))
            shutil.rmtree(h.run_dir)


if __name__ == '__main__': unittest.main()
