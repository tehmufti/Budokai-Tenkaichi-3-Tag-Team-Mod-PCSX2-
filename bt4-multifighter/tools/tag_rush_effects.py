"""Bounded visual-only native beam emitters for tag-team rush attacks.

The real 16A7D0 emitter owns rendering and its native pool node. Both collision
and projectile translation are disabled immediately; the director alone applies
the scheduled attack damage. Endpoints follow posed hand/body bones, not target slots.

Enabled for supported offline matches after the guest bootstrap confirms
private initialization. Never call 14CEB0 under
an arbitrary live allocator, nor free a descriptor while its emitter exists.
"""
import struct
from prototype import Assembler
from native_map import A, ACTOR_HZ
import tag_team_rush as tag
import fusion_partner_lifecycle as full
import fresh_team_combat as core
import beam_struggle as fp

BASE, END = 0x06D60000, 0x06D73000
SPAWN, UPDATE, STOP, OWNED, GEOMETRY = (BASE, BASE+0x2000, BASE+0x4000, BASE+0x5000, BASE+0x6000)
INIT, RELEASE = BASE+0x8000, BASE+0xA000
IGNITE = BASE+0x7000
SELECT_SOURCE = GEOMETRY+0x880
CHARGE_SPAWN, CHARGE, CHARGE_END = 0x06D96000, 0x06D98000, 0x06D99000
FIRE_BIND = CHARGE+0x800
IMPACT = RELEASE  # Native copied-position one-shot; no private actor ownership.
CONTROL, ROWS, STRIDE = BASE+0xC000, BASE+0xC100, 0x1000
ARENAS, ARENA_SIZE = BASE+0xF000, 0x2000
MAGIC, PREPARED = 0x54465831, 0x46585031
C=dict(magic=0,manager=4,count=8,ready=12,pool=16,spawned=20,failed=24,init_status=28)
R=dict(node=0,body=4,source=8,target=12,source_model=16,target_model=20,
       source_index=24,target_index=28,manager=32,source_bone=36,pool=40,
       stopping=44,ticks=48,prepared=52,source_character=56,target_character=60,ignited=64,charged=68,flavor=72,
       native=76)
HEADER, META, DESC, CONTEXT, REQUEST = 0x100, 0x180, 0x220, 0x540, 0x7A0
SOURCE, DIRECTION, TARGET = 0x7E0, 0x7F0, 0x800
# The live arena reader also rejects coordinates at this magnitude. Keeping
# the visual endpoints within that broad ceiling prevents finite-but-corrupt
# joints from overflowing native beam/particle math before the scene cancels.
MAX_COORDINATE = 1_000_000.0
SBC_OPAQUE_TRAVEL = 600.0
SBC_MIN_SCALE, SBC_MAX_SCALE = .025, .20
NODE_SIZE, BODY_SIZE, MAX_TICKS = 64, 0x620, 10*ACTOR_HZ
NATIVE_POOL_OFFSET=-22600
EMIT=A(0x16A7D0); COLLISION=A(0x16ACA8); MOTION=A(0x16AC40)
HARD_RETIRE=A(0x16A6F0)
TERMINATE=A(0x16A900); ALIVE=A(0x16A9C0); BONE=A(0x2058E0)
CALLBACKS=A(0x2C3AD8); NATIVE_UPDATE=A(0x16A400)
NATIVE_IMPACT=A(0x187B00)
EXPLOSION = BASE+0xB000
WHITE_DRAW, WHITE_ALPHA = BASE+0x1000, BASE+0x1F00
WHITE_MAGIC = 0x54465731
W = dict(magic=32,manager=36,count=40,request=44,start=48,descriptor=52)
WHITE_TICKS = (3*ACTOR_HZ+4)//5
WHITE_RISE = max(2,(ACTOR_HZ+7)//8)
WHITE_PEAK = 32  # PS2 alpha128 is opaque: a gentle25% white, once.


def white_alphas():
    def smooth(t):return t*t*(3-2*t)
    return bytes(round(WHITE_PEAK*smooth(t/WHITE_RISE)) if t<=WHITE_RISE else
                 round(WHITE_PEAK*(1-smooth((t-WHITE_RISE)/(WHITE_TICKS-WHITE_RISE))))
                 for t in range(WHITE_TICKS+1))


def white_clock(a,out,base):
    import tag_rush_scene as scene
    a.lw(out,base,scene.S['total_ticks'])
    for key in ('settle_ticks','retirement_ticks'):
        a.lw(8,base,scene.S[key]);a.r(0x21,out,out,8)


def white_start_code():
    """a0victim role2/a1torso17 -> one scene-owned gentle white finish.

    A native172480 ultimate flash forces owner=-1 and shares one global fade
    node. This receipt instead lets the normal per-view native GS submission
    fade only cameras watching our scene. No native explosion/cloud is spawned.
    """
    import tag_rush_camera as camera
    import tag_rush_scene as scene
    import tag_rush_assets as assets
    a=Assembler(EXPLOSION);tag.save(a)
    a.li(8,2);a.branch(5,4,8,'no');a.li(8,17);a.branch(5,5,8,'no')
    gate(a,'no');a.li(16,CONTROL);a.li(17,scene.STATE);a.li(18,tag.CONTROL)
    a.lw(8,17);a.li(9,scene.SCENE_MAGIC);a.branch(5,8,9,'no')
    for key in ('cancelled','retiring'):
        a.lw(8,17,scene.S[key]);a.branch(5,8,0,'no')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'no')
    a.lw(19,17,scene.S['descriptor']);full.pointer(a,19,64,'no')
    a.li(8,assets.BASE);a.r(0x2B,8,19,8);a.branch(5,8,0,'no')
    a.li(8,assets.END-64);a.r(0x2B,8,8,19);a.branch(5,8,0,'no')
    a.lw(10,19,28);a.i(12,8,10,assets.FINISHER);a.branch(4,8,0,'no')
    a.i(12,8,10,assets.BEAM_LEAD|assets.BEAM_PARTNER);a.branch(4,8,0,'no')
    a.li(21,scene.ROWS+2*scene.STRIDE);scene.identity(a,21,'no','white_victim')
    a.lw(8,16,W['magic']);a.li(9,WHITE_MAGIC);a.branch(5,8,9,'publish')
    for off,key in ((W['manager'],'manager'),(W['count'],'count'),(W['request'],'start_requests')):
        a.lw(8,16,off);a.lw(9,18,tag.C[key]);a.branch(5,8,9,'publish')
    a.lw(8,16,W['descriptor']);a.branch(4,8,19,'yes')
    a.label('publish');a.sw(0,16,W['magic'])
    for off,key in ((W['manager'],'manager'),(W['count'],'count'),(W['request'],'start_requests')):
        a.lw(8,18,tag.C[key]);a.sw(8,16,off)
    a.sw(19,16,W['descriptor']);white_clock(a,20,17);a.sw(20,16,W['start'])
    a.li(8,WHITE_MAGIC);a.sw(8,16,W['magic'])
    a.label('yes');a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr()
    data=a.finish();assert EXPLOSION+len(data)<=CONTROL;return data


