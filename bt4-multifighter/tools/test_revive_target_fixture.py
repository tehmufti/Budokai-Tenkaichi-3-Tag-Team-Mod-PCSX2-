"""Synthetic target-selection fixture; no game images or captured RAM."""
import math
import struct
import unittest
try:
    import teammate_revive
except FileNotFoundError:
    raise unittest.SkipTest('Revival instruction tests need local disc-derived native headers')
import battle_mode_policy as modes
import display_settings as display
import fresh_team_camera as follow
import fresh_team_combat as core
import lockoff_target as off
import lockon_queue as q
import lockon_select as sel
import lockon_switch as ls
import team_participation as part
from input_script import RECORDS
from test_fusion_partner_lifecycle import FusionCpu
GP, MANAGER, CAM = 0x304270, 0x1870400, 0x1900000
ACTORS = [0x2000000+i*0x2000 for i in range(12)]
MODELS = [0x3000000+i*0x2000 for i in range(12)]
BONES = [0x3100000+i*0x100 for i in range(12)]
PREVIOUS = 0x07200600
BATTLE = 0x1A00000
ORTHO = (1,0,0,0,0,1,0,0,0,0,1,0,1792,1824,0,1)
L3 = 2
A_BATTLE = 0x2FEB38
def project(matrix, point):
    clip = [sum(matrix[k*4+j]*point[k] for k in range(4)) for j in range(4)]
    if not all(math.isfinite(x) for x in clip) or clip[3] <= 0: return None
    return int(clip[0]/clip[3]*16), int(clip[1]/clip[3]*16), 1, max(1, int(clip[3]))


