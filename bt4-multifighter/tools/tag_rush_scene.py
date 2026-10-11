"""Three-actor tag choreography; borrowed poses never dispatch attacks.

The coordinator owns consent/meters; the asset builder owns reviewed clips and
retarget bind data. Supported offline matches enable this director after
native preparation; online matches leave it unarmed. Reviewed disc camera samples retain
the original shot cuts while a private camera keeps unrelated views separate.
"""
import math
import struct
from native_map import A, ACTOR_HZ
from prototype import Assembler
import fresh_team_combat as core
import fusion_partner_lifecycle as full
import extra_throws as actors
import beam_struggle as fp
import tag_team_rush as tag
import tag_rush_assets as assets
import tag_rush_camera as camera
import tag_rush_safety as safety
import tag_rush_effects as effects
import tag_rush_audio as audio
import tag_rush_shots as shots
import tag_rush_staging as staging
import tag_rush_choreography as choreography
import tag_rush_native_pose as native_pose
import tag_rush_recovery as fall_recovery
import tag_rush_damage as damage_schedule

START, STEP, FINISH = tag.START, tag.STEP, tag.FINISH
START_BODY,STEP_BODY,BODIES_END=0x06D89800,0x06D8B800,0x06D8D800
FX_BODY,FX_BODY_END=0x06D8D800,0x06D8E800
FINISH_BODY,FINISH_BODY_END=0x06D91000,0x06D93000
ANCHOR = STEP+0xA40  # Internal START helper, sharing its private stack scratch.
ALIGN = FINISH+0xC00  # Scoped native paired-body alignment, never a global scan.
FX_STEP = FINISH+0xAC0
RECOVERY, RECOVERY_END = 0x06D0D800, 0x06D0E000
CONTROL, STATE = tag.CONTROL, tag.MEMBERS_SAVE
TABLE, STAGING, ADMISSION = CONTROL+0x80, CONTROL+0xA0, CONTROL+0x3A0
ROWS, STRIDE, END = STATE+0x100, 0x200, CONTROL+0x1000
SCENE_MAGIC = 0x54534331
# State: signature, phase, local ticks, descriptor base/count/current pointer,
# entered phase, cancellation, common XYZW/orientation, camera focus, clock.
S = dict(magic=0, phase=4, ticks=8, base=12, count=16, descriptor=20,
         entered=24, cancelled=28, origin=32, rotation=48, focus=64,
         radius=80, total_ticks=84, saved_camera=88, saved_renderer=92,
         saved_binding=96, staging=100, uniform_scale=104, height_scale=108,
         phase_origin=112, phase_rotation=128, retiring=144, fx_started=148,
         retirement_ticks=152, cleanup_pending=156, placement=160, exploded=164)
RETIREMENT_LIMIT = 2*ACTOR_HZ
# Keep the authored phase roots inside the arena. Native cinematic poses may
# extend beyond gameplay limits; reserving a guessed full-body envelope here
# made ordinary Wasteland's ceiling incompatible with its actual ground.
ANCHOR_ROOT_UP = 40.0 - min(row[1] for row in assets.NATIVE_STAGING)
# Preserve identities and original pose before leaving the current action. An
# interrupted attack is never restarted at cleanup: finish uses a fresh idle.
R = dict(index=0, actor=4, model=8, character=12, model_id=16, skeleton=20,
         clip0=24, animation=28, speed=32, action=36, original=48,
         rotation=64, bookkeeping=80, clocks=144, borrowed=176,
         loaded_clip=180, idle_animation=184, end=192, bone_offset=208,
         recovering=224, recovery_anchor=240)


def finite(a, base, offsets, fail):
    for off in offsets:
        a.lw(8,base,off);a.li(9,0x7F800000);a.r(0x24,8,8,9)
        a.branch(4,8,9,fail)


def identity(a,row,fail,tagname):
    """Validate the exact captured actor/model before any stale writes."""
    a.lw(22,row,R['actor']);a.lw(23,row,R['model'])
    full.pointer(a,22,0x1600,fail);full.pointer(a,23,0x1700,fail)
    a.lw(10,row,R['index']);a.lw(8,22);a.branch(5,8,10,fail)
    a.r(0,8,0,10,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(8,8)
    a.branch(5,8,22,fail);a.lw(10,row,R['model_id']);a.lw(8,22,12)
    a.branch(5,8,10,fail);a.r(0,8,0,10,2);a.li(9,core.MODELS)
    a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,23,fail)
    for live,saved in ((12,R['character']),(16,R['model_id']),(64,R['skeleton'])):
        a.lw(8,23,live);a.lw(9,row,saved);a.branch(5,8,9,fail)
    a.lw(8,23,4);a.li(9,1);a.branch(5,8,9,fail)


def copy_words(a,source,sourceoff,dest,destoff,size):
    for off in range(0,size,4):a.lw(8,source,sourceoff+off);a.sw(8,dest,destoff+off)


def native_idle(a,actor):
    a.move(4,actor);a.li(5,11);a.call(A(0x1E0290))
    a.move(4,actor);a.call(A(0x1E23D0))


