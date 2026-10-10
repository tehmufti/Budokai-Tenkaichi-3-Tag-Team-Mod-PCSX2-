import support
"""Exercise native counter acceptance/dispatch and both actual melee clashes."""
import struct
import unittest
import vanish_pair_guard as fix
import counter_contact_fixture as contact
import counter_body_fixture as body
import counter_dash_fixture as dash
import battle_mode_policy as policy
_scope=None
def setUpModule():
    global _scope
    _scope=policy.building_for(policy.LEGACY_TEAM_CAPACITY);_scope.__enter__()
def tearDownModule():_scope.__exit__(None,None,None)

ACTORS, MODELS, MANAGER = contact.ACTORS, contact.MODELS, contact.MANAGER
call, flag = contact.call, contact.flag


def machine(guard=True):
    c=body.machine()
    # BT4 redirects several vanilla routines into its own overlay. Execute
    # that code too; running its ELF alone loops through empty guest memory.
    addon=support.ADDON
    if addon.is_file():c.write(0x334C00,addon.read_bytes())
    c.write(fix.BODY_SITE,fix.NATIVE(fix.BODY_SITE,8))
    if guard:
        for p,b in fix.pieces():c.write(p,b)
    return c


def captured_ram():
    """Canonical installed clash/contact chain with native disc code intact."""
    from prototype import elf_reader
    from native_map import elf_path
    ram=bytearray(0x8000000);blob,segments,_=elf_reader(support.ELF)
    for address,offset,size,_ in segments:ram[address:address+size]=blob[offset:offset+size]
    c=machine(False)
    for p,b in fix.dash.pieces():c.write(p,b)
    for p,b in fix.multi.pieces():c.write(p,b)
    for p,b in body.fix.pieces():c.write(p,b)
    for p,value in c.memory.items():ram[p]=value
    return bytes(ram)


def native_counter(c, defender=3):
    # Execute the real 1C8580 response routine and 1C97C0 hit evaluation.
    # Character/input metadata is isolated; native counter flags are not.
    c.write(0x1C8580,fix.NATIVE(0x1C8580,0x440));c.callbacks.pop(0x1C8580,None)
    c.callbacks[0x1DC2D0]=lambda m:m.r.__setitem__(2,1)
    c.callbacks[0x1C4638]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x1C4650]=lambda m:m.r.__setitem__(2,0xB1)
    c.callbacks[0x1CF0C8]=lambda m:m.r.__setitem__(2,0)
    c.w(ACTORS[defender]+3588,1)  # one native counter response charge
    contact.geometry_pairs(c,{(0,defender)});call(c,0x1AF740)
    call(c,fix.multi.GATHER,ACTORS[0])


