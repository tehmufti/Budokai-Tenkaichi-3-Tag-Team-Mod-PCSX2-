"""Construct a hidden replacement model from completed extra reload IO.

No fighter is rebound and no transformation gate is removed. The active model,
AI and resource ownership stay intact. A separate reviewed commit must publish
the replacement and retire old references. Only the scratch getter is extended;
the caller invokes ENTRY under the same held-world protocol as the IO stage.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

import extra_reload_service as io
import extra_reload_preload as prior
import selected_team_prepare as creator
from camera_snapshot import read_ram
from prototype import Assembler, ROOT, elf_reader
from twelve_prepare import copy_words
from native_map import FILE_ID

ENTRY, EXTENSION, OLD_EXTENSION = 0x07610000, 0x07613000, 0x07613800
CONTROL, END = 0x0761F000, 0x07620000
ALLOC_SIZE, COLLISION_OFF = creator.ALLOC_SIZE, creator.COLLISION_OFF
SHADER_OFF, FX_OFF = 0x20000, 0x22100
FIELDS = dict(enabled=0,status=4,manager=8,actor=12,old_model=16,old_model_id=20,
              old_resource=24,new_resource=28,new_handle=32,allocation=36,
              model_id=40,model=44,pending=48,shader=52,packet0=56,packet1=60,
              collision=64,shader_node=68,fx_node=72,dataset=76,
              repaired_groups=80,texture_group=84,staged_group=88)
# Native texture groups 0..14: a bare bit mask at pool+GROUP_MASK, no owner, no count.
GROUPS, GROUP_MASK = 15, 439156


def require(value, why):
    if not value: raise ValueError(why)


def texture_groups(ram):
    """The native group mask, the groups live registered models draw from, and the group staging takes.

    A model created from an already initialised geometry header re-reserves the group that header remembers
    without checking it (1132F8 re-init path, 249000 result ignored), and every model destructor (1135F0)
    clears its group bit even while another model still uses that number. A destroyed type-1 effect model
    therefore keeps "its" group in its persistent header; once a reload has given that number to a fighter,
    the effect's next use frees it under the fighter and the next staging is handed the fighter's own group
    (TTM-MATCH-08). The staging payload re-marks every live model's group and takes the highest free one,
    away from the lowest-first groups native transients initialise into; this host view predicts it exactly.
    """
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    mask=u(u(prior.REGISTRY_GLOBAL)+GROUP_MASK);live=0
    for mid in range(12):
        model=u(prior.core.MODELS+4*mid)
        if not (0x100000<=model<=len(ram)-0x1670 and model%4==0) or u(model+4)!=1:continue
        geometry=u(model+64)
        if not (0x100000<=geometry<=len(ram)-64 and geometry%4==0):continue
        if u(geometry+40)<GROUPS:live|=1<<u(geometry+40)
    full=(1<<GROUPS)-1;used=(mask|live)&full;free=full&~used
    return dict(mask=mask,live=live,used=used,repaired=live&~mask&full,
                group=free.bit_length()-1 if free else None)


def resource_info(ram, resource, handle, character, costume, damaged):
    """Reuse the native PAK/part-chain audit with the correct damaged file ID."""
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    files=prior.request_files(character,costume,damaged)
    require(2<=handle<14,'Replacement must own a dynamic resource record')
    pool=u(prior.REGISTRY_GLOBAL)
    require(resource==pool+prior.REGISTRY_OFFSET+(handle-2)*56,'Replacement resource registry identity changed')
    require(u(resource+48)==3 and u(resource+52)==handle,'Replacement resource is not loaded')
    for i,file_id in enumerate(files):
        require(u(resource+16*i+8)==file_id,'Replacement file identity mismatch')
    # Parse this snapshot directly, including its actual damaged-file ID.
    # No 128MiB analysis clone is needed during staging or final commit.
    return creator.resource_info(ram,resource,handle,character,costume,pool,
                                 damaged=damaged)


def extension_code(world, occupied):
    a=Assembler(EXTENSION);a.li(8,CONTROL)
    a.lw(9,8,8);a.lw(10,28,-22364);a.branch(5,9,10,'old')
    a.i(11,9,4,12);a.branch(4,9,0,'old')
    for mid in occupied:
        a.addiu(9,0,mid);a.branch(4,4,9,'old')
    a.lw(9,8,40);a.branch(4,9,4,'ours')
    a.lw(9,8,48);a.branch(4,9,0,'old');a.sw(4,8,40)
    a.label('ours');a.lw(2,8,36);a.branch(4,2,0,'old');a.jr()
    a.label('old');a.jump(OLD_EXTENSION)
    return a.finish()


def group_choice(a,row):
    """Before any allocation: re-mark every live model's group, pick the highest free one (else 122).

    Mirrors texture_groups(). Uses t0-t7 only; the repaired bits and the choice go to CONTROL+80/+84.
    """
    a.li(8,row['pool']+GROUP_MASK);a.lw(9,8);a.move(10,9)
    a.li(11,prior.core.MODELS);a.addiu(12,11,48)
    a.label('group_scan');a.lw(13,11)
    a.li(14,0x100000);a.r(0x2B,14,13,14);a.branch(5,14,0,'group_next')
    a.li(14,0x8000000-0x1670);a.r(0x2B,14,14,13);a.branch(5,14,0,'group_next')
    a.i(12,14,13,3);a.branch(5,14,0,'group_next')
    a.lw(14,13,4);a.addiu(15,0,1);a.branch(5,14,15,'group_next')
    a.lw(14,13,64)
    a.li(15,0x100000);a.r(0x2B,15,14,15);a.branch(5,15,0,'group_next')
    a.li(15,0x8000000-64);a.r(0x2B,15,15,14);a.branch(5,15,0,'group_next')
    a.i(12,15,14,3);a.branch(5,15,0,'group_next')
    a.lw(14,14,40);a.i(11,15,14,GROUPS);a.branch(4,15,0,'group_next')
    a.addiu(15,0,1);a.r(4,15,14,15);a.r(0x25,10,10,15)
    a.label('group_next');a.addiu(11,11,4);a.branch(5,11,12,'group_scan')
    a.sw(10,8)
    a.r(0x27,13,9,0);a.r(0x24,13,13,10);a.sw(13,16,80)
    a.r(0x27,13,10,0);a.i(12,13,13,(1<<GROUPS)-1);a.branch(4,13,0,'error122')
    a.addiu(14,0,GROUPS-1);a.addiu(15,0,1<<(GROUPS-1))
    a.label('group_pick');a.r(0x24,12,13,15);a.branch(5,12,0,'group_picked')
    a.addiu(14,14,-1);a.r(2,15,0,15,1);a.jump('group_pick')
    a.label('group_picked');a.sw(14,16,84)


def payload(world,row,occupied,quiet=False,allow_forms=False,quiet_guard=None):
    # A resident copy (Body Change) re-creates an initialised header that keeps its group on purpose.
    fresh=not row.get('geometry_initialized')
    a=Assembler(ENTRY);a.addiu(29,29,-0x80)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(63,r,29,i*8)
    for i in range(4):a.i(57,20+i,29,0x60+i*4)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,4);a.branch(5,8,0,'done')
    for p,value in ((prior.core.ACTORS,world['manager']),(prior.core.MODE,1),
                    (prior.core.MODE+4,world['count']),(prior.core.MODE+8,world['manager']),
                    (prior.core.MODE+12,world['count']),(prior.core.PAIR+4,0),
                    (io.CONTROL+4,5),(io.CONTROL+32,row['resource']),
                    (io.CONTROL+36,row['resource_handle']),
                    (world['actor']+12,world['model_id']),
                    (world['model']+20,world['old_resource'])):
        a.li(8,p);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error110')
    for i,actor in enumerate(world['actors']):
        held=() if quiet else ((actor+0x948,11),(actor+0x1278,0),(actor+0x127C,0),(actor+0x1280,0),(actor+0x1284,0))
        for p,value in ((prior.core.POINTERS+i*4,actor),(actor,i))+held:
            a.li(8,p);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error110')
    if quiet:
        if quiet_guard is None:
            import extra_reload_quiet
            extra_reload_quiet.guard(a,world,'error110',allow_forms)
        else:
            quiet_guard(a,world,'error110')
    for p,value in ((row['resource']+48,3),(row['resource']+52,row['resource_handle'])):
        a.li(8,p);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error110')
    for i,file_id in enumerate(row['file_ids']):
        a.li(8,row['resource']+16*i+8);a.lw(8,8);a.li(9,file_id);a.branch(5,8,9,'error110')
    a.li(8,row['pool']+397320);a.lw(8,8);a.li(9,row['draw_nodes'])
    a.r(0x2B,8,8,9);a.branch(5,8,0,'error120')
    a.li(8,row['pool']+69128);a.lw(8,8);a.branch(4,8,0,'error120')
    if fresh:group_choice(a,row)
    a.addiu(8,0,1);a.sw(8,16,4)
    a.li(4,ALLOC_SIZE);a.addiu(5,0,64);a.move(6,0);a.addiu(7,0,1)
    a.call(A(0x2554D8));a.branch(4,2,0,'error130');a.move(18,2);a.sw(18,16,36)
    a.move(4,18);a.move(5,0);a.li(6,ALLOC_SIZE);a.call(A(0x2A9ACC))
    for reg,size,align,field in ((19,192,32,52),(20,creator.PACKET_BYTES,64,56),(21,creator.PACKET_BYTES,64,60)):
        a.li(4,size);a.addiu(5,0,align);a.move(6,0);a.addiu(7,0,1)
        a.call(A(0x2554D8));a.branch(4,2,0,'error131');a.move(reg,2);a.sw(reg,16,field)
        a.move(4,reg);a.move(5,0);a.li(6,size);a.call(A(0x2A9ACC))
    a.sw(20,19);a.sw(21,19,4)
    a.li(8,SHADER_OFF);a.r(0x21,8,18,8);a.sw(19,8,8240)
    for off,listoff,field in ((SHADER_OFF,439072,68),(FX_OFF,397776,72)):
        a.li(8,off);a.r(0x21,5,18,8);a.sw(5,16,field)
        a.li(4,row['pool']+listoff);a.call(0x255CF0)
    a.li(20,row['collision']);a.li(8,COLLISION_OFF);a.r(0x21,21,18,8)
    if not row['collision_size']:a.move(21,0)
    a.sw(21,16,64)
    copy_words(a,'backup_collision',20,21,row['collision_size'])
    a.addiu(8,0,1);a.sw(8,16,48)
    if fresh:
        # The first-init allocator (249098) takes the lowest free group: for this one native call every
        # other free group is marked (s1 keeps exactly those bits), so it can only take the chosen one.
        a.li(8,row['pool']+GROUP_MASK);a.lw(9,8);a.lw(10,16,84);a.addiu(11,0,1);a.r(4,11,10,11)
        a.r(0x27,17,9,11);a.i(12,17,17,(1<<GROUPS)-1);a.r(0x25,9,9,17);a.sw(9,8)
    a.move(4,0);a.li(5,row['resource']);a.move(6,0);a.call(A(0x249AB8))
    a.move(22,2);a.sw(0,16,48)
    if fresh:
        a.li(8,row['pool']+GROUP_MASK);a.lw(9,8);a.r(0x27,10,17,0);a.r(0x24,9,9,10);a.sw(9,8)
    copy_words(a,'restore_collision',21,20,row['collision_size'])
    a.i(11,8,22,12);a.branch(4,8,0,'error140')
    for mid in occupied:
        a.addiu(8,0,mid);a.branch(4,22,8,'error140')
    a.sw(22,16,40);a.move(4,22);a.call(A(0x2499B0))
    a.branch(4,2,0,'error141');a.move(19,2);a.sw(19,16,44);a.sw(0,19,8)
    for field,value in ((16,None),(20,row['resource']),(12,row['character']),(5728,'allocation')):
        a.lw(8,19,field)
        if value is None:a.move(9,22)
        elif value=='allocation':a.move(9,18)
        else:a.li(9,value)
        a.branch(5,8,9,'error142')
    if fresh:a.li(8,row['geometry']+40);a.lw(8,8);a.sw(8,16,88)
    a.sw(21,19,84);a.move(4,19);a.call(A(0x24DB28))
    for field,control in ((5736,68),(5732,72)):
        a.lw(8,19,field);a.lw(9,16,control);a.branch(5,8,9,'error143')
    a.move(4,19);a.move(5,0);a.addiu(6,0,2);a.call(A(0x24D330))
    a.move(4,19);a.li(5,world['actor']+16);a.li(6,world['actor']+144);a.call(A(0x1D3128))
    for function in (A(0x24C958),A(0x24CC88),A(0x24E3F8)):a.move(4,19);a.call(function)
    a.lw(8,19,2356);a.branch(4,8,0,'error144');a.sw(8,16,76)
    a.sw(0,19,8);a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    for error in (110,120)+((122,) if fresh else ())+(130,131,140,141,142,143,144):
        a.label(f'error{error}');a.addiu(8,0,error);a.sw(8,16,4);a.sw(0,16,48);a.jump('done')
    a.label('done');a.lw(2,16,4)
    for i in range(4):a.i(49,20+i,29,0x60+i*4)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x80);a.jr()
    code=a.finish();assert ENTRY+len(code)<EXTENSION;return code


def build_memory(ram,source='<offline-memory>',quiet=False,allow_forms=False):
    require(len(ram)==0x8000000,'Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    require(u(io.CONTROL+4)==5 and u(io.CONTROL+40)==1,'Independent reload IO must be complete')
    physical=u(io.CONTROL+20);world=prior.capture(ram,physical)
    for key in ('manager','actor','model','old_resource','old_dataset','registry'):
        require(u(io.CONTROL+prior.FIELDS[key])==world[key],f'Completed IO owner changed:{key}')
    files=[u(io.CONTROL+96+i*4) for i in range(3)]
    character,costume,damaged=io.decode_request(ram,files)
    resource,handle=u(io.CONTROL+32),u(io.CONTROL+36)
    row=resource_info(ram,resource,handle,character,costume,damaged)
    row.update(character=character,costume=costume,damaged=damaged,pool=u(prior.REGISTRY_GLOBAL))
    require(resource!=world['old_resource'],'Replacement must not overwrite the current resource')
    if quiet:
        import extra_reload_quiet
        extra_reload_quiet.validate(ram,world,allow_forms)
    else:
        for actor in world['actors']:
            require(u(actor+0x948)==11 and all(u(actor+off)==0 for off in (0x1278,0x127C,0x1280,0x1284)),
                    'Staging requires held idle actors')
    for i in range(3):
        require(u(resource+16*i)==u(io.CONTROL+64+4*i) and
                u(resource+16*i+4)==u(io.CONTROL+80+4*i),'Completed IO buffer identity changed')
        p,size=u(resource+16*i),u(resource+16*i+4)
        for model in world['models']:
            old=u(model+20)
            for j in range(3):
                q,n=u(old+16*j),u(old+16*j+4)
                require(p+size<=q or p>=q+n,'Replacement buffer overlaps an active fighter resource')
    occupied=[i for i in range(12) if u(prior.core.MODELS+i*4) and u(u(prior.core.MODELS+i*4)+4)]
    require(len(occupied)<12,'No spare staging model slot')
    pool=row['pool'];require(u(pool+397320)>=row['draw_nodes'] and u(pool+69128)>0,'Insufficient staging model/draw capacity')
    groups=texture_groups(ram);require(groups['group'] is not None,'No spare texture group')
    require(not row['geometry_initialized'],'Staging requires a fresh independently loaded mesh')
    require(not any(ram[ENTRY:END]),'Reload staging reservation occupied')
    original=bytes(ram[creator.EXT_ENTRY:creator.EXT_ENTRY+8])
    require(u(creator.EXT_ENTRY)>>26==2 and u(creator.EXT_ENTRY+4)==0,'Expected reviewed scratch getter chain')
    previous=(u(creator.EXT_ENTRY)&0x3FFFFFF)<<2
    require(previous==creator.EXT_CODE,'This version requires selected-team scratch routing')
    _,_,native=elf_reader(elf_path(ROOT))
    for p,n in ((A(0x249AB8),0xA0),(A(0x2499B0),0x18),(A(0x255CF0),0x30),(A(0x24DB28),0x70),
                (A(0x113660),0xA0),(A(0x1D3128),0x50),(A(0x24D330),0x58)):
        require(ram[p:p+n]==native(p,n),f'Native staging helper changed:{p:08X}')
    control=bytearray(0x100)
    for field,value in ((8,world['manager']),(12,world['actor']),(16,world['model']),
                        (20,world['model_id']),(24,world['old_resource']),(28,resource),(32,handle),(40,0xFFFFFFFF)):
        struct.pack_into('<I',control,field,value)
    pieces=[(ENTRY,payload(world,row,occupied,quiet,allow_forms)),(EXTENSION,extension_code(world,occupied)),
            (OLD_EXTENSION,original),(CONTROL,bytes(control)),
            (creator.EXT_ENTRY,struct.pack('<2I',(2<<26)|(EXTENSION>>2),0))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),world=world,resource=row,texture_groups=groups,
        occupied_model_ids=occupied,entry=ENTRY,control=CONTROL,fields=FIELDS,quiet=quiet,
        status='DORMANT HIDDEN REPLACEMENT STAGE; NO ACTOR COMMIT',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces],
        requirements=['Keep all fighters idle under the caller-owned hold; enable then call ENTRY once.',
                      'Status5 means a hidden registered model only; do not expose it or rebind an actor.',
                      'Keep all allocations/resources on failure and restore the checkpoint; no incomplete cleanup guessed.'],
        limitations=['No active model/AI/effect-row commit, transformation request routing or resource retirement.',
                     'One hidden staging model consumes a temporary native model slot and texture group.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    x=p.parse_args();m=build_memory(read_ram(x.source),x.source)
    x.out.write_text(json.dumps(m,indent=2)+'\n');print(x.out)