def common_anchor(a, victim, destination, fail):
    """One bounded stage anchor; native bone contact places the victim later."""
    import arena_bounds
    a.r(0,8,0,victim,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(22,8)
    actors.model(a,22,23,fail)
    copy_words(a,23,2384,29,destination,16)
    a.li(8,arena_bounds.STAGE);a.lw(12,8);full.pointer(a,12,68,fail)
    a.lw(12,12,64);full.pointer(a,12,12,fail);finite(a,12,(0,4,8),fail)
    # Extents use the live retarget height ratio and the currently applied
    # uniform scale, including canonical giants' temporary root-matrix scale.
    a.i(49,0,12,0);fp.fconst(a,1,250.0);a.i(49,2,29,0x350)
    fp.fop(a,2,1,1,2);fp.fop(a,1,0,0,1)
    fp.fconst(a,1,20.0);fp.fop(a,0x34,0,0,1);a.branch(17,8,1,fail)
    a.i(49,2,29,destination);a.i(49,3,29,destination+8)
    fp.fop(a,2,4,2,2);fp.fop(a,2,5,3,3);fp.fop(a,0,4,4,5);fp.fop(a,2,5,0,0)
    fp.fop(a,0x36,0,4,5);a.branch(17,8,1,'anchor_radial')
    fp.fop(a,4,4,4,4);fp.fop(a,3,0,0,4);fp.fop(a,2,2,2,0);fp.fop(a,2,3,3,0)
    a.i(57,2,29,destination);a.i(57,3,29,destination+8)
    a.label('anchor_radial');a.i(49,0,12,4);fp.fconst(a,1,ANCHOR_ROOT_UP)
    a.i(49,4,29,0x354);fp.fop(a,2,1,1,4);fp.fop(a,0,0,0,1);a.i(57,0,29,0x358)
    a.i(49,2,12,8);fp.fconst(a,1,40.0);fp.fop(a,2,1,1,4);fp.fop(a,1,2,2,1)
    fp.fop(a,0x34,0,0,2);a.branch(17,8,0,fail)
    a.i(49,3,29,destination+4);fp.fop(a,1,3,3,1)
    fp.fop(a,0x34,0,3,0);a.branch(17,8,0,'anchor_ceiling');fp.fop(a,6,3,0)
    a.label('anchor_ceiling');fp.fop(a,0x34,0,2,3);a.branch(17,8,0,'anchor_floor');fp.fop(a,6,3,2)
    a.label('anchor_floor');a.i(57,3,29,destination+4)
    a.addiu(4,29,destination);a.call(safety.FLOOR)
    a.branch(4,2,0,'anchor_ready');a.i(49,0,29,destination+12)
    fp.fconst(a,1,40.0);a.i(49,2,29,0x354);fp.fop(a,2,1,1,2)
    fp.fop(a,1,0,0,1);a.i(57,0,29,destination+4)
    a.i(49,1,29,0x358);fp.fop(a,0x34,0,0,1);a.branch(17,8,1,fail)
    a.label('anchor_ready');a.li(8,0x3F800000);a.sw(8,29,destination+12)


def anchor_code():
    """Internal START continuation: reviewed live dimensions, one safe origin.

    Uses START's saved inputs at sp+0x300 and selected descriptor in s5.
    s4/ra survive; the helper never mutates an actor/model or giant settings.
    """
    import giant_options as giants
    a=Assembler(ANCHOR);a.sw(31,29,0x334);a.sw(20,29,0x338)
    fp.fconst(a,0,1.0);a.i(57,0,29,0x350);a.i(57,0,29,0x354);a.move(20,0)
    a.label('dimensions');a.r(0,8,0,20,2);a.addiu(9,29,0x300);a.r(0x21,8,8,9);a.lw(10,8)
    a.r(0,8,0,10,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(22,8)
    actors.model(a,22,23,'no');a.lw(10,23,2332);full.pointer(a,10,12,'no')
    finite(a,23,(2592,),'no');finite(a,10,(4,),'no')
    a.i(49,0,23,2592);a.i(49,2,10,4);fp.fconst(a,1,0.0)
    fp.fop(a,0x34,0,1,0);a.branch(17,8,0,'no');fp.fop(a,0x34,0,1,2);a.branch(17,8,0,'no')
    # giant_options.model_code's exact admission: native size class4, matching
    # manager/count, option enabled. Reading +2592 alone misses its multiplier,
    # which SCALE applies temporarily and restores after each matrix rebuild.
    a.i(36,8,10,2);a.li(9,4);a.branch(5,8,9,'native_scale')
    a.li(11,giants.CONTROL);a.lw(8,11);a.li(9,giants.MAGIC);a.branch(5,8,9,'native_scale')
    a.lw(8,11,4);a.lw(9,19,4);a.branch(5,8,9,'native_scale')
    a.lw(8,11,8);a.lw(9,19,8);a.branch(5,8,9,'native_scale')
    a.lw(8,11,12);a.branch(4,8,0,'native_scale');finite(a,11,(16,),'no')
    a.i(49,3,11,16);fp.fop(a,0x34,0,1,3);a.branch(17,8,0,'no');fp.fop(a,2,0,0,3)
    a.label('native_scale');a.lw(10,21,60);a.r(0,8,0,20,2);a.r(0x21,10,10,8)
    a.lw(10,10);a.lw(10,10,2332);full.pointer(a,10,8,'no');finite(a,10,(4,),'no')
    a.i(49,3,10,4);fp.fop(a,0x34,0,1,3);a.branch(17,8,0,'no')
    fp.fop(a,3,2,2,3);fp.fop(a,2,2,2,0)
    fp.fconst(a,3,64.0)
    for value in (0,2):fp.fop(a,0x34,0,3,value);a.branch(17,8,1,'no')
    a.i(49,1,29,0x350);fp.fop(a,0x34,0,1,0);a.branch(17,8,0,'scale_kept');a.i(57,0,29,0x350)
    a.label('scale_kept');a.i(49,1,29,0x354);fp.fop(a,0x34,0,1,2);a.branch(17,8,0,'height_kept');a.i(57,2,29,0x354)
    a.label('height_kept');a.addiu(20,20,1);a.li(8,3);a.branch(5,20,8,'dimensions')
    common_anchor(a,18,0x340,'no');finite(a,29,(0x340,0x344,0x348),'no')
    a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done');a.lw(20,29,0x338);a.lw(31,29,0x334);a.jr()
    data=a.finish();assert len(data)<=FINISH-ANCHOR,len(data);return data


def start_code():
    """a0 requester/a1 partner/a2 victim physical indices -> v0 accepted.

    All resource, identity and queued-contact checks run before actor writes.
    ADMISSION is {byte_flags_pointer, character_count}. The disc-derived flags
    apply to the current model character, so a transformed form is checked anew.
    """
    a=Assembler(START_BODY);tag.save(a);a.move(16,4);a.move(17,5);a.move(18,6)
    a.call(tag.GATE);a.branch(4,2,0,'reject');a.li(19,CONTROL)
    a.lw(8,19,tag.C['active']);a.branch(5,8,0,'reject')
    for x,y in ((16,17),(16,18),(17,18)):a.branch(4,x,y,'reject')
    a.r(0x26,8,16,17);a.i(12,8,8,1);a.branch(5,8,0,'reject')
    a.r(0x26,8,16,18);a.i(12,8,8,1);a.branch(4,8,0,'reject')
    for k,reg in enumerate((16,17,18)):a.sw(reg,29,0x300+4*k)
    a.move(20,0);a.sw(0,29,0x30C)
    a.label('preflight')
    a.r(0,8,0,20,2);a.addiu(9,29,0x300);a.r(0x21,8,8,9);a.lw(21,8)
    a.lw(9,19,8);a.r(0x2B,8,21,9);a.branch(4,8,0,'reject')
    a.r(0,8,0,21,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(22,8)
    a.move(4,22);a.call(safety.PREFLIGHT);a.branch(4,2,0,'reject')
    actors.model(a,22,23,'reject')
    a.li(25,ADMISSION);a.lw(10,25);full.pointer(a,10,4096,'reject')
    a.lw(8,23,12);a.lw(9,25,4);a.addiu(11,9,-1);a.i(11,11,11,4096)
    a.branch(4,11,0,'reject');a.r(0x2B,9,8,9);a.branch(4,9,0,'reject')
    a.r(0x21,10,10,8);a.i(36,8,10,0);a.i(12,9,8,1);a.branch(4,9,0,'reject')
    a.i(11,9,20,2);a.branch(4,9,0,'not_attacker')
    a.i(12,8,8,2);a.r(2,8,0,8,1);a.r(4,8,20,8)
    a.lw(24,29,0x30C);a.r(0x25,24,24,8);a.sw(24,29,0x30C)
    a.label('not_attacker')
    # Decoder scratch, placement/framing bones and both reviewed beam hands.
    # Native opening/impact cues use31; custom one-hand finishers use45.
    a.lw(10,23,5728);full.pointer(a,10,98348,'reject')
    a.lw(10,23,192);full.pointer(a,10,8,'reject')
    for bone in (2,3,17,31,45,52):
        a.lw(10,23,3436+4*bone);full.pointer(a,10,80,'reject')
        finite(a,10,(64,68,72),'reject')
    # New custom packs use the fighter's actual native clash pose. Refuse a
    # missing own clip before the approach can enter cinematic ownership.
    a.li(10,CONTROL);a.lw(10,10,staging.TABLE_OFFSET);a.branch(4,10,0,'own_pose_checked')
    a.i(11,9,20,2);a.branch(4,9,0,'own_pose_checked')
    a.lw(10,25);a.lw(8,23,12);a.r(0x21,10,10,8);a.i(36,8,10,0)
    a.i(12,8,8,2);a.branch(4,8,0,'own_pose_checked')
    a.move(4,23);a.call(native_pose.SELECT);a.branch(1,2,0,'reject')
    a.label('own_pose_checked')
    finite(a,23,(2384,2388,2392,2400,2404,2408),'reject')
    a.addiu(20,20,1);a.li(8,3);a.branch(5,20,8,'preflight')
    # Ki bits 00->melee, 01->lead beam, 10->partner beam, 11->two beams.
    a.lw(24,29,0x30C);a.li(20,1);a.branch(4,24,0,'variant');a.li(20,0);a.li(8,3)
    a.branch(4,24,8,'variant');a.addiu(20,24,1);a.label('variant')
    a.lw(8,19,tag.C['scene_table']);a.li(9,TABLE);a.branch(5,8,9,'reject')
    a.r(0,9,0,20,3);a.r(0x21,8,8,9);a.lw(21,8);a.lw(25,8,4)
    a.addiu(9,25,-5);a.i(11,9,9,choreography.MAX_PHASES-4);a.branch(4,9,0,'reject');a.sw(25,29,0x318)
    a.li(8,assets.BASE);a.r(0x2B,9,21,8);a.branch(5,9,0,'reject')
    a.r(0,9,0,25,6);a.r(0x21,9,21,9);a.li(8,assets.END);a.r(0x2B,9,8,9);a.branch(5,9,0,'reject')
    # Every phase pointer/header is checked, not just the first phase.
    a.move(22,21);a.move(23,0)
    a.label('descriptor');a.lw(8,22);a.addiu(8,8,-1);a.i(11,9,8,3600);a.branch(4,9,0,'reject')
    a.lw(8,22,56);a.li(9,60);a.branch(5,8,9,'reject')
    a.lw(10,22,60);full.pointer(a,10,12,'reject')
    for k in range(3):
        a.lw(11,22,4+4*k)
        if k==1:a.branch(4,11,0,f'no_clip{k}')
        full.pointer(a,11,8,'reject');a.lw(8,11);a.i(11,9,8,148);a.branch(5,9,0,'reject')
        a.li(9,0xC000);a.r(0x2B,9,9,8);a.branch(5,9,0,'reject')
        a.lw(8,10,4*k);full.pointer(a,8,2400,'reject',temp=11,test=9)
        if k==1:a.label(f'no_clip{k}')
    a.addiu(22,22,64);a.addiu(23,23,1);a.branch(5,23,25,'descriptor')
    a.li(12,STAGING);a.lw(12,12);full.pointer(a,12,4*choreography.MAX_PHASES*16,'reject')
    a.li(22,0);a.li(10,TABLE)
    a.label('previous_staging');a.branch(4,22,20,'staging_base')
    a.lw(9,10,4);a.addiu(8,9,-5);a.i(11,8,8,choreography.MAX_PHASES-4);a.branch(4,8,0,'reject')
    a.r(0,9,0,9,4);a.r(0x21,12,12,9);a.addiu(10,10,8);a.addiu(22,22,1);a.jump('previous_staging')
    a.label('staging_base')
    a.sw(12,29,0x314);a.move(22,0)
    a.label('staging');finite(a,12,(0,4,8,12),'reject');a.addiu(12,12,16)
    a.addiu(22,22,1);a.lw(9,29,0x318);a.branch(5,22,9,'staging')
    # Prepared native descriptors must exist before consuming either meter.
    # Parsing occurs during setup under the private allocator, never here.
    a.li(12,effects.CONTROL)
    for off,value in ((0,effects.MAGIC),(12,1),(28,2)):
        a.lw(8,12,off);a.li(9,value);a.branch(5,8,9,'reject')
    for off in (4,8):a.lw(8,12,off);a.lw(9,19,off);a.branch(5,8,9,'reject')
    for role in (0,1):
        a.li(12,effects.ROWS+role*effects.STRIDE);a.lw(8,12,effects.R['prepared'])
        a.li(9,effects.PREPARED);a.branch(5,8,9,'reject')
    a.call(ANCHOR);a.branch(4,2,0,'reject')
    a.call(camera.INIT);a.branch(4,2,0,'reject')
    a.li(18,STATE);a.li(8,SCENE_MAGIC);a.sw(8,18,S['magic'])
    a.lw(8,29,0x314);a.sw(8,18,S['staging'])
    a.lw(8,29,0x350);a.sw(8,18,S['uniform_scale']);a.lw(8,29,0x354);a.sw(8,18,S['height_scale'])
    a.lw(8,28,-22176);a.sw(8,18,S['saved_camera'])
    a.lw(8,28,-22172);a.sw(8,18,S['saved_renderer']);a.lw(9,8,0xC40);a.sw(9,18,S['saved_binding'])
    for off in (S['phase'],S['ticks'],S['cancelled'],S['total_ticks'],S['retiring'],S['fx_started'],S['retirement_ticks'],S['cleanup_pending'],S['exploded']):a.sw(0,18,off)
    a.sw(21,18,S['base']);a.lw(8,29,0x318);a.sw(8,18,S['count']);a.sw(21,18,S['descriptor'])
    a.li(8,-1);a.sw(8,18,S['entered']);a.sw(20,19,tag.C['variant'])
    a.move(20,0);a.li(21,ROWS);a.move(24,0)
    a.label('capture');a.r(0,8,0,20,2);a.addiu(9,29,0x300);a.r(0x21,8,8,9);a.lw(10,8)
    a.sw(10,21,R['index']);a.li(8,1);a.r(4,8,10,8);a.r(0x25,24,24,8)
    a.r(0,8,0,10,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(22,8);a.sw(22,21,R['actor'])
    actors.model(a,22,23,'capture_error');a.sw(23,21,R['model'])
    for off,saved in ((12,R['character']),(16,R['model_id']),(64,R['skeleton']),(192,R['clip0']),(3200,R['speed'])):
        a.lw(8,23,off);a.sw(8,21,saved)
    a.lw(8,22,2420);a.sw(8,21,R['animation']);a.lw(8,22,2376);a.sw(8,21,R['action'])
    copy_words(a,23,2384,21,R['original'],16);copy_words(a,23,2400,21,R['rotation'],16)
    copy_words(a,22,2420,21,R['bookkeeping'],64);copy_words(a,23,3184,21,R['clocks'],28)
    a.sw(0,21,R['borrowed']);a.sw(0,21,R['loaded_clip']);a.sw(0,21,R['recovering'])
    for off in (native_pose.ACTIVE,native_pose.CLIP,native_pose.POINTER):a.sw(0,21,off)
    a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'capture')
    # Capture the entire cast before the first outgoing native action cleanup.
    # No rejected preflight can leave a partially interrupted group behind.
    a.sw(24,29,0x310);a.move(20,0);a.li(21,ROWS)
    a.label('cleanup');a.lw(22,21,R['actor']);a.lw(23,21,R['model'])
    native_idle(a,22)
    a.lw(8,22,2420);a.sw(8,21,R['idle_animation'])
    a.move(4,23);a.call(A(0x24C958));a.move(4,23);a.call(A(0x24E3F8))
    a.lw(10,23,3436+4*2)
    for off in range(0,12,4):
        a.i(49,0,10,64+off);a.i(49,1,23,2384+off);fp.fop(a,1,0,0,1);a.i(57,0,21,R['bone_offset']+off)
    a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'cleanup')
    copy_words(a,29,0x340,18,S['origin'],16)
    a.li(21,ROWS)
    copy_words(a,21,R['rotation'],18,S['rotation'],16)
    for k,off in enumerate((tag.C['initiator'],tag.C['partner'],tag.C['victim'])):
        a.lw(8,29,0x300+4*k);a.sw(8,19,off)
    a.lw(8,29,0x310);a.sw(8,19,tag.C['members']);a.sw(0,19,tag.C['frame'])
    a.li(8,safety.DAMAGE_DONE);a.sw(0,8);a.li(8,1);a.sw(8,19,tag.C['active'])
    a.lw(8,19,tag.C['start_requests']);a.addiu(8,8,1);a.sw(8,19,tag.C['start_requests'])
    # A successful request consumes offers, never other fighters' meters.
    a.li(21,tag.METERS);a.lw(22,19,8);a.li(8,-1)
    a.label('offers');a.sw(8,21,tag.T['inviter']);a.sw(0,21,tag.T['expiry'])
    a.addiu(21,21,tag.METER_STRIDE);a.addiu(22,22,-1);a.branch(5,22,0,'offers')
    a.call(audio.RESET);a.call(damage_schedule.RESET);a.call(STEP);a.li(2,1);a.jump('done')
    # This can only mean a synchronous native callback replaced a captured
    # model after all preflights. Never publish a partially captured scene.
    a.label('capture_error');a.sw(0,18,S['magic'])
    a.label('reject');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr()
    data=a.finish();assert START_BODY+len(data)<=STEP_BODY,len(data);return data


def step_code():
    a=Assembler(STEP_BODY);tag.save(a);a.li(16,CONTROL);a.li(17,STATE)
    a.lw(8,16,tag.C['active']);a.li(9,1);a.branch(5,8,9,'done')
    a.lw(8,17);a.li(9,SCENE_MAGIC);a.branch(5,8,9,'cancel')
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'stale')
    a.lw(8,17,S['retiring']);a.branch(4,8,0,'scene_live')
    a.lw(4,17,S['cancelled']);a.call(FINISH);a.jump('done');a.label('scene_live')
    a.li(21,ROWS);a.move(20,0)
    a.label('identities');identity(a,21,'cancel','step')
    actors.hp(a,22,'cancel');a.addiu(20,20,1);a.addiu(21,21,STRIDE)
    a.li(8,3);a.branch(5,20,8,'identities')
    a.lw(18,17,S['phase']);a.lw(8,17,S['count']);a.r(0x2B,9,18,8);a.branch(4,9,0,'finish')
    a.r(0,8,0,18,6);a.lw(19,17,S['base']);a.r(0x21,19,19,8);a.sw(19,17,S['descriptor'])
    a.lw(8,17,S['entered']);a.branch(4,8,18,'animate')
    a.sw(18,17,S['entered']);a.sw(0,17,S['ticks']);a.move(20,0);a.li(21,ROWS)
    a.move(4,18);a.call(staging.QUERY);a.sw(2,17,S['placement'])
    a.lw(8,19,28);a.i(12,8,8,assets.CUSTOM_FINISHER);a.branch(4,8,0,'placement_valid')
    a.branch(4,2,0,'cancel');a.label('placement_valid')
    a.branch(4,2,0,'settle_captured');a.call(staging.BEGIN);a.branch(4,2,0,'cancel');a.label('settle_captured')
    a.lw(10,17,S['staging']);a.r(0,8,0,18,4);a.r(0x21,10,10,8)
    copy_words(a,17,S['origin'],17,S['phase_origin'],16)
    copy_words(a,17,S['rotation'],17,S['phase_rotation'],16)
    for off in (0,4,8):
        a.i(49,0,10,off);a.i(49,1,17,S['height_scale'] if off==4 else S['uniform_scale'])
        fp.fop(a,2,0,0,1);a.i(49,1,17,S['origin']+off);fp.fop(a,0,0,0,1);a.i(57,0,17,S['phase_origin']+off)
    a.i(49,0,10,12);a.i(49,1,17,S['rotation']+4);fp.fop(a,0,0,0,1);a.i(57,0,17,S['phase_rotation']+4)
    a.label('phase');a.lw(22,21,R['actor']);a.lw(23,21,R['model'])
    a.r(0,8,0,20,2);a.r(0x21,24,19,8);a.lw(25,24,4);a.branch(4,25,0,'phase_next')
    a.sw(25,21,R['loaded_clip']);a.sw(25,23,192)
    a.move(4,22);a.addiu(5,17,S['phase_origin']);a.addiu(6,17,S['phase_rotation']);a.lw(7,23,2596)
    a.call(A(0x1D7418))
    a.lw(6,17,S['placement']);a.branch(4,6,0,'native_placement')
    a.move(4,20);a.move(5,21);a.move(7,17);a.call(staging.APPLY);a.branch(4,2,0,'cancel')
    a.label('native_placement')
    a.move(4,23);a.call(A(0x24E2B0))
    a.move(4,20);a.move(5,21);a.move(6,19);a.call(native_pose.ENTER)
    a.li(8,1);a.branch(4,2,8,'phase_next');a.branch(5,2,0,'cancel')
    # Suppress the recipient's automatic self-retarget exactly while decoding;
    # then adapt from the real donor bind pose once, without double scaling.
    a.lw(10,23,5728);a.li(9,98344);a.r(0x21,10,10,9);a.lw(8,10)
    a.sw(10,29,0x300);a.sw(8,29,0x304);a.sw(0,10)
    a.move(4,23);a.move(5,0);a.move(6,0);a.li(7,1);a.call(A(0x24D038))
    a.lw(10,29,0x300);a.lw(8,29,0x304);a.sw(8,10)
    a.lw(4,23,2880);a.move(5,23);a.lw(8,19,60);a.r(0,9,0,20,2)
    a.r(0x21,8,8,9);a.lw(6,8);a.move(7,0);a.move(8,0);a.call(A(0x24BBE8))
    # 24D038 decodes the new clip but does not reset the former animation's
    # blend clocks. Our authored clock bypasses their native decay; retaining
    # them would blend cached idle into every cinematic pose indefinitely.
    # The separate recovery helper deliberately starts its own moving blend.
    for off in (3204,3208,3212):a.sw(0,23,off)
    a.sw(0,22,2420);a.sw(0,23,3200);a.li(8,1);a.sw(8,21,R['borrowed'])
    a.label('phase_next');a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'phase')
    a.label('animate');a.move(20,0);a.li(21,ROWS)
    a.lw(8,17,S['ticks']);a.addiu(8,8,1);a.sw(8,17,S['ticks'])
    a.emit((17<<26)|(4<<21)|(8<<16)|(20<<11));a.emit((17<<26)|(20<<21)|(20<<11)|(20<<6)|32)
    fp.fconst(a,21,60.0/ACTOR_HZ);fp.fop(a,2,20,20,21)
    a.label('pose');a.lw(22,21,R['actor']);a.lw(23,21,R['model'])
    a.move(4,20);a.move(5,21);a.call(native_pose.TICK)
    a.li(8,1);a.branch(4,2,8,'pose_next');a.branch(5,2,0,'cancel')
    a.lw(8,19,28);a.i(12,8,8,assets.CUSTOM_FINISHER);a.branch(5,8,0,'authored_pose')
    a.move(4,20);a.move(5,21);a.call(RECOVERY)
    a.li(8,1);a.branch(4,2,8,'pose_next');a.branch(5,2,0,'cancel')
    a.label('authored_pose')
    a.r(0,8,0,20,2);a.r(0x21,24,19,8);a.lw(8,24,4);a.branch(4,8,0,'pose_next')
    a.lw(8,24,44);a.emit((17<<26)|(4<<21)|(8<<16)|(1<<11))
    a.emit((17<<26)|(20<<21)|(1<<11)|(1<<6)|32);fp.fop(a,6,0,20)
    fp.fop(a,0x34,0,1,0);a.branch(17,8,0,'frame_ok');fp.fop(a,6,0,1)
    a.label('frame_ok');a.i(49,1,23,3192);a.i(57,1,23,3196);a.i(57,0,23,3192)
    a.sw(0,23,3200)
    a.move(4,23);a.call(A(0x24C958));a.move(4,23);a.call(A(0x24E2B0));a.move(4,23);a.call(A(0x24E3F8))
    a.label('pose_next');a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'pose')
    a.lw(8,19,28);a.i(12,8,8,assets.CUSTOM_FINISHER);a.branch(5,8,0,'aligned')
    a.call(ALIGN);a.branch(4,2,0,'cancel');a.jump('placement_finished')
    a.label('aligned');a.call(staging.TICK);a.branch(4,2,0,'cancel');a.label('placement_finished')
    a.call(FX_STEP);a.branch(4,2,0,'cancel')
    a.call(audio.TICK)
    a.call(damage_schedule.TICK);a.branch(4,2,0,'cancel')
    # Disc-authored shots use the real lead root and the same phase clock as
    # the borrowed poses. The fallback remains for incomplete research packs.
    a.lw(4,17,S['phase']);a.lw(5,17,S['ticks']);a.li(8,ROWS)
    a.lw(6,8,R['model']);a.addiu(7,17,S['uniform_scale'])
    a.move(8,19);a.li(9,ROWS+STRIDE);a.lw(9,9,R['model']);a.call(shots.UPDATE)
    a.branch(5,2,0,'camera_ready')
    # Framing uses posed torso world positions, not static actor roots. Keep
    # the waiting ally out of the first two phases' framing calculation.
    a.li(21,ROWS);a.move(20,0);a.move(24,0)
    for off in (64,68,72):a.sw(0,17,off)
    a.label('focus');a.r(0,8,0,20,2);a.r(0x21,9,19,8);a.lw(8,9,4);a.branch(4,8,0,'focus_next')
    a.lw(23,21,R['model']);a.lw(10,23,3436+4*17);full.pointer(a,10,80,'cancel')
    finite(a,10,(64,68,72),'cancel')
    for off in range(0,12,4):
        a.i(49,0,10,64+off);a.i(49,1,17,S['focus']+off);fp.fop(a,0,0,0,1);a.i(57,0,17,S['focus']+off)
    a.addiu(24,24,1);a.label('focus_next');a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'focus')
    a.emit((17<<26)|(4<<21)|(24<<16)|(1<<11));a.emit((17<<26)|(20<<21)|(1<<11)|(1<<6)|32)
    for off in range(0,12,4):a.i(49,0,17,S['focus']+off);fp.fop(a,3,0,0,1);a.i(57,0,17,S['focus']+off)
    a.li(21,ROWS);a.move(20,0);fp.fconst(a,4,0.0)
    a.label('radius');a.r(0,8,0,20,2);a.r(0x21,9,19,8);a.lw(8,9,4);a.branch(4,8,0,'radius_next')
    a.lw(23,21,R['model']);a.lw(10,23,3436+4*17);fp.fconst(a,3,0.0)
    for off in range(0,12,4):
        a.i(49,0,10,64+off);a.i(49,1,17,S['focus']+off);fp.fop(a,1,0,0,1);fp.fop(a,2,0,0,0);fp.fop(a,0,3,3,0)
    fp.fop(a,0x34,0,4,3);a.branch(17,8,0,'radius_next');fp.fop(a,6,4,3)
    a.label('radius_next');a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'radius')
    fp.fop(a,4,4,4,4);fp.fconst(a,1,65.0);fp.fop(a,0,4,4,1)
    a.li(23,camera.CAMERA)
    for off,mult in ((0,1.95),(4,-1.05),(8,2.55)):
        fp.fconst(a,1,mult);fp.fop(a,2,0,4,1);a.i(49,1,17,S['focus']+off);fp.fop(a,0,0,0,1);a.i(57,0,23,720+off)
    for off,value in ((732,1.0),(736,-math.atan2(.35,math.hypot(.65,.85))),(740,math.atan2(-.65,-.85)),(744,0.0),(748,1.0)):
        a.li(8,struct.unpack('<I',struct.pack('<f',value))[0]);a.sw(8,23,off)
    a.call(camera.UPDATE)
    a.label('camera_ready')
    a.lw(8,17,S['total_ticks']);a.addiu(8,8,1);a.sw(8,17,S['total_ticks']);a.sw(8,16,tag.C['frame'])
    a.lw(8,17,S['ticks']);a.li(9,60);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.lw(9,19);a.li(10,ACTOR_HZ);a.r(0x19,0,9,10);a.r(0x12,9,0,0)
    a.r(0x2B,8,8,9);a.branch(5,8,0,'done')
    a.lw(8,17,S['phase']);a.addiu(8,8,1);a.sw(8,17,S['phase']);a.jump('done')
    a.label('finish');a.move(4,0);a.call(FINISH);a.jump('done')
    a.label('cancel');a.li(4,1);a.call(FINISH);a.jump('done')
    a.label('stale');a.li(4,1);a.call(FINISH)
    a.label('done');tag.restore(a);a.jr()
    data=a.finish();assert STEP_BODY+len(data)<=BODIES_END,len(data);return data


