"""Manual search/free-camera state and screen-centred reacquisition.

Native actor flag 5 is the lock-on flag (1C6920/1C69C8 choose the free
camera when clear). Keep the combat resolver's last valid opponent: native
damage and cinematic consumers dereference it even while searching. Only a
living human's explicit lock-off suppresses flag 5. CPUs, scripted pairs,
spectators and unmodified matches retain their ordinary behavior.

Installed last: the exact mode/four-pad queue is replaced with a variant
sharing its cinematic safety gates. No host polling or per-frame projection;
the picker runs once, on an explicit lock-on request from the unlocked state.
"""
from native_map import A, elf_path
import math
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import battle_mode_policy as modes
import lockon_queue as queue
import mod_settings
from regional import DISPLAY_H, Y_ORIGIN
from native_map import ACTOR_HZ

BASE, END = 0x06940000, 0x06948000
INPUT, APPLY, PICK, CAMERA = BASE, BASE+0x1000, BASE+0x2000, BASE+0x3000
QUERY, SET, TAILS = BASE+0x4000, BASE+0x4400, BASE+0x4800
IS_OFF = BASE+0x4C00
COMMAND, EDGE = BASE+0x5000, BASE+0x5400
HIDE_HUD, NATIVE_HUD = BASE+0x6800, BASE+0x6C00
HUD_POLICY = 16
HUD_POLICIES = {'single_enemy': 0, 'hide': 1, 'show': 2}
CONTROL, ROWS = BASE+0x6000, BASE+0x6100
MAGIC = 0x4C4F4631
# Per-physical state. The table reference is deliberately never set to -1.
STRIDE = 32
OFF, HELD, SWITCH_HELD, FIRED, KIND, QUIET = 0, 4, 8, 12, 16, 20
SAVED = tuple(range(16,24))+(31,)
HOOKS = ((A(0x1DAC78),QUERY),(A(0x1DA9D0),SET),(A(0x2013E0),COMMAND),(A(0x1DACE8),EDGE))


def save(a, size=0x80):
    a.addiu(29,29,-size)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)


def restore(a, size=0x80):
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,size);a.jr()


def row(a,index,dest=16,scratch=8):
    a.r(0,scratch,0,index,5);a.li(dest,ROWS);a.r(0x21,dest,dest,scratch)


def emit_clear(a,index):
    # Scratch only t1/t2; index may be t0, and the caller owns all s-registers.
    row(a,index,10,9)
    for off in (OFF,HELD,SWITCH_HELD,FIRED,KIND,QUIET):a.sw(0,10,off)


def emit_off(a,index,yes,tag):
    """Branch when this captured human has deliberately unlocked. t0..t3."""
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,tag)
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,tag)
    a.li(8,core.MODE);a.lw(9,8);a.branch(4,9,0,tag)
    a.lw(9,8,4);a.r(0x2B,10,index,9);a.branch(4,10,0,tag)
    row(a,index,10,9);a.lw(11,10,OFF);a.branch(5,11,0,yes);a.label(tag)


def input_code():
    # a0 actor, a1 unmasked held pad, a2 physical. Queue already validates
    # human ownership/HP and supplies the routed pad for all four seats.
    a=Assembler(INPUT);save(a);a.move(17,5);row(a,6)
    a.lw(8,16,QUIET);a.branch(4,8,0,'quiet_done')
    a.addiu(8,8,-1);a.sw(8,16,QUIET);a.label('quiet_done')
    a.li(18,CONTROL);a.li(19,queue.CONTROL);a.move(20,0)
    a.lw(8,18,8);a.r(0x24,8,8,17);a.branch(4,8,0,'released_off')
    a.lw(9,16,HELD);a.lw(10,18,12);a.r(0x2B,11,9,10)
    a.branch(4,11,0,'threshold');a.addiu(9,9,1);a.sw(9,16,HELD)
    a.label('threshold');a.branch(5,9,10,'switch_input')
    a.lw(8,16,FIRED);a.branch(5,8,0,'switch_input')
    a.addiu(8,0,1);a.sw(8,16,FIRED);a.addiu(20,0,2);a.jump('switch_input')
    a.label('released_off');a.sw(0,16,HELD)
    # Keep FIRED until after switch-release processing; a long shared press
    # must not immediately lock back on when the player lets go.
    a.label('switch_input');a.lw(8,19,queue.FIELDS['button']);a.r(0x24,9,8,17)
    a.branch(4,9,0,'released_switch');a.lw(9,16,SWITCH_HELD)
    a.lw(10,19,queue.TIMING_UPDATES);a.r(0x2B,11,9,10);a.branch(4,11,0,'finish')
    a.addiu(9,9,1);a.sw(9,16,SWITCH_HELD);a.jump('finish')
    a.label('released_switch');a.lw(9,16,SWITCH_HELD);a.sw(0,16,SWITCH_HELD)
    a.lw(10,19,queue.TIMING_UPDATES);a.r(0x2B,11,9,10);a.branch(5,11,0,'finish')
    a.branch(5,20,0,'finish');a.lw(10,18,8);a.branch(5,8,10,'switch')
    a.lw(9,16,FIRED);a.branch(5,9,0,'finish')
    a.label('switch');a.addiu(20,0,1)
    a.label('finish');a.lw(8,18,8);a.r(0x24,8,8,17);a.branch(5,8,0,'keep_latch')
    a.sw(0,16,FIRED);a.label('keep_latch')
    a.branch(4,20,0,'return');a.sw(20,16,KIND)
    a.label('return');a.move(2,20);restore(a);return a.finish()


