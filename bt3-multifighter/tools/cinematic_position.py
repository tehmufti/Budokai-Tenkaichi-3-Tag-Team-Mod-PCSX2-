"""Optional local staging for native rushes, specials and transformations.

Only the five authored recenter/staging setter calls are intercepted. Ordinary
movement, spawn/reset, saved-pose restoration, stage destruction and story
cinematics stay native. Paired placements share a rigid world translation so
their relative animation poses still agree (every staging kind, giant
transformations included). Each staged placement that would put a participant
under the floor at its own X/Z is lifted onto it (LIFT; the game re-applies a
staged pose every update, so moving a fighter between placements would only
make it jitter: seen live). When ownership ends, recovery keeps
the fighter where it is: it is only clamped into the live arena box and lifted
onto the floor found just above or below it (an arch overhead is not a floor).
The solid-body test is telemetry only. A pose that cannot be read falls back to
the pre-move pose and then the native side spawn; after three attempts, thirty
updates apart, the row retires without moving anyone.

v2 (beta.37 movement stream) of the Oct 3 peer module in the local project, moved to
0x06F80000 (p41/reservations.md); the story gate applies when story_cinematics
is installed (the local project developer tree).
"""
from native_map import A, CRC, SERIAL, elf_path
import struct
from prototype import Assembler,ROOT,elf_reader
import fresh_team_combat as core
import fusion_partner_lifecycle as abi
import spawn_placement as terrain
import arena_bounds
import mod_settings
import team_intro
import result_presentation
import camera_continuity
from battle_mode_policy import ACTOR_COUNTS

KEY='prevent_cinematic_recentering'
BASE,END=0x06F80000,0x06F8C000
PLACE,TICK,SAFE=BASE+0xA00,BASE+0x1800,BASE+0x2000
QUERY,FOOTPRINT,BODY=BASE+0x4000,BASE+0x5000,BASE+0x6000
COMMIT,LIFT=BASE+0x5800,BASE+0x6800
ROWS,CONTROL,WORK=BASE+0x7000,BASE+0x7800,BASE+0x7900
STRIDE,MAGIC=0x80,0x4E435231
# Row: actor, active, staging kind, shared root physical ID; world delta XYZ;
# original root XYZ/W, angles XYZ/W; ordinary-update count, original stage;
# +80 recovered, +84 retry countdown, +88 reject bits, +92 recovery attempts.
# CONTROL: magic, manager, count, enabled; placements (QUERY counts its floor
# queries in the same word), rescued, camera row, fallback placements,
# rejections; +60/+64 native geometry scratch; +0x80 placements lifted onto the
# floor, +0x84 abandoned rows, +0x88 OR of reject bits, +0x8C largest recovery
# displacement (float).
REJECT=dict(nonfinite=1,box=2,floor=4,body=8,footprint=16)
TELEMETRY=dict(placements_and_queries=16,rescued=20,fallbacks=28,rejections=32,floor_lifts=0x80,abandoned=0x84,reject_bits=0x88,
               largest_move=0x8C)
ATTEMPTS,RETRY=3,30
LIFT_MIN=40.0       # floor query starts H = max(40, 4R) above the root (Y down)
SINK=0.5            # a root more than this below the floor is lifted
MOVED=0.01          # smaller pose changes are not committed
# Optional authored height kept per staging kind (world units, Y up); the live survey keeps every kind at 0.
CLEARANCE={1:0.0,2:0.0,3:0.0,4:0.0}
RECENTER_CALLS=((A(0x1D760C),1),(A(0x1D7668),1),(A(0x1D76FC),2),(A(0x1D78DC),3),(A(0x1D7978),4))
HOOKS=tuple((site,BASE+i*0x200,kind) for i,(site,kind) in enumerate(RECENTER_CALLS))
SYNC_SITE,SYNC_NATIVE=A(0x1C1F74),A(0x1D70E8)
SETTER=A(0x1D7418)
NATIVE=elf_reader(elf_path(ROOT))[2]


def jal(p):return struct.pack('<I',(3<<26)|(p>>2))


def story_cinematics():
    """The scenario module of the the local project developer tree, or None (beta.36/37 player builds have no story mode)."""
    try:
        import story_cinematics as module
    except ImportError:
        return None
    return module


