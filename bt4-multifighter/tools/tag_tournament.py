"""Tag Team Tournament: the game's own World Tournament ("Dragon World Tour") with a team behind every entrant.

The native tournament module (menu overlay DBZP.BIN, scenes 33 type menu / 34 registration / 35 bracket and match
launch) keeps doing everything it shows: bracket, CPU-match simulation, VS / result screens, rounds, the champion
ending. The mod adds:

* A setup panel (players, their teams, team size, tournament type and difficulty) and a roster draft: every team
  picks all its fighters (character, costume and Potara loadout) once on the familiar Team Battle select, each slot
  labelled by the player who picks/controls it; CPU slots are picked by the team's first player (CPU only: player 1
  picks the team to follow). Nothing is asked twice: the native type menu and registration (scenes 33 / 34) are
  answered from the setup by two stand-ins (AUTO, one shot), so Dragon World Tour opens straight on the bracket.
* No locked fighters: the select screen's lock-icon slots (one portrait several roster ids share) never enter the
  bracket (a post-pass after the native entrant setup swaps them) and are never random teammates.
* Team rows. The match launch (overlay 0x36A720) writes one fighter row per side through the engine's row filler
  A(0x12A2D8)(side, member, character, costume, 0, ai_level, items, f12=hp). While a Tag Team Tournament is armed
  a hook on that filler runs the original, then - for member 0 of a mode-4 (tournament) setup in scene 35 whose
  side maps to an entrant with a team in TABLE - calls the original again for members 1..N-1 (with their costumes
  and Potara items) and keeps the side's member count. The hook, its cave and the table are written by PCSX2 only
  while CONTROL holds ARMED (pnach D-codes), and the original words are written back once it does not.
* Guidance drawn over the native screens (the CPU-match question, the teammates on the VS / result screens; the
  entry turns and How-many-people check only when the stand-ins could not run) through the menu fade hook, from a
  picture the host publishes.
* Results. Each match is prepared and played like any team battle (the preparation gate accepts the tournament
  mode while armed: native_preparation.ACCEPTED_MODE). The host then restores the savestate of the fresh native
  battle and asks the engine to end it with the team result (the native surrender request: result flags 8, reason
  0x20 / 0x40), so the tournament reads the winner on a clean state and continues natively.
* Controllers: every tournament player's own controller drives their fighter in every match, and their turn at the
  native entry (controller_hub.Hub.set_order).
"""
from native_map import A, NativeMapError
import json
import random
import struct
from pathlib import Path
from prototype import Assembler

# ---------------------------------------------------------------- reservation (zero in every prepared state checked)
BASE, END = 0x06180000, 0x061A0000
CODE, TRAMP, PAD_CODE, DRAW_CODE, WATCH_CODE = BASE, BASE+0x800, BASE+0x880, BASE+0xA00, BASE+0x2000
CONTROL, TABLE, DRAWBUF = BASE+0x1000, BASE+0x1100, BASE+0x3000
DRAW_CAPACITY = 0xD000                # DRAWBUF .. BASE+0x10000 (native text tables follow)
ARMED = 0x5454                       # CONTROL low halfword the pnach D-codes compare (little endian)
MAGIC = 0x31545454                   # 'TTT1': the whole CONTROL word while armed
READY_MAGIC = 0x59445254             # 'TRDY': written by the armed pnach after the code, cleared once disarmed
DRAFT_MAGIC = 0x46524454             # 'TDRF': the roster draft's slot owners (team_assignment.resolve_code)
ENTRANTS, BOSS = 17, 16
TEAM_MAX = 5
MEMBER = 24                          # TABLE member: character, costume, 16 bytes of Potara items (u16 id+1)
ENTRY = 8 + TEAM_MAX*MEMBER          # TABLE record per entrant: count, flags, 5 members
COPY_LEADER_ITEMS = 1                # TABLE flag: members without items take the leader's (CPU teams)
# CONTROL words (offsets)
F = dict(magic=0, version=4, applied=8, side=12, entrant=16, count=20, epoch=24, refused=28,
         draft=0x40, ready=0x60, block=0x64, draw_len=0x70, draw_scene=0x74, draw_lease=0x78, draw_frames=0x7C,
         watch=0x90, ask=0x94, answer=0x98, wbuttons=0x9C, wprev=0xA0, wclean=0xA4, we0=0xA8, wstop=0xAC,
         wprot=0xB0, wlease=0xB4, wframes=0xB8, swapped=0xBC, level=0xC0, native_level=0xC4)
# CPU-match watching (watch_code): watch 1 = armed; ask = row+1 the bracket waits on (CPU vs CPU, guest->host);
# answer 1 Watch / 2 Skip (host->guest); wbuttons = raw pad presses latched while asking; wclean = watched or human
# row+1 whose return clears we0 (side-0 entrant+1 marked human for the native result) and the wprot rows (played
# bits that kept the native from resolving them at the return); wstop = row+1 whose entrant A carries a stop mark
# (cleared once the bracket waits on it); wlease = frames the host's question stays valid (0: Skip).
DRAFT = CONTROL + F['draft']         # magic, owner byte per physical slot 0..11 (+4), team size (+16)
READY = CONTROL + F['ready']
VERSION = 2
# swapped (guest->host): CPU entrants the post-pass gave a playable fighter instead of a locked one.
# The auto entry (host->guest, one shot; ENTRY_STUB clears its magic): the answers the native type menu and
# registration would collect. +4 type, +8 difficulty, +12 human entrants (1..4), then one AUTO_STRIDE record per
# registered leader at +AUTO_ENTRY: character, costume, flags halfword (HUMAN, CUSTOM when it has items), 16 item bytes.
AUTO, AUTO_MAGIC, AUTO_ENTRY, AUTO_STRIDE, AUTO_MAX = BASE+0x1980, 0x54554154, 0x20, 0x20, 4
CUSTOM = 0x20                        # entrant flag: the registration took a Custom (Potara) loadout
# Locked select-screen ids (bitmap, id < 256) and the playable spares the post-pass draws from (u32 count, u16 ids).
LOCKED, SPARES, SPARE_MAX = BASE+0x1A20, BASE+0x1A40, 250
TYPE_STUB, ENTRY_STUB, SETUP_STUB = BASE+0x400, BASE+0x500, BASE+0xC00   # (after the cave) .. TRAMP; .. CONTROL
# The transitions are covered (the watcher's owned cover, autopilot.tournament_veil_show). VEIL: a plain black GIF
# packet the host publishes with the draft (DRAFT+DRAFT_VEIL = its length): the picture guest draws it over the
# Team Select from the frame its stage selection opens, until the watcher's cover is up and the main menu is loaded
# under it.
VEIL, VEIL_CAPACITY, VEIL_CHECK = BASE+0x1C40, 0xC0, BASE+0x1E00
DRAFT_VEIL = 20

# ---------------------------------------------------------------- native addresses (USA; A() maps other discs)
HOOK = A(0x12A2D8)                   # engine battle-setup row filler (side, member, character, costume, ...)
RESUME = A(0x12A2E0)                 # after its two relocated prologue instructions
ORIGINAL = (0x27BDFFB0, 0xFFB00000)  # addiu sp,sp,-0x50 ; sd s0,0(sp)
# The setup commit (0x12A458 -> 0x129B20) switches on the battle mode through a jump table; the mode-4 entry forces
# every side back to ONE member. While armed that entry points at the mode-2 case (no change), so the commit keeps
# the team counts (and copies them into its 0x301268 mirror) exactly as it does for Team Select's mode-0 setups.
COUNT_CASE = A(0x2EC3D8)             # jump table 0x2EC3D0, index mode-2
COUNT_FORCE, COUNT_KEEP = A(0x129CB8), A(0x129D10)
HOOK_HIGH = ((2 << 26) | (CODE >> 2)) >> 16   # high halfword of the hook word 'j CODE' (at HOOK+2)
SCENE_MANAGER = A(0x2FF10C)          # scene id at +0x18
SETUP = A(0x331DC8)                  # battle setup: +0x08 mode, +0xC0 + side*0x270 member count, rows +0xC4 (0x64)
RUNTIME = A(0x3B5918)                # overlay: the tournament runtime object while scene 35 runs
# CPU strength. The match launch passes the row filler an AI level from Dragon World Tour's own table (difficulty x
# round, overlay 0x36AE04: level 0 = the weakest native AI at 1 Dragon Ball's first round). Team Battle (overlay
# 0x348B74) passes the options' COM level (OPTIONS +0xC38, Very Easy..Very Hard) through COM_LEVEL_OF (BT3 0, 6, 13,
# 21, 29; the BT4 executable 6, 13, 21, 29, 99). A level-0 CPU mostly stands and watches - while anyone performs a
# special move its fighters wait it out
# (live Oct 20: idle 26% of CPU ticks, 35% during specials, against 6% in a Team Battle at Very Hard), which reads as
# "the AI stops". Every member of an armed tournament launch gets the higher of the two levels, so a tournament team
# fights at least as hard as the same fighters in a modded Team Battle, and the Dragon Balls still raise it.
OPTIONS = A(0x2FF28C)                # options object pointer (fusion_audio_restore.OPTIONS_GLOBAL)
COM_LEVEL, COM_LEVELS = 0xC38, 5    # options +0xC38: the COM level 0..4 Team Battle uses
COM_LEVEL_OF = A(0x261738)           # native leaf: v0 = AI level of COM level a0 (v0/v1 only, no stack)
RESULT_FLAGS, RESULT_REASON = A(0x333700), A(0x333704)
PAD_RECORDS = A(0x333800)            # PCSX2's two port records (mode_menu.PAD); translated words +0x18C/+0x190
TEAM_SELECT = A(0x3B38D8)            # the Team Select object (scene 40)
# The native CRI ADX streams (extra_special_pools.native_stream_buffers): six handles in 20-byte rows (ch0 the match
# music, ch1 a second stream such as the crowd, ch2-5 voices); handle+1 is the ADXT status (0 stopped, 3 playing,
# 5 play end): the restored match start of a result hand-back plays its music, crowd and a voice (the noise the
# hand-back's cover mutes; stream_playing logs it). Not stopped in game: the game's own stop (0x265970 -> ADXT_Stop)
# called from the pad hook left the restored final crawling (live Oct 20). Scene 35's opening logo starts its jingle
# and sets OBJ_WAIT bit LOGO_WAIT (0x365040; 0x3655C4 polls it), then runs as script step 0x34.
try:
    ADX_TABLE = A(0x2C7070)
except NativeMapError:               # a disc without a reviewed stream table: no stream log
    ADX_TABLE = None
ADX_CHANNELS, ADX_ROW, LOGO_WAIT = 6, 20, 0x80000
TOURNAMENT_SCENES = (33, 34, 35)
# Bracket (scene 35) natives the watch helper calls, as the overlay's own accept / instant result / advance do.
BRACKET_PAD_RETURN = A(0x365CB8)     # the scene-35 loop's pad read returns here (the pad hook's caller)
VS_START, ACCEPT_SOUND = A(0x369EE8), A(0x124F68)        # 0x365B30's accept: VS + flip +0x2DC bit 4 + sound(1, 1)
ROW_RESULT, ROW_ADVANCE = A(0x368C18), A(0x369AE0)       # instant CPU-row result (rand); next row / next round
OBJ_WAIT, OBJ_SCRIPT, OBJ_MESSAGE, OBJ_FACES = 0x2DC, 0x1A3C, 0x1A4C, 0x1A40
WAIT_BUSY = 0x2 | 0x20 | 0x40 | 0x80 | 0x400   # +0x2DC bits that mean "not the plain bracket wait"
CPU_ROWS = 14                        # rows 0..13 can be CPU vs CPU (14 / 15 always hold the remaining human)
TYPE_SCENE, ENTRY_SCENE, BRACKET_SCENE, SELECT_SCENE, MAIN_MENU = 33, 34, 35, 40, 4
TOURNAMENT_MODE = 4
SIDE_STRIDE, ROW_BYTES = 0x270, 0x64
# Runtime object (scene 35) and the scene manager's persistent copy (+0x80..+0x440, survives the battle).
OBJ_ROUND, OBJ_ROW, OBJ_ENTRANTS, OBJ_ROWS = 0x1A44, 0x1A48, 0x1A68, 0x1D10
MGR_TYPE, MGR_DIFFICULTY, MGR_HUMANS, MGR_ROUND, MGR_MATCH = 0x84, 0x88, 0x8C, 0x90, 0x94
MGR_ENTRANTS, MGR_ROWS = 0x98, 0x340
ENTRANT_BYTES, ROW_RECORD = 40, 16
HUMAN, ELIMINATED, BOSS_FLAG = 1, 2, 4
SURRENDER_SIDE0, SURRENDER_SIDE1 = 0x20, 0x40   # reason bits: that side surrendered (0x1291C0 picks the other)
LATCHED = 8
TYPES = ('World Tournament', 'World Martial Arts Big Tournament', 'Cell Games', 'Otherworld Tournament',
         'Yamcha Game')
BT4_TYPES = TYPES[:4] + ('Tournament of Power',)   # the BT4 B14 Free list (its fifth row, the same type 4)


def type_names():
    """The Free list's tournament names (manager +0x84 order) on the chosen disc."""
    from native_map import SERIAL
    return BT4_TYPES if SERIAL == 'SLUS-21978' else TYPES


ROUND_NAMES = ('1st Round', '2nd Round', '3rd Round', 'Semifinal', 'Final')
# Team Select (scene 40): side rosters *(obj+0x8E8+4*side): 5 x 48-byte records (+0x18 costume, +0x1C character,
# +0x20 16 bytes of items), +0x134 accepted count, +0x12C hovered slot, +0x13C state (8 = Done); obj+0x3BC bit 4 =
# stage select open (both sides Done).
SEL_SIDES, SEL_RECORD, SEL_COUNT, SEL_HOVER, SEL_STATE, SEL_FLAGS, SEL_DONE = 0x8E8, 48, 0x134, 0x12C, 0x13C, 0x3BC, 8
# Tournament entry (scene 34): S = *(ENTRY_OBJECT); whose turn = *(*(S+0x3C4)+0x1C0) (0-based; +1 on each decision,
# -1 on cancel; registration ends when it reaches the scene manager's How many people).
ENTRY_OBJECT, ENTRY_TURN_OBJECT, ENTRY_TURN = A(0x3B5910), 0x3C4, 0x1C0
# The scene 33..35 dispatcher (USA 0x362160) calls the type menu (0x364B18: World Tour / Free, the Free list,
# difficulty, How many people -> manager +0x80 Free, +0x84 type, +0x88 difficulty, +0x8C people) and the registration
# (0x361D80: entrant records +0x98, one per person: flags HUMAN (| CUSTOM), character, costume, order, items +0x18);
# each returns 1 to go on. While an auto entry is published those two calls go to the stand-ins.
TYPE_CALL, ENTRY_CALL = A(0x362220), A(0x36229C)
TYPE_MENU, REGISTRATION = A(0x364B18), A(0x361D80)
MGR_FREE = 0x80
# Scene 35's fresh start (0x364FE8..) calls the entrant setup 0x369318 (humans from the manager copy, the other 15
# drawn from the select-screen grid); while armed that call goes to SETUP_STUB, which swaps locked CPU entrants.
SETUP_CALL, ENTRANT_SETUP, RAND = A(0x365020), A(0x369318), A(0x254DE8)
# The entrant pick's own exclusion: BT3 'slti v0, a0, CAP' (ids below CAP); the BT4 executable calls its filter
# there (BT4_FILTER: 0xA1..0xA4 refused).
PICK_RULE = A(0x369470)
BT4_PICK_CALL, BT4_FILTER = 0x0C0EFC1D, 0x3BF1C8   # 'jal 0x3BF074' at PICK_RULE, its filter (BT4 executable only)
HELD_SCROLL = 3                      # translated held word +0x188 bits the bracket wait scrolls on (0x365B30)


# ---------------------------------------------------------------- guest code
SAVE = 0x70     # 16-byte aligned frame: ra a0 a1 a2 a3 t0 t1 t2 f12 s0 s1 s2 v0 s3


SAVED = ((0, 31), (8, 4), (16, 5), (24, 6), (32, 7), (40, 8), (48, 9), (56, 10), (72, 16), (80, 17), (88, 18),
         (104, 19))


def tramp_code():
    """The relocated prologue of the native row filler, then its body: callable like the original."""
    a = Assembler(TRAMP)
    a.addiu(29, 29, -0x50)
    a.i(63, 16, 29, 0)                   # sd s0,0(sp)
    a.jump(RESUME)
    return a.finish()


