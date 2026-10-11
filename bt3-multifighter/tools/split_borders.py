"""Finish the native two-view separator after world effects, before the HUD.

The multiview renderer paints its own complete matte in quad_viewports. This
wrapper covers the ordinary two-player path only; it never changes a camera,
scissor layout, update clock, fade, or shared cinematic's geometry.
"""
import struct
from native_map import A
from prototype import Assembler
import battle_mode_policy as modes
import fresh_team_combat as core
import guest_healthbars as bars
import viewport_hud as hud
from regional import DISPLAY_H,SCISSOR_Y1,Y_ORIGIN

CODE,END=0x072D3C00,0x072D4000
# The unique final overlay call is +0x154 in the reviewed native draw routine
# on USA, PAL and JPN (12BB14 / 12BC34 / 12BB0C). Translate the enclosing
# function; the exact JAL+NOP below is still required before installation.
HOOK,NATIVE=A(0x12B9C0)+0x154,A(0x247688)
ORIGINAL=struct.pack('<2I',(3<<26)|(NATIVE>>2),0)


def code():
    a=Assembler(CODE)
    # Preserve the native callee's results and side effects, plus the caller's
    # actual return address. Our GS sprites do not touch simulation state.
    a.addiu(29,29,-16);a.i(63,31,29,0);a.call(NATIVE);hud.save(a)
    core.gate(a,'done')
    a.li(8,hud.CONTROL);a.lw(9,8);a.li(11,hud.MAGIC);a.branch(5,9,11,'done')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'done')
    a.lw(9,8,8);a.li(11,1);a.branch(5,9,11,'done')
    a.lw(16,28,-22176);hud.spectator.pointer(a,16,656,'done')
    # Match the actual rendered camera, not a cached human-count preference.
    # Full-screen cinematics and the short top/bottom views never qualify.
    for off,value in ((640,1),(520,0),(524,SCISSOR_Y1)):
        a.lw(9,16,off);a.li(11,value);a.branch(5,9,11,'done')
    a.lw(9,16,512);a.branch(4,9,0,'left');a.li(11,257);a.branch(5,9,11,'done')
    a.li(11,511);a.jump('right_edge')
    a.label('left');a.li(11,254)
    a.label('right_edge');a.lw(9,16,516);a.branch(5,9,11,'done')
    for reg,value in ((4,0),(5,511),(6,0),(7,SCISSOR_Y1)):a.li(reg,value)
    a.call(hud.SCISSOR)
    for reg,value in ((4,(1792+255)*16),(5,Y_ORIGIN*16),
                      (6,(1792+257)*16),(7,(Y_ORIGIN+DISPLAY_H)*16),(8,0x80000000)):
        a.li(reg,value)
    a.call(bars.RECT)
    a.label('done');hud.restore(a);a.i(55,31,29,0);a.addiu(29,29,16);a.jr()
    data=a.finish();assert len(data)<=END-CODE;return data


@modes.matching_install
def build_memory(ram):
    if len(ram)!=0x8000000:raise ValueError('Split borders require captured 128 MiB RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if manager&3 or not 0x100000<=manager<=len(ram)-16 or u(manager)!=2:
        raise ValueError('Split borders require the captured native actor manager')
    if tuple(u(core.MODE+4*i) for i in range(4))!=(1,count,manager,count) or count not in modes.ACTOR_COUNTS:
        raise ValueError('Split borders require an authenticated prepared match')
    if tuple(u(hud.CONTROL+4*i) for i in range(3))!=(hud.MAGIC,manager,1):
        raise ValueError('Split borders require the prepared viewport HUD')
    for address,data in ((hud.SCISSOR,hud.scissor_code()),(bars.RECT,bars.rectangle_code()),(bars.TEMPLATE,bars.sprite_template())):
        if ram[address:address+len(data)]!=data:raise ValueError('Split border GS dependency changed')
    body=code();hook=struct.pack('<2I',(3<<26)|(CODE>>2),0)
    if ram[HOOK:HOOK+8]==hook and ram[CODE:CODE+len(body)]==body:
        return dict(blocks=[])
    if ram[HOOK:HOOK+8]!=ORIGINAL:raise ValueError('Native split overlay call changed')
    if any(ram[CODE:END]):raise ValueError('Split border code reservation occupied')
    return dict(blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex())
                        for p,b in ((CODE,body),(HOOK,hook))])
