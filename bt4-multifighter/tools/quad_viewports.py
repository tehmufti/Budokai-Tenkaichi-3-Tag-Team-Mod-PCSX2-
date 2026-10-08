"""Three/four-view render integration for prepared multiplayer matches.

Each pair reuses the game's two visibility/matrix caches after the prior pair
has submitted its packets. The simulation and cinematic clock still tick once.
Input and actor ownership are installed separately by four_player_mode.
"""
from native_map import A, elf_path
import struct
from prototype import Assembler,ROOT,elf_reader
import fresh_team_combat as core
import battle_mode_policy as modes
import viewport_hud as hud
import cinematic_policy as cinema
import fresh_team_camera as follow
from regional import DISPLAY_H, SCISSOR_Y1, Y_ORIGIN

BASE,END=0x06C00000,0x06C10000
DRAW,SELECT,ONCE,PREPARE=BASE,BASE+0x1000,BASE+0x1800,BASE+0x2000
SCISSOR=BASE+0x3000
TAILS,CAMERAS,CONTROL=BASE+0x4000,BASE+0x5000,BASE+0xF000
BACKUP=BASE+0x7000
STAGE=BASE+0x8000
CACHE_VIEW,CACHE_PAIR=BASE+0x9000,BASE+0x9400
MATTE=BASE+0x9800
# Exact unrolled copies of the native ordering-table reset and link. Each
# native entry jumps to its copy for good (no TAILS); the bodies must be native.
OT_RESET,OT_LINK=BASE+0xA000,BASE+0xA400
OT_ROUTINES=((A(0x102610),A(0x10263C),OT_RESET),(A(0x102688),A(0x102708),OT_LINK))
OT_FIRST,OT_LAST=-0x59CC,-0x59C8
VIEW_COUNT=36
# Private render-only copies: the native two-cache pause shortcut cannot be
# used when four cameras share those caches. Never clear the global pause bit.
CACHE_ROUTINES=((A(0x24AD08),A(0x24ADF8),A(0x24AD34),CACHE_VIEW),
                (A(0x24ADF8),A(0x24AF18),A(0x24AE24),CACHE_PAIR))
MAGIC=0x51564131
SUBJECTS=CONTROL+0x40
# Rows of the split: USA 0..222 / 225..447 of a 448-line frame; European 0..254 / 257..511 of 512 lines.
TOP_LAST, BOTTOM_FIRST = (DISPLAY_H//2-2, DISPLAY_H//2+1)
RECTS=((0,254,0,TOP_LAST),(257,511,0,TOP_LAST),(0,254,BOTTOM_FIRST,SCISSOR_Y1),(257,511,BOTTOM_FIRST,SCISSOR_Y1))
THREE_RECTS=RECTS[:2]+((128,382,BOTTOM_FIRST,SCISSOR_Y1),)
TWO_RECTS=((0,254,0,SCISSOR_Y1),(257,511,0,SCISSOR_Y1))


def rectangles(humans):return {2:TWO_RECTS,3:THREE_RECTS,4:RECTS}[humans]
NATIVE=elf_reader(elf_path(ROOT))[2]
SAVED=tuple(range(2,28))+(30,31)


def jump(at):return struct.pack('<2I',(2<<26)|(at>>2),0)


def save(a):
    a.addiu(29,29,-0x160)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0x100+i*4)


def restore(a,skip=()):
    for i in range(12):a.i(49,20+i,29,0x100+i*4)
    for i,r in enumerate(SAVED):
        if r not in skip:a.i(55,r,29,i*8)
    a.addiu(29,29,0x160)


def gate(a,fail):
    core.gate(a,fail);a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail);a.lw(9,8,12);a.branch(4,9,0,fail)


