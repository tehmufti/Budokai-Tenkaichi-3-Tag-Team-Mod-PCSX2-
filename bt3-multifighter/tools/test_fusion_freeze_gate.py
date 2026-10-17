"""TTM-MATCH-21 CPU fusion freeze (Oct 16): an extra's form or fusion pose must not hold the match
before its reload is claimed, and a retired body's texture group must not stay reserved.

Synthetic guest machines, no savestates: FORM_GATE/FORM_TRACK and the shared transformation stop
(cinematic_policy) and the commit's group_in_use scan (extra_reload_commit).
"""
import struct
import unittest

import cinematic_policy as p
import extra_reload_commit as commit
import extra_reload_forms as forms
import extra_reload_requests as requests
from prototype import Assembler
from test_concurrent_cinematic_progress import machine as policy_machine, run
from test_fused_shared_cinematic import ACTORS, MODELS, Cpu


def row(physical):
    return requests.RECORDS+(physical-2)*requests.STRIDE


def gated(worker=True):
    c=policy_machine()
    for address,data in ((p.FORM_GATE,p.form_gate_code()),(p.FORM_TRACK,p.form_track()),
                         (p.SHARED_FORM,p.shared_form_owner(form_gate=True))):c.write(address,data)
    if worker:c.w(forms.CONTROL,1);c.w(forms.FORM_ENABLE,1)
    return c


def publish(c,physical,generation,status,kind=1,action=236):
    at=row(physical)
    c.w(at,generation);c.w(at+4,status);c.w(at+8,ACTORS[physical]);c.w(at+56,kind);c.w(at+60,action)


def pose(c,physical,action=236):
    c.w(ACTORS[physical]+2376,action)
    c.write(ACTORS[physical]+p.PRIORITY_FLAG_BYTES[0],bytes([p.PRIORITY_FLAG_BIT]))


def gate(c,physical):
    c.r[4]=physical;return run(c,p.FORM_GATE)