def apply_code():
    # Returns 0 to let the existing queue cycle its ordinary locked target;
    # 1 consumes an unlock/reacquire request, even when no enemy is visible.
    a=Assembler(APPLY);save(a);a.move(17,4);a.move(18,5);row(a,5)
    a.lw(8,16,KIND);a.addiu(9,0,2);a.branch(4,8,9,'unlock')
    a.lw(8,16,OFF);a.branch(4,8,0,'cycle')
    a.move(4,18);a.call(PICK);a.branch(1,2,0,'consume')
    a.li(8,core.TABLE);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.sw(2,8)
    a.sw(0,16,OFF)
    a.addiu(8,0,2);a.sw(8,16,QUIET)
    a.move(4,17);a.addiu(5,0,5);a.call(A(0x1DA9D0))
    a.li(8,queue.CONTROL);a.lw(9,8,queue.FIELDS['switches']);a.addiu(9,9,1);a.sw(9,8,queue.FIELDS['switches'])
    a.jump('consume')
    a.label('unlock');a.lw(8,16,OFF);a.branch(5,8,0,'consume')
    a.addiu(8,0,1);a.sw(8,16,OFF)
    a.addiu(8,0,2);a.sw(8,16,QUIET)
    a.move(4,17);a.addiu(5,0,5);a.call(A(0x1DAA50))
    # If the player unlocks during the game's own searching animation, leave
    # it through the native action transition (including its cleanup), rather
    # than stranding action 54 with a lock flag it can never set.
    a.lw(8,17,0x948);a.addiu(9,0,54);a.branch(5,8,9,'consume')
    a.move(4,17);a.addiu(5,0,11);a.call(A(0x1E0290))
    a.label('consume');a.addiu(2,0,1);a.jump('return')
    a.label('cycle');a.move(2,0)
    a.label('return');restore(a);return a.finish()


def camera_code():
    """a0 physical -> v0 last rendered camera for that subject, or 0."""
    import quad_viewports as quad
    import fresh_team_camera as follow
    a=Assembler(CAMERA)
    a.li(8,quad.CONTROL);a.lw(9,8);a.li(10,quad.MAGIC);a.branch(5,9,10,'native')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'native')
    a.lw(11,8,quad.VIEW_COUNT);a.i(11,9,11,5);a.branch(4,9,0,'none')
    a.li(8,quad.SUBJECTS);a.move(10,0)
    a.label('quad');a.branch(4,10,11,'none');a.lw(9,8);a.branch(4,9,4,'quad_found')
    a.addiu(10,10,1);a.addiu(8,8,4);a.jump('quad')
    a.label('quad_found');a.r(0,10,0,10,10);a.li(2,quad.CAMERAS);a.r(0x21,2,2,10);a.jr()
    a.label('native');a.li(8,follow.SUCCESSOR_CONTROL);a.lw(9,8,8);a.move(10,0)
    a.branch(4,9,4,'found');a.lw(9,8,12);a.branch(5,9,4,'none');a.addiu(10,0,656)
    a.label('found');a.lw(2,28,-22172);a.branch(4,2,0,'none');a.addiu(2,2,1824);a.r(0x21,2,2,10);a.jr()
    a.label('none');a.move(2,0);a.jr();return a.finish()


