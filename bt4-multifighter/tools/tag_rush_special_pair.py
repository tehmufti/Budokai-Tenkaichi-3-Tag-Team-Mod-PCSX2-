"""Early Goku/Piccolo's native restraint and Special Beam Cannon tag.

The restraining actor and victim use Spopovich's actual matched ultimate
animations as their lower-body base. An authored upper-body acquisition and
struggle accompanies the victim-relative full-nelson grip. No substitute
actor, donor attack state or donor voice is created.
"""
import math
import struct

NAME = 'early_goku_piccolo'
VARIANT = 4
GOKU, PICCOLO = 0, 22
try:
    import bt4_resources
except ImportError:
    DONOR = 158
else:
    # B14 moves Spopovich to194;158 is Vegito Blue, not a restraint donor.
    DONOR = 194
BASE, END = 0x06E60000, 0x06E7B000
ALIGN_BODY, ALIGN_END = END, 0x06E7C000
RESERVATION_END = 0x06E80000
TABLE_OFFSET, COUNT_OFFSET = 0xB8, 0xBC
RESTRAIN = 256
SOURCE_FRAMES = {355:107,356:253,360:107,361:253}
# Native355 is the curled flying entry, not the upright restraint, and356
# stays curled/tumbling until it unfolds at frame12. The opening plays the
# matched356/361 samples from that unfold at native speed: the holder arrives
# upright into the hold while the victim shows the native grab reaction.
# Contiguous matched hold samples then continue through the tightening grip,
# aim and beam. No loop, stretch or backward jump.
SEGMENTS = ((356,361,12,40,28),(356,361,40,64,24),
            (356,361,64,94,45),(356,361,94,114,30),
            (356,361,114,136,180))
# The scene's staged settle glides the real roots from the dash contact into
# the airborne placement (record settle, in60Hz frames). The native pose
# helper carries the authored pair along that glide from the first tick, so
# the open reach shows instead of the decoded restraint start.
SETTLE_TICKS = 8
APPROACH_FRAMES = 2*SETTLE_TICKS


def matches(first, second):
    return (first,second) in ((GOKU,PICCOLO),(PICCOLO,GOKU))


def _decode(raw, animation):
    """Normalize only the native signed -4-frame preroll for private crops.

    These leading rotation keys precede frame0; replacing their time with0
    preserves all visible samples, since the actual frame0 key follows them.
    Every other decreasing/out-of-range key remains a hard source error.
    """
    from model_animations import AnimationClip
    data=bytearray(raw)
    if len(data)<148 or struct.unpack_from('<H',data,2)[0]!=SOURCE_FRAMES[animation]:
        raise ValueError('Special tag restraint duration changed')
    for bone in range(71):
        off=struct.unpack_from('<H',data,6+bone*2)[0]*4
        if not off:continue
        if not 148<=off<=len(data)-4:raise ValueError('Invalid restraint channel')
        flags,count=struct.unpack_from('<HH',data,off)
        if flags&1 and count>1:
            at=off+4+count*8
            if at+count*2>len(data):raise ValueError('Truncated restraint keys')
            times=struct.unpack_from('<%dH'%count,data,at)
            if times[0]==65532:
                if times[1]!=0:raise ValueError('Restraint preroll has no frame0')
                struct.pack_into('<H',data,at,0)
    clip=AnimationClip.from_decoded(animation,data)
    if len(clip.tracks)<40:raise ValueError('Incomplete restraint skeleton')
    return clip


def read_sources(iso):
    import model_assets as model
    from model_animations import decompress_animation
    bank=model.read_animation_bank(iso,DONOR)
    return {i:_decode(decompress_animation(model.package_entry(bank,i+1)),i)
            for i in SOURCE_FRAMES}


AUTHORED_HOLDER = frozenset((3,16,17,18,32,46,47))
AUTHORED_VICTIM = frozenset((0,3,16,17,18,19,20,21,32,33,34,35,46,47))
# The opening keeps the victim's native grab reaction but pins its root: the
# matched native361 turns the victim to face its attacker, which showed as the
# held opponent turning around at the hold seam. The pinned root matches the
# authored hold phases, so one facing (back to Goku) lasts from contact on.
OPENING_VICTIM = frozenset((0,))


