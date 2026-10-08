"""Guest core for delay-based lockstep online play (stock PCSX2 2.8.2, reviewed BT3/BT4 adapters), layout 4.

LAYOUT 4 (TTM Online Kit 2.1) adds, on top of layout 3 below:
  * TEN input slots, one per fighter of the 5 v 5 engine: slot s plays the fighter of physical index SEATS[s] (the kit
    uses slot = physical index: 0/1 the side leaders, 2.. the extras, side = physical & 1). INCOMING holds 512 frames
    per slot now (10 x 8 KiB). Slots 0/1 keep the native path (RAW injects them into ports 0/1); slots 2..9 are
    published by SEAT (OPT_SEATS, inside POLL, the same update on every PC) into private native-format pad records
    SEAT_PADS[s - 2] (the held word with the dominant stick directions, the four stick floats as the native poll
    derives them, the previous held word and the pressed edges), exactly the fields quad_controller's FRAME writes
    for players 3/4;
  * RESOLVE, the pad resolver at A(0x1DC2A0) (the native accessor the human input decoder, the lock-on queue's
    resolver variant and the lock-on arrow call with a0 = actor): an actor seated in SEAT_CONTROL gets its slot's
    record (slots 0/1: the native port records; 2..9: SEAT_PADS), any other actor goes down the chain unchanged (the
    mod's takeover / co-op resolvers, then the native accessor). The seat table is logic (hashed, class 1): a player
    who leaves becomes a CPU at a frame-scheduled frame (SCHED writes its seat := NO_SLOT, the actor's CPU flag and
    the slot mask bit), identically on every PC;
  * the kit's netplay_view layout 4 keeps its per-fighter cameras in VIEW_AREA (+0x26000..+0x30000).

LAYOUT 3 (TTM Online Kit 2.0) adds, on top of layout 2 below:
  * up to four input slots (= the mod's quad seats): slots 0/1 are the native ports, slots 2/3 are written into the
    mod's quad_controller MAILBOX inside POLL (OPT_MAILBOX), in the controller hub's format, from the agreed input;
    any slot can be this PC's own (self feed), or none (a spectator, a host that does not play);
  * W waits for this PC's OWN drain once a wait is agreed: a PC whose aux is not part of the agreement (no slot)
    stalls in the vblank sleep inside W until its own disc pump has drained, so the wait still completes at the
    agreed frame on every PC;
  * the VOICE gate (OPT_VOICE): the battle director's three voice-done queries (intro speakers A/B, win quote;
    `jal 0x265F70` = ADXT_GetStat in {STOP, PLAYEND}) read an AGREED answer. VSTART wraps the three voice starts
    (`jal 0x265E98`) and counts them in gate_seq byte 2 (identical on every PC: starts are director logic);
    VQ records this PC's completion as gate_local byte 2 := that count and answers 'done' only while gate_agreed
    byte 2 equals it, which POLL sets when every masked slot's aux byte 2 equals the current count (a completion of
    an earlier line carries an older count and never matches). The intro and the win quote then advance at the same
    frame on every PC: lockstep can run from the first update of the battle loop (start_state ANY) through the
    intro, the fight, the K.O. banner and the win quote;
  * the END_STATE end rule: DECIDED when the director reaches CONTROL.end_state (6 = the result menu) or later;
  * OPT_NEUTRAL_END: once DECIDED or ABORTED every netplay port (and the mailbox seats) reads NEUTRAL instead of the
    PC's own pads, so the native result menu (Fight Again, replays, Character Select...) can never be used: the kit
    runs Retry / Return to lobby itself;
  * CONTROL grows to 0x100 bytes: +0xF0 the kit's token (never written here, never hashed), +0xF4 end_state,
    +0xF8 options, +0xFC gate_wait (vblanks W waited for this PC's own drain; local);
  * the SCHED ring (OPT_SCHED): frame-scheduled host writes. The host kit picks a frame K at least D + 2 updates
    ahead of its own game and sends the entry {K, seq, writes} to every PC; each kit writes it into its ring (tag
    last) before its game can reach K. POLL(N) waits (vblank stall, like a late input) until CONTROL.sched_sealed >= N
    (the kit raises it once every entry up to that frame is in the ring; the host's own copy holds 0xFFFFFFFF), then
    applies, in seq order, every entry tagged K + 1 == N + 1 whose seq is sched_next_seq (hashed): each write is
    (old & ~mask) | (value & mask) on an aligned EE RAM word. An entry tagged below N + 1 still pending means a kit
    bug: ABORTED with ABORT_SCHED_LATE. Before RUNNING and after DECIDED / ABORTED every present entry is applied at
    once, in seq order (the games are unlinked then). The hub's open / parked / duel words and the services' control
    words travel this way.
Aux bytes: 0 = the native FIFO loader (W0), 1 = the mod's runner pumps (W1, frame-scheduled services), 2 = voice,
3 = reserved.

Every peer runs the whole game from the same savestate; only controller inputs travel, and both games must stay
bit-identical. This module is the guest half: it makes one battle update consume exactly one agreed frame of input
for every human slot, captures this machine's physical pad for a later frame, waits (in the game's own vblank sleep)
when the agreed input is late, hashes the state that decides the next update, and (layout 2) makes the native disc
loader's completion an AGREED event: the native IO gate. The host half (the PINE bridge, the UDP session, the relay)
is the TTM Online Kit; the builders here never touch PINE. Not shipped in the mod: only the kit's match files use it.

WHERE IT SITS (USA addresses through A(); all eleven are native in beta.35 and beta.36 matches)
  A(0x12BC64)  battle loop sub_12BBD0: `jal 0x122A38` (the native pad poll)           -> jal POLL
  A(0x122A78)  inside sub_122A38: `jal 0x296160` (pad status, once per port)            -> jal STATUS
  A(0x122B08)  inside sub_122A38: `jal 0x295FB8` (raw read into record+0x114)           -> jal RAW
  GATE_SITES   the 8 in-fight `jal 0x265298` (the native disc pump) of the FIFO task handlers -> jal W0
Every consumer of the pad records (pause and menu checks, the mod's actor-chain wrappers at A(0x1C2A28), the actor
update) runs after the poll in the same update. Only the battle loop is hooked: menus, loading and FMV poll natively.

DESIGN DECISIONS (from the p22 research: frame, state and rig parts)
  * Injection is at the RAW read, not by rewriting the derived record fields. sub_122A38 then derives held (+328),
    previous, pressed edge (+336), auto-repeat, logical masks and the analog floats from the injected bytes itself,
    once, identically on every peer; the pressed edge is computed from the previous INJECTED word.
  * Stall policy: POLL waits for the agreed frame by calling sub_26E290 (CRI ADXM wait-vsync: services CRI, then
    sleeps until the next vblank) and zeroes the vblank counter gp-0x5148 afterwards exactly as sub_264D98 does, so
    a stall is an extension of the previous pass's vsync wait (a slowdown, never an extra logic step).
  * Lockstep starts at the fight: while ARMED every netplay port reads neutral and nothing waits; RUNNING starts at
    the first update whose director state is CONTROL.start_state right after CONTROL.after_state. Frame N counts
    updates from there. Frames N < D are neutral on every peer (no capture exists for them).
  * Both native ports are overridden while a netplay poll runs: ports in the slot mask get agreed input, the others
    neutral, and STATUS reports 'connected, ready' for both. The local physical pad (CONTROL.capture_port) is still
    read and captured into OUTGOING[N + D], with this machine's gate word as the aux word.
  * In lockstep mode the capture (raw8 AND aux) is also committed straight into INCOMING[local_slot][N + D] (self
    feed), so the host only forwards OUTGOING to the peer and writes the peer's frames. The per-machine words
    (local_slot, self_feed) are written by the host while the emulator is paused on the loaded state, or are already
    in a per-machine copy (late attach); the installed savestate is byte-identical on every peer.
  * Playback mode never waits: a frame with no committed entry is neutral (counted in CONTROL.missing). Its INCOMING
    rings can be preloaded with a script (2048 frames per slot, about 68 s at 30 updates/s) in the savestate itself.
  * The per-update state hash reuses netplay_state_hash's descriptor table plus this module's gate rows
    (hash_rows: gate_seq, gate_agreed, gate_opened) and its guest hash (h = h*33 ^ word per class). It runs at the
    start of POLL for frame N (the state after N running updates), before any wait.
  * Lockstep ends the moment the fight is DECIDED (CONTROL.end_rule, on by default): at the start of POLL for frame N,
    after the hash of N, the core checks the state after N updates (director out of CONTROL.live_state, or the
    winner bits of the result words A(0x333700)). Then this update and every later one poll natively and nothing
    waits again, so each copy plays the end sequence alone.
  * A stall longer than CONTROL.max_stall vblanks or a host abort request ends the session: state ABORTED, local pads
    native again (one-sided; they exist so a dead host or link never freezes the game forever).

THE NATIVE IO GATE (layout 2; spec 9)
  Why: the battle's FIFO task handlers (sub_1272B0, sub_127430, sub_127680 type 2, sub_1278B0 type 1, sub_127C40;
  run one task at a time by the task runner sub_263508 at A(0x12BC24), the top of the battle-loop pass, BEFORE POLL)
  wait for the native disc pump sub_265298 (a per-call state machine on 0x31E760; 1 only when the pending list is
  empty) and then act: sub_20B350 publishes manager+612/+616 (the transformation / damage-costume / summon reload is
  ready), models are swapped, the next state starts. How many updates the IO takes depends on the whole stall history
  of that PC (music and voice share the drive), so two PCs under different stalls saw the completion at different
  frames (p33 t-pre/t-io/t-io2: manager+612/+616 differed for 8-33 frames; a short form such as Goku (Mid) -> SSJ
  could act on it).
  How: every one of the 8 pump calls becomes `jal W0`. W(c), channel c's program:
    r = sub_265298()                       always called, so this PC's IO keeps moving
    native when: no CONTROL magic, state != RUNNING (ARMED, DECIDED, ABORTED), gate_enable == 0, the blocking loader
      runs (bit 0x4000 of *(gp-20836)+20, set by sub_2635C8 around its loop and nowhere else), or the scene restart
      flag 0x8000 (A(0x3337B8)) is set. The blocking loader runs the FIFO handlers through sub_263508 but never
      reaches POLL (it calls the native pad poll itself), so a gated W there would wait forever for an agreed word
      nobody computes. The battle restart sub_12B570 runs it at the top of a pass, BEFORE that pass's POLL could see
      the director leave the fight (scene flag 0x8000 is set by sub_216CC8 at director 99, after POLL), and every
      later battle load (sub_12B5E0) runs it too. The restart flag alone does not cover that: sub_126F18 clears the
      scene flags before its sub_128530 starts the loader.
    if r != 0 and gate_local[c] == gate_seq[c]: gate_local[c] += 1      this PC has drained for wait seq+1
    if gate_agreed[c] == gate_seq[c] + 1: gate_seq[c] += 1; gate_opened += 1; return 1
    return 0
  RAW captures gate_local (one byte per channel) as the aux word of OUTGOING[N + D] and of the self-fed INCOMING
  entry; the kit forwards raw8 + aux and writes the peer's tag + aux as one aligned 8-byte PINE write. POLL(N), once
  every masked slot's input N is present: gate_agreed[c] = seq + 1 when EVERY masked slot's INCOMING[s][N].aux byte c
  equals (seq + 1) & 0xFF, else seq (N < D, or a missing entry in playback: seq). Byte arithmetic is modulo 256.
  Why it is deterministic: W's result depends only on gate_seq/gate_agreed (hashed, identical on every PC); the local
  pump result only moves gate_local (unhashed, local) and so only what travels as aux. agreed == seq + 1 means every
  PC had captured local == seq + 1 at least D frames earlier, i.e. its pending list was empty for this wait (the task
  runner serves only the head task, so the waits of one channel are sequential). The invariant is gate_local in
  {seq, seq + 1}. Cost: completion is seen D frames after the slowest PC drains.
  Channels: 0 native FIFO loader (installed here); 1 extra-reload runners, 2 body runner, 3 fusion job (reserved for
  the frame-scheduled services, kit 1.4.0). The SCHED ring and its CONTROL words stay zero.

MEMORY (BASE..END = 0x07B00000..0x07B50000, zero and unreferenced in beta.35/36; netplay_view lives in CONTROL+0x100..
TABLE; netplay_state_hash's own probe uses 0x06E00000..0x06E60000)
  POLL_CODE +0x0000, RAW_CODE +0x0600, STATUS_CODE +0x0900, HASH_CODE +0x0A00
  CONTROL   +0x1000  (FIELDS below; +0x80 fighter count, +0x84 up to 12 fighter pointers of this update; +0xB8..
                     the end rule; +0xC8.. scheduling (reserved, zero) and the gate; +0xF0 the kit's resync token,
                     never written by the core and never hashed)
  TABLE     +0x2000  hash descriptors (netplay_state_hash.table_bytes format), zero-terminated
  OUTGOING  +0x3000  256 x 16 B: +0 raw[8] of the local physical pad, +8 tag = frame + 1 (written last), +12 aux
                     (this PC's gate_local at the capture); the frame is N + D of the capturing update
  HASHES    +0x4000  256 x 64 B: +0 tag = N + 1 (written last), +4 combined hash, +8 game frame counter, +12 words
                     hashed, +16..+47 class hashes, +48 battle clock; machine-local diagnostics, never compared:
                     +52 CRI vsync count, +56 total stall vblanks so far, +60 EE cycles of the hash
  INCOMING  +0x10000 10 slots x 512 x 16 B (layout 4; slot s at +s*0x2000, `sll 13`): +0 raw[8], +8 tag = frame + 1
                     (the commit word, written LAST, together with +12), +12 aux (gate bytes of that slot's PC)
                     (the native poll serves slots 0/1 as ports 0/1; slots 2..9 are SEAT's records)
  SEATS     +0x24000 SEAT_CONTROL (magic, enable, the fighter of each slot), +0x24100 SEAT_PADS (8 x 448 B),
                     +0x25000 SEAT_CODE, +0x25800 RESOLVE_CODE, +0x25C00 its displaced-prologue trampoline
  VIEW_AREA +0x26000..+0x30000 netplay_view layout 4 (per-fighter cameras and their programs)
  SCHED     +0x30000 64 x 512 B (layout 3, OPT_SCHED): +0 tag = K + 1 (written last; 0 = empty), +4 seq, +8 count
                     (up to 41), +12 flags (0), +16 count x {address, value, mask}; entry index = seq & 63
  W_CODE    +0x38000 W(c) at +0x200*c: W0 (the native FIFO loader's 8 pump sites) and W1 (installed for the
                     frame-scheduled services' runner pumps: called only by code the host's service delivers);
                     CODE2 +0x39000..+0x3C000 the layout 3 programs
Raw 8 bytes = the record+0x114 layout: buttons (active-low, low byte then high byte), right X, right Y, left X,
left Y, two pressure bytes; the rest of the 18-byte buffer is zeroed and the read returns 18.

Guest rules kept: 16-byte stack frames, no k0/k1, native addresses through A() (resolved lazily, so the host
helpers import under any adapter). Online play is reviewed BT3/BT4 adapters: natives() fails closed under any other
adapter (NativeMapError), so no European, Japanese or BT4 state can be built (BT4 shares the USA addresses and serial,
so the adapter's own name is checked, not only the serial).
"""
import functools
import struct
from types import SimpleNamespace

