"""Native giant-aura and afterimage storage for held captured four/six teams.

No live access. Both native modules drain while their original storage exists;
only then are separate owner tables, instance bodies and particles published.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
import afterimage_bounds as bounds
import extra_charge_aura as ordinary
from camera_snapshot import read_ram
from prototype import Assembler,ROOT,elf_reader
from battle_mode_policy import ACTOR_COUNTS

CODE,FREE_G,FREE_A=0x07580000,0x07583000,0x07583400
PRED,OLD_PRED,CLEAN,OLD_CLEAN=0x07583800,0x07583A00,0x07583C00,0x07583E00
HEART,HEART_TAIL,HEART_COPY=0x07584000,0x07584200,0x07584400
ALLOC_COPY,ALLOC_WRAP,ALLOC_TAIL=0x07584500,0x07584600,0x07584700
META_REFRESH,META_CLASS=0x07584800,0x07584A00
DRAIN_G=0x07584B00
CONTROL,RECORDS=0x07584C00,0x07584D00
END=0x075D0000
core=ordinary.core
FAMILIES=(dict(name='giant',global_=A(0x2FEA18),poolglobal=A(0x2FEA1C),size=1144,tableoff=1136,
               body=3760,owner=4,callbacks=A(0x2C3A60),child=A(0x2C3A78),free=A(0x1684B0),
               wrapper=FREE_G,tail=FREE_G+0x200,table=0x07584E00,nodes=0x07585000,
               payloads=0x07585800,particles=0x07591000,stride=64,oldcapacity=200,capacity=1200),
          dict(name='afterimage',global_=A(0x2FEA38),poolglobal=A(0x2FEA44),size=1792,tableoff=1776,
               body=736,owner=76,callbacks=A(0x2C3B50),child=A(0x2C3B68),free=A(0x171318),
               wrapper=FREE_A,tail=FREE_A+0x200,table=0x07584E40,nodes=0x07585300,
               payloads=0x0758EB00,particles=0x075A4000,stride=192,oldcapacity=140,capacity=840))
require=ordinary.require


def save(a):
    a.addiu(29,29,-0x130)
    for i,r in enumerate(ordinary.SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0x100+i*4)


def restore(a):
    for i in range(12):a.i(49,20+i,29,0x100+i*4)
    for i,r in enumerate(ordinary.SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x130)


def gate(a,label,family=None):
    a.li(8,CONTROL);a.lw(9,8);a.addiu(10,0,5);a.branch(5,9,10,label)
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,label)
    if family is not None:
        f=FAMILIES[family];a.lw(9,8,0x40+family*64)
        a.li(10,f['global_']);a.lw(10,10);a.branch(5,9,10,label)
        a.lw(9,8,0x40+family*64+48);a.addiu(10,0,5);a.branch(5,9,10,label)


def predicate(cleanup=False):
    a=Assembler(CLEAN if cleanup else PRED);a.addiu(29,29,-0x20)
    for i,r in enumerate((8,9,10,11)):a.i(63,r,29,i*8)
    gate(a,'old',1)
    if cleanup:
        a.li(9,0x100000);a.r(0x2B,10,4,9);a.branch(5,10,0,'denied')
        a.li(9,0x8000000-64);a.r(0x2B,10,9,4);a.branch(5,10,0,'denied')
        a.lw(11,4,56);a.li(9,0x100000);a.r(0x2B,10,11,9);a.branch(5,10,0,'denied')
        a.li(9,0x8000000-736);a.r(0x2B,10,9,11);a.branch(5,10,0,'denied')
        a.lw(11,11,76)
    else:a.move(11,4)
    a.li(8,CONTROL);a.lw(10,8,8);a.li(9,RECORDS)
    a.label('scan');a.lw(8,9,4);a.branch(4,8,11,'found')
    a.addiu(9,9,12);a.addiu(10,10,-1);a.branch(5,10,0,'scan');a.jump('denied')
    a.label('found');a.lw(8,9);a.lw(8,8,12);a.branch(5,8,11,'denied')
    a.move(2,0);a.jump('done')
    a.label('denied');a.addiu(2,0,1)
    a.label('done')
    for i,r in enumerate((8,9,10,11)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x20);a.jr()
    a.label('old')
    for i,r in enumerate((8,9,10,11)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x20);a.jump(OLD_CLEAN if cleanup else OLD_PRED)
    b=a.finish();assert len(b)<=0x200;return b


def free_code(index):
    f=FAMILIES[index];desc=CONTROL+0x40+64*index;a=Assembler(f['wrapper']);save(a)
    a.li(16,desc);a.lw(17,16);a.li(8,f['global_']);a.lw(8,8)
    a.branch(5,17,8,'done');a.branch(4,17,0,'done')
    a.lw(8,17,f['tableoff']);a.li(9,f['table']);a.branch(5,8,9,'done')
    if not index:a.call(DRAIN_G)
    a.lw(4,16,4);a.call(A(0x1AD9F8))
    for field,offset in ((8,f['tableoff']),(12,8),(16,4),(20,12)):
        a.lw(8,16,field);a.sw(8,17,offset)
    if index:
        a.sw(0,17,16);a.lw(8,16,28);a.sw(8,17,20)
    a.addiu(8,0,90);a.sw(8,16,48)
    a.label('done');restore(a);a.jump(f['tail'])
    b=a.finish();assert len(b)<=0x200;return b


# Guest stack frames are multiples of 16 bytes (LS-2): the BIOS saves a preempted thread with sq (aligned
# down to 16) and sd HI/LO at exact offsets, so with $sp = 8 mod 16 its saved $gp became LO1 on resume.
def drain_giant_code():
    """Drain all ten native subchains before any giant instance is destroyed."""
    a=Assembler(DRAIN_G);a.addiu(29,29,-48)
    for i,r in enumerate((16,17,18,19,31)):a.i(63,r,29,i*8)
    a.li(16,FAMILIES[0]['table']);a.addiu(17,0,12)
    a.label('owner');a.lw(8,16);a.branch(4,8,0,'next')
    a.lw(18,8,56);a.addiu(18,18,16);a.addiu(19,0,10)
    a.label('group');a.move(4,18);a.call(A(0x165820))
    a.addiu(18,18,144);a.addiu(19,19,-1);a.branch(5,19,0,'group')
    a.label('next');a.addiu(16,16,4);a.addiu(17,17,-1);a.branch(5,17,0,'owner')
    for i,r in enumerate((16,17,18,19,31)):a.i(55,r,29,i*8)
    a.addiu(29,29,48);a.jr();b=a.finish();assert len(b)<=0x100;return b


def code(previous,actors,mids,models,captures):
    a=Assembler(CODE);save(a);a.li(16,CONTROL);a.lw(8,16);a.branch(5,8,0,'done')
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,'error101')
    for p,v in ((core.MODE,1),(core.MODE+4,len(actors)),(core.MODE+12,len(actors)),(core.PAIR+4,0)):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error101')
    a.li(8,core.MODE+8);a.lw(8,8);a.lw(9,16,4);a.branch(5,8,9,'error101')
    for i,(actor,mid,model) in enumerate(zip(actors,mids,models)):
        for p,v in ((core.POINTERS+i*4,actor),(actor,i),(actor+12,mid),(core.MODELS+mid*4,model),
                    (actor+0x948,11),(actor+0x1278,0),(actor+0x127C,0),(actor+0x1280,0),(actor+0x1284,0)):
            a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error102')
    for index,(f,c) in enumerate(zip(FAMILIES,captures)):
        a.li(18,CONTROL+0x40+64*index);a.lw(17,18);a.li(8,f['global_']);a.lw(8,8)
        a.branch(5,17,8,'error103')
        for off,field in ((f['tableoff'],8),(8,12),(4,16)):
            a.lw(8,17,off);a.lw(9,18,field);a.branch(5,8,9,'error103')
        a.lw(19,18,4);a.li(8,f['poolglobal']);a.lw(8,8);a.branch(5,19,8,'error103')
        # Every giant subchain is native-owned; drain all ten groups before
        # the root destructor, which only calls165820 on the first group.
        if not index:
            for body in c['active_bodies']:
                for group in range(10):a.li(4,body+16+group*144);a.call(A(0x165820))
        a.move(4,19);a.call(A(0x1AD9F8))
        for off in (4,8):a.lw(8,19,off);a.branch(5,8,0,'error104')
        a.lw(9,18,8)
        for off in (0,4):a.lw(8,9,off);a.branch(5,8,0,'error104')
        if index:a.lw(8,17,16);a.branch(5,8,0,'error104')
        a.lw(20,19,12);a.lw(21,18,32);a.branch(4,20,21,f'first{index}')
        a.addiu(8,21,64);a.branch(5,20,8,'error105')
        a.label(f'first{index}');a.lw(22,20,52);a.branch(4,22,20,'error105')
        a.branch(4,22,21,f'second{index}');a.addiu(8,21,64);a.branch(5,22,8,'error105')
        a.label(f'second{index}');a.lw(8,22,52);a.branch(5,8,0,'error105')
        # Draining finished; preserve native recycled history before switching.
        a.lw(8,17,12);a.sw(8,18,20)
        if index:a.lw(8,17,20);a.sw(8,18,28)
        for off,value in ((f['tableoff'],f['table']),(8,f['particles']),(4,f['capacity']),(12,0)):
            a.li(8,value);a.sw(8,17,off)
        if index:a.sw(0,17,16);a.sw(0,17,20)
        a.li(8,f['nodes']);a.sw(8,22,52);a.addiu(8,0,5);a.sw(8,18,48)
    a.addiu(8,0,5);a.sw(8,16);a.lw(8,16,12);a.addiu(8,8,1);a.sw(8,16,12);a.jump('done')
    for err in (101,102,103,104,105):
        a.label(f'error{err}');a.addiu(8,0,err);a.sw(8,16);a.jump('done')
    a.label('done');a.li(16,CONTROL);a.lw(8,16);a.addiu(9,0,5);a.branch(4,8,9,'restore')
    a.lw(11,16,4);a.lw(9,28,-22364);a.branch(5,11,9,'restore')
    for name,ctrl in (('start',ordinary.start_gate.CONTROL),('intro',ordinary.intro.CONTROL)):
        a.li(8,ctrl);a.lw(9,8);a.addiu(10,0,1);a.branch(5,9,10,f'skip_{name}')
        a.lw(9,8,8);a.branch(5,9,11,f'skip_{name}');a.sw(0,8,4)
        a.label(f'skip_{name}')
    a.label('restore');restore(a);a.jump(previous)
    result=a.finish();assert CODE+len(result)<FREE_G;return result


def scoped_copy_wrapper(address,copy,tail,family=None):
    a=Assembler(address);a.addiu(29,29,-0x20)
    for i,r in enumerate((8,9,10)):a.i(63,r,29,i*8)
    gate(a,'native',family)
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x20);a.jump(copy)
    a.label('native')
    for i,r in enumerate((8,9,10)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x20);a.jump(tail)
    return a.finish()


def model_bridge(address,target):
    a=Assembler(address);a.addiu(29,29,-16);a.i(63,8,29,0);a.i(63,9,29,8)
    a.r(0,8,0,4,1);a.r(0x21,8,8,4);a.r(0,8,0,8,2)
    a.li(9,RECORDS);a.r(0x21,8,8,9);a.lw(4,8,4)
    a.i(55,8,29,0);a.i(55,9,29,8);a.addiu(29,29,16);a.jump(target)
    return a.finish()


def inspect_family(ram,f):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    ptr=lambda p,n:0x100000<=p<=len(ram)-n
    family=u(f['global_']);pool=u(f['poolglobal'])
    require(ptr(family,f['size']) and u(family)==2 and ptr(pool,24),'Expected native two-owner effect family')
    table=u(family+f['tableoff']);particles=u(family+8)
    require(ptr(table,8) and u(family+4)==f['oldcapacity'] and
            ptr(particles,f['oldcapacity']*f['stride']),'Invalid native effect table/particles')
    nodes=u(pool+16);payloads=u(pool+20);module=u(pool)
    require(ptr(nodes,128) and ptr(payloads,2*f['body']) and ptr(module,64) and
            u(module+36)==pool and u(module+40)==f['callbacks'],'Invalid native effect pool hierarchy')
    seen=set();owners=set();bodies=[];node=u(pool+4);previous=0
    while node:
        require(node in (nodes,nodes+64) and node not in seen,'Invalid effect active list')
        body=u(node+56);require(u(node+32)==pool and u(node+36)==0 and u(node+40)==f['child'] and
                              u(node+44)==previous and body==payloads+(node-nodes)//64*f['body'],
                              'Invalid native effect instance ownership')
        mid=u(body+f['owner']);require(mid<2 and mid not in owners and u(table+mid*4)==node,'Invalid effect owner table')
        seen.add(node);owners.add(mid);bodies.append(body);previous=node;node=u(node+48)
    require(u(pool+8)==previous,'Invalid effect active tail')
    for mid in range(2):require(bool(u(table+4*mid))==(mid in owners),'Orphaned effect owner table')
    node=u(pool+12)
    while node:
        require(node in (nodes,nodes+64) and node not in seen,'Invalid effect free list')
        require(u(node+32)==pool and u(node+56)==payloads+(node-nodes)//64*f['body'],'Invalid effect free node')
        seen.add(node);node=u(node+52)
    require(len(seen)==2,'Native effect nodes are not fully accounted for')
    if f['name']=='afterimage':
        ordinary.particle_partition(ram,family,particles,140,192,12,16,20,176,7,owners)
    else:
        require(u(family+12)<200,'Invalid giant particle cursor');parts=set()
        for body in bodies:
            for group in range(10):
                particle=u(body+16+144*group)
                while particle:
                    delta=particle-particles
                    require(0<=delta<200*64 and delta%64==0 and particle not in parts,'Invalid giant particle chain')
                    parts.add(particle);particle=u(particle+48)
    return dict(family=family,pool=pool,table=table,particles=particles,nodes=nodes,payloads=payloads,
                active_bodies=bodies,owners=sorted(owners))


def build_memory(ram,config=None,source='<offline-held>'):
    require(len(ram)==0x8000000,'Requires128MiB captured RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0];manager=u(core.ACTORS);count=u(core.MODE+4)
    require(count in ACTOR_COUNTS and u(core.MODE)==1 and u(core.MODE+8)==manager and
            u(core.MODE+12)==count and not u(core.PAIR+4),'Expected captured four/six world')
    actors=[];mids=[];models=[]
    for i in range(count):
        actor=u(core.POINTERS+4*i);require(0x100000<=actor<=len(ram)-0x1600,'Invalid captured actor pointer')
        mid=u(actor+12);require(mid<12 and mid not in mids,'Invalid captured model ID')
        model=u(core.MODELS+mid*4)
        require(u(actor)==i and 0x100000<=model<=len(ram)-0x1670 and u(model+16)==mid,'Invalid captured model identity')
        require(u(actor+0x948)==11 and all(u(actor+o)==0 for o in (0x1278,0x127C,0x1280,0x1284)),
                'Effect preparation requires every actor held idle')
        actors.append(actor);mids.append(mid);models.append(model)
    require(mids[:2]==[0,1] and u(ordinary.CONTROL+4)==manager and u(ordinary.CONTROL) in (0,5),
            'Ordinary aura expansion must be prepared first')
    require(not any(ram[CODE:END]),'Extended aura reservation occupied')
    captures=[inspect_family(ram,f) for f in FAMILIES]
    _,_,native=elf_reader(elf_path(ROOT))
    for i,(entry,_) in enumerate(bounds.ENTRIES):
        p=bounds.WRAPPERS+i*0x100;expected=bounds.wrapper_code(i,native(entry,8))
        require(ram[p:p+len(expected)]==expected and
                ram[entry:entry+8]==struct.pack('<2I',(2<<26)|(p>>2),0),'Changed afterimage entry guard')
    previous=(u(ordinary.HOOK)&0x3FFFFFF)<<2
    require(u(ordinary.HOOK)>>26==2 and u(ordinary.HOOK+4)==0 and 0x07000000<=previous<0x08000000,'Expected held frame chain')
    control=bytearray(0x100);struct.pack_into('<5I',control,0,0,manager,count,0,previous)
    pieces=[]
    for i,(f,c) in enumerate(zip(FAMILIES,captures)):
        vals=(c['family'],c['pool'],c['table'],c['particles'],f['oldcapacity'],u(c['family']+12),
              0,u(c['family']+20) if i else 0,c['nodes'],c['payloads'],2,0,0)
        struct.pack_into('<13I',control,0x40+i*64,*vals)
        nodes=bytearray(640)
        for j in range(10):
            struct.pack_into('<H',nodes,j*64+2,j+2);struct.pack_into('<I',nodes,j*64+32,c['pool'])
            struct.pack_into('<I',nodes,j*64+52,f['nodes']+64*(j+1) if j<9 else 0)
            struct.pack_into('<I',nodes,j*64+56,f['payloads']+f['body']*j)
        original=native(f['free'],8);require(ram[f['free']:f['free']+8]==original,'Changed native family teardown')
        pieces.extend(((f['nodes'],bytes(nodes)),(f['wrapper'],free_code(i)),
                       (f['tail'],original+struct.pack('<2I',(2<<26)|((f['free']+8)>>2),0)),
                       (f['free'],struct.pack('<2I',(2<<26)|(f['wrapper']>>2),0))))
    for address,cleanup in ((bounds.PREDICATE,False),(bounds.CLEAN_PREDICATE,True)):
        old=bounds.predicate_code(cleanup);require(ram[address:address+len(old)]==old,'Changed afterimage bounds')
        p=CLEAN if cleanup else PRED;pieces.extend(((p,predicate(cleanup)),(OLD_CLEAN if cleanup else OLD_PRED,old),
                        (address,struct.pack('<2I',(2<<26)|(p>>2),0))))
    for p in (A(0x1D0564),A(0x1D05A4),A(0x1D05DC)):
        require(u(p)==0x8E040000,'Changed physical afterimage callsite');pieces.append((p,struct.pack('<I',0x8E04000C)))
    heartbeat=bytearray(native(A(0x164F30),0xE8));require(ram[A(0x164F30):A(0x165018)]==heartbeat,'Changed native aura heartbeat')
    for p in (A(0x164F88),A(0x164FAC),A(0x164FEC)):struct.pack_into('<I',heartbeat,p-A(0x164F30),0x24020000|count)
    for p,target in ((A(0x164FCC),META_REFRESH),(A(0x164FDC),META_CLASS)):
        struct.pack_into('<I',heartbeat,p-A(0x164F30),(3<<26)|(target>>2))
    alloc=bytearray(native(A(0x16E7C8),0x80));require(ram[A(0x16E7C8):A(0x16E848)]==alloc,'Changed native afterimage allocator')
    require(struct.unpack_from('<I',alloc,0x24)[0]==0x28420046,'Unexpected native afterimage cap')
    struct.pack_into('<I',alloc,0x24,0x28420000|840)
    pieces.extend(((CONTROL,bytes(control)),(RECORDS,b''.join(struct.pack('<3I',*r) for r in zip(actors,mids,models))),
                   (DRAIN_G,drain_giant_code()),
                   (CODE,code(previous,actors,mids,models,captures)),
                   (HEART,scoped_copy_wrapper(HEART,HEART_COPY,HEART_TAIL,0)),
                   (HEART_COPY,bytes(heartbeat)),(HEART_TAIL,native(A(0x164F30),8)+struct.pack('<2I',(2<<26)|(A(0x164F38)>>2),0)),
                   (META_REFRESH,model_bridge(META_REFRESH,A(0x206F68))),(META_CLASS,model_bridge(META_CLASS,A(0x1643D0))),
                   (ALLOC_WRAP,scoped_copy_wrapper(ALLOC_WRAP,ALLOC_COPY,ALLOC_TAIL,1)),(ALLOC_COPY,bytes(alloc)),
                   (ALLOC_TAIL,native(A(0x16E7C8),8)+struct.pack('<2I',(2<<26)|(A(0x16E7D0)>>2),0)),
                   (A(0x164F30),struct.pack('<2I',(2<<26)|(HEART>>2),0)),
                   (A(0x16E7C8),struct.pack('<2I',(2<<26)|(ALLOC_WRAP>>2),0)),
                   (ordinary.HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))))
    intervals=sorted((p,p+len(b)) for p,b in pieces)
    require(all(end<=b for (_,end),(b,_) in zip(intervals,intervals[1:])),'Extended aura payload overlap')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                status='HELD GIANT/AFTERIMAGE INITIALIZATION; WAIT STATUS5; LIVE RENDER VALIDATION REQUIRED',
                actors=actors,model_ids=mids,models=models,captures=captures,previous_frame=previous,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in pieces],
                limitations=['Shared authored textures remain native; per-owner instances/particles are independent.',
                             'Only giant aura and afterimages expanded; other cosmetic families are separate.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    args.out.write_text(json.dumps(build_memory(read_ram(args.source),source=args.source),indent=2)+'\n')
