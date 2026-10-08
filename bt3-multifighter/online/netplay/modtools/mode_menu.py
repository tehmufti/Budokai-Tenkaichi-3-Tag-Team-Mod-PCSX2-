"""Controller-operated mode selection drawn inside the game's main menu.

Only the audited USA main-menu pad caller can consume inputs. The host keeps
a short lease; without it the original menu remains usable. Choosing a match
uses the native Duel accept path, preserving its resource cleanup/fades.
"""
from native_map import A, elf_path
from regional import MENU_ACCEPT, RAW_ACCEPT, RAW_BACK
import struct
import time
from prototype import Assembler, ROOT, elf_reader

CODE, CONTROL, END = 0x07100000, 0x0710F000, 0x07110000
HOOK, MAGIC = A(0x122D8C), 0x554D5442
SCENE_MANAGER, MAIN_OBJECT, DUEL_OBJECT = A(0x2FF10C), A(0x3B0E80), A(0x3B38E8)
PAD, MAIN_CALLER, DUEL_CALLER = A(0x333800), A(0x336890), A(0x3560E0)
FIELDS = dict(magic=0,active=4,choice=8,result=12,lease=16,route=20,
              frames=24,caller=28,scene=32,epoch=36)
OPTIONS = ('TEAM BATTLE','FREE-FOR-ALL / 1 PLAYER','FREE-FOR-ALL / 2 PLAYERS',
           'CO-OP / 2 PLAYERS','FREE-FOR-ALL / ALL CPU','ORIGINAL GAME MENU')
# Choice -> (battle mode, human players). The all-CPU entry takes exactly the
# same native Duel route as the one-player free-for-all; what makes it an
# exhibition is the trainer's 'Cpu' controller mode, which marks both leaders
# computer controlled, and extras always are.
SELECTIONS = (('teams',1),('ffa',1),('ffa',2),('coop',2),('ffa',0),('teams',1))
TWO_PLAYER_CHOICE = 2      # the only entry that asks the native menu for two pads
RETURN_CHOICE = len(OPTIONS)-1  # ORIGINAL GAME MENU stays last; cancel selects it


