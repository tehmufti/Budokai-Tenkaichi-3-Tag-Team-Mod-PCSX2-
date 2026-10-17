"""Two native beam SFX in a private, checked SPU bank for local tag attacks.

The source bank's sequence/header layout is retained, but every sample except
Goku's primary beam charge45 and fire46 is replaced by native silence. No voice
sample is copied. The allocator preflight mirrors11EDC8's17-entry free list;
IOP allocations are checked before the native asynchronous upload is registered.
Only a matching private row may be stopped/unloaded, after native transfer drain.
"""
import hashlib
import struct
from functools import lru_cache
from pathlib import Path
from prototype import Assembler
from native_map import A, ACTOR_HZ
import tag_team_rush as tag
import tag_rush_camera as camera
import fusion_partner_lifecycle as full

INIT,TICK,RELEASE,EXIT=0x06DB0000,0x06DB1000,0x06DB2000,0x06DB2800
# BT4 paired-beam code reservation, between CODE_END and its DATA.
IMPACT,IMPACT_END=0x06EDD000,0x06EDE000
STATE,DATA,END=0x06DB3000,0x06DB4000,0x06DC0000
HOOK=A(0x128884)
NATIVE_HOOK=struct.pack('<I',(3<<26)|(A(0x124A28)>>2))
INSTALLED_HOOK=struct.pack('<I',(3<<26)|(EXIT>>2))
MAGIC=0x54425331
S=dict(magic=0,manager=4,sound=8,status=12,mask=16,row=20,spu=24,header=28,sequence=32,
       charge=36,fire=40,stops=44,error=48,active=52,last_phase=56,roles=60,
       body_size=64,header_size=68,sequence_size=72,raw_header=76,raw_sequence=80,bank_data=84)
WAITING,UPLOADING,READY,FAILED,CLOSED=0,1,2,3,4
SPU_TABLE=A(0x300DC8)


def _u(data,at):return struct.unpack_from('<I',data,at)[0]


def isolate_bank(original, ultimate=None):
    """Preserve native sequence commands; copy only the reviewed nonvoice SFX."""
    import sys
    from prototype import ROOT
    if str(ROOT.parent) not in sys.path:sys.path.insert(0,str(ROOT.parent))
    from iso_compatibility.disc import package
    parts=package(original)
    if len(parts)!=3:raise ValueError('Unexpected native beam sound package')
    body,header,sequence=[bytearray(original[a:b])for a,b in parts]
    if header[:8]!=b'IECSsreV' or header[16:24]!=b'IECSdaeH':raise ValueError('Unknown native beam sound header')
    table=_u(header,48);count=_u(header,table+12)+1
    if header[table:table+8]!=b'IECSigaV' or count!=57:raise ValueError('Native beam sample table changed')
    rows=[table+_u(header,table+16+4*i)for i in range(count)]
    if any(row<0 or row+8>len(header)for row in rows):raise ValueError('Native beam sample row escaped header')
    offsets=[_u(header,row)for row in rows]+[_u(header,32)]
    if offsets[0]!=0 or any(a>b or a%16 for a,b in zip(offsets,offsets[1:]))or offsets[-1]>len(body):
        raise ValueError('Native beam ADPCM offsets changed')
    silence=bytes(body[offsets[47]:offsets[48]])
    if silence!=bytes.fromhex('000000000000000000000000000000000c01000000000000000000000000000007007777777777777777777777777777'):
        raise ValueError('Native silent sample changed')
    selected={i:bytes(body[offsets[i]:offsets[i+1]])for i in (45,46)}
    if any(not 4096<=len(wave)<=32768 for wave in selected.values()):raise ValueError('Native beam SFX lengths changed')
    if ultimate is not None:
        # Teen Gohan SSJ2's Father-Son Kamehameha beam and impact.
        # Its sequence programs are identical to this 57-program bank; only
        # the two reviewed ADPCM samples/pitches are imported, never voices.
        uparts=package(ultimate)
        if len(uparts)!=3:raise ValueError('Unexpected Father-Son Kamehameha sound package')
        ub,uh,us=[ultimate[a:b]for a,b in uparts];ut=_u(uh,48)
        if us!=sequence or uh[ut:ut+8]!=b'IECSigaV' or _u(uh,ut+12)!=56:
            raise ValueError('Father-Son Kamehameha sound programs changed')
        ur=[ut+_u(uh,ut+16+4*i)for i in range(57)];uo=[_u(uh,r)for r in ur]+[_u(uh,32)]
        if any(a>b or a%16 for a,b in zip(uo,uo[1:])) or uo[-1]>len(ub):raise ValueError('Invalid ultimate ADPCM offsets')
        for i in (54,55):
            selected[i]=bytes(ub[uo[i]:uo[i+1]])
            if not 4096<=len(selected[i])<=32768:raise ValueError('Ultimate SFX length changed')
            header[rows[i]+4:rows[i]+6]=uh[ur[i]+4:ur[i]+6]
        from tag_rush_sound_sample import at_rate
        native_rate=struct.unpack_from('<H',header,rows[55]+4)[0]
        selected[55]=at_rate(selected[55],native_rate,12000)
        struct.pack_into('<H',header,rows[55]+4,12000)
    wave=bytearray()
    for i,row in enumerate(rows):
        struct.pack_into('<I',header,row,len(wave));header[row+6]=0
        wave.extend(selected.get(i,silence))
    struct.pack_into('<I',header,32,len(wave))
    chunks=(wave,header,sequence);result=bytearray(64)
    struct.pack_into('<I',result,0,3)
    sizes=[]
    for i,chunk in enumerate(chunks):
        struct.pack_into('<I',result,4+4*i,len(result));before=len(result)
        result.extend(chunk);result.extend(bytes((-len(result))%64));sizes.append(len(result)-before)
    struct.pack_into('<I',result,16,len(result))
    if len(result)>(96*1024 if ultimate is not None else END-DATA):raise ValueError('Private native beam bank exceeds reservation')
    return dict(data=bytes(result),sizes=tuple(sizes),sample_sha256={i:hashlib.sha256(v).hexdigest()for i,v in selected.items()},
                header_offset=_u(result,8),sequence_offset=_u(result,12))