def draw(extensions=()):
    """extensions: viewport_hud.hud_extensions entries (guarded caption calls after each view's revival call).
    With none, the same bytes as before."""
    a=Assembler(DRAW);save(a);gate(a,'native')
    # Keep stock intro/results and checked shared cinematics in their native
    # renderer. Free-action specials retain all four independent viewports.
    cinema.gate(a,'native',combat=False)
    # Phase 1 owns dialogue. Phase 2 is READY/FIGHT and already uses ordinary
    # fighter cameras: publish every viewport before controls are released.
    a.lw(9,11);a.addiu(8,9,-2);a.i(11,8,8,2);a.branch(4,8,0,'native')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'native')
    a.addiu(8,0,2);a.branch(4,9,8,'quad')
    import multiplayer_fusion as fusion
    a.li(8,fusion.CONTROL);a.lw(9,8);a.li(10,fusion.MAGIC);a.branch(5,9,10,'shared_cinematic')
    a.call(fusion.SHARED);a.branch(5,2,0,'native')
    a.call(fusion.PRESENTATION);a.branch(5,2,0,'quad');a.label('shared_cinematic')
    cinema.shared_owner(a,'quad','quad_draw',bounded=True);a.jump('native')
    a.label('quad');a.li(16,CONTROL)
    a.lw(8,28,-22172);a.lw(9,8,3136);a.sw(9,16,28)
    a.lw(9,28,-22176);a.sw(9,16,32)
    a.addiu(8,8,1824);a.li(9,BACKUP);copy_words(a,8,9,2*656,'backup')
    for view in range(4):
        a.lw(8,16,VIEW_COUNT);a.i(11,9,8,view+1);a.branch(5,9,0,'prepared')
        a.addiu(4,0,view);a.call(PREPARE)
    a.label('prepared')

    def omit_fourth(tag):
        a.lw(8,16,VIEW_COUNT);a.addiu(9,0,3);a.branch(5,8,9,tag+'_keep')
        a.branch(5,17,0,tag);a.label(tag+'_keep')

    def draw_layer(routine,tag):
        a.addiu(4,0,2);a.lw(8,16,VIEW_COUNT);a.addiu(9,0,3);a.branch(5,8,9,tag)
        a.branch(4,17,0,tag);a.addiu(4,0,1);a.label(tag);a.call(routine)

    def pair_pass(tag,body):
        a.move(17,0);a.label(tag);a.move(4,17);a.call(STAGE)
        body()
        a.addiu(17,17,1);a.lw(8,16,VIEW_COUNT);a.addiu(8,8,1);a.r(3,8,0,8,1);a.branch(5,17,8,tag)

    def backgrounds():
        for side in range(2):
            if side:omit_fourth('background_done')
            a.addiu(4,0,side);a.call(A(0x23EF98));a.addiu(4,0,1);a.call(A(0x23EFD0))
            a.lw(4,28,-22176);a.call(A(0x115950))
            a.lw(4,28,-22176);a.call(A(0x115DE0))
        a.label('background_done')

    pair_pass('backgrounds',backgrounds)
    a.sw(0,16,16);a.call(A(0x247578))
    # Native 10FF40 is a layered renderer, not an independent viewport draw.
    # Submit all four opaque views before its full-frame postprocessing once.
    a.addiu(4,0,2);a.call(A(0x2490F8));a.branch(4,2,0,'effects')
    a.li(4,0xFFFFFF);a.li(5,0xFF000000);a.call(A(0x102120));a.call(A(0x2493A0))
    pair_pass('opaque',lambda:draw_layer(A(0x10FB80),'opaque_count'))
    a.sw(0,16,16);a.call(A(0x24B118))
    a.addiu(4,0,8);a.call(A(0x2490F8));a.branch(4,2,0,'translucent')
    pair_pass('detail',lambda:draw_layer(A(0x10FC50),'detail_count'))
    a.label('translucent')
    pair_pass('translucent_pair',lambda:draw_layer(A(0x10FD98),'translucent_count'))
    a.sw(0,16,16);a.call(A(0x111E50))
    a.label('effects');a.call(A(0x1021D8))
    def effects():
        for side in range(2):
            if side:omit_fourth('effects_done')
            a.addiu(4,0,side);a.call(A(0x23EF98));a.addiu(4,0,1);a.call(A(0x23EFD0))
            a.addiu(4,0,int(side==0));a.call(A(0x12CCD0));a.call(A(0x102708))
            # Revival rings use world projection and must be submitted while
            # each actual camera is bound, rather than once after the last view.
            import teammate_revive as revive
            a.li(8,revive.CONTROL);a.lw(9,8);a.li(10,revive.MAGIC)
            a.branch(5,9,10,f'no_revive{side}');a.call(revive.DRAW);a.label(f'no_revive{side}')
            hud.extension_calls(a,extensions,f'no_extension{side}_')
        a.label('effects_done')
    pair_pass('world_effects',effects)
    a.sw(0,16,16);a.call(A(0x247688))
    a.lw(8,16,VIEW_COUNT);a.addiu(9,0,3);a.branch(5,8,9,'no_matte');a.call(MATTE);a.label('no_matte')
    # Menus, HUD, fades and flash cleanup are once per complete frame.
    for routine in (A(0x2129C8),A(0x23A2B8),A(0x2476D8)):a.call(routine)
    a.li(8,fusion.CONTROL);a.lw(9,8);a.li(10,fusion.MAGIC);a.branch(5,9,10,'no_fusion_caption')
    a.call(fusion.DRAW);a.label('no_fusion_caption')
    a.sw(0,16,16);a.lw(8,16,24);a.addiu(8,8,1);a.sw(8,16,24)
    a.li(8,BACKUP);a.lw(9,28,-22172);a.addiu(9,9,1824);copy_words(a,8,9,2*656,'restore')
    a.lw(8,28,-22172);a.lw(9,16,28);a.sw(9,8,3136)
    a.lw(4,16,32);a.addiu(5,0,1);a.call(A(0x23E6A0))
    restore(a);a.move(2,0);a.jr()
    a.label('native');restore(a);a.jump(TAILS);return a.finish()


