"""The kit's PCSX2 on this PC: settings, BIOS, patch file, memory cards, start, 'loaded and paused', resume, stop.

Every start rewrites pcsx2/inis/PCSX2.ini from match/PCSX2.ini.template (the Tag Team Mod installer's PCSX2.ini) with
the same emulation settings on every PC; only these keys are per PC: the PINE slot, the controller binding of Pad1
(controller 1 = SDL-0 by default, or the keyboard), the BIOS file name, the SDL hints and (test mode) Null audio.
The cross-machine policy's FORCED keys (kit_ident.FORCED: FPU/VU round modes and clamps at PCSX2's default, EE cycle
rate/skip 0, fast CDVD on, cheats + patches on, widescreen / no-interlacing patches off, game fixes on, HostFs off,
multitap port 1 with four DualShock 2 pads) are written last and checked after writing. Extra pnach files for BT3 or
a BT3 per-game settings file in the PCSX2 data folders are refused (TTM-NET-27).
The first match is loaded with -statefile (both PCs load it the same way); a rematch and every later match are
PINE-loaded into the running PCSX2 (slot 241, a per-machine copy with CONTROL.local_slot written) and attached late:
the p33 rig measured identical hash streams for both load paths of an in-fight match state.
PCSX2's pause toggle is the Pause key (Keyboard/Pause, kit 1.3.0; it was Space, which a player pressed by accident
on one PC): the kit presses it itself to start a fight, to pause the game when the players go back to the lobby and
to resume a loaded match (ensure_running / ensure_paused, checked over PINE).
Kit 2.0, the emulator-settings policy (README "What you may change"):
  * the game window has no menus (-nogui) and NO hotkeys but the kit's own (every [Hotkeys] line of the template
    goes; only the kit's pause key and the screenshot key are bound), so no savestate load / save, speed toggle,
    frame advance, reset or settings dialog can be reached while playing;
  * the speed scalars are 1.0 (nominal, turbo and slow motion: even a turbo bound later runs at full speed only), the
    PCSX2 achievements (hardcore mode) are off, save-on-shutdown is off;
  * the ini is written at every start and its forced keys checked (kit_ident.FORCED); during a match the kit watches
    the ini and the PCSX2 data folders (EmulatorWatch): a changed forced key or a new per-game file only takes effect
    when PCSX2 starts again, and the next start writes the kit's values back; the game window being paused, closed or
    loading another state is seen over PINE (the kit resumes it, or the player leaves the match);
  * what may differ per PC: renderer, resolution / upscaling, window or full screen, audio, controller bindings.
  * the runtime pnach is the one the match names (match/runtime/pnach/<sha256>.pnach: one per accepted Tag Team Mod
    build family), copied into the PCSX2 data folder before PCSX2 starts.
"""
import os
import re
import shutil
import time
from pathlib import Path

import kit_paths
import kit_win
from kit_codes import KitError
from kit_ident import PNACH, MEMCARDS, FORCED, forced_problems, ini_values, pnach_files

EXE = 'pcsx2-qt.exe'
PAD_BUTTONS = ('Up', 'Right', 'Down', 'Left', 'Triangle', 'Circle', 'Cross', 'Square', 'Select', 'Start', 'L1', 'L2',
               'R1', 'R2', 'L3', 'R3', 'LUp', 'LRight', 'LDown', 'LLeft', 'RUp', 'RRight', 'RDown', 'RLeft')
SDL_NAMES = dict(Up='DPadUp', Right='DPadRight', Down='DPadDown', Left='DPadLeft', Triangle='FaceNorth',
                 Circle='FaceEast', Cross='FaceSouth', Square='FaceWest', Select='Back', Start='Start',
                 L1='LeftShoulder', L2='+LeftTrigger', R1='RightShoulder', R2='+RightTrigger', L3='LeftStick',
                 R3='RightStick', LUp='-LeftY', LRight='+LeftX', LDown='+LeftY', LLeft='-LeftX', RUp='-RightY',
                 RRight='+RightX', RDown='+RightY', RLeft='-RightX')
