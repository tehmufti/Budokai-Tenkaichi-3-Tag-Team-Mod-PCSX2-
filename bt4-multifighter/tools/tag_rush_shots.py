"""Reviewed native Sadistic Dance camera samples for tag-team rush attacks.

23D270 evaluates CMAn's XYZ/Euler channels linearly, except bit0x10 holds
the preceding key. 207BB8 accumulates each completed animation's duration+1.
The track is taken from donor101 combat/6/8/3, not an invented shot plan.
Only immutable per-update samples are copied to the guest; the native camera
resource is never relocated and the global cinematic track is never borrowed.
"""
from dataclasses import dataclass
import hashlib
import math
import struct

SOURCE_SHA256 = 'db69e3de969f3c078cbcdd001299e2406b8c5eecbc9791f0d700b4ae3cc24199'
PHASE_FRAMES = (68, 99, 149, 119, 262)
PHASE_STARTS = (0, 69, 169, 319, 439)
UPDATE, END = 0x06D7A800, 0x06D7C000
TABLE_OFFSET, MAGIC_OFFSET = 0xA4, 0xA8
MAGIC = 0x54435331
CUSTOM_UPDATE,CUSTOM_DATA,CUSTOM_END=0x06D88000,0x06D89000,0x06D89800


def custom_shot_data():
    """Eye and focus endpoints for smooth airborne pans and dolly shots.

    The runtime rebuilds an orthonormal look-at basis every frame; moving
    sideways therefore follows the fighters instead of retaining an old aim.
    The beam shot pulls back at the end to leave room for its impact burst.
    """
    views=(
        ((108.,-30.,96.),(93.,-20.,72.),(0.,-8.,0.),(0.,-8.,0.)),
        ((140.,-24.,62.),(156.,-30.,86.),(0.,-9.,0.),(0.,-8.,0.)),
        ((34.,-20.,28.),(-30.,-12.,30.),(0.,-9.,0.),(0.,-7.,0.)),
        ((30.,3.,26.),(20.,-25.,24.),(0.,-9.,0.),(0.,-5.,0.)),
        ((22.,-8.,28.),(38.,30.,8.),(0.,-8.,0.),(0.,38.,-30.)),
        ((38.,-56.,82.),(62.,-62.,96.),(-16.,-37.,0.),(-10.,-36.,0.)),
        ((32.,-20.,89.),(40.,-18.,81.),(0.,-10.,63.),(0.,-10.,61.)),
        ((-40.,-24.,-32.),(-32.,-14.,-28.),(0.,-10.,0.),(0.,-8.,0.)),
        ((44.,-36.,32.),(50.,-30.,-16.),(0.,-22.,0.),(0.,-20.,0.)),
        ((32.,-6.,28.),(42.,-42.,32.),(0.,-25.,0.),(0.,-28.,0.)),
        ((40.,-4.,34.),(22.,-40.,36.),(0.,-10.,0.),(0.,-38.,0.)),
        ((-58.,-45.,28.),(-54.,-44.,24.),(-42.,-38.,0.),(-42.,-38.,0.)),
        ((-30.,-13.,28.),(-26.,-12.,24.),(0.,-11.,0.),(0.,-11.,0.)),
        ((-18.,-14.,-30.),(-14.,-13.,-34.),(0.,-12.,-58.),(0.,-12.,-58.)),
        ((74.,-16.,-64.),(86.,-18.,-78.),(0.,-11.,-15.),(0.,-10.,-12.)),
    )
    return b''.join(struct.pack('<16f',*(v for point in row for v in (*point,1.))) for row in views)


