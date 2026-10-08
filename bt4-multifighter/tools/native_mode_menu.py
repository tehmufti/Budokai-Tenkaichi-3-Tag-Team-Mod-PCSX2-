"""Native animated grouped mode menu, installed with the original BT3 boot cheat.

Uses original menu plates, navigation, sound and fade/cleanup. Owned image
texture descriptors replace the stock label atlas bindings. A guest lease
restores every owned pointer/row even if the host stops servicing the menu.
No emulator is opened by this module. The autopilot owns Controller leases.
"""
import struct
import localization
from regional import MENU_ACCEPT, RAW_ACCEPT, RAW_BACK
from functools import lru_cache
from prototype import Assembler
import mode_menu as old
import native_menu_assets as assets
import native_menu_services as services
import input_binding
import roster_selection_guard
import coop_character_select
import ingame_settings
import team_assignment
import controller_assignment
import player_slot_labels
import scenario_menu

CODE,OFF,ON,CONTROL,END=0x07690000,0x076A0000,0x076C1000,0x076FF000,0x07700000
ALT_OFF,ALT_ON=0x06C40000,0x06C61000
MAGIC=0x324D4E42
CHECKPOINT_WAIT,PENDING_CHOICE=0xD0,0xD4
# Choice numbers stay stable across additions and native return routing.
SELECTIONS=old.SELECTIONS+(('teams',2),('teams',0),('training',1),('training',2),('training_coop',2),('teams',4),('ffa',4),('coop',4),('training',4),('training_coop',4),('teams',3),('ffa',3),('coop',3),('training',3),('training_coop',3))
PAGES=((0,1,2,3,6),(4,5,1,0,6,7),(4,5,1,0,6,7),(5,1,0,7),(4,5,1,0,7),(5,1,0,7))
# CONTROL: magic,state(1 armed/2 custom/3 committed/4 original),page,result,lease,owner,
# epoch; snapshots: rows/count/cursor at100,scroll140,off144,on148,resource14c.


def owned_atlases(a,fail,tag):
    a.li(12,OFF);a.lw(10,8,8);a.branch(4,10,0,tag+'_off')
    a.li(12,ALT_OFF)
    a.label(tag+'_off');a.lw(10,11,0x60);a.branch(5,10,12,fail)
    a.li(12,ON);a.lw(10,8,8);a.branch(4,10,0,tag+'_on')
    a.li(12,ALT_ON)
    a.label(tag+'_on');a.lw(10,11,0x70);a.branch(5,10,12,fail)


