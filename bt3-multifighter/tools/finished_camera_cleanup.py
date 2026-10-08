"""Retire a finished effect camera whose fighter already left its special.

Native 12F720 stops advancing a model-bound track when 206B28 says its owner
is no longer in actions261..306. An interrupted effect can miss its stop, so
the active bit survives forever at the last frame and blocks new forms.
Do not time out arbitrary cinematics: authenticate the director/model/track,
require the actual track end, and preserve every queued special/form.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import special_camera_arbitration as camera
import fresh_team_combat as core
import cinematic_admission as admission
import extra_reload_quiet as reload
import native_preparation as preparation

HOOK, CODE, CLEANUP = A(0x12F720), 0x077FC000, 0x077FC100
CONTROL, END, MAGIC = 0x077FDF00, 0x077FE000, 0x46434331
SAVED = tuple(range(2,26))+(31,)


def cleanup():
    a=Assembler(CLEANUP);a.addiu(29,29,-0xD0)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    core.gate(a,'done');a.move(16,10)
    a.li(17,CONTROL);a.lw(8,17);a.li(9,MAGIC);a.branch(5,8,9,'done')
    a.lw(8,17,4);a.lw(9,28,-22364);a.branch(5,8,9,'done')
    a.lw(8,17,8);a.branch(5,8,16,'done')
    for off in (600,612,628):a.lw(8,9,off);a.branch(5,8,0,'done')
    a.lw(8,9,604);a.lw(9,9,608);a.branch(5,8,9,'done')
    a.li(8,camera.team_intro.BATTLE);a.lw(8,8);a.lw(9,17,12);a.branch(5,8,9,'done')
    a.branch(4,8,0,'done');a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,'done')
    for at in (camera.result_presentation.RESULT,core.PAIR+4,preparation.CONTROL+16):
        a.li(8,at);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,reload.SCENE_FLAGS);a.lw(8,8);a.i(12,8,8,reload.SCENE_RELOAD_MASK);a.branch(5,8,0,'done')
    camera.emit_owned_beam(a,'no_beam');a.jump('done');a.label('no_beam')
    a.li(8,camera.CINEMATIC);a.lw(18,8);camera.pointer(a,18,832,'done')
    a.lw(8,18,812);a.branch(5,8,0,'done')
    a.lw(8,18,776);a.i(12,8,8,3);a.addiu(9,0,1);a.branch(5,8,9,'done')
    a.lw(19,18,704);camera.pointer(a,19,24,'done')
    a.li(8,camera.DIRECTOR);a.lw(20,8);camera.pointer(a,20,28,'done')
    a.lw(8,20);a.branch(5,8,19,'done')
    a.lw(8,20,12);a.addiu(9,0,1);a.branch(5,8,9,'done')
    for off in (16,20):a.lw(8,20,off);a.branch(5,8,0,'done')
    a.lw(21,20,4);a.i(11,8,21,12);a.branch(4,8,0,'done')
    a.lw(8,20,24);a.branch(5,8,21,'done')
    a.li(8,core.MODELS);a.r(0,9,0,21,2);a.r(0x2D,8,8,9);a.lw(22,8)
    camera.pointer(a,22,0x1670,'done');a.lw(8,22,16);a.branch(5,8,21,'done')
    a.lw(8,18,772);a.branch(5,8,22,'done')
    a.lw(8,18,768);a.branch(5,8,0,'done')
    # Positive finite IEEE floats sort as unsigned words. No FPU state changes.
    a.lw(8,19,20);a.li(10,0x7F800000);a.branch(6,8,0,'done')
    a.r(0x2B,9,8,10);a.branch(4,9,0,'done')
    a.lw(9,18,752);a.r(0x2B,11,9,10);a.branch(4,11,0,'done')
    a.r(0x2B,11,9,8);a.branch(5,11,0,'done')
    a.li(22,core.POINTERS);a.move(23,0);a.move(24,0)
    a.label('scan');a.lw(25,22);camera.pointer(a,25,0x1600,'done')
    # A form could replace the camera later in this same battle update.
    for off in admission.ACTION_FIELDS:
        a.lw(8,25,off);a.addiu(9,8,-236);a.i(11,9,9,8);a.branch(5,9,0,'done')
    a.lw(8,25,12);a.branch(5,8,21,'next')
    a.addiu(24,24,1)
    for off in admission.ACTION_FIELDS:
        a.lw(8,25,off);a.addiu(9,8,-253);a.i(11,9,9,63);a.branch(5,9,0,'done')
    a.label('next');a.addiu(22,22,4);a.addiu(23,23,1);a.branch(5,23,16,'scan')
    a.addiu(8,0,1);a.branch(5,24,8,'done')
    # Use the game's stop operation (sets finish bit, releases director).
    a.call(camera.NATIVE_STOP)
    a.lw(8,17,16);a.addiu(8,8,1);a.sw(8,17,16);a.sw(19,17,20);a.sw(21,17,24)
    a.label('done')
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0xD0);a.jr()
    data=a.finish();assert len(data)<CONTROL-CLEANUP;return data


def wrapper(native):
    a=Assembler(CODE);a.addiu(29,29,-16);a.i(63,31,29,0);a.call(CLEANUP)
    a.i(55,31,29,0);a.addiu(29,29,16)
    for word in struct.unpack('<2I',native(HOOK,8)):a.emit(word)
    a.jump(HOOK+8);data=a.finish();assert len(data)<CLEANUP-CODE;return data


def build_memory(ram,source='<prepared>'):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    if camera.build_memory(ram,source=source)['blocks']:raise ValueError('Install camera arbitration first')
    native=elf_reader(elf_path(ROOT))[2]
    for p,n in ((camera.NATIVE_STOP,0x38),(A(0x23DCB8),0x28)):
        if ram[p:p+n]!=native(p,n):raise ValueError('Native camera stop changed')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    header=struct.pack('<4I',MAGIC,u(core.ACTORS),u(core.MODE+4),u(camera.team_intro.BATTLE))
    hook=struct.pack('<2I',(2<<26)|(CODE>>2),0)
    installed=u(CONTROL)==MAGIC
    parts=[(CODE,wrapper(native)),(CLEANUP,cleanup()),(CONTROL,header),(HOOK,hook)]
    if installed:
        for p,data in parts:
            if ram[p:p+len(data)]!=data:raise ValueError('Finished camera cleanup changed')
        return dict(blocks=[])
    if any(ram[CODE:END]) or ram[HOOK:HOOK+8]!=native(HOOK,8):
        raise ValueError('Finished camera cleanup reservation or native update changed')
    return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in parts])
