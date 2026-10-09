"""Walk and run on the ground (ground_locomotion.py): DECODE runs inside the disc's own clip decoder 24C590, SPEED
at its hook sites and inside the disc's own action-13 handler; the builder against synthetic and captured RAM."""
import math
import os
import random
import struct
import unittest
from pathlib import Path

import fresh_team_combat as core
import ground_clips as clips
import ground_legs
import ground_locomotion as fix
import mod_settings
from native_map import A, FLAG, GP, elf_path
from prototype import ROOT, elf_reader
from test_extra_special_pools import Cpu as PoolCpu

READ = elf_reader(elf_path(ROOT))[2]
MANAGER, ATTRIBUTES = 0x1800000, 0x1810000
ACTORS = [0x1900000 + i*0x2000 for i in range(6)]
MODELS = [0x1A00000 + i*0x2000 for i in range(6)]
RECORDS = [0x1B00000 + i*0x200 for i in range(6)]
DEST = 0x1C00000
RA = 0x1EEF1C
BLEND = struct.unpack('<f', struct.pack('<f', 0.15))[0]
LEGACY = dict(mod_settings.DEFAULTS)
ON = dict(LEGACY, ground_running=True)


class Cpu(PoolCpu):
    """The pool interpreter plus srlv and c.eq.s."""
    def extra_instruction(self, ins, pc):
        if ins >> 26 == 0 and ins & 63 == 6:
            self.r[(ins >> 11) & 31] = (self.r[(ins >> 16) & 31] & 0xFFFFFFFF) >> (self.r[(ins >> 21) & 31] & 31)
            return None
        if ins >> 26 == 0 and ins & 63 == 4:
            self.r[(ins >> 11) & 31] = ((self.r[(ins >> 16) & 31] & 0xFFFFFFFF) << (self.r[(ins >> 21) & 31] & 31)) & 0xFFFFFFFF
            return None
        if ins >> 26 == 17 and (ins >> 21) & 31 == 16 and ins & 63 == 0x32:
            self.condition = self.number((ins >> 11) & 31) == self.number((ins >> 16) & 31)
            return None
        if ins >> 26 == 17 and (ins >> 21) & 31 == 16 and ins & 63 == 7:
            self.set_number((ins >> 6) & 31, -self.number((ins >> 11) & 31)); return None
        if ins >> 26 == 17 and (ins >> 21) & 31 == 16 and ins & 63 == 4:      # EE sqrt.s: the operand is ft
            self.set_number((ins >> 6) & 31, math.sqrt(self.number((ins >> 16) & 31))); return None
        if ins >> 26 == 39:   # lwu used by the native quaternion channel evaluator
            rs, rt, off = (ins >> 21) & 31, (ins >> 16) & 31, ins & 65535
            self.r[rt] = self.u(self.r[rs] + (off if off < 32768 else off - 65536)); return None
        if ins >> 26 == 0 and ins & 63 == 60:   # dsll32, assemble packed 64-bit quaternion
            self.r[(ins >> 11) & 31] = (self.r[(ins >> 16) & 31] << (32 + ((ins >> 6) & 31))) & ((1 << 64)-1)
            return None
        if ins >> 26 == 17 and (ins >> 21) & 31 == 20 and ins & 63 == 32:
            self.set_number((ins >> 6) & 31, self.signed_word(self.f[(ins >> 11) & 31])); return None
        return super().extra_instruction(ins, pc)


def settings(**changes):
    return mod_settings.validate_settings(dict(ON, **changes))


def set_flag(c, actor, usa, on=True):
    n = FLAG(usa); p = actor + 0x1085 + (n >> 3)
    value = c.read(p, 1)[0]
    c.write(p, bytes([value | (1 << (n & 7)) if on else value & ~(1 << (n & 7))]))