from native_map import A, CRC, SERIAL, NativeMapError
from prototype import Assembler

BASE, END = 0x07B00000, 0x07B50000
POLL_CODE, RAW_CODE, STATUS_CODE, HASH_CODE = BASE, BASE + 0x600, BASE + 0x900, BASE + 0xA00
CONTROL = BASE + 0x1000
ACTOR_COUNT, ACTOR_LIST, ACTOR_MAX = CONTROL + 0x80, CONTROL + 0x84, 12
TABLE, TABLE_END = BASE + 0x2000, BASE + 0x3000
OUTGOING, OUT_SLOTS, OUT_ENTRY = BASE + 0x3000, 256, 16
HASHES, HASH_SLOTS, HASH_ENTRY = BASE + 0x4000, 256, 64
INCOMING, IN_SLOTS, IN_ENTRY, SLOTS = BASE + 0x10000, 512, 16, 10
SLOT_BYTES, SLOT_SHIFT = IN_SLOTS * IN_ENTRY, 13
PORTS = 2                                        # the native poll serves ports 0 and 1: input slots 0/1
MAILBOX_SLOTS = (2, 3)                           # layout 3: slots 2/3 = quad seats 2/3 (quad_controller MAILBOX)
SEAT_CONTROL, SEAT_PADS = BASE + 0x24000, BASE + 0x24100      # layout 4 (OPT_SEATS)
SEAT_CODE, RESOLVE_CODE, RESOLVE_TRAMP = BASE + 0x25000, BASE + 0x25800, BASE + 0x25C00
VIEW_AREA, VIEW_AREA_END = BASE + 0x26000, BASE + 0x30000
SEAT_MAGIC = 0x4E505354                          # 'NPST'
SEAT_FIELDS = (('magic', 0x00), ('enable', 0x04), ('published', 0x08), ('resolved', 0x0C), ('seats', 0x10))
SF = dict(SEAT_FIELDS)
SEAT_CONTROL_BYTES = 0x40
RECORD_STRIDE = 448                              # the native pad record (input_script.RECORD_STRIDE)
PAD_RESOLVER = 0x1DC2A0                          # USA: the native pad accessor the human input decoder calls
SCHED, SCHED_ENTRIES, SCHED_ENTRY = BASE + 0x30000, 64, 512
W_CODE, W_STRIDE, CHANNELS = BASE + 0x38000, 0x200, 4         # layout 3: 0x200 per channel (W waits for its drain)
CODE2, CODE2_END = BASE + 0x39000, BASE + 0x3C000
assert OUTGOING + OUT_SLOTS * OUT_ENTRY <= HASHES and HASHES + HASH_SLOTS * HASH_ENTRY <= INCOMING
assert INCOMING + SLOTS * SLOT_BYTES <= SEAT_CONTROL and SEAT_PADS + (SLOTS - PORTS) * RECORD_STRIDE <= SEAT_CODE
assert RESOLVE_TRAMP + 0x40 <= VIEW_AREA and VIEW_AREA_END <= SCHED and SCHED + SCHED_ENTRIES * SCHED_ENTRY == W_CODE
assert W_CODE + CHANNELS * W_STRIDE <= CODE2 and CODE2_END <= END
assert SLOT_BYTES == 1 << SLOT_SHIFT and ACTOR_LIST + 4 * ACTOR_MAX <= CONTROL + 0x100
MAGIC = 0x4E504331                               # 'NPC1'
LAYOUT = 4
LAYOUT2 = SimpleNamespace(layout=2, control_bytes=0xF0)
OPT_NEUTRAL_END, OPT_MAILBOX, OPT_VOICE, OPT_SCHED = 1, 2, 4, 8   # CONTROL.options (layout 3)
OPT_SEATS = 16                                   # layout 4: slots 2..9 through SEAT / RESOLVE
SCHED_WRITES = (SCHED_ENTRY - 16) // 12          # 41 word writes per ring entry
NO_SEAL = 0xFFFFFFFF                             # sched_sealed of the host's own copy (it seals itself)
END_STATE = 4                                    # end rule bit: DECIDED when the director reaches CONTROL.end_state
RESULT_MENU = 6                                  # director state 6: the result menu (Fight Again, Character Select)
VOICE_CHANNEL = 2                                # the gate byte the voice gate uses
VOICE_START, VOICE_DONE, STICK_FLOAT = 0x265E98, 0x265F70, 0x1230B8
# (USA site, the delay-slot argument) of the director's voice starts and voice-done queries (ELF; p60 research)
VOICE_START_SITES = (0x217478, 0x2174D8, 0x217A70)
VOICE_DONE_SITES = (0x217590, 0x2175B8, 0x217B50)
LAYOUT1 = SimpleNamespace(layout=1, in_slots=8192, slots=2, slot_bytes=0x20000, control_bytes=0xC8)
OFF, PLAYBACK, LOCKSTEP = 0, 1, 2                # CONTROL.mode
IDLE, ARMED, RUNNING, ABORTED, DECIDED = 0, 1, 2, 3, 4   # CONTROL.state
AGREED, NEUTRAL_POLL = 1, 2                      # CONTROL.inject (only inside a netplay poll)
ABORT_HOST, ABORT_STALL, ABORT_SCHED_LATE = 1, 2, 3     # CONTROL.abort_reason (3: the frame-scheduled services)
FIGHT, READY, ANY = 3, 2, 0xFFFFFFFF             # battle director (gp-22328 -> +0) states
END_DIRECTOR, END_RESULT = 1, 2                  # CONTROL.end_rule bits: director left live_state / result words set
DEFAULT_END_RULE = END_DIRECTOR | END_RESULT
RESULT_WINNER_MASK = 0x1F                        # sub_217EF0: (*A(0x333700) & 0x1F) != 0 means the fight is over
NO_SLOT = 0xFFFFFFFF
DEFAULT_MAX_STALL = 1800                         # vblanks (30 s NTSC)
NEUTRAL = bytes.fromhex('ffff7f7f7f7f0000')
NEUTRAL_LO, NEUTRAL_HI = struct.unpack('<2I', NEUTRAL)
GP_VBLANK, GP_FRAME, GP_DIRECTOR = -0x5148, -22188, -22328
SCENE_FLAGS, RESTART_FLAG = 0x3337B8, 0x8000     # sub_126EC8()+6640 (USA), the battle-restart request (sub_216CC8)
GP_SYSTEM, LOADER_FLAGS, LOADER_ACTIVE = -20836, 20, 0x4000   # *(gp-20836)+20 |= 0x4000 while sub_2635C8 loops
PUMP = 0x265298                                  # the native disc pump (USA)
# (USA site, handler, handler state): the 8 in-fight `jal 0x265298`, read from the ELF in R-GATE (every delay slot
# is `nop`). Their handlers are queued by sub_128170/128230/128318/1283F0/128530/128728 and run only through the
# task runner sub_263508 (battle loop A(0x12BC24), or the blocking loader sub_2635C8 at load / restart).
GATE_SITES = ((0x1273A0, 'sub_1272B0', 2), (0x1274C0, 'sub_127430', 2), (0x127550, 'sub_127430', 5),
              (0x127760, 'sub_127680', 1), (0x127A70, 'sub_1278B0', 1), (0x127D68, 'sub_127C40', 1),
              (0x128058, 'sub_127C40', 5), (0x1280F8, 'sub_127C40', 91))
FIELDS = (('magic', 0x00), ('enable', 0x04), ('mode', 0x08), ('state', 0x0C), ('local_slot', 0x10),
          ('delay', 0x14), ('frame', 0x18), ('mask', 0x1C), ('capture_port', 0x20), ('self_feed', 0x24),
          ('waiting', 0x28), ('stall_now', 0x2C), ('stall_total', 0x30), ('stalled_updates', 0x34),
          ('stall_longest', 0x38), ('inject', 0x3C), ('abort', 0x40), ('abort_frame', 0x44), ('abort_reason', 0x48),
          ('max_stall', 0x4C), ('start_state', 0x50), ('after_state', 0x54), ('seen_state', 0x58),
          ('start_game_frame', 0x5C), ('missing', 0x60), ('captures', 0x64), ('hashing', 0x68), ('hash_tag', 0x6C),
          ('hash_last', 0x70), ('layout', 0x74), ('end_rule', 0x78), ('stall_start', 0x7C), ('actors', 0x80),
          ('live_state', 0xB8), ('decided_frame', 0xBC), ('decided_state', 0xC0), ('decided_result', 0xC4),
          # layout 2: frame-scheduled host writes (kit 1.4.0; zero here) and the native IO gate
          ('sched_enable', 0xC8), ('sched_sealed', 0xCC), ('sched_next_seq', 0xD0), ('sched_wait_total', 0xD4),
          ('sched_fail_frame', 0xD8), ('gate_enable', 0xDC), ('gate_local', 0xE0), ('gate_seq', 0xE4),
          ('gate_agreed', 0xE8), ('gate_opened', 0xEC),
          # layout 3
          ('token', 0xF0), ('end_state', 0xF4), ('options', 0xF8), ('gate_wait', 0xFC))
F = dict(FIELDS)
HOST_FIELDS = ('local_slot', 'self_feed', 'abort')   # what a host may write into a running game
CONTROL_BYTES = 0x100
TOKEN = CONTROL + 0xF0                           # the kit's resync token word (reserved: never written here)
MBOX_CODE, VSTART_CODE, VQ_CODE = CODE2, CODE2 + 0x600, CODE2 + 0x700
PRESENT_CODE, AGREE_CODE = CODE2 + 0x800, CODE2 + 0x900
SCHED_CODE = CODE2 + 0xC00
assert ACTOR_LIST + 4 * ACTOR_MAX <= CONTROL + F['live_state'] and CONTROL_BYTES <= 0x100
# Layout 1 builds made before the end rule hold 0 at +0x78 (end_rule off) and +0xB8..: they keep the old behaviour.


def adapter_name():
    """The selected disc's adapter as named (TAGTEAM_ADAPTER, else the installed game profile, else bt3-usa), before
    native_map folds the identity adapters into 'bt3-usa': BT4 keeps the USA address space and serial but is not the
    BT3 USA game."""
    import os
    import game_profile
    return os.environ.get('TAGTEAM_ADAPTER', '').strip() or game_profile.installed_adapter() or 'bt3-usa'


@functools.lru_cache(maxsize=None)
def natives():
    """Native addresses of the selected disc. Online play is reviewed BT3/BT4 adapters: any other adapter fails closed
    (the European and BT4 adapters here; an unknown one, e.g. the Japanese disc, already fails in native_map)."""
    if adapter_name() not in ('bt3-usa', 'bt3-pal', 'bt3-jpn', 'bt4-b14-rev2-eng'):
        raise NativeMapError('No reviewed online adapter: ' + adapter_name())
    return SimpleNamespace(
        poll_site=A(0x12BC64), status_site=A(0x122A78), raw_site=A(0x122B08),
        poll=A(0x122A38), status=A(0x296160), rawread=A(0x295FB8), sleep_vblank=A(0x26E290),
        records=A(0x333800), cri_vsync=A(0x2C9280), manager=A(0x2FEB14), battle=A(0x2FEB38),
        result=A(0x333700), pump=A(PUMP), gate_sites=tuple(A(site) for site, _, _ in GATE_SITES),
        scene_flags=A(SCENE_FLAGS), voice_start=A(VOICE_START), voice_done=A(VOICE_DONE),
        voice_start_sites=tuple(A(s) for s in VOICE_START_SITES), voice_done_sites=tuple(A(s) for s in VOICE_DONE_SITES),
        stick_float=A(STICK_FLOAT), resolver=A(PAD_RESOLVER))