def white_draw_code():
    """Draw one translucent native sprite in the authenticated current view.

    This has no draw-clock side effects: two/four views and repeated draws get
    exactly the same alpha. Native pause freezes the director clock; cancelled,
    replaced, ended or newly-started scenes cannot reuse a stale white receipt.
    """
    import tag_rush_camera as camera
    import tag_rush_scene as scene
    import fresh_team_camera as follow
    import viewport_hud as hud
    import guest_healthbars as bars
    from regional import SCISSOR_Y1,Y_ORIGIN
    a=Assembler(WHITE_DRAW);tag.save(a);gate(a,'done')
    a.li(16,CONTROL);a.li(17,scene.STATE);a.li(18,tag.CONTROL)
    a.lw(8,16,W['magic']);a.li(9,WHITE_MAGIC);a.branch(5,8,9,'done')
    a.lw(8,17);a.li(9,scene.SCENE_MAGIC);a.branch(5,8,9,'done')
    a.lw(8,17,scene.S['cancelled']);a.branch(5,8,0,'done')
    for off,key in ((W['manager'],'manager'),(W['count'],'count'),(W['request'],'start_requests')):
        a.lw(8,16,off);a.lw(9,18,tag.C[key]);a.branch(5,8,9,'done')
    a.lw(8,16,W['descriptor']);a.lw(9,17,scene.S['descriptor']);a.branch(5,8,9,'done')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    white_clock(a,20,17);a.lw(8,16,W['start']);a.r(0x23,20,20,8)
    a.i(11,8,20,WHITE_TICKS);a.branch(4,8,0,'done')
    a.li(8,WHITE_ALPHA);a.r(0x21,8,8,20);a.i(36,20,8,0);a.branch(4,20,0,'done')
    a.lw(17,28,-22176);full.pointer(a,17,832,'done')
    # The same rectangle-to-physical-subject binding used by tag HUD handles
    # ordinary split, quad, spectator takeover and either layout orientation.
    a.li(19,follow.SUCCESSOR_CONTROL+8)
    a.lw(8,18,tag.C['shared']);a.branch(5,8,0,'subject')
    # Full-screen passes use the current followed subject. Every reduced
    # viewport requires an authenticated descriptor, even if HUD is hidden.
    for off,value in ((512,0),(516,511),(520,0),(524,SCISSOR_Y1)):
        a.lw(8,17,off);a.li(9,value);a.branch(5,8,9,'split_subject')
    a.jump('subject');a.label('split_subject')
    a.li(8,hud.CONTROL);a.lw(9,8);a.li(10,hud.MAGIC);a.branch(5,9,10,'done')
    a.lw(9,8,4);a.lw(10,18,tag.C['manager']);a.branch(5,9,10,'done')
    a.lw(9,8,12);a.addiu(9,9,-2);a.i(11,9,9,hud.MAX_VIEWS-1);a.branch(4,9,0,'done')
    a.li(21,hud.VIEWS);a.move(22,0)
    a.label('view')
    for off,desc in ((512,4),(516,8),(520,12),(524,16)):
        a.lw(8,17,off);a.lw(9,21,desc);a.branch(5,8,9,'next_view')
    a.lw(19,21,20);a.jump('subject')
    a.label('next_view');a.addiu(21,21,hud.VIEW_STRIDE);a.addiu(22,22,1)
    a.li(8,hud.MAX_VIEWS);a.branch(5,22,8,'view');a.jump('done')
    a.label('subject');full.pointer(a,19,4,'done');a.lw(4,19);a.call(camera.QUERY)
    a.li(8,camera.CAMERA);a.branch(5,2,8,'done')
    a.lw(9,8,812);a.li(10,1);a.branch(5,9,10,'done')
    finite(a,17,(0,4,8,16,20,24,32,36,40),'done');a.li(8,camera.CAMERA)
    # Refuse a different camera even if its logical subject happens to be a
    # participant. Quad views copy only the view matrices; portrait fitting
    # changes their translation. Compare the unchanged3x3 view orientation.
    for off in (0,4,8,16,20,24,32,36,40):
        a.lw(9,17,off);a.lw(10,8,off);a.branch(5,9,10,'done')
    a.lw(4,17,512);a.lw(6,17,516);a.lw(5,17,520);a.lw(7,17,524)
    for reg,limit in ((4,512),(6,512),(5,SCISSOR_Y1+1),(7,SCISSOR_Y1+1)):
        a.i(11,9,reg,limit);a.branch(4,9,0,'done')
    a.r(0x2B,9,6,4);a.branch(5,9,0,'done');a.r(0x2B,9,7,5);a.branch(5,9,0,'done')
    a.addiu(4,4,1792);a.addiu(6,6,1793);a.addiu(5,5,Y_ORIGIN);a.addiu(7,7,Y_ORIGIN+1)
    for reg in (4,5,6,7):a.r(0,reg,0,reg,4)
    a.r(0,8,0,20,24);a.li(9,0x00FFFFFF);a.r(0x25,8,8,9);a.call(bars.RECT)
    a.label('done');tag.restore(a);a.jr();data=a.finish()
    assert WHITE_DRAW+len(data)<=WHITE_ALPHA;return data


def gate(a,fail,active=True):
    core.gate(a,fail)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,C['manager']);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,C['count']);a.branch(5,9,10,fail)
    a.lw(9,8,C['ready']);a.li(11,1);a.branch(5,9,11,fail)
    a.lw(9,8,C['pool']);a.lw(11,28,NATIVE_POOL_OFFSET);a.branch(5,9,11,fail)
    a.li(8,tag.CONTROL);a.lw(9,8);a.li(11,tag.MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,tag.C['manager']);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,tag.C['count']);a.branch(5,9,10,fail)
    if active:
        a.lw(9,8,tag.C['active']);a.li(11,1);a.branch(5,9,11,fail)


def row_pointer(a,slot,row,fail):
    a.i(11,8,slot,2);a.branch(4,8,0,fail)
    a.r(0,row,0,slot,12);a.li(8,ROWS);a.r(0x21,row,row,8)


def finite(a,base,offsets,fail):
    for offset in offsets:
        a.lw(8,base,offset);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,fail)


def bounded_point(a,base,offsets,fail):
    maximum=struct.unpack('<I',struct.pack('<f',MAX_COORDINATE))[0]
    for offset in offsets:
        a.lw(8,base,offset);a.li(9,0x7FFFFFFF);a.r(0x24,8,8,9)
        a.li(9,maximum);a.r(0x2B,8,9,8);a.branch(5,8,0,fail)


