"""One deliberate loading cover over the isolated emulator, without taking focus.

The controller only exchanges JSON with an owned helper process. The helper
has no PINE client, keyboard injection or emulator-memory access. While a
loading cover (never a failure cover) is up it mutes only that emulator's audio
sessions, and unmutes them afterwards unless the player had muted the game
(loading_audio).
It disappears if the watcher dies, and follows the emulator's client bounds.
"""
import runtime_profile
import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from atomic_files import read_json, write_json
from character_names import character_info
from loading_design import mode_options

ROOT = Path(__file__).resolve().parents[1]
EMULATOR = runtime_profile.EXECUTABLE
# The desktop cover helper is Win32 (layered window, WASAPI mute). Elsewhere the in-game
# (guest) loading screen is the only cover: no helper starts, so nothing waits for its replies.
HELPER = os.name == 'nt'


def normalize_teams(teams):
    """Keep selected metadata bounded; portrait paths come from local assets."""
    if not isinstance(teams,(list,tuple)) or len(teams)>2:raise ValueError('Expected up to two selected teams')
    result=[];sides=set()
    for team in teams:
        side=team.get('side')
        if side not in (0,1) or side in sides:raise ValueError('Invalid or duplicate team side')
        sides.add(side);fighters=team.get('fighters',team.get('members',[]))
        if not isinstance(fighters,(list,tuple)) or not 1<=len(fighters)<=6:
            raise ValueError('Loading presentation supports one to six members per team')
        entries=[]
        for fighter in fighters:
            if isinstance(fighter,int):fighter={'character_id':fighter}
            character=fighter.get('character_id')
            if isinstance(character,bool) or not isinstance(character,int) or not 0<=character<250:
                raise ValueError('Invalid selected character ID')
            info=character_info(character)
            # Do not let metadata ask the helper to open arbitrary external files.
            if 'player' in fighter:
                player=fighter['player']
                if type(player)is not int or not 0<=player<=4:raise ValueError('Invalid loading player label')
                info=dict(info,player=player)
            entries.append(info)
        result.append(dict(side=side,fighters=entries))
    return sorted(result,key=lambda item:item['side'])


def choose_target(candidates, foreground):
    """The active fullscreen render root wins over a larger main/debug window."""
    if not candidates: return None
    return max(candidates, key=lambda item: (item['hwnd'] == foreground,
        'QWindowOwnDC' in item['class_name'], item['width']*item['height']))


def placement_allowed(target, foreground):
    return target is not None and target['hwnd'] == foreground


def visible_state(data, parent_alive, now):
    """Malformed/stale commands never leave an opaque window covering the game."""
    if not isinstance(data, dict) or not parent_alive:
        return False
    updated = data.get('updated', 0)
    return (data.get('visible') is True and isinstance(updated, (int, float))
            and -5 <= now-updated <= 15)


ACK_INTERVAL = .2


def ack_schedule(now, last_heartbeat, acked, state):
    """Return (write, heartbeat) for the helper's acknowledgement this tick.

    state is (command updated, owned audio records): what a waiting controller
    checks. The 0.2 s heartbeat keeps exactly its former cadence; a state not
    yet written successfully is also acknowledged on the tick it is seen,
    instead of waiting up to one heartbeat for the next write."""
    heartbeat = now-last_heartbeat >= ACK_INTERVAL
    return heartbeat or state != acked, heartbeat


