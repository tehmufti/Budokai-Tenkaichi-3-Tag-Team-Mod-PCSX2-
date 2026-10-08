"""Beam struggle options for captured team matches (beta.37/38): longer struggles and early wins, hits on the two
struggling fighters, and team assists (beta.38: splash damage removed; the assist is R3 near the struggling ally).

Beam assist (beta.38): once per coordinator tick of the push stage, a living ally of exactly one struggler within
beam_assist_range (flat, model centres) who is not busy, has a blast stock and whose side has a free assist slot
assists: a human on a new R3 press with no face/shoulder button held (R3 is then hidden from that player's own pad
record until released, so the native R3 action does not fire), a CPU on the fixed schedule.

beta.40: up to MAX_ASSISTS (4) teammates per side, each in its own slot (CONTROL SLOTS, 8 records). A new assister
first plays a short transition (P_MOVING, TRANSITION_TICKS = 0.5 s): the native fly-in action TRANSITION_ACTION while
it glides (eased) from where it stood to its formation spot; only then is it asked into the ally's struggle action
(P_PENDING, beta.39's pose gate). Nothing is paid until the assister is seen in the struggle action (STEP every
running tick, or POSE from its own struggle handler): CONFIRM then pays that assister's blast stock, adds its own
bonus share (beam_assist_multiplier_percent - 100) to the side's multiplier (capped at MAX_SIDE_MULT) and starts
'BEAM ASSIST Xm' (the side's multiplier after that assist). Until then the request is repeated every tick; after
PEND_TICKS, or when it is hit, falls or the struggle ends, FAIL cancels that slot (nothing paid, a waiting request
withdrawn, it may assist again) with 'ASSIST FAILED - BUSY/BLOCKED/HIT'; a human's R3 while its current action is
busy says BUSY too. Only once a human assister's pose has taken does its own view switch to the struggling ally
(VIEWSET: the view's subject word now names the ally) for the rest of the struggle; SWEEP restores it at frame start
as soon as the struggle stops running or the assister leaves the pose.
Formation (FORMATION, in units behind the ally away from the enemy struggler and to its side): slot 0/1 close behind
and beside the ally on either side, slot 2/3 a step further back and wider; the first slot takes the side nearer the
drawn camera. The posed assister is re-placed every update (the struggle action does not hold it in the air). Every
spot is clamped into the live arena and never left inside the terrain (spawn_placement's floor query). While posed
its own struggle handler's flag call keeps its armour and, once the struggle ends or it falls, sets the native
'struggle over' flag (0xC3) so it returns to idle.
Multipliers: side multiplier = 100 + share * confirmed assists (%), at most MAX_SIDE_MULT (x3); it scales that side's
push; the end damage (and the cinematic ending's hits) use min(MAX_MULT, side0 * side1 / 100) (x4 at most).

Beam clash camera (beta.40, beam_clash_camera): 'clash' (native) lets the struggle script the camera of the fighter it
frames (1C6E78, re-armed every update; in split screen an ultimate-beam struggle then owns one shared view); 'keep'
skips those three script calls (KEEPCAM) so every view, split or single, keeps following its own player.

Guest code only: it reads guest RAM and the fighters' own decoded inputs, never host time or randomness, so a
match plays out the same everywhere (online lockstep). Nothing is installed while every option holds its legacy
value: build_memory then returns no blocks and the prepared match bytes equal beta.36.

Hooks (USA addresses, every one through A(); each installs only while its option group is on):
  G1 clock      1D8FD0/1D8FD4 struggle end test -> ENDCHECK; 1D8F58 meter step -> TUG (returns to 1D8F84)
  G2 push       1FB9CC..1FB9D4 'strength += INC' -> jal PUSH (per accepted input; q8 accumulator)
  G3 tick       five 'jal 1DABE8' struggle-flag calls 1FB960 + 0xC*k -> jal FLAGS (TICKBLOCK, assists, POSE)
  G4 hits       1CB6A8 ki-blast action immunity -> jal KIBLAST; beam_clash.CONTACT entry -> j PRE (trampoline)
  G5 end damage 1D922C 'jal 1CE630' (struggle loser) -> jal DMG
  G6 hits       1D9178 'jal 1CA6D0' (cinematic winner) -> jal CINE; every guest_killfeed.ATTRIBUTION call
                site 'jal 1CE630' -> jal STUB (attacker register into v1) -> HIT
  G7 caption    one guarded DRAW call per view through viewport_hud's per-view HUD extension list
  G8 camera     the struggle's three 'jal 1C6E78' scripted-camera calls 1D8B54/1D8CD0/1D8DEC -> jal KEEPCAM
An installed match only turns groups inert through CONFIG; it never gains groups. Settings apply from the next
match.
"""
from native_map import A, ACTOR_HZ, CRC, FLAG, SERIAL, elf_path
import math
import struct
from prototype import Assembler, ROOT, elf_reader
from input_script import RECORDS
import coop_controller as coop
import fresh_team_combat as core
import team_participation as part
import fresh_team_camera as camera
import team_intro
import result_presentation
import beam_clash as beam
import extra_throws as throws
import team_participation as participation
import battle_mode_policy as policy
import cinematic_contact_guard as contact
import guest_killfeed as feed
import viewport_hud as hud
import arena_bounds
import spawn_placement as terrain
import mod_settings
from regional import Y_ORIGIN, screen_y

BASE, END = 0x07250000, 0x07258000
GATE, RUNNING, SYNC, ENDCHECK = BASE, BASE+0x100, BASE+0x200, BASE+0x300
TUG, PUSH, FLAGS, TICKBLOCK = BASE+0x400, BASE+0x700, BASE+0xA00, BASE+0xC00
FREE, SLOTOF, FAILCAP, SWEEP = BASE+0xE00, BASE+0xE80, BASE+0xF00, BASE+0x1000   # beta.40 assist slots
KIBLAST, DMG, CINE, HIT, STUBS = BASE+0x1300, BASE+0x1400, BASE+0x1700, BASE+0x1800, BASE+0x1C00
KEEPCAM = BASE+0x1D00                                                              # beta.40 camera option
PRE, BYSTANDER, TRAMPOLINE = BASE+0x2200, BASE+0x2500, BASE+0x2800   # +0x1D00: the beta.38 PLACE (moved)
REGISTER, MULTIPLIER, DRAW = BASE+0x1E00, BASE+0x2B00, BASE+0x2C00   # beta.40: REGISTER moved (was +0x2900)
ASSIST, POSE = BASE+0x3400, BASE+0x3C00            # beta.38 assist (the beta.37 one at +0xE00 is gone)
FRAMESTUB, R3PRE, ELIGIBLE = BASE+0x4000, BASE+0x4100, BASE+0x4800   # frame-start R3 (team_participation FRAME)
VIEWSET, PLACE = BASE+0x4E00, BASE+0x5400          # beta.40: the assisting human's view; the formation spot
FLOOR, QUERY, REFUSE = BASE+0x5C00, BASE+0x5E00, BASE+0x4600                                               # and its terrain check
CONFIRM, FAIL, STEP = BASE+0x6000, BASE+0x6300, BASE+0x6500   # beta.40 (STEP replaces beta.39's PENDING)
TEXT, CONTROL = BASE+0x6C00, BASE+0x7000
MAGIC, VERSION = 0x424D5331, 2        # 'BMS1'; version 2 = beta.40 (assist slots)
STUB_SIZE = 16
# CONTROL identity (+0x00..+0x1F), CONFIG (+0x20..+0x6F, rewritten on every build), STATE (+0x100..+0x1BF,
# per struggle), TELEMETRY (+0x1C0.., counters only), ASSIST_STATE (+0x220..+0x23F, across struggles: R3 latches),
# more TELEMETRY (+0x240..+0x27F), SLOTS (+0x280..+0x47F, beta.40: one record per assister, across struggles until
# its release). CONFIG +0x44..+0x4C and +0x54 held the removed splash options (beta.37); beta.40 uses +0x44 for the
# camera option (1 = keep player views) and +0x48/+0x4C for the assist transition (action, ticks); +0x54 stays 0;
# +0x50 is the assist range squared (float).
C = dict(magic=0x00, manager=0x04, count=0x08, battle=0x0C, version=0x10, intro=0x14, limit_native=0x18, inc=0x1C,
         limit=0x20, rule=0x24, clamp=0x28, margin_inputs=0x2C, margin_strength=0x30, seed_cap=0x34, cpu_pct=0x38,
         interference=0x3C, penalty_pct=0x40, camera=0x44, trans_action=0x48, trans_ticks=0x4C, range2=0x50,
         assist=0x58, assist_step=0x5C, assist_cpu=0x60, max_mult=0x64, caption_ticks=0x68,
         groups=0x6C,
         serial=0x100, end_now=0x104, last_counter=0x10C, last_age=0x110,
         side=0x120, last0=0x160, last1=0x164, tug_acc=0x168,
         pending_winner=0x170, pending_loser=0x174, pending_mult=0x178, pending_serial=0x17C, masks=0x180,
         # per side (+4*side), in STATE: the last failure's reason (F_*) and age (its caption).
         fail=0x198, fail_age=0x1A0,
         r3_last=0x220, r3_mask=0x224, r3_req=0x238, frame_prev=0x23C)
P_NONE, P_PENDING, P_CONFIRMED, P_FAILED, P_MOVING = 0, 1, 2, 3, 4
F_BUSY, F_BLOCKED, F_HIT = 1, 2, 3
FAIL_TEXTS = ('ASSIST FAILED - BUSY', 'ASSIST FAILED - BLOCKED', 'ASSIST FAILED - HIT')
SIDE = dict(mult=0x0, acc=0x4, hp_start=0x8, hp_max=0xC, presses=0x10, gained=0x14, assists=0x18, assist_age=0x1C)
SIDE_STRIDE = 0x20
TELEMETRY = dict(struggles=0x1C0, tug_early_wins=0x1C4, limit_ends=0x1C8, clamp_hits=0x1CC, pushes_scaled=0x1D0,
                 flags_skipped=0x1D4, kiblast_bypassed=0x1D8, contacts_allowed=0x1DC, shot_contacts_allowed=0x1E0,
                 end_damage_scaled=0x1E4, last_end_damage=0x1E8, cine_pending_set=0x1EC, cine_scaled_hits=0x1F0,
                 assists_human=0x1FC, assists_cpu=0x200, assist_no_stock=0x204, cine_pending_cleared=0x210,
                 r3_consumed=0x1F4, posed=0x1F8, released=0x208, placed=0x20C, holds=0x214,
                 # beta.39: assists requested, confirmed (posed: the bonus paid), failed by reason, re-requests
                 # while pending, requests found overwritten before the next one, per-frame re-placements.
                 triggers=0x240, confirmed=0x244, fail_busy=0x248, fail_blocked=0x24C, fail_hit=0x250,
                 rerequests=0x254, overridden=0x258, replaced=0x25C, refused=0x260, last_override=0x264, floor_queries=0x268,
                 lifted=0x26C, kept_camera=0x270,
                 # beta.40: transitions finished (pose then asked), views switched to the ally and given back.
                 moved=0x274, view_switched=0x278, view_restored=0x27C)
SLOTS, SLOT_STRIDE = 0x280, 0x40
# Slot record: assister actor (0 = free), struggle serial, state (P_*), age of the state's start, failure reason,
# re-requests, the action last seen while pending, aside sign (float +-1, 0 = unset), transition start X/Y/Z (floats),
# the switched view's subject word, its old and new values, the assister's physical index, its formation index.
S = dict(actor=0x00, serial=0x04, state=0x08, age=0x0C, fail=0x10, tries=0x14, seen=0x18, sign=0x1C,
         sx=0x20, sy=0x24, sz=0x28, view=0x2C, view_old=0x30, view_new=0x34, phys=0x38, k=0x3C)
CONTROL_SIZE = 0x480
STATE_LO, STATE_HI = 0x104, 0x1C0
# Install groups (CONTROL+0x6C bits).
G_CLOCK, G_PUSH, G_TICK, G_HITS, G_END, G_CINE, G_CAPTION, G_CAMERA = (1 << i for i in range(8))
GROUP_NAMES = {G_CLOCK: 'clock', G_PUSH: 'push', G_TICK: 'tick', G_HITS: 'interference', G_END: 'end damage',
               G_CINE: 'hit damage', G_CAPTION: 'caption', G_CAMERA: 'camera'}

KEYS = ('beam_clash_camera', 'beam_struggle_length', 'beam_struggle_push_ahead', 'beam_struggle_cpu_power_percent',
        'beam_struggle_interference', 'beam_struggle_damage_penalty_percent', 'beam_assist_enabled',
        'beam_assist_multiplier_percent', 'beam_assist_cpu', 'beam_assist_range')
# Removed in beta.38 (splash damage): an older saved mod-settings.json may still hold them; loading drops them.
REMOVED_KEYS = ('beam_clash_splash', 'ultimate_splash', 'splash_damage_percent', 'splash_radius',
                'splash_friendly_fire')
LENGTHS = {'native': 1, 'long': 2, 'very_long': 4}
CAMERAS = ('clash', 'keep')     # beam_clash_camera: the struggle's scripted camera (native) or every player's own view
STOCK = 100000                  # one blast stock in the HP row (+20)
MAX_MULT = 400                  # combined end-damage multiplier cap (%)
MAX_SIDE_MULT = 300             # one side's multiplier cap (%): push and its share of the end damage
DAMAGE_CAP = 2 * 10**6
NATIVE_CLAMP = 40               # meter clamp for long struggles under the native rule (two-fighter camera)
MAX_ASSISTS = 4                 # beta.40: up to four assisters per side, one formation slot each
R3, FACE_SHOULDER = 0x4, 0xFF00  # raw pad bits (input_script): R3 alone, no L1/L2/R1/R2/face button held
PRESS_WORDS = (328, 336, 340)    # the pad record's held word and both pressed words (lockon_select's mask set)
# beta.40 formation (world units): (behind the ally, away from the enemy struggler; to its side). Slot 0/1 close
# behind and beside the ally, slot 2/3 a step further back and wider; no two spots closer than ~14 units. The
# first slot of a side takes the side nearer the drawn camera (sign kept for that assister).
FORMATION = ((7.0, 12.0), (7.0, -12.0), (17.0, 24.0), (17.0, -24.0))
ARENA_MARGIN = 10.0
TRANSITION_TICKS = math.ceil(0.5 * ACTOR_HZ)   # the fly-in before the pose (eased glide to the formation spot)
TRANSITION_ACTION = 15                       # native forward dash played during it (probed live, beta.40)
PEND_TICKS = math.ceil(0.5 * ACTOR_HZ)   # an assist not posed within this many ticks fails (nothing is paid)
CAPTION_COLOR, OUTLINE_COLOR = 0x80A0FFFF, 0x80000000
CAPTION_Y = -130              # above the native struggle stick prompt (bottom-left), LOOKed live
BUSY_ACTIONS = ((183, 61), (253, 63))       # an assister must not be in a throw/hit-reaction or cinematic action
SOURCE_BUSY = ((183, 5), (253, 63))          # a bystander source must not be throwing or in any cinematic action

# Native sites (USA, through A()). Literal arguments: release_tools/build_pal_map.py maps every one of them.
END_TEST, END_BRANCH, END_STORE, END_ZERO = A(0x1D8FD0), A(0x1D8FD4), A(0x1D8FD8), A(0x1D8FDC)
LOOP, INTRO_SITE = A(0x1D8EE4), A(0x1D8F30)
TUG_SITE, TUG_RETURN = A(0x1D8F58), A(0x1D8F84)
PUSH_SITE, INC_SITE = A(0x1FB9CC), A(0x1FB9D0)
FLAG_SITES = (A(0x1FB960), A(0x1FB96C), A(0x1FB978), A(0x1FB984), A(0x1FB990))
FLAG_SETTER = A(0x1DABE8)
DMG_SITE, CINE_SITE, KIBLAST_SITE = A(0x1D922C), A(0x1D9178), A(0x1CB6A8)
DAMAGE, CINEMATIC, ACTION_IMMUNE = A(0x1CE630), A(0x1CA6D0), A(0x1E03A8)
# beta.38 assist: pad record resolver, action request, sector lookup, root setter, model transform refresh, root
# sync and the facing angle (the p50 probe's and cinematic_position.commit's sequence).
PAD_RECORD, SET_ACTION, SET_FLAG = A(0x1DC2A0), A(0x1E0290), A(0x1DA9D0)
FACING, SECTOR, SET_ROOT = A(0x241F10), A(0x23FF78), A(0x1D7418)
MODEL_REFRESH = (A(0x24E2B0), A(0x24E3F8))
MODEL_SPHERES, ROOT_SYNC = A(0x24DC58), A(0x1D70E8)
FLOOR_NATIVES = (A(0x230B38), A(0x1B14C0))   # beta.39: spawn_placement's floor query (QUERY) calls these
SCRIPT_CAMERA = A(0x1C6E78)                   # beta.40: the actor-local scripted camera the struggle re-arms
CAMERA_SITES = (A(0x1D8B54), A(0x1D8CD0), A(0x1D8DEC))   # intro/winner/resolve, push, clash-contact shots
RELEASE_FLAG = FLAG(0xC3)
FLAG_IDS = (FLAG(0x42), FLAG(0x43), FLAG(0x44), FLAG(0x45), FLAG(0x46))
SKIPPED = (0, 2, 4)             # F0 (0x42 melee), F2 (0x44 ki blasts), F4 (0x46); 0x43 (class 85, grabs) and 0x45 stay
# Native words at the sites (immediates checked separately).
END_WORDS = (0x28430000, 0x14600000, 0xAE220000, 0xAE200000)
TUG_WORDS = (0x10400005, 0x02D5102A, 0x8E220008, 0x24420001, 0xAE220008, 0x02D5102A, 0x50400005, 0xC62C000C,
             0x8E220008, 0x2442FFFF, 0xAE220008)