def jal(target):
    return 0x0C000000 | (target >> 2)


def w_entry(channel):
    if channel not in range(CHANNELS):
        raise ValueError('gate channel must be 0..3')
    return W_CODE + W_STRIDE * channel


# ---- instruction helpers the prototype Assembler does not name ----------------------------------------------------
def _sd(a, r, off): a.i(63, r, 29, off)
def _ld(a, r, off): a.i(55, r, 29, off)
def _sll(a, rd, rt, s): a.r(0, rd, 0, rt, s)
def _srl(a, rd, rt, s): a.r(2, rd, 0, rt, s)
def _addu(a, rd, rs, rt): a.r(0x21, rd, rs, rt)
def _subu(a, rd, rs, rt): a.r(0x23, rd, rs, rt)
def _and(a, rd, rs, rt): a.r(0x24, rd, rs, rt)
def _or(a, rd, rs, rt): a.r(0x25, rd, rs, rt)
def _xor(a, rd, rs, rt): a.r(0x26, rd, rs, rt)
def _nor(a, rd, rs, rt): a.r(0x27, rd, rs, rt)
def _sltu(a, rd, rs, rt): a.r(0x2B, rd, rs, rt)
def _srlv(a, rd, rt, rs): a.r(6, rd, rs, rt)
def _andi(a, rt, rs, imm): a.i(12, rt, rs, imm)
def _sltiu(a, rt, rs, imm): a.i(11, rt, rs, imm)
def _sh(a, rt, rs, off): a.i(41, rt, rs, off)
def _sb(a, rt, rs, off): a.i(40, rt, rs, off)
def _lbu(a, rt, rs, off): a.i(36, rt, rs, off)
def _blez(a, rs, label): a.branch(6, rs, 0, label)
def _mfc0_count(a, reg): a.emit(0x40000000 | (reg << 16) | (9 << 11))   # mfc0 reg, $9 (Count)
def _mtc1(a, rt, fs): a.emit((0x11 << 26) | (0x04 << 21) | (rt << 16) | (fs << 11))
def _lwc1(a, ft, base, off): a.i(0x31, ft, base, off)
def _swc1(a, ft, base, off): a.i(0x39, ft, base, off)
def _abs_s(a, fd, fs): a.emit((0x11 << 26) | (0x10 << 21) | (fs << 11) | (fd << 6) | 0x05)
def _c_lt_s(a, fs, ft): a.emit((0x11 << 26) | (0x10 << 21) | (ft << 16) | (fs << 11) | 0x34)   # c.lt.s (EE)


def _bc1(a, true, label):
    """bc1t / bc1f to a label (delay slot nop)."""
    a.fixups.append((len(a.words), label, 'branch'))
    a.emit((0x11 << 26) | (0x08 << 21) | ((1 if true else 0) << 16))
    a.emit(0)


def _valid(a, reg, fail):
    """Skip to `fail` unless reg is an aligned EE RAM pointer (t8 scratch), as netplay_state_hash does."""
    a.li(24, 0x100000); _sltu(a, 24, reg, 24); a.branch(5, 24, 0, fail)
    a.li(24, 0x07F00000); _sltu(a, 24, reg, 24); a.branch(4, 24, 0, fail)
    _andi(a, 24, reg, 3); a.branch(5, 24, 0, fail)


# ---- POLL: replaces the battle loop's call of the native pad poll -------------------------------------------------
POLL_MASK, POLL_SCHED_DONE = 0x28, 0x2C                         # POLL's frame: the mask before SCHED(N), applied flag


def poll_code():
    n = natives()
    t0, t1, t2, t3, t4 = 8, 9, 10, 11, 12
    s0, s1, s2, s3 = 16, 17, 18, 19
    a = Assembler(POLL_CODE)
    a.addiu(29, 29, -0x30)
    for i, r in enumerate((31, s0, s1, s2, s3)):
        _sd(a, r, 8 * i)
    a.li(s0, CONTROL)
    a.lw(t0, s0, F['magic']); a.li(t1, MAGIC); a.branch(5, t0, t1, 'native')
    a.lw(t0, s0, F['enable']); a.branch(4, t0, 0, 'native')
    a.lw(t0, s0, F['mode']); a.branch(4, t0, 0, 'native')
    a.lw(t0, s0, F['state']); a.addiu(t1, 0, RUNNING); a.branch(4, t0, t1, 'running')
    a.addiu(t1, 0, ARMED); a.branch(5, t0, t1, 'ended')
    # ARMED: a host abort ends the session before it starts; otherwise wait for the director transition.
    a.lw(s1, s0, F['frame']); a.move(s2, 0)
    a.lw(t0, s0, F['abort']); a.branch(5, t0, 0, 'abort_host')
    a.lw(t1, s0, F['start_state']); a.addiu(t2, 0, -1); a.branch(4, t1, t2, 'start')
    a.lw(t2, 28, GP_DIRECTOR); a.branch(4, t2, 0, 'armed')
    a.lw(t2, t2, 0); a.lw(t3, s0, F['seen_state']); a.sw(t2, s0, F['seen_state'])
    a.branch(5, t2, t1, 'armed')
    a.lw(t1, s0, F['after_state']); a.addiu(t4, 0, -1); a.branch(4, t1, t4, 'start')
    a.branch(5, t3, t1, 'armed')
    a.label('start')
    a.addiu(t1, 0, RUNNING); a.sw(t1, s0, F['state']); a.sw(0, s0, F['frame'])
    a.lw(t1, 28, GP_FRAME); a.sw(t1, s0, F['start_game_frame'])
    a.label('running')
    a.sw(0, 29, POLL_SCHED_DONE)                                  # layout 4: SCHED(N) not applied yet
    a.lw(s1, s0, F['frame']); a.move(s2, 0)                       # s1 = N, s2 = vblanks waited
    a.lw(t0, s0, F['abort']); a.branch(5, t0, 0, 'abort_host')
    a.lw(t0, s0, F['hashing']); a.branch(4, t0, 0, 'hashed')
    a.move(4, s1); a.call(HASH_CODE)                              # the state after N running updates
    a.label('hashed')
    # The end rule: once the fight is decided in the state after N updates, stop for good (DECIDED, native polls).
    a.lw(t0, s0, F['end_rule']); a.branch(4, t0, 0, 'live')
    _andi(a, t1, t0, END_STATE); a.branch(4, t1, 0, 'end_director')
    a.lw(t2, 28, GP_DIRECTOR); _valid(a, t2, 'end_director')
    a.lw(t2, t2, 0); a.lw(t3, s0, F['end_state']); _sltu(a, t3, t2, t3); a.branch(4, t3, 0, 'decided')
    a.label('end_director')
    a.lw(t0, s0, F['end_rule'])
    _andi(a, t1, t0, END_DIRECTOR); a.branch(4, t1, 0, 'end_result')
    a.lw(t2, 28, GP_DIRECTOR); _valid(a, t2, 'end_result')
    a.lw(t2, t2, 0); a.lw(t3, s0, F['live_state']); a.branch(5, t2, t3, 'decided')     # the director left the fight
    a.label('end_result')
    _andi(a, t1, t0, END_RESULT); a.branch(4, t1, 0, 'live')
    a.li(t2, n.result); a.lw(t2, t2, 0); _andi(a, t3, t2, RESULT_WINNER_MASK); a.branch(5, t3, 0, 'decided')
    a.label('live')
    a.lw(t0, s0, F['mode']); a.addiu(t1, 0, LOCKSTEP); a.branch(5, t0, t1, 'ready')   # playback never waits
    a.lw(t0, s0, F['delay']); _sltu(a, t0, s1, t0); a.branch(5, t0, 0, 'ready')      # N < D: neutral, no wait
    a.move(4, s1); a.call(PRESENT_CODE); a.branch(5, 2, 0, 'present')
    # Stall: sleep one vblank at a time in the game's own primitive until every masked slot has frame N.
    a.label('stall')
    a.addiu(t0, 0, 1); a.sw(t0, s0, F['waiting'])
    a.li(t0, n.cri_vsync); a.lw(s3, t0, 0); a.sw(s3, s0, F['stall_start'])
    a.label('wait')
    a.call(n.sleep_vblank)
    a.li(t0, n.cri_vsync); a.lw(t0, t0, 0); _subu(a, s2, t0, s3); a.sw(s2, s0, F['stall_now'])
    a.lw(t0, s0, F['abort']); a.branch(5, t0, 0, 'abort_host')
    a.lw(t0, s0, F['max_stall']); a.branch(4, t0, 0, 'unbounded')
    _sltu(a, t0, s2, t0); a.branch(4, t0, 0, 'abort_stall')
    a.label('unbounded')
    a.move(4, s1); a.call(PRESENT_CODE); a.branch(4, 2, 0, 'wait')
    a.lw(t0, s0, F['stall_total']); _addu(a, t0, t0, s2); a.sw(t0, s0, F['stall_total'])
    a.lw(t0, s0, F['stalled_updates']); a.addiu(t0, t0, 1); a.sw(t0, s0, F['stalled_updates'])
    a.lw(t0, s0, F['stall_longest']); _sltu(a, t1, t0, s2); a.branch(4, t1, 0, 'longest')
    a.sw(s2, s0, F['stall_longest'])
    a.label('longest')
    a.sw(0, s0, F['waiting']); a.sw(0, s0, F['stall_now'])
    a.sw(0, 28, GP_VBLANK)                                        # restart the pacing as sub_264D98 does
    # Layout 4: N's sealed host writes apply BEFORE N's inputs are taken, so a slot an entry adds (a player who joins
    # a running hub) is waited for from N on and one it removes (a player who left) is not: every PC injects the
    # same slots at N. A mask change waits for the new slots' frame N (the same stall).
    a.label('present')
    a.lw(t0, s0, F['sched_enable']); a.branch(4, t0, 0, 'ready')
    a.lw(t0, s0, F['mask']); a.sw(t0, 29, POLL_MASK)
    a.move(4, s1); a.move(5, 0); a.call(SCHED_CODE)
    a.branch(5, 2, 0, 'abort_sched')
    a.addiu(t0, 0, 1); a.sw(t0, 29, POLL_SCHED_DONE)
    a.lw(t0, s0, F['mask']); a.lw(t1, 29, POLL_MASK); a.branch(4, t0, t1, 'ready')
    a.move(4, s1); a.call(PRESENT_CODE); a.branch(4, 2, 0, 'stall')
    a.label('ready')
    a.move(4, s1); a.call(AGREE_CODE)                          # the gate's agreed word for frame N
    a.lw(t0, 29, POLL_SCHED_DONE); a.branch(5, t0, 0, 'sched_done')
    a.move(4, s1); a.move(5, 0); a.call(SCHED_CODE)               # the host's writes scheduled for frame N
    a.branch(5, 2, 0, 'abort_sched')
    a.label('sched_done')
    a.lw(t0, s0, F['options']); _andi(a, t0, t0, OPT_MAILBOX); a.branch(4, t0, 0, 'no_mailbox')
    a.move(4, s1); a.addiu(5, 0, 1); a.call(MBOX_CODE)            # quad seats 2/3 from INCOMING[2/3][N]
    a.label('no_mailbox')
    a.lw(t0, s0, F['options']); _andi(a, t0, t0, OPT_SEATS); a.branch(4, t0, 0, 'no_seats')
    a.move(4, s1); a.addiu(5, 0, 1); a.call(SEAT_CODE)            # layout 4: slots 2..9 from INCOMING[s][N]
    a.label('no_seats')
    a.addiu(t0, 0, AGREED); a.sw(t0, s0, F['inject'])
    a.call(n.poll)
    a.sw(0, s0, F['inject'])
    a.addiu(s1, s1, 1); a.sw(s1, s0, F['frame'])
    a.jump('out')
    a.label('armed')                                              # before the fight: every netplay port neutral
    a.move(4, s1); a.addiu(5, 0, 1); a.call(SCHED_CODE)           # unlinked: every present entry at once
    a.lw(t0, s0, F['options']); _andi(a, t0, t0, OPT_MAILBOX); a.branch(4, t0, 0, 'armed_poll')
    a.move(4, s1); a.move(5, 0); a.call(MBOX_CODE)                # quad seats 2/3 neutral
    a.label('armed_poll')
    a.lw(t0, s0, F['options']); _andi(a, t0, t0, OPT_SEATS); a.branch(4, t0, 0, 'armed_native')
    a.move(4, s1); a.move(5, 0); a.call(SEAT_CODE)                # layout 4: slots 2..9 neutral
    a.label('armed_native')
    a.addiu(t0, 0, NEUTRAL_POLL); a.sw(t0, s0, F['inject'])
    a.call(n.poll)
    a.sw(0, s0, F['inject'])
    a.jump('out')
    a.label('decided')                                            # N and what was seen; no wait happened this pass
    a.sw(s1, s0, F['decided_frame'])
    a.li(t2, n.result); a.lw(t2, t2, 0); a.sw(t2, s0, F['decided_result'])
    a.addiu(t2, 0, -1)
    a.lw(t3, 28, GP_DIRECTOR); _valid(a, t3, 'decided_store'); a.lw(t2, t3, 0)
    a.label('decided_store')
    a.sw(t2, s0, F['decided_state'])
    a.addiu(t0, 0, DECIDED); a.sw(t0, s0, F['state'])
    a.sw(0, s0, F['waiting'])
    a.jump('ended')
    a.label('abort_stall')
    a.addiu(t0, 0, ABORT_STALL); a.jump('abort')
    a.label('abort_sched')
    a.sw(s1, s0, F['sched_fail_frame'])
    a.addiu(t0, 0, ABORT_SCHED_LATE); a.jump('abort')
    a.label('abort_host')
    a.addiu(t0, 0, ABORT_HOST)
    a.label('abort')
    a.sw(t0, s0, F['abort_reason']); a.sw(s1, s0, F['abort_frame'])
    a.addiu(t0, 0, ABORTED); a.sw(t0, s0, F['state'])
    a.sw(0, s0, F['waiting'])
    a.branch(4, s2, 0, 'ended')
    a.sw(0, 28, GP_VBLANK)                                        # the aborted stall slept: restart the pacing
    # DECIDED / ABORTED (or IDLE): with OPT_NEUTRAL_END every netplay port stays neutral for good (the result menu and
    # the pause menu are never usable: the kit decides what happens next); else the PC's own pads, natively.
    a.label('ended')
    a.lw(t0, s0, F['state']); a.addiu(t1, 0, DECIDED); a.branch(4, t0, t1, 'ended_option')
    a.addiu(t1, 0, ABORTED); a.branch(5, t0, t1, 'native')
    a.label('ended_option')
    a.lw(t0, s0, F['options']); _andi(a, t0, t0, OPT_NEUTRAL_END); a.branch(5, t0, 0, 'armed')
    a.label('native')
    a.call(n.poll)
    a.label('out')
    for i, r in enumerate((31, s0, s1, s2, s3)):
        _ld(a, r, 8 * i)
    a.addiu(29, 29, 0x30)
    a.jr()
    code = a.finish()
    assert len(code) <= RAW_CODE - POLL_CODE, hex(len(code))
    return code


