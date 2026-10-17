"""Original resident battle HUD art, independently placed inside each viewport.

Uses the game's own frame, gauge, pip, digit and current-model portrait textures.
No selection portrait substitutes, shared two-side widget mutation, camera-matrix
changes, new texture assets or host polling. The native upload queue retains its
authored HUD/portrait VRAM banks; only portrait upload-cache invalidation follows
the same policy as native21F438. All sprite positions preserve the world scissor.
"""
from native_map import A, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import viewport_hud as hud
from regional import tbp, Y_ORIGIN
from native_map import ACTOR_HZ, SERIAL

SPRITE,TEMPLATE,NATIVE_PANEL,COMPACT = 0x072D4000,0x072D5800,0x072D6000,0x072DC000
SETTINGS = 0x072DE000
METERS, METER_BYTES = 0x072DE100,12*24
# HP trail identity per fighter: row character | model character << 16, then the clock until which a lowered HP
# snaps instead of animating (a form, fusion, defusion, body or revival change is not damage). PASSES holds the
# clocks of the current and previous HUD pass: a fighter the previous pass did not draw is newly shown (target
# switch, swap) and starts from its own current HP, never from a stale trail.
IDENTITY, IDENTITY_BYTES = 0x072DE240,12*8
PASSES = 0x072DE2C0
SETTLE = round(.5*ACTOR_HZ)
# Where each view's own fighter panel was last drawn, per view (hud.VIEWS order): x, y, width | mirrored << 16 |
# anamorphic << 17, and the HUD pass (hud.CONTROL+20) that drew it. The tag meter reads it to sit beside its own HP.
OWN, OWN_STRIDE = 0x072DE300, 16
assert METERS+METER_BYTES<=IDENTITY and IDENTITY+IDENTITY_BYTES<=PASSES and PASSES+8<=OWN
assert OWN+OWN_STRIDE*hud.MAX_VIEWS<=0x072DF000
# Native 21C5B0/21C940 use palette 5 (blue) from this layer up: slti 7 on BT3 (all regions), slti 4 on BT4.
BLUE_LAYER = 4 if SERIAL == 'SLUS-21978' else 7
# The native pip records' own palettes (21CA60 only shows/hides them): BT3 draws every pip green, BT4 colours
# pip k like HP layer k (orange, yellow, green, green, blue, blue).
PIP_PALETTES = (3,4,1,1,5,5) if SERIAL == 'SLUS-21978' else (1,)*6
# Status-node positions relative to the atlas6 frame, read from each game's resident node tree (*(gp-22324): node
# translations +16..+28, sprite records +32/+36, children +40/+44): portrait (64 x 64), stock digit (32 x 32), stock
# frame (atlas 15, 48 x 12) and the stock fill's origin. Health (69,9), pips (73,2) and ki (64,27) are shared. BT4's
# hexagonal frame holds its portrait at (3,-2) and its digit in a housing right of the ki bars, the blast-stock gauge
# beside it; BT3's positions there put the portrait 13 px right of and 5 px below the hexagon's centre.
LAYOUTS = dict(bt3=((16,3),(7,30),(27,46),(34,49)), bt4=((3,-2),(106,20),(132,25),(140,28)))
LAYOUT = 'bt4' if SERIAL == 'SLUS-21978' else 'bt3'
UPLOAD, INVALIDATE = A(0x224F00),A(0x21F438)
PARAM=0x120
NATIVE_RANGES=((UPLOAD,0x1C8),(INVALIDATE,0x48),(A(0x1006E8),8),(A(0x100738),8))
# Parameter words: bundle,index,palette_delta,u0,v0,u1,v1,x0,y0,x1,y1,
# flags,color. Flags: bit0 portrait bank; bit1 XY already in GS 1/16 pixels.
# Legacy callers without bit1 still use logical512x448 whole screen pixels.


def dispatch():
    a=Assembler(hud.PANEL)
    # Preserve the caller's role t0 and every other scratch register.
    a.addiu(29,29,-16);a.i(63,8,29,0);a.i(63,9,29,8)
    a.li(8,SETTINGS);a.lw(9,8);a.branch(4,9,0,'compact')
    a.i(55,8,29,0);a.i(55,9,29,8);a.addiu(29,29,16);a.jump(NATIVE_PANEL)
    a.label('compact');a.i(55,8,29,0);a.i(55,9,29,8);a.addiu(29,29,16);a.jump(COMPACT)
    return a.finish()


def template():
    # The same ALPHA/TEST/PABE setup as the existing healthbar emitter. Texture
    # sampling uses native PSMT8 TEX0 plus explicit nearest TEX1 and clamp modes.
    setup=((68,66),(196608,71),(0,74),(0,20),(5,8),(0x156,0),
           (0x3F80000080808080,1),(0,6))
    out=struct.pack('<2Q',len(setup)|(1<<60),14)
    out+=b''.join(struct.pack('<2Q',v,r)for v,r in setup)
    out+=struct.pack('<6Q',0x4400000000008001,0x5353,0,0,0,0)
    assert len(out)==192
    return out


