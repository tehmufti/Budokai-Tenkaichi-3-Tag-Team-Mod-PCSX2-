"""Hold every grabbed fighter in its own grab, however many grabs run at once.

The game holds a thrown fighter in place once per update in one function, 1D7C30 (called only from 1C2D20). It
scans every fighter for the 'holding' flag 0x8B (set each update by the thrower's handler: throw actions 183/185/
187, the rush-grab attackers 298..303) and the 'held' flag 0x97 (the thrown fighter: 184/186/188, 307..309,
313..315), keeps the LAST fighter carrying each, and moves that one victim so its grab bone sits on the thrower's
hand (or, with 0x9B, the thrower onto the victim), then marks the victim held (flag 0x23). A one-on-one game never
has more than one grab, so that is enough there.

With the mod's extra fighters two grabs can run at once (an extra throwing an extra while a leader throws someone,
or any two rush grabs). Only the last pair is held. Every other victim misses flag 0x23, so its own handler (1FC918
for 184/186) takes the release path: 1FC2B0 plus a velocity of -(actor+0xA0), backwards, re-applied every update.
It slides away at about 9 units per update while its grab animation, and the thrower's hits, play on: the glitch
players saw as 'the grabbed fighter slides backwards while still being hit'. When the indices cross, the last
victim is even pinned to the other pair's thrower and teleports between them.

This replaces that call with a pair-aware one. It scans the same fighters with the same native helpers
(1DC168/1DC178 counts and getters, 1DC2C0 'gone', 1DAC78 flags), then pairs each held fighter with the thrower
that is actually holding it: a rush grab's own pair fields (3732/3736, the same on both fighters), then the mod's
resolver (the live throw record of extra_throws, the rush pair, else the lock-on target) asked from the victim and
from each thrower, and only when nothing names a free thrower, the closest free thrower within reach (NEAR), so a
victim already let go is never pulled back. Each pair runs the game's own hold code: a stub rebuilds 1D7C30's exact stack frame
and enters it at 1D7CBC with s3 = thrower and s2 = victim, so bone choice, the 0x34 scale, the 0x9B direction,
the root refresh and flag 0x23 are the native instructions. One thrower and one victim (every one-on-one grab)
goes straight to that same native code, as before. Outside an active team match the call goes to 1D7C30 untouched.

Guest code only: it reads guest RAM, never host time, so a match plays out the same everywhere (online lockstep).
Always installed in team matches (a bug fix, not a setting).
"""
import struct

from native_map import A, CRC, FLAG, SERIAL, elf_path
from prototype import Assembler, ROOT, elf_reader
import battle_mode_policy as policy
import fresh_team_combat as core

CODE, END = 0x0696C000, 0x0696D000
ENTRY, ATTACH = CODE, CODE + 0xC00
CONTROL = CODE + 0xE00
MAGIC, VERSION = 0x47524231, 1          # 'GRB1'
NEAR = 40.0                             # pass 4 reach (units; a held victim is ~8-13 from its thrower)
# CONTROL: +0 magic, +4 version, +8 scanned count, +12 pass-4 best victim (scratch); counters +16 multi-grab updates, +20 pairs held by this code, +24 victims left
# unpaired, +28 resolver pairings, +32 nearest-thrower fallbacks; scratch lists (rebuilt every update) +0x40
# throwers, +0x80 victims, +0xC0 thrower-used marks, +0x100 victim-held marks (ENGINE_ACTORS words each).
C = dict(magic=0, version=4, count=8, best=12, multi=16, held=20, unpaired=24, resolved=28, nearest=32)
THROWERS, VICTIMS, USED, DONE = CONTROL + 0x40, CONTROL + 0x80, CONTROL + 0xC0, CONTROL + 0x100
SLOTS = policy.ENGINE_ACTORS
assert USED + 4 * SLOTS <= DONE and DONE + 4 * SLOTS <= END

SITE = A(0x1C2D20)                       # the only call of 1D7C30: jal 1D7C30 (in the per-update fighter loop)
HOLD, BODY = A(0x1D7C30), A(0x1D7CBC)    # the native hold function and its body after the scan
COUNT, GETTER, GONE, HAS_FLAG = A(0x1DC168), A(0x1DC178), A(0x1DC2C0), A(0x1DAC78)
HOLDING, HELD = FLAG(0x8B), FLAG(0x97)
NATIVE = elf_reader(elf_path(ROOT))[2]
JAL = lambda target: struct.pack('<I', (3 << 26) | (target >> 2))
U32 = lambda data, i=0: struct.unpack_from('<I', data, 4 * i)[0]

