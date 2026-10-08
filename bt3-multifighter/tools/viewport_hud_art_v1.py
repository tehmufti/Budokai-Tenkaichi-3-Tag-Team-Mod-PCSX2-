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

SPRITE,TEMPLATE,NATIVE_PANEL,COMPACT = 0x072D4000,0x072D5800,0x072D6000,0x072DC000
SETTINGS = 0x072DE000
UPLOAD, INVALIDATE = A(0x224F00),A(0x21F438)
PARAM=0x120
NATIVE_RANGES=((UPLOAD,0x1C8),(INVALIDATE,0x48),(A(0x1006E8),8),(A(0x100738),8))
# Parameter words: bundle,index,palette_delta,u0,v0,u1,v1,x0,y0,x1,y1,
# portrait_bank,color. All coordinates are logical512x448 screen pixels.


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


def sprite_code():
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
    a.lw(21,16,44);a.addiu(22,0,tbp(0x2A00));a.addiu(23,0,tbp(0x2C80))
    a.branch(4,21,0,'upload')
    a.call(INVALIDATE);a.sw(0,19,40);a.sw(0,20,40)
    a.addiu(22,0,tbp(0x2C00));a.addiu(23,0,tbp(0x2CD0))
    a.label('upload');a.move(4,17);a.lw(5,16,4);a.lw(6,16,8);a.move(7,22);a.move(8,23);a.call(UPLOAD)
    a.call(A(0x100878));a.move(24,2);a.li(8,TEMPLATE)
    for off in range(0,192,4):a.lw(9,8,off);a.sw(9,24,off)
    a.lw(8,16,48);a.sw(8,24,112)
    a.lw(8,19,48);a.lw(9,19,32);a.r(0x21,9,9,22);a.r(0x25,8,8,9);a.sw(8,24,128)
    a.lw(8,19,52);a.lw(9,20,36);a.r(0x21,9,9,23);a.r(0,9,0,9,5);a.i(13,8,8,4);a.r(0x25,8,8,9);a.sw(8,24,132)
    for first,uv,xy in ((160,12,28),(176,20,36)):
        for off,dest,xbias,ybias in ((uv,first,0,0),(xy,first+8,1792,Y_ORIGIN)):
            a.lw(8,16,off);a.lw(9,16,off+4)
            if xbias:a.addiu(8,8,xbias);a.addiu(9,9,ybias)
            a.r(0,8,0,8,4);a.r(0,9,0,9,4)
            if not xbias:a.addiu(8,8,8);a.addiu(9,9,8)
            a.r(0,9,0,9,16);a.r(0x25,8,8,9);a.sw(8,24,dest)
    a.addiu(4,24,192);a.call(A(0x100890))
    a.branch(4,21,0,'done')
    # A different panel may have replaced either stock portrait VRAM slot.
    # Leave the native two-side cache invalid, as21F438 does before each draw.
    a.call(INVALIDATE);a.sw(0,19,40);a.sw(0,20,40)
    a.label('done');hud.restore(a);a.jr();data=a.finish();assert len(data)<TEMPLATE-SPRITE;return data


def scale(a,dst,source):
    a.r(25,0,source,19);a.r(18,dst,0);a.r(2,dst,0,dst,8)


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
    a.r(0x23,8,19,8);a.r(0x23,9,19,9);a.sw(9,29,PARAM+28);a.sw(8,29,PARAM+36)
    if mirror_uv:
        a.lw(8,29,PARAM+12);a.lw(9,29,PARAM+20);a.sw(9,29,PARAM+12);a.sw(8,29,PARAM+20)
    a.label(tag)
    for off,origin in ((28,17),(36,17),(32,18),(40,18)):
        a.lw(8,29,PARAM+off);a.r(0x21,8,8,origin);a.sw(8,29,PARAM+off)
    a.addiu(8,0,int(portrait));a.sw(8,29,PARAM+44);a.li(8,color);a.sw(8,29,PARAM+48)
    a.addiu(4,29,PARAM);a.call(SPRITE)


def clamp(a,out,pointer_reg,offset,maximum,tag):
    a.lw(out,pointer_reg,offset);a.branch(7,out,0,tag+'positive');a.move(out,0)
    a.label(tag+'positive');a.li(8,maximum);a.r(0x2B,9,8,out);a.branch(4,9,0,tag+'ready');a.move(out,8);a.label(tag+'ready')


def hp_palette(a,layer,out,tag):
    a.i(11,8,layer,7);a.branch(4,8,0,tag+'blue');a.i(11,8,layer,2);a.branch(4,8,0,tag+'green')
    a.branch(5,layer,0,tag+'yellow');a.addiu(out,0,3);a.jump(tag+'end')
    for name,p in (('blue',5),('green',1),('yellow',4)):
        a.label(tag+name);a.addiu(out,0,p);a.jump(tag+'end')
    a.label(tag+'end')


