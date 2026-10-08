"""Held two-body replacement with explicit native leader resource adoption.

All participants and both hidden models are
validated before the first model destructor. Failure after publication keeps
the caller's native hold engaged and requires checkpoint recovery.
"""
from native_map import A
import copy
import math
import struct

import body_swap as body
import body_swap_resources as resources
import extra_reload_commit as old
from prototype import Assembler

ENTRY, CONTROL, DATA = 0x07060000, 0x0706F000, 0x0706F800
OWNERS=(0x07070000,0x07080000)
END=0x07090000
# Native marker-only model adjustment (SLUS_216.78.c:200939-200941): after a
# reload with the restriction marker, sub_1C0538 calls sub_24FFE8(model), the
# sole writer of the model+1880 pointer table (:276493-276515). The commit's
# REFRESH runs the sub_1C0538 tail under action 11 (switch default), so the
# attacker's owner helper wraps REFRESH and reproduces that call itself.
ABILITY_REFRESH,ABILITY_REFRESH_SIZE=A(0x24FFE8),0xC8
REFRESH_OFF,INNER_REFRESH_OFF=0x3200,0x3400
ANCHOR_OFF=0x6000
require,u=body.require,body.u


def marker_refresh_code(entry,inner,model):
    """REFRESH wrapper: native tail first, then sub_24FFE8 on the rebuilt model."""
    a=Assembler(entry);a.addiu(29,29,-16);a.i(63,31,29,0)
    a.call(inner);a.li(4,model);a.call(ABILITY_REFRESH)
    a.i(55,31,29,0);a.addiu(29,29,16);a.jr()
    data=a.finish();assert len(data)<INNER_REFRESH_OFF-REFRESH_OFF;return data


def anchor_code(entry,actor,model,root):
    """Preserve the world root and refresh the replacement skeleton's pivot.

    Native1D7198 subtracts actor+96 (the prior skeleton's local root).
    Native1D70E8 normally refreshes it after pose evaluation; our held
    replacement omitted that step, leaving different sized bodies with the
    old pivot on their first ordinary movement update.
    """
    a=Assembler(entry);a.addiu(29,29,-16);a.i(63,31,29,0);a.li(8,model)
    for i,bits in enumerate(root[:3]):
        a.li(9,bits);a.emit((17<<26)|(4<<21)|(9<<16))
        a.i(49,1,8,2416+4*i);a.emit((17<<26)|(16<<21)|(1<<16)|1)
        a.i(49,1,8,2384+4*i);a.emit((17<<26)|(16<<21)|(1<<16))
        a.i(57,0,8,2384+4*i)
    a.li(4,model);a.call(A(0x24E2B0));a.li(4,model);a.call(A(0x24E3F8))
    a.li(4,actor);a.call(A(0x1D70E8))
    a.i(55,31,29,0);a.addiu(29,29,16);a.jr()
    return a.finish()


def ptr(ram,p,n=4):return 0x100000<=p<=len(ram)-n and p%4==0


def adoption(ram,w,receipt):
    """Plan ownership transfer; no file bytes or resource ownership change here."""
    if w['physical']>=2:return None
    original=w['old_resource'];replacement=receipt['resource']['resource']
    registry=w['registry'];side=w['physical']
    require(original==registry+0x2A0+56*side and u(ram,original+48)==1 and
            u(ram,original+52)==side and u(ram,registry+0x348)==1,
            'Leader must retain its original native resource handle')
    require(tuple(receipt['capacities'] or ())==resources.NATIVE_CAPACITIES,
            'Adopted leader buffers require native maximum capacities')
    old_geometry,new_geometry=u(ram,original),u(ram,replacement)
    retention=[registry+p for p in (0x31C,0x32C,0x33C) if u(ram,registry+p)==old_geometry]
    require(len(retention)==1,'Leader geometry must have one native cleanup owner')
    # Native +340 points at one of the live rotating scratch triples.
    scratch=u(ram,registry+0x340)
    require(scratch in (registry+0x310,registry+0x320,registry+0x330) and
            u(ram,scratch)!=old_geometry,'Leader geometry is still the active reload scratch')
    aliases=[];guards=[]
    for mid in range(12):
        model=u(ram,resources.preload.core.MODELS+4*mid)
        if not model:continue
        require(ptr(ram,model,0x1670),'Registered model pointer changed')
        if u(ram,model+4)!=1:continue
        if u(ram,model+20)==original and model!=w['model']:aliases.append(model)
        guards += [(resources.preload.core.MODELS+4*mid,model),(model+4,1),(model+20,u(ram,model+20))]
    require(receipt['staged_model'] not in aliases,'Staged resource is not independent')
    for p in (original,replacement):
        guards += [(p+off,u(ram,p+off)) for off in range(0,56,4)]
    guards += [(retention[0],old_geometry),(registry+0x340,scratch),(scratch,u(ram,scratch))]
    return dict(original=original,replacement=replacement,retention=retention[0],
                old_geometry=old_geometry,new_geometry=new_geometry,aliases=aliases,
                staged_model=receipt['staged_model'],guards=guards)