def finish_code():
    """a0 cancellation; release ACTIVE only after every valid actor is safe."""
    a=Assembler(FINISH_BODY);tag.save(a);a.move(18,4);a.li(16,CONTROL);a.li(17,STATE)
    a.lw(8,16,tag.C['active']);a.li(9,1);a.branch(5,8,9,'done')
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'stale_world')
    a.lw(8,17,S['cancelled']);a.r(0x25,18,18,8);a.sw(18,17,S['cancelled'])
    a.li(8,1);a.sw(8,17,S['retiring']);a.call(effects.STOP)
    a.branch(4,2,0,'retired')
    # Return to the normal game loop while native children retire. No busy
    # wait and no unsafe descriptor free while the renderer still owns a node.
    a.lw(8,17,S['retirement_ticks']);a.addiu(8,8,1);a.sw(8,17,S['retirement_ticks'])
    a.i(11,9,8,RETIREMENT_LIMIT);a.branch(5,9,0,'done')
    # Persistent private FX storage stays allocated. Disarm future tag moves,
    # release player control, and let the coordinator retry STOP outside GATE.
    a.li(18,1);a.sw(18,17,S['cleanup_pending']);a.sw(18,17,S['cancelled']);a.sw(0,16,tag.C['ready'])
    a.label('retired')
    a.li(21,ROWS);a.move(20,0)
    # Capture current rendered roots before replacing any borrowed pose.
    a.label('endpoints');identity(a,21,'end_next','end')
    copy_words(a,21,R['original'],21,R['end'],16)
    a.lw(8,21,R['borrowed']);a.branch(4,8,0,'end_next')
    a.lw(10,23,3436+4*2);full.pointer(a,10,80,'end_next');finite(a,10,(64,68,72),'end_next')
    for off in range(0,12,4):
        a.i(49,0,10,64+off);a.i(49,1,21,R['bone_offset']+off);fp.fop(a,1,0,0,1);a.i(57,0,21,R['end']+off)
    a.label('end_next');a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'endpoints')
    # Only separate overlapping final anchors; there is no return teleport to
    # where the fighters happened to be before the move.
    for first,second in ((0,1),(0,2),(1,2)):
        a.li(21,ROWS+first*STRIDE);a.li(22,ROWS+second*STRIDE);fp.fconst(a,3,0.0)
        for off in (0,4,8):
            a.i(49,0,21,R['end']+off);a.i(49,1,22,R['end']+off);fp.fop(a,1,0,0,1);fp.fop(a,2,0,0,0);fp.fop(a,0,3,3,0)
        fp.fconst(a,1,2500.0);fp.fop(a,0x34,0,3,1);a.branch(17,8,0,f'separate{first}{second}')
        a.i(49,0,21,R['end']);fp.fconst(a,1,35.0);fp.fop(a,1,0,0,1);a.i(57,0,21,R['end'])
        a.i(49,0,22,R['end']);fp.fop(a,0,0,0,1);a.i(57,0,22,R['end'])
        a.label(f'separate{first}{second}')
    a.li(21,ROWS);a.move(20,0)
    a.label('restore');identity(a,21,'restore_next','restore')
    a.lw(8,21,R['clip0']);a.sw(8,23,192)
    # A successful victim stays in its hit pose until damage and native fall
    # admission below. Attackers and aborted scenes restore their own idle.
    a.li(8,2);a.branch(5,20,8,'restore_idle');a.branch(4,18,0,'restore_place')
    a.label('restore_idle')
    # Idle's entry/cleanup reinstates the fighter's own model, pose, flags and
    # move events. Old attacking animation fields are deliberately not replayed.
    native_idle(a,22)
    # Requesting action11 when already idle can retain the decoded loan. This
    # explicit native animation start rebuilds that decoded pose from our own
    # restored animation directory even when the dispatcher takes that shortcut.
    a.move(4,22);a.lw(5,21,R['idle_animation'])
    a.emit((17<<26)|(4<<21)|(12<<11));a.call(A(0x1C3E60))
    a.label('restore_place')
    a.move(4,22);a.addiu(5,21,R['end']);a.addiu(6,21,R['rotation']);a.call(safety.PLACE)
    a.branch(5,2,0,'placed')
    # Invalid live terrain leaves the last safe original position as fallback.
    a.move(4,22);a.addiu(5,21,R['original']);a.addiu(6,21,R['rotation']);a.call(safety.PLACE)
    a.label('placed');a.sw(0,21,R['borrowed']);a.sw(0,21,R['loaded_clip']);a.sw(0,21,native_pose.ACTIVE)
    a.label('restore_next');a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'restore')
    a.branch(5,18,0,'cancelled');a.li(21,ROWS+2*STRIDE);identity(a,21,'cancelled','victim')
    fall_recovery.hp_record(a,22,24,'cancelled');a.lw(20,24);a.lw(19,22,0x994)
    a.call(damage_schedule.FINAL);a.branch(4,2,0,'victim_damage_refused')
    # Scenario rules may reject the hit or replace a form during the damage
    # callback. Keep their decision; never force the replacement into a fall.
    identity(a,21,'completed','after_damage');a.lw(8,22,0x994);a.branch(5,8,19,'completed')
    fall_recovery.hp_record(a,22,24,'completed');a.lw(8,24)
    a.r(0x2A,8,8,20);a.branch(5,8,0,'victim_hurt')
    a.li(8,damage_schedule.STATE);a.lw(8,8,damage_schedule.C['loss']);a.branch(4,8,0,'victim_idle')
    a.label('victim_hurt')
    a.move(4,21);a.lw(8,17,S['descriptor']);a.lw(5,8,28);a.call(fall_recovery.BEGIN)
    a.branch(5,2,0,'completed')
    # A native transition already chosen during handoff takes precedence.
    identity(a,21,'completed','after_fall');a.lw(8,22,2376);a.li(9,11)
    a.branch(5,8,9,'completed')
    a.label('victim_idle');native_idle(a,22);a.move(4,22);a.lw(5,21,R['idle_animation'])
    a.emit((17<<26)|(4<<21)|(12<<11));a.call(A(0x1C3E60))
    a.label('completed')
    a.lw(8,16,tag.C['completed']);a.addiu(8,8,1);a.sw(8,16,tag.C['completed']);a.jump('camera_cleanup')
    # A refused finishing portion leaves no native fall to replace the loaned
    # pose. Decode the same idle victim's own pose before releasing ownership;
    # a scenario-selected action or changed body must retain its new state.
    a.label('victim_damage_refused');identity(a,21,'cancelled','refused_victim')
    a.lw(8,22,2376);a.li(9,11);a.branch(5,8,9,'cancelled')
    native_idle(a,22);a.move(4,22);a.lw(5,21,R['idle_animation'])
    a.emit((17<<26)|(4<<21)|(12<<11));a.call(A(0x1C3E60))
    a.label('cancelled');a.lw(8,16,tag.C['cancelled']);a.addiu(8,8,1);a.sw(8,16,tag.C['cancelled'])
    # A full-screen pass can leave our private camera selected until the next
    # renderer pass. Release only those bindings still owned by this scene;
    # never overwrite another player's camera or a new renderer/world.
    a.label('camera_cleanup');a.lw(8,28,-22172);a.lw(19,17,S['saved_renderer']);a.branch(5,8,19,'release')
    full.pointer(a,19,0xC44,'release');a.li(20,camera.CAMERA)
    a.lw(8,28,-22176);a.branch(5,8,20,'render_binding')
    a.lw(21,17,S['saved_camera']);full.pointer(a,21,832,'release')
    a.branch(4,21,20,'release');a.move(4,21);a.li(5,1);a.call(A(0x23E6A0));a.sw(21,28,-22176)
    a.label('render_binding');a.lw(8,19,0xC40);a.branch(4,8,20,'restore_binding')
    a.addiu(9,20,16);a.branch(5,8,9,'release')
    a.label('restore_binding');a.lw(8,17,S['saved_binding']);a.sw(8,19,0xC40)
    a.jump('release')
    a.label('stale_world');a.call(effects.STOP)
    a.r(0x2B,8,0,2);a.sw(8,17,S['cleanup_pending']);a.sw(0,16,tag.C['ready'])
    a.label('release');a.sw(0,16,tag.C['members']);a.sw(0,17,S['magic']);a.sw(0,16,tag.C['active'])
    a.label('done');tag.restore(a);a.jr()
    data=a.finish();assert FINISH_BODY+len(data)<=FINISH_BODY_END,len(data);return data