def custom_sample(shot,fraction):
    """Reference evaluator for the exact emitted moving look-at camera."""
    values=struct.unpack_from('<16f',custom_shot_data(),(shot-1)*64)
    t=max(0.,min(1.,fraction))
    if shot in (2,6,15):
        import tag_rush_choreography as choreography
        frame=t*choreography.BEAM_FRAMES
        close=struct.unpack_from('<16f',custom_shot_data(),(13 if shot==15 else 11 if shot==6 else 6)*64)
        if frame<choreography.CHARGE_CLOSEUP:
            values=close;t=frame/choreography.CHARGE_CLOSEUP
        elif frame<choreography.BEAM_START:
            values=(*close[4:8],*values[:4],*close[12:16],*values[8:12])
            t=(frame-choreography.CHARGE_CLOSEUP)/(choreography.BEAM_START-choreography.CHARGE_CLOSEUP)
        else:t=(frame-choreography.BEAM_START)/(choreography.BEAM_FRAMES-choreography.BEAM_START)
    t=t*t*(3.-2.*t)
    eye=tuple(values[i]+(values[4+i]-values[i])*t for i in range(3))
    target=tuple(values[8+i]+(values[12+i]-values[8+i])*t for i in range(3))
    forward=tuple(b-a for a,b in zip(eye,target));n=math.sqrt(sum(v*v for v in forward));forward=tuple(v/n for v in forward)
    right=(forward[2],0.,-forward[0]);n=math.sqrt(sum(v*v for v in right));right=tuple(v/n for v in right)
    down=(forward[1]*right[2]-forward[2]*right[1],forward[2]*right[0]-forward[0]*right[2],forward[0]*right[1]-forward[1]*right[0])
    return (*right,0.,*down,0.,*forward,0.,*eye,1.),target


def special_hold_fraction(phase,ticks,hz=None):
    """One continuous held-pair pan before the single Piccolo charge cut."""
    import tag_rush_special_pair as special
    from native_map import ACTOR_HZ
    hz=ACTOR_HZ if hz is None else hz
    if type(phase)is not int or not 0<=phase<4 or not math.isfinite(ticks)or ticks<0 or hz<=0:
        raise ValueError('Invalid special hold-camera clock')
    prefix=sum(row[4]for row in special.SEGMENTS[:phase])
    duration=sum(row[4]for row in special.SEGMENTS[:4])
    return max(0.,min(1.,(prefix+ticks*60/hz)/duration))


