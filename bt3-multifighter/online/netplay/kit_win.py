"""Windows helpers with the Python standard library only (ctypes): processes, the PINE listener's owner, the PCSX2
window (placement, key presses, front / minimise / taskbar flash), the lobby's always-on-top banner style, window
captures (PrintWindow, also on a hidden desktop), XInput controllers, the UI language and, for the kit's test mode,
hidden desktops.

Nothing here needs psutil or pywin32, so the kit runs on a plain python.org Python as well as on a Tag Team Mod
installation's private Python.
"""
import ctypes
import ctypes.wintypes as wt
import os
import queue
import socket
import struct
import subprocess
import threading

WINDOWS = os.name == 'nt'
CREATE_NO_WINDOW = 0x08000000
STILL_ACTIVE = 259

if WINDOWS:
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    iphlpapi = ctypes.WinDLL('iphlpapi', use_last_error=True)
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    user32.OpenDesktopW.restype = wt.HANDLE
    user32.OpenDesktopW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.BOOL, wt.DWORD]
    user32.CreateDesktopW.restype = wt.HANDLE
    user32.SetThreadDesktop.argtypes = [wt.HANDLE]
    user32.CloseDesktop.argtypes = [wt.HANDLE]
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.GetWindow.restype = wt.HWND
    user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetForegroundWindow.restype = wt.HWND
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.IsIconic.argtypes = [wt.HWND]
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    user32.FlashWindowEx.argtypes = [ctypes.c_void_p]
    user32.GetWindowDC.argtypes = [wt.HWND]
    user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
    ENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001 - older Windows: the window is placed in scaled pixels
        pass


# ---- processes -----------------------------------------------------------------------------------------------------------
def pid_alive(pid):
    """True while process `pid` runs."""
    if not pid:
        return False
    if not WINDOWS:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    handle = kernel32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wt.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_path(pid):
    """The executable path of process `pid` ('' when it cannot be read)."""
    if not WINDOWS or not pid:
        return ''
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return ''
    try:
        size = wt.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        return buffer.value if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else ''
    finally:
        kernel32.CloseHandle(handle)


def kill_tree(pid):
    """End process `pid` and its children (taskkill /T /F). Only ever called with PIDs this kit started."""
    if not pid or not pid_alive(pid):
        return False
    subprocess.run(['taskkill', '/PID', str(int(pid)), '/T', '/F'], capture_output=True,
                   creationflags=CREATE_NO_WINDOW if WINDOWS else 0)
    return True


class _BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wt.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wt.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ('r_ops', 'w_ops', 'o_ops', 'r_bytes', 'w_bytes', 'o_bytes')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IoCounters),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


_jobs = []


def kill_with_me(pid):
    """Put process `pid` in a job object that Windows ends when this kit process ends (closing the kit's console
    window then also closes its PCSX2). Best effort: returns False when Windows does not allow it."""
    if not WINDOWS or not pid:
        return False
    try:
        kernel32.CreateJobObjectW.restype = wt.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000                 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(wt.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(wt.HANDLE(job))
            return False
        process = kernel32.OpenProcess(0x0100 | 0x0001, False, int(pid))   # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not process:
            kernel32.CloseHandle(wt.HANDLE(job))
            return False
        ok = bool(kernel32.AssignProcessToJobObject(wt.HANDLE(job), wt.HANDLE(process)))
        kernel32.CloseHandle(process)
        if ok:
            _jobs.append(job)                                          # kept open for this process's lifetime
        else:
            kernel32.CloseHandle(wt.HANDLE(job))
        return ok
    except Exception:  # noqa: BLE001 - only a convenience
        return False


class _TcpRow(ctypes.Structure):
    _fields_ = [('state', wt.DWORD), ('local_addr', wt.DWORD), ('local_port', wt.DWORD), ('remote_addr', wt.DWORD),
                ('remote_port', wt.DWORD), ('pid', wt.DWORD)]


def tcp_listeners():
    """{port: pid} of every IPv4 TCP socket in the LISTEN state (GetExtendedTcpTable, TCP_TABLE_OWNER_PID_LISTENER)."""
    if not WINDOWS:
        return {}
    size = wt.DWORD(0)
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)
    for _ in range(4):
        buffer = ctypes.create_string_buffer(size.value + 4096)
        size = wt.DWORD(len(buffer))
        result = iphlpapi.GetExtendedTcpTable(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)
        if result == 0:
            break
        if result != 122:                                            # ERROR_INSUFFICIENT_BUFFER: try again
            return {}
    else:
        return {}
    count = struct.unpack_from('<I', buffer, 0)[0]
    rows = (_TcpRow * count).from_buffer_copy(buffer, 4) if count else []
    out = {}
    for row in rows:
        port = socket.ntohs(row.local_port & 0xFFFF)
        out.setdefault(port, row.pid)
    return out


