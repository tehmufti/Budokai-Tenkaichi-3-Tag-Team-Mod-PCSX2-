"""Compact status panels scoped to each native world viewport.

Two panels per viewport: the watched fighter and that fighter's actual target.
All drawing uses existing native GS packet submitters under the world pass's
scissor. Rectangle descriptors and subject pointers allow four future views;
no extra controllers or rendering viewports are created by this module.
"""
from native_map import A
import struct
from prototype import Assembler
import fresh_team_combat as core
import fresh_team_camera as camera
import guest_killfeed as feed
import guest_healthbars as bars
import battle_mode_policy as modes
import hud_subject
import spectator_takeover as spectator
from regional import DISPLAY_H, SCISSOR_Y1, Y_ORIGIN

# The four-view cinematic checks need more than 1 KiB. Keep their code clear
# of DRAW; its 736-byte body still fits comfortably before POST at +0x1000.
CODE, ACTIVE, DRAW, PANEL, NUMBER = 0x072D0000,0x072D0400,0x072D0900,0x072D1800,0x072D3000
POST, SCISSOR = 0x072D1000,0x072D3800
CONTROL, VIEWS, END = 0x072DF000,0x072DF100,0x072E0000
MAGIC=0x56504831
POST_MAGIC=0x48555032
VIEW_STRIDE, MAX_VIEWS = 24,4
# enabled, x0,x1,y0,y1, pointer-to-current-physical-subject
DEFAULT_VIEWS=((1,0,254,0,SCISSOR_Y1,camera.SUCCESSOR_CONTROL+8),
               (1,257,511,0,SCISSOR_Y1,camera.SUCCESSOR_CONTROL+12))
SAVED=tuple(range(2,28))+(30,31)
FRAME=0x240


def save(a):
    a.addiu(29,29,-FRAME)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)
    a.r(16,8,0);a.i(63,8,29,0xE0);a.r(18,8,0);a.i(63,8,29,0xE8)


def restore(a,skip=()):
    a.i(55,8,29,0xE0);a.r(17,0,8);a.i(55,8,29,0xE8);a.r(19,0,8)
    for i,r in enumerate(SAVED):
        if r not in skip:a.i(55,r,29,8*i)
    a.addiu(29,29,FRAME)


def active(shared_ultimate=True,shared_form=True,form_fallback=True,quad_support=False,shared_rush=True):
    """v0: split panels own the HUD; preserve every argument and caller register."""
    a=Assembler(ACTIVE);save(a);core.gate(a,'no')
    if quad_support:
        import multiplayer_fusion as fusion
        a.li(8,fusion.CONTROL);a.lw(9,8);a.li(11,fusion.MAGIC);a.branch(5,9,11,'quad_intro')
        a.call(fusion.SHARED);a.branch(5,2,0,'no');a.label('quad_intro')
        # Intros/results use one native view. The four-panel pass must follow
        # the same released-combat boundary as the four-view world renderer.
        a.li(8,A(0x2FEB38));a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'no')
        a.li(9,0x7FFFF00);a.r(0x2B,9,8,9);a.branch(4,9,0,'no')
        a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,'no')
        a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'no')
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(4,9,0,'no');a.lw(9,8,12);a.i(11,11,9,MAX_VIEWS+1);a.branch(4,11,0,'no')
    a.i(11,11,9,2);a.branch(5,11,0,'no')
    a.li(8,hud_subject.SCENE);a.lw(9,8,hud_subject.SPLIT_OFF);a.addiu(11,0,hud_subject.SPLIT_VALUE);a.branch(5,9,11,'no')
    if shared_ultimate:
        # A checked live ultimate owns one native full-screen camera. Ask the
        # authenticated current owner each time; cached telemetry can outlive
        # the move, a KO or an arena change. Older policy installs omit this
        # helper, so verify its known entry before making an optional call.
        import cinematic_policy as cinematic
        a.li(8,cinematic.CONTROL);a.lw(9,8);a.li(11,cinematic.MAGIC);a.branch(5,9,11,'ordinary_split')
        a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'ordinary_split')
        a.lw(9,8,8);a.branch(5,9,10,'ordinary_split')
        if shared_form and form_fallback:
            # The two preferences are independent. An enabled ultimate option
            # with no active ultimate must not mask a live transformation.
            a.lw(9,8,20);a.addiu(11,0,1);a.branch(5,9,11,'check_ultimate')
            a.lw(9,8,cinematic.TRANSFORM_VIEW);a.branch(5,9,11,'check_ultimate')
            a.li(8,cinematic.SHARED_FORM)
            for offset,word in enumerate(struct.unpack('<2I',cinematic.shared_form_owner()[:8])):
                a.lw(9,8,offset*4);a.li(11,word);a.branch(5,9,11,'check_ultimate')
            a.call(cinematic.SHARED_FORM);a.branch(5,2,0,'no')
            a.label('check_ultimate');a.li(8,cinematic.CONTROL)
            a.lw(9,8,16);a.addiu(11,0,1);a.branch(5,9,11,'ordinary_split')
        elif shared_form:
            # A checked transformation can own the same one full-screen view.
            a.lw(9,8,16);a.addiu(11,0,1);a.branch(4,9,11,'shared_ultimate')
            a.lw(9,8,20);a.branch(5,9,11,'ordinary_split')
            a.lw(9,8,cinematic.TRANSFORM_VIEW);a.branch(5,9,11,'ordinary_split')
            a.li(8,cinematic.SHARED_FORM)
            for offset,word in enumerate(struct.unpack('<2I',cinematic.shared_form_owner()[:8])):
                a.lw(9,8,offset*4);a.li(11,word);a.branch(5,9,11,'ordinary_split')
            a.call(cinematic.SHARED_FORM);a.branch(5,2,0,'no')
            a.jump('ordinary_split')
            a.label('shared_ultimate')
        else:
            a.lw(9,8,16);a.addiu(11,0,1);a.branch(5,9,11,'ordinary_split')
        a.li(8,cinematic.ULTIMATE_OWNER)
        for offset,word in enumerate(struct.unpack('<2I',cinematic.ultimate_owner()[:8])):
            a.lw(9,8,offset*4);a.li(11,word);a.branch(5,9,11,'ordinary_split')
        a.call(cinematic.ULTIMATE_OWNER);a.branch(5,2,0,'no')
        a.label('ordinary_split')
    if shared_rush:
        import rush_cinematics as rush
        rush.emit_hud_gate(a,'no')
    # Co-op deliberately merges the two humans' fused body into one full view.
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(11,modes.MAGIC);a.branch(5,9,11,'yes')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'yes')
    a.lw(9,8,12);a.addiu(11,0,modes.COOP);a.branch(5,9,11,'yes')
    if quad_support:a.lw(9,8,16);a.i(11,11,9,3);a.branch(4,11,0,'yes')
    a.lw(9,8,24);a.r(0x2B,9,9,10);a.branch(5,9,0,'no')
    a.label('yes');a.addiu(2,0,1);a.jump('return')
    a.label('no');a.move(2,0)
    a.label('return');restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<=DRAW-ACTIVE;return data


