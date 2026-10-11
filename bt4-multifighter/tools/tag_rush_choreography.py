"""Local finisher recipes assembled from reviewed native humanoid poses.

Only the new finishers remove horizontal root travel. The Sadistic Dance
attackers retain their visible poses; an invisible contact mark lifts the
victim during the partner entrance. The victim's long prone entrance wait
recovers into the next native hurt pose. All limb rotations and vertical body
motion come from the selected disc, without dispatching native attack actions.
"""
import hashlib
import math
import struct

REVISION = 15
VARIANTS = ('two_ki','two_melee','mixed_ki_lead','mixed_ki_partner')
SOURCE_FRAMES = {0:59,43:39,55:11,57:12,58:16,61:12,63:10,
                 162:24,164:24,174:112,175:112,198:19}
# Native hit-stun192 selects162..165 in its airborne posture. Strong hurt
# actions203/204 select174/175. Fall217 selects198/199. The former45/46/51
# candidates belong to movement handlers and must never be victim reactions.
HURT_SOURCES = (162,164)
BEAM_HURT_SOURCES = (174,175)
HURT_PEAK = {162:8,164:8,174:10,175:10}
def hit_reactions(frames,contacts,*,sustained=False):
    """Native hurt poses peak exactly when the corresponding strike lands."""
    rows=[];cursor=0
    for index,contact in enumerate(contacts):
        source=(BEAM_HURT_SOURCES if sustained else HURT_SOURCES)[index%2]
        peak=HURT_PEAK[source]
        rest=24 if sustained else SOURCE_FRAMES[source]
        start=contact-4
        if start>cursor:rows.append((source,rest,rest,start-cursor))
        rows.append((source,rest,peak,4));cursor=contact
        next_start=contacts[index+1]-4 if index+1<len(contacts) else frames
        release=min(14,frames-cursor,next_start-cursor)
        if release:rows.append((source,peak,rest,release));cursor+=release
    if cursor<frames:
        source=BEAM_HURT_SOURCES[0] if sustained else HURT_SOURCES[0]
        rest=24 if sustained else SOURCE_FRAMES[source]
        rows.append((source,rest,rest,frames-cursor))
    return tuple(rows)


DERIVED = {
    'idle': (1000, 180, ((0,0,59,180),)),
    'recoil': (1002,144, hit_reactions(144,(18,42,66,90,114,138))),
    'air_fall': (1003,144, ((198,0,19,24),(198,0,19,120))),
    'duo_lead': (1004,144, tuple((i,0,SOURCE_FRAMES[i] if i else 0,24) for i in (55,0,58,0,61,0))),
    'duo_partner': (1005,144, tuple((i,0,SOURCE_FRAMES[i] if i else 0,24) for i in (0,57,0,55,0,63))),
    'solo_combo': (1006,96, tuple((i,0,SOURCE_FRAMES[i],24) for i in (55,57,55,58))),
    'downkick': (1007,36, ((61,0,12,18),(63,0,10,18))),
    'fall': (1008,36, hit_reactions(36,(12,30))),
    # One beam impact, then a sustained native hurt pose until the director
    # hands the victim to the game's fall/recovery action at the ending.
    'beam_reaction': (1009,180, hit_reactions(180,(94,),sustained=True)),
    'retreat': (1010,180, ((43,0,39,24),(0,0,59,156))),
}
BEAM_START = 90
BEAM_FRAMES = 180
CHARGE_CLOSEUP = 60
MAX_PHASES = 12
INDEPENDENT = 1
AIR_HEIGHT = 160.0
MIN_CLEARANCE = 60.0
RECORD_SIZE = 64
# Native ordinary-strike event0x8 opens contact at these source frames. The
# event itself is stripped; retiming its pose to our explicit impact keeps
# both the limb extension and victim reaction on one deterministic clock.
STRIKE_CONTACT = {55:6,57:6,58:7,61:7,63:4}
# mode, shot, beam start, optional settle duration, then role-local XYZ/yaw.
ZERO = (0.,0.,0.,0.)
# Native1D7418 writes facing=(sin(yaw),0,cos(yaw)); yaw0 faces +Z.
# The mesh preview's authored local -Z axis is not the actor-facing axis.
OPPOSED = ((0.,0.,42.,180.),(0.,0.,-42.,0.),ZERO)
CONTACT = ((0.,0.,8.,180.),(0.,0.,-8.,0.),(0.,0.,0.,90.))


