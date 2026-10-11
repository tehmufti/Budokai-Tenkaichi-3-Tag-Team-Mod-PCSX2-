"""Run the original rush action; replace only the successful paired capture.

Only the initiating real fighter dashes. Native startup/camera/steering/miss
behavior runs in the ordinary actor dispatcher, not a recreated motion loop.
The helper remains their real actor and joins the custom scene on contact.
"""
from prototype import Assembler
from native_map import A,ACTOR_HZ
import tag_team_rush as tag
import extra_throws as actors
import fusion_partner_lifecycle as full
import beam_struggle as fp
import fresh_team_combat as core

BEGIN,TICK,CANCEL,MOVE=0x06D80000,0x06D82000,0x06D83800,0x06D84000
START_SOUND=MOVE
STATE,END=0x06D86000,0x06D86800
MAGIC=0x54415031
S=dict(magic=0,active=4,manager=8,count=12,ticks=16,mask=20,misses=24,connected=28,
       reason=32,role=36,action=40,clip=44,pending=48,stage=52,phase_ticks=56,contact=60,
       sound_pending=64,sound_delivered=68,sound_discarded=72)
MISS_REASONS={0:'none',1:'battle ended',2:'native rush timed out',3:'participant identity changed',
 4:'participant no longer eligible',5:'participant busy or hit pending',6:'native rush interrupted',
 7:'attacker took damage',8:'native rush missed or reached a different target',9:'cinematic preflight refused',10:'stale capture'}
ROWS,STRIDE=STATE+0x100,0x80
R=dict(index=0,actor=4,model=8,character=12,skeleton=16,model_id=20,hp=24)
TIMEOUT=8*ACTOR_HZ
MAX_DISTANCE=1000.
NATIVE_ACTION=285
NATIVE_PRELUDE=261
NATIVE_START_SOUND=43


def identity(a,row,fail,prefix):
    a.lw(10,row,R['index']);a.li(9,tag.CONTROL);a.lw(9,9,tag.C['count'])
    a.r(0x2B,9,10,9);a.branch(4,9,0,fail)
    a.r(0,10,0,10,2);a.li(9,core.POINTERS);a.r(0x21,9,9,10);a.lw(22,9)
    a.lw(8,row,R['actor']);a.branch(5,22,8,fail)
    actors.model(a,22,23,fail)
    for current,saved in ((12,R['character']),(16,R['model_id']),(64,R['skeleton'])):
        a.lw(8,23,current);a.lw(9,row,saved);a.branch(5,8,9,fail)
    a.lw(8,row,R['model']);a.branch(5,23,8,fail)


def distance(a,source,target,out=3):
    fp.fconst(a,out,0.)
    for off in (0,4,8):
        a.i(49,0,target,2384+off);a.i(49,1,source,2384+off)
        fp.fop(a,1,0,0,1);fp.fop(a,2,0,0,0);fp.fop(a,0,out,out,0)


