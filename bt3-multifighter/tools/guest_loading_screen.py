"""Loading presentation in the game's GS output, including exclusive fullscreen.

The isolated launcher installs a small dormant PNACH hook late in the native
frame, before the battle loop submits its GIF packet arena. The watcher supplies bounded, double-buffered
packets through PINE. Only data changes during a match.

Version 4 (Ki Storm, analysis/loading-redesign-v4/PORT-SPEC.md, protocol in
loading_protocol): packet A carries the GS setup, the PSMT8 background,
foreground and atlas IMAGE uploads with their CLUTs and the background sprite;
packet B the foreground register state; the 4 KiB descriptor after them the
animation plan. The guest copies both packets verbatim and jumps into two
fixed-size emitter pieces (KS_A between the packets, KS_B after them:
loading_lights_a/_b, stubs until Phase 2b) so the arena reserve is constant.
A legacy rectangle-only packet A without a descriptor (the fallback menu, the
_draw_picture fallback) is still accepted: the guest copies it and draws no
lights. SUBS stays byte-identical to v3 (its emitters serve the KS pieces).
"""
from native_map import A, SERIAL, elf_path
import argparse
import game_profile
import contextvars
import copy
import hashlib
import os
import struct
import localization
import threading
import time
import secrets
from contextlib import nullcontext
from functools import lru_cache
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
import loading_protocol as protocol
from loading_protocol import BUFFERS, CAPACITY, DESCRIPTOR, LIGHT_A, FGB, RESERVE, KS_RETURN, packed_color, noise_table
from regional import PAL, SCISSOR_Y1, Y_ORIGIN, xyz2_y, emit_window_y
from native_map import GPO

HOOK, CODE, CONTROL = A(0x102098), 0x07470000, 0x07471000
MAGIC, LEASE = 0x4254334C, 900
CHEAT = ROOT/'runtime128/cheats'/game_profile.cheat_name(SERIAL)
SCENE_LOOP = A(0x3337C0)
# Control words: magic+0, buffer+4, size+8, drawn+12, age+16, generation+20,
# consumed+24, no_space+28, surface+32, menu_frames+36, drawn_latch+40 (set by
# every drawn frame, cleared when the cover drops), cycle+44 (clash cycle, wraps
# at CYCLE), cursor_max+48 (largest native arena cursor offset seen at the hook),
# last_count+52 (CP0 Count at the previous drawn frame, 0 when a cover starts),
# tick_acc+56 (cycles carried toward the next animation step), tick+60 (cycles
# per step from the speed preference; anything outside MIN_TICK..MAX_TICK uses TICK).
MENU_FRAMES, DRAWN_LATCH, CYCLE_WORD, CURSOR_MAX, CYCLE = 36, 40, 44, 48, 150
LAST_COUNT, TICK_ACC, TICK_WORD = 52, 56, 60
# The design and every frame constant in KS_A/KS_B were authored at 60 steps a
# second. CP0 Count advances with the 294.912 MHz EE clock, so one step is one
# NTSC field of cycles (on the European disc one 50 Hz field, so every step is one
# displayed field there too). A stalled frame resumes after at most four steps rather
# than leaping ahead; speeds from 25% to 400% are accepted.
TICK = 294_912_000//50 if PAL else 294_912_000*1001//60_000
MIN_TICK, MAX_TICK, MAX_ELAPSED = TICK//4, TICK*4, TICK*4
LIGHTS = protocol.MAGIC                                   # descriptor magic 'L4KS'
LIGHT_B = FGB
SPRITE_2D, HUD_INVALIDATE = A(0x2FE9C8), A(0x21F438)            # *(*(SPRITE_2D)+0x230): the change-cached 2D texture handle (sub_13DB90)
# PRE/PRIM in a GIFtag only apply to PACKED data, so every primitive block is
# preceded by an A+D PRIM write (which also resets the vertex queue).
PRIM_BYTES = 32
OFFSCREEN = -64                                          # hidden geometry is clipped by the scissor
FRAME = 0x100                                            # 0xA0..0xF7 KS scratch, 0xF8 the KS return address
SAVED = ((16,0),(17,8),(18,16),(19,24),(4,32),(5,40),(31,48),(20,64),(21,72),(22,80),(23,88),(6,96),(7,104))
PARAMS, STRIP_RA = 0x70, 0x9C   # eleven strip parameters, then the strip's saved return address
PRIM_TAG = (0x8001, 0x10000000, 0xE)         # one A+D register, EOP, PACKED
STRIP_PRIM, SPRITE_PRIM, BOLT_PRIM = 0x0C, 0x06, 0x0A   # gouraud strip, flat sprite, gouraud line strip
STRIP_TAG = (0x8006, 0x24000000, 0x51)       # 6 vertices, EOP, REGLIST RGBAQ/XYZ2
MAX_PARTICLES, BOLT_POINTS = 12, 9
SPRITE_TAG = (0x8000|MAX_PARTICLES, 0x34000000, 0x551)
BOLT_TAG = (0x8000|BOLT_POINTS, 0x24000000, 0x51)
Q_ONE = 0x3F800000
# Bolt parameters on the stack: x, y, dx8, dy8, colour, end colour, noise index, x offset, visible, y step scratch.
BOLT_PARAMS = 0x70


def gif_packet(rectangles):
    # Full-frame scissor and XY offset, depth ALWAYS, untextured opaque sprites.
    # REGLIST: RGBAQ, XYZ2, XYZ2. One GIF packet, bounded below65535 DMA QWC.
    rectangles = list(rectangles)
    if not 1 <= len(rectangles) < 10240: raise ValueError('Too many loading rectangles')
    setup = [(0x1FF0000 | (SCISSOR_Y1 << 48), 0x40),
             ((1792*16) | ((Y_ORIGIN*16) << 32), 0x18),
             (0x30000, 0x47), (0, 0x4A), (6, 0)]
    out = bytearray(struct.pack('<2Q', len(setup)|(1<<60), 14))
    for value, register in setup: out.extend(struct.pack('<2Q', value, register))
    out.extend(struct.pack('<2Q', len(rectangles)|0x8000|(1<<58)|(3<<60), 0x551))
    for x0,y0,x1,y1,rgb in rectangles:
        if not 0 <= x0 < x1 <= 512 or not 0 <= y0 < y1 <= 448:
            raise ValueError('Loading rectangle outside native frame')
        color = rgb[0] | (rgb[1]<<8) | (rgb[2]<<16) | (0x80<<24) | (0x3F800000<<32)
        xy0 = ((x0+1792)*16) | (xyz2_y(y0)<<16)
        xy1 = ((x1+1792)*16) | (xyz2_y(y1)<<16)
        out.extend(struct.pack('<3Q', color, xy0, xy1))
    out.extend(bytes((-len(out))%16))
    if len(out) > CAPACITY-16: raise ValueError('Loading packet exceeds reserved buffer')
    return bytes(out)