# ---- POLL's leaf subroutines (layout 3 moved them out of POLL's page) ------------------------------------------------
def present_code():
    a = Assembler(PRESENT_CODE)
    t0, t1, t2, t3, t4 = 8, 9, 10, 11, 12
    # present(a0 = frame) -> v0 = 1 when every masked slot has committed that frame and (OPT_SCHED) the host's writes
    # up to that frame are sealed: sched_sealed >= frame (leaf; t0..t4).
    a.li(t0, CONTROL); a.move(2, 0)
    a.lw(t1, t0, F['sched_enable']); a.branch(4, t1, 0, 'present_sealed')
    a.lw(t1, t0, F['sched_sealed']); _sltu(a, t1, t1, 4); a.branch(5, t1, 0, 'present_done')
    a.label('present_sealed')
    a.lw(t1, t0, F['mask'])
    _andi(a, t2, 4, IN_SLOTS - 1); _sll(a, t2, t2, 4); a.li(t3, INCOMING + 8); _addu(a, t2, t2, t3)
    a.addiu(t4, 4, 1); a.addiu(2, 0, 1)
    a.label('present_slot')
    a.branch(4, t1, 0, 'present_done')
    _andi(a, t3, t1, 1); a.branch(4, t3, 0, 'present_next')
    a.lw(t3, t2, 0); a.branch(4, t3, t4, 'present_next')
    a.move(2, 0); a.jump('present_done')
    a.label('present_next')
    _srl(a, t1, t1, 1); a.li(t3, SLOT_BYTES); _addu(a, t2, t2, t3); a.jump('present_slot')
    a.label('present_done')
    a.jr()
    code = a.finish()
    assert PRESENT_CODE + len(code) <= AGREE_CODE, hex(len(code))
    return code


def agree_code():
    a = Assembler(AGREE_CODE)
    t0, t1, t2, t3, t4 = 8, 9, 10, 11, 12
    # agree(a0 = N) -> CONTROL.gate_agreed (leaf; t0..t9, a1). Per channel byte c: seq + 1 when every masked slot's
    # committed INCOMING[s][N].aux byte c equals seq + 1 (mod 256), else seq; N < D or a missing entry: seq.
    t5, t6, t7, t8, t9, a1 = 13, 14, 15, 24, 25, 5
    a.li(t0, CONTROL); a.lw(t1, t0, F['gate_seq'])
    a.li(t2, 0x7F7F7F7F); _and(a, t3, t1, t2); a.li(t2, 0x01010101); _addu(a, t3, t3, t2)
    a.li(t2, 0x80808080); _and(a, t4, t1, t2); _xor(a, t3, t3, t4)        # t3 = seq + 1 in every byte, no carries
    # Layout 3: the voice byte agrees on the count itself (target = seq), its 'not agreed' value is seq + 1; the W
    # bytes agree on seq + 1 and fall back to seq. a2 = the fallback word, t3 = the target word.
    a.li(t2, 0xFF << (8 * VOICE_CHANNEL)); _and(a, t4, t3, t2); _and(a, t5, t1, t2)   # t4 = inc voice, t5 = seq voice
    _nor(a, t2, t2, 0); _and(a, 6, t1, t2); _or(a, 6, 6, t4)                          # a2 = seq | inc voice
    _and(a, t3, t3, t2); _or(a, t3, t3, t5)                                           # t3 = inc | seq voice
    a.lw(t5, t0, F['delay']); _sltu(a, t5, 4, t5); a.branch(5, t5, 0, 'agree_none')
    a.lw(t6, t0, F['mask'])
    _andi(a, t7, 4, IN_SLOTS - 1); _sll(a, t7, t7, 4); a.li(t8, INCOMING); _addu(a, t7, t7, t8)
    a.move(t9, 0); a.addiu(a1, 4, 1)                              # t9 = differing bits, a1 = the tag of frame N
    a.label('agree_slot')
    a.branch(4, t6, 0, 'agree_mix')
    _andi(a, t8, t6, 1); a.branch(4, t8, 0, 'agree_next')
    a.lw(t8, t7, 8); a.branch(5, t8, a1, 'agree_none')            # not committed: nothing agrees
    a.lw(t8, t7, 12); _xor(a, t8, t8, t3); _or(a, t9, t9, t8)
    a.label('agree_next')
    _srl(a, t6, t6, 1); a.li(t8, SLOT_BYTES); _addu(a, t7, t7, t8); a.jump('agree_slot')
    a.label('agree_mix')
    a.move(t4, 0)                                                 # t4 = 0xFF in every agreeing byte
    for c in range(CHANNELS):
        _srl(a, t8, t9, 8 * c); _andi(a, t8, t8, 0xFF); a.branch(5, t8, 0, f'agree_skip{c}')
        a.li(t8, 0xFF << (8 * c)); _or(a, t4, t4, t8)
        a.label(f'agree_skip{c}')
    _and(a, t5, t3, t4); _nor(a, t4, t4, 0); _and(a, t6, 6, t4); _or(a, t5, t5, t6)
    a.sw(t5, t0, F['gate_agreed']); a.jr()
    a.label('agree_none')
    a.sw(6, t0, F['gate_agreed']); a.jr()
    code = a.finish()
    assert AGREE_CODE + len(code) <= CODE2_END, hex(len(code))
    return code


# ---- RAW: replaces sub_122A38's raw read; s1 = record, s2 = port index, a1 = record+0x114 ------------------------------
def sched_code():
    """sched(a0 = N, a1 = any) -> v0 = 1 when an entry for an earlier frame is still pending (ABORT_SCHED_LATE).
    Applies, in seq order, every ring entry whose seq is sched_next_seq and whose tag is N + 1 (a1 = 0), or every
    present one (a1 != 0: not RUNNING). Leaf; t0..t9, a2, a3."""
    t0, t1, t2, t3, t4, t5, t6, t7, t8, t9, a2, a3 = 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 6, 7
    a = Assembler(SCHED_CODE)
    a.li(t0, CONTROL); a.move(2, 0)
    a.lw(t1, t0, F['sched_enable']); a.branch(4, t1, 0, 'sched_out')
    a.addiu(a3, 4, 1)                                             # a3 = the tag of frame N
    a.label('sched_entry')
    a.lw(t1, t0, F['sched_next_seq'])
    _andi(a, t2, t1, SCHED_ENTRIES - 1); _sll(a, t2, t2, 9); a.li(t3, SCHED); _addu(a, t2, t2, t3)
    a.lw(t3, t2, 0); a.branch(4, t3, 0, 'sched_out')              # empty
    a.lw(t4, t2, 4); a.branch(5, t4, t1, 'sched_out')             # an older entry (already applied) or not written yet
    a.branch(5, 5, 0, 'sched_apply')                              # unlinked: apply whatever is there
    a.branch(4, t3, a3, 'sched_apply')
    _sltu(a, t4, t3, a3); a.branch(4, t4, 0, 'sched_out')         # a later frame's entry: not yet
    a.addiu(2, 0, 1); a.jump('sched_out')                         # an earlier frame's entry still pending: late
    a.label('sched_apply')
    a.lw(t5, t2, 8); a.addiu(t6, t2, 16)                          # t5 = count, t6 = the first write
    _sltiu(a, t4, t5, SCHED_WRITES + 1); a.branch(5, t4, 0, 'sched_write')
    a.move(t5, 0)                                                 # a malformed count applies nothing
    a.label('sched_write')
    a.branch(4, t5, 0, 'sched_done')
    a.lw(t7, t6, 0); _valid(a, t7, 'sched_skip')
    a.lw(t8, t6, 4); a.lw(t9, t6, 8); a.lw(a2, t7, 0)
    _nor(a, t4, t9, 0); _and(a, a2, a2, t4); _and(a, t8, t8, t9); _or(a, a2, a2, t8)
    a.sw(a2, t7, 0)
    a.label('sched_skip')
    a.addiu(t6, t6, 12); a.addiu(t5, t5, -1); a.jump('sched_write')
    a.label('sched_done')
    a.addiu(t1, t1, 1); a.sw(t1, t0, F['sched_next_seq'])
    a.jump('sched_entry')
    a.label('sched_out')
    a.jr()
    code = a.finish()
    assert SCHED_CODE + len(code) <= CODE2_END, hex(len(code))
    return code


def sched_entry(seq, frame, writes):
    """One SCHED ring entry (bytes, SCHED_ENTRY long) and its address: writes = [(address, value, mask)] applied at the
    POLL of `frame` (address word aligned, at most SCHED_WRITES)."""
    writes = list(writes)
    if not 0 < len(writes) <= SCHED_WRITES:
        raise ValueError(f'a scheduled entry holds 1..{SCHED_WRITES} writes')
    body = bytearray(SCHED_ENTRY)
    struct.pack_into('<3I', body, 4, seq & 0xFFFFFFFF, len(writes), 0)
    for i, (address, value, mask) in enumerate(writes):
        if address & 3 or not 0x100000 <= address < 0x07F00000:
            raise ValueError(f'scheduled write address {address:#x} is not an aligned EE RAM word')
        struct.pack_into('<3I', body, 16 + 12 * i, address, value & 0xFFFFFFFF, mask & 0xFFFFFFFF)
    struct.pack_into('<I', body, 0, frame + 1)
    return SCHED + (seq % SCHED_ENTRIES) * SCHED_ENTRY, bytes(body)


