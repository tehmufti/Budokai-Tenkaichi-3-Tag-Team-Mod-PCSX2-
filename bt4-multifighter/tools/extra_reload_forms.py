"""Native ordinary-form admission and private reload handshake for extras.

Installation remains dormant: CONTROL enable0. A reviewed serial worker must
own the private resource transaction before enabling commands99..103. Fusion
104..106 and tag107 retain their existing bounds. No shared native queue row or
scene roster is repurposed for an extra fighter.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

import extra_reload_requests as requests
import extra_reload_quiet as quiet
import ordinary_transform_guard as ordinary
import fresh_team_safety as safety
import extra_reload_heap as heap
from prototype import Assembler,ROOT,elf_reader
import battle_mode_policy as policy

CODE,ELIGIBILITY,BEGIN,SIDE,PUSH=0x07660000,0x07660000,0x07660400,0x07661000,0x07661400
OLD_ELIGIBILITY,OLD_BEGIN=0x07660800,0x07660C00
READY,ACK,FINISH=0x07662000,0x07662400,0x07662800
OLD_READY,OLD_ACK,OLD_FINISH=0x07662C00,0x07662E00,0x07662F00
CONTROL,END=0x0766F000,0x07670000
FORM_ENABLE=requests.CONTROL+24
# Refusal telemetry: how many ordinary-form commands this service turned away,
# why the last one was refused (1 fusion reservation, 2 no native model
# storage, 3 texture groups full, 4 no free resource record, 5 heap admission,
# whose own reason word is extra_reload_heap.REASON) and whose actor it was.
REFUSALS,REFUSED_REASON,REFUSED_ACTOR=16,20,24
SAVED=(8,9,10,11,12,13,14,15,16,17,24,25)
NATIVE=elf_reader(elf_path(ROOT))[2]


def scope(a,fallback):
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,fallback)
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,fallback)
    a.li(8,requests.CONTROL);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,fallback)
    a.lw(9,8,24);a.branch(5,9,10,fallback)
    a.li(8,quiet.core.MODE);a.lw(9,8);a.branch(5,9,10,fallback)
    a.lw(9,8,8);a.lw(10,28,-22364);a.branch(5,9,10,fallback)
    a.lw(11,8,4);a.lw(9,8,12);a.branch(5,9,11,fallback)
    policy.emit_listed_count(a,11,fallback,'scope_count',scratch=9)
    a.label('scope_count')
    a.li(8,CONTROL);a.lw(9,8,8);a.branch(5,9,11,fallback)
    # Count and pointers were captured during installation; scan actual
    # pointers instead of aliased actor+0 to preserve physical team identity.
    a.addiu(12,0,2);a.li(13,quiet.core.POINTERS+8)


def admission(entry,base,old):
    saved=(2,8,9,10,11,12,13,31)
    a=Assembler(base);a.addiu(29,29,-0x40)
    for i,r in enumerate(saved):a.i(63,r,29,8*i)
    scope(a,'fallback')
    a.label('scan');a.lw(8,13);a.branch(4,8,4,'native')
    a.addiu(13,13,4);a.addiu(12,12,1);a.branch(5,12,11,'scan');a.jump('fallback')
    a.label('native')
    a.li(8,requests.FUSION_CONTROL);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,'not_reserved')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'not_reserved')
    a.call(requests.FUSION_RESERVED);a.branch(5,2,0,'refuse1');a.label('not_reserved')
    # Admission is read-only. A full registry/model/texture table must leave
    # ordinary combat running instead of queuing an unserviceable form that
    # could acquire the host hold and fail halfway through preparation.
    a.li(8,requests.preloader.REGISTRY_GLOBAL);a.lw(8,8)
    a.li(9,69128);a.r(0x2D,9,8,9);a.lw(9,9);a.branch(4,9,0,'refuse2')
    a.li(9,439156);a.r(0x2D,9,8,9);a.lw(9,9);a.i(12,9,9,0x7FFF)
    # Keep two texture groups for cinematic summons after this replacement.
    # Clear the two lowest free bits; require a third for this replacement.
    a.i(14,9,9,0x7FFF);a.addiu(10,9,-1);a.r(0x24,10,9,10)
    a.addiu(9,10,-1);a.r(0x24,10,9,10)
    a.branch(4,10,0,'refuse3')
    a.li(9,requests.preloader.REGISTRY_OFFSET);a.r(0x2D,9,8,9);a.addiu(10,0,12)
    a.label('free_record');a.lw(8,9,48);a.i(12,8,8,1);a.branch(4,8,0,'capacity_ready')
    a.addiu(9,9,56);a.addiu(10,10,-1);a.branch(5,10,0,'free_record');a.jump('refuse4')
    a.label('capacity_ready')
    a.call(heap.ENTRY);a.branch(4,2,0,'refuse5')
    for i,r in enumerate(saved):a.i(55,r,29,8*i)
    a.addiu(29,29,0x40)
    for word in struct.unpack('<2I',NATIVE(entry,8)):a.emit(word)
    a.jump(entry+8)
    # A capacity refusal is otherwise invisible: the command simply falls
    # through to the ordinary guard and the fighter keeps looking for a move it
    # can never start. Record how often, why and for whom, after the actor has
    # been matched so leaders and other modes stay byte-identical.
    for reason in range(1,6):
        a.label(f'refuse{reason}');a.addiu(12,0,reason)
        if reason<5:a.jump('refused')
    a.label('refused')
    a.li(8,CONTROL);a.lw(9,8,REFUSALS);a.addiu(9,9,1);a.sw(9,8,REFUSALS)
    a.sw(12,8,REFUSED_REASON);a.sw(4,8,REFUSED_ACTOR)
    a.label('fallback')
    for i,r in enumerate(saved):a.i(55,r,29,8*i)
    a.addiu(29,29,0x40);a.jump(old)
    result=a.finish();assert len(result)<0x400;return result


def side_code():
    a=Assembler(SIDE);a.addiu(29,29,-0x40)
    for i,r in enumerate((4,8,9,10,11,12,13,31)):a.i(63,r,29,8*i)
    scope(a,'call')
    a.label('scan');a.lw(8,13);a.branch(4,8,16,'mapped') # native2033C8's s0 is its actor
    a.addiu(13,13,4);a.addiu(12,12,1);a.branch(5,12,11,'scan');a.jump('call')
    a.label('mapped');a.i(12,4,12,1)
    a.label('call');a.call(A(0x12B4F0))
    for i,r in enumerate((4,8,9,10,11,12,13,31)):a.i(55,r,29,8*i)
    a.addiu(29,29,0x40);a.jr();return a.finish()


def push_code():
    a=Assembler(PUSH);a.addiu(29,29,-0x60)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)
    scope(a,'fallback')
    a.i(11,8,4,2);a.branch(5,8,0,'fallback');a.r(0x2B,8,4,11);a.branch(4,8,0,'fallback')
    a.r(0,8,0,4,2);a.li(9,quiet.core.POINTERS);a.r(0x2D,9,9,8);a.lw(14,9)
    a.lw(15,14,0x948);a.addiu(8,15,-236);a.i(11,8,8,7);a.branch(4,8,0,'fallback')
    for reg,off in ((5,0x12D0),(6,0x12D4),(7,0x12E0)):
        a.lw(8,14,off);a.branch(5,8,reg,'fallback')
    # Ordinary203610 stores the same destination character in animation,
    # combat and sound fields. Do not silently change a scripted variant.
    for stack in (0,8,16):
        a.lw(8,29,stack);a.branch(5,8,5,'fallback')
    a.lw(13,14,12);a.i(11,8,13,12);a.branch(4,8,0,'fallback')
    a.r(0,8,0,13,2);a.li(9,quiet.core.MODELS);a.r(0x2D,9,9,8);a.lw(17,9)
    a.branch(4,17,0,'fallback');a.lw(8,17,16);a.branch(5,8,13,'fallback')
    a.addiu(8,4,-2);a.r(0,8,0,8,6);a.li(16,requests.RECORDS);a.r(0x2D,16,16,8)
    a.lw(8,16,4);a.addiu(8,8,-2);a.i(11,8,8,3);a.branch(5,8,0,'handled')
    a.sw(0,16,4);a.lw(8,16);a.addiu(8,8,1);a.branch(5,8,0,'generation');a.addiu(8,0,1)
    a.label('generation');a.sw(8,16)
    for off,reg in ((8,14),(12,13),(16,17),(20,5),(24,6),(28,7),(32,5),(36,5),(40,5),(44,4),(60,15)):
        a.sw(reg,16,off)
    a.lw(8,17,20);a.sw(8,16,48);a.sw(0,16,52)
    a.addiu(8,0,1);a.sw(8,16,56);a.sw(8,16,4)
    a.label('handled');a.move(2,0);a.jump('done')
    a.label('fallback')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x60);a.jump(requests.CODE)
    a.label('done')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x60);a.jr();result=a.finish();assert len(result)<READY-PUSH;return result


def handshake(kind):
    base,old={'ready':(READY,OLD_READY),'ack':(ACK,OLD_ACK),'finish':(FINISH,OLD_FINISH)}[kind]
    a=Assembler(base);a.addiu(29,29,-0x60)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)
    scope(a,'fallback')
    # A completed transformation receipt can remain after the model changes.
    # Its ACK/FINISH must never consume a subsequent native summon handshake.
    import model_slot_guards as summons
    a.li(8,summons.CONTROL);a.lw(9,8);a.li(10,summons.MAGIC)
    a.branch(5,9,10,'form_receipt')
    a.addiu(29,29,-16);a.i(63,31,29,0);a.call(summons.SUMMON_PENDING)
    a.i(55,31,29,0);a.addiu(29,29,16);a.branch(5,2,0,'fallback')
    a.label('form_receipt')
    a.i(11,8,4,2);a.branch(5,8,0,'fallback');a.r(0x2B,8,4,11);a.branch(4,8,0,'fallback')
    a.addiu(8,4,-2);a.r(0,8,0,8,6);a.li(16,requests.RECORDS);a.r(0x2D,16,16,8)
    a.lw(8,16,56);a.addiu(9,0,1);a.branch(5,8,9,'fallback')
    a.lw(9,16,8);a.r(0,8,0,4,2);a.li(10,quiet.core.POINTERS);a.r(0x2D,10,10,8)
    a.lw(8,10);a.branch(5,8,9,'fallback')
    a.lw(8,9,12);a.lw(10,16,12);a.branch(5,8,10,'fallback')
    a.lw(8,16,4)
    if kind=='ready':
        a.addiu(9,8,-3);a.i(11,2,9,3) # ready for staged3, commit-request4, committed5
    elif kind=='ack':
        a.addiu(9,0,3);a.branch(5,8,9,'handled')
        # Actor has consumed its native transformation cost and selected its
        # transition animation. Hold on the next dispatch for atomic commit.
        a.li(10,quiet.native.CONTROL);a.lw(11,10);a.li(12,quiet.native.MAGIC)
        a.branch(5,11,12,'handled');a.lw(11,28,-22364);a.sw(11,10,24)
        a.addiu(8,0,4);a.sw(8,16,4);a.addiu(8,0,1);a.sw(8,10,16)
        a.label('handled');a.move(2,0)
    else:
        a.addiu(9,0,5);a.branch(5,8,9,'handled')
        a.addiu(8,0,6);a.sw(8,16,4)
        a.label('handled');a.move(2,0)
    a.jump('done')
    a.label('fallback')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x60);a.jump(old)
    a.label('done')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x60);a.jr()
    result=a.finish();assert len(result)<0x400;return result


def build_memory(ram,source='<captured-ready>'):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    world=requests.preloader.capture(ram,2)
    heap.validate_native(ram)
    if any(ram[CODE:END]):raise ValueError('Ordinary-form service reservation occupied')
    if ram[requests.CODE:requests.CODE+len(requests.payload())]!=requests.payload():
        raise ValueError('Install reviewed reload request capture first')
    parts=heap.pieces()
    for (entry,cave,_),new,old in zip(ordinary.ENTRIES,(ELIGIBILITY,BEGIN),(OLD_ELIGIBILITY,OLD_BEGIN)):
        owned=cave+0x200;before=safety.owned_code(entry,owned,2,NATIVE(entry,8))
        if ram[owned:owned+len(before)]!=before:raise ValueError('Ordinary form guard body changed')
        parts += [(new,admission(entry,new,old)),(old,safety.owned_code(entry,old,2,NATIVE(entry,8))),
                  (owned,struct.pack('<2I',(2<<26)|(new>>2),0))]
    if u(A(0x203484))!=(3<<26)|(A(0x12B4F0)>>2):raise ValueError('Native ordinary side-eligibility call changed')
    parts += [(SIDE,side_code()),(A(0x203484),struct.pack('<I',(3<<26)|(SIDE>>2)))]
    expected=struct.pack('<2I',(2<<26)|(requests.CODE>>2),0)
    if ram[requests.previous.PUSH_HOOK:requests.previous.PUSH_HOOK+8]!=expected:
        raise ValueError('Reviewed request capture entry changed')
    parts += [(PUSH,push_code()),(requests.previous.PUSH_HOOK,struct.pack('<2I',(2<<26)|(PUSH>>2),0))]
    for kind,entry,base,old in (('ready',A(0x1D6360),READY,OLD_READY),('ack',A(0x1D63D8),ACK,OLD_ACK),('finish',A(0x1D6408),FINISH,OLD_FINISH)):
        expected=struct.pack('<2I',(2<<26)|(requests.previous.READY>>2),0) if kind=='ready' else NATIVE(entry,8)
        if ram[entry:entry+8]!=expected:raise ValueError(f'Native reload {kind} handshake changed')
        fallback=expected if kind=='ready' else expected+struct.pack('<2I',(2<<26)|((entry+8)>>2),0)
        parts += [(base,handshake(kind)),(old,fallback),(entry,struct.pack('<2I',(2<<26)|(base>>2),0))]
    parts += [(CONTROL,struct.pack('<7I',0,world['manager'],world['count'],0,0,0,0))]
    result=dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                status='DORMANT NATIVE ORDINARY-FORM HANDSHAKE; WORKER REQUIRED',
                blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in parts])
    import extra_reload_form_contacts as contacts
    view=bytearray(ram)
    for block in result['blocks']:
        p=block['address'];data=bytes.fromhex(block['data_hex']);view[p:p+len(data)]=data
    result['blocks']+=contacts.build_memory(view,source)['blocks']
    import extra_cell_absorption
    result['blocks']+=extra_cell_absorption.build_memory(view,source)['blocks']
    return result