def listener_pid(port):
    """PID of the process listening on TCP `port` (PINE), or None."""
    return tcp_listeners().get(int(port))


# ---- launching -----------------------------------------------------------------------------------------------------------
class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR), ('lpTitle', wt.LPWSTR),
                ('dwX', wt.DWORD), ('dwY', wt.DWORD), ('dwXSize', wt.DWORD), ('dwYSize', wt.DWORD),
                ('dwXCountChars', wt.DWORD), ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD),
                ('dwFlags', wt.DWORD), ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD),
                ('lpReserved2', ctypes.c_void_p), ('hStdInput', wt.HANDLE), ('hStdOutput', wt.HANDLE),
                ('hStdError', wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE), ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]


def launch(args, cwd, console, desktop=None, env=None):
    """Start `args` (stdin NUL, stdout and stderr into the file `console`); on `desktop` (a hidden desktop this call
    creates, test mode only) when given. Returns the PID."""
    if desktop is None or not WINDOWS:
        with open(console, 'wb') as out:
            process = subprocess.Popen([str(a) for a in args], cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=out,
                                       stderr=subprocess.STDOUT, env=env)
        return process.pid
    import msvcrt
    for fd in (0, 1, 2):                      # our own console/pipe handles must not leak into the emulator
        try:
            os.set_handle_inheritable(msvcrt.get_osfhandle(fd), False)
        except OSError:
            pass
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, 0x10000000, None)
    if not hdesk:
        raise OSError(ctypes.get_last_error(), 'CreateDesktopW failed')
    out = open(console, 'wb')
    null = open(os.devnull, 'rb')
    handles = []
    try:
        handles = [msvcrt.get_osfhandle(out.fileno()), msvcrt.get_osfhandle(null.fileno())]
        for handle in handles:
            os.set_handle_inheritable(handle, True)
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = desktop
        si.dwFlags = 0x100                                           # STARTF_USESTDHANDLES
        si.hStdInput, si.hStdOutput, si.hStdError = handles[1], handles[0], handles[0]
        pi = PROCESS_INFORMATION()
        environment = dict(env if env is not None else os.environ)
        block = ''.join(f'{k}={v}\0' for k, v in sorted(environment.items())) + '\0'
        command = subprocess.list2cmdline([str(a) for a in args])
        if not kernel32.CreateProcessW(None, ctypes.create_unicode_buffer(command), None, None, True, 0x00000400,
                                       ctypes.create_unicode_buffer(block), str(cwd), ctypes.byref(si),
                                       ctypes.byref(pi)):
            raise OSError(ctypes.get_last_error(), 'CreateProcessW failed')
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
        return pi.dwProcessId
    finally:
        for handle in handles:
            try:
                os.set_handle_inheritable(handle, False)
            except OSError:
                pass
        out.close()
        null.close()


# ---- windows -------------------------------------------------------------------------------------------------------------
class DesktopThread:
    """Window calls for a hidden desktop must come from a thread assigned to it; this thread is (one per desktop)."""
    _threads = {}
    _lock = threading.Lock()

    @classmethod
    def run(cls, desktop, fn, *args):
        if desktop is None:
            return fn(*args)
        with cls._lock:
            worker = cls._threads.get(desktop)
            if worker is None:
                worker = cls._threads[desktop] = cls(desktop)
        return worker.call(fn, *args)

    def __init__(self, desktop):
        self.desktop, self.jobs = desktop, queue.Queue()
        threading.Thread(target=self.loop, daemon=True, name=f'desktop-{desktop}').start()

    def loop(self):
        handle = user32.OpenDesktopW(self.desktop, 0, False, 0x10000000)
        ok = bool(handle) and bool(user32.SetThreadDesktop(handle))
        while True:
            fn, args, box, done = self.jobs.get()
            try:
                if not ok:
                    raise OSError(f'cannot attach to desktop {self.desktop}')
                box['value'] = fn(*args)
            except Exception as error:  # noqa: BLE001 - handed back to the caller
                box['error'] = error
            done.set()

    def call(self, fn, *args):
        box, done = {}, threading.Event()
        self.jobs.put((fn, args, box, done))
        done.wait(30)
        if 'error' in box:
            raise box['error']
        return box.get('value')