def begin_code():
    import tag_rush_safety as safety
    import tag_rush_scene as scene
    import tag_rush_launch as launch
    a=Assembler(BEGIN);tag.save(a);a.move(16,4);a.move(17,5);a.move(18,6)
    a.call(tag.GATE);a.branch(4,2,0,'no');a.li(19,tag.CONTROL)
    for off in (tag.C['active'],tag.C['approaching']):a.lw(8,19,off);a.branch(5,8,0,'no')
    for first,second in ((16,17),(16,18),(17,18)):a.branch(4,first,second,'no')
    a.r(0x26,8,16,17);a.i(12,8,8,1);a.branch(5,8,0,'no')
    a.r(0x26,8,16,18);a.i(12,8,8,1);a.branch(4,8,0,'no')
    for i,r in enumerate((16,17,18)):a.sw(r,29,0x300+4*i)
    a.li(20,0);a.li(21,ROWS)
    a.label('check');a.r(0,8,0,20,2);a.addiu(9,29,0x300);a.r(0x21,9,9,8);a.lw(4,9)
    a.call(tag.ELIGIBLE);a.branch(4,2,0,'no');a.move(22,2)
    a.move(4,22);a.call(safety.PREFLIGHT);a.branch(4,2,0,'no')
    actors.model(a,22,23,'no');scene.finite(a,23,(2384,2388,2392,2400,2404,2408),'no')
    for field,reg in (('actor',22),('model',23)):a.sw(reg,21,R[field])
    a.lw(8,22);a.sw(8,21,R['index'])
    for off,key in ((12,'character'),(16,'model_id'),(64,'skeleton')):a.lw(8,23,off);a.sw(8,21,R[key])
    a.lw(8,22,0x994);a.li(9,164);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.r(0x21,8,8,22);a.lw(8,8,0x9E4);a.sw(8,21,R['hp'])
    a.branch(5,20,0,'checked');a.move(4,23);a.call(launch.CHECK);a.branch(4,2,0,'no')
    a.label('checked');a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'check')
    a.li(21,ROWS);a.lw(23,21,R['model']);a.li(8,ROWS+2*STRIDE);a.lw(24,8,R['model'])
    distance(a,23,24);fp.fconst(a,4,MAX_DISTANCE**2);fp.fop(a,0x36,0,3,4);a.branch(17,8,0,'no')
    # Outgoing ordinary cleanup precedes borrowing. No helper or victim action
    # is replaced during the dash; only native contact admits the custom scene.
    a.lw(22,21,R['actor']);scene.native_idle(a,22)
    a.call(launch.ENTER);a.branch(4,2,0,'no')
    a.li(21,STATE);a.li(8,MAGIC);a.sw(8,21,S['magic'])
    for off,key in ((tag.C['manager'],'manager'),(tag.C['count'],'count')):a.lw(8,19,off);a.sw(8,21,S[key])
    for key in ('ticks','reason','stage','phase_ticks','contact','sound_pending'):a.sw(0,21,S[key])
    a.li(8,1);a.sw(8,21,S['active']);a.sw(8,19,tag.C['approaching'])
    a.li(21,tag.METERS);a.lw(20,19,tag.C['count']);a.li(8,-1)
    a.label('offers');a.sw(8,21,tag.T['inviter']);a.sw(0,21,tag.T['expiry'])
    a.addiu(21,21,tag.METER_STRIDE);a.addiu(20,20,-1);a.branch(5,20,0,'offers')
    a.li(21,ROWS);a.lw(4,21,R['actor']);a.li(5,NATIVE_PRELUDE);a.call(A(0x1E0290))
    a.lw(4,21,R['actor']);a.move(5,0);a.li(6,NATIVE_PRELUDE);a.call(A(0x1E02A8))
    a.lw(4,21,R['actor']);a.li(5,1);a.li(6,NATIVE_ACTION);a.call(A(0x1E02A8))
    a.lw(4,21,R['actor']);a.call(A(0x1E23D0))
    # Native261 phase0 calls1F5FF8 ->1DA370(actor,43), but BEGIN runs
    # before1C2B30 clears this frame's sound requests. Deliver that one
    # accepted startup at the existing late sound hook instead. Merely
    # offering/holding the input never arms this receipt.
    a.lw(8,21,R['actor']);a.lw(8,8,2376);a.li(9,NATIVE_PRELUDE)
    a.branch(5,8,9,'started');a.li(8,STATE);a.li(9,1);a.sw(9,8,S['sound_pending'])
    a.label('started')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();data=a.finish();assert BEGIN+len(data)<=TICK;return data


