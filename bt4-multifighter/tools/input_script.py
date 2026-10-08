"""Guest-side scripted input injection for reproduction tests (offline builder).

Installs a small wrapper at the head of the native actor-update hook chain
(0x1C2A28). Each frame, for every armed entry, it overwrites either the raw
controller record (human path: record 0x333800+448*controller, +328 buttons,
+304/+308 analog floats) or the actor's AI-written digital word (+0x127C).
Pad polling (sub_122A38) precedes this hook in the frame loop (sub_12BBD0),
and the actor update (sub_1C1AD0 -> sub_1D4A00) consumes it afterwards.

Raw PS2 button masks: Select 0x1, L3 0x2, R3 0x4, Start 0x8, Up 0x10,
Right 0x20, Down 0x40, Left 0x80, L2 0x100, R2 0x200, L1 0x400, R1 0x800,
Triangle 0x1000, Circle 0x2000, Cross 0x4000, Square 0x8000.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram

CODE, CONTROL, HOOK = 0x073D0000, 0x073D0800, A(0x1C2A28)
RECORDS, RECORD_STRIDE = A(0x333800), 448
ENTRIES, ENTRY_SIZE, ENTRY_BASE = 4, 0x20, 0x20
BUTTON = dict(select=0x1, l3=0x2, r3=0x4, start=0x8, up=0x10, right=0x20, down=0x40, left=0x80,
              l2=0x100, r2=0x200, l1=0x400, r1=0x800, triangle=0x1000, circle=0x2000,
              cross=0x4000, square=0x8000)


def code(previous):
    a = Assembler(CODE)
    a.addiu(29, 29, -0x30)
    for i, r in enumerate((8, 9, 10, 11, 12)): a.i(63, r, 29, i*8)
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'done')
    a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'done')
    a.lw(9, 8, 8); a.addiu(9, 9, 1); a.sw(9, 8, 8)
    for k in range(ENTRIES):
        e = ENTRY_BASE+k*ENTRY_SIZE
        a.lw(9, 8, e); a.branch(4, 9, 0, f'skip{k}')
        a.lw(10, 8, e+8); a.branch(4, 10, 0, f'skip{k}')
        a.addiu(10, 10, -1); a.sw(10, 8, e+8)
        a.lw(10, 8, e+20); a.addiu(10, 10, 1); a.sw(10, 8, e+20)
        a.lw(10, 8, e+24); a.branch(5, 10, 0, f'word{k}')
        # Human path: rewrite this controller's polled record.
        a.lw(10, 9, 4); a.i(11, 11, 10, 2); a.branch(4, 11, 0, f'skip{k}')
        a.r(0, 11, 0, 10, 6); a.r(0, 12, 0, 10, 7); a.r(0x2D, 11, 11, 12)
        a.r(0, 12, 0, 10, 8); a.r(0x2D, 11, 11, 12)  # 448 = 64+128+256
        a.li(12, RECORDS); a.r(0x2D, 11, 11, 12)
        a.lw(12, 8, e+4); a.sw(12, 11, 328)
        a.lw(12, 8, e+12); a.sw(12, 11, 304)
        a.lw(12, 8, e+16); a.sw(12, 11, 308)
        a.jump(f'skip{k}')
        a.label(f'word{k}')
        a.lw(12, 8, e+4); a.sw(12, 9, 0x127C)
        a.lw(12, 8, e+12); a.sw(12, 9, 0x1280)
        a.lw(12, 8, e+16); a.sw(12, 9, 0x1284)
        a.label(f'skip{k}')
    a.label('done')
    for i, r in enumerate((8, 9, 10, 11, 12)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30)
    a.jump(previous)
    result = a.finish(); assert len(result) < CONTROL-CODE; return result


TRAMPOLINE = CODE+0x400
# Previous chain heads chain_head() accepts. The release builders that share it (lockon_switch, team_start_gate,
# team_intro) keep the reviewed battle wrappers in 0x07000000..0x07400000. The scripted-input injector below is
# reproduction tooling: it accepts any head in the guest reservations above heap1 (which ends at 0x06000000),
# because current prepared matches chain through wrappers at 0x06C10000 (four-player co-op), 0x077A0000 (the
# 5v5 sound hook) and 0x077C0000 (team participation).
BATTLE_HEADS, GUEST_HEADS = (0x07000000, 0x07400000), (0x06000000, 0x08000000)
SOUND_CODE, SOUND_TRAMPOLINE, SOUND_CONTROL, SOUND_RING = 0x073D0500, 0x073D0700, 0x073D0900, 0x073D0A00
SOUND_HOOK, RING_ENTRIES = A(0x1D9B78), 1024


def chain_head(ram, hook, trampoline, native, heads=BATTLE_HEADS):
    """Return (previous target, extra payloads) for hooking at hook."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    word = u(hook)
    if word >> 26 == 2 and u(hook+4) == 0:
        previous = (word & 0x3FFFFFF) << 2
        if not heads[0] <= previous < heads[1]: raise ValueError(f'Unreviewed hook chain head {previous:08X}')
        return previous, []
    original = native(hook, 8)
    if ram[hook:hook+8] != original: raise ValueError(f'Unknown bytes at hook {hook:X}')
    for w in struct.unpack('<2I', original):
        if w >> 26 in (1, 2, 3, 4, 5, 6, 7, 20, 21): raise ValueError('Native prologue needs branch relocation')
    return trampoline, [(trampoline, original+struct.pack('<2I', (2<<26)|((hook+8)>>2), 0), 'Displaced native prologue')]