def raw_code():
    n = natives()
    t0, t1, t2, t3, t4, t5, t6, t7, t8, t9 = 8, 9, 10, 11, 12, 13, 14, 15, 24, 25
    s0, s2, s3 = 16, 18, 19
    a = Assembler(RAW_CODE)
    a.addiu(29, 29, -0x20)
    _sd(a, 31, 0); _sd(a, s0, 8); _sd(a, s3, 16)
    a.move(s0, 5)                                                 # the 18-byte buffer
    a.li(t0, CONTROL); a.lw(t1, t0, F['inject']); a.branch(4, t1, 0, 'read')
    _sltiu(a, t1, s2, PORTS); a.branch(4, t1, 0, 'read')
    # A physical read that writes fewer bytes must never leave the previous agreed frame in the capture.
    a.li(t1, NEUTRAL_LO); a.sw(t1, s0, 0); a.li(t1, NEUTRAL_HI); a.sw(t1, s0, 4)
    a.label('read')
    a.call(n.rawread)                                             # the real read: this machine's physical pad
    a.move(s3, 2)
    a.li(t0, CONTROL); a.lw(t1, t0, F['inject']); a.branch(4, t1, 0, 'done')
    _sltiu(a, t2, s2, PORTS); a.branch(4, t2, 0, 'done')
    a.addiu(t2, 0, AGREED); a.branch(5, t1, t2, 'neutral')       # armed: neutral, nothing captured
    a.lw(t2, t0, F['frame'])                                      # t2 = N
    # Capture: the physical capture port -> OUTGOING[(N + D) & 255] (neutral when the read failed), aux = gate_local.
    a.lw(t3, t0, F['capture_port']); a.branch(5, t3, s2, 'inject')
    a.lw(t3, t0, F['delay']); _addu(a, t3, t3, t2)                # t3 = N + D
    _andi(a, t4, t3, OUT_SLOTS - 1); _sll(a, t4, t4, 4); a.li(t1, OUTGOING); _addu(a, t4, t4, t1)
    _blez(a, s3, 'capture_neutral')
    a.lw(t5, s0, 0); a.lw(t6, s0, 4); a.jump('capture_store')
    a.label('capture_neutral')
    a.li(t5, NEUTRAL_LO); a.li(t6, NEUTRAL_HI)
    a.label('capture_store')
    a.lw(t9, t0, F['gate_local'])                                 # t9 = this machine's gate bytes (the aux word)
    a.sw(t5, t4, 0); a.sw(t6, t4, 4); a.sw(t9, t4, 12)
    a.addiu(t7, t3, 1); a.sw(t7, t4, 8)                           # commit tag last
    a.lw(t7, t0, F['captures']); a.addiu(t7, t7, 1); a.sw(t7, t0, F['captures'])
    # Lockstep self feed: the same bytes and aux become this machine's agreed input for its slot at N + D.
    a.lw(t7, t0, F['self_feed']); a.branch(4, t7, 0, 'inject')
    a.lw(t7, t0, F['mode']); a.addiu(t8, 0, LOCKSTEP); a.branch(5, t7, t8, 'inject')
    a.lw(t7, t0, F['local_slot']); _sltiu(a, t8, t7, SLOTS); a.branch(4, t8, 0, 'inject')
    _sll(a, t7, t7, SLOT_SHIFT); a.li(t8, INCOMING); _addu(a, t7, t7, t8)
    _andi(a, t8, t3, IN_SLOTS - 1); _sll(a, t8, t8, 4); _addu(a, t7, t7, t8)
    a.sw(t5, t7, 0); a.sw(t6, t7, 4); a.sw(t9, t7, 12)
    a.addiu(t8, t3, 1); a.sw(t8, t7, 8)                           # commit tag last
    a.label('inject')
    a.lw(t3, t0, F['delay']); _sltu(a, t3, t2, t3); a.branch(5, t3, 0, 'neutral')     # N < D
    a.lw(t3, t0, F['mask']); _srlv(a, t3, t3, s2); _andi(a, t3, t3, 1); a.branch(4, t3, 0, 'neutral')
    _sll(a, t4, s2, SLOT_SHIFT); a.li(t1, INCOMING); _addu(a, t4, t4, t1)
    _andi(a, t3, t2, IN_SLOTS - 1); _sll(a, t3, t3, 4); _addu(a, t4, t4, t3)
    a.lw(t3, t4, 8); a.addiu(t5, t2, 1); a.branch(5, t3, t5, 'missing')
    a.lw(t5, t4, 0); a.sw(t5, s0, 0); a.lw(t5, t4, 4); a.sw(t5, s0, 4)
    a.jump('clear')
    a.label('missing')
    a.lw(t3, t0, F['missing']); a.addiu(t3, t3, 1); a.sw(t3, t0, F['missing'])
    a.label('neutral')
    a.li(t5, NEUTRAL_LO); a.sw(t5, s0, 0); a.li(t5, NEUTRAL_HI); a.sw(t5, s0, 4)
    a.label('clear')
    a.sw(0, s0, 8); a.sw(0, s0, 12); _sh(a, 0, s0, 16)            # the rest of the 18-byte buffer
    a.addiu(s3, 0, 18)                                            # the read length the savestate stores (+0x128)
    a.label('done')
    a.move(2, s3)
    _ld(a, 31, 0); _ld(a, s0, 8); _ld(a, s3, 16)
    a.addiu(29, 29, 0x20)
    a.jr()
    code = a.finish()
    assert len(code) <= STATUS_CODE - RAW_CODE, hex(len(code))
    return code


# ---- STATUS: replaces sub_122A38's status call; s1 = record, s2 = port index, a0 = port handle -----------------------
def status_code():
    n = natives()
    t0, t1 = 8, 9
    s3 = 19
    a = Assembler(STATUS_CODE)
    a.addiu(29, 29, -0x10)
    _sd(a, 31, 0); _sd(a, s3, 8)
    a.call(n.status)                                              # keep the pad library serviced
    a.move(s3, 2)
    a.li(t0, CONTROL); a.lw(t1, t0, F['inject']); a.branch(4, t1, 0, 'done')   # only inside a netplay poll
    _sltiu(a, t1, 18, PORTS); a.branch(4, t1, 0, 'done')
    a.addiu(t1, 0, 2); a.sw(t1, 17, 0x108)                        # state 'ready': the raw read comes next
    a.addiu(s3, 0, 1)                                             # status 1 = connected (stored to +0x104)
    a.label('done')
    a.move(2, s3)
    _ld(a, 31, 0); _ld(a, s3, 8)
    a.addiu(29, 29, 0x10)
    a.jr()
    code = a.finish()
    assert len(code) <= HASH_CODE - STATUS_CODE, hex(len(code))
    return code


# ---- HASH: HASH(a0 = N) writes HASHES[N & 255] (the netplay_state_hash walker as a subroutine) -----------------------
HASH_SAVED = (16, 17, 18, 19, 20, 21, 22, 23, 31)
HASH_FRAME = 0x50
assert len(HASH_SAVED) * 8 <= HASH_FRAME and HASH_FRAME % 16 == 0


def hash_code():
    import fresh_team_combat as core
    import netplay_state_hash as nh
    n = natives()
    a = Assembler(HASH_CODE)
    a.addiu(29, 29, -0x50)
    for index, reg in enumerate(HASH_SAVED):
        _sd(a, reg, index * 8)
    _mfc0_count(a, 20)                                            # s4 = start Count
    a.move(17, 4)                                                 # s1 = N
    _andi(a, 8, 17, HASH_SLOTS - 1); _sll(a, 8, 8, 6); a.li(9, HASHES); _addu(a, 18, 9, 8)   # s2 = entry
    for offset in range(0, HASH_ENTRY, 4):
        a.sw(0, 18, offset)
    # This update's fighters: the mod's captured actors while its mode block is live, else the native pair.
    a.li(6, ACTOR_LIST); a.move(7, 0)                             # a2 = list cursor, a3 = listed
    a.li(13, core.MODE); a.lw(14, 13); a.addiu(15, 0, 1); a.branch(5, 14, 15, 'native_list')
    a.lw(23, 13, 4); _sltiu(a, 14, 23, ACTOR_MAX + 1); a.branch(4, 14, 0, 'list_done')
    a.move(22, 0)
    a.label('mod_loop'); a.branch(4, 22, 23, 'list_done')
    _sll(a, 13, 22, 2); a.li(14, core.POINTERS); _addu(a, 13, 13, 14); a.lw(4, 13)
    _valid(a, 4, 'mod_next')
    a.sw(4, 6); a.addiu(6, 6, 4); a.addiu(7, 7, 1)
    a.label('mod_next'); a.addiu(22, 22, 1); a.jump('mod_loop')
    a.label('native_list')
    a.li(13, n.manager); a.lw(14, 13); _valid(a, 14, 'list_done')
    a.lw(23, 14); _sltiu(a, 13, 23, ACTOR_MAX + 1); a.branch(4, 13, 0, 'list_done')
    a.lw(4, 14, 4); a.move(22, 0)
    a.label('native_loop'); a.branch(4, 22, 23, 'list_done')
    _valid(a, 4, 'list_done')
    a.sw(4, 6); a.addiu(6, 6, 4); a.addiu(7, 7, 1)
    a.li(13, 0x1600); _addu(a, 4, 4, 13); a.addiu(22, 22, 1); a.jump('native_loop')
    a.label('list_done')
    a.li(13, ACTOR_COUNT); a.sw(7, 13)
    a.move(21, 0)                                                 # s5 = words hashed
    a.li(19, TABLE)                                               # s3 = descriptor
    a.label('desc')
    a.lw(8, 19); a.branch(4, 8, 0, 'desc_done')
    _andi(a, 9, 8, 0xFF)                                          # t1 = kind
    _srl(a, 10, 8, 8); _andi(a, 10, 10, 7); _sll(a, 10, 10, 2)
    _addu(a, 25, 18, 10); a.addiu(25, 25, 16)                     # t9 = class slot
    a.lw(2, 25)                                                   # v0 = running class hash
    a.lw(6, 19, 4); a.lw(7, 19, 8); a.lw(11, 19, 12)              # a2 address, a3 offset, t3 words
    for kind, label in ((nh.DIRECT, 'k_direct'), (nh.INDIRECT, 'k_indirect'), (nh.ACTORS, 'k_actors'),
                        (nh.ACTOR_ROWS, 'k_rows'), (nh.CURRENT_ROW, 'k_current')):
        a.addiu(12, 0, kind); a.branch(4, 9, 12, label)
    a.jump('store')
    a.label('k_direct')
    a.move(4, 6); a.move(5, 11); a.jump('hash', True); _addu(a, 21, 21, 11); a.jump('store')
    a.label('k_indirect')
    a.lw(4, 6); _valid(a, 4, 'store'); _addu(a, 4, 4, 7); a.move(5, 11); a.jump('hash', True)
    _addu(a, 21, 21, 11); a.jump('store')
    for kind in ('actors', 'rows', 'current'):
        a.label(f'k_{kind}')
        a.li(13, ACTOR_COUNT); a.lw(23, 13); a.move(22, 0)        # s6 = listed index, s7 = listed
        a.label(f'{kind}_loop'); a.branch(4, 22, 23, 'store')
        _sll(a, 13, 22, 2); a.li(14, ACTOR_LIST); _addu(a, 13, 13, 14); a.lw(4, 13)
        if kind == 'actors':
            _addu(a, 4, 4, 7); a.move(5, 11); a.jump('hash', True); _addu(a, 21, 21, 11)
        elif kind == 'current':
            # row = min(slot, 4); a0 = actor + ROW_BASE + row*164 + offset (164 = 128 + 32 + 4)
            a.lw(15, 4, 0x994); _sltiu(a, 14, 15, nh.ROWS); a.branch(5, 14, 0, 'current_row')
            a.addiu(15, 0, nh.ROWS - 1)
            a.label('current_row')
            _sll(a, 14, 15, 7); _sll(a, 13, 15, 5); _addu(a, 14, 14, 13); _sll(a, 13, 15, 2); _addu(a, 14, 14, 13)
            _addu(a, 4, 4, 14); a.addiu(4, 4, nh.ROW_BASE); _addu(a, 4, 4, 7); a.move(5, 11); a.jump('hash', True)
            _addu(a, 21, 21, 11)
        else:
            a.addiu(15, 4, nh.ROW_BASE); _addu(a, 15, 15, 7); a.addiu(14, 0, nh.ROWS)   # t7 row field, t6 rows left
            a.label('row_loop')
            a.move(4, 15); a.move(5, 11); a.jump('hash', True); _addu(a, 21, 21, 11)
            a.addiu(15, 15, nh.ROW_BYTES); a.addiu(14, 14, -1); a.branch(5, 14, 0, 'row_loop')
        a.addiu(22, 22, 1); a.jump(f'{kind}_loop')
    a.label('store')
    a.sw(2, 25); a.addiu(19, 19, 16); a.jump('desc')
    a.label('desc_done')
    a.move(2, 0); a.addiu(4, 18, 16); a.addiu(5, 0, 8); a.jump('hash', True)   # combined = hash of the 8 classes
    a.sw(2, 18, 4)
    a.lw(8, 28, GP_FRAME); a.sw(8, 18, 8)
    a.sw(21, 18, 12)
    a.li(8, n.battle); a.lw(4, 8); _valid(a, 4, 'no_clock'); a.lw(8, 4, 264); a.sw(8, 18, 48)
    a.label('no_clock')
    a.li(8, n.cri_vsync); a.lw(8, 8); a.sw(8, 18, 52)
    a.li(16, CONTROL); a.lw(8, 16, F['stall_total']); a.sw(8, 18, 56)
    _mfc0_count(a, 8); _subu(a, 8, 8, 20); a.sw(8, 18, 60)
    a.sw(2, 16, F['hash_last']); a.addiu(8, 17, 1); a.sw(8, 16, F['hash_tag'])
    a.sw(8, 18, 0)                                                # commit tag last
    for index, reg in enumerate(HASH_SAVED):
        _ld(a, reg, index * 8)
    a.addiu(29, 29, 0x50)
    a.jr()
    # hash: a0 words, a1 count, v0 running hash -> v0 = (v0*33) ^ word per word. t0/t1 scratch.
    a.label('hash')
    a.branch(4, 5, 0, 'hash_return')
    a.label('hash_loop')
    a.lw(8, 4); _sll(a, 9, 2, 5); _addu(a, 2, 2, 9); a.r(0x26, 2, 2, 8); a.addiu(5, 5, -1)
    a.branch(5, 5, 0, 'hash_loop'); a.words.pop(); a.addiu(4, 4, 4)      # the pointer step fills the delay slot
    a.label('hash_return')
    a.jr()
    code = a.finish()
    assert HASH_CODE + len(code) <= CONTROL, hex(len(code))
    return code