def fx_step_code():
    """Internal STEP continuation; native FX own their updates/retirement."""
    a=Assembler(FX_BODY);tag.save(a)
    a.lw(18,19,28);a.i(12,8,18,assets.BEAM_LEAD|assets.BEAM_PARTNER);a.branch(4,8,0,'update')
    a.lw(8,17,S['fx_started']);a.li(9,1);a.branch(4,8,9,'update')
    a.li(20,160);a.i(12,8,18,assets.CUSTOM_FINISHER);a.branch(4,8,0,'native_fire')
    a.lw(8,17,S['placement']);full.pointer(a,8,64,'no',temp=10);a.lw(20,8,8)
    a.label('native_fire');a.lw(21,19);a.r(0x2B,8,20,21);a.branch(4,8,0,'no')
    # Custom endings retain the same native emitter from charge to fire.
    # The original Sadistic Dance phase keeps its original firing schedule.
    a.i(12,8,18,assets.CUSTOM_FINISHER);a.branch(4,8,0,'firing_check')
    a.lw(8,17,S['fx_started']);a.branch(5,8,0,'firing_check')
    a.li(9,ACTOR_HZ);a.r(0x19,0,21,9);a.r(0x12,8,0,0)
    a.addiu(8,8,59);a.li(9,60);a.r(0x1B,0,8,9);a.r(0x12,22,0,0)
    for role in (0,1):
        a.i(12,8,18,assets.BEAM_LEAD if role==0 else assets.BEAM_PARTNER);a.branch(4,8,0,f'charge{role}_done')
        a.li(4,role);a.move(5,22);a.call(effects.CHARGE_SPAWN)
        a.branch(4,2,0,'no');a.label(f'charge{role}_done')
    a.li(8,2);a.sw(8,17,S['fx_started'])
    a.label('firing_check')
    # Compare source-frame products, preserving correct crossing on PAL too.
    a.lw(8,17,S['ticks']);a.li(9,60);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.li(9,ACTOR_HZ);a.r(0x19,0,20,9);a.r(0x12,9,0,0);a.r(0x2B,8,8,9);a.branch(5,8,0,'update')
    a.r(0x23,8,21,20);a.li(9,ACTOR_HZ);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.addiu(8,8,59);a.li(9,60);a.r(0x1B,0,8,9);a.r(0x12,21,0,0)
    for role in (0,1):
        a.i(12,8,18,assets.BEAM_LEAD if role==0 else assets.BEAM_PARTNER);a.branch(4,8,0,f'role{role}_done')
        a.lw(8,17,S['fx_started']);a.li(9,2);a.branch(4,8,9,f'ignite{role}')
        a.li(4,role);a.move(5,21);a.call(effects.SPAWN);a.jump(f'spawned{role}')
        a.label(f'ignite{role}');a.li(4,effects.ROWS+role*effects.STRIDE);a.call(effects.IGNITE)
        a.label(f'spawned{role}')
        a.branch(4,2,0,'no');a.label(f'role{role}_done')
    a.li(8,1);a.sw(8,17,S['fx_started'])
    a.label('update');a.call(effects.UPDATE)
    # One copied-position native impact at the beam's victim, leaving half a
    # second in the shot before restoring normal views and falling physics.
    # Cosmetic pool exhaustion never cancels an otherwise completed attack.
    a.i(12,8,18,assets.BEAM_LEAD|assets.BEAM_PARTNER);a.branch(4,8,0,'updated')
    a.lw(8,17,S['exploded']);a.branch(5,8,0,'updated')
    a.lw(8,17,S['fx_started']);a.li(9,1);a.branch(5,8,9,'updated')
    a.lw(8,19);a.addiu(8,8,-30);a.li(9,ACTOR_HZ)
    a.r(0x19,0,8,9);a.r(0x12,10,0,0)
    a.lw(8,17,S['ticks']);a.li(9,60);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.r(0x2B,8,8,10);a.branch(5,8,0,'updated')
    a.li(8,1);a.sw(8,17,S['exploded']);a.li(4,2);a.li(5,17);a.call(effects.EXPLOSION)
    a.label('updated');a.li(2,1)
    a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();data=a.finish();assert FX_BODY+len(data)<=FX_BODY_END;return data