def injector_head(ram, hook, trampoline, native):
    """chain_head for this injector's own hooks: any guest head, never one of its own entry points."""
    previous, extra = chain_head(ram, hook, trampoline, native, heads=GUEST_HEADS)
    if previous in (CODE, SOUND_CODE, PLAY_CODE):
        raise ValueError(f'Hook chain head {previous:08X} is this injector: the image already has it installed')
    return previous, extra


def sound_code(previous):
    """Log every sound request (a1 owner, a2, a3 id) with the AI frame counter."""
    a = Assembler(SOUND_CODE)
    a.addiu(29, 29, -0x30)
    for i, r in enumerate((8, 9, 10, 11)): a.i(63, r, 29, i*8)
    a.li(8, SOUND_CONTROL); a.lw(9, 8); a.addiu(9, 9, 1); a.sw(9, 8)
    a.lw(9, 8, 4); a.r(0, 10, 0, 9, 4); a.li(11, SOUND_RING); a.r(0x2D, 10, 10, 11)
    a.sw(5, 10); a.sw(6, 10, 4); a.sw(7, 10, 8)
    a.li(11, 0x07338000); a.lw(11, 11, 0x10); a.sw(11, 10, 12)
    a.addiu(9, 9, 1); a.i(12, 9, 9, RING_ENTRIES-1); a.sw(9, 8, 4)
    for i, r in enumerate((8, 9, 10, 11)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30); a.jump(previous)
    result = a.finish(); assert len(result) < SOUND_TRAMPOLINE-SOUND_CODE; return result


PLAY_CODE, PLAY_TRAMPOLINE, PLAY_CONTROL, PLAY_RING = 0x073D8000, 0x073D8200, 0x073D8400, 0x073D8500
PLAY_HOOK, PLAY_ENTRIES = A(0x124F88), 256


