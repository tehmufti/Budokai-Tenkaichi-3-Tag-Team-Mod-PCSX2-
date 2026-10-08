"""In-game scenario library and guarded native roster admission.

Definitions are ordinary story JSON files. The game constructs a fresh Team
Select scene, receives its own roster records, then runs its normal stage and
battle initialization. This module never loads an emulator checkpoint.
"""
import copy
import logging
import struct
import time
from pathlib import Path

from native_map import A
from prototype import Assembler
import mode_menu as old
import roster_selection_guard as roster
import story_missions as missions
import localization
import fonts

CODE, ROUTE, CONTROL, DATA, END = 0x06980000, 0x06980800, 0x06981800, 0x06981900, 0x06982000
MAGIC = 0x53434E31
MENU = 0x076FF000
# Control: magic, browser active, lease, edges, previous, route state,
# route lease, selector owner, two roster counts, preset stage (-1 = choose).
# Route states: 1 awaiting selector, 2 records published, 3 native stage select,
# 4 finished, 100 rejected. DATA holds two complete 5*48-byte native rosters.
SIGNATURES = {**roster.SIGNATURES, A(0x351BA8): 0x0040182D,
              A(0x351BB8): 0x0C000000 | (A(0x12A2D8) >> 2)}


def input_code():
    a=Assembler(CODE);a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'no')
    a.lw(9,8,4);a.branch(4,9,0,'no');a.lw(9,8,8);a.branch(4,9,0,'expire')
    a.addiu(9,9,-1);a.sw(9,8,8)
    a.li(10,old.MAIN_CALLER);a.branch(5,4,10,'no')
    a.li(10,MENU);a.lw(11,10,4);a.addiu(12,0,2);a.branch(5,11,12,'expire')
    a.li(10,old.PAD);a.lw(11,10,0x150);a.lw(12,8,16);a.sw(11,8,16)
    a.i(14,12,12,0xFFFF);a.r(0x24,11,11,12);a.lw(12,8,12);a.r(0x25,11,11,12);a.sw(11,8,12)
    a.sw(0,10,0x18C);a.sw(0,10,0x190);a.addiu(2,0,1);a.jr()
    a.label('expire');a.sw(0,8,4);a.sw(0,8,12)
    a.label('no');a.move(2,0);a.jr();return a.finish()


