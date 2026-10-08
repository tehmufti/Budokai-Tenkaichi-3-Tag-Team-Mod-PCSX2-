"""Serial caller-owned service for real timed defusion (no connection creation)."""
import os
import struct
import bt4_model_metadata
from types import SimpleNamespace
import fusion_duration as timer
import fusion_duration_commit as restore
import body_swap_worker as shared
import body_swap_commit as commit
import body_swap_retire as retire
import body_swap_resources as resources
import native_preparation as native
import battle_mode_policy as policy
import lazy_ram

EPOCH_WORDS=(timer.CONTROL+24,timer.JOB_CONTROL+4,timer.JOB_CONTROL+8)
# Service-owner claim written to CONTROL+12: this process's ID with bit 31 set (never 0).
OWNER=0x80000000|(os.getpid()&0x7FFFFFFF)


def retirement_memory(ram,owned,record,generation):
    """Reuse the exact bundle retirement audit under this completed receipt."""
    def capture(view,receipt,*,body_context=None):
        context=dict(body_context)
        context['commit_guards']=[(commit.CONTROL+4,5),(record,3),(record+72,generation),
                                  (timer.CONTROL+4,receipt['manager'])]
        return retire.prior.capture(view,receipt,body_context=context)
    prior=SimpleNamespace(**dict(vars(retire.prior),capture=capture))
    return timer.core.rebound(retire.build_memory,prior=prior)(ram,owned)


@policy.matching_install
def prepare_memory(ram,settings=None,source='<captured-ready>'):
    import mod_settings
    options=mod_settings.validate_settings(settings or {})
    if not options.get('fusion_duration_enabled',False):
        if timer.u32(ram,timer.CONTROL)==timer.MAGIC:raise ValueError('Disabling timed fusion requires a new match')
        return resources.parts_manifest(ram,[],source=str(source),status='TIMED FUSION DISABLED')
    return timer.build_memory(ram,options.get('fusion_duration_seconds',40),options.get('show_fusion_timer',True),source,lore=False,
                              animate=options.get('fusion_defusion_animation',True))


