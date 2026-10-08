"""Held leader reconstruction and retained-partner reactivation.

Only scalar roster fields are restored. Model/resource pointers are rebuilt by
the reviewed independent native leader adoption path, never snapshot-copied.
The partner's owned model survives consumption; its drained FX roots and AI
contexts are constructed again before participation and controllers publish.
"""
from native_map import A
import copy
import math
import struct
from types import SimpleNamespace
from prototype import Assembler
import fusion_duration as timer
import body_swap as body
import body_swap_resources as resources
import body_swap_commit as commit
import extra_reload_commit as reload
import fresh_team_camera as camera
import spectator_switch as spectator

u,require=body.u,body.require
PARTNER=commit.OWNERS[1]
PLACEMENT_OFF=0x6800


def placement_code(base,actor,model):
    """Refresh both collision frames after a restored body changes location."""
    a=Assembler(base+PLACEMENT_OFF);a.addiu(29,29,-16);a.i(63,31,29,0)
    a.call(base+commit.ANCHOR_OFF)
    a.li(4,model);a.move(5,0);a.call(A(0x24DC58))
    a.li(8,actor)
    # A consumed partner has not run physics/input since the fusion began.
    # Its old movement/sweep cannot be replayed from its former location.
    for off in range(64,96,4):a.sw(0,8,off)
    for off in range(0,48,4):a.lw(9,8,16+off);a.sw(9,8,256+off)
    a.li(8,model);a.lw(9,8,4000);a.lw(10,8,4004)
    for off in range(0,32,4):a.lw(11,9,off);a.sw(11,10,off)
    a.addiu(4,0,-1);a.addiu(5,8,2416);a.call(A(0x23FF78))
    a.li(8,model);a.sw(2,8,2596)
    a.i(55,31,29,0);a.addiu(29,29,16);a.jr();return a.finish()


def restore_views(a,snap):
    """Publish the real human seats before the held commit can render again.

    The ordinary lifecycle tick is suspended during retirement/audio upload.
    Waiting for that tick leaves both seats on the vanished fusion meanwhile.
    Only this pair is changed; an unrelated concurrent fusion keeps its views.
    Return v0=1 after publishing authenticated multiplayer seats, so the
    legacy co-op fallback cannot overwrite an arbitrary human-seat order.
    """
    import multiplayer_fusion as multi
    import quad_viewports as views
    import quad_lifecycle as seats
    a.li(8,multi.CONTROL);a.lw(9,8);a.li(10,multi.MAGIC);a.branch(5,9,10,'views_done')
    a.lw(9,8,4);a.li(10,snap['world']['manager']);a.branch(5,9,10,'views_done')
    a.li(8,views.CONTROL);a.lw(9,8);a.li(10,views.MAGIC);a.branch(5,9,10,'views_done')
    row=multi.ROWS+snap['side']*multi.STRIDE
    a.li(8,row);a.lw(9,8,multi.F['status']);a.addiu(10,0,3);a.branch(5,9,10,'views_done')
    a.lw(9,8,multi.F['partner']);a.li(10,snap['partner']['physical']);a.branch(5,9,10,'views_done')
    for seat in range(4):
        a.li(8,views.CONTROL);a.lw(9,8,views.VIEW_COUNT);a.i(11,9,9,seat+1);a.branch(5,9,0,f'view_next{seat}')
        a.li(8,seats.CONTROL+seats.F['owned']+4*seat);a.lw(9,8)
        a.li(10,snap['side']);a.branch(4,9,10,f'view_pair{seat}')
        a.li(10,snap['partner']['physical']);a.branch(5,9,10,f'view_next{seat}')
        a.label(f'view_pair{seat}');a.li(8,views.SUBJECTS+4*seat);a.sw(9,8)
        if seat<2:
            a.li(8,camera.SUCCESSOR_CONTROL+8+4*seat);a.sw(9,8)
            a.li(8,spectator.CONTROL+spectator.FIELDS['lock']+4*seat);a.sw(0,8)
        for field in ('held','watching'):
            a.li(8,seats.CONTROL+seats.F[field]+4*seat);a.sw(0,8)
        a.label(f'view_next{seat}')
    a.li(8,row);a.sw(0,8,multi.F['status']);a.addiu(2,0,1);a.jump('views_return')
    a.label('views_done');a.move(2,0);a.label('views_return')


