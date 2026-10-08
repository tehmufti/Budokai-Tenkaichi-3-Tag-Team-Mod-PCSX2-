"""Construct and bind Cell's independently loaded temporary Android.

Shares the serial hidden-model workspace with extra_reload_stage. A caller
must finish this transaction before reusing that workspace for the real form.
Native kind2 auxiliary update, animation, rendering and destruction then own
actor+1330/1334/1338. No native leader queue or singleton loader is used.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

import extra_reload_aux_io as auxiliary
import extra_reload_preload as prior
import extra_reload_quiet as quiet
import extra_reload_stage as stage
from prototype import Assembler, ROOT, elf_reader

ENTRY, CONTROL, END = stage.ENTRY, stage.CONTROL, stage.END
FIELDS = stage.FIELDS
# Kind2 has no fighter scratch region. Both intrusive nodes must outlive their
# model because native destruction returns them to shared free lists. As with
# normal staging, these small backing allocations remain until match teardown.
NODE_BYTES, SHADER_OFF, FX_OFF = 0x2200, 0, 0x2100
NATIVE = elf_reader(elf_path(ROOT))[2]
require = stage.require
HELPERS = ((A(0x249AB8),0xA0),(A(0x249A28),0x90),(A(0x2499B0),0x18),
           (A(0x113598),0x58),(A(0x113528),0x70),(A(0x255CF0),0x30),
           (A(0x1D3540),0x28),(A(0x1D3568),0x48),(A(0x1D35B0),0xB8),
           (A(0x1D3668),0x50),(A(0x1D36B8),0xD8),(A(0x1D3790),0xC0))


def configuration(ram,character,costume):
    require(len(ram)==0x8000000,'Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    row=auxiliary.completed_resource(ram,character,costume)
    w=prior.capture(ram,u(auxiliary.CONTROL+20));actor=w['actor']
    quiet.validate(ram,w,True)
    require(w['owner_action']==239,'Auxiliary is only serviced for Cell absorption')
    for key in ('manager','actor','model','physical','old_resource','old_dataset','registry'):
        require(u(auxiliary.CONTROL+prior.FIELDS[key])==w[key],f'Auxiliary IO owner changed:{key}')
    slot=u(actor+0x994);count=u(actor+0x998)
    require(slot<count<=5,'Invalid Cell selected row')
    selected=actor+0x9A4+slot*164;source=u(selected)
    require(source in (105,106) and character==source-4 and u(actor+0x12D0)==source+1,
            'Cell source, destination or auxiliary identity changed')
    require(u(actor+0x12F0)==character and u(actor+0x12F4)==costume,
            'Native Cell auxiliary request changed')
    require(not any(u(actor+off) for off in (0x1330,0x1334,0x1338)),
            'Cell already owns an auxiliary')
    resource=row['resource'];pool=row['pool'];handle=row['resource_handle']
    mesh,size=u(resource),u(resource+4)
    require(resource!=w['old_resource'] and not row['geometry_initialized'],
            'Auxiliary must own a fresh independently loaded mesh')
    occupied=[];live=[]
    for mid in range(12):
        model=u(prior.core.MODELS+4*mid)
        if not model:continue
        require(0x100000<=model<=len(ram)-0x1670,'Invalid registered model')
        if u(model+4)!=1:continue
        occupied.append(mid);old=u(model+20)
        require(0x100000<=old<=len(ram)-56 and old!=resource,'Auxiliary resource already has a model')
        for i in range(3):
            other,n=u(old+i*16),u(old+i*16+4)
            require(not n or mesh+size<=other or other+n<=mesh,
                    'Auxiliary mesh overlaps a registered model resource')
        live += [(prior.core.MODELS+4*mid,model),(model+4,1),(model+20,old)]
    # The actual form still needs its own hidden staging model and texture.
    require(len(occupied)<=10 and u(pool+69128)>=2,'Cell requires auxiliary and form model capacity')
    require(u(pool+397320)>=row['draw_nodes'],'Insufficient auxiliary draw capacity')
    # The same rule as the preflight, which admitted this job under the same hold.
    require(auxiliary.texture_room(ram),'Cell requires auxiliary and form texture capacity')
    require(any(not u(w['registry']+i*56+48)&1 for i in range(12)),
            'Cell requires a free record for the actual form')
    require(not any(ram[ENTRY:END]),'Auxiliary staging workspace must be restored before reuse')
    for address,size in HELPERS:
        import extra_cell_absorption
        require(ram[address:address+size] in extra_cell_absorption.helper_images(address,size),
                f'Native auxiliary helper changed:{address:08X}')
    guards=quiet.checks(w,True)+[
        (prior.core.ACTORS,w['manager']),(prior.core.MODE,1),(prior.core.MODE+4,w['count']),
        (prior.core.MODE+8,w['manager']),(prior.core.MODE+12,w['count']),(prior.core.PAIR+4,0),
        (prior.REGISTRY_GLOBAL,pool),(auxiliary.CONTROL+4,5),(auxiliary.CONTROL+40,1),
        (auxiliary.CONTROL+44,1),(auxiliary.CONTROL+32,resource),(auxiliary.CONTROL+36,handle),
        (actor+12,w['model_id']),(w['model']+20,w['old_resource']),
        (actor+0x994,slot),(actor+0x998,count),(selected,source),
        (actor+0x12D0,source+1),(actor+0x12F0,character),(actor+0x12F4,costume),
        (actor+0x1330,0),(actor+0x1334,0),(actor+0x1338,0),
        (resource+48,3),(resource+52,handle)]+live
    for i,pointer in enumerate(w['actors']):guards += [(prior.core.POINTERS+4*i,pointer),(pointer,i)]
    for i in range(3):
        for off in (0,4,8,12):guards.append((resource+16*i+off,u(resource+16*i+off)))
        for off in (64,80,96):guards.append((auxiliary.CONTROL+off+4*i,u(auxiliary.CONTROL+off+4*i)))
    return dict(world=w,resource=row,occupied_model_ids=occupied,guards=guards)


def payload(c):
    w,row=c['world'],c['resource'];pool=row['pool'];actor=w['actor']
    a=Assembler(ENTRY);a.addiu(29,29,-0x80)
    saved=tuple(range(16,24))+(31,)
    for i,r in enumerate(saved):a.i(63,r,29,8*i)
    for i in range(4):a.i(57,20+i,29,0x60+4*i)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,4);a.branch(5,8,0,'done')
    for p,value in c['guards']:
        a.li(8,p);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error110')
    for off,minimum in ((69128,2),(397320,row['draw_nodes'])):
        a.li(8,pool+off);a.lw(8,8);a.li(9,minimum)
        a.r(0x2B,8,8,9);a.branch(5,8,0,'error120')
    a.addiu(8,0,1);a.sw(8,16,4)
    # Allocate all backing memory before inserting any native intrusive node.
    for reg,size,align,field in ((18,NODE_BYTES,64,36),(19,192,32,52),
            (20,stage.creator.PACKET_BYTES,64,56),(21,stage.creator.PACKET_BYTES,64,60)):
        a.li(4,size);a.addiu(5,0,align);a.move(6,0);a.addiu(7,0,1)
        a.call(A(0x2554D8));a.branch(4,2,0,'error130');a.move(reg,2);a.sw(reg,16,field)
        a.move(4,reg);a.move(5,0);a.li(6,size);a.call(A(0x2A9ACC))
    a.sw(20,19);a.sw(21,19,4);a.sw(19,18,8240)
    for off,listoff,field in ((SHADER_OFF,439072,68),(FX_OFF,397776,72)):
        a.addiu(5,18,off);a.sw(5,16,field);a.li(4,pool+listoff);a.call(A(0x255CF0))
    a.addiu(4,0,2);a.li(5,row['resource']);a.move(6,0);a.call(A(0x249AB8))
    a.move(22,2);a.i(11,8,22,12);a.branch(4,8,0,'error140')
    for mid in c['occupied_model_ids']:
        a.addiu(8,0,mid);a.branch(4,22,8,'error140')
    a.sw(22,16,40);a.move(4,22);a.call(A(0x2499B0))
    a.branch(4,2,0,'error141');a.move(19,2);a.sw(19,16,44)
    for off,value in ((0,2),(4,1),(8,0),(12,row['character']),(20,row['resource']),
                       (64,row['geometry']),(84,row['collision']),(1864,row['aux_animation'])):
        a.lw(8,19,off);a.li(9,value);a.branch(5,8,9,'error142')
    a.lw(8,19,16);a.branch(5,8,22,'error142')
    a.lw(8,19,5736);a.lw(9,16,68);a.branch(5,8,9,'error143')
    a.lw(8,19,5732);a.branch(4,8,0,'fx_valid');a.lw(9,16,72);a.branch(5,8,9,'error143')
    a.label('fx_valid')
    # Pose before exposure; animation4 is selected at the original native
    # absorption frame by 1D36B8. Native per-fighter update handles attachment.
    a.move(4,19);a.li(5,w['model']+2384);a.li(6,w['model']+2400);a.call(A(0x1D3128))
    a.li(4,actor);a.li(5,row['resource_handle']);a.move(6,22);a.call(A(0x1D3540))
    for off,value in ((0x1330,1),(0x1334,row['resource_handle'])):
        a.li(8,actor+off);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error144')
    a.li(8,actor+0x1338);a.lw(8,8);a.branch(5,8,22,'error144')
    # Publication is not the start of the authored absorption animation.
    # Keep the prop dormant until native1D36B8 selects animation422 and sets
    # its animation clock. The owned render adapter checks that clock.
    a.sw(0,19,8);a.sw(0,19,0xC70)
    a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    for error in (110,120,130,140,141,142,143,144):
        a.label(f'error{error}');a.addiu(8,0,error);a.sw(8,16,4);a.jump('done')
    a.label('done');a.lw(2,16,4)
    for i in range(4):a.i(49,20+i,29,0x60+4*i)
    for i,r in enumerate(saved):a.i(55,r,29,8*i)
    a.addiu(29,29,0x80);a.jr();data=a.finish()
    assert len(data)<CONTROL-ENTRY
    return data


def build_memory(ram,character,costume=0,source='<auxiliary>'):
    c=configuration(ram,character,costume);w,row=c['world'],c['resource']
    control=bytearray(0x100)
    for off,value in ((8,w['manager']),(12,w['actor']),(16,w['model']),(20,w['model_id']),
                      (24,w['old_resource']),(28,row['resource']),(32,row['resource_handle']),
                      (40,0xFFFFFFFF)):
        struct.pack_into('<I',control,off,value)
    pieces=((ENTRY,payload(c)),(CONTROL,bytes(control)))
    return dict(serial=SERIAL,crc=CRC,source=str(source),entry=ENTRY,control=CONTROL,
        fields=FIELDS,configuration=c,world=w,resource=row,occupied_model_ids=c['occupied_model_ids'],
        status='DORMANT CELL AUXILIARY CONSTRUCTION AND PUBLICATION',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex())for p,d in pieces],
        requirements=[
            'Invoke only under the acknowledged native quiet hold; status5 means bound type2 Android.',
            'Restore this serial staging workspace before staging the actual fighter form.',
            'Native Cell animation179 calls1D3568 to destroy this model and release its independent mesh.',
            'Retain shader/FX backing allocations until match teardown because native free lists own their nodes.',
            'Any error keeps combat held for caller recovery; never publish or free a partially constructed model.'])
