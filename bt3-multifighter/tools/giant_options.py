"""Opt-in larger native giants, scoped to the captured actor/model pair.

Size class comes from the live model's parameter block, so transformations,
body exchanges and compatible modded character IDs follow their current body.
The uniform skeleton transform also feeds native limb collision and effects.
Cached body dimensions are rebuilt from source data (never compounded).
Authored paired scenes keep their native animation clock.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
import math
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import battle_mode_policy as modes
import mod_settings

BASE, END = 0x070F0000, 0x07100000
MODEL, ACTOR = BASE, BASE+0x400
SCALE, SPEED, DAMAGE, ARMOR = BASE+0x800,BASE+0x1800,BASE+0x2000,BASE+0x2800
TAILS, CONTROL = BASE+0x3000,BASE+0xF000
CAMERA = BASE+0x3500
LOCKED_CAMERA = BASE+0x4000
ROOT_MOTION = BASE+0x4800
ATTACK_SPHERE = BASE+0x5000
SPHERE_CALL = A(0x24DF3C)
ATTACK_BOX,ATTACK_BASIS=BASE+0x5400,BASE+0x5800
BOX_CALL,BASIS_CALL=A(0x24E01C),A(0x24DFD4)
HURT_BOX,HURT_CALL=BASE+0x6000,A(0x24DA6C)
MAGIC=0x474E5431
NATIVE=elf_reader(elf_path(ROOT))[2]
HOOKS=((A(0x24E2B0),SCALE),(A(0x24D410),SPEED),(A(0x20D2C0),DAMAGE),
       (A(0x1C6268),CAMERA),(A(0x1C5C80),LOCKED_CAMERA),(A(0x1D70E8),ROOT_MOTION))
ARMOR_CALL=A(0x1C9D84)  # a0 attacker, s2 actual contacted defender
SAVED=tuple(range(2,16))+(24,25,31)
FRAME=0xE0


def jump(p,link=False):return struct.pack('<2I',((3 if link else 2)<<26)|(p>>2),0)


def save(a):
    a.addiu(29,29,-FRAME)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    for i in range(4):a.i(57,i,29,0x90+i*4)
    a.r(16,8,0);a.i(63,8,29,0xA0);a.r(18,8,0);a.i(63,8,29,0xA8)


def restore(a,result=False):
    a.i(55,8,29,0xA0);a.r(17,0,8);a.i(55,8,29,0xA8);a.r(19,0,8)
    for i in range(4):a.i(49,i,29,0x90+i*4)
    for i,r in enumerate(SAVED):
        if not (result and r in (2,3)):a.i(55,r,29,i*8)
    a.addiu(29,29,FRAME)


def fop(a,fn,d,s,t=0):a.emit((17<<26)|(16<<21)|(t<<16)|(s<<11)|(d<<6)|fn)


def pointer(a,r,tail,fail):
    a.i(12,9,r,3);a.branch(5,9,0,fail)
    a.li(9,0x100000);a.r(0x2B,9,r,9);a.branch(5,9,0,fail)
    a.li(9,0x08000000-tail);a.r(0x2B,9,r,9);a.branch(4,9,0,fail)


def model_code():
    # a0 model -> v0 owning captured actor, or zero. No ID/name heuristics.
    a=Assembler(MODEL);core.gate(a,'no');a.move(15,10)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,15,'no');a.lw(9,8,12);a.branch(4,9,0,'no')
    pointer(a,4,0x1670,'no');a.lw(12,4,16);a.i(11,9,12,modes.ENGINE_ACTORS);a.branch(4,9,0,'no')
    a.r(0,9,0,12,2);a.li(11,core.MODELS);a.r(0x2D,11,11,9);a.lw(11,11);a.branch(5,11,4,'no')
    a.lw(11,4,2332);pointer(a,11,0x100,'no');a.i(36,9,11,2);a.addiu(11,0,4);a.branch(5,9,11,'no')
    a.li(13,core.POINTERS);a.move(14,0)
    a.label('scan');a.lw(2,13);a.branch(4,2,0,'next');a.lw(9,2,12);a.branch(4,9,12,'yes')
    a.label('next');a.addiu(13,13,4);a.addiu(14,14,1);a.branch(5,14,15,'scan')
    a.label('no');a.move(2,0);a.label('yes');a.jr();return a.finish()


def actor_code():
    # Only captured pointers may be dereferenced as actors. Works under aliases.
    a=Assembler(ACTOR);core.gate(a,'no');a.li(11,core.POINTERS);a.move(12,0)
    a.label('scan');a.lw(9,11);a.branch(4,9,4,'found');a.addiu(11,11,4);a.addiu(12,12,1)
    a.branch(5,12,10,'scan');a.jump('no')
    a.label('found');a.lw(9,4,12);a.i(11,10,9,modes.ENGINE_ACTORS);a.branch(4,10,0,'no')
    a.r(0,9,0,9,2);a.li(10,core.MODELS);a.r(0x2D,10,10,9);a.lw(4,10);a.jump(MODEL)
    a.label('no');a.move(2,0);a.jr();return a.finish()


def scale_code(anchored=True,ee_compare=True):
    a=Assembler(SCALE);save(a);a.call(MODEL);a.branch(4,2,0,'native')
    a.lw(4,29,SAVED.index(4)*8);a.li(8,CONTROL);a.i(49,1,8,16)
    # Start with the native per-frame scale; do not replace scripted scaling.
    a.lw(9,4,2592);a.sw(9,29,0xB0);a.i(49,0,4,2592);fop(a,2,0,0,1);a.i(57,0,4,2592)
    if anchored:
        # 1D7198 subtracts the unscaled animation root from the actor anchor.
        # Scale that subtraction as well, otherwise the root offset reappears
        # as translation and accumulates every time native motion reads it.
        for i,off in enumerate((0,4,8)):
            a.lw(9,4,2384+off);a.sw(9,29,0xB4+4*i)
            a.i(49,2,2,16+off);a.i(49,3,2,48+off);fop(a,0,2,2,3)
            a.i(49,0,4,2384+off);fop(a,1,0,0,2);fop(a,2,0,0,1);fop(a,0,0,0,2)
            a.i(57,0,4,2384+off)
    a.lw(11,4,64);pointer(a,11,40,'matrix')
    for src,dst in ((24,4084),(28,4088),(32,4092),(36,4096)):
        a.i(49,0,11,src);fop(a,2,0,0,1);a.i(57,0,4,dst)
    a.lw(11,4,84);pointer(a,11,8,'matrix');a.i(49,0,11,4);fop(a,2,0,0,1);a.i(57,0,4,4080)
    a.lw(11,4,2332);a.i(49,0,11,8)
    # Ground-contact sphere uses param+8 when positive, otherwise 2*body radius.
    a.emit((17<<26)|(4<<21)|(0<<16)|(2<<11));fop(a,0x34 if ee_compare else 0x3C,0,2,0)
    a.branch(17,8,1,'sphere');a.i(49,0,4,4096);fop(a,0,0,0,0);a.i(57,0,4,4100);a.jump('matrix')
    a.label('sphere');fop(a,2,0,0,1);a.i(57,0,4,4100)
    a.label('matrix');a.call(TAILS)
    a.lw(8,29,SAVED.index(4)*8);a.lw(9,29,0xB0);a.sw(9,8,2592)
    if anchored:
        for i,off in enumerate((0,4,8)):a.lw(9,29,0xB4+4*i);a.sw(9,8,2384+off)
    restore(a,result=True);a.jr()
    a.label('native');restore(a);a.jump(TAILS)
    return a.finish()


def root_motion_code():
    """Feed native physics the unscaled root displacement; keep draw/collision large."""
    a=Assembler(ROOT_MOTION);save(a);a.call(ACTOR);a.branch(4,2,0,'native')
    a.sw(4,29,0xC0);a.li(8,CONTROL);a.i(49,1,8,16)
    for i,off in enumerate((0,4,8)):
        a.lw(9,4,2416+off);a.sw(9,29,0xB0+4*i)
        a.i(49,2,2,16+off);a.i(49,3,2,48+off);fop(a,0,2,2,3)
        a.i(49,0,4,2416+off);fop(a,1,0,0,2);fop(a,3,0,0,1);fop(a,0,0,0,2)
        a.i(57,0,4,2416+off)
    a.lw(4,29,SAVED.index(4)*8);a.call(TAILS+0xA0)
    a.lw(8,29,0xC0)
    for i,off in enumerate((0,4,8)):a.lw(9,29,0xB0+4*i);a.sw(9,8,2416+off)
    restore(a,result=True);a.jr()
    a.label('native');restore(a);a.jump(TAILS+0xA0);return a.finish()


def attack_sphere_code():
    # Native 24DDF0 scales the limb position through its world matrix, but
    # supplies a literal radius to 2399A0. Scale that radius before broad-phase
    # bounds are built. No change to projectiles, targets, or hit arbitration.
    a=Assembler(ATTACK_SPHERE);save(a);a.i(57,12,29,0xB0)
    a.move(4,23);a.call(MODEL);a.branch(4,2,0,'sphere')
    a.li(8,CONTROL);a.i(49,0,8,16);fop(a,2,12,12,0)
    a.label('sphere');a.lw(4,29,SAVED.index(4)*8);a.lw(5,29,SAVED.index(5)*8)
    a.call(A(0x2399A0));a.i(49,12,29,0xB0);restore(a,result=True);a.jr();return a.finish()


def attack_box_code():
    # The OBB solver requires unit basis vectors and explicit half extents.
    # Baking scale only into the basis expands the rendered corners correctly
    # but makes the narrow-phase projections reject otherwise valid hits.
    a=Assembler(ATTACK_BOX);save(a)
    for i in range(3):a.i(57,12+i,29,0xB0+4*i)
    a.move(4,23);a.call(MODEL);a.branch(4,2,0,'box')
    a.li(8,CONTROL);a.i(49,0,8,16)
    for i in range(3):fop(a,2,12+i,12+i,0)
    a.label('box');a.lw(4,29,SAVED.index(4)*8);a.lw(5,29,SAVED.index(5)*8)
    a.call(A(0x230F70))
    for i in range(3):a.i(49,12+i,29,0xB0+4*i)
    restore(a,result=True);a.jr();return a.finish()


def attack_basis_code():
    a=Assembler(ATTACK_BASIS);save(a);a.call(A(0x120230))
    a.sw(2,29,0xB0);a.sw(3,29,0xB4);a.move(4,23);a.call(MODEL);a.branch(4,2,0,'done')
    a.li(8,CONTROL);a.i(49,1,8,16);a.lw(8,29,SAVED.index(4)*8)
    for off in (0,4,8,16,20,24,32,36,40):
        a.i(49,0,8,off);fop(a,3,0,0,1);a.i(57,0,8,off)
    a.label('done');a.lw(2,29,0xB0);a.lw(3,29,0xB4);restore(a,result=True);a.jr();return a.finish()


def hurt_box_code():
    # Native 24D9D0 keeps s2 = model+FC0. World corners/broad bounds are
    # already scaled; normalize only the query basis and rebuild half extents
    # from the immutable positive local corner, never last frame's extents.
    a=Assembler(HURT_BOX);save(a);a.call(A(0x24D7F8))
    a.sw(2,29,0xB0);a.sw(3,29,0xB4);a.addiu(4,18,-0xFC0);a.call(MODEL);a.branch(4,2,0,'done')
    a.li(8,CONTROL);a.i(49,1,8,16);a.lw(8,29,SAVED.index(4)*8)
    for off in (0x20,0x24,0x28,0x30,0x34,0x38,0x40,0x44,0x48):
        a.i(49,0,8,off);fop(a,3,0,0,1);a.i(57,0,8,off)
    for off in (0,4,8):
        a.i(49,0,8,0x90+off);fop(a,2,0,0,1);a.i(57,0,8,0x10+off)
    a.label('done');a.lw(2,29,0xB0);a.lw(3,29,0xB4);restore(a,result=True);a.jr();return a.finish()


def speed_code():
    a=Assembler(SPEED);save(a);a.call(MODEL);a.branch(4,2,0,'native')
    # Melee/projectile attacks; never desynchronise rushes, throws, clashes,
    # transformations, intros, KO/get-up or authored ultimate timelines.
    a.lw(9,2,2376);a.addiu(9,9,-55);a.i(11,9,9,125);a.branch(4,9,0,'native')
    a.lw(4,29,SAVED.index(4)*8);a.lw(9,4,3200);a.sw(9,29,0xB0)
    a.li(8,CONTROL);a.i(49,1,8,20);a.i(49,0,4,3200);fop(a,2,0,0,1);a.i(57,0,4,3200)
    a.call(TAILS+0x20);a.lw(8,29,SAVED.index(4)*8);a.lw(9,29,0xB0);a.sw(9,8,3200)
    restore(a,result=True);a.jr()
    a.label('native');restore(a);a.jump(TAILS+0x20);return a.finish()


def damage_code(ee_convert=True):
    a=Assembler(DAMAGE);save(a);a.call(ACTOR);a.branch(4,2,0,'native')
    a.lw(9,29,SAVED.index(5)*8);a.branch(6,9,0,'native')
    a.li(8,CONTROL);a.i(49,1,8,24);a.emit((17<<26)|(4<<21)|(9<<16))
    a.emit((17<<26)|(20<<21)|(0<<11)|(0<<6)|0x20);fop(a,2,0,0,1)
    # Bound before float -> int conversion, including corrupt incoming values.
    a.li(8,struct.unpack('<I',struct.pack('<f',10000000.0))[0]);a.emit((17<<26)|(4<<21)|(8<<16)|(2<<11))
    fop(a,0x34 if ee_convert else 0x3C,0,2,0);a.branch(17,8,0,'bounded');fop(a,6,0,2)
    # EE supports CVT.W.S; MIPS III TRUNC.W.S is not implemented by the EE.
    # The latter left IEEE float bits in a1, turning 2580 into 1159806976 damage.
    a.label('bounded');fop(a,0x24 if ee_convert else 13,0,0);a.emit((17<<26)|(0<<21)|(9<<16));a.i(63,9,29,SAVED.index(5)*8)
    a.label('native');restore(a);a.jump(TAILS+0x40);return a.finish()


def armor_code():
    a=Assembler(ARMOR);save(a);a.call(A(0x20DF60));a.sw(2,29,0xB0)
    a.move(4,18);a.call(ACTOR);a.branch(4,2,0,'done')
    a.li(8,CONTROL);a.lw(9,8,28);a.lw(2,29,0xB0);a.r(0x23,2,2,9);a.sw(2,29,0xB0)
    a.label('done');a.lw(2,29,0xB0);restore(a,result=True);a.jr();return a.finish()


def camera_code(locked=False):
    # Ordinary follow only, before native smoothing, arena clamp and terrain
    # collision in 1C69C8. Authored close-ups use other native camera solvers.
    a=Assembler(LOCKED_CAMERA if locked else CAMERA);save(a);a.call(TAILS+(0x80 if locked else 0x60))
    a.lw(4,29,SAVED.index(4)*8);a.call(ACTOR);a.branch(4,2,0,'done')
    a.lw(5,29,SAVED.index(5)*8);a.lw(7,29,SAVED.index(7)*8)
    a.li(8,CONTROL);a.i(49,2,8,32)
    for off in (0,4,8):
        a.i(49,0,5,off);a.i(49,1,7,off);fop(a,1,0,0,1)
        fop(a,2,0,0,2);fop(a,0,0,0,1);a.i(57,0,5,off)
    a.label('done');restore(a);a.jr();return a.finish()


def pieces():
    out=[(MODEL,model_code()),(ACTOR,actor_code()),(SCALE,scale_code()),(SPEED,speed_code()),
         (DAMAGE,damage_code()),(ARMOR,armor_code()),(CAMERA,camera_code()),(LOCKED_CAMERA,camera_code(True)),
         (ROOT_MOTION,root_motion_code()),(ATTACK_SPHERE,attack_sphere_code()),
         (ATTACK_BOX,attack_box_code()),(ATTACK_BASIS,attack_basis_code()),(HURT_BOX,hurt_box_code())]
    for i,(hook,entry) in enumerate(HOOKS):
        old=NATIVE(hook,8)
        if any(w>>26 in (1,2,3,4,5,6,7,20,21) for w in struct.unpack('<2I',old)):
            raise ValueError('Giant hook needs branch relocation')
        out.extend(((TAILS+i*0x20,old+jump(hook+8)),(hook,jump(entry))))
    out.append((ARMOR_CALL,jump(ARMOR,True)[:4])) # preserve original argument delay slot
    out.append((SPHERE_CALL,jump(ATTACK_SPHERE,True)[:4]))
    out.append((BOX_CALL,jump(ATTACK_BOX,True)[:4]))
    out.append((BASIS_CALL,jump(ATTACK_BASIS,True)[:4]))
    out.append((HURT_CALL,jump(HURT_BOX,True)[:4]))
    spans=sorted((p,p+len(d)) for p,d in out)
    assert all(e<=s for (_,e),(s,_) in zip(spans,spans[1:]))
    return out


def native_helper(ram,address,size,native):
    """Exact optional hook chain for model reload validators."""
    expected=native(address,size)
    entry=dict(HOOKS).get(address)
    if entry is None or ram[address:address+8]!=jump(entry):return expected
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(MAGIC,u(core.ACTORS),u(core.MODE+4)):
        raise ValueError('Giant helper belongs to another match')
    for p,d in pieces():
        if ram[p:p+len(d)]!=d:raise ValueError(f'Giant helper code changed:{p:08X}')
    return jump(entry)+expected[8:]


@modes.matching_install
def build_memory(ram,settings=None,source='<prepared>'):
    s=mod_settings.validate_settings(settings or {});u=lambda p:struct.unpack_from('<I',ram,p)[0]
    installed=u(CONTROL)==MAGIC
    if not installed and not s['canonical_giants']:return dict(blocks=[])
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Giant options require a captured active match')
    code=pieces()
    upgrade=[]
    if installed:
        if (u(CONTROL+4),u(CONTROL+8))!=(manager,count):raise ValueError('Giant options belong to another match')
        additions={CAMERA,LOCKED_CAMERA,TAILS+0x60,TAILS+0x80,A(0x1C6268),A(0x1C5C80),ROOT_MOTION,TAILS+0xA0,A(0x1D70E8),ATTACK_SPHERE,SPHERE_CALL,ATTACK_BOX,ATTACK_BASIS,BOX_CALL,BASIS_CALL,HURT_BOX,HURT_CALL}
        for p,d in code:
            if ram[p:p+len(d)]==d:continue
            if p==SCALE:
                old_versions=(scale_code(False,False),scale_code(True,False))
                if any(ram[p:p+len(old)]==old and not any(ram[p+len(old):p+len(d)]) for old in old_versions):
                    upgrade.append((p,d));continue
            if p==DAMAGE and ram[p:p+len(d)]==damage_code(False):
                upgrade.append((p,d));continue
            # Exact original giant install may predate the follow-camera option.
            before=NATIVE(p,len(d)) if p<BASE else bytes(len(d))
            if p not in additions or ram[p:p+len(d)]!=before:raise ValueError('Giant code changed')
            upgrade.append((p,d))
    else:
        if any(ram[BASE:END]):raise ValueError('Giant reservation occupied')
        for p,d in code:
            if p<BASE and ram[p:p+len(d)]!=NATIVE(p,len(d)):raise ValueError(f'Giant native hook changed: {p:X}')
        if ram[ARMOR_CALL+4:ARMOR_CALL+8]!=NATIVE(ARMOR_CALL+4,4):raise ValueError('Giant armor delay slot changed')
    for call in (SPHERE_CALL,BOX_CALL,BASIS_CALL,HURT_CALL):
        if ram[call+4:call+8]!=NATIVE(call+4,4):raise ValueError('Giant collision delay slot changed')
    data=struct.pack('<4I3fIf',MAGIC,manager,count,int(s['canonical_giants']),
                     s['giant_size_multiplier'],s['giant_attack_speed_percent']/100,
                     s['giant_damage_percent']/100,s['giant_armor_levels'],s['giant_camera_distance_percent']/100)
    patches=(upgrade+[(CONTROL,data)] if installed else code+[(CONTROL,data)])
    if installed and u(CONTROL+12) and not s['canonical_giants']:
        # Switching an owned install off also restores cached native dimensions.
        # The root matrix multiplier itself is temporary and never persists.
        for i in range(count):
            actor=u(core.POINTERS+4*i)
            if not 0x100000<=actor<len(ram)-0x1600:raise ValueError('Invalid giant actor identity')
            mid=u(actor+12)
            if mid>=modes.ENGINE_ACTORS:raise ValueError('Invalid giant model identity')
            model=u(core.MODELS+4*mid)
            if not 0x100000<=model<len(ram)-0x1670 or u(model+16)!=mid:raise ValueError('Giant model registration changed')
            param=u(model+2332)
            if not 0x100000<=param<len(ram)-16:raise ValueError('Invalid giant parameters')
            if ram[param+2]!=4:continue
            mesh,collision=u(model+64),u(model+84)
            if not all(0x100000<=p<len(ram)-40 for p in (mesh,collision)):raise ValueError('Invalid giant dimension source')
            values=[struct.unpack_from('<f',ram,p)[0] for p in (collision+4,mesh+24,mesh+28,mesh+32,mesh+36)]
            sphere=struct.unpack_from('<f',ram,param+8)[0]
            values.append(sphere if sphere>0 else 2*values[-1])
            if not all(math.isfinite(v) for v in values):raise ValueError('Invalid giant dimensions')
            patches.append((model+4080,struct.pack('<6f',*values)))
            if ram[HURT_BOX:HURT_BOX+len(hurt_box_code())]==hurt_box_code():
                node=u(model+0xF50)
                if not node:continue
                for _ in range(64):
                    if not 0x100000<=node<len(ram)-0x1D0:raise ValueError('Invalid giant limb collision storage')
                    patches.append((node+0x50,ram[node+0xD0:node+0xDC]))
                    if u(node)&1:break
                    node+=0x1D0
                else:raise ValueError('Giant limb collision list has no terminator')
    return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[
        dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex())
        for p,d in patches if ram[p:p+len(d)]!=d],
        notes=['Playable interpretation of giant scale, not a claim of exact canonical heights.',
               'Slower ordinary attacks; paired/cinematic timelines retain their native timing.',
               'Armor adds native stagger tiers; armor-breaking attacks and damage remain active.'])
