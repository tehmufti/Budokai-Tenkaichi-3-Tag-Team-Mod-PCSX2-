"""Three special activation pause modes for captured 2v2/3v3.

Native default is retained. The option narrows only the global pause generated
by actor flags125/126; normal impact timers, menu/loading pause, special
admission, authored cameras and paired animation handlers remain native.
Offline builders only; no PINE access.
"""
from native_map import A, CRC, FLAG_BITS, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import hitstop12
import cinematic_contact_guard as contact
import cinematic_admission as admission
import leader_transform_safety as transform
import team_intro
import result_presentation
from battle_mode_policy import ACTOR_COUNTS

FRAME, PREPARE, NATIVE, STORE = 0x07520000, 0x07520400, 0x07522000, 0x07522400
MELEE, CONTACT, CONTROL, END = 0x07522800, 0x07522C00, 0x0753F000, 0x07540000
MAGIC = 0x53505031
PAUSE_OTHERS = CONTROL + 4
MODE = PAUSE_OTHERS
MODES = {'target': 0, 'all': 1, 'none': 2}
MELEE_CALL = A(0x1C10E0)
SAVED = tuple(range(1, 29)) + (30, 31)


def save(a, registers, frame):
    a.addiu(29, 29, -frame)
    for i, r in enumerate(registers): a.i(63, r, 29, i*8)


def restore(a, registers, frame):
    for i, r in enumerate(registers): a.i(55, r, 29, i*8)
    a.addiu(29, 29, frame)


def mode_gate(a, fail, *, legacy=False, include_all=False):
    """t0..t3 clobbered; t2=count. Only an installed, captured combat phase."""
    core.gate(a, fail)
    a.li(8, CONTROL); a.lw(9, 8); a.li(11, MAGIC); a.branch(5, 9, 11, fail)
    a.lw(9, 8, 4)
    if legacy:
        a.branch(5, 9, 0, fail)
    else:
        if not include_all:
            a.addiu(11, 0, 1); a.branch(4, 9, 11, fail)
        a.i(11, 11, 9, 3); a.branch(4, 11, 0, fail)
    a.lw(9, 8, 8); a.lw(11, 28, -22364); a.branch(5, 9, 11, fail)
    a.lw(9, 8, 12); a.branch(5, 9, 10, fail)
    a.lw(9, 11, 628); a.branch(5, 9, 0, fail)
    a.li(9, core.PAIR+4); a.lw(9, 9); a.branch(5, 9, 0, fail)
    a.lw(9, 8, 16); a.li(11, team_intro.BATTLE); a.lw(11, 11)
    a.branch(5, 9, 11, fail); a.branch(4, 11, 0, fail)
    a.lw(9, 11); a.addiu(11, 0, 3); a.branch(5, 9, 11, fail)
    a.li(9, result_presentation.RESULT); a.lw(9, 9); a.branch(5, 9, 0, fail)


def frame_code():
    a = Assembler(FRAME); save(a, SAVED, 0x100)
    a.call(PREPARE)
    restore(a, SAVED, 0x100); a.jump(NATIVE)
    return a.finish()


def add_bit(a, register, accumulator):
    a.addiu(8, 0, 1); a.r(4, 8, register, 8); a.r(0x25, accumulator, accumulator, 8)


