"""Serial host service for true Body Change; uses only the caller's PINE client.

The guest finishes the authored capture and acquires the ordinary native hold.
Two complete independent bundles/models are staged before the atomic commit.
No process, input, save/load state, connection, thread or reset is created here.
"""
import struct
import time

import body_swap as body
import body_swap_resources as resources
import body_swap_commit as commit
import body_swap_runner as runner
import body_swap_retire as retire
import native_preparation as native
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy
import lazy_ram
import body_swap_snapshot
import body_swap_copy

EPOCH_WORDS=(body.CONTROL+24,runner.CONTROL+4,runner.CONTROL+8)
# Status 2 (authored animation finished, stock reload suppressed) can only
# advance when the runner sees both bodies outside authored/reload actions and alive. A dead or never-idle
# victim would otherwise hold the claim forever; the host abandons it after
# this many observed combat frames (native.CONTROL+44 advances only while the
# combat dispatch actually runs, so held/paused intervals do not count).
STUCK_FRAMES=1800


def block(ram,p,data):
    return dict(address=p,expected_hex=bytes(ram[p:p+len(data)]).hex(),data_hex=bytes(data).hex())


def live_block(p,at,value):
    return dict(address=at,expected_hex=p.read(at,4).hex(),data_hex=struct.pack('<I',value).hex())


def live_owner_mask(p):
    """Original Ginyu owner bits from live reads; the same rule as body.ginyu_owners."""
    count=p.read_u32(body.core.MODE+4)
    if count not in ACTOR_COUNTS:raise ValueError('Captured world required to enable Body Change')
    present=p.read_u32(body.participation.CONTROL+12)&~p.read_u32(body.participation.CONTROL+16)
    mask=0
    for physical in range(count):
        if not present&(1<<physical):continue
        actor=p.read_u32(body.core.POINTERS+4*physical)
        if not 0x100000<=actor<=0x8000000-0x1600:raise ValueError('Invalid captured actor pointer')
        slots=p.read_u32(actor+0x998)
        if slots>5:continue
        rows=p.read(actor+0x9A4,body.ROW_BYTES*slots)
        if any(struct.unpack_from('<I',rows,body.ROW_BYTES*slot)[0]==body.GINYU for slot in range(slots)):
            mask|=1<<physical
    return mask


@policy.matching_install
def install_memory(ram,source='<captured-ready>',enabled=False,stolen_abilities=False):
    import body_swap_capture as capture
    from fresh_team_trainer import compose_manifests
    if type(enabled) is not bool:raise ValueError('Body capture enabled must be Boolean')
    if type(stolen_abilities) is not bool:raise ValueError('Stolen-body ability option must be Boolean')
    if body.u(ram,body.CONTROL)==body.MAGIC:
        runner.validate_memory(ram)
        if body.u(ram,body.ALLOW_ABILITIES)!=int(stolen_abilities):
            raise ValueError('Body Change ability changes require a newly prepared match')
        data=runner.code();blocks=[]
        if ram[runner.ENTRY:runner.ENTRY+len(data)]!=data:
            body.require(body.u(ram,body.CONTROL+16)==0,'Cannot upgrade an in-flight Body Change')
            old=runner.code(False)
            body.require(not any(ram[runner.ENTRY+len(old):runner.ENTRY+len(data)]),'Body runner upgrade extension occupied')
            blocks=[block(ram,runner.ENTRY,data)]
        return dict(source=str(source),blocks=blocks,control=body.CONTROL,entry=runner.ENTRY,
                    status='TRUE BODY CHANGE VERIFIED',enabled=bool(body.u(ram,body.CONTROL+20)))
    result=compose_manifests(ram,[lambda r:capture.build_memory(r,source=source,enabled=enabled,stolen_abilities=stolen_abilities),runner.build_memory])
    # Capture remains disabled until a fully validated host worker attaches.
    result.update(source=str(source),control=body.CONTROL,entry=runner.ENTRY,
                  status='TRUE BODY CHANGE; SERIAL HOST WORKER REQUIRED',enabled=bool(enabled))
    return result


def prepare_memory(ram,settings=None,source='<captured-ready>'):
    import mod_settings
    options=mod_settings.validate_settings(settings or {})
    if not options['true_body_change']:
        if body.u(ram,body.CONTROL)==body.MAGIC:
            raise ValueError('Disabling installed Body Change requires a newly prepared match')
        return dict(source=str(source),blocks=[],status='TRUE BODY CHANGE DISABLED')
    return install_memory(ram,source=source,enabled=False,stolen_abilities=options['ginyu_stolen_abilities'])