def identity(a,row,fail):
    for indexoff,actoroff,modeloff,charoff in (
            (R['source_index'],R['source'],R['source_model'],R['source_character']),
            (R['target_index'],R['target'],R['target_model'],R['target_character'])):
        a.lw(10,row,indexoff);a.li(8,CONTROL);a.lw(8,8,C['count']);a.r(0x2B,8,10,8);a.branch(4,8,0,fail)
        a.lw(22,row,actoroff);full.pointer(a,22,0x1600,fail)
        a.lw(8,22);a.branch(5,8,10,fail)
        a.r(0,10,0,10,2);a.li(8,core.POINTERS);a.r(0x21,8,8,10);a.lw(8,8);a.branch(5,8,22,fail)
        a.lw(23,row,modeloff);full.pointer(a,23,0x1700,fail)
        a.lw(10,22,12);a.i(11,8,10,12);a.branch(4,8,0,fail)
        a.lw(8,23,16);a.branch(5,8,10,fail)
        a.r(0,10,0,10,2);a.li(8,core.MODELS);a.r(0x21,8,8,10);a.lw(8,8);a.branch(5,8,23,fail)
        a.lw(8,23,12);a.lw(9,row,charoff);a.branch(5,8,9,fail)
        for offset in (4,8):
            a.lw(8,23,offset);a.li(9,1);a.branch(5,8,9,fail)


def owned_code():
    """a0 exact private row -> v0 native body or0, no global battle gate.

    Node reuse is authenticated against its pool, exact body, private header
    and descriptor. A stale pointer can never stop a different native attack.
    """
    a=Assembler(OWNED);a.li(8,ROWS);a.branch(4,4,8,'row');a.li(8,ROWS+STRIDE);a.branch(5,4,8,'no')
    a.label('row');a.lw(10,4,R['node']);full.pointer(a,10,NODE_SIZE,'no')
    a.lw(11,4,R['pool']);a.lw(8,28,NATIVE_POOL_OFFSET);a.branch(5,11,8,'no')
    a.lw(8,10,32);a.branch(5,8,11,'no')
    a.lw(8,10,40);a.li(9,CALLBACKS);a.branch(5,8,9,'no')
    a.lw(2,10,56);full.pointer(a,2,BODY_SIZE,'no');a.lw(8,4,R['body']);a.branch(5,8,2,'no')
    a.lw(8,2);a.addiu(9,4,HEADER);a.branch(5,8,9,'no')
    a.lw(8,2,48);a.addiu(9,4,DESC);a.branch(5,8,9,'no')
    a.lw(8,2,1408);a.i(12,8,8,1);a.branch(4,8,0,'no');a.jr()
    a.label('no');a.move(2,0);a.jr();return a.finish()


def geometry_code():
    """a0 private row -> atomically publish bounded endpoints, v0 success."""
    a=Assembler(GEOMETRY);tag.save(a);a.move(16,4);identity(a,16,'no')
    source,target,direction=0x300,0x310,0x320
    a.lw(17,16,R['source_model']);a.lw(18,16,R['target_model'])
    a.lw(19,16,R['source_bone']);a.li(8,31);a.branch(4,19,8,'hand');a.li(8,45);a.branch(4,19,8,'hand')
    a.li(8,54);a.branch(5,19,8,'no')
    a.label('hand');a.r(0,8,0,19,2);a.r(0x21,8,17,8);a.lw(10,8,3436);full.pointer(a,10,80,'no')
    bounded_point(a,10,(64,68,72),'no')
    a.lw(10,18,3436+4*17);full.pointer(a,10,80,'no');bounded_point(a,10,(64,68,72),'no')
    # Native bone lookup can apply additional model context. Validate its
    # results in private stack storage too; a rejected update leaves the last
    # good emitter geometry intact and never exposes a partial endpoint.
    a.lw(4,17,16);a.move(5,19);a.addiu(6,29,source);a.call(BONE)
    a.lw(4,18,16);a.li(5,17);a.addiu(6,29,target);a.call(BONE)
    bounded_point(a,29,(source,source+4,source+8,target,target+4,target+8),'no')
    fp.fconst(a,3,0.0)
    for off in (0,4,8):
        a.i(49,0,29,target+off);a.i(49,1,29,source+off);fp.fop(a,1,0,0,1)
        a.i(57,0,29,direction+off);fp.fop(a,2,0,0,0);fp.fop(a,0,3,3,0)
    fp.fconst(a,1,.0001);fp.fop(a,0x34,0,1,3);a.branch(17,8,0,'no')
    fp.fop(a,4,3,3,3)
    for off in (0,4,8):
        a.i(49,0,29,direction+off);fp.fop(a,3,0,0,3);a.i(57,0,29,direction+off)
    finite(a,29,(direction,direction+4,direction+8),'no')
    a.sw(0,29,direction+12)
    for offset in (source,target):a.li(8,0x3F800000);a.sw(8,29,offset+12)
    for scratch,published in ((source,SOURCE),(target,TARGET),(direction,DIRECTION)):
        for off in range(0,16,4):a.lw(8,29,scratch+off);a.sw(8,16,published+off)
    a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();data=a.finish()
    assert GEOMETRY+len(data)<=SELECT_SOURCE;return data


def publish_parent_geometry(a,row,body,label):
    """Adapt the private endpoints to the real SBC emitter's native axes.

    Native 16A108 copies the request source into both 0x5A0 and 0x5B0;
    169F48 passes 0x5B0 to 14FF50. SBC's actual spiral rule uses selector5,
    whose native context index is -1, so that origin is its only placement.
    Its spiral rule reverses the parent axis. Native particle world quads
    prove a forward private axis then travels away from the victim; supply
    the native backward axis only for this reviewed descriptor. The private
    row keeps its ordinary muzzle-to-target direction for bounds and aiming.
    Ordinary private beam recipes retain their existing endpoint contract.
    """
    for source,dest in ((SOURCE,1440),(TARGET,1472),(DIRECTION,1376)):
        for off in range(0,16,4):a.lw(8,row,source+off);a.sw(8,body,dest+off)
    a.addiu(12,row,TARGET);a.lw(8,row,R['flavor']);a.li(9,1)
    a.branch(5,8,9,label);a.addiu(12,row,SOURCE)
    a.li(9,0x80000000)
    for off in (0,4,8):
        a.lw(8,row,DIRECTION+off);a.r(0x26,8,8,9);a.sw(8,body,1376+off)
    a.label(label)
    for off in range(0,16,4):a.lw(8,12,off);a.sw(8,body,1456+off)
    publish_firing_scale(a,row,body,label+'_scale')


def publish_firing_scale(a,row,body,label,force=False):
    """Fit the reviewed native spiral's first opaque segment to this lane.

    Native191D28/192668 scale the original particle quads uniformly. The
    reviewed command entry32 travels60units/update and reaches full alpha at its tenth
    placement (600units). Keep the genuine texture, rotating shape and color;
    fit that visual to the actual endpoint distance. Charge remains full size.
    """
    a.lw(8,row,R['flavor']);a.li(9,1);a.branch(5,8,9,label+'_done')
    if not force:
        a.lw(8,row,R['ignited']);a.branch(4,8,0,label+'_done')
    fp.fconst(a,0,0.)
    for off in (0,4,8):
        a.i(49,1,row,TARGET+off);a.i(49,2,row,SOURCE+off)
        fp.fop(a,1,1,1,2);fp.fop(a,2,1,1,1);fp.fop(a,0,0,0,1)
    # The EE square-root operand is Ft. Keep it explicit even though Fs and
    # Ft are both f0 here; the ordinary point guard already bounds this input.
    fp.fop(a,4,0,0,0);fp.fconst(a,1,SBC_OPAQUE_TRAVEL);fp.fop(a,3,0,0,1)
    fp.fconst(a,1,SBC_MIN_SCALE);fp.fop(a,0x34,0,0,1)
    a.branch(17,8,0,label+'_minimum');fp.fop(a,6,0,1)
    a.label(label+'_minimum');fp.fconst(a,1,SBC_MAX_SCALE);fp.fop(a,0x34,0,1,0)
    a.branch(17,8,0,label+'_publish');fp.fop(a,6,0,1)
    a.label(label+'_publish');a.i(57,0,body,1420)
    a.label(label+'_done')


