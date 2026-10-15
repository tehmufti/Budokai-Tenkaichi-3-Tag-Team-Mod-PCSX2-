"""Private match-making copy speed and confirm guards (Oct 15 redesign); no emulator is opened.

Until kit 2.3 the copy navigated native menus at nominal speed with window key messages and held a turbo hotkey only
while loading; these tests guarded those key pulses. The Oct 15 redesign drives the copy from inside the game (kit_inject), so it
runs at its private speed from boot to export, and the tests now guard that nothing is ever sent to a window and that
the one match confirm is a single guest-pad press admitted only at the exact written map select.
"""
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
import kit_potara
import kit_spec
from kit_codes import KitError

MANAGER, OBJ, TABLE = 0x600000, 0x700000, 0x710000


class Memory:
    def __init__(self):
        self.m = {}
        self.closed = False

    def connect(self):
        return self

    def close(self):
        self.closed = True

    def read(self, a, n):
        return bytes(self.m.get(a + i, 0) for i in range(n))

    def write(self, a, data):
        for i, b in enumerate(data):
            self.m[a + i] = b

    def w(self, a, v):
        self.write(a, struct.pack('<I', v))

    def u(self, a):
        return struct.unpack('<I', self.read(a, 4))[0]


SPEC = dict(teams=[[dict(character=3, costume=0, potaras=[])], [dict(character=22, costume=1, potaras=[1, 4])]],
            stage=2, bgm=5, native=dict(time=90, com=2))


class ConfirmFixture(unittest.TestCase):
    def setUp(self):
        mem = self.mem = Memory()
        mem.w(auto.TEAM_OBJECT, OBJ)
        mem.w(auto.MANAGER, MANAGER)
        mem.w(MANAGER + 0x18, auto.TEAM_SELECT)
        mem.w(OBJ + 0x3C6C, 1)
        for s, side in enumerate(auto.SIDES):
            mem.w(OBJ + 0x8E8 + 4 * s, OBJ + side)
        mem.w(OBJ + auto.BGM_TABLE, TABLE)
        for i in range(auto.BGM_ROWS):
            mem.w(TABLE + 4 * i, (i + 3) % auto.BGM_ROWS)        # a permutation: the cursor is not the track
        self.taps = []
        self.removed = []
        self.late_start = None                                  # the game starts the match only after N polls
        self.started_by_tap = 1                                 # the n-th tap starts the native match
        c = self.copy = auto.PrepCopy.__new__(auto.PrepCopy)
        c.base = SimpleNamespace(dest=Path('.'), pid=123, cmd_pid=124, desktop='ttm-kit-prep-29990', close=Mock())
        c.slot, c.fast_loading, c.state = 29990, False, 'busy'
        c.pine = lambda timeout=3: mem
        c.ensure_pad = Mock()
        self.poll_count = [0]

        def polls(client=None):
            self.poll_count[0] += 10
            if self.late_start and self.taps and self.poll_count[0] >= self.late_start:
                self.start_now()
            return self.poll_count[0]
        c.pad = SimpleNamespace(polls=polls)
        c.check = c.progress = c.event = Mock()
        c.remove_pad = lambda client=None: self.removed.append((client, mem.u(auto.SCENE + 0x10)))
        c.tap = self.tap

    def tap(self, *names, hold=3, gap=4, client=None):
        self.assertIs(client, self.mem)                         # the confirm's own connection: no nested PINE
        self.assertEqual(hold, 3)
        self.taps.append(names)
        if len(self.taps) < self.started_by_tap or self.late_start:
            return
        self.start_now()

    def start_now(self):
        mem = self.mem
        if mem.u(auto.LOOP) == 1:
            return
        mem.w(auto.LOOP, 1)
        for s in range(2):
            side = OBJ + auto.SIDES[s]
            n = mem.u(side + 0x134)
            mem.w(auto.SCENE + 0xC0 + 0x270 * s, n)
            for j in range(n):
                rec = side + 0x30 * j
                costume, character = struct.unpack('<2i', mem.read(rec + 0x18, 8))
                at = auto.SCENE + 0xC4 + 0x270 * s + 100 * j
                mem.write(at, struct.pack('<3I', character, costume, 0))
                mem.write(at + 20, mem.read(rec + 0x20, 16))
        stage = mem.u(OBJ + 0x98C)
        mem.w(auto.SCENE + 0x1C, stage)
        mem.w(auto.SCENE + 0x28, stage)
        mem.w(auto.SCENE + 0x0C, mem.u(TABLE + 4 * mem.u(OBJ + auto.BGM_CURSOR)))


