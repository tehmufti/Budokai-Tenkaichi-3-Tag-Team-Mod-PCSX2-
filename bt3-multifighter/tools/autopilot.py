"""Zero-configuration simultaneous teams: watch the emulator and prepare matches.

Run alongside PCSX2 (see launch-autopilot.ps1). The launcher prepares matches
only after a mode is selected in Modded Modes. Original-menu selections stay
native, including Team Battle. Character selection still uses the game's own
roster screens. Headless diagnostic callers without a menu retain auto-detection.

States: MENU (battle loop off), BATTLE (native 1v1 or a battle that was already
handled), PREPARING (trainer running), ACTIVE (prepared match), RECOVER.
After a prepared match, Fight Again reloads the playable checkpoint (the
native rematch cannot rebuild the extra fighters), and leaving to the menu
reloads the clean menu checkpoint captured at boot.
"""
import sys
if __name__ == '__main__' and '--check' in sys.argv[1:]:
    # The launchers' probe (--check below). The imports that follow load the chosen game disc's native references
    # first: a game file that fails there (the executable the European or Japanese table was made from, the chosen
    # disc's folder) is exit 4 'game files', never a traceback that reads as a broken private Python (TTM-PLAY-25/26).
    try:
        import native_map
        if native_map.TRANSLATED:
            native_map.table()
    except (LookupError, ValueError) as error:  # native_map.NativeMapError, game_profile.DiscError
        print(f'CHECK FAILED (game files): {type(error).__name__}: {error}', flush=True)
        raise SystemExit(4)
from native_map import A, CRC, PAL, SERIAL, elf_path
import argparse
import json
import os
import shutil
import runtime_profile
import game_profile
import guest_loading_screen
guest_loading_screen.CHEAT = runtime_profile.CHEATS/game_profile.cheat_name(SERIAL)
import struct
import subprocess
import sys
import threading
import time
import traceback
from functools import lru_cache
from pathlib import Path
from atomic_files import write_json as atomic_json

from pine import PineClient, PineError
from fresh_team_trainer import Session, StreamingSession, PreparationBusyError, STATES, PREFIX, ROOT, ACK_ADDRESS
import native_preparation
import menu_return
import battle_mode_policy
import story_missions
from battle_mode_policy import ACTOR_COUNTS
from battle_mode_policy import TEAM_CAPACITY

SCENE, BATTLE_OBJECT, MANAGER, REPLAY = A(0x331DC8), A(0x2FEB38), A(0x2FEB14), A(0x31BE04)
LOOP_FLAG = SCENE+6648
MODE, HEAP1_START, HEAP1_END = 0xD8080, A(0x2FF084), A(0x2FF08C)
ACTOR_HOOK, NATIVE_PROLOGUE = A(0x1C2A28), bytes.fromhex('f0ffbd270000b0ff')
MENU_SLOT, RELOAD_SLOT = 219, 218
INPUT_HOLD = 0x07361850  # fresh_memory preparation hold word; 1 while the leaders are held idle
SUPPORTED_SIDES = tuple(range(1, TEAM_CAPACITY + 1))
# Freeze watchdog: the render observer counts every submitted graphics packet
# (capacity_stage CONTROL+16), including in-game pause menus and cutscenes. If
# it stops for this long while the emulator runs, the game's main loop is hung.
# Stillness counts only between reads at most WATCH_GAP apart: the first longer
# gap in a stall (Windows asleep) is left out instead of being called a hang;
# any later one counts, so a hang whose reads come slowly is still reported.
import capacity_stage
FRAME_HEARTBEAT = capacity_stage.CONTROL+16
FREEZE_SECONDS = 5.0
WATCH_GAP = 10.0


def hold_snapshot_updates():
    """A shared hold this old (10 s of game updates) leaves a one-line snapshot of who it holds."""
    from native_map import ticks
    return ticks(300)


def savestate_pc(path):
    """The EE program counter saved in a PCSX2 savestate (cpuRegs: 32 GPRs of 16 bytes, HI, LO, CP0[32], sa,
    IsDelaySlot, pc), or None when the file is not a readable savestate."""
    import zipfile
    import state128
    try:
        with zipfile.ZipFile(path) as archive, open(path, 'rb') as raw:
            internals = state128.read_entry(archive, raw, archive.getinfo(state128.INTERNAL))
        at = state128.unique_tag(internals, 'cpuRegs') + 32
        pc = struct.unpack_from('<I', internals, at + 32*16 + 32 + 32*4 + 8)[0]
    except (OSError, KeyError, ValueError, struct.error, zipfile.BadZipFile):
        return None
    return pc


def hang_signature(pc):
    """What a frozen EE program counter is known to mean, for a freeze snapshot's facts."""
    if pc is None:
        return None
    import aux_trail_lists
    first, last = aux_trail_lists.LOOP
    label = 'trail-list cycle' if first <= pc <= last else None
    return dict(pc=f'0x{pc:08X}', label=label)
WINDOWS = os.name == 'nt'  # PowerShell key injection and the pycaw loading-audio helper


def supported_teams(rows, include_single=False):
    return len(rows) == 2 and all(n in SUPPORTED_SIDES for n in rows) and (include_single or max(rows) > 1)


def log(message):
    try:
        print(time.strftime('%H:%M:%S'), message, flush=True)
    except UnicodeEncodeError:
        # A console code page without these characters (a path, Spanish text) never stops the watcher.
        print(time.strftime('%H:%M:%S'), str(message).encode('ascii', 'backslashreplace').decode('ascii'), flush=True)


@lru_cache(maxsize=1)
def native_guards():
    from prototype import elf_reader
    from selected_team_capture import NATIVE_RANGES
    _, _, readelf = elf_reader(elf_path(ROOT))
    return [(address, readelf(address, size)) for address, size in
            (*NATIVE_RANGES, (ACTOR_HOOK, 8), (A(0x12BC8C), 8))]


# Windows API for send_space(pid): which process owns the foreground window, and whether that
# window is a dialog. Passed to PowerShell through the environment, so no quote survives
# Windows command-line parsing.
FOREGROUND_API = ('[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow(); '
                  '[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId('
                  'System.IntPtr window, out uint process); '
                  '[DllImport("user32.dll")] public static extern bool IsWindowEnabled(System.IntPtr window); '
                  '[DllImport("user32.dll")] public static extern System.IntPtr GetWindow(System.IntPtr window, uint command); '
                  '[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText('
                  'System.IntPtr window, System.Text.StringBuilder text, int count);')
# PCSX2's own tool windows (English and Spanish titles). They are separate top-level windows,
# so neither the owner nor the enabled test catches them; Space there presses a control.
TOOL_WINDOWS = r'Settings|Configuraci|Properties|Propiedades|Debugger|Depurador'
# Exit 2: no such process; 3: another program is in front; 4: a PCSX2 dialog or tool window is:
# an owned window (GW_OWNER 4: Qt dialogs with a parent), a disabled one (a modal dialog is open
# over it), or a tool window by its title. The game window is unowned and enabled.
SPACE_TO_OWNED = ("Add-Type -AssemblyName Microsoft.VisualBasic; Add-Type -AssemblyName System.Windows.Forms; "
                  "Add-Type -Namespace TagTeam -Name Foreground -MemberDefinition $env:TAGTEAM_FOREGROUND_API; "
                  "$target = [int]$env:TAGTEAM_EMULATOR_PID; "
                  "$p = Get-Process -Id $target -ErrorAction SilentlyContinue; if (-not $p) { exit 2 }; "
                  "try { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) } catch { exit 3 }; "
                  "Start-Sleep -Milliseconds 300; $window = [TagTeam.Foreground]::GetForegroundWindow(); $owner = [uint32]0; "
                  "[void][TagTeam.Foreground]::GetWindowThreadProcessId($window, [ref]$owner); "
                  "if ($owner -ne $target) { exit 3 }; "
                  "if (-not [TagTeam.Foreground]::IsWindowEnabled($window)) { exit 4 }; "
                  "if ([TagTeam.Foreground]::GetWindow($window, 4) -ne [IntPtr]::Zero) { exit 4 }; "
                  "$title = New-Object System.Text.StringBuilder 512; "
                  "[void][TagTeam.Foreground]::GetWindowText($window, $title, 512); "
                  "if ($title.ToString() -match $env:TAGTEAM_TOOL_WINDOWS) { exit 4 }; "
                  "[System.Windows.Forms.SendKeys]::SendWait(' ')")


def say(template, **values):
    """A console line in the player's language (localization.tr). {play} is this installation's
    launcher (native_preparation.launcher); values are never templates."""
    values.setdefault('play', native_preparation.launcher())
    try:
        import localization
        return localization.tr(template, **values)
    except Exception:  # noqa: BLE001 - a message only: English then
        return template.format(**values)


def say_text(text):
    """A fixed sentence (a pending reason, the closed-PCSX2 notice) in the player's language. It is never formatted,
    so braces in it stay as they are; English when it has no translation."""
    try:
        import localization
        return localization.tr(text)
    except Exception:  # noqa: BLE001 - a message only: English then
        return text


def send_space(pid=None):
    """Press PCSX2's pause key (Space) in the emulator window.

    With `pid` (the emulator this launcher started) only that process is activated, and the
    key is sent only once its game window is really in front: never into another program
    when Windows refuses the focus change, and never into a PCSX2 dialog or settings window,
    where Space would press a control. Returns whether it was sent. Without a PID the first
    'pcsx2-qt' is used, as before."""
    if not WINDOWS:
        # No portable key injection (Wayland has none) and PINE has no pause opcode: the
        # player presses PCSX2's pause key. The Linux launcher also runs with --manual-pause.
        log('Press the PCSX2 pause key (Space by default) in the game window to continue.')
        return False
    if pid is None:
        script = ("Add-Type -AssemblyName Microsoft.VisualBasic; Add-Type -AssemblyName System.Windows.Forms; "
                  "$p = Get-Process -Name 'pcsx2-qt' -ErrorAction SilentlyContinue | Select-Object -First 1; "
                  "if ($p) { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id); Start-Sleep -Milliseconds 300; "
                  "[System.Windows.Forms.SendKeys]::SendWait(' ') }")
        subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True, timeout=20)
        return None
    environment = dict(os.environ, TAGTEAM_FOREGROUND_API=FOREGROUND_API, TAGTEAM_EMULATOR_PID=str(int(pid)),
                       TAGTEAM_TOOL_WINDOWS=TOOL_WINDOWS)
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-Command', SPACE_TO_OWNED], capture_output=True,
                                text=True, timeout=20, env=environment)
    except (OSError, subprocess.SubprocessError) as error:
        log(say(SAY_NO_KEY, error=error))
        return False
    if result.returncode != 0:
        log(say(SAY_NOT_IN_FRONT))
    return result.returncode == 0


class Observation:
    def __init__(self, p, status=None):
        # Fetch independent fields together. PINE executes each request on the
        # emulator thread; dozens of tiny round trips add avoidable polling work.
        captured = {}
        def capture(ranges):
            if hasattr(p, 'read_ranges'):
                captured.update(zip(ranges, p.read_ranges(ranges)))
        def read(address, size):
            key = (address, size)
            return captured[key] if key in captured else p.read(address, size)
        u = lambda address: struct.unpack('<I', read(address, 4))[0]
        self.status = p.status() if status is None else status
        guards = native_guards()
        capture([(address,4) for address in (LOOP_FLAG,BATTLE_OBJECT,SCENE+8,
            SCENE+192,SCENE+816,MANAGER,REPLAY,MODE,HEAP1_START,HEAP1_END,
            INPUT_HOLD,native_preparation.HOOK,native_preparation.CONTROL+20,
            native_preparation.CONTROL+56,menu_return.RESULT_FLAGS,menu_return.REASON_FLAGS)]
            + [(ACTOR_HOOK,8),(ACK_ADDRESS,16)] + [(a,len(b)) for a,b in guards])
        self.loop = u(LOOP_FLAG)
        obj = u(BATTLE_OBJECT)
        self.battle_object = obj
        manager = u(MANAGER)
        scene_counts = [u(SCENE+192+624*i) for i in range(2)]
        capture(([(obj,4)] if 0x100000 <= obj < 0x8000000 else []) +
                ([(manager,4),(manager+4,4),(manager+16,4)] if 0x100000 <= manager < 0x8000000 else []) +
                [(SCENE+196+624*i+100*j,4) for i,n in enumerate(scene_counts)
                 for j in range(n if 1 <= n <= 5 else 0)])
        self.battle_state = u(obj) if 0x100000 <= obj < 0x8000000 else -1
        self.mode = u(SCENE+8)
        self.scene_rows = scene_counts
        self.scene_characters = [tuple(u(SCENE+196+624*i+100*j) for j in range(n))
                                 if 1 <= n <= 5 else () for i,n in enumerate(self.scene_rows)]
        self.manager = u(MANAGER)
        self.count = u(self.manager) if 0x100000 <= self.manager < 0x8000000 else -1
        self.initialised = bool(u(self.manager+16) & 1) if self.count >= 0 else False
        self.rows, self.slots, self.hp, self.actions, self.characters = [], [], [], [], []
        self.array = 0
        if self.count == 2:
            self.array = u(self.manager+4)
            if 0x100000 <= self.array <= 0x8000000-0x2C00 and self.array % 16 == 0:
                capture([(self.array+i*0x1600+offset,4) for i in range(2) for offset in (0x994,0x998,0x948)])
                counts = [u(self.array+i*0x1600+0x998) for i in range(2)]
                capture([(self.array+i*0x1600+0x9E4+min(u(self.array+i*0x1600+0x994),4)*0xA4,4) for i in range(2)] +
                        [(self.array+i*0x1600+0x9A4+j*0xA4,4) for i,n in enumerate(counts)
                         for j in range(n if 1 <= n <= 5 else 0)])
                for i in range(2):
                    actor = self.array+i*0x1600
                    slot = u(actor+0x994); rows = u(actor+0x998)
                    self.rows.append(rows); self.slots.append(slot)
                    self.hp.append(struct.unpack('<i', read(actor+0x9E4+min(slot, 4)*0xA4, 4))[0])
                    self.actions.append(u(actor+0x948))
                    self.characters.append(tuple(u(actor+0x9A4+j*0xA4) for j in range(rows)) if 1 <= rows <= 5 else ())
        self.replay = u(REPLAY)
        self.team_mode = u(MODE)
        self.heap1 = u(HEAP1_START) | u(HEAP1_END)
        self.native_hook = read(ACTOR_HOOK, 8) == NATIVE_PROLOGUE
        self.changed_native = [hex(address) for address, expected in guards
                               if read(address, len(expected)) != expected]
        self.ack = read(ACK_ADDRESS, 16)
        self.hold = u(INPUT_HOLD)
        self.streaming = (read(native_preparation.HOOK,4)==native_preparation.HOOK_WORD)
        self.native_held = self.streaming and u(native_preparation.CONTROL+20)==1
        self.native_intro = self.streaming and u(native_preparation.CONTROL+56)==1
        self.result_flags = u(menu_return.RESULT_FLAGS)
        self.return_flags = u(menu_return.REASON_FLAGS)
        self.menu_scene = menu_return.read_scene(p) if self.loop == 0 else None

    @property
    def clean(self):
        # A load acknowledgement can legitimately survive restoring a clean
        # original state. Actual hooks/heap ownership determine cleanliness.
        return self.heap1 == 0 and self.team_mode == 0 and self.native_hook and not self.changed_native

    @property
    def pending_reason(self):
        # Fixed sentences: the Play window shows them through say_text (Spanish in localization.ES).
        if self.loop != 1: return 'Waiting in the game menus until a match starts.'
        if self.mode != 0: return 'This game mode is not one the mod prepares, so it plays normally.'
        if self.replay != 0: return 'Replay playback: the mod does not change replays.'
        if self.battle_state not in (2, 3): return 'Waiting for the battle to finish loading.'
        if self.count != 2 or not self.initialised or len(self.rows) != 2:
            return 'Waiting for both team leaders and their selected teams to initialize.'
        if not all(1 <= r <= 5 for r in self.rows): return 'Waiting for valid selected rosters.'
        if not all(s == 0 for s in self.slots): return 'A leader already tagged or was replaced; start a fresh match.'
        if not all(h > 0 for h in self.hp): return 'A leader is already defeated; start a fresh match.'
        return None

    @property
    def fresh_battle(self):
        return self.pending_reason is None

    @property
    def early_teams(self):
        return self.selected_early_teams()

    def selected_early_teams(self, include_single=False):
        if (self.loop != 1 or self.mode != 0 or self.replay != 0 or not self.clean or
                not supported_teams(self.scene_rows, include_single=include_single)):
            return None
        if not all(len(team) == count and all(0 <= c <= 160 for c in team)
                   for team, count in zip(self.scene_characters, self.scene_rows)): return None
        return self.scene_characters

    @property
    def key(self):
        return (self.manager, self.array, tuple(self.rows), tuple(self.characters))

    def summary(self):
        return {key: getattr(self, key) for key in ('status', 'loop', 'battle_state', 'mode',
            'manager', 'array', 'count', 'initialised', 'rows', 'slots', 'hp', 'actions',
            'characters', 'replay', 'team_mode', 'heap1', 'native_hook', 'changed_native', 'hold')}