def cave_code():
    """Hook body on A(0x12A2D8). Runs the original with the caller's arguments, then (armed tournament launch,
    member 0, mapped entrant whose leader matches) adds members 1..N-1 through the original and sets the count."""
    a = Assembler(CODE)
    a.addiu(29, 29, -SAVE)
    for off, reg in SAVED:
        a.i(63, reg, 29, off)            # sd
    a.i(57, 12, 29, 64)                  # swc1 f12,64(sp)
    # ---- guards (before the original: the level it writes may change): armed, scene 35, tournament setup,
    # member 0, side 0/1. s2 = 1 once they pass.
    a.move(18, 0)
    a.li(16, CONTROL); a.lw(8, 16, F['magic']); a.li(9, MAGIC); a.branch(5, 8, 9, 'call')
    a.lw(8, 16, F['version']); a.addiu(9, 0, VERSION); a.branch(5, 8, 9, 'call')
    a.branch(5, 5, 0, 'call')                                        # member argument (a1) must be 0
    a.move(17, 4); a.i(11, 9, 17, 2); a.branch(4, 9, 0, 'call')      # side (a0) < 2
    a.li(8, SCENE_MANAGER); a.lw(8, 8)
    a.li(9, 0x100000); a.r(0x2B, 9, 8, 9); a.branch(5, 9, 0, 'call')
    a.li(9, 0x1FFF000); a.r(0x2B, 9, 8, 9); a.branch(4, 9, 0, 'call')
    a.lw(8, 8, 0x18); a.addiu(9, 0, BRACKET_SCENE); a.branch(5, 8, 9, 'call')
    a.li(8, SETUP); a.lw(8, 8, 8); a.addiu(9, 0, TOURNAMENT_MODE); a.branch(5, 8, 9, 'call')
    a.addiu(18, 0, 1)
    # ---- the AI level (t1): at least the options' COM level as Team Battle maps it (COM_LEVELS); receipts
    a.lw(9, 29, 48); a.sw(9, 16, F['native_level']); a.sw(9, 16, F['level'])
    a.li(8, OPTIONS); a.lw(8, 8)
    a.li(10, 0x100000); a.r(0x2B, 10, 8, 10); a.branch(5, 10, 0, 'call')
    a.li(10, 0x1FFF000); a.r(0x2B, 10, 8, 10); a.branch(4, 10, 0, 'call')
    a.lw(4, 8, COM_LEVEL); a.i(11, 10, 4, COM_LEVELS); a.branch(4, 10, 0, 'call')
    a.call(COM_LEVEL_OF); a.move(10, 2)                              # (a0..t2 are reloaded below)
    a.lw(9, 29, 48); a.r(0x2A, 11, 9, 10); a.branch(4, 11, 0, 'call')  # native level already as high: kept
    a.i(63, 10, 29, 48); a.sw(10, 16, F['level'])                    # sd t1 slot: this call and members 1..N-1
    a.label('call')
    for off, reg in SAVED[1:8]:
        a.i(55, reg, 29, off)            # ld a0..a3, t0..t2 (t1 possibly raised)
    a.i(49, 12, 29, 64)                  # lwc1 f12
    a.call(TRAMP)
    a.i(63, 2, 29, 96)                   # sd v0 (the original's result, returned unchanged)
    a.branch(4, 18, 0, 'done')
    # ---- the launched row and the entrant on this side (0x36A720: side 0 = A when A is human, else B)
    a.li(8, RUNTIME); a.lw(18, 8)
    a.li(9, 0x100000); a.r(0x2B, 9, 18, 9); a.branch(5, 9, 0, 'refuse')
    a.li(9, 0x1FFC000); a.r(0x2B, 9, 18, 9); a.branch(4, 9, 0, 'refuse')
    a.lw(8, 18, OBJ_ROW); a.i(11, 9, 8, 16); a.branch(4, 9, 0, 'refuse')
    a.r(0, 8, 0, 8, 4); a.r(0x21, 8, 8, 18)                          # row record = obj + row*16
    a.i(37, 10, 8, OBJ_ROWS+2); a.i(37, 11, 8, OBJ_ROWS+4)           # lhu entrant A, B
    for reg in (10, 11):
        a.i(11, 9, reg, ENTRANTS); a.branch(4, 9, 0, 'refuse')
    # flags of A: obj + 0x1A68 + A*40
    a.r(0, 12, 0, 10, 5); a.r(0, 13, 0, 10, 3); a.r(0x21, 12, 12, 13); a.r(0x21, 12, 12, 18)
    a.i(37, 12, 12, OBJ_ENTRANTS); a.i(12, 12, 12, HUMAN)
    a.branch(4, 12, 0, 'a_cpu')
    a.move(13, 10); a.move(14, 11); a.jump('mapped')                 # A human: side0 = A, side1 = B
    a.label('a_cpu'); a.move(13, 11); a.move(14, 10)                 # else side0 = B, side1 = A
    a.label('mapped')
    a.branch(4, 17, 0, 'side0'); a.move(13, 14)
    a.label('side0')                                                 # t5 = entrant on this side
    # the entrant's registered character must be the one the native just wrote
    a.r(0, 12, 0, 13, 5); a.r(0, 15, 0, 13, 3); a.r(0x21, 12, 12, 15); a.r(0x21, 12, 12, 18)
    a.lw(12, 12, OBJ_ENTRANTS+4); a.i(55, 15, 29, 24); a.branch(5, 12, 15, 'refuse')
    # its team record: s3 = TABLE + entrant*128 (ENTRY)
    assert ENTRY == 128
    a.r(0, 19, 0, 13, 7)
    a.li(8, TABLE); a.r(0x21, 19, 19, 8)
    a.lw(8, 19, 0); a.addiu(9, 8, -2); a.i(11, 9, 9, TEAM_MAX-1); a.branch(4, 9, 0, 'done')   # count 2..5
    a.lw(9, 19, 8); a.i(55, 15, 29, 24); a.branch(5, 9, 15, 'refuse')  # leader record matches too
    a.li(8, CONTROL); a.sw(13, 8, F['entrant'])
    # ---- members 1..count-1 through the original (same AI level and HP; their own costume and items)
    a.addiu(16, 0, 1)
    a.label('member')
    a.addiu(9, 0, MEMBER); a.r(0x18, 0, 16, 9); a.r(0x12, 9, 0); a.addiu(9, 9, 8); a.r(0x21, 9, 9, 19)  # s3+8+24*m
    a.move(4, 17); a.move(5, 16); a.lw(6, 9, 0); a.lw(7, 9, 4)
    a.addiu(10, 9, 8)                                                # t2 = this member's 16 item bytes
    # CPU teams: a member with no items of its own takes the leader's (the native wrote them for member 0)
    a.lw(11, 19, 4); a.i(12, 11, 11, COPY_LEADER_ITEMS); a.branch(4, 11, 0, 'items_ready')
    for off in (0, 4, 8, 12):
        a.lw(11, 10, off); a.branch(5, 11, 0, 'items_ready')
    a.li(10, SETUP+0xC4+0x14); a.branch(4, 17, 0, 'items_ready'); a.addiu(10, 10, SIDE_STRIDE)
    a.label('items_ready')
    a.i(55, 8, 29, 40); a.i(55, 9, 29, 48); a.i(49, 12, 29, 64)    # t0, t1, lwc1 f12
    a.call(TRAMP)
    a.addiu(16, 16, 1); a.lw(8, 19, 0); a.r(0x2A, 9, 16, 8); a.branch(5, 9, 0, 'member')
    # the side's count (the commit keeps it while COUNT_CASE is patched); a receipt for the host
    a.li(8, SETUP+0xC0); a.branch(4, 17, 0, 'count0'); a.addiu(8, 8, SIDE_STRIDE)
    a.label('count0'); a.lw(9, 19, 0); a.sw(9, 8, 0)
    a.li(8, CONTROL); a.lw(10, 8, F['applied']); a.addiu(10, 10, 1); a.sw(10, 8, F['applied'])
    a.sw(17, 8, F['side']); a.sw(9, 8, F['count'])
    a.jump('done')
    a.label('refuse')
    a.li(8, CONTROL); a.lw(9, 8, F['refused']); a.addiu(9, 9, 1); a.sw(9, 8, F['refused'])
    a.label('done')
    a.i(55, 2, 29, 96)
    a.i(49, 12, 29, 64)
    for off, reg in SAVED:
        a.i(55, reg, 29, off)
    a.addiu(29, 29, SAVE)
    a.jr()
    data = a.finish()
    assert CODE + len(data) <= TYPE_STUB
    return data


def pad_code():
    """Called from the Modded Modes pad hook (native_mode_menu.payload) once READY.
    It withholds pads:
    - in the tournament entry (scene 34) while CONTROL+block is set, the disc's accept (Back still works): the entry
      cannot go on with a wrong How many people number;
    - in a roster draft's Team Select (scene 40, DRAFT published) once stage selection opened, every button of both
      ports: nobody picks a stage, backs out or starts a battle while the host reads the picks and restores the
      main menu under its cover."""
    from regional import MENU_ACCEPT
    a = Assembler(PAD_CODE)
    a.li(9, SCENE_MANAGER); a.lw(9, 9)
    a.li(10, 0x100000); a.r(0x2B, 10, 9, 10); a.branch(5, 10, 0, 'out')
    a.li(10, 0x1FFF000); a.r(0x2B, 10, 9, 10); a.branch(4, 10, 0, 'out')
    a.lw(9, 9, 0x18)
    a.addiu(10, 0, BRACKET_SCENE); a.branch(5, 9, 10, 'entry')
    a.jump(WATCH_CODE)                   # scene 35: the CPU-match helper (a0 = the pad routine's caller)
    a.label('entry')
    a.addiu(10, 0, ENTRY_SCENE); a.branch(5, 9, 10, 'draft')
    a.li(8, CONTROL); a.lw(10, 8, F['block']); a.branch(4, 10, 0, 'out'); a.jump('mask')
    a.label('draft')
    a.addiu(10, 0, SELECT_SCENE); a.branch(5, 9, 10, 'out')
    a.li(8, DRAFT); a.lw(10, 8); a.li(11, DRAFT_MAGIC); a.branch(5, 10, 11, 'out')
    a.li(8, TEAM_SELECT); a.lw(8, 8); a.i(12, 10, 8, 3); a.branch(5, 10, 0, 'out')
    a.li(10, 0x100000); a.r(0x2B, 10, 8, 10); a.branch(5, 10, 0, 'out')
    a.li(10, 0x1FF0000); a.r(0x2B, 10, 8, 10); a.branch(4, 10, 0, 'out')
    a.lw(10, 8, SEL_FLAGS); a.i(12, 10, 10, 4); a.branch(4, 10, 0, 'out')
    a.li(8, PAD_RECORDS)
    for port in (0, 0x1C0):                                 # both ports: raw and translated words
        for off in (0x150, 0x18C, 0x190):
            a.sw(0, 8, port+off)
    a.jump('out')
    a.label('mask')
    a.li(8, PAD_RECORDS)
    for off in (0x18C, 0x190, 0x1C0+0x18C, 0x1C0+0x190):    # both ports' translated words
        a.lw(9, 8, off); a.i(12, 9, 9, 0xFFFF & ~MENU_ACCEPT); a.sw(9, 8, off)
    a.label('out'); a.jr()
    data = a.finish()
    assert PAD_CODE + len(data) <= DRAW_CODE
    return data


DRAW_SAVED = ((0, 31), (8, 16), (16, 20), (24, 21))


def draw_code():
    """Called after the native fade (native_menu_services.fade) once READY: draws the host's picture (DRAWBUF, one
    GIF packet of sprite rectangles, CONTROL+draw_len bytes) in the scene CONTROL+draw_scene names (0: any of
    33-35), while the host's lease (CONTROL+draw_lease frames) lasts. Same checked GIF arena contract as
    player_slot_labels."""
    from native_map import GPO
    # Only called by the fade hook after its full register save (native_menu_services.fade): a small frame for ra
    # and the saved registers used here is enough.
    a = Assembler(DRAW_CODE)
    a.addiu(29, 29, -0x20)
    for off, reg in DRAW_SAVED:
        a.i(63, reg, 29, off)
    a.li(16, CONTROL)
    a.call(VEIL_CHECK); a.branch(4, 2, 0, 'picture')       # the draft's black veil over the Team Select
    a.move(21, 2); a.li(20, VEIL); a.jump('arena')
    a.label('picture')
    a.lw(21, 16, F['draw_len']); a.branch(4, 21, 0, 'done')
    a.li(9, DRAW_CAPACITY); a.r(0x2B, 9, 9, 21); a.branch(5, 9, 0, 'done')
    a.lw(9, 16, F['draw_lease']); a.branch(4, 9, 0, 'done'); a.addiu(9, 9, -1); a.sw(9, 16, F['draw_lease'])
    a.lw(9, 16, F['draw_frames']); a.addiu(9, 9, 1); a.sw(9, 16, F['draw_frames'])
    a.li(9, SCENE_MANAGER); a.lw(9, 9)
    a.li(10, 0x100000); a.r(0x2B, 10, 9, 10); a.branch(5, 10, 0, 'done')
    a.li(10, 0x1FFF000); a.r(0x2B, 10, 9, 10); a.branch(4, 10, 0, 'done')
    a.lw(9, 9, 0x18); a.lw(10, 16, F['draw_scene']); a.branch(4, 10, 0, 'any_scene')
    a.branch(5, 9, 10, 'done'); a.jump('scene_ok')
    a.label('any_scene'); a.addiu(9, 9, -TYPE_SCENE); a.i(11, 9, 9, 3); a.branch(4, 9, 0, 'done')
    a.label('scene_ok')
    a.li(20, DRAWBUF)
    a.label('arena')
    a.lw(8, 28, -23004); a.i(11, 9, 8, 2); a.branch(4, 9, 0, 'done')
    a.r(0, 8, 0, 8, 2); a.r(0x2D, 8, 28, 8)
    a.lw(9, 8, GPO(-23024)); a.lw(10, 8, GPO(-23016)); a.lw(11, 28, -23008)
    a.r(0x2D, 11, 11, 9); a.branch(5, 11, 10, 'done')
    a.lw(11, 28, -23000); a.r(0x2B, 12, 11, 9); a.branch(5, 12, 0, 'done')
    a.r(0x2D, 12, 11, 21); a.addiu(12, 12, 64); a.r(0x2B, 13, 12, 11); a.branch(5, 13, 0, 'done')
    a.r(0x2B, 13, 10, 12); a.branch(5, 13, 0, 'done')
    a.call(A(0x100878)); a.r(0x21, 9, 20, 21); a.move(10, 2)
    a.label('copy')
    for off in (0, 8):
        a.i(55, 11, 20, off); a.i(63, 11, 10, off)
    a.addiu(20, 20, 16); a.addiu(10, 10, 16); a.branch(5, 20, 9, 'copy')
    a.move(4, 10); a.call(A(0x100890))
    a.label('done')
    for off, reg in DRAW_SAVED:
        a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x20); a.jr()
    data = a.finish()
    assert DRAW_CODE + len(data) <= SETUP_STUB
    return data


def veil_check_code():
    """Leaf for draw_code: v0 = the VEIL length to draw, else 0 - Team Select (scene 40) with DRAFT and a VEIL
    published, once its stage selection opened. t0-t3 only."""
    a = Assembler(VEIL_CHECK)
    a.move(2, 0)
    a.li(9, SCENE_MANAGER); a.lw(9, 9)
    a.li(10, 0x100000); a.r(0x2B, 10, 9, 10); a.branch(5, 10, 0, 'none')
    a.li(10, 0x1FFF000); a.r(0x2B, 10, 9, 10); a.branch(4, 10, 0, 'none')
    a.lw(9, 9, 0x18); a.addiu(10, 0, SELECT_SCENE); a.branch(5, 9, 10, 'none')
    a.li(8, DRAFT); a.lw(10, 8); a.li(11, DRAFT_MAGIC); a.branch(5, 10, 11, 'none')
    a.lw(11, 8, DRAFT_VEIL); a.branch(4, 11, 0, 'none')
    a.addiu(9, 0, VEIL_CAPACITY); a.r(0x2B, 9, 9, 11); a.branch(5, 9, 0, 'none')
    a.li(8, TEAM_SELECT); a.lw(8, 8); a.i(12, 10, 8, 3); a.branch(5, 10, 0, 'none')
    a.li(10, 0x100000); a.r(0x2B, 10, 8, 10); a.branch(5, 10, 0, 'none')
    a.li(10, 0x1FF0000); a.r(0x2B, 10, 8, 10); a.branch(4, 10, 0, 'none')
    a.lw(10, 8, SEL_FLAGS); a.i(12, 10, 10, 4); a.branch(4, 10, 0, 'none')
    a.move(2, 11)
    a.label('none'); a.jr()
    data = a.finish()
    assert VEIL_CHECK + len(data) <= WATCH_CODE
    return data


def _auto_checks(a, scene):
    """Stand-in guards (t0 = AUTO, t5 = people, t6 = scene manager): armed, the auto entry published with sane
    values, the manager in RAM and in `scene`; else 'native'."""
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'native')
    a.li(8, AUTO); a.lw(9, 8); a.li(10, AUTO_MAGIC); a.branch(5, 9, 10, 'native')
    a.lw(11, 8, 4); a.i(11, 9, 11, len(TYPES)); a.branch(4, 9, 0, 'native')
    a.lw(12, 8, 8); a.i(11, 9, 12, len(DIFFICULTIES)); a.branch(4, 9, 0, 'native')
    a.lw(13, 8, 12); a.addiu(9, 13, -1); a.i(11, 9, 9, AUTO_MAX); a.branch(4, 9, 0, 'native')
    a.li(14, SCENE_MANAGER); a.lw(14, 14)
    a.li(9, 0x100000); a.r(0x2B, 9, 14, 9); a.branch(5, 9, 0, 'native')
    a.li(9, 0x1FFF000); a.r(0x2B, 9, 14, 9); a.branch(4, 9, 0, 'native')
    a.lw(9, 14, 0x18); a.addiu(10, 0, scene); a.branch(5, 9, 10, 'native')


def type_stub():
    """Stands in for the type menu (TYPE_CALL, a0 = 1): Free, the type, the difficulty and How many people from
    the auto entry, returns 1 (the dispatcher goes on to scene 34). Anything unexpected: the native menu (tail call,
    the dispatcher's a0 / ra). A leaf: no frame."""
    a = Assembler(TYPE_STUB)
    _auto_checks(a, TYPE_SCENE)
    a.addiu(9, 0, 1); a.sw(9, 14, MGR_FREE)
    a.sw(11, 14, MGR_TYPE); a.sw(12, 14, MGR_DIFFICULTY); a.sw(13, 14, MGR_HUMANS)
    a.addiu(2, 0, 1); a.jr()
    a.label('native'); a.jump(TYPE_MENU)
    data = a.finish()
    assert TYPE_STUB + len(data) <= ENTRY_STUB
    return data


def entry_stub():
    """Stands in for the registration (ENTRY_CALL, a0 = 2): clears the 17 entrant records of the manager copy (as
    the registration's own start does), writes one human record per auto entry (flags, character, costume, the
    registration order, items), clears the auto entry (one shot: the pnach puts both native calls back) and returns
    1 (scene 35 starts). Anything unexpected: the native registration. A leaf: no frame."""
    a = Assembler(ENTRY_STUB)
    _auto_checks(a, ENTRY_SCENE)
    a.addiu(9, 14, MGR_ENTRANTS); a.addiu(10, 9, ENTRANTS*ENTRANT_BYTES)
    a.label('clear'); a.sw(0, 9, 0); a.addiu(9, 9, 4); a.branch(5, 9, 10, 'clear')
    a.move(15, 0); a.addiu(9, 8, AUTO_ENTRY); a.addiu(10, 14, MGR_ENTRANTS)
    a.label('entry')
    a.lw(11, 9, 8); a.i(41, 11, 10, 0)                  # flags
    a.lw(11, 9, 0); a.sw(11, 10, 4)                     # character
    a.lw(11, 9, 4); a.sw(11, 10, 8)                     # costume
    a.sw(15, 10, 12)                                    # registration order
    for off in (0, 4, 8, 12):
        a.lw(11, 9, 16+off); a.sw(11, 10, 0x18+off)     # Potara items
    a.addiu(15, 15, 1); a.addiu(9, 9, AUTO_STRIDE); a.addiu(10, 10, ENTRANT_BYTES)
    a.branch(5, 15, 13, 'entry')
    a.sw(0, 8, 0)
    a.addiu(2, 0, 1); a.jr()
    a.label('native'); a.jump(REGISTRATION)
    data = a.finish()
    assert ENTRY_STUB + len(data) <= TRAMP
    return data


SETUP_SAVED = ((0, 31), (8, 16), (16, 17), (24, 18), (32, 19))
SWAP_TRIES = 8


def setup_stub():
    """Stands in for the entrant setup call of scene 35's fresh start (SETUP_CALL, a0 = the runtime object): runs
    the native setup, then gives every CPU entrant (not human, not the boss) whose character is LOCKED a spare drawn
    with the game's rand (up to SWAP_TRIES draws for one nobody in the bracket has yet), costume 0, and counts the
    swaps (CONTROL+swapped). No spares (or not armed): the native setup alone."""
    a = Assembler(SETUP_STUB)
    a.addiu(29, 29, -0x30)
    for off, reg in SETUP_SAVED:
        a.i(63, reg, 29, off)
    a.move(16, 4)
    a.call(ENTRANT_SETUP)
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'done')
    a.li(8, SPARES); a.lw(9, 8); a.addiu(9, 9, -1); a.i(11, 9, 9, SPARE_MAX); a.branch(4, 9, 0, 'done')
    a.move(17, 0)
    a.label('entrant')
    a.addiu(9, 0, ENTRANT_BYTES); a.r(0x18, 0, 17, 9); a.r(0x12, 19, 0); a.r(0x21, 19, 19, 16)
    a.addiu(19, 19, OBJ_ENTRANTS)                                    # s3 = this entrant's record
    a.i(37, 9, 19, 0); a.i(12, 9, 9, HUMAN | BOSS_FLAG); a.branch(5, 9, 0, 'next')
    a.lw(9, 19, 4); a.i(11, 10, 9, 256); a.branch(4, 10, 0, 'next')
    a.r(2, 10, 0, 9, 3); a.li(11, LOCKED); a.r(0x21, 10, 10, 11); a.i(36, 10, 10, 0)
    a.i(12, 9, 9, 7); a.addiu(11, 0, 1); a.r(4, 11, 9, 11); a.r(0x24, 10, 10, 11)
    a.branch(4, 10, 0, 'next')
    a.addiu(18, 0, SWAP_TRIES)
    a.label('draw')
    a.li(8, SPARES); a.lw(4, 8); a.call(RAND)
    a.li(8, SPARES); a.lw(9, 8); a.r(0x2B, 9, 2, 9); a.branch(4, 9, 0, 'next')     # rand(count) in range
    a.r(0, 9, 0, 2, 1); a.r(0x21, 9, 9, 8); a.i(37, 9, 9, 4)          # t1 = spares[v0]
    a.addiu(18, 18, -1); a.branch(4, 18, 0, 'take')
    a.addiu(10, 16, OBJ_ENTRANTS+4); a.addiu(11, 10, ENTRANTS*ENTRANT_BYTES)
    a.label('dup')
    a.lw(12, 10, 0); a.branch(4, 12, 9, 'draw')
    a.addiu(10, 10, ENTRANT_BYTES); a.branch(5, 10, 11, 'dup')
    a.label('take')
    a.sw(9, 19, 4); a.sw(0, 19, 8)
    a.li(8, CONTROL); a.lw(9, 8, F['swapped']); a.addiu(9, 9, 1); a.sw(9, 8, F['swapped'])
    a.label('next')
    a.addiu(17, 17, 1); a.addiu(9, 0, BOSS); a.branch(5, 17, 9, 'entrant')
    a.label('done')
    for off, reg in SETUP_SAVED:
        a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x30); a.jr()
    data = a.finish()
    assert SETUP_STUB + len(data) <= CONTROL, hex(len(data))
    return data