class GuestConfirm(ConfirmFixture):
    def test_one_pad_press_starts_the_written_match_then_the_pad_leaves(self):
        with patch.object(auto.kit_win, 'post_key', side_effect=AssertionError('no window keys')), \
                patch('native_map.JPN', False):
            result = self.copy.confirm(SPEC)
        self.assertEqual(self.taps, [('cross',)])
        self.assertEqual(result['members'], [[[3, 0, 0]], [[22, 1, 0]]])
        self.assertEqual(self.mem.u(auto.SCENE + 0x10), kit_spec.scene_time(90))
        self.assertEqual(len(self.removed), 1)
        self.assertIs(self.removed[0][0], self.mem)
        self.assertEqual(self.mem.read(auto.SCENE + 0x270 + 0xC4 + 20, 16), kit_potara.native([1, 4]))
        self.assertTrue(self.mem.closed)

    def test_japanese_disc_confirms_with_circle(self):
        with patch('native_map.JPN', True):
            self.copy.confirm(SPEC)
        self.assertEqual(self.taps, [('circle',)])

    def test_an_ignored_press_is_repeated_only_while_the_selector_still_waits(self):
        self.started_by_tap = 2
        with patch('native_map.JPN', False):
            self.copy.confirm(SPEC)
        self.assertEqual(self.taps, [('cross',), ('cross',)])

    def test_a_press_the_game_took_late_is_never_repeated(self):
        self.late_start = 600                                  # 60 polls after the press: well inside the window
        with patch('native_map.JPN', False):
            self.copy.confirm(SPEC)
        self.assertEqual(self.taps, [('cross',)])

    def test_a_selector_that_left_never_gets_a_press(self):
        self.mem.w(OBJ + 0x3C6C, 0)
        with self.assertRaises(KitError):
            self.copy.confirm(SPEC)
        self.assertEqual(self.taps, [])

    def test_a_started_other_match_is_refused_after_the_press(self):
        original = self.tap

        def other(*names, **kw):
            original(*names, **kw)
            self.mem.w(auto.SCENE + 0xC4, 77)                   # the game started someone else
        self.copy.tap = other
        with self.assertRaises(KitError) as caught, patch('native_map.JPN', False):
            self.copy.confirm(SPEC)
        self.assertEqual(caught.exception.code, 'TTM-NET-31')

    def test_no_start_after_four_presses_is_a_bounded_error(self):
        self.started_by_tap = 99
        with self.assertRaises(KitError) as caught, patch('native_map.JPN', False):
            self.copy.confirm(SPEC)
        self.assertEqual(len(self.taps), 4)
        self.assertEqual(caught.exception.code, 'TTM-NET-23')
        self.assertEqual(self.removed, [])                      # the copy is reset from its base, never exported


class NoWindowKeys(unittest.TestCase):
    def copy(self):
        c = auto.PrepCopy.__new__(auto.PrepCopy)
        c.base = SimpleNamespace(dest=Path('.'), pid=123, cmd_pid=124, desktop='private-test', close=Mock())
        c.fast_loading = False
        return c

    def test_loading_speed_never_posts_a_key(self):
        c = self.copy()
        with patch.object(auto.kit_win, 'post_key', side_effect=AssertionError('no keys')):
            for enabled in (True, True, False, True, False):
                c.loading_speed(enabled)
                self.assertEqual(c.fast_loading, enabled)

    def test_headless_flag_needs_an_owned_private_emulator(self):
        c = self.copy()
        c.base.desktop = None
        c.loading_speed(True)
        self.assertFalse(c.fast_loading)

    def test_return_to_select_loads_the_base_instead_of_menu_presses(self):
        c = self.copy()
        c.engine = 'ffa'
        c.cached_selector = Mock(return_value=True)
        c.watcher = Mock(return_value=dict(state='ACTIVE'))
        c.check = c.event = Mock()
        c.sample = Mock(return_value={})
        c.restore_selector = Mock()
        c.keys = c.tap = Mock(side_effect=AssertionError('no menu presses'))
        c.return_to_select()
        c.restore_selector.assert_called_once_with('ffa')

    def test_return_without_a_base_is_an_explained_error(self):
        c = self.copy()
        c.engine = 'teams'
        c.cached_selector = Mock(return_value=False)
        with self.assertRaises(KitError):
            c.return_to_select()


class PrivateINI(unittest.TestCase):
    def configure(self, hidden, windows, original):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        c = prepare.Prepare.__new__(prepare.Prepare)
        c.dest, c.orig, c.slot = root / 'copy', root / 'old', 29990
        c.args = SimpleNamespace(hidden=hidden)
        path = c.dest / 'game/runtime28/inis/PCSX2.ini'
        path.parent.mkdir(parents=True)
        path.write_text(original)
        with patch.object(prepare, 'patches', return_value={}), patch.object(prepare.kit_win, 'WINDOWS', windows):
            c.patch()
        result = configparser.ConfigParser(interpolation=None)
        result.read(path)
        self.assertEqual((c.orig / 'game/runtime28/inis/PCSX2.ini').read_text(), original)
        return result

    def test_hidden_windows_profile_runs_at_private_speed_on_d3d11(self):
        result = self.configure(True, True, '[EmuCore/GS]\nRenderer=7\n[Framerate]\nNominalScalar=1\nTurboScalar=1\n')
        self.assertEqual(prepare.PRIVATE_SPEED, 32.0)
        self.assertEqual(result.getfloat('Framerate', 'NominalScalar'), 32)
        self.assertEqual(result.getfloat('Framerate', 'TurboScalar'), 32)
        self.assertEqual(result.getint('EmuCore/GS', 'Renderer'), 3)   # D3D11: PCSX2 2.8 has no Null renderer
        self.assertTrue(result.getboolean('EmuCore/GS', 'VsyncEnable'))
        self.assertTrue(result.getboolean('EmuCore/GS', 'DisableMailboxPresentation'))

    def test_fifo_and_renderer_change_only_the_hidden_windows_builder(self):
        original = ('[EmuCore/GS]\nRenderer=7\nVsyncEnable=false\nDisableMailboxPresentation=false\n'
                    '[Framerate]\nNominalScalar=1\nTurboScalar=1\n')
        for hidden, windows in ((False, True), (True, False)):
            with self.subTest(hidden=hidden, windows=windows):
                result = self.configure(hidden, windows, original)
                self.assertEqual(result.getint('EmuCore/GS', 'Renderer'), 7)
                self.assertFalse(result.getboolean('EmuCore/GS', 'VsyncEnable'))
                self.assertFalse(result.getboolean('EmuCore/GS', 'DisableMailboxPresentation'))
                self.assertEqual(result.getfloat('Framerate', 'NominalScalar'), 32 if hidden else 1)


if __name__ == '__main__':
    unittest.main()
