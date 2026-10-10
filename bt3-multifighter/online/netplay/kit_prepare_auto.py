"""Automatic host preparation (spec 6): the host's game builds the lobby's match by itself, with nobody at its menus.

The host's PrepCopy is a PRIVATE COPY of its Tag Team Mod installation (kit_prepare.Prepare: the installation is only
read), running on a hidden desktop with the kit's blank memory card, keyboard pad 1 and no sound. It is warmed up as
soon as the lobby opens and kept at the game's map select between matches:
  boot()            logos -> title (u32(0x300EC8) == 0x40703802) -> New Game -> the blank card's two questions
                    (Cross = No, Left + Cross = Yes) -> main menu (scene 4) with the Modded Modes pager published
  commit_mode()     Select (only when the pager shows the original page) -> Team Battle (or Free-for-all: the
                    second row) -> 1 Player; the watcher's log line 'Modded Modes: Team Battle, 1 Player' (or
                    'Free-for-all, 1 Player') and scene 0x28 (Team Select). An engine change returns to the main
                    menu and selects the other mode; only an unhealthy copy reboots (1 v 1 uses the FFA engine).
  native_picks()    the fewest native presses that reach map select (one fighter per side, END twice)
A preparation then pays only for the match itself:
  settings          the COMPLETE online settings (kit_settings.match_settings: every key of the copy's mod) into the
                    copy's mod-settings.json: the host's offline values never reach an online match
  write_native()    Duel Time, CPU level, referee, CPU transformations off and destructible stage into the save block
                    *(A(0x2FF28C)) +0xC34..+0xC48 (read back)
  write_spec()      both columns (1..5 fighters each: character, colour, Z-items Normal), the stage and the music
                    (the BGM cursor at +0x9A0 whose table entry, table pointer +0x3C60, is the track) into the Team
                    Select object *(0x3B38D8) (pickers at +0x3D8 / +0x660, stage at +0x98C), read back, then Cross
  at loop == 1      SCENE+0x10 (Duel Time index) and both sides' 161-bit transformation availability sets
                    (SCENE+0x2D0 / +0x540): every transformation online, whatever the copy's save has unlocked
  read back         the SCENE counts, characters, colours and stage the game wrote (TTM-NET-31 when they differ)
  capture           the native held checkpoint, copied as capture.p2s after an exact whole-archive/CRC receipt
                    bound to this private owner; conversion applies the guarded normal release in the final archive
  convert           kit_prepare.convert with the spec (single view, players, the online writes, layout 3, verify)
  back to select    Start, Down, Down, Cross, Up, Cross (the watcher reloads its clean character-select checkpoint),
                    then the native picks again: the copy waits at map select for the next match. This happens in
                    the background AFTER the converted match is delivered, serialized by the copy's ownership lock.
The private builder runs ordinary boot and all native menu navigation at nominal speed. Only authenticated cached
selector restores and native resource loading hold accelerated turbo. Client games retain their enforced 1x profile.
Screenshot pauses are opt-in, separate from test hooks.
While the online match runs the copy's process tree is suspended (NtSuspendProcess) and resumed before the next
preparation; a copy that does not answer then (PINE, scene) is closed and started again (cold).
Windows only: the copy is driven by key messages to its hidden window.
"""
import json
import hashlib
import os
import shutil
import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import kit_paths
from native_map import A, GP, GPO
import kit_prepare

import kit_spec
import kit_potara
import kit_win
from kit_codes import KitError

