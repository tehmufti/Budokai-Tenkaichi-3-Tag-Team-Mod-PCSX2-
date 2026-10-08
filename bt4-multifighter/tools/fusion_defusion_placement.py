"""Read-only native terrain checks for a separated defusion partner position."""
from native_map import A
import math
import struct
from prototype import Assembler
import spawn_placement as terrain
import fusion_duration as timer
import body_swap_commit as commit
import body_swap_resources as resources
import giant_options
import arena_bounds

ENTRY,CONTROL,END=timer.runner.RETIRE,timer.runner.RETIRE_CONTROL,timer.runner.END
QUERY,FOOTPRINT,BODY=ENTRY+0x2000,ENTRY+0x3000,ENTRY+0x4000
ROW,CANDIDATES=CONTROL+0x80,CONTROL+0x200


def candidate_positions(root,yaw,radii,grounded,center_offset_gap=0.):
    """Try a bounded set of separated positions, closest lateral ones first.

    Narrow terrain may block the eight cardinal/diagonal positions even when
    there is room just between them. Farther rings help a fused body standing
    beside a wall, while airborne-only vertical alternatives fit enclosed
    spaces without making a grounded partner appear floating in midair.
    """
    distance=max(24.,sum(radii)+8.)
    turns=(0,8,4,12,2,14,6,10,1,15,3,13,5,11,7,9)
    candidates=[]
    for scale in (1.,1.5,2.):
        for turn in turns:
            angle=yaw+turn*math.pi/8
            candidates.append((root[0]+math.cos(angle)*distance*scale,root[1],
                               root[2]-math.sin(angle)*distance*scale,1.))
    if not grounded:
        # Different character heights shift the sphere centers by different
        # amounts. Root spacing alone does not prove vertical separation.
        vertical=max(distance,sum(radii)+8.+abs(center_offset_gap))
        for sign in (-1,1):candidates.append((root[0],root[1]+sign*vertical,root[2],1.))
    return candidates


def code(guards,count,grounded):
    fp,constant=terrain.fp,terrain.constant
    a=Assembler(ENTRY);a.addiu(29,29,-0x80)
    for i,r in enumerate((16,17,18,31)):a.i(63,r,29,i*8)
    for i,off in enumerate(terrain.QUERY_GLOBALS):a.lw(8,28,off);a.sw(8,29,0x30+i*4)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done');a.lw(8,16,4);a.branch(5,8,0,'done')
    for at,value in guards:
        a.li(8,at);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error')
    a.li(17,CANDIDATES);a.move(18,0)
    a.label('candidate');a.li(8,ROW)
    for off in range(0,16,4):a.lw(9,17,off);a.sw(9,8,0x10+off)
    if grounded:
        # Nine floor samples reject ledges; preserve the current height when
        # airborne rather than dropping a flying fusion to the ground.
        a.li(4,ROW);a.call(FOOTPRINT);a.branch(4,2,0,'retry')
        a.li(8,ROW);a.i(49,0,8,0x14);a.i(49,1,16,0x20)
        fp(a,1,0,0,1);fp(a,5,0,0);constant(a,1,16)
        fp(a,0x36,0,0,1);a.branch(17,8,0,'retry')
    # BODY checks solid terrain, but a valid sector can extend beyond the
    # actual flight boundary. Test the live collision sphere center after
    # the floor query adjusts Y, including expanded/destructed map limits.
    a.li(4,ROW)
    for off in (0,8):a.lw(8,4,0x10+off);a.sw(8,4,0x60+off)
    a.i(49,0,4,0x14);a.i(49,1,4,0x24);fp(a,0,0,0,1);a.i(57,0,4,0x64)
    arena_bounds.emit_inside(a,4,'retry','defusion',point=0x60)
    a.call(BODY);a.branch(4,2,0,'retry')
    a.li(8,ROW)
    for off in range(0,16,4):a.lw(9,8,0x10+off);a.sw(9,16,0x70+off)
    a.addiu(8,0,1);a.sw(8,16,0x24);a.jump('complete')
    a.label('retry');a.addiu(17,17,16);a.addiu(18,18,1);a.li(8,count);a.branch(5,18,8,'candidate')
    # If enclosed on every side, retain the occupied footprint. Never freeze
    # a match or put a fighter through solid terrain to enforce spacing.
    a.label('complete');a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    a.label('error');a.li(8,110);a.sw(8,16,4)
    a.label('done')
    for i,off in enumerate(terrain.QUERY_GLOBALS):a.lw(8,29,0x30+i*4);a.sw(8,28,off)
    for i,r in enumerate((16,17,18,31)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x80);a.jr();return a.finish()


