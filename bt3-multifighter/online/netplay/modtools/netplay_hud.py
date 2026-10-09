"""Client-local status drawing, with no change to the shared native HUD publish.

The two native status roots are hidden only during live online HUD rendering.
Their updates, the timer, clash prompts and menus remain native. The existing
viewport artwork reads the displayed fighter and their actual target directly;
no client-specific subject is ever lent to a gameplay accessor or RNG caller.
"""
import struct
from prototype import Assembler
from native_map import A
import netplay_core as nc
import netplay_view as view
import viewport_hud as hud
import viewport_hud_art as art
import hud_subject as native
import display_settings as display
import fresh_team_camera as follow
import fresh_team_combat as core
from regional import SCISSOR_Y1

BASE=nc.VIEW_AREA+0x3000
SUBJECT,FILTER,RENDER,DRAW,CONTROL=BASE,BASE+0x800,BASE+0xC00,BASE+0x1000,BASE+0x1F00
END=BASE+0x2000
MAGIC=0x4E504831
assert END<=nc.VIEW_AREA_END


def subject_code():
    """Return the local camera's physical fighter, or -1 outside a live match."""
    a=Assembler(SUBJECT)
    view._gate(a,'none')
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'none')
    a.li(8,nc.CONTROL);a.lw(9,8,nc.F['magic']);a.li(10,nc.MAGIC);a.branch(5,9,10,'none')
    a.lw(9,8,nc.F['mode']);a.addiu(10,0,nc.LOCKSTEP);a.branch(5,9,10,'none')
    a.lw(9,8,nc.F['state']);a.addiu(10,0,nc.RUNNING);a.branch(5,9,10,'none')
    core.gate(a,'none')
    a.lw(8,28,view.GP_DIRECTOR);nc._valid(a,8,'none');a.lw(9,8);a.addiu(11,0,3);a.branch(5,9,11,'none')
    a.li(8,A(0x333700));a.lw(9,8);a.i(12,9,9,31);a.branch(5,9,0,'none')
    # Exactly the same subject choice as SWAP: explicit spectator side, then
    # a live extra's own camera, otherwise the followed side's successor.
    a.move(12,0);a.li(8,view.CONTROL);a.lw(9,8,view.F['watch'])
    a.i(11,11,9,2);a.branch(4,11,0,'slot');a.move(12,9);a.jump('side')
    a.label('slot');a.li(8,nc.CONTROL);a.lw(9,8,nc.F['local_slot'])
    a.i(11,11,9,2);a.branch(4,11,0,'extra');a.move(12,9);a.jump('side')
    a.label('extra');a.i(11,11,9,nc.SLOTS);a.branch(4,11,0,'side')
    a.li(8,nc.SEAT_CONTROL);a.lw(11,8,nc.SF['magic']);a.li(13,nc.SEAT_MAGIC);a.branch(5,11,13,'side')
    a.lw(11,8,nc.SF['enable']);a.branch(4,11,0,'side')
    a.r(0,11,0,9,2);a.r(0x21,8,8,11);a.lw(2,8,nc.SF['seats'])
    a.r(0x2B,11,2,10);a.branch(4,11,0,'side');a.i(12,12,2,1)
    a.li(8,view.CAM_LOGIC);a.lw(11,8);a.r(6,11,9,11);a.i(12,11,11,1)
    a.branch(5,11,0,'validate')
    a.label('side');a.li(8,follow.SUCCESSOR_CONTROL);a.r(0,9,0,12,2);a.r(0x21,8,8,9);a.lw(2,8,8)
    a.label('validate');a.r(0x2B,9,2,10);a.branch(4,9,0,'none')
    a.li(8,core.POINTERS);a.r(0,9,0,2,2);a.r(0x21,8,8,9);a.lw(8,8)
    nc._valid(a,8,'none');a.lw(9,8);a.branch(5,9,2,'none');a.jr()
    a.label('none');a.addiu(2,0,-1);a.jr()
    data=a.finish();assert len(data)<=FILTER-SUBJECT;return data


def filter_code():
    a=Assembler(FILTER);hud.save(a);a.move(16,4)
    a.li(8,native.CONTROL);a.lw(9,8,native.FIELDS['active']);a.branch(4,9,0,'native')
    a.call(SUBJECT);a.branch(1,2,0,'native')
    a.lw(8,28,-22324);nc._valid(a,8,'native')
    for off in (0,8):a.lw(9,8,off);a.branch(4,16,9,'hidden')
    a.label('native');hud.restore(a);a.jump(display.HUD_DRAW_FILTER)
    a.label('hidden');hud.restore(a);a.jr()
    data=a.finish();assert len(data)<=RENDER-FILTER;return data


