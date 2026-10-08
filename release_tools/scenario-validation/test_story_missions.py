import copy
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import story_missions as d
import story_runtime as r
import fresh_team_combat as core
import native_preparation as prep
from native_map import A
from test_fusion_partner_lifecycle import FusionCpu


class StoryCpu(FusionCpu):
    def extra_instruction(self,ins,pc):
        if ins >> 26 == 0 and ins & 63 == 25:
            left=self.r[(ins>>21)&31]&0xffffffff;right=self.r[(ins>>16)&31]&0xffffffff
            product=left*right;self.lo=product&0xffffffff;self.hi=product>>32
            return
        return super().extra_instruction(ins,pc)


def mission(actions=None,when=None):
    doc=d.default_mission()
    doc['fighters'].append(dict(id='reserve',team=2,slot=2,character=3,reserve=True))
    doc['events']=[dict(id='arrive',when=when or dict(type='time',seconds=1),
        actions=actions or [dict(type='enter',fighter='reserve',intro=False)])]
    return d.validate(doc)


def machine(document):
    c=StoryCpu();c.r[28]=0x304270;c.manager=0x1800000
    c.actors=[0x1900000+0x2000*i for i in range(4)];c.models=[0x900000+0x2000*i for i in range(4)]
    c.w(core.ACTORS,c.manager);c.w(c.manager,2);c.w(c.manager+4,c.actors[0])
    for off,v in ((0,1),(4,4),(8,c.manager),(12,4)):c.w(core.MODE+off,v)
    for off,v in ((0,r.MAGIC),(4,c.manager),(8,4),(52,0xffffffff),(56,1)):c.w(r.CONTROL+off,v)
    c.w(A(0x2FEB38),0x1700000);c.w(0x1700000,3);c.w(r.part.CONSUMED,8)
    import spawn_placement
    c.w(spawn_placement.CONTROL,5)
    for i,(actor,model) in enumerate(zip(c.actors,c.models)):
        c.w(core.POINTERS+4*i,actor);c.w(r.ACTORS+4*i,actor);c.w(core.MODELS+4*i,model)
        for off,v in ((0,i),(8,i&1),(12,i),(0x948,11),(0x94C,0xffffffff),(0x964,47),(0x998,1),(0x9E4,30000),(0x9E8,30000),
                      (0x9FC,5),(0x1278,int(i>0))):c.w(actor+off,v)
        c.w(model+4,1);c.w(model+8,1);c.w(model+16,i);c.w(model+12,i)
        c.w(model+0x91C,0x1600000+i*0x1000);c.write(0x1600000+i*0x1000+152,bytes((1,2,3,255)))
    c.callbacks[r.ORIGINAL]=lambda m:None
    c.callbacks[r.ARRIVAL]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[A(0x1E0290)]=lambda m:m.w(m.r[4]+0x94C,m.r[5])
    c.callbacks[A(0x2033C8)]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[A(0x203610)]=lambda m:m.w(m.r[4]+0x94C,236+m.r[5])
    for f in document['fighters']:c.w(r.ACTORS+0x200+8*r.physical(f),c.u(c.models[r.physical(f)]+12))
    c.write(r.FRAME,r.frame(document,{i:int(i>0) for i in range(4)}));c.write(r.CPU_INIT,r.cpu_init([]))
    return c


def tick(c,n=1):
    for _ in range(n):
        c.w(prep.CONTROL+44,c.u(prep.CONTROL+44)+1);c.r[31]=0xFEED0000;c.run(r.FRAME)


