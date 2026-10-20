"""Fighter Gauntlet guest program: waves of enemies in one continuous match.

Installed only for a gauntlet match (fresh_team_trainer, after the story runtime the gauntlet is built on). It chains
the once-per-battle-update call (guest_killfeed.TICK_CALL, as hub_mode/outnumbered do) and the world draw. A match
without a gauntlet installs nothing.

Per update (UPDATE, never while paused or held; 16-byte frames, no k0/k1):
- COPIER: installs a host-published reload job (data packet: address, old bytes, new bytes) into the extra reload
  job regions WITHOUT a combat hold. The EE validates every destination against a fixed allowlist (io, stage, commit,
  retire workspaces and the exact staging getter word) and every expected old byte before the first store, and only
  while every reload workspace is dormant and nothing holds combat. PINE never writes code.
- RUNNER: calls the installed job entry (io: once per update until its status is final, behind the native loader
  idle gate; stage/commit/retire: once), then acknowledges the job's own status.
- SLOT GATES: GATE[p] = GATE_MAGIC + generation while enemy extra p is consumed, hidden, KO'd (action 216, HP 0)
  for two updates; 0 otherwise. Every job body re-checks it (extra_reload_quiet.owner_guard), so a slot that came
  back is never rebuilt.
- WAVES (the state machine, see wave_code): KO tracking, the 5-second body removal, the 15-second countdown, the
  player HP refill when the next wave starts, admission of the next wave, the end of the run.

Between waves (COUNTDOWN) the player team moves freely. The native opponent mirror (1DBCE0) copies "my opponent has
no HP" (1DC320) into actor flag 177, and the pad reader (1D4738) then clears every button and centres both sticks:
the native "the round is won" freeze. BREAK answers that one call with "alive" for a player-team fighter during the
countdown, so humans fly, dash, guard, charge and revive; the enemy side (only KO'd, removed or loading bodies) is
story-protected meanwhile, so nothing they do lands. Each entrant is placed relative to the team (PLACE).
"""
import struct

from native_map import A, ACTOR_HZ, CRC, SERIAL
from prototype import Assembler
import fresh_team_combat as core
import guest_killfeed as feed
import native_preparation as native
import team_participation as part
import extra_reload_quiet as runner_module
import extra_reload_service as io
import extra_reload_stage as stage
import extra_reload_commit as commit
import extra_reload_retire as retire

BASE, END = 0x06200000, 0x06260000
TICK, UPDATE, WAVE, ADMIT = BASE, BASE + 0x400, BASE + 0x1000, BASE + 0x5000
COPIER, RUNNER, DRAW = BASE + 0x6000, BASE + 0x6800, BASE + 0x8000
VIEW = BASE + 0x9000       # the same drawing, called per view by the multi-view renderer (a viewport_hud extension)
AURA = BASE + 0xA000       # ends a vanished body's live aura instances
BREAK = BASE + 0xB000      # the opponent-KO mirror's HP test (native 1DBCE0 -> 1DC320): no freeze between waves
PLACE = BASE + 0xB400      # an admitted entrant's spawn moved relative to the player team
HUDGATE = BASE + 0xC000    # in front of viewport_hud.ACTIVE: no split panels over a full-screen wave intro
MIRROR_CALL, OPPONENT_DEAD = A(0x1DBDE0), A(0x1DC320)   # `jal 1DC320` of the mirror's flag-177 test (a0 = s0)
# PLACE (see place_code): the arc's distance from the living player team's centre (native 1v1 starts are about 250
# apart), the gap between two bodies (PLACE_GAP + PLACE_SIZE * both native body radii, PLACE_TEAM more to a
# player-team body), bodies more than PLACE_VERTICAL apart in height never collide; radius sanity bound. World y
# grows downwards.
PLACE_NEAR, PLACE_FAR = 200, 450
PLACE_GAP, PLACE_SIZE, PLACE_TEAM, PLACE_VERTICAL, PLACE_RADIUS_MAX = 60, 6, 60, 200, 64
SELECT, PRESENT, WATCH = BASE + 0x5400, BASE + 0x5600, BASE + 0x7000
NAMES = BASE + 0x1F000          # 256 words: native-font name string of each character id used in the run
ORDER = BASE + 0xE5C0           # 12 bytes: spectator cycle order (the player team first, then the enemies)
CONTROL = BASE + 0xE000
GATES = BASE + 0xE200          # 12 words: owner gate per physical
SLOTS = BASE + 0xE240          # 12 x 64: per physical state (see S)
SLOT_STRIDE = 64
WAVES = BASE + 0x10000         # wave table (see WAVE)
STRINGS = BASE + 0x18000       # banner strings
PACKET, CAPACITY = BASE + 0x20000, 0x40000
MAGIC, GATE_MAGIC = 0x474E5431, 0x47410000   # 'GNT1'; gate = GATE_MAGIC | generation (16 bits)
MAX_BLOCKS = 4096
RECORD = 16
# CONTROL words
C = dict(magic=0, manager=4, count=8, version=12, tick_previous=16, tick=20,
         copy_request=32, copy_ack=36, copy_status=40, copy_blocks=44, copy_bytes=48, copy_failure=52, copy_tick=56,
         run_request=64, run_ack=68, run_status=72, run_entry=76, run_control=80, run_kind=84, run_physical=88,
         run_calls=92, run_waits=96, run_limit=100,
         gate_mask=112, generation=116,
         admit_request=128, admit_ack=132, admit_physical=136, admit_status=140,
         state=160, wave=164, waves=168, countdown_end=172, phase_tick=176, refill=180, player_mask=184,
         enemy_mask=188, wave_mask=192, pending=196, banner_until=200, last_admit=204, result=212,
         reached=216, entrant=220, participants=224, intro_admitted=232, draws=236,
         countdown=240, vanish=244, overtime=248, step=252, tail=256, banner=260, release=264, player_team=268,
         text_next=272, text_ready=276, text_won=280, pending_deadline=284, give_up=288,
         intro_phase=292, intro_actor=296, intro_since=300, intro_camera=304, intro_len=308, intro_track=312,
         spectate=316, watched=320, watch_buttons=324, watch_until=332, order_count=336, intros=340, taunts=344,
         getup=348, group_step=352, intro_queue=356,
         draw_calls=448, draw_gate=452, draw_gp=456, draw_view=460, in_world=464, view_calls=468, cleanup=472, cleanups=476, homes=480, parked=484,
         breaks=488, placed=492, place_x=496, place_y=500, place_z=504,
         place_clear=360, place_tries=364, intro_wait=368, intro_waited=372, intro_chained=376,
         intro_posed=380, intro_nopose=384, intro_min=388)
INIT, FIGHT, COUNTDOWN, INTRO, WON, LOST = range(6)

STATE_NAMES = ('init', 'fight', 'countdown', 'intro', 'won', 'lost')
WAVE_SHIFT = 8
WAVE_STRIDE, WAVE_HEADER, FIGHTER_STRIDE = 1 << WAVE_SHIFT, 16, 20
assert 32 + 5 * FIGHTER_STRIDE <= WAVE_STRIDE
# WAVES: count, then per wave at +16+256*w: fighters, CPU level, banner, title and "reached" strings, then up to
# 5 x (character, costume, HP, damage per mille, defense per mille) at +32.
# SLOTS rows (32 bytes per physical)
S = dict(hidden=0, generation=4, state=8, ko_tick=12, hp=16, damage=20, defense=24, difficulty=28,
         wave=32, index=36, taunted=40, admitted=44, character=48, home=52)
ACTIVE, KO, VANISHED, LOADING, READY = 1, 2, 3, 4, 5
RUN_IO, RUN_ONCE, RUN_POLL = 1, 2, 3   # io: idle gate + repeat; once: one call; poll: repeat (retire)
TARGETS = ((io.ENTRY, io.CONTROL), (stage.ENTRY, stage.CONTROL), (commit.ENTRY, commit.CONTROL),
           (retire.ENTRY, retire.CONTROL))
# Destinations a job packet may write: the four reload workspaces and the staging getter word.
ALLOWED = ((io.ENTRY, io.END), (stage.ENTRY, stage.END), (commit.ENTRY, commit.END), (retire.ENTRY, retire.END))
try:
    import bt4_model_metadata as METADATA
except ImportError:          # BT3: native metadata needs no private copy
    METADATA = None
if METADATA is not None:
    # BT4: a recycled fighter's private character metadata (sidecars and row) for dynamic resource handles 2..13,
    # published before its staging like the ordinary Worker does; never the bridge code, its hook or leader data.
    METADATA_REGIONS = ((METADATA.DATA, METADATA.DATA + 12 * METADATA.STRIDE), (METADATA.ROWS, METADATA.ROWS + 12 * 64))
    assert METADATA_REGIONS[0][1] <= METADATA.CODE and METADATA_REGIONS[1][1] <= METADATA.END
    ALLOWED += METADATA_REGIONS
else:
    METADATA_REGIONS = ()
EXT_WORD = stage.creator.EXT_ENTRY
EXT_NEW = struct.pack('<2I', (2 << 26) | (stage.EXTENSION >> 2), 0)
# Idle waits before an io start gives up (status 112): updates with the native loader busy.
IO_IDLE_LIMIT = 300
SAVED = tuple(range(16, 24)) + (31,)
ALL = tuple(range(1, 26)) + (28, 30, 31)


def u32(ram, p):
    return struct.unpack_from('<I', ram, p)[0]


def jump(target, link=False):
    return struct.pack('<2I', ((3 if link else 2) << 26) | (target >> 2), 0)


def frame(a, size=0x60):
    assert size % 16 == 0
    a.addiu(29, 29, -size)
    for i, r in enumerate(SAVED):
        a.i(63, r, 29, i * 8)


def unframe(a, size=0x60):
    for i, r in enumerate(SAVED):
        a.i(55, r, 29, i * 8)
    a.addiu(29, 29, size)
    a.jr()


def save_all(a):
    for i, r in enumerate(ALL):
        a.i(63, r, 29, i * 8)


def restore_all(a):
    for i, r in enumerate(ALL):
        a.i(55, r, 29, i * 8)


def tick_code():
    """At feed.TICK_CALL: the previous target first with the native registers (its v0 kept), then UPDATE."""
    a = Assembler(TICK); a.addiu(29, 29, -0x100); save_all(a); a.i(63, 31, 29, 0xE8)
    restore_all(a); a.li(25, CONTROL); a.lw(25, 25, C['tick_previous']); a.r(9, 31, 25); a.emit(0)
    save_all(a); a.call(UPDATE)
    restore_all(a); a.i(55, 31, 29, 0xE8); a.addiu(29, 29, 0x100); a.jr()
    data = a.finish(); assert len(data) <= UPDATE - TICK; return data


def scope(a, fail):
    """s0 = CONTROL; the captured live world (core.gate: t0..t2), this run's manager and count."""
    core.gate(a, fail)
    a.li(16, CONTROL); a.lw(8, 16); a.li(9, MAGIC); a.branch(5, 8, 9, fail)
    a.lw(8, 16, C['manager']); a.lw(9, 28, -22364); a.branch(5, 8, 9, fail)
    a.lw(8, 16, C['count']); a.branch(5, 8, 10, fail)


def emit_dormant(a, busy):
    """Branch to `busy` unless every reload workspace and runner is idle and nothing holds combat (t0..t2)."""
    a.li(8, native.CONTROL + 16); a.lw(8, 8); a.branch(5, 8, 0, busy)
    for base in (runner_module.CONTROL, runner_module.BG_CONTROL):
        a.li(8, base); a.lw(9, 8, 4); a.lw(10, 8, 8); a.branch(5, 9, 10, busy)
    for _, control in TARGETS:
        a.li(8, control); a.lw(9, 8, 4); a.addiu(9, 9, -1); a.i(11, 9, 9, 4); a.branch(5, 9, 0, busy)
    a.lw(9, 16, C['run_request']); a.lw(10, 16, C['run_ack']); a.branch(5, 9, 10, busy)


def copier_code():
    """Install one validated job packet (native_preparation.encode format) into the reload workspaces."""
    a = Assembler(COPIER); frame(a, 0x80)
    scope(a, 'done')
    a.lw(17, 16, C['copy_request']); a.lw(8, 16, C['copy_ack']); a.branch(4, 17, 8, 'done')
    emit_dormant(a, 'busy')
    a.lw(18, 16, C['copy_blocks']); a.addiu(8, 18, -1); a.li(9, MAX_BLOCKS); a.r(0x2B, 8, 8, 9)
    a.branch(4, 8, 0, 'bounds_error')
    a.lw(19, 16, C['copy_bytes']); a.li(8, CAPACITY + 1); a.r(0x2B, 8, 19, 8); a.branch(4, 8, 0, 'bounds_error')
    a.r(0, 8, 0, 18, 4); a.r(0x2B, 9, 19, 8); a.branch(5, 9, 0, 'bounds_error')
    a.li(20, PACKET); a.move(21, 0)
    a.label('validate_block'); a.sw(21, 16, C['copy_failure'])
    a.lw(8, 20); a.lw(9, 20, 4); a.lw(10, 20, 8); a.lw(11, 20, 12)
    a.branch(4, 9, 0, 'bounds_error')
    # Destination inside exactly one allowed workspace, or the exact 8-byte getter word.
    for lo, hi in ALLOWED:
        a.li(12, lo); a.r(0x2B, 12, 8, 12); a.branch(5, 12, 0, f'not_{lo:x}')
        a.li(12, hi); a.r(0x2B, 13, 8, 12); a.branch(4, 13, 0, f'not_{lo:x}')          # dest < hi
        a.r(0x23, 12, 12, 8); a.r(0x2B, 12, 12, 9); a.branch(5, 12, 0, f'not_{lo:x}')   # and size <= hi - dest
        a.jump('destination_ok'); a.label(f'not_{lo:x}')
    a.li(12, EXT_WORD); a.branch(5, 8, 12, 'bounds_error')
    a.addiu(12, 0, 8); a.branch(5, 9, 12, 'bounds_error')
    a.li(12, PACKET); a.r(0x2D, 12, 12, 11)
    for k, word in enumerate(struct.unpack('<2I', EXT_NEW)):
        a.lw(13, 12, 4 * k); a.li(14, word); a.branch(5, 13, 14, 'bounds_error')
    a.label('destination_ok')
    a.r(0, 12, 0, 18, 4)
    for reg in (10, 11):
        a.r(0x2B, 13, reg, 12); a.branch(5, 13, 0, 'bounds_error')
        a.r(0x2B, 13, 19, reg); a.branch(5, 13, 0, 'bounds_error')
        a.r(0x23, 13, 19, reg); a.r(0x2B, 13, 13, 9); a.branch(5, 13, 0, 'bounds_error')
    a.li(12, PACKET); a.r(0x2D, 10, 10, 12)
    a.label('compare'); a.i(36, 12, 8, 0); a.i(36, 13, 10, 0); a.branch(5, 12, 13, 'guard_error')
    a.addiu(8, 8, 1); a.addiu(10, 10, 1); a.addiu(9, 9, -1); a.branch(5, 9, 0, 'compare')
    a.addiu(20, 20, RECORD); a.addiu(21, 21, 1); a.branch(5, 21, 18, 'validate_block')
    a.li(20, PACKET); a.move(21, 0)
    a.label('write_block'); a.lw(8, 20); a.lw(9, 20, 4); a.lw(10, 20, 12)
    a.li(12, PACKET); a.r(0x2D, 10, 10, 12)
    a.label('copy'); a.r(0x25, 12, 8, 10); a.i(12, 12, 12, 3); a.branch(5, 12, 0, 'byte')
    a.i(11, 12, 9, 4); a.branch(5, 12, 0, 'byte')
    a.lw(12, 10); a.sw(12, 8); a.addiu(8, 8, 4); a.addiu(10, 10, 4); a.addiu(9, 9, -4); a.jump('copied')
    a.label('byte'); a.i(36, 12, 10, 0); a.i(40, 12, 8, 0); a.addiu(8, 8, 1); a.addiu(10, 10, 1); a.addiu(9, 9, -1)
    a.label('copied'); a.branch(5, 9, 0, 'copy')
    a.addiu(20, 20, RECORD); a.addiu(21, 21, 1); a.branch(5, 21, 18, 'write_block')
    a.lw(8, 16, C['tick']); a.sw(8, 16, C['copy_tick'])
    a.addiu(8, 0, 1); a.jump('ack')
    a.label('busy'); a.addiu(8, 0, 103); a.jump('ack')
    a.label('guard_error'); a.addiu(8, 0, 100); a.jump('ack')
    a.label('bounds_error'); a.addiu(8, 0, 101)
    a.label('ack'); a.sw(8, 16, C['copy_status']); a.sw(17, 16, C['copy_ack'])
    a.label('done'); unframe(a, 0x80)
    data = a.finish(); assert len(data) <= RUNNER - COPIER, len(data); return data


