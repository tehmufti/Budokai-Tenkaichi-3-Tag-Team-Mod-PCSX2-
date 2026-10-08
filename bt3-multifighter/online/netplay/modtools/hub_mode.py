"""In-level online hub ("Hub" match type): free roam with consent damage, respawn on KO and a scoreboard.

Installed offline as guest code into a prepared match (a kit-made netplay state or an ordinary prepared match).
Everything below runs inside the battle update on every peer from agreed inputs only, so lockstep keeps working;
the only per-machine part is the scoreboard drawing, which reads the hub record and writes GS packets.

Rules (one record, CONTROL + ROWS + PAIRS, updated every live battle update):
- consent damage: every pair of fighters starts non-hostile. An attributed hit from A on B records A's intent
  (ROWS[A].intent bit B, PAIRS[A][B] = clock) and is BLOCKED (no HP loss; the native hit reaction still plays)
  unless B has already tried to hit A (ROWS[B].intent bit A) - the hit that answers an attack is the first one that
  hurts. Both fighters' bits in CONTROL.open (an opt-in mask the kit may set) also make the pair hostile. A pair with
  no attributed attempt either way for decay_ticks calms down again (0 = never). Unattributed damage (projectiles
  the kill feed cannot attribute, the environment) only hurts a fighter that is engaged in at least one fight;
  flags bit0 (HP costs/recoil) and self damage always pass. A fighter in respawn grace takes no damage.
- respawn: the native KO (HP edge to 0, action 216 retained body) is kept; after respawn_ticks the body gets HP =
  max and down age 91, the stock get-up dispatcher stands it up (teammate_revive's commit), grace_ticks of
  protection follow. The victim's hostility is cleared both ways (no spawn camping). The native side-defeat
  predicate (A(0x20B878), already the team_defeat/FFA hook) answers 0 while the hub is installed, so a KO never
  decides the match; with Duel Time infinite (the kit's SCENE+0x10 word = 0) nothing else ends it.
- scoreboard: kills are credited to the last fighter who landed a hurting hit on the victim within 5 s
  (ROWS.last_attacker), deaths to the victim. TEXTS holds one composed line per fighter (name, K, D, W duel wins,
  AWAY/DOWN/DUEL/FIGHT) plus a header and a three-line event feed ('A VS B' when a pair becomes hostile, 'A KO B',
  'B IS DOWN', 'A VS B - DUEL', 'A WINS THE DUEL'), each shown 4 s. (guest_killfeed's own lines did not appear in
  the kit's own-view netplay renders, so the hub keeps its own feed.) Drawn bottom-left (board_x/board_y).
- kit commands (CONTROL.open / parked / duel, see C below): written by the lobby kit on every peer at the same
  frame (a frame-scheduled host write). duel = an accepted challenge fought in the level and watched by everyone.

Hooks (all existing mod words, chained, never a native byte):
  guest_killfeed.DAMAGE_NATIVE (8 B: `j PREVIOUS; nop` -> `j DAMAGE; nop`, the old 8 bytes move to TAIL)
  guest_killfeed.TICK_CALL     (4 B: `jal PREVIOUS` -> `jal TICK`, PREVIOUS kept in CONTROL.tick_previous)
  A(0x20B878) defeat entry     (8 B: `j TEAM_OR_FFA_DEFEAT; nop` -> `j DEFEAT; nop`, old 8 bytes in DEFEAT_TAIL)
  the world HUD pass's last call (guest_killfeed.WORLD's second jal; viewport_hud's wrapper in current builds)
                               (`jal X` -> `jal DRAW`, X kept in CONTROL.draw_previous and called first)
  spectator_takeover's option words (OPTIONS = magic, TAKE_ENABLED = 0): a dead hub player never adopts a CPU.
Guest rules: 16-byte aligned frames, no k0/k1, native addresses through A().
"""
from native_map import A
import struct
from prototype import Assembler
import fresh_team_combat as core
import guest_killfeed as feed
import cpu_retaliation as retaliation
import team_participation as part
import team_start_gate as start
import spectator_switch as spec
import spectator_takeover as takeover
from regional import SCISSOR_Y1, Y_ORIGIN

BASE, END = 0x06400000, 0x06408000
GATE, DAMAGE, TAIL, DEFEAT, DEFEAT_TAIL = BASE, BASE + 0x400, BASE + 0xC00, BASE + 0xD00, BASE + 0xE00
TICK, UPDATE, DRAW, NUMBER, NAME = BASE + 0x1000, BASE + 0x1400, BASE + 0x2800, BASE + 0x3400, BASE + 0x3600
CONTROL, ROWS, PAIRS, TEXTS, STATIC = BASE + 0x6000, BASE + 0x6100, BASE + 0x6400, BASE + 0x6800, BASE + 0x6C00
EVENT = BASE + 0x3800
MAGIC, VERSION, STRIDE, LINE, MAX_FIGHTERS = 0x31425548, 1, 64, 48, 12        # 'HUB1'
EVENT_LINES = (13, 14, 15)                                                      # TEXTS lines of the event feed
# CONTROL words the kit writes (frame-scheduled, the same frame on every peer): open, parked, duel.
#   open    bit i: fighter i opted in to free fighting (two opted-in fighters are hostile without hitting first)
#   parked  bit i: slot i has no player (left / not joined): takes and deals no damage, shown AWAY
#   duel    (a + 1) | (b + 1) << 8, 0 = none: an accepted challenge. a and b may only hurt each other and nobody
#           else may hurt them; the first KO between them ends it (ROWS.duel_wins of the winner + 1, duel = 0)
C = dict(magic=0, manager=4, count=8, version=12, tick_previous=16, damage_tail=20, defeat_tail=24, draw_previous=28,
         respawn=32, grace=36, decay=40, open=44, flags=48, board_x=52, board_y=56, clock=60, live=64,
         event0=68, credit=72, parked=76, duel=80, event1=84, event2=88, duel_seen=92,
         updates=128, passed=132, blocked=136, unknown_pass=140, unknown_block=144, consents=148, kills=152,
         respawns=156, decays=160, defeat_calls=164, fallback=168, grace_block=172, self_pass=176, draws=180,
         deaths=184, duel_block=188, duels=192, parked_block=196)
