"""Independent Body Change bundles copied on EE, with no AFS/IOP requests.

Only the three resident PAK files are copied, never a live model or its caches.
The ordinary hidden-model constructor reparses PAK offsets and rebinds skeleton
and collision pointers into private storage. Uploaded texture IDs remain valid:
1132F8's initialized branch reparses 10A028 and claims the existing group without
uploading or modifying TIM2 addresses a second time. Both old owners stay live
until the existing verified atomic two-body commit.
"""
from native_map import A
import struct

import body_swap as body
import body_swap_resources as resources
from prototype import Assembler
from selected_team_prepare import resource_info

IO,CONTROL=resources.IO,resources.IO_CONTROL
MAGIC=0x42534331
COPY_MARKER,COPY_SOURCE=48,52
MEMCPY=A(0x2A9A1C)


class SourceUnavailable(ValueError):
    """A legitimate auxiliary bundle needs the ordinary full-body disc load."""


def source(ram,snapshot,physical):
    world=resources.body_world(ram,snapshot,physical)
    donor=snapshot['target'] if physical==snapshot['source']['physical'] else snapshot['source']
    descriptor=donor['resource'];handle=body.u(ram,descriptor+52)
    body.require(0<=handle<14 and descriptor==world['registry']+(672+handle*56 if handle<2 else (handle-2)*56) and
                 body.u(ram,descriptor+48)==(1 if handle<2 else 3),'Resident source descriptor identity changed')
    files=resources.preload.request_files(donor['character'],donor['costume'],donor['damaged'])
    actual=[body.u(ram,descriptor+16*i+8) for i in range(3)]
    if actual!=files:
        raise SourceUnavailable('The donor has auxiliary move data instead of its ordinary three body files')
    row=resource_info(ram,descriptor,handle,donor['character'],donor['costume'],
                      body.u(ram,resources.preload.REGISTRY_GLOBAL),damaged=donor['damaged'])
    body.require(row['geometry_initialized'] and row['texture_group']<15,
                 'Resident body must have a valid uploaded texture group')
    body.require(body.u(ram,donor['model']+64)==row['geometry'],'Resident body geometry identity changed')
    owner=snapshot['source'] if physical==snapshot['source']['physical'] else snapshot['target']
    own_geometry=body.u(ram,owner['model']+64)
    if body.u(ram,own_geometry+40)==row['texture_group']:
        raise SourceUnavailable('Both bodies already share a texture group; independent replacement upload is required')
    buffers=[(body.u(ram,descriptor+16*i),body.u(ram,descriptor+16*i+4)) for i in range(3)]
    body.require(all(p%16==0 and 0<n<=resources.NATIVE_CAPACITIES[i] and n%2048==0
                     for i,(p,n) in enumerate(buffers)),'Resident body files exceed native capacities or alignment')
    body.require(all(p+n<=q or q+m<=p for i,(p,n) in enumerate(buffers) for q,m in buffers[i+1:]),
                 'Resident body files overlap')
    return world,donor,row,buffers


