"""Compact per-view tag meter beneath the normal fighter HUD.

The right-hand strip sits below either status-panel style and to the right of
compact fusion captions. Drawing reads captured identities; it never changes
fighter charge, invitations or input.
"""
import struct

from prototype import Assembler
from native_map import A
from regional import Y_ORIGIN, screen_y
import fresh_team_combat as core
import fresh_team_camera as camera
import team_participation as participation
import battle_mode_policy as modes
import viewport_hud as hud
import guest_killfeed as feed
import guest_healthbars as bars
import localization

BASE, END = 0x06D74000, 0x06D78000
DRAW, ALIVE, TEXT = BASE, BASE+0x1000, BASE+0x1800
CAPTION = BASE+0x2000
CONTROL, MAGIC = 0x06D08000, 0x54414731
METERS, METER_STRIDE = CONTROL+0x100, 32
WIDTH, MARGIN, LABEL_TOP, BAR_TOP, HEIGHT = 64, 8, 72, 80, 2
REGS, STACK = (*range(16, 24), 31), 0x70
LABEL = 'TAG ATTACK'
TEXT_STRIDE = 32
BLUE, GOLD, BLACK = 0x80FFC050, 0x8050D8FF, 0x80000000


def rectangles(view):
    """Design bounds used by layout checks (native coordinates, inclusive view)."""
    x0, x1, y0, y1 = view
    x, y = x1-MARGIN-WIDTH, y0+screen_y(LABEL_TOP)
    return {'caption': (x, y, x+WIDTH, y+6.25),
            'meter': (x-1, y0+screen_y(BAR_TOP)-1,
                      x+WIDTH+1, y0+screen_y(BAR_TOP)+HEIGHT+1)}


def caption_code():
    """The existing native glyph runs at 75% in every view, including solo.

    feed.SMALL_TEXT deliberately falls back to full size outside 3/4 views.
    A private renderer keeps this caption small without changing other text.
    All geometry stays in GS 12.4 units; no reduced bitmap is stretched back up.
    """
    a=Assembler(CAPTION)
    def units(reg):
        a.r(0,14,0,reg,1);a.r(0x21,reg,reg,14);a.r(0,reg,0,reg,2)
    a.addiu(29,29,-0x60)
    saved=(*range(16,24),31)
    for i,r in enumerate(saved):a.i(63,r,29,i*8)
    for d,s in zip(range(16,20),range(4,8)):a.move(d,s)
    a.call(A(0x100878));a.move(20,2);a.li(8,feed.TEMPLATE)
    for off in range(0,112,4):a.lw(9,8,off);a.sw(9,20,off)
    a.sw(19,20,80);a.addiu(21,20,112);a.move(22,0);a.move(23,0)
    a.label('char');a.i(36,8,16,0);a.branch(4,8,0,'finish')
    a.i(12,8,8,127);a.r(0,8,0,8,7);a.li(9,feed.FONT);a.r(0x2D,8,8,9);a.lw(9,8)
    a.addiu(8,8,4)
    a.label('run');a.branch(4,9,0,'next');a.lw(10,8)
    a.i(12,11,10,255);units(11);a.r(0x2D,11,11,17)
    a.r(3,12,0,10,8);a.i(12,12,12,255);units(12);a.r(0x2D,12,12,18)
    a.r(3,13,0,10,16);units(13);a.r(0x2D,13,13,11);a.addiu(14,12,12)
    a.r(0,12,0,12,16);a.r(0x25,11,11,12);a.sw(11,21);a.sw(0,21,4)
    a.r(0,14,0,14,16);a.r(0x25,13,13,14);a.sw(13,21,8);a.sw(0,21,12)
    a.addiu(21,21,16);a.addiu(22,22,1);a.addiu(8,8,4);a.addiu(9,9,-1);a.jump('run')
    a.label('next');a.addiu(16,16,1);a.addiu(17,17,72);a.addiu(23,23,1)
    a.i(11,8,23,TEXT_STRIDE-1);a.branch(5,8,0,'char')
    a.label('finish');a.i(13,8,22,0x8000);a.sw(8,20,96);a.move(4,21);a.call(A(0x100890))
    for i,r in enumerate(saved):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60);a.jr()
    data=a.finish();assert len(data)<=END-CAPTION
    return data


