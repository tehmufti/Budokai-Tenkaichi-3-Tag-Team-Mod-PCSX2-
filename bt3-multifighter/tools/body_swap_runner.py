"""Native frame-boundary handoff for a captured true Body Change pair.

Original126FB0 executes first, retaining its result. A completed authored pair
may request the established native hold; jobs run only after its ACK. Neither
this runner nor its IO/commit jobs ever release that hold.
"""
from native_map import A
import struct
from prototype import Assembler
import body_swap as body
import body_swap_resources as resources
import body_swap_commit as commit
import native_preparation as native
import extra_reload_requests as requests
import cinematic_contact_guard as contact
import fusion_partner_lifecycle as fusion
import coop_fusion as coop

ENTRY, OLD, JOB, PROTECTED = 0x07030000,0x07033800,0x07034000,0x07036000
CONTROL, RETIRE, RETIRE_CONTROL, END=0x0703F000,0x07090000,0x0709F000,0x070A0000
HOOK=A(0x126FB0)
TARGETS=((resources.IO,resources.IO_CONTROL),(resources.STAGE,resources.STAGE_CONTROL),
         (commit.ENTRY,commit.CONTROL),(RETIRE,RETIRE_CONTROL))
SAVED=tuple(range(1,29))+(30,31)


def save(a):
    a.addiu(29,29,-0x220)
    for i,r in enumerate(SAVED):a.i(31,r,29,16*i)
    for i in range(12):a.i(57,20+i,29,0x1E0+4*i)


def restore(a):
    for i in range(12):a.i(49,20+i,29,0x1E0+4*i)
    for i,r in enumerate(SAVED):a.i(30,r,29,16*i)
    a.addiu(29,29,0x220)


def scope(a,fail):
    a.li(16,body.CONTROL);a.lw(8,16);a.li(9,body.MAGIC);a.branch(5,8,9,fail)
    a.lw(8,16,20);a.addiu(9,0,1);a.branch(5,8,9,fail)
    body.core.gate(a,fail);a.move(17,10)
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,fail)
    a.lw(8,16,8);a.branch(5,8,17,fail)
    a.li(8,body.core.PAIR+4);a.lw(8,8);a.branch(5,8,0,fail)


def code(early=True):
    a=Assembler(ENTRY);a.addiu(29,29,-16);a.i(63,31,29,0);a.call(OLD)
    a.i(55,31,29,0);a.addiu(29,29,16);save(a);scope(a,'done')
    a.lw(8,16,16);a.addiu(9,0,3);a.branch(4,8,9,'job')
    a.addiu(9,0,2);a.branch(5,8,9,'done')
    for p,value in ((native.CONTROL,native.MAGIC),(native.CONTROL+16,0)):
        a.li(8,p);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'done')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x3900);a.branch(5,8,0,'done')
    a.lw(18,16,4)
    for off in (600,612,628):a.lw(8,18,off);a.branch(5,8,0,'done')
    a.lw(8,18,604);a.lw(9,18,608);a.branch(5,8,9,'done')
    # An existing extra transaction must finish its native ACK before this
    # new hold. Pending but unclaimed requests are safe to service afterward.
    for physical in range(2,body.policy.emitted_actors()):
        a.li(8,requests.RECORDS+(physical-2)*requests.STRIDE+4);a.lw(8,8)
        a.addiu(8,8,-2);a.i(11,8,8,3);a.branch(5,8,0,'done')
    for i in range(2):
        a.li(19,body.ROWS+i*64);a.lw(20,19,4);a.lw(8,20,2376);a.addiu(9,0,11)
        if early:
            # FINISH has released the authored Body Change. Any ordinary
            # action (including aerial idle, movement and recovery) is safe
            # to rebind. Waiting for standing idle11 adds seconds and can be
            # prolonged indefinitely by player input. Reloads and paired
            # actions remain excluded until their native dispatch completes.
            a.i(11,9,8,236);a.branch(4,9,0,'done')
        else:a.branch(5,8,9,'done')
        a.lw(8,19);a.r(0x2B,9,8,17);a.branch(4,9,0,'done')
        a.r(0,8,0,8,2);a.li(9,body.core.POINTERS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,20,'done')
        a.lw(8,20,12);a.lw(9,19,8);a.branch(5,8,9,'done')
        a.lw(8,19,12);a.lw(9,8,20);a.lw(10,19,20);a.branch(5,9,10,'done')
        a.lw(8,19,16);a.lw(8,8,64);a.branch(6,8,0,'done')
    # Exact handoff-time rows: the hold is requested in this same frame before
    # any actor update, so these bytes are what the host publishes exchanged.
    for i in range(2):
        a.li(19,body.ROWS+i*64);a.lw(20,19,16);fusion.pointer(a,20,body.ROW_BYTES,'done')
        a.li(21,body.HANDOFF_ROWS[i])
        for off in range(0,body.ROW_BYTES,4):a.lw(8,20,off);a.sw(8,21,off)
    a.li(8,native.CONTROL);a.sw(18,8,24);a.addiu(9,0,1);a.sw(9,8,16)
    a.addiu(9,0,3);a.sw(9,16,16);a.jump('done')
    a.label('job');a.call(JOB)
    a.label('done');restore(a);a.jr();data=a.finish();assert len(data)<OLD-ENTRY;return data