def adoption_code(plan,entry):
    """Called after old model destruction while both actors remain held.

    Exchange only file triples. Flags/handles and live scratch triples retain
    their native meaning. The retired dynamic record now owns the old bundle;
    native match-exit cleanup retains the new leader geometry exactly once.
    """
    a=Assembler(entry);a.li(8,plan['original']);a.li(9,plan['replacement'])
    for field in (0,16,32):
        for off in (0,4,8):
            a.lw(10,8,field+off);a.lw(11,9,field+off)
            a.sw(11,8,field+off);a.sw(10,9,field+off)
    a.li(8,plan['retention']);a.li(9,plan['new_geometry']);a.sw(9,8)
    for model in plan['aliases']:
        a.li(8,model);a.li(9,plan['replacement']);a.sw(9,8,20)
    # Keep the staged decoder alive until the active model consumes its texture
    # and independent collision/shader backing. Its descriptor must track the
    # new files after the exchange, before any model helper can inspect it.
    a.li(8,plan['staged_model']);a.li(9,plan['original']);a.sw(9,8,20)
    a.jr();data=a.finish();assert len(data)<0x1000;return data


def configuration(ram,snapshot,receipt,index):
    physical=receipt['physical'];w=resources.body_world(ram,snapshot,physical)
    owner=snapshot['source'] if physical==snapshot['source']['physical'] else snapshot['target']
    donor=snapshot['target'] if owner is snapshot['source'] else snapshot['source']
    require(0<=w['owner_action']<236,'Both bodies must have left authored/reload actions')
    row=copy.deepcopy(receipt['resource']);model=receipt['staged_model'];mid=receipt['staged_id']
    require(0<=mid<12 and mid!=w['model_id'] and ptr(ram,model,0x1670) and
            u(ram,resources.preload.core.MODELS+4*mid)==model and
            u(ram,model+4)==1 and u(ram,model+8)==0 and u(ram,model+16)==mid and
            u(ram,model+20)==row['resource'] and u(ram,model+12)==donor['character'] and
            u(ram,model+2356)==receipt['dataset'],'Completed hidden replacement changed')
    checked=resources.stage.resource_info(ram,row['resource'],row['resource_handle'],
                                        donor['character'],donor['costume'],donor['damaged'])
    require(all(checked[k]==row[k] for k in checked),'Hidden replacement bundle changed')
    allocation=receipt['allocation'];scratch=u(ram,w['model']+5728)
    require(ptr(ram,allocation,resources.stage.ALLOC_SIZE) and ptr(ram,scratch,0x1A0C0),
            'Private animation/collision backing is missing')
    require(u(ram,model+5728)==allocation,'Hidden model allocation changed')
    geometry=u(ram,w['model']+64);new_geometry=u(ram,model+64)
    require(ptr(ram,geometry,112) and ptr(ram,new_geometry,112),'Geometry header changed')
    old_group,new_group=u(ram,geometry+40),u(ram,new_geometry+40)
    require(old_group<15 and new_group<15 and old_group!=new_group,'Independent texture groups required')
    base=OWNERS[index];leader=physical<2
    guards=resources.quiet_checks(w)+[(old.fresh.CONTROL,5),(old.AI_GLOBAL,u(ram,old.AI_GLOBAL)),
        (resources.preload.core.PAIR+4,0),(w['model']+5728,scratch),
        (resources.preload.core.MODELS+4*mid,model),(model+4,1),(model+8,0),
        (model+20,row['resource']),(model+2356,receipt['dataset']),
        (row['resource']+48,3),(row['resource']+52,row['resource_handle'])]
    for field in range(0,48,4):guards.append((row['resource']+field,u(ram,row['resource']+field)))
    for i,actor in enumerate(w['actors']):guards += [(resources.preload.core.POINTERS+4*i,actor),(actor,i)]
    require(u(ram,old.fresh.DESCRIPTORS[physical])==w['actor'] and
            u(ram,old.fresh.DESCRIPTORS[physical]+4)==old.fresh.SHADOWS[physical],
            'Private AI owner changed')
    require(not u(ram,old.fresh.SHADOWS[physical]+0x10+(physical&1)*0x520+36)&1,
            'Private AI may not own the original combat bundle')
    generic,ground=old.newer_effects(ram,w,guards,base+0xF440 if leader else None)
    primary,allocator=u(ram,old.effects.GLOBAL),u(ram,old.effects.ALLOC_GLOBAL)
    require(ptr(ram,primary,12) and ptr(ram,allocator,156),'Special resource manager missing')
    require(u(ram,old.effects.CONTROL)==5 and u(ram,old.effects.CONTROL+4)==w['manager'] and
            u(ram,primary+4)==old.effects.ROWS and u(ram,primary+8)==12,'Special resource pools not ready')
    group=4+physical if leader else 5;record=base+0xF400 if leader else old.effects.RECORDS+(physical-2)*64
    arena=u(ram,allocator+16*group) if leader else u(ram,record+12)
    capacity=u(ram,allocator+16*group+8) if leader else old.effects.ARENA_BYTES
    require(ptr(ram,arena,capacity) and capacity>0 and u(ram,allocator+152)&(1<<(group+1)),
            'Special owner requires a bounded arena')
    effect_row=old.effects.ROWS+w['model_id']*old.effects.ROW_BYTES
    root=u(ram,effect_row+1324);rootpool=u(ram,primary);callbacks=A(0x2C36E8) if leader else old.effects.CALLBACKS
    require(ptr(ram,root,64) and u(ram,root+32)==rootpool and u(ram,root+40)==callbacks,
            'Special owner root changed')
    if not leader:
        require(tuple(u(ram,record+o) for o in (0,4,8))==(w['actor'],w['model_id'],w['model']) and
                u(ram,record+16)==root,'Extra special pool owner changed')
    guards += [(old.effects.GLOBAL,primary),(old.effects.ALLOC_GLOBAL,allocator),
        (old.effects.CONTROL,5),(old.effects.CONTROL+4,w['manager']),(old.effects.CONTROL+16,0),
        (effect_row+1324,root),(root+32,rootpool),(root+40,callbacks),(allocator+152,u(ram,allocator+152))]
    if leader:guards += [(allocator+16*group,arena),(allocator+16*group+8,capacity)]
    visuals=[]
    specs=[('ordinary',old.ordinary.GLOBAL,old.ordinary.POOL_GLOBAL,1168,100,old.ordinary.CONTROL,A(0x2C3A48))]
    specs += [(f['name'],f['global_'],f['poolglobal'],f['tableoff'],f['owner'],old.extended.CONTROL,f['child'])
              for f in old.extended.FAMILIES]
    for kind,global_,poolglobal,tableoff,owner_field,control,callbacks in specs:
        family,pool=u(ram,global_),u(ram,poolglobal)
        require(ptr(ram,family,tableoff+4) and ptr(ram,pool,24),'Visual family missing')
        require(u(ram,control)==5 and u(ram,control+4)==w['manager'],'Expanded visual family not ready')
        at=u(ram,family+tableoff)+4*w['model_id'];node=u(ram,at);guards.append((at,node));node_body=0
        if node:
            require(ptr(ram,node,64),'Visual node changed');node_body=u(ram,node+56)
            require(ptr(ram,node_body,owner_field+4) and u(ram,node+32)==pool and u(ram,node+36)==0 and
                    u(ram,node+40)==callbacks and u(ram,node_body+owner_field)==w['model_id'],
                    'Visual instance owner changed')
            guards += [(node+32,pool),(node+36,0),(node+40,callbacks),(node+56,node_body),
                       (node_body+owner_field,w['model_id'])]
        visuals.append(dict(kind=kind,table=at,node=node,body=node_body))
    adopt=adoption(ram,w,receipt)
    if adopt:
        guards+=adopt['guards'];row['resource']=adopt['original'];row['resource_handle']=physical
    return dict(world=w,resource=row,staged_model=model,staged_id=mid,
        new_collision=allocation+old.PRIVATE_COLLISION_OFF,old_scratch=scratch,
        old_group=old_group,new_group=new_group,guards=guards,zero_regions=[],
        allocator=allocator,arena=arena,arena_capacity=capacity,record=record,effect_row=effect_row,
        root=root,rootpool=rootpool,visuals=visuals,selected_row=owner['row'],generic=generic,ground=ground,
        form=w['owner_action']!=11,leader=leader,adoption=adopt,adopt_entry=base+0x5000 if adopt else None,
        retire_staged=True,defer_ai=True)


