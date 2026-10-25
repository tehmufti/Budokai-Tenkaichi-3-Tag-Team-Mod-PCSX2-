"""Installed runtime paths and isolated preparation sockets on both platforms."""
import os
import socket
from pathlib import Path
WINDOWS = os.name == 'nt'


def data(root):
    from runtime_profile import data_directory
    return data_directory(Path(root) / 'game/runtime28', windows=WINDOWS)


def python(root):
    return Path(root) / '.venv' / ('Scripts/python.exe' if WINDOWS else 'bin/python')


def socket_path(slot):
    import pine
    return pine.socket_path(slot, environ={k: v for k, v in os.environ.items() if k != pine.SOCKET_ENV})


def owner(slot):
    import pine
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        try:
            connection.connect(socket_path(slot))
            return pine.peer_pid(connection)
        except OSError:
            return None


def client(slot, timeout=3, pid=None):
    import pine
    result = pine.PineClient(port=slot, timeout=timeout)
    if WINDOWS:
        return result
    # The playing client's socket override is process-wide. A concurrent
    # preparation must always use its own slot, without changing that override.
    result.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        result.sock.settimeout(timeout)
        result.sock.connect(socket_path(slot))
        if pid is not None and pine.peer_pid(result.sock) != pid:
            raise pine.PineError('The preparation socket belongs to another emulator')
    except BaseException:
        result.close()
        raise
    return result


def is_child_emulator(pid, parent, appimage):
    import psutil
    try:
        process = psutil.Process(pid)
        return (parent in [p.pid for p in process.parents()] and
                Path(process.environ().get('APPIMAGE', '')).resolve() == Path(appimage).resolve())
    except (OSError, psutil.Error):
        return False
