"""Share idle native character-voice streams with captured extra fighters.

The original character/language file selection and spatial attenuation remain
native. Extras never interrupt an occupied stream. Leader requests retain
priority; player stop/status/fade operations only affect their own stream.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

import fresh_team_combat as core
import fresh_team_safety as safety
import extra_positional_audio as positional
import battle_mode_policy as policy
from prototype import Assembler,ROOT,elf_reader

CODE,QUEUE,PLAY,OPERATIONS,CONTROL,END=0x072E0000,0x072E0000,0x072E1000,0x072E2000,0x072EF000,0x072F0000
MAGIC=0x56584331
VOICE_CALL=A(0x1DA588)
PLAY_ENTRY=A(0x265850)
OPS=((A(0x265F40),0),(A(0x265F58),0),(A(0x265F70),1),(A(0x265F88),0))
PRIOR_PLAY=0x07382200
PRIOR_FADE=0x07382800
OWNERS=0x10
NATIVE=elf_reader(elf_path(ROOT))[2]
SAVED=tuple(range(2,19))+(31,)
FRAME=0x90


def save(a):
    a.addiu(29,29,-FRAME)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)


def restore(a):
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,FRAME)


def argument(a,reg,value):a.i(63,value,29,8*SAVED.index(reg))


def gate(a,fail):
    core.gate(a,fail)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail)


def count(a,off):
    a.li(8,CONTROL);a.lw(9,8,off);a.addiu(9,9,1);a.sw(9,8,off)


def queue_code():
    a=Assembler(QUEUE);save(a);gate(a,'prior')
    # s0 is the actual actor pointer preserved by native1DA548. Unlike its
    # first word, that pointer stays physical inside a private AI role alias.
    a.li(8,core.POINTERS);a.li(11,CONTROL+0x40);a.move(12,0)
    a.label('scan');a.lw(9,8);a.branch(4,9,16,'found')
    a.addiu(8,8,4);a.addiu(11,11,4);a.addiu(12,12,1)
    a.r(0x2B,9,12,10);a.branch(5,9,0,'scan');a.jump('prior')
    a.label('found');a.lw(9,11);a.branch(5,9,16,'prior')
    a.i(11,9,12,2);a.branch(5,9,0,'prior')
    argument(a,5,12);a.addiu(9,0,5);argument(a,6,9)
    count(a,0x20);restore(a)
    # Only this audited character-voice call bypasses generic extra suppression.
    # Native queue retains its four-request budget and positional volume input.
    for word in struct.unpack('<2I',NATIVE(positional.HOOK,8)):a.emit(word)
    a.jump(positional.HOOK+8)
    a.label('prior');restore(a);a.jump(positional.HOOK)
    return a.finish()


def blockers(a,channel,fail):
    # Exact native265850 ->259E20 admission for voice channel4/5.
    a.addiu(8,channel,-4);a.r(0,8,0,8,3);a.li(9,A(0x334788));a.r(0x2D,8,8,9)
    a.lw(9,8);a.branch(5,9,0,fail);a.lw(9,8,4);a.branch(5,9,0,fail)


def play_code():
    a=Assembler(PLAY);save(a);gate(a,'prior')
    a.i(11,8,4,4);a.branch(5,8,0,'prior')
    a.i(11,8,4,6);a.branch(5,8,0,'leader')
    a.addiu(16,4,-4);a.r(0x2B,8,16,10);a.branch(4,8,0,'drop')
    a.addiu(16,16,1)  # owner = physical ID + 1
    # Reuse the speaker's existing stream first. It can replace its own line.
    for slot in range(2):
        a.li(8,CONTROL+OWNERS+4*slot);a.lw(9,8)
        a.branch(4,9,16,f'choose{slot}')
    # Otherwise only a completed/idle stream may be borrowed. Leader and other
    # NPC lines keep playing; there is no stop call or asset IO on this path.
    for slot in range(2):
        a.addiu(17,0,4+slot);blockers(a,17,f'next{slot}')
        a.move(4,17);a.call(A(0x265B48));a.branch(5,2,0,f'choose{slot}')
        a.label(f'next{slot}')
    count(a,0x28);a.jump('drop')
    for slot in range(2):
        a.label(f'choose{slot}');a.addiu(17,0,4+slot)
        blockers(a,17,'drop')
        a.li(8,CONTROL+OWNERS+4*slot);a.sw(16,8);argument(a,4,17)
        count(a,0x24);a.jump('prior')
    a.label('leader');a.move(17,4);blockers(a,17,'prior')
    a.addiu(9,17,-3);a.addiu(8,17,-4);a.r(0,8,0,8,2)
    a.li(11,CONTROL+OWNERS);a.r(0x2D,8,8,11);a.sw(9,8)
    a.label('prior');restore(a);a.jump(PRIOR_PLAY)
    a.label('drop');restore(a);a.jr()
    return a.finish()


def operation_code(index):
    entry,missing=OPS[index];base=OPERATIONS+0x400*index
    a=Assembler(base);save(a);gate(a,'native')
    a.move(16,4)
    # Native actor operations may execute during an AI role alias.
    a.i(11,8,16,2);a.branch(4,8,0,'physical')
    a.li(8,core.PAIR);a.lw(9,8,4);a.branch(4,9,0,'physical')
    a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(16,8,16)
    a.label('physical');a.r(0x2B,8,16,10);a.branch(4,8,0,'missing')
    a.addiu(16,16,1)
    for slot in range(2):
        a.li(8,CONTROL+OWNERS+4*slot);a.lw(9,8)
        a.branch(4,9,16,f'found{slot}')
        # Pre-install leader streams have no ownership record yet.
        a.branch(5,9,0,f'next{slot}');a.addiu(9,0,slot+1)
        a.branch(4,9,16,f'found{slot}');a.label(f'next{slot}')
    a.jump('missing')
    for slot in range(2):
        a.label(f'found{slot}');a.addiu(9,0,slot);argument(a,4,9);a.jump('native')
    a.label('missing');restore(a);a.addiu(2,0,missing);a.jr()
    a.label('native');restore(a)
    if entry==A(0x265F88):a.jump(PRIOR_FADE)
    else:
        for word in struct.unpack('<2I',NATIVE(entry,8)):a.emit(word)
        a.jump(entry+8)
    return a.finish()


def pieces():
    return [(QUEUE,queue_code()),(PLAY,play_code())]+[(OPERATIONS+0x400*i,operation_code(i)) for i in range(len(OPS))]


def build_memory(ram,source='<prepared-match>',settings=None):
    if len(ram)!=0x8000000:raise ValueError('Requires 128 MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count_=u(core.ACTORS),u(core.MODE+4)
    if count_ not in policy.ACTOR_COUNTS or u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.MODE+12)!=count_ or u(core.PAIR+4):
        raise ValueError('Requires active captured fighters outside AI aliases')
    if not 0x100000<=manager<len(ram)-640 or u(manager)!=2:raise ValueError('Invalid native actor manager')
    actors=[u(core.POINTERS+4*i) for i in range(count_)]
    if len(set(actors))!=count_ or any(not 0x100000<=p<len(ram)-0x1600 or u(p)!=i for i,p in enumerate(actors)):
        raise ValueError('Invalid physical actor capture')
    positional.dependencies(ram)
    hooks=[(VOICE_CALL,struct.pack('<I',(3<<26)|(QUEUE>>2))),
           (PLAY_ENTRY,struct.pack('<2I',(2<<26)|(PLAY>>2),0))]
    hooks += [(entry,struct.pack('<2I',(2<<26)|((OPERATIONS+0x400*i)>>2),0)) for i,(entry,_) in enumerate(OPS)]
    dependencies=[(positional.HOOK,struct.pack('<2I',(2<<26)|(positional.CODE>>2),0)),
                  (positional.CODE,positional.payload()),
                  (PRIOR_PLAY,safety.scalar_code(PLAY_ENTRY,PRIOR_PLAY,6,False,NATIVE(PLAY_ENTRY,8))),
                  (PRIOR_FADE,safety.scalar_code(A(0x265F88),PRIOR_FADE,2,False,NATIVE(A(0x265F88),8))),
                  (A(0x1DA548),NATIVE(A(0x1DA548),VOICE_CALL-A(0x1DA548))),
                  (VOICE_CALL+4,NATIVE(VOICE_CALL+4,A(0x1DA5A8)-VOICE_CALL-4)),
                  (PLAY_ENTRY+8,NATIVE(PLAY_ENTRY+8,0x120-8)),
                  (A(0x265E38),NATIVE(A(0x265E38),0x108)),(A(0x259E20),NATIVE(A(0x259E20),0x30))]
    for entry,cave,size in ((A(0x265970),0x07382400,0xB0),(A(0x265B18),0x07382600,0x30)):
        dependencies += [(entry,struct.pack('<2I',(2<<26)|(cave>>2),0)),
                         (cave,safety.scalar_code(entry,cave,6,False,NATIVE(entry,8))),
                         (entry+8,NATIVE(entry+8,size-8))]
    dependencies += [(A(0x265B48),NATIVE(A(0x265B48),0x38)),(A(0x265C00),NATIVE(A(0x265C00),0x80))]
    for entry,_ in OPS:dependencies.append((entry+8,NATIVE(entry+8,0x10)))
    for at,data in dependencies:
        if ram[at:at+len(data)]!=data:raise ValueError(f'Voice dependency changed:{at:08X}')
    import mod_settings
    enabled=mod_settings.validate_settings(settings or {})['extra_character_voices']
    programs=pieces()
    if u(CONTROL)==MAGIC:
        if any(ram[p:p+len(data)]!=data for p,data in programs+hooks) or (u(CONTROL+4),u(CONTROL+8))!=(manager,count_):
            raise ValueError('Installed voice arbiter changed')
        if any(u(CONTROL+0x40+4*i)!=p for i,p in enumerate(actors)):raise ValueError('Voice actor capture changed')
        if not enabled:raise ValueError('Start a new match to disable extra character voices')
        programs=[]
    else:
        originals=[(VOICE_CALL,NATIVE(VOICE_CALL,4)),(PLAY_ENTRY,struct.pack('<2I',(2<<26)|(PRIOR_PLAY>>2),0))]
        originals += [(entry,struct.pack('<2I',(2<<26)|(PRIOR_FADE>>2),0) if entry==A(0x265F88) else NATIVE(entry,8)) for entry,_ in OPS]
        for at,data in originals:
            if ram[at:at+len(data)]!=data:raise ValueError(f'Unexpected voice hook:{at:08X}')
        if any(ram[CODE:END]):raise ValueError('Voice arbiter reservation occupied')
        if not enabled:
            return dict(serial=SERIAL,crc=CRC,source=str(source),
                        status='EXTRA CHARACTER VOICES DISABLED BY SETTINGS',blocks=[])
        control=bytearray(0x100);struct.pack_into('<3I',control,0,MAGIC,manager,count_)
        for i,p in enumerate(actors):struct.pack_into('<I',control,0x40+4*i,p)
        programs += [(CONTROL,bytes(control))]+hooks
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                status='EXTRA CHARACTER VOICES THROUGH IDLE NATIVE STREAMS; USER AUDIO TEST NEEDED',
                blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in programs],
                limits=['Two character voice streams remain; extra lines are skipped while both are occupied.',
                        'Original leaders can interrupt extra lines. Native language, character IDs, attenuation and request budget are preserved.'])
