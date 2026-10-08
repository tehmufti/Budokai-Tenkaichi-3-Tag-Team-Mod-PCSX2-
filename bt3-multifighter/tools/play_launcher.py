"""Start the modded game (Play.sh) or open Mod Settings (Mod settings.sh), mainly on Linux.

`play` is launch-autopilot.ps1 + launcher-lifecycle.ps1 in Python and `settings` is launch-settings.ps1:
the same checks, startup steps, logs, ownership handshake and clean-up order. Windows players keep the
PowerShell launchers; this module also runs on Windows for tests. It imports only the standard library
plus runtime_profile, pcsx2_versions and atomic_files, so it can explain a broken environment before
the watcher's packages are checked. Adapter differences come from the files present
(tools/bt4_preflight.py), like the PowerShell launchers.

Linux specifics: PCSX2 is the official AppImage started with -portable (its data folder is then
runtime28/PCSX2), PINE is a Unix socket whose path is handed to the watcher, and every long-lived child
gets its own session, so closing the terminal after startup leaves the game running (SIGHUP detaches).
"""
import argparse
import contextlib
import csv
import ctypes
import hashlib
import json
import locale
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import atomic_files
import pcsx2_versions
import runtime_profile

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == 'nt'
# This adapter's PINE slot: PCSX2.ini must name it (the BT4 port rewrites the number).
PINE_SLOT = 28011
# PINE_DEFAULT_SLOT (PINE.h): the only slot without a '.<slot>' socket suffix. Hexadecimal, so the port never rewrites it.
PCSX2_DEFAULT_SLOT = 0x6D6B
SOCKET_ENV = 'TAGTEAM_PINE_SOCKET'  # read by pine.socket_path in the watcher
SUN_PATH_BYTES = 107  # PCSX2 Strlcpy()s the socket name into sockaddr_un.sun_path[108]
PROFILES = ('runtime128', 'runtime28')
MODES = ('Original', 'Player', 'Cpu', 'TwoPlayer')
# The developer tree's disc when no game-profile.json names one (player installations always have one).
BT3_ISO = 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
BT4_ISO = 'SLUS_219.78.DBZBT4B14REV2ENG.iso'
# The AppImage runtime must mount itself (no extract-and-run: that makes the launched PID a mere parent) and
# must not run another file named by TARGET_APPIMAGE. It sets APPIMAGE/APPDIR/ARGV0/OWD itself.
APPIMAGE_VARIABLES = ('APPIMAGE_EXTRACT_AND_RUN', 'TARGET_APPIMAGE', 'APPIMAGE', 'APPDIR', 'ARGV0', 'OWD')
EXIT_REFUSED = 2
# settings: the error was already shown to the player (a dialog or the terminal), so the generated
# "Mod settings.sh" shows no second one (it does for any other failure, such as a Python that cannot start).
EXIT_REPORTED = 3
# play: the session ended after an error (status.json last_error, not recovered) or the watcher died while
# PCSX2 ran. Play.sh pauses on every status but 0, so the explanation stays on screen.
EXIT_SESSION_ERROR = 3
RED, YELLOW = '31', '33'

MISSING_FILE = 'Missing file: {path}'
NOT_EXECUTABLE = ('The PCSX2 AppImage cannot run: {path} is not executable, or its folder is mounted noexec. '
                  'Run chmod +x on it, or install the mod into a folder in your home directory.')
NEEDS_PLAYER_VERSION = 'This runtime needs PCSX2 {minimum} or newer ({major}.x); it contains PCSX2 {version}.'
NEEDS_DEVELOPER_VERSION = 'The developer runtime needs PCSX2 {developer}; it contains PCSX2 {version}.'
UNTESTED_VERSION = ('PCSX2 {version} is not one of the supported stable releases ({tested}). '
                    'It is allowed; report any problem with this version.')
NEEDS_EXTRA_MEMORY = 'The isolated profile must have ExtraMemory = true in [EmuCore/CPU].'
NEEDS_PINE = 'Automatic preparation requires EnablePINE = true and PINESlot = {slot} in the isolated profile.'
NEEDS_CHEATS = 'The isolated profile needs EnableCheats = true for its in-game loading hook.'
CLOSE_EMULATOR = 'Close the current emulator, then run this launcher again.'
EMULATOR_APPEARED = 'An emulator opened while this launcher was starting. Close it before launching again.'
PINE_FOREIGN = ('The PINE socket {path} belongs to another user or cannot be opened, so this PCSX2 could not serve '
                'the mod there. Close the PCSX2 that uses it, or remove that file, then start again.')
NO_PYTHON = 'No Python 3.11+ with the trainer dependencies could start. {detail}'
BT4_FAILED = 'BT4 compatibility verification failed; nothing was launched.'
MAP_FAILED = 'Expanded-map selection failed. No emulator was launched; see the message above.'
DISC_UNUSABLE = 'The game disc chosen in {mod_settings} cannot be used; see the message above.'
ISO_MISSING = 'Selected game ISO is missing: {path}'
LEASE_BUSY = ('Another Tag Team Mod launcher is still running or cleaning up. '
              'Close its emulator before launching again.')
NOT_STARTED = 'Automatic preparation could not start. Read {path}'
NOT_CONFIRMED = 'The controller did not confirm ownership of this emulator.'
HELPER_STUCK = 'An owned launcher helper did not stop.'
# The watcher died while PCSX2 still runs (TTM-PLAY-37, the same line as launch-autopilot.ps1 'helperstop.line').
WATCHER_STOPPED = ("[TTM-PLAY-37] The mod's helper stopped (exit {code}), so the mod no longer prepares matches in "
                   'this session. Close PCSX2, then start {play} again. Logs: {logs}')
BROKEN_VENV = ('The private Python environment ({prefix}) was made for Python {made} but now runs Python {now}, '
               'usually because a system upgrade replaced its Python. Run Install.sh and choose the folder of this '
               'installation itself: setup installs a fresh copy beside it and offers to copy your memory cards and '
               'mod settings into it.')
MISSING_PACKAGES = (' The private Python environment is missing packages; if a system upgrade replaced its Python, '
                    'run Install.sh and choose the folder of this installation itself: setup installs a fresh copy '
                    'beside it.')
FUSE_FAILURE = ('PCSX2 could not start: its AppImage could not mount itself because FUSE is unavailable. Install '
                'FUSE 3 (the fuse3 package, which provides a setuid fusermount3) and make sure /dev/fuse exists. The '
                'launcher never extracts the AppImage instead (APPIMAGE_EXTRACT_AND_RUN is not used).')
LIBRARY_FAILURE = ('PCSX2 could not start: the system library {library} is missing. Install it with your package '
                   'manager{hint}.')
LIBRARY_HINTS = {'libOpenGL.so.0': ' (Debian/Ubuntu: libopengl0; Fedora: libglvnd-opengl; Arch: libglvnd)'}
DISPLAY_FAILURE = ('PCSX2 could not start: it needs a desktop session (DISPLAY or WAYLAND_DISPLAY). Start Play '
                   'from your desktop.')
EARLY_EXIT = 'PCSX2 closed during startup ({status}).'
SETTINGS_MISSING = 'Missing settings application: {path}'
SETTINGS_NO_TK = 'Could not find Python 3.11 or later with Tk. {detail}'
TK_HINT = (' Install Tk for Python (Debian/Ubuntu: python3-tk; Fedora: python3-tkinter; Arch: tk), '
           'then open Mod settings again.')
SETTINGS_FAILED = 'The settings window could not finish. Check {logs} for details.'
SETTINGS_TITLE = 'Tag Team Mod settings'

# The launcher's own failures, explained (codes: player_errors.LAUNCH_CODES; Spanish: localization.ES;
# launch-autopilot.ps1 carries the same text). Each entry: what happened, why, how to fix.
# What setup does with the folder of an installation (install_player.plan_destination): a fresh copy beside it, then
# the offer to copy the memory cards and mod settings (install_player.import_previous).
CHECK_OR_REINSTALL = ('Run {check_installation}. If it reports a problem, run {install} and choose the folder of this '
                      'installation itself (the one that contains {play}): setup installs a fresh copy beside it and '
                      'offers to copy your memory cards and mod settings into it.')