def payload():
    a=Assembler(CODE);services.save(a)
    a.call(controller_assignment.CODE)
    a.lw(4,29,services.STACK+0x18);a.call(scenario_menu.ROUTE)
    a.lw(4,29,services.STACK+0x18);a.call(scenario_menu.CODE);a.branch(5,2,0,'return')
    a.lw(4,29,services.STACK+0x18);a.call(ingame_settings.CODE);a.branch(5,2,0,'return')
    a.lw(4,29,services.STACK+0x18);a.call(team_assignment.CODE);a.branch(5,2,0,'return')
    a.lw(4,29,services.STACK+0x18);a.call(coop_character_select.CODE)
    a.lw(4,29,services.STACK+0x18);a.call(roster_selection_guard.CODE)
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'return')
    a.lw(9,8,4);a.branch(4,9,0,'return');a.addiu(10,0,3);a.branch(4,9,10,'return')
    a.lw(10,8,16);a.branch(4,10,0,'restore');a.addiu(10,10,-1);a.sw(10,8,16)
    a.li(10,old.MAIN_OBJECT);a.lw(11,10);a.lw(12,8,20);a.branch(5,11,12,'disown')
    a.li(10,old.SCENE_MANAGER);a.lw(10,10);a.li(12,0x100000)
    a.r(0x2B,12,10,12);a.branch(5,12,0,'restore');a.li(12,0x1FFF000)
    a.r(0x2B,12,10,12);a.branch(4,12,0,'restore');a.lw(10,10,0x18)
    a.addiu(12,0,4);a.branch(5,10,12,'restore')
    a.lw(10,29,services.STACK+0x18);a.li(12,old.MAIN_CALLER);a.branch(5,10,12,'return')
    a.lw(10,11,4);a.lw(12,8,0x14C);a.branch(5,10,12,'disown')
    a.addiu(10,0,1);a.branch(4,9,10,'arm')
    a.addiu(10,0,4);a.branch(4,9,10,'original_checks')
    owned_atlases(a,'disown','check')
    a.lw(15,8,PENDING_CHOICE);a.branch(5,15,0,'commit_ready')
    a.lw(10,8,team_assignment.STATE);a.addiu(12,0,2);a.branch(5,10,12,'inputs')
    a.lw(15,8,team_assignment.CHOICE);a.sw(0,8,team_assignment.STATE);a.jump('commit_ready')
    a.label('original_checks');a.lw(10,11,0x60);a.lw(12,8,0x144);a.branch(5,10,12,'disown')
    a.lw(10,11,0x70);a.lw(12,8,0x148);a.branch(5,10,12,'disown')
    a.label('inputs');a.lw(10,11,0x18);a.i(12,10,10,2);a.branch(4,10,0,'return')
    a.lw(10,11,0x108);a.i(12,10,10,4);a.branch(4,10,0,'return')
    a.li(12,old.PAD)
    a.lw(13,12,0x150);a.lw(10,8,28);a.sw(13,8,28)
    a.i(14,10,10,0xFFFF);a.r(0x24,13,13,10)
    a.lw(10,8,32);a.r(0x24,10,13,10);a.branch(5,10,0,'toggle')
    a.lw(10,12,0x150);a.lw(14,8,32);a.r(0x24,10,10,14);a.branch(5,10,0,'consume')
    a.addiu(10,0,4);a.branch(4,9,10,'return')
    # The native accept (USA/Europe Cross 0x200, Japan Circle 0x100) never reaches the stock row under a custom
    # page; the disc's own back / accept buttons drive the pages.
    for off in (0x18C,0x190):a.lw(10,12,off);a.i(12,10,10,0xFFFF&~MENU_ACCEPT);a.sw(10,12,off)
    a.i(12,10,13,RAW_BACK);a.branch(5,10,0,'back')
    a.i(12,10,13,RAW_ACCEPT);a.branch(4,10,0,'return')
    a.lw(10,11,0x144);a.i(11,14,10,12);a.branch(4,14,0,'restore');a.branch(4,10,0,'restore')
    a.lw(13,11,0x148);a.r(0x2B,14,13,10);a.branch(4,14,0,'restore')
    a.lw(14,11,0x10C);a.addiu(15,14,1);a.i(11,15,15,12);a.branch(4,15,0,'restore')
    a.r(0x21,13,13,14);a.addiu(13,13,1)
    a.label('modulo');a.r(0x2B,14,13,10);a.branch(5,14,0,'selected');a.r(0x23,13,13,10);a.jump('modulo')
    a.label('selected');a.r(0,13,0,13,2);a.r(0x21,13,13,11);a.lw(13,13,0x118)
    a.lw(14,8,8);a.branch(4,14,0,'root_choice');a.addiu(10,0,7);a.branch(4,13,10,'back')
    # Submenu row 1 is the private Three Players label. Keep all existing
    # semantic choice IDs stable for saved selector-return receipts.
    a.addiu(10,0,1);a.branch(5,13,10,'existing_choice')
    a.addiu(15,14,16);a.jump('commit');a.label('existing_choice')
    a.addiu(10,0,1);a.branch(4,14,10,'teams');a.addiu(10,0,2);a.branch(4,14,10,'ffa')
    a.addiu(10,0,4);a.branch(4,14,10,'training')
    a.addiu(10,0,5);a.branch(4,14,10,'training_coop')
    a.addiu(15,0,14);a.branch(4,13,0,'commit')
    a.addiu(10,0,5);a.branch(5,13,10,'restore');a.addiu(15,0,4);a.jump('commit')
    a.label('teams');a.addiu(15,0,12);a.branch(4,13,0,'commit');a.addiu(10,0,4);a.addiu(15,0,1);a.branch(4,13,10,'commit')
    a.addiu(10,0,5);a.addiu(15,0,7);a.branch(4,13,10,'commit')
    a.addiu(10,0,6);a.addiu(15,0,8);a.branch(4,13,10,'commit');a.jump('restore')
    a.label('ffa');a.addiu(15,0,13);a.branch(4,13,0,'commit');a.addiu(10,0,4);a.addiu(15,0,2);a.branch(4,13,10,'commit')
    a.addiu(10,0,5);a.addiu(15,0,3);a.branch(4,13,10,'commit')
    a.addiu(10,0,6);a.addiu(15,0,5);a.branch(4,13,10,'commit');a.jump('restore')
    a.label('training');a.addiu(15,0,15);a.branch(4,13,0,'commit');a.addiu(10,0,4);a.addiu(15,0,9);a.branch(4,13,10,'commit')
    a.addiu(10,0,5);a.addiu(15,0,10);a.branch(4,13,10,'commit')
    a.addiu(10,0,2);a.addiu(14,0,5);a.branch(4,13,10,'page');a.jump('restore')
    a.label('training_coop');a.addiu(15,0,16);a.branch(4,13,0,'commit')
    a.addiu(10,0,5);a.addiu(15,0,11);a.branch(4,13,10,'commit');a.jump('restore')
    a.label('root_choice');a.addiu(10,0,6);a.branch(4,13,10,'settings')
    a.addiu(10,0,2);a.branch(4,13,10,'scenarios')
    a.i(11,10,13,4);a.branch(4,10,0,'restore');a.addiu(14,13,1);a.jump('page')
    a.label('scenarios');a.li(10,scenario_menu.CONTROL);a.li(12,scenario_menu.MAGIC);a.sw(12,10)
    a.addiu(12,0,1);a.sw(12,10,4);a.addiu(12,0,180);a.sw(12,10,8);a.sw(0,10,12)
    a.li(12,old.PAD);a.lw(12,12,0x150);a.sw(12,10,16);a.jump('consume')
    a.label('settings');a.li(10,ingame_settings.CONTROL);a.li(12,ingame_settings.MAGIC);a.sw(12,10)
    a.addiu(12,0,1);a.sw(12,10,4);a.addiu(12,0,180);a.sw(12,10,8);a.sw(0,10,12)
    a.li(12,old.PAD);a.lw(12,12,0x150);a.sw(12,10,16);a.jump('consume')
    a.label('back');a.lw(14,8,8);a.branch(4,14,0,'stock');a.addiu(10,0,5);a.branch(5,14,10,'root_back');a.addiu(14,0,4);a.jump('page');a.label('root_back');a.move(14,0);a.jump('page')
    a.label('arm');a.lw(14,8,64);a.branch(4,14,0,'arm_stock');a.i(11,15,14,7);a.branch(4,15,0,'arm_stock');a.addiu(14,14,-1);a.sw(14,8,68);a.jump('activate')
    a.label('arm_stock');a.sw(0,8,64);a.sw(0,8,60);a.addiu(10,0,6);a.sw(10,8,12);a.addiu(10,0,4);a.sw(10,8,4);a.jump('consume')
    a.label('toggle');a.addiu(10,0,2);a.branch(4,9,10,'stock')
    a.label('activate');a.lw(10,11,0x60);a.lw(12,8,0x144);a.branch(5,10,12,'disown')
    a.lw(10,11,0x70);a.lw(12,8,0x148);a.branch(5,10,12,'disown')
    for i in range(13):a.lw(10,11,0x118+i*4);a.sw(10,8,0x100+i*4)
    for co,oo in ((0x140,0x10C),(0x150,0x150),(0x154,0x154),(0x158,0x158)):
        a.lw(10,11,oo);a.sw(10,8,co)
    a.li(10,OFF);a.sw(10,11,0x60);a.li(10,ON);a.sw(10,11,0x70)
    a.addiu(10,0,2);a.sw(10,8,4);a.sw(0,8,12);a.lw(14,8,68);a.sw(0,8,68);a.sw(0,8,64)
    a.label('page');a.sw(14,8,8)
    a.li(10,OFF);a.li(12,ON);a.branch(4,14,0,'atlas_ready')
    a.li(10,ALT_OFF);a.li(12,ALT_ON)
    a.label('atlas_ready');a.sw(10,11,0x60);a.sw(12,11,0x70)
    for i in range(11):a.sw(0,11,0x118+i*4)
    for off in (0x10C,0x150,0x154,0x158):a.sw(0,11,off)
    for page,rows in enumerate(PAGES):
        a.addiu(10,0,page);a.branch(5,14,10,f'page_next{page}')
        a.addiu(10,0,len(rows));a.sw(10,11,0x144)
        a.addiu(10,0,len(rows)-1);a.sw(10,11,0x148)
        for i,v in enumerate(rows):a.addiu(10,0,v);a.sw(10,11,0x118+i*4)
        a.jump('redraw');a.label(f'page_next{page}')
    a.jump('restore')
    a.label('redraw');a.call(services.RESET)
    a.label('consume');a.li(12,old.PAD);a.lw(10,12,0x150);a.sw(10,8,28);a.sw(0,12,0x18C);a.sw(0,12,0x190);a.jump('return')
    a.label('stock');a.sw(0,8,64);a.sw(0,8,68);a.sw(0,8,60);a.addiu(10,0,4);a.sw(10,8,4);a.addiu(10,0,6);a.sw(10,8,12);a.jump('restore_owned')
    a.label('commit');a.sw(0,8,team_assignment.VALID)
    for choice in team_assignment.CHOICES:
        a.addiu(10,0,choice);a.branch(4,15,10,'assign_teams')
    a.jump('commit_ready')
    a.label('assign_teams');a.sw(15,8,team_assignment.CHOICE);a.addiu(10,0,1);a.sw(10,8,team_assignment.STATE)
    a.addiu(10,0,180);a.sw(10,8,team_assignment.LEASE);a.sw(0,8,team_assignment.BUTTONS)
    a.li(10,old.PAD);a.lw(10,10,0x150);a.sw(10,8,team_assignment.PREVIOUS);a.jump('consume')
    a.label('commit_ready');a.lw(10,8,CHECKPOINT_WAIT);a.branch(4,10,0,'checkpoint_ready')
    a.sw(15,8,PENDING_CHOICE);a.jump('consume')
    a.label('checkpoint_ready');a.sw(0,8,PENDING_CHOICE);a.sw(0,8,64);a.sw(0,8,72);a.sw(15,8,60);a.sw(15,8,12);a.lw(10,8,24);a.addiu(10,10,1);a.sw(10,8,24)
    a.addiu(10,0,3);a.sw(10,8,4);a.jump('restore_owned')
    a.label('restore');a.sw(0,8,4);a.sw(0,8,12)
    a.label('restore_owned');a.li(10,old.MAIN_OBJECT);a.lw(11,10);a.lw(12,8,20);a.branch(5,11,12,'return')
    a.lw(10,11,4);a.lw(12,8,0x14C);a.branch(5,10,12,'return')
    owned_atlases(a,'return','restore')
    for i in range(13):a.lw(10,8,0x100+i*4);a.sw(10,11,0x118+i*4)
    for co,oo in ((0x140,0x10C),(0x144,0x60),(0x148,0x70),(0x150,0x150),(0x154,0x154),(0x158,0x158)):
        a.lw(10,8,co);a.sw(10,11,oo)
    a.call(services.RESET)
    a.lw(15,8,12);a.branch(4,15,0,'consume');a.addiu(10,0,6);a.branch(4,15,10,'consume')
    # Restore the stock rows before the normal Duel dispatch sees acceptance.
    a.sw(0,11,0x10C);a.addiu(10,0,2);a.sw(10,11,0x148)
    a.li(12,old.CONTROL);a.li(10,old.MAGIC);a.sw(10,12);a.sw(0,12,4)
    a.addiu(10,0,450);a.sw(10,12,16);a.sw(10,12,44);a.addiu(10,0,1);a.sw(10,12,20);a.sw(0,12,40)
    a.lw(10,8,coop_character_select.ALL_CONTROLLERS);a.branch(5,10,0,'accept')
    a.lw(10,8,team_assignment.VALID);a.branch(5,10,0,'accept');a.addiu(10,0,3);a.branch(4,15,10,'two_pads');a.addiu(10,0,7);a.branch(4,15,10,'two_pads');a.addiu(10,0,10);a.branch(5,15,10,'accept')
    a.label('two_pads');a.addiu(10,0,1);a.sw(10,12,40)
    a.label('accept');a.lw(10,8,48);a.sw(10,8,40);a.addiu(10,0,600);a.sw(10,8,44)
    a.li(12,old.PAD);a.addiu(10,0,MENU_ACCEPT);a.sw(10,12,0x18C);a.sw(0,12,0x190);a.jump('return')
    a.label('disown');a.sw(0,8,4);a.sw(0,8,12)
    a.label('return')
    services.restore(a);a.jump(old.CODE)
    data=a.finish();assert len(data)<0x3000;return data


