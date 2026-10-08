"""Aim scripted pair cameras at the actual pair, not at the two leaders.

A grab starts the thrower's scripted camera (1FC648 -> 1C7330(actor, 0, 7|8)).
Its entries 7/8, like the global clash/hit entries 6..14, 17..22, 24..27 and
32, use "midpoint" anchors: sub_1C4F68 recomputes them every frame as the
midpoint of two bones, taking the two fighters from sub_1DC178(0) and
sub_1DC178(1). In a native 1v1 those are the two fighters. With more fighters
they are the two leaders, whoever is actually grabbing whom, so a grab of any
other fighter framed the thrower against the enemy leader - often someone
elsewhere on the stage, or a body.

Each of the four midpoint blocks now takes the fighter itself (s4, the actor
this camera belongs to) and its resolved partner: sub_1DB7B0, the native
"opponent model" getter, which the mod routes through the resolver chain, so a
live throw record, a rush or clash pair, or else the lock-on target is used.
The same function's pivot already uses that partner (0x1C5498..0x1C54E4), so
the anchors now agree with it. Leader against leader gives the same midpoint
as before. Only native bytes are replaced; nothing is gated.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

from prototype import ROOT, elf_reader

NATIVE = elf_reader(elf_path(ROOT))[2]
GETTER, OPPONENT_MODEL = A(0x1DC178), A(0x1DB7B0)
# jal 1DC178 ; move a0,zero  ->  daddu v0,s4,zero ; move a0,zero
# (the following 'lw a0,0xc(v0)' then reads the fighter's own model ID)
SELF_SITES = (A(0x1C5078), A(0x1C51B0), A(0x1C52B0), A(0x1C53B8))
# jal 1DC178 ; addiu a0,zero,1 ; daddu a1,s0,zero ; lw a0,0xc(v0)
#   -> jal 1DB7B0 ; daddu a0,s4,zero ; daddu a1,s0,zero ; daddu a0,v0,zero
PARTNER_SITES = (A(0x1C50A0), A(0x1C51D4), A(0x1C52D8), A(0x1C53DC))
JAL = lambda target: (3 << 26) | (target >> 2)
SELF_NATIVE = (JAL(GETTER), 0x0000202D)
SELF_PATCH = 0x0280102D
PARTNER_NATIVE = (JAL(GETTER), 0x24040001, 0x0200282D, 0x8C44000C)
PARTNER_PATCH = (JAL(OPPONENT_MODEL), 0x0280202D, 0x0200282D, 0x0040202D)
for _site in SELF_SITES:
    assert struct.unpack('<2I', NATIVE(_site, 8)) == SELF_NATIVE, hex(_site)
for _site in PARTNER_SITES:
    assert struct.unpack('<4I', NATIVE(_site, 16)) == PARTNER_NATIVE, hex(_site)


def pieces():
    return ([(site, struct.pack('<I', SELF_PATCH)) for site in SELF_SITES] +
            [(site, struct.pack('<4I', *PARTNER_PATCH)) for site in PARTNER_SITES])


def state(ram):
    """'native', 'installed', or raise for anything else at the sites."""
    parts = pieces()
    if all(ram[p:p+len(d)] == d for p, d in parts): return 'installed'
    if all(ram[p:p+len(d)] == NATIVE(p, len(d)) for p, d in parts): return 'native'
    raise ValueError('Pair camera anchor sites changed')


def build_memory(ram, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE RAM')
    if state(ram) == 'installed':
        return dict(serial=SERIAL, crc=CRC, source=str(source), blocks=[], status='PAIR CAMERA ANCHORS INSTALLED')
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex()) for p, d in pieces()]
    return dict(serial=SERIAL, crc=CRC, source=str(source), blocks=blocks,
                status='PAIR CAMERA ANCHORS: SELF AND RESOLVED PARTNER')
