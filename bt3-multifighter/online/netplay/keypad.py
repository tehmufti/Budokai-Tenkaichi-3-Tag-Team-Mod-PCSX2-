"""A seeded human-like player on one instance's PHYSICAL pad 1, through PCSX2's own keyboard bindings.

input_gen.generate(frames, seed, profile) gives one raw pad value per battle update (30 per second). KeyPlayer turns
it into key transitions of that instance's Pad1 keyboard bindings (netrig.PAD1_KEYS: buttons and d-pad as they are,
each stick axis past a threshold as the bound direction key = full deflection) and posts WM_KEYDOWN / WM_KEYUP to the
emulator's windows on its hidden desktop at the script's wall-clock times (frame f at f / 29.97 s after start). The
emulator's input manager turns the keys into pad 1 state; the game's raw pad read (sub_295FB8 through libpad / SIO2)
then reads it exactly as it reads a USB/SDL controller bound to pad 1, and netplay_core captures it there. Wall-clock
timing (not frame-exact) is deliberate: a human presses on real time, so presses land on whichever update the
emulator happens to poll next, and stalls stretch nothing on the player's side.
"""
import json
import threading
import time

import input_gen

AXIS_LO, AXIS_HI = 0x40, 0xC0
DPAD_AND_BUTTONS = ('up', 'right', 'down', 'left', 'l2', 'r2', 'l1', 'r1', 'triangle', 'circle', 'cross', 'square',
                    'r3')                                    # R3: only the 'transform' test profile presses it


def keys_of(raw):
    """The Pad1 key names held for one raw8 value."""
    d = input_gen.decode(raw)
    held = {name for name in DPAD_AND_BUTTONS if d['buttons'] & input_gen.BUTTON[name]}
    for value, lo, hi in ((d['lx'], 'lleft', 'lright'), (d['ly'], 'lup', 'ldown'),
                          (d['rx'], 'rleft', 'rright'), (d['ry'], 'rup', 'rdown')):
        if value < AXIS_LO:
            held.add(lo)
        elif value > AXIS_HI:
            held.add(hi)
    return held


def schedule(frames, seed, profile='fighter'):
    """[(frame, downs, ups)] transitions of the key script."""
    out, previous = [], set()
    for f, raw in enumerate(input_gen.generate(frames, seed, profile)):
        held = keys_of(raw)
        downs, ups = sorted(held - previous), sorted(previous - held)
        if downs or ups:
            out.append((f, downs, ups))
        previous = held
    if previous:
        out.append((frames, [], sorted(previous)))
    return out


class KeyPlayer(threading.Thread):
    def __init__(self, instances, name, frames, seed, profile='fighter', rate=29.97, log=None):
        super().__init__(daemon=True, name=f'keys-{name}')
        self.I, self.name, self.rate = instances, name, rate
        self.plan = schedule(frames, seed, profile)
        self.go, self.halt = threading.Event(), threading.Event()
        self.held, self.posted, self.started_at, self.log = set(), [], None, log
        self.error = None

    def post(self, key, down):
        self.I.key_event(self.name, f'p1:{key}', down)

    def run(self):
        try:
            self.go.wait()
            t0 = self.started_at = time.perf_counter()
            for f, downs, ups in self.plan:
                due = t0 + f / self.rate
                while not self.halt.is_set():
                    left = due - time.perf_counter()
                    if left <= 0:
                        break
                    time.sleep(min(left, 0.05))
                if self.halt.is_set():
                    break
                for key in ups:
                    self.post(key, False)
                    self.held.discard(key)
                for key in downs:
                    self.post(key, True)
                    self.held.add(key)
                self.posted.append((round(time.perf_counter() - t0, 4), f, downs, ups))
        except Exception as error:  # noqa: BLE001 - reported by the runner
            self.error = repr(error)
        finally:
            for key in sorted(self.held):
                try:
                    self.post(key, False)
                except Exception:  # noqa: BLE001
                    pass
            self.held.clear()
            if self.log:
                with open(self.log, 'w', encoding='utf-8') as f:
                    json.dump(dict(name=self.name, started_at=self.started_at, transitions=self.posted,
                                   error=self.error), f)

    def stop(self):
        self.halt.set()
        self.go.set()
