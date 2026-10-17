"""BT4-only native directors for paired beam attacks.

The same three real actors, tag consent, native approach and cleanup are used.
Both variants first play the shared native Sadistic Dance opening (its four
phases, cameras and timing, exactly as the other tag attacks); they split off
afterwards. The authored data contain poses and immutable placements, never
game actions. The bank holds authored animation cues and camera paths.
"""
from pathlib import Path
import hashlib
import json
import math
import struct
import zlib

BASE,DATA,END=0x06ED0000,0x06EE0000,0x06F40000
ROOT_STEP,CAMERA_STEP,ANCHOR,AURA_START,AURA_STOP=BASE,BASE+0x2000,BASE+0x4000,BASE+0x5000,BASE+0x6000
AURA_SIZE=BASE+0x7000
SPLIT,SEPARATE,FX=BASE+0x8000,BASE+0x9000,BASE+0xB000
CODE_END=BASE+0xD000
MAGIC=0x42504731
FLAG=0x200
NAMES=('blue_galick_kamehameha','super_galick_pair')
VARIANTS=(5,6)
TABLE_OFFSETS=(0xC0,0xC8)
# Phases of the shared native opening (tag_rush_assets.OPENING). The paired
# variants split off at exactly the same point as every other tag attack.
INTRO=4
GOKU,VEGETA_BLUE=122,35
VEGETA=VEGETA_BLUE
# Future Trunks (Super), every form: base225, SSJ226, SSJ2 72, Rage149.
TRUNKS=(72,149,225,226)
# The Vegeta whose disc form line reaches Super Saiyan Blue35: base31, SSJ32,
# Super Vegeta33, SSJ2 36, SSG68, Blue35, Evolved113 (no other Vegeta).
VEGETA_LINE=(31,32,33,35,36,68,113)
LEADS=((GOKU,),TRUNKS)
PARTNERS=((VEGETA_BLUE,),VEGETA_LINE)
EDGES=(0,34,62,90,120,138,374,424)
FIRE_FRAME,BURST_FRAME=127,189
SPATIAL_SCALE=172
DASH_PARTICLE_SCALE=.85
DASH_RENDER_SCALE=.256  # Another 20% smaller than the preceding .32 render scale.
DASH_AURA_SCALE=DASH_PARTICLE_SCALE*DASH_RENDER_SCALE
DASH_SIZE_FIELDS=(64,68)
# Captured from the normal L2+Cross dash in the same BT4 test match.
DASH_SOUND=28
BANK=Path(__file__).with_name('tag_rush_blue_motion.bin')
# Guest header: magic, revision, FX schedule pointer, then one table per variant.
TABLES,TABLE_SIZE=DATA+16,48
T=dict(samples=0,phases=4,mode=8,roots=12,camera=24,edges=28,spacing=32,final_yaws=36,root_indices=40)
LANE,GROUND=0,1
# Scene-row words owned by this director (beyond the aura lease at 368..411).
SEP,GROUND_DY,FX_STATE=448,460,464
END_ROTATION,END_FACING=480,496
# Body sampling for the overlap guard: pelvis, chest, head, knees, ankles,
# elbows and wrists. Radii are native units at model scale1.
BODY=((2,2.8),(17,3.),(47,2.4),(10,1.4),(14,1.4),(11,1.2),(15,1.2),(20,1.2),(34,1.2),(21,1.),(35,1.))
CLEARANCE=.35
SEPARATION_DECAY=.97
SEPARATION_LIMIT=24.


def pair(first,second):
    if type(first)is not int or type(second)is not int:return None
    for name,leads,partners in zip(NAMES,LEADS,PARTNERS):
        if first in leads and second in partners or second in leads and first in partners:return name
    return None


def bank():
    raw=BANK.read_bytes()
    if len(raw)>512*1024 or raw[:4]!=b'TTBP':raise ValueError('Invalid local paired-beam bank')
    size=struct.unpack_from('<I',raw,4)[0]
    if not 100<size<32768:raise ValueError('Invalid paired-beam header')
    header=json.loads(raw[8:8+size]);decoder=zlib.decompressobj()
    data=decoder.decompress(raw[8+size:],END-DATA)
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or len(data)>=END-DATA:
        raise ValueError('Paired-beam bank exceeds its reservation')
    if (header['schema'],header['revision'],tuple(header['edges']),header['samples'])!=(1,13,EDGES,213):
        raise ValueError('Paired-beam authoring revision changed')
    if hashlib.sha256(data).hexdigest()!=header['payload_sha256']:
        raise ValueError('Paired-beam motion bank changed')
    return header,data


def _blue_clips():
    import tag_rush_assets as assets
    header,data=bank();result={}
    for row in header['clips']:
        role,phase=row['role'],row['phase'];raw=data[row['offset']:row['offset']+row['size']]
        if not 0<=role<5 or not 0<=phase<7 or hashlib.sha256(raw).hexdigest()!=row['sha256']:
            raise ValueError('Invalid paired-beam clip')
        # Roles3/4 were the retired airborne Trunks/Vegeta draft.
        if role<3:result[assets.ClipSource((122,35,0)[role],1200+role*10+phase)]=raw
    return result


def prepared_clips(iso=None):
    result=_blue_clips()
    if iso is not None:
        import tag_rush_galick_pair as galick
        result.update(galick.prepared_clips(iso))
    return result


def own_timeline(name):
    import tag_rush_assets as assets
    if name not in NAMES:raise ValueError(name)
    if name==NAMES[1]:
        import tag_rush_galick_pair as galick
        return galick.timeline()
    phases=[]
    for i,(start,end) in enumerate(zip(EDGES,EDGES[1:])):
        sources=tuple(assets.ClipSource((122,35,0)[role],1200+role*10+i) for role in range(3))
        flags=assets.CUSTOM_FINISHER|FLAG
        if i==5:flags|=assets.BEAM_LEAD|assets.BEAM_PARTNER|assets.FINISHER|assets.CHARGE_BEAM
        phases.append(assets.Phase(('Pursuit','Bank around','Closing in','Final approach','Take aim',
                                   'Paired beams','Recover')[i],end-start,sources,(end-start,)*3,flags))
    return tuple(phases)


def timeline(name):
    import tag_rush_assets as assets
    return assets.OPENING+own_timeline(name)