def upper_body(role,phase,time,frames):
    """Continuous acquisition, tightening, struggle and bracing; no root travel.

    This conditions the borrowed source crop before retargeting. The native
    authored-pose helper replaces its upper body with the reviewed acquisition
    and exact user grip; the airborne lower body keeps the contiguous donor
    motion. No runtime arm fitting is involved.
    """
    from ground_clips import qaxis,qmul
    t=max(0.,min(1.,time/frames));elapsed=sum(x[4]for x in SEGMENTS[:phase])+time
    grip=min(1.,max(0.,elapsed-APPROACH_FRAMES)/28.);grip=grip*grip*(3.-2.*grip)
    # One restrained attempt to pull free, then smaller continuous breathing.
    struggle=(math.sin((elapsed-64.)*math.pi/27.)*math.sin(min(1.,max(0.,(elapsed-64.)/80.))*math.pi)
              if 64.<elapsed<144. else 0.)
    breathe=math.sin(elapsed*math.pi/55.)
    axis=lambda x=0.,y=0.,z=0.:qmul(qmul(qaxis((1,0,0),x),qaxis((0,1,0),y)),qaxis((0,0,1),z))
    if role==0:
        return {3:axis(5.+3.*grip+.7*breathe,0.,struggle*1.2),16:axis(-3.,0.,-.5*struggle),
                17:axis(1.+.4*breathe),18:axis(0.,-8.-22.*grip,-4.),32:axis(0.,8.+22.*grip,4.),
                46:axis(-4.,0.,-struggle*.5),47:axis(1.,0.,struggle*.3)}
    lift=8.+12.*grip
    return {0:axis(),3:axis(4.+grip*4.,struggle*2.,struggle*2.),16:axis(-3.+breathe*.8,0.,-struggle),
            17:axis(-2.,struggle,-struggle*.8),18:axis(0.,-5.+20.*grip,15.*grip),32:axis(0.,5.-20.*grip,-15.*grip),
            19:axis(0.,-8.,lift),20:axis(0.,-65.-grip*10.,5.),21:axis(0.,0.,-15.),
            33:axis(0.,8.,-lift),34:axis(0.,65.+grip*10.,-5.),35:axis(0.,0.,15.),
            46:axis(5.+grip*3.,struggle*3.,struggle),47:axis(3.,-struggle*2.)}


def _crop(clip,start,end,frames,shift=None,*,role=None,phase=0):
    from model_animations import BoneTransform,AnimationClip
    from tag_rush_choreography import _encode
    if not 0<=start<end<=clip.frame_count or not 1<=frames<=1000:
        raise ValueError('Invalid special restraint crop')
    tracks={}
    for track in clip.tracks:
        bone=track.bone_id
        #54 is the native auxiliary Yamu marker, not a humanoid body joint.
        if bone>52:continue
        if bone==1:raise ValueError('Restraint uses a native motion-root channel')
        authored=(AUTHORED_HOLDER if role==0 else AUTHORED_VICTIM) if role is not None else ()
        if phase==0 and role==2:authored=OPENING_VICTIM
        times=sorted({start,end}|{t for t in track.times if start<=t<=end}|
                     ({start+(end-start)*t/frames for t in range(0,frames+1,6)} if bone in authored else set()))
        keys=[]
        for source_time in times:
            time=round((source_time-start)*frames/(end-start))
            value=track.evaluate(source_time);translation=value.translation
            if translation is not None:
                if bone not in (0,2,31,45,52):raise ValueError('Unreviewed restraint translation')
                if bone==0:translation=(0.,0.,0.)
                elif shift is not None and bone in (2,52):
                    translation=tuple(x-y for x,y in zip(translation,shift))
            rotation=upper_body(role,phase,time,frames)[bone] if bone in authored else value.rotation
            value=BoneTransform(translation,rotation)
            if keys and keys[-1][0]==time:keys[-1]=(time,value)
            else:keys.append((time,value))
        tracks[bone]=keys
    raw=_encode(frames,tracks)
    AnimationClip.from_decoded(0,raw)
    return raw


