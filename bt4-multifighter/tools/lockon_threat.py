"""Who is targeting you: marks for those enemies, an attack warning, and a tap that switches to your attacker.

Installed last, after lockon_select, and only when one of its two settings differs from its legacy value
(lockon_attacker_switch 'never', lockon_threat_marks 'hide'); with both legacy nothing here is installed and prepared
matches keep their beta.36 bytes.

Simulation (deterministic guest code; every write happens in the damage path or the lock-on queue):
- HITLOG takes over the retaliation accumulator's entry (cpu_retaliation ACCUMULATE, whose first word ffa_targeting or
  battle_modes points at the dynamic NPC policy) and keeps, per victim and attacker, the last hit (feed clock + 1) and
  the damage summed while hits keep coming within SUM_WINDOW, then continues to CONTROL+40 (ACC_TAIL). A stream that
  later hooks the damage path chains through ACC_TAIL; it never overwrites the entry.
- INPUT3 wraps lock-off INPUT (in front of lockon_select's INPUT2) and, once per queue update of every living human,
  writes one record: the enemies targeting you (TGT: an enemy whose target-table entry is you; a human enemy only while
  locked on) and the enemies attacking you (ATK: targeting you and in an attack action 68..191 / 253..315 or owning a
  live projectile row, or having hit you within HIT_WINDOW). The attacker a tap takes (PICK) is the most recent hitter,
  else the nearest attacker, never your own target while locked. The switch button's PRESS latches it (within
  TAP_GRACE of a warning), so the release after any hold time still finds it. A tap or hold-release switch (kind 1)
  then becomes queue request kind 6; 'when_hit' adds a damped automatic request (AUTO_DAMAGE within SUM_WINDOW from one
  enemy, AUTO_COOLDOWN between, OWN_QUIET after your own target hit you, never while you attack, are unlocked or another
  request waits). Kinds 2, 4 and 5 pass untouched.
- APPLY3 wraps lock-off APPLY at the queue's safe point: kind 6 switches the target table to the latched attacker
  (relocking when unlocked, as an aim does), or, for a tap whose attacker is no longer valid or is already your target,
  falls back to the ordinary next-in-order switch; an automatic request that is invalid or stale is dropped.
Render (reads only; writes nothing but GS packets): DRAW runs once per view for that view's own human seat, from the
overhead-bar wrapper's display call (ENTRY: marks, then the target ring, then the bars) and, in three/four-view matches
and two-player matches with a team assignment, from the quad renderer's two per-view link calls (QUAD_LINK). In the
Tenkaichi Tag Team style: a pair of red chevrons points in at the body of each enemy targeting you; off screen one
chevron on the view border points out toward that enemy (the lower half when behind the camera). While that enemy
attacks you its chevrons grow and blink yellow/red. Pairs follow the enemy's on-screen size (lockon_select SIZE,
clamped per view) and border chevrons the view's height, so both are smaller far away and in split and quad views.
While the target ring is drawn in that view (style ring or both), your own lock-on target's pair is the ring's
chevrons (lockon_select MARKER/QMARKER), which blink the same way; no second pair is drawn on it.
"""
from native_map import A, CRC, SERIAL, ticks
import struct
from prototype import Assembler
import fresh_team_combat as core
import battle_mode_policy as modes
import mod_settings
from regional import DISPLAY_H, Y_ORIGIN, screen_y

BASE = 0x06948000
END = BASE+0x8000      # lockon_select.BASE
HITLOG, TRAMPOLINE, INPUT3, APPLY3 = BASE, BASE+0x200, BASE+0x400, BASE+0x2000
DRAW, ENTRY, QUAD_LINK = BASE+0x3000, BASE+0x5000, BASE+0x5040
CONTROL, ROWS, LAST, CELLS = BASE+0x7000, BASE+0x7100, BASE+0x7400, BASE+0x7500
MAGIC = 0x54485231   # 'THR1'
STRIDE = 64          # ROWS, one per physical slot
LAST_STRIDE = 16     # LAST: attacker (0xFFFFFFFF none), when (feed clock + 1), damage
CELL = 8             # CELLS[victim][attacker]: when (feed clock + 1; 0 never), damage sum (saturating)
CELL_ROW = CELL*modes.ENGINE_ACTORS
SUM_CAP = 1000000
FIELDS = dict(magic=0, manager=4, switch=8, marks=12, hit_window=16, tap_grace=20, sum_window=24, auto_damage=28,
              auto_cooldown=32, own_quiet=36, acc_tail=40, render_tail=44, quad_sites=48, target_colour=52,
              warn_a=56, warn_b=60, outline=64, half=68, warn_half=72, blink=76, top_inset=80, auto_stale=84,
              edge_scale=88, edge_warn_scale=92,
              hits=0x80, taps=0x84, autos=0x88, applied=0x8C, unchanged=0x90, tap_fallbacks=0x94,
              auto_dropped=0x98, auto_blocked=0x9C)
# ROWS fields (bytes 48..63 stay zero).
STAMP, RUN_START, TGT, ATK, PICK, PICK_LATCH, PICK_WHEN = 0, 4, 8, 12, 16, 20, 24
REQ, REQ_SRC, LAST_AUTO, PRESS_PICK, BTN_PREV = 28, 32, 36, 40, 44
KIND_ATTACKER = 6
SOURCES = {'tap': 1, 'auto': 2}
KEYS = ('lockon_attacker_switch', 'lockon_threat_marks')
LEGACY = {'lockon_attacker_switch': 'never', 'lockon_threat_marks': 'hide'}
SWITCH = {'never': 0, 'tap_during_warning': 1, 'when_hit': 2}
MARK_MODES = {'hide': 0, 'marks': 1, 'marks_and_warning': 2}
# Windows in queue/kill-feed updates (30 per second; European 25).
HIT_WINDOW, TAP_GRACE, SUM_WINDOW = ticks(45), ticks(15), ticks(90)
AUTO_DAMAGE, AUTO_COOLDOWN, OWN_QUIET, AUTO_STALE = 1000, ticks(150), ticks(60), ticks(90)
# Attack actions (the 2C4980 action table has the same layout on every disc): melee, smashes, ki blasts, grabs and rushes
# 68..191; blasts, beams and ultimates 253..315. Movement 1..67, hurt/down 192..235 and transformation 236..252 are not.
OFFENSIVE = ((68, 124), (253, 63))
# GS ABGR: red chevrons; warnings alternate yellow and red; a translucent dark outline (lockon_select's colours).
TARGET_COLOUR, WARN_A, WARN_B, OUTLINE = 0x802020E8, 0x8028ECFF, 0x802020E8, 0x50060606
# Chevron scales (Q8 of lockon_select.MARK_CHEVRON, 14 x 18 px): on screen 1.0 / 1.5 while attacking, on the border
# 0.63 (9 x 11 px) / 1.09 since beta.39 (were 0.78 / 1.56), both times the view height over DISPLAY_H. BLINK:
# queue.frames & BLINK picks the warning colour (about 7.5 Hz).
HALF, WARN_HALF, EDGE_SCALE, EDGE_WARN_SCALE, BLINK = 256, 384, 160, 280, 4
# beta.39: from r = lockon_select SIZE of that enemy (sixteenths; 12..34 px in one 448-line view, 6..17 px split or
# quad): the on-screen pair's tips at (TIP_NUM*r >> 8) + TIP_ADD sixteenths from the body centre (0.9 r + 4 px) and
# its scale MARK_BASE + (MARK_NUM*r >> 8) (Q8 of the 14 x 18 px chevron: 150..249 in one view, 123..172 split/quad),
# x1.5 while attacking (HALF / WARN_HALF stay in CONTROL for older readers). Border chevrons: the CONTROL scale times
# the view size over DISPLAY_H (lockon_select.emit_view_size: unchanged in one full view, smaller in split views).
TIP_NUM, TIP_ADD, MARK_NUM, MARK_BASE = 230, 64, 72, 96
ORIENT = dict(right=0, left=1, down=2, up=3)    # lockon_select TRI orientations (the way the tip points)
# Rows kept clear at the top of every view (the clamp's minimum y, on and off screen): the native HUD's health-bar
# band (1-view rows 0..~30, split/quad HUDs ~29) is drawn after the world pass and would cover a top-border mark.
TOP_INSET = screen_y(30)
EDGE_LIMIT = 32767
SAVED = tuple(range(16, 24))+(31,)
# The quad renderer's per-view effects pass: `jal 12CCD0; nop; jal 102708` once per side.
QUAD_SCAN = 0x1000


