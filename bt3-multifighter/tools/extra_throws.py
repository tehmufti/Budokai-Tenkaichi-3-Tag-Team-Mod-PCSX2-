"""Bind confirmed native throws to their actual participants in captured teams.

This enables commands92/94 only with authored attacker animations and a valid
victim scratch buffer. The native hit/reaction, animation and damage code stays.
No clash, rush, resource reload or cinematic admission entry is relaxed.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import cinematic_contact_guard as contact
import leader_transform_safety as leader
import cinematic_camera_state as camera
import battle_mode_policy as policy
from battle_mode_policy import ACTOR_COUNTS

CODE=0x07780000
VALID=CODE; LOOKUP=CODE+0x1000; CAPTURE=CODE+0x2000
COMMAND=CODE+0x3000; RESOLVE=CODE+0x4000; OLD_RESOLVE=CODE+0x4400
CONTACT=CODE+0x5000; OLD_CONTACT=CODE+0x5800
OLD_COMMAND=CODE+0x6800
PARTICIPANT=CODE+0x7000; OLD_PARTICIPANT=CODE+0x7400
CAMERA_NATIVE=CODE+0x7800
PAIRED_LOOKUP=CODE+0x8000
CONTROL=CODE+0xF000; ROWS=CODE+0xF100; END=CODE+0x10000
CAPTURE_HOOK=A(0x1C9F14)
HOOKS=((CAPTURE_HOOK,CAPTURE),(contact.THROW,COMMAND),(core.RESOLVER,RESOLVE),
       (leader.FALLBACK,CONTACT),(camera.PARTICIPANT,PARTICIPANT))
SAVED=tuple(range(2,16))+(24,25,31)
NATIVE=elf_reader(elf_path(ROOT))[2]
ACTION_FIELDS=(2376,2380,2388,2392,2396,2400)


def save(a):
    a.addiu(29,29,-0x90)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)


def restore(a, results=False):
    for i,r in enumerate(SAVED):
        if not results or r not in (2,3):a.i(55,r,29,i*8)
    a.addiu(29,29,0x90)


def gate(a,fail):
    core.gate(a,fail)
    a.li(8,CONTROL);a.lw(9,8);a.branch(4,9,0,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail)


def scan(a,actor,result,label,fail):
    a.li(8,core.POINTERS);a.move(result,0)
    a.label(label);a.lw(9,8);a.branch(4,9,actor,label+'found')
    a.addiu(result,result,1);a.addiu(8,8,4);a.branch(5,result,13,label)
    a.jump(fail);a.label(label+'found')


def hp(a,actor,fail):
    a.lw(8,actor,0x994);a.i(11,9,8,5);a.branch(4,9,0,fail)
    a.r(0,9,0,8,7);a.r(0,10,0,8,5);a.r(0x2D,9,9,10)
    a.r(0,10,0,8,2);a.r(0x2D,9,9,10);a.r(0x2D,9,9,actor)
    a.lw(8,9,0x9E4);a.branch(6,8,0,fail)


def ptr(a,reg,size,fail):
    a.li(8,0x100000);a.r(0x2B,9,reg,8);a.branch(5,9,0,fail)
    a.li(8,0x08000000-size+1);a.r(0x2B,9,reg,8);a.branch(4,9,0,fail)


def model(a,actor,out,fail):
    a.lw(10,actor,12);a.i(11,9,10,12);a.branch(4,9,0,fail)
    a.r(0,8,0,10,2);a.li(9,core.MODELS);a.r(0x2D,8,8,9);a.lw(out,8)
    ptr(a,out,0x1670,fail);a.lw(9,out,16);a.branch(5,9,10,fail)
    a.lw(9,out,4);a.addiu(8,0,1);a.branch(5,9,8,fail)


def valid_code():
    # a0/1 actual pointers, a2 attacker animation base148 or390.
    # v0 boolean, t6/t7 physical source/target IDs on success. No calls.
    a=Assembler(VALID);gate(a,'no');a.move(13,10)
    scan(a,4,14,'src','no');scan(a,5,15,'dst','no')
    policy.emit_enemy(a,14,15,'no','throw_valid')
    hp(a,4,'no');hp(a,5,'no')
    model(a,4,11,'no');model(a,5,12,'no')
    a.lw(12,12,0x1660);ptr(a,12,0xC000,'no')
    a.r(0,8,0,6,2);a.r(0x2D,11,11,8)
    for off in range(192,212,4):
        a.lw(12,11,off);ptr(a,12,8,'no')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr()
    b=a.finish();assert len(b)<=0x1000;return b


def lookup_code():
    # A record is reciprocal and lasts while either participant still has a
    # native throw action current/requested/queued. Previous action is excluded.
    a=Assembler(LOOKUP);gate(a,'no');a.move(13,10)
    scan(a,4,14,'src','no');a.li(8,ROWS);a.r(0,9,0,14,2);a.r(0x2D,8,8,9)
    a.lw(15,8);a.branch(4,15,0,'no');a.addiu(15,15,-1)
    a.r(0x2B,9,15,13);a.branch(4,9,0,'no')
    policy.emit_enemy(a,14,15,'no','throw_lookup')
    a.li(8,ROWS);a.r(0,9,0,15,2);a.r(0x2D,8,8,9)
    a.lw(9,8);a.addiu(10,14,1);a.branch(5,9,10,'no')
    a.li(8,core.POINTERS);a.r(0,9,0,15,2);a.r(0x2D,8,8,9);a.lw(12,8)
    a.branch(4,12,0,'no')
    for actor in (4,12):
        for off in ACTION_FIELDS:
            a.lw(8,actor,off);a.addiu(9,8,-180);a.i(11,9,9,8)
            a.branch(5,9,0,'yes')
    # Both native actions have finished, so the record must not reserve an
    # unrelated subsequent animation. Current targets remain the last pair.
    for idx in (14,15):
        a.li(8,ROWS);a.r(0,9,0,idx,2);a.r(0x2D,8,8,9);a.sw(0,8)
    a.li(8,CONTROL);a.lw(9,8,20);a.addiu(9,9,1);a.sw(9,8,20)
    a.jump('no');a.label('yes');a.move(2,12);a.move(3,15);a.jr()
    a.label('no');a.move(2,0);a.move(3,0);a.jr()
    b=a.finish();assert len(b)<=0x1000;return b


def capture_code():
    a=Assembler(CAPTURE);save(a);gate(a,'native')
    a.addiu(8,0,20);a.branch(4,16,8,'normal')
    a.addiu(8,0,22);a.branch(5,16,8,'native')
    a.addiu(6,0,390);a.jump('validate');a.label('normal');a.addiu(6,0,148)
    a.label('validate');a.move(4,17);a.move(5,18);a.call(VALID)
    a.branch(4,2,0,'deny')
    # Validate neither actor belongs to a different live throw. Saving the
    # physical IDs avoids recomputing them after the lookup scratch registers.
    a.sw(14,29,0x88);a.sw(15,29,0x8C)
    a.move(4,17);a.call(LOOKUP);a.branch(4,2,0,'defender')
    a.branch(5,2,18,'deny');a.label('defender')
    a.move(4,18);a.call(LOOKUP);a.branch(4,2,0,'bind')
    a.branch(5,2,17,'deny');a.label('bind')
    a.lw(14,29,0x88);a.lw(15,29,0x8C)
    for index,partner in ((14,15),(15,14)):
        a.r(0,9,0,index,2);a.li(8,ROWS);a.r(0x2D,8,8,9)
        a.addiu(10,partner,1);a.sw(10,8)
        a.li(8,core.TABLE);a.r(0x2D,8,8,9);a.sw(partner,8)
    a.li(8,CONTROL);a.lw(9,8,16);a.addiu(9,9,1);a.sw(9,8,16)
    a.sw(14,8,32);a.sw(15,8,36);a.jump('native')
    a.label('deny');a.li(8,CONTROL);a.lw(9,8,24);a.addiu(9,9,1);a.sw(9,8,24)
    restore(a);a.jump(A(0x1C9E58))  # Native failed-grab flag and full caller epilogue.
    a.label('native');restore(a)
    # Replay the overwritten addiu/branch and its preserved native store slot.
    a.addiu(2,0,2);a.sw(16,18,4016);a.branch(5,16,2,'accepted')
    a.jump(A(0x1C9FF0));a.label('accepted');a.jump(A(0x1C9F20))
    b=a.finish();assert len(b)<=0x1000;return b


def command_code():
    a=Assembler(COMMAND);a.addiu(8,0,92);a.branch(4,5,8,'normal')
    a.addiu(8,0,94);a.branch(5,5,8,'allow')
    a.addiu(6,0,390);a.jump('check');a.label('normal');a.addiu(6,0,148)
    a.label('check');save(a);gate(a,'old');a.move(13,10)
    scan(a,4,14,'src','old');a.li(8,core.TABLE);a.r(0,9,0,14,2);a.r(0x2D,8,8,9)
    a.lw(15,8);a.r(0x2B,9,15,13);a.branch(4,9,0,'blocked')
    # Original0<->1 flags retain their complete original behavior.
    a.i(11,9,14,2);a.branch(4,9,0,'extra');a.i(14,9,14,1)
    a.branch(4,9,15,'okay');a.label('extra')
    a.li(8,core.POINTERS);a.r(0,9,0,15,2);a.r(0x2D,8,8,9);a.lw(5,8)
    a.call(VALID);a.branch(4,2,0,'blocked')
    # Conservative admission: new extra pairs do not compete with an active
    # throw, transformation, rush or cinematic. This does not modify admission.
    a.li(12,core.POINTERS);a.move(14,0)
    a.label('others');a.lw(11,12)
    for off in ACTION_FIELDS:
        a.lw(8,11,off)
        for start,span in ((183,5),(236,80)):
            a.addiu(9,8,-start);a.i(11,9,9,span);a.branch(5,9,0,'blocked')
    a.addiu(12,12,4);a.addiu(14,14,1);a.branch(5,14,13,'others')
    a.lw(11,28,-22180);a.branch(4,11,0,'okay')
    a.lw(8,11,812);a.branch(5,8,0,'blocked')
    a.lw(8,11,704);a.branch(4,8,0,'okay')
    a.lw(8,11,776);a.i(12,8,8,3);a.addiu(9,0,1);a.branch(4,8,9,'blocked')
    a.label('okay');restore(a);a.jump('allow')
    a.label('blocked');restore(a);a.addiu(2,0,1);a.jr()
    a.label('old');restore(a);a.jump(OLD_COMMAND)
    a.label('allow');a.move(2,0);a.jr()
    b=a.finish();assert len(b)<=0x1000;return b


def resolve_code():
    a=Assembler(RESOLVE);save(a)
    # Preserve the AI's explicitly selected virtual pair during private slices.
    core.alias_gate(a,'binding');a.jump('native')
    a.label('binding');a.call(PAIRED_LOOKUP);a.branch(5,2,0,'resolved')
    a.call(LOOKUP);a.branch(4,2,0,'native')
    a.label('resolved')
    restore(a,True);a.jr();a.label('native');restore(a);a.jump(OLD_RESOLVE)
    b=a.finish();assert len(b)<=0x400;return b


def paired_lookup_code():
    """Keep rush/paired-special recipients bound until both scripts finish.

    Native fields3732/3736, rather than the ordinary lock-on target, select the
    scripted partner. Require reciprocal captured identities so old records do
    not redirect an unrelated later move. This also covers pre-action flag94.
    """
    a=Assembler(PAIRED_LOOKUP);gate(a,'no');a.move(13,10)
    scan(a,4,14,'src','no')
    a.lw(11,4,3732);a.lw(15,4,3736)
    a.r(0x2B,8,11,13);a.branch(4,8,0,'no')
    a.r(0x2B,8,15,13);a.branch(4,8,0,'no');a.branch(4,11,15,'no')
    a.branch(4,14,11,'partner');a.branch(5,14,15,'no');a.move(15,11)
    a.label('partner');policy.emit_enemy(a,14,15,'no','rush_lookup')
    a.li(8,core.POINTERS);a.r(0,9,0,15,2)
    a.r(0x2D,8,8,9);a.lw(12,8);a.branch(4,12,0,'no')
    for off in (3732,3736):
        a.lw(8,4,off);a.lw(9,12,off);a.branch(5,8,9,'no')
    for actor in (4,12):contact.paired_pending(a,actor,'yes')
    a.jump('no');a.label('yes');a.move(2,12);a.move(3,15);a.jr()
    a.label('no');a.move(2,0);a.move(3,0);a.jr()
    b=a.finish();assert len(b)<=0x1000;return b


def contact_code():
    # Insert after the existing leader reload prefix, preserving its veto.
    a=Assembler(CONTACT);save(a);a.call(LOOKUP);a.branch(4,2,0,'defender')
    a.branch(4,2,5,'allow');a.jump('blocked')
    a.label('defender');a.move(4,5);a.call(LOOKUP)
    a.branch(4,2,0,'native');a.lw(8,29,SAVED.index(4)*8)
    a.branch(4,2,8,'allow')
    a.label('blocked');restore(a);a.addiu(2,0,1);a.jr()
    a.label('allow');restore(a);a.move(2,0);a.jr()
    a.label('native');restore(a);a.jump(OLD_CONTACT)
    b=a.finish();assert len(b)<=0x800;return b


def participant_code():
    # Original camera side0/1 may now follow an extra successor. Match its
    # verified throw counterpart to the native bound model before old fallback.
    a=Assembler(PARTICIPANT);save(a);gate(a,'native')
    a.move(13,10);a.i(11,9,4,2);a.branch(4,9,0,'native');a.move(14,4)
    a.li(8,camera.fresh.SUCCESSOR_CONTROL);a.lw(9,8);a.branch(4,9,0,'owner')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'owner')
    a.r(0,9,0,4,2);a.r(0x2D,8,8,9);a.lw(9,8,8)
    a.r(0x2B,10,9,13);a.branch(4,10,0,'owner');a.move(14,9)
    a.label('owner');a.li(8,core.POINTERS);a.r(0,9,0,14,2);a.r(0x2D,8,8,9);a.lw(4,8)
    a.call(LOOKUP);a.branch(4,2,0,'native');model(a,2,12,'native')
    a.lw(11,28,-22180);a.branch(4,11,0,'native')
    for off in (768,772):
        a.lw(9,11,off);a.branch(4,9,12,'yes')
    a.jump('native');a.label('yes');restore(a);a.addiu(2,0,1);a.jr()
    a.label('native');restore(a);a.jump(OLD_PARTICIPANT)
    b=a.finish();assert len(b)<=0x400;return b


def pieces():
    oldresolve=core.rebound(core.resolver_code,RESOLVER=OLD_RESOLVE)()
    oldcontact=core.rebound(contact.protected_code,PROTECTED=OLD_CONTACT,PENDING_CAPTURE=True)()
    oldthrow=core.rebound(contact.throw_code,THROW=OLD_COMMAND)()
    oldparticipant=core.rebound(camera.participant,PARTICIPANT=OLD_PARTICIPANT,
                                OLD_PARTICIPANT=CAMERA_NATIVE)()
    return [(VALID,valid_code()),(LOOKUP,lookup_code()),(CAPTURE,capture_code()),
            (COMMAND,command_code()),(RESOLVE,resolve_code()),(OLD_RESOLVE,oldresolve),
            (CONTACT,contact_code()),(OLD_CONTACT,oldcontact),(OLD_COMMAND,oldthrow),
            (PARTICIPANT,participant_code()),(OLD_PARTICIPANT,oldparticipant),
            (PAIRED_LOOKUP,paired_lookup_code()),
            (CAMERA_NATIVE,struct.pack('<2I',(2<<26)|(camera.OLD_PARTICIPANT>>2),0))]


def build_memory(ram,config=None,source='<offline-memory>'):
    def require(ok,why):
        if not ok:raise ValueError(why)
    require(len(ram)==0x8000000,'Requires128MiB captured RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,n=u(core.ACTORS),u(core.MODE+4)
    require(n in ACTOR_COUNTS and u(core.MODE)==1 and u(core.MODE+8)==manager and u(core.MODE+12)==n,
            'Requires captured active four/six configuration')
    require(not u(core.PAIR+4),'Install only with restored AI aliases')
    for i in range(n):
        actor=u(core.POINTERS+i*4)
        require(0x100000<=actor<=len(ram)-0x1600 and u(actor)==i,'Invalid captured actor')
        require(not any(180<=u(actor+o)<=187 for o in ACTION_FIELDS),'Install before a throw starts')
    require(not any(ram[CODE:END]),'Throw reservation occupied')
    required=[(core.RESOLVER,core.resolver_code()),(leader.PROTECTED,leader.protected_code()),
              (leader.FALLBACK,leader.prior_contact()),(contact.THROW,contact.throw_code()),
              (contact.GATE,contact.gate_code()),(CAPTURE_HOOK,NATIVE(CAPTURE_HOOK,12)),
              (camera.PARTICIPANT,camera.participant())]
    required += [(p,NATIVE(p,n)) for p,n in ((A(0x1FC598),0x368),(A(0x1C3E60),0x1D0),(A(0x24D178),0xC0))]
    for p,b in required:require(ram[p:p+len(b)]==b,f'Throw dependency changed:{p:08X}')
    data=pieces();control=bytearray(0x100);struct.pack_into('<4I',control,0,1,manager,n,1)
    data += [(CONTROL,bytes(control)),(ROWS,bytes(4*n))]
    for hook,dest in HOOKS:
        data.append((hook,struct.pack('<2I',(2<<26)|(dest>>2),0)))
    intervals=sorted((p,p+len(b)) for p,b in data)
    require(all(e<=q for (_,e),(q,_) in zip(intervals,intervals[1:])),'Throw payload overlap')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,rows=ROWS,
                status='AUTHORED NATIVE THROW PAIRS; LIVE VALIDATION REQUIRED',
                blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in data],
                limitations=['No clash/rush/transform guard is removed.',
                             'Native throw animation scratch conversion and timing require live pair coverage.',
                             'Initial extra throw admission conservatively waits for other cinematic sequences.',
                             'Pair records expire when neither participant has a current/requested/queued native throw action.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);x=p.parse_args()
    x.out.write_text(json.dumps(build_memory(read_ram(x.source),source=x.source),indent=2)+'\n')
