"""Opt-in help for outnumbered fighters ('Outnumbered' settings page), installed offline as guest code.

A fighter is helped in a live battle update when it is alive and present, on the side with fewer living fighters
(Team Battle and Co-op) or, with the scope 'Smaller team or 2+ attackers', targeted by at least two living enemies
(core.TABLE, every mode including Free-for-all), and - with 'Players only' - human (actor+0x1278 == 0).

Four effects, all derived each battle update from one published record (CONTROL + ROWS):
- damage: the smaller living side deals more and takes less, scaled by the size difference
  (kill-feed attributed attacker; unknown attackers apply only the defender side's reduction); never in
  Free-for-all or with equal sides; teammates, self damage and flags bit0 (recoil, costs) are never scaled;
- recovery: native recovery clocks (down age, knockback flight counter, reaction animation frame) advance by an
  extra share of the progress the game itself made since the last update (frozen clocks get nothing);
- get-up protection: entering a get-up/air recovery while helped sets the native armor timer (actor+0xE18: ordinary
  hits do not stagger) and zeroes ordinary damage outside paired scenes; Blast 2 hits (super ki blasts 0x800000,
  rush supers 0x1000000, ultimates 0x2000000), rushes and throws still hurt;
- combo breaker: the native combo hit counter (actor+0xD44) reaching N grants the same protection for 1 s, ends a
  knockback flight, then waits a cooldown; it waits while a paired action (rush, throw, paired super) runs.
Hooks: the kill-feed native-damage slot (feed.DAMAGE_NATIVE) and the once-per-update deferred damage call
(feed.TICK_CALL, native 1C2E30), both existing mod words. No native byte changes. Preset Off (the default) and a
neutral Custom preset install nothing.
"""
from native_map import A, ACTOR_HZ, CRC, SERIAL, elf_path
import math
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import battle_mode_policy as policy
import team_participation as part
import team_start_gate as start
import guest_killfeed as feed
import cpu_retaliation as retaliation
import mod_settings

BASE, END = 0x06964000, 0x0696C000
GATE, CENSUS, RECOVER, TICK, DAMAGE, TAIL = BASE, BASE+0x400, BASE+0x1000, BASE+0x2800, BASE+0x3000, BASE+0x3800
CONTROL, ROWS, SETS = BASE+0x7000, BASE+0x7100, BASE+0x7800
MAGIC, VERSION, STRIDE = 0x4F555431, 1, 64          # 'OUT1'
# CONTROL fields (byte offsets). 28..71 is the configuration (config()); 128..175 are telemetry counters.
C = dict(magic=0, manager=4, count=8, mode=12, version=16, tick_previous=20, damage_previous=24, flags=28,
         bonus=32, reduction=36, k100=40, kfloat=44, protect=48, breaker=52, break_protect=56, cooldown=60,
         cap=64, floor=68, live=72, clock=76, weight0=80, weight1=84, small=88, dealt=92, taken=96, helped=100,
         updates=128, helped_updates=132, extra_age=136, extra_flight=140, extra_anim=144, protections=148,
         breakers=152, scaled=156, zeroed=160, passthrough=164, scaled_before=168, scaled_after=172)
# ROWS fields, one 64-byte row per physical fighter (byte offsets).
R = dict(actor=0, action=4, age=8, flight=12, frame=16, model=20, acc=24, protect_until=28, cooldown_until=32,
         dealt=36, taken=40, helped=44)
F_DAMAGE, F_GANGED, F_HUMANS = 1, 2, 4
SET_GETUP, SET_FLIGHT, SET_ANIM, SET_PAIRED = 0, 64, 128, 192    # 40-byte action bitmaps (actions 0..319)
GETUP = tuple(range(225, 231))
DOWN = 216
FLIGHT = (213, 214, 223)
ANIMATED = (189,) + tuple(range(192, 211)) + (212, 215) + GETUP
PAIRED = tuple(range(183, 188)) + tuple(range(301, 316))
ULTIMATE_FLAG = 0x2000000
BLAST_FLAGS = 0x3800000          # 0x800000 super ki blast, 0x1000000 rush super, 0x2000000 ultimate (live, p40 run 161137)
DEALT_CAP, TAKEN_FLOOR = 300, 40
BREAK_SECONDS, COOLDOWN_SECONDS, MAX_STEP = 1.0, 5.0, 4
PROTECT_MAX_SECONDS = 3
PRESETS = {
    'balanced': dict(bonus=15, reduction=10, recovery=150, protection=0.5, breaker=12),
    'strong': dict(bonus=40, reduction=30, recovery=200, protection=1.0, breaker=8),
}
KEYS = dict(bonus='outnumbered_damage_bonus_percent', reduction='outnumbered_damage_reduction_percent',
            recovery='outnumbered_recovery_speed_percent', protection='outnumbered_getup_protection_seconds',
            breaker='outnumbered_combo_breaker_hits', scope='outnumbered_scope', applies='outnumbered_applies_to')
PRESET_KEY = 'outnumbered_preset'
# Every key of the Outnumbered settings page, in display order.
SETTING_KEYS = (PRESET_KEY, KEYS['scope'], KEYS['applies'], KEYS['bonus'], KEYS['reduction'], KEYS['recovery'],
                KEYS['protection'], KEYS['breaker'])
