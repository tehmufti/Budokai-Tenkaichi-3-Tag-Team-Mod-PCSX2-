"""Never walk the stage debris pool through a null pointer.

Breakable stage objects (the Space stage's asteroids, for one) spawn rigid-body
debris into a 128-entry pool whose pointer lives at 0x2FEB78 (gp-0x56F8).
sub_230328 creates it with the stage and sub_230398 frees it and stores 0.
The first live 5v5 froze inside the per-frame update sub_2309A8: the pointer
read 0 in the middle of a sub-step, every later load went through address
0x12004 (unmapped), and right after that first faulting load the thread's $gp
and the loop's floating-point registers were garbage, so the loop never ended.
What cleared the pointer, and what replaced the registers, is not known;
nothing in the mod writes there.

This keeps any such moment harmless. The allocator 22FC80 and the id lookup
22FD50 (its callers 2304C0, 230908 and 230AA0 all treat 0 as "no such piece")
return their own "nothing" result while the pointer is 0 (only v0/v1 are
touched; both set them before use). The update 2309A8 is replaced: the pointer
went to 0 in the middle of that loop, so an entry check is not enough. The
replacement makes the same calls in the same order, but re-reads the pointer
from its absolute address (not through $gp) before every one, stops the frame
the moment it is 0, and caps the sub-steps with an integer counter, so it can
neither walk a null pool nor spin forever on bad step values. The round
reset 2302F0 (also reached from a round restart, not only from creation) does
nothing while the pointer is 0.

The log also fits $gp going bad first (gp-0x56F8 was 0x58822B0D). BT3 keeps $gp
at 0x304270 for its whole life, so the replaced update checks it at entry and
after every native call it makes: a wrong value is put back and recorded
(the value and which call returned it), turning a permanent hang into one bad
frame and naming the routine that clobbered it. Each refusal is counted.
"""
from native_map import A, CRC, GP as NATIVE_GP, SERIAL, elf_path
import struct

from prototype import Assembler, ROOT, elf_reader

CODE, CONTROL, END = 0x072C0000, 0x072CF000, 0x072D0000
MAGIC = 0x44425231  # 'DBR1'
POOL_GP = -0x56F8   # 0x2FEB78
STRIDE = 0x80
# entry, control counter offset: allocator, id lookup, round reset
ENTRIES = ((A(0x22FC80), 4), (A(0x22FD50), 8), (A(0x2302F0), 32))
UPDATE_ENTRY, UPDATE = A(0x2309A8), CODE + 0x400
POOL_ADDRESS = A(0x304270 + POOL_GP)
STEP, LIMIT = A(0x304270 - 0x5E88), A(0x304270 - 0x5E84)    # f22, f21 of the native update
PRE, INTEGRATE, CONTACTS, DAMPING, SETTLE, SLEEP, ACTIVE = (
    A(0x22FE98), A(0x22FFA8), A(0x230008), A(0x2301B0), A(0x230218), A(0x230270), A(0x22FC40))
SCENE, SCENE_FLAGS, PAUSED = A(0x126EC8), 0x19F0, 0x100
MAX_STEPS = 16          # the native frame takes 10 sub-steps (0.1666 s / 0.016677 s)
GP = 0x304270
# gp_site: 0 on entry, else 1 + the index of the call in CALL_ORDER that returned it
FIELDS = dict(magic=0, refused_allocations=4, refused_lookups=8, skipped_updates=12, capped_updates=16,
              gp_repairs=20, last_bad_gp=24, gp_site=28, skipped_resets=32)
CALL_ORDER = ('scene', 'pre', 'integrate', 'contacts', 'damping', 'settle', 'sleep', 'active')
NATIVE = elf_reader(elf_path(ROOT))[2]
assert CODE + len(ENTRIES)*STRIDE <= UPDATE < CONTROL < END


def wrapper_code(index):
    entry, counter = ENTRIES[index]; original = NATIVE(entry, 8)
    a = Assembler(CODE + index*STRIDE)
    a.lw(2, 28, POOL_GP); a.branch(5, 2, 0, 'native')
    a.li(2, CONTROL); a.lw(3, 2, counter); a.addiu(3, 3, 1); a.sw(3, 2, counter)
    a.move(2, 0); a.jr()
    a.label('native')
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in range(1, 8), f'Debris routine {entry:X} prologue is not position independent'
        a.emit(word)
    a.jump(entry + 8)
    code = a.finish(); assert len(code) <= STRIDE; return code


def fp(a, fn, fd, fs, ft):
    a.emit((17 << 26) | (16 << 21) | (ft << 16) | (fs << 11) | (fd << 6) | fn)


