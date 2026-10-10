import support
"""Actual-pair geometry, native contact latches and per-victim projectiles."""
import struct
import unittest
import multi_contact as fix
import counter_beam_fixture as base
import counter_dash_fixture as dash_tests

ACTORS,MIDS,MODELS,MANAGER=base.ACTORS,base.MIDS,base.MODELS,base.MANAGER


def call(c,p,*args):
    for i,value in enumerate(args):c.r[4+i]=value
    c.r[31]=0xFEED0000;c.run(p)
    return c.r[2]


def flag(c,pid,number,value=True):
    for bank in (0x1085,0x10AD):
        p=ACTORS[pid]+bank+(number>>3);current=c.read(p,1)[0];mask=1<<(number&7)
        c.write(p,bytes([(current|mask) if value and bank==0x1085 else current&~mask]))


def machine():
    c=dash_tests.machine();c.instruction_budget=1000000
    for p,n in ((0x1C8F18,0xF8),(0x1C97C0,0x1C8),(0x1C9988,0x1C8),
                (0x1DA9D0,0x2E0),(0x1DB770,0x48),(0x1AF650,0xF0),
                (0x12E718,0x140),(0x1AFE70,0x1C0),(0x2ED838,28)):
        c.write(p,fix.NATIVE(p,n))
    for p,b,_ in fix.core.program():
        if p==0x1DB778:c.write(p,b)
    for p,b in fix.pieces():c.write(p,b)
    # This focused fixture has no installed throw-resource stage. Its retained
    # fallback is the exact core selector; full preset tests verify the chain.
    c.write(fix.dash.RESOLVE,fix.core.rebound(fix.core.resolver_code,RESOLVER=fix.dash.RESOLVE)())
    c.write(fix.CONTROL,struct.pack('<3I',fix.MAGIC,MANAGER,6))
    for i,p in enumerate(ACTORS):
        c.w(fix.CONTROL+0x100+4*i,p);c.w(p+2376,11);c.w(p+0xF40,0xFFFFFFFF)
        c.w(MODELS[i]+5728,0x4800000+i*0x20000)
        c.w(0x4800000+i*0x20000+98336,0x1000000)
    c.callbacks.pop(0x1DB770,None)
    c.callbacks[0x1DC280]=lambda m:m.r.__setitem__(2,MODELS[ACTORS.index(m.r[4])])
    c.callbacks[0x1DB408]=lambda m:m.set_number(0,0)
    c.callbacks[0x20C9F0]=lambda m:m.r.__setitem__(2,11)
    c.callbacks[0x20D970]=lambda m:m.r.__setitem__(2,0)
    for p in (0x1C84A8,0x1C8580,0x1C89C0,0x1C8A10,0x1C8A78):
        c.callbacks[p]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x1C8DB8]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[fix.contact.PROTECTED]=lambda m:m.r.__setitem__(2,0)
    c.fw(c.r[28]-0x7144,180)
    for p in (0x211080,0x2110B0,0x2110F8,0x211128):c.callbacks[p]=lambda m:m.r.__setitem__(2,15)
    return c


def geometry_pairs(c,overlapping=None):
    pairs=[]
    def collide(m):
        left,right=m.u(m.r[4]+16),m.u(m.r[5]+16);pairs.append((left,right))
        if overlapping is None or (MIDS.index(left),MIDS.index(right)) in overlapping:
            m.w(fix.core.MATRIX_ROWS+4*left,m.u(fix.core.MATRIX_ROWS+4*left)|(1<<right));m.r[2]=1
        else:m.r[2]=0
    c.callbacks[0x1AF650]=collide
    return pairs


def projectile_machine(repeating=True,overlaps=(1,3,5),source=0):
    c=machine();record,effect,attack,params,pool=0x5000000,0x5100000,0x5200000,0x5300000,0x5000000
    c.w(record,source);c.w(record+0x60,effect);c.w(record+0x64,attack)
    c.w(attack,source);c.w(attack+4,2);c.w(attack+0x24,params)
    c.write(params+10,bytes((8,3)));c.w(params+0x3C,32)
    c.w(effect+4,0x4000 if repeating else 0);c.w(c.r[28]-0x58C8,pool);c.w(pool+0x6400,1)
    c.shot_hits=[];c.shot_geometry=[];c.w(fix.CONTROL+60,1)
    def shape(m):
        mid=m.u(m.r[4]+16);c.shot_geometry.append(mid);m.r[2]=int(MIDS.index(mid) in overlaps)
    for offset in range(0,28,4):c.callbacks[struct.unpack('<I',fix.NATIVE(0x2ED838+offset,4))[0]]=shape
    for p in (0x1CC820,0x1CCB98,0x1CCE58,0x1CCFE8,0x1CD258,0x12E420):c.callbacks[p]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x12E850]=lambda m:None
    def damage(m):
        pid=MIDS.index(m.r[4]);c.shot_hits.append(pid);m.w(ACTORS[pid]+0x9E4,m.u(ACTORS[pid]+0x9E4)-250);m.r[2]=1
    c.callbacks[0x1CD320]=damage
    c.write(0x1AFDB0,fix.NATIVE(0x1AFDB0,0xC0))
    c.record,c.effect,c.attack,c.params,c.pool=record,effect,attack,params,pool
    return c


def projectile_step(c):
    c.r[16]=c.record;c.r[18]=c.record+0x130;c.r[19]=0;c.r[20]=c.pool;c.r[31]=0xFEED0000
    return c.run(0x1B00C4,(0x1B01FC,))