def hook():return struct.pack('<2I',(2<<26)|(CODE>>2),0)


def _control(ram,obj,atlases,settings):
    ctl=bytearray(0x180)
    struct.pack_into('<I',ctl,0xD8,int(localization.language(settings)=='es'))
    struct.pack_into('<7I',ctl,0,MAGIC,1,0,0,180,obj,0)
    button=settings.get('menu_toggle_button','select')
    if button not in input_binding.MASKS:raise ValueError('Invalid menu toggle binding')
    struct.pack_into('<5I',ctl,32,input_binding.MASKS[button],int(settings.get('show_menu_toggle_hint',True)),0,0,
                     1)
    struct.pack_into('<I',ctl,56,int(settings.get('native_mode_menu_enabled',True)))
    struct.pack_into('<I',ctl,0x80,int(settings.get('coop_independent_selection',True)))
    struct.pack_into('<I',ctl,coop_character_select.ALL_CONTROLLERS,int(settings.get('all_controllers_character_select',False)))
    struct.pack_into('<I',ctl,player_slot_labels.VISIBLE,int(settings.get('show_player_slot_labels',True)))
    # Removed at the user's request. Retain dormant guest bytes for exact
    # prepared-state compatibility, but never reactivate an obsolete setting.
    struct.pack_into('<I',ctl,coop_character_select.SHOW_HINT,0)
    if assets.u32(ram,CONTROL)==MAGIC and 1<=assets.u32(ram,CONTROL+64)<=6:
        struct.pack_into('<I',ctl,64,assets.u32(ram,CONTROL+64))
        struct.pack_into('<2I',ctl,40,1,600)
        struct.pack_into('<I',ctl,52,128)
    ctl[0x100:0x134]=bytes(ram[obj+0x118:obj+0x14C])
    for off,value in ((0x140,assets.u32(ram,obj+0x10C)),(0x144,atlases['off'].descriptor),
                      (0x148,atlases['on'].descriptor),(0x14C,assets.u32(ram,obj+4)),
                      (0x150,assets.u32(ram,obj+0x150)),(0x154,assets.u32(ram,obj+0x154)),(0x158,assets.u32(ram,obj+0x158))):
        struct.pack_into('<I',ctl,off,value)
    return bytes(ctl)


