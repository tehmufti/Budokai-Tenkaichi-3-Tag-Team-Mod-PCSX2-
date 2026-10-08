"""Widen the native auxiliary-trail lists from two owners to twelve (the 5v5 Muscle Tower hang).

The trail manager *(gp-22588) (USA holder 0x2FEA34, a 0x660-byte object from 16B4E0) keeps one list per
owner: heads at +0x554+4*owner and tails at +0x55C+4*owner, valid only for owners 0 and 1, over a 20-node
pool of {data, flags, next} at +0x564 with a cursor byte at +0x654. Extra fighters create trails with their
own fighter index (2..9), so their head and tail writes land inside the pool: owner 6's head is node0.next
and its tail is node1.flags, the first insert links a node to itself, and once that node is marked consumed
the walk 16D2A8..16D2C8 never ends. The EE hangs with the picture frozen (acc3, TTM-MATCH-20).

Owners 0/1 keep the native lists and native code. Owners 2..11 get mod-owned heads/tails (HEADS/TAILS in
CONTROL) over the same native node pool, and every pointer taken from them is checked to be one of the 20
pool nodes. Anything else - an owner >= 12, a negative halfword, an uncaptured manager or MODE 2 - takes
the native empty / not-tracked result (the bound). Five entry points are wrapped: insert (mid-hook at
16CF98, after 16D050 has taken a node), pop 16CFF8, pop-and-mark 16D628, walk 16D270 and walk-head 16C988.
"""
from native_map import A, CRC, GP, GPO, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import battle_mode_policy as policy

CODE, CONTROL = 0x0723D000, 0x0723DF00
CONTROL_BYTES = 224
END = CONTROL + CONTROL_BYTES      # 0x0723DFE0: the whole reservation
W_INS, W_POP, W_PM, W_WALK, W_WH = CODE + 0x000, CODE + 0x200, CODE + 0x400, CODE + 0x600, CODE + 0x900
MAGIC = 0x54524C31                 # 'TRL1'
WIDEN, BOUND = 1, 2
MODES = {'widen': WIDEN, 'bound': BOUND}
OWNERS = policy.ENGINE_ACTORS      # 12: every fighter index the engine tables can hold
MODE, HOLDER, MGR = 4, 8, 12
# Counters, u32 at CONTROL+16+4*k.
COUNTERS = ('ext_insert', 'ext_pop', 'ext_popmark', 'ext_walk', 'ext_walkhead',
            'bound_insert', 'bound_pop', 'bound_popmark', 'bound_walk', 'bound_walkhead', 'faults')
C_INS, C_POP, C_PM, C_WALK, C_WH, B_INS, B_POP, B_PM, B_WALK, B_WH, FAULTS = range(len(COUNTERS))
LAST_FAULT, HEADS, TAILS = 64, 128, 176
POOL, NODES, NODE, CURSOR, SIZE = 0x564, 20, 12, 0x654, 0x660
HOLDER_GP = -22588
# Hook sites. Each wrapper relocates the two native words it displaces; they are read from the disc ELF.
SITES = {'insert': A(0x16CF98), 'pop': A(0x16CFF8), 'popmark': A(0x16D628), 'walk': A(0x16D270),
         'walkhead': A(0x16C988)}
WRAPPERS = {'insert': W_INS, 'pop': W_POP, 'popmark': W_PM, 'walk': W_WALK, 'walkhead': W_WH}
# The native words this design depends on: the 0x660 allocation, the five indexed list users and the pool
# cursor/base. A disc whose words differ is not the manager this was written for.
NATIVE_WORDS = {A(0x16B50C): 0x24050660, A(0x16C9A4): 0x8C430554, A(0x16CFA0): 0x24450550,
                A(0x16D01C): 0x24440554, A(0x16D2A4): 0x8C510554, A(0x16D640): 0x24640554,
                A(0x16D058): 0x90A20654, A(0x16D08C): 0x24420564}
# The endless loop itself (beqz s1 .. lw s1,8(s1)); autopilot labels a frozen PC in it.
LOOP = (A(0x16D2A8), A(0x16D2C8))
BRANCH_OPS = (1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23)


def bump(a, k):
    """CONTROL counter k += 1. Uses t4/t5 only."""
    a.li(12, CONTROL); a.lw(13, 12, 16 + 4 * k); a.addiu(13, 13, 1); a.sw(13, 12, 16 + 4 * k)


