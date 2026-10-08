"""Body-attached revival radius: projected translucent world-space annulus.

Uses the same native projection and GS packet submission as overhead bars.
All points are rebuilt from current actor XYZ and the live admission radius.
No game actors, terrain, native effects, input or camera data are changed.
"""
from native_map import A
import math
import struct
from prototype import Assembler
import teammate_revive as r
from regional import DISPLAY_H, Y_ORIGIN

SEGMENTS=32
# Inner/outer radius factors, opacity divisor. The central luminous band is
# centered exactly on the interaction radius; two weaker bands form its glow.
LAYERS=((0.93,1.07,6),(0.965,1.035,3),(0.988,1.012,1))
# These layers are vertical ribbons on the exact radius, not extra range.
# Values are fractions of the current wave height; the brighter upper strip
# makes the rising edge readable without filling the whole cylinder brightly.
WAVE_LAYERS=((0.,1.,2),(.92,1.,1))
WAVE_SAMPLES=256
WAVE_CRESTS=3


def fp(a,operation,dst,left,right):
    a.emit((17<<26)|(16<<21)|(right<<16)|(left<<11)|(dst<<6)|operation)


def quad():
    """a0 four projected XYZW rows, a1 ABGR -> submit two blended triangles."""
    a=Assembler(r.QUAD);a.addiu(29,29,-0x30)
    for i,reg in enumerate((16,17,18,31)):a.i(63,reg,29,8*i)
    a.move(16,4);a.move(17,5);a.call(A(0x100878));a.move(18,2);a.li(8,r.RING_TEMPLATE)
    for off in range(0,144,4):a.lw(9,8,off);a.sw(9,18,off)
    a.sw(17,18,80)
    for vertex in range(4):
        a.lw(8,16,vertex*16);a.lw(9,16,vertex*16+4)
        a.r(0,9,0,9,16);a.r(0x25,8,8,9);a.sw(8,18,112+vertex*8)
        a.lw(8,16,vertex*16+8);a.sw(8,18,116+vertex*8)
    a.addiu(4,18,144);a.call(A(0x100890))
    for i,reg in enumerate((16,17,18,31)):a.i(55,reg,29,8*i)
    a.addiu(29,29,0x30);a.jr();data=a.finish();assert len(data)<r.DRAW-r.QUAD;return data


def template():
    # Reviewed existing sprite packet setup, with PRIM=triangle strip+alpha
    # blending and four XYZ2 vertices instead of a two-vertex sprite.
    data=bytearray(r.bars.sprite_template())+bytes(16)
    struct.pack_into('<Q',data,64,0x44)
    struct.pack_into('<Q',data,96,0x2400000000008002)
    return bytes(data)