# ---- W(c): replaces a `jal 0x265298` (the native disc pump); sub_265298 takes no arguments ---------------------------
def w_code(channel=0):
    """The native IO gate of one channel (see the module text). Clobbers only v0 and t0..t7 (caller-saved: the
    handler expects nothing else across the call); a 16-byte frame holds ra."""
    n = natives()
    t0, t1, t2, t3, t4, t5, t6, t7 = 8, 9, 10, 11, 12, 13, 14, 15
    entry = w_entry(channel)
    local, seq, agreed = F['gate_local'] + channel, F['gate_seq'] + channel, F['gate_agreed'] + channel
    a = Assembler(entry)
    a.addiu(29, 29, -0x10)
    _sd(a, 31, 0)
    a.call(n.pump)                                                # r = sub_265298(): this PC's IO always moves
    a.li(t0, CONTROL)
    a.lw(t1, t0, F['magic']); a.li(t2, MAGIC); a.branch(5, t1, t2, 'native')
    a.lw(t1, t0, F['state']); a.addiu(t2, 0, RUNNING); a.branch(5, t1, t2, 'native')   # ARMED/DECIDED/ABORTED
    a.lw(t1, t0, F['gate_enable']); a.branch(4, t1, 0, 'native')
    # The blocking loader sub_2635C8 (battle restart and battle load: it never reaches POLL) runs natively. The
    # record pointer is the game's own (dereferenced unchecked by the native code); null / misaligned: not loading.
    a.lw(t1, 28, GP_SYSTEM); a.branch(4, t1, 0, 'not_loading')
    _andi(a, t2, t1, 3); a.branch(5, t2, 0, 'not_loading')
    a.lw(t1, t1, LOADER_FLAGS); _andi(a, t1, t1, LOADER_ACTIVE); a.branch(5, t1, 0, 'native')
    a.label('not_loading')
    a.li(t1, n.scene_flags); a.lw(t1, t1, 0); _andi(a, t1, t1, RESTART_FLAG); a.branch(5, t1, 0, 'native')
    _lbu(a, t3, t0, local); _lbu(a, t4, t0, seq)
    a.branch(4, 2, 0, 'check')                                    # not drained (this call)
    a.branch(5, t3, t4, 'check')                                  # already counted for this wait
    a.addiu(t3, t3, 1); _sb(a, t3, t0, local)                     # drained for wait seq + 1
    a.label('check')
    _lbu(a, t5, t0, agreed); a.addiu(t6, t4, 1); _andi(a, t6, t6, 0xFF)
    a.branch(5, t5, t6, 'closed')
    # Layout 3: agreed, but THIS PC has not drained (its aux is not part of the agreement: a spectator, a host that
    # does not play): wait in the game's vblank sleep, pumping, until it has; a host abort ends the wait.
    _lbu(a, t3, t0, local); a.branch(4, t3, t6, 'open')
    a.label('own_wait')
    a.call(n.sleep_vblank)
    a.li(t0, CONTROL); a.lw(t1, t0, F['gate_wait']); a.addiu(t1, t1, 1); a.sw(t1, t0, F['gate_wait'])
    a.lw(t1, t0, F['abort']); a.branch(5, t1, 0, 'own_done')
    a.call(n.pump)
    a.branch(4, 2, 0, 'own_wait')
    a.label('own_done')
    a.li(t0, CONTROL); _lbu(a, t4, t0, seq); a.addiu(t6, t4, 1); _andi(a, t6, t6, 0xFF)
    _sb(a, t6, t0, local)
    a.sw(0, 28, GP_VBLANK)                                        # the wait slept: restart the pacing as POLL does
    a.label('open')
    _sb(a, t6, t0, seq)                                           # every PC drained: the wait completes HERE
    a.lw(t7, t0, F['gate_opened']); a.addiu(t7, t7, 1); a.sw(t7, t0, F['gate_opened'])
    a.addiu(2, 0, 1); a.jump('native')
    a.label('closed')
    a.move(2, 0)
    a.label('native')
    _ld(a, 31, 0)
    a.addiu(29, 29, 0x10)
    a.jr()
    code = a.finish()
    assert len(code) <= W_STRIDE, hex(len(code))
    return code


def programs(previous_resolver=None):
    """[(address, bytes)] of every guest program (the lint and the tests read these). previous_resolver: where
    RESOLVE continues for an actor no slot owns (default: its own trampoline)."""
    return [(POLL_CODE, poll_code()), (RAW_CODE, raw_code()), (STATUS_CODE, status_code()), (HASH_CODE, hash_code()),
            (w_entry(0), w_code(0)), (w_entry(1), w_code(1)), (MBOX_CODE, mbox_code()), (VSTART_CODE, vstart_code()), (VQ_CODE, vq_code()),
            (PRESENT_CODE, present_code()), (AGREE_CODE, agree_code()), (SCHED_CODE, sched_code()),
            (SEAT_CODE, seat_code()),
            (RESOLVE_CODE, resolve_code(RESOLVE_TRAMP if previous_resolver is None else previous_resolver))]


# ---- SEAT(a0 = N, a1 = 1: agreed input / 0: neutral): slots 2..9 -> SEAT_PADS (layout 4) -----------------------------
def seat_code():
    """For every slot s in 2..9 that SEAT_CONTROL seats: the raw 8 bytes (INCOMING[s][N] when a1 and the slot is in
    the mask, N >= D and the entry is committed; else neutral) become the record SEAT_PADS[s - 2] the native human
    decoder reads through RESOLVE: +328 the held word (~raw16 plus the dominant stick directions at <<16 / <<20, as
    quad_controller.encode_pad), +304/+308/+312/+316 LX/LY/RX/RY (sub_1230B8(byte, 50), as the native poll), then the
    pressed edge (+336 and +340 := held & ~previous, +332 := held) and +348/+384/+388/+396/+400 := 0, exactly the
    fields quad_controller's FRAME publishes. Unseated records are left alone."""
    n = natives()
    t0, t1, t2, t3 = 8, 9, 10, 11
    s0, s1, s2, s3, s4 = 16, 17, 18, 19, 20
    a = Assembler(SEAT_CODE)
    a.addiu(29, 29, -0x40)
    for i, r in enumerate((31, s0, s1, s2, s3, s4)):
        _sd(a, r, 8 * i)
    a.li(t0, SEAT_CONTROL); a.lw(t1, t0, SF['magic']); a.li(t2, SEAT_MAGIC); a.branch(5, t1, t2, 'out')
    a.lw(t1, t0, SF['enable']); a.branch(4, t1, 0, 'out')
    a.lw(t1, t0, SF['published']); a.addiu(t1, t1, 1); a.sw(t1, t0, SF['published'])
    a.move(s0, 4); a.move(s1, 5); a.addiu(s2, 0, PORTS)            # s0 = N, s1 = agreed, s2 = slot
    a.label('seat')
    a.li(t0, SEAT_CONTROL); _sll(a, t1, s2, 2); _addu(a, t1, t1, t0); a.lw(t1, t1, SF['seats'])
    _sltiu(a, t1, t1, SLOTS); a.branch(4, t1, 0, 'next')            # not seated: the record is never read
    a.li(s3, NEUTRAL_LO); a.li(s4, NEUTRAL_HI)                    # s3/s4 = the raw 8 bytes (neutral by default)
    a.branch(4, s1, 0, 'have')
    a.li(t0, CONTROL); a.lw(t1, t0, F['mask']); _srlv(a, t1, t1, s2); _andi(a, t1, t1, 1); a.branch(4, t1, 0, 'have')
    a.lw(t1, t0, F['delay']); _sltu(a, t1, s0, t1); a.branch(5, t1, 0, 'have')
    _sll(a, t1, s2, SLOT_SHIFT); a.li(t2, INCOMING); _addu(a, t1, t1, t2)
    _andi(a, t2, s0, IN_SLOTS - 1); _sll(a, t2, t2, 4); _addu(a, t1, t1, t2)
    a.lw(t2, t1, 8); a.addiu(t3, s0, 1); a.branch(5, t2, t3, 'have')       # not committed: neutral
    a.lw(s3, t1, 0); a.lw(s4, t1, 4)
    a.label('have')
    # t3 = the record of this slot: SEAT_PADS + (s - 2) * 448 (448 = 256 + 128 + 64)
    a.addiu(t3, s2, -PORTS); _sll(a, t0, t3, 8); _sll(a, t1, t3, 7); _addu(a, t0, t0, t1); _sll(a, t1, t3, 6)
    _addu(a, t0, t0, t1); a.li(t1, SEAT_PADS); _addu(a, t3, t0, t1)
    a.sw(t3, 29, 0x38)
    # sticks: raw byte 2 RX, 3 RY, 4 LX, 5 LY -> floats at +304 LX, +308 LY, +312 RX, +316 RY
    for byte_index, field in ((4, 304), (5, 308), (2, 312), (3, 316)):
        reg, shift = (s3, 8 * byte_index) if byte_index < 4 else (s4, 8 * (byte_index - 4))
        _srl(a, 4, reg, shift); _andi(a, 4, 4, 0xFF); a.addiu(5, 0, 50)
        a.call(n.stick_float)
        a.lw(t3, 29, 0x38); _swc1(a, 0, t3, field)
    # buttons: the native held word ~raw16, plus the dominant stick directions
    a.lw(t3, 29, 0x38)
    _nor(a, t0, s3, 0); _andi(a, t0, t0, 0xFFFF)
    a.li(t1, 0x3F000000); _mtc1(a, t1, 2)                         # f2 = 0.5
    a.li(t1, 0xBF000000); _mtc1(a, t1, 3)                         # f3 = -0.5
    for xo, yo, shift in ((304, 308, 16), (312, 316, 20)):
        _lwc1(a, 4, t3, xo); _lwc1(a, 5, t3, yo)                  # f4 = x, f5 = y
        _abs_s(a, 6, 4); _abs_s(a, 7, 5)
        _c_lt_s(a, 7, 6); _bc1(a, True, f'xdom{shift}')           # |y| < |x|: the x axis decides
        _c_lt_s(a, 2, 5); _bc1(a, False, f'yneg{shift}')          # y > 0.5
        a.li(t1, 4 << shift); _or(a, t0, t0, t1); a.jump(f'dir{shift}')
        a.label(f'yneg{shift}')
        _c_lt_s(a, 5, 3); _bc1(a, False, f'dir{shift}')           # y < -0.5
        a.li(t1, 8 << shift); _or(a, t0, t0, t1); a.jump(f'dir{shift}')
        a.label(f'xdom{shift}')
        _c_lt_s(a, 2, 4); _bc1(a, False, f'xneg{shift}')          # x > 0.5
        a.li(t1, 2 << shift); _or(a, t0, t0, t1); a.jump(f'dir{shift}')
        a.label(f'xneg{shift}')
        _c_lt_s(a, 4, 3); _bc1(a, False, f'dir{shift}')           # x < -0.5
        a.li(t1, 1 << shift); _or(a, t0, t0, t1)
        a.label(f'dir{shift}')
    # held, previous, pressed edges (quad_controller FRAME's 'held' block)
    a.sw(t0, t3, 328); a.lw(t1, t3, 332); _nor(a, t1, t1, 0); _and(a, t1, t1, t0)
    a.sw(t1, t3, 336); a.sw(t1, t3, 340); a.sw(t0, t3, 332)
    for off in (348, 384, 388, 396, 400):
        a.sw(0, t3, off)
    a.label('next')
    a.addiu(s2, s2, 1); a.addiu(t0, 0, SLOTS); a.branch(5, s2, t0, 'seat')
    a.label('out')
    for i, r in enumerate((31, s0, s1, s2, s3, s4)):
        _ld(a, r, 8 * i)
    a.addiu(29, 29, 0x40)
    a.jr()
    code = a.finish()
    assert SEAT_CODE + len(code) <= RESOLVE_CODE, hex(len(code))
    return code


# ---- RESOLVE: the pad resolver A(0x1DC2A0) (a0 = actor -> v0 = its pad record) -----------------------------------------
def resolve_code(previous):
    """a0 seated (POINTERS[SEATS[s]] == a0, the mod's match block live) -> v0 = slot s's record (0/1: the native port
    records, 2..9: SEAT_PADS[s - 2]); else `j previous` with every register as the caller left it. A leaf: t0..t3,
    v0."""
    import fresh_team_combat as core
    n = natives()
    t0, t1, t2, t3 = 8, 9, 10, 11
    a = Assembler(RESOLVE_CODE)
    a.li(t0, SEAT_CONTROL); a.lw(t1, t0, SF['magic']); a.li(t2, SEAT_MAGIC); a.branch(5, t1, t2, 'previous')
    a.lw(t1, t0, SF['enable']); a.branch(4, t1, 0, 'previous')
    a.li(t1, core.MODE); a.lw(t1, t1, 0); a.addiu(t2, 0, 1); a.branch(5, t1, t2, 'previous')
    a.move(t3, 0)                                                 # t3 = slot
    a.label('slot')
    _sll(a, t1, t3, 2); _addu(a, t1, t1, t0); a.lw(t1, t1, SF['seats'])
    _sltiu(a, t2, t1, SLOTS); a.branch(4, t2, 0, 'next')
    _sll(a, t1, t1, 2); a.li(t2, core.POINTERS); _addu(a, t1, t1, t2); a.lw(t1, t1, 0)
    a.branch(4, t1, 4, 'found')
    a.label('next')
    a.addiu(t3, t3, 1); _sltiu(a, t2, t3, SLOTS); a.branch(5, t2, 0, 'slot')
    a.label('previous')
    a.jump(previous)
    a.label('found')
    a.lw(t1, t0, SF['resolved']); a.addiu(t1, t1, 1); a.sw(t1, t0, SF['resolved'])
    _sltiu(a, t2, t3, PORTS); a.branch(4, t2, 0, 'private')
    _sll(a, t0, t3, 8); _sll(a, t1, t3, 7); _addu(a, t0, t0, t1); _sll(a, t1, t3, 6); _addu(a, t0, t0, t1)
    a.li(t1, n.records); _addu(a, 2, t0, t1); a.jr()
    a.label('private')
    a.addiu(t3, t3, -PORTS)
    _sll(a, t0, t3, 8); _sll(a, t1, t3, 7); _addu(a, t0, t0, t1); _sll(a, t1, t3, 6); _addu(a, t0, t0, t1)
    a.li(t1, SEAT_PADS); _addu(a, 2, t0, t1); a.jr()
    code = a.finish()
    assert RESOLVE_CODE + len(code) <= RESOLVE_TRAMP, hex(len(code))
    return code