def panel_code():
    a=Assembler(NATIVE_PANEL);hud.save(a)
    for dest,source in ((16,4),(17,5),(18,6),(19,7)):a.move(dest,source)
    a.i(55,20,29,hud.SAVED.index(8)*8)
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
    emit_sprite(a,0,0,(0,0,64,64),(12,0,76,64),bundle=24,portrait=True)
    a.label('portrait_done')
    # HP uses exact native10k layers, partial current bar over previous layer.
    clamp(a,24,21,0,10000000,'hp_');a.branch(4,24,0,'hp_done')
    a.li(8,10000);a.r(27,0,24,8);a.r(18,25,0);a.r(16,24,0)
    a.branch(5,24,0,'hp_layer');a.addiu(25,25,-1);a.li(24,10000)
    a.label('hp_layer');a.sw(25,29,0x180);a.sw(24,29,0x184)
    a.branch(4,25,0,'hp_front');a.addiu(25,25,-1);hp_palette(a,25,26,'hp_under_')
    emit_sprite(a,8,(26,),(0,0,160,16),(64,8,224,24))
    a.label('hp_front');a.lw(25,29,0x180);hp_palette(a,25,26,'hp_front_')
    a.lw(24,29,0x184);a.addiu(8,0,160);a.r(25,0,24,8);a.r(18,24,0);a.li(8,10000);a.r(27,0,24,8);a.r(18,24,0)
    a.i(11,8,24,3);a.branch(4,8,0,'hp_sliver');a.addiu(24,0,3);a.label('hp_sliver')
    a.addiu(27,24,64)
    emit_sprite(a,8,(26,),(0,0,24,16),(64,8,27,24),uv_registers=(2,),box_registers=(2,))
    for pip in range(6):
        a.lw(25,29,0x180);a.i(11,8,25,pip+1);a.branch(5,8,0,f'pip{pip}')
        emit_sprite(a,8,1,(0,16,16,32),(70+9*pip,0,86+9*pip,16))
        a.label(f'pip{pip}')
    a.label('hp_done')
    # Both layers retain native20k-per-band semantics:100k normal yellow,
    # the next100k blue. The stock resources provide the authored angled bands.
    clamp(a,24,21,12,200000,'ki_');a.sw(24,29,0x188)
    for blue,palette in ((False,1),(True,5)):
        for band in range(5):
            tag=f'ki_{int(blue)}_{band}'
            a.lw(24,29,0x188);a.li(8,(100000 if blue else 0)+20000*band);a.r(0x2A,9,8,24);a.branch(4,9,0,tag)
            a.r(0x23,24,24,8);a.li(8,20000);a.r(0x2B,9,8,24);a.branch(4,9,0,tag+'fraction');a.move(24,8)
            a.label(tag+'fraction');a.addiu(8,0,17);a.r(25,0,24,8);a.r(18,24,0);a.li(8,20000);a.r(27,0,24,8);a.r(18,24,0)
            a.addiu(8,0,33);a.r(0x23,25,8,24);a.addiu(8,0,43);a.r(0x23,27,8,24)
            emit_sprite(a,8,palette,(16,25,30,33),(64+8*band,27,78+8*band,43),uv_registers=(1,),box_registers=(1,))
            a.label(tag)
    # Lower native stock frame, cyan fractional progress and actual digit art.
    emit_sprite(a,15,0,(0,0,48,12),(28,44,76,56))
    clamp(a,24,21,20,10000000,'stocks_');clamp(a,25,21,24,10000000,'stockmax_')
    a.r(0x2B,8,25,24);a.branch(4,8,0,'stock_clamped');a.move(24,25);a.label('stock_clamped')
    a.li(8,100000);a.r(27,0,24,8);a.r(18,26,0);a.r(16,27,0)
    a.branch(5,24,25,'stock_fraction');a.branch(4,25,0,'stock_fraction');a.move(27,8);a.label('stock_fraction')
    a.sw(26,29,0x18C);a.addiu(8,0,26);a.r(25,0,27,8);a.r(18,27,0);a.li(8,100000);a.r(27,0,27,8);a.r(18,27,0)
    a.addiu(25,27,161);a.addiu(26,27,35)
    emit_sprite(a,8,1,(161,0,25,6),(35,47,26,53),uv_registers=(2,),box_registers=(2,))
    a.lw(24,29,0x18C);a.i(11,8,24,8);a.branch(4,8,0,'stock_text')
    a.i(12,25,24,3);a.r(0,25,0,25,5);a.r(2,26,0,24,2);a.r(0,26,0,26,5)
    a.addiu(27,25,32);a.addiu(24,26,32)
    emit_sprite(a,14,0,(25,26,27,24),(6,28,38,60),uv_registers=(0,1,2,3),mirror_uv=False)
    a.jump('sparking')
    a.label('stock_text');a.move(4,24);a.addiu(5,29,0x1A0);a.call(hud.NUMBER)
    a.addiu(25,29,0x1A0);a.move(24,18);a.addiu(24,24,22);a.move(26,17);a.addiu(26,26,4);hud.text(a,25,26,24,0x8050DFFF)
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


def pieces():
    return [(SPRITE,sprite_code()),(TEMPLATE,template()),(NATIVE_PANEL,panel_code()),
            (COMPACT,hud.panel(styled=True,base=COMPACT))]


def settings_data(settings=None):
    import mod_settings
    s=mod_settings.validate_settings(settings or dict(mod_settings.DEFAULTS))
    return struct.pack('<3I',int(s['split_hud_style']=='native'),int(s['show_hud_portraits']),
                       int(s['show_hud_sparking_effects']))


def native_guards(ram):
    native=elf_reader(elf_path(ROOT))[2]
    for p,n in NATIVE_RANGES:
        if ram[p:p+n]!=native(p,n):raise ValueError(f'Native HUD texture service changed at{p:08X}')
