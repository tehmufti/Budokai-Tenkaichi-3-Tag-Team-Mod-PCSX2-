"""Recover a newly missed downward floor crossing using native stage triangles.

Runs after native sphere collision/floor probing. Only a deep, short downward
step is reconsidered; query from the prior world root at the current X/Z. No
global ground height, last-map-height assumption, or persistent teleport state.
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

ENTRY, CODE, NATIVE, CONTROL, END = A(0x1B15B8), 0x07405000, 0x07405E00, 0x07405F00, 0x07406000


def fp(a, fn, fd, fs, ft=0): a.emit((17<<26)|(16<<21)|(ft<<16)|(fs<<11)|(fd<<6)|fn)
def constant(a, f, value):
    a.li(8, struct.unpack('<I', struct.pack('<f', value))[0]); a.emit((17<<26)|(4<<21)|(8<<16)|(f<<11))


def payload():
    a = Assembler(CODE); a.addiu(29, 29, -0xF0)
    # 00..63 query scratch;70..7F retained native return;80+ callee saves.
    for i, reg in enumerate((16, 17, 18, 19, 20, 21, 31)): a.i(63, reg, 29, 0x80+8*i)
    for i in range(4): a.i(57, 20+i, 29, 0xC0+4*i)
    a.move(16, 4); a.call(NATIVE)
    a.i(63, 2, 29, 0x70); a.i(63, 3, 29, 0x78)
    core.gate(a, 'done')
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'done')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'done')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'done')
    a.li(8, A(0x333700)); a.lw(8, 8); a.branch(5, 8, 0, 'done')
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'done')
    a.li(8, core.POINTERS); a.move(18, 0)
    a.label('scan'); a.lw(17, 8); a.branch(4, 17, 0, 'next')
    a.lw(9, 17, 12); a.i(11, 11, 9, 12); a.branch(4, 11, 0, 'next')
    a.r(0, 9, 0, 9, 2); a.li(11, core.MODELS); a.r(0x2D, 11, 11, 9); a.lw(11, 11)
    a.branch(4, 11, 16, 'found')
    a.label('next'); a.addiu(8, 8, 4); a.addiu(18, 18, 1)
    a.branch(5, 18, 10, 'scan'); a.jump('done')
    a.label('found')
    for offset in (4, 8): a.lw(9, 16, offset); a.branch(4, 9, 0, 'done')
    # Avoid scripted placement and participant staging, including native intro
    # and result actions. Ordinary falling/knockback/KO216 remains eligible.
    a.lw(9, 17, 0x948); a.i(11, 8, 9, 4); a.branch(5, 8, 0, 'done')
    for start, length in ((183, 5), (236, 80)):
        a.addiu(8, 9, -start); a.i(11, 8, 8, length); a.branch(5, 8, 0, 'done')
    # Exclude any active shared cinematic; transforms have the action gate too.
    a.call(A(0x23DBC0)); a.branch(5, 2, 0, 'done')
    a.lw(19, 16, 4000); a.branch(4, 19, 0, 'done')
    a.i(49, 22, 19, 16)
    constant(a, 0, 0.0); fp(a, 0x34, 0, 0, 22); a.branch(17, 8, 0, 'done')
    constant(a, 0, 128.0); fp(a, 0x34, 0, 22, 0); a.branch(17, 8, 0, 'done')
    # Prior world root = native previous base + previous animation root offset.
    a.i(49, 20, 17, 260); a.i(49, 0, 17, 292); fp(a, 0, 20, 20, 0)
    a.i(49, 21, 16, 2420); fp(a, 1, 23, 21, 20)
    constant(a, 0, 4.0); fp(a, 0, 0, 22, 0)
    fp(a, 0x34, 0, 0, 23); a.branch(17, 8, 0, 'done')
    constant(a, 0, 256.0); fp(a, 0x34, 0, 23, 0); a.branch(17, 8, 0, 'done')
    # Keep the sweep local (<=two collision radii horizontally).
    for f, off in ((1, 0), (2, 8)):
        a.i(49, f, 17, 256+off); a.i(49, 0, 17, 288+off); fp(a, 0, f, f, 0)
        a.i(49, 0, 16, 2416+off); fp(a, 1, f, 0, f); fp(a, 2, f, f, f)
    fp(a, 0, 1, 1, 2); fp(a, 2, 2, 22, 22); constant(a, 0, 4.0); fp(a, 2, 2, 2, 0)
    fp(a, 0x36, 0, 1, 2); a.branch(17, 8, 0, 'done')
    # Counter and last candidate fields do not affect simulation state.
    a.li(20, CONTROL); a.lw(8, 20, 16); a.addiu(8, 8, 1); a.sw(8, 20, 16)
    a.sw(18, 20, 24); a.i(57, 20, 20, 28); a.i(57, 21, 20, 32)
    # Native AABB construction matches1B15B8: narrow X/Z, long downward query
    # generated internally by1B1260. Its native callback checks triangle XY
    # coverage, upward-facing normal, and non-solid flags.
    for off in (0, 8): a.lw(8, 16, 2416+off); a.sw(8, 29, 0x20+off)
    constant(a, 0, 0.25); fp(a, 1, 20, 20, 0); a.i(57, 20, 29, 0x24)
    constant(a, 0, 1.0); a.i(57, 0, 29, 0x2C); a.i(57, 0, 29, 0x34); a.i(57, 0, 29, 0x3C)
    constant(a, 0, 0.1); a.i(57, 0, 29, 0x30); a.i(57, 0, 29, 0x38)
    a.addiu(4, 29, 0); a.addiu(5, 29, 0x20); a.addiu(6, 29, 0x30); a.call(A(0x230B38))
    # Output includes floor XYZ + plane + flags, same layout as ext+98352.
    for off in (0, 8): a.lw(8, 16, 2416+off); a.sw(8, 29, 0x40+off)
    a.sw(0, 29, 0x4C); a.sw(0, 29, 0x54)
    a.lw(4, 16, 2596); a.addiu(5, 29, 0); a.addiu(6, 29, 0x40)
    fp(a, 6, 12, 20); a.call(A(0x1B14C0))
    a.i(49, 0, 29, 0x54); constant(a, 1, -0.5)
    fp(a, 0x36, 0, 0, 1); a.branch(17, 8, 0, 'done')
    a.i(49, 0, 29, 0x44)
    fp(a, 0x34, 0, 20, 0); a.branch(17, 8, 0, 'done')
    fp(a, 1, 1, 21, 0); fp(a, 0x34, 0, 22, 1); a.branch(17, 8, 0, 'done')
    # Native model correction ordering follows1B1F58: translation, transforms,
    # current sphere. Enclosing1C2098 then copies this model root back to actor.
    fp(a, 1, 23, 0, 21); a.i(49, 1, 16, 2388); fp(a, 0, 1, 1, 23); a.i(57, 1, 16, 2388)
    a.i(57, 0, 20, 36); a.lw(8, 20, 20); a.addiu(8, 8, 1); a.sw(8, 20, 20)
    a.move(4, 16); a.call(A(0x24E2B0)); a.move(4, 16); a.call(A(0x24E3F8))
    a.move(4, 16); a.move(5, 0); a.call(A(0x24DC58))
    a.label('done')
    a.i(55, 2, 29, 0x70); a.i(55, 3, 29, 0x78)
    for i in range(4): a.i(49, 20+i, 29, 0xC0+4*i)
    for i, reg in enumerate((16, 17, 18, 19, 20, 21, 31)): a.i(55, reg, 29, 0x80+8*i)
    a.addiu(29, 29, 0xF0); a.jr()
    data=a.finish(); assert len(data) < NATIVE-CODE; return data


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('128MiB EE RAM required')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager=u(core.ACTORS); count=len(config['actors']) if config else u(core.MODE+4)
    if (count not in ACTOR_COUNTS or not 0x100000<=manager<len(ram)-0x1000 or u(manager)!=2
            or u(core.MODE+8)!=manager or u(core.MODE+12)!=count):
        raise ValueError('Captured native two-row4/6 match required')
    if any(ram[CODE:END]): raise ValueError('Terrain crossing reservation occupied')
    _,_,native=elf_reader(elf_path(ROOT))
    if ram[ENTRY:ENTRY+8]!=native(ENTRY,8): raise ValueError('Native floor update entry changed')
    control=bytearray(0x100);struct.pack_into('<3I',control,0,1,manager,count)
    parts=[(CODE,payload()),(NATIVE,native(ENTRY,8)+struct.pack('<2I',(2<<26)|((ENTRY+8)>>2),0)),
           (CONTROL,bytes(control)),(ENTRY,struct.pack('<2I',(2<<26)|(CODE>>2),0))]
    blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in parts]
    return dict(serial=SERIAL,crc=CRC,source=str(Path(source).resolve()),blocks=blocks,control=CONTROL,
        status='EXPERIMENTAL NATIVE TRIANGLE FLOOR-CROSSING RECOVERY; LIVE VALIDATION REQUIRED',
        telemetry=dict(candidates=CONTROL+16,recoveries=CONTROL+20,last_actor=CONTROL+24,
                       previous_y=CONTROL+28,current_y=CONTROL+32,floor_y=CONTROL+36),
        limitations=['Prevents newly missed deep downward crossings; does not teleport an already-stuck checkpoint.',
                     'Skips cinematics, scripted actions, long/horizontal teleports, missing or steep ground.',
                     'Uses real native stage triangles; other kinds of terrain/root-motion failure need a failing snapshot.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    x=p.parse_args();r=build_memory(read_ram(x.source),source=x.source);x.out.write_text(json.dumps(r,indent=2)+'\n');print(f'{x.out}: {len(r["blocks"])} blocks')
