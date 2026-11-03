"""Per-CPU COM level after the original Team Select costume confirmation.

The original selector still commits the fighter and its equipment. The pad
service holds that one confirmation while the COM-level plate is open; the
native battle-setup call receives the chosen level before any AI is loaded.
"""
import struct
from functools import lru_cache
from native_map import A, GPO, elf_path
from prototype import Assembler, ROOT, elf_reader
from regional import MENU_ACCEPT, MENU_BACK
import mode_menu
import roster_selection_guard as guard
import team_assignment as assignment

# Retired v3 loading-picture bank; v4 uses 0x06A00000..0x06B00000.
# Menu state must survive the 0x07800000..0x08000000 preparation packet.
BASE, END = 0x07480000, 0x074D0000
INPUT, DRAW, MEMBER, OLD_MEMBER = BASE, BASE+0x2000, BASE+0x3000, BASE+0x3800
CONTROL, TABLE, DATA = BASE+0x4000, BASE+0x4100, BASE+0x5000
MAGIC=0x43505531
# header: magic, active physical+1, current level; rows: ten physical slots,
# each setting+1 (0 inherits the native COM level). Counts track removals.
LEVELS=CONTROL+0x40
ENTRY=A(0x12A308) # interior level-copy; tournament owns the function entry
TOUR_LEVELS=BASE+0x4800 # 17 entrants, five settings+1 each

def human(a,side,slot,yes):
    import tag_tournament as tour
    a.li(8,tour.DRAFT);a.lw(9,8);a.li(10,tour.DRAFT_MAGIC);a.branch(5,9,10,'regular_owners')
    a.r(0,10,0,slot,1);a.r(0x21,10,10,side);a.r(0x21,8,8,10);a.i(36,9,8,4)
    a.addiu(10,0,255);a.branch(5,9,10,yes);a.jump('cpu');a.label('regular_owners')
    a.li(8,guard.CONTROL);a.lw(9,8,guard.CHOICE)
    a.r(0,10,0,slot,1);a.r(0x21,10,10,side)
    a.lw(11,8,assignment.VALID);a.addiu(12,0,1);a.branch(5,11,12,'legacy')
    for choice in assignment.TEAM_CHOICES:
        a.addiu(11,0,choice);a.branch(4,9,11,'assigned')
    a.jump('legacy');a.label('assigned')
    for p in range(4):
        a.lw(11,8,assignment.SEATS+4*p);a.branch(4,11,10,yes)
    a.jump('cpu');a.label('legacy')
    # Co-op puts all humans on the left. FFA's 3/4-player selector
    # assigns people in selection order, left column then right.
    for choice,count in ((4,2),(11,2),(14,4),(16,4),(19,3),(21,3)):
        a.addiu(11,0,choice);a.branch(5,9,11,f'not_coop{choice}')
        a.branch(5,side,0,'cpu');a.i(11,11,slot,count);a.branch(5,11,0,yes);a.jump('cpu');a.label(f'not_coop{choice}')
    for choice,count in ((13,4),(18,3)):
        a.addiu(11,0,choice);a.branch(5,9,11,f'not_ffa{choice}')
        a.move(11,slot);a.branch(4,side,0,f'ffa{choice}')
        a.lw(12,16,0x8E8);a.lw(12,12,0x134);a.r(0x21,11,11,12)
        a.label(f'ffa{choice}');a.i(11,11,11,count);a.branch(5,11,0,yes);a.jump('cpu');a.label(f'not_ffa{choice}')
    groups=((0,(8,5)),(1,(1,2,9)),(2,(3,7,10)),(3,(17,20)),(4,(12,15)))
    for count,choices in groups:
        for choice in choices:
            a.addiu(11,0,choice);a.branch(5,9,11,f'not{choice}')
            a.i(11,11,10,count);a.branch(5,11,0,yes);a.jump('cpu');a.label(f'not{choice}')
    a.jump(yes) # Unknown/scenario selection is never intercepted.
    a.label('cpu')