def records(name=NAMES[0]):
    native=[(0,0,0,0,(0.,0.,0.,0.),(0.,0.,0.,0.),(0.,0.,0.,0.))]*INTRO
    if name==NAMES[1]:
        import tag_rush_galick_pair as galick
        return native+galick.records()
    return native+[(1,1,FIRE_FRAME if i==5 else 0,BURST_FRAME if i==5 else 0,
             (0.,0.,0.,0.),(0.,0.,0.,0.),(0.,0.,0.,0.)) for i in range(7)]


def burst(name):
    """(timeline phase index, frame) of the single finishing impact."""
    if name==NAMES[1]:
        import tag_rush_galick_pair as galick
        return INTRO+galick.BURST_PHASE,galick.BURST_FRAME
    return INTRO+5,BURST_FRAME


def phase_donors(name,index,pack):
    """Native opening phases keep the ordinary Sadistic Dance donors."""
    return pack['role_donors'] if index<INTRO else pack['bindings'][NAMES.index(name)]


def placements(name,staging):
    return tuple(staging[:INTRO])+((0.,0.,0.,0.),)*(len(timeline(name))-INTRO)


def beam_schedule(name):
    """Per role: (charge, fire, end) in absolute authored source frames."""
    if name==NAMES[1]:
        import tag_rush_galick_pair as galick
        return galick.beam_schedule()
    start=EDGES[5];end=EDGES[6]
    return ((start,start+FIRE_FRAME,end),(start,start+FIRE_FRAME,end))


def charge_cues(name,phase):
    """(role, local frame) of each beam charge that starts in this phase."""
    edges=own_edges(name);local=phase-INTRO
    if not 0<=local<len(edges)-1:return ()
    return tuple((role,charge-edges[local]) for role,(charge,_,_) in enumerate(beam_schedule(name))
                 if edges[local]<=charge<edges[local+1])


def _skeleton_models(iso,characters,data):
    import tag_rush_assets as assets
    models={}
    for character in characters:
        binding=assets.read_skeleton(iso,character)
        data.extend(bytes((-len(data))%16));model=DATA+len(data);nodes=model+0x920
        height=nodes+len(binding['rows'])*64;donor=bytearray(0x920)
        struct.pack_into('<I',donor,24,model+0x100);struct.pack_into('<f',donor,0x174,binding['height'])
        struct.pack_into('<I',donor,68,nodes);struct.pack_into('<I',donor,2332,height)
        data.extend(donor);data.extend(b''.join(row['header'] for row in binding['rows']))
        data.extend(struct.pack('<If',0,binding['height']));models[character]=model
    return models


def build(iso):
    import tag_rush_assets as assets
    import tag_rush_galick_pair as galick
    header,payload=bank();data=bytearray(16+2*TABLE_SIZE);pointers={};clips=[]
    sources=dict(_blue_clips());sources.update(galick.prepared_clips(iso))
    for source,raw in sources.items():
        data.extend(bytes((-len(data))%16));address=DATA+len(data);packed=assets.literal_pack(raw)
        pointers[source]=address;data.extend(packed)
        clips.append(dict(character=source.character,animation=source.animation,mesh_entry=None,
                          frames=struct.unpack_from('<H',raw,2)[0],decoded_sha256=hashlib.sha256(raw).hexdigest(),
                          address=address,size=len(packed),blue_pair=True))
    characters=(122,35,0,*galick.DONORS)
    models=_skeleton_models(iso,tuple(dict.fromkeys(characters)),data)
    data.extend(bytes((-len(data))%16));bindings=DATA+len(data)
    data.extend(struct.pack('<6I',models[122],models[35],models[0],*(models[c] for c in galick.DONORS)))
    # Variant5: the reviewed authored bank, roles0..2.
    roots=[]
    for offset in header['roots'][:3]:
        data.extend(bytes((-len(data))%16));roots.append(DATA+len(data));data.extend(payload[offset:offset+213*64])
    data.extend(bytes((-len(data))%16));camera=DATA+len(data)
    data.extend(payload[header['camera']:header['camera']+213*80])
    data.extend(bytes((-len(data))%16));edges=DATA+len(data);data.extend(struct.pack('<8I',*EDGES))
    # Body-sized extra spacing for the exact Goku Blue/Vegeta Blue pair,
    # solved offline on their disc skeletons (tag_rush_pair_clearance).
    import tag_rush_blue_spacing as spacing
    if len(spacing.ROLE0)!=213:raise ValueError('Paired-beam spacing table changed')
    data.extend(bytes((-len(data))%16));gap=DATA+len(data)
    data.extend(b''.join(struct.pack('<4f',*row,0.) for row in spacing.ROLE0))
    struct.pack_into('<9I',data,TABLES-DATA,213,7,LANE,*roots,camera,edges,gap)
    # Variant6: disc-derived grounded Galick Gun exchange.
    motion=galick.motion(iso)
    groots=[];gindices=[];gyaws=[]
    for table in motion['roots']:
        # Most grounded shooter roots repeat while their limbs animate. Exact
        # matrix deduplication leaves room for this pair's own ultimate audio.
        unique={};indices=[]
        for at in range(0,len(table),64):
            matrix=table[at:at+64]
            indices.append(unique.setdefault(matrix,len(unique)))
        data.extend(bytes((-len(data))%16));groots.append(DATA+len(data));data.extend(b''.join(unique))
        data.extend(bytes((-len(data))%16));gindices.append(DATA+len(data));data.extend(struct.pack('<%dH'%len(indices),*indices))
        # Galick's firing pose faces -Z; the fighter's ordinary idle faces
        # +Z. Compensate only when handing back to the ordinary animation.
        final=struct.unpack('<16f',table[-64:]);gyaws.append(math.atan2(final[8],final[10])+math.pi)
    data.extend(bytes((-len(data))%16));gcamera=DATA+len(data);data.extend(motion['camera'])
    data.extend(bytes((-len(data))%16));gedges=DATA+len(data)
    data.extend(struct.pack('<%dI'%len(motion['edges']),*motion['edges']))
    data.extend(bytes((-len(data))%16));yaw_pointer=DATA+len(data);data.extend(struct.pack('<4f',*gyaws,0.))
    index_pointer=DATA+len(data);data.extend(struct.pack('<4I',*gindices,0))
    struct.pack_into('<9I',data,TABLES+TABLE_SIZE-DATA,motion['samples'],len(motion['edges'])-1,GROUND,*groots,gcamera,gedges,0)
    struct.pack_into('<2I',data,TABLES+TABLE_SIZE-DATA+T['final_yaws'],yaw_pointer,index_pointer)
    import tag_rush_beam_audio as beam_audio
    bank_audio=beam_audio.disc_bank(str(Path(iso).resolve()))
    data.extend(bytes((-len(data))%64));beam_audio_address=DATA+len(data);data.extend(bank_audio['data'])
    data.extend(bytes((-len(data))%16));gfx=DATA+len(data)
    for index,name in enumerate(NAMES):
        schedule=beam_schedule(name);hit=burst(name)
        data.extend(struct.pack('<8I',*(v for row in schedule for v in row),_absolute(name,*hit),0))
    struct.pack_into('<4I',data,0,MAGIC,2,gfx,0)
    if DATA+len(data)>END:raise ValueError('Paired beams exceed reserved storage')
    return dict(blocks=[(DATA,bytes(data))],pointers=pointers,clips=clips,bindings=(bindings,bindings+12),
                bytes_used=len(data),sha256=hashlib.sha256(BANK.read_bytes()).hexdigest(),
                galick_sha256=motion['sha256'],fx_table=gfx,beam_audio_address=beam_audio_address,reviewed=True)