REINSTALL = 'Restore the missing file, or install the mod again into a new folder.'
EXPLAIN = {
    'TTM-PLAY-20': ('PCSX2 is already running, so Play did not start.', 'Only one PCSX2 can run while the mod plays.',
                    'Close every PCSX2 window (check the taskbar), then start {play} again.'),
    'TTM-PLAY-21': ('Another program is using the connection port Play needs.', '',
                    'Close that program, then start {play} again.'),
    'TTM-PLAY-22': ('The game ISO is no longer at its saved location.',
                    'It was moved, renamed or deleted, or its drive is not connected.',
                    'Put it back or reconnect its drive, or choose its new location when {play} asks.'),
    'TTM-PLAY-23': ('The game ISO could not be checked.', '',
                    'Read the message above. If you replaced the ISO, add the new file in {mod_settings} > Game disc and use it.'),
    'TTM-PLAY-24': ('A file Play needs is missing.', 'The installation is incomplete, or a security program removed a file.',
                    CHECK_OR_REINSTALL),
    'TTM-PLAY-25': ("The mod's private Python (.venv) does not start.",
                    'The Python it was made from was removed, upgraded or changed.',
                    'Run {install} and choose the folder of this installation itself (the one that contains {play}): '
                    'setup installs a fresh copy beside it and offers to copy your memory cards and mod settings into it.'),
    'TTM-PLAY-26': ('No Python with the mod packages could start.', '',
                    'Install Python 3.11 or later with the packages the mod needs, then start {play} again.'),
    'TTM-PLAY-27': ('Your mod settings file cannot be read.',
                    'The file game/mod-settings.json is damaged or comes from an unsupported version.',
                    'Open {mod_settings} and choose Restore defaults (or delete game/mod-settings.json), then start {play} again.'),
    'TTM-PLAY-28': ('A game file the mod needs is missing or does not match.', '', CHECK_OR_REINSTALL),
    'TTM-PLAY-29': ('This PCSX2 version is not supported.', '',
                    'Install the mod again into a new folder; setup installs a supported PCSX2.'),
    'TTM-PLAY-30': ('A PCSX2 setting this installation needs was changed.', '', CHECK_OR_REINSTALL),
    'TTM-PLAY-31': ('Another Play window is still starting or closing.', '',
                    'Close its PCSX2, wait a few seconds, then start {play} again.'),
    'TTM-PLAY-32': ('A startup step failed.', '',
                    'Start {play} again. If it happens again, send the saved log file to the mod author.'),
    'TTM-PLAY-33': ("The mod's helper could not start.", '',
                    'Close PCSX2, then start {play} again. If it happens again, send the log folder to the mod author.'),
    'TTM-PLAY-34': ("The mod's helper did not start in time, so PCSX2 was closed.",
                    'The PC was busy, or a security program delayed Python.', 'Start {play} again.'),
    'TTM-PLAY-35': ('PCSX2 closed while Play was starting.', '', 'Read the message above, then start {play} again.'),
    'TTM-PLAY-36': ('PCSX2 closed with an error.', 'PCSX2 crashed; a graphics driver problem is the usual cause.',
                    'Start {play} again. If it keeps happening, update your graphics driver or choose another renderer in PCSX2.'),
    'TTM-PLAY-37': ("The mod's helper stopped during the session.", '',
                    'Close PCSX2, then start {play} again. If it happens again, send the log folder to the mod author.'),
    'TTM-PLAY-39': ('The expanded-map ISO could not be selected.', '',
                    'Read the message above. Turn expanded maps off in {mod_settings}, or build them again.'),
    'TTM-PLAY-40': ('Play stopped because of an unexpected error.', '',
                    'Start {play} again. If it happens again, send the saved log file to the mod author.'),
    'TTM-PLAY-41': ('A PCSX2 opened while Play was starting.', '', 'Close it, then start {play} again.'),
    'TTM-PLAY-44': ('The chosen file is not the installed game ISO.', 'Only the same ISO file (same contents) can be used.',
                    'Choose the same ISO file again, or add another ISO in {mod_settings} > Game disc.'),
    'TTM-PLAY-46': ('The game disc chosen in {mod_settings} cannot be used.',
                    'Its extracted files are missing or changed, or the selection file game/discs/active.json is damaged.',
                    'Open {mod_settings} > Game disc and choose a disc again (the disc you installed with always works), '
                    'then start {play} again.'),
}
# The game disc a Play session runs (game_profile.PIN): every child of one launch is pinned to the disc resolved once,
# under the lease, by game_profile.py --where.
DISC_ENV = 'TAGTEAM_DISC'
# The private Python starts but fails its check (a package or Tk is missing): not a removed base Python.
VENV_PACKAGES = 'The private Python starts, but a package the mod needs is missing or damaged.'
PINE_SERVER = 'a PINE server on {where}'
SESSION_ENDED = 'The session ended after an error. Details are above and in the report file.'
RECOVERED_SESSION = 'A problem was handled during the session; you could keep playing.'
RELINK_PROMPT = 'Where is the game ISO now? Type its full path and press Enter (empty: stop): '
# The watcher log in the terminal: the same patterns as launch-autopilot.ps1 (launcher-lifecycle.ps1).
# Telemetry stays in watcher.log; an explicit deny list hides it, never an allow list.
ERROR_LINE = r'^\d\d:\d\d:\d\d ERROR:'
WARNING_LINE = r'^\d\d:\d\d:\d\d WARNING:'
DENY_LINE = (r'^(?:\d\d:\d\d:\d\d )?(?:[A-Z]+: )?(?:loading cover:|Menu return:|Extra reload timing:|Body Change (?:timing|pre-hold recovery|handoff actions):|Team activated\. Restart checkpoint:|The automatic launcher handles rematches\.|Capturing a fresh idle team match|Rematch checkpoint:|Saved clean [a-z ]+ checkpoint\.|Reused savestate slot\(s\) |Se reutilizaron las ranuras de guardado |Phase-1 stall: |Shared hold snapshot \(|Trail lists: |Frozen EE program counter )')
# autopilot.SAY_NO_CONNECTION and SAY_BOOTING in English and Spanish (localization.ES): the noise of PCSX2 closing.
CLOSING_LINE = r'^(?:\d\d:\d\d:\d\d )?WAITING: (?:The connection to PCSX2 did not answer|La conexi.n con PCSX2 no respondi.|Waiting for PCSX2 to start the game\.|Esperando a que PCSX2 inicie el juego\.)'
# A start-up step's raw proof lines (the loading hook's SHA-256, the old-file clean-up list, the session speed and
# savestate settings) stay in its launch-<step>-<n>.out.log; the Play window shows its player lines only
# ($Bt3StepRawLine in launcher-lifecycle.ps1 is the same pattern).
STEP_RAW_LINE = r'^(?:[0-9a-f]{64}|\{"removed": .*\}|Session (?:emulator speed|savestate compression): .*)$'
STEP_RETRY = 'That startup step failed; retrying it once.'
HINTS = ('Opening a clean game with automatic simultaneous-team preparation.',
         'Choose Team Battle, Free-for-all, or Modded Training in the modded main menu, including three- and four-player modes.',
         'Original-menu selections play normally; only a Modded Modes selection activates the trainer.',
         "Choose each player's team before selecting fighters. Share a team for cooperative play against CPUs.",
         'Team Battle and Training let you assign each controller to either team before selecting fighters. Share a team for co-op; CPU slots are selected by Player 1. FFA needs at least one fighter per human.',
         'A loading screen prepares every fighter and the full team display before the match begins.')


def _localization():
    """localization (standard library only), or None in a folder that lacks it."""
    try:
        import localization
        return localization
    except Exception:
        return None


def translate(text, settings=None, **values):
    """localization.tr with the saved language (settings: a mod-settings dict), or plain English."""
    loc = _localization()
    if loc is not None:
        try:
            return loc.tr(text, settings, **values)
        except Exception:
            pass
    return text.format(**values) if values else text


def launcher_names(found):
    """localization.entries() with plain fallbacks, plus 'install': setup's launcher on the Play launcher's platform."""
    found = dict(found or {})
    found['play'] = found.get('play') or 'Play'
    found['mod_settings'] = found.get('mod_settings') or 'Mod settings'
    found.setdefault('check_installation', '')
    windows = found['play'].endswith('.cmd') or (WINDOWS and not found['play'].endswith('.sh'))
    found['install'] = 'Install.cmd' if windows else 'Install.sh'
    return found


def names():
    """{name: launcher} of this installation (localization.entries), with plain fallbacks."""
    loc = _localization()
    try:
        found = loc.entries() if loc is not None else {}
    except Exception:
        found = {}
    return launcher_names(found)


def explanation(code, settings=None):
    """(what, why, fix) of a launcher code, translated and with this installation's launcher names."""
    what, why, fix = EXPLAIN.get(code, EXPLAIN['TTM-PLAY-40'])
    values = names()
    if '{check_installation}' in fix and not values['check_installation']:
        fix = REINSTALL
    return (translate(what, settings), translate(why, settings) if why else '', translate(fix, settings, **values))


def render_block(code, what, why='', fix='', file=None, details='', detail_lines=(), report=None, log=None,
                 nothing_changed=False, language=None):
    """player_errors.block, or the plain lines when that module cannot be loaded."""
    try:
        import player_errors
        return player_errors.block(code, what, why, fix, file=file, details=details, detail_lines=detail_lines,
                                   report=report, log=log, nothing_changed=nothing_changed, language=language)
    except Exception:
        lines = [f'[{code}] {what}'] + [line for line in (why, fix) if line]
        lines += [str(path) for path in (file, report, log) if path] + ([details] if details else []) + list(detail_lines)
        return lines