def _pointer(a, reg, size, fail):
    a.li(8, 0x100000); a.r(0x2B, 9, reg, 8); a.branch(5, 9, 0, fail)
    a.li(8, 0x08000000-size+1); a.r(0x2B, 9, reg, 8); a.branch(4, 9, 0, fail)
    a.i(12, 9, reg, 3); a.branch(5, 9, 0, fail)


def alive_code():
    """Physical a0 -> a present living non-giant tag actor, else zero; leaf."""
    import extra_throws as actors
    import tag_rush_safety as safety
    import tag_team_rush as tag
    a=Assembler(ALIVE)
    a.li(8, CONTROL); a.lw(9, 8, 8); a.r(0x2B, 9, 4, 9); a.branch(4, 9, 0, 'no')
    a.li(8, participation.CONTROL); a.lw(9, 8, 12); a.lw(10, 8, 16)
    a.r(0x27, 10, 10, 0); a.r(0x24, 9, 9, 10)
    a.addiu(10, 0, 1); a.r(4, 10, 4, 10); a.r(0x24, 9, 9, 10); a.branch(4, 9, 0, 'no')
    a.r(0, 8, 0, 4, 2); a.li(2, core.POINTERS); a.r(0x21, 2, 2, 8); a.lw(2, 2)
    _pointer(a, 2, 0x1600, 'no')
    a.lw(9,2);a.branch(5,9,4,'no')
    a.lw(9, 2, 0x994); a.i(11, 8, 9, 5); a.branch(4, 8, 0, 'no')
    a.lw(10, 2, 0x998); a.r(0x2B, 10, 9, 10); a.branch(4, 10, 0, 'no')
    a.r(0, 3, 0, 9, 7); a.r(0, 8, 0, 9, 5); a.r(0x21, 3, 3, 8)
    a.r(0, 8, 0, 9, 2); a.r(0x21, 3, 3, 8); a.r(0x21, 3, 3, 2)
    a.lw(8, 3, 0x9E4); a.branch(6, 8, 0, 'no')
    actors.model(a,2,12,'no');safety.emit_non_giant_model(a,12,'no');tag.emit_admitted_model(a,12,'no');a.jr()
    a.label('no'); a.move(2, 0); a.jr()
    data=a.finish(); assert len(data)<=TEXT-ALIVE
    return data


def _rect(a, width, dy, height, color, *, dx=0):
    # s5/s6 retain the top-left of the bar; s7 is the scaled fill width.
    a.addiu(4, 21, 1792+dx); a.r(0, 4, 0, 4, 4)
    a.addiu(5, 22, Y_ORIGIN+dy); a.r(0, 5, 0, 5, 4)
    if width is None: a.r(0x21, 6, 21, 23); a.addiu(6, 6, 1792)
    else: a.addiu(6, 21, 1792+dx+width)
    a.r(0, 6, 0, 6, 4)
    a.addiu(7, 22, Y_ORIGIN+dy+height); a.r(0, 7, 0, 7, 4)
    if color is None: a.lw(8, 29, 0x60)
    else: a.li(8, color)
    a.call(bars.RECT)


