"""Opt-in battle camera zoom-out for the fighters a player is watching.

One call hook inside the native camera update 1C69C8, right after the solver
dispatch, scales the fresh follow, lock-on or tight (0xDC/0xB8) solver eye
about its focus, before shake, arena clamp, smoothing and terrain collision.
Scripted cameras, the 0xCC hold and every global cinematic keep their native
framing; they start from and blend back to the zoomed view.

Only displayed view subjects are zoomed: the game's AI reads its own camera
(obstruction flag and yaw), so zooming an unwatched CPU would change its play.
The zoom never pushes an eye beyond max(solver distance, LIMIT), so it only
trims giant-size bodies and never shortens a native or giant distance.

Two more call hooks hand native smoothing the unzoomed eye, so its lag and
rotation smoothing stay the game's own at every zoom. At 100% nothing is
installed; an installed match switched back to 100% only goes inert.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import battle_mode_policy as modes
import fresh_team_camera as fresh
import quad_viewports as quad
import hud_subject
import mod_settings

KEY = 'battle_camera_distance_percent'
BASE, END = 0x06960000, 0x06961000
ZOOM, SMOOTH, SNAP, CONTROL = BASE, BASE+0x400, BASE+0x500, BASE+0xF00
MAGIC = 0x5A4F4D31  # 'ZOM1'
LIMIT = 150.0       # world units: the zoom never pushes an eye beyond max(solver distance, LIMIT)
# CONTROL: magic, manager, count, enabled, factor (float), then runtime words:
# LAST actor zoomed in this camera update (else 0), DELTA x/y/z (float),
# zoomed/compensated/capped update counters. +48..+0xFF stay zero.
LAST, DELTA, ZOOMED, COMPENSATED, CAPPED = 20, 24, 36, 40, 44
SITE, SMOOTH_SITE, SNAP_SITE = A(0x1C6B3C), A(0x1C6C04), A(0x1C6C44)
SMOOTH_NATIVE, SNAP_NATIVE = A(0x1C4DB8), A(0x1C4D38)
# Native words at the sites: addiu s1,s3,0x50 (replayed by ZOOM), jal 1C4DB8, jal 1C4D38.
# Their delay slots (move a1,s0 / movn s1,zero,v0 / move a2,s7) are kept.
SITE_WORD = 0x26710050
DELAY_WORDS = {SITE: 0x0200282D, SMOOTH_SITE: 0x0002880B, SNAP_SITE: 0x02E0302D}
NATIVE = elf_reader(elf_path(ROOT))[2]


def fop(a,fn,d,s,t=0):a.emit((17<<26)|(16<<21)|(t<<16)|(s<<11)|(d<<6)|fn)


def mtc1(a,r,f):a.emit((17<<26)|(4<<21)|(r<<16)|(f<<11))


def fbits(v):return struct.unpack('<I',struct.pack('<f',v))[0]


def jal(entry):return struct.pack('<I',(3<<26)|(entry>>2))


def zoom_code():
    """Entered by jal at SITE (delay slot already run); returns to SITE+8.

    No frame, no call; t0..t7 and f0..f12 only. Live: s2 actor, s3 actor+0x420,
    s4/s5 solver flags, s7 focus, eye at sp+0. Sets s1 exactly as native.
    """
    a=Assembler(ZOOM)
    a.li(8,CONTROL);a.sw(0,8,LAST)                                  # never leave a stale LAST
    a.r(0x25,9,20,21);a.branch(4,9,0,'done')                        # s4|s5: follow, lock, 1C5840; scripted/hold -> native
    core.gate(a,'done')                                             # t0..t2, t2 = count
    a.li(8,CONTROL);a.lw(9,8,0);a.li(11,MAGIC);a.branch(5,9,11,'done')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'done')
    a.lw(9,8,8);a.branch(5,9,10,'done')
    a.lw(9,8,12);a.branch(4,9,0,'done')
    a.lw(12,18,0);a.r(0x2B,9,12,10);a.branch(4,9,0,'done')          # t4 = physical < count
    a.r(0,9,0,12,2);a.li(11,core.POINTERS);a.r(0x21,11,11,9);a.lw(11,11);a.branch(5,11,18,'done')
    # Mod 2/3/4-view: the published subjects of this match.
    a.li(13,quad.CONTROL);a.lw(14,13);a.li(15,quad.MAGIC);a.branch(5,14,15,'sides')
    a.lw(14,13,4);a.lw(15,28,-22364);a.branch(5,14,15,'sides')
    a.lw(14,13,quad.VIEW_COUNT);a.i(11,15,14,5);a.branch(4,15,0,'done')
    a.li(13,quad.SUBJECTS)
    a.label('view');a.branch(4,14,0,'done');a.lw(15,13);a.branch(4,15,12,'scale')
    a.addiu(13,13,4);a.addiu(14,14,-1);a.jump('view')
    # Single view and native split: the team camera's side owners.
    a.label('sides')
    a.li(13,fresh.SUCCESSOR_CONTROL);a.lw(14,13);a.addiu(15,0,1);a.branch(5,14,15,'done')
    a.lw(14,13,4);a.lw(15,28,-22364);a.branch(5,14,15,'done')
    a.li(14,hud_subject.SCENE);a.lw(14,14,hud_subject.SPLIT_OFF);a.addiu(15,0,hud_subject.SPLIT_VALUE)
    a.branch(5,14,15,'single')
    a.lw(14,13,8);a.branch(4,14,12,'scale');a.lw(14,13,12);a.branch(4,14,12,'scale');a.jump('done')
    a.label('single');a.li(14,fresh.LEADER_CONTROL);a.lw(14,14,12);a.i(11,15,14,2)
    a.branch(5,15,0,'side');a.move(14,0)                            # side >= 2 falls back to side 0
    a.label('side');a.r(0,14,0,14,2);a.r(0x21,14,13,14);a.lw(14,14,8);a.branch(5,14,12,'done')
    a.label('scale')
    for i,off in enumerate((0,4,8)):                                # f5..f7 = eye - focus
        a.i(49,0,29,off);a.i(49,1,23,off);fop(a,1,5+i,0,1)
    fop(a,2,8,5,5);fop(a,2,9,6,6);fop(a,0,8,8,9);fop(a,2,9,7,7);fop(a,0,8,8,9)   # f8 = d^2
    a.i(49,3,8,16)                                                  # f3 = k
    fop(a,2,9,3,3);fop(a,2,10,9,8)                                  # f10 = k^2 d^2
    a.li(9,fbits(LIMIT*LIMIT));mtc1(a,9,11)                         # f11 = LIMIT^2
    fop(a,0x36,0,10,11);a.branch(17,8,1,'apply')                    # c.le.s: within LIMIT -> full factor
    a.lw(9,8,CAPPED);a.addiu(9,9,1);a.sw(9,8,CAPPED)
    fop(a,0x36,0,11,8);a.branch(17,8,1,'done')                      # already at/after LIMIT: keep native/giant distance
    a.emit(0);a.emit(0);fop(a,4,9,0,8)                              # sqrt.s f9,f8 (EE: operand in ft)
    a.li(9,fbits(LIMIT));mtc1(a,9,12)
    a.emit(0);a.emit(0);fop(a,3,3,12,9)                             # f3 = LIMIT / d
    a.label('apply')
    for i,off in enumerate((0,4,8)):
        a.i(49,0,29,off);a.i(49,1,23,off)
        fop(a,2,2,5+i,3);fop(a,0,2,2,1);fop(a,1,4,2,0)              # f2 = focus + k*(eye-focus); f4 = f2 - eye
        a.i(57,2,29,off);a.i(57,4,8,DELTA+off)
    a.sw(18,8,LAST);a.lw(9,8,ZOOMED);a.addiu(9,9,1);a.sw(9,8,ZOOMED)
    a.label('done');a.addiu(17,19,0x50)                             # replay the replaced native word
    a.jr()
    return a.finish()


def compensation_code(entry,native):
    """Native smoothing reads the eye through a1 only: hand it eye-DELTA (the unzoomed eye plus shake)."""
    a=Assembler(entry)
    a.li(8,CONTROL);a.lw(9,8,LAST);a.branch(4,9,0,'native');a.branch(5,9,4,'native')
    a.addiu(29,29,-0x20);a.i(63,31,29,0x10)
    for off in (0,4,8):
        a.i(49,0,5,off);a.i(49,1,8,DELTA+off);fop(a,1,0,0,1);a.i(57,0,29,off)
    a.lw(9,5,12);a.sw(9,29,12)
    a.lw(9,8,COMPENSATED);a.addiu(9,9,1);a.sw(9,8,COMPENSATED)
    a.move(5,29);a.call(native)                                     # factor comes back in f0, untouched
    a.i(55,31,29,0x10);a.addiu(29,29,0x20);a.jr()
    a.label('native');a.jump(native)                                # tail call, a1 untouched
    return a.finish()


def pieces():
    out=[(ZOOM,zoom_code()),(SMOOTH,compensation_code(SMOOTH,SMOOTH_NATIVE)),(SNAP,compensation_code(SNAP,SNAP_NATIVE))]
    for (p,d),nxt in zip(out,(SMOOTH,SNAP,CONTROL)):assert p+len(d)<=nxt,(hex(p),len(d))
    return out


HOOKS=((SITE,ZOOM),(SMOOTH_SITE,SMOOTH),(SNAP_SITE,SNAP))


def native_sites():
    """The 8 native bytes each hook site must hold (its word and the kept delay slot)."""
    return {SITE:struct.pack('<2I',SITE_WORD,DELAY_WORDS[SITE]),
            SMOOTH_SITE:jal(SMOOTH_NATIVE)+struct.pack('<I',DELAY_WORDS[SMOOTH_SITE]),
            SNAP_SITE:jal(SNAP_NATIVE)+struct.pack('<I',DELAY_WORDS[SNAP_SITE])}


def check_native():
    """Guards PAL and BT4 mapping errors: the adapter's executable must hold the expected instructions."""
    for site,expected in native_sites().items():
        if NATIVE(site,8)!=expected:raise ValueError('Battle camera native site is not the expected instruction')