def render_code():
    a=Assembler(RENDER);a.addiu(29,29,-32);a.i(63,31,29,0)
    a.call(native.RENDER_WRAP);a.i(63,2,29,8);a.i(63,3,29,16)
    a.call(DRAW)
    a.i(55,2,29,8);a.i(55,3,29,16);a.i(55,31,29,0);a.addiu(29,29,32);a.jr()
    data=a.finish();assert len(data)<=DRAW-RENDER;return data


def draw_code():
    import lockoff_target as off
    import rush_cinematics as rush
    a=Assembler(DRAW);hud.save(a);a.call(SUBJECT);a.branch(1,2,0,'done');a.move(16,2)
    a.li(8,display.CONTROL);a.lw(9,8,display.FIELDS['hud']);a.branch(4,9,0,'done')
    rush.emit_hud_gate(a,'done')
    # Final HUD pass, after world textures: same invalidation as viewport POST.
    a.lw(8,28,-0x5728);art.pointer(a,8,32,'bundle_done');a.lw(8,8)
    art.pointer(a,8,32,'bundle_done');a.lw(9,8);a.i(11,10,9,65);a.branch(4,10,0,'bundle_done')
    a.lw(8,8,16);art.pointer(a,8,4096,'bundle_done');a.branch(4,9,0,'bundle_done')
    a.label('invalidate');a.sw(0,8,40);a.addiu(8,8,64);a.addiu(9,9,-1);a.branch(5,9,0,'invalidate')
    a.label('bundle_done')
    a.move(4,0);a.addiu(5,0,511);a.move(6,0);a.addiu(7,0,SCISSOR_Y1);a.call(hud.SCISSOR)
    # Full-screen native proportions, leaving the normal central timer clear.
    a.move(4,16);a.addiu(5,0,4);a.addiu(6,0,5);a.addiu(7,0,216);a.move(8,0);a.call(hud.PANEL)
    # The shared simulation retains its old panel policy. Lend the user's
    # original lock-off policy only to this render-only visibility query.
    a.li(8,off.CONTROL);a.lw(9,8);a.li(10,off.MAGIC);a.branch(5,9,10,'target')
    a.lw(17,8,off.HUD_POLICY);a.li(9,CONTROL);a.lw(9,9,4);a.sw(9,8,off.HUD_POLICY)
    a.move(4,16);a.call(off.HIDE_HUD);a.li(8,off.CONTROL);a.sw(17,8,off.HUD_POLICY);a.branch(5,2,0,'done')
    a.label('target');a.li(8,core.TABLE);a.r(0,9,0,16,2);a.r(0x21,8,8,9);a.lw(4,8)
    a.branch(4,4,16,'done');a.li(8,core.MODE);a.lw(9,8,4);a.r(0x2B,9,4,9);a.branch(4,9,0,'done')
    a.addiu(5,0,292);a.addiu(6,0,5);a.addiu(7,0,216);a.addiu(8,0,1);a.call(hud.PANEL)
    a.label('done');hud.restore(a);a.jr()
    data=a.finish();assert len(data)<=CONTROL-DRAW;return data


def blocks(ram):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    # Old research fixtures need not carry the native viewport artwork.
    if u(hud.CONTROL)!=hud.MAGIC:return []
    if any(ram[BASE:END]):raise ValueError('Online HUD reservation is occupied')
    if u(native.RENDER_SITE)!=view.jal(native.RENDER_WRAP):raise ValueError('Online HUD render scope changed')
    if bytes(ram[display.HUD_DRAW_ENTRY:display.HUD_DRAW_ENTRY+8])!=display.jump(display.HUD_DRAW_FILTER):
        raise ValueError('Online HUD status filter changed')
    if ram[hud.PANEL:hud.PANEL+len(art.dispatch())]!=art.dispatch():raise ValueError('Online HUD artwork dispatcher changed')
    import lockoff_target as off
    policy=u(off.CONTROL+off.HUD_POLICY) if u(off.CONTROL)==off.MAGIC else 2
    return [(SUBJECT,subject_code()),(FILTER,filter_code()),(RENDER,render_code()),(DRAW,draw_code()),
            (CONTROL,struct.pack('<2I',MAGIC,policy)),
            (native.RENDER_SITE,struct.pack('<I',view.jal(RENDER))),
            (display.HUD_DRAW_ENTRY,display.jump(FILTER))]