def hint_lines(root, logs, manual_pause=False, windows=WINDOWS, disc=None):
    """The launch hints in the player's language (launch-autopilot.ps1 prints them through `hints`). disc: the title
    of the game disc this session starts (game_profile.py --where), none in a developer folder."""
    button, seconds, settings, drift = 'r3', 0.5, {}, []
    path = Path(root)/'mod-settings.json'
    try:
        # The settings the match uses (keys the file lacks take the shipped defaults, as in a new installation); the
        # raw file only when mod_settings cannot be loaded. The hints never stop a launch.
        try:
            import mod_settings
            values = mod_settings.load_settings(path)
            drift = mod_settings.developer_drift(path)
        except Exception:  # noqa: BLE001
            values = json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(values, dict):
            settings = values
        if 'lockon_switch_button' in values:
            button = str(values['lockon_switch_button'])
        if 'lockon_hold_seconds' in values:
            seconds = float(values['lockon_hold_seconds'])
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, AttributeError):
        button = 'r3'
    lines = [translate(line, settings) for line in HINTS]
    if seconds == 0:
        lines.append(translate('Target/spectator switch: tap {button}.', settings, button=button.upper()))
    else:
        lines.append(translate('Target/spectator switch: hold {button} for {seconds} seconds, then release.', settings,
                               button=button.upper(), seconds=f'{seconds:g}'))
    # Stick aiming (lockon_select) is on by default: with the switch button held (not with R3, the stick's own
    # click) or, when set, the right stick alone while locked on (any switch button).
    on = settings.get('lockon_right_stick', True) is True
    alone = settings.get('lockon_right_stick_mode') == 'right_stick_alone'
    if on and alone:
        lines.append(translate('Flick the right stick to pick a target while locked on; left/right steps around you.', settings))
    elif on and button.lower() != 'r3':
        lines.append(translate('Hold {button} and flick the right stick to pick a target; left/right steps around you.',
                               settings, button=button.upper()))
    # Switching to your attacker (lockon_threat) is on by default: the switch during an attack warning. A hold time
    # makes it the hold-and-release switch, latched when the button goes down.
    if settings.get('lockon_attacker_switch', 'tap_during_warning') in ('tap_during_warning', 'when_hit'):
        hint = 'During an attack warning, tap {button} to lock on to your attacker.' if seconds == 0 else 'During an attack warning, your {button} target switch locks on to your attacker.'
        lines.append(translate(hint, settings, button=button.upper()))
    if drift:
        # Developer folders only (mod_settings.developer_drift): what differs from a new installation's settings.
        shown = ', '.join(drift[:4]) + (f' (+{len(drift)-4})' if len(drift) > 4 else '')
        text = ('Developer folder: 1 setting differs from a new installation: {keys}. Details: '
                'python tools/dev_settings_parity.py --report' if len(drift) == 1 else
                'Developer folder: {count} settings differ from a new installation: {keys}. Details: '
                'python tools/dev_settings_parity.py --report')
        lines.append(translate(text, settings, count=len(drift), keys=shown))
    lines.append(translate('After defeat, watch a living CPU teammate and press Square to take over (L2+Square if Square is your target-switch button). Not available in FFA or CPU-only matches.', settings))
    lines.append(translate('Fight Again reloads the prepared match with the button it was prepared with.', settings))
    lines.append(translate('{mod_settings} controls which game disc {play} starts, pauses, cinematics, fusion controls, display options and '
                           'target-switch input/timing.', settings, mod_settings=names()['mod_settings'], play=names()['play']))
    if disc:
        lines.append(translate('Game disc: {disc}. To start another of your ISOs, close PCSX2 and choose it in '
                               '{mod_settings} > Game disc.', settings, disc=disc, mod_settings=names()['mod_settings']))
    lines.append(translate('Preparation status and errors remain in this window. Logs: {logs}', settings, logs=logs))
    if manual_pause or not windows:
        # Only Windows can send PCSX2 its pause key; elsewhere the watcher asks the player to press it.
        lines.append(translate('Manual pause mode: follow the Space instructions in this window.', settings))
    return lines


def crash_status(returncode, windows=WINDOWS):
    """True when PCSX2's exit status is a crash: an exception code on Windows, a fatal signal elsewhere."""
    if returncode is None:
        return False
    if windows:
        return (returncode & 0xF0000000) == 0xC0000000
    fatal = {getattr(signal, name, None) for name in ('SIGSEGV', 'SIGABRT', 'SIGBUS', 'SIGILL', 'SIGFPE')} - {None}
    return returncode < 0 and -returncode in fatal


def relinked_iso(root, profile, default):
    """game_profile.iso_path, repeated so this launcher needs no game_profile import: iso-location.json wins
    when its sha256 equals the profile's iso_sha256 and that file exists (an ISO moved back is found)."""
    expected = str(profile.get('iso_sha256') or '').lower() if isinstance(profile, dict) else ''
    try:
        location = json.loads((Path(root)/'iso-location.json').read_text(encoding='utf-8-sig'))
        if (expected and isinstance(location, dict) and isinstance(location.get('path'), str)
                and str(location.get('sha256', '')).lower() == expected and Path(location['path']).is_file()):
            return Path(location['path'])
    except (OSError, ValueError, UnicodeError):
        pass
    return default


class LaunchError(RuntimeError):
    """A startup failure: shown as an explained block, saved to launch-error-*.log, exit status `exit` (1,
    or 2 when nothing was started because a file, the ISO or the private Python is missing or broken).
    `why` replaces the code's usual reason; `explained` means a child process already printed the block."""

    def __init__(self, message, code='TTM-PLAY-40', exit=1, file=None, why=None, explained=False):
        super().__init__(message)
        self.code, self.exit, self.file, self.why, self.explained = code, exit, file, why, explained


class Refused(RuntimeError):
    """Nothing was started because another PCSX2 is running (TTM-PLAY-20), or another program holds the
    PINE port or socket (TTM-PLAY-21). Exit status 2."""
    exit, file = EXIT_REFUSED, None

    def __init__(self, message, code='TTM-PLAY-20'):
        super().__init__(message)
        self.code = code


class Stopped(BaseException):
    """SIGINT/SIGTERM (or SIGHUP before startup completed): clean up like the PowerShell finally block."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


class Detached(BaseException):
    """SIGHUP after startup: the terminal closed; PCSX2, its watcher and the settings watchdog keep running."""


# ---- PINE socket and environment -------------------------------------------------------------------------

def socket_path(slot, environ=None):
    """pine.socket_path, repeated so this launcher needs no watcher module (test_play_launcher keeps them equal).

    $XDG_RUNTIME_DIR/pcsx2.sock ($TMPDIR on macOS), or /tmp/pcsx2.sock when the variable is unset, plus
    '.<slot>' for every slot but PCSX2's default, cut where PCSX2 cuts an over-long name.
    """
    environ = os.environ if environ is None else environ
    override = environ.get(SOCKET_ENV)
    if override:
        return override
    if type(slot) is not int:
        raise ValueError('The PINE slot must be an integer')
    folder = environ.get('TMPDIR' if sys.platform == 'darwin' else 'XDG_RUNTIME_DIR')
    path = '/tmp/pcsx2.sock' if folder is None else folder + '/pcsx2.sock'
    if slot != PCSX2_DEFAULT_SLOT:
        path += f'.{slot}'
    encoded = os.fsencode(path)
    return os.fsdecode(encoded[:SUN_PATH_BYTES]) if len(encoded) > SUN_PATH_BYTES else path


def runtime_directory_problem(value, slot=PINE_SLOT):
    """Why PCSX2 should not put its PINE socket in this XDG_RUNTIME_DIR, or None (unset means /tmp, which is fine)."""
    if value is None:
        return None
    if not value:
        return 'is empty'
    if not os.path.isabs(value):
        return 'is not an absolute path'
    try:
        info = os.stat(value)
    except OSError:
        return 'does not exist'
    if not stat.S_ISDIR(info.st_mode):
        return 'is not a folder'
    if hasattr(os, 'getuid') and info.st_uid != os.getuid():
        return 'belongs to another user'
    if not os.access(value, os.W_OK | os.X_OK):
        return 'is not writable'
    if len(os.fsencode(value + '/pcsx2.sock' + ('' if slot == PCSX2_DEFAULT_SLOT else f'.{slot}'))) > SUN_PATH_BYTES:
        return 'is too long for a socket path'
    return None


def launch_environment(profile, slot=PINE_SLOT, base=None, windows=WINDOWS, warn=None):
    """(environment, PINE socket path) shared by PCSX2, the watcher and every helper.

    POSIX: an unusable XDG_RUNTIME_DIR is dropped (PCSX2 then serves /tmp/pcsx2.sock) and the final socket
    path is passed to the watcher as TAGTEAM_PINE_SOCKET, so both sides always agree. Windows: loopback TCP.
    """
    env = dict(os.environ if base is None else base)
    env['BT3_RUNTIME_PROFILE'] = profile
    # Every Python child writes UTF-8 (player paths, Spanish text); this launcher reads it as UTF-8.
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    for name in APPIMAGE_VARIABLES:
        env.pop(name, None)
    env.pop(SOCKET_ENV, None)  # PCSX2 never reads it: only the path computed below is true
    if windows:
        return env, None
    value = env.get('XDG_RUNTIME_DIR')
    problem = runtime_directory_problem(value, slot)
    if problem:
        del env['XDG_RUNTIME_DIR']
        if warn:
            warn(f'XDG_RUNTIME_DIR ({value!r}) {problem}; PCSX2 and the mod use {socket_path(slot, env)} instead.')
    path = socket_path(slot, env)
    env[SOCKET_ENV] = path
    return env, path


def pine_in_use(path=None, port=PINE_SLOT, timeout=1.0):
    """True when something accepts PINE connections: the Unix socket `path`, or loopback TCP `port` on Windows.

    A socket file nobody listens on is stale and fine (PCSX2 unlinks it before binding). Raises Refused when
    the path exists but cannot be opened (another user's socket PCSX2 could not replace).
    """
    if path is None:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=5):
                return True
        except ConnectionRefusedError:
            return False
        except socket.timeout:
            return True
        except OSError:
            return False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(timeout)
        client.connect(path)
        return True
    except (FileNotFoundError, ConnectionRefusedError, NotADirectoryError):
        return False
    except PermissionError:
        raise Refused(PINE_FOREIGN.format(path=path), 'TTM-PLAY-21') from None
    except socket.timeout:
        return True  # a listener with a full backlog
    except OSError:
        return False
    finally:
        client.close()


# ---- Other emulators ------------------------------------------------------------------------------------

def looks_like_pcsx2(name=None, exe=None, appimage=None):
    """basename(exe) is pcsx2-qt, the process name starts with pcsx2, or it runs from an AppImage named after PCSX2."""
    return bool((exe and os.path.basename(exe) == 'pcsx2-qt') or
                (name and name.lower().startswith('pcsx2')) or
                (appimage and 'pcsx2' in os.path.basename(appimage).lower()))


def linux_processes(proc='/proc'):
    """(pid, name, exe, APPIMAGE) of this user's running processes (another user's hide their exe and are
    skipped); a field that cannot be read is None."""
    own = os.getpid()
    try:
        entries = os.listdir(proc)
    except OSError:
        return
    for entry in entries:
        if not entry.isdigit() or int(entry) == own:
            continue
        folder = os.path.join(proc, entry)
        try:
            with open(os.path.join(folder, 'stat'), 'rb') as stream:
                status = stream.read()
        except OSError:
            continue  # exited meanwhile
        if status[status.rfind(b')') + 2:][:1] in (b'Z', b'X'):
            continue  # a zombie is not running
        name = exe = appimage = None
        try:
            exe = os.readlink(os.path.join(folder, 'exe')).removesuffix(' (deleted)')
        except PermissionError:
            continue  # another user's process: it serves that user's own PINE socket, not this launch
        except OSError:
            pass  # a kernel thread, or exited meanwhile
        try:
            with open(os.path.join(folder, 'comm'), 'rb') as stream:
                name = os.fsdecode(stream.read().rstrip(b'\n'))
        except OSError:
            pass
        try:
            with open(os.path.join(folder, 'environ'), 'rb') as stream:
                for item in stream.read().split(b'\0'):
                    if item.startswith(b'APPIMAGE='):
                        appimage = os.fsdecode(item[9:])
                        break
        except OSError:
            pass
        yield int(entry), name, exe, appimage


def windows_processes():
    """(pid, image name, None, None) from tasklist, like Get-Process -Name 'pcsx2*' in launch-autopilot.ps1."""
    try:
        result = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, errors='replace',
                                timeout=60, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) >= 2 and row[1].isdigit():
            yield int(row[1]), row[0], None, None


def other_emulators():
    """Running PCSX2 processes, as 'name (process N)' plus ': path' when the path is readable."""
    rows = windows_processes() if WINDOWS else linux_processes()
    return [f'{name or exe or appimage} (process {pid})' + (f': {appimage or exe}' if (appimage or exe) else '')
            for pid, name, exe, appimage in rows if looks_like_pcsx2(name, exe, appimage)]


# ---- Profile checks ---------------------------------------------------------------------------------------

_CPU_SECTION = re.compile(r'^\[EmuCore/CPU\]\s*\r?\n(?P<body>.*?)(?=^\[|\Z)', re.M | re.S)


def _setting(name, value):
    # PowerShell's -match is case-insensitive; the section lookup above ([regex]::Match) is not.
    return re.compile(rf'^{name}\s*=\s*{value}\s*$', re.M | re.I)


def check_configuration(text, slot=PINE_SLOT):
    """launch-autopilot.ps1's PCSX2.ini checks, with the same patterns and messages."""
    section = _CPU_SECTION.search(text)
    if not section or not _setting('ExtraMemory', 'true').search(section.group('body')):
        raise LaunchError(NEEDS_EXTRA_MEMORY, 'TTM-PLAY-30', EXIT_REFUSED)
    if not _setting('EnablePINE', 'true').search(text) or not _setting('PINESlot', str(slot)).search(text):
        raise LaunchError(NEEDS_PINE.format(slot=slot), 'TTM-PLAY-30', EXIT_REFUSED)
    if not _setting('EnableCheats', 'true').search(text):
        raise LaunchError(NEEDS_CHEATS, 'TTM-PLAY-30', EXIT_REFUSED)


