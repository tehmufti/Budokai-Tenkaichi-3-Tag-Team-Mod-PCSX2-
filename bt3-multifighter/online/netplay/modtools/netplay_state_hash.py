"""Per-update desync hash for delay-based lockstep netplay (Stage A proof of concept).

Every peer runs the whole game; only inputs travel. Two games that stop being bit-identical must be caught
within a few updates, before the difference is visible, so a guest probe hashes the state that decides the
next update and stores it in a ring keyed by a deterministic update number. Hosts exchange ring entries and
compare them by key; the first differing class names what diverged.

The probe is chained in FRONT of the actor-update hook A(0x1C2A28) (once per game update, before the pad
consumers and actor updates, i.e. it sees the result of the previous update). It walks a descriptor table
(TABLE) so coverage can change without new code, and writes one 64-byte ring entry per update:

  +0 key (capacity_stage CONTROL+8: the render observer's per-update counter, identical on every peer
     after the same checkpoint; the probe's own call count where no render observer is installed, as in a
     native match), +4 probe calls, +8 EE cycles of the table walk (CP0 Count delta), +12 words
     hashed, +16..+47 eight class hashes (CLASSES), +48 sweep chunk, +52 sweep hash, +56 EE cycles with the
     sweep, +60 the battle clock's update counter (battle+264).

The optional sweep (CONTROL+12) additionally hashes one 64 KiB block of EE RAM per update, cycling through
all 128 MiB (2048 updates); it is a diagnostic for finding what differs, ~115k EE instructions per update,
never a netplay default.

What is deliberately NOT in the table (it legitimately differs per machine, or is written by a host at host
time): native pad records of local ports before injection (A(0x333800)+port*448), host mailboxes and their
tokens (quad_controller, controller_assignment, quad_menu_input), the load acknowledgement token 0x073BFF00,
native_preparation's transaction words and 8 MiB staging packet, the loading cover's control block and
buffers, the reload/body/fusion runner request/ack words and host-built workspaces, the fusion service claim
(fusion_duration CONTROL+12 carries the watcher's PID), render/GS packet arenas and telemetry counters. Class 7
('canary') hashes a few of them on purpose so a two-run comparison shows whether they differ.

Guest rules kept: 16-byte stack frame, no k0/k1, native addresses through A(). No PINE here except read_ring;
build_memory returns an ordinary guarded manifest.
"""
from native_map import A
import struct
from prototype import Assembler
import fresh_team_combat as core
import capacity_stage as cap

BASE, END = 0x06E00000, 0x06E60000
CODE = BASE
TRAMPOLINE = BASE + 0xD000   # only used when A(0x1C2A28) still holds the native prologue
TABLE = BASE + 0xE000        # up to 255 descriptors of 16 bytes, zero-terminated
CONTROL = BASE + 0xF000      # +0 magic, +4 calls, +8 enabled, +12 sweep, +16 last key
ACTOR_COUNT, ACTOR_LIST = CONTROL + 0x3C, CONTROL + 0x40   # this update's fighter list (at most 12 pointers)
RING = BASE + 0x10000
RING_ENTRIES, ENTRY = 4096, 64
SWEEP_CHUNKS, SWEEP_BYTES = 2048, 0x10000
MAGIC = 0x4E485331           # 'NHS1'
HOOK = A(0x1C2A28)
NATIVE_PROLOGUE = bytes.fromhex('f0ffbd270000b0ff')
DIRECT, INDIRECT, ACTORS, ACTOR_ROWS, CURRENT_ROW = 1, 2, 3, 4, 5
CLASSES = ('rng', 'battle', 'actor_core', 'actor_combat', 'actor_flags_camera', 'camera', 'mod_state', 'canary')
ROW_BASE, ROW_BYTES, ROWS = 0x9A4, 164, 5
SAVED = tuple(range(2, 26)) + (31,)
FRAME_BYTES = 0xD0           # 25 doublewords, rounded to 16 bytes
assert len(SAVED) * 8 <= FRAME_BYTES and FRAME_BYTES % 16 == 0
assert RING + RING_ENTRIES * ENTRY <= END