class LoadingPresentation:
    def __init__(self, path, emulator=EMULATOR, native=False, helper=None):
        self.path, self.emulator = Path(path), Path(emulator).resolve()
        self.helper = HELPER if helper is None else bool(helper)
        self.process = None; self.last = {}; self.last_write = 0
        self.lock = threading.Lock(); self.teams = []
        self.mode, self.humans = 'teams', 1
        self.guest = None
        if native:
            from guest_loading_screen import GuestLoadingScreen
            self.guest = GuestLoadingScreen()

    def set_mode(self, mode='teams', humans=1):
        selected = mode_options(mode, humans)
        with self.lock:
            if selected == (self.mode, self.humans): return False
            self.mode, self.humans = selected
            if self.guest: self.guest.set_mode(*selected)
            if self.last.get('visible'):
                self.last.update(mode=self.mode, humans=self.humans)
                self._write()
            return True

    def set_teams(self, teams):
        prepared=normalize_teams(teams)
        with self.lock:
            if prepared==self.teams:return False
            self.teams=prepared
            if self.guest:self.guest.set_teams(prepared)
            if self.last.get('visible'):
                self.last['teams']=prepared;self._write()
            return True

    def prerender(self, messages):
        """Paint the in-game cover's pictures for these messages ahead of show()."""
        with self.lock:
            return self.guest.prerender(messages) if self.guest else False

    def show(self, title='Preparing your team match', message='Getting your fighters ready...', progress=0, *, error=None):
        """error=(line 1, line 2): the failure state of the in-game cover (never pre-rendered)."""
        with self.lock:
            if error:
                guest_surface = self.guest.show(message, progress, error=tuple(error)) if self.guest else False
            else:
                guest_surface = self.guest.show(message, progress) if self.guest else False
            self.last = dict(visible=True, title=title, message=message,
                             progress=max(0, min(100, int(progress))),teams=self.teams,
                             mode=self.mode, humans=self.humans,
                             guest_surface=guest_surface)
            if error: self.last['error'] = list(error)
            self._write()
            if self.helper and (self.process is None or self.process.poll() is not None):
                with self.path.with_suffix('.helper.log').open('a', encoding='utf-8') as output:
                    self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                        '--state', str(self.path), '--parent-pid', str(os.getpid()),
                        '--emulator', str(self.emulator)],
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                        stdin=subprocess.DEVNULL, stdout=output, stderr=output)

    def _write(self):
        updated = time.time()
        write_json(self.path, dict(self.last, updated=updated, parent_pid=os.getpid()))
        self.last_write = updated

    def tick(self):
        with self.lock:
            if self.guest and self.last.get('visible'):
                self.last['guest_surface']=self.guest.sync()
            if self.last.get('visible') and time.time()-self.last_write >= 1:
                try: self._write()
                except OSError as error:
                    print(f'Loading screen heartbeat delayed: {error}', flush=True)

    def wait_visible(self, timeout=2):
        if self.guest and self.guest.available:return self.guest.wait_drawn(timeout)
        if not self.helper: return False  # no desktop cover exists to acknowledge
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                ack = read_json(self.path.with_suffix('.ack.json'))
                if ack.get('visible') and ack.get('command_updated', 0) >= self.last_write:
                    return True
            except (OSError, ValueError):
                pass
            if self.process is not None and self.process.poll() is not None:
                return False
            time.sleep(.05)
        return False

    def wait_hidden(self, timeout=.5):
        # Without a helper there is no desktop cover or muted audio; hide() already raised
        # if the in-game screen could not be cleared.
        if not self.helper: return True
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                ack = read_json(self.path.with_suffix('.ack.json'))
                if (ack.get('visible') is False and ack.get('cover_visible') is False
                        and ack.get('command_updated', 0) >= self.last_write
                        and ack.get('audio_restore_pending', 0) == 0):
                    return True
            except (OSError, ValueError):
                pass
            time.sleep(.01)
        return False

    def hide(self, refresh_surface=False):
        with self.lock:
            if self.guest and not self.guest.hide():
                raise OSError('Could not clear the in-game loading screen')
            self.last = dict(visible=False, refresh_surface=bool(refresh_surface))
            self._write()

    def close(self):
        try:
            self.hide()
            self.wait_hidden(timeout=1)
        except OSError as error:
            print(f'Loading screen close command could not be written: {error}', flush=True)
        finally:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try: self.process.wait(timeout=2)
                except subprocess.TimeoutExpired: self.process.kill()


