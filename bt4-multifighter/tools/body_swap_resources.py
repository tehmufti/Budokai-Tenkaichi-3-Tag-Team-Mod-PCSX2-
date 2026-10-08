"""Dormant independent bundle preparation for a captured Body Change pair.

These offline builders do not install a runner, suppress stock Body Change, or
commit either body. Both actors/models remain intact until an atomic exchange
has been prepared. Native leader replacement buffers use native maximum sizes,
because future native reloads reuse their pointers without a capacity check.
"""
from native_map import A, CRC, RANGE, SERIAL
import struct
from types import SimpleNamespace

import body_swap as swap
import extra_reload_preload as preload
import extra_reload_service as io
import extra_reload_stage as stage
import native_preparation as transport

IO, INNER, QUEUE, IO_CONTROL = 0x07040000, 0x07040800, 0x07044000, 0x0704F000
STAGE, EXTENSION, OLD_EXTENSION, STAGE_CONTROL = 0x07050000, 0x07053000, 0x07053800, 0x0705F000
# Native24B510's bounded allocation sizes, independently matched against every
# BT4 native24B510 allocation immediates; guarded against the selected ELF.
NATIVE_CAPACITIES = (0xE7000, 0x160800, 0xD4800)
require, u = swap.require, swap.u


def body_world(ram, snapshot, physical):
    require(physical in (snapshot['source']['physical'], snapshot['target']['physical']),
            'Resource job must belong to the captured Body Change pair')
    current = swap.world(ram)
    require(all(current[k] == snapshot['world'][k] for k in ('manager','count','actors','mode','present')),
            'Body Change world or relationships changed')
    world = preload.capture(ram, physical, allow_leaders=True)
    world['body_guards'] = []
    for body in (snapshot['source'], snapshot['target']):
        now = swap.body(ram, current, body['physical'])
        for key in ('actor','model_id','model','resource','row','character','costume','controller','cpu'):
            require(now[key] == body[key], f'Body Change participant changed:{key}')
        world['body_guards'] += [(body['actor'],body['physical']),
            (body['actor']+12,body['model_id']), (preload.core.MODELS+4*body['model_id'],body['model']),
            (body['model']+16,body['model_id']), (body['model']+20,body['resource']),
            (body['model']+12,body['character']), (body['row'],body['character']),
            (body['row']+4,body['costume'])]
    for p,v in quiet_checks(world): require(u(ram,p)==v,'Body preparation needs an acknowledged native hold')
    return world


def quiet_checks(world):
    return [(transport.CONTROL,transport.MAGIC), (transport.CONTROL+16,1),
            (transport.CONTROL+20,1), (transport.CONTROL+24,world['manager']),
            (world['actor']+2376,world['owner_action'])]+world['body_guards']


def quiet_guard(a, world, fail):
    for p,v in quiet_checks(world):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,fail)


def parts_manifest(ram, pieces, **metadata):
    return dict(serial=SERIAL,crc=CRC,
                status=metadata.pop('status','DORMANT BODY RESOURCE PREPARATION; NO BODY COMMIT'),
                blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex())
                        for p,data in pieces],**metadata)


def io_memory(ram, snapshot, physical):
    world = body_world(ram,snapshot,physical)
    donor = snapshot['target'] if physical==snapshot['source']['physical'] else snapshot['source']
    files = preload.request_files(donor['character'],donor['costume'],donor['damaged'])
    require(not any(ram[IO:STAGE]),'Body IO reservation is occupied')
    for p,n in (RANGE(0x2654D8,0x58),(A(0x26B5E8),0x38),(A(0x26AA40),0x38),
                (A(0x2554D8),0x30),(A(0x255508),0x68),(A(0x24B238),0x60),
                (A(0x265298),0x180),(A(0x255BD8),0x28),(A(0x255B88),0x50),(A(0x255978),0x68)):
        require(ram[p:p+n]==swap.NATIVE(p,n),f'Native body IO helper changed:{p:08X}')
    values=dict(ENTRY=IO,INNER=INNER,QUEUE=QUEUE,CONTROL=IO_CONTROL)
    capacities=NATIVE_CAPACITIES if physical<2 else None
    entry=preload.core.rebound(io.entry_code,**values)()
    inner=preload.core.rebound(io.inner_code,**values)(world,files,True,False,quiet_guard,capacities)
    queue=preload.core.rebound(io.queue_code,**values)()
    control=bytearray(256)
    for key in ('manager','actor','model','physical','old_resource','old_dataset','registry'):
        struct.pack_into('<I',control,preload.FIELDS[key],world[key])
    struct.pack_into('<I',control,36,0xFFFFFFFF)
    struct.pack_into('<3I',control,96,*files)
    struct.pack_into('<I',control,io.TIMEOUT,io.POLL_UPDATES)
    return parts_manifest(ram,[(IO,entry),(INNER,inner),(QUEUE,queue),(IO_CONTROL,bytes(control))],
                          entry=IO,control=IO_CONTROL,world=world,
                          destination=donor,capacities=capacities)