def jump(target): return struct.pack('<2I', (2 << 26) | (target >> 2), 0)
def jal(target): return struct.pack('<I', (3 << 26) | (target >> 2))


def save(a, size, hilo=False):
    a.addiu(29, 29, -size)
    for i, r in enumerate(SAVED): a.i(63, r, 29, 8*i)
    if hilo:
        a.r(16, 8, 0, 0); a.i(63, 8, 29, 0x48); a.r(18, 8, 0, 0); a.i(63, 8, 29, 0x50)


def restore(a, size, hilo=False, ret=True):
    if hilo:
        a.i(55, 8, 29, 0x48); a.r(17, 0, 8); a.i(55, 8, 29, 0x50); a.r(19, 0, 8)
    for i, r in enumerate(SAVED): a.i(55, r, 29, 8*i)
    a.addiu(29, 29, size)
    if ret: a.jr()


def emit_owned(a, fail, control=8, scratch=9, scratch2=10):
    """Branch to fail unless CONTROL is this capture's (MAGIC, manager)."""
    a.li(control, CONTROL); a.lw(scratch, control); a.li(scratch2, MAGIC); a.branch(5, scratch, scratch2, fail)
    a.lw(scratch, control, 4); a.lw(scratch2, 28, -22364); a.branch(5, scratch, scratch2, fail)


def emit_cell(a, dest, victim, attacker):
    """dest = CELLS + victim*96 + attacker*8 (t0 scratch unless dest)."""
    a.r(0, dest, 0, victim, 6); a.r(0, 8 if dest != 8 else 9, 0, victim, 5)
    a.r(0x21, dest, dest, 8 if dest != 8 else 9)
    a.r(0, 8 if dest != 8 else 9, 0, attacker, 3); a.r(0x21, dest, dest, 8 if dest != 8 else 9)
    a.li(8 if dest != 8 else 9, CELLS); a.r(0x21, dest, dest, 8 if dest != 8 else 9)


def emit_offensive(a, action, yes, scratch=9):
    for start, span in OFFENSIVE:
        a.addiu(scratch, action, -start); a.i(11, scratch, scratch, span); a.branch(5, scratch, 0, yes)


def emit_recent(a, when, now, field, fresh, scratch=11):
    """Branch to fresh when when != 0 and now - when < CONTROL[field] (unsigned); when/now hold registers."""
    a.branch(4, when, 0, fresh+'_old')
    a.r(0x23, scratch, now, when); a.li(25, CONTROL); a.lw(25, 25, FIELDS[field])
    a.r(0x2B, scratch, scratch, 25); a.branch(5, scratch, 0, fresh)
    a.label(fresh+'_old')


def hitlog_code():
    """a0 victim, a1 attacker (-1 unknown), a2 HP lost: entered by the accumulator's entry jump. t0..t7/t9 only."""
    import guest_killfeed as feed
    a = Assembler(HITLOG)
    emit_owned(a, 'tail')
    core.gate(a, 'tail')                                   # t2 count
    a.r(0x2B, 11, 4, 10); a.branch(4, 11, 0, 'tail')
    a.r(0x2B, 11, 5, 10); a.branch(4, 11, 0, 'tail')       # unknown (-1) fails unsigned
    a.branch(4, 4, 5, 'tail'); a.branch(6, 6, 0, 'tail')
    a.li(8, feed.CONTROL); a.lw(12, 8, 12); a.addiu(12, 12, 1)      # t4 when
    a.r(0, 9, 0, 4, 4); a.li(8, LAST); a.r(0x21, 8, 8, 9)
    a.sw(5, 8, 0); a.sw(12, 8, 4); a.sw(6, 8, 8)
    emit_cell(a, 13, 4, 5)                                  # t5 cell
    a.move(14, 6)                                           # t6 sum
    a.lw(15, 13, 0); a.branch(4, 15, 0, 'store')
    a.r(0x23, 15, 12, 15); a.li(8, CONTROL); a.lw(8, 8, FIELDS['sum_window'])
    a.r(0x2B, 15, 15, 8); a.branch(4, 15, 0, 'store')
    a.lw(14, 13, 4); a.r(0x21, 14, 14, 6)
    a.li(8, SUM_CAP); a.r(0x2B, 15, 14, 8); a.branch(5, 15, 0, 'store'); a.move(14, 8)
    a.label('store'); a.sw(12, 13, 0); a.sw(14, 13, 4)
    a.li(8, CONTROL); a.lw(9, 8, FIELDS['hits']); a.addiu(9, 9, 1); a.sw(9, 8, FIELDS['hits'])
    a.label('tail'); a.li(8, CONTROL); a.lw(25, 8, FIELDS['acc_tail']); a.branch(4, 25, 0, 'none')
    a.jr(25)
    a.label('none'); a.jr()
    data = a.finish(); assert len(data) <= TRAMPOLINE-HITLOG; return data


def trampoline(original):
    """The accumulator's original position-independent prologue, then its next word."""
    import cpu_retaliation as retaliation
    return original+jump(retaliation.ACCUMULATE+8)


I_FRAME = 0xC0
NOW, LIVE, OWN, OFFV, SEATM, MTGT, MATK, BEST_J = 0x50, 0x54, 0x58, 0x5C, 0x60, 0x64, 0x68, 0x6C
BEST_WHEN, NEAR_J, NEAR_KEY, TJ, WHENJ, HELD, BEST_SUM, AUTO_J = 0x70, 0x74, 0x78, 0x7C, 0x80, 0x84, 0x88, 0x8C