def payload():
    a=Assembler(CODE);a.addiu(29,29,-0x50)
    for i,r in enumerate((8,9,10,11,12,13,14,15)):a.i(63,r,29,i*8)
    a.li(8,CONTROL);a.lw(9,29,0x50+0x18);a.sw(9,8,28)
    a.lw(10,8,24);a.addiu(10,10,1);a.sw(10,8,24)
    a.sw(0,8,32);a.li(10,SCENE_MANAGER);a.lw(10,10);a.li(11,0x100000)
    a.r(0x2B,11,10,11);a.branch(5,11,0,'return');a.li(11,0x1FFF000)
    a.r(0x2B,11,10,11);a.branch(4,11,0,'return');a.lw(10,10,0x18);a.sw(10,8,32)
    a.lw(10,8);a.li(11,MAGIC);a.branch(5,10,11,'return')
    a.lw(10,8,16);a.branch(4,10,0,'expired');a.addiu(10,10,-1);a.sw(10,8,16)
    a.li(10,DUEL_CALLER);a.branch(4,9,10,'duel_route')
    a.li(10,MAIN_CALLER);a.branch(5,9,10,'return')
    a.lw(10,8,32);a.addiu(11,0,4);a.branch(5,10,11,'return')
    a.lw(10,8,4);a.branch(4,10,0,'return')
    a.li(11,MAIN_OBJECT);a.lw(11,11);a.li(12,0x100000)
    a.r(0x2B,12,11,12);a.branch(5,12,0,'expired');a.li(12,0x1FFF000)
    a.r(0x2B,12,11,12);a.branch(4,12,0,'expired')
    a.lw(12,11,0x144);a.addiu(13,0,10);a.branch(5,12,13,'expired')
    a.li(12,PAD);a.sw(0,12,0x18C);a.sw(0,12,0x190)
    a.addiu(13,0,1);a.branch(5,10,13,'return')
    a.lw(10,11,0x18);a.i(12,10,10,2);a.branch(4,10,0,'return')
    a.lw(10,11,0x108);a.i(12,10,10,4);a.branch(4,10,0,'return')
    a.lw(13,12,0x150);a.lw(14,8,8)
    a.i(12,10,13,0x10);a.branch(4,10,0,'down')
    a.addiu(14,14,-1);a.branch(1,14,1,'store');a.addiu(14,0,RETURN_CHOICE);a.jump('store')
    a.label('down');a.i(12,10,13,0x40);a.branch(4,10,0,'accept')
    a.addiu(14,14,1);a.i(11,10,14,len(OPTIONS));a.branch(5,10,0,'store');a.move(14,0)
    a.label('store');a.sw(14,8,8)
    # The disc's back / accept buttons (USA and Europe: Triangle / Cross; Japan: Cross / Circle).
    a.label('accept');a.i(12,10,13,RAW_BACK);a.branch(4,10,0,'cross')
    a.addiu(14,0,RETURN_CHOICE);a.jump('commit')
    a.label('cross');a.i(12,10,13,RAW_ACCEPT);a.branch(4,10,0,'return')
    a.label('commit');a.addiu(10,14,1);a.sw(10,8,12);a.addiu(10,0,2);a.sw(10,8,4)
    a.lw(10,8,36);a.addiu(10,10,1);a.sw(10,8,36)
    a.addiu(10,0,RETURN_CHOICE);a.branch(4,14,10,'return')
    a.branch(4,14,0,'native_duel')
    a.addiu(10,0,450);a.sw(10,8,44)
    a.addiu(10,0,1);a.sw(10,8,20);a.sw(0,8,40)
    a.addiu(10,0,TWO_PLAYER_CHOICE);a.branch(5,14,10,'native_duel')
    a.addiu(10,0,1);a.sw(10,8,40)
    a.label('native_duel')
    # Select native Duel and let its normal acceptance code transition.
    a.sw(0,11,0x10C);a.addiu(10,0,2);a.sw(10,11,0x148)
    a.addiu(10,0,MENU_ACCEPT);a.sw(10,12,0x18C);a.jump('return')
    a.label('duel_route');a.lw(10,8,20);a.branch(4,10,0,'return')
    a.lw(11,8,32);a.addiu(12,0,38);a.branch(5,11,12,'return')
    a.lw(11,8,44);a.branch(4,11,0,'expired');a.addiu(11,11,-1);a.sw(11,8,44)
    a.li(11,DUEL_OBJECT);a.lw(11,11);a.li(12,0x100000);a.r(0x2B,12,11,12)
    a.branch(5,12,0,'expired');a.li(12,0x1FFF000);a.r(0x2B,12,11,12);a.branch(4,12,0,'expired')
    a.li(12,PAD);a.sw(0,12,0x18C);a.sw(0,12,0x190)
    # A pad pulse is only a request. Native movie/fade/busy gates run after
    # this hook and can discard it. Observe the actual phase and acceptance
    # record before advancing; retry on later ready frames if it was dropped.
    a.lw(13,11,0x128);a.addiu(14,0,1);a.branch(5,13,14,'route_ready')
    a.lw(13,11,0x110);a.lw(14,8,40);a.branch(5,13,14,'return')
    a.addiu(10,0,2);a.sw(10,8,20)
    a.lw(13,11,0x114);a.addiu(14,0,1);a.branch(5,13,14,'route_ready')
    a.lw(13,11,0x10C);a.i(12,13,13,2);a.branch(5,13,0,'route_done')
    # Native acceptance stage 2 waits for voice status 5. Covered menu
    # announcements are deliberately muted, so that status may never occur.
    # Use its ordinary Cross-to-skip branch and keep ownership until the
    # native exit flag, rather than abandoning the route at stage 1.
    a.lw(13,11,0x148);a.addiu(14,0,2);a.branch(5,13,14,'route_ready')
    a.li(13,SCENE_MANAGER);a.lw(13,13);a.lw(13,13,0x14)
    a.i(12,13,13,0x100);a.branch(5,13,0,'return');a.jump('route_accept')
    a.label('route_ready')
    a.li(13,SCENE_MANAGER);a.lw(13,13);a.lw(13,13,0x14)
    a.i(12,13,13,0x100);a.branch(5,13,0,'return')
    a.lw(13,11,0x148);a.branch(5,13,0,'return')
    a.lw(13,11,0x184);a.branch(5,13,0,'return')
    a.lw(13,11,0x1C);a.i(12,13,13,2);a.branch(4,13,0,'return')
    a.lw(13,11,0x10C);a.i(12,14,13,3);a.branch(5,14,0,'return')
    a.i(12,13,13,4);a.branch(4,13,0,'return')
    a.lw(13,11,0x128);a.addiu(14,0,1);a.branch(5,10,14,'team_kind')
    a.branch(5,13,0,'return');a.lw(14,8,40);a.sw(14,11,0x110)
    a.jump('route_accept')
    a.label('team_kind');a.addiu(14,0,2);a.branch(5,10,14,'return')
    a.addiu(14,0,1);a.branch(5,13,14,'return');a.sw(14,11,0x114)
    a.label('route_accept');a.addiu(10,0,MENU_ACCEPT);a.sw(10,12,0x18C);a.jump('return')
    a.label('route_done');a.sw(0,8,20);a.jump('return')
    a.label('expired');a.sw(0,8,4);a.sw(0,8,20)
    a.label('return')
    for i,r in enumerate((8,9,10,11,12,13,14,15)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x50)
    a.i(55,16,29,0);a.i(55,17,29,8);a.jump(HOOK+8)
    result=a.finish();assert len(result)<0x1000;return result


