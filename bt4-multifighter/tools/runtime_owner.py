"""One host controller, bound to one emulator lifetime, never a replacement PID."""
import runtime_profile
import os
from pathlib import Path
import time
import psutil

from fresh_team_trainer import acquire_lock
# The process identity helpers live in process_identity (no game addresses): the Game disc backend uses them too.
from process_identity import same_file, appimage_process  # noqa: F401 - re-exported

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = runtime_profile.EXECUTABLE
WINDOWS = os.name == 'nt'
LOCK = ROOT/'analysis/autopilot/.owner.lock'


class EmulatorClosed(RuntimeError):
    pass


def claim(path=LOCK, timeout=3):
    """Crash-released OS lock, acquired before any presentation or PINE access."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic()+timeout
    while True:
        try:
            return acquire_lock(path)
        except ValueError:
            if time.monotonic() >= deadline:
                raise ValueError('Another automatic match controller is already running. '
                                 'Close its emulator before starting another launcher.') from None
            # An immediately relaunched emulator may overlap the old watcher's
            # bounded cleanup. Wait only for its OS lease, with no PINE access.
            time.sleep(.05)


class EmulatorLifetime:
    def __init__(self, pid, executable=EXECUTABLE):
        try:
            self.process = psutil.Process(pid)
            if WINDOWS:
                if Path(self.process.exe()).resolve() != Path(executable).resolve():
                    raise ValueError('The watcher requires its own isolated emulator process')
            elif not appimage_process(self.process, executable):
                raise ValueError('The watcher requires its own isolated emulator process')
            self.created = self.process.create_time()
        except psutil.NoSuchProcess:
            raise EmulatorClosed('PCSX2 was closed') from None
        # PINE's Unix-socket peer check compares the listener with this PID.
        self.pid = self.process.pid
        self.closed = False
        self.require_alive()

    def require_alive(self):
        # is_running compares process creation identity as well as PID. Once
        # lost, the lease is permanently revoked, even if Windows reuses PID.
        if not self.closed:
            try:
                self.closed = not self.process.is_running()
            except psutil.NoSuchProcess:
                self.closed = True
        if self.closed:
            raise EmulatorClosed("PCSX2 was closed; the mod's helper stops with it")

    def revoke(self):
        self.closed = True
