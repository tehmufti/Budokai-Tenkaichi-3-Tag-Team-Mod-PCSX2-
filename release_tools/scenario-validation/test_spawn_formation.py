"""Native initial setter/sphere construction and formation geometry, offline only."""
import math,struct,unittest
from camera_snapshot import read_ram
from prototype import ROOT,elf_reader
from test_extra_special_pools import Cpu
from test_spawn_placement import SpawnPlacementTests
import spawn_placement as s
import team_participation as participation
from legacy_fixtures import setUpModule, tearDownModule  # noqa: F401 - fixtures are three-a-side builds
NATIVE=elf_reader(ROOT/'analysis/SLUS_216.78')[2]
class FormCpu(Cpu):
 def extra_instruction(self,ins,pc):
  if ins>>26==17 and (ins>>21)&31==16 and ins&63 in (4,7):
   v=self.number((ins>>11)&31);self.set_number((ins>>6)&31,math.sqrt(v) if ins&63==4 else -v);return
  if ins>>26==17 and (ins>>21)&31==16 and ins&63==0x32:
   self.condition=self.number((ins>>11)&31)==self.number((ins>>16)&31);return
  return super().extra_instruction(ins,pc)
class FormationTests(unittest.TestCase):
 def machine(self,counts=(3,3),floor=lambda x,z:-15,blocked=lambda x,z:False,anchors=((0,-50),(0,50))):
  old=SpawnPlacementTests();old.native=NATIVE
  c,aa,mm,calls,queries,tail=old.machine(floor=floor);c.__class__=FormCpu;c.instruction_budget=300000
  n,mask=participation.layout(counts)
  for o in (4,12):c.w(s.core.MODE+o,n)
  for o,v in ((8,n),(28,2),(32,mask),(36,0x1500000),(40,0x1500100),(44,0x1500200),(64,1),(68,0x1500300)):c.w(s.CONTROL+o,v)
  for o,v in ((0,1),(8,c.u(s.core.ACTORS)),(12,n)):c.w(s.start.CONTROL+o,v)
  c.w(s.STAGE,0x1500000);c.w(0x1500004,0x1500100);c.w(0x150012C,0x1500200);c.w(0x1500038,1);c.w(0x150003C,0x1500300)
  for side,(x,z) in enumerate(anchors):
   look=anchors[1-side];d=struct.pack('<8f',x,0,z,0,look[0],0,look[1],0)
   c.write(0x1500200+side*32,d);c.write(s.CONTROL+0x80+side*32,d)
  for i,(a,m) in enumerate(zip(aa,mm)):
   row=s.ROWS+i*s.STRIDE;c.w(row+0x48,(mask>>i)&1);c.fw(m+0x1004,6);c.w(row+0x64,c.u(m+0x1004));c.fw(row+0x20,6);c.fw(row+0x24,-10)
   for j,o in enumerate((0xD6C,0xDB0)):
    b=0x3000000+i*0x200+j*0x80;c.w(m+o,b);c.w(row+0x68+4*j,b);c.write(b+0x40,c.read(m+2416,12));c.fw(b+0x44,c.fr(m+2420)-(0 if j==0 else 8.8))
   if not mask>>i&1:c.w(a+0x948,216);c.w(m+8,0)
  c.fw(c.r[28]-0x5C24,1.2)
  c.write(c.r[28]-0x5C84,NATIVE(c.r[28]-0x5C84,16))
  plan=s.candidate_plan(anchors,[6]*n,mask);cursor=s.CANDIDATES
  for i,points in enumerate(plan['candidates']):
   row=s.ROWS+i*s.STRIDE;c.w(row+0x4C,len(points));c.w(row+0x50,cursor)
   for x,z in points:c.write(cursor,struct.pack('<2f',x,z));cursor+=8
  for p,b in ((s.CODE,s.formation_payload(tail)),(s.FOOTPRINT,s.footprint_code()),(s.BODY,s.body_code())):c.write(p,b)
  for p,l in ((0x1D7418,0x158),(0x24D920,0xB0),(0x2505A8,16),(0x241F10,0x140)):c.write(p,NATIVE(p,l))
  c.callbacks[0x121FA8]=lambda q:q.write(q.r[4],q.read(q.r[5],16))
  c.callbacks[0x2A9ACC]=lambda q:q.write(q.r[4],bytes(q.r[6]))
  c.callbacks[0x28F770]=lambda q:q.set_number(0,math.sqrt(q.number(12)))
  c.callbacks[0x28F740]=lambda q:q.set_number(0,math.atan2(q.number(12),q.number(13)))
  c.callbacks[0x1DC298]=lambda q:q.r.__setitem__(2,q.r[4]+16)
  c.callbacks[0x1DC280]=lambda q:q.r.__setitem__(2,c.u(s.core.MODELS+4*c.u(q.r[4]+12)))
  c.callbacks[0x204EA0]=lambda q:q.set_number(0,10)
  c.callbacks[0x11F588]=lambda q:q.set_number(0,math.sin(q.number(12)))
  c.callbacks[0x11F620]=lambda q:q.set_number(0,math.cos(q.number(12)))
  c.callbacks[0x1DABE8]=lambda q:calls.append(('flag',q.r[4],q.r[5]))
  def swap(q):
   m=q.r[4];x,y=c.u(m+4000),c.u(m+4004);c.w(m+4000,y);c.w(m+4004,x)
  c.callbacks[0x24DD20]=swap
  def anchor(q):
   x,z=anchors[q.r[4]];h=floor(x,z);h=-15 if isinstance(h,tuple) else h
   q.write(q.r[5],struct.pack('<4f',x,1e10 if h is None else h,z,1));q.write(q.r[6],bytes(16));q.r[2]=0
  c.callbacks[0x2427A0]=anchor;c.callbacks[0x23FDB0]=lambda q:q.r.__setitem__(2,0)
  c.callbacks[0x240110]=lambda q:q.r.__setitem__(2,0x1500300)
  c.callbacks[0x1B16F0]=lambda q:q.w(q.r[28]-0x50B8,0xCAFE)
  body=[]
  def visit(q):
   self.assertEqual(q.r[8],0x1B26E0);self.assertEqual(q.u(q.r[7]+192),0)
   x,y,z=struct.unpack('<3f',q.read(q.r[7],12));r=q.fr(q.r[7]+16)
   self.assertAlmostEqual(q.fr(q.r[7]+20),r*r,places=4);body.append((x,y,z,r));q.w(q.r[7]+200,int(blocked(x,z)))
   for o in s.QUERY_GLOBALS:q.w(q.r[28]+o,q.r[7])
  c.callbacks[0x1B1708]=visit
  return c,aa[:n],mm[:n],calls,queries,body,tail,mask
 def test_all_uneven_layouts_native_facing_history_nonoverlap_and_reserved_slots(self):
  for counts in ((2,1),(1,2),(3,1),(1,3),(3,2),(2,3),(2,2),(3,3)):
   c,aa,mm,calls,queries,body,tail,mask=self.machine(counts)
   absent={i:(c.read(a,0x1600),c.read(mm[i],0x1670)) for i,a in enumerate(aa) if not mask>>i&1}
   regs=c.r.copy();c.f[20:]=list(range(20,32));fp=c.f[20:].copy()
   for j,o in enumerate(s.QUERY_GLOBALS):c.w(c.r[28]+o,0xACAB0000+j)
   c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),5,counts);self.assertEqual(c.r,regs);self.assertEqual(c.f[20:],fp)
   self.assertEqual(c.u(s.CONTROL+12),mask.bit_count());self.assertEqual([c.u(c.r[28]+o) for o in s.QUERY_GLOBALS],[0xACAB0000+j for j in range(6)])
   for i,(a,m) in enumerate(zip(aa,mm)):
    if i in absent:self.assertEqual((c.read(a,0x1600),c.read(m,0x1670)),absent[i]);continue
    self.assertEqual(c.read(a+16,240),c.read(a+256,240));self.assertEqual(c.read(c.u(m+4000),32),c.read(c.u(m+4004),32))
    other=mm[1-(i&1)];yaw=math.atan2(c.fr(other+2416)-c.fr(m+2416),c.fr(other+2424)-c.fr(m+2424))
    self.assertAlmostEqual(math.sin(c.fr(a+36)),math.sin(yaw),places=5);self.assertAlmostEqual(math.cos(c.fr(a+36)),math.cos(yaw),places=5)
    self.assertAlmostEqual(c.fr(m+2420),-15.25);self.assertEqual(c.u(a+0x948),11)
   self.assertEqual([c.fr(m+2416) for m in mm[:2]],[0,0]);self.assertEqual([c.fr(m+2424) for m in mm[:2]],[-50,50])
   for i in range(len(mm)):
    for j in range(i):
     if mask>>i&1 and mask>>j&1:self.assertGreaterEqual(math.hypot(c.fr(mm[i]+2416)-c.fr(mm[j]+2416),c.fr(mm[i]+2424)-c.fr(mm[j]+2424)),48 if (i&1)!=(j&1) else 32)
   before=[c.read(a,0x1600) for a in aa];number=len(queries);c.run(s.CODE,stops=[tail]);self.assertEqual(number,len(queries));self.assertEqual(before,[c.read(a,0x1600) for a in aa])
 def test_body_fallback_never_stacks_and_failed_planning_is_atomic(self):
  c,aa,mm,_,_,_,tail,_=self.machine(blocked=lambda x,z:abs(x)>70);c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),5)
  self.assertGreater(c.u(s.CONTROL+20),0);self.assertTrue(all(abs(c.fr(m+2416))>=40 for m in mm[2:]))
  c,aa,mm,_,_,_,tail,_=self.machine(blocked=lambda x,z:min(math.hypot(x,z-50),math.hypot(x,z+50))>8);before=[(c.read(a,0x1600),c.read(m,0x1670)) for a,m in zip(aa,mm)]
  c.w(s.start.REQUEST,1);c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),104);self.assertEqual(c.u(s.start.REQUEST),0)
  self.assertEqual(before,[(c.read(a,0x1600),c.read(m,0x1670)) for a,m in zip(aa,mm)])
 def test_footprint_hole_and_cliff_use_only_safe_alternatives(self):
  for floor in (lambda x,z:None if x<-1 else -15,lambda x,z:-15 if x>=-1 else -500):
   c,aa,mm,_,_,_,tail,_=self.machine(floor=floor)
   c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),5)
   for m in mm:
    self.assertGreaterEqual(c.fr(m+2416)-6,-1)
    self.assertAlmostEqual(c.fr(m+2420),-15.25)
 def test_narrow_road_uses_separated_rear_columns(self):
  c,_,mm,_,_,_,tail,_=self.machine(floor=lambda x,z:-15 if abs(x)<=14 else None,blocked=lambda x,z:abs(x)>8)
  c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),5)
  self.assertGreater(c.u(s.CONTROL+20),0)
  for i,m in enumerate(mm):
   self.assertLessEqual(abs(c.fr(m+2416)),8)
   self.assertAlmostEqual(c.fr(m+2420),-15.25)
   for j in range(i):
    separation=math.hypot(c.fr(m+2416)-c.fr(mm[j]+2416),c.fr(m+2424)-c.fr(mm[j]+2424))
    self.assertGreaterEqual(separation,48 if (i&1)!=(j&1) else 32)
 def test_only_two_safe_footprints_still_fail_atomically(self):
  floor=lambda x,z:-15 if min(math.hypot(x,z-50),math.hypot(x,z+50))<=8 else None
  c,aa,mm,_,_,_,tail,_=self.machine(floor=floor)
  before=[(c.read(a,0x1600),c.read(m,0x1670)) for a,m in zip(aa,mm)]
  c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),104)
  self.assertEqual(before,[(c.read(a,0x1600),c.read(m,0x1670)) for a,m in zip(aa,mm)])
 def test_candidate_budget_fits_reserved_array_with_all_six_large_bodies(self):
  for radius in (1,6,32,512):
   result=s.candidate_plan(((40,-30),(-40,30)),[radius]*6,63)
   self.assertTrue(all(len(points)<=s.MAX_CANDIDATES for points in result['candidates']))
   self.assertLessEqual(sum(map(len,result['candidates']))*8,s.ANCHORS-s.CANDIDATES)
 def test_unreleased_gate_input_and_stage_identity_fail_closed(self):
  for p,v,status in ((s.start.CONTROL+20,1,106),(s.start.CONTROL,0,106),(s.STAGE,0,105),(0x1900000+0x948,35,102),(0x1900000+0x1278,1,102)):
   c,_,_,calls,queries,body,tail,_=self.machine();c.w(p,v);c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),status);self.assertEqual((calls,queries,body),([],[],[]))
 def test_small_stage_gap_has_minimum_opposing_clearance(self):
  c,_,mm,_,_,_,tail,_=self.machine(anchors=((0,-8),(0,8)));c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),5);self.assertGreaterEqual(c.fr(mm[1]+2424)-c.fr(mm[0]+2424),48)
 def test_rotated_authored_anchors_and_sloping_native_terrain(self):
  anchors=((-51.423,61.284),(51.423,-61.284))
  c,aa,mm,_,_,_,tail,mask=self.machine((3,2),floor=lambda x,z:(-15,.05,.03),anchors=anchors)
  c.run(s.CODE,stops=[tail]);self.assertEqual(c.u(s.CONTROL),5)
  for i,m in enumerate(mm):
   if not mask>>i&1:continue
   x,z=c.fr(m+2416),c.fr(m+2424);center=-15+.05*x+.03*z
   self.assertLess(c.fr(m+2420),center)
   if i<2:self.assertAlmostEqual(x,anchors[i][0],places=4);self.assertAlmostEqual(z,anchors[i][1],places=4)
 def test_actual_native_spawn_lookup_returns_position_and_rotation_homogeneous_one(self):
  c,_,_,_,_,_,_,_=self.machine();c.callbacks.pop(0x2427A0);c.write(0x2427A0,NATIVE(0x2427A0,0x118))
  c.callbacks[0x23FBF8]=lambda q:q.r.__setitem__(2,1)
  def floor(q):q.fw(q.r[6]+4,-15);q.r[2]=0
  c.callbacks[0x2426E0]=floor
  for side in (0,1):
   p=0x3100000;c.r[4:8]=[side,p,p+16,0];c.run(0x2427A0)
   self.assertEqual(c.fr(p+12),1);self.assertEqual(c.fr(p+28),1);self.assertEqual(c.fr(p+4),-15)
 def test_intro_replay_chain_does_not_reapply_or_shift_finished_formation(self):
  c,aa,mm,_,queries,_,tail,_=self.machine();c.run(s.CODE,stops=[tail])
  c.write(s.start.CODE,s.start.code(tail));c.write(s.intro.CODE,s.intro.payload(s.start.CODE))
  # Continue finished formation through the normal intro -> start chain.
  c.write(s.CODE,s.formation_payload(s.intro.CODE));phase=0x1600000;c.w(s.intro.BATTLE,phase);c.w(phase,3)
  for o,v in ((0,1),(4,1),(8,c.u(s.core.ACTORS)),(12,6),(16,phase)):c.w(s.intro.CONTROL+o,v)
  for i,a in enumerate(aa):c.w(s.start.CONTROL+0x80+4*i,a);c.w(s.start.CONTROL+0x40+4*i,int(i>0))
  c.callbacks[0x216AF8]=lambda q:q.w(phase+4,0x22FAE8)
  poses=[c.read(m+2384,48) for m in mm];before=len(queries)
  for state in (3,1,1,2,2,3):
   c.w(phase,state);c.run(s.CODE,stops=[tail]);self.assertEqual(poses,[c.read(m+2384,48) for m in mm])
  self.assertEqual(c.u(s.start.CONTROL+20),1);self.assertEqual(before,len(queries))
 def test_exact_pending_preset_upgrade_and_source_preservation(self):
  ram=read_ram(ROOT/'runtime128/sstates/SLUS-21678 (428113C2).08.p2s');before=bytes(ram);result=s.upgrade_memory(ram);self.assertEqual(ram,before)
  self.assertFalse(any(b['address']==s.HOOK for b in result['blocks']))
  for b in result['blocks']:self.assertEqual(b['expected_hex'],ram[b['address']:b['address']+len(bytes.fromhex(b['data_hex']))].hex())
  for p,v in ((s.CONTROL,5),(s.start.CONTROL+20,1),(s.CODE,0),(s.HOOK,0),(s.CODE+len(s.payload(0))-8,(2<<26)|(0x073D7000>>2)),(s.start.CODE,0),(0x24E2B0,0)):
   bad=bytearray(ram);struct.pack_into('<I',bad,p,v)
   with self.assertRaises(ValueError):s.upgrade_memory(bad)
if __name__=='__main__':unittest.main()