def align_code():
    """Internal STEP helper: native 1D7C30's forward branch for our pair only.

    Sadistic Dance's move flags omit inverse alignment. Bone52 is the donor's
    authored contact anchor; native animation decoding selects victim bone3.
    No synthetic attack flags, global actor scan or unrelated pair is touched.
    """
    a=Assembler(ALIGN);a.sw(31,29,0x34C)
    for reg,off in ((20,0x350),(21,0x354),(22,0x358),(23,0x35C)):a.sw(reg,29,off)
    a.li(20,ROWS);a.li(21,ROWS+2*STRIDE);a.lw(22,20,R['model']);a.lw(23,21,R['model'])
    # Once the melee attacker exits the mixed ending, keep the victim at its
    # last authored contact mark. An idle bone52 is not a cinematic anchor.
    a.lw(8,20,R['recovering']);a.li(9,ROWS+STRIDE);a.lw(9,9,R['recovering'])
    a.r(0x25,8,8,9);a.branch(5,8,0,'aligned')
    for model,bone in ((22,52),(23,3)):
        a.lw(10,model,3436+4*bone);full.pointer(a,10,80,'no');finite(a,10,(64,68,72),'no')
    a.lw(4,20,R['model_id']);a.li(5,52);a.addiu(6,29,0x310);a.call(A(0x2058E0))
    a.lw(4,21,R['model_id']);a.li(5,3);a.addiu(6,29,0x320);a.call(A(0x2058E0))
    finite(a,29,(0x310,0x314,0x318,0x320,0x324,0x328),'no')
    a.lw(4,21,R['actor']);a.li(5,0x34);a.call(A(0x1DAC78))
    fp.fconst(a,3,1.0);a.branch(4,2,0,'delta')
    finite(a,23,(3204,),'no');a.i(49,0,23,3204);fp.fconst(a,1,0.0)
    fp.fop(a,0x34,0,0,1);a.branch(17,8,1,'no');fp.fop(a,0x34,0,3,0);a.branch(17,8,1,'no')
    fp.fop(a,1,3,3,0)
    a.label('delta')
    for off in (0,4,8):
        a.i(49,0,29,0x310+off);a.i(49,1,29,0x320+off);fp.fop(a,1,0,0,1)
        fp.fop(a,2,0,0,3);a.i(57,0,29,0x330+off)
    a.lw(4,21,R['actor']);a.call(A(0x1DC298));full.pointer(a,2,32,'no')
    finite(a,2,(0,4,8),'no')
    for off in (0,4,8):
        a.i(49,0,2,off);a.i(49,1,29,0x330+off);fp.fop(a,0,0,0,1);a.i(57,0,2,off)
    a.lw(4,21,R['actor']);a.move(5,0);a.call(A(0x1D7198))
    a.move(4,23);a.call(A(0x24E3F8));a.lw(4,21,R['actor']);a.call(A(0x1D70E8))
    a.lw(4,21,R['actor']);a.li(5,0x23);a.call(A(0x1DABE8));a.label('aligned');a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done')
    for reg,off in ((20,0x350),(21,0x354),(22,0x358),(23,0x35C)):a.lw(reg,29,off)
    a.lw(31,29,0x34C);a.jr();data=a.finish();assert len(data)<=0x400,len(data);return data


