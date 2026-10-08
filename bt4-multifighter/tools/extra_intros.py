"""Optional sequential extra intros within the native held dialogue phase.

Use generic native lines/animations against the existing formation. No actor ID
aliasing, resource reload, second FIGHT banner, or new battle phase is required.
"""
from native_map import A
import struct
from prototype import Assembler
import extra_cell_absorption as elf
import fusion_partner_lifecycle as saved
import fresh_team_combat as core
import team_intro as intro
import team_start_gate as start
import battle_mode_policy as policy

CODE, MODEL, CAMERA, GATE = 0x07434000,0x07435000,0x07436000,0x07437000
OLD,CONTROL,END = 0x07438000,0x07439000,0x0743A000
PRESET_READY,PRESET_OLD,PRESET_END=0x0743A000,0x0743B000,0x0743C000
CLEANUP,OLD_CLEANUP,CLEANUP_HOOK=0x07438100,0x07438A00,A(0x2171A0)
HOOK,MAGIC = A(0x217410),0x58494E31
NATIVE=elf.NATIVE
MODELS=(A(0x217480),A(0x2174E0))
CAMERAS=(A(0x217468),A(0x2174C8))


def gate_code():
    a=Assembler(GATE);core.gate(a,'no');a.li(8,CONTROL)
    a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no');a.lw(9,8,12);a.branch(4,9,0,'no')
    a.li(8,core.PAIR+4);a.lw(9,8);a.branch(5,9,0,'no')
    a.li(8,intro.CONTROL);a.lw(9,8);a.addiu(12,0,1);a.branch(5,9,12,'no')
    a.lw(9,8,20);a.branch(5,9,12,'no');a.lw(9,8,8);a.branch(5,9,11,'no')
    a.lw(9,8,16);a.li(8,intro.BATTLE);a.lw(8,8);a.branch(5,8,9,'no')
    a.lw(9,8);a.branch(5,9,12,'no')
    a.li(8,start.CONTROL);a.lw(9,8);a.branch(5,9,12,'no')
    a.lw(9,8,8);a.branch(5,9,11,'no');a.lw(9,8,4);a.branch(5,9,0,'no')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr()
    return a.finish()