def prepare_code(*, legacy=False):
    a = Assembler(PREPARE)
    # FRAME saves every incoming GPR. This helper has no nested native calls.
    a.li(16, CONTROL); a.sw(0, 16, 20); a.sw(0, 16, 24); a.sw(0, 16, 28)
    if not legacy: a.sw(0, 16, 52)
    mode_gate(a, 'done', legacy=legacy)
    a.move(17, 10); a.move(18, 0); a.move(19, 0); a.move(20, 0)
    if not legacy: a.move(26, 0)
    a.li(21, core.POINTERS); a.addiu(22, 16, 0x80)
    # Validate the whole captured table before granting an exemption.
    a.label('validate'); a.lw(23, 21); a.lw(8, 22); a.branch(5, 23, 8, 'done')
    a.lw(8, 23); a.branch(5, 8, 18, 'done')
    a.lw(8, 23, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, 'done')
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x2D, 8, 8, 9)
    a.lw(8, 8); a.branch(4, 8, 0, 'done')
    a.lw(9, 8, 16); a.lw(8, 23, 12); a.branch(5, 8, 9, 'done')
    a.addiu(21, 21, 4); a.addiu(22, 22, 4); a.addiu(18, 18, 1)
    a.branch(5, 18, 17, 'validate')
    a.move(18, 0); a.li(21, core.POINTERS)
    a.label('owners'); a.lw(23, 21)
    # Native1DAC78 flag125/126 = OR of these two flag-bank bytes, bits5/6 (USA; native_map.FLAG_BITS).
    index, mask = FLAG_BITS((0x125, 0x126))
    a.i(36, 8, 23, 0x1085 + index); a.i(36, 9, 23, 0x10AD + index); a.r(0x25, 8, 8, 9)
    a.i(12, 8, 8, mask); a.branch(4, 8, 0, 'next_owner')
    a.lw(24, 23, 2376); a.addiu(8, 24, -253); a.i(11, 8, 8, 63)
    a.branch(4, 8, 0, 'done')  # transform/KO/non-special priority retains native global pause
    add_bit(a, 18, 19); add_bit(a, 18, 20)
    a.addiu(8, 24, -301); a.i(11, 8, 8, 3); a.branch(5, 8, 0, 'paired')
    a.addiu(8, 24, -313); a.i(11, 8, 8, 3); a.branch(5, 8, 0, 'paired')
    a.r(0, 8, 0, 18, 2); a.li(9, core.TABLE); a.r(0x2D, 8, 8, 9); a.lw(25, 8)
    a.r(0x2B, 8, 25, 17); a.branch(4, 8, 0, 'done')
    a.r(0x26, 8, 25, 18); a.i(12, 8, 8, 1); a.branch(4, 8, 0, 'done')
    add_bit(a, 25, 19); a.jump('next_owner')
    a.label('paired'); a.lw(24, 23, 3732); a.lw(25, 23, 3736)
    for r in (24, 25):
        a.r(0x2B, 8, r, 17); a.branch(4, 8, 0, 'done')
    a.branch(4, 24, 25, 'done'); a.branch(4, 18, 24, 'paired_member')
    a.branch(5, 18, 25, 'done')
    a.label('paired_member'); add_bit(a, 24, 19); add_bit(a, 25, 19)
    if not legacy: add_bit(a, 24, 26); add_bit(a, 25, 26)
    a.label('next_owner'); a.addiu(18, 18, 1); a.addiu(21, 21, 4)
    a.branch(5, 18, 17, 'owners'); a.branch(4, 20, 0, 'done')
    # Include any bound camera models, even if the active fighter's target
    # was captured before the camera finished binding the paired animation.
    a.lw(22, 28, -22180); a.branch(4, 22, 0, 'publish')
    a.lw(8, 22, 812); a.branch(5, 8, 0, 'camera')
    a.lw(8, 22, 704); a.branch(4, 8, 0, 'publish')
    a.lw(8, 22, 776); a.i(12, 8, 8, 3); a.addiu(9, 0, 1)
    a.branch(5, 8, 9, 'publish')
    a.label('camera')
    for off in (768, 772):
        a.lw(25, 22, off); a.branch(4, 25, 0, f'camera_next{off}')
        a.move(18, 0); a.li(21, core.POINTERS)
        a.label(f'camera_scan{off}'); a.lw(23, 21); a.lw(8, 23, 12)
        a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x2D, 8, 8, 9); a.lw(8, 8)
        a.branch(4, 8, 25, f'camera_found{off}')
        a.addiu(18, 18, 1); a.addiu(21, 21, 4); a.branch(5, 18, 17, f'camera_scan{off}')
        a.jump('done')  # Unrecognized cinematic subject: retain original behavior.
        a.label(f'camera_found{off}'); add_bit(a, 18, 19)
        if not legacy: add_bit(a, 18, 26)
        a.label(f'camera_next{off}')
    a.label('publish'); a.sw(19, 16, 24); a.sw(20, 16, 44)
    if not legacy:
        # Freely moving, unbound targets must not become invulnerable in none
        # mode. The caster and actually bound animation subjects remain safe.
        a.lw(8, 16, 4); a.addiu(9, 0, 2); a.branch(5, 8, 9, 'contact_members')
        a.r(0x25, 19, 20, 26)
        a.label('contact_members'); a.sw(19, 16, 52)
    a.addiu(8, 0, 1); a.sw(8, 16, 20)
    a.lw(8, 16, 32); a.addiu(8, 8, 1); a.sw(8, 16, 32)
    a.label('done'); a.jr()
    data = a.finish(); assert len(data) <= NATIVE-PREPARE; return data


