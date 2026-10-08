"""Seeded, human-like controller input for the lockstep experiments (one frame = one battle update, 30 per second).

A player is a random walk over short actions with human timing: taps are held 2-5 updates (66-166 ms), a combo is
3-8 Square taps with 2-6 update gaps, guards and ki charges are held for 0.3-2 s, the left stick ramps to a
direction over 2-4 updates, sweeps around the circle, dashes (a direction plus a Cross double tap), R1 specials
(R1 held, then Triangle/Square/Cross), ki blasts, short mashing bursts, rare right-stick flicks and idle pauses.
Start and Select (pause and menus) and L3/R3 are never pressed, except by the 'transform' profile (kit 1.3.0 test
bots for the native IO gate): it also taps R3 (transform), holds a direction then R3 with it (a leader fusion with a
teammate) and enters ultimates (L2 + Down + Triangle, which the game takes in MAX POWER; the 'charge' action reaches
MAX POWER at full ki with a blast stock). The same seed always gives the same frames.

Frames are netplay_core raw bytes: buttons (active-low, low byte then high byte), right X, right Y, left X,
left Y, two pressure bytes (0). Stick bytes: 0x7F is centre, 0x00 left/up, 0xFF right/down.

File format (.npin): 'NPIN', u16 version 1, u16 slots, u32 frames, u32 seed, 16-byte profile name, then
frames x slots x 8 raw bytes (frame-major).

usage: python input_gen.py make OUT.npin --frames 5400 --seed 7 [--profiles fighter,calm]
       python input_gen.py show IN.npin [--first 0] [--count 40]
"""
import argparse
import math
import random
import struct
from dataclasses import dataclass, field
from pathlib import Path

BUTTON = dict(select=0x1, l3=0x2, r3=0x4, start=0x8, up=0x10, right=0x20, down=0x40, left=0x80, l2=0x100, r2=0x200,
              l1=0x400, r1=0x800, triangle=0x1000, circle=0x2000, cross=0x4000, square=0x8000)
NEVER = BUTTON['start'] | BUTTON['select'] | BUTTON['l3'] | BUTTON['r3']
NEUTRAL = bytes.fromhex('ffff7f7f7f7f0000')
HEADER = struct.Struct('<4sHHII16s')
MAGIC = b'NPIN'
PROFILES = {
    #            idle walk sweep dash combo  ki guard charge special mash flick  r3   fuse  ultimate
    'fighter': (0.10, 0.16, 0.07, 0.09, 0.20, 0.09, 0.09, 0.04, 0.08, 0.05, 0.03, 0.00, 0.00, 0.00),
    'calm':    (0.30, 0.25, 0.10, 0.05, 0.10, 0.05, 0.08, 0.03, 0.02, 0.00, 0.02, 0.00, 0.00, 0.00),
    'mash':    (0.03, 0.10, 0.05, 0.10, 0.25, 0.12, 0.05, 0.02, 0.10, 0.16, 0.02, 0.00, 0.00, 0.00),
    'transform': (0.05, 0.10, 0.04, 0.07, 0.15, 0.06, 0.04, 0.12, 0.06, 0.05, 0.01, 0.10, 0.04, 0.11),
}
ACTIONS = ('idle', 'walk', 'sweep', 'dash', 'combo', 'ki', 'guard', 'charge', 'special', 'mash', 'flick', 'r3', 'fuse',
           'ultimate')
# trailing zero weights leave the older profiles' frames exactly as they were (random.choices draws the same index)


def stick(angle=None, radius=1.0):
    """(x, y) bytes for a direction in radians (0 = right, pi/2 = up) at radius 0..1; None = centre."""
    if angle is None or radius <= 0:
        return 0x7F, 0x7F
    x = 127.5 + 127.5 * radius * math.cos(angle)
    y = 127.5 - 127.5 * radius * math.sin(angle)
    return max(0, min(255, int(round(x)))), max(0, min(255, int(round(y))))


def raw(buttons=0, lx=0x7F, ly=0x7F, rx=0x7F, ry=0x7F):
    word = ~buttons & 0xFFFF
    return bytes([word & 0xFF, word >> 8, rx, ry, lx, ly, 0, 0])


def decode(data):
    buttons = ~(data[0] | data[1] << 8) & 0xFFFF
    return dict(buttons=buttons, names=[k for k, v in BUTTON.items() if buttons & v], rx=data[2], ry=data[3],
                lx=data[4], ly=data[5])


@dataclass
class Frame:
    buttons: int = 0
    left: tuple = (0x7F, 0x7F)
    right: tuple = (0x7F, 0x7F)
    allow: int = 0                                                # NEVER buttons this frame may press (R3)

    def encode(self):
        return raw(self.buttons & ~(NEVER & ~self.allow), self.left[0], self.left[1], self.right[0], self.right[1])