def route_code():
    # Executes on the selector's pad boundary. No host writes to live rows.
    a=Assembler(ROUTE);a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done')
    a.lw(9,8,20);a.addiu(10,9,-1);a.i(11,10,10,3);a.branch(4,10,0,'done')
    a.li(10,roster.CALLER);a.branch(5,4,10,'done')
    a.lw(10,8,24);a.branch(4,10,0,'fail');a.addiu(10,10,-1);a.sw(10,8,24)
    a.li(10,old.SCENE_MANAGER);a.lw(10,10)
    a.li(11,0x100000);a.r(0x2B,11,10,11);a.branch(5,11,0,'fail')
    a.li(11,0x1FFF000);a.r(0x2B,11,10,11);a.branch(4,11,0,'fail')
    a.lw(11,10,0x18);a.addiu(12,0,40);a.branch(5,11,12,'done')
    a.lw(11,10,0x14);a.i(12,11,11,0x100);a.branch(5,11,0,'done')
    for p,word in SIGNATURES.items():
        a.li(10,p);a.lw(11,10);a.li(12,word);a.branch(5,11,12,'fail')
    a.li(10,roster.TEAM_OBJECT);a.lw(11,10)
    a.li(12,0x100000);a.r(0x2B,12,11,12);a.branch(5,12,0,'fail')
    a.li(12,0x1FFC000);a.r(0x2B,12,11,12);a.branch(4,12,0,'fail')
    a.lw(12,11,0x3C);a.i(12,12,12,2);a.branch(4,12,0,'done')
    a.addiu(10,0,1);a.branch(4,9,10,'hold')
    a.lw(12,8,28);a.branch(5,11,12,'fail')
    a.addiu(10,0,3);a.branch(4,9,10,'stage')
    # Prove every destination/count before any roster modification.
    for side in range(2):
        a.lw(12,11,0x8E8+side*4);a.li(13,0x100000);a.r(0x2B,13,12,13);a.branch(5,13,0,'fail')
        a.li(13,0x1FFFF00-0x100);a.r(0x2B,13,12,13);a.branch(4,13,0,'fail')
        a.i(12,13,12,3);a.branch(5,13,0,'fail')
        a.lw(13,8,32+side*4);a.addiu(13,13,-1);a.i(11,13,13,5);a.branch(4,13,0,'fail')
    for side in range(2):
        a.lw(12,11,0x8E8+side*4);a.li(13,DATA+side*240)
        for off in range(0,240,4):a.lw(14,13,off);a.sw(14,12,off)
        a.lw(13,8,32+side*4);a.sw(13,12,0x134)
        a.addiu(13,0,5);a.sw(13,12,0x12C)
        # The native state-8 handler observes both Done confirmations and
        # opens the stage selector with its normal animations and cleanup.
        a.addiu(13,0,8);a.sw(13,12,0x13C)
    a.addiu(10,0,3);a.sw(10,8,20);a.jump('hold')
    a.label('stage');a.lw(10,11,0x3BC);a.i(12,10,10,4);a.branch(4,10,0,'hold')
    a.lw(12,11,0x9A4);a.li(13,0x100000);a.r(0x2B,13,12,13);a.branch(5,13,0,'fail')
    a.li(13,0x1FFFFA0);a.r(0x2B,13,12,13);a.branch(4,13,0,'fail')
    a.lw(10,8,52);a.sw(10,12,0x4C);a.sw(10,12,0x50)
    a.lw(10,8,40);a.addiu(13,0,-1);a.branch(4,10,13,'finished')
    # An explicit preset arena was verified against the native stage list.
    a.sw(10,12,0x3C);a.lw(10,8,44);a.sw(10,12);a.lw(10,8,48);a.sw(10,12,4)
    a.lw(10,12,0x44);a.branch(5,10,0,'hold')
    a.lw(10,12,0x40)
    for state in (9,10):a.addiu(13,0,state);a.branch(4,10,13,'confirm')
    a.jump('hold')
    a.label('confirm');a.li(10,old.PAD);a.addiu(13,0,0x200);a.sw(13,10,0x18C);a.sw(0,10,0x190);a.jr()
    a.label('finished');a.addiu(10,0,4);a.sw(10,8,20);a.jr()
    a.label('hold');a.li(10,old.PAD);a.sw(0,10,0x18C);a.sw(0,10,0x190);a.jr()
    a.label('fail');a.addiu(10,0,100);a.sw(10,8,20)
    a.label('done');a.jr();data=a.finish()
    if ROUTE+len(data)>CONTROL:raise ValueError('Scenario route exceeds its reservation')
    return data


def code_pieces():return [(CODE,input_code()),(ROUTE,route_code())]


def _ptr(value,size):
    if value%4 or not 0x100000<=value<=0x2000000-size:raise ValueError('Scenario selector data is not ready')
    return value