def native_code():
    data, _ = core.rebound(hitstop12.relocated_code, CODE=NATIVE, COUNT=core.HITSTOP_COUNT)()
    data = bytearray(data); off = A(0x1C0D84)-hitstop12.ENTRY
    assert data[off:off+8] == struct.pack('<2I', 0xAE001328, 0xAE121324)
    struct.pack_into('<2I', data, off, (3<<26)|(STORE>>2), 0)
    return bytes(data)


def store_code(*, legacy=False):
    # Replacement for only the two unconditional global pending-timer stores.
    # s0=actor, s1=physical index+1, s2=1. Preserve every native live register.
    a = Assembler(STORE); regs = (8, 9, 10, 11); save(a, regs, 0x20)
    a.li(8, CONTROL); a.lw(9, 8, 20); a.branch(4, 9, 0, 'native')
    if not legacy:
        a.lw(9, 8, 4); a.addiu(10, 0, 2); a.branch(4, 9, 10, 'skip')
    a.addiu(9, 17, -1); a.addiu(10, 0, 1); a.r(4, 10, 9, 10)
    a.lw(9, 8, 24); a.r(0x24, 9, 9, 10); a.branch(5, 9, 0, 'member')
    if not legacy: a.label('skip')
    a.lw(9, 8, 36); a.addiu(9, 9, 1); a.sw(9, 8, 36); a.jump('done')
    a.label('member'); a.lw(9, 8, 28); a.r(0x25, 9, 9, 10); a.sw(9, 8, 28)
    a.label('native'); a.sw(0, 16, 4904); a.sw(18, 16, 4900)
    a.label('done'); restore(a, regs, 0x20); a.jr()
    return a.finish()


def melee_code(*, legacy=False):
    # The global melee pass may proceed past a special-frozen participant.
    # Actual timers still protect that actor's native update and contact tests.
    a = Assembler(MELEE); regs = (3, 8, 9, 10, 11, 12, 13); save(a, regs, 0x40)
    mode_gate(a, 'native', legacy=legacy); a.li(8, CONTROL); a.lw(9, 8, 20); a.branch(4, 9, 0, 'native')
    a.lw(9, 4, 4896); a.addiu(11, 0, 1); a.branch(5, 9, 11, 'native')
    a.li(12, core.POINTERS); a.move(13, 0)
    a.label('scan'); a.lw(9, 12); a.branch(4, 9, 4, 'found')
    a.addiu(12, 12, 4); a.addiu(13, 13, 1); a.branch(5, 13, 10, 'scan'); a.jump('native')
    a.label('found'); a.r(4, 11, 13, 11); a.lw(9, 8, 28); a.r(0x24, 9, 9, 11)
    a.branch(4, 9, 0, 'native'); a.lw(9, 8, 40); a.addiu(9, 9, 1); a.sw(9, 8, 40)
    a.move(2, 0); restore(a, regs, 0x40); a.jr()
    a.label('native'); restore(a, regs, 0x40); a.jump(A(0x1DC2C0))
    return a.finish()


