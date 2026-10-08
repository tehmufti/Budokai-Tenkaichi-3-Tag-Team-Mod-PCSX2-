"""Walk and run on the ground (approved authored revision 3; Mod settings > Movement).

Natively a fighter that moves on the ground glides just above it (action 13: anims 2 start / 3 loop, the turned
layer 4..7; action 14, the close-range movement around the target that also brakes a run, anims 8/9 and the
sideways layer 10/11). With 'Walk and run on the ground' on, a fighter in
those two actions on solid ground (not in flight mode, not in water) plays the clips of ground_clips.py instead and
moves at a percentage of its native ground speed: a walk below the set stick tilt, a run above it. CPU fighters
always run; so does a stick record with no analog reading (d-pad). Dashes, jumps, flight and water stay native.

Walk/run v2 (beta.38):
  - Ground speed follows the fighter's size: sqrt(leg / Goku's leg), clamped to 0.55..1.25 (ground_legs.py: one
    stride leg per character ID, read from the live model's +0x0C, times the model's uniform scale +0xA20 so the
    giants option counts; the body radius relative to Goku's when the table has no entry). 'Size changes ground
    speed' (on by default) switches the size factor and the step cap off. The speed settings multiply on top: a run
    at 100% is RUN_BASE of the native speed for Goku, a walk at the default 40% is about 0.54 units per tick.
  - Speed builds up over RAMP animation units (1/3 s, about 10 ticks) of the start clip.
  - A running human who reverses the stick by more than 120 degrees skids: the start clip replays and the speed
    drops to SKID_START, then builds up again.
  - The loop clip plays at the movement speed over the planted foot's speed (ground_clips.STANCE_SPEED x leg), with no
    rate clamp, so the feet stay planted; at most MAX_STEPS steps per second: a fighter that would need more is
    slowed to fit instead of sliding. Small-body directory aliases retain the approved gait, scaled to their legs.
  - Releasing the stick while running (action 14 straight from 13, no stick) plays the stop clip until the stick
    moves or the action ends.

Guest code only: it reads guest RAM and the fighters' own pad records, never host time, so a match plays out the
same everywhere (online lockstep). Nothing is installed while the option is off (build_memory returns no blocks and
the prepared match bytes equal beta.36).

Hooks (USA addresses, every one through A()):
  H1 DECODE  24C5D0/24C5D4 'lw v0,0xC0(v1); beqz v0,24C5F0' in the clip decoder 24C590 -> 'j DECODE; lw v0,...':
             for anims 2..11 of a captured fighter's model in action 13/14 on the ground, v0 = our clip (the
             directory row of the fighter's current set: gait + 2 x bounding, or the stop clip for 8/9 while
             braking); exits to 24C5DC (decode) or 24C5F0 (no clip). No calls, no stack; only t-registers and v1
             change (a1, a3, s-registers and sp are preserved).
  H2/H3 SPEED  'jal 1DE080' at 1EEF14 (action 13) and 1EF30C (action 14) -> 'jal SPEED': reads the size, picks the
             gait from the pad record (A(0x1DC2A0), which the controller modules hook, so P3/P4 and fusion routing
             hold), tracks the brake, restarts a base clip or the turned layer whose decoded source no longer
             matches (never while an animation request is queued), turns a landing into the run loop, ramps the
             speed through the start clip, starts a skid-turn, caps the speed, queues the loop phase increment
             (anim 3 in action 13, steps8/9 in action14) from actual movement, scales speed, and tail-jumps to
             1DE080 with the handler's own return address.
  H4 STEP    24D418, inside the native clock update after giant_options' entry trampoline: consumes that loop
             increment exactly once while the same decoded ground clip still owns the model, advances modulo
             the cycle length, and preserves the native rate word. Native/nonmovement animations take the original
             branch. Neither the bone evaluator nor the blend layers ever see a negative pre-step phase.
Settings apply from the next match: an installed match only rewrites CONTROL's settings words (Fight Again).
"""
from native_map import A, ACTOR_HZ, ADAPTER, CRC, FLAG, FLAG_BITS, SERIAL, elf_path
import math
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import battle_mode_policy as policy
import ground_clips as clips
import ground_legs
import ground_motion
import ground_root_motion
import mod_settings

BASE, END = 0x06F40000, 0x06F80000
DECODE, SPEED, STEP, CONTROL = BASE, BASE+0x400, BASE+0x1400, BASE+0x1800
ACTORS, DIRECTORY, FTABLE, CONSTS, LEGS, CLIPS = (BASE+0x1900, BASE+0x1C00, BASE+0x1D00, BASE+0x1E00, BASE+0x2000,
                                                  BASE+0x2400)
FEMALE_BITS, FEMALE_DIRECTORY = BASE+0x1E80, BASE+0x1F00
CLIPS_END = END-0x4000                 # per-character root-motion retargeting owns the tail reservation
MAGIC, VERSION = 0x47524E31, 3        # 'GRN1'
ROW = 0x40
CONTROL_SIZE = 0x100
KEYS = ('ground_running', 'ground_walk_tilt_percent', 'ground_walk_speed_percent', 'ground_run_speed_percent',
        'ground_size_speed')
# CONTROL: identity +0..+12 (+12 enabled), settings +16..+59 (rewritten on an installed match), +60 version,
# counters +64...
C = dict(magic=0, manager=4, count=8, enabled=12, run13=16, walk13=20, tilt2=24, run2=28, walk2=32, hold=36,
         run14=40, walk14=44, size_on=48, version=60)
COUNTERS = dict(substitutions=64, native_for_eligible=68, base_restarts=72, landing_restarts=76, gait_switches=80,
                speed_scalings=84, layer_invalidations=88, cadence_nudges=92, reconciles_skipped=96, skids=100,
                brakes=104, speed_caps=108)
# ACTORS row: gait (0 run, 1 walk), pending gait, hold count, base source, lean source (0 native, 1 + set k for our
# clips, OTHER another clip in layer 1), last substituted base anim, bounding (leg under SMALL), braking, the action
# of the previous update, skid (the start clip replays as a skid-turn), the stick reference direction (x, y floats),
# the fighter's ground position (x,z) at the previous update, queued phase increment and decoded-clip token.
R = dict(gait=0, pending=4, hold=8, base_src=12, lean_src=16, last_base=20, set=24, brake=28, prev_action=32,
         skid=36, refx=40, refy=44, posx=48, posz=52, step=56, step_clip=60)
OTHER = 7
# CONSTS: per clip set k (0..3) the planted-foot speed per animation unit per unit of leg, the speed cap per unit of
# leg, the loop clip's frame count (float bits); then the scalars.
CADENCE_CLOSE = 4                   # action14 keeps its48-unit native layer duration
K = dict(s=0, capk=20, floop=40, lref=60, lo=64, hi=68, small=72, ramp=76, ramp_start=80, skid_start=84,
         r_default=88, nchar=92, r_max=96)