def image_rectangles(picture, key=None):
    """Merge equal horizontal runs vertically; preserves every rendered pixel.

    Runs of the key colour are dropped: the foreground layer keys out where the
    background and the guest lighting must remain visible.
    """
    px=picture.convert('RGB'); width,height=px.size; active={}; result=[]
    left,top,right,bottom=0,0,width,height
    if key is not None:
        # Slot badges occupy only 30x15 pixels of a 512x448 keyed image.
        # Scan its real content, preserving full-frame coordinates and run
        # order. Avoid millions of PIL getpixel/load calls on first menu open.
        from PIL import Image,ImageChops
        bounds=ImageChops.difference(px,Image.new('RGB',px.size,tuple(key))).getbbox()
        if bounds is None:return []
        left,top,right,bottom=bounds
    pixels=px.load()
    for y in range(top,bottom):
        row={}; x=left
        while x<right:
            color=pixels[x,y]; end=x+1
            while end<right and pixels[end,y]==color: end+=1
            key_=(x,end,color); row[key_]=active.pop(key_,y); x=end
        for (x0,x1,color),y0 in active.items(): result.append((x0,y0,x1,y,color))
        active=row
    result.extend((x0,y0,x1,bottom,color) for (x0,x1,color),y0 in active.items())
    if key is not None: result=[r for r in result if r[4]!=tuple(key)]
    return result


def picture_rectangles(picture):
    """A modal picture as one full-frame rectangle of its most common colour,
    then only the runs of every other colour (drawn later, on top).

    The GS shows exactly the pixels of image_rectangles(picture) with far
    fewer sprites: a flat background no longer costs one run per text gap.
    """
    px=picture.convert('RGB'); width,height=px.size
    background=max(px.getcolors(width*height))[1]
    return [(0,0,width,height,background)]+image_rectangles(px,key=background)


KEY = (255, 0, 255)


@lru_cache(maxsize=483)
def _portrait(character_id,colors=32):
    from PIL import Image
    from character_names import character_info
    with Image.open(character_info(character_id)['bitmap_path']) as source:
        # Keep the real portrait. A bounded palette makes every six-card screen
        # fit the existing immutable GS packet buffers without texture uploads.
        return source.convert('RGB').resize((56,56)).quantize(colors=colors).convert('RGB')


def _draw_picture(teams=(), progress=0, message='GETTING YOUR FIGHTERS READY', *, mode='teams', humans=1, portrait_colors=32):
    """Legacy single-layer picture, the fallback when the Ki Storm painter is unavailable."""
    from PIL import Image, ImageDraw
    from localization import guest
    from guest_killfeed import GLYPHS
    from loading_design import design, WHITE, MUTED
    view=design(teams,mode,humans)
    canvas=Image.new('RGB',(512,448),view['background']);d=ImageDraw.Draw(canvas)
    def label(text,x,y,color=WHITE,scale=1,maxlen=70):
        for ch in guest(text.upper()).decode()[:maxlen]:
            rows=GLYPHS.get(ch,GLYPHS['?'])
            for yy,bits in enumerate(rows):
                for xx,bit in enumerate(bits):
                    if bit=='1':d.rectangle((x+xx*scale,y+yy*scale,x+(xx+1)*scale-1,y+(yy+1)*scale-1),fill=color)
            x+=6*scale
    def wrapped(text,maxlen):
        lines=['']
        for word in text.upper().replace('SUPER SAIYAN','SS').split():
            if lines[-1] and len(lines[-1])+len(word)+1>maxlen:lines.append(word)
            else:lines[-1]=(' '.join((lines[-1],word))).strip()
        return lines[:2]
    accent=view['accent']
    d.rectangle((0,0,511,4),fill=accent)
    label(view['heading'],28,25,scale=3)
    label(view['subtitle'],29,57,MUTED)
    if mode=='ffa':
        d.polygon([(455,22),(476,43),(455,64),(434,43)],outline=accent,width=2)
        for x,y in ((455,22),(476,43),(455,64),(434,43)):
            d.rectangle((x-2,y-2,x+2,y+2),fill=accent)
    elif mode=='coop':
        d.rectangle((434,26,458,50),outline=accent,width=3)
        d.rectangle((449,38,473,62),outline=accent,width=3)
    else:
        for x,color in ((439,(68,179,246)),(466,(245,116,97))):
            for y in (29,42,55):d.rectangle((x,y,x+7,y+7),fill=color)
    if view['detail']:label(view['detail'],28,89,accent)
    for group in view['groups']:label(group['label'],group['x'],group['y'],group['accent'],2)
    for card in view['cards']:
        x,y,w,h=card['x'],card['y'],card['width'],card['height'];color=card['accent'];info=card['info']
        d.rectangle((x,y,x+w-1,y+h-1),fill=(29,23,39) if mode=='ffa' else (18,29,47))
        d.rectangle((x,y,x+2,y+h-1),fill=color)
        canvas.paste(_portrait(info['character_id'],portrait_colors),(x+7,y+6))
        if card['compact']:
            label(card['role'],x+71,y+12,color,maxlen=11)
            label('FIGHTER',x+71,y+31,MUTED,maxlen=11)
            label(str(view['cards'].index(card)+1).zfill(2),x+71,y+44,WHITE,2)
            for j,line in enumerate(wrapped(info['base_name'],21)):label(line,x+8,y+68+j*10,maxlen=21)
            label(info['form'].replace('Super Saiyan','SS'),x+8,y+92,color,maxlen=21)
        else:
            for j,line in enumerate(wrapped(info['base_name'],21)):label(line,x+72,y+9+j*10,maxlen=21)
            label(info['form'].replace('Super Saiyan','SS'),x+72,y+36,color,maxlen=21)
            label(card['role'],x+72,y+53,MUTED,maxlen=21)
    if mode!='ffa':label('VS',250,214,MUTED,maxlen=2)
    p=max(0,min(100,int(progress)))
    label(view['footer'],28,360,WHITE,2)
    d.rectangle((28,389,483,398),fill=(28,43,66))
    if p:d.rectangle((28,389,28+int(455*p/100),398),fill=accent)
    label(message,28,418,MUTED,maxlen=75)
    return canvas