def health_split(remaining,leader,partner):
    if any(type(n) is not int or n<0 for n in (remaining,leader,partner)) or not leader or not partner:
        raise ValueError('Positive pre-fusion health and nonnegative remaining health required')
    budget=min(remaining,leader+partner)
    # Rounding belongs to the leader; neither participant exceeds its saved
    # health, and the sum cannot exceed the actually remaining merged pool.
    hp_partner=budget*partner//(leader+partner)
    return budget-hp_partner,hp_partner


def snapshot(ram,side):
    require(type(side) is int and 0<=side<u(ram,timer.CONTROL+8),'Captured physical survivor required');record=timer.RECORDS+side*timer.STRIDE
    require(u(ram,record)==3,'Defusion requires an expired held receipt')
    w=body.world(ram);leader=body.body(ram,w,side)
    require(u(ram,timer.CONTROL+4)==w['manager'] and u(ram,timer.CONTROL+8)==w['count'],'Fusion match changed')
    require(leader['actor']==u(ram,record+8) and leader['controller']==u(ram,record+56),'Fusion leader ownership changed')
    physical=u(ram,record+20);actor=u(ram,record+12)
    require(2<=physical<w['count'] and physical&1==side&1 and physical!=side and w['actors'][physical]==actor,'Fusion partner identity changed')
    require(u(ram,timer.part.CONSUMED)&(1<<physical),'Partner no longer consumed')
    mid,model,resource=(u(ram,record+off) for off in (28,36,44));slot=u(ram,record+52)
    require(u(ram,actor+12)==mid and u(ram,timer.core.MODELS+4*mid)==model and
            u(ram,model+4)==1 and u(ram,model+8)==0 and u(ram,model+16)==mid and u(ram,model+20)==resource,
            'Retained fusion partner model/resource changed')
    require(u(ram,actor+0x994)==slot and u(ram,actor+4)==u(ram,record+64),'Fusion partner control/slot changed')
    require(bytes(ram[resource:resource+56])==bytes(ram[record+0x300:record+0x338]),'Retained partner resource bundle changed')
    originals=[bytes(ram[record+off:record+off+164]) for off in timer.ROW_OFFSETS]
    require(u(ram,model+12)==struct.unpack_from('<I',originals[1])[0],'Fusion partner form changed')
    hp=health_split(leader['health'],*(struct.unpack_from('<I',row,64)[0] for row in originals))
    destination=copy.deepcopy(leader)
    destination.update(character=struct.unpack_from('<I',originals[0])[0],costume=struct.unpack_from('<I',originals[0],4)[0],
                       damaged=bool(struct.unpack_from('<I',originals[0],96)[0]),row_hex=originals[0].hex(),physical=physical)
    partner=dict(physical=physical,actor=actor,model_id=mid,model=model,resource=resource,slot=slot,
                 row=actor+0x9A4+164*slot,controller=u(ram,record+64),cpu=u(ram,record+68))
    rows=[]
    for index,owner in enumerate((leader,partner)):
        active_slot=u(ram,record+48+4*index);row=owner['actor']+0x9A4+164*active_slot
        data=bytearray(ram[row:row+164])
        # Native selected-row pointers (120+) retain current ownership.
        data[:120]=originals[index][:120];struct.pack_into('<I',data,64,hp[index])
        # Consumed ki/stocks cannot be restored above their pre-fusion level.
        if index==0:
            for off in (76,84):struct.pack_into('<I',data,off,min(u(ram,leader['row']+off),struct.unpack_from('<I',data,off)[0]))
        rows.append(dict(actor=owner['actor'],row=row,data_hex=data.hex(),health=hp[index],slot=active_slot,
                         controller=u(ram,record+56+8*index),cpu=u(ram,record+60+8*index)))
    return dict(world=w,source=leader,target=destination,partner=partner,record=record,
                originals=originals,rows=rows,generation=u(ram,record+72),side=side)


def body_world(ram,snap,physical):
    require(physical==snap['source']['physical'],'Defusion stages only its original leader')
    now=snapshot(ram,snap['side'])
    require(now['generation']==snap['generation'] and now['world']==snap['world'],'Defusion ownership changed')
    for key in ('actor','model_id','model','resource','row','character','costume','controller','cpu'):
        require(now['source'][key]==snap['source'][key],f'Defusion leader changed:{key}')
    world=resources.preload.capture(ram,physical,allow_leaders=True)
    world['body_guards']=[(snap['record'],3),(snap['record']+72,snap['generation']),
                          (timer.part.CONSUMED,u(ram,timer.part.CONSUMED)),(snap['partner']['model']+20,snap['partner']['resource'])]
    for p,v in resources.quiet_checks(world):require(u(ram,p)==v,'Defusion needs acknowledged native hold')
    return world


