"""Explicit selected/consumed participation while retaining native parity slots.

Absent reservations are initialized for safe native table traversal, then made
inactive after placement/effect initialization. Their allocations stay owned.
Only this captured world is changed; original leaders can never be removed.
"""
from native_map import CRC, SERIAL
import struct
from prototype import Assembler
import fresh_team_combat as core
import team_start_gate as start
import team_intro as intro
import guest_killfeed as feed
import extra_reload_requests as reloads
from battle_mode_policy import ACTOR_COUNTS
from battle_mode_policy import TEAM_CAPACITY

FRAME, APPLY, CONSUME, TRAMPOLINE = 0x077C0000,0x077C1000,0x077C2000,0x077C3000
CONTROL, ROWS, END = 0x077CF000,0x077CF100,0x077D0000
PRESENT, CONSUMED = CONTROL+12, CONTROL+16
STRIDE=64
SERVICES=(0x0745E000,0x0750F000,0x0754F000,0x07584C00,0x075DF000,0x07703C00)
SAVED=tuple(range(1,29))+(30,31)


def layout(counts):
    if (not isinstance(counts,(list,tuple)) or len(counts)!=2 or
            any(type(n) is not int or not 1<=n<=TEAM_CAPACITY for n in counts)):
        raise ValueError('Select between1 and3 fighters on each team')
    n=2*max(counts)
    mask=sum(1<<(2*slot+side) for side in range(2) for slot in range(counts[side]))
    return n,mask


def target_plan(n,mask):
    if type(n) is not int or type(mask) is not int or n not in ACTOR_COUNTS or mask&3!=3 or mask>>n:raise ValueError('Invalid captured participation mask')
    # Match each roster slot against the same opposing slot. For uneven teams,
    # an absent counterpart falls back to the opposing leader, never a reserve.
    result=[]
    for i in range(n):
        candidates=[j for j in range(n) if (i&1)!=(j&1) and mask&(1<<j)]
        result.append((i^1) if (i^1) in candidates else candidates[0])
    return result


def save(a):
    a.addiu(29,29,-0x100)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)


def restore(a, result=None):
    for i,r in enumerate(SAVED):
        if r!=2 or result is None:a.i(55,r,29,8*i)
    a.addiu(29,29,0x100)
    if result is not None:a.addiu(2,0,result)
    a.jr()


def validate(a, fail):
    core.gate(a,fail);a.li(16,CONTROL);a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,fail)
    a.lw(17,16,8);a.branch(5,17,10,fail)
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,fail)
    a.lw(18,16,12);a.i(12,8,18,3);a.addiu(9,0,3);a.branch(5,8,9,fail)
    a.addiu(8,0,1);a.r(4,8,17,8);a.addiu(8,8,-1);a.r(0x27,9,8,0)
    a.r(0x24,9,9,18);a.branch(5,9,0,fail)
    a.lw(19,16,16);a.r(0x27,8,18,0);a.r(0x24,8,8,19);a.branch(5,8,0,fail)
    a.i(12,8,19,3);a.branch(5,8,0,fail)
    # Living forms may replace model metadata or native selected slots. Only
    # their stable actor/team identity is shared with this participation table.
    a.li(20,ROWS);a.move(21,0)
    a.label('validate_actor');a.lw(22,20)
    a.li(8,core.POINTERS);a.r(0,9,0,21,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,22,fail)
    a.lw(8,22);a.branch(5,8,21,fail);a.lw(8,22,8);a.i(12,9,21,1);a.branch(5,8,9,fail)
    a.addiu(21,21,1);a.addiu(20,20,STRIDE);a.branch(5,21,17,'validate_actor')


def refresh_removed(a,fail):
    # Resolve only a removed/consumed owner's current typed model and HP row.
    # Record refresh is harmless; all removed rows validate before actor edits.
    a.lw(22,20);a.lw(24,22,12);a.i(11,8,24,12);a.branch(4,8,0,fail)
    a.li(8,core.MODELS);a.r(0,9,0,24,2);a.r(0x2D,8,8,9);a.lw(23,8)
    a.i(12,8,23,3);a.branch(5,8,0,fail)
    a.li(8,0x100000);a.r(0x2B,8,23,8);a.branch(5,8,0,fail)
    a.li(8,0x8000000-0x1670);a.r(0x2B,8,8,23);a.branch(5,8,0,fail)
    a.lw(8,23,16);a.branch(5,8,24,fail);a.lw(8,23,4);a.addiu(9,0,1);a.branch(5,8,9,fail)
    a.lw(8,22,0x994);a.lw(9,22,0x998);a.i(11,10,9,6);a.branch(4,10,0,fail)
    a.r(0x2B,10,8,9);a.branch(4,10,0,fail)
    a.sw(8,20,28);a.r(0,9,0,8,7);a.r(0,10,0,8,5);a.r(0x2D,9,9,10)
    a.r(0,10,0,8,2);a.r(0x2D,9,9,10);a.r(0x2D,9,9,22);a.addiu(9,9,0x9A4)
    a.sw(9,20,16);a.sw(23,20,4);a.sw(24,20,8)


