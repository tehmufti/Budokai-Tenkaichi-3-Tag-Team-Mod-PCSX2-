"""Fake transport executes the real emitted atomic defusion without PCSX2."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import fusion_duration as timer
import fusion_duration_worker as worker
import fusion_duration_commit as restore
import body_swap_commit as commit
import body_swap_resources as resources
import native_preparation as native
import test_fusion_duration as tests
import test_body_swap_worker as shared


class FrameCpu(tests.Cpu):
    def __init__(self,ram):super().__init__(ram,{'blocks':[]});self.fcr31=0
    def extra_instruction(self,ins,pc):
        op,rs,rt=ins>>26,(ins>>21)&31,(ins>>16)&31
        if op==17 and rs in (2,6):
            if rs==2:self.r[rt]=self.fcr31
            else:self.fcr31=self.r[rt]&0xFFFFFFFF
            return None
        return super().extra_instruction(ins,pc)


class Client(shared.Client):
    def write(self,p,data):
        self.ram[p:p+len(data)]=data
        if p==timer.JOB_CONTROL+4:self.job(struct.unpack('<I',data)[0])

    def job(self,request):
        target=self.read_u32(timer.JOB_CONTROL+24);entry=self.read_u32(timer.JOB_CONTROL+20)
        name={resources.IO_CONTROL:'io',resources.STAGE_CONTROL:'stage',commit.CONTROL:'commit',timer.runner.RETIRE_CONTROL:'retire'}[target]
        self.jobs.append(name);status=self.fail.get(name,5);cpu=FrameCpu(self.ram)
        cpu.callbacks[timer.OLD]=lambda m:None
        def boundary(m):
            self.ram[:]=m.buffer
            self.frame_stack=m.r[29]
            if status==5:getattr(self,name)()
            if name!='commit' or status!=5:self.write_u32(target+4,status)
            m.buffer[:]=self.ram
        cpu.callbacks[entry]=boundary
        # Execute the emitted frame, scope, receipt-state dispatch and JOB
        # protocol. A prematurely completed receipt suppresses this ACK.
        cpu.run(timer.FRAME);self.ram[:]=cpu.buffer
        assert self.read_u32(timer.JOB_CONTROL+8)==request,'Guest FRAME did not acknowledge the held job'

    def retire(self):
        job=self.worker.owned['retire']
        if 'configuration' not in job:return super().retire()
        import fusion_audio_restore as audio
        cpu=tests.Cpu(bytes(self.ram),job);cpu.w(audio.CONTROL,1);self.audio_uploads=[]
        cpu.callbacks[0x124C38]=lambda m:self.audio_uploads.append((m.r[4],m.r[5],m.r[6]))
        cpu.callbacks[0x124E60]=lambda m:m.r.__setitem__(2,1)
        cpu.callbacks[0x265AD0]=lambda m:None
        cpu.callbacks[0x125128]=lambda m:None
        cpu.run(audio.ENTRY);self.ram[:]=cpu.buffer
        assert self.u(audio.CONTROL+4)==5

    def commit(self):
        t=tests.CommitTests();t.ram=bytes(self.ram);t.snap=self.snapshot;t.manifest=self.worker.owned['commit']
        t.receipt=self.loaded[self.snapshot['side']]
        cpu,calls=t.machine();cpu.r[29]=self.frame_stack-0x100
        cpu.run(commit.ENTRY);self.ram[:]=cpu.buffer;self.commit_calls=calls


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ram,cls.snap,cls.receipt=tests.held_fixture()

    def prepared(self):
        ram=bytearray(self.ram);r=self.receipt
        for at,data in timer.program(timer.OLD,timer.feed.DRAW):ram[at:at+len(data)]=data
        struct.pack_into('<I',ram,timer.CONTROL+28,self.snap['side'])
        struct.pack_into('<I',ram,r['staged_model']+4,0);struct.pack_into('<I',ram,timer.core.MODELS+4*r['staged_id'],0)
        p=Client(ram,[r]);p.snapshot=self.snap
        def apply(client,manifest):
            self.assertEqual((client.u(native.CONTROL+16),client.u(native.CONTROL+20)),(1,1))
            for block in manifest['blocks']:
                data=bytes.fromhex(block['data_hex']);at=block['address']
                self.assertEqual(client.read(at,len(data)).hex(),block['expected_hex'],hex(at));client.write(at,data)
        def resume(client):client.events.append('resume');client.write_u32(native.CONTROL+16,0)
        w=worker.Worker(read_ram=lambda client:bytes(client.ram),apply=apply,resume=resume,clock=lambda:0,sleep=lambda _:None)
        w.active=True;p.worker=w;return p,w

    def test_native_commit_round_trip_releases_only_after_owned_scratch_cleanup(self):
        p,w=self.prepared();self.assertTrue(w.poll(p))
        self.assertEqual(p.jobs[:3],['io','stage','commit']);self.assertEqual(p.events[-1],'resume')
        self.assertEqual(p.audio_uploads,[(16,p.u(p.u(0x2FF11C)+44),0)])
        self.assertEqual(w.owned,{});self.assertEqual(p.u(timer.RECORDS),5)
        self.assertEqual(p.u(timer.part.CONSUMED)&4,0);self.assertEqual(len(w.completions),1)
        self.assertFalse(any(p.read(resources.IO,0x50000)))
        self.assertEqual(sum(p.u(row['row']+64) for row in self.snap['rows']),10000)

    def test_frame_dispatches_retirement_after_actual_commit_before_final_publication(self):
        p,w=self.prepared();observed=[]
        def retirement(ram,owned,record,generation):
            observed.append((restore.u(ram,record),restore.u(ram,commit.CONTROL+4),generation))
            control=bytearray(40);struct.pack_into('<I',control,8,owned['manager'])
            return resources.parts_manifest(ram,[(timer.runner.RETIRE_CONTROL,bytes(control))],
                entry=timer.runner.RETIRE,control=timer.runner.RETIRE_CONTROL)
        with patch.object(worker,'retirement_memory',side_effect=retirement):self.assertTrue(w.poll(p))
        self.assertEqual(observed,[(3,5,self.snap['generation'])]);self.assertEqual(p.jobs,['io','stage','commit','retire','retire'])
        self.assertEqual(p.u(timer.RECORDS),5);self.assertEqual(w.retained,[])

    def test_retirement_native_audit_uses_fusion_receipt_and_generation(self):
        p,w=self.prepared();seen={}
        def capture(ram,owned,*,body_context=None):
            seen.update(body_context);raise ValueError('audit boundary')
        with patch.object(worker.retire.prior,'capture',side_effect=capture):
            with self.assertRaisesRegex(ValueError,'audit boundary'):
                worker.retirement_memory(p.ram,dict(group=14,manager=self.snap['world']['manager']),self.snap['record'],self.snap['generation'])
        self.assertEqual(seen['commit_guards'],[(commit.CONTROL+4,5),(self.snap['record'],3),
            (self.snap['record']+72,self.snap['generation']),(timer.CONTROL+4,self.snap['world']['manager'])])

    def test_staging_failure_preserves_consumed_partner_and_keeps_hold(self):
        p,w=self.prepared();p.fail['stage']=120
        with self.assertRaisesRegex(RuntimeError,'stage failed'):w.poll(p)
        self.assertTrue(w.failure);self.assertEqual(p.u(native.CONTROL+16),1)
        self.assertEqual(p.u(timer.part.CONSUMED)&4,4);self.assertNotIn('resume',p.events)

    def test_a_defusion_without_room_is_postponed_never_held(self):
        """Live (after3, Oct 16): a defusion right after the extras' transformations met no free
        resource record, failed its IO under the expiry hold and the match stayed held
        (TTM-MATCH-08). Without room it now goes back to the fused countdown and releases."""
        p,w=self.prepared();notes=[];w.progress=notes.append
        pool=p.u(worker.resources.preload.REGISTRY_GLOBAL);p.write_u32(pool+69128,0)
        record=timer.RECORDS+self.snap['side']*timer.STRIDE
        self.assertEqual(worker.defusion_shortage(bytes(p.ram),self.snap['side']),'no spare model slot')
        self.assertFalse(w.poll(p))
        self.assertEqual(p.jobs,[]);self.assertEqual(p.events,['resume']);self.assertFalse(w.failure)
        self.assertEqual((p.u(record),p.u(record+4)),(2,worker.POSTPONE_UPDATES))
        self.assertEqual(p.u(native.CONTROL+16),0);self.assertIn('continues for now',notes[0])
        p.write_u32(record,3);p.write_u32(native.CONTROL+16,1);p.write_u32(native.CONTROL+20,1)
        self.assertFalse(w.poll(p));self.assertEqual(p.u(record+4),2*worker.POSTPONE_UPDATES,'each retry waits longer')
        self.assertEqual(p.jobs,[]);self.assertEqual(len(notes),1,'one note per reason')

    def test_the_extra_worker_hands_the_fused_receipt_to_the_defusion(self):
        """Live (after6): a defused extra's next transformation found the reload worker still
        naming the fused bundle and held the match (owned resource identity changed)."""
        original=(self.ram,self.snap,self.receipt)
        try:
            self.ram,self.snap,self.receipt=tests.held_fixture(2)
            p,w=self.prepared();side=self.snap['side']
            fused=p.u(p.u(timer.core.MODELS+4*p.u(p.u(timer.core.POINTERS+4*side)+12))+20)
            other={'resource':0x12345678}
            extra=SimpleNamespace(form_job=None,resources={side:{'resource':fused},9:other},retained={})
            self.assertTrue(w.poll(p,reload_worker=extra))
            self.assertNotIn(side,extra.resources);self.assertIs(extra.resources[9],other)
        finally:self.ram,self.snap,self.receipt=original

    def test_foreign_worker_transaction_is_not_borrowed(self):
        p,w=self.prepared();p.write_u32(timer.body.CONTROL,timer.body.MAGIC);p.write_u32(timer.body.CONTROL+16,3)
        with self.assertRaisesRegex(RuntimeError,'both claim'):w.poll(p,body_worker=SimpleNamespace(busy=True))
        self.assertEqual(p.jobs,[]);p.write_u32(timer.body.CONTROL+16,0)
        self.assertFalse(w.poll(p,reload_worker=SimpleNamespace(form_job=object())))
        self.assertEqual(p.jobs,[])
        with self.assertRaisesRegex(RuntimeError,'still owns'):
            w.poll(p,body_worker=SimpleNamespace(busy=False,owned={'commit':object()}))
        self.assertEqual(p.jobs,[])


if __name__=='__main__':unittest.main()