def pointer(a,r,size,tag):
    a.li(10,0x100000);a.r(0x2B,11,r,10);a.branch(5,11,0,tag)
    a.li(10,0x08000000-size);a.r(0x2B,11,10,r);a.branch(5,11,0,tag)
    a.i(12,11,r,3);a.branch(5,11,0,tag)


def sprite_code(safe_edges=True,isolated=True):
    a=Assembler(SPRITE);hud.save(a);a.move(16,4)
    a.lw(17,16);pointer(a,17,32,'done');a.lw(18,17,16)
    pointer(a,18,64,'done');a.lw(8,17);a.i(11,9,8,65);a.branch(4,9,0,'done')
    a.lw(19,16,4);a.lw(20,16,8);a.r(0x21,20,19,20)
    for r in (19,20):a.r(0x2B,9,r,8);a.branch(4,9,0,'done')
    a.r(0,19,0,19,6);a.r(0x21,19,18,19);pointer(a,19,64,'done')
    a.r(0,20,0,20,6);a.r(0x21,20,18,20);pointer(a,20,64,'done')
    # Only bounded native8-bit indexed sprites are supported. Wrong/incomplete
    # reload resources omit the art for this frame rather than reading stale RAM.
    a.lw(8,19,48);a.r(2,9,0,8,20);a.i(12,9,9,63);a.addiu(10,0,19);a.branch(5,9,10,'done')
    for desc,off in ((19,8),(20,12)):
        a.lw(9,desc,off);a.i(11,10,9,0x81);a.branch(5,10,0,'done')
        a.li(10,0x20081);a.r(0x2B,10,9,10);a.branch(4,10,0,'done')
        a.lw(8,desc,56 if off==8 else 60);pointer(a,8,0x80,'done')
        a.r(0x21,8,8,9);a.li(10,0x08000000);a.r(0x2B,10,8,10);a.branch(4,10,0,'done')
    a.lw(21,16,44);a.i(12,26,21,2);a.i(12,21,21,1)
    a.addiu(22,0,tbp(0x2A00));a.addiu(23,0,tbp(0x2C80))
    a.branch(4,21,0,'upload')
    a.call(INVALIDATE);a.sw(0,19,40);a.sw(0,20,40)
    a.addiu(22,0,tbp(0x2C00));a.addiu(23,0,tbp(0x2CD0))
    a.label('upload');a.move(4,17);a.lw(5,16,4);a.lw(6,16,8);a.move(7,22);a.move(8,23);a.call(UPLOAD)
    a.call(A(0x100878));a.move(24,2);a.li(8,TEMPLATE)
    for off in range(0,192,4):a.lw(9,8,off);a.sw(9,24,off)
    # TEX1 MMAG/MMIN filter controls the original atlas, never a generated
    # low-resolution copy. Keep nearest selectable for original pixel edges.
    a.li(8,SETTINGS);a.lw(8,8,24);a.branch(4,8,0,'nearest_filter')
    a.addiu(8,0,0x60);a.sw(8,24,64)
    a.label('nearest_filter')
    if safe_edges:
        # Clamp each atlas cell before bilinear filtering. The full-texture
        # clamp allowed the health/pip/stock edges to sample neighboring art.
        a.addiu(12,0,10) # WMS=WMT=REGION_CLAMP
        for lo,hi,shift_min,shift_max,tag in ((12,20,4,14,'u'),(16,24,24,34,'v')):
            a.lw(8,16,lo);a.lw(9,16,hi);a.r(0x2B,10,8,9)
            a.branch(5,10,0,tag+'_ordered');a.move(11,8);a.move(8,9);a.move(9,11)
            a.label(tag+'_ordered');a.branch(4,8,9,tag+'_nonempty');a.addiu(9,9,-1)
            a.label(tag+'_nonempty')
            a.r(0x38,8,0,8,shift_min)
            a.r(0x3C if shift_max>=32 else 0x38,9,0,9,shift_max%32)
            a.r(0x25,12,12,8);a.r(0x25,12,12,9)
        a.i(63,12,24,80) # CLAMP_1 value in template
    a.lw(8,16,48);a.sw(8,24,112)
    a.lw(8,19,48);a.lw(9,19,32);a.r(0x21,9,9,22);a.r(0x25,8,8,9);a.sw(8,24,128)
    a.lw(8,19,52);a.lw(9,20,36);a.r(0x21,9,9,23);a.r(0,9,0,9,5);a.i(13,8,8,4);a.r(0x25,8,8,9);a.sw(8,24,132)
    for first,uv,xy in ((160,12,28),(176,20,36)):
        for off,dest,xbias,ybias in ((uv,first,0,0),(xy,first+8,1792,Y_ORIGIN)):
            a.lw(8,16,off);a.lw(9,16,off+4)
            if xbias:a.branch(5,26,0,f'fixed_xy_{first}')
            a.r(0,8,0,8,4);a.r(0,9,0,9,4)
            if xbias:
                a.label(f'fixed_xy_{first}');a.addiu(8,8,xbias*16);a.addiu(9,9,ybias*16)
            else:a.addiu(8,8,8);a.addiu(9,9,8)
            a.r(0,9,0,9,16);a.r(0x25,8,8,9);a.sw(8,24,dest)
    a.addiu(4,24,192);a.call(A(0x100890))
    if isolated:
        # GS state outlives a GIF packet. Native timer/clash widgets do not
        # set CLAMP themselves: a tiny atlas-cell REGION_CLAMP turns them
        # into solid rectangles. Return sampling to the native HUD defaults.
        a.call(A(0x100878));a.move(24,2)
        for off,value in ((0,0x8002),(4,0x10000000),(8,14),(12,0),
                          (16,5),(20,0),(24,8),(28,0),
                          (32,0),(36,0),(40,20),(44,0)):
            a.li(8,value);a.sw(8,24,off)
        a.addiu(4,24,48);a.call(A(0x100890))
    a.branch(4,21,0,'done')
    # A different panel may have replaced either stock portrait VRAM slot.
    # Leave the native two-side cache invalid, as21F438 does before each draw.
    a.call(INVALIDATE);a.sw(0,19,40);a.sw(0,20,40)
    a.label('done');hud.restore(a);a.jr();data=a.finish();assert len(data)<TEMPLATE-SPRITE;return data


