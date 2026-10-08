"""Retarget only mod-owned walk/run hip translations after native clip conversion.

Native 24D038 may retarget decoded translation keys through 24BBE8 before its
epilogue. The hook here runs afterwards, using immutable normalized curves and
the current model's PMDL bind root. It never writes mesh data or actor position.
"""
from __future__ import annotations

import math
import struct

from native_map import A
from prototype import Assembler
import fresh_team_combat as core
import ground_legs

BASE, END = 0x06F7C000, 0x06F80000
CODE, RECORDS, CURVES = BASE, BASE + 0x800, BASE + 0x1000
SITE, RESUME = A(0x24D150), A(0x24D158)
WORDS = (0xDFB00010, 0xDFB10018)  # ld s0,0x10(sp); ld s1,0x18(sp)
TAG = 0x4000
MAX_RECORDS = 80                 # two profiles x four gait sets x ten clip IDs
MAX_KEYS = 65


def root_tag(gait, anim, profile=0):
    """Even channel flags retain native type-0 semantics; high bits identify ours."""
    if profile not in (0, 1) or gait not in range(4) or anim not in range(2, 12):
        raise ValueError('Invalid walk/run root curve identity')
    return TAG + 2 * (1 + profile * 40 + gait * 10 + anim - 2)


def data_blocks(built_sets=None):
    """Immutable XYZ copied from the marked, normalized type-0 clip keys.

Accept one build_set dictionary or a sequence of dictionaries (male/source
profiles). Native conversion may mutate the decoded keys; these never change.
    """
    import ground_clips as clips
    if built_sets is None:
        built_sets = [clips.build_set(profile=p) for p in ('male', 'female')]
    groups = [built_sets] if isinstance(built_sets, dict) else built_sets
    tracks = {}
    for built in groups:
        for packed in built.values():
            decoded = clips.decompress_literal(packed)
            offset = struct.unpack_from('<H', decoded, 10)[0] * 4
            if not offset:
                continue
            flags, count = struct.unpack_from('<HH', decoded, offset)
            if not TAG < flags <= TAG + 2 * MAX_RECORDS or flags & 1:
                continue
            if not 1 <= count <= MAX_KEYS or offset + 4 + count * 24 > len(decoded):
                raise ValueError('Invalid marked walk/run hip track')
            values = [struct.unpack_from('<3f', decoded, offset + 4 + i * 24) for i in range(count)]
            if not all(math.isfinite(v) and abs(v) < 4 for row in values for v in row):
                raise ValueError('Walk/run hip keys must be normalized finite displacements')
            curve = b''.join(struct.pack('<3f', *row) for row in values)
            index = (flags - TAG) // 2 - 1
            if index in tracks and tracks[index] != (count, curve):
                raise ValueError('Walk/run hip curve identity collision')
            tracks[index] = (count, curve)
    records = bytearray(MAX_RECORDS * 16)
    output, placed = bytearray(), {}
    for index, (count, curve) in sorted(tracks.items()):
        if curve not in placed:
            output.extend(bytes((-len(output)) % 16))
            placed[curve] = CURVES + len(output)
            output.extend(curve)
        struct.pack_into('<4I', records, index * 16, TAG + 2 * (index + 1), count, placed[curve], 0)
    if CURVES + len(output) > END:
        raise ValueError('Walk/run hip curves exceed their reservation')
    return [(RECORDS, bytes(records)), (CURVES, bytes(output))]


def pointer(a, reg, size, fail):
    """Check a four-byte-aligned EE pointer; uses t0/t1 only."""
    a.i(12, 8, reg, 3); a.branch(5, 8, 0, fail)
    a.li(8, 0x100000); a.r(0x2B, 9, reg, 8); a.branch(5, 9, 0, fail)
    a.li(8, 0x08000000-size+1); a.r(0x2B, 9, reg, 8); a.branch(4, 9, 0, fail)