PUSH_WORDS = (0x8E220E4C, 0x24420000, 0xAE220E4C)
DADDU_A0_S1 = 0x0220202D
JUMP = lambda p: struct.pack('<2I', (2 << 26) | (p >> 2), 0)
CALL = lambda p: struct.pack('<I', (3 << 26) | (p >> 2))


def native():
    return elf_reader(elf_path(ROOT))[2]


def u32(data, p=0):
    return struct.unpack_from('<I', data, p)[0]


# ------------------------------------------------------------------------------------------ disc constants

def disc_constants(read):
    """INTRO_END, LIMIT, INC and the flag immediates, read from one executable (or RAM).

    Raises ValueError unless every site holds the reviewed instruction pattern."""
    w = lambda p: u32(read(p, 4))
    intro = w(INTRO_SITE)
    if intro & 0xFFFF0000 != 0x28620000: raise ValueError('Beam struggle intro test is not the reviewed slti')
    words = [w(END_TEST + 4*i) for i in range(4)]
    if words[0] & 0xFFFF0000 != END_WORDS[0] or words[2:] != list(END_WORDS[2:]):
        raise ValueError('Beam struggle end test is not the reviewed pattern')
    target = END_BRANCH + 4 + 4*(((words[1] & 0xFFFF) ^ 0x8000) - 0x8000)
    if words[1] & 0xFFFF0000 != END_WORDS[1] or target != LOOP: raise ValueError('Beam struggle end branch changed')
    tug = [w(TUG_SITE + 4*i) for i in range(len(TUG_WORDS))]
    if tug != list(TUG_WORDS) or TUG_SITE + 4*len(TUG_WORDS) != TUG_RETURN:
        raise ValueError('Beam struggle meter step is not the reviewed block')
    push = [w(PUSH_SITE + 4*i) for i in range(3)]
    if push[0] != PUSH_WORDS[0] or push[1] & 0xFFFF0000 != PUSH_WORDS[1] or push[2] != PUSH_WORDS[2]:
        raise ValueError('Beam struggle push is not the reviewed pattern')
    flags = []
    for site in FLAG_SITES:
        if w(site-4) != DADDU_A0_S1 or w(site) != u32(CALL(FLAG_SETTER)) or w(site+4) & 0xFFFF0000 != 0x24050000:
            raise ValueError(f'Beam struggle flag call changed at {site:X}')
        flags.append(w(site+4) & 0xFFFF)
    if tuple(flags) != FLAG_IDS: raise ValueError(f'Beam struggle flag numbers differ: {flags}')
    for site, callee, delay in ((DMG_SITE, DAMAGE, 0x0240202D), (CINE_SITE, CINEMATIC, 0x0040382D),
                                (KIBLAST_SITE, ACTION_IMMUNE, 0x0040202D)):
        if w(site) != u32(CALL(callee)) or w(site+4) != delay:
            raise ValueError(f'Beam struggle call site changed at {site:X}')
    for site in CAMERA_SITES:
        if w(site) != u32(CALL(SCRIPT_CAMERA)): raise ValueError(f'Beam struggle camera call changed at {site:X}')
    inc = push[1] & 0xFFFF
    limit = words[0] & 0xFFFF
    intro &= 0xFFFF
    if not (0 < intro < limit < 0x400 and 1 <= inc <= 16): raise ValueError('Unexpected beam struggle constants')
    return dict(intro=intro, limit=limit, inc=inc, flags=tuple(flags))


# ------------------------------------------------------------------------------------------ settings

def legacy(settings):
    s = settings
    return (s['beam_struggle_length'] == 'native' and s['beam_struggle_push_ahead'] == 0 and
            s['beam_struggle_cpu_power_percent'] == 100 and not s['beam_struggle_interference'] and
            not s['beam_assist_enabled'] and s['beam_clash_camera'] == 'clash')


def groups(settings):
    s = settings
    interference, assist = s['beam_struggle_interference'], s['beam_assist_enabled']
    mask = 0
    if s['beam_struggle_length'] != 'native' or s['beam_struggle_push_ahead'] > 0: mask |= G_CLOCK
    if s['beam_struggle_push_ahead'] > 0 or s['beam_struggle_cpu_power_percent'] != 100 or interference or assist:
        mask |= G_PUSH
    if interference or assist: mask |= G_TICK
    if interference: mask |= G_HITS
    # The assist's multiplier scales the end damage and the cinematic ending's hits (attribution sites).
    if assist: mask |= G_END | G_CINE | G_CAPTION
    if s['beam_clash_camera'] == 'keep': mask |= G_CAMERA
    return mask


def length_limit(length, intro, limit):
    return intro + (limit - intro) * LENGTHS[length]


def config_bytes(settings, consts, mask):
    s = settings
    intro, limit, inc = consts['intro'], consts['limit'], consts['inc']
    ahead = s['beam_struggle_push_ahead']
    rule = int(ahead > 0)
    clamp = NATIVE_CLAMP if (not rule and s['beam_struggle_length'] != 'native') else 0
    margin = ahead * inc
    reach = float(s['beam_assist_range'])
    caption = math.ceil(3 * ACTOR_HZ)
    out = bytearray(0x50)
    struct.pack_into('<12I', out, 0, length_limit(s['beam_struggle_length'], intro, limit), rule, clamp, ahead, margin,
                     margin // 2, s['beam_struggle_cpu_power_percent'], int(s['beam_struggle_interference']),
                     s['beam_struggle_damage_penalty_percent'], int(s['beam_clash_camera'] == 'keep'),
                     TRANSITION_ACTION, TRANSITION_TICKS)
    struct.pack_into('<f7I', out, 0x30, reach * reach, 0, int(s['beam_assist_enabled']),
                     s['beam_assist_multiplier_percent'] - 100, int(s['beam_assist_cpu']), MAX_MULT, caption, mask)
    return bytes(out)


def side_multiplier(step, count):
    """One side's multiplier (%) after `count` confirmed assists of share `step` each (MAX_SIDE_MULT cap)."""
    return min(MAX_SIDE_MULT, 100 + step * count)


def multiplier_text(step, count):
    value = side_multiplier(step, count) / 100
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def text_bytes(settings):
    """TEXT: the side's caption after 1..MAX_ASSISTS assists (32 bytes each), the R3 hint, the failure captions."""
    import localization
    step = settings['beam_assist_multiplier_percent'] - 100
    captions = b''.join(localization.slot(f'BEAM ASSIST X{multiplier_text(step, n)}', 32)
                        for n in range(1, MAX_ASSISTS+1))
    return captions + localization.slot('R3 - BEAM ASSIST', 32) + b''.join(localization.slot(t, 32) for t in FAIL_TEXTS)


HINT_TEXT, FAIL_TEXT = TEXT + 32*MAX_ASSISTS, TEXT + 32*(MAX_ASSISTS+1)


# ------------------------------------------------------------------------------------------ emit helpers

def fop(a, fn, d, s, t=0): a.emit((17 << 26) | (16 << 21) | (t << 16) | (s << 11) | (d << 6) | fn)
def mtc1(a, r, f): a.emit((17 << 26) | (4 << 21) | (r << 16) | (f << 11))
def mfc1(a, r, f): a.emit((17 << 26) | (r << 16) | (f << 11))
def cvt_s_w(a, d, s): a.emit((17 << 26) | (20 << 21) | (s << 11) | (d << 6) | 32)
def mult(a, rs, rt): a.r(0x18, 0, rs, rt)
def multu(a, rs, rt): a.r(0x18, 0, rs, rt)    # values are below 2**31: signed mult (every interpreter has it)
def divu(a, rs, rt): a.r(0x1B, 0, rs, rt)
def mflo(a, rd): a.r(0x12, rd, 0, 0)


def bump(a, offset, base=8, temp=9):
    a.li(base, CONTROL); a.lw(temp, base, offset); a.addiu(temp, temp, 1); a.sw(temp, base, offset)


def frame(a, regs, size):
    a.addiu(29, 29, -size)
    for i, r in enumerate(regs): a.i(63, r, 29, 8*i)


def unframe(a, regs, size, skip=()):
    for i, r in enumerate(regs):
        if r not in skip: a.i(55, r, 29, 8*i)
    a.addiu(29, 29, size)


def scale_percent(a, reg, pct_reg, temp=13):
    """reg = reg * pct_reg / 100 (unsigned, 32-bit); clobbers temp."""
    multu(a, reg, pct_reg); mflo(a, reg); a.addiu(temp, 0, 100); divu(a, reg, temp); mflo(a, reg)


def hp_row(a, out, actor, fail, temp=9):
    """out = the actor's active HP row (+0 HP, +4 max, +20 blast stock); slot >= 5 -> fail."""
    a.lw(temp, actor, 0x994); a.i(11, out, temp, 5); a.branch(4, out, 0, fail)
    a.r(0, out, 0, temp, 7); a.r(0, temp+1, 0, temp, 5); a.r(0x21, out, out, temp+1)
    a.r(0, temp+1, 0, temp, 2); a.r(0x21, out, out, temp+1); a.r(0x21, out, out, actor); a.addiu(out, out, 0x9E4)


def actor_at(a, out, index, temp=8):
    a.r(0, temp, 0, index, 2); a.li(out, core.POINTERS); a.r(0x21, out, out, temp); a.lw(out, out)


def physical(a, actor, out, fail, tag):
    """out = physical index of a captured actor pointer (scan of core.POINTERS); clobbers t0..t2."""
    a.li(8, core.POINTERS); a.li(10, CONTROL); a.lw(10, 10, C['count']); a.move(out, 0)
    a.label(tag); a.lw(9, 8); a.branch(4, 9, actor, tag+'_found')
    a.addiu(out, out, 1); a.addiu(8, 8, 4); a.branch(5, out, 10, tag); a.jump(fail)
    a.label(tag+'_found')


def participating(a, index, fail, t0=8, t1=9, t2=10):
    a.li(t0, participation.CONTROL); a.lw(t1, t0, 12); a.lw(t2, t0, 16); a.r(0x27, t2, t2, 0)
    a.r(0x24, t1, t1, t2); a.r(6, t1, index, t1); a.i(12, t1, t1, 1); a.branch(4, t1, 0, fail)


def in_ranges(a, value, ranges, yes, temp=9):
    for first, length in ranges:
        a.addiu(temp, value, -first); a.i(11, temp, temp, length); a.branch(5, temp, 0, yes)


def side_of(a, actor, out, fail, temp=9):
    """out = 0/0x20 (side byte offset) when actor is a beam participant, else fail."""
    a.li(temp, beam.ACTORS); a.lw(temp, temp); a.move(out, 0); a.branch(4, actor, temp, f'side_{len(a.words)}')
    tag = f'side_{len(a.words)-2}'
    a.li(temp, beam.ACTORS+4); a.lw(temp, temp); a.branch(5, actor, temp, fail); a.addiu(out, 0, SIDE_STRIDE)
    a.label(tag)


# ------------------------------------------------------------------------------------------ programs

def gate_code():
    """Leaf: v0 = our install belongs to this live captured match (t0..t3 only)."""
    a = Assembler(GATE); core.gate(a, 'no')
    a.li(8, CONTROL); a.lw(9, 8); a.li(11, MAGIC); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'no')
    a.li(11, team_intro.BATTLE); a.lw(11, 11); a.lw(9, 8, 12); a.branch(5, 9, 11, 'no')
    a.branch(4, 11, 0, 'no'); a.lw(9, 11); a.addiu(11, 0, 3); a.branch(5, 9, 11, 'no')
    a.li(9, result_presentation.RESULT); a.lw(9, 9); a.branch(5, 9, 0, 'no')
    a.addiu(2, 0, 1); a.jr(); a.label('no'); a.move(2, 0); a.jr()
    data = a.finish(); assert len(data) <= RUNNING-GATE; return data


def running_code():
    """v0 = GATE and beam_clash VALID and a running struggle (both participants in 304..306); t0..t5 only."""
    a = Assembler(RUNNING); a.addiu(29, 29, -16); a.i(63, 31, 29, 0)
    a.call(GATE); a.branch(4, 2, 0, 'done')
    a.call(beam.VALID); a.branch(4, 2, 0, 'done')
    a.li(8, beam.ACTIVE); a.lw(9, 8); a.addiu(10, 0, 2); a.move(2, 0); a.branch(5, 9, 10, 'done')
    a.addiu(2, 0, 1)
    a.label('done'); a.i(55, 31, 29, 0); a.addiu(29, 29, 16); a.jr()
    data = a.finish(); assert len(data) <= SYNC-RUNNING; return data


def sync_code():
    """Leaf: reset STATE when the struggle serial changed (or the age ran backwards); t0..t5 only."""
    a = Assembler(SYNC); a.li(8, CONTROL); a.li(9, beam.CONTROL)
    a.lw(10, 9, 24); a.lw(11, 8, C['serial']); a.branch(5, 10, 11, 'reset')
    a.lw(12, 9, 16); a.branch(4, 12, 0, 'age')
    a.lw(12, 9, 20); a.lw(13, 8, C['last_age']); a.r(0x2B, 13, 12, 13); a.branch(4, 13, 0, 'age')
    a.label('reset'); a.sw(10, 8, C['serial'])
    a.addiu(11, 8, STATE_LO); a.addiu(12, 8, STATE_HI)
    a.label('clear'); a.sw(0, 11); a.addiu(11, 11, 4); a.branch(5, 11, 12, 'clear')
    a.addiu(11, 0, 100); a.sw(11, 8, C['side']); a.sw(11, 8, C['side']+SIDE_STRIDE)
    a.addiu(11, 0, -1); a.sw(11, 8, C['last_counter'])
    a.lw(11, 8, TELEMETRY['struggles']); a.addiu(11, 11, 1); a.sw(11, 8, TELEMETRY['struggles'])
    a.label('age'); a.lw(12, 9, 20); a.sw(12, 8, C['last_age']); a.jr()
    data = a.finish(); assert len(data) <= ENDCHECK-SYNC; return data


def endcheck_code(limit):
    """Entered by j from 1D8FD0 with v0 = counter+1, s1 = manager+0x50; replaces slti/bnez and its delay store."""
    a = Assembler(ENDCHECK); a.addiu(29, 29, -0x20); a.i(63, 31, 29, 0); a.i(63, 2, 29, 8)
    a.call(GATE); a.branch(4, 2, 0, 'native')
    a.li(8, CONTROL); a.lw(9, 8, C['end_now']); a.branch(4, 9, 0, 'configured')
    a.li(10, beam.CONTROL); a.lw(10, 10, 24); a.branch(5, 9, 10, 'configured')
    a.sw(0, 8, C['end_now']); a.i(55, 2, 29, 8); a.jump('end')
    a.label('configured'); a.lw(11, 8, C['limit']); a.i(55, 2, 29, 8); a.r(0x2A, 9, 2, 11)
    a.branch(5, 9, 0, 'continue'); bump(a, TELEMETRY['limit_ends']); a.jump('end')
    a.label('native'); a.i(55, 2, 29, 8); a.i(10, 9, 2, limit); a.branch(5, 9, 0, 'continue')
    a.label('end'); a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20); a.sw(2, 17, 0); a.jump(END_ZERO)
    a.label('continue'); a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20); a.sw(2, 17, 0); a.jump(LOOP)
    data = a.finish(); assert len(data) <= TUG-ENDCHECK; return data


def clamp(a, value, bound, tag, count=None):
    """value = clamp(value, -bound, +bound) (signed); clobbers t6/t7."""
    a.r(0x2A, 14, bound, value); a.branch(4, 14, 0, tag+'_hi_ok'); a.move(value, bound)
    if count: bump(a, count, 14, 15)
    a.jump(tag+'_done')
    a.label(tag+'_hi_ok'); a.r(0x23, 15, 0, bound); a.r(0x2A, 14, value, 15); a.branch(4, 14, 0, tag+'_done')
    a.move(value, 15)
    if count: bump(a, count, 14, 15)
    a.label(tag+'_done')