def scale(a,dst,source):
    # Keep native GS subpixels throughout composition. Rounding each edge to
    # whole pixels makes identical angled ki bands alternate in width/gap.
    a.r(25,0,source,19);a.r(18,dst,0);a.r(2,dst,0,dst,4)


def emit_sprite(a,index,palette,uv,box,*,bundle=22,portrait=False,color=0x80808080,
                mirror_uv=True,uv_registers=(),box_registers=()):
    """UV and original256px-wide HUD coordinates; role1 mirrors both."""
    a.sw(bundle,29,PARAM);a.addiu(8,0,index);a.sw(8,29,PARAM+4)
    if isinstance(palette,tuple):a.sw(palette[0],29,PARAM+8)
    else:a.addiu(8,0,palette);a.sw(8,29,PARAM+8)
    for k,value in enumerate(uv):
        if k in uv_registers:a.sw(value,29,PARAM+12+4*k)
        else:a.li(8,value);a.sw(8,29,PARAM+12+4*k)
    # box describes x0,y0,x1,y1 in unscaled native atlas geometry.
    for k,value in enumerate(box):
        if k in box_registers:a.move(8,value)
        else:a.li(8,value)
        scale(a,9,8);a.sw(9,29,PARAM+28+4*k)
    tag=f'sprite_{a.pc:x}'
    a.branch(4,20,0,tag)
    a.lw(8,29,PARAM+28);a.lw(9,29,PARAM+36)
    a.r(0,10,0,19,4);a.r(0x23,8,10,8);a.r(0x23,9,10,9);a.sw(9,29,PARAM+28);a.sw(8,29,PARAM+36)
    if mirror_uv:
        a.lw(8,29,PARAM+12);a.lw(9,29,PARAM+20);a.sw(9,29,PARAM+12);a.sw(8,29,PARAM+20)
    a.label(tag)
    # Preserve atlas proportions in anamorphic 16:9. Right-facing panels keep
    # their right anchor; vertical dimensions and viewport scissors never move.
    wide_tag=tag+'_wide_done';a.lw(8,29,0x1D0);a.branch(4,8,0,wide_tag)
    a.r(0,10,0,19,4)
    for off in (28,36):
        a.lw(8,29,PARAM+off);anchor_tag=tag+'_anchor_'+str(off)
        a.branch(4,20,0,anchor_tag);a.r(0x23,8,10,8);a.label(anchor_tag)
        a.r(0,9,0,8,1);a.r(0x21,8,8,9);a.r(2,8,0,8,2)
        a.branch(4,20,0,anchor_tag+'_done');a.r(0x23,8,10,8);a.label(anchor_tag+'_done')
        a.sw(8,29,PARAM+off)
    a.label(wide_tag)
    for off,origin in ((28,17),(36,17),(32,18),(40,18)):
        a.lw(8,29,PARAM+off);a.r(0,9,0,origin,4);a.r(0x21,8,8,9);a.sw(8,29,PARAM+off)
    a.addiu(8,0,int(portrait)|2);a.sw(8,29,PARAM+44);a.li(8,color);a.sw(8,29,PARAM+48)
    a.addiu(4,29,PARAM);a.call(SPRITE)


def clamp(a,out,pointer_reg,offset,maximum,tag):
    a.lw(out,pointer_reg,offset);a.branch(7,out,0,tag+'positive');a.move(out,0)
    a.label(tag+'positive');a.li(8,maximum);a.r(0x2B,9,8,out);a.branch(4,9,0,tag+'ready');a.move(out,8);a.label(tag+'ready')


def hp_palette(a,layer,out,tag,blue=7):
    a.i(11,8,layer,blue);a.branch(4,8,0,tag+'blue');a.i(11,8,layer,2);a.branch(4,8,0,tag+'green')
    a.branch(5,layer,0,tag+'yellow');a.addiu(out,0,3);a.jump(tag+'end')
    for name,p in (('blue',5),('green',1),('yellow',4)):
        a.label(tag+name);a.addiu(out,0,p);a.jump(tag+'end')
    a.label(tag+'end')