def machine(options=None, count=6):
    c = Cpu({'segments': []})
    c.r[28] = GP
    s = settings(**(options or {}))
    for p, d in fix.programs(): c.write(p, d)
    where, female, pieces = fix.layout_profiles()
    directory, frames = fix.table_bytes(where)
    c.write(fix.FEMALE_DIRECTORY, fix.table_bytes(female)[0]); c.write(fix.FEMALE_BITS, fix.female_bits())
    c.female_where = female
    c.write(fix.CONTROL, fix.control_bytes(MANAGER, count, s))
    c.write(fix.DIRECTORY, directory); c.write(fix.FTABLE, frames)
    c.write(fix.CONSTS, fix.consts_bytes()); c.write(fix.LEGS, fix.legs_bytes())
    c.where = where
    c.write(core.MODE, struct.pack('<4I', 1, count, MANAGER, count))
    c.w(core.ACTORS, MANAGER); c.w(MANAGER, 2); c.w(MANAGER+0x20, ATTRIBUTES)
    for i in range(count):
        c.w(core.POINTERS+4*i, ACTORS[i]); c.w(ACTORS[i]+12, i); c.w(core.MODELS+4*i, MODELS[i])
        c.w(ACTORS[i]+0x948, 13); c.w(ACTORS[i]+0x974, 3); c.w(ACTORS[i]+0x980, 5)
        c.w(ACTORS[i]+4, i)
        c.w(MODELS[i]+0x1660, DEST)
        for anim in range(414): c.w(MODELS[i]+0xC0+4*anim, 0x2000000 + i*0x10000 + anim*0x10)
        c.fw(MODELS[i]+0x1004, 6.13); c.fw(MODELS[i]+0xC80, 2.0); c.fw(MODELS[i]+0xB44, float(clips.LOOP_FRAMES[clips.RUN]))
        c.w(MODELS[i]+0xB40, DEST + i*0xC000); c.w(MODELS[i]+0xC74, 2)
        c.fw(MODELS[i]+0xC78, 6.0)
        c.fw(RECORDS[i]+304, 0.0); c.fw(RECORDS[i]+308, -1.0)
        set_flag(c, ACTORS[i], 0xF)
    # The disc's own clip decoder, patched.
    c.write(A(0x24C590), READ(A(0x24C590), 0x78))
    c.write(A(0x24D410), READ(A(0x24D410), 0x88))
    for p, d in fix.hook_patches():
        if p in (fix.DECODE_SITE, fix.STEP_SITE): c.write(p, d)
    c.decoded, c.requests, c.moves = [], [], []
    def clobber(m):
        """A real callee may destroy every caller-saved register: at, v0/v1, a0..a3, t0..t9 and f0..f19."""
        for r in tuple(range(1, 16)) + (24, 25): m.r[r] = 0xDEAD0000 + r
        for f in range(20): m.f[f] = 0x4E000000 + f
    def decode(m):
        m.decoded.append((m.r[4], m.r[5], m.r[6]))
    c.callbacks[fix.DECODE_FN] = decode
    def request(m):
        m.requests.append((m.r[4], m.r[5], m.number(12)))
        set_flag(m, m.r[4], 0x2D); m.w(m.r[4]+0x978, m.r[5])          # 1C41A0 queues (1DA9D0, +0x978)
        clobber(m)
    c.callbacks[fix.REQUEST] = request
    def pad_record(m):
        record = RECORDS[ACTORS.index(m.r[4])]; clobber(m); m.r[2] = record
    c.callbacks[fix.PAD_RECORD] = pad_record
    def move(m):
        m.moves.append(dict(ra=m.r[31], a=tuple(m.r[4:8]), f12=m.number(12), f13=m.number(13), sp=m.r[29],
                            s=tuple(m.r[16:24]), f=tuple(m.f[20:32])))
    c.callbacks[fix.MOVE] = move
    return c


def decode(c, model, anim, dest=DEST, out=0x1D00000):
    c.r[4:8] = [model, dest, anim, out]; c.r[31] = 0xFEED0000; c.r[16] = 0x5050
    c.r[29] = 0x2000000 - 0x100
    c.run(A(0x24C590))
    return c.decoded[-1] if c.decoded else None


def speed(c, i, f12=4.07, site=0, a1=None):
    c.r[4], c.r[5], c.r[6], c.r[7] = ACTORS[i], (0 if site == 0 else 2) if a1 is None else a1, 5, 3
    c.set_number(12, f12); c.set_number(13, 0.925926); c.r[31] = RA
    c.run(fix.SPEED, stops=(RA,))
    result = c.moves[-1]
    if row(c, i, 'step_clip'): clock_step(c, i)
    return result


def clock_step(c, i):
    c.r[4], c.r[31] = MODELS[i], 0xFEED0000
    c.run(A(0x24D410))


def row(c, i, field): return c.u(fix.ACTORS + fix.ROW*i + fix.R[field])
def counter(c, name): return c.u(fix.CONTROL + fix.COUNTERS[name])
def native_clip(i, anim): return 0x2000000 + i*0x10000 + anim*0x10
GOKU = ground_legs.BT3[0]


def expect_v(f12, action=13, gait=0, run=100, walk=40, leg=GOKU, size=True, cap=True):
    """The speed SPEED passes on before the ramp: native x gait scale x size factor, at most the step cap."""
    if action == 13: scale = (run/100*fix.RUN_BASE, walk/100*fix.WALK_BASE)[gait]
    else: scale = (run/100, walk/100)[gait]
    factor = min(fix.SIZE_HI, max(fix.SIZE_LO, math.sqrt(leg/ground_legs.REFERENCE))) if size else 1.0
    v = f12*scale*factor
    if size and cap:
        k = (gait + 2*(leg < ground_legs.SMALL)) if action == 13 else clips.WALK
        v = min(v, fix.MAX_STEPS/30*clips.STANCE_SPEED[k]*clips.LOOP_FRAMES[k]/2*leg)
    return v


def wrapped(t, frames, rate=2.0):
    """The native clock hook preserves overflow phase at the loop seam."""
    return t % frames


def expect_r(v, k=0, leg=GOKU, rate=2.0, anim=3):
    frames = clips.FRAMES[(k, anim)]
    foot_speed = clips.STANCE_SPEED[k]*clips.LOOP_FRAMES[k]/frames
    return min(fix.R_MAX, frames/4/rate, max(0.0, v/(foot_speed*leg*rate)))



class Builder:
    @classmethod
    def setUpClass(cls):
            ram = bytearray(0x8000000)
            struct.pack_into('<4I', ram, core.MODE, 1, 6, MANAGER, 6)
            struct.pack_into('<I', ram, core.ACTORS, MANAGER); struct.pack_into('<I', ram, MANAGER, 2)
            struct.pack_into('<I', ram, MANAGER+0x20, ATTRIBUTES)
            for a in range(414): struct.pack_into('<I', ram, ATTRIBUTES+4*a, 0xC0030001 if 8 <= a <= 11 else 0x80030001)
            for p, n in ((fix.DECODE_SITE, 8), (fix.SPEED_SITES[0], 4), (fix.SPEED_SITES[1], 4), (fix.STEP_SITE, 8), (fix.ground_root_motion.SITE, 8)):
                ram[p:p+n] = READ(p, n)
            cls.ram = ram
