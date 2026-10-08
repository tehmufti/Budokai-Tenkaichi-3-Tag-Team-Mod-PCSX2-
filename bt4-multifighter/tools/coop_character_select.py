"""Sequential native multiplayer roster ownership, before translated input.

The native one-pad Team Select owns the complete character/form/costume flow.
Co-op delegates allies in controller order. Three/four-player team modes
delegate physical seats in order; FFA delegates the first N selections,
left column then right. P1 manages CPU additions and Done. No roster is invented.
The slot-to-seat table is deliberately separate from the native two-pad limit.
"""
from native_map import A
from functools import lru_cache
import fonts
from prototype import Assembler
import mode_menu
import roster_selection_guard as guard
from native_map import GPO
from regional import MENU_BACK

CODE,DRAW,DATA,END=0x07699000,0x07699900,0x0769A000,0x076A0000
CONTROL=guard.CONTROL
ENABLED,OWNER,SEAT,READY,VISIBLE,SHOW_HINT=0x80,0x84,0x88,0x8C,0x90,0x94
ALL_CONTROLLERS=0xE0
BACK=MENU_BACK  # Native translated back (USA/Europe Triangle, Japan Cross), including controller reassignment.
SLOT_SEATS=(0,1,0,0,0)
PAD_STRIDE=0x1C0
# These are the native reads and accepted-pick writes that make delegation safe.
SIGNATURES=dict(guard.SIGNATURES)
SIGNATURES.update({A(0x34DD20):0x8C440190,A(0x34E158):0x8C42018C,
                   A(0x34FF70):0x8C64012C,A(0x34FF74):0x8C620134,
                   A(0x34FF84):0xAC620134,A(0x34FFA4):0xAC83012C})


def pointer(a,reg,size):
    a.i(12,9,reg,3);a.branch(5,9,0,'inactive')
    a.li(9,0x100000);a.r(0x2B,9,reg,9);a.branch(5,9,0,'inactive')
    a.li(9,0x2000000-size);a.r(0x2B,9,9,reg);a.branch(5,9,0,'inactive')


def scope(a,*,drawing=False,require_enabled=True,all_selectors=False):
    a.li(8,CONTROL);a.lw(9,8);a.li(10,guard.MAGIC);a.branch(5,9,10,'done')
    a.lw(9,8,guard.CHOICE)
    if not all_selectors:
        a.lw(10,8,ALL_CONTROLLERS);a.branch(4,10,0,'assigned_scope')
    # Only committed mod modes; never acquire an original-menu selector.
    a.i(11,10,9,22);a.branch(4,10,0,'inactive');a.branch(4,9,0,'inactive')
    a.addiu(10,0,6);a.branch(4,9,10,'inactive');a.jump('coop_choice')
    a.label('assigned_scope')
    for choice in (4,7,10,12,13,14,15,16,17,18,19,20,21):a.addiu(10,0,choice);a.branch(4,9,10,'coop_choice')
    a.addiu(10,0,11);a.branch(5,9,10,'inactive');a.label('coop_choice')
    if require_enabled:
        a.lw(9,8,ALL_CONTROLLERS);a.branch(5,9,0,'selection_enabled')
        a.lw(9,8,ENABLED);a.addiu(10,0,1);a.branch(5,9,10,'inactive')
        a.label('selection_enabled')
    a.li(11,mode_menu.SCENE_MANAGER);a.lw(11,11);pointer(a,11,0x20)
    a.lw(9,11,0x18);a.addiu(10,0,40);a.branch(5,9,10,'inactive')
    a.lw(9,11,0x14);a.i(12,9,9,0x100);a.branch(5,9,0,'inactive')
    for p,word in SIGNATURES.items():
        a.li(11,p);a.lw(9,11);a.li(10,word);a.branch(5,9,10,'inactive')
    a.li(11,guard.TEAM_OBJECT);a.lw(11,11);pointer(a,11,0x3F00)
    a.lw(9,11,0x3C);a.i(12,9,9,2);a.branch(4,9,0,'inactive')
    # Input delegation only owns the one-pad selector. Slot badges also draw
    # in the native two-pad selector, without changing its input ownership.
    a.lw(9,11,0x3C38)
    if all_selectors:
        a.i(11,9,9,2);a.branch(4,9,0,'inactive')
    else:a.branch(5,9,0,'inactive')
    a.lw(13,11,0x3C58);a.i(11,9,13,2);a.branch(4,9,0,'inactive')
    a.r(0,12,0,13,2);a.r(0x21,12,12,11);a.lw(12,12,0x8E8);pointer(a,12,0x200)
    a.lw(9,12,0x13C);a.i(11,10,9,8);a.branch(4,10,0,'inactive')
    a.lw(14,12,0x12C);a.i(11,9,14,6);a.branch(4,9,0,'inactive')
    a.lw(9,12,0x134);a.i(11,9,9,6);a.branch(4,9,0,'inactive')