def _legacy_hp(a):
    """The previous release's HP section, byte for byte (strict upgrades of prepared captures)."""
    # Native21C5B0 paints the next layer followed by atlas8/palette0's
    # translucent black mask; adjacent green layers remain distinguishable.
    # Keep that underlay behind the per-fighter red damage trail and live HP.
    clamp(a,24,21,0,10000000,'hp_');a.branch(5,24,0,'hp_alive')
    a.r(0,8,0,16,1);a.r(0x21,8,8,16);a.r(0,8,0,8,3);a.li(9,METERS);a.r(0x21,8,8,9);a.sw(0,8)
    a.jump('hp_done');a.label('hp_alive')
    a.sw(24,29,0x190);a.r(0,25,0,16,1);a.r(0x21,25,25,16);a.r(0,25,0,25,3)
    a.li(8,METERS);a.r(0x21,25,25,8);a.li(8,hud.feed.CONTROL);a.lw(27,8,12)
    a.lw(8,25);a.branch(5,8,23,'hp_reset');a.lw(8,25,4);a.branch(5,8,21,'hp_reset')
    a.li(8,SETTINGS);a.lw(10,8,16);a.branch(4,10,0,'hp_reset')
    a.lw(26,25,8);a.r(0x2B,8,24,26);a.branch(4,8,0,'hp_reset')
    a.lw(8,25,20);a.branch(4,8,24,'hp_rate_ready')
    a.r(0x23,8,26,24);a.r(0x21,8,8,10);a.addiu(8,8,-1)
    a.r(27,0,8,10);a.r(18,9,0);a.sw(9,25,16)
    a.label('hp_rate_ready')
    a.lw(8,25,12);a.branch(4,8,27,'hp_trail_ready')
    a.lw(9,25,16);a.r(0x23,26,26,9);a.r(0x2A,8,26,24);a.branch(4,8,0,'hp_store');a.move(26,24)
    a.jump('hp_store')
    a.label('hp_reset');a.sw(23,25);a.sw(21,25,4);a.move(26,24);a.addiu(8,0,1);a.sw(8,25,16)
    a.label('hp_store');a.sw(26,25,8);a.sw(27,25,12)
    a.label('hp_trail_ready');a.sw(24,25,20);a.sw(26,29,0x194)
    a.li(8,10000);a.r(27,0,24,8);a.r(18,25,0);a.r(16,24,0)
    a.branch(5,24,0,'hp_layer');a.addiu(25,25,-1);a.li(24,10000)
    a.label('hp_layer');a.sw(25,29,0x180);a.sw(24,29,0x184)
    a.branch(4,25,0,'hp_under_done');a.addiu(25,25,-1)
    hp_palette(a,25,26,'hp_under_')
    emit_sprite(a,8,(26,),(0,0,160,16),(69,9,229,25))
    emit_sprite(a,8,0,(0,0,160,16),(69,9,229,25))
    a.label('hp_under_done');a.lw(25,29,0x180)
    a.lw(26,29,0x194);a.lw(8,29,0x190);a.branch(4,26,8,'hp_front')
    a.addiu(26,26,-1);a.li(8,10000);a.r(27,0,26,8);a.r(18,27,0);a.r(16,26,0);a.addiu(26,26,1)
    a.branch(4,27,25,'hp_trail_same');a.li(26,10000);a.label('hp_trail_same')
    a.addiu(8,0,160);a.r(25,0,26,8);a.r(18,26,0);a.li(8,10000);a.r(27,0,26,8);a.r(18,26,0)
    a.addiu(27,26,69)
    # Exact native red trail palette and stepped alpha mask. The upper part
    # begins at UVx64: a hit crossing that step legitimately looks taller than
    # the remaining lower-left green fill; it is not an opaque rectangle.
    emit_sprite(a,8,2,(0,0,26,16),(69,9,27,25),uv_registers=(2,),box_registers=(2,))
    a.label('hp_front');a.lw(25,29,0x180);hp_palette(a,25,26,'hp_front_')
    a.lw(24,29,0x184);a.addiu(8,0,160);a.r(25,0,24,8);a.r(18,24,0);a.li(8,10000);a.r(27,0,24,8);a.r(18,24,0)
    a.i(11,8,24,3);a.branch(4,8,0,'hp_sliver');a.addiu(24,0,3);a.label('hp_sliver')
    a.addiu(27,24,69)
    emit_sprite(a,8,(26,),(0,0,24,16),(69,9,27,25),uv_registers=(2,),box_registers=(2,))
    for pip in range(6):
        a.lw(25,29,0x180);a.i(11,8,25,pip+1);a.branch(5,8,0,f'pip{pip}')
        emit_sprite(a,8,1,(0,16,16,32),(73+9*pip,2,89+9*pip,18))
        a.label(f'pip{pip}')
    a.label('hp_done')


