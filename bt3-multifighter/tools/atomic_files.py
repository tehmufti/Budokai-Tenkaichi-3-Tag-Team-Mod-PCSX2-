"""Small shared-file transport tolerant of Windows readers and concurrent writers.

Each write uses its own closed temporary file, then an atomic replacement.
Only Windows sharing/access failures are retried. Cooperating readers allow
delete sharing, while bounded retries cover ordinary external file readers.
"""
import ctypes
import json
import os
import tempfile
import threading
import time
from pathlib import Path

_locks = {}
_guard = threading.Lock()


def _lock(path):
    key = os.path.normcase(str(Path(path).resolve()))
    with _guard:
        return _locks.setdefault(key, threading.RLock())


def _retry(operation, timeout=2):
    deadline = time.monotonic()+timeout
    delay = .01
    while True:
        try: return operation()
        except OSError as error:
            transient = isinstance(error, PermissionError) or getattr(error, 'winerror', None) in (5, 32, 33)
            remaining = deadline-time.monotonic()
            if not transient or remaining <= 0: raise
            time.sleep(min(delay, remaining)); delay = min(.1, delay*1.5)


def read_bytes(path):
    """Read with FILE_SHARE_DELETE so our snapshots never block replacements."""
    if os.name != 'nt': return Path(path).read_bytes()
    import msvcrt
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                   w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateFileW(str(Path(path).resolve()), 0x80000000, 0x7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try: descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle); raise
    with os.fdopen(descriptor, 'rb') as stream:
        return stream.read()


def read_json(path):
    return json.loads(read_bytes(path).decode('utf-8-sig'))


def write_bytes(path, data, timeout=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock(path):
        descriptor, name = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'wb') as stream: stream.write(data)
            _retry(lambda: os.replace(temporary, path), timeout)
        finally:
            if temporary.exists(): temporary.unlink()


def write_json(path, data, timeout=2):
    write_bytes(path, (json.dumps(data, indent=2)+'\n').encode('utf-8'), timeout)


def unlink(path, timeout=2):
    path = Path(path)
    with _lock(path): _retry(lambda: path.unlink(missing_ok=True), timeout)
