"""Captured-match display preferences and per-fighter confirmed kill counts.

Installed last, after mode/HUD/camera policy. Base healthbar and mode payloads
stay intact: only their owned call/entry is chained. Kill attribution is copied
from a newly committed kill-feed event, never inferred from a lock-on target.
"""
from native_map import A, CRC, SERIAL
import struct
import localization

import battle_mode_policy as modes
import fresh_team_combat as core
import fresh_team_camera as camera
import guest_healthbars as bars
import guest_killfeed as feed
import hud_subject
import mod_settings as settings_store
from prototype import Assembler, ROOT, elf_reader
from regional import DISPLAY_H, Y_ORIGIN, screen_y

CODE, END = 0x07270000, 0x07280000
SUBJECT, BAR_FILTER, HUD_FILTER = CODE, CODE+0x400, CODE+0x800
FEED_FILTER, SCORE, RECORD = CODE+0xA00, CODE+0x1000, CODE+0x1800
BAR_DRAW, FEED_DRAW, RECORD_NATIVE = CODE+0x2000, CODE+0x4000, CODE+0x5000
HUD_DRAW_FILTER = CODE+0x6000
HUD_DRAW_ENTRY = A(0x2188B8)
HUD_DRAW_ORIGINAL = struct.pack("<2I", 0x27BDFF50, 0xFFB10098)
CONTROL, COUNTS = CODE+0x7000, CODE+0x7100
MAGIC = 0x44535031
FIELDS = dict(magic=0, manager=4, friend=8, enemy=12, hud=16, feed=20, score=24)
KEYS = (settings_store.FRIEND_BARS_KEY, settings_store.ENEMY_BARS_KEY,
        settings_store.NATIVE_HUD_KEY, settings_store.KILL_FEED_KEY, settings_store.KILL_SCORE_KEY)
HUD_ENTRY = hud_subject.RENDER_ROOT
HUD_ORIGINAL = struct.pack('<2I', 0x27BDFFF0, 0xFFBF0000)


def jump(target): return struct.pack('<2I', (2 << 26) | (target >> 2), 0)
def jal(target): return struct.pack('<I', (3 << 26) | (target >> 2))


def relocated(function, old, new, **options):
    # Rebind the generator itself. Wrapping it in a lambda leaves the real
    # generator's Assembler untouched and emits absolute jumps to the old cave.
    class Relocated(Assembler):
        used = False

        def __init__(self, address):
            if address == old: Relocated.used = True
            super().__init__(new if address == old else address)
    code = core.rebound(function, Assembler=Relocated)(**options)
    if not Relocated.used:
        raise ValueError('Relocated generator did not use the relocated assembler')
    return code


def subject_code():
    """a0 active viewport -> v0 actual camera subject, or -1. No HP filter."""
    a=Assembler(SUBJECT)
    a.li(8, core.MODE); a.lw(9,8,4); a.move(10,0)
    a.lw(11,4,512); a.branch(4,11,0,'left'); a.addiu(10,0,1); a.jump('side')
    a.label('left')
    # A single viewport can follow native side 1 after a KO/manual camera swap.
    a.li(11,hud_subject.SCENE); a.lw(11,11,hud_subject.SPLIT_OFF)
    a.addiu(12,0,hud_subject.SPLIT_VALUE); a.branch(4,11,12,'side')
    a.li(11,camera.LEADER_CONTROL); a.lw(10,11,12); a.i(11,12,10,2)
    a.branch(5,12,0,'side'); a.move(10,0)
    a.label('side'); a.li(11,camera.SUCCESSOR_CONTROL); a.r(0,12,0,10,2)
    a.r(0x2D,11,11,12); a.lw(2,11,8); a.r(0x2B,12,2,9)
    a.branch(4,12,0,'invalid')
    # A captured present mask also prevents an absent padded actor becoming HUD subject.
    a.li(11,modes.CONTROL); a.lw(12,11); a.li(13,modes.MAGIC)
    a.branch(5,12,13,'return'); a.lw(12,11,4); a.lw(13,28,-22364)
    a.branch(5,12,13,'return'); a.lw(12,11,20); a.addiu(13,0,1)
    a.r(4,13,2,13); a.r(0x24,12,12,13); a.branch(4,12,0,'invalid')
    a.label('return'); a.jr(); a.label('invalid'); a.addiu(2,0,-1); a.jr()
    return a.finish()