@modes.matching_install
def build_memory(ram,settings=None,source='<prepared>'):
    s=mod_settings.validate_settings(settings or {});u=lambda p:struct.unpack_from('<I',ram,p)[0]
    pct=s[KEY];installed=u(CONTROL)==MAGIC
    if not installed and pct==100:return dict(blocks=[])
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Battle camera zoom requires a captured active match')
    check_native()
    control=struct.pack('<4If',MAGIC,manager,count,int(pct!=100),pct/100)
    code=pieces();sites=native_sites()
    if installed:
        if (u(CONTROL+4),u(CONTROL+8))!=(manager,count):raise ValueError('Battle camera zoom belongs to another match')
        expected=code+[(site,jal(entry)+sites[site][4:]) for site,entry in HOOKS]
        if any(ram[p:p+len(d)]!=d for p,d in expected):raise ValueError('Battle camera zoom code changed')
        patches=[(CONTROL,control)]
    else:
        if any(ram[BASE:END]):raise ValueError('Battle camera zoom reservation occupied')
        if (u(fresh.SUCCESSOR_CONTROL),u(fresh.SUCCESSOR_CONTROL+4))!=(1,manager):
            raise ValueError('Battle camera zoom needs the team camera')
        for site,native in sites.items():
            if ram[site:site+8]!=native:raise ValueError(f'Battle camera native site changed: {site:X}')
        patches=code+[(CONTROL,control)]+[(site,jal(entry)) for site,entry in HOOKS]
    return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=[
        dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex())
        for p,d in patches if ram[p:p+len(d)]!=d],
        notes=['Battle camera zoom-out: follow, lock-on and tight cameras of displayed fighters; cinematics keep native framing.'])
