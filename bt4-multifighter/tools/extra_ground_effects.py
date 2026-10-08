"""Independent native dust, auxiliary trail, and optional surface owner storage.

Install only at a held captured four/six-fighter checkpoint. This module has no
emulator access. Native constructors, particles, updates, and resource releases
remain in use; fixed two-owner indexing is routed to separate captured tables.
"""
from native_map import A, CRC, GPO, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
import aux_effect_bounds as aux
import ground_effect_bounds as ground
import extra_charge_aura as ordinary
from camera_snapshot import read_ram
from prototype import Assembler, ROOT, elf_reader
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy

CODE, CONTROL, RECORDS = 0x07700000, 0x07703C00, 0x07703D00
WRAPPERS, COPIES, PRED = 0x07704000, 0x07705000, 0x07706000
TAILS, FREE, CLEANUP, TAG = 0x07706400, 0x07707000, 0x07708000, 0x07708400
SURFACE_HEART, SURFACE_COPY, SURFACE_TAIL = 0x07708800, 0x07709000, 0x07709A00
SURFACE_FREE = 0x07709C00
DUST_BASE, AUX_BASE = 0x07710000, 0x07720000
DUST_TABLE, AUX_TABLE, SURFACE_TABLE = DUST_BASE+25392, AUX_BASE+800, 0x07720400
DUST_NODES, DUST_BODIES = 0x07721000, 0x07722000
AUX_NODES, AUX_BODIES = 0x07724000, 0x07725000
DUST_PARTICLES = 0x07730000
END = 0x07780000
# Dust bodies past the particles, for builds whose appended nodes no longer fit
# below AUX_NODES (224-byte bodies, 64 nodes end at 0x07753800).
WIDE_DUST_BODIES = 0x07750000


def dust_layout():
    """(appended nodes, particles per kind, body base) for the build being emitted.

    Native provisioning is 8 dust nodes and 32 particles of each kind per owner
    (16 nodes and 64+63 particles for two). Every extra gets the same share, so
    the pool never runs dry before the native two-fighter one would. Three-a-
    side builds carry four extras' worth with the bodies at DUST_BODIES.
    """
    extras=policy.emitted_actors()-2
    bodies=DUST_BODIES if extras<=4 else WIDE_DUST_BODIES
    return 8*extras,32*extras,bodies


for _extras in (4,policy.MAX_ACTORS-2):
    assert DUST_NODES+8*_extras*64<=AUX_NODES,'Appended dust nodes overrun the auxiliary nodes'
    assert DUST_PARTICLES+2*32*_extras*192<=WIDE_DUST_BODIES,'Dust particles overrun the dust bodies'
assert WIDE_DUST_BODIES+8*(policy.MAX_ACTORS-2)*224<=END,'Dust bodies overrun the ground reservation'
GLOBALS = (A(0x2FEAA0), A(0x2FEA2C), A(0x2FF1A8))
POOLS = (A(0x2FEA9C), A(0x2FEA30))
ENTRIES = (A(0x196F88), A(0x197148), A(0x16B418), A(0x16B4A0), A(0x140358))
LENGTHS = (0x1C0, 0x1D0, 0x88, 0x40, 0xB0)
FAMILY = (0, 0, 1, 1, 2)
OLD = (ground.BASE, ground.BASE+0x200, aux.WRAPPERS, aux.WRAPPERS+0x100, ground.BASE+0x400)
core, require = ordinary.core, ordinary.require
NATIVE = elf_reader(elf_path(ROOT))[2]


def save(a):
    a.addiu(29,29,-0x150)
    for i,r in enumerate(ordinary.SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0x100+i*4)


def restore(a):
    for i in range(12):a.i(49,20+i,29,0x100+i*4)
    for i,r in enumerate(ordinary.SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x150)


def captured(a, fail):
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(5,9,10,fail)
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,fail)