def bar_filter_code(solo=True):
    # a0 physical fighter, a1 camera. Preserve all caller saved s-registers.
    a=Assembler(BAR_FILTER); a.addiu(29,29,-16); a.i(63,31,29,0)
    import rush_cinematics as rush
    rush.emit_hud_gate(a,'cinematic_hidden')
    a.move(15,4)
    if solo:
        # Team mode has no mode-control block. The captured controller seats
        # are authoritative across teams, training, FFA and allied takeovers.
        import spectator_takeover as seats
        import quad_controller as quad
        a.li(8,seats.spec.CONTROL);a.lw(9,8);a.li(10,seats.spec.MAGIC)
        a.branch(5,9,10,'bar_relation');a.lw(9,8,seats.spec.FIELDS['manager']);a.lw(10,28,-22364)
        a.branch(5,9,10,'bar_relation');a.lw(9,8,seats.F['version']);a.addiu(10,0,seats.VERSION)
        a.branch(5,9,10,'bar_relation');a.lw(9,8,seats.F['human_ports']);a.addiu(10,0,1)
        a.branch(5,9,10,'bar_relation')
        # Three/four-player installs retain the two-seat spectator record.
        # Never mistake its P1 bit for a single-human session.
        a.li(11,quad.CONTROL);a.lw(9,11);a.li(10,quad.MAGIC)
        a.branch(5,9,10,'bar_solo');a.lw(9,11,4);a.lw(10,28,-22364)
        a.branch(4,9,10,'bar_relation')
        a.label('bar_solo');a.lw(9,8,seats.F['owned'])
        a.branch(4,15,9,'cinematic_hidden')
        a.label('bar_relation')
    a.move(4,5); a.call(SUBJECT)
    a.branch(1,2,0,'enemy')
    modes.emit_enemy(a,15,2,'friend','display_relation')
    a.label('enemy'); a.li(8,CONTROL); a.lw(2,8,FIELDS['enemy']); a.jump('return')
    a.label('friend'); a.li(8,CONTROL); a.lw(2,8,FIELDS['friend'])
    a.jump('return')
    a.label('cinematic_hidden');a.move(2,0)
    a.label('return'); a.i(55,31,29,0); a.addiu(29,29,16); a.jr()
    return a.finish()


def hud_filter_code(legacy=False,deferred=True):
    if not legacy:
        # This root also advances the FIGHT banner and clash prompt nodes.
        # Always update it, even while every visual is hidden.
        a=Assembler(HUD_FILTER)
        if deferred:
            import viewport_hud as view
            a.addiu(29,29,-16);a.i(63,8,29,0);a.i(63,9,29,8)
            a.li(8,view.CONTROL);a.lw(9,8);a.li(8,view.MAGIC);a.branch(5,8,9,'no_panels')
            a.li(8,view.CONTROL);a.sw(0,8,24)
            a.label('no_panels');a.i(55,8,29,0);a.i(55,9,29,8);a.addiu(29,29,16)
        for word in struct.unpack("<2I",HUD_ORIGINAL):a.emit(word)
        a.jump(HUD_ENTRY+8);return a.finish()
    a=Assembler(HUD_FILTER); core.gate(a,'native')
    a.li(8,CONTROL); a.lw(9,8,FIELDS['manager']); a.lw(10,28,-22364)
    a.branch(5,9,10,'native'); a.lw(9,8,FIELDS['hud']); a.branch(4,9,0,'hidden')
    # A prepared split HUD has two panels per viewport. Suppress the original
    # two global panels only while that exact captured renderer owns the view.
    import viewport_hud
    a.li(8,viewport_hud.CONTROL);a.lw(9,8);a.li(10,viewport_hud.MAGIC);a.branch(5,9,10,'native')
    a.addiu(29,29,-0x20);a.i(63,31,29,0);a.i(63,2,29,8)
    a.call(viewport_hud.ACTIVE);a.move(8,2);a.i(55,2,29,8);a.i(55,31,29,0);a.addiu(29,29,0x20)
    a.branch(4,8,0,'native')
    a.label('hidden');a.jr()
    a.label('native')
    for word in struct.unpack('<2I',HUD_ORIGINAL): a.emit(word)
    a.jump(HUD_ENTRY+8)
    return a.finish()