# 1D7C30's prologue (stack frame 0x70; s0..s6 and ra in these slots) and the first word of its body: the stub
# depends on exactly this layout, so the build refuses any other executable.
PROLOGUE = (0x27BDFF90, 0xFFB10038, 0x0000882D, 0xFFB20040, 0x0000902D, 0xFFB30048, 0x0000982D,
            0xFFB00030, 0xFFB40050, 0xFFB50058, 0xFFB60060)
SAVES = ((17, 0x38), (18, 0x40), (19, 0x48), (16, 0x30), (20, 0x50), (21, 0x58), (22, 0x60), (31, 0x68))
BODY_FIRST = 0x1260                    # beqz s3, 1D7E40 (the body's 'no thrower' exit), upper half
DEPENDENCIES = ((HOLD, 0x238),)         # the whole native hold function: the stub enters it mid-way


def _sd(a, reg, off): a.i(63, reg, 29, off)
def _ld(a, reg, off): a.i(55, reg, 29, off)
def _lwc1(a, ft, base, off): a.i(49, ft, base, off)
def _fop(a, fn, fd, fs, ft): a.emit((17 << 26) | (16 << 21) | (ft << 16) | (fs << 11) | (fd << 6) | fn)


def attach_code():
    """ATTACH(a0 thrower, a1 victim): 1D7C30's own frame, then its body at 1D7CBC; it returns to our caller."""
    a = Assembler(ATTACH)
    a.addiu(29, 29, -0x70)
    for reg, off in SAVES:
        _sd(a, reg, off)
    a.move(19, 4); a.move(18, 5)
    a.jump(BODY)
    data = a.finish(); assert len(data) <= CONTROL - ATTACH; return data


def _bump(a, key):
    a.li(8, CONTROL + C[key]); a.lw(9, 8); a.addiu(9, 9, 1); a.sw(9, 8)


def _resolve(a, actor):
    """v0 = the mod resolver's partner of `actor` (a0); clobbers temporaries, a- and v-registers only."""
    a.move(4, actor); a.call(core.RESOLVER)