def tug_code():
    """Entered by j from 1D8F58 (v0 = s5<s6, s1 = manager+0x50, s6/s5 side 0/1 strength); returns to 1D8F84."""
    a = Assembler(TUG); a.addiu(29, 29, -0x20); a.i(63, 31, 29, 0)
    a.call(GATE); a.branch(4, 2, 0, 'native')
    # STATE follows this struggle before the seed: a first reset by a later PUSH or FLAGS call would wipe the
    # seeded tug and re-seed it on the next tick without the head-start cap (an instant early win).
    a.call(SYNC)
    a.li(8, CONTROL); a.lw(9, 8, C['rule']); a.branch(5, 9, 0, 'tug')
    a.lw(11, 8, C['clamp']); a.branch(4, 11, 0, 'native')
    a.r(0x2A, 9, 21, 22); a.r(0x2A, 10, 22, 21); a.r(0x23, 9, 9, 10); a.lw(10, 17, 8); a.r(0x21, 10, 10, 9)
    clamp(a, 10, 11, 'clamp', TELEMETRY['clamp_hits'])
    a.sw(10, 17, 8); a.jump('done')
    a.label('native')
    a.r(0x2A, 9, 21, 22); a.r(0x2A, 10, 22, 21); a.r(0x23, 9, 9, 10); a.lw(10, 17, 8); a.r(0x21, 10, 10, 9)
    a.sw(10, 17, 8); a.jump('done')
    a.label('tug'); a.lw(9, 17, 0); a.lw(10, 8, C['intro']); a.branch(5, 9, 10, 'accumulate')
    a.sw(22, 8, C['last0']); a.sw(21, 8, C['last1']); a.r(0x23, 10, 22, 21); a.lw(11, 8, C['seed_cap'])
    clamp(a, 10, 11, 'seed'); a.sw(10, 8, C['tug_acc']); a.jump('meter')
    a.label('accumulate')
    a.lw(9, 8, C['last0']); a.r(0x23, 9, 22, 9); a.lw(10, 8, C['last1']); a.r(0x23, 10, 21, 10); a.r(0x23, 9, 9, 10)
    a.lw(10, 8, C['tug_acc']); a.r(0x21, 10, 10, 9); a.sw(10, 8, C['tug_acc'])
    a.sw(22, 8, C['last0']); a.sw(21, 8, C['last1'])
    a.label('meter'); a.lw(10, 8, C['tug_acc']); a.lw(11, 8, C['inc'])
    # |acc| / INC with the sign of acc (truncation toward zero), then clamp to +-margin_inputs.
    a.move(12, 10); a.branch(1, 10, 1, 'positive'); a.r(0x23, 12, 0, 10)
    a.label('positive'); a.move(13, 12); a.branch(4, 11, 0, 'divided'); divu(a, 12, 11); mflo(a, 13)
    a.label('divided'); a.branch(1, 10, 1, 'signed'); a.r(0x23, 13, 0, 13)
    a.label('signed'); a.lw(11, 8, C['margin_inputs']); clamp(a, 13, 11, 'meter'); a.sw(13, 17, 8)
    a.lw(11, 8, C['margin_strength']); a.branch(4, 11, 0, 'done'); a.r(0x2A, 13, 12, 11); a.branch(5, 13, 0, 'done')
    a.li(9, beam.CONTROL); a.lw(9, 9, 24); a.li(8, CONTROL); a.sw(9, 8, C['end_now'])
    bump(a, TELEMETRY['tug_early_wins'])
    a.label('done'); a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20); a.jump(TUG_RETURN)
    data = a.finish(); assert len(data) <= PUSH-TUG; return data


def push_code(inc):
    """jal from 1FB9CC (a0 = actor via the delay slot); strength += push, exactly +INC when inert."""
    a = Assembler(PUSH); a.addiu(29, 29, -0x20); a.i(63, 31, 29, 0); a.i(63, 4, 29, 8)
    a.call(GATE); a.branch(4, 2, 0, 'native'); a.i(55, 4, 29, 8)
    a.li(8, beam.ACTIVE); a.lw(9, 8); a.addiu(9, 9, -1); a.i(11, 9, 9, 2); a.branch(4, 9, 0, 'native')
    side_of(a, 4, 9, 'native', temp=10); a.sw(9, 29, 16)
    a.call(SYNC); a.i(55, 4, 29, 8); a.lw(14, 29, 16)
    a.li(8, CONTROL); a.r(0x21, 14, 14, 8)                                       # t6 = CONTROL + side offset
    a.lw(9, 8, C['inc']); a.r(0, 9, 0, 9, 8); a.lw(10, 14, C['side']+SIDE['mult']); scale_percent(a, 9, 10)
    a.lw(10, 8, C['interference']); a.branch(4, 10, 0, 'cpu')
    hp_row(a, 11, 4, 'cpu', temp=12); a.lw(12, 11)                                # t4 = HP now
    a.lw(13, 14, C['side']+SIDE['hp_start']); a.r(0x23, 13, 13, 12); a.branch(6, 13, 0, 'cpu')
    a.lw(12, 14, C['side']+SIDE['hp_max']); a.branch(4, 12, 0, 'cpu')
    a.addiu(15, 0, 100); multu(a, 13, 15); mflo(a, 13); divu(a, 13, 12); mflo(a, 13)  # lost %
    a.lw(10, 8, C['penalty_pct']); scale_percent(a, 13, 10, temp=15)
    a.addiu(10, 0, 100); a.r(0x23, 10, 10, 13); a.i(10, 13, 10, 25); a.branch(4, 13, 0, 'penalty')
    a.addiu(10, 0, 25)
    a.label('penalty'); scale_percent(a, 9, 10)
    a.label('cpu'); a.lw(10, 4, 0x1278); a.branch(4, 10, 0, 'apply')
    a.lw(10, 8, C['cpu_pct']); scale_percent(a, 9, 10)
    a.label('apply')
    a.lw(10, 8, C['inc']); a.r(0, 10, 0, 10, 8); a.branch(4, 9, 10, 'unscaled'); bump(a, TELEMETRY['pushes_scaled'], 11, 12)
    a.label('unscaled')
    a.lw(10, 14, C['side']+SIDE['acc']); a.r(0x21, 10, 10, 9); a.r(3, 11, 0, 10, 8); a.i(12, 10, 10, 0xFF)
    a.sw(10, 14, C['side']+SIDE['acc'])
    a.lw(12, 4, 0xE4C); a.r(0x21, 12, 12, 11); a.sw(12, 4, 0xE4C)
    a.lw(12, 14, C['side']+SIDE['presses']); a.addiu(12, 12, 1); a.sw(12, 14, C['side']+SIDE['presses'])
    a.lw(12, 14, C['side']+SIDE['gained']); a.r(0x21, 12, 12, 11); a.sw(12, 14, C['side']+SIDE['gained'])
    a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20); a.jr()
    a.label('native'); a.i(55, 4, 29, 8); a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20)
    a.lw(2, 4, 0xE4C); a.addiu(2, 2, inc); a.sw(2, 4, 0xE4C); a.jr()
    data = a.finish(); assert len(data) <= FLAGS-PUSH; return data


def flags_code(flag_ids):
    """jal from the five flag calls (a0 = actor, a1 = flag in the delay slot); tail-calls 1DABE8 unless skipped."""
    a = Assembler(FLAGS); a.addiu(29, 29, -0x30); a.i(63, 31, 29, 0); a.i(63, 4, 29, 8); a.i(63, 5, 29, 16)
    a.call(GATE); a.branch(4, 2, 0, 'native')
    # Once per handler update (its first flag call): a posed assister is held or released by its own handler.
    a.i(55, 5, 29, 16); a.addiu(9, 0, flag_ids[0]); a.branch(5, 5, 9, 'posed')
    a.i(55, 4, 29, 8); a.call(POSE)
    a.label('posed'); a.i(55, 4, 29, 8)
    side_of(a, 4, 9, 'native', temp=10)
    a.call(RUNNING); a.sw(2, 29, 24); a.branch(4, 2, 0, 'native')
    a.i(55, 5, 29, 16); a.addiu(9, 0, flag_ids[0]); a.branch(5, 5, 9, 'skip_test')
    a.call(TICKBLOCK)
    a.label('skip_test'); a.li(8, CONTROL); a.lw(9, 8, C['interference']); a.branch(4, 9, 0, 'native')
    a.i(55, 5, 29, 16)
    for k in SKIPPED:
        a.addiu(9, 0, flag_ids[k]); a.branch(4, 5, 9, 'skip')
    a.jump('native')
    a.label('skip'); bump(a, TELEMETRY['flags_skipped'])
    a.i(55, 31, 29, 0); a.addiu(29, 29, 0x30); a.jr()
    a.label('native'); a.i(55, 4, 29, 8); a.i(55, 5, 29, 16); a.i(55, 31, 29, 0); a.addiu(29, 29, 0x30)
    a.jump(FLAG_SETTER)
    data = a.finish(); assert len(data) <= TICKBLOCK-FLAGS; return data


S_REGS = (16, 17, 18, 19, 20, 21, 22, 23, 31)


def tickblock_code():
    """Every running tick: reset and armour; once per coordinator counter value: HP snapshot and assists."""
    a = Assembler(TICKBLOCK); frame(a, S_REGS, 0x50)
    a.call(SYNC)
    a.li(16, CONTROL); a.li(17, beam.CONTROL); a.li(8, core.ACTORS); a.lw(18, 8)
    # Armour on every call, not once per counter value: the coordinator counter stands still through phase 4
    # (and restarts in phases 3 and 5) while the 0x42/0x44/0x46 flags stay skipped.
    a.lw(9, 16, C['interference']); a.branch(4, 9, 0, 'armoured')
    for side in range(2):
        a.lw(19, 17, 64+4*side); a.lw(9, 19, 3608); a.i(10, 10, 9, 2); a.branch(4, 10, 0, f'armour{side}')
        a.addiu(9, 0, 2); a.sw(9, 19, 3608); a.label(f'armour{side}')
    a.label('armoured')
    # A requested (pending) assist is re-requested, confirmed or failed on every call.
    a.lw(9, 16, C['assist']); a.branch(4, 9, 0, 'pended'); a.call(SWEEP); a.call(STEP)
    a.label('pended')
    a.lw(9, 18, 80); a.lw(10, 16, C['last_counter']); a.branch(4, 9, 10, 'done'); a.sw(9, 16, C['last_counter'])
    for side in range(2):
        base = C['side'] + SIDE_STRIDE*side
        a.lw(9, 16, base+SIDE['hp_max']); a.branch(5, 9, 0, f'snapped{side}')
        a.lw(19, 17, 64+4*side); hp_row(a, 11, 19, f'snapped{side}', temp=12)
        a.lw(9, 11); a.sw(9, 16, base+SIDE['hp_start']); a.lw(9, 11, 4); a.sw(9, 16, base+SIDE['hp_max'])
        a.label(f'snapped{side}')
    a.lw(9, 16, C['assist']); a.branch(4, 9, 0, 'done')
    a.lw(9, 18, 64); a.addiu(10, 0, 2); a.branch(5, 9, 10, 'done')
    a.move(4, 0); a.call(ASSIST)
    a.lw(9, 16, C['assist_cpu']); a.branch(4, 9, 0, 'done')
    a.addiu(4, 0, 1); a.call(ASSIST)
    a.label('done'); unframe(a, S_REGS, 0x50); a.jr()
    data = a.finish(); assert len(data) <= FREE-TICKBLOCK, hex(len(data)); return data


def ally_side(a, index, fail, prefix):
    """t5 = 0/1, the side whose participant `index` (s-register) is an ally of; fail when neither or both."""
    a.li(13, beam.INDICES); a.lw(12, 13)
    policy.emit_enemy(a, index, 12, prefix+'_ally0', prefix+'_e0', t0=8, t1=9)
    a.li(13, beam.INDICES+4); a.lw(12, 13)
    policy.emit_enemy(a, index, 12, prefix+'_ally1', prefix+'_e1', t0=8, t1=9)
    a.jump(fail)
    a.label(prefix+'_ally0'); a.li(13, beam.INDICES+4); a.lw(12, 13)
    policy.emit_enemy(a, index, 12, fail, prefix+'_e2', t0=8, t1=9)
    a.move(13, 0); a.jump(prefix+'_side')
    a.label(prefix+'_ally1'); a.addiu(13, 0, 1)
    a.label(prefix+'_side')


def in_range(a, x, y, fail):
    """Fall through when actors x and y (registers other than t0..t5) stand within the assist range: flat distance
    between their model centres (CONFIG range2). Clobbers t0..t5 and f0..f3."""
    throws.model(a, x, 12, fail); throws.model(a, y, 13, fail)
    for k, off in enumerate((2416, 2424)):
        a.i(49, 0, 12, off); a.i(49, 1, 13, off); fop(a, 1, 0, 0, 1)
        if k == 0: fop(a, 2, 2, 0, 0)
        else: fop(a, 2, 0, 0, 0); fop(a, 0, 2, 2, 0)
    a.li(8, CONTROL); a.i(49, 3, 8, C['range2']); fop(a, 0x34, 0, 2, 3); a.branch(17, 8, 0, fail)   # !(d2 < R2)


def hide_r3(a, record):
    """Clear R3 in the pad record's held word and both pressed words (lockon_select's mask set); t1/t7."""
    assert record not in (9, 15)
    a.addiu(15, 0, ~R3)
    for word in PRESS_WORDS:
        a.lw(9, record, word); a.r(0x24, 9, 9, 15); a.sw(9, record, word)


SIDE_SLOT, SOURCE_SLOT = 0x48, 0x50     # ASSIST frame locals above the saved registers
PRE_GPRS = tuple(range(1, 26)) + (28, 30, 31)   # R3PRE keeps every register FRAME's predecessor may read (never k0/k1)
PRE_FPRS = (0, 1, 2, 3)
R3_FRAME = 0x200                        # not PRE_FRAME: that name is the contact PRE program's
PRE_SOURCE = 0x1F0                      # R3PRE local above its saved registers


def pre_save(a):
    a.addiu(29, 29, -R3_FRAME)
    for i, r in enumerate(PRE_GPRS): a.i(31, r, 29, 16*i)                       # sq: the full 128-bit registers
    for i, f in enumerate(PRE_FPRS): a.i(57, f, 29, 0x1C0+4*i)
    a.emit((17 << 26) | (2 << 21) | (8 << 16) | (31 << 11)); a.sw(8, 29, 0x1D0)   # cfc1 t0, FCR31 (compare flag)
    assert 16*len(PRE_GPRS) <= 0x1C0


def pre_restore(a):
    a.lw(8, 29, 0x1D0); a.emit((17 << 26) | (6 << 21) | (8 << 16) | (31 << 11))
    for i, f in enumerate(PRE_FPRS): a.i(49, f, 29, 0x1C0+4*i)
    for i, r in enumerate(PRE_GPRS): a.i(30, r, 29, 16*i)
    a.addiu(29, 29, R3_FRAME)


def r3_press(a, fail, prefix, slot, active=None):
    """Human s5 (physical s4, CONTROL in s0): read the record its actor update reads, follow the R3 latch and keep a
    consumed R3 hidden until released; fall through on a new R3 press with no face/shoulder button held and no co-op
    fusion offer open (the source record is saved at sp+slot). With `active` (a register), only latch and mask while
    it is 0. Clobbers t0..t7 and s6."""
    a.move(4, 21); a.call(PAD_RECORD); a.move(22, 2); a.branch(4, 22, 0, fail)
    a.i(12, 9, 22, 3); a.branch(5, 9, 0, fail)
    # The merged co-op control takes its bits from pad 0 (lockon_select's rule).
    a.move(10, 22); a.li(8, coop.MERGED); a.branch(5, 22, 8, prefix+'source'); a.li(10, RECORDS)
    a.label(prefix+'source'); a.sw(10, 29, slot)
    a.lw(11, 22, PRESS_WORDS[0]); a.i(12, 12, 11, R3)                          # t3 held word, t4 R3 now
    a.addiu(8, 0, 1); a.r(4, 8, 20, 8)                                          # t0 = 1 << index
    a.lw(9, 16, C['r3_last']); a.r(0x24, 14, 9, 8)                              # t6 = R3 down last time
    a.r(0x27, 15, 8, 0); a.r(0x24, 9, 9, 15); a.branch(4, 12, 0, prefix+'latched'); a.r(0x25, 9, 9, 8)
    a.label(prefix+'latched'); a.sw(9, 16, C['r3_last'])
    # A consumed R3 stays hidden from the fighter until it is physically released.
    a.lw(9, 16, C['r3_mask']); a.r(0x24, 15, 9, 8); a.branch(4, 15, 0, prefix+'unmasked')
    a.branch(4, 12, 0, prefix+'mask_end')
    a.lw(10, 29, slot); hide_r3(a, 10); a.jump(fail)
    a.label(prefix+'mask_end'); a.r(0x27, 15, 8, 0); a.r(0x24, 9, 9, 15); a.sw(9, 16, C['r3_mask']); a.jump(fail)
    a.label(prefix+'unmasked')
    if active is not None: a.branch(4, active, 0, fail)
    a.branch(4, 12, 0, fail); a.branch(5, 14, 0, fail)                          # a new R3 press ...
    a.i(12, 9, 11, FACE_SHOULDER); a.branch(5, 9, 0, fail)                     # ... alone
    a.li(8, policy.CONTROL); a.lw(9, 8); a.li(10, policy.MAGIC); a.branch(5, 9, 10, prefix+'pressed')
    a.lw(9, 8, policy.FIELDS['request_expires']); a.branch(5, 9, 0, fail)
    a.label(prefix+'pressed')


