"""Frame-boundary preparation transport for the isolated 128 MiB runtime.

PINE publishes data packets only. The EE validates every old byte before it
executes any patch writes, while both combat dispatches are held. Native GS,
disc IO and the loading animation continue running. No stage loads a state.
"""
from native_map import A, elf_path
import struct
import time
from prototype import Assembler, ROOT, elf_reader
import battle_mode_policy as policy

CODE, GATE, CONTROL = 0x07680000, 0x07682000, 0x0768F000
PACKET, CAPACITY = 0x07800000, 0x800000
RECORD_SIZE = 16
MAX_BLOCKS = CAPACITY // (RECORD_SIZE + 2)
HOOK, NATIVE = A(0x12BC84), A(0x126FB0)
MAGIC = 0x42545032
INCLUDE_SINGLE_FFA = CONTROL+60
# Control: magic,request,ack,status,quiet,quiet_ack,manager,blocks,bytes,
# failure_block,frames,combat_frames,armed,captured,deferred_intro,include_single_ffa.
REGS = tuple(range(1, 26)) + (28, 30, 31)
STACK = 0x100


def save(a):
    a.addiu(29, 29, -STACK)
    for i, r in enumerate(REGS): a.i(63, r, 29, i*8)


def restore(a):
    for i, r in enumerate(REGS): a.i(55, r, 29, i*8)
    a.addiu(29, 29, STACK)