R = dict(actor=0, intent=4, state=8, respawn_at=12, grace_until=16, last_attacker=20, last_hit=24, kills=28,
         deaths=32, engaged=36, char=40, previous_engaged=44, duel_wins=48)
F_CONSENT, F_RESPAWN, F_BOARD = 1, 2, 4
KO, GETUP_AGE = 216, 91
DEFAULTS = dict(respawn_seconds=3.0, grace_seconds=2.0, decay_seconds=20.0, consent=True, respawn=True, board=True,
                credit_seconds=5.0, board_x=8, board_y=300)
HZ = 30
HEADER = b'HUB - HIT BACK TO FIGHT'
WHITE, RED, YELLOW, GREY, SHADOW = 0x80F0F0F0, 0x805060FF, 0x8040E0FF, 0x80A0A0A0, 0x80000000


def jump(p, link=False):
    return struct.pack('<2I', ((3 if link else 2) << 26) | (p >> 2), 0)


def counter(a, field, base=8, scratch=9):
    a.lw(scratch, base, C[field]); a.addiu(scratch, scratch, 1); a.sw(scratch, base, C[field])


SAVED = tuple(range(16, 24)) + (31,)


def frame(a, size=0x60):
    assert size % 16 == 0
    a.addiu(29, 29, -size)
    for i, r in enumerate(SAVED): a.i(63, r, 29, i * 8)


def unframe(a, size=0x60):
    for i, r in enumerate(SAVED): a.i(55, r, 29, i * 8)
    a.addiu(29, 29, size); a.jr()


def gate_code():
    """Leaf, t0..t3: v0 = 1 inside a live captured battle update (outnumbered's / teammate_revive's predicate)."""
    a = Assembler(GATE); core.gate(a, 'no')
    a.li(8, CONTROL); a.lw(9, 8); a.li(11, MAGIC); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, C['manager']); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, C['count']); a.branch(5, 9, 10, 'no')
    a.li(8, core.PAIR + 4); a.lw(9, 8); a.branch(5, 9, 0, 'no')
    a.li(8, part.CONTROL); a.lw(9, 8); a.addiu(11, 0, 5); a.branch(5, 9, 11, 'no')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'no'); a.lw(9, 8, 8); a.branch(5, 9, 10, 'no')
    a.li(8, start.CONTROL); a.lw(9, 8); a.branch(5, 9, 0, 'no')
    a.li(8, A(0x3337B8)); a.lw(9, 8); a.i(12, 9, 9, 0x3900); a.branch(5, 9, 0, 'no')
    a.li(8, A(0x3337C0)); a.lw(9, 8); a.addiu(11, 0, 1); a.branch(5, 9, 11, 'no')
    a.lw(9, 28, -22364); a.lw(9, 9, 628); a.branch(5, 9, 0, 'no')
    a.addiu(2, 0, 1); a.jr(); a.label('no'); a.move(2, 0); a.jr()
    data = a.finish(); assert len(data) <= DAMAGE - GATE; return data


