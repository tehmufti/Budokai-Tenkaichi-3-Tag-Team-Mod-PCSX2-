"""Load actual selected bench bundles for fresh teams of up to five per side.

Only constructs guarded manifests or reads completed offline results. Resource
requests execute one at a time through the game's normal asynchronous loader.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
from selected_team_capture import capture, selected_damage
import fresh_memory as memory
from battle_mode_policy import TEAM_CAPACITY, MAX_ACTORS
from native_map import FILE_ID

CODE, CONTROL, DESCRIPTORS, HOOK = 0x07364000, 0x07367000, 0x07367100, A(0x1C2A28)
# At most one distinct load per extra: every fighter beyond the two leaders.
QUEUE_SLOTS = MAX_ACTORS - 2
assert DESCRIPTORS + QUEUE_SLOTS*64 <= 0x07368000, 'Resource descriptors overrun the queue reservation'


def queue_for(selection):
    if not 2 <= selection['members_per_side'] <= TEAM_CAPACITY:
        raise ValueError(f'Fresh simultaneous mode requires up to {TEAM_CAPACITY} selected members per side; 1v1 stays native')
    requests,bindings=[],[]
    seen={}
    for row in selection['roster'][2:]:
        character,costume=row['character'],row['costume']
        damaged=selected_damage(row)
        if not 0<=costume<=3:raise ValueError('Native costume index must be 0..3')
        key=(character,costume,damaged)
        binding={'physical_id':row['physical_id'],'character':character,'costume':costume,'damaged':damaged}
        if row.get('participating') is False and row['loaded_resource'] is None:
            raise ValueError('An inactive reservation must reuse its actual leader bundle')
        if row['loaded_resource'] is not None:
            binding.update(resource=row['loaded_resource'],resource_handle=row['loaded_resource_handle'])
        else:
            if key not in seen:
                seen[key]=len(requests)
                requests.append({'character':character,'costume':costume,'damaged':damaged,
                                 'file_ids':[FILE_ID(10*character+1424+costume+4*damaged),FILE_ID(10*character+1432),FILE_ID(10*character+1433)]})
            binding['queue_index']=seen[key]
        bindings.append(binding)
    return requests,bindings


def hold_idle_tail(a):
    """Only the direct native queue call can defer the following actor update.

    Resource IO and the loading-screen draw remain native. Once actor creation
    wraps this queue, its return address differs and the old behavior resumes.
    """
    import native_preparation as transport
    a.li(8,A(0x12BC9C));a.branch(5,31,8,'idle_return')
    for address,value in ((HOOK,(2<<26)|(CODE>>2)),(HOOK+4,0),
                          (A(0x12BC9C),(3<<26)|(A(0x12B6E0)>>2)),(A(0x12BCA0),0),
                          (A(0x3337C0),1),(A(0x31BE04),0),(0xD8080,0),
                          (transport.CONTROL,transport.MAGIC),
                          (transport.CONTROL+52,1),(CONTROL,1),
                          (memory.CONTROL,20),(memory.CONTROL+80,1)):
        a.li(8,address);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'idle_return')
    a.lw(10,28,-22364)
    for address in (CONTROL+20,memory.CONTROL+84,transport.CONTROL+24):
        a.li(8,address);a.lw(8,8);a.branch(5,8,10,'idle_return')
    a.lw(8,10);a.addiu(9,0,2);a.branch(5,8,9,'idle_return')
    a.lw(11,10,4);a.li(8,CONTROL+28);a.lw(8,8);a.branch(5,8,11,'idle_return')
    a.li(8,0x100000);a.r(0x2B,9,11,8);a.branch(5,9,0,'idle_return')
    a.li(8,0x8000000-0x2C00);a.r(0x2B,9,8,11);a.branch(5,9,0,'idle_return')
    a.i(12,8,11,15);a.branch(5,8,0,'idle_return')
    for side in range(2):
        off=side*0x1600
        for field,value in ((0,side),(12,side),(0x994,0),(0x948,11),
                            (0x1278,0),(0x127C,0),(0x1280,0),(0x1284,0)):
            a.lw(8,11,off+field);a.li(9,value);a.branch(5,8,9,'idle_return')
    a.li(8,CONTROL+32);a.lw(9,8);a.addiu(9,9,1);a.sw(9,8)
    # The skipped routine normally supplies the following single/split mode.
    # Like transport quiet, request the native full-surface loading draw.
    a.move(2,0);a.addiu(31,31,8)
    a.label('idle_return')


# sub_265298's own disc-job state word: 0 idle, 1 open, 2 read, 3 wait, 4 retire.
PUMP_STATE = A(0x31E760)
# Upper bound on native pump steps per pump site in one frame (fast_pump only).
PUMP_STEPS = 8


def pump_until_stalled(a):
    """Subroutine 'pump': step the native disc job while each step advances it.

    Native loaders already call sub_265298 repeatedly within one frame
    (sub_263198 spins on it). Stop on the first nonzero result (queue idle),
    when a step leaves the state word unchanged (refused open or read, or a read
    still in flight), or after PUMP_STEPS calls. Returns the last result in v0;
    clobbers t0, s2 and s3, which the caller's frame saves.
    """
    a.label('pump');a.addiu(29,29,-16);a.i(63,31,29,0);a.addiu(18,0,PUMP_STEPS)
    a.label('pump_step');a.li(8,PUMP_STATE);a.lw(19,8)
    a.call(A(0x265298));a.branch(5,2,0,'pump_return')
    a.li(8,PUMP_STATE);a.lw(8,8);a.branch(4,8,19,'pump_return')
    a.addiu(18,18,-1);a.branch(5,18,0,'pump_step')
    a.label('pump_return');a.i(55,31,29,0);a.addiu(29,29,16);a.jr()


def payload(requests, *, hold_idle=False, fast_pump=False):
    """Frame-hook queue for the selected bundles.

    The default and hold_idle emitters are pinned byte-for-byte. fast_pump adds
    no new states or results: it only steps the native pump until it stalls,
    starts the first read in the frame that queued a request, and issues the
    next request in the frame that completed the previous one.
    """
    saved=((16,0),(17,8),(18,16),(19,24),(31,32)) if fast_pump else ((16,0),(17,8),(31,16))
    frame,result=(0x40,40) if fast_pump else (0x30,24)
    pump='pump' if fast_pump else A(0x265298)
    a=Assembler(CODE);a.addiu(29,29,-frame)
    for reg,off in saved:a.i(63,reg,29,off)
    a.call(memory.CODE);a.i(63,2,29,result)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,20);a.lw(9,28,-22364);a.branch(5,8,9,'done')
    a.lw(8,9);a.addiu(9,0,2);a.branch(5,8,9,'done')
    a.li(8,memory.CONTROL);a.lw(8,8);a.addiu(9,0,20);a.branch(5,8,9,'done')
    a.lw(8,16,4);a.addiu(9,0,5);a.branch(4,8,9,'done')
    a.i(11,9,8,100);a.branch(4,9,0,'done')
    if fast_pump:a.label('dispatch')
    a.lw(8,16,8)
    for k in range(len(requests)):
        a.addiu(9,0,k);a.branch(4,8,9,f'entry{k}')
    a.jump('complete')
    for k,request in enumerate(requests):
        a.label(f'entry{k}');a.li(17,DESCRIPTORS+k*64)
        a.call(pump);a.branch(4,2,0,'done')
        a.lw(8,17,28);a.branch(5,8,0,f'poll{k}')
        a.move(4,0)
        for reg,value in zip((5,6,7),request['file_ids']):a.li(reg,value)
        a.call(A(0x24B7A8))
        a.i(11,8,2,2);a.branch(5,8,0,'error120')
        a.i(11,8,2,14);a.branch(4,8,0,'error120')
        a.sw(2,17,20);a.addiu(8,0,1);a.sw(8,17,28);a.sw(8,16,4)
        # Open and start the first read in the frame that queued the files.
        if fast_pump:a.call(pump)
        a.jump('done')
        a.label(f'poll{k}');a.lw(4,17,20);a.call(A(0x24B910))
        a.li(8,0x100000);a.r(0x2B,9,2,8);a.branch(5,9,0,'error130')
        a.li(8,0x8000000-56);a.r(0x2B,9,8,2);a.branch(5,9,0,'error130')
        a.lw(8,2,48);a.addiu(9,0,3);a.branch(5,8,9,'error131')
        a.lw(8,2,52);a.lw(9,17,20);a.branch(5,8,9,'error131')
        for n,file_id in enumerate(request['file_ids']):
            a.lw(8,2,n*16);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'error140')
            a.li(9,0x8000000);a.r(0x2B,9,8,9);a.branch(4,9,0,'error140')
            a.lw(9,2,n*16+4);a.branch(4,9,0,'error140')
            a.li(10,0x8000000);a.r(0x2B,10,10,9);a.branch(5,10,0,'error140')
            a.r(0x2D,10,8,9);a.li(9,0x8000000);a.r(0x2B,9,9,10);a.branch(5,9,0,'error140')
            a.lw(9,2,n*16+8);a.li(10,file_id);a.branch(5,9,10,'error141')
            a.sw(8,17,32+n*4)
        a.sw(2,17,24);a.addiu(8,0,2);a.sw(8,17,28)
        # fast_pump issues the next request (or completes) in this same frame.
        a.addiu(8,0,k+1);a.sw(8,16,8);a.sw(8,16,12);a.jump('dispatch' if fast_pump else 'done')
    a.label('complete');a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    for error in (120,130,131,140,141):
        a.label(f'error{error}');a.addiu(8,0,error);a.sw(8,16,4);a.jump('done')
    a.label('done');a.i(55,2,29,result)
    for reg,off in saved:a.i(55,reg,29,off)
    a.addiu(29,29,frame)
    if hold_idle:hold_idle_tail(a)
    a.jr()
    if fast_pump:pump_until_stalled(a)
    code=a.finish();assert CODE+len(code)<CONTROL
    return code


def build(source, *, hold_idle=False, fast_pump=False, minimum_members=1):
    r=read_ram(source);selection=capture(r,minimum_members=minimum_members);requests,bindings=queue_for(selection)
    u=lambda p:struct.unpack_from('<I',r,p)[0]
    if u(memory.CONTROL)!=20 or u(memory.START1)!=memory.START or u(memory.END1)!=memory.END:
        raise ValueError('Run fresh extended heap bootstrap successfully before building the loader')
    expected_hook=struct.pack('<2I',(2<<26)|(memory.CODE>>2),0)
    if r[HOOK:HOOK+8]!=expected_hook:raise ValueError('Expected fresh-memory wrapper chain')
    if len(requests)>QUEUE_SLOTS:raise ValueError('More distinct selected bundles than queue descriptors')
    if any(r[CODE:DESCRIPTORS+QUEUE_SLOTS*64]):raise ValueError('Selected-resource queue reservation occupied')
    control=struct.pack('<8I',1,0,0,0,len(requests),selection['native_manager'],memory.CODE,selection['native_actor_array'])
    if hold_idle:
        import native_preparation as transport
        if not transport.captured_transport(r):
            raise ValueError('Idle resource hold requires the exact native transport')
        native=elf_reader(elf_path(ROOT))[2]
        if r[A(0x12BC94):A(0x12BCA4)]!=native(A(0x12BC94),16):
            raise ValueError('Idle resource hold requires the original actor dispatch calls')
        for leader in selection['leaders']:
            actor=leader['actor']
            if u(actor+0x948)!=11 or any(u(actor+off) for off in (0x1278,0x127C,0x1280,0x1284)):
                raise ValueError('Idle resource hold requires already idle input-held leaders')
        if (u(transport.CONTROL)!=transport.MAGIC or u(transport.CONTROL+24)!=selection['native_manager']
                or u(transport.CONTROL+16)!=1 or u(transport.CONTROL+20)!=1 or u(transport.CONTROL+52)!=1):
            raise ValueError('Idle resource hold requires the captured native hold')
    payloads=[(CODE,payload(requests,hold_idle=hold_idle,fast_pump=fast_pump)),(CONTROL,control)]
    for k,request in enumerate(requests):
        desc=bytearray(64);struct.pack_into('<6I',desc,0,request['character'],request['costume'],*request['file_ids'],0xFFFFFFFF)
        payloads.append((DESCRIPTORS+k*64,bytes(desc)))
    payloads.append((HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0)))
    return {'serial':SERIAL,'crc':CRC,'source':str(Path(source).resolve()),
            'status':'FRESH SELECTED RESOURCE QUEUE; ACTORS NOT CREATED','control':CONTROL,
            'selection':selection,'requests':requests,'bindings':bindings,
            'blocks':[{'address':p,'expected_hex':r[p:p+len(b)].hex(),'data_hex':b.hex()} for p,b in payloads],
            'requirements':['Run until control+4 is5; any status>=100 requires restoring the prior checkpoint.',
                            'Export completed bindings from the new saved state before creating hidden actors.']}


def export(source,manifest):
    r=read_ram(source);m=json.loads(Path(manifest).read_text());u=lambda p:struct.unpack_from('<I',r,p)[0]
    if u(CONTROL+4)!=5 or u(CONTROL+20)!=u(A(0x2FEB14)):raise ValueError('Queue has not completed in this match')
    output=[]
    for original in m['bindings']:
        row=dict(original)
        if 'queue_index' in row:
            p=DESCRIPTORS+row.pop('queue_index')*64
            if u(p+28)!=2:raise ValueError('Incomplete resource descriptor')
            row.update(resource_handle=u(p+20),resource=u(p+24))
        output.append(row)
    return {'status':'SELECTED BUNDLES LOADED; ACTORS NOT CREATED','bindings':output}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path)
    p.add_argument('--manifest',type=Path,help='Export completed bindings for this loader manifest')
    p.add_argument('--out',required=True,type=Path);x=p.parse_args()
    result=export(x.source,x.manifest) if x.manifest else build(x.source)
    x.out.write_text(json.dumps(result,indent=2)+'\n');print(x.out)