NATIVE = elf_reader(elf_path(ROOT))[2]


def jump(p, link=False):
    """j/jal p followed by a nop (8 bytes)."""
    return struct.pack('<2I', ((3 if link else 2) << 26) | (p >> 2), 0)


def resolved(settings):
    """Effective values (bonus, reduction, recovery, protection, breaker, scope, applies) for validated settings,
    or None when nothing would change (nothing is installed). The two who-rows apply to every preset."""
    s = settings
    preset = s.get(PRESET_KEY, 'off')
    if preset == 'off': return None
    v = dict(PRESETS[preset]) if preset in PRESETS else {k: s[KEYS[k]] for k in PRESETS['balanced']}
    v.update(scope=s.get(KEYS['scope'], 'also_ganged_up'), applies=s.get(KEYS['applies'], 'everyone'))
    if not (v['bonus'] or v['reduction'] or v['recovery'] > 100 or v['protection'] > 0 or v['breaker']):
        return None
    return v


def side_percents(weights, bonus, reduction, mode=policy.TEAMS):
    """(small side or -1, dealt %, taken %) exactly as CENSUS computes them from the two living side weights."""
    w0, w1 = weights
    if mode == policy.FFA or w0 == w1 or not w0 or not w1: return -1, 100, 100
    small = 0 if w0 < w1 else 1
    S, L = (w0, w1) if small == 0 else (w1, w0)
    return small, min(DEALT_CAP, 100 + bonus*(L-S)//S), max(TAKEN_FLOOR, 100 - reduction*(L-S)//S)


def fop(a, fn, d, s, t=0):
    """COP1 single-precision op fn: fd=d, fs=s, ft=t."""
    a.emit((17 << 26) | (16 << 21) | (t << 16) | (s << 11) | (d << 6) | fn)


def bit(a, reg, table, out, fail):
    """out = bit reg of the 320-bit action set at SETS+table; branch to fail when clear. t8/t9 scratch."""
    a.i(11, 24, reg, 320); a.branch(4, 24, 0, fail)
    a.r(2, 24, 0, reg, 3); a.li(25, SETS+table); a.r(0x21, 24, 24, 25); a.i(36, out, 24, 0)
    a.i(12, 24, reg, 7); a.r(6, out, 24, out); a.i(12, out, out, 1); a.branch(4, out, 0, fail)


def gate_code():
    """Leaf, t0..t3: v0=1 inside a live captured battle update (the teammate_revive predicate); t2 = count."""
    a = Assembler(GATE); core.gate(a, 'no')
    a.li(8, CONTROL); a.lw(9, 8); a.li(11, MAGIC); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'no')
    a.li(8, core.PAIR+4); a.lw(9, 8); a.branch(5, 9, 0, 'no')
    a.li(8, part.CONTROL); a.lw(9, 8); a.addiu(11, 0, 5); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'no'); a.lw(9, 8, 8); a.branch(5, 9, 10, 'no')
    a.li(8, start.CONTROL); a.lw(9, 8); a.branch(5, 9, 0, 'no')
    a.li(8, A(0x3337B8)); a.lw(9, 8); a.i(12, 9, 9, 0x3900); a.branch(5, 9, 0, 'no')
    a.li(8, A(0x3337C0)); a.lw(9, 8); a.addiu(11, 0, 1); a.branch(5, 9, 11, 'no')
    a.lw(9, 28, -22364); a.lw(9, 9, 628); a.branch(5, 9, 0, 'no')
    a.addiu(2, 0, 1); a.jr(); a.label('no'); a.move(2, 0); a.jr()
    data = a.finish(); assert len(data) <= CENSUS-GATE; return data


SAVED = tuple(range(16, 24)) + (31,)


def frame(a, size=0x60):
    """Allocate a 16-byte aligned frame and save s0..s7 and ra."""
    assert size % 16 == 0
    a.addiu(29, 29, -size)
    for i, r in enumerate(SAVED): a.i(63, r, 29, i*8)


def unframe(a, size=0x60):
    """Restore s0..s7 and ra, release the frame and return."""
    for i, r in enumerate(SAVED): a.i(55, r, 29, i*8)
    a.addiu(29, 29, size); a.jr()