def gate(a, owner, fail):
    """Fall through only for the captured manager in widen mode and owner < 12. Uses t0..t2; t0 = CONTROL."""
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, fail)
    a.lw(9, 8, MODE); a.addiu(10, 0, WIDEN); a.branch(5, 9, 10, fail)
    a.lw(9, 28, HOLDER_GP); a.branch(4, 9, 0, fail); a.lw(10, 8, HOLDER); a.branch(5, 9, 10, fail)
    a.lw(9, 9); a.lw(10, 8, MGR); a.branch(5, 9, 10, fail)
    a.i(11, 9, owner, OWNERS); a.branch(4, 9, 0, fail)


def valid(a, reg, bad, tag):
    """reg must be one of the 20 pool nodes of the captured manager, else jump to bad. Uses v1/a3."""
    a.li(3, CONTROL); a.lw(3, 3, MGR); a.addiu(3, 3, POOL); a.addiu(7, 0, NODES)
    a.label(tag); a.branch(4, reg, 3, tag + '_ok')
    a.addiu(3, 3, NODE); a.addiu(7, 7, -1); a.branch(5, 7, 0, tag)
    a.jump(bad)
    a.label(tag + '_ok')


def relocated(a, words, resume):
    for w in words:
        assert w >> 26 not in BRANCH_OPS, f'relocated native word is a branch: {w:08X}'
        a.emit(w)
    a.jump(resume)


def insert_code(native_words):
    """Mid-hook at 16CF98: a0 = the node 16D050 just took (data set, next 0, flags |1 or |0x11), s3 = owner,
    s0 = manager. Native continues at 16CFD8 (v0 = 1) or 16CFDC (v0 as set)."""
    a = Assembler(W_INS)
    a.i(11, 9, 19, 2); a.branch(5, 9, 0, 'native')
    gate(a, 19, 'bound')
    a.r(0, 9, 0, 19, 2); a.r(0x21, 9, 9, 8)
    a.lw(2, 9, HEADS); a.branch(5, 2, 0, 'append')
    a.label('first'); a.sw(4, 9, HEADS); a.sw(4, 9, TAILS); bump(a, C_INS); a.jump(A(0x16CFD8))
    a.label('append'); a.lw(5, 9, TAILS); valid(a, 5, 'reset', 'tail'); valid(a, 2, 'reset', 'head')
    a.sw(4, 5, 8); a.sw(4, 9, TAILS); bump(a, C_INS); a.jump(A(0x16CFD8))
    a.label('reset'); bump(a, FAULTS); a.li(12, CONTROL); a.sw(19, 12, LAST_FAULT); a.jump('first')
    # Not tracked: hand the node straight back to the pool and answer like a full pool (v0 = 0).
    a.label('bound'); a.sw(0, 4, 0); a.sw(0, 4, 4); a.sw(0, 4, 8); bump(a, B_INS); a.move(2, 0)
    a.jump(A(0x16CFDC))
    a.label('native'); relocated(a, native_words, A(0x16CFA0))
    data = a.finish(); assert W_INS + len(data) <= W_POP; return data


def pop_code(native_words, mark):
    """Entry 16CFF8 (pop) or 16D628 (pop-and-mark), a0 = owner."""
    a = Assembler(W_PM if mark else W_POP)
    a.i(11, 9, 4, 2); a.branch(5, 9, 0, 'native')
    gate(a, 4, 'bound')
    a.r(0, 9, 0, 4, 2); a.r(0x21, 9, 9, 8); a.lw(5, 9, HEADS); a.branch(4, 5, 0, 'ext')
    valid(a, 5, 'fault', 'head')
    a.label('ext'); a.addiu(4, 9, HEADS); a.move(2, 0); bump(a, C_PM if mark else C_POP)
    a.jump(A(0x16D644) if mark else A(0x16D020))
    a.label('fault'); a.sw(0, 9, HEADS); bump(a, FAULTS); a.jump('ext')
    a.label('bound'); bump(a, B_PM if mark else B_POP); a.move(2, 0)
    if not mark:  # the native empty list answers 1 while a manager exists
        a.lw(9, 28, HOLDER_GP); a.branch(4, 9, 0, 'ret'); a.lw(9, 9); a.branch(4, 9, 0, 'ret'); a.addiu(2, 0, 1)
    a.label('ret'); a.jr()
    a.label('native'); relocated(a, native_words, A(0x16D630) if mark else A(0x16D000))
    data = a.finish(); assert a.base + len(data) <= (W_WALK if mark else W_PM); return data


