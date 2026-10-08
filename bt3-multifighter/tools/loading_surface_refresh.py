"""Optional diagnostic refresh beneath an existing loading cover.

Only a one-pixel size change and its exact reversal are requested. The caller
must keep combat held and its cover visible until this transaction returns.
The normal preparation flow does not request this diagnostic: later control
tests reproduced stale fullscreen capture without any loading cover.
"""
import time


def same_window(current, original, bounds):
    return (current is not None and current['pid'] == original['pid']
            and current['style'] == original['style']
            and current['extended'] == original['extended']
            and current['bounds'] == bounds and current['visible'] and not current['iconic'])


def refresh(api, window, target, delay=time.sleep):
    if not target or not target.get('pid') or api.foreground() != target['hwnd']:
        return dict(status='skipped', reason='game is not foreground')
    hwnd = target['hwnd']; original = api.window_state(hwnd)
    if (not original or original['pid'] != target['pid'] or not original['visible']
            or original['iconic'] or original['style'] & (0xC00000 | 0x40000)):
        return dict(status='skipped', reason='window is not an owned borderless surface')
    bounds = original['bounds']; x, y, width, height = bounds
    if width < 240 or height < 180 or api.monitor_bounds(hwnd) != bounds:
        return dict(status='skipped', reason='window is not fullscreen')
    expected = (target['x'], target['y'], target['width'], target['height'])
    if bounds != expected or not api.evidence(window.hwnd, target)['visible']:
        return dict(status='skipped', reason='fullscreen surface is not fully covered')
    changed = (x, y, width, height-1)
    result = dict(status='skipped', reason='surface rejected the temporary size')
    attempted = False; restored = False; settle_error = None

    def settle():
        # Let the Qt resize signal reach the CPU/GS queues; immediate reversal
        # can be coalesced before Vulkan sees a different surface size.
        for _ in range(5):
            window.pump(); delay(.02)

    try:
        if (api.foreground() != hwnd or
                not same_window(api.window_state(hwnd), original, bounds)):
            return dict(status='skipped', reason='window changed before refresh')
        attempted = True
        if api.resize_surface(hwnd, width, height-1):
            settle()
    except Exception as error:
        settle_error = str(error)
        result = dict(status='error', reason=str(error))
    finally:
        if attempted:
            current = api.window_state(hwnd)
            # Restore our temporary geometry even after focus loss. A user
            # resize, fullscreen toggle, minimize or replaced HWND is retained.
            if same_window(current, original, changed):
                restored = bool(api.resize_surface(hwnd, width, height))
                if restored and same_window(api.window_state(hwnd), original, bounds):
                    result = dict(status='restored', hwnd=hwnd, bounds=list(bounds))
                else:
                    result = dict(status='error', reason='original surface size was not restored')
            elif not same_window(current, original, bounds):
                result = dict(status='skipped', reason='user or window changed during refresh')
    if restored:
        try:
            settle()
        except Exception as error:
            settle_error = str(error)
    if settle_error is not None:
        # A restored surface is safe to uncover, but retain diagnostic evidence
        # rather than silently replacing an interrupted wait with success.
        result['settle_error'] = settle_error
    return result
