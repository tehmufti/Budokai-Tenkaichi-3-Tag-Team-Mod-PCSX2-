import support
"""Execute original dash contact loop and both native clash coordinators."""
import struct
import unittest
import dash_clash as fix
import beam_clash as beam
import counter_beam_fixture as base
from prototype import ROOT

ACTORS, MIDS, MANAGER = base.ACTORS, base.MIDS, base.MANAGER


class Cpu(base.Cpu):
    def extra_instruction(self,ins,pc):
        if ins>>26==0 and ins&63==27:
            left=self.r[(ins>>21)&31]&0xFFFFFFFF;right=self.r[(ins>>16)&31]&0xFFFFFFFF
            self.lo=left//right if right else 0xFFFFFFFF;self.hi=left%right if right else left
            return None
        return super().extra_instruction(ins,pc)


def has_flag(c,pid,n):
    return any(c.read(ACTORS[pid]+bank+(n>>3),1)[0] & (1<<(n&7)) for bank in (0x1085,0x10AD))


def machine():
    c=base.machine();c.__class__=Cpu
    for p,n in ((0x1C9010,0x248),(0x1D87D8,0x1A8),(0x1D8D08,0x100),
                (0x1D9330,0x6D0),(0x1DA9D0,0x300)):
        c.write(p,base.NATIVE(p,n))
    for p,b in beam.pieces():c.write(p,b)
    for p,b in fix.pieces():c.write(p,b)
    c.write(fix.CONTROL,struct.pack('<4I',fix.MAGIC,MANAGER,6,base.BATTLE))
    for i,actor in enumerate(ACTORS):
        c.w(fix.CONTROL+0x100+4*i,actor);c.w(actor+2376,11)
    c.callbacks[0x1DA370]=lambda m:c.events.append(('sound',m.r[4],m.r[5]))
    c.callbacks[0x1DB770]=lambda m:m.r.__setitem__(2,m.u(fix.core.TABLE+4*ACTORS.index(m.r[4])))
    c.callbacks[0x1CF578]=lambda m:c.events.append(('move',m.r[4],m.r[5]))
    c.callbacks[0x1DEEA8]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[0x1C7330]=lambda m:c.camera.append((m.r[4],m.r[5],m.r[6]))
    c.callbacks[0x1C7A88]=lambda m:None
    c.callbacks[0x1DC3A8]=lambda m:m.r.__setitem__(2,44)
    c.callbacks[0x241EA0]=lambda m:m.r.__setitem__(2,8)
    c.callbacks[0x241EC8]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x12AB38]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x1E11D0]=lambda m:None
    return c


def flag(c,pid,n):
    offset=ACTORS[pid]+0x1085+(n>>3)
    c.write(offset,bytes([c.read(offset,1)[0]|1<<(n&7)]))


def contact(c,first,second,kind=250):
    c.w(fix.core.TABLE+4*first,second);c.w(fix.core.TABLE+4*second,first)
    flag(c,first,3);flag(c,first,0x47)
    flag(c,second,0x47 if kind==250 else 0x48)
    c.run(0x1C9010)