# Keyboard play (--keyboard) and the test bots: the p22 rig's Pad1 letters. (vk, scan, extended, PCSX2 key name)
PAD1_KEYS = {'cross': (0x51, 0x10, 0, 'Q'), 'start': (0x45, 0x12, 0, 'E'), 'select': (0x52, 0x13, 0, 'R'),
             'left': (0x54, 0x14, 0, 'T'), 'down': (0x59, 0x15, 0, 'Y'), 'right': (0x55, 0x16, 0, 'U'),
             'up': (0x49, 0x17, 0, 'I'), 'circle': (0x4F, 0x18, 0, 'O'), 'triangle': (0x50, 0x19, 0, 'P'),
             'square': (0x57, 0x11, 0, 'W'), 'l1': (0x41, 0x1E, 0, 'A'), 'r1': (0x53, 0x1F, 0, 'S'),
             'l2': (0x44, 0x20, 0, 'D'), 'r2': (0x46, 0x21, 0, 'F'), 'l3': (0x47, 0x22, 0, 'G'), 'r3': (0x48, 0x23, 0, 'H'),
             'rup': (0x4A, 0x24, 0, 'J'), 'rright': (0x4B, 0x25, 0, 'K'), 'rdown': (0x4C, 0x26, 0, 'L'),
             'rleft': (0x5A, 0x2C, 0, 'Z'), 'lup': (0x58, 0x2D, 0, 'X'), 'lright': (0x43, 0x2E, 0, 'C'),
             'ldown': (0x56, 0x2F, 0, 'V'), 'lleft': (0x42, 0x30, 0, 'B')}
PAD_NAMES = {'cross': 'Cross', 'start': 'Start', 'select': 'Select', 'left': 'Left', 'down': 'Down', 'right': 'Right',
             'up': 'Up', 'circle': 'Circle', 'triangle': 'Triangle', 'square': 'Square', 'l1': 'L1', 'r1': 'R1',
             'l2': 'L2', 'r2': 'R2', 'l3': 'L3', 'r3': 'R3', 'rup': 'RUp', 'rright': 'RRight', 'rdown': 'RDown',
             'rleft': 'RLeft', 'lup': 'LUp', 'lright': 'LRight', 'ldown': 'LDown', 'lleft': 'LLeft'}
HOTKEYS = {'space': (0x20, 0x39, 0, 'Space'), 'f8': (0x77, 0x42, 0, 'F8'), 'pause': (0x13, 0x45, 0, 'Pause'),
           'scrolllock': (0x91, 0x46, 0, 'ScrollLock')}
PAUSE_KEY = 'pause'                          # PCSX2's TogglePause (make_ini); fallback ScrollLock (--pause-key)
from native_map import SERIAL, CRC, SERIAL_FILE
STATE_NAME = __import__('kit_adapter').state_name('{slot}')
if kit_paths.ADAPTER.startswith('bt4'):
    SERIAL, SERIAL_FILE = 'SLUS-21978', 'SLUS_219.78'
SDL_BACKGROUND = ('SDLHints', 'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', '1')


def ini_set(text, keys):
    """Set [section] key = value lines (replacing every copy of the key), keeping every other line (CRLF out).
    value None removes every copy of the key (PCSX2 then uses its default)."""
    lines = re.split(r'\r\n|\r|\n', text)
    for section, key, value in keys:
        out, cur, done = [], None, value is None
        for line in lines:
            s = line.strip()
            if s.startswith('[') and s.endswith(']'):
                if cur == section and not done:
                    out.append(f'{key} = {value}')
                    done = True
                cur = s[1:-1]
            elif cur == section and s.split('=')[0].strip() == key:
                if not done:
                    out.append(f'{key} = {value}')
                    done = True
                continue
            out.append(line)
        if not done:
            out += [f'{key} = {value}'] if cur == section else [f'[{section}]', f'{key} = {value}']
        lines = out
    return '\r\n'.join(lines)


