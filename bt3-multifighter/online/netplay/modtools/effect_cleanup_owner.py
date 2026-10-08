"""Tag captured extra model effects for their borrowed leader's reload cleanup.

Native14DBB8 treats every nonzero owner model as leader1. Extra models on
team0 therefore retain leader0 combat-file textures after that file is reused.
Resolve only captured actual model IDs to side before the original tag helper.
This does not change effect model ownership, resources, or cleanup callbacks.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
from battle_mode_policy import ACTOR_COUNTS

ENTRY, CODE, CONTROL, END = A(0x14DBB8), 0x07402000, 0x07402F00, 0x07404000
SAVED = (8, 9, 10, 11, 12)


def payload(native):
    a = Assembler(CODE); a.addiu(29, 29, -0x30)
    for i, r in enumerate(SAVED): a.i(63, r, 29, i*8)
    core.gate(a, 'native')
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'native')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'native')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'native')
    a.branch(4, 4, 0, 'native')
    for kind in (2, 5):
        a.addiu(9, 0, kind); a.branch(4, 6, 9, 'native')
    # Native leaders and unowned cosmetic models keep the exact old ABI.
    a.i(11, 9, 5, 2); a.branch(5, 9, 0, 'native')
    a.i(11, 9, 5, 12); a.branch(4, 9, 0, 'native')
    a.li(8, core.POINTERS); a.move(12, 0)
    a.label('scan'); a.lw(9, 8); a.branch(4, 9, 0, 'next')
    a.lw(11, 9, 12); a.branch(4, 11, 5, 'found')
    a.label('next'); a.addiu(8, 8, 4); a.addiu(12, 12, 1)
    a.branch(5, 12, 10, 'scan'); a.jump('native')
    a.label('found'); a.li(8, CONTROL)
    a.lw(9, 8, 16); a.addiu(9, 9, 1); a.sw(9, 8, 16)
    a.sw(5, 8, 20); a.sw(12, 8, 24); a.i(12, 5, 12, 1)
    a.label('native')
    for i, r in enumerate(SAVED): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30)
    for word in struct.unpack('<2I', native(ENTRY, 8)): a.emit(word)
    a.jump(ENTRY+8)
    code = a.finish(); assert len(code) < CONTROL-CODE; return code


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE memory')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if (not 0x100000 <= manager < len(ram)-0x1000 or u(manager) != 2
            or count not in ACTOR_COUNTS or u(core.MODE) != 1
            or u(core.MODE+8) != manager or u(core.MODE+12) != count):
        raise ValueError('Active captured4/6 native manager required')
    actors, models = [], []
    for i in range(count):
        actor = u(core.POINTERS+4*i)
        if not 0x100000 <= actor < len(ram)-0x1600 or u(actor) != i:
            raise ValueError('Captured actor identity or alias changed')
        model = u(actor+12)
        if model >= 12 or not u(core.MODELS+model*4): raise ValueError('Missing actual model')
        actors.append(actor); models.append(model)
    if len(set(actors)) != count or len(set(models)) != count: raise ValueError('Duplicate actor/model')
    _, _, native = elf_reader(elf_path(ROOT))
    if ram[ENTRY:ENTRY+8] != native(ENTRY, 8): raise ValueError('Native effect tagging entry changed')
    if any(ram[CODE:END]): raise ValueError('Effect cleanup owner reservation occupied')
    control = bytearray(0x100); struct.pack_into('<3I', control, 0, 1, manager, count)
    parts = [(CODE, payload(native)), (CONTROL, bytes(control)),
             (ENTRY, struct.pack('<2I', (2<<26)|(CODE>>2), 0))]
    blocks = [dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex()) for p, b in parts]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
                control=CONTROL, status='BORROWED EFFECT TEXTURE RELOAD CLEANUP OWNERSHIP',
                evidence=['Native14DBB8 owner!=0 tags1000; captured even-side extras need800.',
                          'Native1283F0 calls12D180→12CBC8→1AD280 before in-place combat-file reload.',
                          'Failed122 particle01A02BA0 retained leader0 textureD620A0 but had1000 cleanup flag.'],
                limitations=['Install before new effects spawn; existing incorrectly tagged particles are not rewritten.',
                             'Effect resource pools are still borrowed from the original side leader.'])


def build(source): return build_memory(read_ram(source), source=source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source); x.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'{x.out}: {len(result["blocks"])} blocks')