class Windows:
    """Minimal Win32 ownership/geometry; nothing activates another application."""
    def __init__(self):
        from ctypes import wintypes as w
        self.w = w
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT), ('flags', w.DWORD)]
        self.MonitorInfo = MonitorInfo
        self.owner_targets = {}
        self.repaint_requests = 0
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        u, k = self.user, self.kernel
        u.EnumWindows.argtypes = [self.callback, w.LPARAM]
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.IsWindowVisible.argtypes = [w.HWND]; u.IsIconic.argtypes = [w.HWND]
        u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        u.WindowFromPoint.argtypes = [w.POINT]; u.WindowFromPoint.restype = w.HWND
        u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
        u.GetParent.argtypes = [w.HWND]; u.GetParent.restype = w.HWND
        u.GetAncestor.argtypes = [w.HWND, w.UINT]; u.GetAncestor.restype = w.HWND
        u.GetForegroundWindow.restype = w.HWND
        u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, w.UINT]
        u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
        u.RedrawWindow.argtypes = [w.HWND, ctypes.POINTER(w.RECT), w.HANDLE, w.UINT]
        u.RedrawWindow.restype = w.BOOL
        u.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]; u.MonitorFromWindow.restype = w.HANDLE
        u.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.POINTER(MonitorInfo)]
        u.GetMonitorInfoW.restype = w.BOOL
        self.get_long = u.GetWindowLongPtrW; self.set_long = u.SetWindowLongPtrW
        self.get_long.argtypes = [w.HWND, ctypes.c_int]; self.get_long.restype = ctypes.c_ssize_t
        self.set_long.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.set_long.restype = ctypes.c_ssize_t
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenProcess.restype = w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        try: u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError: pass

    def alive(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle: return False
        try:
            code = self.w.DWORD()
            return bool(self.kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally: self.kernel.CloseHandle(handle)

    def path(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle: return ''
        try:
            value = ctypes.create_unicode_buffer(32768); size = self.w.DWORD(len(value))
            if self.kernel.QueryFullProcessImageNameW(handle, 0, value, ctypes.byref(size)):
                return os.path.normcase(os.path.abspath(value.value))
            return ''
        finally: self.kernel.CloseHandle(handle)

    def foreground(self):
        hwnd = self.user.GetForegroundWindow()
        return self.user.GetAncestor(hwnd, 2) if hwnd else 0

    def target(self, executable):
        matches = []; wanted = os.path.normcase(os.path.abspath(executable)); cache = {}
        @self.callback
        def visit(hwnd, _):
            if not self.user.IsWindowVisible(hwnd) or self.user.IsIconic(hwnd): return True
            pid = self.w.DWORD(); self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in cache: cache[pid.value] = self.path(pid.value)
            if cache[pid.value] != wanted: return True
            rect = self.w.RECT(); point = self.w.POINT(0, 0)
            if self.user.GetClientRect(hwnd, ctypes.byref(rect)) and self.user.ClientToScreen(hwnd, ctypes.byref(point)):
                width, height = rect.right-rect.left, rect.bottom-rect.top
                if width >= 240 and height >= 180:
                    name = ctypes.create_unicode_buffer(256); title = ctypes.create_unicode_buffer(512)
                    self.user.GetClassNameW(hwnd, name, len(name))
                    self.user.GetWindowTextW(hwnd, title, len(title))
                    matches.append(dict(hwnd=hwnd, pid=pid.value, x=point.x, y=point.y,
                        width=width, height=height, class_name=name.value, title=title.value))
            return True
        self.user.EnumWindows(visit, 0)
        return choose_target(matches, self.foreground())

    def own(self, hwnd, owner):
        # Ownership never changes the emulator's parent, styles or focus.
        self.set_long(hwnd, -8, owner)
        style = self.get_long(hwnd, -20)
        self.set_long(hwnd, -20, (style | 0x08000000 | 0x80) & ~0x40000)

    def conceal(self, hwnd):
        owner = self.get_long(hwnd, -8)
        style = self.get_long(hwnd, -20)
        visible = bool(self.user.IsWindowVisible(hwnd))
        if not visible and not owner and not style & 0x8:
            return False  # Do not perturb compositor/window order every tick.
        self.user.ShowWindow(hwnd, 0)
        # Detach before demoting: Win32 can otherwise demote a topmost owner.
        self.set_long(hwnd, -8, 0)
        self.user.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x10 | 0x1 | 0x2 | 0x200)
        target = getattr(self, 'owner_targets', {}).pop(hwnd, None)
        if visible and target:
            self.request_repaint(target)
        return True

    def request_repaint(self, target):
        """One native expose/paint request after uncovering the owned surface."""
        owner = target['hwnd']
        if (not target.get('pid') or self.foreground() != owner
                or not self.user.IsWindowVisible(owner) or self.user.IsIconic(owner)):
            return False
        pid = self.w.DWORD()
        self.user.GetWindowThreadProcessId(owner, ctypes.byref(pid))
        if pid.value != target['pid']: return False  # A destroyed HWND may be reused.
        # Invalidate and process WM_PAINT for this window and its render children.
        # Do not erase its background, resize it, change styles or activate it.
        requested = bool(self.user.RedrawWindow(owner, None, None, 0x1 | 0x80 | 0x100))
        if requested: self.repaint_requests = getattr(self, 'repaint_requests', 0)+1
        print(f'Loading reveal repaint: hwnd={owner} accepted={requested}', flush=True)
        return requested

    def window_state(self, hwnd):
        rect = self.w.RECT(); pid = self.w.DWORD()
        if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)): return None
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return dict(pid=pid.value, bounds=(rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top),
            style=self.get_long(hwnd, -16), extended=self.get_long(hwnd, -20),
            visible=bool(self.user.IsWindowVisible(hwnd)), iconic=bool(self.user.IsIconic(hwnd)))

    def monitor_bounds(self, hwnd):
        handle = self.user.MonitorFromWindow(hwnd, 0)
        info = self.MonitorInfo(); info.size = ctypes.sizeof(info)
        if not handle or not self.user.GetMonitorInfoW(handle, ctypes.byref(info)): return None
        rect = info.monitor
        return (rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top)

    def resize_surface(self, hwnd, width, height):
        # NOMOVE | NOZORDER | NOACTIVATE | NOOWNERZORDER. No fullscreen/style change.
        return bool(self.user.SetWindowPos(hwnd, None, 0, 0, width, height, 0x216))

    def place(self, hwnd, target):
        if not placement_allowed(target, self.foreground()):
            self.conceal(hwnd); return False
        if not hasattr(self, 'owner_targets'): self.owner_targets = {}
        self.owner_targets[hwnd] = dict(target)
        self.own(hwnd, target['hwnd'])
        if not self.user.SetWindowPos(hwnd, -1, target['x'], target['y'], target['width'], target['height'],
                                      0x10 | 0x40 | 0x200):
            raise ctypes.WinError(ctypes.get_last_error())
        # Recheck after placement so a foreground switch cannot leave a cover
        # above another application until the next ordinary polling tick.
        if not placement_allowed(target, self.foreground()):
            self.conceal(hwnd); return False
        return True

    def evidence(self, hwnd, target):
        rect = self.w.RECT(); valid = self.user.GetWindowRect(hwnd, ctypes.byref(rect))
        actual = [rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top] if valid else None
        expected = [target[k] for k in ('x', 'y', 'width', 'height')] if target else None
        foreground = self.foreground()
        point_owner = 0
        if target:
            point = self.w.POINT(target['x']+target['width']//2, target['y']+target['height']//2)
            point_owner = self.user.WindowFromPoint(point) or 0
        cover_visible = bool(self.user.IsWindowVisible(hwnd))
        visible = bool(cover_visible and target and actual == expected
                       and placement_allowed(target, foreground) and point_owner == hwnd)
        return dict(visible=visible, cover_visible=cover_visible, cover_hwnd=hwnd,
                    cover_rect=actual, target=target, foreground=foreground,
                    center_window=point_owner, repaint_requests=getattr(self, 'repaint_requests', 0))


def run_cover(path, parent_pid, emulator):
    from loading_audio import AudioMute, cover_mutes, repaired_sessions
    from native_loading_window import NativeLoadingWindow
    from loading_surface_refresh import refresh
    api = Windows()
    audio_receipt = path.with_name(f'audio-restore-{os.getpid()}.json')
    audio = AudioMute(emulator, audio_receipt)
    with path.with_suffix('.helper.log').open('a', encoding='utf-8') as output:
        subprocess.Popen([sys.executable, str(Path(__file__).with_name('loading_audio.py')),
            '--watch', str(os.getpid()), '--emulator', str(emulator), '--receipt', str(audio_receipt)],
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            stdin=subprocess.DEVNULL, stdout=output, stderr=output)
    window = NativeLoadingWindow(api)
    last_ack = 0; last_audio = 0; owner_pid = None; audio_failed = False; acked = None
    previous = None; diagnostic = None; data = {}; last_refresh = None; surface_refresh = None
    # Helper start: unmute the private PCSX2 once its sessions appear (Windows keeps a mute an
    # earlier session left), whenever no loading cover mutes. Bounded: 60 s, then the
    # Play-launch repair (loading_audio.py --repair) alone watches for new sessions. A mute
    # found later on a session checked here is the player's, and loading covers keep it.
    repaired = set(); repair_until = time.monotonic()+60; last_repair = 0
    try:
        while not window.closed and api.alive(parent_pid):
            window.pump()
            try: data = read_json(path)
            except (OSError, ValueError): pass  # Retain a recent complete command.
            now = time.time(); loading = visible_state(data, True, now)
            # Explicit diagnostic only; ordinary preparation never requests a
            # surface resize. Fullscreen capture can be stale without a cover.
            if (not loading and data.get('refresh_surface') is True and data.get('updated') != last_refresh):
                last_refresh = data.get('updated')
                surface_refresh = refresh(api, window, api.owner_targets.get(window.hwnd))
                print('Loading surface refresh: '+json.dumps(surface_refresh), flush=True)
            target = api.target(emulator) if loading else None
            window.target_hwnd = target['hwnd'] if target else 0
            shown = api.place(window.hwnd, None if data.get('guest_surface') else target)
            if target: owner_pid = target['pid']
            content = (data.get('title'), data.get('message'), data.get('progress'),
                       json.dumps(data.get('teams',[]),sort_keys=True),int(time.monotonic()*6),
                       tuple(target[k] for k in ('x', 'y', 'width', 'height')) if target else None)
            if shown and content != previous:
                window.redraw(data); previous = content
            elif not shown: previous = None
            evidence = api.evidence(window.hwnd, target)
            evidence.update(bitmap_submissions=window.surface.submissions,
                            presentation_path='native-gs' if data.get('guest_surface') else 'layered-bitmap',
                            physical_visibility_verified=False)
            marker = (evidence['visible'], tuple(evidence['cover_rect'] or []),
                      evidence['foreground'], target['hwnd'] if target else 0)
            if marker != diagnostic:
                print('Loading cover: '+json.dumps(evidence), flush=True)
                diagnostic = marker
            # Only the loading cover mutes: a failure cover (its command carries 'error') unmutes
            # on the tick it is read, like a hidden cover.
            muting = loading and cover_mutes(data)
            repair = repair_until is not None and not muting and now-last_repair >= .5
            if (muting and now-last_audio >= .5) or (not muting and audio.records) or repair:
                try:
                    # Sessions the Play-launch repair checked (its audio-repaired.json beside this command)
                    # are checked for this helper too. On every checked session a mute found later is the
                    # player's: a loading cover puts it back (keep), and the start check leaves it alone.
                    repaired.update(repaired_sessions(path.parent))
                    before = len(audio.records)
                    if muting and owner_pid is not None: audio.mute(owner_pid, keep=repaired)
                    elif not muting:
                        if audio.records: audio.restore()
                        if repair:
                            last_repair = now
                            if time.monotonic() >= repair_until: repair_until = None  # this try is the last
                            unmuted = audio.repair(seen=repaired)
                            if unmuted:
                                print(f'Loading audio: unmuted {unmuted} session(s) that started muted.', flush=True)
                            if repaired: repair_until = None
                    if len(audio.records) != before:
                        print(f'Loading audio: {len(audio.records)} owned session(s) muted for the loading screen; '
                              'each is unmuted when it ends.', flush=True)
                except Exception as error:
                    if not audio_failed:
                        print(f'Loading audio control unavailable: {error}', flush=True)
                        audio_failed = True
                last_audio = now
            # After the audio step, so a restore is reported on the tick it happens.
            state = (data.get('updated', 0), len(audio.records))
            write, heartbeat = ack_schedule(now, last_ack, acked, state)
            if write:
                try:
                    write_json(path.with_suffix('.ack.json'), dict(evidence, updated=now,
                        command_updated=state[0], requested_visible=loading,
                        surface_refresh=surface_refresh,
                        audio_muted=any(r.get('applied') for r in audio.records.values()),
                        audio_restore_pending=state[1]))
                    acked = state
                    if heartbeat: last_ack = now
                except OSError as error:
                    print(f'Loading screen acknowledgement delayed: {error}', flush=True)
            time.sleep(.02)
    finally:
        try:
            window.close()
        finally:
            try: audio.restore()
            except Exception: traceback.print_exc()  # independent watchdog retries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--parent-pid', required=True, type=int)
    parser.add_argument('--emulator', type=Path, default=EMULATOR)
    args = parser.parse_args()
    if os.name != 'nt': raise RuntimeError('The loading cover requires Windows')
    run_cover(args.state, args.parent_pid, args.emulator)
