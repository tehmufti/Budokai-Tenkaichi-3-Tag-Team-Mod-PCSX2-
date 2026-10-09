"""Team ring-outs using the game's own tournament collision decisions.

The native collision solver (1CD558) sets flag 7 at exactly three sites, after
checking tournament rules and the authored contact/surface flags. Intercepting
those decisions preserves airborne, edge, destroyed-stage and scaled geometry
behavior without inventing a rectangle or a world-height threshold.

For a captured match a ring-out eliminates that actor, not its whole team.
The normal full-team/FFA HP predicate still selects the result. A separate
per-actor mask forbids reviving an eliminated body. The preference can disable
ring-outs in modded matches; native/unowned matches keep the original rules.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import battle_mode_policy as policy
import fresh_team_combat as core
import team_participation as participation
import team_start_gate as start
import teammate_revive as revival

BASE, END = 0x06F90000, 0x06F93000
GATE, LOOKUP, CONTACT, RESULT = BASE, BASE+0x200, BASE+0x600, BASE+0xC00
REVIVE, REVIVE_NATIVE, RESULT_NATIVE, CONTROL = BASE+0x1000, BASE+0x1400, BASE+0x1800, BASE+0x2000
MAGIC, VERSION = 0x52494E47, 1
KEY = 'tournament_ring_outs'
F = dict(magic=0, version=4, manager=8, count=12, enabled=16, eliminated=20,
         contacts=24, last_actor=28, pointers=64)
CONTACT_HOOKS = (A(0x1CD918), A(0x1CD93C), A(0x1CD960))
RESULT_HOOK, NATIVE_SET = A(0x20B8F0), A(0x1DA9D0)
NATIVE = elf_reader(elf_path(ROOT))[2]
JUMP = lambda p: struct.pack('<2I', (2 << 26) | (p >> 2), 0)
CALL = lambda p: struct.pack('<I', (3 << 26) | (p >> 2))
SAVED = tuple(range(3, 26)) + (31,)


def save(a):
    a.addiu(29, 29, -0xC0)
    for i, r in enumerate(SAVED): a.i(63, r, 29, i*8)


def restore(a):
    for i, r in enumerate(SAVED): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0xC0)


def gate():
    """Captured installation identity -> count or zero; never a stage guess."""
    a = Assembler(GATE); core.gate(a, 'no')
    a.li(11, CONTROL); a.lw(8, 11); a.li(9, MAGIC); a.branch(5, 8, 9, 'no')
    a.lw(8, 11, F['version']); a.addiu(9, 0, VERSION); a.branch(5, 8, 9, 'no')
    a.lw(8, 11, F['manager']); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'no')
    a.lw(8, 11, F['count']); a.branch(5, 8, 10, 'no')
    a.move(2, 10); a.jr(); a.label('no'); a.move(2, 0); a.jr()
    return a.finish()


def lookup():
    """Actual actor pointer -> physical index + 1 and current HP address.

    Pointer identity remains valid inside the engine's temporary role aliases.
    Only a present, unconsumed fighter and a valid native row can be changed.
    """
    a = Assembler(LOOKUP); a.addiu(29, 29, -16); a.i(63, 31, 29, 0)
    a.call(GATE); a.branch(4, 2, 0, 'no'); a.move(15, 2)
    a.li(11, CONTROL+F['pointers']); a.li(12, core.POINTERS); a.move(13, 0)
    a.label('scan'); a.lw(8, 11); a.lw(9, 12); a.branch(5, 8, 9, 'no')
    a.branch(4, 8, 4, 'found'); a.addiu(11, 11, 4); a.addiu(12, 12, 4)
    a.addiu(13, 13, 1); a.branch(5, 13, 15, 'scan'); a.jump('no')
    a.label('found'); a.li(11, participation.CONTROL)
    a.lw(8, 11, 4); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'no')
    a.lw(8, 11, 8); a.branch(5, 8, 15, 'no')
    a.lw(8, 11, 12); a.lw(9, 11, 16); a.r(0x27, 9, 9, 0); a.r(0x24, 8, 8, 9)
    a.addiu(9, 0, 1); a.r(4, 9, 13, 9); a.r(0x24, 8, 8, 9); a.branch(4, 8, 0, 'no')
    a.lw(8, 4, 0x994); a.i(11, 9, 8, 5); a.branch(4, 9, 0, 'no')
    a.lw(9, 4, 0x998); a.i(11, 10, 9, 6); a.branch(4, 10, 0, 'no')
    a.r(0x2B, 10, 8, 9); a.branch(4, 10, 0, 'no')
    a.r(0, 3, 0, 8, 7); a.r(0, 9, 0, 8, 5); a.r(0x2D, 3, 3, 9)
    a.r(0, 8, 0, 8, 2); a.r(0x2D, 3, 3, 8); a.r(0x2D, 3, 3, 4)
    a.addiu(3, 3, 0x9E4); a.addiu(2, 13, 1); a.jump('done')
    a.label('no'); a.move(2, 0); a.move(3, 0)
    a.label('done'); a.i(55, 31, 29, 0); a.addiu(29, 29, 16); a.jr()
    return a.finish()


def contact():
    """Replace only a native collision solver's flag-7 set, never all setters."""
    a = Assembler(CONTACT); save(a); a.call(LOOKUP); a.branch(4, 2, 0, 'native')
    a.move(16, 2); a.move(17, 3); a.li(18, CONTROL)
    # A held intro/preparation or a completed match cannot eliminate a fighter.
    for p in (start.CONTROL, A(0x333700)):
        a.li(8, p); a.lw(8, 8); a.branch(5, 8, 0, 'suppress')
    a.li(8, A(0x2FEB38)); a.lw(8, 8); a.branch(4, 8, 0, 'suppress')
    a.lw(8, 8); a.addiu(9, 0, 3); a.branch(5, 8, 9, 'suppress')
    a.lw(8, 18, F['enabled']); a.branch(4, 8, 0, 'suppress')
    a.addiu(16, 16, -1); a.addiu(9, 0, 1); a.r(4, 9, 16, 9)
    a.lw(8, 18, F['eliminated']); a.r(0x24, 10, 8, 9); a.branch(5, 10, 0, 'zero')
    a.r(0x25, 8, 8, 9); a.sw(8, 18, F['eliminated'])
    a.lw(8, 18, F['contacts']); a.addiu(8, 8, 1); a.sw(8, 18, F['contacts'])
    a.sw(4, 18, F['last_actor'])
    a.label('zero'); a.sw(0, 17)
    # The ordinary KO dispatcher, spectator handoff and victory predicates now
    # observe zero HP. Retain the native out flag for its announcement/state.
    a.label('native'); restore(a); a.jump(NATIVE_SET)
    a.label('suppress'); restore(a); a.move(2, 0); a.jr()
    return a.finish()