def jal(target):
    return 0x0C000000 | (target >> 2) & 0x3FFFFFF


def ready_call(a, target, skip):
    """Emit 'call target if the armed pnach published READY' (resident callers: the pad hook and the fade)."""
    a.li(8, READY); a.lw(9, 8); a.li(10, READY_MAGIC); a.branch(5, 9, 10, skip)
    a.call(target)
    a.label(skip)


def hook_words(target=CODE):
    return struct.pack('<2I', (2 << 26) | (target >> 2), 0)


def code_pieces():
    """(address, bytes) the armed pnach block writes: cave and trampoline, the stand-ins, the count case, then the
    hook (last)."""
    return [(CODE, cave_code()), (TRAMP, tramp_code()), (TYPE_STUB, type_stub()), (ENTRY_STUB, entry_stub()),
            (SETUP_STUB, setup_stub()), (COUNT_CASE, struct.pack('<I', COUNT_KEEP)), (HOOK, hook_words(CODE))]


def call_sites():
    """(overlay call site, native target, stand-in, needs the auto entry): the dispatcher's type menu and
    registration calls (only while an auto entry is published) and scene 35's entrant setup call (while armed)."""
    return ((TYPE_CALL, TYPE_MENU, TYPE_STUB, True), (ENTRY_CALL, REGISTRATION, ENTRY_STUB, True),
            (SETUP_CALL, ENTRANT_SETUP, SETUP_STUB, False))


def service_pieces():
    """(address, bytes) of the helpers resident callers run once READY: the pad mask, the picture and the
    CPU-match helper."""
    return [(PAD_CODE, pad_code()), (VEIL_CHECK, veil_check_code()), (DRAW_CODE, draw_code()), (WATCH_CODE, watch_code())]


WATCH_SAVED = ((0, 31), (8, 16), (16, 17), (24, 18), (32, 19))


def _clear_human(a, base, offset_reg, scratch=12):
    """Clear bit 0 of the halfword at base+offset_reg (an entrant's flags or a row's played bit)."""
    a.r(0x21, scratch, base, offset_reg); a.i(37, 13, scratch, 0); a.r(2, 13, 0, 13, 1); a.r(0, 13, 0, 13, 1)
    a.i(41, 13, scratch, 0)


def _withhold(a, pads):
    """Both ports' decision words (+0x18C pressed, +0x190) withheld; the held word +0x188 keeps only the two
    directions the bracket wait scrolls the bracket on, so Left/Right still look over the participants."""
    for port in (0, 0x1C0):
        a.lw(11, pads, port+0x188); a.i(12, 11, 11, HELD_SCROLL); a.sw(11, pads, port+0x188)
        for off in (0x18C, 0x190):
            a.sw(0, pads, port+off)


def watch_code():
    """Scene-35 CPU-match helper (pad_code jumps here; a0 = the pad routine's caller, only the bracket loop's
    own call at BRACKET_PAD_RETURN acts). With CONTROL+watch armed, in the plain bracket wait (+0x2DC bit 4, none of
    WAIT_BUSY, no message / face load) it:
    1. after a return from a launched row (wclean), clears the side-0 human mark and the protected played bits the
       host wrote into the scene manager copy for that return;
    2. clears the stop mark on the row the native advance stopped at (wstop);
    3. points the bracket at the first unplayed row; a CPU-vs-CPU row is asked (ask = row+1): the pad's decision
       words are withheld and raw presses latched (wbuttons) until the host answers: Watch = the native accept
       (VS_START, flip +0x2DC bit 4, ACCEPT_SOUND); Skip = the native instant result (ROW_RESULT) then the native
       advance (ROW_ADVANCE), with a stop mark on the next CPU row's entrant A for that call only. An expired host
       lease answers Skip."""
    a = Assembler(WATCH_CODE)
    a.addiu(29, 29, -0x30)
    for off, reg in WATCH_SAVED:
        a.i(63, reg, 29, off)
    a.li(8, BRACKET_PAD_RETURN); a.branch(5, 4, 8, 'done')
    a.li(16, CONTROL); a.lw(8, 16, F['magic']); a.li(9, MAGIC); a.branch(5, 8, 9, 'done')
    a.lw(8, 16, F['watch']); a.branch(4, 8, 0, 'done')
    a.li(8, RUNTIME); a.lw(17, 8)
    a.li(9, 0x100000); a.r(0x2B, 9, 17, 9); a.branch(5, 9, 0, 'done')
    a.li(9, 0x1FFC000); a.r(0x2B, 9, 17, 9); a.branch(4, 9, 0, 'done')
    a.li(8, SCENE_MANAGER); a.lw(18, 8)
    a.li(9, 0x100000); a.r(0x2B, 9, 18, 9); a.branch(5, 9, 0, 'done')
    a.li(9, 0x1FFF000); a.r(0x2B, 9, 18, 9); a.branch(4, 9, 0, 'done')
    a.lw(8, 16, F['wframes']); a.addiu(8, 8, 1); a.sw(8, 16, F['wframes'])
    # ---- 1. the return from a launched row: its result is applied (played bit) -> remove the host's marks
    a.lw(8, 16, F['wclean']); a.branch(4, 8, 0, 'stop')
    a.addiu(8, 8, -1); a.r(0, 8, 0, 8, 4); a.r(0x21, 9, 17, 8); a.i(37, 9, 9, OBJ_ROWS); a.i(12, 9, 9, 1)
    a.branch(4, 9, 0, 'stop')
    a.lw(10, 16, F['we0']); a.branch(4, 10, 0, 'prot')
    a.addiu(10, 10, -1); a.addiu(11, 0, ENTRANT_BYTES); a.r(0x18, 0, 10, 11); a.r(0x12, 10, 0)
    a.addiu(11, 10, OBJ_ENTRANTS); _clear_human(a, 17, 11)
    a.addiu(11, 10, MGR_ENTRANTS); _clear_human(a, 18, 11)
    a.label('prot')
    a.lw(10, 16, F['wprot'])
    for row in range(CPU_ROWS):
        a.i(12, 11, 10, 1 << row); a.branch(4, 11, 0, f'prot{row}')
        a.addiu(11, 0, OBJ_ROWS + 16*row); _clear_human(a, 17, 11)
        a.addiu(11, 0, MGR_ROWS + 16*row); _clear_human(a, 18, 11)
        a.label(f'prot{row}')
    a.sw(0, 16, F['wclean']); a.sw(0, 16, F['we0']); a.sw(0, 16, F['wprot'])
    a.label('stop')
    # ---- the plain bracket wait only
    a.lw(8, 17, OBJ_WAIT); a.i(12, 9, 8, 4); a.branch(4, 9, 0, 'idle')
    a.i(12, 9, 8, WAIT_BUSY); a.branch(5, 9, 0, 'busy')
    for off in (OBJ_MESSAGE, OBJ_FACES):     # (+0x1A3C keeps the round's script pointer while it waits)
        a.lw(9, 17, off); a.branch(5, 9, 0, 'busy')
    # ---- 2. the stop mark: the advance stopped here; the row is a CPU row again
    a.lw(8, 16, F['wstop']); a.branch(4, 8, 0, 'find')
    a.addiu(8, 8, -1); a.lw(9, 17, OBJ_ROW); a.branch(5, 8, 9, 'find')
    a.r(0, 8, 0, 8, 4); a.r(0x21, 8, 17, 8); a.i(37, 10, 8, OBJ_ROWS+2)
    a.addiu(11, 0, ENTRANT_BYTES); a.r(0x18, 0, 10, 11); a.r(0x12, 10, 0)
    a.addiu(11, 10, OBJ_ENTRANTS); _clear_human(a, 17, 11)
    a.addiu(11, 10, MGR_ENTRANTS); _clear_human(a, 18, 11)
    a.sw(0, 16, F['wstop'])
    # ---- 3. the first unplayed row
    a.label('find')
    a.move(19, 0)
    a.label('scan')
    a.r(0, 8, 0, 19, 4); a.r(0x21, 8, 17, 8); a.i(37, 9, 8, OBJ_ROWS); a.i(12, 9, 9, 1); a.branch(4, 9, 0, 'found')
    a.addiu(19, 19, 1); a.i(11, 9, 19, CPU_ROWS); a.branch(5, 9, 0, 'scan')
    a.jump('idle')
    a.label('found')                    # t0 = obj + row*16
    for k, off in enumerate((2, 4)):
        a.i(37, 10, 8, OBJ_ROWS+off); a.i(11, 9, 10, ENTRANTS); a.branch(4, 9, 0, 'idle')
        a.addiu(11, 0, ENTRANT_BYTES); a.r(0x18, 0, 10, 11); a.r(0x12, 10, 0); a.r(0x21, 10, 10, 17)
        a.i(37, 10, 10, OBJ_ENTRANTS); a.i(12, 10, 10, HUMAN); a.branch(5, 10, 0, 'idle')
    # a CPU vs CPU row: the bracket waits on it, the host is asked
    a.sw(19, 17, OBJ_ROW)
    a.addiu(8, 19, 1); a.sw(8, 16, F['ask'])
    a.li(8, PAD_RECORDS)
    _withhold(a, 8)
    a.lw(9, 8, 0x150); a.lw(10, 8, 0x1C0+0x150); a.r(0x25, 9, 9, 10)
    a.lw(10, 16, F['wprev']); a.sw(9, 16, F['wprev']); a.r(0x27, 10, 10, 0); a.r(0x24, 9, 9, 10)
    a.lw(10, 16, F['wbuttons']); a.r(0x25, 10, 10, 9); a.sw(10, 16, F['wbuttons'])
    a.lw(8, 16, F['answer'])
    a.lw(9, 16, F['wlease']); a.branch(5, 9, 0, 'leased')
    a.addiu(8, 0, 2)                    # no host: Skip
    a.label('leased')
    a.branch(4, 9, 0, 'answer'); a.addiu(9, 9, -1); a.sw(9, 16, F['wlease'])
    a.label('answer')
    a.branch(4, 8, 0, 'done')
    a.sw(0, 16, F['answer']); a.sw(0, 16, F['ask']); a.sw(0, 16, F['wbuttons'])
    a.addiu(9, 0, 1); a.branch(5, 8, 9, 'skip')
    a.move(4, 17); a.call(VS_START)                                        # Watch: the native accept
    a.lw(8, 17, OBJ_WAIT); a.i(14, 8, 8, 4); a.sw(8, 17, OBJ_WAIT)
    a.addiu(4, 0, 1); a.addiu(5, 0, 1); a.call(ACCEPT_SOUND)
    a.jump('done')
    a.label('skip')
    a.move(4, 17); a.move(5, 19); a.call(ROW_RESULT)                      # Skip: the native instant result
    a.addiu(8, 19, 1); a.i(11, 9, 8, CPU_ROWS); a.branch(4, 9, 0, 'advance')
    a.r(0, 8, 0, 8, 4); a.r(0x21, 8, 17, 8)
    a.i(37, 10, 8, OBJ_ROWS+2); a.i(37, 11, 8, OBJ_ROWS+4)
    for reg in (10, 11):
        a.i(11, 9, reg, ENTRANTS); a.branch(4, 9, 0, 'advance')
    for reg in (11, 10):                # t2 ends as A's record offset
        a.addiu(12, 0, ENTRANT_BYTES); a.r(0x18, 0, reg, 12); a.r(0x12, reg, 0)
        a.r(0x21, 13, reg, 17); a.i(37, 13, 13, OBJ_ENTRANTS); a.i(12, 13, 13, HUMAN); a.branch(5, 13, 0, 'advance')
    a.r(0x21, 13, 10, 17); a.i(37, 12, 13, OBJ_ENTRANTS); a.i(13, 12, 12, HUMAN); a.i(41, 12, 13, OBJ_ENTRANTS)
    a.sw(10, 29, 40)
    a.move(4, 17); a.call(ROW_ADVANCE)                                     # stops at the marked next CPU row
    a.lw(10, 29, 40); a.addiu(11, 10, OBJ_ENTRANTS); _clear_human(a, 17, 11)
    a.jump('done')
    a.label('advance')
    a.move(4, 17); a.call(ROW_ADVANCE)
    a.jump('done')
    # ---- an accept wait that is not plain yet (moving, message, faces): a CPU-vs-CPU current row (or the row
    # holding the stop mark) never takes the native accept - only the answer launches it
    a.label('busy')
    a.lw(8, 17, OBJ_ROW); a.lw(9, 16, F['wstop']); a.addiu(10, 8, 1); a.branch(4, 9, 10, 'withhold')
    a.i(11, 9, 8, CPU_ROWS); a.branch(4, 9, 0, 'idle')
    a.r(0, 8, 0, 8, 4); a.r(0x21, 8, 17, 8)
    for off in (2, 4):
        a.i(37, 10, 8, OBJ_ROWS+off); a.i(11, 9, 10, ENTRANTS); a.branch(4, 9, 0, 'idle')
        a.addiu(11, 0, ENTRANT_BYTES); a.r(0x18, 0, 10, 11); a.r(0x12, 10, 0); a.r(0x21, 10, 10, 17)
        a.i(37, 10, 10, OBJ_ENTRANTS); a.i(12, 10, 10, HUMAN); a.branch(5, 10, 0, 'idle')
    a.label('withhold')
    a.li(8, PAD_RECORDS)
    _withhold(a, 8)
    a.label('idle')
    a.sw(0, 16, F['ask'])
    a.label('done')
    for off, reg in WATCH_SAVED:
        a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x30); a.jr()
    data = a.finish()
    assert WATCH_CODE + len(data) <= DRAWBUF, hex(len(data))
    return data


# Written back once the tournament is disarmed, only while the hook is still present (no per-frame code writes).
NATIVE_WORDS = ((HOOK, ORIGINAL), (COUNT_CASE, (COUNT_FORCE,)))


def _d(address, count, equal, value):
    return f'patch=1,EE,D{address & 0x0FFFFFFF:07X},extended,{count:02X}{0 if equal else 1}0{value:04X}'


def _w(address, word):
    return f'patch=1,EE,2{address & 0x0FFFFFFF:07X},extended,{word:08X}'


def _words(pieces):
    out = []
    for address, data in pieces:
        out += [(address+o, struct.unpack_from('<I', data, o)[0]) for o in range(0, len(data), 4)]
    return out


def pnach_lines():
    """Extended pnach lines (D-code: Daaaaaaa nntXvvvv - if the halfword at aaaaaaa equals (t 0) or differs from
    (t 1) vvvv, apply the next nn lines, else skip them; nested blocks work; blocks stay under 200 lines):
    - armed or drafting, READY not yet published: the helpers, then READY (once per arming or draft);
    - neither: READY cleared (once);
    - armed and the hook not yet there: the cave, the count case and the hook (last), once per arming;
    - not armed while the hook is still there: the native words, once."""
    lines = []
    services = _words(service_pieces()) + [(READY, READY_MAGIC)]   # READY last: after every helper word
    for gate, value in ((CONTROL, ARMED), (DRAFT, DRAFT_MAGIC & 0xFFFF)):
        for start in range(0, len(services), 190):
            block = services[start:start+190]
            lines.append(_d(gate, len(block)+1, True, value))
            lines.append(_d(READY, len(block), False, READY_MAGIC & 0xFFFF))
            lines += [_w(address, word) for address, word in block]
    lines += [_d(CONTROL, 3, False, ARMED), _d(DRAFT, 2, False, DRAFT_MAGIC & 0xFFFF),
              _d(READY, 1, True, READY_MAGIC & 0xFFFF), _w(READY, 0)]
    writes = _words(code_pieces())
    for start in range(0, len(writes), 190):
        block = writes[start:start+190]
        lines.append(_d(CONTROL, len(block)+1, True, ARMED))
        lines.append(_d(HOOK+2, len(block), False, HOOK_HIGH))
        lines += [_w(address, word) for address, word in block]
    native = [(address+4*i, word) for address, words in NATIVE_WORDS for i, word in enumerate(words)]
    lines.append(_d(CONTROL, len(native)+1, False, ARMED))
    lines.append(_d(HOOK+2, len(native), True, HOOK_HIGH))
    lines += [_w(address, word) for address, word in native]
    # The overlay call sites: the stand-in only over the native call it replaces (both halfwords checked) and only
    # once the stand-in's first word is in place; the native call back once the gate closes (only over our call).
    auto = (AUTO, AUTO_MAGIC & 0xFFFF)
    for site, target, stub, needs_auto in call_sites():
        native_call, ours = jal(target), jal(stub)
        first, = struct.unpack_from('<I', dict(code_pieces())[stub])
        gates = [(CONTROL, True, ARMED)] + ([(auto[0], True, auto[1])] if needs_auto else [])
        gates += [(stub, True, first & 0xFFFF), (stub+2, True, first >> 16),
                  (site, True, native_call & 0xFFFF), (site+2, True, native_call >> 16)]
        lines += _when(gates, [(site, ours)])
        for gate in [(CONTROL, False, ARMED)] + ([(auto[0], False, auto[1])] if needs_auto else []):
            lines += _when([gate, (site, True, ours & 0xFFFF), (site+2, True, ours >> 16)], [(site, native_call)])
    return lines


def _when(gates, writes):
    """Lines that apply `writes` [(address, word)] in a frame where every gate (address, equal, halfword) holds."""
    body = [_w(address, word) for address, word in writes]
    for address, equal, value in reversed(gates):
        body = [_d(address, len(body), equal, value)] + body
    return body


# ---------------------------------------------------------------- pure model of the native tournament
class Entrant:
    __slots__ = ('index', 'flags', 'character', 'costume', 'player')

    def __init__(self, index, flags, character, costume, player=0):
        self.index, self.flags, self.character, self.costume = index, flags, character, costume
        self.player = player        # +0xC: a human entrant's registration order (0 = the first registered)

    @property
    def human(self):
        return bool(self.flags & HUMAN)

    @property
    def eliminated(self):
        return bool(self.flags & ELIMINATED)

    def __repr__(self):
        return f'Entrant({self.index}, flags={self.flags:#x}, character={self.character}, costume={self.costume})'


def parse_entrants(blob):
    """17 x 40-byte entrant records (runtime object +0x1A68 or scene manager +0x98)."""
    if len(blob) != ENTRANTS*ENTRANT_BYTES:
        raise ValueError('Expected 17 tournament entrant records')
    out = []
    for i in range(ENTRANTS):
        flags, = struct.unpack_from('<H', blob, i*ENTRANT_BYTES)
        character, costume, player = struct.unpack_from('<3I', blob, i*ENTRANT_BYTES+4)
        out.append(Entrant(i, flags, character, costume, player))
    return out


def parse_rows(blob):
    """16 bracket rows: (flags, entrant A, entrant B, next row)."""
    if len(blob) != 16*ROW_RECORD:
        raise ValueError('Expected 16 bracket rows')
    return [struct.unpack_from('<4H', blob, k*ROW_RECORD) for k in range(16)]


def settled(entrants, rows):
    """True once the native setup finished: the first round seats the 16 entrants exactly once, the boss is entrant
    16 and every character is a roster id. The runtime object is read while scene 35 initialises it."""
    seated = sorted(x for flags, a, b, _ in rows[:8] for x in (a, b))
    return (seated == list(range(16)) and all(e.character < roster_size() for e in entrants) and
            bool(entrants[BOSS].flags & BOSS_FLAG))


def sides(entrants, row):
    """(side 0 entrant, side 1 entrant) of a launched row, as 0x36A720 assigns them."""
    _, a, b, _ = row
    return (a, b) if entrants[a].human else (b, a)


# Giant bodies (Great Apes, giant Slug, Hirudegarn) are never drawn as random teammates; they can still be picked.
GIANTS = frozenset((12, 30, 72, 74, 76, 78, 81, 122, 124, 139, 143))
ROSTER = 161                         # BT3; roster_size() reads the chosen disc's own list (BT4: 250)
GIANT_NAMES = ('Great Ape', 'Giant', 'Hirudegarn')