def custom_update_code():
    """a0 phase,a1 ticks,a2 descriptor -> v0. Private common-origin camera."""
    from native_map import A,ACTOR_HZ
    from prototype import Assembler
    import tag_rush_camera as camera,tag_rush_staging as staging,tag_team_rush as tag
    import fusion_partner_lifecycle as full,beam_struggle as fp,tag_rush_special_pair as special
    a=Assembler(CUSTOM_UPDATE);camera.save(a);a.addiu(29,29,-0x100)
    a.sw(4,29,0xF8);a.move(16,5);a.move(17,6);full.pointer(a,17,64,'no')
    a.call(staging.QUERY);a.branch(4,2,0,'no');a.lw(8,2);a.li(9,1);a.branch(5,8,9,'no')
    a.lw(8,2,4);a.addiu(8,8,-1);a.i(11,9,8,15);a.branch(4,9,0,'no')
    a.sw(8,29,0xF4)
    a.r(0,8,0,8,6);a.li(18,CUSTOM_DATA);a.r(0x21,18,18,8)
    a.li(19,tag.MEMBERS_SAVE)
    for off in (104,108,112,116,120,132):
        a.lw(8,19,off);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,'no')
    a.lw(8,17);a.addiu(9,8,-1);a.i(11,9,9,3600);a.branch(4,9,0,'no')
    a.emit((17<<26)|(4<<21)|(16<<16)|(0<<11));a.emit((17<<26)|(20<<21)|(0<<11)|(0<<6)|32)
    a.emit((17<<26)|(4<<21)|(8<<16)|(1<<11));a.emit((17<<26)|(20<<21)|(1<<11)|(1<<6)|32)
    fp.fconst(a,2,60/ACTOR_HZ);fp.fop(a,2,0,0,2)
    # The special restraint spans four descriptors but is a single slow pan.
    # Restarting this shot at every crop seam looked like a repeated/stuttering
    # Piccolo setup. Only variant4/shot13 inherits the preceding source clock.
    a.lw(8,29,0xF4);a.li(9,12);a.branch(5,8,9,'hold_clock_ready')
    a.li(8,tag.CONTROL);a.lw(8,8,tag.C['variant']);a.li(9,special.VARIANT)
    a.branch(5,8,9,'hold_clock_ready');a.lw(8,29,0xF8)
    a.i(11,9,8,4);a.branch(4,9,0,'no')
    prefix=0
    for index,segment in enumerate(special.SEGMENTS[:4]):
        next_phase='hold_camera_phase'+str(index)
        a.li(9,index);a.branch(5,8,9,next_phase)
        fp.fconst(a,2,prefix);fp.fop(a,0,0,0,2);a.jump('hold_prefix_ready')
        a.label(next_phase);prefix+=segment[4]
    a.label('hold_prefix_ready');fp.fconst(a,1,prefix)
    a.label('hold_clock_ready')
    # Charge and fire share one descriptor and one emitter. Only its camera
    # changes: own-character charge closeup, pullback, then the wide impact.
    a.lw(8,29,0xF4);a.li(9,1);a.branch(4,8,9,'beam_clock')
    a.li(9,5);a.branch(4,8,9,'beam_clock');a.li(9,14);a.branch(5,8,9,'normal_clock')
    a.label('beam_clock');fp.fconst(a,2,60.);fp.fop(a,0x34,0,0,2)
    a.branch(17,8,0,'pull_back');a.li(18,CUSTOM_DATA+6*64)
    a.lw(8,29,0xF4);a.li(9,14);a.branch(5,8,9,'ordinary_charge_closeup')
    a.li(18,CUSTOM_DATA+13*64);a.jump('charge_closeup_ready')
    a.label('ordinary_charge_closeup');a.li(9,5);a.branch(5,8,9,'charge_closeup_ready');a.li(18,CUSTOM_DATA+11*64)
    a.label('charge_closeup_ready');fp.fop(a,6,1,2)
    a.jump('normal_clock')
    a.label('pull_back');fp.fconst(a,2,90.);fp.fop(a,0x34,0,0,2)
    a.branch(17,8,0,'beam_wide')
    a.li(8,CUSTOM_DATA+6*64);a.lw(9,29,0xF4);a.li(10,14)
    a.branch(5,9,10,'ordinary_closeup_source');a.li(8,CUSTOM_DATA+13*64);a.jump('closeup_source_ready')
    a.label('ordinary_closeup_source');a.li(10,5)
    a.branch(5,9,10,'closeup_source_ready');a.li(8,CUSTOM_DATA+11*64)
    a.label('closeup_source_ready')
    for source,target in ((16,0),(48,32)):
        for off in range(0,16,4):a.lw(9,8,source+off);a.sw(9,29,0x80+target+off)
    for source,target in ((0,16),(32,48)):
        for off in range(0,16,4):a.lw(9,18,source+off);a.sw(9,29,0x80+target+off)
    a.addiu(18,29,0x80);fp.fconst(a,2,60.);fp.fop(a,1,0,0,2);fp.fconst(a,1,30.)
    a.jump('normal_clock')
    a.label('beam_wide');fp.fop(a,1,0,0,2);fp.fop(a,1,1,1,2)
    a.label('normal_clock');fp.fop(a,3,0,0,1)
    fp.fconst(a,1,1.);fp.fop(a,0x34,0,1,0);a.branch(17,8,0,'clock');fp.fop(a,6,0,1)
    a.label('clock')
    fp.fop(a,2,2,0,0);fp.fconst(a,1,2.);fp.fop(a,2,0,0,1)
    fp.fconst(a,1,3.);fp.fop(a,1,0,1,0);fp.fop(a,2,0,0,2);a.i(57,0,29,0xF0)
    for off in (0,4,8):
        for source,dest in ((0,48),(32,0x60)):
            a.i(49,0,18,source+off);a.i(49,1,18,source+16+off);a.i(49,2,29,0xF0)
            fp.fop(a,1,1,1,0);fp.fop(a,2,1,1,2);fp.fop(a,0,0,0,1)
            a.i(49,1,19,108 if off==4 else 104);fp.fop(a,2,0,0,1);a.i(57,0,29,dest+off)
    # Forward=(focus-eye)/length, right=(forwardZ,0,-forwardX), down=F x R.
    for f,off in enumerate((0,4,8)):
        a.i(49,f,29,0x60+off);a.i(49,3,29,48+off);fp.fop(a,1,f,f,3)
    fp.fop(a,2,3,0,0);fp.fop(a,2,4,1,1);fp.fop(a,0,3,3,4)
    fp.fop(a,2,4,2,2);fp.fop(a,0,3,3,4);fp.fop(a,4,3,3,3)
    fp.fconst(a,4,.001);fp.fop(a,0x34,0,3,4);a.branch(17,8,1,'no')
    for f,off in enumerate((32,36,40)):fp.fop(a,3,f,f,3);a.i(57,f,29,off)
    fp.fop(a,2,3,0,0);fp.fop(a,2,4,2,2);fp.fop(a,0,3,3,4);fp.fop(a,4,3,3,3)
    fp.fconst(a,4,.001);fp.fop(a,0x34,0,3,4);a.branch(17,8,1,'no')
    fp.fop(a,3,4,2,3);fp.fop(a,3,5,0,3);fp.fconst(a,6,-1.);fp.fop(a,2,5,5,6)
    a.i(57,4,29,0);a.sw(0,29,4);a.i(57,5,29,8)
    fp.fop(a,2,6,1,5);a.i(57,6,29,16)
    fp.fop(a,2,6,2,4);fp.fop(a,2,7,0,5);fp.fop(a,1,6,6,7);a.i(57,6,29,20)
    fp.fop(a,2,6,1,4);fp.fconst(a,7,-1.);fp.fop(a,2,6,6,7);a.i(57,6,29,24)
    for off in (12,28,44):a.sw(0,29,off)
    a.li(8,0x3F800000);a.sw(8,29,60)
    a.lw(20,28,-22180);a.lw(21,28,-22176);a.lw(22,28,-22172)
    full.pointer(a,21,832,'no');full.pointer(a,22,0xC44,'no');a.lw(23,22,0xC40)
    a.addiu(4,29,0x80);a.call(A(0x120098))
    a.addiu(4,29,0x80);a.move(5,4);a.i(49,12,19,132);a.call(A(0x120428))
    for off in range(0,16,4):a.lw(8,19,112+off);a.sw(8,29,0xB0+off)
    # Portrait-view fitting must use this shot's actual world focus. The
    # generic scene focus is not populated by the authored-camera path and
    # otherwise remains world zero, turning a closeup into a distant shot.
    # Apply the exact same yaw/origin matrix as the camera eye below.
    for off in (0,4,8):
        a.i(49,0,29,0xB0+off)
        for axis in range(3):
            a.i(49,1,29,0x60+axis*4);a.i(49,2,29,0x80+axis*16+off)
            fp.fop(a,2,1,1,2);fp.fop(a,0,0,0,1)
        a.i(57,0,19,64+off)
    a.li(8,0x3F800000);a.sw(8,19,76)
    a.move(4,29);a.addiu(5,29,0x80);a.move(6,29);a.call(A(0x1201B8))
    a.li(24,camera.CAMERA)
    for off in range(0,16,4):a.lw(8,29,48+off);a.sw(8,24,720+off)
    a.addiu(4,24,64);a.move(5,29);a.call(A(0x1202A0))
    a.li(4,camera.CAMERA+64);a.call(A(0x121408))
    a.li(4,camera.CAMERA);a.addiu(5,4,64);a.call(A(0x120230))
    a.li(4,camera.CAMERA);a.addiu(5,4,720);a.call(A(0x23E598))
    a.move(4,21);a.li(5,1);a.call(A(0x23E6A0))
    a.sw(20,28,-22180);a.sw(21,28,-22176);a.sw(23,22,0xC40)
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');a.addiu(29,29,0x100);camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert CUSTOM_UPDATE+len(data)<=CUSTOM_DATA;return data