def pad1_bindings(source):
    """'SDL-0' (controller 1), 'SDL-1', ... or 'keyboard'."""
    if source == 'keyboard':
        return {PAD_NAMES[k]: 'Keyboard/' + v[3] for k, v in PAD1_KEYS.items()}
    return {b: f'{source}/{SDL_NAMES[b]}' for b in PAD_BUTTONS}


def make_ini(template, *, pine_slot, pad1, bios_name, null_audio=False, extra=(), start_paused=True,
             pause_key=PAUSE_KEY):
    """The PCSX2.ini of one kit run (see the module text). kit_ident.FORCED is written last, so neither the template
    nor `extra` can change a forced key."""
    out, section = [], None
    for line in template.splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1]
        elif section in ('Pad1', 'Pad2', 'Pad3', 'Pad4') and '=' in s and s.split('=')[0].strip() != 'Type':
            continue                                                  # every binding goes; Pad1 is written below
        elif section == 'Hotkeys' and '=' in s:
            continue                                                  # kit 2.0: no hotkeys but the kit's own
        out.append(line)
    keys = [('UI', 'StartPaused', 'true' if start_paused else 'false'), ('UI', 'PauseOnFocusLoss', 'false'),
            ('UI', 'ConfirmShutdown', 'false'), ('UI', 'ShowToolbar', 'false'),
            ('UI', 'SetupWizardIncomplete', 'false'),
            ('Folders', 'Bios', 'bios'), ('Filenames', 'BIOS', bios_name),
            ('EmuCore', 'EnablePINE', 'true'), ('EmuCore', 'PINESlot', str(pine_slot)),
            ('EmuCore', 'SavestateCompressionType', '2'),
            # no OSD messages or unsafe-setting warnings: they covered the HUD (the Duel Time) at every fight start.
            # PCSX2 2.x reads OsdMessagesPos (0 = none; 'Loaded state from slot ...', 'N cheat patches are active');
            # OsdShowMessages is the older key, kept for older builds.
            ('EmuCore/GS', 'OsdShowMessages', 'false'), ('EmuCore/GS', 'OsdMessagesPos', '0'),
            ('EmuCore', 'WarnAboutUnsafeSettings', 'false'),
            ('InputSources', 'SDL', 'true'),
            ('Hotkeys', 'TogglePause', 'Keyboard/' + HOTKEYS[pause_key][3]), ('Hotkeys', 'Screenshot', 'Keyboard/F8'),
            ('Logging', 'EnableFileLogging', 'true'), ('AutoUpdater', 'CheckAtStartup', 'false'), SDL_BACKGROUND,
            ('Framerate', 'NominalScalar', '1'), ('Framerate', 'TurboScalar', '1'), ('Framerate', 'SlomoScalar', '1'),
            ('Achievements', 'Enabled', 'false'), ('EmuCore', 'SaveStateOnShutdown', 'false')]
    if null_audio:
        keys.append(('SPU2/Output', 'Backend', 'Null'))
    keys += [('Pad1', name, value) for name, value in pad1.items()]
    keys += list(extra)
    keys += list(FORCED)
    return ini_set('\r\n'.join(out), keys)


def is_game_file(name):
    """A patch or settings file name PCSX2 would apply to BT3 USA (serial_CRC... or CRC...)."""
    upper = name.upper()
    return upper.startswith((SERIAL, SERIAL_FILE)) or CRC in upper