def hud_draw_filter_code(deferred=True,quad_support=False,lockoff=False,prompt_state=True):
    """Filter render-only traversal; leave native callbacks/timers running."""
    import viewport_hud as view
    a=Assembler(HUD_DRAW_FILTER);view.save(a);core.gate(a,'native')
    a.li(8,CONTROL);a.lw(9,8,FIELDS['manager']);a.lw(10,28,-22364)
    a.branch(5,9,10,'native')
    # Generic node renderer is also called by menus. Our HUD wrapper scopes it.
    a.li(10,hud_subject.CONTROL);a.lw(11,10,hud_subject.FIELDS['active']);a.branch(4,11,0,'native')
    a.lw(9,8,FIELDS['hud']);a.branch(4,9,0,'hidden')
    import rush_cinematics as rush
    rush.emit_hud_gate(a,'rush_status_nodes')
    a.li(8,view.CONTROL);a.lw(9,8);a.li(10,view.MAGIC);a.branch(5,9,10,'native')
    if quad_support:
        # Intros use the native camera, so ACTIVE intentionally returns false.
        # Still suppress the two stock status panels; keep dialogue, FIGHT,
        # clash prompts and all native node updates running as usual.
        a.li(8,A(0x2FEB38));a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'native')
        a.li(9,0x7FFFF00);a.r(0x2B,9,8,9);a.branch(4,9,0,'native')
        a.lw(8,8);a.i(11,9,8,3);a.branch(5,9,0,'status_nodes')
    a.call(view.ACTIVE);a.branch(4,2,0,'single_hud' if lockoff else 'native')
    if quad_support:a.label('status_nodes')
    # 219710 updates roots +0 (health/ki/stock) and +8 (portrait/name).
    # Keep +4/+12/+16/+20/+24, including clash mash and intro prompts.
    a.lw(8,28,-22324);a.branch(4,8,0,'native')
    a.lw(9,8,0);a.branch(4,4,9,'panels' if deferred else 'hidden');a.lw(9,8,8);a.branch(4,4,9,'hidden')
    a.label('native')
    if prompt_state:
        # Native 219710 establishes its GS baseline once, before custom split
        # panels and world overlays can replace it. The interactive prompt is
        # the +20 tree; its draw callbacks set textures/vertices but inherit
        # scissors and sampling in both GS contexts. Restore the exact native
        # baseline for that tree, including paths where split panels did not
        # run this frame. Descendants and ordinary menu nodes remain unchanged.
        a.li(8,hud_subject.CONTROL);a.lw(9,8,hud_subject.FIELDS['active'])
        a.branch(4,9,0,'native_ready')
        a.lw(8,28,-22324);a.branch(4,8,0,'native_ready')
        a.lw(9,8,20);a.branch(5,4,9,'native_ready')
        core.gate(a,'native_ready')
        a.li(8,CONTROL);a.lw(9,8,FIELDS['manager']);a.lw(10,28,-22364)
        a.branch(5,9,10,'native_ready');a.call(A(0x225790))
        a.label('native_ready')
    view.restore(a)
    for word in struct.unpack('<2I',HUD_DRAW_ORIGINAL):a.emit(word)
    a.jump(HUD_DRAW_ENTRY+8)
    if deferred:
        a.label('panels');a.li(8,view.CONTROL);a.lw(9,8,28);a.li(10,view.POST_MAGIC)
        a.branch(5,9,10,'hidden');a.call(view.POST)
        a.jump('hidden')
    # A shared rush is one authored scene. Hide character status roots without
    # substituting split panels, but retain native cinematic/clash prompts.
    a.label('rush_status_nodes');a.lw(8,28,-22324);a.branch(4,8,0,'native')
    for off in (0,8):
        a.lw(9,8,off);a.branch(4,4,9,'hidden')
    a.jump('native')
    a.label('hidden');view.restore(a);a.jr()
    if lockoff:
        import lockoff_target
        a.label('single_hud');a.call(lockoff_target.NATIVE_HUD)
        a.branch(5,2,0,'hidden');a.jump('native')
    data=a.finish();assert len(data)<CONTROL-HUD_DRAW_FILTER;return data