def _compose(teams,progress,message,mode,humans,error=None):
    """Ki Storm artwork; a presentation defect must never abort a preparation."""
    try:
        import loading_art_v4
        return loading_art_v4.compose(teams,progress,message,mode=mode,humans=humans,**({'error':error} if error else {}))
    except Exception:
        canvas=_draw_picture(teams,progress,' / '.join(error) if error else message,mode=mode,humans=humans)
        return dict(background=canvas,foreground=None,lights=None)


def is_v4(layers):
    return layers.get('atlas_image') is not None


def descriptor_for(layers,progress):
    """The descriptor of a v4 picture at one progress value (digits from the atlas table)."""
    import loading_art_v4
    return protocol.encode_lights(layers,progress,loading_art_v4.gauge_digits(progress))


def layer_packets(layers):
    """(packet A, packet B, descriptor) for one picture.

    v4 layers (with an atlas) -> the textured packets and the descriptor; the
    quantised pictures are kept in layers['quantised']. Legacy layers (RGB
    foreground keyed with KEY, or no foreground) -> one rectangle packet A, no
    packet B, no descriptor: the guest copies it and draws no lights.
    """
    if is_v4(layers):
        import loading_textures
        quantised=layers.get('quantised')
        if quantised is None:quantised=layers['quantised']=loading_textures.quantise(layers)
        packet_a,packet_b=protocol.packet_a(quantised),protocol.packet_b()
        descriptor=descriptor_for(layers,layers.get('progress',0))
        if len(packet_a)+len(packet_b)+len(descriptor)>CAPACITY-16: raise ValueError('Loading layers exceed the reserved buffer')
        return packet_a,packet_b,descriptor
    rectangles=image_rectangles(composite(layers))
    if len(rectangles)>=10240: raise ValueError('Loading layer exceeds the native sprite budget')
    return gif_packet(rectangles),b'',b''


def composite(layers):
    """What the GS shows: the quantised v4 composite, or the keyed legacy foreground over the background."""
    if is_v4(layers):
        import loading_textures
        return loading_textures.composite_quantised(layers.get('quantised') or layers)
    if layers.get('foreground') is None: return layers['background']
    from PIL import Image, ImageChops
    fg=layers['foreground'].convert('RGB'); key=Image.new('RGB',fg.size,KEY)
    r,g,b=ImageChops.difference(fg,key).split()
    mask=ImageChops.lighter(ImageChops.lighter(r,g),b).point(lambda v:255 if v else 0)
    return Image.composite(fg,layers['background'].convert('RGB'),mask)


def render(teams=(),progress=0,message='GETTING YOUR FIGHTERS READY',*,mode='teams',humans=1,error=None):
    """Return (picture, layers, packets) for one loading screen (error: the failure state's two lines)."""
    import os
    if os.environ.get('BT3_LOADING_PROBE')=='1':   # Phase 0c: the guest draws the textured test card instead
        import loading_texture_probe;return loading_texture_probe.render()
    layers=_compose(teams,progress,str(message),mode,humans,error)
    try:packets=layer_packets(layers)
    except ValueError:
        # Only the rectangle fallback has a sprite budget: fewer portrait colours fit it.
        if is_v4(layers):raise
        for colors in (16,8,4,2):
            layers=dict(background=_draw_picture(teams,progress,str(message),mode=mode,humans=humans,portrait_colors=colors),foreground=None,lights=None)
            try:packets=layer_packets(layers);break
            except ValueError:continue
        else:raise ValueError('Loading artwork exceeds the native sprite budget')
    return composite(layers),layers,packets


# One picture is painted at a time: the pre-render thread and show() never share the fonts,
# portraits and quantiser caches concurrently, and show() finds an in-flight pre-render done.
_RENDER_LOCK=threading.Lock()


def artwork(teams=(),progress=0,message='GETTING YOUR FIGHTERS READY',*,mode='teams',humans=1):
    """Compatibility view: the composite picture and its own sprite rectangles."""
    picture_=render(teams,progress,message,mode=mode,humans=humans)[0]
    return picture_,image_rectangles(picture_)


def picture(teams=(),progress=0,message='GETTING YOUR FIGHTERS READY',*,mode='teams',humans=1):
    return render(teams,progress,message,mode=mode,humans=humans)[0]


SUBS, SUBS_END = 0x07473000, 0x07474000


