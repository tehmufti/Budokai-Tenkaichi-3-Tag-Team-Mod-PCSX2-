"""Optional CPU-only ordinary form restrictions, before any action/reload starts.

The native model parameter +2 is size class (20E130); class4 is giant.
GIANTS was extracted from mesh package17 of all161 original USA characters,
not inferred from display names. Form destinations use the same parameter
+152+slot read by native20E180. Only2033C8/203610 are wrapped; fusion, tag,
Body Change and already started reload handshakes remain untouched.
"""
from native_map import CRC, SERIAL, elf_path
import struct
import battle_mode_policy as modes
import fresh_team_combat as core
import ordinary_transform_guard as ordinary
import cinematic_admission as admission
import guest_killfeed as abi
import mod_settings as prefs
from prototype import Assembler,ROOT,elf_reader

CODE, PREDICATE, CONTROL, END = 0x07290000,0x07292000,0x0729F000,0x072A0000
WRAPPERS=(CODE,CODE+0x800)
OVERRIDES, GIANT_TABLE = CONTROL+0x100,CONTROL+0x200
MAGIC=0x4E545031
# All original-USA sizeclass4 records, verified directly from the ISO.
GIANTS=(12,30,72,74,76,78,81,120,122,124,137,139,143,153)
FIELDS=dict(magic=0,manager=4,count=8,disable_all=12,disable_giants=16,
            refused=20,actor=24,current_character=28,destination=32)
NATIVE=elf_reader(elf_path(ROOT))[2]


def jump(target): return struct.pack('<2I',(2<<26)|(target>>2),0)


def pointer(a,reg,tail,fail):
    a.i(12,9,reg,3);a.branch(5,9,0,fail)
    a.li(9,0x100000);a.r(0x2B,9,reg,9);a.branch(5,9,0,fail)
    a.li(9,0x08000000-tail);a.r(0x2B,9,reg,9);a.branch(4,9,0,fail)


def predicate(*,chance=True):
    # a0 actual actor pointer, a1 native form slot -> v0=1 refuse /0 continue.
    a=Assembler(PREDICATE);core.gate(a,'allow')
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'allow')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'allow')
    a.lw(9,8,8);a.branch(5,9,10,'allow')
    a.li(11,core.POINTERS);a.move(12,0)
    a.label('scan');a.lw(9,11);a.branch(4,9,4,'actor')
    a.addiu(11,11,4);a.addiu(12,12,1);a.branch(5,12,10,'scan');a.jump('allow')
    a.label('actor');a.lw(9,4,0x1278);a.addiu(10,0,1);a.branch(5,9,10,'allow')
    # The actor's own current CPU flag follows takeovers automatically. Never
    # infer ownership from side, temporary aliased ID, or initial human mask.
    a.i(11,9,5,4);a.branch(4,9,0,'allow')
    a.lw(11,4,12);a.i(11,9,11,modes.ENGINE_ACTORS);a.branch(4,9,0,'allow')
    a.r(0,9,0,11,2);a.li(10,core.MODELS);a.r(0x2D,10,10,9);a.lw(10,10)
    pointer(a,10,0x920,'allow');a.lw(9,10,16);a.branch(5,9,11,'allow')
    a.lw(12,10,12);a.i(11,9,12,250);a.branch(4,9,0,'allow')
    # 0 inherits global rules,1 explicit allow,2 explicit deny (for current form).
    a.li(11,OVERRIDES);a.r(0x2D,11,11,12);a.i(36,9,11,0)
    a.addiu(11,0,1);a.branch(4,9,11,'chance' if chance else 'allow')
    a.addiu(11,0,2);a.addiu(13,0,-1);a.branch(4,9,11,'deny')
    a.lw(9,8,FIELDS['disable_all']);a.branch(5,9,0,'deny')
    a.lw(9,8,FIELDS['disable_giants']);a.branch(4,9,0,'chance' if chance else 'allow')
    a.lw(10,10,0x91C);pointer(a,10,0x100,'allow')
    a.r(0x2D,10,10,5);a.i(36,13,10,152);a.i(11,9,13,250)
    a.branch(4,9,0,'allow') # unavailable/invalid destination stays native's concern
    a.li(10,GIANT_TABLE);a.r(0x2D,10,10,13);a.i(36,9,10,0);a.branch(4,9,0,'chance' if chance else 'allow')
    if chance:
        a.jump('deny');a.label('chance')
        # Stable for 64 combat updates per actor: an AI retrying each frame
        # cannot defeat a low probability by rolling again immediately. This
        # changes admission only, never forces a form or bypasses native costs.
        import native_preparation
        a.lw(10,8,36);a.i(11,9,10,256);a.branch(4,9,0,'allow')
        a.addiu(13,0,-1);a.branch(4,10,0,'deny')
        a.li(9,native_preparation.CONTROL+44);a.lw(9,9);a.r(2,9,0,9,6)
        a.r(0x26,9,9,4);a.li(11,0x9E3779B9);a.r(0x26,9,9,11)
        for shift,right in ((13,False),(17,True),(5,False)):
            a.r(2 if right else 0,11,0,9,shift);a.r(0x26,9,9,11)
        a.i(12,9,9,255);a.r(0x2B,9,9,10);a.branch(5,9,0,'allow')
    a.label('deny');a.lw(9,8,FIELDS['refused']);a.addiu(9,9,1);a.sw(9,8,FIELDS['refused'])
    a.sw(4,8,FIELDS['actor']);a.sw(12,8,FIELDS['current_character']);a.sw(13,8,FIELDS['destination'])
    a.addiu(2,0,1);a.jr();a.label('allow');a.move(2,0);a.jr()
    return a.finish()


