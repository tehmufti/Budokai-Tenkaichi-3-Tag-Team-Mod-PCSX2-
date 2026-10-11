"""Deliver private tag cues after the native frame clears its sound queue.

The tag director runs before 12B6E0. Native1C2B30 clears manager+160 before
1C2F10 dispatches sounds, so early calls to1DA348 were discarded. This bounded
mailbox is drained at the existing1C2F90 call, preserving native requests,
attenuation, the four-request budget and the ordinary sound-loop cleanup.
"""
import struct
from native_map import A, ACTOR_HZ
from prototype import Assembler
import tag_team_rush as tag
import tag_rush_camera as camera
import fusion_partner_lifecycle as full
import fresh_team_combat as core
import beam_struggle as fp

BASE, ENQUEUE, FLUSH, CHARGE = 0x06D99000,0x06D99000,0x06D99800,0x06D9A000
STATE, RECORDS, END = 0x06D9AC00,0x06D9AD00,0x06D9B000
HOOK, DISPATCH, SOUND = A(0x1C2F90),A(0x1DA098),A(0x1DA348)
NATIVE_HOOK=struct.pack('<I',(3<<26)|(DISPATCH>>2))
INSTALLED_HOOK=struct.pack('<I',(3<<26)|(FLUSH>>2))
MAGIC, CAPACITY, STRIDE = 0x54415131,16,48
F=dict(magic=0,manager=4,count=8,pending=12,enqueued=16,delivered=20,
       overflow=24,discarded=28,head=32,charge_requests=36)


def reset(a):
    a.li(8,STATE)
    for offset in F.values():a.sw(0,8,offset)
    a.li(9,MAGIC);a.sw(9,8,F['magic'])
    a.li(9,tag.CONTROL);a.lw(10,9,tag.C['manager']);a.sw(10,8,F['manager'])
    a.lw(10,9,tag.C['count']);a.sw(10,8,F['count'])


def gate(a,fail):
    camera.emit_active(a,fail)
    a.li(16,STATE);a.lw(9,16);a.li(10,MAGIC);a.branch(5,9,10,fail)
    for off in (F['manager'],F['count']):
        a.lw(9,16,off);a.lw(10,8,off);a.branch(5,9,10,fail)


def enqueue_code():
    """Same position/bank/id/FPU arguments as1DA348; v0 means accepted."""
    a=Assembler(ENQUEUE);tag.save(a);a.move(20,4);a.move(21,5);a.move(22,6)
    gate(a,'no');a.i(11,8,21,2);a.branch(4,8,0,'no')
    a.i(11,8,22,256);a.branch(4,8,0,'no');full.pointer(a,20,16,'no')
    for off in (0,4,8):
        a.lw(8,20,off);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,'no')
    a.lw(17,16,F['pending']);a.i(11,9,17,CAPACITY);a.branch(4,9,0,'full')
    a.lw(18,16,F['head']);a.r(0x21,18,18,17);a.i(12,18,18,CAPACITY-1)
    a.li(9,STRIDE);a.r(0x19,0,18,9);a.r(0x12,18,0,0);a.li(9,RECORDS);a.r(0x21,18,18,9)
    for off in range(0,16,4):a.lw(8,20,off);a.sw(8,18,off)
    a.i(57,12,18,16);a.i(57,13,18,20);a.sw(22,18,24);a.sw(21,18,28)
    # A delayed cue is useful for at most four scene updates, not after a long
    # native sound backlog. The scene clock freezes during pause.
    a.li(8,tag.MEMBERS_SAVE);a.lw(9,8,84);a.sw(9,18,32)
    a.addiu(17,17,1);a.sw(17,16,F['pending'])
    a.lw(8,16,F['enqueued']);a.addiu(8,8,1);a.sw(8,16,F['enqueued']);a.li(2,1);a.jump('done')
    a.label('full');a.lw(8,16,F['overflow']);a.addiu(8,8,1);a.sw(8,16,F['overflow'])
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,result=2);a.jr()
    data=a.finish();assert ENQUEUE+len(data)<=FLUSH;return data