@lru_cache(maxsize=1)
def subroutines():
    """Shared emitters called from the payload's frame: (bytes, label addresses)."""
    a=Assembler(SUBS)
    # scale: v0 = a0 * (1..4) selected by a1 bits (1: +a0, 2: +2*a0).
    a.label('scale');a.move(2,4);a.i(12,8,5,1);a.branch(4,8,0,'scale_two');a.r(0x2D,2,2,4)
    a.label('scale_two');a.i(12,8,5,2);a.branch(4,8,0,'scale_done');a.r(0,8,0,4,1);a.r(0x2D,2,2,8)
    a.label('scale_done');a.jr()
    # prim: A+D write of PRIM = a0 (32 bytes) at s7; resets the vertex queue.
    a.label('prim');a.i(13,8,0,PRIM_TAG[0]);a.sw(8,23,0);a.li(8,PRIM_TAG[1]);a.sw(8,23,4)
    a.addiu(8,0,PRIM_TAG[2]);a.sw(8,23,8);a.sw(0,23,12);a.sw(4,23,16);a.sw(0,23,20);a.sw(0,23,24);a.sw(0,23,28)
    a.addiu(23,23,PRIM_BYTES);a.jr()
    # vertex: RGBAQ+XYZ2 (16 bytes) at s7 for a0=x, a1=y, a2=packed colour.
    a.label('vertex');a.addiu(8,4,1792);a.r(0,8,0,8,4);emit_window_y(a,9,5,20);a.r(0x25,8,8,9)
    a.sw(6,23,0);a.li(9,Q_ONE);a.sw(9,23,4);a.sw(8,23,8);a.sw(0,23,12);a.addiu(23,23,16);a.jr()
    # sprite: a0,a1 -> a2,a3 with colour t9 (24 bytes).
    a.label('sprite');a.sw(25,23,0);a.li(9,Q_ONE);a.sw(9,23,4)
    a.addiu(8,4,1792);a.r(0,8,0,8,4);emit_window_y(a,9,5,20);a.r(0x25,8,8,9);a.sw(8,23,8);a.sw(0,23,12)
    a.addiu(8,6,1792);a.r(0,8,0,8,4);emit_window_y(a,9,7,20);a.r(0x25,8,8,9);a.sw(8,23,16);a.sw(0,23,20)
    a.addiu(23,23,24);a.jr()
    def strip(name,order):
        a.label(name);a.sw(31,29,STRIP_RA)
        a.addiu(4,0,STRIP_PRIM);a.jump('prim',True)
        a.i(13,8,0,STRIP_TAG[0]);a.sw(8,23,0);a.li(8,STRIP_TAG[1]);a.sw(8,23,4)
        a.i(13,8,0,STRIP_TAG[2]);a.sw(8,23,8);a.sw(0,23,12);a.addiu(23,23,16)
        for i,(x,y) in enumerate(order):
            a.lw(4,29,PARAMS+4*x);a.lw(5,29,PARAMS+4*y);a.lw(6,29,PARAMS+20+4*i);a.jump('vertex',True)
        a.lw(31,29,STRIP_RA);a.jr()
    # strip_h params: xa,xb,xc,y0,y1 then six colours; strip_v: x0,x1,ya,yb,yc.
    strip('strip_h',((0,3),(0,4),(1,3),(1,4),(2,3),(2,4)))
    strip('strip_v',((0,2),(1,2),(0,3),(1,3),(0,4),(1,4)))
    # bolt: nine-point gouraud line strip from BOLT_PARAMS; s6 = noise table.
    a.label('bolt');a.sw(31,29,STRIP_RA)
    a.addiu(4,0,BOLT_PRIM);a.jump('prim',True)
    a.i(13,8,0,BOLT_TAG[0]);a.sw(8,23,0);a.li(8,BOLT_TAG[1]);a.sw(8,23,4)
    a.i(13,8,0,BOLT_TAG[2]);a.sw(8,23,8);a.sw(0,23,12);a.addiu(23,23,16)
    a.move(18,0)                                             # s2 = point index
    a.label('bolt_point')
    a.lw(4,29,BOLT_PARAMS);a.lw(5,29,BOLT_PARAMS+4)          # running x, y
    a.lw(8,29,BOLT_PARAMS+8);a.r(0x2D,8,8,4);a.sw(8,29,BOLT_PARAMS)
    a.lw(8,29,BOLT_PARAMS+12);a.r(0x2D,8,8,5);a.sw(8,29,BOLT_PARAMS+4)
    a.lw(6,29,BOLT_PARAMS+20)                                # end colour unless inner
    a.branch(4,18,0,'bolt_vertex');a.addiu(8,0,BOLT_POINTS-1);a.branch(4,18,8,'bolt_vertex')
    a.lw(6,29,BOLT_PARAMS+16)
    a.lw(9,29,BOLT_PARAMS+24);a.i(12,8,9,127);a.r(0x2D,8,8,22);a.i(36,8,8,0)
    a.r(3,8,0,8,3);a.addiu(8,8,-16);a.r(0x2D,4,4,8)          # x jitter
    a.addiu(8,9,64);a.i(12,8,8,127);a.r(0x2D,8,8,22);a.i(36,8,8,0)
    a.r(3,8,0,8,3);a.addiu(8,8,-16);a.r(0x2D,5,5,8)          # y jitter
    a.label('bolt_vertex')
    a.lw(9,29,BOLT_PARAMS+24);a.addiu(9,9,11);a.sw(9,29,BOLT_PARAMS+24)
    a.lw(8,29,BOLT_PARAMS+28);a.r(0x2D,4,4,8)                # glow offset
    a.lw(8,29,BOLT_PARAMS+32);a.branch(5,8,0,'bolt_emit')
    a.addiu(4,0,OFFSCREEN);a.addiu(5,0,OFFSCREEN)
    a.label('bolt_emit');a.jump('vertex',True)
    a.addiu(18,18,1);a.addiu(8,0,BOLT_POINTS);a.branch(5,18,8,'bolt_point')
    # Restore the start point (nine steps were added) for the same bolt's next strip.
    a.lw(8,29,BOLT_PARAMS+8);a.r(0,9,0,8,3);a.r(0x2D,9,9,8);a.lw(8,29,BOLT_PARAMS);a.r(0x23,8,8,9);a.sw(8,29,BOLT_PARAMS)
    a.lw(8,29,BOLT_PARAMS+12);a.r(0,9,0,8,3);a.r(0x2D,9,9,8);a.lw(8,29,BOLT_PARAMS+4);a.r(0x23,8,8,9);a.sw(8,29,BOLT_PARAMS+4)
    a.lw(8,29,BOLT_PARAMS+24);a.addiu(8,8,-11*BOLT_POINTS);a.sw(8,29,BOLT_PARAMS+24)
    a.lw(31,29,STRIP_RA);a.jr()
    data=a.finish();assert len(data)<SUBS_END-SUBS;return data,dict(a.labels)


def SUB():return subroutines()[1]


