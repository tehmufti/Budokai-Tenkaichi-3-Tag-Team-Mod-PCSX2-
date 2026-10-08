"""Exclude unused/consumed slots from native per-actor updates.

Uneven-match reservations can still contain borrowed leader model data. A
leader reload invalidates that data; zero HP alone does not stop native ki,
input, action or model updates. Real corpses remain participants and continue
updating normally. No emulator connection is made by this module.
"""
from native_map import A, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import team_participation as part

ENTRY, END, HOOK = 0x077C4000, 0x077C5000, A(0x1DC2C0)
NATIVE = elf_reader(elf_path(ROOT))[2]
# Exact return addresses of native per-actor update calls. Other callers ask
# whether anyone is paused; reporting a permanent pause there would freeze an
# uneven match's global systems merely because it reserves an absent slot.
CALLERS=(A(0x1C1AE4),A(0x1C1B38),A(0x1C1D64),A(0x1C1EC4),A(0x1C1FC4),A(0x1C202C),
         A(0x1C20C8),A(0x1C21BC),A(0x1C223C),A(0x1C22D4),A(0x1C2330),A(0x1C249C),A(0x1C2594))


def code():
    a=Assembler(ENTRY);regs=(8,9,10,11,12)
    a.addiu(29,29,-0x50)
    for i,r in enumerate(regs):a.i(31,r,29,16*i)
    for caller in CALLERS:
        a.li(8,caller);a.branch(4,31,8,'actor_update')
    a.jump('native');a.label('actor_update')
    core.gate(a,'native')
    a.li(8,part.CONTROL);a.lw(9,8);a.addiu(11,0,5);a.branch(5,9,11,'native')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'native')
    a.lw(9,8,8);a.branch(5,9,10,'native')
    a.lw(11,4);a.r(0x2B,9,11,10);a.branch(4,9,0,'native')
    a.li(9,core.POINTERS);a.r(0,12,0,11,2);a.r(0x2D,9,9,12);a.lw(9,9)
    a.branch(5,9,4,'native')
    a.addiu(9,0,1);a.r(4,9,11,9)
    a.lw(12,8,12);a.r(0x24,12,12,9);a.branch(4,12,0,'inactive')
    a.lw(12,8,16);a.r(0x24,12,12,9);a.branch(4,12,0,'native')
    a.label('inactive');a.addiu(2,0,1);a.jump('return')
    a.label('native');a.lw(2,4,4896);a.r(0x2A,2,0,2)
    a.label('return')
    for i,r in enumerate(regs):a.i(30,r,29,16*i)
    a.addiu(29,29,0x50);a.jr();data=a.finish();assert len(data)<END-ENTRY;return data


def hook():return struct.pack('<2I',(2<<26)|(ENTRY>>2),0)+NATIVE(HOOK+8,4)


def validate_memory(ram):
    for at,data in ((ENTRY,code()),(HOOK,hook())):
        if ram[at:at+len(data)]!=data:raise ValueError('Inactive actor update guard changed')


def dependency_override(ram,address,expected):
    if address!=HOOK or ram[HOOK:HOOK+12]==expected:return expected
    validate_memory(ram)
    return hook()


@part.core.policy.matching_install
def build_memory(ram,source='<captured-ready>'):
    if ram[HOOK:HOOK+12]!=NATIVE(HOOK,12):
        validate_memory(ram);return dict(source=str(source),blocks=[])
    u=lambda at:struct.unpack_from('<I',ram,at)[0]
    if (u(part.CONTROL+4),u(part.CONTROL+8))!=(u(core.ACTORS),u(core.MODE+4)):
        raise ValueError('Inactive actor guard requires this match participation table')
    if any(ram[ENTRY:END]):raise ValueError('Inactive actor guard reservation occupied')
    call=struct.pack('<I',(3<<26)|(HOOK>>2))
    if any(ram[caller-8:caller-4]!=call for caller in CALLERS):
        raise ValueError('Inactive actor update callsite changed')
    return dict(source=str(source),blocks=[dict(address=at,expected_hex=ram[at:at+len(data)].hex(),data_hex=data.hex())
                for at,data in ((ENTRY,code()),(HOOK,hook()))])