def input_code():
    a=Assembler(INPUT);guard.save(a)
    a.li(8,guard.CONTROL);a.lw(9,8);a.li(10,guard.MAGIC);a.branch(5,9,10,'done')
    a.li(8,mode_menu.MAIN_CALLER);a.branch(5,4,8,'selector')
    a.li(8,CONTROL);a.li(9,MAGIC);a.sw(9,8)
    for off in (4,8,12,16,20,*range(0x40,0x68,4)):a.sw(0,8,off)
    a.jump('done');a.label('selector');a.li(8,guard.CALLER);a.branch(5,4,8,'done')
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done')
    a.li(8,mode_menu.SCENE_MANAGER);a.lw(8,8);guard.pointer(a,8,0x20)
    a.lw(9,8,0x18);a.addiu(10,0,40);a.branch(5,9,10,'clear_modal')
    a.li(8,guard.TEAM_OBJECT);a.lw(16,8);guard.pointer(a,16,0x3F00)
    a.lw(9,16,0x3C);a.i(12,9,9,4);a.branch(5,9,0,'clear_modal') # stage selector
    a.move(17,0)
    a.label('pad');a.lw(18,16,0x3C58);a.r(0x21,18,18,17)
    a.i(11,9,18,2);a.branch(4,9,0,'done')
    a.r(0,9,0,18,2);a.r(0x21,9,9,16);a.lw(19,9,0x8E8);guard.pointer(a,19,0x200)
    a.li(20,mode_menu.PAD);a.branch(4,17,0,'pad_ready');a.addiu(20,20,0x1C0);a.label('pad_ready')
    # Shift difficulty with a removed roster member, just as the native list shifts.
    a.r(0,9,0,18,2);a.li(8,CONTROL+16);a.r(0x21,8,8,9)
    a.lw(10,8);a.lw(11,19,0x134);a.sw(11,8);a.r(0x2B,12,11,10);a.branch(4,12,0,'state')
    a.lw(12,19,0x12C);a.i(11,9,12,5);a.branch(4,9,0,'state')
    a.r(0,12,0,12,1);a.r(0x21,12,12,18);a.r(0,12,0,12,2);a.li(8,LEVELS);a.r(0x21,8,8,12)
    a.label('shift');a.i(11,9,12,32);a.branch(4,9,0,'shift_end');a.lw(9,8,8);a.sw(9,8);a.addiu(8,8,8);a.addiu(12,12,8);a.jump('shift')
    a.label('shift_end');a.sw(0,8)
    a.label('state');a.lw(9,19,0x13C);a.addiu(10,0,5);a.branch(4,9,10,'costume')
    # Backing out or changing the roster can dismiss the native costume panel
    # before this service runs. Do not leave its CPU modal on the next fighter.
    a.li(8,CONTROL);a.lw(9,8,4);a.branch(4,9,0,'next');a.addiu(9,9,-1);a.i(12,9,9,1)
    a.branch(5,9,18,'next');a.sw(0,8,4);a.jump('next');a.label('costume')
    a.lw(21,19,0x12C);a.i(11,9,21,5);a.branch(4,9,0,'next')
    human(a,18,21,'next')
    a.r(0,22,0,21,1);a.r(0x21,22,22,18);a.addiu(22,22,1)
    a.li(23,CONTROL);a.lw(9,23,4);a.branch(4,9,22,'active')
    a.branch(5,9,0,'consume') # another CPU is choosing its level
    a.lw(9,20,0x18C);a.i(12,9,9,MENU_ACCEPT);a.branch(4,9,0,'next')
    a.sw(22,23,4);a.addiu(9,22,-1);a.r(0,9,0,9,2);a.li(8,LEVELS);a.r(0x21,8,8,9);a.lw(9,8)
    a.branch(5,9,0,'chosen');a.li(8,A(0x2FF28C));a.lw(8,8);guard.pointer(a,8,0xD00);a.lw(9,8,0xC38);a.addiu(9,9,1)
    a.label('chosen');a.addiu(9,9,-1);a.i(11,10,9,5);a.branch(5,10,0,'valid_level');a.addiu(9,0,2)
    a.label('valid_level');a.sw(9,23,8);a.jump('consume')
    a.label('active');a.lw(10,23,8);a.lw(9,20,0x190);a.i(12,11,9,8);a.branch(4,11,0,'down')
    a.addiu(10,10,-1);a.branch(1,10,1,'store');a.addiu(10,0,4);a.jump('store')
    a.label('down');a.i(12,11,9,4);a.branch(4,11,0,'buttons');a.addiu(10,10,1);a.i(11,11,10,5);a.branch(5,11,0,'store');a.move(10,0)
    a.label('store');a.sw(10,23,8)
    a.label('buttons');a.lw(9,20,0x18C);a.i(12,11,9,MENU_BACK);a.branch(4,11,0,'confirm');a.sw(0,23,4);a.jump('consume')
    a.label('confirm');a.i(12,11,9,MENU_ACCEPT);a.branch(4,11,0,'consume')
    a.addiu(9,22,-1);a.r(0,9,0,9,2);a.li(8,LEVELS);a.r(0x21,8,8,9);a.addiu(10,10,1);a.sw(10,8);a.sw(0,23,4);a.jump('next')
    a.label('consume');a.sw(0,20,0x18C);a.sw(0,20,0x190)
    a.label('next');a.lw(9,16,0x3C38);a.addiu(10,0,1);a.branch(5,9,10,'done');a.addiu(17,17,1);a.i(11,9,17,2);a.branch(5,9,0,'pad')
    a.jump('done');a.label('clear_modal');a.li(8,CONTROL);a.sw(0,8,4)
    a.label('done');guard.restore(a);a.jr();b=a.finish();assert INPUT+len(b)<=DRAW;return b