def pick_code():
    """Closest visible living enemy to this view's centre, by projected distance.

    Use the native projection and each camera's actual viewport (including
    centred P3, widescreen and fusion duplicates). Behind/offscreen actors
    aren't fallback targets. No visible opponent leaves the player unlocked.
    """
    import team_participation as part
    from guest_healthbars import valid_pointer
    a=Assembler(PICK);save(a,0xC0);a.move(16,4);a.addiu(23,0,-1)
    core.gate(a,'return');a.move(20,10);a.call(CAMERA);a.move(17,2)
    valid_pointer(a,17,'return',656)
    for off,upper in ((512,512),(516,512),(520,DISPLAY_H),(524,DISPLAY_H)):
        a.lw(8,17,off);a.i(11,9,8,upper);a.branch(4,9,0,'return')
    for lo,hi in ((512,516),(520,524)):
        a.lw(8,17,lo);a.lw(9,17,hi);a.r(0x2B,8,8,9);a.branch(4,8,0,'return')
    a.call(A(0x120AB0));a.addiu(4,17,320);a.call(A(0x120B80))
    a.move(18,0);a.li(22,0x7FFFFFFF)
    a.label('loop');a.branch(4,18,20,'pop');a.branch(4,18,16,'next')
    modes.emit_enemy(a,18,16,'next','pick_enemy')
    a.li(8,part.CONTROL);a.lw(9,8,12);a.lw(10,8,16);a.r(0x27,10,10,0);a.r(0x24,9,9,10)
    a.addiu(10,0,1);a.r(4,10,18,10);a.r(0x24,9,9,10);a.branch(4,9,0,'next')
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(19,8)
    valid_pointer(a,19,'next',0x1600)
    a.lw(8,19,0x994);a.i(11,9,8,5);a.branch(4,9,0,'next')
    a.addiu(9,0,164);a.r(24,0,8,9);a.r(18,9,0);a.r(0x21,9,9,19)
    a.lw(8,9,0x9E4);a.branch(6,8,0,'next')
    a.lw(8,19,12);a.i(11,9,8,12);a.branch(4,9,0,'next')
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(21,8)
    valid_pointer(a,21,'next',0x1670)
    for off in (4,8):a.lw(8,21,off);a.branch(4,8,0,'next')
    a.lw(5,21,3436+47*4);a.branch(4,5,0,'root');valid_pointer(a,5,'root',0xE0)
    a.addiu(5,5,64);a.jump('project');a.label('root');a.addiu(5,21,2416)
    a.label('project');a.addiu(4,29,0x80);a.call(A(0x1210D8))
    a.branch(4,2,0,'next');a.lw(8,29,0x8C);a.branch(6,8,0,'next')
    a.lw(8,29,0x88);a.branch(1,8,0,'next');a.move(15,0)
    for coord,lo,hi,origin in ((0x80,512,516,1792),(0x84,520,524,Y_ORIGIN)):
        a.lw(10,29,coord);a.lw(8,17,lo);a.lw(9,17,hi)
        a.r(0x21,11,8,9);a.addiu(11,11,2*origin);a.r(0,11,0,11,3)
        a.addiu(8,8,origin);a.r(0,8,0,8,4);a.r(0x2A,12,10,8);a.branch(5,12,0,'next')
        a.addiu(9,9,origin+1);a.r(0,9,0,9,4);a.r(0x2A,12,10,9);a.branch(4,12,0,'next')
        a.r(0x23,10,10,11);a.r(24,0,10,10);a.r(18,10,0);a.r(0x21,15,15,10)
    a.r(0x2B,8,15,22);a.branch(4,8,0,'next');a.move(22,15);a.move(23,18)
    a.label('next');a.addiu(18,18,1);a.jump('loop')
    a.label('pop');a.call(A(0x120AC8))
    a.label('return');a.move(2,23);restore(a,0xC0);return a.finish()


