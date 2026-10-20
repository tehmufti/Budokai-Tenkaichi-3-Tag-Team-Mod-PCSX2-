"""View grace (p94): one shared presentation never flashes back to split screen for an update or two.

Live (BT3 USA, 2P versus, hidden rig): Goku's ultimate activation (264) ran its own camera, which stopped two
updates before the hit phase's camera (303/315) started; both views went back to two halves and the split HUD
for those frames, then returned to the shared view. An extra's transformation did the same mid close-up.
"""
# Native execution tests use only the developer's own fixture helpers.
import importlib.util as _TestSpec
import unittest as _TestUnit
if not all(_TestSpec.find_spec(_name) for _name in ('test_special_pause', 'test_ultimate_cinematics', 'legacy_fixtures')):
    raise _TestUnit.SkipTest('The developer cinematic fixture helpers are required for view-grace tests')
import struct
import unittest

import cinematic_policy as p
import test_cinematic_policy as base
from test_ultimate_cinematics import captured_spirit_bomb, coop_selector, run, updated_actors
from legacy_fixtures import setUpModule, tearDownModule  # noqa: F401


def graced(machine):
    for at, data in p.program(participants=True, form_gate=True, view_grace=True)+p.hooks():
        machine.write(at, data)
    return machine


def ungraced(machine):
    for at, data in p.program(participants=True, form_gate=True)+p.hooks():
        machine.write(at, data)
    return machine


def gap(c):
    """The camera of the proven presentation stops; no actor-side proof is left; the owner stays in its action."""
    cine = c.u(c.r[28]-22180)
    c.w(cine+704, 0); c.w(cine+776, 0); c.w(cine+812, 0); c.w(cine+768, 0); c.w(cine+772, 0)
    c.w(base.arbitration.DIRECTOR, 0)
    for actor in c.actors:
        c.w(actor+3732, 0); c.w(actor+3736, 0)
        for offset in p.PRIORITY_FLAG_BYTES + p.ULTIMATE_FLAG_BYTES:
            c.write(actor+offset, b'\0')
    return cine


