"""Consent, meter and generated coordinator boundary checks (no emulator)."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import unittest
from dataclasses import replace
import tag_team_rush as tag


def fighters():
    return [tag.Fighter(0,0,1),tag.Fighter(1,1,0),tag.Fighter(2,0,1),tag.Fighter(3,1,0)]


class ConsentTests(unittest.TestCase):
    def ready(self):
        c=tag.Coordinator(charge_seconds=1,hz=10)
        for _ in range(10):c.tick(fighters())
        return c

    def test_defaults_are_real_active_seconds_and_not_render_frames(self):
        c=tag.Coordinator()
        for _ in range(25*tag.ACTOR_HZ-1):c.tick(fighters())
        self.assertEqual(c.charge,dict.fromkeys(range(4),c.limit-1))
        c.tick(fighters(),paused=True);self.assertEqual(c.charge,dict.fromkeys(range(4),c.limit-1))
        c.tick(fighters());self.assertEqual(c.charge,dict.fromkeys(range(4),c.limit))
        self.assertEqual(c.damage,15000)

    def test_human_consent_requires_another_edge_and_same_target(self):
        c=self.ready();self.assertIsNone(c.tick(fighters(),[0,2]))
        for _ in range(3):self.assertIsNone(c.tick(fighters(),[0,2]))
        c.tick(fighters(),[0]);self.assertEqual(c.tick(fighters(),[0,2]),(0,2,1,'dual_beam'))
        self.assertEqual(c.charge[0],0);self.assertIsNone(c.tick(fighters(),[0,2]))

    def test_giant_form_in_any_role_invalidates_pending_consent_without_spending(self):
        for index in (0,2,1):
            c=self.ready();fs=fighters();c.tick(fs,[0]);fs[index]=replace(fs[index],giant=True)
            self.assertIsNone(c.tick(fs,[2]));self.assertEqual(c.charge[0],c.limit)
            self.assertEqual(c.charge[2],c.limit)

    def test_refused_enemies_different_target_busy_dead_and_absent(self):
        for changed in (dict(target=3),dict(busy=True),dict(alive=False),dict(present=False)):
            c=self.ready();fs=fighters();fs[2]=replace(fs[2],**changed)
            c.tick(fs,[0]);c.tick(fs,[1,2]);self.assertIsNone(c.active)
            self.assertEqual(c.charge[0],c.limit)

    def test_cpu_accepts_only_eligible_same_target_and_keeps_variant(self):
        c=self.ready();fs=fighters();fs[2]=replace(fs[2],cpu=True,ki=False)
        c.tick(fs,[0]);self.assertEqual(c.tick(fs),(0,2,1,'mixed'))
        c.finish();self.assertIsNone(c.active)

    def test_offer_expires_without_spending(self):
        c=self.ready();c.tick(fighters(),[0])
        for _ in range(c.ttl):c.tick(fighters())
        self.assertNotIn(0,c.offers);self.assertEqual(c.charge[0],c.limit)

    def test_target_change_or_death_cancels(self):
        for change in (dict(target=3),dict(alive=False)):
            c=self.ready();fs=fighters();c.tick(fs,[0]);fs[0]=replace(fs[0],**change)
            c.tick(fs,[2]);self.assertIsNone(c.active);self.assertNotIn(0,c.offers)

    def test_training_full_never_applies_to_normal_battle(self):
        c=tag.Coordinator(training_full=True)
        c.tick(fighters());self.assertEqual(c.charge,dict.fromkeys(range(4),1))
        c.tick(fighters(),training=True);self.assertEqual(c.charge,dict.fromkeys(range(4),c.limit))

    def test_incomplete_director_ffa_or_disabled_does_not_arm(self):
        for kw in (dict(ready=False),dict(teams=False),dict(enabled=False)):
            c=self.ready();c.tick(fighters(),[0],**kw);c.tick(fighters(),[2],**kw)
            self.assertIsNone(c.active);self.assertEqual(c.offers,{})

    def test_uneven_single_enemy_and_short_roster(self):
        c=self.ready();fs=fighters()[:3]
        c.tick(fs,[0]);self.assertEqual(c.tick(fs,[2])[:3],(0,2,1))
        c=tag.Coordinator(charge_seconds=1,hz=10)
        for _ in range(50):c.tick(fighters()[:2])
        self.assertEqual(c.charge,{0:0,1:0})

    def test_only_the_two_participants_spend_their_own_meter(self):
        fs=fighters()+[tag.Fighter(4,0,1),tag.Fighter(5,1,0)]
        c=tag.Coordinator(charge_seconds=1,hz=10)
        for _ in range(c.limit):c.tick(fs)
        c.tick(fs,[0]);self.assertEqual(c.tick(fs,[2])[:3],(0,2,1))
        self.assertEqual(c.charge,{0:0,1:10,2:0,3:10,4:10,5:10})
        c.finish();c.tick(fs)
        self.assertEqual((c.charge[0],c.charge[2],c.charge[4]),(1,1,10))

    def test_an_undercharged_teammate_cannot_accept_even_as_cpu(self):
        for cpu in (False,True):
            c=self.ready();c.charge[2]=0
            fs=fighters();fs[2]=replace(fs[2],cpu=cpu)
            c.tick(fs,[0]);self.assertIsNone(c.tick(fs,[2]))
            self.assertEqual(c.charge[0],c.limit)

    def test_dead_or_consumed_fighter_does_not_charge_from_other_teammates(self):
        for missing in (dict(alive=False),dict(present=False)):
            fs=fighters()+[tag.Fighter(4,0,1)]
            fs[0]=replace(fs[0],**missing)
            c=tag.Coordinator();c.tick(fs)
            self.assertEqual((c.charge[0],c.charge[2],c.charge[4]),(0,1,1))

    def test_guest_programs_fit_reservations(self):
        for builder in (tag.gate_code,tag.eligible_code,tag.input_code,tag.tick_code):
            self.assertTrue(builder())
        self.assertTrue(tag.frame_code(0x100000))


if __name__=='__main__':unittest.main()
