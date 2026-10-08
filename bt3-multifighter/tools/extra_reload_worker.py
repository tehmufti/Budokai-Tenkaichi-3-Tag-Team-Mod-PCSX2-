"""Autopilot-facing extra costume worker using the acknowledged guest hold.

The caller supplies its existing PINE client and serializes calls with other
preparation work. This module creates no connection, process, thread, UI input
or savestate operation. A job is claimed only after quiet is acknowledged.
Failures leave quiet owned by the caller for explicit checkpoint recovery.
"""
from native_map import A
import struct
import time

import extra_reload_requests as requests
import extra_reload_quiet as runner
import extra_reload_service as io
import extra_reload_stage as stage
import extra_reload_commit as commit
import extra_reload_retire as retire
import extra_reload_aux_worker as auxiliary
import native_preparation as native
import lazy_ram
import extra_reload_preload as preload
import extra_reload_heap as heap
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy

SCENE_FLAGS=A(0x3337B8)
SCENE_RELOAD_MASK=0x3800
# Bounds for the background transformation window. Every guest bound is
# strictly shorter than the host bound that follows it, so the host never
# decides while the guest runner is still armed:
#   guest idle wait  30 gate calls  < host hold-A' wait 40 presentation frames
#   guest IO deadline450 poll calls < host form budget 900 active frames
BACKGROUND_IO_CALLS=450
BACKGROUND_START_FRAMES=40
BACKGROUND_START_SECONDS=6.0
# Transient background refusals: the claim is simply released and retried.
BACKGROUND_RETRY=(112,130,131)


def u(ram,p):return struct.unpack_from('<I',ram,p)[0]


def loader_busy(ram):
    """True while any native loader or task work could take our record/buffers.

    The guest start gate tests exactly these words, so a hold taken while they
    are set would sit waiting for a start the guest refuses to make.
    """
    if (u(ram,runner.LOADER_STATE) or u(ram,runner.LOADER_HANDLE) or
            u(ram,runner.LOADER_PENDING)&0xFFFF):return True
    fifo=u(ram,runner.TASK_FIFO)
    if not 0x100000<=fifo<=0x08000000-32 or fifo%4:return False
    return bool(u(ram,fifo+12))


def loader_busy_live(p):
    if (p.read_u32(runner.LOADER_STATE) or p.read_u32(runner.LOADER_HANDLE) or
            p.read_u32(runner.LOADER_PENDING)&0xFFFF):return True
    fifo=p.read_u32(runner.TASK_FIFO)
    if not 0x100000<=fifo<=0x08000000-32 or fifo%4:return False
    return bool(p.read_u32(fifo+12))


def poll_delay(worker,ordinary):
    """Finish an acknowledged form promptly; keep the idle watcher inexpensive.

    Native forms hold combat at their commit frame. A normal 150/200ms watcher
    sleep was added directly to every such hold, regardless of loader speed.
    An unheld background disc read lasts ~1.7s with the match running, so it
    gets a relaxed cadence instead of ~170 connect/preflight cycles.
    """
    if worker is None or worker.form_job is None:return ordinary
    return min(ordinary,.05 if getattr(worker,'form_phase',None)=='io' else .01)


# The native resource registry: twelve 56-byte records at pool+REGISTRY_OFFSET.
REGISTRY_BYTES=12*56


def free_record(records):
    """True when the record io would take (the first free one) is clean.

    Mirrors the preload free_scan exactly: it takes the FIRST record whose +48
    bit0 is clear and fails (status130, after the claim) if its buffers remain.
    """
    for i in range(12):
        if not u(records,56*i+48)&1:
            return not any(u(records,56*i+off) for off in (0,16,32))
    return False


def largest_free_block(ram):
    """Largest free heap1 block's header size (the guest admission compares
    exactly this word with its budget), or0 if the bounded chain does not validate."""
    at,largest=heap.START,0
    for _ in range(heap.MAX_BLOCKS):
        if u(ram,at)!=0x53484254:return 0
        size=u(ram,at+16)
        if size<32 or size%4 or at+size>heap.STOP:return 0
        if not u(ram,at+4):largest=max(largest,size)
        at+=size
        if at==heap.STOP:return largest
    return 0


def capacity_shortage(ram):
    """Why a NEW reload could not complete now, or None.

    io and stage check these only after the claim and the guest hold, and a
    failure there keeps the match held. Every completed reload keeps its old
    bundle, record and texture group, so at eight or ten fighters they can run
    out; the request then simply waits and the fighter keeps its costume.
    """
    pool=u(ram,preload.REGISTRY_GLOBAL)
    if not 0x100000<=pool<=len(ram)-preload.REGISTRY_OFFSET-REGISTRY_BYTES:return 'the model pool is unreadable'
    registry=pool+preload.REGISTRY_OFFSET
    if not free_record(ram[registry:registry+REGISTRY_BYTES]):return 'no free resource record'
    models=[u(ram,runner.core.MODELS+4*i) for i in range(12)]
    occupied=sum(1 for m in models if 0x100000<=m<=len(ram)-8 and u(ram,m+4))
    if occupied>=12 or not u(ram,pool+69128):return 'no spare model slot'
    # The two-spare policy reads the raw mask, exactly as the guest form
    # admission does. Staging also needs one group no live model uses: a
    # transient's destructor can clear a live group's bit, which staging
    # re-marks (extra_reload_stage.texture_groups).
    if ((u(ram,pool+439156)&0x7FFF).bit_count()>=13 or
            stage.texture_groups(ram)['group'] is None):return 'no spare texture group'
    # Host-side: the real per-file ceiling, whatever the installed build.
    if largest_free_block(ram)<heap.NEED:return 'not enough free memory'
    return None


def word_block(ram,p,value):
    return dict(address=p,expected_hex=bytes(ram[p:p+4]).hex(),data_hex=struct.pack('<I',value).hex())