def descriptors(profile='lean'):
    """(kind, class, address, offset, words, why). USA addresses through A(); guest-owned mod state as-is.

    'lean' is the netplay default (a few thousand EE instructions per update); 'full' adds every roster row,
    the flag bytes, per-actor cameras, static tables and the class-7 canaries, for diagnosis."""
    if profile not in ('lean', 'full'):
        raise ValueError('Unknown hash profile')
    full = profile == 'full'
    import cinematic_policy as cinematic
    import team_start_gate as start
    import team_participation as participation
    import extra_reload_requests as requests
    import ffa_targeting as ffa
    import fresh_team_ai as ai
    import native_preparation as preparation
    import guest_loading_screen as cover
    impure, battle, manager = A(0x2E9808), A(0x2FEB38), A(0x2FEB14)
    cinematic_camera, camera_manager, scene = A(0x2FEBCC), A(0x2FEBD4), A(0x331DC8)
    rows = []
    add = lambda *item: rows.append(item)
    # 0 rng: every random source a game update can draw from.
    add(INDIRECT, 0, impure, 168, 2, 'newlib rand() state _impure_ptr->_rand_next (rand 0x2A9C78, 442 call sites)')
    add(DIRECT, 0, A(0x2FF060), 0, 1, 'MT19937 #3 index ($gp-21008); random(n) 0x254DE8, 65 call sites')
    add(DIRECT, 0, A(0x31DBB0), 0, 4, 'MT19937 #3 state words 0..3 (change at every 624-draw refill)')
    add(DIRECT, 0, A(0x2FEC50), 0, 1, 'MT19937 #1 index ($gp-22048)')
    add(DIRECT, 0, A(0x2FEE58), 0, 1, 'MT19937 #2 index ($gp-21528)')
    add(DIRECT, 0, ffa.CONTROL + 16, 0, 2, 'mod NPC targeting tick and private xorshift state (host-seeded)')
    # 1 battle: phase, clocks, scene flags, result, the native actor manager.
    add(INDIRECT, 1, battle, 0, 4, 'battle object phase/substate')
    add(INDIRECT, 1, battle, 264, 8, 'battle clocks (+264, +280: update counter, h/m/s/sub, remaining)')
    add(DIRECT, 1, scene + 8, 0, 1, 'scene battle mode')
    add(DIRECT, 1, scene + 36, 0, 1, 'scene split-view flag')
    add(DIRECT, 1, A(0x3337B8), 0, 1, 'scene pause/script flags (0x3900 family)')
    add(DIRECT, 1, A(0x333700), 0, 2, 'battle result winner/reason')
    add(INDIRECT, 1, manager, 600, 8, 'actor manager native reload/script-stop words (+600..+628)')
    if full:
        add(DIRECT, 1, scene + 16, 0, 1, 'scene time-limit setting')
        add(INDIRECT, 1, manager, 0, 5, 'actor manager head (count, array, flags)')
    # 2 actor core, every captured fighter (core.POINTERS, count core.MODE+4).
    add(ACTORS, 2, 0, 0x0, 16, 'identity, controller/role, side, model id; base and offset positions (+0x0..+0x3F)')
    add(ACTORS, 2, 0, 0x948, 8, 'action words (+0x948..+0x967)')
    add(ACTORS, 2, 0, 0x994, 2, 'current roster slot and row count')
    if full:
        add(ACTORS, 2, 0, 0x974, 1, 'animation')
    # 3 actor combat numbers.
    if full:
        add(ACTOR_ROWS, 3, 0, 64, 7, 'each roster row: HP, max HP, ki, max ki, blast stocks, max (5 rows)')
    else:
        add(CURRENT_ROW, 3, 0, 64, 7, 'current roster row: HP, max HP, ki, max ki, blast stocks, max')
    add(ACTORS, 3, 0, 0x1278, 4, 'CPU enable, digital input, analog inputs (after injection)')
    add(ACTORS, 3, 0, 3480, 9, 'pending HP damage, absorption, pending ki damage (+3480..+3515)')
    add(ACTORS, 3, 0, 3732, 2, 'paired-action partner')
    add(ACTORS, 3, 0, 4896, 4, 'hitstop / queued / delay')
    # 4 the per-actor camera the native AI reads (eye +1072, angles +1088), and in 'full' the flag bytes.
    add(ACTORS, 4, 0, 1072, 7, 'actor camera eye and angles (+1072..+1099)')
    if full:
        add(ACTORS, 3, 0, 5608, 3, 'combat cache')
        add(ACTORS, 4, 0, 0x1080, 22, 'actor flag bytes (+0x1080..+0x10D7, includes 0xD3/0xCC camera flags)')
    # 5 cameras.
    add(INDIRECT, 5, camera_manager, 1824 + 608, 12, 'normal camera side 0: eye, angles, viewport mode, priority')
    add(INDIRECT, 5, camera_manager, 1824 + 656 + 608, 12, 'normal camera side 1')
    add(INDIRECT, 5, cinematic_camera, 752, 1, 'cinematic animation time')
    add(INDIRECT, 5, cinematic_camera, 776, 1, 'cinematic flags')
    if full:
        add(DIRECT, 5, cinematic_camera, 0, 3, 'cinematic / active / camera-manager pointers ($gp-22180..-22172)')
        add(INDIRECT, 5, cinematic_camera, 704, 1, 'cinematic animation data')
        add(INDIRECT, 5, cinematic_camera, 768, 2, 'cinematic bound models')
        add(INDIRECT, 5, cinematic_camera, 812, 1, 'cinematic direct override')
    # 6 guest-owned mod gameplay state (deterministic guest code only).
    add(DIRECT, 6, core.TABLE, 0, 12, 'mod target table (physical ids)')
    add(DIRECT, 6, core.MODE, 0, 4, 'mod mode/count/manager/configured')
    add(DIRECT, 6, core.PAIR, 0, 2, 'pair engine enable / alias-active (0 between actor slices)')
    add(DIRECT, 6, cinematic.CONTROL, 0, 24, 'cinematic policy record (shared stop, latches)')
    if full:
        add(DIRECT, 6, core.POINTERS, 0, 12, 'mod actor pointers')
        add(DIRECT, 6, A(0x31C640), 0, 12, 'native model pointer table')
        add(DIRECT, 6, ai.CONTROL + 0x10, 0, 2, 'fresh AI frames / alive mask')
        add(DIRECT, 6, start.CONTROL, 0, 6, 'start gate')
        add(DIRECT, 6, participation.CONTROL, 0, 5, 'participation present/consumed masks')
        add(DIRECT, 6, requests.RECORDS, 0, 16 * min(requests.ROWS, 8), 'extra reload request rows (status, row data)')
        # 7 canary: host-written or timing-derived words, hashed apart so a comparison shows what differs.
        add(DIRECT, 7, A(0x333800), 0, 224, 'native pad records ports 0/1 (local input before injection)')
        add(DIRECT, 7, cap.CONTROL, 0, 16, 'render observer telemetry (packet heartbeat, arena cursors)')
        add(DIRECT, 7, preparation.CONTROL, 0, 16, 'native_preparation transaction words (host-written)')
        add(DIRECT, 7, cover.CONTROL, 0, 16, 'loading cover control (host-written, CP0 Count clock)')
    assert len(rows) < 255
    return rows