def own_edges(name):
    if name==NAMES[1]:
        import tag_rush_galick_pair as galick
        return galick.EDGES
    return EDGES


def _absolute(name,phase,frame):
    return own_edges(name)[phase-INTRO]+frame


def _table(a,fail,reg=19):
    """reg = this variant's authored table (variant5/6 only); t0..t3 scratch."""
    import tag_team_rush as tag
    a.li(8,tag.CONTROL);a.lw(8,8,tag.C['variant']);a.addiu(8,8,-5);a.i(11,9,8,2);a.branch(4,9,0,fail)
    a.r(0,9,0,8,5);a.r(0,8,0,8,4);a.r(0x21,8,8,9);a.li(reg,TABLES);a.r(0x21,reg,reg,8)


def _sample(a,fail):
    """s0=scene state, s3=variant table, v0=sample index; t0..t3/f0..f3 scratch."""
    from native_map import ACTOR_HZ
    import tag_rush_scene as scene
    a.li(16,scene.STATE);a.lw(8,16);a.li(9,scene.SCENE_MAGIC);a.branch(5,8,9,fail)
    a.li(8,DATA);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,fail)
    _table(a,fail)
    # Shared opening phases precede the authored split; they never sample.
    a.lw(9,16,scene.S['phase']);a.addiu(9,9,-INTRO);a.lw(10,19,T['phases'])
    a.r(0x2B,11,9,10);a.branch(4,11,0,fail)
    a.r(0,9,0,9,2);a.lw(10,19,T['edges']);a.r(0x21,10,10,9);a.lw(10,10)
    a.lw(9,16,scene.S['ticks']);a.li(11,60);a.r(0x19,0,9,11);a.r(0x12,9,0,0)
    a.li(11,ACTOR_HZ);a.r(0x1B,0,9,11);a.r(0x12,9,0,0);a.r(0x21,9,9,10)
    a.r(2,2,0,9,1);a.lw(11,19,T['samples']);a.r(0x2B,9,2,11);a.branch(5,9,0,fail+'_sampled')
    a.addiu(2,11,-1)
    a.label(fail+'_sampled')


def _global_matrix(a):
    """Stack+0x40 common yaw/origin; stack+0 local sample, result+0x80.

    Stack+0xE0 holds an unscaled local offset added after the arena scale.
    """
    from native_map import A
    import tag_rush_scene as scene
    a.addiu(4,29,0x40);a.call(A(0x120098))
    a.addiu(4,29,0x40);a.move(5,4);a.i(49,12,16,scene.S['rotation']+4);a.call(A(0x120428))
    for off in range(0,16,4):a.lw(8,16,scene.S['origin']+off);a.sw(8,29,0x70+off)
    import beam_struggle as fp
    for k,off in enumerate((48,52,56)):
        a.i(49,0,29,off);a.i(49,1,16,SPATIAL_SCALE);fp.fop(a,2,0,0,1)
        a.i(49,1,29,0xE0+4*k);fp.fop(a,0,0,0,1);a.i(57,0,29,off)
    a.addiu(4,29,0x80);a.addiu(5,29,0x40);a.move(6,29);a.call(A(0x1201B8))


def lane_offset(own,other,scale):
    """Python reference: the pair's spacing is body-sized, never arena-scaled."""
    return tuple((1.-scale)*(p-q)*.5 for p,q in zip(own,other))