def eligible_code():
    """a0 physical, a1 actor -> v0 = side+1 when it may assist now (not a struggler nor an assister already, participating,
    alive, not busy (current/requested/queued action), an ally of exactly one struggler whose side has a free assist
    slot, within range of that struggler), else 0; -(side+1) when only its current action is busy (beta.39: a human's
    R3 then says why). Stock and input are the caller's."""
    a = Assembler(ELIGIBLE); frame(a, (16, 17, 18, 19, 31), 0x30); a.sw(0, 29, 0x2C)
    a.move(16, 4); a.move(17, 5); a.li(18, beam.CONTROL); a.li(19, CONTROL)
    a.lw(9, 18, 64); a.branch(4, 17, 9, 'no'); a.lw(9, 18, 68); a.branch(4, 17, 9, 'no')
    a.move(4, 17); a.call(SLOTOF); a.branch(5, 2, 0, 'no')                     # already assisting (or releasing)
    participating(a, 16, 'no')
    hp_row(a, 12, 17, 'no', temp=9); a.lw(9, 12); a.branch(6, 9, 0, 'no')
    for offset in throws.ACTION_FIELDS[1:]:
        a.lw(10, 17, offset); in_ranges(a, 10, BUSY_ACTIONS, 'no')
    a.lw(10, 17, throws.ACTION_FIELDS[0]); in_ranges(a, 10, BUSY_ACTIONS, 'busy'); a.jump('free')
    a.label('busy'); a.addiu(9, 0, 1); a.sw(9, 29, 0x2C)
    a.label('free')
    ally_side(a, 16, 'no', 'ally')                                                # t5 = side
    a.sw(13, 29, 0x28)
    a.move(4, 13); a.call(FREE); a.branch(4, 2, 0, 'no')                         # every slot of that side taken
    a.lw(13, 29, 0x28)
    a.r(0, 14, 0, 13, 2); a.r(0x21, 14, 14, 18); a.lw(24, 14, 64)               # t8 = the struggling ally
    in_range(a, 17, 24, 'no')
    a.lw(2, 29, 0x28); a.addiu(2, 2, 1); a.lw(9, 29, 0x2C); a.branch(4, 9, 0, 'done')
    a.r(0x23, 2, 0, 2); a.jump('done')
    a.label('no'); a.move(2, 0)
    a.label('done'); unframe(a, (16, 17, 18, 19, 31), 0x30); a.jr()
    data = a.finish(); assert len(data) <= VIEWSET-ELIGIBLE, hex(len(data)); return data


REFUSE_REGS = (31, 16, 17)


def refuse_code():
    """a0 physical, a1 side, a2 actor: a human's new R3 alone near its struggling ally while its current action is
    busy (hit, thrown, cinematic): with a blast stock, 'ASSIST FAILED - BUSY' for that player (nothing paid, R3 left
    to the native action)."""
    a = Assembler(REFUSE); frame(a, REFUSE_REGS, 0x20)
    a.move(16, 4); a.move(17, 5)
    hp_row(a, 12, 6, 'done', temp=9); a.lw(9, 12, 20); a.li(10, STOCK); a.r(0x2A, 9, 9, 10); a.branch(5, 9, 0, 'done')
    a.li(8, CONTROL); side_word(a, 14, 17, 'masks'); a.lw(9, 14); a.addiu(10, 0, 1); a.r(4, 10, 16, 10)
    a.r(0x25, 9, 9, 10); a.sw(9, 14)
    bump(a, TELEMETRY['triggers']); a.move(4, 17); a.addiu(5, 0, F_BUSY); a.call(FAILCAP)
    a.label('done'); unframe(a, REFUSE_REGS, 0x20); a.jr()
    data = a.finish(); assert len(data) <= ELIGIBLE-REFUSE, hex(len(data)); return data


def assist_code():
    """a0 = 0: human allies (an R3 request latched at frame start, or without the frame link their record's R3);
    a0 = 1: the CPU schedule. REGISTER for each new assist."""
    a = Assembler(ASSIST); frame(a, S_REGS, 0x60)
    a.move(23, 4); a.li(16, CONTROL); a.li(17, beam.CONTROL); a.li(8, core.ACTORS); a.lw(18, 8)
    a.lw(19, 16, C['count']); a.move(20, 0)
    a.label('loop'); a.branch(4, 20, 19, 'done')
    actor_at(a, 21, 20); a.branch(4, 21, 0, 'next')
    a.lw(9, 21, 0x1278); a.branch(4, 23, 0, 'human')
    a.branch(4, 9, 0, 'next'); a.jump('check')
    a.label('human'); a.branch(5, 9, 0, 'next')
    a.lw(8, 16, C['frame_prev']); a.branch(4, 8, 0, 'record')
    a.addiu(8, 0, 1); a.r(4, 8, 20, 8); a.lw(9, 16, C['r3_req']); a.r(0x24, 10, 9, 8); a.branch(4, 10, 0, 'next')
    a.r(0x27, 10, 8, 0); a.r(0x24, 9, 9, 10); a.sw(9, 16, C['r3_req']); a.jump('check')
    a.label('record'); r3_press(a, 'next', 'r', SOURCE_SLOT)
    a.label('check'); a.move(4, 20); a.move(5, 21); a.call(ELIGIBLE); a.branch(4, 2, 0, 'next')
    a.branch(1, 2, 0, 'refuse')
    a.addiu(13, 2, -1); a.sw(13, 29, SIDE_SLOT)
    hp_row(a, 22, 21, 'next', temp=9)
    a.lw(13, 29, SIDE_SLOT)
    a.branch(4, 23, 0, 'stock')
    a.lw(9, 18, 80); a.lw(10, 16, C['intro']); a.r(0x23, 9, 9, 10)
    # At c == 8 + 2*physical and every 32 counter values after it (a failed assist is retried; ELIGIBLE refuses a
    # pending or posed side).
    a.r(0, 10, 0, 20, 1); a.addiu(10, 10, 8); a.r(0x23, 9, 9, 10); a.branch(1, 9, 0, 'next')
    a.i(12, 9, 9, 31); a.branch(5, 9, 0, 'next')
    a.lw(9, 18, 88); a.branch(5, 13, 0, 'cpu_side1'); a.branch(7, 9, 0, 'next'); a.jump('stock')
    a.label('cpu_side1'); a.branch(1, 9, 0, 'next')
    a.label('stock'); a.lw(9, 22, 20); a.li(10, STOCK); a.r(0x2A, 9, 9, 10); a.branch(4, 9, 0, 'register')
    bump(a, TELEMETRY['assist_no_stock']); a.jump('next')
    a.label('register'); a.branch(5, 23, 0, 'call')
    a.lw(8, 16, C['frame_prev']); a.branch(5, 8, 0, 'call')                     # already hidden at frame start
    a.lw(10, 29, SOURCE_SLOT); hide_r3(a, 10)
    a.addiu(8, 0, 1); a.r(4, 8, 20, 8); a.lw(9, 16, C['r3_mask']); a.r(0x25, 9, 9, 8); a.sw(9, 16, C['r3_mask'])
    bump(a, TELEMETRY['r3_consumed'])
    a.label('call'); a.move(4, 20); a.lw(5, 29, SIDE_SLOT); a.call(REGISTER)
    a.label('next'); a.addiu(20, 20, 1); a.jump('loop')
    a.label('refuse'); a.branch(5, 23, 0, 'next'); a.r(0x23, 5, 0, 2); a.addiu(5, 5, -1); a.move(4, 20); a.move(6, 21)
    a.call(REFUSE); a.jump('next')
    a.label('done'); unframe(a, S_REGS, 0x60); a.jr()
    data = a.finish(); assert len(data) <= POSE-ASSIST, hex(len(data)); return data


def r3pre_code():
    """Frame start (team_participation's FRAME chain, before any actor reads its pad record): every human's R3 latch
    and mask; during the push stage of a running struggle, a new R3 press alone by an eligible ally with a blast stock
    is hidden from that player's record (the native R3 action never sees it) and latched for ASSIST."""
    a = Assembler(R3PRE); pre_save(a)
    a.call(GATE); a.branch(4, 2, 0, 'done')
    a.li(16, CONTROL); a.lw(9, 16, C['assist']); a.branch(4, 9, 0, 'done')
    a.call(SWEEP)
    a.call(RUNNING); a.move(23, 2); a.branch(4, 23, 0, 'idle')
    a.li(8, core.ACTORS); a.lw(8, 8); a.lw(9, 8, 64); a.addiu(10, 0, 2); a.branch(4, 9, 10, 'stage')
    a.label('idle'); a.move(23, 0); a.li(16, CONTROL); a.sw(0, 16, C['r3_req']); a.jump('scan')
    a.label('stage'); a.call(SYNC)
    a.label('scan'); a.li(16, CONTROL); a.lw(19, 16, C['count']); a.move(20, 0)
    a.label('loop'); a.branch(4, 20, 19, 'done')
    actor_at(a, 21, 20); a.branch(4, 21, 0, 'next')
    a.lw(9, 21, 0x1278); a.branch(5, 9, 0, 'next')
    r3_press(a, 'next', 'p', PRE_SOURCE, active=23)
    a.move(4, 20); a.move(5, 21); a.call(ELIGIBLE); a.branch(4, 2, 0, 'next')
    a.branch(7, 2, 0, 'eligible'); a.r(0x23, 5, 0, 2); a.addiu(5, 5, -1); a.move(4, 20); a.move(6, 21); a.call(REFUSE)
    a.jump('next')
    a.label('eligible'); hp_row(a, 22, 21, 'next', temp=9); a.lw(9, 22, 20); a.li(10, STOCK); a.r(0x2A, 9, 9, 10); a.branch(5, 9, 0, 'next')
    a.lw(10, 29, PRE_SOURCE); hide_r3(a, 10)
    a.li(16, CONTROL); a.addiu(8, 0, 1); a.r(4, 8, 20, 8)
    for key in ('r3_mask', 'r3_req'):
        a.lw(9, 16, C[key]); a.r(0x25, 9, 9, 8); a.sw(9, 16, C[key])
    bump(a, TELEMETRY['r3_consumed'])
    a.label('next'); a.addiu(20, 20, 1); a.jump('loop')
    a.label('done'); pre_restore(a); a.jr()
    data = a.finish(); assert len(data) <= REFUSE-R3PRE, hex(len(data)); return data


def frame_stub(previous):
    """Spliced into team_participation's FRAME (its single `jal previous` now calls this): R3PRE, then the recorded
    predecessor with every register as FRAME left it."""
    a = Assembler(FRAMESTUB); a.addiu(29, 29, -16); a.i(63, 31, 29, 0); a.call(R3PRE)
    a.i(55, 31, 29, 0); a.addiu(29, 29, 16); a.jump(previous)
    data = a.finish(); assert len(data) <= R3PRE-FRAMESTUB; return data


def splice_site():
    """The single `jal previous` in team_participation's FRAME."""
    template = part.frame_code(0)
    offsets = [i for i in range(0, len(template), 4) if struct.unpack_from('<I', template, i)[0] == 3 << 26]
    if len(offsets) != 1: raise ValueError('Unknown team participation frame layout')
    return part.FRAME + offsets[0]


def frame_predecessor(ram):
    """The predecessor team_participation's FRAME calls, when it is the exact plain FRAME; else None."""
    site = splice_site(); word = u32(ram, site); previous = (word & 0x3FFFFFF) << 2
    if (word >> 26 != 3 or not 0x07000000 <= previous < 0x08000000 or BASE <= previous < END
            or ram[part.FRAME:part.FRAME+len(part.frame_code(0))] != part.frame_code(previous)):
        return None
    return previous


REGISTER_REGS = (31, 4, 5, 16, 17, 18, 19)


def side_word(a, out, side, key, base=8):
    """out = CONTROL + C[key] + 4*side (side a register; base = CONTROL already loaded); clobbers t7."""
    a.r(0, 15, 0, side, 2); a.r(0x21, out, base, 15); a.addiu(out, out, C[key])


def in_struggle(a, action, no, temp=9):
    a.addiu(temp, action, -304); a.i(11, temp, temp, 3); a.branch(4, temp, 0, no)


def register_code():
    """a0 = physical assister, a1 = side: a requested assist takes the side's first free slot (its formation spot)
    and starts its transition: the native fly-in action while STEP glides it there; nothing is paid yet (CONFIRM
    pays one blast stock and raises the side's multiplier once the assister is seen in the struggle action)."""
    a = Assembler(REGISTER); frame(a, REGISTER_REGS, 0x40)
    a.call(SYNC); a.i(55, 4, 29, 8); a.i(55, 5, 29, 16)
    actor_at(a, 16, 4); hp_row(a, 13, 16, 'done', temp=9); a.move(17, 5)        # s0 assister, s1 side
    a.li(8, beam.CONTROL); a.r(0, 9, 0, 17, 2); a.r(0x21, 9, 9, 8); a.lw(19, 9, 64)   # s3 ally
    a.lw(9, 19, 2376); in_struggle(a, 9, 'done')
    throws.model(a, 16, 19, 'done')                                              # s3 = the assister's model now
    a.move(4, 17); a.call(FREE); a.branch(4, 2, 0, 'done'); a.move(18, 2)       # s2 slot
    a.li(8, CONTROL); a.r(0, 14, 0, 17, 2); a.r(0x21, 14, 14, 8); a.lw(9, 14, C['masks']); a.addiu(10, 0, 1)
    a.i(55, 4, 29, 8); a.r(4, 10, 4, 10); a.r(0x25, 9, 9, 10); a.sw(9, 14, C['masks'])   # caption routing
    bump(a, TELEMETRY['triggers'])
    clear_slot(a, 18)
    a.sw(16, 18, S['actor']); a.sw(4, 18, S['phys'])
    a.li(10, beam.CONTROL); a.lw(11, 10, 24); a.sw(11, 18, S['serial']); a.lw(11, 10, 20); a.sw(11, 18, S['age'])
    a.addiu(9, 0, P_MOVING); a.sw(9, 18, S['state'])
    a.li(8, CONTROL+SLOTS); a.r(0x23, 9, 18, 8); a.r(2, 9, 0, 9, 6); a.i(12, 9, 9, MAX_ASSISTS-1); a.sw(9, 18, S['k'])
    for k, off in enumerate((2416, 2420, 2424)):
        a.lw(9, 19, off); a.sw(9, 18, S['sx']+4*k)                                # the transition starts here
    a.move(4, 16); a.li(5, CONTROL); a.lw(5, 5, C['trans_action']); a.call(SET_ACTION)
    a.addiu(9, 0, 2); a.sw(9, 16, 3608)
    a.label('done'); unframe(a, REGISTER_REGS, 0x40); a.jr()
    data = a.finish(); assert len(data) <= PRE-REGISTER, hex(len(data)); return data


CONFIRM_REGS = (31, 16, 17, 18)


def confirm_code():
    """a0 = slot whose assister is in the struggle action: pay its blast stock, add its share to the side's
    multiplier (MAX_SIDE_MULT cap), count the assist and start its caption (a stock spent meanwhile fails it as busy);
    a human assister's view now follows the struggling ally (VIEWSET) and its target is the enemy struggler."""
    a = Assembler(CONFIRM); frame(a, CONFIRM_REGS, 0x20)
    a.move(16, 4); a.lw(18, 16, S['actor']); a.branch(4, 18, 0, 'done')        # s0 slot, s2 assister
    slot_side(a, 17, 16)                                                         # s1 side
    hp_row(a, 13, 18, 'broke', temp=9); a.lw(9, 13, 20); a.li(10, STOCK); a.r(0x2A, 11, 9, 10)
    a.branch(5, 11, 0, 'broke')
    a.r(0x23, 9, 9, 10); a.sw(9, 13, 20)
    a.li(8, CONTROL); a.r(0, 14, 0, 17, 5); a.r(0x21, 14, 14, 8)
    a.lw(9, 14, C['side']+SIDE['mult']); a.lw(10, 8, C['assist_step']); a.r(0x21, 9, 9, 10)
    a.addiu(10, 0, MAX_SIDE_MULT); a.r(0x2A, 11, 10, 9); a.branch(4, 11, 0, 'capped'); a.move(9, 10)
    a.label('capped'); a.sw(9, 14, C['side']+SIDE['mult'])
    a.lw(9, 14, C['side']+SIDE['assists']); a.addiu(9, 9, 1); a.sw(9, 14, C['side']+SIDE['assists'])
    a.li(10, beam.CONTROL); a.lw(10, 10, 20); a.sw(10, 14, C['side']+SIDE['assist_age'])
    a.addiu(9, 0, P_CONFIRMED); a.sw(9, 16, S['state'])
    bump(a, TELEMETRY['confirmed'])
    a.lw(9, 18, 0x1278); a.branch(5, 9, 0, 'cpu'); bump(a, TELEMETRY['assists_human'])
    a.lw(11, 16, S['phys'])
    a.li(8, beam.INDICES); a.i(14, 9, 17, 1); a.r(0, 9, 0, 9, 2); a.r(0x21, 8, 8, 9); a.lw(12, 8)
    a.li(8, core.TABLE); a.r(0, 9, 0, 11, 2); a.r(0x21, 8, 8, 9); a.sw(12, 8)
    a.move(4, 16); a.addiu(5, 0, 1); a.call(VIEWSET); a.jump('done')
    a.label('cpu'); bump(a, TELEMETRY['assists_cpu']); a.jump('done')
    a.label('broke'); bump(a, TELEMETRY['assist_no_stock']); a.move(4, 16); a.addiu(5, 0, F_BUSY); a.call(FAIL)
    a.label('done'); unframe(a, CONFIRM_REGS, 0x20); a.jr()
    data = a.finish(); assert len(data) <= FAIL-CONFIRM, hex(len(data)); return data


