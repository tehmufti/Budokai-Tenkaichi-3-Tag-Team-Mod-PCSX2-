"""Use a fighter's own sustained-beam pose only while it assists a clash.

Native clash participants, actions304..306, move slots and collision remain
unchanged. An assistant's sphere/volley/kick firing pose is replaced by its
own reviewed beam pose or native generic364. No tag-rush code is required.
"""
import struct
from native_map import A, CRC, SERIAL, elf_path
from prototype import Assembler, ROOT, elf_reader
import beam_clash as beam
import beam_struggle as assist
import fresh_team_combat as core
import fusion_partner_lifecycle as saved
import beam_pose

CODE, CONTROL, END = 0x07258000, 0x07258F00, 0x07259000
MAGIC=0x42504131
HOOK, NATIVE, FLAGS = A(0x1FB6C8), A(0x1C3E60), A(0x1C4650)
CALL=lambda address:struct.pack('<I',(3<<26)|(address>>2))
NATIVE_HEAD=CALL(NATIVE)+struct.pack('<I',0x0220202D)
INSTALLED_HEAD=CALL(CODE)+NATIVE_HEAD[4:]


def code():
    a=Assembler(CODE);beam.save(a);a.move(16,4)
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'native')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'native')
    a.call(assist.RUNNING);a.branch(4,2,0,'native')
    a.li(8,assist.CONTROL);a.lw(9,8,assist.C['assist']);a.branch(4,9,0,'native')
    saved.pointer(a,16,0x1600,'native')
    # Real clash participants always retain their unmodified native choice.
    a.li(8,beam.ACTORS)
    for off in (0,4):a.lw(9,8,off);a.branch(4,16,9,'native')
    a.move(4,16);a.call(assist.SLOTOF);a.branch(4,2,0,'native');a.move(17,2)
    a.lw(8,17,assist.S['state']);a.li(9,assist.P_PENDING);a.branch(4,8,9,'state_ok')
    a.li(9,assist.P_CONFIRMED);a.branch(5,8,9,'native');a.label('state_ok')
    a.lw(8,17,assist.S['serial']);a.li(9,beam.CONTROL);a.lw(9,9,24);a.branch(5,8,9,'native')
    a.lw(8,16,2376);a.addiu(8,8,-304);a.i(11,9,8,3);a.branch(4,9,0,'native')
    a.lw(8,17,assist.S['phys']);a.li(9,assist.CONTROL);a.lw(9,9,assist.C['count'])
    a.r(0x2B,10,8,9);a.branch(4,10,0,'native');a.lw(9,16);a.branch(5,8,9,'native')
    a.r(0,8,0,8,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,16,'native')
    assist.hp_row(a,12,16,'native',temp=13);a.lw(8,12);a.branch(6,8,0,'native')
    a.lw(8,16,12);a.i(11,9,8,12);a.branch(4,9,0,'native');a.move(21,8)
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(18,8)
    saved.pointer(a,18,0x1700,'native');a.lw(8,18,16);a.branch(5,8,21,'native')
    a.lw(8,18,4);a.branch(4,8,0,'native');a.lw(8,18,8);a.li(9,1);a.branch(5,8,9,'native')
    a.lw(19,18,2348);saved.pointer(a,19,640,'native')
    beam_pose.emit_select(a,18,19,'own');a.branch(1,2,0,'native');a.move(20,2)
    # The native decoder can retarget paired animations. These own poses
    # must not borrow another fighter's model or scratch bank.
    a.move(4,20);a.call(FLAGS);a.li(8,0x20000000);a.r(0x24,8,8,2);a.branch(5,8,0,'native')
    a.i(63,20,29,beam.SAVED.index(5)*8)
    a.label('native');beam.restore(a);a.jump(NATIVE)
    data=a.finish();assert CODE+len(data)<=CONTROL;return data


def build_memory(ram,source='<prepared>'):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if len(ram)<END or u(assist.CONTROL)!=assist.MAGIC or not u(assist.CONTROL+assist.C['assist']):
        return {'blocks':[]}
    manager=u(assist.CONTROL+assist.C['manager'])
    data=code();control=struct.pack('<2I',MAGIC,manager)
    current=bytes(ram[HOOK:HOOK+8]);installed=u(CONTROL)==MAGIC
    if installed:
        if current!=INSTALLED_HEAD or bytes(ram[CODE:CODE+len(data)])!=data or bytes(ram[CONTROL:CONTROL+8])!=control:
            raise ValueError('Beam-assist pose installation changed')
        return {'blocks':[]}
    native=elf_reader(elf_path(ROOT))[2]
    if native(HOOK,8)!=NATIVE_HEAD or current!=NATIVE_HEAD:
        raise ValueError('Native beam-assist pose call changed')
    if any(ram[CODE:END]):raise ValueError('Beam-assist pose reservation is occupied')
    pieces=[(CODE,data),(CONTROL,control),(HOOK,INSTALLED_HEAD[:4])]
    return {'serial':SERIAL,'crc':CRC,'source':str(source),'blocks':[
        {'address':p,'expected_hex':bytes(ram[p:p+len(b)]).hex(),'data_hex':b.hex()}for p,b in pieces]}