def _windows_of(pid, desktop):
    found = []

    def each(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, 256)
            if name.value.startswith('Qt'):
                r = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                found.append((hwnd, (r.left, r.top, r.right, r.bottom), not user32.GetWindow(hwnd, 4)))
        return True
    callback = ENUM(each)
    if desktop:
        handle = user32.OpenDesktopW(desktop, 0, False, 0x10000000)
        if handle:
            user32.EnumDesktopWindows(handle, callback, 0)
            user32.CloseDesktop(handle)
    else:
        user32.EnumWindows(callback, 0)
    found.sort(key=lambda w: -(w[1][2] - w[1][0]) * (w[1][3] - w[1][1]))
    return found


def windows_of(pid, desktop=None):
    """[(hwnd, rect, unowned)] of the visible Qt windows of process `pid`, largest first."""
    if not WINDOWS:
        return []
    return DesktopThread.run(desktop, _windows_of, pid, desktop)


def _post_key(pid, desktop, vk, scan, extended, down):
    lparam = 1 | (scan << 16) | (extended << 24) | (0 if down else 0xC0000000)
    hits = 0
    for hwnd, _, _ in _windows_of(pid, desktop):
        user32.PostMessageW(hwnd, 0x0100 if down else 0x0101, vk, lparam)
        hits += 1
    return hits


def post_key(pid, key, down, desktop=None):
    """WM_KEYDOWN / WM_KEYUP of key = (vk, scan, extended[, name]) to every window of `pid`. PCSX2 reads hotkeys
    (Space = pause, F8 = screenshot) and keyboard-bound pad buttons from these messages, focused or not."""
    vk, scan, extended = key[:3]
    return DesktopThread.run(desktop, _post_key, pid, desktop, vk, scan, extended, down)


def _place(pid, desktop, width_share, height_share):
    area = wt.RECT()
    user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)    # SPI_GETWORKAREA (primary screen)
    tops = [w for w in _windows_of(pid, desktop) if w[2]]
    if not tops:
        return None
    hwnd = tops[0][0]
    aw, ah = area.right - area.left, area.bottom - area.top
    height = int(ah * height_share)
    width = min(int(aw * width_share), height * 4 // 3)
    height = min(height, width * 3 // 4 + 40)
    x, y = area.left + (aw - width) // 2, area.top + (ah - height) // 2
    user32.ShowWindow(hwnd, 9)                                        # SW_RESTORE
    user32.SetWindowPos(hwnd, 0, x, y, width, height, 0x0004 | 0x0010)
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def place_window(pid, desktop=None, width_share=0.75, height_share=0.85):
    """Centre the game window on the primary screen at a 4:3 size (most of the screen height)."""
    if not WINDOWS:
        return None
    return DesktopThread.run(desktop, _place, pid, desktop, width_share, height_share)


_console_handlers = []


def on_console_close(fn):
    """Call fn() when the console window is closed (or Windows logs off / shuts down), so the other PC hears a
    goodbye instead of waiting. Ctrl+C keeps Python's own handling (KeyboardInterrupt)."""
    if not WINDOWS:
        return False
    HANDLER = ctypes.WINFUNCTYPE(wt.BOOL, wt.DWORD)

    def handler(kind):
        if kind in (2, 5, 6):                                         # CLOSE, LOGOFF, SHUTDOWN
            try:
                fn()
            except Exception:  # noqa: BLE001 - the process ends anyway
                pass
            return True
        return False
    callback = HANDLER(handler)
    _console_handlers.append(callback)
    return bool(kernel32.SetConsoleCtrlHandler(callback, True))


# ---- window choreography (kit 1.3.0) ---------------------------------------------------------------------------------
SW_MINIMIZE, SW_RESTORE, SW_SHOWNOACTIVATE = 6, 9, 4


def _main_window(pid, desktop):
    tops = [w for w in _windows_of(pid, desktop) if w[2]]
    return tops[0][0] if tops else None


def _front(pid, desktop):
    hwnd = _main_window(pid, desktop)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, SW_RESTORE)
    foreground = user32.GetForegroundWindow()
    mine = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached = bool(other) and other != mine and bool(user32.AttachThreadInput(other, mine, True))
    try:
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(other, mine, False)
    return ok


def bring_to_front(pid, desktop=None):
    """Restore the game window and give it the focus (a keyboard pad needs it). Best effort."""
    if not WINDOWS or not pid:
        return False
    try:
        return DesktopThread.run(desktop, _front, pid, desktop)
    except Exception:  # noqa: BLE001 - cosmetic
        return False


def _show(pid, desktop, how):
    hwnd = _main_window(pid, desktop)
    return bool(hwnd) and bool(user32.ShowWindow(hwnd, how) or True)


def minimise(pid, desktop=None):
    if not WINDOWS or not pid:
        return False
    try:
        return DesktopThread.run(desktop, _show, pid, desktop, SW_MINIMIZE)
    except Exception:  # noqa: BLE001
        return False


class FLASHWINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.UINT), ('hwnd', wt.HWND), ('dwFlags', wt.DWORD), ('uCount', wt.UINT),
                ('dwTimeout', wt.DWORD)]


