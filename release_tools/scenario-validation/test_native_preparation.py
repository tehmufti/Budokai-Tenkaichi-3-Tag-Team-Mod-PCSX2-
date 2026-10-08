"""Execute packet validation/commit and the real dispatch gate instruction stream."""
import struct
import unittest
from test_extra_special_pools import Cpu
import native_preparation as n


def machine():
    c=Cpu({'segments':[dict(address=p,data_hex=d.hex()) for p,d in n.code_pieces()]})
    c.w(n.CONTROL,n.MAGIC);c.w(n.CONTROL+16,1);c.w(n.CONTROL+20,1)
    c.w(n.CONTROL+24,0x1800000);c.w(0x2FEB14,0x1800000);c.w(0x3337C0,1)
    c.callbacks[n.NATIVE]=lambda m:None
    return c


def queue(c,blocks):
    packet,count=n.encode({'blocks':[dict(address=p,expected_hex=old.hex(),data_hex=new.hex()) for p,old,new in blocks]})
    c.write(n.PACKET,packet);c.w(n.CONTROL+28,count);c.w(n.CONTROL+32,len(packet));c.w(n.CONTROL+4,1)


class PreparationTests(unittest.TestCase):
    def test_disarmed_gate_preserves_native_intro_and_team_match(self):
        for phase in (1,2,3):
            c=machine();c.read_u32=c.u;c.write_u32=c.w
            c.w(n.CONTROL+16,0);c.w(n.CONTROL+20,0);c.w(n.CONTROL+48,1);c.w(n.INCLUDE_SINGLE_FFA,1)
            obj,actor,manager=0x1801000,0x1900000,0x1800000
            c.w(0x2FEB38,obj);c.w(obj+260,0x2C6070);c.w(obj,phase)
            c.w(manager,2);c.w(manager+4,actor);c.w(manager+16,1)
            for side in range(2):
                c.w(0x331DC8+192+624*side,3)
                c.w(actor+0x1600*side+0x998,3);c.w(actor+0x1600*side+0x9E4,40000)
            self.assertTrue(n.disarm(c));self.assertTrue(n.disarm(c))
            c.run(n.GATE)
            for address in (obj+8,n.CONTROL+16,n.CONTROL+20,n.CONTROL+48,n.CONTROL+52,n.CONTROL+56,n.INCLUDE_SINGLE_FFA):
                self.assertEqual(c.u(address),0)

    def test_disarm_cannot_release_a_transaction_or_modify_unknown_control(self):
        c=machine();c.read_u32=c.u;c.write_u32=c.w
        c.w(n.CONTROL+48,1);c.w(n.INCLUDE_SINGLE_FFA,1);c.w(n.CONTROL+4,7)
        self.assertTrue(n.disarm(c))
        self.assertEqual([c.u(n.CONTROL+i)for i in (4,16,20,24)],[7,1,1,0x1800000])
        c.w(n.CONTROL,0);c.w(n.CONTROL+48,1);before=c.read(n.CONTROL,64)
        self.assertFalse(n.disarm(c));self.assertEqual(c.read(n.CONTROL,64),before)

    def test_reload_runner_is_called_only_inside_acknowledged_quiet(self):
        import extra_reload_quiet as reload_job
        for quiet in (False,True):
            for installed in (False,True):
                c=machine();events=[]
                c.w(n.CONTROL+16,int(quiet))
                c.w(reload_job.CONTROL,reload_job.MAGIC if installed else 0)
                c.callbacks[reload_job.ENTRY]=lambda m:events.append(m.u(n.CONTROL+20))
                c.r[31]=0xFEED0000
                if quiet:c.callbacks[0xFEED0018]=lambda m:m.r.__setitem__(31,0xFEED0000)
                c.run(n.GATE)
                self.assertEqual(events,[1] if quiet and installed else [])

    def test_background_reload_runner_is_called_on_both_gate_paths_only_when_installed(self):
        """The gate runs in menus, movies and the title screen too, so an older
        prepared match (zeros at BG_CONTROL) must never jump into the cave."""
        import extra_reload_quiet as reload_job
        for held in (False,True):
            for installed in (False,True):
                c=machine();events=[]
                c.w(n.CONTROL+16,int(held))
                c.w(reload_job.CONTROL,reload_job.MAGIC)
                c.w(reload_job.BG_CONTROL,reload_job.BG_MAGIC if installed else 0)
                c.callbacks[reload_job.ENTRY]=lambda m:events.append('runner')
                c.callbacks[reload_job.BACKGROUND]=lambda m:events.append('background')
                c.r[31]=0xFEED0000
                if held:c.callbacks[0xFEED0018]=lambda m:m.r.__setitem__(31,0xFEED0000)
                c.run(n.GATE)
                with self.subTest(held=held,installed=installed):
                    self.assertEqual(events,(['runner'] if held else [])+(['background'] if installed else []))

    def test_the_background_call_preserves_the_native_return_and_every_saved_register(self):
        import extra_reload_quiet as reload_job
        for held in (False,True):
            c=machine();c.w(n.CONTROL+16,int(held))
            c.w(reload_job.CONTROL,0);c.w(reload_job.BG_CONTROL,reload_job.BG_MAGIC)
            c.callbacks[n.NATIVE]=lambda m:m.r.__setitem__(2,0x4321)
            def clobber(m):
                for register in n.REGS:
                    if register!=31:m.r[register]=0xDEADBEEF
            c.callbacks[reload_job.BACKGROUND]=clobber
            c.r[31]=0xFEED0000;before=c.r.copy()
            if held:c.callbacks[0xFEED0018]=lambda m:m.r.__setitem__(31,0xFEED0000)
            c.run(n.GATE)
            with self.subTest(held=held):
                self.assertEqual(c.r[2],1 if held else 0x4321)
                self.assertEqual(c.r[29],before[29])
                for register in n.REGS:
                    if register not in (2,31):
                        self.assertEqual(c.r[register],before[register],register)

    def test_the_gate_still_fits_its_reservation(self):
        import battle_mode_policy as policy
        for capacity in (policy.TEAM_CAPACITY,policy.LEGACY_TEAM_CAPACITY):
            with policy.building_for(capacity):
                self.assertLess(len(n.gate_code()),0x2000)

    def test_all_guards_precede_any_write_and_unaligned_tails_are_supported(self):
        for broken in (False,True):
            c=machine();c.write(0x123456,b'abcdef');c.write(0x2000000,b'01234567')
            queue(c,[(0x123456,b'abcdef',b'ABCDEF'),(0x2000000,b'01234567',b'76543210')])
            if broken:c.write(0x2000007,b'!')
            saved=c.r.copy();c.run(n.CODE)
            self.assertEqual(c.r,saved);self.assertEqual(c.u(n.CONTROL+8),1)
            self.assertEqual(c.u(n.CONTROL+12),100 if broken else 1)
            self.assertEqual(c.read(0x123456,6),b'abcdef' if broken else b'ABCDEF')
            self.assertEqual(c.read(0x2000000,8),b'0123456!' if broken else b'76543210')

    def test_scope_hold_range_and_packet_bounds_fail_closed(self):
        for mutation in ('manager','quiet','packet','self','hook','zero','wrap','end','offset'):
            c=machine();c.write(0x2000000,b'1234');queue(c,[(0x2000000,b'1234',b'abcd')])
            if mutation=='manager':c.w(n.CONTROL+24,0)
            elif mutation=='quiet':c.w(n.CONTROL+16,0)
            elif mutation=='packet':c.w(n.CONTROL+32,n.CAPACITY+1)
            elif mutation=='self':c.w(n.PACKET,n.CODE)
            elif mutation=='hook':c.w(n.PACKET,n.HOOK)
            elif mutation=='zero':c.w(n.PACKET+4,0)
            elif mutation=='wrap':c.w(n.PACKET,0xFFFFFFFC)
            elif mutation=='end':c.w(n.PACKET,0x7FFFFFF)
            elif mutation=='offset':c.w(n.PACKET+8,0)
            c.run(n.CODE);self.assertGreaterEqual(c.u(n.CONTROL+12),100,mutation)
            self.assertEqual(c.read(0x2000000,4),b'1234')

    def test_no_commit_until_quiet_ack_then_once_only(self):
        c=machine();c.write(0x2000000,b'1234');queue(c,[(0x2000000,b'1234',b'abcd')])
        c.w(n.CONTROL+20,0);c.run(n.CODE);self.assertEqual(c.u(n.CONTROL+8),0)
        c.w(n.CONTROL+20,1);c.run(n.CODE);self.assertEqual(c.u(n.CONTROL+8),1)
        c.run(n.CODE);self.assertEqual(c.u(n.CONTROL+12),1)

    def test_gate_holds_only_dispatch_calls_and_preserves_native_return_values(self):
        # A held frame only requests one full surface while the mod's loading
        # cover owns the screen; otherwise it reports split so both viewports
        # keep being drawn. Unheld frames still return the predecessor's value.
        import guest_loading_screen as cover
        for held in (False,True):
            for covered in (False,True):
                c=machine();c.w(n.CONTROL+16,int(held));c.r[31]=0xFEED0000
                # No co-op fusion is installed in this fixture.
                if covered:c.w(cover.CONTROL,cover.MAGIC)
                c.callbacks[n.NATIVE]=lambda m:m.r.__setitem__(2,0x4321)
                # Mips runner stops at its configured return, including adjusted RA.
                if held:c.callbacks[0xFEED0018]=lambda m:m.r.__setitem__(31,0xFEED0000)
                c.run(n.GATE)
                with self.subTest(held=held,covered=covered):
                    self.assertEqual(c.r[2],0 if held and covered else (1 if held else 0x4321))
                    self.assertEqual(c.u(n.CONTROL+20),int(held))

    def test_actual_main_loop_skips_mutators_and_keeps_split_unless_the_cover_is_armed(self):
        native=n.elf_reader(n.ROOT/'analysis/SLUS_216.78')[2]
        import guest_loading_screen as cover
        # Execute the real post-IO battle call/branch sequence. Both native AI
        # and an installed private-AI callsite must be skipped without edits.
        # A held frame collapses to one full surface only under the loading
        # cover; an in-combat hold keeps both split viewports (and the divider).
        for held in (False,True):
            for split in (False,True):
                for covered,fused in ((False,False),(True,False),(False,True)):
                    for ai in (0x1BB620,0x07330000):
                        c=machine();c.w(n.CONTROL+16,int(held));events=[]
                        if covered:c.w(cover.CONTROL,cover.MAGIC)
                        if fused:
                            import battle_mode_policy as modes
                            c.write(modes.CONTROL,struct.pack('<7I',modes.MAGIC,c.u(0x2FEB14),6,
                                                              modes.COOP,2,63,0))
                        c.write(0x12BC84,native(0x12BC84,0x12BCE0-0x12BC84))
                        c.w(n.HOOK,(3<<26)|(n.GATE>>2));c.w(0x12BC8C,(3<<26)|(ai>>2))
                        def event(name,value):
                            def called(m):events.append(name);m.r[2]=value
                            return called
                        c.callbacks[n.NATIVE]=event('native_predecessor',0x4321)
                        c.callbacks[ai]=event('ai',0xA101)
                        c.callbacks[0x1C2A28]=event('input',0xA202)
                        c.callbacks[0x12B6E0]=event('movement_damage_models',1)
                        c.callbacks[0x2129B0]=event('scene_query',123)
                        c.callbacks[0x12AB10]=event('split_query',int(split))
                        c.callbacks[0x12B9C0]=event('split_draw',0)
                        c.callbacks[0x12B7F8]=event('single_draw',0)
                        saved_sp=c.r[29];saved_slice=c.read(0x12BC8C,16)
                        self.assertEqual(c.run(0x12BC84,(0x12BCE0,)),0x12BCE0)
                        single=held and covered or (held and fused)
                        expected=['native_predecessor']
                        if not held:expected+=['ai','input','movement_damage_models']
                        expected+=['scene_query','split_query','split_draw' if split and not single else 'single_draw']
                        with self.subTest(held=held,split=split,covered=covered,fused=fused,ai=hex(ai)):
                            self.assertEqual(events,expected)
                            self.assertEqual(c.r[16],0 if single else 1)
                            self.assertEqual(c.r[17],123)
                            self.assertEqual(c.r[29],saved_sp)
                            self.assertEqual(c.read(0x12BC8C,16),saved_slice)
                            # The held frame never edits the native split-mode word.
                            self.assertEqual(c.u(0x331DC8+36),0)

    def test_native_auto_capture_waits_for_initialized_rosters_and_defers_intro(self):
        c=machine();c.w(n.CONTROL+16,0);c.w(n.CONTROL+20,0);c.w(n.CONTROL+48,1)
        obj,actor,manager=0x1801000,0x1900000,0x1800000
        c.w(0x2FEB38,obj);c.w(obj+260,0x2C6070);c.w(obj,1)
        c.w(0x331DC8+192,3);c.w(0x331DC8+816,3)
        c.run(n.GATE);self.assertEqual(c.u(obj+8),4);self.assertEqual(c.u(n.CONTROL+56),1)
        c.w(obj,2);c.w(manager,2);c.w(manager+4,actor)
        for off in (0,0x1600):c.w(actor+off+0x998,3);c.w(actor+off+0x9E4,40000)
        c.run(n.GATE);self.assertEqual(c.u(n.CONTROL+52),0)
        c.w(manager+16,1);c.callbacks[0xFEED0018]=lambda m:m.r.__setitem__(31,0xFEED0000)
        c.run(n.GATE);self.assertEqual(c.u(n.CONTROL+52),1);self.assertEqual(c.u(n.CONTROL+20),1)

    def test_auto_capture_all_supported_uneven_counts_and_native_one_vs_one(self):
        for left in range(1,4):
            for right in range(1,4):
                c=machine();c.w(n.CONTROL+16,0);c.w(n.CONTROL+20,0);c.w(n.CONTROL+48,1)
                obj,actor,manager=0x1801000,0x1900000,0x1800000
                c.w(0x2FEB38,obj);c.w(obj+260,0x2C6070);c.w(obj,2)
                c.w(manager,2);c.w(manager+4,actor);c.w(manager+16,1)
                for side,count in enumerate((left,right)):
                    c.w(0x331DC8+192+624*side,count)
                    c.w(actor+0x1600*side+0x998,count);c.w(actor+0x1600*side+0x9E4,40000)
                c.callbacks[0xFEED0018]=lambda m:m.r.__setitem__(31,0xFEED0000)
                c.run(n.GATE)
                self.assertEqual(c.u(n.CONTROL+52),int(max(left,right)>1),(left,right))
                self.assertEqual(c.u(n.CONTROL+20),int(max(left,right)>1),(left,right))

    def test_auto_capture_rejects_wrong_scene_roster_phase_identity_and_incomplete_leaders(self):
        for change in ('scene','training','core_active','mismatched_menu','short_menu','callback','phase',
                       'manager_count','uninitialized','unaligned','selected_slot','unequal_actor_rosters','dead','negative_hp'):
            c=machine();c.w(n.CONTROL+16,0);c.w(n.CONTROL+20,0);c.w(n.CONTROL+48,1)
            obj,actor,manager=0x1801000,0x1900000,0x1800000
            c.w(0x2FEB38,obj);c.w(obj+260,0x2C6070);c.w(obj,2)
            c.w(0x331DC8+192,3);c.w(0x331DC8+816,3)
            c.w(manager,2);c.w(manager+4,actor);c.w(manager+16,1)
            for off in (0,0x1600):c.w(actor+off+0x998,3);c.w(actor+off+0x9E4,40000)
            if change=='scene':c.w(0x3337C0,0)
            elif change=='training':c.w(0x331DD0,1)
            elif change=='core_active':c.w(0xD8080,1)
            elif change=='mismatched_menu':c.w(0x331DC8+816,2)
            elif change=='short_menu':c.w(0x331DC8+192,1);c.w(0x331DC8+816,1)
            elif change=='callback':c.w(obj+260,0)
            elif change=='phase':c.w(obj,4)
            elif change=='manager_count':c.w(manager,4)
            elif change=='uninitialized':c.w(manager+16,0)
            elif change=='unaligned':c.w(manager+4,actor+4)
            elif change=='selected_slot':c.w(actor+0x1600+0x994,1)
            elif change=='unequal_actor_rosters':c.w(actor+0x1600+0x998,2)
            elif change=='dead':c.w(actor+0x1600+0x9E4,0)
            else:c.w(actor+0x9E4,0xFFFFFFFF)
            c.run(n.GATE)
            self.assertEqual(c.u(n.CONTROL+52),0,change)
            self.assertEqual(c.u(n.CONTROL+20),0,change)

    def test_single_ffa_explicit_opt_in_defers_intro_and_captures_both_real_rosters(self):
        for opt_in in (0,1,2,0xFFFFFFFF):
            c=machine();c.w(n.CONTROL+16,0);c.w(n.CONTROL+20,0);c.w(n.CONTROL+48,1)
            c.w(n.INCLUDE_SINGLE_FFA,opt_in)
            obj,actor,manager=0x1801000,0x1900000,0x1800000
            c.w(0x2FEB38,obj);c.w(obj+260,0x2C6070);c.w(obj,1)
            c.w(0x331DC8+192,1);c.w(0x331DC8+816,1)
            c.run(n.GATE)
            self.assertEqual(c.u(obj+8),4 if opt_in==1 else 0)
            self.assertEqual(c.u(n.CONTROL+56),int(opt_in==1))
            c.w(obj,2);c.w(manager,2);c.w(manager+4,actor);c.w(manager+16,1)
            for off in (0,0x1600):c.w(actor+off+0x998,1);c.w(actor+off+0x9E4,40000)
            c.callbacks[0xFEED0018]=lambda m:m.r.__setitem__(31,0xFEED0000)
            c.run(n.GATE)
            self.assertEqual(c.u(n.CONTROL+52),int(opt_in==1))
            self.assertEqual(c.u(n.CONTROL+20),int(opt_in==1))

    def test_hook_word_is_the_installed_hook_piece(self):
        # Pollers compare HOOK_WORD instead of rebuilding every code piece.
        self.assertEqual(n.code_pieces()[-1],(n.HOOK,n.HOOK_WORD))
        self.assertEqual(struct.unpack('<I',n.HOOK_WORD)[0],(3<<26)|(n.GATE>>2))