def gate(a,fail):
    core.gate(a,fail);a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail);a.lw(9,8,12);a.branch(4,9,0,fail)
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,fail)
    a.li(8,team_intro.BATTLE);a.lw(8,8);abi.pointer(a,8,4,fail,temp=11,test=9)
    a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,fail)
    a.li(8,result_presentation.RESULT);a.lw(8,8);a.branch(5,8,0,fail)
    a.li(8,camera_continuity.SCENE_FLAGS);a.lw(8,8);a.i(12,8,8,0x2000);a.branch(5,8,0,fail)
    # A scenario controls its own absolute cinematic coordinates.
    story=story_cinematics()
    if story is not None:story.emit_active(a,fail,f'position_story_{len(a.words)}')


def identity(a,actor,row,index,fail):
    abi.pointer(a,actor,0x1600,fail,temp=8,test=9)
    a.lw(index,actor);a.r(0x2B,9,index,10);a.branch(4,9,0,fail)
    a.r(0,9,0,index,2);a.li(8,core.POINTERS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,actor,fail)
    a.r(0,row,0,index,7);a.li(8,ROWS);a.r(0x21,row,row,8)


def action(a,actor,yes,no,tag):
    a.lw(8,actor,0x948);a.addiu(9,8,-236);a.i(11,9,9,8);a.branch(5,9,0,yes)
    a.addiu(9,8,-253);a.i(11,9,9,63);a.branch(5,9,0,yes);a.jump(no)


def seed(a,actor,row,index,tag):
    a.lw(8,row);a.branch(5,8,actor,tag+'_new');a.lw(8,row,4);a.addiu(9,0,1);a.branch(5,8,9,tag+'_new')
    a.li(8,arena_bounds.STAGE);a.lw(8,8);a.lw(9,row,68);a.branch(4,8,9,tag+'_done')
    a.label(tag+'_new');a.sw(actor,row);a.addiu(8,0,1);a.sw(8,row,4);a.sw(0,row,8);a.sw(index,row,12)
    for off in range(0,16,4):
        a.lw(8,actor,16+off);a.sw(8,row,32+off);a.lw(8,actor,32+off);a.sw(8,row,48+off)
    for off in (64,80,84,88,92):a.sw(0,row,off)
    a.li(8,arena_bounds.STAGE);a.lw(8,8);a.sw(8,row,68)
    a.label(tag+'_done')


def finite(a,reg,offset,fail):
    a.lw(8,reg,offset);a.li(9,0x7FFFFFFF);a.r(0x24,8,8,9)
    a.li(9,0x49742400);a.r(0x2B,9,8,9);a.branch(4,9,0,fail)


