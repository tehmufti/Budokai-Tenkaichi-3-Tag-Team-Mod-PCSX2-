"""Execute placement MIPS and real native triangle math, without an emulator."""
import struct
import unittest
from prototype import ROOT, elf_reader
from camera_snapshot import read_ram
from test_terrain_crossing_guard import ScalarMips
import spawn_placement as spawn


class SpawnPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,_,native=elf_reader(ROOT/'analysis/SLUS_216.78');cls.native=staticmethod(native)

    def native_triangle(self,x,z,top,floor):
        """Run the game's actual X/Z inclusion + floor-height selection."""
        c=ScalarMips({'segments':[]});c.write(0x1B12E0,self.native(0x1B12E0,0x120))
        out,tri=0x1000000,0x1000100
        base,sx,sz=floor if isinstance(floor,tuple) else (floor,0,0)
        verts=[]
        for vx,vz in ((x-100,z-100),(x+100,z-100),(x,z+100)):
            verts.extend((vx,base+sx*vx+sz*vz,vz,1))
        verts.extend((sx,-1,sz,-base))
        c.write(tri,struct.pack('<16f',*verts));c.fw(out,x);c.fw(out+4,1e10);c.fw(out+8,z)
        c.fw(c.r[28]-29360,.01);c.r[4:7]=[out,tri,0x11223344];c.set_number(12,top)
        c.callbacks[0x121FA8]=lambda q:q.write(q.r[4],q.read(q.r[5],16))
        c.run(0x1B12E0);return c.read(out,36)

    def machine(self,floor=lambda x,z:-15-abs(x)*.5, clearance=0):
        previous=0x073D7000
        c=ScalarMips({'segments':[dict(address=spawn.CODE,data_hex=spawn.payload(previous).hex()),
                                  dict(address=spawn.QUERY,data_hex=spawn.query_code().hex())]})
        c.instruction_budget=100000
        manager=0x1800000;c.w(spawn.core.ACTORS,manager);c.w(manager,2)
        for off,v in ((0,1),(4,6),(8,manager),(12,6)):c.w(spawn.core.MODE+off,v)
        for off,v in ((0,1),(4,manager),(8,6)):c.w(spawn.CONTROL+off,v)
        c.w(spawn.fresh_memory.CONTROL+80,1)
        actors=[];models=[];calls=[];queries=[]
        for i in range(6):
            actor=0x1900000+i*0x2000;model=0x900000+i*0x2000
            actors.append(actor);models.append(model);c.w(spawn.core.POINTERS+4*i,actor)
            c.w(actor,i);c.w(actor+12,i);c.w(actor+0x948,11);c.w(spawn.core.MODELS+4*i,model)
            c.w(model+4,1);c.w(model+8,1);c.w(model+4000,model+3936);c.w(model+4004,model+3968)
            p=spawn.ROWS+i*spawn.STRIDE
            for off,v in ((0,actor),(4,model),(8,i),(12,i&1)):c.w(p+off,v)
            x=(i//2)*90*(-1 if i&1 else 1);z=50 if i&1 else -50;y=-15-clearance
            for off,v in ((0,x),(4,y),(8,z)):
                c.fw(actor+16+off,v);c.fw(actor+256+off,v)
                c.fw(model+2384+off,v);c.fw(model+2416+off,v)
            # Different animation offsets exercise native model→actor sync.
            c.fw(actor+52,2 if i>=2 else 0)
        def query(q):
            self.assertEqual(q.r[4]&0xFFFFFFFF,0xFFFFFFFF)
            p=q.r[6];x=q.fr(p);z=q.fr(p+8);top=q.number(12);queries.append((x,z,top))
            h=floor(x,z)
            if h is None:q.fw(p+4,1e10);q.fw(p+20,0)
            else:q.write(p,self.native_triangle(x,z,top,h))
            # A real native query may destroy every caller-saved temporary.
            # In particular the retry counter must not live in t8/t9.
            for r in (8,9,10,11,12,13,14,15,24,25):q.r[r]=0xDEAD0000+r
        def update(q):
            m=q.r[4];calls.append((0x24E3F8,m))
            for off in (0,4,8):q.fw(m+2416+off,q.fr(m+2384+off))
        def sphere(q):
            m=q.r[4];calls.append((0x24DC58,m))
            q.write(q.u(m+4000),q.read(m+2416,16));q.fw(q.u(m+4000)+16,6)
        def sync(q):
            actor=q.r[4];m=models[actors.index(actor)];calls.append((0x1D70E8,actor))
            for off in (0,4,8):q.fw(actor+16+off,q.fr(m+2416+off)-q.fr(actor+48+off))
        c.callbacks[0x230B38]=lambda q:None
        c.callbacks[0x1B14C0]=query
        c.callbacks[0x24E2B0]=lambda q:calls.append((0x24E2B0,q.r[4]))
        c.callbacks[0x24E3F8]=update;c.callbacks[0x24DC58]=sphere;c.callbacks[0x1D70E8]=sync
        c.callbacks[0x23FF78]=lambda q:q.r.__setitem__(2,77)
        return c,actors,models,calls,queries,previous

    def test_sloped_spawn_moves_all_extras_above_actual_floor_and_syncs_history(self):
        c,actors,models,calls,queries,previous=self.machine(
            floor=lambda x,z:(-15,-.5 if x>=0 else .5,0))
        leaders=[c.read(x,0x1600) for x in actors[:2]];registers=c.r.copy();fpu=list(range(32));c.f=fpu.copy()
        c.run(spawn.CODE,stops=[previous])
        self.assertEqual(c.u(spawn.CONTROL),5);self.assertEqual(c.u(spawn.CONTROL+12),4)
        self.assertEqual([c.read(x,0x1600) for x in actors[:2]],leaders)
        self.assertEqual(c.r,registers);self.assertEqual(c.f[20:],fpu[20:])
        self.assertEqual(len(queries),8)
        for i in range(2,6):
            actor,m=actors[i],models[i];expected=-15-(i//2)*45-.25
            self.assertAlmostEqual(c.fr(m+2420),expected)
            self.assertAlmostEqual(c.fr(actor+20)+c.fr(actor+52),expected)
            self.assertEqual(c.read(actor+16,48),c.read(actor+256,48))
            self.assertEqual(c.read(c.u(m+4000),32),c.read(c.u(m+4004),32))
            self.assertEqual(c.u(m+2596),77)
        before=len(calls),len(queries);c.run(spawn.CODE,stops=[previous]);self.assertEqual((len(calls),len(queries)),before)

    def test_aerial_clearance_and_lower_terrain_are_preserved(self):
        c,_,models,_,_,previous=self.machine(floor=lambda x,z:-15+abs(x)*.5,clearance=100)
        c.run(spawn.CODE,stops=[previous]);self.assertEqual(c.u(spawn.CONTROL),5)
        for i in range(2,6):self.assertAlmostEqual(c.fr(models[i]+2420),-15+(i//2)*45-100-.25)

    def test_model_ids_are_not_assumed_to_equal_actor_indices_or_teams(self):
        c,actors,models,_,_,previous=self.machine()
        for i,model_id in enumerate((0,1,7,10,4,6)):
            c.w(actors[i]+12,model_id);c.w(spawn.ROWS+i*spawn.STRIDE+8,model_id)
            c.w(spawn.core.MODELS+4*model_id,models[i])
        c.run(spawn.CODE,stops=[previous]);self.assertEqual(c.u(spawn.CONTROL),5)
        self.assertEqual(c.u(spawn.CONTROL+12),4)

    def test_cliff_or_missing_floor_falls_back_toward_verified_leader_footprint(self):
        for floor in (lambda x,z:None if abs(x)>30 else -15,lambda x,z:1000 if abs(x)>30 else -15):
            c,_,models,_,_,previous=self.machine(floor=floor);c.run(spawn.CODE,stops=[previous])
            self.assertEqual(c.u(spawn.CONTROL),5);self.assertEqual(c.u(spawn.CONTROL+20),4)
            self.assertTrue(all(abs(c.fr(m+2416))<=30 for m in models[2:]))

    def test_failed_plan_never_partially_changes_actor_or_model_positions(self):
        c,actors,models,_,_,previous=self.machine(floor=lambda x,z:None if z>0 else -15)
        before=[(c.read(a,0x1600),c.read(m,0x1670)) for a,m in zip(actors,models)]
        c.run(spawn.CODE,stops=[previous]);self.assertEqual(c.u(spawn.CONTROL),103)
        self.assertEqual(c.u(spawn.CONTROL+12),0)
        self.assertEqual([(c.read(a,0x1600),c.read(m,0x1670)) for a,m in zip(actors,models)],before)

    def test_stale_capture_combat_input_and_unheld_state_do_not_place(self):
        for change,error in ((lambda c,a,m:c.w(a[5],4),101),(lambda c,a,m:c.w(a[4]+0x948,35),102),
                             (lambda c,a,m:c.w(a[0]+0x1278,1),102),
                             (lambda c,a,m:c.w(spawn.fresh_memory.CONTROL+80,0),102)):
            c,actors,models,calls,queries,previous=self.machine();change(c,actors,models)
            c.run(spawn.CODE,stops=[previous]);self.assertEqual(c.u(spawn.CONTROL),error)
            self.assertEqual((calls,queries),([],[]))

    def test_prearmed_release_survives_success_but_failure_cancels_owned_start_and_intro(self):
        for success in (True,False):
            c,actors,_,_,_,previous=self.machine(floor=(lambda x,z:-15) if success else (lambda x,z:None))
            manager=c.u(spawn.core.ACTORS)
            for control in (spawn.start.CONTROL,spawn.intro.CONTROL):
                for off,value in ((0,1),(4,1),(8,manager)):c.w(control+off,value)
            c.run(spawn.CODE,stops=[previous])
            self.assertEqual(c.u(spawn.CONTROL),5 if success else 103)
            for control in (spawn.start.CONTROL,spawn.intro.CONTROL):
                self.assertEqual(c.u(control+4),int(success));self.assertEqual(c.u(control),1)
            if not success:
                # Every failed frame cancels retries; it cannot eventually
                # release because a host/export set the bit again.
                c.w(spawn.start.REQUEST,1);c.run(spawn.CODE,stops=[previous])
                self.assertEqual(c.u(spawn.start.REQUEST),0)
        c,_,_,_,_,previous=self.machine(floor=lambda x,z:None)
        c.w(spawn.start.CONTROL,1);c.w(spawn.start.REQUEST,1);c.w(spawn.start.CONTROL+8,0x123456)
        c.run(spawn.CODE,stops=[previous]);self.assertEqual(c.u(spawn.start.REQUEST),1)

    def test_real_preset_builder_requires_hold_and_preserves_guarded_native_helpers(self):
        ram=read_ram(ROOT/'runtime128/sstates/SLUS-21678 (428113C2).147.p2s')
        with self.assertRaisesRegex(ValueError,'hold'):spawn.build_memory(ram)
        manifest=spawn.ready_manifest(ram);seen=set()
        for b in manifest['blocks']:
            p=b['address'];data=bytes.fromhex(b['data_hex'])
            self.assertEqual(ram[p:p+len(data)].hex(),b['expected_hex'])
            self.assertFalse(seen.intersection(range(p,p+len(data))));seen.update(range(p,p+len(data)))
        self.assertNotIn(0x1B14C0,seen);self.assertNotIn(0x1B12E0,seen)
        v=bytearray(ram)
        for b in manifest['blocks']:
            p=b['address'];data=bytes.fromhex(b['data_hex']);v[p:p+len(data)]=data
        with self.assertRaisesRegex(ValueError,'occupied'):spawn.build_memory(v)


if __name__=='__main__':unittest.main()