def input_code():
    """a0 actor, a1 routed held word, a2 physical -> v0 kind (lock-off INPUT's ABI; INPUT2 runs first, unchanged)."""
    import guest_killfeed as feed
    import lockoff_target as off
    import lockon_queue as queue
    import lockon_select as sel
    import multi_contact as mc
    from lockon_select import lwc1, fop, mfc1
    pending = queue.CONTROL+queue.layout()[0]['pending']
    a = Assembler(INPUT3); save(a, I_FRAME)
    a.move(16, 4); a.move(17, 5); a.move(18, 6)
    a.call(sel.INPUT2); a.move(19, 2)                     # s3 kind
    emit_owned(a, 'out')
    core.gate(a, 'out'); a.move(20, 10)                   # s4 count
    a.r(0x2B, 8, 18, 20); a.branch(4, 8, 0, 'out')
    sel.emit_row(a, 18, 21, ROWS)                          # s5 own row
    a.li(8, queue.CONTROL); a.lw(8, 8, queue.FIELDS['frames'])
    a.li(9, feed.CONTROL); a.lw(9, 9, 12); a.addiu(9, 9, 1); a.sw(9, 29, NOW)
    # A gap in this human's queue updates (death, takeover, teardown) starts the record afresh.
    a.lw(10, 21, STAMP); a.addiu(10, 10, 1); a.branch(4, 8, 10, 'stamped')
    for field in range(4, STRIDE, 4): a.sw(0, 21, field)
    a.sw(9, 21, RUN_START)
    a.label('stamped'); a.sw(8, 21, STAMP)
    # Owners of the projectile rows the latest projectile pass saw.
    a.move(12, 0)
    a.li(8, mc.CONTROL); a.lw(9, 8); a.li(10, mc.MAGIC); a.branch(5, 9, 10, 'shots_done')
    a.lw(13, 8, 60); a.li(8, mc.SHOT_ROWS); a.addiu(14, 8, 64*0x100)
    a.label('shot'); a.lw(9, 8, 0); a.branch(4, 9, 0, 'shot_next')
    a.lw(9, 8, 24); a.branch(5, 9, 13, 'shot_next')
    a.lw(9, 8, 4); a.r(0x2B, 10, 9, 20); a.branch(4, 10, 0, 'shot_next')
    a.addiu(10, 0, 1); a.r(4, 10, 9, 10); a.r(0x25, 12, 12, 10)
    a.label('shot_next'); a.addiu(8, 8, 0x100); a.branch(5, 8, 14, 'shot')
    a.label('shots_done'); a.sw(12, 29, LIVE)
    a.li(8, core.TABLE); a.r(0, 9, 0, 18, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.sw(8, 29, OWN)
    a.move(4, 18); a.call(off.IS_OFF); a.sw(2, 29, OFFV)            # 1 = unlocked
    a.sw(0, 29, SEATM)
    sel.emit_model(a, 16, 10, 'seat_modelled', drawn=False); a.sw(10, 29, SEATM)
    a.label('seat_modelled')
    a.sw(0, 29, MTGT); a.sw(0, 29, MATK); a.sw(0, 29, BEST_WHEN)
    a.addiu(8, 0, -1); a.sw(8, 29, BEST_J); a.sw(8, 29, NEAR_J); a.sw(8, 29, NEAR_KEY)
    a.move(22, 0)                                          # s6 j
    a.label('loop'); a.r(0x2B, 8, 22, 20); a.branch(4, 8, 0, 'loop_done')
    a.branch(4, 22, 18, 'next')
    modes.emit_enemy(a, 22, 18, 'next', 'thr_enemy')
    sel.emit_present(a, 22, 'next')
    sel.emit_actor(a, 22, 23, 'next')                      # s7 enemy actor
    sel.emit_health(a, 23, 'next')
    # Targeting you: its table entry is you (a human enemy only while locked on).
    a.sw(0, 29, TJ)
    a.li(8, core.TABLE); a.r(0, 9, 0, 22, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.branch(5, 8, 18, 'tj_done')
    a.lw(8, 23, 0x1278); a.branch(5, 8, 0, 'tj_yes')
    a.move(4, 22); a.call(off.IS_OFF); a.branch(5, 2, 0, 'tj_done')
    a.label('tj_yes'); a.addiu(8, 0, 1); a.sw(8, 29, TJ)
    a.label('tj_done')
    # In an attack action, or owning a live projectile row.
    a.move(13, 0)
    a.lw(8, 23, 0x948); emit_offensive(a, 8, 'off_yes')
    a.lw(9, 29, LIVE); a.addiu(10, 0, 1); a.r(4, 10, 22, 10); a.r(0x24, 9, 9, 10); a.branch(4, 9, 0, 'off_done')
    a.label('off_yes'); a.addiu(13, 0, 1)
    a.label('off_done')
    # Hit you within HIT_WINDOW, since this record began.
    a.move(14, 0)
    emit_cell(a, 15, 18, 22)
    a.lw(9, 15, 0); a.sw(9, 29, WHENJ); a.branch(4, 9, 0, 'hit_done')
    a.lw(10, 21, RUN_START); a.r(0x2B, 11, 9, 10); a.branch(5, 11, 0, 'hit_done')
    a.lw(10, 29, NOW); emit_recent(a, 9, 10, 'hit_window', 'hit')
    a.jump('hit_done')
    a.label('hit'); a.addiu(14, 0, 1)
    a.label('hit_done')
    a.addiu(10, 0, 1); a.r(4, 10, 22, 10)                 # t2 this enemy's bit
    a.lw(12, 29, TJ); a.branch(4, 12, 0, 'no_tgt')
    a.lw(8, 29, MTGT); a.r(0x25, 8, 8, 10); a.sw(8, 29, MTGT)
    a.label('no_tgt')
    a.r(0x24, 9, 12, 13); a.r(0x25, 9, 9, 14); a.branch(4, 9, 0, 'next')
    a.lw(8, 29, MATK); a.r(0x25, 8, 8, 10); a.sw(8, 29, MATK)
    # The attacker a tap takes: never your own target while locked on.
    a.lw(8, 29, OFFV); a.branch(5, 8, 0, 'candidate')
    a.lw(8, 29, OWN); a.branch(4, 8, 22, 'next')
    a.label('candidate'); a.branch(4, 14, 0, 'nearest')
    a.lw(9, 29, WHENJ); a.lw(8, 29, BEST_WHEN); a.r(0x2B, 8, 8, 9); a.branch(4, 8, 0, 'next')
    a.sw(9, 29, BEST_WHEN); a.sw(22, 29, BEST_J); a.jump('next')
    a.label('nearest')
    a.lw(10, 29, SEATM); a.branch(4, 10, 0, 'next')
    sel.emit_model(a, 23, 11, 'next', drawn=False)
    lwc1(a, 0, 11, 2416); lwc1(a, 1, 10, 2416); fop(a, 1, 0, 0, 1)
    lwc1(a, 2, 11, 2420); lwc1(a, 3, 10, 2420); fop(a, 1, 2, 2, 3)
    lwc1(a, 4, 11, 2424); lwc1(a, 5, 10, 2424); fop(a, 1, 4, 4, 5)
    fop(a, 2, 0, 0, 0); fop(a, 2, 2, 2, 2); fop(a, 2, 4, 4, 4); fop(a, 0, 0, 0, 2); fop(a, 0, 0, 0, 4)
    mfc1(a, 12, 0)
    a.lw(8, 29, NEAR_KEY); a.r(0x2B, 9, 12, 8); a.branch(4, 9, 0, 'next')
    a.sw(12, 29, NEAR_KEY); a.sw(22, 29, NEAR_J)
    a.label('next'); a.addiu(22, 22, 1); a.jump('loop')
    a.label('loop_done')
    a.lw(8, 29, MTGT); a.sw(8, 21, TGT); a.lw(8, 29, MATK); a.sw(8, 21, ATK)
    a.lw(8, 29, BEST_J); a.addiu(9, 0, -1); a.branch(5, 8, 9, 'picked'); a.lw(8, 29, NEAR_J)
    a.label('picked'); a.addiu(8, 8, 1); a.sw(8, 21, PICK)
    a.branch(4, 8, 0, 'latched'); a.sw(8, 21, PICK_LATCH); a.lw(9, 29, NOW); a.sw(9, 21, PICK_WHEN)
    a.label('latched')
    # The switch button's press latches the warning's attacker, so a release after any hold time still finds it.
    a.li(8, queue.CONTROL); a.lw(8, 8, queue.FIELDS['button']); a.r(0x24, 9, 17, 8); a.sw(9, 29, HELD)
    a.branch(4, 9, 0, 'edge_done'); a.lw(10, 21, BTN_PREV); a.branch(5, 10, 0, 'edge_done')
    a.move(15, 0); a.lw(14, 21, PICK_LATCH); a.lw(9, 21, PICK_WHEN); a.lw(10, 29, NOW)
    emit_recent(a, 9, 10, 'tap_grace', 'press_recent'); a.jump('press_set')
    a.label('press_recent'); a.move(15, 14)
    a.label('press_set'); a.sw(15, 21, PRESS_PICK)
    a.label('edge_done'); a.lw(9, 29, HELD); a.sw(9, 21, BTN_PREV)
    a.li(23, CONTROL); a.lw(8, 23, FIELDS['switch']); a.branch(4, 8, 0, 'clear')
    a.addiu(9, 0, 1); a.branch(5, 19, 9, 'not_tap')
    # A tap or hold-release switch during (or TAP_GRACE after) a warning takes the latched attacker.
    a.lw(14, 21, PRESS_PICK); a.branch(5, 14, 0, 'tap_request')
    a.lw(14, 21, PICK_LATCH); a.lw(9, 21, PICK_WHEN); a.lw(10, 29, NOW)
    emit_recent(a, 9, 10, 'tap_grace', 'tap_recent'); a.jump('clear')
    a.label('tap_recent'); a.branch(4, 14, 0, 'clear')
    a.label('tap_request'); a.sw(14, 21, REQ); a.addiu(9, 0, SOURCES['tap']); a.sw(9, 21, REQ_SRC)
    a.lw(8, 23, FIELDS['taps']); a.addiu(8, 8, 1); a.sw(8, 23, FIELDS['taps'])
    a.jump('request')
    a.label('not_tap'); a.branch(5, 19, 0, 'clear')
    a.addiu(9, 0, 2); a.branch(5, 8, 9, 'clear')
    a.lw(9, 29, OFFV); a.branch(5, 9, 0, 'clear')
    a.lw(8, 16, 0x948); emit_offensive(a, 8, 'clear')
    a.lw(9, 21, LAST_AUTO); a.lw(10, 29, NOW); a.li(25, CONTROL)
    a.branch(4, 9, 0, 'cooled'); a.r(0x23, 11, 10, 9); a.lw(12, 25, FIELDS['auto_cooldown'])
    a.r(0x2B, 11, 11, 12); a.branch(5, 11, 0, 'clear')
    a.label('cooled')
    a.lw(12, 29, OWN); a.r(0x2B, 8, 12, 20); a.branch(4, 8, 0, 'quiet')
    emit_cell(a, 15, 18, 12); a.lw(9, 15, 0); a.lw(10, 29, NOW)
    emit_recent(a, 9, 10, 'own_quiet', 'clear')
    a.label('quiet')
    a.r(0, 9, 0, 18, 2); a.li(8, pending); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.branch(4, 8, 0, 'auto_search')
    a.lw(8, 23, FIELDS['auto_blocked']); a.addiu(8, 8, 1); a.sw(8, 23, FIELDS['auto_blocked']); a.jump('clear')
    a.label('auto_search')
    a.sw(0, 29, BEST_SUM); a.addiu(8, 0, -1); a.sw(8, 29, AUTO_J)
    a.move(22, 0)
    a.label('auto_loop'); a.r(0x2B, 8, 22, 20); a.branch(4, 8, 0, 'auto_done')
    a.branch(4, 22, 18, 'auto_next'); a.lw(8, 29, OWN); a.branch(4, 8, 22, 'auto_next')
    modes.emit_enemy(a, 22, 18, 'auto_next', 'auto_enemy')
    sel.emit_present(a, 22, 'auto_next')
    sel.emit_actor(a, 22, 13, 'auto_next')
    sel.emit_health(a, 13, 'auto_next')
    emit_cell(a, 15, 18, 22)
    a.lw(9, 15, 0); a.branch(4, 9, 0, 'auto_next')
    a.lw(10, 21, RUN_START); a.r(0x2B, 11, 9, 10); a.branch(5, 11, 0, 'auto_next')
    a.lw(10, 29, NOW); emit_recent(a, 9, 10, 'hit_window', 'auto_recent'); a.jump('auto_next')
    a.label('auto_recent')
    a.lw(12, 15, 4); a.li(25, CONTROL); a.lw(8, 25, FIELDS['auto_damage']); a.r(0x2B, 8, 12, 8)
    a.branch(5, 8, 0, 'auto_next')
    a.lw(8, 29, BEST_SUM); a.r(0x2B, 8, 8, 12); a.branch(4, 8, 0, 'auto_next')
    a.sw(12, 29, BEST_SUM); a.sw(22, 29, AUTO_J)
    a.label('auto_next'); a.addiu(22, 22, 1); a.jump('auto_loop')
    a.label('auto_done')
    a.lw(8, 29, AUTO_J); a.addiu(9, 0, -1); a.branch(4, 8, 9, 'clear')
    a.addiu(8, 8, 1); a.sw(8, 21, REQ); a.addiu(9, 0, SOURCES['auto']); a.sw(9, 21, REQ_SRC)
    a.lw(9, 29, NOW); a.sw(9, 21, LAST_AUTO)
    a.li(23, CONTROL); a.lw(8, 23, FIELDS['autos']); a.addiu(8, 8, 1); a.sw(8, 23, FIELDS['autos'])
    a.label('request')
    sel.emit_row(a, 18, 9, off.ROWS, 5); a.addiu(19, 0, KIND_ATTACKER); a.sw(19, 9, off.KIND)
    a.label('clear'); a.lw(8, 29, HELD); a.branch(5, 8, 0, 'out'); a.sw(0, 21, PRESS_PICK)
    a.label('out'); a.move(2, 19); restore(a, I_FRAME)
    data = a.finish(); assert len(data) <= APPLY3-INPUT3; return data


def apply_code():
    """a0 actor, a1 physical -> v0 (lock-off APPLY's ABI, at the queue's safe point). Other kinds go to APPLY2."""
    import guest_killfeed as feed
    import lockoff_target as off
    import lockon_queue as queue
    import lockon_select as sel
    a = Assembler(APPLY3); save(a, 0x100)
    a.move(16, 4); a.move(17, 5)
    emit_owned(a, 'pass')
    a.li(21, CONTROL)
    sel.emit_row(a, 17, 19, off.ROWS, 5)                   # s3 lock-off row
    a.lw(8, 19, off.KIND); a.addiu(9, 0, KIND_ATTACKER); a.branch(5, 8, 9, 'pass')
    sel.emit_row(a, 17, 22, ROWS)                          # s6 own row
    a.lw(18, 22, REQ); a.lw(23, 22, REQ_SRC); a.sw(0, 22, REQ); a.sw(0, 22, REQ_SRC)
    a.addiu(18, 18, -1)                                    # s2 attacker (-1: none)
    core.gate(a, 'invalid'); a.r(0x2B, 8, 18, 10); a.branch(4, 8, 0, 'invalid')
    sel.emit_candidate(a, 18, 17, 11, 13, 'invalid', 'thr_apply')
    a.addiu(8, 0, SOURCES['auto']); a.branch(5, 23, 8, 'current')
    # An automatic request waits behind cinematics and grabs; it applies only while its hit is recent.
    emit_cell(a, 15, 17, 18); a.lw(9, 15, 0)
    a.li(10, feed.CONTROL); a.lw(10, 10, 12); a.addiu(10, 10, 1)
    emit_recent(a, 9, 10, 'auto_stale', 'current'); a.jump('drop')
    a.label('current')
    a.li(8, core.TABLE); a.r(0, 9, 0, 17, 2); a.r(0x21, 20, 8, 9)
    a.lw(8, 19, off.OFF); a.branch(5, 8, 0, 'relock')
    a.lw(9, 20); a.branch(5, 9, 18, 'switch')
    a.addiu(8, 0, SOURCES['tap']); a.branch(4, 23, 8, 'fallback')      # already your target: next in order
    a.lw(8, 21, FIELDS['unchanged']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['unchanged']); a.jump('consumed')
    a.label('switch'); a.sw(18, 20); a.jump('changed')
    a.label('relock'); a.sw(18, 20)
    a.sw(0, 19, off.OFF); a.addiu(8, 0, 2); a.sw(8, 19, off.QUIET)
    a.move(4, 16); a.addiu(5, 0, 5); a.call(A(0x1DA9D0))
    a.label('changed')
    sel.emit_row(a, 17, 20)                                # s4 lockon_select row (emit_rewatch)
    a.addiu(8, 18, 1); sel.emit_rewatch(a, 8, 'thr_watched'); a.sw(0, 20, sel.DEADN)
    a.li(8, queue.CONTROL); a.lw(9, 8, queue.FIELDS['switches']); a.addiu(9, 9, 1); a.sw(9, 8, queue.FIELDS['switches'])
    a.r(0, 9, 0, 17, 2); a.r(0x21, 8, 8, 9)
    a.lw(9, 8, queue.FIELDS['per_actor']); a.addiu(9, 9, 1); a.sw(9, 8, queue.FIELDS['per_actor'])
    a.li(21, CONTROL); a.lw(8, 21, FIELDS['applied']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['applied'])
    a.label('consumed'); a.addiu(2, 0, 1); restore(a, 0x100)
    a.label('invalid'); a.addiu(8, 0, SOURCES['tap']); a.branch(5, 23, 8, 'drop')
    a.label('fallback')
    a.li(21, CONTROL); a.lw(8, 21, FIELDS['tap_fallbacks']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['tap_fallbacks'])
    a.addiu(8, 0, 1); a.sw(8, 19, off.KIND)
    a.label('pass'); a.move(4, 16); a.move(5, 17); restore(a, 0x100, ret=False); a.jump(sel.APPLY2)
    a.label('drop')
    a.li(21, CONTROL); a.lw(8, 21, FIELDS['auto_dropped']); a.addiu(8, 8, 1); a.sw(8, 21, FIELDS['auto_dropped'])
    a.jump('consumed')
    data = a.finish(); assert len(data) <= DRAW-APPLY3; return data


D_FRAME = 0x100
D_NATIVE, D_DRAW, D_WARN, D_ISWARN, D_HALF, D_BLINK = 0x58, 0x5C, 0x60, 0x64, 0x68, 0x6C
D_CX, D_CY, D_HW, D_HH, D_OUT, D_OK, D_MX, D_MY, D_QUAL, D_POINT = 0x70, 0x74, 0x78, 0x7C, 0x80, 0x90, 0x94, 0x98, 0x9C, 0xA0
D_COLOUR, D_SCALE, D_TIP, D_ORIENT, D_EOP, D_X16, D_Y16, D_OWN = 0xB0, 0xB4, 0xB8, 0xBC, 0xC0, 0xC4, 0xC8, 0xCC


def emit_abs(a, dest, src, tag):
    a.move(dest, src); a.branch(1, dest, 1, tag); a.r(0x23, dest, 0, dest); a.label(tag)


def emit_divide(a, out, numerator, divisor, tag):
    """out = numerator / divisor truncated toward zero (divisor > 0); t0, HI/LO."""
    emit_abs(a, 8, numerator, tag+'_abs')
    a.r(27, 0, 8, divisor); a.r(18, out, 0, 0)
    a.branch(1, numerator, 1, tag+'_done'); a.r(0x23, out, 0, out)
    a.label(tag+'_done')


def emit_margin(a, scale):
    """t6 = a chevron's clamp margin in pixels at this scale: its half height (9 px at 256) + 3."""
    a.r(0, 14, 0, scale, 3); a.r(0x21, 14, 14, scale); a.r(2, 14, 0, 14, 8); a.addiu(14, 14, 3)


def emit_sixteenths(a):
    """D_X16/D_Y16 = the view pixel (t4, t5) in GS sixteenths. t0."""
    a.addiu(8, 12, 1792); a.r(0, 8, 0, 8, 4); a.sw(8, 29, D_X16)
    a.addiu(8, 13, Y_ORIGIN); a.r(0, 8, 0, 8, 4); a.sw(8, 29, D_Y16)


def draw_code():
    """a0 1 from the overhead-bar call (one or two native views), 0 from a quad view. Render only."""
    import cinematic_policy as cinema
    import display_settings as display
    import lockoff_target as off
    import lockon_queue as queue
    import lockon_select as sel
    import quad_viewports as views
    import rush_cinematics as rush
    from guest_healthbars import valid_pointer
    from result_presentation import RESULT
    a = Assembler(DRAW); save(a, D_FRAME, hilo=True)
    a.sw(4, 29, D_NATIVE)
    emit_owned(a, 'return')
    a.li(21, CONTROL); a.lw(8, 21, FIELDS['marks']); a.branch(4, 8, 0, 'return')
    a.li(8, A(0x2FEB38)); a.lw(11, 8); valid_pointer(a, 11, 'return', 0x200)
    a.lw(9, 11); a.addiu(10, 0, 3); a.branch(5, 9, 10, 'return')
    a.li(8, RESULT); a.lw(8, 8); a.branch(5, 8, 0, 'return')
    core.gate(a, 'return'); a.move(19, 10)                 # s3 count
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'return')
    rush.emit_hud_gate(a, 'return', 'thr_rush')
    a.li(8, A(0x2FEBCC)); a.lw(11, 8); a.branch(4, 11, 0, 'free_camera')
    valid_pointer(a, 11, 'return', 816); a.lw(8, 11, 812); a.branch(5, 8, 0, 'return')
    a.label('free_camera')
    a.li(8, cinema.CONTROL); a.lw(9, 8); a.li(10, cinema.MAGIC); a.branch(5, 9, 10, 'no_policy')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'no_policy')
    a.lw(9, 8, cinema.SHARED_STOP); a.branch(5, 9, 0, 'return')
    a.label('no_policy')
    a.li(21, CONTROL)
    a.lw(22, 28, -22176); valid_pointer(a, 22, 'return', 0x300); sel.emit_viewport(a, 22, 'return')
    # This view's seat (lockon_select MARKER's rule).
    a.li(8, views.CONTROL); a.lw(9, 8); a.li(10, views.MAGIC); a.branch(5, 9, 10, 'single')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'single')
    a.lw(12, 8, views.VIEW_COUNT); a.i(11, 9, 12, 5); a.branch(4, 9, 0, 'return')
    a.move(13, 0); a.li(14, views.CAMERAS)
    a.label('views'); a.branch(4, 13, 12, 'return')
    for at in (512, 516, 520, 524):
        a.lw(9, 14, at); a.lw(10, 22, at); a.branch(5, 9, 10, 'other_view')
    a.r(0, 9, 0, 13, 2); a.li(10, views.SUBJECTS); a.r(0x21, 9, 9, 10); a.lw(16, 9); a.jump('seat')
    a.label('other_view'); a.addiu(13, 13, 1); a.addiu(14, 14, 1024); a.jump('views')
    a.label('single')
    a.li(8, display.CONTROL); a.lw(9, 8); a.li(10, display.MAGIC); a.branch(5, 9, 10, 'return')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'return')
    a.move(4, 22); a.call(display.SUBJECT); a.move(16, 2)
    a.label('seat')
    a.r(0x2B, 8, 16, 19); a.branch(4, 8, 0, 'return')
    sel.emit_actor(a, 16, 17, 'return'); a.lw(8, 17, 0x1278); a.branch(5, 8, 0, 'return')
    sel.emit_health(a, 17, 'return')
    sel.emit_row(a, 16, 20, ROWS)                          # s4 the seat's record, fresh from this or the last update
    a.li(8, queue.CONTROL); a.lw(23, 8, queue.FIELDS['frames'])
    a.lw(9, 20, STAMP); a.r(0x23, 9, 23, 9); a.i(11, 9, 9, 2); a.branch(4, 9, 0, 'return')
    a.lw(8, 21, FIELDS['blink']); a.r(0x24, 8, 23, 8); a.sw(8, 29, D_BLINK)
    # Native views only: one fighter's authored close-up (flag 0xD3, a checked ultimate or transformation class) owns
    # the camera; a best-effort mirror of cinematic_policy.priority().
    a.lw(8, 29, D_NATIVE); a.branch(4, 8, 0, 'priority_done')
    a.li(8, cinema.CONTROL); a.lw(9, 8); a.li(10, cinema.MAGIC); a.branch(5, 9, 10, 'priority_done')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'priority_done')
    a.sw(0, 29, D_QUAL); a.move(18, 0)
    a.label('priority'); a.r(0x2B, 8, 18, 19); a.branch(4, 8, 0, 'priority_counted')
    sel.emit_actor(a, 18, 23, 'priority_next')
    a.i(36, 9, 23, cinema.PRIORITY_FLAG_BYTES[0]); a.i(36, 10, 23, cinema.PRIORITY_FLAG_BYTES[1]); a.r(0x25, 9, 9, 10)
    a.i(12, 9, 9, cinema.PRIORITY_FLAG_BIT); a.branch(4, 9, 0, 'priority_next')
    sel.emit_health(a, 23, 'priority_next')
    a.lw(4, 23, 0x948); a.call(cinema.CLASSIFY)
    a.addiu(9, 2, -1); a.i(11, 9, 9, 2); a.branch(4, 9, 0, 'priority_next')
    a.r(0, 9, 0, 2, 2); a.li(10, cinema.CONTROL+12); a.r(0x21, 10, 10, 9); a.lw(10, 10); a.branch(4, 10, 0, 'priority_next')
    a.lw(8, 29, D_QUAL); a.addiu(8, 8, 1); a.sw(8, 29, D_QUAL)
    a.label('priority_next'); a.addiu(18, 18, 1); a.jump('priority')
    a.label('priority_counted'); a.lw(8, 29, D_QUAL); a.addiu(9, 0, 1); a.branch(4, 8, 9, 'return')
    a.label('priority_done')
    # Marks: enemies targeting you (marks), plus those attacking you (marks and warning), which also flash.
    a.lw(8, 21, FIELDS['marks']); a.lw(9, 20, TGT); a.lw(10, 20, ATK)
    a.addiu(11, 0, 2); a.branch(4, 8, 11, 'warned'); a.move(10, 0); a.jump('sets')
    a.label('warned'); a.r(0x25, 9, 9, 10)
    a.label('sets'); a.sw(9, 29, D_DRAW); a.sw(10, 29, D_WARN); a.branch(4, 9, 0, 'return')
    sel.emit_push(a, 22)
    a.move(18, 0)
    a.label('loop'); a.r(0x2B, 8, 18, 19); a.branch(4, 8, 0, 'pop')
    a.addiu(9, 0, 1); a.r(4, 9, 18, 9); a.lw(8, 29, D_DRAW); a.r(0x24, 8, 8, 9); a.branch(4, 8, 0, 'next')
    a.lw(8, 29, D_WARN); a.r(0x24, 8, 8, 9); a.sw(8, 29, D_ISWARN)
    sel.emit_actor(a, 18, 17, 'next'); sel.emit_health(a, 17, 'next'); sel.emit_model(a, 17, 23, 'next')
    # Your own lock-on target in a view with the target ring (style ring or both; a native view through the bar call,
    # a quad view through QMARKER): the ring's chevrons carry its mark on screen.
    a.sw(0, 29, D_OWN)
    a.li(10, sel.CONTROL); a.lw(9, 10, sel.FIELDS['style']); a.i(12, 9, 9, 2); a.branch(4, 9, 0, 'not_own')
    a.lw(8, 29, D_NATIVE); a.branch(5, 8, 0, 'own_native')
    a.lw(9, 10, sel.FIELDS['quad']); a.branch(4, 9, 0, 'not_own'); a.jump('own_seat')
    a.label('own_native')
    a.lw(8, 21, FIELDS['render_tail']); a.li(9, sel.MARKER); a.branch(5, 8, 9, 'not_own')
    a.label('own_seat')
    a.li(8, core.TABLE); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.branch(5, 8, 18, 'not_own')
    a.move(4, 16); a.call(off.IS_OFF); a.branch(5, 2, 0, 'not_own')
    a.addiu(8, 0, 1); a.sw(8, 29, D_OWN)
    a.label('not_own')
    # Colour: red; while attacking you, blinking warn_a / warn_b.
    a.lw(9, 21, FIELDS['target_colour']); a.lw(10, 29, D_ISWARN); a.branch(4, 10, 0, 'styled')
    a.lw(9, 21, FIELDS['warn_a']); a.lw(10, 29, D_BLINK); a.branch(5, 10, 0, 'styled'); a.lw(9, 21, FIELDS['warn_b'])
    a.label('styled'); a.sw(9, 29, D_COLOUR)
    # The body centre, projected; behind the camera the raw result still gives a direction.
    sel.emit_body_centre(a, 23, D_POINT, 'body')
    a.addiu(4, 29, D_OUT); a.call(A(0x1210D8)); a.sw(2, 29, D_OK)
    a.lw(12, 29, D_OUT); a.r(3, 12, 0, 12, 4); a.addiu(12, 12, -1792)      # t4 px
    a.lw(13, 29, D_OUT+4); a.r(3, 13, 0, 13, 4); a.addiu(13, 13, -Y_ORIGIN)  # t5 py
    a.lw(8, 29, D_OK); a.branch(4, 8, 0, 'offscreen')
    a.lw(8, 29, D_OUT+12); a.branch(6, 8, 0, 'offscreen')
    a.lw(8, 29, D_OUT+8); a.branch(1, 8, 0, 'offscreen')
    a.lw(8, 22, 512); a.r(0x2A, 9, 12, 8); a.branch(5, 9, 0, 'offscreen')
    a.lw(8, 22, 516); a.r(0x2A, 9, 8, 12); a.branch(5, 9, 0, 'offscreen')
    a.lw(8, 22, 520); a.r(0x2A, 9, 13, 8); a.branch(5, 9, 0, 'offscreen')
    a.lw(8, 22, 524); a.r(0x2A, 9, 8, 13); a.branch(5, 9, 0, 'offscreen')
    # On screen: an inward pair bracketing the body centre, kept below TOP_INSET and above the bottom by its height.
    a.lw(8, 29, D_OWN); a.branch(5, 8, 0, 'next')
    a.sw(12, 29, D_MX); a.sw(13, 29, D_MY)
    a.move(4, 23); a.move(5, 22); a.call(sel.SIZE)                              # v0 r (this enemy, this view)
    a.addiu(8, 0, TIP_NUM); a.r(24, 0, 2, 8); a.r(18, 8, 0, 0); a.r(3, 8, 0, 8, 8); a.addiu(8, 8, TIP_ADD)
    a.sw(8, 29, D_TIP)
    a.addiu(8, 0, MARK_NUM); a.r(24, 0, 2, 8); a.r(18, 8, 0, 0); a.r(3, 8, 0, 8, 8); a.addiu(8, 8, MARK_BASE)
    a.lw(10, 29, D_ISWARN); a.branch(4, 10, 0, 'pair_sized'); a.r(3, 9, 0, 8, 1); a.r(0x21, 8, 8, 9)
    a.label('pair_sized'); a.sw(8, 29, D_SCALE)
    a.lw(12, 29, D_MX); a.lw(13, 29, D_MY)
    emit_margin(a, 8)
    a.lw(8, 22, 520); a.r(0x21, 8, 8, 14); a.lw(9, 21, FIELDS['top_inset']); a.r(0x21, 8, 8, 9)
    a.r(0x2A, 9, 13, 8); a.branch(4, 9, 0, 'pair_low'); a.move(13, 8)
    a.label('pair_low'); a.lw(8, 22, 524); a.r(0x23, 8, 8, 14); a.r(0x2A, 9, 8, 13); a.branch(4, 9, 0, 'pair_high')
    a.move(13, 8)
    a.label('pair_high'); emit_sixteenths(a)
    sel.emit_packet_begin(a, 17, 'pair_header')
    sel.emit_chevron_pair(a, 17, D_X16, D_Y16, D_TIP, D_SCALE, sel.MARK_OUTLINE, sel.MARK_FILL, D_COLOUR, D_EOP)
    sel.emit_packet_end(a, 17, D_EOP)
    a.jump('next')
    # Off screen: the border point in the enemy's direction from the view centre, the ratio kept; one chevron there
    # pointing out toward the enemy (the side of the border reached).
    a.label('offscreen')
    a.lw(8, 21, FIELDS['edge_scale']); a.lw(10, 29, D_ISWARN); a.branch(4, 10, 0, 'edge_sized')
    a.lw(8, 21, FIELDS['edge_warn_scale'])
    a.label('edge_sized')
    sel.emit_view_size(a, 22, 10, 9)
    a.r(24, 0, 8, 10); a.r(18, 8, 0, 0); a.addiu(9, 0, DISPLAY_H); a.r(0x1B, 0, 8, 9); a.r(18, 8, 0, 0)
    a.sw(8, 29, D_SCALE)
    emit_margin(a, 8); a.sw(14, 29, D_HALF)
    for lo, hi, centre, half in ((512, 516, D_CX, D_HW), (520, 524, D_CY, D_HH)):
        a.lw(8, 22, lo); a.lw(9, 22, hi); a.r(0x21, 10, 8, 9); a.r(3, 10, 0, 10, 1); a.sw(10, 29, centre)
        a.r(0x23, 11, 9, 8); a.r(3, 11, 0, 11, 1); a.r(0x23, 11, 11, 14); a.sw(11, 29, half)
        a.branch(6, 11, 0, 'next')
    a.lw(8, 29, D_CX); a.r(0x23, 12, 12, 8); a.lw(8, 29, D_CY); a.r(0x23, 13, 13, 8)
    a.label('scale')
    emit_abs(a, 8, 12, 'scale_x'); a.addiu(10, 0, EDGE_LIMIT); a.r(0x2A, 11, 10, 8); a.branch(5, 11, 0, 'halve')
    emit_abs(a, 8, 13, 'scale_y'); a.r(0x2A, 11, 10, 8); a.branch(4, 11, 0, 'scaled')
    a.label('halve'); a.r(3, 12, 0, 12, 1); a.r(3, 13, 0, 13, 1); a.jump('scale')
    a.label('scaled')
    a.lw(8, 29, D_OUT+12); a.branch(7, 8, 0, 'front')
    a.r(0x23, 12, 0, 12); emit_abs(a, 13, 13, 'behind'); a.lw(8, 29, D_HH); a.r(0x21, 13, 13, 8)
    a.label('front')
    a.branch(5, 12, 0, 'direction'); a.branch(4, 13, 0, 'next')
    a.label('direction')
    emit_abs(a, 10, 12, 'adx'); emit_abs(a, 11, 13, 'ady')
    a.lw(8, 29, D_HH); a.r(24, 0, 10, 8); a.r(18, 14, 0, 0)
    a.lw(8, 29, D_HW); a.r(24, 0, 11, 8); a.r(18, 15, 0, 0)
    a.r(0x2A, 8, 14, 15); a.branch(5, 8, 0, 'vertical')
    a.lw(8, 29, D_HW); a.r(24, 0, 13, 8); a.r(18, 9, 0, 0)          # dy*hw / |dx|
    emit_divide(a, 15, 9, 10, 'side_y'); a.lw(8, 29, D_CY); a.r(0x21, 13, 8, 15)
    a.lw(8, 29, D_HW); a.addiu(9, 0, ORIENT['right']); a.branch(7, 12, 0, 'right')
    a.r(0x23, 8, 0, 8); a.addiu(9, 0, ORIENT['left'])
    a.label('right'); a.sw(9, 29, D_ORIENT); a.lw(9, 29, D_CX); a.r(0x21, 12, 9, 8); a.jump('clamp')
    a.label('vertical')
    a.lw(8, 29, D_HH); a.r(24, 0, 12, 8); a.r(18, 9, 0, 0)          # dx*hh / |dy|
    emit_divide(a, 15, 9, 11, 'side_x'); a.lw(8, 29, D_CX); a.r(0x21, 12, 8, 15)
    a.lw(8, 29, D_HH); a.addiu(9, 0, ORIENT['down']); a.branch(7, 13, 0, 'below')
    a.r(0x23, 8, 0, 8); a.addiu(9, 0, ORIENT['up'])
    a.label('below'); a.sw(9, 29, D_ORIENT); a.lw(9, 29, D_CY); a.r(0x21, 13, 9, 8)
    # Inside the view by the chevron's margin; the top kept clear of TOP_INSET rows.
    a.label('clamp')
    a.lw(14, 29, D_HALF)
    a.lw(8, 22, 512); a.r(0x21, 8, 8, 14); a.r(0x2A, 9, 12, 8); a.branch(4, 9, 0, 'x_min'); a.move(12, 8)
    a.label('x_min'); a.lw(8, 22, 516); a.r(0x23, 8, 8, 14); a.r(0x2A, 9, 8, 12); a.branch(4, 9, 0, 'x_max'); a.move(12, 8)
    a.label('x_max'); a.lw(8, 22, 520); a.r(0x21, 8, 8, 14); a.lw(9, 21, FIELDS['top_inset']); a.r(0x21, 8, 8, 9)
    a.r(0x2A, 9, 13, 8); a.branch(4, 9, 0, 'y_min'); a.move(13, 8)
    a.label('y_min'); a.lw(8, 22, 524); a.r(0x23, 8, 8, 14); a.r(0x2A, 9, 8, 13); a.branch(4, 9, 0, 'y_max'); a.move(13, 8)
    a.label('y_max'); emit_sixteenths(a)
    sel.emit_packet_begin(a, 17, 'edge_header')
    for table, slot in ((sel.MARK_OUTLINE, None), (sel.MARK_FILL, D_COLOUR)):
        sel.emit_segment(a, 17, sel.PRIM_TRIANGLES, 3, sel.DARK, slot, D_EOP)
        sel.emit_chevron(a, 17, D_X16, D_Y16, None, D_SCALE, ('sp', D_ORIENT), table)
        a.sw(0, 4, 0); a.sw(0, 4, 4); a.addiu(17, 17, 8)          # the tag's 64-bit padding (3 is odd)
    sel.emit_packet_end(a, 17, D_EOP)
    a.label('next'); a.addiu(18, 18, 1); a.jump('loop')
    a.label('pop'); a.call(A(0x120AC8))
    a.label('return'); restore(a, D_FRAME, hilo=True)
    data = a.finish(); assert len(data) <= ENTRY-DRAW; return data