def place_code():
    fp=terrain.fp
    a=Assembler(PLACE);gate(a,'native');a.move(16,4);a.move(17,5);a.move(18,6)
    identity(a,16,19,20,'native');action(a,16,'eligible','native','place')
    a.label('eligible')
    for off in (0,4,8):finite(a,17,off,'native');finite(a,16,16+off,'native')
    seed(a,16,19,20,'self');a.move(21,19);a.move(22,20);a.move(15,0)
    # Share the delta only for an authenticated current native special pair.
    # The victim's actor and row live in t6/t7 (never k0/k1: kernel scratch, LS-2).
    # The two pair fields are physical indices, never parity/team aliases.
    a.lw(8,16,0x948);a.addiu(9,8,-301);a.i(11,9,9,3);a.branch(5,9,0,'pair')
    a.addiu(9,8,-313);a.i(11,9,9,3);a.branch(4,9,0,'solo')
    a.label('pair');a.lw(22,16,3732);a.lw(23,16,3736)
    for r in (22,23):a.r(0x2B,9,r,10);a.branch(4,9,0,'solo')
    a.branch(4,22,23,'solo');a.branch(4,20,22,'performer');a.branch(5,20,23,'solo')
    a.label('performer');a.r(0,9,0,22,2);a.li(8,core.POINTERS);a.r(0x21,8,8,9);a.lw(25,8)
    abi.pointer(a,25,0x1600,'solo');a.lw(8,25);a.branch(5,8,22,'solo')
    a.lw(8,25,0x948);a.addiu(8,8,-301);a.i(11,9,8,3);a.branch(4,9,0,'solo')
    a.lw(8,25,3732);a.branch(5,8,22,'solo');a.lw(8,25,3736);a.branch(5,8,23,'solo')
    a.r(0,9,0,23,2);a.li(8,core.POINTERS);a.r(0x21,8,8,9);a.lw(14,8)
    abi.pointer(a,14,0x1600,'solo');a.lw(8,14);a.branch(5,8,23,'solo')
    a.lw(8,14,0x948);a.addiu(8,8,-313);a.i(11,9,8,3);a.branch(4,9,0,'solo')
    a.lw(8,14,3732);a.branch(5,8,22,'solo');a.lw(8,14,3736);a.branch(5,8,23,'solo')
    a.r(0,21,0,22,7);a.li(8,ROWS);a.r(0x21,21,21,8);seed(a,25,21,22,'pair_root')
    a.r(0,15,0,23,7);a.li(8,ROWS);a.r(0x21,15,15,8);seed(a,14,15,23,'pair_victim')
    a.jump('offset')
    a.label('solo');a.move(21,19);a.move(22,20);a.move(15,0)
    a.label('offset');a.lw(8,21,8);a.branch(4,8,24,'translate')
    # The first placement of a new staging kind supplies a shared anchor.
    # Reuse the pre-move root, rather than a previous centered/staging pose.
    # Every kind is a rigid move (a kind-specific native height would be a jump).
    for off in (0,4,8):
        a.i(49,0,19,32+off);a.i(49,1,17,off);fp(a,1,0,0,1);a.i(57,0,21,16+off)
    # A pair is anchored at its performer even when the victim's setter runs
    # first (a lower physical index updates first). The performer's own
    # staging offset (actor+0xE70) is only set in its own update, so its
    # staged root is taken to be this one: live, rush and ultimate pairs are
    # staged at one point (both offsets equal once set; p41 movement-review).
    a.branch(4,15,0,'anchored');a.branch(4,16,25,'anchored')
    for off in (0,4,8):finite(a,21,32+off,'anchored')
    for off in (0,4,8):
        a.i(49,0,21,32+off);a.i(49,1,17,off);fp(a,1,0,0,1);a.i(57,0,21,16+off)
    a.label('anchored')
    for kind,clearance in sorted(CLEARANCE.items()):
        if clearance:
            a.addiu(8,0,kind);a.branch(5,24,8,f'clearance_{kind}')
            a.i(49,0,21,20);terrain.constant(a,1,clearance);fp(a,1,0,0,1);a.i(57,0,21,20)
            a.label(f'clearance_{kind}')
    a.sw(24,21,8);a.sw(22,21,12)
    a.label('translate');a.sw(24,19,8);a.sw(22,19,12);a.sw(0,19,64)
    # Publish both authenticated participants before native camera selection,
    # even if it names the victim before its own staging setter has run.
    a.branch(4,15,0,'pair_published');a.sw(24,15,8);a.sw(22,15,12)
    for off in (0,4,8):a.lw(8,21,16+off);a.sw(8,15,16+off)
    a.label('pair_published')
    for off in (0,4,8):
        a.lw(8,21,16+off);a.sw(8,19,16+off)
        a.i(49,0,17,off);a.i(49,1,21,16+off);fp(a,0,0,0,1);a.i(57,0,29,0x2A0+off)
    a.li(8,0x3F800000);a.sw(8,29,0x2AC)
    # A staged pose under the floor at its own X/Z goes onto that floor.
    a.move(4,16);a.addiu(5,29,0x2A0);a.call(LIFT)
    # Look up the new sector; the centered sector is no longer valid here.
    for i,off in enumerate(terrain.QUERY_GLOBALS):a.lw(8,28,off);a.sw(8,29,0x300+4*i)
    a.addiu(4,0,-1);a.addiu(5,29,0x2A0);a.call(A(0x23FF78));a.move(23,2)
    for i,off in enumerate(terrain.QUERY_GLOBALS):a.lw(8,29,0x300+4*i);a.sw(8,28,off)
    a.move(4,16);a.addiu(5,29,0x2A0);a.move(6,18);a.move(7,23);a.call(SETTER)
    a.i(31,2,29,abi.OFFSETS[2]);a.i(31,3,29,abi.OFFSETS[3])
    a.li(8,CONTROL);a.lw(9,8,16);a.addiu(9,9,1);a.sw(9,8,16);a.sw(21,8,24)
    abi.restore(a);a.jr()
    a.label('native');abi.restore(a);a.jump(SETTER)
    data=a.finish();assert len(data)<TICK-PLACE;return data


def retire(a,row,tag):
    a.sw(0,row,4);a.li(8,CONTROL);a.lw(9,8,24);a.branch(5,9,row,tag+'_done');a.sw(0,8,24)
    a.label(tag+'_done')


