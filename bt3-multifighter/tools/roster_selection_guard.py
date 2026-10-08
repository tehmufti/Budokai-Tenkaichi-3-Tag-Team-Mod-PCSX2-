"""Refuse an incomplete two-human co-op roster at native Team Select Done.

Called by the cold-boot native menu pad wrapper before the scene dispatches
translated input. a0 is the original pad caller, not this helper's return RA.
Only co-op's left Done confirmation is consumed; the stock menu continues to
own all selection, navigation, opposite-team counts and completion behavior.
"""
from native_map import A
from prototype import Assembler
from regional import MENU_ACCEPT
import mode_menu

CODE,END=0x07698000,0x0769E000
CONTROL,MAGIC,CHOICE=0x076FF000,0x324D4E42,60
TEAM_OBJECT,CALLER=A(0x3B38D8),A(0x351580)
SOUND=A(0x124F68)
# Runtime overlay proof: Team Select pad caller, state-6 dispatch, Done count
# predicate and stock rejection sound. No scene-overlay instructions patched.
SIGNATURES={A(0x351578):0x0C000000|(A(0x122A38)>>2),A(0x35157C):0,
            A(0x3B42A8):A(0x00350168),A(0x3505D0):0x8C420134,
            A(0x3505D4):0x1040030E,A(0x351214):0x0C000000|(A(0x124F68)>>2),
            A(0x351218):0x24050007}
REGS=tuple(range(1,29))+(30,31)
STACK=0x300


def save(a):
    a.addiu(29,29,-STACK)
    for i,r in enumerate(REGS):a.i(31,r,29,i*16)
    for r in range(32):a.i(57,r,29,0x200+r*4)
    a.emit((17<<26)|(2<<21)|(8<<16)|(31<<11));a.sw(8,29,0x280)
    a.r(16,8,0);a.i(63,8,29,0x290)
    a.r(18,8,0);a.i(63,8,29,0x298)


def restore(a):
    a.lw(8,29,0x280);a.emit((17<<26)|(6<<21)|(8<<16)|(31<<11))
    a.i(55,8,29,0x290);a.r(17,0,8)
    a.i(55,8,29,0x298);a.r(19,0,8)
    for r in range(32):a.i(49,r,29,0x200+r*4)
    for i,r in enumerate(REGS):a.i(30,r,29,i*16)
    a.addiu(29,29,STACK)


def pointer(a,reg,size):
    a.i(12,9,reg,3);a.branch(5,9,0,'done')
    a.li(9,0x100000);a.r(0x2B,9,reg,9);a.branch(5,9,0,'done')
    a.li(9,0x2000000-size);a.r(0x2B,9,9,reg);a.branch(5,9,0,'done')