def payload(world,donor,row,buffers,capacities):
    a=Assembler(IO);a.addiu(29,29,-0x50)
    for i,r in enumerate((16,17,18,19,20,21,31)):a.i(63,r,29,i*8)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,4);a.branch(5,8,0,'done')
    checks=resources.quiet_checks(world)+[(world['model']+2356,world['old_dataset']),
        (resources.preload.REGISTRY_GLOBAL,world['registry']-resources.preload.REGISTRY_OFFSET),
        (A(0x2FF084),0x02000000),(A(0x2FF08C),0x06000000),
        (donor['model']+64,row['geometry']),(row['geometry']+40,row['texture_group']),
        (row['geometry']+12,row['geometry_flags'])]
    for off in range(0,56,4):
        # Reserved record words too: a queued native loader must not be able
        # to replace a donor while this copy reads its three file allocations.
        checks.append((donor['resource']+off,row['descriptor_words'][off//4]))
    for p,v in checks:
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error110')
    a.li(8,world['manager'])
    for off in (600,612,628):a.lw(9,8,off);a.branch(5,9,0,'error112')
    a.lw(9,8,604);a.lw(10,8,608);a.branch(5,9,10,'error112')
    a.li(8,world['registry']+836);a.lw(8,8);a.addiu(9,0,-1);a.branch(5,8,9,'error112')
    a.li(19,world['registry']);a.move(20,0)
    a.label('free_scan');a.lw(8,19,48);a.i(12,8,8,1);a.branch(4,8,0,'found')
    a.addiu(20,20,1);a.addiu(19,19,56);a.i(11,8,20,12);a.branch(5,8,0,'free_scan');a.jump('error130')
    a.label('found')
    for off in (0,16,32):a.lw(8,19,off);a.branch(5,8,0,'error130')
    for i,(pointer,size) in enumerate(buffers):
        a.li(4,capacities[i] if capacities else size);a.addiu(5,0,64);a.move(6,0);a.addiu(7,0,1)
        a.call(A(0x2554D8));a.branch(4,2,0,'allocation_failed');a.sw(2,16,64+4*i)
        # Preserve the native initialized PAK contents, including their texture
        # group. Skeleton pointer caches are rebuilt by 24FA50/10A028 later.
        a.move(4,2);a.li(5,pointer);a.li(6,size);a.call(MEMCPY)
    a.call(A(0x24B238));a.branch(5,2,19,'error132')
    a.lw(8,19,52);a.addiu(9,20,2);a.branch(5,8,9,'error132')
    a.sw(8,16,36);a.sw(19,16,32)
    for i,(_,size) in enumerate(buffers):
        a.lw(8,16,64+4*i);a.sw(8,19,16*i)
        a.li(8,size);a.sw(8,19,16*i+4)
        a.li(8,row['file_ids'][i]);a.sw(8,19,16*i+8);a.sw(0,19,16*i+12)
    a.addiu(8,0,3);a.sw(8,19,48)
    a.addiu(8,0,1);a.sw(8,16,40);a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    a.label('allocation_failed')
    for i in range(3):
        a.lw(4,16,64+4*i);a.branch(4,4,0,f'no_alloc{i}')
        a.call(A(0x255508));a.sw(0,16,64+4*i);a.label(f'no_alloc{i}')
    a.jump('error131')
    for status in (110,112,130,131,132):
        a.label(f'error{status}');a.addiu(8,0,status);a.sw(8,16,4);a.jump('done')
    a.label('done');a.lw(2,16,4)
    for i,r in enumerate((16,17,18,19,20,21,31)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x50);a.jr();code=a.finish()
    assert len(code)<CONTROL-IO
    return code


def io_memory(ram,snapshot,physical):
    world,donor,row,buffers=source(ram,snapshot,physical)
    body.require(not any(ram[IO:resources.STAGE]),'Body IO reservation is occupied')
    # Native pointer relocation and no-upload branches are part of this ABI,
    # not just an assumption about the file format being relocatable.
    for p,n in ((MEMCPY,0xB0),(A(0x2554D8),0x30),(A(0x255508),0x68),(A(0x24B238),0x60),
                (A(0x24FA20),0x30),(A(0x24FA50),0x358),(A(0x10A028),0x80),(A(0x1132F8),0x180)):
        body.require(ram[p:p+n]==body.NATIVE(p,n),f'Native resident-copy helper changed:{p:08X}')
    row=dict(row,descriptor_words=[body.u(ram,donor['resource']+off) for off in range(0,56,4)],
             geometry_flags=body.u(ram,row['geometry']+12))
    capacities=resources.NATIVE_CAPACITIES if physical<2 else None
    control=bytearray(256)
    for key in ('manager','actor','model','physical','old_resource','old_dataset','registry'):
        struct.pack_into('<I',control,resources.preload.FIELDS[key],world[key])
    struct.pack_into('<I',control,36,0xFFFFFFFF)
    struct.pack_into('<2I',control,COPY_MARKER,MAGIC,donor['resource'])
    struct.pack_into('<3I',control,80,*[n for _,n in buffers])
    struct.pack_into('<3I',control,96,*row['file_ids'])
    return resources.parts_manifest(ram,[(IO,payload(world,donor,row,buffers,capacities)),(CONTROL,bytes(control))],
        entry=IO,control=CONTROL,world=world,destination=donor,capacities=capacities,
        resident_copy=True,source_buffers=buffers,source_geometry=row['geometry'],texture_group=row['texture_group'])


def validate_staging(ram,donor,row):
    body.require(body.u(ram,CONTROL+COPY_SOURCE)==donor['resource'],'Resident-copy donor changed')
    old=donor['resource'];files=resources.preload.request_files(donor['character'],donor['costume'],donor['damaged'])
    body.require([body.u(ram,old+16*i+8) for i in range(3)]==files,'Resident-copy source files changed')
    geometry=body.u(ram,donor['model']+64)
    body.require(row['geometry_initialized'] and row['texture_group']==body.u(ram,geometry+40) and
                 body.u(ram,geometry+12)&0x80000000,'Resident-copy uploaded texture identity changed')