def extra_game_files(root):
    """Files in the PCSX2 data folders that would change BT3 USA besides the kit's own pnach: other pnach files
    (cheats, the legacy cheats_ws / cheats_ni and the user patches folder) and per-game settings."""
    root = Path(root)
    found = []
    for name in ('cheats', 'cheats_ws', 'cheats_ni', 'patches'):
        folder = root / name
        if folder.is_dir():
            found += [folder / p.name for p in sorted(folder.glob('*.pnach'))
                      if is_game_file(p.name) and not (name == 'cheats' and p.name == PNACH)]
    folder = root / 'gamesettings'
    if folder.is_dir():
        found += [p for p in sorted(folder.glob('*.ini')) if is_game_file(p.name)]
    return found


class Emulator:
    def __init__(self, *, root=None, pine_slot=28460, desktop=None, run_dir=None, say=print):
        self.root = Path(root or kit_paths.PCSX2)
        self.pine_slot, self.desktop, self.run_dir, self.say = pine_slot, desktop, Path(run_dir or '.'), say
        self.pid = None
        self.ini_text = None
        self.job = None
        self.pnach = None

    # ---- files ------------------------------------------------------------------------------------------------------
    def build_identity(self):
        """kit_ident's description of this PCSX2 build (tested or not)."""
        import kit_ident
        return kit_ident.pcsx2_identity(self.root)

    START_PAUSED = True          # loaded paused; the session unpauses both games together (the Pause key)
    CAN_POST_KEYS = True         # hotkeys and the test bots go to the window as key messages
    READY_STATUS = ('paused',)   # PINE status of a loaded match before the fight starts

    def check_program(self):
        if not (self.root / EXE).is_file():
            raise KitError('TTM-NET-25', what=f'{self.root / EXE} is missing.')
        (self.root / 'portable.ini').touch()

    def setup(self, *, bios, pad1='SDL-0', null_audio=False, extra=()):
        """Write everything this PC's PCSX2 needs into the kit's PCSX2 data folder; returns the ini text."""
        self.check_program()
        for sub in ('bios', 'cheats', 'memcards', 'inis', 'sstates', 'snaps', 'logs'):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        bios = Path(bios)
        target = self.root / 'bios' / bios.name
        if not target.exists() or target.stat().st_size != bios.stat().st_size or \
                target.read_bytes() != bios.read_bytes():
            shutil.copyfile(bios, target)
        self.check_extra_files()
        self.pnach = None
        for card in MEMCARDS:                                          # both PCs start from the same cards
            shutil.copyfile(kit_paths.RUNTIME / 'memcards' / card, self.root / 'memcards' / card)
        template = kit_paths.INI_TEMPLATE.read_bytes().decode('utf-8-sig')
        self.ini_text = make_ini(template, pine_slot=self.pine_slot, pad1=pad1_bindings(pad1), bios_name=bios.name,
                                 null_audio=null_audio, extra=extra, start_paused=self.START_PAUSED,
                                 pause_key=self.pause_key)
        self.write_ini(self.root / 'inis' / 'PCSX2.ini')
        return self.ini_text

    def check_extra_files(self):
        extra = extra_game_files(self.root)
        if extra:
            raise KitError('TTM-NET-27', what='PCSX2 would also apply these files to the game: '
                                              + ', '.join(str(p) for p in extra[:6]) + '.')

    def write_ini(self, path):
        """Write the ini and check that every forced key holds its forced value (kit_ident.FORCED)."""
        problems = forced_problems(self.ini_text)
        if problems:
            raise KitError('TTM-NET-25', what='The kit\'s PCSX2 settings could not be forced: ' + '; '.join(problems))
        Path(path).write_bytes(self.ini_text.encode('utf-8'))
        if forced_problems(Path(path).read_bytes().decode('utf-8')):
            raise KitError('TTM-NET-25', what=f'{path} did not keep the forced settings.')

    # ---- the process -------------------------------------------------------------------------------------------------
    def pine_owner(self):
        """PID of the process serving our PINE slot (None: nobody)."""
        return kit_win.listener_pid(self.pine_slot)

    def install_pnach(self, sha):
        """The runtime pnach the match needs (its installation's build family) into the PCSX2 data folder; returns
        True when it changed (a running PCSX2 must then be started again: PCSX2 reads patches at boot)."""
        source = pnach_files().get(sha)
        if source is None:
            raise KitError('TTM-NET-24', what=f'This kit has no runtime patch {str(sha)[:16]} for the host\'s Tag Team '
                                              'Mod version.')
        target = self.root / 'cheats' / PNACH
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.read_bytes() == source.read_bytes():
            changed = False
        else:
            shutil.copyfile(source, target)
            changed = True
        changed = changed or (self.pnach is not None and self.pnach != sha)
        self.pnach = sha
        return changed

    def launch(self, state, iso, fullscreen=False, slot=None):
        owner = kit_win.listener_pid(self.pine_slot)
        if owner is not None:
            raise KitError('TTM-NET-22', what=f'PINE port {self.pine_slot} is already used by process {owner} '
                                              f'({kit_win.process_path(owner) or "unknown"}). Close that program or '
                                              'use another --pine-slot.', logs=str(self.run_dir))
        copy = self.root / 'sstates' / 'netplay.p2s'
        shutil.copyfile(state, copy)
        args = [self.root / EXE, '-batch', '-nogui', '-fastboot'] + (['-fullscreen'] if fullscreen else []) + \
            ['-statefile', copy, '--', iso]
        console = self.run_dir / 'pcsx2.console.txt'
        self.pid = kit_win.launch(args, self.root, console, self.desktop)
        self.job = kit_win.kill_with_me(self.pid)
        return self.pid

    def alive(self):
        return kit_win.pid_alive(self.pid)

    def launch_idle(self, iso):
        """Initialize the private Windows VM while players edit the lobby.

        It stays paused and has no online match yet. The verified match is
        subsequently loaded through the normal PINE path, after everyone loads.
        """
        owner = kit_win.listener_pid(self.pine_slot)
        if owner is not None:
            raise KitError('TTM-NET-22', what=f'PINE port {self.pine_slot} is already used by process {owner}.',
                           logs=str(self.run_dir))
        args = [self.root / EXE, '-batch', '-nogui', '-fastboot', '--', iso]
        self.pid = kit_win.launch(args, self.root, self.run_dir / 'pcsx2.console.txt', self.desktop)
        self.job = kit_win.kill_with_me(self.pid)
        return self.pid

    def wait_idle(self, timeout=60):
        """Boot completed in the paused VM; no netplay code is expected yet."""
        import pine
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self.alive():
                raise KitError('TTM-NET-22', what='PCSX2 closed during lobby initialization.', logs=str(self.run_dir))
            if self.pine_owner() == self.pid:
                try:
                    with pine.PineClient(port=self.pine_slot, timeout=3) as p:
                        info = p.info()
                    if info.get('status') == 'paused' and info.get('serial') == SERIAL:
                        return info
                except (OSError, RuntimeError):
                    pass
            time.sleep(.05)
        raise KitError('TTM-NET-22', what='PCSX2 did not finish lobby initialization.', logs=str(self.run_dir))

    def wait_ready(self, magic_address, magic, timeout=120):
        """PINE answers from our PCSX2, the match is loaded (paused) and the netplay core is in it."""
        import pine
        end = time.time() + timeout
        info = None
        while time.time() < end:
            if not self.alive():
                raise KitError('TTM-NET-22', what='PCSX2 closed while loading the match (see pcsx2.console.txt).',
                               logs=str(self.run_dir))
            if self.pine_owner() == self.pid:
                try:
                    with pine.PineClient(port=self.pine_slot, timeout=3) as p:
                        info = p.info()
                        value = int.from_bytes(p.read(magic_address, 4), 'little') if info.get('serial') else 0
                    if info.get('status') in self.READY_STATUS and value == magic:
                        return info
                except Exception:  # noqa: BLE001 - PINE comes up before the state is loaded
                    pass
            time.sleep(0.3)
        raise KitError('TTM-NET-22', what=f'PCSX2 did not load the match within {timeout} s (last answer: {info}).',
                       logs=str(self.run_dir))

    def press(self, key, hold=0.08):
        kit_win.post_key(self.pid, key, True, self.desktop)
        time.sleep(hold)
        kit_win.post_key(self.pid, key, False, self.desktop)

    def key_event(self, name, key, down):
        """keypad.KeyPlayer interface (test bots): key = 'p1:cross'."""
        kit_win.post_key(self.pid, PAD1_KEYS[key.split(':')[1]], down, self.desktop)

    def place(self):
        if self.desktop:
            return None
        try:
            return kit_win.place_window(self.pid)
        except Exception:  # noqa: BLE001 - cosmetic
            return None

    def controllers(self):
        """The gamepads PCSX2 opened (its log: 'SDLInputSource: Opened gamepad ...')."""
        try:
            text = (self.root / 'logs' / 'emulog.txt').read_text(encoding='utf-8', errors='replace')
        except OSError:
            return []
        return re.findall(r'SDLInputSource: Opened (.+)', text)

    def screenshot(self, dest, timeout=60):
        """Test mode: F8 (PCSX2's own PNG of the game picture), moved to dest."""
        snaps = self.root / 'snaps'
        before = set(snaps.glob('**/*.png')) if snaps.exists() else set()
        self.press(HOTKEYS['f8'], 0.1)
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(0.3)
            new = (set(snaps.glob('**/*.png')) if snaps.exists() else set()) - before
            if new:
                src = sorted(new, key=lambda x: x.stat().st_mtime)[-1]
                last = -1
                while time.time() < end:
                    time.sleep(0.4)
                    try:
                        size = src.stat().st_size
                        if size == last and size > 0:
                            shutil.copyfile(src, dest)
                            src.unlink()
                            return str(dest)
                        last = size
                    except OSError:
                        pass
        return None

    def stop(self):
        """Close our PCSX2 (by its PID) if it still runs."""
        stopped = kit_win.kill_tree(self.pid) if self.pid else False
        return stopped

    # ---- kit 1.3.0: pause, resume, load, window ------------------------------------------------------------------------
    pause_key = PAUSE_KEY

    def state_file(self, slot):
        return self.root / 'sstates' / STATE_NAME.format(slot=slot)

    def vm_status(self, link):
        try:
            return link.status()
        except (OSError, RuntimeError):
            return None

    def _toggle_to(self, link, want, tries=5):
        if not self.CAN_POST_KEYS:
            return self.vm_status(link) == want
        for _ in range(tries):
            status = self.vm_status(link)
            if status == want or status not in ('running', 'paused'):
                return status == want
            self.press(HOTKEYS[self.pause_key], 0.08)
            end = time.time() + 1.5
            while time.time() < end:
                time.sleep(0.05)
                if self.vm_status(link) == want:
                    return True
        return self.vm_status(link) == want

    def ensure_running(self, link):
        """Unpause our PCSX2 (the kit-pressed Pause key), checked over PINE."""
        return self._toggle_to(link, 'running')

    def ensure_paused(self, link):
        return self._toggle_to(link, 'paused')

    def front(self):
        return None if self.desktop is None and not self.pid else kit_win.bring_to_front(self.pid, self.desktop)

    def minimise(self):
        return kit_win.minimise(self.pid, self.desktop)

    def flash(self, count=3):
        return kit_win.flash(self.pid, self.desktop, count)

    def ini(self):
        return ini_values(self.ini_text or '')