HOLD = 4                # consecutive updates before a gait change (immediately while the start clip plays)
HYSTERESIS = 0.05       # stick tilt band around the threshold
NO_ANALOG2 = 0.0025     # x^2 + y^2 below this while moving: no analog reading (d-pad, released) -> run / brake
RUN_BASE = 0.59         # a run at 100%: this share of the native ground speed for Goku (2.4 of 4.07 units per tick)
WALK_BASE = 0.54/(4.074*0.40)       # a walk at the default 40%: 0.54 units per tick for Goku
SIZE_LO, SIZE_HI = 0.55, 1.25       # size factor clamp against Goku (balance)
MAX_STEPS = 9.0         # steps per second at most
RAMP = 20.0             # start clip time (animation units, 60 per second) to full speed: 1/3 s
RAMP_START, SKID_START = 0.1, 0.4
R_DEFAULT = 6.13        # the native body radius (model+0x1004) of a standard fighter, for the size fallback
R_MAX = 8.0             # sanity bound of a playback rate
MOVED_MIN = 0.02        # real movement (units per tick) under this is a stall: the cadence keeps the asked speed
BLEND = 0.15            # native request blend (1EEFE8)
ATTRIBUTE_SHARED = 0x20000000       # 1C3E60: an anim with this attribute decodes through 24D178 (shared clip)
BT4 = ADAPTER.startswith('bt4')

# Native sites (USA, through A()).
DECODE_SITE, DECODE_DELAY, DECODE_MOVE = A(0x24C5D0), A(0x24C5D4), A(0x24C5D8)
DECODE_CALL, DECODE_NULL, DECODE_FN = A(0x24C5DC), A(0x24C5F0), A(0x263278)
SPEED_SITES = (A(0x1EEF14), A(0x1EF30C))
STEP_SITE, STEP_NATIVE, STEP_ONCE = A(0x24D418), A(0x24D424), A(0x24D440)
STEP_WORDS = (0x8C830134, 0x50620008)  # lw v1,0x134(a0); beql v1,v0,24D440
# Native action handler table: action 13 (ground/air stick movement) and 14 (brake) hold the SPEED sites.
ACTION_TABLE = A(0x2C4980)
HANDLERS = ((13, A(0x1EED28)), (14, A(0x1EF0D8)))
MOVE = A(0x1DE080)
PAD_RECORD, REQUEST = A(0x1DC2A0), A(0x1C41A0)
MODELS = core.MODELS
LW_CLIP = 0x8C6200C0                # lw v0,0xC0(v1)
SPEED_DELAYS = (0x0200202D, 0x24050002)                       # move a0,s0 / addiu a1,zero,2
JUMP = lambda p: struct.pack('<2I', (2 << 26) | (p >> 2), 0)
CALL = lambda p: struct.pack('<I', (3 << 26) | (p >> 2))
F_GROUND, F_FLIGHT, F_WATER = FLAG(0xF), FLAG(0xE), FLAG(0x11)
PENDING = FLAG_BITS((0x2D, 0x2E))   # a queued animation request (1C41A0 / 1C41F0)
BASE_ANIMS, LEAN_ANIMS = (2, 3, 8, 9), (4, 5, 6, 7, 10, 11)
SET_ROWS = clips.SETS + (clips.STOP,)


def native():
    return elf_reader(elf_path(ROOT))[2]


def u32(data, p=0):
    return struct.unpack_from('<I', data, p)[0]


def f32bits(v):
    return struct.unpack('<I', struct.pack('<f', v))[0]


# ------------------------------------------------------------------------------------------ emit helpers

def fop(a, fn, d, s, t=0): a.emit((17 << 26) | (16 << 21) | (t << 16) | (s << 11) | (d << 6) | fn)
def mtc1(a, r, f): a.emit((17 << 26) | (4 << 21) | (r << 16) | (f << 11))
def lwc1(a, f, base, off=0): a.i(49, f, base, off)
def swc1(a, f, base, off=0): a.i(57, f, base, off)
def fconst(a, f, value, temp=9): a.li(temp, f32bits(value)); mtc1(a, temp, f)
def add_s(a, d, s, t): fop(a, 0, d, s, t)
def sub_s(a, d, s, t): fop(a, 1, d, s, t)
def mul_s(a, d, s, t): fop(a, 2, d, s, t)
def div_s(a, d, s, t): fop(a, 3, d, s, t)
def mov_s(a, d, s): fop(a, 6, d, s)
def c_olt(a, s, t): fop(a, 0x34, 0, s, t)          # condition = fs < ft
def bc1t(a, label): a.branch(17, 8, 1, label)
def bc1f(a, label): a.branch(17, 8, 0, label)


def sqrt_s(a, d, s):
    """d = sqrt(s). The EE's SQRT.S reads ft (standard MIPS: fs): both fields name s. Nops cover its latency."""
    a.emit(0); a.emit(0); fop(a, 4, d, s, s); a.emit(0); a.emit(0)


def bump(a, name, base=8, temp=9):
    a.li(base, CONTROL); a.lw(temp, base, COUNTERS[name]); a.addiu(temp, temp, 1); a.sw(temp, base, COUNTERS[name])


def flag_set(a, actor, flag, label, t1=9, t2=12):
    """Branch to label when the native actor flag (USA number already translated) is set (1DAC78 inline)."""
    a.i(36, t1, actor, 0x1085 + (flag >> 3)); a.i(36, t2, actor, 0x10AD + (flag >> 3)); a.r(0x25, t1, t1, t2)
    a.i(12, t1, t1, 1 << (flag & 7)); a.branch(5, t1, 0, label)


def pending(a, label):
    """Branch to label while s0's animation request is queued (t1, t4)."""
    a.i(36, 9, 16, 0x1085 + PENDING[0]); a.i(36, 12, 16, 0x10AD + PENDING[0]); a.r(0x25, 9, 9, 12)
    a.i(12, 9, 9, PENDING[1]); a.branch(5, 9, 0, label)


def gate(a, fail):
    """CONTROL belongs to this live captured match and the option is on; t0..t2 and t6 only, t2 = count."""
    a.li(8, CONTROL); a.lw(9, 8); a.li(14, MAGIC); a.branch(5, 9, 14, fail)
    a.lw(9, 8, C['manager']); a.lw(14, 28, -22364); a.branch(5, 9, 14, fail)
    a.lw(9, 8, C['enabled']); a.branch(4, 9, 0, fail)
    core.gate(a, fail)
    a.li(8, CONTROL); a.lw(9, 8, C['count']); a.branch(5, 9, 10, fail)


def ground(a, actor, fail):
    """Branch to fail unless the actor is in action 13/14 on the ground: flight mode and water clear."""
    a.lw(9, actor, 0x948); a.addiu(9, 9, -13); a.i(11, 9, 9, 2); a.branch(4, 9, 0, fail)
    tag = f'ground_{len(a.words)}'
    flag_set(a, actor, F_GROUND, tag)
    a.jump(fail); a.label(tag)
    flag_set(a, actor, F_FLIGHT, fail)
    flag_set(a, actor, F_WATER, fail)