def remove(a, tag):
    # s4 row, s5 physical; mark observed BEFORE changing HP, so disappearance
    # never creates a fabricated death or attacker attribution.
    a.li(8,feed.CONTROL);a.lw(9,8,4);a.lw(10,16,4);a.branch(5,9,10,tag+'no_feed')
    a.r(0,9,0,21,2);a.r(0x2D,8,8,9);a.addiu(9,0,1);a.sw(9,8,0x40)
    a.label(tag+'no_feed');a.lw(22,20);a.lw(23,20,4);a.lw(8,20,16);a.sw(0,8,64)
    for off in (0x1278,0x127C,0x1280,0x1284):a.sw(0,22,off)
    for off,value in ((0x948,216),(0x94C,-1),(0x950,216),(0x954,-1),(0x958,-1),(0x95C,-1),(0x960,-1),(0x964,0),(0x968,0)):
        a.addiu(8,0,value);a.sw(8,22,off)
    a.sw(0,23,8)
    # Neither a pending input nor a request may resurrect a removed actor.
    a.addiu(8,21,-2);a.r(0,8,0,8,6);a.li(9,reloads.RECORDS);a.r(0x2D,9,9,8)
    a.addiu(8,0,6);a.sw(8,9,4);a.sw(0,9,52)
    a.li(8,start.CONTROL);a.lw(9,8,8);a.lw(10,16,4);a.branch(5,9,10,tag+'cpu_done')
    a.r(0,9,0,21,2);a.r(0x2D,8,8,9);a.sw(0,8,0x40)
    a.label(tag+'cpu_done')


def apply_code():
    a=Assembler(APPLY);save(a);a.li(8,CONTROL);a.lw(8,8);a.i(11,8,8,100);a.branch(4,8,0,'done')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'done');validate(a,'error')
    for p in SERVICES:
        a.li(8,p);a.lw(9,8);a.addiu(10,0,5);a.branch(5,9,10,'done')
        a.lw(9,8,4);a.lw(10,16,4);a.branch(5,9,10,'done')
    a.addiu(21,0,2);a.li(20,ROWS+2*STRIDE)
    a.label('check_removed');a.addiu(8,0,1);a.r(4,8,21,8);a.r(0x24,9,18,8);a.branch(4,9,0,'check_row')
    a.r(0x24,9,19,8);a.branch(4,9,0,'check_next')
    a.label('check_row');refresh_removed(a,'error')
    a.label('check_next');a.addiu(21,21,1);a.addiu(20,20,STRIDE);a.branch(5,21,17,'check_removed')
    a.addiu(21,0,2);a.li(20,ROWS+2*STRIDE)
    a.label('actor');a.addiu(8,0,1);a.r(4,8,21,8);a.r(0x24,9,18,8);a.branch(4,9,0,'remove')
    a.r(0x24,9,19,8);a.branch(4,9,0,'next')
    a.label('remove');remove(a,'apply_')
    a.label('next');a.addiu(21,21,1);a.addiu(20,20,STRIDE);a.branch(5,21,17,'actor')
    a.r(0x27,8,18,0);a.r(0x25,8,8,19);a.addiu(9,0,1);a.r(4,9,17,9);a.addiu(9,9,-1);a.r(0x24,8,8,9);a.sw(8,16,20)
    a.lw(8,16,24);a.addiu(8,8,1);a.sw(8,16,24);a.addiu(8,0,5);a.sw(8,16);a.jump('done')
    a.label('error');a.li(8,CONTROL);a.addiu(9,0,110);a.sw(9,8)
    a.label('done');restore(a)
    return a.finish()