def tick_code():
    a=Assembler(TICK);abi.save(a);a.move(16,4);a.call(SYNC_NATIVE)
    a.i(31,2,29,abi.OFFSETS[2]);a.i(31,3,29,abi.OFFSETS[3]);gate(a,'done')
    identity(a,16,19,20,'done');a.lw(8,19);a.branch(5,8,16,'done');a.lw(8,19,4);a.branch(4,8,0,'done')
    a.li(8,arena_bounds.STAGE);a.lw(8,8);a.lw(9,19,68);a.branch(5,8,9,'clear')
    action(a,16,'held','ordinary','tick')
    a.label('held');a.sw(0,19,64);a.jump('done')
    a.label('ordinary')
    # Model-bound authored cameras can outlive their performer's action. Wait
    # until that camera finishes, without holding an unrelated fighter's view.
    a.lw(12,28,-22180);abi.pointer(a,12,832,'idle')
    a.lw(8,12,812);a.branch(5,8,0,'camera_models')
    a.lw(8,12,776);a.i(12,8,8,3);a.addiu(9,0,1);a.branch(5,8,9,'idle')
    a.label('camera_models');a.lw(8,16,12);a.i(11,9,8,12);a.branch(4,9,0,'idle')
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,9,9,8);a.lw(9,9)
    a.lw(8,12,768);a.branch(4,8,9,'held');a.lw(8,12,772);a.branch(4,8,9,'held')
    import cinematic_position_camera as camera
    a.li(8,camera.CONTROL);a.lw(8,8);a.li(9,camera.MAGIC);a.branch(5,8,9,'idle')
    a.move(4,19);a.call(camera.OWNED);a.branch(5,2,0,'held')
    a.label('idle');a.lw(8,19,64);a.addiu(8,8,1);a.sw(8,19,64);a.i(11,9,8,2);a.branch(5,9,0,'done')
    a.lw(8,19,84);a.branch(4,8,0,'recover');a.addiu(8,8,-1);a.sw(8,19,84);a.jump('done')
    # At most ATTEMPTS recoveries per row; then it retires without moving anyone.
    a.label('recover');a.lw(8,19,92);a.addiu(9,0,ATTEMPTS);a.r(0x2A,8,8,9);a.branch(5,8,0,'attempt')
    a.li(8,CONTROL);a.lw(9,8,TELEMETRY['abandoned']);a.addiu(9,9,1);a.sw(9,8,TELEMETRY['abandoned']);a.jump('clear')
    a.label('attempt');a.move(4,16);a.move(5,19);a.call(SAFE)
    a.lw(8,19,80);a.branch(5,8,0,'clear')
    # An unreadable pose never becomes an unchecked teleport. Keep a bounded
    # retry armed while ordinary gameplay continues freely.
    a.addiu(8,0,2);a.sw(8,19,4);a.addiu(8,0,RETRY);a.sw(8,19,84);a.jump('done')
    a.label('clear');retire(a,19,'retire')
    a.label('done');abi.restore(a);a.jr()
    data=a.finish();assert len(data)<SAFE-TICK;return data


def reject(a,row,bit,temp=8):
    """row+88 |= bit (t0/t1)."""
    a.lw(temp,row,88);a.i(13,temp,temp,bit);a.sw(temp,row,88)


def model_of(a,actor,out,fail):
    """out = the actor's registered model (MODELS[actor+12], whose +16 names the same ID), else fail."""
    a.lw(8,actor,12);a.i(11,9,8,12);a.branch(4,9,0,fail)
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,9,9,8);a.lw(out,9)
    abi.pointer(a,out,0x1670,fail);a.lw(8,out,16);a.lw(9,actor,12);a.branch(5,8,9,fail)


