"""Offline revival transaction, native recovery, isolation and ownership tests."""
import copy
import hashlib
import json
import random
import struct
import unittest
import teammate_revive as r
from revive_native_fixture import fixture as native_fixture,ACTOR,MODEL,dispatch
from prototype import ROOT

MANAGER,BATTLE=0x1800000,0x1801000
TAILS=(0x073A0000,r.fusion.CONTACT,r.feed.DAMAGE,0x073C6400,r.camera.BODY)

def machine(count=6,source=2,corpse=0,cost=4,channel=3,air=False,
            radius=40.,health=20000,recovery=30,ring=False,opacity=58,wave_height=0.,wave_speed=1.):
    c=native_fixture(air,ACTOR+corpse*0x2000,MODEL+corpse*0x2000)
    for p,b in r.program(TAILS):c.write(p,b)
    # The original native request remains behind its owned body continuation.
    c.write(r.camera.BODY,r.NATIVE(0x1E0290,0x18))
    c.write(r.CONTROL,struct.pack('<6I',r.MAGIC,MANAGER,count,r.policy.TEAMS,cost*100000,channel))
    c.w(r.CONTROL+24,r.OPTIONS_VERSION)
    c.write(r.CONTROL+64,struct.pack('<2f4I',radius,radius*radius,health,recovery,int(ring),opacity))
    c.write(r.CONTROL+88,struct.pack('<f2I',wave_height,round(wave_speed*65536/30),0))
    c.write(r.core.MODE,struct.pack('<4I',1,count,MANAGER,count));c.w(r.core.ACTORS,MANAGER);c.w(MANAGER,2)
    c.write(r.part.CONTROL,struct.pack('<5I',5,MANAGER,count,(1<<count)-1,0))
    c.w(0x2FEB38,BATTLE);c.w(BATTLE,3);c.w(0x3337C0,1)
    c.w(r.spectator.CONTROL,r.spectator.MAGIC);c.w(r.spectator.CONTROL+r.spectator.FIELDS['manager'],MANAGER)
    c.w(r.spectator.CONTROL+r.takeover.F['version'],r.takeover.VERSION)
    c.w(r.spectator.CONTROL+r.takeover.F['human_ports'],1)
    c.w(r.spectator.CONTROL+r.takeover.F['owned'],source)
    c.actors=[ACTOR+i*0x2000 for i in range(count)]
    for i,actor in enumerate(c.actors):
        c.w(r.core.POINTERS+4*i,actor);c.w(r.ROWS+r.STRIDE*i,actor)
        model=MODEL+i*0x2000;c.w(r.core.MODELS+4*i,model)
        c.w(actor,i);c.w(actor+8,i&1);c.w(actor+12,i)
        c.w(model+4,1);c.w(model+8,1);c.w(model+16,i)
        c.w(actor+0x948,216 if i==corpse else 11);c.w(actor+0x994,0);c.w(actor+0x998,1)
        c.w(actor+0x9E4,0 if i==corpse else 30000);c.w(actor+0x9E8,30000)
        c.w(actor+0x9F0,123456);c.w(actor+0x9F8,500000)
        c.w(actor+r.spectator.CPU_DRIVEN,int(i!=source))
        for off in (2380,2388,2392,2396,2400):c.w(actor+off,-1)
        c.fw(actor+16,0. if i==corpse else 10. if i==source else 500.+i*100)
        c.fw(actor+20,0.);c.fw(actor+24,0.)
        c.w(r.core.TABLE+4*i,i^1)
    c.source,c.corpse=source,corpse
    c.callbacks[r.fusion.RESERVED]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[TAILS[0]]=lambda m:None
    c.callbacks[TAILS[1]]=lambda m:m.r.__setitem__(2,77)
    c.callbacks[TAILS[2]]=lambda m:m.r.__setitem__(2,55)
    c.callbacks[TAILS[3]]=lambda m:m.r.__setitem__(2,66)
    # Remove proof fixture's native command mock so the new outer guard runs.
    c.callbacks.pop(0x1D4F30,None)
    return c

def tick(c,n=1):
    for _ in range(n):c.r[31]=0xFEED0000;c.run(r.TICK)

def row(c,i):return r.ROWS+i*r.STRIDE
def hp(c,i):return c.u(c.actors[i]+0x9E4)
def stock(c,i):return c.u(c.actors[i]+0x9F8)