# Optional per-view HUD extensions (beta.37), drawn in every view right after the revival text. Each listed
# module's hud_extension(ram) returns (control, magic, draw) while its caption is installed, else None. With none
# installed the wrapper and the quad pass are byte-identical to the previous release.
HUD_EXTENSION_MODULES=('beam_struggle',)


def hud_extensions(ram,installing=None):
    """Installed per-view HUD extensions in list order; installing={module: entry} adds one being installed."""
    import importlib
    found=[]
    for name in HUD_EXTENSION_MODULES:
        entry=(installing or {}).get(name) or importlib.import_module(name).hud_extension(ram)
        if entry:found.append(tuple(entry))
    return tuple(found)


def extension_calls(a,extensions,tag):
    for k,(control,magic,draw) in enumerate(extensions):
        a.li(8,control);a.lw(9,8);a.li(10,magic);a.branch(5,9,10,f'{tag}{k}')
        a.call(draw);a.label(f'{tag}{k}')


def wrapper(previous,legacy=False,revival=True,deferred=False,extensions=()):
    a=Assembler(CODE);save(a);a.call(previous);a.i(63,2,29,0x100);a.i(63,3,29,0x108)
    a.r(16,8,0);a.i(63,8,29,0xE0);a.r(18,8,0);a.i(63,8,29,0xE8)
    if not deferred:a.call(DRAW)
    if not legacy:
        # Optional assistance is independent of the battle-HUD visibility option.
        import spectator_feedback as feedback
        a.li(8,feedback.CONTROL);a.lw(9,8);a.li(10,feedback.MAGIC);a.branch(5,9,10,'no_feedback')
        a.call(feedback.DRAW);a.label('no_feedback')
    if revival and not legacy:
        import teammate_revive as revive
        a.li(8,revive.CONTROL);a.lw(9,8);a.li(10,revive.MAGIC);a.branch(5,9,10,'no_revive')
        a.call(revive.DRAW);a.label('no_revive')
        extension_calls(a,extensions,'no_extension')
    a.i(55,2,29,0x100);a.i(55,3,29,0x108);restore(a,skip=(2,3));a.jr();return a.finish()


def number():
    """a0 unsigned value, a1 buffer -> v0 address of terminator, bounded six digits."""
    a=Assembler(NUMBER);a.li(8,999999);a.r(0x2B,9,8,4);a.branch(4,9,0,'bounded');a.move(4,8)
    a.label('bounded');a.move(2,5);a.move(11,0)
    for divisor in (100000,10000,1000,100,10,1):
        a.li(8,divisor);a.r(27,0,4,8);a.r(18,9,0);a.r(16,4,0)
        if divisor!=1:
            a.r(0x25,10,11,9);a.branch(4,10,0,f'next{divisor}')
        a.addiu(11,0,1);a.addiu(9,9,48);a.i(40,9,2,0);a.addiu(2,2,1)
        a.label(f'next{divisor}')
    a.i(40,0,2,0);a.jr();return a.finish()


def text(a,buffer,x,y,color):
    a.move(4,buffer);a.addiu(5,x,1792);a.r(0,5,0,5,4);a.addiu(6,y,Y_ORIGIN);a.r(0,6,0,6,4)
    a.li(7,color)
    for i,r in enumerate((24,25,26,27)):a.i(63,r,29,0x100+8*i)
    a.call(feed.TEXT)
    for i,r in enumerate((24,25,26,27)):a.i(55,r,29,0x100+8*i)


def rectangle(a,x,y,width,height,color):
    a.addiu(4,x,1792);a.r(0,4,0,4,4);a.addiu(5,y,Y_ORIGIN);a.r(0,5,0,5,4)
    a.r(0x2D,6,x,width);a.addiu(6,6,1792);a.r(0,6,0,6,4)
    a.addiu(7,y,Y_ORIGIN+height);a.r(0,7,0,7,4);a.li(8,color)
    for i,r in enumerate((24,25,26,27)):a.i(63,r,29,0x100+8*i)
    a.call(bars.RECT)
    for i,r in enumerate((24,25,26,27)):a.i(55,r,29,0x100+8*i)


# Samples from original USA HUD atlas8, palette variants3/4/1/5,
# pixel(50,9). Native21C5B0 uses10000HP layers;21F718 uses20000ki units.
HP_COLORS=(0x802D89D9,0x802DD9D3,0x8034D92E,0x80D97D2D)