def emit_loader_idle(a, wait):
    """extra_reload_quiet.background_code's idle gate: branch to `wait` while the native loader may be busy."""
    for p in (runner_module.LOADER_STATE, runner_module.LOADER_HANDLE):
        a.li(8, p); a.lw(8, 8); a.branch(5, 8, 0, wait)
    a.li(8, runner_module.LOADER_PENDING); a.lw(8, 8); a.i(12, 8, 8, 0xFFFF); a.branch(5, 8, 0, wait)
    a.li(8, runner_module.TASK_FIFO); a.lw(8, 8)
    a.li(9, 0x100000); a.r(0x2B, 10, 8, 9); a.branch(5, 10, 0, 'fifo_unknown')
    a.li(9, 0x08000000 - 32); a.r(0x2B, 10, 9, 8); a.branch(5, 10, 0, 'fifo_unknown')
    a.i(12, 10, 8, 3); a.branch(5, 10, 0, 'fifo_unknown')
    a.lw(8, 8, 12); a.branch(5, 8, 0, wait)
    a.label('fifo_unknown'); a.lw(8, 16, C['manager'])
    for off in (600, 612, 628):
        a.lw(9, 8, off); a.branch(5, 9, 0, wait)
    a.lw(9, 8, 604); a.lw(10, 8, 608); a.branch(5, 9, 10, wait)
    a.li(8, runner_module.SCENE_FLAGS); a.lw(8, 8); a.i(12, 8, 8, runner_module.SCENE_RELOAD_MASK)
    a.branch(5, 8, 0, wait)


def runner_code():
    """Call the installed job: io once per update until final (after the loader idle gate), others once."""
    a = Assembler(RUNNER); frame(a, 0x80)
    scope(a, 'done')
    a.lw(17, 16, C['run_request']); a.lw(8, 16, C['run_ack']); a.branch(4, 17, 8, 'done')
    # Never in the update its code was installed (the copy and the first call are separate updates).
    a.lw(8, 16, C['copy_tick']); a.lw(9, 16, C['tick']); a.branch(4, 8, 9, 'done')
    a.li(8, native.CONTROL + 16); a.lw(8, 8); a.branch(5, 8, 0, 'done')
    a.lw(18, 16, C['run_entry']); a.lw(19, 16, C['run_control'])
    for index, (entry, control) in enumerate(TARGETS):
        a.li(8, entry); a.branch(5, 18, 8, f'next{index}')
        a.li(8, control); a.branch(5, 19, 8, 'error110'); a.jump('target_ok')
        a.label(f'next{index}')
    a.jump('error110')
    a.label('target_ok')
    a.lw(8, 19); a.addiu(9, 0, 1); a.branch(5, 8, 9, 'error110')
    a.lw(8, 19, 4); a.branch(4, 8, 0, 'not_final')
    a.addiu(9, 0, 5); a.branch(4, 8, 9, 'final'); a.i(11, 9, 8, 100); a.branch(4, 9, 0, 'final')
    a.label('not_final')
    a.lw(8, 16, C['run_kind']); a.addiu(9, 0, RUN_IO); a.branch(5, 8, 9, 'call')
    a.lw(8, 19, 4); a.branch(5, 8, 0, 'call')      # polling an io already queued: no idle gate
    emit_loader_idle(a, 'wait')
    a.sw(0, 16, C['run_waits']); a.jump('call')
    a.label('wait'); a.lw(8, 16, C['run_waits']); a.addiu(8, 8, 1); a.sw(8, 16, C['run_waits'])
    a.i(11, 9, 8, IO_IDLE_LIMIT); a.branch(5, 9, 0, 'done')
    a.addiu(8, 0, 112); a.jump('ack_status')
    a.label('call')
    for index, (entry, _) in enumerate(TARGETS):
        a.li(8, entry); a.branch(5, 18, 8, f'skip{index}'); a.call(entry); a.jump('called'); a.label(f'skip{index}')
    a.jump('error110')
    a.label('called'); a.lw(8, 16, C['run_calls']); a.addiu(8, 8, 1); a.sw(8, 16, C['run_calls'])
    a.lw(8, 19, 4); a.addiu(9, 0, 5); a.branch(4, 8, 9, 'ack_status')
    a.i(11, 9, 8, 100); a.branch(4, 9, 0, 'ack_status')
    # Not final: io and poll jobs repeat (bounded); a once-job that did not finish is a failure.
    a.lw(9, 16, C['run_kind']); a.addiu(10, 0, RUN_ONCE); a.branch(5, 9, 10, 'limit')
    a.addiu(8, 0, 113); a.jump('ack_status')
    a.label('limit'); a.lw(9, 16, C['run_calls']); a.lw(10, 16, C['run_limit']); a.r(0x2B, 9, 9, 10)
    a.branch(5, 9, 0, 'done'); a.addiu(8, 0, 134); a.jump('ack_status')
    a.label('final'); a.lw(8, 19, 4); a.jump('ack_status')
    a.label('error110'); a.addiu(8, 0, 110)
    a.label('ack_status'); a.sw(8, 16, C['run_status']); a.sw(17, 16, C['run_ack'])
    a.label('done'); unframe(a, 0x80)
    data = a.finish(); assert len(data) <= DRAW - RUNNER, len(data); return data


def gates_code(a):
    """GATES[p] for every physical in CONTROL.gate_mask: GATE_MAGIC | generation once the extra has been consumed,
    hidden, KO'd (action 216) and at 0 HP for two updates; 0 otherwise. A slot that becomes hidden again gets a new
    generation, so a job built for an earlier vanish never runs. s0 = CONTROL. Uses s1..s6, t0..t5."""
    a.move(17, 0)
    a.label('gate_loop')
    a.addiu(11, 0, 1); a.r(4, 11, 17, 11)                                 # t3 = 1 << s1 (sllv)
    a.lw(8, 16, C['gate_mask']); a.r(0x24, 8, 8, 11); a.branch(4, 8, 0, 'gate_next')
    a.r(0, 9, 0, 17, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(18, 8)          # s2 actor
    a.li(8, 0x100000); a.r(0x2B, 8, 18, 8); a.branch(5, 8, 0, 'gate_clear')
    a.li(8, 0x08000000 - 0x1600); a.r(0x2B, 8, 8, 18); a.branch(5, 8, 0, 'gate_clear')
    a.lw(8, 18); a.branch(5, 8, 17, 'gate_clear')
    a.lw(8, 18, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, 'gate_clear')
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(19, 8)            # s3 model
    a.li(8, 0x100000); a.r(0x2B, 8, 19, 8); a.branch(5, 8, 0, 'gate_clear')
    a.li(8, 0x08000000 - 0x1670); a.r(0x2B, 8, 8, 19); a.branch(5, 8, 0, 'gate_clear')
    a.lw(8, 19, 8); a.branch(5, 8, 0, 'gate_clear')
    a.lw(8, 18, 0x948); a.addiu(9, 0, 216); a.branch(5, 8, 9, 'gate_clear')
    a.li(8, part.CONSUMED); a.lw(8, 8); a.r(0x24, 8, 8, 11); a.branch(4, 8, 0, 'gate_clear')
    a.lw(8, 18, 0x994); a.lw(9, 18, 0x998); a.r(0x2B, 10, 8, 9); a.branch(4, 10, 0, 'gate_clear')
    a.r(0, 9, 0, 8, 7); a.r(0, 10, 0, 8, 5); a.r(0x21, 9, 9, 10); a.r(0, 10, 0, 8, 2); a.r(0x21, 9, 9, 10)
    a.r(0x21, 9, 9, 18); a.lw(8, 9, 0x9A4 + 64); a.branch(5, 8, 0, 'gate_clear')
    # Hidden: count updates (SLOTS+0), stamp a new generation on the first one (SLOTS+4).
    a.r(0, 9, 0, 17, 6); a.li(8, SLOTS); a.r(0x21, 20, 8, 9)                               # s4 slot row
    a.lw(8, 20); a.branch(5, 8, 0, 'gate_counted')
    a.lw(9, 16, C['generation']); a.addiu(9, 9, 1); a.i(12, 9, 9, 0xFFFF); a.branch(5, 9, 0, 'gate_gen')
    a.addiu(9, 0, 1)
    a.label('gate_gen'); a.sw(9, 16, C['generation']); a.sw(9, 20, 4)
    a.label('gate_counted'); a.addiu(8, 8, 1); a.sw(8, 20)
    a.i(11, 9, 8, 3); a.branch(5, 9, 0, 'gate_zero')
    a.lw(9, 20, 4); a.li(10, GATE_MAGIC); a.r(0x25, 9, 9, 10); a.jump('gate_store')
    a.label('gate_clear')
    a.r(0, 9, 0, 17, 6); a.li(8, SLOTS); a.r(0x21, 20, 8, 9); a.sw(0, 20)
    a.label('gate_zero'); a.move(9, 0)
    a.label('gate_store'); a.r(0, 10, 0, 17, 2); a.li(8, GATES); a.r(0x21, 8, 8, 10); a.sw(9, 8)
    a.label('gate_next'); a.addiu(17, 17, 1); a.i(11, 8, 17, 12); a.branch(5, 8, 0, 'gate_loop')


def admit_code():
    """a0 physical -> v0 1 when admitted. Story `enter` semantics for a slot whose fighter is loaded and hidden:
    the arena's guarded native spawn (story ARRIVAL), participation and reload rows released, the planned HP,
    damage/defense (story_rules.STATS) and CPU level (row-8 + native 1BB478 under its private AI), visible.
    The CPU flag stays 0 (the intro's input lock) until the runtime releases the wave."""
    import story_runtime as story
    import story_rules
    import team_start_gate as start
    import extra_reload_requests as reloads
    from ai_shadow import AI_GLOBAL
    from team_six_ai import SHADOWS
    assert all(SHADOWS[i] == SHADOWS[0] + 0x1000 * i for i in range(len(SHADOWS)))
    a = Assembler(ADMIT); frame(a, 0x80)
    a.move(17, 4); a.move(2, 0)
    a.addiu(8, 17, -2); a.i(11, 8, 8, 10); a.branch(4, 8, 0, 'done')
    a.r(0, 9, 0, 17, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(18, 8)
    a.li(8, 0x100000); a.r(0x2B, 8, 18, 8); a.branch(5, 8, 0, 'done')
    a.li(8, 0x08000000 - 0x1600); a.r(0x2B, 8, 8, 18); a.branch(5, 8, 0, 'done')
    a.lw(8, 18); a.branch(5, 8, 17, 'done')
    a.lw(8, 18, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, 'done')
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(19, 8)
    a.li(8, 0x100000); a.r(0x2B, 8, 19, 8); a.branch(5, 8, 0, 'done')
    a.li(8, 0x08000000 - 0x1670); a.r(0x2B, 8, 8, 19); a.branch(5, 8, 0, 'done')
    a.lw(8, 19, 4); a.addiu(9, 0, 1); a.branch(5, 8, 9, 'done')
    a.lw(8, 18, 0x994); a.lw(9, 18, 0x998); a.r(0x2B, 10, 8, 9); a.branch(4, 10, 0, 'done')
    a.r(0, 9, 0, 8, 7); a.r(0, 10, 0, 8, 5); a.r(0x21, 9, 9, 10); a.r(0, 10, 0, 8, 2); a.r(0x21, 9, 9, 10)
    a.r(0x21, 9, 9, 18); a.addiu(21, 9, 0x9E4)                                       # s5 HP row
    a.r(0, 9, 0, 17, 6); a.li(8, SLOTS); a.r(0x21, 20, 8, 9)                         # s4 slot row
    a.move(4, 18); a.move(5, 19); a.call(story.ARRIVAL); a.branch(4, 2, 0, 'refused')
    a.move(4, 18); a.move(5, 19); a.call(PLACE)                                       # on the arc, on the floor
    # Stand it up at once: the slot's body is a retained KO body (action 216) that the native would fall (217..219)
    # and get up (225) from; requesting idle (11) skips both (live, p90 r5 neutral probe).
    a.addiu(8, 0, 11); a.sw(8, 18, 0x94C)
    a.addiu(9, 0, 1); a.r(4, 9, 17, 9); a.r(0x27, 9, 9, 0)
    a.li(8, part.CONSUMED); a.lw(10, 8); a.r(0x24, 10, 10, 9); a.sw(10, 8)
    a.addiu(8, 17, -2); a.r(0, 8, 0, 8, 6); a.li(9, reloads.RECORDS); a.r(0x21, 8, 8, 9); a.sw(0, 8, 4); a.sw(0, 8, 52)
    a.lw(8, 20, S['hp']); a.branch(5, 8, 0, 'hp'); a.lw(8, 21, 4)
    a.label('hp'); a.sw(8, 21, 4); a.sw(8, 21)
    a.r(0, 9, 0, 17, 2)
    a.li(8, feed.CONTROL + 0x40); a.r(0x21, 8, 8, 9); a.sw(0, 8)
    a.li(8, start.CONTROL + 0x40); a.r(0x21, 8, 8, 9); a.sw(0, 8)
    for off in (0x1278, 0x127C, 0x1280, 0x1284):
        a.sw(0, 18, off)
    a.r(0, 9, 0, 17, 4); a.li(8, story_rules.STATS); a.r(0x21, 8, 8, 9)
    a.lw(9, 20, S['damage']); a.sw(9, 8); a.lw(9, 20, S['defense']); a.sw(9, 8, 4); a.sw(0, 8, 8); a.sw(0, 8, 12)
    a.lw(5, 20, S['difficulty']); a.sw(5, 21, -8)
    a.li(22, AI_GLOBAL); a.lw(23, 22)
    a.r(0, 8, 0, 17, 12); a.li(9, SHADOWS[0]); a.r(0x21, 8, 8, 9); a.sw(8, 22)
    a.i(12, 4, 17, 1); a.call(A(0x1BB478)); a.sw(23, 22)
    a.addiu(8, 0, 1); a.sw(8, 19, 8)
    a.addiu(8, 0, ACTIVE); a.sw(8, 20, S['state']); a.sw(0, 20, S['taunted']); a.sw(0, 20, S['ko_tick'])
    a.li(8, CONTROL); a.lw(8, 8, C['tick']); a.addiu(8, 8, 1); a.sw(8, 20, S['admitted'])
    a.addiu(2, 0, 1); a.jump('done')
    a.label('refused'); a.move(2, 0)
    a.label('done'); unframe(a, 0x80)
    data = a.finish(); assert len(data) <= SELECT - ADMIT, len(data); return data


# COP1 single precision (EE): add 0, sub 1, mul 2, div 3, sqrt 4 (source in ft), abs 5; conversions below.
def fop(a, fn, fd, fs, ft=0): a.emit((17 << 26) | (16 << 21) | (ft << 16) | (fs << 11) | (fd << 6) | fn)
def mtc1(a, rt, fs): a.emit((17 << 26) | (4 << 21) | (rt << 16) | (fs << 11))
def mfc1(a, rt, fs): a.emit((17 << 26) | (rt << 16) | (fs << 11))
def cvt_s_w(a, fd, fs): a.emit((17 << 26) | (20 << 21) | (fs << 11) | (fd << 6) | 0x20)
def cvt_w_s(a, fd, fs): a.emit((17 << 26) | (16 << 21) | (fs << 11) | (fd << 6) | 0x24)
def lwc1(a, ft, base, offset): a.i(49, ft, base, offset)
def swc1(a, ft, base, offset): a.i(57, ft, base, offset)
def fconst(a, fd, value):
    a.li(8, struct.unpack('<I', struct.pack('<f', value))[0]); mtc1(a, 8, fd)


def break_code():
    """BREAK, called by the native opponent mirror (1DBCE0) instead of 1DC320 for its flag-177 test: a0 = the
    opponent, the caller's s1 = the viewing actor. During the countdown a player-team viewer is told its opponent is
    alive (v0 = 0), so its pad is not cleared; everyone else, and every other time, gets 1DC320 itself."""
    a = Assembler(BREAK); a.addiu(29, 29, -0x20)
    for i, r in enumerate((8, 9, 10)):
        a.i(63, r, 29, i * 8)
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'native')
    a.lw(9, 8, C['manager']); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'native')
    a.lw(9, 8, C['state']); a.addiu(10, 0, COUNTDOWN); a.branch(5, 9, 10, 'native')
    a.li(9, 0x100000); a.r(0x2B, 9, 17, 9); a.branch(5, 9, 0, 'native')
    a.li(9, 0x08000000 - 0x1600); a.r(0x2B, 9, 9, 17); a.branch(5, 9, 0, 'native')
    a.lw(9, 17); a.i(11, 10, 9, 12); a.branch(4, 10, 0, 'native')           # t1 = physical (< 12)
    a.r(0, 10, 0, 9, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 10); a.lw(8, 8); a.branch(5, 8, 17, 'native')
    a.addiu(10, 0, 1); a.r(4, 10, 9, 10)
    a.li(8, CONTROL); a.lw(9, 8, C['player_mask']); a.r(0x24, 9, 9, 10); a.branch(4, 9, 0, 'native')
    a.lw(9, 8, C['breaks']); a.addiu(9, 9, 1); a.sw(9, 8, C['breaks'])
    for i, r in enumerate((8, 9, 10)):
        a.i(55, r, 29, i * 8)
    a.addiu(29, 29, 0x20); a.move(2, 0); a.jr()
    a.label('native')
    for i, r in enumerate((8, 9, 10)):
        a.i(55, r, 29, i * 8)
    a.addiu(29, 29, 0x20); a.jump(OPPONENT_DEAD)
    data = a.finish(); assert len(data) <= PLACE - BREAK, len(data); return data