def feed_filter_code():
    a=Assembler(FEED_FILTER); a.addiu(29,29,-16); a.i(63,31,29,0)
    a.li(8,CONTROL); a.lw(9,8,FIELDS['feed']); a.branch(4,9,0,'score')
    a.call(FEED_DRAW)
    a.label('score'); a.call(SCORE)
    a.i(55,31,29,0); a.addiu(29,29,16); a.jr()
    return a.finish()


def record_code():
    # Preserve the complete ABI because native audited callers have live temps.
    a=Assembler(RECORD); feed.prologue(a)
    a.li(8,feed.CONTROL); a.lw(9,8,16); a.sw(9,29,0xF0)
    feed.restore(a); a.call(RECORD_NATIVE); feed.save(a)
    a.li(8,feed.CONTROL); a.lw(9,8,16); a.lw(10,29,0xF0)
    a.branch(4,9,10,'done')
    a.li(8,feed.EVENTS); a.lw(9,8,16); a.li(10,core.MODE); a.lw(10,10,4)
    a.r(0x2B,10,9,10); a.branch(4,10,0,'done')
    a.r(0,9,0,9,2); a.li(8,COUNTS); a.r(0x2D,8,8,9); a.lw(9,8)
    a.i(11,10,9,999); a.branch(4,10,0,'done'); a.addiu(9,9,1); a.sw(9,8)
    a.label('done'); feed.epilogue(a)
    return a.finish()


def score_code(quad=False):
    a=Assembler(SCORE); a.addiu(29,29,-0xB0)
    for i,r in enumerate(tuple(range(16,24))+(31,)): a.i(63,r,29,i*8)
    a.call(feed.GATE); a.branch(4,2,0,'done')
    if quad:
        a.li(8,A(0x2FEB38));a.lw(8,8);a.branch(4,8,0,'done');a.lw(8,8)
        a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.li(8,CONTROL); a.lw(9,8,FIELDS['score']); a.branch(4,9,0,'done')
    a.lw(16,28,-22176); a.branch(4,16,0,'done')
    for off,upper in ((512,512),(516,512),(520,DISPLAY_H),(524,DISPLAY_H)):
        a.lw(8,16,off); a.i(11,9,8,upper); a.branch(4,9,0,'done')
    a.lw(8,16,512); a.lw(9,16,516); a.r(0x2B,8,8,9); a.branch(4,8,0,'done')
    a.move(4,16); a.call(SUBJECT); a.branch(1,2,0,'done')
    a.r(0,8,0,2,2); a.li(9,COUNTS); a.r(0x2D,8,8,9); a.lw(17,8)
    a.i(11,8,17,1000); a.branch(5,8,0,'bounded'); a.addiu(17,0,999)
    a.label('bounded')
    # Fixed width avoids division / HI-LO state; counters are saturated to 999.
    a.li(8,int.from_bytes(localization.guest('KILLS')[:4],'little')); a.sw(8,29,0x70)
    a.li(8,int.from_bytes(localization.guest('KILLS')[4:]+b' 00','little')); a.sw(8,29,0x74)
    a.addiu(8,0,ord('0')); a.sw(8,29,0x78)
    for divisor,offset,tag in ((100,0x76,'hundreds'),(10,0x77,'tens')):
        a.addiu(8,0,ord('0')); a.label(tag)
        a.i(11,9,17,divisor); a.branch(5,9,0,tag+'_done')
        a.addiu(17,17,-divisor); a.addiu(8,8,1); a.jump(tag)
        a.label(tag+'_done'); a.i(40,8,29,offset)
    a.addiu(17,17,ord('0')); a.i(40,17,29,0x78)
    a.addiu(4,29,0x70); a.lw(5,16,512); a.addiu(5,5,1792+8); a.r(0,5,0,5,4)
    import multiview_layout
    a.lw(6,16,520); a.addiu(6,6,Y_ORIGIN+screen_y(multiview_layout.SCORE_Y if quad else 88)); a.r(0,6,0,6,4)
    a.li(7,0x80EEEEEE); a.call(feed.SMALL_TEXT if quad else feed.TEXT)
    a.label('done')
    for i,r in enumerate(tuple(range(16,24))+(31,)): a.i(55,r,29,i*8)
    a.addiu(29,29,0xB0); a.jr()
    return a.finish()


