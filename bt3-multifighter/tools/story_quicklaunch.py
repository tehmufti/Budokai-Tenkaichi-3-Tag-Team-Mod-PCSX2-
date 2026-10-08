"""Workbench "Test this mission": start the game straight into one mission.

The Workbench writes a one-shot request (a complete, checksummed copy of the
document) and starts this tree's ordinary Play launcher. The watcher of that
session turns the request into exactly the launch that choosing the mission in
Modded Scenarios performs: the Modded Modes page opens by itself on the main
menu, the mission is armed and its roster, arena and music are published
through the native selectors. No emulator state is loaded and no controller
input is synthesized. The request expires, so a forgotten test never takes
over a later ordinary session.
"""
import os
import subprocess
import time
from pathlib import Path

import atomic_files
import story_missions as missions

ROOT = Path(__file__).resolve().parents[1]
REQUEST = missions.QUICK
LIFETIME = 15 * 60  # seconds from the Workbench click to the main menu
# Player and developer folders share the same ordinary Play entry point.
LAUNCHERS = ('Play.cmd',) if os.name == 'nt' else ('Play.sh',)
CLEAN = ('PYTHONHOME', 'PYTHONPATH', 'TAGTEAM_DISC', 'TAGTEAM_ADAPTER')


def request(document, path=None, now=None, cpu_only=False):
    """Validate and queue `document` for the next main menu; returns the stored copy.

    cpu_only selects the browser's CPU Only variant (every fighter, including Player 1's, stays a CPU)."""
    d = missions.validate(document)
    path = Path(path or REQUEST)
    with missions.queue_lock(path):
        atomic_files.write_json(path, {'sha256': missions.digest(d), 'requested': time.time() if now is None else now,
                                       'cpu_only': bool(cpu_only), 'mission': d})
    return d


def pending(path=None, now=None):
    """(mission, cpu_only) of the request, or None. Expired or damaged requests are removed."""
    path = Path(path or REQUEST)
    try:
        data = atomic_files.read_json(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        clear(path)
        return None
    try:
        d = missions.validate(data['mission'])
        missions.require(data['sha256'] == missions.digest(d), 'Quick launch checksum mismatch')
        age = (time.time() if now is None else now) - float(data['requested'])
        missions.require(-60 <= age <= LIFETIME, 'Quick launch request expired')
        cpu_only = data.get('cpu_only', False)
        missions.require(type(cpu_only) is bool, 'Quick launch mode must be boolean')
    except (KeyError, TypeError, ValueError):
        clear(path)
        return None
    return d, cpu_only


def taken(document, path=None):
    """Remove the request once its launch started (only if it still names `document`)."""
    path = Path(path or REQUEST)
    with missions.queue_lock(path):
        try:
            current = atomic_files.read_json(path).get('mission')
            same = current is not None and missions.digest(current) == missions.digest(document)
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, AttributeError):
            same = True
        if same:
            atomic_files.unlink(path)


def clear(path=None):
    path = Path(path or REQUEST)
    try:
        with missions.queue_lock(path):
            atomic_files.unlink(path)
    except (OSError, TimeoutError):
        pass


def launcher(root=ROOT):
    for name in LAUNCHERS:
        if (Path(root) / name).is_file():
            return Path(root) / name
    raise FileNotFoundError('No Play launcher found in ' + str(root))


def game_running():
    """True while this tree's PINE port answers (its game is already running)."""
    import play_launcher
    return play_launcher.pine_in_use()


def start(root=ROOT, popen=subprocess.Popen):
    """Open this tree's ordinary Play launcher in its own console window."""
    path = launcher(root)
    env = {k: v for k, v in os.environ.items() if k not in CLEAN}
    if os.name == 'nt':
        return popen(['cmd.exe', '/d', '/c', str(path)], cwd=str(path.parent), env=env,
                     creationflags=subprocess.CREATE_NEW_CONSOLE)
    return popen(['sh', str(path)], cwd=str(path.parent), env=env, start_new_session=True)