def code_pieces():
    native=elf_reader(elf_path(ROOT))[2]
    assert native(HOOK,8)==struct.pack('<2I',0xDFB00000,0xDFB10008)
    return [(CODE,payload()),(HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))]


def main_ready(p):
    manager=p.read_u32(SCENE_MANAGER)
    if not 0x100000<=manager<0x1FFF000 or p.read_u32(manager+0x18)!=4:return False
    obj=p.read_u32(MAIN_OBJECT)
    if not 0x100000<=obj<0x1FFF000:return False
    # Exact main-menu shape plus its English dialogue bundle signature.
    if p.read_u32(obj+0x144)!=10:return False
    resource=p.read_u32(A(0x2FF0D8))
    if not 0x100000<=resource<0x1FFF000:return False
    bundle=p.read_u32(resource)
    if not 0x100000<=bundle<0x1FFF000:return False
    # DBT begins with the string count and the first string offset.
    return p.read(bundle,8)==struct.pack('<2I',64,0x140)


def picture(choice):
    # The panel is drawn by loading_art in two layers; this is the flat composite.
    from loading_art import composite,menu_compose
    return composite(menu_compose(choice))


class Controller:
    def __init__(self):
        from guest_loading_screen import GuestLoadingScreen
        self.screen=GuestLoadingScreen();self.dismissed=False;self.active=False
        self.last_choice=None;self.mode='teams';self.humans=1;self.epoch=0

    def tick(self,p):
        state=struct.unpack('<10I',p.read(CONTROL,40))
        if self.active and state[0]==MAGIC and state[3]:
            if any(p.read(a,len(d))!=d for a,d in code_pieces()):raise ValueError('In-game menu code changed')
            choice=state[3]-1
            if choice not in range(len(OPTIONS)):raise ValueError('Invalid in-game mode selection')
            self.mode,self.humans=SELECTIONS[choice]
            self.epoch+=1;self.dismissed=True;self.screen.hide(client=p);self.active=False
            p.write_u32(CONTROL+4,0);p.write_u32(CONTROL+12,0)
            return dict(mode=self.mode,humans=self.humans,choice=choice)
        ready=main_ready(p)
        if not ready:
            if self.active:self.screen.hide(client=p);self.active=False
            if state[0]==MAGIC and state[5]:p.write_u32(CONTROL+16,180)
            self.dismissed=False
            return None
        if self.dismissed:return None
        if any(p.read(a,len(d))!=d for a,d in code_pieces()):return None
        if not self.active:
            p.write(CONTROL,struct.pack('<6I',MAGIC,1,0,0,180,0))
            self.active=True;self.last_choice=None;state=(MAGIC,1,0,0,180,0,0,0,0,0)
        p.write_u32(CONTROL+16,180)
        choice=state[2] if state[2]<len(OPTIONS) else 0
        if choice!=self.last_choice:
            # This method only publishes pixels. It does not control an OS UI.
            # A static rectangle picture: the fallback menu has no lights (spec 5.5).
            self.screen.show_picture(picture(choice),surface='menu',client=p)
            self.last_choice=choice
        else:self.screen.sync(client=p)
        return None

    def close(self):
        if self.active:self.screen.hide();self.active=False