def snapshot(ram):
    """Match immutable guest receipt to both original bodies after the authored dispatch."""
    import body_swap_capture as capture
    u=lambda p:body.u(ram,p);w=body.world(ram)
    body.require(u(body.CONTROL)==body.MAGIC and u(body.CONTROL+16)==3 and
                 u(body.CONTROL+4)==w['manager'] and u(body.CONTROL+8)==w['count'],
                 'Body Change handoff is not owned')
    result=[]
    for i in range(2):
        record=body.ROWS+i*64;physical=u(record);b=body.body(ram,w,physical)
        for off,key in ((4,'actor'),(8,'model_id'),(12,'model'),(16,'row'),(20,'resource'),
                        (24,'character'),(28,'costume'),(52,'controller'),(56,'cpu')):
            body.require(u(record+off)==b[key],f'Captured Body Change participant changed:{key}')
        original=bytes(ram[capture.FULL_ROWS[i]:capture.FULL_ROWS[i]+body.ROW_BYTES])
        body.require(struct.unpack_from('<2I',original)==(b['character'],b['costume']),
                     'Captured full body row identity changed')
        # The runner copied both rows in the hold frame; nothing may have
        # changed them since, so the published exchange uses handoff values.
        handoff=bytes(ram[body.HANDOFF_ROWS[i]:body.HANDOFF_ROWS[i]+body.ROW_BYTES])
        body.require(handoff==bytes.fromhex(b['row_hex']),'Handoff-time body row changed before the exchange')
        body.require(0<=b['action']<236,'Authored Body Change has not released both bodies')
        result.append(b)
    body.require(result[0]['character']==body.GINYU and
                 body.policy.enemy(w['mode'],result[0]['physical'],result[1]['physical']),
                 'Captured pair must be Ginyu and his actual enemy')
    body.require(u(body.OWNERS)>>result[0]['physical']&1,'Captured attacker is not an original Ginyu owner')
    body.require(u(body.ALLOW_ABILITIES) in (0,1),'Invalid stolen-body ability preference')
    return dict(world=w,source=result[0],target=result[1],generation=u(body.CONTROL+24),
                stolen_abilities=bool(u(body.ALLOW_ABILITIES)))