def damage_code(feed_return):
    """At feed.DAMAGE_NATIVE: a0 defender, a1 damage, a2 flags; the kill feed's frame holds the victim index at
    sp+0xF0 and the attributed attacker index (or -1) at sp+0xF4. Function entry: only t0..t7 change; sp/ra are
    untouched on every exit; the blocked exit returns v0 = 0 (outnumbered's reviewed blocked exit)."""
    a = Assembler(DAMAGE)
    a.li(8, CONTROL)
    a.li(9, feed_return); a.branch(5, 31, 9, 'fallback')            # not the kill feed's own native call
    a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'pass')
    a.lw(9, 8, C['live']); a.branch(4, 9, 0, 'pass')
    a.lw(9, 8, C['manager']); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'pass')
    a.lw(9, 8, C['flags']); a.i(12, 9, 9, F_CONSENT); a.branch(4, 9, 0, 'pass')
    a.i(12, 9, 6, 1); a.branch(5, 9, 0, 'self_pass')                 # HP costs / recoil
    a.branch(6, 5, 0, 'pass')                                        # nothing to block
    a.lw(11, 29, 0xF0); a.lw(9, 8, C['count']); a.r(0x2B, 10, 11, 9); a.branch(4, 10, 0, 'pass')
    a.r(0, 12, 0, 11, 6); a.li(9, ROWS); a.r(0x21, 12, 12, 9)        # t4 = victim row
    a.lw(9, 12, R['actor']); a.branch(5, 9, 4, 'pass')
    a.lw(9, 12, R['grace_until']); a.lw(10, 8, C['clock']); a.r(0x2B, 13, 10, 9); a.branch(5, 13, 0, 'grace')
    a.lw(9, 8, C['parked']); a.r(6, 10, 11, 9); a.i(12, 10, 10, 1); a.branch(5, 10, 0, 'parked')
    a.lw(13, 29, 0xF4); a.branch(1, 13, 0, 'unknown')               # t5 = attacker (bltz -> unknown)
    a.lw(9, 8, C['count']); a.r(0x2B, 10, 13, 9); a.branch(4, 10, 0, 'unknown')
    a.branch(4, 13, 11, 'self_pass')
    a.lw(9, 8, C['parked']); a.r(6, 10, 13, 9); a.i(12, 10, 10, 1); a.branch(5, 10, 0, 'parked')
    # an accepted duel: its two fighters only hurt each other and nobody else touches them
    a.lw(25, 8, C['duel']); a.branch(4, 25, 0, 'consent')
    a.i(12, 24, 25, 0xFF); a.addiu(24, 24, -1); a.r(2, 25, 0, 25, 8); a.i(12, 25, 25, 0xFF); a.addiu(25, 25, -1)
    a.r(0x26, 9, 11, 24); a.i(11, 9, 9, 1); a.r(0x26, 10, 11, 25); a.i(11, 10, 10, 1); a.r(0x25, 9, 9, 10)  # victim in
    a.r(0x26, 14, 13, 24); a.i(11, 14, 14, 1); a.r(0x26, 10, 13, 25); a.i(11, 10, 10, 1); a.r(0x25, 14, 14, 10)
    a.branch(5, 9, 14, 'duel_block'); a.branch(5, 9, 0, 'hostile')
    a.label('consent')
    a.r(0, 14, 0, 13, 6); a.li(9, ROWS); a.r(0x21, 14, 14, 9)        # t6 = attacker row
    a.lw(9, 14, R['intent']); a.addiu(10, 0, 1); a.r(4, 10, 11, 10); a.r(0x25, 9, 9, 10); a.sw(9, 14, R['intent'])
    a.r(0, 9, 0, 13, 4); a.r(0x21, 9, 9, 11); a.r(0, 9, 0, 9, 2); a.li(10, PAIRS); a.r(0x21, 9, 9, 10)
    a.lw(10, 8, C['clock']); a.sw(10, 9, 0)                           # PAIRS[k*16+v] = clock
    a.lw(9, 12, R['intent']); a.r(6, 9, 13, 9); a.i(12, 9, 9, 1); a.branch(5, 9, 0, 'hostile')
    a.lw(9, 8, C['open']); a.r(6, 10, 13, 9); a.r(6, 9, 11, 9); a.r(0x24, 9, 9, 10); a.i(12, 9, 9, 1)
    a.branch(5, 9, 0, 'hostile')
    counter(a, 'blocked'); a.jump('blocked')
    a.label('hostile'); a.sw(13, 12, R['last_attacker']); a.lw(10, 8, C['clock']); a.sw(10, 12, R['last_hit'])
    counter(a, 'passed'); a.jump('pass')
    a.label('unknown')
    a.lw(25, 8, C['duel']); a.branch(4, 25, 0, 'unknown_consent')    # a duelist: its opponent's shot
    a.i(12, 24, 25, 0xFF); a.addiu(24, 24, -1); a.r(2, 25, 0, 25, 8); a.i(12, 25, 25, 0xFF); a.addiu(25, 25, -1)
    a.branch(4, 11, 24, 'unknown_pass'); a.branch(4, 11, 25, 'unknown_pass')
    a.label('unknown_consent'); a.lw(9, 12, R['engaged']); a.branch(4, 9, 0, 'unknown_block')
    a.label('unknown_pass'); counter(a, 'unknown_pass'); a.jump('pass')
    a.label('unknown_block'); counter(a, 'unknown_block'); a.jump('blocked')
    a.label('grace'); counter(a, 'grace_block'); a.jump('blocked')
    a.label('parked'); counter(a, 'parked_block'); a.jump('blocked')
    a.label('duel_block'); counter(a, 'duel_block'); a.jump('blocked')
    a.label('self_pass'); counter(a, 'self_pass'); a.jump('pass')
    a.label('fallback'); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'pass'); counter(a, 'fallback')
    a.jump('pass')
    a.label('blocked'); a.move(2, 0); a.jr()
    a.label('pass'); a.jump(TAIL)
    data = a.finish(); assert len(data) <= TAIL - DAMAGE, hex(len(data)); return data


def defeat_code():
    """At A(0x20B878) (side-defeat predicate): 0 while the hub owns this match, else the previous hook."""
    a = Assembler(DEFEAT)
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'native')
    a.lw(9, 8, C['manager']); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'native')
    a.lw(9, 8, C['flags']); a.i(12, 9, 9, F_RESPAWN); a.branch(4, 9, 0, 'native')
    counter(a, 'defeat_calls'); a.move(2, 0); a.jr()
    a.label('native'); a.jump(DEFEAT_TAIL)
    data = a.finish(); assert len(data) <= DEFEAT_TAIL - DEFEAT; return data


# Every register a caller may expect back, k0/k1 excluded (kernel scratch: never touched by guest code).
ALL = tuple(range(1, 26)) + (28, 30)


def save_all(a):
    for i, r in enumerate(ALL): a.i(63, r, 29, i * 8)


def restore_all(a):
    for i, r in enumerate(ALL): a.i(55, r, 29, i * 8)


def tick_code():
    """At feed.TICK_CALL (once per battle update): the previous target first with the native registers (its v0
    kept), then UPDATE. outnumbered.tick_code's frame shape without k0/k1."""
    a = Assembler(TICK); a.addiu(29, 29, -0x100); save_all(a); a.i(63, 31, 29, 0xE8)
    restore_all(a); a.li(25, CONTROL); a.lw(25, 25, C['tick_previous']); a.r(9, 31, 25); a.emit(0)
    save_all(a); a.call(UPDATE)
    restore_all(a); a.i(55, 31, 29, 0xE8); a.addiu(29, 29, 0x100); a.jr()
    data = a.finish(); assert len(data) <= UPDATE - TICK; return data