def _hp_color(a,layer,out,tag):
    a.i(11,8,layer,7);a.branch(4,8,0,tag+'blue')
    a.i(11,8,layer,2);a.branch(4,8,0,tag+'green')
    a.branch(5,layer,0,tag+'yellow');a.li(out,HP_COLORS[0]);a.jump(tag+'ready')
    for label,color in (('yellow',HP_COLORS[1]),('green',HP_COLORS[2]),('blue',HP_COLORS[3])):
        a.label(tag+label);a.li(out,color);a.jump(tag+'ready')
    a.label(tag+'ready')


def _styled_fill(a,height,color=None):
    # Inward-facing gauges: own fighter drains to the left, target to the right.
    # r22 is a dynamic color only when color is None; r20 is the panel role.
    tag=f'fill_{a.pc:08X}'
    a.branch(4,20,0,tag);a.addiu(8,19,-8);a.r(0x23,8,8,25);a.r(0x21,23,23,8)
    a.label(tag)
    if color is not None:
        rectangle(a,23,24,25,height,color)
    else:
        a.addiu(4,23,1792);a.r(0,4,0,4,4);a.addiu(5,24,Y_ORIGIN);a.r(0,5,0,5,4)
        a.r(0x21,6,23,25);a.addiu(6,6,1792);a.r(0,6,0,6,4)
        a.addiu(7,24,Y_ORIGIN+height);a.r(0,7,0,7,4);a.move(8,22)
        for i,r in enumerate((24,25,26,27)):a.i(63,r,29,0x100+8*i)
        a.call(bars.RECT)
        for i,r in enumerate((24,25,26,27)):a.i(55,r,29,0x100+8*i)
    a.addiu(23,17,4)


def panel(legacy=False,styled=True,native=False,base=PANEL,repaired=False):
    """a0 physical, a1 x, a2 y, a3 width, t0 role (0 own /1 target)."""
    if native and not legacy:
        import viewport_hud_art as art
        return art.dispatch()
    styled=styled and not legacy
    a=Assembler(base);save(a);a.move(16,4);a.move(17,5);a.move(18,6);a.move(19,7)
    if styled:a.i(55,20,29,SAVED.index(8)*8) # save() uses t0 for HI/LO
    else:a.move(20,8)
    a.call(spectator.LOOKUP);a.branch(4,3,0,'done')
    a.li(8,core.POINTERS);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(4,8);a.call(feed.ROW)
    a.branch(4,2,0,'done');a.move(21,2);a.move(22,3)
    rectangle(a,17,18,19,57 if legacy else 64,0x380C0804 if styled else 0x70140E08)
    # Character name is copied into a bounded local line fitting the panel.
    a.i(11,8,22,161);a.branch(4,8,0,'unknown_name')
    a.r(0,8,0,22,7);a.li(9,feed.NAMES);a.r(0x2D,8,8,9);a.jump('name_ready')
    a.label('unknown_name');a.li(8,feed.UNKNOWN)
    a.label('name_ready');a.addiu(9,29,0x140);a.move(10,0)
    a.addiu(11,19,-8);a.addiu(12,0,6);a.r(27,0,11,12);a.r(18,11,0)
    a.i(11,12,11,19);a.branch(5,12,0,'name_size');a.addiu(11,0,18)
    a.label('name_size');a.i(36,12,8,0);a.branch(4,12,0,'name_end')
    a.i(40,12,9,0);a.addiu(8,8,1);a.addiu(9,9,1);a.addiu(10,10,1);a.branch(5,10,11,'name_size')
    a.label('name_end');a.i(40,0,9,0);a.addiu(23,17,4);a.addiu(24,18,4);a.addiu(25,29,0x140)
    text(a,25,23,24,0x80F0F0F0)
    for index,(label,offset,color) in enumerate((('HP ',0,0x8080E090),('KI ',12,0x8050CFFF),('STOCKS ',20,0x80F0D090))):
        prefix=label.encode();a.addiu(25,29,0x140)
        for k,ch in enumerate(prefix):a.addiu(8,0,ch);a.i(40,8,25,k)
        a.lw(26,21,offset);a.lw(27,21,offset+4)
        # Corrupt / negative scalars cannot create huge loops or packets.
        a.branch(7,27,0,f'max{index}');a.addiu(27,0,1);a.label(f'max{index}');a.li(8,0x1000000);a.r(0x2B,9,8,27);a.branch(4,9,0,f'max_bounded{index}');a.move(27,8);a.label(f'max_bounded{index}')
        a.branch(1,26,0,f'zero{index}');a.r(0x2B,8,27,26);a.branch(4,8,0,f'value{index}')
        a.move(26,27);a.jump(f'value{index}');a.label(f'zero{index}');a.move(26,0)
        a.label(f'value{index}')
        if index==2:
            if legacy:
                a.li(8,100000);a.r(27,0,26,8);a.r(18,26,0);a.r(27,0,27,8);a.r(18,27,0)
            else:
                # One stock is 100000 native units; retain the remainder for the
                # visible charging gauge instead of discarding it at integer divide.
                a.li(8,100000);a.r(27,0,26,8);a.r(16,9,0)
                a.branch(5,26,27,'stock_fraction');a.move(9,8)
                a.label('stock_fraction');a.sw(9,29,0x120)
                a.r(18,26,0);a.r(27,0,27,8);a.r(18,27,0)
        a.move(4,26);a.addiu(5,25,len(prefix));a.call(NUMBER)
        a.addiu(8,0,47);a.i(40,8,2,0);a.addiu(5,2,1);a.move(4,27);a.call(NUMBER)
        a.addiu(24,18,14 if index==0 else 31 if index==1 else 48)
        text(a,25,23,24,color)
        if index<2:
            # Scale without multiplication overflow: divide native units by
            # max first through a 64-bit product whose upper half is bounded.
            a.addiu(25,19,-8);a.addiu(24,18,23 if index==0 else 40)
            if styled:
                a.addiu(23,23,-1);a.addiu(24,24,-1);a.addiu(25,25,2)
                rectangle(a,23,24,25,7 if index==0 else 6,0x80AFAFAF)
                a.addiu(23,23,1);a.addiu(24,24,1);a.addiu(25,25,-2)
            rectangle(a,23,24,25,5 if styled and index==0 else 4,0x80504438)
            if styled and index==0:
                a.branch(4,26,0,'bar_done0');a.li(8,10000);a.r(27,0,26,8)
                a.r(16,26,0);a.r(18,27,0)
                a.branch(5,26,0,'hp_layer_ready');a.addiu(27,27,-1);a.li(26,10000)
                a.label('hp_layer_ready');a.sw(27,29,0x124)
                if not repaired:
                    a.branch(4,27,0,'hp_base_ready');a.addiu(27,27,-1)
                    _hp_color(a,27,22,'under_');_styled_fill(a,5)
                a.label('hp_base_ready');a.lw(27,29,0x124)
                _hp_color(a,27,22,'front_');a.li(27,10000)
            a.r(25,0,26,25);a.r(18,8,0);a.r(27,0,8,27);a.r(18,25,0)
            if styled and index==0:
                # Stock21C670 keeps critical positive HP visible. Scale its
                # three-pixel sliver down to two within these smaller panels.
                a.i(11,8,25,2);a.branch(4,8,0,'hp_sliver_ready');a.addiu(25,0,2)
                a.label('hp_sliver_ready')
            a.branch(4,25,0,f'bar_done{index}')
            if styled:_styled_fill(a,5 if index==0 else 4,None if index==0 else color)
            else:rectangle(a,23,24,25,4,color)
            a.label(f'bar_done{index}')
            if styled and index==1:
                # Five native ki bands, bounded inside the viewport at all sizes.
                for tick in range(1,5):
                    a.addiu(25,19,-8);a.addiu(8,0,tick);a.r(25,0,25,8);a.r(18,25,0)
                    a.addiu(8,0,5);a.r(27,0,25,8);a.r(18,25,0)
                    a.r(0x21,23,23,25);a.addiu(25,0,1)
                    rectangle(a,23,24,25,4,0x80302A24);a.addiu(23,17,4)
        elif not legacy:
            a.addiu(25,19,-8);a.addiu(24,18,58)
            rectangle(a,23,24,25,3,0x80504438)
            a.lw(26,29,0x120);a.li(27,100000)
            a.r(25,0,26,25);a.r(18,8,0);a.r(27,0,8,27);a.r(18,25,0)
            a.branch(4,25,0,'stock_bar_done')
            if styled:_styled_fill(a,3,color)
            else:rectangle(a,23,24,25,3,color)
            a.label('stock_bar_done')
    a.label('done');restore(a);a.jr();data=a.finish();assert len(data)<NUMBER-PANEL;return data


