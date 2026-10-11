"""Disc-timed portions of one configured tag attack damage budget.

Every reviewed strike uses the ordinary attributed damage entry. Native flags
suppress per-call rounding/combo scaling and hold the victim above zero until
successful cleanup; the final one-point portion permits the normal KO path.
Cancellation never submits future portions or the reserved finishing point.
"""
import struct
from prototype import Assembler
from native_map import A, ACTOR_HZ
import tag_team_rush as tag
import tag_rush_camera as camera
import tag_rush_safety as safety
import tag_rush_recovery as recovery

RESET,TICK,FINAL,APPLY = 0x06DAC000,0x06DAC800,0x06DAE000,0x06DAE800
TABLE,STATE,END = 0x06DAF400,0x06DAFC00,0x06DB0000
MAGIC=0x54444831
VARIANTS=('two_ki','two_melee','mixed_ki_lead','mixed_ki_partner')
C=dict(magic=0,manager=4,count=8,bank=12,cursor=16,budget=20,paid=24,
       loss=28,finalized=32,table=36,events=40)
HIT_FLAGS=0x02000502  # ultimate, nonlethal, no combo reduction, no rounding
FINAL_FLAGS=(HIT_FLAGS & ~0x400)|8  # final continuation is not an extra combo hit


def schedules(pack=None):
    """(phase, elapsed-source-frame, cumulative weight/10000) per impact.

    Identical simultaneous donor impact cues describe one physical contact.
    The beam burst receives60%; all earlier contacts share40%. Melee variants
    share the complete budget among their actual contacts. Integer cumulative
    allocation keeps the configured total exact even for odd/small values.
    """
    if not pack or not pack.get('audio_cues'):return {n:() for n in VARIANTS}
    result={}
    for name in VARIANTS:
        phases=pack['variants'][name]['phases'];cues=pack['audio_cues'][name]
        if len(phases)!=len(cues) or not 1<=len(phases)<=12:raise ValueError('Invalid tag damage phases')
        contacts=set();burst=None
        import tag_rush_assets as assets
        for phase,(row,events) in enumerate(zip(phases,cues)):
            duration=row['source_frames'];starts=row['starts'];ends=row['ends']
            for cue in events:
                if cue.get('sound_id')!=73:continue
                role,frame=cue.get('role'),cue.get('frame')
                if (cue.get('effect_kind')!=16 or type(role)is not int or not 0<=role<3
                        or type(frame)is not int or not starts[role]<=frame<=ends[role]):
                    raise ValueError('Unreviewed tag damage contact')
                elapsed=frame-starts[role]
                if not 0<=elapsed<=duration:raise ValueError('Invalid tag damage contact frame')
                contacts.add((phase,elapsed))
            if row['flags']&assets.FINISHER and row['flags']&(assets.BEAM_LEAD|assets.BEAM_PARTNER):
                if burst is not None or duration<=30:raise ValueError('Invalid tag damage beam finisher')
                burst=(phase,duration-30)
        if not contacts:raise ValueError('Tag attack has no reviewed damage contacts')
        if burst:
            contacts.discard(burst)
            if any(p>=burst for p in contacts):raise ValueError('Tag damage contact follows beam burst')
        ordered=sorted(contacts);weight=4000 if burst else 10000
        rows=[(p,f,(i+1)*weight//len(ordered)) for i,(p,f) in enumerate(ordered)]
        if burst:rows.append((*burst,10000))
        if len(rows)>64:raise ValueError('Too many tag damage contacts')
        result[name]=tuple(rows)
    return result


def table_data(pack=None):
    data=bytearray(32)
    for variant,name in enumerate(VARIANTS):
        rows=schedules(pack)[name];struct.pack_into('<2I',data,variant*8,TABLE+len(data),len(rows))
        for phase,frame,weight in rows:data.extend(struct.pack('<4I',phase,frame,weight,0))
    if len(data)>STATE-TABLE:raise ValueError('Tag damage table exceeds reservation')
    return bytes(data)


def valid(a,fail):
    """Authenticate the whole captured scene and the victim's selected HP bank."""
    import tag_rush_scene as scene
    camera.emit_active(a,fail);a.li(16,STATE);a.li(17,scene.STATE)
    a.lw(9,16);a.li(10,MAGIC);a.branch(5,9,10,fail)
    for off in (4,8):a.lw(9,16,off);a.lw(10,8,off);a.branch(5,9,10,fail)
    a.lw(9,17);a.li(10,scene.SCENE_MAGIC);a.branch(5,9,10,fail)
    a.li(21,scene.ROWS+2*scene.STRIDE);scene.identity(a,21,fail,'damage_victim')
    a.lw(9,22,0x994);a.lw(10,16,C['bank']);a.branch(5,9,10,fail)
    recovery.hp_record(a,22,24,fail)


def reset_code():
    import tag_rush_scene as scene
    a=Assembler(RESET);tag.save(a);a.li(16,STATE);a.sw(0,16)
    camera.emit_active(a,'done');a.lw(9,8,tag.C['variant']);a.i(11,10,9,4);a.branch(4,10,0,'done')
    a.r(0,9,0,9,3);a.li(10,TABLE);a.r(0x21,10,10,9);a.lw(11,10);a.lw(12,10,4)
    a.i(11,9,12,65);a.branch(4,9,0,'done');a.sw(11,16,C['table']);a.sw(12,16,C['events'])
    for off in (4,8):a.lw(9,8,off);a.sw(9,16,off)
    a.lw(9,8,tag.C['damage']);a.li(10,100000);a.r(0x2B,10,10,9);a.branch(5,10,0,'done');a.sw(9,16,C['budget'])
    a.li(21,scene.ROWS+2*scene.STRIDE);scene.identity(a,21,'done','reset_victim')
    a.lw(9,22,0x994);a.i(11,10,9,5);a.branch(4,10,0,'done');a.sw(9,16,C['bank'])
    for field in ('cursor','paid','loss','finalized'):a.sw(0,16,C[field])
    a.li(9,MAGIC);a.sw(9,16)
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert RESET+len(data)<=TICK;return data


def apply_code():
    """a0 raw portion,a1 hit flags -> v0 authenticated; records actual HP loss.

    Only the exact safety.DAMAGE native call supplies attack attribution. Its
    per-call latch is reset after reserving this event, before entering native
    scenario/defense/KO hooks. An interrupted/form-changing callback ends the
    scene instead of applying the remaining budget to another body.
    """
    import tag_rush_scene as scene
    a=Assembler(APPLY);tag.save(a);a.move(18,4);a.move(19,5);valid(a,'no')
    a.branch(6,18,0,'yes');a.lw(20,24);a.branch(6,20,0,'no')
    a.li(8,safety.DAMAGE_DONE);a.sw(0,8)
    a.move(4,22);a.move(5,18);a.move(6,19);a.call(safety.DAMAGE)
    a.branch(4,2,0,'no');valid(a,'no');a.lw(8,24);a.r(0x2B,9,8,20);a.branch(4,9,0,'yes')
    a.r(0x23,8,20,8);a.lw(9,16,C['loss']);a.r(0x21,9,9,8);a.sw(9,16,C['loss'])
    a.label('yes');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();data=a.finish();assert APPLY+len(data)<=TABLE;return data


def tick_code():
    import tag_rush_scene as scene
    a=Assembler(TICK);tag.save(a);valid(a,'no')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'yes')
    for field in ('retiring','cancelled'):a.lw(8,17,scene.S[field]);a.branch(5,8,0,'yes')
    a.lw(8,16,C['finalized']);a.branch(5,8,0,'yes')
    a.lw(18,17,scene.S['phase']);a.i(11,8,18,12);a.branch(4,8,0,'no')
    a.lw(19,17,scene.S['ticks']);a.i(11,8,19,1001);a.branch(4,8,0,'no')
    a.li(8,60);a.r(0x19,0,19,8);a.r(0x12,19,0,0)
    a.label('event');a.lw(20,16,C['cursor']);a.lw(8,16,C['events']);a.r(0x2B,8,20,8);a.branch(4,8,0,'yes')
    a.r(0,8,0,20,4);a.lw(25,16,C['table']);a.r(0x21,25,25,8)
    a.li(8,TABLE+32);a.r(0x2B,9,25,8);a.branch(5,9,0,'no');a.li(8,STATE-16)
    a.r(0x2B,9,8,25);a.branch(5,9,0,'no')
    a.lw(8,25);a.r(0x2B,9,18,8);a.branch(5,9,0,'yes');a.branch(5,8,18,'due')
    a.lw(8,25,4);a.li(9,ACTOR_HZ);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.r(0x2B,9,19,8);a.branch(5,9,0,'yes')
    a.label('due');a.lw(8,25,8);a.i(11,9,8,10001);a.branch(4,9,0,'no')
    a.lw(9,16,C['budget']);a.branch(4,9,0,'zero');a.addiu(9,9,-1)
    a.r(0x19,0,8,9);a.r(0x12,8,0,0);a.li(9,10000);a.r(0x1B,0,8,9);a.r(0x12,24,0,0);a.jump('amount')
    a.label('zero');a.move(24,0);a.label('amount');a.lw(9,16,C['paid']);a.r(0x2B,8,24,9);a.branch(5,8,0,'no')
    a.r(0x23,4,24,9);a.sw(24,16,C['paid']);a.addiu(20,20,1);a.sw(20,16,C['cursor'])
    a.li(5,HIT_FLAGS);a.call(APPLY);a.branch(4,2,0,'no');a.jump('event')
    a.label('yes');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();data=a.finish();assert TICK+len(data)<=FINAL;return data


def final_code():
    """Successful cleanup only; never charge unplayed events on cancellation."""
    import tag_rush_scene as scene
    a=Assembler(FINAL);tag.save(a);valid(a,'no')
    a.lw(8,17,scene.S['cancelled']);a.branch(5,8,0,'no');a.lw(8,16,C['finalized']);a.branch(5,8,0,'yes')
    a.lw(8,16,C['cursor']);a.lw(9,16,C['events']);a.branch(5,8,9,'no')
    a.li(8,1);a.sw(8,16,C['finalized']);a.lw(4,16,C['budget']);a.lw(9,16,C['paid'])
    a.r(0x2B,8,4,9);a.branch(5,8,0,'no');a.sw(4,16,C['paid']);a.r(0x23,4,4,9)
    a.li(5,FINAL_FLAGS);a.call(APPLY);a.branch(4,2,0,'no')
    a.label('yes');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();data=a.finish();assert FINAL+len(data)<=APPLY;return data


def pieces():
    return [(RESET,reset_code()),(TICK,tick_code()),(FINAL,final_code()),(APPLY,apply_code()),
            (STATE,bytes(END-STATE))]
