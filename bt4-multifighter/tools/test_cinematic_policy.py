"""Native generated policy tests; no emulator/PINE/process access."""
import struct
import unittest
import cinematic_policy as p
import test_special_pause as old
import special_camera_arbitration as arbitration
from test_special_camera_arbitration import machine as camera_machine, start as camera_start, ACTORS, MODELS, MIDS
from prototype import elf_reader, ROOT
from legacy_fixtures import setUpModule, tearDownModule  # noqa: F401 - fixtures are three-a-side builds


def apply(ram,manifest):
    for block in manifest['blocks']:
        at=block['address'];data=bytes.fromhex(block['data_hex'])
        if ram[at:at+len(data)].hex()!=block['expected_hex']:raise AssertionError(hex(at))
        ram[at:at+len(data)]=data


def install_cpu(c,ultimate=False,transformation=False):
    for at,data in p.program()+p.hooks():c.write(at,data)
    c.write(p.continuity.LOOKUP,p.continuity.lookup_code())
    c.write(p.CONTROL,struct.pack('<6I',p.MAGIC,c.u(p.core.ACTORS),c.u(p.core.MODE+4),
                                 c.u(p.team_intro.BATTLE),ultimate,transformation))
    return c


class CinematicPolicyTests(unittest.TestCase):
    def test_native_action_classification_all_boundaries(self):
        c=old.cpu()
        c.write(p.CLASSIFY,p.classify())
        for action in range(0,400):
            c.r[4]=action;c.r[31]=0xFEED0000;c.run(p.CLASSIFY)
            expected=(2 if 236<=action<=243 else 1 if action==261 or 262<=action<316 and (action-262)%3==2
                      else 0 if 253<=action<316 else 3)
            self.assertEqual(c.r[2],expected,action)

    def test_unchecked_transform_and_ultimate_ignore_ordinary_pause_selection(self):
        for mode in p.pause.MODES:
            for action in (236,241,243,261,264,288,303,315):
                c=old.cpu(False,6,[2,0,0,0,0,0]);c.w(p.pause.MODE,p.pause.MODES[mode])
                c.w(c.actors[0]+2376,action);install_cpu(c)
                c.run(p.pause.hitstop12.ENTRY)
                self.assertEqual(old.timers(c),[[0,0,0]]*6,(mode,action))
                self.assertEqual(c.u(p.pause.CONTROL+52)&1,1)

    def test_each_checkbox_forces_native_pause_only_for_its_category(self):
        for ultimate,transformation in ((False,False),(True,False),(False,True),(True,True)):
            for action in (241,264):
                c=old.cpu(False,6,[2,0,0,0,0,0]);c.w(p.pause.MODE,2);c.w(c.actors[0]+2376,action)
                install_cpu(c,ultimate,transformation);c.run(p.pause.hitstop12.ENTRY)
                stopped=transformation if action==241 else ultimate
                expected=old.expected_timers([2,0,0,0,0,0],[False]*6,[[0,0,0]]*6) if stopped else [[0,0,0]]*6
                self.assertEqual(old.timers(c),expected,(ultimate,transformation,action))

    def test_ordinary_modes_remain_and_mixed_disabled_transform_does_not_hide_ordinary_pause(self):
        for mode in p.pause.MODES:
            c=old.cpu(False,6,[2,0,0,0,0,0]);c.w(p.pause.MODE,p.pause.MODES[mode]);install_cpu(c)
            c.run(p.pause.hitstop12.ENTRY)
            baseline=old.cpu(False,6,[2,0,0,0,0,0]);baseline.w(p.pause.MODE,p.pause.MODES[mode]);baseline.run(p.pause.hitstop12.ENTRY)
            self.assertEqual(old.timers(c),old.timers(baseline),mode)
        c=old.cpu(False,6,[2,0,2,0,0,0]);c.w(p.pause.MODE,0);c.w(c.actors[2]+2376,241);install_cpu(c)
        c.run(p.pause.hitstop12.ENTRY)
        self.assertEqual(c.u(p.CONTROL+28),3)
        self.assertEqual([x[0] for x in old.timers(c)],[0,1,0,0,0,0])

    def test_impact_and_manager_scene_holds_are_untouched(self):
        for reason in ('impact','manager','scene'):
            c=old.cpu(False,6,[2,0,0,0,0,0]);c.w(c.actors[0]+2376,241);install_cpu(c)
            if reason=='impact':c.w(c.actors[3]+4900,6)
            elif reason=='manager':c.w(c.u(p.core.ACTORS)+628,1)
            else:c.w(p.continuity.SCENE_FLAGS,0x2000)
            c.run(p.pause.hitstop12.ENTRY)
            if reason=='impact':self.assertEqual(c.u(c.actors[3]+4896),6)
            else:self.assertEqual(c.u(p.CONTROL+24),0)

    def test_manifest_is_idempotent_guards_every_entry_and_remains_pause_configurable(self):
        ram=bytearray(old.RAM);apply(ram,p.pause.build_memory(ram,mode='none'))
        apply(ram,p.build_memory(ram));self.assertEqual(p.build_memory(ram)['blocks'],[])
        self.assertEqual(p.pause.configure_memory(ram,mode='none')['blocks'],[])
        apply(ram,p.build_memory(ram,ultimate=True));self.assertEqual(struct.unpack_from('<2I',ram,p.CONTROL+16),(1,0))
        apply(ram,p.pause.configure_memory(ram,mode='target'))
        p.validate_memory(ram)
        for at in (p.CODE,p.STORE,p.OLD_PREPARE,p.pause.PREPARE,p.leader.HOOK,p.RENDER_CALLS[0]+4):
            ram[at]^=1
            with self.assertRaises(ValueError):p.build_memory(ram)
            with self.assertRaises(ValueError):p.pause.configure_memory(ram,mode='none')
            ram[at]^=1

    def test_exact_previous_camera_emission_upgrades_without_accepting_modified_code(self):
        ram=bytearray(old.RAM);apply(ram,p.pause.build_memory(ram,mode='none'))
        apply(ram,p.build_memory(ram))
        # Reconstruct precisely the pre-fusion/pre-corpse policy (build_memory installed the beta.37
        # participants emission, whose PROTECT/FOREIGN/PENDING no earlier release had).
        current=dict(p.program(participants=True,form_gate=True))
        for address,data in p.program(False):
            ram[address:address+len(current[address])]=bytes(len(current[address]))
            ram[address:address+len(data)]=data
        ram[p.COOP_FUSION:p.COOP_FUSION+len(p.coop_fusion())]=bytes(len(p.coop_fusion()))
        for address in (p.PROTECT,p.FOREIGN,p.PENDING,p.PROTECT_ACTIVE,p.FORM_GATE,p.FORM_TRACK):ram[address:address+len(current[address])]=bytes(len(current[address]))
        p.validate_memory(ram)
        manifest=p.build_memory(ram);self.assertTrue(manifest['blocks'])
        apply(ram,manifest);self.assertEqual(p.build_memory(ram)['blocks'],[])
        ram[p.VIEW+8]^=1
        with self.assertRaises(ValueError):p.build_memory(ram)

    def test_previous_participant_classifier_upgrades_in_single_and_quad_views(self):
        import four_player_mode as quad
        for expanded in (False,True):
            with self.subTest(quad=expanded):
                ram=bytearray(old.RAM);apply(ram,p.pause.build_memory(ram,mode='none'))
                apply(ram,p.build_memory(ram,ultimate=True))
                # The previous classifier shipped before the beta.37 participants emission.
                for address,data in p.program(participants=True,form_gate=True):ram[address:address+len(data)]=bytes(len(data))
                for address,data in p.program():ram[address:address+len(data)]=data
                if expanded:
                    manager,count=struct.unpack_from('<2I',ram,p.CONTROL+4)
                    struct.pack_into('<3I',ram,quad.controllers.CONTROL,quad.controllers.MAGIC,manager,count)
                    struct.pack_into('<4I',ram,quad.views.CONTROL,quad.views.MAGIC,manager,count,1)
                    data=p.selector(quad_support=True);ram[p.CODE:p.CODE+len(data)]=data
                previous=p.ultimate_owner(all_activations=False)
                ram[p.ULTIMATE_OWNER:p.ULTIMATE_OWNER+len(previous)]=previous
                p.validate_memory(ram)
                manifest=p.build_memory(ram,ultimate=True)
                self.assertEqual(sorted(b['address'] for b in manifest['blocks']),
                                 sorted([p.PREPARE,p.ULTIMATE_OWNER,p.ULTIMATE_STOP,p.PROTECT,p.FOREIGN,p.PENDING,p.PROTECT_ACTIVE,
                                         p.STORE,p.SHARED_FORM,p.ULTIMATE_FRAME,p.FORM_GATE,p.FORM_TRACK]))
                apply(ram,manifest)
                self.assertEqual(p.build_memory(ram,ultimate=True)['blocks'],[])
                ram[p.ULTIMATE_OWNER:p.ULTIMATE_OWNER+len(previous)]=previous
                ram[p.ULTIMATE_OWNER+8]^=1
                with self.assertRaises(ValueError):p.validate_memory(ram)

    def camera(self,split=True):
        c=camera_machine(split=split);install_cpu(c);c.calls=[]
        manager=0x1840000;c.w(c.r[28]-22172,manager)
        c.w(c.r[28]-22176,manager+0x720)
        for side in range(2):
            # Three original native viewport templates, distinct footprint.
            c.write(manager+(side+1)*0x260,bytes([side+1])*0x260)
            c.w(manager+(0x720 if side==0 else 0x9B0)+0x284,side)
        c.callbacks[0x12A9E8]=lambda m:m.r.__setitem__(2,0)
        c.callbacks[0x23DBC0]=lambda m:m.r.__setitem__(2,1)
        c.callbacks[p.camera.PARTICIPANT]=lambda m:m.r.__setitem__(2,int(m.r[4]==0))
        def select(m):
            side=m.r[4];body=manager+(0x720 if side==0 else 0x9B0)
            m.w(manager+0xC40,body);m.w(m.r[28]-22176,body);m.calls.append(('select',side))
        c.callbacks[0x23EF98]=select
        c.callbacks[0x23EFD0]=lambda m:m.calls.append(('native_bind',m.r[4],m.u(m.r[28]-22176)))
        c.callbacks[0x23EE78]=lambda m:m.calls.append(('viewport',m.r[4],m.r[5]))
        c.callbacks[0x23E6A0]=lambda m:m.calls.append(('cinematic_bind',m.r[4],m.r[5]))
        c.callbacks[p.camera.CODE]=lambda m:(m.r.__setitem__(2,1),m.r.__setitem__(3,0xABCDEF0000001234))
        return c,manager

    def test_split_selector_always_restores_both_viewports_even_when_native_selected_single(self):
        c,manager=self.camera();before=c.r[4:].copy();c.run(p.CODE)
        self.assertEqual(c.r[2],0);self.assertEqual(c.r[3],0xABCDEF0000001234);self.assertEqual(c.r[4:],before)
        self.assertEqual(c.calls,[('select',0),('viewport',1,0),('select',1),('viewport',1,0),('select',0)])

    def fused_camera(self,fused=0,mode=None,count=6,manager=None):
        c,manager_address=self.camera()
        live=c.u(p.core.ACTORS) if manager is None else manager
        c.write(p.modes.CONTROL,struct.pack('<7I',p.modes.MAGIC,live,count,
                                            p.modes.COOP if mode is None else mode,
                                            2,63,fused&0xFFFFFFFF))
        c.w(p.CONTROL+16,0);c.w(p.CONTROL+20,0)
        return c,manager_address

    def test_a_fused_coop_match_renders_one_full_screen_view(self):
        c,manager=self.fused_camera()
        c.run(p.CODE)
        # One camera pass, the full-screen template, and a nonzero result so
        # the caller takes the single renderer.
        self.assertEqual(c.r[2],1)
        cine=c.u(c.r[28]-22180)
        self.assertEqual(c.calls,[('select',0),('native_bind',1,manager+0x720),('viewport',0,1),
                                  ('cinematic_bind',cine,1)])
        # Without a cinematic to show, the fused view is the ordinary follow
        # camera on the retained leader and nothing is rebound.
        c,manager=self.fused_camera()
        c.callbacks[p.camera.PARTICIPANT]=lambda m:m.r.__setitem__(2,0)
        c.callbacks[0x23DBC0]=lambda m:m.r.__setitem__(2,0)
        c.run(p.CODE)
        self.assertEqual(c.r[2],1)
        self.assertEqual(c.calls,[('select',0),('native_bind',1,manager+0x720),('viewport',0,1)])

    def test_only_a_live_coop_fusion_collapses_the_view(self):
        split=[('select',0),('viewport',1,0),('select',1),('viewport',1,0),('select',0)]
        for name,kwargs in (('unfused',dict(fused=-1)),('teams',dict(mode=p.modes.TEAMS)),
                            ('ffa',dict(mode=p.modes.FFA)),('foreign',dict(manager=0x1234560)),
                            ('out_of_range',dict(fused=6)),('count',dict(count=4))):
            c,_=self.fused_camera(**kwargs);c.run(p.CODE)
            with self.subTest(name=name):
                self.assertEqual(c.r[2],0)
                self.assertEqual(c.calls,split)
        # A stale identity word is refused the same way.
        c,_=self.fused_camera();c.w(p.modes.CONTROL,0);c.run(p.CODE)
        self.assertEqual(c.calls,split)

    def test_a_finished_match_keeps_the_native_result_camera(self):
        c,_=self.fused_camera();c.w(p.result.RESULT,1)
        before=c.r[2];c.run(p.CODE)
        self.assertEqual(c.calls,[])

    def test_single_disabled_activation_camera_restores_follow_but_bound_rush_stays_framed(self):
        for action,enabled,restore in ((241,False,True),(241,True,False),(264,False,True),(264,True,False),(303,False,False)):
            c,_=self.camera(split=False);c.w(ACTORS[0]+2376,action)
            c.w(p.CONTROL+(20 if action==241 else 16),enabled);c.run(p.CODE)
            self.assertEqual(any(call[0]=='select' for call in c.calls),restore,(action,enabled))
            self.assertEqual(c.r[2],1)

    def test_stale_paired_action_without_active_camera_does_not_rebind_cinematic(self):
        c,_=self.camera();c.w(ACTORS[0]+2376,303)
        c.callbacks[0x23DBC0]=lambda m:m.r.__setitem__(2,0)
        c.r[4]=0;c.run(p.VIEW)
        self.assertEqual(c.r[2],0)

    def test_activation_victim_uses_verified_caster_checkbox_not_its_old_hit_action(self):
        for enabled in (False,True):
            c,_=self.camera();c.w(ACTORS[0]+2376,11);c.w(ACTORS[1]+2376,264)
            c.w(p.CONTROL+16,enabled);camera_start(c,1)
            c.r[4]=0;c.r[31]=0xFEED0000;c.run(p.VIEW)
            self.assertEqual(c.r[2],int(enabled))

    def test_a_grab_joins_a_global_cinematic_only_through_its_own_pair(self):
        """A rush binding someone else (the participant fallback assumes a
        thrower's partner is slot^1) no longer takes over the grab view."""
        import extra_throws
        def run(bound,grab=(0,3),manager=True):
            c,_=self.camera(split=False);c.w(ACTORS[0]+2376,183)
            pair=[ACTORS[i] for i in grab]
            c.callbacks[extra_throws.LOOKUP]=lambda m:m.r.__setitem__(
                2,pair[1-pair.index(m.r[4])] if m.r[4] in pair else 0)
            cinematic=0x1850000 if manager else 0;c.w(c.r[28]-22180,cinematic)
            model=lambda i:c.u(p.core.MODELS+4*MIDS[i])
            if manager:
                for off,who in zip((768,772),bound):c.w(cinematic+off,model(who) if who is not None else 0)
            return self.run_view(c,0)
        self.assertEqual(run((1,4)),0)          # an unrelated rush: stay on the grab
        self.assertEqual(run((0,None)),1)       # the thrower itself is bound
        self.assertEqual(run((None,3)),1)       # the grabbed fighter is bound
        self.assertEqual(run((1,4),grab=(0,1)),1)   # its partner is the bound leader
        self.assertEqual(run((1,4),manager=False),0)

    def victim_machine(self,split=True,side=1,owner=2,caster=3):
        """A split view whose own subject is the recorded victim of a caster."""
        c,_=self.camera(split=split)
        c.w(p.fresh.SUCCESSOR_CONTROL+8+4*side,owner)
        c.w(ACTORS[caster]+2376,271);c.w(ACTORS[owner]+2376,11)
        for actor in (ACTORS[caster],ACTORS[owner]):
            c.w(actor+3732,caster);c.w(actor+3736,owner)
        c.w(ACTORS[owner]+4016,29)
        camera_start(c,caster)
        return c

    def run_view(self,c,side):
        c.r[4]=side;c.r[31]=0xFEED0000;c.run(p.VIEW);return c.r[2]

    def test_split_victim_of_an_owned_special_camera_is_viewed_on_its_own_half(self):
        c=self.victim_machine()
        self.assertEqual(self.run_view(c,1),1)
        # The reaction may also still be pending on the contact update, where
        # the native rush marker is set before the paired action commits.
        c=self.victim_machine();c.w(ACTORS[2]+4016,30)
        self.assertEqual(self.run_view(c,1),1)
        c=self.victim_machine();c.w(ACTORS[2]+4016,34)
        for bank in (0x1085,0x10AD):c.write(ACTORS[2]+bank+(0x94>>3),bytes([1<<(0x94&7)]))
        self.assertEqual(self.run_view(c,1),1)
        # Every part of the rule is load-bearing.
        for name,change in (('not_reciprocal',(ACTORS[3]+3736,4)),
                            ('caster_idle',(ACTORS[3]+2376,11)),
                            ('camera_not_owned',(arbitration.CONTROL+16,0)),
                            ('no_reaction',(ACTORS[2]+4016,0)),
                            ('owner_not_named',(ACTORS[2]+3736,4)),
                            ('subject_out_of_range',(p.fresh.SUCCESSOR_CONTROL+12,9))):
            c=self.victim_machine();c.w(*change)
            with self.subTest(name=name):self.assertEqual(self.run_view(c,1),0)
        # An ally is never a victim, and a single view is untouched.
        c=self.victim_machine(owner=4,caster=2)
        self.assertEqual(self.run_view(c,1),0)
        c=self.victim_machine(split=False)
        self.assertEqual(self.run_view(c,1),0)

    def test_split_victim_still_obeys_the_caster_category_checkboxes(self):
        # An ultimate follows its checkbox; an ordinary special always frames.
        for action,word,expected in ((264,16,True),(264,None,False),(271,None,True)):
            c=self.victim_machine();c.w(ACTORS[3]+2376,action)
            if word is not None:c.w(p.CONTROL+word,1)
            with self.subTest(action=action,enabled=word is not None):
                self.assertEqual(self.run_view(c,1),int(expected))
        # A transformation has no victim, so it can never reach this rule.
        for enabled in (0,1):
            c=self.victim_machine();c.w(ACTORS[3]+2376,241);c.w(p.CONTROL+20,enabled)
            with self.subTest(action=241,enabled=enabled):self.assertEqual(self.run_view(c,1),0)

    def test_split_rush_keeps_the_authored_view_inside_the_private_split_viewport(self):
        c,manager=self.camera();c.w(ACTORS[0]+2376,302)
        cine=c.u(p.camera.CINEMATIC);c.write(cine,bytes([0xCC])*0x340);before=c.read(cine,0x340)
        native=elf_reader(ROOT/'analysis/SLUS_219.78')[2]
        c.write(0x23E950,native(0x23E950,0x80))
        def rebuilt(m):
            m.calls.append(('anchor_rebuild',m.r[4],m.r[5]))
            m.w(m.r[28]-22176,m.r[4])
        c.callbacks[0x23EAD0]=rebuilt
        def recalc(m):
            m.calls.append(('recalculate',m.r[4],m.r[5]))
            m.w(m.r[28]-22176,m.r[4])
        c.callbacks[0x23E598]=recalc
        c.callbacks[0x23E6A0]=lambda m:m.calls.append(('matrix_bind',m.r[4],m.r[5]))
        c.r[4]=1;c.run(p.BIND)
        clone=p.CLONES[0]
        self.assertEqual(c.u(manager+0xC40),clone);self.assertEqual(c.u(c.r[28]-22176),clone)
        # The authored view matrix survives the split template, which only
        # supplies viewport/projection/scissor, and the rest of the authored
        # record (anchor, rendered eye) is untouched.
        self.assertEqual(c.read(clone,0x80),before[:0x80])
        self.assertEqual(c.read(clone+0x80,0x1E0),c.read(manager+0x260+0x80,0x1E0))
        self.assertEqual(c.read(clone+0x260,0x20),before[0x260:0x280])
        self.assertEqual(c.read(cine,0x340),before)
        # The VU matrices are recomputed from the template projections times
        # that view, with the cinematic's own rendered eye; the anchor-based
        # rebuild that discarded the authored framing is gone.
        self.assertIn(('recalculate',clone,cine+544),c.calls)
        self.assertNotIn('anchor_rebuild',[call[0] for call in c.calls])
        self.assertIn(('matrix_bind',clone,1),c.calls)
        c.w(c.r[28]-22176,manager+0x9B0);c.w(manager+0xC40,manager+0x9B0)
        c.r[4]=1;c.r[31]=0xFEED0000;c.run(p.BIND)
        self.assertEqual(c.u(c.r[28]-22176),manager+0x9B0)
        self.assertEqual(c.calls[-1][0],'native_bind')

    def test_coop_p2_and_fusion_and_ffa_dead_successor_use_physical_subjects(self):
        for mode,side,initial,fused,alive,winner,expected in (
            (p.modes.COOP,1,1,-1,{0,2,4},-1,2),
            (p.modes.COOP,0,0,2,{2,4},-1,2),
            (p.modes.COOP,1,1,0,{0,4},-1,0),
            (p.modes.FFA,0,4,-1,{1,2},-1,1),
            (p.modes.FFA,0,0,-1,{0,2},2,2)):
            c,_=self.camera();manager=c.u(p.core.ACTORS)
            c.write(p.modes.CONTROL,struct.pack('<9I',p.modes.MAGIC,manager,6,mode,2,63,fused&0xffffffff,0xffffffff,0))
            c.w(p.modes.CONTROL+44,winner&0xffffffff);c.w(p.result.RESULT,int(winner>=0))
            c.w(p.fresh.SUCCESSOR_CONTROL+8+4*side,initial)
            def lookup(m):
                pid=m.r[4];m.r[2]=MIDS[pid] if pid<6 else 0xffffffff;m.r[3]=int(pid in alive);m.r[5]=pid&1
            c.callbacks[p.continuity.LOOKUP]=lookup
            c.r[4]=side;before=c.r[3:].copy();c.run(p.SUBJECT)
            self.assertEqual(c.r[2],MIDS[expected]);self.assertEqual(c.r[3:],before)
            self.assertEqual(c.u(p.fresh.SUCCESSOR_CONTROL+8+4*side),expected)

    def locked_subject(self,side,locked,mode=None,alive=None,armed=True):
        """Run SUBJECT with a spectator lock set for one side.

        mode None installs no battle-mode block, which is what Team Battle does.
        """
        import spectator_switch as spec
        c,_=self.camera();manager=c.u(p.core.ACTORS)
        if mode is not None:
            c.write(p.modes.CONTROL,struct.pack('<9I',p.modes.MAGIC,manager,6,mode,1,63,0xffffffff,0xffffffff,0))
        if armed:c.w(spec.CONTROL,spec.MAGIC)
        c.w(spec.CONTROL+spec.FIELDS['lock']+4*side,locked+1)
        c.w(p.fresh.SUCCESSOR_CONTROL+8+4*side,side)
        living=set(range(6)) if alive is None else set(alive)
        def lookup(m):
            pid=m.r[4];m.r[2]=MIDS[pid] if pid<6 else 0xffffffff;m.r[3]=int(pid in living);m.r[5]=pid&1
        c.callbacks[p.continuity.LOOKUP]=lookup
        # The pre-lock fallback: camera_successor keeps the viewport's own side.
        c.callbacks[p.fresh.SUCCESSOR]=lambda m:m.r.__setitem__(2,MIDS[side])
        c.r[4]=side;c.run(p.SUBJECT)
        return c,spec

    def test_a_spectator_lock_wins_in_every_mode_and_on_either_team(self):
        """Team Battle used to fall through to a same-side rescan."""
        for mode in (None,p.modes.TEAMS,p.modes.COOP,p.modes.FFA):
            for side,locked in ((0,3),(1,4),(0,1),(1,0)):
                with self.subTest(mode=mode,side=side,locked=locked):
                    c,_=self.locked_subject(side,locked,mode)
                    self.assertEqual(c.r[2],MIDS[locked])
                    self.assertEqual(c.u(p.fresh.SUCCESSOR_CONTROL+8+4*side),locked)

    def test_a_defeated_locked_fighter_releases_the_lock(self):
        c,spec=self.locked_subject(0,3,None,alive={0,1,2,4,5})
        self.assertEqual(c.u(spec.CONTROL+spec.FIELDS['lock']),0)
        self.assertEqual(c.r[2],MIDS[0])        # back to the camera's own choice

    def test_no_lock_leaves_every_mode_to_its_own_rules(self):
        c,spec=self.locked_subject(0,-1,None)   # lock word 0 = none
        self.assertEqual(c.r[2],MIDS[0])

    def test_a_lock_is_ignored_without_the_spectator_installed(self):
        c,_=self.locked_subject(0,3,None,armed=False)
        self.assertEqual(c.r[2],MIDS[0])

    def priority_machine(self,split=False,base=0,side=0,candidates=(),ultimate=0,transformation=1,alive=None,bank=4295,grab=None):
        c,_=self.camera(split=split)
        # extra_throws.LOOKUP: a0 actor -> v0 verified throw partner actor or 0.
        import extra_throws
        def throw_lookup(m):
            partner=None
            if grab is not None:
                pair=[ACTORS[i] for i in grab]
                if m.r[4] in pair:partner=pair[1-pair.index(m.r[4])]
            m.r[2]=partner or 0
        c.callbacks[extra_throws.LOOKUP]=throw_lookup
        c.callbacks[p.fresh.SUCCESSOR]=lambda m:m.r.__setitem__(2,MIDS[base])
        c.w(p.fresh.SUCCESSOR_CONTROL+8+4*side,base)
        c.w(p.CONTROL+16,ultimate);c.w(p.CONTROL+20,transformation)
        living=set(range(6)) if alive is None else set(alive)
        def lookup(m):
            pid=m.r[4];m.r[2]=MIDS[pid] if pid<6 else 0xffffffff;m.r[3]=int(pid in living);m.r[5]=pid&1
        c.callbacks[p.continuity.LOOKUP]=lookup
        for pid,action in candidates:
            c.w(ACTORS[pid]+2376,action);c.write(ACTORS[pid]+bank,bytes([8]))
        c.r[4]=side;c.r[31]=0xFEED0000
        return c

    def fusion_camera(self,side=1):
        c=self.priority_machine(split=True,base=2*side,side=side,
                                candidates=((0,241),(2,241)))
        manager=c.u(p.core.ACTORS)
        values=(p.modes.MAGIC,manager,6,p.modes.COOP,2,63,0xffffffff,0xffffffff,0)
        c.write(p.modes.CONTROL,struct.pack('<9I',*values));c.w(p.modes.CONTROL+64,1)
        c.w(p.fresh.SUCCESSOR_CONTROL+8,0);c.w(p.fresh.SUCCESSOR_CONTROL+12,2)
        return c

    def test_consenting_p2_sees_fusion_even_if_both_participants_raise_priority(self):
        for side in (0,1):
            c=self.fusion_camera(side)
            c.run(p.PRIORITY)
            self.assertEqual(c.r[2],MIDS[0])
            self.assertEqual(c.u(p.fresh.SUCCESSOR_CONTROL+8+4*side),2*side)
        # The priority exception disappears with the actual fusion action.
        c=self.fusion_camera();c.w(ACTORS[0]+2376,236);c.run(p.PRIORITY)
        self.assertEqual(c.r[2],MIDS[2])

    def test_p2_shared_fusion_camera_requires_the_bound_leader_and_live_consent(self):
        c=self.fusion_camera();cine=c.u(c.r[28]-22180)
        model=c.u(p.core.MODELS+4*MIDS[0]);c.w(cine+768,model);c.w(cine+772,0)
        self.assertEqual(self.run_view(c,1),1)
        # Unrelated cinematics, stale consent and disabled cinematic options
        # must keep the ordinary P2 view. A pending request is not acceptance.
        for address,value in ((cine+768,c.u(p.core.MODELS+4*MIDS[3])),
                (p.modes.CONTROL+64,0),(p.modes.CONTROL+24,0),
                (p.modes.CONTROL+4,0),(p.modes.CONTROL+8,4),
                (p.modes.CONTROL+12,p.modes.FFA),(p.CONTROL+20,0),
                (ACTORS[0]+2376,11),(p.fresh.SUCCESSOR_CONTROL+12,4)):
            before=c.u(address);c.w(address,value)
            with self.subTest(address=hex(address),value=value):self.assertEqual(self.run_view(c,1),0)
            c.w(address,before)
        c.callbacks[p.continuity.LOOKUP]=lambda m:(m.r.__setitem__(2,MIDS[m.r[4]]),m.r.__setitem__(3,int(m.r[4]!=2)))
        self.assertEqual(self.run_view(c,1),0)

    def test_fusion_camera_helper_preserves_native_registers_and_has_no_side_effects(self):
        c=self.fusion_camera();before=c.r[:2]+c.r[3:]
        mode_before=c.read(p.modes.CONTROL,100)
        c.run(p.COOP_FUSION)
        self.assertEqual(c.r[2],ACTORS[0]);self.assertEqual(c.r[:2]+c.r[3:],before)
        self.assertEqual(c.read(p.modes.CONTROL,100),mode_before)

    def test_priority_subject_follows_unique_transforming_fighter_only_when_enabled(self):
        for action,ultimate,transformation,expected in (
                (236,0,1,3),(243,0,1,3),(236,1,0,0),(261,1,0,3),(264,1,0,3),(263,1,1,0),(302,1,1,0),(11,1,1,0),(236,0,0,0)):
            c=self.priority_machine(candidates=((3,action),),ultimate=ultimate,transformation=transformation)
            before=c.r[3:].copy();c.run(p.PRIORITY)
            self.assertEqual(c.r[2],MIDS[expected],(action,ultimate,transformation));self.assertEqual(c.r[3:],before)
            self.assertEqual(c.u(p.fresh.SUCCESSOR_CONTROL+8),0)
            self.assertEqual(c.u(p.CONTROL+p.PRIORITY_VIEWS),int(expected==3))
            if expected==3:self.assertEqual(c.u(p.CONTROL+p.LAST_PRIORITY),3)

    def test_a_live_grab_keeps_its_camera_against_another_fighters_close_up(self):
        """Transformations keep their separate camera preference. A checked
        ultimate explicitly overrides every view, including an unrelated grab."""
        for grab in ((0,3),(3,0),(0,5)):
            c=self.priority_machine(candidates=((3,236),),transformation=1,grab=grab)
            c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[0],grab)
            self.assertEqual(c.u(p.CONTROL+p.PRIORITY_VIEWS),0)
            c=self.priority_machine(candidates=((3,261),),ultimate=1,grab=grab)
            c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[3],grab)
        c=self.priority_machine(candidates=((3,261),),ultimate=1,grab=(2,5))   # someone else's grab
        c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[3])
        c=self.priority_machine(candidates=((3,261),),ultimate=1)
        c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[3])

    def test_priority_requires_native_flag_in_either_bank_and_a_living_unique_candidate(self):
        c=self.priority_machine(candidates=((3,236),),bank=4255);c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[3])
        c=self.priority_machine();c.w(ACTORS[3]+2376,236);c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[0])
        c=self.priority_machine(candidates=((3,236),),alive=(0,1,2,4,5));c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[0])
        c=self.priority_machine(candidates=((3,236),(5,241)));c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[0])
        c=self.priority_machine(candidates=((0,236),(5,241)));c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[0])
        c=self.priority_machine(candidates=((0,236),));c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[0])
        self.assertEqual(c.u(p.CONTROL+p.PRIORITY_VIEWS),0)
        c=self.priority_machine(base=1,side=1,candidates=((4,236),));c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[4])

    def test_split_priority_follows_a_checked_close_up_from_either_team(self):
        # Checking a category asks for its camera and its pause together, so
        # a split half no longer refuses an enemy's close-up and strand a
        # stopped bystander on an ordinary camera. An unchecked category is
        # still never followed, in either view.
        for side,base,candidate in ((0,0,3),(0,0,2),(1,1,2),(1,1,3)):
            c=self.priority_machine(split=True,base=base,side=side,candidates=((candidate,236),))
            c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[candidate],(side,candidate))
            c=self.priority_machine(split=True,base=base,side=side,transformation=0,
                                    candidates=((candidate,236),))
            c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[base],(side,candidate))
        for split in (True,False):
            c=self.priority_machine(split=split,candidates=((2,236),));manager=c.u(p.core.ACTORS)
            c.write(p.modes.CONTROL,struct.pack('<9I',p.modes.MAGIC,manager,6,p.modes.FFA,2,63,0xffffffff,0xffffffff,0))
            c.run(p.PRIORITY);self.assertEqual(c.r[2],MIDS[2],split)

    def test_native_manager_stop_does_not_split_transformation_or_ultimate_impact(self):
        for pid,action in ((0,236),(2,237),(0,303),(2,303)):
            c=self.priority_machine(candidates=((pid,action),))
            c.w(p.CONTROL+p.TRANSFORM_VIEW,1);c.w(c.u(p.core.ACTORS)+628,1)
            c.run(p.SHARED_FORM if action<244 else p.ULTIMATE_OWNER)
            self.assertEqual(c.r[2],ACTORS[pid]);self.assertTrue(c.r[3])
            self.assertEqual(c.u(c.u(p.core.ACTORS)+628),1)

    def test_unchecked_impact_releases_only_living_nonparticipants(self):
        c=self.priority_machine(candidates=((0,303),));c.w(p.CONTROL+16,0)
        c.w(ACTORS[0]+3732,0);c.w(ACTORS[0]+3736,1)
        c.w(ACTORS[1]+2376,315);c.w(ACTORS[1]+3732,0);c.w(ACTORS[1]+3736,1)
        c.w(c.u(p.core.ACTORS)+628,1);c.run(p.BYSTANDERS)
        self.assertEqual(c.u(p.CONTROL+p.FREE_MASK),60)
        c.w(ACTORS[2]+2376,236);c.r[31]=0xFEED0000;c.run(p.BYSTANDERS)
        self.assertEqual(c.u(p.CONTROL+p.FREE_MASK),0,'Concurrent checked form keeps its stop')

    def test_actor_script_stop_queries_preserve_global_and_participant_holds(self):
        for (reg,offset),callers in p.SCRIPT_ACTORS.items():
            for caller in callers:
                for physical,expected in ((0,1),(1,1),(2,0)):
                    c=self.priority_machine();c.w(p.CONTROL+16,0)
                    c.w(c.u(p.core.ACTORS)+628,1);c.w(p.CONTROL+p.FREE_MASK,4)
                    c.r[reg]=ACTORS[physical]-offset;c.r[31]=caller
                    before=c.r.copy();c.run(p.SCRIPT_STOP,(caller,))
                    self.assertEqual(c.r[2],expected,(hex(caller),physical))
                    self.assertEqual(c.r[:2]+c.r[3:],before[:2]+before[3:])
                    self.assertEqual(c.u(c.u(p.core.ACTORS)+628),1)
        for mutation in ('unknown','checked','scene','result','identity','alias'):
            c=self.priority_machine();c.w(p.CONTROL+16,0);c.w(c.u(p.core.ACTORS)+628,1)
            c.w(p.CONTROL+p.FREE_MASK,4);c.r[17]=ACTORS[2];c.r[31]=0x1D452C
            if mutation=='unknown':c.r[31]=0xFEED0000
            elif mutation=='checked':c.w(p.CONTROL+16,1)
            elif mutation=='scene':c.w(p.continuity.SCENE_FLAGS,0x2000)
            elif mutation=='result':c.w(p.result.RESULT,1)
            elif mutation=='identity':c.w(p.CONTROL+4,0)
            else:c.w(p.core.PAIR+4,1)
            c.run(p.SCRIPT_STOP,(c.r[31],) if c.r[31]!=p.SCRIPT_STOP else ())
            self.assertEqual(c.r[2],1,mutation)

    def test_priority_is_inert_outside_combat_or_with_stale_subjects(self):
        for mutate in ((lambda c:c.w(c.u(p.team_intro.BATTLE),2)),(lambda c:c.w(p.result.RESULT,1)),
                       (lambda c:c.w(p.core.PAIR+4,1)),(lambda c:c.w(p.core.MODE,0)),
                       (lambda c:c.w(p.fresh.SUCCESSOR_CONTROL+8,5)),(lambda c:c.w(p.fresh.SUCCESSOR_CONTROL+8,9))):
            c=self.priority_machine(candidates=((3,236),));mutate(c);c.run(p.PRIORITY)
            self.assertEqual(c.r[2],MIDS[0]);self.assertEqual(c.u(p.CONTROL+p.PRIORITY_VIEWS),0)
        hook=dict(p.hooks())[p.fresh.successor.HOOK]
        self.assertEqual(struct.unpack_from('<I',hook),((3<<26)|(p.PRIORITY>>2),))

    def result_machine(self,winner=2):
        c,_=self.camera();manager=c.u(p.core.ACTORS)
        c.write(p.modes.CONTROL,struct.pack('<12I',p.modes.MAGIC,manager,6,p.modes.FFA,
                                          1,63,0xffffffff,0xffffffff,0,0,0,winner))
        c.w(p.result.RESULT,1+(winner&1));c.w(c.u(p.team_intro.BATTLE),6)
        c.callbacks[0x1DC178]=lambda m:m.r.__setitem__(2,ACTORS[m.r[4]])
        c.callbacks[0x12B1D0]=lambda m:m.r.__setitem__(2,MIDS[m.r[4]])
        c.callbacks[0x23DE60]=lambda m:m.calls.append(('result_camera',m.r[4],m.r[5]))
        return c

    def test_actual_ffa_winner_actor_model_camera_and_losing_native_channel(self):
        for winner in range(6):
            for side in range(2):
                expected=winner if side==(winner&1) else side
                for entry,value in ((p.RESULT_ACTOR,ACTORS[expected]),(p.RESULT_MODEL,MIDS[expected])):
                    c=self.result_machine(winner);c.r[4]=side;before=c.r.copy();c.run(entry)
                    self.assertEqual(c.r[2],value,(winner,side,entry));self.assertEqual(c.r[3:],before[3:])
                c=self.result_machine(winner);c.r[4]=side;c.r[5]=1 if side==(winner&1) else 2
                c.run(p.RESULT_CAMERA)
                self.assertEqual(c.calls,[('result_camera',MIDS[expected],1 if side==(winner&1) else 2)])

    def test_result_remapping_requires_exact_capture_and_confirmed_present_winner(self):
        for mutation in (
            (p.result.RESULT,0),(p.result.RESULT,4),(p.result.RESULT,8),
            (p.CONTROL,0),(p.CONTROL+4,0),(p.CONTROL+8,4),(p.CONTROL+12,0),
            (p.core.MODE+4,2),(p.core.PAIR+4,1),
            (p.modes.CONTROL,0),(p.modes.CONTROL+4,0),(p.modes.CONTROL+8,4),
            (p.modes.CONTROL+12,p.modes.COOP),(p.modes.CONTROL+12,p.modes.TEAMS),
            (p.modes.CONTROL+44,6),(p.modes.CONTROL+44,0xffffffff),(p.modes.CONTROL+20,3),
            (p.core.POINTERS+8,0),(ACTORS[2],3),(ACTORS[2]+12,12),
            (p.core.MODELS+4*MIDS[2],0),(MODELS[2]+16,0)):
            c=self.result_machine();c.w(*mutation);c.r[4]=0;c.run(p.RESULT_ACTOR)
            self.assertEqual(c.r[2],ACTORS[0],mutation)

    def test_native_result_requests_and_camera_use_actual_survivor_without_rewriting_voice_side(self):
        native=elf_reader(ROOT/'analysis/SLUS_219.78')[2]
        c=self.result_machine();c.callbacks.pop(0x23DE60)
        for start,size in ((0x209F58,0x100),(0x217730,0x180),(0x2179D0,0xE0),
                           (0x23DE60,0x74),(0x23DC68,0x28)):
            c.write(start,native(start,size))
        for at,data in p.hooks():c.write(at,data)
        flag=[]
        c.callbacks[0x1DABE8]=lambda m:flag.append((m.r[4],m.r[5]))
        c.callbacks[0x23DCE0]=lambda m:m.calls.append(('camera_model',m.r[4]))
        c.w(MODELS[2]+0xB4,0x4550000)
        script=0x4560000;c.w(script+8,0);c.r[16]=script
        c.run(0x217A14,stops=(0x217A28,))
        self.assertEqual(flag,[(ACTORS[2],0xF1)])
        self.assertEqual(c.events,[('start',0x4550000)])
        self.assertIn(('camera_model',MODELS[2]),c.calls)
        self.assertEqual(c.u(c.u(p.camera.CINEMATIC)+776),5)
        self.assertEqual(c.u(script+8),0)
        # Native result setup uses the actual character model for its dialogue
        # table, while retaining logical side0 as the two-channel voice index.
        c.w(MODELS[2]+0x93C,0x4570000)
        c.r[4]=0;c.r[17]=0;c.run(0x217764,stops=(0x217790,))
        self.assertEqual(c.r[21],MODELS[2]);self.assertEqual(c.r[22],0x4570000)
        self.assertEqual(c.r[20],MODELS[1]);self.assertEqual(c.u(script+8),0)
        checked=[]
        c.callbacks[0x1C4638]=lambda m:(checked.append(m.r[4]),m.r.__setitem__(2,0x183))
        c.r[4]=0;c.r[31]=0xFEED0000;c.run(0x209FC8)
        self.assertEqual(checked,[ACTORS[2]]);self.assertEqual(c.r[2],1)


if __name__=='__main__':unittest.main()