def table_bytes(rows=None, profile='lean'):
    rows = descriptors(profile) if rows is None else rows
    data = bytearray()
    for kind, cls, address, offset, words, _ in rows:
        data += struct.pack('<4I', kind | cls << 8, address, offset, words)
    return bytes(data + bytes(16))


def _mfc0_count(a, reg):
    a.emit(0x40000000 | (reg << 16) | (9 << 11))   # mfc0 reg, $9 (Count)


def _valid(a, reg, fail):
    """Skip when reg is not an aligned EE RAM pointer (t8 scratch)."""
    a.li(24, 0x100000); a.r(0x2B, 24, reg, 24); a.branch(5, 24, 0, fail)
    a.li(24, 0x07F00000); a.r(0x2B, 24, reg, 24); a.branch(4, 24, 0, fail)
    a.i(12, 24, reg, 3); a.branch(5, 24, 0, fail)


def frame_code(previous):
    """The probe; ends by jumping to `previous` (the chain's former head) with every register restored."""
    a = Assembler(CODE)
    a.addiu(29, 29, -FRAME_BYTES)
    for index, reg in enumerate(SAVED):
        a.i(63, reg, 29, index * 8)
    _mfc0_count(a, 20)                                            # s4 = start Count
    a.li(16, CONTROL); a.lw(8, 16); a.li(9, MAGIC); a.branch(5, 8, 9, 'done')
    a.lw(8, 16, 4); a.addiu(8, 8, 1); a.sw(8, 16, 4)
    a.lw(8, 16, 8); a.branch(4, 8, 0, 'done')
    # s1 = key: the render observer's update counter in a prepared match, else this probe's own call count
    # (equal on every peer that loaded the same checkpoint with the probe already in it).
    a.lw(17, 16, 4)
    a.li(8, cap.CONTROL); a.lw(9, 8); a.li(10, cap.MAGIC); a.branch(5, 9, 10, 'keyed')
    a.lw(17, 8, 8)
    a.label('keyed')
    a.i(12, 8, 17, RING_ENTRIES - 1); a.r(0, 8, 0, 8, 6); a.li(9, RING); a.r(0x21, 18, 9, 8)   # s2 = entry
    for offset in range(0, ENTRY, 4):
        a.sw(0, 18, offset)
    a.sw(17, 18, 0); a.lw(8, 16, 4); a.sw(8, 18, 4)
    # Fighter list once per update (ACTOR_LIST): the mod's captured actors when its mode block is live,
    # otherwise the native pair from the actor manager (array stride 0x1600).
    a.li(6, ACTOR_LIST); a.move(7, 0)                             # a2 = list cursor, a3 = listed
    a.li(13, core.MODE); a.lw(14, 13); a.addiu(15, 0, 1); a.branch(5, 14, 15, 'native_list')
    a.lw(23, 13, 4); a.i(11, 14, 23, 13); a.branch(4, 14, 0, 'list_done')
    a.move(22, 0)
    a.label('mod_loop'); a.branch(4, 22, 23, 'list_done')
    a.r(0, 13, 0, 22, 2); a.li(14, core.POINTERS); a.r(0x21, 13, 13, 14); a.lw(4, 13)
    _valid(a, 4, 'mod_next')
    a.sw(4, 6); a.addiu(6, 6, 4); a.addiu(7, 7, 1)
    a.label('mod_next'); a.addiu(22, 22, 1); a.jump('mod_loop')
    a.label('native_list')
    a.li(13, A(0x2FEB14)); a.lw(14, 13); _valid(a, 14, 'list_done')
    a.lw(23, 14); a.i(11, 13, 23, 13); a.branch(4, 13, 0, 'list_done')
    a.lw(4, 14, 4); a.move(22, 0)
    a.label('native_loop'); a.branch(4, 22, 23, 'list_done')
    _valid(a, 4, 'list_done')
    a.sw(4, 6); a.addiu(6, 6, 4); a.addiu(7, 7, 1)
    a.li(13, 0x1600); a.r(0x21, 4, 4, 13); a.addiu(22, 22, 1); a.jump('native_loop')
    a.label('list_done')
    a.li(13, ACTOR_COUNT); a.sw(7, 13)
    a.move(21, 0)                                                 # s5 = words hashed
    a.li(19, TABLE)                                               # s3 = descriptor
    a.label('desc')
    a.lw(8, 19); a.branch(4, 8, 0, 'desc_done')
    a.i(12, 9, 8, 0xFF)                                           # t1 = kind
    a.r(2, 10, 0, 8, 8); a.i(12, 10, 10, 7); a.r(0, 10, 0, 10, 2)
    a.r(0x21, 25, 18, 10); a.addiu(25, 25, 16)                    # t9 = class slot
    a.lw(2, 25)                                                   # v0 = running class hash
    a.lw(6, 19, 4); a.lw(7, 19, 8); a.lw(11, 19, 12)              # a2 address, a3 offset, t3 words
    for kind, label in ((DIRECT, 'k_direct'), (INDIRECT, 'k_indirect'), (ACTORS, 'k_actors'), (ACTOR_ROWS, 'k_rows'),
                        (CURRENT_ROW, 'k_current')):
        a.addiu(12, 0, kind); a.branch(4, 9, 12, label)
    a.jump('store')
    a.label('k_direct')
    a.move(4, 6); a.move(5, 11); a.jump('hash', True); a.r(0x21, 21, 21, 11); a.jump('store')
    a.label('k_indirect')
    a.lw(4, 6); _valid(a, 4, 'store'); a.r(0x21, 4, 4, 7); a.move(5, 11); a.jump('hash', True)
    a.r(0x21, 21, 21, 11); a.jump('store')
    for kind in ('actors', 'rows', 'current'):
        a.label(f'k_{kind}')
        a.li(13, ACTOR_COUNT); a.lw(23, 13); a.move(22, 0)        # s6 = listed index, s7 = listed
        a.label(f'{kind}_loop'); a.branch(4, 22, 23, 'store')
        a.r(0, 13, 0, 22, 2); a.li(14, ACTOR_LIST); a.r(0x21, 13, 13, 14); a.lw(4, 13)
        if kind == 'actors':
            a.r(0x21, 4, 4, 7); a.move(5, 11); a.jump('hash', True); a.r(0x21, 21, 21, 11)
        elif kind == 'current':
            # row = min(slot, 4); a0 = actor + ROW_BASE + row*164 + offset (164 = 128 + 32 + 4)
            a.lw(15, 4, 0x994); a.i(11, 14, 15, ROWS); a.branch(5, 14, 0, 'current_row')
            a.addiu(15, 0, ROWS - 1)
            a.label('current_row')
            a.r(0, 14, 0, 15, 7); a.r(0, 13, 0, 15, 5); a.r(0x21, 14, 14, 13); a.r(0, 13, 0, 15, 2); a.r(0x21, 14, 14, 13)
            a.r(0x21, 4, 4, 14); a.addiu(4, 4, ROW_BASE); a.r(0x21, 4, 4, 7); a.move(5, 11); a.jump('hash', True)
            a.r(0x21, 21, 21, 11)
        else:
            a.addiu(15, 4, ROW_BASE); a.r(0x21, 15, 15, 7); a.addiu(14, 0, ROWS)   # t7 row field, t6 rows left
            a.label('row_loop')
            a.move(4, 15); a.move(5, 11); a.jump('hash', True); a.r(0x21, 21, 21, 11)
            a.addiu(15, 15, ROW_BYTES); a.addiu(14, 14, -1); a.branch(5, 14, 0, 'row_loop')
        a.addiu(22, 22, 1); a.jump(f'{kind}_loop')
    a.label('store')
    a.sw(2, 25); a.addiu(19, 19, 16); a.jump('desc')
    a.label('desc_done')
    _mfc0_count(a, 8); a.r(0x23, 8, 8, 20); a.sw(8, 18, 8); a.sw(21, 18, 12)
    a.li(8, A(0x2FEB38)); a.lw(4, 8); _valid(a, 4, 'no_clock'); a.lw(8, 4, 264); a.sw(8, 18, 60)
    a.label('no_clock')
    a.lw(8, 16, 12); a.branch(4, 8, 0, 'sweep_done')
    a.i(12, 8, 17, SWEEP_CHUNKS - 1); a.sw(8, 18, 48); a.r(0, 4, 0, 8, 16)
    a.li(9, 0x80000); a.r(0x2B, 9, 4, 9); a.branch(5, 9, 0, 'sweep_skip')   # the kernel's first 512 KiB: not read
    a.li(5, SWEEP_BYTES // 4); a.move(2, 0); a.jump('hash', True); a.sw(2, 18, 52)
    a.label('sweep_skip')
    _mfc0_count(a, 8); a.r(0x23, 8, 8, 20); a.sw(8, 18, 56)
    a.label('sweep_done')
    a.sw(17, 16, 16)
    a.label('done')
    for index, reg in enumerate(SAVED):
        a.i(55, reg, 29, index * 8)
    a.addiu(29, 29, FRAME_BYTES)
    a.jump(previous)
    # hash: a0 words, a1 count, v0 running hash -> v0 = (v0*33) ^ word per word. t0/t1 scratch.
    a.label('hash')
    a.branch(4, 5, 0, 'hash_return')
    a.label('hash_loop')
    a.lw(8, 4); a.r(0, 9, 0, 2, 5); a.r(0x21, 2, 2, 9); a.r(0x26, 2, 2, 8); a.addiu(5, 5, -1)
    a.branch(5, 5, 0, 'hash_loop'); a.words.pop(); a.addiu(4, 4, 4)     # the pointer step fills the delay slot
    a.label('hash_return')
    a.jr()
    code = a.finish()
    assert CODE + len(code) <= TRAMPOLINE
    return code


def hash_words(data, h=0):
    """The guest hash over little-endian words (reference for tests and host checks)."""
    for (word,) in struct.iter_unpack('<I', data):
        h = (((h * 33) & 0xFFFFFFFF) ^ word) & 0xFFFFFFFF
    return h


def fighters(ram):
    """The guest's per-update fighter list: captured actors when the mod mode block is live, else the native pair."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    valid = lambda p: 0x100000 <= p < 0x07F00000 and not p & 3
    listed = []
    if u(core.MODE) == 1:
        count = u(core.MODE + 4)
        if count < 13:
            listed = [p for p in (u(core.POINTERS + 4 * i) for i in range(count)) if valid(p)]
        return listed
    manager = u(A(0x2FEB14))
    if not valid(manager) or u(manager) >= 13:
        return listed
    p = u(manager + 4)
    for _ in range(u(manager)):
        if not valid(p):
            break
        listed.append(p)
        p += 0x1600
    return listed


def reference(ram, rows=None, profile='lean'):
    """Class hashes and word count exactly as the guest computes them from an EE image."""
    rows = descriptors(profile) if rows is None else rows
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    valid = lambda p: 0x100000 <= p < 0x07F00000 and not p & 3
    hashes, words = [0] * 8, 0
    actors = fighters(ram)
    for kind, cls, address, offset, n, _ in rows:
        spans = []
        if kind == DIRECT:
            spans = [address]
        elif kind == INDIRECT:
            p = u(address)
            spans = [p + offset] if valid(p) else []
        else:
            for p in actors:
                if kind == ACTORS:
                    spans.append(p + offset)
                elif kind == CURRENT_ROW:
                    spans.append(p + ROW_BASE + min(u(p + 0x994), ROWS - 1) * ROW_BYTES + offset)
                else:
                    spans += [p + ROW_BASE + offset + r * ROW_BYTES for r in range(ROWS)]
        for at in spans:
            hashes[cls] = hash_words(ram[at:at + 4 * n], hashes[cls])
            words += n
    return hashes, words


def chain_previous(ram):
    """(previous, trampoline blocks): the current head of the A(0x1C2A28) chain."""
    head = struct.unpack_from('<2I', ram, HOOK)
    if head[0] >> 26 == 2 and head[1] == 0:
        return (head[0] & 0x3FFFFFF) << 2, []
    if bytes(ram[HOOK:HOOK + 8]) == NATIVE_PROLOGUE:
        a = Assembler(TRAMPOLINE)
        a.emit(head[0]); a.emit(head[1]); a.jump(HOOK + 8)
        return TRAMPOLINE, [(TRAMPOLINE, a.finish())]
    raise ValueError('Unknown actor-update hook head')


def build_memory(ram, sweep=False, enabled=True, profile='lean'):
    if any(ram[BASE:END]):
        raise ValueError('Netplay hash reservation occupied')
    previous, extra = chain_previous(ram)
    if not 0x100000 <= previous < 0x08000000:
        raise ValueError('Invalid chain predecessor')
    control = struct.pack('<5I', MAGIC, 0, int(bool(enabled)), int(bool(sweep)), 0)
    pieces = extra + [(CODE, frame_code(previous)), (TABLE, table_bytes(profile=profile)), (CONTROL, control),
                      (HOOK, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0))]
    return dict(status='NETPLAY STATE HASH PROBE', previous=previous, profile=profile,
                blocks=[dict(address=p, expected_hex=bytes(ram[p:p + len(d)]).hex(), data_hex=d.hex()) for p, d in pieces])


def parse_entry(data):
    words = struct.unpack('<16I', data)
    return dict(key=words[0], calls=words[1], cycles=words[2], words=words[3], classes=list(words[4:12]),
                chunk=words[12], sweep=words[13], cycles_total=words[14], clock=words[15])


def read_ring(p):
    """Every written ring entry of a live game (PINE reader), keyed by update number."""
    data = p.read(RING, RING_ENTRIES * ENTRY)
    entries = {}
    for index in range(RING_ENTRIES):
        entry = parse_entry(data[index * ENTRY:(index + 1) * ENTRY])
        if entry['calls'] and entry['key'] & (RING_ENTRIES - 1) == index:
            entries[entry['key']] = entry
    return entries