def consume_code():
    a=Assembler(CONSUME);save(a);validate(a,'reject')
    a.lw(8,16);a.addiu(9,0,5);a.branch(5,8,9,'reject')
    a.i(11,8,4,2);a.branch(5,8,0,'reject');a.r(0x2B,8,4,17);a.branch(4,8,0,'reject')
    a.addiu(8,0,1);a.r(4,8,4,8);a.r(0x24,9,18,8);a.branch(4,9,0,'reject')
    a.r(0x24,9,19,8);a.branch(5,9,0,'reject')
    a.move(21,4);a.r(0,8,0,21,6);a.li(20,ROWS);a.r(0x2D,20,20,8);refresh_removed(a,'reject')
    # An active serial reload owns this actor until its native handshake ends.
    # The fusion admission layer must avoid booking it; CONSUME also refuses
    # to overwrite the worker's generation/status if a caller violates that.
    a.li(8,reloads.CONTROL);a.lw(9,8,4);a.lw(10,16,4);a.branch(5,9,10,'no_reload')
    a.lw(9,8,8);a.branch(5,9,17,'no_reload')
    a.addiu(8,21,-2);a.r(0,8,0,8,6);a.li(9,reloads.RECORDS);a.r(0x2D,9,9,8)
    a.lw(8,9,8);a.branch(5,8,22,'no_reload');a.lw(8,9,4);a.addiu(8,8,-1)
    a.i(11,8,8,4);a.branch(5,8,0,'reject');a.label('no_reload')
    a.lw(8,20,16);a.lw(8,8,64);a.r(0x2A,8,0,8);a.branch(4,8,0,'reject')
    a.addiu(8,0,1);a.r(4,8,21,8);a.r(0x25,19,19,8);a.sw(19,16,16)
    a.lw(9,16,20);a.r(0x25,9,9,8);a.sw(9,16,20);remove(a,'consume_')
    restore(a,1);a.label('reject');restore(a,0);return a.finish()


def frame_code(previous):
    a=Assembler(FRAME);save(a);a.call(APPLY)
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(4,9,10,'chain')
    # Pending/error initialization must never release an exported prearm.
    a.li(8,CONTROL);a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'chain')
    for index,module in enumerate((start,intro)):
        a.li(8,module.CONTROL);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,f'skip{index}')
        a.lw(9,8,8);a.lw(10,28,-22364);a.branch(5,9,10,f'skip{index}');a.sw(0,8,4)
        a.label(f'skip{index}')
    a.label('chain')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.call(previous);a.call(APPLY)
    a.i(55,31,29,(len(SAVED)-1)*8);a.addiu(29,29,0x100);a.jr();return a.finish()


def build_memory(ram,present_mask=None,source='<captured-ready>'):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,n=u(core.ACTORS),u(core.MODE+4)
    mask=(1<<n)-1 if present_mask is None else present_mask
    target_plan(n,mask)
    if u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.MODE+12)!=n or u(manager)!=2:
        raise ValueError('Requires captured active parity slots')
    if any(ram[FRAME:END]):raise ValueError('Participation reservation occupied')
    previous=(u(start.HOOK)&0x3FFFFFF)<<2
    if (u(start.HOOK)>>26!=2 or u(start.HOOK+4) or
            not 0x07000000<=previous<0x08000000 or FRAME<=previous<END or
            not any(ram[previous:previous+8])):
        raise ValueError('Requires an installed captured frame chain')
    records=bytearray(n*STRIDE);actors=[]
    for i in range(n):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<len(ram)-0x1600 or u(actor)!=i or u(actor+8)!=i&1:raise ValueError('Invalid captured actor')
        mid=u(actor+12);model=u(core.MODELS+4*mid) if mid<12 else 0
        if not 0x100000<=model<len(ram)-0x1670 or u(model+16)!=mid or u(model+4)!=1:raise ValueError('Invalid captured model')
        slot=u(actor+0x994);count=u(actor+0x998)
        if not 0<=slot<count<=5:raise ValueError('Invalid selected row')
        selected=actor+0x9A4+164*slot
        struct.pack_into('<8I',records,i*STRIDE,actor,model,mid,i,selected,u(selected+64),i&1,slot)
        actors.append(actor)
    if len(set(actors))!=n:raise ValueError('Aliased reservation actors')
    control=struct.pack('<7I',0,manager,n,mask,0,0,0)+bytes(0x100-28)
    parts=[(FRAME,frame_code(previous)),(APPLY,apply_code()),(CONSUME,consume_code()),
        (CONTROL,control),(ROWS,bytes(records)),(start.HOOK,struct.pack('<2I',(2<<26)|(FRAME>>2),0))]
    spans=sorted((p,p+len(d)) for p,d in parts)
    if any(end>begin for (_,end),(begin,_) in zip(spans,spans[1:])):raise ValueError('Participation code overlaps')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,present_mask=mask,
        consume=CONSUME,previous=previous,actors=actors,
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in parts])