def entry_code():
    """The overhead-bar wrapper's display call: marks first, then the call it replaced (CONTROL+44)."""
    a = Assembler(ENTRY)
    a.addiu(29, 29, -16); a.i(63, 31, 29, 0)
    a.addiu(4, 0, 1); a.call(DRAW)
    a.i(55, 31, 29, 0); a.addiu(29, 29, 16)
    a.li(8, CONTROL); a.lw(25, 8, FIELDS['render_tail']); a.branch(4, 25, 0, 'none')
    a.jr(25)
    a.label('none'); a.jr()
    data = a.finish(); assert len(data) <= QUAD_LINK-ENTRY; return data


def quad_link_code():
    """A quad view's world-effects link (native 102708, a0..a3 untouched), then this view's marks; v0/v1 kept."""
    a = Assembler(QUAD_LINK)
    a.addiu(29, 29, -32); a.i(63, 31, 29, 0)
    a.call(A(0x102708))
    a.i(63, 2, 29, 8); a.i(63, 3, 29, 16)
    a.move(4, 0); a.call(DRAW)
    a.i(55, 2, 29, 8); a.i(55, 3, 29, 16); a.i(55, 31, 29, 0); a.addiu(29, 29, 32); a.jr()
    data = a.finish(); assert len(data) <= 0x40; return data