def seat_control(seats=(), enable=True):
    """SEAT_CONTROL: seats[s] = the physical fighter index slot s plays (None: no fighter)."""
    seats = list(seats) + [None] * (SLOTS - len(seats))
    if len(seats) != SLOTS:
        raise ValueError(f'at most {SLOTS} seats')
    used = [p for p in seats if p is not None]
    if len(set(used)) != len(used) or any(not 0 <= p < SLOTS for p in used):
        raise ValueError('every seat is a distinct physical fighter 0..9')
    blob = bytearray(SEAT_CONTROL_BYTES)
    struct.pack_into('<2I', blob, 0, SEAT_MAGIC, int(bool(enable)))
    for s, p in enumerate(seats):
        struct.pack_into('<I', blob, SF['seats'] + 4 * s, NO_SLOT if p is None else p)
    return bytes(blob)


def resolver_chain(ram):
    """(previous, [(address, bytes)]) for hooking the pad resolver: an existing `j X; nop` head continues at X (a guest
    resolver: the mod's takeover / co-op / quad pads), the native prologue is displaced into RESOLVE_TRAMP."""
    n = natives()
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    hook = n.resolver
    word = u(hook)
    if word >> 26 == 2 and u(hook + 4) == 0:
        previous = (word & 0x3FFFFFF) << 2
        if not 0x06000000 <= previous < 0x08000000 or BASE <= previous < END:
            raise ValueError(f'unreviewed pad resolver chain head {previous:08X}')
        return previous, []
    from native_map import elf_path
    from prototype import ROOT, elf_reader
    native = elf_reader(elf_path(ROOT))[2]
    original = native(hook, 8)
    if ram[hook:hook + 8] != original:
        raise ValueError(f'unknown bytes at the pad resolver {hook:X}')
    for w in struct.unpack('<2I', original):
        if w >> 26 in (1, 2, 3, 4, 5, 6, 7, 20, 21):
            raise ValueError('the native pad resolver prologue needs branch relocation')
    return RESOLVE_TRAMP, [(RESOLVE_TRAMP, original + struct.pack('<2I', (2 << 26) | ((hook + 8) >> 2), 0))]


# ---- MBOX(a0 = N, a1 = 1: agreed input / 0: neutral): quad seats 2/3 from INCOMING[2/3][N] --------------------------
def mbox_code():
    """Writes quad_controller's MAILBOX for seats 2/3 (slots 2/3 of the mask; other seats neutral) in the controller
    hub's format (<I4f: the native digital word with the dominant stick directions at <<16 (left) / <<20 (right),
    then LX, LY, RX, RY as the native poll derives them: sub_1230B8(byte, 50)), then publishes it (busy +28 = 0,
    sequence +16 += 1), so quad FRAME copies it into its private pad records in this same update on every PC.
    Nothing happens without quad_controller's magic (no three/four-human match)."""
    import quad_controller as quad
    n = natives()
    t0, t1, t2, t3 = 8, 9, 10, 11
    s0, s1, s2, s3, s4 = 16, 17, 18, 19, 20
    a = Assembler(MBOX_CODE)
    a.addiu(29, 29, -0x40)
    for i, r in enumerate((31, s0, s1, s2, s3, s4)):
        _sd(a, r, 8 * i)
    a.li(t0, quad.CONTROL); a.lw(t1, t0, 0); a.li(t2, quad.MAGIC); a.branch(5, t1, t2, 'out')
    a.move(s0, 4); a.move(s1, 5); a.addiu(s2, 0, MAILBOX_SLOTS[0])           # s0 = N, s1 = agreed, s2 = slot
    a.label('seat')
    a.li(s3, NEUTRAL_LO); a.li(s4, NEUTRAL_HI)                    # s3/s4 = the raw 8 bytes (neutral by default)
    a.branch(4, s1, 0, 'have')
    a.li(t0, CONTROL); a.lw(t1, t0, F['mask']); _srlv(a, t1, t1, s2); _andi(a, t1, t1, 1); a.branch(4, t1, 0, 'have')
    a.lw(t1, t0, F['delay']); _sltu(a, t1, s0, t1); a.branch(5, t1, 0, 'have')
    _sll(a, t1, s2, SLOT_SHIFT); a.li(t2, INCOMING); _addu(a, t1, t1, t2)
    _andi(a, t2, s0, IN_SLOTS - 1); _sll(a, t2, t2, 4); _addu(a, t1, t1, t2)
    a.lw(t2, t1, 8); a.addiu(t3, s0, 1); a.branch(5, t2, t3, 'have')       # not committed: neutral
    a.lw(s3, t1, 0); a.lw(s4, t1, 4)
    a.label('have')
    # t3 = the mailbox entry of this seat (seat - 2)
    a.addiu(t3, s2, -MAILBOX_SLOTS[0]); _sll(a, t3, t3, 5); a.li(t0, quad.MAILBOX); _addu(a, t3, t3, t0)
    a.sw(t3, 29, 0x38)
    # sticks: raw byte 2 RX, 3 RY, 4 LX, 5 LY -> floats at +4 LX, +8 LY, +12 RX, +16 RY
    for byte_index, field in ((4, 4), (5, 8), (2, 12), (3, 16)):
        reg, shift = (s3, 8 * byte_index) if byte_index < 4 else (s4, 8 * (byte_index - 4))
        _srl(a, 4, reg, shift); _andi(a, 4, 4, 0xFF); a.addiu(5, 0, 50)
        a.call(n.stick_float)
        a.lw(t3, 29, 0x38); _swc1(a, 0, t3, field)
    # buttons: the native held word ~raw16, plus the dominant stick directions
    a.lw(t3, 29, 0x38)
    _nor(a, t0, s3, 0); _andi(a, t0, t0, 0xFFFF)
    a.li(t1, 0x3F000000); _mtc1(a, t1, 2)                         # f2 = 0.5
    a.li(t1, 0xBF000000); _mtc1(a, t1, 3)                         # f3 = -0.5
    for xo, yo, shift in ((4, 8, 16), (12, 16, 20)):
        _lwc1(a, 4, t3, xo); _lwc1(a, 5, t3, yo)                  # f4 = x, f5 = y
        _abs_s(a, 6, 4); _abs_s(a, 7, 5)
        _c_lt_s(a, 7, 6); _bc1(a, True, f'xdom{shift}')           # |y| < |x|: the x axis decides
        _c_lt_s(a, 2, 5); _bc1(a, False, f'yneg{shift}')          # y > 0.5
        a.li(t1, 4 << shift); _or(a, t0, t0, t1); a.jump(f'dir{shift}')
        a.label(f'yneg{shift}')
        _c_lt_s(a, 5, 3); _bc1(a, False, f'dir{shift}')           # y < -0.5
        a.li(t1, 8 << shift); _or(a, t0, t0, t1); a.jump(f'dir{shift}')
        a.label(f'xdom{shift}')
        _c_lt_s(a, 2, 4); _bc1(a, False, f'xneg{shift}')          # x > 0.5
        a.li(t1, 2 << shift); _or(a, t0, t0, t1); a.jump(f'dir{shift}')
        a.label(f'xneg{shift}')
        _c_lt_s(a, 4, 3); _bc1(a, False, f'dir{shift}')           # x < -0.5
        a.li(t1, 1 << shift); _or(a, t0, t0, t1)
        a.label(f'dir{shift}')
    a.sw(t0, t3, 0)
    a.addiu(s2, s2, 1); a.addiu(t0, 0, MAILBOX_SLOTS[-1] + 1); a.branch(5, s2, t0, 'seat')
    a.li(t0, quad.CONTROL); a.sw(0, t0, 28)                       # not busy
    a.lw(t1, t0, 16); a.addiu(t1, t1, 1); a.sw(t1, t0, 16)        # publish: a new sequence every update
    a.label('out')
    for i, r in enumerate((31, s0, s1, s2, s3, s4)):
        _ld(a, r, 8 * i)
    a.addiu(29, 29, 0x40)
    a.jr()
    code = a.finish()
    assert len(code) <= VSTART_CODE - MBOX_CODE, hex(len(code))
    return code


def _gated_running(a, fail, t0=8, t1=9, t2=10):
    """Fall to `fail` unless the core runs a lockstep fight with the voice gate on (t0 = CONTROL after)."""
    a.li(t0, CONTROL)
    a.lw(t1, t0, F['magic']); a.li(t2, MAGIC); a.branch(5, t1, t2, fail)
    a.lw(t1, t0, F['state']); a.addiu(t2, 0, RUNNING); a.branch(5, t1, t2, fail)
    a.lw(t1, t0, F['options']); _andi(a, t1, t1, OPT_VOICE); a.branch(4, t1, 0, fail)


# ---- VSTART: replaces the director's `jal 0x265E98` (start a voice line); a0..a3 pass through -------------------------
def vstart_code():
    """Counts the line (gate_seq byte 2 += 1) while a lockstep fight runs, then tail-jumps to the native start (ra
    is the director's). Leaf: t0..t2 only."""
    n = natives()
    a = Assembler(VSTART_CODE)
    _gated_running(a, 'native')
    _lbu(a, 9, 8, F['gate_seq'] + VOICE_CHANNEL); a.addiu(9, 9, 1); _sb(a, 9, 8, F['gate_seq'] + VOICE_CHANNEL)
    a.label('native')
    a.jump(n.voice_start)
    code = a.finish()
    assert len(code) <= VQ_CODE - VSTART_CODE, hex(len(code))
    return code


# ---- VQ: replaces the director's `jal 0x265F70` (is the voice line done?); a0 passes through --------------------------
def vq_code():
    """r = native answer (always asked: this PC's stream keeps being serviced); while a lockstep fight runs with the
    voice gate on: r != 0 records gate_local byte 2 := the line count, and the answer is gate_agreed byte 2 == the line
    count (every PC finished THIS line, D updates ago). Clobbers v0 and t0..t3 only; a 16-byte frame holds ra."""
    n = natives()
    a = Assembler(VQ_CODE)
    a.addiu(29, 29, -0x10)
    _sd(a, 31, 0)
    a.call(n.voice_done)
    _gated_running(a, 'out')
    _lbu(a, 11, 8, F['gate_seq'] + VOICE_CHANNEL)
    a.branch(4, 2, 0, 'check')
    _sb(a, 11, 8, F['gate_local'] + VOICE_CHANNEL)                # this PC's stream finished line `count`
    a.label('check')
    _lbu(a, 9, 8, F['gate_agreed'] + VOICE_CHANNEL); a.move(2, 0)
    a.branch(5, 9, 11, 'out')
    a.addiu(2, 0, 1)
    a.label('out')
    _ld(a, 31, 0)
    a.addiu(29, 29, 0x10)
    a.jr()
    code = a.finish()
    assert VQ_CODE + len(code) <= PRESENT_CODE, hex(len(code))
    return code


# ---- builders -----------------------------------------------------------------------------------------------------------
def hash_rows():
    """The core's own hash descriptors (netplay_state_hash format, class 1 'battle'): the gate's agreed words and
    (layout 4) the seat table and the slot mask. gate_local (machine-local) and the aux words are never hashed."""
    import netplay_state_hash as nh
    return [(nh.DIRECT, 1, CONTROL + F['gate_seq'], 0, 3, 'netplay gate: seq, agreed (channel bytes), opened count'),
            (nh.DIRECT, 1, CONTROL + F['sched_next_seq'], 0, 1, 'netplay SCHED: entries applied'),
            (nh.DIRECT, 1, CONTROL + F['mask'], 0, 1, 'netplay slot mask (a player who left drops out of it)'),
            (nh.DIRECT, 1, SEAT_CONTROL + SF['seats'], 0, SLOTS, 'netplay seats: the fighter of every input slot')]


def table_rows(profile='lean', extra_rows=()):
    """The full descriptor list a match's TABLE holds: netplay_state_hash's profile, the gate rows, then extra_rows
    (e.g. netplay_view.hash_rows())."""
    import netplay_state_hash as nh
    return nh.descriptors(profile) + hash_rows() + list(extra_rows)