class VanishPairTests(unittest.TestCase):
    def test_native_counter_reproduces_old_target_and_keeps_real_attacker_with_guard(self):
        for old_target in (2,4):
            for old_dead in (False,True):
                for guard in (False,True):
                    c=machine(guard);c.w(fix.core.TABLE+12,old_target)
                    if old_dead:c.w(ACTORS[old_target]+0x9E4,0)
                    native_counter(c)
                    self.assertTrue(dash.has_flag(c,3,0x77))
                    self.assertEqual(c.u(ACTORS[3]+3588),0)
                    # Dispatch the real queued counter into animation121.
                    c.write(0x1E12D0,fix.NATIVE(0x1E12D0,0x1100))
                    c.callbacks[0x1DC480]=lambda m:m.r.__setitem__(2,0)
                    c.callbacks[0x202DB8]=lambda m:m.w(m.r[4]+2388,m.r[5])
                    c.callbacks[0x1E0370]=lambda m:m.r.__setitem__(2,m.u(m.r[4]+2388))
                    c.callbacks[0x1E0290]=lambda m:m.w(m.r[4]+2380,m.r[5])
                    c.callbacks[0x204200]=lambda m:m.r.__setitem__(2,0)
                    call(c,0x1E12D0,ACTORS[3])
                    self.assertEqual(c.u(ACTORS[3]+2380),121)
                    call(c,0x1DB770,ACTORS[3])
                    self.assertEqual(c.r[2],0 if guard else old_target,(old_target,old_dead,guard))
                    self.assertEqual(c.u(fix.multi.CONTEXT),0)

    def test_binding_survives_retargeting_only_during_response_and_does_not_override_contact(self):
        c=machine();native_counter(c);flag(c,3,0x77,False);c.w(ACTORS[3]+2376,121)
        c.w(fix.core.TABLE+12,4)
        call(c,fix.core.RESOLVER,ACTORS[3]);self.assertEqual((c.r[2],c.r[3]),(ACTORS[0],0))
        c.write(fix.multi.CONTEXT,struct.pack('<5I',1,4,3,ACTORS[4],ACTORS[3]))
        call(c,fix.core.RESOLVER,ACTORS[3]);self.assertEqual(c.r[3],4)
        c.w(fix.multi.CONTEXT,0);c.w(ACTORS[3]+2376,11)
        for off in (2380,2388):c.w(ACTORS[3]+off,0xFFFFFFFF)
        call(c,fix.core.RESOLVER,ACTORS[3]);self.assertEqual(c.r[3],4)
        self.assertEqual(c.u(fix.ROWS+3*fix.STRIDE),0)

    def test_ordinary_hits_and_preexisting_counter_flags_never_steal_a_response(self):
        for preexisting in (False,True):
            c=machine();before=c.read(fix.core.TABLE,24)
            if preexisting:flag(c,3,0x77)
            contact.geometry_pairs(c,{(0,3)});call(c,0x1AF740)
            call(c,fix.multi.GATHER,ACTORS[0])
            self.assertEqual(c.read(fix.core.TABLE,24),before)
            self.assertEqual(c.u(fix.CAPTURED),0)

    def test_new_sonic_sway_binds_both_sides_without_changing_ordinary_bystanders(self):
        c=machine()
        def sway(m):
            flag(m,3,0x7D);flag(m,0,0x7E);m.r[2]=1
        c.callbacks[0x1C8580]=sway;before=c.read(fix.core.TABLE,24)
        contact.geometry_pairs(c,{(0,3)});call(c,0x1AF740);call(c,fix.multi.GATHER,ACTORS[0])
        self.assertEqual(c.u(fix.ROWS),ACTORS[3]);self.assertEqual(c.u(fix.ROWS+3*fix.STRIDE),ACTORS[0])
        for i in (1,2,4,5):self.assertEqual(c.u(fix.core.TABLE+4*i),struct.unpack_from('<I',before,4*i)[0])

    def test_counter_binding_clears_on_ko_removal_consumption_reload_timeout_and_authored_moves(self):
        for cause in ('dead','absent','consumed','model','resource','clock','rush','transform'):
            c=machine();native_counter(c);c.w(fix.core.TABLE+12,4)
            if cause=='dead':c.w(ACTORS[0]+0x9E4,0)
            elif cause=='absent':c.w(fix.multi.participation.PRESENT,62)
            elif cause=='consumed':c.w(fix.multi.participation.CONTROL+16,1)
            elif cause=='model':c.w(MODELS[0]+20,c.u(MODELS[0]+20)+1)
            elif cause=='resource':c.w(MODELS[3]+5728,c.u(MODELS[3]+5728)+4)
            elif cause=='clock':c.w(fix.CLOCK,fix.MAX_AGE)
            elif cause=='rush':c.w(ACTORS[3]+2380,301)
            elif cause=='transform':c.w(ACTORS[3]+2380,236)
            call(c,fix.core.RESOLVER,ACTORS[3]);self.assertEqual(c.r[3],4,cause)
            self.assertEqual(c.u(fix.ROWS+3*fix.STRIDE),0,cause)

    def test_ffa_counter_to_same_parity_and_private_alias_safety(self):
        c=machine();p=fix.policy;c.write(p.CONTROL,struct.pack('<4I',p.MAGIC,MANAGER,6,p.FFA))
        flag(c,4,0x77);call(c,fix.CAPTURE,ACTORS[4],ACTORS[0])
        call(c,fix.core.RESOLVER,ACTORS[4]);self.assertEqual(c.r[3],0)
        # Temporary AI aliases are not durable physical rows.
        c.w(ACTORS[4],0);call(c,fix.CAPTURE,ACTORS[4],ACTORS[3])
        self.assertEqual(c.u(fix.ROWS+4*fix.STRIDE),ACTORS[0])

    def test_body_counter_rejects_third_party_contact_and_dead_defender(self):
        for cause in ('other','dead','absent','resource'):
            c=machine();body.observe(c,0,3 if cause!='other' else 1)
            if cause=='dead':c.w(ACTORS[3]+0x9E4,0)
            elif cause=='absent':c.w(fix.multi.participation.PRESENT,63^(1<<3))
            elif cause=='resource':c.w(MODELS[3]+5728,c.u(MODELS[3]+5728)+4)
            c.r[17]=ACTORS[0];c.r[16]=ACTORS[3]
            self.assertEqual(call(c,fix.BODY,ACTORS[0]),0,cause)
        c=machine();body.observe(c,0,3);c.r[17]=ACTORS[0];c.r[16]=ACTORS[3]
        self.assertEqual(call(c,fix.BODY,ACTORS[0]),1)

    def test_native_body_counter_loop_cannot_borrow_contact_from_original_opponent(self):
        for guard in (False,True):
            c=machine(guard);body.observe(c,0,1);c.w(fix.core.TABLE,3)
            c.write(0x1C9258,fix.NATIVE(0x1C9258,0x4A0))
            if guard:c.write(fix.BODY_SITE,fix.CALL(fix.BODY))
            flag(c,0,0x49)
            c.r[31]=0xFEED0000;stopped=c.run(0x1C9258,(0x1C92D4,0x1C96E4))
            self.assertEqual(stopped,0x1C96E4 if guard else 0x1C92D4)

    def test_running_250_and_252_release_on_ko_or_removal_without_touching_bystanders(self):
        for kind in (250,251):
            for cause in ('dead','absent','consumed'):
                c=machine();body.observe(c,0,3);body.propose(c,0,3,kind)
                for i in (0,3):c.w(ACTORS[i]+2376,kind)
                call(c,0x1D9900);self.assertEqual(c.u(fix.dash.ACTIVE),2)
                if kind==251:
                    for i in (0,3):c.w(ACTORS[i]+2376,252)
                if cause=='dead':c.w(ACTORS[3]+0x9E4,0)
                elif cause=='absent':c.w(fix.multi.participation.PRESENT,63^(1<<3))
                else:c.w(fix.multi.participation.CONTROL+16,1<<3)
                call(c,0x1D9900);self.assertEqual(c.u(fix.dash.ACTIVE),0,(kind,cause))
                self.assertEqual(c.u(MANAGER+64),0)
                for i in (1,2,4,5):self.assertFalse(dash.has_flag(c,i,0xBF) or dash.has_flag(c,i,0xC6))

    def test_native_output_registers_and_stack_survive_counter_observation(self):
        c=machine();c.w(fix.core.TABLE,3);sp=c.r[29]
        returned={r:0xA000+r for r in range(2,28)}
        def native(m):
            flag(m,3,0x77)
            for r,value in returned.items():m.r[r]=value
        c.callbacks[0x1C97C0]=native;call(c,fix.HIT,ACTORS[0])
        self.assertEqual(c.r[29],sp)
        self.assertEqual({r:c.r[r] for r in returned},returned)
        self.assertEqual(c.u(fix.ROWS+3*fix.STRIDE),ACTORS[0])

    def test_full_preset_reconfiguration_and_tamper_checks(self):
        import special_pause
        from patch_state import patch_memory
        ram=captured_ram()
        before=bytes(ram)
        manifest=fix.build_memory(ram)
        installed=patch_memory(ram,manifest)[0] if manifest['blocks'] else ram
        self.assertEqual(bytes(ram),before)
        self.assertEqual(fix.build_memory(installed)['blocks'],[])
        self.assertEqual(fix.multi.prior_manifest(installed,fix.dash.build_memory)['blocks'],[])
        self.assertTrue(special_pause.beam_chain_dependencies(installed,MANAGER,6))
        for p in (fix.HIT,fix.LOOKUP,fix.CONTROL,fix.BODY_SITE-12,fix.BODY_SITE,fix.BODY_SITE+4,fix.multi.GATHER,fix.dash.FRAME):
            bad=bytearray(installed);bad[p]^=1
            with self.assertRaises(ValueError,msg=hex(p)):fix.build_memory(bad)
            with self.assertRaises(ValueError,msg=hex(p)):
                special_pause.beam_chain_dependencies(bad,MANAGER,6)


if __name__=='__main__':unittest.main()