class CameraFormatError(ValueError):pass


def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]


@dataclass(frozen=True)
class Key:
    flags:int
    frame:float
    value:float


@dataclass(frozen=True)
class Track:
    end:float
    defaults:tuple
    channels:tuple

    def sample(self,frame):
        if not math.isfinite(frame) or not 0<=frame<=self.end:
            raise CameraFormatError('Camera frame outside the reviewed timeline')
        frame=f32(frame);out=list(self.defaults)
        for channel,keys in self.channels:
            previous=following=None
            for key in keys:
                if key.frame==frame:previous=key;break
                if key.frame<frame:previous=key
                else:following=key;break
            if previous is None:value=following.value
            elif following is None or previous.flags&0x10:value=previous.value
            else:
                ratio=f32(f32(frame-previous.frame)/f32(following.frame-previous.frame))
                value=f32(f32(f32(following.value-previous.value)*ratio)+previous.value)
            out[channel]=value
        return tuple(out)


def parse_track(raw):
    """Validate relative-offset source data, without native in-place fixups."""
    if len(raw)<80 or raw[:4]!=b'CMAn':raise CameraFormatError('Missing native camera track')
    version,table,count=struct.unpack_from('<3I',raw,4)
    begin,end=struct.unpack_from('<2f',raw,16)
    defaults,events,event_count=struct.unpack_from('<3I',raw,24)
    if version!=6 or count!=6 or begin!=0 or not math.isfinite(end) or not 0<end<=1000:
        raise CameraFormatError('Unexpected native camera header')
    if table<80 or table%16 or table+16*count>len(raw) or defaults!=48 or event_count:
        raise CameraFormatError('Unsupported native camera table or events')
    if not table+16*count<=events<=len(raw):raise CameraFormatError('Invalid native camera event boundary')
    initial=struct.unpack_from('<6f',raw,defaults)
    if not all(math.isfinite(x) for x in initial):raise CameraFormatError('Nonfinite camera defaults')
    channels=[];spans=[]
    for index in range(count):
        channel,start,n,reserved=struct.unpack_from('<4I',raw,table+index*16)
        if channel!=index or not 1<=n<=1024 or start%16 or start<table+16*count or start+n*32>events:
            raise CameraFormatError('Invalid native camera key table')
        keys=[]
        for j in range(n):
            flags,frame,value=struct.unpack_from('<I2f',raw,start+j*32)
            if flags not in (0x12,0x22) or not all(math.isfinite(v) for v in (frame,value)):
                raise CameraFormatError('Unsupported native camera key')
            if not 0<=frame<=end or keys and frame<=keys[-1].frame:
                raise CameraFormatError('Unordered native camera keys')
            if abs(value)>(2048 if channel<3 else 4*math.pi):raise CameraFormatError('Unbounded camera channel')
            keys.append(Key(flags,frame,value))
        if keys[0].frame!=0 or keys[-1].frame!=end:
            raise CameraFormatError('Incomplete native camera channel')
        spans.append((start,start+n*32));channels.append((channel,tuple(keys)))
    spans.sort()
    if any(hi>lo for (_,hi),(lo,_) in zip(spans,spans[1:])):
        raise CameraFormatError('Overlapping native camera channels')
    return Track(end,initial,tuple(channels))