def stage_memory(ram, snapshot, physical):
    import body_swap_copy
    world=body_world(ram,snapshot,physical)
    require(u(ram,IO_CONTROL+4)==5 and u(ram,IO_CONTROL+40)==1,'Body IO has not completed')
    for key in ('manager','actor','model','physical','old_resource','old_dataset','registry'):
        require(u(ram,IO_CONTROL+preload.FIELDS[key])==world[key],f'Body IO owner changed:{key}')
    donor=snapshot['target'] if physical==snapshot['source']['physical'] else snapshot['source']
    resource,handle=u(ram,IO_CONTROL+32),u(ram,IO_CONTROL+36)
    files=preload.request_files(donor['character'],donor['costume'],donor['damaged'])
    require([u(ram,IO_CONTROL+96+4*i) for i in range(3)]==files,'Body IO destination changed')
    row=stage.resource_info(ram,resource,handle,donor['character'],donor['costume'],donor['damaged'])
    row.update(character=donor['character'],costume=donor['costume'],damaged=donor['damaged'],
               pool=u(ram,preload.REGISTRY_GLOBAL))
    require(resource!=world['old_resource'],'Body staging cannot overwrite an active resource')
    for i in range(3):
        pointer,size=u(ram,resource+16*i),u(ram,resource+16*i+4)
        require((pointer,size)==(u(ram,IO_CONTROL+64+4*i),u(ram,IO_CONTROL+80+4*i)),
                'Body IO buffer identity changed')
        if physical<2:require(size<=NATIVE_CAPACITIES[i],'Body data exceeds native leader buffer capacity')
        for model in world['models']:
            old=u(ram,model+20)
            for j in range(3):
                p,n=u(ram,old+16*j),u(ram,old+16*j+4)
                require(pointer+size<=p or pointer>=p+n,'Body staging overlaps active fighter data')
    occupied=[i for i in range(12) if u(ram,preload.core.MODELS+4*i) and
              u(ram,u(ram,preload.core.MODELS+4*i)+4)]
    require(len(occupied)<12,'No free temporary model slot')
    pool=row['pool']
    require(u(ram,pool+397320)>=row['draw_nodes'] and u(ram,pool+69128)>0,
            'Insufficient native model/draw storage')
    copied=u(ram,IO_CONTROL+body_swap_copy.COPY_MARKER)==body_swap_copy.MAGIC
    if copied:body_swap_copy.validate_staging(ram,donor,row)
    else:
        require(stage.texture_groups(ram)['group'] is not None,'No temporary texture group available')
        require(not row['geometry_initialized'],'Body staging requires freshly loaded geometry')
    require(not any(ram[STAGE:0x07060000]),'Body staging reservation is occupied')
    at=stage.creator.EXT_ENTRY;original=bytes(ram[at:at+8])
    expected=struct.pack('<2I',(2<<26)|(stage.creator.EXT_CODE>>2),0)
    require(original==expected,'Body staging requires the restored selected-team scratch getter')
    for p,n in ((A(0x249AB8),0xA0),(A(0x2499B0),0x18),(A(0x255CF0),0x30),(A(0x24DB28),0x70),
                (A(0x113660),0xA0),(A(0x1D3128),0x50),(A(0x24D330),0x58)):
        require(ram[p:p+n]==swap.NATIVE(p,n),f'Native body staging helper changed:{p:08X}')
    values=dict(ENTRY=STAGE,EXTENSION=EXTENSION,OLD_EXTENSION=OLD_EXTENSION,
                CONTROL=STAGE_CONTROL,io=SimpleNamespace(CONTROL=IO_CONTROL))
    payload=preload.core.rebound(stage.payload,**values)(world,row,occupied,True,False,quiet_guard)
    extension=preload.core.rebound(stage.extension_code,**values)(world,occupied)
    control=bytearray(256)
    for off,value in ((8,world['manager']),(12,world['actor']),(16,world['model']),
                      (20,world['model_id']),(24,world['old_resource']),(28,resource),(32,handle),(40,0xFFFFFFFF)):
        struct.pack_into('<I',control,off,value)
    pieces=[(STAGE,payload),(EXTENSION,extension),(OLD_EXTENSION,original),(STAGE_CONTROL,bytes(control)),
            (at,struct.pack('<2I',(2<<26)|(EXTENSION>>2),0))]
    return parts_manifest(ram,pieces,entry=STAGE,control=STAGE_CONTROL,world=world,
                          resource=row,occupied_model_ids=occupied)


