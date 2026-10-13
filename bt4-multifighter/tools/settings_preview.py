"""Read-only HUD examples for the controller (in-game) settings screen, and the disc art both settings
screens draw with: the desktop window shows one picture per option instead (settings_thumbnails).

Native frames and gauges are decoded in memory from the selected player's disc;
no game artwork, RAM image or preview preference is stored in a release. Examples
are staged settings, never a connection to the emulator or a saved-setting edit.
"""
from functools import lru_cache
from pathlib import Path
import struct

import fonts
import game_profile
import localization

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ('HUD', 'Split-screen HUD', 'Fusion', 'Spectating', 'Revival', 'Tag-team rush', 'Training')
PHASES = ('Normal', 'Taking damage', 'Charging to Sparking', 'Sparking', 'Locked off')
SHORT_PHASES = ('Normal', 'Damage', 'Sparking charge', 'Sparking', 'Locked off')
TEXTS = ('Visual preview', 'Players', 'Example', 'Co-op', 'Co-op example', 'Preview uses unsaved changes.',
         'Example layout; game art comes from your selected disc.',
         'Disc art unavailable; showing a layout diagram.', 'Loading the game artwork…',
         'Select: visual preview', 'Select/Triangle: back    Cross: team/co-op',
         'L1/R1: players    L2/R2: example', 'Up/Down: setting    Left/Right: change',
         'Allies', 'Enemy', 'Target', 'TAG ATTACK', 'Kills 2', 'Goku defeated Frieza',
         'P{player} takes control in 3', 'Fused - P{player} has control', 'Fusion {seconds} s',
         'Stand nearby to revive', 'Reviving', 'Square to take over', 'Now controlling Goku',
         'Locked-off example has several enemies.',
         *PHASES,*SHORT_PHASES)


def available(group):
    return group in GROUPS