def gate_code(heal_any_substate=True):
    """heal_any_substate=False emits the beta.35/36 gate (previous_gate_images), which rewrote only phase-1
    substates below 4."""
    import extra_reload_quiet as reload_job
    a=Assembler(GATE)
    # Keep the native predecessor's result/register behavior exactly.
    a.addiu(29,29,-16);a.i(63,31,29,0);a.call(NATIVE)
    a.i(55,31,29,0);a.addiu(29,29,16)
    save(a);a.li(16,CONTROL);a.lw(8,16);a.li(9,MAGIC)
    a.branch(5,8,9,'normal')
    a.lw(8,16,16);a.branch(5,8,0,'held')
    a.lw(8,16,48);a.branch(4,8,0,'normal')
    a.lw(8,16,52);a.branch(5,8,0,'normal')
    for address,value in ((A(0x3337C0),1),(A(0x331DD0),0),(A(0x31BE04),0),(0xD8080,0),(A(0x2FF084),0),(A(0x2FF08C),0)):
        a.li(8,address);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'normal')
    a.li(8,A(0x331DC8));a.lw(9,8,192);a.lw(10,8,816)
    # One to TEAM_CAPACITY members a side. More falls back to a native match.
    for reg in (9,10):
        a.addiu(11,reg,-1);a.i(11,11,11,policy.TEAM_CAPACITY);a.branch(4,11,0,'normal')
    a.r(0x21,11,9,10);a.addiu(12,0,2);a.branch(5,11,12,'selected_team')
    a.lw(11,16,60);a.addiu(12,0,1);a.branch(5,11,12,'normal')
    a.label('selected_team')
    a.li(8,A(0x2FEB38));a.lw(17,8)
    a.li(9,0x100000);a.r(0x2B,10,17,9);a.branch(5,10,0,'normal')
    a.li(9,0x7FFFE00);a.r(0x2B,10,17,9);a.branch(4,10,0,'normal')
    a.lw(8,17,260);a.li(9,A(0x2C6070));a.branch(5,8,9,'normal')
    a.lw(8,17);a.addiu(9,0,1);a.branch(5,8,9,'ready_phase')
    # Any phase-1 substate but 4 becomes 4 (xori, not sltiu < 4). Native code holds only 0..4 here (99 is the
    # mode-1 path, excluded above by SCENE+8 == 0). 5..98 can only come from a store racing 217410's
    # read-call-reread increment (217424 .. 217500/217508): beta.35/36's host-timed watcher write left 5, and
    # phase 1 never leaves 5 by itself (217520 has no case for it; only the Start skip). This is the same
    # frame, before 2129B0/217520 reads it, so a 5 from any source is healed before it can stall.
    a.lw(8,17,8);a.i(14 if heal_any_substate else 11,9,8,4);a.branch(4,9,0,'normal')
    a.addiu(8,0,4);a.sw(8,17,8);a.addiu(8,0,1);a.sw(8,16,56);a.jump('normal')
    a.label('ready_phase');a.addiu(8,8,-2);a.i(11,9,8,2);a.branch(4,9,0,'normal')
    a.li(8,A(0x2FEB14));a.lw(17,8)
    a.li(9,0x100000);a.r(0x2B,10,17,9);a.branch(5,10,0,'normal')
    a.li(9,0x7FFF000);a.r(0x2B,10,17,9);a.branch(4,10,0,'normal')
    a.lw(8,17);a.addiu(9,0,2);a.branch(5,8,9,'normal')
    a.lw(8,17,16);a.i(12,8,8,1);a.branch(4,8,0,'normal')
    a.lw(18,17,4);a.li(9,0x100000);a.r(0x2B,10,18,9);a.branch(5,10,0,'normal')
    a.li(9,0x7FFD400);a.r(0x2B,10,18,9);a.branch(4,10,0,'normal')
    a.i(12,8,18,15);a.branch(5,8,0,'normal')
    for offset in (0,0x1600):
        a.lw(8,18,offset+0x994);a.branch(5,8,0,'normal')
        a.lw(8,18,offset+0x998);a.addiu(9,8,-1);a.i(11,9,9,policy.TEAM_CAPACITY);a.branch(4,9,0,'normal')
        a.li(9,A(0x331DC8)+192+(624 if offset else 0));a.lw(9,9);a.branch(5,8,9,'normal')
        a.lw(8,18,offset+0x9E4);a.branch(6,8,0,'normal')
    a.sw(17,16,24);a.addiu(8,0,1);a.sw(8,16,16);a.sw(8,16,52)
    a.label('held');a.addiu(8,0,1);a.sw(8,16,20)
    # A bounded reload may use the same acknowledged combat hold. The runner
    # validates its owner and IO/stage/commit/retire allowlist before each call.
    a.li(8,reload_job.CONTROL);a.lw(8,8);a.li(9,reload_job.MAGIC)
    a.branch(5,8,9,'held_restore');a.call(reload_job.ENTRY)
    a.label('held_restore')
    # A published background reload drains its disc IO from every battle-loop
    # iteration, held or not. Gated on its own magic so a current gate over an
    # older prepared match (zeros at BG_CONTROL) never jumps into the cave.
    a.li(8,reload_job.BG_CONTROL);a.lw(8,8);a.li(9,reload_job.BG_MAGIC)
    a.branch(5,8,9,'held_background');a.call(reload_job.BACKGROUND)
    a.label('held_background')
    # Also skip12B6E0: it advances movement, damage, reloads and effects.
    # Skipping it also removes the value that normally decides the draw path:
    # the caller keeps whatever this gate returns in s0 (delay slot at12BCA8)
    # and takes the two-viewport12B9C0 only when12AB10 reports split AND s0
    # is nonzero. Native12B6E0 returns "sub_23EFF0() == 0", i.e. draw split
    # unless a cinematic owns the whole screen. Zero is therefore correct only
    # while the mod's loading cover owns the screen; during an in-combat hold
    # (costume/form reload, body exchange, failed-match hold) it collapsed the
    # split view and dropped its divider on every held frame. Report split
    # instead, and let the unchanged12AB10 query decide single-view modes.
    import guest_loading_screen as cover
    import battle_mode_policy as modes
    a.li(8,cover.CONTROL);a.lw(8,8);a.li(9,cover.MAGIC);a.branch(5,8,9,'held_uncovered')
    restore(a);a.move(2,0);a.addiu(31,31,24);a.jr()
    # A committed co-op fusion leaves one body and renders one full-screen
    # view, so a held frame has to keep reporting single or the picture would
    # flick back to two viewports for the length of every reload.
    a.label('held_uncovered')
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(10,modes.MAGIC);a.branch(5,9,10,'held_split')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'held_split')
    a.lw(9,8,12);a.addiu(10,0,modes.COOP);a.branch(5,9,10,'held_split')
    a.lw(9,8,8);a.lw(10,8,24);a.r(0x2B,10,10,9);a.branch(4,10,0,'held_split')
    restore(a);a.move(2,0);a.addiu(31,31,24);a.jr()
    a.label('held_split');restore(a);a.addiu(2,0,1);a.addiu(31,31,24);a.jr()
    a.label('normal');a.sw(0,16,20)
    a.lw(8,16,44);a.addiu(8,8,1);a.sw(8,16,44)
    # Same call on the unheld path, so the disc read continues while combat
    # runs. restore() reloads every saved register including r2, and the value
    # the caller keeps in s0 comes from12B6E0 (delay slot at12BCA8), not here.
    a.li(8,reload_job.BG_CONTROL);a.lw(8,8);a.li(9,reload_job.BG_MAGIC)
    a.branch(5,8,9,'normal_background');a.call(reload_job.BACKGROUND)
    a.label('normal_background')
    restore(a);a.jr()
    result=a.finish();assert len(result)<0x2000;return result