def staged_receipt(ram, snapshot, physical, capacities):
    """Detach a completed hidden model from its reusable staging workspace."""
    world=body_world(ram,snapshot,physical)
    require(u(ram,STAGE_CONTROL+4)==5,'Hidden Body Change model is not complete')
    for off,value in ((8,world['manager']),(12,world['actor']),(16,world['model']),
                      (20,world['model_id']),(24,world['old_resource'])):
        require(u(ram,STAGE_CONTROL+off)==value,'Hidden Body Change model owner changed')
    donor=snapshot['target'] if physical==snapshot['source']['physical'] else snapshot['source']
    resource,handle=u(ram,STAGE_CONTROL+28),u(ram,STAGE_CONTROL+32)
    row=stage.resource_info(ram,resource,handle,donor['character'],donor['costume'],donor['damaged'])
    row.update(character=donor['character'],costume=donor['costume'],damaged=donor['damaged'])
    mid,model=u(ram,STAGE_CONTROL+40),u(ram,STAGE_CONTROL+44)
    require(mid<12 and mid!=world['model_id'] and u(ram,preload.core.MODELS+4*mid)==model and
            u(ram,model+4)==1 and u(ram,model+8)==0 and u(ram,model+16)==mid and
            u(ram,model+20)==resource and u(ram,model+12)==donor['character'],
            'Replacement model must remain independent and hidden')
    allocation=u(ram,STAGE_CONTROL+36)
    require(0x2000000<=allocation<=len(ram)-stage.ALLOC_SIZE and u(ram,model+5728)==allocation,
            'Hidden model scratch allocation changed')
    if physical<2:require(tuple(capacities or ())==NATIVE_CAPACITIES,'Leader staging capacities missing')
    return dict(physical=physical,resource=row,staged_id=mid,staged_model=model,
                allocation=allocation,dataset=u(ram,model+2356),capacities=capacities,
                receipt_words=[(STAGE_CONTROL+off,u(ram,STAGE_CONTROL+off)) for off in range(0,80,4)])


def detach_memory(ram,receipt,io_manifest,stage_manifest):
    """Restore the scratch getter, erase only exact owned preparation code.

    Buffers, hidden models and their model/skeleton backing allocations remain
    alive. A second job can reuse this workspace without changing the first.
    """
    require(all(u(ram,p)==v for p,v in receipt['receipt_words']),'Staging completion changed')
    expected_hook=struct.pack('<2I',(2<<26)|(EXTENSION>>2),0)
    at=stage.creator.EXT_ENTRY
    require(ram[at:at+8]==expected_hook,'Body scratch getter chain changed')
    for manifest in (io_manifest,stage_manifest):
        for block in manifest['blocks']:
            p=block['address'];data=bytes.fromhex(block['data_hex'])
            if p in (IO_CONTROL,STAGE_CONTROL,at):continue
            require(ram[p:p+len(data)]==data,'Body preparation code changed before detach')
    untouched=bytearray(ram[IO:0x07060000])
    for manifest in (io_manifest,stage_manifest):
        for block in manifest['blocks']:
            p=block['address'];size=len(bytes.fromhex(block['data_hex']))
            if IO<=p and p+size<=0x07060000:untouched[p-IO:p-IO+size]=bytes(size)
    require(not any(untouched),'Body preparation workspace acquired foreign data before detach')
    original=bytes(ram[OLD_EXTENSION:OLD_EXTENSION+8])
    require(original==struct.pack('<2I',(2<<26)|(stage.creator.EXT_CODE>>2),0),
            'Body scratch getter original is not owned')
    # The entire workspace was audited above, including every unused gap.
    # Only authenticated occupied spans need crossing PINE in the clear packet;
    # sending expected/new zeros for the other ~120 KiB merely stalls the hold.
    clear=[(b['address'],bytes(len(bytes.fromhex(b['data_hex']))))
           for manifest in (io_manifest,stage_manifest) for b in manifest['blocks']
           if IO<=b['address']<0x07060000]
    return parts_manifest(ram,[(at,original)]+clear,
                          status='DETACH COMPLETE HIDDEN BODY MODEL; NO BODY COMMIT')