def root_code():
    """a0 role, a1 capture row -> v0 placed. Called again by SEPARATE."""
    from prototype import Assembler
    from native_map import A
    import tag_rush_camera as camera,tag_rush_scene as scene,beam_struggle as fp
    a=Assembler(ROOT_STEP);camera.save(a);a.addiu(29,29,-0x100);a.move(18,4);a.move(21,5)
    _sample(a,'no');a.move(17,2)
    a.i(11,8,18,3);a.branch(4,8,0,'no')
    a.r(0,8,0,18,2);a.r(0x21,8,8,19);a.lw(8,8,T['roots'])
    a.move(10,17);a.lw(9,19,T['root_indices']);a.branch(4,9,0,'root_indexed')
    a.r(0,11,0,18,2);a.r(0x21,9,9,11);a.lw(9,9);a.r(0,11,0,17,1);a.r(0x21,9,9,11);a.i(37,10,9,0)
    a.label('root_indexed');a.r(0,9,0,10,6);a.r(0x21,20,8,9)
    for off in range(0,64,4):a.lw(9,20,off);a.sw(9,29,off)
    for off in (0,4,8):a.sw(0,29,0xE0+off)
    # Attackers share one travelling lane; their mutual spacing stays at the
    # authored body-sized distance on every arena (previously it shrank with
    # the lane scale until the bodies intersected on smaller maps).
    a.li(8,2);a.branch(4,18,8,'lane_done');a.lw(8,19,T['mode']);a.branch(5,8,0,'lane_done')
    a.li(8,1);a.r(0x26,8,18,8);a.r(0,8,0,8,2);a.r(0x21,8,8,19);a.lw(8,8,T['roots'])
    a.r(0,9,0,17,6);a.r(0x21,8,8,9)
    fp.fconst(a,3,1.,temp=10);a.i(49,1,16,SPATIAL_SCALE);fp.fop(a,1,3,3,1);fp.fconst(a,1,.5,temp=10);fp.fop(a,2,3,3,1)
    for k,off in enumerate((48,52,56)):
        a.i(49,0,20,off);a.i(49,1,8,off);fp.fop(a,1,0,0,1);fp.fop(a,2,0,0,3);a.i(57,0,29,0xE0+4*k)
    a.lw(8,19,T['spacing']);a.branch(4,8,0,'lane_done')
    a.r(0,9,0,17,4);a.r(0x21,8,8,9)
    # Role0 moves by +offset, role1 by -offset (symmetric about the lane).
    for role,fn in ((0,0),(1,1)):
        if role==0:a.branch(5,18,0,'spacing1')
        else:a.label('spacing1')
        for k in range(3):
            a.i(49,0,29,0xE0+4*k);a.i(49,1,8,4*k);fp.fop(a,fn,0,0,1);a.i(57,0,29,0xE0+4*k)
        if role==0:a.jump('lane_done')
    a.label('lane_done')
    a.lw(23,21,scene.R['model'])
    # Shape size is independent of cinematic travel distance. The native
    # retargeter already adapts limb lengths; do not scale skeletons twice.
    for off in (*range(0,12,4),*range(16,28,4),*range(32,44,4)):
        a.i(49,0,29,off);a.i(49,1,23,2592);fp.fop(a,2,0,0,1);a.i(57,0,29,off)
    _global_matrix(a)
    # Collision guard push and per-role ground height, both world-space.
    for k in range(3):
        a.i(49,0,29,0xB0+4*k);a.i(49,1,21,SEP+4*k);fp.fop(a,0,0,0,1)
        if k==1:a.i(49,1,21,GROUND_DY);fp.fop(a,0,0,0,1)
        a.i(57,0,29,0xB0+4*k)
    a.lw(4,21,scene.R['actor']);a.addiu(5,29,0xB0);a.addiu(6,16,scene.S['rotation']);a.lw(7,23,2596);a.call(A(0x1D7418))
    for off in range(0,64,4):a.lw(8,29,0x80+off);a.sw(8,23,2464+off)
    a.move(4,23);a.call(A(0x24E3F8))
    #52 is a nondrawable contact marker. These scenes do not use native
    #paired-contact alignment; bind their beam to the midpoint of both palms.
    fp.fconst(a,2,.5)
    a.lw(8,23,3436+4*31);a.lw(9,23,3436+4*45);a.lw(10,23,3436+4*52)
    for off in (64,68,72):
        a.i(49,0,8,off);a.i(49,1,9,off);fp.fop(a,0,0,0,1)
        fp.fop(a,2,0,0,2);a.i(57,0,10,off)
    a.li(8,2);a.branch(4,18,8,'root_finished');a.lw(8,19,T['mode']);a.branch(5,8,0,'root_finished')
    # Dash uses the separate native afterimage/shell family. Its scoped
    # instance is started once by AURA_START, not restarted every pose tick.
    a.lw(4,21,scene.R['index']);a.li(5,6);a.call(A(0x165418))
    a.move(4,23);a.li(5,6);a.li(6,1);a.call(A(0x2500E8))
    a.label('root_finished')
    # On success use the last authored facing when decoding the fighter's
    # own idle. Restoring the pre-rush yaw made both shooters turn around.
    a.lw(8,19,T['final_yaws']);a.branch(4,8,0,'facing_ready');a.i(11,9,18,2);a.branch(4,9,0,'facing_ready')
    a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.i(49,0,8,0);a.i(49,1,16,scene.S['rotation']+4)
    fp.fop(a,0,0,0,1)
    for off in (0,8,12):a.sw(0,21,END_ROTATION+off)
    a.i(57,0,21,END_ROTATION+4);a.li(8,MAGIC);a.sw(8,21,END_FACING)
    a.label('facing_ready')
    a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');a.addiu(29,29,0x100);camera.restore(a,skip=(2,));a.jr()
    raw=a.finish();assert ROOT_STEP+len(raw)<=CAMERA_STEP;return raw


def camera_code():
    from prototype import Assembler
    from native_map import A
    import tag_rush_camera as camera,tag_rush_scene as scene
    a=Assembler(CAMERA_STEP);camera.save(a);a.addiu(29,29,-0x100);_sample(a,'no')
    a.lw(8,19,T['camera']);a.li(9,80);a.r(0x19,0,2,9);a.r(0x12,9,0,0);a.r(0x21,8,8,9)
    for off in range(0,64,4):a.lw(9,8,off);a.sw(9,29,off)
    for off in range(0,16,4):a.lw(9,8,64+off);a.sw(9,29,0xC0+off)
    for off in (0,4,8):a.sw(0,29,0xE0+off)
    _global_matrix(a)
    a.lw(20,28,-22180);a.lw(21,28,-22176);a.lw(22,28,-22172);a.lw(23,22,0xC40)
    a.li(24,camera.CAMERA)
    for off in range(0,16,4):a.lw(8,29,0xB0+off);a.sw(8,24,720+off)
    # A charge closeup focuses on the attacker, not the distant victim.
    # Apply the same native yaw/origin/arena scale to the authored focus.
    import beam_struggle as fp
    for off in (0,4,8):
        a.i(49,0,29,0x70+off)
        for axis in range(3):
            a.i(49,1,29,0xC0+axis*4);a.i(49,2,16,SPATIAL_SCALE)
            fp.fop(a,2,1,1,2);a.i(49,2,29,0x40+axis*16+off)
            fp.fop(a,2,1,1,2);fp.fop(a,0,0,0,1)
        a.i(57,0,16,scene.S['focus']+off)
    a.li(8,0x3F800000);a.sw(8,16,scene.S['focus']+12)
    a.addiu(4,24,64);a.addiu(5,29,0x80);a.call(A(0x1202A0))
    a.li(4,camera.CAMERA+64);a.call(A(0x121408))
    a.li(4,camera.CAMERA);a.addiu(5,4,64);a.call(A(0x120230))
    a.li(4,camera.CAMERA);a.addiu(5,4,720);a.call(A(0x23E598))
    a.move(4,21);a.li(5,1);a.call(A(0x23E6A0))
    a.sw(20,28,-22180);a.sw(21,28,-22176);a.sw(23,22,0xC40);a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');a.addiu(29,29,0x100);camera.restore(a,skip=(2,));a.jr()
    raw=a.finish();assert CAMERA_STEP+len(raw)<=ANCHOR;return raw