def _flash(pid, desktop, count):
    hwnd = _main_window(pid, desktop)
    if not hwnd:
        return False
    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x2 | 0xC if count is None else 0x2, count or 0, 0)
    return bool(user32.FlashWindowEx(ctypes.byref(info)))


def flash(pid, desktop=None, count=3):
    """Flash the game window's taskbar button (count None: until it gets the focus)."""
    if not WINDOWS or not pid:
        return False
    try:
        return DesktopThread.run(desktop, _flash, pid, desktop, count)
    except Exception:  # noqa: BLE001
        return False


def _rect(pid, desktop):
    hwnd = _main_window(pid, desktop)
    if not hwnd:
        return None
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    iconic = bool(user32.IsIconic(hwnd))
    return dict(hwnd=int(hwnd), rect=(r.left, r.top, r.right, r.bottom), minimised=iconic)


def window_info(pid, desktop=None):
    """{hwnd, rect, minimised} of the game's main window (None when it has none)."""
    if not WINDOWS or not pid:
        return None
    try:
        return DesktopThread.run(desktop, _rect, pid, desktop)
    except Exception:  # noqa: BLE001
        return None


def overlay_style(hwnd):
    """The lobby's wait banner: always on top, never takes the focus, no taskbar button (WS_EX_TOPMOST |
    WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)."""
    if not WINDOWS:
        return False
    GWL_EXSTYLE = -20
    get = user32.GetWindowLongW
    get.restype = ctypes.c_long
    style = get(wt.HWND(hwnd), GWL_EXSTYLE)
    user32.SetWindowLongW(wt.HWND(hwnd), GWL_EXSTYLE, style | 0x08000000 | 0x80 | 0x8)
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
    return True


def capture_png(hwnd):
    """PNG bytes of a window's own picture (PrintWindow with PW_RENDERFULLCONTENT): works on a hidden desktop."""
    import zlib
    gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    rect = wt.RECT()
    user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    user32.GetWindowDC.restype = wt.HDC
    hdc = user32.GetWindowDC(wt.HWND(hwnd))
    gdi32.CreateCompatibleDC.restype = wt.HDC
    mem = gdi32.CreateCompatibleDC(wt.HDC(hdc))
    gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
    bmp = gdi32.CreateCompatibleBitmap(wt.HDC(hdc), w, h)
    gdi32.SelectObject(wt.HDC(mem), wt.HBITMAP(bmp))
    user32.PrintWindow(wt.HWND(hwnd), wt.HDC(mem), 2)
    header = struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(wt.HDC(mem), wt.HBITMAP(bmp), 0, h, buf, ctypes.c_char_p(header), 0)
    raw = buf.raw
    rows = []
    for y in range(h):
        line = bytearray(raw[y * w * 4:(y + 1) * w * 4])
        line[0::4], line[2::4] = line[2::4], line[0::4]
        line[3::4] = b'\xff' * w
        rows.append(b'\0' + bytes(line))
    gdi32.DeleteObject(wt.HBITMAP(bmp))
    gdi32.DeleteDC(wt.HDC(mem))
    user32.ReleaseDC(wt.HWND(hwnd), wt.HDC(hdc))
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows), 6)) + chunk(b'IEND', b''))