FAIL_REGS = (31, 16, 17, 18)
REQUEST_FIELDS = (2380, 2388, 2392, 2396, 2400)     # the request slot (SET_ACTION) and the queued actions


def fail_code():
    """a0 = slot, a1 = reason (F_*; 0 = silent): the assist is cancelled with nothing paid (that fighter may assist
    again). A pose or transition request still waiting in the assister's request slot or queue is withdrawn and a
    switched view is given back; an assister already in a struggle action keeps its record (P_FAILED) so its own
    handler releases it (POSE: the native 'struggle over' flag); otherwise the slot is freed."""
    a = Assembler(FAIL); frame(a, FAIL_REGS, 0x20)
    a.move(16, 4); a.move(17, 5)
    slot_side(a, 4, 16); a.move(5, 17); a.call(FAILCAP)
    a.lw(18, 16, S['actor']); a.branch(4, 18, 0, 'free')
    for k, off in enumerate(REQUEST_FIELDS):
        a.lw(9, 18, off); a.addiu(10, 9, -304); a.i(11, 10, 10, 3); a.branch(5, 10, 0, f'drop{k}')
        a.li(10, CONTROL); a.lw(10, 10, C['trans_action']); a.branch(5, 9, 10, f'kept{k}')
        a.label(f'drop{k}'); a.addiu(9, 0, -1); a.sw(9, 18, off); a.label(f'kept{k}')
    a.move(4, 16); a.move(5, 0); a.call(VIEWSET)
    a.lw(9, 18, 2376); a.addiu(10, 9, -304); a.i(11, 10, 10, 3); a.branch(4, 10, 0, 'free')
    a.addiu(9, 0, P_FAILED); a.sw(9, 16, S['state']); a.jump('done')
    a.label('free'); clear_slot(a, 16)
    a.label('done'); unframe(a, FAIL_REGS, 0x20); a.jr()
    data = a.finish(); assert len(data) <= STEP-FAIL, hex(len(data)); return data


STEP_REGS = (31, 16, 17, 18, 19, 20, 21, 22, 23)


def step_code():
    """Every running struggle tick, for every slot of this struggle: a moving assister (its transition) keeps its
    fly-in action and glides on (PLACE eases it from its start to its formation spot); after CONFIG trans_ticks (TRANSITION_TICKS) it
    is asked into the ally's struggle action (P_PENDING). A pending one now in the struggle action is confirmed; one
    still waiting is asked again (its request slot may have been overwritten by the CPU or the native action system)
    and kept at its spot, armoured; after PEND_TICKS, or when it falls or is hit, it fails (reason busy/hit). The
    ally out of its struggle cancels a moving one (busy)."""
    a = Assembler(STEP); frame(a, STEP_REGS, 0x50)
    a.li(20, CONTROL+SLOTS); a.move(21, 0); a.li(19, beam.CONTROL)
    a.label('slot'); a.lw(17, 20, S['actor']); a.branch(4, 17, 0, 'next')       # s1 assister, s4 slot, s5 index
    a.lw(9, 20, S['state']); a.addiu(10, 9, -P_MOVING); a.branch(4, 10, 0, 'live')
    a.addiu(10, 9, -P_PENDING); a.branch(5, 10, 0, 'next')
    a.label('live')
    a.lw(9, 19, 24); a.lw(10, 20, S['serial']); a.branch(5, 9, 10, 'busy')
    a.r(2, 22, 0, 21, 2)                                                          # s6 side
    a.r(0, 9, 0, 22, 2); a.r(0x21, 9, 9, 19); a.lw(18, 9, 64)                   # s2 ally
    a.lw(23, 17, 2376)                                                            # s7 its action
    a.lw(9, 20, S['state']); a.addiu(10, 9, -P_MOVING); a.branch(5, 10, 0, 'pending')
    # ---- transition
    hp_row(a, 11, 17, 'hit', temp=12); a.lw(9, 11); a.branch(6, 9, 0, 'hit')
    in_ranges(a, 23, BUSY_ACTIONS[:1], 'hit')
    a.lw(9, 18, 2376); in_struggle(a, 9, 'busy', temp=10)
    a.lw(9, 19, 20); a.lw(10, 20, S['age']); a.r(0x23, 9, 9, 10); a.li(10, CONTROL); a.lw(10, 10, C['trans_ticks'])
    a.r(0x2A, 9, 9, 10); a.branch(4, 9, 0, 'arrive')
    a.li(5, CONTROL); a.lw(5, 5, C['trans_action']); a.branch(4, 23, 5, 'glide')
    a.lw(9, 17, 2380); a.branch(4, 9, 5, 'glide')
    a.move(4, 17); a.call(SET_ACTION)
    a.label('glide'); a.addiu(9, 0, 2); a.sw(9, 17, 3608)
    a.move(4, 17); a.move(5, 18); a.i(14, 9, 22, 1); a.r(0, 9, 0, 9, 2); a.r(0x21, 9, 9, 19); a.lw(6, 9, 64)
    a.move(7, 20); a.call(PLACE); a.branch(4, 2, 0, 'blocked'); a.jump('next')
    a.label('arrive')
    a.addiu(9, 0, P_PENDING); a.sw(9, 20, S['state']); a.lw(9, 19, 20); a.sw(9, 20, S['age']); a.sw(0, 20, S['tries'])
    bump(a, TELEMETRY['moved'])
    a.move(4, 17); a.move(5, 18); a.i(14, 9, 22, 1); a.r(0, 9, 0, 9, 2); a.r(0x21, 9, 9, 19); a.lw(6, 9, 64)
    a.move(7, 20); a.call(PLACE); a.branch(4, 2, 0, 'blocked')
    a.lw(5, 18, 2376); a.move(4, 17); a.call(SET_ACTION); bump(a, TELEMETRY['posed'])
    a.addiu(9, 0, 2); a.sw(9, 17, 3608)
    a.lw(9, 17, 2376); in_struggle(a, 9, 'next', temp=10)                        # taken at once: confirm now
    a.move(4, 20); a.call(CONFIRM); a.jump('next')
    # ---- pending (beta.39's pose gate, per slot)
    a.label('pending'); a.sw(23, 20, S['seen'])
    a.addiu(9, 23, -304); a.i(11, 9, 9, 3); a.branch(4, 9, 0, 'waiting')
    a.move(4, 20); a.call(CONFIRM); a.jump('next')
    a.label('waiting')
    hp_row(a, 11, 17, 'hit', temp=12); a.lw(9, 11); a.branch(6, 9, 0, 'hit')
    a.lw(9, 19, 20); a.lw(10, 20, S['age']); a.r(0x23, 9, 9, 10); a.i(11, 9, 9, PEND_TICKS)
    a.branch(5, 9, 0, 'ask')
    in_ranges(a, 23, BUSY_ACTIONS[:1], 'hit')
    a.jump('busy')
    a.label('ask')
    a.lw(5, 18, 2376); in_struggle(a, 5, 'next', temp=10)
    # Why the last request did not take: still waiting, withdrawn/refused (slot empty) or overwritten (another
    # action requested by the CPU or the native action system; its number is kept for diagnosis).
    a.lw(9, 17, 2380); a.branch(4, 9, 5, 'asked')                                # our request still waiting
    a.lw(10, 20, S['tries']); a.branch(4, 10, 0, 'asked')
    a.addiu(10, 0, -1); a.branch(4, 9, 10, 'refused')
    a.li(10, CONTROL); a.sw(9, 10, TELEMETRY['last_override']); bump(a, TELEMETRY['overridden'], 10, 11)
    a.jump('asked')
    a.label('refused'); bump(a, TELEMETRY['refused'], 10, 11)
    a.label('asked'); a.lw(5, 18, 2376); a.move(4, 17); a.call(SET_ACTION)
    a.addiu(9, 0, 2); a.sw(9, 17, 3608)
    a.lw(9, 20, S['tries']); a.addiu(9, 9, 1); a.sw(9, 20, S['tries']); bump(a, TELEMETRY['rerequests'])
    a.move(4, 17); a.move(5, 18); a.i(14, 9, 22, 1); a.r(0, 9, 0, 9, 2); a.r(0x21, 9, 9, 19); a.lw(6, 9, 64)
    a.move(7, 20); a.call(PLACE); a.jump('next')
    a.label('busy'); a.move(4, 20); a.addiu(5, 0, F_BUSY); a.call(FAIL); a.jump('next')
    a.label('hit'); a.move(4, 20); a.addiu(5, 0, F_HIT); a.call(FAIL); a.jump('next')
    a.label('blocked'); a.move(4, 20); a.addiu(5, 0, F_BLOCKED); a.call(FAIL)
    a.label('next'); a.addiu(20, 20, SLOT_STRIDE); a.addiu(21, 21, 1); a.addiu(9, 0, 2*MAX_ASSISTS)
    a.branch(5, 21, 9, 'slot')
    unframe(a, STEP_REGS, 0x50); a.jr()
    data = a.finish(); assert len(data) <= TEXT-STEP, hex(len(data)); return data


PLACE_REGS = (16, 17, 18, 19, 20, 21, 22, 23, 31)
# PLACE frame: the new root XYZW, rotation, the formation spot (X, Z) and whether the assister is still gliding.
POS, ROT, SPOT, MOVING = 0x50, 0x60, 0x70, 0x78
PLACE_FRAME = 0x90


def fconst(a, f, value, temp=8):
    a.li(temp, struct.unpack('<I', struct.pack('<f', value))[0]); mtc1(a, temp, f)


def place_code():
    """a0 assister, a1 struggling ally, a2 enemy struggler, a3 its slot -> v0 = 1 when the assister's root moved.
    The slot's formation spot: FORMATION[k] behind the ally (away from the enemy) and to its side, the side sign kept
    in the slot (unset: the side nearer the drawn camera's eye, else +1), at the ally's height. While the slot is
    moving, the root is eased (t(2-t)) from the transition start to that spot over CONFIG trans_ticks, facing the spot;
    otherwise it stands on the spot facing the enemy. Clamped into the live arena (radius and ceiling/floor planes)
    and never inside the terrain (FLOOR: a buried spot stands on the floor); the native setter with a fresh sector,
    model refresh and root sync (cinematic_position.commit). Nothing moves when a model is missing or the two
    strugglers share a spot. Only f0..f19 are used (the native callers of the struggle flag calls keep f20..f31)."""
    a = Assembler(PLACE); frame(a, PLACE_REGS, PLACE_FRAME)
    a.move(16, 4); a.move(17, 5); a.move(18, 6); a.move(22, 7); a.move(23, 0); a.sw(0, 29, MOVING)
    throws.model(a, 17, 19, 'done'); throws.model(a, 18, 20, 'done'); throws.model(a, 16, 21, 'done')
    for f, off in ((2, 2416), (3, 2424)):                                      # f2/f3 = ally - enemy (x, z)
        a.i(49, 0, 19, off); a.i(49, 1, 20, off); fop(a, 1, f, 0, 1)
    fop(a, 2, 4, 2, 2); fop(a, 2, 5, 3, 3); fop(a, 0, 4, 4, 5)                  # f4 = |d|^2
    fconst(a, 5, 1.0); fop(a, 0x34, 0, 4, 5); a.branch(17, 8, 0, 'apart'); a.jump('done')   # |d| < 1: in place
    a.label('apart'); fop(a, 4, 4, 4, 4); fop(a, 3, 2, 2, 4); fop(a, 3, 3, 3, 4)    # unit back direction (EE sqrt.s reads ft)
    a.i(49, 16, 19, 2416); a.i(49, 17, 19, 2424)                               # f16/f17 = ally x, z
    # The side sign: kept, else the side (r = (-bz, bx)) nearer the drawn camera's eye.
    a.i(49, 11, 22, S['sign']); fconst(a, 12, 0.0); fop(a, 0x32, 0, 11, 12); a.branch(17, 8, 0, 'signed')
    fconst(a, 11, 1.0)
    a.lw(12, 28, -22176); throws.ptr(a, 12, 560, 'sign_kept')
    a.i(49, 0, 12, 544); a.i(49, 1, 12, 552)
    fop(a, 1, 6, 0, 16); fop(a, 1, 7, 1, 17)                                     # f6/f7 = eye - ally
    fop(a, 2, 8, 7, 2); fop(a, 2, 9, 6, 3); fop(a, 1, 8, 8, 9)                  # dot = ez*bx - ex*bz
    fconst(a, 9, 0.0); fop(a, 0x34, 0, 8, 9); a.branch(17, 8, 0, 'sign_kept'); fconst(a, 11, -1.0)
    a.label('sign_kept'); a.i(57, 11, 22, S['sign'])
    a.label('signed')
    # FORMATION[k]: f5 = behind, f6 = aside (times the sign).
    a.lw(9, 22, S['k'])
    for k, (back, aside) in enumerate(FORMATION):
        a.addiu(10, 0, k); a.branch(5, 9, 10, f'not{k}')
        fconst(a, 5, back); fconst(a, 6, aside); a.jump('formed'); a.label(f'not{k}')
    a.jump('done')
    a.label('formed'); fop(a, 2, 6, 6, 11)
    fop(a, 2, 7, 2, 5); fop(a, 2, 8, 3, 6); fop(a, 1, 7, 7, 8); fop(a, 0, 7, 16, 7)   # x: ally + B bx - A bz
    fop(a, 2, 8, 3, 5); fop(a, 2, 9, 2, 6); fop(a, 0, 8, 8, 9); fop(a, 0, 8, 17, 8)   # z: ally + B bz + A bx
    a.i(57, 7, 29, SPOT); a.i(57, 8, 29, SPOT+4)
    a.i(49, 9, 19, 2420)                                                          # f9 = ally y
    a.lw(9, 22, S['state']); a.addiu(10, 9, -P_MOVING); a.branch(5, 10, 0, 'final')
    # Gliding: e = t(2 - t), t = elapsed / TRANSITION_TICKS in [0, 1].
    a.li(8, beam.CONTROL); a.lw(9, 8, 20); a.lw(10, 22, S['age']); a.r(0x23, 9, 9, 10)
    a.branch(1, 9, 1, 'nonneg'); a.move(9, 0)
    a.label('nonneg'); a.li(11, CONTROL); a.lw(11, 11, C['trans_ticks']); a.branch(6, 11, 0, 'final')
    a.r(0x2A, 10, 9, 11); a.branch(5, 10, 0, 'below'); a.move(9, 11)
    a.label('below'); mtc1(a, 9, 10); cvt_s_w(a, 10, 10); mtc1(a, 11, 12); cvt_s_w(a, 12, 12); fop(a, 3, 10, 10, 12)
    fconst(a, 12, 2.0); fop(a, 1, 12, 12, 10); fop(a, 2, 10, 10, 12)             # f10 = e
    for f, off in ((7, S['sx']), (9, S['sy']), (8, S['sz'])):
        a.i(49, 13, 22, off); fop(a, 1, 14, f, 13); fop(a, 2, 14, 14, 10); fop(a, 0, f, 13, 14)
    a.addiu(9, 0, 1); a.sw(9, 29, MOVING)
    a.label('final'); a.i(57, 7, 29, POS); a.i(57, 9, 29, POS+4); a.i(57, 8, 29, POS+8)
    a.li(8, 0x3F800000); a.sw(8, 29, POS+12)
    # The live arena (arena_bounds): radial limit (radius - 100 - margin) and the ceiling/floor planes (Y down).
    a.li(8, arena_bounds.STAGE); a.lw(12, 8); throws.ptr(a, 12, 68, 'clamped'); a.lw(12, 12, 64)
    throws.ptr(a, 12, 12, 'clamped')
    a.i(49, 0, 12, 0); fconst(a, 1, 100.0 + ARENA_MARGIN); fop(a, 1, 0, 0, 1)    # f0 = R
    fconst(a, 1, 1.0); fop(a, 0x34, 0, 0, 1); a.branch(17, 8, 1, 'clamped')
    a.i(49, 2, 29, POS); a.i(49, 3, 29, POS+8)
    fop(a, 2, 4, 2, 2); fop(a, 2, 5, 3, 3); fop(a, 0, 4, 4, 5); fop(a, 2, 5, 0, 0)
    fop(a, 0x36, 0, 4, 5); a.branch(17, 8, 1, 'radial')                          # inside: x^2+z^2 <= R^2
    fop(a, 4, 4, 4, 4); fop(a, 3, 0, 0, 4); fop(a, 2, 2, 2, 0); fop(a, 2, 3, 3, 0)
    a.i(57, 2, 29, POS); a.i(57, 3, 29, POS+8)
    a.label('radial'); a.i(49, 2, 29, POS+4); fconst(a, 1, ARENA_MARGIN)
    a.i(49, 0, 12, 4); fop(a, 0, 0, 0, 1); fop(a, 0x34, 0, 2, 0); a.branch(17, 8, 0, 'below_top'); fop(a, 6, 2, 0)
    a.label('below_top'); a.i(49, 0, 12, 8); fop(a, 1, 0, 0, 1); fop(a, 0x34, 0, 0, 2); a.branch(17, 8, 0, 'above_floor')
    fop(a, 6, 2, 0)
    a.label('above_floor'); a.i(57, 2, 29, POS+4)
    # Terrain: a spot under the floor (a hill beside the ally) stands on the floor.
    a.addiu(4, 29, POS); a.call(FLOOR); a.branch(4, 2, 0, 'clamped')
    a.lw(9, 29, POS+12); a.sw(9, 29, POS+4); bump(a, TELEMETRY['lifted'])
    a.label('clamped'); a.li(8, 0x3F800000); a.sw(8, 29, POS+12)
    # Facing: the spot while gliding (until within 1 unit of it), else the enemy struggler.
    a.i(49, 12, 29, POS); a.i(49, 13, 29, POS+8); a.i(49, 14, 20, 2416); a.i(49, 15, 20, 2424)
    a.lw(9, 29, MOVING); a.branch(4, 9, 0, 'face')
    a.i(49, 0, 29, SPOT); a.i(49, 1, 29, SPOT+4); fop(a, 1, 2, 0, 12); fop(a, 1, 3, 1, 13)
    fop(a, 2, 2, 2, 2); fop(a, 2, 3, 3, 3); fop(a, 0, 2, 2, 3); fconst(a, 3, 1.0); fop(a, 0x34, 0, 2, 3)
    a.branch(17, 8, 1, 'face'); fop(a, 6, 14, 0); fop(a, 6, 15, 1)
    a.label('face'); a.call(FACING)
    a.sw(0, 29, ROT); a.i(57, 0, 29, ROT+4); a.sw(0, 29, ROT+8); a.li(8, 0x3F800000); a.sw(8, 29, ROT+12)
    a.addiu(4, 0, -1); a.addiu(5, 29, POS); a.call(SECTOR); a.move(7, 2)
    a.move(4, 16); a.addiu(5, 29, POS); a.addiu(6, 29, ROT); a.call(SET_ROOT)
    for fn in MODEL_REFRESH:
        a.move(4, 21); a.call(fn)
    a.move(4, 21); a.move(5, 0); a.call(MODEL_SPHERES); a.move(4, 16); a.call(ROOT_SYNC)
    # Native swept movement starts at the new pose, not from the old one (spawn_placement / cinematic_position).
    a.addiu(8, 16, 16); a.addiu(9, 16, 256)
    a.label('copy'); a.lw(10, 8); a.sw(10, 8, 240); a.addiu(8, 8, 4); a.branch(5, 8, 9, 'copy')
    a.lw(12, 21, 4000); a.lw(13, 21, 4004)
    throws.ptr(a, 12, 32, 'counted'); throws.ptr(a, 13, 32, 'counted')
    for off in range(0, 32, 4):
        a.lw(10, 12, off); a.sw(10, 13, off)
    a.label('counted'); bump(a, TELEMETRY['placed']); a.addiu(23, 0, 1)
    a.label('done'); a.move(2, 23); unframe(a, PLACE_REGS, PLACE_FRAME); a.jr()
    data = a.finish(); assert len(data) <= FLOOR-PLACE, hex(len(data)); return data