class Phase1RaceTests(unittest.TestCase):
    """beta.37 (HTC 0 % cover): the gate heals any phase-1 substate but 4, in the frame it appears, against the real
    native update A (217410) / transition (217520) bytes of this build's executable."""
    OBJ=0x1801000

    def gated(self,substate,armed=1,captured=0,heal=True):
        c=Cpu({'segments':[dict(address=n.GATE,data_hex=n.gate_code(heal_any_substate=heal).hex())]})
        c.callbacks[n.NATIVE]=lambda m:None
        c.w(n.CONTROL,n.MAGIC);c.w(n.CONTROL+48,armed);c.w(n.CONTROL+52,captured);c.w(n.A(0x3337C0),1)
        c.w(n.A(0x2FEB38),self.OBJ);c.w(self.OBJ+260,n.A(0x2C6070));c.w(self.OBJ,1);c.w(self.OBJ+8,substate)
        c.w(n.A(0x331DC8)+192,2);c.w(n.A(0x331DC8)+816,2)
        c.run(n.GATE)
        return c

    def test_every_substate_but_four_becomes_four_and_requests_the_intro(self):
        for substate in (0,1,2,3,5,6,7,50,98,0xFFFFFFFF):
            c=self.gated(substate)
            self.assertEqual((c.u(self.OBJ+8),c.u(n.CONTROL+56)),(4,1),substate)
        c=self.gated(4)
        self.assertEqual((c.u(self.OBJ+8),c.u(n.CONTROL+56)),(4,0))

    def test_disarmed_or_captured_phase_one_is_untouched(self):
        for armed,captured in ((0,0),(1,1)):
            for substate in (0,5):
                self.assertEqual(self.gated(substate,armed,captured).u(self.OBJ+8),substate)

    def test_previous_image_differs_in_exactly_the_phase_one_compare(self):
        old,new=n.previous_gate_images()[0],n.gate_code()
        self.assertEqual(len(old),len(new))
        diff=[i for i in range(0,len(new),4) if old[i:i+4]!=new[i:i+4]]
        self.assertEqual(len(diff),1)
        i=diff[0]
        self.assertEqual(struct.unpack_from('<3I',old,i-4)[:2],(0x8E280008,0x2D090004))   # lw t0,8(s1); sltiu t1,t0,4
        self.assertEqual(struct.unpack_from('<3I',new,i-4)[:2],(0x8E280008,0x39090004))   # lw t0,8(s1); xori t1,t0,4
        self.assertEqual(struct.unpack_from('<I',new,i+4)[0]>>16,0x1120)                     # beq t1,zero,normal

    def test_native_interplay_raced_write_is_healed_in_the_same_frame(self):
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        native=elf_reader(elf_path(ROOT))[2]
        update_a,update_b=n.A(0x217410),n.A(0x217520)
        span=native(update_a,update_b+0x188-update_a)
        for heal,expected in ((False,(5,1)),(True,(4,2))):
            c=Cpu({'segments':[dict(address=update_a,data_hex=span.hex()),
                               dict(address=n.GATE,data_hex=n.gate_code(heal_any_substate=heal).hex())]})
            calls=[]
            for i in range(0,len(span),4):
                word=struct.unpack_from('<I',span,i)[0]
                if word>>26==3:calls.append((word&0x3FFFFFF)<<2)
            for target in calls:c.callbacks[target]=lambda m:m.r.__setitem__(2,0)
            # The host write lands during update A's first call (actor message): stored 4, then +1.
            c.callbacks[calls[0]]=lambda m:(m.w(self.OBJ+8,4),m.r.__setitem__(2,0))
            c.callbacks[n.NATIVE]=lambda m:None
            c.w(self.OBJ+4,0);c.w(self.OBJ+8,0)
            c.r[4]=self.OBJ+4;c.run(update_a)
            self.assertEqual(c.u(self.OBJ+8),5)
            c.w(n.CONTROL,n.MAGIC);c.w(n.CONTROL+48,1);c.w(n.A(0x3337C0),1)
            c.w(n.A(0x2FEB38),self.OBJ);c.w(self.OBJ+260,n.A(0x2C6070));c.w(self.OBJ,1)
            c.w(n.A(0x331DC8)+192,2);c.w(n.A(0x331DC8)+816,2)
            c.run(n.GATE)
            c.r[4]=self.OBJ+4;c.run(update_b)
            self.assertEqual((c.u(self.OBJ+8),c.r[2]),expected,'fixed' if heal else 'beta.36')

    def test_captured_transport_accepts_current_and_previous_gate_only(self):
        ram=bytearray(0x8000000)
        for p,d in n.code_pieces():ram[p:p+len(d)]=d
        self.assertTrue(n.captured_transport(ram))
        old=n.previous_gate_images()[0];ram[n.GATE:n.GATE+len(old)]=old
        self.assertTrue(n.captured_transport(ram))
        ram[n.GATE+len(old)-1]^=1
        self.assertFalse(n.captured_transport(ram))
        ram[n.GATE+len(old)-1]^=1;ram[n.CODE]^=1
        self.assertFalse(n.captured_transport(ram))