class LinuxEmulator(Emulator):
    """The official PCSX2 2.8.2 x64 AppImage on Linux (the player gives it with --pcsx2; kit_ident.TESTED_PCSX2).

    Its data folder is the kit's own <kit>/linux/PCSX2 (XDG_CONFIG_HOME=<kit>/linux: the player's own PCSX2 settings
    are not touched), PINE is a Unix socket (pine.socket_path's rule; the kit names it in TAGTEAM_PINE_SOCKET), and
    the window can neither be hidden nor sent key presses. So the game starts UNPAUSED: the netplay core plays frames
    0..D-1 neutral and waits at frame D for the other PC (a stall, which the fight tolerates). For that this PC's
    per-machine word CONTROL.local_slot must already be in the state it loads: launch() loads a local copy of the
    agreed state with only that word written (guarded; never hashed; the core's self feed is already on in every
    match), and the session attaches late (kit_session.KitSession.attach). Test screenshots (--hold-at, --after) are
    the picture inside a PINE savestate of slot 250 of the kit's own data folder. Bots need key presses: Windows only.
    """
    START_PAUSED = False
    CAN_POST_KEYS = False
    READY_STATUS = ('paused', 'running')
    SHOT_SLOT = 250

    def __init__(self, *, appimage=None, root=None, **kwargs):
        super().__init__(root=root or kit_paths.LINUX / 'PCSX2', **kwargs)
        import pine
        self.appimage = Path(appimage) if appimage else None
        self.proc = None
        self.link = None
        runtime = os.environ.get('XDG_RUNTIME_DIR') or ''
        if not (runtime and os.path.isdir(runtime) and os.access(runtime, os.W_OK)):
            runtime = '/tmp'
        self.runtime = runtime.rstrip('/') or '/'
        self.socket = pine.socket_path(self.pine_slot, environ={'XDG_RUNTIME_DIR': self.runtime})
        os.environ[pine.SOCKET_ENV] = self.socket                     # every PineClient of this kit process

    def build_identity(self):
        import kit_ident
        if not self.appimage or not self.appimage.is_file():
            raise KitError('TTM-NET-28', build=f'no PCSX2 AppImage ({self.appimage or "none given"}; give it with '
                                               '--pcsx2 "PATH")',
                           tested='PCSX2 2.8.2 (the official x64 Qt AppImage, pcsx2-v2.8.2-linux-appimage-x64-Qt)')
        return kit_ident.appimage_identity(self.appimage)

    def check_program(self):
        if not self.appimage or not os.access(self.appimage, os.X_OK):
            raise KitError('TTM-NET-22', what=f'{self.appimage} is not executable (chmod +x it).', logs=str(self.run_dir))

    def pine_owner(self):
        """The PID behind our PINE socket (SO_PEERCRED); self.pid when it is a process of the group we started."""
        import socket as sockets
        import pine
        s = sockets.socket(sockets.AF_UNIX, sockets.SOCK_STREAM)
        s.settimeout(2.0)
        try:
            s.connect(self.socket)
            pid = pine.peer_pid(s)
        except OSError:
            return None
        finally:
            s.close()
        if pid is None:
            return None
        try:
            group = os.getpgid(pid)
        except OSError:
            return pid
        return self.pid if self.proc is not None and group == self.proc.pid else pid

    def launch(self, state, iso, fullscreen=False, slot=None):
        import subprocess
        owner = self.pine_owner()
        if owner is not None:
            raise KitError('TTM-NET-22', what=f'The PINE socket {self.socket} is already served by process {owner}. '
                                              'Close that PCSX2 or use another --pine-slot.', logs=str(self.run_dir))
        copy = self.root / 'sstates' / 'netplay.p2s'
        if slot is None:
            shutil.copyfile(state, copy)
        else:
            per_machine_copy(state, copy, slot)
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'TAGTEAM_PINE_SOCKET')}
        env.update(XDG_CONFIG_HOME=str(self.root.parent), XDG_RUNTIME_DIR=self.runtime)
        args = [str(self.appimage), '-batch', '-nogui', '-fastboot'] + (['-fullscreen'] if fullscreen else []) + \
            ['-statefile', str(copy), '--', str(iso)]
        with open(self.run_dir / 'pcsx2.console.txt', 'wb') as console:
            self.proc = subprocess.Popen(args, cwd=str(self.root.parent), env=env, stdin=subprocess.DEVNULL,
                                         stdout=console, stderr=subprocess.STDOUT, start_new_session=True)
        self.pid = self.proc.pid
        return self.pid

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def press(self, key, hold=0.08):
        return None

    def key_event(self, name, key, down):
        return None

    def place(self):
        return None

    def front(self):
        return None

    def minimise(self):
        return None

    def flash(self, count=3):
        return None

    def state_file(self, slot):
        return self.root / 'sstates' / STATE_NAME.format(slot=slot)

    def screenshot(self, dest, timeout=60):
        """Test mode: the picture inside a PINE savestate (slot 250 of the kit's own Linux data folder)."""
        import zipfile
        if self.link is None:
            return None
        path = self.root / 'sstates' / STATE_NAME.format(slot=self.SHOT_SLOT)
        before = path.stat().st_mtime_ns if path.exists() else None
        self.link._call('save_state', self.SHOT_SLOT)
        end, last = time.time() + timeout, -1
        while time.time() < end:
            time.sleep(0.5)
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_mtime_ns == before:
                continue
            if st.st_size == last and st.st_size > 0:
                try:
                    with zipfile.ZipFile(path) as z:
                        name = next(n for n in z.namelist() if n.lower().endswith('.png'))
                        Path(dest).write_bytes(z.read(name))
                    path.unlink()
                    return str(dest)
                except (OSError, StopIteration, zipfile.BadZipFile):
                    pass
            last = st.st_size
        return None

    def stop(self):
        import signal
        if not self.alive():
            return False
        for sig, wait in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(self.proc.pid, sig)
            except OSError:
                pass
            try:
                self.proc.wait(wait)
                return True
            except Exception:  # noqa: BLE001 - subprocess.TimeoutExpired: next signal
                continue
        return True


