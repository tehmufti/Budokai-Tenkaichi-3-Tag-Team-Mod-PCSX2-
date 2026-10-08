"""Bounded scenario shots: preloaded skeletal clips, native voice, held combat.

No save-state or executable data is stored in scenario documents. Animation
assets are read from the selected disc during preparation, never mid-shot.
"""
import math
import struct
from pathlib import Path
from prototype import Assembler
from native_map import A, ACTOR_HZ
import native_preparation as prep
import fusion_partner_lifecycle as full
import fresh_team_combat as core

BASE, END = 0x069A0000, 0x06A00000
START, TICK, VOICE = BASE, BASE+0x1000, BASE+0x3000
FORMATION = BASE+0x3500
CONTROL, CAMERA_SAVE, DESCRIPTORS, CLIPS = BASE+0x4000, BASE+0x4200, BASE+0x5000, BASE+0xA000
MAGIC, STRIDE = 0x53434E33, 80  # SCN3: camera tables include both position and aim.
# +12 state: 0 idle, 1 requested, 2 playing, 3 complete, 100 failed.
# +16 actor,+20 model,+24 elapsed,+28 duration,+32 action key,+36 descriptor,
# +40 old clip0 pointer,+44 old animation,+48 saved active camera,+52 cinematic,
# +64 root XYZW, +80..143 saved actor animation bookkeeping.


def emit_active(a, target, tag):
    """Inline, no native calls; only branches for this captured live world."""
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,tag)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,tag)
    a.lw(9,8,12);a.addiu(9,9,-1);a.i(11,9,9,2);a.branch(5,9,0,target)
    a.label(tag)


def voice_code():
    # Native 265E38 resolves the chosen language's stream: role, character,
    # line (0..99), volume (0..128), pitch=0. The final native argument is
    # pitch, not volume; putting the percentage there makes voices silent.
    # Explicit dialogue takes the actor's parity voice stream. It must not be
    # dropped by the optional ambient-extra arbiter when both leaders speak.
    a=Assembler(VOICE);full.save(a);save_hilo(a)
    a.i(12,21,4,1);a.move(22,5);a.addiu(4,21,4);a.call(A(0x265970))
    a.move(4,21);a.lw(5,22);a.lw(6,22,4);a.lw(7,22,8)
    a.li(9,128);a.r(0x19,0,7,9);a.r(0x12,7,0,0)
    a.li(9,100);a.r(0x1B,0,7,9);a.r(0x12,7,0,0);a.move(8,0)
    a.call(A(0x265E38));restore_hilo(a);full.restore(a);a.jr()
    return a.finish()


def save_hilo(a):
    a.r(16,8,0,0);a.r(18,9,0,0);a.i(63,8,29,0x2A0);a.i(63,9,29,0x2A8)


def restore_hilo(a):
    a.i(55,8,29,0x2A0);a.i(55,9,29,0x2A8);a.r(17,0,8,0);a.r(19,0,9,0)


def anchor(a):
    for i in range(3):
        a.i(49,0,21,64+4*i);a.i(49,1,23,2416+4*i)
        a.emit((17<<26)|(16<<21)|(1<<16)|1)
        a.i(49,1,23,2384+4*i);a.emit((17<<26)|(16<<21)|(1<<16));a.i(57,0,23,2384+4*i)
    a.move(4,23);a.call(A(0x24E2B0));a.move(4,23);a.call(A(0x24E3F8))