# The cover messages of a fresh preparation, in the order they appear: the fresh-detection
# cover, Session.progress stage labels (fresh_team_trainer), then the Ready frame.
PREPARATION_MESSAGES = ('Loading your selected fighters...', 'Getting your fighters ready...', 'Preparing team battle', 'Loading fighters',
                        'Preparing arena', 'Getting ready', 'Starting your match...')

# Recovered or explained watcher failures (beta.33). The text is fixed, so player_errors can
# translate it (localization.ES); the facts behind each one go to its context and the log.
MAIN_INSTEAD = 'The game went to a menu the mod cannot restore, so the clean main menu was loaded instead'
MAIN_AFTER_WAIT = 'The game did not say which menu it went to after the match, so the clean main menu was loaded instead'
MAIN_AFTER_FAILURE = 'Returning to character selection failed, so the clean main menu was loaded instead'
MENU_LOCK_BUSY = 'Another operation kept the preparation lock for 30 seconds, so no menu was loaded over it'
UPDATES_OFF = ('Transformations, Body Change and fusion timers are off for the rest of this match. '
               'The match goes on; start a new match to turn them back on')
PAGER_STOPPED = ("The Modded Modes menu stopped. The game's own menus still work; to use Modded Modes, "
                 'close PCSX2, then start {play} again')
PAGER_RESET = 'The Modded Modes menu rejected a choice and was reset. Choose again'
# The pager's own notices (player_errors.Detected): HOW TO FIX is their real next step, never the generic one.
PAGER_RESET_WHAT = 'At the main menu, the Modded Modes menu rejected a choice and was reset.'
PAGER_RESET_FIX = 'Choose your mode again in Modded Modes.'
PAGER_STOPPED_WHAT = "At the main menu, the Modded Modes menu stopped; the game's own menus still work."
PAGER_STOPPED_FIX = ('You can keep playing the original modes. To use Modded Modes again, close PCSX2, then start '
                     '{play} again.')
PAGER_CHOICES = ('Invalid native mode choice', 'Invalid in-game mode selection')  # a rejected queued choice only
INPUT_STUCK = ('A controller input thread did not stop; it was left running in the background. '
               'Players 1 and 2 are not affected')
REMATCH_UNCONFIRMED = 'The game did not confirm loading the rematch checkpoint'

# Console lines (autopilot.log, the Play window), translated through say(). {play} is this
# installation's launcher; the error details stay English.
SAY_RUNNING = 'Tag Team Mod is running. At the main menu, press {button} for Modded Modes.'
SAY_CARRIES_CHANGES = ('This PCSX2 already carries changes from an earlier preparation. Close PCSX2, then start '
                       '{play} again for a new roster.')   # group A's wording
SAY_MENU_PAUSED = 'The game is paused in its menus. Resume it with Space (or System > Resume in PCSX2).'
SAY_LOADING_PAUSED = ('PCSX2 is paused. Loading your fighters continues when you resume it (Space, or System > '
                      'Resume in PCSX2).')
SAY_LOADING_RESUMED = 'PCSX2 resumed; loading your fighters continues.'
SAY_INTRO_CONTINUED = 'The match intro stopped at its start; the mod continued it.'
SAY_NOT_IN_FRONT = ("The game window of PCSX2 is not in front (another program or a PCSX2 dialog is), so no key "
                    'was pressed. Click the game window and press Space.')
SAY_NO_KEY = 'Could not press Space in PCSX2 ({error}). Click the game window and press Space.'
SAY_PINE_WAIT = {
    'menus': 'PCSX2 did not answer in the menus ({error}); trying again in {delay} s.',
    'match': 'PCSX2 did not answer while a match was starting ({error}); trying again in {delay} s.',
    'main': 'PCSX2 did not answer while the main menu was loading ({error}); trying again in {delay} s.',
    'character_select': 'PCSX2 did not answer while character selection was loading ({error}); trying again in {delay} s.'}
SAY_MAIN_INSTEAD = 'Character selection could not be loaded ({error}); loading the main menu instead.'
SAY_RETURN_FAILED = {
    'main': ('Returning to the main menu failed: {error}. No checkpoint was loaded, so the game is in its own menus '
             'with this match still set up. Close PCSX2, then start {play} again.'),
    'character_select': ('Returning to character selection failed: {error}. No checkpoint was loaded, so the game is '
                         'in its own menus with this match still set up. Close PCSX2, then start {play} again.')}
SAY_RETURN_CANCELLED = 'The match continued, so the return to the menu was cancelled.'
SAY_PAGER_FAULT = 'The Modded Modes menu stopped: {error}.'
SAY_UPDATE_STOPPED = 'Fighter update stopped: {error}. {hold} Close PCSX2, then start {play} again.'
SAY_HELD = 'Combat is held.'
SAY_HOLD_UNCONFIRMED = 'Combat hold could not be confirmed.'
SAY_SERVICES_CHANGED = 'The fighter update services changed while the match was out of combat; attaching again.'
SAY_ORIGINAL_MENU = "Original-menu match: the game plays it normally, without the mod's team setup."
SAY_MENU_INPUT_OFF = ('Three/four-player input unavailable: {detail}. Players 3 and 4 (and the all-controllers option) '
                      'cannot use their controllers on this selection screen; players 1 and 2 are not affected.')
SAY_MENU_INPUT_RETRY = ('Three/four-player input unavailable: {detail}. Players 3 and 4 (and the all-controllers option) '
                        'cannot use their controllers yet (trying again); players 1 and 2 are not affected.')
SAY_ASSIGNMENT_STOPPED = ('Controller assignment stopped: {detail}. Default controls are restored (players 1 and 2 use '
                          'their PCSX2 controllers); assign controllers again in Player Setup.')
SAY_BATTLE_INPUT_STOPPED = ('3-4 player input stopped: {detail}. Players 3 and 4 cannot use their controllers in this '
                            'match; the match goes on and players 1 and 2 are not affected.')
# The Play-window code of the three input-stopped lines above (player_errors.EVENT_CODES).
INPUT_STOPPED_CODE = 'TTM-CTRL-25'
# Online play (netplay_frame CONTROL: MAGIC 'NPF1' + state): while it runs the controller hub stays passive. The kit
# stores MAGIC as a little-endian word (netplay_frame.MAGIC 0x4E504631, struct '<I'), so RAM holds b'1FPN'.
NETPLAY_CONTROL, NETPLAY_MAGIC = 0x07B01000, 0x4E504631


def online_active(p):
    """True while the online kit's lockstep frame is armed or running (never arm the P1/P2 override, no sinks)."""
    try:
        data = bytes(p.read(NETPLAY_CONTROL, 8))
    except (AttributeError, KeyError, TypeError):   # test doubles without this address
        return False
    if len(data) != 8:
        return False
    magic, state = struct.unpack('<2I', data)
    return magic == NETPLAY_MAGIC and state != 0
# A FAILED watcher whose game reached its menus (G7a): said once, then the failure block again.
SAY_FAILED_AT_MENUS = ('The game is in its menus now, but the mod stays stopped after this error, so no modded match '
                       'can start:')
# The Play window's routine lines (beta.33 round 4): plain words in the player's language. What a player cannot act on
# (the rematch checkpoint path, the clean-menu captures) stays in watcher.log on lines the Play window does not echo
# (play_launcher.DENY_LINE); the closing lines are hidden once PCSX2 has closed (play_launcher.CLOSING_LINE).
SAY_FRESH_MATCH = 'New {teams} match: getting every fighter ready. They stay still until the match starts.'
SAY_FRESH_PAUSE = 'New {teams} match: press Space in the game window to pause it, so every fighter can be loaded.'
SAY_FRESH_FFA = 'New free-for-all with {count} fighters: getting every fighter ready. They stay still until the match starts.'
SAY_FRESH_FFA_PAUSE = ('New free-for-all with {count} fighters: press Space in the game window to pause it, so every '
                       'fighter can be loaded.')
SAY_PAUSE_UNCONFIRMED = ('PCSX2 did not confirm the automatic pause. Press Space in the game window to start loading '
                         'your fighters.')
SAY_MATCH_READY = 'The match is ready: every fighter is on the field.'
SAY_REMATCH_LOADING = 'Fight Again: loading the prepared match again.'
SAY_REMATCH_READY = 'The rematch is ready.'
SAY_REMATCH_INTERRUPTED = 'Fight Again stopped: PCSX2 is closing or its game was shut down.'
SAY_GAME_RUNNING = 'The game is running again; loading your fighters continues.'
SAY_HOLD_RESUMING = 'The game is paused while your fighters load; PCSX2 was asked to resume it.'
SAY_HOLD_PAUSED = 'The game is paused while your fighters load. Resume it with Space (or System > Resume in PCSX2).'
SAY_WAITING_HOLD = 'Waiting for the game to hold the fighters for loading.'
SAY_ONE_ON_ONE = '1v1 match: the game plays it normally.'
SAY_TOO_MANY = 'This {teams} match has more than {capacity} fighters on a side, so it plays as a normal tag match.'
SAY_RETURNED = {'main': 'Back at the main menu.', 'character_select': 'Back at character selection.'}
SAY_RETURN_WAITS = 'Returning to the menu once the previous step finishes.'
SAY_CAPTURE_DELAYED = 'Saving the menu the mod returns to after a match is delayed ({error}); trying again.'
SAY_MENU_RESUMING = 'PCSX2 was paused in the menus; resuming it.'
SAY_BOOTING = 'Waiting for PCSX2 to start the game.'
SAY_OTHER_GAME = 'Waiting for PCSX2 to start the installed game ({expected}); it shows {serial} (CRC {crc}).'
SAY_NO_CONNECTION = 'The connection to PCSX2 did not answer ({error}); trying again.'
SAY_UNUSABLE = 'The mod cannot use this PCSX2 ({error}).'
SAY_SELECTED = 'Modded Modes: {mode}, {players}.'
# Also said on every arrival at the main menu: the pager arms its stock page there (native_mode_menu arm_stock, choice 5).
SAY_ORIGINAL_CHOSEN = "Original game menu: its matches play normally, without the mod's team setup."
ORIGINAL_MENU_CHOICE = 5   # ORIGINAL GAME MENU: mode_menu.RETURN_CHOICE, the native pager's only original-menu choice
MODE_LABELS = {'teams': 'Team Battle', 'ffa': 'Free-for-all', 'coop': 'Co-op', 'training': 'Modded Training',
               'training_coop': 'Co-op training'}


def selection_line(selected):
    """The Play window's line for a pager choice (a tick() result): the original game menu is named as such (it maps
    to ('teams', 1) only so that its matches play natively); a Modded Modes choice names its mode and players."""
    if selected.get('choice') == ORIGINAL_MENU_CHOICE:
        return say(SAY_ORIGINAL_CHOSEN)
    humans = int(selected.get('humans') or 0)
    players = 'CPU Only' if humans == 0 else '1 Player' if humans == 1 else f'{humans} Players'
    mode = selected.get('mode')
    return say(SAY_SELECTED, mode=say_text(MODE_LABELS.get(mode, str(mode))), players=say_text(players))

# Problems the watcher detects itself (player_errors.Detected, beta.33 round 2): fixed English sentences with
# Spanish in localization.ES; the numbers and paths go to DETAILS and the report file.
FROZEN_WHAT = ('The game stopped responding during the match: its picture did not change for 5 seconds while PCSX2 '
               'was running.')   # 5 = FREEZE_SECONDS
FROZEN_WHY = ('The game hung inside the match, a rare problem of the mod with some moves, effects or rosters that is '
              'not fixed yet.')
FROZEN_FIX = ('Close PCSX2, then start {play} again. So that the next freeze can be fixed, open {mod_settings}, choose '
              'Diagnostics and turn on "Save a large diagnostic snapshot if a match freezes"; then send the snapshot '
              'and the report file to the mod author.')
FROZEN_FIX_SAVED = ('Close PCSX2, then start {play} again. Send the report file and the diagnostic snapshot it names '
                    'to the mod author.')
FROZEN_FIX_NOT_SAVED = 'Close PCSX2, then start {play} again. If it happens again, send the report file to the mod author.'
SAY_FROZEN_RESUMED = 'The game is drawing again after it stopped responding; the match goes on.'
SAY_SAVING_SNAPSHOT = 'The game stopped responding. Saving a diagnostic snapshot; this takes a moment.'
SAY_SAVING_START_SNAPSHOT = ('The game stopped drawing while the match was starting. Saving a diagnostic snapshot; this '
                             'takes a moment.')
SAY_SNAPSHOT_SAVED = 'Diagnostic snapshot saved: {path}'
HOLD_RELEASED_WHAT = 'A cinematic pause did not end on its own, so the mod released it; the fighters are moving again.'
HOLD_RELEASED_WHY = 'A special move or transformation held every fighter for longer than its limit.'
HOLD_RELEASED_FIX = ('You can keep playing. If it happens again, note which move was used and send the report file to '
                     'the mod author.')
RESTARTED_WHAT = 'The game restarted during the match, so the mod loaded the clean main menu.'
RESTARTED_WHY = 'PCSX2 was reset, or the game rebooted itself (for example after a crash).'
RESTARTED_FIX = ('You can keep playing: choose your next match. If it happens again, send the report file to the mod '
                 'author.')
PINE_SLOW_WHAT = {
    'menus': 'PCSX2 did not answer the mod several times in a row in the menus; the mod keeps trying.',
    'match': 'PCSX2 did not answer the mod several times in a row while a match was starting; the mod keeps trying.'}
PINE_SLOW_WHY = 'PCSX2 was busy (loading, an open settings window or a slow PC), or its connection dropped for a moment.'
PINE_SLOW_FIX = 'You can keep playing. If no modded match starts, close PCSX2, then start {play} again.'