def _width(a,reg,tag,sliver):
    """reg = native 160-unit width of a 1..10000 layer remainder; sliver: 21C5B0 keeps 3 units on the last layer."""
    a.addiu(8,0,160);a.r(25,0,reg,8);a.r(18,reg,0);a.li(8,10000);a.r(27,0,reg,8);a.r(18,reg,0)
    if sliver:
        a.lw(8,29,0x180);a.branch(5,8,0,tag);a.i(11,8,reg,3);a.branch(4,8,0,tag);a.addiu(reg,0,3)
        a.label(tag)


def _native_hp(a):
    """HP exactly as native 21C5B0/21CA60 draw it, from this fighter's own trail record.

    The trail layer (not the HP layer) chooses the fill and next-layer palettes and the pip count. While the trail is
    still in a higher layer the fill is hidden, the trail shows red, and the next layer shows its remaining HP over
    the dark mask with the part already lost in dark red (native records 0x1C/0x38). The trail resets instead of
    animating on a new fighter, form, fusion, defusion, body change or revival (identity), on any HP rise, when the
    fighter was not drawn by the previous HUD pass (target switch, swap) and after a HUD absence longer than the
    trail itself (co-op fusion, cinematics). Draw-only: only HUD records change.
    """
    # Values live in t4..t7 (r12..r15), s-registers and the stack, never k0/k1 (r26/r27): a kernel interrupt
    # handler may overwrite those between two instructions (a one-frame wrong palette, width or pip count).
    clamp(a,24,21,0,10000000,'hp_');a.branch(5,24,0,'hp_alive')
    a.r(0,8,0,16,1);a.r(0x21,8,8,16);a.r(0,8,0,8,3);a.li(9,METERS);a.r(0x21,8,8,9);a.sw(0,8)
    a.jump('hp_done');a.label('hp_alive')
    a.sw(24,29,0x190);a.r(0,25,0,16,1);a.r(0x21,25,25,16);a.r(0,25,0,25,3)
    a.li(8,METERS);a.r(0x21,25,25,8);a.li(8,hud.feed.CONTROL);a.lw(15,8,12)
    # Pass clocks: the first panel of a new battle tick moves current -> previous (a clock that went back starts over).
    a.li(8,PASSES);a.lw(9,8);a.branch(4,9,15,'hp_pass_ready')
    a.r(0x2B,10,15,9);a.branch(4,10,0,'hp_pass_forward');a.move(9,15)
    a.label('hp_pass_forward');a.sw(9,8,4);a.sw(15,8)
    a.label('hp_pass_ready')
    # Identity: the selected row's character (row-0x40) and the bounded model's character.
    a.lw(12,21,-64);a.i(12,12,12,0xFFFF)
    a.lw(8,23,12);a.i(11,9,8,12);a.branch(4,9,0,'hp_id_ready')
    a.r(0,8,0,8,2);a.li(9,hud.core.MODELS);a.r(0x21,8,8,9);a.lw(8,8)
    pointer(a,8,0x10,'hp_id_ready');a.lw(8,8,12);a.i(12,8,8,0xFFFF);a.r(0,8,0,8,16);a.r(0x25,12,12,8)
    a.label('hp_id_ready');a.r(0,13,0,16,3);a.li(8,IDENTITY);a.r(0x21,13,13,8)
    a.lw(8,25);a.branch(5,8,23,'hp_identity');a.lw(8,25,4);a.branch(5,8,21,'hp_identity')
    a.lw(8,13);a.branch(5,8,12,'hp_identity')
    # A record the previous HUD pass did not draw, one from a later clock, or one older than the trail's own
    # duration (a long single-view stretch: co-op fusion, an ultimate) is stale: start from the current HP.
    a.lw(8,25,12);a.branch(4,8,15,'hp_fresh')
    a.r(0x2B,9,15,8);a.branch(5,9,0,'hp_reset')
    a.li(9,PASSES);a.lw(9,9,4);a.r(0x2B,9,8,9);a.branch(5,9,0,'hp_reset')
    a.li(9,SETTINGS);a.lw(9,9,16);a.r(0x23,11,15,8);a.r(0x2B,9,9,11);a.branch(5,9,0,'hp_reset')
    a.label('hp_fresh')
    a.li(8,SETTINGS);a.lw(10,8,16);a.branch(4,10,0,'hp_reset')
    a.lw(14,25,8);a.r(0x2B,8,24,14);a.branch(4,8,0,'hp_reset')
    # Within SETTLE ticks of an identity change a lower HP is the new form's value, not damage.
    a.lw(8,13,4);a.r(0x23,8,8,15);a.addiu(8,8,-1);a.i(11,8,8,SETTLE);a.branch(5,8,0,'hp_reset')
    a.lw(8,25,20);a.branch(4,8,24,'hp_rate_ready')
    a.r(0x23,8,14,24);a.r(0x21,8,8,10);a.addiu(8,8,-1)
    a.r(27,0,8,10);a.r(18,9,0);a.sw(9,25,16)
    a.label('hp_rate_ready')
    a.lw(8,25,12);a.branch(4,8,15,'hp_trail_ready')
    a.lw(9,25,16);a.r(0x23,14,14,9);a.r(0x2A,8,14,24);a.branch(4,8,0,'hp_store');a.move(14,24)
    a.jump('hp_store')
    a.label('hp_identity');a.sw(12,13);a.addiu(8,15,SETTLE);a.sw(8,13,4)
    a.label('hp_reset');a.sw(23,25);a.sw(21,25,4);a.move(14,24);a.addiu(8,0,1);a.sw(8,25,16)
    a.label('hp_store');a.sw(14,25,8);a.sw(15,25,12)
    a.label('hp_trail_ready');a.sw(24,25,20);a.sw(14,29,0x194)
    # Layers (exact multiples keep a full bar): HP -> 0x1B0/0x1B4, trail -> 0x180/0x184.
    for value,layer_at,tag in ((24,0x1B0,'hp_layer_hp'),(14,0x180,'hp_layer_trail')):
        a.li(8,10000);a.r(27,0,value,8);a.r(18,25,0);a.r(16,9,0)
        a.branch(5,9,0,tag);a.addiu(25,25,-1);a.li(9,10000)
        a.label(tag);a.sw(25,29,layer_at);a.sw(9,29,layer_at+4)
    a.lw(25,29,0x180);a.branch(4,25,0,'hp_under_done');a.addiu(25,25,-1)
    hp_palette(a,25,14,'hp_under_',BLUE_LAYER)
    emit_sprite(a,8,(14,),(0,0,160,16),(69,9,229,25))
    # Trail above the HP layer: the HP layer's lost part is red under the mask (one layer apart: past its
    # remaining HP; further apart: all of it).
    a.lw(25,29,0x180);a.lw(8,29,0x1B0);a.branch(4,25,8,'hp_lost_done')
    a.addiu(8,8,1);a.move(15,0);a.branch(5,25,8,'hp_lost_x')
    a.lw(15,29,0x1B4);_width(a,15,'hp_lost_w',False)
    a.label('hp_lost_x');a.addiu(8,0,160);a.branch(4,15,8,'hp_lost_done');a.addiu(14,15,69)
    emit_sprite(a,8,2,(15,0,160,16),(14,9,229,25),uv_registers=(0,),box_registers=(0,))
    a.label('hp_lost_done')
    emit_sprite(a,8,0,(0,0,160,16),(69,9,229,25))
    a.label('hp_under_done')
    # Exact native red trail palette and stepped alpha mask. The upper part
    # begins at UVx64: a hit crossing that step legitimately looks taller than
    # the remaining lower-left green fill; it is not an opaque rectangle.
    a.lw(14,29,0x194);a.lw(8,29,0x190);a.branch(4,14,8,'hp_front')
    a.lw(14,29,0x184);_width(a,14,'hp_trail_w',True)
    a.branch(4,14,0,'hp_front');a.addiu(15,14,69)
    emit_sprite(a,8,2,(0,0,14,16),(69,9,15,25),uv_registers=(2,),box_registers=(2,))
    # The fill shows only once the trail is back in the HP layer, in the trail layer's palette.
    a.label('hp_front');a.lw(25,29,0x180);a.lw(8,29,0x1B0);a.branch(5,25,8,'hp_front_done')
    hp_palette(a,25,14,'hp_front_',BLUE_LAYER)
    a.lw(24,29,0x1B4);_width(a,24,'hp_front_w',True)
    a.branch(4,24,0,'hp_front_done');a.addiu(15,24,69)
    emit_sprite(a,8,(14,),(0,0,24,16),(69,9,15,25),uv_registers=(2,),box_registers=(2,))
    a.label('hp_front_done')
    # 21CA60: one pip per full layer below the trail's layer (max six), each in its native record's palette.
    for pip in range(6):
        a.lw(25,29,0x180);a.i(11,8,25,pip+1);a.branch(5,8,0,f'pip{pip}')
        emit_sprite(a,8,PIP_PALETTES[pip],(0,16,16,32),(73+9*pip,2,89+9*pip,18))
        a.label(f'pip{pip}')
    a.label('hp_done')