class Worker(shared.Worker):
    def attach(self,p):
        magic=p.read_u32(timer.CONTROL)
        if magic==0:self.active=False;return False
        if magic!=timer.MAGIC:raise ValueError('Unknown timed fusion service')
        manager,count=p.read_u32(timer.CONTROL+4),p.read_u32(timer.CONTROL+8)
        if count not in policy.ACTOR_COUNTS or p.read_u32(timer.core.ACTORS)!=manager:raise ValueError('Timed fusion owner changed')
        previous,draw_previous=p.read_u32(timer.CONTROL+32),p.read_u32(timer.CONTROL+36)
        matched=False
        import four_player_mode
        ram=lazy_ram.LazyRam(p)
        for capacity in (policy.TEAM_CAPACITY,policy.LEGACY_TEAM_CAPACITY):
            with policy.building_for(capacity):
                pieces=timer.program(previous,draw_previous)+[(timer.fusion.BEGIN,timer.fusion.begin_code(True)),(timer.fusion.COMMIT,timer.fusion.commit_code(True))]
                with lazy_ram.patched():
                    try:pieces=[(at,four_player_mode.dependency_override(ram,at,data))for at,data in pieces]
                    except ValueError:continue
                if all(p.read(at,len(data))==data for at,data in pieces):self.capacity=capacity;self.pieces=pieces;matched=True;break
        if not matched:raise ValueError('Timed fusion executable changed')
        if p.read(timer.runner.HOOK,8)!=timer.JUMP(timer.FRAME):raise ValueError('Timed fusion frame hook changed')
        if any(p.read_u32(timer.RECORDS+i*timer.STRIDE) not in (0,5) for i in range(count)):
            raise ValueError('Cannot adopt an in-flight timed fusion')
        # The claim carries this watcher's token (the guest only tests it for zero), so the
        # same watcher may attach again after dropping its worker, with every record idle.
        claim=p.read_u32(timer.CONTROL+12)
        if claim not in (0,OWNER):raise ValueError('Timed fusion already has a service owner')
        if claim==0:self.apply(p,dict(blocks=[shared.live_block(p,timer.CONTROL+12,OWNER)]))
        self.active=True;return True

    def installed(self,p):
        """The timed fusion service is still this match's and still claimed by this watcher.
        Reads only (no claim, no write); see body_swap_worker.Worker.installed (match F1)."""
        manager=p.read_u32(timer.CONTROL+4)
        if (p.read_u32(timer.CONTROL)!=timer.MAGIC or p.read_u32(timer.CONTROL+8) not in policy.ACTOR_COUNTS or
                p.read_u32(timer.core.ACTORS)!=manager or p.read_u32(timer.CONTROL+12)!=OWNER or
                p.read(timer.runner.HOOK,8)!=timer.JUMP(timer.FRAME)):return False
        return all(p.read(at,len(data))==data for at,data in getattr(self,'pieces',()))

    def _run(self,p,name,ram,manifest):
        runner=SimpleNamespace(**dict(vars(timer.runner),CONTROL=timer.JOB_CONTROL))
        body=SimpleNamespace(**dict(vars(shared.body),CONTROL=timer.CONTROL))
        return timer.core.rebound(shared.Worker._run,runner=runner,body=body)(self,p,name,ram,manifest)

    def poll(self,p,reload_worker=None,body_worker=None):
        with policy.building_for(self.capacity),lazy_ram.patched():return self._poll_fusion(p,reload_worker,body_worker)

    def _poll_fusion(self,p,reload_worker=None,body_worker=None):
        if not self.active or self.failure:return False
        statuses=[p.read_u32(timer.RECORDS+i*timer.STRIDE) for i in range(p.read_u32(timer.CONTROL+8))]
        self.busy=3 in statuses
        if not self.busy:return False
        # Host busy flags can lag one poll. Guest claims decide ownership;
        # two simultaneous acknowledged claims are an error, never a wait.
        if p.read_u32(timer.body.CONTROL)==timer.body.MAGIC and p.read_u32(timer.body.CONTROL+16)!=0:
            raise RuntimeError('Body Change and timed fusion both claim the native hold')
        if body_worker is not None:body_worker.busy=False
        if body_worker is not None and getattr(body_worker,'owned',{}):
            raise RuntimeError('Body Change still owns shared preparation code; defusion cannot borrow it')
        if reload_worker is not None and getattr(reload_worker,'form_job',None) is not None:return False
        if (p.read_u32(native.CONTROL+16),p.read_u32(native.CONTROL+20))!=(1,1):return False
        side=statuses.index(3)
        try:
            ram=self._snapshot(p);snap=restore.snapshot(ram,side)
            ram=self.release_stage_getter(p,ram,reload_worker)
            self.progress('Restoring the original fusion partners')
            io=restore.invoke(resources.io_memory,ram,snap,side);self._run(p,'io',ram,io)
            ram=bt4_model_metadata.staged(self,p,self._snapshot(p),resources.IO_CONTROL);stage=restore.invoke(resources.stage_memory,ram,snap,side);self._run(p,'stage',ram,stage)
            ram=self._snapshot(p);receipt=restore.invoke(resources.staged_receipt,ram,snap,side,io['capacities'])
            self.apply(p,resources.detach_memory(ram,receipt,io,stage));self.owned.pop('io');self.owned.pop('stage')
            # Stage the original body while the fusion still holds its idle
            # pose. Playing power-down before disc IO left that finished pose
            # visibly frozen for the entire load. Once the hidden replacement
            # exists, presentation can lead straight into the atomic split.
            ram=self._snapshot(p)
            if p.read_u32(timer.CONTROL+48):
                import fusion_defusion_animation as animation
                presentation=animation.build_memory(ram,snap)
                if presentation is not None:
                    self._run(p,'retire',ram,presentation);ram=self._snapshot(p)
                    self._clear(p,ram,('retire',),timer.runner.RETIRE,timer.runner.END);ram=self._snapshot(p)
            import fusion_defusion_placement as placement
            ram=self._snapshot(p);separation=placement.build_memory(ram,snap,receipt)
            self._run(p,'retire',ram,separation)
            snap['partner_root_words']=struct.unpack('<4I',p.read(separation['output'],16))
            ram=self._snapshot(p);self._clear(p,ram,('retire',),timer.runner.RETIRE,timer.runner.END)
            ram=self._snapshot(p);manifest=restore.build_memory(ram,snap,receipt)
            before={c['world']['old_resource']:bytes(ram[c['world']['old_resource']:c['world']['old_resource']+56]) for c in manifest['configurations']}
            ram=bt4_model_metadata.adoption(self,p,ram,manifest)
            self._run(p,'commit',ram,manifest);ram=self._snapshot(p)
            for index,row in enumerate(manifest['rows']):
                model=p.read_u32(timer.core.MODELS+4*p.read_u32(row['actor']+12))
                if (p.read_u32(row['row']+64)!=row['health'] or p.read_u32(row['actor']+4)!=row['controller'] or
                    p.read_u32(model+12)!=struct.unpack_from('<I',bytes.fromhex(row['data_hex']))[0] or
                    p.read_u32(commit.OWNERS[index]+0xF200)!=5):
                    raise RuntimeError('Defusion verification failed; match remains held')
            removed,mapping=retire.removed_receipts(before,ram,manifest)
            self.retained += [r for r in removed if r['resource'] not in {x['resource'] for x in self.retained}]
            self.completed=dict(generation=snap['generation'],physical_ids=[side,snap['partner']['physical']],
                old_resources={c['world']['physical']:c['world']['old_resource'] for c in manifest['configurations']},
                new_resources={},descriptor_mapping=mapping,mapped_handles={v:restore.u(ram,v+52) for v in mapping.values()},
                bodies=[dict(physical=i,health=row['health']) for i,row in zip((side,snap['partner']['physical']),manifest['rows'])])
            if reload_worker is not None:self.coordinate_reload_worker(reload_worker)
            for owned in list(self.retained):
                try:recycle=retirement_memory(ram,owned,snap['record'],snap['generation'])
                except ValueError as exc:self.retirement_notes.append(str(exc));continue
                self._run(p,'retire',ram,recycle);ram=self._snapshot(p)
                deferred=p.read_u32(timer.runner.RETIRE_CONTROL+32)==1
                self._clear(p,ram,('retire',),timer.runner.RETIRE,timer.runner.END)
                if deferred:self.retirement_notes.append('Renderer busy; retained old fusion bundle for a later safe cleanup')
                else:self.retained.remove(owned)
                ram=self._snapshot(p)
            import fusion_audio_restore as audio
            upload,audio_job=audio.build_memory(ram,snap)
            if upload['blocks']:self.apply(p,upload)
            self._run(p,'retire',ram,audio_job);ram=self._snapshot(p)
            self._clear(p,ram,('retire',),timer.runner.RETIRE,timer.runner.END);ram=self._snapshot(p)
            self._clear(p,ram,('commit',),commit.ENTRY,commit.END,extra_blocks=[
                shared.block(ram,snap['record'],struct.pack('<I',5))])
            self.completions.append(self.completed);self.busy=False
            self.progress('Fusion ended; both original fighters restored');self.resume(p);return True
        except Exception as exc:
            self.failure=str(exc);self.progress(self.failure);raise
        finally:
            if self._ram_buffer is not None:self._ram_buffer.invalidate()
            self._ram_buffer=None