def payload():
    a=Assembler(CODE)
    # Every battle frame also goes through this pad epilogue. Save only three
    # scratch registers on that hot path; use a full EE save solely in selector.
    a.addiu(29,29,-0x30)
    for i,r in enumerate((8,9,10)):a.i(31,r,29,i*16)
    a.li(8,guard.CALLER);a.branch(4,4,8,'inspect')
    a.li(8,CONTROL);a.lw(9,8);a.li(10,guard.MAGIC);a.branch(5,9,10,'quick_done')
    for off in (OWNER,SEAT,READY,VISIBLE):a.sw(0,8,off)
    a.label('quick_done')
    for i,r in enumerate((8,9,10)):a.i(30,r,29,i*16)
    a.addiu(29,29,0x30);a.jr()
    a.label('inspect')
    for i,r in enumerate((8,9,10)):a.i(30,r,29,i*16)
    a.addiu(29,29,0x30)
    # Preserve all EE GPR lanes/FPU/HI/LO. a0 is original native pad caller.
    guard.save(a)
    scope(a)
    a.li(8,CONTROL);a.lw(9,8,ALL_CONTROLLERS);a.branch(4,9,0,'pending_pick')
    a.addiu(15,0,5);a.jump('chosen')  # Stable shared-input ownership.
    a.label('pending_pick')
    # 12C is the hovered slot, which can visit another player's completed
    # fighter. 134 is the accepted roster length: only an accepted pick or
    # a removal changes whose turn it is, not navigation/form/costume browsing.
    a.lw(14,12,0x134)
    a.addiu(15,0,1)
    a.li(8,CONTROL);a.lw(9,8,guard.CHOICE)
    import team_assignment as assignment
    a.call(assignment.RESOLVE);a.branch(4,2,0,'legacy_assignment')
    a.move(15,2);a.jump('chosen');a.label('legacy_assignment')
    a.li(8,CONTROL);a.lw(9,8,guard.CHOICE)
    for choice in (17,20):a.addiu(10,0,choice);a.branch(4,9,10,'three_teams')
    a.addiu(10,0,18);a.branch(4,9,10,'three_ffa')
    for choice in (19,21):a.addiu(10,0,choice);a.branch(4,9,10,'three_coop')
    for choice in (12,15):a.addiu(10,0,choice);a.branch(4,9,10,'four_teams')
    a.addiu(10,0,13);a.branch(4,9,10,'four_ffa')
    a.branch(5,13,0,'chosen')
    a.addiu(10,0,14);a.branch(4,9,10,'four_coop')
    a.addiu(10,0,16);a.branch(5,9,10,'two_coop')
    a.label('four_coop');a.i(11,9,14,4);a.branch(4,9,0,'chosen')
    a.addiu(15,14,1);a.jump('chosen');a.label('two_coop')
    for slot,seat in enumerate(SLOT_SEATS):
        if seat:
            a.addiu(9,0,slot);a.branch(5,14,9,f'next{slot}')
            a.addiu(15,0,seat+1);a.jump('chosen');a.label(f'next{slot}')
    a.jump('chosen')
    a.label('four_teams');a.i(11,9,14,2);a.branch(4,9,0,'chosen')
    a.r(0,15,0,14,1);a.r(0x21,15,15,13);a.addiu(15,15,1);a.jump('chosen')
    a.label('three_teams');a.i(11,9,14,2);a.branch(4,9,0,'chosen')
    a.r(0,10,0,14,1);a.r(0x21,10,10,13);a.i(11,9,10,3);a.branch(4,9,0,'chosen')
    a.addiu(15,10,1);a.jump('chosen')
    a.label('three_coop');a.branch(5,13,0,'chosen');a.i(11,9,14,3);a.branch(4,9,0,'chosen')
    a.addiu(15,14,1);a.jump('chosen')
    a.label('three_ffa');a.addiu(24,0,3);a.jump('ffa_shared')
    a.label('four_ffa');a.addiu(24,0,4)
    a.label('ffa_shared');a.move(10,14);a.branch(4,13,0,'ffa_index')
    a.lw(12,11,0x8E8);pointer(a,12,0x200);a.lw(9,12,0x134)
    a.i(11,12,9,6);a.branch(4,12,0,'inactive');a.r(0x21,10,10,9)
    a.label('ffa_index');a.r(0x2B,9,10,24);a.branch(4,9,0,'chosen');a.addiu(15,10,1)
    a.label('chosen');a.li(8,CONTROL);a.sw(15,8,VISIBLE)
    a.lw(9,8,OWNER);a.branch(5,9,11,'changed');a.lw(9,8,SEAT);a.branch(4,9,15,'same')
    a.label('changed');a.sw(11,8,OWNER);a.sw(15,8,SEAT);a.sw(0,8,READY)
    a.label('same')
    import quad_menu_input
    a.move(4,15);a.call(quad_menu_input.ROUTE);a.li(8,CONTROL)
    # Routing gives host Back priority even during the neutral-input handoff.
    a.branch(5,2,0,'forward')
    a.label('source_ready')
    a.lw(9,8,READY);a.branch(5,9,0,'forward')
    a.r(0x25,9,13,14);a.branch(5,9,0,'consume')
    a.addiu(9,0,1);a.sw(9,8,READY)
    a.label('consume');a.move(13,0);a.move(14,0)
    a.label('forward');a.li(12,mode_menu.PAD);a.sw(13,12,0x18C);a.sw(14,12,0x190);a.jump('done')
    a.label('inactive');a.li(8,CONTROL)
    for off in (OWNER,SEAT,READY,VISIBLE):a.sw(0,8,off)
    a.label('done');guard.restore(a);a.jr()
    blob=a.finish();assert CODE+len(blob)<=DRAW;return blob