@dataclass
class Player:
    rng: random.Random
    weights: tuple
    angle: float = 0.0
    frames: list = field(default_factory=list)

    def tap(self, button, hold=None, left=None):
        hold = hold or self.rng.randint(2, 5)
        for _ in range(hold):
            self.frames.append(Frame(BUTTON[button], left or (0x7F, 0x7F)))

    def pause(self, lo, hi, left=None):
        for _ in range(self.rng.randint(lo, hi)):
            self.frames.append(Frame(0, left or (0x7F, 0x7F)))

    def ramp(self, angle, steps, up=True):
        for i in range(steps):
            r = (i + 1) / steps if up else 1 - (i + 1) / steps
            self.frames.append(Frame(0, stick(angle, r)))

    # -- actions
    def idle(self):
        self.pause(4, 24)

    def walk(self):
        r = self.rng
        self.angle = r.uniform(0, 2 * math.pi)
        self.ramp(self.angle, r.randint(2, 4))
        for _ in range(r.randint(8, 45)):
            self.angle += r.gauss(0, 0.05)                        # a thumb never holds perfectly still
            self.frames.append(Frame(0, stick(self.angle, r.uniform(0.9, 1.0))))
        self.ramp(self.angle, r.randint(2, 3), up=False)

    def sweep(self):
        r = self.rng
        start, turn, steps = r.uniform(0, 2 * math.pi), r.choice((-1, 1)) * r.uniform(math.pi / 2, 2 * math.pi), r.randint(15, 50)
        radius = r.uniform(0.8, 1.0)
        for i in range(steps):
            self.frames.append(Frame(0, stick(start + turn * i / steps, radius)))

    def dash(self):
        r = self.rng
        left = stick(r.uniform(0, 2 * math.pi))
        self.pause(1, 2, left)
        self.tap('cross', r.randint(2, 3), left)
        self.pause(2, 4, left)
        self.tap('cross', r.randint(2, 3), left)
        self.pause(3, 8, left)

    def combo(self):
        r = self.rng
        left = stick(r.uniform(0, 2 * math.pi)) if r.random() < 0.4 else None
        for _ in range(r.randint(3, 8)):
            self.tap('square', r.randint(2, 4), left)
            self.pause(2, 6, left)
        finish = r.random()
        if finish < 0.3:
            self.tap('triangle')
        elif finish < 0.5:
            self.tap('square', r.randint(6, 12), stick(r.uniform(0, 2 * math.pi)))   # a held (charged) smash

    def ki(self):
        r = self.rng
        for _ in range(r.randint(1, 4)):
            self.tap('triangle')
            self.pause(3, 8)

    def guard(self):
        r = self.rng
        left = stick(r.uniform(0, 2 * math.pi)) if r.random() < 0.3 else (0x7F, 0x7F)
        for _ in range(r.randint(10, 50)):
            self.frames.append(Frame(BUTTON['circle'], left))

    def charge(self):
        r = self.rng
        for _ in range(r.randint(20, 60)):
            self.frames.append(Frame(BUTTON['l1'] | BUTTON['circle']))

    def special(self):
        r = self.rng
        hold = r.randint(4, 10)
        for _ in range(hold):
            self.frames.append(Frame(BUTTON['r1']))
        button = r.choice(('triangle', 'square', 'cross'))
        for _ in range(r.randint(2, 5)):
            self.frames.append(Frame(BUTTON['r1'] | BUTTON[button]))
        self.pause(4, 12)

    def mash(self):
        r = self.rng
        for i in range(r.randint(3, 8)):                          # about 7 presses a second, alternating
            for _ in range(2):
                self.frames.append(Frame(BUTTON['square' if i % 2 else 'triangle']))
            self.pause(1, 2)

    def flick(self):
        r = self.rng
        right = stick(r.choice((0, math.pi / 2, math.pi, 3 * math.pi / 2)))
        for _ in range(r.randint(3, 6)):
            self.frames.append(Frame(0, (0x7F, 0x7F), right))

    def r3(self):                                                 # transform (a tap: the next form)
        for _ in range(self.rng.randint(2, 4)):
            self.frames.append(Frame(BUTTON['r3'], allow=BUTTON['r3']))
        self.pause(6, 20)

    def fuse(self):                                               # a direction, then R3 with it held (fusion)
        side = self.rng.choice(('left', 'right'))
        for _ in range(2):
            self.frames.append(Frame(BUTTON[side]))
        for _ in range(self.rng.randint(20, 30)):
            self.frames.append(Frame(BUTTON['r3'] | BUTTON[side], allow=BUTTON['r3']))
        self.pause(6, 20)

    def ultimate(self):                                           # L2 + Down + Triangle (in MAX POWER)
        for _ in range(self.rng.randint(3, 5)):
            self.frames.append(Frame(BUTTON['l2'] | BUTTON['down'] | BUTTON['triangle']))
        self.pause(8, 30)

    def fill(self, count):
        while len(self.frames) < count:
            getattr(self, self.rng.choices(ACTIONS, self.weights)[0])()
            if self.rng.random() < 0.5:
                self.pause(0, 4)                                  # reaction gap between actions
        return [f.encode() for f in self.frames[:count]]