@lru_cache(maxsize=1)
def packets():
    import cpu_difficulty_art,guest_loading_screen as gs
    out=tuple(gs.gif_packet(rows) for rows in cpu_difficulty_art.rectangles())
    assert DATA+sum(map(len,out))<=END
    return tuple(out)

def draw_code():
    a=Assembler(DRAW);guard.save(a)
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done');a.lw(9,8,4);a.branch(4,9,0,'done')
    # pointer() uses t1 as scratch; the scene pointer must live elsewhere.
    a.li(11,mode_menu.SCENE_MANAGER);a.lw(11,11);guard.pointer(a,11,0x20);a.lw(9,11,0x18);a.addiu(10,0,40);a.branch(5,9,10,'done')
    a.lw(9,8,8);a.i(11,10,9,5);a.branch(4,10,0,'done')
    # Native-menu control owns the selected language. Both banks are immutable.
    import native_mode_menu
    a.li(10,native_mode_menu.CONTROL);a.lw(10,10,0xD8);a.branch(4,10,0,'language_ready')
    a.addiu(9,9,5);a.label('language_ready')
    a.r(0,9,0,9,3);a.li(10,TABLE);a.r(0x21,10,10,9);a.lw(16,10);a.lw(17,10,4)
    a.lw(8,28,-23004);a.i(11,9,8,2);a.branch(4,9,0,'done');a.r(0,8,0,8,2);a.r(0x21,8,28,8)
    a.lw(9,8,GPO(-23024));a.lw(10,8,GPO(-23016));a.lw(11,28,-23008);a.r(0x21,11,11,9);a.branch(5,11,10,'done')
    a.lw(11,28,-23000);a.r(0x2B,12,11,9);a.branch(5,12,0,'done');a.r(0x21,12,11,17);a.addiu(12,12,64)
    a.r(0x2B,13,12,11);a.branch(5,13,0,'done');a.r(0x2B,13,10,12);a.branch(5,13,0,'done')
    a.call(A(0x100878));a.move(10,2);a.r(0x21,9,16,17)
    a.label('copy')
    for off in (0,8):a.i(55,11,16,off);a.i(63,11,10,off)
    a.addiu(16,16,16);a.addiu(10,10,16);a.branch(5,16,9,'copy');a.move(4,10);a.call(A(0x100890))
    a.label('done');guard.restore(a);a.jr();return a.finish()