def number_code():
    """Leaf: a0 unsigned value (clamped to 999), a1 buffer -> v0 address after the digits (no terminator)."""
    a = Assembler(NUMBER); a.addiu(8, 0, 999); a.r(0x2B, 9, 8, 4); a.branch(4, 9, 0, 'bounded'); a.move(4, 8)
    a.label('bounded'); a.move(2, 5); a.move(11, 0)
    for divisor in (100, 10, 1):
        a.addiu(8, 0, divisor); a.r(27, 0, 4, 8); a.r(18, 9, 0); a.r(16, 4, 0)
        if divisor != 1:
            a.r(0x25, 10, 11, 9); a.branch(4, 10, 0, f'skip{divisor}')
        a.addiu(11, 0, 1); a.addiu(9, 9, 48); a.i(40, 9, 2, 0); a.addiu(2, 2, 1)
        a.label(f'skip{divisor}')
    a.jr()
    data = a.finish(); assert len(data) <= NAME - NUMBER; return data


def name_code():
    """Leaf: a0 character id, a1 buffer, a2 max chars -> v0 address after the copied name (no terminator)."""
    a = Assembler(NAME); a.move(2, 5)
    a.i(11, 8, 4, 161); a.branch(4, 8, 0, 'unknown')
    a.r(0, 8, 0, 4, 7); a.li(9, feed.NAMES); a.r(0x2D, 8, 8, 9); a.jump('copy')
    a.label('unknown'); a.li(8, STATIC + 64)
    a.label('copy'); a.branch(6, 6, 0, 'done')
    a.i(36, 9, 8, 0); a.branch(4, 9, 0, 'done'); a.i(40, 9, 2, 0)
    a.addiu(8, 8, 1); a.addiu(2, 2, 1); a.addiu(6, 6, -1); a.jump('copy')
    a.label('done'); a.jr()
    data = a.finish(); assert len(data) <= BASE + 0x3800 - NAME; return data


def put(a, text, reg=2):
    for ch in text:
        a.addiu(8, 0, ch); a.i(40, 8, reg, 0); a.addiu(reg, reg, 1)


def event_code():
    """Leaf, t0/t1: push the event feed up one line (the oldest drops) -> v0 = the newest line, shown 4 s."""
    a = Assembler(EVENT); a.li(8, TEXTS + EVENT_LINES[0] * LINE)
    for off in range(0, 2 * LINE, 4):
        a.lw(9, 8, off + LINE); a.sw(9, 8, off)
    a.li(8, CONTROL)
    a.lw(9, 8, C['event1']); a.sw(9, 8, C['event0']); a.lw(9, 8, C['event2']); a.sw(9, 8, C['event1'])
    a.lw(9, 8, C['clock']); a.addiu(9, 9, 4 * HZ); a.sw(9, 8, C['event2'])
    a.li(2, TEXTS + EVENT_LINES[2] * LINE); a.jr()
    data = a.finish(); assert len(data) <= BASE + 0x3C00 - EVENT; return data


def duel_pair(a, fail, scratch=8):
    """t8 = duelist a, t9 = duelist b from CONTROL.duel (s0 = CONTROL); branch to fail when there is no duel."""
    a.lw(25, 16, C['duel']); a.branch(4, 25, 0, fail)
    a.i(12, 24, 25, 0xFF); a.addiu(24, 24, -1); a.r(2, 25, 0, 25, 8); a.i(12, 25, 25, 0xFF); a.addiu(25, 25, -1)