def job_code():
    a=Assembler(JOB);a.addiu(29,29,-0x50)
    for i,r in enumerate((16,17,18,19,20,21,31)):a.i(63,r,29,8*i)
    a.li(16,CONTROL);a.lw(17,16,4);a.lw(8,16,8);a.branch(4,17,8,'done')
    for p,v in ((native.CONTROL,native.MAGIC),(native.CONTROL+16,1),(native.CONTROL+20,1)):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error110')
    a.lw(18,16,16);a.lw(8,28,-22364);a.branch(5,8,18,'error110')
    a.li(8,native.CONTROL+24);a.lw(8,8);a.branch(5,8,18,'error110')
    a.lw(19,16,20);a.lw(20,16,24)
    for i,(entry,control) in enumerate(TARGETS):
        a.li(8,entry);a.branch(5,19,8,f'next{i}');a.li(8,control);a.branch(5,20,8,'error110')
        a.lw(8,20,8);a.branch(5,8,18,'error110')
        a.call(entry);a.jump('called');a.label(f'next{i}')
    a.jump('error110');a.label('called');a.lw(8,20,4);a.sw(8,16,12)
    a.addiu(9,0,5);a.branch(4,8,9,'ack');a.i(11,9,8,100);a.branch(5,9,0,'done');a.jump('ack')
    a.label('error110');a.addiu(8,0,110);a.sw(8,16,12)
    a.label('ack');a.sw(17,16,8)
    a.label('done')
    for i,r in enumerate((16,17,18,19,20,21,31)):a.i(55,r,29,8*i)
    a.addiu(29,29,0x50);a.jr();data=a.finish();assert len(data)<PROTECTED-JOB;return data


def protected_code(previous):
    a=Assembler(PROTECTED);save(a);scope(a,'native')
    a.lw(8,16,16);a.addiu(8,8,-2);a.i(11,8,8,2);a.branch(4,8,0,'native')
    # a0 source / a1 target. Reject new contacts involving either reserved
    # body, including attempted third-party paired captures after its cinematic.
    for i in range(2):
        a.li(8,body.ROWS+i*64+4);a.lw(8,8)
        a.branch(4,4,8,'blocked');a.branch(4,5,8,'blocked')
    a.label('native');restore(a);a.jump(previous)
    a.label('blocked');restore(a);a.addiu(2,0,1);a.jr()
    data=a.finish();assert len(data)<0x1000;return data


def program(previous,early=True):
    original=body.NATIVE(HOOK,8)
    return [(ENTRY,code(early)),(OLD,original+struct.pack('<2I',(2<<26)|((HOOK+8)>>2),0)),
            (JOB,job_code()),(PROTECTED,protected_code(previous)),
            (HOOK,struct.pack('<2I',(2<<26)|(ENTRY>>2),0)),
            (contact.PROTECTED,struct.pack('<2I',(2<<26)|(PROTECTED>>2),0))]