def draw():
    import display_settings as display
    a=Assembler(DRAW);save(a);a.call(ACTIVE);a.branch(4,2,0,'done')
    a.li(8,display.CONTROL);a.lw(9,8);a.li(10,display.MAGIC);a.branch(5,9,10,'display_ready')
    a.lw(9,8,display.FIELDS['hud']);a.branch(4,9,0,'done')
    a.label('display_ready');a.lw(16,28,-22176);spectator.pointer(a,16,832,'done')
    a.li(17,VIEWS);a.li(8,CONTROL);a.lw(18,8,12);a.move(19,0)
    a.label('view');a.lw(8,17);a.branch(4,8,0,'next')
    for native,descriptor in ((512,4),(516,8),(520,12),(524,16)):
        a.lw(8,16,native);a.lw(9,17,descriptor);a.branch(5,8,9,'next')
    a.lw(14,17,20);spectator.pointer(a,14,4,'done');a.lw(20,14)
    a.lw(21,17,4);a.lw(22,17,12);a.addiu(21,21,4);a.addiu(22,22,5)
    a.lw(23,17,8);a.lw(8,17,4);a.r(0x23,23,23,8);a.addiu(23,23,-11);a.r(2,23,0,23,1)
    a.move(4,20);a.move(5,21);a.move(6,22);a.move(7,23);a.move(8,0);a.call(PANEL)
    a.li(8,core.MODE);a.lw(8,8,4);a.r(0x2B,9,20,8);a.branch(4,9,0,'done')
    a.li(8,core.TABLE);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(4,8);a.branch(4,4,20,'done')
    a.r(0x2D,21,21,23);a.addiu(21,21,4);a.move(5,21);a.move(6,22);a.move(7,23);a.addiu(8,0,1);a.call(PANEL)
    a.li(8,CONTROL);a.lw(9,8,20);a.addiu(9,9,1);a.sw(9,8,20);a.jump('done')
    a.label('next');a.addiu(17,17,VIEW_STRIDE);a.addiu(19,19,1);a.branch(5,19,18,'view')
    a.label('done');restore(a);a.jr();data=a.finish();assert len(data)<PANEL-DRAW;return data


def scissor_code():
    """a0..a3 inclusive pixel bounds. Independent final-HUD GS scissor packet."""
    a=Assembler(SCISSOR);save(a)
    for dest,src in ((16,4),(17,5),(18,6),(19,7)):a.move(dest,src)
    a.call(A(0x100878));a.move(20,2)
    for off,value in ((0,1),(4,0x10000000),(8,14),(12,0),(24,0x40),(28,0)):
        a.li(8,value);a.sw(8,20,off)
    a.r(0,8,0,17,16);a.r(0x25,8,8,16);a.sw(8,20,16)
    a.r(0,8,0,19,16);a.r(0x25,8,8,18);a.sw(8,20,20)
    a.addiu(4,20,32);a.call(A(0x100890));restore(a);a.jr();return a.finish()