def _own_record(a):
    """Record this panel when it shows its view's own fighter: the enabled view whose rectangle holds the panel's
    top-left (s1, s2) and whose subject is this fighter (s0). A target panel never matches its own view."""
    a.li(8,hud.CONTROL);a.lw(9,8,12);a.i(11,10,9,hud.MAX_VIEWS+1);a.branch(4,10,0,'own_done')
    a.li(14,hud.VIEWS);a.move(15,0)
    a.label('own_view');a.branch(4,15,9,'own_done')
    a.lw(12,14);a.branch(4,12,0,'own_next')
    a.lw(12,14,4);a.r(0x2A,13,17,12);a.branch(5,13,0,'own_next')
    a.lw(12,14,8);a.r(0x2A,13,12,17);a.branch(5,13,0,'own_next')
    a.lw(12,14,12);a.r(0x2A,13,18,12);a.branch(5,13,0,'own_next')
    a.lw(12,14,16);a.r(0x2A,13,12,18);a.branch(5,13,0,'own_next')
    a.lw(12,14,20);pointer(a,12,4,'own_next');a.lw(12,12);a.branch(5,12,16,'own_next')
    a.li(12,OWN);a.r(0,13,0,15,4);a.r(0x21,12,12,13)
    a.sw(17,12);a.sw(18,12,4)
    a.i(12,13,20,1);a.r(0,13,0,13,16);a.r(0x25,13,13,19)
    a.lw(24,29,0x1D0);a.branch(4,24,0,'own_word');a.i(15,24,0,2);a.r(0x25,13,13,24)
    a.label('own_word');a.sw(13,12,8);a.li(24,hud.CONTROL);a.lw(24,24,20);a.sw(24,12,12);a.jump('own_done')
    a.label('own_next');a.addiu(14,14,hud.VIEW_STRIDE);a.addiu(15,15,1);a.jump('own_view')
    a.label('own_done')


