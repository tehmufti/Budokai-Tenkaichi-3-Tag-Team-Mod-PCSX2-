"""Automatic host preparation (spec 6): the host's game builds the lobby's match by itself, with nobody at its menus.

The host's PrepCopy is a PRIVATE COPY of its Tag Team Mod installation (kit_prepare.Prepare: the installation is only
read), running on a hidden desktop with the kit's blank memory card, keyboard pad 1 and no sound. It is warmed up as
soon as the lobby opens and kept at the game's map select between matches:
  boot()            logos -> title (u32(0x300EC8) == 0x40703802) -> New Game -> the blank card's two questions
                    (Cross = No, Left + Cross = Yes) -> main menu (scene 4) with the Modded Modes pager published
  commit_mode()     Select (only when the pager shows the original page) -> Team Battle (or Free-for-all: the
                    second row) -> 1 Player; the watcher's log line 'Modded Modes: Team Battle, 1 Player' (or
                    'Free-for-all, 1 Player') and scene 0x28 (Team Select). A match of the other engine mode closes the
                    copy and warms it again in that mode (kit 2.0: 1 v 1 and free-for-all run on the FFA engine)
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
  capture           the mod's own playable checkpoint (kit 2.0: the match held just before its intro, playable
                    without the watcher; the watcher's log names it 'Rematch checkpoint: ...'), copied as capture.p2s
  convert           kit_prepare.convert with the spec (single view, players, the online writes, layout 3, verify)
  back to select    Start, Down, Down, Cross, Up, Cross (the watcher reloads its clean character-select checkpoint),
                    then the native picks again: the copy waits at map select for the next match
While the online match runs the copy's process tree is suspended (NtSuspendProcess) and resumed before the next
preparation; a copy that does not answer then (PINE, scene) is closed and started again (cold).
Windows only: the copy is driven by key messages to its hidden window.
"""
import json
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
import kit_win
from kit_codes import KitError

SCENE, LOOP, MANAGER = A(0x331DC8), A(0x3337C0), A(0x2FF10C)
PAGER, PAGER_MAGIC = 0x076FF000, 0x324D4E42
TITLE_WORD = GP + GPO(-13224)
TITLE_VALUE = 0x40703802
TEAM_OBJECT, SIDES = A(0x3B38D8), (0x3D8, 0x660)
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
# Seconds each step usually takes (the lobby's ETA; p33 live runs).
ETA = dict(copy=30, start=25, boot=30, mode=10, picks=22, settings=3, confirm=3, loading=50, capture=8, convert=10,
           back=15)
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