def flag_code(entry,tail):
    a=Assembler(entry)
    # Native flag queries only clobber v0/v1/a0/a1/a2. The game keeps movement
    # state in t0..t4 across them, so even the fast path must preserve those.
    a.addiu(3,0,5);a.branch(5,5,3,'direct')
    a.addiu(29,29,-0x30)
    for i,r in enumerate(range(8,13)):a.i(63,r,29,i*8)
    # Other flags take only the fast comparison. Never inspect an arbitrary
    # native object as a captured actor or suppress a CPU/spectator's lock.
    core.gate(a,'native');a.lw(11,4);a.r(0x2B,9,11,10);a.branch(4,9,0,'native')
    a.li(8,core.POINTERS);a.r(0,9,0,11,2);a.r(0x21,8,8,9);a.lw(9,8);a.branch(5,9,4,'native')
    a.lw(9,4,0x1278);a.branch(5,9,0,'native')
    # An unlocked player can become the recipient of someone else's authored
    # move. Let the native pair own its flags until that animation ends; the
    # persistent manual OFF bit resumes search afterward.
    a.lw(9,4,0x948)
    for start,span in ((183,5),(236,8),(253,63)):
        a.addiu(8,9,-start);a.i(11,8,8,span);a.branch(5,8,0,'native')
    # Inline uses t3, so keep the physical index in t4.
    a.move(12,11)
    if entry==EDGE:
        # Only the two updates surrounding an explicit gesture lose the
        # acquired-lock edge effect. Natural lock/loss events stay untouched.
        a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'native')
        a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'native')
        row(a,12,10,9);a.lw(11,10,QUIET);a.branch(5,11,0,'off')
    else:
        emit_off(a,12,'off','not_off')
    a.jump('native')
    a.label('off')
    for i,r in enumerate(range(8,13)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x30);a.move(2,0);a.jr()
    a.label('native')
    for i,r in enumerate(range(8,13)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x30)
    a.label('direct');a.jump(tail);return a.finish()


def command_code(tail):
    # The idle/movement dispatcher automatically enters search action 54 when
    # flag 5 is clear. Its update repeatedly emits acquisition lines/sound and
    # tries to set flag 5. Manual free movement must not enter that action.
    # Mask only the search-admission bit, leaving attacks/movement untouched.
    a=Assembler(COMMAND);a.addiu(29,29,-0x30)
    for i,r in enumerate(range(8,13)):a.i(63,r,29,i*8)
    core.gate(a,'native');a.lw(12,4);a.r(0x2B,9,12,10);a.branch(4,9,0,'native')
    a.li(8,core.POINTERS);a.r(0,9,0,12,2);a.r(0x21,8,8,9);a.lw(9,8);a.branch(5,9,4,'native')
    a.lw(9,4,0x1278);a.branch(5,9,0,'native')
    emit_off(a,12,'off','not_off');a.jump('native')
    a.label('off');a.li(8,0xFFDFFFFF);a.r(0x24,5,5,8)
    a.label('native')
    for i,r in enumerate(range(8,13)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x30);a.jump(tail);return a.finish()


def hook_code(entry,tail):
    return command_code(tail) if entry==COMMAND else flag_code(entry,tail)


def is_off_code():
    a=Assembler(IS_OFF);emit_off(a,4,'off','locked');a.move(2,0);a.jr()
    a.label('off');a.addiu(2,0,1);a.jr();return a.finish()


def hide_hud_code():
    """a0 physical subject -> v0 suppress its target panel. No combat writes."""
    import team_participation as part
    from guest_healthbars import valid_pointer
    a=Assembler(HIDE_HUD);save(a);a.move(16,4)
    core.gate(a,'show');a.move(20,10)
    emit_off(a,16,'unlocked','locked');a.jump('show')
    a.label('unlocked');a.li(8,CONTROL);a.lw(9,8,HUD_POLICY)
    a.addiu(10,0,2);a.branch(4,9,10,'show')
    a.addiu(10,0,1);a.branch(4,9,10,'hide')
    a.move(18,0);a.move(23,0)
    a.label('loop');a.branch(4,18,20,'counted')
    modes.emit_enemy(a,18,16,'next','hud_enemy')
    a.li(8,part.CONTROL);a.lw(9,8,12);a.lw(10,8,16)
    a.r(0x27,10,10,0);a.r(0x24,9,9,10)
    a.addiu(10,0,1);a.r(4,10,18,10);a.r(0x24,9,9,10);a.branch(4,9,0,'next')
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(19,8)
    valid_pointer(a,19,'next',0x1600)
    a.lw(8,19,0x994);a.i(11,9,8,5);a.branch(4,9,0,'next')
    a.addiu(9,0,164);a.r(24,0,8,9);a.r(18,9,0);a.r(0x21,9,9,19)
    a.lw(8,9,0x9E4);a.branch(6,8,0,'next')
    a.addiu(23,23,1);a.addiu(8,0,2);a.branch(4,23,8,'hide')
    a.label('next');a.addiu(18,18,1);a.jump('loop')
    a.label('counted');a.addiu(8,0,1);a.branch(4,23,8,'show')
    a.label('hide');a.addiu(2,0,1);a.jump('return')
    a.label('show');a.move(2,0)
    a.label('return');restore(a);data=a.finish();assert len(data)<=NATIVE_HUD-HIDE_HUD
    return data