def _assets(ram,obj,atlases,settings):
    blocks=[]
    for name,dest,limit,labels in (('off',OFF,ON,assets.LABELS),('on',ON,services.TEXT,assets.LABELS),
            ('off',ALT_OFF,ALT_ON,('4 Players','3 Players')+assets.LABELS[2:6]+('CPU Only','Back')),
            ('on',ALT_ON,ALT_ON+0x21000,('4 Players','3 Players')+assets.LABELS[2:6]+('CPU Only','Back'))):
        blob=assets.clone(ram,atlases[name],dest,assets.compose_indices(ram,atlases[name],tuple(localization.tr(label,settings) for label in labels)))
        if dest+len(blob)>limit:raise ValueError('Owned atlas exceeds reservation')
        blocks.append((dest,blob))
    button=input_binding.LABELS[settings.get('menu_toggle_button','select')]
    texts=assets.descriptions(ram,obj,button,settings.get('show_menu_toggle_hint',True),settings)
    if len(texts[0])>0x3000 or len(texts[1])>0x10000:raise ValueError('Native menu text exceeds reservation')
    custom=bytearray(0x4000);custom[:len(texts[0])]=texts[0]
    for i in range(7):
        name=f'mc_menu_plate_{i+1}'.encode()+b'\0';custom[0x3000+i*32:0x3000+i*32+len(name)]=name
    blocks.extend(((services.TEXT,bytes(custom)),(services.STOCK_TEXT,texts[1]+bytes(0x10000-len(texts[1])))))
    return blocks