def file_digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def recorded_version(root, emulator):
    """The PCSX2 version the installer recorded in installed-files.json, while that emulator file is unchanged."""
    receipt = Path(root).parent/'installed-files.json'
    try:
        data = json.loads(receipt.read_text(encoding='utf-8-sig'))
        key = Path(emulator).resolve().relative_to(receipt.parent.resolve()).as_posix()
        expected, version = data['files'][key], data['emulator_version']
        if not isinstance(version, str) or file_digest(emulator) != expected:
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return version


def appimage_environment(base=None):
    return {k: v for k, v in (os.environ if base is None else base).items() if k not in APPIMAGE_VARIABLES}


def appimage_version(appimage, timeout=120):
    """'2.8.2' from the AppImage's usr/share/metainfo (<release version="v2.8.2">), unpacked in a fresh temporary
    folder; the runtime's --appimage-extract needs neither FUSE nor a display. None when unreadable."""
    with tempfile.TemporaryDirectory(prefix='tagteam-version-') as folder:
        try:
            subprocess.run([str(appimage), '--appimage-extract', 'usr/share/metainfo'], cwd=folder,
                           env=appimage_environment(), stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        for xml in sorted(Path(folder).glob('squashfs-root/usr/share/metainfo/*.xml')):
            if xml.is_symlink() or not xml.is_file():
                continue
            match = re.search(r'<release\b[^>]*\bversion="([^"]+)"', xml.read_text(encoding='utf-8', errors='replace'))
            parsed = pcsx2_versions.parse(match.group(1)) if match else None
            if parsed:
                return pcsx2_versions.text(parsed)
    return None


def windows_file_version(path):
    """'2.8.2.0' from the executable's version resource (FileVersionInfo in launch-autopilot.ps1), or None."""
    from ctypes import wintypes
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    api.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    value, length = ctypes.c_void_p(), wintypes.UINT()
    if (not api.GetFileVersionInfoW(str(path), 0, size, data) or
            not api.VerQueryValueW(data, '\\', ctypes.byref(value), ctypes.byref(length)) or length.value < 52):
        return None
    info = ctypes.cast(value, ctypes.POINTER(wintypes.DWORD))
    return '.'.join(map(str, (info[2] >> 16, info[2] & 0xffff, info[3] >> 16, info[3] & 0xffff)))


def version_problem(version, profile):
    """(error, notice) under pcsx2_versions.json, like Test-Bt3Pcsx2Version: runtime28 takes any accepted 2.x."""
    shown = version or 'unknown'
    policy = pcsx2_versions.policy()
    if profile == 'runtime28':
        if not pcsx2_versions.player_accepts(shown):
            minimum = policy['player_minimum']
            return NEEDS_PLAYER_VERSION.format(minimum=pcsx2_versions.text(minimum), major=minimum[0], version=shown), None
        if not pcsx2_versions.is_tested(shown):
            return None, translate(UNTESTED_VERSION, None, version=pcsx2_versions.text(pcsx2_versions.parse(shown)),
                                   tested=pcsx2_versions.tested_text())
        return None, None
    if not pcsx2_versions.developer_accepts(shown):
        return NEEDS_DEVELOPER_VERSION.format(developer=pcsx2_versions.text(policy['developer']), version=shown), None
    return None, None


def controller_ready(status, token, emulator_pid):
    """Test-Bt3ControllerStatus: this launch's token, a worker PID and the owned emulator, not failed or closed."""
    if not isinstance(status, dict) or not token:
        return False
    if any(key not in status for key in ('launcher_token', 'pid', 'emulator_pid', 'state')):
        return False
    pid = status['pid']
    return (status['launcher_token'] == token and type(pid) is int and pid > 0 and
            status['emulator_pid'] == emulator_pid and str(status['state']).upper() not in ('FAILED', 'CLOSED'))


def venv_problem(prefix=None, base_prefix=None, version=None):
    """A clear message when this virtual environment was made for another Python (a distribution upgrade)."""
    prefix = Path(sys.prefix if prefix is None else prefix)
    base_prefix = Path(sys.base_prefix if base_prefix is None else base_prefix)
    version = tuple((version or sys.version_info)[:2])
    if prefix == base_prefix:
        return None
    try:
        lines = (prefix/'pyvenv.cfg').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return None
    for line in lines:
        key, separator, value = line.partition('=')
        if separator and key.strip().lower() in ('version_info', 'version'):
            made = pcsx2_versions.parse(value.strip()) or tuple(int(p) for p in re.findall(r'\d+', value)[:2])
            if len(made) >= 2 and tuple(made[:2]) != version:
                return BROKEN_VENV.format(prefix=prefix, made='.'.join(map(str, made[:2])),
                                          now='.'.join(map(str, version)))
            return None
    return None


def startup_failure(returncode, output):
    """Why PCSX2 closed before the watcher confirmed it, or None for a normal close (exit status 0)."""
    if returncode == 0 or returncode is None:
        return None
    lines = output.strip().splitlines()[-12:]
    detail = ('\n' + '\n'.join(lines)) if lines else ''
    lowered = output.lower()
    # First: a loader error names the mounted program (/tmp/.mount_*/usr/bin/pcsx2-qt), so FUSE worked.
    missing = re.search(r'error while loading shared libraries: ([^:\s]+)', output)
    if missing:
        library = missing.group(1)
        return LIBRARY_FAILURE.format(library=library, hint=LIBRARY_HINTS.get(library, '')) + detail
    # 'Cannot mount AppImage, please check your FUSE setup.', 'fusermount3: mount failed', 'libfuse', never
    # 'refused' or a '.mount_' path.
    if re.search(r'fusermount|libfuse|/dev/fuse|\bfuse\b|cannot mount|mount failed|failed to mount', lowered):
        return FUSE_FAILURE + detail
    if 'could not connect to display' in lowered or 'qt platform plugin' in lowered:
        return DISPLAY_FAILURE + detail
    if WINDOWS and crash_status(returncode, windows=True):
        status = f'exception code 0x{returncode & 0xFFFFFFFF:08X}'
    else:
        status = f'stopped by signal {-returncode}' if returncode < 0 else f'exit status {returncode}'
    return EARLY_EXIT.format(status=status) + (detail or ' It printed nothing.')


# ---- Processes --------------------------------------------------------------------------------------------

def _kernel32():
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)]*4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel


def process_start_time(pid):
    """When a process started, in the unit presentation_settings' watchdog compares (--start-time), or None.

    Linux: seconds since boot, starttime (clock ticks, /proc/<pid>/stat) / CLK_TCK, as presentation_settings.
    process_started() reads it. Not psutil's create_time(): that adds the boot time derived from the wall clock,
    so a clock step between launch and check would make the watchdog take PCSX2 for a reused PID and restore
    the settings while PCSX2 still runs. Windows: seconds since the epoch, as psutil's create_time().
    """
    if WINDOWS:
        from ctypes import wintypes
        kernel = _kernel32()
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *map(ctypes.byref, times)):
                return None
            created = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
            return (created - 116444736000000000) / 10_000_000
        finally:
            kernel.CloseHandle(handle)
    try:
        with open(f'/proc/{pid}/stat', 'rb') as stream:
            data = stream.read()
        return float(data[data.rfind(b')') + 2:].split()[19]) / os.sysconf('SC_CLK_TCK')
    except (OSError, ValueError, IndexError):
        return None


class Child:
    """A process this launcher started (subprocess.Popen): signalled by its own PID only, never its group."""

    def __init__(self, process):
        self.process = process
        self.pid = process.pid

    @property
    def returncode(self):
        return self.process.poll()

    def exited(self):
        return self.process.poll() is not None

    def wait(self, timeout):
        try:
            self.process.wait(timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def send(self, signum):
        self.process.send_signal(signum)  # skipped once the process has been reaped

    def kill(self):
        self.process.kill()

    def close(self):
        pass


class OwnedPid:
    """The watcher's worker when it is not the process the launcher started (the Windows venv redirector's child).

    Found once, through the watcher's authenticated status file, then held by a handle (a pidfd on Linux), so a
    reused PID is never signalled.
    """

    def __init__(self, pid):
        self.pid = pid
        self._handle = self._fd = None
        if WINDOWS:
            self._kernel = _kernel32()
            # SYNCHRONIZE | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION
            self._handle = self._kernel.OpenProcess(0x00100000 | 0x0001 | 0x1000, False, pid)
            if not self._handle:
                raise ctypes.WinError(ctypes.get_last_error())
        elif hasattr(os, 'pidfd_open'):
            self._fd = os.pidfd_open(pid)
        else:
            os.kill(pid, 0)

    @property
    def returncode(self):
        if not self.exited():
            return None
        if WINDOWS:
            from ctypes import wintypes
            code = wintypes.DWORD()
            return code.value if self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)) else None
        return None  # not our child: its status belongs to its parent

    def exited(self):
        return self.wait(0)

    def wait(self, timeout):
        if WINDOWS:
            milliseconds = 0xFFFFFFFF if timeout is None else max(0, int(timeout*1000))
            return self._kernel.WaitForSingleObject(self._handle, milliseconds) == 0
        if self._fd is not None:
            import select
            return bool(select.select([self._fd], [], [], timeout)[0])
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            try:
                os.kill(self.pid, 0)
            except ProcessLookupError:
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(.05)

    def send(self, signum):
        if WINDOWS:
            self.kill()
            return
        try:
            if self._fd is not None:
                signal.pidfd_send_signal(self._fd, signum)
            else:
                os.kill(self.pid, signum)
        except ProcessLookupError:
            pass

    def kill(self):
        if WINDOWS:
            self._kernel.TerminateProcess(self._handle, 1)
        else:
            self.send(signal.SIGKILL)

    def close(self):
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def stop_owned(process, grace=5.0, interrupt_grace=5.0):
    """Stop-Bt3OwnedHelper: a helper normally finishes when the emulator closes. After `grace`, POSIX helpers get
    SIGINT (the watcher then runs its own clean-up), then everything is killed through the retained object."""
    if process is None or process.wait(grace):
        return
    if not WINDOWS and interrupt_grace:
        process.send(signal.SIGINT)
        if process.wait(interrupt_grace):
            return
    process.kill()
    if not process.wait(5):
        raise LaunchError(HELPER_STUCK)


class Lease:
    """analysis/autopilot/.launcher.lock, held for the whole launch (Enter-Bt3LauncherLease).

    fcntl.flock on POSIX, a byte lock on Windows; the operating system releases it if the launcher dies.
    """

    def __init__(self, path, timeout=12.0):
        self.path, self.timeout, self.fd = Path(path), timeout, None

    def _try(self):
        if WINDOWS:
            import msvcrt
            try:
                descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_BINARY | os.O_NOINHERIT)
            except PermissionError:
                raise BlockingIOError('held exclusively by another Play window') from None
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError:
                os.close(descriptor)
                raise BlockingIOError('locked') from None
        else:
            import fcntl
            descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(descriptor)
                raise
        self.fd = descriptor

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._try()
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LaunchError(LEASE_BUSY, 'TTM-PLAY-31', EXIT_REFUSED) from None
                time.sleep(.1)

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _decode(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False), 'replace')


def tail(path, count=24):
    """The last `count` lines of a log (all of them for None); nothing when it cannot be read."""
    try:
        lines = _decode(Path(path).read_bytes()).splitlines()
    except OSError:
        return []
    return lines if count is None else lines[-count:]


# ---- play -------------------------------------------------------------------------------------------------

