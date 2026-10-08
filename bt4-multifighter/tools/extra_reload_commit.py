"""Quiet, one-shot same-character costume commit for a staged extra model.

This is a dormant diagnostic service, not a transformation unlock. It preserves
the active model's address/ID, uses native destruction/reinitialization and
refreshes the owner's special resources and private AI. Old resource buffers
and their texture reservation remain retained. Any failure after destruction
requires checkpoint recovery; the caller must keep the whole match held.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

import extra_reload_stage as stage
import extra_charge_aura as ordinary
import extra_extended_auras as extended
import extra_special_pools as effects
import extra_generic_effects as generic
import extra_ground_effects as ground
import fresh_team_ai as fresh
import team_pair_ai as pair
import distinct_ai
import roster_models
from ai_shadow import Assembler as AiAssembler, AI_GLOBAL
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from twelve_prepare import copy_words
from native_map import FILE_ID

ENTRY,CACHE,REFRESH,AI=0x07620000,0x07623000,0x07623200,0x07624000
CONTROL,AI_META,END=0x0762F000,0x0762F200,0x07630000
PRIVATE_COLLISION_OFF=0x36000
assert stage.COLLISION_OFF + stage.creator.COLLISION_CAPACITY <= PRIVATE_COLLISION_OFF
assert PRIVATE_COLLISION_OFF + stage.creator.COLLISION_CAPACITY <= stage.ALLOC_SIZE
require=stage.require


def actor_initializers(native):
    cache,refresh=roster_models.private_initializers(native)
    refresh=bytearray(refresh)
    struct.pack_into('<I',refresh,0x24,(3<<26)|(CACHE>>2))
    return cache,bytes(refresh)


def ai_code(physical):
    a=AiAssembler(AI);a.addiu(29,29,-0x90)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.mem(63,r,29,i*8)
    a.load_address(16,pair.CONTROL);a.mem(35,17,28,-0x5760)
    a.load_address(8,fresh.DESCRIPTORS[physical]);a.mem(35,9,8,0)
    a.mem(35,10,9,12);a.emit((10<<16)|(11<<11)|(2<<6))
    a.load_address(12,stage.prior.core.MODELS);a.emit((11<<21)|(12<<16)|(11<<11)|0x2D)
    a.mem(35,11,11,0);a.mem(35,12,11,2356)
    a.load_address(13,fresh.RECORDS[physical])
    for off,r in ((0,9),(4,10),(8,11),(12,12)):a.mem(43,r,13,off)
    for off,r in ((32,10),(36,11),(40,12)):a.mem(43,r,8,off)
    distinct_ai.emit_initialize(a,physical,fresh.DESCRIPTORS[physical],fresh.RECORDS[physical],AI_META+0x80)
    a.addiu(2,0,5);a.branch(0,0,'done');a.nop()
    for label,status in (('invalid',201),('owned',202),('dataset_failed',203)):
        a.label(label);a.addiu(2,0,status);a.branch(0,0,'done');a.nop()
    a.label('done');a.load_address(8,AI_META);a.mem(43,2,8,0)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.mem(55,r,29,i*8)
    a.emit(0x03E00008);a.addiu(29,29,0x90)
    code=a.finish();assert len(code)<0x1000;return code


def payload(c):
    w,row=c['world'],c['resource'];a=Assembler(ENTRY);a.addiu(29,29,-0x150)
    leader=bool(c.get('leader'))
    for i,r in enumerate(effects.SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0x100+i*4)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,4);a.branch(5,8,0,'done')
    for p,value in c['guards']:
        a.li(8,p);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error110')
    for p,size in c['zero_regions']:
        a.li(8,p);a.li(9,p+size)
        label=f'zero{p:x}';a.label(label);a.lw(10,8);a.branch(5,10,0,'error111')
        a.addiu(8,8,4);a.branch(5,8,9,label)
    a.addiu(8,0,1);a.sw(8,16,4)
    if c['ground']:
        a.li(4,w['model_id']);a.call(ground.CLEANUP)
        for p in c['ground']['tables']:
            a.li(8,p);a.lw(8,8);a.branch(5,8,0,'error120')
    # Visual instances retain skeleton references. Destroy only the matched
    # owner's node, with all giant subchains drained before its destructor.
    for visual in c['visuals']:
        if not visual['node']:continue
        if visual['kind']=='giant':
            for group in range(10):a.li(4,visual['body']+16+group*144);a.call(A(0x165820))
        a.li(4,visual['node']);a.call(A(0x1ADA80))
        a.li(8,visual['table']);a.lw(8,8);a.branch(5,8,0,'error120')
    if c['generic']:
        # Its reviewed root callback drains descendants under allocator8 and
        # restores the prior selector before outer1ADA80 returns.
        if leader:
            a.li(8,c['allocator']);a.lw(9,8,148);a.sw(9,16,0x7C)
            a.addiu(9,0,7+w['physical']);a.sw(9,8,148)
        a.li(4,c['generic']['root']);a.call(A(0x1ADA80))
        if leader:
            a.li(8,c['allocator']);a.lw(9,16,0x7C);a.sw(9,8,148)
        a.li(8,c['generic']['row']);a.sw(0,8);a.sw(0,8,4)
    # Native child-pool destruction consults the current allocator selector.
    # Group5 is a bump arena; using a heap selector would free arena interiors.
    a.li(18,c['allocator']);a.addiu(19,18,16*(4+w['physical']) if leader else 80)
    for off in ((148,) if leader else range(0,156,4)):a.lw(8,18,off);a.sw(8,16,0x80+off)
    a.addiu(8,0,4+w['physical'] if leader else 5);a.sw(8,18,148)
    a.li(4,c['root']);a.call(A(0x1ADA80))
    a.li(8,c['effect_row']);a.sw(0,8,1324)
    # Restore the entire native allocator before model helpers can run.
    for off in ((148,) if leader else range(0,156,4)):a.lw(8,16,0x80+off);a.sw(8,18,off)
    a.addiu(8,0,2);a.sw(8,16,4)
    a.li(17,w['actor']);a.li(20,w['model'])
    a.move(4,20);a.call(A(0x1135F0))
    a.li(4,c['old_group']);a.call(A(0x249000))
    if c.get('adopt_entry'):a.call(c['adopt_entry'])
    a.li(21,row['collision']);a.li(22,c['new_collision'] if row['collision_size'] else 0)
    copy_words(a,'backup',21,22,row['collision_size'])
    a.li(4,w['model_id']);a.li(5,row['resource_handle']);a.call(A(0x249BD8))
    copy_words(a,'restore',22,21,row['collision_size'])
    a.sw(0,20,8)
    for field,value in ((16,w['model_id']),(20,row['resource']),(12,row['character']),(5728,c['old_scratch'])):
        a.lw(8,20,field);a.li(9,value);a.branch(5,8,9,'error130')
    a.sw(22,20,84);a.move(4,20);a.call(A(0x24DB28))
    for off in (5608,5612,5616):a.sw(0,17,off)
    a.move(4,17)
    if c.get('form') and w['owner_action'] in (241,242):
        import fusion_partner_lifecycle as fusion
        a.call(fusion.EXTRA_COMMIT)
        a.li(8,fusion.CONTROL);a.lw(9,8,28);a.branch(5,9,0,'error145')
        a.lw(9,8,24);a.branch(5,9,17,'error145')
    else:a.call(REFRESH)
    if c.get('body_pose'):
        # Body exchanges may now commit during ordinary recovery/movement.
        # Rebind that pose to the new skeleton after the restricted-ability
        # animation table is applied; do not reuse the staged donor's idle.
        animation,frame=c['body_pose']
        a.move(4,17);a.li(5,animation);a.li(8,frame)
        a.emit((17<<26)|(4<<21)|(8<<16)|(12<<11));a.call(A(0x1C3E60))
    elif not c.get('form'):
        a.move(4,17);a.move(5,0);a.emit((17<<26)|(4<<21)|(12<<11));a.call(A(0x1C3E60))
    a.move(4,17);a.addiu(5,0,1);a.call(A(0x1D7198))
    for fn in (A(0x24C958),A(0x24CC88),A(0x24E3F8)):a.move(4,20);a.call(fn)
    if c.get('reanchor_entry'):a.call(c['reanchor_entry'])
    # Recreate the same actual owner's typed special resources in its private
    # arena. The metadata bridges use the freshly initialized active model.
    a.li(23,c['record'])
    if not leader:
        a.li(8,c['arena']);a.sw(8,19);a.sw(8,19,4)
        a.li(8,effects.ARENA_BYTES);a.sw(8,19,8);a.sw(0,19,12)
    a.addiu(8,0,4+w['physical'] if leader else 5);a.sw(8,18,148)
    a.li(21,effects.CONTROL);a.li(8,w['model_id']);a.sw(8,21,20)
    a.sw(20,21,24);a.addiu(8,0,1);a.sw(8,21,16)
    a.li(4,c['rootpool']);a.li(5,A(0x2C36E8) if leader else effects.CALLBACKS);a.addiu(6,23,4);a.call(A(0x1AD7B8))
    a.sw(2,23,16);a.li(8,c['effect_row']);a.sw(2,8,1324)
    a.lw(8,19,12);a.sw(8,23,20);a.sw(0,21,16)
    for off in ((148,) if leader else range(0,156,4)):a.lw(8,16,0x80+off);a.sw(8,18,off)
    a.lw(8,23,16);a.branch(4,8,0,'error140')
    a.lw(8,23,20);a.li(9,c['arena_capacity'] if leader else effects.ARENA_BYTES);a.r(0x2B,9,9,8);a.branch(5,9,0,'error140')
    a.li(21,c['effect_row'])
    for slot in range(5):
        a.lw(8,20,156+slot*4);a.lw(9,21,slot*80+28);a.branch(5,8,9,'error141')
    if c['generic']:
        g=c['generic'];a.li(23,g['record']);a.addiu(19,18,16*(7+w['physical']) if leader else 128)
        if not leader:
            a.li(4,g['arena']);a.move(5,0);a.li(6,generic.ARENA_BYTES);a.call(A(0x2A9ACC))
            a.li(8,g['arena']);a.sw(8,19);a.sw(8,19,4)
            a.li(8,generic.ARENA_BYTES);a.sw(8,19,8);a.sw(0,19,12)
        a.addiu(8,0,7+w['physical'] if leader else 8);a.sw(8,18,148)
        a.li(21,generic.CONTROL);a.li(8,w['model_id']);a.sw(8,21,20)
        a.sw(20,21,24);a.addiu(8,0,1);a.sw(8,21,16)
        a.li(4,g['rootpool']);a.li(5,A(0x2C3BC8) if leader else generic.CALLBACKS);a.li(6,w['model_id']);a.call(A(0x1AD7B8))
        a.sw(2,23,16);a.li(8,g['row']);a.sw(2,8)
        a.lw(8,19,12);a.sw(8,23,20);a.sw(0,21,16)
        for off in ((148,) if leader else range(0,156,4)):a.lw(8,16,0x80+off);a.sw(8,18,off)
        a.lw(8,23,16);a.branch(4,8,0,'error142')
        a.lw(8,23,20);a.li(9,g['arena_capacity'] if leader else generic.ARENA_BYTES);a.r(0x2B,9,9,8);a.branch(5,9,0,'error142')
        a.li(8,g['row']);a.lw(8,8,4);a.branch(4,8,0,'error142')
    if not c.get('defer_ai'):
        a.call(AI);a.addiu(8,0,5);a.branch(5,2,8,'error150')
    # The native idle refresh intentionally leaves combat values unchanged.
    # Costume/mesh-state publication changes only the selected row identity.
    a.li(8,c['selected_row']);a.li(9,row['costume']);a.sw(9,8,4)
    a.li(9,int(row['damaged']));a.sw(9,8,96)
    if c.get('retire_staged'):
        # The temporary decoder has completed its ownership check. Return its
        # model-ID/draw nodes, then restore the non-refcounted texture bit still
        # used by the active model. Its allocation backs free shader/FX nodes
        # and active private collision, so that allocation remains retained.
        a.li(4,c['staged_id']);a.call(A(0x249B58));a.addiu(8,0,1);a.branch(5,2,8,'error160')
        a.li(4,c['new_group']);a.call(A(0x249000))
        a.li(8,c['staged_model']);a.lw(8,8,4);a.branch(5,8,0,'error160')
        a.addiu(8,0,1);a.sw(8,16,36)
    a.addiu(8,0,1);a.sw(8,20,8);a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    errors=(110,111,120,130,140,141,142,150,160)
    if c.get('form') and w['owner_action'] in (241,242):errors+=(145,)
    for error in errors:
        a.label(f'error{error}');a.addiu(8,0,error);a.sw(8,16,4);a.jump('done')
    a.label('done')
    for i in range(12):a.i(49,20+i,29,0x100+i*4)
    for i,r in enumerate(effects.SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x150);a.jr()
    code=a.finish();assert ENTRY+len(code)<CACHE;return code


def newer_effects(ram,w,guards,leader_record=None):
    """Validate optional newer families and their exact owner-cleanup code."""
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    ptr=lambda p,n:0x100000<=p<=len(ram)-n
    gen=None;gnd=None
    if any(ram[generic.CODE:generic.CODE+16]):
        leader=leader_record is not None
        primary=u(generic.GLOBAL);record=leader_record if leader else generic.RECORDS+(w['physical']-2)*64
        require(ptr(primary,12) and u(generic.CONTROL)==5 and u(generic.CONTROL+4)==w['manager'] and
                u(generic.CONTROL+8)==w['count'] and u(generic.CONTROL+40)==u(effects.ALLOC_GLOBAL) and
                u(generic.CONTROL+28)==primary and u(generic.CONTROL+48)==1 and
                u(primary+4)==generic.ROWS and u(primary+8)==12,'Generic effect pools not ready for reload')
        allocator=u(effects.ALLOC_GLOBAL);group=7+w['physical'] if leader else 8
        require(u(allocator+152)&(1<<(group+1)),'Generic allocator must use bounded arena storage')
        if not leader:require(tuple(u(record+o) for o in (0,4,8))==(w['actor'],w['model_id'],w['model']), 'Generic effect owner changed')
        arena=u(allocator+16*group) if leader else u(record+12)
        capacity=u(allocator+16*group+8) if leader else generic.ARENA_BYTES
        row=generic.ROWS+w['model_id']*48;root=u(row);rootpool=u(primary)
        callbacks=A(0x2C3BC8) if leader else generic.CALLBACKS
        require(ptr(arena,capacity) and capacity>0 and ptr(root,64) and u(root+32)==rootpool and
                u(root+40)==callbacks and (leader or u(record+16)==root) and u(row+4)!=0,'Generic effect root missing')
        for p,data in ((generic.DESTROY,generic.destroy_code()),(generic.RESOURCE,generic.resource_code()),
                       (generic.CALLBACKS,struct.pack('<3I',A(0x1720D0),A(0x171F10),generic.DESTROY))):
            require(ram[p:p+len(data)]==data,f'Generic reload helper changed:{p:08X}')
        require(u(A(0x12CDF4))==(3<<26)|(generic.RESOURCE>>2),'Generic metadata bridge call changed')
        guards += [(generic.CONTROL,5),(generic.CONTROL+4,w['manager']),(generic.CONTROL+16,0),
                   (generic.CONTROL+8,w['count']),(generic.CONTROL+40,u(effects.ALLOC_GLOBAL)),
                   (generic.CONTROL+28,primary),(generic.GLOBAL,primary),(primary+4,generic.ROWS),(primary+8,12)]
        guards += ([(allocator+16*group,arena),(allocator+16*group+8,capacity)] if leader else
                   [(record+12,arena),(record+16,root)])
        guards += [(row,root),(root+32,rootpool),(root+40,callbacks)]
        gen=dict(primary=primary,record=record,arena=arena,row=row,root=root,rootpool=rootpool)
        if leader:gen['arena_capacity']=capacity
    else:guards += [(generic.CODE+o,0) for o in range(0,16,4)]
    if any(ram[ground.CODE:ground.CODE+16]):
        require(u(ground.CONTROL)==5 and u(ground.CONTROL+4)==w['manager'] and
                u(ground.CONTROL+8)==w['count'],'Ground effect pools not ready for reload')
        for p,data in ((ground.CLEANUP,ground.cleanup()),(ground.PRED,ground.predicate())):
            require(ram[p:p+len(data)]==data,f'Ground reload helper changed:{p:08X}')
        guards += [(ground.CONTROL,5),(ground.CONTROL+4,w['manager']),(ground.CONTROL+8,w['count'])]
        for index in range(2):
            value=u(ground.GLOBALS[index]);require(ptr(value,12) and value==u(ground.CONTROL+20+4*index),
                                                'Ground captured manager changed')
            guards += [(ground.GLOBALS[index],value),(ground.CONTROL+20+4*index,value)]
        tables=[]
        for table,poolglobal,owner,callbacks in ((ground.DUST_TABLE,ground.POOLS[0],56,A(0x2C4138)),
                (ground.DUST_TABLE+48,ground.POOLS[0],56,A(0x2C4150)),(ground.AUX_TABLE,ground.POOLS[1],32,A(0x2C3B08))):
            at=table+4*w['model_id'];node=u(at);guards.append((at,node));tables.append(at)
            if node:
                require(ptr(node,64),'Ground effect node outside EE RAM');body=u(node+56);pool=u(poolglobal)
                require(ptr(body,owner+4) and u(node+32)==pool and u(node+40)==callbacks and
                        (ram[body+owner] if owner==56 else u(body+owner))==w['model_id'],'Ground effect instance owner changed')
                guards += [(poolglobal,pool),(node+32,pool),(node+40,callbacks),(node+56,body),(body+owner,u(body+owner))]
        gnd=dict(tables=tables)
    else:guards += [(ground.CODE+o,0) for o in range(0,16,4)]
    return gen,gnd


def capture(ram,quiet=False,form=False):
    require(len(ram)==0x8000000,'Requires128MiB EE RAM');u=lambda p:struct.unpack_from('<I',ram,p)[0]
    ptr=lambda p,n:0x100000<=p<=len(ram)-n
    require(u(stage.CONTROL+4)==5,'Hidden replacement stage must be ready')
    physical=u(stage.io.CONTROL+20);w=stage.prior.capture(ram,physical)
    for off,value in ((8,w['manager']),(12,w['actor']),(16,w['model']),(20,w['model_id']),(24,w['old_resource'])):
        require(u(stage.CONTROL+off)==value,'Staging owner changed')
    staged_id,staged_model=u(stage.CONTROL+40),u(stage.CONTROL+44)
    require(staged_id<12 and staged_id!=w['model_id'] and ptr(staged_model,0x1670) and
            u(stage.prior.core.MODELS+4*staged_id)==staged_model and
            u(staged_model+4)==1 and u(staged_model+8)==0,'Staging model must remain hidden')
    resource,handle=u(stage.CONTROL+28),u(stage.CONTROL+32)
    files=[u(resource+8+16*i) for i in range(3)]
    character,costume,damaged=stage.io.decode_request(ram,files)
    if form:
        import extra_reload_forms as forms
        record=forms.requests.RECORDS+(physical-2)*64
        require(quiet and 236<=w['owner_action']<=242 and u(record+4)==4 and u(record+56)==1 and
                u(record+8)==w['actor'] and u(record+20)==character and u(w['actor']+0x12D0)==character and
                u(w['actor']+0x12D4)==costume and u(w['actor']+0x12E0)==int(damaged),
                'Ordinary form commit requires its acknowledged native request')
    else:require(character==u(w['model']+12),'Costume commit requires same-character replacement')
    row=stage.resource_info(ram,resource,handle,character,costume,damaged)
    row.update(character=character,costume=costume,damaged=damaged)
    require(u(staged_model+20)==resource and u(staged_model+2356)==u(stage.CONTROL+76),'Staged resource/dataset changed')
    require(resource!=w['old_resource'] and u(w['model']+8)==1,'Active model/resource changed')
    allocation=u(stage.CONTROL+36);require(ptr(allocation,stage.ALLOC_SIZE),'Invalid staging allocation')
    old_scratch=u(w['model']+5728);require(ptr(old_scratch,0x1A0C0),'Missing active animation scratch')
    old_geometry=u(w['model']+64);require(ptr(old_geometry,112),'Missing old geometry')
    old_group=u(old_geometry+40);new_group=u(u(staged_model+64)+40)
    require(old_group<15 and new_group<15 and old_group!=new_group,'Replacement texture group is not independent')
    guards=[(stage.prior.core.ACTORS,w['manager']),(stage.prior.core.MODE,1),
            (stage.prior.core.MODE+4,w['count']),(stage.prior.core.MODE+8,w['manager']),
            (stage.prior.core.MODE+12,w['count']),(stage.prior.core.PAIR+4,0),
            (stage.CONTROL+4,5),(stage.CONTROL+44,staged_model),(staged_model+8,0),
            (w['model']+20,w['old_resource']),(w['model']+5728,old_scratch),
            (fresh.CONTROL,5),(AI_GLOBAL,u(AI_GLOBAL))]
    gen,gnd=newer_effects(ram,w,guards)
    if form:
        guards += [(record+4,4),(record+56,1),(record+8,w['actor']),(record+20,character),
                   (w['actor']+0x12D0,character),(w['actor']+0x12D4,costume),(w['actor']+0x12E0,int(damaged))]
    for i in range(3):
        for off in (0,4,8):guards.append((resource+16*i+off,u(resource+16*i+off)))
    guards += [(resource+48,3),(resource+52,handle),(staged_model+20,resource),
               (staged_model+2356,u(stage.CONTROL+76))]
    for i,actor in enumerate(w['actors']):
        held=() if quiet else ((actor+0x948,11),(actor+0x1278,0),(actor+0x127C,0),(actor+0x1280,0),(actor+0x1284,0))
        for p,value in ((stage.prior.core.POINTERS+4*i,actor),(actor,i),(actor+12,u(actor+12)))+held:
            require(u(p)==value,'Commit requires all captured actors held idle');guards.append((p,value))
    if quiet:
        import extra_reload_quiet
        extra_reload_quiet.validate(ram,w,form);guards+=extra_reload_quiet.checks(w,form)
    require(u(fresh.DESCRIPTORS[physical])==w['actor'] and
            u(fresh.DESCRIPTORS[physical]+4)==fresh.SHADOWS[physical], 'Private AI owner mismatch')
    require(u(fresh.SHADOWS[physical]+0x10+(physical&1)*0x520+36)&1==0,'Private AI unexpectedly owns dataset')
    primary,allocator=u(effects.GLOBAL),u(effects.ALLOC_GLOBAL);record=effects.RECORDS+(physical-2)*64
    require(ptr(primary,12) and ptr(allocator,156),'Special manager/allocator missing')
    require(u(effects.CONTROL)==5 and u(effects.CONTROL+4)==w['manager'] and
            u(primary+4)==effects.ROWS and u(primary+8)==12,'Own special pools must be ready')
    require(tuple(u(record+o) for o in (0,4,8))==(w['actor'],w['model_id'],w['model']),'Special owner record changed')
    arena=u(record+12);require(ptr(arena,effects.ARENA_BYTES),'Missing private special arena')
    require(u(allocator+152)&64,'Allocator5 must use bounded arena storage')
    effect_row=effects.ROWS+w['model_id']*effects.ROW_BYTES;root=u(effect_row+1324);rootpool=u(primary)
    require(ptr(root,64) and u(root+32)==rootpool and u(root+40)==effects.CALLBACKS and
            u(record+16)==root,'Missing owned special root')
    guards += [(effects.GLOBAL,primary),(effects.ALLOC_GLOBAL,allocator),(effects.CONTROL,5),
               (effects.CONTROL+4,w['manager']),(effects.CONTROL+16,0),(effect_row+1324,root),
               (root+32,rootpool),(root+40,effects.CALLBACKS),(allocator+152,u(allocator+152))]
    visuals=[]
    specs=[('ordinary',ordinary.GLOBAL,ordinary.POOL_GLOBAL,1168,100,ordinary.CONTROL,A(0x2C3A48))]
    specs += [(f['name'],f['global_'],f['poolglobal'],f['tableoff'],f['owner'],extended.CONTROL,f['child']) for f in extended.FAMILIES]
    for kind,global_,poolglobal,tableoff,owner,control,callbacks in specs:
        family,pool=u(global_),u(poolglobal);require(ptr(family,tableoff+4) and ptr(pool,24),'Visual family missing')
        table=u(family+tableoff)
        if u(control)!=5:
            # Old bounded two-owner families cannot contain this extra.
            require(u(family)==2,'Unreviewed visual family capacity');continue
        require(u(control+4)==w['manager'],'Visual family belongs to another match')
        at=table+4*w['model_id'];node=u(at);guards.append((at,node))
        body=0
        if node:
            body=u(node+56)
            require(ptr(node,64) and ptr(body,owner+4) and u(node+32)==pool and
                    u(node+36)==0 and u(node+40)==callbacks and u(body+owner)==w['model_id'],'Visual instance owner mismatch')
            guards += [(node+32,pool),(node+36,0),(node+40,callbacks),(node+56,body),(body+owner,w['model_id'])]
        visuals.append(dict(kind=kind,table=at,node=node,body=body))
    slot=u(w['actor']+0x994);require(slot<u(w['actor']+0x998)<=5,'Invalid selected row')
    selected=w['actor']+0x9A4+164*slot;require(u(selected)==u(w['model']+12),'Selected character changed')
    # Existing input hold is caller-owned; this module never releases it.
    return dict(world=w,resource=row,staged_model=staged_model,staged_id=staged_id,
                new_collision=allocation+PRIVATE_COLLISION_OFF,old_scratch=old_scratch,
                old_group=old_group,new_group=new_group,guards=guards,zero_regions=[],
                allocator=allocator,arena=arena,record=record,effect_row=effect_row,
                root=root,rootpool=rootpool,visuals=visuals,selected_row=selected,generic=gen,ground=gnd,form=form)


def build_memory(ram,source='<offline-held-reload>',quiet=False,retire_staged=False,form=False):
    c=capture(ram,quiet,form);require(not any(ram[ENTRY:END]),'Reload commit reservation occupied')
    c['retire_staged']=bool(retire_staged)
    _,_,native=elf_reader(elf_path(ROOT))
    for p,n in ((A(0x1135F0),0x70),(A(0x249BD8),0x70),(A(0x249000),0x58),(A(0x1C0058),0xD0),
                (A(0x1C0538),0x570),(A(0x1ADA80),0xB0),(A(0x1AD6A8),0x80),(A(0x1A71B8),0x40)):
        require(ram[p:p+n]==native(p,n),f'Native commit helper changed:{p:08X}')
    if retire_staged:
        for p,n in ((A(0x249B58),0x58),(A(0x249910),0xA0)):
            require(ram[p:p+n]==native(p,n),f'Native staged retirement helper changed:{p:08X}')
    for code,target,field in ((effects.RESOURCE,A(0x14BC98),156),(effects.BLAST1,A(0x205370),2352),(effects.BLAST2,A(0x205330),2348)):
        data=effects.bridge(code,target,field);require(ram[code:code+len(data)]==data,'Special metadata bridge changed')
    for p,data in ((distinct_ai.MODEL_BRIDGE,distinct_ai.role_bridge(distinct_ai.MODEL_BRIDGE,A(0x2499B0))),
                   (distinct_ai.HEIGHT_BRIDGE,distinct_ai.role_bridge(distinct_ai.HEIGHT_BRIDGE,A(0x204EA0))),
                   (distinct_ai.RADIUS_BRIDGE,distinct_ai.role_bridge(distinct_ai.RADIUS_BRIDGE,A(0x2062F0)))):
        require(ram[p:p+len(data)]==data,'Private AI model alias bridge changed')
    cache,refresh=actor_initializers(native);control=bytearray(0x200)
    struct.pack_into('<6I',control,8,c['world']['manager'],c['world']['actor'],c['world']['model'],
                     c['resource']['resource'],c['world']['old_resource'],c['world']['model_id'])
    pieces=[(ENTRY,payload(c)),(CACHE,cache),(REFRESH,refresh),(AI,ai_code(c['world']['physical'])),
            (CONTROL,bytes(control)),(AI_META,bytes(0x100))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),configuration=c,
                entry=ENTRY,control=CONTROL,quiet=quiet,status='DORMANT QUIET COSTUME COMMIT; NO AUTOMATIC RELOAD UNLOCK',
                blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in pieces],
                requirements=['Caller keeps every actor held idle before, throughout and after the single ENTRY invocation.',
                              'Enable CONTROL then invoke once; status5 and AI_META5 are required before any later release.',
                              'Any failure requires checkpoint restoration. Old buffers, staging model and groups remain retained.'],
                limitations=['Same-character costume only; no automatic damage event or transformation routing.',
                             'No resource retirement/cache eviction. This diagnostic is one transaction per checkpoint.',
                             'Native model/render/AI helpers still require live validation together.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    x=p.parse_args();x.out.write_text(json.dumps(build_memory(read_ram(x.source),x.source),indent=2)+'\n');print(x.out)