def census_code():
    """Once per battle update: the clock, both living side weights, the small side's percents and every row's
    helped flag and percents. Outside a live update the record is reset to neutral (nothing helped, 100%)."""
    a = Assembler(CENSUS); frame(a)
    a.call(GATE); a.li(16, CONTROL); a.branch(4, 2, 0, 'inactive')
    a.lw(17, 16, C['count'])
    a.lw(8, 16, C['clock']); a.addiu(8, 8, 1); a.sw(8, 16, C['clock'])
    a.lw(8, 16, C['updates']); a.addiu(8, 8, 1); a.sw(8, 16, C['updates'])
    a.addiu(8, 0, 1); a.sw(8, 16, C['live'])
    # weights: living, non-removed fighters per side (s3 side 0, s4 side 1, s5 alive mask)
    a.move(18, 0); a.move(19, 0); a.move(20, 0); a.move(21, 0)
    a.label('weigh')
    a.li(8, part.CONTROL); a.lw(9, 8, 20); a.r(6, 9, 18, 9); a.i(12, 9, 9, 1); a.branch(5, 9, 0, 'weigh_next')
    a.li(8, core.POINTERS); a.r(0, 9, 0, 18, 2); a.r(0x21, 8, 8, 9); a.lw(4, 8); a.branch(4, 4, 0, 'weigh_next')
    a.call(feed.ROW); a.branch(4, 2, 0, 'weigh_next'); a.lw(8, 2); a.branch(6, 8, 0, 'weigh_next')
    a.addiu(8, 0, 1); a.r(4, 8, 18, 8); a.r(0x25, 21, 21, 8)
    a.i(12, 8, 18, 1); a.branch(5, 8, 0, 'side1'); a.addiu(19, 19, 1); a.jump('weigh_next')
    a.label('side1'); a.addiu(20, 20, 1)
    a.label('weigh_next'); a.addiu(18, 18, 1); a.branch(5, 18, 17, 'weigh')
    # a consumed fusion partner still counts for its side while that side has a living fighter
    a.li(8, part.CONTROL); a.lw(9, 8, 16); a.move(18, 0)
    a.label('consumed'); a.r(6, 10, 18, 9); a.i(12, 10, 10, 1); a.branch(4, 10, 0, 'consumed_next')
    a.i(12, 10, 18, 1); a.branch(5, 10, 0, 'consumed1')
    a.branch(6, 19, 0, 'consumed_next'); a.addiu(19, 19, 1); a.jump('consumed_next')
    a.label('consumed1'); a.branch(6, 20, 0, 'consumed_next'); a.addiu(20, 20, 1)
    a.label('consumed_next'); a.addiu(18, 18, 1); a.branch(5, 18, 17, 'consumed')
    a.sw(19, 16, C['weight0']); a.sw(20, 16, C['weight1'])
    # small side and its percents (s6 small or -1, s7 dealt, t-reg taken stored directly)
    a.addiu(22, 0, -1); a.addiu(23, 0, 100); a.sw(23, 16, C['taken'])
    a.lw(8, 16, C['mode']); a.addiu(9, 0, policy.FFA); a.branch(4, 8, 9, 'percents')
    a.branch(4, 19, 20, 'percents'); a.branch(6, 19, 0, 'percents'); a.branch(6, 20, 0, 'percents')
    a.r(0x2A, 8, 19, 20); a.move(22, 0); a.move(10, 19); a.move(11, 20); a.branch(5, 8, 0, 'sized')
    a.addiu(22, 0, 1); a.move(10, 20); a.move(11, 19)
    a.label('sized'); a.lw(8, 16, C['flags']); a.i(12, 8, 8, F_DAMAGE); a.branch(4, 8, 0, 'percents')
    a.r(0x23, 12, 11, 10)                                          # t4 = L - S
    a.lw(8, 16, C['bonus']); a.r(24, 0, 8, 12); a.r(18, 8, 0); a.r(27, 0, 8, 10); a.r(18, 8, 0)
    a.addiu(23, 8, 100); a.lw(8, 16, C['cap']); a.r(0x2A, 9, 8, 23); a.branch(4, 9, 0, 'dealt_ok'); a.move(23, 8)
    a.label('dealt_ok')
    a.lw(8, 16, C['reduction']); a.r(24, 0, 8, 12); a.r(18, 8, 0); a.r(27, 0, 8, 10); a.r(18, 8, 0)
    a.addiu(9, 0, 100); a.r(0x23, 9, 9, 8); a.lw(8, 16, C['floor']); a.r(0x2A, 13, 9, 8); a.branch(4, 13, 0, 'taken_ok')
    a.move(9, 8)
    a.label('taken_ok'); a.sw(9, 16, C['taken'])
    a.label('percents'); a.sw(22, 16, C['small']); a.sw(23, 16, C['dealt'])
    # per-fighter record: helped flag and the percents its damage uses
    a.move(18, 0); a.li(19, ROWS); a.move(20, 0)
    a.label('row')
    a.addiu(8, 0, 100); a.sw(8, 19, R['dealt']); a.sw(8, 19, R['taken']); a.sw(0, 19, R['helped'])
    a.r(6, 8, 18, 21); a.i(12, 8, 8, 1); a.branch(4, 8, 0, 'row_next')
    a.move(13, 0); a.branch(1, 22, 0, 'ganged')                    # t5 = on the small side
    a.i(12, 8, 18, 1); a.branch(5, 8, 22, 'ganged'); a.addiu(13, 0, 1); a.jump('human')
    a.label('ganged'); a.lw(8, 16, C['flags']); a.i(12, 8, 8, F_GANGED); a.branch(4, 8, 0, 'row_next')
    a.move(14, 0); a.move(15, 0)                                   # t6 attackers, t7 j
    a.label('attacker'); a.branch(4, 15, 18, 'attacker_next')
    a.r(6, 8, 15, 21); a.i(12, 8, 8, 1); a.branch(4, 8, 0, 'attacker_next')
    policy.emit_enemy(a, 15, 18, 'attacker_next', 'out_enemy')
    a.li(8, core.TABLE); a.r(0, 9, 0, 15, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.branch(5, 8, 18, 'attacker_next')
    a.addiu(14, 14, 1)
    a.label('attacker_next'); a.addiu(15, 15, 1); a.branch(5, 15, 17, 'attacker')
    a.i(10, 8, 14, 2); a.branch(5, 8, 0, 'row_next')
    a.label('human'); a.lw(8, 16, C['flags']); a.i(12, 8, 8, F_HUMANS); a.branch(4, 8, 0, 'help')
    a.li(8, core.POINTERS); a.r(0, 9, 0, 18, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8)
    a.lw(8, 8, 0x1278); a.branch(5, 8, 0, 'row_next')
    a.label('help'); a.addiu(8, 0, 1); a.sw(8, 19, R['helped']); a.r(4, 8, 18, 8); a.r(0x25, 20, 20, 8)
    a.branch(4, 13, 0, 'row_next'); a.sw(23, 19, R['dealt']); a.lw(8, 16, C['taken']); a.sw(8, 19, R['taken'])
    a.label('row_next'); a.addiu(18, 18, 1); a.addiu(19, 19, STRIDE); a.branch(5, 18, 17, 'row')
    a.sw(20, 16, C['helped']); a.branch(4, 20, 0, 'done')
    a.lw(8, 16, C['helped_updates']); a.addiu(8, 8, 1); a.sw(8, 16, C['helped_updates']); a.jump('done')
    a.label('inactive'); a.sw(0, 16, C['live']); a.sw(0, 16, C['helped']); a.li(19, ROWS)
    for i in range(policy.ENGINE_ACTORS):
        a.addiu(8, 0, 100); a.sw(8, 19, i*STRIDE+R['dealt']); a.sw(8, 19, i*STRIDE+R['taken'])
        a.sw(0, 19, i*STRIDE+R['helped']); a.addiu(8, 0, -1); a.sw(8, 19, i*STRIDE+R['action'])
    a.label('done'); unframe(a)
    data = a.finish(); assert len(data) <= RECOVER-CENSUS, hex(len(data)); return data


def protect(a, ticks_off, tag):
    """s4 actor, s3 row, s0 CONTROL: protect for CONTROL[ticks_off] updates. t0..t3."""
    a.lw(10, 16, ticks_off); a.lw(8, 16, C['clock']); a.r(0x21, 8, 8, 10)
    a.lw(9, 19, R['protect_until']); a.r(0x2B, 11, 9, 8); a.branch(4, 11, 0, tag+'_until'); a.sw(8, 19, R['protect_until'])
    a.label(tag+'_until'); a.lw(9, 20, 0xE18); a.r(0x2A, 11, 9, 10); a.branch(4, 11, 0, tag+'_armor'); a.sw(10, 20, 0xE18)
    a.label(tag+'_armor'); a.lw(8, 16, C['protections']); a.addiu(8, 8, 1); a.sw(8, 16, C['protections'])


def accumulate(a, delta):
    """t0 = whole extra ticks for `delta` native ticks; carries the remainder in the row. t0..t3."""
    a.lw(9, 16, C['k100']); a.r(24, 0, delta, 9); a.r(18, 8, 0); a.lw(9, 19, R['acc']); a.r(0x21, 8, 8, 9)
    a.addiu(9, 0, 100); a.r(27, 0, 8, 9); a.r(18, 8, 0); a.r(16, 9, 0); a.sw(9, 19, R['acc'])


def recover_code():
    """Once per battle update after CENSUS, for every helped fighter: get-up protection on the first update of a
    get-up, the combo breaker (never inside a paired action), then recovery acceleration that mirrors the native
    progress made since the previous update (same action, same body, no pending request, at most MAX_STEP)."""
    a = Assembler(RECOVER); frame(a, 0x70)
    for i in range(4): a.i(57, i, 29, 0x50+4*i)
    a.li(16, CONTROL); a.lw(8, 16, C['live']); a.branch(4, 8, 0, 'done')
    a.lw(17, 16, C['count']); a.move(18, 0); a.li(19, ROWS)
    a.label('actor')
    a.lw(20, 19, R['actor']); a.li(8, core.POINTERS); a.r(0, 9, 0, 18, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8)
    a.branch(5, 8, 20, 'next'); a.branch(4, 20, 0, 'next')
    a.lw(21, 20, 0x948)
    a.lw(8, 20, 12); a.i(11, 9, 8, policy.ENGINE_ACTORS); a.branch(4, 9, 0, 'next')
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(22, 8)
    a.i(12, 9, 22, 3); a.branch(5, 9, 0, 'next'); a.li(9, 0x100000); a.r(0x2B, 9, 22, 9); a.branch(5, 9, 0, 'next')
    a.li(9, 0x08000000-0x1670); a.r(0x2B, 9, 22, 9); a.branch(4, 9, 0, 'next')
    a.lw(8, 19, R['helped']); a.branch(4, 8, 0, 'rebase')
    # get-up protection: first update of a get-up / air recovery
    a.lw(8, 16, C['protect']); a.branch(6, 8, 0, 'breaker')
    bit(a, 21, SET_GETUP, 8, 'breaker'); a.lw(10, 19, R['action'])
    a.addiu(9, 10, -225); a.i(11, 9, 9, len(GETUP)); a.branch(5, 9, 0, 'breaker')
    protect(a, C['protect'], 'getup')
    # combo breaker
    a.label('breaker'); a.lw(10, 16, C['breaker']); a.branch(6, 10, 0, 'accelerate')
    a.lw(8, 16, C['clock']); a.lw(9, 19, R['cooldown_until']); a.r(0x2B, 11, 8, 9); a.branch(5, 11, 0, 'accelerate')
    a.lw(9, 20, 0xD44); a.r(0x2A, 11, 9, 10); a.branch(5, 11, 0, 'accelerate')
    bit(a, 21, SET_PAIRED, 8, 'unpaired'); a.jump('accelerate'); a.label('unpaired')
    protect(a, C['break_protect'], 'break')
    a.lw(8, 16, C['clock']); a.lw(9, 16, C['cooldown']); a.r(0x21, 8, 8, 9); a.sw(8, 19, R['cooldown_until'])
    a.lw(8, 16, C['breakers']); a.addiu(8, 8, 1); a.sw(8, 16, C['breakers'])
    bit(a, 21, SET_FLIGHT, 8, 'accelerate'); a.lw(8, 20, 0x3D8); a.i(10, 9, 8, 2); a.branch(5, 9, 0, 'accelerate')
    a.addiu(8, 0, 1); a.sw(8, 20, 0x3D8)
    # acceleration mirrors native progress made since the previous update, same action and body only
    a.label('accelerate'); a.lw(8, 16, C['k100']); a.branch(6, 8, 0, 'rebase')
    a.lw(8, 20, 0x94C); a.addiu(9, 0, -1); a.branch(5, 8, 9, 'rebase')
    a.lw(8, 19, R['action']); a.branch(5, 8, 21, 'rebase'); a.lw(8, 19, R['model']); a.branch(5, 8, 22, 'rebase')
    a.addiu(8, 0, DOWN); a.branch(5, 21, 8, 'flight')
    a.lw(12, 20, 0x964); a.lw(9, 19, R['age']); a.r(0x23, 13, 12, 9); a.branch(6, 13, 0, 'rebase')
    a.i(11, 9, 13, MAX_STEP+1); a.branch(4, 9, 0, 'rebase')
    accumulate(a, 13); a.r(0x21, 12, 12, 8); a.sw(12, 20, 0x964)
    a.lw(9, 16, C['extra_age']); a.r(0x21, 9, 9, 8); a.sw(9, 16, C['extra_age']); a.jump('rebase')
    a.label('flight'); bit(a, 21, SET_FLIGHT, 8, 'animated')
    a.lw(12, 20, 0x3D8); a.lw(9, 19, R['flight']); a.r(0x23, 13, 9, 12); a.branch(6, 13, 0, 'rebase')
    a.i(11, 9, 13, MAX_STEP+1); a.branch(4, 9, 0, 'rebase')
    accumulate(a, 13); a.r(0x23, 9, 12, 8); a.branch(6, 9, 0, 'rebase'); a.sw(9, 20, 0x3D8)
    a.lw(9, 16, C['extra_flight']); a.r(0x21, 9, 9, 8); a.sw(9, 16, C['extra_flight']); a.jump('rebase')
    a.label('animated'); bit(a, 21, SET_ANIM, 8, 'rebase')
    a.i(49, 0, 22, 0xC78); a.i(49, 1, 19, R['frame']); fop(a, 1, 2, 0, 1)        # f2 = frame - last
    a.i(49, 1, 22, 0xC80); a.emit((17 << 26) | (4 << 21) | (0 << 16) | (3 << 11))  # f1 rate, f3 = 0
    fop(a, 0x34, 0, 3, 1); a.branch(17, 8, 0, 'rebase')                           # 0 < rate
    fop(a, 0x34, 0, 3, 2); a.branch(17, 8, 0, 'rebase')                           # 0 < delta
    a.li(8, 0x40800000); a.emit((17 << 26) | (4 << 21) | (8 << 16) | (3 << 11)); fop(a, 2, 3, 3, 1)
    fop(a, 0x36, 0, 2, 3); a.branch(17, 8, 0, 'rebase')                           # delta <= 4 * rate
    a.i(49, 3, 16, C['kfloat']); fop(a, 2, 2, 2, 3); fop(a, 0, 0, 0, 2); a.i(57, 0, 22, 0xC78)
    a.lw(9, 16, C['extra_anim']); a.addiu(9, 9, 1); a.sw(9, 16, C['extra_anim'])
    a.label('rebase')
    a.sw(21, 19, R['action']); a.lw(8, 20, 0x964); a.sw(8, 19, R['age']); a.lw(8, 20, 0x3D8); a.sw(8, 19, R['flight'])
    a.lw(8, 22, 0xC78); a.sw(8, 19, R['frame']); a.sw(22, 19, R['model'])
    a.label('next'); a.addiu(18, 18, 1); a.addiu(19, 19, STRIDE); a.branch(5, 18, 17, 'actor')
    a.label('done')
    for i in range(4): a.i(49, i, 29, 0x50+4*i)
    unframe(a, 0x70)
    data = a.finish(); assert len(data) <= TICK-RECOVER, hex(len(data)); return data


def tick_code():
    """At feed.TICK_CALL (once per battle update, not while paused): the previous target (cpu_retaliation.TICK or
    feed.TICK, CONTROL+20) first with the native registers, its v0 kept, then CENSUS and RECOVER."""
    a = Assembler(TICK); a.addiu(29, 29, -0x100); feed.save(a); a.i(63, 31, 29, 0xE8)
    feed.restore(a); a.li(25, CONTROL); a.lw(25, 25, C['tick_previous']); a.r(9, 31, 25); a.emit(0)
    feed.save(a); a.call(CENSUS); a.call(RECOVER)
    feed.restore(a); a.i(55, 31, 29, 0xE8); a.addiu(29, 29, 0x100); a.jr()
    data = a.finish(); assert len(data) <= DAMAGE-TICK; return data


def damage_code():
    """At feed.DAMAGE_NATIVE: a0 defender, a1 damage, a2 flags; sp/ra are the kill feed's own.
    Only t0..t7 and a1 change (v0 = 0 on the blocked exit); sp and ra are untouched on every exit."""
    a = Assembler(DAMAGE)
    a.li(8, retaliation.feed_return()); a.branch(5, 31, 8, 'pass')        # the kill feed's own native call
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'pass')
    a.lw(9, 8, C['live']); a.branch(4, 9, 0, 'pass')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'pass')
    a.i(12, 9, 6, 1); a.branch(5, 9, 0, 'pass'); a.branch(6, 5, 0, 'pass')
    a.lw(11, 29, 0xF0); a.lw(9, 8, C['count']); a.r(0x2B, 10, 11, 9); a.branch(4, 10, 0, 'pass')
    a.r(0, 12, 0, 11, 6); a.li(9, ROWS); a.r(0x21, 12, 12, 9)              # t4 victim row
    a.lw(9, 12, R['actor']); a.branch(5, 9, 4, 'pass')
    # protection: inside the window, armor still on, not a Blast 2 hit, not a paired/throw scene
    a.lw(9, 12, R['protect_until']); a.lw(10, 8, C['clock']); a.r(0x2B, 13, 10, 9); a.branch(4, 13, 0, 'scale')
    a.lw(9, 4, 0xE18); a.branch(6, 9, 0, 'scale')
    a.li(9, BLAST_FLAGS); a.r(0x24, 9, 6, 9); a.branch(5, 9, 0, 'scale')
    a.lw(9, 4, 0x948); a.i(11, 10, 9, 320); a.branch(4, 10, 0, 'blocked')
    a.r(2, 10, 0, 9, 3); a.li(13, SETS+SET_PAIRED); a.r(0x21, 10, 10, 13); a.i(36, 10, 10, 0)
    a.i(12, 13, 9, 7); a.r(6, 10, 13, 10); a.i(12, 10, 10, 1); a.branch(5, 10, 0, 'scale')
    a.label('blocked'); a.lw(9, 8, C['zeroed']); a.addiu(9, 9, 1); a.sw(9, 8, C['zeroed'])
    a.move(2, 0); a.jr()
    # scaling: victim side's 'taken', times the attacker's 'dealt' for a cross-team attributed hit
    a.label('scale'); a.lw(13, 12, R['taken'])
    a.lw(14, 29, 0xF4); a.branch(1, 14, 0, 'percent')                     # unknown attacker (-1)
    a.lw(9, 8, C['count']); a.r(0x2B, 10, 14, 9); a.branch(4, 10, 0, 'pass')
    a.branch(4, 14, 11, 'pass'); a.r(0x26, 9, 14, 11); a.i(12, 9, 9, 1); a.branch(4, 9, 0, 'pass')
    a.lw(9, 8, C['mode']); a.addiu(10, 0, policy.FFA); a.branch(4, 9, 10, 'pass')
    a.r(0, 9, 0, 14, 6); a.li(10, ROWS); a.r(0x21, 9, 9, 10); a.lw(9, 9, R['dealt'])
    a.r(24, 0, 13, 9); a.r(18, 13, 0); a.addiu(9, 0, 100); a.r(27, 0, 13, 9); a.r(18, 13, 0)
    a.label('percent'); a.addiu(9, 0, 100); a.branch(4, 13, 9, 'pass')
    a.li(9, 1000000); a.r(0x2B, 10, 5, 9); a.branch(5, 10, 0, 'bounded'); a.move(5, 9)
    a.label('bounded'); a.move(15, 5); a.r(24, 0, 5, 13); a.r(18, 5, 0); a.addiu(9, 0, 100); a.r(27, 0, 5, 9)
    a.r(18, 5, 0); a.branch(5, 5, 0, 'nonzero'); a.addiu(5, 0, 1)
    a.label('nonzero'); a.lw(9, 8, C['scaled']); a.addiu(9, 9, 1); a.sw(9, 8, C['scaled'])
    a.lw(9, 8, C['scaled_before']); a.r(0x21, 9, 9, 15); a.sw(9, 8, C['scaled_before'])
    a.lw(9, 8, C['scaled_after']); a.r(0x21, 9, 9, 5); a.sw(9, 8, C['scaled_after'])
    a.label('pass'); a.jump(TAIL)
    data = a.finish(); assert len(data) <= TAIL-DAMAGE; return data