def install_memory(ram,source='<captured-ready>',enabled=False,forms=False):
    capture=requests.build_memory(ram,source);quiet=runner.build_memory(ram)
    if type(enabled) is not bool or type(forms) is not bool:raise ValueError('Capture enabled and forms must be Boolean')
    if enabled:
        for block in capture['blocks']:
            if block['address']==requests.CONTROL:
                data=bytearray.fromhex(block['data_hex']);struct.pack_into('<I',data,0,1);block['data_hex']=data.hex()
    capture['blocks']+=quiet['blocks']
    capture.update(status='DORMANT AUTOMATIC COSTUME REQUEST SERVICE',quiet_entry=runner.ENTRY)
    if forms:
        import extra_reload_forms as form_module
        from fresh_team_trainer import compose_manifests
        base=capture
        capture=compose_manifests(ram,[lambda _:base,lambda r:form_module.build_memory(r,source)])
        capture.update(control=requests.CONTROL,quiet_entry=runner.ENTRY,forms=True)
    return capture


def candidate(ram,statuses=(1,),specific=None):
    """Read a complete, still-current pending row; claim requires later quiet."""
    # A new costume/form transaction must not freeze the arena's native effect
    # clock or borrow its loader. Already-claimed form commits must still finish
    # and release their own quiet hold if the arena acquired ownership meanwhile.
    if statuses==(1,) and u(ram,SCENE_FLAGS)&SCENE_RELOAD_MASK:return None
    # Only a new claim needs the room; a claimed form (statuses (4,)) has
    # already used it, and refusing it now would hold the match.
    if statuses==(1,) and capacity_shortage(ram):return None
    # The background start is gated on an idle native loader. Refusing a NEW
    # scan keeps hold A' from being taken in a state the guest will not start
    # in; the recheck under an existing hold (specific=) must not add a veto,
    # because Cell hands its already-published form job straight through it.
    if statuses==(1,) and specific is None and loader_busy(ram):return None
    count=u(ram,requests.CONTROL+8);manager=u(ram,requests.CONTROL+4)
    if count not in ACTOR_COUNTS or u(ram,requests.CONTROL)!=1:return None
    if u(ram,runner.core.ACTORS)!=manager or u(ram,runner.core.MODE)!=1 or u(ram,runner.core.MODE+8)!=manager:return None
    if specific is not None and not 2<=specific<count:return None
    for physical in (range(2,count) if specific is None else (specific,)):
        at=requests.RECORDS+(physical-2)*requests.STRIDE;values=struct.unpack_from('<16I',ram,at)
        generation,status,actor,mid,model,character,costume,damaged=values[:8]
        if status not in statuses or not generation:continue
        is_form=values[14]==1;action=values[15] if is_form else 11
        if values[14] not in (0,1) or (is_form and action not in range(236,243)):continue
        if not (0x100000<=actor<=0x8000000-0x1600 and 0x100000<=model<=0x8000000-0x1670 and mid<12):continue
        if (u(ram,runner.core.POINTERS+4*physical)!=actor or u(ram,actor)!=physical or
                u(ram,actor+12)!=mid or u(ram,runner.core.MODELS+4*mid)!=model or
                u(ram,model+16)!=mid or u(ram,model+20)!=values[12] or
                values[11]!=physical or costume>3 or damaged not in ((0,1) if is_form else (1,))):continue
        if is_form:
            if auxiliary.blocks_form(ram,physical,actor):continue
            import extra_reload_forms
            if (not u(ram,extra_reload_forms.CONTROL) or not u(ram,extra_reload_forms.FORM_ENABLE) or
                    u(ram,actor+0x12D0)!=character or u(ram,actor+0x12D4)!=costume or
                    u(ram,actor+0x12E0)!=damaged):continue
        elif u(ram,model+12)!=character:continue
        if any(x not in (0xFFFFFFFF,character) for x in values[8:11]):continue
        if u(ram,actor+0x948)!=action or u(ram,runner.core.PAIR+4):continue
        # These two only gate a NEW claim. A claimed form (statuses (4,)) is
        # committed under the guest hold, where neither can clear - the hold
        # stops the native reload queue and the throw clock - and its commit
        # borrows no disc IO; refusing it there would keep the match held.
        if statuses==(1,):
            # Native throws can keep the other participant bound after this
            # owner has returned idle. Wait for the reciprocal record to expire.
            if u(ram,0x0778F100+4*physical):continue
            # Let any native leader reload finish before borrowing disc IO.
            if any(u(ram,manager+off) for off in (600,612,628)) or u(ram,manager+604)!=u(ram,manager+608):continue
        return dict(row=at,generation=generation,physical=physical,actor=actor,model=model,
                    model_id=mid,character=character,costume=costume,damaged=bool(damaged),
                    old_resource=values[12],manager=manager,form=is_form,owner_action=action)
    return None


def room_hint(p):
    """Cheap reads of the capacity_shortage counters, all but the heap walk."""
    pool=p.read_u32(preload.REGISTRY_GLOBAL)
    if not 0x100000<=pool<=0x08000000-preload.REGISTRY_OFFSET-REGISTRY_BYTES:return False
    if not free_record(p.read(pool+preload.REGISTRY_OFFSET,REGISTRY_BYTES)):return False
    if not p.read_u32(pool+69128) or (p.read_u32(pool+439156)&0x7FFF).bit_count()>=13:return False
    return True