def native_hud_code():
    """Single-view render-only filter; the roots are reused for each side.

    21F648 publishes the meter side at gp-5728 +24; 21ABB8 publishes the
    portrait side at gp-5730 +0C. Filter only side 1's two root draws, leaving
    the update traversals, player status, timer and clash prompts untouched.
    The display wrapper preserves caller registers and HI/LO around this.
    """
    import hud_subject as hud
    a=Assembler(NATIVE_HUD);save(a)
    a.lw(8,28,-22324);a.branch(4,8,0,'show')
    a.lw(9,8);a.branch(4,4,9,'meters');a.lw(9,8,8);a.branch(5,4,9,'show')
    a.lw(8,28,-22320);a.branch(4,8,0,'show');a.lw(9,8,12);a.jump('side')
    a.label('meters');a.lw(8,28,-22312);a.branch(4,8,0,'show');a.lw(9,8,36)
    a.label('side');a.addiu(8,0,1);a.branch(5,9,8,'show')
    a.li(8,hud.CONTROL);a.lw(4,8,hud.LEFT_SUBJECT);a.call(HIDE_HUD);a.jump('return')
    a.label('show');a.move(2,0)
    a.label('return');restore(a);return a.finish()


def programs():
    parts=[(INPUT,input_code()),(APPLY,apply_code()),(PICK,pick_code()),(CAMERA,camera_code()),(IS_OFF,is_off_code()),
           (HIDE_HUD,hide_hud_code()),(NATIVE_HUD,native_hud_code())]
    native=elf_reader(elf_path(ROOT))[2]
    for i,(hook,entry) in enumerate(HOOKS):
        tail=TAILS+i*32
        parts.extend(((entry,hook_code(entry,tail)),
                      (tail,native(hook,8)+struct.pack('<2I',(2<<26)|((hook+8)>>2),0)),
                      (hook,struct.pack('<2I',(2<<26)|(entry>>2),0))))
    return parts


def validate_memory(ram):
    if struct.unpack_from('<2I',ram,CONTROL)!=(MAGIC,struct.unpack_from('<I',ram,core.ACTORS)[0]):
        raise ValueError('Lock-off belongs to another capture')
    # lockon_select hooks the INPUT/APPLY entries; it validates its own programs, never these.
    import lockon_select
    import lockon_threat
    for p,b in programs():
        b=lockon_select.dependency_override(ram,p,b)
        b=lockon_threat.dependency_override(ram,p,b)
        if ram[p:p+len(b)]!=b:raise ValueError(f'Lock-off executable changed at {p:X}')


def dependency_override(ram,address,expected):
    import viewport_hud as hud
    import display_settings as display
    if address not in (queue.CODE,hud.POST,display.HUD_DRAW_FILTER) or struct.unpack_from('<I',ram,CONTROL)[0]!=MAGIC:return expected
    validate_memory(ram)
    if address==queue.CODE:
        mode=struct.unpack_from('<I',ram,modes.CONTROL+12)[0] if struct.unpack_from('<I',ram,modes.CONTROL)[0]==modes.MAGIC else modes.TEAMS
        import four_player_mode
        previous=queue.legacy_previous(ram)
        options=dict(free_for_all=mode==modes.FFA,coop_controls=mode==modes.COOP,
                     button_aware=queue.CONFIGURABLE,pad_resolver=A(0x1DC2A0) if four_player_mode.installed(ram) else None)
        old=queue.payload(previous,**options)
        if expected[:len(old)]!=old:return expected
        new=queue.payload(previous,lockoff=True,**options)
    else:
        builder=hud.post_code if address==hud.POST else display.hud_draw_filter_code
        for quad in (False,True):
            if expected==builder(quad_support=quad):
                new=builder(quad_support=quad,lockoff=True);break
        else:return expected
    return new+bytes(max(0,len(expected)-len(new)))