def build_memory(ram,snap,receipt):
    u=lambda p:commit.u(ram,p)
    f=lambda p:struct.unpack_from('<f',ram,p)[0]
    require=commit.require
    require(not any(ram[ENTRY:END]),'Defusion placement workspace occupied')
    model=snap['source']['model'];partner=snap['partner']['model']
    root=struct.unpack_from('<4f',ram,model+2416);yaw=f(model+2404)
    require(all(math.isfinite(v)for v in (*root,yaw)),'Invalid defusion position')
    radii=[]
    for body in (receipt['staged_model'],partner):
        radius=f(body+0x1004)
        require(.1<=radius<=512,'Invalid restored body radius');radii.append(radius)
    # Retained partner's neutral sphere is still valid even though hidden.
    center=struct.unpack_from('<3f',ram,u(partner+4000))
    oldroot=struct.unpack_from('<3f',ram,partner+2416)
    offset=center[1]-oldroot[1]
    require(math.isfinite(offset)and abs(offset)<1024,'Invalid partner sphere offset')
    grounded=u(snap['source']['actor']+2376)==11
    gap=0.
    if not grounded:
        restored=receipt['staged_model'];sphere=u(restored+4000)
        require(commit.ptr(ram,sphere,32),'Restored body sphere unavailable')
        restored_offset=f(sphere+4)-f(restored+2420)
        require(math.isfinite(restored_offset)and abs(restored_offset)<1024,'Invalid restored sphere offset')
        gap=restored_offset-offset
    candidates=candidate_positions(root,yaw,radii,grounded,gap)
    stage=u(terrain.STAGE);require(commit.ptr(ram,stage,68),'Stage unavailable during defusion')
    sectors=u(stage+56);require(1<=sectors<=4096,'Invalid stage sector count')
    guards=[(snap['record'],3),(snap['record']+72,snap['generation']),
        (timer.core.ACTORS,snap['world']['manager']),(terrain.STAGE,stage),(stage+56,sectors),
        (timer.native.CONTROL+16,1),(timer.native.CONTROL+20,1)]
    for at,size in ((A(0x230B38),0xC0),(A(0x1B14C0),0xF8),(A(0x23FDB0),0xC0),
                    (A(0x1B26E0),0x108),(A(0x1B1708),0x1B0),(A(0x1B16F0),0x18),(A(0x240110),0x28)):
        require(bytes(ram[at:at+size])==giant_options.native_helper(ram,at,size,timer.body.NATIVE),
                f'Defusion geometry helper changed:{at:08X}')
    control=bytearray(0x80);struct.pack_into('<I',control,8,snap['world']['manager'])
    struct.pack_into('<f',control,0x20,root[1]);struct.pack_into('<I',control,64,sectors)
    struct.pack_into('<4f',control,0x70,*root)
    row=bytearray(0x80);struct.pack_into('<2f',row,0x20,radii[1],offset)
    struct.pack_into('<f',row,0x5C,root[1]-32)
    # Output and row occupy different ranges even though both are private.
    output=CONTROL+0x70
    pieces=[(ENTRY,code(guards,len(candidates),grounded)),(CONTROL,bytes(control)),(ROW,bytes(row)),
        (CANDIDATES,b''.join(struct.pack('<4f',*v)for v in candidates)),
        (QUERY,timer.core.rebound(terrain.query_code,QUERY=QUERY,CONTROL=CONTROL)()),
        (FOOTPRINT,timer.core.rebound(terrain.footprint_code,QUERY=QUERY,FOOTPRINT=FOOTPRINT,BODY=BODY)()),
        (BODY,timer.core.rebound(terrain.body_code,BODY=BODY,CANDIDATES=CANDIDATES,CONTROL=CONTROL)())]
    return resources.parts_manifest(ram,pieces,entry=ENTRY,control=CONTROL,defusion_placement=True,
        output=output,guards=guards,candidate_positions=candidates,grounded=grounded)
