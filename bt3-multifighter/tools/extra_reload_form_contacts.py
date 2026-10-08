"""Keep a captured extra's pending native transformation safe until commit.

Private form and fusion requests are covered. The prefix rejects new fighter
contacts while a matching live extra waits in action236..242 with request1..4.
The original leader reload veto and throw/cinematic chain remain intact. This
module never changes timers, actions, HP, camera ownership or native queues.
"""
from native_map import A
import struct

from prototype import Assembler
import fresh_team_combat as core
import leader_transform_safety as leader
import extra_reload_forms as forms
import extra_reload_requests as requests
from battle_mode_policy import ACTOR_COUNTS

CODE, TRAMPOLINE, END = 0x07663000, 0x07663800, 0x07664000
HOOK = leader.PROTECTED
SAVED = tuple(range(8, 18)) + (24, 25)


def code():
    a = Assembler(CODE); a.addiu(29, 29, -0x60)
    for i, r in enumerate(SAVED): a.i(63, r, 29, i*8)
    core.gate(a, 'native'); a.move(17, 10)
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'native')
    a.lw(14, 28, -22364)
    for control in (forms.CONTROL, requests.CONTROL):
        a.li(8, control); a.lw(9, 8); a.addiu(10, 0, 1); a.branch(5, 9, 10, 'native')
        a.lw(9, 8, 4); a.branch(5, 9, 14, 'native')
        a.lw(9, 8, 8); a.branch(5, 9, 17, 'native')
    a.lw(9, 8, 24); a.branch(5, 9, 10, 'native')
    a.branch(4, 4, 5, 'native')
    # Only another captured fighter can produce a new contact we suppress.
    a.li(11, core.POINTERS); a.move(12, 0)
    a.label('source'); a.lw(9, 11); a.branch(4, 9, 4, 'source_found')
    a.addiu(11, 11, 4); a.addiu(12, 12, 1); a.branch(5, 12, 17, 'source'); a.jump('native')
    a.label('source_found'); a.li(11, core.POINTERS+8); a.addiu(15, 0, 2)
    a.label('target'); a.lw(9, 11); a.branch(4, 9, 5, 'target_found')
    a.addiu(11, 11, 4); a.addiu(15, 15, 1); a.branch(5, 15, 17, 'target'); a.jump('native')
    a.label('target_found')
    a.addiu(8, 15, -2); a.r(0, 8, 0, 8, 6); a.li(16, requests.RECORDS); a.r(0x2D, 16, 16, 8)
    a.lw(8, 16); a.branch(4, 8, 0, 'native')
    a.lw(8, 16, 56); a.addiu(9, 0, 1); a.branch(5, 8, 9, 'native')
    a.lw(8, 16, 4); a.addiu(8, 8, -1); a.i(11, 9, 8, 4); a.branch(4, 9, 0, 'native')
    a.lw(8, 16, 8); a.branch(5, 8, 5, 'native')
    a.lw(8, 16, 44); a.branch(5, 8, 15, 'native')
    a.lw(8, 5, 2376); a.addiu(9, 8, -236); a.i(11, 9, 9, 7); a.branch(4, 9, 0, 'native')
    a.lw(9, 16, 60); a.branch(5, 8, 9, 'native')
    for actor_offset, row_offset in ((0x12D0, 20), (0x12D4, 24), (0x12E0, 28)):
        a.lw(8, 5, actor_offset); a.lw(9, 16, row_offset); a.branch(5, 8, 9, 'native')
    a.lw(13, 5, 12); a.i(11, 9, 13, 12); a.branch(4, 9, 0, 'native')
    a.lw(8, 16, 12); a.branch(5, 8, 13, 'native')
    a.r(0, 8, 0, 13, 2); a.li(9, core.MODELS); a.r(0x2D, 8, 8, 9); a.lw(12, 8)
    a.li(8, 0x100000); a.r(0x2B, 9, 12, 8); a.branch(5, 9, 0, 'native')
    a.li(8, 0x8000000-0x1670); a.r(0x2B, 9, 12, 8); a.branch(4, 9, 0, 'native')
    a.lw(8, 12, 16); a.branch(5, 8, 13, 'native')
    a.lw(8, 16, 16); a.branch(5, 8, 12, 'native')
    a.lw(8, 12, 20); a.lw(9, 16, 48); a.branch(5, 8, 9, 'native')
    # Native active roster row: HP at actor+0x9E4+164*slot.
    a.lw(8, 5, 0x994); a.i(11, 9, 8, 5); a.branch(4, 9, 0, 'native')
    a.r(0, 9, 0, 8, 7); a.r(0, 10, 0, 8, 5); a.r(0x2D, 9, 9, 10)
    a.r(0, 10, 0, 8, 2); a.r(0x2D, 9, 9, 10); a.r(0x2D, 9, 9, 5)
    a.lw(8, 9, 0x9E4); a.branch(6, 8, 0, 'native')
    for i, r in enumerate(SAVED): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x60); a.addiu(2, 0, 1); a.jr()
    a.label('native')
    for i, r in enumerate(SAVED): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x60); a.jump(TRAMPOLINE)
    result = a.finish(); assert len(result) <= TRAMPOLINE-CODE; return result