@modes.matching_install
def build_memory(ram,settings=None,source='<prepared>'):
    options=mod_settings.validate_settings({} if settings is None else settings)
    # lockon_select needs these programs; with lock-off disabled they install with button mask 0,
    # which can never set OFF (the switch path still reports its tap/hold-release request).
    import lockon_select
    if not (options['lockoff_enabled'] or lockon_select.wanted(options)):return dict(blocks=[])
    if len(ram)!=0x8000000:raise ValueError('Lock-off requires full captured memory')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Lock-off requires the prepared captured match')
    if any(ram[BASE:END]):raise ValueError('Lock-off reservation occupied')
    mode=u(modes.CONTROL+12) if u(modes.CONTROL)==modes.MAGIC else modes.TEAMS
    previous=queue.legacy_previous(ram)
    flags=dict(free_for_all=mode==modes.FFA,coop_controls=mode==modes.COOP)
    found=queue.installed_configuration(ram,previous,**flags)
    if found is None or found[0]!=queue.CONFIGURABLE:raise ValueError('Lock-off needs the configurable target queue')
    flags.update(button_aware=found[0],pad_resolver=found[1])
    old=queue.payload(previous,**flags);new=queue.payload(previous,lockoff=True,**flags)
    # FFA's shorter predicate retains the known suffix of the preceding teams
    # emission. It is owned code, not a free-cave collision.
    base=queue.payload(previous,button_aware=found[0])
    owned=old+base[len(old):]
    if ram[queue.CODE:queue.CODE+len(owned)]!=owned:raise ValueError('Lock-off queue predecessor changed')
    if any(ram[queue.CODE+len(owned):queue.CODE+len(new)]):raise ValueError('Lock-off queue growth is occupied')
    native=elf_reader(elf_path(ROOT))[2]
    control=struct.pack('<5I',MAGIC,manager,
                        mod_settings.LOCKON_MASKS[options['lockoff_button']] if options['lockoff_enabled'] else 0,
                        max(1,math.ceil(options['lockoff_hold_seconds']*ACTOR_HZ)),HUD_POLICIES[options['lockoff_target_hud']])
    parts=[(INPUT,input_code()),(APPLY,apply_code()),(PICK,pick_code()),(CAMERA,camera_code()),(IS_OFF,is_off_code()),
           (HIDE_HUD,hide_hud_code()),(NATIVE_HUD,native_hud_code()),
           (CONTROL,control),(ROWS,bytes(STRIDE*modes.ENGINE_ACTORS))]
    for i,(hook,entry) in enumerate(HOOKS):
        original=native(hook,8)
        if ram[hook:hook+8]!=original:raise ValueError(f'Native lock flag hook changed at {hook:X}')
        # Both native prologues are position-independent straight-line words.
        if any(w>>26 in (1,2,3,4,5,6,7,20,21) for w, in struct.iter_unpack('<I',original)):
            raise ValueError('Unexpected branching native flag prologue')
        tail=TAILS+i*32
        parts.extend(((entry,hook_code(entry,tail)),(tail,original+struct.pack('<2I',(2<<26)|((hook+8)>>2),0))))
    ordered=sorted(parts)
    if any(p+len(b)>n for (p,b),(n,_) in zip(ordered,ordered[1:])):raise ValueError('Lock-off code overlaps')
    parts.extend((h,struct.pack('<2I',(2<<26)|(e>>2),0)) for h,e in HOOKS)
    parts.append((queue.CODE,new+bytes(max(0,len(owned)-len(new)))))
    # Target HUD disappears while unlocked; the player's own panel stays.
    import viewport_hud as hud
    import four_player_mode
    quad=four_player_mode.installed(ram)
    old_hud=hud.post_code(quad_support=quad);new_hud=hud.post_code(quad_support=quad,lockoff=True)
    if ram[hud.POST:hud.POST+len(old_hud)]!=old_hud:raise ValueError('Lock-off HUD predecessor changed')
    if any(ram[hud.POST+len(old_hud):hud.POST+len(new_hud)]):raise ValueError('Lock-off HUD growth occupied')
    parts.append((hud.POST,new_hud+bytes(max(0,len(old_hud)-len(new_hud)))))
    import display_settings as display
    old_draw=display.hud_draw_filter_code(quad_support=quad)
    new_draw=display.hud_draw_filter_code(quad_support=quad,lockoff=True)
    if ram[display.HUD_DRAW_FILTER:display.HUD_DRAW_FILTER+len(old_draw)]!=old_draw:
        raise ValueError('Lock-off native HUD predecessor changed')
    if any(ram[display.HUD_DRAW_FILTER+len(old_draw):display.HUD_DRAW_FILTER+len(new_draw)]):
        raise ValueError('Lock-off native HUD growth occupied')
    parts.append((display.HUD_DRAW_FILTER,new_draw+bytes(max(0,len(old_draw)-len(new_draw)))))
    return dict(blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in parts],
                status='Manual lock-off and camera-centred reacquisition',source=source)