def anchor_code():
    """Fit the entire flying lane in the live arena, including enlarged maps."""
    from prototype import Assembler
    import arena_bounds,tag_rush_camera as camera,tag_rush_scene as scene,beam_struggle as fp
    a=Assembler(ANCHOR);camera.save(a);a.li(16,scene.STATE)
    # Only these authored, long-distance scenes use a centered air lane. The
    # final native safety placement still grounds/clamps every participant.
    a.sw(0,16,scene.S['origin']);a.sw(0,16,scene.S['origin']+8)
    a.li(8,arena_bounds.STAGE);a.lw(8,8);a.lw(8,8,64)
    a.i(49,0,8,0);fp.fconst(a,1,100.);fp.fop(a,1,0,0,1);fp.fconst(a,1,1100.);fp.fop(a,3,0,0,1)
    fp.fconst(a,1,1.);fp.fop(a,0x34,0,1,0);a.branch(17,8,0,'scale');fp.fop(a,6,0,1)
    a.label('scale');fp.fconst(a,1,.05);fp.fop(a,0x34,0,0,1);a.branch(17,8,0,'publish');fp.fop(a,6,0,1)
    a.label('publish');a.i(57,0,16,SPATIAL_SCALE);camera.restore(a);a.jr()
    raw=a.finish();assert ANCHOR+len(raw)<=AURA_START;return raw


def split_code():
    """Entering the first authored phase: own the presentation from here on.

    Variant5 centres its long flying lane and leases the dash shells. The
    grounded variant6 keeps the shared opening's anchor, stands it on the
    terrain and measures each role's own floor, so nobody floats or sinks.
    Clears this director's per-role guard state. v0 success.
    """
    from prototype import Assembler
    import tag_rush_camera as camera,tag_rush_scene as scene,tag_rush_safety as safety,beam_struggle as fp
    a=Assembler(SPLIT);camera.save(a);a.addiu(29,29,-0x40)
    _table(a,'no');a.li(16,scene.STATE)
    for role in range(3):
        for off in (SEP,SEP+4,SEP+8,GROUND_DY,FX_STATE):a.li(8,scene.ROWS+role*scene.STRIDE);a.sw(0,8,off)
    a.lw(8,19,T['mode']);a.branch(5,8,0,'ground')
    a.call(ANCHOR);a.call(AURA_START);a.li(2,1);a.jump('done')
    a.label('ground')
    for role in range(2):a.li(8,scene.ROWS+role*scene.STRIDE);a.sw(0,8,380)
    fp.fconst(a,0,1.);a.i(57,0,16,SPATIAL_SCALE)
    # START's anchor is 40 native units (height scaled) above the floor.
    a.i(49,0,16,scene.S['origin']+4);fp.fconst(a,1,40.);a.i(49,2,16,scene.S['height_scale'])
    fp.fop(a,2,1,1,2);fp.fop(a,0,0,0,1);a.i(57,0,16,scene.S['origin']+4)
    # Each role's landing mark, rotated by the shared yaw, then its floor.
    # safety.FLOOR reports the terrain under a point that is below it, so
    # probe from 200 units under the estimate. The victim's floor becomes the
    # scene ground; each attacker keeps its own level unless it is a ledge.
    a.i(49,12,16,scene.S['rotation']+4);from native_map import A;a.call(A(0x11F588));a.i(57,0,29,0x30)
    a.i(49,12,16,scene.S['rotation']+4);a.call(A(0x11F620));a.i(57,0,29,0x34)
    for role in (2,0,1):
        a.lw(8,19,T['roots']+4*role)
        a.move(9,0)
        if role<2:a.lw(9,19,T['samples']);a.addiu(9,9,-1)
        a.lw(10,19,T['root_indices']);a.branch(4,10,0,f'floor_indexed{role}')
        a.lw(10,10,4*role);a.r(0,11,0,9,1);a.r(0x21,10,10,11);a.i(37,9,10,0)
        a.label(f'floor_indexed{role}');a.r(0,9,0,9,6);a.r(0x21,8,8,9)
        # x' = x cos + z sin, z' = z cos - x sin  (native yaw about Y).
        a.i(49,0,8,48);a.i(49,1,8,56);a.i(49,2,29,0x34);a.i(49,3,29,0x30)
        fp.fop(a,2,4,0,2);fp.fop(a,2,5,1,3);fp.fop(a,0,4,4,5)
        fp.fop(a,2,5,1,2);fp.fop(a,2,6,0,3);fp.fop(a,1,5,5,6)
        a.i(49,6,16,scene.S['origin']);fp.fop(a,0,4,4,6);a.i(57,4,29,0)
        a.i(49,6,16,scene.S['origin']+8);fp.fop(a,0,5,5,6);a.i(57,5,29,8)
        a.i(49,6,16,scene.S['origin']+4);fp.fconst(a,7,200.);fp.fop(a,0,6,6,7);a.i(57,6,29,4)
        a.sw(0,29,12);a.move(4,29);a.call(safety.FLOOR);a.branch(4,2,0,f'floor_done{role}')
        a.i(49,0,29,12);a.i(49,1,16,scene.S['origin']+4);fp.fop(a,1,0,0,1)
        # A different terrain level of more than 60 units is a ledge, not a
        # slope; keep the shared anchor rather than stepping off a cliff.
        fp.fconst(a,2,60.);fp.fop(a,0x34,0,0,2);a.branch(17,8,0,f'floor_done{role}')
        fp.fconst(a,2,-60.);fp.fop(a,0x34,0,2,0);a.branch(17,8,0,f'floor_done{role}')
        if role==2:a.i(49,0,29,12);a.i(57,0,16,scene.S['origin']+4)
        else:a.li(8,scene.ROWS+role*scene.STRIDE);a.i(57,0,8,GROUND_DY)
        a.label(f'floor_done{role}')
    a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done');a.addiu(29,29,0x40);camera.restore(a,skip=(2,));a.jr()
    raw=a.finish();assert SPLIT+len(raw)<=SEPARATE;return raw