def wrapper(base,previous):
    a=Assembler(base);abi.prologue(a);a.call(PREDICATE);a.branch(4,2,0,'native')
    abi.restore(a);a.i(55,31,29,abi.RETURN);a.addiu(29,29,abi.FRAME_SIZE);a.move(2,0);a.jr()
    a.label('native');abi.restore(a);a.i(55,31,29,abi.RETURN)
    a.addiu(29,29,abi.FRAME_SIZE);a.jump(previous)
    return a.finish()


def pieces(*,chance=True):
    return [(PREDICATE,predicate(chance=chance))]+[(base,wrapper(base,cave))
        for (entry,cave,_),base in zip(ordinary.ENTRIES,WRAPPERS)]


def configured_data(options,manager,count):
    control=bytearray(20)
    struct.pack_into('<5I',control,0,MAGIC,manager,count,int(options[prefs.NPC_TRANSFORM_KEY]),
                     int(options[prefs.NPC_GIANT_KEY]))
    overrides=bytearray(250)
    for cid,allow in options[prefs.NPC_OVERRIDES_KEY].items():overrides[int(cid)]=1 if allow else 2
    import compatibility_profile
    giant_ids={c['character_id'] for c in compatibility_profile.profile()['characters'] if c.get('size_class')==4}
    giants=bytes(int(cid in giant_ids) for cid in range(250))
    threshold=round(options['npc_transform_chance_percent']*256/100)
    return [(CONTROL,bytes(control)),(CONTROL+36,struct.pack('<I',threshold)),(OVERRIDES,bytes(overrides)),(GIANT_TABLE,giants)]


@modes.matching_install
def build_memory(ram,settings=None,source='<prepared>',force=False):
    if len(ram)!=0x8000000:raise ValueError('NPC transform settings require128MiB captured RAM')
    options=prefs.validate_settings({} if settings is None else settings)
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    installed=u(CONTROL)==MAGIC
    # No changes at all for existing/default players, preserving original emissions.
    if not force and not installed and not (options[prefs.NPC_TRANSFORM_KEY] or options[prefs.NPC_GIANT_KEY]
                              or options[prefs.NPC_OVERRIDES_KEY] or options['npc_transform_chance_percent']!=100):
        return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[])
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('NPC form settings require an active captured actor manager')
    patches=[(entry,jump(base)) for (entry,_,_),base in zip(ordinary.ENTRIES,WRAPPERS)]
    code=pieces();data=configured_data(options,manager,count)
    if installed:
        if (u(CONTROL+4),u(CONTROL+8))!=(manager,count):raise ValueError('NPC form policy belongs to another match')
        legacy=dict(pieces(chance=False))
        for p,d in code+patches:
            old=legacy.get(p)
            if ram[p:p+len(d)]!=d and (old is None or ram[p:p+len(d)]!=old+bytes(len(d)-len(old))):
                raise ValueError(f'NPC form policy changed:{p:08X}')
        blocks=[(p,d) for p,d in code+data if ram[p:p+len(d)]!=d]
    else:
        if any(ram[CODE:END]):raise ValueError('NPC form policy reservation occupied')
        for index,(entry,cave,_) in enumerate(ordinary.ENTRIES,7):
            expected=admission.wrapper(entry,cave,cave+0x200,NATIVE(entry,8),index)
            if ram[entry:entry+8]!=jump(cave):
                raise ValueError(f'Ordinary form admission chain changed:{entry:08X}')
            if ram[cave:cave+len(expected)]!=expected:
                import ordinary_form_admission as forms
                updated=dict((p,d) for p,_,d in forms.wrapper_parts(NATIVE))[cave]
                body=forms.predicate_code()
                if (ram[cave:cave+len(updated)]!=updated or
                        ram[forms.PREDICATE:forms.PREDICATE+len(body)]!=body):
                    raise ValueError(f'Ordinary form admission chain changed:{cave:08X}')
        blocks=code+data+patches
    spans=sorted((p,p+len(d)) for p,d in blocks)
    if any(end>p for (_,end),(p,_) in zip(spans,spans[1:])):raise ValueError('NPC form policy overlaps')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        settings={key:options[key] for key in (prefs.NPC_TRANSFORM_KEY,prefs.NPC_GIANT_KEY,prefs.NPC_OVERRIDES_KEY,'npc_transform_chance_percent')},
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in blocks],
        scope='CPU-controlled ordinary forms only; selected starting bodies/fusions/Body Change unchanged',
        giant_ids=list(GIANTS))
