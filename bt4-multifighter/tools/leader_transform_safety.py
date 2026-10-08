"""Protect native leader reload handshakes and rebuild their private AI afterward.

Only new contacts against transforming/reloading captured leaders are rejected.
Native1BB1F0 still initializes the real manager first; the corresponding private
own context is then rebuilt with1BAF68 through the proven physical pair aliases.
No actor/model resources are copied, freed or replaced by this patch.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from types import FunctionType

from prototype import Assembler, ROOT, elf_reader
from ai_shadow import Assembler as AiAssembler, AI_GLOBAL
from camera_snapshot import read_ram
import cinematic_contact_guard as contact
import fresh_team_combat as core
import fresh_team_ai as fresh
import distinct_ai
import team_pair_ai as pair
from battle_mode_policy import ACTOR_COUNTS

PROTECTED, FALLBACK, REFRESH, CONTROL = 0x073F9000, 0x073F9800, 0x073FA000, 0x073FFF00
REFRESH_HOOK = A(0x1BB1F0)
END = 0x07400000


def prior_contact():
    env = dict(contact.protected_code.__globals__); env['PROTECTED'] = FALLBACK
    return FunctionType(contact.protected_code.__code__, env)()


def protected_code():
    a = Assembler(PROTECTED)
    core.gate(a, 'native')
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'native')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'native')
    a.lw(9, 8, 12); a.branch(5, 9, 10, 'native')
    # Match actual leader pointers. Temporary role IDs never imply ownership.
    a.li(8, core.POINTERS); a.lw(9, 8); a.move(15, 0)
    a.branch(4, 5, 9, 'leader'); a.lw(9, 8, 4); a.addiu(15, 0, 1)
    a.branch(5, 5, 9, 'native')
    a.label('leader'); a.branch(4, 4, 5, 'native')
    # Reject only contacts whose source is another captured fighter.
    a.move(14, 0)
    a.label('source'); a.lw(9, 8); a.branch(4, 4, 9, 'owned')
    a.addiu(8, 8, 4); a.addiu(14, 14, 1); a.branch(5, 14, 10, 'source')
    a.jump('native')
    a.label('owned'); a.lw(9, 5, 2376); a.addiu(9, 9, -236)
    a.i(11, 9, 9, 8); a.branch(5, 9, 0, 'blocked')
    # Keep the native acknowledgement protected even if an old interruption
    # changed action already. Kind0 and owner0/1 identify a leader reload.
    a.lw(8, 11, 600); a.branch(4, 8, 0, 'native')
    a.addiu(9, 11, 312); a.r(0x2B, 12, 8, 9); a.branch(5, 12, 0, 'native')
    a.addiu(9, 11, 600); a.r(0x2B, 12, 8, 9); a.branch(4, 12, 0, 'native')
    a.lw(9, 8); a.branch(5, 9, 15, 'native'); a.lw(9, 8, 4); a.branch(5, 9, 0, 'native')
    a.lw(9, 11, 612); a.addiu(9, 9, -1); a.i(11, 9, 9, 4)
    a.branch(4, 9, 0, 'native')
    a.label('blocked'); a.li(8, CONTROL); a.lw(9, 8, 32); a.addiu(9, 9, 1)
    a.sw(9, 8, 32); a.sw(15, 8, 36); a.addiu(2, 0, 1); a.jr()
    a.label('native'); a.jump(FALLBACK)
    result = a.finish(); assert len(result) <= FALLBACK-PROTECTED; return result


def refresh_code():
    a = AiAssembler(REFRESH); a.addiu(29, 29, -0x90)
    saved = [(16+i, i*8) for i in range(8)] + [(31, 0x40)]
    for r, o in saved: a.mem(63, r, 29, o)
    a.mem(43, 4, 29, 0x70)
    # Native1BB1F0 is a tail call1BAF68(a0,0). Preserve its result exactly.
    a.jump(A(0x1BAF68), link=True); a.move(5, 0)
    a.mem(63, 2, 29, 0x60); a.mem(63, 3, 29, 0x68)
    a.load_address(18, CONTROL); a.mem(35, 8, 18, 0)
    a.branch(8, 0, 'return'); a.nop()
    a.mem(35, 17, 28, -0x5760)
    a.mem(35, 8, 18, 8); a.branch(8, 17, 'return', not_equal=True); a.nop()
    a.load_address(8, core.MODE)
    a.mem(35, 9, 8, 0); a.branch(9, 0, 'return'); a.nop()
    a.mem(35, 10, 28, -22364); a.mem(35, 9, 18, 4)
    a.branch(9, 10, 'return', not_equal=True); a.nop()
    a.mem(35, 11, 10, 0); a.addiu(12, 0, 2)
    a.branch(11, 12, 'return', not_equal=True); a.nop()
    a.mem(35, 9, 8, 8); a.branch(9, 10, 'return', not_equal=True); a.nop()
    for offset in (4, 12):
        a.mem(35, 9, 8, offset); a.mem(35, 10, 18, 12)
        a.branch(9, 10, 'return', not_equal=True); a.nop()
    a.load_address(8, fresh.CONTROL)
    a.mem(35, 9, 8, 0); a.addiu(10, 0, 5)
    a.branch(9, 10, 'return', not_equal=True); a.nop()
    a.mem(35, 9, 8, 0x2C); a.branch(9, 17, 'return', not_equal=True); a.nop()
    a.load_address(16, pair.CONTROL)
    a.mem(35, 8, 16, 0); a.branch(8, 0, 'return'); a.nop()
    a.mem(35, 8, 16, 4); a.branch(8, 0, 'return', not_equal=True); a.nop()
    a.mem(35, 8, 29, 0x70); a.mem(11, 9, 8, 2)
    a.branch(9, 0, 'return'); a.nop()
    a.mem(43, 8, 18, 20); a.mem(43, 0, 18, 28)
    a.branch(8, 0, 'leader0'); a.nop()
    a.jump(REFRESH+0x1000); a.nop()
    a.label('leader0')
    # Out-of-line branches permit reuse of the proven unrolled initializer.
    a.jump(REFRESH+0x800); a.nop()
    for name, value in (('invalid', 101), ('owned', 102), ('dataset_failed', 103)):
        a.label(name); a.addiu(8, 0, value); a.load_address(9, CONTROL)
        a.mem(43, 8, 9, 28); a.branch(0, 0, 'return'); a.nop()
    a.label('success'); a.load_address(9, CONTROL)
    a.mem(35, 8, 9, 16); a.addiu(8, 8, 1); a.mem(43, 8, 9, 16)
    a.mem(35, 8, 10, 20); a.mem(43, 8, 9, 24)
    a.label('return')
    a.mem(55, 2, 29, 0x60); a.mem(55, 3, 29, 0x68)
    for r, o in saved: a.mem(55, r, 29, o)
    a.emit(0x03E00008); a.addiu(29, 29, 0x90)
    first = a.finish(); assert len(first) <= 0x800
    parts = [(REFRESH, first)]
    for physical, at in ((0, REFRESH+0x800), (1, REFRESH+0x1000)):
        b = AiAssembler(at)
        # Native reload has completed model initialization. Bind current model
        # metadata only; never memcpy its old/native own AI context.
        b.load_address(8, fresh.DESCRIPTORS[physical]); b.mem(35, 9, 8, 0)
        b.load_address(10, core.POINTERS+physical*4); b.mem(35, 10, 10, 0)
        b.branch(9, 10, 'invalid', not_equal=True); b.nop()
        b.mem(35, 10, 9, 0); b.addiu(11, 0, physical)
        b.branch(10, 11, 'invalid', not_equal=True); b.nop()
        b.mem(35, 10, 9, 12); b.mem(11, 11, 10, 12)
        b.branch(11, 0, 'invalid'); b.nop()
        b.emit((10<<16)|(11<<11)|(2<<6)); b.load_address(12, core.MODELS)
        b.emit((11<<21)|(12<<16)|(11<<11)|0x2D); b.mem(35, 11, 11, 0)
        b.branch(11, 0, 'invalid'); b.nop(); b.mem(35, 12, 11, 2356)
        b.branch(12, 0, 'invalid'); b.nop()
        b.load_address(13, fresh.RECORDS[physical])
        for offset, value in ((0, 9), (4, 10), (8, 11), (12, 12)):
            b.mem(43, value, 13, offset)
        for offset, value in ((32, 10), (36, 11), (40, 12)):
            b.mem(43, value, 8, offset)
        distinct_ai.emit_initialize(b, physical, fresh.DESCRIPTORS[physical],
                                   fresh.RECORDS[physical], CONTROL+0x80)
        b.jump(a.labels['success']); b.nop()
        # Every initializer failure after alias activation restores first.
        for label in ('invalid', 'owned', 'dataset_failed'):
            b.label(label); b.jump(a.labels[label]); b.nop()
        payload = b.finish(); assert len(payload) <= 0x800; parts.append((at, payload))
    return parts


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE memory')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, native_ai, n = u(core.ACTORS), u(AI_GLOBAL), u(core.MODE+4)
    if not 0x100000 <= manager < len(ram)-0x1000 or u(manager) != 2:
        raise ValueError('Native captured actor manager required')
    if (u(core.MODE) != 1 or u(core.MODE+8) != manager or n not in ACTOR_COUNTS
            or u(core.MODE+12) != n or u(pair.CONTROL+4)):
        raise ValueError('Captured4/6 mode with inactive aliases required')
    if (not 0x100000 <= native_ai < len(ram)-0xA60 or u(fresh.CONTROL) != 5
            or u(fresh.CONTROL+0x2C) != native_ai):
        raise ValueError('Initialized fresh private AI required')
    if tuple(u(contact.CONTROL+o) for o in (0, 4, 8)) != (1, manager, n):
        raise ValueError('Matching active cinematic contact control required')
    fresh.support_matches(ram, {'capacity': n, 'features': {}}, set(), n)
    for i in range(n):
        actor, shadow = u(fresh.DESCRIPTORS[i]), u(fresh.DESCRIPTORS[i]+4)
        if actor != u(core.POINTERS+4*i) or u(actor) != i or shadow != fresh.SHADOWS[i]:
            raise ValueError('Captured private AI identity changed')
        if u(shadow+0x10+(i&1)*0x520+36)&1:
            raise ValueError('Private AI unexpectedly owns its borrowed dataset')
    if any(ram[PROTECTED:END]): raise ValueError('Leader transformation reservation occupied')
    _, _, native = elf_reader(elf_path(ROOT))
    if ram[REFRESH_HOOK:REFRESH_HOOK+24] != native(REFRESH_HOOK, 24):
        raise ValueError('Native leader AI reload entry changed')
    if ram[contact.PROTECTED:contact.PROTECTED+len(contact.protected_code())] != contact.protected_code():
        raise ValueError('Existing cinematic contact predicate changed')
    for address, payload in ((contact.GATE, contact.gate_code()),
                             (distinct_ai.MODEL_BRIDGE, distinct_ai.role_bridge(distinct_ai.MODEL_BRIDGE, A(0x2499B0)))):
        if ram[address:address+len(payload)] != payload:
            raise ValueError(f'Required contact/AI bridge changed at{address:08X}')
    control = bytearray(0x100); struct.pack_into('<4I', control, 0, 1, manager, native_ai, n)
    parts = [(PROTECTED, protected_code()), (FALLBACK, prior_contact()), *refresh_code(),
             (CONTROL, bytes(control)),
             (contact.PROTECTED, struct.pack('<2I', (2<<26)|(PROTECTED>>2), 0)),
             (REFRESH_HOOK, struct.pack('<2I', (2<<26)|(REFRESH>>2), 0))]
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex()) for p, d in parts]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
                control=CONTROL, status='LEADER RELOAD CONTACT PROTECTION AND PRIVATE AI REINITIALIZATION',
                scope=['Protect captured leader current236..243 and pending native kind0 reload phases1..4.',
                       'Rebuild the reloaded leader private own AI with native1BAF68 and actual pair aliases.',
                       'Preserve native1BB1F0 return value, original manager, actor/model identity and CPU flags.'],
                limitations=['Does not recover a reload already interrupted before installation.',
                             'New extra form entry remains separately bounded by ordinary_transform_guard.'])


def build(source): return build_memory(read_ram(source), source=source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args(); result = build(x.source)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