def post_code(sizing=True,placement=True,inset=True,outward=True,pair_offset=8,quad_support=False,lockoff=False):
    """All panels after both world passes; never upload art between cameras."""
    import display_settings as display
    import viewport_hud_art as art
    a=Assembler(POST);save(a);a.call(ACTIVE);a.branch(4,2,0,'done')
    a.li(8,display.CONTROL);a.lw(9,8,display.FIELDS['hud']);a.branch(4,9,0,'done')
    # The final native traversal may visit its status root twice. Once per
    # native HUD render scope, not per simulation tick (pause still renders).
    a.li(8,CONTROL);a.lw(9,8,24);a.branch(5,9,0,'done');a.addiu(9,0,1);a.sw(9,8,24)
    # World rendering may have borrowed HUD VRAM. Invalidate our bundle once,
    # then reuse its resident atlases only within this final overlay phase.
    a.lw(8,28,-0x5728);art.pointer(a,8,32,'no_bundle');a.lw(8,8)
    art.pointer(a,8,32,'no_bundle');a.lw(9,8);a.i(11,10,9,65);a.branch(4,10,0,'no_bundle')
    a.lw(8,8,16);art.pointer(a,8,4096,'no_bundle');a.branch(4,9,0,'no_bundle')
    a.label('invalidate');a.sw(0,8,40);a.addiu(8,8,64);a.addiu(9,9,-1);a.branch(5,9,0,'invalidate')
    a.label('no_bundle');a.move(24,0)
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(10,modes.MAGIC);a.branch(5,9,10,'layout_ready')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'layout_ready')
    if quad_support:
        import quad_lifecycle as seats
        a.lw(9,8,12);a.addiu(10,0,modes.FFA);a.branch(4,9,10,'layout_ready')
        a.li(10,seats.CONTROL+seats.F['owned']);a.lw(11,10);a.i(12,11,11,1)
        for seat in range(1,4):
            a.lw(9,10,seat*4);a.addiu(12,0,-1);a.branch(4,9,12,f'layout_seat{seat}')
            a.i(12,9,9,1);a.branch(5,9,11,'layout_ready');a.label(f'layout_seat{seat}')
    else:a.lw(9,8,12);a.addiu(10,0,modes.COOP);a.branch(5,9,10,'layout_ready')
    a.li(8,art.SETTINGS);a.lw(9,8,12);a.branch(5,9,0,'layout_ready');a.addiu(24,0,1)
    a.label('layout_ready');a.li(17,VIEWS);a.li(8,CONTROL);a.lw(18,8,12);a.move(19,0)
    a.label('view');a.lw(8,17);a.branch(4,8,0,'next')
    a.lw(14,17,20);spectator.pointer(a,14,4,'next');a.lw(20,14)
    for r,off in ((4,4),(5,8),(6,12),(7,16)):a.lw(r,17,off)
    a.call(SCISSOR)
    a.lw(21,17,4);a.lw(22,17,12);a.addiu(21,21,4);a.addiu(22,22,5)
    a.lw(23,17,8);a.lw(8,17,4);a.r(0x23,23,23,8);a.addiu(23,23,-11);a.r(2,23,0,23,1)
    a.branch(4,24,0,'own')
    # One larger player status per co-op half; odd columns face right.
    a.lw(23,17,8);a.lw(8,17,4);a.r(0x23,23,23,8);a.addiu(23,23,-8)
    a.i(12,8,19,1);a.jump('draw_own')
    a.label('own')
    if sizing and placement:
        # Preserve one row with a small inset toward each viewport's center.
        # Native-size top/bottom instead uses the full view width. Compact
        # text panels retain their fixed64px height and don't scale their font.
        a.li(8,art.SETTINGS);a.lw(27,8,28);a.addiu(9,0,1)
        a.branch(4,27,9,'full_width')
        a.move(27,0);a.lw(9,8);a.branch(4,9,0,'fit_top')
        a.lw(9,8,20);a.i(11,10,9,80);a.branch(5,10,0,'scale_default')
        a.i(11,10,9,141);a.branch(5,10,0,'scale_valid')
        a.label('scale_default');a.addiu(9,0,100 if inset else 95)
        a.label('scale_valid');a.r(25,0,23,9);a.r(18,23,0)
        a.addiu(9,0,100);a.r(27,0,23,9);a.r(18,23,0)
        a.label('fit_top');a.lw(9,17,8);a.lw(10,17,4);a.r(0x23,9,9,10)
        a.addiu(9,9,(-14 if pair_offset>3 and outward else -12) if inset else -6);a.r(2,9,0,9,1)
        if quad_support:
            # Widescreen narrows the artwork to 3/4 width. Let the size option
            # use that room, capped for one4px outer and26px inner inset.
            import widescreen_support as wide
            a.move(11,9);a.li(8,CONTROL);a.lw(8,8,12);a.i(11,10,8,3);a.branch(4,10,0,'quad_limit')
            # Keep the previous two-view scale. Atlas6 has transparent side
            # padding; use that padding for timer clearance instead of shrinking
            # the whole panel and quantizing every gauge at a different size.
            a.jump('quad_limit_ready')
            a.label('quad_limit')
            a.li(8,art.SETTINGS);a.lw(8,8);a.branch(4,8,0,'quad_limit_ready')
            a.move(10,0);wide.emit_detection(a,10,'quad_limit_ready');a.addiu(11,0,148)
            a.label('quad_limit_ready');a.move(9,11)
        a.r(0x2B,10,9,23)
        a.branch(4,10,0,'placement_ready');a.move(23,9);a.jump('placement_ready')
        a.label('full_width');a.lw(23,17,8);a.lw(9,17,4);a.r(0x23,23,23,9)
        a.addiu(23,23,-2);a.addiu(9,0,256);a.r(0x2B,10,9,23)
        a.branch(4,10,0,'placement_ready');a.move(23,9)
        a.label('placement_ready')
        if inset:
            a.addiu(25,0,1);a.branch(5,27,0,'inset_ready');a.addiu(25,0,4)
            if quad_support:
                # Inset both frames toward the middle of their own viewport.
                # Anamorphic art occupies only 3/4 of its logical width, so
                # its extra margin also keeps stocks clear of the stock timer.
                # Keep original Y and scale; 4:3 gets the safe 7px inset.
                import widescreen_support as wide
                a.li(8,CONTROL);a.lw(9,8,12);a.i(11,9,9,3);a.branch(4,9,0,'quad_inset')
                a.addiu(25,0,1);a.jump('inset_ready');a.label('quad_inset')
                a.li(8,art.SETTINGS);a.lw(9,8);a.branch(4,9,0,'inset_ready')
                a.addiu(25,0,7);a.move(10,0);wide.emit_detection(a,10,'inset_ready')
                a.addiu(25,0,4)
            a.label('inset_ready');a.lw(21,17,4);a.r(0x21,21,21,25)
        else:a.lw(21,17,4);a.addiu(21,21,1)
        a.lw(22,17,12);a.addiu(22,22,2);a.i(12,26,19,1)
        a.branch(4,26,0,'left_own');a.lw(21,17,8)
        if inset:a.r(0x23,21,21,25)
        else:a.addiu(21,21,-1)
        a.r(0x23,21,21,23)
        a.label('left_own')
        if outward and inset:
            if quad_support:
                a.jump('own_shifted')
            a.branch(5,27,0,'own_shifted');a.addiu(9,0,-min(3,pair_offset));a.branch(4,26,0,'own_shift');a.addiu(9,0,min(3,pair_offset))
            a.label('own_shift');a.r(0x21,21,21,9);a.label('own_shifted')
        a.move(8,26)
    elif sizing:
        # The enlarged own/target panels cannot fit side by side inside a
        # half-width view. Keep corner anchors and stagger the target below;
        # the existing100% layout and two-player-only co-op layout stay intact.
        a.move(25,0);a.li(8,art.SETTINGS);a.lw(9,8);a.branch(4,9,0,'scaled_ready')
        a.lw(9,8,20);a.i(11,10,9,80);a.branch(5,10,0,'scale_default')
        a.i(11,10,9,141);a.branch(5,10,0,'scale_valid')
        a.label('scale_default');a.addiu(9,0,120)
        a.label('scale_valid');a.move(25,9)
        a.r(25,0,23,9);a.r(18,23,0);a.addiu(9,0,100);a.r(27,0,23,9);a.r(18,23,0)
        a.i(11,10,25,101);a.move(25,0);a.branch(5,10,0,'scaled_ready')
        a.addiu(25,23,3);a.r(2,25,0,25,2);a.addiu(25,25,3)
        a.label('scaled_ready')
    if not(sizing and placement):a.move(8,0)
    a.label('draw_own');a.move(4,20);a.move(5,21);a.move(6,22);a.move(7,23);a.call(PANEL)
    a.branch(5,24,0,'next')
    if lockoff:
        import lockoff_target
        a.move(4,20);a.call(lockoff_target.HIDE_HUD);a.branch(5,2,0,'next')
    a.li(8,core.MODE);a.lw(8,8,4);a.r(0x2B,9,20,8);a.branch(4,9,0,'next')
    a.li(8,core.TABLE);a.r(0,9,0,20,2);a.r(0x21,8,8,9);a.lw(4,8);a.branch(4,4,20,'next')
    if sizing and placement:
        if outward and inset:
            a.branch(4,27,0,'target_scaled');a.addiu(8,0,85);a.r(25,0,23,8);a.r(18,23,0)
            a.addiu(8,0,100);a.r(27,0,23,8);a.r(18,23,0);a.label('target_scaled')
        if quad_support:
            # Only the inner top-row status needs extra timer clearance.
            # Bottom cameras and the outer top status keep their edge anchors.
            a.branch(5,27,0,'target_inset_ready')
            a.li(8,CONTROL);a.lw(9,8,12);a.i(11,9,9,3);a.branch(4,9,0,'quad_target_inset')
            a.addiu(25,0,22);a.jump('target_inset_ready');a.label('quad_target_inset')
            a.li(8,art.SETTINGS);a.lw(9,8);a.branch(4,9,0,'target_inset_ready')
            a.lw(9,17,12);a.branch(5,9,0,'target_inset_ready')
            a.move(10,0);wide.emit_detection(a,10,'target_inset_ready');a.addiu(25,0,26)
            a.label('target_inset_ready')
        a.branch(5,26,0,'left_target');a.lw(21,17,8)
        if inset:a.r(0x23,21,21,25)
        else:a.addiu(21,21,-1)
        a.r(0x23,21,21,23);a.jump('target_x_ready')
        a.label('left_target');a.lw(21,17,4)
        if inset:a.r(0x21,21,21,25)
        else:a.addiu(21,21,1)
        a.label('target_x_ready');a.branch(4,27,0,'target_y_ready')
        a.r(2,25,0,23,2);a.li(8,art.SETTINGS);a.lw(9,8)
        a.branch(5,9,0,'target_height_ready');a.addiu(25,0,64)
        a.label('target_height_ready');a.lw(22,17,16);a.addiu(22,22,-2);a.r(0x23,22,22,25)
        a.label('target_y_ready')
        if outward and inset:
            if quad_support:
                a.jump('target_shifted')
            a.branch(5,27,0,'target_shifted');a.addiu(9,0,-pair_offset);a.branch(4,26,0,'target_shift');a.addiu(9,0,pair_offset)
            a.label('target_shift');a.r(0x21,21,21,9);a.label('target_shifted')
        a.i(14,8,26,1)
    elif sizing:
        a.lw(21,17,8);a.addiu(21,21,-4);a.r(0x23,21,21,23);a.r(0x21,22,22,25)
    else:a.r(0x21,21,21,23);a.addiu(21,21,4)
    a.move(5,21);a.move(6,22);a.move(7,23)
    if not(sizing and placement):a.addiu(8,0,1)
    a.call(PANEL)
    a.label('next');a.addiu(17,17,VIEW_STRIDE);a.addiu(19,19,1);a.branch(5,19,18,'view')
    a.move(4,0);a.addiu(5,0,511);a.move(6,0);a.addiu(7,0,SCISSOR_Y1);a.call(SCISSOR)
    a.li(8,CONTROL);a.lw(9,8,20);a.addiu(9,9,1);a.sw(9,8,20)
    a.label('done');restore(a);a.jr();data=a.finish();assert len(data)<PANEL-POST;return data