def invoke(function,*args):return timer.core.rebound(function,body_world=body_world)(*args)


def partner_plan(ram,snap):
    p=snap['partner'];guards=[];allocator=u(ram,reload.effects.ALLOC_GLOBAL)
    require(commit.ptr(ram,allocator,156),'Partner allocator missing')
    specs=[]
    for module,group,offset in ((reload.effects,5,1324),(reload.generic,8,0)):
        primary=u(ram,module.GLOBAL);record=module.RECORDS+(p['physical']-2)*64
        row=module.ROWS+p['model_id']*(1344 if group==5 else 48);arena=u(ram,record+12)
        require(u(ram,module.CONTROL)==5 and u(ram,module.CONTROL+4)==snap['world']['manager'] and
                u(ram,primary+4)==module.ROWS and u(ram,primary+8)==12,'Partner effect manager changed')
        require(tuple(u(ram,record+off) for off in (0,4,8))==(p['actor'],p['model_id'],p['model']),
                'Partner effect ownership changed')
        require(commit.ptr(ram,arena,module.ARENA_BYTES) and not u(ram,row+offset) and
                u(ram,allocator+152)&(1<<(group+1)),'Partner effects were not completely drained')
        pool=u(ram,primary);require(commit.ptr(ram,pool,24),'Partner FX root pool missing')
        guards += [(module.CONTROL,5),(module.CONTROL+4,snap['world']['manager']),
                   (module.CONTROL+16,0),(record,p['actor']),(record+4,p['model_id']),
                   (record+8,p['model']),(record+12,arena),(row+offset,0)]
        specs.append(dict(module=module,group=group,row=row,record=record,arena=arena,pool=pool,offset=offset))
    for table in (reload.ordinary.TABLE,)+tuple(f['table'] for f in reload.extended.FAMILIES)+(reload.ground.DUST_TABLE,reload.ground.DUST_TABLE+48,reload.ground.AUX_TABLE):
        require(not u(ram,table+4*p['model_id']),'Partner visual survived fusion drain');guards.append((table+4*p['model_id'],0))
    for at,value in ((p['actor']+2376,216),(p['model']+4,1),(p['model']+8,0),(p['model']+20,p['resource']),
                     (p['row']+64,0),(timer.part.CONSUMED,u(ram,timer.part.CONSUMED)),
                     (snap['record'],3),(snap['record']+72,snap['generation'])):
        require(u(ram,at)==value,'Consumed partner changed');guards.append((at,value))
    return dict(partner=p,allocator=allocator,specs=specs,guards=guards)


def partner_code(plan):
    a=Assembler(PARTNER);a.addiu(29,29,-0x120)
    regs=(16,17,18,19,20,21,22,23,31)
    for i,r in enumerate(regs):a.i(63,r,29,i*8)
    p=plan['partner'];a.li(18,plan['allocator'])
    for off in range(0,156,4):a.lw(8,18,off);a.sw(8,29,0x70+off)
    a.li(17,p['actor']);a.li(20,p['model'])
    for off,val in ((2376,11),(2380,-1),(2384,11),(2388,-1),(2392,-1),(2396,-1),(2400,-1),(2404,0),(2408,0)):
        a.addiu(8,0,val);a.sw(8,17,off)
    a.move(4,17);a.call(PARTNER+commit.REFRESH_OFF)
    a.move(4,17);a.move(5,0);a.emit((17<<26)|(4<<21)|(12<<11));a.call(A(0x1C3E60))
    a.move(4,17);a.addiu(5,0,1);a.call(A(0x1D7198))
    for fn in (A(0x24C958),A(0x24CC88),A(0x24E3F8)):a.move(4,20);a.call(fn)
    a.call(PARTNER+PLACEMENT_OFF)
    for spec in plan['specs']:
        module=spec['module'];a.li(23,spec['record']);a.addiu(19,18,16*spec['group'])
        a.li(4,spec['arena']);a.move(5,0);a.li(6,module.ARENA_BYTES);a.call(A(0x2A9ACC))
        a.li(8,spec['arena']);a.sw(8,19);a.sw(8,19,4);a.li(8,module.ARENA_BYTES);a.sw(8,19,8);a.sw(0,19,12)
        a.addiu(8,0,spec['group']);a.sw(8,18,148);a.li(21,module.CONTROL)
        a.li(8,p['model_id']);a.sw(8,21,20);a.sw(20,21,24);a.addiu(8,0,1);a.sw(8,21,16)
        a.li(4,spec['pool']);a.li(5,module.CALLBACKS)
        if spec['group']==5:a.addiu(6,23,4)
        else:a.li(6,p['model_id'])
        a.call(A(0x1AD7B8));a.sw(2,23,16);a.li(8,spec['row']);a.sw(2,8,spec['offset']);a.sw(0,21,16)
        a.lw(8,19,12);a.sw(8,23,20)
        a.branch(4,2,0,'failure');a.li(9,module.ARENA_BYTES);a.r(0x2B,9,9,8);a.branch(5,9,0,'failure')
    a.addiu(2,0,5);a.jump('done');a.label('failure');a.addiu(2,0,140)
    a.label('done')
    for off in range(0,156,4):a.lw(8,29,0x70+off);a.sw(8,18,off)
    for i,r in enumerate(regs):a.i(55,r,29,i*8)
    a.addiu(29,29,0x120);a.jr();data=a.finish();assert len(data)<0x3000;return data