def prepare(ram,settings=None):
    """Offline complete plan. Original menu remains visible until toggled."""
    settings=settings or {}
    if len(ram)<END:raise ValueError('Native pager requires expanded RAM')
    if any(ram[CODE:END]):raise ValueError('Native pager reservation occupied')
    obj,atlases=assets.inspect(ram)
    for p,data in old.code_pieces():
        if bytes(ram[p:p+len(data)])!=data:raise ValueError('Audited existing mode-menu hook required')
    for p,data in services.ORIGINAL.items():
        if bytes(ram[p:p+8])!=struct.pack('<2I',*data):raise ValueError('Native menu service hook changed')
    import native_menu_texture
    return code_pieces()+_assets(ram,obj,atlases,settings)+native_menu_texture.plan(ram)+[(CONTROL,_control(ram,obj,atlases,settings))]


@lru_cache(maxsize=1)
def code_pieces():
    """Include AFTER old.code_pieces in cold-boot/checkpoint construction."""
    return [(CODE,payload()),(old.HOOK,hook())]+services.code_pieces()+roster_selection_guard.code_pieces()+coop_character_select.code_pieces()+ingame_settings.code_pieces()+team_assignment.code_pieces()+controller_assignment.code_pieces()+player_slot_labels.pieces()+scenario_menu.code_pieces()


