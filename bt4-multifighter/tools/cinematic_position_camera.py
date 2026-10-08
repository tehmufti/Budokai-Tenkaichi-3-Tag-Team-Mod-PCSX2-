"""Keep authenticated unbound cinematic cameras with in-place staged fighters.

Bound tracks already derive their frame from the relocated model. Unbound
animation anchors and explicit camera positions temporarily receive the same
rigid offset as the actual cinematic owner. Native camera timing runs once;
the input anchor is restored while the computed camera/VU state stays intact.

Moved with cinematic_position to 0x06F8C000 (beta.37 movement stream); the story gate applies when
story_cinematics is installed (the local project developer tree).
"""
import struct

from native_map import A,CRC,SERIAL,elf_path
from prototype import Assembler,ROOT,elf_reader
import fresh_team_combat as core
import fusion_partner_lifecycle as full

BASE,END=0x06F8C000,0x06F8E000
CODE,OWNED,NATIVE,CONTROL=BASE,BASE+0x1000,BASE+0x1800,BASE+0x1F00
MAGIC=0x50434131
ENTRY=A(0x23D510)
# Stable ABI shared with cinematic_position; no module import cycle.
POSITION_CONTROL,POSITION_ROWS,POSITION_STRIDE=0x06F87800,0x06F87000,0x80
POSITION_MAGIC=0x4E435231


def jump(target):return struct.pack('<2I',(2<<26)|(target>>2),0)


