"""Private BT4 sidecar data for dynamic character bundles.

BT4 moved AI/move/effect metadata out of the mesh into files 4150/4400/
4650-or-4900 + character. Native200790 only serves the leader table. Publish
the exact disc bytes in independent per-resource storage before model init;
route dynamic resource records without aliasing either leader's table.
"""
import struct
from functools import lru_cache

from prototype import Assembler, ROOT, elf_reader
from native_map import elf_path
from bt4_disc import Disc
from bt4_resources import decode_files

HOOK, CODE, OLD, CONTROL, ROWS = 0x200790, 0x06900000, 0x06900F00, 0x06901000, 0x06901100
DATA, STRIDE, END = 0x06800000, 0x14000, 0x06902000
LEADER_DATA = 0x067D0000
MAGIC = 0x4254344D
OFFSETS, SIZES = (0, 0xA800, 0xE800), (0xA800, 0x4000, 0x5000)
NATIVE = elf_reader(elf_path(ROOT))[2]   # the chosen game disc's executable
assert DATA + 12*STRIDE == 0x068F0000


def code():
    a=Assembler(CODE);a.addiu(29,29,-0x30)
    for i,r in enumerate(range(8,13)):a.i(63,r,29,i*8)
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'native')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'native')
    a.i(11,9,5,3);a.branch(4,9,0,'native')
    # Only a record in this native resource registry can select a private row.
    a.lw(9,28,-22060);a.li(10,439276);a.r(0x21,9,9,10)
    a.li(10,ROWS)
    for h in range(2,14):
        a.branch(4,4,9,f'handle{h}');a.addiu(9,9,56);a.addiu(10,10,64)
    for h in range(2):
        a.branch(4,4,9,f'handle{h}');a.addiu(9,9,56);a.addiu(10,10,64)
    a.jump('native')
    for h in range(14):
        a.label(f'handle{h}');a.li(11,h);a.jump('record')
    a.label('record');a.lw(9,4,52);a.branch(5,9,11,'native')
    a.lw(9,4,48);a.i(11,11,11,2);a.branch(5,11,0,'leader_flags');a.addiu(11,0,3);a.jump('flags')
    a.label('leader_flags');a.addiu(11,0,1);a.label('flags');a.branch(5,9,11,'native')
    a.lw(9,10);a.li(11,MAGIC);a.branch(5,9,11,'native')
    a.lw(9,10,4);a.branch(5,9,4,'native')
    for i in range(3):
        a.lw(9,4,8+16*i);a.lw(11,10,8+4*i);a.branch(5,9,11,'native')
    a.r(0,9,0,5,2);a.r(0x21,10,10,9)
    a.lw(2,10,20);a.move(5,2);a.lw(6,10,32)
    for i,r in enumerate(range(8,13)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x30);a.jr()
    a.label('native')
    for i,r in enumerate(range(8,13)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x30);a.jump(OLD)
    result=a.finish();assert CODE+len(result)<OLD
    return result


def pieces():
    return [(CODE,code()),(OLD,NATIVE(HOOK,8)+struct.pack('<2I',(2<<26)|((HOOK+8)>>2),0)),
            (HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0))]


@lru_cache(maxsize=500)
def sidecars(character, variant):
    disc=Disc()
    try: blobs=[disc.read(base+character) for base in (4150,4400,4900 if variant else 4650)]
    finally: disc.close()
    for blob,limit in zip(blobs,SIZES):
        if len(blob)>limit:raise ValueError(f'BT4 metadata for character {character} exceeds its native buffer')
    main=blobs[0];count,start,data,finish,end=struct.unpack_from('<5I',main)
    if count!=3 or not 20<=start<data<finish<end<=len(main) or finish-data<0x3060:
        raise ValueError(f'Invalid BT4 AI metadata package for character {character}')
    return tuple(blobs)