class Autopilot:
    def __init__(self, mode='Original', poll=0.2, menu_checkpoint=True, status_file=None, manual_pause=False,
                 presentation=None, lifetime=None, in_game_menu=False, launcher_token=None):
        self.launcher_token = launcher_token
        self.mode, self.poll, self.menu_checkpoint = mode, poll, menu_checkpoint
        self.handled = set()
        self.noted = set()
        self.playable = None
        self.ack_token = None
        self.state = 'MENU'
        self.menu_saved = False
        self.worker = None
        self.reload_worker = None
        self.body_worker = None
        self.fusion_worker = None
        self.reload_capture = None
        self.reload_epoch = None
        self.result = {}
        self.resume_needed = False
        self.resume_attempted = False
        self.status_file = Path(status_file) if status_file else None
        self.last_report = None
        self.last_status_time = 0
        self.report_lock = threading.RLock()
        self.status_error = False
        self.connection_error = say(SAY_BOOTING)
        self.last_loop = 0
        self.manual_pause = manual_pause
        self.presentation = presentation
        self.cover_started = False
        self.progress = 0
        self.play_intro_after_loading = False
        self.deferred_intro_object = None
        self.intro_repairs = 0
        self.phase1_since = None         # (battle object, first and last running poll in phase 1), streaming
        self.phase1_stall = None         # this match's phase-1 stall record (status.json 'phase1_stall')
        self.lifetime = lifetime
        self.game_seen = False   # PINE has answered with this session's game running (observe)
        from controller_mailbox import Owner
        # Off Windows a failed 3-4 player input check reaches the status the launcher shows,
        # and so does its recovery after a provisional "could not be confirmed yet".
        unavailable = lambda message: self.report(message, None, 'warning')
        recovered = lambda message: self.report(message, None, 'info')
        # One SDL owner thread for the whole Play session (controller_hub): every input owner below is a sink of it.
        import controller_hub
        hub = self.controller_hub = controller_hub.Hub(lifetime.process.pid, log=log) if lifetime is not None else None
        self.controller_input = Owner(lifetime.process.pid, report=unavailable, notice=recovered, hub=hub) if lifetime is not None else None
        from quad_menu_input import Owner as MenuInputOwner
        self.menu_input = MenuInputOwner(lifetime.process.pid, report=unavailable, notice=recovered, hub=hub) if lifetime is not None else None
        self.menu_input_failed = None  # {capture, retry time or None} of a failed three/four-player attach
        self.battle_input_failed = self.battle_input_reported = None  # match capture whose 3-4 player input failed / was reported
        self.assignment_failed = self.assignment_reported = None   # capture whose P1/P2 check-in input failed / was reported
        self.hub_match = None          # the match capture the hub last counted (per-match messages and self-heal)
        self.input_checked = WINDOWS   # the startup 3-4 player input check runs once, off Windows
        from controller_assignment import Owner as AssignmentOwner
        self.assigned_input = AssignmentOwner(lifetime.process.pid, hub=hub) if lifetime is not None else None
        self.battle_mode, self.humans = 'teams', 1
        self.assignment=None
        self.menu_checkpoints = None
        self.menu_return_started = None
        self.mode_menu = None
        from battle_diagnostics import Recorder
        self.battle_diagnostics = Recorder()
        self.heartbeat = None      # (packet count, time it last changed)
        self.heartbeat_read = None # when the match's freeze watch last read it (WATCH_GAP)
        self.heartbeat_gap = False # a gap was already left out of the current stall (WATCH_GAP)
        self.freeze_dumped = False       # one diagnostic snapshot per match
        self.freeze_reported = False     # the current freeze was reported (TTM-MATCH-20)
        self.frozen_count = self.freeze_record = None   # its heartbeat and last_error record, until it draws again
        self.hold_overruns = None
        self.hold_snapshot = False       # the current shared hold already left its long-hold snapshot (C2)
        self.trail_faults_logged = False # this match's trail-list faults were logged once
        self.preparation_session = None  # the running preparation's Session (its unused slot takes an intro snapshot)
        self.preparation_lock = threading.Lock()
        self.start_freeze_capture = None # a snapshot of a preparation's frozen intro (LS-2), named in its failure
        self.failure_repeated = False    # a FAILED watcher repeated its block at the menus (G7a)
        self.menu_return_boot = 0        # polls in a row that showed the boot scene during a menu return (G7b)
        self.menu_return_restarted = False   # this menu return follows a game restart
        self.pine_errors = 0             # consecutive transient PINE errors outside observe()
        self.menu_return_fallback = None # (safe-top-level candidate, consecutive polls) of an unknown return
        self.menu_return_seen = None     # last logged (scene, manager, result, reason) of a menu return
        self.menu_resume_sent = False    # the paused boot menu is resumed at most once per session
        self.fighter_updates_off = None  # capture whose fighter updates were switched off after a refusal
        self.rematch_run = None          # this watcher's newest rematch lease folder
        self.preparation_paused = False  # a streaming preparation is waiting for PCSX2 to resume
        self.workers_parked = False      # fighter-update workers kept for a moment out of combat
        self.menu_restore_errors = 0     # connection errors while loading a menu checkpoint (this return)
        self.menu_pager_failures = 0     # consecutive Modded Modes pager faults
        self.menu_pager_stopped = False  # the pager was closed for this session after a fault
        self.pause_probe_at = 0.0
        self.progress_message = PREPARATION_MESSAGES[0]
        import mod_settings
        self.diagnostic_settings=mod_settings.load_settings() if in_game_menu else dict(mod_settings.DEFAULTS)
        if in_game_menu:
            import native_mode_menu
            import mod_settings
            self.mode_menu = native_mode_menu.Controller(settings=mod_settings.load_settings())
            self.mode_menu.team_menu.hub=getattr(self,'controller_hub',None)
            self.mode_menu.team_menu.log=log

    def checkpoints(self):
        if self.menu_checkpoints is None:
            self.menu_checkpoints = menu_return.MenuCheckpoints()
        return self.menu_checkpoints

    @property
    def preparation_enabled(self):
        # The launcher always installs a menu controller. Merely opening its
        # page is not an opt-in: only a committed custom mode grants ownership.
        return self.mode_menu is None or bool(getattr(self.mode_menu,'custom_match',False))

    def sync_preparation(self, obs):
        if not (obs.streaming and obs.clean):return
        with PineClient(timeout=5) as p:
            if self.preparation_enabled:
                native_preparation.arm(p, include_single_ffa=battle_mode_policy.prepare_singleton(self.battle_mode,self.humans) or story_missions.pending_for(self.battle_mode))
            else:
                native_preparation.disarm(p)

    MENU_INPUT_RETRY = (2.0, 30.0)  # first and longest wait before a failed attach is tried again

    def check_controller_input(self):
        """Off Windows, once the game runs: can 3-4 player input work here (SDL2, PCSX2's memory)?
        The owner caches the verdict for this emulator and reports a failure once."""
        if self.controller_input is None:self.input_checked=True;return
        try:
            with PineClient(timeout=5) as p:self.controller_input.available(p)
        except (OSError,PineError) as error:
            log(f'Three/four-player input check delayed: {error}');return   # PINE busy: next poll
        self.input_checked=True

    def controller_settings(self):
        """(controller_checkin mode, keep_controller_checkins) from the settings the menus use."""
        settings=getattr(self.mode_menu,'settings',None) or {}
        return settings.get('controller_checkin'),settings.get('keep_controller_checkins')

    def drain_controller_messages(self, obs=None):
        """The controller hub's Play-window lines (TTM-CTRL-20..24 and 'Player n is back on ...'), in the
        player's language, prefixed with their code."""
        hub=getattr(self,'controller_hub',None)
        if hub is None:return
        try:messages=hub.take_messages()
        except RuntimeError:return
        for level,code,template,values in messages:
            text=say(template,**values)
            self.report(f'{code}: {text}' if code else text,obs,level)

    def timed_attach(self, kind, owner, attach):
        """Run an owner's attach; a new sink is logged with its duration (the EEmem base makes it milliseconds)."""
        before=getattr(owner,'service',None);started=time.perf_counter()
        try:attach()
        finally:
            after=getattr(owner,'service',None)
            if after is not None and after is not before:
                log(f'Controller input: {kind} sink attached in {(time.perf_counter()-started)*1000:.1f} ms.')

    def wants_assignment(self, in_match):
        """The P1/P2 sink is needed: Player Setup is open (lights, press matching) or the roster arms the override."""
        hub=getattr(self,'controller_hub',None)
        if hub is None or hub.state=='failed':return False
        menu=getattr(getattr(self,'mode_menu',None),'team_menu',None)
        if hub.setup_open or bool(getattr(menu,'active',False)):return True
        # 'Allow all controllers during character selection': the hub reads PCSX2's ports while the selector serves
        # free controllers, so a pad PCSX2 already uses is recognised and never moves a second cursor.
        selector=getattr(self,'menu_input',None)
        if not in_match and getattr(selector,'seats',None)=='extras' and getattr(selector,'service',None) is not None:
            return True
        import controller_checkin
        return controller_checkin.p12(hub.checkin.roster,in_match)[0]

    def attach_menu_input(self, menu_input, capture, obs=None):
        """Controllers 3/4 in character select. If they cannot work here (no SDL2, no access to
        PCSX2's memory), say so once per selection screen and keep watching: players 1 and 2 play on.
        Other failures are tried again after a growing pause."""
        failed=getattr(self,'menu_input_failed',None)
        if failed is not None and failed['capture']==capture and (failed['retry'] is None or time.monotonic()<failed['retry']):
            return
        try:
            with PineClient(timeout=5) as p:self.timed_attach('selector',menu_input,lambda:menu_input.attach(p,capture))
        except Exception as error:
            from runtime_owner import EmulatorClosed
            if isinstance(error,EmulatorClosed):raise
            from controller_mailbox import AttachPending, MailboxUnavailable, plain_reason
            if isinstance(error,AttachPending):return   # the EE base is still being located: next tick, silently
            from input_binding import SDLUnavailable
            again=failed is not None and failed['capture']==capture
            first,longest=self.MENU_INPUT_RETRY
            delay=None if isinstance(error,(SDLUnavailable,MailboxUnavailable)) else min(longest,failed['delay']*2) if again else first
            self.menu_input_failed=dict(capture=capture,delay=delay,retry=None if delay is None else time.monotonic()+delay)
            try:menu_input.close()
            except Exception as close_error:log(f'Could not release three/four-player input: {close_error}')
            detail=plain_reason(error)
            if again:
                log(f'Three/four-player input still unavailable: {detail}.'+('' if delay is None else f' Trying again in {delay:.0f} s.'))
                return
            message=say(SAY_MENU_INPUT_OFF if delay is None else SAY_MENU_INPUT_RETRY,detail=detail)
            self.report(f'{INPUT_STOPPED_CODE}: {message}' if delay is None else message,obs,'warning')
        else:self.menu_input_failed=None

    def attach_assigned_input(self, assigned, p, capture, obs=None, *, in_match=False):
        """The check-in's P1/P2 sink for `capture` (the hub arms it from the roster). If it cannot start (no access
        to PCSX2's memory, OpenProcess refused...), say so once for this capture, disarm (PCSX2's own controls for
        players 1 and 2) and keep watching; a later capture tries again. A closed emulator and PINE failures
        (PineError, the socket's connection and timeout errors) still propagate."""
        if getattr(self,'assignment_failed',None)==capture:return
        try:
            self.timed_attach('assignment',assigned,lambda:assigned.attach(p,capture,allow_arm=True,in_match=in_match))
        except Exception as error:
            from runtime_owner import EmulatorClosed
            if isinstance(error,(EmulatorClosed,PineError,ConnectionError,TimeoutError)):raise
            import controller_assignment
            from controller_mailbox import AttachPending, plain_reason
            if isinstance(error,AttachPending):return   # the EE base is still being located: next tick, silently
            # Remove the sink once. A hub that does not answer is dropped, never asked again.
            try:assigned.close()
            except Exception as close_error:log(f'Could not release the assigned controllers: {close_error}')
            assigned.service=assigned.capture=None
            self.assignment_failed=capture
            p.write_u32(controller_assignment.CONTROL+12,0)   # disarm the hook; PINE errors propagate
            detail=plain_reason(error)
            if getattr(self,'assignment_reported',None) is not None:
                log(f'Controller assignment still unavailable: {detail}.');return
            self.assignment_reported=capture
            self.report(f'{INPUT_STOPPED_CODE}: '+say(SAY_ASSIGNMENT_STOPPED,detail=detail),obs,'warning')

    def attach_battle_input(self, p, capture, rewound=False, obs=None):
        """Players 3 and 4 in a prepared match. If their input cannot start or stops (no SDL2, no
        access to PCSX2's memory, OpenProcess refused, a failed input thread...), release it, say so
        once for this match and keep the match: players 1 and 2 and the fighter updates go on. It is
        tried again after a rewind or once the watcher starts the match over (the next match); a
        repeated failure in the same match is only logged. A closed emulator and PINE failures
        (PineError, the socket's connection and timeout errors) still propagate."""
        owner=self.controller_input
        if getattr(self,'battle_input_failed',None)==capture and not rewound:return
        try:
            self.timed_attach('battle',owner,lambda:owner.attach(p,capture,rewound=rewound))
        except (OSError,ValueError,RuntimeError) as error:
            from runtime_owner import EmulatorClosed
            if isinstance(error,(EmulatorClosed,PineError,ConnectionError,TimeoutError)):raise
            from controller_mailbox import AttachPending, plain_reason
            if isinstance(error,AttachPending):return   # the EE base is still being located: next tick, silently
            # Close the input thread once. One that does not stop is dropped, never closed again.
            try:owner.close()
            except Exception as close_error:log(f'Could not release three/four-player input: {close_error}')
            owner.service=owner.capture=None
            self.battle_input_failed=capture
            detail=plain_reason(error)
            if getattr(self,'battle_input_reported',None)==capture:
                log(f'3-4 player input still unavailable: {detail}.');return
            self.battle_input_reported=capture
            self.report(f'{INPUT_STOPPED_CODE}: '+say(SAY_BATTLE_INPUT_STOPPED,detail=detail),obs,'warning')

    def service_menu(self, obs):
        """Make menu navigation ready before checkpoint IO; avoid nested PINE."""
        native_menu=bool(getattr(self.mode_menu,'native',False))
        scene=obs.menu_scene
        assigned=getattr(self,'assigned_input',None)
        online=False
        if assigned is not None:
            import native_mode_menu as native_menu_module
            with PineClient(timeout=5) as p:
                online=online_active(p)
                if getattr(self,'controller_hub',None) is not None:self.controller_hub.online=online
                # Arm only in modded matches (beta.36's rule), never online.
                custom=bool(self.preparation_enabled or (native_menu and p.read_u32(native_menu_module.CONTROL+4)==2))
                if custom and not online and self.wants_assignment(False):
                    self.attach_assigned_input(assigned,p,('menu',),obs,in_match=False)
                else:assigned.disable(p)
        menu_input=getattr(self,'menu_input',None)
        if menu_input is not None:
            shared_selection=getattr(self.mode_menu,'settings',{}).get('all_controllers_character_select',False)
            if (self.preparation_enabled and not online and scene is not None and scene.kind=='character_select'
                    and (self.humans>=3 or shared_selection)):
                menu_input.seats='private' if self.humans>=3 else 'extras'
                self.attach_menu_input(menu_input,(scene.manager,scene.object),obs)
            else:menu_input.close();self.menu_input_failed=None
        stock_main=bool(scene is not None and getattr(scene,'kind',None)=='main' and getattr(scene,'ready',False))
        def capture(capture_scene=None):
            if not(self.menu_checkpoint and obs.clean and obs.status=='running'):return
            try:
                record=self.checkpoints().consider_scene(scene if capture_scene is None else capture_scene,clean=True)
                if record:
                    self.menu_saved=True
                    log(f"Saved clean {record['kind'].replace('_',' ')} checkpoint.")
            except (OSError,ValueError,RuntimeError,TimeoutError) as error:
                self.report(say(SAY_CAPTURE_DELAYED,error=str(error).rstrip('.')),obs,'waiting')
        # Navigation is independent of checkpoint IO; launch remains gated by
        # a current archive. Options/save visits still refresh that archive.
        returning_to_mod=False
        if native_menu and stock_main and callable(getattr(self.mode_menu,'return_pending',None)):
            with PineClient(timeout=5) as p:returning_to_mod=self.mode_menu.return_pending(p)
        checkpoint=self.checkpoints() if native_menu and self.menu_checkpoint else None
        reuse_main=bool(returning_to_mod and checkpoint and 'main' in checkpoint.records and
                        checkpoint.card_reader()==checkpoint.card_revision)
        # A custom selector cancellation has a current clean main checkpoint.
        # Do not recapture/save it merely to reopen the same mod page. If game
        # saves changed, keep the loading cue while the new clean capture runs.
        # Publish the interactive pager first. The recovery snapshot may finish
        # while the user browses; only committing a mode needs its receipt.
        checkpoint_current=bool(checkpoint and checkpoint.handled_scene and scene and
            (checkpoint.handled_scene.kind,checkpoint.handled_scene.manager,checkpoint.handled_scene.object)==
            (scene.kind,scene.manager,scene.object) and checkpoint.card_reader()==checkpoint.card_revision)

        if self.mode_menu is not None and not getattr(self,'menu_pager_stopped',False):
            with PineClient(timeout=5) as p:
                try:
                    if native_menu:
                        checkpoint=self.checkpoints() if self.menu_checkpoint else None
                        capture_ready=(not self.menu_checkpoint or reuse_main or
                                       (checkpoint_current and 'main' in checkpoint.records))
                        selected=self.mode_menu.tick(p,allow_activate=stock_main,
                                                     checkpoint_ready=capture_ready)
                    else:selected=self.mode_menu.tick(p)
                    self.menu_pager_failures=0
                except ValueError as error:
                    selected=None;self.menu_pager_failed(p,error,obs)
            if selected is not None:
                self.battle_mode,self.humans=selected['mode'],selected['humans']
                self.assignment=selected.get('assignment')
                self.report(selection_line(selected),obs)
                hub=getattr(self,'controller_hub',None)
                if hub is not None:
                    import team_assignment
                    mode,keep=self.controller_settings()
                    try:hub.select(self.humans,selected.get('choice') is not None and selected.get('choice')+1 in team_assignment.CHOICES,
                                   mode=mode,keep=keep)
                    except RuntimeError as error:log(f'Controller check-in roster not updated: {error}')
                    self.assignment_failed=None   # a new selection tries the P1/P2 input again
        if native_menu and scene is not None and getattr(scene,'kind',None)=='main':
            if not reuse_main:
                with PineClient(timeout=5) as p:
                    checkpoint_scene=menu_return.read_scene(p,allow_owned_main=True)
                capture(checkpoint_scene)
            return
        capture()

    def menu_pager_failed(self, p, error, obs=None):
        """A Modded Modes pager fault is reported once; it never ends the watcher (W5).

        Only a rejected queued choice (PAGER_CHOICES) is cleared, and the pager is published
        again on the next main-menu visit. Any other fault is deterministic (changed pager
        code, a reservation another patch occupies, an invalid setting): resetting would only
        repeat it on every poll. The pager is then closed for this session (the game's own
        menus keep working) and the player is told to restart; so is a choice rejected again
        right after its reset."""
        import native_mode_menu
        failures=getattr(self,'menu_pager_failures',0)+1;self.menu_pager_failures=failures
        rejected=(str(error) in PAGER_CHOICES and failures==1 and callable(getattr(self.mode_menu,'reset',None)))
        if rejected:
            try:
                if getattr(self.mode_menu,'native',False) and p.read_u32(native_mode_menu.CONTROL)==native_mode_menu.MAGIC:
                    p.write_u32(native_mode_menu.CONTROL+12,0)   # the rejected choice
                self.mode_menu.reset(p)
            except (OSError,PineError,ValueError) as reset_error:
                log(f'Could not reset the Modded Modes menu: {reset_error}');rejected=False
        if rejected:
            log(f'Modded Modes menu reset: {error}')
            # Its own next step as HOW TO FIX (a plain recovered failure would only say 'You can keep playing').
            from player_errors import Detected, code_for
            self.fail('observe',Detected(code_for('observe','descriptive'),PAGER_RESET_WHAT,fix=PAGER_RESET_FIX,
                                         detail=PAGER_RESET),cover=False,recovered=True,
                      context=dict(where='Modded Modes menu',error=str(error)))
            return
        self.menu_pager_stopped=True
        self.mode_menu.custom_match=False
        close=getattr(self.mode_menu,'close',None)
        if callable(close):
            try:close()
            except Exception as close_error:log(f'Could not close the Modded Modes menu: {close_error}')  # noqa: BLE001
        log(say(SAY_PAGER_FAULT,error=str(error).rstrip('.')))
        from player_errors import Detected, code_for
        self.fail('observe',Detected(code_for('observe','descriptive'),PAGER_STOPPED_WHAT,fix=PAGER_STOPPED_FIX,
                                     detail=PAGER_STOPPED.format(play=native_preparation.launcher())),cover=False,
                  recovered=True,context=dict(where='Modded Modes menu',error=str(error)))

    PINE_RETRY = (0.5, 4.0)   # first and longest pause after a transient emulator connection error
    PINE_REPORT_AFTER = 4     # consecutive errors before the problem is reported as a failure

    def pine_hiccup(self, error, where):
        """A PINE or socket error outside observe() while PCSX2 still runs (W5).

        The watcher waits a growing pause and tries again on the next poll, so a busy or
        briefly unreachable emulator never ends it. Only a closed emulator does
        (EmulatorClosed, from the lifetime check). A long streak is reported once.
        `where` is a SAY_PINE_WAIT key ('menus' or 'match')."""
        from runtime_owner import EmulatorClosed
        if isinstance(error,EmulatorClosed):raise error
        if self.lifetime is not None:self.lifetime.require_alive()
        count=getattr(self,'pine_errors',0)+1;self.pine_errors=count
        first,longest=self.PINE_RETRY
        delay=min(longest,first*2**(count-1))
        self.report(say(SAY_PINE_WAIT[where],error=error,delay=f'{delay:.1f}'),level='waiting')
        if count==self.PINE_REPORT_AFTER:
            # The watcher is only waiting: worded as a slow PCSX2, not as 'the mod stopped following the match'.
            from player_errors import Detected, code_for
            slow=Detected(code_for('observe','lost'),PINE_SLOW_WHAT[where],PINE_SLOW_WHY,PINE_SLOW_FIX,
                          detail=f'{count} PINE errors in a row; the last one: {str(error) or type(error).__name__}')
            self.fail('observe',slow,cover=False,recovered=True,context=dict(where=where,attempts=count,error=repr(error)))
        time.sleep(delay)

    MENU_RETURN_WAIT = 15   # seconds the game has to name its post-match menu
    MENU_RETURN_BUSY = 30   # seconds another operation may hold the preparation lock
    MENU_RESTORE_TRIES = 4  # connection errors in one menu return before its restore counts as failed

    def return_to_menu(self, obs):
        """After a prepared match, load the clean checkpoint of the menu the game went to.

        The game's result and reason flags name it (menu_return.return_destination), or the
        menu scene itself does. Exits no captured menu matches (reason 0x800/0x1000, the Duel
        menu 0x26), seen on two polls in a row, go to the main menu, the safe top level. So
        does a destination still unknown after MENU_RETURN_WAIT seconds, and a character
        selection whose restore failed. Only a main menu that cannot be restored leaves the
        watcher FAILED, uncovered (menus draw no loading cover, and the game is unmuted) with
        the reason in the Play window. While the destination is unknown the match's workers
        stay parked: the loop can come back to the same match.
        """
        if not self.menu_checkpoint:
            self.reset_reload_worker()
            self.state = 'MENU'
            return
        checkpoints = self.checkpoints()
        # Native flags normally arrive during results. The observed native
        # destination also covers a fast menu choice between watcher polls.
        destination = checkpoints.destination
        if destination is None and obs.menu_scene is not None:
            destination = obs.menu_scene.kind
        if self.menu_return_started is None:
            self.menu_return_started = time.monotonic()
            self.menu_restore_errors = 0
            self.menu_return_boot, self.menu_return_restarted = 0, False
        fallback = None
        # A reset or a reboot after a crash (G7b) shows the boot scene with no result: the same wait and the same
        # clean main menu as before (live-proven on the European disc), but told as a restart, not a failed return.
        restarted = destination is None and self.game_restarted(obs) or getattr(self, 'menu_return_restarted', False)
        if destination is None:
            destination = fallback = self.fallback_destination(obs)
        timed_out = destination is None and time.monotonic()-self.menu_return_started > self.MENU_RETURN_WAIT
        self.log_menu_return(obs, destination, timed_out)
        if destination is None:
            self.reset_reload_worker(park=True)
            self.cover('Returning to your selected menu...', 50)
            if not timed_out:
                return
            destination, fallback = 'main', self.restart_notice() if restarted else ValueError(MAIN_AFTER_WAIT)
        elif restarted:
            destination, fallback = 'main', self.restart_notice()
        elif fallback is not None:
            fallback = ValueError(MAIN_INSTEAD)
        self.reset_reload_worker()
        self.restore_menu(destination, fallback, dict(seen=self.describe_return(obs), restarted=bool(restarted)))

    @staticmethod
    def restart_notice():
        from player_errors import Detected
        return Detected('TTM-MENU-20', RESTARTED_WHAT, RESTARTED_WHY, RESTARTED_FIX,
                        detail='After the match the game showed its boot scene (1) with no result or exit reason')

    def fallback_destination(self, obs):
        """'main' once two polls in a row show an exit no captured menu matches, else None."""
        scene = getattr(getattr(obs, 'menu_scene', None), 'scene', None)
        candidate = menu_return.fallback_destination(getattr(obs, 'result_flags', 0) or 0,
                                                     getattr(obs, 'return_flags', 0) or 0, scene)
        previous = self.menu_return_fallback
        polls = previous[1]+1 if previous is not None and previous[0] == candidate else 1
        self.menu_return_fallback = (candidate, polls) if candidate is not None else None
        return candidate if candidate is not None and polls >= 2 else None

    def game_restarted(self, obs):
        """True once two polls in a row showed the boot scene with no result latched (menu_return.restarted), for
        the rest of this return: the game restarted during the match (a PCSX2 reset, or the game rebooting
        itself). The European session of Sept 24 showed exactly this: scene 1, flags 0/0, until the wait ran out."""
        scene = getattr(getattr(obs, 'menu_scene', None), 'scene', None)
        seen = menu_return.restarted(getattr(obs, 'result_flags', 0) or 0, getattr(obs, 'return_flags', 0) or 0, scene)
        self.menu_return_boot = getattr(self, 'menu_return_boot', 0)+1 if seen else 0
        if self.menu_return_boot >= 2:
            self.menu_return_restarted = True
        return bool(getattr(self, 'menu_return_restarted', False))

    def failed_at_menus(self):
        """A FAILED watcher whose game reached its menus (G7a). Menus draw no in-game cover, so the failure cover
        comes down (on Windows that also unmutes the game) and the explanation is repeated once in the Play
        window: the block shown during the match may have scrolled away."""
        if getattr(self, 'failure_repeated', False):
            return
        self.failure_repeated = True
        self.uncover()
        try:
            import player_errors
            lines = player_errors.record_lines(getattr(self, 'last_error', None))
        except ImportError:
            player_errors, lines = None, []
        if not lines:
            return
        self.report(say(SAY_FAILED_AT_MENUS), level='error')
        for line in lines:
            player_errors.emit(line, 'error')

    @staticmethod
    def describe_return(obs):
        scene = getattr(obs, 'menu_scene', None)
        word = lambda value: f'0x{value:X}' if isinstance(value, int) and value >= 0 else str(value)
        return (f'scene {word(getattr(scene, "scene", None))}, scene manager {word(getattr(scene, "manager", None))}, '
                f'result flags {word(getattr(obs, "result_flags", None))}, reason flags {word(getattr(obs, "return_flags", None))}')

    def log_menu_return(self, obs, destination, timed_out=False):
        """What the game showed while returning, logged whenever it changes (W6). The line
        after the wait is logged once too, not on every poll a busy lock keeps it waiting."""
        seen = (self.describe_return(obs), destination, bool(timed_out))
        if seen == self.menu_return_seen:
            return
        self.menu_return_seen = seen
        state = 'not identified after the wait' if timed_out else destination or 'not identified yet'
        log(f'Menu return: {seen[0]}; destination {str(state).replace("_", " ")}.')

    def restore_menu(self, destination, fallback=None, facts=None):
        from runtime_owner import EmulatorClosed
        facts = dict(facts or {}, destination=destination)
        checkpoints = self.checkpoints()
        self.cover('Returning to character selection...' if destination == 'character_select'
                   else 'Returning to the main menu...', 50)
        try:
            checkpoints.restore(destination)
        except EmulatorClosed:
            raise
        except PreparationBusyError:
            # A short overlap with another owned operation is not a corrupt
            # archive. Keep the requested destination and cover until its lease
            # is released; never load underneath the existing owner.
            if time.monotonic()-self.menu_return_started < self.MENU_RETURN_BUSY:
                self.cover('Finishing the previous operation before returning...',50)
                self.report(say(SAY_RETURN_WAITS),level='waiting')
                return
            self.menu_return_failed(RuntimeError(MENU_LOCK_BUSY), destination)
            return
        except (PineError, ConnectionError, TimeoutError) as error:
            # A dropped or slow emulator connection (a socket timeout too): the restore is tried
            # again on the next polls, uncovered in between (menus draw no cover, and the game
            # must not stay muted). A closed emulator ends the watcher. After MENU_RESTORE_TRIES
            # it is a failed restore like any other.
            if self.lifetime is not None: self.lifetime.require_alive()
            tries = getattr(self, 'menu_restore_errors', 0)+1
            self.menu_restore_errors = tries
            if tries < self.MENU_RESTORE_TRIES:
                self.uncover()
                delay = min(self.PINE_RETRY[1], self.PINE_RETRY[0]*2**(tries-1))
                self.report(say(SAY_PINE_WAIT[destination], error=error, delay=f'{delay:.1f}'), level='waiting')
                time.sleep(delay)
                return
            self.restore_failed(destination, error, facts)
            return
        except (OSError, ValueError, RuntimeError) as error:
            self.restore_failed(destination, error, facts)
            return
        if self.mode_menu is not None:
            # The archived guest cover/lease belongs to an earlier visit.
            # Reopen only when returning to the actual main menu.
            import mode_menu
            try:
                with PineClient(timeout=5) as p:
                    if getattr(self.mode_menu,'native',False):
                        if destination=='main' and getattr(self.mode_menu,'custom_match',False):
                            page={'teams':1,'ffa':2,'coop':1,'training':4,'training_coop':4}[self.battle_mode]
                            self.mode_menu.reset(p,return_page=page)
                        else:self.mode_menu.reset(p)
                    else:
                        self.mode_menu.screen.hide(client=p)
                        p.write_u32(mode_menu.CONTROL+4, 0)
                        p.write_u32(mode_menu.CONTROL+12, 0)
                        p.write_u32(mode_menu.CONTROL+20, 0)
            except (OSError, PineError) as error:
                # The clean menu is loaded; the pager is published again on its next visit.
                log(f'Modded Modes will reopen on the next main-menu visit: {error}')
            self.mode_menu.active = False
            self.mode_menu.dismissed = False
            self.mode_menu.last_choice = None
        self.state = 'MENU'
        self.menu_return_started = None
        self.menu_return_fallback = self.menu_return_seen = None
        self.menu_return_boot, self.menu_return_restarted = 0, False
        self.uncover()
        if fallback is not None:
            # Uncovered first: the notice is in the Play window (menus draw no guest cover).
            self.fail('menu_return', fallback, cover=False, recovered=True, context=facts)
        self.report(say(SAY_RETURNED.get(destination, SAY_RETURNED['main'])))

    def restore_failed(self, destination, error, facts):
        """A menu checkpoint could not be loaded: character selection falls back to the clean
        main menu; a main menu that cannot be loaded leaves the watcher FAILED."""
        if destination != 'main':
            log(say(SAY_MAIN_INSTEAD, error=str(error).rstrip('.')))
            self.restore_menu('main', ValueError(MAIN_AFTER_FAILURE), dict(facts, error=str(error)))
            return
        self.menu_return_failed(error, destination)

    def menu_return_failed(self, error, destination):
        """No clean menu could be loaded. The game sits in its own menus with this match's
        changes: stop preparing, unmute and uncover (the cover is not drawn in menus), and
        say why in the Play window."""
        self.state = 'FAILED'
        self.failure_repeated = True   # already said at the menus: failed_at_menus() does not repeat it
        self.uncover()
        self.fail('menu_return', error, cover=False, context=dict(destination=destination))
        self.report(say(SAY_RETURN_FAILED.get(destination, SAY_RETURN_FAILED['main']),
                        error=str(error).rstrip('.')), level='error')

    def set_loading_teams(self, characters):
        if self.presentation is None or not hasattr(self.presentation, 'set_teams'): return
        self.presentation.set_teams([dict(side=i, fighters=[dict(character_id=c,player=(self.assignment.index(2*slot+i)+1 if 2*slot+i in self.assignment else 0)) if self.assignment is not None else dict(character_id=c) for slot,c in enumerate(team)])
                                     for i,team in enumerate(characters)])

    def early_loading(self, obs):
        """Cover native arena/intro loading, then defer dialogue to prepared start."""
        if not self.preparation_enabled:return
        teams = obs.selected_early_teams(include_single=battle_mode_policy.prepare_singleton(self.battle_mode,self.humans) or story_missions.pending_for(self.battle_mode))
        if teams is None or obs.battle_state not in (-1, 0, 1): return
        self.set_loading_teams(teams)
        if self.presentation is not None and hasattr(self.presentation, 'set_mode'):
            self.presentation.set_mode(self.battle_mode, self.humans)
        # 12BD10 starts native disc loading before BATTLE_OBJECT exists. Paint
        # ahead while its minigame is visible, but publish only when phase 0
        # initializes the arena (or phase 1 if the polling interval missed 0).
        self.prerender_cover()
        if obs.battle_state == -1: return
        self.play_intro_after_loading = True
        self.cover('Loading your selected fighters...', 0)
        if obs.battle_state != 1: return
        # The boot hook's gate (native_preparation; sync_preparation arms it from the menus on, in this same
        # poll at the latest) defers phase 1 at the frame boundary, deterministically. beta.35/36 also wrote
        # substate 4 from here: a host-timed write that could land inside 217410's read-call-reread increment
        # and leave 5, which phase 1 never leaves (the 0 % cover until Start, about one start in a hundred).
        if obs.streaming:
            self.watch_phase1(obs)
            return
        self.legacy_intro_deferral(obs)

    PHASE1_STALL_SECONDS = 10.0
    PHASE1_STALL_GAP = 2.0      # a longer gap between phase-1 polls (PCSX2 paused, PINE busy) starts the count again

    def watch_phase1(self, obs, clock=None):
        """Read-only phase-1 stall diagnostic (beta.37, streaming only). With the boot hook the gate defers the
        native intro in the frame it starts, so phase 1 lasts one frame before preparation. If it stays for
        PHASE1_STALL_SECONDS of running polls on one battle object, log its state once to watcher.log and keep it
        as status.json 'phase1_stall': phase, substate, phase table and the gate's CONTROL+16/+44/+48/+52/+56. The
        beta.36 0 % cover was never recorded this way; a repeat is attributed directly. No write, no player text."""
        now = (clock or time.monotonic)()
        obj = obs.battle_object
        since = self.phase1_since
        if (obs.status != 'running' or since is None or since[0] != obj or
                now - since[2] > self.PHASE1_STALL_GAP):
            self.phase1_since = (obj, now, now) if obs.status == 'running' else None
            return
        self.phase1_since = (obj, since[1], now)
        if now - since[1] < self.PHASE1_STALL_SECONDS or (self.phase1_stall or {}).get('battle_object') == obj:
            return
        control = native_preparation.CONTROL
        with PineClient(timeout=5) as p:
            phase, substate, table = p.read_u32(obj), p.read_u32(obj+8), p.read_u32(obj+260)
            words = {f'control_{offset}': p.read_u32(control+offset) for offset in (16, 44, 48, 52, 56)}
        self.phase1_stall = dict(seconds=round(now-since[1], 1), battle_object=obj, phase=phase, substate=substate,
                                 table=table, **words)
        log(f'Phase-1 stall: battle object {obj:08X} in phase 1 for {now-since[1]:.1f} s: phase {phase}, '
            f'substate {substate}, table {table:08X} (duel {A(0x2C6070):08X}); gate control +16 {words["control_16"]} '
            f'+44 {words["control_44"]} +48 {words["control_48"]} +52 {words["control_52"]} '
            f'+56 {words["control_56"]}')

    PHASE1_REPAIRS = 3

    def legacy_intro_deferral(self, obs):
        """No boot hook (a developer run without the cheat file): the host defers the intro itself. Phase1's
        documented substate4 returns phase2 through the normal exit, so actor initialization still runs on its
        original path; voice and camera setup are repeated natively only after preparation ends. That first
        write can race 217410 and leave 5..98; native code never stores there, so a later poll writes 4 again
        (at most PHASE1_REPAIRS times per battle object)."""
        with PineClient(timeout=5) as p:
            obj = p.read_u32(BATTLE_OBJECT)
            if obj != obs.battle_object or p.read_u32(obj) != 1 or p.read_u32(obj+260) != A(0x2C6070):
                return
            substate = p.read_u32(obj+8)
            if self.deferred_intro_object != obj:
                if substate not in range(4): return
                p.write_u32(obj+8, 4)
                self.deferred_intro_object, self.intro_repairs = obj, 0
                return
            if not 5 <= substate < 99 or self.intro_repairs >= self.PHASE1_REPAIRS: return
            p.write_u32(obj+8, 4)
        self.intro_repairs += 1
        log(say(SAY_INTRO_CONTINUED))

    def prerender_cover(self):
        # Native loading leaves the host idle for ~20 s; paint the preparation's pictures
        # then instead of between its holds. A miss still renders when shown.
        prerender = getattr(self.presentation, 'prerender', None)
        if prerender is None: return
        try: prerender(tuple(self.stage_message(message) for message in PREPARATION_MESSAGES))
        except (OSError, RuntimeError) as error:
            log(f'Loading pictures will render when shown: {error}')

    def cover(self, message='Getting your fighters ready...', progress=None, error=None):
        """The loading cover; error=(line 1, line 2) draws the failure state (player_errors.cover_text)."""
        if self.presentation is None: return
        try:
            if progress is not None: self.progress = progress
            if hasattr(self.presentation, 'set_mode'):
                self.presentation.set_mode(self.battle_mode, self.humans)
            title = {'teams': 'Preparing team battle', 'ffa': 'Preparing free-for-all',
                     'coop': 'Preparing co-op battle','training':'Preparing modded training',
                     'training_coop':'Preparing co-op training'}[self.battle_mode]
            if error:
                try:
                    from player_errors import cover_title  # what stopped: setup, a rematch, a fusion ...
                except ImportError:
                    from localization import tr
                    cover_title = lambda _: tr('Match setup stopped')
                self.presentation.show(cover_title(error), message, self.progress, error=tuple(error))
            else:
                self.presentation.show(title, message, self.progress)
            if not self.cover_started:
                self.cover_started = True
                if not self.presentation.wait_visible():
                    log('Loading screen is waiting for the game window; preparation status is also in this window.')
        except (OSError, RuntimeError) as error:
            log(f'Loading screen unavailable: {error}. Preparation status remains in this window.')

    def uncover(self, refresh_surface=False):
        if self.presentation is not None:
            try:
                self.presentation.hide(refresh_surface=refresh_surface)
                if not self.presentation.wait_hidden(timeout=2):
                    # An unresponsive cover must not keep hiding a match after
                    # Session releases its final hold in the Ready callback.
                    self.presentation.close()
            except OSError as error:
                log(f'Could not update loading screen: {error}')
                self.presentation.close()
        self.cover_started = False

    def fresh_text(self, obs, pause=False):
        """(template, values) of the Play window's new-match line: a free-for-all counts its fighters (its native
        rows are two halves of one field), a team battle names its sides ('5v5')."""
        if self.battle_mode == 'ffa':
            return (SAY_FRESH_FFA_PAUSE if pause else SAY_FRESH_FFA), dict(count=obs.rows[0]+obs.rows[1])
        return (SAY_FRESH_PAUSE if pause else SAY_FRESH_MATCH), dict(teams=f'{obs.rows[0]}v{obs.rows[1]}')

    def stage_message(self, stage):
        """A preparation stage as the cover shows it. fresh_team_trainer's first stage names a team battle, so the
        other modes show 'Preparing your match' (the same in-game Spanish, PREPARANDO COMBATE)."""
        stage = str(stage)
        if stage == 'Preparing team battle' and getattr(self, 'battle_mode', 'teams') != 'teams':
            return 'Preparing your match'
        return stage

    def on_progress(self, stage, completed, total):
        self.progress_message = self.stage_message(stage)   # shown again when PCSX2 resumes from a pause
        if stage == 'Ready':
            # Loading is over: the intro that follows is the match, never a paused-loading cover.
            self.preparation_paused = False
            # Session releases the final all-fighter hold only after returning
            # from this callback. The frame revealed here already has its bars.
            self.cover('Starting your match...',100)
            guest=getattr(self.presentation,'guest',None)
            if guest:guest.wait_drawn(timeout=2)
            self.uncover()
            return
        progress = round(100*completed/total) if total else 0
        self.cover(self.stage_message(stage), progress)

    def fail(self, operation, error, *, stage=None, context=None, cover=True, recovered=False):
        """Report one failure through player_errors (group A); plain fallback when it is absent."""
        try:
            import player_errors
        except ImportError:
            player_errors = None
        if player_errors is not None:
            return player_errors.fail(self, operation, error, stage=stage, context=context,
                                      cover=cover, recovered=recovered)
        detail = str(error) or type(error).__name__
        if cover:
            self.cover('SETUP STOPPED - CLOSE PCSX2, THEN START PLAY AGAIN', 100)
        self.report(f'{operation} failed: {detail}', level='warning' if recovered else 'error')
        return None

    def report(self, message, obs=None, level='info'):
        with self.report_lock:
            self._report(message, obs, level)

    def _report(self, message, obs=None, level='info'):
        marker = (self.state, level, message)
        changed = marker != self.last_report
        if changed: log(f'{level.upper()}: {message}')
        now = time.monotonic()
        if self.status_file and (changed or now-self.last_status_time >= 5):
            value = dict(updated=time.strftime('%Y-%m-%d %H:%M:%S'), pid=os.getpid(),
                         state=self.state, level=level, message=message,
                         battle_mode=self.battle_mode, humans=self.humans,
                         observation=obs.summary() if obs else None)
            value['launcher_token'] = self.launcher_token
            # Sticky: the launcher reads the last failure after PCSX2 closes (exit 3 unless recovered).
            if getattr(self, 'last_error', None): value['last_error'] = self.last_error
            if getattr(self, 'phase1_stall', None): value['phase1_stall'] = self.phase1_stall
            if self.lifetime is not None:
                value['emulator_pid'] = self.lifetime.process.pid
                value['emulator_created'] = self.lifetime.created
            try:
                atomic_json(self.status_file, value)
                self.last_status_time = now
                self.status_error = False
            except OSError as error:
                if not self.status_error: log(f'Status file update delayed: {error}')
                self.status_error = True
        self.last_report = marker

    def track_match_boundary(self, obs):
        # The native allocator can reuse exactly the same manager/array and
        # roster for another match. A prior failure must not suppress it forever.
        if self.last_loop == 1 and obs.loop == 0:
            self.handled.clear(); self.noted.clear()
            self.heartbeat = None; self.freeze_dumped = False; self.hold_overruns = None
            self.hold_snapshot = False; self.trail_faults_logged = False
            self.phase1_since = self.phase1_stall = None
            self.freeze_reported = False; self.frozen_count = self.freeze_record = None
        self.last_loop = obs.loop

    def observe(self):
        try:
            with PineClient(timeout=5) as p:
                info = p.info()
                if info['status'] == 'shutdown':
                    # A closing PCSX2 stops its game about 0.5 s before its process ends (live 2.8.2): once this
                    # session's game ran, wait for that end (EmulatorClosed ends the watcher normally) instead of
                    # saying the game is starting. A game shut down in a PCSX2 that stays open waits once.
                    if getattr(self, 'game_seen', False) and self.lifetime is not None:
                        self.game_seen = False
                        import player_errors
                        if player_errors._closing(self): self.lifetime.require_alive()
                    self.connection_error = say(SAY_BOOTING); return None
                if info.get('serial', '').upper() != SERIAL or info.get('crc', '').upper() != game_profile.pcsx2_crc():
                    self.connection_error = say(SAY_OTHER_GAME, expected=SERIAL, serial=info.get('serial') or '?',
                                                crc=info.get('crc') or '?')
                    return None
                try:
                    runtime_profile.require_version(info['version'])
                except ValueError as error:   # this PCSX2 answers, but with a version the installation does not accept
                    self.connection_error = say(SAY_UNUSABLE, error=str(error).rstrip('.')); return None
                self.game_seen = True
                return Observation(p, status=info['status'])
        except (OSError, PineError, ValueError) as error:
            self.connection_error = say(SAY_NO_CONNECTION, error=error)
            return None

    def save_slot(self, slot):
        path = STATES/f'{PREFIX}{slot:02}.p2s'
        before = path.stat().st_mtime_ns if path.exists() else None
        with PineClient(timeout=5) as p: p.save_state(slot)
        deadline = time.monotonic()+40
        while time.monotonic() < deadline:
            time.sleep(0.3)
            if path.exists() and path.stat().st_mtime_ns != before and path.stat().st_size > 0x100000:
                time.sleep(0.5); return path
        return None

    def load_file(self, source, expect_ack=None):
        import prepared_rematch
        import saved_game_state
        # Later rematches reuse this watcher's decoded playable and, for identical
        # blocks, its verified staged archive (prepared_rematch.ArchiveCache).
        cache=getattr(self,'rematch_cache',None)
        if cache is None:cache=self.rematch_cache=prepared_rematch.ArchiveCache()
        source_ram=cache.read(source)
        source_ack=bytes(source_ram[ACK_ADDRESS:ACK_ADDRESS+16])
        if len(source_ack)!=16 or (expect_ack is not None and source_ack!=expect_ack):
            raise ValueError('Prepared checkpoint acknowledgement changed')
        # A headless/no-loading-screen watcher has no presentation owner to
        # dismiss an archived cover after the restore.
        capture=prepared_rematch.plan(source_ram,show_loading=self.presentation is not None)
        self.reset_reload_worker()
        lease=None
        try:
            # Borrow the trainer's verified slot lease, as menu restoration
            # does. Fixed218/219 may contain foreign saves and are never used.
            lease=Session()
            staged=lease.run/'rematch-staged.p2s'
            with PineClient(timeout=5) as p:
                prior_ack=p.read(ACK_ADDRESS,16)
                # A rematch rewinds the match, not saved options/progress.
                # Read before staging, and include the data in the immutable
                # archive rather than overwriting a live save writer.
                payload=saved_game_state.preserve(p,source_ram)
                blocks=(capture['blocks'] if capture is not None else [])+payload['blocks']
                if blocks:
                    if cache.stage(source,dict(serial=SERIAL,crc=CRC,blocks=blocks),staged):
                        log('Reused the verified rematch archive.')
                else:shutil.copyfile(source,staged)
                slot,target=lease.check_slot(1)
                shutil.copyfile(staged,target)
                lease.record_slot(1,staged)
                # The slot receipt now names this archive: the previous rematch's is spare.
                self.drop_previous_rematch(lease)
                if p.read(ACK_ADDRESS,16)!=prior_ack:
                    raise RuntimeError('The current checkpoint changed before reload')
                sentinel=os.urandom(16)
                while sentinel==source_ack:sentinel=os.urandom(16)
                # The immutable source token may already be in live RAM during a
                # rematch. Only restoration from this load can replace our sentinel.
                p.write(ACK_ADDRESS,sentinel)
                if p.read(ACK_ADDRESS,16)!=sentinel:
                    raise RuntimeError('Checkpoint reload sentinel was not accepted')
                p.load_state(slot)
                # The loaded state brings its own loading buffers: nothing this
                # process wrote there can be trusted for a header-only republish.
                import guest_loading_screen;guest_loading_screen.invalidate_buffers()
            deadline = time.monotonic()+40
            while time.monotonic() < deadline:
                time.sleep(0.3)
                try:
                    with PineClient(timeout=5) as p:
                        ack = p.read(ACK_ADDRESS, 16)
                        if ack == source_ack:
                            if capture is None:return True
                            try:return prepared_rematch.complete(p,capture)
                            except (OSError,PineError,ValueError,RuntimeError,TimeoutError) as error:
                                log(f'Prepared rematch remains covered: {error}')
                                return False
                except (OSError, PineError):
                    pass
            return False
        finally:
            # Retain the immutable staged archive so a later Session can prove
            # this slot is ours before reusing it. Close releases the lock and
            # frees the slot this lease claimed but did not record.
            if lease is not None:lease.close()

    REMATCH_FILES = {'rematch-staged.p2s', 'session.json'}

    def drop_previous_rematch(self, lease):
        """Delete this watcher's previous rematch folder once a newer archive holds the slot (F6).

        Each rematch stages a ~15 MB archive in a new prepared-states folder. Only the newest
        is referenced (by the slot receipt and the rematch cache). The previous folder goes
        when it holds nothing but a staged archive and its session file, and no slot claim
        names it; otherwise it is kept for player_storage's pruning at the next launch."""
        previous,self.rematch_run=getattr(self,'rematch_run',None),Path(lease.run)
        if previous is None or previous==self.rematch_run:return
        try:
            folder=previous.resolve()
            if folder.parent!=Path(lease.run).resolve().parent or not folder.is_dir():return
            if any(p.is_dir() or p.name not in self.REMATCH_FILES for p in folder.iterdir()):return
            from fresh_team_trainer import STATES
            for claim in STATES.glob('*.trainer-claim.json'):
                try:archive=json.loads(claim.read_text()).get('archive')
                except (OSError,ValueError):return   # uncertain ownership: keep it
                if archive and Path(archive).resolve().parent==folder:return
            for p in folder.iterdir():p.unlink()
            folder.rmdir()
        except (OSError,TypeError,ValueError) as error:
            log(f'Kept the previous rematch archive: {error}')

    def release_input(self, owner, what):
        """Close one input owner. A thread that does not stop is dropped, never joined again,
        and never ends the watcher (F8)."""
        if owner is None:return
        try:owner.close()
        except Exception as error:
            owner.service=owner.capture=None
            log(f'Could not release {what}: {error}')
            if not getattr(self,'input_release_reported',False):
                self.input_release_reported=True
                self.fail('controllers',RuntimeError(INPUT_STUCK),cover=False,recovered=True,
                          context=dict(input=what,error=str(error)))

    def reset_reload_worker(self, *, keep_menu_input=False, keep_battle_input=False, park=False):
        """Release the input owners (as the flags say) and the match's fighter-update workers.

        park=True keeps the workers, their capture and epoch: the match only left combat for
        a moment (a phase or loop read in between). service_extra_reloads reuses them for the
        same capture with no rewind, because a second attach of a service that already ran is
        refused. Everything else (a rematch, a known menu return, a new capture, teardown)
        drops them."""
        menu_input=getattr(self,'menu_input',None)
        if menu_input is not None and not keep_menu_input:self.release_input(menu_input,'three/four-player input');self.menu_input_failed=None
        if not keep_battle_input:
            self.release_input(self.controller_input,'three/four-player input')
            self.battle_input_failed=None   # the next match tries players 3 and 4 again
        assigned=getattr(self,'assigned_input',None)
        if assigned is not None and not (keep_menu_input or keep_battle_input):self.release_input(assigned,'the assigned controllers')
        if park:
            # Parked workers do not drive poll_delay: no 10-50 ms polling in results or menus.
            self.workers_parked = self.reload_worker is not None
            return
        self.reload_worker = self.reload_capture = self.reload_epoch = None
        self.body_worker = None
        self.fusion_worker = None
        self.fighter_updates_off = None
        self.workers_parked = False

    def parked_workers_installed(self, p):
        """Match F1: parked workers are reused only while each service they attached to is
        still installed for this match (Worker.installed: reads only, no claim)."""
        for worker in (self.reload_worker, self.body_worker, self.fusion_worker):
            check = getattr(worker, 'installed', None)
            if worker is not None and callable(check) and not check(p):
                return False
        return True

    def service_extra_reloads(self, obs):
        """The watcher owns one serial reload worker for this prepared match."""
        if obs.status!='running':
            return
        if obs.battle_state!=3:
            # Results still consume controller input (including Fight Again).
            # Closing an assigned mailbox leaves its armed guest hook emitting
            # neutral input once the lease expires, so nobody can confirm a
            # result-menu choice. Fighter reloads stop here; input lives until
            # the actual teardown/restore, which resets both owners normally.
            # The workers are parked: a moment out of combat is not a new match.
            self.reset_reload_worker(keep_battle_input=(obs.loop==1 and obs.team_mode==1
                                     and obs.battle_state in (1,2,4,5,6)),park=True)
            return
        import extra_reload_worker
        import extra_reload_requests
        import fighter_updates
        import trainer_bridge
        import team_start_gate
        from preset_runtime import epoch
        operation_started = False
        capture = None
        try:
            with PineClient(timeout=10) as p:
                if p.status()!='running': return
                battle = p.read_u32(BATTLE_OBJECT)
                phase=p.read_u32(battle) if 0x100000<=battle<0x8000000-0x200 else -1
                if phase!=3:
                    # The phase can advance between Observation and this read.
                    self.reset_reload_worker(keep_battle_input=(phase in (1,2,4,5,6)
                                             and p.read_u32(MODE)==1),park=True)
                    return
                manager = p.read_u32(MANAGER)
                mode,count,captured,configured = struct.unpack('<4I',p.read(MODE,16))
                enabled,owner,request_count = struct.unpack('<3I',p.read(extra_reload_requests.CONTROL,12))
                started = struct.unpack('<6I',p.read(team_start_gate.CONTROL,24))
                if (mode!=1 or count not in ACTOR_COUNTS or enabled!=1 or
                        (captured,configured,owner,request_count)!=(manager,count,manager,count) or
                        started[0]!=0 or started[2:4]!=(manager,count) or started[5]!=1):
                    # Legacy, preparing, or withdrawn checkpoint, or one glitched read: parked
                    # like a phase miss. Reuse needs the same capture and no rewind; a new
                    # capture, a rematch or a menu return drops them.
                    self.reset_reload_worker(park=True)
                    return
                capture = (manager,count,p.read(ACK_ADDRESS,16))
                counters = epoch(p)
                rewound = self.reload_epoch is not None and any(
                    new<old for new,old in zip(counters,self.reload_epoch))
                operation_started = True
                hub=getattr(self,'controller_hub',None)
                if hub is not None and getattr(self,'hub_match',None)!=capture:
                    self.hub_match=capture
                    try:hub.new_match()
                    except RuntimeError:pass
                online=online_active(p)
                if hub is not None:hub.online=online
                assigned=getattr(self,'assigned_input',None)
                if assigned is not None:
                    if not online and self.preparation_enabled and self.wants_assignment(True):
                        if rewound:assigned.close()
                        self.attach_assigned_input(assigned,p,('battle',capture),obs,in_match=True)
                    else:assigned.disable(p)
                if self.controller_input is not None and not online:
                    self.attach_battle_input(p,capture,rewound,obs)
                if getattr(self,'fighter_updates_off',None)==capture and not rewound:
                    self.reload_epoch=counters
                    return   # switched off for this match after a refused attach
                if (getattr(self,'workers_parked',False) and self.reload_worker is not None and
                        capture==self.reload_capture and not rewound and not self.parked_workers_installed(p)):
                    # Something re-initialised the services in place while the workers were
                    # parked: never adopt that blindly. A new attach decides (a refusal turns
                    # fighter updates off for this match).
                    log(say(SAY_SERVICES_CHANGED))
                    self.reload_worker=self.body_worker=self.fusion_worker=None
                self.workers_parked=False
                if self.reload_worker is None or capture!=self.reload_capture or rewound:
                    try:
                        worker=extra_reload_worker.Worker(progress=log,cell_auxiliary=True)
                        worker.attach(p)
                        self.reload_worker=worker
                        self.body_worker=fighter_updates.attach_body(p,progress=log)
                        self.fusion_worker=fighter_updates.attach_fusion(p,progress=log)
                    except ValueError as refusal:
                        self.fighter_updates_refused(p,capture,counters,refusal)
                        return
                    self.reload_capture=capture
                    self.fighter_updates_off=None
                fighter_updates.poll(p,self.reload_worker,self.body_worker,self.fusion_worker)
                trainer_bridge.service(p,extra=self.reload_worker,body=self.body_worker,fusion=self.fusion_worker)
                if self.reload_worker.failure:
                    raise RuntimeError(self.reload_worker.failure)
                if not self.reload_worker.active:
                    self.reset_reload_worker()
                else:
                    # poll can complete several transactions. Retain the final
                    # counters, so a manual load cannot reuse their ownership.
                    self.reload_epoch=epoch(p)
        except (OSError,PineError) as error:
            # A closing emulator (or a stopped game) is not a fighter-update failure (W8).
            if operation_started and not self.emulator_stopping(): self.fail_extra_reload(error,capture)
            # Retry read-only connection/preflight failures before any guest
            # operation; an uncertain transaction remains terminal.
        except Exception as error:
            from runtime_owner import EmulatorClosed
            if isinstance(error,EmulatorClosed):raise
            self.fail_extra_reload(error,capture)

    def fighter_updates_refused(self, p, capture, counters, refusal):
        """An attach was refused, before any guest write (match F1): the match goes on.

        A second attach of a service that already ran is refused (a savestate loaded mid-match,
        or workers dropped and rebuilt). That used to hold combat for good. Now the guest
        services that would wait for a host are switched off and the match continues without
        fighter updates; one that is mid-transaction still makes this a failure, as before."""
        import fighter_updates
        self.reload_worker=self.body_worker=self.fusion_worker=None
        busy=fighter_updates.switch_off(p)
        if busy:
            raise RuntimeError(f'{str(refusal).rstrip(".")}; a {" and ".join(busy).replace("_"," ")} update was in progress')
        if p.read_u32(native_preparation.CONTROL+16):
            # Combat is still held (a hold this refusal did not take, such as a failed guest
            # service): "the match goes on" would be false, so this is a failure after all.
            raise RuntimeError(f'{str(refusal).rstrip(".")}; combat is still held')
        self.reload_capture,self.reload_epoch,self.fighter_updates_off=capture,counters,capture
        log(f'Fighter updates are off for this match: {refusal}')
        self.fail('fighter_update',ValueError(UPDATES_OFF),cover=False,recovered=True,
                  context=dict(job='reload',refusal=str(refusal)))

    def emulator_stopping(self):
        """After a PINE error in a match: is PCSX2 closing or its game stopped (W8)?

        A closed emulator raises EmulatorClosed, which ends the watcher normally. A refused
        reconnect or a VM that is no longer running means it is shutting down: that is not a
        fighter-update failure, so no FAILED state and no failure receipt."""
        if self.lifetime is not None:self.lifetime.require_alive()
        try:
            with PineClient(timeout=2) as p:return p.status() not in ('running','paused')
        except ConnectionRefusedError:return True
        except (OSError,PineError):return False

    def freeze_folder(self):
        return self.status_file.parent if self.status_file else ROOT/'analysis'/'autopilot'

    def capture_freeze(self, p, session=None):
        """Savestate first (it holds the CPU registers and kernel memory the
        diagnosis needs); a compressed EE image if no savestate completes.

        The slot comes from the trainer's verified lease, as menu restoration
        and rematches use: only an empty slot or one proven to be ours. During a
        preparation (`session`, whose lock this watcher cannot take) its own
        unused second slot is borrowed; that session's close() frees it.
        """
        stamp = time.strftime('%Y%m%d-%H%M%S'); folder = self.freeze_folder()
        lease = None
        try:
            if session is not None:
                slot, path = session.check_slot(1)
            else:
                lease = Session()
                slot, path = lease.check_slot(0)
            before = path.stat().st_mtime_ns if path.exists() else None
            p.save_state(slot)
            deadline = time.monotonic()+60
            from pine import require_runtime
            while time.monotonic() < deadline:
                time.sleep(0.5)
                require_runtime()   # a closed emulator ends the wait (and frees the slot) at once
                if path.exists() and path.stat().st_mtime_ns != before and path.stat().st_size > 0x100000:
                    time.sleep(1.0)
                    target = folder/f'freeze-{stamp}.p2s'
                    shutil.copyfile(path, target)
                    # Not recorded: the copy is the diagnosis, and a receipt naming a file
                    # outside prepared-states could not be reused while this watcher runs.
                    # close() frees the slot now (W1).
                    return target
            log('Freeze savestate did not complete in time.')
        except (OSError, PineError, ValueError) as error:
            log(f'Freeze savestate failed: {error}')
        finally:
            if lease is not None: lease.close()
        import zstandard
        target = folder/f'freeze-{stamp}.bin.zst'
        target.write_bytes(zstandard.ZstdCompressor(level=3).compress(native_preparation.read_ram(p)))
        return target

    def save_freeze(self, p, count, stall, session=None, starting=False):
        """One diagnostic snapshot of a hung game (freeze dumps on) and its facts beside it."""
        self.report(say(SAY_SAVING_START_SNAPSHOT if starting else SAY_SAVING_SNAPSHOT), level='warning')
        target = self.capture_freeze(p, session)
        signature = hang_signature(savestate_pc(target)) if target.suffix == '.p2s' else None
        if signature is not None:
            log(f'Frozen EE program counter {signature["pc"]}' +
                (f' ({signature["label"]})' if signature['label'] else ''))
        atomic_json(target.with_name(target.name.split('.')[0]+'.json'),
                    dict(capture=str(target), packets=count, frozen_seconds=round(stall, 1), starting=starting,
                         playable=str(self.playable), battle_mode=self.battle_mode, humans=self.humans,assignment=self.assignment,
                         hang_signature=signature))
        log(say(SAY_SNAPSHOT_SAVED, path=target))
        return target

    @staticmethod
    def render_counting(p):
        """The render observer is installed and counting (capacity_stage): only then is its heartbeat a picture."""
        return (p.read_u32(capacity_stage.CONTROL) == capacity_stage.MAGIC and
                p.read_u32(capacity_stage.CONTROL+48) == 1)

    def watch_holds(self, client):
        """Report a shared cinematic pause that outlived its bound and was released.

        The render watchdog below cannot see this: a presentation that holds every
        fighter keeps drawing frames at full rate, so the heartbeat never stops. The
        guest releases the hold itself; this tells the player why the match stood
        still (a handled problem, TTM-MATCH-21, with a report file), and leaves the
        counters for a later diagnosis.
        """
        import cinematic_policy
        self.watch_trails(client)
        if client.read_u32(cinematic_policy.CONTROL) != cinematic_policy.MAGIC:
            self.hold_overruns = None
            return
        overruns = client.read_u32(cinematic_policy.CONTROL+cinematic_policy.HOLD_OVERRUNS)
        # Evidence without freeze dumps: who a long shared hold is holding, once per hold.
        age = client.read_u32(cinematic_policy.CONTROL+cinematic_policy.HOLD_AGE)
        if age >= hold_snapshot_updates() and not self.hold_snapshot:
            self.log_hold_snapshot(client, f'shared hold reached {age} updates')
        self.hold_snapshot = age >= hold_snapshot_updates()
        if self.hold_overruns is None:
            self.hold_overruns = overruns
            return
        if overruns <= self.hold_overruns:
            return
        self.hold_overruns = overruns
        self.log_hold_snapshot(client, f'shared hold overrun {overruns}')
        longest = client.read_u32(cinematic_policy.CONTROL+cinematic_policy.HOLD_LONGEST)
        # beta.37 participant protection telemetry (zero on older installs, which never write these words).
        protected = client.read_u32(cinematic_policy.CONTROL+120)
        refused = client.read_u32(cinematic_policy.CONTROL+124)
        from player_errors import Detected
        released = Detected('TTM-MATCH-21', HOLD_RELEASED_WHAT, HOLD_RELEASED_WHY, HOLD_RELEASED_FIX,
                            detail=f'a shared cinematic hold was released after {longest} updates '
                                   f'({overruns} overrun(s) in this match)')
        self.fail('observe', released, cover=False, recovered=True,
                  context=dict(longest_hold_updates=longest, hold_overruns=overruns,
                               protect_updates=protected, latch_refused=refused))

    @staticmethod
    def log_hold_snapshot(client, reason):
        """One watcher.log line: every fighter's action, stop timer, pair and presentation flags, the
        cinematic CONTROL words +52..+124 and the running camera's track/bindings/state. Read-only."""
        import cinematic_policy as cp
        import fresh_team_combat as core
        from native_map import GP, GPO
        try:
            words = struct.unpack('<19I', client.read(cp.CONTROL+52, 76))
            count = min(client.read_u32(cp.CONTROL+8), battle_mode_policy.ENGINE_ACTORS)
            fighters = []
            for i in range(count):
                actor = client.read_u32(core.POINTERS+4*i)
                if not 0x100000 <= actor < 0x08000000-0x1600 or actor & 3:
                    fighters.append(f'{i}:-'); continue
                action, stop = client.read_u32(actor+2376), client.read_u32(actor+4896)
                pair = (client.read_u32(actor+3732), client.read_u32(actor+3736))
                d3 = any(client.read(actor+b, 1)[0] & cp.PRIORITY_FLAG_BIT for b in cp.PRIORITY_FLAG_BYTES)
                ult = any(client.read(actor+b, 1)[0] & cp.ULTIMATE_FLAG_MASK for b in cp.ULTIMATE_FLAG_BYTES)
                fighters.append(f'{i}:a{action}/s{stop}/p{pair[0]},{pair[1]}/{"D3" if d3 else ""}{"U" if ult else ""}')
            camera = client.read_u32(GP+GPO(-22180))
            fields = ([client.read_u32(camera+o) for o in (704, 768, 772, 776, 812)]
                      if 0x100000 <= camera < 0x08000000-832 and not camera & 3 else [])
        except (OSError, PineError, ValueError, IndexError, struct.error) as error:
            log(f'Shared hold snapshot ({reason}) could not be read: {error}')
            return
        log(f'Shared hold snapshot ({reason}): control+52..124 {" ".join(f"{w:X}" for w in words)}; '
            f'camera {camera:08X} +704/768/772/776/812 {" ".join(f"{w:X}" for w in fields)}; '
            f'fighters {" ".join(fighters)}')

    def watch_trails(self, client):
        """One watcher.log line per match when the widened trail lists had to forget a corrupt list
        (aux_trail_lists faults) or were installed bound-only. Read-only; never a player-facing error."""
        import aux_trail_lists as trails
        if self.trail_faults_logged or client.read_u32(trails.CONTROL) != trails.MAGIC:
            return
        faults = client.read_u32(trails.CONTROL+16+4*trails.FAULTS)
        if not faults:
            return
        self.trail_faults_logged = True
        try:
            counters = struct.unpack(f'<{len(trails.COUNTERS)}I', client.read(trails.CONTROL+16, 4*len(trails.COUNTERS)))
            mode, last = client.read_u32(trails.CONTROL+trails.MODE), client.read_u32(trails.CONTROL+trails.LAST_FAULT)
        except (OSError, PineError, ValueError, struct.error) as error:
            log(f'Trail lists: {faults} fault(s); counters unreadable: {error}'); return
        log(f'Trail lists: {faults} fault(s) this match (mode {mode}, last fault owner {last}); '
            + ', '.join(f'{name} {value}' for name, value in zip(trails.COUNTERS, counters)))

    def render_stall(self, p, count, clock):
        """Seconds the picture has stood still while PCSX2 runs, once that reaches FREEZE_SECONDS and was not
        reported yet; else None. A picture that moves again after a reported freeze ends it (freeze_resumed).

        Stillness counts only between reads at most WATCH_GAP apart. The first longer gap in a stall is left
        out (Windows asleep: the watcher could not look, so it proves nothing), while the stillness watched
        before and after it still counts. Any later gap in the same stall counts in full, so a hang whose
        reads keep coming slowly (PINE timing out under it) is still reported."""
        now = clock()
        previous, self.heartbeat_read = getattr(self, 'heartbeat_read', None), now
        if self.heartbeat is None or self.heartbeat[0] != count:
            self.heartbeat, self.heartbeat_gap = (count, now), False
            frozen = getattr(self, 'frozen_count', None)
            if frozen is not None and count != frozen:
                self.freeze_resumed()
            return None
        if previous is None:
            self.heartbeat, self.heartbeat_gap = (count, now), False
            return None
        if now-previous > WATCH_GAP and not getattr(self, 'heartbeat_gap', False):
            # Not watched in between: this gap is left out of the stillness (its start moves by the gap), once.
            self.heartbeat, self.heartbeat_gap = (count, self.heartbeat[1]+(now-previous)), True
            return None
        if getattr(self, 'freeze_reported', False) or now-self.heartbeat[1] < FREEZE_SECONDS or p.status() != 'running':
            return None
        self.freeze_reported = True
        return now-self.heartbeat[1]

    def freeze_resumed(self):
        """The picture moved again after a reported freeze: the match goes on, so that failure is a handled one
        now (the session no longer ends with exit 3 for it). Any other failure keeps its own outcome."""
        record = getattr(self, 'freeze_record', None)
        self.frozen_count = self.freeze_record = None
        self.freeze_reported = False
        if isinstance(record, dict) and getattr(self, 'last_error', None) is record:
            record['recovered'] = True
        self.report(say(SAY_FROZEN_RESUMED), level='warning')

    def report_freeze(self, count, stall, target):
        """A hung match (TTM-MATCH-20), not recovered: a report file with the heartbeat and the stall, and a
        sticky last_error, so Play ends with exit 3 and keeps its block on screen after PCSX2 closes."""
        from player_errors import Detected
        dumps = bool(self.diagnostic_settings.get('capture_freeze_dumps'))
        fix = FROZEN_FIX_SAVED if target is not None else FROZEN_FIX_NOT_SAVED if dumps else FROZEN_FIX
        detail = f'no new picture for {stall:.1f} s while PCSX2 was running (render heartbeat {count})'
        if target is not None:
            detail += f'; diagnostic snapshot {target}'
        self.fail('observe', Detected('TTM-MATCH-20', FROZEN_WHAT, FROZEN_WHY, fix, detail=detail), cover=False,
                  context=dict(heartbeat=count, stalled_seconds=round(stall, 1), freeze_dumps=dumps,
                               snapshot=str(target) if target is not None else None))
        self.frozen_count = count
        self.freeze_record = getattr(self, 'last_error', None)

    def watch_freeze(self, obs, clock=time.monotonic):
        """Report a prepared match that stops rendering, and capture it once when freeze dumps are on.

        Read-only toward the guest: the game is already hung. The capture is
        what a later diagnosis needs (registers, saved thread contexts, the
        model table and every guard's telemetry), since the emulator log only
        shows the symptom. With dumps off (the player default) the explanation
        says how to turn them on for the next time.
        """
        if obs.status != 'running' or obs.battle_state != 3:
            self.heartbeat = None
            return
        stall = target = None
        try:
            with PineClient(timeout=10) as p:
                # Only a match whose render observer is installed and counting.
                if not self.render_counting(p):
                    self.heartbeat = None
                    return
                self.watch_holds(p)
                count = p.read_u32(FRAME_HEARTBEAT)
                if self.diagnostic_settings['record_battle_diagnostics']:
                    self.battle_diagnostics.tick(p,self.freeze_folder()/'battle-diagnostics.json',clock)
                stall = self.render_stall(p, count, clock)
                if stall is None:
                    return
                if self.diagnostic_settings['capture_freeze_dumps'] and not self.freeze_dumped:
                    self.freeze_dumped = True
                    target = self.save_freeze(p, count, stall)
        except (OSError, PineError) as error:
            log(f'Freeze watchdog could not capture the game: {error}')
            if stall is None:
                return
        self.report_freeze(count, stall, target)

    def watch_start_freeze(self, clock=time.monotonic):
        """The prepared intro after Ready, still PREPARING (LS-2): the same render watch as a match.

        The trainer reports a frozen start itself (release_start's START_FROZE, after 10 s of running
        time). With freeze dumps on, this takes the diagnostic snapshot first, after FREEZE_SECONDS,
        through the preparation's own unused savestate slot; the preparation's failure report names it.
        """
        if (self.progress_message != 'Ready' or self.freeze_dumped or
                not getattr(self, 'diagnostic_settings', {}).get('capture_freeze_dumps')):
            return
        try:
            with PineClient(timeout=10) as p:
                if p.status() != 'running' or not self.render_counting(p):
                    self.heartbeat = None
                    return
                count = p.read_u32(FRAME_HEARTBEAT)
                now = clock()
                if self.heartbeat is None or self.heartbeat[0] != count:
                    self.heartbeat = (count, now)
                    return
                if now-self.heartbeat[1] < FREEZE_SECONDS:
                    return
                self.freeze_dumped = True
                lock = getattr(self, 'preparation_lock', None) or threading.Lock()
                with lock:   # the preparation cannot close its session (and free the slot) under the capture
                    self.start_freeze_capture = self.save_freeze(p, count, now-self.heartbeat[1],
                                                                 session=getattr(self, 'preparation_session', None),
                                                                 starting=True)
        except (OSError, PineError, ValueError) as error:
            log(f'Freeze watchdog could not capture the game: {error}')

    def hold_failed_reload(self,capture):
        """Hold only the exact failed world through its verified native service."""
        if capture is None:return False
        manager,count,marker=capture
        try:
            with PineClient(timeout=5) as p:
                if (p.status()!='running' or not native_preparation.installed(p) or
                        p.read_u32(native_preparation.CONTROL)!=native_preparation.MAGIC or
                        p.read_u32(MANAGER)!=manager or p.read(ACK_ADDRESS,16)!=marker or
                        struct.unpack('<4I',p.read(MODE,16))!=(1,count,manager,count)):
                    return False
                if (p.read_u32(native_preparation.CONTROL+16) and
                        p.read_u32(native_preparation.CONTROL+24)!=manager):return False
                native_preparation.quiet(p,timeout=2)
                return (p.read_u32(native_preparation.CONTROL+20)==1 and
                        p.read_u32(native_preparation.CONTROL+24)==manager)
        except Exception as hold_error:
            log(f'Could not confirm failed-match combat hold: {hold_error}')
            return False

    def failed_job(self):
        """Which fighter update failed, for the explanation (player_errors context 'job')."""
        if getattr(self.fusion_worker,'failure',None):return 'fusion'
        if getattr(self.body_worker,'failure',None):return 'body_change'
        if getattr(self.reload_worker,'failure',None) or getattr(self.reload_worker,'form_job',None) is not None:
            return 'transformation'
        return 'reload'

    def fail_extra_reload(self,error,capture=None):
        held=self.hold_failed_reload(capture)
        self.state='FAILED'
        self.fail('fighter_update',error,context=dict(job=self.failed_job(),hold_confirmed=held))
        detail=(str(error) or type(error).__name__).rstrip('.')
        self.report(say(SAY_UPDATE_STOPPED,error=detail,hold=say(SAY_HELD if held else SAY_HOLD_UNCONFIRMED)),level='error')
        if self.status_file:
            try:
                atomic_json(self.status_file.with_name('reload-failure.json'),
                            dict(error=str(error),playable=str(self.playable),hold_confirmed=held))
            except OSError as receipt_error:
                log(f'Could not save fighter-update failure details: {receipt_error}')

    def prepare(self):
        import player_errors
        self.result = {}
        session = None
        try:
            import mod_settings
            self.diagnostic_settings=mod_settings.load_settings()
            session_type=StreamingSession if self.streaming else Session
            session = session_type(self.mode, progress=self.on_progress,
                              play_intro=self.play_intro_after_loading,
                              battle_mode=self.battle_mode, humans=self.humans,assignment=self.assignment)
            self.preparation_session = session   # watch_start_freeze borrows its unused slot
            try:
                try:session.prepare()
                finally:
                    # The trainer loads its prepared checkpoint through the same PINE slot lease.
                    import guest_loading_screen;guest_loading_screen.invalidate_buffers()
                self.result = dict(ok=True, playable=session.source)
            except Exception as error:  # noqa: BLE001 - every failure keeps its message, step and traceback
                traceback.print_exc()  # errors.log
                stage = getattr(session, 'stage', None)
                failure = dict(error=player_errors.short(error), type=type(error).__name__, stage=stage,
                               traceback=traceback.format_exc(), source=str(session.source),
                               transport='native-frame' if self.streaming else 'state-load', status='failed')
                from fresh_team_trainer import write_json
                # The run folder may be pruned by later launches; this launch's log folder keeps a copy.
                for target in (session.run/'failure.json', self.status_file.with_name('failure.json') if self.status_file else None):
                    if target is None: continue
                    try: write_json(target, failure)
                    except OSError as write_error: log(f'Could not save the failure details to {target}: {write_error}')
                originals = list(session.run.glob('*original-selected-match.p2s'))
                player_errors.release_frames(error)  # kept until PCSX2 closes: not the trainer's RAM copies
                self.result = dict(ok=False, error=failure['error'], original=originals[0] if originals else None,
                                   exception=error, stage=stage)
            finally:
                # Never under an intro snapshot that uses this session's slot (watch_start_freeze).
                with getattr(self, 'preparation_lock', None) or threading.Lock():
                    self.preparation_session = None
                    session.close()
        except Exception as error:  # noqa: BLE001 - report anything to the console
            traceback.print_exc()
            player_errors.release_frames(error)
            self.result = dict(ok=False, error=player_errors.short(error), original=None, exception=error,
                               stage=getattr(session, 'stage', None))

    def handle_preparation_resume(self, obs):
        if obs is None:
            return
        if obs.status == 'running':
            self.resume_needed = False
            self.report(say(SAY_GAME_RUNNING), obs)
        elif obs.status == 'paused' and obs.hold == 1:
            if not self.resume_attempted and not self.manual_pause:
                send_space(self.owned_pid())
                self.resume_attempted = True
                self.report(say(SAY_HOLD_RESUMING), obs, 'waiting')
            else:
                self.resume_attempted = True
                self.cover('Press Space in the game to continue loading.')
                self.report(say(SAY_HOLD_PAUSED), obs, 'waiting')

    def owned_pid(self):
        """The emulator this launcher started, for send_space (None without a lifetime)."""
        lifetime=getattr(self,'lifetime',None)
        return getattr(lifetime,'pid',None) or getattr(getattr(lifetime,'process',None),'pid',None)

    PAUSED_LOADING = 'Paused: resume PCSX2 to continue loading'

    def watch_streaming_pause(self):
        """A native-frame preparation waits while PCSX2 is paused (F2); say so, and why.

        At most one status request a second. The in-game cover can change only once guest
        frames run again (the desktop cover shows it at once); the Play window says it now.
        Once the Ready stage ran, loading is over: the intro that follows (release_start) is
        the match itself, so a pause there is the player's own and never covers it."""
        if self.progress_message=='Ready':
            self.preparation_paused=False
            return
        now=time.monotonic()
        if now<getattr(self,'pause_probe_at',0.0):return
        self.pause_probe_at=now+1.0
        try:
            with PineClient(timeout=2) as p:status=p.status()
        except (OSError,PineError):return
        if self.progress_message=='Ready':return   # Ready ran during the status read
        if status=='paused' and not self.preparation_paused:
            self.preparation_paused=True
            self.cover(self.PAUSED_LOADING)
            self.report(say(SAY_LOADING_PAUSED),level='waiting')
        elif status=='running' and self.preparation_paused:
            self.preparation_paused=False
            self.cover(self.progress_message)
            self.report(say(SAY_LOADING_RESUMED))

    def menu_button(self):
        """The controller button that opens Modded Modes (Mod settings: menu_toggle_button)."""
        try:
            import input_binding
            settings=getattr(self.mode_menu,'settings',None) or {}
            return input_binding.LABELS.get(settings.get('menu_toggle_button','select'),'Select')
        except Exception:  # noqa: BLE001 - a label only
            return 'Select'

    def run(self):
        self.report(say(SAY_RUNNING, button=say(self.menu_button())))
        while True:
            import fighter_updates
            # Parked workers wait for combat, and a FAILED watcher polls no worker: the ordinary
            # poll then, never 10-50 ms (match F1).
            time.sleep(self.poll if getattr(self,'workers_parked',False) or self.state=='FAILED' else
                       fighter_updates.poll_delay(self.reload_worker,self.body_worker,self.fusion_worker,self.poll))
            if self.lifetime is not None:
                self.lifetime.require_alive()
            if self.presentation is not None: self.presentation.tick()
            if self.worker is not None:
                if self.worker.is_alive():
                    if self.resume_needed:
                        # The leaders are held idle once the memory stage is loaded; resume then.
                        self.handle_preparation_resume(self.observe())
                    elif getattr(self,'streaming',False):
                        self.watch_streaming_pause()
                        self.watch_start_freeze()   # after Ready only: a frozen intro is captured (LS-2)
                    continue
                self.worker = None
                self.heartbeat, self.freeze_dumped = None, False   # the match's own watch starts afresh
                if self.result.get('ok'):
                    self.playable = self.result['playable']
                    ack_error = None
                    for attempt in range(5):
                        # A transient PINE error while reading the start acknowledgement must not end the watcher.
                        try:
                            with PineClient(timeout=5) as p: self.ack_token = p.read(ACK_ADDRESS, 16)
                            ack_error = None; break
                        except (OSError, PineError) as error:
                            ack_error = error
                            if self.lifetime is not None: self.lifetime.require_alive()
                            time.sleep(.5)
                    if ack_error is None:
                        self.state = 'ACTIVE'
                        self.uncover()
                        self.report(say(SAY_MATCH_READY))
                        log(f'Rematch checkpoint: {self.playable}')   # watcher.log only (play_launcher.DENY_LINE)
                    else:
                        self.state='FAILED'
                        self.fail('preparation', ack_error, stage='Reading the start acknowledgement')
                else:
                    # A boot/menu archive is not a recovery transaction. In
                    # particular, another controller's lock failure must never
                    # load a state underneath the actual preparation owner:
                    # no checkpoint is loaded after a failed setup.
                    self.state='FAILED'
                    error = self.result.get('exception') or RuntimeError(self.result.get('error') or 'Preparation failed')
                    context = dict(original=str(self.result.get('original') or ''))
                    if getattr(self,'start_freeze_capture',None) is not None:
                        context['freeze_snapshot'] = str(self.start_freeze_capture)   # the frozen intro (LS-2)
                    self.fail('preparation', error, stage=self.result.get('stage'), context=context)
                    self.handled.add(self.current_key)
                self.start_freeze_capture = None
                continue
            obs = self.observe()
            if obs is None:
                # The launcher owns our lifetime. BIOS/loading delays must not
                # quietly terminate the watcher before the user chooses teams.
                self.report(self.connection_error, level='waiting')
                continue
            if self.state=='FAILED':
                # A failed transaction/restore is not permission to expose the
                # partial world when the native loop next visits its menu. Its
                # cover is not drawn there, though: take it down, say why once.
                if obs.loop == 0:
                    self.failed_at_menus()
                continue
            hub=getattr(self,'controller_hub',None)
            if hub is not None and obs.status=='running':
                hub.start()   # the first tick with the game running starts the one SDL owner thread (idempotent)
                self.drain_controller_messages(obs)
            if not getattr(self,'input_checked',True) and obs.status=='running':
                # Tell Linux players at startup, not first in character select, when P3/P4 cannot work.
                self.check_controller_input()
            if self.state == 'ACTIVE' and self.menu_checkpoint:
                self.checkpoints().observe_result(obs.result_flags, obs.return_flags)
            self.track_match_boundary(obs)
            if obs.status == 'paused' and obs.loop == 0 and self.state == 'MENU' and not self.menu_saved:
                if self.manual_pause or self.menu_resume_sent:
                    # A menu pause is usually the player's own: resumed automatically once per session.
                    self.report(say(SAY_MENU_PAUSED), obs, 'waiting')
                else:
                    self.menu_resume_sent=True
                    log(say(SAY_MENU_RESUMING)); send_space(self.owned_pid()); time.sleep(1.0)
                continue
            if obs.loop == 0:
                # The selector owns its service across menu polls. Closing it
                # here would repeatedly recreate SDL devices while P3/P4 pick.
                # service_menu closes it when leaving character selection.
                # The match's workers are parked; return_to_menu drops them once a menu is known.
                self.reset_reload_worker(keep_menu_input=True, park=True)
                self.play_intro_after_loading = False
                self.deferred_intro_object = None
                if self.state == 'ACTIVE':
                    self.return_to_menu(obs)
                    continue
                if self.state != 'MENU': self.state = 'MENU'
                if self.cover_started: self.uncover()
                self.report(say_text(obs.pending_reason), obs, 'waiting')
                try:
                    self.service_menu(obs)
                    # Consume Original/Modded selection before changing the guest
                    # gate, including cancellation or return from a custom match.
                    self.sync_preparation(obs)
                    self.pine_errors = 0
                except (OSError, PineError) as error:
                    self.pine_hiccup(error, 'menus')   # W5: a busy emulator never ends the watcher
                continue
            # Native shutdown clears the team marker before LOOP_FLAG. A
            # pause-menu exit can therefore resemble a rematch for one poll.
            # Honor the latched destination and wait for native teardown first.
            if self.state == 'ACTIVE' and (
                    menu_return.return_destination(obs.result_flags, obs.return_flags) is not None or
                    menu_return.fallback_destination(obs.result_flags, obs.return_flags) is not None or
                    (self.menu_checkpoint and self.checkpoints().destination is not None)):
                continue
            if self.state == 'ACTIVE' and self.menu_return_started is not None:
                # The loop came back to the match before any menu was named (F3): no return.
                # The parked workers are reused; the return cover must not hide the match.
                self.menu_return_started = self.menu_return_fallback = self.menu_return_seen = None
                log(say(SAY_RETURN_CANCELLED))
                self.uncover()
            # battle loop active
            if self.state == 'ACTIVE':
                if obs.team_mode == 0:
                    log(say(SAY_REMATCH_LOADING))
                    self.cover('Getting everyone ready for the rematch...', 90)
                    restore_error=None
                    try:restored=bool(self.playable and self.load_file(self.playable,self.ack_token))
                    except (OSError,PineError,ValueError,RuntimeError,TimeoutError) as error:
                        from runtime_owner import EmulatorClosed
                        if isinstance(error,EmulatorClosed):raise   # closing PCSX2 is not a rematch failure
                        restored=False;restore_error=error
                    if restored:
                        self.heartbeat=None
                        log(say(SAY_REMATCH_READY));self.uncover()
                    elif isinstance(restore_error,(OSError,PineError)) and self.emulator_stopping():
                        # PCSX2 was closed (or its game shut down) during the load: not a failed rematch, as for
                        # fighter updates (W8). A closed PCSX2 raises EmulatorClosed here or on the next poll (live,
                        # Sept 28: closing it during Fight Again gave TTM-MATCH-02 and exit 3). One line says so, and
                        # the rematch cover comes down: a PCSX2 that stays open with its game shut down gets its
                        # window back (a game started again later is watched from its menus as usual).
                        log(say(SAY_REMATCH_INTERRUPTED)); self.uncover()
                        continue
                    else:
                        self.state='FAILED'
                        # One explained block (no second English line); the game keeps its failure cover.
                        self.fail('rematch',restore_error or RuntimeError(REMATCH_UNCONFIRMED))
                else:
                    self.service_extra_reloads(obs)
                    self.watch_freeze(obs)
                continue
            if self.state in ('MENU', 'BATTLE', 'PAUSE_REQUIRED'):
                try:
                    self.sync_preparation(obs)
                    if self.preparation_enabled:self.early_loading(obs)
                    self.pine_errors = 0
                except (OSError, PineError) as error:
                    self.pine_hiccup(error, 'match'); continue
                if not self.preparation_enabled:
                    self.state='BATTLE'
                    self.report(say(SAY_ORIGINAL_MENU),obs)
                    continue
                if not obs.fresh_battle:
                    self.report(say_text(obs.pending_reason), obs, 'waiting'); continue
                if not obs.clean:
                    # A prepared checkpoint loaded by hand, or leftovers after a native
                    # rematch: transient, so do not remember it as handled.
                    if obs.key not in self.noted:
                        self.noted.add(obs.key)
                        self.report(say(SAY_CARRIES_CHANGES), obs, 'warning')
                    self.state = 'BATTLE'; continue
                if obs.key in self.handled: continue
                if max(obs.rows) <= 1 and not (battle_mode_policy.prepare_singleton(self.battle_mode,self.humans) or story_missions.pending_for(self.battle_mode)):
                    if self.cover_started: self.uncover()
                    self.handled.add(obs.key); self.state = 'BATTLE'
                    self.report(say(SAY_ONE_ON_ONE), obs); continue
                if not supported_teams(obs.rows, include_single=battle_mode_policy.prepare_singleton(self.battle_mode,self.humans) or story_missions.pending_for(self.battle_mode)):
                    if self.cover_started: self.uncover()
                    self.handled.add(obs.key)
                    self.state = 'BATTLE'
                    self.report(say(SAY_TOO_MANY, teams=f'{obs.rows[0]}v{obs.rows[1]}', capacity=TEAM_CAPACITY), obs, 'warning'); continue
                self.set_loading_teams(obs.characters)
                self.streaming=obs.streaming
                self.play_intro_after_loading=self.play_intro_after_loading or obs.streaming or obs.native_intro
                if obs.streaming and not obs.native_held:
                    self.report(say(SAY_WAITING_HOLD),obs,'waiting');continue
                if obs.status == 'running' and not obs.streaming:
                    if self.manual_pause or self.state == 'PAUSE_REQUIRED':
                        self.state = 'PAUSE_REQUIRED'
                        template, values = self.fresh_text(obs, pause=True)
                        self.report(say(template, **values), obs, 'waiting')
                        continue
                    # Freeze the moment of capture so no hit lands before the input hold exists.
                    self.cover(progress=0)
                    send_space(self.owned_pid())
                    paused = False
                    for _ in range(15):
                        time.sleep(0.2); check = self.observe()
                        if check is not None and check.status == 'paused': paused = True; break
                    if not paused:
                        self.state = 'PAUSE_REQUIRED'
                        self.cover('Press Space in the game to begin loading.')
                        self.report(say(SAY_PAUSE_UNCONFIRMED), obs, 'warning')
                        continue
                self.state = 'PREPARING'
                self.menu_return_started = None
                self.progress_message, self.preparation_paused = PREPARATION_MESSAGES[0], False
                if self.menu_checkpoint:
                    self.checkpoints().begin_battle()
                self.cover(progress=0)
                template, values = self.fresh_text(obs)
                self.report(say(template, **values), obs)
                self.resume_needed = not obs.streaming
                self.resume_attempted = False
                self.current_key = obs.key; self.state = 'PREPARING'
                self.worker = threading.Thread(target=self.prepare, daemon=True); self.worker.start()