class ReadOnlyMemory:
    def __init__(self,client):self.client=client
    def __len__(self):return END
    def __getitem__(self,key):
        if not isinstance(key,slice)or key.step is not None:raise TypeError('Contiguous memory slices only')
        return self.client.read(key.start,key.stop-key.start)


def owned_plan(ram,settings=None):
    """Data-only rearm plan for an already installed native pager."""
    settings=settings or {}
    for p,b in old.code_pieces()[:1]+code_pieces():
        if bytes(ram[p:p+len(b)])!=b:
            from native_preparation import launcher
            raise ValueError(f'Native pager boot hook mismatch at EE 0x{p:08X}; close PCSX2, then start {launcher()} again to install the current hooks')
    obj,atlases=assets.inspect(ram);blocks=_assets(ram,obj,atlases,settings)
    previous=bytes(ram[CONTROL:CONTROL+0x180])
    if any(previous) and struct.unpack_from('<I',previous)[0]!=MAGIC:
        raise ValueError('Native menu control belongs to another patch')
    previous_texts={}
    if any(previous):
        mask,hint=struct.unpack_from('<2I',previous,32)
        prior_button=next((name for name,value in input_binding.MASKS.items()if value==mask),None)
        if prior_button is not None and hint in (0,1):
            prior_settings=dict(settings,menu_toggle_button=prior_button,show_menu_toggle_hint=bool(hint),language='es' if struct.unpack_from('<I',previous,0xD8)[0]==1 else 'en')
            previous_texts=dict(_assets(ram,obj,atlases,prior_settings))
    for dest,blob in blocks:
        current=bytes(ram[dest:dest+len(blob)])
        if any(current) and current not in (blob,previous_texts.get(dest)):
            raise ValueError('Native menu asset reservation has a different owner')
    occupied=sorted([(p,p+len(b)) for p,b in code_pieces()+blocks if CODE<=p<END]+[(CONTROL,CONTROL+0x180)])
    for (_,end),(start,_)in zip(occupied,occupied[1:]):
        if any(ram[end:start]):raise ValueError('Native menu reservation padding occupied')
    if any(ram[CONTROL+0x180:END]):raise ValueError('Native menu reservation tail occupied')
    import native_menu_texture
    return blocks+native_menu_texture.plan(ram)+[(CONTROL,_control(ram,obj,atlases,settings))]