def predicate():
    """a0 actual model, a1 family; v0=1 owned,2 rejected,0 old world."""
    a=Assembler(PRED);captured(a,'old')
    a.i(11,9,5,3);a.branch(4,9,0,'reject')
    a.r(0,9,0,5,2);a.r(0x21,8,8,9);a.lw(10,8,20)
    a.li(8,CONTROL+0x80);a.r(0x21,8,8,9);a.lw(8,8);a.lw(8,8)
    # A manager created after this capture is not silently treated as expanded.
    a.branch(5,8,10,'reject');a.branch(4,8,0,'reject')
    a.li(8,CONTROL);a.lw(10,8,8);a.li(9,RECORDS)
    a.label('scan');a.lw(11,9,4);a.branch(4,11,4,'found')
    a.addiu(9,9,12);a.addiu(10,10,-1);a.branch(5,10,0,'scan');a.jump('reject')
    a.label('found');a.lw(8,9);a.lw(8,8,12);a.branch(5,8,4,'reject')
    a.lw(10,9,8);a.r(0,11,0,4,2);a.li(8,core.MODELS);a.r(0x21,8,8,11)
    a.lw(8,8);a.branch(5,8,10,'reject');a.lw(8,10,16);a.branch(5,8,4,'reject')
    a.addiu(2,0,1);a.jr()
    a.label('reject');a.addiu(2,0,2);a.jr()
    a.label('old');a.move(2,0);a.jr()
    b=a.finish();assert len(b)<0x400;return b


def command(index):
    a=Assembler(WRAPPERS+index*0x200)
    saved=(4,5,8,9,10,11,31)
    a.addiu(29,29,-0x40)
    for i,r in enumerate(saved):a.i(63,r,29,i*8)
    def undo():
        for i,r in enumerate(saved):a.i(55,r,29,i*8)
        a.addiu(29,29,0x40)
    if index==2:
        captured(a,'old')
        a.li(8,0x100000);a.r(0x2B,8,4,8);a.branch(5,8,0,'deny')
        a.li(8,0x8000000-12);a.r(0x2B,8,8,4);a.branch(5,8,0,'deny')
        # The native common575 bundle has one800-byte descriptor, kind0.
        a.lw(8,4,4);a.branch(5,8,0,'deny');a.lw(4,4)
    a.addiu(5,0,FAMILY[index]);a.call(PRED)
    a.branch(4,2,0,'old');a.addiu(8,0,1);a.branch(5,2,8,'deny')
    undo();a.jump(COPIES+index*0x200)
    a.label('old');undo();a.jump(OLD[index])
    a.label('deny');undo();a.move(2,0);a.jr()
    b=a.finish();assert len(b)<=0x200;return b


def command_copy(index):
    p=ENTRIES[index];b=bytearray(NATIVE(p,LENGTHS[index]));changes=[]
    if index<4:
        off=(GPO(-22480) if index<2 else GPO(-22596))&65535
        base=DUST_BASE if index<2 else AUX_BASE
        for j in range(0,len(b),4):
            w=struct.unpack_from('<I',b,j)[0]
            if w>>26==35 and (w>>21)&31==28 and w&65535==off:
                # Each of these loads is used only to address its owner table.
                struct.pack_into('<I',b,j,(15<<26)|(w&0x1F0000)|(base>>16));changes.append(p+j)
        expect=((A(0x196F8C),A(0x1970B8),A(0x1970C4)),(A(0x19714C),A(0x19728C),A(0x197298)),
                (A(0x16B438),A(0x16B468),A(0x16B480)),(A(0x16B4A0),))[index]
        assert tuple(changes)==expect
    if index==1:
        for p in (A(0x19718C),A(0x197294),A(0x1972A0),A(0x1972AC)):
            j=p-ENTRIES[index];w=struct.unpack_from('<I',b,j)[0];assert w&65535==8
            struct.pack_into('<I',b,j,(w&0xFFFF0000)|48)
    # Internal branch displacements remain unchanged; no internal absolute J.
    for j in range(0,len(b),4):
        w=struct.unpack_from('<I',b,j)[0]
        if w>>26 in (2,3):assert not ENTRIES[index]<=((w&0x3FFFFFF)<<2)<ENTRIES[index]+len(b)
    return bytes(b)