def formation_code():
    """a0 cast mask, a1 apply (otherwise preflight the entire cast, no writes).

    Reuse the current stage's terrain/footprint-aware spawn route, including
    scaled and destroyed stages. Never teleport a bound attack, resurrect a
    corpse, move a reserve, or mutate fighter identity/HP/controller ownership.
    """
    import story_runtime as story
    import spawn_placement as spawn
    import team_participation as part
    a=Assembler(FORMATION);full.save(a);save_hilo(a)
    a.move(23,4);a.move(21,5);a.move(22,0)
    a.branch(4,23,0,'accepted')
    a.li(8,spawn.STAGE);a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'reject')
    a.li(9,0x8000000-64);a.r(0x2B,9,9,8);a.branch(5,9,0,'reject')
    a.label('scan');a.li(8,CONTROL+8);a.lw(8,8);a.r(0x2B,8,22,8);a.branch(4,8,0,'accepted')
    a.addiu(9,0,1);a.r(4,9,22,9);a.r(0x24,8,23,9);a.branch(4,8,0,'next')
    a.li(8,part.CONSUMED);a.lw(8,8);a.li(10,story.CONTROL+112);a.lw(10,10)
    a.r(0x25,8,8,10);a.r(0x24,8,8,9);a.branch(5,8,0,'next')
    a.r(0,8,0,22,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(18,9)
    a.li(9,story.ACTORS);a.r(0x21,9,9,8);a.lw(9,9);a.branch(5,9,18,'reject')
    a.li(9,0x100000);a.r(0x2B,8,18,9);a.branch(5,8,0,'reject')
    a.li(9,0x8000000-0x1600);a.r(0x2B,8,9,18);a.branch(5,8,0,'reject')
    a.lw(8,18);a.branch(5,8,22,'reject')
    a.lw(8,18,0x994);a.lw(9,18,0x998);a.r(0x2B,10,8,9);a.branch(4,10,0,'reject')
    a.i(11,10,9,6);a.branch(4,10,0,'reject')
    full.row_address(a,19,18,8,9);a.lw(8,19,64);a.branch(6,8,0,'next')
    # Ordinary locomotion, charging, melee and hit reactions may be reset.
    # Bound rushes, clashes, transformations and pending specials finish first.
    for off in (0x948,0x94C):
        a.lw(8,18,off)
        if off==0x94C:
            a.addiu(9,0,-1);a.branch(4,8,9,'pending_clear')
        a.addiu(8,8,-11);a.i(11,8,8,169);a.branch(4,8,0,'reject')
    a.label('pending_clear')
    a.lw(8,18,12);a.i(11,9,8,12);a.branch(4,9,0,'reject')
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,9,9,8);a.lw(20,9)
    a.li(9,0x100000);a.r(0x2B,8,20,9);a.branch(5,8,0,'reject')
    a.li(9,0x8000000-0x1670);a.r(0x2B,8,9,20);a.branch(5,8,0,'reject')
    a.lw(8,20,4);a.li(9,1);a.branch(5,8,9,'reject')
    a.lw(8,20,16);a.lw(9,18,12);a.branch(5,8,9,'reject')
    for off in (4000,4004):
        a.lw(8,20,off);a.addiu(9,20,3936);a.branch(4,8,9,f'sphere{off}')
        a.addiu(9,20,3968);a.branch(5,8,9,'reject');a.label(f'sphere{off}')
    a.branch(4,21,0,'next')
    a.move(4,18);a.move(5,20);a.call(story.ARRIVAL);a.branch(4,2,0,'reject')
    # Native dispatch performs the outgoing action's cleanup before idle; do
    # not directly overwrite animation/action numbers or leave an attack live.
    a.move(4,18);a.li(5,11);a.call(A(0x1E0290))
    a.move(4,18);a.call(A(0x1E23D0))
    a.label('next');a.addiu(22,22,1);a.jump('scan')
    a.label('accepted');restore_hilo(a);full.restore(a);a.li(2,1);a.jr()
    a.label('reject');restore_hilo(a);full.restore(a);a.move(2,0);a.jr()
    data=a.finish();assert FORMATION+len(data)<=CONTROL;return data