class Launcher:
    """One `play` run. The timing attributes are the PowerShell values; tests shorten them."""
    ready_timeout = 10.0
    ready_poll = .1
    follow_poll = .5
    retry_delay = 2.0
    helper_grace = 5.0
    emulator_grace = 3.0
    lease_timeout = 12.0

    def __init__(self, root=ROOT, profile='runtime28', mode='Original', manual_pause=False, no_loading_screen=False,
                 python=None, environ=None):
        if profile not in PROFILES:
            raise ValueError('Unknown runtime profile: ' + str(profile))
        if mode not in MODES:
            raise ValueError('Unknown mode: ' + str(mode))
        self.root = Path(root)
        self.tools = self.root/'tools'
        self.profile, self.mode = profile, mode
        self.manual_pause, self.no_loading_screen = manual_pause, no_loading_screen
        self.python = python or sys.executable
        self.environ = dict(os.environ if environ is None else environ)
        self.bt4 = (self.tools/'bt4_preflight.py').is_file()
        self.env = self.socket = self.logs = self.lease = self.emulator_path = self.where_failure = None
        self.disc_title = None   # the chosen game disc's title (game_iso), named in the hints
        self.emulator = self.watchdog = self.watcher = self.worker = None
        self.python_ready = self.startup_complete = self.detached = self.cleaning = False
        self.silenced = False
        self.deferring = 0
        self.pending = None
        self.echoed = 0
        self.colors = not WINDOWS and _isatty(sys.stdout) and 'NO_COLOR' not in self.environ

    # -- output

    def say(self, text='', color=None, error=False):
        if self.silenced:
            return
        stream = sys.stderr if error else sys.stdout
        if color and self.colors:
            text = f'\x1b[{color}m{text}\x1b[0m'
        try:
            try:
                print(text, file=stream, flush=True)
            except UnicodeEncodeError:
                print(text.encode('ascii', 'replace').decode(), file=stream, flush=True)
        except (OSError, ValueError):
            self.silence()  # the terminal is gone

    def silence(self):
        """After a hangup: never write to the closed terminal again (children inherit /dev/null instead)."""
        self.silenced = True

    def inherited(self):
        return subprocess.DEVNULL if self.silenced else None

    def echo_new(self, final=False):
        if self.silenced or self.logs is None:
            return
        try:
            with open(self.logs/'watcher.log', 'rb') as stream:
                stream.seek(self.echoed)
                data = stream.read()
        except OSError:
            return
        end = len(data) if final else data.rfind(b'\n') + 1  # complete lines only while it is written
        if end:
            self.echoed += end
            for line in _decode(data[:end]).splitlines():
                if re.match(DENY_LINE, line) or (final and re.match(CLOSING_LINE, line)):
                    continue  # telemetry and shutdown noise stay in watcher.log
                self.say(line, RED if re.match(ERROR_LINE, line) else YELLOW if re.match(WARNING_LINE, line) else None)

    def show_errors(self):
        if self.logs is not None:
            for line in tail(self.logs/'errors.log'):
                self.say(line, RED, error=True)

    # -- signals

    def install_signals(self):
        if threading.current_thread() is not threading.main_thread():
            return {}
        names = ('SIGINT', 'SIGTERM', 'SIGBREAK') if WINDOWS else ('SIGINT', 'SIGTERM', 'SIGHUP')
        previous = {}
        for name in names:
            number = getattr(signal, name, None)
            if number is not None:
                previous[number] = signal.signal(number, self._on_signal)
        return previous

    @staticmethod
    def restore_signals(previous):
        for number, handler in previous.items():
            signal.signal(number, handler)

    def _on_signal(self, signum, frame):
        if signum == getattr(signal, 'SIGHUP', None):
            self.silence()
        if self.cleaning or self.deferring:
            if self.pending is None:
                self.pending = signum
            return
        self._raise_for(signum)

    def _raise_for(self, signum):
        if signum == getattr(signal, 'SIGHUP', None) and self.startup_complete:
            raise Detached()
        raise Stopped(signum)

    @contextlib.contextmanager
    def critical(self):
        """Defer signals while a child is being created, so its object is always retained for clean-up."""
        self.deferring += 1
        try:
            yield
        finally:
            self.deferring -= 1
        if not self.deferring and not self.cleaning and self.pending is not None:
            signum, self.pending = self.pending, None
            self._raise_for(signum)

    # -- children

    def run_python(self, *arguments, **options):
        options.setdefault('env', self.env)
        options.setdefault('cwd', str(self.root))
        options.setdefault('stdin', subprocess.DEVNULL)
        return subprocess.run([self.python, *map(str, arguments)], **options)

    def spawn(self, command, stdout, stderr, cwd=None):
        options = dict(env=self.env, cwd=str(cwd or self.root), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        if WINDOWS:
            options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            options['start_new_session'] = True  # a closed terminal's SIGHUP never reaches the game
        return Child(subprocess.Popen([str(part) for part in command], **options))

    def emulator_command(self, iso):
        return [self.emulator_path, '-portable', '-fastboot', '--', iso]

    def run_step(self, name, description, *arguments, attempts=2):
        """Invoke-Bt3LaunchStep: output kept in launch-<name>-<n>.{out,err}.log and shown, except its raw proof lines
        (STEP_RAW_LINE); one retry."""
        error_path = None
        for attempt in range(1, attempts + 1):
            output_path = self.logs/f'launch-{name}-{attempt}.out.log'
            error_path = self.logs/f'launch-{name}-{attempt}.err.log'
            with open(output_path, 'wb') as output, open(error_path, 'wb') as errors:
                step = None
                try:
                    with self.critical():
                        step = subprocess.Popen([self.python, *map(str, arguments)], stdout=output, stderr=errors,
                                                stdin=subprocess.DEVNULL, env=self.env, cwd=str(self.root))
                    code = step.wait()
                except BaseException:
                    if step is not None:
                        step.kill()
                        step.wait()
                    raise
            for path in (output_path, error_path):
                for line in tail(path, None):
                    if not re.match(STEP_RAW_LINE, line):   # raw proof lines stay in the log
                        self.say(line)
            if code == 0:
                return
            if attempt < attempts:
                self.say(translate(STEP_RETRY), YELLOW)
                time.sleep(self.retry_delay)
        raise LaunchError(f'{description} Details: {error_path}', 'TTM-PLAY-32', file=error_path)

    def restore_display(self):
        result = self.run_python(self.tools/'presentation_settings.py', 'restore', stdout=self.inherited(),
                                 stderr=self.inherited())
        if result.returncode:
            self.say(f'Restoring the display settings failed (exit {result.returncode}).', YELLOW, error=True)

    def stop_emulator(self):
        """Startup did not complete: stop PCSX2 by its own PID (never its group: the AppImage's FUSE daemon serves it)."""
        emulator = self.emulator
        if WINDOWS:
            emulator.kill()
        else:
            emulator.send(signal.SIGTERM)
            if emulator.wait(self.emulator_grace):
                return
            emulator.kill()
        emulator.wait(5)

    # -- the launch

    def check_environment(self):
        problem = venv_problem()
        if problem:
            # The distribution upgraded the Python this .venv was made from: a refusal, not a crash.
            raise LaunchError(problem, 'TTM-PLAY-25', EXIT_REFUSED, Path(sys.prefix)/'pyvenv.cfg')
        self.env, self.socket = launch_environment(self.profile, PINE_SLOT, self.environ,
                                                   warn=lambda message: self.say(message, YELLOW))

    def game_iso(self):
        """The ISO of the game disc this session starts. game_profile.py --where names the disc chosen in Mod settings
        > Game disc, once, under the lease; every child is then pinned to it (TAGTEAM_DISC), and a damaged choice is
        TTM-PLAY-46 (explained by Python). A folder without game_profile.py reads game-profile.json as before."""
        default = self.root.parent/'games'/(BT4_ISO if self.bt4 else BT3_ISO)
        self.where_failure = None
        where = self.tools/'game_profile.py'
        if where.is_file():
            env = dict(self.env if self.env is not None else self.environ)
            for name in (DISC_ENV, 'TAGTEAM_ADAPTER'):
                env.pop(name, None)
            try:
                result = self.run_python(where, '--where', '--json', capture_output=True, env=env)
            except OSError as error:
                self.where_failure = f'{self.python}: {error}'
                return default
            errors = _decode(result.stderr)
            if result.returncode == 2 and '[TTM-PLAY-46]' in errors:
                for line in errors.splitlines():
                    if line.strip():
                        self.say(line, YELLOW, error=True)
                raise LaunchError(self.disc_unusable(), 'TTM-PLAY-46', EXIT_REFUSED, explained=True)
            lines = [line for line in _decode(result.stdout).splitlines() if line.startswith('{')]
            if result.returncode == 0 and lines:
                try:
                    found = json.loads(lines[-1])
                except ValueError:
                    found = None
                if isinstance(found, dict) and found.get('player'):
                    self.disc_title = str(found.get('title') or '') or None
                    if self.env is not None:
                        self.env.pop('TAGTEAM_ADAPTER', None)
                        self.env[DISC_ENV] = str(found.get('key') or '')
                    return Path(str(found.get('iso')))
                if isinstance(found, dict):
                    return default
            # Python did not answer (a broken private Python): the probe explains that; anything else is unexpected.
            self.where_failure = (f'game_profile.py --where ended with exit status {result.returncode}: ' +
                                  ' '.join(line for line in (errors + _decode(result.stdout)).splitlines() if line.strip()))
            return default
        path = default
        profile = self.root/'game-profile.json'
        if profile.is_file():
            try:
                record = json.loads(profile.read_text(encoding='utf-8-sig'))
                path = relinked_iso(self.root, record, Path(str(record['iso'])))
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise LaunchError(f'Could not read {profile}: {error}', 'TTM-PLAY-24', EXIT_REFUSED, profile) from error
        return path

    def disc_unusable(self):
        """The launch-error log line of a TTM-PLAY-46 refusal (Python has shown its block), in the player's language."""
        return translate(DISC_UNUSABLE, self.settings_values(), mod_settings=names()['mod_settings'])

    def settings_values(self):
        try:
            values = json.loads((self.root/'mod-settings.json').read_text(encoding='utf-8-sig'))
            return values if isinstance(values, dict) else {}
        except (OSError, ValueError):
            return {}

    def relink(self, game):
        """The installed ISO moved: ask where it is now (a terminal only) and let game_profile.py --relink
        accept it (the same file only). Returns the ISO to start; raises when it stays missing."""
        missing = LaunchError(MISSING_FILE.format(path=game), 'TTM-PLAY-22', EXIT_REFUSED, game)
        if not (self.root/'game-profile.json').is_file() or not _isatty(sys.stdin) or self.silenced:
            raise missing
        settings = self.settings_values()
        what, why, fix = explanation('TTM-PLAY-22', settings)
        for line in render_block('TTM-PLAY-22', what, why, fix, file=game, language=self.language()):
            self.say(line, YELLOW)
        try:
            answer = input(translate(RELINK_PROMPT, settings)).strip().strip('"')
        except (EOFError, OSError, ValueError):
            answer = ''
        if not answer:
            raise missing
        result = self.run_python(self.tools/'game_profile.py', '--relink', answer, stdin=subprocess.DEVNULL)
        # game_profile.py has printed its own block: 2 = another file (TTM-PLAY-44), 1 = the path cannot be read.
        if result.returncode == 2:
            raise LaunchError(f'Not the installed game ISO: {answer}', 'TTM-PLAY-44', EXIT_REFUSED, answer, explained=True)
        if result.returncode:
            raise LaunchError(MISSING_FILE.format(path=answer), 'TTM-PLAY-22', EXIT_REFUSED, answer, explained=True)
        return Path(answer)

    def language(self):
        return 'es' if self.settings_values().get('language') == 'es' else 'en'

    def emulator_version(self):
        version = recorded_version(self.root, self.emulator_path)
        if version is None:
            version = windows_file_version(self.emulator_path) if WINDOWS else appimage_version(self.emulator_path)
        return version

    def running_emulators(self):
        """Other PCSX2 processes, or else a live PINE server on this launch's socket (connect probe)."""
        found = other_emulators()
        if not found and pine_in_use(self.socket, PINE_SLOT):
            found = [PINE_SERVER.format(where=self.socket or 'port ' + str(PINE_SLOT))]
        return found

    def probe_python(self):
        """The first check of launch-autopilot.ps1's interpreter probe: fail before opening a game.
        autopilot.py --check exits 3 for the mod settings file and 4 for game files: this Python works then."""
        broken = 'TTM-PLAY-25' if sys.prefix != sys.base_prefix else 'TTM-PLAY-26'
        try:
            result = self.run_python(self.tools/'autopilot.py', '--check', capture_output=True)
        except OSError as error:
            raise LaunchError(NO_PYTHON.format(detail=f'{self.python}: {error}'), broken, EXIT_REFUSED) from error
        output = _decode(result.stdout + result.stderr)
        if result.returncode:
            lines = [line for line in output.splitlines() if line.strip()]
            if result.returncode in (3, 4):
                raise LaunchError('\n'.join(lines[-8:]) or 'autopilot.py --check failed',
                                  'TTM-PLAY-27' if result.returncode == 3 else 'TTM-PLAY-28', EXIT_REFUSED,
                                  self.root/'mod-settings.json' if result.returncode == 3 else None)
            detail = f'{self.python}: ' + ' '.join(lines)
            if 'No module named' in output and sys.prefix != sys.base_prefix:
                detail += MISSING_PACKAGES
            # This Python ran (it printed its check or a traceback): its base Python is fine, a package is not.
            ran = 'CHECK FAILED' in output or 'Traceback (most recent call last)' in output
            why = VENV_PACKAGES if broken == 'TTM-PLAY-25' and ran else None
            raise LaunchError(NO_PYTHON.format(detail=detail), broken, EXIT_REFUSED, why=why)
        self.python_ready = True
        for line in output.splitlines():
            if line.strip() and not line.startswith('Autopilot dependencies ready'):
                self.say(line)  # e.g. whether three/four-player input is available here

    def select_iso(self):
        result = self.run_python(self.tools/'map_scale_launch.py', '--json', stdout=subprocess.PIPE, stderr=self.inherited())
        if result.returncode == 4:
            # map_scale_launch.py printed the TTM-PLAY-46 block: the chosen disc's files failed their check.
            raise LaunchError(self.disc_unusable(), 'TTM-PLAY-46', EXIT_REFUSED, explained=True)
        if result.returncode == 2:
            raise LaunchError('The installed game ISO failed its check; see the message above.', 'TTM-PLAY-23', EXIT_REFUSED)
        if result.returncode:
            raise LaunchError(MAP_FAILED, 'TTM-PLAY-39')
        lines = [line for line in _decode(result.stdout).splitlines() if line.strip()]
        game = None
        if lines:
            try:
                game = Path(json.loads(lines[-1]))
            except (ValueError, TypeError):
                game = Path(lines[-1].strip())  # an older map_scale_launch.py prints the bare path
        if game is None or not game.is_file():
            raise LaunchError(ISO_MISSING.format(path=game or ''), 'TTM-PLAY-22', EXIT_REFUSED, game)
        return game

    def hints(self):
        for line in hint_lines(self.root, self.logs, self.manual_pause, disc=self.disc_title):
            self.say(line)

    def run(self):
        """Exit status: 0 played (closing PCSX2 is normal, and so is closing the terminal after startup),
        1 startup error or PCSX2 crash (also saved to launch-error-*.log), 2 refused (another PCSX2, a missing
        file or ISO, a broken private Python), 3 the session ended after an error, 128+N stopped by signal N."""
        previous = self.install_signals()
        try:
            try:
                outcome = self._play()
            finally:
                # Only the outcome is reported from here on: a signal now is deferred, never a stray
                # Stopped/Detached traceback out of the handlers below.
                self.cleaning = True
            return outcome or 0
        except Refused as refusal:
            if not getattr(refusal, 'shown', False):
                self.explain(refusal, YELLOW)
            return EXIT_REFUSED
        except Detached:
            return 0
        except Stopped as stop:
            self.say('The launcher was stopped.', YELLOW, error=True)
            return 128 + stop.signum
        except Exception as error:
            saved = self.write_failure(error)
            code = getattr(error, 'exit', 1) if isinstance(error, LaunchError) else 1
            if not getattr(error, 'explained', False):
                self.explain(error, YELLOW if code == EXIT_REFUSED else RED, saved)
            if saved:
                self.say(f'The full error is saved in {saved}', RED, error=True)
            return code
        finally:
            self.restore_signals(previous)

    def explain(self, error, color, saved=None):
        """One block: what happened, why, how to fix it, with the raw message as unwrapped detail lines."""
        code = getattr(error, 'code', 'TTM-PLAY-40') if isinstance(error, (LaunchError, Refused)) else 'TTM-PLAY-40'
        what, why, fix = explanation(code, self.settings_values())
        if getattr(error, 'why', None):
            why = translate(error.why, self.settings_values())
        # Only a refusal changed nothing: a startup failure (PCSX2 started and stopped, display settings
        # applied, a log folder made) did.
        refused = isinstance(error, (LaunchError, Refused)) and getattr(error, 'exit', 1) == EXIT_REFUSED
        for line in render_block(code, what, why, fix, file=getattr(error, 'file', None),
                                 detail_lines=str(error).splitlines(), log=saved,
                                 nothing_changed=refused and not self.startup_complete,
                                 language=self.language()):
            self.say(line, color, error=True)

    def session_outcome(self, watcher_code):
        """After PCSX2 closed: 3 with a summary when the session ended after an error, else 0."""
        status = {}
        try:
            status = atomic_files.read_json(self.logs/'status.json')
        except (OSError, ValueError):
            pass
        last = status.get('last_error') if isinstance(status, dict) else None
        settings = self.settings_values()
        if isinstance(last, dict) and not last.get('recovered'):
            self.say(translate(SESSION_ENDED, settings), RED, error=True)
            for line in render_block(str(last.get('code') or 'TTM-PLAY-38'), str(last.get('what') or ''),
                                     str(last.get('cause') or ''), str(last.get('action') or ''),
                                     report=last.get('report'), log=self.logs, details=str(last.get('detail') or ''),
                                     language=self.language()):
                self.say(line, RED, error=True)
            return EXIT_SESSION_ERROR
        if watcher_code:
            what, why, fix = explanation('TTM-PLAY-37', settings)
            for line in render_block('TTM-PLAY-37', what, why, fix, details=f'Helper exit status: {watcher_code}',
                                     file=self.logs/'errors.log', log=self.logs, language=self.language()):
                self.say(line, RED, error=True)
            return EXIT_SESSION_ERROR
        if isinstance(last, dict):
            self.say(translate(RECOVERED_SESSION, settings), YELLOW)
            if last.get('report'):
                self.say(str(last['report']), YELLOW)
        return 0

    def write_failure(self, error):
        """Write-Bt3LaunchFailure: the console showing an error may close on a key press; keep it on disk."""
        directory = self.logs or self.root/'analysis'/'autopilot'
        try:
            directory.mkdir(parents=True, exist_ok=True)
            now = datetime.now()
            path = directory/f'launch-error-{now:%Y%m%d-%H%M%S}.log'
            text = '\n'.join((now.astimezone().isoformat(), str(error),
                              ''.join(traceback.format_exception(error)).rstrip())) + '\n'
            path.write_text(text, encoding='utf-8')
            return path
        except OSError:
            return None

    def _play(self):
        self.check_environment()
        runtime = self.root/self.profile
        self.emulator_path = runtime_profile.executable(runtime)
        config = runtime_profile.data_directory(runtime)/'inis'/'PCSX2.ini'
        # The game disc is resolved under the lease (game_iso), and its ISO checked after the Python probe, where a
        # moved ISO can be found again.
        for path in (self.emulator_path, config, self.tools/'autopilot.py', self.tools/'presentation_settings.py',
                     self.tools/'pcsx2_versions.json', runtime/'portable.ini'):
            if not path.is_file():
                raise LaunchError(MISSING_FILE.format(path=path), 'TTM-PLAY-24', EXIT_REFUSED, path)
        if not WINDOWS and not os.access(self.emulator_path, os.X_OK):
            raise LaunchError(NOT_EXECUTABLE.format(path=self.emulator_path), 'TTM-PLAY-24', EXIT_REFUSED, self.emulator_path)
        problem, notice = version_problem(self.emulator_version(), self.profile)
        if problem:
            raise LaunchError(problem, 'TTM-PLAY-29', EXIT_REFUSED, self.emulator_path)
        if notice:
            self.say(notice, YELLOW)
        check_configuration(config.read_bytes().decode('utf-8-sig', 'replace'))
        found = self.running_emulators()
        if found:
            port = all(item.startswith(PINE_SERVER.split('{')[0]) for item in found)   # no PCSX2, only the port
            raise Refused(CLOSE_EMULATOR + ' Found: ' + ', '.join(found), 'TTM-PLAY-21' if port else 'TTM-PLAY-20')
        # Serialize the entire launch, from the choice of the game disc (Mod settings > Game disc switches only while
        # no Play holds this lease) to the interval before PINE listens. Every refusal below releases it.
        self.lease = Lease(self.root/'analysis'/'autopilot'/'.launcher.lock', self.lease_timeout).acquire()
        watcher_code = None
        try:
            game = self.game_iso()
            self.probe_python()
            if self.where_failure is not None:
                raise LaunchError(self.where_failure)
            if not game.is_file():
                game = self.relink(game)
            if self.bt4:
                result = self.run_python(self.tools/'bt4_preflight.py', stdout=self.inherited(), stderr=self.inherited())
                if result.returncode:
                    raise LaunchError(BT4_FAILED, 'TTM-PLAY-28')
            game = self.select_iso()
            self.logs = self.root/'analysis'/'autopilot'/f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}'
            self.logs.mkdir(parents=True, exist_ok=True)
            self.hints()
            try:
                watcher_code = self._start(game)
            except Detached:
                self.detached = True
                raise
            except Exception as error:
                self.say(f'AUTOMATIC PREPARATION ERROR: {error}', RED, error=True)
                self.show_errors()
                error.shown = True
                raise
            finally:
                self.cleaning = True
                if not self.detached:
                    self.clean_up()
        finally:
            self.lease.release()
            if self.worker is not None:
                self.worker.close()
        code = self.emulator.returncode if self.emulator is not None else None
        if crash_status(code):
            what, why, fix = explanation('TTM-PLAY-36', self.settings_values())
            status = f'0x{code & 0xFFFFFFFF:08X}' if WINDOWS else f'signal {-code}'
            for line in render_block('TTM-PLAY-36', what, why, fix, details=f'PCSX2 exit status: {status}',
                                     file=self.logs/'emulator.log', log=self.logs, language=self.language()):
                self.say(line, RED, error=True)
            return 1
        return self.session_outcome(watcher_code)

    def _start(self, game):
        if self.running_emulators():
            raise LaunchError(EMULATOR_APPEARED, 'TTM-PLAY-41', EXIT_REFUSED)
        presentation = self.tools/'presentation_settings.py'
        self.run_step('storage', 'Could not check generated-file retention.', self.tools/'player_storage.py')
        self.run_step('boot-hooks', 'Could not install the isolated in-game loading screen.',
                      self.tools/'install_boot_hooks.py')
        self.run_step('display', 'Could not prepare the isolated display settings.', presentation, 'apply')
        with open(self.logs/'emulator.log', 'ab') as log, self.critical():
            # PCSX2's console output goes to the log, not over the watcher's messages.
            self.emulator = self.spawn(self.emulator_command(game), log, subprocess.STDOUT,
                                       cwd=self.root/self.profile)
        pid = self.emulator.pid
        # This independent watchdog survives a closed launcher and restores the temporary display/startup keys
        # after PCSX2 has written its settings; the start time stops it from waiting for a reused PID.
        watch = [self.python, presentation, 'watch', '--pid', pid]
        started = process_start_time(pid)
        if started is not None:
            watch += ['--start-time', repr(started)]
        with open(self.logs/'settings-watchdog.log', 'ab') as log, self.critical():
            self.watchdog = self.spawn(watch, log, subprocess.STDOUT)
        token = uuid.uuid4().hex
        status_path = self.logs/'status.json'
        arguments = [self.python, '-u', self.tools/'autopilot.py', '--mode', self.mode, '--status-file', status_path,
                     '--emulator-pid', pid, '--launcher-token', token]
        if self.manual_pause or not WINDOWS:
            arguments.append('--manual-pause')
        if self.no_loading_screen:
            arguments.append('--no-loading-screen')
        errors_path = self.logs/'errors.log'
        with open(self.logs/'watcher.log', 'wb') as output, open(errors_path, 'wb') as errors, self.critical():
            self.watcher = self.spawn(arguments, output, errors)
        self.await_controller(token, status_path, errors_path)
        self.startup_complete = True
        failed = None
        while not self.emulator.exited():
            self.echo_new()
            if self.watcher.exited() and failed is None:
                if self.emulator.exited():
                    break
                failed = self.watcher.returncode
                self.say(translate(WATCHER_STOPPED, self.settings_values(), code=failed, logs=self.logs,
                                   play=names()['play']), RED, error=True)
                self.show_errors()
            time.sleep(self.follow_poll)
        code = self.emulator.returncode
        if code and not crash_status(code):
            self.say(f'PCSX2 closed with exit status {code}; its output is in {self.logs/"emulator.log"}.', YELLOW)
        return failed

    def await_controller(self, token, status_path, errors_path):
        deadline = time.monotonic() + self.ready_timeout
        ready = False
        while True:
            if self.emulator.exited():
                break
            if self.watcher.exited():
                raise LaunchError(NOT_STARTED.format(path=errors_path), 'TTM-PLAY-33', file=errors_path)
            if status_path.exists():
                try:
                    status = atomic_files.read_json(status_path)
                    ready = controller_ready(status, token, self.emulator.pid)
                    if ready and status['pid'] != self.watcher.pid:
                        # A Windows venv python.exe is a redirector: retain the authenticated worker too, so
                        # forced clean-up cannot orphan it.
                        if self.worker is None:
                            self.worker = OwnedPid(status['pid'])
                        ready = self.worker.pid == status['pid'] and not self.worker.exited()
                except (OSError, ValueError):
                    ready = False
            if ready or time.monotonic() >= deadline:
                break
            time.sleep(self.ready_poll)
        if not ready and not self.emulator.exited():
            raise LaunchError(NOT_CONFIRMED, 'TTM-PLAY-34')
        if not ready:
            code = self.emulator.returncode
            problem = startup_failure(code, '\n'.join(tail(self.logs/'emulator.log', 200)))
            if problem:
                # A crash (exception code or fatal signal) with no more specific diagnosis is TTM-PLAY-36.
                crashed = crash_status(code) and problem.startswith(EARLY_EXIT.split('{')[0])
                raise LaunchError(problem, 'TTM-PLAY-36' if crashed else 'TTM-PLAY-35', file=self.logs/'emulator.log')

    def clean_up(self):
        """The finally block of launch-autopilot.ps1, in the same order."""
        if not self.startup_complete and self.emulator is not None and not self.emulator.exited():
            self.stop_emulator()
        stop_owned(self.worker, self.helper_grace)
        stop_owned(self.watcher, self.helper_grace)
        self.echo_new(final=True)
        if self.emulator is None:
            if self.python_ready:
                self.restore_display()
        elif self.watchdog is None:
            self.say('Waiting for the emulator to close before restoring display settings.')
            self.emulator.wait(None)
            self.restore_display()
        elif self.emulator.exited():
            stop_owned(self.watchdog, self.helper_grace)
            self.restore_display()