def clear_tail(index):
    """Run after native payload release; retain original v0/v1 and32-byte frame."""
    a=Assembler(TAILS+index*0x200);a.addiu(29,29,-0x30)
    for i,r in enumerate((2,3,8,9,10,11)):a.i(63,r,29,i*8)
    # Native module destruction may follow withdrawal of the actor manager.
    # Its own still-captured family and expanded table remain authoritative.
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(5,9,10,'native')
    family=0 if index<2 else 1
    a.li(8,GLOBALS[family]);a.lw(8,8);a.li(9,CONTROL);a.lw(9,9,20+family*4)
    a.branch(5,8,9,'native');a.i(55,10,29,0);a.r(0x23,10,10,8)
    a.i(11,11,10,48);a.branch(4,11,0,'done');a.i(12,11,10,3);a.branch(5,11,0,'done')
    a.li(8,(DUST_TABLE+index*48) if index<2 else AUX_TABLE)
    a.r(0x21,8,8,10);a.sw(0,8);a.jump('done')
    a.label('native');a.i(55,2,29,0);a.sw(0,2,(25392,25400,800)[index])
    a.label('done')
    for i,r in enumerate((2,3,8,9,10,11)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x30);a.emit(0x03E00008);a.addiu(29,29,32)
    b=a.finish();assert len(b)<=0x200;return b