def clip_set(a, out, row, anim, temp):
    """out = the row's clip set k: gait + 2 x bounding, or STOP for anims 8/9 (anim register) while braking."""
    tag = f'set_{len(a.words)}'
    a.lw(out, row, R['gait']); a.lw(temp, row, R['set']); a.r(0, temp, 0, temp, 1); a.r(0x21, out, out, temp)
    a.lw(temp, row, R['brake']); a.branch(4, temp, 0, tag)
    a.addiu(temp, anim, -8); a.i(11, temp, temp, 2); a.branch(4, temp, 0, tag)
    a.addiu(out, 0, clips.STOP)
    a.label(tag)


# ------------------------------------------------------------------------------------------ programs

def decode_code():
    """H1. In: a0 model, a1 dest, a3 out, t0 = 4*anim, v0 = the native clip pointer (the displaced load)."""
    a = Assembler(DECODE)
    a.r(2, 11, 0, 8, 2)                                   # t3 = anim
    a.addiu(12, 11, -2); a.i(11, 13, 12, 10)              # t5 = anim in 2..11
    gate(a, 'native')
    a.move(14, 0)                                         # t6 = i
    a.label('find'); a.branch(4, 14, 10, 'native')
    a.r(0, 15, 0, 14, 2); a.li(24, core.POINTERS); a.r(0x21, 24, 24, 15); a.lw(15, 24)   # t7 = actor
    a.branch(4, 15, 0, 'next')
    a.lw(24, 15, 12); a.i(11, 25, 24, 12); a.branch(4, 25, 0, 'next')
    a.r(0, 24, 0, 24, 2); a.li(25, MODELS); a.r(0x21, 25, 25, 24); a.lw(25, 25)
    a.branch(4, 25, 4, 'found')
    a.label('next'); a.addiu(14, 14, 1); a.jump('find')
    a.label('found')
    a.r(0, 24, 0, 14, 6); a.li(25, ACTORS); a.r(0x21, 24, 24, 25)                        # t8 = row
    a.branch(5, 13, 0, 'ours')
    # Another clip decoded into layer 1 (dest = *(model+0x1660) + 0xC000): the turned layer is no longer ours.
    a.lw(9, 4, 0x1660); a.li(12, 0xC000); a.r(0x21, 9, 9, 12); a.branch(5, 9, 5, 'native')
    a.addiu(9, 0, OTHER); a.sw(9, 24, R['lean_src']); a.jump('native')
    a.label('ours')
    # t2 = the row's source field for this anim's class (base 2/3/8/9, lean 4..7/10/11).
    a.r(2, 9, 0, 11, 1); a.addiu(10, 0, R['base_src'])
    a.addiu(12, 0, 1); a.branch(4, 9, 12, 'class')
    a.addiu(12, 0, 4); a.branch(4, 9, 12, 'class')
    a.addiu(10, 0, R['lean_src'])
    a.label('class'); a.r(0x21, 10, 24, 10)               # t2 = &row[class]
    ground(a, 15, 'ineligible')
    clip_set(a, 9, 24, 11, 12)                            # t1 = k
    a.r(0, 12, 0, 9, 3); a.r(0, 13, 0, 9, 1); a.r(0x21, 12, 12, 13); a.r(0x21, 12, 12, 11)
    a.addiu(12, 12, -2); a.r(0, 12, 0, 12, 2)
    # Select only this body's authored walking profile. Run, braking and side layers share identical data.
    a.li(13, DIRECTORY); a.lw(14, 4, 12); a.i(11, 15, 14, 256); a.branch(4, 15, 0, 'directory')
    a.i(12, 15, 14, 7); a.r(2, 14, 0, 14, 3); a.li(25, FEMALE_BITS); a.r(0x21, 25, 25, 14)
    a.i(36, 25, 25, 0); a.r(6, 25, 15, 25); a.i(12, 25, 25, 1); a.branch(4, 25, 0, 'directory')
    a.li(13, FEMALE_DIRECTORY)
    a.label('directory'); a.r(0x21, 12, 12, 13); a.lw(12, 12)
    a.branch(4, 12, 0, 'ineligible')
    a.move(2, 12)                                         # v0 = our clip
    a.addiu(9, 9, 1); a.sw(9, 10)                         # source = 1 + k
    a.addiu(13, 24, R['base_src']); a.branch(5, 10, 13, 'counted')
    a.sw(11, 24, R['last_base'])
    a.label('counted'); bump(a, 'substitutions'); a.jump('exit')
    a.label('ineligible'); a.sw(0, 10); bump(a, 'native_for_eligible')
    a.label('native'); a.branch(4, 2, 0, 'null')
    a.label('exit'); a.move(4, 2); a.jump(DECODE_CALL)
    a.label('null'); a.jump(DECODE_NULL)
    data = a.finish(); assert len(data) <= SPEED-DECODE; return data


SAVED = ((31, 0x00), (4, 0x08), (5, 0x10), (6, 0x18), (7, 0x20), (16, 0x28), (17, 0x30), (18, 0x38), (19, 0x40),
         (20, 0x48), (21, 0x50))
F12, F13, LEG, FACTOR, SX, SY, MAG2, FRAC, VEL, MOVED = 0x58, 0x5C, 0x60, 0x64, 0x68, 0x6C, 0x70, 0x74, 0x78, 0x7C
FRAME = 0x80