def _isatty(stream):
    try:
        return stream.isatty()
    except (AttributeError, ValueError, OSError):
        return False


# ---- settings ---------------------------------------------------------------------------------------------

DIALOGS = (('zenity', '--error', '--no-markup', '--title={title}', '--text={message}'),
           ('kdialog', '--title', '{title}', '--error', '{message}'),
           ('xmessage', '-center', '{title}: {message}'),
           ('notify-send', '{title}', '{message}'))


def _tk_error(message, title):
    try:
        import tkinter
        from tkinter import messagebox
        window = tkinter.Tk()
        window.withdraw()
        try:
            messagebox.showerror(title, message, parent=window)
        finally:
            window.destroy()
        return True
    except Exception:
        return False


def show_error(message, title=SETTINGS_TITLE, environ=None):
    """Report a settings failure where the player sees it: stderr, and a dialog when no terminal shows stderr."""
    environ = os.environ if environ is None else environ
    try:
        print(message, file=sys.stderr, flush=True)
    except (OSError, ValueError, AttributeError):
        pass
    if not WINDOWS:
        if _isatty(sys.stderr):
            return 'terminal'
        if not (environ.get('DISPLAY') or environ.get('WAYLAND_DISPLAY')):
            return None
    if _tk_error(message, title):
        return 'tk'
    if WINDOWS:
        return None
    for command in DIALOGS:
        if shutil.which(command[0], path=environ.get('PATH')) is None:
            continue
        try:
            result = subprocess.run([part.format(title=title, message=message) for part in command], env=dict(environ),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
        if result.returncode == 0:
            return command[0]
    return None


def settings(root=ROOT, validate_only=False, python=None, report=show_error):
    """launch-settings.ps1: probe mod_settings.py --check, then run --ui with its logs in analysis/settings."""
    root = Path(root)
    python = python or sys.executable
    script = root/'tools'/'mod_settings.py'
    options = dict(cwd=str(root), stdin=subprocess.DEVNULL)
    if WINDOWS:
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        # Each refusal names its code, like Play (a broken private Python is TTM-PLAY-25 there too). Square
        # brackets in the path (TTM-PLAY-45) matter only to the PowerShell launchers, not here.
        problem = venv_problem()
        if problem:
            raise LaunchError(problem, 'TTM-PLAY-25', EXIT_REFUSED)
        if not script.is_file():
            raise LaunchError(SETTINGS_MISSING.format(path=script), 'TTM-PLAY-24', EXIT_REFUSED)
        try:
            probe = subprocess.run([python, str(script), '--check'], capture_output=True, **options)
            output = _decode(probe.stdout + probe.stderr)
            code = probe.returncode
        except OSError as error:
            output, code = str(error), None
        if code != 0:
            detail = f'{python}: ' + ' '.join(line for line in output.splitlines() if line.strip())
            if 'tkinter' in output.lower() or '_tkinter' in output:
                detail += TK_HINT
            raise LaunchError(SETTINGS_NO_TK.format(detail=detail), 'TTM-PLAY-43')
        if validate_only:
            print(f'Settings validation passed: {python}. No window was opened.', flush=True)
            return 0
        logs = root/'analysis'/'settings'
        logs.mkdir(parents=True, exist_ok=True)
        token = f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}'
        with open(logs/f'{token}.log', 'wb') as output_log, open(logs/f'{token}-errors.log', 'wb') as error_log:
            code = subprocess.run([python, '-u', str(script), '--ui'], stdout=output_log, stderr=error_log,
                                  **options).returncode
        if code != 0:
            raise LaunchError(SETTINGS_FAILED.format(logs=logs), 'TTM-PLAY-42')
        return 0
    except Exception as error:
        # The dialog names the code, as the Play blocks do.
        coded = getattr(error, 'code', None) if isinstance(error, LaunchError) else None
        message = f'[{coded}] {error}' if coded and coded != 'TTM-PLAY-40' else str(error)
        if validate_only:
            print(message, file=sys.stderr, flush=True)
            return 1
        report(message)
        return EXIT_REPORTED