def control(mode=LOCKSTEP, delay=3, local_slot=NO_SLOT, mask=0b11, state=ARMED, start_state=FIGHT, after_state=READY,
            max_stall=DEFAULT_MAX_STALL, hashing=True, self_feed=None, capture_port=0, enable=True,
            end_rule=DEFAULT_END_RULE, live_state=FIGHT, gate_enable=True, end_state=RESULT_MENU, options=0,
            sealed=0):
    if end_rule & ~(END_DIRECTOR | END_RESULT | END_STATE):
        raise ValueError('end rule bits: END_DIRECTOR (1), END_RESULT (2), END_STATE (4)')
    if options & ~(OPT_NEUTRAL_END | OPT_MAILBOX | OPT_VOICE | OPT_SCHED | OPT_SEATS):
        raise ValueError('options: OPT_NEUTRAL_END (1), OPT_MAILBOX (2), OPT_VOICE (4), OPT_SCHED (8), OPT_SEATS (16)')
    if end_rule & END_DIRECTOR and live_state == ANY:
        raise ValueError('the director end rule needs a concrete live state')
    if mode not in (OFF, PLAYBACK, LOCKSTEP):
        raise ValueError('mode must be OFF, PLAYBACK or LOCKSTEP')
    if not 0 <= delay < min(OUT_SLOTS, IN_SLOTS) // 2:
        raise ValueError('input delay out of range')
    if local_slot != NO_SLOT and local_slot not in range(SLOTS):
        raise ValueError(f'local slot must be 0..{SLOTS - 1} or NO_SLOT')
    if not mask or mask & ~((1 << SLOTS) - 1):
        raise ValueError(f'slot mask must name slots 0..{SLOTS - 1}')
    if mask & ~((1 << PORTS) - 1) and not options & (OPT_MAILBOX | OPT_SEATS):
        raise ValueError('slots 2.. need OPT_SEATS (or OPT_MAILBOX for the quad seats 2/3)')
    if mask & ~0b1111 and not options & OPT_SEATS:
        raise ValueError('slots 4..9 need OPT_SEATS')
    if capture_port not in range(PORTS):
        raise ValueError('capture port must be 0 or 1')
    if state not in (IDLE, ARMED, RUNNING):
        raise ValueError('initial state must be IDLE, ARMED or RUNNING')
    if self_feed is None:
        self_feed = mode == LOCKSTEP
    if mode == LOCKSTEP and self_feed and delay < 1:
        raise ValueError('lockstep with self feed needs an input delay of at least 1 (the capture of update N '
                         'commits frame N + D, after update N has started)')
    values = dict(magic=MAGIC, enable=int(bool(enable)), mode=mode, state=state, local_slot=local_slot, delay=delay,
                  mask=mask, capture_port=capture_port, self_feed=int(bool(self_feed)), max_stall=max_stall,
                  start_state=start_state & 0xFFFFFFFF, after_state=after_state & 0xFFFFFFFF, seen_state=ANY,
                  hashing=int(bool(hashing)), layout=LAYOUT, end_rule=end_rule, live_state=live_state & 0xFFFFFFFF,
                  decided_frame=NO_SLOT, decided_state=ANY, gate_enable=int(bool(gate_enable)), end_state=end_state,
                  options=options, sched_enable=int(bool(options & OPT_SCHED)), sched_sealed=sealed)
    blob = bytearray(CONTROL_BYTES)
    for name, value in values.items():
        struct.pack_into('<I', blob, F[name], value & 0xFFFFFFFF)
    return bytes(blob)


def _entry_of(item):
    """raw8 or (raw8, aux) -> (raw8, aux)."""
    if isinstance(item, (bytes, bytearray)):
        raw, aux = bytes(item), 0
    else:
        raw, aux = bytes(item[0]), item[1]
    if len(raw) != 8:
        raise ValueError('every input entry is 8 raw bytes')
    return raw, aux & 0xFFFFFFFF


def script_blocks(script):
    """Preloaded INCOMING rings for playback: script[frame][slot] = raw8 or (raw8, aux) (None or a missing slot = no
    entry)."""
    if len(script) > IN_SLOTS:
        raise ValueError(f'a preloaded script holds at most {IN_SLOTS} frames (got {len(script)})')
    out = []
    for slot in range(SLOTS):
        ring = bytearray(SLOT_BYTES)
        used = False
        for frame, row in enumerate(script):
            item = row[slot] if slot < len(row) else None
            if item is None:
                continue
            raw, aux = _entry_of(item)
            at = frame * IN_ENTRY
            ring[at:at + 8] = raw
            struct.pack_into('<2I', ring, at + 8, frame + 1, aux)
            used = True
        if used:
            out.append((INCOMING + slot * SLOT_BYTES, bytes(ring)))
    return out


def check_sites(ram):
    """ValueError unless the eleven call sites hold the native calls and the reservation is free."""
    n = natives()
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    for site, native in ((n.poll_site, n.poll), (n.status_site, n.status), (n.raw_site, n.rawread)) + \
            tuple((site, n.pump) for site in n.gate_sites) + \
            tuple((site, n.voice_start) for site in n.voice_start_sites) + \
            tuple((site, n.voice_done) for site in n.voice_done_sites):
        if u(site) != jal(native):
            raise ValueError(f'{site:08X} is not the native call (found {u(site):08X}); another hook owns it')
    if any(ram[BASE:END]):
        raise ValueError('netplay core reservation 0x07B00000..0x07B50000 occupied')


def blocks(ram, *, mode=LOCKSTEP, delay=3, local_slot=NO_SLOT, mask=0b11, state=ARMED, start_state=FIGHT,
           after_state=READY, max_stall=DEFAULT_MAX_STALL, hashing=True, profile='lean', self_feed=None, capture_port=0,
           script=None, enable=True, end_rule=DEFAULT_END_RULE, live_state=FIGHT, extra_rows=(), gate_enable=True,
           end_state=RESULT_MENU, options=0, sealed=0, seats=None):
    """[(address, bytes)] installing the core into a RAM image (a copy of a savestate's eeMemory.bin).

    extra_rows: more netplay_state_hash descriptors (kind, class, address, offset, words, why) appended after the
    profile's table and the gate rows, e.g. netplay_view.hash_rows() (its logic record in class 7).
    seats (OPT_SEATS): the physical fighter of every slot (default: slot s plays physical s for every masked slot);
    the pad resolver A(0x1DC2A0) is then hooked (RESOLVE ahead of whatever resolver chain the image holds)."""
    import netplay_state_hash as nh
    check_sites(ram)
    n = natives()
    table = nh.table_bytes(rows=table_rows(profile, extra_rows))
    if TABLE + len(table) > TABLE_END:
        raise ValueError('hash descriptor table too large')
    previous, extra = (None, [])
    if options & OPT_SEATS:
        previous, extra = resolver_chain(ram)
        if seats is None:
            seats = [s if mask >> s & 1 else None for s in range(SLOTS)]
    out = programs(previous) + extra + [(TABLE, table),
                        (CONTROL, control(mode, delay, local_slot, mask, state, start_state, after_state, max_stall,
                                          hashing, self_feed, capture_port, enable, end_rule, live_state, gate_enable,
                                          end_state, options, sealed))]
    if script is not None:
        out += script_blocks(script)
    out += [(n.poll_site, struct.pack('<I', jal(POLL_CODE))), (n.status_site, struct.pack('<I', jal(STATUS_CODE))),
            (n.raw_site, struct.pack('<I', jal(RAW_CODE)))]
    out += [(site, struct.pack('<I', jal(w_entry(0)))) for site in n.gate_sites]
    if options & OPT_VOICE:
        out += [(site, struct.pack('<I', jal(VSTART_CODE))) for site in n.voice_start_sites]
        out += [(site, struct.pack('<I', jal(VQ_CODE))) for site in n.voice_done_sites]
    if options & OPT_SEATS:
        out += [(SEAT_CONTROL, seat_control(seats)), (SEAT_PADS, bytes((SLOTS - PORTS) * RECORD_STRIDE)),
                (n.resolver, struct.pack('<2I', (2 << 26) | (RESOLVE_CODE >> 2), 0))]
    return out


def build_memory(ram, **options):
    """A guarded manifest (patch_state.patch applies it to a savestate copy): serial, crc, expected/data per block."""
    return dict(status='NETPLAY CORE layout 4 (native IO gate, voice gate, ten slots)', serial=SERIAL, crc=CRC,
                layout=LAYOUT,
                options={k: (v if k not in ('script', 'extra_rows') else (None if v is None else len(v)))
                         for k, v in options.items()},
                blocks=[dict(address=p, expected_hex=bytes(ram[p:p + len(b)]).hex(), data_hex=b.hex())
                        for p, b in blocks(ram, **options)])


def install(ram, **options):
    """A patched copy of a RAM image (bytes)."""
    out = bytearray(ram)
    for p, b in blocks(ram, **options):
        out[p:p + len(b)] = b
    return bytes(out)


# ---- host helpers (the PINE bridge); `client` is anything with read(address, n) / write_ranges([(address, bytes)]) ----
def parse_control(data):
    return {name: struct.unpack_from('<I', data, offset)[0] for name, offset in FIELDS if offset + 4 <= len(data)}


def read_control(client):
    return parse_control(client.read(CONTROL, CONTROL_BYTES))


def config_writes(**values):
    """[(address, bytes)] for host-owned CONTROL words (HOST_FIELDS), e.g. local_slot=1, self_feed=1."""
    out = []
    for name, value in values.items():
        if name not in HOST_FIELDS:
            raise ValueError(f'{name} is not a host-owned field')
        out.append((CONTROL + F[name], struct.pack('<I', value & 0xFFFFFFFF)))
    return out


def parse_outgoing(data):
    """{frame: (raw8, aux)} for every committed OUTGOING entry of a 4 KiB OUTGOING image."""
    out = {}
    for i in range(OUT_SLOTS):
        raw = bytes(data[i * OUT_ENTRY:i * OUT_ENTRY + 8])
        tag, aux = struct.unpack_from('<2I', data, i * OUT_ENTRY + 8)
        if tag and (tag - 1) % OUT_SLOTS == i:
            out[tag - 1] = (raw, aux)
    return out


def read_outgoing(client):
    return parse_outgoing(client.read(OUTGOING, OUT_SLOTS * OUT_ENTRY))


def incoming_address(slot, frame):
    return INCOMING + slot * SLOT_BYTES + (frame % IN_SLOTS) * IN_ENTRY


def incoming_writes(slot, frames, aux=0):
    """[(address, bytes)] publishing {frame: raw8 or (raw8, aux)} for one slot: every data word first, then each frame's
    commit tag and aux word as ONE aligned 8-byte write (PINE write64: the guest never sees a tag without its aux).
    `aux` is the aux word of the plain raw8 entries."""
    if slot not in range(SLOTS):
        raise ValueError(f'slot must be 0..{SLOTS - 1}')
    items = []
    for f, item in sorted(frames.items()):
        raw, a = _entry_of(item) if not isinstance(item, (bytes, bytearray)) else (bytes(item), aux)
        if len(raw) != 8:
            raise ValueError('raw input is 8 bytes')
        items.append((f, raw, a & 0xFFFFFFFF))
    data = [(incoming_address(slot, f), raw) for f, raw, _ in items]
    tags = [(incoming_address(slot, f) + 8, struct.pack('<2I', f + 1, a)) for f, _, a in items]
    return data + tags


def write_incoming(client, slot, frames, aux=0):
    if frames:
        client.write_ranges(incoming_writes(slot, frames, aux))


def parse_hash(data):
    words = struct.unpack('<16I', data)
    return dict(frame=words[0] - 1, combined=words[1], game_frame=words[2], words=words[3], classes=list(words[4:12]),
                clock=words[12], cri_vsync=words[13], stall_total=words[14], cycles=words[15])


def parse_hashes(data):
    """{frame: entry} for every committed HASHES entry of a 16 KiB HASHES image."""
    out = {}
    for i in range(HASH_SLOTS):
        entry = bytes(data[i * HASH_ENTRY:(i + 1) * HASH_ENTRY])
        tag = struct.unpack_from('<I', entry)[0]
        if tag and (tag - 1) % HASH_SLOTS == i:
            out[tag - 1] = parse_hash(entry)
    return out


def read_hashes(client):
    return parse_hashes(client.read(HASHES, HASH_SLOTS * HASH_ENTRY))


def gate_bytes(word):
    """The four channel bytes of a gate word (gate_local, gate_seq, gate_agreed or an aux word)."""
    return [(word >> (8 * c)) & 0xFF for c in range(CHANNELS)]


def reference_hash(ram, rows=None, profile='lean'):
    """(classes, combined, words) exactly as HASH computes them from an EE image whose TABLE holds `rows` (default: the
    profile's rows plus the gate rows)."""
    import netplay_state_hash as nh
    classes, words = nh.reference(ram, table_rows(profile) if rows is None else rows, profile)
    return classes, nh.hash_words(struct.pack('<8I', *classes)), words


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Write a guarded netplay-core manifest for a prepared-match image')
    parser.add_argument('image', type=Path, help='a .p2s savestate or a 128 MiB EE RAM image')
    parser.add_argument('out', type=Path, help='the manifest JSON to write (patch_state.py applies it)')
    parser.add_argument('--mode', choices=('lockstep', 'playback'), default='lockstep')
    parser.add_argument('--delay', type=int, default=3)
    parser.add_argument('--max-stall', type=int, default=DEFAULT_MAX_STALL)
    parser.add_argument('--start', choices=('fight', 'now'), default='fight')
    parser.add_argument('--end-rule', type=int, default=DEFAULT_END_RULE, help='0 = never decide (the old behaviour)')
    parser.add_argument('--no-gate', action='store_true', help='gate_enable = 0 (the disc pump stays native)')
    args = parser.parse_args(argv)
    from camera_snapshot import read_ram
    ram = read_ram(args.image)
    manifest = build_memory(ram, mode=LOCKSTEP if args.mode == 'lockstep' else PLAYBACK, delay=args.delay,
                            max_stall=args.max_stall, start_state=FIGHT if args.start == 'fight' else ANY,
                            end_rule=args.end_rule, gate_enable=not args.no_gate)
    args.out.write_text(json.dumps(manifest) + '\n', encoding='utf-8')
    print(f'{len(manifest["blocks"])} blocks -> {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
