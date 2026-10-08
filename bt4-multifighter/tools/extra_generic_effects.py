"""Held native per-model projectile/cosmetic pools and independent trackers.

The native48-byte owner rows and five two-owner trackers are different from
the1344-byte special pools. This module preserves leader allocations, builds
each extra's real ten-kind hierarchy, and retains projectile format checks.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
import numpy as np
import extra_effect_suppression as old
import extra_special_pools as special
import fresh_team_safety as safety
from camera_snapshot import read_ram
from prototype import Assembler,ROOT,elf_reader
from battle_mode_policy import ACTOR_COUNTS

CODE,RESOURCE,LOOKUP,PRED,OLD_PRED=0x075D0000,0x075D4000,0x075D4200,0x075D4400,0x075D4600
FREE,FREE_TAIL,DESTROY,CALLBACKS=0x075D4800,0x075D4A00,0x075D4B00,0x075D4F00
TRACK_WRAPPERS,TRACK_COPIES=0x075D5000,0x075D9000
CONTROL,RECORDS,ROWS,TRACKS,NODES=0x075DF000,0x075DF200,0x075E0000,0x075E0300,0x075E0500
END,GLOBAL,ARENA_BYTES=0x07600000,A(0x2FEA48),0x100000
core=special.core
NATIVE=elf_reader(elf_path(ROOT))[2]


def require(condition,message):
    if not condition:raise ValueError(message)


def save(a):
    a.addiu(29,29,-0x130)
    for i,r in enumerate(special.SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0x100+4*i)


def restore(a):
    for i in range(12):a.i(49,20+i,29,0x100+4*i)
    for i,r in enumerate(special.SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x130)


def owned(a,fallback,extra=False):
    """Leaf predicate using only v0/v1,t0..t2; input a0 is actual model ID."""
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(5,9,10,fallback)
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,fallback)
    a.lw(9,8,28);a.li(10,GLOBAL);a.lw(10,10);a.branch(5,9,10,fallback)
    a.lw(9,9,4);a.li(10,ROWS);a.branch(5,9,10,fallback)
    if extra:a.i(11,9,4,2);a.branch(5,9,0,fallback)
    a.li(9,core.POINTERS);a.lw(10,8,8)
    a.label('scan');a.lw(2,9);a.lw(3,2,12);a.branch(4,3,4,'found')
    a.addiu(9,9,4);a.addiu(10,10,-1);a.branch(5,10,0,'scan');a.jump(fallback)
    a.label('found')


# Guest stack frames are multiples of 16 bytes (LS-2): the BIOS saves a preempted thread with sq (aligned
# down to 16) and sd HI/LO at exact offsets, so with $sp = 8 mod 16 its saved $gp became LO1 on resume.
def resource_code():
    # Only the native pool initializer passes an actual model into12CDE8.
    # All ordinary physical-ID callers retain2053B0's original semantics.
    a=Assembler(RESOURCE);a.addiu(29,29,-32)
    for i,r in enumerate((8,9,10)):a.i(63,r,29,i*8)
    a.li(8,CONTROL);a.lw(9,8,16);a.branch(4,9,0,'native')
    a.lw(9,8,20);a.branch(5,9,4,'native')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'native')
    a.lw(9,8,24);a.lw(2,9,88)
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,32);a.jr()
    a.label('native')
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,32);a.jump(A(0x2053B0))
    return a.finish()


def lookup_code(previous):
    a=Assembler(LOOKUP);a.addiu(29,29,-32)
    for i,r in enumerate((8,9,10)):a.i(63,r,29,i*8)
    owned(a,'native');a.i(11,9,5,10);a.branch(4,9,0,'zero')
    a.r(0,2,0,4,1);a.r(0x21,2,2,4);a.r(0,2,0,2,4)
    a.li(3,ROWS);a.r(0x21,3,3,2);a.r(0,2,0,5,2);a.r(0x21,3,3,2)
    a.lw(2,3,8);a.jump('done');a.label('zero');a.move(2,0)
    a.label('done')
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,32);a.jr()
    a.label('native')
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,32);a.jump(previous)
    return a.finish()


def predicate():
    a=Assembler(PRED);a.addiu(29,29,-32)
    for i,r in enumerate((8,9,10)):a.i(63,r,29,i*8)
    owned(a,'native');a.move(2,0)
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,32);a.jr()
    a.label('native')
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,32);a.jump(OLD_PRED)
    return a.finish()


def tracker_wrapper(index,previous):
    a=Assembler(TRACK_WRAPPERS+index*0x200);a.addiu(29,29,-48)
    for i,r in enumerate((2,3,8,9,10)):a.i(63,r,29,i*8)
    if index%3==2:
        # Native effect objects can outlive the actor manager, generic module
        # and even the tracker module itself. Their own captured clears must
        # never fall through to the native80-byte two-owner table.
        a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(4,9,10,'clear_scope')
        a.addiu(10,0,90);a.branch(5,9,10,'native');a.label('clear_scope')
        a.li(9,A(0x2FEAA8));a.lw(9,9);a.branch(4,9,0,'clear_scan')
        a.lw(10,8,52);a.branch(5,9,10,'native')
        a.label('clear_scan');a.lw(10,8,8);a.addiu(10,10,-2);a.li(9,RECORDS)
        a.label('scan');a.lw(8,9,4);a.branch(4,8,4,'found')
        a.addiu(9,9,64);a.addiu(10,10,-1);a.branch(5,10,0,'scan');a.jump('native')
        a.label('found')
    else:owned(a,'native',extra=True)
    for i,r in enumerate((2,3,8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,48);a.jump(TRACK_COPIES+index*0x100)
    a.label('native')
    for i,r in enumerate((2,3,8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,48);a.jump(previous)
    result=a.finish();assert len(result)<=0x200;return result


def tracker_copy(index,entry):
    # Original branch offsets remain valid: only first nonbranch LW becomes
    # two instructions; all instructions after it move together by4 bytes.
    kind,operation=divmod(index,3)
    # Get exact function through its JR delay slot, excluding alignment padding.
    native=NATIVE(entry,0x48);words=struct.unpack('<18I',native)
    end=next(i+2 for i,w in enumerate(words) if w==0x03E00008)
    reg=(words[0]>>16)&31;assert words[0]>>26==35 and ((words[0]>>21)&31)==28
    a=Assembler(TRACK_COPIES+index*0x100);a.li(reg,TRACKS+kind*96-kind*16)
    for w in words[1:end]:a.emit(w)
    return a.finish()


def destroy_code():
    # Native1ADA80 invokes this callback BEFORE destroying child pools. Drain
    # them here under bump allocator8 so an unrelated heap selector cannot
    # free interior arena pointers; outer1ADA80 then sees childpool0.
    a=Assembler(DESTROY);save(a);a.move(16,4);a.li(8,special.ALLOC_GLOBAL);a.lw(17,8)
    a.lw(18,17,148);a.addiu(8,0,8);a.sw(8,17,148)
    a.lw(4,16,36);a.call(A(0x1AD6A8));a.sw(0,16,36);a.sw(18,17,148)
    # Native172078's owner-row clearing, without resetting leader1's arena8.
    a.i(36,2,16,1);a.r(0,3,0,2,1);a.r(0x21,3,3,2);a.r(0,3,0,3,4)
    a.li(2,ROWS);a.r(0x21,3,3,2)
    for off in range(8,48,4):a.sw(0,3,off)
    restore(a);a.jr();b=a.finish();assert len(b)<CALLBACKS-DESTROY;return b


def free_code():
    a=Assembler(FREE);a.addiu(29,29,-32)
    for i,r in enumerate((8,9,10)):a.i(63,r,29,i*8)
    a.li(8,CONTROL);a.lw(9,8,28);a.li(10,GLOBAL);a.lw(10,10);a.branch(5,9,10,'done')
    a.lw(10,9,4);a.li(8,ROWS);a.branch(5,10,8,'done')
    a.li(8,CONTROL);a.lw(10,8,32);a.sw(10,9,4);a.addiu(10,0,2);a.sw(10,9,8)
    a.addiu(9,0,90);a.sw(9,8);a.sw(0,8,16)
    a.label('done')
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,32);a.jump(FREE_TAIL);return a.finish()


def initialize(previous,actors,mids,models,primary,allocator,rootpool):
    a=Assembler(CODE);save(a);a.li(16,CONTROL);a.lw(8,16);a.branch(5,8,0,'done')
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'error101')
    for p,v in ((core.MODE,1),(core.MODE+4,len(actors)),(core.MODE+12,len(actors)),
                (core.PAIR+4,0),(GLOBAL,primary),(special.ALLOC_GLOBAL,allocator),
                (primary+4,ROWS),(primary+8,2),(rootpool+12,0)):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error101')
    a.li(8,core.MODE+8);a.lw(8,8);a.lw(9,16,4);a.branch(5,8,9,'error101')
    for i,(actor,mid,model) in enumerate(zip(actors,mids,models)):
        for p,v in ((core.POINTERS+4*i,actor),(actor,i),(actor+12,mid),(core.MODELS+4*mid,model),
                    (actor+0x948,11),(actor+0x1278,0),(actor+0x127C,0),(actor+0x1280,0),(actor+0x1284,0)):
            a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error102')
    a.addiu(8,0,1);a.sw(8,16)
    for i in range(len(actors)-2):
        a.li(4,ARENA_BYTES);a.addiu(5,0,32);a.move(6,0);a.addiu(7,0,1);a.call(A(0x2554D8))
        a.branch(4,2,0,'error110');a.li(17,RECORDS+i*64);a.sw(2,17,12)
        a.move(4,2);a.move(5,0);a.li(6,ARENA_BYTES);a.call(A(0x2A9ACC))
    a.li(18,allocator+128)
    for off in (0,4,8,12):a.lw(8,18,off);a.sw(8,16,0x80+off)
    a.li(8,allocator);a.lw(9,8,148);a.sw(9,16,0x90)
    a.li(8,rootpool);a.li(9,NODES);a.sw(9,8,12)
    for i,(mid,model) in enumerate(zip(mids[2:],models[2:])):
        a.li(17,RECORDS+i*64);a.lw(19,17,12)
        a.sw(19,18);a.sw(19,18,4);a.li(8,ARENA_BYTES);a.sw(8,18,8);a.sw(0,18,12)
        a.li(8,mid);a.sw(8,16,20);a.li(8,model);a.sw(8,16,24);a.addiu(8,0,1);a.sw(8,16,16)
        # Native1AD988 preserves a2 as the root initializer's a1 argument.
        a.li(4,rootpool);a.li(5,CALLBACKS);a.li(6,mid);a.call(A(0x1AD7B8))
        a.sw(2,17,16);a.li(8,ROWS+mid*48);a.sw(2,8)
        a.lw(8,18,12);a.sw(8,17,20);a.sw(0,16,16)
        for off in (0,4,8,12):a.lw(8,16,0x80+off);a.sw(8,18,off)
        a.lw(8,16,0x90);a.li(9,allocator);a.sw(8,9,148)
        a.lw(8,17,16);a.branch(4,8,0,'error120')
        a.lw(8,17,20);a.li(9,ARENA_BYTES);a.r(0x2B,9,9,8);a.branch(5,9,0,'error121')
        a.li(8,ROWS+mid*48);a.lw(8,8,4);a.branch(4,8,0,'error122')
        a.lw(8,16,12);a.addiu(8,8,1);a.sw(8,16,12)
    a.li(8,primary);a.addiu(9,0,12);a.sw(9,8,8);a.addiu(8,0,5);a.sw(8,16);a.jump('done')
    for error in (101,102,110,120,121,122):
        a.label(f'error{error}');a.addiu(8,0,error);a.sw(8,16);a.sw(0,16,16);a.jump('done')
    a.label('done');a.li(16,CONTROL);a.lw(8,16);a.addiu(9,0,5);a.branch(4,8,9,'restore')
    a.lw(11,16,4);a.lw(9,28,-22364);a.branch(5,11,9,'restore')
    for name,ctrl in (('start',special.start.CONTROL),('intro',special.intro.CONTROL)):
        a.li(8,ctrl);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,f'skip_{name}')
        a.lw(9,8,8);a.branch(5,9,11,f'skip_{name}');a.sw(0,8,4);a.label(f'skip_{name}')
    a.label('restore');restore(a);a.jump(previous)
    b=a.finish();assert CODE+len(b)<RESOURCE;return b


def build_memory(ram,config=None,source='<offline-held>'):
    require(len(ram)==0x8000000,'Requires128MiB captured RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0];ptr=lambda p,n:0x100000<=p<=len(ram)-n
    manager,count=u(core.ACTORS),u(core.MODE+4)
    require(count in ACTOR_COUNTS and u(core.MODE)==1 and u(core.MODE+8)==manager and
            u(core.MODE+12)==count and not u(core.PAIR+4),'Requires captured four/six world')
    actors=[];mids=[];models=[]
    for i in range(count):
        actor=u(core.POINTERS+4*i);require(ptr(actor,0x1600) and u(actor)==i,'Invalid physical actor')
        mid=u(actor+12);require(mid<12 and mid not in mids,'Invalid model identity');model=u(core.MODELS+mid*4)
        require(ptr(model,0x1670) and u(model+16)==mid,'Invalid model pointer')
        require(u(actor+0x948)==11 and all(u(actor+o)==0 for o in (0x1278,0x127C,0x1280,0x1284)),
                'Generic effect initialization requires held idle actors')
        resource=u(model+88);require(ptr(resource,48) and u(resource)==11,'Missing native generic-effect resource')
        for k in range(1,12):require(ptr(resource+(u(resource+4*k)&~3),16),'Invalid effect resource offset')
        require(ptr(u(model+2340),13*52),'Missing projectile-type metadata')
        actors.append(actor);mids.append(mid);models.append(model)
    require(mids[:2]==[0,1],'Expected original leader model IDs')
    require(not any(ram[CODE:END]),'Generic effect reservation occupied')
    primary=u(GLOBAL);require(ptr(primary,12) and u(primary+8)==2,'Expected native two-owner generic manager')
    row=u(primary+4);root=u(primary);allocator=u(special.ALLOC_GLOBAL)
    require(ptr(row,96) and ptr(root,24) and not u(root+12),'Invalid original generic roots')
    require(ptr(allocator,156) and u(allocator+152)==0x3FE,'Expected native bump allocator registry')
    # Song and voice bytes streaming through the native ADX buffers are data, never cached row pointers.
    streams=special.native_stream_buffers(ram,[(row,row+96),(primary,primary+12),(root,root+24)]+
                                          special.effect_arena_spans(ram,allocator))
    words=np.frombuffer(ram,dtype='<u4')
    refs=set(special.outside((int(i)*4 for i in special.pointer_word_indices(words,row,96)),streams))
    stray=sorted(refs-{primary+4})
    require(refs=={primary+4},'Cached generic row references prevent safe relocation'+
            (f' ({len(stray)} word(s), first {u(stray[0]):#010x} at {stray[0]:#010x})' if stray else ''))
    for mid in range(2):
        rootnode=u(row+48*mid);require(ptr(rootnode,64) and u(rootnode+32)==root and
                u(rootnode+40)==A(0x2C3BC8) and u(rootnode+36)==u(row+48*mid+4),'Invalid original generic hierarchy')
    previous=(u(special.HOOK)&0x3FFFFFF)<<2
    require(u(special.HOOK)>>26==2 and not u(special.HOOK+4) and 0x07000000<=previous<0x08000000,'Expected held frame chain')
    getter=u(A(0x1722C0));require(getter==(2<<26)|(safety.EFFECTS>>2) and not u(A(0x1722C4)),'Changed scoped generic getter')
    expected=safety.effects_code(NATIVE(A(0x1722C0),8));require(ram[safety.EFFECTS:safety.EFFECTS+len(expected)]==expected,'Changed prior generic lookup')
    oldpred=safety.cosmetic_predicate();require(ram[old.PREDICATE:old.PREDICATE+len(oldpred)]==oldpred,'Changed cosmetic predicate')
    for i,(entry,_,_) in enumerate(old.ROWS):
        p=old.WRAPPERS+i*0x100;b=old.wrapper_code(i,NATIVE(entry,8))
        require(u(entry)==(2<<26)|(p>>2) and not u(entry+4) and ram[p:p+len(b)]==b,'Changed cosmetic wrapper')
    require(u(A(0x12CDF4))==(3<<26)|(A(0x2053B0)>>2),'Changed native resource-getter call')
    require(ram[A(0x171F10):A(0x172128)]==NATIVE(A(0x171F10),0x218),'Changed native generic initializer')
    require(ram[A(0x171EA8):A(0x171EB0)]==NATIVE(A(0x171EA8),8),'Changed generic module teardown')
    control=bytearray(0x100)
    tracker=u(A(0x2FEAA8));require(ptr(tracker,80),'Missing native cosmetic tracker')
    for off,v in ((4,manager),(8,count),(28,primary),(32,row),(36,root),(40,allocator),(44,previous),(48,1),(52,tracker)):
        struct.pack_into('<I',control,off,v)
    rows=bytearray(576);rows[:96]=ram[row:row+96];nodes=bytearray((count-2)*64);records=bytearray((count-2)*64)
    for i,(actor,mid,model) in enumerate(zip(actors[2:],mids[2:],models[2:])):
        struct.pack_into('<H',nodes,i*64+2,i+2);struct.pack_into('<I',nodes,i*64+32,root)
        struct.pack_into('<I',nodes,i*64+52,NODES+(i+1)*64 if i<count-3 else 0)
        struct.pack_into('<3I',records,i*64,actor,mid,model)
    pieces=[(CODE,initialize(previous,actors,mids,models,primary,allocator,root)),(RESOURCE,resource_code()),
            (LOOKUP,lookup_code(safety.EFFECTS)),(PRED,predicate()),(OLD_PRED,oldpred),
            (FREE,free_code()),(FREE_TAIL,NATIVE(A(0x171EA8),8)+struct.pack('<2I',(2<<26)|(A(0x171EB0)>>2),0)),
            (DESTROY,destroy_code()),(CALLBACKS,struct.pack('<3I',A(0x1720D0),A(0x171F10),DESTROY)),
            (CONTROL,bytes(control)),(RECORDS,bytes(records)),(ROWS,bytes(rows)),(NODES,bytes(nodes)),
            (A(0x12CDF4),struct.pack('<I',(3<<26)|(RESOURCE>>2))),(A(0x1722C0),struct.pack('<2I',(2<<26)|(LOOKUP>>2),0)),
            (old.PREDICATE,struct.pack('<2I',(2<<26)|(PRED>>2),0)),
            (A(0x171EA8),struct.pack('<2I',(2<<26)|(FREE>>2),0)),(primary+4,struct.pack('<I',ROWS)),
            (special.HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))]
    for index,entry in enumerate(p for triple in old.TRACKERS for p in triple):
        prev=old.WRAPPERS+(6+index)*0x100
        pieces += [(TRACK_WRAPPERS+index*0x200,tracker_wrapper(index,prev)),
                   (TRACK_COPIES+index*0x100,tracker_copy(index,entry)),
                   (entry,struct.pack('<2I',(2<<26)|((TRACK_WRAPPERS+index*0x200)>>2),0))]
    intervals=sorted((p,p+len(d)) for p,d in pieces)
    require(all(end<=b for (_,end),(b,_) in zip(intervals,intervals[1:])),'Generic payload overlap')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                status='HELD GENERIC EFFECT INITIALIZATION; WAIT STATUS5; LIVE VALIDATION REQUIRED',
                previous_frame=previous,actors=actors,model_ids=mids,models=models,primary=primary,rootpool=root,
                allocator=allocator,old_rows=row,version=1,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces],
                limitations=['Native allocator arena-use check is post-init telemetry, not an overflow proof.',
                             'Extra generic arenas retained until checkpoint reset; reload must drain/reinitialize them.',
                             'Projectile family/descriptor compatibility guards deliberately remain.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path);x=p.parse_args()
    x.out.write_text(json.dumps(build_memory(read_ram(x.source),source=x.source),indent=2)+'\n')