class ViewGraceTests(unittest.TestCase):
    def proven(self, install=graced):
        c = install(captured_spirit_bomb(True))
        caster = c.actors[0]
        self.assertEqual(run(c, p.ULTIMATE_OWNER), caster)
        return c, caster

    def test_a_short_camera_gap_inside_an_ultimate_keeps_one_view_and_holds_nobody(self):
        c, caster = self.proven()
        self.assertEqual(c.u(p.CONTROL+p.GRACE_OWNER), 1)
        self.assertEqual(c.u(p.CONTROL+p.GRACE_KIND), 1)
        gap(c)
        run(c, p.pause.hitstop12.ENTRY)           # one update: prepare spends one grace update, latch dropped
        self.assertEqual(c.u(p.CONTROL+p.LATCH_OWNER), 0)
        self.assertEqual(run(c, p.ULTIMATE_OWNER), caster)
        self.assertEqual(c.r[3], p.GRACE_ANSWER)
        self.assertEqual(c.u(p.CONTROL+p.ULTIMATE_MEMBERS), (1 << len(c.actors))-1)
        c.w(p.CONTROL+p.HOLD_AGE, 40)
        run(c, p.pause.hitstop12.ENTRY)
        self.assertEqual(updated_actors(c), c.actors)  # the stop holds nobody for a graced view
        self.assertEqual(c.u(p.CONTROL+p.HOLD_AGE), 0)  # and counts it as an update with no presentation
        result, calls = coop_selector(c)
        self.assertEqual(result, 1)                    # one view, not two halves
        self.assertNotIn(('cinematic_bind', c.u(c.r[28]-22180), 1), calls)  # the stopped camera is not shown

    def test_the_old_emission_flashes_back_to_two_views(self):
        c, caster = self.proven(ungraced)
        gap(c)
        run(c, p.pause.hitstop12.ENTRY)
        self.assertEqual(run(c, p.ULTIMATE_OWNER), 0)
        self.assertEqual(coop_selector(c)[0], 0)

    def test_grace_is_bounded_and_ends_with_the_move(self):
        for reason in ('expired', 'ordinary', 'dead', 'battle_over', 'other_kind', 'hit_phase', 'camera', 'arena',
                       'unchecked'):
            c, caster = self.proven()
            gap(c)
            if reason == 'expired':
                for _ in range(p.GRACE_UPDATES):
                    run(c, p.pause.hitstop12.ENTRY)
            else:
                run(c, p.pause.hitstop12.ENTRY)
            if reason == 'ordinary': c.w(caster+2376, 11)
            if reason == 'dead': c.w(caster+0x9E4+164*c.u(caster+0x994), 0)
            if reason == 'battle_over': c.w(p.result.RESULT, 1)
            if reason == 'other_kind': c.w(caster+2376, 236)
            if reason == 'hit_phase': c.w(caster+2376, 288 if c.u(caster+2376) != 288 else 264)  # a new phase: its own proof decides
            if reason == 'camera': c.w(c.u(c.r[28]-22180)+812, 1)    # a running camera is the ordinary logic's
            if reason == 'arena': c.w(p.continuity.SCENE_FLAGS, c.u(p.continuity.SCENE_FLAGS) | 0x2000)
            if reason == 'unchecked': c.w(p.CONTROL+16, 0)
            self.assertEqual(run(c, p.GRACE, 1), 0, reason)
            if reason in ('hit_phase', 'camera', 'unchecked'):
                continue
            self.assertEqual(run(c, p.ULTIMATE_OWNER), 0, reason)
            self.assertEqual(c.u(p.CONTROL+p.ULTIMATE_MEMBERS), 0, reason)
            if reason not in ('battle_over', 'arena'):
                self.assertEqual(coop_selector(c)[0], 0, reason)

    def test_a_new_proof_rearms_and_the_grace_never_outlives_its_budget(self):
        c, caster = self.proven()
        gap(c)
        answers = []
        for _ in range(p.GRACE_UPDATES+2):
            run(c, p.pause.hitstop12.ENTRY)
            answers.append(run(c, p.ULTIMATE_OWNER))
        self.assertEqual(answers, [caster]*(p.GRACE_UPDATES-1)+[0]*3)
        self.assertGreaterEqual(c.u(p.CONTROL+p.GRACE_USED), p.GRACE_UPDATES-1)

    def transform(self, c, physical=1, action=236):
        actor = c.actors[physical]
        c.w(actor+2376, action)
        c.write(actor+p.PRIORITY_FLAG_BYTES[0],
                bytes([c.read(actor+p.PRIORITY_FLAG_BYTES[0], 1)[0] | p.PRIORITY_FLAG_BIT]))
        return actor

    def form_machine(self, install=graced):
        c = install(captured_spirit_bomb(False))
        for actor in c.actors:
            c.w(actor+2376, 11)
        c.w(p.CONTROL+20, 1); c.w(p.CONTROL+p.TRANSFORM_VIEW, 1)
        return c

    def test_a_transformation_that_loses_its_proof_for_an_update_keeps_one_view(self):
        c = self.form_machine()
        actor = self.transform(c)
        self.assertEqual(run(c, p.SHARED_FORM), actor)
        self.assertEqual(c.u(p.CONTROL+p.GRACE_KIND), 2)
        # The priority flag drops for an update (the extra's reload), the action stays in the form family.
        c.write(actor+p.PRIORITY_FLAG_BYTES[0], bytes([c.read(actor+p.PRIORITY_FLAG_BYTES[0], 1)[0] & ~p.PRIORITY_FLAG_BIT]))
        run(c, p.pause.hitstop12.ENTRY)
        self.assertEqual(run(c, p.SHARED_FORM), actor)
        self.assertEqual(c.r[3], p.GRACE_ANSWER)
        self.assertEqual(c.u(p.CONTROL+p.ULTIMATE_MEMBERS), (1 << len(c.actors))-1)
        # The form moves on inside its family (237): still the same close-up.
        c.w(actor+2376, 237)
        self.assertEqual(run(c, p.SHARED_FORM), actor)
        self.assertEqual(coop_selector(c)[0], 1)
        # The form ends: two views at once.
        c.w(actor+2376, 11)
        self.assertEqual(run(c, p.SHARED_FORM), 0)
        self.assertEqual(coop_selector(c)[0], 0)

    def test_each_half_preference_never_arms_a_grace(self):
        c = self.form_machine()
        c.w(p.CONTROL+p.TRANSFORM_VIEW, 0)
        actor = self.transform(c)
        self.assertEqual(run(c, p.SHARED_FORM), 0)
        self.assertEqual(c.u(p.CONTROL+p.GRACE_LEFT), 0)
        self.assertEqual(coop_selector(c)[0], 0)

    def test_the_13_6_emission_upgrades_to_the_graced_one_and_nothing_else_is_accepted(self):
        import test_special_pause as old
        ram = bytearray(old.RAM); base.apply(ram, p.pause.build_memory(ram, mode='none'))
        base.apply(ram, p.build_memory(ram, ultimate=True))
        self.assertTrue(any(ram[p.GRACE:p.GRACE+16]))
        self.assertEqual(p.build_memory(ram, ultimate=True)['blocks'], [])
        # Rebuild exactly the 13.6 emission: no GRACE, and its PREPARE/ULTIMATE_OWNER/SHARED_FORM.
        current = dict(p.program(participants=True, form_gate=True, view_grace=True))
        ram[p.GRACE:p.GRACE+len(current[p.GRACE])] = bytes(len(current[p.GRACE]))
        for address, data in p.program(participants=True, form_gate=True):
            ram[address:address+len(current[address])] = bytes(len(current[address]))
            ram[address:address+len(data)] = data
        p.validate_memory(ram)
        manifest = p.build_memory(ram, ultimate=True)
        self.assertEqual(sorted(b['address'] for b in manifest['blocks']),
                         sorted([p.PREPARE, p.SHARED_FORM, p.ULTIMATE_OWNER, p.ULTIMATE_STOP, p.GRACE]))
        base.apply(ram, manifest)
        self.assertEqual(p.build_memory(ram, ultimate=True)['blocks'], [])
        ram[p.GRACE+12] ^= 1
        with self.assertRaises(ValueError):
            p.validate_memory(ram)

    def test_grace_routine_preserves_callee_saved_registers(self):
        c, caster = self.proven()
        gap(c)
        run(c, p.pause.hitstop12.ENTRY)
        for r in range(16, 24):
            c.r[r] = 0x1111*(r+1)
        c.r[29] = 0x01F00000
        self.assertEqual(run(c, p.GRACE, 1), caster)
        self.assertEqual([c.r[r] for r in range(16, 24)], [0x1111*(r+1) for r in range(16, 24)])
        self.assertEqual(c.r[29], 0x01F00000)

    def test_a_split_tag_rush_is_never_a_shared_ultimate(self):
        """p94 G2: the tag approach dash borrows native 261/285; in the tag's split mode it owns no shared view."""
        import tag_rush_camera as tag_camera
        for shared in (0, 1):
            c = graced(captured_spirit_bomb(True))
            caster = c.actors[0]
            c.write(tag_camera.CONTROL, struct.pack('<7I', tag_camera.MAGIC, c.u(c.r[28]-22364), c.u(p.core.MODE+4),
                                                    1, 1, 0, shared))
            self.assertEqual(run(c, p.ULTIMATE_OWNER), caster if shared else 0, shared)
            self.assertEqual(c.u(p.CONTROL+p.ULTIMATE_MEMBERS) != 0, bool(shared), shared)
        # No tag presentation: the ordinary owner, as before.
        c = graced(captured_spirit_bomb(True))
        self.assertEqual(run(c, p.ULTIMATE_OWNER), c.actors[0])


if __name__ == '__main__':
    unittest.main()