def protected_ranges():
    return ((CODE,CONTROL+0x100),(PACKET,PACKET+CAPACITY),(HOOK,HOOK+4),
            (A(0x102098),A(0x10209C)),(0x07470000,0x07471000))



def service_code(*, legacy_block_limit=False):
    a=Assembler(CODE);save(a);a.li(16,CONTROL)
    a.lw(8,16);a.li(9,MAGIC);a.branch(5,8,9,'done')
    a.lw(8,16,40);a.addiu(8,8,1);a.sw(8,16,40)
    a.lw(17,16,4);a.lw(8,16,8);a.branch(4,17,8,'done')
    a.lw(8,16,16);a.branch(4,8,0,'scope_error')
    a.lw(8,16,20);a.branch(4,8,0,'done') # wait until dispatch has stopped
    a.li(8,A(0x2FEB14));a.lw(8,8);a.lw(9,16,24);a.branch(5,8,9,'scope_error')
    a.li(8,A(0x3337C0));a.lw(8,8);a.addiu(9,0,1);a.branch(5,8,9,'scope_error')
    a.lw(18,16,28);a.addiu(8,18,-1)
    if legacy_block_limit:a.i(11,8,8,1024)
    else:a.li(9,MAX_BLOCKS);a.r(0x2B,8,8,9)
    a.branch(4,8,0,'bounds_error')
    a.lw(19,16,32);a.li(8,CAPACITY+1);a.r(0x2B,8,19,8);a.branch(4,8,0,'bounds_error')
    a.r(0,8,0,18,4);a.r(0x2B,9,19,8);a.branch(5,9,0,'bounds_error')
    a.li(20,PACKET);a.move(21,0)
    # Validate the whole transaction before the first destination store.
    a.label('validate_block');a.sw(21,16,36)
    a.lw(8,20);a.lw(9,20,4);a.lw(10,20,8);a.lw(11,20,12)
    a.branch(4,9,0,'bounds_error')
    a.li(12,0x30000);a.r(0x2B,12,8,12);a.branch(5,12,0,'bounds_error')
    a.li(12,0x08000000);a.r(0x2B,13,8,12);a.branch(4,13,0,'bounds_error')
    a.r(0x23,12,12,8);a.r(0x2B,12,12,9);a.branch(5,12,0,'bounds_error')
    # The transport and staging packet must never overwrite themselves.
    for lo,hi in protected_ranges():
        a.li(12,hi);a.r(0x2B,12,8,12);a.branch(4,12,0,f'outside_{lo:x}')
        a.r(0x2D,13,8,9);a.li(12,lo);a.r(0x2B,12,12,13);a.branch(5,12,0,'bounds_error')
        a.label(f'outside_{lo:x}')
    a.r(0,12,0,18,4)
    for reg in (10,11):
        a.r(0x2B,13,reg,12);a.branch(5,13,0,'bounds_error')
        a.r(0x2B,13,19,reg);a.branch(5,13,0,'bounds_error')
        a.r(0x23,13,19,reg);a.r(0x2B,13,13,9);a.branch(5,13,0,'bounds_error')
    a.li(12,PACKET);a.r(0x2D,10,10,12)
    a.label('compare');a.i(36,12,8,0);a.i(36,13,10,0);a.branch(5,12,13,'guard_error')
    a.addiu(8,8,1);a.addiu(10,10,1);a.addiu(9,9,-1);a.branch(5,9,0,'compare')
    a.addiu(20,20,16);a.addiu(21,21,1);a.branch(5,21,18,'validate_block')
    a.li(20,PACKET);a.move(21,0)
    a.label('write_block');a.lw(8,20);a.lw(9,20,4);a.lw(10,20,12)
    a.li(12,PACKET);a.r(0x2D,10,10,12)
    # Aligned word writes preserve normal EE self-modifying-code behavior.
    a.label('copy');a.r(0x25,12,8,10);a.i(12,12,12,3);a.branch(5,12,0,'byte')
    a.i(11,12,9,4);a.branch(5,12,0,'byte')
    a.lw(12,10);a.sw(12,8);a.addiu(8,8,4);a.addiu(10,10,4);a.addiu(9,9,-4);a.jump('copied')
    a.label('byte');a.i(36,12,10,0);a.i(40,12,8,0);a.addiu(8,8,1);a.addiu(10,10,1);a.addiu(9,9,-1)
    a.label('copied');a.branch(5,9,0,'copy')
    a.addiu(20,20,16);a.addiu(21,21,1);a.branch(5,21,18,'write_block')
    a.addiu(8,0,1);a.jump('ack')
    a.label('guard_error');a.addiu(8,0,100);a.jump('ack')
    a.label('bounds_error');a.addiu(8,0,101);a.jump('ack')
    a.label('scope_error');a.addiu(8,0,102)
    a.label('ack');a.sw(8,16,12);a.sw(17,16,8)
    a.label('done');restore(a);a.jr()
    result=a.finish();assert len(result)<GATE-CODE;return result



