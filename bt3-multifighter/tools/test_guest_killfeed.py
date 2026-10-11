# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
from test_ai_shadow import Mips
import guest_killfeed as k
import guest_healthbars as h
import fresh_team_combat as core
from prototype import ROOT,elf_reader
from native_map import elf_path

GP, MANAGER, CAMERA = 0x304270,0x1900000,0x1950000

ACTORS=[0x2000000+i*0x2000 for i in range(6)]

MODELS=[0x2100000+i*0x2000 for i in range(6)]

MODEL_IDS=[0,1,7,10,4,9]

class CPU(Mips):instruction_budget=500000

def make(count=6,native_damage=False):
    _,_,native=elf_reader(elf_path(ROOT))
    names={0:'GOKU',1:'VEGETA',2:'GOHAN',3:'PICCOLO',4:'BROLY',5:'TRUNKS',77:'GOKU (SUPER SAIYAN)'}
    parts=k.payloads(native)+[(k.NAMES,k.name_data(names)[0])]
    if native_damage:
        parts += [(k.DAMAGE_ENTRY,native(k.DAMAGE_ENTRY,0x510)),(0x1CE1B8,native(0x1CE1B8,0x20)),
                  (0x1CE050,native(0x1CE050,0x20)),(0x1CE030,native(0x1CE030,0x20))]
    c=CPU({'segments':[dict(address=p,data_hex=d.hex()) for p,d in parts]})
    c.r[28]=GP;c.w(core.ACTORS,MANAGER);c.w(MANAGER,2)
    for off,v in ((0,1),(4,count),(8,MANAGER),(12,count)):c.w(core.MODE+off,v)
    for off,v in ((0,1),(4,MANAGER),(8,count),(12,100)):c.w(k.CONTROL+off,v)
    for i,col in enumerate(h.COLORS):c.w(k.CONTROL+0x80+4*i,col&0xFFFFFF)
    c.w(GP-22176,CAMERA)
    for off,v in ((512,0),(516,511),(520,0),(524,447)):c.w(CAMERA+off,v)
    for i,(actor,model,mid) in enumerate(zip(ACTORS,MODELS,MODEL_IDS)):
        c.w(core.POINTERS+4*i,actor);c.w(actor,i);c.w(actor+8,i&1);c.w(actor+12,mid)
        c.w(actor+0x994,0);c.w(actor+0x9A4,i);c.w(actor+0x9E4,100);c.w(actor+0x9E8,100)
        c.w(core.MODELS+4*mid,model);c.w(model+12,i)
    c.packets=[];c.cursor=0x5000000;c.calls=[]
    def begin(c):c.r[2]=c.cursor+16
    def end(c):
        c.packets.append(c.read(c.cursor+16,c.r[4]-c.cursor-16));c.cursor=c.r[4]
        c.r[2]=0xDEAD;c.r[3]=0xBEEF
    def damage(c):
        actor=c.r[4];hp=actor+0x9E4+c.u(actor+0x994)*164
        previous=c.u(hp);new=max(0,previous-c.r[5]);c.w(hp,new);c.r[2]=previous-new
        c.r[3]=0x76543210;c.r[4]=0x12345678
    c.callbacks={0x100878:begin,0x100890:end,0x1CF220:lambda c:c.calls.append('delayed'),
                 h.CODE:lambda c:setattr(c,'world_return',0x24681357) or c.r.__setitem__(2,0x24681357)}
    if native_damage:
        c.callbacks.update({0x1CF0C8:lambda c:c.r.__setitem__(2,0),
          0x1DAC78:lambda c:c.r.__setitem__(2,1),0x12AB38:lambda c:c.r.__setitem__(2,0),
          0x1296B8:lambda c:c.calls.append(('native_stat',c.r[4],c.r[5])),
          0x1DB770:lambda c:c.r.__setitem__(2,0),0x1DAA50:lambda c:c.calls.append('native_deathflag')})
    else:c.callbacks[k.DAMAGE_NATIVE]=damage
    return c

def event(c,index=0):return struct.unpack('<8I',c.read(k.EVENTS+32*index,32))