def entry_code():
    """Replaces 'jal 1D7C30' at 1C2D20.  s0 index/loop, s1 actor, s5 throwers, s6 victims, s7 count, s2 victim,
    s3 thrower slot, s4 scratch pointer."""
    a = Assembler(ENTRY)
    core.gate(a, 'native')
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'native')
    a.addiu(29, 29, -0x60)
    for k, reg in enumerate((16, 17, 18, 19, 20, 21, 22, 23, 31)):
        _sd(a, reg, 8 * k)
    a.call(COUNT); a.move(23, 2)
    a.addiu(8, 0, SLOTS); a.r(0x2A, 9, 8, 23); a.branch(4, 9, 0, 'count_ok'); a.move(23, 8)   # at most SLOTS
    a.label('count_ok')
    a.li(8, CONTROL); a.sw(23, 8, 8)                                   # the scanned count (pass 0)
    a.move(16, 0); a.move(21, 0); a.move(22, 0)
    # ---- scan, as the native loop does: skip 'gone' fighters; collect holding (0x8B) and held (0x97) fighters
    a.label('scan'); a.r(0x2A, 8, 16, 23); a.branch(4, 8, 0, 'scanned')
    a.move(4, 16); a.call(GETTER); a.move(17, 2)
    a.branch(4, 17, 0, 'scan_next')
    a.move(4, 17); a.call(GONE); a.branch(5, 2, 0, 'scan_next')
    for flag, lst, count, tag in ((HOLDING, THROWERS, 21, 't'), (HELD, VICTIMS, 22, 'v')):
        a.move(4, 17); a.addiu(5, 0, flag); a.call(HAS_FLAG); a.branch(4, 2, 0, f'{tag}_skip')
        a.li(8, lst); a.move(9, 0)                                   # the same actor once (pair aliases)
        a.label(f'{tag}_dup'); a.branch(4, 9, count, f'{tag}_add')
        a.lw(10, 8); a.branch(4, 10, 17, f'{tag}_skip')
        a.addiu(8, 8, 4); a.addiu(9, 9, 1); a.jump(f'{tag}_dup')
        a.label(f'{tag}_add'); a.sw(17, 8); a.addiu(count, count, 1)
        a.label(f'{tag}_skip')
    a.label('scan_next'); a.addiu(16, 16, 1); a.jump('scan')
    a.label('scanned')
    a.branch(4, 21, 0, 'done'); a.branch(4, 22, 0, 'done')
    a.addiu(8, 0, 1); a.branch(5, 21, 8, 'multi'); a.branch(5, 22, 8, 'multi')
    # ---- one thrower, one victim: the native pair, through the native body
    a.li(8, THROWERS); a.lw(4, 8); a.li(8, VICTIMS); a.lw(5, 8); a.call(ATTACH); a.jump('done')
    # ---- several grabs: pair each victim with the thrower actually holding it, strongest evidence first:
    #   pass 0  a rush grab's own pair: both fighters name the same (performer, recipient) physical ids in
    #           fields 3732/3736, the thrower in a rush attack (298..303), the victim in a rush reaction (307..309,
    #           313..315)
    #   pass 1  the victim's partner (the mod resolver: throw record, rush pair, else lock-on) is a free thrower
    #           whose own partner is the victim
    #   pass 2  a free thrower whose partner is the victim
    #   pass 3  the victim's partner is a free thrower
    #   pass 4  the closest free thrower/victim pair overall, repeatedly, within NEAR units (a thrower holds its
    #           victim within reach; a victim already let go and flying off is not pulled back)
    # A victim left over has no thrower holding it and keeps the native release, as before.
    a.label('multi'); _bump(a, 'multi')
    a.li(8, USED); a.addiu(9, 8, 4 * SLOTS)
    a.label('clear'); a.sw(0, 8); a.addiu(8, 8, 4); a.branch(5, 8, 9, 'clear')
    a.li(8, DONE); a.addiu(9, 8, 4 * SLOTS)
    a.label('clear_done'); a.sw(0, 8); a.addiu(8, 8, 4); a.branch(5, 8, 9, 'clear_done')
    a.move(23, 0)
    a.label('pass'); a.addiu(8, 0, 4); a.branch(4, 23, 8, 'global'); a.move(16, 0)
    a.label('victim'); a.branch(4, 16, 22, 'pass_next')
    a.li(8, DONE); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(9, 8); a.branch(5, 9, 0, 'victim_next')
    a.li(8, VICTIMS); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(18, 8); a.move(19, 0)
    a.branch(4, 23, 0, 'fields')
    a.addiu(8, 0, 2); a.branch(4, 23, 8, 'ask')
    # passes 1 and 3: the victim's own partner, if it is a free thrower
    _resolve(a, 18); a.move(17, 2)
    a.label('partner')     # s1 = candidate thrower actor: find it among the free throwers
    a.branch(4, 17, 0, 'victim_next'); a.branch(4, 17, 18, 'victim_next'); a.move(20, 0)
    a.label('fr_loop'); a.branch(4, 20, 21, 'victim_next')
    a.li(8, THROWERS); a.r(0, 9, 0, 20, 2); a.r(0x21, 8, 8, 9); a.lw(9, 8); a.branch(5, 9, 17, 'fr_next')
    a.li(8, USED); a.r(0, 9, 0, 20, 2); a.r(0x21, 8, 8, 9); a.lw(9, 8); a.branch(5, 9, 0, 'fr_next')
    a.addiu(19, 20, 1); a.addiu(8, 0, 1); a.branch(5, 23, 8, 'resolved')
    _resolve(a, 17); a.branch(4, 2, 18, 'resolved'); a.move(19, 0); a.jump('victim_next')   # pass 1: reciprocal
    a.label('fr_next'); a.addiu(20, 20, 1); a.jump('fr_loop')
    # pass 0: the rush pair fields, checked on both fighters (s1 = the performer; then the same free-thrower search,
    # which for pass 0 takes it without asking the resolver)
    a.label('fields')
    a.lw(8, 18, 0x948); a.addiu(9, 8, -307); a.i(11, 9, 9, 3); a.branch(5, 9, 0, 'f_victim')
    a.addiu(9, 8, -313); a.i(11, 9, 9, 3); a.branch(4, 9, 0, 'victim_next')
    a.label('f_victim')
    a.li(10, CONTROL); a.lw(10, 10, 8)                                          # the scanned count
    a.lw(12, 18, 3732); a.lw(13, 18, 3736)
    for r in (12, 13):
        a.r(0x2B, 9, r, 10); a.branch(4, 9, 0, 'victim_next')
    a.branch(4, 12, 13, 'victim_next')
    a.li(8, core.POINTERS); a.r(0, 9, 0, 13, 2); a.r(0x21, 9, 8, 9); a.lw(9, 9); a.branch(5, 9, 18, 'victim_next')
    a.r(0, 9, 0, 12, 2); a.r(0x21, 9, 8, 9); a.lw(17, 9); a.branch(4, 17, 0, 'victim_next')
    a.lw(8, 17, 0x948); a.addiu(8, 8, -298); a.i(11, 9, 8, 6); a.branch(4, 9, 0, 'victim_next')
    a.lw(8, 17, 3732); a.branch(5, 8, 12, 'victim_next'); a.lw(8, 17, 3736); a.branch(5, 8, 13, 'victim_next')
    a.jump('partner')
    # pass 2: a free thrower whose partner is this victim
    a.label('ask'); a.move(20, 0)
    a.label('ask_loop'); a.branch(4, 20, 21, 'victim_next')
    a.li(8, USED); a.r(0, 9, 0, 20, 2); a.r(0x21, 8, 8, 9); a.lw(9, 8); a.branch(5, 9, 0, 'ask_next')
    a.li(8, THROWERS); a.r(0, 9, 0, 20, 2); a.r(0x21, 8, 8, 9); a.lw(17, 8)
    a.branch(4, 17, 18, 'ask_next')
    _resolve(a, 17); a.branch(5, 2, 18, 'ask_next')
    a.addiu(19, 20, 1); a.jump('resolved')
    a.label('ask_next'); a.addiu(20, 20, 1); a.jump('ask_loop')
    # pass 4: the closest remaining free thrower / unheld victim pair within NEAR, again until none is left
    a.label('global'); a.move(19, 0); a.move(16, 0)
    a.li(8, struct.unpack('<I', struct.pack('<f', NEAR * NEAR))[0])
    a.emit((17 << 26) | (4 << 21) | (8 << 16) | (6 << 11))                                # mtc1 t0, f6
    a.label('g_victim'); a.branch(4, 16, 22, 'g_done')
    a.li(8, DONE); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(9, 8); a.branch(5, 9, 0, 'g_victim_next')
    a.li(8, VICTIMS); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(18, 8); a.move(20, 0)
    a.label('g_thrower'); a.branch(4, 20, 21, 'g_victim_next')
    a.li(8, USED); a.r(0, 9, 0, 20, 2); a.r(0x21, 8, 8, 9); a.lw(9, 8); a.branch(5, 9, 0, 'g_thrower_next')
    a.li(8, THROWERS); a.r(0, 9, 0, 20, 2); a.r(0x21, 8, 8, 9); a.lw(17, 8)
    a.branch(4, 17, 18, 'g_thrower_next')
    for k, off in enumerate((16, 20, 24)):
        _lwc1(a, 2, 17, off); _lwc1(a, 3, 18, off); _fop(a, 1, 2, 2, 3); _fop(a, 2, 2, 2, 2)   # d = (t-v)^2
        if k == 0:
            _fop(a, 6, 4, 2, 0)                                                             # mov.s f4, f2
        else:
            _fop(a, 0, 4, 4, 2)                                                             # f4 += d
    a.emit((17 << 26) | (16 << 21) | (6 << 16) | (4 << 11) | 0x34)                        # c.lt.s f4, f6 (in reach)
    a.fixups.append((len(a.words), 'g_thrower_next', 'branch')); a.emit((17 << 26) | (8 << 21)); a.emit(0)   # bc1f
    a.branch(4, 19, 0, 'g_take')                                                          # first candidate
    a.emit((17 << 26) | (16 << 21) | (5 << 16) | (4 << 11) | 0x34)                        # c.lt.s f4, f5
    a.fixups.append((len(a.words), 'g_thrower_next', 'branch')); a.emit((17 << 26) | (8 << 21)); a.emit(0)   # bc1f
    a.label('g_take'); a.addiu(19, 20, 1); _fop(a, 6, 5, 4, 0)                               # best, f5 = f4
    a.li(8, CONTROL); a.sw(16, 8, 12)                                                     # its victim index
    a.label('g_thrower_next'); a.addiu(20, 20, 1); a.jump('g_thrower')
    a.label('g_victim_next'); a.addiu(16, 16, 1); a.jump('g_victim')
    a.label('g_done'); a.branch(4, 19, 0, 'leftover')
    a.li(8, CONTROL); a.lw(16, 8, 12)
    a.li(8, VICTIMS); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(18, 8)
    _bump(a, 'nearest'); a.jump('take')
    a.label('resolved'); _bump(a, 'resolved')
    a.label('take')
    a.addiu(19, 19, -1)
    a.li(8, USED); a.r(0, 9, 0, 19, 2); a.r(0x21, 8, 8, 9); a.addiu(10, 0, 1); a.sw(10, 8)
    a.li(8, DONE); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.sw(10, 8)
    a.li(8, THROWERS); a.r(0, 9, 0, 19, 2); a.r(0x21, 8, 8, 9); a.lw(4, 8); a.move(5, 18)
    a.call(ATTACH); _bump(a, 'held')
    a.addiu(8, 0, 4); a.branch(4, 23, 8, 'global')
    a.label('victim_next'); a.addiu(16, 16, 1); a.jump('victim')
    a.label('pass_next'); a.addiu(23, 23, 1); a.jump('pass')
    a.label('leftover'); a.move(16, 0)
    a.label('left_loop'); a.branch(4, 16, 22, 'done')
    a.li(8, DONE); a.r(0, 9, 0, 16, 2); a.r(0x21, 8, 8, 9); a.lw(9, 8); a.branch(5, 9, 0, 'left_next')
    _bump(a, 'unpaired')
    a.label('left_next'); a.addiu(16, 16, 1); a.jump('left_loop')
    a.label('done')
    for k, reg in enumerate((16, 17, 18, 19, 20, 21, 22, 23, 31)):
        _ld(a, reg, 8 * k)
    a.addiu(29, 29, 0x60); a.jr()
    a.label('native'); a.jump(HOLD)
    data = a.finish(); assert len(data) <= ATTACH - ENTRY; return data