def recovery_code():
    """a0 role,a1 capture row ->0 authored pose,1 native idle,2 cancel.

    The non-ki role completes its reviewed frame80 before leaving the borrowed
    pose. Native 1C3E60's blend caches the current bones; 1C4920 advances only
    its own idle and blend clock, without dispatching an attack's events.
    The rendered hip stays at that last mark throughout the blend and wait.
    """
    a=Assembler(RECOVERY);tag.save(a);a.move(20,4);a.move(21,5);a.li(16,CONTROL);a.li(17,STATE)
    a.lw(8,17,S['phase']);a.li(9,4);a.branch(5,8,9,'authored')
    a.lw(8,16,tag.C['variant']);a.li(9,2);a.branch(4,8,9,'partner')
    a.li(9,3);a.branch(5,8,9,'authored');a.branch(5,20,0,'authored');a.jump('candidate')
    a.label('partner');a.li(9,1);a.branch(5,20,9,'authored')
    a.label('candidate');a.lw(8,17,S['ticks']);a.addiu(8,8,-1)
    a.li(9,60);a.r(0x19,0,8,9);a.r(0x12,8,0,0);a.i(11,9,8,80*ACTOR_HZ);a.branch(5,9,0,'authored')
    a.lw(22,21,R['actor']);a.lw(23,21,R['model']);a.lw(8,21,R['recovering']);a.branch(5,8,0,'advance')
    a.lw(10,23,3436+4*2);full.pointer(a,10,80,'cancel');finite(a,10,(64,68,72),'cancel')
    copy_words(a,10,64,21,R['recovery_anchor'],16)
    a.lw(8,21,R['clip0']);a.sw(8,23,192)
    a.move(4,22);a.lw(5,21,R['idle_animation']);fp.fconst(a,12,.2);a.call(A(0x1C3E60))
    # The native blend helper uses a30Hz divisor, even for PAL. Preserve the
    # requested .2 seconds at either actor update rate.
    fp.fconst(a,0,1.0/(.2*ACTOR_HZ));a.i(57,0,23,3208)
    a.li(8,1);a.sw(8,21,R['recovering']);a.sw(0,21,R['loaded_clip'])
    a.label('advance');fp.fconst(a,0,60.0/ACTOR_HZ);a.i(57,0,23,3200)
    a.move(4,22);a.move(5,0);a.call(A(0x1C4920))
    a.move(4,23);a.call(A(0x24C958));a.move(4,23);a.call(A(0x24E2B0));a.move(4,23);a.call(A(0x24E3F8))
    a.lw(10,23,3436+4*2);full.pointer(a,10,80,'cancel');finite(a,10,(64,68,72),'cancel')
    for off in (0,4,8):
        a.i(49,0,21,R['recovery_anchor']+off);a.i(49,1,10,64+off);fp.fop(a,1,0,0,1);a.i(57,0,29,0x300+off)
    a.move(4,22);a.call(A(0x1DC298));full.pointer(a,2,32,'cancel')
    # Translate both the model base and actor anchor; canonical giant scaling
    # then preserves this world displacement rather than multiplying it again.
    for off in (0,4,8):
        a.i(49,0,29,0x300+off)
        for base,at in ((23,2384),(2,0)):
            a.i(49,1,base,at+off);fp.fop(a,0,1,1,0);a.i(57,1,base,at+off)
    a.move(4,23);a.call(A(0x24E2B0));a.move(4,23);a.call(A(0x24E3F8))
    a.move(4,22);a.call(A(0x1D70E8));a.li(2,1);a.jump('done')
    a.label('authored');a.move(2,0);a.jump('done')
    a.label('cancel');a.li(2,2)
    a.label('done');tag.restore(a,2);a.jr();data=a.finish();assert len(data)<=RECOVERY_END-RECOVERY,len(data);return data