def panel_code(native_hp=True,layout=None,own_record=True):
    (portrait_x,portrait_y),(digit_x,digit_y),(stock_x,stock_y),(fill_x,fill_y)=LAYOUTS[layout or LAYOUT]
    a=Assembler(NATIVE_PANEL);hud.save(a)
    for dest,source in ((16,4),(17,5),(18,6),(19,7)):a.move(dest,source)
    a.i(55,20,29,hud.SAVED.index(8)*8)
    import widescreen_support as wide
    a.sw(0,29,0x1D0);wide.emit_detection(a,10,'aspect_ready');a.sw(10,29,0x1D0);a.label('aspect_ready')
    if own_record:_own_record(a)
    a.call(hud.spectator.LOOKUP);a.branch(4,3,0,'done')
    a.li(8,hud.core.POINTERS);a.r(0,9,0,16,2);a.r(0x21,8,8,9);a.lw(23,8);a.move(4,23)
    a.call(hud.feed.ROW);a.branch(4,2,0,'done');a.move(21,2)
    a.lw(22,28,-0x5728);pointer(a,22,0x200,'compact');a.lw(22,22);pointer(a,22,32,'compact')
    a.lw(8,22);a.i(11,9,8,16);a.branch(5,9,0,'compact')
    # Normal native background and real active model portrait.
    emit_sprite(a,6,0,(0,0,256,64),(0,0,256,64))
    a.li(8,SETTINGS);a.lw(8,8,4);a.branch(4,8,0,'portrait_done')
    a.lw(8,23,12);a.i(11,9,8,12);a.branch(4,9,0,'portrait_done')
    a.r(0,8,0,8,2);a.li(9,hud.core.MODELS);a.r(0x21,8,8,9);a.lw(24,8)
    pointer(a,24,84,'portrait_done');a.lw(24,24,80)
    # Native status-node translations relative to the atlas6 frame (LAYOUTS):
    # portrait, health (69,9), pips (73,2), ki (64,27).
    # These are authored node offsets, not the visible texture bounds. A node above the frame's top (BT4) drops the
    # cell's transparent top rows instead: sprite boxes scale unsigned.
    top=max(0,-portrait_y)
    emit_sprite(a,0,0,(0,top,64,64),(portrait_x,portrait_y+top,portrait_x+64,portrait_y+64),bundle=24,portrait=True)
    a.label('portrait_done')
    (_native_hp if native_hp else _legacy_hp)(a)
    # Native20B4E0 reads ordinary ki at row+0x0C, but charging to Sparking
    # uses20B588 -> row+0x1C and21DB78 -> 6000 per blue band (30000 total).
    # Ordinary ki can exceed100k in Sparking; it is not the blue accumulator.
    for blue,palette in ((False,1),(True,5)):
        units=6000 if blue else 20000
        clamp(a,24,21,28 if blue else 12,5*units,'blue_' if blue else 'ki_');a.sw(24,29,0x188)
        for band in range(5):
            tag=f'ki_{int(blue)}_{band}'
            a.lw(24,29,0x188);a.li(8,units*band);a.r(0x2A,9,8,24);a.branch(4,9,0,tag)
            a.r(0x23,24,24,8);a.li(8,units);a.r(0x2B,9,8,24);a.branch(4,9,0,tag+'fraction');a.move(24,8)
            a.label(tag+'fraction');a.addiu(8,0,17);a.r(25,0,24,8);a.r(18,24,0);a.li(8,units);a.r(27,0,24,8);a.r(18,24,0)
            a.addiu(8,0,33);a.r(0x23,25,8,24);a.addiu(8,0,44);a.r(0x23,27,8,24)
            emit_sprite(a,8,palette,(16,25,30,33),(64+8*band,27,78+8*band,44),uv_registers=(1,),box_registers=(1,))
            a.label(tag)
    # Lower native stock frame, cyan fractional progress and actual digit art.
    emit_sprite(a,15,0,(0,0,48,12),(stock_x,stock_y,stock_x+48,stock_y+12))
    clamp(a,24,21,20,10000000,'stocks_');clamp(a,25,21,24,10000000,'stockmax_')
    a.r(0x2B,8,25,24);a.branch(4,8,0,'stock_clamped');a.move(24,25);a.label('stock_clamped')
    a.li(8,100000);a.r(27,0,24,8);a.r(18,26,0);a.r(16,27,0)
    a.branch(5,24,25,'stock_fraction');a.branch(4,25,0,'stock_fraction');a.move(27,8);a.label('stock_fraction')
    a.sw(26,29,0x18C);a.addiu(8,0,26);a.r(25,0,27,8);a.r(18,27,0);a.li(8,100000);a.r(27,0,27,8);a.r(18,27,0)
    a.addiu(25,27,161);a.addiu(26,27,fill_x)
    emit_sprite(a,8,1,(161,0,25,6),(fill_x,fill_y,26,fill_y+6),uv_registers=(2,),box_registers=(2,))
    a.lw(24,29,0x18C);a.i(11,8,24,8);a.branch(4,8,0,'stock_text')
    a.i(12,25,24,3);a.r(0,25,0,25,5);a.r(2,26,0,24,2);a.r(0,26,0,26,5)
    a.addiu(27,25,32);a.addiu(24,26,32)
    emit_sprite(a,14,0,(25,26,27,24),(digit_x,digit_y,digit_x+32,digit_y+32),uv_registers=(0,1,2,3),mirror_uv=False)
    a.jump('sparking')
    a.label('stock_text');a.move(4,24);a.addiu(5,29,0x1A0);a.call(hud.NUMBER)
    if (digit_x,digit_y)==LAYOUTS['bt3'][1]:
        a.addiu(25,29,0x1A0);a.move(24,18);a.addiu(24,24,22);a.move(26,17);a.addiu(26,26,4)
    else:
        # The digit's own housing, scaled with the panel (and mirrored with it): 8+ stocks as text.
        a.addiu(25,29,0x1A0)
        a.addiu(8,0,digit_y+6);a.r(25,0,8,19);a.r(18,24,0);a.r(2,24,0,24,8);a.r(0x21,24,24,18)
        a.addiu(8,0,digit_x+16);a.r(25,0,8,19);a.r(18,26,0);a.r(2,26,0,26,8)
        a.branch(4,20,0,'stock_text_left');a.r(0x23,26,19,26)
        a.label('stock_text_left');a.r(0x21,26,26,17);a.addiu(26,26,-6)
    hud.text(a,25,26,24,0x8050DFFF)
    a.label('sparking');a.li(8,SETTINGS);a.lw(8,8,8);a.branch(4,8,0,'done')
    a.i(36,8,23,0x1085);a.i(36,9,23,0x10AD);a.r(0x25,8,8,9);a.i(12,8,8,64);a.branch(4,8,0,'done')
    # Native white frame-mask becomes an electric-blue translucent glow; the
    # flicker is driven by the existing battle clock, not host wall time.
    a.li(8,hud.feed.CONTROL);a.lw(8,8,12);a.i(12,8,8,4);a.branch(4,8,0,'dim_glow')
    emit_sprite(a,7,0,(0,0,256,64),(0,0,256,64),color=0x18806420)
    a.jump('lightning');a.label('dim_glow')
    emit_sprite(a,7,0,(0,0,256,64),(0,0,256,64),color=0x0C806420)
    a.label('lightning');a.li(8,hud.feed.CONTROL);a.lw(8,8,12)
    a.r(2,24,0,8,2);a.i(12,24,24,3);a.r(0,24,0,24,6)
    a.r(2,25,0,8,4);a.i(12,25,25,1);a.r(0,25,0,25,6)
    a.addiu(26,24,64);a.addiu(27,25,64)
    for box in ((52,0,92,32),(169,3,209,35)):
        emit_sprite(a,16,0,(24,25,26,27),box,uv_registers=(0,1,2,3),color=0x70808080)
    a.jump('done')
    a.label('compact');hud.restore(a);a.jump(COMPACT)
    a.label('done');hud.restore(a);a.jr();data=a.finish();assert len(data)<COMPACT-NATIVE_PANEL;return data


def pieces(safe_edges=True,isolated=True,native_hp=True,layout=None,own_record=True):
    return [(SPRITE,sprite_code(safe_edges,isolated)),(TEMPLATE,template()),(NATIVE_PANEL,panel_code(native_hp,layout,own_record)),
            (COMPACT,hud.panel(styled=True,base=COMPACT,repaired=True))]


def settings_data(settings=None):
    import mod_settings
    s=mod_settings.validate_settings(settings or dict(mod_settings.DEFAULTS))
    return struct.pack('<8I',int(s['split_hud_style']=='native'),int(s['show_hud_portraits']),
                       int(s['show_hud_sparking_effects']),int(s.get('coop_hud_layout','players')=='targets'),
                       round(s.get('hud_damage_trail_seconds',.5)*ACTOR_HZ),
                       s.get('split_hud_scale_percent',100),int(s.get('split_hud_filter','linear')=='linear'),
                       int(s.get('split_hud_layout','top')=='top_bottom'))


def native_guards(ram):
    native=elf_reader(elf_path(ROOT))[2]
    for p,n in NATIVE_RANGES:
        if ram[p:p+n]!=native(p,n):raise ValueError(f'Native HUD texture service changed at{p:08X}')