def contact_code(*, legacy=False):
    # During the narrowed activation pause, explicitly exclude outside damage
    # against the protected caster/target even before paired camera binding.
    a = Assembler(CONTACT); mode_gate(a, 'native', legacy=legacy)
    a.li(8, CONTROL); a.lw(9, 8, 20); a.branch(4, 9, 0, 'native')
    a.move(12, 0); a.move(13, 0); a.li(11, core.POINTERS)
    a.label('scan'); a.lw(9, 11); a.addiu(14, 0, 1); a.r(4, 14, 12, 14)
    a.branch(5, 9, 4, 'not_source'); a.r(0x25, 13, 13, 14)
    a.label('not_source'); a.branch(5, 9, 5, 'next'); a.move(15, 14)
    a.label('next'); a.addiu(11, 11, 4); a.addiu(12, 12, 1); a.branch(5, 12, 10, 'scan')
    a.branch(4, 13, 0, 'native')
    # Resolve target separately so an unregistered target cannot reuse t7.
    a.move(12, 0); a.li(11, core.POINTERS)
    a.label('target'); a.lw(9, 11); a.branch(4, 9, 5, 'found_target')
    a.addiu(11, 11, 4); a.addiu(12, 12, 1); a.branch(5, 12, 10, 'target'); a.jump('native')
    a.label('found_target'); a.addiu(15, 0, 1); a.r(4, 15, 12, 15)
    a.lw(9, 8, 24 if legacy else 52); a.r(0x24, 14, 9, 13); a.branch(5, 14, 0, 'native')
    a.r(0x24, 14, 9, 15); a.branch(4, 14, 0, 'native')
    a.lw(9, 8, 48); a.addiu(9, 9, 1); a.sw(9, 8, 48); a.addiu(2, 0, 1); a.jr()
    a.label('native'); a.jump(transform.PROTECTED)
    return a.finish()


def program(*, legacy=False):
    return [(FRAME, frame_code()), (PREPARE, prepare_code(legacy=legacy)), (NATIVE, native_code()),
            (STORE, store_code(legacy=legacy)), (MELEE, melee_code(legacy=legacy)), (CONTACT, contact_code(legacy=legacy)),
            (hitstop12.ENTRY, struct.pack('<2I', (2<<26)|(FRAME>>2), 0)),
            (MELEE_CALL, struct.pack('<I', (3<<26)|(MELEE>>2))),
            (contact.PROTECTED, struct.pack('<2I', (2<<26)|(CONTACT>>2), 0))]


def identity(ram):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count, battle = u(core.ACTORS), u(core.MODE+12), u(team_intro.BATTLE)
    if (count not in ACTOR_COUNTS or not 0x100000 <= manager < len(ram)-0x1000
            or u(manager) != 2 or u(core.MODE+8) != manager or u(core.MODE+4) != count
            or not 0x100000 <= battle < len(ram)-300 or u(core.PAIR+4)):
        raise ValueError('Captured4/6 identities and restored aliases required')
    actors = [u(core.POINTERS+4*i) for i in range(count)]
    for i, actor in enumerate(actors):
        if not 0x100000 <= actor < len(ram)-0x1600 or u(actor) != i or u(actor+12) >= 12:
            raise ValueError('Invalid captured fighter')
    if len(set(actors)) != count: raise ValueError('Duplicate captured fighter')
    return manager, count, battle, actors