@lru_cache(maxsize=1)
def packets():
    """Small native-frame prompt using the existing sprite packet format."""
    from PIL import Image,ImageDraw
    import guest_loading_screen as gs
    # A near-black key is rounded to unused black palette entries by Pillow's
    # palette quantizer. It then survives key removal as an opaque full-frame
    # rectangle. Use a separated chroma key and fill unused entries with it.
    result=[];key=(255,0,255)
    for seat in (1,2):
        im=Image.new('RGB',(512,448),key);d=ImageDraw.Draw(im)
        font=fonts.truetype('sans-bold',16)
        label=f'PLAYER {seat} SELECTS'
        box=d.textbbox((0,0),label,font=font);x=(512-box[2])//2
        d.rectangle((x-9,388,x+box[2]+9,415),fill=(35,19,42))
        d.text((x,391),label,font=font,fill=(247,171,97),stroke_width=1,stroke_fill=(81,34,92))
        pal=Image.new('P',(1,1));colors=[key,(35,19,42),(247,171,97),(81,34,92)]
        pal.putpalette([v for rgb in colors+[key]*(256-len(colors)) for v in rgb])
        im=im.quantize(palette=pal,dither=Image.Dither.NONE).convert('RGB')
        result.append(gs.gif_packet(gs.image_rectangles(im,key=key)))
    assert DATA+sum(map(len,result))<=END
    return tuple(result)


def draw():
    """Called after stock fade from scoped native menu services."""
    p1,p2=packets();a=Assembler(DRAW);guard.save(a)
    scope(a,drawing=True)
    a.li(8,CONTROL);a.lw(9,8,SHOW_HINT);a.branch(4,9,0,'done')
    a.lw(15,8,VISIBLE);a.branch(4,15,0,'done')
    a.li(16,DATA);a.li(17,len(p1));a.addiu(9,0,1);a.branch(4,15,9,'packet')
    a.addiu(9,0,2);a.branch(5,15,9,'done');a.li(16,DATA+len(p1));a.li(17,len(p2))
    a.label('packet')
    # Reject a full/inconsistent GIF arena rather than overwriting it.
    a.lw(8,28,-23004);a.i(11,9,8,2);a.branch(4,9,0,'done')
    a.r(0,8,0,8,2);a.r(0x2D,8,28,8)
    # t0 = gp + 4*index: the arena base/end offsets are gp offsets through another register (GPO by hand).
    a.lw(9,8,GPO(-23024));a.lw(10,8,GPO(-23016));a.lw(11,28,-23008)
    a.r(0x2D,11,11,9);a.branch(5,11,10,'done')
    a.lw(11,28,-23000);a.r(0x2B,12,11,9);a.branch(5,12,0,'done')
    a.r(0x2D,12,11,17);a.addiu(12,12,64);a.r(0x2B,13,12,11);a.branch(5,13,0,'done')
    a.r(0x2B,13,10,12);a.branch(5,13,0,'done')
    a.call(A(0x100878));a.r(0x21,9,16,17);a.move(10,2)
    a.label('copy')
    for off in (0,8):a.i(55,11,16,off);a.i(63,11,10,off)
    a.addiu(16,16,16);a.addiu(10,10,16);a.branch(5,16,9,'copy')
    a.move(4,10);a.call(A(0x100890))
    a.label('inactive');a.label('done');guard.restore(a);a.jr()
    blob=a.finish();assert DRAW+len(blob)<=DATA;return blob


def code_pieces():
    import quad_menu_input, team_assignment
    return [(team_assignment.RESOLVE,team_assignment.resolve_code()),(CODE,payload()),(DRAW,draw()),(DATA,b''.join(packets())),
            (quad_menu_input.CODE,quad_menu_input.payload()),(quad_menu_input.ROUTE,quad_menu_input.route_payload())]
