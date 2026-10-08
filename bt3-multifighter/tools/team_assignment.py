"""Controller-owned team setup before the native character selector: Player Setup and its controller check-in.

The chosen physical seats are a single receipt shared by selection, roster
validation and preparation. No choice changes the fighters' parity identities.

Player Setup is also a live controller panel (controller_checkin rules, controller_hub data): each row names its
controller, a light flashes with that player's presses, and an empty seat says how to join. The watcher's tick
never blocks: it reads hub snapshots only.
"""
import struct
import time
from localization import tr
from prototype import Assembler
import fonts

CODE, RESOLVE, END = 0x06911000, 0x06911800, 0x06912000
MENU, MAGIC = 0x076FF000, 0x324D4E42
STATE, CHOICE, BUTTONS, PREVIOUS, LEASE, HUMANS, VALID = range(0xA0,0xBC,4)
SEATS=0xC0
TEAM_CHOICES={7:2,10:2,12:4,17:3,15:4,20:3}
CHOICES={**TEAM_CHOICES,3:2,13:4,18:3}
HOST_LEASE=300          # guest frames the host's lease lasts (MENU+LEASE and the pager's MENU+16)
REDRAW=0.25             # at most four redraws a second
LIGHT_GAP,LIGHT_MIN=0.25,0.15   # a light stays lit while presses are this close, and at least this long
SLOW_TICK=0.25          # ticks longer than this are logged
STARTING=5.0            # seconds Player Setup waits for the controller reader before the default order applies

# Panel texts (Spanish in localization.ES).
TITLE_TEAMS,TITLE_PLAYERS='CHOOSE YOUR TEAMS','PLAYER SETUP'
INTRO='Each player: press START on your own controller to join.'
EMPTY='Press START on your controller to join'
DEFAULT='PCSX2 controller {k} (default order)'
CLASSIC='Controller {k} (connection order): {name}'
NATIVE='{name} (PCSX2 controller {k})'
PSEUDO='Keyboard / PCSX2 controller {k}'
LOST='Controller lost: reconnect it, or hold START on another'
CONTINUE,CLEAR='Continue','Clear check-ins'
WAITING='Waiting for players {list} to join.'
WAITING_ONE='Waiting for player {list} to join.'
READY='Everyone is in. Player 1: Continue.'
CONNECTING='Connecting controllers…'
UNAVAILABLE="The mod's controller reader did not start: players 3 and 4 cannot join (TTM-CTRL-20)."
NOTICES={
    'keyboard_taken':'The keyboard can only be player {k}. Player {k}: press SELECT to free that seat.',
    'twin':'One controller appears twice (DS4Windows or Steam Input?): the mod uses one copy and ignores the other (TTM-CTRL-23).',
    'double':'{name} also moves player {k} through PCSX2: remove it from PCSX2 controller port {k} (TTM-CTRL-24).',
    'unmapped':'{name} has no gamepad layout here; it can still play as player 1 or 2 through PCSX2 (TTM-CTRL-21).',
}
NOTICE_SECONDS=8.0
FOOTER_P1='Player 1: Up/Down select · Left/Right team · Cross continue · Triangle back'
FOOTER_ALL='Everyone: START join · Left/Right own team · SELECT leave'
# Free-for-all has no teams: its footers leave Left/Right out.
FOOTER_P1_FFA='Player 1: Up/Down select · Cross continue · Triangle back'
FOOTER_ALL_FFA='Everyone: START join · SELECT leave'
GOLD,WHITE,DIM,GREEN,RED,PANEL,EDGE,BLUE,ORANGE,BG,TEXT=((249,197,90),(242,244,249),(150,162,182),(117,227,161),
    (240,104,92),(31,46,66),(64,80,102),(71,184,241),(246,120,102),(10,16,28),(203,216,234))
BAR,SLOT_TEXT=(245,184,63),(219,228,240)
_PALETTE=None