def emit_owner_row(a,fail,tag):
    """Find the captured shared row of a proven running camera owner.

    Clobbers t0..t3 and s0..s7, no native calls or FPU/HI/LO writes. Returns
    s1=camera, s2=shared row, s7=explicit-position flag. CAMERA_ROW is only
    advisory: a concurrent placement must not suppress an earlier owned track.
    """
    import camera_continuity as continuity
    import result_presentation as results
    import special_camera_arbitration as arbitration
    import cinematic_position
    import team_intro

    label=lambda name:tag+'_'+name
    core.gate(a,fail)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail)
    a.li(16,POSITION_CONTROL);a.lw(8,16);a.li(9,POSITION_MAGIC);a.branch(5,8,9,fail)
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,fail)
    a.lw(8,16,8);a.branch(5,8,10,fail);a.lw(8,16,12);a.branch(4,8,0,fail)
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,fail)
    a.li(8,team_intro.BATTLE);a.lw(20,8);arbitration.pointer(a,20,4,fail)
    a.lw(8,20);a.addiu(9,0,3);a.branch(5,8,9,fail)
    a.li(8,results.RESULT);a.lw(8,8);a.branch(5,8,0,fail)
    a.li(8,continuity.SCENE_FLAGS);a.lw(8,8);a.i(12,8,8,0x2000);a.branch(5,8,0,fail)
    scenario=cinematic_position.story_cinematics()
    if scenario is not None:scenario.emit_active(a,fail,label('not_scenario'))

    a.lw(17,28,-22180);arbitration.pointer(a,17,832,fail)
    # Bound tracks already follow the translated model's native anchor.
    for off in (768,772):a.lw(8,17,off);a.branch(5,8,0,fail)
    a.lw(23,17,812);a.branch(5,23,0,label('camera_running'))
    a.lw(8,17,776);a.i(12,8,8,3);a.addiu(9,0,1);a.branch(5,8,9,fail)
    a.lw(11,17,704);arbitration.pointer(a,11,24,fail)
    a.label(label('camera_running'))

    # Match the active director's actual model and track, or an authenticated
    # arbitration receipt. Actor actions and last placement are not ownership.
    a.li(8,arbitration.DIRECTOR);a.lw(20,8);arbitration.pointer(a,20,28,label('arbitrated'))
    a.lw(8,20,12);a.addiu(9,0,1);a.branch(5,8,9,label('arbitrated'))
    a.lw(22,20,24);a.i(11,8,22,12);a.branch(4,8,0,label('arbitrated'))
    a.lw(8,20,4);a.branch(5,8,22,label('arbitrated'))
    a.lw(8,20);a.lw(9,17,704);a.branch(5,8,9,label('arbitrated'));a.jump(label('scan'))
    a.label(label('arbitrated'));arbitration.emit_owned_camera(a,fail)
    a.li(8,arbitration.CONTROL);a.lw(22,8,24);a.i(11,8,22,12);a.branch(4,8,0,fail)

    # Resolve model ID through the physical pointer table. In a paired scene
    # the victim may own the track; both participants use the source root.
    a.label(label('scan'));a.li(18,POSITION_ROWS);a.move(20,0)
    a.label(label('find'))
    a.lw(8,18,4);a.addiu(9,0,1);a.branch(5,8,9,label('next'))
    a.lw(8,18,8);a.addiu(8,8,-1);a.i(11,8,8,4);a.branch(4,8,0,label('next'))
    a.lw(19,18);arbitration.pointer(a,19,0x1600,label('next'))
    a.r(0,8,0,20,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(9,9);a.branch(5,9,19,label('next'))
    a.lw(8,19,12);a.branch(4,8,22,label('found'))
    a.label(label('next'));a.addiu(20,20,1);a.addiu(18,18,POSITION_STRIDE)
    a.lw(10,16,8);a.r(0x2B,8,20,10);a.branch(5,8,0,label('find'));a.jump(fail)
    a.label(label('found'))
    a.r(0,8,0,22,2);a.li(9,core.MODELS);a.r(0x21,9,9,8);a.lw(11,9)
    arbitration.pointer(a,11,0x1670,fail);a.lw(8,11,16);a.branch(5,8,22,fail)
    a.lw(21,18,12);a.lw(10,16,8);a.r(0x2B,8,21,10);a.branch(4,8,0,fail)
    a.r(0,8,0,21,7);a.li(18,POSITION_ROWS);a.r(0x21,18,18,8)
    a.lw(8,18,4);a.addiu(9,0,1);a.branch(5,8,9,fail)
    a.lw(8,18,8);a.addiu(8,8,-1);a.i(11,8,8,4);a.branch(4,8,0,fail)
    a.lw(8,18,12);a.branch(5,8,21,fail)
    a.lw(8,18,68);a.li(9,A(0x2FEBE0));a.lw(9,9);a.branch(5,8,9,fail)
    a.lw(19,18);arbitration.pointer(a,19,0x1600,fail)
    a.r(0,8,0,21,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(9,9);a.branch(5,9,19,fail)
    a.lw(22,19,12);a.i(11,8,22,12);a.branch(4,8,0,fail)
    a.r(0,8,0,22,2);a.li(9,core.MODELS);a.r(0x21,9,9,8);a.lw(11,9)
    arbitration.pointer(a,11,0x1670,fail);a.lw(8,11,16);a.branch(5,8,22,fail)


def owned_code():
    """a0=captured row; v0=1 if its root owns a live unbound/direct track.

    This lifetime query makes no native calls and changes no telemetry. It
    preserves every other GPR at 128 bits and leaves FPU/HI/LO untouched.
    """
    a=Assembler(OWNED);saved=tuple(range(8,12))+tuple(range(16,24))
    frame=16*len(saved);a.addiu(29,29,-frame)
    for i,r in enumerate(saved):a.i(31,r,29,16*i)
    emit_owner_row(a,'no','life')
    # A root may keep both participants' rows alive, but stale or unrelated
    # rows must not inherit that proof merely by pointing at the same index.
    a.li(8,POSITION_ROWS);a.r(0x23,9,4,8);a.i(12,8,9,POSITION_STRIDE-1);a.branch(5,8,0,'no')
    a.r(2,20,0,9,7);a.lw(10,16,8);a.r(0x2B,8,20,10);a.branch(4,8,0,'no')
    a.lw(8,4,4);a.addiu(9,0,1);a.branch(5,8,9,'no')
    a.lw(8,4,8);a.addiu(8,8,-1);a.i(11,8,8,4);a.branch(4,8,0,'no')
    a.lw(8,4,12);a.branch(5,8,21,'no')
    a.lw(8,4);a.r(0,9,0,20,2);a.li(11,core.POINTERS);a.r(0x21,11,11,9);a.lw(11,11);a.branch(5,8,11,'no')
    a.addiu(2,0,1);a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done')
    for i,r in enumerate(saved):a.i(30,r,29,16*i)
    a.addiu(29,29,frame);a.jr()
    code=a.finish()
    if OWNED+len(code)>NATIVE:raise ValueError('Cinematic position camera lifetime query exceeds its reservation')
    return code


def wrapper():
    a=Assembler(CODE);full.save(a);a.sw(0,29,0x300)
    emit_owner_row(a,'native','shift')

    # Input +736 is Euler angles, not a target position. Explicit camera
    # overrides translate only +720. Animated tracks translate +608's anchor.
    a.addiu(20,17,656);a.addiu(21,0,1);a.branch(4,23,0,'anchor_ready')
    a.addiu(20,17,720);a.addiu(21,0,2);a.label('anchor_ready')
    for axis in range(3):
        # Refuse nonfinite source coordinates or deltas before any write.
        for reg,off in ((18,16+4*axis),(20,4*axis)):
            a.lw(8,reg,off);a.r(2,8,0,8,23);a.i(12,8,8,255);a.addiu(9,0,255);a.branch(4,8,9,'native')
    for axis in range(3):
        a.lw(8,20,4*axis);a.sw(8,29,0x320+4*axis)
        a.i(49,0,20,4*axis);a.i(49,1,18,16+4*axis)
        a.emit((17<<26)|(16<<21)|(1<<16)|(0<<11)|(0<<6))
        a.i(57,0,29,0x340+4*axis);a.lw(8,29,0x340+4*axis)
        a.r(2,8,0,8,23);a.i(12,8,8,255);a.addiu(9,0,255);a.branch(4,8,9,'native')
    # Publish all axes only after every sum passed; a finite-but-overflowing
    # damaged offset cannot partially edit the native anchor.
    a.sw(21,29,0x300);a.sw(17,29,0x304);a.sw(20,29,0x308)
    for axis in range(3):a.lw(8,29,0x340+4*axis);a.sw(8,20,4*axis)
    a.li(8,CONTROL);a.lw(9,8,16);a.addiu(9,9,1);a.sw(9,8,16)
    a.label('native');full.restore(a,finish=False);a.call(NATIVE)
    # Preserve native output registers/FPU values, then restore only our
    # temporary input. Keep its computed matrix and GS/VU binding unchanged.
    full.save(a,after=True)
    a.lw(8,29,0x300);a.branch(4,8,0,'done')
    a.lw(17,29,0x304);a.lw(8,28,-22180);a.branch(5,8,17,'done')
    a.lw(20,29,0x308)
    for axis in range(3):
        a.lw(8,20,4*axis);a.lw(9,29,0x340+4*axis);a.branch(5,8,9,'done')
    for axis in range(3):a.lw(8,29,0x320+4*axis);a.sw(8,20,4*axis)
    a.label('done');full.restore(a);a.jr()
    code=a.finish()
    if CODE+len(code)>OWNED:raise ValueError('Cinematic position camera code exceeds its reservation')
    return code


def build_memory(ram,config=None,source='<prepared>',*,settings=None):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if not any(ram[POSITION_CONTROL:POSITION_CONTROL+16]):
        return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[],control=CONTROL,
                    note='Cinematic placement policy is disabled; native cameras are unchanged.')
    if len(ram)!=0x8000000:raise ValueError('Cinematic position camera needs 128 MiB RAM')
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if (u(POSITION_CONTROL),u(POSITION_CONTROL+4),u(POSITION_CONTROL+8))!=(POSITION_MAGIC,manager,count):
        raise ValueError('Cinematic position camera requires the matching placement policy')
    original=elf_reader(elf_path(ROOT))[2](ENTRY,8)
    if any(w>>26 in (1,2,3,4,5,6,7,20,21) for w in struct.unpack('<2I',original)):
        raise ValueError('Native cinematic update prologue cannot be relocated')
    code,owned=wrapper(),owned_code();native=original+jump(ENTRY+8)
    if any(ram[BASE:END]):
        if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(MAGIC,manager,count):
            raise ValueError('Cinematic position camera reservation is occupied')
        for address,data in ((CODE,code),(OWNED,owned),(NATIVE,native),(ENTRY,jump(CODE))):
            if bytes(ram[address:address+len(data)])!=data:raise ValueError('Cinematic position camera code changed')
        return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[],control=CONTROL)
    if bytes(ram[ENTRY:ENTRY+8])!=original:raise ValueError('Native cinematic camera update hook changed')
    control=struct.pack('<4I',MAGIC,manager,count,1)+bytes(48)
    pieces=[(CODE,code),(OWNED,owned),(NATIVE,native),(CONTROL,control),(ENTRY,jump(CODE))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        note='Model-bound cameras follow native anchors; authenticated unbound cameras follow the shared placement offset.',
        limitations=['An unbound track without a proven current actor owner keeps its native framing.'],
        blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in pieces])