def draw_code():
    a=Assembler(DRAW); a.addiu(29, 29, -STACK)
    for i, reg in enumerate(REGS): a.i(63, reg, 29, i*8)
    a.r(16, 8, 0); a.i(63, 8, 29, 0x48)
    a.r(18, 8, 0); a.i(63, 8, 29, 0x50)
    core.gate(a, 'done')
    a.li(16, CONTROL); a.lw(9, 16); a.li(8, MAGIC); a.branch(5, 9, 8, 'done')
    a.lw(9, 16, 4); a.lw(8, 28, -22364); a.branch(5, 9, 8, 'done')
    a.lw(9, 16, 8); a.branch(5, 9, 10, 'done')
    for off in (12, 60):
        a.lw(9, 16, off); a.addiu(8, 0, 1); a.branch(5, 9, 8, 'done')
    # A captured free-for-all has no allies, regardless of physical slot parity.
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(11,modes.MAGIC);a.branch(5,9,11,'team_mode')
    a.lw(9,8,4);a.lw(11,16,4);a.branch(5,9,11,'team_mode')
    a.lw(9,8,12);a.li(11,modes.FFA);a.branch(4,9,11,'done')
    a.label('team_mode')
    a.li(8, participation.CONTROL); a.lw(9, 8); a.addiu(11, 0, 5); a.branch(5, 9, 11, 'done')
    a.lw(9, 8, 4); a.lw(11, 16, 4); a.branch(5, 9, 11, 'done')
    a.lw(9, 8, 8); a.branch(5, 9, 10, 'done')
    a.li(8, A(0x333700)); a.lw(9, 8); a.branch(5, 9, 0, 'done')
    a.li(8, A(0x2FEB38)); a.lw(11, 8); _pointer(a, 11, 4, 'done')
    a.lw(8, 11); a.addiu(9, 0, 3); a.branch(5, 8, 9, 'done')
    a.lw(17, 28, -22176); _pointer(a, 17, 832, 'done')
    # Apply to the camera actually drawn in this viewport: an unrelated
    # bystander's follow camera must not hide its meter for someone else's move.
    import cinematic_policy
    cinematic_policy.camera_running(a, 17, 'ordinary_camera', 'tag_hud_camera')
    a.lw(8, 17, 768); a.lw(9, 17, 772); a.r(0x25, 8, 8, 9); a.branch(5, 8, 0, 'done')
    a.label('ordinary_camera')
    a.li(19, camera.SUCCESSOR_CONTROL+8)
    a.li(8, hud.CONTROL); a.lw(9, 8); a.li(10, hud.MAGIC); a.branch(5, 9, 10, 'subject')
    a.call(hud.ACTIVE); a.branch(4, 2, 0, 'subject')
    a.li(20, hud.VIEWS); a.move(21, 0)
    a.label('view')
    for off, desc in ((512, 4), (516, 8), (520, 12), (524, 16)):
        a.lw(8, 17, off); a.lw(9, 20, desc); a.branch(5, 8, 9, 'next_view')
    a.lw(19, 20, 20); a.jump('subject')
    a.label('next_view'); a.addiu(20, 20, hud.VIEW_STRIDE); a.addiu(21, 21, 1)
    a.addiu(8, 0, hud.MAX_VIEWS); a.branch(5, 21, 8, 'view'); a.jump('done')
    a.label('subject'); a.lw(18, 19); a.move(4, 18); a.call(ALIVE); a.branch(4, 2, 0, 'done')
    a.lw(8,16,16);a.branch(4,8,0,'free_subject')
    a.lw(8,16,24);a.branch(5,8,0,'done')
    a.lw(8,16,20);a.li(9,1);a.r(4,9,18,9);a.r(0x24,8,8,9);a.branch(5,8,0,'done')
    a.label('free_subject')
    # Team parity comes from the captured physical subject, not an actor role alias.
    a.i(12, 19, 18, 1); a.move(20, 19); a.move(21, 0); a.lw(22, 16, 8)
    a.label('ally'); a.move(4, 20); a.call(ALIVE); a.branch(4, 2, 0, 'next_ally')
    a.addiu(21, 21, 1); a.addiu(8, 0, 2); a.branch(4, 21, 8, 'team_ready')
    a.label('next_ally'); a.addiu(20, 20, 2); a.r(0x2B, 8, 20, 22); a.branch(5, 8, 0, 'ally'); a.jump('done')
    a.label('team_ready'); a.r(0, 19, 0, 18, 5); a.li(8, METERS); a.r(0x21, 19, 19, 8)
    a.lw(20, 16, 48); a.branch(6, 20, 0, 'done'); a.lw(23, 19)
    a.r(0x2B, 8, 23, 20); a.branch(5, 8, 0, 'charging'); a.move(23, 20)
    a.li(8, GOLD); a.sw(8, 29, 0x60); a.jump('chosen')
    a.label('charging'); a.li(8, BLUE); a.sw(8, 29, 0x60)
    a.label('chosen'); a.li(22, TEXT); a.lw(21, 17, 516); a.addiu(21, 21, -MARGIN-WIDTH)
    a.lw(8, 17, 512); a.r(0x2A, 8, 21, 8); a.branch(5, 8, 0, 'done')
    a.lw(19, 17, 520); a.addiu(19, 19, screen_y(LABEL_TOP))
    a.lw(8, 17, 524); a.lw(9, 17, 520); a.addiu(9, 9, screen_y(BAR_TOP)+HEIGHT+1)
    a.r(0x2A, 8, 8, 9); a.branch(5, 8, 0, 'done')
    for dx, dy, color in ((1, 1, BLACK), (0, 0, None)):
        a.move(4, 22); a.addiu(5, 21, 1792+dx); a.r(0, 5, 0, 5, 4)
        a.addiu(6, 19, Y_ORIGIN+dy); a.r(0, 6, 0, 6, 4)
        if color is None: a.lw(7, 29, 0x60)
        else: a.li(7, color)
        a.call(CAPTION)
    a.lw(22, 17, 520); a.addiu(22, 22, screen_y(BAR_TOP))
    a.addiu(8, 0, WIDTH); a.r(24, 0, 23, 8); a.r(18, 23, 0)
    a.r(27, 0, 23, 20); a.r(18, 23, 0)
    _rect(a, WIDTH+2, -1, HEIGHT+2, BLACK, dx=-1)
    _rect(a, WIDTH, 0, HEIGHT, 0x80403020)
    a.branch(4, 23, 0, 'done'); _rect(a, None, 0, HEIGHT, None)
    a.label('done')
    a.i(55, 8, 29, 0x48); a.r(17, 0, 8); a.i(55, 8, 29, 0x50); a.r(19, 0, 8)
    for i, reg in enumerate(REGS): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, STACK); a.jr()
    data=a.finish(); assert len(data)<=ALIVE-DRAW
    return data


