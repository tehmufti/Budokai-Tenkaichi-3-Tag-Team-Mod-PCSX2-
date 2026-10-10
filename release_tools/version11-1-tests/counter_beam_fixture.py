import support
"""Execute native beam contact and coordinator paths with captured extra actors."""
import copy
import struct
import unittest

import beam_clash as fix
import fresh_team_combat as core
import team_intro as intro
from prototype import ROOT, elf_reader
from test_extra_special_pools import Cpu as BaseCpu

class Cpu(BaseCpu):
    def extra_instruction(self,ins,pc):
        if ins>>26==17 and (ins>>21)&31==20 and ins&63==32:
            self.f[(ins>>6)&31]=struct.unpack('<I',struct.pack('<f',float(self.signed_word(self.f[(ins>>11)&31]))))[0]
            return None
        if ins>>26==17 and (ins>>21)&31 in (2,6):
            rt=(ins>>16)&31
            if (ins>>21)&31==2:self.r[rt]=getattr(self,'fcr31',0)
            else:self.fcr31=self.r[rt]&0xFFFFFFFF
            return None
        return super().extra_instruction(ins,pc)

NATIVE=elf_reader(support.ELF)[2]
ACTORS=[0x1800000,0x1801600,0x2400000,0x2440000,0x2480000,0x24C0000]
MIDS=[0,1,7,10,3,8]
MODELS=[0x900000+i*0x2000 for i in range(6)]
MANAGER=0x1700000
BATTLE=0x1A00000


def machine():
    c=Cpu({'segments':[]})
    # Native state machine and real per-actor flag helpers remain executable.
    for p,n in ((0x1B0AC8,0x160),(0x1D8750,0xB8),(0x1D87D8,0x108),
                (0x1D8E50,0x4E0),(0x1D9900,0x120),(0x2EF240,0x50),
                (0x206D68,0x50),(0x207350,0x38),(0x1DA9D0,0x180),
                (0x1DAC78,0x38),(0x174CE0,0x128),(0x175440,0xD0)):
        c.write(p,NATIVE(p,n))
    for p,b,_ in core.program():c.write(p,b)
    for p,b in fix.pieces(NATIVE):c.write(p,b)
    c.w(core.ACTORS,MANAGER);c.w(MANAGER,2);c.w(MANAGER+4,ACTORS[0])
    c.write(core.MODE,struct.pack('<4I',1,6,MANAGER,6));c.w(intro.BATTLE,BATTLE);c.w(BATTLE,3)
    c.write(fix.CONTROL,struct.pack('<4I',fix.MAGIC,MANAGER,6,BATTLE))
    c.write(fix.participation.CONTROL,struct.pack('<5I',5,MANAGER,6,63,0))
    c.events=[];c.models_requested=[];c.damage=[];c.camera=[];c.effect_cleanup=[]
    for pid,(actor,mid,model) in enumerate(zip(ACTORS,MIDS,MODELS)):
        c.w(core.POINTERS+4*pid,actor);c.w(core.TABLE+4*pid,pid^1)
        c.w(fix.CONTROL+0x100+4*pid,actor);c.w(core.MODELS+4*mid,model)
        c.w(actor,pid);c.w(actor+8,pid%2);c.w(actor+12,mid);c.w(actor+2376,262)
        c.w(actor+0x9E4,30000);c.w(model+4,1);c.w(model+8,1);c.w(model+16,mid)
        c.w(actor+3660,60)
        for off in (2380,2388,2392,2396,2400):c.w(actor+off,0xFFFFFFFF)
    def model_actor(m):
        mid=m.r[4];m.models_requested.append(mid)
        m.r[2]=ACTORS[MIDS.index(mid)] if mid in MIDS else 0
    c.callbacks[0x1DC1A0]=model_actor
    c.callbacks[0x1E0358]=lambda m:m.r.__setitem__(2,m.u(m.r[4]+2376))
    c.callbacks[0x1DC320]=lambda m:m.r.__setitem__(2,int(m.u(m.r[4]+0x9E4)==0))
    c.callbacks[0x1DA4E8]=lambda m:m.events.append(('voice',m.r[4],m.r[5]))
    c.callbacks[0x1DC738]=lambda m:m.events.append(('event',m.r[4],m.r[5]))
    c.callbacks[0x1D8980]=lambda m:m.camera.append((m.r[4],m.r[5]))
    c.callbacks[0x1D8B88]=lambda m:None
    c.callbacks[0x1D8E08]=lambda m:m.set_number(0,0)
    c.callbacks[0x2058E0]=lambda m:(m.models_requested.append(m.r[4]),m.write(m.r[6],bytes(16)))
    c.callbacks[0x122168]=lambda m:None
    c.callbacks[0x1DC380]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[0x1E0430]=lambda m:m.r.__setitem__(2,2)
    c.callbacks[0x211F60]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x211AF0]=lambda m:m.r.__setitem__(2,100)
    def damage(m):m.damage.append((m.r[4],m.r[5],m.r[6]));m.w(m.r[4]+0x9E4,m.u(m.r[4]+0x9E4)-m.r[5])
    c.callbacks[0x1CE630]=damage
    c.callbacks[0x1DAFC0]=lambda m:None
    c.callbacks[0x174CE0]=lambda m:m.effect_cleanup.append(m.r[4])
    c.callbacks[0x174CC0]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x205D08]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x216E20]=lambda m:m.r.__setitem__(2,3)
    c.callbacks[0x12E0E8]=lambda m:m.events.append(('projectile',m.r[4],m.r[5],m.r[6]))
    c.fw(c.r[28]-28468,-1);c.fw(c.r[28]-28464,1)
    return c


def active(c,a,b):
    a,b=sorted((a,b),key=lambda i:i%2)
    c.w(fix.CONTROL+16,1)
    for off,value in ((64,ACTORS[a]),(68,ACTORS[b]),(72,MIDS[a]),(76,MIDS[b]),(80,a),(84,b)):
        c.w(fix.CONTROL+off,value)
    c.w(ACTORS[a]+2376,304);c.w(ACTORS[b]+2376,305)
    c.w(core.TABLE+4*a,b);c.w(core.TABLE+4*b,a)
    return a,b


def flag(c,pid,value):
    return bool(c.read(ACTORS[pid]+0x1085+(value>>3),1)[0] & (1<<(value&7)))