FLOOR_REGS = (31, 16, 17)
SINK, LIFT_FROM = 0.5, 40.0         # a spot more than SINK under the floor is buried; the query starts 40 above it


def floor_code():
    """a0 = a root XYZW: v0 = 1 when the terrain floor at its X/Z is more than SINK above it (Y down), with that
    floor's Y in its W; else 0 (no floor found, arena bounds unreadable). The floor query (spawn_placement's) runs
    from LIFT_FROM above the point, then from the arena ceiling; the native query globals are kept."""
    a = Assembler(FLOOR); frame(a, FLOOR_REGS, 0x40)
    a.move(16, 4); a.move(2, 0)
    a.li(8, arena_bounds.STAGE); a.lw(17, 8); throws.ptr(a, 17, 68, 'done'); a.lw(17, 17, 64)
    throws.ptr(a, 17, 12, 'done')
    for i, off in enumerate(terrain.QUERY_GLOBALS): a.lw(8, 28, off); a.sw(8, 29, 0x20+4*i)
    a.i(49, 0, 16, 4); fconst(a, 1, LIFT_FROM); fop(a, 1, 12, 0, 1)
    a.move(4, 16); a.call(QUERY); a.branch(5, 2, 0, 'hit')
    a.i(49, 12, 17, 4); a.move(4, 16); a.call(QUERY); a.branch(4, 2, 0, 'restore')
    a.label('hit'); a.move(2, 0); a.i(49, 1, 16, 4); fconst(a, 2, SINK); fop(a, 0, 2, 0, 2)
    fop(a, 0x34, 0, 2, 1); a.branch(17, 8, 0, 'restore')                         # floor + SINK < Y: buried
    a.i(57, 0, 16, 12); a.addiu(2, 0, 1)
    a.label('restore')
    for i, off in enumerate(terrain.QUERY_GLOBALS): a.lw(8, 29, 0x20+4*i); a.sw(8, 28, off)
    a.label('done'); unframe(a, FLOOR_REGS, 0x40); a.jr()
    data = a.finish(); assert len(data) <= QUERY-FLOOR, hex(len(data)); return data


def query_code():
    """spawn_placement's floor query (a0 = XYZ, f12 = top Y -> v0 valid, f0 floor Y), counting in our TELEMETRY."""
    code = core.rebound(terrain.query_code, QUERY=QUERY, CONTROL=CONTROL+TELEMETRY['floor_queries']-16)()
    assert len(code) <= TEXT-QUERY, hex(len(code)); return code


POSE_REGS = (16, 17, 18, 19, 31)


def pose_code():
    """a0 = the actor of a struggle-handler flag call. A pending assister seen here (its own struggle handler runs)
    is confirmed. A posed assister keeps its armour and its formation spot (re-placed every update: the struggle
    action does not hold it in the air) while its struggle runs with the ally still struggling; otherwise (failed,
    ended, aborted, another struggle, the ally out of the struggle, the assister fallen) its view is given back, it
    gets the native 'struggle over' flag once and returns to idle. A slot naming a fighter that now struggles itself
    is dropped without a flag."""
    a = Assembler(POSE); frame(a, POSE_REGS, 0x30)
    a.move(16, 4); a.call(SLOTOF); a.branch(4, 2, 0, 'done'); a.move(17, 2)        # s1 slot
    a.li(8, beam.CONTROL); a.lw(9, 8, 64); a.branch(4, 16, 9, 'drop'); a.lw(9, 8, 68); a.branch(4, 16, 9, 'drop')
    a.lw(9, 17, S['state']); a.addiu(10, 0, P_MOVING); a.branch(4, 9, 10, 'done')   # STEP owns a transition
    a.call(RUNNING); a.branch(4, 2, 0, 'release')
    a.li(8, beam.CONTROL); a.lw(9, 8, 24); a.lw(10, 17, S['serial']); a.branch(5, 9, 10, 'release')
    slot_side(a, 18, 17); a.r(0, 9, 0, 18, 2)
    a.r(0x21, 9, 9, 8); a.lw(19, 9, 64); a.lw(9, 19, 2376); a.addiu(9, 9, -304); a.i(11, 9, 9, 3)   # s3 ally
    a.branch(4, 9, 0, 'release')
    hp_row(a, 11, 16, 'release', temp=12); a.lw(9, 11); a.branch(6, 9, 0, 'release')
    a.lw(9, 17, S['state']); a.addiu(10, 0, P_FAILED); a.branch(4, 9, 10, 'release')
    a.addiu(10, 0, P_PENDING); a.branch(5, 9, 10, 'confirmed')
    a.move(4, 17); a.call(CONFIRM)
    a.lw(9, 17, S['state']); a.addiu(10, 0, P_CONFIRMED); a.branch(5, 9, 10, 'release')
    a.label('confirmed')
    a.lw(9, 16, 3608); a.i(10, 10, 9, 2); a.branch(4, 10, 0, 'held'); a.addiu(9, 0, 2); a.sw(9, 16, 3608)
    a.label('held'); bump(a, TELEMETRY['holds'])
    a.move(4, 17); a.addiu(5, 0, 1); a.call(VIEWSET)                            # a human's view stays on its ally
    a.li(8, beam.CONTROL); a.i(14, 9, 18, 1); a.r(0, 9, 0, 9, 2); a.r(0x21, 9, 9, 8); a.lw(6, 9, 64)   # a2 enemy
    a.move(4, 16); a.move(5, 19); a.move(7, 17); a.call(PLACE)
    a.branch(4, 2, 0, 'done'); bump(a, TELEMETRY['replaced']); a.jump('done')
    a.label('release'); a.move(4, 17); a.move(5, 0); a.call(VIEWSET); clear_slot(a, 17)
    a.move(4, 16); a.addiu(5, 0, RELEASE_FLAG); a.call(SET_FLAG); bump(a, TELEMETRY['released']); a.jump('done')
    a.label('drop'); a.move(4, 17); a.move(5, 0); a.call(VIEWSET); clear_slot(a, 17)
    a.label('done'); unframe(a, POSE_REGS, 0x30); a.jr()
    data = a.finish(); assert len(data) <= FRAMESTUB-POSE, hex(len(data)); return data


def slot_side(a, out, slot, temp=9):
    """out = the side (0/1) of a slot record address (register); clobbers temp."""
    a.li(temp, CONTROL+SLOTS); a.r(0x23, out, slot, temp); a.r(2, out, 0, out, 8)


def clear_slot(a, slot):
    for off in range(0, SLOT_STRIDE, 4): a.sw(0, slot, off)


def free_code():
    """Leaf: a0 = side -> v0 = its first free slot record (0 when full), v1 = its occupied slots; t0..t2 only."""
    a = Assembler(FREE); a.li(8, CONTROL+SLOTS); a.r(0, 9, 0, 4, 8); a.r(0x21, 8, 8, 9)
    a.move(2, 0); a.move(3, 0); a.addiu(10, 0, MAX_ASSISTS)
    a.label('loop'); a.lw(9, 8, S['actor']); a.branch(4, 9, 0, 'free'); a.addiu(3, 3, 1); a.jump('next')
    a.label('free'); a.branch(5, 2, 0, 'next'); a.move(2, 8)
    a.label('next'); a.addiu(8, 8, SLOT_STRIDE); a.addiu(10, 10, -1); a.branch(5, 10, 0, 'loop'); a.jr()
    data = a.finish(); assert len(data) <= SLOTOF-FREE, hex(len(data)); return data


def slotof_code():
    """Leaf: a0 = actor -> v0 = the slot record naming it, else 0; t0..t2 only."""
    a = Assembler(SLOTOF); a.li(8, CONTROL+SLOTS); a.addiu(10, 0, 2*MAX_ASSISTS); a.move(2, 0)
    a.branch(4, 4, 0, 'done')
    a.label('loop'); a.lw(9, 8, S['actor']); a.branch(4, 9, 4, 'found')
    a.addiu(8, 8, SLOT_STRIDE); a.addiu(10, 10, -1); a.branch(5, 10, 0, 'loop'); a.jr()
    a.label('found'); a.move(2, 8)
    a.label('done'); a.jr()
    data = a.finish(); assert len(data) <= FAILCAP-SLOTOF, hex(len(data)); return data


def failcap_code():
    """Leaf: a0 = side, a1 = reason (F_*, 0 = silent): the side's failure caption (reason and age) and its counter;
    t0..t2 only."""
    a = Assembler(FAILCAP); a.branch(4, 5, 0, 'done')
    a.li(8, CONTROL); a.r(0, 9, 0, 4, 2); a.r(0x21, 9, 9, 8); a.sw(5, 9, C['fail'])
    a.li(10, beam.CONTROL); a.lw(10, 10, 20); a.sw(10, 9, C['fail_age'])
    a.addiu(9, 5, -1); a.i(11, 10, 9, 3); a.branch(4, 10, 0, 'done')
    a.r(0, 9, 0, 9, 2); a.li(10, CONTROL+TELEMETRY['fail_busy']); a.r(0x21, 10, 10, 9)
    a.lw(9, 10); a.addiu(9, 9, 1); a.sw(9, 10)
    a.label('done'); a.jr()
    data = a.finish(); assert len(data) <= SWEEP-FAILCAP, hex(len(data)); return data


SWEEP_REGS = (31, 16, 17, 18, 19, 20)


def sweep_code():
    """Every frame start (R3PRE) and running struggle tick (TICKBLOCK): a slot whose struggle stopped running (or
    is another struggle) gives its human's view back; one still moving or pending there is cancelled silently (nothing
    paid, its request withdrawn); a posed or failed one whose assister left the struggle action (hit out of it, or
    the struggle over) is freed. A posed assister still in the action is left to its own handler (POSE: the native
    'struggle over' flag)."""
    a = Assembler(SWEEP); frame(a, SWEEP_REGS, 0x30)
    a.call(RUNNING); a.move(18, 2); a.li(19, beam.CONTROL); a.lw(19, 19, 24)          # s2 running, s3 serial
    a.li(16, CONTROL+SLOTS); a.addiu(20, 0, 2*MAX_ASSISTS)
    a.label('loop'); a.lw(17, 16, S['actor']); a.branch(4, 17, 0, 'next')
    a.branch(4, 18, 0, 'stopped'); a.lw(9, 16, S['serial']); a.branch(5, 9, 19, 'stopped')
    a.lw(9, 16, S['state']); a.addiu(10, 0, P_CONFIRMED); a.branch(4, 9, 10, 'posed')
    a.addiu(10, 0, P_FAILED); a.branch(5, 9, 10, 'next')
    a.label('posed'); a.lw(9, 17, 2376); in_struggle(a, 9, 'gone'); a.jump('next')
    a.label('stopped'); a.move(4, 16); a.move(5, 0); a.call(VIEWSET)
    a.lw(9, 16, S['state']); a.addiu(10, 9, -P_MOVING); a.branch(4, 10, 0, 'cancel')
    a.addiu(10, 9, -P_PENDING); a.branch(5, 10, 0, 'posed')
    a.label('cancel'); a.move(4, 16); a.move(5, 0); a.call(FAIL); a.jump('next')
    a.label('gone'); a.move(4, 16); a.move(5, 0); a.call(VIEWSET); clear_slot(a, 16)
    a.label('next'); a.addiu(16, 16, SLOT_STRIDE); a.addiu(20, 20, -1); a.branch(5, 20, 0, 'loop')
    unframe(a, SWEEP_REGS, 0x30); a.jr()
    data = a.finish(); assert len(data) <= KIBLAST-SWEEP, hex(len(data)); return data


VIEW_REGS = (31, 16, 17, 18, 19)