def pieces(previous,legacy=False,styled=True,revival=True,native=True,repaired=True,layers=True,sizing=True,shared_ultimate=True,placement=True,inset=True,outward=True,safe_edges=True,shared_form=True,isolated=True,pair_offset=8,form_fallback=True,extensions=()):
    import viewport_hud_art as art
    native=native and styled and revival and not legacy
    shared=shared_ultimate and native and repaired and layers and sizing
    result=[(CODE,wrapper(previous,legacy,revival,deferred=native and repaired,extensions=extensions)),(ACTIVE,active(shared,shared_form and shared,form_fallback)),(DRAW,draw()),
            (PANEL,panel(legacy,styled,native)),(NUMBER,number())]
    if native:
        if not repaired:
            import viewport_hud_art_v1
            return result+viewport_hud_art_v1.pieces()
        if not layers:
            import viewport_hud_art_v2
            return result+viewport_hud_art_v2.pieces()+[(POST,post_code(False)),(SCISSOR,scissor_code())]
        if not sizing:
            import viewport_hud_art_v3
            return result+viewport_hud_art_v3.pieces()+[(POST,post_code(False)),(SCISSOR,scissor_code())]
        return result+art.pieces(safe_edges,isolated)+[(POST,post_code(placement=placement and shared_ultimate,inset=inset,outward=outward,pair_offset=pair_offset)),(SCISSOR,scissor_code())]
    return result


