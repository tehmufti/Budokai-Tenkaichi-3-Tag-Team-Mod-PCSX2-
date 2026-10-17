import struct
import unittest
from unittest.mock import patch

import extra_reload_worker as worker
from test_extra_reload_commit import SOURCE
from camera_snapshot import read_ram


class Client:
    def __init__(self,ram):
        self.ram=bytearray(ram);self.events=[];self.fail=None
        # Background guest simulation: 'start' reserves the record and buffers
        # on the publishing frame, ('refuse',status) acknowledges without
        # starting, 'stall' never answers. frames advances the presentation
        # counter on every read so a host frame bound can expire offline.
        self.background='start';self.frames=None
    def read(self,p,n):return bytes(self.ram[p:p+n])
    def read_u32(self,p):
        if p==worker.native.CONTROL+40 and self.frames is not None:
            self.frames+=1;self.write(p,struct.pack('<I',self.frames))
        return struct.unpack_from('<I',self.ram,p)[0]
    def write(self,p,data):self.ram[p:p+len(data)]=data
    def write_u32(self,p,v):
        self.write(p,struct.pack('<I',v))
        if p==worker.runner.BG_CONTROL+4:
            if self.background=='start':
                self.write(worker.io.CONTROL+4,struct.pack('<I',2))
            elif self.background!='stall':
                self.write(worker.runner.BG_CONTROL+12,struct.pack('<I',self.background[1]))
                self.write(worker.runner.BG_CONTROL+8,struct.pack('<I',v))
        if p==worker.runner.CONTROL+4:
            target=self.read_u32(worker.runner.CONTROL+24);status=self.fail or 5
            self.write(target+4,struct.pack('<I',status))
            for at,value in ((worker.runner.CONTROL+8,v),(worker.runner.CONTROL+12,status)):
                self.write(at,struct.pack('<I',value))
            if target==worker.commit.CONTROL:
                self.write(worker.commit.AI_META,struct.pack('<I',5));self.write(target+36,struct.pack('<I',1))


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ram=read_ram(SOURCE)

    def prepared(self):
        p=Client(self.ram);p.write_u32(worker.native.CONTROL+16,0)
        manifest=worker.install_memory(p.ram)
        for b in manifest['blocks']:p.write(b['address'],bytes.fromhex(b['data_hex']))
        p.write_u32(worker.requests.CONTROL,1)
        count=p.read_u32(worker.runner.core.MODE+4);actor=p.read_u32(worker.runner.core.POINTERS+8)
        mid=p.read_u32(actor+12);model=p.read_u32(worker.runner.core.MODELS+4*mid)
        values=(1,1,actor,mid,model,p.read_u32(model+12),0,1,*([0xFFFFFFFF]*3),2,p.read_u32(model+20),0,0,0)
        p.write(worker.requests.RECORDS,struct.pack('<16I',*values))
        def apply(client,m):
            self.assertEqual(client.read_u32(worker.native.CONTROL+16),1)
            for b in m['blocks']:
                data=bytes.fromhex(b['data_hex']);at=b['address']
                self.assertEqual(client.read(at,len(data)).hex(),b['expected_hex'])
                client.write(at,data)
            # A published runner request starts only after the complete native
            # transaction has been guarded and copied, never mid-packet.
            if any(b['address']==worker.runner.CONTROL+4 for b in m['blocks']):
                client.write_u32(worker.runner.CONTROL+4,client.read_u32(worker.runner.CONTROL+4))
            if any(b['address']==worker.runner.BG_CONTROL+4 for b in m['blocks']):
                client.write_u32(worker.runner.BG_CONTROL+4,client.read_u32(worker.runner.BG_CONTROL+4))
            client.events.append('apply')
        def quiet(client):
            client.events.append('quiet');client.write_u32(worker.native.CONTROL+16,1)
        def resume(client):client.events.append('resume');client.write_u32(worker.native.CONTROL+16,0)
        w=worker.Worker(read_ram=lambda c:bytes(c.ram),apply=apply,quiet=quiet,resume=resume,sleep=lambda _:None)
        w.active=True
        # Stage execution is represented by bounded control callbacks in these
        # orchestration tests. Native receipt/free validation has its own suite.
        w._complete_resources=lambda client,ram,job:ram
        return p,w

    def builders(self,p):
        def build(module,ram,*args,**kwargs):
            p.events.append(module.__name__);self.assertTrue(kwargs['quiet'])
            # A background IO body is built BEFORE its claim: the claim, the
            # body and the request are one guarded native transaction.
            self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1 if kwargs.get('background') else 2)
            d=bytearray(40);struct.pack_into('<2I',d,8,p.read_u32(worker.runner.core.ACTORS),p.read_u32(worker.runner.core.POINTERS+8))
            return dict(entry=module.ENTRY,control=module.CONTROL,blocks=[dict(address=module.CONTROL,
                        expected_hex=bytes(ram[module.CONTROL:module.CONTROL+40]).hex(),data_hex=d.hex())])
        return [patch.object(module,'build_memory',side_effect=lambda ram,*a,_m=module,**k:build(_m,ram,*a,**k))
                for module in (worker.io,worker.stage,worker.commit)]

    def test_claim_precedes_all_stages_and_success_releases_only_after_final_checks(self):
        p,w=self.prepared();a,b,c=self.builders(p)
        with a,b,c:self.assertTrue(w.poll(p))
        self.assertEqual(p.events[0],'quiet');self.assertEqual(p.events[-1],'resume')
        self.assertEqual([x for x in p.events if x.startswith('extra_reload_')],
                         ['extra_reload_service','extra_reload_stage','extra_reload_commit'])
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),5);self.assertEqual(p.read_u32(worker.requests.RECORDS+52),5)

    def test_stage_failure_keeps_hold_and_stops_later_stages(self):
        p,w=self.prepared();p.fail=134;a,b,c=self.builders(p)
        with a,b,c,self.assertRaisesRegex(RuntimeError,'io failed'):w.poll(p)
        self.assertEqual(p.read_u32(worker.native.CONTROL+16),1)
        self.assertNotIn('resume',p.events);self.assertNotIn('extra_reload_stage',p.events)
        self.assertTrue(w.failure);self.assertFalse(w.poll(p))

    def test_owner_busy_or_changed_generation_does_not_claim(self):
        p,w=self.prepared();actor=p.read_u32(worker.runner.core.POINTERS+8)
        oldread=w.read_ram;w.read_ram=lambda _:self.fail('No full RAM reads while owner remains busy')
        p.write_u32(actor+0x948,15);self.assertFalse(w.poll(p));self.assertEqual(p.events,[])
        w.read_ram=oldread
        p.write_u32(actor+0x948,11);oldquiet=w.quiet
        def quiet(client):oldquiet(client);client.write_u32(worker.requests.RECORDS,2)
        w.quiet=quiet;self.assertFalse(w.poll(p));self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1)
        self.assertEqual(p.events,['quiet','resume'])

    def test_arena_ownership_defers_new_reload_before_any_hold_or_full_read(self):
        for flag in (0x800,0x1000,0x2000):
            p,w=self.prepared();p.write_u32(worker.SCENE_FLAGS,flag)
            self.assertIsNone(worker.candidate(p.ram))
            w.read_ram=lambda _:self.fail('Arena work must not take a full snapshot or quiet hold')
            self.assertFalse(w.poll(p));self.assertEqual(p.events,[])
            self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1)

    def registry(self,p):
        return p.read_u32(worker.preload.REGISTRY_GLOBAL)+worker.preload.REGISTRY_OFFSET

    def test_room_is_checked_before_any_claim_hold_or_full_read(self):
        """io/stage fail only after the claim, keeping the match held. At eight
        or ten fighters records, model slots and texture groups can run out,
        so a request that cannot complete waits unclaimed instead."""
        def records_full(p):
            for i in range(12):
                at=self.registry(p)+56*i+48;p.write_u32(at,p.read_u32(at)|1)
        def stale_first_free(p):
            at=next(self.registry(p)+56*i for i in range(12)
                    if not p.read_u32(self.registry(p)+56*i+48)&1)
            p.write_u32(at+16,0x02000000)
        pool=lambda p:p.read_u32(worker.preload.REGISTRY_GLOBAL)
        cases=((records_full,'no free resource record'),
               (stale_first_free,'no free resource record'),
               (lambda p:p.write_u32(pool(p)+69128,0),'no spare model slot'),
               (lambda p:p.write_u32(pool(p)+439156,0x7FFF),'no spare texture group'))
        for mutate,reason in cases:
            p,w=self.prepared();mutate(p)
            with self.subTest(reason=reason):
                self.assertEqual(worker.capacity_shortage(p.ram),reason)
                self.assertIsNone(worker.candidate(p.ram))
                w.read_ram=lambda _:self.fail('A request without room must not take a full snapshot')
                notes=[];w.progress=notes.append
                self.assertFalse(w.poll(p));self.assertEqual(p.events,[])
                self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1)
                self.assertIn(reason,notes[0])

    def test_a_claimed_form_still_finishes_without_room(self):
        p,_=self.prepared();p.write_u32(p.read_u32(worker.preload.REGISTRY_GLOBAL)+69128,0)
        self.assertEqual(worker.capacity_shortage(p.ram),'no spare model slot')
        self.assertIsNone(worker.candidate(p.ram))
        p.write_u32(worker.requests.RECORDS+4,4)
        self.assertIsNotNone(worker.candidate(p.ram,statuses=(4,)))

    def test_a_claimed_form_is_not_refused_by_waits_that_cannot_clear_under_the_hold(self):
        """A leader's own reload or a throw record may appear the frame a form is
        acknowledged; under the guest hold neither can clear, and the commit
        borrows no disc IO, so only a new claim waits for them."""
        manager=lambda p:p.read_u32(worker.requests.CONTROL+4)
        for veto in ('leader_reload','throw'):
            p,_=self.prepared()
            if veto=='leader_reload':p.write_u32(manager(p)+604,p.read_u32(manager(p)+608)+1)
            else:p.write_u32(0x0778F100+4*2,1)
            with self.subTest(veto=veto):
                self.assertIsNone(worker.candidate(p.ram))
                p.write_u32(worker.requests.RECORDS+4,4)
                self.assertIsNotNone(worker.candidate(p.ram,statuses=(4,)))

    def test_heap_room_uses_the_real_file_ceiling_and_backs_off_full_reads(self):
        p,w=self.prepared()
        self.assertGreaterEqual(worker.largest_free_block(p.ram),worker.heap.NEED)
        self.assertIsNone(worker.capacity_shortage(p.ram))
        # One used block and a free tail, sized as the guest admission reads
        # it (the block's header size word): exactly NEED fits, a word less not.
        start,stop=worker.heap.START,worker.heap.STOP
        def tail_of(tail):
            ram=bytearray(p.ram);used=stop-start-tail
            struct.pack_into('<7I',ram,start,0x53484254,1,0,4,used,start+32,used-36);struct.pack_into('<I',ram,start+used-4,used)
            struct.pack_into('<7I',ram,start+used,0x53484254,0,0,4,tail,0,tail-32);struct.pack_into('<I',ram,stop-4,tail)
            return ram
        self.assertIsNone(worker.capacity_shortage(tail_of(worker.heap.NEED)))
        ram=tail_of(worker.heap.NEED-4)
        self.assertEqual(worker.capacity_shortage(ram),'not enough free memory')
        p.ram=ram;reads=[]
        w.read_ram=lambda c:(reads.append(1),bytes(c.ram))[1]
        clock=[100.0];w.clock=lambda:clock[0]
        self.assertFalse(w.poll(p));self.assertFalse(w.poll(p));self.assertEqual(len(reads),1)
        clock[0]+=1.5;self.assertFalse(w.poll(p));self.assertEqual(len(reads),2)
        self.assertEqual(p.events,[])
        # The launcher names the shortage the full read found.
        notes=[];w.progress=notes.append;w.waiting=None
        clock[0]+=1.5;w.poll(p);self.assertIn('not enough free memory',notes[-1])

    def test_arena_start_between_observation_and_quiet_releases_without_claim(self):
        p,w=self.prepared();oldquiet=w.quiet
        def quiet(client):oldquiet(client);client.write_u32(worker.SCENE_FLAGS,0x2000)
        w.quiet=quiet;self.assertFalse(w.poll(p))
        self.assertEqual(p.events,['quiet','resume'])
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1)

    def test_rearm_requires_exact_owned_code_and_restores_original_analysis_bytes(self):
        p,w=self.prepared();entry=worker.io.ENTRY
        p.write(entry,b'abcd');p.write_u32(worker.io.CONTROL+4,5)
        w.owned={'io':dict(blocks=[dict(address=entry,data_hex=b'abcd'.hex(),expected_hex=b'old!'.hex(),restore_hex='00000000')])}
        self.assertEqual(w._analysis_view(p.ram)[entry:entry+4],bytes(4))
        p.write(entry,b'bad!')
        with self.assertRaisesRegex(RuntimeError,'Owned reload code changed'):w._analysis_view(p.ram)

    def form_prepared(self):
        import extra_reload_forms as forms
        p,w=self.prepared();actor=p.read_u32(worker.runner.core.POINTERS+8)
        model=p.read_u32(worker.runner.core.MODELS+4*p.read_u32(actor+12))
        target=p.read_u32(model+12)+1
        for at,value in ((forms.CONTROL,1),(forms.FORM_ENABLE,1),(actor+0x948,238),
                         (actor+0x12D0,target),(actor+0x12D4,0),(actor+0x12E0,0),
                         (worker.requests.RECORDS+20,target),(worker.requests.RECORDS+28,0),
                         (worker.requests.RECORDS+56,1),(worker.requests.RECORDS+60,238)):
            p.write_u32(at,value)
        w.forms=True
        return p,w,actor,model,target

    def test_form_stages_hidden_model_then_waits_for_native_ack_before_commit(self):
        p,w,actor,model,target=self.form_prepared();a,b,_=self.builders(p)
        with a,b,patch.object(worker.commit,'build_memory') as commit:
            self.assertFalse(w.poll(p));commit.assert_not_called()
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),3)
        self.assertEqual(p.read_u32(model+12),target-1)
        self.assertFalse(w.poll(p));self.assertFalse(p.read_u32(worker.native.CONTROL+16))
        p.write_u32(worker.requests.RECORDS+4,4)
        p.write_u32(worker.native.CONTROL+16,1);p.write_u32(worker.native.CONTROL+20,1)
        def build(ram,**kwargs):
            self.assertEqual(kwargs,dict(quiet=True,retire_staged=True,form=True))
            return dict(entry=worker.commit.ENTRY,control=worker.commit.CONTROL,blocks=[
                worker.word_block(ram,model+12,target),
                dict(address=worker.commit.CONTROL,expected_hex=bytes(ram[worker.commit.CONTROL:worker.commit.CONTROL+40]).hex(),data_hex=bytes(40).hex())])
        with patch.object(worker.commit,'build_memory',side_effect=build):self.assertTrue(w.poll(p))
        self.assertEqual(p.read_u32(model+12),target);self.assertEqual(p.read_u32(worker.requests.RECORDS+4),5)
        self.assertIsNone(w.form_job);self.assertEqual(p.events[-1],'resume')

    def test_form_ack_timeout_or_displacement_holds_same_world_for_recovery(self):
        for change in ('elapsed','action','status'):
            p,w,actor,_,_=self.form_prepared();a,b,_=self.builders(p)
            with a,b:self.assertFalse(w.poll(p))
            at,value={'elapsed':(worker.native.CONTROL+40,w.form_frame+901),
                      'action':(actor+0x948,15),'status':(worker.requests.RECORDS+4,1)}[change]
            p.write_u32(at,value)
            with self.subTest(change=change),self.assertRaisesRegex(RuntimeError,'acknowledgment was interrupted'):w.poll(p)
            self.assertEqual(p.read_u32(worker.native.CONTROL+16),1);self.assertTrue(w.failure)
            self.assertFalse(w.poll(p))

    def test_old_form_job_does_not_hold_or_touch_new_world(self):
        p,w,_,_,_=self.form_prepared();a,b,_=self.builders(p)
        with a,b:self.assertFalse(w.poll(p))
        p.write_u32(worker.runner.core.ACTORS,0x2300000);before=list(p.events)
        self.assertFalse(w.poll(p));self.assertEqual(p.events,before)
        self.assertFalse(w.active);self.assertIsNone(w.form_job)

    def test_form_ack_deadline_excludes_stage_pause_and_preserves_prior_active_age(self):
        p,w,actor,_,_=self.form_prepared();a,b,_=self.builders(p)
        with a,b:self.assertFalse(w.poll(p))
        p.write_u32(worker.native.CONTROL+40,w.form_frame+600);self.assertFalse(w.poll(p))
        self.assertEqual(w.form_elapsed,600)
        for flag in (0x2000,0x100,0x800,0):
            p.write_u32(worker.SCENE_FLAGS,flag)
            p.write_u32(worker.native.CONTROL+40,w.form_frame+1200);self.assertFalse(w.poll(p))
            self.assertEqual(w.form_elapsed,600);self.assertFalse(w.failure)
        p.write_u32(worker.native.CONTROL+40,w.form_frame+301)
        with self.assertRaisesRegex(RuntimeError,'acknowledgment was interrupted'):w.poll(p)
        self.assertEqual(w.form_elapsed,901)

    def test_form_acknowledged_before_arena_start_can_commit_and_release_own_hold(self):
        p,w,actor,model,target=self.form_prepared();a,b,_=self.builders(p)
        with a,b:self.assertFalse(w.poll(p))
        p.write_u32(worker.requests.RECORDS+4,4);p.write_u32(worker.SCENE_FLAGS,0x2000)
        p.write_u32(worker.native.CONTROL+16,1);p.write_u32(worker.native.CONTROL+20,1)
        def build(ram,**kwargs):
            return dict(entry=worker.commit.ENTRY,control=worker.commit.CONTROL,blocks=[
                worker.word_block(ram,model+12,target),
                dict(address=worker.commit.CONTROL,expected_hex=bytes(ram[worker.commit.CONTROL:worker.commit.CONTROL+40]).hex(),data_hex=bytes(40).hex())])
        with patch.object(worker.commit,'build_memory',side_effect=build):self.assertTrue(w.poll(p))
        self.assertEqual(p.events[-1],'resume');self.assertEqual(p.read_u32(worker.SCENE_FLAGS),0x2000)
        self.assertIsNone(w.form_job)

    def test_resource_receipts_keep_original_and_rearm_only_owned_completed_retirements(self):
        p,w=self.prepared();w._complete_resources=worker.Worker._complete_resources.__get__(w)
        first=dict(physical=2,resource=0x3000000);second=dict(physical=2,resource=0x3100000)
        job=dict(physical=2,old_resource=0x2000000,manager=p.read_u32(worker.runner.core.ACTORS),owner_action=11)
        with patch.object(worker.retire,'receipt',return_value=first),patch.object(worker.retire,'build_memory') as build:
            w._complete_resources(p,bytes(p.ram),job);build.assert_not_called()
        self.assertEqual(w.resources[2],first)
        def build(ram,owned):
            self.assertEqual(owned,first)
            return dict(entry=worker.retire.ENTRY,control=worker.retire.CONTROL,blocks=[
                dict(address=worker.retire.CONTROL,expected_hex=bytes(ram[worker.retire.CONTROL:worker.retire.CONTROL+40]).hex(),data_hex=bytes(40).hex())])
        p.write_u32(worker.native.CONTROL+16,1);job['old_resource']=first['resource']
        with patch.object(worker.retire,'receipt',return_value=second),patch.object(worker.retire,'build_memory',side_effect=build):
            w._complete_resources(p,bytes(p.ram),job)
        self.assertEqual(w.resources[2],second);self.assertEqual(w.retained[2],[])
        self.assertIn('retire',w.owned);self.assertEqual(p.read_u32(worker.retire.CONTROL+4),5)

    def test_unknown_retirement_reference_defers_before_mutation_and_preserves_playability(self):
        p,w=self.prepared();w._complete_resources=worker.Worker._complete_resources.__get__(w)
        old=dict(physical=2,resource=0x3000000);new=dict(physical=2,resource=0x3100000)
        w.resources[2]=old;job=dict(physical=2,old_resource=old['resource'])
        with patch.object(worker.retire,'receipt',return_value=new),patch.object(worker.retire,'build_memory',side_effect=ValueError('unknown live reference')):
            w._complete_resources(p,bytes(p.ram),job)
        self.assertEqual(w.retained[2],[old]);self.assertFalse(w.failure);self.assertEqual(p.events,[])
        self.assertEqual(w.retirement_notes,['unknown live reference'])

    # ---- unheld background transformation IO -----------------------------

    def background_prepared(self):
        p,w,actor,model,target=self.form_prepared()
        w.background=True
        for at in (worker.runner.BG_CONTROL,worker.runner.BG_CONTROL+4,worker.runner.BG_CONTROL+8):
            p.write_u32(at,0)
        p.write_u32(worker.runner.BG_CONTROL,worker.runner.BG_MAGIC)
        return p,w,actor,model,target

    def finish_background(self,p,status=5,result=5,calls=52):
        p.write_u32(worker.io.CONTROL+4,status)
        p.write_u32(worker.runner.BG_CONTROL+12,result)
        p.write_u32(worker.runner.BG_CONTROL+28,calls)
        p.write_u32(worker.runner.BG_CONTROL+8,p.read_u32(worker.runner.BG_CONTROL+4))

    def commit_builder(self,ram,model,target):
        return dict(entry=worker.commit.ENTRY,control=worker.commit.CONTROL,blocks=[
            worker.word_block(ram,model+12,target),
            dict(address=worker.commit.CONTROL,
                 expected_hex=bytes(ram[worker.commit.CONTROL:worker.commit.CONTROL+40]).hex(),
                 data_hex=bytes(40).hex())])

    def test_a_background_form_freezes_combat_in_three_short_holds(self):
        p,w,actor,model,target=self.background_prepared();a,b,_=self.builders(p)
        with a,b,patch.object(worker.commit,'build_memory') as commit:
            self.assertFalse(w.poll(p));commit.assert_not_called()
        # Hold A': one guarded transaction carrying the claim, the IO body and
        # the background request, released as soon as the guest has reserved.
        self.assertEqual(p.events,['quiet','extra_reload_service','apply','resume'])
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),2)
        self.assertEqual(p.read_u32(worker.io.CONTROL+4),2)
        self.assertEqual(w.form_phase,'io');self.assertIsNotNone(w.form_job)
        self.assertFalse(p.read_u32(worker.native.CONTROL+16))
        # The unheld window: no hold, no build, nothing written.
        p.events.clear()
        with a,b:self.assertFalse(w.poll(p));self.assertFalse(w.poll(p))
        self.assertEqual(p.events,[]);self.assertEqual(w.form_phase,'io')
        # Second short hold: today's staging, then row+4=3, then release.
        self.finish_background(p)
        with a,b,patch.object(worker.commit,'build_memory') as commit:
            self.assertFalse(w.poll(p));commit.assert_not_called()
        self.assertEqual(p.events[0],'quiet');self.assertEqual(p.events[-1],'resume')
        self.assertIn('extra_reload_stage',p.events)
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),3)
        self.assertEqual(w.form_phase,'commit')
        self.assertEqual(p.read_u32(model+12),target-1)
        # Hold B is today's unchanged ACK commit.
        p.write_u32(worker.requests.RECORDS+4,4)
        p.write_u32(worker.native.CONTROL+16,1);p.write_u32(worker.native.CONTROL+20,1)
        with patch.object(worker.commit,'build_memory',
                          side_effect=lambda ram,**k:self.commit_builder(ram,model,target)):
            self.assertTrue(w.poll(p))
        self.assertEqual(p.read_u32(model+12),target)
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),5)
        self.assertIsNone(w.form_job);self.assertIsNone(w.form_phase)

    def test_the_hold_a_transaction_carries_no_ordinary_runner_request(self):
        """The held runner only acknowledges at status5 or >=100, so a pending
        ordinary request would outlive the whole read and the background runner
        refuses while one is pending."""
        p,w,_,_,_=self.background_prepared();a,b,_=self.builders(p)
        seen=[]
        real=w.apply
        def apply(client,m):
            seen.append([block['address'] for block in m['blocks']]);real(client,m)
        w.apply=apply
        with a,b:self.assertFalse(w.poll(p))
        self.assertEqual(len(seen),1)
        addresses=seen[0]
        for at in (worker.runner.CONTROL+4,worker.runner.CONTROL+8,worker.runner.CONTROL+12,
                   worker.runner.CONTROL+16):
            self.assertNotIn(at,addresses)
        self.assertEqual(addresses[0],worker.requests.RECORDS+4)
        self.assertEqual(addresses[-1],worker.runner.BG_CONTROL+4)
        self.assertEqual(p.read_u32(worker.runner.CONTROL+4),p.read_u32(worker.runner.CONTROL+8))
        self.assertEqual(p.read_u32(worker.runner.CONTROL+4),0)

    def test_a_start_that_never_answers_unwinds_the_whole_claim_and_retries(self):
        p,w,_,_,_=self.background_prepared();a,b,_=self.builders(p)
        p.background='stall';p.frames=0
        before=bytes(p.ram[worker.io.ENTRY:worker.io.CONTROL+0x100])
        with a,b:self.assertFalse(w.poll(p))
        self.assertEqual(p.events[-1],'resume')
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1,'the request is simply retried')
        self.assertEqual(bytes(p.ram[worker.io.ENTRY:worker.io.CONTROL+0x100]),before)
        self.assertEqual(p.read_u32(worker.runner.BG_CONTROL+4),0)
        self.assertEqual(p.read_u32(worker.runner.BG_CONTROL+8),0)
        self.assertIsNone(w.form_job);self.assertIsNone(w.form_phase)
        self.assertNotIn('io',w.owned);self.assertFalse(w.failure)

    def test_a_refused_start_unclaims_transient_reasons_and_parks_the_rest_at5(self):
        for status,expected in ((112,1),(130,1),(131,1),(110,5),(120,5)):
            p,w,_,_,_=self.background_prepared();a,b,_=self.builders(p)
            p.background=('refuse',status)
            with a,b:self.assertFalse(w.poll(p))
            with self.subTest(status=status):
                self.assertEqual(p.read_u32(worker.requests.RECORDS+4),expected)
                self.assertEqual(p.read_u32(worker.runner.BG_CONTROL+4),0)
                self.assertEqual(p.events[-1],'resume')
                self.assertIsNone(w.form_job);self.assertFalse(w.failure)
                self.assertFalse(p.read_u32(worker.native.CONTROL+16))

    def test_an_io_failure_after_submission_parks_the_actor_at5_never_at6(self):
        """forms.READY answers ready for3/4/5 only and the native action-236
        handler has no timeout, so status6 would park the fighter forever."""
        p,w,_,_,_=self.background_prepared();a,b,_=self.builders(p)
        with a,b:self.assertFalse(w.poll(p))
        self.finish_background(p,status=134,result=134)
        with a,b,patch.object(worker.stage,'build_memory') as stage:
            self.assertFalse(w.poll(p));stage.assert_not_called()
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),5)
        self.assertEqual(p.read_u32(worker.requests.RECORDS+52),134)
        self.assertEqual(p.read_u32(worker.requests.RECORDS+56),1,'the reviewed handshake still owns the row')
        self.assertEqual(p.events[-1],'resume');self.assertFalse(p.read_u32(worker.native.CONTROL+16))
        self.assertIsNone(w.form_job);self.assertFalse(w.failure)
        self.assertTrue(w.retirement_notes)
        self.assertTrue(w.active,'the worker keeps serving later requests')

    def test_an_owner_that_left_its_pose_while_loading_aborts_without_staging(self):
        p,w,actor,_,_=self.background_prepared();a,b,_=self.builders(p)
        with a,b:self.assertFalse(w.poll(p))
        self.finish_background(p)
        p.write_u32(actor+0x948,15)
        with a,b,patch.object(worker.stage,'build_memory') as stage:
            self.assertFalse(w.poll(p));stage.assert_not_called()
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),5)
        self.assertEqual(p.read_u32(worker.requests.RECORDS+52),110)
        self.assertFalse(w.failure);self.assertFalse(p.read_u32(worker.native.CONTROL+16))

    def test_capacity_lost_during_the_unheld_window_aborts_instead_of_holding(self):
        p,w,_,_,_=self.background_prepared();a,b,_=self.builders(p)
        with a,b:self.assertFalse(w.poll(p))
        self.finish_background(p)
        with a,patch.object(worker.stage,'build_memory',side_effect=ValueError('no texture group left')):
            self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),5)
        self.assertEqual(p.read_u32(worker.requests.RECORDS+52),130)
        self.assertFalse(w.failure);self.assertEqual(p.events[-1],'resume')

    def test_the_host_never_writes_while_the_background_runner_is_armed(self):
        p,w,_,_,_=self.background_prepared();a,b,_=self.builders(p)
        with a,b:self.assertFalse(w.poll(p))
        p.events.clear()
        p.write_u32(worker.native.CONTROL+40,p.read_u32(worker.native.CONTROL+40)+5000)
        with a,b,self.assertRaisesRegex(RuntimeError,'never acknowledged'):w.poll(p)
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),2)
        self.assertEqual(p.read_u32(worker.io.CONTROL+4),2)
        self.assertEqual(p.read_u32(worker.native.CONTROL+16),1,'held for recovery')
        self.assertTrue(w.failure)

    def test_a_missing_background_cave_keeps_todays_fully_held_path(self):
        p,w,actor,model,target=self.form_prepared();a,b,_=self.builders(p)
        self.assertFalse(w.background)
        with a,b,patch.object(worker.commit,'build_memory') as commit:
            self.assertFalse(w.poll(p));commit.assert_not_called()
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),3)
        self.assertEqual(w.form_phase,'commit')
        self.assertEqual(p.read_u32(worker.runner.BG_CONTROL+4),0)
        self.assertIn('extra_reload_stage',p.events)

    def test_cell_keeps_one_hold_across_its_auxiliary_and_form_loads(self):
        p,w,actor,_,_=self.background_prepared();a,b,_=self.builders(p)
        p.write_u32(actor+0x948,239);p.write_u32(worker.requests.RECORDS+60,239)
        with a,b,patch.object(worker.commit,'build_memory'):self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.runner.BG_CONTROL+4),0,'no background request for action239')
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),3)

    def test_a_busy_native_loader_defers_the_claim_before_any_hold(self):
        for address in (worker.runner.LOADER_STATE,worker.runner.LOADER_HANDLE,worker.runner.LOADER_PENDING):
            p,w,_,_,_=self.background_prepared()
            p.write_u32(address,1)
            with self.subTest(address=hex(address)):
                self.assertTrue(worker.loader_busy(p.ram))
                self.assertIsNone(worker.candidate(p.ram))
                w.read_ram=lambda _:self.fail('A busy loader must not take a hold or a full read')
                notes=[];w.progress=notes.append
                self.assertFalse(w.poll(p));self.assertEqual(p.events,[])
                self.assertIn('native loader',notes[0])
        p,w,_,_,_=self.background_prepared()
        p.write_u32(p.read_u32(worker.runner.TASK_FIFO)+12,1)
        self.assertTrue(worker.loader_busy(p.ram))
        p.write_u32(worker.runner.TASK_FIFO,0x102)
        self.assertFalse(worker.loader_busy(p.ram))

    def test_attach_refuses_a_prepared_match_with_a_stale_background_request(self):
        p,w,_,_,_=self.background_prepared()
        w.background=True;w.active=False
        p.write_u32(worker.runner.BG_CONTROL+4,3)
        with patch.object(w,'_background_service',return_value=True),\
             patch.object(worker.native,'arm',return_value=True),\
             self.assertRaisesRegex(ValueError,'Restart this prepared match'):
            w.attach(p)

    def test_poll_cadence_relaxes_while_the_read_runs_unheld(self):
        import fighter_updates
        w=worker.Worker()
        self.assertEqual(worker.poll_delay(w,.2),.2)
        w.form_job=object();w.form_phase='io'
        self.assertEqual(worker.poll_delay(w,.2),.05)
        self.assertEqual(fighter_updates.poll_delay(w,None,None,.2),.05)
        w.form_phase='commit'
        self.assertEqual(worker.poll_delay(w,.2),.01)
        self.assertEqual(fighter_updates.poll_delay(w,None,None,.2),.01)
        self.assertEqual(fighter_updates.poll_delay(w,None,None,.005),.005)

    def test_long_short_third_body_rearm_restores_and_keeps_guarding_old_tail(self):
        p,w=self.prepared();p.write_u32(worker.native.CONTROL+16,1)
        job=dict(manager=p.read_u32(worker.runner.core.ACTORS),physical=2,owner_action=11)
        def manifest(view,data):
            return dict(entry=worker.io.ENTRY,control=worker.io.CONTROL,blocks=[
                dict(address=worker.io.ENTRY,expected_hex=bytes(view[worker.io.ENTRY:worker.io.ENTRY+len(data)]).hex(),data_hex=data.hex()),
                dict(address=worker.io.CONTROL,expected_hex=bytes(view[worker.io.CONTROL:worker.io.CONTROL+40]).hex(),data_hex=bytes(40).hex())])
        for data in (b'A'*12,b'B'*4,b'C'*8):
            ram=bytes(p.ram);view=w._analysis_view(ram)
            self.assertEqual(view[worker.io.ENTRY:worker.io.ENTRY+12],bytes(12))
            w._install_stage(p,'io',ram,manifest(view,data),job)
            self.assertEqual(p.read(worker.io.ENTRY,12),data+bytes(12-len(data)))
        p.write(worker.io.ENTRY+10,b'X')
        with self.assertRaisesRegex(RuntimeError,'Owned reload code changed'):w._analysis_view(p.ram)

    # ---- TTM-MATCH-21 CPU fusion freeze (Oct 16) --------------------------------------------------------------------
    def crowded(self,p,used):
        """Mark texture groups until `used` are set, keeping the highest group free of live models."""
        pool=p.read_u32(worker.preload.REGISTRY_GLOBAL);groups=worker.stage.texture_groups(p.ram)
        bits=groups['used']
        for g in range(15):
            if (bits&0x7FFF).bit_count()>=used:break
            if g!=14 or used>=15:bits|=1<<g
        p.write_u32(pool+439156,bits);return pool

    def test_an_admitted_form_needs_one_free_group_not_the_costume_two_spare_rule(self):
        p,w,actor,model,target=self.form_prepared();self.crowded(p,13)
        self.assertEqual(worker.capacity_shortage(p.ram),'no spare texture group')
        self.assertIsNone(worker.capacity_shortage(p.ram,form=True))
        self.assertIsNotNone(worker.candidate(p.ram))
        p.write_u32(worker.requests.RECORDS+56,0)          # the same room for a costume row waits
        p.write_u32(actor+0x948,11);self.assertIsNone(worker.candidate(p.ram))
        p,w,_,_,_=self.form_prepared();pool=self.crowded(p,15)
        self.assertEqual(worker.capacity_shortage(p.ram,form=True),'no spare texture group')

    def test_a_transient_ai_alias_no_longer_defers_the_unheld_scan(self):
        p,w,_,_,_=self.form_prepared();p.write_u32(worker.runner.core.PAIR+4,1)
        self.assertIsNotNone(worker.candidate(p.ram))
        self.assertIsNone(worker.candidate(p.ram,specific=2),'the held recheck keeps the veto')

    def stalled(self,used=15):
        p,w,actor,model,target=self.form_prepared();self.crowded(p,used)
        notes=[];w.progress=notes.append
        p.write_u32(worker.native.CONTROL+40,1000)
        return p,w,notes

    def test_a_form_nobody_can_claim_is_cancelled_after_a_bounded_wait(self):
        p,w,notes=self.stalled()
        self.assertFalse(w.poll(p));self.assertEqual(p.events,[])
        p.write_u32(worker.native.CONTROL+40,1000+worker.PENDING_FORM_FRAMES)
        w.retry_at=0;self.assertFalse(w.poll(p));self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1)
        p.write_u32(worker.native.CONTROL+40,1001+worker.PENDING_FORM_FRAMES)
        w.retry_at=0;self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),5)
        self.assertEqual(p.read_u32(worker.requests.RECORDS+52),worker.FORM_CANCELLED)
        self.assertEqual(p.events,['quiet','apply','resume']);self.assertFalse(w.failure)
        self.assertTrue(any('Cancelled a transformation' in n and 'texture group' in n for n in notes),notes)
        self.assertEqual(p.read_u32(worker.native.CONTROL+16),0)

    def test_a_cancel_rechecks_the_request_under_the_hold(self):
        p,w,notes=self.stalled();self.assertFalse(w.poll(p))
        oldquiet=w.quiet
        def quiet(client):oldquiet(client);client.write_u32(worker.requests.RECORDS,9)  # republished meanwhile
        w.quiet=quiet;p.write_u32(worker.native.CONTROL+40,1001+worker.PENDING_FORM_FRAMES)
        w.retry_at=0;self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1);self.assertEqual(p.events,['quiet','resume'])

    def test_pauses_and_other_jobs_do_not_age_a_waiting_form(self):
        p,w,notes=self.stalled();self.assertFalse(w.poll(p))
        p.write_u32(worker.SCENE_FLAGS,0x100)               # a native pause/arena hold
        p.write_u32(worker.native.CONTROL+40,5000);w.retry_at=0;self.assertFalse(w.poll(p))
        p.write_u32(worker.SCENE_FLAGS,0)
        p.write_u32(worker.native.CONTROL+40,5001);w.retry_at=0;self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1)
        w.form_job=dict(manager=0);w.form_phase='commit'
        with patch.object(w,'_finish_form',return_value=False):self.assertFalse(w.poll(p))
        w.form_job=None;w.form_phase=None
        p.write_u32(worker.native.CONTROL+40,9000);w.retry_at=0;self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1,'time spent behind another job is not a stall')

    def test_a_live_timed_fusion_keeps_room_for_its_defusion(self):
        import fusion_duration as timer
        p,w,_,_,_=self.form_prepared();registry=self.registry(p)
        free=[i for i in range(12) if not p.read_u32(registry+56*i+48)&1]
        self.assertGreaterEqual(len(free),2)
        for i in free[1:]:p.write_u32(registry+56*i+48,p.read_u32(registry+56*i+48)|1)
        self.assertIsNone(worker.capacity_shortage(p.ram,form=True))
        p.write_u32(timer.CONTROL,timer.MAGIC);p.write_u32(timer.CONTROL+8,p.read_u32(worker.runner.core.MODE+4))
        p.write_u32(timer.RECORDS+3*timer.STRIDE,2)
        self.assertEqual(worker.capacity_shortage(p.ram,form=True),'room kept for a fusion to end')
        self.assertIsNone(worker.candidate(p.ram))
        p.write_u32(registry+56*free[1]+48,p.read_u32(registry+56*free[1]+48)&~1)
        self.assertIsNone(worker.capacity_shortage(p.ram,form=True))
        p.write_u32(timer.RECORDS+3*timer.STRIDE,5);self.assertFalse(worker.defusion_pending(p.ram))
        # The claimant's own accepted fusion receipt reserves nothing for itself, and the held
        # recheck (Cell's form after its auxiliary load) never adds the reservation.
        p.write_u32(registry+56*free[1]+48,p.read_u32(registry+56*free[1]+48)|1)
        p.write_u32(timer.RECORDS+2*timer.STRIDE,1)
        self.assertIsNone(worker.capacity_shortage(p.ram,form=True,claimant=2))
        self.assertIsNotNone(worker.candidate(p.ram))
        p.write_u32(timer.RECORDS+2*timer.STRIDE,0);p.write_u32(timer.RECORDS+3*timer.STRIDE,2)
        self.assertIsNone(worker.candidate(p.ram));self.assertIsNotNone(worker.candidate(p.ram,specific=2))

    def test_a_waiting_costume_is_never_cancelled(self):
        p,w=self.prepared();self.crowded(p,15);p.write_u32(worker.native.CONTROL+40,100)
        self.assertFalse(w.poll(p))
        p.write_u32(worker.native.CONTROL+40,100+worker.PENDING_FORM_LIMIT+5);w.retry_at=0;self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1);self.assertEqual(p.events,[])

    def test_any_form_waiting_past_the_long_limit_is_cancelled(self):
        p,w,notes=self.stalled(used=10)
        manager=p.read_u32(worker.requests.CONTROL+4)       # a native leader reload keeps the loader
        p.write_u32(manager+604,p.read_u32(manager+608)+1)
        self.assertFalse(w.poll(p))
        p.write_u32(worker.native.CONTROL+40,1001+worker.PENDING_FORM_FRAMES);w.retry_at=0;self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),1,'room exists: only the long limit applies')
        p.write_u32(worker.native.CONTROL+40,1001+worker.PENDING_FORM_LIMIT);w.retry_at=0;self.assertFalse(w.poll(p))
        self.assertEqual(p.read_u32(worker.requests.RECORDS+4),5)