def roster_size():
    """Fighters on the chosen disc (character_names: its extracted characters.json), else BT3's 161."""
    try:
        import character_names
        table = character_names.character_table()
    except Exception:  # noqa: BLE001 - a missing table keeps the BT3 roster
        table = {}
    return max(table) + 1 if table else ROSTER


def roster_pool(exclude=()):
    """Characters a random teammate may be: the disc's named fighters minus giants (by name: BT4 numbers them
    differently) and the excluded ones. Without the disc's table, BT3's ids and GIANTS."""
    try:
        import character_names
        table = character_names.character_table()
    except Exception:  # noqa: BLE001
        table = {}
    excluded = set(exclude)
    if table:
        pool = [c for c, row in sorted(table.items())
                if c not in excluded and row.get('name') and not str(row['name']).startswith('Fighter ')
                and not any(word in str(row['name']) for word in GIANT_NAMES)]
    else:
        pool = [c for c in range(ROSTER) if c not in excluded | GIANTS]
    if not pool:
        raise ValueError('No characters left for a random teammate')
    return pool


LOCK_ART_SHARED = 3                  # a portrait this many roster slots share is the select screen's lock icon


def lock_art_ids():
    """Roster ids whose select-screen portrait is the lock icon: the one picture of the chosen disc's extracted
    portraits (character_names / characters.json) that several slots share. Locked slots are not meant to be played
    (BT4: 162, 231-240, 242-249); every BT3 disc has none."""
    try:
        import hashlib
        import character_names
        table = character_names.character_table()
        folder = character_names.assets_folder()
    except Exception:  # noqa: BLE001 - no table: nothing is known to be locked
        return frozenset()
    groups = {}
    for character, row in table.items():
        try:
            data = (folder / row['portrait']).read_bytes()
        except (KeyError, TypeError, OSError):
            continue
        groups.setdefault(hashlib.sha1(data).digest(), []).append(character)
    return frozenset(c for ids in groups.values() if len(ids) >= LOCK_ART_SHARED for c in ids)


def native_excluded(p):
    """Character ids the game's own entrant pick never takes (its select-screen specials: Random, the password and
    empty slots), read from the running disc: BT3 discs 'slti v0, a0, CAP' at PICK_RULE (ids from CAP up); the BT4
    executable calls its filter there, which refuses 0xA1..0xA4. None when neither is recognised."""
    word = p.read_u32(PICK_RULE)
    if word >> 16 == 0x2882:                                  # slti v0, a0, imm
        return frozenset(range(word & 0xFFFF, 256))
    if word == BT4_PICK_CALL:
        upper, lower = p.read_u32(BT4_FILTER+0x14), p.read_u32(BT4_FILTER+0x1C)
        if upper >> 16 == 0x2A04 and lower >> 16 == 0x2A04:   # slti a0, s0, 0xA5 ... slti a0, s0, 0xA1
            return frozenset(range(lower & 0xFFFF, upper & 0xFFFF))
    return None


SPECIAL_NAMES = ('Random', '? ? ?', 'Password Character', 'Not selectable')   # only when the rule is not readable


def unplayable(p=None):
    """(locked, excluded): the lock-icon ids and unnamed slots the post-pass swaps out of the bracket, and every id
    that is no fighter at all (those plus the native pick's own exclusions) for random teammates and spares."""
    try:
        import character_names
        table = character_names.character_table()
    except Exception:  # noqa: BLE001
        table = {}
    unnamed = {c for c, row in table.items() if not row.get('name') or str(row['name']).startswith('Fighter ')}
    locked = frozenset(lock_art_ids() | unnamed)
    native = native_excluded(p) if p is not None else None
    if native is None:
        native = {c for c, row in table.items() if row.get('name') in SPECIAL_NAMES}
    return locked, frozenset(locked | native)


def character_name(character, settings=None):
    """The fighter's name and form as the mod shows it elsewhere (character_names; English disc names)."""
    try:
        import character_names
        row = character_names.character_table().get(character)
    except Exception:  # noqa: BLE001
        row = None
    if row and row.get('name'):
        return row['name']
    try:
        import regional
        base, form = regional.english_names()[character]
        return f'{base} ({form})' if form else base
    except Exception:  # noqa: BLE001
        return f'#{character}'


def short_name(character):
    """The fighter's name without its form (VS lines are narrow)."""
    return character_name(character).split(' - ')[0].split(' (')[0]


NO_ITEMS = bytes(16)


def member(character, costume=0, items=NO_ITEMS):
    """One roster member: (character, costume, 16 bytes of Potara items as the select writes them)."""
    items = bytes(items or NO_ITEMS)
    if len(items) != 16:
        raise ValueError('Potara items are 16 bytes')
    return (int(character), int(costume), items)


CPU_MATCH_POLICIES = ('ask', 'watch', 'skip')
# The native difficulty (1..3 Dragon Balls: the computer's level and the CPU entrants' strength).
DIFFICULTIES = ('1 Dragon Ball', '2 Dragon Balls', '3 Dragon Balls')


class Setup:
    """What the panel commits: team size, each player's team number, the human teams that follow from them, the
    tournament type and difficulty.

    humans: {player number: team number (0..3)}. Human teams are ordered by team number; a team's players own its
    slots in player order (slot 0 is the leader the tournament registers for the team's first player); slots past
    its players are CPU fighters, picked in the draft by the team's first player."""

    def __init__(self, size, humans=None, cpu_matches='ask', kind=0, level=0):
        if type(size) is not int or not 1 <= size <= TEAM_MAX:
            raise ValueError('Team size must be 1 to 5')
        if cpu_matches not in CPU_MATCH_POLICIES:
            raise ValueError('CPU matches are ask, watch or skip')
        if type(kind) is not int or not 0 <= kind < len(TYPES) or type(level) is not int or not 0 <= level < len(DIFFICULTIES):
            raise ValueError('Unknown tournament type or difficulty')
        self.size = size
        self.cpu_matches = cpu_matches        # CPU-vs-CPU rows: ask before each, always watch, always skip
        self.kind, self.level = kind, level   # native type (manager +0x84) and difficulty (+0x88)
        self.humans = {int(p): int(t) for p, t in (humans or {}).items()}
        if any(p not in (1, 2, 3, 4) or t not in (0, 1, 2, 3) for p, t in self.humans.items()):
            raise ValueError('Players are numbered 1..4 and teams 0..3')
        if sorted(self.humans) != list(range(1, len(self.humans)+1)):
            raise ValueError('Players are numbered from 1 without gaps')

    @property
    def teams(self):
        """[(team number, (player numbers...))] of the human teams, in team order."""
        out = {}
        for player in sorted(self.humans):
            out.setdefault(self.humans[player], []).append(player)
        return [(team, tuple(players)) for team, players in sorted(out.items())]

    @property
    def cpu_only(self):
        return not self.humans

    def owners(self, k):
        """Slot owners of human team k: player numbers, 0 = CPU."""
        players = self.teams[k][1]
        return tuple(players[i] if i < len(players) else 0 for i in range(self.size))

    def entry_count(self):
        """The How-many-people number the native entry must get: one per human team, 1 for CPU only."""
        return len(self.teams) or 1

    def problem(self):
        for team, players in self.teams:
            if len(players) > self.size:
                return ('Team {t} has more players than fighters.', dict(t=team+1))
        return None

    def pickers(self, k):
        """The players who pick team k's slots in the draft (CPU only: player 1 picks the team to follow)."""
        return self.teams[k][1] if self.teams else (1,)

    def to_json(self):
        return dict(size=self.size, humans={str(p): t for p, t in self.humans.items()}, cpu_matches=self.cpu_matches,
                    kind=self.kind, level=self.level)

    @classmethod
    def from_json(cls, data):
        return cls(data['size'], {int(p): t for p, t in data.get('humans', {}).items()},
                   data.get('cpu_matches', 'ask'), data.get('kind', 0), data.get('level', 0))


class Plan:
    """Teams behind the 17 entrants of one tournament.

    teams[i] = [member(...), ...] leader first; players[i] = player numbers (1..4) controlling entrant i's team in
    slot order (empty = CPU team). rosters[k] = the draft of human team k (setup order), leader included. The
    native entry registers the leaders: human entrant k (registration order) is human team k. A leader that differs
    from the draft's slot 1 is adopted (notes says so); the drafted slots 2..N follow it."""

    def __init__(self, setup, rosters=None, seed=None, pool=None, cpu_settings=None):
        self.setup = setup
        self.size = setup.size
        self.rosters = [list(r) for r in (rosters or [])]
        self.random = random.Random(seed)
        self.pool = pool
        self.teams = None
        self.players = None
        self.flags = None
        self.notes = []
        self.cpu_settings = cpu_settings or []
        self.levels = [[0]*TEAM_MAX for _ in range(ENTRANTS)]

    def build(self, entrants):
        # Human entrant k (registration order, entrant +0xC; the bracket seats them anywhere) is human team k.
        # CPU only: the one registered entrant is the followed team (drafted by player 1, every fighter a CPU).
        humans = sorted((e for e in entrants if e.human), key=lambda e: (e.player, e.index))
        teams, players, flags = [], [], []
        human_teams = self.setup.teams
        self.notes = []
        for e in entrants:
            k = humans.index(e) if e.human and (human_teams or self.rosters) else None
            if k is not None and k < len(self.cpu_settings):
                self.levels[e.index] = (list(self.cpu_settings[k])+[0]*TEAM_MAX)[:TEAM_MAX]
            leader = member(e.character, e.costume)
            members = [leader]
            if k is not None and k < len(self.rosters) and self.rosters[k]:
                draft = [member(*m) for m in self.rosters[k]]
                if draft[0][0] != e.character:
                    self.notes.append(dict(team=human_teams[k][0] if k < len(human_teams) else k, entrant=e.index,
                                           drafted=draft[0][0], registered=e.character))
                members += draft[1:self.size]
            used = {m[0] for m in members}
            while len(members) < self.size:
                pool = [c for c in (self.pool or roster_pool()) if c not in used]
                character = self.random.choice(pool)
                members.append(member(character)); used.add(character)
            teams.append(members[:self.size])
            if k is None:
                players.append(()); flags.append(COPY_LEADER_ITEMS)
            elif not human_teams:
                players.append(()); flags.append(0)     # the followed CPU team keeps its drafted loadouts
            elif k < len(human_teams):
                players.append(human_teams[k][1]); flags.append(0)
            else:
                players.append((1,)); flags.append(0)   # more entrants than set-up teams (never after the check)
        self.teams, self.players, self.flags = teams, players, flags
        return self

    def table(self):
        """TABLE bytes for the guest (17 records of ENTRY bytes)."""
        if self.teams is None:
            raise ValueError('Plan not built')
        out = bytearray(ENTRANTS*ENTRY)
        for i, members in enumerate(self.teams):
            struct.pack_into('<2I', out, i*ENTRY, len(members), self.flags[i])
            for m, (character, costume, items) in enumerate(members):
                at = i*ENTRY+8+m*MEMBER
                struct.pack_into('<2I', out, at, character, costume)
                out[at+8:at+24] = items
        return bytes(out)

    def level_table(self):
        if (len(self.levels) != ENTRANTS or any(len(row) != TEAM_MAX for row in self.levels)
                or any(type(v) is not int or not 0 <= v <= 5 for row in self.levels for v in row)):
            raise ValueError('Invalid tournament CPU difficulty table')
        return struct.pack('<85I', *(v for row in self.levels for v in row))

    def match(self, side0, side1):
        """(humans, assignment seats or None, order) of a launched match between two entrants.

        Physical fighter index = 2*slot + side. A human team's players take its slots in player order, starting
        with the leader (slot 0). Match players are numbered in increasing tournament player number; order[j] is the
        tournament player of match player j+1 (whose own controller drives that fighter)."""
        seats = []
        for side, entrant in ((0, side0), (1, side1)):
            for slot, player in enumerate(self.players[entrant][:len(self.teams[entrant])]):
                seats.append((player, 2*slot+side))
        seats.sort()
        if not seats:
            return 0, None, ()
        return len(seats), tuple(seat for _, seat in seats), tuple(player for player, _ in seats)

    def to_json(self):
        return dict(setup=self.setup.to_json(), rosters=[[[c, k, i.hex()] for c, k, i in r] for r in self.rosters],
                    teams=[[[c, k, i.hex()] for c, k, i in t] for t in self.teams or []],
                    players=[list(p) for p in self.players or []], flags=self.flags, notes=self.notes,
                    cpu_settings=self.cpu_settings, levels=self.levels)

    @classmethod
    def from_json(cls, data):
        plan = cls(Setup.from_json(data['setup']),
                   [[member(c, k, bytes.fromhex(i)) for c, k, i in r] for r in data.get('rosters', [])])
        if data.get('teams'):
            plan.teams = [[member(c, k, bytes.fromhex(i)) for c, k, i in t] for t in data['teams']]
            plan.players = [tuple(p) for p in data['players']]
            plan.flags = list(data['flags'])
            plan.notes = list(data.get('notes') or [])
            plan.cpu_settings = data.get('cpu_settings') or []
            plan.levels = data.get('levels') or [[0]*TEAM_MAX for _ in range(ENTRANTS)]
            plan.level_table()
        return plan


def surrender_reason(winner_side):
    """Reason word that makes the native 0x1291C0 choose `winner_side` (0 or 1): the other side surrendered."""
    if winner_side not in (0, 1):
        raise ValueError('winner side must be 0 or 1')
    return SURRENDER_SIDE1 if winner_side == 0 else SURRENDER_SIDE0


def winner_side(flags):
    """Side that won according to result flags, or None. A KO, ring-out or time-out sets only bit 0/1 (no latch
    bit); a surrender sets bit 8 first and the winner bit at teardown (0x1291C0)."""
    if flags & 3 == 1:
        return 0
    if flags & 3 == 2:
        return 1
    return None


# ---------------------------------------------------------------- the roster draft (Team Select passes)
def draft_passes(setup):
    """The Team Select passes of a setup: [(team indices on the left/right)]. Every team is picked here, teams of one
    too (the tournament registers each drafted leader by itself). Two human teams per pass (left and right side), a
    last odd team alone on the left; CPU only: one pass, player 1 picks the team to follow."""
    if setup.cpu_only:
        return [(0,)]
    ks = list(range(len(setup.teams)))
    return [tuple(ks[i:i+2]) for i in range(0, len(ks), 2)]


def pass_receipt(setup, teams):
    """What a draft pass commits like Player Setup would: (choice value, humans, SEATS[4], VALID, owners[10]).

    SEATS is indexed by tournament player (players outside this pass hold 0xFFFFFFFF), so each player keeps their
    own controller lane; owners gives every physical slot of the pass (2*slot+side, slots 0..5: slot 5 is END after
    five picks) to its picker (CPU slots and END: the team's first player) for team_assignment.resolve_code.
    CPU only: no seat and no owner (every slot is labelled CPU); player 1 picks them all (the resolver's default)."""
    if setup.cpu_only:
        return 1, 1, (0xFFFFFFFF,)*4, 0, (0,)*12
    humans = len(setup.humans)
    seats = [0xFFFFFFFF]*4
    owners = [0]*12
    for side, k in enumerate(teams):
        players = setup.teams[k][1]
        for slot in range(TEAM_MAX+1):          # slot `count` is the END turn: the team's first player
            owners[2*slot+side] = players[slot] if slot < min(len(players), setup.size) else players[0]
        for slot, player in enumerate(players):
            seats[player-1] = 2*slot+side
    choice = {1: 1, 2: 7, 3: 17, 4: 12}[humans]
    return choice, humans, tuple(seats), int(humans >= 2), tuple(owners)


def read_selection(p, side):
    """[member(...)] picked on one Team Select side (accepted records only)."""
    obj = p.read_u32(TEAM_SELECT)
    if obj % 4 or not 0x100000 <= obj < 0x1FF0000:
        raise ValueError('Team Select is not open')
    roster = p.read_u32(obj+SEL_SIDES+4*side)
    if roster % 4 or not 0x100000 <= roster < 0x1FF0000:
        raise ValueError('Team Select side is not ready')
    count = p.read_u32(roster+SEL_COUNT)
    if not 1 <= count <= TEAM_MAX:
        raise ValueError('Team Select side has no fighters')
    out = []
    for i in range(count):
        record = p.read(roster+i*SEL_RECORD, SEL_RECORD)
        costume, character = struct.unpack_from('<2I', record, 0x18)
        out.append(member(character, costume, record[0x20:0x30]))
    return out


def selection_state(p):
    """(object, [(count, state) per side], stage select open) of the Team Select, or None."""
    obj = p.read_u32(TEAM_SELECT)
    if obj % 4 or not 0x100000 <= obj < 0x1FF0000 or not p.read_u32(obj+0x3C) & 2:
        return None
    sides_ = []
    for side in range(2):
        roster = p.read_u32(obj+SEL_SIDES+4*side)
        if roster % 4 or not 0x100000 <= roster < 0x1FF0000:
            return None
        sides_.append((p.read_u32(roster+SEL_COUNT), p.read_u32(roster+SEL_STATE), roster))
    return obj, sides_, bool(p.read_u32(obj+SEL_FLAGS) & 4)


def complete_unused_side(p, obj, sides_):
    """A pass with one human team: once its (left) side is Done, the unused right side gets one copy of the left's
    first record and is marked Done too, so the native opens stage selection (and the host reads the left)."""
    (lcount, lstate, left), (rcount, rstate, right) = sides_
    if lstate != SEL_DONE or rstate == SEL_DONE or lcount < 1:
        return False
    if rstate not in (0, 6):
        return False
    p.write(right, p.read(left, SEL_RECORD))
    p.write_u32(right+SEL_COUNT, 1)
    p.write_u32(right+SEL_HOVER, 5)
    p.write_u32(right+SEL_STATE, SEL_DONE)
    return True


# ---------------------------------------------------------------- host: savestates of the fresh native battle
TOKEN = CONTROL + 0x80            # 16 bytes written just before the tournament original is saved
ORIGINAL_NAME = 'tournament-original.p2s'


def save_original(session, p, token):
    """Save the fresh native battle (combat held, nothing prepared yet) into the session's second slot and keep a
    copy in its run folder. `token` is written first so a later load can be recognised. Returns the copy's path."""
    import shutil
    import time
    import zipfile
    p.write(TOKEN, token)
    slot, path = session.check_slot(1)
    before = path.stat().st_mtime_ns if path.exists() else None
    restart_cover_entrance(p)
    p.save_state(slot)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        time.sleep(0.2)
        try:
            stat = path.stat()
            if stat.st_mtime_ns == before or stat.st_size < 0x100000:
                continue
            with zipfile.ZipFile(path) as z:
                z.getinfo('eeMemory.bin')
            target = session.run / ORIGINAL_NAME
            shutil.copyfile(path, target)
            if path.stat().st_mtime_ns != stat.st_mtime_ns:
                target.unlink()
                continue
            session.record_slot(1, target)
            start_covered_copy(session, target)
            return target
        except (FileNotFoundError, PermissionError, zipfile.BadZipFile, KeyError, EOFError):
            continue
    raise TimeoutError('PCSX2 did not save the tournament match start')


COVERED_NAME = 'tournament-original-covered.p2s'


def covered_copy(path, out):
    """A copy of the saved original that draws a plain black owned cover from its first frame (the in-game screen
    adopts the returned record after the load): nothing of the restored battle is ever seen. Returns (out, record)."""
    import zipfile
    import guest_loading_screen as gs
    import patch_state
    import state128
    from native_map import CRC, SERIAL
    from PIL import Image
    record = gs.cover_record(Image.new('RGB', (512, 448), (0, 0, 0)), 'owned')
    with zipfile.ZipFile(path) as z, open(path, 'rb') as raw:
        ram = state128.read_entry(z, raw, z.getinfo(state128.MEMORY))
    blocks = gs.cover_blocks(record, ram)
    manifest = Path(out).with_suffix('.json')
    manifest.write_text(json.dumps(dict(serial=SERIAL, crc=CRC, blocks=blocks)), encoding='utf-8')
    Path(out).unlink(missing_ok=True)
    patch_state.patch(path, manifest, out)
    return Path(out), record