def beam_chain_dependencies(ram, manager, count):
    """Allow optional clash wrappers only as complete captured programs."""
    import beam_clash as beam
    import dash_clash as dash
    import multi_contact
    actual_ram=ram
    ram=multi_contact.base_view(ram,manager,count)
    multi_pieces=multi_contact.installed_pieces(actual_ram) if ram is not actual_ram else []
    native=elf_reader(elf_path(ROOT))[2]
    dash_pieces=[]
    beam_ram=ram
    if any(ram[dash.CODE:dash.END]):
        if struct.unpack_from('<3I',ram,dash.CONTROL)!=(dash.MAGIC,manager,count):
            raise ValueError('Required dash capture ownership changed')
        if dash.build_memory(ram)['blocks']:
            raise ValueError('Required dash binding chain is incomplete')
        dash_pieces=[(p,data+native(p+4,4) if p in dash.ACTOR_CALLS else data)
                     for p,data in dash.installed_pieces(ram)]
        # Validate the known outer program first, then reconstruct only the
        # four reviewed beam entry overrides for its strict inner validator.
        # This copy is never installed or returned as a patch.
        beam_ram=bytearray(ram)
        overrides=dict(dash_pieces)
        for p,data in beam.pieces(native):
            if p in overrides:beam_ram[p:p+len(data)]=data
    if not any(ram[beam.CODE:beam.END]):
        if dash_pieces:raise ValueError('Required inner beam binding is missing')
        return []
    # The builder validates every native callsite, wrapper, captured actor,
    # model identity and immutable header. Mutable clash counters remain free.
    if struct.unpack_from('<3I',ram,beam.CONTROL) != (beam.MAGIC,manager,count):
        raise ValueError('Required beam capture ownership changed')
    if beam.build_memory(beam_ram)['blocks']:
        raise ValueError('Required beam binding chain is incomplete')
    # A call patch changes one word, but its unchanged delay instruction is
    # part of the callable contract and must remain exact on reconfiguration.
    callsites={p for sites in beam.CALLS.values() for p in sites}
    pieces=[(p,data+native(p+4,4) if p in callsites else data) for p,data in beam.pieces(native)]
    pieces=list((dict(pieces)|dict(dash_pieces)|dict(multi_pieces)).items())
    import beam_struggle
    pieces=beam_struggle.with_overlay(actual_ram,pieces)
    for p,data in pieces:
        if actual_ram[p:p+len(data)] != data:raise ValueError(f'Required beam binding code changed:{p:08X}')
    return pieces


def with_beam_entries(expected, beam_pieces):
    """Replace only reviewed entry bytes, preserving every preceding tail."""
    overrides=dict(beam_pieces)
    result=[]
    for address,data in expected:
        replacement=overrides.get(address)
        if replacement is not None:
            if len(replacement)>len(data):raise ValueError('Beam wrapper exceeds preserved dependency entry')
            data=replacement+data[len(replacement):]
        result.append((address,data))
    return result