def floor_lift(a,work,tag):
    """Lift work+0x10's Y onto the floor at its X/Z: query from Y - max(40, 4R) (work+0x20 = R + 1), then from the
    arena ceiling (s5 = live bounds). v0 = 1 when a floor was found. Clobbers t-registers, f0..f2, f12, f20."""
    fp,constant=terrain.fp,terrain.constant
    a.i(49,0,work,0x20);constant(a,1,1);fp(a,1,0,0,1);constant(a,1,4);fp(a,2,0,0,1)
    constant(a,1,LIFT_MIN);fp(a,0x34,0,0,1);a.branch(17,8,0,f'{tag}_h');fp(a,6,0,1)
    a.label(f'{tag}_h');a.i(49,1,work,0x14);fp(a,1,12,1,0)
    a.addiu(4,work,0x10);a.call(QUERY);a.branch(5,2,0,f'{tag}_hit')
    a.i(49,12,21,4);a.addiu(4,work,0x10);a.call(QUERY);a.branch(4,2,0,f'{tag}_done')
    a.label(f'{tag}_hit');a.i(49,1,work,0x14);constant(a,2,SINK);fp(a,0,2,0,2)
    fp(a,0x34,0,2,1);a.branch(17,8,0,f'{tag}_found');a.i(57,0,work,0x14)
    a.label(f'{tag}_found');a.addiu(2,0,1)
    a.label(f'{tag}_done')


def commit_code():
    """a0 = actor, a1 = model, a2 = new root XYZ(W). The setter with a fresh sector, then the native resync."""
    a=Assembler(COMMIT);a.addiu(29,29,-0x40)
    for i,r in enumerate((16,17,18,31)):a.i(63,r,29,i*8)
    a.move(16,4);a.move(17,5);a.move(18,6);a.li(8,0x3F800000);a.sw(8,18,12)
    a.addiu(4,0,-1);a.move(5,18);a.call(A(0x23FF78));a.move(7,2)
    a.move(4,16);a.move(5,18);a.addiu(6,16,32);a.call(SETTER)
    for fn in (A(0x24E2B0),A(0x24E3F8)):a.move(4,17);a.call(fn)
    a.move(4,17);a.move(5,0);a.call(A(0x24DC58));a.move(4,16);a.call(SYNC_NATIVE)
    # Native swept movement must start at the repaired pose, not drag its
    # collision spheres through terrain from the old staging position.
    for off in range(0,240,4):a.lw(8,16,16+off);a.sw(8,16,256+off)
    a.lw(12,17,4000);a.lw(13,17,4004)
    abi.pointer(a,12,32,'spheres_done');abi.pointer(a,13,32,'spheres_done')
    for off in range(0,32,4):a.lw(8,12,off);a.sw(8,13,off)
    a.label('spheres_done')
    for i,r in enumerate((16,17,18,31)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x40);a.jr()
    data=a.finish();assert len(data)<=0x800;return data


def lift_code():
    """a0 = a participant, a1 = its staged root XYZ: Y goes onto the floor at that X/Z when the pose is more than
    SINK under it (query from Y - max(40, 4R), then from the arena ceiling). Every register and the native query
    globals are preserved."""
    fp,constant=terrain.fp,terrain.constant
    a=Assembler(LIFT);abi.save(a);a.move(16,4);a.move(17,5);a.addiu(18,29,0x2C0)
    model_of(a,16,20,'done')
    for off in (0,4,8):finite(a,17,off,'done')
    a.lw(8,20,0x1004);a.sw(8,18,0x20);finite(a,18,0x20,'done')
    a.i(49,0,18,0x20);constant(a,1,.1);fp(a,0x34,0,0,1);a.branch(17,8,1,'done')
    constant(a,1,512);fp(a,0x34,0,1,0);a.branch(17,8,1,'done')
    constant(a,1,1);fp(a,0,0,0,1);a.i(57,0,18,0x20)
    for off in (0,4,8):a.lw(8,17,off);a.sw(8,18,0x10+off)
    a.li(8,arena_bounds.STAGE);a.lw(8,8);abi.pointer(a,8,68,'done',temp=11,test=9)
    a.lw(21,8,64);abi.pointer(a,21,12,'done');finite(a,21,4,'done')
    for i,off in enumerate(terrain.QUERY_GLOBALS):a.lw(8,28,off);a.sw(8,29,0x300+4*i)
    floor_lift(a,18,'lift')
    for i,off in enumerate(terrain.QUERY_GLOBALS):a.lw(8,29,0x300+4*i);a.sw(8,28,off)
    a.lw(8,18,0x14);a.lw(9,17,4);a.branch(4,8,9,'done')
    a.sw(8,17,4)
    a.li(8,CONTROL);a.lw(9,8,TELEMETRY['floor_lifts']);a.addiu(9,9,1);a.sw(9,8,TELEMETRY['floor_lifts'])
    a.label('done');abi.restore(a);a.jr()
    data=a.finish();assert len(data)<=0x800;return data