def records(variant):
    native = [(0,0,0,0, ZERO,ZERO,ZERO)]*4
    if variant=='two_ki':
        return native+[(1,1,0,0,*OPPOSED),(1,2,BEAM_START,0,*OPPOSED)]
    if variant=='two_melee':
        return native+[(1,3,0,0,*CONTACT),(1,4,0,0,*CONTACT),
                       (1,5,0,24,(0.,0.,14.,180.),(0.,0.,-14.,180.),(0.,48.,-36.,0.))]
    if variant not in ('mixed_ki_lead','mixed_ki_partner'):raise ValueError(variant)
    ki = 0 if variant=='mixed_ki_lead' else 1
    close = [(0.,0.,8.,180.),(0.,0.,8.,180.),ZERO]
    close[ki]=(0.,0.,42.,180.)
    # The melee partner physically retreats behind the camera's near plane;
    # its real body remains present but does not block the beam composition.
    finish=list(close);finish[1-ki]=(155.,-12.,-110.,127.281)
    return native+[(1,3,0,0,*close),(1,4,0,0,*close),(1,6,BEAM_START,0,*finish)]


def pack_records(variants,base):
    names=tuple(variants)
    if len(names)!=len(VARIANTS) or set(names)!=set(VARIANTS):
        raise ValueError('Tag choreography requires the four reviewed variants exactly once')
    # This table is indexed by the runtime variant enum. JSON cache key sorting
    # must never reorder physical entries or their embedded addresses.
    data=bytearray(8*len(VARIANTS));rows={}
    for index,name in enumerate(VARIANTS):
        entries=records(name);at=base+len(data)
        struct.pack_into('<2I',data,index*8,at,len(entries))
        for row in entries:data.extend(struct.pack('<4I12f',*row[:4],*(v for p in row[4:] for v in p)))
        rows[name]=dict(address=at,count=len(entries),records=entries)
    return bytes(data),dict(table_address=base,variants=rows,record_size=RECORD_SIZE,
                           revision=REVISION,reviewed=True)


def read_sources(iso):
    import model_assets as model
    from model_animations import decompress_animation,AnimationClip
    bank=model.read_animation_bank(iso,101);out={}
    for animation,frames in SOURCE_FRAMES.items():
        raw=decompress_animation(model.package_entry(bank,animation+1))
        clip=AnimationClip.from_decoded(animation,raw)
        if clip.frame_count!=frames or len(clip.tracks)<40:
            raise ValueError(f'Unreviewed grounded tag pose 101/{animation}')
        if animation in STRIKE_CONTACT:
            count=struct.unpack_from('<H',raw)[0]>>8
            contacts=[struct.unpack_from('<I',raw,156+16*i)[0] for i in range(count)
                      if struct.unpack_from('<Q',raw,148+16*i)[0]&8]
            if contacts!=[STRIKE_CONTACT[animation]]:
                raise ValueError(f'Unreviewed native strike contact 101/{animation}')
        out[animation]=raw
    return out


