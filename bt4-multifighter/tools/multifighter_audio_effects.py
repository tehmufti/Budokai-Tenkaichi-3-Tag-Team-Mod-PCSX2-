"""Scoped sound-loop cleanup and bright overlay mitigation for captured teams.

Offline builder only. The native sound dispatcher cleans loop records for only
actors0/1; extending its final cleanup call prevents interrupted extra charge
sounds from persisting. Optional extra sound suppression reduces overlap.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from battle_mode_policy import ACTOR_COUNTS

REQUEST, CLEANUP, FLASH, CONTROL = 0x073C0000, 0x073C0400, 0x073C1000, 0x073C1800
REQUEST_HOOK, CLEANUP_HOOK, FLASH_HOOK = A(0x1D9B78), A(0x1DA31C), A(0x107508)
MODE, POINTERS, PAIR = 0xD8080, 0xD8040, 0xC4000


def save(a):
    a.addiu(29, 29, -0x20)
    for i, r in enumerate((8, 9, 10, 11)): a.i(63, r, 29, i*8)


def restore(a):
    for i, r in enumerate((8, 9, 10, 11)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x20)


def gate(a, failure):
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, failure)
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, failure)
    a.branch(4, 9, 0, failure); a.lw(11, 9); a.addiu(10, 0, 2)
    a.branch(5, 11, 10, failure)
    a.lw(11, 9, 12); a.lw(10, 8, 8); a.branch(5, 11, 10, failure)
    a.li(10, MODE); a.lw(11, 10); a.branch(4, 11, 0, failure)
    a.lw(11, 10, 8); a.branch(5, 11, 9, failure)
    a.lw(11, 10, 4); a.lw(10, 8, 12); a.branch(5, 11, 10, failure)
    # Count and auxiliary ownership were checked when the manifest was built.


def counter(a, offset):
    a.li(8, CONTROL); a.lw(9, 8, offset); a.addiu(9, 9, 1); a.sw(9, 8, offset)


def native_tail(a, entry, original):
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21)
        a.emit(word)
    a.jump(entry+8)


def request_code(original):
    a = Assembler(REQUEST); save(a); gate(a, 'native')
    a.li(8, CONTROL); a.lw(8, 8, 28); a.branch(4, 8, 0, 'native')
    a.move(11, 5)  # Native a1 is the physical owner, -1 for world sounds.
    a.i(11, 8, 11, 2); a.branch(4, 8, 0, 'physical')
    # AI slices temporarily alias 0/1; saved physical role IDs disambiguate.
    a.li(8, PAIR); a.lw(9, 8, 4); a.branch(4, 9, 0, 'native')
    a.r(0, 9, 0, 11, 2); a.r(0x2D, 8, 8, 9); a.lw(11, 8, 16)
    a.label('physical'); a.i(11, 8, 11, 2); a.branch(5, 8, 0, 'native')
    a.li(8, CONTROL); a.lw(8, 8, 12); a.r(0x2B, 9, 11, 8)
    a.branch(4, 9, 0, 'native')  # Keep world/unowned events unchanged.
    counter(a, 16); restore(a); a.move(2, 0); a.jr()
    a.label('native'); restore(a); native_tail(a, REQUEST_HOOK, original)
    code = a.finish(); assert len(code) < 0x400; return code


def cleanup_code():
    # Replaces only the final JAL in1DA098. Original a0 is leader1; keep
    # that exact call and return value before visiting all extra loop rows.
    a = Assembler(CLEANUP); a.addiu(29, 29, -0x30)
    for r, off in ((31, 0), (16, 8), (17, 16), (18, 24)): a.i(63, r, 29, off)
    a.call(A(0x1D9D28)); a.i(63, 2, 29, 32)
    save(a); gate(a, 'inactive'); a.lw(17, 8, 12)
    counter(a, 20); restore(a)
    a.li(16, POINTERS+8); a.addiu(18, 0, 2)
    a.label('loop'); a.lw(4, 16); a.branch(4, 4, 0, 'next')
    a.call(A(0x1D9D28))
    a.label('next'); a.addiu(16, 16, 4); a.addiu(18, 18, 1)
    a.branch(5, 18, 17, 'loop'); a.jump('done')
    a.label('inactive'); restore(a)
    a.label('done'); a.i(55, 2, 29, 32)
    for r, off in ((31, 0), (16, 8), (17, 16), (18, 24)): a.i(55, r, 29, off)
    a.addiu(29, 29, 0x30); a.jr()
    code = a.finish(); assert len(code) < 0x800; return code


def flash_code(original):
    a = Assembler(FLASH); save(a); gate(a, 'native')
    a.li(8, CONTROL); a.lw(8, 8, 32); a.branch(4, 8, 0, 'native')
    # 107508 draws a screen-sized untextured RGBA fill. Only its four
    # known battle overlay sources are eligible; timers update elsewhere.
    for index, pointer in enumerate((A(0x31C4A0), A(0x31C500), A(0x31C560), A(0x31C5C0))):
        a.li(8, pointer); a.branch(4, 5, 8, 'color')
    a.jump('native'); a.label('color')
    # Positive IEEE754 floats preserve unsigned order. Restrict to the
    # native color range192..255; dark and colored overlays remain normal.
    a.li(9, 0x43400000); a.li(10, 0x43800000)
    for offset in (0, 4, 8):
        a.lw(8, 5, offset); a.r(0x2B, 11, 8, 9); a.branch(5, 11, 0, 'native')
        a.r(0x2B, 11, 8, 10); a.branch(4, 11, 0, 'native')
    a.lw(8, 5, 12); a.branch(4, 8, 0, 'native')
    counter(a, 24); restore(a); a.move(2, 0); a.jr()
    a.label('native'); restore(a); native_tail(a, FLASH_HOOK, original)
    code = a.finish(); assert len(code) < 0x800; return code


def build_memory(ram, source='<offline>', quiet_extras=True, reduce_flashes=True):
    if len(ram) != 0x8000000: raise ValueError('Exactly128 MiB EE RAM is required')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(A(0x2FEB14)), u(MODE+4)
    if count not in ACTOR_COUNTS or not manager or u(MODE+8) != manager or u(manager) != 2:
        raise ValueError('Captured active4/6 fighter core is required')
    aux = u(manager+12)
    if not 0x100000 <= aux <= len(ram)-count*52: raise ValueError('Invalid expanded sound-loop records')
    for i in range(count):
        actor = u(POINTERS+4*i)
        if not 0x100000 <= actor <= len(ram)-0x1600 or u(actor) != i:
            raise ValueError('Captured physical actor identities must be restored')
    if u(PAIR+4): raise ValueError('Install between AI aliases')
    _, _, native = elf_reader(elf_path(ROOT))
    code = [(REQUEST, request_code(native(REQUEST_HOOK, 8)), 'Quiet extra-owned sound requests'),
            (CLEANUP, cleanup_code(), 'Clean interrupted loops for every captured extra'),
            (FLASH, flash_code(native(FLASH_HOOK, 8)), 'Skip bright-white battle overlay draws')]
    controls = struct.pack('<9I', 1, manager, aux, count, 0, 0, 0, int(quiet_extras), int(reduce_flashes))
    payloads = code+[(CONTROL, controls, 'Captured ownership, counters and independent audio/flash toggles')]
    for entry, cave in ((REQUEST_HOOK, REQUEST), (FLASH_HOOK, FLASH)):
        if ram[entry:entry+8] != native(entry, 8): raise ValueError(f'Changed native hook:{entry:X}')
        payloads.append((entry, struct.pack('<2I', (2<<26)|(cave>>2), 0), 'Install scoped wrapper'))
    expected_call = struct.pack('<I', (3<<26)|(A(0x1D9D28)>>2))
    if ram[CLEANUP_HOOK:CLEANUP_HOOK+4] != expected_call: raise ValueError('Sound cleanup call changed')
    payloads.append((CLEANUP_HOOK, struct.pack('<I', (3<<26)|(CLEANUP>>2)), 'Keep native delay-slot actor argument'))
    for p, b, _ in payloads:
        if p >= REQUEST and any(ram[p:p+len(b)]): raise ValueError(f'Audio reservation occupied:{p:X}')
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
        blocks=[dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex(), purpose=why) for p,b,why in payloads],
        control=CONTROL, telemetry=dict(suppressed_requests=CONTROL+16, cleanup_frames=CONTROL+20, white_overlays=CONTROL+24),
        evidence=['1DA098 invokes1D9D28 only for actors0/1; loop records for extras otherwise have no periodic stop.',
                  '1D9D28 calls native125128 to stop any loop absent from the current sound request queue.',
                  '107508 draws full-screen RGBA fills; its four battle sources are31C4A0/31C500/31C560/31C5C0.'],
        limitations=['Extra-owned sounds are suppressed; leader and ownerless world sounds remain native.',
                     'White overlay suppression needs live verification against the reported flash; projectile geometry is unchanged.',
                     'All native overlay timers continue running; restore the clean checkpoint to remove the hooks.'])


def build(source, **options): return build_memory(read_ram(source), source, **options)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source); x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