def ready(p):
    manager=p.read_u32(old.SCENE_MANAGER)
    if not 0x100000<=manager<0x1FFF000 or p.read_u32(manager+0x18)!=4:return False
    obj=p.read_u32(old.MAIN_OBJECT)
    return 0x100000<=obj<0x1FFF000


class Controller:
    """Host lease/semantic publication only; visual navigation runs in guest."""
    native=True
    def __init__(self,settings=None):
        self.settings=dict(settings or {});self.pending_settings=None
        self.active=False;self.dismissed=False;self.last_choice=None
        self.mode='teams';self.humans=1;self.epoch=0;self.closed=False
        self.await_restore=False;self.owned=False
        self.custom_match=False;self.pending_return_page=None
        self.settings_menu=ingame_settings.Controller()
        self.team_menu=team_assignment.Controller()
        self.scenarios=scenario_menu.Controller(self.settings)
        # Assemble immutable programs, badges and logo during boot, before
        # the user reaches the main menu. These do not inspect or mutate RAM.
        code_pieces()
        assets.addresses()
        import native_menu_texture
        native_menu_texture.packet()

    def set_settings(self,settings):
        """Queue a lease-safe native menu refresh; tick owns all writes.

        The latest report always wins: one that matches the applied settings
        drops a refresh an earlier report queued, so it can never go stale."""
        relevant=('language','native_mode_menu_enabled','menu_toggle_button','show_menu_toggle_hint','coop_independent_selection','all_controllers_character_select','show_player_slot_labels')
        # Host-only (Player Setup's check-in): taken at once, no pager refresh.
        for key in ('controller_checkin','keep_controller_checkins'):
            if key in settings:self.settings[key]=settings[key]
        self.pending_settings=dict(settings) if any(settings.get(k)!=self.settings.get(k) for k in relevant) else None

    def return_pending(self,p):
        return (self.pending_return_page is not None or
                p.read_u32(CONTROL)==MAGIC and 1<=p.read_u32(CONTROL+64)<=6)

    def reset(self,p,*,return_page=None):
        if return_page is not None:
            if return_page not in range(len(PAGES)):raise ValueError('Invalid native return page')
            # Checkpoint restoration removes guest return intent. Keep it on
            # the host until the fully staged, freshly owned menu is published.
            self.pending_return_page=return_page
            self.custom_match=False
        if p.read_u32(CONTROL)==MAGIC:p.write_u32(CONTROL+16,0)
        for off in (4,12,20):p.write_u32(old.CONTROL+off,0)
        self.active=False;self.dismissed=False;self.last_choice=None;self.await_restore=True

    def tick(self,p,*,allow_activate=True,checkpoint_ready=True):
        if self.closed:return None
        self.scenarios.settings=self.settings
        self.scenarios.checkpoint_ready=checkpoint_ready
        if self.scenarios.tick(p):return None
        if self.scenarios.failed:
            self.custom_match=False;self.scenarios.failed=False
        self.team_menu.settings=self.settings
        if self.team_menu.tick(p):return None
        settings=self.settings_menu.tick(p)
        if settings is not None:self.set_settings(settings)
        if self.settings_menu.active:
            p.write_u32(CONTROL+16,180)
            self.custom_match=False
            return None
        state=struct.unpack('<7I',p.read(CONTROL,28))
        if state[0]==MAGIC and self.owned:p.write_u32(CONTROL+CHECKPOINT_WAIT,int(not checkpoint_ready))
        if state[0]==MAGIC and p.read_u32(CONTROL+coop_character_select.SHOW_HINT):
            # Also retire the hint from restored pre-removal checkpoints.
            p.write_u32(CONTROL+coop_character_select.SHOW_HINT,0)
        if self.pending_settings is not None:
            if state[0]==MAGIC and state[1] in (1,2,4):
                p.write_u32(CONTROL+16,0);self.active=False;return None
            self.settings=self.pending_settings;self.pending_settings=None
        if not self.settings.get('native_mode_menu_enabled',True):
            self.pending_return_page=None;self.custom_match=False
            if state[0]==MAGIC:
                for off in (56,64):p.write_u32(CONTROL+off,0)
            if state[0]==MAGIC and state[1]in (1,2,4):p.write_u32(CONTROL+16,0)
            return None
        if state[0]==MAGIC and state[1]in (3,4) and state[3]:
            if any(p.read(a,len(b))!=b for a,b in code_pieces()):raise ValueError('Native menu code changed')
            choice=state[3]-1
            if choice not in range(len(SELECTIONS))or(state[1]==4 and choice!=5):raise ValueError('Invalid native mode choice')
            self.mode,self.humans=SELECTIONS[choice];self.epoch+=1
            self.last_choice=choice;self.custom_match=choice!=5
            p.write_u32(CONTROL+12,0)
            if state[1]==3:
                self.dismissed=True;self.active=False;p.write_u32(CONTROL+4,0)
            else:self.active=True;p.write_u32(CONTROL+16,180)
            result=dict(mode=self.mode,humans=self.humans,choice=choice)
            assignment=team_assignment.selected(ReadOnlyMemory(p),self.mode,self.humans)
            if assignment is not None:result['assignment']=assignment
            return result
        if not ready(p):
            self.dismissed=False;self.active=False
            if p.read_u32(old.CONTROL)==old.MAGIC and p.read_u32(old.CONTROL+20):p.write_u32(old.CONTROL+16,180)
            return None
        if self.dismissed:return None
        # Backing out of selection or restoring the main menu ends the previous
        # match's authorization even without an explicit Original-menu receipt.
        # Character-select returns take the not-ready path and retain it.
        self.custom_match=False
        if self.await_restore:
            if state[0]==MAGIC and state[1]in (1,2,4):return None
            self.await_restore=False
        if state[0]==MAGIC and state[1]in (1,2,4):
            # A new host must release an archived/abandoned lease before it
            # snapshots rows; otherwise a "clean" checkpoint keeps our labels.
            if not self.owned:
                self.reset(p);return None
            p.write_u32(CONTROL+16,180);self.active=True
            if (state[1]==4 and allow_activate and ready(p) and not self.scenarios.launched and
                    self.scenarios.quick_document() is not None):
                # Workbench "Test this mission": open the Modded Modes root page through the
                # guest's own return-page route (as after a custom match); scenario_menu launches it.
                p.write_u32(CONTROL+64,1);p.write_u32(CONTROL+4,1)
            return None
        if not allow_activate:return None
        if self.pending_return_page is None and self.scenarios.quick_document() is not None:
            self.pending_return_page=0
        plan=owned_plan(ReadOnlyMemory(p),self.settings)
        # Assets are staged first. Publish magic last: PINE writes can span
        # multiple commands while guest frames run. No live code/object edits.
        if not ready(p):return None
        owner=struct.unpack_from('<I',plan[-1][1],20)[0]
        if p.read_u32(old.MAIN_OBJECT)!=owner:return None
        for address,blob in plan[:-1]:p.write(address,blob)
        control=bytearray(plan[-1][1])
        struct.pack_into('<I',control,CHECKPOINT_WAIT,int(not checkpoint_ready))
        if self.pending_return_page is not None:
            struct.pack_into('<I',control,64,self.pending_return_page+1)
            struct.pack_into('<2I',control,40,1,600)
            struct.pack_into('<I',control,52,128)
        p.write_u32(CONTROL,0)
        p.write(CONTROL+4,control[4:])
        p.write_u32(CONTROL,MAGIC)
        self.pending_return_page=None
        self.owned=True;self.active=True
        return None

    def close(self):
        # The guest restores ownership itself after at most 180 pad updates;
        # no detached process or fresh emulator connection is created here.
        self.team_menu.shutdown()
        self.scenarios.shutdown()
        self.closed=True;self.active=False