def start_code():
    import story_runtime as story
    a=Assembler(START);full.save(a);story.guard(a,'reject')
    a.li(21,CONTROL);a.lw(8,21,12);a.branch(5,8,0,'reject')
    a.li(8,prep.CONTROL);a.lw(8,8);a.li(9,prep.MAGIC);a.branch(5,8,9,'reject')
    a.li(8,prep.CONTROL+16);a.lw(8,8);a.branch(5,8,0,'reject')
    # Pending/claimed reloads finish before taking the shared combat hold.
    import extra_reload_requests as reloads
    import body_swap as body
    a.li(8,body.CONTROL+16);a.lw(8,8)
    for value in (1,2,3):a.li(9,value);a.branch(4,8,9,'reject')
    a.li(10,reloads.RECORDS);a.lw(11,21,8);a.addiu(11,11,-2)
    a.label('reload_scan');a.branch(6,11,0,'reload_clear');a.lw(8,10,4)
    for value in (1,2):a.li(9,value);a.branch(4,8,9,'reject')
    a.addiu(10,10,reloads.STRIDE);a.addiu(11,11,-1);a.jump('reload_scan');a.label('reload_clear')
    # Do not steal an existing native cinematic or an in-flight body reload.
    a.lw(8,28,-22180);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'reject')
    a.li(9,0x8000000-832);a.r(0x2B,9,9,8);a.branch(5,9,0,'reject')
    a.lw(9,8,812);a.branch(5,9,0,'reject');a.lw(9,8,776);a.i(12,9,9,1);a.branch(5,9,0,'reject')
    a.lw(4,6,76);a.move(5,0);a.call(FORMATION);a.branch(4,2,0,'reject')
    for reg in (4,5,6,7):a.i(30,reg,29,full.OFFSETS[reg])
    a.sw(4,21,16);a.sw(5,21,20);a.sw(6,21,36);a.sw(7,21,32)
    a.lw(8,6,4);a.sw(8,21,28);a.sw(0,21,24)
    a.addiu(8,0,1);a.sw(8,21,12);a.li(9,prep.CONTROL+16);a.sw(8,9)
    full.restore(a);a.addiu(2,0,1);a.jr()
    a.label('reject');full.restore(a);a.move(2,0);a.jr();return a.finish()


def tick_code():
    a=Assembler(TICK);full.save(a);save_hilo(a);a.li(21,CONTROL)
    a.lw(8,21,4);a.lw(9,28,-22364);a.branch(5,8,9,'stale')
    a.lw(22,21,16);a.lw(23,21,20);a.lw(24,21,36)
    a.lw(8,22,12);a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,23,'stale')
    a.lw(8,23,4);a.addiu(9,0,1);a.branch(5,8,9,'stale')
    a.lw(8,21,12);a.addiu(9,0,1);a.branch(5,8,9,'advance')
    a.lw(4,24,76);a.li(5,1);a.call(FORMATION);a.branch(4,2,0,'stale')
    a.lw(8,23,192);a.sw(8,21,40);a.lw(8,22,2420);a.sw(8,21,44)
    a.lw(8,23,3200);a.sw(8,21,144)
    a.lw(8,28,-22176);a.sw(8,21,48);a.lw(25,28,-22180);a.sw(25,21,52)
    a.li(9,CAMERA_SAVE)
    for off in range(0,832,4):a.lw(8,25,off);a.sw(8,9,off)
    for off in range(0,16,4):a.lw(8,23,2416+off);a.sw(8,21,64+off)
    for off in range(0,64,4):a.lw(8,22,2420+off);a.sw(8,21,80+off)
    a.lw(8,24);a.branch(4,8,0,'camera_only_start');a.sw(8,23,192)
    a.move(4,23);a.move(5,0);a.move(6,0);a.addiu(7,0,1);a.call(A(0x24D038))
    a.lw(24,21,36);a.sw(0,22,2420);a.lw(8,24,8);a.sw(8,23,3200)
    a.label('camera_only_start')
    a.lw(25,21,52);a.sw(0,25,704);a.sw(0,25,776);a.addiu(8,0,1);a.sw(8,25,812)
    a.move(4,25);a.move(5,0);a.call(A(0x23E950))
    a.lw(24,21,36);a.lw(8,24,12);a.addiu(9,0,-1);a.branch(4,8,9,'no_voice')
    a.lw(4,22);a.addiu(5,24,12);a.call(VOICE);a.label('no_voice')
    a.addiu(8,0,2);a.sw(8,21,12)
    a.label('advance')
    a.lw(24,21,36);a.lw(8,24);a.branch(4,8,0,'camera_pose')
    a.move(4,22);a.move(5,0);a.call(A(0x1C47A8))
    a.move(4,23);a.call(A(0x24C958));a.move(4,23);a.call(A(0x24E3F8))
    # Keep the model's root anchored; donor clips must not teleport its body.
    anchor(a)
    # Both position and Euler view direction use the same precomputed easing.
    # This avoids per-frame interpolation/trigonometry and mismatched aim pans.
    a.label('camera_pose');a.lw(24,21,36);a.lw(25,21,52)
    a.lw(8,21,24);a.r(0,8,0,8,5);a.lw(9,24,72);a.r(0x21,9,9,8)
    for off in range(0,12,4):
        a.i(49,0,9,off);a.i(49,1,21,64+off)
        a.emit((17<<26)|(16<<21)|(1<<16));a.i(57,0,25,720+off)
    a.li(8,0x3F800000);a.sw(8,25,732)
    for off in range(0,16,4):a.lw(8,9,16+off);a.sw(8,25,736+off)
    a.call(A(0x23D510))
    a.lw(8,21,24);a.addiu(8,8,1);a.sw(8,21,24);a.lw(9,21,28);a.r(0x2B,9,8,9);a.branch(5,9,0,'done')
    a.lw(24,21,36);a.lw(8,24);a.branch(4,8,0,'camera_only_end')
    a.lw(8,21,40);a.sw(8,23,192)
    a.move(4,22);a.lw(5,21,44);a.emit((17<<26)|(4<<21)|(12<<11));a.call(A(0x1C3E60))
    for off in range(0,64,4):a.lw(8,21,80+off);a.sw(8,22,2420+off)
    a.move(4,23);a.call(A(0x24C958));a.move(4,23);a.call(A(0x24E3F8));anchor(a)
    a.move(4,22);a.call(A(0x1D70E8))
    a.lw(8,21,144);a.sw(8,23,3200)
    a.label('camera_only_end')
    a.li(9,CAMERA_SAVE);a.lw(25,21,52)
    for off in range(0,832,4):a.lw(8,9,off);a.sw(8,25,off)
    a.lw(4,21,48);a.addiu(5,0,1);a.call(A(0x23E6A0))
    a.addiu(8,0,3);a.sw(8,21,12);a.li(8,prep.CONTROL+16);a.sw(0,8);a.jump('done')
    a.label('stale')
    # A changed world must never receive stale actor/model writes. Its normal
    # preparation owns quiet now; only release ours if the manager still matches.
    a.li(8,prep.CONTROL);a.lw(9,8,24);a.lw(10,21,4);a.branch(5,9,10,'stale_done');a.sw(0,8,16)
    a.label('stale_done');a.li(8,100);a.sw(8,21,12)
    a.label('done');restore_hilo(a);full.restore(a);a.jr()
    data=a.finish()
    if len(data)>VOICE-TICK:raise ValueError('Scenario shot exceeds its guest code reservation')
    return data


