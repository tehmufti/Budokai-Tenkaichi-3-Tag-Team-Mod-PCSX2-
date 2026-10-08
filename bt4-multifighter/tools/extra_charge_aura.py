"""Expand the ordinary native aura family for a held captured four/six team.

Offline only. No new resources, native allocator writes, process or PINE calls.
The separate giant/afterimage/projectile families remain unchanged.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

import aura_index_guard as bounds
import fresh_team_combat as core
import team_start_gate as start_gate
import team_intro as intro
from camera_snapshot import read_ram
from prototype import Assembler, ROOT, elf_reader
from battle_mode_policy import ACTOR_COUNTS

PREDICATE, OLD_PREDICATE, FREE, FREE_TAIL = 0x07540000,0x07540400,0x07540800,0x07540C00
CONTROL, RECORDS, TABLE = 0x0754F000,0x0754F100,0x07550000
NODES, PAYLOADS, PARTICLES208, PARTICLES176 = 0x07550100,0x07550400,0x07554000,0x07573000
END, CAPACITY = 0x0757D000,12
GLOBAL, POOL_GLOBAL, FREE_ENTRY = A(0x2FEA00),A(0x2FEA0C),A(0x164EB8)
INITIALIZE, HOOK = 0x07541000,A(0x1C2A28)
MODEL_LOADS = (A(0x1D0568),A(0x1D05A8),A(0x1D05E0))
SAVED = tuple(range(1,29))+(30,31)


def predicate_code():
    # Existing thirteen wrappers expect only v0/v1 to change here.
    a=Assembler(PREDICATE);a.addiu(29,29,-0x20)
    for i,r in enumerate((8,9,10,11)):a.i(63,r,29,i*8)
    a.li(8,CONTROL);a.lw(9,8,4);a.lw(10,28,-22364)
    a.branch(5,9,10,'old');a.lw(9,8,8);a.lw(10,28,-22640)
    a.branch(5,9,10,'old');a.branch(4,10,0,'old')
    a.i(11,2,4,2);a.branch(5,2,0,'allowed')
    a.lw(9,8);a.addiu(11,0,5);a.branch(5,9,11,'denied')
    a.lw(9,10,1168);a.li(11,TABLE);a.branch(5,9,11,'denied')
    a.i(11,2,4,CAPACITY);a.branch(4,2,0,'denied')
    a.lw(11,8,12);a.li(9,RECORDS)
    a.label('scan');a.lw(10,9,4);a.branch(4,10,4,'found')
    a.addiu(9,9,12);a.addiu(11,11,-1);a.branch(5,11,0,'scan');a.jump('denied')
    a.label('found');a.lw(10,9);a.lw(10,10,12);a.branch(5,10,4,'denied')
    a.label('allowed');a.move(2,0);a.jump('done')
    a.label('denied');a.lw(9,8,48);a.addiu(9,9,1);a.sw(9,8,48);a.sw(4,8,52)
    a.addiu(2,0,1)
    a.label('done')
    for i,r in enumerate((8,9,10,11)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x20);a.jr()
    a.label('old')
    for i,r in enumerate((8,9,10,11)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x20);a.jump(OLD_PREDICATE)
    code=a.finish();assert len(code)<0x400;return code


def free_code():
    # Destroy aura instances while their manager and wide table still exist.
    # Native whole-module destructor otherwise releases its table first.
    a=Assembler(FREE);a.addiu(29,29,-0x100)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    a.li(8,CONTROL);a.lw(9,8,8);a.lw(10,28,-22640)
    a.branch(5,9,10,'done');a.branch(4,10,0,'done')
    a.lw(9,10,1168);a.li(11,TABLE);a.branch(5,9,11,'done')
    a.lw(4,8,16);a.call(A(0x1AD9F8))
    a.li(8,CONTROL);a.lw(10,8,8)
    for control,offset in ((20,1168),(24,12),(28,24),(32,4),(36,8),
                           (56,16),(60,28),(64,36),(68,40)):
        a.lw(9,8,control);a.sw(9,10,offset)
    a.sw(0,10,20);a.sw(0,10,32) # Original active lists were verified empty.
    a.addiu(9,0,90);a.sw(9,8)
    a.label('done')
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x100);a.jump(FREE_TAIL)
    code=a.finish();assert len(code)<0x400;return code


def require(value,why):
    if not value:raise ValueError(why)


def initialize_code(previous,actors,mids,models,detached176=()):
    """Drain native instances under the hold, then publish all new storage."""
    a=Assembler(INITIALIZE);a.addiu(29,29,-0x130)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0x100+i*4)
    a.li(16,CONTROL);a.lw(8,16);a.branch(5,8,0,'done')
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'error101')
    for address,value in ((core.MODE,1),(core.MODE+4,len(actors)),(core.MODE+12,len(actors)),(core.PAIR+4,0)):
        a.li(8,address);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error101')
    a.li(8,core.MODE+8);a.lw(8,8);a.lw(9,16,4);a.branch(5,8,9,'error101')
    for i,(actor,mid,model) in enumerate(zip(actors,mids,models)):
        for address,value in ((core.POINTERS+4*i,actor),(actor,i),(actor+12,mid),
                              (core.MODELS+4*mid,model),(actor+0x948,11),
                              (actor+0x1278,0),(actor+0x127C,0),(actor+0x1280,0),(actor+0x1284,0)):
            a.li(8,address);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error102')
    a.lw(17,16,8);a.lw(8,28,-22640);a.branch(5,17,8,'error103')
    a.lw(18,16,16);a.lw(8,28,-22628);a.branch(5,18,8,'error103')
    for offset,control in ((1168,20),(12,24),(24,28),(4,32),(8,36)):
        a.lw(8,17,offset);a.lw(9,16,control);a.branch(5,8,9,'error103')
    a.addiu(8,0,1);a.sw(8,16);a.move(4,18);a.call(A(0x1AD9F8))
    # Native164810 removed only owned particles and cleared both old rows.
    for offset in (4,8):a.lw(8,18,offset);a.branch(5,8,0,'error104')
    a.lw(9,16,20)
    for offset in (0,4):a.lw(8,9,offset);a.branch(5,8,0,'error104')
    for offset in (20,32):a.lw(8,17,offset);a.branch(5,8,0,'error104')
    # Native1617D0 can replace an expiring head through1615D8/161170,
    # then overwrite that new head while unlinking the expired particle.
    # Reclaim only the bounded, owned detached records proven by the builder,
    # and only AFTER native destruction has drained all live instances.
    for particle in detached176:
        a.li(9,particle);a.lw(8,17,28);a.sw(8,9,160);a.sw(9,17,28)
    # The original pool's two now-free nodes must still form its whole chain.
    a.lw(19,18,12);a.lw(20,16,76);a.branch(4,19,20,'first_ok')
    a.addiu(8,20,64);a.branch(5,19,8,'error105')
    a.label('first_ok');a.lw(21,19,52);a.branch(4,21,19,'error105')
    a.branch(4,21,20,'second_ok');a.addiu(8,20,64);a.branch(5,21,8,'error105')
    a.label('second_ok');a.lw(8,21,52);a.branch(5,8,0,'error105')
    # Save fully drained history for later native module teardown.
    for control,offset in ((56,16),(60,28),(64,36),(68,40)):
        a.lw(8,17,offset);a.sw(8,16,control)
    for offset,value in ((1168,TABLE),(4,600),(8,216),(12,PARTICLES208),(24,PARTICLES176),
                         (16,0),(20,0),(28,0),(32,0),(36,0),(40,0)):
        a.li(8,value);a.sw(8,17,offset)
    a.li(8,NODES);a.sw(8,21,52)
    a.addiu(8,0,5);a.sw(8,16);a.lw(8,16,84);a.addiu(8,8,1);a.sw(8,16,84)
    a.jump('done')
    for error in (101,102,103,104,105):
        a.label(f'error{error}');a.addiu(8,0,error);a.sw(8,16);a.jump('done')
    a.label('done');a.li(16,CONTROL);a.lw(8,16);a.addiu(9,0,5);a.branch(4,8,9,'restore')
    a.lw(11,16,4);a.lw(9,28,-22364);a.branch(5,11,9,'restore')
    for name,control in (('start',start_gate.CONTROL),('intro',intro.CONTROL)):
        a.li(8,control);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,f'skip_{name}')
        a.lw(9,8,8);a.branch(5,9,11,f'skip_{name}');a.sw(0,8,4)
        a.label(f'skip_{name}')
    a.label('restore')
    for i in range(12):a.i(49,20+i,29,0x100+i*4)
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x130);a.jump(previous)
    result=a.finish();assert INITIALIZE+len(result)<CONTROL;return result


def drained_particles(ram,aura,base,capacity,stride,free_off,active_off,high_off,next_off):
    """Validate every previously allocated particle is now on its own free list.

    Native high-water marks do not shrink after particles are destroyed. A
    drained warm pool may therefore have nonzero history without live effects.
    Never migrate live particles or carry old addresses into the new arrays.
    """
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    require(u(aura+active_off)==0,'Aura particle active lists must be empty before migration')
    high=u(aura+high_off);head=u(aura+free_off)
    require(high<=capacity,'Aura particle high-water exceeds native capacity')
    node=head;seen=set()
    while node:
        delta=node-base
        require(0<=delta<high*stride and delta%stride==0 and node not in seen,
                'Invalid native aura particle free list')
        seen.add(node);node=u(node+next_off)
    require(len(seen)==high,'Aura particle free list must contain every allocated particle')
    return head,high


def particle_partition(ram,aura,base,capacity,stride,free_off,active_off,high_off,next_off,owner_off,owners,*,detached176=None):
    """Bound both native chains before permitting native instance destruction."""
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    high=u(aura+high_off);require(high<=capacity,'Aura particle high-water exceeds native capacity')
    seen=set()
    for offset in (free_off,active_off):
        node=u(aura+offset)
        while node:
            delta=node-base
            require(0<=delta<high*stride and delta%stride==0 and node not in seen,
                    'Invalid native aura particle partition')
            seen.add(node)
            if offset==active_off:
                require(ram[node+owner_off] in owners,'Active particle has no owned aura instance')
            node=u(node+next_off)
    missing={base+i*stride for i in range(high)}-seen
    if missing and detached176 is not None:
        require((capacity,stride,free_off,active_off,high_off,next_off,owner_off)==(36,176,28,32,40,160,4),
                'Detached recovery is limited to the native replacement-particle family')
        for node in missing:
            # Its original instance may already have been destroyed; unlike
            # reachable active particles, this is not a live ownership claim.
            require(ram[node+4]<2 and ram[node+7]==1,
                    'Detached aura particle has no native owner or initialized emitter')
            chain=set();tail=node
            while tail and tail not in seen:
                require(tail in missing and tail not in chain,'Invalid detached aura particle chain')
                chain.add(tail);tail=u(tail+next_off)
        detached176.extend(sorted(missing))
    else:
        require(not missing,'Aura particle partition must contain every allocated particle')
    return u(aura+free_off),high


def build_memory(ram,config=None,source='<offline-held>'):
    require(len(ram)==0x8000000,'Requires128MiB EE checkpoint')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if ram[PREDICATE:PREDICATE+len(predicate_code())]==predicate_code():
        return upgrade_memory(ram,config,source)
    ptr=lambda p,size=4:0x100000<=p<=len(ram)-size
    manager=u(core.ACTORS);count=u(core.MODE+4)
    require(ptr(manager,16) and u(manager)==2,'Expected native two-actor manager')
    require(count in ACTOR_COUNTS and u(core.MODE)==1 and u(core.MODE+8)==manager and
            u(core.MODE+12)==count and not u(core.PAIR+4),'Expected captured four/six team without aliases')
    actors=[];mids=[];models=[]
    for i in range(count):
        actor=u(core.POINTERS+4*i);require(ptr(actor,0x1600) and u(actor)==i,'Actor identity mismatch')
        mid=u(actor+12);require(mid<CAPACITY and mid not in mids,'Invalid/duplicate actual model ID')
        model=u(core.MODELS+4*mid)
        require(ptr(model,0x1670) and u(model+16)==mid,'Actual model registration mismatch')
        require(u(actor+0x948)==11 and all(u(actor+x)==0 for x in (0x1278,0x127C,0x1280,0x1284)),
                'Install only while all fighters are held idle with CPU/input zero')
        actors.append(actor);mids.append(mid);models.append(model)
    require(mids[:2]==[0,1],'Original aura leaders must own models0/1')
    aura=u(GLOBAL);pool=u(POOL_GLOBAL)
    require(ptr(aura,1184) and u(aura)==2 and ptr(pool,24),'Expected native aura manager/pool')
    oldtable=u(aura+1168);p208=u(aura+12);p176=u(aura+24)
    require(ptr(oldtable,8),'Invalid original aura table')
    require((u(aura+4),u(aura+8))==(100,36) and ptr(p208,20800) and ptr(p176,6336),
            'Unexpected native particle capacities')
    module=u(pool);require(ptr(module,64) and u(module+36)==pool and u(module+40)==A(0x2C3A30),
                          'Aura module hierarchy mismatch')
    original_nodes=u(pool+16);original_payloads=u(pool+20)
    require(ptr(original_nodes,128) and ptr(original_payloads,2*0x510),'Invalid original aura allocations')
    active=u(pool+4);seen=[];owners=set();previous_node=0
    while active:
        require(active in (original_nodes,original_nodes+64) and active not in seen,'Invalid native aura active list')
        body=u(active+56)
        require(u(active+32)==pool and body==original_payloads+(active-original_nodes)//64*0x510 and
                u(active+36)==0 and u(active+40)==A(0x2C3A48) and u(active+44)==previous_node,
                'Invalid owned native aura instance')
        mid=u(body+100)
        require(mid<2 and mid not in owners and u(oldtable+4*mid)==active,'Aura table ownership mismatch')
        owners.add(mid);seen.append(active);previous_node=active;active=u(active+48)
    require(u(pool+8)==previous_node,'Aura active tail mismatch')
    for mid in range(2):require((u(oldtable+4*mid)!=0)==(mid in owners),'Orphaned aura table entry')
    free=u(pool+12)
    while free:
        require(free in (original_nodes,original_nodes+64) and free not in seen,'Invalid native aura free list')
        require(u(free+32)==pool and u(free+56)==original_payloads+(free-original_nodes)//64*0x510,
                'Invalid aura node owner/payload')
        seen.append(free);free=u(free+52)
    require(len(seen)==2,'Every native aura node must be active or free')
    free208,high208=particle_partition(ram,aura,p208,100,208,16,20,36,192,7,owners)
    detached176=[]
    free176,high176=particle_partition(ram,aura,p176,36,176,28,32,40,160,4,owners,detached176=detached176)
    allocator=u(A(0x2FEAE0))
    require(ptr(allocator,156) and u(allocator+152)&0x3FE==0x3FE,
            'Static extension requires the preserved native bump allocator policy')
    require(not any(ram[PREDICATE:END]),'Ordinary aura reservation occupied')
    _,_,native=elf_reader(elf_path(ROOT))
    old=bounds.predicate_code()
    require(ram[bounds.PREDICATE:bounds.PREDICATE+len(old)]==old,'Changed aura bounds predicate')
    require(tuple(u(bounds.CONTROL+off) for off in (0,4,8,12))==(1,manager,aura,2),
            'Aura guard ownership mismatch')
    for i,entry in enumerate(bounds.ENTRIES):
        origin=native(entry,12 if entry==A(0x165180) else 8)
        wrapper=bounds.wrapper_code(i,origin);address=bounds.WRAPPERS+0x100*i
        require(ram[address:address+len(wrapper)]==wrapper and u(entry)==(2<<26)|(address>>2),
                'Aura entry wrapper changed')
    require(ram[FREE_ENTRY:FREE_ENTRY+8]==native(FREE_ENTRY,8),'Changed native aura free entry')
    for p in MODEL_LOADS:require(u(p)==0x8E040000,'Aura physical-ID callsite changed')
    nodes=bytearray(10*64)
    for i in range(10):
        base=i*64;struct.pack_into('<H',nodes,base+2,i+2)
        struct.pack_into('<I',nodes,base+32,pool)
        struct.pack_into('<I',nodes,base+52,NODES+(i+1)*64 if i<9 else 0)
        struct.pack_into('<I',nodes,base+56,PAYLOADS+i*0x510)
    previous=(u(HOOK)&0x3FFFFFF)<<2
    require(u(HOOK)>>26==2 and u(HOOK+4)==0 and 0x07000000<=previous<0x08000000,
            'Expected captured held frame chain')
    control=struct.pack('<23I',0,manager,aura,count,pool,oldtable,p208,p176,100,36,module,0,0,0,
                        free208,free176,high208,high176,previous,original_nodes,original_payloads,0,2)
    records=b''.join(struct.pack('<3I',a,m,p) for a,m,p in zip(actors,mids,models))
    pieces=[(PREDICATE,predicate_code()),(OLD_PREDICATE,old),(FREE,free_code()),
            (FREE_TAIL,native(FREE_ENTRY,8)+struct.pack('<2I',(2<<26)|((FREE_ENTRY+8)>>2),0)),
            (CONTROL,control),(RECORDS,records),(NODES,nodes),
            (INITIALIZE,initialize_code(previous,actors,mids,models,detached176))]
    # Keep M+0=2: its runtime loop exclusively services the separate giant-aura
    # module. Ordinary aura update/draw follows the extended instance pool.
    # Runtime native draining precedes all array/table publication in one call.
    for p in MODEL_LOADS:pieces.append((p,struct.pack('<I',0x8E04000C)))
    pieces += [(FREE_ENTRY,struct.pack('<2I',(2<<26)|(FREE>>2),0)),
               (bounds.PREDICATE,struct.pack('<2I',(2<<26)|(PREDICATE>>2),0)),
               (HOOK,struct.pack('<2I',(2<<26)|(INITIALIZE>>2),0))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),
                status='HELD NATIVE AURA DRAIN; WAIT STATUS5 BEFORE RELEASE',
                control=CONTROL,actors=actors,model_ids=mids,models=models,aura_manager=aura,aura_pool=pool,
                previous_frame=previous,initializer=INITIALIZE,version=2,detached_particles_reclaimed=detached176,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=bytes(data).hex()) for p,data in pieces],
                limitations=['Only ordinary ki-charge/glow aura is expanded; giant/afterimage/tracked charge-burst families stay protected.',
                             'Native aura module count remains2 for its separate giant-aura loop; table/instance capacity is12.',
                             'Native sound suppression and bright-white overlay protection remain unchanged.',
                             'Static extended pools are retained until checkpoint reset.'])


def upgrade_memory(ram,config=None,source='<offline-v1-ready>'):
    """Add the v2 frame contract to already expanded v1 held presets.

    Their active effects/storage stay untouched: status5 makes the new frame
    wrapper a pass-through. This path never repeats draining or node appending.
    """
    require(len(ram)==0x8000000,'Requires128MiB EE checkpoint')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager=u(core.ACTORS);count=u(core.MODE+4);aura=u(GLOBAL);pool=u(POOL_GLOBAL)
    require(count in ACTOR_COUNTS and u(core.MODE)==1 and u(core.MODE+8)==manager and
            u(core.MODE+12)==count and not u(core.PAIR+4),'Expected captured four/six team without aliases')
    require(tuple(u(CONTROL+o) for o in (0,4,8,12,16))==(5,manager,aura,count,pool),
            'Only ready captured v1 aura storage can be upgraded')
    require(u(aura+1168)==TABLE and u(aura+12)==PARTICLES208 and u(aura+24)==PARTICLES176 and
            (u(aura+4),u(aura+8))==(600,216),'Expanded v1 aura storage mismatch')
    actors=[];mids=[];models=[]
    for i in range(count):
        actor,mid,model=struct.unpack_from('<3I',ram,RECORDS+12*i)
        require(u(core.POINTERS+4*i)==actor and u(actor)==i and u(actor+12)==mid and
                u(core.MODELS+4*mid)==model,'Captured v1 actor/model identity mismatch')
        require(u(actor+0x948)==11 and all(u(actor+o)==0 for o in (0x1278,0x127C,0x1280,0x1284)),
                'Upgrade only a held idle checkpoint')
        actors.append(actor);mids.append(mid);models.append(model)
    for p,data in ((PREDICATE,predicate_code()),(OLD_PREDICATE,bounds.predicate_code()),(FREE,free_code())):
        require(ram[p:p+len(data)]==data,'Changed v1 aura code')
    require(not any(ram[INITIALIZE:CONTROL]),'Aura initializer reservation occupied')
    require(not any(ram[CONTROL+72:CONTROL+92]),'Changed v1 aura extension metadata')
    require(u(bounds.PREDICATE)==(2<<26)|(PREDICATE>>2) and u(FREE_ENTRY)==(2<<26)|(FREE>>2),
            'Changed v1 aura dispatch hooks')
    previous=(u(HOOK)&0x3FFFFFF)<<2
    require(u(HOOK)>>26==2 and u(HOOK+4)==0 and 0x07000000<=previous<0x08000000,
            'Expected captured held frame chain')
    pieces=[(INITIALIZE,initialize_code(previous,actors,mids,models)),
            (CONTROL+72,struct.pack('<5I',previous,u(pool+16),u(pool+20),1,2)),
            (HOOK,struct.pack('<2I',(2<<26)|(INITIALIZE>>2),0))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),version=2,
                status='READY V1 AURA STORAGE PRESERVED; V2 FRAME CONTRACT ADDED',
                control=CONTROL,actors=actors,model_ids=mids,models=models,aura_manager=aura,aura_pool=pool,
                previous_frame=previous,initializer=INITIALIZE,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in pieces])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path);x=p.parse_args()
    result=build_memory(read_ram(x.source),source=x.source)
    x.out.write_text(json.dumps(result,indent=2)+'\n');print(x.out)