def payload(menu_surface=True,native_modals=True):
    import native_preparation
    import loading_lights_a as ks_a
    import loading_lights_b as ks_b
    a=Assembler(CODE); a.addiu(29,29,-FRAME)
    for r,off in SAVED:a.i(63,r,29,off)
    a.call(native_preparation.CODE)
    a.li(16,CONTROL); a.lw(8,16); a.li(9,MAGIC); a.branch(5,8,9,'undrawn')
    if menu_surface:
        a.lw(8,16,32);a.branch(4,8,0,'battle_surface');a.addiu(9,0,1);a.branch(5,8,9,'undrawn')
        import mode_menu
        if native_modals:
            # Native pages deliberately leave the retired legacy overlay off.
            # Their modal pictures have their own live owner/scene/lease proof;
            # requiring legacy active+lease made both settings and team setup
            # capture input behind an invisible picture.
            import native_menu_services as menus
            import team_assignment as teams
            import ingame_settings as settings
            import scenario_menu as scenarios
            menus.scope(a,'legacy_menu')
            a.lw(9,8,teams.STATE);a.addiu(10,0,1);a.branch(5,9,10,'settings_modal')
            a.lw(9,8,teams.LEASE);a.branch(5,9,0,'menu_ready')
            a.label('settings_modal');a.li(8,settings.CONTROL);a.lw(9,8);a.li(10,settings.MAGIC)
            a.branch(5,9,10,'scenario_modal');a.lw(9,8,4);a.addiu(10,0,1);a.branch(5,9,10,'scenario_modal')
            a.lw(9,8,8);a.branch(5,9,0,'menu_ready')
            a.label('scenario_modal');a.li(8,scenarios.CONTROL);a.lw(9,8);a.li(10,scenarios.MAGIC)
            a.branch(5,9,10,'legacy_menu');a.lw(9,8,4);a.addiu(10,0,1);a.branch(5,9,10,'legacy_menu')
            a.lw(9,8,8);a.branch(5,9,0,'menu_ready')
            a.label('legacy_menu')
        a.li(8,mode_menu.CONTROL);a.lw(9,8);a.li(10,mode_menu.MAGIC);a.branch(5,9,10,'undrawn')
        a.lw(9,8,4);a.branch(4,9,0,'undrawn');a.lw(9,8,16);a.branch(4,9,0,'undrawn')
        a.lw(9,8,28);a.li(10,mode_menu.MAIN_CALLER);a.branch(5,9,10,'undrawn')
        a.lw(9,8,32);a.addiu(10,0,4);a.branch(5,9,10,'undrawn')
        if native_modals:a.label('menu_ready')
        a.li(8,SCENE_LOOP);a.lw(8,8);a.branch(5,8,0,'undrawn');a.jump('surface_ready')
        a.label('battle_surface');a.li(8,SCENE_LOOP);a.lw(8,8);a.addiu(9,0,1);a.branch(5,8,9,'undrawn')
        a.label('surface_ready')
    else:
        a.li(8,SCENE_LOOP); a.lw(8,8); a.addiu(9,0,1);a.branch(5,8,9,'undrawn')
    a.lw(8,16,16); a.i(11,9,8,LEASE); a.branch(4,9,0,'expire')
    a.addiu(8,8,1); a.sw(8,16,16)
    a.lw(17,16,4); a.li(8,BUFFERS[0]); a.branch(4,17,8,'buffer')
    a.li(8,BUFFERS[1]); a.branch(5,17,8,'expire')
    a.label('buffer');a.sw(17,29,0x38);a.lw(18,17)
    a.i(12,8,18,15);a.branch(5,8,0,'expire')
    a.i(11,8,18,128);a.branch(5,8,0,'expire');a.li(8,CAPACITY-15-DESCRIPTOR)
    a.r(0x2B,8,18,8);a.branch(4,8,0,'expire')
    # Foreground split offset: zero, or a 16-byte aligned offset inside the packets.
    a.lw(19,17,8);a.i(12,8,19,15);a.branch(5,8,0,'expire')
    a.r(0x2B,8,18,19);a.branch(5,8,0,'expire')
    # Descriptor: absent, or exactly after the packets with its magic (s4 = 0 means no lights).
    a.move(20,0);a.lw(8,17,12);a.branch(4,8,0,'no_lights');a.branch(5,8,18,'expire')
    a.addiu(20,17,16);a.r(0x2D,20,20,18);a.lw(8,20);a.li(9,LIGHTS);a.branch(4,8,9,'no_lights');a.move(20,0)
    a.label('no_lights')
    # Honor the active native GIF arena, including before its later4MiB growth.
    a.lw(8,28,-23004);a.i(11,9,8,2);a.branch(4,9,0,'expire')
    a.r(0,8,0,8,2);a.r(0x2D,8,28,8)
    # t0 = gp + 4*index: the arena base/end offsets are gp offsets through another register (GPO by hand).
    a.lw(9,8,GPO(-23024));a.lw(10,8,GPO(-23016));a.lw(11,28,-23016+8)
    a.r(0x2D,11,11,9);a.branch(5,11,10,'expire')
    a.lw(11,28,-23000);a.r(0x2B,12,11,9);a.branch(5,12,0,'expire')
    # Telemetry: the largest native cursor offset seen at the hook (1 MiB arena headroom).
    a.r(0x23,12,11,9);a.lw(13,16,CURSOR_MAX);a.r(0x2B,14,13,12);a.branch(4,14,0,'cursor_kept');a.sw(12,16,CURSOR_MAX)
    a.label('cursor_kept')
    # Reserve = the two REF tags and the fixed KS blocks; the pictures are never copied, so a
    # frame needs tens of kilobytes of arena, not half a megabyte. RESERVE exceeds an addiu.
    a.li(13,RESERVE);a.r(0x21,12,11,13)
    a.r(0x2B,13,12,11);a.branch(5,13,0,'expire')
    a.r(0x2B,13,10,12);a.branch(5,13,0,'no_space')
    # Steps this frame come from elapsed emulated time, not from drawn frames. The cover
    # is drawn once per main-loop pass and nearly every loading loop waits two vblanks a
    # pass (sub_102060 -> sub_264D98), so counting frames played an animation authored at
    # 60 steps a second at half speed, and slower again on any heavy frame. t5 = steps:
    # one on a cover's first frame, else elapsed cycles over the tick with the remainder
    # carried. Only t0..t3 and t5 are touched (t4 holds the arena reserve above), and
    # nothing after this reads a t register it has not written.
    a.emit(0x40000000|(8<<16)|(9<<11))                        # mfc0 t0, Count
    a.lw(9,16,LAST_COUNT);a.sw(8,16,LAST_COUNT);a.addiu(13,0,1)
    a.branch(4,9,0,'first_step')
    a.r(0x23,8,8,9)                                           # elapsed cycles, wrap-safe
    a.li(9,MAX_ELAPSED);a.r(0x2B,10,9,8);a.branch(4,10,0,'elapsed_ok');a.move(8,9)
    a.label('elapsed_ok')
    a.lw(9,16,TICK_ACC);a.r(0x21,8,8,9)
    a.lw(9,16,TICK_WORD)
    a.li(10,MIN_TICK);a.r(0x2B,11,9,10);a.branch(5,11,0,'tick_default')
    a.li(10,MAX_TICK);a.r(0x2B,11,10,9);a.branch(4,11,0,'tick_ok')
    a.label('tick_default');a.li(9,TICK)
    a.label('tick_ok');a.move(13,0)
    a.label('step');a.r(0x2B,10,8,9);a.branch(5,10,0,'carry')
    a.r(0x23,8,8,9);a.addiu(13,13,1);a.jump('step')
    a.label('carry');a.sw(8,16,TICK_ACC);a.jump('stepped')
    a.label('first_step');a.sw(0,16,TICK_ACC)
    a.label('stepped')
    # Animation phase: battle frames at +12, menu frames at +36.
    if menu_surface:
        a.lw(8,16,32);a.branch(4,8,0,'battle_frames')
        a.lw(8,16,MENU_FRAMES);a.r(0x21,8,8,13);a.sw(8,16,MENU_FRAMES);a.move(21,8);a.jump('counted')
        a.label('battle_frames')
    a.lw(8,16,12);a.r(0x21,8,8,13);a.sw(8,16,12);a.move(21,8)
    a.label('counted')
    # Clash cycle: advances by the same steps, modulo CYCLE (no div). An out-of-range
    # cycle restarts at 0 as it always has; a valid one plus at most 17 steps needs one
    # subtraction to wrap.
    a.lw(8,16,CYCLE_WORD);a.i(11,9,8,CYCLE);a.branch(4,9,0,'cycle_restart')
    a.r(0x21,8,8,13);a.i(11,9,8,CYCLE);a.branch(5,9,0,'cycle_ok')
    a.addiu(8,8,-CYCLE);a.jump('cycle_ok')
    a.label('cycle_restart');a.move(8,0)
    a.label('cycle_ok');a.sw(8,16,CYCLE_WORD)
    a.addiu(17,17,16);a.move(22,19);a.branch(5,19,0,'part_one');a.move(22,18)
    a.label('part_one');a.r(0x2D,22,22,17)
    def reference(tag):
        # Native REF-tag builder: a0 = the run's first qword (its VIF prologue), a1 = its bytes.
        a.move(4,17);a.r(0x23,5,22,17);a.call(A(0x100738));a.move(17,22)
    def ks(tag,piece):
        # One allocation for the KS piece: s7 cursor, s4 descriptor, s5 frame
        # counter, s6 buffer; it returns through the address stored at KS_RETURN.
        a.branch(4,20,0,'after_'+tag)
        a.call(A(0x100878));a.move(23,2);a.lw(22,29,0x38)
        back=a.pc+5*4
        a.li(8,back);a.sw(8,29,KS_RETURN);a.jump(piece.ENTRY);a.label('return_'+tag)
        assert a.labels['return_'+tag]==back
        a.move(4,23);a.call(A(0x100890))
        a.label('after_'+tag)
    reference('a')
    ks('ks_a',ks_a)
    a.branch(4,19,0,'after_foreground')
    a.lw(8,29,0x38);a.lw(18,8);a.addiu(8,8,16);a.r(0x2D,22,8,18)
    reference('b')
    a.label('after_foreground')
    ks('ks_b',ks_b)
    a.label('drawn');a.lw(8,29,0x38);a.sw(8,16,24);a.addiu(8,0,1);a.sw(8,16,DRAWN_LATCH);a.jump('native')
    a.label('no_space');a.lw(8,16,28);a.addiu(8,8,1);a.sw(8,16,28);a.jump('undrawn')
    a.label('expire');a.sw(0,16)
    # Cover dropped after a drawn frame: the pictures clobbered the 2D sprite
    # texture change-cached at 0x2D00 and the HUD banks' upload caches, so force
    # their re-upload once (the 2D handle compared by sub_13DB90, then the
    # argument-free native invalidation sub_21F438, a leaf clobbering v0/v1/a0/a1).
    a.label('undrawn');a.lw(8,16,DRAWN_LATCH);a.branch(4,8,0,'native');a.sw(0,16,DRAWN_LATCH)
    a.li(8,SPRITE_2D);a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'no_handle')
    a.li(9,0x08000000);a.r(0x2B,9,8,9);a.branch(4,9,0,'no_handle');a.sw(0,8,0x230)
    a.label('no_handle');a.call(HUD_INVALIDATE)
    a.label('native')
    for r,off in SAVED:a.i(55,r,29,off)
    a.addiu(29,29,FRAME);a.jump(A(0x263030))
    result=a.finish();assert len(result)<CONTROL-CODE;return result