def read_track(iso):
    import model_assets
    try:import bt4_resources
    except ImportError:combat=2443
    else:combat=5501
    raw=model_assets.read_archive_entry(iso,combat)
    for entry in (6,8,3):raw=model_assets.package_entry(raw,entry)
    if len(raw)!=14592 or hashlib.sha256(raw).hexdigest()!=SOURCE_SHA256:
        raise CameraFormatError('Sadistic Dance camera differs from the reviewed disc resource')
    track=parse_track(raw)
    if track.end!=701:raise CameraFormatError('Unexpected paired-rush camera duration')
    return track


def build_samples(iso,base,actor_hz):
    """Five {samples,count,start,frames} rows; samples are XYZ1/EulerXYZ1.

    Sample at the director's real tick clock, including PAL fractional frames.
    Never interpolate across an authored cut at a phase boundary.
    """
    if type(base) is not int or base%16 or actor_hz not in (25,30):
        raise CameraFormatError('Invalid tag-camera sample layout')
    track=read_track(iso);data=bytearray(80);phases=[];all_positions=[]
    for phase,(start,frames) in enumerate(zip(PHASE_STARTS,PHASE_FRAMES)):
        count=math.ceil(frames*actor_hz/60);address=base+len(data)
        for tick in range(1,count+1):
            local=min(f32(tick*f32(60/actor_hz)),float(frames))
            xyz_angles=track.sample(f32(start+local))
            data.extend(struct.pack('<8f',*xyz_angles[:3],1.,*xyz_angles[3:],1.))
            all_positions.append(xyz_angles[:3])
        struct.pack_into('<4I',data,phase*16,address,count,start,frames)
        phases.append(dict(address=address,count=count,source_start=start,source_frames=frames))
    return bytes(data),dict(table_address=base,actor_hz=actor_hz,phases=phases,
        source_sha256=SOURCE_SHA256,reviewed=True,
        max_horizontal=max(math.hypot(x,z) for x,y,z in all_positions),
        max_upward=max(-y for x,y,z in all_positions))