def result(original):
    """Suppress leader-only ring victory; team/FFA exhaustion remains native."""
    a = Assembler(RESULT); save(a); a.call(GATE); a.branch(4, 2, 0, 'native')
    # Form swaps, scripted healing and fusion splits must not undo an out.
    # Native result evaluation follows fighter updates and runs before the
    # existing team/FFA HP predicate. Pointer/row guards remain authoritative.
    a.move(16, 2); a.move(17, 0); a.li(18, CONTROL)
    a.lw(19, 18, F['eliminated']); a.branch(4, 19, 0, 'done')
    a.label('scan'); a.addiu(8, 0, 1); a.r(4, 8, 17, 8); a.r(0x24, 8, 8, 19)
    a.branch(4, 8, 0, 'next'); a.r(0, 8, 0, 17, 2); a.r(0x2D, 8, 18, 8)
    a.lw(4, 8, F['pointers']); a.call(LOOKUP); a.branch(4, 2, 0, 'next'); a.sw(0, 3)
    a.label('next'); a.addiu(17, 17, 1); a.branch(5, 17, 16, 'scan')
    a.label('done')
    restore(a); a.move(2, 0); a.jr()
    a.label('native'); restore(a); a.jump(RESULT_NATIVE)
    payload = a.finish()
    b = Assembler(RESULT_NATIVE)
    for word in struct.unpack('<2I', original): b.emit(word)
    b.jump(RESULT_HOOK+8)
    return payload, b.finish()


def revive():
    """The existing revival actor resolver returns no candidate for ring-outs."""
    a = Assembler(REVIVE); save(a); a.call(GATE); a.branch(4, 2, 0, 'native')
    a.r(0x2B, 8, 4, 2); a.branch(4, 8, 0, 'native')
    a.li(8, CONTROL); a.lw(8, 8, F['eliminated']); a.addiu(9, 0, 1)
    a.r(4, 9, 4, 9); a.r(0x24, 8, 8, 9); a.branch(4, 8, 0, 'native')
    restore(a); a.move(2, 0); a.move(3, 0); a.jr()
    a.label('native'); restore(a); a.jump(REVIVE_NATIVE)
    return a.finish()


