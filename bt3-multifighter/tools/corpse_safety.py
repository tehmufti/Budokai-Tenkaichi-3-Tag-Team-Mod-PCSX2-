"""Keep retained KO bodies supported at the current arena's flight boundary.

Native limiter skips dead actors; KO216 also enters unsupported fall217 when
there is no terrain below. Handle both KO states, cancel downward gravity at
the net, and make only the KO216 support query see the virtual floor there.
Living actors, real terrain geometry, control ownership and HP remain native.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

from prototype import Assembler, ROOT, elf_reader
import battle_mode_policy as policy
import fresh_team_combat as core
import team_participation as participation
import team_start_gate as start
import mod_settings as preferences

CODE, CONTROL, END = 0x072F0000, 0x072FF000, 0x07300000
HOOK, DEAD, MAGIC = A(0x1DF068), A(0x1DC320), 0x4B4F4E31
FLOOR_HOOK, FLOOR_CODE, FLOOR_NATIVE = A(0x1EA16C), CODE+0x1000, A(0x1E0510)
SUPPORTED = CONTROL+0x100 # 12 rows: physical actor pointer, native stage bottom bits
STAGE, BATTLE = A(0x2FEBE0), A(0x2FEB38)
NATIVE = elf_reader(elf_path(ROOT))[2]
FIELDS = dict(magic=0, manager=4, count=8, enabled=12, eligible_updates=16, last_actor=20)
DEPENDENCIES = ((A(0x1DEF70),0x22C), (A(0x23FF38),0x40), (A(0x204EA0),0x30))
SAVED = (8,9,10,11,12,13,14,15)


def pointer(a, reg, size, fail):
    a.i(12,9,reg,3); a.branch(5,9,0,fail)
    a.li(9,0x100000); a.r(0x2B,9,reg,9); a.branch(5,9,0,fail)
    a.li(9,0x8000000-size); a.r(0x2B,9,9,reg); a.branch(5,9,0,fail)


def _payload(address=CODE, legacy=True, floor=False):
    a=Assembler(address); a.addiu(29,29,-0x40)
    for i,r in enumerate(SAVED): a.i(63,r,29,i*8)
    core.gate(a,'native')
    a.li(8,CONTROL); a.lw(9,8); a.li(11,MAGIC); a.branch(5,9,11,'native')
    a.lw(9,8,4); a.lw(11,28,-22364); a.branch(5,9,11,'native')
    a.lw(9,8,8); a.branch(5,9,10,'native')
    a.lw(9,8,12); a.branch(4,9,0,'native')
    a.li(8,core.PAIR+4); a.lw(9,8); a.branch(5,9,0,'native')
    a.li(8,start.CONTROL); a.lw(9,8); a.branch(5,9,0,'native')
    a.li(8,A(0x333700)); a.lw(9,8); a.branch(5,9,0,'native')
    a.li(8,BATTLE); a.lw(11,8); pointer(a,11,4,'native')
    a.lw(9,11); a.addiu(8,0,3); a.branch(5,9,8,'native')
    # Pointer membership, not a transient role alias, owns the retained body.
    a.li(11,core.POINTERS); a.move(12,0)
    a.label('scan'); a.lw(9,11); a.branch(4,9,4,'found')
    a.addiu(11,11,4); a.addiu(12,12,1); a.branch(5,12,10,'scan'); a.jump('native')
    a.label('found'); pointer(a,4,0x1600,'native')
    a.li(11,participation.CONTROL); a.lw(9,11); a.addiu(8,0,5); a.branch(5,9,8,'native')
    a.lw(9,11,4); a.lw(8,28,-22364); a.branch(5,9,8,'native')
    a.lw(9,11,8); a.branch(5,9,10,'native')
    a.addiu(8,0,1); a.r(4,8,12,8)
    a.lw(9,11,12); a.r(0x24,9,9,8); a.branch(4,9,0,'native')
    a.lw(9,11,16); a.r(0x24,9,9,8); a.branch(5,9,0,'native')
    a.lw(9,4,0x948)
    if legacy:
        a.addiu(8,0,216); a.branch(5,9,8,'native')
    else:
        a.addiu(8,9,-216); a.i(11,8,8,2); a.branch(4,8,0,'native')
    a.lw(8,4,0x994); a.i(11,9,8,5); a.branch(4,9,0,'native')
    a.r(0,9,0,8,7); a.r(0,11,0,8,5); a.r(0x2D,9,9,11)
    a.r(0,11,0,8,2); a.r(0x2D,9,9,11); a.r(0x2D,9,9,4)
    a.lw(9,9,0x9E4); a.branch(7,9,0,'native')
    # Readiness and finite bounds only. The untouched native helper selects
    # the actual current stage bottom each update, including stage destruction.
    a.li(8,STAGE); a.lw(11,8); pointer(a,11,68,'native')
    a.lw(11,11,64); pointer(a,11,12,'native')
    a.lw(9,11,8); a.li(8,0x7FFFFFFF); a.r(0x24,9,9,8)
    a.li(8,0x49742400); a.r(0x2B,9,9,8); a.branch(4,9,0,'native')
    if not legacy:
        # The KO handler uses its real-floor distance to turn action216 into
        # falling217. A flight-boundary clamp alone cannot settle that cycle.
        # At the current safety plane, clear native vertical gravity and let
        # this KO-only distance call see support. No terrain data is changed.
        a.lw(14,11,8); a.lw(13,4,20)
        a.li(8,0x7FFFFFFF); a.r(0x24,9,13,8); a.li(8,0x49742400)
        a.r(0x2B,9,9,8); a.branch(4,9,0,'native')
        a.li(8,0x7FFFFFFF); a.r(0x24,9,13,8)
        a.branch(5,9,0,'nonzero_y'); a.move(13,0); a.label('nonzero_y')
        a.r(0x24,9,14,8); a.branch(5,9,0,'nonzero_bottom')
        a.move(14,0); a.label('nonzero_bottom')
        # Finite IEEE-float ordering without changing FPU status/registers.
        a.li(8,0x80000000); a.r(0x24,9,14,8); a.r(0x24,8,13,8)
        a.branch(5,8,9,'different_signs')
        a.branch(5,8,0,'negative_values')
        a.r(0x2B,9,13,14); a.branch(5,9,0,'above'); a.jump('supported')
        a.label('negative_values'); a.r(0x2B,9,14,13)
        a.branch(5,9,0,'above'); a.jump('supported')
        a.label('different_signs'); a.branch(5,8,0,'above')
        a.label('supported')
        if floor:
            a.emit((17<<26)|(4<<21)) # mtc1 zero,f0: supported KO distance
        else:
            a.sw(0,4,0xAC) # native1DED28 gravity accumulator
            a.li(11,SUPPORTED); a.r(0,9,0,12,3); a.r(0x2D,11,11,9)
            a.sw(4,11); a.sw(14,11,4)
            a.lw(9,4,0x948); a.addiu(8,0,217); a.branch(5,9,8,'settled')
            a.lw(9,4,0x94C); a.addiu(8,0,-1)
            a.branch(4,9,8,'queue_ko'); a.addiu(8,0,217); a.branch(5,9,8,'settled')
            a.label('queue_ko'); a.addiu(8,0,216); a.sw(8,4,0x94C)
            a.label('settled')
        a.jump('eligible')
        a.label('above')
        if floor:
            a.jump('native')
        else:
            a.li(11,SUPPORTED); a.r(0,9,0,12,3); a.r(0x2D,11,11,9); a.sw(0,11)
        a.label('eligible')
    if not floor:
        a.li(8,CONTROL); a.lw(9,8,16); a.addiu(9,9,1); a.sw(9,8,16); a.sw(4,8,20)
    for i,r in enumerate(SAVED): a.i(55,r,29,i*8)
    a.addiu(29,29,0x40); a.move(2,0); a.jr()
    a.label('native')
    for i,r in enumerate(SAVED): a.i(55,r,29,i*8)
    a.addiu(29,29,0x40); a.jump(FLOOR_NATIVE if floor else DEAD)
    data=a.finish(); assert len(data)<0x1000; return data


def payload(): return _payload(legacy=False)
def legacy_payload(): return _payload()
def floor_payload(): return _payload(FLOOR_CODE,legacy=False,floor=True)


def validate_native(ram, installed=False, current=False):
    for p,size in DEPENDENCIES:
        expected=bytearray(NATIVE(p,size))
        if installed and p<=HOOK<p+size:
            struct.pack_into('<I',expected,HOOK-p,(3<<26)|(CODE>>2))
        if ram[p:p+size]!=expected:
            raise ValueError(f'Corpse safety native limiter changed {p:08X}')
    floor_expected=struct.pack('<I',(3<<26)|(FLOOR_CODE>>2)) if current else NATIVE(FLOOR_HOOK,4)
    if ram[FLOOR_HOOK:FLOOR_HOOK+4]!=floor_expected:
        raise ValueError('Corpse safety KO floor-distance call changed')
    for p,size in ((FLOOR_NATIVE,0x40),(A(0x1DED28),0x50)):
        if ram[p:p+size]!=NATIVE(p,size): raise ValueError('Corpse safety native KO physics changed')


@policy.matching_install
def build_memory(ram, settings=None, source='<prepared>'):
    if len(ram)!=0x8000000: raise ValueError('Corpse safety requires original 128MiB BT3 RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    enabled=preferences.validate_settings({} if settings is None else settings)[preferences.CORPSE_SAFETY_KEY]
    installed=u(CONTROL)==MAGIC
    if not installed and not enabled:
        return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[],enabled=False)
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if (count not in policy.ACTOR_COUNTS or not 0x100000<=manager<=len(ram)-0x1000
            or u(manager)!=2 or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count)):
        raise ValueError('Corpse safety captured actor manager changed')
    if (u(participation.CONTROL+4),u(participation.CONTROL+8))!=(manager,count):
        raise ValueError('Corpse safety requires matching participation records')
    code=payload(); hook=struct.pack('<I',(3<<26)|(CODE>>2))
    old=legacy_payload()
    legacy=installed and ram[CODE:CODE+len(old)]==old
    current=installed and not legacy
    validate_native(ram,installed,current)
    if installed:
        if (u(CONTROL+4),u(CONTROL+8))!=(manager,count):
            raise ValueError('Corpse safety belongs to another match')
        if (not legacy and ram[CODE:CODE+len(code)]!=code) or ram[HOOK:HOOK+4]!=hook:
            raise ValueError('Corpse safety code changed')
        if u(CONTROL+12) not in (0,1): raise ValueError('Corpse safety enabled flag changed')
        parts=[]
        if legacy:
            if any(ram[CODE+len(old):CONTROL]) or any(ram[CONTROL+24:END]):
                raise ValueError('Corpse safety upgrade reservation occupied')
            parts.extend(((CODE,code),(FLOOR_CODE,floor_payload()),
                          (FLOOR_HOOK,struct.pack('<I',(3<<26)|(FLOOR_CODE>>2)))))
        elif ram[FLOOR_CODE:FLOOR_CODE+len(floor_payload())]!=floor_payload():
            raise ValueError('Corpse safety KO support code changed')
        if u(CONTROL+12)!=int(enabled): parts.append((CONTROL+12,struct.pack('<I',int(enabled))))
    else:
        if any(ram[CODE:END]): raise ValueError('Corpse safety reservation occupied')
        control=struct.pack('<6I',MAGIC,manager,count,int(enabled),0,0)
        parts=[(CODE,code),(CONTROL,control),(HOOK,hook),(FLOOR_CODE,floor_payload()),
               (FLOOR_HOOK,struct.pack('<I',(3<<26)|(FLOOR_CODE>>2)))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,enabled=enabled,
        blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in parts],
        telemetry={name:CONTROL+offset for name,offset in FIELDS.items()},supported_rows=SUPPORTED,
        status='Retained KO bodies settle at the current native arena lower flight boundary',
        limitations=['No revival mechanic or forced landing animation is added.',
                     'Only captured present KO216/217 bodies during fighting are eligible.',
                     'Ground geometry remains native; airborne corpses can rest at the arena boundary.'])