def tick_code():
    import tag_rush_safety as safety
    import tag_rush_scene as scene
    import tag_rush_launch as launch
    a=Assembler(TICK);tag.save(a);a.li(16,STATE);a.li(17,tag.CONTROL)
    a.lw(8,16);a.li(9,MAGIC);a.branch(5,8,9,'stale')
    a.lw(8,16,S['active']);a.li(9,1);a.branch(5,8,9,'done')
    a.lw(8,16,S['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'stale')
    for field in ('manager','count'):
        a.lw(8,16,S[field]);a.lw(9,17,tag.C[field]);a.branch(5,8,9,'stale')
    core.gate(a,'gate_miss')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    import native_preparation as prep
    a.li(8,prep.CONTROL);a.lw(9,8);a.li(10,prep.MAGIC);a.branch(5,9,10,'not_quiet')
    a.lw(9,8,16);a.branch(5,9,0,'done')
    a.label('not_quiet');a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,9,8,0x2000);a.branch(5,9,0,'gate_miss')
    a.i(12,9,8,0x100);a.branch(5,9,0,'done')
    a.li(8,A(0x3337C0));a.lw(8,8);a.li(9,1);a.branch(5,8,9,'gate_miss')
    a.lw(8,16,S['ticks']);a.addiu(8,8,1);a.sw(8,16,S['ticks']);a.i(11,9,8,TIMEOUT+1);a.branch(4,9,0,'timeout_miss')
    a.li(20,0);a.li(21,ROWS)
    a.label('roles');a.sw(20,16,S['role']);identity(a,21,'identity_miss','tick')
    actors.hp(a,22,'eligible_miss');safety.emit_non_giant_model(a,23,'eligible_miss');tag.emit_admitted_model(a,23,'eligible_miss')
    scene.finite(a,23,(2384,2388,2392),'identity_miss')
    a.branch(5,20,0,'role_next')
    for field,offset in (('action',2376),('clip',2420),('pending',2380)):
        a.lw(8,22,offset);a.sw(8,16,S[field])
    a.lw(8,22,0x994);a.li(9,164);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.r(0x21,8,8,22);a.lw(8,8,0x9E4);a.lw(9,21,R['hp']);a.branch(5,8,9,'hp_miss')
    a.lw(8,22,2376);a.li(9,NATIVE_PRELUDE);a.branch(4,8,9,'native_owned')
    a.li(9,NATIVE_ACTION);a.branch(5,8,9,'native_miss');a.label('native_owned')
    a.lw(8,23,2348);a.li(9,launch.PARAMS);a.branch(5,8,9,'identity_miss')
    a.lw(8,22,2420);a.sw(8,16,S['stage'])
    a.label('role_next');a.addiu(20,20,1);a.addiu(21,21,STRIDE);a.li(8,3);a.branch(5,20,8,'roles')
    a.lw(8,16,S['contact']);a.branch(4,8,0,'done');a.li(9,1);a.branch(5,8,9,'native_miss')
    # Native contact has not yet written the paired victim or original helper.
    # Finish original rush cleanup while its borrowed parameters still exist.
    a.move(4,0);a.call(CANCEL)
    for r,p in ((4,ROWS),(5,ROWS+STRIDE),(6,ROWS+2*STRIDE)):a.li(8,p);a.lw(r,8,R['index'])
    a.call(tag.START);a.branch(4,2,0,'failed_start')
    a.lw(8,16,S['connected']);a.addiu(8,8,1);a.sw(8,16,S['connected']);a.jump('done')
    for label,value in (('gate_miss',1),('timeout_miss',2),('identity_miss',3),('eligible_miss',4),('hp_miss',7),('native_miss',8)):
        a.label(label);a.li(8,value);a.jump('miss')
    a.label('miss');a.sw(8,16,S['reason']);a.li(4,1);a.call(CANCEL);a.jump('done')
    a.label('failed_start');a.li(8,9);a.sw(8,16,S['reason']);a.lw(8,16,S['misses']);a.addiu(8,8,1);a.sw(8,16,S['misses']);a.jump('done')
    a.label('stale');a.li(8,10);a.sw(8,16,S['reason']);a.call(launch.RESTORE);a.sw(0,16,S['active']);a.sw(0,16,S['sound_pending']);a.sw(0,17,tag.C['approaching'])
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert TICK+len(data)<=CANCEL;return data


def cancel_code():
    import tag_rush_scene as scene
    import tag_rush_launch as launch
    a=Assembler(CANCEL);tag.save(a);a.move(16,4);a.li(17,STATE);a.li(21,ROWS)
    a.lw(8,17,S['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'restore')
    identity(a,21,'restore','cancel')
    a.lw(8,22,2376);a.li(9,NATIVE_PRELUDE);a.branch(4,8,9,'cancel_owned')
    a.li(9,NATIVE_ACTION);a.branch(5,8,9,'restore');a.label('cancel_owned')
    a.lw(8,22,2380);a.li(9,-1);a.branch(5,8,9,'restore')
    a.call(launch.RESET_MARKER)
    a.move(4,22);a.call(A(0x1E0310))
    scene.native_idle(a,22)
    # Native285 success requests effect5 before303. The normal actor effect
    # pass (1D0508) then removes the dash trail, restores ordinary aura mode
    # and clears model effect6. Our contact handoff holds the actor before
    # that pass, so finish that exact, actor-local path here. Do not destroy
    # the ordinary aura or touch another action's beam/charge effects.
    a.li(8,launch.STATE);a.lw(8,8,launch.P['owned']);a.li(9,1);a.branch(5,8,9,'restore')
    a.lw(8,23,2348);a.li(9,launch.PARAMS);a.branch(5,8,9,'restore')
    a.lw(8,23,2868);a.i(12,8,8,0x40);a.branch(4,8,0,'restore')
    a.lw(4,22,12);a.li(5,2);a.call(A(0x1714E8))
    a.lw(4,22,12);a.li(5,5);a.call(A(0x165418))
    a.move(4,23);a.li(5,6);a.move(6,0);a.call(A(0x2500E8))
    a.label('restore');a.call(launch.RESTORE);a.li(8,tag.CONTROL);a.sw(0,8,tag.C['approaching'])
    a.sw(0,17,S['active']);a.sw(0,17,S['sound_pending']);a.branch(4,16,0,'done');a.lw(8,17,S['misses']);a.addiu(8,8,1);a.sw(8,17,S['misses'])
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert CANCEL+len(data)<=MOVE;return data


def emit_hold(a,actor,held,fail):
    # The original action must run through every ordinary actor update.
    # Native startup flags own its normal pause. No synthetic actor hold.
    a.jump(fail)


def start_sound_code():
    """Queue the native261 one-shot after the frame reset, exactly once.

    Uses the real owner's bone3/attenuation and common sound bank. It neither
    starts native285 again nor touches actor/beam sound loops. A short native
    backlog can retry; cancellation, a new world or an old receipt cannot.
    """
    import tag_rush_launch as launch
    a=Assembler(START_SOUND);tag.save(a);a.li(16,STATE)
    a.lw(8,16,S['magic']);a.li(9,MAGIC);a.branch(5,8,9,'done')
    a.lw(8,16,S['sound_pending']);a.li(9,1);a.branch(5,8,9,'done')
    a.lw(8,16,S['active']);a.branch(5,8,9,'discard')
    a.li(17,tag.CONTROL);a.lw(8,17,tag.C['approaching']);a.branch(5,8,9,'discard')
    a.lw(8,16,S['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'discard')
    for field in ('manager','count'):
        a.lw(8,16,S[field]);a.lw(9,17,tag.C[field]);a.branch(5,8,9,'discard')
    core.gate(a,'discard')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    a.lw(8,16,S['ticks']);a.i(11,8,8,5);a.branch(4,8,0,'discard')
    a.li(21,ROWS);identity(a,21,'discard','sound')
    a.lw(8,23,2348);a.li(9,launch.PARAMS);a.branch(5,8,9,'discard')
    a.lw(8,22,2376);a.li(9,NATIVE_PRELUDE);a.branch(4,8,9,'owned')
    a.li(9,NATIVE_ACTION);a.branch(5,8,9,'discard');a.label('owned')
    a.lw(18,16,S['manager']);a.lw(19,18,288);a.i(11,8,19,5);a.branch(4,8,0,'discard')
    # If a native path already submitted this exact owner/cue this frame,
    # consume our receipt without duplicating it.
    a.addiu(20,18,160);a.move(24,19);a.lw(25,21,R['index'])
    a.label('scan');a.branch(4,24,0,'submit')
    a.lw(8,20,24);a.li(9,NATIVE_START_SOUND);a.branch(5,8,9,'next')
    a.i(36,8,20,28);a.branch(5,8,25,'next');a.i(36,8,20,29);a.branch(4,8,0,'delivered')
    a.label('next');a.addiu(20,20,32);a.addiu(24,24,-1);a.jump('scan')
    a.label('submit');a.i(11,8,19,4);a.branch(4,8,0,'done')
    a.li(4,4);a.call(A(0x1252D8));a.branch(4,2,0,'discard')
    a.move(4,22);a.li(5,NATIVE_START_SOUND);a.call(A(0x1DA370))
    a.lw(8,18,288);a.branch(4,8,19,'done')
    a.label('delivered');a.sw(0,16,S['sound_pending'])
    a.lw(8,16,S['sound_delivered']);a.addiu(8,8,1);a.sw(8,16,S['sound_delivered']);a.jump('done')
    a.label('discard');a.sw(0,16,S['sound_pending'])
    a.lw(8,16,S['sound_discarded']);a.addiu(8,8,1);a.sw(8,16,S['sound_discarded'])
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert START_SOUND+len(data)<=STATE;return data


def pieces():
    import tag_rush_launch as launch
    return [(BEGIN,begin_code()),(TICK,tick_code()),(CANCEL,cancel_code()),
            (START_SOUND,start_sound_code()),(STATE,bytes(END-STATE))]+launch.pieces()