SCENE, LOOP, MANAGER = A(0x331DC8), A(0x3337C0), A(0x2FF10C)
PAGER, PAGER_MAGIC = 0x076FF000, 0x324D4E42
TITLE_WORD = GP + GPO(-13224)
TITLE_VALUE = 0x40703802
TEAM_OBJECT, SIDES = A(0x3B38D8), (0x3D8, 0x660)
MAIN_OBJECT = A(0x3B0E80)
SAVE_POINTER = A(0x2FF28C)
SAVE_TIME, SAVE_COM, SAVE_REFEREE, SAVE_CPU1, SAVE_CPU2, SAVE_DESTRUCT = 0xC34, 0xC38, 0xC3C, 0xC40, 0xC44, 0xC48
TEAM_SELECT, MAIN_MENU, TITLE = 0x28, 4, 1
BGM_CURSOR, BGM_TABLE, BGM_ROWS = 0x9A0, 0x3C60, 25
MODE_ROWS = {'teams': 0, 'ffa': 1}                 # the Modded Modes page rows (Team Battle, Free-for-all)
MODE_LOG = {'teams': 'Modded Modes: Team Battle, 1 Player', 'ffa': 'Modded Modes: Free-for-all, 1 Player'}
ROSTER_COUNT = __import__('kit_adapter').roster_count()
AVAILABLE_QWORDS = ((1 << ROSTER_COUNT) - 1).to_bytes((ROSTER_COUNT + 63) // 64 * 8, 'little')     # bits 0..160
BLANK_CARD = kit_paths.MATCH / 'runtime' / 'memcards' / 'Mcd001.ps2'
BLANK_SHA256 = '47ebe237a3987f843fc1'          # (prefix) the installer's blank card, identical in the kit
PRIVATE_SPEED = kit_prepare.PRIVATE_SPEED
# Conservative step estimates for the accelerated private builder. The old
# 1x values and synchronous menu reset overstated warm-match waiting by a minute.
ETA = dict(copy=5, start=5, boot=15, mode=5, picks=5, selector=6, settings=1, confirm=1, loading=10, capture=1, convert=3,
           back=12)
WARM_STEPS = ('copy', 'start', 'boot', 'mode', 'picks')
WAIT_ES = {'its first screen': 'su primera pantalla', 'the main menu': 'el menú principal',
           'the Modded Modes page': 'la página Modded Modes', 'Team Select': 'la selección de equipos (Team Select)'}
PREP_STEPS = ('settings', 'confirm', 'loading', 'capture', 'convert')


class Cancelled(Exception):
    pass


def u32(c, a):
    return struct.unpack('<I', c.read(a, 4))[0]


def native_words(native):
    """{save offset: value} of the native Battle Settings for a spec's 'native' rules."""
    return {SAVE_TIME: kit_spec.TIMES.index(native['time']), SAVE_COM: native['com'],
            SAVE_REFEREE: native['referee'], SAVE_CPU1: 1, SAVE_CPU2: 1,
            SAVE_DESTRUCT: 0 if native['destructible'] else 1}


def held_receipt_owned(record, owner, emulator_pid):
    """A held archive is usable only by the current private preparation owner."""
    return (type(record) is dict and type(record.get('schema')) is int and record['schema'] == 1 and
            record.get('kind') == kit_prepare.HELD_EXPORT_KIND and
            record.get('status') == kit_prepare.HELD_EXPORT_STATUS and type(owner) is dict and
            type(owner.get('schema')) is int and owner['schema'] == 1 and
            type(owner.get('emulator_pid')) is int and owner['emulator_pid'] > 0 and owner['emulator_pid'] == emulator_pid and
            isinstance(owner.get('token'), str) and len(owner['token']) == 32 and
            all(c in '0123456789abcdef' for c in owner['token']) and
            type(record.get('owner')) is dict and type(record['owner'].get('schema')) is int and
            type(record['owner'].get('emulator_pid')) is int and record['owner'] == owner)


class PrepCopy:
    """The host's warm match-making copy. Every public step runs in a worker thread of the session process; one at a
    time (self.lock)."""

    def __init__(self, install, iso, slot, run_dir, say=print, test=False, capture_shots=False):
        self.install, self.iso, self.slot, self.say = install, iso, slot, say
        self.run_dir = Path(run_dir)
        args = SimpleNamespace(prep_pine_slot=slot, pine_slot=slot - 1, hidden=True, prep_timeout=600,
                               prep_settle=1.0)
        run = SimpleNamespace(args=args, say=say, install=install, run_dir=self.run_dir, iso=iso)
        self.base = kit_prepare.Prepare(run)
        self.base.desktop = f'ttm-kit-prep-{slot}'
        self.lock = threading.RLock()            # kit_controller.prepare_job holds it around prepare()
        self.state = 'cold'              # cold, warming, warm (at map select), busy, suspended, failed
        self.error = None
        self.suspended = []
        self.settings_written = None
        self.timeline = self.run_dir / 'prepare-auto.jsonl'
        self.cancel = threading.Event()
        self.warming = False             # a cancel stops a preparation, never the warm-up (check())
        self.progress = lambda step, pct=None, eta_s=None: None
        self.test = test
        # Fault/KO hooks do not add screenshot waits to a real startup benchmark.
        self.capture_shots = bool(capture_shots or os.environ.get('TTM_PREP_SHOTS') == '1')
        self.started = None
        self.engine = 'teams'            # the engine mode the copy is committed to (kit 2.0)
        self.checkpoint_before = None
        self.exports_before = set()
        self.fast_loading = False
        self.reset_thread = None
        self.reset_token = None
        self.reset_running = False
        self.reset_deferred = False
        self.reset_owner = None
        self.suspended_tokens = {}
        self.selector_cache = None
        self.selector_identity = None
        self.selector_lease = None
        self.selector_boot = None
        self.verified_iso = None
        self.export_owner = None
        self.held_export = None

    # ---- small helpers -------------------------------------------------------------------------------------------------
    def event(self, what, **fields):
        row = dict(t=round(time.time(), 2), event=what, **fields)
        try:
            with open(self.timeline, 'a', encoding='utf-8') as f:
                f.write(json.dumps(row, default=str) + '\n')
        except OSError:
            pass
        return row

    def check(self):
        if self.reset_running and self.reset_token is None:
            raise Cancelled()
        if self.cancel.is_set() and not self.warming:   # the warm-up always finishes: the next Ready is fast
            raise Cancelled()
        if self.base.pid and not kit_win.pid_alive(self.base.pid):
            raise KitError('TTM-NET-23', what='The host\'s match-making copy of the game closed by itself.',
                           fix='Press Ready again: the kit starts it again.',
                           what_es='La copia del juego del anfitrión para crear combates se cerró sola.',
                           fix_es='Pulsa Listo otra vez: el kit la vuelve a arrancar.')

    def sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.check()
            time.sleep(min(0.1, max(0.0, end - time.time())))

    def pine(self, timeout=3):
        import pine
        return pine.PineClient(port=self.slot, timeout=timeout)

    def sample(self):
        """scene, loop, pager words of the copy (None while PINE is busy: the watcher holds it for a moment)."""
        for _ in range(20):
            try:
                with self.pine() as c:
                    m = u32(c, MANAGER)
                    scene = u32(c, m + 0x18) if 0x100000 <= m < 0x2000000 else None
                    return dict(scene=scene, loop=u32(c, LOOP), pager=u32(c, PAGER) == PAGER_MAGIC,
                                pager_state=u32(c, PAGER + 4), title_word=u32(c, TITLE_WORD),
                                pager_page=u32(c, PAGER + 8), pager_owner=u32(c, PAGER + 20),
                                main_object=u32(c, MAIN_OBJECT),
                                title=u32(c, TITLE_WORD) == TITLE_VALUE)
            except Exception:  # noqa: BLE001 - PINE busy or the copy starting
                time.sleep(0.1)
        return dict(scene=None, loop=None, pager=False, pager_state=None, title=False)

    def wait(self, pred, timeout, what, step=0.3):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            self.check()
            last = self.sample()
            if pred(last):
                return last
            time.sleep(step)
        what_es = WAIT_ES.get(what, what)
        raise KitError('TTM-NET-23', what=f'The host\'s game did not reach {what} in {int(timeout)} s (last {last}).',
                       fix='Press Ready again: the kit starts the copy again.',
                       what_es=f'El juego del anfitrión no llegó a {what_es} en {int(timeout)} s (último estado {last}).',
                       fix_es='Pulsa Listo otra vez: el kit vuelve a arrancar la copia.')

    def press(self, button, hold=0.25):
        from native_map import JPN
        if JPN:
            button = {'cross': 'circle', 'triangle': 'cross'}.get(button, button)
        import kit_emu
        key = kit_emu.PAD1_KEYS[button]
        kit_win.post_key(self.base.pid, key, True, self.base.desktop)
        # Even a machine below the requested turbo rate sees at least two
        # ordinary video frames of the key, so its native 30Hz pad poll sees it.
        time.sleep(max(1 / 30, hold / PRIVATE_SPEED) if self.fast_loading else hold)
        kit_win.post_key(self.base.pid, key, False, self.base.desktop)

    def keys(self, buttons, gap=0.5):
        for b in buttons:
            self.check()
            self.press(b)
            self.sleep(max(1 / 15, gap / PRIVATE_SPEED) if self.fast_loading else gap)

    def watcher(self):
        folder = self.base.dest / 'game' / 'analysis' / 'autopilot'
        out = {}
        try:
            runs = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        except OSError:
            return out
        if not runs:
            return out
        try:
            out.update(json.loads((runs[-1] / 'status.json').read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass
        try:
            out['log'] = (runs[-1] / 'watcher.log').read_text(encoding='utf-8', errors='replace').splitlines()[-12:]
        except OSError:
            out['log'] = []
        return out

    def watcher_failed(self):
        w = self.watcher()
        if str(w.get('state', '')).upper() == 'FAILED':
            return str(w.get('message') or 'the mod reported a failure')
        return None

    def test_shot(self, name):
        """Test hooks only: the copy's own screenshot (F8, PCSX2's GS picture) into <run>/prep-shots/NAME.png. A
        picture that cannot be taken never stops the preparation."""
        if not self.test or not self.base.pid:
            return None
        try:
            return self._test_shot(name)
        except OSError as error:
            self.event('shot failed', shot=name, error=str(error)[:200])
            return None

    def _test_shot(self, name):
        import kit_emu
        snaps = self.base.dest / 'game' / 'runtime28' / 'snaps'
        before = set(snaps.glob('**/*.png')) if snaps.exists() else set()
        key = kit_emu.HOTKEYS['f8']
        kit_win.post_key(self.base.pid, key, True, self.base.desktop)
        time.sleep(0.15)
        kit_win.post_key(self.base.pid, key, False, self.base.desktop)
        end = time.time() + 15
        while time.time() < end:
            time.sleep(0.4)
            new = (set(snaps.glob('**/*.png')) if snaps.exists() else set()) - before
            if new:
                src = max(new, key=lambda p: p.stat().st_mtime)
                last = -1
                for _ in range(20):
                    size = src.stat().st_size
                    if size == last and size:
                        break
                    last = size
                    time.sleep(0.3)
                out = self.run_dir / 'prep-shots'
                out.mkdir(parents=True, exist_ok=True)
                target = out / f'{name}.png'
                for attempt in range(20):                # PCSX2 may still hold the file for a moment
                    try:
                        shutil.copyfile(src, target)
                        break
                    except PermissionError:
                        time.sleep(0.25)
                self.event('shot', shot=name, path=str(target))
                return target
        self.event('shot missing', shot=name)
        return None

    # ---- the copy itself ---------------------------------------------------------------------------------------------------
    def make_copy(self):
        self.progress('prep.copy', 0, ETA['copy'])
        self.base.copy_installation()
        self.base.patch()
        for name in ('Mcd001.ps2', 'Mcd002.ps2'):           # the kit's blank card: the title flow is always the same
            target = self.base.dest / 'game' / 'runtime28' / 'memcards' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BLANK_CARD, target)
        self.settings_written = None
        # Neutral templates must never depend on the host's offline options.
        # Every committed match reapplies its complete online configuration.
        self.write_settings({}, {}, 'en')
        import kit_selector_cache
        self.selector_cache = kit_selector_cache.SelectorCache()
        self.selector_identity = kit_selector_cache.identity(self)
        self.selector_lease = None
        self.selector_boot = None

    def cached_selector(self, engine):
        return bool(self.selector_cache and self.selector_identity and
                    self.selector_cache.available(engine, self.selector_identity))

    def restore_selector(self, engine):
        import kit_selector_cache
        if self.selector_lease is None:
            self.selector_lease = kit_selector_cache.find_watcher(self)
        result = self.selector_cache.restore(self, engine, self.selector_identity, self.selector_lease,
                                             boot=self.selector_boot)
        self.selector_boot = None
        self.event('selector restored', engine=engine, **result)
        return result

    def cache_selector(self):
        """Publish only a genuinely selected, clean native selector in our copy."""
        import kit_selector_cache
        if self.cached_selector(self.engine):
            return
        self.selector_lease = kit_selector_cache.find_watcher(self)
        state = self.base.save()
        record = self.selector_cache.publish(state, self.engine, self.selector_identity, self.selector_lease, self)
        self.event('selector cached', engine=self.engine, bytes=state.stat().st_size,
                   sha256=record['state_sha256'])

    def write_settings(self, gameplay, services, language):
        """The copy's mod-settings.json for this match (only when it changes): EVERY key set (the copy's own mod's
        defaults, then kit_settings.match_settings), so nothing of the host's offline settings reaches the match."""
        import kit_settings
        values = kit_settings.match_settings(gameplay, services, language)
        if values == self.settings_written:
            return
        code, out, err = self.base.copy_python('-c', 'import copy, json, sys; sys.path.insert(0, "tools"); import '
                                               'mod_settings; d = copy.deepcopy(mod_settings.DEFAULTS); '
                                               'd.update(json.loads(sys.argv[1])); mod_settings.save_settings(d); '
                                               'print(json.dumps(mod_settings.load_settings()))',
                                               json.dumps(values))
        if code != 0:
            raise KitError('TTM-NET-23', what=f'The match-making copy\'s mod settings could not be written: '
                                              f'{err.strip()[-300:]}', fix='Press Ready again.',
                           what_es=f'No se pudieron escribir los ajustes del mod de la copia: {err.strip()[-300:]}',
                           fix_es='Pulsa Listo otra vez.')
        try:
            shown = json.loads(out)
        except ValueError:
            shown = None
        if not isinstance(shown, dict):
            raise KitError('TTM-NET-23', what='The private builder did not return its saved effective settings.',
                           fix='Press Ready again.',
                           what_es='La copia privada no devolvió sus ajustes efectivos guardados.',
                           fix_es='Pulsa Listo otra vez.')
        wrong = {k: shown.get(k) for k, v in values.items() if k in shown and shown.get(k) != v and
                 not (isinstance(v, float) and isinstance(shown.get(k), (int, float)) and abs(v - shown[k]) < 1e-9)}
        if code != 0 or wrong:
            raise KitError('TTM-NET-23', what=f'The match-making copy\'s mod settings did not take effect: '
                                              f'{wrong or err[-200:]}', fix='Press Ready again.',
                           what_es=f'Los ajustes del mod de la copia no se aplicaron: {wrong or err[-200:]}',
                           fix_es='Pulsa Listo otra vez.')
        self.settings_written = values
        self.event('settings', values={k: values[k] for k in sorted(values)})

    def launch(self, cached=False):
        if not cached:
            self.loading_speed(False)
        # A verified neutral selector skips the boot/menu/pick steps. Do not
        # estimate those discarded steps while this fast path is running.
        self.progress('prep.selector' if cached else 'prep.start', 0,
                      ETA['selector'] if cached else ETA['start'])
        self.started = time.time()
        if os.name == 'nt':
            import kit_prepare_launch
            self.selector_boot = self.selector_cache.stage_boot(self, self.engine, self.selector_identity) \
                if cached else None
            kit_prepare_launch.launch(self, self.selector_identity, boot=self.selector_boot)
        else:
            self.base.launch()
        self.event('launched', pcsx2=self.base.pid, cmd=self.base.cmd_pid, desktop=self.base.desktop)
        if not cached:
            self.wait(lambda s: s['scene'] is not None, 120, 'its first screen')

    def close(self):
        """Close the copy's Play session (by PID: its cmd.exe tree and its PCSX2)."""
        # Invalidate a pending reset before taking its lock. Its normal check()
        # then stops it, rather than sending keys to an emulator being closed.
        self.reset_token = None
        self.reset_deferred = False
        self.reset_owner = None
        self.export_owner = None
        self.held_export = None
        with self.lock:
            self.loading_speed(False)
            self.resume()
            self.base.close()
            self.base.pid = self.base.cmd_pid = None
            self.suspended = []
            self.suspended_tokens = {}
            boot, self.selector_boot = self.selector_boot, None
            if boot is not None:
                import kit_selector_cache
                try:
                    kit_selector_cache._boot_path(self.base.dest, boot['claim']['state_path']).unlink(missing_ok=True)
                except (OSError, ValueError, KeyError):
                    pass
            if self.state != 'failed':
                self.state = 'cold'

    def loading_speed(self, enabled):
        """Accelerate cached restoration/resource loading; ordinary menus run at nominal speed."""
        enabled = bool(enabled and self.base.desktop and self.base.pid)
        if enabled == self.fast_loading:
            return
        base = self.base
        pid, desktop, slot = base.pid, base.desktop, getattr(self, 'slot', None)
        try:
            token = self._private_process_token(pid) if kit_win.WINDOWS else None
        except (OSError, RuntimeError, ValueError, TypeError):
            token = None
        expected = os.path.normcase(str(base.dest / 'game/runtime28/pcsx2-qt.exe'))

        def owned():
            return (self.base is base and base.pid == pid and base.desktop == desktop and
                    type(slot) is int and desktop == f'ttm-kit-prep-{slot}' and token is not None and
                    getattr(self, 'slot', None) == slot and kit_win.listener_pid(slot) == pid and
                    os.path.normcase(kit_win.process_path(pid)) == expected and
                    self._private_process_token(pid) == token)

        try:
            if not kit_win.post_key(pid, kit_prepare.PREP_SPEED_KEY, enabled, desktop):
                raise OSError('The private loading-speed key has no owned window')
            if self.base is not base or base.pid != pid or base.desktop != desktop:
                raise Cancelled()
        except BaseException:
            if self.base is base and base.pid == pid:
                self.fast_loading = False
            try:
                if token is not None and self._private_process_token(pid) == token:
                    kit_win.post_key(pid, kit_prepare.PREP_SPEED_KEY, False, desktop)
            except (OSError, RuntimeError, ValueError, TypeError):
                pass
            try:
                current_owner = owned()
            except (OSError, RuntimeError, ValueError, TypeError):
                current_owner = False
            if current_owner:
                self.close()
            raise
        else:
            self.fast_loading = enabled
        finally:
            # HoldTurbo captures the previous limiter. Releasing it restores
            # that original Nominal mode before any native menu navigation.
            if not enabled and self.base is base and base.pid == pid:
                self.fast_loading = False

    # ---- 6.2 boot, 6.4 mode, 6.5 picks -------------------------------------------------------------------------------
    def boot(self, timeout=240):
        self.loading_speed(False)
        self.progress('prep.boot', 0, ETA['boot'])
        end, tries = time.time() + timeout, 0
        while time.time() < end:
            self.check()
            s = self.sample()
            if s['scene'] == MAIN_MENU and s['pager']:
                self.event('main menu', tries=tries, **s)
                return s
            if s['scene'] == TITLE and s['title']:
                tries += 1
                self.keys(['cross'], gap=2.0)
                self.keys(['cross'], gap=2.0)
                self.keys(['left', 'cross'], gap=1.0)
                try:
                    self.wait(lambda x: x['scene'] == MAIN_MENU and x['pager'], 12, 'the main menu')
                except KitError:
                    self.event('boot retry', **self.sample())
                    self.test_shot('boot-retry')
                    self.keys(['triangle', 'triangle', 'triangle'], gap=1.0)
                continue
            if s['scene'] == TITLE:
                # PAL's language chooser precedes the logos and shares scene 1.
                # Its language object marker is distinct from the title packet.
                if __import__('native_map').PAL and s.get('title_word') == 0x001BA100:
                    self.keys(['cross'], gap=2.0)
                else:
                    self.keys(['start'], gap=1.5)
            else:
                self.sleep(0.5)
        raise KitError('TTM-NET-23', what='The host\'s match-making copy did not reach the game\'s main menu.',
                       fix='Press Ready again: the kit starts it again.',
                       what_es='La copia del anfitrión no llegó al menú principal del juego.', fix_es='Pulsa Listo otra vez: el kit la vuelve a arrancar.')

    def commit_mode(self):
        self.loading_speed(False)
        self.progress('prep.mode', 0, ETA['mode'])
        # A returned main menu may retain the previous pager's magic but be
        # disarmed (state0). Never press Cross into that stock Duel row while
        # the watcher is republishing its new, owned menu object.
        s = self.wait(lambda x: x['scene'] == MAIN_MENU and x['pager'] and
                      x['pager_state'] in (2, 4) and x.get('main_object') == x.get('pager_owner') and
                      bool(x.get('main_object')), 30, 'the main menu')
        if s['pager_state'] == 4:                        # the original page is up: Select shows Modded Modes
            self.keys(['select'], gap=2.0)
            s = self.wait(lambda x: x['pager_state'] == 2, 10, 'the Modded Modes page')
        # Selector cancellation returns to its remembered submenu, not always
        # the root page. Normalize both page and effective row before accepting.
        for _ in range(3):
            if s.get('pager_page') == 0:
                break
            self.keys(['triangle'], gap=.6)
            s = self.sample()
        if s.get('pager_page') != 0:
            raise KitError('TTM-NET-23', what='The host\'s mod menu did not return to its mode list.',
                           fix='Press Ready again.')
        with self.pine(5) as c:
            obj = u32(c, MAIN_OBJECT)
            count = u32(c, obj + 0x144)
            if not 1 <= count <= 12 or obj != u32(c, PAGER + 20):
                raise KitError('TTM-NET-24', what='The host\'s mod menu ownership changed.')
            row = ((u32(c, obj + 0x148) + u32(c, obj + 0x10C) + 1) & 0xFFFFFFFF) % count
        self.keys(['down'] * ((MODE_ROWS[self.engine] - row) % count), gap=.6)
        self.keys(['cross'], gap=2.0)                    # Team Battle / Free-for-all
        self.keys(['cross'], gap=1.0)                    # 1 Player (first row)
        s = self.wait(lambda x: x['scene'] == TEAM_SELECT and x['loop'] == 0, 30, 'Team Select')
        end = time.time() + 30
        while time.time() < end:
            self.check()
            log = self.watcher().get('log') or []
            if self.watcher().get('battle_mode') == self.engine and self.watcher().get('humans') == 1:
                self.event('mode committed', engine=self.engine, **s)
                return
            self.sleep(0.5)
        raise KitError('TTM-NET-23', what='The host\'s game did not open Modded Modes > Team Battle.',
                       fix='Press Ready again: the kit starts it again.',
                       what_es='El juego del anfitrión no abrió Modded Modes > Team Battle.', fix_es='Pulsa Listo otra vez: el kit la vuelve a arrancar.')

    def team_word(self, c, offset, side=None):
        obj = u32(c, TEAM_OBJECT)
        return u32(c, obj + (SIDES[side] if side is not None else 0) + offset)

    def obj_word(self, offset, side=None):
        for _ in range(20):
            try:
                with self.pine() as c:
                    return self.team_word(c, offset, side)
            except Exception:  # noqa: BLE001 - PINE busy
                time.sleep(0.1)
        return None

    def native_picks(self):
        """One fighter per side (the cursor's: always unlocked), END twice: the map select."""
        self.loading_speed(False)
        # A restored neutral map selector is already finished. Confirming END
        # here would instead start an unwanted native fight.
        if self.at_map_select():
            return
        self.progress('prep.picks', 0, ETA['picks'])
        self.sleep(3.0 / (PRIVATE_SPEED if self.fast_loading else 1.0))  # selector intro
        for side in (0, 1):
            for _ in range(4):
                if (self.obj_word(0x134, side) or 0) >= 1:
                    break
                self.keys(['cross'], gap=1.3)           # character, Normal, colour 1
            if (self.obj_word(0x134, side) or 0) < 1:
                raise KitError('TTM-NET-23', what=f'The host\'s game did not take a fighter for team {side + 1}.',
                               fix='Press Ready again.',
                               what_es=f'El juego del anfitrión no tomó un luchador para el equipo {side + 1}.',
                               fix_es='Pulsa Listo otra vez.')
            for _ in range(8):
                if self.obj_word(0x12C, side) == 5:
                    break
                self.keys(['right'], gap=0.6)
            if self.obj_word(0x12C, side) != 5:
                raise KitError('TTM-NET-23', what='The host\'s game did not reach END on the team screen.',
                               fix='Press Ready again.',
                               what_es='El juego del anfitrión no llegó a END en la pantalla de equipos.', fix_es='Pulsa Listo otra vez.')
            self.keys(['cross'], gap=2.5)
            if side == 0 and self.obj_word(0x13C, 0) != 8:
                raise KitError('TTM-NET-23', what='The host\'s game did not finish team 1.', fix='Press Ready again.',
                               what_es='El juego del anfitrión no terminó el equipo 1.', fix_es='Pulsa Listo otra vez.')
        end = time.time() + 15
        while time.time() < end and self.obj_word(0x3C6C) != 1:
            self.sleep(0.3)
        if self.obj_word(0x3C6C) != 1:
            raise KitError('TTM-NET-23', what='The host\'s game did not reach the map select.', fix='Press Ready again.',
                           what_es='El juego del anfitrión no llegó a la selección de escenario.', fix_es='Pulsa Listo otra vez.')
        self.event('map select')

    def at_map_select(self):
        s = self.sample()
        return s['scene'] == TEAM_SELECT and s['loop'] == 0 and self.obj_word(0x3C6C) == 1

    def at_select(self):
        s = self.sample()
        return s['scene'] == TEAM_SELECT and s['loop'] == 0

    # ---- the whole warm-up (lobby open) --------------------------------------------------------------------------------
    def warm(self):
        """Copy, start, boot, Team Battle, map select. Leaves the copy warm (at map select)."""
        with self.lock:
            return self._warm()

    def _warm(self):
        before = self.warming
        self.warming = True
        try:
            return self._warm_steps()
        finally:
            self.warming = before

    def _warm_steps(self):
        self._finish_pending_reset()
        if self.state == 'suspended':
            self._resume_checked()
        if self.state == 'warm' and self.base.pid and kit_win.pid_alive(self.base.pid):
            return 'warm'
        self.state = 'warming'
        self.error = None
        t0 = time.time()
        try:
            if not (self.base.pid and kit_win.pid_alive(self.base.pid)):
                self.make_copy()
                self.check()
                if self.cached_selector(self.engine):
                    self.launch(cached=True)
                    self.loading_speed(True)
                    try:
                        self.restore_selector(self.engine)
                    except Cancelled:
                        raise
                    except Exception as error:
                        # Reject the cache and reboot normally; never leave a
                        # partial load or failed worker authorized for a match.
                        self.event('selector rejected', error=str(error)[:300])
                        self.close()
                        self.state = 'warming'
                        # Closing restores temporary presentation/core settings.
                        # Rebuild the isolated profile and its checked identity
                        # before ordinary boot; never reuse the pre-close one.
                        self.make_copy()
                        self.check()
                        self.launch()
                        self.loading_speed(False)
                        self.boot()
                        self.commit_mode()
                else:
                    self.launch()
                    self.loading_speed(False)
                    self.boot()
                    self.commit_mode()
            elif not self.at_select():
                self.close()
                return self._warm_steps()
            if not self.at_map_select():
                self.native_picks()
            self.cache_selector()
            self.state = 'warm'
            self.event('warm', seconds=round(time.time() - t0, 1))
            self.say(f'The host\'s match-making copy is ready ({time.time() - t0:.0f} s).')
            return 'warm'
        except Cancelled:
            self.close()
            raise
        except BaseException as error:
            self.state = 'failed'
            self.error = str(error)
            self.event('warm failed', error=str(error)[:500])
            self.close()
            self.state = 'failed'
            raise
        finally:
            self.loading_speed(False)

    def switch_engine(self, engine):
        """Switch a healthy menu copy without paying for another game boot."""
        if engine not in MODE_ROWS:
            raise ValueError('Unknown preparation engine')
        with self.lock:
            self._finish_pending_reset()
            if self.state == 'suspended':
                self._resume_checked()
            if engine == self.engine:
                return self._warm()
            self.event('engine change', old=self.engine, new=engine)
            previous = self.warming
            self.warming = True
            try:
                if self.base.pid and kit_win.pid_alive(self.base.pid):
                    if self.cached_selector(engine) and self.at_map_select():
                        self.loading_speed(True)
                        self.restore_selector(engine)
                        self.event('engine switched cached', engine=engine)
                        return 'warm'
                    self.loading_speed(False)
                    self.state = 'warming'
                    end = time.time() + 30
                    while time.time() < end:
                        self.check()
                        state = self.sample()
                        if state['scene'] == MAIN_MENU and state['pager']:
                            self.engine = engine
                            self.commit_mode()
                            self.native_picks()
                            self.cache_selector()
                            self.state = 'warm'
                            self.event('engine switched', engine=engine)
                            return 'warm'
                        self.keys(['triangle'], gap=.3)
                    self.event('engine menu return failed')
                self.close()
                self.engine = engine
                self.state = 'cold'
                return self._warm()
            finally:
                self.loading_speed(False)
                self.warming = previous

    # ---- 6.3 / 6.5: one match ------------------------------------------------------------------------------------------------
    def write_native(self, spec):
        words = native_words(spec['native'])
        for _ in range(3):
            try:
                with self.pine(5) as c:
                    base = u32(c, SAVE_POINTER)
                    if not 0x100000 <= base < 0x2000000:
                        raise KitError('TTM-NET-23', what=f'The game\'s save data pointer is {base:#x}.',
                                       fix='Press Ready again.',
                                       what_es=f'El puntero de los datos guardados del juego es {base:#x}.',
                                       fix_es='Pulsa Listo otra vez.')
                    for off, value in words.items():
                        c.write(base + off, struct.pack('<I', value))
                    back = {off: u32(c, base + off) for off in words}
                if back == words:
                    self.event('native settings', base=hex(base), words={hex(k): v for k, v in words.items()})
                    return base
            except KitError:
                raise
            except Exception:  # noqa: BLE001 - PINE busy
                time.sleep(0.2)
        raise KitError('TTM-NET-31', what='The match settings could not be written into the host\'s game.',
                       what_es='No se pudieron escribir los ajustes del combate en el juego del anfitrión.')

    def write_spec(self, c, spec):
        obj = u32(c, TEAM_OBJECT)
        if u32(c, u32(c, MANAGER) + 0x18) != TEAM_SELECT or u32(c, obj + 0x3C6C) != 1:
            raise KitError('TTM-NET-23', what='The host\'s game left the map select.', fix='Press Ready again.',
                           what_es='El juego del anfitrión salió de la selección de escenario.', fix_es='Pulsa Listo otra vez.')
        for s, team in enumerate(spec['teams']):
            side = obj + SIDES[s]
            if u32(c, obj + 0x8E8 + 4 * s) != side:
                raise KitError('TTM-NET-24', what='The team screen of the host\'s game is not the one the kit knows.',
                               what_es='La pantalla de equipos del juego del anfitrión no es la que conoce el kit.')
            fighters = team
            for r in range(5):
                rec = side + 0x30 * r
                if r < len(fighters):
                    c.write(rec + 0x14, struct.pack('<3i', 0, fighters[r]['costume'], fighters[r]['character']))
                    c.write(rec + 0x20, kit_potara.native(fighters[r].get('potaras', [])))
                else:
                    c.write(rec + 0x14, struct.pack('<3i', 0, 0, -1))
                    c.write(rec + 0x20, bytes(16))
            c.write(side + 0x134, struct.pack('<I', len(fighters)))
        c.write(obj + 0x98C, struct.pack('<I', spec['stage']))
        table = u32(c, obj + BGM_TABLE)
        cursor = None
        if 0x100000 <= table < 0x2000000:
            rows = struct.unpack(f'<{BGM_ROWS}I', c.read(table, 4 * BGM_ROWS))
            cursor = next((i for i, v in enumerate(rows) if v == spec['bgm']), None)
        if cursor is None:
            raise KitError('TTM-NET-31', what=f'The host\'s game offers no music track {spec["bgm"] + 1}.',
                           what_es=f'El juego del anfitrión no ofrece la pista de música {spec["bgm"] + 1}.')
        c.write(obj + BGM_CURSOR, struct.pack('<I', cursor))
        back = []
        for s in range(2):
            side = obj + SIDES[s]
            n = u32(c, side + 0x134)
            back.append([list(struct.unpack('<3i', c.read(side + 0x30 * r + 0x14, 12))) for r in range(n)])
        want = [[[0, f['costume'], f['character']] for f in team] for team in spec['teams']]
        if back != want or u32(c, obj + 0x98C) != spec['stage'] or u32(c, obj + BGM_CURSOR) != cursor:
            raise KitError('TTM-NET-31', what=f'The team screen did not take the lobby\'s teams (read back {back}).',
                           what_es=f'La pantalla de equipos no aceptó los equipos de la sala (leído: {back}).')
        for s, team in enumerate(spec['teams']):
            for r, fighter in enumerate(team):
                if c.read(obj + SIDES[s] + 0x30*r + 0x20, 16) != kit_potara.native(fighter.get('potaras', [])):
                    raise KitError('TTM-NET-31', what='The native selector did not accept the Potara loadout.',
                                   what_es='El selector nativo no aceptó los Pótaras equipados.')
        return obj

    def confirm(self, spec, cancel_ok=True):
        """Write the spec, press Cross, and at loop == 1 the Duel Time and the transformation sets; returns what the
        game wrote into SCENE."""
        self.progress('prep.confirm', 0, ETA['confirm'])
        time_word = kit_spec.scene_time(spec['native']['time'])
        for attempt in range(5):
            try:
                c = self.pine(5)
                c.connect()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            raise KitError('TTM-NET-23', what='The host\'s game does not answer.', fix='Press Ready again.',
                           what_es='El juego del anfitrión no responde.', fix_es='Pulsa Listo otra vez.')
        try:
            base = self.base
            pid, desktop, slot = base.pid, base.desktop, getattr(self, 'slot', None)
            fast = self.fast_loading
            guarded = fast and kit_win.WINDOWS
            token = self._private_process_token(pid) if guarded else None
            expected = os.path.normcase(str(base.dest / 'game/runtime28/pcsx2-qt.exe'))

            def captured_live():
                try:
                    return (token is not None and self._private_process_token(pid) == token and
                            os.path.normcase(kit_win.process_path(pid)) == expected)
                except (OSError, RuntimeError, ValueError, TypeError):
                    return False

            def require_owner():
                if guarded and not (self.base is base and base.pid == pid and base.desktop == desktop and
                        type(slot) is int and desktop == f'ttm-kit-prep-{slot}' and self.slot == slot and
                        kit_win.listener_pid(slot) == pid and captured_live()):
                    raise KitError('TTM-NET-23', what='The private match-confirm owner changed.',
                                   fix='Press Ready again.',
                                   what_es='Cambió la copia privada que confirma el combate.', fix_es='Pulsa Listo otra vez.')

            def close_uncertain_input():
                # A failed delivery may leave the original key held. Never
                # terminate a replacement PID or another private/client VM.
                if captured_live():
                    try:
                        kit_win.kill_tree(pid)
                    except (OSError, RuntimeError, ValueError, TypeError):
                        pass
                    if self.base is base and base.pid == pid:
                        self.fast_loading = False
                        self.state = 'cold'

            require_owner()
            obj = self.write_spec(c, spec)
            self.event('spec written', teams=kit_spec.teams_of(spec), stage=spec['stage'])
            self.check()
            # One input is admitted only while the exact written selector
            # still owns map select and the native match has not started.
            if (u32(c, LOOP) != 0 or u32(c, TEAM_OBJECT) != obj or
                    u32(c, u32(c, MANAGER) + 0x18) != TEAM_SELECT or
                    u32(c, obj + 0x3C6C) != 1):
                raise KitError('TTM-NET-23', what="The host's game left the written map selector before confirm.",
                               fix='Press Ready again.',
                               what_es='El juego del anfitrión salió del selector escrito antes de confirmar.',
                               fix_es='Pulsa Listo otra vez.')
            key = __import__('kit_emu').PAD1_KEYS['circle' if __import__('native_map').JPN else 'cross']
            def await_native_start():
                started = time.time()
                while time.time() - started < 15:
                    self.check()
                    require_owner()
                    if u32(c, LOOP) == 1:
                        return started
                    time.sleep(0.005)
                raise KitError('TTM-NET-23', what='The host\'s game did not start the match after the confirm.',
                               fix='Press Ready again.',
                               what_es='El juego del anfitrión no empezó el combate tras confirmarlo.', fix_es='Pulsa Listo otra vez.')

            primary, delivery_failed = None, False
            try:
                try:
                    delivered = kit_win.post_key(pid, key, True, desktop)
                except BaseException:
                    delivery_failed = guarded
                    raise
                if guarded and not delivered:
                    delivery_failed = True
                    raise KitError('TTM-NET-23', what='The private match-confirm key has no owned window.',
                                   fix='Press Ready again.',
                                   what_es='La tecla para confirmar el combate no tiene una ventana propia.',
                                   fix_es='Pulsa Listo otra vez.')
                if guarded:
                    # Queued host key events can both arrive between pad polls.
                    # Admit one held Cross and release it at the native start acknowledgement.
                    t0 = await_native_start()
                else:
                    time.sleep(1 / 120 if fast else .2)
            except BaseException as error:
                primary = error
                raise
            finally:
                try:
                    if not guarded or captured_live():
                        released = kit_win.post_key(pid, key, False, desktop)
                        if guarded and not released:
                            raise KitError('TTM-NET-23', what='The private match-confirm key could not be released.',
                                           fix='Press Ready again.',
                                           what_es='No se pudo soltar la tecla para confirmar el combate.',
                                           fix_es='Pulsa Listo otra vez.')
                except BaseException:
                    delivery_failed = guarded
                    if primary is None:
                        raise
                finally:
                    if delivery_failed:
                        close_uncertain_input()
            if not guarded:
                t0 = await_native_start()
            self.check()
            require_owner()
            c.write(SCENE + 0x10, struct.pack('<I', time_word))
            for s, team in enumerate(spec['teams']):
                c.write(SCENE + 0x270 * s + 0x2D0, AVAILABLE_QWORDS)
                # Normalize extra AI levels before their private contexts initialize. BT4
                # otherwise inherits a different saved difficulty for reserve fighters.
                for j in range(1, len(team)):
                    c.write(SCENE + 0x270*s + 0xC4 + 100*j + 12,
                            struct.pack('<I', kit_spec.COM_CODES[spec['native']['com']]))
            after = round(time.time() - t0, 3)
            counts = [u32(c, SCENE + 0xC0 + 0x270 * s) for s in range(2)]
            members = [[[u32(c, SCENE + 0xC4 + 0x270 * s + 100 * j + o) for o in (0, 4, 8)]
                        for j in range(min(counts[s], 5))] for s in range(2)]
            stage = (u32(c, SCENE + 0x1C), u32(c, SCENE + 0x28))
            got_time = u32(c, SCENE + 0x10)
            got_bgm = u32(c, SCENE + 0x0C)
            equipment = [[c.read(SCENE + 0x270*s + 0xC4 + 100*j + 20, 16).hex()
                          for j in range(len(team))] for s, team in enumerate(spec['teams'])]
        finally:
            c.close()
        want = [[[f['character'], f['costume'], 0] for f in team] for team in spec['teams']]
        want_equipment = [[kit_potara.native(f.get('potaras', [])).hex() for f in team] for team in spec['teams']]
        self.event('confirmed', after=after, counts=counts, members=members, stage=stage, time=got_time, bgm=got_bgm)
        if members != want or stage != (spec['stage'], spec['stage']) or got_time != time_word or \
                got_bgm != spec['bgm'] or equipment != want_equipment:
            raise KitError('TTM-NET-31', what=f'The host\'s game started another match than the lobby\'s (teams '
                                              f'{members}, stage {stage}, time index {got_time}, music {got_bgm}).',
                           what_es=f'El juego del anfitrión empezó otro combate distinto al de la sala (equipos '
                                   f'{members}, escenario {stage}, índice de tiempo {got_time}).')
        return dict(counts=counts, members=members, stage=stage)

    def wait_for_fight(self, timeout=240):
        """kit_prepare's capture rule: live fight, mod Team Battle, the watcher ACTIVE and the combat services
        attached, for a moment."""
        self.progress('prep.loading', 0, ETA['loading'])
        end = time.time() + timeout
        live_since = None
        t0 = time.time()
        last = None
        prev_clock = None
        while time.time() < end:
            self.check()
            failed = self.watcher_failed()
            if failed:
                raise KitError('TTM-NET-23', what=f'The mod in the host\'s match-making copy failed: {failed}',
                               fix='Press Ready again: the kit starts the copy again.',
                               what_es=f'El mod de la copia del anfitrión falló: {failed}', fix_es='Pulsa Listo otra vez: el kit vuelve a arrancar la copia.')
            try:
                s = self.base.sample()
            except Exception:  # noqa: BLE001 - PINE busy
                time.sleep(0.2)
                continue
            s['watcher'] = self.base.watcher_state()
            key = (s['director'], s['mode'], s['watcher'], s['armed'], s['hold'], s['worker'])
            if key != last:
                last = key
                self.event('loading', **s)
            pct = min(95, int((time.time() - t0) * 100 / ETA['loading']))
            self.progress('prep.loading', pct, max(1, ETA['loading'] - (time.time() - t0)))
            in_fight = s['director'] == 3 and s['result'] == 0
            attached = (in_fight and s['mode'] == 1 and s['watcher'] == 'ACTIVE' and s['prep_magic'] == 0x42545032
                        and s['armed'] == 1 and s['hold'] == 0 and (s['worker'] == 1 or s['fighters'] <= 2))
            # The battle clock runs (its 30 Hz ticks moved since the last sample): no special's pause holds the
            # fighters and the clock (Special pause 'all' freezes everyone else for the whole special), so both
            # players start moving at once. A clock that stays held 15 s does not block the capture.
            ticking = s.get('clock') is not None and s.get('clock') != prev_clock
            prev_clock = s.get('clock')
            if attached:
                live_since = live_since or time.time()
                if time.time() - live_since >= 1.0 and (ticking or time.time() - live_since >= 15.0):
                    s['clock_running'] = ticking
                    return s
            else:
                live_since = None
            time.sleep(0.1)
        raise KitError('TTM-NET-23', what=f'The host\'s match did not start within {int(timeout)} s.',
                       fix='Press Ready again: the kit starts the copy again.',
                       what_es=f'El combate del anfitrión no empezó en {int(timeout)} s.', fix_es='Pulsa Listo otra vez: el kit vuelve a arrancar la copia.')

    def newest_checkpoint(self):
        """The playable checkpoint the copy's watcher named last (kit_prepare.checkpoint_from_log), or None."""
        folder = self.base.dest / 'game' / 'analysis' / 'autopilot'
        try:
            runs = sorted((q for q in folder.iterdir() if q.is_dir()), key=lambda q: q.stat().st_mtime)
            lines = (runs[-1] / 'watcher.log').read_text(encoding='utf-8', errors='replace').splitlines() if runs else []
        except OSError:
            lines = []
        return kit_prepare.checkpoint_from_log(lines, self.base.dest)

    def export_receipts(self):
        folder = self.base.dest / 'game' / 'analysis' / 'prepared-states'
        return list(folder.glob('*/playable-export.json')) if folder.is_dir() else []

    def early_checkpoint(self):
        """Find THIS preparation's archive-verified export, before its native intro.

        The normal watcher's checkpoint log is intentionally late (after the
        intro acknowledgement). The trainer publishes this receipt only after
        the original archive's complete payloads/CRCs have been checked. An old receipt,
        foreign disc, escaped output path or changed file is never accepted;
        convert() still independently checks all native guards and the spec.
        """
        from native_map import SERIAL, CRC
        serial = 'SLUS-21978' if kit_paths.ADAPTER.startswith('bt4') else SERIAL
        root = (self.base.dest / 'game' / 'analysis' / 'prepared-states').resolve()
        for receipt in sorted(self.export_receipts(), reverse=True):
            if str(receipt.resolve()) in self.exports_before:
                continue
            try:
                record = json.loads(receipt.read_text(encoding='utf-8'))
                output = Path(record['output']).resolve()
                directory = receipt.parent.resolve()
                held = record.get('kind') == kit_prepare.HELD_EXPORT_KIND
                if (directory.parent != root or output.parent != directory or output.suffix != '.p2s'
                        or record.get('serial') != serial or str(record.get('crc')).upper() != CRC.upper()
                        or (held and (not held_receipt_owned(record, self.export_owner, self.base.pid) or
                            not output.name.endswith('-ready-held.p2s') or record.get('source') != str(output)))
                        or (not held and record.get('status') !=
                            'Offline copy patched and archive-verified; not loaded into the emulator')):
                    continue
                wanted = record.get('output_sha256')
                if not isinstance(wanted, str) or len(wanted) != 64:
                    continue
                before = output.stat()
                digest = hashlib.sha256()
                with output.open('rb') as stream:
                    for block in iter(lambda: stream.read(1 << 20), b''):
                        digest.update(block)
                after = output.stat()
                if (before.st_size <= 0 or (before.st_size, before.st_mtime_ns) !=
                        (after.st_size, after.st_mtime_ns) or digest.hexdigest() != wanted):
                    continue
                self.held_export = record if held else None
                self.event('early export verified', checkpoint=str(output), sha256=wanted)
                return output
            except (OSError, ValueError, KeyError, TypeError):
                # The JSON may still be being written. A partial receipt cannot
                # publish a partial archive; retry on the next poll.
                continue
        return None

    def wait_for_checkpoint(self, timeout=240):
        """The mod's playable checkpoint of THIS match (a new 'Rematch checkpoint' line, its file written)."""
        self.progress('prep.loading', 0, ETA['loading'])
        end, t0 = time.time() + timeout, time.time()
        while time.time() < end:
            self.check()
            failed = self.watcher_failed()
            if failed:
                raise KitError('TTM-NET-23', what=f'The mod in the host\'s match-making copy failed: {failed}',
                               fix='Press Start again: the kit starts the copy again.',
                               what_es=f'El mod de la copia del anfitrión falló: {failed}',
                               fix_es='Pulsa Empezar otra vez: el kit vuelve a arrancar la copia.')
            path = self.early_checkpoint()
            if path is not None:
                return path
            path = self.newest_checkpoint()
            if path is not None and path != self.checkpoint_before and path.is_file():
                size = path.stat().st_size
                time.sleep(1.0)
                if path.stat().st_size == size and size > 0:
                    return path
            pct = min(95, int((time.time() - t0) * 100 / ETA['loading']))
            self.progress('prep.loading', pct, max(1, ETA['loading'] - (time.time() - t0)))
            time.sleep(0.01)
        raise KitError('TTM-NET-23', what=f'The host\'s match was not ready within {int(timeout)} s.',
                       fix='Press Start again: the kit starts the copy again.',
                       what_es=f'El combate del anfitrión no estuvo listo en {int(timeout)} s.',
                       fix_es='Pulsa Empezar otra vez: el kit vuelve a arrancar la copia.')

    def return_to_select(self):
        """From the live (prepared) fight: Start, Return to Character Select, Yes; the watcher reloads its clean
        character-select checkpoint and keeps Team Battle."""
        self.loading_speed(False)
        self.keys(['start'], gap=1.5)
        self.keys(['down', 'down', 'cross'], gap=0.6)
        self.keys(['up', 'cross'], gap=0.6)
        end = time.time() + 60
        while time.time() < end:
            self.check()
            log = self.watcher().get('log') or []
            s = self.sample()
            if s['scene'] == TEAM_SELECT and s['loop'] == 0 and \
                    any('Back at character selection' in line for line in log[-4:]):
                self.event('back at character select', **s)
                return
            self.sleep(0.5)
        raise KitError('TTM-NET-23', what='The host\'s match-making copy did not return to the team screen.',
                       fix='Press Ready again: the kit starts it again.',
                       what_es='La copia del anfitrión no volvió a la pantalla de equipos.', fix_es='Pulsa Listo otra vez: el kit la vuelve a arrancar.')

    def prepare(self, spec, folder, mod=None, language='en', options=None, *, controls=None, deferred_reset=False):
        """Make `spec` into `folder` (capture.p2s, netplay.p2s), returning the verified report and timings.
        Committed Starts may park the private copy until delivery/intro finish;
        other owners return it to map selection in the background immediately."""
        with self.lock:
            return self._prepare(spec, Path(folder), mod, language, options, controls=controls,
                                 deferred_reset=deferred_reset)

    def _prepare(self, spec, folder, mod, language, options, *, controls=None, deferred_reset=False):
        import kit_match
        controls = kit_match.transport_controls(controls)
        t0 = time.time()
        timings = {}
        self._finish_pending_reset()
        if self.state == 'suspended':
            self._resume_checked()
        engine = kit_spec.engine_mode(spec)
        if engine != self.engine:
            self.switch_engine(engine)
            timings['engine'] = round(time.time() - t0, 1)
        if self.state != 'warm' or not self.base.pid or not kit_win.pid_alive(self.base.pid):
            self.state = 'cold'
            self._warm()
            timings['warm'] = round(time.time() - t0, 1)
        elif not self.at_map_select():
            if self.at_select():
                self.native_picks()
            else:
                self.close()
                self._warm()
            timings['warm'] = round(time.time() - t0, 1)
        self.state = 'busy'
        confirmed = False
        try:
            self.progress('prep.settings', 0, ETA['settings'])
            t = time.time()
            self.write_settings(spec.get('gameplay') or {}, spec.get('services') or {}, language)
            self.write_native(spec)
            timings['settings'] = round(time.time() - t, 1)
            self.check()
            t = time.time()
            written = spec
            if self.test and (options or {}).get('bad_costume'):
                # TEST HOOK ONLY: a colour the last fighter of team 2 does not have, written past the lobby's
                # validation, so the mod's own preparation fails (TTM-MATCH-06) and the failure path runs
                written = json.loads(json.dumps(spec))
                written['teams'][1][-1]['costume'] = 3
                self.event('test: invalid colour written', fighter=written['teams'][1][-1])
            self.checkpoint_before = self.newest_checkpoint()
            self.exports_before = {str(p.resolve()) for p in self.export_receipts()}
            self.export_owner = dict(schema=1, token=os.urandom(16).hex(), emulator_pid=self.base.pid)
            self.held_export = None
            kit_prepare.independent_write(self.base.dest / 'game' / kit_prepare.HELD_EXPORT_OWNER,
                                          json.dumps(self.export_owner).encode('utf-8'))
            self.loading_speed(True)
            self.confirm(written)
            confirmed = True
            timings['confirm'] = round(time.time() - t, 1)
            t = time.time()
            tag = kit_spec.spec_sha(spec)[:8]
            if self.capture_shots:                       # opt-in screenshots, never implicit with KO/fault hooks
                for i, wait_s in enumerate((5.0, 13.0, 13.0)):
                    self.sleep(wait_s)
                    self.test_shot(f'{tag}-loading{i + 1}')
            checkpoint = self.wait_for_checkpoint()
            self.check()                                 # a cancel that came while the match loaded
            timings['loading'] = round(time.time() - t, 1)
            self.progress('prep.capture', 0, ETA['capture'])
            t = time.time()
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checkpoint, folder / 'capture.p2s')
            timings['capture'] = round(time.time() - t, 1)
            self.event('captured', checkpoint=str(checkpoint))
            self.loading_speed(False)
        except Cancelled:
            self.loading_speed(False)
            self.event('cancelled', confirmed=confirmed)
            if confirmed and self.base.pid:
                self._recover_after_confirm()
            else:
                self.state = 'warm'
            raise
        except BaseException as error:
            self.loading_speed(False)
            self.event('prepare failed', error=str(error)[:500])
            if confirmed and self.base.pid:
                try:
                    self._recover_after_confirm()
                except BaseException:  # noqa: BLE001 - recovery failed: cold start next time
                    self.close()
                    self.state = 'failed'
            elif self.state == 'busy':
                self.state = 'warm' if self.at_map_select() else 'failed'
            raise
        # Conversion and its complete spec verification are the final critical
        # step. The copy's intro and return to selection run AFTER delivery.
        self.progress('prep.convert', 0, ETA['convert'])
        t = time.time()
        try:
            report = kit_prepare.convert(folder / 'capture.p2s', folder,
                                         self.base.dest / 'game' / 'assets' / 'characters.json',
                                         python=self.base.python(), say=self.say, spec=spec, options=options,
                                         controls=controls, held_export=self.held_export)
        except BaseException:
            self.schedule_reset()
            raise
        timings['convert'] = round(time.time() - t, 1)
        self.schedule_reset(deferred=True) if deferred_reset else self.schedule_reset()
        report['timings'] = timings
        report['seconds'] = round(time.time() - t0, 1)
        report['copy_after'] = self.state
        self.event('prepared', seconds=report['seconds'], timings=timings, verify_sha=report.get('verify_sha'))
        return report

    def schedule_reset(self, *, deferred=False):
        """Return the private copy in the background, serialized with every owner."""
        token = object()
        self.reset_token = token
        self.reset_thread = None
        self.state = 'resetting'
        self.reset_deferred = False
        self.reset_owner = None
        if deferred:
            try:
                if self._park_pending_reset(token):
                    self.reset_deferred = True
                    self.event('reset deferred', pids=self.suspended)
                    return
            except (OSError, RuntimeError, ValueError) as error:
                # The delivered archive is already verified. An unrelated or
                # replaced worker must not receive suspend/menu commands.
                self.event('reset owner changed', error=str(error)[:300])
                self.reset_token = None
                self.state = 'cold'
                return

        def reset():
            with self.lock:
                if self.reset_token is token:
                    self._finish_pending_reset()

        self.reset_thread = threading.Thread(target=reset, name='ttm-prep-reset', daemon=True)
        self.reset_thread.start()

    def _private_process_token(self, pid):
        from kit_fight import FightMixin
        return FightMixin._load_process_token(self.base, pid)

    def _reset_owner_current(self, owner):
        return self.base is owner['base'] and self.base.pid == owner['pid'] and \
            self.base.cmd_pid == owner['cmd_pid'] and kit_win.listener_pid(self.slot) == owner['pid'] and \
            all(self._private_process_token(pid) == token for pid, token in owner['tokens'].items())

    def _park_pending_reset(self, token):
        """Defer the unchanged private tree; park only after its worker is ACTIVE."""
        if os.name != 'nt' or not self.base.pid or self.reset_token is not token:
            return False
        pids = kit_win.process_tree(self.base.cmd_pid, self.base.pid)
        tokens = {pid: self._private_process_token(pid) for pid in pids}
        owner = dict(base=self.base, pid=self.base.pid, cmd_pid=self.base.cmd_pid, tokens=tokens)
        expected = os.path.normcase(str(self.base.dest / 'game' / 'runtime28' / 'pcsx2-qt.exe'))
        if self.base.pid not in tokens or any(value is None for value in tokens.values()) or \
                os.path.normcase(kit_win.process_path(self.base.pid)) != expected or \
                not self._reset_owner_current(owner):
            raise ValueError('The private reset process tree is no longer owned.')
        watcher_state = self.watcher().get('state')
        if not self._reset_owner_current(owner):
            raise ValueError('The private reset owner changed before parking.')
        self.reset_owner = owner
        if watcher_state != 'ACTIVE':
            # PREPARING may still charge a native running-time watchdog.
            # Leave it running at nominal speed; defer selector reset only.
            self.event('reset waiting for worker', watcher=watcher_state, pid=owner['pid'])
            return True
        done = kit_win.suspend_pids(pids)
        self.suspended, self.suspended_tokens = done, {pid: tokens[pid] for pid in done}
        if not self._reset_owner_current(owner):
            self.resume()
            raise ValueError('The private reset owner changed while suspending.')
        if set(done) != set(pids):
            self.resume()
            return False
        self.reset_owner = owner
        return True

    def finish_deferred_reset(self):
        """Consume a parked reset once delivery is over, or before the next owner."""
        with self.lock:
            if getattr(self, 'reset_deferred', False) and self.reset_token is not None:
                self._finish_pending_reset()
                if self.state == 'warm':
                    self.suspend()
            return self.state

    def _finish_pending_reset(self):
        """Called with lock held. Also covers a new request winning the worker race.

        Joining the worker while holding the same RLock would deadlock. Instead
        the first owner performs the pending reset; the worker then sees its
        token consumed and does nothing. Closing invalidates it before waiting.
        """
        token = self.reset_token
        if token is None or self.reset_running:
            return
        owner = getattr(self, 'reset_owner', None)
        if owner is not None and not self._reset_owner_current(owner):
            self.resume()
            self.reset_token = None
            self.reset_deferred = False
            self.reset_owner = None
            self.state = 'cold'
            self.event('reset discarded', reason='private owner changed')
            return
        previous = self.warming
        self.warming = self.reset_running = True
        started = time.time()
        try:
            if not self.resume():
                raise ValueError('The private reset process tree did not fully resume.')
            self.loading_speed(True)
            if self.cached_selector(self.engine):
                # The playable export precedes cleanup. Wait for the worker to
                # release its borrowed state slots before loading any template.
                end = time.monotonic() + 90
                while time.monotonic() < end:
                    self.check()
                    status = self.watcher()
                    if status.get('state') == 'ACTIVE':
                        break
                    if status.get('state') == 'FAILED':
                        raise ValueError('Preparation worker failed before selector reset')
                    self.sleep(.05)
                else:
                    raise TimeoutError('Preparation worker did not release its state slots')
                self.restore_selector(self.engine)
            else:
                self.loading_speed(True)
                sample = self.wait_for_fight()
                self.event('copy in its fight', clock=sample.get('clock'), fighters=sample.get('fighters'))
                if self.capture_shots:
                    self.test_shot('prepared-fight')
                self.return_to_select()
                self.native_picks()
            self.check()
            self.state = 'warm'
            self.event('reset complete', seconds=round(time.time() - started, 1))
        except Cancelled:
            self.state = 'cold'
        except BaseException as error:  # noqa: BLE001 - already delivered match remains playable
            self.event('back failed', error=str(error)[:300])
            self.close()
            self.state = 'cold'
        finally:
            self.loading_speed(False)
            if self.reset_token is token:
                self.reset_token = None
            self.reset_running = False
            self.reset_deferred = False
            self.reset_owner = None
            self.warming = previous

    def _recover_after_confirm(self):
        """A preparation stopped after the confirm: let the match load, then back to the team screen."""
        self.cancel.clear()
        self.warming = True                              # a second cancel does not stop the way back either
        try:
            self.wait_for_fight(180)
            self.return_to_select()
            self.native_picks()
            self.state = 'warm'
        except BaseException:  # noqa: BLE001
            self.close()
            self.state = 'cold'
        finally:
            self.loading_speed(False)
            self.warming = False

    # ---- 6.9 suspend while the online match runs ------------------------------------------------------------------------------
    def suspend(self):
        with self.lock:
            if self.state != 'warm' or not self.base.pid:
                return []
            pids = kit_win.process_tree(self.base.cmd_pid, self.base.pid)
            self.suspended = kit_win.suspend_pids(pids)
            if self.suspended:
                self.state = 'suspended'
            self.event('suspended', pids=self.suspended)
            return self.suspended

    def resume(self):
        if self.suspended:
            tokens = getattr(self, 'suspended_tokens', {})
            owned = [pid for pid in self.suspended if pid not in tokens or
                     self._private_process_token(pid) == tokens[pid]]
            done = kit_win.resume_pids(owned)
            self.event('resumed', pids=done)
            self.suspended = [pid for pid in owned if tokens and pid not in done]
            self.suspended_tokens = {pid: tokens[pid] for pid in self.suspended}
            if self.state == 'suspended' and not self.suspended:
                self.state = 'warm'
        return not self.suspended

    def _resume_checked(self):
        """Resume, then the health check: PINE answers and the team screen shows within 10 s, else a cold start."""
        self.resume()
        end = time.time() + 10
        while time.time() < end:
            s = self.sample()
            if s['scene'] == TEAM_SELECT and s['loop'] == 0:
                self.state = 'warm'
                self.event('resume healthy', **s)
                return True
            time.sleep(0.3)
        self.event('resume unhealthy', **self.sample())
        self.close()
        self.state = 'cold'
        return False

    def status(self):
        return dict(state=self.state, error=self.error, pid=self.base.pid, slot=self.slot)


# ---- standalone use (development and tests): python kit_prepare_auto.py --install DIR --slot N --spec FILE ----------------
def main():
    import argparse
    import kit_install
    ap = argparse.ArgumentParser()
    ap.add_argument('--install', required=True)
    ap.add_argument('--slot', type=int, required=True)
    ap.add_argument('--spec', action='append', default=[])
    ap.add_argument('--out', required=True)
    ap.add_argument('--iso')
    ap.add_argument('--test-ko', action='store_true')
    ap.add_argument('--suspend-test', type=float, default=0.0)
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--build-selector-cache', action='store_true',
                    help='Build both local neutral engine templates once; no matches or user saves are created')
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    install = kit_install.read_installation(args.install)
    import kit_match
    kit_match.ensure_elf(args.iso or install['iso'])
    copy = PrepCopy(install, args.iso or install['iso'], args.slot, out, say=print)
    copy.progress = lambda step, pct=None, eta_s=None: print(f'  [{step}] {pct}% eta {eta_s}', flush=True)
    results = []
    try:
        t = time.time()
        copy.warm()
        results.append(dict(step='warm', seconds=round(time.time() - t, 1)))
        if args.build_selector_cache:
            for engine in ('teams', 'ffa'):
                t = time.time()
                copy.switch_engine(engine)
                copy.cache_selector()
                results.append(dict(step='selector-cache', engine=engine, seconds=round(time.time()-t, 3)))
        for i, path in enumerate(args.spec):
            spec = json.loads(Path(path).read_text(encoding='utf-8'))
            if args.suspend_test and i:
                copy.suspend()
                time.sleep(args.suspend_test)
            t = time.time()
            report = copy.prepare(spec, out / Path(path).stem, mod=spec.get('mod'), language='en',
                                  options={'test_ko': True} if args.test_ko else None)
            results.append(dict(step=Path(path).stem, seconds=round(time.time() - t, 1), title=report['title'],
                                verify_sha=report['verify_sha'], timings=report['timings'],
                                copy_after=report['copy_after']))
            print(json.dumps(results[-1]), flush=True)
    finally:
        try:
            (out / 'results.json').write_text(json.dumps(results, indent=1), encoding='utf-8')
        finally:
            if not args.keep:
                copy.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