@lru_cache(maxsize=4)
def disc_bank(iso):
    # Explicit selected-disc reader, independent of local developer settings.
    import sys
    from prototype import ROOT
    if str(ROOT.parent) not in sys.path:sys.path.insert(0,str(ROOT.parent))
    from iso_compatibility.disc import Disc
    import regional
    from native_map import SERIAL
    if SERIAL=='SLUS-21978':
        with Disc(Path(iso))as disc:return isolate_bank(disc.read(0x1D012),disc.read(0x1D012+16))
    elif regional.DISC_REGION!='US':
        with regional.open_disc(Path(iso))as disc:data=disc.read(regional.FILE_ID(3034))
    else:
        with Disc(Path(iso))as disc:data=disc.read(3034)
    return isolate_bank(data)


def _owner(a,fail):
    a.li(16,STATE);a.lw(8,16,S['magic']);a.li(9,MAGIC);a.branch(5,8,9,fail)
    a.lw(17,16,S['sound']);full.pointer(a,17,680,fail)
    a.lw(8,28,-20708);a.branch(5,8,17,fail)
    a.lw(18,16,S['row']);full.pointer(a,18,76,fail)
    a.lw(19,16,S['mask']);a.li(8,64);a.branch(4,19,8,'owner6')
    a.li(8,128);a.branch(5,19,8,fail);a.addiu(8,17,76*7);a.jump('owner_row')
    a.label('owner6');a.addiu(8,17,76*6);a.label('owner_row');a.branch(5,8,18,fail)
    for rowoff,key in ((0,'spu'),(4,'sequence'),(8,'header')):
        a.lw(8,18,rowoff);a.lw(9,16,S[key]);a.branch(4,9,0,fail);a.branch(5,8,9,fail)
    for rowoff,key in ((12,None),(16,'raw_header'),(20,'raw_sequence')):
        a.lw(8,18,rowoff)
        if key:a.lw(9,16,S[key])
        else:a.lw(9,16,S['bank_data']);a.addiu(9,9,64)
        a.branch(5,8,9,fail)