def select_source_code():
    """a0 owned effect row ->v0 posed muzzle bone31/45/54, or0.

    Native14B108 copies the selected slot's flags into converted metadata+60;
    native14AA18/14A958 use bit0x2000 to emit from bone54. Apply that rule only
    to the exact captured own firing clip, never a different special or generic
    clash364. Otherwise choose the actual forward hand for this pose.
    """
    import tag_rush_scene as scene
    import tag_rush_native_pose as pose
    import tag_rush_pose_profiles as profiles
    import tag_rush_assets as assets
    a=Assembler(SELECT_SOURCE);tag.save(a);a.move(16,4);a.move(17,0)
    a.li(8,ROWS);a.li(20,scene.ROWS);a.branch(4,16,8,'row')
    a.li(8,ROWS+STRIDE);a.branch(5,16,8,'no');a.li(20,scene.ROWS+scene.STRIDE)
    a.label('row');a.lw(21,16,R['source_model']);a.lw(22,16,R['target_model'])
    a.li(8,scene.STATE);a.lw(9,8);a.li(10,scene.SCENE_MAGIC);a.branch(5,9,10,'hands')
    a.lw(11,8,scene.S['descriptor']);full.pointer(a,11,64,'no')
    a.li(9,assets.BASE);a.r(0x2B,10,11,9);a.branch(5,10,0,'no')
    a.li(9,assets.END-64);a.r(0x2B,10,9,11);a.branch(5,10,0,'no')
    a.lw(8,11,28);a.i(12,8,8,pose.OWN_CLASH_POSE);a.branch(4,8,0,'hands')
    a.lw(8,20,pose.ACTIVE);a.li(9,1);a.branch(5,8,9,'hands')
    a.lw(8,20,scene.R['model']);a.branch(5,8,21,'hands')
    a.lw(8,20,pose.FIRE_CLIP)
    for slot,clip in enumerate((264,298,332)):
        a.li(9,clip);a.li(19,4*slot);a.branch(4,8,9,'flags')
    a.jump('hands')
    a.label('flags');a.lw(18,20,pose.BANK);a.branch(4,18,0,'own_flags')
    a.move(4,21);a.call(profiles.QUERY);a.branch(1,2,0,'no');a.branch(5,3,18,'no')
    a.lw(8,18,profiles.BANK_FLAGS);a.jump('muzzle_flags')
    a.label('own_flags');a.lw(10,21,2348);full.pointer(a,10,640,'no')
    a.r(0x21,10,10,19);a.lw(8,10)
    a.label('muzzle_flags');a.i(12,8,8,0x2000);a.branch(4,8,0,'canonical_hand')
    a.lw(10,21,3436+4*54);full.pointer(a,10,80,'no');finite(a,10,(64,68,72),'no')
    a.li(2,54);a.jump('done')
    # The actual Special Beam Cannon events bind both charge512 and fire1024
    # to mask0x10000 (native24D518 ->bone31). Selecting the nearest forward
    # hand while startup blends from the preceding stance can attach the glow
    # to the other arm. Preserve this native binding only for an authenticated
    # own Piccolo firing sequence; generic/donated/other slots stay geometric.
    a.label('canonical_hand');a.branch(5,18,0,'hands')
    a.lw(8,21,12);a.li(9,22);a.branch(4,8,9,'piccolo_early')
    a.li(9,23);a.branch(5,8,9,'hands');a.li(9,264);a.jump('piccolo_clip')
    a.label('piccolo_early');a.li(9,332)
    a.label('piccolo_clip');a.lw(8,20,pose.FIRE_CLIP);a.branch(5,8,9,'hands');a.li(17,31)
    a.label('hands')
    for reg,bone in ((12,31),(13,45)):
        a.lw(reg,21,3436+4*bone);full.pointer(a,reg,80,'no');finite(a,reg,(64,68,72),'no')
    a.lw(14,22,3436+4*17);full.pointer(a,14,80,'no');finite(a,14,(64,68,72),'no')
    finite(a,21,(2416,2420,2424),'no');a.li(2,31);a.branch(5,17,0,'done');fp.fconst(a,3,0.)
    for off in (0,4,8):
        a.i(49,0,13,64+off);a.i(49,1,12,64+off);fp.fop(a,1,0,0,1)
        a.i(49,1,14,64+off);a.i(49,2,21,2416+off);fp.fop(a,1,1,1,2)
        fp.fop(a,2,0,0,1);fp.fop(a,0,3,3,0)
    a.li(2,31);fp.fconst(a,0,0.);fp.fop(a,0x34,0,0,3)
    a.branch(17,8,0,'done');a.li(2,45);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();data=a.finish()
    assert SELECT_SOURCE+len(data)<=IGNITE;return data