def code():
    import ground_locomotion as ground
    a = Assembler(CODE)
    # Native decoder's 0x50-byte frame still exists. Its scratch output word is
    # dead here; preserve the native return value without altering its stack.
    a.sw(2, 29, 0)
    ground.gate(a, 'done')
    pointer(a, 18, 0x1670, 'done')
    a.move(11, 0)
    a.label('actors'); a.branch(4, 11, 10, 'done')
    a.r(0, 8, 0, 11, 2); a.li(9, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(15, 8)
    a.branch(4, 15, 0, 'next')
    a.lw(12, 15, 12); a.i(11, 13, 12, 12); a.branch(4, 13, 0, 'next')
    a.r(0, 12, 0, 12, 2); a.li(13, core.MODELS); a.r(0x21, 12, 12, 13); a.lw(12, 12)
    a.branch(4, 12, 18, 'found')
    a.label('next'); a.addiu(11, 11, 1); a.jump('actors')
    a.label('found'); ground.ground(a, 15, 'done')
    a.r(0, 24, 0, 11, 6); a.li(8, ground.ACTORS); a.r(0x21, 24, 24, 8)
    a.i(11, 8, 19, 2); a.branch(4, 8, 0, 'done')  # only native base/layer 0 or 1
    a.addiu(8, 18, 0xB40); a.branch(4, 19, 0, 'descriptor')
    a.addiu(8, 8, 0x98)
    a.label('descriptor'); a.branch(5, 8, 16, 'done')
    a.i(37, 8, 16, 8); a.addiu(8, 8, -2); a.i(11, 8, 8, 8); a.branch(4, 8, 0, 'done')
    a.lw(8, 24, ground.R['base_src']); a.branch(4, 19, 0, 'source')
    a.lw(8, 24, ground.R['lean_src'])
    a.label('source'); a.addiu(8, 8, -1); a.i(11, 8, 8, 4); a.branch(4, 8, 0, 'done')
    a.lw(4, 16); pointer(a, 4, 0xC000, 'done')
    a.lw(8, 18, 0x1660); a.branch(4, 19, 0, 'buffer')
    a.li(9, 0xC000); a.r(0x21, 8, 8, 9)
    a.label('buffer'); a.branch(5, 8, 4, 'done')
    a.i(37, 5, 4, 10); a.r(0, 5, 0, 5, 2)
    a.i(11, 8, 5, 148); a.branch(5, 8, 0, 'done')
    a.li(8, 0xC000-4-MAX_KEYS*24); a.r(0x2B, 8, 5, 8); a.branch(4, 8, 0, 'done')
    a.r(0x21, 5, 5, 4)
    a.i(37, 8, 5, 0); a.addiu(9, 8, -(TAG+2))
    a.i(11, 12, 9, MAX_RECORDS*2); a.branch(4, 12, 0, 'done')
    a.i(12, 12, 9, 1); a.branch(5, 12, 0, 'done')
    a.r(2, 9, 0, 9, 1); a.r(0, 9, 0, 9, 4); a.li(12, RECORDS); a.r(0x21, 12, 12, 9)
    a.lw(9, 12); a.branch(5, 8, 9, 'done')
    a.i(37, 7, 5, 2); a.lw(9, 12, 4); a.branch(5, 7, 9, 'done')
    a.addiu(8, 7, -1); a.i(11, 8, 8, MAX_KEYS); a.branch(4, 8, 0, 'done')
    a.lw(6, 12, 8); a.li(8, CURVES); a.r(0x2B, 9, 6, 8); a.branch(5, 9, 0, 'done')
    a.r(0, 8, 0, 7, 3); a.r(0, 9, 0, 7, 2); a.r(0x21, 8, 8, 9)
    a.r(0x21, 8, 8, 6); a.li(9, END); a.r(0x2B, 8, 9, 8); a.branch(5, 8, 0, 'done')
    # Locate root on this exact costume/body. Only the first 128 bounded PMDL
    # nodes may be inspected, so a missing/malformed skeleton safely declines.
    a.lw(15, 18, 68); a.addiu(25, 0, 128)
    a.label('bones'); pointer(a, 15, 64, 'done')
    a.i(37, 8, 15, 10); a.addiu(9, 0, 2); a.branch(4, 8, 9, 'root')
    a.i(37, 8, 15, 6); a.branch(5, 8, 0, 'done')
    a.lw(8, 15); a.i(11, 9, 8, 64); a.branch(5, 9, 0, 'done')
    a.li(9, 0x400000); a.r(0x2B, 9, 8, 9); a.branch(4, 9, 0, 'done')
    a.r(0x21, 15, 15, 8); a.addiu(25, 25, -1); a.branch(5, 25, 0, 'bones'); a.jump('done')
    a.label('root')
    # Local model units, without model+0xA20 scale: the native model matrix
    # already applies giant scaling once to the complete skeleton.
    ground.fconst(a, 0, ground_legs.REFERENCE)
    a.lw(8, 18, 12); a.li(9, len(ground.legs())); a.r(0x2B, 9, 8, 9); a.branch(4, 9, 0, 'fallback')
    a.r(0, 8, 0, 8, 2); a.li(9, ground.LEGS); a.r(0x21, 8, 8, 9); ground.lwc1(a, 1, 8)
    ground.fconst(a, 2, 0.0); ground.c_olt(a, 2, 1); ground.bc1f(a, 'fallback')
    ground.fconst(a, 2, 128.0); ground.c_olt(a, 1, 2); ground.bc1f(a, 'fallback')
    ground.mov_s(a, 0, 1); a.jump('keys')
    a.label('fallback'); ground.lwc1(a, 1, 18, 0x1004)
    ground.fconst(a, 2, .5); ground.c_olt(a, 2, 1); ground.bc1f(a, 'keys')
    ground.fconst(a, 2, 512.0); ground.c_olt(a, 1, 2); ground.bc1f(a, 'keys')
    ground.fconst(a, 2, ground.R_DEFAULT); ground.div_s(a, 1, 1, 2); ground.mul_s(a, 0, 0, 1)
    a.label('keys'); a.addiu(5, 5, 4)
    # Validate all three bind values before the first write (reject NaN/Inf).
    for off in (48, 52, 56):
        a.lw(8, 15, off); a.li(9, 0x7F800000); a.r(0x24, 8, 8, 9); a.branch(4, 8, 9, 'done')
    a.label('key')
    for axis in range(3):
        ground.lwc1(a, 1, 6, axis*4); ground.mul_s(a, 1, 1, 0)
        ground.lwc1(a, 2, 15, 48+axis*4); ground.add_s(a, 1, 1, 2); ground.swc1(a, 1, 5, axis*4)
    a.addiu(5, 5, 24); a.addiu(6, 6, 12); a.addiu(7, 7, -1); a.branch(5, 7, 0, 'key')
    a.label('done'); a.lw(2, 29, 0)
    a.i(55, 16, 29, 0x10); a.i(55, 17, 29, 0x18); a.jump(RESUME)
    result = a.finish()
    if len(result) > RECORDS-CODE:
        raise ValueError('Walk/run root helper exceeds its code reservation')
    return result


def programs():
    return [(CODE, code())]


def hook_patches():
    return [(SITE, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0))]


def disc_check(read):
    if struct.unpack('<2I', read(SITE, 8)) != WORDS:
        raise ValueError('Walk/run post-conversion epilogue changed (24D150)')