def init_code():
    a=Assembler(INIT);tag.save(a);a.li(16,STATE)
    a.lw(8,16,S['magic']);a.li(9,MAGIC);a.branch(5,8,9,'fail')
    a.lw(8,16,S['status']);a.li(9,UPLOADING);a.branch(4,8,9,'poll')
    a.li(9,READY);a.branch(4,8,9,'ready_check');a.branch(5,8,0,'no')
    a.lw(8,16,S['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'fail')
    a.lw(17,28,-20708);full.pointer(a,17,680,'fail');a.sw(17,16,S['sound'])
    # No other upload may be in flight while adding the small bank.
    for i in range(8):
        for off in (48,52):a.lw(8,17,76*i+off);a.branch(5,8,0,'wait')
    a.li(19,64);a.addiu(18,17,76*6)
    for i in range(19):a.lw(8,18,4*i);a.branch(5,8,0,'try7')
    a.jump('bank_found');a.label('try7');a.li(19,128);a.addiu(18,17,76*7)
    for i in range(19):a.lw(8,18,4*i);a.branch(5,8,0,'occupied')
    a.label('bank_found');a.sw(19,16,S['mask']);a.sw(18,16,S['row'])
    #11EDC8 has no failure branch. Require one spare record and a contiguous
    # free block big enough before invoking it; aggregate free bytes is unsafe.
    a.move(20,0);a.move(21,0);a.li(22,SPU_TABLE);a.li(23,17)
    a.lw(8,16,S['body_size']);a.addiu(8,8,63);a.li(9,0xFFFFFFC0);a.r(0x24,8,8,9);a.sw(8,29,0x300)
    a.label('scan');a.lw(8,22);a.branch(5,8,0,'not_empty');a.li(20,1)
    a.label('not_empty');a.li(9,1);a.branch(5,8,9,'next');a.lw(8,22,8);a.lw(9,29,0x300)
    a.r(0x2B,8,8,9);a.branch(5,8,0,'next');a.li(21,1)
    a.label('next');a.addiu(22,22,12);a.addiu(23,23,-1);a.branch(5,23,0,'scan')
    a.branch(4,20,0,'space');a.branch(4,21,0,'space')
    # Checked equivalents of1246E0's allocation branch. IOP failures cannot
    # reach1240F0 with null pointers or consume a native character bank.
    for key in ('header','sequence'):
        a.lw(4,16,S[key+'_size']);a.call(A(0x11EC28));a.branch(6,2,0,'allocation')
        a.sw(2,16,S[key])
    a.lw(4,16,S['body_size']);a.call(A(0x11EDC8));a.branch(6,2,0,'allocation');a.sw(2,16,S['spu'])
    for off,key in ((0,'spu'),(4,'sequence'),(8,'header'),(36,'body_size'),(40,'header_size'),(44,'sequence_size')):
        a.lw(8,16,S[key]);a.sw(8,18,off)
    a.move(4,18);a.move(5,19);a.lw(6,16,S['bank_data']);a.move(7,0);a.call(A(0x1246E0))
    a.move(4,18);a.move(5,0);a.call(A(0x1248A0))
    a.move(4,19);a.lw(5,18);a.lw(6,18,8);a.lw(7,18,4);a.call(A(0x1240F0))
    a.li(8,UPLOADING);a.sw(8,16,S['status']);a.jump('wait')
    a.label('ready_check');a.jump('poll')
    a.label('poll');_owner(a,'fail')
    for off in (48,52):a.lw(8,18,off);a.branch(5,8,0,'wait')
    a.li(8,READY);a.sw(8,16,S['status']);a.li(2,1);a.jump('done')
    a.label('allocation')
    for key in ('header','sequence'):
        a.lw(4,16,S[key]);a.branch(4,4,0,'free_'+key);a.call(A(0x11EC40));a.sw(0,16,S[key]);a.label('free_'+key)
    a.li(8,3);a.jump('error')
    a.label('occupied');a.li(8,1);a.jump('error')
    a.label('space');a.li(8,2);a.jump('error')
    a.label('fail');a.li(16,STATE);a.li(8,4)
    a.label('error');a.sw(8,16,S['error']);a.li(8,FAILED);a.sw(8,16,S['status'])
    a.label('no');a.li(2,0xFFFFFFFF);a.jump('done')
    a.label('wait');a.move(2,0);a.label('done');tag.restore(a,result=2);a.jr()
    data=a.finish();assert INIT+len(data)<=TICK;return data


def tick_code():
    """Sound-frame callback: play once at charge/fire; stop private bank on exit."""
    import tag_rush_scene as scene
    import tag_rush_assets as assets
    import tag_rush_staging as staging
    import tag_rush_blue_native as blue
    a=Assembler(TICK);tag.save(a);_owner(a,'done')
    a.lw(8,16,S['status']);a.li(9,READY);a.branch(5,8,9,'done')
    for off in (48,52):a.lw(8,18,off);a.branch(5,8,0,'done')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    camera.emit_active(a,'stop')
    a.lw(9,16,S['manager']);a.lw(10,8,tag.C['manager']);a.branch(5,9,10,'stop')
    a.li(17,scene.STATE);a.lw(8,17,scene.S['retiring']);a.branch(5,8,0,'stop')
    a.lw(20,17,scene.S['descriptor']);full.pointer(a,20,64,'stop')
    a.lw(21,20,28);a.i(12,8,21,assets.OWN_CLASH_POSE|0x200);a.branch(4,8,0,'stop')
    a.li(8,tag.CONTROL);a.lw(8,8,tag.C['variant']);a.li(9,6);a.branch(4,8,9,'galick_flags')
    a.i(12,8,21,assets.BEAM_LEAD|assets.BEAM_PARTNER);a.branch(4,8,0,'stop')
    a.label('galick_flags')
    a.lw(22,17,scene.S['phase']);a.lw(8,16,S['last_phase']);a.branch(4,8,22,'phase_ok')
    a.sw(22,16,S['last_phase']);a.li(8,tag.CONTROL);a.lw(8,8,tag.C['variant']);a.li(9,6);a.branch(4,8,9,'phase_ok');a.sw(0,16,S['roles'])
    a.label('phase_ok');a.li(8,1);a.sw(8,16,S['active'])
    a.move(4,22);a.call(staging.QUERY);a.branch(4,2,0,'stop')
    a.lw(8,2,8);a.li(9,ACTOR_HZ);a.r(0x19,0,8,9);a.r(0x12,8,0,0)
    a.lw(9,17,scene.S['ticks']);a.li(10,60);a.r(0x19,0,9,10);a.r(0x12,9,0,0)
    a.r(0x2B,8,9,8);a.li(9,46);a.branch(4,8,0,'fire');a.li(9,45)
    a.label('fire');a.sw(9,29,0x300)
    for role,flag in enumerate((assets.BEAM_LEAD,assets.BEAM_PARTNER)):
        end=f'role_end{role}'
        a.li(8,tag.CONTROL);a.lw(8,8,tag.C['variant']);a.li(9,6);a.branch(5,8,9,f'ordinary{role}')
        # Follow the native emitters across phase boundaries. A new camera
        # shot must neither replay a charge nor stop the beam sound early.
        a.li(8,scene.ROWS+role*scene.STRIDE);a.lw(8,8,blue.FX_STATE);a.branch(4,8,0,end)
        a.li(9,1);a.branch(4,8,9,f'galick_fire{role}');a.li(9,45);a.li(20,1<<role);a.jump(f'bit{role}')
        a.label(f'galick_fire{role}');a.li(9,54);a.li(20,1<<(role+2));a.jump(f'bit{role}')
        a.label(f'ordinary{role}')
        a.i(12,8,21,flag);a.branch(4,8,0,end)
        a.lw(9,29,0x300);a.li(8,45);a.li(20,1<<role);a.branch(4,9,8,f'bit{role}');a.li(20,1<<(role+2))
        a.label(f'bit{role}');a.sw(9,29,0x308);a.lw(8,16,S['roles']);a.r(0x24,8,8,20);a.branch(5,8,0,end)
        a.sw(20,29,0x304);a.li(20,scene.ROWS+role*scene.STRIDE);scene.identity(a,20,end,f'beam_audio{role}')
        a.lw(8,28,-20712);full.pointer(a,8,0x200,end);a.lw(8,8,104);a.i(11,8,8,30);a.branch(4,8,0,end)
        a.lw(4,20,scene.R['model_id']);a.li(5,3);a.addiu(6,29,0x320);a.call(A(0x2058E0))
        a.addiu(4,29,0x320);a.addiu(5,29,0x310);a.addiu(6,29,0x314)
        a.li(8,0x43480000);a.emit((0x11<<26)|(4<<21)|(8<<16)|(12<<11))
        a.li(8,0x44BB8000);a.emit((0x11<<26)|(4<<21)|(8<<16)|(13<<11));a.call(A(0x1D9DB0))
        a.lw(4,16,S['mask']);a.lw(5,29,0x308);a.lw(6,29,0x310);a.lw(7,29,0x314);a.move(8,0);a.call(A(0x124F88))
        a.i(10,8,2,0);a.branch(5,8,0,end)
        a.lw(20,29,0x304);a.lw(8,16,S['roles']);a.r(0x25,8,8,20);a.sw(8,16,S['roles'])
        a.lw(8,29,0x308);a.li(9,45);a.branch(5,8,9,f'count_fire{role}')
        a.lw(8,16,S['charge']);a.addiu(8,8,1);a.sw(8,16,S['charge']);a.jump(end)
        a.label(f'count_fire{role}');a.lw(8,16,S['fire']);a.addiu(8,8,1);a.sw(8,16,S['fire']);a.label(end)
    a.jump('done')
    a.label('stop');a.lw(8,16,S['active']);a.branch(4,8,0,'done')
    a.lw(4,16,S['mask']);a.call(A(0x125188));a.sw(0,16,S['active']);a.sw(0,16,S['roles']);a.li(8,0xFFFFFFFF);a.sw(8,16,S['last_phase'])
    a.lw(8,16,S['stops']);a.addiu(8,8,1);a.sw(8,16,S['stops'])
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert TICK+len(data)<=RELEASE;return data


def release_code():
    a=Assembler(RELEASE);tag.save(a);_owner(a,'done')
    for off in (48,52):a.lw(8,18,off);a.branch(5,8,0,'done')
    a.move(4,19);a.call(A(0x125188));a.move(4,19);a.call(A(0x124DC0))
    #124DC0 clears allocated pointers but retains stale header bytes; restore
    #the wholly-empty private row so a later prepared match may claim it.
    for i in range(19):a.sw(0,18,4*i)
    a.li(8,CLOSED);a.sw(8,16,S['status']);a.sw(0,16,S['active'])
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert RELEASE+len(data)<=EXIT;return data


def exit_code():
    a=Assembler(EXIT);tag.save(a);a.call(A(0x124A28));a.call(RELEASE);tag.restore(a);a.jr()
    data=a.finish();assert EXIT+len(data)<=STATE;return data


def impact_code():
    """Use the ultimate's own impact once, at the actual victim."""
    import tag_rush_scene as scene
    a=Assembler(IMPACT);tag.save(a);_owner(a,'done')
    a.lw(8,16,S['status']);a.li(9,READY);a.branch(5,8,9,'done')
    camera.emit_active(a,'done');a.lw(8,8,tag.C['variant']);a.li(9,6);a.branch(5,8,9,'done')
    a.li(20,scene.ROWS+2*scene.STRIDE);scene.identity(a,20,'done','ultimate_impact')
    a.lw(4,20,scene.R['model_id']);a.li(5,3);a.addiu(6,29,0x320);a.call(A(0x2058E0))
    a.addiu(4,29,0x320);a.addiu(5,29,0x310);a.addiu(6,29,0x314)
    a.li(8,0x43480000);a.emit((0x11<<26)|(4<<21)|(8<<16)|(12<<11))
    a.li(8,0x44BB8000);a.emit((0x11<<26)|(4<<21)|(8<<16)|(13<<11));a.call(A(0x1D9DB0))
    a.lw(4,16,S['mask']);a.li(5,55);a.lw(6,29,0x310);a.lw(7,29,0x314);a.move(8,0);a.call(A(0x124F88))
    a.label('done');tag.restore(a);a.jr();data=a.finish();assert IMPACT+len(data)<=IMPACT_END;return data


def pieces(iso,manager,*,address=DATA):
    bank=disc_bank(str(Path(iso).resolve()));state=bytearray(0x100)
    import tag_rush_blue_native as blue
    if not (address==DATA and len(bank['data'])<=END-DATA or
            blue.DATA<=address<address+len(bank['data'])<=blue.END):
        raise ValueError('Private tag audio escaped its prepared reservation')
    for key,value in dict(magic=MAGIC,manager=manager,last_phase=0xFFFFFFFF,
                          body_size=bank['sizes'][0],header_size=bank['sizes'][1],sequence_size=bank['sizes'][2],
                          raw_header=address+bank['header_offset'],raw_sequence=address+bank['sequence_offset'],bank_data=address).items():
        struct.pack_into('<I',state,S[key],value)
    result=[(INIT,init_code()),(TICK,tick_code()),(RELEASE,release_code()),(EXIT,exit_code()),(IMPACT,impact_code()),(STATE,bytes(state))]
    if address==DATA:result.append((DATA,bank['data']))
    return result
