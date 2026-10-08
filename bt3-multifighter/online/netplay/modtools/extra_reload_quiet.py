"""Strict reload jobs executed by the parent's acknowledged native quiet gate.

The parent calls ENTRY only while its native quiet branch skips both battle
dispatches. This runner never releases quiet, accepts only the four compiled
reload entries, and requires the matched extra owner idle or in its acknowledged
ordinary form action. The rest of the
fighters keep their existing actions and input state unchanged.
"""
from native_map import A, CRC, SERIAL
import struct
import native_preparation as native
import fresh_team_combat as core
from prototype import Assembler
import battle_mode_policy as policy

ENTRY,CONTROL,END=0x07650000,0x0765F000,0x07660000
MAGIC=0x524C4431
TARGETS=((0x07600000,0x0760F000),(0x07610000,0x0761F000),(0x07620000,0x0762F000),
         (0x07670000,0x0767F000))
SAVED=tuple(range(1,29))+(30,31)
# Second, hold-agnostic runner inside the same reservation. It drives ONLY the
# serial IO pair (TARGETS[0]) and never writes the private request row: the host
# still owns every row transition. BG_CONTROL words:
#   +0 magic  +4 request  +8 ack  +12 result  +16 manager  +20 io entry
#   +24 io control  +28 calls  +32 physical  +36 expected owner action
#   +40 request row  +44 row generation  +48 reserved  +52 idle waits
#   +56/+60 reserved
BACKGROUND,BG_CONTROL=0x07658000,0x0765E000
BG_MAGIC=0x424B4731
# Strictly shorter than the host's own hold-A' bound (40 presentation frames),
# so the runner always goes inert before the host decides to unwind.
BG_IDLE_CALLS=30
# Verified loader state/handle/pending-count (SLUS_216.78.c:287249-287303) and
# the native task FIFO object allocated by sub_263490 (*(gp-20816)); its +8/+12/
# +16 are the fields its own reset clears. The pointer is bounds-checked and the
# FIFO term is skipped when it does not validate, never treated as busy.
LOADER_STATE,LOADER_HANDLE,LOADER_PENDING=A(0x31E760),A(0x31E764),A(0x31E77C)
TASK_FIFO=A(0x2FF120)
SCENE_FLAGS,SCENE_RELOAD_MASK=A(0x3337B8),0x3800


def checks(world,allow_forms=False):
    action=world.get('owner_action',11) if allow_forms else 11
    if action!=11 and action not in range(236,243):raise ValueError('Unsupported reload owner action')
    return [(native.CONTROL,native.MAGIC),(native.CONTROL+16,1),(native.CONTROL+20,1),
            (native.CONTROL+24,world['manager']),(world['actor']+0x948,action)]


def validate(ram,world,allow_forms=False):
    for p,v in checks(world,allow_forms):
        if struct.unpack_from('<I',ram,p)[0]!=v:raise ValueError('Matching native quiet ACK and idle reload owner required')


def guard(a,world,label,allow_forms=False):
    for p,v in checks(world,allow_forms):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,label)