def generate(frames, seed, profile='fighter'):
    """frames raw8 values for one player."""
    if profile not in PROFILES:
        raise ValueError(f'unknown profile {profile!r} (one of {", ".join(PROFILES)})')
    return Player(random.Random(seed), PROFILES[profile]).fill(frames)


def make_script(frames, seed, profiles=('fighter', 'fighter')):
    """rows[frame] = (slot 0 raw, slot 1 raw, ...); slot s uses seed * 16 + s."""
    columns = [generate(frames, seed * 16 + s, p) for s, p in enumerate(profiles)]
    return [tuple(c[f] for c in columns) for f in range(frames)]


@dataclass
class Script:
    rows: list
    seed: int
    profile: str

    @property
    def frames(self):
        return len(self.rows)

    @property
    def slots(self):
        return len(self.rows[0]) if self.rows else 0


def save(path, rows, seed, profile='fighter'):
    slots = len(rows[0])
    blob = bytearray(HEADER.pack(MAGIC, 1, slots, len(rows), seed & 0xFFFFFFFF, profile.encode()[:16].ljust(16, b'\0')))
    for row in rows:
        if len(row) != slots or any(len(r) != 8 for r in row):
            raise ValueError('every row holds one 8-byte raw input per slot')
        blob += b''.join(row)
    Path(path).write_bytes(bytes(blob))


def load(path):
    data = Path(path).read_bytes()
    magic, version, slots, frames, seed, profile = HEADER.unpack_from(data)
    if magic != MAGIC or version != 1 or len(data) != HEADER.size + frames * slots * 8:
        raise ValueError(f'{path} is not an NPIN v1 script')
    at = HEADER.size
    rows = []
    for _ in range(frames):
        rows.append(tuple(data[at + s * 8:at + (s + 1) * 8] for s in range(slots)))
        at += slots * 8
    return Script(rows, seed, profile.rstrip(b'\0').decode())


def describe(stream):
    """Counts of a raw8 stream: presses (rising edges) per button, stick activity, neutral share."""
    presses, previous, moving, neutral = {k: 0 for k in BUTTON}, 0, 0, 0
    for data in stream:
        d = decode(data)
        for name, bit in BUTTON.items():
            if d['buttons'] & bit and not previous & bit:
                presses[name] += 1
        previous = d['buttons']
        if (d['lx'], d['ly']) != (0x7F, 0x7F):
            moving += 1
        if data == NEUTRAL:
            neutral += 1
    n = max(len(stream), 1)
    return dict(frames=len(stream), presses={k: v for k, v in presses.items() if v}, stick_share=round(moving / n, 3),
                neutral_share=round(neutral / n, 3))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    make = sub.add_parser('make')
    make.add_argument('out', type=Path)
    make.add_argument('--frames', type=int, default=5400)
    make.add_argument('--seed', type=int, default=1)
    make.add_argument('--profiles', default='fighter,fighter')
    show = sub.add_parser('show')
    show.add_argument('script', type=Path)
    show.add_argument('--first', type=int, default=0)
    show.add_argument('--count', type=int, default=40)
    args = parser.parse_args(argv)
    if args.command == 'make':
        profiles = tuple(args.profiles.split(','))
        rows = make_script(args.frames, args.seed, profiles)
        save(args.out, rows, args.seed, '+'.join(profiles))
        for s in range(len(profiles)):
            print(f'slot {s}:', describe([r[s] for r in rows]))
        print(f'{args.out}: {len(rows)} frames x {len(profiles)} slots')
    else:
        script = load(args.script)
        print(f'{script.frames} frames, {script.slots} slots, seed {script.seed}, profile {script.profile}')
        for f in range(args.first, min(args.first + args.count, script.frames)):
            print(f, ' | '.join(f"{','.join(decode(r)['names']) or '-':>16} L{decode(r)['lx']:3d},{decode(r)['ly']:3d}"
                                f" R{decode(r)['rx']:3d},{decode(r)['ry']:3d}" for r in script.rows[f]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