def viewset_code():
    """a0 = slot, a1 = 1: a human assister's own view follows its struggling ally from now on (the view whose subject
    word names the assister: a viewport_hud view descriptor - quad_viewports' SUBJECTS with two or more humans - else
    the single view's camera successor owner), kept so on every later call (POSE, each update of its pose); a1 = 0:
    a switched view is given back (only while it still names the ally: a KO successor or takeover keeps its own)."""
    a = Assembler(VIEWSET); frame(a, VIEW_REGS, 0x30)
    a.move(16, 4); a.branch(5, 5, 0, 'switch')
    a.lw(8, 16, S['view']); a.branch(4, 8, 0, 'done')
    a.lw(9, 8); a.lw(10, 16, S['view_new']); a.branch(5, 9, 10, 'forget')
    a.lw(9, 16, S['view_old']); a.sw(9, 8); bump(a, TELEMETRY['view_restored'])
    a.label('forget'); a.sw(0, 16, S['view']); a.jump('done')
    a.label('switch'); a.lw(17, 16, S['actor']); a.branch(4, 17, 0, 'done')
    a.lw(9, 17, 0x1278); a.branch(5, 9, 0, 'done')                                # humans only
    # Already switched: kept every update. The view's own owner (quad_lifecycle's seat publisher, a spectator
    # switch) writes the player back each frame; written back to the player it is switched again, taken over by
    # anything else (a KO successor, a takeover) it is left alone and forgotten.
    a.lw(8, 16, S['view']); a.branch(4, 8, 0, 'first')
    a.lw(9, 8); a.lw(10, 16, S['view_new']); a.branch(4, 9, 10, 'done')
    a.lw(10, 16, S['view_old']); a.branch(5, 9, 10, 'forget')
    a.lw(10, 16, S['view_new']); a.sw(10, 8); a.jump('done')
    a.label('first')
    a.lw(18, 16, S['phys'])                                                       # s2 = whose view to find
    slot_side(a, 9, 16); a.r(0, 9, 0, 9, 2); a.li(8, beam.INDICES); a.r(0x21, 8, 8, 9); a.lw(19, 8)   # s3 ally
    a.li(8, hud.CONTROL); a.lw(9, 8); a.li(10, hud.MAGIC); a.branch(5, 9, 10, 'single')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'single')
    a.lw(11, 8, 12); a.i(10, 10, 11, hud.MAX_VIEWS+1); a.branch(4, 10, 0, 'single')
    a.li(12, hud.VIEWS)
    a.label('view'); a.branch(4, 11, 0, 'single')
    a.lw(9, 12); a.branch(4, 9, 0, 'next_view')                                    # enabled
    a.lw(13, 12, 20); throws.ptr(a, 13, 4, 'next_view'); a.lw(9, 13); a.branch(4, 9, 18, 'found')
    a.label('next_view'); a.addiu(12, 12, hud.VIEW_STRIDE); a.addiu(11, 11, -1); a.jump('view')
    a.label('single'); a.li(13, camera.SUCCESSOR_CONTROL+8); a.lw(9, 13); a.branch(5, 9, 18, 'done')
    a.label('found'); a.sw(13, 16, S['view']); a.sw(18, 16, S['view_old']); a.sw(19, 16, S['view_new'])
    a.sw(19, 13); bump(a, TELEMETRY['view_switched'])
    a.label('done'); unframe(a, VIEW_REGS, 0x30); a.jr()
    data = a.finish(); assert len(data) <= PLACE-VIEWSET, hex(len(data)); return data


KEEP_REGS = (8, 9, 10, 11, 31)


def keepcam_code():
    """jal from the struggle's three scripted-camera calls (args in a0..a3, t0..t3, f12..f17 and the caller's stack):
    with the camera option on, in our live match, return at once (no script: every view keeps its own player's
    camera); otherwise j 1C6E78 with every argument intact. Only v0/v1 (1C6E78 overwrites both) are clobbered."""
    a = Assembler(KEEPCAM); frame(a, KEEP_REGS, 0x30)
    a.call(GATE); a.branch(4, 2, 0, 'native')
    a.li(2, CONTROL); a.lw(3, 2, C['camera']); a.branch(4, 3, 0, 'native')
    a.lw(3, 2, TELEMETRY['kept_camera']); a.addiu(3, 3, 1); a.sw(3, 2, TELEMETRY['kept_camera'])
    unframe(a, KEEP_REGS, 0x30); a.jr()
    a.label('native'); unframe(a, KEEP_REGS, 0x30); a.jump(SCRIPT_CAMERA)
    data = a.finish(); assert len(data) <= REGISTER-KEEPCAM, hex(len(data)); return data


def multiplier_code():
    """Leaf: v0 = min(MAX, mult0 * mult1 / 100) for the current serial, else 100; t0..t4."""
    a = Assembler(MULTIPLIER); a.li(8, CONTROL); a.li(9, beam.CONTROL); a.addiu(2, 0, 100)
    a.lw(10, 8, C['serial']); a.lw(11, 9, 24); a.branch(5, 10, 11, 'done')
    a.lw(10, 8, C['side']); a.lw(11, 8, C['side']+SIDE_STRIDE); multu(a, 10, 11); mflo(a, 10)
    a.addiu(11, 0, 100); divu(a, 10, 11); mflo(a, 2)
    a.lw(10, 8, C['max_mult']); a.r(0x2A, 11, 10, 2); a.branch(4, 11, 0, 'done'); a.move(2, 10)
    a.label('done'); a.jr()
    data = a.finish(); assert len(data) <= DRAW-MULTIPLIER; return data


def kiblast_code():
    """jal from 1CB6A8 (a0 = defender action, s1 = defender): no action immunity for a struggling fighter."""
    a = Assembler(KIBLAST); a.addiu(29, 29, -0x20); a.i(63, 31, 29, 0); a.i(63, 4, 29, 8)
    a.li(8, CONTROL); a.lw(9, 8, C['interference']); a.branch(4, 9, 0, 'native')
    a.call(RUNNING); a.branch(4, 2, 0, 'native')
    side_of(a, 17, 9, 'native', temp=10)
    a.i(55, 4, 29, 8); a.addiu(9, 4, -304); a.i(11, 9, 9, 3); a.branch(4, 9, 0, 'native')
    bump(a, TELEMETRY['kiblast_bypassed'])
    a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20); a.move(2, 0); a.jr()
    a.label('native'); a.i(55, 4, 29, 8); a.i(55, 31, 29, 0); a.addiu(29, 29, 0x20); a.jump(ACTION_IMMUNE)
    data = a.finish(); assert len(data) <= DMG-KIBLAST; return data


DMG_REGS = (16, 17, 18, 19, 20, 21, 22, 23, 31, 4, 5, 6, 7)


def dmg_code():
    """jal from 1D922C (a0 loser, a1 damage, a2 flags; s3 winner): the assist multiplier."""
    a = Assembler(DMG); frame(a, DMG_REGS, 0x70)
    a.call(GATE); a.branch(4, 2, 0, 'native')
    a.i(55, 4, 29, 72); side_of(a, 4, 9, 'native', temp=10)
    a.call(MULTIPLIER); a.move(20, 2)
    a.i(55, 5, 29, 80); a.move(21, 5); a.branch(1, 5, 0, 'scaled')                 # negative damage: unchanged
    a.li(9, DAMAGE_CAP); a.r(0x2A, 10, 9, 21); a.branch(4, 10, 0, 'capped'); a.move(21, 9)
    a.label('capped'); scale_percent(a, 21, 20)
    a.label('scaled'); a.li(16, CONTROL); a.sw(21, 16, TELEMETRY['last_end_damage'])
    a.addiu(9, 0, 100); a.branch(4, 20, 9, 'same'); bump(a, TELEMETRY['end_damage_scaled'])
    a.label('same'); a.i(63, 21, 29, 80)                                        # the loser's scaled damage
    unframe(a, DMG_REGS, 0x70); a.jump(DAMAGE)
    a.label('native'); unframe(a, DMG_REGS, 0x70); a.jump(DAMAGE)
    data = a.finish(); assert len(data) <= CINE-DMG; return data


def cine_code():
    """jal from 1D9178 (a0 winner, a1 loser): record the struggle's multiplier for the cinematic's hits."""
    a = Assembler(CINE); frame(a, (31, 4, 5, 6, 7), 0x30)
    a.call(GATE); a.branch(4, 2, 0, 'native')
    a.li(8, CONTROL); a.lw(9, 8, C['assist']); a.branch(4, 9, 0, 'native')
    a.i(55, 5, 29, 16); side_of(a, 5, 9, 'native', temp=10)
    a.call(MULTIPLIER); a.li(8, CONTROL); a.sw(2, 8, C['pending_mult'])
    a.i(55, 4, 29, 8); a.sw(4, 8, C['pending_winner']); a.i(55, 5, 29, 16); a.sw(5, 8, C['pending_loser'])
    a.li(9, beam.CONTROL); a.lw(9, 9, 24); a.sw(9, 8, C['pending_serial'])
    bump(a, TELEMETRY['cine_pending_set'])
    a.label('native'); unframe(a, (31, 4, 5, 6, 7), 0x30); a.jump(CINEMATIC)
    data = a.finish(); assert len(data) <= HIT-CINE; return data


HIT_REGS = (16, 17, 18, 19, 20, 21, 22, 23, 31, 4, 5, 6, 7, 3)


def hit_code():
    """Entered by j from a STUB (v1 = the audited attacker, ra = original site+8); always ends in j 1CE630."""
    a = Assembler(HIT); frame(a, HIT_REGS, 0x70)
    slot = {r: 8*i for i, r in enumerate(HIT_REGS)}
    a.call(GATE); a.branch(4, 2, 0, 'finish')
    a.li(16, CONTROL); a.li(17, beam.CONTROL)
    a.lw(9, 16, C['pending_serial']); a.branch(4, 9, 0, 'finish'); a.lw(10, 17, 24); a.branch(5, 9, 10, 'finish')
    a.lw(18, 16, C['pending_loser']); a.lw(11, 18, 2376)
    a.addiu(12, 11, -313); a.i(11, 12, 12, 3); a.branch(5, 12, 0, 'cinematic')
    a.addiu(12, 11, -304); a.i(11, 12, 12, 3); a.branch(5, 12, 0, 'finish')         # still struggling: keep it
    a.sw(0, 16, C['pending_serial']); bump(a, TELEMETRY['cine_pending_cleared']); a.jump('finish')
    a.label('cinematic')
    a.i(55, 4, 29, slot[4]); a.branch(5, 4, 18, 'finish')
    a.i(55, 3, 29, slot[3]); a.lw(9, 16, C['pending_winner']); a.branch(5, 3, 9, 'finish')
    a.i(55, 5, 29, slot[5]); a.branch(1, 5, 0, 'finish')
    a.li(9, DAMAGE_CAP); a.r(0x2A, 10, 9, 5); a.branch(4, 10, 0, 'cine_capped'); a.move(5, 9)
    a.label('cine_capped'); a.lw(20, 16, C['pending_mult']); scale_percent(a, 5, 20); a.i(63, 5, 29, slot[5])
    bump(a, TELEMETRY['cine_scaled_hits'])
    a.label('finish'); unframe(a, HIT_REGS, 0x70); a.jump(DAMAGE)
    data = a.finish(); assert len(data) <= STUBS-HIT; return data


def stubs_code(attribution):
    """One 16-byte stub per audited damage call site: v1 = its attacker register, then HIT."""
    a = Assembler(STUBS); sites = {}
    for k, (ra, reg) in enumerate(sorted(attribution.items())):
        assert a.pc == STUBS + STUB_SIZE*k
        sites[ra-8] = a.pc
        a.r(0x2D, 3, reg, 0); a.jump(HIT); a.emit(0)
    data = a.finish(); assert len(data) <= KEEPCAM-STUBS, hex(len(data)); return data, sites


PRE_REGS = (2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 31)
PRE_FRAME = 0x80


def caves():
    """{cave base: kind} of cinematic_contact_guard (0 direct, 1 queued, 2 direct special, 3 projectile, 4 reverse)."""
    return {cave: k for k, (_, cave, _, _) in enumerate(contact.SPECS) if k < 5}


def shot_returns():
    """(forward, reverse) return addresses of multi_contact.PROJECTILE's two contact.PROTECTED calls."""
    import multi_contact
    code = multi_contact.projectile_code()
    words = struct.unpack('<%dI' % (len(code)//4), code)
    calls = [i*4 for i, w in enumerate(words) if w == u32(CALL(contact.PROTECTED))]
    if len(calls) != 2: raise ValueError('Expected two contact calls in the multi-contact projectile program')
    return tuple(multi_contact.PROJECTILE + offset + 8 for offset in calls)


def bystander_code():
    """Leaf: v0 = 1 when a0 is a captured, participating, living enemy of participant index a1 that is neither
    throwing nor in a cinematic action (current, requested or queued). t0..t7 only."""
    a = Assembler(BYSTANDER); a.move(14, 4); a.move(15, 5)
    physical(a, 14, 13, 'no', 'scan')
    participating(a, 13, 'no')
    hp_row(a, 11, 14, 'no', temp=8); a.lw(9, 11); a.branch(6, 9, 0, 'no')
    for offset in throws.ACTION_FIELDS:
        a.lw(10, 14, offset); in_ranges(a, 10, SOURCE_BUSY, 'no')
    policy.emit_enemy(a, 13, 15, 'no', 'enemy', t0=8, t1=9)
    a.addiu(2, 0, 1); a.jr(); a.label('no'); a.move(2, 0); a.jr()
    data = a.finish(); assert len(data) <= TRAMPOLINE-BYSTANDER, hex(len(data)); return data


def pre_code(original):
    """beam_clash.CONTACT entry: a bystander's melee/queued/projectile contact on a struggling enemy continues
    to the rest of the contact chain; everything else runs beam_clash.CONTACT unchanged (trampoline)."""
    forward, reverse = shot_returns()
    a = Assembler(PRE); frame(a, PRE_REGS, PRE_FRAME)
    a.li(8, CONTROL); a.lw(9, 8, C['interference']); a.branch(4, 9, 0, 'native')
    a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'native')
    # Contact kind from the guard's return address.
    first = min(caves()); a.li(9, first); a.r(0x23, 9, 31, 9); a.i(11, 10, 9, 0x400*5); a.branch(4, 10, 0, 'shot')
    a.r(2, 9, 0, 9, 10)
    for k in (2, 4): a.addiu(10, 0, k); a.branch(4, 9, 10, 'native')
    a.addiu(24, 0, 0); a.jump('kind')
    a.label('shot'); a.li(9, forward); a.addiu(24, 0, 1); a.branch(4, 31, 9, 'kind')
    a.li(9, reverse); a.addiu(24, 0, 2); a.branch(5, 31, 9, 'native')
    a.label('kind'); a.i(63, 24, 29, 0x78)
    a.call(RUNNING); a.branch(4, 2, 0, 'native')
    a.i(55, 4, 29, 16); a.i(55, 5, 29, 24); a.i(55, 24, 29, 0x78); a.li(8, beam.CONTROL)
    a.addiu(9, 0, 2); a.branch(4, 24, 9, 'reverse')
    # Forward (a0 source -> a1 struggling target).
    a.lw(9, 8, 64); a.lw(25, 8, 80); a.branch(4, 5, 9, 'target')
    a.lw(9, 8, 68); a.lw(25, 8, 84); a.branch(5, 5, 9, 'native')
    a.label('target'); a.lw(9, 8, 64); a.branch(4, 4, 9, 'native'); a.lw(9, 8, 68); a.branch(4, 4, 9, 'native')
    a.move(5, 25); a.call(BYSTANDER); a.branch(4, 2, 0, 'native'); a.jump('allowed')
    # Reverse shot check (a0 struggling candidate, a1 shooter).
    a.label('reverse')
    a.lw(9, 8, 64); a.lw(25, 8, 80); a.branch(4, 4, 9, 'source')
    a.lw(9, 8, 68); a.lw(25, 8, 84); a.branch(5, 4, 9, 'native')
    a.label('source'); a.lw(9, 8, 64); a.branch(4, 5, 9, 'native'); a.lw(9, 8, 68); a.branch(4, 5, 9, 'native')
    a.move(4, 5); a.move(5, 25); a.call(BYSTANDER); a.branch(4, 2, 0, 'native')
    a.label('allowed'); bump(a, TELEMETRY['contacts_allowed'])
    a.i(55, 24, 29, 0x78); a.branch(4, 24, 0, 'continue'); bump(a, TELEMETRY['shot_contacts_allowed'])
    a.label('continue'); unframe(a, PRE_REGS, PRE_FRAME); a.jump(throws.CONTACT)
    a.label('native'); unframe(a, PRE_REGS, PRE_FRAME); a.jump(TRAMPOLINE)
    data = a.finish(); assert len(data) <= BYSTANDER-PRE, hex(len(data))
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23)
    t = Assembler(TRAMPOLINE)
    for word in struct.unpack('<2I', original): t.emit(word)
    t.jump(beam.CONTACT+8)
    return data, t.finish()


DRAW_REGS = (16, 17, 18, 19, 20, 21, 22, 23, 31)