def _encode(frames,tracks):
    from ground_clips import encode_quat
    data=bytearray(148);struct.pack_into('<HH',data,0,0,frames)
    for bone,keys in sorted(tracks.items()):
        data.extend(bytes((-len(data))%4));struct.pack_into('<H',data,6+bone*2,len(data)//4)
        translated=keys[0][1].translation is not None
        # Constant channels remain single-key native channels.
        if all(value==keys[0][1] for _,value in keys):keys=keys[:1]
        data.extend(struct.pack('<HH',0 if translated else 1,len(keys)))
        if translated:
            for time,value in keys:data.extend(struct.pack('<3fIQ',*value.translation,time,encode_quat(value.rotation)))
        else:
            for _,value in keys:data.extend(struct.pack('<Q',encode_quat(value.rotation)))
            if len(keys)>1:data.extend(struct.pack('<%dH'%len(keys),*(t for t,_ in keys)))
    return bytes(data)


def stabilize_opening_victim(raw_launch,raw_followup):
    """Recover the whole body after impact without changing native contact.

    Original357 holds an arched horizontal body through68. Keep its native
    compressed keys through28 (the first key after the requested24-frame
    follow-through), so the hit and every earlier interpolated pose are exact.
    Blend all body rotations into359's airborne hurt pose by44, then retain
    its small moving recoil until the partner entrance. Root/contact channels,
    every translation and the original event records remain byte-for-byte.
    """
    from model_animations import AnimationClip,slerp
    from ground_clips import encode_quat
    clip=AnimationClip.from_decoded(357,raw_launch)
    hurt=AnimationClip.from_decoded(359,raw_followup)
    tracks={t.bone_id:t for t in clip.tracks}
    following={t.bone_id:t for t in hurt.tracks}
    if (clip.frame_count!=68 or hurt.frame_count!=149 or len(tracks)<40
            or set(tracks)!=set(following) or not {0,2,3,17,52}<=set(tracks)):
        raise ValueError('Unreviewed native opening victim pose')
    data=bytearray(raw_launch)
    for bone,track in tracks.items():
        if bone in (0,2,52):continue
        target=following[bone]
        offset=struct.unpack_from('<H',raw_launch,6+2*bone)[0]*4
        flags,count=struct.unpack_from('<HH',raw_launch,offset)
        if not flags&1:
            raise ValueError('Unreviewed translated opening victim body channel')
        # Original prefix quaternions are copied, not decoded and requantized.
        # Constant accessory channels need no replacement at all.
        if all(k==track.keys[0] for k in track.keys) and all(k==track.keys[0] for k in target.keys):continue
        if 28 not in track.times:raise ValueError('Opening victim follow-through key changed')
        prefix=[(t,raw_launch[offset+4+8*i:offset+12+8*i]) for i,t in enumerate(track.times) if t<=28]
        start=track.evaluate(28).rotation
        for frame in range(29,69):
            u=min((frame-28.)/16.,1.);blend=u*u*(3.-2.*u)
            sample=0. if frame<=44 else 5.*math.sin(math.pi*(frame-44.)/24.)**2
            rotation=slerp(start,target.evaluate(sample).rotation,blend)
            prefix.append((frame,struct.pack('<Q',encode_quat(rotation))))
        data.extend(bytes((-len(data))%4))
        struct.pack_into('<H',data,6+2*bone,len(data)//4)
        data.extend(struct.pack('<HH',flags,len(prefix)))
        data.extend(b''.join(value for _,value in prefix))
        data.extend(struct.pack('<%dH'%len(prefix),*(frame for frame,_ in prefix)))
    if len(data)>0xC000:raise ValueError('Opening victim pose exceeds native decode scratch')
    AnimationClip.from_decoded(357,data)
    return bytes(data)


def recover_entrance_victim(raw_flat,raw_followup,raw_launch):
    """Recover from the launch while the partner enters, then join native359.

    Native358 holds the body horizontal for its entire99-frame pause. Begin
    at the preceding corrected launch pose and keep its contact/root channels,
    then blend the limbs into359's initial airborne hurt pose over24 frames.
    A small forward/back sample avoids a frozen hold and ends at359 frame0.
    These are pose samples only; neither source's gameplay events are copied.
    """
    from model_animations import AnimationClip,BoneTransform,slerp
    flat=AnimationClip.from_decoded(358,raw_flat)
    hurt=AnimationClip.from_decoded(359,raw_followup)
    launch=AnimationClip.from_decoded(357,raw_launch)
    first={t.bone_id:t for t in flat.tracks};following={t.bone_id:t for t in hurt.tracks}
    if (flat.frame_count!=99 or hurt.frame_count!=149 or set(first)!=set(following)
            or launch.frame_count!=68 or set(first)!={t.bone_id for t in launch.tracks}
            or len(first)<40 or not {0,2,3,17,52}<=set(first)):
        raise ValueError('Unreviewed native entrance victim pose pair')
    launched=launch.evaluate(launch.frame_count)
    frames=flat.frame_count;tracks={bone:[] for bone in first}
    for frame in range(0,frames+1,3):
        blend=min(frame/24.,1.);blend=blend*blend*(3.-2.*blend)
        source_frame=0. if frame<=24 else 5.*math.sin(math.pi*(frame-24.)/(frames-24.))**2
        for bone,track in first.items():
            native=track.evaluate(frame);target=following[bone].evaluate(source_frame)
            rotation=(native.rotation if bone in (0,2,52) else
                      slerp(launched[bone].rotation,target.rotation,blend))
            tracks[bone].append((frame,BoneTransform(native.translation,rotation)))
    data=_encode(frames,tracks)
    if len(data)>0xC000:raise ValueError('Entrance victim pose exceeds native decode scratch')
    AnimationClip.from_decoded(358,data)
    return data


def raise_entrance_contact(raw,phase):
    """Lift only the victim mark during the partner's preserved native shot.

    Native353's contact bone52 has no translation, pinning victim hips to the
    origin below its high camera. Move24 units up and100 units back over12
    frames, placing the victim behind this shot instead of in its foreground.
    Native354's first paired hit is at58: settle back by its original key20,
    retaining all later compressed keys exactly. The real lead's native
    retarget supplies height scaling; the victim's height never sets this lift.
    No visible attacker bone, event, camera or permanent actor offset changes.
    """
    from model_animations import AnimationClip
    if phase not in (1,2):raise ValueError('Unexpected entrance contact phase')
    animation,frames=(353,99) if phase==1 else (354,149)
    clip=AnimationClip.from_decoded(animation,raw)
    track=next((t for t in clip.tracks if t.bone_id==52),None)
    if clip.frame_count!=frames or track is None:
        raise ValueError('Unreviewed entrance contact clip')
    offset=struct.unpack_from('<H',raw,6+52*2)[0]*4
    flags,count=struct.unpack_from('<HH',raw,offset)
    if bool(flags&1)!=(phase==1) or any(k.rotation!=track.keys[0].rotation for k in track.keys):
        raise ValueError('Unreviewed entrance contact channel')
    quaternion=raw[offset+4:offset+12] if flags&1 else raw[offset+20:offset+28]
    keys=[]
    if phase==1:
        for frame in (*range(13),99):
            t=min(frame/12.,1.);blend=t*t*(3.-2.*t)
            keys.append(struct.pack('<3fI',0.,-24.*blend,-100.*blend,frame)+quaternion)
    else:
        if 20 not in track.times:raise ValueError('Paired contact recovery key changed')
        for frame in range(20):
            x,y,z=track.evaluate(frame).translation;t=frame/20.
            blend=1.-t*t*(3.-2.*t)
            keys.append(struct.pack('<3fI',x,y-24.*blend,z-100.*blend,frame)+quaternion)
        for index,frame in enumerate(track.times):
            if frame>=20:keys.append(raw[offset+4+24*index:offset+28+24*index])
    data=bytearray(raw);data.extend(bytes((-len(data))%4))
    struct.pack_into('<H',data,6+52*2,len(data)//4)
    data.extend(struct.pack('<HH',flags&~1,len(keys)));data.extend(b''.join(keys))
    if len(data)>0xC000:raise ValueError('Entrance contact exceeds native decode scratch')
    AnimationClip.from_decoded(animation,data)
    return bytes(data)


def derive(raw_sources,name):
    from model_animations import AnimationClip,BoneTransform,slerp
    _,frames,segments=DERIVED[name]
    clips={i:AnimationClip.from_decoded(i,raw_sources[i]) for i,_,_,_ in segments}
    bones=sorted(set.intersection(*(set(t.bone_id for t in clip.tracks) for clip in clips.values())))
    tracks={bone:[] for bone in bones};cursor=0
    for segment,(source,start,end,duration) in enumerate(segments):
        clip=clips[source];lookup={t.bone_id:t for t in clip.tracks}
        # Hurt channels deliberately peak on contact rather than blending
        # four frames after the audio/impact event.
        blend=4 if segment and name not in ('recoil','fall','beam_reaction','air_fall') else 0
        for bone in bones:
            track=lookup[bone];times={0,duration}
            hit=STRIKE_CONTACT.get(source) if name in ('duo_lead','duo_partner','solo_combo','downkick') else None
            contact=18 if duration==24 else 12
            if end!=start:
                if hit is None:
                    times.update(blend+round((t-start)*(duration-blend)/(end-start)) for t in track.times if min(start,end)<=t<=max(start,end))
                else:
                    times.add(contact)
                    times.update(round(blend+(t-start)*(contact-blend)/(hit-start) if t<=hit else
                                       contact+(t-hit)*(duration-contact)/(end-hit))
                                 for t in track.times if start<=t<=end)
            if blend:times.update((blend,))
            previous=tracks[bone][-1][1] if tracks[bone] else None
            for t in sorted(times):
                if hit is None:source_frame=start+max(0,t-blend)*(end-start)/(duration-blend)
                elif t<=contact:source_frame=start+max(0,t-blend)*(hit-start)/(contact-blend)
                else:source_frame=hit+(t-contact)*(end-hit)/(duration-contact)
                value=track.evaluate(source_frame)
                translation=value.translation
                # Bone0 owns native battlefield travel. Lock its XYZ to the
                # native origin; bone2 retains all authored vertical motion.
                if translation is not None:
                    if bone==0:translation=(0.,0.,0.)
                    elif bone==2:translation=(0.,translation[1],0.)
                if previous is not None and (translation is None)!=(previous.translation is None):
                    # Mixed channel types resolve through the zero bind offset.
                    translation=(0.,0.,0.) if translation is None else translation
                    previous=BoneTransform(previous.translation or (0.,0.,0.),previous.rotation)
                value=BoneTransform(translation,value.rotation)
                if blend and t<blend:
                    fraction=t/blend
                    translation=(None if value.translation is None else tuple(
                        x+(y-x)*fraction for x,y in zip(previous.translation,value.translation)))
                    value=BoneTransform(translation,slerp(previous.rotation,value.rotation,fraction))
                absolute=cursor+t
                if tracks[bone] and tracks[bone][-1][0]==absolute:tracks[bone][-1]=(absolute,value)
                else:tracks[bone].append((absolute,value))
        cursor+=duration
    # Channel presence may vary between source clips. A translated channel
    # must use one format throughout; rotation-only binds are zero offsets.
    for bone,keys in tracks.items():
        if any(v.translation is not None for _,v in keys):
            tracks[bone]=[(t,BoneTransform(v.translation or (0.,0.,0.),v.rotation)) for t,v in keys]
    data=_encode(frames,tracks)
    AnimationClip.from_decoded(DERIVED[name][0],data)
    if len(data)>0xC000:raise ValueError('Grounded tag pose exceeds native decode scratch')
    return data


def prepared(iso):
    raw=read_sources(iso);out={};provenance={}
    for name,(animation,frames,recipe) in DERIVED.items():
        out[animation]=derive(raw,name)
        provenance[animation]=dict(recipe=name,source_frames=frames,revision=REVISION,
            source_sha256={i:hashlib.sha256(raw[i]).hexdigest() for i,_,_,_ in recipe},
            segments=recipe,decoded_sha256=hashlib.sha256(out[animation]).hexdigest())
    return out,provenance