def camera_continuity_dependencies(ram, manager, count, throws):
    """Recognize only the complete reviewed camera/throw successor chain."""
    import camera_continuity as continuity
    import camera_successor as successor
    import cinematic_camera_state as camera
    import fresh_team_camera as fresh
    import leader_camera as leader
    import team_intro_camera as intro_camera
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if struct.unpack_from('<4I', ram, continuity.CONTROL) != (1, manager, count, 1):
        raise ValueError('Required camera continuity ownership is inactive')
    for control in (fresh.SUCCESSOR_CONTROL, camera.CONTROL):
        if (u(control), u(control+4)) != (1, manager):
            raise ValueError('Required camera ownership belongs to another capture')
    if u(fresh.LEADER_CONTROL) != 1:
        raise ValueError('Required leader camera selection is inactive')
    jump = lambda target: struct.pack('<2I', (2<<26)|(target>>2), 0)
    old_lookup = fresh.rebound(successor.lookup_stub, LOOKUP=fresh.LOOKUP)()
    old_inner = fresh.rebound(leader.payload_cinematic, Assembler=fresh.FreshAssembler,
                             CODE=fresh.LEADER_INNER, CONTROL=fresh.LEADER_CONTROL)()
    offset = leader.PARTICIPANT_OFFSET
    native_participant = old_inner[offset:offset+8]+jump(camera.HELPER_ENTRY+8)
    current_inner = old_inner[:offset]+jump(camera.PARTICIPANT)+old_inner[offset+8:]
    expected = [(p, data) for p, data, _ in continuity.pieces(manager, count)
                if p != continuity.CONTROL]
    expected += [(throws.PARTICIPANT, jump(continuity.CODE)+throws.participant_code()[8:]),
                 (fresh.LOOKUP, jump(continuity.LOOKUP)+old_lookup[8:]),
                 (camera.PARTICIPANT, jump(throws.PARTICIPANT)+camera.participant()[8:]),
                 (leader.HOOK, jump(camera.CODE)), (camera.CODE, camera.wrapper()),
                 (fresh.LEADER_INNER, current_inner),
                 (camera.OLD_PARTICIPANT, native_participant),
                 (fresh.GATE, fresh.gate_code()),
                 (fresh.LEADER_NATIVE, leader.ORIGINAL+jump(leader.HOOK+8))]
    # Result and intro presentation may wrap the same leader scope. Recognize
    # only their complete known payloads, captured controls and preserved tail.
    scope = fresh.scope(fresh.LEADER, fresh.LEADER_INNER, fresh.LEADER_NATIVE)
    entry = ram[fresh.LEADER:fresh.LEADER+8]
    previous = None
    if entry == jump(intro_camera.CODE):
        if struct.unpack_from('<3I', ram, intro_camera.CONTROL) != (1, manager, count):
            raise ValueError('Required intro camera ownership changed')
        for target in (intro_camera.TRAMPOLINE, result_presentation.SELECTOR):
            data = intro_camera.payload(target)
            if ram[intro_camera.CODE:intro_camera.CODE+len(data)] == data:
                previous = target
                break
        if previous is None: raise ValueError('Required intro camera wrapper changed')
        expected += [(intro_camera.CODE, intro_camera.payload(previous)),
                     (fresh.LEADER, jump(intro_camera.CODE)+scope[8:])]
        if previous == intro_camera.TRAMPOLINE:
            expected.append((intro_camera.TRAMPOLINE, scope[:8]+jump(fresh.LEADER+8)))
    elif entry == jump(result_presentation.SELECTOR):
        previous = result_presentation.SELECTOR
        expected.append((fresh.LEADER, jump(previous)+scope[8:]))
    else:
        expected.append((fresh.LEADER, scope))
    if previous == result_presentation.SELECTOR:
        if struct.unpack_from('<3I', ram, result_presentation.CONTROL) != (1, manager, count):
            raise ValueError('Required result camera ownership changed')
        expected += [(result_presentation.GATE, result_presentation.gate()),
                     (result_presentation.SELECTOR, result_presentation.wrapper(
                         result_presentation.SELECTOR, fresh.LEADER, fresh.LEADER_NATIVE, scope[:8], 20))]
    beam_pieces=beam_chain_dependencies(ram,manager,count)
    import cinematic_policy
    return cinematic_policy.dependency_overrides(
        ram, with_beam_entries(expected,beam_pieces)+beam_pieces, manager, count)


