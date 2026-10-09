"""Fuse actual teammates through native leader or private extra reloads.

Extras require an attached private form worker. Models/resources remain allocated; owned live effects
are drained, and team_participation records consumption separately from death.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import fresh_team_safety as safety
import extra_special_pools as special
import extra_generic_effects as generic
import extra_charge_aura as ordinary
import extra_extended_auras as extended
import extra_ground_effects as ground
import native_preparation as transport
import extra_reload_requests as requests
import cinematic_contact_guard as contact
import leader_transform_safety as leader_safety
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy

SYNC, ELIGIBILITY, BEGIN, COMMIT = 0x077D0000, 0x077D1000, 0x077D2000, 0x077D3000
CLEANUP, OLD_ELIGIBILITY, OLD_BEGIN = 0x077D5000, 0x077D7000, 0x077D7400
DENIED = 0x077D7800
RESERVED, CONTACT = 0x077D9000, 0x077DA000
EXTRA_COMMIT, EXTRA_ELIGIBILITY, EXTRA_BEGIN, SIDE = 0x077DB000,0x077DD000,0x077DD400,0x077DD800
ADMIT_BEGIN=0x077DDC00
CONTROL, END = 0x077DF000, 0x077E0000
# Zero preserves the historical enabled behavior in existing checkpoints. Only
# new initiation is gated: accepted queues, model commits and timed defusion
# must finish even when the option changes during a fusion.
DISABLED = CONTROL + 32
PART_CONTROL, PART_ROWS, CONSUME = 0x077CF000, 0x077CF100, 0x077C2000
ELIGIBILITY_HOOK, BEGIN_HOOK, COMMIT_HOOK = 0x073E0000, 0x073E0400, A(0x1C29BC)
NATIVE = elf_reader(elf_path(ROOT))[2]
SAVED = tuple(range(1,29))+(30,31)
OFFSETS = {r:i*16 for i,r in enumerate(SAVED)}
FRAME = 0x400
# Only scalar fields consumed by native fusion search/merge are mirrored.
FIELDS = (0,4,8,12,16,20,24,28,32,36,40,44,48,52,64,68,112)


def save(a, after=False):
    if not after:a.addiu(29,29,-FRAME)
    for r in SAVED:
        if after and r==31:continue
        a.i(31,r,29,OFFSETS[r])
    for i in range(32):a.i(57,i,29,0x200+i*4)
    a.emit((17<<26)|(2<<21)|(8<<16)|(31<<11));a.sw(8,29,0x280)


def restore(a, finish=True):
    a.lw(8,29,0x280);a.emit((17<<26)|(6<<21)|(8<<16)|(31<<11))
    for i in range(32):a.i(49,i,29,0x200+i*4)
    for r in SAVED:a.i(30,r,29,OFFSETS[r])
    if finish:a.addiu(29,29,FRAME)


def row_address(a,out,actor,slot,temp):
    a.r(0,temp,0,slot,5);a.r(0x21,out,temp,slot)
    a.r(0,out,0,out,2);a.r(0x21,out,out,temp) # 164*slot
    a.r(0x21,out,out,actor);a.addiu(out,out,0x9A4)


def pointer(a,reg,size,fail,temp=8,test=9):
    a.i(12,test,reg,3);a.branch(5,test,0,fail)
    a.li(temp,0x100000);a.r(0x2B,test,reg,temp);a.branch(5,test,0,fail)
    a.li(temp,0x8000000-size);a.r(0x2B,test,temp,reg);a.branch(5,test,0,fail)


def reserved_code():
    """Leaf actual-actor reservation; all non-result registers/HI/LO unchanged."""
    a=Assembler(RESERVED);a.addiu(29,29,-0xB0)
    regs=(3,8,9,10,11,12,13,14,15,24,25)
    for i,r in enumerate(regs):a.i(31,r,29,i*16)
    a.move(2,0);core.gate(a,'done');a.li(8,CONTROL);a.lw(9,8)
    a.addiu(11,0,1);a.branch(5,9,11,'done');a.lw(9,8,4);a.lw(11,28,-22364)
    a.branch(5,9,11,'done');a.lw(9,8,8);a.branch(5,9,10,'done')
    a.li(8,PART_CONTROL);a.lw(9,8);a.addiu(11,0,5);a.branch(5,9,11,'done')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'done')
    a.lw(24,8,12);a.lw(25,8,16);a.li(12,core.POINTERS+8);a.addiu(13,0,2)
    a.label('scan');a.lw(14,12);a.branch(4,14,4,'found');a.addiu(12,12,4)
    a.addiu(13,13,1);a.branch(5,13,10,'scan');a.jump('done')
    a.label('found');a.addiu(8,0,1);a.r(4,8,13,8);a.r(0x24,9,24,8);a.branch(4,9,0,'done')
    a.r(0x24,9,25,8);a.branch(5,9,0,'done')
    a.i(12,12,13,1)
    a.label('claimant');a.r(0,8,0,12,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(15,9)
    a.branch(4,15,4,'next_claimant')
    a.lw(9,15,4856);a.r(2,8,0,13,1);a.branch(5,8,9,'next_claimant')
    for off in (2376,2380,2388,2392,2396,2400):
        a.lw(8,15,off);a.addiu(8,8,-241);a.i(11,8,8,2);a.branch(5,8,0,'yes')
    a.label('next_claimant');a.addiu(12,12,2);a.r(0x2B,8,12,10);a.branch(5,8,0,'claimant')
    a.jump('done');a.label('yes');a.addiu(2,0,1)
    a.label('done')
    for i,r in enumerate(regs):a.i(30,r,29,i*16)
    a.addiu(29,29,0xB0);a.jr();b=a.finish();assert len(b)<0x1000;return b


def contact_code():
    a=Assembler(CONTACT);save(a);a.call(RESERVED);a.branch(5,2,0,'blocked')
    a.lw(4,29,OFFSETS[5]);a.call(RESERVED);a.branch(5,2,0,'blocked')
    restore(a);a.jump(0x07522C00)
    a.label('blocked');restore(a);a.addiu(2,0,1);a.jr();return a.finish()


def sync_code(quad_support=False):
    """a0 leader; v0=side+1 if scoped, else0. Mirror real bench scalar data."""
    a=Assembler(SYNC);a.addiu(29,29,-0xB0)
    regs=(3,8,9,10,11,12,13,14,15,24,25)
    for i,r in enumerate(regs):a.i(31,r,29,i*16)
    a.move(2,0);a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,'done')
    a.lw(11,8,4);a.lw(9,28,-22364);a.branch(5,9,11,'done')
    a.li(9,core.MODE);a.lw(12,9);a.branch(5,12,10,'done')
    a.lw(12,9,8);a.branch(5,12,11,'done');a.lw(12,9,4)
    a.lw(13,8,8);a.branch(5,12,13,'done');a.lw(13,9,12);a.branch(5,12,13,'done')
    a.li(9,PART_CONTROL);a.lw(13,9);a.addiu(10,0,5);a.branch(5,13,10,'done')
    a.lw(13,9,4);a.branch(5,13,11,'done');a.lw(13,9,8);a.branch(5,13,12,'done')
    a.li(10,core.POINTERS);a.move(14,0)
    a.label('owner_scan');a.lw(11,10);a.branch(4,4,11,'leader')
    a.addiu(10,10,4);a.addiu(14,14,1);a.branch(5,14,12,'owner_scan');a.jump('done')
    a.label('leader');a.lw(11,4);a.branch(4,11,14,'physical_owner')
    # Native CPU decision slices temporarily expose a virtual team ID. Accept
    # only the exact recorded alias; initiation/commit still run unaliased.
    a.li(8,core.PAIR);a.lw(10,8,4);a.addiu(13,0,1);a.branch(5,10,13,'done')
    a.i(12,10,14,1);a.branch(5,11,10,'done');a.r(0,10,0,10,2);a.r(0x21,8,8,10)
    a.lw(10,8,8);a.branch(5,10,4,'done');a.lw(10,8,16);a.branch(5,10,14,'done')
    a.label('physical_owner')
    # Extras may enter only while the private form worker owns this match.
    a.i(11,11,14,2);a.branch(5,11,0,'owner_ready')
    import extra_reload_forms as forms
    for at in (forms.CONTROL, forms.FORM_ENABLE):
        a.li(8,at);a.lw(11,8);a.addiu(10,0,1);a.branch(5,11,10,'done')
    a.label('owner_ready');a.i(12,14,14,1)
    a.lw(11,4,8);a.branch(5,11,14,'done')
    a.lw(11,4,0x994);a.lw(10,4,0x998);a.r(0x2B,10,11,10);a.branch(4,10,0,'done')
    a.lw(24,9,12);a.lw(25,9,16);a.addiu(15,14,2)
    a.label('slot');a.r(0x2B,9,15,12);a.branch(4,9,0,'scoped')
    a.r(2,13,0,15,1);a.lw(9,4,0x998);a.r(0x2B,9,13,9);a.branch(4,9,0,'next')
    a.lw(9,4,0x994);a.branch(4,9,13,'next') # Never mirror over the owner's live row.
    row_address(a,3,4,13,9)
    a.addiu(9,0,1);a.r(4,9,15,9);a.r(0x24,11,24,9);a.branch(4,11,0,'absent')
    a.r(0x24,11,25,9);a.branch(5,11,0,'absent')
    a.r(0,9,0,15,2);a.li(10,core.POINTERS);a.r(0x21,10,10,9);a.lw(10,10)
    a.r(0,9,0,15,6);a.li(11,PART_ROWS);a.r(0x21,11,11,9)
    a.lw(9,11);a.branch(5,9,10,'absent');a.lw(9,10);a.branch(5,9,15,'absent')
    a.lw(9,10,8);a.branch(5,9,14,'absent')
    # The two-player consent controller only owns the native leader pair.
    # An autonomous extra must never silently consume a human teammate.
    a.lw(9,4);a.i(11,9,9,2);a.branch(5,9,0,'extra_human_ok')
    a.lw(9,10,0x1278);a.branch(5,9,0,'extra_human_ok')
    import multiplayer_fusion as multi
    a.li(8,multi.CONTROL);a.lw(9,8);a.li(11,multi.MAGIC);a.branch(5,9,11,'absent')
    a.label('extra_human_ok')
    if quad_support:
        # Never consume another human through the CPU partner path. Co-op's
        # consent controller owns the native leader/first-ally pair; other human
        # seats remain independent until a matching consent path exists.
        import quad_controller as quad
        a.li(8,quad.CONTROL);a.lw(9,8);a.li(11,quad.MAGIC);a.branch(5,9,11,'human_guard_done')
        a.lw(9,10,0x1278);a.branch(5,9,0,'human_guard_done')
        import multiplayer_fusion as multiplayer
        a.li(8,multiplayer.CONTROL);a.lw(9,8);a.li(11,multiplayer.MAGIC)
        a.branch(4,9,11,'human_guard_done')
        a.li(8,policy.CONTROL);a.lw(9,8);a.li(11,policy.MAGIC);a.branch(5,9,11,'absent')
        a.lw(9,8,12);a.addiu(11,0,policy.COOP);a.branch(5,9,11,'absent')
        a.addiu(9,0,2);a.branch(5,15,9,'absent')
        a.label('human_guard_done')
    a.lw(9,10,12);a.i(11,11,9,12);a.branch(4,11,0,'absent')
    a.r(0,9,0,9,2);a.li(11,core.MODELS);a.r(0x21,11,11,9);a.lw(11,11)
    pointer(a,11,0x1670,'absent',8,9)
    a.lw(9,11,4);a.addiu(13,0,1);a.branch(5,9,13,'absent')
    a.lw(9,10,12);a.lw(11,11,16);a.branch(5,9,11,'absent')
    a.lw(13,10,0x994);a.lw(9,10,0x998);a.i(11,11,9,6);a.branch(4,11,0,'absent')
    a.r(0x2B,11,13,9);a.branch(4,11,0,'absent')
    # Pending/active worker transactions and paired moves cannot be consumed.
    a.addiu(8,15,-2);a.r(0,8,0,8,6);a.li(11,requests.RECORDS);a.r(0x21,11,11,8)
    a.lw(8,11,4);a.addiu(8,8,-1);a.i(11,8,8,4);a.branch(5,8,0,'absent')
    for off in (2376,2380,2388,2392,2396,2400):
        a.lw(8,10,off);a.addiu(9,8,-236);a.i(11,9,9,8);a.branch(5,9,0,'absent')
        a.addiu(9,8,-180);a.i(11,9,9,8);a.branch(5,9,0,'absent')
    for off in (3480,3500,3512):
        a.lw(8,10,off);a.branch(5,8,0,'absent')
    row_address(a,11,10,13,9)
    for off in FIELDS:a.lw(9,11,off);a.sw(9,3,off)
    a.jump('next')
    a.label('absent');a.sw(0,3,8);a.sw(0,3,64)
    a.label('next');a.addiu(15,15,2);a.jump('slot')
    a.label('scoped');a.addiu(2,14,1)
    a.label('done')
    for i,r in enumerate(regs):a.i(30,r,29,i*16)
    a.addiu(29,29,0xB0);a.jr();b=a.finish();assert len(b)<0x1000;return b


def eligibility_code():
    a=Assembler(ELIGIBILITY);save(a);a.call(SYNC);a.branch(4,2,0,'old')
    a.li(8,DISABLED);a.lw(8,8);a.branch(5,8,0,'denied')
    restore(a);a.jump(EXTRA_ELIGIBILITY)
    a.label('old');restore(a);a.jump(OLD_ELIGIBILITY)
    a.label('denied');restore(a);a.move(2,0);a.jr()
    return a.finish()


def scoped_entry(entry,base,old,admission=False):
    """A guarded native prologue; an unserviced extra still hits the old veto."""
    a=Assembler(base);save(a);a.call(SYNC);a.branch(4,2,0,'old')
    a.li(8,DISABLED);a.lw(8,8);a.branch(5,8,0,'denied')
    restore(a)
    if admission:a.jump(ADMIT_BEGIN)
    else:
        for word in struct.unpack('<2I',NATIVE(entry,8)):a.emit(word)
        a.jump(entry+8)
    a.label('old');restore(a);a.jump(old)
    # Reuse the saved-frame epilogue: these entries each own only 0x400 bytes.
    a.label('denied');a.jump(DENIED)
    data=a.finish();assert len(data)<=0x400;return data


def denied_code():
    a=Assembler(DENIED);restore(a);a.move(2,0);a.jr();return a.finish()


def side_code():
    # Native eligibility keeps its actual s1 actor; only the unlock-table side
    # argument is mapped. Never alias the actor or its model during a reload.
    a=Assembler(SIDE);save(a);a.move(4,17);a.call(SYNC);a.branch(4,2,0,'old')
    a.addiu(8,2,-1);a.i(31,8,29,OFFSETS[4])
    a.label('old');restore(a);a.jump(A(0x12B4F0));return a.finish()


def begin_code(timed=False):
    a=Assembler(BEGIN);save(a);a.call(SYNC);a.branch(4,2,0,'native')
    a.li(8,DISABLED);a.lw(8,8);a.branch(5,8,0,'denied')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'denied')
    # An actor already promised to another fusion cannot become a survivor.
    a.call(RESERVED);a.branch(5,2,0,'denied')
    # Scripted BEGIN must also have a real eligible living physical partner.
    # Cost/ordinary unlock checks remain the caller's responsibility, as native.
    a.move(6,0);a.move(7,0);a.addiu(8,29,0x300);a.call(EXTRA_ELIGIBILITY)
    a.branch(4,2,0,'denied');a.lw(9,29,0x300)
    a.lw(8,29,OFFSETS[6]);a.branch(1,8,0,'reserved_partner');a.branch(5,8,9,'denied')
    a.label('reserved_partner')
    # Eligibility mirrors roster values, but reservations are actual actors.
    # Validate immediately before BEGIN so concurrent requests cannot consume
    # the same teammate or consume one another.
    a.lw(8,29,OFFSETS[4]);a.lw(8,8);a.i(12,8,8,1)
    a.r(0,9,0,9,1);a.r(0x21,9,9,8);a.r(0,9,0,9,2)
    a.li(8,core.POINTERS);a.r(0x21,8,8,9);a.lw(4,8)
    a.call(RESERVED);a.branch(5,2,0,'denied')
    # A timed-fusion receipt must precede the resource reload. Native BEGIN
    # only queues the accepted variant; the merge/commit callback is too late
    # to recover the original leader's form and resource identity.
    a.label('native')
    if timed:
        a.lw(8,29,OFFSETS[4]);a.sw(8,29,0x310)
        restore(a,False);a.call(EXTRA_BEGIN);save(a,True)
        a.branch(4,2,0,'begin_done');a.li(8,0x070DF000);a.lw(9,8);a.li(10,0x46555331)
        a.branch(5,9,10,'begin_done');a.lw(4,29,0x310);a.call(0x070D0000)
        a.label('begin_done');restore(a);a.jr()
    else:restore(a);a.jump(EXTRA_BEGIN)
    a.label('denied');restore(a);a.move(2,0);a.jr();b=a.finish();assert len(b)<0x1000;return b


def commit_code(timed=False,extra=False):
    a=Assembler(EXTRA_COMMIT if extra else COMMIT);save(a);a.sw(0,29,0x300);a.lw(9,4,2376)
    a.addiu(9,9,-241);a.i(11,9,9,2);a.branch(4,9,0,'native')
    a.call(SYNC);a.branch(4,2,0,'native');a.addiu(8,2,-1)
    # leader+4856 is the partner's native roster slot: 1..capacity-1 is a
    # teammate this build places (three-a-side builds stop at slot 2).
    a.lw(10,4,4856);a.addiu(9,10,-1);a.i(11,9,9,policy.emitted_capacity()-1);a.branch(4,9,0,'native')
    a.r(0,9,0,10,1);a.r(0x21,9,9,8);a.li(11,CONTROL);a.lw(11,11,8)
    a.r(0x2B,11,9,11);a.branch(4,11,0,'native')
    a.li(11,PART_CONTROL);a.lw(12,11,12);a.addiu(13,0,1);a.r(4,13,9,13)
    a.r(0x24,12,12,13);a.branch(4,12,0,'native');a.lw(12,11,16)
    a.r(0x24,12,12,13);a.branch(5,12,0,'native')
    row_address(a,11,4,10,12);a.sw(11,29,0x304);a.sw(9,29,0x300)
    a.lw(12,4,4816);a.sw(12,29,0x308);a.sw(4,29,0x30C)
    a.label('native');restore(a,False);a.call(0x07623200 if extra else A(0x1C0538));save(a,True)
    a.lw(16,29,0x300);a.branch(4,16,0,'done');a.lw(17,29,0x304)
    a.lw(8,17,8);a.branch(5,8,0,'done');a.lw(8,17,64);a.branch(5,8,0,'done')
    a.lw(18,29,0x30C);a.lw(9,18,0x994);row_address(a,10,18,9,8)
    a.lw(8,10);a.lw(9,29,0x308);a.branch(5,8,9,'done')
    a.r(0,8,0,16,6);a.li(19,PART_ROWS);a.r(0x21,19,19,8)
    a.lw(8,19);a.lw(4,8,12);a.call(CLEANUP);a.branch(4,2,0,'failed')
    a.move(4,16);a.call(CONSUME);a.branch(4,2,0,'failed')
    a.li(8,CONTROL);a.lw(9,8,16);a.addiu(9,9,1);a.sw(9,8,16);a.sw(16,8,20)
    a.sw(18,8,24)
    if timed:
        a.li(8,0x070DF000);a.lw(9,8);a.li(10,0x46555331);a.branch(5,9,10,'done')
        a.move(4,18);a.move(5,16);a.call(0x070D2000)
    a.jump('done')
    a.label('failed');a.li(8,CONTROL);a.addiu(9,0,110);a.sw(9,8,28)
    # Never release combat after a partially committed owned cleanup failure.
    a.li(8,transport.CONTROL);a.lw(9,8);a.li(10,transport.MAGIC)
    a.branch(5,9,10,'done');a.lw(9,28,-22364);a.sw(9,8,24);a.addiu(9,0,1);a.sw(9,8,16)
    a.label('done');restore(a);a.jr();b=a.finish();assert len(b)<0x2000;return b


def cleanup_code():
    """a0 actual model. Drain only that captured extra's live effect objects."""
    a=Assembler(CLEANUP);save(a);a.move(16,4);a.sw(0,29,0x300)
    a.li(17,CONTROL);a.lw(18,17,4)
    for control in (ordinary.CONTROL,extended.CONTROL,generic.CONTROL,ground.CONTROL,special.CONTROL):
        a.li(8,control);a.lw(9,8);a.addiu(10,0,5);a.branch(5,9,10,'done')
        a.lw(9,8,4);a.branch(5,9,18,'done')
    a.li(8,special.ALLOC_GLOBAL);a.lw(20,8)
    a.lw(9,20,152);a.i(12,9,9,576);a.addiu(10,0,576);a.branch(5,9,10,'done')
    # The native leader's generic/special roots are never selected here.
    for global_,table in ((special.GLOBAL,special.ROWS),(generic.GLOBAL,generic.ROWS)):
        a.li(8,global_);a.lw(8,8);a.branch(4,8,0,'done');a.lw(9,8,4)
        a.li(10,table);a.branch(5,9,10,'done')
    # Resolve the current actual extra, never a native leader or foreign model.
    a.li(21,PART_ROWS+128);a.addiu(19,0,2);a.lw(24,17,8)
    a.label('find_owner');a.lw(22,21);a.lw(9,22,12);a.branch(4,9,16,'owner')
    a.addiu(21,21,64);a.addiu(19,19,1);a.branch(5,19,24,'find_owner');a.jump('done')
    a.label('owner');a.r(0,8,0,16,2);a.li(9,core.MODELS);a.r(0x21,9,9,8);a.lw(23,9)
    pointer(a,23,0x1670,'done');a.lw(8,23,16);a.branch(5,8,16,'done')
    # Validate ALL potentially drained roots before calling any destructor.
    for module,off in ((generic,0),(special,1324)):
        a.addiu(8,19,-2);a.r(0,8,0,8,6);a.li(21,module.RECORDS);a.r(0x21,21,21,8)
        for at,reg in ((0,22),(4,16),(8,23)):
            a.lw(8,21,at);a.branch(5,8,reg,'done')
        a.lw(8,21,12);pointer(a,8,module.ARENA_BYTES,'done',9,10)
        a.li(8,module.GLOBAL);a.lw(8,8);a.lw(24,8);pointer(a,24,24,'done')
        a.lw(25,21,16);pointer(a,25,64,'done');a.lw(8,25,32);a.branch(5,8,24,'done')
        a.lw(8,25,40);a.li(9,module.CALLBACKS);a.branch(5,8,9,'done')
        scale=48 if module is generic else 1344
        if scale==48:
            a.r(0,8,0,16,1);a.r(0x21,8,8,16);a.r(0,8,0,8,4)
        else:
            a.r(0,8,0,16,2);a.r(0x21,8,8,16);a.r(0,8,0,8,2);a.r(0x21,8,8,16);a.r(0,8,0,8,6)
        a.li(9,module.ROWS);a.r(0x21,8,8,9);a.lw(8,8,off);a.branch(5,8,25,'done')
    for i,(glob,poolglob,table,tableoff,body_size,owner,callback) in enumerate([
        (ordinary.GLOBAL,ordinary.POOL_GLOBAL,ordinary.TABLE,1168,0x510,100,A(0x2C3A48))]+[
        (f['global_'],f['poolglobal'],f['table'],f['tableoff'],f['body'],f['owner'],f['child']) for f in extended.FAMILIES]):
        a.li(8,glob);a.lw(21,8);pointer(a,21,tableoff+4,'done');a.lw(8,21,tableoff)
        a.li(9,table);a.branch(5,8,9,'done');a.r(0,8,0,16,2);a.r(0x21,8,8,9);a.lw(24,8)
        a.branch(4,24,0,f'previsual{i}');pointer(a,24,64,'done')
        a.li(8,poolglob);a.lw(8,8);a.lw(9,24,32);a.branch(5,8,9,'done')
        a.lw(8,24,36);a.branch(5,8,0,'done');a.lw(8,24,40);a.li(9,callback);a.branch(5,8,9,'done')
        a.lw(25,24,56);pointer(a,25,body_size,'done');a.lw(8,25,owner);a.branch(5,8,16,'done')
        a.label(f'previsual{i}')
    a.move(4,16);a.call(ground.CLEANUP)
    specs=[(ordinary.GLOBAL,1168,100,False)]
    specs += [(f['global_'],f['tableoff'],f['owner'],f['name']=='giant') for f in extended.FAMILIES]
    for i,(global_,offset,owner,giant) in enumerate(specs):
        a.li(8,global_);a.lw(8,8);a.lw(8,8,offset);a.r(0,9,0,16,2)
        a.r(0x21,21,8,9);a.lw(22,21);a.branch(4,22,0,f'visual{i}')
        a.lw(23,22,56);a.lw(9,23,owner);a.branch(5,9,16,'done')
        if giant:
            for group in range(10):a.addiu(4,23,16+group*144);a.call(A(0x165820))
        a.move(4,22);a.call(A(0x1ADA80));a.lw(9,21);a.branch(5,9,0,'done')
        a.label(f'visual{i}')
    # Generic custom callback selects allocator8 while draining its children.
    a.r(0,8,0,16,1);a.r(0x21,8,8,16);a.r(0,8,0,8,4)
    a.li(21,generic.ROWS);a.r(0x21,21,21,8);a.lw(4,21)
    a.branch(4,4,0,'generic_done');a.call(A(0x1ADA80));a.sw(0,21);a.sw(0,21,4)
    a.label('generic_done')
    for off in range(0,156,4):a.lw(8,20,off);a.sw(8,29,0x310+off)
    a.addiu(8,0,5);a.sw(8,20,148)
    # 1344 = (model*21)*64.
    a.r(0,8,0,16,2);a.r(0x21,8,8,16);a.r(0,8,0,8,2);a.r(0x21,8,8,16);a.r(0,8,0,8,6)
    a.li(21,special.ROWS);a.r(0x21,21,21,8);a.lw(4,21,1324)
    a.branch(4,4,0,'special_done');a.call(A(0x1ADA80));a.sw(0,21,1324)
    a.label('special_done')
    for off in range(0,156,4):a.lw(8,29,0x310+off);a.sw(8,20,off)
    a.addiu(8,0,1);a.sw(8,29,0x300)
    a.label('done');a.lw(8,29,0x300);a.i(31,8,29,OFFSETS[2]);restore(a);a.jr()
    b=a.finish();assert len(b)<0x2000;return b