def update_code():
    """sub_2309A8 with a null-safe, bounded sub-step loop (see the docstring)."""
    a = Assembler(UPDATE)
    a.addiu(29, 29, -0x30); a.i(63, 31, 29, 0); a.i(63, 16, 29, 8)
    for i, f in enumerate((20, 21, 22)): a.i(57, f, 29, 0x10+4*i)
    sites = iter(range(len(CALL_ORDER)+1))
    def gp_check():
        # t-registers only; each check sits right after a call (or at entry).
        site = next(sites); ok = f'gp_ok{site}'
        a.li(8, NATIVE_GP); a.branch(4, 28, 8, ok)
        a.li(9, CONTROL); a.sw(28, 9, FIELDS['last_bad_gp']); a.addiu(10, 0, site)
        a.sw(10, 9, FIELDS['gp_site']); a.lw(10, 9, FIELDS['gp_repairs']); a.addiu(10, 10, 1)
        a.sw(10, 9, FIELDS['gp_repairs']); a.move(28, 8)
        a.label(ok)
    gp_check()
    a.call(SCENE); gp_check(); a.lw(3, 2, SCENE_FLAGS); a.i(12, 3, 3, PAUSED); a.branch(5, 3, 0, 'return')
    a.emit((17 << 26) | (4 << 21) | (0 << 16) | (20 << 11))          # mtc1 zero,f20
    a.li(8, STEP); a.i(49, 22, 8, 0); a.li(8, LIMIT); a.i(49, 21, 8, 0)
    checked = {}
    def call_with_pool(target):
        # a0 = the active list head, read afresh; a null pool ends the frame.
        a.li(8, POOL_ADDRESS); a.lw(2, 8); a.branch(4, 2, 0, 'null')
        a.li(8, 0x10000); a.r(0x21, 4, 2, 8); a.lw(4, 4, 0x2004); a.call(target)
        # One check site per call; the loop body reuses its sites every pass.
        if target not in checked: checked[target] = True; gp_check()
        else: raise AssertionError('each call is emitted once')
    call_with_pool(PRE)
    a.move(16, 0)
    a.label('step')
    call_with_pool(INTEGRATE); fp(a, 0, 20, 20, 22)                   # add.s f20,f20,f22
    for target in (CONTACTS, DAMPING, SETTLE): call_with_pool(target)
    a.addiu(16, 16, 1); a.i(11, 8, 16, MAX_STEPS); a.branch(4, 8, 0, 'capped')
    fp(a, 0x36, 0, 20, 21)                                              # c.ole.s f20,f21
    a.branch(17, 8, 1, 'step')                                          # bc1t
    a.jump('settle')
    a.label('capped'); a.li(8, CONTROL); a.lw(9, 8, FIELDS['capped_updates']); a.addiu(9, 9, 1)
    a.sw(9, 8, FIELDS['capped_updates'])
    a.label('settle')
    call_with_pool(SLEEP); call_with_pool(ACTIVE)
    a.li(8, POOL_ADDRESS); a.lw(3, 8); a.branch(4, 3, 0, 'null')
    a.li(8, 0x10000); a.r(0x21, 3, 3, 8); a.sw(2, 3, 0x200C)
    a.jump('return')
    a.label('null'); a.li(8, CONTROL); a.lw(9, 8, FIELDS['skipped_updates']); a.addiu(9, 9, 1)
    a.sw(9, 8, FIELDS['skipped_updates'])
    a.label('return')
    for i, f in enumerate((20, 21, 22)): a.i(49, f, 29, 0x10+4*i)
    a.i(55, 16, 29, 8); a.i(55, 31, 29, 0); a.addiu(29, 29, 0x30); a.jr()
    code = a.finish(); assert UPDATE + len(code) <= CONTROL; return code


def pieces():
    parts = [(CODE + i*STRIDE, wrapper_code(i)) for i in range(len(ENTRIES))]
    parts += [(entry, struct.pack('<2I', (2 << 26) | ((CODE + i*STRIDE) >> 2), 0))
              for i, (entry, _) in enumerate(ENTRIES)]
    parts += [(UPDATE, update_code()), (UPDATE_ENTRY, struct.pack('<2I', (2 << 26) | (UPDATE >> 2), 0))]
    return parts


def build_memory(ram, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE RAM')
    for entry, _ in ENTRIES:
        if ram[entry:entry+8] != NATIVE(entry, 8): raise ValueError(f'Native debris routine {entry:X} changed')
    # The replacement mirrors this exact update and calls these exact routines.
    if ram[UPDATE_ENTRY:A(0x230AA0)] != NATIVE(UPDATE_ENTRY, A(0x230AA0)-UPDATE_ENTRY):
        raise ValueError('Native debris update changed')
    if any(ram[CODE:END]): raise ValueError('Debris guard reservation occupied')
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex())
              for p, d in [(CONTROL, struct.pack('<9I', MAGIC, *([0]*8)))] + pieces()]
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL,
                status='STAGE DEBRIS POOL NULL GUARD', blocks=blocks,
                telemetry={name: CONTROL+offset for name, offset in FIELDS.items() if name != 'magic'})