def stage():
    """Rebind one pair's native camera/visibility caches for the next layer."""
    a=Assembler(STAGE);save(a);a.move(17,4);a.li(16,CONTROL)
    a.sw(17,16,20);a.addiu(8,0,1);a.sw(8,16,16)
    for side in range(2):
        if side:
            a.lw(8,16,VIEW_COUNT);a.addiu(9,0,3);a.branch(5,8,9,'stage_both')
            a.branch(5,17,0,'stage_pair');a.label('stage_both')
        a.r(0,8,0,17,11);a.li(9,CAMERAS+side*1024);a.r(0x2D,8,8,9)
        a.lw(9,28,-22172);a.addiu(9,9,1824+656*side);copy_words(a,8,9,656,f'stage{side}')
        a.addiu(4,0,side);a.call(A(0x23EF98));a.move(4,0);a.call(A(0x23EFD0))
        a.addiu(4,0,side);a.call(CACHE_VIEW)
    a.label('stage_pair');a.addiu(4,0,1)
    a.lw(8,16,VIEW_COUNT);a.addiu(9,0,3);a.branch(5,8,9,'pair_ready')
    a.branch(4,17,0,'pair_ready');a.move(4,0)
    a.label('pair_ready');a.call(CACHE_PAIR)
    restore(a);a.jr();return a.finish()