def sets():
    """The four 64-byte action bitmaps (bits 0..319): GETUP, FLIGHT, ANIMATED and PAIRED."""
    data = bytearray(256)
    for table, actions in ((SET_GETUP, GETUP), (SET_FLIGHT, FLIGHT), (SET_ANIM, ANIMATED), (SET_PAIRED, PAIRED)):
        for action in actions: data[table + action//8] |= 1 << (action & 7)
    return bytes(data)


def tail_variants():
    """The 8-byte kill-feed native-damage continuations an install accepts: the native pair (no retaliation) and
    beta.36's 'j cpu_retaliation.CODE; nop'."""
    return (NATIVE(feed.DAMAGE_ENTRY, 8), jump(retaliation.CODE))


def program(tail):
    """Code pages and SETS for an install whose kill-feed continuation is `tail` (16 bytes at TAIL)."""
    return [(GATE, gate_code()), (CENSUS, census_code()), (RECOVER, recover_code()), (TICK, tick_code()),
            (DAMAGE, damage_code()), (TAIL, tail), (SETS, sets())]


def config(v, mode=None):
    """CONTROL+28..+71: flags, bonus, reduction, k100, kfloat, protect, breaker, break_protect, cooldown, cap, floor."""
    k100 = v['recovery'] - 100
    flags = (F_DAMAGE if v['bonus'] or v['reduction'] else 0) | (F_GANGED if v['scope'] == 'also_ganged_up' else 0) \
        | (F_HUMANS if v['applies'] == 'humans' else 0)
    protect_ticks = math.ceil(v['protection']*ACTOR_HZ) if v['protection'] > 0 else 0
    return struct.pack('<4If6I', flags, v['bonus'], v['reduction'], k100, k100/100, protect_ticks, v['breaker'],
                       math.ceil(BREAK_SECONDS*ACTOR_HZ), math.ceil(COOLDOWN_SECONDS*ACTOR_HZ), DEALT_CAP, TAKEN_FLOOR)


INERT = dict(bonus=0, reduction=0, recovery=100, protection=0, breaker=0, scope='smaller_team', applies='everyone')


def _validate(ram):
    """validate_memory in the caller's build context (build_memory already runs inside it)."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if u(CONTROL) != MAGIC: raise ValueError('Outnumbered identity missing')
    if u(CONTROL+C['version']) != VERSION: raise ValueError('Outnumbered version unknown; prepare a new match')
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if (u(CONTROL+4), u(CONTROL+8)) != (manager, count) or count not in policy.ACTOR_COUNTS:
        raise ValueError('Outnumbered capture identity mismatch')
    if u(CONTROL+C['mode']) not in (policy.TEAMS, policy.FFA, policy.COOP): raise ValueError('Outnumbered mode unknown')
    f = {k: u(CONTROL+C[k]) for k in ('flags', 'bonus', 'reduction', 'k100', 'protect', 'breaker', 'break_protect',
                                        'cooldown', 'cap', 'floor')}
    if (f['flags'] >= 8 or f['bonus'] > 100 or f['reduction'] > 60 or f['k100'] > 200
            or ram[CONTROL+C['kfloat']:CONTROL+C['kfloat']+4] != struct.pack('<f', f['k100']/100)
            or f['protect'] > math.ceil(PROTECT_MAX_SECONDS*ACTOR_HZ) or f['breaker'] > 30
            or f['break_protect'] != math.ceil(BREAK_SECONDS*ACTOR_HZ) or f['cooldown'] != math.ceil(COOLDOWN_SECONDS*ACTOR_HZ)
            or (f['cap'], f['floor']) != (DEALT_CAP, TAKEN_FLOOR)):
        raise ValueError('Invalid outnumbered configuration')
    previous = u(CONTROL+C['tick_previous'])
    if previous not in (feed.TICK, retaliation.TICK) or u(CONTROL+C['damage_previous']) != TAIL:
        raise ValueError('Unknown outnumbered continuation')
    first = bytes(ram[TAIL:TAIL+8])
    if first not in tail_variants(): raise ValueError('Unknown outnumbered damage continuation')
    for p, b in program(first + jump(feed.DAMAGE_NATIVE+8)):
        if ram[p:p+len(b)] != b: raise ValueError(f'Outnumbered executable changed {p:08X}')
    if ram[feed.DAMAGE_NATIVE:feed.DAMAGE_NATIVE+8] != jump(DAMAGE) or u(feed.TICK_CALL) != (3 << 26) | (TICK >> 2):
        raise ValueError('Outnumbered hook changed')
    for i in range(count):
        if u(ROWS+i*STRIDE) != u(core.POINTERS+4*i): raise ValueError('Outnumbered actor pointer changed')
    return previous, struct.unpack_from('<I', first)[0]


@policy.matching_install
def validate_memory(ram):
    """Strict check of an installed copy: identity, configuration ranges, program bytes for the recorded TAIL
    variant, SETS, both hook words and the row actors. Returns (tick_previous, first word of the TAIL variant)."""
    return _validate(ram)


def _unavailable(reason):
    return dict(blocks=[], status='OUTNUMBERED UNAVAILABLE: ' + reason)


@policy.matching_install
def build_memory(ram, settings=None, source='<prepared>'):
    """Install (or reconfigure) the outnumbered help for a captured active match.

    Off and neutral Custom install nothing. A fresh install needs this build's kill feed (its DAMAGE bytes and
    capture identity), current team participation, and a known kill-feed damage continuation and per-update call;
    otherwise nothing is installed and the status says why ('OUTNUMBERED UNAVAILABLE: ...'). An installed copy is
    validated and only its configuration words are rewritten (Off writes the inert configuration)."""
    v = resolved(mod_settings.validate_settings(settings or {}))
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    installed = len(ram) == 0x8000000 and u(CONTROL) == MAGIC
    if v is None and not installed: return dict(blocks=[], status='OUTNUMBERED OFF')
    if len(ram) != 0x8000000: raise ValueError('Outnumbered help requires original 128MiB BT3 RAM')
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if count not in policy.ACTOR_COUNTS or (u(core.MODE), u(core.MODE+8), u(core.MODE+12)) != (1, manager, count):
        raise ValueError('Outnumbered help requires a captured active match')
    mode = u(policy.CONTROL+12) if u(policy.CONTROL) == policy.MAGIC else policy.TEAMS
    cfg = config(v or INERT, mode)
    if installed:
        _validate(ram)
        old = ram[CONTROL+C['flags']:CONTROL+C['flags']+len(cfg)]
        blocks = [] if old == cfg else [(CONTROL+C['flags'], cfg)]
    else:
        if any(ram[BASE:END]): raise ValueError('Outnumbered reservation occupied')
        if ram[feed.DAMAGE:feed.DAMAGE+len(feed.damage_code())] != feed.damage_code():
            return _unavailable('this checkpoint has an older kill feed')
        if (u(feed.CONTROL), u(feed.CONTROL+4), u(feed.CONTROL+8)) != (1, manager, count):
            return _unavailable('the kill feed belongs to another capture')
        if (u(part.CONTROL+4), u(part.CONTROL+8)) != (manager, count):
            return _unavailable('team participation is missing')
        first = bytes(ram[feed.DAMAGE_NATIVE:feed.DAMAGE_NATIVE+8])
        if first not in tail_variants():
            return _unavailable('unknown kill-feed damage continuation')
        call = u(feed.TICK_CALL)
        if call not in ((3 << 26) | (feed.TICK >> 2), (3 << 26) | (retaliation.TICK >> 2)):
            return _unavailable('unknown per-update call')
        tail = first + jump(feed.DAMAGE_NATIVE+8)
        control = bytearray(0x100)
        struct.pack_into('<6I', control, 0, MAGIC, manager, count, mode, VERSION, (call & 0x3FFFFFF) << 2)
        struct.pack_into('<I', control, C['damage_previous'], TAIL)
        control[C['flags']:C['flags']+len(cfg)] = cfg
        rows = bytearray(policy.ENGINE_ACTORS*STRIDE)
        for i in range(policy.ENGINE_ACTORS):
            struct.pack_into('<I', rows, i*STRIDE+R['action'], 0xFFFFFFFF)
            struct.pack_into('<2I', rows, i*STRIDE+R['dealt'], 100, 100)
        for i in range(count):
            actor = u(core.POINTERS+4*i)
            if not 0x100000 <= actor < len(ram)-0x1600 or u(actor) != i: raise ValueError('Invalid outnumbered actor')
            struct.pack_into('<I', rows, i*STRIDE, actor)
        blocks = program(tail) + [(CONTROL, bytes(control)), (ROWS, bytes(rows)),
                                  (feed.DAMAGE_NATIVE, jump(DAMAGE)),
                                  (feed.TICK_CALL, struct.pack('<I', (3 << 26) | (TICK >> 2)))]
        check = bytearray(ram)
        for p, b in blocks: check[p:p+len(b)] = b
        _validate(check)
        del check
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL,
                status='OUTNUMBERED HELP' if v else 'OUTNUMBERED INERT',
                blocks=[dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex()) for p, d in blocks])


UNSIGNED = ('magic', 'manager', 'count', 'mode', 'version', 'tick_previous', 'damage_previous', 'flags', 'helped')


def telemetry(reader):
    """The CONTROL record as a dict, for any reader with read(addr, size) (a PINE client, an interpreter, a RAM view).

    Counters (CONTROL+128..+172): updates, helped_updates, extra_age/extra_flight/extra_anim (recovery granted),
    protections, breakers, scaled/zeroed hits and the damage sums before/after scaling."""
    data = bytes(reader.read(CONTROL, 0xB0))
    out = {}
    for name, offset in sorted(C.items(), key=lambda item: item[1]):
        if name == 'kfloat': out[name] = struct.unpack_from('<f', data, offset)[0]
        else: out[name] = struct.unpack_from('<I' if name in UNSIGNED else '<i', data, offset)[0]
    out['installed'] = out['magic'] == MAGIC
    return out


def row_telemetry(reader, count):
    """Per physical fighter: (helped, dealt %, taken %, protect_until, cooldown_until, action) from ROWS."""
    data = bytes(reader.read(ROWS, count*STRIDE))
    return [dict(helped=struct.unpack_from('<I', data, i*STRIDE+R['helped'])[0],
                 dealt=struct.unpack_from('<i', data, i*STRIDE+R['dealt'])[0],
                 taken=struct.unpack_from('<i', data, i*STRIDE+R['taken'])[0],
                 protect_until=struct.unpack_from('<I', data, i*STRIDE+R['protect_until'])[0],
                 cooldown_until=struct.unpack_from('<I', data, i*STRIDE+R['cooldown_until'])[0],
                 action=struct.unpack_from('<i', data, i*STRIDE+R['action'])[0]) for i in range(count)]