class Worker:
    def __init__(self,progress=None,read_ram=native.read_ram,apply=native.apply,
                 resume=native.resume,quiet=native.quiet,clock=time.monotonic,sleep=time.sleep,
                 stuck_frames=STUCK_FRAMES,resource_builder=body_swap_copy.io_memory):
        self.progress=progress or (lambda message:None)
        self.read_ram,self.apply,self.resume,self.quiet=read_ram,apply,resume,quiet
        self.clock,self.sleep=clock,sleep
        if type(stuck_frames) is not int or stuck_frames<=0:raise ValueError('Stuck frame bound must be a positive integer')
        self.stuck_frames=stuck_frames
        self.active=False;self.failure=None;self.busy=False;self.owned={}
        self.retained=[];self.retirement_notes=[];self.completed=None;self.completions=[]
        self.aborts=[];self._stuck=None
        self._coordinated_generation=0
        self.capacity=policy.TEAM_CAPACITY
        self._ram_buffer=None
        self.timings={}
        self.resource_builder=resource_builder

    def attach(self,p):
        magic=p.read_u32(body.CONTROL)
        if magic==0:self.active=False;self.busy=False;return False
        if magic!=body.MAGIC:raise ValueError('Unrecognized Body Change installation')
        import body_swap_capture as capture
        manager=p.read_u32(body.CONTROL+4);count=p.read_u32(body.CONTROL+8)
        if count not in ACTOR_COUNTS or p.read_u32(body.core.ACTORS)!=manager:
            raise ValueError('Body Change owner changed before attach')
        previous=p.read_u32(runner.CONTROL+28)
        import teammate_revive
        if previous not in (runner.fusion.CONTACT,runner.coop.CONTACT,teammate_revive.CONTACT):
            raise ValueError('Body Change prior contact chain changed')
        matched=False
        direct_hook=struct.pack('<2I',(2<<26)|(runner.ENTRY>>2),0)
        # This optional outer wrapper has an independent full-code receipt.
        # Do not accept an arbitrary jump merely because its tail names us.
        outer_view=lazy_ram.LazyRam(p)
        for capacity in (policy.TEAM_CAPACITY,policy.LEGACY_TEAM_CAPACITY):
            try:
                with policy.building_for(capacity),lazy_ram.patched():
                    import story_runtime
                    hook=runner.frame_hook(outer_view)
                    expected=[(at,hook if at==runner.HOOK else data) for at,data in runner.program(previous)+capture.program()]
                    expected=[(at,story_runtime.dependency_override(outer_view,at,data)) for at,data in expected]
            except ValueError:
                continue
            if all(p.read(at,len(data))==data for at,data in expected):
                self.capacity=capacity;self.pieces=expected;matched=True;break
        if not matched:
            raise ValueError('Body Change program changed before attach')
        if p.read_u32(body.CONTROL+16)!=0:
            raise ValueError('Cannot adopt an in-flight Body Change without its ownership receipts')
        if p.read_u32(body.FINISHED)!=0:
            raise ValueError('Cannot adopt completed Body Change resource receipts; prepare a new match')
        if p.read_u32(body.ALLOW_ABILITIES) not in (0,1):
            raise ValueError('Invalid stolen-body ability preference')
        # Record the original Ginyu owners before enabling: later exchanges may
        # only be claimed by these physical bodies (reverse-swap policy). Both
        # words are published in one exact-byte guarded transaction, which
        # requires the caller's acknowledged hold (native.apply).
        mask=live_owner_mask(p)
        self.apply(p,dict(blocks=[live_block(p,body.OWNERS,mask),live_block(p,body.CONTROL+20,1)]))
        self.active=True;return True

    def installed(self,p):
        """Is the service this worker attached to still this match's? Reads only (no claim,
        no write): the watcher checks a worker it parked for a moment out of combat before it
        reuses it (match F1). The words attach checked and the exact program bytes it verified;
        a worker that found no service needs none to have appeared since."""
        if not self.active:return p.read_u32(body.CONTROL)==0
        manager=p.read_u32(body.CONTROL+4)
        if (p.read_u32(body.CONTROL)!=body.MAGIC or p.read_u32(body.CONTROL+8) not in ACTOR_COUNTS or
                p.read_u32(body.core.ACTORS)!=manager):return False
        return all(p.read(at,len(data))==data for at,data in getattr(self,'pieces',()))

    def _abort(self,p,generation,reason):
        """Abandon a stuck claim as a stock no-op finish: status 2 -> 0.

        Under the acknowledged hold the runner cannot race to status 3. The
        local hooks then stop suppressing this pair (they act only on status
        1..100), the admission wrapper and the contact prefix release it, and a
        fresh capture may start later. Nothing else is rewritten.

        The runner requests the same native hold (status 2 -> 3) only while
        native.CONTROL+16 is still 0, so it can win the quiet frame: the re-read
        then shows status 3, nothing is written and that hold now belongs to
        the handoff. It is never released here; the next poll services status 3
        under it. A private hold is released only while the claim stays at
        status 2 (whether or not the abort was applied).
        """
        held=p.read_u32(native.CONTROL+16)==1 and p.read_u32(native.CONTROL+20)==1
        if not held:self.quiet(p)
        release=not held
        try:
            status=p.read_u32(body.CONTROL+16)
            if status==3:release=False;return False
            if status!=2 or p.read_u32(body.CONTROL+24)!=generation:return False
            self.apply(p,dict(blocks=[live_block(p,body.CONTROL+16,0),live_block(p,body.ABORTED,generation)]))
            self.aborts.append(dict(generation=generation,reason=reason,
                physical_ids=[p.read_u32(body.ROWS+i*64) for i in range(2)]))
            self.busy=False;self._stuck=None;self.progress('Body Change abandoned: '+reason);return True
        finally:
            if release:self.resume(p)

    def _watch_stuck(self,p):
        """Bounded status-2 wait; abort when the victim is dead or its authored action never exits."""
        generation=p.read_u32(body.CONTROL+24);frames=p.read_u32(native.CONTROL+44)
        if self._stuck is None or self._stuck[0]!=generation:self._stuck=(generation,frames)
        rows=[p.read_u32(body.ROWS+i*64+16) for i in range(2)]
        if any(not 0x100000<=row<=0x8000000-body.ROW_BYTES for row in rows):
            return self._abort(p,generation,'captured body row is invalid')
        if any(p.read_u32(row+64)==0 for row in rows):
            return self._abort(p,generation,'a captured body died before the handoff')
        if (frames-self._stuck[1])&0xFFFFFFFF>self.stuck_frames:
            return self._abort(p,generation,f'bodies did not release their authored actions within {self.stuck_frames} combat frames')
        return False

    def _run(self,p,name,ram,manifest):
        started=time.perf_counter()
        entry,control=manifest['entry'],manifest['control']
        if (entry,control) not in runner.TARGETS:raise ValueError('Unrecognized Body Change job')
        if p.read_u32(runner.CONTROL+4)!=p.read_u32(runner.CONTROL+8):
            raise RuntimeError('Body Change native runner is busy')
        generation=(p.read_u32(runner.CONTROL+4)+1)&0xFFFFFFFF or 1
        # Publish code, enable, ownership and sequence in one checked native
        # packet. There is no host-write window with half a runnable job.
        published=[];found=False
        for source in manifest['blocks']:
            b=dict(source)
            if b['address']==control:
                data=bytearray.fromhex(b['data_hex']);struct.pack_into('<I',data,0,1)
                b['data_hex']=data.hex();found=True
            published.append(b)
        if not found:raise ValueError('Body Change job has no owned control block')
        published += [block(ram,runner.CONTROL+16,struct.pack('<3I',p.read_u32(body.CONTROL+4),entry,control)),
                      block(ram,runner.CONTROL+12,struct.pack('<I',0)),
                      block(ram,runner.CONTROL+4,struct.pack('<I',generation))]
        # Only stage-owned blocks are receipts: transient runner words mutate
        # on ACK and must never become cleanup ownership.
        self.owned[name]=manifest
        self.apply(p,dict(manifest,blocks=published))
        # Running time only: a PCSX2 paused during the job is waited for.
        budget=native.RunningTime(p,90,clock=self.clock)
        while True:
            if p.read_u32(runner.CONTROL+8)==generation:
                status=p.read_u32(runner.CONTROL+12)
                if status!=5 or p.read_u32(control+4)!=5:
                    raise RuntimeError(f'Body Change {name} failed:{status}; match remains held')
                timing_name='resident_copy' if manifest.get('resident_copy') else name
                self.timings[timing_name]=self.timings.get(timing_name,0)+time.perf_counter()-started
                return
            if budget.expired():break
            self.sleep(.02)
        raise TimeoutError(f'Body Change {name} did not finish within 90 s of running time; match remains held')

    def _clear(self,p,ram,names,lo,hi,extra_blocks=()):
        view=bytearray(ram[lo:hi])
        cleared=[]
        for name in names:
            manifest=self.owned[name]
            for b in manifest['blocks']:
                at=b['address'];data=bytes.fromhex(b['data_hex'])
                if not lo<=at<=hi-len(data):raise ValueError('Owned Body Change cleanup exceeds workspace')
                is_data=(name=='commit' and (commit.CONTROL<=at<commit.CONTROL+0x100 or
                    any(base+0xF000<=at<base+0x10000 for base in commit.OWNERS))) or (
                    name=='retire' and runner.RETIRE_CONTROL<=at<runner.RETIRE_CONTROL+0x100)
                if not is_data and ram[at:at+len(data)]!=data:
                    raise RuntimeError('Body Change owned code changed before cleanup')
                view[at-lo:at-lo+len(data)]=bytes(len(data))
                cleared.append(block(ram,at,bytes(len(data))))
        if any(view):raise RuntimeError('Body Change workspace contains unowned data')
        self.apply(p,dict(blocks=cleared+list(extra_blocks)))
        for name in names:self.owned.pop(name,None)

    def coordinate_reload_worker(self,extra):
        """Transfer exact active receipts; never reset the other service's jobs."""
        event=self.completed
        if event is None or self._coordinated_generation==event['generation']:return
        if getattr(extra,'form_job',None) is not None:
            raise RuntimeError('Extra form transaction still owns its acknowledgment')
        mappings=event['descriptor_mapping']
        changed=set(event['new_resources'])
        for physical,new in event['new_resources'].items():
            old=extra.resources.get(physical)
            if old is not None:
                before=event['old_resources'][physical]
                if old['resource']!=before:
                    raise RuntimeError('Extra resource receipt differs from captured Body Change owner')
            # Body service now owns retirement of this removed bundle. The new
            # independent extra record may be recycled by normal later forms.
            extra.resources[physical]=new
        # Alias migrations can affect a retained receipt in another owner list;
        # match the exact former descriptor and retain its existing file/group
        # identity. No other records or executable ownership are reset.
        for pending in extra.retained.values():
            for item in pending:
                if item['resource'] in mappings:
                    item['resource']=mappings[item['resource']]
                    item['handle']=event['mapped_handles'][item['resource']]
        self._coordinated_generation=event['generation']

    def release_stage_getter(self,p,ram,extra):
        """Borrow only the authenticated scratch hook of a completed reload.

        Extra stage code remains owned by its worker. Updating that one hook's
        receipt allows its next analysis/build to restore and replace it safely.
        """
        at=resources.stage.creator.EXT_ENTRY
        original=struct.pack('<2I',(2<<26)|(resources.stage.creator.EXT_CODE>>2),0)
        if ram[at:at+8]==original:return ram
        if extra is None or getattr(extra,'form_job',None) is not None:
            raise ValueError('Body Change scratch getter has no completed reload owner')
        extra._analysis_view_for(ram,('stage',))
        manifest=extra.owned.get('stage')
        if manifest is None:raise ValueError('Body Change scratch getter receipt missing')
        hook=next((b for b in manifest['blocks'] if b['address']==at),None)
        if (hook is None or bytes.fromhex(hook['data_hex'])!=ram[at:at+8] or
            bytes.fromhex(hook.get('restore_hex',hook['expected_hex']))!=original):
            raise ValueError('Body Change scratch getter ownership changed')
        self.apply(p,dict(blocks=[block(ram,at,original)]))
        hook['data_hex']=original.hex()
        return self._snapshot(p)

    def _snapshot(self,p):
        if self.read_ram is not native.read_ram:return self.read_ram(p)
        if self._ram_buffer is None:self._ram_buffer=body_swap_snapshot.Snapshot(p)
        else:self._ram_buffer.renew(p)
        return self._ram_buffer

    def poll(self,p,reload_worker=None):
        with policy.building_for(self.capacity),lazy_ram.patched():return self._poll(p,reload_worker)

    def _poll(self,p,reload_worker=None):
        if not self.active or self.failure:return False
        state=p.read_u32(body.CONTROL+16);self.busy=state in (1,2,3)
        if state in (0,5):self._stuck=None;return False
        if state>=100:
            self.failure=f'Body Change guest capture failed:{state}';raise RuntimeError(self.failure)
        if state==2:
            # A transport failure while abandoning a stuck claim (quiet timeout,
            # rejected block, PINE error) is terminal like any state-3 failure:
            # a host that kept polling could retry under a foreign hold.
            try:self._watch_stuck(p)
            except Exception as exc:
                import player_errors;self.failure=player_errors.short(exc);self.progress(self.failure);raise
            return False
        if state!=3:return False
        if reload_worker is not None and getattr(reload_worker,'form_job',None) is not None:return False
        if (p.read_u32(native.CONTROL+16),p.read_u32(native.CONTROL+20))!=(1,1):return False
        started=time.perf_counter();self.timings={}
        try:
            ram=self._snapshot(p);snap=snapshot(ram)
            handoff_wait_frames=((body.u(ram,native.CONTROL+44)-self._stuck[1])&0xFFFFFFFF
                                 if self._stuck is not None and self._stuck[0]==snap['generation'] else 0)
            ram=self.release_stage_getter(p,ram,reload_worker)
            self.progress('Exchanging fighter bodies')
            receipts=[];resource_paths=[]
            for b in (snap['source'],snap['target']):
                try:io=self.resource_builder(ram,snap,b['physical'])
                except body_swap_copy.SourceUnavailable as exc:
                    self.progress('Body Change requires ordinary file loading: '+str(exc))
                    io=resources.io_memory(ram,snap,b['physical'])
                resource_paths.append('resident' if io.get('resident_copy') else 'disc')
                self._run(p,'io',ram,io)
                ram=self._snapshot(p);stage=resources.stage_memory(ram,snap,b['physical']);self._run(p,'stage',ram,stage)
                ram=self._snapshot(p);receipt=resources.staged_receipt(ram,snap,b['physical'],io['capacities'])
                receipts.append(receipt)
                self.apply(p,resources.detach_memory(ram,receipt,io,stage));self.owned.pop('io');self.owned.pop('stage')
                ram=self._snapshot(p)
            manifest=commit.build_memory(ram,snap,receipts)
            # Retirement compares these original files after native descriptor
            # adoption; force them resident before the commit can change them.
            before={c['world']['old_resource']:bytes(ram[c['world']['old_resource']:c['world']['old_resource']+56])
                    for c in manifest['configurations']}
            self._run(p,'commit',ram,manifest);ram=self._snapshot(p)
            for i,c in enumerate(manifest['configurations']):
                w,row=c['world'],c['resource'];desired=manifest['rows'][i]
                if (body.u(ram,commit.OWNERS[i]+0xF200)!=5 or
                    body.u(ram,commit.OWNERS[i]+0xF024)!=1 or
                    body.u(ram,w['model']+12)!=row['character'] or
                    body.u(ram,w['model']+20)!=row['resource'] or
                    bytes(ram[desired['row']:desired['row']+body.ROW_BYTES])!=bytes.fromhex(desired['data_hex']) or
                    body.u(ram,w['actor']+4)!=desired['controller'] or body.u(ram,w['actor']+0x1278)!=desired['cpu']):
                    raise RuntimeError('Body Change final body/control verification failed; match remains held')
            removed,mapping=retire.removed_receipts(before,ram,manifest)
            existing={x['resource'] for x in self.retained}
            self.retained += [x for x in removed if x['resource'] not in existing]
            new={c['world']['physical']:retire.receipt(ram,c['world']['physical'],c['resource']['resource'],c['new_group'])
                 for c in manifest['configurations'] if c['world']['physical']>=2}
            self.completed=dict(generation=snap['generation'],physical_ids=[b['physical'] for b in (snap['source'],snap['target'])],
                resource_paths=resource_paths,
                handoff_wait_frames=handoff_wait_frames,
                handoff_actions=[b['action'] for b in (snap['source'],snap['target'])],
                old_resources={c['world']['physical']:c['world']['old_resource'] for c in manifest['configurations']},
                new_resources=new,descriptor_mapping=mapping,mapped_handles={p:body.u(ram,p+52) for p in mapping.values()},
                bodies=[dict(physical=c['world']['physical'],character=c['resource']['character'],health=manifest['rows'][i]['health'])
                        for i,c in enumerate(manifest['configurations'])])
            if reload_worker is not None:self.coordinate_reload_worker(reload_worker)
            for owned in list(self.retained):
                try:recycle=retire.build_memory(ram,owned)
                except ValueError as exc:self.retirement_notes.append(str(exc));continue
                self._run(p,'retire',ram,recycle);ram=self._snapshot(p)
                deferred=p.read_u32(runner.RETIRE_CONTROL+32)==1
                self._clear(p,ram,('retire',),runner.RETIRE,runner.END)
                if deferred:self.retirement_notes.append('Renderer busy; retained old body bundle for a later safe cleanup')
                else:self.retained.remove(owned)
                ram=self._snapshot(p)
            # Guest-visible completion: status 0 and FINISHED = this generation
            # and owned-code cleanup are published in one guarded transaction.
            self._clear(p,ram,('commit',),commit.ENTRY,commit.END,extra_blocks=[
                block(ram,body.CONTROL+16,struct.pack('<I',0)),
                block(ram,body.FINISHED,struct.pack('<I',snap['generation']))])
            self.completions.append(self.completed);self.busy=False;self._stuck=None
            self.timings['total']=time.perf_counter()-started
            self.completed['timings_seconds']=dict(self.timings)
            self.progress('Body Change timing: '+', '.join(f'{key}={value:.3f}s' for key,value in self.timings.items()))
            if handoff_wait_frames:self.progress(f'Body Change pre-hold recovery: {handoff_wait_frames} combat frames')
            self.progress('Body Change handoff actions: '+str(self.completed['handoff_actions']))
            self.progress('Bodies exchanged');self.resume(p);return True
        except Exception as exc:
            import player_errors;self.failure=player_errors.short(exc);self.progress(self.failure);raise
        finally:
            if self._ram_buffer is not None:self._ram_buffer.invalidate()
            self._ram_buffer=None