def pool_info(ram,family):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    ptr=lambda p,n:0x100000<=p<=len(ram)-n
    g=u(GLOBALS[family]);pool=u(POOLS[family]);n,body,cb=(16,224,A(0x2C4108)) if family==0 else (3,1392,A(0x2C3AF0))
    require(ptr(g,25408 if family==0 else 808) and ptr(pool,24),'Missing native ground effect manager')
    nodes,payloads=u(pool+16),u(pool+20);module=u(pool)
    require(ptr(nodes,n*64) and ptr(payloads,n*body) and ptr(module,64) and
            u(module+36)==pool and u(module+40)==cb,'Changed ground effect pool ownership')
    seen=set();tracked={};active_bodies=[];node=u(pool+4);prev=0
    while node:
        require(nodes<=node<nodes+n*64 and (node-nodes)%64==0 and node not in seen,'Bad ground active list')
        require(u(node+32)==pool and u(node+36)==0 and u(node+44)==prev and
                u(node+56)==payloads+(node-nodes)//64*body,'Bad ground payload ownership')
        require(u(node+40) in ((A(0x2C4120),A(0x2C4138),A(0x2C4150),A(0x2C4168),A(0x2C4180),A(0x2C4198)) if family==0 else (A(0x2C3B08),)),
                'Unknown ground effect callbacks')
        bodyptr=u(node+56);callback=u(node+40);active_bodies.append(bodyptr)
        if family==1 or callback in (A(0x2C4138),A(0x2C4150)):
            owner=u(bodyptr+32) if family else ram[bodyptr+56]
            row=(800+owner*4) if family else (25392+(8 if callback==A(0x2C4150) else 0)+owner*4)
            require(owner<2 and row not in tracked and u(g+row)==node,'Bad original tracked owner')
            if family:require(u(bodyptr+44)==g,'Foreign auxiliary resource descriptor')
            tracked[row]=node
        seen.add(node);prev=node;node=u(node+48)
    require(prev==u(pool+8),'Bad ground active tail');node=u(pool+12)
    while node:
        require(nodes<=node<nodes+n*64 and (node-nodes)%64==0 and node not in seen,'Bad ground free list')
        require(u(node+32)==pool and u(node+56)==payloads+(node-nodes)//64*body,'Bad ground free ownership')
        seen.add(node);node=u(node+52)
    require(len(seen)==n,'Incomplete native ground pool')
    for row in ((800,804) if family else (25392,25396,25400,25404)):
        require(u(g+row)==tracked.get(row,0),'Orphaned native ground tracker')
    if family==0:
        require(u(g+24600)==g and u(g+24604)==g+12288,'Changed native dust particle bases')
        used=set()
        for header in (g+24576,g+24588,*(b+204 for b in active_bodies)):
            p=u(header);previous=0;length=0
            while p:
                delta=p-g
                require(0<=delta<127*192 and delta%192==0 and p not in used and u(p)==previous,
                        'Invalid dust particle ownership chain')
                used.add(p);length+=1;previous=p;p=u(p+4)
            require(u(header+4)==previous and u(header+8)==length,'Invalid dust particle list metadata')
        require(len(used)==127,'Native dust particles are not fully accounted for')
    return dict(manager=g,pool=pool,nodes=nodes,bodies=payloads,count=n,stride=body)


def initialize(previous,actors,mids,models,caps,surface,oldsurface):
    a=Assembler(CODE);save(a);a.li(16,CONTROL);a.lw(8,16);a.branch(5,8,0,'done')
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'error101')
    for p,v in ((core.MODE,1),(core.MODE+4,len(actors)),(core.MODE+12,len(actors)),(core.PAIR+4,0)):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error101')
    for i,(actor,mid,model) in enumerate(zip(actors,mids,models)):
        for p,v in ((core.POINTERS+i*4,actor),(actor,i),(actor+12,mid),(core.MODELS+mid*4,model),
                    (actor+0x948,11),(actor+0x1278,0),(actor+0x127C,0),(actor+0x1280,0),(actor+0x1284,0)):
            a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error102')
    for i,c in enumerate(caps):
        for p,v in ((GLOBALS[i],c['manager']),(POOLS[i],c['pool']),(c['pool']+16,c['nodes']),(c['pool']+20,c['bodies'])):
            a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error103')
    a.li(8,GLOBALS[2]);a.lw(8,8);a.li(9,surface);a.branch(5,8,9,'error103')
    if surface:a.lw(8,8);a.li(9,oldsurface);a.branch(5,8,9,'error103')
    # All old particles and resource references are released before indexing changes.
    for i,c in enumerate(caps):
        a.li(4,c['pool']);a.call(A(0x1AD9F8))
        a.li(8,c['pool']);a.lw(9,8,4);a.lw(10,8,8);a.r(0x25,9,9,10);a.branch(5,9,0,'error104')
        for j in range(4 if i==0 else 2):
            a.li(8,c['manager']+(25392 if i==0 else 800)+j*4);a.lw(8,8);a.branch(5,8,0,'error104')
        a.li(8,c['pool']);a.lw(17,8,12);a.li(18,c['count']);a.li(19,c['nodes'])
        a.label(f'free{i}');a.r(0x23,9,17,19);a.i(11,10,9,c['count']*64);a.branch(4,10,0,'error105')
        a.i(12,10,9,63);a.branch(5,10,0,'error105');a.move(20,17);a.lw(17,17,52)
        a.addiu(18,18,-1);a.branch(5,18,0,f'free{i}');a.branch(5,17,0,'error105')
        a.sw(20,16,48+4*i)
    for kind,expected in ((0,64),(1,63)):
        a.li(8,caps[0]['manager']+24576+kind*12);a.lw(9,8,8);a.addiu(10,0,expected)
        a.branch(5,9,10,'error104')
    # No rejection paths follow publication. Native original allocations stay put.
    for i,p in enumerate((DUST_NODES,AUX_NODES)):
        a.lw(8,16,48+4*i);a.li(9,p);a.sw(9,8,52)
    per_kind=dust_layout()[1]
    for kind in range(2):
        a.li(17,DUST_PARTICLES+kind*per_kind*192);a.li(18,per_kind)
        a.label(f'particles{kind}');a.li(4,caps[0]['manager']+24576+kind*12);a.move(5,17);a.call(A(0x255978))
        a.addiu(17,17,192);a.addiu(18,18,-1);a.branch(5,18,0,f'particles{kind}')
    if surface:
        # Preserve each native row, including its active/cadence state.
        for off in range(0,24,4):a.li(8,oldsurface);a.lw(9,8,off);a.li(8,SURFACE_TABLE);a.sw(9,8,off)
        a.li(8,surface);a.li(9,SURFACE_TABLE);a.sw(9,8)
    a.li(16,CONTROL);a.addiu(8,0,5);a.sw(8,16);a.addiu(8,0,1);a.sw(8,16,16);a.jump('done')
    for n in range(101,106):a.label(f'error{n}');a.addiu(8,0,n);a.sw(8,16);a.jump('done')
    a.label('done');a.li(16,CONTROL);a.lw(8,16);a.addiu(9,0,5);a.branch(4,8,9,'restore')
    a.lw(11,16,4);a.lw(9,28,-22364);a.branch(5,11,9,'restore')
    for name,ctrl in (('start',ordinary.start_gate.CONTROL),('intro',ordinary.intro.CONTROL)):
        a.li(8,ctrl);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,f'skip_{name}')
        a.lw(9,8,8);a.branch(5,9,11,f'skip_{name}');a.sw(0,8,4);a.label(f'skip_{name}')
    a.label('restore');restore(a);a.jump(previous)
    b=a.finish();assert len(b)<CONTROL-CODE;return b