def start_covered_copy(session, original):
    """In the background (the match is prepared and played meanwhile): session.tournament['covered'] =
    covered_copy(...) once written. A failure only logs; the hand-back then loads the plain original."""
    import threading
    match = getattr(session, 'tournament', None)
    if not isinstance(match, dict):
        return

    def work():
        try:
            match['covered'] = covered_copy(original, Path(original).with_name(COVERED_NAME))
        except Exception as error:  # noqa: BLE001 - the plain original still works
            print(f'Tag Team Tournament: the covered copy of the match start was not written ({error}); the result '
                  'hand-back loads the plain copy.', flush=True)
    threading.Thread(target=work, name='tournament-covered-copy', daemon=True).start()


def restart_cover_entrance(p, settle=0.05):
    """The frame in flight when a state is saved is shown once after that state is loaded (live Oct 20: the
    loading card's entrance frame flashed in the black result hand-back). Right before the save, the in-game cover
    starts its entrance again (a cover shown a moment ago is still entering), so that frame is its first, all but
    black step."""
    import time
    import guest_loading_screen as gs
    if p.read_u32(gs.CONTROL) != gs.MAGIC:
        return
    for offset in (12, gs.MENU_FRAMES, gs.CYCLE_WORD, gs.LAST_COUNT, gs.TICK_ACC):
        p.write_u32(gs.CONTROL+offset, 0)
    time.sleep(settle)


def load_original(path, token, client_factory, timeout=40):
    """Load a saved tournament original through a trainer slot lease; True once its token is back in RAM."""
    import shutil
    import time
    from fresh_team_trainer import Session
    lease = Session()
    try:
        slot, target = lease.check_slot(1)
        shutil.copyfile(path, target)
        lease.record_slot(1, path)
        with client_factory() as p:
            p.write(TOKEN, bytes(16))
            p.load_state(slot)
        import guest_loading_screen
        guest_loading_screen.invalidate_buffers()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.1)
            try:
                with client_factory() as p:
                    if p.read(TOKEN, 16) == token:
                        return True
            except OSError:
                continue
        return False
    finally:
        lease.close()


def force_result(p, side):
    """End the running native battle at once with `side` winning: the native surrender request (0x1288F0's two
    stores), the reason first so the latch bit never lands without it. 0x217EF0 acts on it in the fight phase;
    reasons 0x8000/0x10000 (replay) are never written."""
    p.write_u32(RESULT_REASON, surrender_reason(side))
    p.write_u32(RESULT_FLAGS, LATCHED)


# ---------------------------------------------------------------- host: pictures over the native screens
BANNER_FILL, BANNER_EDGE, BANNER_TEXT = (18, 25, 42), (249, 197, 90), (255, 240, 194)
KEY = (255, 0, 255)


def picture_packet(*draws):
    """One GIF packet of sprite rectangles from a keyed 512x448 picture the `draw(image, d)` functions paint (one
    packet: the guest copies a single GIF packet)."""
    from PIL import Image, ImageDraw
    import guest_loading_screen as gs
    im = Image.new('RGB', (512, 448), KEY)
    d = ImageDraw.Draw(im)
    d.fontmode = '1'                      # crisp glyphs: few colours, few rectangles
    for draw in draws:
        if draw is not None:
            draw(im, d)
    rects = gs.image_rectangles(im, key=KEY)
    if not rects:
        return b''
    return gs.gif_packet(rects)


def banner(lines, y=8, warning=False):
    """A boxed banner (one or two lines) across the top (or at y) in the mod's panel colours."""
    return picture_packet(banner_draw(lines, y, warning))