def per_machine_copy(state, target, slot):
    """`state` with only netplay_core CONTROL.local_slot written (NO_SLOT -> slot): what the session's attach writes
    into a paused game, written into the file instead (Linux: the game cannot be held paused)."""
    import kit_state
    import netplay_core as nc
    return kit_state.patch_words(state, target, {nc.CONTROL + nc.F['local_slot']: (nc.NO_SLOT, slot)})


def make(args, *, run_dir, say, desktop=None):
    """The Emulator of this platform: the kit's PCSX2 on Windows, the player's AppImage on Linux."""
    if os.name == 'nt':
        return Emulator(pine_slot=args.pine_slot, desktop=desktop, run_dir=run_dir, say=say)
    return LinuxEmulator(appimage=args.pcsx2, pine_slot=args.pine_slot, run_dir=run_dir, say=say)


class EmulatorWatch:
    """During a match: the kit's PCSX2.ini and the PCSX2 data folders. changes() -> [text] once per new change (a
    forced key changed by hand, a new per-game patch or settings file). Nothing changes the running game: PCSX2 reads
    them at start, and the kit's next start writes its own values back; the player is told."""

    def __init__(self, emulator):
        self.em = emulator
        self.path = emulator.root / 'inis' / 'PCSX2.ini'
        self.seen = self._stamp()
        self.reported = set()

    def _stamp(self):
        try:
            data = self.path.read_bytes()
        except OSError:
            data = b''
        extra = tuple(str(p) for p in extra_game_files(self.em.root))
        return data, extra

    def changes(self):
        now = self._stamp()
        if now == self.seen:
            return []
        self.seen = now
        out = []
        data, extra = now
        problems = forced_problems(data.decode('utf-8', errors='replace')) if data else ['the settings file is gone']
        for text in problems + [f'a per-game file appeared: {e}' for e in extra]:
            if text not in self.reported:
                self.reported.add(text)
                out.append(text)
        return out