def action_key(event,action):return 1+(event<<8)+action


def anchored_animation(packed):
    """Keep a borrowed pose at its mark, without the donor's travel trajectory.

    Native bone zero drives both skeletal translation and actor root motion.
    Compensating only the actor position leaves its cached skinning/culling
    transforms behind. Remove that trajectory before native decoding instead.
    Other bones, rotation keys and animation timing remain unchanged.
    """
    import model_animations
    decoded=bytearray(model_animations.decompress_animation(packed))
    model_animations.AnimationClip.from_decoded(0,decoded)
    offset=struct.unpack_from('<H',decoded,6)[0]*4
    if not offset:return packed
    flags,count=struct.unpack_from('<HH',decoded,offset)
    if flags&1:return packed
    for i in range(count):struct.pack_into('<3f',decoded,offset+4+i*24,0,0,0)
    # Valid byte-pair packets with an identity dictionary; no compressor or
    # runtime decompression changes are needed, and the native size stays bounded.
    encoded=bytearray()
    for start in range(0,len(decoded),32767):
        block=decoded[start:start+32767]
        encoded.extend(b'\xff\x80\xfe');encoded.extend(struct.pack('>H',len(block)));encoded.extend(block)
    return struct.pack('<II',len(decoded),len(encoded))+encoded