def draw_code():
    """Per view: 'BEAM ASSIST Xm' for a struggle side that was just assisted, or the R3 hint for an eligible
    human ally within the assist range, above the revival text (killfeed glyphs)."""
    a = Assembler(DRAW); frame(a, DRAW_REGS, 0x50)
    a.call(GATE); a.branch(4, 2, 0, 'done')
    a.li(16, CONTROL); a.lw(9, 16, C['assist']); a.branch(4, 9, 0, 'done')
    a.li(17, beam.CONTROL); a.lw(9, 17, 16); a.branch(4, 9, 0, 'done')
    a.lw(18, 28, -22176); throws.ptr(a, 18, 832, 'done')
    a.li(19, camera.SUCCESSOR_CONTROL+8)
    a.call(hud.ACTIVE); a.branch(4, 2, 0, 'subject'); a.li(20, hud.VIEWS); a.move(21, 0)
    a.label('view')
    for off, desc in ((512, 4), (516, 8), (520, 12), (524, 16)):
        a.lw(8, 18, off); a.lw(9, 20, desc); a.branch(5, 8, 9, 'next_view')
    a.lw(19, 20, 20); a.jump('subject')
    a.label('next_view'); a.addiu(20, 20, hud.VIEW_STRIDE); a.addiu(21, 21, 1); a.addiu(8, 0, hud.MAX_VIEWS)
    a.branch(5, 21, 8, 'view'); a.jump('done')
    a.label('subject'); a.lw(20, 19); a.lw(9, 16, C['count']); a.r(0x2B, 9, 20, 9); a.branch(4, 9, 0, 'done')
    actor_at(a, 21, 20); a.branch(4, 21, 0, 'done')
    a.lw(9, 16, C['serial']); a.lw(10, 17, 24); a.move(22, 0); a.branch(5, 9, 10, 'hint')
    a.addiu(22, 0, 1)                                                           # s6: STATE is this struggle's
    a.lw(9, 17, 64); a.branch(4, 21, 9, 'side0'); a.lw(9, 17, 68); a.branch(4, 21, 9, 'side1')
    for side in range(2):
        a.lw(9, 16, C['masks']+4*side); a.r(6, 9, 20, 9); a.i(12, 9, 9, 1); a.branch(5, 9, 0, f'side{side}')
    a.jump('hint')
    for side in range(2):
        a.label(f'side{side}'); a.addiu(23, 16, SIDE_STRIDE*side); a.addiu(12, 16, 4*side); a.jump('caption')
    # beta.39: a failed (unpaid) assist says why, for the same views and time as the bonus caption; beta.40: the
    # newer of the side's last failure and its last confirmed assist is shown, the assist caption naming the side's
    # multiplier after that many assists.
    a.label('caption'); a.lw(9, 12, C['fail']); a.branch(4, 9, 0, 'assisted')
    a.lw(10, 12, C['fail_age']); a.lw(11, 17, 20); a.r(0x23, 11, 11, 10)
    a.lw(13, 16, C['caption_ticks']); a.r(0x2B, 11, 11, 13); a.branch(4, 11, 0, 'assisted')
    a.lw(11, 23, C['side']+SIDE['assists']); a.branch(6, 11, 0, 'failed')
    a.lw(11, 23, C['side']+SIDE['assist_age']); a.r(0x2A, 11, 10, 11); a.branch(5, 11, 0, 'assisted')
    a.label('failed'); a.addiu(9, 9, -1); a.i(11, 10, 9, len(FAIL_TEXTS)); a.branch(4, 10, 0, 'assisted')
    a.r(0, 9, 0, 9, 5); a.li(4, FAIL_TEXT); a.r(0x21, 4, 4, 9); a.jump('draw')
    a.label('assisted'); a.lw(9, 23, C['side']+SIDE['assists']); a.branch(6, 9, 0, 'hint')
    a.lw(10, 23, C['side']+SIDE['assist_age']); a.lw(11, 17, 20); a.r(0x23, 11, 11, 10)
    a.lw(10, 16, C['caption_ticks']); a.r(0x2B, 11, 11, 10); a.branch(4, 11, 0, 'hint')
    a.i(11, 10, 9, MAX_ASSISTS+1); a.branch(5, 10, 0, 'counted'); a.addiu(9, 0, MAX_ASSISTS)
    a.label('counted'); a.addiu(9, 9, -1); a.r(0, 9, 0, 9, 5); a.li(4, TEXT); a.r(0x21, 4, 4, 9); a.jump('draw')
    a.label('hint')
    a.li(8, core.ACTORS); a.lw(8, 8); a.lw(9, 8, 64); a.addiu(9, 9, -1); a.i(11, 9, 9, 2); a.branch(4, 9, 0, 'done')
    a.lw(9, 21, 0x1278); a.branch(5, 9, 0, 'done')
    a.lw(9, 17, 64); a.branch(4, 21, 9, 'done'); a.lw(9, 17, 68); a.branch(4, 21, 9, 'done')
    hp_row(a, 23, 21, 'done', temp=9); a.lw(9, 23); a.branch(6, 9, 0, 'done')
    a.lw(9, 23, 20); a.li(10, STOCK); a.r(0x2A, 9, 9, 10); a.branch(5, 9, 0, 'done')
    ally_side(a, 20, 'done', 'hint')                                              # t5 = side
    a.move(4, 13); a.call(FREE); a.branch(4, 2, 0, 'done')                       # every slot of that side taken
    a.branch(4, 22, 0, 'reach')
    a.r(0, 14, 0, 13, 2); a.r(0x21, 14, 14, 16); a.lw(9, 14, C['masks']); a.r(6, 9, 20, 9); a.i(12, 9, 9, 1)
    a.branch(5, 9, 0, 'done')
    a.label('reach'); a.r(0, 14, 0, 13, 2); a.r(0x21, 14, 14, 17); a.lw(19, 14, 64)   # s3 = the struggling ally
    in_range(a, 21, 19, 'done')
    a.label('hint_text'); a.li(4, HINT_TEXT)
    # A black outline keeps the caption readable on the struggle's white glow (LOOKed live: plain text vanished).
    a.label('draw'); a.move(23, 4)
    a.lw(21, 18, 512); a.addiu(21, 21, 1792+8); a.lw(22, 18, 524); a.addiu(22, 22, Y_ORIGIN+screen_y(CAPTION_Y))
    for dx, dy, color in ((-1, 0, OUTLINE_COLOR), (1, 0, OUTLINE_COLOR), (0, -1, OUTLINE_COLOR), (0, 1, OUTLINE_COLOR),
                          (0, 0, CAPTION_COLOR)):
        a.move(4, 23); a.addiu(5, 21, dx); a.r(0, 5, 0, 5, 4); a.addiu(6, 22, dy); a.r(0, 6, 0, 6, 4)
        a.li(7, color); a.call(feed.TEXT)
    a.label('done'); unframe(a, DRAW_REGS, 0x50); a.jr()
    data = a.finish(); assert len(data) <= ASSIST-DRAW, hex(len(data)); return data


# ------------------------------------------------------------------------------------------ composition

def programs(consts, original_contact):
    pre, trampoline = pre_code(original_contact)
    stubs, _ = stubs_code(feed.ATTRIBUTION)
    out = [(GATE, gate_code()), (RUNNING, running_code()), (SYNC, sync_code()),
           (ENDCHECK, endcheck_code(consts['limit'])), (TUG, tug_code()), (PUSH, push_code(consts['inc'])),
           (FLAGS, flags_code(consts['flags'])), (TICKBLOCK, tickblock_code()),
           (ASSIST, assist_code()), (KIBLAST, kiblast_code()), (DMG, dmg_code()), (CINE, cine_code()),
           (HIT, hit_code()), (STUBS, stubs), (PLACE, place_code()), (PRE, pre), (BYSTANDER, bystander_code()),
           (TRAMPOLINE, trampoline),
           (REGISTER, register_code()), (MULTIPLIER, multiplier_code()), (DRAW, draw_code()), (POSE, pose_code()),
           (R3PRE, r3pre_code()), (ELIGIBLE, eligible_code()), (STEP, step_code()),
           (CONFIRM, confirm_code()), (FAIL, fail_code()), (FLOOR, floor_code()), (QUERY, query_code()),
           (REFUSE, refuse_code()), (FREE, free_code()), (SLOTOF, slotof_code()), (FAILCAP, failcap_code()),
           (SWEEP, sweep_code()), (VIEWSET, viewset_code()), (KEEPCAM, keepcam_code())]
    spans = sorted((p, p+len(d)) for p, d in out)
    assert all(e <= s for (_, e), (s, _) in zip(spans, spans[1:])) and spans[-1][1] <= TEXT
    return out


def hook_patches(mask):
    """(site, new bytes) for every native or chained site the installed groups own."""
    out = []
    if mask & G_CLOCK:
        out += [(END_TEST, JUMP(ENDCHECK)), (TUG_SITE, JUMP(TUG))]
    if mask & G_PUSH:
        out.append((PUSH_SITE, CALL(PUSH) + struct.pack('<2I', DADDU_A0_S1, 0)))
    if mask & G_TICK:
        out += [(site, CALL(FLAGS)) for site in FLAG_SITES]
    if mask & G_HITS:
        out += [(KIBLAST_SITE, CALL(KIBLAST)), (beam.CONTACT, JUMP(PRE))]
    if mask & G_END:
        out.append((DMG_SITE, CALL(DMG)))
    if mask & G_CINE:
        _, sites = stubs_code(feed.ATTRIBUTION)
        out.append((CINE_SITE, CALL(CINE)))
        out += [(site, CALL(stub)) for site, stub in sorted(sites.items())]
    if mask & G_CAMERA:
        out += [(site, CALL(KEEPCAM)) for site in CAMERA_SITES]
    return out


def hook_originals(mask, native_read):
    """(site, bytes) the hook sites hold before this module: native executable bytes (beam CONTACT: its entry)."""
    out = []
    for site, data in hook_patches(mask):
        if site == beam.CONTACT: out.append((site, beam.contact_code()[:8]))
        else: out.append((site, native_read(site, len(data))))
    return out


def installed(ram):
    return u32(ram, CONTROL) == MAGIC


def installed_groups(ram):
    return u32(ram, CONTROL+C['groups']) if installed(ram) else 0


def overlay(ram):
    """Bytes this module writes into other modules' validated programs while installed: the PRE entry inside
    beam_clash.CONTACT and the stub calls at guest_killfeed's audited damage call sites."""
    if not installed(ram): return []
    mask = installed_groups(ram)
    out = [(p, d) for p, d in hook_patches(mask) if p == beam.CONTACT or p in feed_sites()]
    for p, d in out:
        if ram[p:p+len(d)] != d: raise ValueError(f'Changed beam struggle overlay {p:08X}')
    return out


def feed_sites():
    return {ra-8 for ra in feed.ATTRIBUTION}


def with_overlay(ram, pieces):
    """pieces with this module's overlay bytes substituted where they fall inside a piece."""
    entries = overlay(ram)
    if not entries: return list(pieces)
    out = []
    for p, data in pieces:
        data = bytearray(data)
        for q, patch in entries:
            lo, hi = max(p, q), min(p+len(data), q+len(patch))
            if lo < hi:
                if lo != q or hi != q+len(patch): raise ValueError('Beam struggle overlay straddles a piece')
                data[lo-p:hi-p] = patch
        out.append((p, bytes(data)))
    return out


def dependency_override(ram, address, expected):
    """Recognise only this module's exact overlay inside another module's strict validator."""
    replaced = with_overlay(ram, [(address, expected)])[0][1]
    return replaced


def hud_extension(ram):
    """viewport_hud per-view extension entry while the assist caption is installed, else None."""
    if not installed(ram) or not installed_groups(ram) & G_CAPTION: return None
    return (CONTROL, MAGIC, DRAW)


def hud_patch(ram):
    """The viewport_hud wrapper with our caption added after revive.DRAW, or [] (no split HUD installed)."""
    if u32(ram, hud.CONTROL) != hud.MAGIC: return []
    previous = u32(ram, hud.CONTROL+16)
    before = hud.hud_extensions(ram)
    after = hud.hud_extensions(ram, installing={'beam_struggle': (CONTROL, MAGIC, DRAW)})
    for kw in (dict(deferred=True), dict(), dict(revival=False, deferred=True), dict(revival=False)):
        old = hud.wrapper(previous, extensions=before, **kw)
        if ram[hud.CODE:hud.CODE+len(old)] == old:
            new = hud.wrapper(previous, extensions=after, **kw)
            if new == old: return []
            if len(new) > hud.ACTIVE-hud.CODE: raise ValueError('Viewport HUD wrapper extension too large')
            if any(ram[hud.CODE+len(old):hud.CODE+len(new)]): raise ValueError('Viewport HUD wrapper tail occupied')
            return [(hud.CODE, new)]
    raise ValueError('Unknown viewport HUD wrapper')


def control_bytes(manager, count, battle, consts, settings, mask, frame_prev=0):
    out = bytearray(CONTROL_SIZE)
    struct.pack_into('<I', out, C['frame_prev'], frame_prev)
    struct.pack_into('<8I', out, 0, MAGIC, manager, count, battle, VERSION, consts['intro'], consts['limit'], consts['inc'])
    out[0x20:0x70] = config_bytes(settings, consts, mask)
    for side in range(2): struct.pack_into('<I', out, C['side']+SIDE_STRIDE*side, 100)
    struct.pack_into('<I', out, C['last_counter'], 0xFFFFFFFF)
    return bytes(out)


def build_memory(ram, settings=None, source='<prepared>'):
    """The guarded install (or, over an installed match, the new CONFIG). All-legacy settings on a match without
    the module return no blocks before anything is scanned."""
    s = mod_settings.validate_settings(settings or {})
    if not (len(ram) >= END and installed(ram)) and legacy(s): return dict(blocks=[])
    if len(ram) != 0x8000000: raise ValueError('Beam struggle options require 128 MiB captured RAM')
    return _build(ram, s, source)


@policy.matching_install
def _build(ram, s, source):
    u = lambda p: u32(ram, p)
    present = installed(ram)
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if count not in policy.ACTOR_COUNTS or (u(core.MODE), u(core.MODE+8), u(core.MODE+12)) != (1, manager, count):
        raise ValueError('Beam struggle options require a captured active match')
    battle = u(team_intro.BATTLE)
    if (u(beam.CONTROL), u(beam.CONTROL+4), u(beam.CONTROL+8)) != (beam.MAGIC, manager, count):
        raise ValueError('Beam struggle options need the actual-pair beam clash of this match')
    read = native()
    consts = disc_constants(read)
    ram_consts = disc_constants(lambda p, n: bytes(ram[p:p+n])) if not present else None
    if ram_consts is not None and ram_consts != consts:
        raise ValueError('Beam struggle executable and RAM constants differ')
    if present:
        mask = u(CONTROL+C['groups'])
        if (u(CONTROL+4), u(CONTROL+8), u(CONTROL+12)) != (manager, count, battle):
            raise ValueError('Beam struggle install belongs to another match')
        if ram[CONTROL+0x10:CONTROL+0x20] != struct.pack('<4I', VERSION, consts['intro'], consts['limit'], consts['inc']):
            raise ValueError('Beam struggle install constants changed')
        code = programs(consts, beam.contact_code()[:8])
        frame_prev = u(CONTROL+C['frame_prev'])
        if frame_prev: code = code + [(FRAMESTUB, frame_stub(frame_prev))]
        for p, d in code + hook_patches(mask):
            if ram[p:p+len(d)] != d: raise ValueError(f'Changed beam struggle program {p:08X}')
        config = config_bytes(s, consts, mask)
        patches = [(CONTROL+0x20, config), (TEXT, text_bytes(s))]
    else:
        if any(ram[BASE:END]): raise ValueError('Beam struggle reservation occupied')
        mask = groups(s)
        if mask & G_CINE:
            if (u(feed.CONTROL), u(feed.CONTROL+4), u(feed.CONTROL+8)) != (1, manager, count):
                raise ValueError('Beam struggle hit damage needs the kill-feed attribution service')
            for ra in feed.ATTRIBUTION:
                if ram[ra-16:ra] != read(ra-16, 16) or u(ra-8) != u32(CALL(DAMAGE)):
                    raise ValueError(f'Attributed damage call site changed {ra-8:X}')
        if mask & G_HITS:
            body = beam.contact_code()
            if ram[beam.CONTACT:beam.CONTACT+len(body)] != body: raise ValueError('Beam clash contact program changed')
        for site, data in hook_originals(mask, read):
            if ram[site:site+len(data)] != data: raise ValueError(f'Beam struggle hook site changed {site:08X}')
        code = programs(consts, beam.contact_code()[:8])
        # Frame-start R3 for human assisters: spliced into team_participation's plain FRAME chain while the assist
        # is on (an unknown chain keeps the struggle-tick fallback, which reads R3 after earlier fighters updated).
        frame_prev = frame_predecessor(ram) if s['beam_assist_enabled'] else None
        patches = code + [(CONTROL, control_bytes(manager, count, battle, consts, s, mask, frame_prev or 0)),
                          (TEXT, text_bytes(s))]
        patches += hook_patches(mask)
        if frame_prev:
            patches += [(FRAMESTUB, frame_stub(frame_prev)), (splice_site(), CALL(FRAMESTUB))]
        if mask & G_CAPTION:
            patches += hud_patch(ram)
    spans = sorted((p, p+len(d)) for p, d in patches)
    if any(e > q for (_, e), (q, _) in zip(spans, spans[1:])): raise ValueError('Beam struggle patches overlap')
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex())
              for p, d in patches if ram[p:p+len(d)] != d]
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL, blocks=blocks, groups=mask,
                group_names=[name for bit, name in GROUP_NAMES.items() if mask & bit],
                telemetry={k: CONTROL+v for k, v in TELEMETRY.items()},
                notes=['Beam struggle options: length, early win, CPU strength, hits on struggling fighters, '
                       'team assists (R3, up to four per side) and the beam clash camera; installed groups only '
                       'while their option is on.'])