def spawn_code(color=False,charging=False,special=False):
    """a0 role0/1, a1 lifetime actor ticks1..10seconds -> v0 success.

    Requires two privately parsed descriptors and PREPARED row receipts.
    The allocator setup is intentionally separate from an in-progress scene.
    """
    import tag_rush_scene as scene
    import tag_rush_assets as assets
    a=Assembler(CHARGE_SPAWN if charging else SPAWN);tag.save(a);a.move(17,4);a.move(18,5);gate(a,'no')
    row_pointer(a,17,16,'no');a.addiu(8,18,-1);a.i(11,8,8,MAX_TICKS);a.branch(4,8,0,'no')
    a.lw(8,16,R['prepared']);a.li(9,PREPARED);a.branch(5,8,9,'no')
    a.lw(8,16,R['node']);a.branch(5,8,0,'no');a.sw(0,16,R['native'])
    for offset,value in ((HEADER+36,META),(DESC+796,HEADER)):
        a.lw(8,16,offset);a.addiu(9,16,value);a.branch(5,8,9,'no')
    a.li(8,tag.CONTROL);a.r(0,9,0,17,2);a.r(0x21,9,8,9);a.lw(19,9,tag.C['initiator']);a.lw(20,8,tag.C['victim'])
    a.branch(4,19,20,'no');a.lw(10,8,tag.C['count'])
    for index,actoroff,modeloff,indexoff,charoff in ((19,R['source'],R['source_model'],R['source_index'],R['source_character']),
            (20,R['target'],R['target_model'],R['target_index'],R['target_character'])):
        a.r(0x2B,9,index,10);a.branch(4,9,0,'no')
        a.r(0,8,0,index,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(21,8);full.pointer(a,21,0x1600,'no')
        a.lw(8,21);a.branch(5,8,index,'no');a.sw(21,16,actoroff);a.sw(index,16,indexoff)
        a.lw(22,21,12);a.i(11,8,22,12);a.branch(4,8,0,'no')
        a.r(0,8,0,22,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(23,8);full.pointer(a,23,0x1700,'no')
        a.lw(8,23,16);a.branch(5,8,22,'no');a.sw(23,16,modeloff);a.lw(8,23,12);a.sw(8,16,charoff)
    # A character's own clash pose may point either hand toward the victim.
    # Choose once when the emitter starts, using the real posed bones; retain that
    # native bone binding throughout the emitter's lifetime. Older borrowed
    # endings keep their known hand45 (custom) / hand31 (Sadistic Dance).
    a.li(19,31);a.li(8,scene.STATE);a.lw(9,8);a.li(10,scene.SCENE_MAGIC)
    a.branch(5,9,10,'source_ready')
    a.lw(11,8,scene.S['descriptor']);full.pointer(a,11,64,'no')
    a.li(9,assets.BASE);a.r(0x2B,10,11,9);a.branch(5,10,0,'no')
    a.li(9,assets.END-64);a.r(0x2B,10,9,11);a.branch(5,10,0,'no')
    a.lw(10,11,28);a.i(12,9,10,assets.OWN_CLASH_POSE);a.branch(5,9,0,'own_source')
    a.i(12,9,10,assets.CUSTOM_FINISHER);a.branch(4,9,0,'source_ready')
    a.li(19,45)
    a.jump('source_ready')
    a.label('own_source');a.move(4,16);a.call(SELECT_SOURCE);a.branch(4,2,0,'no');a.move(19,2)
    a.label('source_ready');a.sw(19,16,R['source_bone'])
    if special:
        import tag_rush_special_beam as sbc
        # Early/End Piccolo fire the game's own Special Beam Cannon object
        # (family0, his slot4 record/descriptor). It owns charge, fingers,
        # drill core and spiral; this row keeps no private emitter. If it
        # cannot start, the ordinary private recipe below is used instead.
        a.lw(8,16,R['source_character']);a.li(9,22);a.branch(4,8,9,'native_sbc')
        a.li(9,23);a.branch(5,8,9,'scoped_select')
        a.label('native_sbc');a.move(4,16);a.li(5,int(charging));a.call(sbc.NATIVE_SPAWN)
        a.branch(4,2,0,'scoped_select')
        a.li(8,1);a.sw(8,16,R['native']);a.sw(0,16,R['flavor']);a.jump('native_started')
        a.label('scoped_select')
        a.move(4,16);a.lw(5,16,R['source_character']);a.call(sbc.SELECT);a.branch(4,2,0,'no')
        a.i(11,8,3,2);a.branch(4,8,0,'no');a.sw(3,16,R['flavor'])
    else:a.sw(0,16,R['flavor'])
    if color:
        import tag_rush_colors as colors
        if special:
            a.lw(8,16,R['flavor']);a.branch(5,8,0,'palette_ready')
        a.move(4,16);a.call(colors.APPLY);a.branch(4,2,0,'no')
        if special:a.label('palette_ready')
    a.move(4,16);a.call(GEOMETRY);a.branch(4,2,0,'no')
    a.lw(19,28,NATIVE_POOL_OFFSET);full.pointer(a,19,24,'no');a.lw(10,19,12);full.pointer(a,10,64,'no')
    a.lw(8,10,32);a.branch(5,8,19,'no')
    a.lw(8,16,R['source_model']);a.lw(8,8,16);a.sw(8,16,HEADER)
    a.sw(8,16,HEADER+32)
    # Context anchors are native manual bindings; neither participant needs
    # synthetic move flags or a beam special in their own move list.
    a.addiu(4,16,CONTEXT);a.move(5,0);a.li(6,592);a.call(A(0x2A9ACC))
    for phase in (0,1):
        a.addiu(4,16,CONTEXT);a.li(5,phase);a.lw(6,16,R['source_bone']);a.move(7,0);a.call(A(0x1517A0))
    a.addiu(4,16,HEADER);a.addiu(5,16,CONTEXT);a.call(A(0x1512C8))
    for off,ptr in ((0,HEADER),(4,DESC),(8,CONTEXT),(12,SOURCE),(16,DIRECTION)):
        a.addiu(8,16,ptr);a.sw(8,16,REQUEST+off)
    for off,value in ((20,0),(24,1),(28,1),(32,1),(36,0x41200000),(40,0x3F800000),(44,0),(48,0)):
        a.li(8,value);a.sw(8,16,REQUEST+off)
    a.addiu(4,16,REQUEST);a.call(EMIT);a.branch(4,2,0,'failed');a.sw(2,16,R['node'])
    full.pointer(a,2,NODE_SIZE,'unknown_node');a.lw(8,2,56);a.sw(8,16,R['body']);a.sw(19,16,R['pool'])
    a.move(4,16);a.call(OWNED);a.branch(4,2,0,'unknown_node')
    a.lw(4,16,R['node']);a.li(5,1);a.call(COLLISION);a.branch(4,2,0,'stop')
    a.lw(4,16,R['node']);a.li(5,1);a.call(MOTION);a.branch(4,2,0,'stop')
    a.sw(18,16,R['ticks']);a.sw(0,16,R['stopping'])
    a.lw(21,16,R['body'])
    if charging:
        #16A108 admits only the firing pair supplied by the request.169F48
        #therefore never updates manually started charge children: their glow
        #stays at the first pose's hand while the character draws it back.
        #Keep both native event pairs active on this private parent so its
        #ordinary updater moves existing charge children with the posed hand.
        a.sw(0,21,40);a.sw(0,21,44);a.li(8,2);a.sw(8,21,1412)
    publish_parent_geometry(a,16,21,'spawn_native_origin')
    # The native constructor replaces the selected phase's hand binding from
    # the real move's events. Restore our explicit posed-hand bindings before
    # activating visual children; neither actor is running that donor move.
    for phase in (0,1):
        a.addiu(4,21,64);a.li(5,phase);a.lw(6,16,R['source_bone']);a.move(7,0);a.call(A(0x1517A0))
    a.addiu(4,16,HEADER);a.addiu(5,21,64);a.call(A(0x1512C8))
    a.sw(0,16,R['ignited']);a.sw(0,16,R['charged'])
    a.move(4,16);a.call(CHARGE if charging else IGNITE);a.branch(4,2,0,'stop')
    a.label('native_started')
    a.li(8,CONTROL);a.lw(9,8,C['spawned']);a.addiu(9,9,1);a.sw(9,8,C['spawned'])
    a.li(2,1);a.jump('done')
    a.label('stop');a.lw(4,16,R['node']);a.call(TERMINATE);a.li(8,1);a.sw(8,16,R['stopping'])
    a.jump('failed')
    # A changed allocator contract must not create more unknown objects. Keep
    # the receipt for inspection; do not call a destructor on an unowned node.
    a.label('unknown_node');a.li(8,CONTROL);a.sw(0,8,C['ready'])
    a.label('failed');a.li(8,CONTROL);a.lw(9,8,C['failed']);a.addiu(9,9,1);a.sw(9,8,C['failed'])
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();result=a.finish()
    assert len(result)<=0x2000;return result


def ignite_code(charging=False,special=False):
    """a0 owned row -> advance its reviewed native charge or firing event.

    A native beam parent normally reads special-move event bits in14D7A0.
    Borrowed poses do not publish those gameplay events.14D8A8 is the native
    explicit-event equivalent: raw bit1 charges and bit2 fires, with no model mutation.
    Once started, the ordinary emitter updates and retires these same children.
    """
    # Native 14D8A8 maps raw bit1 to charge rules (kind0), bit2 to fire
    # (kind1). Firing also stops charge rules whose native end event is2.
    # Both stages share one authenticated emitter and its ordinary children.
    flag='charged' if charging else 'ignited'
    a=Assembler(CHARGE if charging else IGNITE);tag.save(a);a.move(16,4)
    if special and not charging:
        # A native Special Beam Cannon row fires that object's own event.
        import tag_rush_special_beam as sbc
        a.li(8,ROWS);a.branch(4,16,8,'native_row');a.li(8,ROWS+STRIDE);a.branch(5,16,8,'private_row')
        a.label('native_row');a.lw(8,16,R['native']);a.branch(4,8,0,'private_row')
        a.call(sbc.NATIVE_IGNITE);a.jump('done')
        a.label('private_row')
    a.move(4,16);a.call(OWNED);a.branch(4,2,0,'no');a.move(17,2)
    a.lw(8,16,R[flag]);a.branch(5,8,0,'yes')
    a.lw(8,16,R['prepared']);a.li(9,PREPARED);a.branch(5,8,9,'no')
    if not charging:
        a.lw(8,16,R['charged']);a.branch(4,8,0,'bound')
        a.move(4,16);a.call(FIRE_BIND);a.branch(4,2,0,'no');a.label('bound')
        publish_firing_scale(a,16,17,'ignite_firing_scale',force=True)
    a.addiu(18,16,DESC);a.move(19,0)
    a.label('group');a.r(0,8,0,19,4);a.r(0x21,8,18,8)
    a.lw(10,8,12);a.branch(4,10,0,'next_group');a.i(36,22,8,20);full.pointer(a,10,16,'no')
    a.i(36,21,10,1);a.r(0x21,9,21,22)
    a.lw(8,16,R['flavor']);a.branch(4,8,0,'ordinary_rule_limit')
    a.li(10,1);a.branch(5,8,10,'no');a.i(11,9,9,26);a.jump('rule_limit_ready')
    a.label('ordinary_rule_limit');a.i(11,9,9,20)
    a.label('rule_limit_ready');a.branch(4,9,0,'no')
    a.move(20,0);a.branch(4,21,0,'next_group')
    a.label('rule');a.r(0x21,8,22,20);a.r(0,8,0,8,6);a.lw(9,18,8);a.r(0x21,10,9,8)
    full.pointer(a,10,64,'no');a.i(36,8,10,8)
    if charging:
        a.branch(5,8,0,'next_rule');a.i(36,8,10,10);a.branch(4,8,0,'fire')
        a.li(9,5);a.branch(5,8,9,'next_rule')
    else:
        a.li(9,1);a.branch(4,8,9,'fire_selector')
        a.branch(5,8,0,'next_rule');a.lw(8,16,R['charged']);a.branch(4,8,0,'next_rule')
        a.i(36,8,10,9);a.li(9,2);a.branch(5,8,9,'next_rule');a.jump('fire')
        a.label('fire_selector');a.i(36,8,10,10);a.branch(4,8,9,'fire')
        a.li(9,5);a.branch(5,8,9,'next_rule')
    a.label('fire');a.move(4,18);a.addiu(5,17,656);a.move(6,0);a.move(7,19);a.move(8,20)
    a.move(9,0);a.move(10,0);a.li(11,1 if charging else 2);a.call(A(0x14D8A8));a.branch(4,2,0,'next_rule')
    a.move(11,2);a.move(4,18);a.addiu(5,17,656);a.addiu(6,17,64);a.addiu(7,17,1456)
    a.addiu(8,17,1376);a.move(9,19);a.move(10,20);a.i(49,12,17,1420);a.call(A(0x14FF50))
    a.label('next_rule');a.addiu(20,20,1);a.branch(5,20,21,'rule')
    a.label('next_group');a.addiu(19,19,1);a.li(8,19);a.branch(5,19,8,'group')
    a.li(8,1);a.sw(8,16,R[flag])
    a.label('yes');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();result=a.finish()
    assert len(result)<=(FIRE_BIND-CHARGE if charging else INIT-IGNITE);return result


def fire_bind_code():
    """Rebind once to the firing pose's actual forward hand, on the same node.

    A character can reverse its forward hand between charge261 and fire264.
    Updating the native contexts before firing avoids a muzzle on the back
    hand. Later recoil keeps this binding rather than swapping every frame.
    """
    a=Assembler(FIRE_BIND);tag.save(a);a.move(16,4);a.call(OWNED)
    a.branch(4,2,0,'no');a.move(17,2);identity(a,16,'no')
    a.move(4,16);a.call(SELECT_SOURCE);a.branch(4,2,0,'no');a.move(19,2);a.sw(19,16,R['source_bone'])
    for phase in (0,1):
        a.addiu(4,17,64);a.li(5,phase);a.move(6,19);a.move(7,0);a.call(A(0x1517A0))
    a.addiu(4,16,HEADER);a.addiu(5,17,64);a.call(A(0x1512C8))
    a.move(4,16);a.call(GEOMETRY);a.branch(4,2,0,'no')
    publish_parent_geometry(a,16,17,'fire_native_origin')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();result=a.finish()
    assert FIRE_BIND+len(result)<=CHARGE_END;return result


def stop_code(special=False):
    """Request native teardown of only our two nodes; return nodes still live.

    There is no spin loop and no descriptor free. Native update/destructor must
    retire both nodes before private descriptor storage may be reused.
    """
    a=Assembler(STOP);tag.save(a);a.li(16,ROWS);a.move(17,0);a.move(18,0)
    a.label('slot');a.move(4,16);a.call(OWNED);a.branch(4,2,0,'retired')
    # Native16A400 keeps the beam children drawable between requesting stop
    # and retiring the node. FINISH calls STOP without UPDATE during this
    # interval, so invalidate their per-frame upload references here too.
    # Otherwise an explosion's later GS uploads can replace those cached
    # textures while the last beam frame still uses the old references.
    a.addiu(4,16,DESC);a.call(A(0x14D460))
    a.lw(4,16,R['node']);a.call(TERMINATE)
    # The native explicit cleanup callback ends only children referenced by
    # this authenticated beam. Normal expiry can leave independently pooled
    # sprites alive after their parent, when no private descriptor update is
    # left to refresh their texture addresses. Keep the stock explosion and
    # every other actor's effect pools entirely outside this cleanup.
    a.lw(4,16,R['node']);a.call(HARD_RETIRE)
    a.li(8,1);a.sw(8,16,R['stopping'])
    a.addiu(18,18,1);a.jump('next')
    a.label('retired');a.sw(0,16,R['node']);a.sw(0,16,R['body']);a.sw(0,16,R['stopping']);a.sw(0,16,R['ticks'])
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(17,17,1);a.li(8,2);a.branch(5,17,8,'slot')
    if special:
        # The native Special Beam Cannon object retires through its own end
        # event and destructor; count it until that destructor has run.
        import tag_rush_special_beam as sbc
        a.call(sbc.NATIVE_STOP);a.r(0x21,18,18,2)
    a.move(2,18);tag.restore(a,2);a.jr();return a.finish()


def update_code():
    """Follow rendered bones; invalid identity/timeout stops that emitter."""
    a=Assembler(UPDATE);tag.save(a)
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    gate(a,'stop_all');a.li(16,ROWS);a.move(17,0)
    a.label('slot');a.move(4,16);a.call(OWNED);a.branch(4,2,0,'retired');a.move(18,2)
    # Native descriptor parents reset these upload-cache masks every update.
    # Ours is private, so it must not reuse last frame's dynamic GS references.
    a.addiu(4,16,DESC);a.call(A(0x14D460))
    a.lw(8,16,R['stopping']);a.branch(5,8,0,'next')
    a.lw(8,16,R['ticks']);a.branch(4,8,0,'stop');a.addiu(8,8,-1);a.sw(8,16,R['ticks'])
    a.move(4,16);a.call(GEOMETRY);a.branch(4,2,0,'stop')
    publish_parent_geometry(a,16,18,'update_native_origin')
    a.jump('next')
    a.label('stop');a.lw(4,16,R['node']);a.call(TERMINATE);a.li(8,1);a.sw(8,16,R['stopping']);a.jump('next')
    a.label('retired');a.sw(0,16,R['node']);a.sw(0,16,R['body']);a.sw(0,16,R['stopping']);a.sw(0,16,R['ticks'])
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(17,17,1);a.li(8,2);a.branch(5,17,8,'slot');a.jump('done')
    a.label('stop_all');a.call(STOP)
    a.label('done');tag.restore(a);a.jr();return a.finish()


def init_code(beam=None):
    """Parse the reviewed donor under two bounded private bump arenas.

    Only the known 1/6/0/1 shape recipe is emitted. Its four shape arrays need
    2176 raw bytes per descriptor, well below each 8192-byte private arena.
    Original allocator rows/selector and model parameters are restored before
    any error is reported. The arena receipt is never a live-appearance claim.
    """
    if beam is None:
        a=Assembler(INIT);a.move(2,0);a.jr();return a.finish()
    if not beam.get('reviewed') or tuple(beam.get('descriptor_counts',()))!=(1,6,0,1) or beam.get('descriptor_raw_bytes')!=2176:
        raise ValueError('Native tag-beam descriptor has not been reviewed')
    resource,metadata=beam['resource_address'],beam['metadata_address']
    import tag_rush_assets as assets
    for p,size in ((resource,107456),(metadata,640)):
        if type(p) is not int or p%16 or not assets.BASE<=p<p+size<=assets.END:
            raise ValueError('Native tag-beam resources escaped the asset reservation')
    a=Assembler(INIT);tag.save(a);core.gate(a,'no');a.li(16,CONTROL)
    a.lw(8,16,C['init_status']);a.branch(5,8,0,'no')
    for index in range(2):
        a.li(8,ROWS+index*STRIDE);a.lw(8,8,R['node']);a.branch(5,8,0,'no')
    a.li(8,core.POINTERS);a.lw(21,8);full.pointer(a,21,0x1600,'no')
    a.lw(8,21);a.branch(5,8,0,'no')
    a.lw(20,21,12);a.i(11,8,20,12);a.branch(4,8,0,'no')
    a.r(0,8,0,20,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(21,8);full.pointer(a,21,0x1700,'no')
    a.lw(8,21,16);a.branch(5,8,20,'no')
    for offset in (4,8):a.lw(8,21,offset);a.li(9,1);a.branch(5,8,9,'no')
    a.lw(17,28,-22416);full.pointer(a,17,156,'no')
    a.lw(8,17,152);a.li(9,0x3FE);a.branch(5,8,9,'no')
    a.lw(22,28,NATIVE_POOL_OFFSET);full.pointer(a,22,24,'no')
    a.li(8,1);a.sw(8,16,C['init_status']);a.sw(0,16,C['ready'])
    a.li(8,MAGIC);a.sw(8,16,C['magic']);a.lw(8,28,-22364);a.sw(8,16,C['manager'])
    a.li(8,core.MODE);a.lw(8,8,4);a.sw(8,16,C['count']);a.sw(22,16,C['pool'])
    for off in (80,84,88,92,148):a.lw(8,17,off);a.sw(8,29,0x340+off-80 if off<148 else 0x350)
    a.lw(8,21,2348);a.sw(8,29,0x354)
    a.move(18,0);a.li(19,ROWS)
    a.label('descriptor')
    a.addiu(4,19,HEADER);a.move(5,0);a.li(6,0x720);a.call(A(0x2A9ACC))
    a.sw(20,19,HEADER);a.li(8,2);a.sw(8,19,HEADER+4);a.sw(20,19,HEADER+32)
    a.li(8,resource);a.sw(8,19,HEADER+28);a.addiu(8,19,META);a.sw(8,19,HEADER+36)
    a.li(8,metadata);a.sw(8,21,2348)
    a.move(4,20);a.li(5,2);a.addiu(6,19,META);a.move(7,0);a.call(A(0x14B108))
    a.lw(8,29,0x354);a.sw(8,21,2348)
    a.r(0,8,0,18,13);a.li(9,ARENAS);a.r(0x21,8,8,9)
    a.sw(8,17,80);a.sw(8,17,84);a.li(8,ARENA_SIZE);a.sw(8,17,88);a.sw(0,17,92)
    a.li(8,5);a.sw(8,17,148)
    a.addiu(4,19,HEADER);a.addiu(5,19,DESC);a.move(6,0);a.li(7,resource);a.move(8,0);a.li(9,4);a.call(A(0x14CEB0))
    a.lw(22,17,92)
    for off in (80,84,88,92,148):a.lw(8,29,0x340+off-80 if off<148 else 0x350);a.sw(8,17,off)
    a.li(8,ARENA_SIZE);a.r(0x2B,8,8,22);a.branch(5,8,0,'failed')
    a.lw(8,19,DESC+796);a.addiu(9,19,HEADER);a.branch(5,8,9,'failed')
    for group,count in enumerate((1,6,0,1)):
        a.lw(8,19,DESC+780+4*group);a.li(9,count);a.branch(5,8,9,'failed')
        if count:
            # Every parsed array must lie wholly in this descriptor's arena.
            # This also catches allocation failure before any emitter uses it.
            length=(520,1584,0,72)[group]
            a.lw(10,19,DESC+764+4*group);a.r(0,8,0,18,13);a.li(9,ARENAS);a.r(0x21,8,8,9)
            a.r(0x2B,9,10,8);a.branch(5,9,0,'failed');a.addiu(8,8,ARENA_SIZE-length)
            a.r(0x2B,9,8,10);a.branch(5,9,0,'failed');a.i(12,8,10,15);a.branch(5,8,0,'failed')
    if beam.get('color_plan'):
        import tag_rush_colors as colors
        a.move(4,19);a.call(colors.INIT);a.branch(4,2,0,'failed')
    a.li(8,31);a.sw(8,19,R['source_bone']);a.li(8,PREPARED);a.sw(8,19,R['prepared'])
    a.addiu(19,19,STRIDE);a.addiu(18,18,1);a.li(8,2);a.branch(5,18,8,'descriptor')
    if beam.get('special_beam'):
        import tag_rush_special_beam as sbc
        a.call(sbc.INIT);a.branch(4,2,0,'failed')
    a.li(8,2);a.sw(8,16,C['init_status']);a.li(2,1);a.sw(2,16,C['ready']);a.jump('done')
    a.label('failed');a.li(8,100);a.sw(8,16,C['init_status'])
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();return a.finish()


def impact_code(explosion=False):
    """a0 captured role0..2,a1 encoded native bone -> visual success.

    Ordinary contacts use1D3170's type16 impact through187B00. The beam ending
    starts one scoped soft white finish. Ordinary contacts still copy their
    request into the bounded native pool, which owns their cleanup.
    No hitstop, attack events, damage or target writes are added here.
    """
    if explosion:return white_start_code()
    import tag_rush_camera as camera
    import tag_rush_scene as scene
    entry=EXPLOSION if explosion else IMPACT
    a=Assembler(entry);tag.save(a);a.move(16,4);a.move(17,5)
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'no')
    camera.emit_active(a,'no');a.i(11,9,16,3);a.branch(4,9,0,'no')
    a.i(11,9,17,32);a.branch(4,9,0,'no')
    a.li(8,scene.STATE);a.lw(9,8);a.li(10,scene.SCENE_MAGIC);a.branch(5,9,10,'no')
    a.lw(9,8,scene.S['retiring']);a.branch(5,9,0,'no')
    a.label('impact_actor');a.r(0,8,0,16,9);a.li(9,scene.ROWS);a.r(0x21,21,8,9)
    a.lw(10,21,scene.R['index']);a.li(8,tag.CONTROL);a.lw(9,8,tag.C['count'])
    a.r(0x2B,9,10,9);a.branch(4,9,0,'no')
    a.lw(10,21,scene.R['model_id']);a.i(11,9,10,12);a.branch(4,9,0,'no')
    scene.identity(a,21,'no','impact');a.lw(9,23,8);a.li(10,1);a.branch(5,9,10,'no')
    a.r(0,8,0,17,2);a.r(0x21,8,23,8);a.lw(10,8,3436)
    # Some valid tail-less outfits omit the complete4..7 dummy branch.
    # The native opening's first spark names lead bone5. If that exact
    # branch is absent, place this cosmetic contact at the captured
    # victim's torso instead; every present native bone keeps its cue.
    # Re-enter full identity/loaded checks for the victim before reading.
    a.branch(5,10,0,'impact_bone');a.branch(5,16,0,'no')
    a.li(8,5);a.branch(5,17,8,'no');a.li(8,scene.STATE)
    a.lw(9,8,scene.S['phase']);a.branch(5,9,0,'no')
    for bone in (4,5,6,7):
        a.lw(9,23,3436+4*bone);a.branch(5,9,0,'no')
    a.li(16,2);a.li(17,17);a.jump('impact_actor')
    a.label('impact_bone')
    full.pointer(a,10,80,'no')
    finite(a,10,(64,68,72),'no');finite(a,23,(2404,),'no')
    # The ordinary battle initializes these14 descriptors and its30-node pool.
    # No new resource load or allocator switch occurs in the middle of a hit.
    a.lw(18,28,-22512);full.pointer(a,18,24,'no')
    a.lw(10,18,12);full.pointer(a,10,64,'no');a.lw(9,10,32);a.branch(5,9,18,'no')
    a.lw(19,28,-22516);full.pointer(a,19,11208,'no')
    descriptor=4008
    for off in (descriptor,descriptor+8):a.lw(10,19,off);full.pointer(a,10,64,'no')
    a.lw(4,23,16);a.move(5,17);a.addiu(6,29,0x300);a.call(BONE)
    finite(a,29,(0x300,0x304,0x308),'no')
    a.li(8,0x3F800000);a.sw(8,29,0x30C)
    a.i(49,12,23,2404);a.call(A(0x11F588));a.i(57,0,29,0x310)
    a.i(49,12,23,2404);a.call(A(0x11F620));a.i(57,0,29,0x318)
    a.sw(0,29,0x314);a.sw(0,29,0x31C);a.li(8,16);a.sw(8,29,0x320)
    a.lw(8,23,16);a.sw(8,29,0x324);a.sw(0,29,0x328);a.sw(0,29,0x32C)
    a.addiu(4,29,0x300);a.call(NATIVE_IMPACT)
    a.jump('done')
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();data=a.finish()
    assert entry+len(data)<=(CONTROL if explosion else EXPLOSION);return data


def pieces(beam=None):
    plan=beam.get('color_plan') if beam else None
    special=bool(beam and beam.get('special_beam'))
    result=[(SPAWN,spawn_code(bool(plan),special=special)),(UPDATE,update_code()),(STOP,stop_code(special)),
            (OWNED,owned_code()),(GEOMETRY,geometry_code()),(SELECT_SOURCE,select_source_code()),(IGNITE,ignite_code(special=special)),(INIT,init_code(beam)),(IMPACT,impact_code()),
            (EXPLOSION,white_start_code()),(WHITE_DRAW,white_draw_code()),(WHITE_ALPHA,white_alphas()),(CONTROL,bytes(END-CONTROL)),
            (CHARGE_SPAWN,spawn_code(bool(plan),charging=True,special=special)),(CHARGE,ignite_code(charging=True)),
            (FIRE_BIND,fire_bind_code())]
    if plan:
        import tag_rush_colors as colors
        result.extend(colors.pieces(plan))
    if special:
        import tag_rush_special_beam as sbc
        result.extend(sbc.pieces(beam['special_beam']))
    spans=sorted((p,p+len(b)) for p,b in result)
    assert all(end<=p for (_,end),(p,_) in zip(spans,spans[1:]))
    return result


def installation(beam=None,*args,**kwargs):
    import tag_rush_colors as colors
    mutable=[(CONTROL,END)]
    if beam and beam.get('color_plan'):mutable.append((colors.STORAGE,colors.STORAGE_END))
    if beam and beam.get('special_beam'):
        import tag_rush_special_beam as sbc
        mutable.extend(sbc.mutable_ranges(beam['special_beam']))
    return dict(usable=False,blocks=pieces(beam),mutable_ranges=mutable,limitations=[
        'Private native beam descriptors use a reviewed bounded allocator; live initialization still needs to be checked.',
        'Beam origin, endpoint, firing phase, visibility in each view, and native cleanup need a live match check.'])