@lru_cache(maxsize=1)
def code_pieces():
    import native_preparation
    native=elf_reader(elf_path(ROOT))[2]
    assert struct.unpack('<2I',native(HOOK,8))==(0x0C000000|(A(0x263030)>>2),0x34A54040)
    import mode_menu
    import native_mode_menu
    import select_duplicates
    import loading_lights_a as ks_a
    import loading_lights_b as ks_b
    # The team select screen appears before any match is prepared, so the
    # same-team duplicate unlock has to be resident from boot like the menu.
    # Keep each address exactly once: the native pager wraps the old pad hook,
    # whose code remains available for the established Duel route.
    pieces=(native_preparation.code_pieces()+mode_menu.code_pieces()+native_mode_menu.code_pieces()+select_duplicates.code_pieces()
            +[(CODE,payload()),(SUBS,subroutines()[0]),(ks_a.CODE,ks_a.code()),(ks_b.CODE,ks_b.code()),
              (HOOK,struct.pack('<I',(3<<26)|(CODE>>2)))])
    return list(dict(pieces).items())


def _legacy_images(*keys):
    import json
    data=json.loads((Path(__file__).with_name('loading_legacy_payloads.json')).read_text())
    return tuple(bytes.fromhex(data[k]) for k in keys)


def legacy_payloads():
    """Exact September16 and v3 (September20) payloads, retained for prepared-preset validation.

    The v3 blobs were frozen before the v4 emitter move, so a v4 payload may be
    shorter than a legacy image found in a captured state.
    """
    return _legacy_images('sept16_menu_surface','sept16_battle_only','sept20_v3_menu_surface','sept20_v3_battle_only')


def legacy_subs():
    """Exact v3 SUBS emitters (September20) for the same validation."""
    return _legacy_images('sept20_v3_subs')


def pnach():
    lines=['// BT3 owned loading surface v4 (Ki Storm textured pictures, KS light pieces) and frame-boundary preparation service. Dormant until armed.']
    for address,data in code_pieces():
        for off in range(0,len(data),4):
            lines.append(f'patch=1,EE,{address+off:08X},word,{struct.unpack_from("<I",data,off)[0]:08X}')
    return ('\n'.join(lines)+'\n').encode()


def install_cheat(path=CHEAT):
    from atomic_files import write_bytes
    path=Path(path);data=pnach();path.parent.mkdir(parents=True,exist_ok=True)
    receipt=path.with_suffix('.owned-sha256')
    if path.exists():
        previous=path.read_bytes()
        if previous!=data:
            owned=receipt.read_text().strip() if receipt.exists() else ''
            if hashlib.sha256(previous).hexdigest()!=owned:
                raise ValueError(f'Loading hook file is occupied: {path}')
            write_bytes(path,data)
    else:
        with path.open('xb') as f:f.write(data)
    result=hashlib.sha256(data).hexdigest();write_bytes(receipt,(result+'\n').encode())
    return result