def prior_program(ram,previous):
    import teammate_revive as revive
    if previous==revive.CONTACT:
        revive.validate_memory(ram)
        return
    body.require(previous in (fusion.CONTACT,coop.CONTACT),'Unreviewed prior contact chain')
    prior=coop.contact() if previous==coop.CONTACT else fusion.contact_code()
    body.require(ram[previous:previous+len(prior)]==prior,'Prior contact protection changed')


def frame_hook(ram):
    """Authenticate an optional timed-fusion wrapper without following guesses."""
    direct=struct.pack('<2I',(2<<26)|(ENTRY>>2),0)
    actual=bytes(ram[HOOK:HOOK+8])
    if actual==direct:return direct
    import fusion_duration as duration
    body.require(actual==duration.JUMP(duration.FRAME),'Body Change frame hook changed')
    body.require(duration.validate_memory(ram)==ENTRY,'Timed fusion no longer invokes Body Change')
    body.require((body.u(ram,duration.CONTROL+4),body.u(ram,duration.CONTROL+8))==
                 (body.u(ram,body.CONTROL+4),body.u(ram,body.CONTROL+8)),
                 'Timed fusion belongs to a different Body Change match')
    return actual


@body.policy.matching_install
def validate_memory(ram,*,previous_chain=True):
    import body_swap_capture as capture
    import teammate_revive as revive
    w=body.world(ram,preparing=True)
    body.require(body.u(ram,body.CONTROL)==body.MAGIC and body.u(ram,CONTROL)==body.MAGIC,
                 'Body Change installation identity missing')
    body.require((body.u(ram,body.CONTROL+4),body.u(ram,body.CONTROL+8))==(w['manager'],w['count']),
                 'Body Change capture identity changed')
    body.require(body.u(ram,body.ALLOW_ABILITIES) in (0,1),'Invalid stolen-body ability preference')
    previous=body.u(ram,CONTROL+28)
    body.require(previous in (fusion.CONTACT,coop.CONTACT,revive.CONTACT),'Unreviewed prior contact chain')
    hook=frame_hook(ram)
    current=code()
    early=ram[ENTRY:ENTRY+len(current)]==current
    for at,data in program(previous,early=early)+capture.program():
        if at==HOOK:data=hook
        body.require(ram[at:at+len(data)]==data,f'Body Change executable changed {at:08X}')
    if previous_chain:prior_program(ram,previous)
    return previous


def build_memory(ram):
    w=body.world(ram,preparing=True);body.require(not any(ram[ENTRY:0x07040000]),'Body runner reservation occupied')
    original=body.NATIVE(HOOK,8)
    body.require(ram[HOOK:HOOK+8]==original,'Native frame predecessor changed')
    previous=(body.u(ram,contact.PROTECTED)&0x3FFFFFF)<<2
    expected=struct.pack('<2I',(2<<26)|(previous>>2),0)
    body.require(ram[contact.PROTECTED:contact.PROTECTED+8]==expected,'Unreviewed prior contact chain')
    prior_program(ram,previous)
    parts=program(previous)+[(CONTROL,struct.pack('<8I',body.MAGIC,0,0,0,w['manager'],0,0,previous))]
    return resources.parts_manifest(ram,parts,entry=ENTRY,control=CONTROL,previous_contact=previous)


def dependency_override(ram,address,expected):
    """Authenticate the optional outer contact guard before older validation."""
    if address!=contact.PROTECTED or body.u(ram,body.CONTROL)!=body.MAGIC:return expected
    previous=validate_memory(ram,previous_chain=False)
    actual=struct.pack('<2I',(2<<26)|(PROTECTED>>2),0)
    prior=struct.pack('<2I',(2<<26)|(previous>>2),0)
    body.require(expected[:8] in (prior,actual),'Body Change contact continuation mismatch')
    return actual[:len(expected)]+expected[8:]


def base_view(ram):
    """Expose an authenticated prior hook in a copy, never in guest memory."""
    if body.u(ram,body.CONTROL)!=body.MAGIC:return ram
    previous=validate_memory(ram,previous_chain=False)
    copy=bytearray(ram)
    copy[contact.PROTECTED:contact.PROTECTED+8]=struct.pack('<2I',(2<<26)|(previous>>2),0)
    return copy