def speed_code():
    """H2/H3. In: a0 actor (delay slot), a1..a3 and f12 speed / f13 for 1DE080, ra = the handler's return.
    s0 actor, s1 row, s2 eligible, s3 action, s4 model (0: unknown), s5 human stick read (1)."""
    a = Assembler(SPEED)
    a.addiu(29, 29, -FRAME)
    for r, off in SAVED: a.i(63, r, 29, off)
    swc1(a, 12, 29, F12); swc1(a, 13, 29, F13)
    a.move(16, 4)                                         # s0 = actor
    gate(a, 'done')
    a.move(14, 0)
    a.label('find'); a.branch(4, 14, 10, 'done')
    a.r(0, 15, 0, 14, 2); a.li(24, core.POINTERS); a.r(0x21, 24, 24, 15); a.lw(15, 24)
    a.branch(4, 15, 16, 'found'); a.addiu(14, 14, 1); a.jump('find')
    a.label('found')
    a.r(0, 17, 0, 14, 6); a.li(9, ACTORS); a.r(0x21, 17, 17, 9)     # s1 = row
    a.sw(0, 17, R['step_clip'])                          # cadence is armed afresh by this movement update
    a.lw(19, 16, 0x948)                                   # s3 = action
    a.move(18, 0); ground(a, 16, 'eligible_done'); a.addiu(18, 0, 1)
    a.label('eligible_done')                              # s2 = eligible
    a.move(20, 0); a.move(21, 0)
    fconst(a, 0, 1.0); swc1(a, 0, 29, FRAC); swc1(a, 0, 29, FACTOR)
    a.sw(0, 29, SX); a.sw(0, 29, SY); a.sw(0, 29, MAG2)
    a.li(8, CONSTS); lwc1(a, 0, 8, K['lref']); swc1(a, 0, 29, LEG)

    # ---- size: s4 = model, LEG = stride leg x model scale, the row's bounding set, FACTOR ----
    a.branch(4, 18, 0, 'size_done')
    a.lw(9, 16, 12); a.i(11, 12, 9, 12); a.branch(4, 12, 0, 'size_done')
    a.r(0, 9, 0, 9, 2); a.li(12, MODELS); a.r(0x21, 12, 12, 9); a.lw(20, 12)       # s4 = model
    a.branch(4, 20, 0, 'size_done')
    a.li(8, CONSTS); lwc1(a, 0, 8, K['lref'])             # f0 = L (Goku's until known)
    a.lw(9, 20, 12); a.lw(12, 8, K['nchar']); a.r(0x2B, 12, 9, 12); a.branch(4, 12, 0, 'size_radius')
    a.r(0, 9, 0, 9, 2); a.li(12, LEGS); a.r(0x21, 12, 12, 9); a.lw(9, 12); a.branch(4, 9, 0, 'size_radius')
    lwc1(a, 0, 12); a.jump('size_scale')
    a.label('size_radius')                                # no table entry: the body radius relative to Goku's
    a.lw(12, 20, 0x1004); bad_float(a, 12, 'size_scale')
    mtc1(a, 12, 1); fconst(a, 2, 0.5); c_olt(a, 1, 2); bc1t(a, 'size_scale')
    fconst(a, 2, 512.0); c_olt(a, 2, 1); bc1t(a, 'size_scale')
    a.li(8, CONSTS); lwc1(a, 2, 8, K['r_default']); div_s(a, 1, 1, 2); mul_s(a, 0, 0, 1)
    a.label('size_scale')                                 # the model's uniform scale (giants option)
    a.lw(12, 20, 0xA20); bad_float(a, 12, 'size_leg')
    mtc1(a, 12, 1); fconst(a, 2, 0.25); c_olt(a, 1, 2); bc1t(a, 'size_leg')
    fconst(a, 2, 8.0); c_olt(a, 2, 1); bc1t(a, 'size_leg')
    mul_s(a, 0, 0, 1)
    a.label('size_leg')
    swc1(a, 0, 29, LEG)
    a.li(8, CONSTS); lwc1(a, 1, 8, K['small']); a.move(9, 0); c_olt(a, 0, 1); bc1f(a, 'size_set'); a.addiu(9, 0, 1)
    a.label('size_set'); a.sw(9, 17, R['set'])
    a.li(9, CONTROL); a.lw(9, 9, C['size_on']); a.branch(4, 9, 0, 'size_done')
    lwc1(a, 1, 8, K['lref']); div_s(a, 1, 0, 1); sqrt_s(a, 2, 1)                      # f2 = sqrt(L / Goku's)
    lwc1(a, 3, 8, K['lo']); c_olt(a, 2, 3); bc1f(a, 'size_lo'); mov_s(a, 2, 3)
    a.label('size_lo')
    lwc1(a, 3, 8, K['hi']); c_olt(a, 3, 2); bc1f(a, 'size_hi'); mov_s(a, 2, 3)
    a.label('size_hi'); swc1(a, 2, 29, FACTOR)
    a.label('size_done')

    # ---- gait (on the ground: action 13, and the close-range steps of action 14 while the stick is tilted) ----
    a.branch(4, 18, 0, 'gait_done')
    a.lw(9, 16, 0x1278); a.addiu(12, 0, 1); a.branch(4, 9, 12, 'want_run')      # CPU input
    a.move(4, 16); a.call(PAD_RECORD)
    lwc1(a, 0, 2, 304); lwc1(a, 1, 2, 308); swc1(a, 0, 29, SX); swc1(a, 1, 29, SY)
    mul_s(a, 2, 0, 0); mul_s(a, 3, 1, 1); add_s(a, 2, 2, 3); swc1(a, 2, 29, MAG2)
    a.addiu(21, 0, 1)                                     # s5 = a human stick reading
    a.li(8, CONTROL); a.lw(9, 8, C['tilt2']); a.branch(4, 9, 0, 'want_run')    # tilt 0: always run
    fconst(a, 3, NO_ANALOG2); c_olt(a, 2, 3); bc1f(a, 'analog')
    # No analog reading: a d-pad runs in action 13; action 14 keeps the gait (also the brake after a release).
    a.addiu(9, 0, 13); a.branch(4, 19, 9, 'want_run'); a.jump('gait_done')
    a.label('analog')
    a.li(8, CONTROL); lwc1(a, 3, 8, C['run2']); c_olt(a, 2, 3); bc1f(a, 'want_run')
    lwc1(a, 3, 8, C['walk2']); c_olt(a, 2, 3); bc1t(a, 'want_walk')
    a.lw(13, 17, R['gait']); a.jump('desired')
    a.label('want_run'); a.move(13, 0); a.jump('desired')
    a.label('want_walk'); a.addiu(13, 0, 1)
    a.label('desired')                                    # t5 = desired gait
    a.lw(9, 17, R['gait']); a.branch(5, 9, 13, 'differs')
    a.sw(13, 17, R['pending']); a.sw(0, 17, R['hold']); a.jump('gait_done')
    a.label('differs')
    a.lw(9, 16, 0x974); a.addiu(12, 0, 2); a.branch(4, 9, 12, 'commit')         # start clip: switch at once
    a.lw(9, 17, R['pending']); a.addiu(12, 0, 1); a.branch(5, 9, 13, 'restart_hold')
    a.lw(12, 17, R['hold']); a.addiu(12, 12, 1)
    a.label('restart_hold'); a.sw(13, 17, R['pending']); a.sw(12, 17, R['hold'])
    a.li(8, CONTROL); a.lw(9, 8, C['hold']); a.r(0x2A, 9, 12, 9); a.branch(5, 9, 0, 'gait_done')
    a.label('commit'); a.sw(13, 17, R['gait']); a.sw(13, 17, R['pending']); a.sw(0, 17, R['hold'])
    bump(a, 'gait_switches')
    a.label('gait_done')

    # ---- brake: a human in action 14 with the stick released, straight from a run (action 13) ----
    a.branch(4, 18, 0, 'brake_clear')
    a.addiu(9, 0, 14); a.branch(5, 19, 9, 'brake_clear')
    a.branch(4, 21, 0, 'brake_clear')
    lwc1(a, 2, 29, MAG2); fconst(a, 3, NO_ANALOG2); c_olt(a, 2, 3); bc1f(a, 'brake_clear')
    a.lw(9, 17, R['brake']); a.branch(5, 9, 0, 'brake_keep')
    a.lw(9, 17, R['prev_action']); a.addiu(12, 0, 13); a.branch(5, 9, 12, 'brake_clear')
    bump(a, 'brakes')
    a.label('brake_keep'); a.addiu(9, 0, 1); a.sw(9, 17, R['brake']); a.jump('brake_done')
    a.label('brake_clear'); a.sw(0, 17, R['brake'])
    a.label('brake_done'); a.sw(19, 17, R['prev_action'])

    # ---- reconcile and landing: never while an animation request is queued ----
    a.i(36, 9, 16, 0x1085 + PENDING[0]); a.i(36, 12, 16, 0x10AD + PENDING[0]); a.r(0x25, 9, 9, 12)
    a.i(12, 9, 9, PENDING[1]); a.branch(4, 9, 0, 'reconcile')
    bump(a, 'reconciles_skipped'); a.jump('ramp')
    a.label('reconcile')
    a.lw(9, 16, 0x974)                                    # t1 = base anim
    a.addiu(12, 0, 13); a.branch(5, 19, 12, 'brake')
    a.addiu(12, 9, -2); a.i(11, 12, 12, 2); a.branch(5, 12, 0, 'base_check'); a.jump('lean')
    a.label('brake')
    a.addiu(12, 0, 14); a.branch(5, 19, 12, 'lean')
    a.addiu(12, 9, -8); a.i(11, 12, 12, 2); a.branch(4, 12, 0, 'lean')
    a.label('base_check')
    desired_source(a, 13)
    a.lw(12, 17, R['base_src']); shared_clip(a, 'base_shared'); a.branch(4, 12, 13, 'lean')
    a.move(4, 16); a.move(5, 9); fconst(a, 12, BLEND); a.call(REQUEST)
    bump(a, 'base_restarts')
    a.label('lean')
    a.lw(9, 16, 0x980)
    a.addiu(12, 9, -4); a.i(11, 12, 12, 4); a.branch(5, 12, 0, 'lean_check')
    a.addiu(12, 9, -10); a.i(11, 12, 12, 2); a.branch(4, 12, 0, 'landing')
    a.label('lean_check')
    desired_source(a, 13)
    a.lw(12, 17, R['lean_src']); shared_clip(a, 'lean_shared'); a.branch(4, 12, 13, 'landing')
    a.addiu(12, 0, -1); a.sw(12, 16, 0x980); bump(a, 'layer_invalidations')
    a.label('landing')                                    # flight glide (0x18B) back on the ground -> run loop
    a.branch(4, 18, 0, 'ramp'); a.addiu(12, 0, 13); a.branch(5, 19, 12, 'ramp')
    a.lw(9, 16, 0x974); a.addiu(12, 0, 0x18B); a.branch(5, 9, 12, 'ramp')
    flag_set(a, 16, F_GROUND, 'land')
    a.jump('ramp')
    a.label('land'); a.move(4, 16); a.addiu(5, 0, 3); fconst(a, 12, BLEND); a.call(REQUEST)
    bump(a, 'landing_restarts')

    # ---- ramp: through our start clip (action 13) the speed builds from RAMP_START (SKID_START after a skid) ----
    a.label('ramp')
    a.branch(4, 18, 0, 'velocity'); a.addiu(12, 0, 13); a.branch(5, 19, 12, 'velocity')
    a.lw(9, 16, 0x974); a.addiu(12, 0, 2); a.branch(4, 9, 12, 'ramp_start')
    pending(a, 'skid'); a.sw(0, 17, R['skid']); a.jump('skid')                  # a finished skid-turn
    a.label('ramp_start')
    a.lw(9, 17, R['base_src']); a.branch(4, 9, 0, 'skid'); a.branch(4, 20, 0, 'skid')
    a.lw(12, 20, 0xC78); bad_float(a, 12, 'skid'); mtc1(a, 12, 0)                    # f0 = start clip time
    a.li(8, CONSTS); lwc1(a, 1, 8, K['ramp']); div_s(a, 0, 0, 1)
    a.move(9, 0); mtc1(a, 9, 1); c_olt(a, 0, 1); bc1f(a, 'ramp_low'); mov_s(a, 0, 1)
    a.label('ramp_low')
    fconst(a, 1, 1.0); c_olt(a, 1, 0); bc1f(a, 'ramp_high'); mov_s(a, 0, 1)
    a.label('ramp_high')
    a.li(8, CONSTS); lwc1(a, 2, 8, K['ramp_start'])
    a.lw(9, 17, R['skid']); a.branch(4, 9, 0, 'ramp_from'); lwc1(a, 2, 8, K['skid_start'])
    a.label('ramp_from')
    sub_s(a, 1, 1, 2); mul_s(a, 0, 0, 1); add_s(a, 0, 0, 2); swc1(a, 0, 29, FRAC)

    # ---- skid-turn: a running human whose stick turns more than 120 degrees from the run direction ----
    a.label('skid')
    a.branch(4, 21, 0, 'velocity')
    a.lw(9, 17, R['gait']); a.branch(5, 9, 0, 'velocity')
    lwc1(a, 2, 29, MAG2); fconst(a, 3, NO_ANALOG2); c_olt(a, 2, 3); bc1t(a, 'velocity')
    lwc1(a, 0, 29, SX); lwc1(a, 1, 29, SY)
    a.lw(9, 16, 0x974); a.addiu(12, 0, 3); a.branch(5, 9, 12, 'skid_ref')         # not the loop: follow the stick
    lwc1(a, 4, 17, R['refx']); lwc1(a, 5, 17, R['refy'])
    mul_s(a, 6, 4, 4); mul_s(a, 7, 5, 5); add_s(a, 6, 6, 7)                           # f6 = |ref|^2
    a.move(9, 0); mtc1(a, 9, 7); c_olt(a, 7, 6); bc1f(a, 'skid_ref')
    mul_s(a, 8, 0, 4); mul_s(a, 9, 1, 5); add_s(a, 8, 8, 9)                           # f8 = stick . ref
    c_olt(a, 8, 7); bc1f(a, 'skid_follow')
    mul_s(a, 9, 8, 8); mul_s(a, 10, 2, 6); fconst(a, 11, 0.25); mul_s(a, 10, 10, 11)
    c_olt(a, 10, 9); bc1f(a, 'skid_follow')               # cos^2 > 1/4 with a negative dot: beyond 120 degrees
    a.lw(9, 17, R['base_src']); a.branch(4, 9, 0, 'skid_follow')
    pending(a, 'velocity')
    a.move(4, 16); a.addiu(5, 0, 2); fconst(a, 12, BLEND); a.call(REQUEST)
    a.addiu(9, 0, 1); a.sw(9, 17, R['skid']); bump(a, 'skids')
    a.li(8, CONSTS); lwc1(a, 0, 8, K['skid_start']); swc1(a, 0, 29, FRAC)
    lwc1(a, 0, 29, SX); lwc1(a, 1, 29, SY); a.jump('skid_ref')
    a.label('skid_follow')                                # the reference eases halfway toward the stick
    fconst(a, 11, 0.5); sub_s(a, 6, 0, 4); mul_s(a, 6, 6, 11); add_s(a, 0, 4, 6)
    sub_s(a, 6, 1, 5); mul_s(a, 6, 6, 11); add_s(a, 1, 5, 6)
    a.label('skid_ref'); swc1(a, 0, 17, R['refx']); swc1(a, 1, 17, R['refy'])

    # ---- velocity: native x gait scale (action 13 or 14) x size, capped at MAX_STEPS steps per second ----
    a.label('velocity')
    a.branch(4, 18, 0, 'done')
    a.lw(9, 17, R['gait']); a.r(0, 9, 0, 9, 2); a.li(8, CONTROL); a.r(0x21, 9, 8, 9)
    a.addiu(12, 0, 13); a.branch(4, 19, 12, 'v13'); a.addiu(9, 9, C['run14'] - C['run13'])
    a.label('v13')
    lwc1(a, 4, 9, C['run13']); lwc1(a, 0, 29, F12); mul_s(a, 0, 0, 4); lwc1(a, 4, 29, FACTOR); mul_s(a, 0, 0, 4)
    a.lw(9, 8, C['size_on']); a.branch(4, 9, 0, 'v_done'); a.branch(4, 20, 0, 'v_done')
    a.lw(9, 17, R['brake']); a.branch(5, 9, 0, 'v_done')
    loop_set(a, 'v_slot')                                 # t4 = 4k + CONSTS
    lwc1(a, 4, 12, K['capk']); lwc1(a, 5, 29, LEG); mul_s(a, 4, 4, 5)
    c_olt(a, 4, 0); bc1f(a, 'v_done'); mov_s(a, 0, 4); bump(a, 'speed_caps')
    a.label('v_done'); swc1(a, 0, 29, VEL)
    # MOVED = the distance the fighter really moved since the previous update (actor +0x10/+0x18 against the row).
    lwc1(a, 4, 16, 0x10); lwc1(a, 5, 16, 0x18); lwc1(a, 6, 17, R['posx']); lwc1(a, 7, 17, R['posz'])
    swc1(a, 4, 17, R['posx']); swc1(a, 5, 17, R['posz'])
    sub_s(a, 6, 4, 6); sub_s(a, 7, 5, 7); mul_s(a, 6, 6, 6); mul_s(a, 7, 7, 7); add_s(a, 6, 6, 7)
    sqrt_s(a, 8, 6); swc1(a, 8, 29, MOVED)

    # ---- cadence: our loop (action 13 anim 3, action 14 anims 8/9) plays at speed / planted-foot speed ----
    a.label('cadence')
    a.branch(4, 20, 0, 'scale')
    a.lw(9, 16, 0x974)
    a.addiu(12, 0, 13); a.branch(5, 19, 12, 'cadence_14')
    a.addiu(12, 0, 3); a.branch(5, 9, 12, 'scale')
    a.lw(13, 17, R['gait']); a.lw(12, 17, R['set']); a.r(0, 12, 0, 12, 1); a.r(0x21, 13, 13, 12)
    a.addiu(13, 13, 1); a.lw(9, 17, R['base_src']); a.branch(5, 9, 13, 'scale')
    a.jump('cadence_clip')
    a.label('cadence_14')
    a.addiu(12, 9, -8); a.i(11, 12, 12, 2); a.branch(4, 12, 0, 'scale')
    a.lw(9, 17, R['brake']); a.branch(5, 9, 0, 'scale')
    a.lw(9, 17, R['base_src']); a.addiu(9, 9, -1); a.i(11, 9, 9, 4); a.branch(4, 9, 0, 'scale')
    a.label('cadence_clip')
    loop_set(a, 'c_slot')                                 # t4 = 4k + CONSTS
    a.lw(14, 12, K['floop']); a.lw(9, 20, 0xB44); a.branch(5, 9, 14, 'scale')       # the playing clip is ours
    mtc1(a, 14, 3)                                        # f3 = F
    a.lw(9, 20, 0xC80); bad_float(a, 9, 'scale')
    mtc1(a, 9, 7); fconst(a, 8, 0.25); c_olt(a, 7, 8); bc1t(a, 'scale')
    fconst(a, 8, 8.0); c_olt(a, 8, 7); bc1t(a, 'scale')  # f7 = rate0
    lwc1(a, 5, 12, K['s']); lwc1(a, 6, 29, LEG); mul_s(a, 5, 5, 6); mul_s(a, 5, 5, 7)   # planted foot per tick
    # The speed the feet keep pace with: the fighter's real movement since the previous update (the native movement
    # differs from the asked speed for some fighters and stick tilts, a giant is limited, a wall stops it), unless it
    # is a stall (under MOVED_MIN units) or a jump (over twice the asked speed + 1: the first update after a pause).
    lwc1(a, 9, 29, VEL); lwc1(a, 10, 29, MOVED)
    fconst(a, 11, MOVED_MIN); c_olt(a, 10, 11); bc1t(a, 'moved_ok')
    add_s(a, 11, 9, 9); fconst(a, 8, 1.0); add_s(a, 11, 11, 8); c_olt(a, 11, 10); bc1t(a, 'moved_ok')
    mov_s(a, 9, 10)
    a.label('moved_ok')
    div_s(a, 9, 9, 5)                                     # r = v / (S x L x rate0)
    a.move(9, 0); mtc1(a, 9, 10); c_olt(a, 9, 10); bc1f(a, 'r_low_ok'); mov_s(a, 9, 10)
    a.label('r_low_ok')
    a.li(8, CONSTS); lwc1(a, 10, 8, K['r_max']); c_olt(a, 10, 9); bc1f(a, 'r_ok'); mov_s(a, 9, 10)
    a.label('r_ok')
    # never more than a quarter cycle a tick (rate0 x r <= F/4), so a fast loop cannot alias
    fconst(a, 10, 0.25); mul_s(a, 10, 10, 3); div_s(a, 10, 10, 7); c_olt(a, 10, 9); bc1f(a, 'r_alias'); mov_s(a, 9, 10)
    a.label('r_alias')
    # Schedule one positive phase increment for the native animation step. Do not put a negative pre-step
    # time in the model: the bone evaluator can run before the native +rate and returns identity outside keys.
    # STEP consumes this token only while this same decoded loop and ground action still own the model.
    mul_s(a, 9, 9, 7); swc1(a, 9, 17, R['step'])
    a.lw(9, 20, 0xB40); a.sw(9, 17, R['step_clip']); bump(a, 'cadence_nudges')

    # ---- speed ----
    a.label('scale')
    lwc1(a, 0, 29, VEL); lwc1(a, 4, 29, FRAC); mul_s(a, 0, 0, 4); swc1(a, 0, 29, F12)
    bump(a, 'speed_scalings')
    a.label('done')
    lwc1(a, 12, 29, F12); lwc1(a, 13, 29, F13)
    for r, off in SAVED: a.i(55, r, 29, off)
    a.addiu(29, 29, FRAME)
    a.jump(MOVE)
    data = a.finish(); assert len(data) <= STEP-SPEED; return data