def capture_pid(pid, desktop=None):
    """(png bytes, rect) of a process's main window."""
    info = window_info(pid, desktop)
    if not info:
        return None, None
    try:
        return DesktopThread.run(desktop, capture_png, info['hwnd']), info['rect']
    except Exception:  # noqa: BLE001
        return None, info['rect']


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [('wButtons', wt.WORD), ('bLeftTrigger', ctypes.c_ubyte), ('bRightTrigger', ctypes.c_ubyte),
                ('sThumbLX', ctypes.c_short), ('sThumbLY', ctypes.c_short), ('sThumbRX', ctypes.c_short),
                ('sThumbRY', ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [('dwPacketNumber', wt.DWORD), ('Gamepad', XINPUT_GAMEPAD)]


_xinput = []


def xinput_pads():
    """[(index, pressed)] of the XInput controllers plugged in (pressed: any button or trigger held right now)."""
    if not WINDOWS:
        return []
    if not _xinput:
        for name in ('xinput1_4', 'xinput1_3', 'xinput9_1_0'):
            try:
                _xinput.append(ctypes.WinDLL(name))
                break
            except OSError:
                continue
        else:
            _xinput.append(None)
    lib = _xinput[0]
    if lib is None:
        return []
    out = []
    for index in range(4):
        state = XINPUT_STATE()
        if lib.XInputGetState(index, ctypes.byref(state)) == 0:
            g = state.Gamepad
            out.append((index, bool(g.wButtons or g.bLeftTrigger > 30 or g.bRightTrigger > 30)))
    return out


def ui_language():
    """'es' when Windows' display language is Spanish (primary language 0x0A), else 'en'."""
    if not WINDOWS:
        import locale
        try:
            return 'es' if (locale.getlocale()[0] or '').lower().startswith('es') else 'en'
        except (ValueError, TypeError):
            return 'en'
    try:
        lang = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return 'es' if lang & 0x3FF == 0x0A else 'en'
    except Exception:  # noqa: BLE001
        return 'en'


def lan_addresses():
    """(main, others): the IPv4 address of this PC's default route (the one a friend on the same network or a VPN
    peer usually needs) and the other usable addresses (VPN, virtual adapters); no loopback, no link-local."""
    found, main = set(), None
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:                                     # the address of the default route (no packet is sent by connect on UDP)
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(('10.255.255.255', 1))
        main = probe.getsockname()[0]
        probe.close()
    except OSError:
        pass
    usable = lambda a: a and not a.startswith(('127.', '169.254.', '0.'))
    others = sorted(a for a in found if usable(a) and a != main)
    return (main if usable(main) else (others.pop(0) if others else None)), others


# ---- the host's match-making copy: suspended while an online match runs (spec 6.9) ------------------------------------
if WINDOWS:
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
                    ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', ctypes.c_long), ('dwFlags', wt.DWORD),
                    ('szExeFile', ctypes.c_wchar * 260)]
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def process_children():
    """{parent pid: [child pids]} of every running process (Windows; {} elsewhere)."""
    if not WINDOWS:
        return {}
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)                 # TH32CS_SNAPPROCESS
    if not snap or snap == wt.HANDLE(-1).value:
        return {}
    out = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out


def process_tree(*roots):
    """The running PIDs of `roots` and all their descendants (roots first)."""
    children = process_children()
    out, todo = [], [r for r in roots if r]
    while todo:
        pid = todo.pop(0)
        if pid in out or not pid_alive(pid):
            continue
        out.append(pid)
        todo += children.get(pid, [])
    return out


def _suspend(pids, resume):
    ntdll = ctypes.WinDLL('ntdll')
    fn = ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess
    fn.argtypes = [wt.HANDLE]
    done = []
    for pid in pids:
        handle = kernel32.OpenProcess(0x0800, False, int(pid))      # PROCESS_SUSPEND_RESUME
        if not handle:
            continue
        try:
            if fn(handle) == 0:
                done.append(pid)
        finally:
            kernel32.CloseHandle(handle)
    return done


def suspend_pids(pids):
    """NtSuspendProcess each PID (only ever this kit's own preparation copy); returns the ones suspended."""
    return _suspend(pids, False) if WINDOWS else []


def resume_pids(pids):
    return _suspend(pids, True) if WINDOWS else []