def timeline():
    from tag_rush_assets import Phase,ClipSource,CUSTOM_FINISHER,FINISHER,BEAM_PARTNER,OWN_CLASH_POSE,CHARGE_BEAM
    names=('Close in','Secure the hold','Hold them still','Take aim','Special Beam Cannon')
    result=[]
    for index,(lead,victim,start,end,frames) in enumerate(SEGMENTS):
        roles=(ClipSource(DONOR,1100+index),ClipSource(101,1000),ClipSource(DONOR,1110+index))
        flags=CUSTOM_FINISHER|RESTRAIN
        if index==4:flags|=FINISHER|BEAM_PARTNER|OWN_CLASH_POSE|CHARGE_BEAM
        result.append(Phase(names[index],frames,roles,(frames,min(frames,180),frames),flags))
    return tuple(result)


def records():
    # The native hold helper applies the user's edited pair placement.
    # Native24E2B0 adds PI to the actor yaw before constructing model roots.
    # The pair's meshes face local-Z negative; the 180-degree stage turn
    # below cancels that native
    # half-turn so both face Piccolo in the negative-Z firing lane. Staging
    # metadata is DEGREES; math.pi here was only a 3.14-degree turn in game.
    # 180 degrees preserves the edited pair's local pose and placement while
    # making the native rendered root face the firing lane correctly.
    goku=(0.,0.,0.,180.);piccolo=(0.,0.,-58.,0.);victim=(0.,0.,0.,180.)
    # Phase0 settles both real roots into the hold instead of cutting there.
    return [(1,13,0,SETTLE_TICKS,goku,piccolo,victim),
            (1,13,0,0,goku,piccolo,victim),
            # Piccolo's native charge starts once in phase4. Keep the earlier
            # view on the secure hold instead of replaying his charge closeup.
            (1,13,0,0,goku,piccolo,victim),
            (1,13,0,0,goku,piccolo,victim),
            (1,15,90,0,goku,piccolo,victim)]


def build(iso, *, base=BASE,end=END):
    import hashlib
    import tag_rush_assets as assets
    if base%16 or not BASE<=base<end<=END:raise ValueError('Invalid special tag asset bank')
    clips=read_sources(iso);binding=assets.read_skeleton(iso,DONOR)
    bind2=next(row['translation'] for row in binding['rows'] if row['bone']==2)
    reference=clips[356].evaluate(24)[2].translation
    shift=tuple(a-b for a,b in zip(reference,bind2))
    decoded={}
    for index,(lead,victim,start,stop,frames) in enumerate(SEGMENTS):
        # The opening keeps the native unfold and grab reaction; only the
        # victim's root facing is pinned there.
        roles=(None,2) if index==0 else (0,2)
        decoded[assets.ClipSource(DONOR,1100+index)]=_crop(clips[lead],start,stop,frames,shift,role=roles[0],phase=index)
        decoded[assets.ClipSource(DONOR,1110+index)]=_crop(clips[victim],start,stop,frames,role=roles[1],phase=index)
    data=bytearray();pointers={};provenance=[]
    for source,raw in decoded.items():
        data.extend(bytes((-len(data))%16));address=base+len(data);packed=assets.literal_pack(raw)
        data.extend(packed);pointers[source]=address
        provenance.append(dict(character=source.character,animation=source.animation,mesh_entry=None,
            frames=struct.unpack_from('<H',raw,2)[0],decoded_sha256=hashlib.sha256(raw).hexdigest(),
            address=address,size=len(packed),special_pair=True))
    data.extend(bytes((-len(data))%16));model=base+len(data);nodes=model+0x920
    height=nodes+len(binding['rows'])*64
    donor=bytearray(0x920);struct.pack_into('<I',donor,24,model+0x100)
    struct.pack_into('<f',donor,0x174,binding['height']);struct.pack_into('<I',donor,68,nodes)
    struct.pack_into('<I',donor,2332,height);data.extend(donor)
    data.extend(b''.join(row['header'] for row in binding['rows']))
    data.extend(struct.pack('<If',0,binding['height']))
    if base+len(data)>end:raise ValueError('Special tag restraint exceeds reserved storage')
    return dict(blocks=[(base,bytes(data))],pointers=pointers,clips=provenance,
                donor_model=model,bytes_used=len(data),reviewed=True)