# ---- command line -----------------------------------------------------------------------------------------

def parser():
    result = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = result.add_subparsers(dest='command', required=True)
    play = commands.add_parser('play', help='Start the modded game (launch-autopilot.ps1)')
    play.add_argument('--mode', choices=MODES, default='Original')
    play.add_argument('--manual-pause', action='store_true', help='Never send PCSX2 its pause key (always so off Windows)')
    play.add_argument('--no-loading-screen', action='store_true', help='Diagnostic console-only preparation')
    play.add_argument('--runtime-profile', choices=PROFILES, default='runtime128' if WINDOWS else 'runtime28')
    options = commands.add_parser('settings', help='Open Mod Settings (launch-settings.ps1)')
    options.add_argument('--validate-only', action='store_true', help='Check the settings dependencies; open no window')
    hints = commands.add_parser('hints', help='Print the launch hints in the saved language (launch-autopilot.ps1)')
    hints.add_argument('--logs', default='', help='The log folder the hints name')
    hints.add_argument('--manual-pause', action='store_true')
    hints.add_argument('--disc', default='', help='The title of the game disc this session starts')
    entry = commands.add_parser('entry', help="Print one of this installation's launcher names (launch-autopilot.ps1)")
    entry.add_argument('name', help='play, mod_settings, check_installation, install ...')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # Spanish explanations and player paths must never crash a console with another code page.
        try:
            stream.reconfigure(errors='backslashreplace')
        except (AttributeError, ValueError, OSError):
            pass
    if args.command == 'hints':
        for line in hint_lines(ROOT, args.logs, args.manual_pause, disc=args.disc or None):
            print(line, flush=True)
        return 0
    if args.command == 'entry':
        print(names().get(args.name, ''), flush=True)
        return 0
    if sys.version_info < (3, 11):
        message = f'Python 3.11 or later is required; {sys.executable} is Python {sys.version.split()[0]}.'
        if args.command == 'settings':
            show_error(message)
            return EXIT_REPORTED
        print(message, file=sys.stderr)
        return 1
    if args.command == 'settings':
        return settings(validate_only=args.validate_only)
    return Launcher(profile=args.runtime_profile, mode=args.mode, manual_pause=args.manual_pause,
                    no_loading_screen=args.no_loading_screen).run()


if __name__ == '__main__':
    raise SystemExit(main())
