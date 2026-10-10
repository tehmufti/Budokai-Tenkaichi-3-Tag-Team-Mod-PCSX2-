"""Nominal menu and accelerated private resource-loading guards; no emulator is opened."""
import configparser
from pathlib import Path
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_prepare as prepare
import kit_prepare_auto as auto


class CopyFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.copy = auto.PrepCopy.__new__(auto.PrepCopy)
        c = self.copy
        c.base = SimpleNamespace(dest=self.root, pid=123, cmd_pid=124, desktop='private-test', close=Mock())
        c.run_dir, c.state, c.engine = self.root, 'warm', 'teams'
        c.lock, c.cancel = threading.RLock(), threading.Event()
        c.reset_token = c.reset_thread = c.reset_owner = None
        c.reset_running = c.reset_deferred = c.warming = False
        c.suspended, c.suspended_tokens = [], {}
        c.selector_cache = c.selector_identity = c.selector_lease = c.selector_boot = None
        c.export_owner = c.held_export = None
        c.fast_loading = False
        c.check = c.progress = c.event = c.say = c.sleep = Mock()
        c.cache_selector = Mock()
        c.capture_shots = c.test = False
        self.events = []
        c.loading_speed = self.speed
        self.pid = patch.object(auto.kit_win, 'pid_alive', return_value=True)
        self.pid.start()
        self.addCleanup(self.pid.stop)

    def speed(self, enabled):
        self.copy.fast_loading = bool(enabled)
        self.events.append(('speed', bool(enabled)))

    def assert_nominal(self, name):
        self.assertFalse(self.copy.fast_loading)
        self.events.append(name)

    def launch(self, cached=False):
        self.copy.base.pid = 123
        self.events.append(('launch', cached))

    def warm(self, cached):
        c = self.copy
        c.base.pid = None
        c.make_copy = Mock()
        c.cached_selector = Mock(return_value=cached)
        c.launch = self.launch
        c.at_map_select = Mock(return_value=cached)
        c.boot = lambda: self.assert_nominal('boot')
        c.commit_mode = lambda: self.assert_nominal('commit')
        c.native_picks = lambda: self.assert_nominal('picks')