def update_code():
    """Once per live battle update (after the previous tick target): hostility decay and engaged masks, the
    death/respawn machine, then the scoreboard lines. Outside a live update only CONTROL.live drops to 0."""
    a = Assembler(UPDATE); frame(a, 0x70)
    a.call(GATE); a.li(16, CONTROL); a.branch(5, 2, 0, 'live')
    a.sw(0, 16, C['live']); a.jump('return')
    a.label('live'); a.addiu(8, 0, 1); a.sw(8, 16, C['live'])
    counter(a, 'updates', 16); counter(a, 'clock', 16)
    a.lw(17, 16, C['count'])
    # a newly accepted duel (the kit's frame-scheduled write): 'A VS B - DUEL'
    a.lw(8, 16, C['duel']); a.lw(9, 16, C['duel_seen']); a.branch(4, 8, 9, 'pass1'); a.sw(8, 16, C['duel_seen'])
    duel_pair(a, 'pass1'); a.move(22, 24); a.move(23, 25)
    a.r(0x2B, 8, 22, 17); a.branch(4, 8, 0, 'pass1'); a.r(0x2B, 8, 23, 17); a.branch(4, 8, 0, 'pass1')
    a.call(EVENT); a.move(5, 2); a.r(0, 8, 0, 22, 6); a.li(9, ROWS); a.r(0x21, 8, 8, 9); a.lw(4, 8, R['char'])
    a.addiu(6, 0, 18); a.call(NAME); put(a, b' VS '); a.move(5, 2)
    a.r(0, 8, 0, 23, 6); a.li(9, ROWS); a.r(0x21, 8, 8, 9); a.lw(4, 8, R['char']); a.addiu(6, 0, 18); a.call(NAME)
    put(a, b' - DUEL'); a.i(40, 0, 2, 0)
    a.label('pass1')
    # ---- pass 1: decay, engaged masks, new-fight events (s2 = k, s3 = row k, s4 = v) ------------------------------
    a.move(18, 0); a.li(19, ROWS)
    a.label('k_loop')
    a.move(21, 0); a.move(20, 0)                                       # s5 = engaged, s4 = v
    a.lw(8, 16, C['parked']); a.r(6, 8, 18, 8); a.i(12, 8, 8, 1); a.branch(5, 8, 0, 'k_store')
    a.label('v_loop'); a.branch(4, 20, 18, 'v_next')
    a.lw(8, 16, C['parked']); a.r(6, 8, 20, 8); a.i(12, 8, 8, 1); a.branch(5, 8, 0, 'v_next')
    a.lw(8, 19, R['intent']); a.r(6, 8, 20, 8); a.i(12, 8, 8, 1)       # t0 = k tried v
    a.r(0, 9, 0, 20, 6); a.li(10, ROWS); a.r(0x21, 22, 9, 10)          # s6 = row v
    a.lw(9, 22, R['intent']); a.r(6, 9, 18, 9); a.i(12, 9, 9, 1)       # t1 = v tried k
    a.r(0x25, 10, 8, 9); a.branch(4, 10, 0, 'open_check')
    a.lw(10, 16, C['decay']); a.branch(4, 10, 0, 'no_decay')
    # last attempt either way: PAIRS[k][v], PAIRS[v][k]
    a.r(0, 11, 0, 18, 4); a.r(0x21, 11, 11, 20); a.r(0, 11, 0, 11, 2); a.li(12, PAIRS); a.r(0x21, 11, 11, 12)
    a.lw(11, 11, 0)
    a.r(0, 12, 0, 20, 4); a.r(0x21, 12, 12, 18); a.r(0, 12, 0, 12, 2); a.li(13, PAIRS); a.r(0x21, 12, 12, 13)
    a.lw(12, 12, 0)
    a.r(0x2B, 13, 11, 12); a.branch(4, 13, 0, 'latest'); a.move(11, 12)
    a.label('latest'); a.lw(12, 16, C['clock']); a.r(0x23, 12, 12, 11); a.r(0x2B, 13, 10, 12)
    a.branch(4, 13, 0, 'no_decay')
    # calm down: clear both intents of this pair
    a.lw(11, 19, R['intent']); a.addiu(12, 0, 1); a.r(4, 12, 20, 12); a.r(0x27, 12, 12, 0); a.r(0x24, 11, 11, 12)
    a.sw(11, 19, R['intent'])
    a.lw(11, 22, R['intent']); a.addiu(12, 0, 1); a.r(4, 12, 18, 12); a.r(0x27, 12, 12, 0); a.r(0x24, 11, 11, 12)
    a.sw(11, 22, R['intent'])
    counter(a, 'decays', 16); a.jump('v_next')
    a.label('no_decay'); a.r(0x24, 10, 8, 9); a.branch(5, 10, 0, 'engaged')
    a.label('open_check')
    a.lw(10, 16, C['open']); a.r(6, 11, 18, 10); a.r(6, 10, 20, 10); a.r(0x24, 10, 10, 11); a.i(12, 10, 10, 1)
    a.branch(4, 10, 0, 'v_next')
    a.label('engaged'); a.addiu(8, 0, 1); a.r(4, 8, 20, 8); a.r(0x25, 21, 21, 8)
    a.label('v_next'); a.addiu(20, 20, 1); a.branch(5, 20, 17, 'v_loop')
    a.label('k_store'); a.sw(21, 19, R['engaged'])
    # new fights (bit v set now, not last update, v > k): one event line 'K VS V'
    a.lw(8, 19, R['previous_engaged']); a.r(0x27, 8, 8, 0); a.r(0x24, 8, 8, 21); a.sw(21, 19, R['previous_engaged'])
    a.addiu(9, 18, 1); a.r(6, 8, 9, 8); a.branch(4, 8, 0, 'k_next')    # bits above k only
    a.move(20, 9)
    a.label('first_new'); a.i(12, 10, 8, 1); a.branch(5, 10, 0, 'have_new'); a.r(2, 8, 0, 8, 1)
    a.addiu(20, 20, 1); a.jump('first_new')
    a.label('have_new'); counter(a, 'consents', 16)
    a.call(EVENT); a.move(5, 2); a.lw(4, 19, R['char']); a.addiu(6, 0, 18); a.call(NAME)
    put(a, b' VS ')
    a.move(5, 2); a.r(0, 8, 0, 20, 6); a.li(9, ROWS); a.r(0x21, 8, 8, 9); a.lw(4, 8, R['char'])
    a.addiu(6, 0, 18); a.call(NAME); a.i(40, 0, 2, 0)
    a.label('k_next'); a.addiu(18, 18, 1); a.addiu(19, 19, STRIDE); a.branch(5, 18, 17, 'k_loop')
    # ---- pass 2: deaths and respawns (s2 = i, s3 = row, s4 = actor, s5 = HP row) ----------------------------------
    a.move(18, 0); a.li(19, ROWS)
    a.label('i_loop')
    a.li(8, core.POINTERS); a.r(0, 9, 0, 18, 2); a.r(0x21, 8, 8, 9); a.lw(20, 8)
    a.lw(8, 19, R['actor']); a.branch(5, 8, 20, 'i_next'); a.branch(4, 20, 0, 'i_next')
    a.move(4, 20); a.call(feed.ROW); a.branch(4, 2, 0, 'i_next'); a.move(21, 2); a.sw(3, 19, R['char'])
    a.lw(8, 19, R['state']); a.branch(5, 8, 0, 'down')
    a.lw(8, 21, 0); a.branch(7, 8, 0, 'i_next')                         # alive and HP > 0
    # alive -> down: deaths, credit, hostility cleared both ways
    a.addiu(8, 0, 1); a.sw(8, 19, R['state'])
    a.lw(8, 16, C['clock']); a.lw(9, 16, C['respawn']); a.r(0x21, 8, 8, 9); a.sw(8, 19, R['respawn_at'])
    a.lw(8, 19, R['deaths']); a.addiu(8, 8, 1); a.sw(8, 19, R['deaths']); counter(a, 'deaths', 16)
    a.addiu(22, 0, -1)                                                  # s6 = credited killer or -1
    a.lw(8, 19, R['last_attacker']); a.branch(1, 8, 0, 'uncredited'); a.r(0x2B, 9, 8, 17); a.branch(4, 9, 0, 'uncredited')
    a.branch(4, 8, 18, 'uncredited')
    a.lw(9, 16, C['clock']); a.lw(10, 19, R['last_hit']); a.r(0x23, 9, 9, 10); a.lw(10, 16, C['credit'])
    a.r(0x2B, 9, 10, 9); a.branch(5, 9, 0, 'uncredited')
    a.move(22, 8)
    a.r(0, 9, 0, 8, 6); a.li(10, ROWS); a.r(0x21, 9, 9, 10); a.lw(10, 9, R['kills']); a.addiu(10, 10, 1)
    a.sw(10, 9, R['kills']); counter(a, 'kills', 16)
    a.label('uncredited'); a.addiu(8, 0, -1); a.sw(8, 19, R['last_attacker'])
    a.sw(0, 19, R['intent']); a.addiu(8, 0, 1); a.r(4, 8, 18, 8); a.r(0x27, 8, 8, 0)
    a.move(9, 0); a.li(10, ROWS)
    a.label('clear'); a.lw(11, 10, R['intent']); a.r(0x24, 11, 11, 8); a.sw(11, 10, R['intent'])
    a.addiu(9, 9, 1); a.addiu(10, 10, STRIDE); a.branch(5, 9, 17, 'clear')
    # event: 'KILLER KO VICTIM' or 'VICTIM IS DOWN'
    a.call(EVENT); a.move(5, 2); a.branch(1, 22, 0, 'down_event')
    a.r(0, 8, 0, 22, 6); a.li(9, ROWS); a.r(0x21, 8, 8, 9); a.lw(4, 8, R['char']); a.addiu(6, 0, 18); a.call(NAME)
    put(a, b' KO '); a.move(5, 2); a.lw(4, 19, R['char']); a.addiu(6, 0, 18); a.call(NAME); a.i(40, 0, 2, 0)
    a.jump('duel_check')
    a.label('down_event'); a.lw(4, 19, R['char']); a.addiu(6, 0, 18); a.call(NAME); put(a, b' IS DOWN')
    a.i(40, 0, 2, 0)
    # a duelist's KO ends the duel; the partner's KO wins it
    a.label('duel_check'); duel_pair(a, 'i_next')
    a.branch(4, 18, 24, 'duel_a'); a.branch(5, 18, 25, 'i_next'); a.move(23, 24); a.jump('duel_end')
    a.label('duel_a'); a.move(23, 25)                                   # s7 = the other duelist
    a.label('duel_end'); a.sw(0, 16, C['duel']); counter(a, 'duels', 16); a.branch(5, 22, 23, 'i_next')
    a.r(0, 8, 0, 23, 6); a.li(9, ROWS); a.r(0x21, 23, 8, 9); a.lw(8, 23, R['duel_wins']); a.addiu(8, 8, 1)
    a.sw(8, 23, R['duel_wins'])
    a.call(EVENT); a.move(5, 2); a.lw(4, 23, R['char']); a.addiu(6, 0, 18); a.call(NAME); put(a, b' WINS THE DUEL')
    a.i(40, 0, 2, 0)
    a.jump('i_next')
    a.label('down')
    a.lw(8, 20, 0x948); a.addiu(9, 0, KO); a.branch(4, 8, 9, 'ko_body')
    a.lw(9, 21, 0); a.branch(6, 9, 0, 'i_next')                         # still dying (flight, fall)
    a.sw(0, 19, R['state']); a.jump('i_next')                          # stood up some other way
    a.label('ko_body'); a.lw(8, 16, C['flags']); a.i(12, 8, 8, F_RESPAWN); a.branch(4, 8, 0, 'i_next')
    a.lw(8, 16, C['clock']); a.lw(9, 19, R['respawn_at']); a.r(0x2B, 10, 8, 9); a.branch(5, 10, 0, 'i_next')
    a.lw(8, 21, 4); a.branch(7, 8, 0, 'max_ok'); a.addiu(8, 0, 1)
    a.label('max_ok'); a.sw(8, 21, 0); a.addiu(8, 0, GETUP_AGE); a.sw(8, 20, 0x964)
    a.sw(0, 19, R['state']); a.lw(8, 16, C['clock']); a.lw(9, 16, C['grace']); a.r(0x21, 8, 8, 9)
    a.sw(8, 19, R['grace_until']); counter(a, 'respawns', 16)
    a.label('i_next'); a.addiu(18, 18, 1); a.addiu(19, 19, STRIDE); a.branch(5, 18, 17, 'i_loop')
    # ---- pass 3: scoreboard lines: NAME K<k> D<d> [FIGHT|DOWN] ----------------------------------------------------
    a.move(18, 0); a.li(19, ROWS); a.li(20, TEXTS + LINE)
    a.label('line')
    a.move(5, 20); a.lw(4, 19, R['char']); a.addiu(6, 0, 14); a.call(NAME)
    put(a, b' K'); a.lw(4, 19, R['kills']); a.move(5, 2); a.call(NUMBER)
    put(a, b' D'); a.lw(4, 19, R['deaths']); a.move(5, 2); a.call(NUMBER)
    a.lw(4, 19, R['duel_wins']); a.branch(4, 4, 0, 'no_wins'); put(a, b' W'); a.move(5, 2); a.call(NUMBER)
    a.label('no_wins')
    a.lw(8, 16, C['parked']); a.r(6, 8, 18, 8); a.i(12, 8, 8, 1); a.branch(4, 8, 0, 'present')
    put(a, b' AWAY'); a.jump('terminate')
    a.label('present'); a.lw(8, 19, R['state']); a.branch(4, 8, 0, 'not_down'); put(a, b' DOWN'); a.jump('terminate')
    a.label('not_down'); duel_pair(a, 'no_duel')
    a.branch(4, 18, 24, 'dueling'); a.branch(5, 18, 25, 'no_duel')
    a.label('dueling'); put(a, b' DUEL'); a.jump('terminate')
    a.label('no_duel'); a.lw(8, 19, R['engaged']); a.branch(4, 8, 0, 'terminate'); put(a, b' FIGHT')
    a.label('terminate'); a.i(40, 0, 2, 0)
    a.addiu(18, 18, 1); a.addiu(19, 19, STRIDE); a.addiu(20, 20, LINE); a.branch(5, 18, 17, 'line')
    a.label('return'); unframe(a, 0x70)
    data = a.finish(); assert len(data) <= DRAW - UPDATE, hex(len(data)); return data