def member_code():
    import tag_tournament as tour
    a=Assembler(MEMBER);guard.save(a)
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done')
    a.li(8,mode_menu.SCENE_MANAGER);a.lw(8,8);guard.pointer(a,8,0x20)
    a.lw(9,8,0x18);a.addiu(10,0,35);a.branch(4,9,10,'tournament')
    a.addiu(10,0,40);a.branch(5,9,10,'done')
    a.i(11,9,4,2);a.branch(4,9,0,'done');a.i(11,9,5,5);a.branch(4,9,0,'done')
    a.li(8,guard.CONTROL);a.lw(9,8);a.li(10,guard.MAGIC);a.branch(5,9,10,'done');a.lw(9,8,guard.CHOICE);a.branch(4,9,0,'done')
    a.r(0,8,0,5,1);a.r(0x21,8,8,4);a.r(0,8,0,8,2);a.li(9,LEVELS);a.r(0x21,8,8,9);a.jump('lookup')
    a.label('tournament')
    a.i(11,9,4,2);a.branch(4,9,0,'done');a.i(11,9,5,5);a.branch(4,9,0,'done')
    a.li(8,tour.CONTROL);a.lw(9,8);a.li(10,tour.MAGIC);a.branch(5,9,10,'done')
    a.li(8,tour.RUNTIME);a.lw(8,8);guard.pointer(a,8,0x4000)
    a.lw(9,8,tour.OBJ_ROW);a.i(11,10,9,16);a.branch(4,10,0,'done')
    a.r(0,9,0,9,4);a.r(0x21,9,9,8);a.i(37,10,9,tour.OBJ_ROWS+2);a.i(37,11,9,tour.OBJ_ROWS+4)
    for r in (10,11):a.i(11,12,r,17);a.branch(4,12,0,'done')
    a.r(0,12,0,10,5);a.r(0,13,0,10,3);a.r(0x21,12,12,13);a.r(0x21,12,12,8)
    a.i(37,12,12,tour.OBJ_ENTRANTS);a.i(12,12,12,tour.HUMAN)
    a.branch(5,12,0,'sides_ready');a.move(12,10);a.move(10,11);a.move(11,12)
    a.label('sides_ready');a.branch(4,4,0,'entrant');a.move(10,11);a.label('entrant')
    a.r(0,8,0,10,2);a.r(0x21,8,8,10);a.r(0x21,8,8,5);a.r(0,8,0,8,2)
    a.li(9,TOUR_LEVELS);a.r(0x21,8,8,9)
    a.label('lookup');a.lw(4,8);a.branch(4,4,0,'done')
    a.addiu(4,4,-1);a.i(11,9,4,5);a.branch(4,9,0,'done');a.call(A(0x261738))
    # o32 EE call: the sixth integer argument is t1 (register 9).
    a.sw(2,29,guard.REGS.index(9)*16)
    a.label('done');guard.restore(a);a.jump(OLD_MEMBER);b=a.finish();assert MEMBER+len(b)<=OLD_MEMBER;return b

def code_pieces():
    read=elf_reader(elf_path(ROOT))[2];original=read(ENTRY,8)
    a=Assembler(OLD_MEMBER);a.words.extend(struct.unpack('<2I',original));a.jump(ENTRY+8)
    table=bytearray();offset=DATA;images=packets()
    for image in images:table.extend(struct.pack('<2I',offset,len(image)));offset+=len(image)
    return [(INPUT,input_code()),(DRAW,draw_code()),(MEMBER,member_code()),(OLD_MEMBER,a.finish()),
            (ENTRY,struct.pack('<2I',0x08000000|(MEMBER>>2),0)),(TABLE,bytes(table)),(DATA,b''.join(images))]