class WaitingReasonTests(unittest.TestCase):
    """A published request that nobody claims says why, exactly once."""

    def client(self):
        import extra_reload_forms as form_module
        rows=bytearray(4*worker.requests.STRIDE)
        struct.pack_into('<I',rows,4,1)
        state={worker.native.CONTROL+16:0,worker.SCENE_FLAGS:0,worker.requests.CONTROL:1,
               worker.requests.CONTROL+4:0x1800000,form_module.FORM_ENABLE:1,
               form_module.CONTROL+form_module.REFUSALS:0,
               form_module.CONTROL+form_module.REFUSALS+4:0,
               form_module.CONTROL+form_module.REFUSALS+8:0,
               worker.runner.core.PAIR+4:0}
        for off in (600,604,608,612,628):state[0x1800000+off]=0
        class Client:
            def read_u32(self,p):return state.get(p,0)
            def read(self,p,n):
                if p==worker.requests.RECORDS:return bytes(rows)
                return b''.join(struct.pack('<I',state.get(p+4*i,0)) for i in range(n//4))
        return Client(),state

    def worker(self,client):
        notes=[]
        w=worker.Worker(progress=notes.append)
        w.active=True;w.forms=True
        return w,notes

    def test_each_veto_is_named_once_and_only_when_it_changes(self):
        import extra_reload_forms as form_module
        cases=((worker.SCENE_FLAGS,worker.SCENE_RELOAD_MASK,'arena owns the loader'),
               (0x1800000+628,1,'leader reload'),
               (worker.runner.core.PAIR+4,1,'aliased'),
               (worker.requests.CONTROL,0,'service is disabled'),
               (form_module.FORM_ENABLE,0,'forms are disabled'))
        for address,value,expected in cases:
            client,state=self.client();state[address]=value
            w,notes=self.worker(client)
            with self.subTest(address=hex(address)):
                self.assertFalse(w.poll(client))
                self.assertEqual(len(notes),1);self.assertIn(expected,notes[0])
                self.assertFalse(w.poll(client));self.assertEqual(len(notes),1)

    def test_an_existing_hold_is_ordinary_serialization_and_stays_quiet(self):
        client,state=self.client();state[worker.native.CONTROL+16]=1
        w,notes=self.worker(client)
        self.assertFalse(w.poll(client));self.assertEqual(notes,[])

    def test_a_capacity_refusal_is_reported_with_its_reason(self):
        import extra_reload_forms as form_module
        client,state=self.client()
        state[form_module.CONTROL+form_module.REFUSALS]=7
        state[form_module.CONTROL+form_module.REFUSALS+4]=5
        w,notes=self.worker(client)
        self.assertFalse(w.poll(client))
        self.assertIn('7 command(s) refused',notes[0]);self.assertIn('heap space',notes[0])

    def test_no_pending_request_says_nothing(self):
        client,state=self.client()
        w,notes=self.worker(client)
        w.waiting='stale'
        client.read=lambda p,n:bytes(n)
        self.assertFalse(w.poll(client));self.assertEqual(notes,[])
        self.assertIsNone(w.waiting)


if __name__=='__main__':unittest.main()