def pieces():
    control = bytearray(0x140)
    struct.pack_into('<2I', control, 0, MAGIC, VERSION)
    return [(ENTRY, entry_code()), (ATTACH, attach_code()), (CONTROL, bytes(control)), (SITE, JAL(ENTRY))]


def native_check(native=NATIVE):
    """The executable must hold the exact hold function the stub enters."""
    if native(SITE, 4) != JAL(HOLD):
        raise ValueError('The native hold call 1C2D20 changed')
    words = struct.unpack('<11I', native(HOLD, 44))
    if words != PROLOGUE or U32(native(BODY, 4)) >> 16 != BODY_FIRST:
        raise ValueError('The native hold function 1D7C30 changed')
    scan = struct.unpack('<%dI' % ((BODY - HOLD) // 4), native(HOLD, BODY - HOLD))
    if [w & 0xFFFF for w in scan if w >> 16 == 0x2405] != [HOLDING, HELD]:   # addiu a1,zero,flag in its scan
        raise ValueError("The native hold function's grab flags differ from FLAG(0x8B)/FLAG(0x97)")


def state(ram):
    """'native', 'installed', or raise for anything else at the call site or the reservation."""
    parts = pieces()
    site = ram[SITE:SITE + 4]
    code_ok = all(ram[p:p + len(d)] == d for p, d in parts[:2])
    if site == JAL(ENTRY) and code_ok and U32(ram[CONTROL:CONTROL + 8]) == MAGIC:
        return 'installed'
    if site == JAL(HOLD) and not any(ram[CODE:END]):
        return 'native'
    raise ValueError('Grab hold call site or reservation 0696C000 changed')


@policy.matching_install
def build_memory(ram, source='<prepared>'):
    if len(ram) != 0x8000000:
        raise ValueError('Grab hold pairing requires 128 MiB RAM')
    native_check()
    for p, n in DEPENDENCIES:
        if ram[p:p + n] != NATIVE(p, n):
            raise ValueError(f'Native hold function changed {p:08X}')
    if state(ram) == 'installed':
        return dict(serial=SERIAL, crc=CRC, source=str(source), blocks=[], status='GRAB HOLD PAIRS INSTALLED')
    blocks = [dict(address=p, expected_hex=ram[p:p + len(d)].hex(), data_hex=d.hex()) for p, d in pieces()]
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL, blocks=blocks,
                counters={k: CONTROL + v for k, v in C.items() if v >= 16},
                status='EVERY GRAB HELD BY ITS OWN THROWER')
