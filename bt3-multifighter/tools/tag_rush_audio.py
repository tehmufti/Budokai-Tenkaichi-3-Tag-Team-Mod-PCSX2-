"""Local tag-rush global sound cues and staggered own-character voices.

Four reviewed sound flags from native1D27F8 and strike cues from1D3170 are
admitted, using their source frames and encoded impact bones.
The ordinary positional sound queue owns shared playback and cleanup. Own voices
use the bounded stream arbiter. The separate private beam bank contains only
reviewed charge/fire effects; it cannot dispatch a donor character's voice.
Shared charge21 uses its loaded-bank loop flag: one-shot onset here, or native
actor-owned renewal in the deferred dispatcher until the firing boundary.
"""
import struct
from prototype import Assembler
from native_map import A, ACTOR_HZ
import tag_team_rush as tag
import tag_rush_camera as camera
import fusion_partner_lifecycle as full
import fresh_team_combat as core
import beam_struggle as fp
import tag_rush_effects as effects
import tag_rush_audio_queue as deferred

BASE, RESET, TICK = 0x06D0C000, 0x06D0C000, 0x06D0C400
TABLE, STATE, END = 0x06D0CE00, 0x06D0D700, 0x06D0D800
ROWS, STRIDE, MAGIC = STATE+0x20, 16, 0x54534131
VARIANTS=('two_ki','two_melee','mixed_ki_lead','mixed_ki_partner')
C=dict(magic=0,manager=4,count=8,played=12)
R=dict(phase=0,frame=4)
SOUND=deferred.ENQUEUE
# Native1CD420 ->2111D0 ->1CAD68 selector2 uses bank0/sound71 for
# a primary beam's final blast. This is separate from its repeated hit SFX.
EXPLOSION_SOUND=71


def cue_rows(pack=None):
    """Collapse identical variant cues, retaining only explicitly reviewed SFX."""
    if not pack:return ()
    mapping=pack.get('audio_cues',{})
    if not mapping:return ()
    if set(mapping)!=set(VARIANTS):raise ValueError('Tag sound variants are incomplete')
    merged={}
    for variant,name in enumerate(VARIANTS):
        phases=mapping[name]
        if not 1<=len(phases)<=12:raise ValueError('Tag sound phases changed')
        for phase,cues in enumerate(phases):
            # Native charge action55 uses20F428 ->1DA370(bank0,21). The
            # clash poses contain no animation events, so schedule that same
            # onset explicitly. Bank availability/one-shot status is checked
            # in the guest before queuing; never create an unowned loop.
            import tag_rush_assets as assets
            phase_rows=pack.get('variants',{}).get(name,{}).get('phases',())
            if phase<len(phase_rows):
                row=phase_rows[phase];flags=row.get('flags',0)
                if flags&assets.FINISHER and flags&(assets.BEAM_LEAD|assets.BEAM_PARTNER):
                    frames=row.get('source_frames')
                    if type(frames)is not int or not 30<frames<=1000:
                        raise ValueError('Invalid tag beam ending duration')
                    # Match FX_BODY's final burst, once at the victim even
                    # when both attackers fire. The normal cursor handles
                    # pauses and skipped frames without replaying the sound.
                    cues=tuple(cues)+(dict(role=2,frame=frames-30,bank=0,
                        sound_id=EXPLOSION_SOUND,bone=3,near=200.,far=1500.),)
            if phase<len(phase_rows) and phase_rows[phase].get('flags',0)&assets.OWN_CLASH_POSE:
                flags=phase_rows[phase]['flags']
                charge=tuple(dict(role=role,frame=0,bank=0,sound_id=21,bone=3,near=200.,far=1500.)
                             for role,bit in enumerate((assets.BEAM_LEAD,assets.BEAM_PARTNER)) if flags&bit)
                cues=tuple(cues)+charge
            seen=set()
            for cue in cues:
                role,frame,sound=cue.get('role'),cue.get('frame'),cue.get('sound_id')
                if type(role)is not int or not 0<=role<3 or type(frame)is not int or not 0<=frame<=1000:
                    raise ValueError('Invalid tag sound source frame or role')
                if cue.get('bank')!=0 or cue.get('bone')!=3 or cue.get('near')!=200. or cue.get('far')!=1500.:
                    raise ValueError('Unreviewed tag sound bank, source bone or attenuation')
                alternate,flag=cue.get('alternate_sound_id'),cue.get('parameter_flag',0)
                effect,impact_bone=cue.get('effect_kind',0),cue.get('impact_bone',0)
                if sound==51:
                    if alternate!=11 or flag!=0x8000:raise ValueError('Tag impact sound selector changed')
                elif sound==73:
                    if effect!=16 or type(impact_bone)is not int or not 0<=impact_bone<32 or alternate not in(None,0)or flag:
                        raise ValueError('Unreviewed tag impact visual')
                elif sound not in (21,24,30,31,EXPLOSION_SOUND) or alternate not in (None,0) or flag:
                    raise ValueError('Unreviewed tag sound event')
                if sound!=73 and (effect or impact_bone):raise ValueError('Unexpected tag sound visual')
                key=(phase,role,frame,sound,(alternate or 0)|(impact_bone<<8)|(effect<<16))
                if key in seen:raise ValueError('Duplicate tag sound event')
                seen.add(key);merged[key]=merged.get(key,0)|(1<<variant)
    rows=tuple((mask,*key)for key,mask in sorted(merged.items()))
    if len(rows)*24>STATE-TABLE:raise ValueError('Tag sound cue table is too large')
    return rows