def clamp_box(a,reject_label,tag):
    """Clamp WORK's sphere center (root + work+0x24) into the live radial and vertical limits (s5 = bounds)."""
    fp,constant=terrain.fp,terrain.constant
    a.i(49,0,21,0);constant(a,1,100);fp(a,1,0,0,1);a.i(49,1,18,0x20);fp(a,1,0,0,1)
    constant(a,1,1);fp(a,1,0,0,1);constant(a,1,0);fp(a,0x34,0,1,0);a.branch(17,8,0,reject_label)
    a.i(49,2,18,0x10);a.i(49,3,18,0x18);fp(a,2,4,2,2);fp(a,2,5,3,3);fp(a,0,4,4,5)
    fp(a,2,5,0,0);fp(a,0x36,0,4,5);a.branch(17,8,1,f'radial_ok{tag}')
    # EE sqrt uses ft rather than fs. Two nops match its pipeline latency.
    a.emit(0);a.emit(0);a.emit((17<<26)|(16<<21)|(4<<16)|(5<<6)|4)
    a.emit(0);a.emit(0);fp(a,3,5,0,5);fp(a,2,2,2,5);fp(a,2,3,3,5)
    a.i(57,2,18,0x10);a.i(57,3,18,0x18);a.label(f'radial_ok{tag}')
    a.i(49,0,18,0x14);a.i(49,1,18,0x24);fp(a,0,0,0,1)
    a.i(49,2,21,4);a.i(49,3,21,8);a.i(49,4,18,0x20)
    fp(a,0,2,2,4);fp(a,1,3,3,4);fp(a,0x36,0,2,3);a.branch(17,8,0,reject_label)
    fp(a,0x34,0,0,2);a.branch(17,8,0,f'ceiling_ok{tag}');fp(a,6,0,2);a.label(f'ceiling_ok{tag}')
    fp(a,0x34,0,3,0);a.branch(17,8,0,f'bottom_ok{tag}');fp(a,6,0,3);a.label(f'bottom_ok{tag}')
    fp(a,1,0,0,1);a.i(57,0,18,0x14);a.i(57,0,18,0x28) # retained aerial root Y