def payload():
    a=Assembler(CODE)
    # The hot main/battle pad path pays only a caller check and three temporary
    # saves, not a complete context save for this rare co-op menu condition.
    a.addiu(29,29,-0x30)
    for i,r in enumerate((8,9,10)):a.i(31,r,29,i*16)
    a.li(8,CALLER);a.branch(5,4,8,'quick_done')
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'quick_done')
    a.lw(9,8,CHOICE)
    for choice in (4,7,10,11,12,13,14,15,16,17,18,19,20,21):a.addiu(10,0,choice);a.branch(4,9,10,'coop_choice')
    a.jump('quick_done');a.label('coop_choice')
    for i,r in enumerate((8,9,10)):a.i(30,r,29,i*16)
    a.addiu(29,29,0x30);a.jump('inspect')
    a.label('quick_done')
    for i,r in enumerate((8,9,10)):a.i(30,r,29,i*16)
    a.addiu(29,29,0x30);a.jr()
    a.label('inspect');save(a)
    a.li(8,mode_menu.SCENE_MANAGER);a.lw(8,8);pointer(a,8,0x20)
    a.lw(9,8,0x18);a.addiu(10,0,40);a.branch(5,9,10,'done')
    for p,word in SIGNATURES.items():
        a.li(8,p);a.lw(9,8);a.li(10,word);a.branch(5,9,10,'done')
    a.li(8,TEAM_OBJECT);a.lw(11,8);pointer(a,11,0x3F00)
    a.lw(9,11,0x3C);a.i(12,9,9,2);a.branch(4,9,0,'done')
    # Native loops side = pad + active_side. Left always belongs to pad zero;
    # a one-pad selector on the right must be left alone, as must pad one.
    a.lw(14,11,0x3C58);a.i(11,9,14,2);a.branch(4,9,0,'done')
    a.li(8,CONTROL);a.lw(13,8,CHOICE)
    for choice in (7,10,12,13,15,17,18,20):a.addiu(9,0,choice);a.branch(4,13,9,'side_ready')
    a.branch(5,14,0,'done')
    a.label('side_ready')
    a.lw(9,11,0x3C38);a.i(11,9,9,3);a.branch(4,9,0,'done')
    a.r(0,9,0,14,2);a.r(0x21,9,9,11);a.lw(12,9,0x8E8);pointer(a,12,0x200)
    a.lw(9,12,0x13C);a.addiu(10,0,6);a.branch(5,9,10,'done')
    a.lw(9,12,0x12C);a.addiu(10,0,5);a.branch(5,9,10,'done')
    a.addiu(15,0,2)
    import team_assignment as assignment
    a.lw(9,8,assignment.VALID);a.addiu(10,0,1);a.branch(5,9,10,'legacy_assignment')
    for choice in assignment.CHOICES:
        a.addiu(9,0,choice);a.branch(4,13,9,'assigned')
    a.jump('legacy_assignment');a.label('assigned');a.addiu(15,0,1)
    for seat in range(4):
        a.lw(9,8,assignment.SEATS+4*seat);a.i(11,10,9,10);a.branch(4,10,0,f'assigned_next{seat}')
        a.i(12,10,9,1);a.branch(5,10,14,f'assigned_next{seat}')
        a.r(3,9,0,9,1);a.addiu(9,9,1);a.r(0x2B,10,15,9);a.branch(4,10,0,f'assigned_next{seat}')
        a.move(15,9);a.label(f'assigned_next{seat}')
    a.jump('count_ready');a.label('legacy_assignment')
    # Legacy opposing two-pad matches have no shared assignment receipt.
    for choice in (7,10):a.addiu(9,0,choice);a.branch(4,13,9,'done')
    for choice in (17,20):a.addiu(9,0,choice);a.branch(4,13,9,'three_teams')
    for choice in (19,21):a.addiu(9,0,choice);a.branch(4,13,9,'three_allies')
    a.addiu(9,0,18);a.branch(4,13,9,'three_ffa')
    for choice in (14,16):a.addiu(9,0,choice);a.branch(4,13,9,'four_allies')
    a.addiu(9,0,13);a.branch(5,13,9,'count_ready')
    # FFA can distribute the four humans across either selection column.
    a.addiu(15,0,4);a.jump('ffa_total')
    a.label('three_ffa');a.addiu(15,0,3)
    a.label('ffa_total');a.branch(4,14,0,'done');a.lw(10,11,0x8E8);pointer(a,10,0x200)
    a.lw(10,10,0x134);a.r(0x23,15,15,10);a.branch(6,15,0,'done');a.jump('count_ready')
    a.label('three_teams');a.r(0x23,15,15,14);a.jump('count_ready')
    a.label('three_allies');a.addiu(15,0,3);a.jump('count_ready')
    a.label('four_allies');a.addiu(15,0,4)
    a.label('count_ready');a.lw(9,12,0x134);a.r(0x2B,9,9,15);a.branch(4,9,0,'done')
    a.li(11,mode_menu.PAD);a.lw(9,11,0x18C);a.i(12,10,9,MENU_ACCEPT)
    a.branch(4,10,0,'done');a.li(10,0xFFFFFFFF&~MENU_ACCEPT);a.r(0x24,9,9,10);a.sw(9,11,0x18C)
    a.addiu(4,0,1);a.addiu(5,0,7);a.call(SOUND)
    a.label('done');restore(a);a.jr()
    data=a.finish();assert len(data)<END-CODE;return data


def code_pieces():return [(CODE,payload())]