def emit_player_position(a, index, fail):
    """f4..f6 = the model position of living player-team physical `index` (s2); else to fail. t0..t2, s5, s6."""
    a.addiu(9, 0, 1); a.r(4, 9, index, 9)
    a.lw(8, 20, C['player_mask']); a.r(0x24, 8, 8, 9); a.branch(4, 8, 0, fail)
    emit_hp_row(a, index, fail, actor=21, row=22)
    a.lw(8, 22); a.branch(6, 8, 0, fail)
    a.lw(8, 21, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, fail)
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(10, 8)
    a.li(8, 0x100000); a.r(0x2B, 8, 10, 8); a.branch(5, 8, 0, fail)
    a.li(8, 0x08000000 - 0x1670); a.r(0x2B, 8, 8, 10); a.branch(5, 8, 0, fail)
    for k in range(3):
        lwc1(a, 4 + k, 10, 2416 + 4 * k)


def emit_body(a, index, fail, actor=21, model=10):
    """actor (s5) and model (t2) of any captured physical `index` (visible or hidden), else to fail. t0, t1."""
    a.r(0, 9, 0, index, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(actor, 8)
    a.li(8, 0x100000); a.r(0x2B, 8, actor, 8); a.branch(5, 8, 0, fail)
    a.li(8, 0x08000000 - 0x1600); a.r(0x2B, 8, 8, actor); a.branch(5, 8, 0, fail)
    a.lw(8, actor); a.branch(5, 8, index, fail)
    a.lw(8, actor, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, fail)
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(model, 8)
    a.li(8, 0x100000); a.r(0x2B, 8, model, 8); a.branch(5, 8, 0, fail)
    a.li(8, 0x08000000 - 0x1670); a.r(0x2B, 8, 8, model); a.branch(5, 8, 0, fail)


def emit_radius(a, model, fd):
    """fd = the native body radius (model +0x1004); negative, NaN, infinite or over PLACE_RADIUS_MAX: 6 (t0, t1)."""
    lwc1(a, fd, model, 0x1004)
    a.lw(8, model, 0x1004); a.li(9, struct.unpack('<I', struct.pack('<f', float(PLACE_RADIUS_MAX)))[0])
    a.r(0x2B, 9, 9, 8)
    label = f'radius_ok{len(a.words)}'
    a.branch(4, 9, 0, label)
    fconst(a, fd, 6.0)
    a.label(label)


def place_code():
    """PLACE: a0 entrant actor, a1 its model, right after the native spawn (story ARRIVAL). The players may be
    anywhere after the break, and the native spawn marks can coincide (or hold a KO'd body), so the entrant is put
    on an arc facing the living player team:
      - ring distance D = the team centre -> enemy formation centre distance (the recorded enemy homes), clamped
        to PLACE_NEAR..PLACE_FAR, along that line (u);
      - its slot on the arc from its index in the wave: offset (index - (n-1)/2) * S, S = PLACE_GAP +
        2 PLACE_SIZE * its native body radius (model +0x1004; giants are wider);
      - candidates: that slot, then +-1, +-2, +-3 slots and a second ring D + S; the first candidate that is inside
        the arena's flight radius (arena_bounds), has a native floor (spawn_placement QUERY, the formation planner's
        own floor probe) and keeps PLACE_GAP + PLACE_SIZE * (both radii) (+PLACE_TEAM for the player team) from
        every other body, visible or hidden (KO'd and removed bodies are parked at their homes), wins; else the one
        with the most clearance; with no floor anywhere the native spawn stays.
    Stands on that floor (no fall into a knockdown). Position words as the body parking, then the stage lookup
    ARRIVAL ends with (23FF78 -> model +2596). CONTROL: placed + 1, place_x/y/z, place_clear (the smallest
    clearance surplus, squared units, signed), place_tries."""
    import spawn_placement as planner
    import arena_bounds as bounds
    a = Assembler(PLACE); size = 0x200
    F = dict(cx=0x160, cy=0x164, cz=0x168, ux=0x16C, uz=0x170, d=0x174, s=0x178, off0=0x17C, r=0x180,
             top=0x184, lim2=0x188, px=0x190, py=0x194, pz=0x198, pw=0x19C, bx=0x1A0, by=0x1A4, bz=0x1A8,
             best=0x1AC, worst=0x1B0, ay=0x1B4, have_best=0x1B8, floor_ok=0x1BC)
    a.addiu(29, 29, -size)
    for i, r in enumerate(ALL):
        a.i(63, r, 29, i * 8)
    for f in range(32):
        swc1(a, f, 29, 0xE0 + 4 * f)
    a.move(16, 4); a.move(17, 5); a.li(20, CONTROL)
    a.li(8, 0x100000); a.r(0x2B, 8, 17, 8); a.branch(5, 8, 0, 'done')
    a.li(8, 0x08000000 - 0x1670); a.r(0x2B, 8, 8, 17); a.branch(5, 8, 0, 'done')
    a.lw(19, 16); a.i(11, 8, 19, 12); a.branch(4, 8, 0, 'done')            # s3 = this entrant's physical
    # Team centre (f0..f2; s7 = living players)
    for f in range(3):
        mtc1(a, 0, f)
    a.move(23, 0); a.move(18, 0)
    a.label('team_loop')
    emit_player_position(a, 18, 'team_next')
    for k in range(3):
        fop(a, 0, k, k, 4 + k)
    a.addiu(23, 23, 1)
    a.label('team_next'); a.addiu(18, 18, 1); a.i(11, 8, 18, 12); a.branch(5, 8, 0, 'team_loop')
    a.branch(4, 23, 0, 'done')
    mtc1(a, 23, 3); cvt_s_w(a, 3, 3)
    for k in range(3):
        fop(a, 3, k, k, 3); swc1(a, k, 29, F['cx'] + 4 * k)
    # Formation centre (f7..f9): the recorded enemy homes; none: this spawn
    for f in (7, 8, 9):
        mtc1(a, 0, f)
    a.move(23, 0); a.move(18, 0)
    a.label('home_loop')
    a.addiu(9, 0, 1); a.r(4, 9, 18, 9); a.lw(8, 20, C['homes']); a.r(0x24, 8, 8, 9); a.branch(4, 8, 0, 'home_next')
    a.r(0, 9, 0, 18, 6); a.li(8, SLOTS); a.r(0x21, 10, 8, 9)
    for k in range(3):
        lwc1(a, 4 + k, 10, S['home'] + 4 * k); fop(a, 0, 7 + k, 7 + k, 4 + k)
    a.addiu(23, 23, 1)
    a.label('home_next'); a.addiu(18, 18, 1); a.i(11, 8, 18, 12); a.branch(5, 8, 0, 'home_loop')
    a.branch(5, 23, 0, 'homes_known')
    for k in range(3):
        lwc1(a, 7 + k, 17, 2416 + 4 * k)
    a.jump('centre')
    a.label('homes_known')
    mtc1(a, 23, 3); cvt_s_w(a, 3, 3)
    for k in range(3):
        fop(a, 3, 7 + k, 7 + k, 3)
    a.label('centre')
    # u = unit(formation - team) (x, z); L; D = clamp(L, NEAR, FAR)
    fop(a, 1, 10, 7, 0); fop(a, 1, 11, 9, 2)
    fop(a, 2, 12, 10, 10); fop(a, 2, 13, 11, 11); fop(a, 0, 12, 12, 13); fop(a, 4, 12, 0, 12)
    cvt_w_s(a, 13, 12); mfc1(a, 8, 13)
    a.r(0x2A, 9, 0, 8); a.branch(5, 9, 0, 'length_ok')
    fconst(a, 10, 1.0); mtc1(a, 0, 11); fconst(a, 12, 1.0); a.addiu(8, 0, 1)
    a.label('length_ok')
    fop(a, 3, 10, 10, 12); fop(a, 3, 11, 11, 12); swc1(a, 10, 29, F['ux']); swc1(a, 11, 29, F['uz'])
    a.i(10, 9, 8, PLACE_NEAR); a.branch(4, 9, 0, 'not_near'); fconst(a, 12, float(PLACE_NEAR)); a.jump('ring')
    a.label('not_near')
    a.i(10, 9, 8, PLACE_FAR + 1); a.branch(5, 9, 0, 'ring'); fconst(a, 12, float(PLACE_FAR))
    a.label('ring'); swc1(a, 12, 29, F['d'])
    # S = GAP + SIZE * r (this body); offset of its slot = (2 index - (n - 1)) * S / 2
    emit_radius(a, 17, 14); swc1(a, 14, 29, F['r'])
    fconst(a, 15, float(2 * PLACE_SIZE)); fop(a, 2, 15, 15, 14); fconst(a, 16, float(PLACE_GAP)); fop(a, 0, 15, 15, 16)
    swc1(a, 15, 29, F['s'])
    a.r(0, 9, 0, 19, 6); a.li(8, SLOTS); a.r(0x21, 21, 8, 9)                   # s5 = its slot row
    a.lw(8, 21, S['wave']); a.addiu(8, 8, -1); a.i(11, 9, 8, 64); a.branch(4, 9, 0, 'single')
    a.r(0, 8, 0, 8, WAVE_SHIFT); a.li(9, WAVES + WAVE_HEADER); a.r(0x21, 8, 8, 9); a.lw(9, 8)   # t1 = n
    a.lw(8, 21, S['index']); a.r(0, 8, 0, 8, 1); a.addiu(9, 9, -1); a.r(0x23, 8, 8, 9)          # t0 = 2i - (n-1)
    mtc1(a, 8, 16); cvt_s_w(a, 16, 16); fconst(a, 17, 0.5); fop(a, 2, 16, 16, 17); fop(a, 2, 16, 16, 15)
    a.jump('slot')
    a.label('single'); mtc1(a, 0, 16)
    a.label('slot'); swc1(a, 16, 29, F['off0'])
    # Floor probe top: 300 above the higher of the spawn and the team centre; no floor probe: the spawn's height
    lwc1(a, 4, 17, 2420); swc1(a, 4, 29, F['ay'])
    lwc1(a, 5, 29, F['cy']); fop(a, 1, 6, 4, 5); cvt_w_s(a, 6, 6); mfc1(a, 8, 6)
    a.r(0x2A, 9, 8, 0); a.branch(5, 9, 0, 'top_spawn')                       # the spawn is higher
    lwc1(a, 4, 29, F['cy'])
    a.label('top_spawn'); fconst(a, 5, 300.0); fop(a, 1, 4, 4, 5); swc1(a, 4, 29, F['top'])
    fconst(a, 4, 1.0e9); swc1(a, 4, 29, F['lim2'])
    a.li(8, bounds.STAGE); a.lw(8, 8); a.li(9, 0x100000); a.r(0x2B, 9, 8, 9); a.branch(5, 9, 0, 'no_bounds')
    a.li(9, 0x08000000 - 68); a.r(0x2B, 9, 9, 8); a.branch(5, 9, 0, 'no_bounds')
    a.lw(8, 8, 64); a.li(9, 0x100000); a.r(0x2B, 9, 8, 9); a.branch(5, 9, 0, 'no_bounds')
    a.li(9, 0x08000000 - 12); a.r(0x2B, 9, 9, 8); a.branch(5, 9, 0, 'no_bounds')
    lwc1(a, 4, 8, 0); fconst(a, 5, 140.0); fop(a, 1, 4, 4, 5)
    lwc1(a, 5, 29, F['r']); fconst(a, 6, 4.0); fop(a, 2, 5, 5, 6); fop(a, 1, 4, 4, 5)
    cvt_w_s(a, 5, 4); mfc1(a, 9, 5); a.i(10, 9, 9, 100); a.branch(5, 9, 0, 'no_bounds')     # under 100: ignore
    fop(a, 2, 4, 4, 4); swc1(a, 4, 29, F['lim2'])
    a.label('no_bounds')
    # The formation planner's floor probe must be the resident one (its first words), else no floor test
    a.sw(0, 29, F['floor_ok']); a.li(8, planner.QUERY); a.lw(9, 8)
    q = struct.unpack('<2I', planner.query_code()[:8])
    a.li(10, q[0]); a.branch(5, 9, 10, 'probe_known'); a.lw(9, 8, 4); a.li(10, q[1]); a.branch(5, 9, 10, 'probe_known')
    a.addiu(9, 0, 1); a.sw(9, 29, F['floor_ok'])
    a.label('probe_known')
    a.sw(0, 29, F['have_best']); a.li(8, -0x7FFFFFFF); a.sw(8, 29, F['best'])
    # Candidates j = 0..15: ring j >> 3, slot shift m(j & 7) = 0, +1, -1, +2, -2, +3, -3, +4
    a.move(22, 0)
    a.label('cand_loop')
    a.i(12, 8, 22, 7); a.addiu(9, 8, 1); a.r(2, 9, 0, 9, 1)                    # t1 = (k + 1) >> 1
    a.i(12, 10, 8, 1); a.branch(5, 10, 0, 'shift_pos'); a.r(0x23, 9, 0, 9)     # even k: negative
    a.label('shift_pos')
    mtc1(a, 9, 4); cvt_s_w(a, 4, 4); lwc1(a, 5, 29, F['s']); fop(a, 2, 4, 4, 5)
    lwc1(a, 6, 29, F['off0']); fop(a, 0, 4, 4, 6)                            # f4 = offset along v
    lwc1(a, 6, 29, F['d']); a.r(2, 8, 0, 22, 3); a.branch(4, 8, 0, 'ring0'); fop(a, 0, 6, 6, 5)
    a.label('ring0')                                                         # f6 = ring distance
    lwc1(a, 10, 29, F['ux']); lwc1(a, 11, 29, F['uz'])
    # w = u * Dr + v * off, v = (-uz, ux); P = C + w * Dr / |w|
    fop(a, 2, 7, 10, 6); fop(a, 2, 8, 11, 4); fop(a, 1, 7, 7, 8)              # wx = ux Dr - uz off
    fop(a, 2, 8, 11, 6); fop(a, 2, 9, 10, 4); fop(a, 0, 8, 8, 9)              # wz = uz Dr + ux off
    fop(a, 2, 9, 7, 7); fop(a, 2, 12, 8, 8); fop(a, 0, 9, 9, 12); fop(a, 4, 9, 0, 9)
    fop(a, 3, 9, 6, 9); fop(a, 2, 7, 7, 9); fop(a, 2, 8, 8, 9)
    lwc1(a, 9, 29, F['cx']); fop(a, 0, 7, 7, 9); swc1(a, 7, 29, F['px'])
    lwc1(a, 9, 29, F['cz']); fop(a, 0, 8, 8, 9); swc1(a, 8, 29, F['pz'])
    lwc1(a, 9, 29, F['ay']); swc1(a, 9, 29, F['py'])
    # inside the flight radius
    fop(a, 2, 9, 7, 7); fop(a, 2, 12, 8, 8); fop(a, 0, 9, 9, 12); lwc1(a, 12, 29, F['lim2']); fop(a, 1, 9, 12, 9)
    a.lw(8, 29, F['lim2']); a.branch(4, 8, 0, 'cand_next')
    cvt_w_s(a, 9, 9); mfc1(a, 8, 9); a.r(0x2A, 9, 8, 0); a.branch(5, 9, 0, 'cand_next')
    # floor under it (the planner's probe: a0 = x/z vector, f12 = top Y -> v0 valid, f0 floor Y)
    a.lw(8, 29, F['floor_ok']); a.branch(4, 8, 0, 'floored')
    a.addiu(4, 29, F['px']); lwc1(a, 12, 29, F['top']); a.call(planner.QUERY)
    a.branch(4, 2, 0, 'cand_next'); swc1(a, 0, 29, F['py'])
    a.label('floored')
    # clearance to every other body (t: s2 index, s6 its need, f20 the worst surplus)
    fconst(a, 20, 1.0e9); a.move(18, 0)
    a.label('body_loop')
    a.branch(4, 18, 19, 'body_next')
    emit_body(a, 18, 'body_next')
    lwc1(a, 4, 10, 2416); lwc1(a, 5, 10, 2420); lwc1(a, 6, 10, 2424)
    lwc1(a, 7, 29, F['px']); fop(a, 1, 4, 7, 4); lwc1(a, 7, 29, F['pz']); fop(a, 1, 6, 7, 6)
    lwc1(a, 7, 29, F['py']); fop(a, 1, 5, 7, 5); fop(a, 5, 5, 5)
    cvt_w_s(a, 7, 5); mfc1(a, 8, 7); a.i(10, 9, 8, PLACE_VERTICAL); a.branch(4, 9, 0, 'body_next')
    emit_radius(a, 10, 7); lwc1(a, 8, 29, F['r']); fop(a, 0, 7, 7, 8)
    fconst(a, 8, float(PLACE_SIZE)); fop(a, 2, 7, 7, 8); fconst(a, 8, float(PLACE_GAP)); fop(a, 0, 7, 7, 8)
    a.addiu(9, 0, 1); a.r(4, 9, 18, 9); a.lw(8, 20, C['player_mask']); a.r(0x24, 8, 8, 9)
    a.branch(4, 8, 0, 'not_team'); fconst(a, 8, float(PLACE_TEAM)); fop(a, 0, 7, 7, 8)
    a.label('not_team')
    fop(a, 2, 7, 7, 7); fop(a, 2, 4, 4, 4); fop(a, 2, 6, 6, 6); fop(a, 0, 4, 4, 6); fop(a, 1, 4, 4, 7)
    fop(a, 1, 5, 4, 20); cvt_w_s(a, 5, 5); mfc1(a, 8, 5); a.r(0x2A, 9, 8, 0); a.branch(4, 9, 0, 'body_next')
    a.emit((17 << 26) | (16 << 21) | (0 << 16) | (4 << 11) | (20 << 6) | 6)   # mov.s f20, f4 (new worst)
    a.label('body_next'); a.addiu(18, 18, 1); a.i(11, 8, 18, 12); a.branch(5, 8, 0, 'body_loop')
    # surplus >= 0: take it; else keep the best so far
    cvt_w_s(a, 4, 20); mfc1(a, 8, 4)
    a.r(0x2A, 9, 8, 0); a.branch(4, 9, 0, 'take')
    a.lw(9, 29, F['best']); a.r(0x2A, 10, 9, 8); a.branch(4, 10, 0, 'cand_next')
    a.sw(8, 29, F['best']); a.addiu(9, 0, 1); a.sw(9, 29, F['have_best'])
    for k in range(3):
        a.lw(9, 29, F['px'] + 4 * k); a.sw(9, 29, F['bx'] + 4 * k)
    a.label('cand_next'); a.addiu(22, 22, 1); a.i(11, 8, 22, 16); a.branch(5, 8, 0, 'cand_loop')
    a.lw(8, 29, F['have_best']); a.branch(4, 8, 0, 'done')
    for k in range(3):
        a.lw(9, 29, F['bx'] + 4 * k); a.sw(9, 29, F['px'] + 4 * k)
    a.lw(8, 29, F['best'])
    a.label('take')
    a.li(20, CONTROL); a.sw(8, 20, C['place_clear']); a.sw(22, 20, C['place_tries'])
    for k in range(3):
        a.lw(8, 29, F['px'] + 4 * k)
        a.sw(8, 17, 2416 + 4 * k); a.sw(8, 16, 0x10 + 4 * k); a.sw(8, 16, 0x100 + 4 * k); a.sw(0, 16, 0x30 + 4 * k)
        a.sw(8, 20, C['place_x'] + 4 * k)
    a.addiu(4, 0, -1); a.addiu(5, 17, 2416); a.call(A(0x23FF78)); a.sw(2, 17, 2596)
    a.li(20, CONTROL); a.lw(8, 20, C['placed']); a.addiu(8, 8, 1); a.sw(8, 20, C['placed'])
    a.label('done')
    for f in range(32):
        lwc1(a, f, 29, 0xE0 + 4 * f)
    for i, r in enumerate(ALL):
        a.i(55, r, 29, i * 8)
    a.addiu(29, 29, size); a.jr()
    data = a.finish(); assert len(data) <= CONTROL - PLACE, len(data); return data



def emit_hp_row(a, physical_reg, fail, actor=18, row=21):
    """actor (s2 default) and HP row (s5 default: selected row + 0x40) of a physical; t0..t2."""
    a.r(0, 9, 0, physical_reg, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(actor, 8)
    a.li(8, 0x100000); a.r(0x2B, 8, actor, 8); a.branch(5, 8, 0, fail)
    a.li(8, 0x08000000 - 0x1600); a.r(0x2B, 8, 8, actor); a.branch(5, 8, 0, fail)
    a.lw(8, actor); a.branch(5, 8, physical_reg, fail)
    a.lw(8, actor, 0x994); a.lw(9, actor, 0x998); a.r(0x2B, 10, 8, 9); a.branch(4, 10, 0, fail)
    a.r(0, 9, 0, 8, 7); a.r(0, 10, 0, 8, 5); a.r(0x21, 9, 9, 10); a.r(0, 10, 0, 8, 2); a.r(0x21, 9, 9, 10)
    a.r(0x21, 9, 9, actor); a.addiu(row, 9, 0x9E4)


def emit_cpu(a, physical_reg, value_reg, actor_reg):
    """Set (value 1) or hold (0) a CPU fighter's flag in both places the start gate keeps it (t0, t1)."""
    import team_start_gate as start
    a.sw(value_reg, actor_reg, 0x1278)
    a.r(0, 9, 0, physical_reg, 2); a.li(8, start.CONTROL + 0x40); a.r(0x21, 8, 8, 9); a.sw(value_reg, 8)


FIND, COUNT = WAVE + 0x3800, WAVE + 0x3C00
LOADABLE = COUNT + 0x200        # an enemy slot the host can still load the wave's next fighter into


def wave_code():
    """The run: wave 1 after "Fight!", KO tracking, removal VANISH updates after a KO, the countdown with the
    player refill, the frozen wave intro (everyone protected, entrants spawned one after another), reinforcements,
    the end of the run."""
    import story_runtime as story
    import fresh_team_ai as ai
    assert all(ai.DESCRIPTORS[i] == ai.DESCRIPTORS[0] + 0x40 * i for i in range(len(ai.DESCRIPTORS)))
    a = Assembler(WAVE); frame(a, 0x80)
    a.li(16, CONTROL)
    a.lw(8, 16, C['state'])
    a.addiu(9, 0, WON); a.branch(4, 8, 9, 'done')
    a.addiu(9, 0, LOST); a.branch(4, 8, 9, 'done')
    a.branch(5, 8, 0, 'running')
    # INIT: the story clock starts at "Fight!" (the story frame skips intros and the loading cover).
    a.li(8, story.CONTROL + 12); a.lw(8, 8); a.branch(4, 8, 0, 'done')
    a.addiu(8, 0, FIGHT); a.sw(8, 16, C['state'])
    a.lw(8, 16, C['tick']); a.lw(9, 16, C['banner']); a.r(0x21, 8, 8, 9); a.sw(8, 16, C['banner_until'])
    # Every enemy body's start position (its formation mark): a vanished body is parked back there.
    a.move(17, 0); a.move(22, 0)
    a.label('home_loop')
    a.addiu(9, 0, 1); a.r(4, 23, 17, 9); a.lw(8, 16, C['enemy_mask']); a.r(0x24, 8, 8, 23)
    a.branch(4, 8, 0, 'home_next')
    a.r(0, 9, 0, 17, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(10, 8)
    a.lw(11, 10, 12); a.i(11, 8, 11, 12); a.branch(4, 8, 0, 'home_next')
    a.r(0, 11, 0, 11, 2); a.li(8, core.MODELS); a.r(0x21, 8, 8, 11); a.lw(11, 8); a.branch(4, 11, 0, 'home_next')
    a.r(0, 9, 0, 17, 6); a.li(8, SLOTS); a.r(0x21, 20, 8, 9)
    for k in (0, 4, 8):
        a.lw(12, 11, 2416 + k); a.sw(12, 20, S['home'] + k)
    a.r(0x25, 22, 22, 23)
    a.label('home_next'); a.addiu(17, 17, 1); a.i(11, 8, 17, 12); a.branch(5, 8, 0, 'home_loop')
    a.sw(22, 16, C['homes'])
    a.jump('done')
    a.label('running')
    # The player side lost when none of its fighters has HP (the native result follows; the banner names the wave).
    a.move(17, 0); a.move(22, 0)
    a.label('alive_loop')
    a.addiu(9, 0, 1); a.r(4, 9, 17, 9); a.lw(8, 16, C['player_mask']); a.r(0x24, 8, 8, 9)
    a.branch(4, 8, 0, 'alive_next')
    emit_hp_row(a, 17, 'alive_next')
    a.lw(8, 21); a.branch(6, 8, 0, 'alive_next'); a.addiu(22, 22, 1)
    a.label('alive_next'); a.addiu(17, 17, 1); a.i(11, 8, 17, 12); a.branch(5, 8, 0, 'alive_loop')
    a.branch(5, 22, 0, 'player_alive')
    a.addiu(8, 0, LOST); a.sw(8, 16, C['state']); a.addiu(8, 0, 2); a.sw(8, 16, C['result'])
    a.lw(8, 16, C['tick']); a.lw(9, 16, C['banner']); a.r(0x21, 8, 8, 9); a.sw(8, 16, C['banner_until'])
    a.jump('done')
    a.label('player_alive')
    # Enemy slots: KO, then removal VANISH updates later (never during an intro).
    a.move(17, 0)
    a.label('ko_loop')
    a.addiu(9, 0, 1); a.r(4, 23, 17, 9); a.lw(8, 16, C['enemy_mask']); a.r(0x24, 8, 8, 23)
    a.branch(4, 8, 0, 'ko_next')
    a.r(0, 9, 0, 17, 6); a.li(8, SLOTS); a.r(0x21, 20, 8, 9)
    a.lw(8, 20, S['state']); a.addiu(9, 0, ACTIVE); a.branch(4, 8, 9, 'ko_active')
    a.addiu(9, 0, VANISHED); a.branch(4, 8, 9, 'ko_keep')
    a.addiu(9, 0, KO); a.branch(5, 8, 9, 'ko_next')
    a.lw(8, 16, C['state']); a.addiu(9, 0, INTRO); a.branch(4, 8, 9, 'ko_next')
    a.lw(8, 16, C['tick']); a.lw(9, 20, S['ko_tick']); a.r(0x23, 8, 8, 9); a.lw(9, 16, C['vanish'])
    a.r(0x2B, 8, 8, 9); a.branch(5, 8, 0, 'ko_next')
    # Remove the body: a leader is retired through the story (hidden, 0 HP), an extra is consumed (participation).
    a.addiu(9, 0, 1); a.branch(5, 17, 9, 'ko_extra')
    a.li(8, story.CONTROL + 112); a.lw(9, 8); a.r(0x25, 9, 9, 23); a.sw(9, 8); a.jump('ko_vanished')
    a.label('ko_extra')
    a.li(8, part.CONSUMED); a.lw(9, 8); a.r(0x25, 9, 9, 23); a.sw(9, 8)
    a.label('ko_vanished')
    # The body goes back to its start position: not an invisible obstacle (a retired leader still collides) nor a
    # lock target lying among the fighters (a camera pressed against it pulled its eye into the fighter).
    a.lw(8, 16, C['homes']); a.r(0x24, 8, 8, 23); a.branch(4, 8, 0, 'ko_parked')
    a.r(0, 9, 0, 17, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(10, 8)
    a.lw(11, 10, 12); a.r(0, 11, 0, 11, 2); a.li(8, core.MODELS); a.r(0x21, 8, 8, 11); a.lw(11, 8)
    a.branch(4, 11, 0, 'ko_parked')
    for k in (0, 4, 8):
        a.lw(12, 20, S['home'] + k); a.sw(12, 10, 0x10 + k); a.sw(12, 10, 0x100 + k); a.sw(12, 11, 2416 + k)
        a.sw(0, 10, 0x30 + k)
    a.lw(8, 16, C['parked']); a.addiu(8, 8, 1); a.sw(8, 16, C['parked'])
    a.label('ko_parked')
    # Its live aura instances go with the body (a0 = its model ID); effect pools stay for the next load.
    a.lw(8, 16, C['cleanup']); a.branch(4, 8, 0, 'ko_cleaned')
    a.r(0, 9, 0, 17, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.lw(4, 8, 12)
    a.call(AURA)
    a.lw(8, 16, C['cleanups']); a.r(0x21, 8, 8, 2); a.sw(8, 16, C['cleanups'])
    a.label('ko_cleaned');
    a.jump('ko_vanished_done')
    # A vanished body stays gone: its aura instances end again, a (still simulated) hidden leader stays home.
    a.label('ko_keep')
    a.lw(8, 16, C['cleanup']); a.branch(4, 8, 0, 'keep_home')
    a.r(0, 9, 0, 17, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.lw(4, 8, 12)
    a.call(AURA)
    a.lw(8, 16, C['cleanups']); a.r(0x21, 8, 8, 2); a.sw(8, 16, C['cleanups'])
    a.label('keep_home')
    a.addiu(9, 0, 1); a.branch(5, 17, 9, 'ko_next')
    a.lw(8, 16, C['homes']); a.r(0x24, 8, 8, 23); a.branch(4, 8, 0, 'ko_next')
    a.r(0, 9, 0, 17, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(10, 8)
    a.lw(11, 10, 12); a.r(0, 11, 0, 11, 2); a.li(8, core.MODELS); a.r(0x21, 8, 8, 11); a.lw(11, 8)
    a.branch(4, 11, 0, 'ko_next')
    for k in (0, 4, 8):
        a.lw(12, 20, S['home'] + k); a.sw(12, 10, 0x10 + k); a.sw(12, 10, 0x100 + k); a.sw(12, 11, 2416 + k)
        a.sw(0, 10, 0x30 + k)
    a.jump('ko_next')
    a.label('ko_vanished_done'); a.addiu(8, 0, VANISHED); a.sw(8, 20, S['state']); a.sw(0, 20, S['wave'])
    a.jump('ko_next')
    a.label('ko_active')
    emit_hp_row(a, 17, 'ko_next')
    a.lw(8, 21); a.branch(7, 8, 0, 'ko_alive')
    a.addiu(8, 0, KO); a.sw(8, 20, S['state']); a.lw(8, 16, C['tick']); a.sw(8, 20, S['ko_tick'])
    a.lw(8, 16, C['wave_mask']); a.r(0x27, 9, 23, 0); a.r(0x24, 8, 8, 9); a.sw(8, 16, C['wave_mask'])
    a.jump('ko_next')
    a.label('ko_alive')
    # A fighter admitted outside an intro: native taunt once it stands idle, then its CPU flag back.
    a.lw(8, 20, S['admitted']); a.branch(4, 8, 0, 'ko_next')
    a.lw(8, 16, C['state']); a.addiu(9, 0, INTRO); a.branch(4, 8, 9, 'ko_next')
    a.lw(8, 16, C['tick']); a.lw(9, 20, S['admitted']); a.r(0x23, 8, 8, 9); a.lw(9, 16, C['release'])
    a.r(0x2B, 8, 8, 9); a.branch(5, 8, 0, 'ko_taunt')
    a.addiu(8, 0, 1); emit_cpu(a, 17, 8, 18); a.sw(0, 20, S['admitted']); a.jump('ko_next')
    a.label('ko_taunt')
    a.lw(8, 20, S['taunted']); a.branch(5, 8, 0, 'ko_next')
    a.lw(8, 18, 0x948)
    for value in (11, 15, 17):
        a.addiu(9, 0, value); a.branch(4, 8, 9, 'ko_idle')
    a.jump('ko_next')
    a.label('ko_idle'); a.lw(8, 18, 0x94C); a.addiu(9, 0, -1); a.branch(5, 8, 9, 'ko_next')
    a.addiu(8, 0, 1); a.sw(8, 20, S['taunted'])
    a.move(4, 18); a.addiu(5, 0, 67); a.call(A(0x1E0290))
    a.label('ko_next'); a.addiu(17, 17, 1); a.i(11, 8, 17, 12); a.branch(5, 8, 0, 'ko_loop')
    a.li(16, CONTROL)
    a.lw(8, 16, C['state'])
    a.addiu(9, 0, FIGHT); a.branch(4, 8, 9, 'fight')
    a.addiu(9, 0, COUNTDOWN); a.branch(4, 8, 9, 'countdown')
    a.addiu(9, 0, INTRO); a.branch(4, 8, 9, 'intro')
    a.jump('done')

    # FIGHT: reinforcements of the current wave as slots become ready; the wave ends when all are down.
    a.label('fight')
    a.lw(8, 16, C['pending']); a.branch(6, 8, 0, 'fight_check')
    a.lw(4, 16, C['wave']); a.addiu(4, 4, 1); a.call(FIND)
    a.r(0x2A, 8, 2, 0); a.branch(5, 8, 0, 'fight_check')                 # v0 < 0: nothing ready
    a.move(17, 2); a.move(4, 2); a.call(ADMIT); a.branch(4, 2, 0, 'fight_check')
    a.li(16, CONTROL)
    a.addiu(9, 0, 1); a.r(4, 9, 17, 9)
    a.lw(8, 16, C['wave_mask']); a.r(0x25, 8, 8, 9); a.sw(8, 16, C['wave_mask'])
    a.lw(8, 16, C['pending']); a.addiu(8, 8, -1); a.sw(8, 16, C['pending'])
    a.label('fight_check')
    a.li(16, CONTROL)
    a.lw(8, 16, C['wave_mask']); a.branch(5, 8, 0, 'done')
    a.lw(8, 16, C['pending']); a.branch(6, 8, 0, 'wave_done')
    # Fighters that never became ready (a load failed for good) are given up after GIVE_UP updates.
    a.lw(8, 16, C['tick']); a.lw(9, 16, C['pending_deadline']); a.r(0x2B, 8, 8, 9); a.branch(5, 8, 0, 'done')
    a.sw(0, 16, C['pending'])
    a.label('wave_done')
    a.lw(8, 16, C['wave']); a.addiu(8, 8, 1); a.sw(8, 16, C['reached'])
    a.lw(9, 16, C['waves']); a.r(0x2B, 9, 8, 9); a.branch(5, 9, 0, 'next_wave')
    # The last enemy of the last wave: the story's forced result names the player team the winner.
    a.addiu(8, 0, WON); a.sw(8, 16, C['state']); a.addiu(8, 0, 1); a.sw(8, 16, C['result'])
    a.lw(8, 16, C['tick']); a.lw(9, 16, C['banner']); a.r(0x21, 8, 8, 9); a.sw(8, 16, C['banner_until'])
    a.lw(8, 16, C['player_team']); a.li(9, story.CONTROL + 96); a.sw(8, 9); a.jump('done')
    a.label('next_wave')
    a.addiu(8, 0, COUNTDOWN); a.sw(8, 16, C['state'])
    a.lw(8, 16, C['tick']); a.lw(9, 16, C['countdown']); a.r(0x21, 8, 8, 9); a.sw(8, 16, C['countdown_end'])
    # The break: the player team moves (BREAK); every enemy body (KO'd, removed or still loading) is protected, so
    # no attack lands on it. The intro protects every participant and its release lifts all of it.
    a.li(8, story.CONTROL + 48); a.lw(9, 8); a.lw(10, 16, C['enemy_mask']); a.r(0x25, 9, 9, 10); a.sw(9, 8)
    a.jump('done')

    # COUNTDOWN: at its end the intro starts once the next wave is loaded (or after the overtime with what is).
    a.label('countdown')
    a.lw(8, 16, C['tick']); a.lw(9, 16, C['countdown_end']); a.r(0x2B, 10, 8, 9); a.branch(5, 10, 0, 'done')
    a.lw(4, 16, C['wave']); a.addiu(4, 4, 2); a.call(COUNT)
    a.li(16, CONTROL); a.move(22, 2)
    a.lw(8, 16, C['wave']); a.addiu(8, 8, 1); a.r(0, 8, 0, 8, WAVE_SHIFT); a.li(9, WAVES + WAVE_HEADER)
    a.r(0x21, 8, 8, 9); a.lw(23, 8)                                       # s7 = fighters in the next wave
    a.r(0x2B, 8, 22, 23); a.branch(4, 8, 0, 'start_intro')                 # all ready
    a.lw(8, 16, C['tick']); a.lw(9, 16, C['countdown_end']); a.r(0x23, 8, 8, 9); a.lw(9, 16, C['overtime'])
    a.r(0x2B, 10, 8, 9); a.branch(5, 10, 0, 'done')
    a.branch(5, 22, 0, 'start_intro')                                     # overtime: start with what is ready
    a.r(0, 9, 0, 9, 2); a.r(0x2B, 10, 8, 9); a.branch(5, 10, 0, 'done')    # 4x overtime: start with nobody
    a.label('start_intro')
    a.lw(8, 16, C['wave']); a.addiu(8, 8, 1); a.sw(8, 16, C['wave']); a.sw(23, 16, C['pending'])
    a.addiu(8, 0, INTRO); a.sw(8, 16, C['state']); a.lw(8, 16, C['tick']); a.sw(8, 16, C['phase_tick'])
    a.sw(8, 16, C['intro_since']); a.sw(0, 16, C['intro_phase'])
    a.lw(9, 16, C['give_up']); a.r(0x21, 9, 8, 9); a.sw(9, 16, C['pending_deadline'])
    a.sw(0, 16, C['last_admit']); a.sw(0, 16, C['intro_admitted'])
    a.lw(9, 16, C['banner']); a.r(0x21, 8, 8, 9); a.sw(8, 16, C['banner_until'])
    # Everyone protected: no damage, no commands but get-up/taunt (story_runtime protection hooks).
    a.li(8, story.CONTROL + 48); a.lw(9, 8); a.lw(10, 16, C['participants']); a.r(0x25, 9, 9, 10); a.sw(9, 8)
    # HP back for every living player fighter, once, as the wave starts (a KO'd one stays down: only the revive
    # feature brings it back, also during the break, and a fighter revived then gets the refill too).
    a.lw(22, 16, C['refill']); a.branch(4, 22, 0, 'done')
    a.move(17, 0)
    a.label('refill_loop')
    a.addiu(9, 0, 1); a.r(4, 9, 17, 9); a.lw(8, 16, C['player_mask']); a.r(0x24, 8, 8, 9)
    a.branch(4, 8, 0, 'refill_next')
    emit_hp_row(a, 17, 'refill_next')
    a.lw(8, 21); a.branch(6, 8, 0, 'refill_next')
    a.lw(9, 21, 4); a.addiu(10, 0, -1); a.branch(4, 22, 10, 'refill_full')
    a.r(0x21, 8, 8, 22); a.r(0x2B, 10, 9, 8); a.branch(4, 10, 0, 'refill_store')
    a.label('refill_full'); a.move(8, 9)
    a.label('refill_store'); a.sw(8, 21)
    a.label('refill_next'); a.addiu(17, 17, 1); a.i(11, 8, 17, 12); a.branch(5, 8, 0, 'refill_loop')
    a.jump('done')

    # INTRO: one entrant at a time. Each is spawned just before its own shot (native spawn, placed on the arc
    # facing the team, standing at once: no fall, no get-up), then plays the native per-fighter intro (intro pose,
    # the dialogue clip, its voice line, its own camera track shown full screen) for intro_len; the next entrant
    # starts in the same update on the same shared camera (no gameplay shot between). A fighter of this wave still
    # loading is waited for (bounded by intro_wait) while a slot is free for it; the fight starts after the last.
    a.label('intro')
    a.lw(8, 16, C['intro_phase'])
    a.addiu(9, 0, 2); a.branch(4, 8, 9, 'intro_playing')
    a.addiu(9, 0, 3); a.branch(4, 8, 9, 'intro_tail')
    # phase 0: the next entrant (or wait for one)
    a.label('intro_next')
    a.li(16, CONTROL)
    a.lw(8, 16, C['pending']); a.branch(6, 8, 0, 'intro_queue_done')
    a.lw(4, 16, C['wave']); a.addiu(4, 4, 1); a.call(FIND); a.li(16, CONTROL)
    a.r(0x2A, 8, 2, 0); a.branch(5, 8, 0, 'intro_wait')                  # v0 < 0: nobody ready
    a.move(17, 2); a.move(4, 2); a.call(ADMIT); a.li(16, CONTROL); a.branch(4, 2, 0, 'intro_wait')
    a.addiu(9, 0, 1); a.r(4, 9, 17, 9)
    a.lw(8, 16, C['wave_mask']); a.r(0x25, 8, 8, 9); a.sw(8, 16, C['wave_mask'])
    a.lw(8, 16, C['intro_admitted']); a.r(0x25, 8, 8, 9); a.sw(8, 16, C['intro_admitted'])
    a.lw(8, 16, C['pending']); a.addiu(8, 8, -1); a.sw(8, 16, C['pending'])
    a.sw(17, 16, C['entrant']); a.sw(17, 16, C['intro_actor'])
    # Players and their CPU teammates look at the entrant (native target table and private AI target).
    a.move(18, 0)
    a.label('look_loop')
    a.addiu(9, 0, 1); a.r(4, 9, 18, 9); a.lw(8, 16, C['player_mask']); a.r(0x24, 8, 8, 9)
    a.branch(4, 8, 0, 'look_next')
    a.r(0, 9, 0, 18, 2); a.li(8, core.TABLE); a.r(0x21, 8, 8, 9); a.sw(17, 8)
    a.r(0, 9, 0, 18, 6); a.li(8, ai.DESCRIPTORS[0] + 24); a.r(0x21, 8, 8, 9)
    a.r(0, 10, 0, 17, 6); a.li(11, ai.DESCRIPTORS[0]); a.r(0x21, 10, 10, 11); a.sw(10, 8)
    a.label('look_next'); a.addiu(18, 18, 1); a.i(11, 8, 18, 12); a.branch(5, 8, 0, 'look_loop')
    a.move(4, 17); a.addiu(5, 0, 1); a.call(PRESENT); a.li(16, CONTROL)
    a.addiu(8, 0, 2); a.sw(8, 16, C['intro_phase']); a.lw(8, 16, C['tick']); a.sw(8, 16, C['intro_since'])
    a.lw(9, 16, C['step']); a.sw(9, 16, C['intro_len']); a.sw(0, 16, C['intro_posed'])
    a.jump('done')
    # Nobody ready: wait while a slot is free for the host to load this wave's next fighter into (bounded).
    a.label('intro_wait')
    a.lw(8, 16, C['tick']); a.lw(9, 16, C['intro_since']); a.r(0x23, 8, 8, 9); a.lw(9, 16, C['intro_wait'])
    a.r(0x2B, 8, 8, 9); a.branch(4, 8, 0, 'intro_queue_done')
    a.call(LOADABLE); a.li(16, CONTROL); a.branch(4, 2, 0, 'intro_queue_done')
    a.lw(8, 16, C['intro_waited']); a.addiu(8, 8, 1); a.sw(8, 16, C['intro_waited'])
    a.jump('done')
    a.label('intro_queue_done')
    # After the last entrant the shared camera ends (PRESENT a1 = 3), then the tail and the release.
    a.lw(8, 16, C['intro_camera']); a.branch(4, 8, 0, 'intro_camera_off')
    a.addiu(4, 8, -1); a.addiu(5, 0, 3); a.call(PRESENT); a.li(16, CONTROL)
    a.label('intro_camera_off')
    a.addiu(8, 0, 3); a.sw(8, 16, C['intro_phase']); a.lw(8, 16, C['tick']); a.sw(8, 16, C['last_admit'])
    a.jump('intro_tail')
    # phase 2: the native intro plays out: its entrance pose (action 67, about 3.6 s in) runs to its end (at least
    # intro_min in); an entrant with no pose by intro_nopose ends there; never past intro_len, nor once KO'd. Then
    # the next one in this update.
    a.label('intro_playing')
    a.lw(17, 16, C['intro_actor'])
    emit_hp_row(a, 17, 'intro_finish_now')
    a.lw(8, 21); a.branch(6, 8, 0, 'intro_finish_now')
    a.lw(9, 16, C['tick']); a.lw(8, 16, C['intro_since']); a.r(0x23, 19, 9, 8)          # s3 = elapsed
    a.lw(10, 16, C['intro_len']); a.r(0x2B, 10, 19, 10); a.branch(4, 10, 0, 'intro_finish_now')
    a.lw(8, 18, 0x948); a.addiu(9, 0, 67); a.branch(5, 8, 9, 'intro_not_posing')
    a.addiu(8, 0, 1); a.sw(8, 16, C['intro_posed']); a.jump('done')
    a.label('intro_not_posing')
    a.lw(8, 16, C['intro_posed']); a.branch(4, 8, 0, 'intro_no_pose_yet')
    a.lw(10, 16, C['intro_min']); a.r(0x2B, 10, 19, 10); a.branch(4, 10, 0, 'intro_finish_now')
    a.jump('done')
    a.label('intro_no_pose_yet')
    a.lw(10, 16, C['intro_nopose']); a.r(0x2B, 10, 19, 10); a.branch(4, 10, 0, 'intro_finish_now')
    a.jump('done')
    a.label('intro_finish_now')
    a.lw(4, 16, C['intro_actor']); a.addiu(5, 0, 2); a.call(PRESENT); a.li(16, CONTROL)   # the camera stays
    a.sw(0, 16, C['intro_phase']); a.lw(8, 16, C['tick']); a.sw(8, 16, C['intro_since'])
    a.jump('intro_next')
    a.label('intro_tail')
    a.li(16, CONTROL)
    a.lw(8, 16, C['last_admit']); a.branch(4, 8, 0, 'intro_release')    # nothing ready: fight at once
    a.lw(9, 16, C['tick']); a.r(0x23, 9, 9, 8); a.lw(10, 16, C['tail']); a.r(0x2B, 10, 9, 10)
    a.branch(5, 10, 0, 'done')
    a.label('intro_release')
    a.li(8, story.CONTROL + 48); a.lw(9, 8); a.lw(10, 16, C['participants']); a.r(0x27, 10, 10, 0)
    a.r(0x24, 9, 9, 10); a.sw(9, 8)
    a.move(17, 0)
    a.label('release_loop')
    a.addiu(9, 0, 1); a.r(4, 9, 17, 9); a.lw(8, 16, C['intro_admitted']); a.r(0x24, 8, 8, 9)
    a.branch(4, 8, 0, 'release_next')
    emit_hp_row(a, 17, 'release_next')
    a.addiu(8, 0, 1); emit_cpu(a, 17, 8, 18)
    a.r(0, 9, 0, 17, 6); a.li(8, SLOTS); a.r(0x21, 8, 8, 9); a.sw(0, 8, S['admitted'])
    a.label('release_next'); a.addiu(17, 17, 1); a.i(11, 8, 17, 12); a.branch(5, 8, 0, 'release_loop')
    a.li(16, CONTROL); a.addiu(8, 0, FIGHT); a.sw(8, 16, C['state'])
    a.sw(0, 16, C['intro_phase']); a.sw(0, 16, C['intro_queue']); a.sw(0, 16, C['intro_admitted'])
    a.label('done'); unframe(a, 0x80)
    data = a.finish(); assert len(data) <= FIND - WAVE, len(data)
    return data


def find_code():
    """FIND: a0 = wave number (1-based) -> v0 the lowest enemy physical READY for it, else -1 (leaf, t0..t4)."""
    a = Assembler(FIND)
    a.li(8, SLOTS); a.move(9, 0); a.li(12, CONTROL); a.lw(12, 12, C['enemy_mask'])
    a.label('loop'); a.addiu(10, 0, 1); a.r(4, 10, 9, 10); a.r(0x24, 10, 10, 12); a.branch(4, 10, 0, 'next')
    a.lw(10, 8, S['state']); a.addiu(11, 0, READY); a.branch(5, 10, 11, 'next')
    a.lw(10, 8, S['wave']); a.branch(5, 10, 4, 'next')
    a.move(2, 9); a.jr()
    a.label('next'); a.addiu(8, 8, SLOT_STRIDE); a.addiu(9, 9, 1); a.i(11, 10, 9, 12); a.branch(5, 10, 0, 'loop')
    a.addiu(2, 0, -1); a.jr()
    data = a.finish(); assert len(data) <= COUNT - FIND; return data


def count_code():
    """COUNT: a0 = wave number (1-based) -> v0 enemy slots READY for it (leaf, t0..t4)."""
    a = Assembler(COUNT)
    a.li(8, SLOTS); a.move(9, 0); a.move(2, 0); a.li(12, CONTROL); a.lw(12, 12, C['enemy_mask'])
    a.label('loop'); a.addiu(10, 0, 1); a.r(4, 10, 9, 10); a.r(0x24, 10, 10, 12); a.branch(4, 10, 0, 'next')
    a.lw(10, 8, S['state']); a.addiu(11, 0, READY); a.branch(5, 10, 11, 'next')
    a.lw(10, 8, S['wave']); a.branch(5, 10, 4, 'next'); a.addiu(2, 2, 1)
    a.label('next'); a.addiu(8, 8, SLOT_STRIDE); a.addiu(9, 9, 1); a.i(11, 10, 9, 12); a.branch(5, 10, 0, 'loop')
    a.jr()
    data = a.finish(); assert len(data) <= LOADABLE - COUNT; return data


def loadable_code():
    """LOADABLE: v0 1 when an enemy extra slot is free (removed, so the host can load the wave's next fighter into
    it), else 0 (leaf, t0..t4). The intro waits for such a load (bounded by intro_wait)."""
    a = Assembler(LOADABLE)
    a.li(8, SLOTS); a.move(9, 0); a.li(12, CONTROL); a.lw(12, 12, C['enemy_mask'])
    a.label('loop'); a.addiu(10, 0, 1); a.r(4, 10, 9, 10); a.r(0x24, 10, 10, 12); a.branch(4, 10, 0, 'next')
    a.addiu(10, 0, 1); a.branch(4, 9, 10, 'next')                                     # the native leader slot
    a.lw(10, 8, S['state']); a.addiu(11, 0, VANISHED); a.branch(5, 10, 11, 'next')
    a.addiu(2, 0, 1); a.jr()
    a.label('next'); a.addiu(8, 8, SLOT_STRIDE); a.addiu(9, 9, 1); a.i(11, 10, 9, 12); a.branch(5, 10, 0, 'loop')
    a.move(2, 0); a.jr()
    data = a.finish(); assert len(data) <= ADMIT - LOADABLE; return data


def present_code():
    """PRESENT: a0 physical, a1 1 = start the native per-fighter intro, 0 = end it (both idempotent).

    Start (native primitives of the pre-fight intro, research p87 intro notes): 209EE8 (flag 0xEF: action 1, the
    intro pose), 24F5D8(model, 2, line 0) (the dialogue clip, if this body has one), 23DE60(model id, 0) (its own
    camera track model+176, bound to the model, so no angles are needed), the voice line on the side's dialogue
    stream (265970 stop, 265E38 play), and CONTROL.intro_camera = physical + 1 for SELECT (one full-screen view).
    Without a camera track the entrant only taunts (action 67). End: 24F5D8(model, 0, -1), the voice stopped,
    209F20 (flag 0xF0: back to idle), 23DCB8 only while the camera record still runs our track."""
    a = Assembler(PRESENT); frame(a, 0x80)
    a.move(17, 4); a.move(22, 5); a.li(16, CONTROL)
    a.addiu(8, 17, -1); a.i(11, 8, 8, 11); a.branch(4, 8, 0, 'done')
    emit_hp_row(a, 17, 'done')
    a.lw(8, 18, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, 'done'); a.move(23, 8)        # s7 model id
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(19, 8)          # s3 model
    a.li(8, 0x100000); a.r(0x2B, 8, 19, 8); a.branch(5, 8, 0, 'done')
    a.li(8, 0x08000000 - 0x1670); a.r(0x2B, 8, 8, 19); a.branch(5, 8, 0, 'done')
    a.addiu(8, 0, 1); a.branch(5, 22, 8, 'end')                           # a1 != 1: an end
    # start (the shared camera may still run the previous entrant's track: ours, handed over without a gap)
    a.lw(8, 19, 176); a.branch(4, 8, 0, 'taunt')
    a.lw(8, 28, -22180); a.branch(4, 8, 0, 'taunt')                       # the cinematic camera record
    a.lw(9, 8, 812); a.branch(5, 9, 0, 'taunt')                            # someone drives it directly
    a.lw(9, 8, 776); a.i(12, 9, 9, 1); a.branch(4, 9, 0, 'free')           # no track is running
    a.lw(9, 8, 704); a.lw(10, 16, C['intro_track']); a.branch(5, 9, 10, 'taunt')   # someone else's track
    a.lw(9, 16, C['intro_chained']); a.addiu(9, 9, 1); a.sw(9, 16, C['intro_chained'])
    a.label('free')
    a.move(4, 18); a.call(A(0x209EE8))
    a.lw(8, 19, 1880); a.branch(4, 8, 0, 'no_clip')
    a.move(4, 19); a.addiu(5, 0, 2); a.move(6, 0); a.call(A(0x24F5D8))
    a.label('no_clip')
    a.move(4, 23); a.move(5, 0); a.call(A(0x23DE60))
    a.lw(8, 19, 176); a.sw(8, 16, C['intro_track'])
    a.i(12, 21, 17, 1); a.addiu(4, 21, 4); a.call(A(0x265970))
    a.move(4, 21); a.lw(5, 19, 12); a.move(6, 0); a.addiu(7, 0, 128); a.move(8, 0); a.call(A(0x265E38))
    a.li(16, CONTROL); a.addiu(8, 17, 1); a.sw(8, 16, C['intro_camera'])
    a.lw(8, 16, C['intros']); a.addiu(8, 8, 1); a.sw(8, 16, C['intros'])
    a.jump('done')
    a.label('taunt')
    a.move(4, 18); a.addiu(5, 0, 67); a.call(A(0x1E0290))
    a.li(16, CONTROL); a.lw(8, 16, C['taunts']); a.addiu(8, 8, 1); a.sw(8, 16, C['taunts'])
    a.jump('done')
    # end: a1 0 = all of it; 2 = the entrant's clip, voice and pose only (the shared camera and its track stay for
    # the next entrant's start in the same update); 3 = the shared camera only (after the last entrant)
    a.label('end')
    a.lw(8, 16, C['intro_camera']); a.addiu(9, 17, 1); a.branch(5, 8, 9, 'done')
    a.addiu(9, 0, 2); a.branch(4, 22, 9, 'end_actor')
    a.sw(0, 16, C['intro_camera'])
    a.addiu(9, 0, 3); a.branch(4, 22, 9, 'camera_end')
    a.label('end_actor')
    a.lw(8, 19, 1880); a.branch(4, 8, 0, 'no_clip_end')
    a.move(4, 19); a.move(5, 0); a.addiu(6, 0, -1); a.call(A(0x24F5D8))
    a.label('no_clip_end')
    a.i(12, 4, 17, 1); a.call(A(0x265F40))
    a.move(4, 18); a.call(A(0x209F20))
    a.addiu(9, 0, 2); a.branch(4, 22, 9, 'done')
    a.label('camera_end')
    a.lw(8, 28, -22180); a.branch(4, 8, 0, 'done')
    a.lw(9, 8, 704); a.li(16, CONTROL); a.lw(10, 16, C['intro_track']); a.branch(5, 9, 10, 'done')
    a.lw(9, 8, 768); a.branch(5, 9, 19, 'done')
    a.call(A(0x23DCB8))
    a.label('done'); unframe(a, 0x80)
    data = a.finish(); assert len(data) <= COPIER - PRESENT, len(data); return data


def select_code():
    """SELECT: in front of cinematic_policy's camera selector (native 23EFF0's entry jumps here). While a wave
    intro's camera runs, present the cinematic camera as ONE full-screen view in every layout (the selector's own
    stage-camera block: 23EF98(0), 23EFD0(1), 23EE78(0,1), the manager's camera, 23E6A0); else the selector."""
    import cinematic_policy as policy
    import cinematic_camera_state as camera
    a = Assembler(SELECT)
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'selector')
    a.lw(9, 8, C['manager']); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'selector')
    a.lw(9, 8, C['intro_camera']); a.branch(4, 9, 0, 'selector')
    a.lw(9, 28, -22180); a.branch(4, 9, 0, 'selector')
    frame(a, 0x80)
    a.call(camera.CODE); a.i(63, 3, 29, 0x70)
    a.move(4, 0); a.call(A(0x23EF98)); a.addiu(4, 0, 1); a.call(A(0x23EFD0))
    a.move(4, 0); a.addiu(5, 0, 1); a.call(A(0x23EE78))
    a.lw(4, 28, -22180); a.lw(8, 28, -22172); a.sw(4, 8, 0xC40)
    a.addiu(5, 0, 1); a.call(A(0x23E6A0))
    a.i(55, 3, 29, 0x70); a.addiu(2, 0, 1)
    unframe(a, 0x80)
    a.label('selector'); a.jump(policy.CODE)
    data = a.finish(); assert len(data) <= PRESENT - SELECT, len(data); return data


def watch_code():
    """WATCH (CPU-only runs): L1 / R1 on either PCSX2 controller cycles the watched fighter through ORDER (the player
    team, then the enemies), skipping KO'd, removed and not yet admitted fighters; the choice is the spectator
    switch's lock (its camera keeps that fighter); a watched fighter that is gone moves the camera on by itself."""
    import spectator_switch as spec
    import fresh_team_camera as fresh
    import story_runtime as story
    a = Assembler(WATCH); frame(a, 0x80)
    a.li(16, CONTROL)
    a.move(20, 0)                                                           # s4 step: +1 R1, -1 L1
    for port in (0, 1):
        a.li(8, spec.pad_buttons(port)); a.lw(9, 8); a.lw(10, 16, C['watch_buttons'] + 4 * port)
        a.sw(9, 16, C['watch_buttons'] + 4 * port)
        a.r(0x27, 10, 10, 0); a.r(0x24, 9, 9, 10)                         # newly pressed
        a.i(12, 10, 9, 0x800); a.branch(4, 10, 0, f'no_r1_{port}'); a.addiu(20, 0, 1)
        a.label(f'no_r1_{port}')
        a.i(12, 10, 9, 0x400); a.branch(4, 10, 0, f'no_l1_{port}'); a.addiu(20, 0, -1)
        a.label(f'no_l1_{port}')
    # The watched fighter (physical + 1) is still there? Otherwise move on as if R1 was pressed.
    a.lw(17, 16, C['watched']); a.branch(4, 17, 0, 'check_step')
    a.addiu(4, 17, -1); a.call(WATCH + 0x600); a.li(16, CONTROL); a.branch(5, 2, 0, 'check_step')
    a.branch(5, 20, 0, 'check_step'); a.addiu(20, 0, 1)
    a.label('check_step'); a.branch(4, 20, 0, 'done')
    # Position of the watched fighter in ORDER (or -1), then the next living one in the step's direction.
    a.lw(21, 16, C['order_count']); a.branch(6, 21, 0, 'done')
    a.addiu(22, 0, -1); a.move(18, 0)
    a.label('find_pos'); a.li(8, ORDER); a.r(0x21, 8, 8, 18); a.i(36, 8, 8, 0); a.addiu(8, 8, 1)
    a.branch(5, 8, 17, 'find_next'); a.move(22, 18)
    a.label('find_next'); a.addiu(18, 18, 1); a.branch(5, 18, 21, 'find_pos')
    a.r(0x2A, 8, 22, 0); a.branch(4, 8, 0, 'have_pos'); a.addiu(22, 0, -1)
    a.addiu(8, 0, -1); a.branch(5, 20, 8, 'have_pos'); a.move(22, 21)     # L1 from nothing: start at the end
    a.label('have_pos'); a.move(18, 0)
    a.label('scan'); a.addiu(18, 18, 1); a.r(0x2A, 8, 21, 18); a.branch(5, 8, 0, 'done')   # a lap: nobody
    a.r(24, 0, 18, 20); a.r(18, 9, 0); a.r(0x21, 9, 22, 9)                 # pos + k*step (mult/mflo)
    a.label('wrap_low'); a.r(0x2A, 8, 9, 0); a.branch(4, 8, 0, 'wrap_high'); a.r(0x21, 9, 9, 21); a.jump('wrap_low')
    a.label('wrap_high'); a.r(0x2A, 8, 9, 21); a.branch(5, 8, 0, 'wrapped'); a.r(0x23, 9, 9, 21); a.jump('wrap_high')
    a.label('wrapped'); a.li(8, ORDER); a.r(0x21, 8, 8, 9); a.i(36, 23, 8, 0)               # s7 candidate
    a.move(4, 23); a.call(WATCH + 0x600); a.li(16, CONTROL); a.branch(4, 2, 0, 'scan')
    # Watch it: the spectator switch's lock for side 0 and the successor camera's owner.
    a.addiu(8, 23, 1); a.sw(8, 16, C['watched'])
    a.li(9, spec.CONTROL); a.sw(8, 9, spec.FIELDS['lock']); a.sw(23, 9, spec.FIELDS['subject'])
    a.li(9, fresh.SUCCESSOR_CONTROL); a.sw(23, 9, spec.SUCCESSOR_OWNER)
    a.lw(8, 16, C['tick']); a.addiu(8, 8, 3 * ACTOR_HZ); a.sw(8, 16, C['watch_until'])
    a.label('done'); unframe(a, 0x80)
    data = a.finish(); assert len(data) <= 0x600, len(data)
    # WATCH+0x600 ALIVE: a0 physical -> v0 1 when it can be watched (leaf: t0..t4).
    b = Assembler(WATCH + 0x600)
    b.move(2, 0)
    b.li(8, core.MODE + 4); b.lw(8, 8); b.r(0x2B, 9, 4, 8); b.branch(4, 9, 0, 'no')
    b.addiu(9, 0, 1); b.r(4, 9, 4, 9)
    b.li(8, part.CONSUMED); b.lw(8, 8); b.r(0x24, 8, 8, 9); b.branch(5, 8, 0, 'no')
    b.li(8, story.CONTROL + 112); b.lw(8, 8); b.r(0x24, 8, 8, 9); b.branch(5, 8, 0, 'no')
    b.r(0, 10, 0, 4, 2); b.li(8, feed.CONTROL + 0x40); b.r(0x21, 8, 8, 10); b.lw(8, 8); b.branch(5, 8, 0, 'no')
    b.li(8, core.POINTERS); b.r(0x21, 8, 8, 10); b.lw(8, 8); b.branch(4, 8, 0, 'no')
    b.lw(10, 8, 0x994); b.lw(11, 8, 0x998); b.r(0x2B, 12, 10, 11); b.branch(4, 12, 0, 'no')
    b.r(0, 11, 0, 10, 7); b.r(0, 12, 0, 10, 5); b.r(0x21, 11, 11, 12); b.r(0, 12, 0, 10, 2); b.r(0x21, 11, 11, 12)
    b.r(0x21, 11, 11, 8); b.lw(11, 11, 0x9A4 + 64); b.branch(6, 11, 0, 'no')
    b.addiu(2, 0, 1)
    b.label('no'); b.jr()
    alive = b.finish(); assert len(alive) <= 0x200
    return data + bytes(0x600 - len(data)) + alive


def update_code():
    a = Assembler(UPDATE); frame(a, 0x80)
    scope(a, 'done')
    a.li(8, A(0x3337B8)); a.lw(8, 8); a.i(12, 8, 8, 0x3900); a.branch(5, 8, 0, 'done')
    a.lw(8, 16, C['tick']); a.addiu(8, 8, 1); a.sw(8, 16, C['tick'])
    gates_code(a)
    a.call(COPIER); a.call(RUNNER)
    # Host-requested admission (tests, the probe); the wave logic calls ADMIT itself.
    a.li(16, CONTROL)
    a.lw(17, 16, C['admit_request']); a.lw(8, 16, C['admit_ack']); a.branch(4, 17, 8, 'no_admit')
    a.lw(4, 16, C['admit_physical']); a.call(ADMIT); a.li(16, CONTROL)
    a.sw(2, 16, C['admit_status']); a.sw(17, 16, C['admit_ack'])
    a.label('no_admit')
    a.lw(8, 16, C['waves']); a.branch(4, 8, 0, 'done')            # loader-only installs (probes) have no plan
    a.call(WAVE)
    a.li(16, CONTROL); a.lw(8, 16, C['spectate']); a.branch(4, 8, 0, 'done')
    a.call(WATCH)
    a.label('done'); unframe(a, 0x80)
    data = a.finish(); assert len(data) <= WAVE - UPDATE, len(data); return data


# ---------------------------------------------------------------- presentation (per view, on the world draw)
DIGIT_UV = (4, 3, 28, 29)          # glyph box inside a 32x32 cell of the native timer atlas (hud index 0)
DIGIT_SCALE = 1.5                  # displayed size: 36 x 39 pixels per digit (half of the first version)
DIGIT_STEP = 30                    # pixels between two digits
COUNTDOWN_LABEL = 8                # native font units of NEXT WAVE / GET READY (was 11 / 12)
COUNTDOWN_LABEL_Y, COUNTDOWN_DIGITS_Y = 40, 52   # their tops below the view's top (screen_y)
WHITE, GOLD, RED = 0x80F0F0F0, 0x8040D8FF, 0x805060FF
DRAW_FRAME = 0x200                 # regs at 0, NART parameter block at +0x100, saved a0..a3/v0 at +0x180


def emit_text_width(a, string_reg, units_reg, out):
    """out = native-font width (GS units) of the string at string_reg (t0..t3; METRICS advance byte * units)."""
    import native_hud_style as style
    tag = f'w{len(a.words)}'
    a.move(out, 0); a.move(8, string_reg)
    a.label(tag + 'loop'); a.i(36, 9, 8, 0); a.branch(4, 9, 0, tag + 'done')
    a.i(12, 9, 9, 127); a.r(0, 9, 0, 9, 4); a.li(10, style.METRICS); a.r(0x21, 9, 9, 10); a.i(36, 9, 9, 9)
    a.r(0x21, out, out, 9); a.addiu(8, 8, 1); a.jump(tag + 'loop')
    a.label(tag + 'done'); a.r(24, 0, out, units_reg); a.r(18, out, 0)


def emit_centered(a, string_reg, cx_reg, y_reg, units, colour, native_reg):
    """Draw a string centred on cx (GS units) with its top at y (GS units): native font when the native HUD style
    is installed (native_reg != 0), else the classic compact font. Clobbers a0..a3, t0..t5."""
    import native_hud_style as style
    tag = f'c{len(a.words)}'
    a.branch(4, native_reg, 0, tag + 'classic')
    a.addiu(13, 0, units); emit_text_width(a, string_reg, 13, 12)
    a.r(3, 12, 0, 12, 1); a.r(0x23, 5, cx_reg, 12)
    a.move(4, string_reg); a.move(6, y_reg); a.li(7, colour); a.addiu(8, 0, units); a.call(style.NTEXT_SCALED)
    a.jump(tag + 'end')
    a.label(tag + 'classic')
    a.move(8, string_reg); a.move(12, 0)
    a.label(tag + 'len'); a.i(36, 9, 8, 0); a.branch(4, 9, 0, tag + 'counted'); a.addiu(12, 12, 1); a.addiu(8, 8, 1)
    a.jump(tag + 'len')
    a.label(tag + 'counted'); a.addiu(9, 0, 8 * 16 // 2); a.r(24, 0, 12, 9); a.r(18, 12, 0)
    a.r(0x23, 5, cx_reg, 12); a.move(4, string_reg); a.move(6, y_reg); a.li(7, colour); a.call(feed.TEXT)
    a.label(tag + 'end')


def emit_digit(a, digit_reg, x_reg, y_reg):
    """One native timer digit (0..9) with its top-left at (x, y) GS units, DIGIT_SCALE times its atlas size."""
    import native_hud_style as style
    u0, v0, u1, v1 = DIGIT_UV
    a.i(12, 9, digit_reg, 3); a.r(0, 9, 0, 9, 5)                         # column * 32
    a.r(2, 10, 0, digit_reg, 2); a.r(0, 10, 0, 10, 5)                    # row * 32
    a.addiu(11, 9, u0); a.r(0, 11, 0, 11, 4); a.sw(11, 29, 0x100 + 8)
    a.addiu(11, 10, v0); a.r(0, 11, 0, 11, 4); a.sw(11, 29, 0x100 + 12)
    a.addiu(11, 9, u1); a.r(0, 11, 0, 11, 4); a.sw(11, 29, 0x100 + 16)
    a.addiu(11, 10, v1); a.r(0, 11, 0, 11, 4); a.sw(11, 29, 0x100 + 20)
    a.sw(x_reg, 29, 0x100 + 24); a.sw(y_reg, 29, 0x100 + 28)
    a.addiu(11, x_reg, int((u1 - u0) * DIGIT_SCALE * 16)); a.sw(11, 29, 0x100 + 32)
    a.addiu(11, y_reg, int((v1 - v0) * DIGIT_SCALE * 16)); a.sw(11, 29, 0x100 + 36)
    for off, value in ((0, style.SLOT['timer']), (4, -1), (40, 0x80808080), (44, 0x80808080), (48, 0), (52, 0)):
        a.li(8, value & 0xFFFFFFFF); a.sw(8, 29, 0x100 + off)
    a.addiu(4, 29, 0x100); a.call(style.NART)


def draw_code(story_draw, at=DRAW):
    """Chained in front of the story's world draw (per view): the story draws first, then the countdown (native
    timer digits under "NEXT WAVE"), the wave banner and the end-of-run line, centred in the view.
    story_draw None: the per-view extension entry (VIEW) of the multi-view renderer, which never reaches the world
    hook. A call made inside the world hook's own chain (in_world, the viewport HUD wrapper) draws nothing, so a
    view is never drawn twice."""
    import native_hud_style as style
    from native_map import Y_ORIGIN
    from regional import screen_y
    a = Assembler(at); a.addiu(29, 29, -DRAW_FRAME)
    for i, r in enumerate(ALL):
        a.i(63, r, 29, i * 8)
    # Diagnostics (read by the rig): calls on entry, then the gate that ended this call and what it saw.
    a.li(8, CONTROL)
    if story_draw is None:
        a.lw(9, 8, C['view_calls']); a.addiu(9, 9, 1); a.sw(9, 8, C['view_calls'])
        a.lw(9, 8, C['in_world']); a.branch(5, 9, 0, 'quiet')
    else:
        a.lw(9, 8, C['draw_calls']); a.addiu(9, 9, 1); a.sw(9, 8, C['draw_calls'])
    a.sw(28, 8, C['draw_gp']); a.addiu(9, 0, 1); a.sw(9, 8, C['draw_gate'])
    if story_draw is not None:
        a.addiu(9, 0, 1); a.sw(9, 8, C['in_world'])
        a.call(story_draw)
        a.i(63, 2, 29, 0x1C0)
        a.li(8, CONTROL); a.sw(0, 8, C['in_world'])
    a.li(16, CONTROL); a.addiu(9, 0, 2); a.sw(9, 16, C['draw_gate'])
    a.lw(8, 16); a.li(9, MAGIC); a.branch(5, 8, 9, 'done')
    a.addiu(9, 0, 3); a.sw(9, 16, C['draw_gate'])
    a.lw(8, 16, C['waves']); a.branch(4, 8, 0, 'done')
    a.addiu(9, 0, 4); a.sw(9, 16, C['draw_gate'])
    a.lw(8, 16, C['manager']); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'done')
    a.addiu(9, 0, 5); a.sw(9, 16, C['draw_gate'])
    a.lw(17, 28, -22176); a.sw(17, 16, C['draw_view']); a.branch(4, 17, 0, 'done')   # s1 the view being drawn
    a.sw(0, 16, C['draw_gate'])
    a.lw(8, 17, 512); a.lw(9, 17, 516); a.r(0x21, 8, 8, 9); a.r(3, 8, 0, 8, 1)
    a.addiu(8, 8, 1792); a.r(0, 18, 0, 8, 4)                              # s2 centre x (GS)
    a.lw(19, 17, 520)                                                     # s3 view top (pixels)
    a.li(8, style.CONTROL); a.lw(8, 8); a.li(9, style.MAGIC); a.r(0x26, 23, 8, 9); a.i(11, 23, 23, 1)  # s7 native
    a.lw(20, 16, C['state'])
    a.lw(8, 16, C['draws']); a.addiu(8, 8, 1); a.sw(8, 16, C['draws'])
    # Countdown (seconds left, or GET READY in the overtime).
    a.addiu(9, 0, COUNTDOWN); a.branch(5, 20, 9, 'banner')
    a.addiu(8, 19, Y_ORIGIN + screen_y(COUNTDOWN_LABEL_Y)); a.r(0, 21, 0, 8, 4)   # s5 label top (GS)
    a.lw(8, 16, C['countdown_end']); a.lw(9, 16, C['tick']); a.r(0x23, 22, 8, 9)   # s6 updates left
    a.branch(6, 22, 0, 'overtime')
    a.lw(4, 16, C['text_next']); emit_centered(a, 4, 18, 21, COUNTDOWN_LABEL, WHITE, 23)
    a.branch(4, 23, 0, 'banner')                                          # digits need the native art
    a.addiu(8, 22, ACTOR_HZ - 1); a.addiu(9, 0, ACTOR_HZ); a.r(0x1B, 0, 8, 9); a.r(0x12, 22, 0)   # seconds
    a.addiu(8, 19, Y_ORIGIN + screen_y(COUNTDOWN_DIGITS_Y)); a.r(0, 21, 0, 8, 4)   # digit top
    half = int((DIGIT_UV[2] - DIGIT_UV[0]) * DIGIT_SCALE * 16) // 2
    a.addiu(8, 0, 10); a.r(0x2B, 8, 22, 8); a.branch(5, 8, 0, 'one_digit')
    a.addiu(8, 0, 10); a.r(0x1B, 0, 22, 8); a.r(0x12, 4, 0); a.r(0x10, 22, 0)
    a.addiu(5, 18, -(DIGIT_STEP * 16 // 2) - half); a.move(6, 21); emit_digit(a, 4, 5, 6)
    a.addiu(5, 18, DIGIT_STEP * 16 // 2 - half); a.move(6, 21); emit_digit(a, 22, 5, 6)
    a.jump('banner')
    a.label('one_digit'); a.addiu(5, 18, -half); a.move(6, 21); emit_digit(a, 22, 5, 6)
    a.jump('banner')
    a.label('overtime')
    a.lw(4, 16, C['text_ready']); emit_centered(a, 4, 18, 21, COUNTDOWN_LABEL, WHITE, 23)
    # Wave banner: WAVE n / N and its title while banner_until runs (intro, the start of wave 1).
    a.label('banner')
    # CPU-only runs: who is being watched (the native font, bottom centre; brighter just after a switch).
    a.lw(8, 16, C['spectate']); a.branch(4, 8, 0, 'banner_check')
    a.lw(9, 16, C['watched']); a.branch(4, 9, 0, 'banner_check')
    a.lw(8, 16, C['intro_camera']); a.branch(5, 8, 0, 'banner_check')
    a.addiu(9, 9, -1); a.r(0, 9, 0, 9, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(8, 8)
    a.branch(4, 8, 0, 'banner_check'); a.lw(8, 8, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, 'banner_check')
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(8, 8); a.branch(4, 8, 0, 'banner_check')
    a.lw(8, 8, 12); a.i(11, 9, 8, 256); a.branch(4, 9, 0, 'banner_check')
    a.r(0, 8, 0, 8, 2); a.li(9, NAMES); a.r(0x21, 8, 8, 9); a.lw(4, 8); a.branch(4, 4, 0, 'banner_check')
    a.lw(8, 17, 524); a.addiu(8, 8, Y_ORIGIN - screen_y(64)); a.r(0, 21, 0, 8, 4)
    a.lw(8, 16, C['watch_until']); a.lw(9, 16, C['tick']); a.r(0x2B, 8, 9, 8); a.branch(4, 8, 0, 'watch_dim')
    emit_centered(a, 4, 18, 21, 12, GOLD, 23); a.jump('banner_check')
    a.label('watch_dim')
    emit_centered(a, 4, 18, 21, 10, WHITE, 23)
    a.label('banner_check')
    a.lw(8, 16, C['banner_until']); a.lw(9, 16, C['tick']); a.r(0x2B, 8, 9, 8); a.branch(4, 8, 0, 'done')
    a.lw(8, 16, C['wave']); a.r(0, 8, 0, 8, WAVE_SHIFT); a.li(9, WAVES + WAVE_HEADER); a.r(0x21, 22, 8, 9)   # s6 wave row
    a.addiu(9, 0, WON); a.branch(4, 20, 9, 'won')
    a.addiu(9, 0, LOST); a.branch(4, 20, 9, 'lost')
    a.addiu(9, 0, COUNTDOWN); a.branch(4, 20, 9, 'done')
    a.addiu(8, 19, Y_ORIGIN + screen_y(112)); a.r(0, 21, 0, 8, 4)
    a.lw(4, 22, 8); emit_centered(a, 4, 18, 21, 22, GOLD, 23)
    a.addiu(8, 19, Y_ORIGIN + screen_y(160)); a.r(0, 21, 0, 8, 4)
    a.lw(4, 22, 12); emit_centered(a, 4, 18, 21, 13, WHITE, 23)
    a.jump('done')
    a.label('won')
    a.addiu(8, 19, Y_ORIGIN + screen_y(96)); a.r(0, 21, 0, 8, 4)
    a.lw(4, 16, C['text_won']); emit_centered(a, 4, 18, 21, 20, GOLD, 23)
    a.jump('done')
    a.label('lost')
    a.addiu(8, 19, Y_ORIGIN + screen_y(96)); a.r(0, 21, 0, 8, 4)
    a.lw(4, 22, 16); emit_centered(a, 4, 18, 21, 16, RED, 23)
    a.label('done')
    if story_draw is None:
        a.label('quiet')
    for i, r in enumerate(ALL):
        a.i(55, r, 29, i * 8)
    if story_draw is not None:
        a.i(55, 2, 29, 0x1C0)
    a.addiu(29, 29, DRAW_FRAME); a.jr()
    data = a.finish(); assert len(data) <= (VIEW if at == DRAW else CONTROL) - at, len(data); return data


def hud_extension(ram):
    """viewport_hud per-view extension entry while the gauntlet's per-view draw is installed, else None."""
    if len(ram) < CONTROL + 4 or u32(ram, CONTROL) != MAGIC:
        return None
    if bytes(ram[VIEW:VIEW + 16]) != draw_code(None, VIEW)[:16]:
        return None
    return (CONTROL, MAGIC, VIEW)


def hud_patch(ram):
    """Compose VIEW into the installed per-view renderer, as tag_rush_hud does: the multi-view renderer when it is
    installed (its views never reach the world hook), else the viewport HUD wrapper. [] when neither is installed
    or VIEW is already composed. Unknown bytes are never overwritten."""
    import viewport_hud as hud
    import quad_viewports as quad
    if u32(ram, hud.CONTROL) != hud.MAGIC:
        return []
    entry = (CONTROL, MAGIC, VIEW)
    before = tuple(e for e in hud.hud_extensions(ram) if e != entry)
    after = hud.hud_extensions(ram, installing={'gauntlet_runtime': entry})
    previous = u32(ram, hud.CONTROL + 16)
    if u32(ram, quad.CONTROL) == quad.MAGIC:
        # As tag_rush_install.hud_patches: lockon_select's quad marker stays the last entry, and lockon_threat's
        # quad marker links are re-applied to the composed renderer.
        import lockon_select as sel
        import lockon_threat as threat
        from native_map import A
        if u32(ram, sel.CONTROL) == sel.MAGIC and u32(ram, sel.CONTROL + sel.FIELDS['quad']):
            marker = ((sel.CONTROL, sel.MAGIC, sel.QMARKER),)
            before, after = before + marker, after + marker
        marked = u32(ram, threat.CONTROL) == threat.MAGIC and bool(u32(ram, threat.CONTROL + threat.FIELDS['quad_sites']))

        def with_markers(code):
            if not marked:
                return code
            sites = threat.quad_sites(code, quad.DRAW, A(0x102708))
            if len(sites) != 2:
                raise ValueError('Unknown quad marker positions for the Fighter Gauntlet')
            changed = bytearray(code)
            for site in sites:
                changed[site - quad.DRAW:site - quad.DRAW + 4] = threat.jal(threat.QUAD_LINK)
            return bytes(changed)
        address, limit = quad.DRAW, quad.SELECT
        for extensions in (before, after):
            old = with_markers(quad.draw(extensions))
            if bytes(ram[address:address + len(old)]) == old:
                break
        else:
            raise ValueError('Unknown per-view renderer for the Fighter Gauntlet')
        new = with_markers(quad.draw(after))
    else:
        address, limit = hud.CODE, hud.ACTIVE
        for extensions, kwargs in ((e, k) for e in (before, after) for k in (dict(deferred=True), dict(),
                                                                                 dict(revival=False, deferred=True),
                                                                                 dict(revival=False))):
            old = hud.wrapper(previous, extensions=extensions, **kwargs)
            if bytes(ram[address:address + len(old)]) == old:
                new = hud.wrapper(previous, extensions=after, **kwargs); break
        else:
            raise ValueError('Unknown viewport HUD wrapper for the Fighter Gauntlet')
    if old == new:
        return []
    if len(new) > limit - address:
        raise ValueError('The Fighter Gauntlet per-view draw exceeds the renderer reservation')
    if any(ram[address + len(old):address + len(new)]):
        raise ValueError('The Fighter Gauntlet per-view draw tail is occupied')
    return [(address, new)]



def aura_code():
    """a0 model ID: end that model's live aura / giant aura / afterimage instances (none -> nothing). Every family
    root and the instance's pool, callback and owner are checked before any destructor; v0 = instances ended."""
    import extra_charge_aura as ordinary
    import extra_extended_auras as extended
    from fusion_partner_lifecycle import pointer
    a = Assembler(AURA); a.addiu(29, 29, -0x100)
    for i, r in enumerate(ALL):
        a.i(63, r, 29, i * 8)
    a.move(16, 4); a.move(17, 0)
    a.i(11, 8, 16, 12); a.branch(4, 8, 0, 'done')
    for control in (ordinary.CONTROL, extended.CONTROL):
        a.li(8, control); a.lw(9, 8); a.addiu(10, 0, 5); a.branch(5, 9, 10, 'done')
        a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'done')
    families = [(ordinary.GLOBAL, ordinary.POOL_GLOBAL, ordinary.TABLE, 1168, 0x510, 100, A(0x2C3A48), False)] + [
        (f['global_'], f['poolglobal'], f['table'], f['tableoff'], f['body'], f['owner'], f['child'], f['name'] == 'giant')
        for f in extended.FAMILIES]
    for i, (glob, poolglob, table, tableoff, body_size, owner, callback, giant) in enumerate(families):
        a.li(8, glob); a.lw(21, 8); pointer(a, 21, tableoff + 4, f'next{i}'); a.lw(8, 21, tableoff)
        a.li(9, table); a.branch(5, 8, 9, f'next{i}'); a.r(0, 8, 0, 16, 2); a.r(0x21, 22, 8, 9); a.lw(24, 22)
        a.branch(4, 24, 0, f'next{i}'); pointer(a, 24, 64, f'next{i}')
        a.li(8, poolglob); a.lw(8, 8); a.lw(9, 24, 32); a.branch(5, 8, 9, f'next{i}')
        a.lw(8, 24, 36); a.branch(5, 8, 0, f'next{i}'); a.lw(8, 24, 40); a.li(9, callback); a.branch(5, 8, 9, f'next{i}')
        a.lw(25, 24, 56); pointer(a, 25, body_size, f'next{i}'); a.lw(8, 25, owner); a.branch(5, 8, 16, f'next{i}')
        if giant:
            for group in range(10):
                a.addiu(4, 25, 16 + group * 144); a.call(A(0x165820))
        a.move(4, 24); a.call(A(0x1ADA80)); a.addiu(17, 17, 1)
        a.label(f'next{i}')
    a.label('done'); a.i(63, 17, 29, ALL.index(2) * 8)
    for i, r in enumerate(ALL):
        a.i(55, r, 29, i * 8)
    a.addiu(29, 29, 0x100); a.jr()
    data = a.finish(); assert len(data) <= 0x1000, len(data); return data


def hud_gate_code(head):
    """HUDGATE: in front of viewport_hud.ACTIVE (its first two words, `head`, jump here). While a wave intro's camera
    runs, SELECT presents ONE full-screen view in every layout, but ACTIVE did not know it: the per-view split panels
    (two per view, at each view's corner; in three/four views a pair in mid-screen) were drawn over the full-screen
    intro. Answer 0 then (split panels do not own the HUD; the native single-view HUD draws, as for every shared
    presentation), on exactly SELECT's condition; otherwise run ACTIVE. Every register but v0 is preserved."""
    a = Assembler(HUDGATE)
    a.addiu(29, 29, -32); a.i(63, 8, 29, 0); a.i(63, 9, 29, 8); a.i(63, 10, 29, 16)
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'active')
    a.lw(9, 8, C['manager']); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'active')
    a.lw(9, 8, C['intro_camera']); a.branch(4, 9, 0, 'active')
    a.lw(9, 28, -22180); a.branch(4, 9, 0, 'active')
    a.i(55, 8, 29, 0); a.i(55, 9, 29, 8); a.i(55, 10, 29, 16); a.addiu(29, 29, 32)
    a.move(2, 0); a.jr()
    a.label('active')
    a.i(55, 8, 29, 0); a.i(55, 9, 29, 8); a.i(55, 10, 29, 16); a.addiu(29, 29, 32)
    for word in struct.unpack('<2I', head):
        a.emit(word)
    import viewport_hud as hud
    a.jump(hud.ACTIVE + 8)
    data = a.finish(); assert len(data) <= 0x200, len(data); return data


def hud_gate_blocks(ram):
    """[(HUDGATE, code), (viewport_hud.ACTIVE, j HUDGATE)] when the split viewport HUD is installed, else []. ACTIVE's
    first two words must be its own prologue (every emission shares it) or already this jump; never anything else."""
    import viewport_hud as hud
    if u32(ram, hud.CONTROL) != hud.MAGIC:
        return []
    head = hud.active()[:8]
    if bytes(ram[hud.ACTIVE:hud.ACTIVE + 8]) not in (head, jump(HUDGATE)):
        raise ValueError('Fighter Gauntlet: unknown viewport HUD owner check')
    if any(ram[HUDGATE:HUDGATE + len(hud_gate_code(head))]) and bytes(ram[HUDGATE:HUDGATE + len(hud_gate_code(head))]) != hud_gate_code(head):
        raise ValueError('Fighter Gauntlet: HUD gate reservation occupied')
    return [(HUDGATE, hud_gate_code(head)), (hud.ACTIVE, jump(HUDGATE))]


def code_blocks(story_draw=None):
    import story_runtime as story
    return [(TICK, tick_code()), (UPDATE, update_code()), (WAVE, wave_code()), (FIND, find_code()),
            (COUNT, count_code()), (LOADABLE, loadable_code()), (ADMIT, admit_code()), (SELECT, select_code()), (PRESENT, present_code()),
            (WATCH, watch_code()), (COPIER, copier_code()), (RUNNER, runner_code()),
            (DRAW, draw_code(story_draw or story.DRAW)), (VIEW, draw_code(None, VIEW)), (AURA, aura_code()),
            (BREAK, break_code()), (PLACE, place_code())]


TIME_LIMIT = A(0x331DC8) + 16     # battle setup: time limit index, 0 = infinite
SELECTOR_ENTRY = A(0x23EFF0)       # native camera selector entry; cinematic_policy installs j CODE there


def name_table(run):
    """(None, ORDER bytes): the spectator cycle order: the player team. Watching an enemy loaded mid-match froze the
    game (EE waiting for VIF1 at 100AF0, g17/g18), so enemies are never the spectator's subject."""
    count = len(run['players'])
    return None, bytes(2 * i for i in range(count))
DEFAULT_TIMING = dict(countdown=15, vanish=5, overtime=3, step=9.0, tail=0.8, banner=4, release=2.5, give_up=60,
                      getup=1.6, group_step=9.0, intro_wait=12, intro_nopose=6.5, intro_min=1.0)


def text(value):
    import unicodedata
    value = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().upper()
    return value[:40]


def wave_title(wave, settings=None):
    """The wave intro banner's title: Spanish uses the data's label_es when it has one."""
    import localization
    if localization.language(settings) == 'es' and wave.get('label_es'):
        return wave['label_es']
    return wave['label']


def tables(run):
    """(WAVES bytes, STRINGS bytes, CONTROL text pointers) of a run plan (gauntlet_mode.run_plan)."""
    import localization
    waves, strings = bytearray(WAVE_HEADER + WAVE_STRIDE * len(run['waves'])), bytearray()

    def string(value):
        at = STRINGS + len(strings); strings.extend(text(value).encode('ascii') + b'\0')
        while len(strings) % 4:
            strings.append(0)
        return at
    struct.pack_into('<I', waves, 0, len(run['waves']))
    count = len(run['waves'])
    for w, wave in enumerate(run['waves']):
        row = WAVE_HEADER + WAVE_STRIDE * w
        fighters = wave['enemies']
        if not 1 <= len(fighters) <= 5:
            raise ValueError('A wave needs 1..5 fighters')
        struct.pack_into('<5I', waves, row, len(fighters), wave['difficulty'],
                         string(localization.tr('WAVE {n} / {count}', None, n=w + 1, count=count)),
                         string(wave_title(wave)),
                         string(localization.tr('REACHED WAVE {n} / {count}', None, n=w + 1, count=count)))
        for k, f in enumerate(fighters):
            struct.pack_into('<5I', waves, row + 32 + FIGHTER_STRIDE * k, f['character'], f['costume'], f['hp'],
                             round(f['damage'] * 1000), round(f['defense'] * 1000))
    names = bytearray(256 * 4)
    for character, name in sorted(run.get('names', {}).items()):
        if 0 <= int(character) < 256:
            struct.pack_into('<I', names, int(character) * 4, string(name))
    run['_names_blob'] = bytes(names)
    pointers = dict(text_next=string(localization.tr('NEXT WAVE', None)),
                    text_ready=string(localization.tr('GET READY', None)),
                    text_won=string(localization.tr('GAUNTLET CLEARED', None)))
    if len(strings) > PACKET - STRINGS:
        raise ValueError('Gauntlet texts exceed their reservation')
    if len(waves) > STRINGS - WAVES:
        raise ValueError('Gauntlet waves exceed their reservation')
    return bytes(waves), bytes(strings), pointers


def build_memory(ram, run=None, gate_mask=None, source='<prepared>'):
    """The gauntlet guest program for this captured match. `run` (gauntlet_mode.run_plan) carries the waves, the
    side masks, the initial slot table and the refill; without it only the loader (copier, runner, gates) runs."""
    import story_runtime as story
    if len(ram) != 0x8000000:
        raise ValueError('Requires 128 MiB EE RAM')
    if any(ram[BASE:END]):
        raise ValueError('Fighter Gauntlet reservation occupied')
    manager, count = u32(ram, core.ACTORS), u32(ram, core.MODE + 4)
    if u32(ram, core.MODE) != 1 or u32(ram, core.MODE + 8) != manager or u32(ram, core.MODE + 12) != count:
        raise ValueError('Fighter Gauntlet requires a captured active match')
    call = u32(ram, feed.TICK_CALL)
    if call >> 26 != 3:
        raise ValueError('Per-update call changed')
    previous = (call & 0x3FFFFFF) << 2
    if previous == TICK:
        raise ValueError('Fighter Gauntlet already chained')
    if run is not None:
        gate_mask = run['gate_mask']
    if type(gate_mask) is not int or gate_mask >> count or gate_mask & 3:
        raise ValueError('Gate mask names only extras of this match')
    control = bytearray(0x200)
    struct.pack_into('<5I', control, 0, MAGIC, manager, count, 2, previous)
    # The vanish ends aura instances; AURA itself requires both aura families ready for this match (they are
    # installed after this manifest is built). Only a run installs AURA.
    if run is not None:
        struct.pack_into('<I', control, C['cleanup'], AURA)
    struct.pack_into('<I', control, C['gate_mask'], gate_mask)
    blocks = []
    slots = bytearray(12 * SLOT_STRIDE)
    draw_blocks = []
    if run is not None:
        if u32(ram, story.CONTROL) != story.MAGIC:
            raise ValueError('Fighter Gauntlet runs on the story runtime; install it first')
        timing = dict(DEFAULT_TIMING, **run.get('timing', {}))
        if 'names' not in run:
            import gauntlet_mode
            chars = {c for c, _, _ in run['players']} | {e['character'] for w in run['waves'] for e in w['enemies']}
            chars |= {r['enemy']['character'] for r in run['roster'].values()}
            run['names'] = {c: gauntlet_mode.fighter_name(c) for c in sorted(chars)}
        waves, strings, pointers = tables(run)
        values = dict(waves=len(run['waves']), refill=run['refill'] & 0xFFFFFFFF, player_mask=run['player_mask'],
                      enemy_mask=run['enemy_mask'], wave_mask=run['wave_mask'], participants=run['participants'],
                      player_team=1, pending=0, **pointers,
                      **{k: max(1, round(timing[k] * ACTOR_HZ)) for k in DEFAULT_TIMING})
        for key, value in values.items():
            struct.pack_into('<I', control, C[key], value)
        for p, row in run['slots'].items():
            for key, value in row.items():
                struct.pack_into('<I', slots, p * SLOT_STRIDE + S[key], value & 0xFFFFFFFF)
        blocks += [(WAVES, waves), (STRINGS, strings), (NAMES, run.pop('_names_blob'))]
        # The world draw: the story chained it first (abi.WORLD = j story.DRAW); ours goes in front.
        world = bytes(ram[feed.WORLD:feed.WORLD + 8])
        if world != jump(story.DRAW):
            raise ValueError('Fighter Gauntlet needs the story world draw hook')
        # No time limit: a native time-out would decide the match between waves (native 12AB90 reads +16 == 0).
        draw_blocks = [(feed.WORLD, jump(DRAW)), (TIME_LIMIT, bytes(4))]
    if run is not None:
        # The wave intro's full-screen camera goes in front of the mod's camera selector (native 23EFF0 -> j SELECT).
        import cinematic_policy as policy
        if bytes(ram[SELECTOR_ENTRY:SELECTOR_ENTRY + 8]) != jump(policy.CODE):
            raise ValueError('Fighter Gauntlet needs the installed camera selector')
        draw_blocks.append((SELECTOR_ENTRY, jump(SELECT)))
        # Free movement between waves: the opponent mirror's flag-177 HP test calls BREAK (one jal; see break_code).
        mirror = struct.pack('<I', (3 << 26) | (OPPONENT_DEAD >> 2))
        if bytes(ram[MIRROR_CALL:MIRROR_CALL + 4]) != mirror:
            raise ValueError('Fighter Gauntlet: unknown native opponent mirror')
        draw_blocks.append((MIRROR_CALL, struct.pack('<I', (3 << 26) | (BREAK >> 2))))
        # Multi-view (two to four humans): the per-view renderer calls VIEW for each view (composed as an
        # installing viewport_hud extension; once installed, hud_extension recognises VIEW's own bytes).
        draw_blocks += hud_patch(ram)
        # A wave intro is one full-screen view: the split HUD's per-view panels stay off for it.
        draw_blocks += hud_gate_blocks(ram)
        _, order = name_table(run)
        draw_blocks.append((ORDER, order))
        struct.pack_into('<I', control, C['order_count'], len(order))
        struct.pack_into('<I', control, C['spectate'], int(run.get('humans', 1) == 0))
    pieces = code_blocks() if run is not None else [b for b in code_blocks()
                                                    if b[0] not in (DRAW, VIEW, AURA, SELECT, PRESENT, WATCH, BREAK)]
    blocks = pieces + blocks + [(CONTROL, bytes(control)), (GATES, bytes(48)), (SLOTS, bytes(slots)),
                                (feed.TICK_CALL, struct.pack('<I', (3 << 26) | (TICK >> 2)))] + draw_blocks
    spans = sorted((p, p + len(d)) for p, d in blocks)
    if any(end > begin for (_, end), (begin, _) in zip(spans, spans[1:])):
        raise ValueError('Fighter Gauntlet sections overlap')
    return dict(serial=SERIAL, crc=CRC, source=str(source),
                blocks=[dict(address=p, expected_hex=ram[p:p + len(d)].hex(), data_hex=d.hex()) for p, d in blocks])