def selected_iso():
    installed = game_profile.iso_path()
    if installed:
        return Path(installed)
    import mod_settings
    name = ('SLUS_219.78.DBZBT4B14REV2ENG.iso' if mod_settings.ADAPTER == 'BT4'
            else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
    return ROOT.parent/'games'/name


class NativeArt:
    """Reviewed HUD package (25 descriptors), read only from the selected disc."""
    def __init__(self, bundle, portraits=(), reticle=None):
        count, words = struct.unpack_from('<2I', bundle)
        if count != 25 or words*4 < 32 or words*4+count*64 > len(bundle):
            raise ValueError('The disc has an unrecognized HUD texture table')
        self.bundle, self.table, self.portraits, self.reticle = bundle, words*4, tuple(portraits),reticle
        for index, shape in ((6, (256,64)), (8, (256,64)), (14, (128,64)), (16, (256,128))):
            tex0 = struct.unpack_from('<Q', bundle, self.table+64*index+48)[0]
            if ((1 << ((tex0 >> 26)&15)), (1 << ((tex0 >> 30)&15)), (tex0 >> 20)&63) != (*shape,19):
                raise ValueError('The disc has an unrecognized HUD atlas')

    @lru_cache(maxsize=32)
    def texture(self, index, palette=0):
        from PIL import Image
        import model_assets
        if not 0 <= index < 25 or not 0 <= index+palette < 25:
            raise ValueError('HUD atlas index outside its table')
        # Pixel descriptor stays the original atlas; only its CLUT descriptor
        # changes, exactly as the game's palette_delta drawing call does.
        source = self.table+64*index; pal = self.table+64*(index+palette)
        row = list(struct.unpack_from('<16I', self.bundle, source))
        prow = struct.unpack_from('<16I', self.bundle, pal)
        row[1], row[3] = prow[1], prow[3]
        data = self.bundle+struct.pack('<16I',*row)
        return Image.fromarray(model_assets.decode_texture(data, len(self.bundle)).rgba, 'RGBA')


@lru_cache(maxsize=3)
def _disc_art(path, size, modified):
    del size, modified  # part of the bounded cache identity, not a hash of the whole disc
    from model_assets import package_entry
    import sys
    parent = str(ROOT.parent)
    if parent not in sys.path:
        sys.path.insert(0,parent)
    from iso_compatibility.disc import Disc
    with Disc(path) as disc:
        # Same HUD resource in USA, B14 ENG/ES, Europe and Japan, with each
        # regional volume's actual file numbering. No mutable RAM assumptions.
        file_id = 7 if disc.region=='EU' else 6
        package=disc.read(file_id);bundle = package_entry(package,1)
    from PIL import Image
    folder = game_profile.assets_dir()/'portraits'
    portraits = []
    for cid in (0,22):
        try:
            with Image.open(folder/f'{cid:03d}.png') as im:
                portraits.append(im.convert('RGBA'))
        except (OSError,ValueError):
            portraits.append(None)
    # The original four-arrow reticle is in the same common UI resource.
    import model_assets
    prompt=package_entry(package,2);count,words=struct.unpack_from('<2I',prompt)
    reticle=None
    if count==9:
        reticle=Image.fromarray(model_assets.decode_texture(prompt,words*4+8*64).rgba,'RGBA')
        if reticle.size!=(64,64):reticle=None
    return NativeArt(bundle,portraits,reticle)


def disc_art():
    """None is a readable fallback: missing disc/dependencies never block settings."""
    try:
        path = selected_iso(); stamp = path.stat()
        return _disc_art(str(path), stamp.st_size, stamp.st_mtime_ns)
    except (OSError,ValueError,ImportError,struct.error):
        return None


@lru_cache(maxsize=3)
def _art_job(path, size, modified):
    """One bounded read per disc shared by every settings preview panel."""
    import threading
    job={'done':threading.Event(),'art':None}
    def read():
        try:job['art']=_disc_art(path,size,modified)
        except Exception:pass  # a damaged/unsupported disc must not trap settings input
        finally:job['done'].set()
    threading.Thread(target=read,daemon=True).start()
    return job


def art_job():
    try:
        path=selected_iso();stamp=path.stat()
        return _art_job(str(path),stamp.st_size,stamp.st_mtime_ns)
    except (OSError,ValueError):
        import threading
        done=threading.Event();done.set()
        return {'done':done,'art':None}


def viewports(players):
    if players not in (1,2,3,4):
        raise ValueError('Preview players must be from one through four')
    if players == 1:
        return ((0,0,512,448),)
    if players == 2:
        return ((0,0,255,448),(257,0,512,448))
    top = ((0,0,255,223),(257,0,512,223))
    return top+(((128,225,383,448),) if players == 3 else ((0,225,255,448),(257,225,512,448)))


def panel_boxes(settings, players, coop=False):
    """Authored native atlas coordinates and current post-code corner anchors."""
    wide = aspect_wide(settings); result = []
    if players==1:
        width=192 if wide else 256
        return (((0,0,width,64,False),(512-width,0,width,64,True)),)
    for seat, (left,top,right,bottom) in enumerate(viewports(players)):
        width = right-left; native = settings.get('split_hud_style','native') == 'native'
        bottom_layout = settings.get('split_hud_layout','top') == 'top_bottom'
        factor = .75 if wide and native else 1.
        if coop and settings.get('coop_hud_layout','players')=='players':
            size=width-8;own_right=seat%2==1
            x=left+4+(size*(1-factor) if own_right else 0)
            result.append(((x,top+5,size*factor,size/4,own_right),None));continue
        unscaled=(width-11)//2
        size = min(256,width-2) if bottom_layout else min(unscaled*settings.get('split_hud_scale_percent',100)//100,(width-14)//2)
        if players >= 3 and wide and native and not bottom_layout:
            size = min(unscaled*settings.get('split_hud_scale_percent',100)//100,148)
        inset = 1 if players == 2 else (4 if wide else 7)
        own_right = seat % 2 == 1
        target_inset = (22 if players==2 else (26 if wide else 16)) if top==0 and not bottom_layout else inset
        visible = size*factor
        own_x = right-inset-visible if own_right else left+inset
        target_size = size*(.85 if bottom_layout else 1.)
        target_width = target_size*factor
        target_x = left+target_inset if own_right else right-target_inset-target_width
        target_y = bottom-2-target_size/4 if bottom_layout else top+2
        result.append(((own_x,top+2,visible,size/4,own_right),
                       (target_x,target_y,target_width,target_size/4,not own_right)))
    return tuple(result)


@lru_cache(maxsize=24)
def _font(size, bold=False):
    return fonts.truetype(fonts.path('sans-bold' if bold else 'sans'),size)


def native_panel(art, settings, phase='Normal', portrait=0):
    """Compose the actual frame/gauges with the native sprite UV/node offsets."""
    from PIL import Image,ImageDraw
    panel = Image.new('RGBA',(512,128)); resample = Image.Resampling.LANCZOS
    def sprite(index,palette,uv,box):
        tile = art.texture(index,palette).crop(uv)
        x,y,x1,y1 = (round(2*v) for v in box)
        if x1>x and y1>y:
            panel.alpha_composite(tile.resize((x1-x,y1-y),resample),(x,y))
    sprite(6,0,(0,0,256,64),(0,0,256,64))
    if settings.get('show_hud_portraits',True) and art.portraits:
        p = art.portraits[portrait % len(art.portraits)]
        if p:
            panel.alpha_composite(p.resize((104,104),resample),(32,6))
    # Native nodes are health69,9; pips73,2; ki64,27 (not frame bounds).
    sprite(8,1,(0,0,160,16),(69,9,229,25))
    sprite(8,0,(0,0,160,16),(69,9,229,25))
    if phase == 'Taking damage' and settings.get('hud_damage_trail_seconds',.5) > 0:
        sprite(8,2,(0,0,139,16),(69,9,208,25))
    sprite(8,1,(0,0,102,16),(69,9,171,25))
    for pip in range(3):
        sprite(8,1,(0,16,16,32),(73+9*pip,2,89+9*pip,18))
    for band in range(5):
        sprite(8,1,(16,16,30,33),(64+8*band,27,78+8*band,44))
        if phase in ('Charging to Sparking','Sparking') and band < (3 if phase=='Charging to Sparking' else 5):
            sprite(8,5,(16,16,30,33),(64+8*band,27,78+8*band,44))
    sprite(15,0,(0,0,48,12),(27,46,75,58))
    sprite(8,1,(161,0,177,6),(34,49,50,55))
    sprite(14,0,(32,0,64,32),(7,30,39,62))
    if phase == 'Sparking' and settings.get('show_hud_sparking_effects',True):
        sprite(16,0,(0,0,64,64),(52,0,92,32))
        sprite(16,0,(64,0,128,64),(169,3,209,35))
    return panel


TAG_METER_WIDTH, TAG_METER_HEIGHT = 64, 2


def tag_meter_placement(view, settings, *, split=None, subject=0, coop=False, views=2):
    """Reviewed tag_rush_hud placement, without loading native gameplay or an extracted executable."""
    from regional import screen_y
    left, right, top, _bottom = view
    full_x, full_label, panel_label = (111, 66, 68) if _is_bt4() else (123, 38, 33)
    if split is None:
        x = left+full_x if not subject & 1 else right-full_x-TAG_METER_WIDTH
        y = top+screen_y(full_label)
        return x, y, y+9
    native = settings.get('split_hud_style', 'native') == 'native'
    if not native:
        y = top+screen_y(72)
        return right-8-TAG_METER_WIDTH, y, y+9
    width = right-left
    faces_right = bool(split & 1)
    if settings.get('split_hud_layout', 'top') == 'top_bottom':
        panel_width = min(width-2, 256)
        panel_x = right-1-panel_width if faces_right else left+1
        panel_y = top+2
    elif coop and settings.get('coop_hud_layout', 'players') == 'players':
        panel_x, panel_y, panel_width = left+4, top+5, width-8
    else:
        scale = settings.get('split_hud_scale_percent', 100)
        if not 80 <= scale <= 140:
            scale = 100
        panel_width = min((width-14)//2, ((width-11)//2)*scale//100)
        inset = 1 if views < 3 else 7
        panel_x = right-inset-panel_width if faces_right else left+inset
        panel_y = top+2
    offset = panel_width*118//256
    y = panel_y+min(panel_width*panel_label//256, 50)+3
    x = panel_x+panel_width-offset-TAG_METER_WIDTH if faces_right else panel_x+offset
    return x, y, y+9


def render(settings, *, players=2, phase='Normal', group='HUD', art=None, coop=False, size=(960,540)):
    """An example, including overlapping mod elements; no state/settings are edited."""
    from PIL import Image,ImageDraw,ImageOps
    if phase not in PHASES:
        raise ValueError('Unknown preview example')
    s = dict(settings); language = s.get('language','en')
    coop=bool(coop and players>1)
    if players==1:
        # These are choices for the mod's split-screen panels. The ordinary
        # one-player game frame retains its native dimensions and features.
        s.update(split_hud_style='native',split_hud_layout='top',split_hud_scale_percent=100,
                 show_hud_portraits=True,show_hud_sparking_effects=True,split_hud_filter='linear',hud_damage_trail_seconds=.5)
    def text(key,**values):return localization.tr(key,language,**values)
    image = Image.new('RGBA',(1024,896),'#0c1624'); d = ImageDraw.Draw(image)
    def box(rect,fill,outline=None):
        d.rectangle(tuple(round(v*2) for v in rect),fill=fill,outline=outline,width=2)
    def caption(x,y,line,color='#ffe9a6',point=9):
        d.text((round(x*2),round(y*2)),line,font=_font(point*2,True),fill=color,
               stroke_width=1,stroke_fill='#111a26')
    panes=viewports(players); panels=panel_boxes(s,players,coop)
    import multiview_layout as layout
    for seat, (left,top,right,bottom) in enumerate(panes):
        box((left,top,right,bottom),'#233a4a','#49616a')
        # A deliberately plain arena keeps artwork and settings easy to compare.
        box((left,top+(bottom-top)*.56,right,bottom),'#3b4940')
        center=(left+right)/2; ground=top+(bottom-top)*.74
        d.ellipse((2*(center-11),2*(ground-44),2*(center+11),2*(ground-22)),fill='#d8ba8a')
        d.line((2*center,2*(ground-22),2*center,2*(ground+8)),fill='#d48244',width=17)
        d.line((2*center,2*(ground+8),2*(center-10),2*(ground+26)),fill='#bccaeb',width=9)
        d.line((2*center,2*(ground+8),2*(center+10),2*(ground+26)),fill='#bccaeb',width=9)
        caption(left+7,bottom-18,f'P{seat+1}', '#aacada')
        if s.get('show_native_hud',True):
            player_only = coop and s.get('coop_hud_layout','players')=='players'
            no_target = phase=='Locked off' and s.get('lockoff_target_hud','single_enemy') != 'show'
            for role,panel_box in enumerate(panels[seat]):
                if role and (player_only or no_target):continue
                x,y,w,h,mirror=panel_box
                if s.get('split_hud_style','native')=='native' and art:
                    panel=native_panel(art,s,phase,role)
                    if mirror:panel=ImageOps.mirror(panel)
                    method=Image.Resampling.LANCZOS if s.get('split_hud_filter','linear')=='linear' else Image.Resampling.NEAREST
                    panel=panel.resize((max(1,round(w*2)),max(1,round(h*2))),method)
                    image.alpha_composite(panel,(round(x*2),round(y*2)))
                else:
                    # Explicitly labeled fallback or the selectable compact style.
                    box((x,y,x+w,y+13),'#0f2028','#adc5d2')
                    box((x+3,y+3,x+w*.72,y+7),'#55d55d')
                    box((x+3,y+9,x+w*.56,y+11),'#ffcd42')
                    caption(x+3,y+15,('P'+str(seat+1)) if role==0 else text('Target'),point=7)
        if players>1 and s.get('show_friendly_healthbars',True):
            box((center-17,ground-58,center+17,ground-54),'#65bfde','#0b1017')
        if s.get('show_enemy_healthbars',True):
            box((right-53,ground-58,right-19,ground-54),'#f28564','#0b1017')
        if phase!='Locked off' and s.get('lockon_target_marker',True):
            native_marker=art and art.reticle is not None and s.get('lockon_target_look','native')=='native'
            if s.get('lockon_target_style','arrow') in ('arrow','both'):
                if native_marker:
                    marker=art.reticle.crop((0,0,32,32)).rotate(-45,expand=True).resize((36,36),Image.Resampling.LANCZOS)
                    image.alpha_composite(marker,(round(2*(right-45)),round(2*(ground-59))))
                else:d.polygon(((2*(right-36),2*(ground-46)),(2*(right-41),2*(ground-52)),(2*(right-31),2*(ground-52))),fill='#ebce5c')
            if s.get('lockon_target_style','arrow') in ('ring','both'):
                if native_marker:
                    marker=art.reticle.resize((96,96),Image.Resampling.LANCZOS)
                    image.alpha_composite(marker,(round(2*(right-60)),round(2*(ground-48))))
                else:d.ellipse((2*(right-48),2*(ground-34),2*(right-24),2*(ground-12)),outline='#ebce5c',width=3)
        if s.get('tag_team_rush_enabled',False):
            tag_x,text_y,bar_y=tag_meter_placement((left,right,top,bottom),s,split=seat if players>1 else None,
                                                subject=seat,coop=coop,views=players)
            caption(tag_x,text_y,text('TAG ATTACK'),point=6)
            box((tag_x-1,bar_y-1,tag_x+TAG_METER_WIDTH+1,bar_y+TAG_METER_HEIGHT+1),'#374338','#b9c6b5')
            box((tag_x,bar_y,tag_x+(TAG_METER_WIDTH if s.get('tag_team_rush_training_full',False) and group=='Training' else round(TAG_METER_WIDTH*.7)),bar_y+TAG_METER_HEIGHT),'#d9de48')
        if s.get('show_kill_score',False):
            caption(left+8,top+(layout.SCORE_Y if players>=3 else 178),text('Kills 2'),point=7)
        if group=='Fusion' and s.get('fusion_enabled',True) and (players!=3 or seat<2):
            fy=top+(layout.FUSION_Y if players>=3 else 204)
            if players>1 and s.get('coop_fusion_controls','swap_20s')=='swap_20s':
                owner=1 if seat<2 else 3;next_player=2 if seat<2 else min(players,4)
                if s.get('show_fusion_control_owner',True):caption(left+10,fy,text('Fused - P{player} has control',player=owner),point=7)
                if s.get('show_fusion_control_countdown',True) and players!=3:caption(left+8,fy+12,text('P{player} takes control in 3',player=next_player),point=7)
            if s.get('fusion_duration_enabled',False) and s.get('show_fusion_timer',True):
                ty=fy+(24 if players>=3 else 28)
                caption(left+8,ty,text('Fusion {seconds} s',seconds=max(1,round(s.get('fusion_duration_seconds',40)*.6))),point=7)
                box((left+8,ty+12,left+128,ty+15),'#35463b')
                box((left+8,ty+12,left+92,ty+15),'#d9ed73')
        if group=='Spectating':
            sy=top+(layout.TAKEOVER_Y if players>=3 else 308)
            if s.get('show_takeover_hints',True):caption(left+8,sy,text('Square to take over'),point=7)
            if s.get('show_takeover_confirmation',True):caption(left+8,sy+14,text('Now controlling Goku'),point=7)
        if group=='Revival' and s.get('revive_enabled',False) and s.get('show_revive_ring',True):
            opacity=max(0,min(1,float(s.get('revive_ring_opacity',.45))))
            color=(75,230,100,round(255*opacity))
            radius=max(20,min(58,float(s.get('revive_radius',45))))
            wave=max(0,min(26,float(s.get('revive_ring_wave_height',8))))
            ring=Image.new('RGBA',image.size);rd=ImageDraw.Draw(ring)
            rd.ellipse((2*(center-radius),2*(ground+18-wave),2*(center+radius),2*(ground+38+wave)),outline=color,width=4)
            image.alpha_composite(ring)
            caption(center-radius,ground+43,text('Reviving'),point=7)
        if s.get('lockon_threat_marks','hide') not in (False,None,'hide'):
            d.polygon(((2*(right-6),2*(ground-8)),(2*(right-13),2*(ground-13)),(2*(right-13),2*(ground-3))),fill='#e17169')
        if s.get('show_kill_feed',True) and (players>=3 or seat==0):
            caption(left+8,top+(layout.FEED_Y if players>=3 else 250),text('Goku defeated Frieza'),point=7)
    if s.get('show_native_hud',True):
        box((237,0,275,20),'#24313f','#a8adb0');caption(245,3,'99',point=11)
    return image.convert('RGB').resize(size,Image.Resampling.LANCZOS)


def _is_bt4():
    import mod_settings
    return mod_settings.ADAPTER=='BT4'


def aspect_wide(settings):
    if settings.get('widescreen_patch',False):return True
    try:
        import widescreen_support
        return widescreen_support.embedded()
    except (OSError,ValueError):return False