def play_code(previous):
    """Count native sound plays (bank a0, id a1) with the AI frame counter."""
    a = Assembler(PLAY_CODE)
    a.addiu(29, 29, -0x30)
    for i, r in enumerate((8, 9, 10, 11)): a.i(63, r, 29, i*8)
    a.li(8, PLAY_CONTROL); a.lw(9, 8); a.addiu(9, 9, 1); a.sw(9, 8)
    a.lw(9, 8, 4); a.r(0, 10, 0, 9, 4); a.li(11, PLAY_RING); a.r(0x2D, 10, 10, 11)
    a.sw(17, 10); a.sw(5, 10, 4); a.sw(31, 10, 8)  # caller s1 (effect object), id, caller return address
    a.li(11, 0x07338000); a.lw(11, 11, 0x10); a.sw(11, 10, 12)
    a.addiu(9, 9, 1); a.i(12, 9, 9, PLAY_ENTRIES-1); a.sw(9, 8, 4)
    for i, r in enumerate((8, 9, 10, 11)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30); a.jump(previous)
    result = a.finish(); assert len(result) < PLAY_TRAMPOLINE-PLAY_CODE; return result


def build_memory(ram, source='<offline>', sound_log=True):
    if len(ram) != 0x8000000: raise ValueError('Exactly128 MiB EE RAM is required')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(A(0x2FEB14))
    if not 0x100000 <= manager < len(ram) or u(manager) != 2: raise ValueError('Native two-row manager required')
    _, _, native = elf_reader(elf_path(ROOT))
    previous, extra = injector_head(ram, HOOK, TRAMPOLINE, native)
    if any(ram[CODE:SOUND_RING+RING_ENTRIES*16]): raise ValueError('Input-script reservation occupied')
    control = bytearray(0x100); struct.pack_into('<2I', control, 0, 1, manager)
    payloads = extra+[(CODE, code(previous), 'Scripted input injector at the head of the actor-update chain'),
                (CONTROL, bytes(control), 'Injector control: enabled, manager, frames; entries at +0x20'),
                (HOOK, struct.pack('<2I', (2<<26)|(CODE>>2), 0), 'Chain injector before the previous wrapper')]
    if sound_log:
        sound_previous, sound_extra = injector_head(ram, SOUND_HOOK, SOUND_TRAMPOLINE, native)
        payloads += sound_extra+[(SOUND_CODE, sound_code(sound_previous), 'Sound request ring logger'),
                    (SOUND_CONTROL, bytes(0x100), 'Sound log: total count, ring index'),
                    (SOUND_HOOK, struct.pack('<2I', (2<<26)|(SOUND_CODE>>2), 0), 'Chain sound logger before the previous wrapper')]
        if any(ram[PLAY_CODE:PLAY_RING+PLAY_ENTRIES*16]): raise ValueError('Play-counter reservation occupied')
        play_previous, play_extra = injector_head(ram, PLAY_HOOK, PLAY_TRAMPOLINE, native)
        payloads += play_extra+[(PLAY_CODE, play_code(play_previous), 'Native sound play ring logger'),
                    (PLAY_CONTROL, bytes(0x100), 'Play log: total count, ring index'),
                    (PLAY_HOOK, struct.pack('<2I', (2<<26)|(PLAY_CODE>>2), 0), 'Chain play logger before native play')]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), previous=previous,
        control=CONTROL, entries=ENTRY_BASE, entry_size=ENTRY_SIZE, entry_count=ENTRIES,
        entry_fields=dict(actor=0, mask=4, frames=8, analog_x=12, analog_y=16, applied=20, mode=24),
        blocks=[dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex(), purpose=w) for p, b, w in payloads],
        limitations=['Reproduction tooling only; not part of a release preset.',
                     'Mode0 rewrites the polled controller record for the actor controller at +4; mode1 overwrites the AI word.'])


def build(source): return build_memory(read_ram(source), source)


def entry_bytes(actor, mask, frames, mode=0, x=0.0, y=0.0):
    return struct.pack('<IIIffII', actor, mask, frames, x, y, 0, mode)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    r = build(x.source); x.out.write_text(json.dumps(r, indent=2)+'\n'); print(f'{x.out}: {len(r["blocks"])} blocks; previous {r["previous"]:08X}')
