"""Finishing damage hands the same actual victim to native falling physics."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest
import tag_team_rush as tag
import tag_rush_scene as scene
import tag_rush_recovery as recovery
import tag_rush_safety as safety
from test_tag_rush_scene import fixture,start
from test_tag_rush_camera import run


class RecoveryTests(unittest.TestCase):
    def machine(self,slam=False):
        c=fixture();start(c)
        descriptor=c.u(scene.STATE+scene.S['descriptor'])
        c.w(descriptor+28,recovery.SLAM_DOWN if slam else 0)
        return c

    def test_surviving_victim_falls_without_an_idle_frame_and_can_use_native_recovery(self):
        for slam in (False,True):
            c=self.machine(slam);before=len(c.calls);c.r[4]=0;run(c,scene.FINISH)
            victim=c.actors[1]
            self.assertEqual(c.u(victim+2376),recovery.FALL_ACTION)
            self.assertEqual(c.u(victim+2420),198)
            self.assertAlmostEqual(c.fr(victim+0xAC),(360. if slam else 120.)/recovery.ACTOR_HZ)
            self.assertEqual(c.u(victim+0x9E4),15000)
            self.assertEqual([args[1] for pc,args in c.calls[before:]
                if pc==scene.A(0x1E0290) and args[0]==victim],[217])
            for index in (0,2):self.assertEqual(c.u(c.actors[index]+2376),11)
            self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)
            self.assertEqual(c.u(tag.CONTROL+tag.C['members']),0)
            # Native stunned recovery is admitted without faking controller input or reviving.
            self.assertEqual(c.u(victim+0x1000),4)
            self.assertEqual(c.u(victim+0xA0C),1)
            self.assertEqual(c.u(recovery.STATE+recovery.STRIDE+recovery.ACTIVE),1)
            self.assertEqual(c.u(victim+4896),0)
            run(c,scene.FINISH);self.assertEqual(len(c.damage),1)

    def test_slam_seeds_native_away_speed_once_without_moving_or_hitting_again(self):
        c=self.machine(True);v=c.actors[1];row=scene.ROWS+2*scene.STRIDE
        c.w(c.models[1]+192,c.u(row+scene.R['clip0']))
        for model,x,z in ((c.models[0],-30.,-40.),(c.models[1],0.,0.)):
            c.fw(model+2384,x);c.fw(model+2392,z)
        before=c.read(v+0x10,16);damage=len(c.damage)
        c.r[4:6]=[row,recovery.SLAM_DOWN];run(c,recovery.BEGIN)
        self.assertEqual(c.r[2],1);self.assertEqual(c.read(v+0x10,16),before)
        self.assertAlmostEqual(c.fr(v+0x90),.6,places=5)
        self.assertEqual(c.fr(v+0x94),0.)
        self.assertAlmostEqual(c.fr(v+0x98),.8,places=5)
        self.assertEqual(c.fr(v+0xA8),480./recovery.ACTOR_HZ)
        self.assertEqual(c.fr(v+0xAC),360./recovery.ACTOR_HZ)
        self.assertEqual(len(c.damage),damage)
        c=self.machine(False);c.r[4]=0;run(c,scene.FINISH)
        self.assertEqual(c.fr(c.actors[1]+0xA8),0.)

    def test_slam_normalization_uses_ee_ft_for_all_horizontal_quadrants(self):
        roots=[word for word in struct.unpack('<'+'I'*(len(recovery.code())//4),recovery.code())
               if word>>26==17 and word>>21&31==16 and word&63==4]
        self.assertEqual(len(roots),1);self.assertEqual(roots[0]>>16&31,4)
        for dx,dz in ((12.,5.),(-12.,5.),(12.,-5.),(-12.,-5.),(0.,50.)):
            c=self.machine(True);v=c.actors[1];row=scene.ROWS+2*scene.STRIDE
            c.w(c.models[1]+192,c.u(row+scene.R['clip0']))
            for model,x,z in ((c.models[0],-dx,-dz),(c.models[1],0.,0.)):
                c.fw(model+2384,x);c.fw(model+2392,z)
            c.r[4:6]=[row,recovery.SLAM_DOWN];run(c,recovery.BEGIN)
            length=math.hypot(dx,dz)
            self.assertAlmostEqual(c.fr(v+0x90),dx/length,places=6)
            self.assertAlmostEqual(c.fr(v+0x98),dz/length,places=6)
            self.assertAlmostEqual(c.fr(v+0x90)**2+c.fr(v+0x98)**2,1.,places=6)

    def test_a_lethal_hit_falls_without_reviving_or_replacing_native_ko_rules(self):
        c=self.machine();c.w(c.actors[1]+0x9E4,1000)
        c.r[4]=0;run(c,scene.FINISH)
        self.assertEqual(c.u(c.actors[1]+0x9E4),0)
        self.assertEqual(c.u(c.actors[1]+2376),217)
        self.assertEqual(len(c.damage),1)

    def test_cancel_and_scenario_veto_restore_own_pose_without_forcing_a_hit(self):
        for cancel in (0,1):
            c=self.machine();victim=c.actors[1]
            if not cancel:
                c.callbacks[safety.DAMAGE]=lambda m:m.r.__setitem__(2,0)
            c.r[4]=cancel;run(c,scene.FINISH)
            self.assertEqual(c.u(victim+2376),11)
            self.assertEqual(c.u(victim+0x9E4),30000)
            self.assertEqual(c.fr(victim+0xAC),0.)
            self.assertTrue(any(who==victim for who,clip,blend in c.idle_starts))

    def test_scenario_form_change_or_replacement_during_damage_keeps_its_own_state(self):
        c=self.machine();victim=c.actors[1];model=c.models[1]
        def scripted(m):
            m.w(victim+0x9E4,100);m.w(model+12,25);m.w(victim+2376,316)
            m.fw(victim+0xAC,1.25);m.r[2]=1
        c.callbacks[safety.DAMAGE]=scripted;c.r[4]=0;run(c,scene.FINISH)
        self.assertEqual(c.u(victim+2376),316)
        self.assertEqual(c.fr(victim+0xAC),1.25)
        self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)

    def test_refused_final_preserves_scenario_action_or_replaced_body(self):
        for changed in ('action','form','model'):
            c=self.machine();victim=c.actors[1];model=c.models[1]
            before=len(c.idle_starts)
            def veto(m):
                if changed=='form':m.w(model+12,25)
                elif changed=='model':m.w(tag.core.MODELS+4,c.models[2])
                m.w(victim+2376,316);m.fw(victim+0xAC,1.25);m.r[2]=0
            c.callbacks[safety.DAMAGE]=veto;c.r[4]=0;run(c,scene.FINISH)
            self.assertEqual(c.u(victim+2376),316,changed)
            self.assertEqual(c.fr(victim+0xAC),1.25,changed)
            self.assertFalse(any(who==victim for who,clip,blend in c.idle_starts[before:]),changed)
            self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)

    def test_handoff_rejects_foreign_row_and_changed_identity_without_writes(self):
        for bad in ('row','model','directory'):
            c=self.machine();victim=c.actors[1];row=scene.ROWS+2*scene.STRIDE
            c.w(c.models[1]+192,c.u(row+scene.R['clip0']))
            if bad=='model':c.w(c.models[1]+64,0x123456)
            if bad=='directory':c.w(c.models[1]+192,0x123456)
            before=c.read(victim,0x1600)
            c.r[4]=scene.ROWS if bad=='row' else row;c.r[5]=64
            run(c,recovery.BEGIN);self.assertEqual(c.r[2],0)
            self.assertEqual(c.read(victim,0x1600),before)

    def test_actual_native_fall_entry_decodes_own_hurt_pose_and_releases_hover(self):
        from prototype import ROOT,elf_reader
        from native_map import A,elf_path
        c=self.machine();row=scene.ROWS+2*scene.STRIDE;actor=c.actors[1];model=c.models[1]
        c.w(model+192,c.u(row+scene.R['clip0']))
        native=elf_reader(elf_path(ROOT))[2];entry=A(0x1EA298)
        c.write(entry,native(entry,A(0x1EA5F8)-entry));cleared=[]
        c.callbacks[A(0x1E0A20)]=lambda m:m.r.__setitem__(2,0)
        c.callbacks[A(0x1E0368)]=lambda m:m.r.__setitem__(2,11)
        c.callbacks[A(0x1DAA50)]=lambda m:cleared.append((m.r[4],m.r[5]))
        c.r[4:6]=[actor,0];run(c,entry)
        self.assertEqual(c.u(actor+2420),198)
        self.assertEqual(c.u(model+2880),c.u(model+192)+0x80)
        self.assertIn((actor,0xE),cleared)

    def status_machine(self):
        c=self.machine();c.r[4]=0;run(c,scene.FINISH);c.status_calls=[];c.paused=False
        def status(m):
            actor=m.r[4];m.status_calls.append(actor)
            if not m.paused:
                hp=actor+164*m.u(actor+0x994)+0x9E4;m.w(hp+40,int(m.u(hp)<10000))
            m.r[2]=0x12345678
        c.callbacks[scene.A(0x1C2318)]=status
        c.callbacks[scene.A(0x1DC2C0)]=lambda m:m.r.__setitem__(2,int(m.paused))
        return c

    def test_status_override_only_owns_the_surviving_exact_victim(self):
        c=self.status_machine();victim=c.actors[1]
        for actor in c.actors:
            c.r[4]=actor;run(c,recovery.STATUS)
            self.assertEqual(c.r[2],0x12345678)
            self.assertEqual(c.u(actor+0xA0C),int(actor==victim))
        self.assertEqual(c.status_calls,c.actors)
        self.assertEqual(c.u(victim+0x9E4),15000)
        self.assertEqual(c.u(victim+0x1000),4)

    def test_release_preserves_natural_status_on_every_exit(self):
        for why in ('counter','recovered','interrupted','KO','form','model','manager','count','disabled','timeout','second_hit'):
            c=self.status_machine();v=c.actors[1];row=recovery.STATE+recovery.STRIDE
            if why=='counter':c.w(v+0x1000,0)
            elif why=='recovered':c.w(v+2376,225)
            elif why=='interrupted':c.w(v+2376,207)
            elif why=='KO':c.w(v+0x9E4,0)
            elif why=='form':c.w(c.models[1]+12,33)
            elif why=='model':c.w(tag.core.MODELS+4,c.models[2])
            elif why=='manager':c.w(c.r[28]-22364,0x1800000)
            elif why=='count':c.w(tag.core.MODE+4,2)
            elif why=='disabled':c.w(tag.CONTROL+tag.C['enabled'],0)
            elif why=='timeout':c.w(row+recovery.TICKS,recovery.LIMIT)
            elif why=='second_hit':c.w(v+0x9E4,14000)
            c.r[4]=v;run(c,recovery.STATUS)
            self.assertEqual(c.u(row+recovery.ACTIVE),0,why)
            self.assertEqual(c.u(v+0xA0C),int(c.u(v+0x9E4)<10000),why)
        c=self.status_machine();v=c.actors[1];c.w(v+0x9E4,5000);c.w(v+2376,225)
        c.r[4]=v;run(c,recovery.STATUS);self.assertEqual(c.u(v+0xA0C),1)

    def test_native_reserve_banks_use_only_selected_hp_and_stunned_status(self):
        for bank in range(1,5):
            c=self.machine();v=c.actors[1];hp=v+164*bank+0x9E4
            c.w(v+0x994,bank);c.w(hp,30000);c.w(v+0x9E4,0)
            # The damage ledger captures the active reserve bank at scene
            # entry. Reinitialize after selecting this fixture's bank.
            run(c,scene.damage_schedule.RESET)
            c.r[4]=0;run(c,scene.FINISH)
            self.assertEqual(c.u(hp),15000);self.assertEqual(c.u(v+0x9E4),0)
            self.assertEqual(c.u(hp+40),1);self.assertEqual(c.u(v+0xA0C),0)
            self.assertEqual(c.u(v+2376),217);self.assertEqual(c.u(v+0x1000),4)
            self.assertEqual(c.u(recovery.STATE+recovery.STRIDE+recovery.BANK),bank)
        c=self.status_machine();v=c.actors[1];c.w(v+0x994,1);c.w(v+164+0x9E4,30000)
        c.r[4]=v;run(c,recovery.STATUS)
        self.assertEqual(c.u(v+0xA0C),0)
        self.assertEqual(c.u(v+164+0xA0C),0)
        self.assertEqual(c.u(recovery.STATE+recovery.STRIDE+recovery.ACTIVE),0)

    def test_native_pause_does_not_consume_recovery_counter_or_timeout(self):
        c=self.status_machine();v=c.actors[1];row=recovery.STATE+recovery.STRIDE;c.paused=True
        before=c.read(row,recovery.STRIDE)
        c.r[4]=v;run(c,recovery.STATUS)
        self.assertEqual(c.read(row,recovery.STRIDE),before)
        self.assertEqual(c.u(v+0x1000),4)

    def test_native_counter_initializer_and_fall_handler_use_real_mash_input(self):
        from prototype import ROOT,elf_reader
        from native_map import A,elf_path
        c=self.status_machine();actor=c.actors[1];native=elf_reader(elf_path(ROOT))[2]
        # Execute the unmodified native counter-init basic blocks, including
        # their own low-HP status predicate and own-animation category checks.
        begin,end=A(0x1E22D8),A(0x1E2348);c.write(begin,native(begin,end-begin))
        c.callbacks[A(0x1C4638)]=lambda m:m.r.__setitem__(2,198)
        c.callbacks[A(0x1C4648)]=lambda m:m.r.__setitem__(2,0)
        c.callbacks[A(0x1C4650)]=lambda m:m.r.__setitem__(2,0x80030810 if m.r[4]==198 else 0)
        c.callbacks[A(0x1CF0C8)]=lambda m:m.r.__setitem__(2,0)
        c.callbacks[A(0x1CE1B8)]=lambda m:m.r.__setitem__(2,m.r[4]+0x9E4)
        c.w(actor+0x1000,0);c.r[17]=actor;c.run(begin,stops=(end,))
        self.assertEqual(c.u(actor+0x1000),4)
        entry=A(0x1EA298);c.write(entry,native(entry,A(0x1EA5F8)-entry))
        for address in (0x1C4920,0x1DE080,0x1DED28,0x1E7ED0):c.callbacks[A(address)]=lambda m:None
        c.callbacks[A(0x1DC2D0)]=lambda m:m.r.__setitem__(2,int(m.u(m.r[4]+0x9E4)>0))
        c.callbacks[A(0x1DC480)]=lambda m:m.r.__setitem__(2,0)
        c.callbacks[A(0x1E05E8)]=lambda m:m.set_number(0,100.)
        c.callbacks[A(0x1D4D98)]=lambda m:m.r.__setitem__(2,int(m.r[5]==0x100000))
        flags=[];c.callbacks[A(0x1DABE8)]=lambda m:flags.append((m.r[4],m.r[5]))
        c.w(actor+2380,-1)
        for remaining in (3,2,1,0):
            c.r[4:6]=[actor,1];run(c,entry)
            self.assertEqual(c.u(actor+0x1000),remaining)
            c.r[4:6]=[actor,2];run(c,entry)
            self.assertEqual(c.u(actor+2380),230 if remaining==0 else 0xFFFFFFFF)
        self.assertIn((actor,recovery.FLAG(0xE7)),flags)
        self.assertEqual(c.u(actor+0x9E4),15000)

    def test_exact_hook_bytes_are_the_selected_native_disc_call(self):
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        self.assertEqual(elf_reader(elf_path(ROOT))[2](recovery.HOOK,8),recovery.NATIVE_HOOK)


if __name__=='__main__':unittest.main()