def cache_builders():
    out=[]
    for start,end,pause,dest in CACHE_ROUTINES:
        blob=bytearray(NATIVE(start,end-start))
        if struct.unpack_from('<I',blob,pause-start)[0]!=0x30630100:
            raise ValueError('Native visibility pause guard changed')
        # ANDI v1,v1,0, leaving the function and all its call conventions intact.
        struct.pack_into('<I',blob,pause-start,0x30630000)
        for i,(word,) in enumerate(struct.iter_unpack('<I',blob)):
            op=word>>26;pc=start+i*4
            if op in (1,4,5,6,7,20,21,22,23):
                relative=struct.unpack('<h',struct.pack('<H',word&0xFFFF))[0]
                if not start<=pc+4+4*relative<end:
                    raise ValueError('Visibility clone has an external relative branch')
            elif op in (2,3):
                target=((pc+4)&0xF0000000)|((word&0x3FFFFFF)<<2)
                if start<=target<end:
                    struct.pack_into('<I',blob,i*4,(op<<26)|((dest+target-start)>>2))
        out.append((dest,bytes(blob)))
    return out


def select():
    a=Assembler(SELECT);a.jump(TAILS+0x20);return a.finish()


def copy_words(a,src,dst,size,tag):
    a.addiu(10,src,size);a.label(tag)
    a.i(55,11,src,0);a.i(55,12,src,8);a.i(63,11,dst,0);a.i(63,12,dst,8)
    a.addiu(src,src,16);a.addiu(dst,dst,16);a.branch(5,src,10,tag)


def once():
    a=Assembler(ONCE);save(a);gate(a,'native');a.lw(9,8,16);a.branch(4,9,0,'native')
    a.lw(9,8,20);a.branch(4,9,0,'native');restore(a);a.jr()
    a.label('native');restore(a);a.jump(TAILS+0x40);return a.finish()