def control_block(manager, switch, marks, acc_tail, render_tail, quad):
    control = bytearray(0x100)
    struct.pack_into('<24I', control, 0, MAGIC, manager, switch, marks, HIT_WINDOW, TAP_GRACE, SUM_WINDOW, AUTO_DAMAGE,
                     AUTO_COOLDOWN, OWN_QUIET, acc_tail, render_tail, quad, TARGET_COLOUR, WARN_A, WARN_B, OUTLINE, HALF,
                     WARN_HALF, BLINK, TOP_INSET, AUTO_STALE, EDGE_SCALE, EDGE_WARN_SCALE)
    return bytes(control)


def data_blocks(manager, switch, marks, acc_tail, render_tail, quad):
    """CONTROL, the zero records and LAST (no attacker yet)."""
    last = b''.join(struct.pack('<4I', 0xFFFFFFFF, 0, 0, 0) for _ in range(modes.ENGINE_ACTORS))
    return [(CONTROL, control_block(manager, switch, marks, acc_tail, render_tail, quad)),
            (ROWS, bytes(STRIDE*modes.ENGINE_ACTORS)), (LAST, last), (CELLS, bytes(CELL_ROW*modes.ENGINE_ACTORS))]


def code_parts():
    return [(HITLOG, hitlog_code()), (INPUT3, input_code()), (APPLY3, apply_code()), (DRAW, draw_code()),
            (ENTRY, entry_code()), (QUAD_LINK, quad_link_code())]