def identity(a,physical,fail):
    """Return actor17/model18/mid19/row20 for a captured physical index."""
    a.r(0x2B,8,physical,10);a.branch(4,8,0,fail)
    a.r(0,8,0,physical,4);a.li(20,CONTROL+0x100);a.r(0x21,20,20,8)
    a.lw(17,20);a.r(0,8,0,physical,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9)
    a.lw(8,8);a.branch(5,8,17,fail);a.lw(8,17);a.branch(5,8,physical,fail)
    a.lw(19,20,4);a.lw(8,17,12);a.branch(5,8,19,fail)
    a.r(0,8,0,19,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(18,8)
    a.lw(8,20,8);a.branch(5,8,18,fail);a.lw(8,18,16);a.branch(5,8,19,fail)
    a.lw(8,18,4);a.addiu(9,0,1);a.branch(5,8,9,fail)


def sequence_code():
    a=Assembler(CODE);saved.save(a);a.move(16,4);a.call(GATE);a.branch(4,2,0,'native')
    a.li(21,CONTROL);a.lw(8,21,28);a.branch(5,8,0,'native')
    a.li(8,intro.BATTLE);a.lw(8,8);a.addiu(8,8,4);a.branch(5,8,16,'native')
    a.lw(8,21,16);a.branch(5,8,0,'extra')
    a.lw(8,16,4);a.addiu(9,0,4);a.branch(5,8,9,'native')
    for off in range(8,32,4):a.lw(8,16,off);a.sw(8,21,0x40+off)
    a.addiu(8,0,1);a.sw(8,21,16);a.jump('next')
    a.label('extra');a.lw(8,16,4);a.addiu(9,0,2);a.branch(5,8,9,'native')
    # Restore the finished speaker's normal model animation bank. Do not leave
    # a former speaker frozen in the generic introduction pose during combat.
    a.lw(22,21,24);identity(a,22,'next')
    a.move(4,18);a.move(5,0);a.addiu(6,0,-1);a.call(A(0x24F5D8))
    a.lw(4,21,24);a.call(A(0x265F40))
    a.lw(4,21,24);a.call(A(0x209F20))
    a.label('next');a.lw(22,21,20);a.lw(10,21,8)
    a.label('scan');a.r(0x2B,8,22,10);a.branch(4,8,0,'finished')
    a.addiu(8,22,1);a.sw(8,21,20)
    a.lw(8,21,32);a.addiu(9,0,1);a.r(4,9,22,9);a.r(0x24,8,8,9);a.branch(4,8,0,'skip')
    identity(a,22,'skip')
    a.sw(22,21,24);a.sw(22,16,8);a.lw(8,20,12);a.sw(8,16,0x18)
    a.sw(0,16,0x10);a.sw(0,16,4);a.jump('native')
    a.label('skip');a.addiu(22,22,1);a.jump('scan')
    a.label('finished')
    for off in range(8,32,4):a.lw(8,21,0x40+off);a.sw(8,16,off)
    a.addiu(8,0,4);a.sw(8,16,4);a.addiu(8,0,1);a.sw(8,21,28)
    a.sw(0,21,16)
    a.label('native');saved.restore(a);a.jump(OLD)
    data=a.finish();assert len(data)<MODEL-CODE;return data


def bridge(base,camera=False):
    a=Assembler(base);saved.save(a);a.move(22,4)
    a.i(11,8,22,2);a.branch(5,8,0,'native')
    a.call(GATE);a.branch(4,2,0,'missing');identity(a,22,'missing')
    if camera:
        a.i(31,19,29,saved.OFFSETS[4]);saved.restore(a);a.jump(A(0x23DE60))
    else:
        a.i(31,19,29,saved.OFFSETS[2]);saved.restore(a);a.jr()
    a.label('native');saved.restore(a);a.jump(A(0x23DE60) if camera else A(0x12B1D0))
    # A stale extra must never index the two native scene records. This branch
    # is also safe when an external scene transition cancels the held intro.
    a.label('missing')
    if not camera:a.i(31,0,29,saved.OFFSETS[2])
    saved.restore(a);a.jr()
    data=a.finish();assert len(data)<0x1000;return data


def cleanup_code():
    a=Assembler(CLEANUP);saved.save(a);a.call(GATE);a.branch(4,2,0,'native')
    a.li(21,CONTROL);a.lw(8,21,16);a.branch(4,8,0,'native')
    a.lw(22,21,24);identity(a,22,'restore')
    a.move(4,18);a.move(5,0);a.addiu(6,0,-1);a.call(A(0x24F5D8))
    a.lw(4,21,24);a.call(A(0x265F40))
    a.lw(4,21,24);a.call(A(0x209F20))
    a.label('restore');a.li(8,intro.BATTLE);a.lw(16,8);a.addiu(16,16,4)
    for off in range(8,32,4):a.lw(8,21,0x40+off);a.sw(8,16,off)
    a.sw(0,21,16);a.addiu(8,0,1);a.sw(8,21,28)
    a.label('native');saved.restore(a);a.jump(OLD_CLEANUP)
    data=a.finish();assert CLEANUP+len(data)<OLD_CLEANUP;return data


def pieces():
    old=NATIVE(HOOK,8)+struct.pack('<2I',(2<<26)|((HOOK+8)>>2),0)
    old_cleanup=NATIVE(CLEANUP_HOOK,8)+struct.pack('<2I',(2<<26)|((CLEANUP_HOOK+8)>>2),0)
    return [(CODE,sequence_code()),(GATE,gate_code()),(MODEL,bridge(MODEL)),
        (CAMERA,bridge(CAMERA,True)),(OLD,old),
        (CLEANUP,cleanup_code()),(OLD_CLEANUP,old_cleanup),
        (CLEANUP_HOOK,struct.pack('<2I',(2<<26)|(CLEANUP>>2),0)),
        (HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))]+[
        (p,struct.pack('<I',(3<<26)|(target>>2)))for sites,target in ((MODELS,MODEL),(CAMERAS,CAMERA))for p in sites]