def free_wrapper(index):
    a=Assembler(FREE+index*0x400);save(a)
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(5,9,10,'done')
    a.li(8,GLOBALS[index]);a.lw(8,8);a.li(9,CONTROL);a.lw(9,9,20+4*index);a.branch(5,8,9,'done')
    a.li(8,CONTROL);a.lw(4,8,32+4*index);a.call(A(0x1AD9F8))
    a.label('done');restore(a);a.jump(FREE+index*0x400+0x200)
    return a.finish()


def cleanup():
    """Public reload helper: a0 actual model ID. No actor/model/camera writes."""
    a=Assembler(CLEANUP);save(a);a.move(16,4);a.addiu(5,0,0);a.call(PRED)
    a.addiu(8,0,1);a.branch(5,2,8,'done')
    for table in (DUST_TABLE,DUST_TABLE+48,AUX_TABLE):
        a.r(0,8,0,16,2);a.li(9,table);a.r(0x21,8,8,9);a.lw(4,8);a.branch(4,4,0,f'next{table}')
        a.call(A(0x1ADA80));a.label(f'next{table}')
    a.li(8,CONTROL);a.lw(9,8,28);a.branch(4,9,0,'done')
    a.li(10,GLOBALS[2]);a.lw(10,10);a.branch(5,9,10,'done');a.lw(10,9)
    a.li(11,SURFACE_TABLE);a.branch(5,10,11,'done')
    a.r(0,8,0,16,1);a.r(0x21,8,8,16);a.r(0,8,0,8,2);a.r(0x21,8,8,11);a.sw(0,8,4);a.sw(0,8,8)
    a.label('done');restore(a);a.jr();b=a.finish();assert len(b)<=0x400;return b


def tag_code():
    a=Assembler(TAG);save(a);a.lw(8,4,56);a.lw(4,8,32);a.move(16,4);a.addiu(5,0,1);a.call(PRED)
    a.addiu(8,0,1);a.branch(5,2,8,'done');a.li(8,CONTROL);a.lw(10,8,8);a.li(9,RECORDS)
    a.label('scan');a.lw(8,9,4);a.branch(4,8,16,'found');a.addiu(9,9,12);a.addiu(10,10,-1);a.branch(5,10,0,'scan');a.jump('done')
    a.label('found');a.lw(8,9);a.lw(8,8,8);a.addiu(9,0,0x800);a.branch(4,8,0,'write');a.addiu(9,0,0x1000)
    a.label('write');a.i(63,9,29,ordinary.SAVED.index(5)*8)
    a.label('done');restore(a);a.jump(A(0x1ADB78));b=a.finish();assert len(b)<=0x400;return b


def surface_heart():
    a=Assembler(SURFACE_HEART);save(a);captured(a,'old')
    a.li(8,CONTROL);a.lw(9,8,28);a.branch(4,9,0,'old');a.li(10,GLOBALS[2]);a.lw(10,10);a.branch(5,9,10,'old')
    a.lw(10,9);a.li(11,SURFACE_TABLE);a.branch(5,10,11,'old')
    restore(a);a.jump(SURFACE_COPY);a.label('old');restore(a);a.jump(SURFACE_TAIL);return a.finish()


def surface_free():
    # 1416A0 calls heap-free with a1=current owner table; restore the real allocation.
    a=Assembler(SURFACE_FREE);save(a)
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(5,9,10,'done')
    a.li(8,SURFACE_TABLE);a.branch(5,5,8,'done');a.li(8,CONTROL);a.lw(9,8,28)
    a.li(10,GLOBALS[2]);a.lw(10,10);a.branch(5,9,10,'done');a.lw(9,8,40)
    a.i(63,9,29,ordinary.SAVED.index(5)*8)
    a.label('done');restore(a);a.jump(A(0x1A71B8));return a.finish()