def code(snap,cfg,partner):
    a=Assembler(commit.ENTRY);a.addiu(29,29,-0x90)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(63,r,29,i*8)
    a.li(16,commit.CONTROL);a.lw(8,16);a.branch(4,8,0,'done');a.lw(8,16,4);a.branch(5,8,0,'done')
    for p,v in dict(cfg['guards']+partner['guards']).items():
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error110')
    a.addiu(8,0,1);a.sw(8,16,4)
    for i,row in enumerate(snap['rows']):
        a.li(8,row['row']);a.li(9,commit.DATA+i*164)
        for off in range(0,120,4):a.lw(10,9,off);a.sw(10,8,off)
        a.li(8,row['actor']);a.li(9,row['slot']);a.sw(9,8,0x994)
    # Leader reconstruction runs under idle while the native hold excludes all
    # actor dispatch. Both private AI contexts refresh only after FX exist.
    a.li(8,snap['source']['actor']);a.addiu(9,0,11);a.sw(9,8,2376)
    for off,val in ((0x12D0,snap['target']['character']),(0x12D4,snap['target']['costume']),(0x12E0,int(snap['target']['damaged']))):
        a.li(9,val);a.sw(9,8,off)
    a.li(8,commit.OWNERS[0]+0xF000);a.addiu(9,0,1);a.sw(9,8);a.call(commit.OWNERS[0])
    a.li(8,commit.OWNERS[0]+0xF004);a.lw(8,8);a.addiu(9,0,5);a.branch(5,8,9,'error120')
    a.call(PARTNER);a.addiu(8,0,5);a.branch(5,2,8,'error121')
    for i in range(2):a.call(commit.OWNERS[i]+0x4000);a.addiu(8,0,5);a.branch(5,2,8,'error130')
    for i,row in enumerate(snap['rows']):
        a.li(8,row['actor']);a.li(9,row['controller']);a.sw(9,8,4)
        a.li(9,row['cpu'] if row['health'] else 0);a.sw(9,8,0x1278)
    p=snap['partner']
    # These are transient decoded inputs, not controller preferences. Replaying
    # the pre-fusion R3 request immediately transforms the restored partner.
    for i,row in enumerate(snap['rows']):
        a.li(8,row['actor'])
        for off in (0x127C,0x1280,0x1284,0x1288,0x128C):a.sw(0,8,off)
        # The consumed actor skipped its decoder for the entire fusion. Its
        # last R3 down can otherwise become a NEW short release on re-entry.
        # Clear native1D4370/1D4A70 history, preserving the user's mapping at
        # 1400..1523. Native1D3C40 has four 32-byte age arrays per bank.
        for off in (1392,1524,1528,2368,2372,*range(1852,1884,4)):
            a.sw(0,8,off)
        a.li(9,0x7F7F);a.i(41,9,8,1396)
        for bank in (1532,1692,1920,2080):
            a.addiu(10,8,bank);a.addiu(11,10,32)
            a.label(f'held_{i}_{bank}');a.sw(0,10);a.addiu(10,10,4);a.branch(5,10,11,f'held_{i}_{bank}')
            a.li(9,0x64646464);a.addiu(11,10,96)
            a.label(f'age_{i}_{bank}');a.sw(9,10);a.addiu(10,10,4);a.branch(5,10,11,f'age_{i}_{bank}')
        # Native1CD9C8 resets the separate buffered command bitset too. The
        # consumed partner never ran its normal per-frame input cleanup.
        a.addiu(9,0,-1);a.sw(9,8,0x1294)
        # Discard the queued form/fusion request, as native1E1080 does.
        for off in (0x12CC,0x12E4,0x12E8,0x12EC,0x12F0,0x12F8):a.sw(9,8,off)
        for off in (0x12D8,0x12DC,0x12F4):a.sw(0,8,off)
        original=bytes.fromhex(row['data_hex'])
        for destination,source in ((0x12D0,0),(0x12D4,4),(0x12E0,96)):
            a.li(9,struct.unpack_from('<I',original,source)[0]);a.sw(9,8,destination)
    # At a one-HP expiry the proportional split can leave the partner dead.
    # Restore its visible corpse too, so ordinary spectating/revival still work.
    a.li(8,p['model']);a.addiu(9,0,1);a.sw(9,8,8)
    if not snap['rows'][1]['health']:
        a.li(8,p['actor']);a.addiu(9,0,216);a.sw(9,8,2376)
    a.li(8,timer.start.CONTROL+0x40+4*p['physical']);a.li(9,snap['rows'][1]['cpu'] if snap['rows'][1]['health'] else 0);a.sw(9,8)
    a.li(8,timer.feed.CONTROL+0x40+4*p['physical']);a.addiu(9,0,int(snap['rows'][1]['health']==0));a.sw(9,8)
    a.li(8,timer.fusion.requests.RECORDS+(p['physical']-2)*64);a.sw(0,8,4);a.sw(0,8,52)
    for pword in (timer.part.CONSUMED,timer.part.CONTROL+20):
        a.li(8,pword);a.lw(9,8);a.li(10,0xFFFFFFFF^(1<<p['physical']));a.r(0x24,9,9,10);a.sw(9,8)
    restore_views(a,snap)
    a.sw(2,29,0x80)
    a.li(8,timer.policy.CONTROL);a.lw(9,8);a.li(10,timer.policy.MAGIC);a.branch(5,9,10,'publish')
    a.lw(9,8,24);a.addiu(10,0,snap['side']);a.branch(5,9,10,'publish')
    a.addiu(9,0,-1);a.sw(9,8,24);a.sw(9,8,28);a.sw(0,8,64)
    # Co-op's shared view publishes the leader into both successor seats.
    # Restore the actual two human seats before the next camera/HUD pass.
    a.lw(9,29,0x80);a.branch(5,9,0,'publish')
    a.lw(9,8,12);a.addiu(10,0,timer.policy.COOP);a.branch(5,9,10,'publish')
    for side,physical in ((0,snap['side']),(1,p['physical'])):
        a.li(8,camera.SUCCESSOR_CONTROL+8+4*side);a.addiu(9,0,physical);a.sw(9,8)
        a.li(8,spectator.CONTROL+spectator.FIELDS['lock']+4*side);a.sw(0,8)
    # Keep receipt3 through retirement: FRAME dispatches held jobs for that
    # status. The host publishes receipt5 together with owned-code cleanup.
    a.label('publish');a.addiu(9,0,5);a.sw(9,16,4);a.jump('done')
    for n in (110,120,121,130):a.label(f'error{n}');a.addiu(8,0,n);a.sw(8,16,4);a.jump('done')
    a.label('done');a.lw(2,16,4)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x90);a.jr();data=a.finish();assert len(data)<0xF000;return data


