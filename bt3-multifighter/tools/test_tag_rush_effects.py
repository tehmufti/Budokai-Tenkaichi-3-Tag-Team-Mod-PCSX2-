"""Execute beam lifecycle and real native request/setter code, without PCSX2."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest
from pathlib import Path
import tag_rush_effects as fx
import tag_team_rush as tag
import tag_rush_scene as scene
import tag_rush_assets as assets
import fresh_team_combat as core
from native_map import A, elf_path
from prototype import ROOT,elf_reader
from test_tag_rush_scene import SceneCpu
from test_tag_rush_safety import control,ACTOR,MODEL
from test_tag_rush_camera import run

POOL,NODE,BODY,REGISTRY=0x2400000,0x2410000,0x2420000,0x2430000
BEAM=dict(reviewed=True,resource_address=0x6D30000,metadata_address=0x6D50000,
          descriptor_counts=(1,6,0,1),descriptor_raw_bytes=2176)


class EffectsCpu(SceneCpu):
    def extra_instruction(self,ins,pc):
        op,rs,rt=ins>>26,(ins>>21)&31,(ins>>16)&31
        if op in (26,27,44,45):
            off=ins&65535;off=off if off<32768 else off-65536
            at=(self.r[rs]+off)&0xFFFFFFFF;low=at&7;aligned=at&~7
            if op==26:
                n=low+1;shift=(8-n)*8;mask=((1<<(n*8))-1)<<shift
                self.r[rt]=(self.r[rt]&~mask)|(int.from_bytes(self.read(aligned,n),'little')<<shift)
            elif op==27:
                n=8-low;mask=(1<<(n*8))-1;self.r[rt]=(self.r[rt]&~mask)|int.from_bytes(self.read(at,n),'little')
            elif op==44:self.write(aligned,((self.r[rt]&0xFFFFFFFFFFFFFFFF)>>((7-low)*8)).to_bytes(low+1,'little'))
            else:self.write(at,(self.r[rt]&((1<<((8-low)*8))-1)).to_bytes(8-low,'little'))
            return
        return super().extra_instruction(ins,pc)


def machine(prepared=True):
    c=EffectsCpu({'segments':[dict(address=p,data_hex=b.hex()) for p,b in fx.pieces(BEAM)]})
    control(c,active=1,initiator=0,victim=1,count=4,members=7)
    c.w(tag.CONTROL+tag.C['partner'],2);c.w(tag.CONTROL+tag.C['ready'],1)
    c.w(c.r[28]+fx.NATIVE_POOL_OFFSET,POOL);c.w(POOL+12,NODE);c.w(NODE+32,POOL)
    c.w(c.r[28]-22416,REGISTRY);c.w(REGISTRY+152,0x3FE);c.w(REGISTRY+148,8)
    c.write(REGISTRY+80,struct.pack('<4I',0x3500000,0x3501000,0x100000,0x1000))
    c.actors=[];c.models=[];c.events=[];c.requests=[];c.pool_fail=False
    for index,mid in enumerate((0,4,7,1)):
        actor=ACTOR+index*0x2000;model=MODEL+index*0x2000;c.actors.append(actor);c.models.append(model)
        c.w(core.POINTERS+4*index,actor);c.w(actor,index);c.w(actor+12,mid);c.w(actor+0x9E4,30000)
        c.w(core.MODELS+4*mid,model);c.w(model+4,1);c.w(model+8,1);c.w(model+16,mid);c.w(model+12,20+index)
        c.w(model+2348,0x3900000+index*0x1000)
        for bone in (17,31,45):
            ptr=0x3600000+index*0x1000+bone*0x80;c.w(model+3436+4*bone,ptr)
            c.write(ptr+64,struct.pack('<4f',30.0*index,-float(bone),100.0*index,1))
    native=elf_reader(elf_path(ROOT))[2]
    for addr,size in ((0x16A7D0,0x98),(0x16A900,0x50),(0x16A9C0,0x40),
                      (0x16A6F0,0x48),(0x1ADA58,0x28),
                      (0x16AC40,0xD0),(0x1517A0,0x70),(0x14D8A8,0x2A0),(0x14D460,0x110)):
        c.write(A(addr),native(A(addr),size))
    c.w(fx.CALLBACKS,fx.NATIVE_UPDATE)
    c.callbacks[A(0x2A9ACC)]=lambda m:m.write(m.r[4],bytes(m.r[6]))
    c.callbacks[A(0x150D80)]=lambda m:m.events.append(('retire_children',m.r[4],m.r[5]))
    def bone(m):
        model=m.u(core.MODELS+4*m.r[4]);p=m.u(model+3436+4*m.r[5])
        m.events.append(('bone',m.r[4],m.r[5]));m.write(m.r[6],m.read(p+64,16))
    c.callbacks[fx.BONE]=bone
    def context(m):m.events.append(('context',m.u(m.r[4]),m.r[5]))
    c.callbacks[A(0x1512C8)]=context
    def pool(m):
        c.requests.append(struct.unpack('<13I',m.read(m.r[6],52)))
        if c.pool_fail:m.r[2]=0;return
        n=NODE+(len(c.requests)-1)*0x100;p=BODY+(len(c.requests)-1)*0x1000
        m.w(n+32,POOL);m.w(n+40,fx.CALLBACKS);m.w(n+56,p)
        m.w(p,m.u(m.r[6]));m.w(p+48,m.u(m.r[6]+4));m.w(p+1408,1);m.r[2]=n
    c.callbacks[A(0x1AD7B8)]=pool
    c.callbacks[A(0x14FF50)]=lambda m:None
    if prepared:
        c.write(fx.CONTROL,struct.pack('<5I',fx.MAGIC,c.u(core.ACTORS),4,1,POOL))
        for index in range(2):
            row=fx.ROWS+index*fx.STRIDE
            c.w(row+fx.R['prepared'],fx.PREPARED);c.w(row+fx.R['source_bone'],31)
            c.w(row+fx.HEADER+36,row+fx.META);c.w(row+fx.DESC+796,row+fx.HEADER)
    return c


def spawn(c,slot=0,ticks=60):
    c.r[4:6]=[slot,ticks];run(c,fx.SPAWN);return c.r[2]


class TagEffectsTests(unittest.TestCase):
    @staticmethod
    def custom_ending(c):
        c.w(scene.STATE,scene.SCENE_MAGIC)
        c.w(scene.STATE+scene.S['descriptor'],assets.BASE)
        c.w(assets.BASE+28,assets.CUSTOM_FINISHER|assets.BEAM_LEAD|assets.BEAM_PARTNER)

    def test_custom_beams_bind_both_native_contexts_to_actual_firing_hand(self):
        c=machine();self.custom_ending(c)
        for slot in range(2):
            self.assertEqual(spawn(c,slot),1)
            row=fx.ROWS+slot*fx.STRIDE;body=c.u(row+fx.R['body'])
            model=c.models[0 if slot==0 else 2]
            self.assertEqual(c.u(row+fx.R['source_bone']),45)
            self.assertEqual(c.read(body+1440,16),c.read(c.u(model+3436+45*4)+64,16))
            for context in (row+fx.CONTEXT,body+64):
                for phase in (0,1):self.assertEqual(c.u(context+16+phase*64),45)
        self.assertIn(('bone',7,45),c.events)
        self.assertNotIn(('bone',7,31),c.events)
        moved=struct.pack('<4f',5.,-15.,20.,1.)
        c.write(c.u(c.models[2]+3436+45*4)+64,moved);run(c,fx.UPDATE)
        body=c.u(fx.ROWS+fx.STRIDE+fx.R['body'])
        self.assertEqual(c.read(body+1440,16),moved)

    def test_custom_source_guard_and_legacy_spawn_reset(self):
        for bad in ('missing hand','low descriptor','high descriptor'):
            c=machine();self.custom_ending(c)
            if bad=='missing hand':c.w(c.models[0]+3436+45*4,0)
            else:c.w(scene.STATE+scene.S['descriptor'],assets.BASE-64 if bad=='low descriptor' else assets.END)
            self.assertEqual(spawn(c),0,bad);self.assertFalse(c.requests,bad)
        c=machine();self.custom_ending(c);c.w(assets.BASE+28,0)
        c.w(fx.ROWS+fx.R['source_bone'],45)
        self.assertEqual(spawn(c),1);self.assertEqual(c.u(fx.ROWS+fx.R['source_bone']),31)

    def test_own_clash_selects_forward_live_hand_once_and_keeps_native_binding(self):
        for forward in (31,45):
            c=machine();self.custom_ending(c)
            c.w(assets.BASE+28,assets.CUSTOM_FINISHER|assets.OWN_CLASH_POSE|assets.BEAM_LEAD)
            model=c.models[0]
            c.write(model+2416,struct.pack('<4f',100.,-20.,200.,1.))
            c.write(c.u(c.models[1]+3436+17*4)+64,struct.pack('<4f',60.,-20.,170.,1.))
            for bone in (31,45):
                vec=(92.,-22.,194.,1.) if bone==forward else (104.,-22.,203.,1.)
                c.write(c.u(model+3436+bone*4)+64,struct.pack('<4f',*vec))
            self.assertEqual(spawn(c),1)
            row=fx.ROWS;body=c.u(row+fx.R['body'])
            self.assertEqual(c.u(row+fx.R['source_bone']),forward)
            for context in (row+fx.CONTEXT,body+64):
                for phase in (0,1):self.assertEqual(c.u(context+16+phase*64),forward)
            # A later recoil does not switch to the other hand mid-beam.
            moved=struct.pack('<4f',110.,-25.,210.,1.)
            c.write(c.u(model+3436+forward*4)+64,moved);run(c,fx.UPDATE)
            self.assertEqual(c.u(row+fx.R['source_bone']),forward)
            self.assertEqual(c.read(body+1440,16),moved)

    def test_own_clash_rejects_missing_or_nonfinite_geometry_before_emit(self):
        for invalid in ('missing31','missing45','nan31','nan45','nanroot','nantarget'):
            c=machine();self.custom_ending(c)
            c.w(assets.BASE+28,assets.CUSTOM_FINISHER|assets.OWN_CLASH_POSE|assets.BEAM_LEAD)
            if invalid.startswith('missing'):c.w(c.models[0]+3436+int(invalid[7:])*4,0)
            elif invalid.startswith('nan') and invalid[3:].isdigit():
                c.w(c.u(c.models[0]+3436+int(invalid[3:])*4)+64,0x7FC00000)
            elif invalid=='nanroot':c.w(c.models[0]+2416,0x7FC00000)
            else:c.w(c.u(c.models[1]+3436+17*4)+64,0x7FC00000)
            self.assertEqual(spawn(c),0,invalid);self.assertFalse(c.requests,invalid)

    def test_disc_own_clash_poses_emit_from_actual_forward_hand(self):
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__))
              else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        iso=Path(__file__).resolve().parents[2]/'games'/name
        if not iso.is_file():self.skipTest('Local reviewed disc unavailable')
        from model_assets import load_character,read_animation_bank,package_entry
        from model_animations import AnimationClip,decompress_animation
        from model_viewer import pose_matrices
        for character in (0,23):
            raw=decompress_animation(package_entry(read_animation_bank(iso,character),265))
            clip=AnimationClip.from_decoded(264,raw)
            posed=pose_matrices(load_character(iso,character).bones,clip.evaluate(min(10,clip.frame_count-1)))
            c=machine();self.custom_ending(c)
            c.w(assets.BASE+28,assets.CUSTOM_FINISHER|assets.OWN_CLASH_POSE|assets.BEAM_LEAD)
            c.write(c.u(c.models[1]+3436+17*4)+64,struct.pack('<4f',0.,0.,-80.,1.))
            for bone in (45,31):
                c.write(c.u(c.models[0]+3436+bone*4)+64,struct.pack('<4f',*posed[bone][:3,3],1.))
            expected=min((31,45),key=lambda bone:posed[bone][2,3])
            self.assertEqual(spawn(c),1,character)
            body=c.u(fx.ROWS+fx.R['body'])
            self.assertEqual(c.u(fx.ROWS+fx.R['source_bone']),expected,character)
            self.assertEqual(c.read(body+1440,16),struct.pack('<4f',*posed[expected][:3,3],1.))

    def test_real_native_request_and_setters_make_two_visual_only_beams(self):
        c=machine();self.assertEqual(spawn(c),1);self.assertEqual(spawn(c,1),1)
        self.assertEqual(len(c.requests),2)
        for index,request in enumerate(c.requests):
            row=fx.ROWS+index*fx.STRIDE;p=c.u(row+fx.R['body'])
            self.assertEqual(request[:5],(row+fx.HEADER,row+fx.DESC,row+fx.CONTEXT,row+fx.SOURCE,row+fx.DIRECTION))
            self.assertEqual(request[5:9],(0,1,1,1));self.assertEqual(request[11:],(0,0))
            self.assertEqual(c.u(p+1408)&0xC1,0xC1,'native setters disable both collision and autonomous motion')
            self.assertEqual(c.u(row+fx.HEADER),0 if index==0 else 7)
            self.assertEqual(c.read(p+1456,16),c.read(c.u(c.models[1]+3436+17*4)+64,16))
            direction=struct.unpack('<4f',c.read(p+1376,16));self.assertAlmostEqual(sum(x*x for x in direction[:3]),1,places=5)
        self.assertEqual([c.u(a+0x9E4) for a in c.actors],[30000]*4)
        self.assertIn(('bone',7,31),c.events,'extra actual model is not its actor slot')
        self.assertIn(('bone',4,17),c.events)

    def test_manual_fire_activates_only_private_beam_children_once_without_actor_events(self):
        c=machine();rules=0x3600000;group=0x3610000;calls=[]
        row=fx.ROWS;d=row+fx.DESC;c.w(d+8,rules);c.w(d+12+5*16,group)
        c.write(group,bytes((5,5,0,0)));c.write(d+20+5*16,b'\x00')
        for i,(kind,selector) in enumerate(((1,1),(1,5),(1,0),(0,1),(2,1))):
            c.write(rules+64*i+8,bytes((kind,3,selector)))
        before=[c.read(p,0x1700) for p in c.models]
        def render(m):
            calls.append((m.r[4],m.r[5],m.r[6],m.r[7],m.r[8],m.r[9],m.r[10],m.r[11]))
            self.assertEqual(m.r[11]&1,1,'real native explicit event emits first-start flag')
            m.write(m.r[5]+320+m.r[10],b'\x02')
        c.callbacks[A(0x14FF50)]=render
        self.assertEqual(spawn(c),1)
        body=c.u(row+fx.R['body'])
        self.assertEqual([(x[5],x[6]) for x in calls],[(5,0),(5,1)])
        self.assertTrue(all(x[:5]==(d,body+656,body+64,body+1456,body+1376) for x in calls))
        for phase in (0,1):self.assertEqual(c.u(body+64+16+64*phase),31)
        c.r[4]=row;run(c,fx.IGNITE);self.assertEqual(len(calls),2)
        self.assertEqual(before,[c.read(p,0x1700) for p in c.models])

    def test_sbc_initializer_completes_before_ready_and_failure_stays_disarmed(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        sbc=SimpleNamespace(SELECT=0x06E92000,INIT=0x06E90000)
        for success in (0,1):
            c=machine(prepared=False);old=c.read(REGISTRY,156);original=c.u(c.models[0]+2348)
            with patch.dict(sys.modules,{'tag_rush_special_beam':sbc}):
                c.write(fx.INIT,fx.init_code(dict(BEAM,special_beam={'reviewed':True})))
            c.callbacks[A(0x14B108)]=lambda m:None
            def parse(m):
                arena=m.u(REGISTRY+80);m.w(m.r[5]+796,m.r[4])
                m.write(m.r[5]+780,struct.pack('<4I',1,6,0,1))
                for off,delta in ((764,0),(768,544),(776,2144)):m.w(m.r[5]+off,arena+delta)
                m.w(REGISTRY+92,2304)
            c.callbacks[A(0x14CEB0)]=parse;calls=[]
            def initialize(m):
                self.assertEqual(m.u(fx.CONTROL+fx.C['ready']),0)
                self.assertEqual(m.u(fx.CONTROL+fx.C['init_status']),1)
                self.assertEqual(m.read(REGISTRY,156),old)
                self.assertEqual(m.u(c.models[0]+2348),original)
                for row in (fx.ROWS,fx.ROWS+fx.STRIDE):
                    self.assertEqual(m.u(row+fx.R['prepared']),fx.PREPARED)
                calls.append('sbc');m.r[2]=success
            c.callbacks[sbc.INIT]=initialize
            run(c,fx.INIT)
            self.assertEqual(c.r[2],success);self.assertEqual(calls,['sbc'])
            self.assertEqual(c.u(fx.CONTROL+fx.C['ready']),success)
            self.assertEqual(c.u(fx.CONTROL+fx.C['init_status']),2 if success else 100)
            run(c,fx.INIT);self.assertEqual(c.r[2],0);self.assertEqual(calls,['sbc'])

    def test_optional_sbc_selection_preserves_native_palette_and_switches_each_idle_role(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        import tag_rush_colors as colors
        sbc=SimpleNamespace(SELECT=0x06E92000,INIT=0x06E90000)
        for charging in (False,True):
            c=machine();calls=[]
            with patch.dict(sys.modules,{'tag_rush_special_beam':sbc}):
                c.write(fx.CHARGE_SPAWN if charging else fx.SPAWN,
                        fx.spawn_code(color=True,charging=charging,special=True))
            def select(m):
                calls.append(('select',m.r[4],m.r[5]))
                m.r[2]=1;m.r[3]=int(m.r[5]in(22,23))
            def color(m):calls.append(('color',m.r[4]));m.r[2]=1
            c.callbacks[sbc.SELECT]=select;c.callbacks[colors.APPLY]=color
            for character in (22,23,0):
                c.w(c.models[0]+12,character);c.r[4:6]=[0,60]
                run(c,fx.CHARGE_SPAWN if charging else fx.SPAWN)
                self.assertEqual(c.r[2],1)
                self.assertEqual(c.u(fx.ROWS+fx.R['flavor']),int(character in(22,23)))
                if character in(22,23):self.assertNotIn(('color',fx.ROWS),calls)
                else:self.assertEqual(calls[-1],('color',fx.ROWS))
                # Finish actual ownership before the next source uses this row.
                run(c,fx.STOP);body=c.u(fx.ROWS+fx.R['body']);c.w(body+1408,0);run(c,fx.STOP)
            self.assertEqual([x[2]for x in calls if x[0]=='select'],[22,23,0])

    def test_sbc_selection_failure_or_unknown_flavor_precedes_emitter_creation(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        sbc=SimpleNamespace(SELECT=0x06E92000,INIT=0x06E90000)
        for success,flavor in ((0,0),(1,2)):
            c=machine()
            with patch.dict(sys.modules,{'tag_rush_special_beam':sbc}):
                c.write(fx.SPAWN,fx.spawn_code(special=True))
            def select(m):m.r[2]=success;m.r[3]=flavor
            c.callbacks[sbc.SELECT]=select
            self.assertEqual(spawn(c),0);self.assertFalse(c.requests)

    def test_sbc_manual_fire_accepts_25_rules_but_preserves_smaller_standard_bound(self):
        for flavor,count,expected in ((0,19,1),(0,20,0),(1,25,1),(1,26,0),(2,19,0)):
            c=machine();self.assertEqual(spawn(c),1);row=fx.ROWS;d=row+fx.DESC
            c.w(row+fx.R['ignited'],0);c.w(row+fx.R['flavor'],flavor)
            rules,group=0x3600000,0x3610000;c.w(d+8,rules);c.w(d+12+18*16,group)
            c.write(group,bytes((18,1,0,0)));c.write(d+20+18*16,bytes((count-1,)))
            c.write(rules+64*(count-1)+8,bytes((1,3,1)));calls=[]
            c.callbacks[A(0x14FF50)]=lambda m:calls.append((m.r[9],m.r[10]))
            c.r[4]=row;run(c,fx.IGNITE)
            self.assertEqual(c.r[2],expected,(flavor,count))
            self.assertEqual(calls,[(18,0)]if expected else [])

    def test_manual_fire_rejects_corrupt_private_rule_count(self):
        c=machine();row=fx.ROWS;d=row+fx.DESC;group=0x3610000
        c.w(d+12,group);c.write(group,bytes((0,20,0,0)))
        self.assertEqual(spawn(c),0)
        self.assertEqual(c.u(c.u(row+fx.R['body'])+1408)&2,2)
        self.assertEqual(c.u(row+fx.R['stopping']),1)

    def test_endpoints_follow_bones_and_pause_preserves_lifetime(self):
        c=machine();spawn(c,ticks=3);row=fx.ROWS;p=c.u(row+fx.R['body'])
        for model,bone,vec in ((c.models[0],31,(5.,-20.,8.,1.)),(c.models[1],17,(20.,-30.,40.,1.))):
            c.write(c.u(model+3436+bone*4)+64,struct.pack('<4f',*vec))
        run(c,fx.UPDATE);self.assertEqual(struct.unpack('<4f',c.read(p+1440,16)),(5.,-20.,8.,1.))
        self.assertEqual(struct.unpack('<4f',c.read(p+1456,16)),(20.,-30.,40.,1.))
        self.assertEqual(c.u(row+fx.R['ticks']),2)
        c.w(A(0x333700),1);before=c.read(row,fx.STRIDE);run(c,fx.UPDATE);self.assertEqual(c.read(row,fx.STRIDE),before)
        c.w(A(0x333700),0)
        for _ in range(3):run(c,fx.UPDATE)
        self.assertEqual(c.u(p+1408)&2,2);self.assertEqual(c.u(row+fx.R['stopping']),1)

    def test_live_private_descriptors_reset_native_texture_upload_cache_each_update(self):
        c=machine();spawn(c);spawn(c,1);masks=[]
        for slot in range(2):
            row=fx.ROWS+slot*fx.STRIDE
            for group,(stride,maskoff,count) in enumerate(((520,516,1),(264,260,6),(136,132,0),(72,68,1))):
                p=0x3800000+slot*0x8000+group*0x1000
                c.w(row+fx.DESC+764+4*group,p);c.w(row+fx.DESC+780+4*group,count)
                for j in range(count):
                    mask=p+stride*j+maskoff;c.w(mask,0x7FFFFFFF);masks.append(mask)
                    c.w(mask-4,0x12345678)
        run(c,fx.UPDATE)
        self.assertTrue(all(c.u(p)==0 for p in masks))
        self.assertTrue(all(c.u(p-4)==0x12345678 for p in masks))
        for p in masks:c.w(p,0x3F)
        run(c,fx.UPDATE);self.assertTrue(all(c.u(p)==0 for p in masks))

    def test_retiring_beams_refresh_texture_uploads_until_each_owned_node_is_gone(self):
        c=machine();spawn(c);spawn(c,1);masks=[]
        for slot in range(2):
            row=fx.ROWS+slot*fx.STRIDE;p=0x3800000+slot*0x1000
            c.w(row+fx.DESC+768,p);c.w(row+fx.DESC+784,2)
            masks.append([p+260,p+264+260])
            for mask in masks[-1]:c.w(mask-4,0x12345678)
        c.w(tag.CONTROL+tag.C['active'],0);c.w(tag.CONTROL+tag.C['ready'],0)
        for _ in range(3):
            for mask in masks[0]+masks[1]:c.w(mask,0x7FFFFFFF)
            run(c,fx.STOP);self.assertEqual(c.r[2],2)
            self.assertTrue(all(c.u(p)==0 for p in masks[0]+masks[1]))
            self.assertTrue(all(c.u(p-4)==0x12345678 for p in masks[0]+masks[1]))
        # A recycled node can no longer authorize writes to that descriptor.
        body=c.u(fx.ROWS+fx.R['body']);c.w(body,0x3700000)
        for mask in masks[0]+masks[1]:c.w(mask,0x3F)
        run(c,fx.STOP);self.assertEqual(c.r[2],1)
        self.assertTrue(all(c.u(p)==0x3F for p in masks[0]))
        self.assertTrue(all(c.u(p)==0 for p in masks[1]))

    def test_stop_runs_exact_native_private_child_cleanup_once_per_parent(self):
        c=machine();spawn(c);spawn(c,1)
        bodies=[c.u(fx.ROWS+i*fx.STRIDE+fx.R['body']) for i in range(2)]
        nodes=[c.u(fx.ROWS+i*fx.STRIDE+fx.R['node']) for i in range(2)]
        expected=[('retire_children',fx.ROWS+i*fx.STRIDE+fx.DESC,body+656) for i,body in enumerate(bodies)]
        run(c,fx.STOP)
        self.assertEqual([e for e in c.events if e[0]=='retire_children'],expected)
        self.assertTrue(all(c.u(body+1408)&0x12==0x12 for body in bodies))
        self.assertTrue(all(c.read(node,1)[0]&1 for node in nodes))
        run(c,fx.STOP)
        self.assertEqual([e for e in c.events if e[0]=='retire_children'],expected)
        # No scene/global battle gate is needed, but ownership must remain.
        c=machine();spawn(c);body=c.u(fx.ROWS+fx.R['body']);c.w(body+48,0x3700000)
        run(c,fx.STOP)
        self.assertFalse(any(e[0]=='retire_children'for e in c.events))

    def test_cleanup_waits_for_native_retirement_and_never_touches_recycled_nodes(self):
        c=machine();spawn(c);row=fx.ROWS;p=c.u(row+fx.R['body'])
        run(c,fx.STOP);self.assertEqual(c.r[2],1);self.assertEqual(c.u(p+1408)&2,2)
        self.assertNotEqual(c.u(row+fx.R['node']),0);self.assertEqual(spawn(c),0)
        c.w(p+1408,0);run(c,fx.STOP);self.assertEqual(c.r[2],0);self.assertEqual(c.u(row+fx.R['node']),0)
        c=machine();spawn(c);p=c.u(fx.ROWS+fx.R['body']);c.w(p,0x3700000);before=c.read(p,fx.BODY_SIZE)
        run(c,fx.STOP);self.assertEqual(c.r[2],0);self.assertEqual(c.read(p,fx.BODY_SIZE),before)

    def test_two_beams_retire_independently_without_reusing_a_live_slot(self):
        c=machine();self.assertEqual(spawn(c),1);self.assertEqual(spawn(c,1),1)
        rows=(fx.ROWS,fx.ROWS+fx.STRIDE);bodies=[c.u(r+fx.R['body']) for r in rows]
        run(c,fx.STOP);self.assertEqual(c.r[2],2)
        for row,body in zip(rows,bodies):
            self.assertEqual(c.u(body+1408)&2,2)
            self.assertNotEqual(c.u(row+fx.R['node']),0)
        c.w(bodies[0]+1408,0);run(c,fx.STOP);self.assertEqual(c.r[2],1)
        self.assertEqual(c.u(rows[0]+fx.R['node']),0)
        self.assertNotEqual(c.u(rows[1]+fx.R['node']),0);self.assertEqual(spawn(c,1),0)
        c.w(bodies[1]+1408,0);run(c,fx.STOP);self.assertEqual(c.r[2],0)
        self.assertEqual(spawn(c),1);self.assertEqual(spawn(c,1),1)
        self.assertEqual([c.u(a+0x9E4) for a in c.actors],[30000]*4)

    def test_stop_still_drains_after_scene_and_battle_publication_are_disabled(self):
        c=machine();spawn(c);spawn(c,1)
        rows=(fx.ROWS,fx.ROWS+fx.STRIDE);bodies=[c.u(r+fx.R['body']) for r in rows]
        c.w(tag.CONTROL+tag.C['active'],0);c.w(tag.CONTROL+tag.C['ready'],0)
        c.w(fx.CONTROL+fx.C['ready'],0);c.w(core.MODE+4,0);c.w(c.r[28]-22364,0)
        run(c,fx.STOP);self.assertEqual(c.r[2],2)
        self.assertTrue(all(c.u(p+1408)&2 for p in bodies))
        for body in bodies:c.w(body+1408,0)
        run(c,fx.STOP);self.assertEqual(c.r[2],0)
        self.assertTrue(all(c.u(r+fx.R['node'])==0 for r in rows))

    def test_stale_actor_or_scene_cancels_only_owned_effects(self):
        for addr in ('character','pointer','reload','scene','pool'):
            c=machine();spawn(c);p=c.u(fx.ROWS+fx.R['body'])
            if addr=='character':c.w(c.models[0]+12,99)
            elif addr=='pointer':c.w(core.MODELS,MODEL+0x100000)
            elif addr=='reload':c.w(c.models[0]+8,0)
            elif addr=='scene':c.w(tag.CONTROL+tag.C['active'],0)
            else:c.w(c.r[28]+fx.NATIVE_POOL_OFFSET,POOL+0x10000)
            before=c.read(p,fx.BODY_SIZE);run(c,fx.UPDATE)
            if addr=='pool':self.assertEqual(c.read(p,fx.BODY_SIZE),before)
            else:self.assertEqual(c.u(p+1408)&2,2)

    def test_missing_readiness_bad_bone_empty_pool_and_exhaustion_never_deal_damage(self):
        for kind in ('not ready','bad bone','empty pool','exhaustion','bad role','invalid duration','overlapping'):
            c=machine()
            if kind=='not ready':c.w(fx.CONTROL+fx.C['ready'],0)
            elif kind=='bad bone':c.w(c.models[0]+3436+31*4,0)
            elif kind=='empty pool':c.w(POOL+12,0)
            elif kind=='exhaustion':c.pool_fail=True
            elif kind=='overlapping':c.write(c.u(c.models[1]+3436+17*4)+64,c.read(c.u(c.models[0]+3436+31*4)+64,16))
            self.assertEqual(spawn(c,slot=2 if kind=='bad role' else 0,ticks=0 if kind=='invalid duration' else 30),0,kind)
            self.assertEqual([c.u(a+0x9E4) for a in c.actors],[30000]*4)

    def test_descriptor_init_restores_model_and_allocator_after_success_or_failure(self):
        for bad in (False,True):
            c=machine(prepared=False);old=c.read(REGISTRY,156);original=c.u(c.models[0]+2348);calls=[]
            def metadata(m):
                self.assertEqual(m.u(c.models[0]+2348),BEAM['metadata_address'])
                self.assertEqual(m.r[4:6],[0,2]);m.write(m.r[6],bytes(140));calls.append('metadata')
            def parse(m):
                self.assertEqual(m.r[6:10],[0,BEAM['resource_address'],0,4])
                self.assertEqual(m.u(REGISTRY+148),5);arena=m.u(REGISTRY+80)
                self.assertIn(arena,(fx.ARENAS,fx.ARENAS+fx.ARENA_SIZE))
                self.assertEqual(m.u(REGISTRY+88),fx.ARENA_SIZE);self.assertEqual(m.u(c.models[0]+2348),original)
                m.w(m.r[5]+796,m.r[4]);m.write(m.r[5]+780,struct.pack('<4I',1,5 if bad else 6,0,1))
                for offset,location in ((764,arena),(768,arena+544),(776,arena+2144)):m.w(m.r[5]+offset,location)
                m.w(REGISTRY+92,2304);calls.append('descriptor')
            c.callbacks[A(0x14B108)]=metadata;c.callbacks[A(0x14CEB0)]=parse
            run(c,fx.INIT);self.assertEqual(c.r[2],int(not bad));self.assertEqual(c.read(REGISTRY,156),old)
            self.assertEqual(c.u(c.models[0]+2348),original)
            self.assertEqual(c.u(fx.CONTROL+fx.C['ready']),int(not bad))
            if not bad:self.assertEqual(calls,['metadata','descriptor']*2)
            else:self.assertEqual(c.u(fx.CONTROL+fx.C['init_status']),100)
            before=list(calls);run(c,fx.INIT);self.assertEqual(c.r[2],0);self.assertEqual(calls,before)

    def test_unknown_emitter_node_disarms_creation_without_touching_foreign_memory(self):
        c=machine();foreign=0x3000000;c.write(foreign,bytes([0xCC])*64)
        c.callbacks[A(0x1AD7B8)]=lambda m:m.r.__setitem__(2,foreign)
        before=c.read(foreign,64);self.assertEqual(spawn(c),0)
        self.assertEqual(c.u(fx.CONTROL+fx.C['ready']),0);self.assertEqual(c.read(foreign,64),before)
        self.assertEqual(spawn(c,1),0)

    def test_init_rejects_bad_registry_or_reload_without_any_native_calls(self):
        for address,value in ((REGISTRY+152,0),(core.POINTERS,3),(MODEL+4,0),(MODEL+8,0),(MODEL+16,9)):
            c=machine(prepared=False);c.w(address,value);seen=[]
            c.callbacks[A(0x14B108)]=lambda m:seen.append('metadata')
            c.callbacks[A(0x14CEB0)]=lambda m:seen.append('parse')
            allocator=c.read(REGISTRY,156);original=c.u(c.models[0]+2348)
            run(c,fx.INIT);self.assertEqual(c.r[2],0);self.assertFalse(seen)
            self.assertEqual(c.read(REGISTRY,156),allocator);self.assertEqual(c.u(c.models[0]+2348),original)

    def test_init_rejects_parsed_array_outside_private_arena_after_restoring_registry(self):
        c=machine(prepared=False);old=c.read(REGISTRY,156);original=c.u(c.models[0]+2348)
        c.callbacks[A(0x14B108)]=lambda m:None
        def parse(m):
            m.w(m.r[5]+796,m.r[4]);m.write(m.r[5]+780,struct.pack('<4I',1,6,0,1))
            m.w(m.r[5]+764,0x100000);m.w(REGISTRY+92,2304)
        c.callbacks[A(0x14CEB0)]=parse
        run(c,fx.INIT);self.assertEqual(c.r[2],0);self.assertEqual(c.u(fx.CONTROL+fx.C['ready']),0)
        self.assertEqual(c.read(REGISTRY,156),old);self.assertEqual(c.u(c.models[0]+2348),original)

    def test_second_descriptor_failure_never_publishes_partially_prepared_pair(self):
        c=machine(prepared=False);old=c.read(REGISTRY,156);original=c.u(c.models[0]+2348)
        c.callbacks[A(0x14B108)]=lambda m:None
        def parse(m):
            arena=m.u(REGISTRY+80);m.w(m.r[5]+796,m.r[4])
            m.write(m.r[5]+780,struct.pack('<4I',1,6,0,1))
            for off,delta in ((764,0),(768,544),(776,2144)):m.w(m.r[5]+off,arena+delta)
            m.w(REGISTRY+92,2304 if arena==fx.ARENAS else fx.ARENA_SIZE+16)
        c.callbacks[A(0x14CEB0)]=parse
        run(c,fx.INIT);self.assertEqual(c.r[2],0)
        self.assertEqual(c.u(fx.ROWS+fx.R['prepared']),fx.PREPARED)
        self.assertEqual(c.u(fx.CONTROL+fx.C['ready']),0)
        self.assertEqual(c.u(fx.CONTROL+fx.C['init_status']),100)
        self.assertEqual(spawn(c),0);self.assertEqual(spawn(c,1),0)
        self.assertEqual(c.read(REGISTRY,156),old);self.assertEqual(c.u(c.models[0]+2348),original)

    def test_real_assets_are_required_and_scene_remains_unarmed(self):
        self.assertFalse(fx.installation(BEAM)['usable'])
        for changes in ({'reviewed':False},{'descriptor_counts':(1,7,0,1)}, {'resource_address':0x100000}):
            with self.assertRaises(ValueError):fx.init_code(dict(BEAM,**changes))

    def impact_machine(self):
        c=machine();c.w(scene.STATE,scene.SCENE_MAGIC)
        for role,index in enumerate((0,2,1)):
            row=scene.ROWS+role*scene.STRIDE;actor,model=c.actors[index],c.models[index]
            for key,value in (('index',index),('actor',actor),('model',model),('model_id',c.u(model+16)),('character',c.u(model+12)),('skeleton',0)):
                c.w(row+scene.R[key],value)
            c.fw(model+2404,.4)
            bone=0x3640000+role*0x100;c.w(model+3436+12*4,bone)
            c.write(bone+64,struct.pack('<4f',role*100.,-30.,50.,1.))
        c.w(c.r[28]-22512,0x2440000);c.w(0x2440000+12,0x2440100);c.w(0x2440100+32,0x2440000)
        c.w(c.r[28]-22516,0x2450000)
        c.w(0x2450000+4008,0x2460000);c.w(0x2450000+4016,0x2461000)
        native=elf_reader(elf_path(ROOT))[2];c.write(fx.NATIVE_IMPACT,native(fx.NATIVE_IMPACT,0x70))
        c.callbacks[A(0x11F588)]=lambda m:m.set_number(0,math.sin(m.number(12)))
        c.callbacks[A(0x11F620)]=lambda m:m.set_number(0,math.cos(m.number(12)))
        def impact(m):
            c.requests.append((m.r[4],m.r[5],m.read(m.r[6],64)));m.r[2]=0x2440200
        c.callbacks[A(0x1AD7B8)]=impact
        return c

    def test_native_strike_request_uses_exact_extra_model_and_encoded_bone(self):
        c=self.impact_machine();c.r[4:6]=[1,12];run(c,fx.IMPACT);self.assertEqual(c.r[2],1)
        pool,callbacks,request=c.requests[0]
        self.assertEqual((pool,callbacks),(0x2440000,A(0x2C3F20)))
        self.assertEqual(struct.unpack_from('<3I',request),(0,0,0))
        self.assertEqual(struct.unpack_from('<4f',request,16),(100.,-30.,50.,1.))
        direction=struct.unpack_from('<4f',request,32)
        self.assertAlmostEqual(direction[0],math.sin(.4),places=6);self.assertAlmostEqual(direction[2],math.cos(.4),places=6)
        self.assertEqual(struct.unpack_from('<4I',request,48),(16,7,0,0))
        self.assertEqual([c.u(a+0x9E4)for a in c.actors],[30000]*4)

    def test_first_opening_spark_uses_victim_torso_only_for_complete_absent_tail(self):
        c=self.impact_machine();c.r[4:6]=[0,5]
        run(c,fx.IMPACT);self.assertEqual(c.r[2],1)
        request=c.requests[0][2]
        torso=c.u(c.models[1]+3436+17*4)
        self.assertEqual(request[16:32],c.read(torso+64,16))
        self.assertEqual(struct.unpack_from('<4I',request,48),(16,4,0,0))
        self.assertIn(('bone',4,17),c.events)
        self.assertEqual([c.u(a+0x9E4)for a in c.actors],[30000]*4)
        # A real native tail marker keeps the original position and owner.
        c=self.impact_machine();c.w(c.models[0]+3436+5*4,c.u(c.models[0]+3436+12*4))
        c.r[4:6]=[0,5];run(c,fx.IMPACT);self.assertEqual(c.r[2],1)
        self.assertIn(('bone',0,5),c.events);self.assertNotIn(('bone',4,17),c.events)

    def test_absent_tail_spark_fallback_preserves_identity_and_source_scope_guards(self):
        for bad in ('phase','role','other bone','partial tail','bad nonzero pointer',
                    'victim identity','victim reload','victim torso','victim finite'):
            c=self.impact_machine();c.r[4:6]=[0,5]
            if bad=='phase':c.w(scene.STATE+scene.S['phase'],1)
            elif bad=='role':c.r[4]=1
            elif bad=='other bone':c.r[5]=4
            elif bad=='partial tail':c.w(c.models[0]+3436+4*4,c.u(c.models[0]+3436+12*4))
            elif bad=='bad nonzero pointer':c.w(c.models[0]+3436+5*4,3)
            elif bad=='victim identity':c.w(core.POINTERS+4,0)
            elif bad=='victim reload':c.w(c.models[1]+8,0)
            elif bad=='victim torso':c.w(c.models[1]+3436+17*4,0)
            elif bad=='victim finite':c.w(c.u(c.models[1]+3436+17*4)+64,0x7FC00000)
            run(c,fx.IMPACT);self.assertEqual(c.r[2],0,bad);self.assertFalse(c.requests,bad)

    def test_strike_guards_native_pool_and_captured_actor_without_loading_resources(self):
        for kind in ('pool','free node','descriptor','actor','reload','bone','retiring','inactive','paused','index overflow','model overflow','bad role','bad bone'):
            c=self.impact_machine()
            if kind=='pool':c.w(c.r[28]-22512,3)
            elif kind=='free node':c.w(0x2440000+12,0)
            elif kind=='descriptor':c.w(0x2450000+4008,0)
            elif kind=='actor':c.w(core.POINTERS+8,0)
            elif kind=='reload':c.w(c.models[2]+8,0)
            elif kind=='bone':c.w(c.models[2]+3436+12*4,0)
            elif kind=='retiring':c.w(scene.STATE+scene.S['retiring'],1)
            elif kind=='inactive':c.w(tag.CONTROL+tag.C['active'],0)
            elif kind=='paused':c.w(A(0x333700),1)
            elif kind=='index overflow':c.w(scene.ROWS+scene.STRIDE+scene.R['index'],0x40000002)
            elif kind=='model overflow':c.w(scene.ROWS+scene.STRIDE+scene.R['model_id'],0x40000007)
            c.r[4:6]=[3 if kind=='bad role' else 1,32 if kind=='bad bone' else 12]
            run(c,fx.IMPACT);self.assertEqual(c.r[2],0,kind);self.assertFalse(c.requests,kind)
            self.assertEqual([c.u(a+0x9E4)for a in c.actors],[30000]*4)

    def test_full_impact_pool_returns_without_damage_or_private_allocations(self):
        c=self.impact_machine();c.callbacks[A(0x1AD7B8)]=lambda m:m.r.__setitem__(2,0)
        allocator=c.read(REGISTRY,156);private=c.read(fx.CONTROL,fx.END-fx.CONTROL)
        c.r[4:6]=[0,12];run(c,fx.IMPACT);self.assertEqual(c.r[2],0)
        self.assertEqual(c.read(REGISTRY,156),allocator);self.assertEqual(c.read(fx.CONTROL,fx.END-fx.CONTROL),private)
        self.assertEqual([c.u(a+0x9E4)for a in c.actors],[30000]*4)


if __name__=='__main__':unittest.main()
