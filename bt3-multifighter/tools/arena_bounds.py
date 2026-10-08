"""Read the native arena's live flight limits, including scaled/destroyed maps.

Native 23FEB0 subtracts 100 from the authored radial boundary; 23FEF8 and
23FF38 read its top/bottom planes. Y increases downward. Terrain/solid-body
checks remain separate: a sector existing does not prove a point is playable.
"""
from native_map import A
import math
import struct

STAGE = A(0x2FEBE0)


def read(ram, margin=0.0):
    """Return (usable radius, ceiling Y, bottom Y), or None for invalid data."""
    def ptr(p,n):return p%4==0 and 0x100000<=p<=len(ram)-n
    if len(ram)<=STAGE+4:return None
    stage=struct.unpack_from('<I',ram,STAGE)[0]
    if not ptr(stage,68):return None
    bounds=struct.unpack_from('<I',ram,stage+64)[0]
    if not ptr(bounds,12):return None
    radius,top,bottom=struct.unpack_from('<3f',ram,bounds)
    if not all(math.isfinite(v) and abs(v)<1e6 for v in (radius,top,bottom)):return None
    radius-=100+margin
    if radius<=0 or top>=bottom:return None
    return radius,top,bottom


def inside(point,bounds,radius=0.0,margin=1.0):
    if bounds is None or not all(math.isfinite(v) for v in point[:3]):return False
    limit,top,bottom=bounds;limit-=radius+margin
    x,y,z=point[:3]
    return limit>0 and x*x+z*z<=limit*limit and top+radius+margin<=y<=bottom-radius-margin


def emit_inside(a,row,fail,tag,point=0x10,radius=0x20,margin=1.0):
    """Branch to fail unless row's whole footprint is within the live arena.

    Clobbers t0..t5 and f0..f6; row must be a saved register or a0. No calls,
    writes, native query globals, or arbitrary per-map constants are used.
    """
    from spawn_placement import fp,constant
    def ptr(reg,n):
        a.i(12,9,reg,3);a.branch(5,9,0,fail)
        a.li(9,0x100000);a.r(0x2B,9,reg,9);a.branch(5,9,0,fail)
        a.li(9,0x8000000-n+1);a.r(0x2B,9,reg,9);a.branch(4,9,0,fail)
    def finite(reg,off):
        a.lw(9,reg,off);a.li(10,0x7FFFFFFF);a.r(0x24,9,9,10)
        a.li(10,0x49742400);a.r(0x2B,9,9,10);a.branch(4,9,0,fail)
    for off in (point,point+4,point+8,radius):finite(row,off)
    a.li(8,STAGE);a.lw(12,8);ptr(12,68)
    a.lw(12,12,64);ptr(12,12)
    for off in (0,4,8):finite(12,off)
    a.i(49,0,row,radius);constant(a,1,margin);fp(a,0,0,0,1)
    a.i(49,1,12,0);constant(a,2,100);fp(a,1,1,1,2);fp(a,1,1,1,0)
    constant(a,2,0);fp(a,0x34,0,2,1);a.branch(17,8,0,fail)
    a.i(49,2,row,point);a.i(49,3,row,point+8)
    fp(a,2,2,2,2);fp(a,2,3,3,3);fp(a,0,2,2,3);fp(a,2,1,1,1)
    fp(a,0x36,0,2,1);a.branch(17,8,0,fail)
    a.i(49,3,row,point+4);a.i(49,4,12,4);a.i(49,5,12,8)
    fp(a,0,4,4,0);fp(a,1,5,5,0)
    fp(a,0x36,0,4,3);a.branch(17,8,0,fail)
    fp(a,0x36,0,3,5);a.branch(17,8,0,fail)