def code():
    a=Assembler(ENTRY);a.addiu(29,29,-0x150)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0x100+4*i)
    a.li(16,CONTROL);a.lw(8,16);a.li(9,MAGIC);a.branch(5,8,9,'done')
    a.lw(17,16,4);a.lw(8,16,8);a.branch(4,17,8,'done')
    for p,v in ((native.CONTROL,native.MAGIC),(native.CONTROL+16,1),(native.CONTROL+20,1),(core.MODE,1)):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error110')
    a.lw(18,16,16);a.lw(8,28,-22364);a.branch(5,8,18,'error110')
    for p in (native.CONTROL+24,core.MODE+8):
        a.li(8,p);a.lw(8,8);a.branch(5,8,18,'error110')
    a.li(8,core.MODE);a.lw(9,8,4);a.lw(10,8,12);a.branch(5,9,10,'error110')
    policy.emit_listed_count(a,9,'error110','count',scratch=10)
    a.label('count');a.lw(19,16,32);a.i(11,8,19,2);a.branch(5,8,0,'error110')
    a.r(0x2B,8,19,9);a.branch(4,8,0,'error110')
    a.r(0,8,0,19,2);a.li(9,core.POINTERS);a.r(0x2D,8,8,9);a.lw(20,8)
    a.li(9,0x100000);a.r(0x2B,8,20,9);a.branch(5,8,0,'error110')
    a.li(9,0x08000000-0x1600);a.r(0x2B,8,9,20);a.branch(5,8,0,'error110')
    a.i(12,8,20,3);a.branch(5,8,0,'error110');a.lw(8,20);a.branch(5,8,19,'error110')
    a.lw(8,20,0x948);a.lw(9,16,36);a.branch(5,9,0,'expected_action');a.addiu(9,0,11)
    a.label('expected_action');a.branch(5,8,9,'error110');a.addiu(9,0,11);a.branch(4,8,9,'action_valid')
    a.addiu(8,8,-236);a.i(11,8,8,7);a.branch(4,8,0,'error110');a.label('action_valid')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'error110')
    # Validate both constants before dereferencing a requested control block.
    a.lw(21,16,24);a.lw(8,16,20)
    for index,(entry,control) in enumerate(TARGETS):
        a.li(9,entry);a.branch(5,8,9,f'next{index}')
        a.li(9,control);a.branch(5,21,9,'error110');a.jump('target_valid')
        a.label(f'next{index}')
    a.jump('error110')
    a.label('target_valid');a.lw(8,21,8);a.branch(5,8,18,'error110')
    a.lw(8,21,12);a.branch(5,8,20,'error110')
    a.lw(8,21);a.addiu(9,0,1);a.branch(5,8,9,'error110')
    a.lw(8,16,20)
    for index,(entry,control) in enumerate(TARGETS):
        a.li(9,entry);a.branch(5,8,9,f'call_next{index}')
        a.call(entry);a.jump('called');a.label(f'call_next{index}')
    a.jump('error110')
    a.label('called');a.lw(8,16,28);a.addiu(8,8,1);a.sw(8,16,28)
    a.lw(8,21,4);a.sw(8,16,12);a.addiu(9,0,5);a.branch(4,8,9,'ack')
    a.i(11,9,8,100);a.branch(5,9,0,'done');a.jump('ack')
    a.label('error110');a.addiu(8,0,110);a.sw(8,16,12)
    a.label('ack');a.sw(17,16,8)
    a.label('done')
    for i in range(12):a.i(49,20+i,29,0x100+4*i)
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x150);a.jr()
    result=a.finish();assert len(result)<0x2000;return result


def background_guard(row,generation,action):
    """quiet_guard-compatible emitter for an unheld background IO body.

    It replaces the held runner's ACK words with the request row's own identity,
    so the job refuses (error111) when the row or its owner moved before the
    start. extra_reload_preload.payload emits it in the START phase only.
    """
    if type(row) is not int or type(generation) is not int or type(action) is not int:
        raise ValueError('Background guard requires an explicit row, generation and action')
    if not 0x100000<=row<=0x08000000-64 or row%4:raise ValueError('Invalid background request row')
    if not 1<=generation<=0xFFFFFFFF:raise ValueError('Invalid background request generation')
    if action not in range(236,243):raise ValueError('Background IO serves transformation actions236..242')
    def emit(a,world,label,allow_forms=True):
        a.li(10,row)
        for off,value in ((0,generation),(4,2),(8,world['actor']),(56,1),(60,action)):
            a.lw(8,10,off);a.li(9,value);a.branch(5,8,9,label)
        a.li(8,world['actor']);a.lw(8,8,0x948);a.li(9,action);a.branch(5,8,9,label)
    return emit