def build_memory(ram,config=None,source='<offline-held>'):
    require(len(ram)==0x8000000,'Requires128MiB RAM');u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    require(count in ACTOR_COUNTS and u(core.MODE)==1 and u(core.MODE+8)==manager and
            u(core.MODE+12)==count and not u(core.PAIR+4),'Captured four/six world required')
    actors=[];mids=[];models=[]
    for i in range(count):
        actor=u(core.POINTERS+i*4);require(0x100000<=actor<=len(ram)-0x1600,'Bad actor pointer')
        mid=u(actor+12);require(mid<12 and mid not in mids,'Bad model ID');model=u(core.MODELS+mid*4)
        require(0x100000<=model<=len(ram)-0x1670 and u(model+16)==mid and u(actor)==i,'Bad registered model')
        require(u(actor+8) in (0,1) and u(actor+0x948)==11 and
                all(u(actor+p)==0 for p in (0x1278,0x127C,0x1280,0x1284)),'All actors must be held idle')
        actors.append(actor);mids.append(mid);models.append(model)
    require(mids[:2]==[0,1],'Native leader model IDs must remain0/1')
    require(not any(ram[CODE:END]),'Ground expansion reservation occupied')
    caps=[pool_info(ram,i) for i in range(2)]
    surface=u(GLOBALS[2]);oldsurface=0
    if surface:
        require(0x100000<=surface<=len(ram)-704,'Invalid optional surface manager');oldsurface=u(surface)
        require(0x100000<=oldsurface<=len(ram)-24,'Invalid optional surface rows')
        require(all(u(oldsurface+i*12+8) in (0,1) and (not u(oldsurface+i*12+8) or u(oldsurface+i*12)==i)
                    for i in range(2)),'Invalid optional surface owners')
    # Validate old safeguards, including the release-preserving auxiliary tail.
    for i,e in enumerate(ground.ENTRIES):
        p=ground.BASE+i*0x200;old=ground.wrapper(i,NATIVE(e,8));require(ram[p:p+len(old)]==old,'Changed ground guard')
        require(ram[e:e+8]==struct.pack('<2I',(2<<26)|(p>>2),0),'Changed ground entry')
    for i,e in enumerate(aux.ENTRIES):
        p=aux.WRAPPERS+i*0x100;old=aux.wrapper_code(i,NATIVE(e,8));require(ram[p:p+len(old)]==old,'Changed auxiliary guard')
        old=aux.predicate_code(i);require(ram[aux.PREDICATES[i]:aux.PREDICATES[i]+len(old)]==old,'Changed auxiliary predicate')
        require(ram[e:e+8]==struct.pack('<2I',(2<<26)|(p>>2),0),'Changed auxiliary entry')
    old=aux.tail_code();require(ram[aux.TAIL:aux.TAIL+len(old)]==old and
        ram[A(0x16B15C):A(0x16B164)]==struct.pack('<2I',(2<<26)|(aux.TAIL>>2),0),'Changed auxiliary release tail')
    previous=(u(ordinary.HOOK)&0x3FFFFFF)<<2
    require(u(ordinary.HOOK)>>26==2 and not u(ordinary.HOOK+4) and 0x07000000<=previous<0x08000000,'Missing held frame chain')
    ctl=bytearray(0x100);struct.pack_into('<11I',ctl,0,0,manager,count,previous,0,caps[0]['manager'],caps[1]['manager'],surface,
                                        caps[0]['pool'],caps[1]['pool'],oldsurface)
    struct.pack_into('<3I',ctl,0x80,*GLOBALS)
    pieces=[(CONTROL,bytes(ctl)),(RECORDS,b''.join(struct.pack('<3I',*r) for r in zip(actors,mids,models))),
            (CODE,initialize(previous,actors,mids,models,caps,surface,oldsurface)),(PRED,predicate()),(CLEANUP,cleanup()),(TAG,tag_code())]
    for i,e in enumerate(ENTRIES):
        require(ram[e+8:e+LENGTHS[i]]==NATIVE(e+8,LENGTHS[i]-8),'Changed native cosmetic command body')
        pieces.extend(((WRAPPERS+i*0x200,command(i)),(COPIES+i*0x200,command_copy(i)),
                       (e,struct.pack('<2I',(2<<26)|((WRAPPERS+i*0x200)>>2),0))))
    for i,(p,expected) in enumerate(((A(0x1980BC),NATIVE(A(0x1980BC),8)),(A(0x198594),NATIVE(A(0x198594),8)),
                                   (A(0x16B15C),struct.pack('<2I',(2<<26)|(aux.TAIL>>2),0)))):
        require(ram[p:p+8]==expected,'Changed dust/aux native clear');pieces.extend(((TAILS+i*0x200,clear_tail(i)),(p,struct.pack('<2I',(2<<26)|((TAILS+i*0x200)>>2),0))))
    dust_nodes,_,dust_bodies=dust_layout()
    for i,(c,n,nodebase,bodybase) in enumerate(zip(caps,(dust_nodes,9),(DUST_NODES,AUX_NODES),(dust_bodies,AUX_BODIES))):
        nodes=bytearray(n*64)
        for j in range(n):
            struct.pack_into('<H',nodes,j*64+2,c['count']+j);struct.pack_into('<I',nodes,j*64+32,c['pool'])
            struct.pack_into('<I',nodes,j*64+52,nodebase+(j+1)*64 if j<n-1 else 0)
            struct.pack_into('<I',nodes,j*64+56,bodybase+j*c['stride'])
        pieces.append((nodebase,bytes(nodes)))
        entry=(A(0x197928),A(0x16B3C0))[i];original=NATIVE(entry,8);require(ram[entry:entry+8]==original,'Changed module free')
        pieces.extend(((FREE+i*0x400,free_wrapper(i)),(FREE+i*0x400+0x200,original+struct.pack('<2I',(2<<26)|((entry+8)>>2),0)),
                       (entry,struct.pack('<2I',(2<<26)|((FREE+i*0x400)>>2),0))))
    require(ram[A(0x16B0F0):A(0x16B0F8)]==NATIVE(A(0x16B0F0),8),'Changed auxiliary ownership tag')
    pieces.append((A(0x16B0F0),struct.pack('<I',(3<<26)|(TAG>>2))))
    heart=bytearray(NATIVE(A(0x1418D8),0x99C));require(ram[A(0x1418D8):A(0x142274)]==heart,'Changed surface consumer')
    require(struct.unpack_from('<I',heart,0x68)[0]==0x24120001,'Changed surface two-row loop')
    struct.pack_into('<I',heart,0x68,0x2412000B)
    pieces.extend(((SURFACE_COPY,bytes(heart)),(SURFACE_HEART,surface_heart()),
                   (SURFACE_TAIL,NATIVE(A(0x1418D8),8)+struct.pack('<2I',(2<<26)|(A(0x1418E0)>>2),0)),
                   (A(0x1418D8),struct.pack('<2I',(2<<26)|(SURFACE_HEART>>2),0)),(SURFACE_FREE,surface_free())))
    require(ram[A(0x1416A0):A(0x1416A8)]==NATIVE(A(0x1416A0),8),'Changed surface free call')
    pieces.extend(((A(0x1416A0),struct.pack('<I',(3<<26)|(SURFACE_FREE>>2))),
                   (ordinary.HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))))
    intervals=sorted((p,p+len(b)) for p,b in pieces)
    require(all(end<=nxt for (_,end),(nxt,_) in zip(intervals,intervals[1:])),'Ground payload overlap')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,cleanup=CLEANUP,
                status='HELD NATIVE GROUND EFFECT EXPANSION; WAIT STATUS5; OFFLINE ONLY',
                actors=actors,model_ids=mids,models=models,captures=caps,surface=surface,previous_frame=previous,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in pieces],
                limitations=['Surface effects expand only when their native stage manager exists at capture; no missing stage resource is invented.',
                             'Original native particle formats and authored effects remain unchanged. Live rendering validation is required.'])


def build(source):
    return build_memory(read_ram(source),source=source)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();args.out.write_text(json.dumps(build_memory(read_ram(args.source),source=args.source),indent=2)+'\n')