def walk_code(native_words):
    """Entry 16D270, a0 = query (owner = lh 0x12). The native list scan is replaced by a bounded one."""
    a = Assembler(W_WALK)
    a.i(33, 11, 4, 0x12); a.i(11, 9, 11, 2); a.branch(5, 9, 0, 'native')
    gate(a, 11, 'bound')
    # The native prologue, exactly: its own epilogue (16D2D8 or after 16D2CC) restores these.
    a.addiu(29, 29, -0x20); a.i(63, 18, 29, 0x10); a.move(18, 4); a.i(63, 16, 29, 0)
    a.move(2, 0); a.i(63, 17, 29, 8); a.i(63, 31, 29, 0x18)
    a.r(0, 9, 0, 11, 2); a.r(0x21, 9, 9, 8); a.lw(17, 9, HEADS); a.addiu(10, 0, NODES)
    a.label('scan'); a.branch(4, 17, 0, 'empty')
    valid(a, 17, 'fault', 'node')
    a.lw(2, 17, 4); a.i(12, 2, 2, 0x30); a.branch(4, 2, 0, 'found')
    a.lw(17, 17, 8); a.addiu(10, 10, -1); a.branch(5, 10, 0, 'scan')
    # More than 20 nodes (a cycle) or a pointer outside the pool: forget this list.
    a.label('fault'); a.sw(0, 9, HEADS); bump(a, FAULTS); a.li(12, CONTROL); a.sw(11, 12, LAST_FAULT)
    a.move(17, 0)
    a.label('empty'); bump(a, C_WALK); a.move(4, 18); a.jump(A(0x16D2D8))
    a.label('found'); bump(a, C_WALK); a.jump(A(0x16D2CC))
    a.label('bound'); bump(a, B_WALK); a.jump(A(0x16D448))
    a.label('native'); relocated(a, native_words, A(0x16D278))
    data = a.finish(); assert W_WALK + len(data) <= W_WH; return data


def walkhead_code():
    """Entry 16C988, a1 = query (owner = lh 0x12); native continues at 16C9A8 with v1 = head."""
    a = Assembler(W_WH)
    a.i(33, 11, 5, 0x12); a.i(11, 9, 11, 2); a.branch(5, 9, 0, 'native')
    gate(a, 11, 'bound')
    a.r(0, 9, 0, 11, 2); a.r(0x21, 9, 9, 8); a.lw(2, 9, HEADS); a.branch(4, 2, 0, 'go')
    valid(a, 2, 'fault', 'head')
    a.label('go'); bump(a, C_WH); a.move(3, 2); a.jump(A(0x16C9A8))
    a.label('fault'); a.sw(0, 9, HEADS); bump(a, FAULTS); a.move(2, 0); a.jump('go')
    a.label('bound'); bump(a, B_WH); a.jr()
    a.label('native'); a.lw(3, 28, HOLDER_GP); a.branch(4, 3, 0, 'none'); a.jump(A(0x16C994))
    a.label('none'); a.jump(A(0x16CA20))
    data = a.finish(); assert W_WH + len(data) <= CONTROL; return data


def native_reader():
    return elf_reader(elf_path(ROOT))[2]


def code_blocks(native):
    """[(address, bytes)] of the five wrappers; native(address, n) -> disc ELF bytes."""
    w = lambda name: struct.unpack('<2I', native(SITES[name], 8))
    return [(W_INS, insert_code(w('insert'))), (W_POP, pop_code(w('pop'), False)),
            (W_PM, pop_code(w('popmark'), True)), (W_WALK, walk_code(w('walk'))), (W_WH, walkhead_code())]


def hook_blocks():
    return [(SITES[name], struct.pack('<2I', (2 << 26) | (WRAPPERS[name] >> 2), 0)) for name in SITES]


def control_block(holder, manager, mode=WIDEN):
    data = bytearray(CONTROL_BYTES); struct.pack_into('<4I', data, 0, MAGIC, mode, holder, manager)
    return bytes(data)


def program():
    """The wrappers as this disc's ELF relocates them (fixture-free; the guest-code lints read it)."""
    return code_blocks(native_reader())


def blocks(native, holder, manager, mode=WIDEN):
    """Every block: five wrappers, CONTROL and the five 8-byte hooks."""
    return code_blocks(native) + [(CONTROL, control_block(holder, manager, mode))] + hook_blocks()


