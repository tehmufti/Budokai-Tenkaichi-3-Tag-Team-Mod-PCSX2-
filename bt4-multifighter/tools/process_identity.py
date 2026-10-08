"""Which process is this installation's PCSX2, and OS file locks, without loading the game's addresses.

Standard library plus psutil (imported when used). runtime_owner re-exports same_file and appimage_process; the Game
disc backend (disc_library.py) uses this module so that checking "is Play or PCSX2 running?" never imports
native_map, which resolves the chosen game disc and would fail on exactly the damaged choice it is meant to repair.
"""
import os
from pathlib import Path

WINDOWS = os.name == 'nt'


def same_file(first, second):
    try:
        return Path(first).resolve() == Path(second).resolve() or os.path.samefile(first, second)
    except (OSError, TypeError, ValueError):
        return False


def appimage_process(process, executable):
    """Linux: the launched PID runs the runtime's AppImage, then (same PID) PCSX2 from its mount.

    Before the AppImage runtime execs AppRun, /proc/<pid>/exe is the AppImage itself. Afterwards
    it is /tmp/.mount_*/usr/bin/pcsx2-qt, and the runtime's APPIMAGE variable names the file.
    """
    import psutil
    try:
        exe = process.exe()
        if exe and same_file(exe, executable):
            return True
        if os.path.basename(exe) != 'pcsx2-qt':
            return False
        return same_file(process.environ().get('APPIMAGE'), executable)
    except psutil.AccessDenied:  # another user's process is never ours (an exited one: EmulatorClosed)
        return False


def running_emulators(executable, windows=None):
    """The PIDs of running processes that are this installation's PCSX2 (the executable path, or on Linux the
    AppImage named by the process). [] when psutil is missing."""
    windows = WINDOWS if windows is None else windows
    try:
        import psutil
    except ImportError:
        return []
    found = []
    for process in psutil.process_iter(['name']):
        try:
            name = str(process.info.get('name') or '').lower()
            if 'pcsx2' not in name:
                continue
            if windows:
                if same_file(process.exe(), executable):
                    found.append(process.pid)
            elif appimage_process(process, executable):
                found.append(process.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return found


def alive(pid, started=None):
    """Whether process `pid` still runs (and, given its start time, is the same process, not a reused PID)."""
    try:
        import psutil
        process = psutil.Process(int(pid))
        return process.is_running() and (started is None or abs(process.create_time() - float(started)) < 1.0)
    except ImportError:
        return True     # unknown: never treat a folder in use as abandoned
    except Exception:   # noqa: BLE001 - NoSuchProcess, AccessDenied, a damaged record
        return False


def started(pid=None):
    """The start time of a process (this one by default), or None."""
    try:
        import psutil
        return psutil.Process(pid or os.getpid()).create_time()
    except Exception:  # noqa: BLE001
        return None


class FileLock:
    """An OS lock on byte 0 of a file (msvcrt on Windows, flock elsewhere); the operating system releases it when
    the holder dies. The same primitive as play_launcher.Lease and fresh_team_trainer.acquire_lock, so it excludes
    them and they exclude it. Windows PowerShell's launcher lease (FileShare.None) counts as held too."""

    def __init__(self, path):
        self.path, self.fd = Path(path), None

    def acquire(self, create=True):
        """True when this process now holds the lock; False when another holder has it (or, with create=False, when
        the file does not exist: nobody holds it then, and nothing is created)."""
        flags = os.O_RDWR | (os.O_CREAT if create else 0)
        if WINDOWS:
            import msvcrt
            try:
                descriptor = os.open(self.path, flags | os.O_BINARY | os.O_NOINHERIT)
            except FileNotFoundError:
                if create:
                    raise
                return False
            except PermissionError:
                return False
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError:
                os.close(descriptor)
                return False
        else:
            import fcntl
            try:
                descriptor = os.open(self.path, flags | os.O_CLOEXEC, 0o644)
            except FileNotFoundError:
                if create:
                    raise
                return False
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(descriptor)
                return False
        self.fd = descriptor
        return True

    def release(self):
        if self.fd is not None:
            try:
                if WINDOWS:
                    import msvcrt
                    try:
                        os.lseek(self.fd, 0, os.SEEK_SET)
                        msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
            finally:
                os.close(self.fd)
                self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


def held(path):
    """Whether another process holds the lock on `path`. A missing file is free, and probing creates nothing."""
    lock = FileLock(path)
    if not Path(path).exists():
        return False
    if lock.acquire(create=False):
        lock.release()
        return False
    return Path(path).exists()