def step_code():
    """At the native clock update, a0=model+B40, v1=play mode. Preserve native/giant timing except one
    queued, still-owned ground loop. The first two native instructions are upstream of this hook, including
    giant_options' trampoline; the rate word is never changed, so no altered rate can leak into another action."""
    a = Assembler(STEP)
    gate(a, 'native')
    a.branch(4, 3, 0, 'native')                         # native frozen/stopped animation stays stopped
    a.move(11, 0)
    a.label('find'); a.branch(4, 11, 10, 'native')
    a.r(0, 12, 0, 11, 2); a.li(15, core.POINTERS); a.r(0x21, 15, 15, 12); a.lw(15, 15)
    a.branch(4, 15, 0, 'next')
    a.lw(12, 15, 12); a.i(11, 14, 12, 12); a.branch(4, 14, 0, 'next')
    a.r(0, 12, 0, 12, 2); a.li(14, MODELS); a.r(0x21, 14, 14, 12); a.lw(14, 14)
    a.addiu(14, 14, 0xB40); a.branch(4, 14, 4, 'found')
    a.label('next'); a.addiu(11, 11, 1); a.jump('find')
    a.label('found')
    a.r(0, 24, 0, 11, 6); a.li(25, ACTORS); a.r(0x21, 24, 24, 25)
    a.lw(25, 24, R['step_clip']); a.sw(0, 24, R['step_clip'])
    a.branch(4, 25, 0, 'native'); a.lw(9, 4); a.branch(5, 9, 25, 'native')
    ground(a, 15, 'native')
    a.lw(9, 15, 0x974); a.lw(12, 15, 0x948); a.addiu(14, 0, 13)
    a.branch(5, 12, 14, 'close')
    a.addiu(14, 0, 3); a.branch(5, 9, 14, 'native'); a.jump('phase')
    a.label('close'); a.addiu(9, 9, -8); a.i(11, 9, 9, 2); a.branch(4, 9, 0, 'native')
    a.lw(9, 24, R['brake']); a.branch(5, 9, 0, 'native')
    a.label('phase')
    a.lw(9, 24, R['base_src']); a.addiu(9, 9, -1); a.i(11, 9, 9, 4); a.branch(4, 9, 0, 'native')
    a.lw(9, 4, 0x138); bad_float(a, 9, 'native'); mtc1(a, 9, 0)
    lwc1(a, 1, 24, R['step']); lwc1(a, 2, 4, 4)
    # Normal operation is t in [0,F], step <= F/4. Bound legacy/corrupt phase before the tiny modulo loops.
    fconst(a, 3, 0.0); sub_s(a, 4, 3, 2); c_olt(a, 0, 4); bc1t(a, 'native')
    add_s(a, 4, 2, 2); c_olt(a, 4, 0); bc1t(a, 'native')
    swc1(a, 0, 4, 0x13C); add_s(a, 0, 0, 1)
    a.label('wrap_high'); c_olt(a, 0, 2); bc1t(a, 'wrap_low'); sub_s(a, 0, 0, 2); a.jump('wrap_high')
    a.label('wrap_low'); c_olt(a, 0, 3); bc1f(a, 'store'); add_s(a, 0, 0, 2); a.jump('wrap_low')
    a.label('store'); swc1(a, 0, 4, 0x138); a.jr()
    a.label('native')
    # Reproduce the displaced branch-likely and its delay slot, without altering the caller's model argument.
    a.addiu(2, 0, 1); a.branch(5, 3, 2, 'native_loop')
    lwc1(a, 1, 4, 0x138); a.jump(STEP_ONCE)
    a.label('native_loop'); a.jump(STEP_NATIVE)
    data = a.finish(); assert len(data) <= CONTROL-STEP; return data