def background_code():
    """Unheld per-frame driver for one already published serial IO job.

    Called from both gate paths once per battle-loop iteration, magic-gated, so
    an older prepared match (zeros here) never jumps into it. It refuses while
    the ordinary held runner owns a request, starts the IO only on a verifiably
    idle native loader, then makes exactly one bounded poll step per call and
    acknowledges the host with the job's own status. It writes nothing outside
    BG_CONTROL.
    """
    import extra_reload_service as job
    import extra_reload_requests as requests
    assert requests.STRIDE==64,'Background row arithmetic assumes the64-byte request stride'
    entry,control=TARGETS[0]
    assert (entry,control)==(job.ENTRY,job.CONTROL),'Background runner serves the serial IO pair'
    a=Assembler(BACKGROUND);a.addiu(29,29,-0x150)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    for i in range(12):a.i(57,20+i,29,0x100+4*i)
    a.li(16,BG_CONTROL);a.lw(8,16);a.li(9,BG_MAGIC);a.branch(5,8,9,'done')
    a.lw(17,16,4);a.lw(8,16,8);a.branch(4,17,8,'done')
    # The held runner owns the same workspaces; never drive one job from two
    # call sites in the same frame.
    a.li(8,CONTROL);a.lw(9,8,4);a.lw(10,8,8);a.branch(5,9,10,'done')
    for p,v in ((native.CONTROL,native.MAGIC),(core.MODE,1)):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'error110')
    a.lw(18,16,16);a.lw(8,28,-22364);a.branch(5,8,18,'error110')
    a.li(8,core.MODE);a.lw(9,8,8);a.branch(5,9,18,'error110')
    a.lw(9,8,4);a.lw(10,8,12);a.branch(5,9,10,'error110')
    policy.emit_listed_count(a,9,'error110','count',scratch=10)
    a.label('count');a.lw(19,16,32);a.i(11,8,19,2);a.branch(5,8,0,'error110')
    a.r(0x2B,8,19,9);a.branch(4,8,0,'error110')
    a.r(0,8,0,19,2);a.li(9,core.POINTERS);a.r(0x2D,8,8,9);a.lw(20,8)
    a.li(9,0x100000);a.r(0x2B,8,20,9);a.branch(5,8,0,'error110')
    a.li(9,0x08000000-0x1600);a.r(0x2B,8,9,20);a.branch(5,8,0,'error110')
    a.i(12,8,20,3);a.branch(5,8,0,'error110');a.lw(8,20);a.branch(5,8,19,'error110')
    a.lw(21,16,36);a.addiu(8,21,-236);a.i(11,8,8,7);a.branch(4,8,0,'error110')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'error110')
    a.lw(8,16,20);a.li(9,entry);a.branch(5,8,9,'error110')
    a.lw(8,16,24);a.li(9,control);a.branch(5,8,9,'error110')
    a.li(22,control);a.lw(8,22);a.addiu(9,0,1);a.branch(5,8,9,'error110')
    a.lw(8,22,8);a.branch(5,8,18,'error110')
    a.lw(8,22,12);a.branch(5,8,20,'error110')
    # The row address is recomputed from the validated physical id, never taken
    # from the request word.
    a.addiu(8,19,-2);a.r(0,8,0,8,6);a.li(9,requests.RECORDS);a.r(0x2D,23,9,8)
    a.lw(8,16,40);a.branch(5,8,23,'error110')
    a.lw(8,23);a.lw(9,16,44);a.branch(5,8,9,'error110')
    a.lw(8,22,4);a.branch(4,8,0,'idle_gate')
    a.addiu(9,0,2);a.branch(4,8,9,'call_entry');a.jump('report')
    a.label('idle_gate')
    # Nothing is opened, allocated, reserved or queued while the owner has left
    # its transformation pose, or while any native loader work is in flight.
    a.lw(8,20,0x948);a.branch(5,8,21,'error110')
    for p in (LOADER_STATE,LOADER_HANDLE):
        a.li(8,p);a.lw(8,8);a.branch(5,8,0,'wait')
    a.li(8,LOADER_PENDING);a.lw(8,8);a.i(12,8,8,0xFFFF);a.branch(5,8,0,'wait')
    a.li(8,TASK_FIFO);a.lw(8,8)
    a.li(9,0x100000);a.r(0x2B,10,8,9);a.branch(5,10,0,'fifo_unknown')
    a.li(9,0x08000000-32);a.r(0x2B,10,9,8);a.branch(5,10,0,'fifo_unknown')
    a.i(12,10,8,3);a.branch(5,10,0,'fifo_unknown')
    a.lw(8,8,12);a.branch(5,8,0,'wait')
    a.label('fifo_unknown');a.move(8,18)
    for off in (600,612,628):
        a.lw(9,8,off);a.branch(5,9,0,'wait')
    a.lw(9,8,604);a.lw(10,8,608);a.branch(5,9,10,'wait')
    a.li(8,SCENE_FLAGS);a.lw(8,8);a.i(12,8,8,SCENE_RELOAD_MASK);a.branch(5,8,0,'wait')
    a.sw(0,16,52);a.jump('call_entry')
    a.label('wait');a.lw(8,16,52);a.addiu(8,8,1);a.sw(8,16,52)
    a.i(11,9,8,BG_IDLE_CALLS);a.branch(5,9,0,'done')
    a.addiu(8,0,112);a.jump('ack_status')
    a.label('call_entry');a.call(entry)
    a.lw(8,16,28);a.addiu(8,8,1);a.sw(8,16,28);a.lw(8,22,4)
    a.label('report');a.addiu(9,0,5);a.branch(4,8,9,'ack_status')
    a.i(11,9,8,100);a.branch(5,9,0,'done')
    a.label('ack_status');a.sw(8,16,12);a.jump('ack')
    a.label('error110');a.addiu(8,0,110);a.sw(8,16,12)
    a.label('ack');a.sw(17,16,8)
    a.label('done')
    for i in range(12):a.i(49,20+i,29,0x100+4*i)
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x150);a.jr()
    result=a.finish();assert BACKGROUND+len(result)<BG_CONTROL;return result


def build_memory(ram):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    if any(ram[ENTRY:END]):raise ValueError('Quiet reload runner reservation occupied')
    parts=[(ENTRY,code()),(CONTROL,struct.pack('<9I',MAGIC,0,0,0,0,0,0,0,0)),
           (BACKGROUND,background_code()),(BG_CONTROL,struct.pack('<16I',BG_MAGIC,*([0]*15)))]
    return dict(serial=SERIAL,crc=CRC,control=CONTROL,entry=ENTRY,
                background=BACKGROUND,bg_control=BG_CONTROL,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in parts])