def dependencies(ram, manager, count):
    import battle_modes
    ram = battle_modes.base_view(ram, manager, count)
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    for ctrl, count_off in ((contact.CONTROL, 8), (admission.CONTROL, 8), (transform.CONTROL, 12)):
        if u(ctrl) != 1 or u(ctrl+4) != manager or u(ctrl+count_off) != count:
            raise ValueError('Required admission/contact protection is inactive')
    _, _, native = elf_reader(elf_path(ROOT))
    needed = [(admission.PREDICATE, admission.predicate_code()),
              (contact.GATE, contact.gate_code()), (transform.PROTECTED, transform.protected_code()),
              (transform.FALLBACK, transform.prior_contact()),
              (core.HITSTOP, core.rebound(hitstop12.relocated_code, CODE=core.HITSTOP, COUNT=core.HITSTOP_COUNT)()[0]),
              (core.HITSTOP_COUNT, core.rebound(hitstop12.count_code, COUNT=core.HITSTOP_COUNT)()),
              (A(0x1DC2C0), native(A(0x1DC2C0), 12))]
    import inactive_actor_guard
    needed=[(p,inactive_actor_guard.dependency_override(ram,p,data)) for p,data in needed]
    for i, (entry, cave, kind, rejected) in enumerate(contact.SPECS):
        needed += [(entry, struct.pack('<2I', (2<<26)|(cave>>2), 0)),
                   (cave, contact.wrapper(entry, cave, kind, rejected, native(entry, 8), i))]
    if ram[transform.FALLBACK:transform.FALLBACK+8] != transform.prior_contact()[:8]:
        # The reviewed throw extension wraps this fallback AFTER the unchanged
        # leader reload veto. Accept its full program and ownership, never a
        # bare jump that could silently remove the original contact safety.
        import extra_throws as throws
        if struct.unpack_from('<4I',ram,throws.CONTROL) != (1,manager,count,1):
            raise ValueError('Required throw contact protection is inactive')
        needed = [(p,b) for p,b in needed if p != transform.FALLBACK]
        throw_pieces = throws.pieces()
        if ram[throws.PARTICIPANT:throws.PARTICIPANT+8] != throws.participant_code()[:8]:
            # The camera addon wraps exactly this entry, preserving its complete
            # tail and trampoline. All other throw safety pieces remain exact.
            camera_pieces = camera_continuity_dependencies(ram, manager, count, throws)
            throw_pieces = [(p, data) for p, data in throw_pieces if p != throws.PARTICIPANT]
            needed += camera_pieces
        needed += throw_pieces
        needed += [(p,struct.pack('<2I',(2<<26)|(target>>2),0)) for p,target in throws.HOOKS]
    if ram[transform.PROTECTED:transform.PROTECTED+8] != transform.protected_code()[:8]:
        # Optional private form reloads add protection BEFORE the original
        # leader veto; its full remaining body and trampoline stay unchanged.
        import extra_reload_form_contacts as form_contacts
        form_contacts.validate_memory(ram, manager, count)
        needed = [(p,b) for p,b in needed if p != transform.PROTECTED]
    # Beam struggles wrap the same resolver/contact/camera entries after
    # throws. Retain every old body and accept only the complete reviewed
    # outer wrapper, never an arbitrary jump at one of those entries.
    beam_pieces=beam_chain_dependencies(ram,manager,count)
    needed=with_beam_entries(needed,beam_pieces)+beam_pieces
    for p, data in needed:
        if ram[p:p+len(data)] != data: raise ValueError(f'Required safety code changed:{p:08X}')


def normalize_mode(mode=None, pause_others=None):
    """Version1 False remains target-only; True remains the native default."""
    if pause_others is not None and type(pause_others) is not bool:
        raise ValueError('pause_others must be bool')
    if mode is None:
        return 'target' if pause_others is False else 'all'
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError('mode must be all, target, or none')
    if pause_others is not None and mode != ('all' if pause_others else 'target'):
        raise ValueError('Conflicting mode and legacy pause_others')
    return mode


def installed_program(ram, manager, count, *, legacy=False):
    """Retain a verified fusion reservation guard outside the pause policy."""
    import battle_modes
    original = ram
    ram = battle_modes.base_view(ram, manager, count)
    parts = program(legacy=legacy)
    old = struct.pack('<2I', (2<<26)|(CONTACT>>2), 0)
    if ram[contact.PROTECTED:contact.PROTECTED+8] != old:
        import fusion_partner_lifecycle as fusion
        fusion.validate_contact_memory(ram, manager, count)
        outer = struct.pack('<2I', (2<<26)|(fusion.CONTACT>>2), 0)
        parts = [(p, outer if p == contact.PROTECTED else data) for p, data in parts]
    if not legacy:
        import cinematic_policy
        parts = cinematic_policy.dependency_overrides(ram, parts, manager, count)
    # The mode validator above proves the complete co-op prefix before its
    # canonical view is exposed to older dependency validators. Keep that
    # actual outer hook in comparisons and upgrades; never remove it while
    # changing the user's pause setting.
    if original is not ram:
        parts = [(p, original[p:p+len(data)] if p == contact.PROTECTED else data)
                 for p, data in parts]
    return parts