# The installed hook (jal GATE). Pollers compare only this word; code_pieces() stays
# uncached because the gate code depends on the build-time policy.TEAM_CAPACITY.
HOOK_WORD=struct.pack('<I',(3<<26)|(GATE>>2))


def previous_gate_images():
    """Gate images a prepared capture or preset may hold instead of the current gate; captured_transport and
    preset_cosmetics.transport_memory accept them and the transport rewrites them to gate_code(). In order,
    de-duplicated:
    - gate_code(heal_any_substate=False): this build's gate with the beta.35/36 phase-1 rewrite (sltiu < 4, not
      xori != 4; one word, GATE+0x220);
    - the gate beta.35/36 actually shipped for this adapter, frozen in dispatch_gate_history (sha256 pinned in
      test_native_preparation). Only that copy is exact once the gate changes elsewhere; a rebuild is not.
    Skipped for an adapter those releases did not ship."""
    import native_map
    import dispatch_gate_history as history
    images=[gate_code(heal_any_substate=False)]
    shipped=history.beta36_image(native_map.ADAPTER)
    if shipped is not None and shipped not in images:images.append(shipped)
    return tuple(images)


def code_pieces():
    native=elf_reader(elf_path(ROOT))[2]
    assert native(HOOK,8)==struct.pack('<2I',(3<<26)|(NATIVE>>2),0)
    return [(CODE,service_code()),(GATE,gate_code()),(HOOK,HOOK_WORD)]


def previous_service_images():
    """Exact old 1,024-record validator for authenticated capture upgrades."""
    return (service_code(legacy_block_limit=True),)