def draw_code():
    """Render pass (replaces the world HUD pass's last call): the previous call first, then - in the sole full-width
    world viewport, exactly the kill feed's own placement test - the header, one line per fighter and the event
    line. Reads the hub record only (plus CONTROL.draws, an unhashed render counter)."""
    a = Assembler(DRAW); frame(a, 0x60)
    a.li(25, CONTROL); a.lw(25, 25, C['draw_previous']); a.r(9, 31, 25); a.emit(0)
    a.li(16, CONTROL); a.lw(8, 16); a.li(9, MAGIC); a.branch(5, 8, 9, 'done')
    a.lw(8, 16, C['live']); a.branch(4, 8, 0, 'done')
    a.lw(8, 16, C['flags']); a.i(12, 8, 8, F_BOARD); a.branch(4, 8, 0, 'done')
    a.lw(8, 28, -22176); a.branch(4, 8, 0, 'done')
    a.lw(9, 8, 512); a.branch(5, 9, 0, 'done')
    a.lw(9, 8, 516); a.i(11, 10, 9, 250); a.branch(5, 10, 0, 'done')
    a.i(11, 10, 9, 512); a.branch(4, 10, 0, 'done')
    a.lw(9, 8, 520); a.branch(5, 9, 0, 'done')
    a.lw(9, 8, 524); a.addiu(10, 0, SCISSOR_Y1); a.branch(5, 9, 10, 'done')
    counter(a, 'draws', 16)
    a.lw(17, 16, C['board_y'])                                          # s1 = design row
    a.li(18, STATIC); a.li(19, YELLOW); a.call('line'); a.addiu(17, 17, 12)
    a.move(20, 0); a.li(21, ROWS); a.li(22, TEXTS + LINE)
    a.label('row'); a.lw(8, 16, C['count']); a.branch(4, 20, 8, 'event')
    a.move(18, 22); a.li(19, WHITE)
    a.lw(8, 21, R['engaged']); a.branch(4, 8, 0, 'not_fighting'); a.li(19, RED)
    a.label('not_fighting'); duel_pair(a, 'no_duel')
    a.branch(4, 20, 24, 'dueling'); a.branch(5, 20, 25, 'no_duel')
    a.label('dueling'); a.li(19, YELLOW)
    a.label('no_duel'); a.lw(8, 21, R['state']); a.branch(5, 8, 0, 'grey')
    a.lw(8, 16, C['parked']); a.r(6, 8, 20, 8); a.i(12, 8, 8, 1); a.branch(4, 8, 0, 'colored')
    a.label('grey'); a.li(19, GREY)
    a.label('colored'); a.call('line'); a.addiu(17, 17, 10)
    a.addiu(20, 20, 1); a.addiu(21, 21, STRIDE); a.addiu(22, 22, LINE); a.jump('row')
    a.label('event'); a.addiu(17, 17, 2)
    for n, (line, field) in enumerate(zip(EVENT_LINES, ('event0', 'event1', 'event2'))):
        a.lw(8, 16, C['clock']); a.lw(9, 16, C[field]); a.r(0x2B, 10, 8, 9); a.branch(4, 10, 0, f'old{n}')
        a.li(18, TEXTS + line * LINE); a.li(19, WHITE); a.call('line'); a.addiu(17, 17, 10)
        a.label(f'old{n}')
    a.label('done'); unframe(a, 0x60)
    # 'line': s2 string, s1 design row, s3 color; a black shadow one pixel down-right first.
    a.label('line'); a.addiu(29, 29, -0x10); a.i(63, 31, 29, 0)
    for shadow in (1, 0):
        a.move(4, 18); a.lw(5, 16, C['board_x']); a.addiu(5, 5, 1792 + shadow); a.r(0, 5, 0, 5, 4)
        a.addiu(6, 17, Y_ORIGIN + shadow); a.r(0, 6, 0, 6, 4)
        if shadow: a.li(7, SHADOW)
        else: a.move(7, 19)
        a.call(feed.TEXT)
    a.i(55, 31, 29, 0); a.addiu(29, 29, 0x10); a.jr()
    data = a.finish(); assert len(data) <= NUMBER - DRAW, hex(len(data)); return data