def prepare():
    a=Assembler(PREPARE);save(a);a.move(16,4)
    a.r(0,8,0,16,10);a.li(17,CAMERAS);a.r(0x2D,17,17,8)
    a.lw(8,28,-22172);a.move(9,17);a.addiu(10,8,608)
    a.label('copy');a.i(55,11,8,0);a.i(55,12,8,8);a.i(63,11,9,0);a.i(63,12,9,8)
    a.addiu(8,8,16);a.addiu(9,9,16);a.branch(5,8,10,'copy')
    # Quarter-screen views scale both axes equally. A two-player vertical
    # split is a full-height crop, like the native side cameras: halving only
    # X squeezes fighters and scenery horizontally (especially visible 4:3).
    a.li(8,CONTROL);a.lw(8,8,VIEW_COUNT);a.addiu(9,0,2);a.branch(4,8,9,'scaled')
    a.li(8,0x3F000000);a.emit((17<<26)|(4<<21)|(8<<16)|(1<<11))
    for off in (568,572):
        a.i(49,0,17,off);a.emit((17<<26)|(16<<21)|(1<<16)|2);a.i(57,0,17,off)
    a.label('scaled')
    for view,rect in enumerate(RECTS):
        a.addiu(8,0,view);a.branch(5,16,8,f'next{view}')
        for off,value in zip((512,516,520,524),rect):a.li(8,value);a.sw(8,17,off)
        # Projection centre of the quarter (x 1920/2176; y USA 1936/2160, European 1920/2176) and the
        # first quarter's centre less one (y USA 1935.0, European 1919.0).
        for off,value in ((528,1919.0),(532,float(Y_ORIGIN+DISPLAY_H//4-1)),(576,1920.+256*(view&1)),
                          (580,float(Y_ORIGIN+DISPLAY_H//4+DISPLAY_H//2*(view>>1)))):
            a.li(8,struct.unpack('<I',struct.pack('<f',value))[0]);a.sw(8,17,off)
        if view==2:
            a.li(8,CONTROL);a.lw(8,8,VIEW_COUNT);a.addiu(9,0,3);a.branch(5,8,9,'project')
            for off,value in ((512,128),(516,382),(576,0x45000000)):
                a.li(8,value);a.sw(8,17,off)
        if view<2:
            a.li(8,CONTROL);a.lw(8,8,VIEW_COUNT);a.addiu(9,0,2);a.branch(5,8,9,'project')
            for off,value in ((524,SCISSOR_Y1),(532,0x44FFE000),(580,0x45000000)):
                a.li(8,value);a.sw(8,17,off)
        a.jump('project');a.label(f'next{view}')
    a.label('project');a.addiu(8,0,1);a.sw(8,17,640);a.i(12,8,16,1);a.sw(8,17,644)
    a.move(4,17);a.call(A(0x23E040))
    a.li(8,SUBJECTS);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(9,8)
    a.li(8,core.POINTERS);a.r(0,9,0,9,2);a.r(0x2D,8,8,9);a.lw(18,8)
    a.lw(4,18,12);a.addiu(5,17,608);a.addiu(6,17,624);a.call(A(0x207DD0))
    a.lw(4,18,12);a.call(A(0x207E78));a.sw(2,17,648)
    # Reuse the proven participant policy with a temporary view-zero subject;
    # this is render-local and never transfers input or spectator ownership.
    a.li(8,follow.SUCCESSOR_CONTROL);a.lw(19,8,8);a.lw(9,18);a.sw(9,8,8)
    import multiplayer_fusion as fusion
    a.move(20,0);a.li(8,fusion.CONTROL);a.lw(9,8);a.li(10,fusion.MAGIC);a.branch(5,9,10,'ordinary_cinema')
    a.lw(4,18);a.call(fusion.CINEMATIC);a.move(20,2);a.branch(5,20,0,'cinema_ready')
    a.label('ordinary_cinema');a.move(4,0);a.call(cinema.VIEW);a.move(20,2)
    a.label('cinema_ready');a.li(8,follow.SUCCESSOR_CONTROL);a.sw(19,8,8)
    a.branch(4,20,0,'follow')
    a.lw(20,28,-22180);a.branch(4,20,0,'follow')
    a.move(8,20);a.move(9,17);copy_words(a,8,9,0x80,'authored_view')
    a.move(4,17);a.addiu(5,20,544);a.call(A(0x23E598));a.jump('done')
    a.label('follow');a.move(4,17);a.move(5,0);a.call(A(0x23EAD0))
    a.label('done')
    restore(a);a.jr();return a.finish()


def scissor():
    a=Assembler(SCISSOR);save(a);gate(a,'native');a.lw(9,8,16);a.branch(4,9,0,'native')
    a.lw(9,8,VIEW_COUNT);a.addiu(11,0,2);a.branch(4,9,11,'native')
    a.lw(9,8,20);a.branch(5,9,0,'bottom')
    a.addiu(8,0,TOP_LAST);a.r(0x2B,9,8,7);a.branch(4,9,0,'native');a.i(63,8,29,SAVED.index(7)*8);a.jump('native')
    a.label('bottom');a.addiu(8,0,BOTTOM_FIRST);a.r(0x2B,9,6,8);a.branch(4,9,0,'bottom_x');a.i(63,8,29,SAVED.index(6)*8)
    a.label('bottom_x')
    a.li(8,CONTROL);a.lw(9,8,VIEW_COUNT);a.addiu(8,0,3);a.branch(5,9,8,'native')
    # Clamp the centered third view's horizontal scissor as well as its row.
    a.addiu(8,0,128);a.r(0x2B,9,4,8);a.branch(4,9,0,'right_clip');a.i(63,8,29,SAVED.index(4)*8)
    a.label('right_clip');a.addiu(8,0,382);a.r(0x2B,9,8,5);a.branch(4,9,0,'native');a.i(63,8,29,SAVED.index(5)*8)
    a.label('native');restore(a);a.jump(TAILS+0x60);return a.finish()


def matte():
    """Clear unused lower corners explicitly so prior frames cannot leak in."""
    import guest_healthbars as bars
    a=Assembler(MATTE);save(a)
    for reg,value in ((4,0),(5,511),(6,0),(7,SCISSOR_Y1)):a.addiu(reg,0,value)
    a.call(A(0x101400))
    for left,right in ((0,128),(383,512)):
        for reg,value in ((4,(1792+left)*16),(5,(Y_ORIGIN+BOTTOM_FIRST)*16),(6,(1792+right)*16),(7,(Y_ORIGIN+DISPLAY_H)*16),(8,0x80000000)):
            a.li(reg,value)
        a.call(bars.RECT)
    restore(a);a.jr();return a.finish()


def filled(a,op,rs,rt,label,delay):
    """Branch whose delay slot executes delay(), which emits one word."""
    a.branch(op,rs,rt,label);a.words.pop();size=len(a.words);delay()
    assert len(a.words)==size+1


def ot_reset():
    """Native 102610 (copy each head into its tail), four entries per pass.

    The words read and written are the native ones and they are distinct, so
    the order inside a pass cannot change memory. Only the native registers
    change, to the native final values: v0=1, a0 past the table, v1=a0+4 and
    a1=0 after a positive count. Every loop is at least seven words, like the
    padded native one, so the R5900 short-loop erratum cannot apply.
    """
    a=Assembler(OT_RESET)
    filled(a,6,5,0,'done',lambda:a.addiu(3,4,4))
    a.addiu(5,5,-4);a.branch(1,5,0,'rest')
    a.label('four')
    for off in (0,16):
        a.lw(2,4,off);a.lw(3,4,off+8);a.sw(2,4,off+4);a.sw(3,4,off+12)
    a.addiu(5,5,-4);filled(a,1,5,1,'four',lambda:a.addiu(4,4,32))
    a.label('rest');a.addiu(5,5,4)
    for _ in range(3):
        a.branch(4,5,0,'done')
        a.lw(2,4,0);a.addiu(5,5,-1);a.sw(2,4,4);a.addiu(4,4,8)
    a.label('done');a.addiu(3,4,4);a.r(8,0,31);a.addiu(2,0,1)
    return a.finish()


def ot_link():
    """Native 102688 (chain the non-empty buckets), two entries per pass.

    The native code has two loops: before the chain has a non-zero first head
    it only records first/last, afterwards it links last+4 to each head. Both
    are kept as separate phases with the native loads and stores in the
    native order, and the final entry runs the native final iteration, so
    memory and v0/v1/a0/a2 end exactly as native even if tags alias the table.
    a1 (the count) is only read; no other register is touched.
    """
    a=Assembler(OT_LINK);first,last=OT_FIRST,OT_LAST
    a.sw(0,28,first);a.move(6,0);filled(a,6,5,0,'return',lambda:a.sw(0,28,last))
    # a2 = pairs among the count-1 entries before the final one.
    a.addiu(6,5,-1);a.r(2,6,0,6,1);a.branch(4,6,0,'first_odd')
    for phase in ('first','link'):
        a.label(f'{phase}_pair');a.lw(2,4,4);a.lw(3,4,0);a.branch(5,2,3,f'{phase}_0')
        a.label(f'{phase}_back0');a.lw(2,4,12);a.lw(3,4,8)
        filled(a,5,2,3,f'{phase}_1',lambda:a.addiu(6,6,-1))
        a.label(f'{phase}_back1');filled(a,5,6,0,f'{phase}_pair',lambda:a.addiu(4,4,16))
        # An even count leaves one more entry before the final one.
        a.label(f'{phase}_odd');a.i(12,2,5,1);a.branch(5,2,0,f'{phase}_final')
        a.lw(2,4,4);a.lw(3,4,0);filled(a,5,2,3,f'{phase}_2',lambda:a.addiu(4,4,8))
        a.label(f'{phase}_final')
        if phase=='first':
            a.lw(3,4,4);a.lw(2,4,0);a.branch(4,3,2,'first_done')
            a.sw(3,28,last);a.lw(2,4,0);a.sw(2,28,first)
            a.label('first_done');a.addiu(4,4,8);a.move(6,5);a.r(8,0,31);a.move(2,0)
            for tag,off,back in (('0',0,'back0'),('1',8,'back1'),('2',-8,'final')):
                a.label(f'first_{tag}');a.sw(2,28,last);a.lw(3,4,off);a.sw(3,28,first)
                a.branch(5,3,0,f'link_{back}');a.branch(4,0,0,f'first_{back}')
        else:
            a.lw(2,4,4);a.lw(3,4,0);filled(a,4,2,3,'link_done',lambda:a.lw(2,28,last))
            a.sw(3,2,4);a.lw(3,4,4);a.sw(3,28,last)
            a.label('link_done');a.addiu(4,4,8);a.r(8,0,31);a.move(6,0)
            for tag,off,back in (('0',0,'back0'),('1',8,'back1'),('2',-8,'final')):
                a.label(f'link_{tag}');a.lw(2,28,last);a.sw(3,2,4);a.lw(3,4,off+4)
                filled(a,4,0,0,f'link_{back}',lambda:a.sw(3,28,last))
    a.label('return');a.jr()
    return a.finish()


def pieces(extensions=()):
    out=[(DRAW,draw(extensions)),(SELECT,select()),(ONCE,once()),(PREPARE,prepare()),(SCISSOR,scissor()),(STAGE,stage()),(MATTE,matte())]+cache_builders()
    out.extend(((OT_RESET,ot_reset()),(OT_LINK,ot_link())))
    for i,(hook,entry) in enumerate(((A(0x12B9C0),DRAW),(A(0x23EF98),SELECT),(A(0x13A388),ONCE),(A(0x101400),SCISSOR))):
        old=NATIVE(hook,8)
        assert not any(w>>26 in (1,2,3,4,5,6,7) for w in struct.unpack('<2I',old))
        out.extend(((hook,jump(entry)),(TAILS+32*i,old+jump(hook+8))))
    out.extend((start,jump(entry)) for start,_,entry in OT_ROUTINES)
    spans=sorted((p,p+len(b)) for p,b in out)
    assert all(e<=s for (_,e),(s,_) in zip(spans,spans[1:]))
    return out


@modes.matching_install
def build_memory(ram,subjects=(0,1,2,3),diagnostic=False):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Quad views need a captured match')
    if len(subjects) not in (2,3,4) or any(not 0<=i<count for i in subjects):raise ValueError('Invalid multiview subjects')
    if len(set(subjects))!=len(subjects) and not diagnostic:raise ValueError('Distinct fighters required')
    if any(ram[BASE:END]):raise ValueError('Quad reservation occupied')
    data=pieces(hud.hud_extensions(ram))
    for start,end,_,_ in CACHE_ROUTINES:
        if ram[start:end]!=NATIVE(start,end-start):
            raise ValueError(f'Native visibility builder changed: {start:x}')
    for start,end,_ in OT_ROUTINES:
        if ram[start:end]!=NATIVE(start,end-start):
            raise ValueError(f'Native ordering-table routine changed: {start:x}')
    for p,b in data:
        if p<BASE and ram[p:p+len(b)]!=NATIVE(p,len(b)):raise ValueError(f'Native quad hook changed: {p:x}')
    data.extend(((CONTROL,struct.pack('<4I',MAGIC,manager,count,1)),(CONTROL+VIEW_COUNT,struct.pack('<I',len(subjects))),
                 (SUBJECTS,struct.pack('<4I',*(tuple(subjects)+(0xFFFFFFFF,)*(4-len(subjects)))))))
    if u(hud.CONTROL)==hud.MAGIC:
        rects=rectangles(len(subjects))
        views=b''.join(struct.pack('<6I',1,*rect,SUBJECTS+4*i) for i,rect in enumerate(rects))+bytes((4-len(subjects))*hud.VIEW_STRIDE)
        data.extend(((hud.VIEWS,views),(hud.CONTROL+12,struct.pack('<I',len(subjects)))))
    return dict(blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in data])