def captured_transport(ram):
    """A captured 128 MiB image holds this build's transport, or the same one with a previous gate image
    (previous_gate_images). Live checks keep installed(): the boot pnach is always current there."""
    for addr,data in code_pieces():
        accepted=(data,)
        if addr==CODE:
            accepted+=tuple(old+bytes(len(data)-len(old)) for old in previous_service_images() if len(old)<=len(data))
        if addr==GATE:
            # A shorter earlier gate is followed by the zeros of its reservation, as in preset_cosmetics.
            accepted+=tuple(old+bytes(len(data)-len(old)) for old in previous_gate_images() if len(old)<=len(data))
        if bytes(ram[addr:addr+len(data)]) not in accepted:return False
    return True



def upgrade_blocks(ram):
    """Upgrade only a fully authenticated, dormant captured transport.

    This is used when staging a rematch, before its emulator state is loaded;
    it must never be submitted through the transport to overwrite itself.
    """
    if not captured_transport(ram):raise ValueError('Captured native preparation service changed')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(CONTROL+4)!=u(CONTROL+8):raise ValueError('Captured native preparation transaction is pending')
    return [dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex())
            for p,data in code_pieces() if ram[p:p+len(data)]!=data]



def installed(p):
    return all(p.read(addr,len(data))==data for addr,data in code_pieces())


def encode(manifest):
    from fresh_team_trainer import merge_manifests
    blocks=merge_manifests(manifest)['blocks']
    if not 1<=len(blocks)<=MAX_BLOCKS:
        raise ValueError(f'Invalid native preparation block count: {len(blocks)} blocks for {CAPACITY} bytes of staging storage')
    # Plan the complete padded packet before allocating/publishing it. A bad
    # destination or oversized payload cannot leave a half-published request.
    records=[];size=RECORD_SIZE*len(blocks)
    for i,b in enumerate(blocks):
        old,new=bytes.fromhex(b['expected_hex']),bytes.fromhex(b['data_hex']);address=b['address']
        if address<0x30000:raise ValueError(f'Native preparation destination is outside patch memory: {address:08X}')
        if any(address<hi and lo<address+len(new) for lo,hi in protected_ranges()):
            raise ValueError(f'Native preparation destination overlaps protected memory: {address:08X}')
        size+=(-size)%4;before=size;size+=len(old)
        size+=(-size)%4;after=size;size+=len(new)
        records.append((address,old,new,before,after))
    if size>CAPACITY:
        raise ValueError(f'Native preparation packet exceeds reserved storage: {size} bytes required, {CAPACITY} available ({len(blocks)} blocks)')
    packet=bytearray(size)
    for i,(address,old,new,before,after) in enumerate(records):
        packet[before:before+len(old)]=old;packet[after:after+len(new)]=new
        struct.pack_into('<4I',packet,i*RECORD_SIZE,address,len(new),before,after)
    return bytes(packet),len(blocks)



def arm(p, *, include_single_ffa=False):
    if not installed(p):return False
    if p.read_u32(CONTROL)!=MAGIC:
        p.write(CONTROL,struct.pack('<16I',MAGIC,*([0]*15)))
    value=int(bool(include_single_ffa))
    if p.read_u32(INCLUDE_SINGLE_FFA)!=value:p.write_u32(INCLUDE_SINGLE_FFA,value)
    p.write_u32(CONTROL+48,1)
    return True


def disarm(p):
    """Withdraw auto-capture without releasing any in-flight combat transaction."""
    if p.read_u32(CONTROL)!=MAGIC or not installed(p):return False
    for address in (CONTROL+48, INCLUDE_SINGLE_FFA):
        if p.read_u32(address):p.write_u32(address,0)
    return True


def launcher(name='play'):
    """This installation's launcher for a next step in a message (localization.entry, group A):
    Play.cmd, Play.sh or the developer launcher. Plain 'Play' if the resolver cannot be used."""
    try:
        import localization
        return localization.entry(name) or 'Play'
    except Exception:  # noqa: BLE001 - a name inside a message only
        return 'Play'