class DocumentTests(unittest.TestCase):
    def test_portable_round_trip_and_arm_is_a_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mission.json';arm=Path(folder)/'next.json';doc=mission()
            d.save(path,doc);self.assertEqual(d.load(path),doc);d.arm(doc,arm)
            doc['title']='Changed';self.assertNotEqual(d.armed(arm)['title'],doc['title'])
            raw=json.loads(arm.read_text());raw['mission']['title']='Tampered';arm.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError,'checksum'):d.armed(arm)
    def test_references_cycles_and_unreachable_reserves(self):
        doc=mission();doc['events'][0]['when']=dict(type='defeated',fighter='reserve')
        with self.assertRaisesRegex(ValueError,'cycle'):d.validate(doc)
        doc=mission();doc['events']=[]
        with self.assertRaisesRegex(ValueError,'entrance'):d.validate(doc)
        doc=mission();doc['events'][0]['when']=dict(type='event',event='missing')
        with self.assertRaisesRegex(ValueError,'reference'):d.validate(doc)
    def test_or_time_can_break_dependency_cycle(self):
        doc=mission();doc['events'][0]['when']=dict(type='any',conditions=[dict(type='time',seconds=1),dict(type='defeated',fighter='reserve')])
        self.assertEqual(d.validate(doc)['id'],doc['id'])
    def test_bad_numbers_duplicate_seats_and_executable_fields_rejected(self):
        for change in ('nan','seat','code','version'):
            doc=mission()
            if change=='nan':doc['events'][0]['when']['seconds']=float('nan')
            if change=='seat':doc['fighters'][-1]['slot']=1
            if change=='code':doc['events'][0]['actions'][0]['execute']='os.system(...)'
            if change=='version':doc['version']=9
            with self.assertRaises(ValueError):d.validate(doc)
    def test_runtime_capacity_not_file_format(self):
        doc=d.default_mission()
        for slot in range(2,7):doc['fighters'].append(dict(id=f'f{slot}',team=2,slot=slot,character=3))
        d.validate(doc)
        with self.assertRaisesRegex(ValueError,'supports 5'):r.adapter_check(doc)
        r.adapter_check(doc,capacity=6)
    def test_cpu_copy_does_not_alias_profile_or_body(self):
        doc=d.default_mission();doc['cpu_profiles']={'custom':dict(name='Defensive',transform_chance=25)}
        doc['fighters'][0]['cpu_profile']='custom';copydoc=d.copy_cpu_profile(doc,'hero','rival')
        self.assertEqual(copydoc['fighters'][1]['character'],29)
        self.assertEqual(copydoc['fighters'][1]['copy_cpu_from'],'hero')
        copydoc['cpu_profiles']['rival-cpu']['transform_chance']=10
        self.assertEqual(copydoc['cpu_profiles']['custom']['transform_chance'],25)

    def test_cross_game_presets_and_cpu_copy_cycles_are_rejected(self):
        doc=d.default_mission();doc['game_family']='bt3' if doc['game_family']=='bt4' else 'bt4'
        with self.assertRaisesRegex(ValueError,'character IDs'):r.adapter_check(doc)
        doc=d.default_mission();doc['fighters'][0]['copy_cpu_from']='rival';doc['fighters'][1]['copy_cpu_from']='hero'
        with self.assertRaisesRegex(ValueError,'cycle'):d.validate(doc)

    def test_preflight_checks_exact_roster_costume_and_human_reserves(self):
        doc=mission();rows=[dict(physical_id=r.physical(f),character=f['character'],costume=f['costume'],participating=True) for f in doc['fighters']]
        selection=dict(roster=rows,participation_mask=11)
        self.assertEqual(r.validate_selection(doc,selection,b''),doc)
        rows[-1]['costume']=1
        with self.assertRaisesRegex(ValueError,'slot 2'):r.validate_selection(doc,selection,b'')
        rows[-1]['costume']=0;rows.pop()
        with self.assertRaisesRegex(ValueError,'team sizes'):r.validate_selection(doc,selection,b'')

    def test_rearming_another_mission_is_not_cleared_by_previous_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'next.json';first=d.default_mission();second=mission()
            d.arm(second,path);d.consumed(first,path);self.assertEqual(d.armed(path),second)
            d.consumed(second,path);self.assertFalse(path.exists())

    def test_queue_lock_serializes_other_processes_and_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'next.json'
            code='import sys,story_missions as d\nwith d.queue_lock(sys.argv[1],timeout=.05): pass'
            with d.queue_lock(path):
                result=subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(d.__file__).parent,capture_output=True,text=True,timeout=5)
                self.assertNotEqual(result.returncode,0);self.assertIn('queue is busy',result.stderr)
            result=subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(d.__file__).parent,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)