def make(count=6, humans=(0,), mode='teams', positions=None, view=(0, 511, 0, 447), button=L3, off_button=L3,
         threshold=15, on_threshold=1, order='left_to_right', stick=1, after_ko=1, marker=1, resolver=None,
         install=True, targets=None, matrix=ORTHO, side=0, style=2):
    c = FusionCpu(); c.r[28] = GP
    c.w(core.ACTORS, MANAGER); c.w(MANAGER, 2); c.w(MANAGER+4, ACTORS[0])
    c.write(core.MODE, struct.pack('<4I', 1, count, MANAGER, count))
    positions = positions or [(40+40*i, 224, 0) for i in range(count)]
    for i in range(count):
        a, m = ACTORS[i], MODELS[i]
        c.w(core.POINTERS+4*i, a)
        for field, value in ((0, i), (4, i if i < 2 else i & 1), (8, i & 1), (12, i), (0x994, 0), (0x9E4, 1000),
                             (0x9E8, 1000), (0x948, 11), (0x1278, 0 if i in humans else 1)):
            c.w(a+field, value)
        c.w(core.MODELS+4*i, m); c.w(m+4, 1); c.w(m+8, 1)
        place(c, i, positions[i])
    targets = targets if targets is not None else [(i ^ 1) if mode != 'ffa' else (1 if i == 0 else 0) for i in range(count)]
    for i, t in enumerate(targets): c.w(core.TABLE+4*i, t)
    c.w(part.CONTROL+12, (1 << count)-1); c.w(part.CONTROL+16, 0)
    if mode != 'teams':
        c.write(modes.CONTROL, struct.pack('<4I', modes.MAGIC, MANAGER, count, {'ffa': modes.FFA, 'coop': modes.COOP}[mode]))
    c.write(q.CODE, q.payload(PREVIOUS, button_aware=q.CONFIGURABLE, pad_resolver=resolver, lockoff=True,
                              free_for_all=mode == 'ffa', coop_controls=mode == 'coop'))
    c.write(ls.CONTROL, struct.pack('<3I', 1, MANAGER, button))
    c.w(q.CONTROL+q.FIELDS['timeout'], q.DEFAULT_TIMEOUT)
    c.write(q.CONTROL+q.TIMING_UPDATES, struct.pack('<2I', on_threshold, q.TIMING_TAG))
    for p, b in off.programs(): c.write(p, b)
    c.write(off.CONTROL, struct.pack('<5I', off.MAGIC, MANAGER, off_button, threshold, 0))
    if install:
        for p, b in sel.programs(): c.write(p, b)
        control = bytearray(0x100)
        struct.pack_into('<8I', control, 0, sel.MAGIC, MANAGER, sel.ORDERS[order], stick, sel.STICK_CONFIRM, after_ko,
                         marker, sel.COLOUR)
        struct.pack_into('<I', control, sel.FIELDS['side'], side)
        struct.pack_into('<I', control, sel.FIELDS['style'], style if marker else 0)
        struct.pack_into('<12I', control, sel.FIELDS['keys'], *(sel.INVALID,)*12)
        c.write(sel.CONTROL, bytes(control))
    # Seat cameras: side 0 follows the first human, side 1 the second (or physical 1).
    c.w(follow.SUCCESSOR_CONTROL+8, humans[0] if humans else 0)
    c.w(follow.SUCCESSOR_CONTROL+12, humans[1] if len(humans) > 1 else 1)
    c.w(GP-22172, CAM-1824); c.w(GP-22176, CAM)
    for base in (CAM, CAM+656):
        for i, v in enumerate(view): c.w(base+512+4*i, v)
        c.write(base+320, struct.pack('<16f', *matrix))
    c.w(A_BATTLE, BATTLE); c.w(BATTLE, 3)
    c.events, c.matrix, c.saved_matrix, c.calls, c.packets, c.cursor = [], None, [], [], [], 0x5000000
    def push(m): m.events.append('push'); m.saved_matrix.append(m.matrix)
    def pop(m): m.events.append('pop'); m.matrix = m.saved_matrix.pop()
    def load(m): m.matrix = struct.unpack('<16f', m.read(m.r[4], 64))
    def projection(m):
        value = project(m.matrix, struct.unpack('<4f', m.read(m.r[5], 16)))
        m.r[2] = int(value is not None); m.write(m.r[4], struct.pack('<4i', *(value or (0, 0, -1, -1))))
    def subtract(m):
        left = struct.unpack('<4f', m.read(m.r[5], 16)); right = struct.unpack('<4f', m.read(m.r[6], 16))
        m.write(m.r[4], struct.pack('<4f', *(x-y for x, y in zip(left, right))))
    def pad(m): m.r[2] = RECORDS+m.u(m.r[4]+4)*448
    def begin(m): m.r[2] = m.cursor+16
    def end(m):
        m.events.append('sprite'); m.packets.append(m.read(m.cursor+16, m.r[4]-m.cursor-16)); m.cursor = m.r[4]
    c.callbacks = {0x120AB0: push, 0x120AC8: pop, 0x120B80: load, 0x1210D8: projection, 0x121ED8: subtract,
                   0x1DC2A0: pad, 0x100878: begin, 0x100890: end,
                   0x1DAA50: lambda m: m.calls.append(('clear', m.r[4], m.r[5])),
                   0x1DA9D0: lambda m: m.calls.append(('set', m.r[4], m.r[5])),
                   0x1E0290: lambda m: m.calls.append(('action', m.r[4], m.r[5])),
                   display.BAR_DRAW: lambda m: m.events.append('bars')}
    return c


def place(c, i, position, w=1.0):
    x, y, z = position
    c.write(MODELS[i]+2416, struct.pack('<4f', x, y, z, w))


def frame(c):
    c.r[29] = 0x1FFFF00; c.r[31] = 0xFEED0000
    saved = list(c.r[16:24]); fpu = list(c.f[20:32])
    stop = c.run(q.CODE, stops=(PREVIOUS,))
    assert stop == PREVIOUS and c.r[29] == 0x1FFFF00 and c.r[16:24] == saved and c.f[20:32] == fpu
    assert not c.saved_matrix
    return c.u(core.TABLE)


def press(c, raw, n=1, seat=0):
    """The native poller publishes the physical word into the pad record before every update."""
    for _ in range(n): c.w(RECORDS+448*seat+328, raw); frame(c)


def target(c, seat=0): return c.u(core.TABLE+4*seat)


def tap(c, seat=0, button=L3):
    press(c, button, seat=seat); press(c, 0, seat=seat)
    return target(c, seat)