def loop_set(a, tag):
    """t4 = CONSTS + 4k of the loop clip that carries the steps: action 13 the row's set (gait + 2 x bounding),
    action14 the close-range walk loop (anims8/9 keep their native48-unit layer duration)."""
    a.addiu(12, 0, CADENCE_CLOSE); a.addiu(9, 0, 13); a.branch(5, 19, 9, tag)
    a.lw(12, 17, R['gait']); a.lw(9, 17, R['set']); a.r(0, 9, 0, 9, 1); a.r(0x21, 12, 12, 9)
    a.label(tag); a.r(0, 12, 0, 12, 2); a.li(9, CONSTS); a.r(0x21, 12, 12, 9)


def desired_source(a, out):
    """out = 1 + set k while eligible (s2), else 0 (native). Uses s1 row, s2 eligible, t1 the anim, t6."""
    tag = f'source_{len(a.words)}'
    a.move(out, 0); a.branch(4, 18, 0, tag)
    clip_set(a, out, 17, 9, 14); a.addiu(out, out, 1)
    a.label(tag)


def shared_clip(a, tag):
    """Anims 8..11 (t1) are one clip for the run, walk and bounding sets (1..4): when the recorded source (t4) and the
    desired one (t5) are both among them they match (t5 = t4), so a gait change near the target restarts nothing.
    The stop clip (5) and another clip (OTHER) differ."""
    a.addiu(14, 9, -8); a.i(11, 14, 14, 4); a.branch(4, 14, 0, tag)
    a.addiu(14, 13, -1); a.i(11, 14, 14, 4); a.branch(4, 14, 0, tag)
    a.addiu(14, 12, -1); a.i(11, 14, 14, 4); a.branch(4, 14, 0, tag); a.move(13, 12)
    a.label(tag)


