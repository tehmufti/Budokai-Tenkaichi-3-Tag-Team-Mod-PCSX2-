"""Small player ownership badges above native character-selection slots."""
from native_map import A
import struct
from functools import lru_cache
import fonts
from prototype import Assembler
import team_assignment as teams
import coop_character_select as selector
import roster_selection_guard as guard
from native_map import GPO

CODE,DATA,END=0x06912000,0x06913000,0x06928000
VISIBLE=0xDC


@lru_cache(maxsize=1)
def packets():
    from PIL import Image,ImageDraw
    import guest_loading_screen as gs
    result=[];font=fonts.truetype('sans-bold',11)
    key=(255,0,255)
    for side in range(2):
        for slot in range(5):
            for player in range(5):
                im=Image.new('RGB',(512,448),key);d=ImageDraw.Draw(im)
                x=slot*64+30;y=11 if side==0 else 355
                color=(73,192,255) if side==0 else (255,137,117)
                d.rounded_rectangle((x,y,x+29,y+14),radius=3,fill=(18,25,42),outline=color)
                text=f'P{player}' if player else 'CPU'
                width=d.textbbox((0,0),text,font=font)[2]
                d.text((x+(30-width)//2,y),text,font=font,fill=(255,240,194))
                palette=Image.new('P',(1,1));colors=[key,(18,25,42),color,(255,240,194)]
                palette.putpalette([v for rgb in colors+[key]*252 for v in rgb])
                im=im.quantize(palette=palette,dither=Image.Dither.NONE).convert('RGB')
                result.append(gs.gif_packet(gs.image_rectangles(im,key=key)))
    assert DATA+50*8+sum(map(len,result))<=END
    return tuple(result)


def data():
    blobs=packets();offset=DATA+50*8;table=bytearray()
    for blob in blobs:table+=struct.pack('<2I',offset,len(blob));offset+=len(blob)
    return bytes(table)+b''.join(blobs)


def code():
    import native_mode_menu
    a=Assembler(CODE);guard.save(a)
    selector.scope(a,drawing=True,require_enabled=False,all_selectors=True)
    a.li(8,teams.MENU)
    a.lw(9,8,VISIBLE);a.branch(4,9,0,'done')
    # Read the committed mode, not a leftover team-assignment receipt. FFA
    # has controller setup, but no team assignment. Its 3/4-player seats follow selection order;
    # 1/2-player FFA retains the native first slot on each side.
    a.lw(9,8,guard.CHOICE)
    groups={}
    for choice,(mode,humans) in enumerate(native_mode_menu.SELECTIONS,1):
        if choice==6:continue  # Original game: no mod ownership badges.
        layout=1 if mode=='ffa' and humans>=3 else 2 if mode in ('coop','training_coop') else 0
        key=(humans,layout,choice in teams.TEAM_CHOICES)
        groups.setdefault(key,[]).append(choice)
    for index,choices in enumerate(groups.values()):
        for choice in choices:
            a.addiu(10,0,choice);a.branch(4,9,10,f'mode{index}')
    a.jump('done')
    for index,(humans,layout,assigned) in enumerate(groups):
        a.label(f'mode{index}');a.addiu(22,0,humans);a.addiu(23,0,layout)
        a.addiu(24,0,int(assigned));a.jump('mode_ready')
    a.label('mode_ready');a.move(26,13)
    a.branch(4,24,0,'assignment_ready')
    a.lw(9,8,teams.VALID);a.addiu(10,0,1);a.branch(5,9,10,'no_assignment')
    a.lw(9,8,teams.HUMANS);a.branch(4,9,22,'assignment_ready')
    a.label('no_assignment');a.move(24,0)
    a.label('assignment_ready');a.lw(8,11,0x8E8);selector.pointer(a,8,0x200)
    a.lw(25,8,0x134);a.i(11,9,25,6);a.branch(4,9,0,'done')
    # Native GIF helpers can clobber t8/t9/kernel temporaries. Keep the row
    # metadata in unused space in our saved context, not live across calls.
    for reg,offset in ((24,0x2A0),(25,0x2A4),(26,0x2A8)):a.sw(reg,29,offset)
    # Each native row animates independently. Only mark the slot overview,
    # never the horizontally scrolling character/form gallery.
    a.move(16,0);a.label('side');a.li(8,guard.TEAM_OBJECT);a.lw(8,8)
    a.lw(26,29,0x2A8)
    a.r(0,9,0,16,2);a.r(0x21,8,8,9);a.lw(8,8,0x8E8)
    selector.pointer(a,8,0x200)
    a.lw(9,8,0x13C);a.addiu(10,0,6);a.branch(5,9,10,'next_side')
    # Until the left FFA roster is finished, the right-side human seats are
    # unknown. Do not advertise duplicate players on both unfinished rows.
    a.addiu(9,0,1);a.branch(5,23,9,'row_ready');a.branch(4,16,0,'row_ready')
    a.branch(4,26,0,'next_side');a.label('row_ready')
    a.move(17,0);a.label('slot')
    for reg,offset in ((24,0x2A0),(25,0x2A4),(26,0x2A8)):a.lw(reg,29,offset)
    a.r(0,18,0,17,1);a.r(0x21,18,18,16);a.move(19,0)
    a.branch(4,24,0,'default_seats')
    for player in range(4):
        a.addiu(9,0,player);a.r(0x2B,9,9,22);a.branch(4,9,0,'found')
        a.li(8,teams.MENU+teams.SEATS+4*player);a.lw(8,8);a.branch(5,8,18,f'player{player}')
        a.addiu(19,0,player+1);a.jump('found');a.label(f'player{player}')
    a.jump('found');a.label('default_seats');a.move(8,18)
    a.branch(4,23,0,'owner_index');a.move(8,17)
    a.addiu(9,0,2);a.branch(5,23,9,'ffa_seats')
    a.branch(5,16,0,'found');a.jump('owner_index')
    a.label('ffa_seats');a.branch(5,16,0,'ffa_right')
    a.branch(4,26,0,'owner_index');a.r(0x2B,9,17,25);a.branch(4,9,0,'found')
    a.jump('owner_index');a.label('ffa_right');a.r(0x21,8,8,25)
    a.label('owner_index');a.r(0x2B,9,8,22);a.branch(4,9,0,'found');a.addiu(19,8,1)
    a.label('found');a.r(0,8,0,16,2);a.r(0x21,8,8,16);a.r(0x21,8,8,17)
    a.r(0,9,0,8,2);a.r(0x21,8,8,9);a.r(0x21,8,8,19);a.r(0,8,0,8,3)
    a.li(9,DATA);a.r(0x21,8,8,9);a.lw(20,8);a.lw(21,8,4)
    # Same checked arena contract as the native menu's existing indicator.
    a.lw(8,28,-23004);a.i(11,9,8,2);a.branch(4,9,0,'done')
    a.r(0,8,0,8,2);a.r(0x2D,8,28,8)
    # t0 = gp + 4*index: the arena base/end offsets are gp offsets through another register (GPO by hand).
    a.lw(9,8,GPO(-23024));a.lw(10,8,GPO(-23016));a.lw(11,28,-23008)
    a.r(0x2D,11,11,9);a.branch(5,11,10,'done')
    a.lw(11,28,-23000);a.r(0x2B,12,11,9);a.branch(5,12,0,'done')
    a.r(0x2D,12,11,21);a.addiu(12,12,64);a.r(0x2B,13,12,11);a.branch(5,13,0,'done')
    a.r(0x2B,13,10,12);a.branch(5,13,0,'done')
    a.call(A(0x100878));a.r(0x21,9,20,21);a.move(10,2)
    a.label('copy')
    for off in (0,8):a.i(55,11,20,off);a.i(63,11,10,off)
    a.addiu(20,20,16);a.addiu(10,10,16);a.branch(5,20,9,'copy')
    a.move(4,10);a.call(A(0x100890))
    a.addiu(17,17,1);a.addiu(8,0,5);a.branch(5,17,8,'slot')
    a.label('next_side');a.addiu(16,16,1);a.addiu(8,0,2);a.branch(5,16,8,'side')
    a.label('inactive');a.label('done');guard.restore(a);a.jr();out=a.finish();assert CODE+len(out)<=DATA
    return out


def pieces():return [(CODE,code()),(DATA,data())]