def roster_records(p,document):
    """Derive grid/form records from this disc's live selector, not hardcoded IDs."""
    # Scene 40 is published before its overlay/object has finished loading.
    # An absent constructor is a wait, not an incompatible disc.
    obj=p.read_u32(roster.TEAM_OBJECT)
    if obj%4 or not 0x100000<=obj<=0x2000000-0x3EA4:return None
    if not p.read_u32(obj+0x3C)&2:return None
    for address,word in SIGNATURES.items():
        if p.read_u32(address)!=word:raise ValueError('Scenario roster selector is not supported by this game build')
    if p.read_u32(obj+0x3C38)!=0:raise ValueError('Scenario setup requires the native one-controller selector')
    blobs=[];counts=[]
    for side in range(2):
        total=p.read_u32(obj+0x9A8+side*4)
        if not 1<=total<=512:raise ValueError('Scenario character table has an invalid length')
        table=_ptr(p.read_u32(obj+0x9B0+side*4),total*36)
        records=list(struct.iter_unpack('<9I',p.read(table,total*36)))
        lookup={}
        for grid,row in enumerate(records):
            if row[1]>7:raise ValueError('Scenario character form table changed')
            for form,cid in enumerate(row[2:2+row[1]] if row[1] else (row[0],)):
                lookup.setdefault(cid,(grid,form,row[0]))
        fighters=sorted((f for f in document['fighters'] if f['team']==side+1),key=lambda f:f['slot'])
        blob=bytearray(240)
        for i in range(5):struct.pack_into('<I',blob,i*48+28,0xFFFFFFFF)
        for i,f in enumerate(fighters):
            if f['character'] not in lookup:raise ValueError(f"{f['id']}: this disc's selector does not contain character {f['character']}")
            grid,form,base=lookup[f['character']]
            struct.pack_into('<8I',blob,i*48,grid%7,grid//7,form,0,base,0,f['costume'],f['character'])
        blobs.append(bytes(blob));counts.append(len(fighters))
    stage=(document.get('stage') or {}).get('id',-1);column=row=0
    if stage>=0:
        n=p.read_u32(obj+0x3C64)
        if not 1<=n<=512:raise ValueError('Scenario arena table has an invalid length')
        table=_ptr(p.read_u32(obj+0x3C5C),n*4);stages=struct.unpack('<'+'I'*n,p.read(table,n*4))
        if stage not in stages:raise ValueError('The scenario arena is unavailable in this game/save')
        index=stages.index(stage);column,row=index%6,index//6
    return obj,counts,b''.join(blobs),(stage&0xFFFFFFFF,column,row)


def music_index(p,obj,document):
    count=p.read_u32(obj+0x3C68)
    if not 1<=count<=512:raise ValueError('Scenario music table has an invalid length')
    table=_ptr(p.read_u32(obj+0x3C60),count*4)
    songs=struct.unpack('<'+'I'*count,p.read(table,count*4))
    wanted=document.get('music')
    if wanted is None:
        # Native random row, when exposed by this disc; otherwise select one
        # of its actual songs rather than assuming another ISO's ID range.
        if 24 in songs:return songs.index(24)
        import secrets
        return secrets.randbelow(len(songs))
    if wanted not in songs:raise ValueError(f'Scenario music {wanted} is unavailable on this disc')
    return songs.index(wanted)


def library(root=None):
    """One bad/custom file cannot take down the menu or hide the good entries."""
    from story_runtime import adapter_check
    rows=[]
    for path in sorted(Path(root or missions.LIBRARY).rglob('*.json')):
        if missions.private(path):continue
        try:
            document=missions.load(path);adapter_check(document)
            rows.append(dict(path=path,document=document,error=None,title=document['title']))
        except (OSError,ValueError,KeyError,TypeError) as e:
            rows.append(dict(path=path,document=None,error=str(e),title=path.stem))
    return rows


class Controller:
    def __init__(self,settings=None):
        self.settings=settings or {};self.active=False;self.screen=None;self.entries=[]
        self.row=0;self.detail=False;self.notice='';self.document=None
        self.launched=False;self.left_main=False;self.route_deadline=0
        self.cpu_only=False;self.ready_input=False;self.last_direction=0;self.next_repeat=0
        self.failed=False
        self.quick=None;self.quick_poll=0;self.checkpoint_ready=True

    def text(self,text,**kw):return localization.tr(text,self.settings,**kw)

    def picture(self):
        from PIL import Image,ImageDraw
        from character_names import character_name
        im=Image.new('RGB',(512,448),(10,16,28));draw=ImageDraw.Draw(im)
        title=fonts.truetype('sans-bold',25);font=fonts.truetype('sans-bold',16);small=fonts.truetype('sans',12)
        def line(text,x,y,f=small,color=(205,217,235),width=464):
            while draw.textlength(text,font=f)>width and len(text)>2:text=text[:-2]+'…'
            draw.text((x,y),text,font=f,fill=color)
        draw.rectangle((0,0,511,4),fill=(245,184,63));line(self.text('MODDED SCENARIOS'),23,20,title)
        if self.detail and self.entries:
            entry=self.entries[self.row];line(entry['title'],23,62,font)
            d=entry['document']
            if d:
                for team in (1,2):
                    x=24+(team-1)*244;line(self.text('TEAM {team}',team=team),x,104,font,width=232)
                    for i,f in enumerate(sorted((f for f in d['fighters'] if f['team']==team),key=lambda f:f['slot'])):
                        line(character_name(f['character']),x,136+i*29,small,width=232)
                        if f['reserve']:line(self.text('Reinforcement'),x,149+i*29,small,(245,184,63),232)
                line(self.text('CPU Only' if self.cpu_only else '1 Player')+'  ‹  ›',24,294,font)
                stage=d.get('stage');line(self.text('Arena: {arena}',arena=stage.get('name') or str(stage['id'])) if stage else self.text('Choose your arena after continuing.'),24,327)
                line(self.text('Cross: play scenario    Triangle: back'),24,408)
            else:line(self.text('Unavailable scenario'),24,116,font);line(entry['error'],24,151)
        else:
            first=self.row//7*7
            line(self.text('{count} scenarios',count=len(self.entries)),24,59)
            for i,entry in enumerate(self.entries[first:first+7]):
                y=87+i*40;chosen=first+i==self.row
                draw.rounded_rectangle((18,y,494,y+33),6,fill=(31,46,66),outline=(249,197,90) if chosen else (55,70,90),width=2)
                line(entry['title'],29,y+6,font,(245,244,249) if not entry['error'] else (195,138,127),448)
            if not self.entries:line(self.text('No saved scenarios found.'),24,114,font)
            line(self.text('Up/Down: select   L1/R1: page   Cross: details'),24,384)
            line(self.text('Triangle: return to Modded Modes'),24,406)
        if self.notice:line(self.notice,24,365,small,(255,155,126))
        return im.quantize(16,dither=Image.Dither.NONE).convert('RGB')

    def open(self,p):
        from guest_loading_screen import GuestLoadingScreen
        self.entries=library();self.row=min(self.row,max(0,len(self.entries)-1))
        self.active=True;self.detail=False;self.ready_input=False
        self.screen=GuestLoadingScreen();self.screen.show_picture(self.picture(),surface='menu',client=p)
        p.write(CONTROL,struct.pack('<5I',MAGIC,1,180,0,p.read_u32(old.PAD+0x150)))

    def close(self,p):
        p.write_u32(CONTROL+4,0)
        if self.screen:self.screen.hide(client=p)
        self.screen=None;self.active=False

    def tick(self,p):
        import native_mode_menu as menu
        state=p.read_u32(CONTROL+4) if p.read_u32(CONTROL)==MAGIC else 0
        scene_manager=p.read_u32(old.SCENE_MANAGER)
        scene=p.read_u32(scene_manager+0x18) if 0x100000<=scene_manager<0x1FFF000 else -1
        if self.launched and scene!=4:self.left_main=True
        if self.launched and self.left_main and scene==4 and p.read_u32(MENU+4)==2:
            if self.document:missions.consumed(self.document)
            self.launched=False;self.left_main=False;self.document=None;p.write_u32(CONTROL+20,0)
            self.open(p);state=1
        if not state:
            if self.active:self.close(p)
            self.service_route(p,scene)
            self.service_quick(p,scene)
            return False
        if not self.active:self.open(p)
        if scene!=4:self.close(p);return False
        p.write_u32(CONTROL+8,180);p.write_u32(MENU+16,180)
        edges=p.read_u32(CONTROL+12);p.write_u32(CONTROL+12,0)
        held=p.read_u32(old.PAD+0x148)
        if not self.ready_input:
            self.ready_input=not held and self.screen.presented(p);return True
        direction=held&0x50;now=time.monotonic()
        if direction and direction==self.last_direction and now>=self.next_repeat:edges|=direction;self.next_repeat=now+.12
        elif direction!=self.last_direction:self.next_repeat=now+.4
        self.last_direction=direction;dirty=False
        if edges&0x1000:
            if self.detail:self.detail=False;self.notice='';dirty=True
            else:self.close(p);return True
        elif not self.detail and self.entries:
            step=(-1 if edges&0x10 else 1 if edges&0x40 else -7 if edges&0x400 else 7 if edges&0x800 else 0)
            if step:self.row=(self.row+step)%len(self.entries);dirty=True
            if edges&0x4000:self.detail=True;dirty=True
        elif self.detail:
            if edges&0xA0:self.cpu_only=not self.cpu_only;dirty=True
            if edges&0x4000:
                try:
                    entry=self.entries[self.row]
                    if entry['error']:raise ValueError(entry['error'])
                    self.launch(p,entry['document'],self.cpu_only)
                    self.close(p);return True
                except (OSError,ValueError,KeyError,TypeError) as e:self.notice=str(e);dirty=True
        if dirty:self.screen.show_picture(self.picture(),surface='menu',client=p)
        else:self.screen.sync(client=p)
        return True

    def launch(self,p,document,cpu_only=False):
        """The browser's Cross: arm one mission and let the native menus run it."""
        import native_mode_menu as menu
        from story_runtime import validate_compilation
        document=copy.deepcopy(document);validate_compilation(document)
        missions.arm(document);self.document=document
        p.write(CONTROL+20,struct.pack('<8I',1,1800,0,0,0,0xFFFFFFFF,0,0))
        # Semantic choices stay native: 1-player Team Battle or all CPU.
        p.write_u32(MENU+menu.PENDING_CHOICE,8 if cpu_only else 1)
        self.launched=True;self.left_main=False;self.route_deadline=time.monotonic()+60

    def quick_document(self):
        """Workbench "Test this mission" request (story_quicklaunch), polled at most once a second."""
        now=time.monotonic()
        if now>=self.quick_poll:
            import story_quicklaunch as quick
            self.quick_poll=now+1
            try:self.quick=quick.pending()
            except (OSError,TimeoutError,ValueError):self.quick=None
        return self.quick

    def service_quick(self,p,scene):
        """Start a Workbench quick-launch request once the Modded Modes page is open on the main menu
        (native_mode_menu opens it for the request) and the clean menu checkpoint is current."""
        import native_mode_menu as menu
        if self.launched or scene!=4 or not self.checkpoint_ready:return
        queued=self.quick_document()
        if queued is None or p.read_u32(MENU)!=menu.MAGIC or p.read_u32(MENU+4)!=2:return
        document,cpu_only=queued
        import story_quicklaunch as quick
        quick.taken(document);self.quick=None
        try:
            if p.read_u32(CONTROL)!=MAGIC:
                # Browser closed (state 0): the route program only needs our magic.
                p.write(CONTROL,struct.pack('<5I',MAGIC,0,0,0,p.read_u32(old.PAD+0x150)))
            self.launch(p,document,cpu_only)
            logging.info('Workbench quick launch: %s',document['title'])
        except (OSError,ValueError,KeyError,TypeError) as e:
            # Show why in the browser instead of starting anything.
            logging.warning('Workbench quick launch refused: %s',e)
            self.document=None;self.open(p);self.notice=str(e)
            self.screen.show_picture(self.picture(),surface='menu',client=p)

    def service_route(self,p,scene):
        if not self.launched or self.document is None:return
        state=p.read_u32(CONTROL+20)
        try:
            if state==100:raise ValueError('Scenario selector changed during setup; return to Modded Scenarios and retry')
            if state not in (1,2,3):return
            if scene not in (4,38,40):p.write_u32(CONTROL+20,4);return
            if time.monotonic()>self.route_deadline:
                raise ValueError('Scenario roster setup timed out; return to Modded Scenarios and retry')
            if state==1 and scene==40:
                plan=roster_records(p,self.document)
                if plan:
                    obj,counts,data,stage=plan
                    song=music_index(p,obj,self.document)
                    p.write_u32(CONTROL+52,song)
                    p.write(DATA,data);p.write(CONTROL+28,struct.pack('<6I',obj,*counts,*stage))
                    p.write_u32(CONTROL+20,2)
        except (ValueError,KeyError,TypeError) as e:
            # Reject only this launch, never disable all mod menus. Expiring
            # the transition lets the player use the native Back command.
            p.write_u32(CONTROL+20,0);p.write_u32(MENU+44,0)
            missions.consumed(self.document)
            self.notice=str(e);self.failed=True
            self.launched=False;self.document=None
            logging.warning('Scenario setup cancelled: %s',e)

    def shutdown(self):
        # Leases return input ownership without opening a fresh connection.
        self.active=False
        if self.launched and self.document:
            try:missions.consumed(self.document)
            except OSError:logging.warning('Could not clear the unfinished scenario selection',exc_info=True)
        self.launched=False;self.document=None