def code(configurations,rows):
    a=Assembler(ENTRY);a.addiu(29,29,-0x90)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(63,r,29,i*8)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,4);a.branch(5,8,0,'done')
    # No native calls occur until BOTH plans pass all checks. Their helper
    # bodies run without stale cross-owner guards inside this one held call.
    checks={}
    for c in configurations:
        for p,v in c['guards']:
            require(p not in checks or checks[p]==v,'Conflicting transaction preflight')
            checks[p]=v
    for p,v in checks.items():
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error110')
    a.addiu(8,0,1);a.sw(8,16,4)
    for i,(c,row) in enumerate(zip(configurations,rows)):
        a.li(8,row['row']);a.li(9,DATA+i*body.ROW_BYTES);a.li(10,row['row']+body.ROW_BYTES)
        a.label(f'row{i}');a.lw(11,9);a.sw(11,8);a.addiu(8,8,4);a.addiu(9,9,4);a.branch(5,8,10,f'row{i}')
        a.li(8,c['world']['actor'])
        for off,val in ((0x12D0,c['resource']['character']),(0x12D4,c['resource']['costume']),
                        (0x12E0,int(c['resource']['damaged']))):a.li(9,val);a.sw(9,8,off)
        a.li(8,OWNERS[i]+0xF000);a.addiu(9,0,1);a.sw(9,8)
        a.call(OWNERS[i]);a.li(8,OWNERS[i]+0xF004);a.lw(8,8);a.addiu(9,0,5)
        a.branch(5,8,9,f'error{120+i}')
    # Only complete bodies may become datasets for private own/enemy contexts.
    for i in range(2):
        a.call(OWNERS[i]+0x4000);a.addiu(8,0,5);a.branch(5,2,8,f'error{130+i}')
    a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    for n in (110,120,121,130,131):
        a.label(f'error{n}');a.addiu(8,0,n);a.sw(8,16,4);a.jump('done')
    a.label('done');a.lw(2,16,4)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x90);a.jr();data=a.finish();assert len(data)<0xF000;return data


