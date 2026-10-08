"""Viewport-local takeover offer and short ownership confirmation.

The offer executes the very same admission code as TAKE in read-only mode.
It cannot turn an ineligible fighter into an eligible one or request a takeover.
"""
from native_map import A
import struct
import localization
import math
from prototype import Assembler
import spectator_takeover as takeover
import spectator_switch as spec
import fresh_team_combat as core
import guest_killfeed as feed
import viewport_hud as hud
from regional import screen_y
from native_map import ACTOR_HZ

DRAW, PROBE, CONTROL, END = 0x07287000, 0x07289000, 0x0728D000, 0x0728E000
MAGIC = 0x53504631
PROMPT, CHORD, PREFIX = CONTROL+0x100, CONTROL+0x140, CONTROL+0x180
LIFETIME = 3*ACTOR_HZ  # native 30 Hz (European 25 Hz) update clock, not number of rendered viewports
OFFER_DELAY = ACTOR_HZ  # one second watching this body; never waits for a manual cycle
OFFER_SUBJECT, OFFER_SINCE = 32, 40  # two independent pad seats


CONFIG_MAGIC=0x53504632
CONFIG=64
DELAY,LIFESPAN,HINTS,CONFIRMATIONS=48,52,56,60


def option(a,target,offset,default):
    label=f'option{len(a.words)}';end=label+'end'
    a.li(11,CONTROL);a.lw(12,11,CONFIG);a.li(13,CONFIG_MAGIC);a.branch(5,12,13,label)
    a.lw(target,11,offset);a.jump(end);a.label(label);a.li(target,default);a.label(end)


