"""Arbitrate effect-driven cinematic presentation without serializing attacks.

Only the two native special-effect camera start/stop callsites are wrapped.
Actor animation and damage continue when an unrelated camera request loses.
The viewed successor's verified pair takes precedence over an NPC-only pair.
There is still one cinematic view; suppressed tracks are not replayed later.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import fresh_team_camera as fresh
import cinematic_camera_state as camera
import camera_continuity as continuity
import team_intro
import result_presentation
import battle_mode_policy
from battle_mode_policy import ACTOR_COUNTS

CODE = 0x077F0000
START1, START2, STOP1, STOP2, PRIORITY = (CODE+i for i in (0,0x800,0x1000,0x1800,0x2000))
CONTROL, END, MAGIC = CODE+0x7000, CODE+0x8000, 0x53434131
OWNER_OFFSET = 16
DIRECTOR, CINEMATIC = A(0x2FE9B0), A(0x2FEBCC)
NATIVE_START, NATIVE_STOP = A(0x12F5F0), A(0x12F6E8)
HOOKS = ((A(0x15769C),START1,NATIVE_START,0xAFA30008),
         (A(0x15B610),START2,NATIVE_START,0xAFA30008),
         (A(0x158224),STOP1,NATIVE_STOP,0), (A(0x15C414),STOP2,NATIVE_STOP,0))
SAVED = tuple(range(2,16))+(24,25,31)
FRAME = 0xC0
# Stable beam ownership ABI; keep this module independent of beam_clash imports.
BEAM_CONTROL, BEAM_MAGIC = 0x0724F000, 0x42434C31


def save(a):
    a.addiu(29,29,-FRAME)
    for i,r in enumerate(SAVED): a.i(63,r,29,8*i)


def restore(a):
    for i,r in enumerate(SAVED): a.i(55,r,29,8*i)
    a.addiu(29,29,FRAME)


def pointer(a,reg,size,fail):
    a.li(8,0x100000); a.r(0x2B,9,reg,8); a.branch(5,9,0,fail)
    a.li(8,0x08000000-size+1); a.r(0x2B,9,reg,8); a.branch(4,9,0,fail)
    a.i(12,9,reg,3); a.branch(5,9,0,fail)


def gate(a,fail):
    core.gate(a,fail)
    a.li(8,CONTROL); a.lw(9,8); a.li(11,MAGIC); a.branch(5,9,11,fail)
    a.lw(9,8,4); a.lw(11,28,-22364); a.branch(5,9,11,fail)
    a.lw(9,8,8); a.branch(5,9,10,fail)
    a.lw(9,11,628); a.branch(5,9,0,fail)
    a.li(11,team_intro.BATTLE); a.lw(11,11); a.lw(9,8,12)
    a.branch(5,9,11,fail); a.branch(4,11,0,fail)
    a.lw(9,11); a.addiu(11,0,3); a.branch(5,9,11,fail)
    a.li(9,result_presentation.RESULT); a.lw(9,9); a.branch(5,9,0,fail)
    a.li(9,core.PAIR+4); a.lw(9,9); a.branch(5,9,0,fail)


def bump(a,offset):
    a.li(8,CONTROL); a.lw(9,8,offset); a.addiu(9,9,1); a.sw(9,8,offset)



def emit_owned_beam(a, fail):
    """Prove a live captured beam reservation; clobber only t0..t3.

    Inline, no calls/import cycles. Validate physical pointers and actual model
    identity so a stale active token cannot suppress a later battle's cameras.
    Pending reservations count too: their native AA requests commit next frame.
    """
    core.gate(a,fail)
    a.li(8,BEAM_CONTROL); a.lw(9,8); a.li(11,BEAM_MAGIC); a.branch(5,9,11,fail)
    a.lw(9,8,4); a.lw(11,28,-22364); a.branch(5,9,11,fail)
    a.lw(9,8,8); a.branch(5,9,10,fail)
    a.lw(9,8,12); a.li(11,team_intro.BATTLE); a.lw(11,11); a.branch(5,9,11,fail)
    a.branch(4,11,0,fail); a.lw(9,11); a.addiu(11,0,3); a.branch(5,9,11,fail)
    a.li(9,result_presentation.RESULT); a.lw(9,9); a.branch(5,9,0,fail)
    a.li(9,continuity.SCENE_FLAGS); a.lw(9,9); a.i(12,9,9,0x2000); a.branch(5,9,0,fail)
    a.lw(9,8,16); a.addiu(9,9,-1); a.i(11,11,9,2); a.branch(4,11,0,fail)
    for side in range(2):
        a.lw(9,8,80+4*side); a.lw(11,8,8); a.r(0x2B,11,9,11); a.branch(4,11,0,fail)
        # Coordinator side is collision order, not native team parity. FFA can
        # legitimately bind two actors whose physical indices share parity.
        a.lw(10,8,64+4*side); a.r(0,9,0,9,2)
        a.li(11,core.POINTERS); a.r(0x2D,11,11,9); a.lw(11,11); a.branch(5,10,11,fail)
        a.addiu(11,8,0x100); a.r(0x2D,11,11,9); a.lw(11,11); a.branch(5,10,11,fail)
        a.li(9,0x100000); a.r(0x2B,11,10,9); a.branch(5,11,0,fail)
        a.li(9,0x08000000-0x1600); a.r(0x2B,11,9,10); a.branch(5,11,0,fail)
        a.i(12,9,10,3); a.branch(5,9,0,fail)
        a.lw(9,10,12); a.lw(11,8,72+4*side); a.branch(5,9,11,fail)
        a.i(11,11,9,12); a.branch(4,11,0,fail)
        a.r(0,9,0,9,2); a.li(11,core.MODELS); a.r(0x2D,11,11,9); a.lw(11,11)
        a.li(9,0x100000); a.r(0x2B,10,11,9); a.branch(5,10,0,fail)
        a.li(9,0x08000000-0x1670); a.r(0x2B,10,9,11); a.branch(5,10,0,fail)
        a.i(12,9,11,3); a.branch(5,9,0,fail)
        a.lw(9,11,16); a.lw(10,8,72+4*side); a.branch(5,9,10,fail)
    a.lw(9,8,80); a.lw(10,8,84)
    battle_mode_policy.emit_enemy(a,9,10,fail,f'beam_pair_{len(a.words)}',t0=8,t1=11)


def emit_owned_camera(a, fail):
    """Inline current-owner proof. Clobbers only t0..t3; makes no calls.

    The token alone is insufficient after stage/transform/throw replacement.
    Match captured identity, director request and the actual animated camera.
    """
    a.li(8,CONTROL); a.lw(9,8); a.li(10,MAGIC); a.branch(5,9,10,fail)
    a.lw(9,8,4); a.lw(10,28,-22364); a.branch(5,9,10,fail)
    a.lw(9,8,8); a.li(10,core.MODE+4); a.lw(10,10); a.branch(5,9,10,fail)
    a.lw(9,8,12); a.li(10,team_intro.BATTLE); a.lw(10,10); a.branch(5,9,10,fail)
    a.li(10,0x100000); a.r(0x2B,11,9,10); a.branch(5,11,0,fail)
    a.li(10,0x08000000-300); a.r(0x2B,11,9,10); a.branch(4,11,0,fail)
    a.lw(9,9); a.addiu(10,0,3); a.branch(5,9,10,fail)
    a.li(9,result_presentation.RESULT); a.lw(9,9); a.branch(5,9,0,fail)
    a.lw(9,8,16); a.branch(4,9,0,fail)
    a.li(9,continuity.SCENE_FLAGS); a.lw(9,9); a.i(12,9,9,0x2000); a.branch(5,9,0,fail)
    a.li(9,DIRECTOR); a.lw(11,9)
    a.li(9,0x100000); a.r(0x2B,10,11,9); a.branch(5,10,0,fail)
    a.li(9,0x08000000-28+1); a.r(0x2B,10,11,9); a.branch(4,10,0,fail)
    a.i(12,9,11,3); a.branch(5,9,0,fail)
    a.lw(9,11,12); a.branch(4,9,0,fail)
    for off,control in ((0,20),(4,24),(8,28)):
        a.lw(9,11,off); a.lw(10,8,control); a.branch(5,9,10,fail)
    a.li(9,CINEMATIC); a.lw(11,9)
    a.li(9,0x100000); a.r(0x2B,10,11,9); a.branch(5,10,0,fail)
    a.li(9,0x08000000-832+1); a.r(0x2B,10,11,9); a.branch(4,10,0,fail)
    a.i(12,9,11,3); a.branch(5,9,0,fail)
    a.lw(9,11,812); a.branch(5,9,0,fail)
    a.lw(9,11,776); a.i(12,9,9,3); a.addiu(10,0,1); a.branch(5,9,10,fail)
    a.lw(9,11,704); a.lw(10,8,20); a.branch(5,9,10,fail)


def priority_code():
    """a0=model ID, a1=view side, a2=split; v0=rank, v1=valid actor.

    Side0 then side1 wins in split presentation. In single view only the
    currently viewed side gets priority. Pointer table identity survives aliases.
    """
    a=Assembler(PRIORITY); a.li(8,CONTROL); a.lw(15,8,8)
    a.i(11,8,4,12); a.branch(4,8,0,'invalid')
    a.li(13,core.POINTERS); a.move(14,0)
    a.label('find'); a.lw(11,13); a.branch(4,11,0,'next')
    a.lw(8,11,12); a.branch(4,8,4,'found')
    a.label('next'); a.addiu(13,13,4); a.addiu(14,14,1)
    a.branch(5,14,15,'find'); a.jump('invalid')
    a.label('found'); a.lw(8,11,0x994); a.i(11,9,8,5); a.branch(4,9,0,'invalid')
    a.r(0,9,0,8,7); a.r(0,10,0,8,5); a.r(0x2D,9,9,10)
    a.r(0,10,0,8,2); a.r(0x2D,9,9,10); a.r(0x2D,9,9,11)
    a.lw(8,9,0x9E4); a.branch(6,8,0,'invalid')
    a.r(0,8,0,4,2); a.li(9,core.MODELS); a.r(0x2D,8,8,9); a.lw(12,8)
    pointer(a,12,0x1670,'invalid'); a.lw(8,12,16); a.branch(5,8,4,'invalid')
    a.lw(8,12,4); a.addiu(9,0,1); a.branch(5,8,9,'invalid')
    # Each view's current successor, with native leader fallback.
    a.move(24,0)
    a.label('view'); a.move(25,24)
    a.li(8,fresh.SUCCESSOR_CONTROL); a.lw(9,8); a.branch(4,9,0,'subject')
    a.lw(9,8,4); a.lw(10,28,-22364); a.branch(5,9,10,'subject')
    a.r(0,9,0,24,2); a.r(0x2D,8,8,9); a.lw(9,8,8)
    a.r(0x2B,10,9,15); a.branch(4,10,0,'subject'); a.move(25,9)
    a.label('subject'); a.branch(4,25,14,'member')
    a.li(8,core.POINTERS); a.r(0,9,0,25,2); a.r(0x2D,8,8,9); a.lw(12,8)
    a.branch(4,12,0,'not_member'); a.lw(8,12,2376)
    for start in (301,313):
        a.addiu(9,8,-start); a.i(11,9,9,3); a.branch(5,9,0,'paired')
    a.jump('not_member')
    a.label('paired'); a.lw(8,12,3732); a.lw(9,12,3736)
    a.r(0x2B,10,8,15); a.branch(4,10,0,'not_member')
    a.r(0x2B,10,9,15); a.branch(4,10,0,'not_member'); a.branch(4,8,9,'not_member')
    a.branch(4,25,8,'has_view'); a.branch(5,25,9,'not_member')
    a.label('has_view'); a.branch(4,14,8,'has_source'); a.branch(5,14,9,'not_member')
    a.label('has_source'); a.lw(10,11,3732); a.branch(5,10,8,'not_member')
    a.lw(10,11,3736); a.branch(5,10,9,'not_member')
    a.label('member'); a.branch(5,6,0,'rank'); a.branch(5,24,5,'not_member')
    a.label('rank'); a.addiu(2,0,2); a.r(0x23,2,2,24); a.addiu(3,0,1); a.jr()
    a.label('not_member'); a.addiu(24,24,1); a.addiu(8,0,2); a.branch(5,24,8,'view')
    a.move(2,0); a.addiu(3,0,1); a.jr()
    a.label('invalid'); a.move(2,0); a.move(3,0); a.jr()
    data=a.finish(); assert len(data)<0x1000; return data


def start_code(code,family):
    a=Assembler(code); save(a); gate(a,'native')
    # Native beam cameras own presentation from reservation through resolution.
    emit_owned_beam(a,'no_beam'); a.jump('suppress'); a.label('no_beam')
    # The original call executes its stack-store delay slot before entering us.
    # a0 points at the caller's three-word request; s0 is its effect body.
    pointer(a,4,12,'suppress'); pointer(a,16,0xAB4,'suppress')
    a.lw(8,4); a.sw(8,29,0x90); a.lw(8,4,4); a.sw(8,29,0x94)
    a.lw(8,4,8); a.sw(8,29,0x98)
    a.li(8,continuity.SCENE_FLAGS); a.lw(8,8); a.i(12,8,8,0x2000); a.branch(5,8,0,'suppress')
    a.call(A(0x12AB10)); a.sw(2,29,0x9C)
    a.call(A(0x23EE08)); a.i(11,8,2,2); a.branch(5,8,0,'side'); a.move(2,0)
    a.label('side'); a.sw(2,29,0xA0)
    a.lw(4,29,0x94); a.move(5,2); a.lw(6,29,0x9C); a.call(PRIORITY)
    a.branch(4,3,0,'suppress'); a.sw(2,29,0xA4)
    a.li(8,CINEMATIC); a.lw(13,8); pointer(a,13,832,'suppress')
    a.lw(8,13,812); a.branch(5,8,0,'suppress')
    a.lw(8,13,704); a.branch(4,8,0,'accept')
    a.lw(8,13,776); a.i(12,8,8,3); a.addiu(9,0,1); a.branch(5,8,9,'accept')
    # An active camera not owned by this addon is a stage/form/throw/intro.
    a.li(8,DIRECTOR); a.lw(12,8); pointer(a,12,28,'suppress')
    a.li(10,CONTROL); a.lw(8,10,16); a.branch(4,8,0,'suppress')
    a.lw(9,12,12); a.branch(4,9,0,'suppress')
    for off,control in ((0,20),(4,24),(8,28)):
        a.lw(8,12,off); a.lw(9,10,control); a.branch(5,8,9,'suppress')
    a.lw(8,13,704); a.lw(9,10,20); a.branch(5,8,9,'suppress')
    a.lw(8,10,16); a.branch(4,8,16,'accept')
    a.lw(4,10,24); a.lw(5,29,0xA0); a.lw(6,29,0x9C); a.call(PRIORITY)
    a.lw(8,29,0xA4); a.r(0x2B,9,2,8); a.branch(4,9,0,'suppress')
    bump(a,48)
    a.label('accept'); a.li(10,CONTROL); a.sw(16,10,16)
    for off,control in ((0x90,20),(0x94,24),(0x98,28)):
        a.lw(8,29,off); a.sw(8,10,control)
    a.addiu(8,0,family); a.sw(8,10,32); bump(a,40)
    a.label('native'); restore(a); a.jump(NATIVE_START)
    a.label('suppress'); bump(a,44); restore(a); a.move(2,0); a.jr()
    data=a.finish(); assert len(data)<0x800; return data


def stop_code(code,family,body,track,row):
    a=Assembler(code); save(a); gate(a,'native')
    # Native beam cameras own presentation from reservation through resolution.
    emit_owned_beam(a,'no_beam'); a.jump('suppress'); a.label('no_beam')
    a.li(8,continuity.SCENE_FLAGS); a.lw(8,8); a.i(12,8,8,0x2000); a.branch(5,8,0,'suppress')
    a.li(10,CONTROL); a.lw(8,10,16); a.branch(5,8,body,'suppress')
    a.lw(8,10,32); a.addiu(9,0,family); a.branch(5,8,9,'suppress')
    pointer(a,body,track+4,'suppress'); a.lw(8,body,track); a.lw(9,10,20)
    a.branch(5,8,9,'suppress'); a.lw(11,body,row); pointer(a,11,4,'suppress')
    a.lw(8,11); a.lw(9,10,24); a.branch(5,8,9,'suppress')
    a.li(8,DIRECTOR); a.lw(12,8); pointer(a,12,28,'suppress')
    for off,control in ((0,20),(4,24),(8,28)):
        a.lw(8,12,off); a.lw(9,10,control); a.branch(5,8,9,'suppress')
    a.li(8,CINEMATIC); a.lw(13,8); pointer(a,13,832,'suppress')
    a.lw(8,13,812); a.branch(5,8,0,'suppress')
    a.lw(8,13,704); a.lw(9,10,20); a.branch(5,8,9,'suppress')
    a.sw(0,10,16); bump(a,56)
    a.label('native'); restore(a); a.jump(NATIVE_STOP)
    a.label('suppress'); bump(a,52); restore(a); a.move(2,0); a.jr()
    data=a.finish(); assert len(data)<0x800; return data


def program():
    return [(START1,start_code(START1,1)),(START2,start_code(START2,2)),
            (STOP1,stop_code(STOP1,1,16,2196,1504)),
            (STOP2,stop_code(STOP2,2,18,2736,96)),(PRIORITY,priority_code())]


def build_memory(ram,config=None,source='<offline-memory>'):
    if len(ram)!=0x08000000: raise ValueError('Requires 128 MiB captured EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count,battle=u(core.ACTORS),u(core.MODE+4),u(team_intro.BATTLE)
    if (count not in ACTOR_COUNTS or u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.MODE+12)!=count
            or not 0x100000<=manager<len(ram)-0x1000 or u(manager)!=2
            or not 0x100000<=battle<len(ram)-300 or u(core.PAIR+4)):
        raise ValueError('Requires captured four/six identities and restored aliases')
    actors=[u(core.POINTERS+4*i) for i in range(count)]
    if len(set(actors))!=count: raise ValueError('Duplicate captured camera actors')
    for i,actor in enumerate(actors):
        if not 0x100000<=actor<len(ram)-0x1600 or u(actor)!=i or u(actor+12)>=12:
            raise ValueError('Captured camera actor identity changed')
        model=u(core.MODELS+4*u(actor+12))
        if not 0x100000<=model<len(ram)-0x1670 or u(model+16)!=u(actor+12):
            raise ValueError('Captured camera model identity changed')
    binding=camera.wrapper()
    if ram[camera.CODE:camera.CODE+len(binding)]!=binding:
        raise ValueError('Complete native camera binding wrapper required')
    for ctrl in (camera.CONTROL,fresh.SUCCESSOR_CONTROL):
        if (u(ctrl),u(ctrl+4))!=(1,manager): raise ValueError('Requires captured cinematic camera and successor ownership')
    _,_,native=elf_reader(elf_path(ROOT))
    parts=program(); header=struct.pack('<4I',MAGIC,manager,count,battle)
    hooks=[(p,struct.pack('<I',(3<<26)|(target>>2))) for p,target,_,_ in HOOKS]
    installed=u(CONTROL)==MAGIC
    if installed:
        if ram[CONTROL:CONTROL+16]!=header: raise ValueError('Camera arbitration belongs to another capture')
        for p,data in parts+hooks:
            if ram[p:p+len(data)]!=data: raise ValueError(f'Camera arbitration changed at {p:08X}')
    else:
        if any(ram[CODE:END]): raise ValueError('Camera arbitration reservation occupied')
        for p,_,target,delay in HOOKS:
            expected=struct.pack('<2I',(3<<26)|(target>>2),delay)
            if native(p,8)!=expected or ram[p:p+8]!=expected:
                raise ValueError(f'Native special camera callsite changed at {p:08X}')
        parts += [(CONTROL,header+bytes(0x100-len(header)))]+hooks
    # Delay slots remain native even when already installed.
    for p,_,_,delay in HOOKS:
        if u(p+4)!=delay: raise ValueError(f'Special camera delay slot changed at {p+4:08X}')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        status='VIEWED-PAIR SPECIAL CAMERA ARBITRATION',
        blocks=[] if installed else [dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in parts],
        limitations=['One native cinematic view; split presentation prioritizes side 0 then side 1.',
                     'Suppressed secondary camera tracks are not restarted after the foreground finishes.',
                     'Owned beam struggles retain their native camera until the actual pair finishes.',
                     'Stage, form, throw and intro camera entrypoints remain native.'])
