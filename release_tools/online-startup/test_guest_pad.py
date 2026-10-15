"""Guest pad (kit_inject, Oct 15 redesign) and deterministic navigation (kit_prepare_drive); no emulator is opened.

The guest program is executed by a small MIPS interpreter (the emitted integer subset, real delay slots) against the
native poll's calling convention: a0 = port handle, a1 = the 18-byte raw buffer, s2 = port index.
"""
import struct
import sys
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_paths  # noqa: F401  (bootstrap)
import kit_inject as inject
import kit_prepare_drive as drive
import kit_prepare_auto as auto
import kit_prepare as prepare
from kit_codes import KitError

RETURN = 0xFEED0000
BUFFER = 0x00333914                      # record + 0x114 of port 0 (word aligned like the native record)


class Mips:
    def __init__(self):
        self.mem = {}
        self.r = [0] * 32
        self.callbacks = {}

    def write(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def read(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def w(self, a, v):
        self.write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def u(self, a):
        return struct.unpack('<I', self.read(a, 4))[0]

    def run(self, pc, budget=5000):
        pending = None
        for _ in range(budget):
            if pc == RETURN:
                return
            if pc in self.callbacks:
                self.callbacks[pc](self)
                pc = self.r[31]
                continue
            ins = self.u(pc)
            op, rs, rt, rd = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
            imm = ins & 0xFFFF
            simm = imm - 0x10000 if imm & 0x8000 else imm
            fn = ins & 63
            prev, pending = pending, None
            s = lambda v: v - (1 << 32) if v & 0x80000000 else v
            if ins == 0:
                pass
            elif op == 9:
                self.r[rt] = (self.r[rs] + simm) & 0xFFFFFFFF
            elif op == 15:
                self.r[rt] = imm << 16
            elif op == 13:
                self.r[rt] = self.r[rs] | imm
            elif op == 12:
                self.r[rt] = self.r[rs] & imm
            elif op == 35:
                self.r[rt] = self.u((self.r[rs] + simm) & 0xFFFFFFFF)
            elif op == 43:
                self.w((self.r[rs] + simm) & 0xFFFFFFFF, self.r[rt])
            elif op == 41:
                self.write((self.r[rs] + simm) & 0xFFFFFFFF, struct.pack('<H', self.r[rt] & 0xFFFF))
            elif op == 63:
                self.write((self.r[rs] + simm) & 0xFFFFFFFF, struct.pack('<Q', self.r[rt] & 0xFFFFFFFFFFFFFFFF))
            elif op == 55:
                self.r[rt] = struct.unpack('<Q', self.read((self.r[rs] + simm) & 0xFFFFFFFF, 8))[0]
            elif op in (4, 5):
                if (self.r[rs] == self.r[rt]) == (op == 4):
                    pending = pc + 4 + simm * 4
            elif op == 6:
                if s(self.r[rs] & 0xFFFFFFFF) <= 0:
                    pending = pc + 4 + simm * 4
            elif op in (2, 3):
                if op == 3:
                    self.r[31] = pc + 8
                pending = ((pc + 4) & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
            elif op == 0 and fn == 8:
                pending = self.r[rs]
            elif op == 0 and fn == 0x2D:
                self.r[rd] = self.r[rs] + self.r[rt]
            elif op == 0 and fn == 0x25:
                self.r[rd] = self.r[rs] | self.r[rt]
            elif op == 0 and fn == 0x27:
                self.r[rd] = ~(self.r[rs] | self.r[rt]) & 0xFFFFFFFF
            else:
                raise AssertionError(f'unsupported {ins:08x} at {pc:08x}')
            self.r[0] = 0
            pc = prev if prev is not None else pc + 4
        raise AssertionError('budget')


class GuestProgram(unittest.TestCase):
    def setUp(self):
        self.cpu = Mips()
        self.cpu.write(inject.CODE, inject.code())
        self.cpu.w(inject.CONTROL, inject.MAGIC)
        self.native = b'\x0f\xb0\x7f\x7f\x80\x80\x00\x00' + bytes(10)    # the keyboard holds some buttons
        self.cpu.callbacks[inject.rawread()] = self.raw

    def raw(self, c):
        c.write(c.r[5], self.native)
        c.r[2] = 18

    def poll(self, port=0):
        c = self.cpu
        c.r[4], c.r[5], c.r[18], c.r[29], c.r[31] = 0x1234, BUFFER, port, 0x1FF0000, RETURN
        c.r[16], c.r[19] = 0x5151, 0x7373
        c.run(inject.CODE)
        self.assertEqual((c.r[16], c.r[19], c.r[29]), (0x5151, 0x7373, 0x1FF0000))   # saved registers restored
        return struct.unpack('<H', c.read(BUFFER, 2))[0] ^ 0xFFFF, c.read(BUFFER, 18), c.r[2]

    def request(self, mask, hold, gap):
        c = self.cpu
        c.w(inject.CONTROL + inject.F['buttons'], mask)
        c.w(inject.CONTROL + inject.F['hold'], hold)
        c.w(inject.CONTROL + inject.F['gap'], gap)
        c.w(inject.CONTROL + inject.F['request'], c.u(inject.CONTROL + inject.F['done']) + 1)

    def test_rules_of_the_reservation(self):
        code = inject.code()
        self.assertLessEqual(inject.CODE + len(code), inject.CONTROL)
        words = struct.unpack(f'<{len(code) // 4}I', code)
        for word in words:                                   # no k0/k1 anywhere
            if word >> 26 not in (2, 3):
                self.assertNotIn((word >> 21) & 31, (26, 27))
                self.assertNotIn((word >> 16) & 31, (26, 27))
        self.assertEqual(words[0], 0x27BDFFE0)               # addiu sp, sp, -32 (16-byte aligned frame)

    def test_disabled_or_other_port_keeps_the_native_read(self):
        buttons, raw, length = self.poll()
        self.assertEqual(raw, self.native)                   # not enabled: untouched
        self.cpu.w(inject.CONTROL + inject.F['enable'], 1)
        _, raw, _ = self.poll(port=1)
        self.assertEqual(raw, self.native)

    def test_idle_enabled_port0_reads_neutral_not_the_keyboard(self):
        self.cpu.w(inject.CONTROL + inject.F['enable'], 1)
        buttons, raw, length = self.poll()
        self.assertEqual(buttons, 0)
        self.assertEqual(raw[:8], bytes.fromhex('ffff7f7f7f7f0000'))
        self.assertEqual(raw[8:], bytes(10))
        self.assertEqual(length, 18)

    def test_one_press_is_exactly_hold_polls_then_gap_then_done(self):
        c = self.cpu
        c.w(inject.CONTROL + inject.F['enable'], 1)
        self.request(inject.BUTTONS['cross'], 3, 2)
        seen = [self.poll()[0] for _ in range(8)]
        self.assertEqual(seen, [0x4000] * 3 + [0] * 5)
        self.assertEqual(c.u(inject.CONTROL + inject.F['done']), c.u(inject.CONTROL + inject.F['request']))
        self.assertEqual(c.u(inject.CONTROL + inject.F['polls']), 8)
        # The done word is written only after the gap: a host waiting for it never starts a second press early.
        self.request(inject.BUTTONS['left'] | inject.BUTTONS['cross'], 2, 3)
        dones = []
        for _ in range(6):
            self.poll()
            dones.append(c.u(inject.CONTROL + inject.F['done']) == c.u(inject.CONTROL + inject.F['request']))
        self.assertEqual(dones, [False] * 4 + [True, True])

    def test_wrong_magic_never_injects(self):
        self.cpu.w(inject.CONTROL, 0)
        self.cpu.w(inject.CONTROL + inject.F['enable'], 1)
        self.request(inject.BUTTONS['start'], 3, 3)
        self.assertEqual(self.poll()[1], self.native)


class FakePine:
    """A PINE client over a dict memory; `fail` raises a transient error on the n-th write."""
    def __init__(self, mem, fail=None):
        self.mem, self.fail, self.writes = mem, fail, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def write(self, a, data):
        self.writes += 1
        if self.fail and self.fail(self.writes, a):
            raise ConnectionResetError(10054, 'reset')
        for i, b in enumerate(data):
            self.mem[a + i] = b


class HostInjector(unittest.TestCase):
    def make(self, fail=None, patched=True):
        self.mem = {}
        word = inject.jal(inject.CODE) if patched else inject.jal(inject.rawread())
        self.mem.update({inject.site() + i: b for i, b in enumerate(struct.pack('<I', word))})
        if patched:                                   # PCSX2's patch engine applied the private pnach
            self.mem.update({inject.CODE + i: b for i, b in enumerate(inject.code())})
        self.writes = []

        def pine():
            client = FakePine(self.mem, fail)
            return client
        return inject.Injector(pine, sleep=lambda s: None)

    def u(self, a):
        return struct.unpack('<I', bytes(self.mem.get(a + i, 0) for i in range(4)))[0]

    def spy(self):
        original = FakePine.write
        test = self

        def write(client, a, data):
            test.writes.append(a)
            original(client, a, data)
        return patch.object(FakePine, 'write', write)

    def test_pine_writes_only_the_control_page_never_code(self):
        pad = self.make()
        with self.spy():
            pad.install()
            pad.remove()
        self.assertTrue(self.writes)
        self.assertTrue(all(inject.CONTROL <= a < inject.END for a in self.writes))
        self.assertNotEqual(inject.CODE >> 12, inject.CONTROL >> 12)        # separate 4 KiB pages
        self.assertEqual(self.u(inject.CONTROL), inject.MAGIC)
        self.assertEqual(self.u(inject.CONTROL + inject.F['enable']), 0)

    def test_install_waits_for_the_patch_engine(self):
        pad = self.make(patched=False)
        with self.assertRaises(inject.PadUnavailable):
            pad.install(timeout=0.05)

    def test_foreign_hook_program_or_control_is_refused(self):
        pad = self.make()
        self.mem.update({inject.site() + i: b for i, b in enumerate(struct.pack('<I', 0x0C123456))})
        with self.assertRaises(inject.InjectError):
            pad.install()
        pad = self.make()
        self.mem[inject.CODE + 8] ^= 0xFF
        with self.assertRaisesRegex(inject.InjectError, 'different program'):
            pad.install()
        pad = self.make()
        self.mem[inject.CONTROL + 0x400] = 1
        with self.assertRaisesRegex(inject.InjectError, 'not empty'):
            pad.install()

    def test_install_discards_an_interrupted_command(self):
        pad = self.make()
        self.mem.update({inject.CONTROL + i: b for i, b in enumerate(struct.pack('<11I', inject.MAGIC, 0, 5, 4, 0x4000,
                                                                                     3, 3, 2, 1, 1, 0))})
        pad.install()
        self.assertEqual(self.u(inject.CONTROL + inject.F['request']), self.u(inject.CONTROL + inject.F['done']))
        self.assertEqual([self.u(inject.CONTROL + inject.F[k]) for k in ('hold_left', 'gap_left', 'active')], [0, 0, 0])

    def test_transient_error_while_issuing_never_makes_a_second_press(self):
        failed = []

        def fail(n, a):
            if a == inject.CONTROL + inject.F['request'] and not failed:
                failed.append(n)
                return True
            return False
        pad = self.make()
        pad.install()
        pad.pine = lambda: FakePine(self.mem, fail)
        requests = []
        original = FakePine.write

        def spy(client, a, data):
            original(client, a, data)
            if a == inject.CONTROL + inject.F['request']:
                requests.append(struct.unpack('<I', data)[0])
                # the game takes the press at once
                self.mem.update({inject.CONTROL + inject.F['done'] + i: b for i, b in enumerate(data)})
        with patch.object(FakePine, 'write', spy):
            self.assertTrue(pad.press('cross', timeout=1))
        self.assertTrue(failed)
        self.assertEqual(requests, [1])                       # the retry rewrote the same request number

    def test_unanswering_pcsx2_is_unavailable_not_a_wrong_program(self):
        pad = self.make(fail=lambda n, a: True)
        with self.assertRaises(inject.PadUnavailable):
            pad.install(timeout=0.01)

    def test_pnach_holds_the_program_then_the_hook_word(self):
        lines = inject.pnach_text().decode().splitlines()
        patches = [l.split(',') for l in lines if l.startswith('patch=1,EE,')]
        code = inject.code()
        self.assertEqual(len(patches), len(code) // 4 + 1)
        self.assertEqual(int(patches[-1][2], 16), inject.site())
        self.assertEqual(int(patches[-1][4], 16), inject.jal(inject.CODE))
        self.assertTrue(all(int(p[2], 16) < inject.CONTROL for p in patches[:-1]))
        self.assertEqual(inject.pnach_name('SLUS_216.78', '428113c2'), 'SLUS-21678_428113C2_TTMPrivatePad.pnach')

    def test_export_conversion_unhooks_and_disables_but_keeps_the_program(self):
        # A checkpoint can be saved inside the program (or inside the raw read it called): the code must stay.
        ram = bytearray(0x8000000)
        struct.pack_into('<I', ram, inject.site(), inject.jal(inject.rawread()))
        self.assertEqual(inject.unhook_blocks(ram), [])
        struct.pack_into('<I', ram, inject.site(), inject.jal(inject.CODE))
        ram[inject.CODE:inject.CODE + len(inject.code())] = inject.code()
        struct.pack_into('<3I', ram, inject.CONTROL, inject.MAGIC, 1, 7)
        blocks = inject.unhook_blocks(ram)
        for a, d in blocks:
            ram[a:a + len(d)] = d
        self.assertEqual(struct.unpack_from('<I', ram, inject.site())[0], inject.jal(inject.rawread()))
        self.assertEqual(bytes(ram[inject.CODE:inject.CODE + len(inject.code())]), inject.code())
        self.assertEqual(struct.unpack_from('<I', ram, inject.CONTROL + inject.F['enable'])[0], 0)
        self.assertEqual(inject.unhook_blocks(ram), [])                    # idempotent
        ram[inject.CODE + 0x900] = 1
        with self.assertRaises(ValueError):
            inject.unhook_blocks(ram)
        ram[inject.CODE + 0x900] = 0
        struct.pack_into('<I', ram, inject.site(), 0x0C000001)
        with self.assertRaises(ValueError):
            inject.unhook_blocks(ram)

    def test_reservation_overlaps_no_reserved_guest_range(self):
        if not (ROOT / 'bt3-multifighter/analysis/SLUS_216.78').is_file():
            self.skipTest('An extracted game executable is required for native tests')
        import re
        import native_preparation
        import hub_mode
        import netplay_core
        ranges = [(0x02000000, 0x06000000, 'heap1'), (hub_mode.BASE, hub_mode.END, 'hub'),
                  (netplay_core.BASE, netplay_core.END, 'netplay core'), (0x07800000, 0x07B00000, 'service bulk')]
        ranges += [(lo, hi, 'native preparation') for lo, hi in native_preparation.protected_ranges()]
        for lo, hi, what in ranges:
            self.assertFalse(lo < inject.END and inject.CODE < hi, f'{what} {lo:#x}..{hi:#x}')
        named = set()
        for folder in (ROOT / 'bt3-multifighter/tools', ROOT / 'bt4-multifighter/tools',
                       ROOT / 'bt3-multifighter/online/netplay', ROOT / 'bt3-multifighter/online/netplay/modtools'):
            for path in folder.glob('*.py'):
                if path.name == 'kit_inject.py' or path.name.startswith('test_'):
                    continue
                for value in re.findall(r'0x0?[67][0-9A-Fa-f]{6}\b', path.read_text(encoding='utf-8-sig')):
                    if inject.CODE - 0x10000 <= int(value, 16) < inject.END + 0x10000:
                        named.add((path.name, value))
        self.assertEqual(named, set())                                     # no module names a word near it

class FakeGame:
    """The title flow as seen live on BT3 USA (Oct 15): title words and their answers."""
    def __init__(self, format_question=False):
        self.scene, self.word, self.log = 1, 0x406C0501, []
        self.logo_presses = 0
        self.format_question = format_question

    def sample(self):
        return dict(scene=self.scene, title_word=self.word, loop=0, pager=False, pager_state=0)

    def tap(self, *press, **kw):
        self.log.append('+'.join(press))
        low = self.word & 0xFFFF
        if self.word == 0x406C0501 and self.scene == 1 and not getattr(self, 'title_seen', False):
            self.logo_presses += 1
            if press == ('start',) and self.logo_presses >= 3:
                self.word, self.title_seen = 0x40703802, True
            return
        if low in (0x3802, 0x0501) and press == ('cross',):
            self.word = 0x406C6C01 if self.format_question else 0x406C0401
        elif low == 0x6C01 and press == ('cross',):
            self.word = 0x406C0401
        elif low == 0x0401 and press == ('cross',):
            self.word = 0x406C0101
        elif low == 0x0101 and press == ('left',):
            self.word = 0x406C0001
        elif low == 0x0001 and press == ('cross',):
            self.scene, self.word = 4, 0x406C0501
        elif low == 0x0101 and press == ('cross',):
            self.word = 0x406C0501                          # No: back to the title


class Navigator(drive.GuestDrive):
    def __init__(self, game):
        self.game = game
        self.pad = SimpleNamespace(polls=lambda client=None: self.polls, installed=True)
        self.polls = 0
        self.events = []

    def sample(self):
        self.polls += 40
        return self.game.sample()

    def tap(self, *press, **kw):
        self.game.tap(*press)

    def check(self):
        pass

    def event(self, what, **fields):
        self.events.append((what, fields))


class TitleFlow(unittest.TestCase):
    def test_never_creates_a_save_and_reaches_the_main_menu(self):
        game = FakeGame()
        with patch('native_map.PAL', False), patch('native_map.JPN', False):
            Navigator(game).drive_title(timeout=5)
        self.assertEqual(game.scene, 4)
        self.assertEqual(game.log[-4:], ['cross', 'cross', 'left', 'cross'])
        self.assertTrue(all(p == 'start' for p in game.log[:-4]))
        self.assertNotIn('left', game.log[:-2])               # Yes is chosen only for "start without saving"

    def test_an_unexpected_format_question_is_answered_no(self):
        game = FakeGame(format_question=True)
        nav = Navigator(game)
        with patch('native_map.PAL', False), patch('native_map.JPN', False):
            nav.drive_title(timeout=5)
        self.assertEqual(game.scene, 4)
        self.assertIn('format question', [e for e, _ in nav.events])

    def test_japanese_disc_accepts_with_circle(self):
        game = FakeGame()
        nav = Navigator(game)
        with patch('native_map.JPN', True):
            self.assertEqual(nav.buttons(), ('circle', 'cross'))

    def test_a_stuck_game_ends_with_a_named_bilingual_error(self):
        game = FakeGame()
        game.tap = lambda *p, **k: None
        with patch('native_map.PAL', False), patch('native_map.JPN', False):
            with self.assertRaises(KitError) as caught:
                Navigator(game).drive_title(timeout=0.3)
        self.assertEqual(caught.exception.code, 'TTM-NET-23')
        self.assertIn('main menu', str(caught.exception))


class NoHostKeys(unittest.TestCase):
    """The private copy never receives a window key message during preparation."""
    def copy(self):
        c = auto.PrepCopy.__new__(auto.PrepCopy)
        c.base = SimpleNamespace(dest=Path('.'), pid=123, cmd_pid=124, desktop='private-test', close=Mock())
        c.fast_loading = False
        return c

    def test_loading_speed_only_marks_the_phase(self):
        c = self.copy()
        with patch.object(auto.kit_win, 'post_key', side_effect=AssertionError('no keys')):
            c.loading_speed(True)
            self.assertTrue(c.fast_loading)
            c.loading_speed(False)
        self.assertFalse(c.fast_loading)

    def test_menu_presses_go_through_the_guest_pad(self):
        c = self.copy()
        c.tap = Mock()
        c.check = Mock()
        with patch.object(auto.kit_win, 'post_key', side_effect=AssertionError('no keys')), \
                patch('native_map.JPN', False):
            c.keys(['start', 'down', 'cross'])
        self.assertEqual([call.args for call in c.tap.call_args_list], [('start',), ('down',), ('cross',)])

    def test_hidden_profile_runs_at_private_speed_from_boot(self):
        import configparser
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            c = prepare.Prepare.__new__(prepare.Prepare)
            c.dest, c.orig, c.slot = root / 'copy', root / 'old', 29990
            c.args = SimpleNamespace(hidden=True)
            path = c.dest / 'game/runtime28/inis/PCSX2.ini'
            path.parent.mkdir(parents=True)
            path.write_text('[Framerate]\nNominalScalar=1\nTurboScalar=1\n')
            with patch.object(prepare, 'patches', return_value={}), patch.object(prepare.kit_win, 'WINDOWS', True):
                c.patch()
            result = configparser.ConfigParser(interpolation=None)
            result.read(path)
            self.assertEqual(result.getfloat('Framerate', 'NominalScalar'), prepare.PRIVATE_SPEED)
            self.assertEqual(result.getfloat('Framerate', 'TurboScalar'), prepare.PRIVATE_SPEED)


class BaseLifecycle(unittest.TestCase):
    def copy(self):
        c = auto.PrepCopy.__new__(auto.PrepCopy)
        c.base = SimpleNamespace(dest=Path('.'), pid=None, cmd_pid=None, desktop='private-test', close=Mock())
        c.state, c.engine, c.error = 'cold', 'ffa', None
        c.lock, c.cancel = threading.RLock(), threading.Event()
        c.reset_token = c.reset_thread = c.reset_owner = None
        c.reset_running = c.reset_deferred = c.warming = False
        c.suspended, c.suspended_tokens = [], {}
        c.fast_loading = False
        c.pad = None
        c.progress = c.say = c.event = Mock()
        c.make_copy = c.check = Mock()
        return c

    def test_missing_base_is_built_once_then_the_wanted_engine_is_committed(self):
        c = self.copy()
        steps = []
        c.cached_selector = Mock(return_value=False)
        c.at_map_select = Mock(return_value=True)

        def launch(cached=False):
            steps.append(('launch', cached))
            c.base.pid = 123
        c.launch = launch
        c.boot = lambda: steps.append('title')
        c.commit_mode = lambda: steps.append(('mode', c.engine))
        c.native_picks = lambda: steps.append('picks')
        c.remove_pad = lambda client=None: steps.append('unpad')
        c.cache_selector = lambda: steps.append('cache')
        c.restore_selector = lambda engine: steps.append(('restore', engine)) or setattr(c, 'engine', engine)
        with patch.object(auto.kit_win, 'pid_alive', return_value=False):
            self.assertEqual(c.warm(), 'warm')
        self.assertEqual(steps, [('launch', False), 'title', ('mode', 'teams'), 'picks', 'unpad', 'cache',
                                 ('restore', 'ffa')])

    def test_a_failed_build_is_retried_once_from_a_new_copy_never_looped(self):
        c = self.copy()
        c.cached_selector = Mock(return_value=False)
        c.close = Mock()
        launches = []

        def launch(cached=False):
            launches.append(cached)
            c.base.pid = 123
        c.launch = launch
        c.boot = Mock(side_effect=KitError('TTM-NET-23', what='stuck'))
        with patch.object(auto.kit_win, 'pid_alive', return_value=False):
            with self.assertRaises(KitError):
                c.warm()
        self.assertEqual(launches, [False, False])
        self.assertEqual(c.state, 'failed')

    def test_rejected_base_is_discarded_then_rebuilt_once(self):
        c = self.copy()
        c.selector_identity = {'id': 1}
        c.selector_cache = Mock()
        c.selector_cache.discard = Mock(return_value=['teams.json', 'teams.proof', 'teams.p2s'])
        c.cached_selector = Mock(return_value=True)
        c.close = Mock()
        c.at_map_select = Mock(return_value=True)
        steps = []

        def launch(cached=False):
            steps.append(('launch', cached))
            c.base.pid = 123
        c.launch = launch
        restores = []

        def restore(engine):
            restores.append(engine)
            if len(restores) == 1:
                raise ValueError('live selector differs')
            c.engine = engine
        c.restore_selector = restore
        c.build_base = lambda engine, retry=True: steps.append(('build', engine, retry))
        with patch.object(auto.kit_win, 'pid_alive', return_value=False):
            self.assertEqual(c.warm(), 'warm')
        self.assertEqual(steps, [('launch', True), ('build', 'ffa', False)])
        c.selector_cache.discard.assert_called_once_with('teams', {'id': 1})   # the rebuild publishes a new base

    def test_engine_switch_loads_the_base_without_menus(self):
        c = self.copy()
        c.state, c.engine, c.base.pid = 'warm', 'teams', 123
        c.cached_selector = Mock(return_value=True)
        c.close = Mock(side_effect=AssertionError('no reboot'))
        c.keys = c.tap = Mock(side_effect=AssertionError('no menu presses'))
        c.restore_selector = Mock()
        with patch.object(auto.kit_win, 'pid_alive', return_value=True):
            self.assertEqual(c.switch_engine('ffa'), 'warm')
        c.restore_selector.assert_called_once_with('ffa')


class RegionalAdapters(unittest.TestCase):
    """The guest pad's two native addresses go through A(): every reviewed disc maps them, and on each disc's own
    executable the hook site really is `jal` of the raw read (the verified predecessor)."""
    PROBE = '''
import json, struct, sys
sys.path.insert(0, sys.argv[1])
import kit_paths
import kit_inject as inject
from native_map import ADAPTER, DISCS
from prototype import elf_reader
from pathlib import Path
root = Path(sys.argv[2])
elf = root / 'analysis' / DISCS[ADAPTER]['serial_file']
out = dict(adapter=ADAPTER, site=inject.site(), raw=inject.rawread(), size=len(inject.code()),
           name=inject.pnach_name(DISCS[ADAPTER]['serial_file'], DISCS[ADAPTER]['crc']))
if elf.is_file():
    _, _, read = elf_reader(elf)
    out['word'] = struct.unpack('<I', read(inject.site(), 4))[0]
print(json.dumps(out))
'''

    def run_adapter(self, adapter):
        import json
        import os
        import subprocess
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'TTM_KIT_RUNTIME')}
        env['TTM_ONLINE_ADAPTER'] = env['TAGTEAM_ADAPTER'] = adapter    # the kit's standalone adapter switch
        result = subprocess.run([sys.executable, '-B', '-c', self.PROBE, str(ROOT / 'bt3-multifighter/online/netplay'),
                                 str(ROOT / 'bt3-multifighter')], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_every_reviewed_disc_maps_and_verifies_the_hook(self):
        seen = {}
        for adapter in ('bt3-usa', 'bt3-pal', 'bt3-jpn'):
            with self.subTest(adapter=adapter):
                out = self.run_adapter(adapter)
                self.assertEqual(out['adapter'], adapter)
                if 'word' not in out:
                    self.skipTest(f'{adapter} executable is not in this tree')
                self.assertEqual(out['word'], inject.jal(out['raw']))
                self.assertTrue(out['name'].endswith(inject.PNACH_SUFFIX) and '-' in out['name'].split('_')[0])
                seen[adapter] = (out['site'], out['raw'])
        if len(seen) == 3:
            self.assertNotEqual(seen['bt3-usa'], seen['bt3-pal'])     # really translated, not the USA addresses


class PrivateWatcherRematchDebounce(unittest.TestCase):
    def test_private_watcher_needs_two_rematch_observations_in_both_trees(self):
        edits = prepare.patches(29251)['game/tools/autopilot.py']
        debounce = [(o, n) for o, n in edits if 'SAY_REMATCH_LOADING' in o]
        self.assertEqual(len(debounce), 1)
        old, new = debounce[0]
        for project in ('bt3-multifighter', 'bt4-multifighter'):
            source = (ROOT / project / 'tools/autopilot.py').read_text(encoding='utf-8')
            self.assertEqual(source.count(old), 1, project)
            patched = source.replace(old, new)
            block = patched[patched.index("_private_rematch_seen', False)"):patched.index('log(say(SAY_REMATCH_LOADING))')]
            self.assertIn('continue', block)                       # the first observation only waits a poll
            self.assertIn('self._private_rematch_seen = False', block)


class KitMemoryCards(unittest.TestCase):
    def test_both_cards_are_identical_formatted_and_empty(self):
        sys.path.insert(0, str(ROOT / 'release_tools'))
        import make_online_memcards
        made = make_online_memcards.build()
        folder = ROOT / 'bt3-multifighter/online/match/runtime/memcards'
        if (folder / 'Mcd001.ps2').is_file():          # fetched or generated; ignored by Git
            one, two = (folder / 'Mcd001.ps2').read_bytes(), (folder / 'Mcd002.ps2').read_bytes()
            self.assertEqual(one, made)
        else:
            one = two = made
        self.assertEqual(one, two)
        self.assertEqual(len(one), 8650752)
        self.assertEqual(one[:28], b'Sony PS2 Memory Card Format ')
        self.assertEqual(struct.unpack_from('<4H', one, 40), (512, 2, 16, 0xFF00))
        root = 41 * 2 * 528                                   # allocatable cluster 0: '.' and '..' only
        self.assertEqual(struct.unpack_from('<HHL', one, root), (0x8427, 0, 2))
        self.assertEqual(struct.unpack_from('<HHL', one, root + 528), (0xA426, 0, 0))


class IdentityScope(unittest.TestCase):
    """The neutral base is keyed only on what changes its bytes (kit_selector_cache.identity)."""

    def setUp(self):
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.source = root / 'install' / 'game'
        dest = root / 'prep' / 'Tag Team Mod'
        self.executed = dest / 'game'                          # the copy's tools are the ones the probe runs
        (self.executed / 'tools').mkdir(parents=True)
        (self.executed / 'elf').mkdir()
        (self.executed / 'tools' / 'trainer.py').write_text('x = 1\n')
        self.calls = []
        self.generated = 'ab' * 32

        def copy_python(*args, timeout=0):
            self.calls.append(args)
            return 0, '"' + self.generated + '"\n', ''
        self.copy = SimpleNamespace(base=SimpleNamespace(dest=dest, copy_python=copy_python))

    def test_python_only_edit_regenerates_once_and_keeps_the_guest_identity(self):
        import kit_selector_cache as cache
        first = cache.guest_code(self.copy, self.source)
        self.assertEqual(cache.guest_code(self.copy, self.source), first)
        self.assertEqual(len(self.calls), 1)                    # remembered under the tool tree's digest
        (self.executed / 'tools' / 'trainer.py').write_text('x = 2  # a Python-only change\n')
        self.assertEqual(cache.guest_code(self.copy, self.source), first)
        self.assertEqual(len(self.calls), 2)

    def test_changed_guest_bytes_change_the_identity(self):
        import kit_selector_cache as cache
        first = cache.guest_code(self.copy, self.source)
        # A different size: the per-process hash memo is keyed on file identity (size and times), as real edits are.
        (self.executed / 'tools' / 'trainer.py').write_text('x = 3333\n')
        self.generated = 'cd' * 32
        self.assertNotEqual(cache.guest_code(self.copy, self.source), first)

    def test_a_tree_edited_during_generation_is_never_remembered(self):
        import kit_selector_cache as cache

        def edit_while_running(*args, timeout=0):
            (self.executed / 'tools' / 'trainer.py').write_text('x = 9  # edited meanwhile\n')
            return 0, '"' + self.generated + '"\n', ''
        self.copy.base.copy_python = edit_while_running
        with self.assertRaises(ValueError):
            cache.guest_code(self.copy, self.source)
        self.assertFalse((self.copy.base.dest.parent / cache.GUEST_MEMO).exists())

    def test_failed_generation_never_keys_a_base(self):
        import kit_selector_cache as cache
        self.copy.base.copy_python = lambda *a, timeout=0: (1, '', 'ImportError: x')
        with self.assertRaises(ValueError):
            cache.guest_code(self.copy, self.source)

    def test_identity_names_bytes_not_python_sources(self):
        import inspect
        import kit_selector_cache as cache
        text = inspect.getsource(cache.identity)
        for key in ('iso=', 'bios=', 'emulator=', 'guest=guest_code', 'pad=pad_code', 'config=', 'cards=',
                    'recipe=BASE_RECIPE'):
            self.assertIn(key, text)
        for gone in ('kit_prepare_auto', 'launchers=', "rglob('*') if path.is_file()\n             and '__pycache__'"):
            self.assertNotIn(gone, text)
        self.assertEqual(cache.pad_code(), inject.identity())


if __name__ == '__main__':
    unittest.main()