def draw(automatic=True,configurable=True,quad=False):
    if quad:
        import quad_lifecycle as q
        import quad_viewports as views
        state,seat_control,fields,ports=q.FEEDBACK,q.CONTROL,q.F,4
        offer_subject,offer_since,expiry,probe=48,64,32,q.PROBE
    else:
        state,seat_control,fields,ports=CONTROL,spec.CONTROL,takeover.F,2
        offer_subject,offer_since,expiry,probe=OFFER_SUBJECT,OFFER_SINCE,24,PROBE
    a=Assembler(DRAW);hud.save(a);core.gate(a,'done')
    a.li(16,state);a.lw(8,16);a.li(9,MAGIC);a.branch(5,8,9,'done')
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'done')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,takeover.start.CONTROL);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x3900);a.branch(5,8,0,'done')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'done')
    a.li(8,A(0x2FEB38));a.lw(14,8);takeover.pointer(a,14,0x108,'done')
    a.lw(8,14);a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.li(8,seat_control);a.lw(9,8,fields['battle_mode'])
    a.addiu(10,0,takeover.modes.FFA);a.branch(4,9,10,'done')
    a.lw(17,28,-22176);takeover.pointer(a,17,832,'done')
    a.call(hud.ACTIVE);a.branch(4,2,0,'full')
    # Locate this world pass in the HUD's validated viewport descriptors.
    a.move(18,0);a.li(19,hud.VIEWS)
    a.label('view')
    a.lw(8,19);a.branch(4,8,0,'next')
    for native,descriptor in ((512,4),(516,8),(520,12),(524,16)):
        a.lw(8,17,native);a.lw(9,19,descriptor);a.branch(5,8,9,'next')
    a.jump('seat')
    a.label('next');a.addiu(18,18,1);a.addiu(19,19,hud.VIEW_STRIDE)
    a.addiu(8,0,ports);a.branch(5,18,8,'view');a.jump('done')
    a.label('full');a.move(18,0)
    # No offer while two humans share their fused fighter.
    a.li(8,takeover.modes.CONTROL);a.lw(9,8);a.li(10,takeover.modes.MAGIC)
    a.branch(5,9,10,'seat');a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'seat')
    a.lw(9,8,12);a.addiu(10,0,takeover.modes.COOP);a.branch(5,9,10,'seat')
    a.lw(9,8,24);a.li(10,core.MODE);a.lw(10,10,4);a.r(0x2B,9,9,10);a.branch(5,9,0,'done')
    a.label('seat');a.li(19,seat_control);a.lw(8,19,fields['human_ports'])
    a.addiu(9,0,1);a.r(4,9,18,9);a.r(0x24,8,8,9);a.branch(4,8,0,'done')
    a.r(0,8,0,18,2);a.r(0x2D,19,19,8);a.r(0x2D,16,16,8)
    a.lw(20,19,fields['owned']);a.li(8,core.MODE);a.lw(8,8,4)
    a.r(0x2B,9,20,8);a.branch(4,9,0,'done');a.lw(8,16,16)
    a.li(9,feed.CONTROL);a.lw(21,9,12);a.branch(4,8,20,'clock')
    a.sw(20,16,16)
    if configurable:option(a,8,LIFESPAN,LIFETIME);a.r(0x21,8,21,8)
    else:a.addiu(8,21,LIFETIME)
    a.sw(8,16,expiry)
    a.label('clock');a.lw(22,17,512);a.addiu(22,22,8)
    if quad:
        import multiview_layout
        a.lw(23,17,520);a.addiu(23,23,screen_y(multiview_layout.TAKEOVER_Y))
    else:a.lw(23,17,524);a.addiu(23,23,screen_y(-22))
    if configurable:option(a,8,CONFIRMATIONS,1);a.branch(4,8,0,'offer')
    a.lw(8,16,expiry);a.r(0x23,8,8,21);a.branch(6,8,0,'offer')
    # A just-defeated replacement should show a new offer, not stale success.
    a.li(8,feed.CONTROL+spec.DEAD);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,0,'offer')
    a.move(4,20);a.call(takeover.LOOKUP);a.branch(4,3,0,'done')
    a.li(8,core.POINTERS);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(4,8);a.call(feed.ROW)
    a.branch(4,2,0,'done');a.i(11,8,3,161);a.branch(4,8,0,'done')
    a.r(0,8,0,3,7);a.li(9,feed.NAMES);a.r(0x2D,24,8,9)
    a.addiu(25,29,0x140);a.li(8,PREFIX);a.move(9,25)
    a.label('prefix');a.i(36,10,8,0);a.branch(4,10,0,'name');a.i(40,10,9,0)
    a.addiu(8,8,1);a.addiu(9,9,1);a.jump('prefix')
    a.label('name');a.addiu(11,0,23)
    a.label('copy');a.i(36,10,24,0);a.branch(4,10,0,'terminate');a.i(40,10,9,0)
    a.addiu(24,24,1);a.addiu(9,9,1);a.addiu(11,11,-1);a.branch(5,11,0,'copy')
    a.label('terminate');a.i(40,0,9,0);a.jump('text')
    a.label('offer')
    if configurable:option(a,8,HINTS,1);a.branch(4,8,0,'offer_reset' if automatic else 'done')
    a.lw(8,19,fields['watching']);a.branch(4,8,0,'offer_reset' if automatic else 'done')
    if quad:
        a.r(0,8,0,18,2);a.li(9,views.SUBJECTS);a.r(0x2D,8,8,9);a.lw(5,8)
    else:
        a.lw(8,19,fields['view_side']);a.i(11,9,8,2);a.branch(4,9,0,'done')
        a.r(0,8,0,8,2);a.li(9,spec.CONTROL);a.r(0x2D,8,8,9)
        a.lw(5,8,spec.FIELDS['lock'])
        if automatic:
            a.branch(5,5,0,'chosen_subject');a.lw(8,19,fields['view_side'])
            a.r(0,8,0,8,2);a.li(9,takeover.fresh.SUCCESSOR_CONTROL)
            a.r(0x2D,8,8,9);a.lw(5,8,8);a.jump('offer_subject')
            a.label('chosen_subject');a.addiu(5,5,-1);a.label('offer_subject')
    if automatic:
        a.li(8,core.MODE);a.lw(8,8,4);a.r(0x2B,9,5,8);a.branch(4,9,0,'offer_reset')
        a.addiu(8,5,1);a.lw(9,16,offer_subject);a.branch(4,8,9,'offer_clock')
        a.sw(8,16,offer_subject);a.sw(21,16,offer_since);a.jump('done')
        a.label('offer_clock');a.lw(8,16,offer_since);a.r(0x23,8,21,8)
        if configurable:option(a,9,DELAY,OFFER_DELAY);a.r(0x2B,9,8,9)
        else:a.i(11,9,8,OFFER_DELAY)
        a.branch(5,9,0,'done')
    else:
        a.branch(4,5,0,'done');a.addiu(5,5,-1)
    a.move(4,18);a.call(probe);a.branch(4,2,0,'done')
    a.li(25,PROMPT);a.li(8,spec.lock.CONTROL);a.lw(8,8,spec.lock.FIELDS['button'])
    a.li(9,takeover.SQUARE);a.branch(5,8,9,'text');a.li(25,CHORD)
    a.label('text');hud.text(a,25,22,23,0x80E0F0FF)
    if automatic:
        a.jump('done');a.label('offer_reset');a.sw(0,16,offer_subject);a.sw(0,16,offer_since)
    a.label('done');hud.restore(a);a.jr()
    data=a.finish();assert len(data)<PROBE-DRAW;return data