def bad_float(a, reg, fail):
    """Branch to fail when the float bits in reg are Inf/NaN-patterned (exponent all ones)."""
    a.li(13, 0x7F800000); a.r(0x24, 14, reg, 13); a.branch(4, 14, 13, fail)


def programs():
    return [(DECODE, decode_code()), (SPEED, speed_code()), (STEP, step_code())] + ground_root_motion.programs()


def hook_patches():
    return ([(DECODE_SITE, struct.pack('<2I', (2 << 26) | (DECODE >> 2), LW_CLIP))] +
            [(site, CALL(SPEED)) for site in SPEED_SITES] +
            [(STEP_SITE, struct.pack('<2I', (2 << 26) | (STEP >> 2), STEP_WORDS[0]))] + ground_root_motion.hook_patches())


# ------------------------------------------------------------------------------------------ data

def layout_profiles():
    """Male/female address maps, with identical run/side/brake clips stored only once."""
    mappings, pieces, p, placed = {}, [], CLIPS, {}
    for profile in ('male', 'female'):
        built = clips.build_set(profile=profile)
        where = mappings[profile] = {}
        for key in sorted(built):
            if built[key] in placed:
                where[key] = placed[built[key]]; continue
            where[key] = placed[built[key]] = p
            pieces.append((p, built[key])); p += len(built[key]) + 15 & ~15
    if p > CLIPS_END: raise ValueError('Ground clips exceed their reservation')
    return mappings['male'], mappings['female'], pieces


def layout():
    """Keep the original default map/pieces API for fixture builders and diagnostics."""
    male, _, pieces = layout_profiles()
    return male, pieces


def female_bits():
    out = bytearray(32)
    for character in ground_motion.female_characters(BT4):
        if not 0 <= character < 256: raise ValueError('Walking profile ID exceeds its table')
        out[character >> 3] |= 1 << (character & 7)
    return bytes(out)


def table_bytes(where):
    directory = struct.pack(f'<{10*len(SET_ROWS)}I', *(where[(g, a)] for g in SET_ROWS for a in clips.IDS))
    frames = struct.pack(f'<{10*len(SET_ROWS)}f', *(float(clips.FRAMES[(g, a)]) for g in SET_ROWS for a in clips.IDS))
    return directory, frames


def legs():
    return ground_legs.table(BT4)