def palette():
    """The panel's 16 fixed colours: every drawn colour exactly, plus three title edge tones (gold over the
    background). A median-cut palette merged orange into gold and grey into orange depending on the seats shown."""
    global _PALETTE
    if _PALETTE is None:
        from PIL import Image
        colors=[BG,PANEL,EDGE,GOLD,WHITE,DIM,GREEN,RED,BLUE,ORANGE,TEXT,BAR,SLOT_TEXT]
        colors+=[tuple(round(b+(f-b)*s) for f,b in zip(GOLD,BG)) for s in (1/4,1/2,3/4)]
        image=Image.new('P',(1,1));flat=[c for rgb in colors for c in rgb]
        image.putpalette(flat+flat[:3]*(256-len(colors)));_PALETTE=image
    return _PALETTE


def physical_seats(teams):
    if len(teams) not in (2,3,4) or any(type(t)is not int or t not in (0,1) for t in teams):
        raise ValueError('Assign each of the two to four players to Team 1 or Team 2')
    counts=[0,0];result=[]
    for team in teams:
        result.append(2*counts[team]+team);counts[team]+=1
    return tuple(result)


def selected(ram,mode,humans):
    if mode not in ('teams','training') or humans<2:return None
    u=lambda p:struct.unpack('<I',ram[p:p+4])[0]
    if u(MENU)!=MAGIC or u(MENU+VALID)!=1:return None
    choice=u(MENU+60)
    if CHOICES.get(choice)!=humans:return None
    result=tuple(u(MENU+SEATS+4*i) for i in range(humans))
    if result!=physical_seats(tuple(i&1 for i in result)):
        raise ValueError('Player team assignment is corrupt or stale')
    return result


def input_code():
    import mode_menu as menu
    a=Assembler(CODE);a.li(8,MENU);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'no')
    a.lw(9,8,STATE);a.addiu(10,0,1);a.branch(5,9,10,'no')
    a.lw(9,8,LEASE);a.branch(4,9,0,'expire');a.addiu(9,9,-1);a.sw(9,8,LEASE)
    a.li(9,menu.MAIN_CALLER);a.branch(5,4,9,'no')
    a.li(9,menu.SCENE_MANAGER);a.lw(9,9);a.li(10,0x100000);a.r(0x2B,10,9,10);a.branch(5,10,0,'expire')
    a.li(10,0x1FFF000);a.r(0x2B,10,9,10);a.branch(4,10,0,'expire')
    a.lw(9,9,0x18);a.addiu(10,0,4);a.branch(5,9,10,'expire')
    a.lw(9,8,4);a.addiu(10,0,2);a.branch(5,9,10,'expire')
    a.li(9,menu.PAD);a.lw(10,9,0x150);a.lw(11,8,PREVIOUS);a.sw(10,8,PREVIOUS)
    a.i(14,11,11,0xFFFF);a.r(0x24,10,10,11);a.lw(11,8,BUTTONS);a.r(0x25,10,10,11);a.sw(10,8,BUTTONS)
    a.sw(0,9,0x18C);a.sw(0,9,0x190);a.addiu(2,0,1);a.jr()
    a.label('expire');a.sw(0,8,STATE);a.sw(0,8,BUTTONS);a.sw(0,8,VALID)
    a.label('no');a.move(2,0);a.jr();return a.finish()


def resolve_code():
    # Input t5=selection side, t6=slot; preserve both and t3=selector owner.
    a=Assembler(RESOLVE);a.li(8,MENU);a.lw(10,8,VALID);a.addiu(24,0,1)
    a.branch(5,10,24,'legacy');a.lw(9,8,60)
    for choice in TEAM_CHOICES:
        a.addiu(10,0,choice);a.branch(4,9,10,'assigned')
    a.jump('legacy');a.label('assigned')
    a.r(0,24,0,14,1);a.r(0x21,24,24,13)
    for seat in range(4):
        a.lw(10,8,SEATS+4*seat);a.branch(5,10,24,f'next{seat}')
        a.addiu(2,0,seat+1);a.jr();a.label(f'next{seat}')
    a.addiu(2,0,1);a.jr();a.label('legacy');a.move(2,0);a.jr();return a.finish()


def code_pieces():return [(CODE,input_code())]


def player_list(numbers,settings=None):
    """'1, 2, 3, 4' / '1, 2, 3 y 4' for the waiting notice."""
    import localization
    names=[str(n) for n in numbers]
    if len(names)<2:return ''.join(names)
    last=' y ' if localization.language(settings)=='es' else ', '
    return ', '.join(names[:-1])+last+names[-1]