def pieces(automatic=True,configurable=True,ordinary=True):
    probe=takeover.take(base=PROBE,commit=False,configurable=configurable,ordinary=ordinary)
    assert len(probe)<CONTROL-PROBE
    return [(DRAW,draw(automatic,configurable)),(PROBE,probe),
            (PROMPT,localization.guest('PRESS SQUARE TO TAKE OVER')+b'\0'),
            (CHORD,localization.guest('PRESS L2 AND SQUARE TO TAKE OVER')+b'\0'),
            (PREFIX,localization.guest('CONTROLLING ')+b'\0')]


def build_memory(ram,source='<prepared>',settings=None):
    if len(ram)!=0x8000000:raise ValueError('Spectator feedback requires captured 128 MiB RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    takeover.validate_memory(ram)
    if u(hud.CONTROL)!=hud.MAGIC or u(hud.CONTROL+4)!=u(core.ACTORS):
        raise ValueError('Spectator feedback requires captured viewport renderer')
    if u(CONTROL)==MAGIC:
        if u(CONTROL+4)!=u(core.ACTORS):raise ValueError('Spectator feedback manager changed')
        current=pieces();sizes={p:len(d) for p,d in current}
        matched=None
        for automatic,configurable,ordinary in ((a,c,o) for o in (True,False)
                for a,c in ((True,True),(True,False),(False,True),(False,False))):
            old=pieces(automatic,configurable,ordinary)
            if all(ram[p:p+len(d)]==d and not any(ram[p+len(d):p+sizes[p]]) for p,d in old):
                matched=old;break
        if matched is None:raise ValueError('Spectator feedback payload changed or extension occupied')
        changes=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in current if ram[p:p+len(d)]!=d]
        if settings is not None:changes+=option_blocks(ram,settings)
        return dict(blocks=changes,source=str(source))
    if any(ram[DRAW:END]):raise ValueError('Spectator feedback reservation occupied')
    control=bytearray(0x30);struct.pack_into('<2I',control,0,MAGIC,u(core.ACTORS))
    for port in range(2):struct.pack_into('<I',control,16+4*port,u(spec.CONTROL+takeover.F['owned']+4*port))
    data=pieces()+[(CONTROL,bytes(control))]
    return dict(source=str(source),control=CONTROL,blocks=[
        dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in data]+option_blocks(ram,settings or {}))


def option_blocks(ram,settings):
    import mod_settings
    opts=mod_settings.validate_settings(settings)
    data=struct.pack('<5I',math.ceil(opts['takeover_hint_seconds']*ACTOR_HZ),
        math.ceil(opts['takeover_confirmation_seconds']*ACTOR_HZ),int(opts['show_takeover_hints']),
        int(opts['show_takeover_confirmation']),CONFIG_MAGIC)
    p=CONTROL+DELAY
    return [] if ram[p:p+len(data)]==data else [dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex())]
