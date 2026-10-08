"""Change who you are watching with the lock-on button, while spectating.

Two situations leave a person with nothing to drive: an all-CPU match, where no
fighter is theirs, and any match after their own fighter is defeated - a death
does not end the match here, so they watch until one fighter is left. In both,
the gesture that switches lock-on targets switches the camera subject instead,
in every mode, and to any fighter on either team.

Whether the watcher is spectating is read from their seat's fighter, never from
the battle-mode block: they are spectating when that fighter is CPU-driven
(actor+0x1278 != 0 - nobody holds its pad) or defeated. The mode block is not a
reliable witness - Team Battle installs none at all, so a CPU-versus-CPU team
match looked like "one human, still alive" and never let the watcher switch.

The choice is recorded as a per-side LOCK in this module's control block
(lock = physical index + 1, zero meaning none). cinematic_policy.subject(), the
first camera authority for every mode, honours a lock before any mode-specific
rule and republishes the chosen fighter for as long as they live, then releases
it. That is what lets the camera stay on a fighter from the other team: without
it, Team Battle falls through to camera_successor, which rescans to a fighter
on the viewport's own side. The owner word is written as well, so the switch
shows on the very next frame.

No actor is needed to read the pad: pad 0's held-button word sits at a fixed
address and sub_122A38 refills it every frame from the global loop, whatever
the scene holds. The gesture is the lock-on one - hold the bound button (R3 by
default, L3 from Mod settings) for fifteen updates and release, a D-pad or
other-stick chord cancelling it - so it matches the muscle memory of switching
targets.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

import fresh_team_camera as fresh
import fresh_team_combat as core
import guest_killfeed as kill
import lockon_switch as lock
from prototype import Assembler
from camera_snapshot import read_ram

HOOK = A(0x1C2A28)
CODE, CONTROL, END = 0x07280000, 0x0728F000, 0x07290000
MAGIC = 0x53504331  # 'SPC1'
# The two polled pad records. sub_122A38 refills both every frame from the
# global loop at 0x12BC64, with no dependence on a scene or on any actor.
PAD_RECORDS, PAD_STRIDE, PAD_BUTTONS = A(0x333800), 448, 328
# guest_killfeed keeps a per-fighter defeated latch, refreshed every battle
# update; one load beats walking a row to compare health.
DEAD = 0x40
SUCCESSOR_OWNER = 8
LEADER_SIDE = 12  # the on-screen side in single view, mirrored by leader_camera
SCENE, SPLIT_OFF, SPLIT_VALUE = A(0x331DC8), 36, 1
HOLD_UPDATES = lock.__dict__.get('HOLD_UPDATES', 15)
STICK_CHORDS = 0xF6  # D-pad plus both stick buttons, before removing the bound one
SLOTS = 12
FIELDS = dict(magic=0, enabled=4, manager=8, seat=12, held=16, subject=20,
              switches=24, watching=28, lock=32)
# lock[side] at +32 and +36: physical index + 1 of the fighter the watcher chose
# for that viewport side, 0 when the camera should choose for itself.
CONTROL_WORDS = 10
CPU_DRIVEN = 0x1278


def pad_buttons(port=0):
    return PAD_RECORDS + PAD_STRIDE*port + PAD_BUTTONS


def payload(previous):
    """Chained onto the actor-update hook; runs every frame in every mode."""
    a = Assembler(CODE)
    a.addiu(29, 29, -0x50)
    saved = tuple((16+i, i*8) for i in range(8))
    for reg, off in saved: a.i(63, reg, 29, off)
    a.li(16, CONTROL); a.lw(8, 16); a.li(9, MAGIC); a.branch(5, 8, 9, 'done')
    a.lw(8, 16, FIELDS['enabled']); a.branch(4, 8, 0, 'done')
    core.gate(a, 'done')          # leaves the published fighter count in t2
    a.move(17, 10)
    # Is the watcher's seat theirs to drive? A CPU-driven seat means nobody
    # holds that pad, which covers an all-CPU match in every mode; a defeated
    # seat means they are watching the rest of the match.
    a.lw(9, 16, FIELDS['seat']); a.r(0x2B, 11, 9, 17); a.branch(4, 11, 0, 'idle')
    a.li(11, core.POINTERS); a.r(0, 12, 0, 9, 2); a.r(0x2D, 11, 11, 12); a.lw(11, 11)
    a.branch(4, 11, 0, 'watching')
    a.lw(13, 11, CPU_DRIVEN); a.branch(5, 13, 0, 'watching')
    a.li(11, kill.CONTROL+DEAD); a.r(0x2D, 11, 11, 12); a.lw(11, 11)
    a.branch(4, 11, 0, 'idle')
    a.label('watching')
    a.addiu(8, 0, 1); a.sw(8, 16, FIELDS['watching'])
    # Split screen gives the watcher the left half; single view follows whichever
    # side the native camera picked, which leader_camera mirrors for us.
    a.li(8, SCENE); a.lw(8, 8, SPLIT_OFF); a.addiu(9, 0, SPLIT_VALUE)
    a.branch(4, 8, 9, 'left')
    a.li(8, fresh.LEADER_CONTROL); a.lw(19, 8, LEADER_SIDE); a.addiu(9, 0, 2)
    a.r(0x2B, 11, 19, 9); a.branch(5, 11, 0, 'side_ready'); a.move(19, 0)
    a.jump('side_ready')
    a.label('left'); a.move(19, 0)
    a.label('side_ready')
    a.li(8, pad_buttons(0)); a.lw(20, 8)
    a.li(8, lock.CONTROL); a.lw(21, 8, lock.FIELDS['button'])
    a.i(13, 9, 21, STICK_CHORDS); a.r(0x26, 9, 9, 21); a.r(0x24, 9, 20, 9)
    a.r(0x24, 8, 20, 21)
    a.lw(10, 16, FIELDS['held'])
    a.branch(4, 8, 0, 'released')
    # Held: a chord means the player wants something else, so drop the hold.
    a.branch(5, 9, 0, 'cancel')
    a.addiu(10, 10, 1); a.sw(10, 16, FIELDS['held']); a.jump('done')
    a.label('cancel'); a.sw(0, 16, FIELDS['held']); a.jump('done')
    a.label('released')
    a.sw(0, 16, FIELDS['held'])
    a.addiu(11, 0, HOLD_UPDATES); a.r(0x2B, 12, 10, 11); a.branch(5, 12, 0, 'done')
    # Start from what is on screen for this side.
    a.li(8, fresh.SUCCESSOR_CONTROL); a.r(0, 9, 0, 19, 2); a.r(0x2D, 8, 8, 9)
    a.lw(22, 8, SUCCESSOR_OWNER)
    a.r(0x2B, 8, 22, 17); a.branch(5, 8, 0, 'current_ready'); a.move(22, 0)
    a.label('current_ready')
    a.move(23, 0)
    a.label('scan')
    a.addiu(23, 23, 1)
    # Stop one short of a full lap so the watcher never "switches" to themselves.
    a.r(0x2B, 8, 23, 17); a.branch(4, 8, 0, 'done')
    a.r(0x21, 9, 22, 23)
    a.r(0x2B, 8, 9, 17); a.branch(5, 8, 0, 'bounded'); a.r(0x23, 9, 9, 17)
    a.label('bounded')
    a.li(8, kill.CONTROL+DEAD); a.r(0, 11, 0, 9, 2); a.r(0x2D, 8, 8, 11); a.lw(8, 8)
    a.branch(5, 8, 0, 'scan')
    # Any living fighter, on either team, in every mode: the lock makes the
    # camera keep them, so there is no side to respect here.
    a.r(0, 11, 0, 19, 2); a.r(0x2D, 11, 16, 11); a.addiu(8, 9, 1); a.sw(8, 11, FIELDS['lock'])
    a.li(8, fresh.SUCCESSOR_CONTROL); a.r(0, 11, 0, 19, 2); a.r(0x2D, 8, 8, 11)
    a.sw(9, 8, SUCCESSOR_OWNER)
    a.sw(9, 16, FIELDS['subject'])
    a.lw(8, 16, FIELDS['switches']); a.addiu(8, 8, 1); a.sw(8, 16, FIELDS['switches'])
    a.jump('done')
    a.label('idle')
    # The watcher is back in control of a living fighter: the camera follows
    # them again, so nothing they chose while watching may linger.
    a.sw(0, 16, FIELDS['watching']); a.sw(0, 16, FIELDS['held'])
    a.sw(0, 16, FIELDS['lock']); a.sw(0, 16, FIELDS['lock']+4)
    a.label('done')
    for reg, off in saved: a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x50)
    a.jump(previous)
    data = a.finish()
    assert len(data) < CONTROL-CODE, 'Spectator switch exceeds its reservation'
    return data


def control_words(manager, seat=0):
    block = bytearray(4*CONTROL_WORDS)
    struct.pack_into('<4I', block, 0, MAGIC, 1, manager, seat)
    return bytes(block)


def chain_head(ram):
    return (struct.unpack_from('<I', ram, HOOK)[0] & 0x3FFFFFF) << 2


def installed(ram):
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if u(CONTROL) != MAGIC or u(CONTROL+FIELDS['enabled']) != 1: return False
    return chain_head(ram) == CODE and ram[CODE:CODE+4] != b'\0\0\0\0'


def build_memory(ram, seat=0, source='<prepared-match>'):
    if len(ram) != 0x8000000: raise ValueError('Requires 128 MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(A(0x2FEB14))
    if not 0x100000 <= manager <= len(ram)-16:
        raise ValueError('Spectator switching requires the captured actor manager')
    if u(core.MODE) != 1 or u(core.MODE+8) != manager:
        raise ValueError('Spectator switching requires the published combat core')
    count = u(core.MODE+4)
    if not 2 <= count <= SLOTS or count != u(core.MODE+12):
        raise ValueError('Spectator switching requires a captured actor roster')
    if not 0 <= seat < count:
        raise ValueError('Spectator seat outside the captured roster')
    if u(fresh.SUCCESSOR_CONTROL) != 1 or u(fresh.SUCCESSOR_CONTROL+4) != manager:
        raise ValueError('Spectator switching requires the captured successor camera')
    # The kill feed has no magic; +0 is its enabled flag and +4 its manager.
    if u(kill.CONTROL) != 1 or u(kill.CONTROL+4) != manager:
        raise ValueError('Spectator switching requires the captured kill feed')
    if installed(ram):
        validate_memory(ram)
        return dict(serial=SERIAL, crc=CRC, source=str(source), blocks=[])
    if any(ram[CODE:END]):
        raise ValueError('Spectator switch reservation occupied')
    previous = chain_head(ram)
    if not 0x100000 <= previous <= len(ram)-8:
        raise ValueError(f'Unknown prior actor-update chain head:{HOOK:08X}')
    pieces = [(CODE, payload(previous)), (CONTROL, control_words(manager, seat)),
              (HOOK, struct.pack('<I', (2 << 26) | (CODE >> 2)))]
    return dict(serial=SERIAL, crc=CRC, source=str(source), seat=seat,
                status='SPECTATOR CAMERA FOLLOWS THE LOCK-ON BUTTON',
                blocks=[dict(address=p, expected_hex=ram[p:p+len(d)].hex(),
                             data_hex=bytes(d).hex()) for p, d in pieces])


def validate_memory(ram):
    """Report the installed spectator policy, or None when absent."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if u(CONTROL) != MAGIC: return None
    import spectator_takeover as takeover
    if u(CONTROL+takeover.F['version'])==takeover.VERSION:
        takeover.validate_memory(ram)
    else:
        if not installed(ram):
            raise ValueError(f'Unrecognized spectator switch installation:{CODE:08X}')
        # Legacy emission keeps its original bytes; derive and validate its
        # complete tail instead of accepting any nonzero first instruction.
        length=len(payload(0));tail=CODE+length-8
        if u(tail)>>26!=2 or u(tail+4):raise ValueError('Spectator chain tail changed')
        previous=(u(tail)&0x3ffffff)<<2
        if not 0x100000<=previous<len(ram)-8 or previous==CODE:raise ValueError('Invalid spectator tail')
        if ram[CODE:CODE+length]!=payload(previous):raise ValueError('Spectator payload changed')
        if u(CONTROL+FIELDS['manager'])!=u(core.ACTORS):raise ValueError('Spectator manager changed')
    return dict(manager=u(CONTROL+FIELDS['manager']), seat=u(CONTROL+FIELDS['seat']),
                switches=u(CONTROL+FIELDS['switches']), subject=u(CONTROL+FIELDS['subject']),
                watching=u(CONTROL+FIELDS['watching']))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ram', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--seat', type=int, default=0)
    x = p.parse_args()
    x.out.write_text(json.dumps(build_memory(read_ram(x.ram), seat=x.seat, source=x.ram), indent=2)+'\n')
    print(x.out)