def installed_version(ram, manager, count, battle, actors):
    prefix = struct.unpack_from('<5I', ram, CONTROL)
    if prefix != (MAGIC, prefix[1], manager, count, battle) or prefix[1] not in MODES.values():
        raise ValueError('Special-pause control ownership mismatch')
    if list(struct.unpack_from('<'+'I'*count, ram, CONTROL+0x80)) != actors:
        raise ValueError('Special-pause captured pointers changed')
    for legacy in (False, True):
        if all(ram[p:p+len(data)] == data for p, data in installed_program(ram, manager, count, legacy=legacy)):
            if legacy and prefix[1] not in (0, 1):
                raise ValueError('Invalid legacy option')
            return 1 if legacy else 2
    raise ValueError('Installed special-pause code changed')


def manifest(ram, pieces, mode, source):
    intervals = sorted((p, p+len(d)) for p, d in pieces)
    assert all(end <= q for (_, end), (q, _) in zip(intervals, intervals[1:]))
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL,
                version=2, mode_address=MODE, mode=mode,
                pause_others_address=PAUSE_OTHERS, pause_others={'all':True, 'target':False, 'none':None}[mode],
                status='THREE SPECIAL ACTIVATION PAUSE MODES; SEPTEMBER14 LIVE VALIDATION REQUIRED',
                blocks=[dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex()) for p,d in pieces],
                limitations=['Ordinary impact hitstop, global menu/loading pause and unrecognized priority states retain native behavior.',
                             'Special sequences remain serialized; bound actors keep authored animation/camera handlers.',
                             'None mode removes generated activation stops, not ordinary impact timers or loading pauses.'])


def build_memory(ram, config=None, source='<offline-memory>', *, pause_others=None, mode=None):
    mode = normalize_mode(mode, pause_others)
    manager, count, battle, actors = identity(ram); dependencies(ram, manager, count)
    if any(ram[FRAME:END]):
        version = installed_version(ram, manager, count, battle, actors)
        if version == 2:
            return configure_memory(ram, source=source, mode=mode)
        control = bytearray(ram[CONTROL:CONTROL+0x100])
        struct.pack_into('<I', control, 4, MODES[mode])
        control[20:32] = bytes(12); control[52:56] = bytes(4)
        pieces = [(p,d) for p,d in installed_program(ram, manager, count) if ram[p:p+len(d)] != d]
        pieces.append((CONTROL, bytes(control)))
        result = manifest(ram, pieces, mode, source); result['upgrade_from'] = 1
        return result
    for p, data in ((hitstop12.ENTRY, struct.pack('<2I', (2<<26)|(core.HITSTOP>>2), 0)),
                    (MELEE_CALL, struct.pack('<I', (3<<26)|(A(0x1DC2C0)>>2))),
                    (contact.PROTECTED, struct.pack('<2I', (2<<26)|(transform.PROTECTED>>2), 0))):
        if ram[p:p+len(data)] != data: raise ValueError(f'Existing hook changed:{p:08X}')
    control = bytearray(0x100)
    struct.pack_into('<5I', control, 0, MAGIC, MODES[mode], manager, count, battle)
    struct.pack_into('<'+'I'*count, control, 0x80, *actors)
    pieces = program()+[(CONTROL, bytes(control))]
    return manifest(ram, pieces, mode, source)


def configure_memory(ram, pause_others=None, source='<offline-memory>', *, mode=None):
    mode = normalize_mode(mode, pause_others)
    manager, count, battle, actors = identity(ram); dependencies(ram, manager, count)
    version = installed_version(ram, manager, count, battle, actors)
    if version == 1 and mode == 'none':
        raise ValueError('Legacy special-pause code must be upgraded with build_memory before none mode')
    data = struct.pack('<I', MODES[mode]); before = ram[MODE:MODE+4]
    pieces = [] if before == data else [(MODE, data)]
    result = manifest(ram, pieces, mode, source); result['version'] = version
    return result


def build(source, *, pause_others=None, mode=None):
    return build_memory(read_ram(source), source=source, pause_others=pause_others, mode=mode)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path); p.add_argument('--continue-others', action='store_true')
    p.add_argument('--mode', choices=tuple(MODES))
    args = p.parse_args(); result = build(args.source, mode=args.mode,
                                         pause_others=False if args.continue_others else None)
    args.out.write_text(json.dumps(result, indent=2)+'\n'); print(args.out)