def reset_code(voices=False):
    a=Assembler(RESET);tag.save(a);a.li(16,STATE)
    a.sw(0,16,C['magic']);camera.emit_active(a,'done')
    a.lw(9,8,4);a.sw(9,16,C['manager']);a.lw(9,8,8);a.sw(9,16,C['count'])
    a.sw(0,16,C['played']);a.li(9,0xFFFFFFFF)
    for role in range(3):
        a.li(8,ROWS+role*STRIDE);a.sw(9,8,R['phase']);a.sw(9,8,R['frame'])
    a.li(9,MAGIC);a.sw(9,16,C['magic'])
    deferred.reset(a)
    if voices:
        import tag_rush_voices
        a.call(tag_rush_voices.RESET)
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert len(data)<=TICK-RESET;return data


def tick_code(count=0,voices=False):
    """No arguments; STEP calls once after posed actors and beam processing.

    Per-role cursors compare source frames, so repeated clamped poses, paused
    frames and frame skips cannot duplicate cues. Phase0/frame0 is included on
    the first successful update. Source time is the scene's60Hz clip clock.
    """
    import tag_rush_scene as scene
    import tag_rush_assets as assets
    if type(count)is not int or not 0<=count<=(STATE-TABLE)//24:raise ValueError('Invalid tag sound cue count')
    a=Assembler(TICK);tag.save(a)
    if voices:
        import tag_rush_voices
        a.call(tag_rush_voices.TICK)
    if count==0:
        tag.restore(a);a.jr();return a.finish()
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    camera.emit_active(a,'done');a.lw(9,8,tag.C['variant']);a.i(11,10,9,4);a.branch(4,10,0,'done')
    a.li(10,1);a.r(4,10,9,10);a.sw(10,29,0x300)
    a.li(16,STATE);a.lw(9,16);a.li(10,MAGIC);a.branch(5,9,10,'done')
    for off in (C['manager'],C['count']):
        a.lw(9,16,off);a.lw(10,8,off);a.branch(5,9,10,'done')
    a.li(17,scene.STATE);a.lw(9,17);a.li(10,scene.SCENE_MAGIC);a.branch(5,9,10,'done')
    a.lw(9,17,scene.S['retiring']);a.branch(5,9,0,'done')
    a.lw(18,17,scene.S['phase']);a.i(11,9,18,12);a.branch(4,9,0,'done')
    a.lw(19,17,scene.S['descriptor']);full.pointer(a,19,64,'done')
    a.li(9,assets.BASE);a.r(0x2B,10,19,9);a.branch(5,10,0,'done')
    a.li(9,assets.END-64);a.r(0x2B,10,9,19);a.branch(5,10,0,'done')
    a.lw(9,17,scene.S['ticks']);a.i(11,10,9,1001);a.branch(4,10,0,'done')
    a.li(10,60);a.r(0x19,0,9,10);a.r(0x12,9,0,0);a.li(10,ACTOR_HZ)
    a.r(0x1B,0,9,10);a.r(0x12,9,0,0);a.sw(9,29,0x304)
    a.move(20,0)
    a.label('role');a.r(0,8,0,20,2);a.r(0x21,8,19,8)
    a.lw(10,8,4);a.branch(4,10,0,'next_role')
    a.lw(10,8,16);a.lw(11,8,44);a.i(11,9,11,1001);a.branch(4,9,0,'next_role')
    a.r(0x2B,9,11,10);a.branch(5,9,0,'next_role')
    a.lw(9,29,0x304);a.r(0x21,10,10,9);a.r(0x2B,9,11,10);a.branch(4,9,0,'frame_ready');a.move(10,11)
    a.label('frame_ready');a.sw(10,29,0x308)
    a.r(0,8,0,20,4);a.li(9,ROWS);a.r(0x21,21,8,9)
    a.lw(9,21,R['phase']);a.branch(4,9,18,'same_phase')
    a.li(10,0xFFFFFFFF);a.branch(4,9,10,'new_phase');a.r(0x2B,10,18,9);a.branch(5,10,0,'next_role')
    a.label('new_phase');a.li(9,0xFFFFFFFF);a.jump('previous_ready')
    a.label('same_phase');a.lw(9,21,R['frame']);a.lw(10,29,0x308);a.r(0x2B,10,9,10);a.branch(4,10,0,'next_role')
    a.label('previous_ready');a.sw(9,29,0x30C)
    # Authenticate the actor and its loaded model before native bone reads.
    a.r(0,8,0,20,9);a.li(9,scene.ROWS);a.r(0x21,23,8,9)
    a.lw(10,23,scene.R['actor']);full.pointer(a,10,0x1600,'next_role')
    a.lw(8,23,scene.R['index']);a.lw(9,16,C['count']);a.r(0x2B,9,8,9);a.branch(4,9,0,'next_role')
    a.lw(9,10);a.branch(5,8,9,'next_role');a.r(0,8,0,8,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9)
    a.lw(8,8);a.branch(5,8,10,'next_role');a.lw(8,10,12);a.lw(9,23,scene.R['model_id']);a.branch(5,8,9,'next_role')
    a.lw(22,23,scene.R['model']);full.pointer(a,22,0x1700,'next_role')
    a.lw(8,23,scene.R['model_id']);a.i(11,9,8,12);a.branch(4,9,0,'next_role')
    a.lw(9,22,16);a.branch(5,9,8,'next_role');a.r(0,9,0,8,2);a.li(10,core.MODELS);a.r(0x21,9,9,10)
    a.lw(9,9);a.branch(5,9,22,'next_role');a.lw(9,22,12);a.lw(10,23,scene.R['character']);a.branch(5,9,10,'next_role')
    for off in (4,8):a.lw(9,22,off);a.li(10,1);a.branch(5,9,10,'next_role')
    a.lw(10,22,3436+4*3);full.pointer(a,10,80,'next_role')
    for off in (64,68,72):
        a.lw(8,10,off);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,'next_role')
    a.lw(4,22,16);a.li(5,3);a.addiu(6,29,0x320);a.call(A(0x2058E0))
    a.sw(18,21,R['phase']);a.lw(9,29,0x308);a.sw(9,21,R['frame'])
    a.li(21,TABLE);a.move(23,0)
    a.label('cue');a.lw(8,21);a.lw(9,29,0x300);a.r(0x24,8,8,9);a.branch(4,8,0,'next_cue')
    a.lw(8,21,4);a.branch(5,8,18,'next_cue');a.lw(8,21,8);a.branch(5,8,20,'next_cue')
    a.lw(10,21,12);a.lw(9,29,0x308);a.r(0x2B,8,9,10);a.branch(5,8,0,'next_cue')
    a.lw(9,29,0x30C);a.li(8,0xFFFFFFFF);a.branch(4,9,8,'play')
    a.r(0x2B,8,9,10);a.branch(4,8,0,'next_cue')
    a.label('play');a.lw(8,21,20);a.r(2,9,0,8,16);a.branch(4,9,0,'sound')
    a.r(2,5,0,8,8);a.i(12,5,5,255);a.move(4,20)
    # Derived combos keep the native attacker's cue clock, but their contact
    # occurs on our independently placed victim. Native opening cues retain
    # their original encoded owner/bone; positional sound remains the attacker.
    a.lw(9,19,28);a.i(12,9,9,assets.CUSTOM_FINISHER);a.branch(4,9,0,'impact_ready')
    a.li(4,2);a.li(5,17)
    a.label('impact_ready');a.call(effects.IMPACT)
    a.label('sound');a.lw(6,21,16);a.li(9,21);a.branch(5,6,9,'sound_params')
    a.li(4,4);a.call(A(0x1252D8));a.branch(4,2,0,'next_cue')
    a.li(4,4);a.li(5,21);a.call(A(0x1251E8));a.branch(5,2,0,'next_cue')
    a.lw(6,21,16)
    a.label('sound_params');a.lw(8,21,20);a.i(12,8,8,255);a.branch(4,8,0,'request')
    a.lw(10,22,2332);a.branch(4,10,0,'request');full.pointer(a,10,20,'next_cue')
    a.lw(9,10,16);a.i(12,9,9,0x8000);a.branch(4,9,0,'request');a.lw(6,21,20);a.i(12,6,6,255)
    a.label('request');a.addiu(4,29,0x320);a.move(5,0);fp.fconst(a,12,200.);fp.fconst(a,13,1500.);a.call(SOUND)
    a.branch(4,2,0,'next_cue')
    a.lw(8,16,C['played']);a.addiu(8,8,1);a.sw(8,16,C['played'])
    a.label('next_cue');a.addiu(21,21,24);a.addiu(23,23,1);a.li(8,count);a.branch(5,23,8,'cue')
    a.label('next_role');a.addiu(20,20,1);a.li(8,3);a.branch(5,20,8,'role')
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert len(data)<=TABLE-TICK,len(data);return data


def pieces(pack=None):
    rows=cue_rows(pack)
    data=b''.join(struct.pack('<6I',*r)for r in rows)
    result=[(RESET,reset_code(bool(pack))),(TICK,tick_code(len(rows),bool(pack)))]
    if data:result.append((TABLE,data))
    result.append((STATE,bytes(END-STATE)))
    result.extend(deferred.pieces())
    if pack:
        import tag_rush_voices
        result.extend(tag_rush_voices.pieces())
    result.sort()
    assert all(p+len(b)<=q for (p,b),(q,_)in zip(result,result[1:]))
    return result


def installation(pack=None):
    import tag_rush_voices
    mutable=[(STATE,END),(deferred.STATE,deferred.END)]+([(tag_rush_voices.STATE,tag_rush_voices.END)] if pack else [])
    return dict(blocks=pieces(pack),mutable_ranges=mutable,cue_count=len(cue_rows(pack)),
                usable=False,limitations=['Global cue timing is native-derived; rendered/audio playback still needs a live check.'])