def separate_code():
    """After all three poses: push overlapping bodies apart, then re-pose.

    Each body is sampled at eleven native bones with per-bone radii scaled by
    the live model scale. An attacker pair shares the push; an attacker never
    moves the victim. The world push persists, decays slowly when clear and
    never exceeds SEPARATION_LIMIT. v0 success (0 cancels the scene).
    """
    from prototype import Assembler
    import tag_rush_camera as camera,tag_rush_scene as scene,beam_struggle as fp,fusion_partner_lifecycle as full
    a=Assembler(SEPARATE);camera.save(a);a.addiu(29,29,-0x80)
    a.sw(0,29,0x70)  # iteration
    a.label('iterate');a.sw(0,29,0x74)  # any push this iteration
    for first,second,share in ((0,1,.5),(0,2,1.),(1,2,1.)):
        tag=f'{first}{second}'
        a.li(16,scene.ROWS+first*scene.STRIDE);a.li(17,scene.ROWS+second*scene.STRIDE)
        a.lw(20,16,scene.R['model']);a.lw(21,17,scene.R['model'])
        fp.fconst(a,10,-1e9)  # deepest penetration
        a.li(18,BODY_TABLE);a.li(22,len(BODY))
        a.label('outer'+tag);a.lw(8,18);a.r(0,8,0,8,2);a.r(0x21,8,8,20);a.lw(8,8,3436)
        a.branch(4,8,0,'outer_next'+tag)
        full.pointer(a,8,80,'no',temp=10,test=9);a.i(49,0,8,64);a.i(49,1,8,68);a.i(49,2,8,72)
        a.i(49,3,18,4);a.i(49,4,20,2592);fp.fop(a,2,3,3,4)
        a.li(19,BODY_TABLE);a.li(23,len(BODY))
        a.label('inner'+tag);a.lw(8,19);a.r(0,8,0,8,2);a.r(0x21,8,8,21);a.lw(8,8,3436)
        a.branch(4,8,0,'shallow'+tag)
        full.pointer(a,8,80,'no',temp=10,test=9)
        fp.fconst(a,9,0.,temp=10)
        for k,off in enumerate((64,68,72)):
            a.i(49,5,8,off);fp.fop(a,1,5,k,5);fp.fop(a,2,5,5,5);fp.fop(a,0,9,9,5)
        fp.fop(a,4,9,9,9)
        a.i(49,6,19,4);a.i(49,7,21,2592);fp.fop(a,2,6,6,7);fp.fop(a,0,6,6,3)
        fp.fconst(a,7,CLEARANCE);fp.fop(a,0,6,6,7);fp.fop(a,1,6,6,9)
        fp.fop(a,0x34,0,10,6);a.branch(17,8,0,'shallow'+tag);fp.fop(a,6,10,6)
        a.label('shallow'+tag)
        a.addiu(19,19,8);a.addiu(23,23,-1);a.branch(5,23,0,'inner'+tag)
        a.label('outer_next'+tag)
        a.addiu(18,18,8);a.addiu(22,22,-1);a.branch(5,22,0,'outer'+tag)
        fp.fconst(a,0,0.);fp.fop(a,0x34,0,0,10);a.branch(17,8,0,'pair_done'+tag)
        # Horizontal direction from the second root to the first.
        a.i(49,0,20,2384);a.i(49,1,21,2384);fp.fop(a,1,0,0,1)
        a.i(49,2,20,2392);a.i(49,1,21,2392);fp.fop(a,1,2,2,1)
        fp.fop(a,2,3,0,0);fp.fop(a,2,4,2,2);fp.fop(a,0,3,3,4);fp.fop(a,4,3,3,3)
        fp.fconst(a,4,.01);fp.fop(a,0x34,0,3,4);a.branch(17,8,0,'direction'+tag)
        # Coincident roots: separate along the shared local X axis, which the
        # native yaw maps to (cos, -sin). Native sin/cos clobber f0..f19.
        from native_map import A
        a.i(57,10,29,0x60);a.li(8,scene.STATE);a.i(49,12,8,scene.S['rotation']+4)
        a.call(A(0x11F588));a.i(57,0,29,0x64);a.li(8,scene.STATE);a.i(49,12,8,scene.S['rotation']+4)
        a.call(A(0x11F620));a.i(49,4,29,0x64);fp.fconst(a,2,0.);fp.fop(a,1,2,2,4);fp.fconst(a,3,1.);a.i(49,10,29,0x60)
        a.label('direction'+tag)
        fp.fop(a,3,0,0,3);fp.fop(a,3,2,2,3)
        fp.fconst(a,4,share);fp.fop(a,2,10,10,4)
        a.li(16,scene.ROWS+first*scene.STRIDE)
        for k,axis in ((0,0),(8,2)):
            a.i(49,5,16,SEP+k);fp.fop(a,2,6,axis,10);fp.fop(a,0,5,5,6);a.i(57,5,16,SEP+k)
            if share<1:
                a.li(17,scene.ROWS+second*scene.STRIDE)
                a.i(49,5,17,SEP+k);fp.fop(a,1,5,5,6);a.i(57,5,17,SEP+k)
        a.li(8,1);a.sw(8,29,0x74)
        a.label('pair_done'+tag)
    # Bound both attackers' push; a scene that needs more is mis-authored.
    for role in range(2):
        a.li(16,scene.ROWS+role*scene.STRIDE);fp.fconst(a,2,SEPARATION_LIMIT);fp.fconst(a,3,-SEPARATION_LIMIT)
        for k in (0,8):
            a.i(49,0,16,SEP+k);fp.fop(a,0x34,0,0,3);a.branch(17,8,0,f'low{role}{k}');fp.fop(a,6,0,3)
            a.label(f'low{role}{k}');fp.fop(a,0x34,0,2,0);a.branch(17,8,0,f'high{role}{k}');fp.fop(a,6,0,2)
            a.label(f'high{role}{k}');a.i(57,0,16,SEP+k)
    a.lw(8,29,0x74);a.branch(4,8,0,'clear')
    for role in range(2):
        a.li(4,role);a.li(5,scene.ROWS+role*scene.STRIDE);a.call(ROOT_STEP);a.branch(4,2,0,'no')
    a.lw(8,29,0x70);a.addiu(8,8,1);a.sw(8,29,0x70);a.li(9,2);a.branch(5,8,9,'iterate')
    a.jump('yes')
    a.label('clear');a.lw(8,29,0x70);a.branch(5,8,0,'yes')
    fp.fconst(a,1,SEPARATION_DECAY)
    for role in range(2):
        a.li(16,scene.ROWS+role*scene.STRIDE)
        for k in (0,8):a.i(49,0,16,SEP+k);fp.fop(a,2,0,0,1);a.i(57,0,16,SEP+k)
    a.label('yes');a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done');a.addiu(29,29,0x80);camera.restore(a,skip=(2,));a.jr()
    raw=a.finish();assert SEPARATE+len(raw)<=BODY_TABLE;return raw


