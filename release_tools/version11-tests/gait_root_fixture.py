"""Native MIPS post-conversion adaptation of the owned walk/run hip channel."""
import struct
import unittest

import ground_clips as clips
import ground_locomotion as ground
import ground_root_motion as root
from native_map import A, TRANSLATED
from gait_fixture import machine, MODELS, ACTORS, DEST, set_flag

SENTINEL = 0xFEED0000
BIND = (0.2, -10.0, -.6)
CURVE = ((.02, -.04, .01), (-.03, .05, -.02), (.02, -.04, .01))
PARTS = 0x3100000


def clip(curve=CURVE, tag=None):
    tag = root.root_tag(clips.RUN, 3) if tag is None else tag
    header = bytearray(148)
    struct.pack_into('<HHH', header, 0, 0x61, 32, 0)
    struct.pack_into('<H', header, 10, 37)
    body = struct.pack('<HH', tag, len(curve))
    for i, xyz in enumerate(curve):
        body += struct.pack('<3fIQ', *xyz, i*16, clips.encode_quat((0., 0., 0., 1.)))
    return bytes(header) + body


def prepared(layer=0, char=0):
    c = machine()
    for p, b in root.programs() + root.data_blocks({(0, 3): clips.compress_literal(clip())}):
        c.write(p, b)
    c.write(root.SITE, ground.native()(root.SITE, 0x28))
    for p, b in root.hook_patches(): c.write(p, b)
    model = MODELS[0]
    c.w(model+12, char)
    c.w(model+68, PARTS)
    for bone in range(3):
        c.write(PARTS+64*bone, struct.pack('<IHHHH', 64, 0, int(bone == 2), 0, bone)+bytes(52))
    c.write(PARTS+128+48, struct.pack('<3f', *BIND))
    dest = DEST + (0xC000 if layer else 0)
    c.write(dest, clip())
    # Simulate the optional native 24BBE8 conversion having changed every XYZ.
    # Our result must come from the immutable curve rather than those values.
    for i in range(len(CURVE)): c.write(dest+152+i*24, struct.pack('<3f', 90., 91., 92.))
    desc = model + (0xBD8 if layer else 0xB40)
    c.w(desc, dest); c.write(desc+8, struct.pack('<H', 5 if layer else 3))
    c.w(ground.ACTORS+ground.R['lean_src' if layer else 'base_src'], 1)
    c.r[16], c.r[18], c.r[19] = desc, model, layer
    c.r[29] = 0x3200000
    c.r[2] = 0x12345678
    c.write(c.r[29]+0x40, struct.pack('<Q', SENTINEL))
    c.dest = dest
    return c


def run(c):
    c.run(root.SITE, stops=(SENTINEL,))
    return [struct.unpack('<3f', c.read(c.dest+152+i*24, 12)) for i in range(len(CURVE))]