class SpeedTests(CopyFixture, unittest.TestCase):
    def test_normal_boot_mode_and_picks_never_enable_turbo(self):
        self.warm(cached=False)
        self.assertEqual(self.copy.warm(), 'warm')
        self.assertNotIn(('speed', True), self.events)
        self.assertEqual([e for e in self.events if isinstance(e, str)], ['boot', 'commit', 'picks'])
        self.assertFalse(self.copy.fast_loading)

    def test_cached_warm_accelerates_restore_then_releases_presentation(self):
        self.warm(cached=True)
        def restore(engine):
            self.assertTrue(self.copy.fast_loading)
            self.events.append(('restore', engine))
        self.copy.restore_selector = restore
        self.assertEqual(self.copy.warm(), 'warm')
        self.assertEqual(self.events, [('launch', True), ('speed', True), ('restore', 'teams'), ('speed', False)])

    def test_rejected_cached_restore_falls_back_to_nominal_boot(self):
        self.warm(cached=True)
        self.copy.restore_selector = Mock(side_effect=ValueError('invalid authenticated selector'))
        self.copy.at_map_select = Mock(return_value=False)
        self.assertEqual(self.copy.warm(), 'warm')
        self.assertEqual([e for e in self.events if isinstance(e, str)], ['boot', 'commit', 'picks'])
        false_launch = self.events.index(('launch', False))
        self.assertNotIn(('speed', True), self.events[false_launch:])
        self.assertFalse(self.copy.fast_loading)

    def test_cached_restore_failure_releases_turbo_on_close(self):
        self.warm(cached=True)
        self.copy.restore_selector = Mock(side_effect=auto.Cancelled())
        with self.assertRaises(auto.Cancelled):
            self.copy.warm()
        self.assertFalse(self.copy.fast_loading)
        self.copy.base.close.assert_called_once()

    def test_boot_itself_releases_lingering_turbo(self):
        self.copy.fast_loading = True
        self.copy.sample = Mock(return_value=dict(scene=auto.MAIN_MENU, pager=True))
        self.copy.boot()
        self.assertEqual(self.events[0], ('speed', False))

    def test_native_picks_itself_releases_turbo_even_for_finished_selector(self):
        self.copy.fast_loading = True
        self.copy.at_map_select = Mock(return_value=True)
        self.copy.keys = Mock(side_effect=AssertionError('finished selector must not receive an input'))
        self.copy.native_picks()
        self.assertEqual(self.events, [('speed', False)])

    def test_native_mode_all_inputs_are_nominal(self):
        c = self.copy
        c.fast_loading = True
        c.wait = Mock(side_effect=[dict(scene=auto.MAIN_MENU, pager=True, pager_state=2, pager_page=0),
                                   dict(scene=auto.TEAM_SELECT, loop=0)])
        c.watcher = Mock(return_value=dict(battle_mode='teams', humans=1))
        c.pine = Mock(return_value=SimpleNamespace(__enter__=None))
        class Context:
            def __enter__(self): return self
            def __exit__(self, *_): pass
        c.pine = Mock(return_value=Context())
        def word(_, addr):
            return {auto.MAIN_OBJECT: 1000, 1000 + 0x144: 2, auto.PAGER + 20: 1000,
                    1000 + 0x148: 0, 1000 + 0x10C: 1}.get(addr, 0)
        c.keys = lambda buttons, gap: self.assert_nominal(tuple(buttons))
        with patch.object(auto, 'u32', side_effect=word):
            c.commit_mode()
        self.assertFalse(c.fast_loading)

    def test_non_cached_engine_switch_menus_are_nominal(self):
        c = self.copy
        c.fast_loading = True
        c.cached_selector = Mock(return_value=False)
        c.sample = Mock(side_effect=[dict(scene=auto.TEAM_SELECT), dict(scene=auto.MAIN_MENU, pager=True)])
        c.keys = lambda buttons, gap: self.assert_nominal(tuple(buttons))
        c.commit_mode = lambda: self.assert_nominal('commit')
        c.native_picks = lambda: self.assert_nominal('picks')
        self.assertEqual(c.switch_engine('ffa'), 'warm')
        self.assertNotIn(('speed', True), self.events)
        self.assertFalse(c.fast_loading)

    def test_cached_engine_switch_accelerates_restore_only(self):
        c = self.copy
        c.cached_selector = c.at_map_select = Mock(return_value=True)
        def restore(_): self.assertTrue(c.fast_loading)
        c.restore_selector = restore
        self.assertEqual(c.switch_engine('ffa'), 'warm')
        self.assertEqual(self.events, [('speed', True), ('speed', False)])

    def test_return_to_select_uses_nominal_menu_inputs(self):
        c = self.copy
        c.fast_loading = True
        c.keys = lambda buttons, gap: self.assert_nominal(tuple(buttons))
        c.sample = Mock(return_value=dict(scene=auto.TEAM_SELECT, loop=0))
        c.watcher = Mock(return_value=dict(log=['Back at character selection']))
        c.return_to_select()
        self.assertFalse(c.fast_loading)

    def test_cached_reset_waits_for_active_at_fast_rate_then_releases_it(self):
        c = self.copy
        c.reset_token = object()
        c.resume = Mock(return_value=True)
        c.cached_selector = Mock(return_value=True)
        c.watcher = Mock(side_effect=[dict(state='PREPARING'), dict(state='ACTIVE')])
        def restore(_): self.assertTrue(c.fast_loading)
        c.restore_selector = restore
        c._finish_pending_reset()
        self.assertEqual(self.events, [('speed', True), ('speed', False)])
        self.assertIsNone(c.reset_token)

    def test_reset_failure_and_recovery_failure_release_turbo(self):
        c = self.copy
        c.reset_token = object()
        c.resume = Mock(return_value=True)
        c.cached_selector = Mock(return_value=True)
        c.check = Mock(side_effect=ValueError('owner canceled'))
        c._finish_pending_reset()
        self.assertFalse(c.fast_loading)
        c.fast_loading = True
        c.wait_for_fight = Mock(side_effect=ValueError('failed match'))
        c._recover_after_confirm()
        self.assertFalse(c.fast_loading)

    def test_uncached_reset_releases_turbo_before_navigation(self):
        c = self.copy
        c.reset_token = object()
        c.resume = Mock(return_value=True)
        c.cached_selector = Mock(return_value=False)
        c.wait_for_fight = Mock(return_value=dict(clock=1, fighters=2))
        c.keys = lambda buttons, gap: self.assert_nominal(tuple(buttons))
        c.sample = Mock(return_value=dict(scene=auto.TEAM_SELECT, loop=0))
        c.watcher = Mock(return_value=dict(log=['Back at character selection']))
        c.at_map_select = Mock(return_value=True)
        c._finish_pending_reset()
        self.assertFalse(c.fast_loading)
        self.assertIsNone(c.reset_token)