def program(with_revive=True):
    result_body, result_tail = result(NATIVE(RESULT_HOOK, 8))
    out = [(GATE, gate()), (LOOKUP, lookup()), (CONTACT, contact()),
           (RESULT, result_body), (RESULT_NATIVE, result_tail), (RESULT_HOOK, JUMP(RESULT))]
    out += [(p, CALL(CONTACT)) for p in CONTACT_HOOKS]
    if with_revive:
        out += [(REVIVE, revive()),
                (REVIVE_NATIVE, core.rebound(revival.actor, ACTOR=REVIVE_NATIVE)()),
                (revival.ACTOR, JUMP(REVIVE))]
    ordered = sorted((p, p+len(data)) for p, data in out if BASE <= p < END)
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError('Tournament ring-out programs overlap')
    if ordered[-1][1] > CONTROL: raise ValueError('Tournament code overlaps control')
    return out


def dependency_override(ram, address, expected):
    """Recognize the owned revival wrapper without weakening other validators."""
    if address != revival.ACTOR or len(ram) < END: return expected
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if u(CONTROL) != MAGIC: return expected
    if u(CONTROL+F['version']) != VERSION: raise ValueError('Unknown tournament ring-out version')
    if ram[REVIVE:REVIVE+len(revive())] != revive(): raise ValueError('Ring-out revival wrapper changed')
    original = core.rebound(revival.actor, ACTOR=REVIVE_NATIVE)()
    if ram[REVIVE_NATIVE:REVIVE_NATIVE+len(original)] != original:
        raise ValueError('Ring-out revival continuation changed')
    return JUMP(REVIVE)+expected[8:]


@policy.matching_install
def build_memory(ram, settings=None, source='<prepared>'):
    if len(ram) != 0x8000000: raise ValueError('Tournament rules require full 128 MiB EE RAM')
    enabled = (settings or {}).get(KEY, True)
    if type(enabled) is not bool: raise ValueError('Tournament ring-outs must be Boolean')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if (count not in policy.ACTOR_COUNTS or (u(core.MODE+8), u(core.MODE+12)) != (manager, count)
            or not 0x100000 <= manager <= 0x7FFFF00 or u(manager) != 2):
        raise ValueError('Tournament rules require a captured fighter manager')
    if (u(participation.CONTROL+4), u(participation.CONTROL+8)) != (manager, count):
        raise ValueError('Tournament rules require captured participation')
    with_revive = u(revival.CONTROL) == revival.MAGIC
    pieces = program(with_revive)
    if u(CONTROL) == MAGIC:
        if (u(CONTROL+4), u(CONTROL+8), u(CONTROL+12)) != (VERSION, manager, count):
            raise ValueError('Tournament ring-out installation identity changed')
        for p, data in pieces:
            if ram[p:p+len(data)] != data: raise ValueError(f'Tournament program changed at {p:08X}')
        for i in range(count):
            if u(CONTROL+F['pointers']+4*i) != u(core.POINTERS+4*i):
                raise ValueError('Tournament actor pointer changed')
        new = struct.pack('<I', int(enabled)); p = CONTROL+F['enabled']
        blocks = [] if ram[p:p+4] == new else [dict(address=p, expected_hex=ram[p:p+4].hex(), data_hex=new.hex())]
        return dict(source=str(source), blocks=blocks, control=CONTROL, status='TOURNAMENT RULES VERIFIED')
    if any(ram[BASE:END]): raise ValueError('Tournament ring-out reservation occupied')
    for p in CONTACT_HOOKS:
        if ram[p:p+8] != NATIVE(p, 8) or NATIVE(p, 8) != CALL(NATIVE_SET)+struct.pack('<I', 0x24050007):
            raise ValueError(f'Native tournament collision decision changed at {p:08X}')
    if ram[RESULT_HOOK:RESULT_HOOK+8] != NATIVE(RESULT_HOOK, 8):
        raise ValueError('Native tournament result predicate changed')
    if with_revive and ram[revival.ACTOR:revival.ACTOR+len(revival.actor())] != revival.actor():
        raise ValueError('Revival actor resolver changed before tournament installation')
    control = bytearray(0x100)
    struct.pack_into('<5I', control, 0, MAGIC, VERSION, manager, count, int(enabled))
    for i in range(count):
        actor = u(core.POINTERS+4*i)
        if not 0x100000 <= actor <= 0x8000000-0x1600 or u(actor) != i:
            raise ValueError('Tournament actor pointer invalid')
        struct.pack_into('<I', control, F['pointers']+4*i, actor)
    pieces.append((CONTROL, bytes(control)))
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL,
                status='NATIVE COLLISION TEAM RING-OUTS',
                blocks=[dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex()) for p, b in pieces],
                evidence='Only stock collision-surface flag-7 decisions eliminate; the existing team/FFA HP result decides victory.',
                limitations=['Applies only to captured modded matches; original game tournament rules remain native.'])