class FormGateTests(unittest.TestCase):
    def test_leaders_and_matches_without_the_private_worker_keep_todays_answer(self):
        c=gated(worker=False)
        for physical in range(6):self.assertEqual(gate(c,physical),1)
        c=gated()
        for physical in (0,1):self.assertEqual(gate(c,physical),1)

    def test_an_extra_owns_the_stop_only_after_this_poses_request_was_claimed(self):
        c=gated();publish(c,2,4,6);run(c,p.FORM_TRACK)     # outside the family: generation 4 remembered
        self.assertEqual(c.u(p.CONTROL+p.FORM_LIVE+8),4)
        pose(c,2);run(c,p.FORM_TRACK);self.assertEqual(c.u(p.CONTROL+p.FORM_LIVE+8),4)
        self.assertEqual(gate(c,2),0,'an earlier pose\'s receipt (6) is not this pose')
        publish(c,2,5,1);self.assertEqual(gate(c,2),0,'pending: waiting for room, nobody is held')
        for status in (2,3,4,5,6):
            publish(c,2,5,status)
            with self.subTest(status=status):self.assertEqual(gate(c,2),1)
        publish(c,2,5,5,kind=0);self.assertEqual(gate(c,2),0,'a costume row never opens the gate')

    def test_a_stale_costume_completion_cannot_open_a_new_pose(self):
        c=gated();publish(c,3,9,5,kind=0,action=0);run(c,p.FORM_TRACK)
        pose(c,3);publish(c,3,9,5,kind=0,action=0)
        self.assertEqual(gate(c,3),0)

    def test_a_refused_or_unpublished_form_holds_nobody(self):
        """Live repro: the pose waited for a texture group (pending row) or behind another
        fighter's special (no row at all) while every fighter was held for 900 updates."""
        for pending in (False,True):
            c=gated();publish(c,2,0,0,kind=0,action=0);run(c,p.FORM_TRACK);pose(c,2)
            c.w(ACTORS[3]+2376,262)                        # another fighter mid-special
            if pending:publish(c,2,1,1)
            run(c,p.FORM_TRACK);run(c,p.ULTIMATE_STOP)
            with self.subTest(pending=pending):
                self.assertEqual([c.u(a+4896) for a in ACTORS],[0]*6)
                self.assertEqual(c.u(p.CONTROL+p.HOLD_AGE),0)
            publish(c,2,1,2);run(c,p.FORM_TRACK);run(c,p.ULTIMATE_STOP)
            with self.subTest(pending=pending,claimed=True):
                self.assertEqual([c.u(a+4896) for a in ACTORS],[1,1,0,1,1,1])

    def test_a_form_and_another_activation_never_stop_each_other(self):
        """Live (after2): a leader's special (activation flags) and an extra's claimed form both
        stopped each other through the native activation stop until the bound, and the worker then
        failed the interrupted acknowledgment. While an extra's admitted form forced the stop, no
        activation participant is stopped; otherwise (leaders, ultimates) the native answer stands."""
        for extra_form,expected in ((1,(0,0,7)),(0,(7,7,7))):
            c=gated();c.write(p.STORE,p.store(form_gate=True))
            c.w(p.CONTROL+24,1);c.w(p.CONTROL+32,1);c.w(p.CONTROL+p.SHARED_STOP,2);c.w(p.CONTROL+p.FORM_FORCE,extra_form)
            c.w(p.pause.CONTROL+52,(1<<1)|(1<<4))
            got=[]
            for physical in (1,4,5):
                actor=ACTORS[physical%6];c.w(actor+4900,0)
                c.r[16]=actor;c.r[17]=physical+1;c.r[18]=7;run(c,p.STORE);got.append(c.u(actor+4900))
            with self.subTest(extra_form=extra_form):self.assertEqual(tuple(got),expected)

    def test_the_gate_and_tracker_restore_every_register_they_use(self):
        c=gated();publish(c,2,7,3);pose(c,2)
        for r in range(8,13):c.r[r]=0x1111*r
        c.r[29]=0x01F00000;sp=c.r[29]
        run(c,p.FORM_TRACK);self.assertEqual([c.r[r] for r in range(8,13)],[0x1111*r for r in range(8,13)])
        c.r[4]=2;run(c,p.FORM_GATE);self.assertEqual([c.r[r] for r in range(8,11)],[0x1111*r for r in range(8,11)])
        self.assertEqual(c.r[29],sp)

    def test_the_gated_emission_is_recognised_and_the_previous_one_still_upgrades(self):
        cur=dict(p.program(participants=True,form_gate=True));old=dict(p.program(participants=True))
        self.assertEqual({a for a in cur if cur[a]!=old.get(a)},
                         {p.PREPARE,p.STORE,p.SHARED_FORM,p.ULTIMATE_FRAME,p.FORM_GATE,p.FORM_TRACK})
        parts=sorted(cur.items())
        self.assertTrue(all(a+len(d)<=b for (a,d),(b,_) in zip(parts,parts[1:])))
        self.assertLessEqual(p.FORM_TRACK+len(p.form_track()),p.CLONES[0])
        self.assertLessEqual(p.CONTROL+p.FORM_LIVE+4*12,p.CONTROL+0x100)


class SharedGroupTests(unittest.TestCase):
    def scan(self,groups,group):
        a=Assembler(0x01000000);a.addiu(2,0,0)
        commit.group_in_use(a,group,'shared','unused','probe')
        a.label('shared');a.addiu(2,0,1);a.jr()
        a.label('unused');a.jr()
        c=Cpu({'segments':[]});c.write(0x01000000,a.finish())
        for mid,(live,g) in enumerate(groups):
            model,geometry=0x03000000+mid*0x2000,0x03800000+mid*0x100
            c.w(commit.stage.prior.core.MODELS+4*mid,model);c.w(model+4,int(live));c.w(model+64,geometry);c.w(geometry+40,g)
        c.r[31]=0xFEED0000;c.run(0x01000000);return c.r[2]

    def test_only_a_live_model_on_the_same_group_keeps_it_reserved(self):
        self.assertEqual(self.scan([(True,0),(True,1),(True,13)],6),0)
        self.assertEqual(self.scan([(True,0),(True,6),(True,13)],6),1)
        self.assertEqual(self.scan([(True,0),(False,6),(True,13)],6),0,'a destroyed model frees its group')

    def test_the_worker_commit_returns_unshared_groups_and_shared_payloads_do_not(self):
        import inspect
        source=inspect.getsource(commit.payload)
        self.assertIn("if c.get('return_unshared_group')",source)
        self.assertIn('return_unshared_group=True',inspect.getsource(commit.capture))
        import body_swap_commit,fusion_duration_commit
        for module in (body_swap_commit,fusion_duration_commit):
            self.assertNotIn('return_unshared_group',inspect.getsource(module))


if __name__=='__main__':unittest.main()