def build_memory(ram,settings=None,present_mask=None,source='<offline>'):
    import mod_settings
    enabled=mod_settings.validate_settings(settings or {})['extra_character_intros']
    if not enabled:return dict(source=str(source),blocks=[])
    if len(ram)!=0x8000000:raise ValueError('Extra intros require128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in policy.ACTOR_COUNTS or u(intro.CONTROL)!=1 or u(start.CONTROL)!=1:
        raise ValueError('Extra intros require an unreleased native dialogue sequence')
    if any(ram[CODE:END]):raise ValueError('Extra intro reservation occupied')
    if present_mask is None:present_mask=(1<<count)-1
    if type(present_mask)is not int or not 0<=present_mask<(1<<count):raise ValueError('Invalid intro presence mask')
    for p,n in ((HOOK,0x110),(A(0x217520),0x188),(A(0x23DE60),0x78),(CLEANUP_HOOK,8)):
        if ram[p:p+n]!=NATIVE(p,n):raise ValueError(f'Native extra-intro dependency changed{p:08X}')
    data=bytearray(0x200);struct.pack_into('<9I',data,0,MAGIC,manager,count,1,0,2,0,0,present_mask)
    for i in range(count):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<=len(ram)-0x1600 or u(actor)!=i:raise ValueError('Intro actor identity changed')
        mid=u(actor+12)
        if mid>=12:raise ValueError('Intro model ID changed')
        model=u(core.MODELS+4*mid)
        if not 0x100000<=model<=len(ram)-0x1670 or u(model+16)!=mid:raise ValueError('Intro model identity changed')
        struct.pack_into('<4I',data,0x100+16*i,actor,mid,model,u(model+12))
    return dict(source=str(source),blocks=[dict(address=p,expected_hex=bytes(ram[p:p+len(d)]).hex(),data_hex=d.hex())
        for p,d in pieces()+[(CONTROL,bytes(data))]],behavior='Generic native extra introductions after both leaders; all combat stays held until completion.')


def preset_ready_code(previous):
    import preset_cosmetics as preset
    a=Assembler(PRESET_READY);saved.save(a);core.gate(a,'tail')
    a.li(16,preset.CONTROL);a.lw(8,16,4);a.li(9,preset.MAGIC);a.branch(5,8,9,'tail')
    a.lw(8,16,8);a.lw(9,28,-22364);a.branch(5,8,9,'tail')
    a.lw(8,16);a.addiu(11,0,5);a.branch(5,8,11,'tail')
    a.li(17,intro.CONTROL);a.lw(8,17);a.addiu(11,0,1);a.branch(5,8,11,'tail')
    a.lw(8,17,8);a.branch(5,8,9,'tail');a.lw(8,17,12);a.branch(5,8,10,'tail')
    a.lw(8,17,20);a.branch(5,8,0,'playing');a.sw(11,17,4);a.jump('tail')
    a.label('playing');a.li(8,intro.BATTLE);a.lw(8,8);a.lw(8,8);a.addiu(9,0,3)
    a.branch(5,8,9,'tail');a.sw(11,16,16)
    a.label('tail');saved.restore(a);a.jump(previous)
    result=a.finish();assert len(result)<PRESET_OLD-PRESET_READY;return result


def preset_chain_head(ram, *, check_hook=True):
    """Only the exact verified participation wrapper may precede a preset intro."""
    import team_participation as part
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if check_hook and ram[start.HOOK:start.HOOK+8]!=struct.pack('<2I',(2<<26)|(part.FRAME>>2),0):
        raise ValueError('Preset intro participation hook changed')
    template=part.frame_code(0)
    offsets=[i for i in range(0,len(template),4)if struct.unpack_from('<I',template,i)[0]==3<<26]
    if len(offsets)!=1:raise ValueError('Preset frame continuation shape changed')
    word=u(part.FRAME+offsets[0]);previous=(word&0x3FFFFFF)<<2
    if word>>26!=3 or not 0x07000000<=previous<0x08000000:
        raise ValueError('Preset frame continuation changed')
    if ram[part.FRAME:part.FRAME+len(template)]!=part.frame_code(previous):
        raise ValueError('Preset participation body changed')
    return part.FRAME


def validate_preset_ready(ram,manager,count):
    """Validate the precise inner frame chain when revival wraps this gate."""
    import preset_cosmetics as preset
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    previous=preset_chain_head(ram,check_hook=False)
    if (u(preset.CONTROL+4),u(preset.CONTROL+8),u(preset.CONTROL+12))!=(preset.MAGIC,manager,count):
        raise ValueError('Preset introduction initializer identity changed')
    if (u(intro.CONTROL+8),u(intro.CONTROL+12))!=(manager,count):
        raise ValueError('Preset introduction belongs to another match')
    for at,data in ((PRESET_READY,preset_ready_code(intro.CODE)),(intro.CODE,intro.payload(previous))):
        if ram[at:at+len(data)]!=data:raise ValueError('Preset introduction frame chain changed')
    return PRESET_READY


def prepare_preset_memory(ram,settings=None,source='<preset>'):
    """Give immutable quick-play presets the same held intro option."""
    import mod_settings
    import preset_cosmetics as preset
    import team_intro_camera
    from fresh_team_trainer import compose_manifests
    if not mod_settings.validate_settings(settings or {})['extra_character_intros']:
        return dict(source=str(source),blocks=[])
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(preset.CONTROL+4)!=preset.MAGIC or u(preset.CONTROL+16)!=1:
        raise ValueError('Preset intro requires the verified unreleased preset gate')
    if any(ram[PRESET_READY:PRESET_END]):raise ValueError('Preset intro reservation occupied')
    previous=preset_chain_head(ram)
    def hold(view):
        return dict(blocks=[dict(address=p,expected_hex=bytes(view[p:p+4]).hex(),data_hex='00000000')
            for p in (start.REQUEST,preset.CONTROL+16)])
    def ready(view):
        code=intro.payload(previous)
        if view[intro.CODE:intro.CODE+len(code)]!=code or view[start.HOOK:start.HOOK+8]!=struct.pack('<2I',(2<<26)|(intro.CODE>>2),0):
            raise ValueError('Preset intro chain changed')
        blocks=[(PRESET_READY,preset_ready_code(intro.CODE)),
            (start.HOOK,struct.pack('<2I',(2<<26)|(PRESET_READY>>2),0))]
        return dict(blocks=[dict(address=p,expected_hex=bytes(view[p:p+len(d)]).hex(),data_hex=d.hex())for p,d in blocks])
    return compose_manifests(ram,[hold,lambda r:intro.build_memory(r,source=source,preset=True),
        lambda r:team_intro_camera.build_memory(r,source=source),ready])