class ShippedGateTests(unittest.TestCase):
    """beta.37 (HTC): captures and presets of beta.35/36 hold the gate those releases shipped. It is frozen per adapter in
    dispatch_gate_history and pinned here; a rebuild from current code stops matching once the gate grows."""
    SHIPPED={'bt3-usa':'13eb79e7869258b96c4e24c68bb8537abf1176b9425a020ceed6ff3a2dec8df9',
             'bt3-pal':'a593733756e3da6a2746bd7fb60d7079179cf653b5c0bb208126f7d80530b1d2',
             'bt3-jpn':'a7580913d466a5dff6dd67d49e26e97ce777016df21783562d5f7f5d40b5a2bc'}

    def test_one_accepted_image_is_the_gate_beta36_shipped_for_this_adapter(self):
        import hashlib
        import native_map
        import dispatch_gate_history as history
        shas=[hashlib.sha256(image).hexdigest() for image in n.previous_gate_images()]
        self.assertIn(self.SHIPPED[native_map.ADAPTER],shas)
        self.assertEqual(len(shas),len(set(shas)))
        self.assertEqual(history.SHA256,self.SHIPPED)
        for adapter in self.SHIPPED:
            image=history.beta36_image(adapter)
            # lw t0,8(s1); sltiu t1,t0,4 at GATE+0x21C: the beta.35/36 phase-1 rewrite
            self.assertEqual((len(image),image[0x21C:0x224]),(0x668,struct.pack('<2I',0x8E280008,0x2D090004)))
        self.assertIsNone(history.beta36_image('bt4-b14-rev2-eng'))

    def test_shipped_image_is_still_accepted_after_the_gate_grows(self):
        # Merged with a longer gate (another change adds a path), gate_code(heal_any_substate=False) is no longer
        # what beta.36 shipped; the frozen image still is, and a capture holding it plus zeros stays a transport.
        import native_map
        import dispatch_gate_history as history
        from unittest.mock import patch
        shipped=history.beta36_image(native_map.ADAPTER)
        real=n.gate_code
        grown=lambda heal_any_substate=True:real(heal_any_substate)+struct.pack('<4I',0,0,0,0x03E00008)
        with patch.object(n,'gate_code',grown):
            images=n.previous_gate_images()
            self.assertEqual(len(images),2);self.assertEqual(images[1],shipped)
            ram=bytearray(0x8000000)
            for p,d in n.code_pieces():ram[p:p+len(d)]=d
            self.assertTrue(n.captured_transport(ram))
            current=grown()
            ram[n.GATE:n.GATE+len(current)]=shipped+bytes(len(current)-len(shipped))
            self.assertTrue(n.captured_transport(ram))
            ram[n.GATE+0x220]^=0x10
            self.assertFalse(n.captured_transport(ram))