class DependencyTests(unittest.TestCase):
    def prepared(self):
        import cinematic_contact_guard as contact
        import stage_transition
        document=mission();c=machine(document)
        c.w(r.part.PRESENT,11);c.w(r.modes.CONTROL+12,r.modes.TEAMS)
        for f in document['fighters']:
            row=c.actors[r.physical(f)]+0x9A4
            c.w(row,f['character']);c.w(row+4,f['costume'])
        c.write(r.part.APPLY,r.part.apply_code()[:8]);c.write(r.defeat.ENTRY,r.jump(r.defeat.CODE))
        c.write(r.abi.DAMAGE_ENTRY,r.jump(0x7100000));c.write(A(0x1D4F30),r.jump(0x7100800))
        c.write(contact.PROTECTED,contact.protected_code())
        for hook,target,_ in stage_transition.HOOKS:c.w(hook,(3<<26)|(target>>2))
        ram=bytearray(0x8000000)
        for address,value in c.memory.items():
            if address<len(ram):ram[address]=value
        ram[r.BASE:r.END]=bytes(r.END-r.BASE)
        import story_menus
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        ram[story_menus.ENTRY:story_menus.ENTRY+8]=elf_reader(elf_path(ROOT))[2](story_menus.ENTRY,8)
        return ram,document

    def test_single_player_presentation_installs_its_executable_text_dependency(self):
        ram,doc=self.prepared();plan=r.build_memory(ram,doc)
        blocks={b['address']:bytes.fromhex(b['data_hex']) for b in plan['blocks']}
        self.assertEqual(blocks[r.abi.SMALL_TEXT],r.abi.text_code(compact=True))
        ram[r.abi.SMALL_TEXT]=1
        with self.assertRaisesRegex(ValueError,'text renderer reservation'):r.build_memory(ram,doc)

    def test_outer_guard_requires_matching_world_and_exact_continuation(self):
        import cinematic_contact_guard as contact
        ram,doc=self.prepared();plan=r.build_memory(ram,doc)
        original=bytes(ram[r.abi.DAMAGE_ENTRY:r.abi.DAMAGE_ENTRY+8])
        for b in plan['blocks']:
            data=bytes.fromhex(b['data_hex']);ram[b['address']:b['address']+len(data)]=data
        self.assertEqual(r.dependency_override(ram,r.abi.DAMAGE_ENTRY,original),r.jump(r.DAMAGE))
        ram[r.DAMAGE+16]^=1
        self.assertEqual(r.dependency_override(ram,r.abi.DAMAGE_ENTRY,original),original)
        ram[r.DAMAGE+16]^=1;struct.pack_into('<I',ram,r.CONTROL+4,0)
        with self.assertRaisesRegex(ValueError,'another match'):r.dependency_override(ram,r.abi.DAMAGE_ENTRY,original)