def pieces():
    import tag_rush_approach as approach
    assert audio.END<=RECOVERY and RECOVERY_END<=safety.STATE
    jump=lambda destination:struct.pack('<2I',0x08000000|(destination>>2),0)
    result=[(START,jump(START_BODY)),(START_BODY,start_code()),(STEP,jump(STEP_BODY)),(STEP_BODY,step_code()),
            (ANCHOR,anchor_code()),(FINISH,jump(FINISH_BODY)),(FINISH_BODY,finish_code()),(FX_STEP,jump(FX_BODY)),(FX_BODY,fx_step_code()),
            (ALIGN,align_code()),(STATE,bytes(END-STATE)),(RECOVERY,recovery_code())]+shots.pieces()+staging.pieces()+native_pose.pieces()+fall_recovery.pieces()+damage_schedule.pieces()
    result.sort()
    for (p,b),(q,_) in zip(result,result[1:]):assert p+len(b)<=q,(hex(p),len(b),hex(q))
    return result+approach.pieces()


def installation(pack, roster=None, settings=None, *, local_playtest=False, reviewed_assets=False):
    """Installer contract; unreviewed presentation cannot arm a live match."""
    variants=('two_ki','two_melee','mixed_ki_lead','mixed_ki_partner')
    words={tag.C['scene_table']:TABLE,0xA0:pack.get('staging_address',0)}
    placement=pack.get('choreography_asset')
    if placement is not None:
        if placement.get('reviewed')is not True:raise ValueError('Unreviewed tag rush placements')
        words[staging.TABLE_OFFSET]=placement['table_address']
    approach_asset=pack.get('approach')
    if approach_asset is not None:
        import tag_rush_launch as launch
        if approach_asset.get('reviewed') is not True:raise ValueError('Unreviewed native tag launch poses')
        words[launch.TABLE_OFFSET]=approach_asset['table_address']
    camera_asset=pack.get('camera_asset')
    if camera_asset is not None:
        if (camera_asset.get('source_sha256')!=shots.SOURCE_SHA256 or
                camera_asset.get('actor_hz')!=ACTOR_HZ or camera_asset.get('reviewed') is not True):
            raise ValueError('Unreviewed tag rush camera samples')
        words[shots.TABLE_OFFSET]=camera_asset['table_address'];words[shots.MAGIC_OFFSET]=shots.MAGIC
    for index,name in enumerate(variants):
        row=pack['variants'][name]
        words[0x80+8*index]=row['address'];words[0x84+8*index]=row['count']
    import tag_rush_approach as approach
    import tag_rush_voices as voices
    import tag_rush_audio_queue as audio_queue
    import tag_rush_launch as launch
    mutable=[(STATE,END),(effects.CONTROL,effects.END),(audio.STATE,audio.END),
             (audio_queue.STATE,audio_queue.END),
             (approach.STATE,approach.END),(launch.STATE,launch.END),(voices.STATE,voices.END),
             (fall_recovery.STATE,fall_recovery.END),(damage_schedule.STATE,damage_schedule.END)]
    if pack.get('beam_asset',{}).get('color_plan'):
        import tag_rush_colors as colors
        mutable.append((colors.STORAGE,colors.STORAGE_END))
    reviewed=reviewed_assets is True
    return dict(usable=reviewed,playtest_ready=local_playtest is True, limitations=[] if reviewed else [
        'Native beam descriptors, emitted visuals and retirement require a live match check before arming.',
        'The native paired-body alignment and phase staging require an in-game appearance review.',
        'Disc-authored camera shots, retargeting, impact effects and sound cues still need review.'],
        blocks=pieces()+effects.pieces(pack.get('beam_asset'))+audio.pieces(pack)+[(damage_schedule.TABLE,damage_schedule.table_data(pack))],
        mutable_ranges=mutable, control_words=words)