REGION_SCRIPT = r'''
import hashlib, json, struct, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import prototype
prototype.ROOT = Path(sys.argv[2])
import native_map
import native_preparation as n
gate = n.gate_code()
print(json.dumps(dict(adapter=native_map.ADAPTER, length=len(gate), words=struct.unpack_from('<3I', gate, 0x21C),
                      previous=[[struct.unpack_from('<I', image, 0x220)[0], hashlib.sha256(image).hexdigest()]
                                for image in n.previous_gate_images()])))
'''


class RegionalGateTests(unittest.TestCase):
    def test_european_and_japanese_gates_heal_with_xori_at_the_same_offset(self):
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path
        here=Path(n.__file__).resolve().parent
        import shutil
        import tempfile
        for adapter,table,variable,serial in (('bt3-pal','pal_native_map.json','TAGTEAM_PAL_ELF','SLES_549.45'),
                                              ('bt3-jpn','jpn_native_map.json','TAGTEAM_JPN_ELF','SLPS_258.15')):
            with self.subTest(adapter=adapter):
                if not (here/table).is_file():self.skipTest(f'{table} is not part of this tree')
                # The gate inlines story_cinematics, whose imports read the region's executable (as in
                # test_lockon_threat's regional builds: a temporary analysis/ folder, prototype.ROOT on it).
                elf=os.environ.get(variable)
                if not elf or not Path(elf).is_file():self.skipTest(f'Set {variable} to the {serial} executable')
                with tempfile.TemporaryDirectory() as root:
                    (Path(root)/'analysis').mkdir();shutil.copyfile(elf,Path(root)/'analysis'/serial)
                    run=subprocess.run([sys.executable,'-B','-c',REGION_SCRIPT,str(here),root],capture_output=True,text=True,
                                       timeout=300,env=dict(os.environ,TAGTEAM_ADAPTER=adapter))
                self.assertEqual(run.returncode,0,run.stdout[-2000:]+run.stderr[-4000:])
                out=json.loads(run.stdout.strip().splitlines()[-1])
                self.assertEqual(out['adapter'],adapter)
                self.assertEqual(out['length'],len(n.gate_code()))
                self.assertEqual(out['words'][:2],[0x8E280008,0x39090004])     # lw t0,8(s1); xori t1,t0,4
                self.assertEqual(out['words'][2]>>16,0x1120)                      # beq t1,zero,normal
                self.assertIn([0x2D090004,ShippedGateTests.SHIPPED[adapter]],out['previous'])


if __name__=='__main__':unittest.main()