def start_audio_repair(lifetime, folder):
    """Windows: every Play launch unmutes this installation's PCSX2 once its audio appears (Windows
    keeps a mute that an earlier session's loading screen left when PCSX2 closed under it). An
    independent process (loading_audio.py --repair) that ends with PCSX2; never stops the watcher."""
    try:
        from loading_audio import start_repair
        start_repair(runtime_profile.EXECUTABLE, lifetime.pid, lifetime.created, folder)
    except Exception as error:  # noqa: BLE001 - a diagnostic only; the helper also unmutes at its start
        try:
            with (Path(folder)/'audio-repair.log').open('a', encoding='utf-8') as output:
                output.write(f'{time.strftime("%H:%M:%S")} The audio check could not start: {error!r}\n')
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('Original', 'Player', 'Cpu', 'TwoPlayer'), default='Original')
    parser.add_argument('--no-menu-checkpoint', action='store_true', help='Do not capture the clean menu checkpoint at boot')
    parser.add_argument('--manual-pause', action='store_true', help='Never send UI input; wait for manual pause/resume')
    parser.add_argument('--no-loading-screen', action='store_true', help='Diagnostic console-only preparation')
    parser.add_argument('--status-file', type=Path, default=ROOT/'analysis/autopilot/status.json')
    parser.add_argument('--check', action='store_true', help='Check Python/dependencies without accessing the emulator')
    parser.add_argument('--emulator-pid', type=int, help='Exact emulator process started by this launcher')
    parser.add_argument('--launcher-token', help='Private launch receipt; supports Windows virtual-environment redirectors')
    parser.add_argument('--inspect-state', type=Path, help='Explain detection using an offline RAM/save-state file only')
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        # Spanish explanations and player paths must never crash a console with another code page.
        try: stream.reconfigure(errors='backslashreplace')
        except (AttributeError, ValueError, OSError): pass
    if args.check:
        # One classified line per failure; the launchers stop probing on 3 (settings) and 4 (game files).
        step = 'python'
        try:
            if sys.version_info < (3, 11): raise RuntimeError('Python 3.11+ is required by the trainer')
            import elftools, zstandard, capstone, numpy  # noqa:F401 - fail before opening a game
            from PIL import Image  # noqa:F401 - native loading portraits
            import importlib.util
            import mod_settings
            if WINDOWS:
                from loading_audio import WHEEL
                if not WHEEL.is_file() or any(importlib.util.find_spec(x) is None for x in ('comtypes', 'psutil')):
                    raise RuntimeError('The loading audio helper requires local pycaw, comtypes and psutil')
            else:
                # The loading-audio helper (pycaw/comtypes) is Windows-only; the emulator lifetime needs psutil.
                if importlib.util.find_spec('psutil') is None:
                    raise RuntimeError('The watcher requires psutil')
                from input_binding import sdl_status
                print(f'Three/four-player input: {sdl_status()}', flush=True)
            step = 'game files'
            native_guards()
            step = 'mod settings'
            mod_settings.load_settings()
        except Exception as error:  # noqa: BLE001 - the launcher shows this line, not a traceback
            import player_errors
            print(f'CHECK FAILED ({step}): {type(error).__name__}: {player_errors.short(error)}', flush=True)
            return {'python': 2, 'game files': 4, 'mod settings': 3}[step]
        print(f'Autopilot dependencies ready: {sys.executable}', flush=True)
        return 0
    if args.inspect_state:
        from camera_snapshot import read_ram
        ram = read_ram(args.inspect_state)
        class OfflineReader:
            def status(self): return 'paused'
            def read(self, address, size): return ram[address:address+size]
            def read_u32(self, address): return struct.unpack_from('<I', ram, address)[0]
        obs = Observation(OfflineReader())
        print(json.dumps(dict(observation=obs.summary(), fresh_battle=obs.fresh_battle,
            clean=obs.clean, reason=obs.pending_reason,
            supported=obs.fresh_battle and supported_teams(obs.rows)), indent=2))
        return 0
    from loading_presentation import LoadingPresentation
    from runtime_owner import claim, EmulatorLifetime, EmulatorClosed
    from pine import set_runtime_guard
    ownership = presentation = watcher = lifetime = None
    try:
        if args.emulator_pid is None:
            from localization import entry
            raise ValueError(f'Start {entry("play") or "Play"} so the watcher has an owned emulator PID.')
        ownership = claim()
        lifetime = EmulatorLifetime(args.emulator_pid)
        set_runtime_guard(lifetime.require_alive, lifetime.pid)
        presentation = None if args.no_loading_screen else LoadingPresentation(
            args.status_file.with_name('presentation.json'), native=True)
        # Only Windows can send PCSX2 its pause key; elsewhere the player presses it when asked.
        watcher = Autopilot(args.mode, menu_checkpoint=not args.no_menu_checkpoint,
                            status_file=args.status_file, manual_pause=args.manual_pause or not WINDOWS,
                            presentation=presentation, lifetime=lifetime, in_game_menu=True, launcher_token=args.launcher_token)
        if WINDOWS: start_audio_repair(lifetime, args.status_file.parent)
        watcher.run()
    except EmulatorClosed as error:
        if watcher is not None:
            watcher.state = 'CLOSED'
            watcher.report(say_text(str(error)))
        else:
            log(say_text(str(error)))
        return 0
    except KeyboardInterrupt:
        log('Automatic preparation was stopped.')
        return 0
    except Exception as error:
        import player_errors
        if watcher is not None:
            watcher.state = 'FAILED'
            # The helper ends here and its cover closes with it: the explanation goes to the console.
            watcher.fail('observe', error, cover=False)
        else:
            explanation = player_errors.explain(error, 'launch')
            log(f'ERROR: {explanation.what} ({explanation.code}: {explanation.detail})')
            for line in player_errors.console_lines(explanation)[1:-1]: log(f'ERROR: {line}')
        errors = args.status_file.with_name('errors.log')
        log(f'ERROR: The full error is in {errors}')
        traceback.print_exc()
        return 1
    finally:
        try:
            # Revoke before cleanup: a surviving daemon/cover must not connect
            # to a newly opened emulator after this controller is stopped.
            if lifetime is not None: lifetime.revoke()
            if watcher is not None:watcher.reset_reload_worker()
            if watcher is not None and getattr(watcher,'controller_hub',None) is not None:
                watcher.controller_hub.close()   # SDL quits on the hub thread; the shared process handle closes
            if watcher is not None and watcher.mode_menu is not None:
                watcher.mode_menu.close()
            if watcher is not None and watcher.worker is not None:
                # The revoked lifetime ends the worker's next PINE call or file wait; give it
                # time to run Session.close(), which frees its savestate slots (W1). The
                # launcher's own grace is 5 s; a slot left behind is reclaimed later anyway.
                watcher.worker.join(timeout=3.5)
            if presentation is not None:
                try: presentation.close()
                except EmulatorClosed: pass
        finally:
            if ownership is not None: ownership.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