def pending_hint(p,rows):
    """Bounded reads while a pending owner remains in an ultimate/cutscene."""
    if p.read_u32(SCENE_FLAGS)&SCENE_RELOAD_MASK:return False
    manager=p.read_u32(requests.CONTROL+4);count=p.read_u32(requests.CONTROL+8)
    if count not in ACTOR_COUNTS or not 0x100000<=manager<0x08000000-640:return False
    if (p.read_u32(requests.CONTROL)!=1 or p.read_u32(runner.core.ACTORS)!=manager or
            p.read_u32(runner.core.MODE)!=1 or p.read_u32(runner.core.MODE+8)!=manager or
            p.read_u32(runner.core.PAIR+4)):
        return False
    if any(p.read_u32(manager+off) for off in (600,612,628)) or p.read_u32(manager+604)!=p.read_u32(manager+608):return False
    if loader_busy_live(p):return False
    if not room_hint(p):return False
    for i in range(min(count-2,len(rows)//requests.STRIDE)):
        status,actor=struct.unpack_from('<2I',rows,i*requests.STRIDE+4)
        if status!=1 or not 0x100000<=actor<=0x08000000-0x1600:continue
        kind,action=struct.unpack_from('<2I',rows,i*requests.STRIDE+56)
        if kind not in (0,1):continue
        action=action if kind else 11
        if kind and action not in range(236,243):continue
        if (p.read_u32(runner.core.POINTERS+4*(i+2))==actor and p.read_u32(actor)==i+2 and
                p.read_u32(actor+0x948)==action and not p.read_u32(0x0778F100+4*(i+2))):
            return True
    return False


class Worker:
    """A serial, caller-owned worker; poll only after a captured match is active."""
    def __init__(self,progress=None,read_ram=native.read_ram,apply=native.apply,
                 quiet=native.quiet,resume=native.resume,clock=time.monotonic,sleep=time.sleep,cell_auxiliary=True):
        if type(cell_auxiliary)is not bool:raise ValueError('Cell auxiliary preference must be Boolean')
        self.cell_auxiliary=cell_auxiliary
        self.progress=progress or (lambda message:None)
        self.read_ram=read_ram;self.apply=apply;self.quiet=quiet;self.resume=resume
        self.clock=clock;self.sleep=sleep;self.owned={};self.resources={};self.retained={};self.retirement_notes=[]
        self.active=False;self.failure=None;self.forms=False;self.form_job=None;self.form_frame=0
        self.form_elapsed=0;self.form_paused=False;self.waiting=None
        # 'io' while the disc read runs unheld, 'commit' once the row is staged
        # and the native ACK is awaited (today's only phase).
        self.form_phase=None
        # Whether this prepared match carries the background runner and the
        # gate that calls it. Absent -> today's fully held IO path, unchanged.
        self.background=False
        # Capacity the adopted match's guest code was built for; every stage
        # rebuilt for it emits the same build (release checkpoints carry 3).
        self.capacity=policy.TEAM_CAPACITY
        # A full-world read that found no claimable job is not repeated for a
        # second: a request can wait on heap space, which only that read shows.
        self.retry_at=0
        # What the last full read found missing, for waiting_reason.
        self.shortage=None
        self._ram_buffer=None;self._analysis_buffer=None
        self.timings=[];self._held_since=None

    def _build(self,name,builder,*args,**kwargs):
        started=time.perf_counter()
        try:return builder(*args,**kwargs)
        finally:self.timings.append((name+' build',time.perf_counter()-started))

    def _release(self,p):
        self.resume(p)
        if self._held_since is not None:
            total=time.perf_counter()-self._held_since
            detail=', '.join(f'{name} {seconds:.3f}s' for name,seconds in self.timings)
            self.progress(f'Extra reload timing: combat hold {total:.3f}s; {detail}')
            self._held_since=None;self.timings=[]

    def attach(self,p):
        """Adopt exact preinstalled dormant code; no hold, UI or battle reset."""
        for capacity in (policy.TEAM_CAPACITY,policy.LEGACY_TEAM_CAPACITY):
            with policy.building_for(capacity):
                forms,expected=self._service(p)
                # The optional pair is emitted for the SAME capacity, so a
                # three-a-side checkpoint reports absence, never a mismatch.
                background=self._background_service(p)
            if all(p.read(at,len(data))==data for at,data in expected):break
        else:
            raise ValueError('Prepared match is missing the reviewed extra reload service')
        self.capacity=capacity;self.forms=forms;self.background=background;self.pieces=expected
        import extra_reload_forms as form_module
        manager=p.read_u32(runner.core.ACTORS);count=p.read_u32(requests.CONTROL+8)
        if (count not in ACTOR_COUNTS or p.read_u32(requests.CONTROL+4)!=manager or
                p.read_u32(runner.core.MODE)!=1 or p.read_u32(runner.core.MODE+8)!=manager or
                p.read_u32(runner.core.MODE+4)!=count or p.read_u32(runner.core.MODE+12)!=count or
                p.read_u32(runner.CONTROL)!=runner.MAGIC):
            raise ValueError('Extra reload service belongs to another match')
        if p.read_u32(runner.CONTROL+4)!=p.read_u32(runner.CONTROL+8):
            raise ValueError('Cannot attach while an extra reload job is already running')
        if self.background and p.read_u32(runner.BG_CONTROL+4)!=p.read_u32(runner.BG_CONTROL+8):
            raise ValueError('Restart this prepared match before reattaching a background reload worker')
        if any(p.read_u32(module.CONTROL+4) for module in (io,stage,commit,retire)):
            raise ValueError('Restart this prepared match before reattaching a completed reload worker')
        if not native.arm(p):raise ValueError('The fighter update service is not installed in this PCSX2. Close PCSX2, '
                                              'then start {play} again.'.format(play=native.launcher()))
        if self.forms:
            if tuple(p.read_u32(form_module.CONTROL+off) for off in (4,8))!=(manager,count):
                raise ValueError('Ordinary form service belongs to another match')
            p.write_u32(form_module.CONTROL,1);p.write_u32(form_module.FORM_ENABLE,1)
            auxiliary.arm(p,self.cell_auxiliary)
        p.write_u32(requests.CONTROL,1);self.active=True;self.failure=None;return self

    def installed(self,p):
        """The reload service this worker attached to is still this match's: the MODE and
        service words attach checked and the exact program bytes it verified. Reads only (no
        claim, no write); the watcher checks a worker it parked for a moment out of combat
        before it reuses it (match F1)."""
        manager=p.read_u32(runner.core.ACTORS);count=p.read_u32(requests.CONTROL+8)
        if (count not in ACTOR_COUNTS or p.read_u32(requests.CONTROL+4)!=manager or
                p.read_u32(runner.core.MODE)!=1 or p.read_u32(runner.core.MODE+8)!=manager or
                p.read_u32(runner.core.MODE+4)!=count or p.read_u32(runner.core.MODE+12)!=count or
                p.read_u32(runner.CONTROL)!=runner.MAGIC):return False
        return all(p.read(at,len(data))==data for at,data in getattr(self,'pieces',()))

    def _background_service(self,p):
        """Is the optional unheld IO driver installed for THIS emission?

        Both halves are required: the runner cave plus its armed control block
        (from the prepared match) and the current dispatch gate (from the boot
        pnach), which is what actually calls it. Either missing means a state
        prepared before this change, which keeps today's fully held IO path.
        """
        try:
            body=runner.background_code();gate=native.gate_code()
            return (p.read(runner.BACKGROUND,len(body))==body and
                    p.read_u32(runner.BG_CONTROL)==runner.BG_MAGIC and
                    p.read(native.GATE,len(gate))==gate)
        except Exception:
            return False

    def _service(self,p):
        """The dormant reload service pieces for the build being emitted."""
        import extra_reload_forms as form_module
        form_hook=struct.pack('<2I',(2<<26)|(form_module.PUSH>>2),0)
        forms=p.read(requests.previous.PUSH_HOOK,8)==form_hook
        expected=((requests.CODE,requests.payload()),(runner.ENTRY,runner.code()),
                  (requests.previous.PUSH_HOOK,form_hook if forms else struct.pack('<2I',(2<<26)|(requests.CODE>>2),0)),
                  (requests.previous.PUSH,requests.previous.push_code()))
        if forms:
            import extra_reload_form_contacts as contacts
            import extra_cell_absorption
            expected += tuple(extra_cell_absorption.pieces())
            expected += tuple(form_module.heap.pieces())
            expected += tuple((at,form_module.heap.NATIVE(at,size)) for at,size in form_module.heap.HELPERS)
            expected += tuple(contacts.pieces())
            expected += ((contacts.HOOK+8,contacts.leader.protected_code()[8:]),)
            expected += ((form_module.PUSH,form_module.push_code()),(form_module.SIDE,form_module.side_code()))
            expected += ((A(0x203484),struct.pack('<I',(3<<26)|(form_module.SIDE>>2))),)
            for (entry,cave,_),new,old in zip(form_module.ordinary.ENTRIES,
                    (form_module.ELIGIBILITY,form_module.BEGIN),(form_module.OLD_ELIGIBILITY,form_module.OLD_BEGIN)):
                expected += ((new,form_module.admission(entry,new,old)),
                             (old,form_module.safety.owned_code(entry,old,2,form_module.NATIVE(entry,8))),
                             (cave+0x200,struct.pack('<2I',(2<<26)|(new>>2),0)))
            expected += tuple((base,form_module.handshake(kind)) for kind,base in
                              (('ready',form_module.READY),('ack',form_module.ACK),('finish',form_module.FINISH)))
            expected += tuple((entry,struct.pack('<2I',(2<<26)|(base>>2),0)) for entry,base in
                              ((A(0x1D6360),form_module.READY),(A(0x1D63D8),form_module.ACK),(A(0x1D6408),form_module.FINISH)))
            for entry,old in ((A(0x1D63D8),form_module.OLD_ACK),(A(0x1D6408),form_module.OLD_FINISH)):
                expected += ((old,form_module.NATIVE(entry,8)+struct.pack('<2I',(2<<26)|((entry+8)>>2),0)),)
            expected += ((form_module.OLD_READY,struct.pack('<2I',(2<<26)|(requests.previous.READY>>2),0)),)
        return forms,expected

    def install(self,p,forms=False):
        if self.active:raise RuntimeError('Extra reload worker already owns a captured match')
        was_quiet=p.read_u32(native.CONTROL+16)==1
        if not was_quiet:self.quiet(p)
        ram=self.read_ram(p);self.capacity=policy.installed_capacity(ram)
        with policy.building_for(self.capacity):manifest=install_memory(ram,forms=forms)
        self.apply(p,manifest)
        with policy.building_for(self.capacity):self.background=self._background_service(p)
        p.write_u32(requests.CONTROL,1);self.active=True;self.forms=forms
        if forms:
            import extra_reload_forms
            p.write_u32(extra_reload_forms.CONTROL,1);p.write_u32(extra_reload_forms.FORM_ENABLE,1)
            auxiliary.arm(p,self.cell_auxiliary)
        if not was_quiet:self.resume(p)
        return manifest

    def _analysis_view(self,ram):
        """Reset only this worker's completed diagnostic code for regeneration.

        Old models/resources remain registered. Their capacity is independently
        counted by the next stage. Unrecognized or modified code fails closed.
        """
        overrides={}
        for name,manifest in self.owned.items():
            module={'io':io,'stage':stage,'commit':commit,'retire':retire}[name]
            if u(ram,module.CONTROL+4)!=5:raise RuntimeError('A prior reload did not complete')
            for block in manifest['blocks']:
                p=block['address'];new=bytes.fromhex(block['data_hex']);old=bytes.fromhex(block.get('restore_hex',block['expected_hex']))
                data_region=module.CONTROL<=p<module.END
                if not data_region and ram[p:p+len(new)]!=new:
                    raise RuntimeError(f'Owned reload code changed at {p:08X}')
                overrides[p]=old
        if isinstance(ram,lazy_ram.LazyRam):
            if not overrides:return ram
            self._analysis_buffer=ram.view(overrides,reuse=self._analysis_buffer)
            return self._analysis_buffer
        view=bytearray(ram)
        for p,old in overrides.items():view[p:p+len(old)]=old
        return view

    def _snapshot(self,p):
        """Fetch only bytes inspected by the current reload stage.

        Every call expires the previous view: a completed guest stage invalidates all
        prior pointers and metadata. The existing quiet recheck and guest-side
        identity guards remain the authority for writes. Injected snapshot
        readers retain their original behavior for diagnostics and tests.
        """
        if self.read_ram is native.read_ram:
            if self._analysis_buffer is not None:self._analysis_buffer.invalidate()
            if self._ram_buffer is None:
                self._ram_buffer=lazy_ram.LazyRam(p)
            else:
                self._ram_buffer.invalidate();self._ram_buffer.client=p
            return self._ram_buffer
        return self.read_ram(p)

    def _prepare_blocks(self,name,ram,manifest):
        # Variable-size regenerated bodies can shrink. Restore every byte of
        # the prior owned union not replaced by a new block; otherwise an old
        # executable tail would survive and lose its ownership receipt.
        covered=sorted((b['address'],b['address']+len(bytes.fromhex(b['data_hex']))) for b in manifest['blocks'])
        for previous in self.owned.get(name,{}).get('blocks',[]):
            begin=previous['address'];original=bytes.fromhex(previous.get('restore_hex',previous['expected_hex']))
            fragments=[(begin,begin+len(original))]
            for lo,hi in covered:
                next_fragments=[]
                for left,right in fragments:
                    if hi<=left or lo>=right:next_fragments.append((left,right))
                    else:
                        if left<lo:next_fragments.append((left,lo))
                        if hi<right:next_fragments.append((hi,right))
                fragments=next_fragments
            for left,right in fragments:
                restore=original[left-begin:right-begin].hex()
                manifest['blocks'].append(dict(address=left,expected_hex=restore,data_hex=restore))
        # Builders inspect an explicitly restored analysis view. Native packet
        # guards always compare against the actual current EE bytes instead.
        for block in manifest['blocks']:
            at=block['address'];n=len(bytes.fromhex(block['data_hex']))
            block['restore_hex']=block['expected_hex']
            block['expected_hex']=ram[at:at+n].hex()

    def _install_stage(self,p,name,ram,manifest,job):
        self._prepare_blocks(name,ram,manifest)
        control=manifest['control'];entry=manifest['entry']
        if (entry,control) not in runner.TARGETS:raise ValueError('Unexpected reload job entry')
        sequence=p.read_u32(runner.CONTROL+4)
        if sequence!=p.read_u32(runner.CONTROL+8):raise RuntimeError('Reload runner already busy')
        # Publish code, enabled flag and runner request in ONE compare-before-
        # write native transaction. Formerly installation waited a whole guest
        # update, then five host writes armed a second update. Nothing can run
        # before all guards pass and the complete stage is installed.
        control_block=next((b for b in manifest['blocks'] if b['address']==control),None)
        if control_block is None:raise ValueError('Reload stage has no owned control block')
        data=bytearray.fromhex(control_block['data_hex']);struct.pack_into('<I',data,0,1)
        control_block['data_hex']=data.hex()
        request=(sequence+1)&0xFFFFFFFF or 1
        publication=[(runner.CONTROL+16,struct.pack('<6I',job['manager'],entry,control,0,job['physical'],job.get('owner_action',11))),
                     (runner.CONTROL+12,bytes(4)),(runner.CONTROL+8,struct.pack('<I',sequence)),
                     (runner.CONTROL+4,struct.pack('<I',request))]
        transaction=dict(manifest,blocks=manifest['blocks']+[
            dict(address=at,expected_hex=(struct.pack('<I',sequence) if at in
                 (runner.CONTROL+4,runner.CONTROL+8) else p.read(at,len(data))).hex(),
                 data_hex=data.hex()) for at,data in publication])
        before=time.perf_counter();self.apply(p,transaction);self.owned[name]=manifest
        self.timings.append((name+' publish',time.perf_counter()-before));before=time.perf_counter()
        # Running time only: a PCSX2 paused during the stage is waited for.
        budget=native.RunningTime(p,90,clock=self.clock)
        while True:
            if p.read_u32(runner.CONTROL+8)==request:
                status=p.read_u32(runner.CONTROL+12)
                if status!=5 or p.read_u32(control+4)!=5:
                    raise RuntimeError(f'Extra reload {name} failed with status {status}; match remains held')
                self.timings.append((name+' guest',time.perf_counter()-before))
                return
            if budget.expired():break
            self.sleep(.02)
        raise TimeoutError(f'Extra reload {name} did not finish within 90 s of running time; match remains held')

    def waiting_reason(self,p):
        """Why a published request is not being claimed, in one short phrase.

        A fighter whose transformation never starts otherwise looks like an AI
        that simply never decides. These are the host-visible vetoes, read as a
        handful of words and reported only when the answer changes.
        """
        import extra_reload_forms as form_module
        scene=p.read_u32(SCENE_FLAGS)
        manager=p.read_u32(requests.CONTROL+4)
        if scene&SCENE_RELOAD_MASK:return 'the arena owns the loader'
        if p.read_u32(native.CONTROL+16):return 'another preparation holds combat'
        if any(p.read_u32(manager+off) for off in (600,612,628)) or p.read_u32(manager+604)!=p.read_u32(manager+608):
            return 'a native leader reload is in flight'
        if loader_busy_live(p):return 'the native loader is still busy'
        if p.read_u32(runner.core.PAIR+4):return 'the private AI is aliased'
        if p.read_u32(requests.CONTROL)!=1:return 'the request service is disabled'
        pool=p.read_u32(preload.REGISTRY_GLOBAL)
        if 0x100000<=pool<=0x08000000-preload.REGISTRY_OFFSET-REGISTRY_BYTES:
            if not free_record(p.read(pool+preload.REGISTRY_OFFSET,REGISTRY_BYTES)):return 'no free resource record'
            if not p.read_u32(pool+69128):return 'no spare model slot'
            if (p.read_u32(pool+439156)&0x7FFF).bit_count()>=13:return 'no spare texture group'
        if self.forms and not p.read_u32(form_module.FORM_ENABLE):return 'ordinary forms are disabled'
        refusals,reason,actor=struct.unpack('<3I',p.read(form_module.CONTROL+form_module.REFUSALS,12))
        if refusals:
            names={1:'a fusion reservation',2:'native model storage',3:'texture groups',
                   4:'free resource records',5:'heap space'}
            return f'{refusals} command(s) refused, last for want of {names.get(reason,reason)}'
        if self.shortage:return self.shortage
        return 'its owner is not idle in a transformation action'

    def poll(self,p):
        with policy.building_for(self.capacity),lazy_ram.patched():return self._poll(p)

    def _poll(self,p):
        if not self.active or self.failure:return False
        if self.form_job is not None:
            if self.form_phase=='io':return self._background_form(p)
            result=self._finish_form(p)
            if self.form_job is None:self.form_phase=None
            return result
        # Cheap host reads detect work; full world validation follows under the
        # guest hold. Avoid large RAM snapshots during ordinary combat.
        if p.read_u32(native.CONTROL+16):return False
        auxiliary_result=auxiliary.poll(self,p)
        if auxiliary_result is not None:return auxiliary_result
        rows=p.read(requests.RECORDS,requests.ROWS*requests.STRIDE)
        if not any(struct.unpack_from('<I',rows,i*requests.STRIDE+4)[0]==1 for i in range(requests.ROWS)):
            self.waiting=None;return False
        if not pending_hint(p,rows):return self._waiting(p)
        if self.clock()<self.retry_at:return self._waiting(p)
        ram=self._snapshot(p);job=candidate(ram)
        if job is None:
            self.shortage=capacity_shortage(ram)
            self.retry_at=self.clock()+1.0;return self._waiting(p)
        self.shortage=None
        self.waiting=None
        # Allocate the reusable analysis workspace before taking combat's
        # hold. The first reload has nothing to restore; later ones do.
        if isinstance(ram,lazy_ram.LazyRam) and self.owned and self._analysis_buffer is None:
            self._analysis_buffer=ram.view({})
        self.quiet(p)
        self._held_since=time.perf_counter();self.timings=[]
        return self._load_job(p,job)

    def _load_job(self,p,job):
        """Run one current fighter job under our already acknowledged hold.

        Cell can enter here immediately after its auxiliary publication, so no
        other actor consumes the admitted form capacity between the two loads.
        """
        try:
            ram=self._snapshot(p);current=candidate(ram,specific=job['physical'])
            if current!=job:
                self._release(p);return False
            self.progress('Loading transformation' if job['form'] else 'Updating fighter costume')
            # Costumes and Cell's action-239 pair keep today's fully held path:
            # the auxiliary mesh IO and the form share one serial IO workspace
            # and one capacity reservation across both loads.
            if self.background and job['form'] and job['owner_action']!=239:
                return self._start_background(p,ram,job)
            claim=dict(blocks=[word_block(ram,job['row']+4,2)])
            self.apply(p,claim)
            view=self._analysis_view(ram)
            manifest=self._build('io',io.build_memory,view,job['physical'],job['character'],job['costume'],job['damaged'],quiet=True,allow_forms=self.forms)
            self._install_stage(p,'io',ram,manifest,job)
            ram=self._snapshot(p);view=self._analysis_view_for(ram,('stage','commit'))
            self._install_stage(p,'stage',ram,self._build('stage',stage.build_memory,view,quiet=True,allow_forms=self.forms),job)
            self._group_note(p)
            if job['form']:
                ram=self._snapshot(p)
                self.apply(p,dict(blocks=[word_block(ram,job['row']+4,3)]))
                self.form_job=job;self.form_phase='commit';self.form_frame=p.read_u32(native.CONTROL+40)
                self.form_elapsed=0;self.form_paused=False
                self.progress('Transformation loaded');self._release(p);return False
            ram=self._snapshot(p);view=self._analysis_view_for(ram,('commit',))
            self._install_stage(p,'commit',ram,self._build('commit',commit.build_memory,view,quiet=True,retire_staged=True),job)
            ram=self._snapshot(p)
            if u(ram,commit.AI_META)!=5 or u(ram,commit.CONTROL+36)!=1 or u(ram,job['model']+12)!=job['character']:
                raise RuntimeError('Extra reload final identity check failed; match remains held')
            ram=self._complete_resources(p,ram,job)
            self.apply(p,dict(blocks=[word_block(ram,job['row']+52,5),word_block(ram,job['row']+4,5)]))
            self.progress('Fighter costume updated');self._release(p);return True
        except Exception as exc:
            import player_errors;self.failure=player_errors.short(exc);self.progress(self.failure);raise

    def _waiting(self,p):
        """Report a stalled request once per distinct reason, then stay quiet."""
        try:reason=self.waiting_reason(p)
        except Exception:return False
        if reason!=self.waiting:
            self.waiting=reason
            self.progress(f'Waiting to load a transformation: {reason}')
        return False

    def _group_note(self,p):
        """Log when staging re-marked a live model's texture group (TTM-MATCH-08 cause) or missed its choice."""
        repaired,chosen,staged=struct.unpack('<3I',p.read(stage.CONTROL+80,12))
        if repaired or staged!=chosen:
            live=[g for g in range(stage.GROUPS) if repaired>>g&1]
            self.progress(f'Texture group check: re-marked live group(s) {live}; staged on {staged}, chosen {chosen}')

    # ---- unheld background transformation IO -----------------------------
    #
    # Hold A' publishes the claim, the IO body and the background request in
    # ONE guarded native transaction and releases as soon as the guest has
    # reserved its record and buffers. The ~1.7s disc read then runs with
    # combat dispatching normally. A second short host hold stages the hidden
    # model and writes row+4=3, after which _finish_form and hold B are exactly
    # today's code.

    def _restore_blocks(self,ram,name):
        """Put one owned workspace back to the bytes its builder was shown."""
        manifest=self.owned.get(name)
        if manifest is None:return []
        blocks=[]
        for block in manifest['blocks']:
            at=block['address'];old=bytes.fromhex(block.get('restore_hex',block['expected_hex']))
            blocks.append(dict(address=at,expected_hex=bytes(ram[at:at+len(old)]).hex(),data_hex=old.hex()))
        return blocks

    def _background_clear(self,ram):
        """Disarm the background runner; the request word is written last."""
        return [word_block(ram,runner.BG_CONTROL+12,0),
                word_block(ram,runner.BG_CONTROL+8,0),
                word_block(ram,runner.BG_CONTROL+4,0)]

    def _publish_background(self,p,ram,manifest,job):
        """Hold A': claim + IO body + background request, and NO runner words.

        Publishing the ordinary runner request here would leave it pending for
        the whole read, and the background runner refuses while it is pending.
        """
        control=manifest['control'];entry=manifest['entry']
        if (entry,control)!=(io.ENTRY,io.CONTROL):raise ValueError('Background reload requires the serial IO workspace')
        self._prepare_blocks('io',ram,manifest)
        sequence=p.read_u32(runner.CONTROL+4)
        if sequence!=p.read_u32(runner.CONTROL+8):raise RuntimeError('Reload runner already busy')
        ack=p.read_u32(runner.BG_CONTROL+8)
        if p.read_u32(runner.BG_CONTROL+4)!=ack:raise RuntimeError('A background reload request is already pending')
        control_block=next((b for b in manifest['blocks'] if b['address']==control),None)
        if control_block is None:raise ValueError('Reload stage has no owned control block')
        data=bytearray.fromhex(control_block['data_hex']);struct.pack_into('<I',data,0,1)
        control_block['data_hex']=data.hex()
        request=(ack+1)&0xFFFFFFFF or 1
        parameters=struct.pack('<12I',job['manager'],entry,control,0,job['physical'],job['owner_action'],
                               job['row'],job['generation'],0,0,0,0)
        publication=[(runner.BG_CONTROL+16,parameters),(runner.BG_CONTROL+12,bytes(4)),
                     (runner.BG_CONTROL+8,struct.pack('<I',ack)),
                     (runner.BG_CONTROL+4,struct.pack('<I',request))]
        blocks=[word_block(ram,job['row']+4,2)]+manifest['blocks']+[
            dict(address=at,expected_hex=(struct.pack('<I',ack) if at in
                 (runner.BG_CONTROL+4,runner.BG_CONTROL+8) else p.read(at,len(value))).hex(),
                 data_hex=value.hex()) for at,value in publication]
        before=time.perf_counter();self.apply(p,dict(manifest,blocks=blocks));self.owned['io']=manifest
        self.timings.append(('io publish',time.perf_counter()-before))

    def _unwind_start(self,p,job,result=0):
        """Hold-A' expiry. True when the claim was undone, False if IO started.

        Nothing was opened, allocated, reserved or queued, so a transient
        refusal simply puts the row back to1 and the request is retried. The
        guest still runs between the gate and the packet applier, so the
        restore is guarded on io.CONTROL+4 reading zero: a rejected transaction
        means the guest acted first, and a workspace whose buffers are already
        on the native pending list is never rewritten.
        """
        last=None
        for _ in range(3):
            ram=self._snapshot(p)
            if u(ram,io.CONTROL+4):return False
            blocks=self._restore_blocks(ram,'io')
            blocks.append(word_block(ram,job['row']+52,result))
            blocks.append(word_block(ram,job['row']+4,1 if not result or result in BACKGROUND_RETRY else 5))
            blocks.extend(self._background_clear(ram))
            try:self.apply(p,dict(blocks=blocks))
            except RuntimeError as error:last=error;continue
            self.owned.pop('io',None);return True
        raise RuntimeError(f'Extra reload background start could not be unwound ({last}); match remains held')

    def _start_background(self,p,ram,job):
        view=self._analysis_view(ram)
        manifest=self._build('io',io.build_memory,view,job['physical'],job['character'],job['costume'],
                             job['damaged'],timeout=BACKGROUND_IO_CALLS,quiet=True,allow_forms=self.forms,
                             background=True,row=job['row'],generation=job['generation'])
        self._publish_background(p,ram,manifest,job)
        started=time.perf_counter();frame=p.read_u32(native.CONTROL+40)
        while not p.read_u32(io.CONTROL+4):
            acked=p.read_u32(runner.BG_CONTROL+4)==p.read_u32(runner.BG_CONTROL+8)
            expired=((p.read_u32(native.CONTROL+40)-frame)&0xFFFFFFFF>=BACKGROUND_START_FRAMES or
                     time.perf_counter()-started>BACKGROUND_START_SECONDS)
            if not acked and not expired:
                self.sleep(.01);continue
            reason=p.read_u32(runner.BG_CONTROL+12) if acked else 0
            if not self._unwind_start(p,job,reason):break
            self.timings.append(('io start',time.perf_counter()-started))
            self.progress(f'Transformation start refused with status {reason}'
                          +('; the request will be retried' if not reason or reason in BACKGROUND_RETRY else '')
                          if reason else 'Transformation start timed out; the request will be retried')
            self._release(p);return False
        self.timings.append(('io start',time.perf_counter()-started))
        self.form_job=job;self.form_phase='io'
        self.form_frame=p.read_u32(native.CONTROL+40);self.form_elapsed=0;self.form_paused=False
        self.progress('Transformation loading in the background')
        self._release(p);return False

    def _background_form(self,p):
        """Unheld watch over the disc read; no write until the runner is inert."""
        job=self.form_job
        try:
            if p.read_u32(runner.core.MODE)!=1 or p.read_u32(runner.core.ACTORS)!=job['manager']:
                self.form_job=None;self.form_phase=None;self.active=False;return False
            frame=p.read_u32(native.CONTROL+40);delta=(frame-self.form_frame)&0xFFFFFFFF
            paused=bool(p.read_u32(SCENE_FLAGS)&0x3900 or
                        p.read_u32(job['manager']+628) or p.read_u32(native.CONTROL+16))
            if not paused and not self.form_paused:self.form_elapsed+=delta
            self.form_frame=frame;self.form_paused=paused
            if p.read_u32(runner.BG_CONTROL+4)!=p.read_u32(runner.BG_CONTROL+8):
                # The runner is armed: the host may not touch the row or the
                # workspace. Its own450-call deadline always lands first.
                if delta>=0x80000000 or self.form_elapsed>900:
                    if not p.read_u32(native.CONTROL+16):self.quiet(p)
                    raise RuntimeError('Background transformation IO never acknowledged; match remains held for recovery')
                return False
            status=p.read_u32(io.CONTROL+4);result=p.read_u32(runner.BG_CONTROL+12)
            if status!=5:
                # The start reserved its record and three buffers before
                # io.CONTROL+4 ever left zero, so anything that fails here
                # leaves a bundle nothing references.
                self.progress(f'Transformation load failed with status {result or status}')
                return self._abort_form(p,result or status or 110,orphaned=True)
            self.progress(f'Background transformation IO finished in {p.read_u32(runner.BG_CONTROL+28)} guest calls '
                          f'({p.read_u32(io.CONTROL+io.POLLS)} loader polls)')
            return self._stage_background(p,job)
        except Exception as exc:
            import player_errors;self.failure=player_errors.short(exc);self.progress(self.failure);raise

    def _stage_background(self,p,job):
        """Second short hold: today's staging, then row+4=3, then release."""
        self.quiet(p)
        self._held_since=time.perf_counter();self.timings=[]
        ram=self._snapshot(p)
        if candidate(ram,(2,),specific=job['physical'])!=job:
            self.progress('Transformation owner changed while its resources loaded')
            return self._abort_form(p,110,held=True,orphaned=True)
        try:
            view=self._analysis_view_for(ram,('stage','commit'))
            manifest=self._build('stage',stage.build_memory,view,quiet=True,allow_forms=self.forms)
        except ValueError as error:
            self.progress(f'Transformation staging refused: {error}')
            return self._abort_form(p,130,held=True,orphaned=True)
        self._install_stage(p,'stage',ram,manifest,job)
        self._group_note(p)
        ram=self._snapshot(p)
        self.apply(p,dict(blocks=[word_block(ram,job['row']+4,3)]))
        self.form_phase='commit';self.form_frame=p.read_u32(native.CONTROL+40)
        self.form_elapsed=0;self.form_paused=False
        self.progress('Transformation loaded');self._release(p);return False

    def _abort_form(self,p,result,*,held=False,orphaned=False):
        """Graceful no-swap end. Only ever runs with the runner acknowledged.

        The record and the three buffers are already reserved here, so the row
        can never go back to1: it goes to5, never to6. forms.READY answers
        ready for3/4/5 only and the native action-236 handler has no timeout,
        so status6 would park the fighter in its power-up pose for the rest of
        the match. At5 the actor plays its burst with the old model, ACK
        no-ops (it acts only at status3) and FINISH advances5->6 - all inside
        the reviewed mod handshake, with row+56 left at1 so READY, ACK and
        FINISH keep going through it instead of the unhooked native handlers.
        """
        job=self.form_job
        if not held and not (p.read_u32(native.CONTROL+16)==1 and p.read_u32(native.CONTROL+20)==1):
            self.quiet(p)
        if self._held_since is None:self._held_since=time.perf_counter();self.timings=[]
        last=None
        for _ in range(3):
            ram=self._snapshot(p)
            blocks=self._restore_blocks(ram,'io')
            blocks.append(word_block(ram,job['row']+52,result))
            blocks.append(word_block(ram,job['row']+4,5))
            blocks.extend(self._background_clear(ram))
            try:self.apply(p,dict(blocks=blocks))
            except RuntimeError as error:last=error;continue
            break
        else:
            raise RuntimeError(f'Background transformation abort was rejected ({last}); match remains held')
        self.owned.pop('io',None)
        if orphaned:
            note=f'Transformation {result} for physical {job["physical"]} left its loaded bundle unretired'
            self.retirement_notes.append(note);self.progress(note)
        self.form_job=None;self.form_phase=None
        self._release(p);return False

    def _finish_form(self,p):
        job=self.form_job
        try:
            # A menu/world transition belongs to the parent lifecycle. Never
            # take a new world's hold or write its actors to recover an old job.
            if p.read_u32(runner.core.MODE)!=1 or p.read_u32(runner.core.ACTORS)!=job['manager']:
                self.form_job=None;self.active=False;return False
            frame=p.read_u32(native.CONTROL+40)
            delta=(frame-self.form_frame)&0xFFFFFFFF
            # The native actor cannot acknowledge while the arena, user pause,
            # leader reload or another preparation hold stops its update. Count
            # active observed intervals, retaining elapsed work across each hold.
            paused=bool(p.read_u32(SCENE_FLAGS)&0x3900 or
                        p.read_u32(job['manager']+628) or p.read_u32(native.CONTROL+16))
            if not paused and not self.form_paused:self.form_elapsed+=delta
            self.form_frame=frame;self.form_paused=paused
            state=p.read_u32(job['row']+4)
            if (delta>=0x80000000 or self.form_elapsed>900 or state not in (3,4) or
                    p.read_u32(job['actor']+0x948)!=job['owner_action']):
                if not p.read_u32(native.CONTROL+16):self.quiet(p)
                raise RuntimeError('Native transformation acknowledgment was interrupted; match remains held for recovery')
            if state!=4:return False
            if p.read_u32(native.CONTROL+16)!=1 or p.read_u32(native.CONTROL+20)!=1:return False
            self._held_since=time.perf_counter();self.timings=[]
            ram=self._snapshot(p)
            if candidate(ram,(4,))!=job:raise RuntimeError('Native transformation owner changed before commit; match remains held')
            view=self._analysis_view_for(ram,('commit',))
            manifest=self._build('commit',commit.build_memory,view,quiet=True,retire_staged=True,form=True)
            self._install_stage(p,'commit',ram,manifest,job)
            ram=self._snapshot(p)
            if (u(ram,commit.AI_META)!=5 or u(ram,commit.CONTROL+36)!=1 or
                    u(ram,job['model']+12)!=job['character']):
                raise RuntimeError('Native transformation final identity check failed; match remains held')
            ram=self._complete_resources(p,ram,job)
            self.apply(p,dict(blocks=[word_block(ram,job['row']+52,5),word_block(ram,job['row']+4,5)]))
            self.form_job=None;self.progress('Transformation complete');self._release(p);return True
        except Exception as exc:
            import player_errors;self.failure=player_errors.short(exc);self.progress(self.failure);raise

    def _complete_resources(self,p,ram,job):
        """Retain initial bundles; recycle only this Worker's prior receipts."""
        physical=job['physical'];new=retire.receipt(ram,physical)
        old=self.resources.get(physical);self.resources[physical]=new
        if old is not None:
            if old['resource']!=job['old_resource']:
                raise RuntimeError('Owned resource identity changed before retirement; match remains held')
            self.retained.setdefault(physical,[]).append(old)
        pending=self.retained.get(physical,[])
        for owned in list(pending):
            view=self._analysis_view_for(ram,('retire',))
            try:manifest=retire.build_memory(view,owned)
            except ValueError as error:
                # No destructor has run. A conservative unknown reference
                # retains its bundle and leaves the completed fighter usable.
                # Native admission independently prevents table exhaustion.
                self.retirement_notes.append(str(error));continue
            self._install_stage(p,'retire',ram,manifest,job)
            pending.remove(owned);ram=self._snapshot(p)
        return ram

    def _analysis_view_for(self,ram,names):
        owned=self.owned
        try:
            self.owned={name:owned[name] for name in names if name in owned}
            return self._analysis_view(ram)
        finally:self.owned=owned