def safe_code():
    """Recovery after a staged move: the current pose (clamped into the arena, lifted onto the floor), else the
    pre-move pose, else the native side spawn (both with the full floor-footprint and solid-body checks)."""
    fp,constant=terrain.fp,terrain.constant
    a=Assembler(SAFE);abi.save(a);a.move(16,4);a.move(17,5);a.li(18,WORK);a.sw(0,17,80)
    a.lw(8,17,92);a.addiu(8,8,1);a.sw(8,17,92)
    model_of(a,16,20,'unreadable')
    for i,off in enumerate(terrain.QUERY_GLOBALS):a.lw(8,28,off);a.sw(8,29,0x300+4*i)
    a.li(8,arena_bounds.STAGE);a.lw(8,8);abi.pointer(a,8,68,'box_unreadable',temp=11,test=9)
    a.lw(9,8,56);a.i(11,11,9,4097);a.branch(4,11,0,'box_unreadable');a.branch(4,9,0,'box_unreadable')
    a.li(11,CONTROL);a.sw(9,11,64)
    a.lw(21,8,64);abi.pointer(a,21,12,'box_unreadable')
    for off in (0,4,8):finite(a,21,off,'box_unreadable')
    a.lw(8,20,0x1004);a.sw(8,18,0x20);finite(a,18,0x20,'nonfinite_data')
    a.i(49,0,20,0x1004);constant(a,1,.1);fp(a,0x34,0,0,1);a.branch(17,8,1,'nonfinite_data')
    constant(a,1,512);fp(a,0x34,0,1,0);a.branch(17,8,1,'nonfinite_data')
    constant(a,1,1);fp(a,0,0,0,1);a.i(57,0,18,0x20)
    # The native sphere center offset handles both ordinary and giant bodies.
    a.lw(8,20,4000);abi.pointer(a,8,24,'nonfinite_data',temp=11,test=9)
    a.i(49,0,8,4);a.i(49,1,20,2420);fp(a,1,0,0,1);a.i(57,0,18,0x24);finite(a,18,0x24,'nonfinite_data')
    # Candidate 0: the current root, kept where it is unless outside the arena box or under the floor.
    for off in (0,4,8):a.lw(8,16,16+off);a.sw(8,18,0x10+off)
    for off in (0x10,0x14,0x18):finite(a,18,off,'nonfinite_pose')
    clamp_box(a,'box_reject','0')
    floor_lift(a,18,'current');a.branch(5,2,0,'current_floor');reject(a,17,REJECT['floor'])
    a.label('current_floor')
    a.move(4,18);a.call(BODY);a.branch(5,2,0,'accept');reject(a,17,REJECT['body'])   # telemetry only
    a.jump('accept')
    a.label('nonfinite_pose');reject(a,17,REJECT['nonfinite']);a.jump('fallback')
    a.label('box_reject');reject(a,17,REJECT['box'])
    a.label('fallback')
    for attempt in (1,2):
        failed=f'reject{attempt}'
        if attempt==1:
            for off in (0,4,8):a.lw(8,17,32+off);a.sw(8,18,0x10+off)
        else:
            a.lw(4,16);a.i(12,4,4,1);a.addiu(5,18,0x10);a.addiu(6,18,0x30);a.move(7,0);a.call(A(0x2427A0))
        for off in (0x10,0x14,0x18):finite(a,18,off,f'nonfinite{attempt}')
        clamp_box(a,f'box{attempt}',str(attempt))
        # Query from the arena ceiling; an underground candidate cannot miss
        # its floor merely because the old root was already below the terrain.
        a.i(49,0,21,4);a.i(57,0,18,0x5C);a.move(4,18);a.call(FOOTPRINT)
        a.branch(4,2,0,f'footprint{attempt}')
        a.i(49,0,18,0x14);a.i(49,1,18,0x28);fp(a,0x34,0,1,0)
        a.branch(17,8,0,f'floor_done{attempt}');a.i(57,1,18,0x14);a.jump(f'floor_done{attempt}')
        a.label(f'footprint{attempt}');reject(a,17,REJECT['footprint']);a.jump(failed)
        a.label(f'floor_done{attempt}')
        # Boundary predicate uses the body center, not the fighter's feet.
        for off in (0,4,8):a.lw(8,18,0x10+off);a.sw(8,18,0x40+off)
        a.i(49,0,18,0x44);a.i(49,1,18,0x24);fp(a,0,0,0,1);a.i(57,0,18,0x44)
        arena_bounds.emit_inside(a,18,f'box{attempt}',f'safe{attempt}',point=0x40,margin=0)
        a.move(4,18);a.call(BODY);a.branch(5,2,0,f'fallback_ok{attempt}')
        reject(a,17,REJECT['body']);a.jump(failed)
        a.label(f'box{attempt}');reject(a,17,REJECT['box']);a.jump(failed)
        a.label(f'nonfinite{attempt}');reject(a,17,REJECT['nonfinite']);a.jump(failed)
        a.label(f'fallback_ok{attempt}');a.li(8,CONTROL);a.lw(9,8,28);a.addiu(9,9,1);a.sw(9,8,28);a.jump('accept')
        a.label(failed)
    a.li(8,CONTROL);a.lw(9,8,32);a.addiu(9,9,1);a.sw(9,8,32);a.jump('restore_queries')
    # Commit only a real change; record the largest recovery displacement.
    a.label('accept');a.addiu(8,0,1);a.sw(8,17,80)
    constant(a,6,0)
    for k,off in enumerate((0,4,8)):
        a.i(49,0,18,0x10+off);a.i(49,1,16,16+off);fp(a,1,0,0,1);fp(a,2,0,0,0);fp(a,0,6,6,0)
    constant(a,1,MOVED*MOVED);fp(a,0x36,0,6,1);a.branch(17,8,1,'restore_queries')
    a.emit(0);a.emit(0);a.emit((17<<26)|(16<<21)|(6<<16)|(7<<6)|4);a.emit(0);a.emit(0)   # f7 = sqrt(f6)
    a.li(8,CONTROL);a.i(49,1,8,TELEMETRY['largest_move']);fp(a,0x34,0,1,7);a.branch(17,8,0,'not_largest')
    a.i(57,7,8,TELEMETRY['largest_move'])
    a.label('not_largest')
    a.move(4,16);a.move(5,20);a.addiu(6,18,0x10);a.call(COMMIT)
    a.li(8,CONTROL);a.lw(9,8,20);a.addiu(9,9,1);a.sw(9,8,20);a.jump('restore_queries')
    a.label('box_unreadable');reject(a,17,REJECT['box']);a.jump('rejected')
    a.label('nonfinite_data');reject(a,17,REJECT['nonfinite'])
    a.label('rejected');a.li(8,CONTROL);a.lw(9,8,32);a.addiu(9,9,1);a.sw(9,8,32)
    a.label('restore_queries')
    for i,off in enumerate(terrain.QUERY_GLOBALS):a.lw(8,29,0x300+4*i);a.sw(8,28,off)
    a.label('reported')
    a.lw(8,17,88);a.li(9,CONTROL);a.lw(10,9,TELEMETRY['reject_bits']);a.r(0x25,10,10,8)
    a.sw(10,9,TELEMETRY['reject_bits'])
    a.label('done');abi.restore(a);a.jr()
    a.label('unreadable');reject(a,17,REJECT['nonfinite']);a.jump('reported')
    data=a.finish();assert len(data)<QUERY-SAFE;return data


