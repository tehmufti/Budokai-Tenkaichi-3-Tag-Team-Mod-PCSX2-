"""Ginyu Body Change's actual-pair boundary and transaction snapshot.

The observe-only helper remains independent. The opt-in release service is
body_swap_worker.prepare_memory plus the caller-owned fighter_updates worker;
it loads and verifies both models before publishing either body. This module
does not open a PINE connection or process.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import battle_mode_policy as policy
import team_participation as participation
from battle_mode_policy import ACTOR_COUNTS

CODE, CONTROL, ROWS, END = 0x07020000, 0x0702F000, 0x0702F200, 0x070A0000
MAGIC = 0x42535731
PICKER, PICK_CALL = A(0x1E10F8), A(0x1F9AD8)
NATIVE = elf_reader(elf_path(ROOT))[2]
PAIRED = tuple(range(301, 304))+tuple(range(313, 316))
GINYU, SCRIPT = 86, 0x280
ROW_BYTES = 164
# Native restriction marker: roster row+0x70, read by sub_1DC348 (SLUS_216.78.c:220980),
# written only by sub_1C0538 under the attacker's one-shot flag 0xA6 (:200938-200939).
MARKER = 0x70
# CONTROL words (all relative to CONTROL): 0 magic, 4 manager, 8 count, 12 captures,
# 16 status, 20 enabled, 24 generation, 28 host-finished generation,
# 32 host-aborted generation, 36 original Ginyu owner mask (bit per physical).
# Historical ten-word diagnostic ABI is unchanged; extension words are
# 40 denied-attempt count and 44 stolen-body abilities (Boolean, default 0).
FINISHED, ABORTED, OWNERS = CONTROL+28, CONTROL+32, CONTROL+36
CONTROL_WORDS = 10
# Metadata records at ROWS (2x64), picker-time full rows at ROWS+0x200/+0x300
# (capture.FULL_ROWS) and exact hold-time rows copied by the runner at the
# status 2->3 handoff at ROWS+0x400/+0x500; the reserved data block is 0x600 bytes.
HANDOFF_ROWS = (ROWS+0x400, ROWS+0x500)
# Exact denied authored pairs, indexed by physical source. A second simultaneous
# move may finish normally without ever invoking stock random-body reloads.
DENIED, DENIED_COUNT = ROWS+0x600, CONTROL+40
ALLOW_ABILITIES = CONTROL+44
ROWS_BYTES = 0x700


def u(ram, p): return struct.unpack_from('<I', ram, p)[0]


def require(ok, message):
    if not ok: raise ValueError(message)


def world(ram,*,preparing=False):
    require(len(ram) == 0x8000000, 'Requires128MiB EE memory')
    manager, count = u(ram, core.ACTORS), u(ram, core.MODE+4)
    require(0x100000 <= manager < len(ram)-0x1000 and u(ram, manager) == 2,
            'Captured native manager required')
    require(count in ACTOR_COUNTS and u(ram, core.MODE) == 1 and
            u(ram, core.MODE+8) == manager and u(ram, core.MODE+12) == count and
            u(ram, core.PAIR+4) == 0, 'Published captured world without AI aliases required')
    actors = [u(ram, core.POINTERS+4*i) for i in range(count)]
    require(len(set(actors)) == count, 'Independent actor pointers required')
    for i, actor in enumerate(actors):
        require(0x100000 <= actor <= len(ram)-0x1600 and u(ram, actor) == i,
                'Captured physical actor identity changed')
    require(u(ram, participation.CONTROL) in ((0,5) if preparing else (5,)) and
            u(ram, participation.CONTROL+4) == manager and
            u(ram, participation.CONTROL+8) == count, 'Participation belongs to another match')
    present = u(ram, participation.CONTROL+12) & ~u(ram, participation.CONTROL+16)
    mode = 'teams'
    if (u(ram, policy.CONTROL) == policy.MAGIC and
            u(ram, policy.CONTROL+4) == manager and u(ram, policy.CONTROL+8) == count):
        value = u(ram, policy.CONTROL+12)
        require(value in policy.MODES.values(), 'Unknown battle mode')
        mode = next(k for k, v in policy.MODES.items() if value == v)
    return dict(manager=manager, count=count, actors=actors, present=present, mode=mode)


def body(ram, w, physical):
    require(type(physical) is int and 0 <= physical < w['count'], 'Invalid body physical index')
    require(w['present'] & (1 << physical), 'Body is absent or consumed')
    actor = w['actors'][physical]; mid = u(ram, actor+12)
    require(mid < 12, 'Model index exceeds registered slots')
    model = u(ram, core.MODELS+4*mid)
    require(0x100000 <= model <= len(ram)-0x1670 and u(ram, model+4) == 1 and
            u(ram, model+16) == mid, 'Registered body model changed')
    slot, slots = u(ram, actor+0x994), u(ram, actor+0x998)
    require(slot < slots <= 5, 'Invalid active roster row')
    row = actor+0x9A4+ROW_BYTES*slot
    character, costume = u(ram, row), u(ram, row+4)
    require(character <= 160 and character == u(ram, model+12) and costume <= 3,
            'Roster and actual body identity differ')
    hp, maximum = u(ram, row+64), u(ram, row+68)
    require(0 < hp <= maximum <= 1000000, 'Body must have valid remaining health')
    resource = u(ram, model+20)
    require(0x100000 <= resource <= len(ram)-56 and u(ram, resource+48) & 1,
            'Loaded body resource required')
    return dict(physical=physical, actor=actor, model_id=mid, model=model,
                resource=resource, resource_handle=u(ram, resource+52),
                row=row, row_hex=bytes(ram[row:row+ROW_BYTES]).hex(),
                character=character, costume=costume, damaged=bool(u(ram, row+96)),
                health=hp, max_health=maximum, ki=u(ram, row+76),
                stocks=u(ram, row+84), controller=u(ram, actor+4),
                cpu=u(ram, actor+0x1278), action=u(ram, actor+2376))


def capture(ram, initiator):
    """Capture only a successful native Body Change's reciprocal actual pair.

    The lock-on table may already point elsewhere. It is never consulted.
    Native1CC2A0 writes +E94/+E98 from actual attacker/defender pointers.
    """
    w = world(ram)
    require(initiator in w['actors'], 'Initiator is not a captured actor')
    source_id, target_id = u(ram, initiator+0xE94), u(ram, initiator+0xE98)
    require(source_id < w['count'] and target_id < w['count'] and
            w['actors'][source_id] == initiator, 'Initiator must be native attacker')
    require(policy.enemy(w['mode'], source_id, target_id), 'Body Change requires an enemy')
    source, target = body(ram, w, source_id), body(ram, w, target_id)
    require(source['character'] == GINYU, 'Body Change source must actually be Captain Ginyu')
    for b in (source, target):
        actor = b['actor']
        require(b['action'] in PAIRED and u(ram, actor+0xE90) == SCRIPT and
                u(ram, actor+0xE94) == source_id and u(ram, actor+0xE98) == target_id,
                'Successful reciprocal Body Change capture required')
    require(source['model'] != target['model'], 'Bodies must have independent models')
    return dict(world=w, source=source, target=target)


def ginyu_owners(ram, w):
    """Bit per present physical whose own roster holds Captain Ginyu.

    Recorded when capture is enabled. A body that later receives character 86
    through an exchange is not an original owner and may not start another
    Body Change (neither a true exchange nor the stock random reload).
    """
    mask = 0
    for physical, actor in enumerate(w['actors']):
        if not w['present'] & (1 << physical): continue
        slots = u(ram, actor+0x998)
        if slots > 5: continue
        if any(u(ram, actor+0x9A4+ROW_BYTES*slot) == GINYU for slot in range(slots)):
            mask |= 1 << physical
    return mask


def desired_rows(snapshot):
    """Explicit target outcome; not an apply manifest or visual-only swap.

    Every existing model/actor address, physical/controller ID and team stays
    owned by its original slot. Character, costume, HP, ki and body stats follow
    the exchanged row. The native post-Body-Change restriction marker (row+0x70,
    sub_1DC348) is published as 1 to the ATTACKER's actor, exactly as native
    sub_1C0538 does for the reloaded attacker, so Ginyu cannot use the stolen
    body's Blast1/Blast2/ultimate/transformations by default. The explicit
    stolen_abilities option instead publishes 0 and keeps its native move data.
    The victim's actor, now in
    Ginyu's body, gets 0 (native never restricts the victim).
    New model/combat/animation resources must be independently staged first.
    """
    rows = []
    unrestricted=snapshot.get('stolen_abilities',False)
    require(type(unrestricted) is bool,'Stolen-body ability option must be Boolean')
    for owner, donor, marker in ((snapshot['source'], snapshot['target'], int(not unrestricted)),
                                 (snapshot['target'], snapshot['source'], 0)):
        data = bytearray.fromhex(donor['row_hex'])
        struct.pack_into('<I', data, MARKER, marker)
        rows.append(dict(actor=owner['actor'], row=owner['row'], data_hex=data.hex(),
                         character=donor['character'], health=donor['health'],
                         ki=donor['ki'], max_health=donor['max_health'], marker=marker,
                         controller=owner['controller'], cpu=owner['cpu']))
    return rows


def observe_code():
    """Pass-through call wrapper; snapshots records without changing the move."""
    saved = tuple(range(1, 29))+(30, 31)
    a = Assembler(CODE); a.addiu(29, 29, -0x200)
    for i, r in enumerate(saved): a.i(31, r, 29, i*16)
    a.li(16, CONTROL); a.lw(8, 16); a.li(9, MAGIC); a.branch(5, 8, 9, 'done')
    core.gate(a, 'done'); a.lw(8, 16, 4); a.lw(9, 28, -22364)
    a.branch(5, 8, 9, 'done'); a.lw(8, 16, 8); a.branch(5, 8, 10, 'done')
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'done')
    a.lw(17, 4, 0xE94); a.lw(18, 4, 0xE98)
    for r in (17, 18):
        a.r(0x2B, 8, r, 10); a.branch(4, 8, 0, 'done')
    policy.emit_enemy(a, 17, 18, 'done', 'body_enemy')
    a.r(0, 8, 0, 17, 2); a.li(9, core.POINTERS); a.r(0x21, 8, 8, 9)
    a.lw(8, 8); a.branch(5, 4, 8, 'done')
    a.li(21, ROWS); a.move(19, 17); a.addiu(20, 0, 2)
    a.label('body'); a.r(0, 8, 0, 19, 2); a.li(9, core.POINTERS)
    a.r(0x21, 8, 8, 9); a.lw(22, 8)
    a.lw(8, 22); a.branch(5, 8, 19, 'done')
    a.lw(8, 22, 0xE90); a.addiu(9, 0, SCRIPT); a.branch(5, 8, 9, 'done')
    for off, r in ((0xE94, 17), (0xE98, 18)):
        a.lw(8, 22, off); a.branch(5, 8, r, 'done')
    a.lw(23, 22, 12); a.i(11, 8, 23, 12); a.branch(4, 8, 0, 'done')
    a.r(0, 8, 0, 23, 2); a.li(9, core.MODELS); a.r(0x21, 8, 8, 9); a.lw(24, 8)
    a.branch(4, 24, 0, 'done'); a.lw(8, 24, 16); a.branch(5, 8, 23, 'done')
    a.lw(8, 22, 0x994); a.lw(9, 22, 0x998); a.i(11, 11, 9, 6)
    a.branch(4, 11, 0, 'done'); a.r(0x2B, 11, 8, 9); a.branch(4, 11, 0, 'done')
    a.r(0, 9, 0, 8, 5); a.r(0x21, 11, 9, 8); a.r(0, 11, 0, 11, 2)
    a.r(0x21, 11, 11, 9); a.r(0x21, 25, 22, 11); a.addiu(25, 25, 0x9A4)
    for off, r in ((0, 19), (4, 22), (8, 23), (12, 24), (16, 25)): a.sw(r, 21, off)
    for dst, base, off in ((20,24,20), (24,24,12), (28,25,4), (32,25,64),
                            (36,25,68), (40,25,76), (44,25,84), (48,22,2376),
                            (52,22,4), (56,22,0x1278), (60,25,0x70)):
        a.lw(8, base, off); a.sw(8, 21, dst)
    a.addiu(20, 20, -1); a.move(19, 18); a.addiu(21, 21, 64)
    a.branch(5, 20, 0, 'body')
    a.lw(8, 16, 12); a.addiu(8, 8, 1); a.sw(8, 16, 12)
    a.label('done')
    for i, r in enumerate(saved): a.i(30, r, 29, i*16)
    a.addiu(29, 29, 0x200); a.jump(PICKER)
    result = a.finish(); assert len(result) < CONTROL-CODE; return result


def observe_memory(ram, source='<offline-memory>'):
    """Disposable diagnostic only. Does not claim or enable true body exchange."""
    w = world(ram)
    require(ram[PICK_CALL:PICK_CALL+8] == NATIVE(PICK_CALL, 8), 'Body Change picker call changed')
    require(ram[PICKER:PICKER+0xD8] == NATIVE(PICKER, 0xD8), 'Native random-body picker changed')
    require(not any(ram[CODE:END]), 'Body swap reservation occupied')
    parts = [(CODE, observe_code()), (CONTROL, struct.pack('<4I', MAGIC, w['manager'], w['count'], 0)),
             (ROWS, bytes(128)), (PICK_CALL, struct.pack('<I', (3 << 26)|(CODE >> 2)))]
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL,
                status='OBSERVE ONLY: STOCK RANDOM BODY CHANGE IS UNCHANGED',
                blocks=[dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex()) for p,b in parts])