def build_memory(ram,snap,receipt):
    import giant_options
    require(not any(ram[commit.ENTRY:commit.END]),'Defusion commit workspace occupied')
    for p,n in ((A(0x1135F0),0x70),(A(0x249BD8),0x70),(A(0x249000),0x58),(A(0x1C0058),0xD0),
                (A(0x1C0538),0x570),(A(0x1ADA80),0xB0),(A(0x1AD6A8),0x80),(A(0x1A71B8),0x40),
                (A(0x249B58),0x58),(A(0x249910),0xA0),(A(0x1D70E8),0xB0),
                (A(0x24E2B0),0x148),(A(0x24E3F8),0xB0)):
        require(bytes(ram[p:p+n])==giant_options.native_helper(ram,p,n,body.NATIVE),f'Native defusion helper changed:{p:08X}')
    snap=copy.deepcopy(snap)
    # Native airborne idle (15) is as safe as grounded idle while held. The
    # generic Body Change builder demands action11, so validate using a view
    # with that one scalar normalized, then retain the real15 preflight guard.
    owner=snap['source']['actor'];action=u(ram,owner+2376)
    require(action in (11,15),'Defusion leader is still busy')
    def idle_world(view,snapshot_,physical):
        world=body_world(view,snapshot_,physical);world['owner_action']=11;return world
    facade=SimpleNamespace(**dict(vars(resources),body_world=idle_world))
    cfg=timer.core.rebound(commit.configuration,resources=facade)(ram,snap,receipt,0)
    cfg['guards']=[(p,action if p==owner+2376 else v) for p,v in cfg['guards']]
    # Rebuilding changes the skeleton's local pivot. Preserve the current
    # fusion footprint, not the retained partner's pre-fusion position. The
    # partner uses the nearby position verified by the held geometry job.
    model=snap['source']['model']
    root=tuple(u(ram,model+2416+4*j) for j in range(4))
    require(all(math.isfinite(v) for v in struct.unpack('<4f',struct.pack('<4I',*root))),
            'Invalid defusion world position')
    cfg['guards'] += [(model+2416+4*j,v) for j,v in enumerate(root)]
    partner_root=tuple(snap.get('partner_root_words',root))
    require(len(partner_root)==4 and all(math.isfinite(v)for v in struct.unpack('<4f',struct.pack('<4I',*partner_root))),
            'Invalid verified partner position')
    cfg['reanchor_entry']=commit.OWNERS[0]+PLACEMENT_OFF
    cfg['selected_row']=snap['rows'][0]['row'];partner=partner_plan(ram,snap)
    control=bytearray(256);struct.pack_into('<I',control,8,snap['world']['manager'])
    pieces=[(commit.ENTRY,code(snap,cfg,partner)),(commit.CONTROL,bytes(control)),
            (commit.DATA,b''.join(bytes.fromhex(row['data_hex']) for row in snap['rows']))]
    for index,physical in enumerate((snap['side'],snap['partner']['physical'])):
        base=commit.OWNERS[index];values=dict(ENTRY=base,CACHE=base+0x3000,REFRESH=base+commit.REFRESH_OFF,
                                          AI=base+0x4000,CONTROL=base+0xF000,AI_META=base+0xF200)
        cache,refresh=timer.core.rebound(reload.actor_initializers,**values)(body.NATIVE)
        pieces += [(base+0x3000,cache),(base+commit.REFRESH_OFF,refresh),
                   (base+0x4000,timer.core.rebound(reload.ai_code,**values)(physical)),(base+0xF000,bytes(0x300))]
        body_owner=snap['source'] if index==0 else snap['partner']
        destination=root if index==0 else partner_root
        pieces += [(base+commit.ANCHOR_OFF,commit.anchor_code(base+commit.ANCHOR_OFF,body_owner['actor'],body_owner['model'],destination)),
                   (base+PLACEMENT_OFF,placement_code(base,body_owner['actor'],body_owner['model']))]
        pieces.append((base,timer.core.rebound(reload.payload,**values)(dict(cfg,guards=[])) if index==0 else partner_code(partner)))
    if cfg['adoption']:
        pieces.append((commit.OWNERS[0]+0x5000,commit.adoption_code(cfg['adoption'],commit.OWNERS[0]+0x5000)))
    for offset,g in ((0xF400,cfg),(0xF440,cfg['generic'])):
        if g:
            record=bytearray(64);struct.pack_into('<6I',record,0,cfg['world']['actor'],cfg['world']['model_id'],cfg['world']['model'],g['arena'],g['root'],0)
            pieces.append((commit.OWNERS[0]+offset,bytes(record)))
    return resources.parts_manifest(ram,pieces,entry=commit.ENTRY,control=commit.CONTROL,
                                   configurations=[cfg],rows=snap['rows'],snapshot=dict(snap,originals=[r.hex() for r in snap['originals']]),
                                   partner_plan=dict(partner,specs=[{k:v for k,v in spec.items() if k!='module'} for spec in partner['specs']]),
                                   status='HELD ATOMIC DEFUSION')