class PrepCopy:
    """The host's warm match-making copy. Every public step runs in a worker thread of the session process; one at a
    time (self.lock)."""

    def __init__(self, install, iso, slot, run_dir, say=print, test=False):
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
        self.started = None
        self.engine = 'teams'            # the engine mode the copy is committed to (kit 2.0)
        self.checkpoint_before = None

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
        time.sleep(hold)
        kit_win.post_key(self.base.pid, key, False, self.base.desktop)

    def keys(self, buttons, gap=0.5):
        for b in buttons:
            self.check()
            self.press(b)
            self.sleep(gap)

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

    def write_settings(self, gameplay, services, language):
        """The copy's mod-settings.json for this match (only when it changes): EVERY key set (the copy's own mod's
        defaults, then kit_settings.match_settings), so nothing of the host's offline settings reaches the match."""
        import kit_settings
        values = kit_settings.match_settings(gameplay, services, language)
        if values == self.settings_written:
            return
        code, out, err = self.base.copy_python('-c', 'import copy, json, sys; sys.path.insert(0, "tools"); import '
                                               'mod_settings; d = copy.deepcopy(mod_settings.DEFAULTS); '
                                               'd.update(json.loads(sys.argv[1])); mod_settings.save_settings(d)',
                                               json.dumps(values))
        if code != 0:
            raise KitError('TTM-NET-23', what=f'The match-making copy\'s mod settings could not be written: '
                                              f'{err.strip()[-300:]}', fix='Press Ready again.',
                           what_es=f'No se pudieron escribir los ajustes del mod de la copia: {err.strip()[-300:]}',
                           fix_es='Pulsa Listo otra vez.')
        code, out, err = self.base.copy_python(self.base.dest / 'game' / 'tools' / 'mod_settings.py', '--show')
        try:
            shown = json.loads(out)
        except ValueError:
            shown = {}
        wrong = {k: shown.get(k) for k, v in values.items() if k in shown and shown.get(k) != v and
                 not (isinstance(v, float) and isinstance(shown.get(k), (int, float)) and abs(v - shown[k]) < 1e-9)}
        if code != 0 or wrong:
            raise KitError('TTM-NET-23', what=f'The match-making copy\'s mod settings did not take effect: '
                                              f'{wrong or err[-200:]}', fix='Press Ready again.',
                           what_es=f'Los ajustes del mod de la copia no se aplicaron: {wrong or err[-200:]}',
                           fix_es='Pulsa Listo otra vez.')
        self.settings_written = values
        self.event('settings', values={k: values[k] for k in sorted(values)})

    def launch(self):
        self.progress('prep.start', 0, ETA['start'])
        self.started = time.time()
        self.base.launch()
        self.event('launched', pcsx2=self.base.pid, cmd=self.base.cmd_pid, desktop=self.base.desktop)
        self.wait(lambda s: s['scene'] is not None, 120, 'its first screen')

    def close(self):
        """Close the copy's Play session (by PID: its cmd.exe tree and its PCSX2)."""
        self.resume()
        self.base.close()
        self.base.pid = self.base.cmd_pid = None
        if self.state != 'failed':
            self.state = 'cold'

    # ---- 6.2 boot, 6.4 mode, 6.5 picks -------------------------------------------------------------------------------
    def boot(self, timeout=240):
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
        self.progress('prep.mode', 0, ETA['mode'])
        self.sleep(2.0)                                  # the pager finishes publishing its page
        s = self.sample()
        if s['pager_state'] == 4:                        # the original page is up: Select shows Modded Modes
            self.keys(['select'], gap=2.0)
            self.wait(lambda x: x['pager_state'] in (1, 2), 10, 'the Modded Modes page')
        self.keys(['down'] * MODE_ROWS[self.engine], gap=0.6)
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
        self.progress('prep.picks', 0, ETA['picks'])
        self.sleep(3.0)                                  # the select screen's intro animation
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
                self.launch()
                self.boot()
                self.commit_mode()
            elif not self.at_select():
                self.close()
                return self._warm_steps()
            if not self.at_map_select():
                self.native_picks()
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
                else:
                    c.write(rec + 0x14, struct.pack('<3i', 0, 0, -1))
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
            self.write_spec(c, spec)
            self.event('spec written', teams=kit_spec.teams_of(spec), stage=spec['stage'])
            self.check()
            key = __import__('kit_emu').PAD1_KEYS['circle' if __import__('native_map').JPN else 'cross']
            kit_win.post_key(self.base.pid, key, True, self.base.desktop)
            time.sleep(0.2)
            kit_win.post_key(self.base.pid, key, False, self.base.desktop)
            t0 = time.time()
            while time.time() - t0 < 15 and u32(c, LOOP) != 1:
                time.sleep(0.005)
            if u32(c, LOOP) != 1:
                raise KitError('TTM-NET-23', what='The host\'s game did not start the match after the confirm.',
                               fix='Press Ready again.',
                               what_es='El juego del anfitrión no empezó el combate tras confirmarlo.', fix_es='Pulsa Listo otra vez.')
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
        finally:
            c.close()
        want = [[[f['character'], f['costume'], 0] for f in team] for team in spec['teams']]
        self.event('confirmed', after=after, counts=counts, members=members, stage=stage, time=got_time, bgm=got_bgm)
        if members != want or stage != (spec['stage'], spec['stage']) or got_time != time_word or \
                got_bgm != spec['bgm']:
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
            path = self.newest_checkpoint()
            if path is not None and path != self.checkpoint_before and path.is_file():
                size = path.stat().st_size
                time.sleep(1.0)
                if path.stat().st_size == size and size > 0:
                    return path
            pct = min(95, int((time.time() - t0) * 100 / ETA['loading']))
            self.progress('prep.loading', pct, max(1, ETA['loading'] - (time.time() - t0)))
            time.sleep(0.3)
        raise KitError('TTM-NET-23', what=f'The host\'s match was not ready within {int(timeout)} s.',
                       fix='Press Start again: the kit starts the copy again.',
                       what_es=f'El combate del anfitrión no estuvo listo en {int(timeout)} s.',
                       fix_es='Pulsa Empezar otra vez: el kit vuelve a arrancar la copia.')

    def return_to_select(self):
        """From the live (prepared) fight: Start, Return to Character Select, Yes; the watcher reloads its clean
        character-select checkpoint and keeps Team Battle."""
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

    def prepare(self, spec, folder, mod=None, language='en', options=None):
        """Make the online match of `spec` into `folder` (capture.p2s, base.p2s, netplay.p2s); returns the conversion
        report plus timings. The copy is left warm (at map select) when everything went well."""
        with self.lock:
            return self._prepare(spec, Path(folder), mod, language, options)

    def _prepare(self, spec, folder, mod, language, options):
        t0 = time.time()
        timings = {}
        if self.state == 'suspended':
            self._resume_checked()
        engine = kit_spec.engine_mode(spec)
        if engine != self.engine:                        # the copy is committed to the other engine mode
            self.event('engine change', old=self.engine, new=engine)
            self.close()
            self.engine = engine
            self.state = 'cold'
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
            self.confirm(written)
            confirmed = True
            timings['confirm'] = round(time.time() - t, 1)
            t = time.time()
            tag = kit_spec.spec_sha(spec)[:8]
            if self.test:                                # the game's loading screen, then the mod's cover
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
            sample = self.wait_for_fight()              # the copy plays on into its fight: back to select from there
            self.event('copy in its fight', clock=sample.get('clock'), fighters=sample.get('fighters'))
            if self.test:
                self.test_shot(f'{tag}-fight')
        except Cancelled:
            self.event('cancelled', confirmed=confirmed)
            if confirmed:
                self._recover_after_confirm()
            else:
                self.state = 'warm'
            raise
        except BaseException as error:
            self.event('prepare failed', error=str(error)[:500])
            if confirmed:
                try:
                    self._recover_after_confirm()
                except BaseException:  # noqa: BLE001 - recovery failed: cold start next time
                    self.close()
                    self.state = 'failed'
            elif self.state == 'busy':
                self.state = 'warm' if self.at_map_select() else 'failed'
            raise
        # convert (the installation's Python) while the copy goes back to the team screen and the map select
        self.progress('prep.convert', 0, ETA['convert'])
        box = {}

        def convert():
            try:
                box['report'] = kit_prepare.convert(folder / 'capture.p2s', folder,
                                                    self.base.dest / 'game' / 'assets' / 'characters.json',
                                                    python=self.base.python(), say=self.say, spec=spec,
                                                    options=options)
            except BaseException as error:  # noqa: BLE001 - handed back below
                box['error'] = error
        t = time.time()
        worker = threading.Thread(target=convert, daemon=True)
        worker.start()
        back_error = None
        self.warming = True                              # the match is captured: the copy's way back is not cancelled
        try:
            self.cancel.clear()
            self.return_to_select()
            self.native_picks()
            self.state = 'warm'
        except BaseException as error:  # noqa: BLE001 - the match is made; the copy restarts next time
            back_error = error
            self.event('back failed', error=str(error)[:300])
            self.close()
            self.state = 'cold'
        finally:
            self.warming = False
        worker.join()
        timings['convert_and_back'] = round(time.time() - t, 1)
        if 'error' in box:
            raise box['error']
        report = box['report']
        report['timings'] = timings
        report['seconds'] = round(time.time() - t0, 1)
        report['copy_after'] = self.state if back_error is None else f'cold ({back_error})'
        self.event('prepared', seconds=report['seconds'], timings=timings, verify_sha=report.get('verify_sha'))
        return report

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
            done = kit_win.resume_pids(self.suspended)
            self.event('resumed', pids=done)
            self.suspended = []
            if self.state == 'suspended':
                self.state = 'warm'

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
        (out / 'results.json').write_text(json.dumps(results, indent=1), encoding='utf-8')
        if not args.keep:
            copy.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