def consts_bytes():
    # Four full walk/run sets, then the same walking motion resampled onto the native close-range timeline.
    # Its travel per complete cycle is identical; per-unit foot speed scales by the shorter duration.
    floop = [float(clips.LOOP_FRAMES[g]) for g in clips.SETS] + [float(clips.FRAMES[(clips.WALK, 8)])]
    s = [clips.STANCE_SPEED[g] for g in clips.SETS]
    s.append(clips.STANCE_SPEED[clips.WALK]*clips.LOOP_FRAMES[clips.WALK]/floop[CADENCE_CLOSE])
    cap = [MAX_STEPS/ACTOR_HZ*speed*frames/2 for speed, frames in zip(s, floop)]
    return struct.pack('<15f8fIf', *s, *cap, *floop, ground_legs.REFERENCE, SIZE_LO, SIZE_HI, ground_legs.SMALL, RAMP,
                       RAMP_START, SKID_START, R_DEFAULT, len(legs()), R_MAX)


def legs_bytes():
    return struct.pack(f'<{len(legs())}f', *legs())


def config_bytes(settings):
    s = settings
    tilt = s['ground_walk_tilt_percent']/100.0
    run2 = (tilt + HYSTERESIS)**2 if tilt else 0.0
    walk2 = max(tilt - HYSTERESIS, 0.0)**2 if tilt else 0.0
    run, walk = s['ground_run_speed_percent']/100.0, s['ground_walk_speed_percent']/100.0
    return struct.pack('<I5fI2fI2I', int(bool(s['ground_running'])), run*RUN_BASE, walk*WALK_BASE, tilt*tilt, run2,
                       walk2, HOLD, run, walk, int(bool(s['ground_size_speed'])), 0, 0)


def control_bytes(manager, count, settings):
    out = bytearray(CONTROL_SIZE)
    struct.pack_into('<3I', out, 0, MAGIC, manager, count)
    out[12:60] = config_bytes(settings)
    struct.pack_into('<I', out, C['version'], VERSION)
    return bytes(out)


def disc_check(read):
    """Raise ValueError unless every hook site holds the reviewed native instructions."""
    ground_root_motion.disc_check(read)
    w = lambda p: u32(read(p, 4))
    if w(DECODE_SITE) != LW_CLIP: raise ValueError('Clip decoder load changed (24C5D0)')
    branch = w(DECODE_DELAY)
    target = DECODE_DELAY + 4 + 4*(((branch & 0xFFFF) ^ 0x8000) - 0x8000)
    if branch >> 16 != 0x1040 or target != DECODE_NULL: raise ValueError('Clip decoder null test changed (24C5D4)')
    if w(DECODE_MOVE) != 0x0040202D or w(DECODE_CALL) != u32(CALL(DECODE_FN)) or w(DECODE_CALL+4) != 0x00E0302D:
        raise ValueError('Clip decoder call changed (24C5D8..24C5E0)')
    if w(DECODE_NULL) != 0x0000102D: raise ValueError('Clip decoder null exit changed (24C5F0)')
    if tuple(u32(read(STEP_SITE, 8), off) for off in (0, 4)) != STEP_WORDS:
        raise ValueError('Ground animation clock changed (24D418)')
    for site, delay in zip(SPEED_SITES, SPEED_DELAYS):
        if w(site) != u32(CALL(MOVE)) or w(site+4) != delay:
            raise ValueError(f'Ground movement call changed at {site:X}')
    for (action, handler), site in zip(HANDLERS, SPEED_SITES):
        if w(ACTION_TABLE + 4*action) != handler or not handler < site < handler + 0x400:
            raise ValueError(f'Native action {action} is not the reviewed handler')


def installed(ram):
    return len(ram) >= END and u32(ram, CONTROL) == MAGIC


def build_memory(ram, settings=None, source='<prepared>'):
    """The guarded install (or, over an installed match, the new settings words). Off on a match without the
    module returns no blocks before anything is scanned."""
    s = mod_settings.validate_settings(settings or {})
    if not installed(ram) and not s['ground_running']: return dict(blocks=[])
    if len(ram) != 0x8000000: raise ValueError('Ground running requires 128 MiB captured RAM')
    return _build(ram, s, source)


@policy.matching_install
def _build(ram, s, source):
    u = lambda p: u32(ram, p)
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if count not in policy.ACTOR_COUNTS or (u(core.MODE), u(core.MODE+8), u(core.MODE+12)) != (1, manager, count):
        raise ValueError('Ground running requires a captured active match')
    read = native()
    disc_check(read)
    code = programs()
    where, female, pieces = layout_profiles()
    directory, frames = table_bytes(where)
    female_directory, _ = table_bytes(female)
    data = [(DIRECTORY, directory), (FTABLE, frames), (CONSTS, consts_bytes()), (LEGS, legs_bytes()),
            (FEMALE_DIRECTORY, female_directory), (FEMALE_BITS, female_bits())] + \
            ground_root_motion.data_blocks([clips.build_set(profile='male'), clips.build_set(profile='female')])
    if installed(ram):
        if (u(CONTROL+4), u(CONTROL+8), u(CONTROL+C['version'])) != (manager, count, VERSION):
            raise ValueError('Ground running install belongs to another match')
        for p, d in code + hook_patches() + pieces + data:
            if ram[p:p+len(d)] != d: raise ValueError(f'Changed ground running program {p:08X}')
        patches = [(CONTROL+12, config_bytes(s))]
    else:
        if any(ram[BASE:END]): raise ValueError('Ground running reservation occupied')
        for site, d in hook_patches():
            if ram[site:site+len(d)] != read(site, len(d)): raise ValueError(f'Ground movement hook site changed {site:08X}')
        table = u(manager+0x20) if 0x100000 <= manager < 0x8000000-0x24 else 0
        if not (0x100000 <= table <= 0x8000000-4*414 and table % 4 == 0):
            raise ValueError('Animation attribute table unavailable')
        shared = [a for a in clips.IDS if u(table+4*a) & ATTRIBUTE_SHARED]
        if shared:
            raise ValueError(f'Ground running cannot replace shared animations {shared}: this disc decodes them '
                             'through another model (24D178)')
        patches = code + [(CONTROL, control_bytes(manager, count, s)), (ACTORS, bytes(ROW*12))] + data + pieces + \
            hook_patches()
    spans = sorted((p, p+len(d)) for p, d in patches)
    if any(e > q for (_, e), (q, _) in zip(spans, spans[1:])): raise ValueError('Ground running patches overlap')
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex())
              for p, d in patches if ram[p:p+len(d)] != d]
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL, blocks=blocks,
                enabled=bool(s['ground_running']), clips=clips.CLIP_SET_SHA256,
                telemetry={k: CONTROL+v for k, v in COUNTERS.items()},
                notes=['Walk and run on the ground: approved retargeted clips for actions 13/14 on solid ground, gait from '
                       'the stick tilt, speed scaled by the setting and the fighter\'s size, feet planted.'])


def telemetry(ram):
    return {k: u32(ram, CONTROL+v) for k, v in COUNTERS.items()} if installed(ram) else None