def banner_draw(lines, y=8, warning=False):
    import fonts

    def draw(im, d):
        font = fonts.truetype('sans-bold', 13)
        rows = []
        for text in lines:                       # wrap at the screen width (Spanish lines are longer)
            row = ''
            for word in text.split(' '):
                trial = (row + ' ' + word).strip()
                if row and d.textlength(trial, font=font) > 472:
                    rows.append(row); row = word
                else:
                    row = trial
            rows.append(row)
        top = y if y + 8 + 17*len(rows) <= 446 else 446 - 8 - 17*len(rows)
        widths = [d.textlength(t, font=font) for t in rows]
        w = min(496, int(max(widths)) + 24)
        x = (512 - w)//2
        h = 8 + 17*len(rows)
        y0 = top
        d.rounded_rectangle((x, y0, x+w, y0+h), radius=5, fill=BANNER_FILL,
                            outline=(240, 104, 92) if warning else BANNER_EDGE, width=2)
        for i, text in enumerate(rows):
            tw = d.textlength(text, font=font)
            d.text((x+(w-tw)//2, y0+4+17*i), text, font=font, fill=BANNER_TEXT)
    return draw


def publish_picture(p, packet, scene=0, lease=180):
    """Publish a picture for the guest draw (length last); an empty packet hides it."""
    if not packet:
        p.write_u32(CONTROL+F['draw_len'], 0)
        return
    if len(packet) > DRAW_CAPACITY:
        raise ValueError('Tournament picture exceeds its buffer')
    p.write_u32(CONTROL+F['draw_len'], 0)
    p.write(DRAWBUF, packet)
    p.write(CONTROL+F['draw_scene'], struct.pack('<2I', scene, lease))
    p.write_u32(CONTROL+F['draw_len'], len(packet))


def veil_packet():
    """The draft's plain black VEIL: one full-screen sprite."""
    return picture_packet(lambda im, d: d.rectangle((0, 0, 511, 447), fill=(0, 0, 0)))


# ---------------------------------------------------------------- host: the Tournament Setup panel
TITLE = 'TAG TEAM TOURNAMENT'
INTRO = 'Teams of one to five fight through the World Tournament.'
PLAYERS_ROW = 'Players'
CPU_ONLY = 'CPU only'
TEAM_SIZE = 'Team size'
PLAYER_TEAM = 'PLAYER {n}'
TEAM_VALUE = '<  TEAM {t}  >'
TEAM_LINE = 'TEAM {t}'
PLAYER_SLOT = 'Fighter {k}: Player {p}'
CPU_SLOT = 'Fighter {k}: CPU'
LEADER_SLOT_SHORT, PLAYER_SLOT_SHORT, CPU_SLOT_SHORT = 'Leader: Player {p}', '{k}: Player {p}', '{k}: CPU'
SUMMARY_ONE = 'Next: Team {t} picks its fighters (Team Battle select), then the tournament starts on its own.'
SUMMARY_TWO = ('Next: one fighter select for both teams (Team {t} top, Team {u} bottom), then the tournament '
               'starts on its own.')
SUMMARY_MANY = ('Next: the fighter select, two teams at a time ({n} teams), then the tournament starts on its own.')
ORDER_ITEM = 'Team {t} - Player {p}'
CPU_NOTE = ('CPU only: Player 1 picks the team to follow (every fighter is a CPU), then the tournament starts on '
            'its own.')
TOO_MANY = 'Team {t} has more players than fighters.'
TYPE_ROW, LEVEL_ROW = 'Tournament', 'Difficulty'
CONTINUE_LABEL, CLEAR_LABEL = 'Continue', 'Clear check-ins'
FOOTER_P1 = 'Up/Down select · Left/Right change'
FOOTER_ALL = '{accept} continue · {back} back · START join · SELECT leave'
ROW_H = 22
CPU_MATCHES_ROW = 'CPU matches'
CPU_MATCH_VALUES = dict(ask='Ask each time', watch='Always watch', skip='Always skip')
TEAM_COLORS = ('BLUE', 'ORANGE', 'GREEN', 'GOLD')
# Guidance over the native screens
BANNER_DRAFT = 'Team {t} - Player {p}: pick fighters 1 to {n} (Custom = Potara, then color), then confirm the team.'
BANNER_DRAFT_TWO = 'Top: Team {t}. Bottom: Team {u}. Pick fighters 1 to {n} each, then confirm the team.'
BANNER_DRAFT_SOLO = 'Team {t} - Player {p}: pick your fighter (Custom = Potara, then color), then confirm.'
BANNER_DRAFT_SOLO_TWO = 'Top: Team {t}. Bottom: Team {u}. Each picks one fighter, then confirms.'
BANNER_DRAFT_CPU = 'Player 1: pick the team to follow, fighters 1 to {n} (all CPU), then confirm the team.'
# Only when the stand-ins could not run (the game's own type menu and registration then show):
BANNER_COUNT = 'At the entry choose How many people = {n}, then register in this order:'
CPU_NOTE_SHORT = 'CPU only: register the one leader to follow.'
BANNER_TURN = 'Team {t} - Player {p}, this way please!'
BANNER_TURN_HINT = 'Register your leader: {name}.'
BANNER_TURN_PLAIN = 'Register your team leader.'
BANNER_TURN_CPU = 'Register the leader you want to follow!'
VS_TEAM = 'with {names}'               # the teammates under the leader's name (the bracket shows leaders only)
QUESTION = 'Next is a CPU match: {a}\'s team vs {b}\'s team. Watch it?'
QUESTION_KEYS = '{accept}: Watch · {back}: Skip'
QUESTION_SECONDS = 20.0     # without an answer (counted from the last Left/Right) the CPU match is skipped
WATCH_LEASE = 600            # guest frames a CPU row waits for the host's answer before it is skipped
BANNER_MISMATCH = 'How many people is {got}, but this tournament has {n} human team(s).'
BANNER_MISMATCH_BACK = 'Press {back} to go back and choose {n}.'
BANNER_ADOPTED = 'Team {t}: leader is {name} (picked at the entry, not the drafted {drafted}).'


# The disc's own menu buttons (regional.MENU_ACCEPT / MENU_BACK): Cross / Triangle on the USA and European discs,
# Circle / Cross on the Japanese one. Every prompt names them through buttons().
BUTTON_CROSS, BUTTON_CIRCLE, BUTTON_TRIANGLE = 'Cross', 'Circle', 'Triangle'


def buttons(tr):
    """{accept, back}: the region's confirm and back button names in the player's language."""
    import regional
    accept, back = (BUTTON_CIRCLE, BUTTON_CROSS) if regional.JPN else (BUTTON_CROSS, BUTTON_TRIANGLE)
    return dict(accept=tr(accept), back=tr(back))


def order_text(setup, tr):
    return ', '.join(tr(ORDER_ITEM, t=team+1, p=players[0]) for team, players in setup.teams)


class SetupPanel:
    """Player-Setup style host panel (team_assignment's guest input and picture surface, its check-in hub):
    players 0..4 with a team number each, the team size, the tournament type and difficulty, CPU matches; each human
    team is shown with all its slots and who picks/controls each, then what happens next (one fighter select, then
    the tournament starts on its own)."""

    def __init__(self, owner):
        self.owner = owner
        self.active = False; self.screen = None; self.row = 0
        self.humans = 1; self.teams = [0, 1, 2, 3]; self.size = 3; self.cpu_matches = 'ask'
        self.kind = 0; self.level = 0
        self.hub = None; self.settings = {}; self.log = None; self.view = None
        self.input_ready = False; self.drawn = None; self.drawn_at = 0.0; self.dirty = False; self.opened_at = None
        self.helper = None

    # ---- model
    def setup(self):
        return Setup(self.size, {p: self.teams[p-1] for p in range(1, self.humans+1)}, self.cpu_matches,
                     self.kind, self.level)

    def rows(self):
        rows = [('players',)]
        rows += [('player', n) for n in range(1, self.humans+1)]
        rows += [('size',), ('kind',), ('level',), ('cpu',), ('continue',), ('clear',)]
        return rows

    def problem(self):
        return self.setup().problem()

    def commit(self):
        return self.setup()

    # ---- check-in (team_assignment's helper with the tournament's player count)
    def assignment_helper(self):
        import team_assignment
        if self.helper is None:
            self.helper = team_assignment.Controller()
        self.helper.view = self.view
        self.helper.teams = [0]*self.humans
        self.helper.choice = None
        self.helper.opened_at = self.opened_at
        return self.helper

    def open_hub(self):
        if self.hub is None:
            return
        try:
            self.hub.start()
            if self.humans:
                self.hub.open_setup(self.humans, False, mode=self.settings.get('controller_checkin'),
                                    keep=self.settings.get('keep_controller_checkins'))
        except RuntimeError:
            pass

    def close_hub(self, commit):
        if self.hub is None:
            return
        try:
            self.hub.close_setup(commit)
        except RuntimeError:
            pass

    def ready(self):
        return not self.humans or self.assignment_helper().ready()

    # ---- picture
    def picture(self):
        from PIL import Image, ImageDraw
        import fonts
        import team_assignment as ta
        from localization import tr as _tr
        tr = lambda text, **values: _tr(text, self.settings, **values)
        im = Image.new('RGB', (512, 448), ta.BG)
        d = ImageDraw.Draw(im)
        title = fonts.truetype('sans-bold', 23)
        font = fonts.truetype('sans-bold', 15)
        small = fonts.truetype('sans', 12)
        bold = fonts.truetype('sans-bold', 12)
        d.rectangle((0, 0, 511, 4), fill=ta.BAR)
        d.text((24, 11), tr(TITLE), font=title, fill=ta.GOLD)
        d.fontmode = '1'
        d.text((25, 40), tr(INTRO), font=small, fill=ta.TEXT)
        seats = self.assignment_helper().seats() if self.humans else []
        y = 58
        rows = self.rows()
        step = ROW_H if len(rows) <= 9 else ROW_H - 2      # four players: the summary still fits
        for index, row in enumerate(rows):
            selected = index == self.row
            d.rounded_rectangle((20, y, 491, y+step-3), radius=6, fill=ta.PANEL,
                                outline=ta.GOLD if selected else ta.EDGE, width=2)
            kind = row[0]
            if kind == 'players':
                d.text((32, y+2), tr(PLAYERS_ROW), font=font, fill=ta.WHITE)
                self._value(d, tr(CPU_ONLY) if self.humans == 0 else str(self.humans), y, font, ta.GOLD)
            elif kind == 'player':
                n = row[1]
                d.text((32, y+2), tr(PLAYER_TEAM, n=n), font=font, fill=ta.WHITE)
                team = self.teams[n-1]
                d.text((140, y+2), tr(TEAM_VALUE, t=team+1), font=font, fill=getattr(ta, TEAM_COLORS[team]))
                kind_, text, _ = seats[n-1] if n-1 < len(seats) else ('default', '', None)
                color = {'empty': ta.GOLD, 'default': ta.DIM, 'pad': ta.GREEN, 'lost': ta.RED}.get(kind_, ta.DIM)
                d.ellipse((292, y+7, 299, y+14), fill=color)
                label = text
                while label and d.textlength(label, font=small) > 180:
                    label = label[:-2] + '…'
                d.text((304, y+4), label, font=small, fill=ta.TEXT if kind_ == 'pad' else color)
            elif kind == 'size':
                d.text((32, y+2), tr(TEAM_SIZE), font=font, fill=ta.WHITE)
                self._value(d, str(self.size), y, font, ta.GOLD)
            elif kind == 'kind':
                d.text((32, y+2), tr(TYPE_ROW), font=font, fill=ta.WHITE)
                self._value(d, tr(type_names()[self.kind]), y, font, ta.GOLD)
            elif kind == 'level':
                d.text((32, y+2), tr(LEVEL_ROW), font=font, fill=ta.WHITE)
                self._value(d, tr(DIFFICULTIES[self.level]), y, font, ta.GOLD)
            elif kind == 'cpu':
                d.text((32, y+2), tr(CPU_MATCHES_ROW), font=font, fill=ta.WHITE)
                self._value(d, tr(CPU_MATCH_VALUES[self.cpu_matches]), y, font, ta.GOLD)
            else:
                label = CONTINUE_LABEL if kind == 'continue' else CLEAR_LABEL
                ok = kind != 'continue' or (self.ready() and self.problem() is None)
                d.text((32, y+2), tr(label), font=font, fill=ta.WHITE if ok else ta.DIM)
            y += step
        # every human team with all its slots and who picks / controls each
        setup = self.setup()
        y += 2
        for k, (team, players) in enumerate(setup.teams):
            color = getattr(ta, TEAM_COLORS[team])
            d.text((25, y), tr(TEAM_LINE, t=team+1), font=bold, fill=color)
            parts = []
            short = len(setup.teams) >= 3        # three or four teams: one line each, so the summary still fits
            for slot, owner in enumerate(setup.owners(k)):
                if slot == 0:
                    parts.append(tr(LEADER_SLOT_SHORT, p=owner))
                elif owner:
                    parts.append(tr(PLAYER_SLOT_SHORT if short else PLAYER_SLOT, k=slot+1, p=owner))
                else:
                    parts.append(tr(CPU_SLOT_SHORT if short else CPU_SLOT, k=slot+1))
            y = self._wrap(d, ' · '.join(parts), y, small, ta.TEXT, x=90, width=397, lines=1 if short else 2)
        problem = setup.problem()
        if problem is not None:
            text = tr(problem[0], **problem[1])
        elif setup.cpu_only:
            text = tr(CPU_NOTE)
        else:
            n = len(setup.teams)
            template = SUMMARY_ONE if n == 1 else SUMMARY_TWO if n == 2 else SUMMARY_MANY
            text = tr(template, n=n, t=setup.teams[0][0]+1, u=setup.teams[-1][0]+1)
        top = max(y+4, 330) if y+4+15*3 <= 400 else y+4
        self._wrap(d, text, top, small, ta.RED if problem else ta.GOLD, lines=max(1, min(4, (400-top)//15)))
        self._columns(d, tr(FOOTER_P1), 404, small, ta.TEXT)
        self._columns(d, tr(FOOTER_ALL, **buttons(tr)), 424, small, ta.GOLD)
        return im.quantize(palette=ta.palette(), dither=Image.Dither.NONE).convert('RGB')

    @staticmethod
    def _value(d, text, y, font, color):
        """'<  value  >' right-aligned in the row (long type names and Spanish values fit)."""
        value = f'<  {text}  >'
        d.text((max(150, 484 - int(d.textlength(value, font=font))), y+2), value, font=font, fill=color)

    @staticmethod
    def _wrap(d, text, y, font, color, lines=2, x=25, width=462):
        """Up to `lines` lines inside the text column; returns the next y."""
        row, count = '', 0
        for word in text.split():
            trial = (row + ' ' + word).strip()
            if row and d.textlength(trial, font=font) > width:
                d.text((x, y), row, font=font, fill=color)
                y += 15; count += 1; row = word
                if count >= lines:
                    return y
            else:
                row = trial
        if row:
            d.text((x, y), row, font=font, fill=color)
            y += 15
        return y

    @staticmethod
    def _columns(d, text, y, font, color):
        parts = [part.strip() for part in text.split('·')]
        widths = [d.textlength(part, font=font) for part in parts]
        while sum(widths) + 8*(len(parts)-1) > 462 and len(parts) > 1:
            parts, widths = parts[:-1], widths[:-1]
        gap = max(8, (462-sum(widths))/max(1, len(parts)-1)) if len(parts) > 1 else 0
        x = 25
        for part, width in zip(parts, widths):
            d.text((round(x), y), part, font=font, fill=color)
            x += width + gap

    # ---- the watcher's tick (through native_mode_menu.Controller)
    def tick(self, p):
        import team_assignment as ta
        import time
        wanted = (p.read_u32(ta.MENU) == ta.MAGIC and p.read_u32(ta.MENU+ta.STATE) == 1 and
                  p.read_u32(ta.MENU+ta.CHOICE) == CHOICE)
        if not wanted:
            if self.active:
                self.close(p)
            return False
        if self.owner.route_ready():
            # The draft is done (or not needed): Continue was pressed before it; go on to Dragon World Tour.
            p.write_u32(ta.MENU+ta.STATE, 2)
            return True
        if not self.active:
            from guest_loading_screen import GuestLoadingScreen
            self.screen = GuestLoadingScreen()
            self.active = True; self.row = 0
            self.input_ready = False; self.drawn = None; self.dirty = True; self.opened_at = time.monotonic()
            self.open_hub()
        p.write_u32(ta.MENU+ta.LEASE, ta.HOST_LEASE)
        p.write_u32(ta.MENU+16, ta.HOST_LEASE)
        now = time.monotonic()
        if self.hub is not None:
            try:
                self.view = self.hub.snapshot()
            except RuntimeError:
                self.view = None
        buttons = p.read_u32(ta.MENU+ta.BUTTONS)
        if buttons:
            p.write_u32(ta.MENU+ta.BUTTONS, 0)
        import regional
        if buttons & regional.RAW_BACK:
            p.write_u32(ta.MENU+ta.STATE, 0)
            p.write_u32(ta.MENU+ta.VALID, 0)
            self.close(p)
            return True
        if not self.screen.presented(p):
            buttons = 0
        elif not self.input_ready:
            import mode_menu
            self.input_ready = p.read_u32(mode_menu.PAD+0x150) == 0
            buttons = 0
        rows = self.rows()
        self.row = min(self.row, len(rows)-1)
        if buttons & 0x50:
            self.row = (self.row + (1 if buttons & 0x40 else -1)) % len(rows)
            self.dirty = True
        step = 1 if buttons & 0x20 else -1 if buttons & 0x80 else 0
        row = rows[self.row]
        if step:
            self.change(row, step)
            self.dirty = True
        if buttons & regional.RAW_ACCEPT:
            if row[0] == 'clear':
                if self.hub is not None:
                    try:
                        self.hub.clear_checkins()
                    except RuntimeError:
                        pass
                self.dirty = True
            elif self.ready() and self.problem() is None:
                self.owner.begin(self.commit())
                self.close(p, commit=True)
                # Back to the Modded Modes page: the controller runs the draft (if any), then Dragon World Tour.
                p.write_u32(ta.MENU+ta.STATE, 0)
                p.write_u32(ta.MENU+ta.VALID, 0)
                return True
        state = (self.humans, tuple(self.teams), self.size, self.kind, self.level, self.cpu_matches, self.row,
                 tuple(self.assignment_helper().seats()) if self.humans else (), self.ready())
        if state != self.drawn:
            self.dirty = True
        if self.dirty and now - self.drawn_at >= 0.25:
            self.screen.show_picture(self.picture(), surface='menu', client=p)
            self.drawn, self.drawn_at, self.dirty = state, now, False
        else:
            self.screen.sync(client=p)
        return True

    def change(self, row, step):
        kind = row[0]
        if kind == 'players':
            self.humans = (self.humans + step) % 5
            self.close_hub(False)
            self.open_hub()
        elif kind == 'player':
            n = row[1]
            self.teams[n-1] = (self.teams[n-1] + step) % 4
        elif kind == 'size':
            self.size = min(TEAM_MAX, max(1, self.size + step))
        elif kind == 'kind':
            self.kind = (self.kind + step) % len(TYPES)
        elif kind == 'level':
            self.level = (self.level + step) % len(DIFFICULTIES)
        elif kind == 'cpu':
            i = CPU_MATCH_POLICIES.index(self.cpu_matches)
            self.cpu_matches = CPU_MATCH_POLICIES[(i + step) % len(CPU_MATCH_POLICIES)]

    def close(self, p, commit=False):
        import mode_menu
        import team_assignment as ta
        p.write_u32(ta.MENU+28, p.read_u32(mode_menu.PAD+0x150))
        if self.screen:
            self.screen.hide(client=p)
        if self.active:
            self.close_hub(commit)
        self.screen = None
        self.active = False

    def shutdown(self):
        if self.active:
            self.close_hub(False)
        self.active = False


# ---------------------------------------------------------------- host: native text (announcer, VS / result form line)
# The game draws these strings itself, every frame, from a DBT table pointer (count, offsets, UTF-16 strings with a
# BOM). A copy of the native table with our lines goes into the reservation and the pointer is pointed at it; the
# native objects are freed with their scene, and the pointer is written again whenever a new scene object shows.
ANNOUNCE = BASE + 0x10000            # scene 34 announcer table copy (0x8000)
FORMS = (BASE + 0x18000, BASE + 0x1C000)   # scene 35 form-line table copies, left / right side (0x4000 each)
TEXT_SLOTS = {ANNOUNCE: 0x8000, FORMS[0]: 0x4000, FORMS[1]: 0x4000}
ANNOUNCER_WINDOW = A(0x2FF0D8)       # the message window; +0x48 = its text table
ENTRY_TEXTS, ENTRY_LINE = 0x1C, 0x1E4   # entry object: its 246-string table, the line shown now
OPENING_LINES = (34, 122, 77, 159, 202)   # "Those who wish to enter, this way please!" by tournament type
OBJ_LINE = 0x2E0                     # runtime object: the announcer line the bracket shows
ROW_PLAYED, ROW_LAST = 1, 2          # bracket row flags: played; last row of its round
VS_SCROLL = 400                      # bracket layout scroll x at/after which the VS / result screen covers it
BRACKET_MOVING = 0x400               # runtime object +0x2DC while the bracket zooms to / from the VS screen
OBJ_FORMS, OBJ_FORM_TEXT, OBJ_VS_FLAGS = 0x28, 0x1F28, 0x2DC   # forms table; per side descriptors (+0x8C), table at +4
BOM = '﻿'.encode('utf-16-le')


def read_dbt(p, table, limit=0x10000):
    """[raw UTF-16 bytes] of a native DBT table (bounded reads; None when it does not look like one)."""
    count = p.read_u32(table)
    if not 1 <= count <= 1024:
        return None
    offsets = struct.unpack(f'<{count}I', p.read(table+4, 4*count))
    if not all(4+4*count <= o < limit for o in offsets):
        return None
    end = min(limit, max(offsets) + 0x400)
    blob = p.read(table, end)
    out = []
    for o in offsets:
        k = o
        while k+1 < len(blob) and blob[k:k+2] != b'\0\0':
            k += 2
        out.append(blob[o:k])
    return out


def build_dbt(strings):
    out = bytearray(struct.pack('<I', len(strings)) + bytes(4*len(strings)))
    for i, raw in enumerate(strings):
        while len(out) % 16:
            out += b'\0'
        struct.pack_into('<I', out, 4+4*i, len(out))
        out += raw + b'\0\0'
    while len(out) % 16:
        out += b'\0'
    return bytes(out)


def native_line(text):
    import native_menu_assets
    return BOM + native_menu_assets.native_text(text.replace('·', '-')).encode('utf-16-le')


class NativeText:
    """Our lines in the game's own announcer (scene 34) and VS / result form line (scene 35)."""

    def __init__(self):
        self.base = {}          # native table address -> its strings (read once per scene object)
        self.written = {}       # destination -> (pointer owner, text key)

    def _table(self, p, address):
        strings = self.base.get(address)
        if strings is None:
            strings = read_dbt(p, address)
            if strings is None:
                return None
            self.base = {address: strings} | {k: v for k, v in self.base.items() if k != address}
            if len(self.base) > 4:
                self.base.pop(next(iter(self.base)))
        return list(strings)

    def _publish(self, p, destination, strings, holder, key):
        blob = build_dbt(strings)
        if len(blob) > TEXT_SLOTS[destination]:
            return False
        if self.written.get(destination) != (holder, key) or p.read_u32(holder) != destination:
            p.write(destination, blob)
            p.write_u32(holder, destination)
            self.written[destination] = (holder, key)
        return True

    def announce(self, p, text):
        """The entry announcer's opening line becomes `text` (two lines with \\n)."""
        entry = _pointer(p, ENTRY_OBJECT)
        window = _pointer(p, ANNOUNCER_WINDOW)
        if entry is None or window is None:
            return False
        native = _pointer(p, entry+ENTRY_TEXTS)
        if native is None:
            return False
        strings = self._table(p, native)
        if strings is None:
            return False
        line = native_line(text)
        for i in OPENING_LINES:
            if i < len(strings):
                strings[i] = line
        return self._publish(p, ANNOUNCE, strings, window+0x48, (native, text))

    def bracket_line(self, p, obj, text):
        """The bracket's announcer line (window table entry obj+0x2E0) becomes `text`; restore_line undoes it."""
        window = _pointer(p, ANNOUNCER_WINDOW)
        if window is None:
            return False
        index = p.read_u32(obj+OBJ_LINE)
        current = p.read_u32(window+0x48)
        native = self.line_native if current == ANNOUNCE and getattr(self, 'line_native', None) else current
        if not 0x100000 <= native < 0x2000000 or native == ANNOUNCE:
            return False
        strings = self._table(p, native)
        if strings is None or not 0 <= index < len(strings):
            return False
        strings[index] = native_line(text)
        self.line_native, self.line_window = native, window
        return self._publish(p, ANNOUNCE, strings, window+0x48, ('bracket', native, index, text))

    def restore_line(self, p):
        native, window = getattr(self, 'line_native', None), getattr(self, 'line_window', None)
        if native and window and p.read_u32(window+0x48) == ANNOUNCE:
            p.write_u32(window+0x48, native)
        self.line_native = self.line_window = None
        self.written.pop(ANNOUNCE, None)

    def vs_lines(self, p, obj, texts):
        """VS / result screen: the form line under each side's name becomes texts[side] (None keeps the native)."""
        native = _pointer(p, obj+OBJ_FORMS)
        if native is None:
            return False
        row = p.read_u32(obj+OBJ_ROW)
        if row >= 16:
            return False
        a, b = struct.unpack('<2H', p.read(obj+OBJ_ROWS+16*row+2, 4))
        done = False
        for side, entrant in enumerate((a, b)):
            text = texts.get(entrant)
            holder = obj+OBJ_FORM_TEXT+0x8C*side+4
            if text is None or entrant >= ENTRANTS:
                continue
            current = p.read_u32(holder)
            if current not in (native, FORMS[side]):
                continue                     # not the descriptor this code knows
            flags, = struct.unpack('<H', p.read(obj+OBJ_ENTRANTS+entrant*ENTRANT_BYTES, 2))
            character = p.read_u32(obj+OBJ_ENTRANTS+entrant*ENTRANT_BYTES+4)
            index = form_index(flags, character)
            strings = self._table(p, native)
            if strings is None or index >= len(strings):
                continue
            strings[index] = native_line(text)
            done = self._publish(p, FORMS[side], strings, holder, (native, row, entrant, text)) or done
        return done


def form_index(flags, character):
    """The VS form-line entry of an entrant (USA 0x367E00): flag 0x10 -> 0xA3; on the USA and Japanese discs
    Piccolo (0x16/0x17) -> 0xA7 and Supreme Kai / Kibito (0x3A/0x3B) -> 0xA5 as well (the European disc keeps the
    character id for those)."""
    import regional
    if flags & 0x10:
        return 0xA3
    if regional.PAL:
        return character
    return 0xA7 if character in (0x16, 0x17) else 0xA5 if character in (0x3A, 0x3B) else character


def bracket_records(p, obj, cache, kind='chara'):
    """{entrant: element record address} of the bracket portraits (mc_tournament_chara%d; kind='frame_': their
    frames, mc_tournament_frame_%d) in the bracket layout's element block (runtime object +0x54..+0x58), cached per
    layout block once all 17 are there. The runtime object keeps its address across a return from a battle while the
    bracket builds a new layout block, so the block's bounds are part of the key."""
    start, end = struct.unpack('<2I', p.read(obj+0x54, 8))
    key = (obj, start, end)
    if cache.get(('layout', kind)) == key:
        return cache[('records', kind)]
    records = {}
    if 0x100000 <= start < end < 0x2000000 and end - start <= 0x10000:
        blob = p.read(start, end-start)
        for i in range(ENTRANTS):
            name = f'mc_tournament_{kind}{i}'.encode() + bytes(1)
            at = blob.find(name)
            if at >= 0:
                records[i] = start + at
    if len(records) == ENTRANTS:            # the layout is complete (never cache one read while it is built)
        cache[('layout', kind)], cache[('records', kind)] = key, records
    return records


FRAME_CELL, FRAME_FLAGS = 0x48, 0x6C    # portrait frame element: cell (5 = the red human frame with its 1P/2P tag)
FRAME_HUMAN, FRAME_TAG = 5, 0x40        # and the flag that shows the tag (both set when the bracket builds its layout)


def unmark_frames(p, obj, entrants, marked, cache):
    """The watch marks borrow an entrant's human bit, and the bracket styles every human entrant's portrait frame
    (red, '1P') when it builds its layout after a return: give each CPU entrant (and every marked one) its CPU frame
    back. Returns the entrants changed."""
    changed = []
    for entrant, record in bracket_records(p, obj, cache, 'frame_').items():
        if entrants[entrant].human and entrant not in marked:
            continue
        if p.read_u32(record+FRAME_CELL) == FRAME_HUMAN:
            p.write_u32(record+FRAME_CELL, 0)
            p.write_u32(record+FRAME_FLAGS, p.read_u32(record+FRAME_FLAGS) & ~FRAME_TAG)
            changed.append(entrant)
    return changed


# ---------------------------------------------------------------- host: the watcher's tournament controller
CHOICE = 22               # Modded Modes commit value (native_mode_menu.SELECTIONS index 21 + 1)
STATE_FILE = 'current.json'
PICTURE_REFRESH = 0.5     # seconds between lease refreshes of an unchanged picture
ROUTE_SECONDS = 30.0      # an armed route may stay at the main menu this long (the page waits for its checkpoint)
VEIL_SECONDS, LOGO_SECONDS = 60.0, 6.0    # the transition cover at most; scene 35 without a logo before it comes down
AUTO_GRACE = 3.0          # seconds a tournament menu may stay up while the stand-ins should have answered it
AUTO_LIMIT = 20.0         # seconds in a tournament menu scene with the auto entry published, at most


class Controller:
    """The watcher's side of a Tag Team Tournament: setup panel, roster draft, arming, team plan, guidance over the
    native screens, per-match receipts and controller order, and the native result of each team match."""

    def __init__(self):
        self.panel = SetupPanel(self)
        self.setup = None; self.armed = False; self.pending = False; self.plan = None; self.plan_key = None
        self.routed_at = None; self.cleared = False
        self.match = None; self.winner = None; self.history = []
        self.rosters = []; self.draft = None; self.want_main = False
        self.cpu_settings = []
        self.veil = None                 # the watcher's cover over a transition: dict(kind 'start' | 'pass', since)
        self.picture = None; self.picture_at = 0.0; self.turn = None; self.block = False
        self.hub = None; self.question = None
        self.routing = False; self.bracket_seen = False; self.pool = None; self.locked = frozenset()
        self.auto_since = self.auto_scene = None
        self.text = NativeText(); self.bracket_cache = {}; self.bracket_drawn = None; self.bracket_packet = b''
        self.log = lambda text: print(text, flush=True)
        self.state_dir = None
        self.settings = {}

    # ---- text in the player's language
    def tr(self, text, **values):
        from localization import tr
        return tr(text, self.settings, **values)

    # ---- the setup panel and the draft
    def menu_tick(self, p):
        """The panel is a Modded Modes modal; native_mode_menu ticks it before Player Setup."""
        if self.draft is not None:
            self.draft_tick(p)
        return self.panel.tick(p)

    @property
    def drafting(self):
        return self.draft is not None

    def begin(self, setup):
        """Continue on the panel: draft the human rosters (if any), then route to Dragon World Tour."""
        import time
        self.setup = setup
        self.rosters = [[] for _ in setup.teams or [None]]       # CPU only: the followed team
        self.cpu_settings = [[] for _ in self.rosters]
        self.history = []
        passes = draft_passes(setup)
        self.draft = dict(passes=passes, index=0, stage='commit' if passes else 'route', since=time.monotonic())
        self.log(f'Tag Team Tournament: {self.describe_setup()}; '
                 + (f'{len(passes)} roster pick(s) first.' if passes else 'no roster picks needed.'))

    def route_ready(self):
        return self.draft is not None and self.draft['stage'] == 'routed'

    def set_order(self, order):
        hub = self.hub
        if hub is None:
            return
        try:
            hub.set_order(order)
        except (RuntimeError, AttributeError):
            pass

    def draft_tick(self, p):
        """One menu poll of the draft: commit a pass like Player Setup would, watch its Team Select, read the
        picks once both sides are Done, then ask the watcher for the clean main menu; finally route the Modded
        Modes page to Dragon World Tour (choice 22)."""
        import time
        import team_assignment as ta
        import native_mode_menu as nm
        draft = self.draft
        manager, scene = self.scene(p)
        stage = draft['stage']
        pager = p.read_u32(nm.CONTROL) == nm.MAGIC and p.read_u32(nm.CONTROL+4) == 2
        if stage in ('commit', 'route'):
            if scene != MAIN_MENU or not pager or self.want_main:
                return
            if p.read_u32(ta.MENU+ta.STATE) != 0 or p.read_u32(nm.CONTROL+nm.PENDING_CHOICE):
                return
            if stage == 'route':
                p.write_u32(DRAFT, 0)
                # Armed now, before Dragon World Tour opens: the stand-ins answer its type menu and registration
                # from the setup, and scene 35 must find the post-pass and the CPU-match helper in place.
                self.arm(p, auto=True)
                p.write_u32(ta.MENU+ta.VALID, 0)
                p.write_u32(ta.MENU+ta.CHOICE, CHOICE)
                p.write_u32(ta.MENU+ta.STATE, 2)
                draft['stage'] = 'routed'
                return
            teams = draft['passes'][draft['index']]
            choice, humans, seats, valid, owners = pass_receipt(self.setup, teams)
            # The slot owners are published in the Team Select itself (never in a main-menu checkpoint).
            p.write_u32(DRAFT, 0)
            draft['owners'] = owners
            p.write(ta.MENU+ta.SEATS, struct.pack('<4I', *seats))
            p.write_u32(ta.MENU+ta.HUMANS, humans)
            p.write_u32(ta.MENU+ta.VALID, valid)
            p.write_u32(ta.MENU+ta.CHOICE, choice)
            p.write_u32(ta.MENU+ta.STATE, 2)
            draft.update(stage='select', since=time.monotonic(), teams=teams, completed=False)
            self.log(f"Tag Team Tournament: roster pick {draft['index']+1} of {len(draft['passes'])}: "
                     + (', '.join(f'Team {self.setup.teams[k][0]+1}' for k in teams) if self.setup.teams
                        else 'the CPU team to follow') + '.')
            return
        if stage == 'select':
            if scene != SELECT_SCENE and scene is not None and scene != 38:
                if scene == MAIN_MENU and time.monotonic()-draft['since'] > 8.0:
                    # Backed out of the Team Select: the tournament setup is abandoned.
                    self.cancel(p, 'the roster pick was left')
                return
            if scene == SELECT_SCENE and p.read_u32(DRAFT) != DRAFT_MAGIC:
                p.write(DRAFT+4, bytes(draft['owners'])+bytes((self.setup.size, 0, 0, 0)))   # +16: team size
                veil = veil_packet()
                p.write(VEIL, veil)
                p.write_u32(DRAFT+DRAFT_VEIL, len(veil))
                p.write_u32(DRAFT, DRAFT_MAGIC)
            state = selection_state(p)
            if state is None:
                return
            obj, sides_, stage_open = state
            teams = draft['teams']
            self.show(p, self.draft_banner(teams), scene=SELECT_SCENE)
            if len(teams) == 1 and not draft['completed'] and complete_unused_side(p, obj, sides_):
                draft['completed'] = True
            if not stage_open or any(s[1] != SEL_DONE for s in sides_):
                return
            for side, k in enumerate(teams):
                picks = read_selection(p, side)
                label = f'Team {self.setup.teams[k][0]+1}' if self.setup.teams else 'The followed CPU team'
                if len(picks) < self.setup.size:
                    self.log(f'Tag Team Tournament: {label} picked {len(picks)} of {self.setup.size} fighters; '
                             'the rest are random.')
                self.rosters[k] = picks[:self.setup.size]
                import cpu_difficulty_select as cpu_select
                self.cpu_settings[k] = [p.read_u32(cpu_select.LEVELS+4*(2*m+side)) for m in range(self.setup.size)]
                self.log(f"Tag Team Tournament: {label} roster: "
                         + ', '.join(f'{character_name(c)} (costume {k_+1})' for c, k_, _ in self.rosters[k]))
            # Nothing confirms a stage (pad_code withdraws the accept while DRAFT is published) until the watcher
            # restores the main menu.
            self.show(p, b'')
            draft['index'] += 1
            draft['stage'] = 'commit' if draft['index'] < len(draft['passes']) else 'route'
            self.want_main = True
            # The watcher covers the rest (autopilot.tournament_veil_show): the main menu loaded under the cover, the
            # route and the tournament's own menus, until the tournament's opening logo starts (or the next pick's
            # Team Select is up).
            self.veil = dict(kind='pass' if draft['stage'] == 'commit' else 'start', since=time.monotonic())
            self.save_state()
            return

    def draft_banner(self, teams):
        setup = self.setup
        if setup.cpu_only:
            return banner([self.tr(BANNER_DRAFT_CPU, n=setup.size)], y=422)
        if len(teams) == 2:
            t, u = (setup.teams[k][0]+1 for k in teams)
            return banner([self.tr(BANNER_DRAFT_SOLO_TWO if setup.size == 1 else BANNER_DRAFT_TWO,
                                   t=t, u=u, n=setup.size)], y=422)
        team, players = setup.teams[teams[0]]
        return banner([self.tr(BANNER_DRAFT_SOLO if setup.size == 1 else BANNER_DRAFT,
                               t=team+1, p=players[0], n=setup.size)], y=422)

    def cover_teams(self):
        """Up to two drafted rosters for the loading cover's cards (guest_loading_screen teams)."""
        teams = [r for r in self.rosters if r][:2]
        return [dict(side=i, fighters=[c for c, _, _ in roster]) for i, roster in enumerate(teams)]

    def veil_tick(self, p):
        """While the watcher's cover is up: True once it may come down - the next pick's Team Select is up, or the
        tournament's own opening (scene 35's logo, then World Tournament Open and the bracket) starts, or the
        tournament was left. VEIL_SECONDS at most."""
        import time
        veil = self.veil
        if veil is None or (self.draft is None and not self.armed and not self.pending):
            return True
        if time.monotonic() - veil['since'] > VEIL_SECONDS:
            self.log('Tag Team Tournament: the cover came down after its time limit.')
            return True
        _, scene = self.scene(p)
        if veil['kind'] == 'pass':
            return (scene == SELECT_SCENE and self.draft is not None and self.draft['stage'] == 'select'
                    and selection_state(p) is not None)
        if scene != BRACKET_SCENE:
            return False
        veil.setdefault('bracket', time.monotonic())
        # The logo (its jingle starting: OBJ_WAIT bit LOGO_WAIT) or any later step of the opening; without either
        # within LOGO_SECONDS of scene 35 (another overlay), the cover comes down anyway.
        return opening_started(p) or time.monotonic() - veil['bracket'] > LOGO_SECONDS

    def main_restored(self, p):
        """The watcher loaded the clean main menu for the draft (want_main): the Modded Modes root page opens."""
        self.want_main = False
        if p is not None:
            p.write_u32(DRAFT, 0)

    def cancel(self, p, why):
        if p is not None:
            p.write_u32(DRAFT, 0)
        self.draft = None
        self.disarm(p, why)

    def select(self):
        """The Modded Modes page committed Dragon World Tour. The draft's route armed the tournament already (with
        the stand-ins); a setup without that arms once the game shows a tournament scene (never at the main menu,
        whose clean checkpoint must not keep an armed tournament)."""
        import time
        if self.setup is None:
            raise ValueError('Tag Team Tournament has no setup')
        if self.armed:
            return
        self.pending = True
        self.routed_at = time.monotonic()

    def arm(self, p, auto=False):
        """Start a tournament with the committed setup: CONTROL (magic last), the accepted battle mode, the locked
        ids and spares for the entrant post-pass and, with auto, the one-shot auto entry (magic last) for the
        stand-ins of the type menu and the registration. auto arms at the main menu, right before the Modded Modes
        page opens Dragon World Tour (ROUTE_SECONDS to leave it)."""
        import native_preparation
        import time
        if self.setup is None:
            raise ValueError('Tag Team Tournament has no setup')
        p.write_u32(CONTROL, 0)
        p.write_u32(AUTO, 0)
        p.write(TABLE, bytes(ENTRANTS*ENTRY))
        p.write(CONTROL+4, struct.pack('<12I', VERSION, *([0]*11)))
        p.write(CONTROL+F['ready'], bytes(0x20))
        p.write_u32(CONTROL+F['swapped'], 0)
        self.publish_locked(p)
        p.write_u32(CONTROL, MAGIC)
        p.write_u32(native_preparation.ACCEPTED_MODE, TOURNAMENT_MODE)
        self.arm_watch(p)
        if auto:
            record = self.auto_record()
            p.write(AUTO+4, record[4:])
            p.write_u32(AUTO, AUTO_MAGIC)
        self.armed = True; self.pending = False; self.plan = None; self.plan_key = None
        self.routed_at = time.monotonic(); self.routing = auto; self.bracket_seen = False
        self.match = None; self.winner = None
        self.turn = None; self.block = False; self.picture = None
        if not auto:
            self.draft = None        # (a route keeps its 'routed' draft until a tournament scene shows)
        self.log(f'Tag Team Tournament armed: {self.describe_setup()}'
                 + ('; Dragon World Tour opens on the bracket.' if auto else '.'))
        self.save_state()

    def auto_record(self):
        """AUTO bytes: the setup's type, difficulty and human entrants, and each registered leader (the drafted slot
        1 of human team k, in team order; CPU only: the followed team's)."""
        setup = self.setup
        count = setup.entry_count()
        out = bytearray(AUTO_ENTRY + AUTO_MAX*AUTO_STRIDE)
        struct.pack_into('<4I', out, 0, AUTO_MAGIC, setup.kind, setup.level, count)
        for k in range(count):
            roster = self.rosters[k] if k < len(self.rosters) else []
            character, costume, items = roster[0] if roster else member(self.random_leader(k))
            if character >= 256 or character in self.locked:
                raise ValueError(f'Tag Team Tournament: fighter {character} cannot be registered')
            flags = HUMAN | (CUSTOM if any(items) else 0)
            at = AUTO_ENTRY + k*AUTO_STRIDE
            struct.pack_into('<3I', out, at, character, costume, flags)
            out[at+16:at+32] = items
        return bytes(out)

    def random_leader(self, k):
        """A leader for a team whose draft picked nobody (never seen live: the Team Select needs one pick)."""
        pool = self.pool or roster_pool(exclude=self.locked)
        return random.Random(f'leader|{k}|{self.setup.size}').choice(pool)

    def publish_locked(self, p):
        """LOCKED (lock-icon and unnamed select-screen ids) and SPARES (playable fighters, never giants) for the
        guest post-pass, and the teammate pool, from the chosen disc's data and the running game's pick rule."""
        locked, excluded = unplayable(p)
        self.locked = locked
        try:
            self.pool = roster_pool(exclude=excluded)
        except ValueError:
            self.pool = None
        bitmap = bytearray(32)
        for character in locked:
            if 0 <= character < 256:
                bitmap[character >> 3] |= 1 << (character & 7)
        spares = [c for c in (self.pool or []) if 0 <= c < 256][:SPARE_MAX] if locked else []
        p.write(LOCKED, bytes(bitmap))
        p.write(SPARES+4, struct.pack(f'<{len(spares)}H', *spares) + bytes(2*(SPARE_MAX-len(spares))))
        p.write_u32(SPARES, len(spares))
        if locked:
            self.log(f'Tag Team Tournament: {len(locked)} locked select-screen slots never enter '
                     f'({", ".join(map(str, sorted(locked)))}); {len(spares)} spares.')

    def arm_watch(self, p):
        """CPU-vs-CPU rows: ask / always watch arm the guest helper (watch_code); always skip keeps the native."""
        on = self.setup is not None and self.setup.cpu_matches != 'skip'
        p.write(CONTROL+F['watch'], bytes(0x2C))
        p.write_u32(CONTROL+F['watch'], int(on))
        if on:      # a CPU row asked before the host's first bracket tick waits for it (not an instant Skip)
            p.write_u32(CONTROL+F['wlease'], WATCH_LEASE)
        self.question = None

    @staticmethod
    def clear(p):
        """The guest side of a tournament off: CONTROL (the pnach then writes the native words back once) and the
        preparation gate's accepted battle mode back to Duel."""
        import native_preparation
        if p.read_u32(CONTROL) != 0:
            p.write_u32(CONTROL, 0)
        for address in (CONTROL+F['draw_len'], CONTROL+F['block'], DRAFT, AUTO):
            if p.read_u32(address):
                p.write_u32(address, 0)
        if p.read_u32(native_preparation.ACCEPTED_MODE) != 0:
            p.write_u32(native_preparation.ACCEPTED_MODE, 0)

    def disarm(self, p, why=''):
        if p is not None:
            self.clear(p)
        if self.armed or self.pending or self.draft is not None:
            self.log(f'Tag Team Tournament ended{": " + why if why else ""}.')
        self.armed = False; self.pending = False; self.plan = None; self.plan_key = None; self.match = None
        self.winner = None; self.draft = None; self.turn = None; self.block = False; self.picture = None
        self.routing = False; self.bracket_seen = False; self.veil = None
        self.set_order(None)
        self.forget_state()

    def describe_setup(self):
        s = self.setup
        if s is None:
            return 'no setup'
        teams = ', '.join(f'Team {t+1} ' + '+'.join(f'P{n}' for n in players) for t, players in s.teams) or 'CPU only'
        return (f'teams of {s.size}, human teams {teams}, {type_names()[s.kind]}, '
                f'difficulty {s.level+1}, CPU matches {s.cpu_matches}')

    @staticmethod
    def scene(p):
        manager = p.read_u32(SCENE_MANAGER)
        return (manager, p.read_u32(manager+0x18)) if 0x100000 <= manager < 0x1FFF000 else (manager, None)

    # ---- pictures over the native screens
    def show(self, p, packet, scene=0):
        """Publish (or keep refreshing) the picture the guest draws; b'' hides it."""
        import time
        now = time.monotonic()
        if packet == self.picture and packet and now-self.picture_at < PICTURE_REFRESH:
            return
        if packet == self.picture and packet:
            p.write_u32(CONTROL+F['draw_lease'], 180)
        else:
            publish_picture(p, packet, scene)
        self.picture, self.picture_at = packet, now

    # ---- saved state: a watcher restart re-arms instead of falling back to leaders only
    def save_state(self):
        if self.state_dir is None or self.setup is None:
            return
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            data = dict(setup=self.setup.to_json(), rosters=[[[c, k, i.hex()] for c, k, i in r] for r in self.rosters],
                        armed=self.armed, plan=self.plan.to_json() if self.plan else None,
                        plan_key=list(self.plan_key[:2]) + [list(self.plan_key[2])] if self.plan_key else None,
                        history=self.history, cpu_settings=self.cpu_settings)
            (self.state_dir/STATE_FILE).write_text(json.dumps(data, indent=1), encoding='utf-8')
        except OSError:
            pass

    def forget_state(self):
        if self.state_dir is None:
            return
        try:
            (self.state_dir/STATE_FILE).unlink(missing_ok=True)
        except OSError:
            pass

    def adopt(self, p):
        """A new watcher on a game with an armed tournament: re-arm from the saved state when it describes this very
        tournament (setup and, once the bracket exists, the same entrants); else clear the guest side."""
        import native_preparation
        self.cleared = True
        if p.read_u32(CONTROL) != MAGIC:
            self.clear(p)
            return False
        try:
            data = json.loads((self.state_dir/STATE_FILE).read_text(encoding='utf-8')) if self.state_dir else None
        except (OSError, ValueError):
            data = None
        _, scene = self.scene(p)
        if not data or not data.get('armed') or (scene is not None and scene == MAIN_MENU):
            self.clear(p)
            return False
        try:
            self.setup = Setup.from_json(data['setup'])
            self.rosters = [[member(c, k, bytes.fromhex(i)) for c, k, i in r] for r in data.get('rosters', [])]
            self.cpu_settings = data.get('cpu_settings') or []
            self.history = list(data.get('history') or [])
            if data.get('plan') and data.get('plan_key'):
                self.plan = Plan.from_json(data['plan'])
                kt, kd, chars = data['plan_key']
                self.plan_key = (kt, kd, tuple(chars))
                # the guest table must still describe that plan
                if p.read(TABLE, ENTRANTS*ENTRY) != self.plan.table():
                    p.write(TABLE, self.plan.table())
                import cpu_difficulty_select as cpu_select
                p.write(cpu_select.TOUR_LEVELS,self.plan.level_table())
        except (KeyError, TypeError, ValueError) as error:
            self.log(f'Tag Team Tournament: the saved state could not be used ({error}); ending it.')
            self.clear(p)
            return False
        self.armed = True; self.pending = False; self.draft = None; self.routing = False
        self.bracket_seen = scene == BRACKET_SCENE or bool(self.plan)
        if p.read_u32(native_preparation.ACCEPTED_MODE) != TOURNAMENT_MODE:
            p.write_u32(native_preparation.ACCEPTED_MODE, TOURNAMENT_MODE)
        self.publish_locked(p)
        self.log(f'Tag Team Tournament re-armed from its saved state: {self.describe_setup()}.')
        return True

    # ---- the watcher at the menus (loop 0)
    def tick(self, p):
        """Arm on Dragon World Tour, follow the tournament scenes, check the entry, draw the guidance and publish
        the team table; the main menu after them ends the tournament."""
        import time
        import native_preparation
        manager, scene = self.scene(p)
        if not self.cleared:
            if self.armed:
                self.cleared = True      # armed by this watcher (a route) before its first tick: nothing to adopt
            else:
                self.adopt(p)
        if not self.armed:
            if scene == MAIN_MENU and (p.read_u32(CONTROL) == MAGIC or p.read_u32(AUTO) == AUTO_MAGIC):
                self.clear(p)            # an armed tournament a restored state brought back: never kept
            if not self.pending:
                return
            if scene in TOURNAMENT_SCENES:
                self.arm(p)
            elif time.monotonic()-(self.routed_at or 0) > 120.0:
                self.disarm(p, 'Dragon World Tour was not opened')
            return
        if scene in TOURNAMENT_SCENES:
            self.routing = False; self.draft = None
            if p.read_u32(native_preparation.ACCEPTED_MODE) != TOURNAMENT_MODE:
                p.write_u32(native_preparation.ACCEPTED_MODE, TOURNAMENT_MODE)
        elif scene == MAIN_MENU:
            if self.routing and time.monotonic()-(self.routed_at or 0) < ROUTE_SECONDS:
                return               # armed for the route: the Modded Modes page is opening Dragon World Tour
            # Back at the main menu: over (before the watcher may capture a clean main-menu checkpoint). Other
            # Dragon World Tour screens (World Tour's list, its clock) keep it; their battles are tournament battles.
            self.disarm(p, 'Dragon World Tour did not open' if self.routing else 'back at the main menu')
            return
        auto = p.read_u32(AUTO) == AUTO_MAGIC
        if auto and scene in (TYPE_SCENE, ENTRY_SCENE):
            # The stand-ins return in the frame they are called: the loaded overlay still calling the native menu
            # after AUTO_GRACE means they did not run (a changed overlay); withdraw the auto entry and guide the native
            # entry instead. The overlay's own load is not counted (a slow disc kept scene 33 loading for seconds
            # under the cover, live Oct 20); AUTO_LIMIT bounds a native menu that began before the swap.
            now = time.monotonic()
            self.auto_scene = self.auto_scene or now
            site, menu = (TYPE_CALL, TYPE_MENU) if scene == TYPE_SCENE else (ENTRY_CALL, REGISTRATION)
            if p.read_u32(site) == jal(menu):
                self.auto_since = self.auto_since or now
            else:
                self.auto_since = None
            if ((self.auto_since is not None and now - self.auto_since > AUTO_GRACE)
                    or now - self.auto_scene > AUTO_LIMIT):
                p.write_u32(AUTO, 0)
                auto = False
                self.veil = None     # the players answer the native menus themselves: the cover comes down
                self.log('Tag Team Tournament: the tournament menus did not skip; register the leaders by hand.')
        else:
            self.auto_since = self.auto_scene = None
        if scene == ENTRY_SCENE:
            if auto:
                self.show(p, b'')    # the stand-in registers the drafted leaders
            else:
                self.entry_tick(p, manager)
            return
        if self.block:
            self.block = False
            p.write_u32(CONTROL+F['block'], 0)
        if scene == TYPE_SCENE:
            self.turn = None
            self.set_order(None)
            if self.bracket_seen:
                # The native tournament ended (champion or eliminated) and Dragon World Tour's menu is back: the
                # next tournament there is the game's own.
                self.disarm(p, 'the tournament is over')
            elif auto:
                self.show(p, b'')    # the stand-in answers the type menu
            else:
                self.show(p, banner([self.tr(BANNER_COUNT, n=self.setup.entry_count()),
                                     order_text(self.setup, self.tr) or self.tr(CPU_NOTE_SHORT)], y=404),
                          scene=TYPE_SCENE)
            return
        if scene != BRACKET_SCENE:
            return
        self.bracket_seen = True
        self.turn = None
        self.set_order(None)
        obj = p.read_u32(RUNTIME)
        if not 0x100000 <= obj < 0x1FFC000:
            self.show(p, b'')
            return
        if self.watching(p):
            # the host is here: a CPU row the guest asks about waits for the answer (an expired lease skips it)
            p.write_u32(CONTROL+F['wlease'], WATCH_LEASE)
        entrants = parse_entrants(p.read(obj+OBJ_ENTRANTS, ENTRANTS*ENTRANT_BYTES))
        rows = parse_rows(p.read(obj+OBJ_ROWS, 16*ROW_RECORD))
        if not settled(entrants, rows):
            return
        key = (p.read_u32(manager+MGR_TYPE), p.read_u32(manager+MGR_DIFFICULTY),
               tuple(e.character for e in entrants))
        if key != self.plan_key:
            self.plan_built(p, key, entrants)
        self.bracket_tick(p, obj, entrants)

    def plan_built(self, p, key, entrants):
        setup = self.setup
        # One tournament keeps its teams: the same entrants always give the same random teammates.
        seed = '|'.join(map(str, (key, setup.size, sorted(setup.humans.items()))))
        plan = Plan(setup, self.rosters, seed=seed, pool=self.pool,cpu_settings=self.cpu_settings).build(entrants)
        p.write(TABLE, plan.table())
        import cpu_difficulty_select as cpu_select
        p.write(cpu_select.TOUR_LEVELS,plan.level_table())
        self.plan, self.plan_key = plan, key
        kind = type_names()[key[0]] if key[0] < len(TYPES) else key[0]
        locked = sorted({m[0] for team in plan.teams for m in team} & set(self.locked))
        self.log(f'Tag Team Tournament: {kind}, difficulty {key[1]+1}; locked fighters swapped out of the bracket: '
                 f'{p.read_u32(CONTROL+F["swapped"])}, locked fighters left: {len(locked)}'
                 + (f' ({", ".join(character_name(c) for c in locked)})' if locked else '') + '. Teams:')
        for i, members in enumerate(plan.teams):
            who = '+'.join(f'P{n}' for n in plan.players[i]) or ('followed' if entrants[i].human else 'CPU')
            self.log(f'  {i:2} {who:>8}: ' + ', '.join(f'{character_name(c)}' + (f' (costume {k+1})' if k else '')
                                                         for c, k, _ in members))
        for note in plan.notes:
            self.log('Tag Team Tournament: ' + self.tr(BANNER_ADOPTED, t=note['team']+1,
                                                         name=character_name(note['registered']),
                                                         drafted=character_name(note['drafted'])))
        self.save_state()

    # ---- CPU-vs-CPU rows: the protections a launch needs for its return, and the Watch / Skip question
    def watching(self, p):
        return self.armed and p.read_u32(CONTROL+F['watch']) == 1

    def protect(self, p, manager, clear=False):
        """Before scene 35 restarts after this launch (written at the launch, again on the restored match start):
        the native would resolve every other CPU row of the round at its return (0x3699D0) and scan / advance only
        to rows holding a human. So, in the scene manager copy: a watched row's side-0 entrant B is marked human (the
        result maps sides as the launch did), the next CPU row's entrant A carries a stop mark, and the round's later
        CPU rows are marked played. watch_code removes all three at the return. clear=True takes them out again (the
        last human just lost: the native Eliminated ending and its own simulation run unchanged)."""
        match = self.match
        if match is None or not self.watching(p):
            return
        k, e0 = match['row'], match['entrants'][0]
        entrants = parse_entrants(p.read(manager+MGR_ENTRANTS, ENTRANTS*ENTRANT_BYTES))
        rows = parse_rows(p.read(manager+MGR_ROWS, 16*ROW_RECORD))
        flags = [struct.unpack('<H', p.read(manager+MGR_ROWS+16*r, 2))[0] for r in range(16)]
        marks = match.setdefault('marks', {})
        if not marks:
            cpu = lambda r: (r < CPU_ROWS and rows[r][1] < ENTRANTS and rows[r][2] < ENTRANTS and
                             not entrants[rows[r][1]].human and not entrants[rows[r][2]].human)
            stop = k+1 if cpu(k+1) else None
            prot, r = [], k
            while r < CPU_ROWS-1 and not flags[r] & ROW_LAST:
                r += 1
                if r >= k+2 and cpu(r) and not flags[r] & ROW_PLAYED:
                    prot.append(r)
            marks.update(e0=e0 if match['watched'] else None, stop=stop, stop_entrant=rows[stop][1] if stop else None,
                         prot=prot)
        def human_bit(entrant, on):
            at = manager+MGR_ENTRANTS+entrant*ENTRANT_BYTES
            value = struct.unpack('<H', p.read(at, 2))[0]
            p.write(at, struct.pack('<H', value | HUMAN if on else value & ~HUMAN))
        def played_bit(row, on):
            at = manager+MGR_ROWS+16*row
            value = struct.unpack('<H', p.read(at, 2))[0]
            p.write(at, struct.pack('<H', value | ROW_PLAYED if on else value & ~ROW_PLAYED))
        if marks['e0'] is not None:
            human_bit(marks['e0'], not clear)
        if marks['stop'] is not None:
            human_bit(marks['stop_entrant'], not clear)
        for r in marks['prot']:
            played_bit(r, not clear)
        record = (0, 0, 0, 0) if clear else (k+1, marks['e0']+1 if marks['e0'] is not None else 0,
                                              marks['stop']+1 if marks['stop'] is not None else 0,
                                              sum(1 << r for r in marks['prot']))
        p.write(CONTROL+F['wclean'], struct.pack('<4I', *record))

    def last_human_out(self, p, manager, loser):
        """True when the entrant losing now was the last human (or followed) one: no mark may stay then."""
        marks = (self.match or {}).get('marks') or {}
        marked = {marks.get('e0'), marks.get('stop_entrant')} - {None}
        entrants = parse_entrants(p.read(manager+MGR_ENTRANTS, ENTRANTS*ENTRANT_BYTES))
        if not entrants[loser].human or loser in marked:
            return False
        return not [e for e in entrants if e.human and not e.eliminated and e.index != loser and e.index not in marked]

    def question_tick(self, p, obj):
        """The bracket waits on a CPU-vs-CPU row (watch_code published ask): always watch answers at once; ask
        shows the question in the announcer's window (or a banner) and takes the region's accept (Watch) or back
        (Skip) from either controller; no answer within QUESTION_SECONDS skips. Returns the picture lines, if any."""
        import regional
        import time
        ask = p.read_u32(CONTROL+F['ask'])
        if not ask:
            if self.question is not None:
                self.text.restore_line(p)
            self.question = None
            return None
        row = ask - 1
        p.write_u32(CONTROL+F['wlease'], WATCH_LEASE)
        if self.plan is None:
            return None
        if self.setup.cpu_matches == 'watch':
            p.write_u32(CONTROL+F['answer'], 1)
            return None
        rows = parse_rows(p.read(obj+OBJ_ROWS, 16*ROW_RECORD))
        a, b = rows[row][1], rows[row][2]
        if self.question is None or self.question['row'] != row:
            self.question = dict(row=row, since=time.monotonic())
            p.write_u32(CONTROL+F['wbuttons'], 0)
            self.log(f'Tag Team Tournament: CPU match {character_name(self.plan.teams[a][0][0])} vs '
                     f'{character_name(self.plan.teams[b][0][0])}: watch or skip?')
        pressed = p.read_u32(CONTROL+F['wbuttons'])
        answer = 1 if pressed & regional.RAW_ACCEPT else 2 if pressed & regional.RAW_BACK else 0
        held = p.read_u32(PAD_RECORDS+0x188) | p.read_u32(PAD_RECORDS+0x1C0+0x188)
        if held & HELD_SCROLL:
            self.question['since'] = time.monotonic()   # looking over the bracket: the question waits
        if not answer and time.monotonic()-self.question['since'] > QUESTION_SECONDS:
            answer = 2
        if answer:
            p.write_u32(CONTROL+F['wbuttons'], 0)
            p.write_u32(CONTROL+F['answer'], answer)
            self.log(f"Tag Team Tournament: CPU match {'watched' if answer == 1 else 'skipped'}.")
            self.text.restore_line(p)
            return None
        names = lambda e: short_name(self.plan.teams[e][0][0])
        lines = [self.tr(QUESTION, a=names(a), b=names(b)), self.tr(QUESTION_KEYS, **buttons(self.tr))]
        if self.text.bracket_line(p, obj, '\n'.join(lines)):
            return []
        return lines

    def bracket_tick(self, p, obj, entrants):
        """The CPU-match question, the teammates on the VS / result screens and (a hand-made entry only) the
        adopted-leader notes. The bracket itself stays the game's own: no team-size marks on it."""
        lines = [self.tr(BANNER_ADOPTED, t=n['team']+1, name=character_name(n['registered']),
                         drafted=character_name(n['drafted'])) for n in (self.plan.notes if self.plan else [])]
        question = None
        if self.watching(p):
            question = self.question_tick(p, obj)
            # the marks the guest still holds (the watched row's side-0 entrant, the stop mark) and the CPU
            # entrants the bracket styled as human while they were marked keep a CPU portrait frame
            we0, wstop = struct.unpack('<2I', p.read(CONTROL+F['we0'], 8))
            marked = {we0-1} if we0 else set()
            if 0 < wstop <= 16:
                marked.add(struct.unpack('<H', p.read(obj+OBJ_ROWS+16*(wstop-1)+2, 2))[0])
            unmark_frames(p, obj, entrants, marked, self.bracket_cache)
        if question:
            lines = question
        if self.plan:
            # The VS / result screens: each side's form line names its team (the game draws it; the tables are
            # swapped while the bracket shows, so the VS screen opens with them).
            texts = {e: self.team_line(e) for e in range(ENTRANTS) if len(self.plan.teams[e]) > 1}
            self.text.vs_lines(p, obj, texts)
        # The bracket slides away for the VS screen (layout scroll +0x18 / moving flag): notes on the bracket only.
        scroll = struct.unpack('<2i', p.read(obj+0x30+0x18, 8))
        vs = scroll[0] >= VS_SCROLL or bool(p.read_u32(obj+OBJ_VS_FLAGS) & BRACKET_MOVING)
        key = (vs, tuple(lines))
        if key != self.bracket_drawn:
            self.bracket_drawn = key
            self.bracket_packet = banner(lines[:2], y=372) if lines and not vs else b''
        self.show(p, self.bracket_packet, scene=BRACKET_SCENE)

    def team_line(self, entrant):
        members = self.plan.teams[entrant]
        return self.tr(VS_TEAM, names=', '.join(short_name(c) for c, _, _ in members[1:]))

    def entry_tick(self, p, manager):
        """The tournament entry (scene 34): check How many people, then show whose turn it is and give that
        player's own controller the pass-the-pad entry."""
        setup = self.setup
        expected = setup.entry_count()
        got = p.read_u32(manager+MGR_HUMANS)
        if got != expected:
            if not self.block:
                self.block = True
                p.write_u32(CONTROL+F['block'], 1)
                self.log(f'Tag Team Tournament: How many people is {got}, expected {expected}; the entry waits '
                         'for Back.')
            self.set_order(None)
            self.show(p, banner([self.tr(BANNER_MISMATCH, got=got, n=expected),
                                 self.tr(BANNER_MISMATCH_BACK, n=expected, **buttons(self.tr))], y=8, warning=True), scene=ENTRY_SCENE)
            return
        if self.block:
            self.block = False
            p.write_u32(CONTROL+F['block'], 0)
        turn = entry_turn(p)
        if setup.cpu_only:
            self.set_order(None)
            if self.text.announce(p, self.tr(BANNER_TURN_CPU)):
                self.show(p, b'')
            else:
                self.show(p, banner([self.tr(BANNER_TURN_CPU)], y=90), scene=ENTRY_SCENE)
            return
        if turn is None or not 0 <= turn < len(setup.teams):
            self.show(p, b'')
            return
        team, players = setup.teams[turn]
        if turn != self.turn:
            self.turn = turn
            self.set_order((players[0],))
            self.log(f'Tag Team Tournament entry: Team {team+1}, Player {players[0]} registers the leader.')
        lines = [self.tr(BANNER_TURN, t=team+1, p=players[0])]
        if turn < len(self.rosters) and self.rosters[turn]:
            lines.append(self.tr(BANNER_TURN_HINT, name=character_name(self.rosters[turn][0][0])))
        else:
            lines.append(self.tr(BANNER_TURN_PLAIN))
        # The announcer says it in the game's own message window; the mod's banner only when that is not there.
        if self.text.announce(p, '\n'.join(lines)):
            self.show(p, b'')
        else:
            self.show(p, banner(lines, y=90), scene=ENTRY_SCENE)

    # ---- per match
    def match_for(self, p):
        """At a fresh tournament battle: the match record (humans, assignment, order) of its teams, or None."""
        if not self.armed or self.plan is None:
            return None
        manager, _ = self.scene(p)
        if p.read_u32(SETUP+8) != TOURNAMENT_MODE:
            return None
        row_index = p.read_u32(manager+MGR_MATCH)
        if not 0 <= row_index < 16:
            return None
        if (self.match is not None and not self.match.get('done') and self.match['row'] == row_index and
                self.match['round'] == p.read_u32(manager+MGR_ROUND)):
            return self.match                   # asked again for the same launch (loading cards, then preparation)
        entrants = parse_entrants(p.read(manager+MGR_ENTRANTS, ENTRANTS*ENTRANT_BYTES))
        rows = parse_rows(p.read(manager+MGR_ROWS, 16*ROW_RECORD))
        e0, e1 = sides(entrants, rows[row_index])
        if not (0 <= e0 < ENTRANTS and 0 <= e1 < ENTRANTS):
            return None
        for side, entrant in ((0, e0), (1, e1)):
            team = self.plan.teams[entrant]
            leader = p.read_u32(SETUP+0xC4+side*SIDE_STRIDE)
            count = p.read_u32(SETUP+0xC0+side*SIDE_STRIDE)
            if leader != team[0][0] or count != len(team):
                self.log(f'Tag Team Tournament: side {side} ({character_name(leader)}, {count} fighters) is not '
                         f'entrant {entrant}\'s team; this match plays natively.')
                return None
        humans, assignment, order = self.plan.match(e0, e1)
        watched = not entrants[e0].human and not entrants[e1].human
        self.match = dict(row=row_index, entrants=(e0, e1), humans=0 if watched else humans,
                          assignment=None if watched or humans < 2 else assignment, order=() if watched else order,
                          original=None, token=None, round=p.read_u32(manager+MGR_ROUND), watched=watched)
        humans, order = self.match['humans'], self.match['order']
        self.protect(p, manager)
        self.set_order(order)
        who = lambda e: '+'.join(f'P{n}' for n in self.plan.players[e]) or 'CPU'
        if watched:
            self.log('Tag Team Tournament: watching a CPU match (single screen, every fighter a CPU).')
        self.log(f"Tag Team Tournament match: {ROUND_NAMES[min(self.match['round'], 4)]}, entrant {e0} ({who(e0)}) "
                 f"vs {e1} ({who(e1)}), {len(self.plan.teams[e0])}v{len(self.plan.teams[e1])}, humans {humans}"
                 + (f", controllers of players {', '.join(map(str, order))}" if order else '')
                 + (f', seats {assignment}' if humans >= 2 else '') + '.')
        self.winner = None
        return self.match

    def latch(self, flags):
        if self.match is not None:
            side = winner_side(flags)
            if side is not None:
                self.winner = side

    def result_side(self, p, winner):
        """The side the native result request must name for the team result `winner` (0/1).

        CPU Only: when the followed entrant loses, the winner becomes the followed one (its human bit in the scene
        manager copy, before the native result), so the native tournament keeps showing one match per round up to
        the champion. 0x369BB0 re-derives the sides from that bit (side 0 = the human), so the winner is then side
        0 whatever side it fought on."""
        if (self.plan is None or self.setup is None or not self.setup.cpu_only or self.match is None or
                self.match.get('watched')):
            return winner
        manager, _ = self.scene(p)
        e = self.match['entrants']
        loser, won = e[1-winner], e[winner]
        base = manager + MGR_ENTRANTS
        flags_loser = struct.unpack('<H', p.read(base+loser*ENTRANT_BYTES, 2))[0]
        flags_won = struct.unpack('<H', p.read(base+won*ENTRANT_BYTES, 2))[0]
        if flags_loser & HUMAN and not flags_won & HUMAN:
            p.write(base+won*ENTRANT_BYTES, struct.pack('<H', flags_won | HUMAN))
            p.write(base+loser*ENTRANT_BYTES, struct.pack('<H', flags_loser & ~HUMAN))
            self.log(f'Tag Team Tournament: now following entrant {won}.')
            return 0
        return winner

    def record(self, winner):
        if self.match is None:
            return
        e = self.match['entrants']
        self.history.append(dict(round=self.match['round'], row=self.match['row'], winner=e[winner],
                                 loser=e[1-winner]))
        self.match['done'] = True
        self.set_order(None)
        self.save_state()


def _pointer(p, address):
    value = p.read_u32(address)
    return value if value % 4 == 0 and 0x100000 <= value < 0x1FF0000 else None


def entry_turn(p):
    """Index (0-based) of the human the native entry (scene 34) is registering now, or None (see ENTRY_TURN)."""
    obj = _pointer(p, ENTRY_OBJECT)
    turn = _pointer(p, obj+ENTRY_TURN_OBJECT) if obj is not None else None
    if turn is None:
        return None
    value = p.read_u32(turn+ENTRY_TURN)
    return value if 0 <= value < 8 else None


def ringout_summary(p, loser_side):
    """(fighters of the losing side the ring-outs eliminated, its fighter count, contacts) from tournament_ringout's
    CONTROL of the match just played (None when that feature is not installed)."""
    import tournament_ringout as ring
    if p.read_u32(ring.CONTROL) != ring.MAGIC:
        return None
    count = p.read_u32(ring.CONTROL+ring.F['count'])
    eliminated = p.read_u32(ring.CONTROL+ring.F['eliminated'])
    contacts = p.read_u32(ring.CONTROL+ring.F['contacts'])
    losers = [i for i in range(min(count, 12)) if i & 1 == loser_side]
    return sum(1 for i in losers if eliminated >> i & 1), len(losers), contacts


def finish_native(p, tournament, match, winner, alive=None, timeout=30.0, tick=None):
    """On the just-loaded tournament original: no second capture, release the preparation hold, then - in the fight
    phase - the native surrender request for the side the tournament must see win. Returns once the battle loop
    ended (the native teardown then returns to scene 35 and its result screen). tick(p), if given, runs every
    poll on this client (the watcher re-publishes its black cover there until a frame drew it)."""
    import time
    import native_preparation as prep
    manager, _ = tournament.scene(p)
    if (p.read_u32(manager+MGR_MATCH) != match['row'] or p.read_u32(manager+MGR_ROUND) != match['round']):
        raise ValueError('The saved match start belongs to another tournament match')
    p.write_u32(prep.CONTROL+48, 0)       # disarmed: this fresh battle is never captured again
    side = tournament.result_side(p, winner)
    # The request is queued now; 0x217EF0 acts on it in the fight phase. The restored battle is thrown away, so its
    # intro is skipped under the cover: phase 1 jumps to its last substate (4, as the preparation gate heals it) and
    # phase 2 (Ready/Fight) straight to the fight - the loop then ends about 1.3 s after the release (live, Oct 17).
    # CPU-match watching: the restored start predates nothing the return needs - write the protections again
    # (or take them out when this result eliminates the last human).
    loser = match['entrants'][1-winner]
    tournament.protect(p, manager, clear=tournament.last_human_out(p, manager, loser) if not match.get('watched')
                       else False)
    force_result(p, side)
    heard, polls = _finish_loop(p, side, alive, timeout, tick)
    tournament.log(f'Tag Team Tournament: the restored match start played its own streams (music, crowd, voice) in '
                   f'{heard} of {polls} polls, under the muted black cover.')
    # The fresh battle was captured (CONTROL+52) and held when it was saved. A menu checkpoint would normally bring
    # back a clean transport; here the native tournament goes on, so the next match must find it uncaptured.
    for off in (16, 20, 24, 52, 56):
        if p.read_u32(prep.CONTROL+off):
            p.write_u32(prep.CONTROL+off, 0)
    return side


def _finish_loop(p, side, alive, timeout, tick):
    import time
    import native_preparation as prep
    p.write_u32(prep.CONTROL+16, 0)       # release the hold the save was made in
    asked = time.monotonic()
    budget = prep.RunningTime(p, timeout)
    heard = polls = 0
    while p.read_u32(LOOP) != 0:
        polls += 1
        heard += stream_playing(p)
        if alive:
            alive()
        if tick:
            tick(p)
        if budget.expired():
            raise TimeoutError('The saved match start did not end with the team result')
        phase = p.read_u32(PHASE)
        if 0x100000 <= phase < 0x8000000:
            state = p.read_u32(phase)
            if state == INTRO_PHASE and p.read_u32(phase+8) != INTRO_LAST:
                p.write_u32(phase+8, INTRO_LAST)
            elif state == READY_PHASE:
                p.write_u32(phase+8, 1)
                p.write_u32(phase, FIGHT_PHASE)
        if time.monotonic() - asked > 8.0 and p.read_u32(RESULT_FLAGS) & LATCHED == 0:
            force_result(p, side)          # a request lost to a native write is asked once more
            asked = time.monotonic()
        time.sleep(0.01)
    return heard, polls


def stream_playing(p):
    """True while any native ADX stream reports playing (status 3); False without reviewed stream addresses."""
    if ADX_TABLE is None:
        return False
    for ch in range(ADX_CHANNELS):
        handle = p.read_u32(ADX_TABLE + ADX_ROW*ch)
        if 0x100000 <= handle < 0x2000000 and p.read(handle+1, 1)[0] == 3:
            return True
    return False


PHASE, FIGHT_PHASE, LOOP = A(0x2FEB38), 3, A(0x3337C0)
INTRO_PHASE, INTRO_LAST, READY_PHASE = 1, 4, 2
# Battle phase 0 (enter 0x217C40, update 0x217CF0): the stage's crowd / arena / gate camera shots, substates 0..5;
# substate 6 is the update's own "done" case (it returns phase 1 at once, the exit 0x217DB8 stops the camera).
CROWD_PHASE, CROWD_DONE = 0, 6


def opening_started(p):
    """Scene 35 has started the tournament's own opening: its logo waits for the jingle (OBJ_WAIT bit LOGO_WAIT),
    or the opening script is past it (OBJ_SCRIPT nonzero: 0x34 logo, 0x38 World Tournament Open, then the bracket)."""
    obj = p.read_u32(RUNTIME)
    if not 0x100000 <= obj < 0x1FFC000:
        return False
    return bool(p.read_u32(obj+OBJ_WAIT) & LOGO_WAIT or p.read_u32(obj+OBJ_SCRIPT))


def skip_crowd_shots(p):
    """Before the loading: phase 0 of a tournament battle ends in its next frame (substate CROWD_DONE), so the
    preparation starts at once; the shots play after the loading (team_intro.crowd_first). A store racing the
    update's own increment is simply made again by the next call. True once the battle is past phase 0."""
    obj = p.read_u32(PHASE)
    if not 0x100000 <= obj < 0x8000000 or p.read_u32(obj) != CROWD_PHASE:
        return True
    if p.read_u32(obj+8) < CROWD_DONE:
        p.write_u32(obj+8, CROWD_DONE)
    return False