def program():
    out=[]
    for _,entry,kind in HOOKS:
        a=Assembler(entry);abi.save(a);a.addiu(24,0,kind);a.jump(PLACE)
        data=a.finish();assert len(data)<=0x200;out.append((entry,data))
    values=dict(QUERY=QUERY,FOOTPRINT=FOOTPRINT,BODY=BODY,CONTROL=CONTROL,CANDIDATES=WORK)
    return out+[(PLACE,place_code()),(TICK,tick_code()),(SAFE,safe_code()),
        (QUERY,core.rebound(terrain.query_code,**values)()),
        (FOOTPRINT,core.rebound(terrain.footprint_code,**values)()),
        (COMMIT,commit_code()),
        (BODY,core.rebound(terrain.body_code,**values)()),
        (LIFT,lift_code())]


def build_memory(ram,settings=None,source='<offline-memory>'):
    settings=mod_settings.load_settings() if settings is None else mod_settings.validate_settings(settings)
    enabled=settings[KEY]
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    # Off on a match without the module adds nothing, before any size or identity check (legacy composition).
    if not enabled and (len(ram)<CONTROL+4 or not u(CONTROL)):return dict(serial=SERIAL,crc=CRC,source=source,blocks=[])
    if len(ram)!=0x8000000:raise ValueError('Cinematic positioning requires 128MiB captured RAM')
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or [u(core.MODE+4*i) for i in range(4)]!=[1,count,manager,count]:
        raise ValueError('Cinematic positioning requires captured fighter identities')
    code=program();hooks=[(p,jal(entry)) for p,entry,_ in HOOKS]+[(SYNC_SITE,jal(TICK))]
    if u(CONTROL):
        if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(MAGIC,manager,count):raise ValueError('Cinematic positioning ownership changed')
        if any(ram[p:p+len(b)]!=b for p,b in code+hooks):raise ValueError('Cinematic positioning code changed')
        parts=[(CONTROL+12,struct.pack('<I',enabled))]
    else:
        if any(ram[BASE:END]):raise ValueError('Cinematic positioning workspace occupied')
        for p,entry,_ in HOOKS:
            if ram[p:p+8]!=jal(SETTER)+NATIVE(p+4,4):raise ValueError(f'Native recenter call changed:{p:08X}')
        if ram[SYNC_SITE:SYNC_SITE+8]!=jal(SYNC_NATIVE)+NATIVE(SYNC_SITE+4,4):raise ValueError('Native pose synchronization changed')
        if arena_bounds.read(ram) is None:raise ValueError('Native playable arena bounds unavailable')
        import giant_options
        for p,n in ((SETTER,0x158),(SYNC_NATIVE,0xB0),(A(0x2427A0),0x118),(A(0x23FF78),0x198),
                    (A(0x24E2B0),0x148),(A(0x24E3F8),0xB0),(A(0x24DC58),0x60)):
            if ram[p:p+n]!=giant_options.native_helper(ram,p,n,NATIVE):raise ValueError(f'Native positioning dependency changed:{p:08X}')
        control=bytearray(0x100);struct.pack_into('<4I',control,0,MAGIC,manager,count,enabled)
        parts=code+hooks+[(CONTROL,control),(ROWS,bytes(STRIDE*12)),(WORK,bytes(0x80))]
    return dict(serial=SERIAL,crc=CRC,source=source,control=CONTROL,enabled=enabled,
        telemetry={k:CONTROL+v for k,v in TELEMETRY.items()},
        blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=bytes(b).hex()) for p,b in parts])
