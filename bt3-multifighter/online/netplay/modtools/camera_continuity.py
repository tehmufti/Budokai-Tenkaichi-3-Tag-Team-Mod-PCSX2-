"""Keep living camera subjects through authored vanish and show stage destruction.

Guarded addon after extra_throws. Native camera timing and final full-state bind
remain in cinematic_camera_state. The stage exception requires the exact native
unbound stage/director track, not an arbitrary unbound fighter cinematic.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT
from camera_snapshot import read_ram
import camera_successor as successor
import cinematic_camera_state as camera
import extra_throws as throws
import fresh_team_camera as fresh
import fresh_team_combat as core
import leader_camera as leader
from battle_mode_policy import ACTOR_COUNTS

CODE, LOOKUP, OLD_PARTICIPANT = 0x077B0000, 0x077B1000, 0x077B1800
CONTROL, END = 0x077BF000, 0x077C0000
STAGE, DIRECTOR = A(0x2FE9C8), A(0x2FE9B0)
STAGE_ANIMATION, STAGE_ENDED, SCENE_FLAGS = A(0x31BE68), A(0x31BE74), A(0x3337B8)
SAVED = tuple(range(2, 16)) + (24, 25, 31)


def pointer(a, reg, size, fail):
    a.li(8, 0x100000); a.r(0x2B, 9, reg, 8); a.branch(5, 9, 0, fail)
    a.li(8, 0x08000000-size+1); a.r(0x2B, 9, reg, 8); a.branch(4, 9, 0, fail)
    a.i(12, 9, reg, 3); a.branch(5, 9, 0, fail)


def participant_code():
    a = Assembler(CODE); a.addiu(29, 29, -0x90)
    for i, reg in enumerate(SAVED): a.i(63, reg, 29, i*8)
    core.gate(a, 'old')
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'old')
    a.lw(9, 8, 4); a.lw(11, 28, -22364); a.branch(5, 9, 11, 'old')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'old')
    a.i(11, 9, 4, 2); a.branch(4, 9, 0, 'old')
    a.li(8, camera.CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'old')
    a.lw(9, 8, 4); a.branch(5, 9, 11, 'old')
    # 127430 holds the battle scene while the arena is replaced.
    a.li(8, SCENE_FLAGS); a.lw(9, 8); a.i(12, 9, 9, 0x2000); a.branch(4, 9, 0, 'old')
    a.li(8, STAGE_ENDED); a.lw(9, 8); a.branch(5, 9, 0, 'old')
    a.li(8, STAGE); a.lw(14, 8); pointer(a, 14, 0x9B70, 'old')
    a.li(8, DIRECTOR); a.lw(12, 8); pointer(a, 12, 28, 'old')
    a.lw(13, 28, -22180); pointer(a, 13, 832, 'old')
    # Require the native animated mode; a menu/viewer direct override is not it.
    a.lw(9, 13, 812); a.branch(5, 9, 0, 'old')
    a.lw(9, 13, 776); a.i(12, 9, 9, 3); a.addiu(8, 0, 1); a.branch(5, 9, 8, 'old')
    for off in (768, 772):
        a.lw(9, 13, off); a.branch(5, 9, 0, 'old')
    for off in (12, 20):
        a.lw(9, 12, off); a.addiu(8, 0, 1); a.branch(5, 9, 8, 'old')
    # 13EA88 supplies {-1,-1}; the director also copies modelId to +24.
    for reg, off in ((14, 28), (14, 32), (12, 4), (12, 8), (12, 24)):
        a.lw(9, reg, off); a.addiu(8, 0, -1); a.branch(5, 9, 8, 'old')
    a.lw(15, 13, 704); pointer(a, 15, 24, 'old')
    for reg, off in ((14, 24), (12, 0)):
        a.lw(9, reg, off); a.branch(5, 9, 15, 'old')
    a.li(8, STAGE_ANIMATION); a.lw(9, 8); a.branch(5, 9, 15, 'old')
    a.li(8, CONTROL); a.lw(9, 8, 16); a.addiu(9, 9, 1); a.sw(9, 8, 16)
    for reg, off in ((13, 20), (15, 24), (14, 28), (4, 32)): a.sw(reg, 8, off)
    for i, reg in enumerate(SAVED): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x90); a.addiu(2, 0, 1); a.jr()
    a.label('old')
    for i, reg in enumerate(SAVED): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x90); a.jump(OLD_PARTICIPANT)
    code = a.finish(); assert len(code) < LOOKUP-CODE
    return code


def lookup_code():
    return fresh.rebound(successor.lookup_stub, LOOKUP=LOOKUP)(require_visibility=False)


def pieces(manager, count):
    old = throws.participant_code()
    # The verified prologue is addiu sp,-0x90; sd v0,0(sp), without branches.
    assert old[:8] == struct.pack('<2I', 0x27BDFF70, 0xFFA20000)
    trampoline = old[:8] + struct.pack('<2I', (2<<26)|((throws.PARTICIPANT+8)>>2), 0)
    control = bytearray(64); struct.pack_into('<4I', control, 0, 1, manager, count, 1)
    return [(CODE, participant_code(), 'Recognize the native global arena-destruction cinematic'),
            (LOOKUP, lookup_code(), 'Keep living registered subjects while their model is temporarily hidden'),
            (OLD_PARTICIPANT, trampoline, 'Preserve the installed actual-throw participant chain'),
            (CONTROL, bytes(control), 'Capture identity and global-stage camera telemetry')]


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x08000000: raise ValueError('Requires 128 MiB EE memory')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if not 0x100000 <= manager <= len(ram)-0x1000 or u(manager) != 2:
        raise ValueError('Native captured manager required')
    if u(core.MODE) != 1 or u(core.MODE+8) != manager or count not in ACTOR_COUNTS or u(core.MODE+12) != count:
        raise ValueError('Requires active captured four/six configuration')
    if config and (config.get('actor_manager', manager) != manager or config.get('count', count) != count):
        raise ValueError('Configuration disagrees with captured memory')
    for p, words, name in ((fresh.SUCCESSOR_CONTROL, {0:1, 4:manager}, 'successor'),
                           (camera.CONTROL, {0:1, 4:manager}, 'cinematic'),
                           (throws.CONTROL, {0:1, 4:manager, 8:count}, 'throw')):
        if any(u(p+off) != value for off, value in words.items()):
            raise ValueError(f'Requires active matching {name} control')
    old_lookup = fresh.rebound(successor.lookup_stub, LOOKUP=fresh.LOOKUP)()
    checks = [(fresh.LOOKUP, old_lookup, 'original successor lookup'),
              (throws.PARTICIPANT, throws.participant_code(), 'actual-throw participant'),
              (camera.PARTICIPANT, struct.pack('<2I', (2<<26)|(throws.PARTICIPANT>>2), 0), 'throw camera chain'),
              (leader.HOOK, struct.pack('<2I', (2<<26)|(camera.CODE>>2), 0), 'complete native camera bind'),
              (camera.CODE, camera.wrapper(), 'complete native camera binding wrapper')]
    for p, data, name in checks:
        if ram[p:p+len(data)] != data: raise ValueError(f'Requires exact {name}')
    if any(ram[CODE:END]): raise ValueError('Camera continuity reservation occupied')
    payloads = pieces(manager, count)
    payloads += [(fresh.LOOKUP, struct.pack('<2I', (2<<26)|(LOOKUP>>2), 0), 'Route camera lookup through living-visibility policy'),
                 (throws.PARTICIPANT, struct.pack('<2I', (2<<26)|(CODE>>2), 0), 'Preserve throw participation and add verified global stage camera')]
    blocks = [dict(address=p, expected_hex=ram[p:p+len(data)].hex(), data_hex=data.hex(), purpose=why)
              for p, data, why in payloads]
    return dict(serial=SERIAL, crc=CRC, source=str(source), blocks=blocks,
                status='LIVING CAMERA CONTINUITY AND NATIVE STAGE CINEMATIC', control=CONTROL,
                telemetry=dict(stage_views=CONTROL+16, last_camera=CONTROL+20,
                               last_animation=CONTROL+24, last_stage=CONTROL+28, last_side=CONTROL+32),
                limitations=['Live Sonic Sway and planet-destruction framing still require validation.',
                             'No controller transfer, camera-path edits, actor repositioning or extra cinematic tracks.'])


def build(source): return build_memory(read_ram(source), source=str(source))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    args = p.parse_args(); result = build(args.source)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'{args.out}: {len(result["blocks"])} guarded blocks')