BODY_TABLE=BASE+0xAE00


def body_table():
    return b''.join(struct.pack('<If',bone,radius) for bone,radius in BODY)


def fx_code():
    """Per-role charge/fire/end schedule for the authored paired beams.

    Each role keeps one native emitter from its charge, through ignition, to
    its own end frame, across phase boundaries (variant6's partner joins a
    beam already firing). Shares the generic emitters, update and explosion.
    """
    from prototype import Assembler
    from native_map import ACTOR_HZ
    import tag_rush_camera as camera,tag_rush_scene as scene,tag_rush_effects as effects,tag_team_rush as tag
    a=Assembler(FX);camera.save(a);a.addiu(29,29,-0x40)
    _table(a,'no');a.li(16,scene.STATE)
    a.lw(9,16,scene.S['phase']);a.addiu(9,9,-INTRO);a.lw(10,19,T['phases'])
    a.r(0x2B,11,9,10);a.branch(4,11,0,'update')
    a.r(0,9,0,9,2);a.lw(10,19,T['edges']);a.r(0x21,10,10,9);a.lw(10,10)
    a.lw(9,16,scene.S['ticks']);a.li(11,60);a.r(0x19,0,9,11);a.r(0x12,9,0,0)
    a.li(11,ACTOR_HZ);a.r(0x1B,0,9,11);a.r(0x12,9,0,0);a.r(0x21,20,9,10)  # s4 now
    a.li(8,DATA);a.lw(21,8,8)
    a.li(8,tag.CONTROL);a.lw(8,8,tag.C['variant']);a.addiu(8,8,-5);a.r(0,8,0,8,5);a.r(0x21,21,21,8)
    for role in range(2):
        nxt=f'role{role}_done'
        a.li(17,scene.ROWS+role*scene.STRIDE);a.lw(18,17,FX_STATE)
        a.lw(8,21,12*role+8);a.r(0x2B,9,20,8);a.branch(4,9,0,nxt)  # at/after end
        a.li(9,1);a.branch(4,18,9,nxt)
        a.lw(8,21,12*role);a.r(0x2B,9,20,8);a.branch(5,9,0,nxt)  # before charge
        # Lifetime: remaining frames to this role's end, in actor ticks.
        a.lw(22,21,12*role+4);a.branch(5,18,0,'charging'+str(role))
        a.lw(8,21,12*role+8);a.r(0x23,8,8,20);a.li(9,ACTOR_HZ);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
        a.addiu(8,8,59);a.li(9,60);a.r(0x1B,0,8,9);a.r(0x12,5,0,0)
        a.li(9,effects.MAX_TICKS);a.r(0x2B,8,9,5);a.branch(4,8,0,'lifetime'+str(role));a.move(5,9)
        a.label('lifetime'+str(role))
        a.r(0x2B,9,20,22);a.branch(4,9,0,'fire_now'+str(role))
        a.li(4,role);a.call(effects.CHARGE_SPAWN);a.branch(4,2,0,'no')
        a.li(8,2);a.sw(8,17,FX_STATE);a.jump(nxt)
        a.label('fire_now'+str(role));a.li(4,role);a.call(effects.SPAWN);a.branch(4,2,0,'no')
        a.li(8,1);a.sw(8,17,FX_STATE);a.jump(nxt)
        a.label('charging'+str(role));a.r(0x2B,9,20,22);a.branch(5,9,0,nxt)
        a.li(4,effects.ROWS+role*effects.STRIDE);a.call(effects.IGNITE);a.branch(4,2,0,'no')
        a.li(8,1);a.sw(8,17,FX_STATE)
        a.label(nxt)
    a.label('update');a.call(effects.UPDATE)
    a.lw(8,16,scene.S['exploded']);a.branch(5,8,0,'yes')
    a.lw(8,21,24);a.r(0x2B,9,20,8);a.branch(5,9,0,'yes')
    a.li(8,1);a.sw(8,16,scene.S['exploded']);a.li(4,2);a.li(5,17);a.call(effects.EXPLOSION)
    a.label('yes');a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done');a.addiu(29,29,0x40);camera.restore(a,skip=(2,));a.jr()
    raw=a.finish();assert FX+len(raw)<=CODE_END;return raw