class Controller:
    def __init__(self):
        self.active=False;self.screen=None;self.row=0;self.teams=[];self.choice=None;self.input_ready=False
        self.hub=None;self.settings={};self.view=None;self.log=None
        self.lit=set();self.light={};self.drawn=None;self.drawn_at=0.0;self.dirty=False;self.opened_at=None

    # ---- what the panel shows -----------------------------------------------------------------------------------------
    def seats(self):
        """[(kind, text, light key)] per player row: kind empty / default / pad / lost."""
        view,humans=self.view,len(self.teams)
        roster=view.roster if view is not None and view.state=='ready' else None
        rows=[]
        for number in range(1,humans+1):
            seat=roster.seat(number) if roster is not None and roster.humans==humans else None
            source=seat.source if seat is not None else ('default' if number<=2 else 'classic')
            if seat is not None and seat.lost:rows.append(('lost',tr(LOST),seat.key));continue
            if source=='empty':rows.append(('empty',tr(EMPTY),None))
            elif source=='default':rows.append(('default',tr(DEFAULT,k=number),f'pcsx2:{number}'))
            elif source=='native':rows.append(('pad',tr(NATIVE,name=seat.name,k=number),seat.key))
            elif source=='pseudo':
                text=tr(NATIVE,name=seat.name,k=number) if seat.name else tr(PSEUDO,k=number)
                rows.append(('pad',text,seat.key))
            elif source=='hub':rows.append(('pad',seat.name,seat.key))
            else:
                classic=list(getattr(view,'classic',None) or [])
                key=classic[number-3] if 0<=number-3<len(classic) else None
                device=(getattr(view,'devices',None) or {}).get(key)
                rows.append(('pad' if device else 'default',tr(CLASSIC,k=number,name=device.display if device else '—'),key))
        return rows

    def ready(self):
        """Continue is accepted: without a hub or a working reader the default order applies at once; while the reader
        starts, not yet; otherwise every seat is filled (controller_checkin.ready)."""
        view=self.view
        if view is None or view.state=='failed':return True
        if view.state in ('off','starting'):
            # A reader that never comes up must not lock Player Setup: the default order after STARTING seconds.
            return self.opened_at is not None and time.monotonic()-self.opened_at>=STARTING
        if view.roster is None or view.roster.humans!=len(self.teams):return True
        return bool(view.ready)

    def notice(self):
        """(text, warning) under the buttons."""
        view=self.view
        if view is None:return tr(READY),False
        if view.state=='failed':return tr(UNAVAILABLE),True
        if view.state in ('off','starting'):return tr(CONNECTING),False
        if view.notice is not None and view.now-view.notice[2]<=NOTICE_SECONDS and view.notice[0] in NOTICES:
            kind,values,_=view.notice
            return tr(NOTICES[kind],**values),True
        if view.roster is not None and view.waiting:
            return tr(WAITING if len(view.waiting)>1 else WAITING_ONE,list=player_list(view.waiting)),False
        return tr(READY),False

    def picture(self):
        from PIL import Image,ImageDraw
        im=Image.new('RGB',(512,448),BG);d=ImageDraw.Draw(im)
        title=fonts.truetype('sans-bold',25)
        font=fonts.truetype('sans-bold',17)
        small=fonts.truetype('sans',13)
        d.rectangle((0,0,511,4),fill=BAR)
        d.text((24,16),tr(TITLE_PLAYERS if self.choice not in TEAM_CHOICES else TITLE_TEAMS),font=title,fill=GOLD)
        d.fontmode='1'   # crisp text below: one colour per glyph run
        self.overflow=[]
        def line(text,y,color=TEXT,lines=2):
            # Keep translated text inside the actual 512-pixel surface; a cut text ends with an ellipsis.
            words=text.split();row='';count=0
            for index,word in enumerate(words):
                trial=(row+' '+word).strip()
                if row and d.textlength(trial,font=small)>462:
                    if count+1>=lines:
                        self.overflow.append(text)
                        while row and d.textlength(row+'…',font=small)>462:row=row[:-1]
                        row=row.rstrip()+'…';break
                    d.text((25,y),row,font=small,fill=color);y+=17;row=word;count+=1
                else:row=trial
            d.text((25,y),row,font=small,fill=color)
        def columns(text,y,color):
            parts=[part.strip() for part in text.split('·')]
            widths=[d.textlength(part,font=small) for part in parts]
            gap=max(8,(462-sum(widths))/max(1,len(parts)-1)) if len(parts)>1 else 0
            x=25
            for part,width in zip(parts,widths):d.text((round(x),y),part,font=small,fill=color);x+=width+gap
        line(tr(INTRO),50,lines=1)
        seats=physical_seats(self.teams)
        for i,(team,(kind,text,_)) in enumerate(zip(self.teams,self.seats())):
            y=74+i*50;selected=i==self.row
            d.rounded_rectangle((20,y,491,y+45),radius=7,fill=PANEL,outline=GOLD if selected else EDGE,width=2)
            d.text((33,y+3),tr(f'PLAYER {i+1}'),font=font,fill=WHITE)
            if self.choice in TEAM_CHOICES:
                d.text((196,y+3),tr(f'<  TEAM {team+1}  >'),font=font,fill=(BLUE,ORANGE)[team])
                # The word and the number apart: crisp glyphs would close up the space between them.
                word,number=tr(f'SLOT {seats[i]//2+1}').rsplit(' ',1)
                d.text((400,y+6),word,font=small,fill=SLOT_TEXT)
                d.text((400+round(d.textlength(word,font=small))+5,y+6),number,font=small,fill=SLOT_TEXT)
            color={'empty':GOLD,'default':DIM,'pad':GREEN,'lost':RED}[kind]
            if kind=='empty':d.ellipse((34,y+29,42,y+37),outline=color,width=2)
            elif kind=='lost':d.rectangle((37,y+27,39,y+34),fill=color);d.rectangle((37,y+36,39,y+38),fill=color)
            else:d.ellipse((34,y+29,42,y+37),fill=color)
            d.text((50,y+25),text,font=small,fill=TEXT if kind=='pad' else color)
            lit=i in self.lit
            d.rounded_rectangle((462,y+24,482,y+40),radius=4,fill=GOLD if lit else BG,outline=GOLD if lit else EDGE,width=1)
        base=74+len(self.teams)*50+6
        ready=self.ready()
        for j,label in enumerate((CONTINUE,CLEAR)):
            y=base+j*33;row=len(self.teams)+j
            d.rounded_rectangle((20,y,491,y+28),radius=6,fill=PANEL,outline=GOLD if self.row==row else EDGE,width=2)
            d.text((33,y+4),tr(label),font=font,fill=WHITE if (j or ready) else DIM)
        text,warning=self.notice()
        line(text,max(base+70,352),RED if warning else TEXT)
        teams=self.choice in TEAM_CHOICES
        columns(tr(FOOTER_P1 if teams else FOOTER_P1_FFA),396,TEXT)
        columns(tr(FOOTER_ALL if teams else FOOTER_ALL_FFA),420,GOLD)
        return im.quantize(palette=palette(),dither=Image.Dither.NONE).convert('RGB')

    # ---- lights ---------------------------------------------------------------------------------------------------------
    def lights(self,now):
        """Rows whose player pressed something recently: lit while presses are under LIGHT_GAP apart and for at least
        LIGHT_MIN, so mashing does not redraw."""
        presses=getattr(self.view,'presses',None) or {}
        lit=set()
        for i,(_,_,key) in enumerate(self.seats()):
            count,last=presses.get(key,(0,0.0)) if key else (0,0.0)
            seen,since=self.light.get(i,(count,None))
            if count!=seen:since=since if since is not None else now
            if since is not None and (now-last<LIGHT_GAP or now-since<LIGHT_MIN):lit.add(i)
            else:since=None
            self.light[i]=(count,since)
        return lit

    # ---- the watcher's tick -------------------------------------------------------------------------------------------
    def snapshot(self):
        if self.hub is None:return None
        try:return self.hub.snapshot()
        except RuntimeError:return None   # a hub that does not answer: the panel shows the default order

    def tick(self,p):
        started=time.monotonic()
        try:return self._tick(p)
        finally:
            spent=time.monotonic()-started
            if spent>SLOW_TICK and self.active:
                (self.log or (lambda text:print(time.strftime('%H:%M:%S'),text,flush=True)))(f'Player Setup tick took {spent*1000:.0f} ms.')

    def _tick(self,p):
        wanted=p.read_u32(MENU)==MAGIC and p.read_u32(MENU+STATE)==1
        if not wanted:
            if self.active:self.close(p)
            return False
        choice=p.read_u32(MENU+CHOICE)
        if choice not in CHOICES:raise ValueError('Unknown player assignment request')
        if not self.active:
            from guest_loading_screen import GuestLoadingScreen
            self.screen=GuestLoadingScreen();self.active=True;self.choice=choice
            self.row=0;self.teams=[i&1 for i in range(CHOICES[choice])];self.input_ready=False
            self.lit=set();self.light={};self.drawn=None;self.dirty=True;self.opened_at=time.monotonic()
            if self.hub is not None:
                try:
                    self.hub.start()
                    self.hub.open_setup(len(self.teams),choice in TEAM_CHOICES,
                                        mode=self.settings.get('controller_checkin'),
                                        keep=self.settings.get('keep_controller_checkins'))
                except RuntimeError:pass
        p.write_u32(MENU+LEASE,HOST_LEASE);p.write_u32(MENU+16,HOST_LEASE)
        now=time.monotonic()
        self.view=self.snapshot()
        roster=self.view.roster if self.view is not None and self.view.state=='ready' else None
        if roster is not None and roster.humans==len(self.teams) and self.choice in TEAM_CHOICES:
            self.teams=[seat.team for seat in roster.seats]
        buttons=p.read_u32(MENU+BUTTONS)
        if buttons:p.write_u32(MENU+BUTTONS,0)
        if buttons&0x1000:
            p.write_u32(MENU+STATE,0);p.write_u32(MENU+VALID,0);self.close(p);return True
        if not self.screen.presented(p):buttons=0
        elif not self.input_ready:
            import mode_menu
            self.input_ready=p.read_u32(mode_menu.PAD+0x150)==0
            buttons=0
        rows=len(self.teams)+2
        if buttons&0x50:self.row=(self.row+(1 if buttons&0x40 else -1))%rows;self.dirty=True
        if buttons&0xA0 and self.row<len(self.teams) and self.choice in TEAM_CHOICES:
            self.teams[self.row]^=1;self.dirty=True
            if self.hub is not None:
                try:self.hub.set_team(self.row+1,self.teams[self.row])
                except RuntimeError:pass
        if buttons&0x4000:
            if self.row==len(self.teams)+1:
                if self.hub is not None:
                    try:self.hub.clear_checkins()
                    except RuntimeError:pass
                    self.view=self.snapshot()
                self.dirty=True
            elif self.ready():
                seats=physical_seats(self.teams)
                p.write(MENU+SEATS,struct.pack('<4I',*(seats+(0xFFFFFFFF,)*(4-len(seats)))))
                p.write_u32(MENU+HUMANS,len(seats));p.write_u32(MENU+VALID,int(self.choice in TEAM_CHOICES))
                self.close(p,commit=True)
                # The guest performs the ordinary dispatch only after this receipt
                # has been published completely and the overlay has disappeared.
                p.write_u32(MENU+STATE,2);return True
        self.lit=self.lights(now)
        state=(tuple(self.teams),self.row,tuple(self.seats()),frozenset(self.lit),self.ready(),self.notice())
        if state!=self.drawn:self.dirty=True
        if self.dirty and now-self.drawn_at>=REDRAW:
            self.screen.show_picture(self.picture(),surface='menu',client=p)
            self.drawn,self.drawn_at,self.dirty=state,now,False
        else:self.screen.sync(client=p)
        return True

    def close(self,p,commit=False):
        import mode_menu
        p.write_u32(MENU+28,p.read_u32(mode_menu.PAD+0x150))
        if self.screen:self.screen.hide(client=p)
        if self.hub is not None and self.active:
            try:self.hub.close_setup(commit)
            except RuntimeError:pass
        self.screen=None;self.active=False

    def shutdown(self):
        if self.hub is not None and self.active:
            try:self.hub.close_setup(False)
            except RuntimeError:pass
        self.active=False