def pieces(settings=None):
    return [(DRAW, draw_code()), (ALIVE, alive_code()), (CAPTION, caption_code()),
            (TEXT, localization.slot(LABEL, TEXT_STRIDE, settings))]


def hud_extension(ram):
    if len(ram)<END or struct.unpack_from('<I', ram, CONTROL)[0]!=MAGIC: return None
    if ram[DRAW:DRAW+8]!=draw_code()[:8]: return None
    return (CONTROL, MAGIC, DRAW)


def hud_patch(ram):
    """Compose our draw entry into a known normal or three/four-view renderer.

    Installation follows four_player_mode. Its wrapper suppresses the normal
    extensions; in that case the quad renderer owns all per-view calls instead.
    Unknown bytes are never overwritten.
    """
    if struct.unpack_from('<I', ram, hud.CONTROL)[0]!=hud.MAGIC: return []
    import quad_viewports as quad
    entry=(CONTROL, MAGIC, DRAW)
    before=hud.hud_extensions(ram)
    without=tuple(e for e in before if e!=entry)
    candidates=(before, without) if before!=without else (without,)
    after=without+(entry,)
    previous=struct.unpack_from('<I', ram, hud.CONTROL+16)[0]
    if struct.unpack_from('<I', ram, quad.CONTROL)[0]==quad.MAGIC:
        address, limit=quad.DRAW, quad.SELECT
        for extensions in candidates:
            old=quad.draw(extensions)
            if ram[address:address+len(old)]==old: break
        else: raise ValueError('Unknown per-view HUD renderer for tag-team rush')
        new=quad.draw(after)
    else:
        address, limit=hud.CODE, hud.ACTIVE
        for extensions, kwargs in ((e,k) for e in candidates for k in (dict(deferred=True), dict())):
            old=hud.wrapper(previous, extensions=extensions, **kwargs)
            if ram[address:address+len(old)]==old:
                new=hud.wrapper(previous, extensions=after, **kwargs); break
        else: raise ValueError('Unknown viewport HUD wrapper for tag-team rush')
    if ram[address:address+len(old)]!=old: raise ValueError('Unknown per-view HUD renderer for tag-team rush')
    if old==new: return []
    if len(new)>limit-address: raise ValueError('Tag-team rush HUD exceeds its drawing reservation')
    if any(ram[address+len(old):address+len(new)]): raise ValueError('Tag-team rush HUD extension tail occupied')
    return [(address, new)]