def ring(waves=True,quad_support=False):
    """a0 watched physical fighter, a1 active native viewport; preserve ABI."""
    a=Assembler(r.RING);r.save(a);a.move(17,4);a.move(16,5)
    a.call(r.GATE);a.branch(4,2,0,'done')
    a.li(8,r.CONTROL);a.lw(9,8,r.CFG['ring']);a.branch(4,9,0,'done')
    a.lw(9,8,r.CFG['opacity']);a.branch(4,9,0,'done');a.lw(18,8,8)
    a.li(8,r.core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,r.start.CONTROL);a.lw(8,8);a.branch(5,8,0,'done')
    r.pointer(a,16,832,'done')
    for off,upper in ((512,512),(516,512),(520,DISPLAY_H),(524,DISPLAY_H)):
        a.lw(8,16,off);a.i(11,9,8,upper);a.branch(4,9,0,'done')
    for lo,hi in ((512,516),(520,524)):
        a.lw(8,16,lo);a.lw(9,16,hi);a.r(0x2B,8,8,9);a.branch(4,8,0,'done')
    a.move(4,17);a.call(r.ACTOR);a.branch(4,2,0,'done')
    a.lw(8,3);a.branch(6,8,0,'done');a.lw(8,2,r.spectator.CPU_DRIVEN);a.branch(5,8,0,'done')
    # A living human owner sees allied recoverable bodies in their own view.
    # CPU-vs-CPU and an eliminated player merely spectating get no offer ring.
    a.li(11,r.spectator.CONTROL);a.lw(8,11);a.li(9,r.spectator.MAGIC);a.branch(5,8,9,'done')
    a.lw(8,11,r.takeover.F['version']);a.addiu(9,0,r.takeover.VERSION);a.branch(5,8,9,'done')
    a.lw(8,11,r.spectator.FIELDS['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'done')
    if quad_support:
        import quad_lifecycle as seats
        import quad_controller as pads
        a.li(8,pads.CONTROL);a.lw(9,8);a.li(10,pads.MAGIC);a.branch(5,9,10,'legacy_owner')
        a.li(11,seats.CONTROL)
        for port in range(4):
            a.lw(8,11,seats.F['owned']+4*port);a.branch(4,8,17,'human')
        a.jump('done');a.label('legacy_owner');a.li(11,r.spectator.CONTROL)
    for port in range(2):
        nxt=f'port{port}';a.lw(8,11,r.takeover.F['human_ports']);a.i(12,8,8,1<<port);a.branch(4,8,0,nxt)
        a.lw(8,11,r.takeover.F['owned']+4*port);a.branch(4,8,17,'human');a.label(nxt)
    a.jump('done');a.label('human')
    a.call(A(0x120AB0));a.addiu(4,16,320);a.call(A(0x120B80))
    a.move(19,0)
    a.label('body');a.branch(4,19,17,'next_body');a.r(0x26,8,19,17);a.i(12,8,8,1);a.branch(5,8,0,'next_body')
    a.move(4,19);a.call(r.ACTOR);a.branch(4,2,0,'next_body')
    a.move(20,2);a.lw(8,3);a.branch(7,8,0,'next_body');a.lw(8,3,4);a.branch(6,8,0,'next_body')
    r.eligible(a,20,19,True,'next_body')
    # Reject malformed or non-finite world coordinates before native VU math.
    for off in (16,20,24):
        a.lw(8,20,off);a.li(9,0x7FFFFFFF);a.r(0x24,8,8,9)
        a.li(9,struct.unpack('<I',struct.pack('<f',10000000.))[0]);a.r(0x2B,8,8,9);a.branch(4,8,0,'next_body')
    a.move(23,0)
    a.label('layer');a.li(21,r.ANGLES);a.move(22,0)
    a.label('segment')
    # Each quad's four corners live in world XZ, at this body's current Y.
    # Native projection makes the ring recede/tilt with the actual camera.
    for vertex,(angle_offset,factor_offset) in enumerate(((0,0),(0,4),(8,0),(8,4))):
        a.r(0,8,0,23,4);a.li(9,r.BANDS);a.r(0x2D,8,8,9)
        a.i(49,2,8,factor_offset)
        if waves:
            a.i(11,9,23,len(LAYERS));a.branch(5,9,0,f'flat_radius{vertex}')
            a.li(8,0x3F800000);a.emit((17<<26)|(4<<21)|(8<<16)|(2<<11))
            a.label(f'flat_radius{vertex}')
        a.li(8,r.CONTROL);a.i(49,1,8,r.CFG['radius']);fp(a,2,1,1,2)
        for off,angle in ((16,angle_offset),(24,angle_offset+4)):
            a.i(49,2,21,angle);fp(a,2,2,2,1);a.i(49,3,20,off);fp(a,0,2,2,3)
            a.i(57,2,29,0x2A0+(0 if off==16 else 8))
        if waves:
            a.i(11,9,23,len(LAYERS));a.branch(5,9,0,f'flat_height{vertex}')
            # Three traveling crests around the ring. Body-specific phase
            # prevents identical synchronized columns on nearby corpses.
            a.addiu(8,22,int(angle_offset!=0));a.r(0,9,0,8,4);a.r(0,8,0,8,3);a.r(0x21,9,9,8)
            a.r(0,8,0,19,4);a.r(0x21,8,8,19);a.r(0x21,9,9,8)
            a.li(8,r.CONTROL);a.lw(10,8,r.CFG['wave_phase']);a.r(2,10,0,10,8)
            a.r(0x21,9,9,10);a.i(12,9,9,WAVE_SAMPLES-1);a.r(0,9,0,9,2)
            a.li(10,r.WAVE_TABLE);a.r(0x21,9,9,10);a.i(49,4,9,0)
            a.i(49,5,8,r.CFG['wave_height']);fp(a,2,4,4,5)
            a.r(0,9,0,23,4);a.li(10,r.BANDS);a.r(0x21,9,9,10)
            a.i(49,5,9,factor_offset);fp(a,2,4,4,5)
            a.i(49,5,20,20);fp(a,1,4,5,4) # Negative native Y is up.
            a.i(57,4,29,0x2A4);a.jump(f'height_ready{vertex}')
            a.label(f'flat_height{vertex}')
        a.lw(8,20,20);a.sw(8,29,0x2A4)
        if waves:a.label(f'height_ready{vertex}')
        a.li(8,0x3F800000);a.sw(8,29,0x2AC)
        a.addiu(4,29,0x2B0+vertex*16);a.addiu(5,29,0x2A0);a.call(A(0x1210D8))
        a.branch(4,2,0,'next_segment');a.lw(8,29,0x2BC+vertex*16);a.branch(6,8,0,'next_segment')
        a.lw(8,29,0x2B8+vertex*16);a.branch(1,8,0,'next_segment')
        # Keep every submitted vertex in this native viewport. Rejecting the
        # small boundary segment prevents near-plane spikes and split leakage.
        for coord,lo,hi,origin in ((0,512,516,1792),(4,520,524,Y_ORIGIN)):
            a.lw(10,29,0x2B0+vertex*16+coord)
            a.lw(8,16,lo);a.addiu(8,8,origin);a.r(0,8,0,8,4)
            a.r(0x2A,9,10,8);a.branch(5,9,0,'next_segment')
            a.lw(8,16,hi);a.addiu(8,8,origin+1);a.r(0,8,0,8,4)
            a.r(0x2A,9,10,8);a.branch(4,9,0,'next_segment')
    a.li(8,r.CONTROL);a.lw(8,8,r.CFG['opacity'])
    a.r(0,9,0,23,4);a.li(10,r.BANDS);a.r(0x2D,9,9,10);a.lw(9,9,8)
    a.r(27,0,8,9);a.r(18,8,0);a.branch(4,8,0,'next_segment')
    a.r(0,8,0,8,24);a.li(5,0x00A0FF70);a.r(0x25,5,5,8)
    a.addiu(4,29,0x2B0);a.call(r.QUAD)
    a.label('next_segment');a.addiu(21,21,8);a.addiu(22,22,1);a.addiu(8,0,SEGMENTS)
    a.branch(5,22,8,'segment');a.addiu(23,23,1)
    if waves:
        a.addiu(8,0,len(LAYERS));a.branch(5,23,8,'layers_remaining')
        # Height zero is the exact previous flat visual, with no zero-height
        # wall packets or extra projection calls.
        a.li(8,r.CONTROL);a.lw(8,8,r.CFG['wave_height']);a.li(9,0x7FFFFFFF)
        a.r(0x24,8,8,9);a.branch(4,8,0,'next_body')
        a.label('layers_remaining')
    a.addiu(8,0,len(LAYERS)+(len(WAVE_LAYERS) if waves else 0));a.branch(5,23,8,'layer')
    a.label('next_body');a.addiu(19,19,1);a.branch(5,19,18,'body')
    a.call(A(0x120AC8))
    a.label('done');r.restore(a);a.jr();data=a.finish();assert len(data)<r.QUAD-r.RING;return data


def pieces(waves=True):
    angles=b''.join(struct.pack('<2f',math.cos(2*math.pi*i/SEGMENTS),math.sin(2*math.pi*i/SEGMENTS))
                    for i in range(SEGMENTS))+struct.pack('<2f',1.,0.)
    bands=b''.join(struct.pack('<2f2I',inside,outside,divisor,0) for inside,outside,divisor in LAYERS+(WAVE_LAYERS if waves else ()))
    result=[(r.RING,ring(waves)),(r.QUAD,quad()),(r.ANGLES,angles),(r.BANDS,bands),(r.RING_TEMPLATE,template())]
    if waves:
        samples=struct.pack('<256f',*(.6+.4*math.sin(2*math.pi*i/WAVE_SAMPLES) for i in range(WAVE_SAMPLES)))
        result.append((r.WAVE_TABLE,samples))
    return result