def build_memory(ram,snapshot,receipts,source='<held-body-pair>'):
    require(len(receipts)==2 and [r['physical'] for r in receipts]==
            [snapshot['source']['physical'],snapshot['target']['physical']],
            'Two ordered, independent body receipts required')
    require(not any(ram[ENTRY:END]),'Body commit workspace is occupied')
    require(receipts[0]['staged_id']!=receipts[1]['staged_id'] and
            receipts[0]['resource']['resource']!=receipts[1]['resource']['resource'],
            'Body replacements must have independent model and resource slots')
    cs=[configuration(ram,snapshot,r,i) for i,r in enumerate(receipts)]
    for i,c in enumerate(cs):
        actor,model=c['world']['actor'],c['world']['model']
        root=tuple(u(ram,model+2416+4*j) for j in range(4))
        frame=struct.unpack('<f',bytes(ram[model+3192:model+3196]))[0]
        require(all(math.isfinite(x) for x in struct.unpack('<4f',struct.pack('<4I',*root)))
                and math.isfinite(frame) and 0<=frame<100000,'Invalid Body Change pose')
        c['body_pose']=(u(ram,actor+2420),u(ram,model+3192))
        c['body_root']=root;c['reanchor_entry']=OWNERS[i]+ANCHOR_OFF
        c['guards'] += [(model+2416+4*j,value) for j,value in enumerate(root)]
        c['guards'] += [(actor+2420,c['body_pose'][0]),(model+3192,c['body_pose'][1])]
    for p,n in ((A(0x1135F0),0x70),(A(0x249BD8),0x70),(A(0x249000),0x58),(A(0x1C0058),0xD0),
                (A(0x1C0538),0x570),(A(0x1ADA80),0xB0),(A(0x1AD6A8),0x80),(A(0x1A71B8),0x40),
                (A(0x249B58),0x58),(A(0x249910),0xA0),(ABILITY_REFRESH,ABILITY_REFRESH_SIZE),
                (A(0x1D70E8),0xB0),(A(0x24E2B0),0x148),(A(0x24E3F8),0xB0)):
        import giant_options
        require(ram[p:p+n]==giant_options.native_helper(ram,p,n,body.NATIVE),f'Native body commit helper changed:{p:08X}')
    rows=body.desired_rows(snapshot);control=bytearray(0x100)
    struct.pack_into('<2I',control,8,snapshot['world']['manager'],snapshot['source']['actor'])
    parts=[(ENTRY,code(cs,rows)),(CONTROL,bytes(control)),
           (DATA,b''.join(bytes.fromhex(r['data_hex']) for r in rows))]
    for i,c in enumerate(cs):
        base=OWNERS[i];values=dict(ENTRY=base,CACHE=base+0x3000,REFRESH=base+REFRESH_OFF,
                                 AI=base+0x4000,CONTROL=base+0xF000,AI_META=base+0xF200)
        inner=dict(c,guards=[])
        cache,refresh=old.stage.prior.core.rebound(old.actor_initializers,**values)(body.NATIVE)
        c['ability_refresh']=bool(rows[i]['marker'])
        if c['ability_refresh']:
            # The marker body keeps the native order: cache/tail refresh, then
            # sub_24FFE8, before the animation start and model helpers.
            refresh_parts=[(base+REFRESH_OFF,marker_refresh_code(base+REFRESH_OFF,base+INNER_REFRESH_OFF,c['world']['model'])),
                           (base+INNER_REFRESH_OFF,refresh)]
        else:refresh_parts=[(base+REFRESH_OFF,refresh)]
        parts += [(base,old.stage.prior.core.rebound(old.payload,**values)(inner)),
                  (c['reanchor_entry'],anchor_code(c['reanchor_entry'],c['world']['actor'],c['world']['model'],c['body_root'])),
                  (base+0x3000,cache)]+refresh_parts+[
                  (base+0x4000,old.stage.prior.core.rebound(old.ai_code,**values)(c['world']['physical'])),
                  (base+0xF000,bytes(0x300))]
        if c['adoption']:parts.append((base+0x5000,adoption_code(c['adoption'],base+0x5000)))
        if c['leader']:
            for offset,g in ((0xF400,c),(0xF440,c['generic'])):
                if g:
                    record=bytearray(64)
                    struct.pack_into('<6I',record,0,c['world']['actor'],c['world']['model_id'],c['world']['model'],
                                     g['arena'],g['root'],0)
                    parts.append((base+offset,bytes(record)))
    require(all(ENTRY<=p and p+len(d)<=END for p,d in parts),'Body commit exceeds reservation')
    return resources.parts_manifest(ram,parts,status='DORMANT ATOMIC BODY COMMIT; CALLER KEEPS HOLD',
        source=str(source),entry=ENTRY,control=CONTROL,configurations=cs,rows=rows)