def flush_code():
    import tag_rush_approach as approach
    a=Assembler(FLUSH);tag.save(a)
    # The accepted native rush prelude precedes tag.active. Its phase0 sound
    # also needs the late dispatch, before the private cinematic mailbox.
    a.call(approach.START_SOUND)
    gate(a,'clear');a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'native')
    a.lw(17,16,F['manager'])
    a.label('next');a.lw(18,16,F['pending']);a.branch(4,18,0,'charge')
    a.i(11,9,18,CAPACITY+1);a.branch(4,9,0,'clear')
    a.lw(19,16,F['head']);a.i(11,9,19,CAPACITY);a.branch(4,9,0,'clear')
    a.li(9,STRIDE);a.r(0x19,0,19,9);a.r(0x12,20,0,0);a.li(9,RECORDS);a.r(0x21,20,20,9)
    a.li(8,tag.MEMBERS_SAVE);a.lw(8,8,84);a.lw(9,20,32);a.r(0x23,8,8,9)
    a.i(11,9,8,5);a.branch(4,9,0,'discard')
    a.lw(8,17,288);a.i(11,9,8,4);a.branch(4,9,0,'charge')
    # Check the actual native shared bank before submitting the event.
    a.lw(8,20,28);a.li(4,4);a.branch(4,8,0,'bank');a.li(4,8)
    a.label('bank');a.call(A(0x1252D8));a.branch(4,2,0,'discard')
    a.move(4,20);a.lw(5,20,28);a.lw(6,20,24)
    a.i(49,12,20,16);a.i(49,13,20,20);a.call(SOUND)
    a.branch(4,2,0,'charge')
    a.lw(8,16,F['delivered']);a.addiu(8,8,1);a.sw(8,16,F['delivered']);a.jump('consume')
    a.label('discard');a.lw(8,16,F['discarded']);a.addiu(8,8,1);a.sw(8,16,F['discarded'])
    a.label('consume');a.addiu(18,18,-1);a.sw(18,16,F['pending']);a.addiu(19,19,1)
    a.i(12,19,19,CAPACITY-1);a.sw(19,16,F['head']);a.jump('next')
    a.label('charge');a.call(CHARGE);a.jump('native')
    a.label('clear');a.li(8,STATE);a.sw(0,8,F['pending']);a.sw(0,8,F['head'])
    # This private bank dispatch also runs while tag.active is false so a
    # cancelled/finished move stops its owned sounds on the next sound frame.
    import tag_rush_beam_audio as beam_audio
    a.label('native');a.li(8,beam_audio.STATE);a.lw(8,8);a.li(9,beam_audio.MAGIC)
    a.branch(5,8,9,'native_dispatch');a.call(beam_audio.TICK)
    a.label('native_dispatch');tag.restore(a);a.jump(DISPATCH)
    data=a.finish();assert FLUSH+len(data)<=CHARGE;return data


def charge_code():
    """Renew native actor-owned charge21 only until the authored firing frame.

    Native1DA098 deduplicates its loop handle per physical actor. The existing
    all-actor1D9D28 cleanup stops it on the first frame without renewal, including
    firing, cancellation and normal ending. No global sound/voice stop is used.
    """
    import tag_rush_scene as scene
    import tag_rush_assets as assets
    import tag_rush_staging as staging
    a=Assembler(CHARGE);tag.save(a);gate(a,'done')
    a.li(17,scene.STATE);a.lw(8,17,scene.S['retiring']);a.branch(5,8,0,'done')
    a.lw(18,17,scene.S['descriptor']);full.pointer(a,18,64,'done')
    a.lw(19,18,28);a.i(12,8,19,assets.OWN_CLASH_POSE);a.branch(4,8,0,'done')
    a.lw(4,17,scene.S['phase']);a.call(staging.QUERY);a.branch(4,2,0,'done')
    a.lw(20,2,8);a.i(11,8,20,601);a.branch(4,8,0,'done')
    a.lw(8,17,scene.S['ticks']);a.li(9,60);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.li(9,ACTOR_HZ);a.r(0x19,0,20,9);a.r(0x12,9,0,0)
    a.r(0x2B,8,8,9);a.branch(4,8,0,'done')
    a.li(4,4);a.call(A(0x1252D8));a.branch(4,2,0,'done')
    a.li(4,4);a.li(5,21);a.call(A(0x1251E8));a.branch(4,2,0,'done')
    for role,bit in enumerate((assets.BEAM_LEAD,assets.BEAM_PARTNER)):
        fail=f'next{role}'
        a.i(12,8,19,bit);a.branch(4,8,0,fail)
        a.li(21,scene.ROWS+role*scene.STRIDE);scene.identity(a,21,fail,f'charge{role}')
        a.lw(8,16,F['manager']);a.lw(8,8,288);a.i(11,8,8,4);a.branch(4,8,0,fail)
        a.move(4,22);a.li(5,21);a.call(A(0x1DA370))
        a.lw(8,16,F['charge_requests']);a.addiu(8,8,1);a.sw(8,16,F['charge_requests']);a.label(fail)
    a.label('done');tag.restore(a);a.jr()
    data=a.finish();assert CHARGE+len(data)<=STATE;return data


def pieces():
    return [(ENQUEUE,enqueue_code()),(FLUSH,flush_code()),(CHARGE,charge_code()),(STATE,bytes(END-STATE))]