def quad_sites(data, base, target):
    """Addresses of `jal target` that follow `jal 12CCD0; nop` in data at base."""
    words = struct.unpack('<%dI' % (len(data)//4), data[:len(data)//4*4])
    first, second = (3 << 26) | (A(0x12CCD0) >> 2), (3 << 26) | (target >> 2)
    return [base+4*(i+2) for i in range(len(words)-2) if words[i] == first and words[i+1] == 0 and words[i+2] == second]


def ram_quad_sites(ram, target):
    import quad_viewports as views
    return quad_sites(bytes(ram[views.DRAW:views.DRAW+QUAD_SCAN]), views.DRAW, target)


def effective(settings):
    options = mod_settings.validate_settings({} if settings is None else settings)
    return dict(switch=SWITCH[options['lockon_attacker_switch']], marks=MARK_MODES[options['lockon_threat_marks']])


def wanted(settings):
    """False exactly when both settings hold their legacy values."""
    values = effective(settings)
    return bool(values['switch'] or values['marks'])


def installed(ram):
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    return u(CONTROL) == MAGIC and u(CONTROL+4) == u(core.ACTORS)


def _u(ram, p): return struct.unpack_from('<I', ram, p)[0]


def hook_words(ram):
    """The hook words an installed CONTROL implies: [(address, bytes)]."""
    import cpu_retaliation as retaliation
    import lockoff_target as off
    import lockon_select as sel
    words = [(off.INPUT, jump(INPUT3)), (off.APPLY, jump(APPLY3))]
    if _u(ram, CONTROL+FIELDS['acc_tail']): words.insert(0, (retaliation.ACCUMULATE, jump(HITLOG)))
    if _u(ram, CONTROL+FIELDS['render_tail']): words.append((sel.marker_site()[0], jal(ENTRY)))
    if _u(ram, CONTROL+FIELDS['quad_sites']): words += [(p, jal(QUAD_LINK)) for p in ram_quad_sites(ram, QUAD_LINK)]
    return words


def render_tails():
    import display_settings as display
    import guest_healthbars as bars
    import lockon_select as sel
    return (bars.DRAW, display.BAR_DRAW, sel.MARKER)


def validate_memory(ram):
    """Own code, CONTROL, hook words and tails. Never calls another module's validator."""
    import cpu_retaliation as retaliation
    import ffa_targeting as ffa
    if not installed(ram): raise ValueError('Attacker marks belong to another capture')
    for p, b in code_parts():
        if ram[p:p+len(b)] != b: raise ValueError(f'Attacker marks executable changed at {p:X}')
    switch, marks = _u(ram, CONTROL+FIELDS['switch']), _u(ram, CONTROL+FIELDS['marks'])
    acc, render, quad = (_u(ram, CONTROL+FIELDS[k]) for k in ('acc_tail', 'render_tail', 'quad_sites'))
    if switch not in SWITCH.values() or marks not in MARK_MODES.values() or quad not in (0, 2):
        raise ValueError('Attacker marks control changed')
    if acc not in (0, ffa.ACCUMULATE, TRAMPOLINE) or render not in (0,)+render_tails() or bool(render) != bool(marks):
        raise ValueError('Attacker marks control changed')
    if quad and not marks: raise ValueError('Attacker marks control changed')
    if acc == TRAMPOLINE:
        expected = trampoline(retaliation.accumulate_code()[:8])
        if ram[TRAMPOLINE:TRAMPOLINE+len(expected)] != expected: raise ValueError('Attacker marks executable changed')
    if quad and len(ram_quad_sites(ram, QUAD_LINK)) != 2: raise ValueError('Attacker marks quad view calls changed')
    for p, b in hook_words(ram):
        if ram[p:p+len(b)] != b: raise ValueError(f'Attacker marks hook changed at {p:X}')


def dependency_override(ram, address, expected):
    """Recognise the five (or seven) hook words inside other modules' strict validators."""
    import cpu_retaliation as retaliation
    import lockoff_target as off
    import lockon_select as sel
    import quad_viewports as views
    site = sel.marker_site()[0]
    in_quad = views.DRAW <= address < views.DRAW+QUAD_SCAN
    if address not in (off.INPUT, off.APPLY, site, retaliation.ACCUMULATE) and not in_quad: return expected
    if _u(ram, CONTROL) != MAGIC: return expected
    if address in (off.INPUT, off.APPLY):
        old = jump(sel.INPUT2 if address == off.INPUT else sel.APPLY2)
        if bytes(expected[:8]) != old: return expected
        validate_memory(ram)
        return jump(INPUT3 if address == off.INPUT else APPLY3)+bytes(expected[8:])
    if address == site:
        tail = _u(ram, CONTROL+FIELDS['render_tail'])
        if not tail or bytes(expected) != jal(tail): return expected
        validate_memory(ram)
        return jal(ENTRY)
    if address == retaliation.ACCUMULATE:
        tail = _u(ram, CONTROL+FIELDS['acc_tail'])
        first = jump(tail) if tail != TRAMPOLINE else bytes(ram[TRAMPOLINE:TRAMPOLINE+8])
        if not tail or bytes(expected[:8]) != first: return expected
        validate_memory(ram)
        return jump(HITLOG)+bytes(expected[8:])
    if not _u(ram, CONTROL+FIELDS['quad_sites']): return expected
    sites = set(ram_quad_sites(ram, QUAD_LINK))
    replaced = bytearray(expected)
    for p in quad_sites(bytes(expected), address, A(0x102708)):
        if p in sites: replaced[p-address:p-address+4] = jal(QUAD_LINK)
    if replaced == bytearray(expected): return expected
    validate_memory(ram)
    return bytes(replaced)


@modes.matching_install
def build_memory(ram, settings=None, source='<prepared>'):
    import cpu_retaliation as retaliation
    import ffa_targeting as ffa
    import four_player_mode
    import guest_killfeed as feed
    import lockoff_target as off
    import lockon_select as sel
    options = mod_settings.validate_settings({} if settings is None else settings)
    if not wanted(options): return dict(blocks=[])
    values = effective(options)
    if len(ram) != 0x8000000: raise ValueError('Attacker marks require full captured memory')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE), u(core.MODE+8), u(core.MODE+12)) != (1, manager, count):
        raise ValueError('Attacker marks require the prepared captured match')
    if not sel.installed(ram) or (u(off.CONTROL), u(off.CONTROL+4)) != (off.MAGIC, manager):
        raise ValueError('Attacker marks require target selection')
    off.validate_memory(ram); sel.validate_memory(ram)
    for hook, word in sel.hooks():
        if ram[hook:hook+8] != word: raise ValueError('Attacker marks require target selection')
    if (u(feed.CONTROL), u(feed.CONTROL+4), u(feed.CONTROL+8)) != (1, manager, count):
        raise ValueError('Attacker marks require the kill-feed clock of this match')
    if any(ram[BASE:END]): raise ValueError('Attacker marks reservation occupied')
    limitations = ['Only hits from enemies count, and only attributed ones: knock-down damage and projectiles hitting a '
                   'guarding fighter are not; those attacks still warn through the attack action and projectile rule.']
    parts = code_parts()
    hooks = [(off.INPUT, jump(INPUT3)), (off.APPLY, jump(APPLY3))]
    # H1: the accumulator's entry jump (dynamic NPC targeting in every mode), or its original prologue.
    entry = bytes(ram[retaliation.ACCUMULATE:retaliation.ACCUMULATE+8])
    acc_tail = 0
    if entry == jump(ffa.ACCUMULATE):
        acc_tail = ffa.ACCUMULATE
    elif entry == retaliation.accumulate_code()[:8] and (u(retaliation.CONTROL), u(retaliation.CONTROL+4)) == (1, manager):
        acc_tail = TRAMPOLINE; parts.append((TRAMPOLINE, trampoline(entry)))
    elif not any(ram[retaliation.CODE:retaliation.END]):
        limitations.append('No hit memory: warnings use attack actions and projectiles only.')
    else:
        raise ValueError('Unknown damage accumulator entry')
    if acc_tail: hooks.insert(0, (retaliation.ACCUMULATE, jump(HITLOG)))
    render_tail, quad = 0, 0
    if values['marks']:
        site = sel.marker_site()[0]
        tails = {jal(t): t for t in render_tails()}
        word = bytes(ram[site:site+4])
        if word not in tails: raise ValueError('Unknown overhead-bar display call')
        render_tail = tails[word]
        if render_tail == render_tails()[0]:
            limitations.append('Without the display settings program the marks are not drawn in one- and two-view '
                               'matches.')
        hooks.append((site, jal(ENTRY)))
        if four_player_mode.installed(ram):
            sites = ram_quad_sites(ram, A(0x102708))
            if len(sites) == 2:
                quad = 2; hooks += [(p, jal(QUAD_LINK)) for p in sites]
            else:
                limitations.append('Marks not drawn with a team assignment or three or four players.')
        limitations.append('The overhead bars stay absent with three or four players and in two-player matches '
                           'with a team assignment; the marks and the target indicator are drawn there.')
    if values['switch'] == SWITCH['when_hit']:
        limitations.append(f'Automatic switch: {AUTO_DAMAGE} HP from one enemy within 3 s, at most every 5 s, not while '
                           'your own target hit you in the last 2 s, while you attack, while unlocked or while another '
                           'request waits.')
    parts += data_blocks(manager, values['switch'], values['marks'], acc_tail, render_tail, quad)
    ordered = sorted(parts)
    if any(p+len(b) > n for (p, b), (n, _) in zip(ordered, ordered[1:])) or ordered[-1][0]+len(ordered[-1][1]) > END:
        raise ValueError('Attacker marks code overlaps')
    parts += hooks
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL, rows=ROWS, last=LAST, cells=CELLS,
                status='ATTACKER MARKS, ATTACK WARNING AND SWITCH TO ATTACKER',
                settings={k: options[k] for k in KEYS}, effective=dict(values, acc_tail=acc_tail,
                                                                     render_tail=render_tail, quad_sites=quad),
                blocks=[dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex()) for p, b in parts],
                limitations=limitations)