def static_data():
    data = bytearray(128)
    data[:len(HEADER)] = HEADER
    unknown = b'FIGHTER'
    data[64:64 + len(unknown)] = unknown
    return bytes(data)


def config(settings=None):
    s = dict(DEFAULTS); s.update(settings or {})
    flags = (F_CONSENT if s['consent'] else 0) | (F_RESPAWN if s['respawn'] else 0) | (F_BOARD if s['board'] else 0)
    return dict(respawn=max(1, round(s['respawn_seconds'] * HZ)), grace=round(s['grace_seconds'] * HZ),
                decay=round(s['decay_seconds'] * HZ), open=int(s.get('open', 0)), flags=flags,
                credit=round(s['credit_seconds'] * HZ), board_x=int(s['board_x']), board_y=int(s['board_y']))


def world_last_call(ram):
    """(address, target) of the world HUD pass's last `jal` (guest_killfeed.WORLD's second call)."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    import guest_healthbars as bars
    calls = [p for p in range(feed.WORLD, feed.WORLD + 0x30, 4) if u(p) >> 26 == 3]
    if len(calls) != 2 or u(calls[0]) != (3 << 26) | (bars.CODE >> 2):
        raise ValueError('Unexpected kill-feed world pass')
    return calls[1], (u(calls[1]) & 0x3FFFFFF) << 2


def build_memory(ram, settings=None, source='<prepared>'):
    """Guarded blocks [(address, expected bytes, new bytes)] installing the hub into a captured live match."""
    if len(ram) != 0x8000000: raise ValueError('Requires 128 MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE + 4)
    if u(core.MODE) != 1 or u(core.MODE + 8) != manager or not 4 <= count <= MAX_FIGHTERS:
        raise ValueError('Requires an active captured match')
    if any(ram[BASE:END]): raise ValueError('Hub reservation occupied')
    if u(feed.CONTROL) != 1 or u(feed.CONTROL + 4) != manager: raise ValueError('Kill feed not installed')
    feed_return = retaliation.feed_return()
    if u(feed_return - 8) != (3 << 26) | (feed.DAMAGE_NATIVE >> 2): raise ValueError('Kill-feed native call moved')
    first = bytes(ram[feed.DAMAGE_NATIVE:feed.DAMAGE_NATIVE + 8])
    if u(feed.DAMAGE_NATIVE) >> 26 != 2 or u(feed.DAMAGE_NATIVE + 4) != 0:
        raise ValueError('Unexpected kill-feed native-damage slot')
    tick_call = u(feed.TICK_CALL)
    if tick_call >> 26 != 3: raise ValueError('Unexpected deferred damage call')
    defeat = A(0x20B878)
    old_defeat = bytes(ram[defeat:defeat + 8])
    if u(defeat) >> 26 != 2 or u(defeat + 4) != 0: raise ValueError('Defeat predicate is not hooked by the mod')
    if u(part.CONTROL) != 5 or u(part.CONTROL + 4) != manager: raise ValueError('Participation record missing')
    world_call, world_previous = world_last_call(ram)
    cfg = config(settings)
    control = bytearray(0x100)
    for k, v in dict(magic=MAGIC, manager=manager, count=count, version=VERSION,
                     tick_previous=(tick_call & 0x3FFFFFF) << 2, damage_tail=TAIL, defeat_tail=DEFEAT_TAIL,
                     draw_previous=world_previous, **cfg).items():
        struct.pack_into('<I', control, C[k], v & 0xFFFFFFFF)
    rows = bytearray(STRIDE * MAX_FIGHTERS)
    for i in range(count):
        actor = u(core.POINTERS + 4 * i)
        if not 0x100000 <= actor < 0x8000000 - 0x1600 or u(actor) != i: raise ValueError(f'Actor {i} mismatch')
        struct.pack_into('<I', rows, i * STRIDE + R['actor'], actor)
        struct.pack_into('<i', rows, i * STRIDE + R['last_attacker'], -1)
    pieces = [(GATE, gate_code()), (DAMAGE, damage_code(feed_return)), (TAIL, first + jump(feed.DAMAGE_NATIVE + 8)),
              (DEFEAT, defeat_code()), (DEFEAT_TAIL, old_defeat + jump(defeat + 8)), (TICK, tick_code()),
              (UPDATE, update_code()), (DRAW, draw_code()), (NUMBER, number_code()), (NAME, name_code()),
              (EVENT, event_code()),
              (CONTROL, bytes(control)), (ROWS, bytes(rows)), (STATIC, static_data()),
              (feed.DAMAGE_NATIVE, jump(DAMAGE)), (feed.TICK_CALL, struct.pack('<I', (3 << 26) | (TICK >> 2))),
              (defeat, jump(DEFEAT)), (world_call, struct.pack('<I', (3 << 26) | (DRAW >> 2)))]
    if u(spec.CONTROL) == spec.MAGIC:
        pieces.append((spec.CONTROL + takeover.OPTIONS, struct.pack('<2I', takeover.OPTION_MAGIC, 0)))
    blocks = [(p, bytes(ram[p:p + len(d)]), d) for p, d in pieces]
    spans = sorted((p, p + len(d)) for p, _, d in blocks)
    assert all(e <= s for (_, e), (s, _) in zip(spans, spans[1:])), 'overlapping hub blocks'
    return blocks


def telemetry(read):
    """read(address, length) -> bytes; returns the CONTROL counters and one dict per fighter row."""
    c = read(CONTROL, 0x100)
    out = {k: struct.unpack_from('<I', c, v)[0] for k, v in C.items()}
    count = min(out['count'], MAX_FIGHTERS)
    rows = read(ROWS, STRIDE * count) if count else b''
    out['rows'] = [{k: struct.unpack_from('<i', rows, i * STRIDE + v)[0] for k, v in R.items()} for i in range(count)]
    texts = read(TEXTS, LINE * 16)
    out['lines'] = [texts[i * LINE:(i + 1) * LINE].split(b'\0')[0].decode('ascii', 'replace') for i in range(16)]
    return out