def build_memory(ram, bindings):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,pool=u(0x2FEB14),u(0x2FEC44)
    if not 0x100000<=manager<len(ram)-640 or not 0x100000<=pool<len(ram)-440200:
        raise ValueError('BT4 metadata needs the captured actor/resource managers')
    installed=ram[HOOK:HOOK+8]==pieces()[-1][1]
    if installed:
        if (u(CONTROL),u(CONTROL+4))!=(MAGIC,manager):raise ValueError('BT4 metadata belongs to another match')
        for p,b in pieces():
            if ram[p:p+len(b)]!=b:raise ValueError('BT4 metadata bridge changed')
    elif ram[HOOK:HOOK+8]!=NATIVE(HOOK,8) or any(ram[CODE:END]) or any(ram[DATA:DATA+12*STRIDE]) or any(ram[LEADER_DATA:LEADER_DATA+2*STRIDE]):
        raise ValueError('BT4 metadata storage or native lookup is occupied')
    setting=u(0x304270-0x4FE4)
    if not 0x100000<=setting<len(ram)-0x160C:raise ValueError('BT4 metadata settings pointer is invalid')
    variant=u(setting+0x1608)&1
    blocks=[]
    def add(p,b):
        blocks.append(dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()))
    if not installed:
        for p,b in pieces()[:-1]:add(p,b)
        add(CONTROL,struct.pack('<2I',MAGIC,manager))
    seen=set()
    for binding in bindings:
        handle,resource=binding['resource_handle'],binding['resource']
        expected=pool+439276+(672+handle*56 if handle<2 else (handle-2)*56)
        if not 0<=handle<14 or resource!=expected or (u(resource+48),u(resource+52))!=(1 if handle<2 else 3,handle):
            raise ValueError('BT4 metadata resource is not completely loaded')
        files=binding.get('planned_files',[u(resource+8+i*16) for i in range(3)])
        if 'planned_files' in binding:
            import native_preparation
            if handle>=2 or (u(native_preparation.CONTROL+16),u(native_preparation.CONTROL+20))!=(1,1):
                raise ValueError('Leader metadata adoption requires an acknowledged preparation hold')
        character,_,_=decode_files(files)
        if resource in seen:continue
        seen.add(resource);row=ROWS+(handle-2 if handle>=2 else handle+12)*64
        base=DATA+(handle-2)*STRIDE if handle>=2 else LEADER_DATA+handle*STRIDE
        # Retain in-place native fixups when the exact same bundle is reused.
        identity=struct.pack('<5I',MAGIC,resource,*files)
        if installed and ram[row:row+20]==identity:continue
        for offset,limit,blob in zip(OFFSETS,SIZES,sidecars(character,variant)):
            add(base+offset,blob+bytes(limit-len(blob)))
        record=struct.pack('<12I',MAGIC,resource,*files,*[base+o for o in OFFSETS],*SIZES,character)+bytes(16)
        add(row,record)
    if not installed:add(*pieces()[-1])
    return dict(serial='SLUS-21978',crc='428113C2',status='BT4 PRIVATE CHARACTER METADATA',blocks=blocks)


def publish(worker,p,ram,bindings):
    manifest=build_memory(ram,bindings)
    if manifest['blocks']:
        worker.apply(p,manifest)
        return worker._snapshot(p)
    return ram


def staged(worker,p,ram,control):
    u=lambda at:struct.unpack_from('<I',ram,at)[0]
    return publish(worker,p,ram,[dict(resource=u(control+32),resource_handle=u(control+36))])


def adoption(worker,p,ram,manifest):
    from bt4_resources import request_files
    bindings=[]
    for config in manifest['configurations']:
        if not config.get('leader'):continue
        row=config['resource'];world=config['world']
        bindings.append(dict(resource=world['old_resource'],resource_handle=world['physical'],
            planned_files=request_files(row['character'],row['costume'],row['damaged'])))
    return publish(worker,p,ram,bindings) if bindings else ram
