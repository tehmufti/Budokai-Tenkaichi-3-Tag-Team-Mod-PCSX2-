"""Bound native post-destruction actor reset to the stage's two spawn records.

Native1C29D8 now iterates every captured fighter, but its1D7570 position helper
still indexes a two-row stage table by physical fighter number. Resolve actual
extras to their authored side anchor and find a nearby complete walkable body
footprint. Native arena IO, explosion timing and actor state handling remain.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
from prototype import Assembler,ROOT,elf_reader
import fresh_team_combat as core
import fusion_partner_lifecycle as saved
import spawn_placement as spawn
from terrain_crossing_guard import fp,constant
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy

CODE,RESET,QUERY,FOOTPRINT,BODY = 0x070A0000,0x070A2000,0x070A3000,0x070A4000,0x070A5000
CONTROL,ROW,END = 0x070AF000,0x070AF100,0x070B0000
MAGIC=0x53545231
NATIVE=elf_reader(elf_path(ROOT))[2]
HOOKS=((A(0x1D7594),CODE,A(0x2427A0)),(A(0x1C29F8),RESET,A(0x1C0AA8)))
OFFSETS=((-1,.6),(-.8,.8),(-.65,1),(-1,1.2),(-1.2,.6),(-.65,1.5))
# The relocated spawn helpers still call native floor/sector/solid-body code.
# Keep their reviewed dependencies guarded when installing on older archives,
# and when verifying an already installed bridge after a later patch stage.
NATIVE_DEPENDENCIES=(
    (A(0x1D7570),0x58),(A(0x1C0AA8),0xF8),(A(0x1C29D8),0x50),
    (A(0x2427A0),0x118),(A(0x2426E0),0xC0),(A(0x241F10),0x140),
    (A(0x11F588),0x24),(A(0x11F620),0x1C),
    (A(0x230B38),0x40),(A(0x1B14C0),0xF8),(A(0x1B1260),0x80),(A(0x1B12E0),0x120),
    (A(0x23FF78),0x198),(A(0x23FDB0),0xC0),(A(0x240110),0x28),
    (A(0x1B16F0),0x18),(A(0x1B1708),0x1B0),(A(0x1B26E0),0x108),
    (A(0x238310),0x78),(A(0x2FE5EC),16),(A(0x2FE64C),4),
)


def validate_native_dependencies(ram,installed=False):
    for address,size in NATIVE_DEPENDENCIES:
        expected=bytearray(NATIVE(address,size))
        if installed:
            # Substitute only our exact owned JAL words. Delay slots and the
            # rest of the surrounding native function must remain unchanged.
            for hook,target,_ in HOOKS:
                if address<=hook and hook+4<=address+size:
                    struct.pack_into('<I',expected,hook-address,(3<<26)|(target>>2))
        if ram[address:address+size]!=expected:
            raise ValueError(f'Native stage reset dependency changed {address:08X}')


def gate(a,fail):
    core.gate(a,fail);a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail)
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,fail)


def reset_code():
    a=Assembler(RESET);saved.save(a);gate(a,'native')
    a.li(11,core.POINTERS);a.move(12,0)
    a.label('scan');a.lw(8,11);a.branch(4,8,4,'found')
    a.addiu(11,11,4);a.addiu(12,12,1);a.branch(5,12,10,'scan');a.jump('native')
    a.label('found');a.lw(8,4);a.branch(5,8,12,'native')
    a.lw(8,4,0x994);a.i(11,9,8,5);a.branch(4,9,0,'native')
    saved.row_address(a,11,4,8,9);a.lw(8,11,64);a.branch(7,8,0,'native')
    a.li(8,CONTROL);a.lw(9,8,24);a.addiu(9,9,1);a.sw(9,8,24)
    saved.restore(a);a.jr()
    a.label('native');saved.restore(a);a.jump(A(0x1C0AA8));return a.finish()


def position_code():
    a=Assembler(CODE);saved.save(a);gate(a,'native')
    a.i(11,8,4,2);a.branch(5,8,0,'native');a.r(0x2B,8,4,10);a.branch(4,8,0,'native')
    a.branch(5,7,0,'native');a.move(22,4);a.move(17,5);a.move(18,6)
    # Native1D7570 retains the actual owner in s0. No temporary actor ID alias.
    a.r(0,8,0,4,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(19,9)
    a.branch(5,19,16,'native');a.lw(8,19);a.branch(5,8,22,'native')
    a.lw(8,19,12);a.i(11,9,8,12);a.branch(4,9,0,'native')
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,9,9,8);a.lw(20,9)
    a.branch(4,20,0,'native');a.lw(8,20,16);a.lw(9,19,12);a.branch(5,8,9,'native')
    # Only two authored records exist. This is the essential bounds correction.
    a.i(12,4,22,1);a.call(A(0x2427A0));a.move(23,2)
    a.li(8,CONTROL);a.lw(9,8,28);a.addiu(9,9,1);a.sw(9,8,28)
    # Query helpers temporarily publish scratch addresses; restore their entire
    # known global set even when an alternative is rejected.
    for i,o in enumerate(spawn.QUERY_GLOBALS):a.lw(8,28,o);a.sw(8,29,0x300+4*i)
    a.li(21,ROW)
    for off in (0,4,8,12):a.lw(8,17,off);a.sw(8,21,0x30+off)
    a.i(49,20,18,4);fp(a,6,12,20);a.call(A(0x11F588));fp(a,6,21,0)
    fp(a,6,12,20);a.call(A(0x11F620));fp(a,6,22,0)
    # The native model radius remains valid across transformations. Inflate the
    # footprint for animation displacement, then use a conservative body sphere.
    a.i(49,23,20,0x1004);constant(a,0,1);fp(a,0x34,0,0,23);a.branch(17,8,0,'fallback')
    constant(a,0,512);fp(a,0x34,0,23,0);a.branch(17,8,0,'fallback')
    constant(a,0,16);fp(a,0,23,23,0);a.i(57,23,21,0x20)
    constant(a,0,0);fp(a,1,0,0,23);a.i(57,0,21,0x24)
    constant(a,0,2);fp(a,2,24,23,0);constant(a,0,32);fp(a,0,24,24,0)
    constant(a,0,80);fp(a,0x34,0,24,0);a.branch(17,8,0,'wing');fp(a,6,24,0);a.label('wing')
    a.i(49,0,17,4);constant(a,1,256);fp(a,1,0,0,1);a.i(57,0,21,0x5C)
    a.li(8,spawn.STAGE);a.lw(8,8);a.lw(9,8,56);a.li(8,CONTROL);a.sw(9,8,64)
    # Three-a-side builds only ever re-place ranks 1 and 2: physical 2..3 on
    # one flank, 4..5 on the other (sltiu s6<4). Larger builds alternate the
    # flank by rank parity and set ranks 3..4 (physical 6..9) a second row
    # deeper, so no two extras of a side are dropped on the same spot.
    rows=policy.emitted_capacity()!=policy.LEGACY_TEAM_CAPACITY
    for index,(lr,back) in enumerate(OFFSETS):
        retry=f'retry{index}'
        constant(a,25,lr)
        if rows:a.r(2,8,0,22,1);a.i(12,8,8,1)
        else:a.i(11,8,22,4)
        a.branch(5,8,0,f'hand{index}')
        constant(a,25,-lr);a.label(f'hand{index}');fp(a,2,25,25,24)
        constant(a,26,back)
        if rows:
            a.i(11,8,22,6);a.branch(5,8,0,f'front{index}')
            constant(a,27,.9);fp(a,0,26,26,27);a.label(f'front{index}')
        fp(a,2,26,26,24)
        # right=(cos(yaw),-sin(yaw)); behind=-forward.
        a.i(49,0,21,0x30);fp(a,2,1,25,22);fp(a,0,0,0,1);fp(a,2,1,26,21);fp(a,1,0,0,1);a.i(57,0,21,0x10)
        a.i(49,0,21,0x38);fp(a,2,1,25,21);fp(a,1,0,0,1);fp(a,2,1,26,22);fp(a,1,0,0,1);a.i(57,0,21,0x18)
        a.move(4,21);a.call(FOOTPRINT);a.branch(4,2,0,retry)
        a.i(49,0,21,0x14);a.i(49,1,21,0x34);fp(a,1,0,0,1);fp(a,5,0,0);constant(a,1,128)
        fp(a,0x36,0,0,1);a.branch(17,8,0,retry)
        a.move(4,21);a.call(BODY);a.branch(4,2,0,retry)
        for off in (0,4,8):a.lw(8,21,0x10+off);a.sw(8,17,off)
        a.addiu(4,0,-1);a.move(5,17);a.call(A(0x23FF78));a.move(23,2)
        a.li(8,CONTROL);a.lw(9,8,12);a.addiu(9,9,1);a.sw(9,8,12);a.jump('done')
        a.label(retry)
    a.label('fallback');a.li(8,CONTROL);a.lw(9,8,20);a.addiu(9,9,1);a.sw(9,8,20)
    a.label('done')
    for i,o in enumerate(spawn.QUERY_GLOBALS):a.lw(8,29,0x300+4*i);a.sw(8,28,o)
    a.i(63,23,29,saved.OFFSETS[2]);saved.restore(a);a.jr()
    a.label('native');saved.restore(a);a.jump(A(0x2427A0))
    data=a.finish();assert len(data)<RESET-CODE;return data


def pieces():
    values=dict(QUERY=QUERY,CONTROL=CONTROL,FOOTPRINT=FOOTPRINT,BODY=BODY,CANDIDATES=CONTROL)
    return [(CODE,position_code()),(RESET,reset_code()),
        (QUERY,core.rebound(spawn.query_code,**values)()),
        (FOOTPRINT,core.rebound(spawn.footprint_code,**values)()),
        (BODY,core.rebound(spawn.body_code,**values)())]


def build_memory(ram,config=None,source='<offline-memory>'):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB original BT3 RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or [u(core.MODE+4*i) for i in range(4)]!=[1,count,manager,count]:
        raise ValueError('Captured4/6 fighter identity required')
    code=pieces();hookparts=[(p,struct.pack('<I',(3<<26)|(target>>2))) for p,target,_ in HOOKS]
    if u(CONTROL):
        if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(MAGIC,manager,count):raise ValueError('Stage reset ownership changed')
        if any(ram[p:p+len(b)]!=b for p,b in code+hookparts):raise ValueError('Stage reset code changed')
        validate_native_dependencies(ram,installed=True)
        return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[],control=CONTROL)
    if any(ram[CODE:END]):raise ValueError('Stage reset reservation occupied')
    for p,_,old in HOOKS:
        if u(p)!=(3<<26)|(old>>2):raise ValueError(f'Native stage reset call changed {p:08X}')
    validate_native_dependencies(ram)
    control=bytearray(0x100);struct.pack_into('<3I',control,0,MAGIC,manager,count)
    data=code+[(CONTROL,control),(ROW,bytes(0x80))]+hookparts
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        note='Native arena lifecycle preserved; only bounded reset positions and dead exclusion.',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=bytes(b).hex()) for p,b in data])
