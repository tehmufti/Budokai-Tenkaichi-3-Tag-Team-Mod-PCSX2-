"""Real native stage position lookup with expanded actors and terrain queries."""
import struct
import unittest
import stage_transition as fix
import test_spawn_formation as formation


class StageCpu(formation.FormCpu):
    def extra_instruction(self,ins,pc):
        if ins>>26==17 and (ins>>21)&31 in (2,6):
            rt=(ins>>16)&31
            if (ins>>21)&31==2:self.r[rt]=getattr(self,'fcr31',0)
            else:self.fcr31=self.r[rt]&0xFFFFFFFF
            return None
        return super().extra_instruction(ins,pc)


class StageTransitionTests(unittest.TestCase):
    def machine(self,**kw):
        c,aa,mm,calls,queries,body,tail,mask=formation.FormationTests().machine(**kw)
        c.__class__=StageCpu
        for p,b in fix.pieces():c.write(p,b)
        c.write(fix.CONTROL,struct.pack('<3I',fix.MAGIC,c.u(fix.core.ACTORS),len(aa)))
        for p,t,_ in fix.HOOKS:c.w(p,(3<<26)|(t>>2))
        c.write(0x2427A0,fix.NATIVE(0x2427A0,0x118));c.callbacks.pop(0x2427A0)
        c.callbacks[0x23FBF8]=lambda q:q.r.__setitem__(2,1)
        def floor(q):q.fw(q.r[6]+4,-15);q.r[2]=0
        c.callbacks[0x2426E0]=floor
        c.callbacks[0x23FF78]=lambda q:q.r.__setitem__(2,0)
        for a,m in zip(aa,mm):c.w(m+16,c.u(a+12))
        for side in range(2,6):c.write(0x1500200+side*32,struct.pack('<8f',1e20,0,1e20,0,1e20,0,1e20,0))
        return c,aa,mm,queries,body

    def run_position(self,c,a):
        c.r[4:8]=[c.u(a),0x3100000,0x3100010,0];c.r[16]=a
        c.run(fix.CODE);return struct.unpack('<4f',c.read(0x3100000,16))

    def test_real_native_lookup_never_indexes_extra_record_and_spreads_live_models(self):
        c,aa,mm,queries,body=self.machine();positions=[]
        for physical,a in enumerate(aa):
            before=c.read(a,0x1600);model=c.read(mm[physical],0x1670)
            pos=self.run_position(c,a);positions.append(pos)
            self.assertEqual(c.read(a,0x1600),before);self.assertEqual(c.read(mm[physical],0x1670),model)
            self.assertTrue(all(abs(v)<1000 for v in pos));self.assertEqual(pos[3],1)
            self.assertAlmostEqual(pos[1],-15.25 if physical>=2 else -15)
        self.assertEqual(positions[0][2],-50);self.assertEqual(positions[1][2],50)
        self.assertLess(positions[2][2],-50);self.assertGreater(positions[3][2],50)
        self.assertLess(positions[2][0]*positions[4][0],0)
        self.assertEqual(c.u(fix.CONTROL+28),4);self.assertEqual(c.u(fix.CONTROL+12),4)
        self.assertTrue(queries);self.assertTrue(body)

    def test_failed_candidate_keeps_native_anchor_and_never_holds_match(self):
        c,aa,_,queries,body=self.machine(blocked=lambda x,z:True)
        pos=self.run_position(c,aa[4]);self.assertEqual(pos,(0.,-15.,-50.,1.))
        self.assertEqual(c.u(fix.CONTROL+20),1);self.assertEqual(len(body),len(fix.OFFSETS))
        self.assertEqual(c.u(0x3337B8),0)

    def test_dead_reset_is_skipped_live_state_and_native_fallback_unchanged(self):
        c,aa,mm,_,_=self.machine(counts=(3,2));called=[]
        c.callbacks[0x1C0AA8]=lambda q:called.append(q.r[4])
        for i,a in enumerate(aa):
            c.w(a+0x994,0);c.w(a+0x9E4,1000 if i<4 else 0)
            c.w(a+2376,236);c.w(a+2388,239)
            before=c.read(a,0x1600);c.r[4]=a;c.run(fix.RESET)
            self.assertEqual(c.read(a,0x1600),before)
        self.assertEqual(called,aa[:4]);self.assertEqual(c.u(fix.CONTROL+24),2)
        c.w(fix.CONTROL+4,0);c.r[4]=aa[5];c.run(fix.RESET)
        self.assertEqual(called[-1],aa[5])

    def test_output_commit_and_native_query_globals_registers_preserved(self):
        c,aa,_,_,_=self.machine();c.r[4:8]=[4,0x3100000,0x3100010,0];c.r[16]=aa[4]
        c.r[2]=0xABC;regs=c.r.copy();fpu=c.f.copy()
        for i,o in enumerate(fix.spawn.QUERY_GLOBALS):c.w(c.r[28]+o,0xB000+i)
        c.run(fix.CODE);regs[2]=0
        self.assertEqual(c.r,regs);self.assertEqual(c.f,fpu)
        self.assertEqual([c.u(c.r[28]+o) for o in fix.spawn.QUERY_GLOBALS],[0xB000+i for i in range(6)])

    def test_actual_native_reset_position_setter_keeps_action_resources_and_control(self):
        c,aa,mm,_,_=self.machine();a,m=aa[4],mm[4]
        c.write(0x1D7570,fix.NATIVE(0x1D7570,0x58));c.w(0x1D7594,(3<<26)|(fix.CODE>>2))
        c.w(a+2376,236);c.w(a+2388,239);c.w(a+0x1278,1)
        identity=c.read(a,16);actions=c.read(a+2376,28);control=c.read(a+0x1278,16)
        resources=c.read(m,32);targets=c.read(fix.core.TABLE,24)
        c.r[4]=a;c.run(0x1D7570)
        self.assertEqual(c.read(a,16),identity);self.assertEqual(c.read(a+2376,28),actions)
        self.assertEqual(c.read(a+0x1278,16),control);self.assertEqual(c.read(m,32),resources)
        self.assertEqual(c.read(fix.core.TABLE,24),targets)
        self.assertGreater(c.fr(m+2416),60);self.assertLess(c.fr(m+2424),-90)

    def test_actual_native_reset_loop_keeps_dead_absent_fighters_unmodified(self):
        c,aa,_,_,_=self.machine();called=[]
        c.write(0x1C29D8,fix.NATIVE(0x1C29D8,0x50));c.w(0x1C29F8,(3<<26)|(fix.RESET>>2))
        c.callbacks[0x1DC168]=lambda q:q.r.__setitem__(2,len(aa))
        c.callbacks[0x1DC178]=lambda q:q.r.__setitem__(2,aa[q.r[4]])
        c.callbacks[0x1C0AA8]=lambda q:called.append(q.r[4])
        for i,a in enumerate(aa):c.w(a+0x994,0);c.w(a+0x9E4,1000 if i in (0,2,3) else 0)
        before=[c.read(a,0x1600) for a in aa];c.run(0x1C29D8)
        self.assertEqual(called,[aa[i] for i in (0,2,3)])
        self.assertEqual([c.read(a,0x1600) for a in aa],before)

    def test_actual_user_archive_builder_guards_and_idempotency(self):
        from camera_snapshot import read_ram
        import patch_state
        source=fix.ROOT/'analysis/prepared-states/20260916-162641-89c35bb7/17-playable-team.p2s'
        ram=read_ram(source);before=bytes(ram);manifest=fix.build_memory(ram)
        updated=patch_state.patch_memory(ram,manifest)[0]
        self.assertEqual(ram,before);self.assertEqual(fix.build_memory(updated)['blocks'],[])
        for p in (0x1D7594,0x1C29F8,0x1C0AA8,0x2427A0):
            bad=bytearray(ram);bad[p]^=1
            with self.assertRaises(ValueError):fix.build_memory(bad)
        bad=bytearray(updated);bad[fix.CODE]^=1
        with self.assertRaises(ValueError):fix.build_memory(bad)

    def test_reused_native_terrain_dependencies_are_guarded_before_and_after_install(self):
        from camera_snapshot import read_ram
        import patch_state
        source=fix.ROOT/'analysis/prepared-states/20260916-162641-89c35bb7/17-playable-team.p2s'
        clean=read_ram(source)
        installed=patch_state.patch_memory(clean,fix.build_memory(clean))[0]
        for name,source_ram in (('fresh',clean),('installed',installed)):
            ram=bytearray(source_ram)
            for address,size in fix.NATIVE_DEPENDENCIES:
                with self.subTest(state=name,dependency=hex(address)):
                    ram[address]^=1
                    with self.assertRaisesRegex(ValueError,'dependency changed'):
                        fix.build_memory(ram)
                    ram[address]^=1
            # Checking our hook word must never hide a changed native delay slot.
            for hook,_,_ in fix.HOOKS:
                with self.subTest(state=name,delay_slot=hex(hook+4)):
                    ram[hook+4]^=1
                    with self.assertRaisesRegex(ValueError,'dependency changed'):
                        fix.build_memory(ram)
                    ram[hook+4]^=1
            self.assertEqual(ram,source_ram)

    def test_installed_native_validation_preserves_live_telemetry_and_owned_hooks(self):
        from camera_snapshot import read_ram
        import patch_state
        source=fix.ROOT/'analysis/prepared-states/20260916-162641-89c35bb7/17-playable-team.p2s'
        clean=read_ram(source)
        ram=bytearray(patch_state.patch_memory(clean,fix.build_memory(clean))[0])
        for offset in (12,16,20,24,28,60,64):
            struct.pack_into('<I',ram,fix.CONTROL+offset,123)
        ram[fix.ROW:fix.ROW+0x80]=bytes(range(0x80))
        before=bytes(ram)
        self.assertEqual(fix.build_memory(ram)['blocks'],[])
        self.assertEqual(ram,before)
        for hook,_,old in fix.HOOKS:
            with self.subTest(hook=hex(hook)):
                original=ram[hook:hook+4]
                struct.pack_into('<I',ram,hook,(3<<26)|(old>>2))
                with self.assertRaisesRegex(ValueError,'Stage reset code changed'):
                    fix.build_memory(ram)
                ram[hook:hook+4]=original


if __name__=='__main__':unittest.main()