def leader_lists(ram, manager):
    """None when the two native lists are sound, else the reason they are not.

    Sound: the cursor is inside the pool; each leader list is acyclic and made of pool nodes; every node
    in use (flags != 0) is on exactly one of the two lists."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    pool = [manager + POOL + NODE * k for k in range(NODES)]
    cursor = ram[manager + CURSOR]
    if cursor >= NODES:
        return f'pool cursor {cursor} is outside the {NODES}-node pool'
    listed = {}
    for owner in (0, 1):
        node, seen = u(manager + 0x554 + 4 * owner), set()
        while node:
            if node not in pool:
                return f'leader {owner} list leaves the pool at {node:08X}'
            if node in seen:
                return f'leader {owner} list is cyclic at {node:08X}'
            seen.add(node); listed.setdefault(node, []).append(owner)
            node = u(node + 8)
    for node in pool:
        if u(node + 4) and len(listed.get(node, ())) != 1:
            return f'pool node {node:08X} is in use but on {len(listed.get(node, ()))} leader lists'
    return None


def build(source, mode='widen'):
    if mode not in MODES:
        raise ValueError(f'aux_trail_lists mode must be one of {tuple(MODES)}')
    r = read_ram(source)
    if len(r) != 0x8000000:
        raise ValueError('Full 128 MiB EE RAM is required')
    u = lambda p: struct.unpack_from('<I', r, p)[0]
    native = native_reader()
    for at, word in NATIVE_WORDS.items():
        if u(at) != word or struct.unpack('<I', native(at, 4))[0] != word:
            raise ValueError(f'Native trail-list word changed at {at:08X}')
    for name, at in SITES.items():
        if r[at:at + 8] != native(at, 8):
            raise ValueError(f'Native trail-list hook site changed: {name} {at:08X}')
    if GP + GPO(HOLDER_GP) != A(0x2FEA34):
        raise ValueError('Trail manager holder is not gp-22588 on this disc')
    holder = u(A(0x2FEA34))
    if not (0x100000 <= holder <= 0x8000000 - 4 and holder % 4 == 0):
        raise ValueError(f'Trail manager holder is not a valid pointer: {holder:08X}')
    manager = u(holder)
    if not (0x100000 <= manager <= 0x8000000 - SIZE and manager % 4 == 0):
        raise ValueError(f'Trail manager is not a valid object: {manager:08X}')
    if any(r[CODE:END]):
        raise ValueError(f'Trail-list reservation occupied: {CODE:08X}..{END:08X}')
    chosen, limitations = MODES[mode], []
    problem = leader_lists(r, manager)
    if problem is not None and chosen == WIDEN:
        # A cosmetic list must never make a match unpreparable: track nothing for extras instead.
        chosen = BOUND
        limitations.append(f'Native trail lists were inconsistent at capture ({problem}); extra fighters\' '
                           f'auxiliary trails are untracked for this match (bound mode).')
    payloads = blocks(native, holder, manager, chosen)
    if chosen == BOUND and problem is not None:
        control = bytearray(payloads[5][1]); struct.pack_into('<I', control, 16 + 4 * FAULTS, 1)
        payloads[5] = (CONTROL, bytes(control))
    status = ('WIDENED TWELVE-OWNER TRAIL LISTS; OFFLINE TESTED' if chosen == WIDEN else
              'BOUND TRAIL LISTS (EXTRA FIGHTERS UNTRACKED); OFFLINE TESTED')
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), status=status, mode=chosen,
                control=CONTROL, holder=holder, manager=manager,
                blocks=[dict(address=p, expected_hex=r[p:p + len(b)].hex(), data_hex=b.hex()) for p, b in payloads],
                telemetry=dict(aux_trail_mode=CONTROL + MODE, aux_trail_ext=CONTROL + 16,
                               aux_trail_bound=CONTROL + 16 + 4 * B_INS, aux_trail_faults=CONTROL + 16 + 4 * FAULTS,
                               aux_trail_last_fault=CONTROL + LAST_FAULT),
                limitations=limitations,
                evidence=['16B4E0 allocates 0x660 bytes into gp-22588; heads +0x554 and tails +0x55C hold owners 0/1.',
                          'Owner 6 aliases node0.next and owner 8 node1.flags: the acc3 5v5 hang at 16D2A8.',
                          'Leaders keep native code and lists; extras use mod lists of validated pool nodes.'],
                behavior=['Owners 0/1: native lists and code, byte-identical results.',
                          'Owners 2..11: native list semantics over the native pool through CONTROL HEADS/TAILS.',
                          'Owner >= 12, negative owner, uncaptured manager or bound mode: native not-tracked path.',
                          'A list that leaves the pool or exceeds 20 nodes is forgotten and counted as a fault.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    p.add_argument('--mode', choices=tuple(MODES), default='widen')
    x = p.parse_args(); x.out.write_text(json.dumps(build(x.source, x.mode), indent=2) + '\n'); print(x.out)
