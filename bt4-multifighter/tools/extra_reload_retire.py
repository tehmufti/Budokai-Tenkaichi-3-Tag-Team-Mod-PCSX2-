"""Retire only an exact superseded bundle recorded by the current Worker.

Original selected resources and the staging allocations backing native free
pool nodes remain retained. Registered model ownership, private AI references,
the native upload queue and hardware DMA must be clear before native freeing.
This dormant service never acquires/releases the caller's quiet hold.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

import extra_reload_preload as prior
import extra_reload_quiet as quiet
import extra_reload_commit as commit
import effect_texture_guard as texture
from prototype import Assembler,ROOT,elf_reader

ENTRY,CONTROL,END=0x07670000,0x0767F000,0x07680000
NATIVE=elf_reader(elf_path(ROOT))[2]
require=commit.require
SAVED=tuple(range(1,29))+(30,31)
DMA=(0x10009000,0x1000A000) # VIF1 and GIF CHCR; STR bit8.
# The DMA spin is bounded by elapsed emulated time, read from CP0 Count, which
# advances with the 294.912 MHz EE clock whatever EECycleRate is. The previous
# bound of 65,536 iterations cost 22 cycles each at 100% EE in PCSX2's block
# accounting (sample block 157/8 -> 19, counter block 29/8 -> 3), so this is
# that same window: 1,441,792 cycles, 4.89 ms, 0.29 NTSC field. Counting
# iterations shrank it to 77%, 55% and 32% at EECycleRate +1, +2 and +3.
DMA_WINDOW=65536*22
# One lui loads it, and below 2**31 the EE's sign-extended elapsed time
# compares the same as the unsigned 32-bit difference.
assert DMA_WINDOW&0xFFFF==0 and 0<DMA_WINDOW<1<<31


def receipt(ram,physical):
    """Capture a completed IO/commit bundle, never an initial selected bundle."""
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    w=prior.capture(ram,physical);resource=w['old_resource']
    require(u(commit.CONTROL+4)==5 and u(commit.AI_META)==5 and u(commit.CONTROL+36)==1,
            'Only a completed owned commit can issue a resource receipt')
    require(u(commit.stage.io.CONTROL+4)==5 and u(commit.stage.io.CONTROL+32)==resource and
            u(commit.stage.io.CONTROL+20)==physical,'Completed IO does not own this resource')
    return dict(physical=physical,manager=w['manager'],resource=resource,handle=u(resource+52),
                buffers=[dict(pointer=u(resource+16*i),size=u(resource+16*i+4),file=u(resource+16*i+8)) for i in range(3)],
                group=u(u(w['model']+64)+40))


def capture(ram,owned,*,body_context=None):
    require(len(ram)==0x8000000,'Requires128MiB EE RAM');u=lambda p:struct.unpack_from('<I',ram,p)[0]
    w=prior.capture(ram,owned['physical'],allow_leaders=body_context is not None)
    if body_context is None:quiet.validate(ram,w,True)
    else:
        for p,v in body_context['quiet_checks']:require(u(p)==v,'Body retirement hold changed')
    require(w['manager']==owned['manager'],'Retirement receipt belongs to another match')
    resource,handle,group=owned['resource'],owned['handle'],owned['group']
    preserve_texture=bool(body_context and body_context.get('preserve_texture',False))
    require(2<=handle<14 and resource==w['registry']+(handle-2)*56 and
            u(resource+48)==3 and u(resource+52)==handle,'Owned resource record changed')
    require(resource!=w['old_resource'] and 0<=group<15,'Cannot retire the current resource')
    ranges=[];guards=(quiet.checks(w,True) if body_context is None else body_context['quiet_checks'])+[(prior.core.ACTORS,w['manager']),(prior.core.MODE,1),
        (prior.core.MODE+4,w['count']),(prior.core.MODE+8,w['manager']),(prior.core.MODE+12,w['count']),
        (prior.core.PAIR+4,0),(prior.REGISTRY_GLOBAL,w['registry']-prior.REGISTRY_OFFSET),
        (resource+48,3),(resource+52,handle),(w['model']+20,w['old_resource'])]
    guards += ([(commit.CONTROL+4,5),(commit.AI_META,5),(commit.CONTROL+36,1)] if body_context is None else body_context['commit_guards'])
    for i,b in enumerate(owned['buffers']):
        p,n=b['pointer'],b['size'];require((0x100000 if body_context is not None else 0x2000000)<=p<=len(ram)-n and 0<n<=0x800000,'Invalid owned heap buffer')
        for off,val in ((0,p),(4,n),(8,b['file'])):
            require(u(resource+i*16+off)==val,'Owned buffer identity changed');guards.append((resource+i*16+off,val))
        ranges.append((p,n))
    require(len(ranges)==3 and all(p+n<=q or q+m<=p for i,(p,n) in enumerate(ranges) for q,m in ranges[i+1:]),
            'Owned buffers must be independent')
    inside=lambda v:any(p<=v<p+n for p,n in ranges)
    # Native1D3D48/1D3DF8 own two8-word button-mask rings and16 packed
    # analog bytes. Their bit patterns can look exactly like EE pointers.
    # Every other aligned actor word is conservatively checked, including the
    # three cached attack-script pointers at5608/5612/5616.
    for actor in w['actors']:
        require(not any(inside(u(actor+off)) for off in range(0,0x1600,4) if not 0x8C0<=off<0x910),
                'A captured actor retains an old resource pointer')
    # Every registered model must have released both bundle and texture group.
    vacant=[];texture_owner=False
    for mid in range(12):
        model=u(prior.core.MODELS+4*mid)
        if not model:vacant.append(mid);continue
        require(0x100000<=model<=len(ram)-0x1670,'Invalid native model table')
        if u(model+4)!=1:vacant.append(mid);continue
        guards += [(prior.core.MODELS+4*mid,model),(model+4,1)]
        geometry=u(model+64)
        require(0x100000<=geometry<=len(ram)-112 and u(model+20)!=resource and
                (u(geometry+40)!=group or preserve_texture),
                'A registered model still owns the retired bundle or texture group')
        texture_owner |= u(geometry+40)==group
        require(not any(inside(u(model+off)) for off in range(0,0x1670,4)),
                'A registered model retains a pointer into the old bundle')
        guards += [(model+20,u(model+20)),(model+64,geometry),(geometry+40,u(geometry+40))]
    require(not preserve_texture or texture_owner,'A retained texture group needs a verified current model owner')
    require(u(commit.fresh.CONTROL)==5 and u(prior.core.PAIR+4)==0,'Private AI must be ready and unaliased')
    owner=commit.fresh.SHADOWS[w['physical']]+0x10+(w['physical']&1)*0x520
    dataset=u(w['model']+2356)
    require(u(owner)==w['physical']&1 and u(owner+24)==dataset and not u(owner+36)&1,'New owner AI is not rebound')
    guards += [(owner,u(owner)),(owner+24,dataset),(owner+36,u(owner+36))]
    copies=[]
    for physical in range(w['count']):
        own=commit.fresh.SHADOWS[physical]+0x10+(physical&1)*0x520
        # These two words are native64-bit condition bits, not addresses.
        # Guard their native producer/consumer before allowing the exception.
        require(not any(inside(u(own+off)) for off in range(0,0x520,4) if off not in (0x2C0,0x2C4)),
                'A private own context retains old resource pointers')
        enemy=commit.fresh.SHADOWS[physical]+0x10+(1-(physical&1))*0x520
        refs=[off for off in range(0,0x520,4) if off not in (0x2C0,0x2C4) and inside(u(enemy+off))]
        if refs:
            require(physical&1 != w['physical']&1 and inside(u(enemy+24)) and u(enemy)==w['physical']&1,
                    'Unrecognized stale private enemy context')
            copies.append((enemy,bytes(ram[enemy:enemy+0x520])))
    queue=u(texture.QUEUE);require(0x100000<=queue<=len(ram)-2060,'Invalid texture upload queue')
    guards += [(texture.QUEUE,queue)]
    for p,n in ((A(0x24B8A0),0x70),(A(0x24B290),0x70),(A(0x24B400),0x58),(A(0x249058),0x40),
                (A(0x1B6E50),0x80),(A(0x1BFF70),0x180),(A(0x1D3D48),0xB0),(A(0x1D3DF8),0xB0)):
        import summon_resources
        require(summon_resources.native_or_hook(ram,p,n,NATIVE),f'Native retirement helper changed:{p:08X}')
    result=dict(world=w,owned=owned,guards=guards,ranges=ranges,queue=queue,owner=owner,copies=copies,vacant=vacant)
    if preserve_texture:result['preserve_texture']=True
    return result


def payload(c):
    a=Assembler(ENTRY);a.addiu(29,29,-0x150)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)
    for i in range(12):a.i(57,20+i,29,0x100+4*i)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,4);a.addiu(9,0,5);a.branch(4,8,9,'done');a.i(11,9,8,100);a.branch(4,9,0,'done')
    for p,v in c['guards']:
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error110')
    # Native model-table rebuilding can remove an already-retired staging
    # pointer between packet installation and invocation. Both null and an
    # inactive model are vacant; any newly active model rejects retirement.
    for mid in c['vacant']:
        a.li(8,prior.core.MODELS+4*mid);a.lw(8,8);a.branch(4,8,0,f'vacant{mid}')
        a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'error110')
        a.li(9,0x8000000-0x1670);a.r(0x2B,9,9,8);a.branch(5,9,0,'error110')
        a.i(12,9,8,3);a.branch(5,9,0,'error110');a.lw(8,8,4)
        a.addiu(9,0,1);a.branch(4,8,9,'error110');a.label(f'vacant{mid}')
    # Multi-view rendering can keep VIF busy at this dispatch point. Cleanup
    # is optional after a verified commit: retain the exact receipt instead of
    # freezing the restored fighters waiting for the renderer to become idle.
    # No destructor or reference rewrite has occurred on this deferred path.
    a.lw(8,16,28);a.addiu(8,8,1);a.sw(8,16,28)
    a.i(11,9,8,9 if c.get('defer_busy') else 1801)
    a.branch(4,9,0,'defer' if c.get('defer_busy') else 'error120')
    a.lw(8,16,4);a.branch(5,8,0,'poll')
    a.li(8,quiet.native.CONTROL+40);a.lw(8,8);a.sw(8,16,24);a.addiu(8,0,1);a.sw(8,16,4);a.jump('done')
    a.label('poll');a.li(8,quiet.native.CONTROL+40);a.lw(8,8);a.lw(9,16,24);a.r(0x23,8,8,9)
    a.i(11,9,8,2);a.branch(5,9,0,'done')
    a.li(8,c['queue']);a.lw(8,8,2048);a.branch(5,8,0,'done')
    # Dispatch occurs at the same in-flight DMA phase each frame. A single
    # sample per invocation can therefore starve forever. Like native100EC0
    # and293740, let DMA progress within this invocation, with a strict bound.
    # Never reset a channel or free while either channel remains active.
    # The bound is elapsed CP0 Count (t4 = start, t5 = DMA_WINDOW), so an EE
    # overclock waits the same emulated time instead of fewer cycles. Elapsed
    # time is a wrap-safe 32-bit difference; a Count that ever moved backwards
    # only ends the spin early, and the next dispatch samples again.
    a.emit(0x40000000|(12<<16)|(9<<11))  # mfc0 t4, Count
    a.i(15,13,0,DMA_WINDOW>>16);a.label('dma_wait');a.move(11,0)
    for index,p in enumerate(DMA):
        a.li(8,p);a.lw(8,8);a.sw(8,16,40+4*index)
        a.i(12,8,8,0x100);a.r(0x25,11,11,8)
    a.branch(4,11,0,'dma_clear')
    a.emit(0x40000000|(8<<16)|(9<<11))   # mfc0 t0, Count
    a.r(0x23,8,8,12);a.r(0x2B,8,8,13);a.branch(5,8,0,'dma_wait');a.jump('done')
    a.label('dma_clear')
    # Refresh stale enemy halves before release. The current scheduler normally
    # makes this exact copy before any private manager is published.
    for index,(destination,before) in enumerate(c['copies']):
        a.li(8,destination);a.li(9,c['owner']);a.li(10,destination+0x520)
        a.label(f'copy{index}');a.lw(11,9);a.sw(11,8);a.addiu(8,8,4);a.addiu(9,9,4)
        a.branch(5,8,10,f'copy{index}')
    a.li(4,c['owned']['handle']);a.call(A(0x24B8A0))
    a.li(8,c['owned']['resource'])
    for off in (0,4,16,20,32,36,48):a.lw(9,8,off);a.branch(5,9,0,'error130')
    if not c.get('preserve_texture'):
        a.li(4,c['owned']['group']);a.call(A(0x249058))
    a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    if c.get('defer_busy'):
        a.label('defer');a.addiu(8,0,1);a.sw(8,16,32)
        a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    for name,status in (('error110',110),('error120',120),('error130',130)):
        a.label(name);a.addiu(8,0,status);a.sw(8,16,4);a.jump('done')
    a.label('done')
    for i in range(12):a.i(49,20+i,29,0x100+4*i)
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x150);a.jr();data=a.finish();assert len(data)<CONTROL-ENTRY;return data


def build_memory(ram,owned,source='<worker-owned>'):
    c=capture(ram,owned);require(not any(ram[ENTRY:END]),'Retirement reservation occupied')
    control=bytearray(0x100);struct.pack_into('<4I',control,8,c['world']['manager'],c['world']['actor'],owned['resource'],owned['handle'])
    parts=[(ENTRY,payload(c)),(CONTROL,bytes(control))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),entry=ENTRY,control=CONTROL,
                configuration={k:v for k,v in c.items() if k!='copies'},
                blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in parts])