class RuntimeTests(unittest.TestCase):
    def test_short_ko_timeout_expires_while_falling_before_retained_dead_state(self):
        document=d.default_mission();document['events']=[dict(id='death',when=dict(type='defeated',fighter='hero'),timeout_seconds=1,
            actions=[dict(type='recover',fighter='hero')])]
        c=machine(d.validate(document));c.w(c.actors[0]+0x9E4,0);c.w(c.actors[0]+0x948,207)
        tick(c,r.ACTOR_HZ+1)
        self.assertEqual(c.u(r.EVENTS),3);self.assertEqual(c.u(c.actors[0]+0x9E4),0)
        # A realistic budget permits the later retained KO -> recovery transition.
        document['events'][0]['timeout_seconds']=30;c=machine(d.validate(document))
        c.w(c.actors[0]+0x9E4,0);c.w(c.actors[0]+0x948,207);tick(c,2*r.ACTOR_HZ)
        self.assertEqual(c.u(r.EVENTS),1)
        c.w(c.actors[0]+0x948,216);tick(c);self.assertEqual(c.u(c.actors[0]+0x9E4),30000)
    def test_frame_preserves_full_native_register_and_fpu_context(self):
        c=machine(d.default_mission());c.r[16]=0x112233445566778899AABBCCDDEEFF00;c.r[8]=0xFFEECCDDAABB99881122334455667788
        c.fcr31=123;c.f[0]=0x3F800000;c.hi=7;c.lo=13
        def clobber(m):m.f[0]=0;m.fcr31=999;m.hi=100;m.lo=200
        c.callbacks[r.CPU_INIT]=clobber
        before=(c.r[16],c.r[8],c.f[0],c.fcr31,c.hi,c.lo);tick(c)
        self.assertEqual((c.r[16],c.r[8],c.f[0],c.fcr31,c.hi,c.lo),before)
    def test_arrival_rebuilds_model_actor_collision_and_sector_together(self):
        c=machine(mission());c.callbacks.pop(r.ARRIVAL);c.write(r.ARRIVAL,r.arrival_code())
        import spawn_placement
        c.w(spawn_placement.STAGE,0x1500000)
        actor,model=c.actors[3],c.models[3];position=r.ACTORS+0x130
        for off in (4000,4004):c.w(model+off,model+(3936 if off==4000 else 3968))
        c.write(position,struct.pack('<3f',300.,-10.,400.))
        c.write(model+2416,struct.pack('<3f',100.,900.,200.));c.write(model+2384,struct.pack('<3f',100.,900.,200.))
        c.callbacks[A(0x1D7570)]=lambda m:m.write(model+2384,m.read(position,12))
        c.callbacks[A(0x24E2B0)]=lambda m:m.write(model+2416,m.read(model+2384,12))
        c.callbacks[A(0x24E3F8)]=lambda m:None
        c.callbacks[A(0x24DC58)]=lambda m:m.write(model+3936,m.read(model+2416,12)+bytes(20))
        c.callbacks[A(0x1D70E8)]=lambda m:m.write(actor+16,m.read(model+2416,12))
        c.callbacks[A(0x23FF78)]=lambda m:m.r.__setitem__(2,77)
        c.r[4]=actor;c.r[5]=model;c.r[6]=position;c.r[31]=0xFEED0000;c.run(r.ARRIVAL)
        self.assertEqual(c.r[2],1);self.assertEqual(c.read(actor+16,12),c.read(position,12))
        self.assertEqual(c.read(actor+256,48),c.read(actor+16,48))
        self.assertEqual(c.read(model+3936,32),c.read(model+3968,32));self.assertEqual(c.u(model+2596),77)

    def test_entrance_uses_real_current_arena_lookup_for_extra_rank(self):
        from test_stage_transition import StageTransitionTests
        import stage_transition
        c,actors,models,_,_=StageTransitionTests().machine();actor,model=actors[4],models[4]
        c.write(A(0x1D7570),stage_transition.NATIVE(A(0x1D7570),0x58))
        c.w(A(0x1D7594),(3<<26)|(stage_transition.CODE>>2))
        for off in (4000,4004):c.w(model+off,model+(3936 if off==4000 else 3968))
        c.write(r.ARRIVAL,r.arrival_code());c.r[4]=actor;c.r[5]=model;c.run(r.ARRIVAL)
        self.assertEqual(c.r[2],1);self.assertGreater(c.fr(model+2416),60);self.assertLess(c.fr(model+2424),-90)
        self.assertEqual(c.read(model+3936,32),c.read(model+3968,32))

    def test_taunt_waits_for_animation_and_recovery_timeout_releases_protection(self):
        document=d.default_mission();document['events']=[dict(id='wake',when=dict(type='defeated',fighter='hero'),timeout_seconds=1,
            actions=[dict(type='recover',fighter='hero'),dict(type='taunt',fighter='hero')])]
        c=machine(d.validate(document));c.w(c.actors[0]+0x9E4,0);c.w(c.actors[0]+0x948,216);tick(c)
        self.assertEqual(c.u(r.CONTROL+48),1);tick(c,r.ACTOR_HZ)
        self.assertEqual(c.u(r.EVENTS),3);self.assertEqual(c.u(r.CONTROL+48),0);self.assertEqual(c.u(r.CONTROL+128),0)
        document=d.default_mission();document['events']=[dict(id='pose',when=dict(type='time',seconds=0),actions=[dict(type='taunt',fighter='hero')])]
        c=machine(d.validate(document));tick(c,2);self.assertEqual(c.u(r.EVENTS+4),0)
        self.assertEqual(c.u(c.actors[0]+0x94C),67)
        c.w(c.actors[0]+0x94C,0xffffffff);c.w(c.actors[0]+0x948,67);tick(c,5)
        self.assertEqual(c.u(r.EVENTS),1)
        c.w(c.actors[0]+0x948,11);tick(c,2);self.assertEqual(c.u(r.EVENTS),2)

    def test_status_reads_journal_and_checks_embedded_document_hash(self):
        from test_trainer_bridge import Client
        document=mission();c=machine(document);raw=d.encoded(document)
        c.write(r.CONTROL+64,bytes.fromhex(d.digest(document)));c.w(r.DOCUMENT,len(raw));c.write(r.DOCUMENT+4,raw)
        state=r.snapshot(Client(c));self.assertEqual(state['events'][0]['status'],'waiting')
        tick(c,r.ACTOR_HZ);self.assertEqual(r.snapshot(Client(c))['events'][0]['status'],'running')
        r._documents.clear();c.write(r.DOCUMENT+4,b'X');self.assertIn('error',r.snapshot(Client(c)))

    def test_any_transformation_trigger_is_an_edge_not_a_starting_form(self):
        document=mission(when=dict(type='transformed',fighter='hero'));c=machine(document)
        tick(c,10);self.assertEqual(c.u(r.part.CONSUMED),8)
        c.w(c.models[0]+12,2);tick(c);self.assertEqual(c.u(r.part.CONSUMED),0)
    def test_recovery_uses_actual_native_getup_and_keeps_protection_until_finished(self):
        import test_revive_native_path as native
        class NativeCpu(StoryCpu,native.Cpu):pass
        document=d.default_mission();document['events']=[dict(id='return',when=dict(type='defeated',fighter='hero'),
            actions=[dict(type='recover',fighter='hero',health_percent=100)])]
        document=d.validate(document);c=machine(document);original=native.fixture()
        c.__class__=NativeCpu;c.memory.update(original.memory);c.callbacks.update(original.callbacks);c.events=[]
        native.dispatch(c);tick(c);self.assertEqual(c.u(r.CONTROL+48),1)
        native.dispatch(c);self.assertEqual(c.u(native.ACTOR+0x948),225)
        for _ in range(30):native.dispatch(c);tick(c)
        tick(c,2);self.assertEqual(c.u(native.ACTOR+0x948),11);self.assertEqual(c.u(r.EVENTS),2)
        self.assertEqual(c.u(r.CONTROL+48),0)

    def test_protection_blocks_contact_damage_and_controls_without_blocking_story_commands(self):
        c=machine(d.default_mission());previous=0xF0000;c.callbacks[previous]=lambda m:m.r.__setitem__(2,77)
        c.w(r.CONTROL+48,1);c.w(core.PAIR+4,1) # contact guards must survive native role aliases
        for kind,base in (('contact',r.CONTACT),('command',r.COMMAND),('damage',r.DAMAGE)):
            c.write(base,r.protection_code(base,previous,kind));c.r[4]=c.actors[0];c.r[5]=c.actors[1] if kind=='contact' else 20
            c.r[31]=0xFEED0000;c.run(base);self.assertEqual(c.r[2],int(kind=='contact'))
        c.r[4]=c.actors[1];c.r[5]=c.actors[0];c.r[31]=0xFEED0000;c.run(r.CONTACT);self.assertEqual(c.r[2],1)
        for command in (67,91,100,101,102,103):
            c.r[4]=c.actors[0];c.r[5]=command;c.r[31]=0xFEED0000;c.run(r.COMMAND);self.assertEqual(c.r[2],77)
        c.w(r.CONTROL+48,0);c.r[31]=0xFEED0000;c.run(r.DAMAGE);self.assertEqual(c.r[2],77)

    def test_scripted_transforms_override_random_preference_only(self):
        c=machine(d.default_mission());c.write(r.CHANCE,r.chance_code({1:0}))
        c.callbacks[r.CHANCE_NATIVE]=lambda m:m.r.__setitem__(2,1)
        c.r[4]=c.actors[1];c.r[5]=0;c.r[31]=0xFEED0000;c.run(r.CHANCE);self.assertEqual(c.r[2],1)
        c.w(r.CONTROL+36,2);c.r[31]=0xFEED0000;c.run(r.CHANCE);self.assertEqual(c.r[2],0)
        c.w(r.CONTROL+36,0);c.r[31]=0xFEED0000;c.run(r.CHANCE);self.assertEqual(c.r[2],1)

    def test_cpu_chance_never_restricts_a_human(self):
        c=machine(d.default_mission());c.write(r.CHANCE,r.chance_code({0:0,1:0}))
        c.callbacks[r.CHANCE_NATIVE]=lambda m:m.r.__setitem__(2,0)
        for actor,wanted in ((c.actors[0],0),(c.actors[1],1)):
            c.r[4]=actor;c.r[31]=0xFEED0000;c.run(r.CHANCE);self.assertEqual(c.r[2],wanted)

    def test_message_uses_current_viewport_and_expires(self):
        document=d.default_mission();document['events']=[dict(id='cue',when=dict(type='time',seconds=0),
            actions=[dict(type='message',text='The next fighter arrives',seconds=2)])];document=d.validate(document)
        c=machine(document);program,strings=r.draw_code(document);c.write(r.DRAW,program);c.write(r.STRINGS,strings)
        camera=0x1500000;c.w(c.r[28]-22176,camera);c.w(camera+512,256);c.w(camera+524,447)
        c.callbacks[r.DRAW_NATIVE]=lambda m:None;draws=[]
        c.callbacks[r.abi.SMALL_TEXT]=lambda m:draws.append(tuple(m.r[4:8]))
        tick(c);c.r[31]=0xFEED0000;c.run(r.DRAW);self.assertEqual(len(draws),1)
        self.assertEqual(draws[0][1],(1792+256+8)*16)
        tick(c,r.ACTOR_HZ*2);c.r[31]=0xFEED0000;c.run(r.DRAW);self.assertEqual(len(draws),1)

    def test_story_time_starts_at_fight_not_on_the_frame_before_the_native_intros(self):
        document=d.default_mission();document['events']=[dict(id='open',when=dict(type='time',seconds=0),
            actions=[dict(type='heal',fighter='hero',health_percent=50)])];document=d.validate(document)
        c=machine(document);c.w(r.CONTROL+52,r.FRESH)
        tick(c);self.assertEqual((c.u(r.CONTROL+12),c.u(r.EVENTS)),(0,0),'cover just dropped: not yet')
        c.w(prep.CONTROL+44,c.u(prep.CONTROL+44)+90)  # native intros: frames pass without the story
        tick(c);self.assertEqual((c.u(r.CONTROL+12),c.u(r.EVENTS)),(0,0),'first frame after the intros')
        tick(c);self.assertEqual(c.u(r.CONTROL+12),1);self.assertEqual(c.u(c.actors[0]+0x9E4),15000)
        c.w(prep.CONTROL+44,c.u(prep.CONTROL+44)+30);tick(c);self.assertEqual(c.u(r.CONTROL+12),2,'running clock is not gated')
    def test_retired_leader_is_shown_again_only_for_the_decided_result_pose(self):
        document=d.default_mission();document=d.validate(document)
        c=machine(document);program,strings=r.draw_code(document);c.write(r.DRAW,program);c.write(r.STRINGS,strings)
        c.callbacks[r.DRAW_NATIVE]=lambda m:None
        c.w(r.CONTROL+112,1);c.w(c.models[0]+8,0);c.w(c.models[1]+8,0)
        def draw(phase,winner):
            c.w(0x1700000,phase);c.w(r.CONTROL+96,winner);c.r[31]=0xFEED0000;c.run(r.DRAW)
            return c.u(c.models[0]+8),c.u(c.models[1]+8)
        self.assertEqual(draw(3,1),(0,0),'combat: the retired leader stays hidden')
        self.assertEqual(draw(5,0),(0,0),'no story outcome: native presentation untouched')
        self.assertEqual(draw(4,1),(0,0),'KO slow motion: not yet')
        self.assertEqual(draw(5,1),(1,0),'result pose: only the retired leader returns')
    def test_entrance_exactly_once_and_frame_deduplication(self):
        c=machine(mission());actor=c.actors[3];c.w(actor+0x9E4,0);c.w(c.models[3]+8,0)
        tick(c,r.ACTOR_HZ-1);self.assertEqual(c.u(r.part.CONSUMED),8)
        # Participation APPLY runs before AND after the native update.
        c.r[31]=0xFEED0000;c.run(r.FRAME);self.assertEqual(c.u(r.CONTROL+12),r.ACTOR_HZ-1)
        tick(c);self.assertEqual(c.u(r.part.CONSUMED),0);self.assertEqual(c.u(actor+0x9E4),30000)
        self.assertEqual(c.u(actor+0x964),47);self.assertEqual(c.u(c.models[3]+8),1)
        self.assertEqual(c.u(actor+0x1278),0)
        tick(c,2);self.assertEqual(c.u(actor+0x1278),1)
        c.w(actor+0x9E4,100);tick(c,60);self.assertEqual(c.u(actor+0x9E4),100)
        self.assertEqual(c.u(r.EVENTS),2)
    def test_pause_intro_and_stale_world_do_not_advance(self):
        c=machine(mission())
        c.w(0x1700000,2);tick(c,5);self.assertEqual(c.u(r.CONTROL+12),0)
        c.w(0x1700000,3);c.w(A(0x3337B8),0x100);tick(c,5);self.assertEqual(c.u(r.CONTROL+12),0)
        c.w(A(0x3337B8),0);c.w(r.CONTROL+4,c.manager+4);tick(c);self.assertEqual(c.u(r.CONTROL+12),0)
    def test_form_request_uses_native_command_and_waits_for_actual_body(self):
        doc=d.default_mission();doc['events']=[dict(id='form',when=dict(type='time',seconds=0),
            actions=[dict(type='transform',fighter='hero',character=1)])];doc=d.validate(doc);c=machine(doc)
        calls=[]
        def admission(m):calls.append(tuple(m.r[4:8]));m.r[2]=1
        c.callbacks[A(0x2033C8)]=admission
        tick(c);self.assertEqual(c.u(c.actors[0]+0x94C),236);self.assertEqual(c.u(r.EVENTS+4),0)
        self.assertEqual(calls,[(c.actors[0],0,1,1)])
        c.w(c.models[0]+12,1);tick(c,2);self.assertEqual(c.u(r.EVENTS),1)
        c.w(c.actors[0]+0x94C,0xffffffff);tick(c,2);self.assertEqual(c.u(r.EVENTS),2)
    def test_failed_form_releases_event_and_reports_failure(self):
        doc=d.default_mission();doc['events']=[dict(id='bad',when=dict(type='time',seconds=0),
            actions=[dict(type='transform',fighter='hero',character=99)])];doc=d.validate(doc);c=machine(doc)
        tick(c);self.assertEqual(c.u(r.EVENTS),3);self.assertEqual(c.u(r.CONTROL+16),1)
        self.assertEqual(c.u(c.actors[0]+0x964),47)
    def test_health_threshold_heal_and_second_wind(self):
        doc=d.default_mission();doc['events']=[dict(id='recover',when=dict(type='defeated',fighter='hero'),
            actions=[dict(type='recover',fighter='hero',health_percent=50)])];doc=d.validate(doc);c=machine(doc)
        c.w(c.actors[0]+0x9E4,0);c.w(c.actors[0]+0x948,216);tick(c)
        self.assertEqual(c.u(c.actors[0]+0x9E4),15000);self.assertEqual(c.u(c.actors[0]+0x964),47)
    def test_large_hp_threshold_and_restoration_do_not_overflow(self):
        doc=d.default_mission();doc['events']=[dict(id='heal',when=dict(type='health_below',fighter='hero',percent=50),
            actions=[dict(type='heal',fighter='hero',health_percent=75)])];c=machine(d.validate(doc))
        c.w(c.actors[0]+0x9E4,3_000_000);c.w(c.actors[0]+0x9E8,4_000_000);tick(c)
        self.assertEqual(c.u(c.actors[0]+0x9E4),3_000_000);self.assertEqual(c.u(r.EVENTS),0)
        c.w(c.actors[0]+0x9E4,1_000_000);tick(c);self.assertEqual(c.u(c.actors[0]+0x9E4),3_000_000)
    def test_recovery_keeps_current_takeover_ownership_and_waits_out_death_action(self):
        doc=d.default_mission();doc['events']=[dict(id='recover',when=dict(type='defeated',fighter='rival'),
            actions=[dict(type='recover',fighter='rival')])];c=machine(d.validate(doc));actor=c.actors[1]
        c.w(actor+0x1278,0);c.w(actor+0x9E4,0);c.w(actor+0x948,100);tick(c)
        self.assertEqual(c.u(actor+0x9E4),0)
        c.w(actor+0x948,216);tick(c);self.assertEqual(c.u(actor+0x9E4),30000)
        self.assertEqual(c.u(actor+0x1278),0)
    def test_results_only_wait_when_actually_defeated_and_are_bounded(self):
        doc=mission();c=machine(doc);previous=0x73C8000
        c.write(r.RESULT,r.result_code(doc,previous));c.callbacks[previous]=lambda m:m.r.__setitem__(2,0)
        c.r[4]=1;c.r[31]=0xFEED0000;c.run(r.RESULT);self.assertEqual(c.r[2],0);self.assertEqual(c.u(r.CONTROL+44),0)
        c.callbacks[previous]=lambda m:m.r.__setitem__(2,1)
        c.r[31]=0xFEED0000;c.run(r.RESULT);self.assertEqual(c.r[2],0)
        c.w(r.CONTROL+12,r.ACTOR_HZ*30);c.r[31]=0xFEED0000;c.run(r.RESULT);self.assertEqual(c.r[2],1)
    def test_cpu_profile_copies_only_configuration_and_rebuilds_native_cache(self):
        c=machine(d.default_mission());from ai_shadow import AI_GLOBAL
        c.w(AI_GLOBAL,0x1550000);c.write(r.CPU_INIT,r.cpu_init([(3,c.actors[3],c.actors[3]+0x9A4,2,4)]))
        calls=[]
        for address in (A(0x1BB478),A(0x1BB3E0)):
            c.callbacks[address]=lambda m,p=address:calls.append((p,m.r[4],m.r[5],m.u(AI_GLOBAL)))
        tick(c);self.assertEqual([x[2] for x in calls],[2,4]);self.assertEqual(c.u(AI_GLOBAL),0x1550000)
        self.assertEqual(c.u(c.actors[3]+0x9DC),2);self.assertEqual(c.u(c.models[3]+12),3)
        tick(c);self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