class ConfirmPulse(CopyFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.copy.fast_loading = True
        self.copy.slot = 29990
        self.copy.base.desktop = 'ttm-kit-prep-29990'
        self.token = ('windows', str(self.copy.base.dest/'game/runtime28/pcsx2-qt.exe'), 1, 2)
        self.copy._private_process_token = Mock(return_value=self.token)
        for name,value in (('WINDOWS',True),('listener_pid',Mock(return_value=123)),
                           ('process_path',Mock(return_value=self.token[1])),('kill_tree',Mock())):
            context=patch.object(auto.kit_win,name,value);context.start();self.addCleanup(context.stop)
        self.obj, self.manager = 0x140000, 0x150000
        self.loop, self.clock, self.held, self.ack_after = 0, 0., False, .025
        self.spec = dict(native=dict(time=0), teams=[[dict(character=1, costume=0)], [dict(character=2, costume=0)]],
                         stage=2, bgm=3)
        self.pine = SimpleNamespace(connect=Mock(), close=Mock(), write=Mock())
        self.equipment = {}
        self.pine.read = Mock(side_effect=lambda address,length: self.equipment.get(address,bytes(length)))
        self.copy.pine = Mock(return_value=self.pine)
        self.copy.write_spec = Mock(return_value=self.obj)
        self.inputs = []
        self.words = {auto.TEAM_OBJECT: self.obj, auto.MANAGER: self.manager,
                      self.manager + 0x18: auto.TEAM_SELECT, self.obj + 0x3C6C: 1,
                      auto.SCENE + 0x1C: 2, auto.SCENE + 0x28: 2, auto.SCENE + 0x10: 1,
                      auto.SCENE + 0x0C: 3}
        for side, char in ((0, 1), (1, 2)):
            self.words[auto.SCENE + 0xC0 + 0x270 * side] = 1
            self.words[auto.SCENE + 0xC4 + 0x270 * side] = char

    def word(self, _, addr):
        if addr == auto.LOOP:
            if self.held and self.ack_after is not None and self.clock >= self.ack_after:
                self.loop = 1
            return self.loop
        return self.words.get(addr, 0)

    def input(self, pid, key, down, desktop):
        self.inputs.append((pid, key, down, desktop, self.clock, self.loop))
        self.held = down
        return 1

    def sleep(self, seconds):
        self.clock += seconds
        if self.held and self.ack_after is not None and self.clock >= self.ack_after:
            self.loop = 1

    def confirm(self):
        with patch.object(auto, 'u32', side_effect=self.word), \
                patch.object(auto.kit_win, 'post_key', side_effect=self.input), \
                patch.object(auto.kit_spec, 'scene_time', return_value=1), \
                patch.object(auto.time, 'time', side_effect=lambda: self.clock), \
                patch.object(auto.time, 'sleep', side_effect=self.sleep):
            return self.copy.confirm(self.spec)

    def assert_released(self):
        self.assertEqual([value[2] for value in self.inputs], [True, False])
        self.assertFalse(self.held)
        self.pine.close.assert_called_once()

    def test_delayed_native_pad_poll_acknowledges_while_cross_remains_held(self):
        result=self.confirm()
        self.assert_released()
        self.assertGreater(self.inputs[-1][4],1/120)
        self.assertEqual(self.inputs[-1][5],1)
        self.assertEqual(result['members'], [[[1,0,0]],[[2,0,0]]])

    def test_resumed_reset_delay_uses_one_hold_without_repeat_presses(self):
        for delay in (.05,.4,1.2):
            with self.subTest(delay=delay):
                self.loop,self.clock,self.held,self.ack_after=0,0.,False,delay
                self.inputs=[];self.pine.close.reset_mock()
                self.confirm();self.assert_released()
                self.assertGreaterEqual(self.inputs[-1][4],delay)

    def test_nominal_confirm_retains_original_point_two_second_pulse(self):
        self.copy.fast_loading=False
        self.confirm();self.assert_released()
        self.assertAlmostEqual(self.inputs[-1][4],.2)

    def test_native_ack_rejects_equipment_from_an_old_match(self):
        self.spec['teams'][0][0]['potaras'] = [2]
        with self.assertRaisesRegex(auto.KitError, 'another match'):
            self.confirm()
        self.assert_released()

    def test_native_ack_accepts_the_current_equipment(self):
        import kit_potara
        self.spec['teams'][0][0]['potaras'] = [2,124]
        self.equipment[auto.SCENE + 0xC4 + 20] = kit_potara.native([2,124])
        self.confirm()
        self.assert_released()

    def test_no_native_ack_times_out_and_releases_without_scene_writes(self):
        self.ack_after=None
        with self.assertRaisesRegex(auto.KitError,'did not start'):
            self.confirm()
        self.assert_released()
        self.assertGreaterEqual(self.clock,15)
        self.assertLess(self.clock,15.01)
        self.pine.write.assert_not_called()

    def test_cancellation_during_hold_releases_without_scene_writes(self):
        def check():
            if self.clock >= .02:raise auto.Cancelled()
        self.copy.check=check
        with self.assertRaises(auto.Cancelled):self.confirm()
        self.assert_released();self.pine.write.assert_not_called()

    def test_pine_failure_during_hold_releases_and_closes(self):
        original=self.word
        def broken(client,addr):
            if self.held and self.clock >= .01:raise OSError('owned connection lost')
            return original(client,addr)
        self.word=broken
        with self.assertRaisesRegex(OSError,'connection lost'):self.confirm()
        self.assert_released();self.pine.write.assert_not_called()

    def test_failed_keydown_still_releases_a_possibly_queued_partial_input(self):
        original=self.input
        def broken(pid,key,down,desktop):
            original(pid,key,down,desktop)
            if down:raise OSError('partial delivery')
        self.input=broken
        with self.assertRaisesRegex(OSError,'partial delivery'):self.confirm()
        self.assert_released();self.pine.write.assert_not_called()

    def test_foreign_selector_or_started_match_never_gets_cross(self):
        for guard,value in ((auto.TEAM_OBJECT,self.obj+4),(self.obj+0x3C6C,2),(auto.LOOP,1)):
            previous=self.words.get(guard)
            self.words[guard]=value;self.loop=value if guard==auto.LOOP else 0
            with self.subTest(guard=guard),patch.object(auto,'u32',side_effect=self.word), \
                    patch.object(auto.kit_win,'post_key') as key, \
                    patch.object(auto.kit_spec,'scene_time',return_value=1):
                with self.assertRaises(auto.KitError):self.copy.confirm(self.spec)
                key.assert_not_called()
            if previous is None:self.words.pop(guard,None)
            else:self.words[guard]=previous

    def test_native_ack_still_rejects_wrong_roster_stage_time_and_music(self):
        for address in (auto.SCENE+0xC4,auto.SCENE+0x1C,auto.SCENE+0x10,auto.SCENE+0x0C):
            previous=self.words[address];self.words[address]=previous+1
            self.loop,self.clock,self.held=0,0.,False
            self.inputs=[];self.pine.close.reset_mock()
            with self.subTest(address=address),self.assertRaises(auto.KitError):self.confirm()
            self.assert_released();self.words[address]=previous

    def test_unknown_process_token_refuses_input_and_spec_writes(self):
        self.copy._private_process_token.return_value=None
        with self.assertRaisesRegex(auto.KitError,'owner changed'):self.confirm()
        self.assertEqual(self.inputs,[]);self.copy.write_spec.assert_not_called()
        self.pine.write.assert_not_called();auto.kit_win.kill_tree.assert_not_called()

    def test_foreign_pine_listener_or_executable_refuses_input(self):
        for name,value in (('listener_pid',999),('process_path','foreign.exe')):
            with self.subTest(name=name),patch.object(auto.kit_win,name,return_value=value):
                with self.assertRaisesRegex(auto.KitError,'owner changed'):self.confirm()
                self.assertEqual(self.inputs,[]);self.copy.write_spec.assert_not_called()
                self.pine.write.assert_not_called();auto.kit_win.kill_tree.assert_not_called()

    def test_pid_reuse_during_hold_receives_no_keyup_or_cleanup(self):
        self.copy._private_process_token.side_effect=lambda pid: self.token if self.clock<.01 else ('replacement',pid)
        with self.assertRaisesRegex(auto.KitError,'owner changed'):self.confirm()
        self.assertEqual([row[2] for row in self.inputs],[True])
        self.pine.write.assert_not_called();auto.kit_win.kill_tree.assert_not_called()

    def test_base_replaced_during_hold_releases_only_captured_original(self):
        def check():
            if self.clock>=.01:self.copy.base=SimpleNamespace(pid=999,desktop='other')
        self.copy.check=check
        with self.assertRaisesRegex(auto.KitError,'owner changed'):self.confirm()
        self.assert_released()
        self.assertEqual([row[0] for row in self.inputs],[123,123])
        self.pine.write.assert_not_called();auto.kit_win.kill_tree.assert_not_called()

    def test_false_keydown_delivery_closes_only_original_and_stops(self):
        original=self.input
        def delivery(pid,key,down,desktop):
            original(pid,key,down,desktop);return 0 if down else 1
        self.input=delivery
        with self.assertRaisesRegex(auto.KitError,'no owned window'):self.confirm()
        self.assert_released();self.pine.write.assert_not_called()
        auto.kit_win.kill_tree.assert_called_once_with(123)
        self.assertEqual(self.copy.state,'cold');self.assertFalse(self.copy.fast_loading)

    def test_false_keyup_delivery_closes_only_original_before_scene_writes(self):
        original=self.input
        def delivery(pid,key,down,desktop):
            original(pid,key,down,desktop);return 1 if down else 0
        self.input=delivery
        with self.assertRaisesRegex(auto.KitError,'could not be released'):self.confirm()
        self.assert_released();self.pine.write.assert_not_called()
        auto.kit_win.kill_tree.assert_called_once_with(123)

    def test_cancellation_keeps_primary_error_when_keyup_also_fails(self):
        def check():
            if self.clock>=.02:raise auto.Cancelled()
        self.copy.check=check
        original=self.input
        def delivery(pid,key,down,desktop):
            original(pid,key,down,desktop);return 1 if down else 0
        self.input=delivery
        with self.assertRaises(auto.Cancelled):self.confirm()
        self.assert_released();self.pine.write.assert_not_called()
        auto.kit_win.kill_tree.assert_called_once_with(123)

    def test_postrelease_owner_change_blocks_native_scene_writes(self):
        original=self.input
        def change(pid,key,down,desktop):
            delivered=original(pid,key,down,desktop)
            if not down:self.copy._private_process_token.return_value=('replacement',pid)
            return delivered
        self.input=change
        with self.assertRaisesRegex(auto.KitError,'owner changed'):self.confirm()
        self.assert_released();self.pine.write.assert_not_called()
        auto.kit_win.kill_tree.assert_not_called()

    def test_nonwindows_fast_confirm_retains_original_short_pulse(self):
        self.ack_after=.004
        with patch.object(auto.kit_win,'WINDOWS',False):self.confirm()
        self.assert_released();self.assertAlmostEqual(self.inputs[-1][4],1/120)
        self.copy._private_process_token.assert_not_called()


class PrivateINI(unittest.TestCase):
    def test_hidden_profile_remains_nominal1_with_turbo32_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            c = prepare.Prepare.__new__(prepare.Prepare)
            c.dest, c.orig, c.slot = root / 'copy', root / 'old', 29990
            c.args = SimpleNamespace(hidden=True)
            path = c.dest / 'game/runtime28/inis/PCSX2.ini'
            path.parent.mkdir(parents=True)
            original = '[EmuCore/GS]\nRenderer=7\n[Framerate]\nNominalScalar=1\nTurboScalar=1\n'
            path.write_text(original)
            with patch.object(prepare, 'patches', return_value={}), patch.object(prepare.kit_win, 'WINDOWS', True):
                c.patch()
            result = configparser.ConfigParser(interpolation=None)
            result.read(path)
            self.assertEqual(result.getfloat('Framerate', 'NominalScalar'), 1)
            self.assertEqual(result.getfloat('Framerate', 'TurboScalar'), 32)
            self.assertEqual(prepare.PRIVATE_SPEED, 32.0)
            self.assertEqual(result.getint('EmuCore/GS', 'Renderer'), 11)
            self.assertTrue(result.getboolean('EmuCore/GS', 'VsyncEnable'))
            self.assertTrue(result.getboolean('EmuCore/GS', 'DisableMailboxPresentation'))
            self.assertEqual((c.orig / 'game/runtime28/inis/PCSX2.ini').read_text(), original)


    def test_fifo_changes_only_the_hidden_windows_builder_and_preserves_original_profile(self):
        for hidden, windows in ((False, True), (True, False)):
            with self.subTest(hidden=hidden, windows=windows), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                c = prepare.Prepare.__new__(prepare.Prepare)
                c.dest, c.orig, c.slot = root / 'copy', root / 'old', 29990
                c.args = SimpleNamespace(hidden=hidden)
                path = c.dest / 'game/runtime28/inis/PCSX2.ini'
                path.parent.mkdir(parents=True)
                original = '[EmuCore/GS]\nRenderer=7\nVsyncEnable=false\nDisableMailboxPresentation=false\n[Framerate]\nNominalScalar=1\nTurboScalar=1\n'
                path.write_text(original)
                with patch.object(prepare, 'patches', return_value={}), patch.object(prepare.kit_win, 'WINDOWS', windows):
                    c.patch()
                result = configparser.ConfigParser(interpolation=None)
                result.read(path)
                self.assertEqual(result.getint('EmuCore/GS', 'Renderer'), 7)
                self.assertFalse(result.getboolean('EmuCore/GS', 'VsyncEnable'))
                self.assertFalse(result.getboolean('EmuCore/GS', 'DisableMailboxPresentation'))
                self.assertEqual(result.getfloat('Framerate', 'NominalScalar'), 1)
                self.assertEqual((c.orig / 'game/runtime28/inis/PCSX2.ini').read_text(), original)


class HoldDelivery(CopyFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        c = self.copy
        c.slot = 29929
        c.base.desktop = f'ttm-kit-prep-{c.slot}'
        c.loading_speed = auto.PrepCopy.loading_speed.__get__(c, auto.PrepCopy)
        self.token = ('windows', str(c.base.dest / 'game/runtime28/pcsx2-qt.exe'), 7)
        c._private_process_token = Mock(side_effect=lambda _: self.token)
        self.inputs = []
        self.limiter, self.saved_limiter = 'Nominal', None
        for item in (
            patch.object(auto.kit_win, 'WINDOWS', True),
            patch.object(auto.kit_win, 'listener_pid', return_value=123),
            patch.object(auto.kit_win, 'process_path', return_value=self.token[1]),
            patch.object(auto.kit_win, 'post_key', side_effect=self.post_key),
        ):
            item.start()
            self.addCleanup(item.stop)

    def post_key(self, pid, key, down, desktop):
        self.inputs.append((pid, key, down, desktop))
        self.assertEqual(key, prepare.PREP_SPEED_KEY)
        if down and self.saved_limiter is None:
            self.saved_limiter, self.limiter = self.limiter, 'Turbo'
        elif not down and self.saved_limiter is not None:
            self.limiter, self.saved_limiter = self.saved_limiter, None
        return 1

    def test_delivered_hold_and_release_update_flags_and_restore_nominal(self):
        self.copy.loading_speed(True)
        self.assertTrue(self.copy.fast_loading)
        self.assertEqual(self.limiter, 'Turbo')
        self.copy.loading_speed(False)
        self.assertFalse(self.copy.fast_loading)
        self.assertEqual(self.limiter, 'Nominal')
        self.assertEqual([row[2] for row in self.inputs], [True, False])

    def test_missing_hold_window_never_marks_fast_or_leaves_owned_child(self):
        def missing(pid, key, down, desktop):
            if down:
                self.inputs.append((pid, key, down, desktop))
                return 0
            return self.post_key(pid, key, down, desktop)
        with patch.object(auto.kit_win, 'post_key', side_effect=missing):
            with self.assertRaises(OSError): self.copy.loading_speed(True)
        self.assertFalse(self.copy.fast_loading)
        self.copy.base.close.assert_called_once()
        self.assertIsNone(self.copy.base.pid)
        self.assertEqual(self.limiter, 'Nominal')
        self.assertEqual([row[2] for row in self.inputs], [True, False])

    def test_failed_release_retries_keyup_and_closes_only_owned_child(self):
        self.copy.loading_speed(True)
        def missing(pid, key, down, desktop):
            self.post_key(pid, key, down, desktop)
            return 0 if not down else 1
        with patch.object(auto.kit_win, 'post_key', side_effect=missing):
            with self.assertRaises(OSError): self.copy.loading_speed(False)
        self.assertFalse(self.copy.fast_loading)
        self.copy.base.close.assert_called_once()
        self.assertIsNone(self.copy.base.pid)
        self.assertEqual(self.limiter, 'Nominal')
        self.assertEqual([row[2] for row in self.inputs], [True, False, False])

    def test_changed_base_receives_no_cleanup_or_state_flag_overwrite(self):
        c, original = self.copy, self.copy.base
        replacement = SimpleNamespace(dest=original.dest, pid=321, cmd_pid=322,
                                      desktop=original.desktop, close=Mock())
        def changed(pid, key, down, desktop):
            result = self.post_key(pid, key, down, desktop)
            if down:
                c.base, c.fast_loading = replacement, True
            return result
        with patch.object(auto.kit_win, 'post_key', side_effect=changed):
            with self.assertRaises(auto.Cancelled): c.loading_speed(True)
        self.assertTrue(c.fast_loading)
        original.close.assert_not_called()
        replacement.close.assert_not_called()
        self.assertTrue(all(row[0] == 123 for row in self.inputs))

    def test_reused_pid_receives_no_cleanup_key_or_close(self):
        def reused(pid, key, down, desktop):
            self.inputs.append((pid, key, down, desktop))
            if down:
                self.token = ('windows', self.token[1], 999)
                return 0
            return 1
        with patch.object(auto.kit_win, 'post_key', side_effect=reused):
            with self.assertRaises(OSError): self.copy.loading_speed(True)
        self.assertFalse(self.copy.fast_loading)
        self.copy.base.close.assert_not_called()
        self.assertEqual([row[2] for row in self.inputs], [True])

    def test_foreign_listener_or_executable_is_never_closed_on_failure(self):
        for guard in (patch.object(auto.kit_win, 'listener_pid', return_value=321),
                      patch.object(auto.kit_win, 'process_path', return_value='foreign-emulator')):
            with guard, patch.object(auto.kit_win, 'post_key', return_value=0):
                with self.assertRaises(OSError): self.copy.loading_speed(True)
            self.copy.base.close.assert_not_called()
            self.assertFalse(self.copy.fast_loading)

    def prepare_fixture(self):
        c = self.copy
        (self.root / 'game').mkdir()
        c.at_map_select = Mock(return_value=True)
        c.base.python = Mock(return_value='private-python')
        c.newest_checkpoint = Mock(return_value=None)
        c.write_settings = c.write_native = Mock()
        c.schedule_reset = Mock()
        c.confirm = Mock(return_value=dict(counts=[1, 1], members=[[[1, 0, 0]], [[2, 0, 0]]], stage=(2, 2)))
        c._recover_after_confirm = Mock()
        spec = dict(native=dict(time=0), teams=[[dict(character=1, costume=0)], [dict(character=2, costume=0)]],
                    stage=2, bgm=3)
        return c, spec

    def test_closed_confirmed_child_is_never_sent_to_native_recovery(self):
        c, spec = self.prepare_fixture()
        def closed():
            c.close()
            raise auto.Cancelled()
        c.wait_for_checkpoint = Mock(side_effect=closed)
        with patch.object(auto.kit_spec, 'engine_mode', return_value='teams'), \
                patch.object(auto.kit_spec, 'spec_sha', return_value='a' * 64):
            with self.assertRaises(auto.Cancelled): c.prepare(spec, self.root / 'made')
        c.confirm.assert_called_once()
        c._recover_after_confirm.assert_not_called()

    def test_failed_release_after_capture_never_recovers_the_closed_child(self):
        c, spec = self.prepare_fixture()
        checkpoint = self.root / 'checkpoint.p2s'
        checkpoint.write_bytes(b'test-capture')
        c.wait_for_checkpoint = Mock(return_value=checkpoint)
        def missing(pid, key, down, desktop):
            self.post_key(pid, key, down, desktop)
            return 0 if not down else 1
        with patch.object(auto.kit_spec, 'engine_mode', return_value='teams'), \
                patch.object(auto.kit_spec, 'spec_sha', return_value='a' * 64), \
                patch.object(auto.kit_win, 'post_key', side_effect=missing):
            with self.assertRaises(OSError): c.prepare(spec, self.root / 'made')
        c.confirm.assert_called_once()
        c._recover_after_confirm.assert_not_called()
        c.base.close.assert_called_once()
        self.assertFalse(c.fast_loading)


if __name__ == '__main__': unittest.main()