def aura_code(stop=False):
    """Own the native dash shell for these two actors and retire it on exit."""
    from prototype import Assembler
    from native_map import A
    import tag_rush_camera as camera,tag_rush_scene as scene,fusion_partner_lifecycle as full
    a=Assembler(AURA_STOP if stop else AURA_START);camera.save(a)
    for role in range(2):
        a.li(21,scene.ROWS+role*scene.STRIDE);scene.identity(a,21,'next'+str(role),'aura'+str(role))
        if not stop:
            for off in (368,372,376,380):a.sw(0,21,off)
            a.sw(0,21,404);a.sw(0,21,408)
            a.lw(8,23,2868);a.i(12,8,8,0x40);a.r(2,8,0,8,6);a.sw(8,21,384)
        a.lw(18,28,-22640);full.pointer(a,18,1172,'next'+str(role));a.lw(18,18,1168)
        full.pointer(a,18,48,'next'+str(role));a.lw(8,21,scene.R['index']);a.r(0,8,0,8,2)
        a.r(0x21,18,18,8);a.lw(19,18)
        if stop:
            a.lw(8,21,380);a.li(9,MAGIC);a.branch(5,8,9,'next'+str(role));a.sw(0,21,380)
            a.lw(8,21,368);a.branch(4,8,0,'end_created'+str(role));a.branch(5,8,19,'next'+str(role))
            full.pointer(a,19,64,'next'+str(role));a.lw(20,19,56);a.lw(8,21,372);a.branch(5,8,20,'next'+str(role))
            full.pointer(a,20,80,'next'+str(role))
            for source,destination in ((376,40),(388,44),(392,64),(396,68),(400,76)):
                a.lw(8,21,source);a.sw(8,20,destination)
            # Native approach already faded this shell out before capture.
            # Complete the normal rush-exit fade-in instead of restoring an
            # idle mode with zero opacity and leaving Blue's aura invisible.
            a.lw(4,21,scene.R['index']);a.li(5,5);a.call(A(0x165418))
            a.jump('restore_model_aura'+str(role))
            a.label('end_created'+str(role));a.lw(4,21,scene.R['index']);a.li(5,1);a.call(A(0x165418))
            a.label('restore_model_aura'+str(role))
            a.lw(18,28,-22584);full.pointer(a,18,1780,'restore_model_bit'+str(role))
            a.lw(18,18,1776);full.pointer(a,18,48,'restore_model_bit'+str(role))
            a.lw(8,21,scene.R['index']);a.r(0,8,0,8,2);a.r(0x21,18,18,8);a.lw(19,18)
            a.lw(8,21,404);a.branch(4,8,0,'restore_model_bit'+str(role));a.branch(5,8,19,'restore_model_bit'+str(role))
            full.pointer(a,19,64,'restore_model_bit'+str(role));a.lw(20,19,56)
            a.lw(8,21,408);a.branch(5,8,20,'restore_model_bit'+str(role))
            a.lw(4,21,scene.R['index']);a.li(5,2);a.call(A(0x1714E8))
            a.label('restore_model_bit'+str(role));a.move(4,23);a.li(5,6);a.lw(6,21,384);a.call(A(0x2500E8))
        else:
            a.branch(4,19,0,'new_aura'+str(role));full.pointer(a,19,64,'next'+str(role))
            a.lw(20,19,56);full.pointer(a,20,112,'next'+str(role))
            a.sw(19,21,368);a.sw(20,21,372);a.lw(8,20,40);a.sw(8,21,376)
            for source,destination in ((44,388),(64,392),(68,396),(76,400)):
                a.lw(8,20,source);a.sw(8,21,destination)
            a.jump('aura_captured'+str(role));a.label('new_aura'+str(role))
            a.lw(4,21,scene.R['index']);a.move(5,0);a.call(A(0x165418))
            a.label('aura_captured'+str(role));a.li(8,MAGIC);a.sw(8,21,380)
            a.lw(4,21,scene.R['index']);a.li(5,6);a.call(A(0x165418))
            a.lw(4,21,scene.R['index']);a.move(5,0);a.call(A(0x1714E8))
            a.lw(18,28,-22584);full.pointer(a,18,1780,'next'+str(role))
            a.lw(18,18,1776);full.pointer(a,18,48,'next'+str(role))
            a.lw(8,21,scene.R['index']);a.r(0,8,0,8,2);a.r(0x21,18,18,8);a.lw(19,18)
            full.pointer(a,19,64,'next'+str(role));a.lw(20,19,56);full.pointer(a,20,736,'next'+str(role))
            a.sw(19,21,404);a.sw(20,21,408)
            # Preserve the preceding particle size. The scoped render
            # selector below applies the additional reduction to the
            # whole shell, including widths the native update regenerates.
            import beam_struggle as fp
            fp.fconst(a,1,DASH_PARTICLE_SCALE)
            for off in DASH_SIZE_FIELDS:
                a.i(49,0,20,off);fp.fop(a,2,0,0,1);a.i(57,0,20,off)
        a.label('next'+str(role))
    camera.restore(a);a.jr();return a.finish()


def aura_size_hook():
    from native_map import A
    from prototype import Assembler
    a=Assembler(A(0x16E574));a.jump(AURA_SIZE)
    return A(0x16E574),struct.pack('<2I',0x03E00008,0x46000806),a.finish()


def aura_size_code():
    """Native16E520 return: shrink only the two authenticated owned shells.

    The native updater rewrites head/trail widths every frame. Scaling the
    returned width leaves its positions, opacity and all other actors alone.
    """
    from prototype import Assembler
    import tag_team_rush as tag,tag_rush_scene as scene,beam_struggle as fp
    a=Assembler(AURA_SIZE);a.addiu(29,29,-0x30)
    for i,r in enumerate((8,9,10,11)):a.i(63,r,29,i*8)
    a.i(57,2,29,32);fp.fop(a,6,0,1)  # displaced native MOV.S f0,f1
    a.li(8,tag.CONTROL);a.lw(9,8,tag.C['active']);a.li(10,1);a.branch(5,9,10,'done')
    a.lw(9,8,tag.C['variant']);a.addiu(9,9,-5);a.i(11,10,9,2);a.branch(4,10,0,'done')
    a.li(8,scene.STATE);a.lw(9,8);a.li(10,scene.SCENE_MAGIC);a.branch(5,9,10,'done')
    for role in range(2):
        a.li(8,scene.ROWS+role*scene.STRIDE);a.lw(9,8,380);a.li(10,MAGIC)
        a.branch(5,9,10,'next'+str(role));a.lw(9,8,408);a.branch(4,9,4,'scale')
        a.label('next'+str(role))
    a.jump('done');a.label('scale');fp.fconst(a,2,DASH_RENDER_SCALE);fp.fop(a,2,0,0,2)
    a.label('done');a.i(49,2,29,32)
    for i,r in enumerate((8,9,10,11)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x30);a.jr();raw=a.finish();assert AURA_SIZE+len(raw)<=SPLIT;return raw


def pieces():
    return [(ROOT_STEP,root_code()),(CAMERA_STEP,camera_code()),(ANCHOR,anchor_code()),
            (AURA_START,aura_code()),(AURA_STOP,aura_code(True)),(AURA_SIZE,aura_size_code()),
            (SPLIT,split_code()),(SEPARATE,separate_code()),(BODY_TABLE,body_table()),(FX,fx_code())]