def camera_samples(camera,frames):
    samples=bytearray()
    for frame in range(frames):
        t=frame/max(1,frames-1)
        easing=camera.get('easing','smooth')
        if easing=='smooth':t=t*t*(3-2*t)
        elif easing=='ease_in':t=t*t
        elif easing=='ease_out':t=1-(1-t)**2
        def interpolate(start,end):return [a+(b-a)*t for a,b in zip(start,end)]
        eye=interpolate(camera['eye'],camera.get('end_eye',camera['eye']))
        target=interpolate(camera['target'],camera.get('end_target',camera['target']))
        x,y,z=(b-a for a,b in zip(eye,target))
        samples.extend(struct.pack('<8f',*eye,1,-math.atan2(y,math.hypot(x,z)),math.atan2(x,z),0,1))
    return samples


def asset_blocks(ram, mission, iso=None):
    import story_runtime as story
    import model_assets, model_animations, game_profile, regional
    shots=[(i,k,x) for i,e in enumerate(story.expanded_program(mission)['events']) for k,x in enumerate(e['actions']) if x['type']=='cinematic']
    voices=[x if x['type']=='voice' else x['voice'] for e in mission['events'] for x in e['actions'] if x['type']=='voice' or (x['type']=='cinematic' and 'voice' in x)]
    if not shots and not voices:return [],{}
    if any(ram[BASE:END]):raise ValueError('Scenario cinematic memory is occupied')
    from character_names import character_table
    available=character_table()
    for voice in voices:
        if voice['character'] not in available:raise ValueError(f"Unknown voice character {voice['character']} on this disc")
    if not shots:
        return [(VOICE,voice_code())], {}
    if iso is None:
        from native_map import SERIAL
        name='SLUS_219.78.DBZBT4B14REV2ENG.iso' if SERIAL=='SLUS-21978' else regional.ISO_NAME
        iso=game_profile.source_iso(Path(__file__).resolve().parents[2]/'games'/name)
    assets={};banks={};data=bytearray();descriptors=bytearray();links={}
    for i,k,shot in shots:
        anim=shot.get('animation');donor=anim['character'] if anim else None;clip=anim['clip'] if anim else None;key=(donor,clip)
        if anim and key not in assets:
            bank=banks.setdefault(donor,None)
            if bank is None:bank=model_assets.read_animation_bank(iso,donor);banks[donor]=bank
            # Validate the full package bounds and selected decoded skeleton.
            count=struct.unpack_from('<I',bank)[0]
            if not 414<=count<=4096 or len(bank)<4*(count+2):raise ValueError('Invalid animation bank')
            start,end=(struct.unpack_from('<I',bank,4*(n+1))[0]&~3 for n in (clip,clip+1))
            if not 4*(count+2)<=start<end<=len(bank):raise ValueError(f'Animation {donor}/{clip} is absent or invalid')
            packed=anchored_animation(bank[start:end]);decoded=model_animations.decompress_animation(packed)
            model_animations.AnimationClip.from_decoded(clip,decoded)
            data.extend(bytes((-len(data))%16));assets[key]=CLIPS+len(data);data.extend(packed)
        camera=shot['camera'];voice=shot.get('voice',{})
        frames=math.ceil(shot['seconds']*ACTOR_HZ)
        data.extend(bytes((-len(data))%16));camera_address=CLIPS+len(data)
        data.extend(camera_samples(camera,frames))
        links[action_key(i,k)]=DESCRIPTORS+len(descriptors)
        descriptors.extend(struct.pack('<IIfiii12f',assets[key] if anim else 0,frames,shot['speed'],
            voice.get('character',-1),voice.get('line',0),voice.get('volume',100),
            *camera['eye'],*camera['target'],*camera.get('end_eye',camera['eye']),*camera.get('end_target',camera['target'])))
        cast_mask=sum(1<<story.physical(f) for f in mission['fighters']) if shot.get('reset_positions') else 0
        descriptors.extend(struct.pack('<2I',camera_address,cast_mask))
    if DESCRIPTORS+len(descriptors)>CLIPS or CLIPS+len(data)>END:
        raise ValueError('Scenario animation assets exceed 344 KiB; reuse clips or split this scenario')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    control=struct.pack('<3I',MAGIC,u(core.ACTORS),u(core.MODE+4))
    return [(START,start_code()),(TICK,tick_code()),(VOICE,voice_code()),(FORMATION,formation_code()),(CONTROL,control),
            (DESCRIPTORS,bytes(descriptors)),(CLIPS,bytes(data))],links
