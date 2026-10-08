"""Route two allied human pads without changing native actor/team identities.

The native pad accessor is called by the human input decoder. A fused human
uses either one real pad or a private merged record; physical pad records are
never overwritten. The fusion clock advances in active guest updates only.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import battle_mode_policy as mode
from input_script import RECORDS, RECORD_STRIDE
from native_map import ACTOR_HZ

HOOK, ACTOR_PAD, NATIVE_PAD = A(0x1DC2A0), 0x07190000, 0x07191000
MERGED, END = 0x07192000, 0x071A0000
MOVEMENT_MASK = 0x4AF0  # D-pad, Cross (step/dash), R1/R2 (vertical movement).
SWAP_UPDATES = 20*ACTOR_HZ  # Native battle loop waits two video blanks per update (30 Hz USA, 25 Hz European).
SAVED = (3, 8, 9, 10, 11, 12, 13, 14, 15)
NATIVE = elf_reader(elf_path(ROOT))[2]


def payload(takeover=False,three_humans=False):
    a=Assembler(ACTOR_PAD); a.addiu(29,29,-0x60)
    for i,r in enumerate(SAVED): a.i(63,r,29,i*8)
    a.li(8,mode.CONTROL); a.lw(9,8); a.li(10,mode.MAGIC)
    a.branch(5,9,10,'native'); a.lw(9,8,4); a.lw(10,28,-22364)
    a.branch(5,9,10,'native'); a.lw(9,8,12); a.addiu(10,0,mode.COOP)
    a.branch(5,9,10,'native'); a.lw(9,8,16); a.addiu(10,0,2)
    a.branch(4,9,10,'human_count')
    if three_humans:
        a.addiu(10,0,3);a.branch(4,9,10,'human_count')
    a.addiu(10,0,4);a.branch(5,9,10,'native');a.label('human_count')
    a.li(9,core.MODE); a.lw(10,9); a.addiu(11,0,1)
    a.branch(5,10,11,'native'); a.lw(10,9,8); a.lw(11,8,4)
    a.branch(5,10,11,'native'); a.lw(10,9,4); a.lw(11,8,8)
    a.branch(5,10,11,'native')
    # Use captured pointers; the engine temporarily aliases actor IDs in pairs.
    a.lw(9,8,24); a.addiu(10,0,-1); a.branch(4,9,10,'unfused')
    a.i(11,10,9,mode.emitted_actors()); a.branch(4,10,0,'native')
    a.r(0,9,0,9,2); a.li(10,core.POINTERS); a.r(0x2D,9,9,10)
    a.lw(9,9); a.branch(5,4,9,'native')
    a.lw(9,8,32); a.addiu(10,0,1); a.branch(4,9,10,'merge')
    a.branch(5,9,0,'pad0')  # player1 or invalid value is bounded to pad0.
    a.lw(9,8,36); a.lw(10,8,40); a.r(0x23,9,9,10)
    a.r(16,12,0); a.r(18,13,0); a.addiu(10,0,SWAP_UPDATES)
    a.r(27,0,9,10); a.r(18,11,0); a.r(17,0,12); a.r(19,0,13)
    a.i(12,11,11,1); a.branch(4,11,0,'pad0'); a.jump('pad1')
    a.label('unfused')
    if takeover:
        import spectator_takeover
        spectator_takeover.emit_pad(a,'legacy_unfused')
        a.label('legacy_unfused')
    a.li(9,core.POINTERS); a.lw(9,9,8)
    a.branch(4,4,9,'pad1'); a.jump('native')
    a.label('pad0'); a.li(2,RECORDS); a.jump('return')
    a.label('pad1'); a.li(2,RECORDS+RECORD_STRIDE); a.jump('return')
    a.label('merge'); a.li(9,RECORDS); a.li(10,MERGED)
    for off in range(0,RECORD_STRIDE,8):
        a.i(55,11,9,off); a.i(63,11,10,off)
    a.li(12,MOVEMENT_MASK); a.li(13,0xFFFFFFFF ^ MOVEMENT_MASK)
    for off in (0x148,0x14C,0x150,0x154,0x15C):
        a.lw(11,9,off); a.r(0x24,11,11,13)
        a.lw(14,9,RECORD_STRIDE+off); a.r(0x24,14,14,12)
        a.r(0x25,11,11,14); a.sw(11,10,off)
    for off in (0x130,0x134,0x138,0x13C):
        a.lw(11,9,RECORD_STRIDE+off); a.sw(11,10,off)
    a.move(2,10)
    a.label('return')
    for i,r in enumerate(SAVED): a.i(55,r,29,i*8)
    a.addiu(29,29,0x60); a.jr()
    a.label('native')
    for i,r in enumerate(SAVED): a.i(55,r,29,i*8)
    a.addiu(29,29,0x60); a.jump(NATIVE_PAD)
    data=a.finish(); assert len(data)<NATIVE_PAD-ACTOR_PAD; return data


def pieces():
    return [(ACTOR_PAD,payload()),(NATIVE_PAD,NATIVE(HOOK,0x20)),
            (HOOK,struct.pack('<2I',(2<<26)|(ACTOR_PAD>>2),0))]


def build_memory(ram,source='<prepared>'):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(mode.CONTROL)!=mode.MAGIC or u(mode.CONTROL+12)!=mode.COOP:
        return dict(serial=SERIAL,crc=CRC,blocks=[])
    expected=pieces()
    if ram[HOOK:HOOK+8]==expected[-1][1]:
        if any(ram[p:p+len(d)]!=d for p,d in expected):
            import spectator_takeover as takeover
            # The sole supported alternative is the complete, owned spectator
            # upgrade. Do not accept a prefix or ignore a changed native tail.
            takeover.validate_memory(ram)
            enhanced=[(ACTOR_PAD,payload(takeover=True)),*expected[1:]]
            if any(ram[p:p+len(d)]!=d for p,d in enhanced):raise ValueError('Co-op controller code changed')
        return dict(serial=SERIAL,crc=CRC,blocks=[])
    if ram[HOOK:HOOK+8]!=NATIVE(HOOK,8):raise ValueError('Unknown native pad resolver')
    if any(ram[ACTOR_PAD:END]):raise ValueError('Co-op pad reservation occupied')
    return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[
        dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in expected],
        movement_buttons=MOVEMENT_MASK,swap_updates=SWAP_UPDATES)