def pieces():
    original = leader.protected_code()
    # Address construction only; replay before the unchanged relative branches.
    assert tuple(w >> 26 for w in struct.unpack('<2I', original[:8])) == (15, 13)
    trampoline = original[:8]+struct.pack('<2I', (2<<26)|((HOOK+8)>>2), 0)
    return [(CODE, code()), (TRAMPOLINE, trampoline),
            (HOOK, struct.pack('<2I', (2<<26)|(CODE>>2), 0))]


def validate_memory(ram, manager, count, *, installing=False):
    """Accept the complete optional prefix, never a bare replacement jump."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if (u(forms.CONTROL) not in (0, 1) or u(requests.CONTROL) not in (0, 1) or
            u(forms.FORM_ENABLE) not in (0, 1) or
            tuple(u(forms.CONTROL+off) for off in (4, 8)) != (manager, count) or
            tuple(u(requests.CONTROL+off) for off in (4, 8)) != (manager, count)):
        raise ValueError('Pending form contact owner changed')
    original = leader.protected_code()
    handshake = [(forms.PUSH, forms.push_code()),
                 (requests.previous.PUSH_HOOK, struct.pack('<2I', (2<<26)|(forms.PUSH>>2), 0))]
    for kind, entry, target in (('ready', A(0x1D6360), forms.READY),
                               ('ack', A(0x1D63D8), forms.ACK), ('finish', A(0x1D6408), forms.FINISH)):
        handshake += [(target, forms.handshake(kind)),
                      (entry, struct.pack('<2I', (2<<26)|(target>>2), 0))]
    protection = [(HOOK, original)] if installing else [*pieces(), (HOOK+8, original[8:])]
    for p, data in [*protection, *handshake]:
        if ram[p:p+len(data)] != data:
            raise ValueError(f'Pending form contact code changed:{p:08X}')


def build_memory(ram, source='<offline>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+12)
    if count not in ACTOR_COUNTS or tuple(u(forms.CONTROL+off) for off in (4, 8)) != (manager, count):
        raise ValueError('Install the captured ordinary-form service first')
    if u(HOOK) == (2<<26)|(CODE>>2):
        validate_memory(ram, manager, count); return dict(blocks=[], source=str(source))
    original = leader.protected_code()
    if ram[HOOK:HOOK+len(original)] != original:
        raise ValueError('Changed native leader reload protection')
    if any(ram[CODE:END]): raise ValueError('Pending form contact reservation occupied')
    validate_memory(ram, manager, count, installing=True)
    blocks = [dict(address=p, expected_hex=ram[p:p+len(data)].hex(), data_hex=data.hex()) for p, data in pieces()]
    return dict(source=str(source), status='PENDING EXTRA FORM CONTACT PROTECTION', blocks=blocks)