def owned_pieces(ffa=False,legacy=False,deferred=True,solo=True):
    return [(SUBJECT,subject_code()),(BAR_FILTER,bar_filter_code(solo)),(HUD_FILTER,hud_filter_code(legacy,deferred)),
            (FEED_FILTER,feed_filter_code()),(SCORE,score_code()),(RECORD,record_code()),
            (BAR_DRAW,bars.draw_code(ffa,visibility_filter=BAR_FILTER,entry=BAR_DRAW)),
            (FEED_DRAW,relocated(feed.draw_code,feed.DRAW,FEED_DRAW)),
            (RECORD_NATIVE,relocated(feed.record_code,feed.RECORD,RECORD_NATIVE))]+([] if legacy else [(HUD_DRAW_FILTER,hud_draw_filter_code(deferred))])


@modes.matching_install
def build_memory(ram,settings=None,source='<prepared>'):
    if len(ram)!=0x8000000: raise ValueError('Display settings require 128 MiB captured EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    options=settings_store.validate_settings({} if settings is None else settings)
    # Exact saved predecessors can be upgraded without accepting foreign code
    # or resetting kill counters/display preferences. Dependency validators
    # authenticate the rest against a temporary image containing the new
    # filter, then the returned blocks still compare against the original RAM.
    if u(CONTROL)==MAGIC and ram[HUD_DRAW_ENTRY:HUD_DRAW_ENTRY+8]==jump(HUD_DRAW_FILTER):
        for deferred in (True,False):
            for quad_support in (False,True):
                for lockoff in (False,True):
                    old=hud_draw_filter_code(deferred,quad_support,lockoff,prompt_state=False)
                    if ram[HUD_DRAW_FILTER:HUD_DRAW_FILTER+len(old)]!=old:continue
                    new=hud_draw_filter_code(deferred,quad_support,lockoff)
                    if new==old:continue
                    if any(ram[HUD_DRAW_FILTER+len(old):HUD_DRAW_FILTER+len(new)]):
                        raise ValueError('Native prompt filter extension occupied')
                    size=max(len(old),len(new));data=new+bytes(size-len(new))
                    image=bytearray(ram);image[HUD_DRAW_FILTER:HUD_DRAW_FILTER+size]=data
                    report=build_memory(image,settings,source)
                    blocks={b['address']:b for b in report['blocks']}
                    blocks[HUD_DRAW_FILTER]=dict(address=HUD_DRAW_FILTER,data_hex=data.hex())
                    report['blocks']=[dict(b,expected_hex=ram[p:p+len(bytes.fromhex(b['data_hex']))].hex())
                                      for p,b in sorted(blocks.items())]
                    return report
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Display settings require the published captured match')
    ffa=u(modes.CONTROL)==modes.MAGIC and u(modes.CONTROL+12)==modes.FFA
    pieces=owned_pieces(ffa)
    wrapper=bars.wrapper(); needle=jal(bars.DRAW)
    offsets=[i for i in range(0,len(wrapper),4) if wrapper[i:i+4]==needle]
    if len(offsets)!=1: raise ValueError('Unknown overhead-bar wrapper')
    patches=[(bars.CODE+offsets[0],jal(BAR_DRAW)),(feed.DRAW,jump(FEED_FILTER)),
             (feed.RECORD,jump(RECORD)),(HUD_ENTRY,jump(HUD_FILTER)),
             (HUD_DRAW_ENTRY,jump(HUD_DRAW_FILTER))]
    control=bytearray(0x40)
    struct.pack_into('<7I',control,0,MAGIC,manager,*(int(options[k]) for k in KEYS))
    installed=u(CONTROL)==MAGIC
    if installed:
        import four_player_mode
        pieces=[(p,four_player_mode.dependency_override(ram,p,d)) for p,d in pieces]
        import lockoff_target
        pieces=[(p,lockoff_target.dependency_override(ram,p,d)) for p,d in pieces]
        # The target marker owns the overhead-bar call once installed (it draws the arrow, then the bars over it).
        import lockon_select
        patches=[(p,lockon_select.dependency_override(ram,p,d)) for p,d in patches]
        # The attacker marks then own it (marks, then the arrow, then the bars).
        import lockon_threat
        patches=[(p,lockon_threat.dependency_override(ram,p,d)) for p,d in patches]
        previous=owned_pieces(ffa,legacy=True)+patches[:-1]+[(HUD_DRAW_ENTRY,HUD_DRAW_ORIGINAL)]
        prior_solo=[(p,four_player_mode.dependency_override(ram,p,d)) for p,d in owned_pieces(ffa,solo=False)]+patches
        upgrading=all(ram[p:p+len(d)]==d for p,d in previous)
        if all(ram[p:p+len(d)]==d for p,d in prior_solo):
            old_size=len(bar_filter_code(False));new_size=len(bar_filter_code())
            if any(ram[BAR_FILTER+old_size:BAR_FILTER+new_size]):
                raise ValueError('Overhead bar filter extension occupied')
            upgrading=True
        elif upgrading:
            if any(ram[HUD_DRAW_FILTER:HUD_DRAW_FILTER+len(hud_draw_filter_code())]):
                raise ValueError('Display node filter reservation occupied')
        elif all(ram[p:p+len(d)]==d for p,d in owned_pieces(ffa,deferred=False)+patches):
            upgrading=True
            sizes={p:len(d)for p,d in owned_pieces(ffa,deferred=False)}
            for p,d in pieces:
                if any(ram[p+sizes.get(p,0):p+len(d)]):raise ValueError('Display filter extension occupied')
        else:
            for p,d in pieces+patches:
                if ram[p:p+len(d)]!=d: raise ValueError(f'Display program changed:{p:08X}')
        if u(CONTROL+4)!=manager: raise ValueError('Display settings belong to a different match')
        blocks=[] if ram[CONTROL:CONTROL+len(control)]==control else [(CONTROL,bytes(control))]
        if upgrading:blocks=pieces+patches+blocks
    else:
        if any(ram[CODE:END]): raise ValueError('Display reservation occupied')
        expected=[(bars.CODE,wrapper),(bars.DRAW,bars.draw_code(ffa)),
                  (feed.DRAW,feed.draw_code()),(feed.RECORD,feed.record_code()),(HUD_ENTRY,HUD_ORIGINAL),
                  (HUD_DRAW_ENTRY,HUD_DRAW_ORIGINAL)]
        for p,d in expected:
            if ram[p:p+len(d)]!=d: raise ValueError(f'Unknown display dependency:{p:08X}')
        blocks=pieces+[(CONTROL,bytes(control)),(COUNTS,bytes(modes.ENGINE_ACTORS*4))]+patches
    spans=sorted((p,p+len(d)) for p,d in blocks)
    if any(end>p for (_,end),(p,_) in zip(spans,spans[1:])): raise ValueError('Display payloads overlap')
    return dict(serial=SERIAL,crc=CRC,source=str(source),
        status='PER-VIEW DISPLAY OPTIONS AND CONFIRMED KILL COUNTS',
        settings={k:options[k] for k in KEYS},counts=COUNTS,
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in blocks],
        limitations=['Unknown/environmental deaths have no credited killer and do not increase any score.',
                     'Scores follow the camera subject, including corpses; counts remain with physical fighters.',
                     'Native battle HUD can be hidden independently; menu screens remain available.'])
