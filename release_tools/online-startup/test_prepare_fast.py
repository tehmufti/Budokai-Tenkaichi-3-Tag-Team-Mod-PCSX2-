"""Fast preparation regressions, without starting PCSX2 or requiring game media."""
import ast
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
    (Path(root) / 'game').mkdir(parents=True, exist_ok=True)
    copy = auto.PrepCopy.__new__(auto.PrepCopy)
    copy.base = SimpleNamespace(dest=Path(root), pid=123, cmd_pid=124, desktop='test-private',
                                python=Mock(return_value='private-python'), close=Mock())
    copy.run_dir = Path(root)
    copy.state, copy.engine = 'warm', 'teams'
    copy.lock = threading.RLock()
    copy.cancel = threading.Event()
    copy.reset_token = copy.reset_thread = None
    copy.reset_running = False
    copy.selector_cache = copy.selector_identity = copy.selector_lease = None
    copy.selector_boot = None
    copy.cache_selector = Mock()
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
    def test_rejected_cache_rechecks_private_profile_before_native_boot(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.base.pid = None
            events = []
            copy.make_copy = lambda: events.append('make-copy-and-identity')
            copy.check = Mock()
            copy.cached_selector = Mock(return_value=True)
            copy.at_map_select = Mock(return_value=True)
            copy.launch = lambda cached=False: events.append(('launch', cached))
            copy.loading_speed = Mock()
            copy.restore_selector = Mock(side_effect=ValueError('live selector differs'))
            copy.boot = lambda: events.append('native-boot')
            copy.commit_mode = lambda: events.append('native-mode')
            self.assertEqual(copy.warm(), 'warm')
            self.assertEqual(events, ['make-copy-and-identity', ('launch', True),
                                      'make-copy-and-identity', ('launch', False), 'native-boot', 'native-mode'])
            copy.base.close.assert_called_once()

    def test_settings_are_read_back_in_the_same_checked_interpreter(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.settings_written = None
            values = dict(cpu_transform_rate=.5, language='en')
            copy.base.copy_python = Mock(return_value=(0, json.dumps(values), ''))
            with patch('kit_settings.match_settings', return_value=values):
                copy.write_settings({}, {}, 'en')
            copy.base.copy_python.assert_called_once()
            program = copy.base.copy_python.call_args.args[1]
            self.assertLess(program.index('save_settings(d)'), program.index('load_settings()'))
            self.assertEqual(copy.settings_written, values)
            copy.base.copy_python = Mock(return_value=(0, '{}', ''))
            # Equal settings do not start another interpreter.
            with patch('kit_settings.match_settings', return_value=values):
                copy.write_settings({}, {}, 'en')
            copy.base.copy_python.assert_not_called()

    def test_invalid_settings_readback_is_not_authorized(self):
        for output in ('not-json', 'null', '[]', '{"language":"es"}'):
            with tempfile.TemporaryDirectory() as folder:
                copy = copy_at(folder)
                copy.settings_written = None
                copy.base.copy_python = Mock(return_value=(0, output, ''))
                with patch('kit_settings.match_settings', return_value=dict(language='en')):
                    with self.assertRaises(auto.KitError):
                        copy.write_settings({}, {}, 'en')
                self.assertIsNone(copy.settings_written)

    def test_private_watcher_does_not_toggle_transient_paused_boot(self):
        for game in ('bt3-multifighter', 'bt4-multifighter'):
            source = (ROOT / game / 'tools/autopilot.py').read_text(encoding='utf-8-sig')
            edits = auto.kit_prepare.patches(29921)['game/tools/autopilot.py']
            old, new = next((old, new) for old, new in edits if 'menu_resume_sent' in old)
            self.assertEqual(source.count(old), 1)
            before, after = ast.parse(source), ast.parse(source.replace(old, new))
            changed = []
            for left, right in zip(ast.walk(before), ast.walk(after)):
                if isinstance(left, ast.Assign) and isinstance(right, ast.Assign):
                    if (len(left.targets) == 1 and isinstance(left.targets[0], ast.Attribute)
                            and left.targets[0].attr == 'menu_resume_sent'
                            and isinstance(left.value, ast.Constant) and left.value.value is False):
                        self.assertIs(right.value.value, True)
                        self.assertTrue(any(node.name == '__init__' and node.lineno <= left.lineno <= node.end_lineno
                                            for node in ast.walk(before) if isinstance(node, ast.FunctionDef)))
                        right.value.value = False
                        changed.append(left.lineno)
            self.assertEqual(len(changed), 1)
            self.assertEqual(ast.dump(before), ast.dump(after))

    def test_cached_bootstrap_is_accelerated_and_speed_is_released(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.base.pid = None
            copy.make_copy = copy.check = Mock()
            copy.cached_selector = Mock(return_value=True)
            copy.at_map_select = Mock(return_value=True)
            events = []
            copy.launch = lambda cached=False: events.append(('launch', cached))
            copy.loading_speed = lambda enabled: events.append(('turbo', enabled))
            copy.restore_selector = lambda engine: events.append(('restore', engine))
            self.assertEqual(copy.warm(), 'warm')
            self.assertEqual(events, [('launch', True), ('turbo', True),
                                      ('restore', 'teams'), ('turbo', False)])

    def test_private_poll_patch_only_changes_three_sleep_intervals(self):
        for game in ('bt3-multifighter', 'bt4-multifighter'):
            source = (ROOT / game / 'tools/fresh_team_trainer.py').read_text(encoding='utf-8-sig')
            modified = source
            for old, new in auto.kit_prepare.patches(29921)['game/tools/fresh_team_trainer.py']:
                if not ('time.sleep(.005)' in new or 'time.sleep(0.005)' in new):
                    continue
                self.assertEqual(modified.count(old), 1)
                modified = modified.replace(old, new)
            before, after = ast.parse(source), ast.parse(modified)
            changed = []
            for old, new in zip(ast.walk(before), ast.walk(after)):
                if isinstance(old, ast.Constant) and old.value == .2 and isinstance(new, ast.Constant) and new.value == .005:
                    changed.append(new.lineno)
                    new.value = old.value
            self.assertEqual(len(changed), 3)
            self.assertEqual(ast.dump(before), ast.dump(after))
            methods = ('wait_word', 'wait_counter', 'wait_idle_leaders')
            self.assertTrue(all(any(node.name in methods and node.lineno <= line <= node.end_lineno
                                    for node in ast.walk(after) if isinstance(node, ast.FunctionDef))
                                for line in changed))

    def test_cached_map_selector_never_confirms_an_unwanted_match(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.at_map_select = Mock(return_value=True)
            copy.keys = Mock(side_effect=AssertionError('Map selector must not receive Cross'))
            copy.native_picks()
            copy.keys.assert_not_called()

    def test_cached_reset_waits_for_preparation_worker_but_not_native_intro(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.cached_selector = Mock(return_value=True)
            copy.watcher = Mock(side_effect=[dict(state='PREPARING'), dict(state='ACTIVE')])
            copy.restore_selector = Mock()
            copy.sleep = copy.check = copy.loading_speed = Mock()
            copy.wait_for_fight = Mock(side_effect=AssertionError('Native intro is not required'))
            with copy.lock:
                copy.schedule_reset()
                copy._finish_pending_reset()
            copy.reset_thread.join(timeout=2)
            copy.restore_selector.assert_called_once_with('teams')
            self.assertEqual(copy.state, 'warm')
            self.assertIsNone(copy.reset_token)

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

    def test_normal_warm_failure_never_enables_private_turbo(self):
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
            key.assert_not_called()
            self.assertFalse(copy.fast_loading)
            self.assertEqual(copy.state, 'failed')

    def test_cached_warm_cancel_releases_private_turbo(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = copy_at(folder)
            copy.state = 'cold'
            copy.base.pid = None
            copy.make_copy = copy.check = Mock()
            copy.cached_selector = Mock(return_value=True)
            def launch(cached=False):
                copy.base.pid = 123
            copy.launch = launch
            copy.restore_selector = Mock(side_effect=auto.Cancelled())
            copy.close = Mock()  # The enclosing finally must release the key itself.
            with patch.object(auto.kit_win, 'post_key') as key:
                with self.assertRaises(auto.Cancelled):
                    copy.warm()
            self.assertEqual([c.args[2] for c in key.call_args_list], [True, False])
            self.assertFalse(copy.fast_loading)


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


class PrivateBuilderServiceGuards(unittest.TestCase):
    """Exercise the production patch recipe with no private/staged imports."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / 'prep/Tag Team Mod/game'
        self.game.mkdir(parents=True)
        self.config = self.game / 'runtime28/inis/PCSX2.ini'
        self.config.parent.mkdir(parents=True)
        self.text = '[SPU2/Output]\nBackend=Null\n[InputSources]\nSDL=false\nXInput=false\nDInput=false\n'
        self.config.write_text(self.text, encoding='utf-8')
        self.settings = SimpleNamespace(DEFAULTS={}, load_settings=lambda: {})
        self.recorder = Mock(return_value=SimpleNamespace())
        self.menu = SimpleNamespace(Controller=Mock(return_value=SimpleNamespace(team_menu=SimpleNamespace())))

    def source(self, filename):
        return (ROOT / 'bt3-multifighter/tools' / filename).read_text(encoding='utf-8-sig')

    def services(self, filename):
        markers = ('Private builder service suppression requires', 'private keyboard input stays with PCSX2',
                   'no audio repair worker', 'native ownership/code guards remain eager')
        rows = auto.kit_prepare.patches(29921)['game/tools/'+filename]
        selected = [(old, new) for old, new in rows if any(marker in new for marker in markers)]
        self.assertEqual(len(selected), 3 if filename == 'autopilot.py' else 1)
        return selected

    def patched(self, filename):
        source = self.source(filename)
        for old, new in self.services(filename):
            self.assertEqual(source.count(old), 1, filename)
            source = source.replace(old, new)
        ast.parse(source)
        return source

    def constructor(self):
        tree = ast.parse(self.patched('autopilot.py'))
        watcher = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Autopilot')
        watcher.body = [node for node in watcher.body if isinstance(node, ast.FunctionDef) and node.name == '__init__']
        namespace = dict(ROOT=self.game, runtime_profile=SimpleNamespace(CONFIG=self.config), Path=Path,
                         WINDOWS=True, threading=threading, log=lambda text: None,
                         say=lambda text: text, SAY_BOOTING='booting', PREPARATION_MESSAGES=['preparing'])
        exec(compile(ast.Module(body=[watcher], type_ignores=[]), '<private constructor>', 'exec'), namespace)
        return namespace['Autopilot']

    def test_exact_service_patches_leave_native_action_and_guard_functions_unchanged(self):
        for filename in ('autopilot.py', 'native_mode_menu.py'):
            before, after = ast.parse(self.source(filename)), ast.parse(self.patched(filename))
            def functions(tree):
                return {node.name: ast.dump(node) for node in tree.body if isinstance(node, ast.FunctionDef)}
            original, changed = functions(before), functions(after)
            if filename == 'autopilot.py':
                original.pop('main'); changed.pop('main')
            self.assertEqual(original, changed)

    def test_private_null_keyboard_constructor_keeps_native_state_without_sdl_owners(self):
        forbidden = {name: None for name in ('controller_hub', 'controller_mailbox',
                                              'quad_menu_input', 'controller_assignment')}
        with patch.dict(sys.modules, dict(forbidden, mod_settings=self.settings,
                        battle_diagnostics=SimpleNamespace(Recorder=self.recorder), native_mode_menu=self.menu)):
            watcher = self.constructor()(lifetime=SimpleNamespace(process=SimpleNamespace(pid=123)), in_game_menu=True)
        self.assertEqual((watcher.controller_hub, watcher.controller_input, watcher.menu_input, watcher.assigned_input),
                         (None, None, None, None))
        self.assertIsNone(watcher.mode_menu.team_menu.hub)
        self.assertIsNotNone(watcher.preparation_lock)
        self.assertEqual(watcher.state, 'MENU')

    def test_enabled_real_inputs_or_audio_refuse_service_suppression(self):
        for old, new in [('Backend=Null', 'Backend=Cubeb'), ('SDL=false', 'SDL=true'),
                         ('XInput=false', 'XInput=true'), ('DInput=false', 'DInput=true')]:
            with self.subTest(option=new):
                self.config.write_text(self.text.replace(old, new), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'isolated keyboard/Null-audio profile'):
                    self.constructor()(lifetime=SimpleNamespace(process=SimpleNamespace(pid=123)))

    def test_ordinary_installation_cannot_disable_its_controller_services(self):
        self.game = Path(self.temp.name) / 'regular install/game'
        with self.assertRaisesRegex(ValueError, 'isolated keyboard/Null-audio profile'):
            self.constructor()(lifetime=SimpleNamespace(process=SimpleNamespace(pid=123)))

    def test_private_menu_retains_eager_code_proof_and_defers_only_artwork(self):
        tree = ast.parse(self.patched('native_mode_menu.py'))
        controller = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Controller')
        controller.body = [node for node in controller.body if isinstance(node, ast.FunctionDef) and node.name == '__init__']
        proof = Mock()
        assets = Mock(side_effect=AssertionError('unused main menu artwork'))
        namespace = dict(code_pieces=proof, assets=SimpleNamespace(addresses=assets),
                         ingame_settings=SimpleNamespace(Controller=lambda: object()),
                         team_assignment=SimpleNamespace(Controller=lambda: object()),
                         scenario_menu=SimpleNamespace(Controller=lambda settings: object()))
        with patch.dict(sys.modules, {'native_menu_texture': None}):
            exec(compile(ast.Module(body=[controller], type_ignores=[]), '<private menu>', 'exec'), namespace)
            menu = namespace['Controller']({})
        proof.assert_called_once()
        assets.assert_not_called()
        self.assertFalse(menu.custom_match)
        self.assertEqual(menu.epoch, 0)

    def test_audio_worker_removal_preserves_process_claim_and_lifetime_calls(self):
        def calls(source):
            main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'main')
            return [ast.dump(node.func) for node in ast.walk(main) if isinstance(node, ast.Call)]
        before, after = calls(self.source('autopilot.py')), calls(self.patched('autopilot.py'))
        audio = "Name(id='start_audio_repair', ctx=Load())"
        self.assertEqual(before.count(audio), 1)
        before.remove(audio)
        self.assertEqual(before, after)


class PrivatePollingGuards(unittest.TestCase):
    """Only detection frequency changes; native/owner/archive proof stays eager."""
    def source(self, filename, game='bt3-multifighter'):
        return (ROOT/game/'tools'/filename).read_text(encoding='utf-8-sig')

    def poll_rows(self, filename):
        return [(old, new) for old, new in auto.kit_prepare.patches(29921)['game/tools/'+filename]
                if 'time.sleep(' in old and 'time.sleep(' in new]

    def patched(self, filename, game='bt3-multifighter'):
        source = self.source(filename, game)
        for old, new in self.poll_rows(filename):
            self.assertEqual(source.count(old), 1, (filename, old))
            source = source.replace(old, new)
        return source

    def function(self, filename, name, namespace, class_name=None):
        tree = ast.parse(self.patched(filename))
        scope = tree.body
        if class_name:
            scope = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name).body
        node = next(node for node in scope if isinstance(node, ast.FunctionDef) and node.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<private polling>', 'exec'), namespace)
        return namespace[name]

    def budget(self, timeout):
        return SimpleNamespace(observe=lambda status: status == 'running', expired=False)

    def client(self):
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        return client

    def test_private_native_and_snapshot_patches_change_only_six_constants(self):
        for game in ('bt3-multifighter', 'bt4-multifighter'):
            for filename, expected in [('fresh_team_trainer.py', {'wait_word': (.2,.005),
                    'wait_counter': (.2,.005), 'wait_idle_leaders': (.2,.005), 'snapshot': (.1,.01)}),
                    ('native_preparation.py', {'quiet': (.02,.005), 'apply': (.02,.005)})]:
                before, after = ast.parse(self.source(filename, game)), ast.parse(self.patched(filename, game))
                changes = []
                for left, right in zip(ast.walk(before), ast.walk(after)):
                    if isinstance(left, ast.Constant) and isinstance(right, ast.Constant) and left.value != right.value:
                        owners = [node.name for node in ast.walk(before) if isinstance(node, ast.FunctionDef)
                                  and node.lineno <= left.lineno <= node.end_lineno]
                        self.assertEqual(len(owners), 1)
                        self.assertEqual((left.value,right.value), expected[owners[0]])
                        changes.append(owners[0])
                        right.value = left.value
                self.assertEqual(sorted(changes), sorted(expected))
                self.assertEqual(ast.dump(before), ast.dump(after))

    def test_private_patch_drift_fails_closed_before_target_replacement(self):
        for filename in ('fresh_team_trainer.py','native_preparation.py'):
            rows = self.poll_rows(filename)
            for mutation in ('missing','duplicate'):
                with self.subTest(filename=filename,mutation=mutation), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    target = root/'game/tools'/filename
                    target.parent.mkdir(parents=True)
                    source = self.source(filename)
                    old = rows[0][0]
                    source = source.replace(old,'# changed context') if mutation == 'missing' else source+'\n'+old
                    target.write_text(source,encoding='utf-8')
                    before = target.read_bytes()
                    builder = auto.kit_prepare.Prepare.__new__(auto.kit_prepare.Prepare)
                    builder.dest, builder.orig, builder.slot = root, root/'originals', 29921
                    with patch.object(auto.kit_prepare,'patches',return_value={'game/tools/'+filename:rows}):
                        with self.assertRaises(auto.KitError):
                            builder.patch()
                    self.assertEqual(target.read_bytes(),before)

    def test_wait_word_does_not_accept_paused_frame_and_keeps_error_first(self):
        sleeper = Mock()
        namespace = dict(ActiveRuntimeBudget=self.budget,time=SimpleNamespace(sleep=sleeper))
        wait = self.function('fresh_team_trainer.py','wait_word',namespace,'Session')
        p = self.client()
        p.status.side_effect = ['paused','running']
        p.read_u32.return_value = 1
        session = SimpleNamespace(client=lambda require_running: p)
        with patch.dict(sys.modules,{'localization':SimpleNamespace(tr=lambda text:text)}):
            wait(session,0x1000,1,'step')
            self.assertEqual(p.status.call_count,2)
            sleeper.assert_called_once_with(.005)
            sleeper.reset_mock();p.status.side_effect=['paused'];p.read_u32.return_value=150
            with self.assertRaisesRegex(RuntimeError,'guest status 150'):
                wait(session,0x1000,1,'Creating independent fighters...')
            sleeper.assert_not_called()

    def test_wait_counter_still_requires_running_minimum_frames(self):
        sleeper=Mock()
        wait=self.function('fresh_team_trainer.py','wait_counter',
                           dict(ActiveRuntimeBudget=self.budget,time=SimpleNamespace(sleep=sleeper)),'Session')
        p=self.client();p.status.side_effect=['paused','running','running'];p.read_u32.side_effect=[5,6]
        wait(SimpleNamespace(client=lambda running:p),0x1000,6)
        self.assertEqual(p.status.call_count,3)
        self.assertEqual(p.read_u32.call_count,2)
        self.assertEqual([call.args[0] for call in sleeper.call_args_list],[.005,.005])

    def test_idle_hold_and_manager_guards_are_not_bypassed(self):
        sleeper=Mock(); control=0x200000;actor=0x400000;manager=0x300000
        namespace=dict(ActiveRuntimeBudget=self.budget,time=SimpleNamespace(sleep=sleeper),
                       fresh_memory=SimpleNamespace(CONTROL=control),A=lambda address:address,IDLE_COUNT=0x1234)
        wait=self.function('fresh_team_trainer.py','wait_idle_leaders',namespace,'Session')
        p=self.client();p.status.side_effect=['paused','running','running'];phase=[0]
        words={control+80:1,control+84:manager,0x2FEB14:manager,manager+4:actor}
        p.read_u32.side_effect=lambda address: (11 if phase[0]>=2 else 67) if address==actor+0x948 else words.get(address,0)
        sleeper.side_effect=lambda seconds:phase.__setitem__(0,phase[0]+1)
        wait(SimpleNamespace(client=lambda running:p),[actor])
        self.assertEqual(phase[0],2);p.write_u32.assert_called_once_with(actor+0x1234,0)
        for address,value,message in [(control+80,0,'input hold'),(control+84,manager+4,'manager changed')]:
            p.status.side_effect=None;p.status.return_value='running';words[address]=value
            p.write_u32.reset_mock()
            with self.assertRaisesRegex(ValueError,message):wait(SimpleNamespace(client=lambda running:p),[actor])
            p.write_u32.assert_not_called();words[address]=1 if address==control+80 else manager

    def native(self,name,sleeper):
        return self.function('native_preparation.py',name,dict(CONTROL=0x1000,MAGIC=123,PACKET=0x2000,
            installed=lambda p:True,A=lambda address:address,launcher=lambda:'Play.cmd',SERVICE_MISSING='missing',
            RunningTime=lambda p,timeout:SimpleNamespace(expired=lambda:False),
            time=SimpleNamespace(sleep=sleeper),encode=lambda manifest:(b'packet',2),struct=__import__('struct')))

    def test_quiet_requires_native_ack_and_rejects_unarmed_service(self):
        sleeper=Mock();quiet=self.native('quiet',sleeper);p=Mock();ack=[0,1]
        p.read_u32.side_effect=lambda address: ack.pop(0) if address==0x1014 else {0x1000:123,0x2FEB14:0x400000}[address]
        quiet(p)
        sleeper.assert_called_once_with(.005)
        self.assertEqual([call.args for call in p.write_u32.call_args_list],[(0x1018,0x400000),(0x1010,1)])
        sleeper.reset_mock();p.read_u32.side_effect=lambda address:0
        with self.assertRaisesRegex(ValueError,'not armed'):quiet(p)
        sleeper.assert_not_called()

    def test_apply_requires_hold_and_writes_one_request_before_native_ack(self):
        sleeper=Mock();apply=self.native('apply',sleeper);p=Mock()
        words={0x1014:1,0x1010:1,0x1004:9,0x1008:9,0x100c:1}
        p.read_u32.side_effect=lambda address:words.get(address,0)
        p.write_u32.side_effect=lambda address,value:words.__setitem__(address,value)
        def ack(seconds):words[0x1008]=words[0x1004];words[0x100c]=1
        sleeper.side_effect=ack
        apply(p,{'blocks':[]})
        self.assertEqual([call.args for call in p.write_u32.call_args_list if call.args[0]==0x1004],[(0x1004,10)])
        sleeper.assert_called_once_with(.005)
        for address,value,message in [(0x1014,0,'acknowledged combat hold'),(0x1008,8,'already pending')]:
            words.update({0x1014:1,0x1010:1,0x1004:9,0x1008:9});words[address]=value
            p.write.reset_mock();p.write_u32.reset_mock()
            with self.assertRaisesRegex(ValueError,message):apply(p,{})
            p.write.assert_not_called();p.write_u32.assert_not_called()

    def test_apply_rejection_preserves_guest_error_and_block_number(self):
        sleeper=Mock();apply=self.native('apply',sleeper);p=Mock()
        words={0x1014:1,0x1010:1,0x1004:9,0x1008:9,0x100c:0,0x1024:7}
        p.read_u32.side_effect=lambda address:words.get(address,0)
        p.write_u32.side_effect=lambda address,value:words.__setitem__(address,value)
        def reject(seconds):words[0x1008]=10;words[0x100c]=4
        sleeper.side_effect=reject
        with self.assertRaisesRegex(RuntimeError,'status 4, block 7'):apply(p,{})
        self.assertEqual(sum(call.args[0]==0x1004 for call in p.write_u32.call_args_list),1)

    def test_failed_snapshot_decode_never_publishes_archive(self):
        import shutil
        import zipfile
        import uuid
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'native.p2s';source.write_bytes(b'archive-bytes')
            previous=source.stat().st_mtime_ns
            def saved(slot):os.utime(source,ns=(previous+1000000,previous+1000000))
            p=self.client();p.save_state.side_effect=saved
            z=Mock();z.__enter__=Mock(return_value=z);z.__exit__=Mock(return_value=False)
            z.getinfo.return_value=SimpleNamespace(file_size=0x8000000)
            decoder=Mock(side_effect=zipfile.BadZipFile('CRC mismatch'))
            sleeper=Mock();clock=Mock(side_effect=[0,0,31]);runtime=Mock()
            namespace=dict(time=SimpleNamespace(monotonic=clock,sleep=sleeper),require_runtime=runtime,
                           zipfile=SimpleNamespace(ZipFile=Mock(return_value=z),BadZipFile=zipfile.BadZipFile),
                           shutil=shutil,uuid=uuid,read_entry=decoder)
            snapshot=self.function('fresh_team_trainer.py','snapshot',namespace,'Session')
            session=SimpleNamespace(check_slot=lambda slot:(slot,source),running_client=lambda:p,
                                    run=root,index=0,source=None,record_slot=Mock(),store_scratch=Mock())
            with self.assertRaisesRegex(TimeoutError,'did not finish saving'):snapshot(session,'ready-held')
            sleeper.assert_called_once_with(.01);runtime.assert_called_once();decoder.assert_called_once()
            self.assertFalse((root/'00-ready-held.p2s').exists())
            self.assertTrue(list(root.glob('*.partial')))
            session.record_slot.assert_not_called();session.store_scratch.assert_not_called()
            self.assertEqual(session.index,0);self.assertIsNone(session.source)

    def test_snapshot_runtime_cancellation_stops_before_archive_read(self):
        sleeper=Mock();runtime=Mock(side_effect=auto.Cancelled())
        snapshot=self.function('fresh_team_trainer.py','snapshot',
             dict(time=SimpleNamespace(monotonic=Mock(side_effect=[0,0]),sleep=sleeper),require_runtime=runtime,
                  zipfile=Mock()),'Session')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'missing.p2s';p=self.client()
            session=SimpleNamespace(check_slot=lambda slot:(slot,path),running_client=lambda:p)
            with self.assertRaises(auto.Cancelled):snapshot(session,'ready-held')
            sleeper.assert_called_once_with(.01)

    def test_checkpoint_detection_keeps_unverified_one_second_stability_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            copy=copy_at(folder);copy.check=Mock();copy.watcher_failed=Mock(return_value=None)
            copy.early_checkpoint=Mock(return_value=None)
            path=Path(folder)/'native.p2s';path.write_bytes(b'complete-archive')
            copy.newest_checkpoint=Mock(return_value=path)
            with patch.object(auto.time,'sleep') as sleep:
                self.assertEqual(copy.wait_for_checkpoint(),path)
            sleep.assert_called_once_with(1.0)

    def test_checkpoint_detection_retries_changing_fallback_before_fast_poll(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        copy=copy_at(temp.name);copy.check=Mock();copy.watcher_failed=Mock(return_value=None)
        verified=Path('verified.p2s');copy.early_checkpoint=Mock(side_effect=[None,verified])
        candidate=Mock();candidate.is_file.return_value=True
        candidate.stat.side_effect=[SimpleNamespace(st_size=10),SimpleNamespace(st_size=11)]
        copy.newest_checkpoint=Mock(return_value=candidate)
        with patch.object(auto.time,'sleep') as sleep:
            self.assertEqual(copy.wait_for_checkpoint(),verified)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[1.0,.01])

    def test_checkpoint_cancellation_and_watcher_error_precede_every_archive_read(self):
        for failure in ('cancelled','watcher'):
            with tempfile.TemporaryDirectory() as folder:
                copy=copy_at(folder)
                copy.early_checkpoint=Mock(side_effect=AssertionError('archive must not be read'))
                copy.newest_checkpoint=Mock(side_effect=AssertionError('archive must not be read'))
                copy.check=Mock(side_effect=auto.Cancelled() if failure=='cancelled' else None)
                copy.watcher_failed=Mock(return_value='native transaction failed' if failure=='watcher' else None)
                with self.assertRaises(auto.Cancelled if failure=='cancelled' else auto.KitError):copy.wait_for_checkpoint()
                copy.early_checkpoint.assert_not_called();copy.newest_checkpoint.assert_not_called()

    def test_checkpoint_partial_receipt_and_changed_archive_never_skip_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            copy=copy_at(folder);copy.check=Mock();copy.watcher_failed=Mock(return_value=None)
            path,output=receipt(folder);valid=path.read_bytes()
            path.write_text('{"output":',encoding='utf-8');output.write_bytes(b'changed')
            copy.newest_checkpoint=Mock(return_value=None);polls=[]
            def complete(seconds):
                polls.append(seconds)
                if len(polls)==1:path.write_bytes(valid)  # valid receipt still names changed bytes
                elif len(polls)==2:output.write_bytes(b'fully-written-match')
                else:raise AssertionError('completion should already be accepted')
            with patch.object(auto.time,'sleep',side_effect=complete):
                self.assertEqual(copy.wait_for_checkpoint(),output.resolve())
            self.assertEqual(polls,[.01,.01])

    def test_checkpoint_deadline_still_expires_without_an_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            copy=copy_at(folder);copy.check=Mock();copy.watcher_failed=Mock(return_value=None)
            copy.early_checkpoint=Mock(return_value=None);copy.newest_checkpoint=Mock(return_value=None)
            with patch.object(auto.time,'time',side_effect=[0,0,0,0,0,241]),patch.object(auto.time,'sleep') as sleep:
                with self.assertRaises(auto.KitError):copy.wait_for_checkpoint(timeout=240)
            sleep.assert_called_once_with(.01)


if __name__ == '__main__':
    unittest.main()