def pieces():
    import extra_reload_forms as forms
    return [(SYNC,sync_code()),(ELIGIBILITY,eligibility_code()),(BEGIN,begin_code()),
            (COMMIT,commit_code()),(CLEANUP,cleanup_code()),(RESERVED,reserved_code()),(CONTACT,contact_code()),
            (EXTRA_COMMIT,commit_code(True,True)),
            (EXTRA_ELIGIBILITY,scoped_entry(A(0x203788),EXTRA_ELIGIBILITY,OLD_ELIGIBILITY)),
            (EXTRA_BEGIN,scoped_entry(A(0x2039B0),EXTRA_BEGIN,OLD_BEGIN,True)),
            (ADMIT_BEGIN,forms.admission(A(0x2039B0),ADMIT_BEGIN,OLD_BEGIN)),(SIDE,side_code()),
            (OLD_ELIGIBILITY,safety.owned_code(A(0x203788),OLD_ELIGIBILITY,2,NATIVE(A(0x203788),8))),
            (OLD_BEGIN,safety.owned_code(A(0x2039B0),OLD_BEGIN,2,NATIVE(A(0x2039B0),8))),
            (DENIED,denied_code())]


def build_memory(ram,config=None,source='<offline-prepared>',*,allow_human_partner=False,human_mask=0,enabled=True):
    import team_participation as participation
    import team_start_gate as start
    require=lambda ok,text:None if ok else (_ for _ in ()).throw(ValueError(text))
    require(len(ram)==0x8000000,'Requires128MiB EE RAM')
    require(type(enabled) is bool,'Fusion enabled must be Boolean')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    require(count in ACTOR_COUNTS and (u(core.MODE),u(core.MODE+8),u(core.MODE+12))==(1,manager,count),
            'Requires captured four/six-slot team')
    require((participation.CONTROL,participation.ROWS,participation.CONSUME)==(PART_CONTROL,PART_ROWS,CONSUME),
            'Participation ABI changed')
    require((u(PART_CONTROL+4),u(PART_CONTROL+8))==(manager,count) and u(PART_CONTROL) in (0,5),
            'Install participation before fusion support')
    for i in range(2,count):
        if u(PART_CONTROL+12)&(1<<i):
            cpu=u(start.CONTROL+0x40+4*i)
            require(cpu==1 or (cpu==0 and ((allow_human_partner and i==2) or human_mask&(1<<i))),
                    'Fusion may consume only an NPC extra or the declared cooperative human partner')
    require(not any(ram[SYNC:END]),'Fusion reservation occupied')
    for entry,hook in ((A(0x203788),ELIGIBILITY_HOOK),(A(0x2039B0),BEGIN_HOOK)):
        expected=safety.owned_code(entry,hook,2,NATIVE(entry,8))
        require(ram[hook:hook+len(expected)]==expected,f'Prior extra fusion guard changed:{hook:08X}')
    require(ram[COMMIT_HOOK:COMMIT_HOOK+8]==NATIVE(COMMIT_HOOK,8),'Native leader refresh tail changed')
    require(u(COMMIT_HOOK)==(2<<26)|(A(0x1C0538)>>2),'Unexpected native refresh destination')
    for p,size in ((A(0x1C0538),0x570),(A(0x203790),0x170),(A(0x2039B8),0x160)):
        require(ram[p:p+size]==NATIVE(p,size),f'Native fusion body changed:{p:08X}')
    for p,data in ((generic.DESTROY,generic.destroy_code()),(ground.CLEANUP,ground.cleanup())):
        require(ram[p:p+len(data)]==data,'Owned effect cleanup dependency changed')
    import special_pause as pause
    require(ram[contact.PROTECTED:contact.PROTECTED+8]==struct.pack('<2I',(2<<26)|(pause.CONTACT>>2),0),'Install special pause before fusion contact reservation')
    require(ram[pause.CONTACT:pause.CONTACT+len(pause.contact_code())]==pause.contact_code(),'Changed prior pause contact policy')
    blocks=pieces()+[(CONTROL,struct.pack('<9I',1,manager,count,1,0,0,0,0,int(not enabled)))]
    blocks += [(ELIGIBILITY_HOOK,struct.pack('<2I',(2<<26)|(ELIGIBILITY>>2),0)),
               (A(0x203830),struct.pack('<I',(3<<26)|(SIDE>>2))),
               (BEGIN_HOOK,struct.pack('<2I',(2<<26)|(BEGIN>>2),0)),
               (contact.PROTECTED,struct.pack('<2I',(2<<26)|(CONTACT>>2),0)),
               (COMMIT_HOOK,struct.pack('<I',(2<<26)|(COMMIT>>2)))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in blocks],
                limitations=['Extra initiation requires the active private form-reload worker; native tag guards remain.',
                    'Consumed partner retains backing allocations and actual model identity for safe lifecycle teardown.',
                    'Requires participation consumption and fully initialized owned effect families before a fusion.'])