def update_code():
    """a0 phase,a1 ticks,a2 lead,a3 scales,a4 phase,a5 partner ->v0.

    Reproduce 23D510's local XYZ/Euler -> lead model2464 -> inverse-view
    chain using its exact X,Y,Z rotation/multiplication call order at
    23D844..23D8D8. No guessed Euler/yaw composition.
    """
    from native_map import A
    from prototype import Assembler
    import tag_rush_camera as camera
    import tag_rush_assets as assets
    import beam_struggle as fp
    import fusion_partner_lifecycle as full
    a=Assembler(UPDATE);camera.save(a);a.addiu(29,29,-0x100);a.move(23,8);a.move(22,9)
    camera.emit_active(a,'no')
    full.pointer(a,23,64,'no');a.lw(8,23,28);a.i(12,8,8,assets.CUSTOM_FINISHER)
    a.branch(4,8,0,'native_shot');a.move(6,23);a.call(CUSTOM_UPDATE);a.jump('done')
    a.label('native_shot')
    a.i(11,9,4,5);a.branch(4,9,0,'no');a.branch(6,5,0,'no')
    a.move(18,6);a.move(19,7);full.pointer(a,23,64,'no')
    a.lw(20,23,28);a.lw(23,23,60);full.pointer(a,23,12,'no')
    # The non-ki lead returns to an idle at its posed airborne location. Its
    # new model root must not be added to the original camera travel again.
    # A partner-only beam keeps the authored shot on the partner's unchanged
    # phase root and height; the other variants keep their original owner.
    a.li(9,4);a.branch(5,4,9,'lead_owner')
    a.i(12,20,20,assets.BEAM_LEAD|assets.BEAM_PARTNER)
    a.li(9,assets.BEAM_PARTNER);a.branch(5,20,9,'lead_owner')
    a.move(18,22);a.lw(23,23,4);a.jump('owner_ready')
    a.label('lead_owner');a.lw(23,23)
    a.label('owner_ready');full.pointer(a,18,0x1700,'no');full.pointer(a,19,8,'no')
    full.pointer(a,23,2336,'no')
    a.lw(20,18,2332);a.lw(21,23,2332)
    for ptr in (20,21):full.pointer(a,ptr,8,'no')
    a.li(8,camera.CONTROL);a.lw(9,8,MAGIC_OFFSET);a.li(10,MAGIC);a.branch(5,9,10,'no')
    a.lw(8,8,TABLE_OFFSET);a.li(9,assets.BASE);a.r(0x2B,10,8,9);a.branch(5,10,0,'no')
    a.li(9,assets.END-80);a.r(0x2B,10,9,8);a.branch(5,10,0,'no')
    a.i(12,9,8,15);a.branch(5,9,0,'no');a.r(0,9,0,4,4);a.r(0x21,8,8,9)
    a.lw(17,8);a.lw(9,8,4);a.branch(6,9,0,'no');a.i(11,10,9,133);a.branch(4,10,0,'no')
    a.addiu(16,5,-1);a.r(0x2B,10,16,9);a.branch(5,10,0,'tick_ok');a.addiu(16,9,-1)
    a.label('tick_ok');a.li(10,assets.BASE);a.r(0x2B,11,17,10);a.branch(5,11,0,'no')
    a.li(10,assets.END-32);a.r(0x2B,11,10,17);a.branch(5,11,0,'no')
    a.r(0,9,0,9,5);a.r(0x21,9,17,9);a.li(10,assets.END);a.r(0x2B,11,10,9);a.branch(5,11,0,'no')
    a.i(12,9,17,15);a.branch(5,9,0,'no');a.r(0,16,0,16,5);a.r(0x21,17,17,16)
    # Retained coordinates and scales are finite before native matrix calls.
    for ptr,offsets in ((17,range(0,32,4)),(19,(0,4)),(18,range(2464,2528,4)),(20,(4,)),(21,(4,))):
        for off in offsets:
            a.lw(8,ptr,off);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,'no')
    for off in (0,4):
        a.i(49,0,19,off);fp.fconst(a,1,0.0);fp.fop(a,0x34,0,1,0);a.branch(17,8,0,'no')
        fp.fconst(a,1,64.0);fp.fop(a,0x34,0,1,0);a.branch(17,8,1,'no')
    # 24E2B0 bakes model2592 into model2464; canonical giants multiply it
    # temporarily too. Strip that uniform basis scale from a PRIVATE copy,
    # otherwise the per-cast framing adjustment below would apply it twice.
    fp.fconst(a,2,0.0)
    for off in (0,4,8):
        a.i(49,0,18,2464+off);fp.fop(a,2,0,0,0);fp.fop(a,0,2,2,0)
    fp.fop(a,4,2,2,2);fp.fconst(a,1,.0001);fp.fop(a,0x34,0,1,2);a.branch(17,8,0,'no')
    fp.fconst(a,1,64.0);fp.fop(a,0x34,0,1,2);a.branch(17,8,1,'no')
    # Native shots belong to their animation owner. The largest cast member
    # only governs scene clearance: using a taller victim's height here lifts
    # a close beam shot above both attackers. Match the lead's retargeted
    # translations, while retaining the real root scale exactly once.
    a.i(57,2,29,0x50)
    a.i(49,0,20,4);a.i(49,3,21,4);fp.fconst(a,1,.0001)
    for value in (0,3):fp.fop(a,0x34,0,1,value);a.branch(17,8,0,'no')
    fp.fop(a,3,0,0,3);fp.fop(a,2,0,0,2)
    fp.fconst(a,1,64.0);fp.fop(a,0x34,0,1,0);a.branch(17,8,1,'no')
    a.i(57,0,29,0x54)
    for row in range(3):
        for col in range(3):
            off=16*row+4*col;a.i(49,0,18,2464+off);fp.fop(a,3,0,0,2);a.i(57,0,29,0xC0+off)
        a.sw(0,29,0xCC+row*16)
    for off in range(0,16,4):a.lw(8,18,2512+off);a.sw(8,29,0xF0+off)
    for off in range(0,16,4):a.lw(8,17,16+off);a.sw(8,29,0x40+off)
    a.lw(20,28,-22180);a.lw(21,28,-22176);a.lw(22,28,-22172)
    full.pointer(a,21,832,'no');full.pointer(a,22,0xC44,'no');a.lw(23,22,0xC40)
    a.move(4,29);a.call(A(0x120098))
    for off,function in ((0,0x120398),(4,0x120428),(8,0x120308)):
        a.addiu(4,29,0x80);a.call(A(0x120098))
        a.addiu(4,29,0x80);a.move(5,4);a.i(49,12,29,0x40+off);a.call(A(function))
        a.move(4,29);a.addiu(5,29,0x80);a.move(6,29);a.call(A(0x1201B8))
    for off in (0,4,8):
        a.i(49,0,17,off);a.i(49,1,29,0x54 if off==4 else 0x50);fp.fop(a,2,0,0,1);a.i(57,0,29,48+off)
    a.li(8,0x3F800000);a.sw(8,29,60)
    a.move(4,29);a.addiu(5,29,0xC0);a.move(6,29);a.call(A(0x1201B8))
    a.li(24,camera.CAMERA)
    for off in range(0,16,4):a.lw(8,29,48+off);a.sw(8,24,720+off)
    a.addiu(4,24,64);a.move(5,29);a.call(A(0x1202A0))
    a.li(4,camera.CAMERA+64);a.call(A(0x121408))
    # Split-view consumers retain both native view-matrix blocks.
    a.li(4,camera.CAMERA);a.addiu(5,4,64);a.call(A(0x120230))
    a.li(4,camera.CAMERA);a.addiu(5,4,720);a.call(A(0x23E598))
    a.move(4,21);a.li(5,1);a.call(A(0x23E6A0))
    a.sw(20,28,-22180);a.sw(21,28,-22176);a.sw(23,22,0xC40)
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');a.addiu(29,29,0x100);camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert UPDATE+len(data)<=END,len(data);return data


def pieces():return [(UPDATE,update_code()),(CUSTOM_UPDATE,custom_update_code()),(CUSTOM_DATA,custom_shot_data())]