# What each guest buffer holds as far as THIS process knows: buffer -> (generation
# written there, packet identity). A header-only republish (progress change) is
# allowed only when the record matches the header read back from the guest.
_written={}
_stale_logged=False


def invalidate_buffers():
    """Forget every buffer record: after a savestate load, a hide or a failed write."""
    _written.clear()


def tick_for(percent):
    """Cycles per animation step for a speed preference; 100% is the approved design."""
    if type(percent) not in (int,float) or not 25<=percent<=400:percent=100
    return max(MIN_TICK,min(MAX_TICK,round(TICK*100/percent)))


def speed_preference():
    """The saved animation speed. A settings problem must never cost the cover."""
    try:
        import mod_settings
        return mod_settings.load_settings().get('loading_animation_speed_percent',100)
    except Exception:
        return 100


class GuestLoadingScreen:
    def __init__(self,speed=None):
        self.lock=threading.RLock();self.visible=False;self.teams=[];self.packet=None;self.packet_id=None
        self.foreground=0;self.descriptor=b'';self.layers=None;self.progress=None;self.reset_counters=False
        self.generation=secrets.randbits(31);self.last_sync=0;self.available=False;self.key=None;self.surface=0
        self.mode,self.humans='teams',1
        # A fixed speed stays; otherwise every new cover re-reads the saved preference.
        self.speed=speed
        self.tick=tick_for(speed_preference() if speed is None else speed)
        self._ahead_lock=threading.Lock();self._ahead_context=None;self._ahead={};self._ahead_used=set()

    def set_mode(self,mode='teams',humans=1):
        from loading_design import mode_options
        selected=mode_options(mode,humans)
        with self.lock:
            if selected==(self.mode,self.humans):return False
            self.mode,self.humans=selected;self.key=None
            return True

    def set_teams(self,teams):
        with self.lock:
            self.teams=teams;self.key=None

    def _bump(self):
        self.generation=(self.generation+1)&0xFFFFFFFF or 1

    def _publish(self,packets):
        # Each packet is published behind its VIF prologue: the guest references the buffer
        # instead of copying it, so the offsets name the prologues, not the GIF data.
        packet_a,packet_b,descriptor=packets
        part_a=protocol.referenced(packet_a)
        self.packet=part_a+(protocol.referenced(packet_b) if packet_b else b'')
        self.foreground=len(part_a) if packet_b else 0;self.descriptor=descriptor
        self.packet_id=hashlib.sha256(self.packet).digest();self._bump()

    def _show(self,client=None):
        # The entrance replays on every cover: the guest counters restart when
        # the screen goes from hidden to visible, never on a republish. A saved
        # animation speed applies from the next cover (sync publishes TICK_WORD).
        if not self.visible:
            self.reset_counters=True
            if self.speed is None:self.tick=tick_for(speed_preference())
        self.visible=True
        return self.sync(force=True,client=client)

    def show(self,message,progress,*,error=None):
        # error=(line 1, line 2): the failure state (red text, no gauge); its key never matches a pre-render.
        with self.lock:
            self.surface=0;progress=max(0,min(100,int(progress)))
            key=(localization.language(),self.mode,self.humans,repr(self.teams),str(message))+((tuple(error),) if error else ())
            if key!=self.key or self.layers is None or (not is_v4(self.layers) and progress!=self.progress):
                self.layers,packets=self._picture(key,progress,str(message),error=tuple(error) if error else None)
                self._publish(packets);self.key=key
            elif progress!=self.progress and self.descriptor:
                self.descriptor=descriptor_for(self.layers,progress);self._bump()
            self.progress=progress
            return self._show()

    def _picture(self,key,progress,message,*,error=None):
        with _RENDER_LOCK:
            with self._ahead_lock:
                ahead=self._ahead.pop(key,None)
                if key[:4]==self._ahead_context:self._ahead_used.add(key)
            if ahead is None:
                _,layers,packets=render(self.teams,progress,message,mode=self.mode,humans=self.humans,
                                        **({'error':error} if error else {}))
                return layers,packets
        # A v4 picture does not depend on progress (the guest draws the gauge from the
        # descriptor), so a pre-rendered one only needs this progress's descriptor.
        layers=dict(ahead[0],progress=progress);packet_a,packet_b,_=ahead[1]
        return layers,(packet_a,packet_b,descriptor_for(layers,progress))

    def prerender(self,messages):
        """Paint these messages' pictures on a background thread for the current teams, mode
        and language (called during native loading), so show() publishes them at once. The
        pictures are the ones show() would render; any miss still renders synchronously."""
        if os.environ.get('BT3_LOADING_PROBE')=='1':return False
        with self.lock:
            teams,mode,humans,shown=copy.deepcopy(self.teams),self.mode,self.humans,self.key
        context=(localization.language(),mode,humans,repr(teams))
        pending=[m for m in dict.fromkeys(str(m) for m in messages) if context+(m,)!=shown]
        with self._ahead_lock:
            if self._ahead_context==context:return False
            self._ahead_context=context;self._ahead={};self._ahead_used=set()
        threading.Thread(target=contextvars.copy_context().run,name='loading-prerender',daemon=True,
                         args=(self._render_ahead,context,teams,mode,humans,pending)).start()
        return True

    def _render_ahead(self,context,teams,mode,humans,pending):
        for message in pending:
            key=context+(message,)
            with _RENDER_LOCK:
                with self._ahead_lock:
                    if self._ahead_context!=context:return
                    if key in self._ahead_used:continue   # show() already painted it
                try:_,layers,packets=render(teams,0,message,mode=mode,humans=humans)
                except Exception:return   # show() renders it itself and reports any failure
                if not is_v4(layers) or localization.language()!=context[0]:continue
                with self._ahead_lock:
                    if self._ahead_context==context:self._ahead[key]=(layers,packets)

    def show_picture(self,canvas,surface='menu',client=None):
        with self.lock:
            self.surface=int(surface=='menu');self._publish((gif_packet(picture_rectangles(canvas)),b'',b''))
            self.key=None;self.layers=None
            return self._show(client)

    def show_layers(self,layers,surface='menu',client=None):
        with self.lock:
            self.surface=int(surface=='menu');self._publish(layer_packets(layers))
            self.key=None;self.layers=None
            return self._show(client)

    def sync(self,force=False,client=None):
        from pine import PineClient,PineError
        global _stale_logged
        with self.lock:
            if not self.visible or not self.packet:return False
            if not force and time.monotonic()-self.last_sync<.5:return self.available
            try:
                with nullcontext(client) if client is not None else PineClient(timeout=3) as p:
                    # A matching JAL can outlive a PNACH emitter upgrade. Verify
                    # the complete machine code before publishing the current
                    # immutable-buffer protocol.
                    stale=next((address for address,expected in code_pieces()
                                if p.read(address,len(expected))!=expected),None)
                    if stale is not None:
                        # PCSX2 re-applies the boot words every vsync, so after something rewrites the
                        # executable text (a reset reloading it, for one) a check can differ and a later one
                        # pass (European run 20260924-230953: one differing check at the battle-to-menu edge,
                        # later checks passed). Refuse this publish; warn only when checks 1 to 10 s apart
                        # keep differing. hide() forgets the mark, so a new cover starts a new window.
                        now=time.monotonic();first=getattr(self,'_stale_since',None)
                        if first is None or now-first>10:
                            self._stale_since=now
                            print(time.strftime('%H:%M:%S'),f'loading cover: boot code differs at 0x{stale:08X}; checking again',flush=True)
                        elif now-first>=1 and not _stale_logged:
                            from native_preparation import launcher
                            _stale_logged=True;print(time.strftime('%H:%M:%S'),'WARNING: '+localization.tr(
                                'In-game loading screen code differs at {address}; close PCSX2 and start {play} again.',
                                address=f'0x{stale:08X}',play=launcher()),flush=True)
                        self.available=False;return False
                    self._stale_since=None
                    p.write_u32(CONTROL+32,self.surface)
                    if self.reset_counters:
                        # A new cover replays its entrance from its first step.
                        for offset in (12,MENU_FRAMES,CYCLE_WORD,LAST_COUNT,TICK_ACC):p.write_u32(CONTROL+offset,0)
                        self.reset_counters=False
                    data=p.read(CONTROL,TICK_WORD+4);magic,ptr,size,drawn,age,generation,consumed=struct.unpack_from('<7I',data)
                    if struct.unpack_from('<I',data,TICK_WORD)[0]!=self.tick:p.write_u32(CONTROL+TICK_WORD,self.tick)
                    if generation!=self.generation or size!=len(self.packet):
                        # Never reuse an older packet until a guest frame has
                        # observed the last published pointer (paused mid-copy).
                        if ptr in BUFFERS and consumed!=ptr:
                            # A hide may have withdrawn the lease while an older
                            # buffer was still being copied. Re-arm the published
                            # packet, let it acknowledge, then reuse the other.
                            p.write_u32(CONTROL+16,0);p.write_u32(CONTROL,MAGIC)
                            self.available=True;self.last_sync=time.monotonic()
                            return True
                        other=BUFFERS[1] if ptr==BUFFERS[0] else BUFFERS[0]
                        tail=len(self.packet) if self.descriptor else 0
                        header=struct.pack('<4I',len(self.packet),self.generation,self.foreground,tail)
                        record=_written.pop(other,None)
                        if (record is not None and record[1]==self.packet_id
                                and p.read(other,16)==struct.pack('<4I',len(self.packet),record[0],self.foreground,tail)):
                            # The guest buffer still holds this very packet: publish
                            # the new header and descriptor only.
                            p.write(other,header)
                            if self.descriptor:p.write(other+16+len(self.packet),self.descriptor)
                        else:
                            p.write(other,header+self.packet+self.descriptor)
                        _written[other]=(self.generation,self.packet_id)
                        # Packet length belongs to the immutable buffer header.
                        # One32-bit pointer write publishes both together.
                        p.write_u32(CONTROL+4,other)
                        p.write_u32(CONTROL+8,len(self.packet));p.write_u32(CONTROL+20,self.generation)
                        p.write_u32(CONTROL+16,0);p.write_u32(CONTROL,MAGIC)
                    else:
                        p.write_u32(CONTROL+16,0);p.write_u32(CONTROL,MAGIC)
                    self.available=True;self.last_sync=time.monotonic();return True
            except (OSError,PineError):invalidate_buffers();self.available=False;return False

    def hide(self,client=None):
        from pine import PineClient,PineError
        with self.lock:
            self.visible=False;self._stale_since=None;invalidate_buffers()
            try:
                with nullcontext(client) if client is not None else PineClient(timeout=3) as p:
                    if p.read(HOOK,4)==code_pieces()[-1][1]:
                        no_space,cursor_max=struct.unpack('<2I',p.read(CONTROL+28,4)+p.read(CONTROL+CURSOR_MAX,4))
                        if no_space or cursor_max:
                            print(time.strftime('%H:%M:%S'),f'loading cover: no_space {no_space}, max native arena cursor {cursor_max:#x}',flush=True)
                        p.write_u32(CONTROL,0)
                        if p.read_u32(CONTROL)!=0:return False
                return True
            except (OSError,PineError):return False

    def presented(self,client):
        """Non-blocking proof that this exact picture reached a guest frame."""
        if not self.visible or not self.packet:return False
        data=client.read(CONTROL,DRAWN_LATCH+4)
        magic,ptr,size,draws,age,generation,consumed=struct.unpack_from('<7I',data)
        counter=struct.unpack_from('<I',data,MENU_FRAMES)[0] if self.surface else draws
        return (magic==MAGIC and ptr in BUFFERS and consumed==ptr and counter>0
                and bool(struct.unpack_from('<I',data,DRAWN_LATCH)[0])
                and generation==self.generation and size==len(self.packet))

    def wait_drawn(self,timeout=2):
        """A submitted packet is not a rendered frame; wait for the guest ACK."""
        from pine import PineClient,PineError
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if not self.visible:return False
            self.sync()
            try:
                with PineClient(timeout=3) as p:
                    magic,ptr,size,draws,age,generation,consumed=struct.unpack('<7I',p.read(CONTROL,28))
                if (magic==MAGIC and ptr in BUFFERS and consumed==ptr and draws>0
                        and generation==self.generation and size==len(self.packet)):
                    return True
            except (OSError,PineError):return False
            time.sleep(.03)
        return False


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['install','preview']);args=p.parse_args()
    if args.action=='install':print(install_cheat())
    else:picture([{'fighters':[{'character_id':c} for c in team]} for team in ([54,3,21],[109,117,133])],65).save(ROOT/'analysis/native-loading-preview.png')