def settings_plan(ram,enabled,source='<fusion-settings>'):
    """Change only future fusion admission, retaining active receipts/owners.

    Reject old code rather than silently writing a setting it cannot honor.
    Check the scoped runtime identity, so native matches remain untouched.
    """
    if type(enabled) is not bool:raise ValueError('Fusion enabled must be Boolean')
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Fusion settings require an active prepared match')
    if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(1,manager,count):
        raise ValueError('Fusion settings owner changed')
    code=eligibility_code()
    if ram[ELIGIBILITY:ELIGIBILITY+len(code)]!=code:
        raise ValueError('Fusion option requires the current admission guards')
    if u(DISABLED) not in (0,1):raise ValueError('Invalid fusion option state')
    data=struct.pack('<I',int(not enabled))
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                blocks=[dict(address=DISABLED,expected_hex=ram[DISABLED:DISABLED+4].hex(),data_hex=data.hex())])


def validate_contact_memory(ram,manager,count):
    """Strict optional-chain validator for pause mode/preset updates."""
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(1,manager,count):
        raise ValueError('Fusion contact owner changed')
    import fusion_duration
    for p,data in pieces():
        import four_player_mode
        data=four_player_mode.dependency_override(ram,p,data)
        data=fusion_duration.dependency_override(ram,p,data)
        if ram[p:p+len(data)]!=data:raise ValueError(f'Fusion dependency changed:{p:08X}')
    hooks=((ELIGIBILITY_HOOK,ELIGIBILITY,8),(BEGIN_HOOK,BEGIN,8),
           (COMMIT_HOOK,COMMIT,4),(contact.PROTECTED,CONTACT,8))
    for hook,destination,size in hooks:
        expected=struct.pack('<I',(2<<26)|(destination>>2))+bytes(4)
        import multiplayer_fusion
        expected=multiplayer_fusion.dependency_override(ram,hook,expected[:size])
        if ram[hook:hook+size]!=expected[:size]:raise ValueError('Fusion hook chain changed')
    if ram[COMMIT_HOOK+4:COMMIT_HOOK+8]!=NATIVE(COMMIT_HOOK+4,4):raise ValueError('Fusion native tail delay changed')
    if u(A(0x203830))!=(3<<26)|(SIDE>>2):raise ValueError('Fusion side unlock hook changed')
    if (u(PART_CONTROL+4),u(PART_CONTROL+8))!=(manager,count):raise ValueError('Fusion participation owner changed')
    return True