def build_memory(ram,source='<prepared>',views=DEFAULT_VIEWS,settings=None):
    import viewport_hud_art as art
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if len(ram)!=0x8000000:raise ValueError('Viewport HUD requires captured 128 MiB RAM')
    if not 2<=len(views)<=MAX_VIEWS:raise ValueError('Viewport HUD requires 2 to 4 viewport descriptors')
    for enabled,x0,x1,y0,y1,subject in views:
        if enabled not in (0,1) or not 0<=x0<x1<512 or not 0<=y0<y1<DISPLAY_H or x1-x0<230:
            raise ValueError('Invalid native HUD viewport rectangle')
        if not 0x100000<=subject<len(ram)-4 or subject&3:raise ValueError('Invalid viewport subject pointer')
    manager=u(core.ACTORS)
    old=feed.world_code();needle=struct.pack('<I',(3<<26)|(feed.DRAW>>2))
    offsets=[n for n in range(0,len(old),4) if old[n:n+4]==needle]
    if len(offsets)!=1:raise ValueError('Unknown world HUD chain')
    hook=feed.WORLD+offsets[0]
    if u(CONTROL)==MAGIC:
        previous=u(CONTROL+16)
        import coop_fusion
        if previous not in (feed.DRAW,coop_fusion.DRAW):raise ValueError('Unknown saved viewport render owner')
        if (u(CONTROL+4),u(CONTROL+8),u(CONTROL+12))!=(manager,1,len(views)):
            raise ValueError('Viewport HUD capture or descriptor count changed')
        expected=bytearray(old);struct.pack_into('<I',expected,offsets[0],(3<<26)|(CODE>>2))
        # Timed fusion draws its meter after this complete viewport wrapper.
        # Authenticate that outer service and preserve its exact continuation
        # when validating or changing existing viewport preferences.
        import fusion_duration
        before=bytes(expected[offsets[0]:offsets[0]+4])
        after=fusion_duration.dependency_override(ram,hook,before)
        if after!=before:
            fusion_duration.validate_memory(ram)
            expected[offsets[0]:offsets[0]+4]=after
        if ram[feed.WORLD:feed.WORLD+len(expected)]!=expected:raise ValueError('Viewport HUD render chain changed')
        descriptor_bytes=b''.join(struct.pack('<6I',*v) for v in views)
        if ram[VIEWS:VIEWS+len(descriptor_bytes)]!=descriptor_bytes:raise ValueError('Viewport HUD descriptors changed')
        import four_player_mode
        current=[(p,four_player_mode.dependency_override(ram,p,b)) for p,b in pieces(previous,extensions=hud_extensions(ram))]
        import lockoff_target
        current=[(p,lockoff_target.dependency_override(ram,p,b)) for p,b in current]
        if all(ram[p:p+len(d)]==d for p,d in current):
            if u(CONTROL+28)!=POST_MAGIC:raise ValueError('Viewport HUD final phase marker changed')
            if any(u(art.SETTINGS+4*i)not in(0,1)for i in range(4)) or u(art.SETTINGS+16)>90:
                raise ValueError('Invalid native viewport HUD options')
            if not 80<=u(art.SETTINGS+20)<=140 or u(art.SETTINGS+24) not in(0,1):
                raise ValueError('Invalid native viewport HUD scale/filter options')
            if u(art.SETTINGS+28)not in(0,1):raise ValueError('Invalid native viewport HUD placement option')
            # Dependency validation must preserve a previously chosen compact
            # style or disabled effect. Only explicit new settings change them.
            blocks=[]
            if settings is not None:
                data=art.settings_data(settings)
                if ram[art.SETTINGS:art.SETTINGS+len(data)]!=data:
                    blocks.append(dict(address=art.SETTINGS,expected_hex=ram[art.SETTINGS:art.SETTINGS+len(data)].hex(),data_hex=data.hex()))
            return dict(blocks=blocks,source=str(source))
        # Final-phase v2 differs only in the native panel. Keep the verified
        # rendering isolation, settings, live meter records and counters intact.
        # The shared-transformation panel rule is orthogonal to every earlier
        # final-phase difference, so each of them has both emissions.
        variants=(dict(),dict(outward=False),dict(inset=False),dict(placement=False),dict(shared_ultimate=False),
                  dict(safe_edges=False),dict(outward=False,safe_edges=False),dict(inset=False,safe_edges=False),
                  dict(placement=False,safe_edges=False),dict(shared_ultimate=False,safe_edges=False),
                  dict(sizing=False),dict(layers=False))
        for former in (pieces(previous,shared_form=shared_form,isolated=isolated,pair_offset=pair_offset,form_fallback=fallback,**variant)
                       for variant in variants for shared_form in (False,True)
                       for fallback in (False,True)
                       for isolated,pair_offset in ((True,8),(False,3))):
            if not all(ram[p:p+len(d)]==d for p,d in former):continue
            if u(CONTROL+28)!=POST_MAGIC:raise ValueError('Viewport HUD final phase marker changed')
            if any(u(art.SETTINGS+4*i)not in(0,1)for i in range(4)) or u(art.SETTINGS+16)>90:
                raise ValueError('Invalid native viewport HUD options')
            old_sizes={p:len(d)for p,d in former}
            for p,d in current:
                if any(ram[p+old_sizes.get(p,0):p+len(d)]):raise ValueError('Viewport HUD extension occupied')
            art.native_guards(ram)
            extension=bytes(ram[art.SETTINGS+20:art.SETTINGS+28])
            if any(extension) and not(80<=u(art.SETTINGS+20)<=140 and u(art.SETTINGS+24)in(0,1)):
                raise ValueError('Viewport HUD scale/filter settings extension occupied')
            placement_option=bytes(ram[art.SETTINGS+28:art.SETTINGS+32])
            if u(art.SETTINGS+28)not in(0,1):raise ValueError('Viewport HUD placement settings extension occupied')
            options=(art.settings_data(settings) if settings is not None else
                     bytes(ram[art.SETTINGS:art.SETTINGS+20])+
                     (extension if any(extension) else art.settings_data()[20:28])+placement_option)
            data=current+[(art.SETTINGS,options)]
            return dict(source=str(source),blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex())
                        for p,d in data if ram[p:p+len(d)]!=d])
        # Exact complete releases only, including the immediately preceding
        # styled+revival release. Additional helper reservations must be empty.
        for former in (pieces(previous,repaired=False),pieces(previous,native=False),pieces(previous,legacy=True),
                       pieces(previous,styled=False,revival=False)):
            if not all(ram[p:p+len(d)]==d for p,d in former):continue
            old_sizes={p:len(d)for p,d in former}
            for p,d in current:
                if any(ram[p+old_sizes.get(p,0):p+len(d)]):raise ValueError('Viewport HUD extension occupied')
            old_art=any(p==art.SPRITE for p,_ in former)
            if old_art:
                if any(u(art.SETTINGS+4*i)not in(0,1)for i in range(3)) or u(art.SETTINGS+12) or u(art.SETTINGS+16):
                    raise ValueError('Viewport HUD settings changed')
            elif any(ram[art.SETTINGS:art.SETTINGS+20]):raise ValueError('Viewport HUD settings occupied')
            if any(ram[art.METERS:art.METERS+art.METER_BYTES]):raise ValueError('Viewport HUD meter reservation occupied')
            art.native_guards(ram)
            options=art.settings_data(settings)
            if old_art and settings is None:options=bytes(ram[art.SETTINGS:art.SETTINGS+12])+art.settings_data()[12:]
            data=current+[(art.SETTINGS,options),(CONTROL+24,struct.pack('<2I',0,POST_MAGIC))]
            blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex())
                    for p,d in data if ram[p:p+len(d)]!=d]
            return dict(blocks=blocks,source=str(source))
        raise ValueError('Viewport HUD payload changed')
    if any(ram[CODE:END]):raise ValueError('Viewport HUD reservation occupied')
    spectator.validate_memory(ram);art.native_guards(ram)
    word=u(hook);previous=(word&0x3ffffff)<<2
    import coop_fusion
    if word>>26!=3 or previous not in(feed.DRAW,coop_fusion.DRAW):raise ValueError('Unknown viewport render owner')
    expected=bytearray(old);struct.pack_into('<I',expected,offsets[0],word)
    if ram[feed.WORLD:feed.WORLD+len(expected)]!=expected:raise ValueError('World HUD wrapper changed')
    control=bytearray(0x40);struct.pack_into('<5I',control,0,MAGIC,manager,1,len(views),previous)
    struct.pack_into('<I',control,28,POST_MAGIC)
    descriptors=b''.join(struct.pack('<6I',*v)for v in views)+bytes((MAX_VIEWS-len(views))*VIEW_STRIDE)
    data=pieces(previous)+[(art.SETTINGS,art.settings_data(settings)),(CONTROL,bytes(control)),
                          (VIEWS,descriptors),(hook,struct.pack('<I',(3<<26)|(CODE>>2)))]
    return dict(source=str(source),control=CONTROL,blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex())for p,d in data])


def dependency_override(ram,address,expected):
    """Recognise only this fully validated wrapper around a known world call."""
    old=feed.world_code();needle=struct.pack('<I',(3<<26)|(feed.DRAW>>2))
    offset=old.index(needle)
    if address!=feed.WORLD+offset:return expected
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(CONTROL)!=MAGIC:return expected
    previous=u(CONTROL+16)
    if expected!=struct.pack('<I',(3<<26)|(previous>>2)):
        raise ValueError('Viewport HUD prior render owner differs from requested dependency')
    count=u(CONTROL+12)
    if not 2<=count<=MAX_VIEWS:raise ValueError('Invalid installed viewport descriptor count')
    views=tuple(struct.unpack_from('<6I',ram,VIEWS+i*VIEW_STRIDE) for i in range(count))
    build_memory(ram,views=views)
    return struct.pack('<I',(3<<26)|(CODE>>2))