# Group A's wording; player_errors translates it through its {play} template.
SERVICE_MISSING = 'The mod preparation service is not installed in this PCSX2. Close PCSX2, then start {play} again.'


class RunningTime:
    """Time a guest wait has spent while PCSX2 was running.

    A paused emulator runs no guest frames, so a wall-clock deadline fails a
    transaction that only waits for the player to resume PCSX2. The status is
    read at most every `interval` seconds, and again before the budget can run
    out; only an interval that starts and ends 'running' is charged. Any other
    status (shutdown) ends the wait at once. A reader without a status counts
    as running, exactly as before.
    """
    def __init__(self, p, seconds, clock=None, interval=.25):
        clock=clock or (lambda:time.monotonic())
        self.p,self.seconds,self.clock,self.interval=p,seconds,clock,interval
        self.elapsed=0.0;self.paused=False;self.at=clock();self.status='running'

    def _read(self):
        status=getattr(self.p,'status',None)
        status=status() if callable(status) else 'running'
        return status if status in ('running','paused','shutdown') else 'running'

    def expired(self):
        now=self.clock()
        if now-self.at<self.interval and not (self.status=='running' and self.elapsed+now-self.at>=self.seconds):
            return False
        status=self._read()
        if self.status==status=='running':self.elapsed+=now-self.at
        self.at,self.status=now,status
        self.paused=self.paused or status=='paused'
        return status!='running' and status!='paused' or self.elapsed>=self.seconds


def quiet(p, timeout=10):
    if not installed(p):raise ValueError(SERVICE_MISSING.format(play=launcher()))
    if p.read_u32(CONTROL)!=MAGIC:raise ValueError('Native preparation service is not armed')
    p.write_u32(CONTROL+24,p.read_u32(A(0x2FEB14)));p.write_u32(CONTROL+16,1)
    # Only running time counts: a player who pauses PCSX2 here is waited for.
    budget=RunningTime(p,timeout)
    while True:
        if p.read_u32(CONTROL+20)==1:return
        if budget.expired():break
        time.sleep(.02)
    raise TimeoutError(f'The game did not acknowledge its combat hold within {timeout} s of running time')


def resume(p):
    p.write_u32(CONTROL+16,0)


def apply(p,manifest,timeout=15):
    if p.read_u32(CONTROL+20)!=1 or p.read_u32(CONTROL+16)!=1:
        raise ValueError('Patch installation requires an acknowledged combat hold')
    packet,count=encode(manifest)
    req=p.read_u32(CONTROL+4);ack=p.read_u32(CONTROL+8)
    if req!=ack:raise ValueError('A native preparation transaction is already pending')
    p.write(PACKET,packet)
    p.write(CONTROL+28,struct.pack('<3I',count,len(packet),0));p.write_u32(CONTROL+12,0)
    request=(req+1)&0xFFFFFFFF or 1;p.write_u32(CONTROL+4,request)
    # The request is written once; a pause only extends the wait (running time).
    budget=RunningTime(p,timeout)
    while True:
        if p.read_u32(CONTROL+8)==request:
            status=p.read_u32(CONTROL+12)
            if status!=1:raise RuntimeError(f'Native patch rejected: status {status}, block {p.read_u32(CONTROL+36)}')
            return
        if budget.expired():break
        time.sleep(.02)
    raise TimeoutError(f'Native preparation transaction was not acknowledged within {timeout} s of running time; match remains held')


def read_ram(p):
    """Batch aligned EE reads without constructing 16 million Python spans."""
    import numpy as np
    size=0x8000000;batch=32768;stride=batch*8;result=bytearray(size)
    commands=np.empty(batch,dtype=[('op','u1'),('address','<u4')]);commands['op']=3
    relative=np.arange(batch,dtype=np.uint32)*8
    for start in range(0,size,stride):
        commands['address']=relative+start
        result[start:start+stride]=p._exchange(commands.tobytes(),stride)
    return bytes(result)
