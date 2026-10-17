"""Who is targeting you (lockon_threat): hit memory, the per-human threat record, switching to your attacker and the
marks, in the guest instruction harness of test_lockon_select (the queue's lock-off emission, the unchanged lock-off
programs and lockon_select, with lockon_threat's wrappers in front), plus its install and the validator chains.
"""
import copy
import random
import re
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

import battle_mode_policy as modes
import cpu_retaliation as retaliation
import display_settings as display
import ffa_targeting as ffa
import fresh_team_combat as core
import guest_healthbars as bars
import guest_killfeed as feed
import lockoff_target as off
import lockon_queue as q
import lockon_select as sel
import lockon_threat as threat
import mod_settings
import multi_contact as mc
import quad_viewports as views
import team_participation as part
from input_script import RECORDS
from native_map import A
from prototype import ROOT
from regional import DISPLAY_H, Y_ORIGIN
import test_lockon_select as base
from test_lockon_select import (ACTORS, CAM, GP, L3, MANAGER, MODELS, LEFT, RIGHT, make, frame, place, target, row, own,
                                FIXTURE_FFA, FIXTURE_REMATCH, IMAGE_MODE)

FEED_CLOCK = feed.CONTROL+12
FRAMES = q.CONTROL+q.FIELDS['frames']
ACC_STOP = ffa.ACCUMULATE
PENDING = q.CONTROL+q.layout()[0]['pending']
SHIELD = 0x100            # a lock-off button other than the switch button


def settings(**values):
    out = {'lockon_switch_button': 'l3', 'lockon_hold_seconds': 0.0}
    out.update(values)
    return mod_settings.validate_settings(out)


def install(c, switch='tap_during_warning', marks='marks_and_warning', count=6, acc_tail=ACC_STOP, render_tail=None,
            quad=0, clock=1000):
    for p, b in threat.code_parts(): c.write(p, b)
    render = 0 if marks == 'hide' else (sel.MARKER if render_tail is None else render_tail)
    for p, b in threat.data_blocks(MANAGER, threat.SWITCH[switch], threat.MARK_MODES[marks], acc_tail, render, quad):
        c.write(p, b)
    c.write(off.INPUT, threat.jump(threat.INPUT3)); c.write(off.APPLY, threat.jump(threat.APPLY3))
    c.write(feed.CONTROL, struct.pack('<4I', 1, MANAGER, count, clock))
    return c


def machine(switch='tap_during_warning', marks='marks_and_warning', **kwargs):
    count = kwargs.get('count', 6)
    return install(make(**kwargs), switch, marks, count=count)


def update(c, raw=0, n=1, seat=0, words=None):
    """One game update: the kill-feed clock ticks, the native poller publishes the pads, the queue runs."""
    for _ in range(n):
        c.w(FEED_CLOCK, c.u(FEED_CLOCK)+1)
        for s, word in (words or {seat: raw}).items(): c.w(RECORDS+448*s+328, word)
        frame(c)


def tap(c, seat=0, button=L3, hold=1):
    update(c, button, hold, seat=seat); update(c, 0, seat=seat)
    return target(c, seat)


def hit(c, victim, attacker, damage, stop=ACC_STOP):
    """The accumulator entry, as cpu_retaliation's damage call reaches it; returns where execution continued."""
    c.r[4], c.r[5], c.r[6], c.r[7] = victim, attacker & 0xFFFFFFFF, damage & 0xFFFFFFFF, 0x7777
    c.r[29] = 0x1FFFF00; c.r[31] = 0xFEED0000
    for r in range(16, 24): c.r[r] = 0x1000+r
    pc = c.run(retaliation.ACCUMULATE, stops=(stop, retaliation.ACCUMULATE+8))
    return pc


def rec(c, seat=0, field=0): return c.u(threat.ROWS+threat.STRIDE*seat+field)
def cell(c, victim, attacker): return struct.unpack('<2I', c.read(threat.CELLS+threat.CELL_ROW*victim+8*attacker, 8))
def tcount(c, name): return c.u(threat.CONTROL+threat.FIELDS[name])
def act(c, i, action): c.w(ACTORS[i]+0x948, action)


def with_accumulator(c):
    """The live entry: cpu_retaliation ACCUMULATE redirected to the dynamic NPC policy, then to HITLOG."""
    c.write(retaliation.ACCUMULATE, threat.jump(threat.HITLOG))
    return c


# ---------------------------------------------------------------------------------------------- hit memory
class HitLogTests(unittest.TestCase):
    def setUp(self):
        self.c = with_accumulator(machine())

    def test_last_and_cell_are_written_and_execution_continues_at_the_accumulator(self):
        c = self.c; clock = c.u(FEED_CLOCK)
        self.assertEqual(hit(c, 0, 3, 120), ACC_STOP)
        self.assertEqual(struct.unpack('<3I', c.read(threat.LAST, 12)), (3, clock+1, 120))
        self.assertEqual(cell(c, 0, 3), (clock+1, 120))
        self.assertEqual(tcount(c, 'hits'), 1)
        self.assertEqual((c.r[4], c.r[5], c.r[6], c.r[7], c.r[29], c.r[31]), (0, 3, 120, 0x7777, 0x1FFFF00, 0xFEED0000))
        self.assertEqual(c.r[16:24], [0x1000+r for r in range(16, 24)])
        self.assertEqual(struct.unpack('<I', c.read(threat.LAST+16, 4))[0], 0xFFFFFFFF, 'other victims untouched')

    def test_sum_grows_inside_the_window_restarts_after_it_and_saturates(self):
        c = self.c; clock = c.u(FEED_CLOCK)
        hit(c, 0, 3, 100); c.w(FEED_CLOCK, clock+threat.SUM_WINDOW-1); hit(c, 0, 3, 50)
        self.assertEqual(cell(c, 0, 3), (clock+threat.SUM_WINDOW, 150), 'chained within the window')
        c.w(FEED_CLOCK, clock+2*threat.SUM_WINDOW-1); hit(c, 0, 3, 7)
        self.assertEqual(cell(c, 0, 3), (clock+2*threat.SUM_WINDOW, 7), 'the window is measured from the last hit')
        for _ in range(3): hit(c, 0, 3, 400000)
        self.assertEqual(cell(c, 0, 3)[1], threat.SUM_CAP)
        hit(c, 0, 3, 0x7FFFFFFF); self.assertEqual(cell(c, 0, 3)[1], threat.SUM_CAP, 'no wrap')

    def test_unknown_self_out_of_range_non_positive_and_foreign_hits_are_ignored_but_continue(self):
        c = self.c
        before = bytes(c.read(threat.LAST, 0x580))
        for victim, attacker, damage in ((0, -1, 50), (3, 3, 50), (6, 1, 50), (0, 6, 50), (0, 3, 0), (0, 3, -5)):
            self.assertEqual(hit(c, victim, attacker, damage), ACC_STOP, (victim, attacker, damage))
        self.assertEqual(bytes(c.read(threat.LAST, 0x580)), before); self.assertEqual(tcount(c, 'hits'), 0)
        for field, value in ((0, 0x12345678), (4, MANAGER+4)):
            d = with_accumulator(machine()); d.w(threat.CONTROL+field, value)
            self.assertEqual(hit(d, 0, 3, 50), ACC_STOP); self.assertEqual(cell(d, 0, 3), (0, 0), field)

    def test_friendly_fire_is_logged_but_never_warns(self):
        c = self.c; hit(c, 0, 2, 300); self.assertEqual(cell(c, 0, 2)[1], 300)
        update(c); self.assertEqual(rec(c, 0, threat.ATK) & 4, 0, 'consumers filter allies')

    def test_trampoline_form_runs_the_original_prologue_then_the_rest(self):
        c = machine(); original = retaliation.accumulate_code()[:8]
        c.write(threat.TRAMPOLINE, threat.trampoline(original))
        c.w(threat.CONTROL+threat.FIELDS['acc_tail'], threat.TRAMPOLINE)
        with_accumulator(c)
        self.assertEqual(hit(c, 0, 3, 90), retaliation.ACCUMULATE+8)
        self.assertEqual(c.r[29], 0x1FFFF00-0x50, 'the original prologue ran: its frame and its s0 save')
        self.assertEqual(c.u(c.r[29]), 0x1010); self.assertEqual(cell(c, 0, 3)[1], 90)
        self.assertEqual(struct.unpack('<2I', original), (0x27BDFFB0, 0xFFB00000))

    def test_no_tail_returns_to_the_caller(self):
        c = with_accumulator(machine()); c.w(threat.CONTROL+threat.FIELDS['acc_tail'], 0)
        self.assertEqual(hit(c, 0, 3, 10), 0xFEED0000)


# ---------------------------------------------------------------------------------------------- the record
class RecordTests(unittest.TestCase):
    """TGT/ATK/PICK: one record per human per update."""
    def masks(self, c, seat=0):
        update(c); return rec(c, seat, threat.TGT), rec(c, seat, threat.ATK)

    def test_targeting_you_enemies_only_and_human_enemies_only_while_locked(self):
        c = machine(targets=[1, 0, 0, 0, 0, 2])               # 1 and 3 (enemies) and 2/4 (allies) target the human
        self.assertEqual(self.masks(c), (0b1010, 0))
        for address, value, name in ((ACTORS[3]+0x9E4, 0, 'dead'), (part.CONTROL+12, 0x37, 'absent'),
                                     (part.CONTROL+16, 1 << 3, 'consumed')):
            d = machine(targets=[1, 0, 0, 0, 0, 2]); d.w(address, value)
            self.assertEqual(self.masks(d), (0b0010, 0), name)
        c = machine(humans=(0, 1), targets=[1, 0, 1, 0, 1, 2])
        self.assertEqual(self.masks(c)[0], 0b1010, 'a locked human enemy targets you')
        c.w(row(c, 1)+off.OFF, 1)
        self.assertEqual(self.masks(c)[0], 0b1000, 'an unlocked human enemy does not')

    def test_attack_action_boundaries(self):
        for action, attacking in ((67, False), (68, True), (191, True), (192, False), (252, False), (253, True),
                                  (315, True), (316, False), (11, False)):
            c = machine(targets=[1, 0, 1, 0, 1, 2]); act(c, 3, action)
            self.assertEqual(self.masks(c), (0b1010, 0b1000 if attacking else 0), action)

    def test_an_attack_on_someone_else_is_no_warning(self):
        c = machine(targets=[1, 0, 1, 2, 1, 2]); act(c, 3, 100)
        self.assertEqual(self.masks(c), (0b0010, 0))

    def test_live_projectile_rows_warn_stale_ones_and_bad_owners_do_not(self):
        def shots(c, rows, epoch=7):
            c.write(mc.CONTROL, struct.pack('<I', mc.MAGIC)); c.w(mc.CONTROL+60, epoch)
            for k, (effect, owner, seen) in enumerate(rows):
                c.write(mc.SHOT_ROWS+0x100*k, struct.pack('<2I', effect, owner)); c.w(mc.SHOT_ROWS+0x100*k+24, seen)
            return c
        c = shots(machine(targets=[1, 0, 1, 0, 1, 2]), [(0x1234, 3, 7)])
        self.assertEqual(self.masks(c), (0b1010, 0b1000))
        self.assertEqual(self.masks(shots(machine(targets=[1, 0, 1, 0, 1, 2]), [(0x1234, 3, 6)])), (0b1010, 0))
        self.assertEqual(self.masks(shots(machine(targets=[1, 0, 1, 0, 1, 2]), [(0, 3, 7)])), (0b1010, 0))
        self.assertEqual(self.masks(shots(machine(targets=[1, 0, 1, 0, 1, 2]), [(0x1234, 40, 7), (0x99, 6, 7)])),
                         (0b1010, 0))
        c = shots(machine(targets=[1, 0, 1, 0, 1, 2]), [(0x1234, 3, 7)]); c.w(mc.CONTROL, 0)
        self.assertEqual(self.masks(c), (0b1010, 0), 'no projectile service, no projectile rule')

    def test_a_hit_warns_for_hit_window_updates_since_the_record_began(self):
        c = with_accumulator(machine(targets=[1, 0, 1, 2, 1, 2])); update(c)
        hit(c, 0, 5, 200)                                    # 5 targets an ally, but hit you
        for k in range(1, threat.HIT_WINDOW):                # now - when = k
            self.assertEqual(self.masks(c)[1], 0b100000, k)
        self.assertEqual(self.masks(c)[1], 0, f'{threat.HIT_WINDOW} updates later')
        c = with_accumulator(machine(targets=[1, 0, 1, 2, 1, 2])); update(c); hit(c, 0, 5, 200)
        c.w(FRAMES, c.u(FRAMES)+3)                            # a gap in this human's updates: a new record
        self.assertEqual(self.masks(c)[1], 0, 'a hit before the record began never warns')

    def test_pick_most_recent_hitter_else_nearest_attacker_never_your_target_while_locked(self):
        places = [(256, 224, 0), (300, 224, 0), (40, 224, 0), (262, 224, 0), (40, 224, 0), (400, 224, 0)]
        c = with_accumulator(machine(positions=places, targets=[1, 0, 1, 0, 1, 0]))
        for j in (1, 3, 5): act(c, j, 100)
        update(c); self.assertEqual(rec(c, 0, threat.PICK), 4, 'nearest attacker that is not your target (3)')
        hit(c, 0, 5, 10); update(c); self.assertEqual(rec(c, 0, threat.PICK), 6, 'a hitter beats a nearer attacker')
        hit(c, 0, 3, 10); update(c); self.assertEqual(rec(c, 0, threat.PICK), 4, 'the most recent hitter')
        hit(c, 0, 1, 10); update(c); self.assertEqual(rec(c, 0, threat.PICK), 4, 'your own target never, while locked')
        c.w(row(c)+off.OFF, 1); update(c); self.assertEqual(rec(c, 0, threat.PICK), 2, 'unlocked: it is allowed')
        d = with_accumulator(machine(positions=places, targets=[1, 0, 1, 0, 1, 0]))
        hit(d, 0, 5, 10); hit(d, 0, 3, 10); update(d)
        self.assertEqual(rec(d, 0, threat.PICK), 4, 'same update: the lower slot')
        self.assertEqual(rec(d, 0, threat.PICK_LATCH), 4); self.assertEqual(rec(d, 0, threat.PICK_WHEN), d.u(FEED_CLOCK)+1)


# ---------------------------------------------------------------------------------------------- switching
class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.places = [(256, 224, 0), (300, 224, 0), (40, 224, 0), (262, 224, 0), (40, 224, 0), (400, 224, 0)]

    def attacked(self, **kwargs):
        kwargs.setdefault('positions', self.places); kwargs.setdefault('targets', [1, 0, 1, 0, 1, 2])
        c = machine(**kwargs); act(c, 3, 100); return c

    def test_a_tap_during_a_warning_switches_to_the_attacker(self):
        c = self.attacked(); update(c)
        self.assertEqual(tap(c), 3)
        self.assertEqual((tcount(c, 'taps'), tcount(c, 'applied')), (1, 1))
        self.assertEqual(c.u(q.CONTROL+q.FIELDS['switches']), 1); self.assertEqual(c.u(q.CONTROL+q.FIELDS['per_actor']), 1)
        self.assertEqual(c.u(own(c)+sel.WATCH), 4, 'lockon_select watches the new target')
        self.assertEqual((rec(c, 0, threat.REQ), rec(c, 0, threat.REQ_SRC)), (0, 0))

    def test_a_tap_without_a_warning_cycles_exactly_as_lockon_select(self):
        c = machine(positions=self.places, targets=[1, 0, 1, 0, 1, 0])
        plain = make(positions=self.places, targets=[1, 0, 1, 0, 1, 0])
        for _ in range(4):
            self.assertEqual(tap(c), base.tap(plain))
        self.assertEqual(tcount(c, 'taps'), 0)

    def test_grace_after_the_warning_ends(self):
        # The press must come less than TAP_GRACE updates after the last warning update.
        for gap, expected in ((threat.TAP_GRACE-1, 3), (threat.TAP_GRACE, None)):
            c = self.attacked(); update(c); act(c, 3, 11); update(c, 0, gap-1)
            plain = make(positions=self.places, targets=[1, 0, 1, 0, 1, 2])
            self.assertEqual(tap(c), expected if expected is not None else base.tap(plain), gap)

    def test_the_press_latches_the_attacker_for_any_hold_time(self):
        for hold in (1, 15):
            c = self.attacked(on_threshold=hold, off_button=SHIELD); update(c)
            update(c, L3); act(c, 3, 11)                    # pressed during the warning, which then ends
            update(c, L3, hold+20)                          # held well past the grace
            update(c, 0); self.assertEqual(target(c), 3, hold)
        c = self.attacked(on_threshold=15, off_button=SHIELD); update(c); act(c, 3, 11); update(c, 0, 20)
        update(c, L3, 20); update(c, 0)
        plain = make(positions=self.places, targets=[1, 0, 1, 0, 1, 2], on_threshold=15, off_button=SHIELD)
        base.press(plain, L3, 20); base.press(plain, 0)
        self.assertEqual(target(c), target(plain), 'pressed after the grace: the ordinary switch')

    def test_a_short_press_below_the_hold_time_does_nothing(self):
        c = self.attacked(on_threshold=15, off_button=SHIELD); update(c); update(c, L3, 3); update(c, 0, 3)
        self.assertEqual((target(c), tcount(c, 'taps')), (1, 0))

    def test_never_mode_always_cycles(self):
        c = self.attacked(switch='never'); update(c)
        plain = make(positions=self.places, targets=[1, 0, 1, 0, 1, 2]); act(plain, 3, 100)
        self.assertEqual(tap(c), base.tap(plain)); self.assertEqual(tcount(c, 'taps'), 0)

    def test_unlocked_tap_during_a_warning_relocks_onto_the_attacker(self):
        c = self.attacked(off_button=SHIELD); c.w(row(c)+off.OFF, 1); update(c)
        c.calls.clear(); self.assertEqual(tap(c), 3)
        self.assertEqual((c.u(row(c)+off.OFF), c.u(row(c)+off.QUIET) <= 2), (0, True))
        self.assertIn(('set', ACTORS[0], 5), c.calls)

    def test_a_tap_whose_attacker_is_already_your_target_switches_in_order(self):
        c = self.attacked(); update(c, 0, 2)
        update(c, L3)                                       # latched: 3
        c.w(core.TABLE, 3)                                  # the stick already took 3
        update(c, 0)
        plain = make(positions=self.places, targets=[3, 0, 1, 0, 1, 2])
        self.assertEqual(target(c), base.tap(plain)); self.assertEqual(tcount(c, 'tap_fallbacks'), 1)

    def test_an_invalid_tap_falls_back_to_the_ordinary_switch(self):
        c = self.attacked(); update(c); update(c, L3); c.w(ACTORS[3]+0x9E4, 0); update(c, 0)
        plain = make(positions=self.places, targets=[1, 0, 1, 0, 1, 2]); plain.w(ACTORS[3]+0x9E4, 0)
        self.assertEqual(target(c), base.tap(plain)); self.assertEqual(tcount(c, 'tap_fallbacks'), 1)

    def test_kinds_two_four_and_five_are_never_overridden(self):
        c = self.attacked(threshold=15); update(c)
        update(c, L3, 16); update(c, 0)
        self.assertEqual((c.u(row(c)+off.OFF), target(c)), (1, 1), 'the hold still unlocks during a warning')
        c = base.follow_camera(self.attacked()); update(c)
        plain = make(positions=self.places, targets=[1, 0, 1, 0, 1, 2]); act(plain, 3, 100)
        self.assertEqual(base.flick(c, RIGHT), base.flick(base.follow_camera(plain), RIGHT), 'aim')
        c = self.attacked(); update(c); c.w(ACTORS[1]+0x9E4, 0); update(c, 0, 3)
        self.assertNotEqual(target(c), 1); self.assertEqual(sel_counter(c, 'ko'), 1)
        self.assertEqual(tcount(c, 'taps'), 0)

    def test_a_latched_request_survives_paired_transform_and_cinematic_waits(self):
        camera = 0x1950000
        for name, hold, release in (('paired', lambda c: act(c, 0, 185), lambda c: act(c, 0, 11)),
                                    ('transform', lambda c: act(c, 0, 240), lambda c: act(c, 0, 11)),
                                    ('cinematic', lambda c: (c.w(0x2FEBCC, camera), c.w(camera+812, 1),
                                                             c.w(camera+768, MODELS[0])),
                                     lambda c: c.w(camera+812, 0))):
            c = self.attacked(); update(c); update(c, L3); hold(c); act(c, 3, 11); update(c, 0)
            update(c, 0, 60); self.assertEqual(target(c), 1, name)
            release(c); update(c); self.assertEqual(target(c), 3, name)


def sel_counter(c, name): return c.u(sel.CONTROL+sel.FIELDS[name])


class AutomaticTests(unittest.TestCase):
    def setUp(self):
        self.places = [(256, 224, 0), (300, 224, 0), (40, 224, 0), (262, 224, 0), (40, 224, 0), (400, 224, 0)]

    def dogpile(self, **kwargs):
        kwargs.setdefault('positions', self.places); kwargs.setdefault('targets', [1, 0, 1, 0, 1, 0])
        c = with_accumulator(machine(switch='when_hit', **kwargs)); update(c); return c

    def test_fires_at_the_damage_threshold_and_takes_the_largest_sum(self):
        c = self.dogpile()
        hit(c, 0, 3, threat.AUTO_DAMAGE-1); hit(c, 0, 5, 300); update(c); self.assertEqual(target(c), 1)
        hit(c, 0, 5, 800); hit(c, 0, 3, 1); update(c, 0, 2)
        self.assertEqual(target(c), 5, '1100 beats 1000')
        self.assertEqual((tcount(c, 'autos'), tcount(c, 'applied')), (1, 1))

    def test_cooldown_own_quiet_own_attack_unlocked_and_tap_mode_block_it(self):
        c = self.dogpile(); hit(c, 0, 3, 1500); update(c, 0, 2); self.assertEqual(target(c), 3)
        hit(c, 0, 5, 1500); update(c, 0, 2); self.assertEqual(target(c), 3, 'cooldown')
        update(c, 0, threat.AUTO_COOLDOWN); hit(c, 0, 5, 1500); update(c, 0, 2); self.assertEqual(target(c), 5)
        c = self.dogpile(); hit(c, 0, 1, 10); hit(c, 0, 3, 1500); update(c, 0, 2)
        self.assertEqual(target(c), 1, 'your own target hit you within OWN_QUIET')
        update(c, 0, threat.OWN_QUIET); hit(c, 0, 3, 1500); update(c, 0, 2); self.assertEqual(target(c), 3)
        c = self.dogpile(); act(c, 0, 100); hit(c, 0, 3, 1500); update(c, 0, 2); self.assertEqual(target(c), 1, 'attacking')
        c = self.dogpile(off_button=SHIELD); c.w(row(c)+off.OFF, 1); hit(c, 0, 3, 1500); update(c, 0, 2)
        self.assertEqual((target(c), c.u(row(c)+off.OFF)), (1, 1), 'unlocked')
        c = with_accumulator(machine(positions=self.places, targets=[1, 0, 1, 0, 1, 0])); update(c)
        hit(c, 0, 3, 5000); update(c, 0, 2); self.assertEqual(target(c), 1, 'tap mode never switches by itself')

    def test_a_waiting_request_blocks_it_and_is_never_overwritten(self):
        c = self.dogpile(); act(c, 0, 240)                  # a transformation holds the safe point
        c.w(ACTORS[1]+0x9E4, 0); update(c, 0, 3)             # the KO retarget (kind 5) waits
        self.assertNotEqual(c.u(PENDING), 0); self.assertEqual(c.u(row(c)+off.KIND), 5)
        hit(c, 0, 3, 5000); update(c, 0, 2)
        self.assertEqual(c.u(row(c)+off.KIND), 5); self.assertGreater(tcount(c, 'auto_blocked'), 0)
        act(c, 0, 11); update(c); self.assertEqual(sel_counter(c, 'ko'), 1)

    def test_a_stale_automatic_request_is_dropped(self):
        c = self.dogpile(); act(c, 0, 240); hit(c, 0, 3, 1500); update(c)
        self.assertEqual((c.u(row(c)+off.KIND), rec(c, 0, threat.REQ_SRC)), (6, 2))
        update(c, 0, threat.AUTO_STALE); act(c, 0, 11); update(c)
        self.assertEqual((target(c), tcount(c, 'auto_dropped')), (1, 1))

    def test_an_invalid_automatic_request_is_dropped(self):
        c = self.dogpile(); act(c, 0, 240); hit(c, 0, 3, 1500); update(c)
        c.w(ACTORS[3]+0x9E4, 0); act(c, 0, 11); update(c)
        self.assertEqual((target(c), tcount(c, 'auto_dropped')), (1, 1))

    def test_a_dogpile_switches_a_bounded_number_of_times(self):
        rng = random.Random(4); c = self.dogpile()
        for k in range(30*120):
            if rng.random() < 0.05: hit(c, 0, rng.choice((1, 3, 5)), rng.randint(100, 900))
            update(c)
        self.assertLessEqual(tcount(c, 'autos'), 120//5+1)
        self.assertGreaterEqual(tcount(c, 'autos'), 5, 'the dogpile does switch by itself')
        self.assertEqual(tcount(c, 'applied'), tcount(c, 'autos'), 'every automatic request applied')


# ---------------------------------------------------------------------------------------------- determinism, audit
class SimulationTests(unittest.TestCase):
    def script(self, seed):
        rng = random.Random(seed)
        return [(rng.choice((0, 0, 0, L3)), rng.choice((None, 1, 3, 5)), rng.randint(50, 900), rng.choice((11, 100, 260)))
                for _ in range(400)]

    def run_script(self, c, script):
        out = []
        for word, attacker, damage, action in script:
            if attacker is not None: hit(c, 0, attacker, damage)
            act(c, attacker or 3, action); update(c, word)
            out.append((c.u(core.TABLE), bytes(c.read(threat.ROWS, 64)), bytes(c.read(threat.CELLS, 96))))
        return out

    def test_two_simulators_agree_every_update(self):
        for seed in (1, 2):
            a = with_accumulator(machine(switch='when_hit')); b = with_accumulator(machine(switch='when_hit'))
            self.assertEqual(self.run_script(a, self.script(seed)), self.run_script(b, self.script(seed)))

    def test_never_and_hide_leave_lockon_select_exactly_as_without(self):
        places = base.ring((1, 90), (3, 30), (5, 150))
        for script in ([L3, 0]*6+[L3, L3 | RIGHT, L3, 0]*3+[L3]*16+[0, L3, 0],):
            a = base.follow_camera(machine(switch='never', marks='hide', positions=places))
            b = base.follow_camera(make(positions=places))
            for word in script:
                update(a, word); update(b, word)
                self.assertEqual([a.u(core.TABLE+4*i) for i in range(6)], [b.u(core.TABLE+4*i) for i in range(6)])
                self.assertEqual(a.read(sel.ROWS, 64), b.read(sel.ROWS, 64)); self.assertEqual(a.read(off.ROWS, 32), b.read(off.ROWS, 32))

    def test_writes_stay_inside_the_owned_state(self):
        c = with_accumulator(machine(switch='when_hit', targets=[1, 0, 1, 0, 1, 0])); act(c, 3, 100); update(c)
        allowed = [(core.TABLE, core.TABLE+48), (off.ROWS, off.ROWS+12*off.STRIDE), (sel.ROWS, sel.END),
                   (sel.CONTROL, sel.CONTROL+0x100), (q.CONTROL-0x800, q.CONTROL+0x400), (RECORDS+328, RECORDS+344),
                   (threat.CONTROL, threat.END), (FEED_CLOCK, FEED_CLOCK+4), (0x1FF0000, 0x2000000)]
        before = dict(c.memory)
        for word in (L3, 0, 0, L3, 0):
            hit(c, 0, 5, 400); update(c, word)
        changed = {a for a, v in c.memory.items() if before.get(a, 0) != v}
        stray = sorted(a for a in changed if not any(lo <= a < hi for lo, hi in allowed))
        self.assertEqual(stray, [], [hex(a) for a in stray[:8]])
        written = sorted(a for a in changed if threat.BASE <= a < threat.CONTROL)
        self.assertEqual(written, [], 'code pages are never written')


# ---------------------------------------------------------------------------------------------- the marks
def raw_projection(m):
    """Screen x, y straight from the world point; w from z (behind the camera when z <= 0), like 1210D8's raw result."""
    x, y, z, _ = struct.unpack('<4f', m.read(m.r[5], 16))
    clamp = lambda v: max(-2**31, min(2**31-1, int(v)))
    m.r[2] = int(z > 0)
    m.write(m.r[4], struct.pack('<4i', clamp((x+1792)*16), clamp((y+Y_ORIGIN)*16), 1 if z > 0 else -1, int(z)))


def margin(scale): return ((9*scale) >> 8)+3


FULL = (0, 511, 0, 447)


def size_r(rect=FULL, h=0):
    """beta.39 (lockon_select SIZE): (H*72) >> 8 sixteenths for the projected head-root extent H, clamped to the
    view height's [27/64, 78/64] sixteenths per line (no head bone in these machines: H = 0, the minimum)."""
    vh = view_size(rect)
    return min(max((h*72) >> 8, (vh*27) >> 6), (vh*78) >> 6)


def view_size(rect):
    """lockon_select.emit_view_size: min(height, 11/8 width) in lines."""
    return min(rect[3]-rect[2]+1, (11*(rect[1]-rect[0]+1)) >> 3)


def tip_distance(rect=FULL, h=0):
    """The on-screen pair's tips from the body centre (sixteenths): 0.9 r + 4 px."""
    return ((230*size_r(rect, h)) >> 8)+64


def pair_scale(rect=FULL, warn=False, h=0):
    """The pair's chevron scale (Q8): 96 + 0.28 r, x1.5 while attacking."""
    s = 96+((72*size_r(rect, h)) >> 8)
    return s+(s >> 1) if warn else s


def edge_scale(rect=FULL, warn=False):
    """A border chevron's scale: the CONTROL scale times the view height over DISPLAY_H."""
    return ((threat.EDGE_WARN_SCALE if warn else threat.EDGE_SCALE)*view_size(rect))//DISPLAY_H


def expected_mark(px, py, w, rect, warn=False, inset=None, v0=None, flag=None):
    """The spec's placement rule, independently: on screen a pair at the body centre (kept below the top inset);
    otherwise one chevron at the border point in the enemy's direction (ratio kept, sign(w) flipped, behind the camera
    in the lower half), clamped by its margin, pointing toward the border side reached. ('pair', x, y) or
    ('edge', x, y, orientation)."""
    x0, x1, y0, y1 = rect; inset = threat.TOP_INSET if inset is None else inset
    v0 = (w > 0) if v0 is None else v0; flag = (1 if w > 0 else -1) if flag is None else flag
    if v0 and w > 0 and flag >= 0 and x0 <= px <= x1 and y0 <= py <= y1:
        m = margin(pair_scale(rect, warn))
        return ('pair', px, min(max(py, y0+m+inset), y1-m))
    m = margin(edge_scale(rect, warn))
    cx, cy, hw, hh = (x0+x1) >> 1, (y0+y1) >> 1, ((x1-x0) >> 1)-m, ((y1-y0) >> 1)-m
    if hw <= 0 or hh <= 0: return None
    dx, dy = px-cx, py-cy
    while abs(dx) > 32767 or abs(dy) > 32767: dx >>= 1; dy >>= 1
    if w <= 0: dx, dy = -dx, abs(dy)+hh
    if dx == 0 and dy == 0: return None
    div = lambda n, d: (abs(n)//d)*(1 if n >= 0 else -1)
    if abs(dx)*hh >= abs(dy)*hw:
        mx, my, side = cx+(hw if dx > 0 else -hw), cy+div(dy*hw, abs(dx)), 'right' if dx > 0 else 'left'
    else:
        mx, my, side = cx+div(dx*hh, abs(dy)), cy+(hh if dy > 0 else -hh), 'down' if dy > 0 else 'up'
    return ('edge', min(max(mx, x0+m), x1-m), min(max(my, y0+m+inset), y1-m), threat.ORIENT[side])


def _xyz(x, y): return struct.pack('<2I', (x & 0xFFFF) | (y << 16), 0)


def _segment(rgba, n, eop):
    return struct.pack('<8I', 2, 0x10000000, 0xE, 0, 0x43, 0, 0, 0)+struct.pack('<8I', rgba, sel.ONE, 1, 0, n | (eop << 15),
                                                                              0x14000000, 5, 0)


def pair_packet(cx, cy, tip, scale, colour):
    """The spec's pair, built independently (sixteenths): outlines, then faces; tips either side pointing inward."""
    out = sel.ring_data()[:96]
    for k, (table, rgba) in enumerate(((sel.CHEVRONS[2], threat.OUTLINE), (sel.CHEVRONS[3], colour))):
        out += _segment(rgba, 6, k == 1)
        for x0, sign in ((cx-tip, 1), (cx+tip, -1)):
            for ux, uy in table: out += _xyz(x0+sign*((ux*scale) >> 8), cy+((uy*scale) >> 8))
    return out


def edge_packet(x, y, scale, orient, colour):
    """One chevron with its tip at (x, y) (sixteenths) pointing right/left/down/up (0..3)."""
    out = sel.ring_data()[:96]
    for k, (table, rgba) in enumerate(((sel.CHEVRONS[2], threat.OUTLINE), (sel.CHEVRONS[3], colour))):
        out += _segment(rgba, 3, k == 1)
        for ux, uy in table:
            a, b = (ux*scale) >> 8, (uy*scale) >> 8
            if orient & 1: a = -a
            dx, dy = (b, a) if orient & 2 else (a, b)
            out += _xyz(x+dx, y+dy)
        out += bytes(8)
    return out


def marks(c):
    """Decode every mark packet: ('pair', x, y, tip16, scale, colour) / ('edge', x, y, orient, scale, colour), each
    checked byte for byte against the independent builders."""
    out = []
    for packet in c.packets:
        word = lambda at: struct.unpack_from('<I', packet, at)[0]
        if len(packet) == 320:
            left, right, colour = word(96+112+64), word(96+112+64+24), word(96+112+32)
            cx, cy, tip = ((left & 0xFFFF)+(right & 0xFFFF)) // 2, left >> 16, ((right & 0xFFFF)-(left & 0xFFFF)) // 2
            guess = -((struct.unpack_from('<I', packet, 280)[0] >> 16)-cy)*256//144
            found = [s for s in range(max(1, guess-4), guess+5) if pair_packet(cx, cy, tip, s, colour) == packet]
            assert len(found) == 1, packet.hex()
            out.append(('pair', cx//16-1792, cy//16-Y_ORIGIN, tip, found[0], colour))
        elif len(packet) == 288:
            first, colour = word(96+96+64), word(96+96+32)
            x, y = first & 0xFFFF, first >> 16
            found = [(o, s) for o in range(4) for s in range(1, 1024)
                     if edge_packet(x, y, s, o, colour) == packet]
            assert len(found) == 1, packet.hex()
            out.append(('edge', x//16-1792, y//16-Y_ORIGIN, found[0][0], found[0][1], colour))
        else:
            raise AssertionError(f'unknown packet of {len(packet)} bytes')
    return out


def placed(got):
    """('pair', x, y) / ('edge', x, y, orient) of decoded marks."""
    return [g[:3] if g[0] == 'pair' else g[:4] for g in got]


class DrawTests(unittest.TestCase):
    """The marks in one, two and four views, drawn before the target ring and the bars."""
    def machine(self, humans=(0,), view=(0, 511, 0, 447), marks='marks_and_warning', **kwargs):
        places = kwargs.pop('positions', [(100, 300, 1), (256, 224, 1), (300, 200, 1), (400, 224, 1), (150, 150, 1),
                                          (60, 224, 1)])
        # Seat 0 is locked on to 5; 1 targets seat 0; 3 and 5 target others.
        kwargs.setdefault('targets', [5, 0, 3, 2, 3, 4])
        c = machine(marks=marks, positions=places, humans=humans, view=view, **kwargs)
        for p, b in ((bars.RECT, bars.rectangle_code()), (bars.TEMPLATE, bars.sprite_template()),
                     (display.SUBJECT, display.subject_code())):
            c.write(p, b)
        c.write(display.CONTROL, struct.pack('<2I', display.MAGIC, MANAGER))
        c.write(bars.CONTROL+0x80, struct.pack('<4f', 0, bars.HEAD_LIFT, 0, 0))
        c.callbacks[0x1210D8] = raw_projection
        c.callbacks[sel.MARKER] = lambda m: m.events.append('marker')
        return c

    def run_entry(self, c, entry=None):
        c.events.clear(); c.packets.clear(); c.r[31] = 0xFEED0000; c.r[29] = 0x1FFFF00
        saved = list(c.r[16:24]); c.r[2] = 0x12345678
        c.hi = 0x1111; c.lo = 0x2222
        c.run(threat.ENTRY if entry is None else entry)
        self.assertEqual((c.r[16:24], c.r[29], c.saved_matrix, c.hi, c.lo), (saved, 0x1FFFF00, [], 0x1111, 0x2222))
        return marks(c)

    def at(self, c, j, px, py, w=1):
        place(c, j, (px, py, w))

    def test_on_screen_pairs_bracket_the_body_blink_and_grow_while_attacking(self):
        c = self.machine(); self.at(c, 1, 256, 224); update(c)
        tip = tip_distance((0, 511, 0, 447)); self.assertEqual(tip, 233)
        self.assertEqual(self.run_entry(c), [('pair', 256, 224, tip, pair_scale(), threat.TARGET_COLOUR)])
        self.assertEqual(c.events, ['push', 'sprite', 'pop', 'marker'], 'marks, then the ring and bars')
        act(c, 1, 100); update(c)
        for frames in (8, 4, 12, 3):
            c.w(FRAMES, frames); c.w(threat.ROWS+threat.STAMP, frames)
            colour = threat.WARN_A if frames & threat.BLINK else threat.WARN_B
            self.assertEqual(self.run_entry(c), [('pair', 256, 224, tip, pair_scale(warn=True), colour)], frames)
        self.assertEqual((threat.WARN_A, threat.WARN_B, threat.TARGET_COLOUR), (sel.WARN_Y, sel.RED, sel.RED))
        c.w(threat.CONTROL+threat.FIELDS['marks'], 1)
        self.assertEqual(self.run_entry(c), [('pair', 256, 224, tip, pair_scale(), threat.TARGET_COLOUR)],
                         'marks only: never blinks')

    def test_the_pairs_follow_the_view_height(self):
        for rect in [r for r in views.rectangles(2)+views.rectangles(4) if r[0] == 0]:
            places = [(0, 0, 1)]*6; places[1] = ((rect[0]+rect[1])//2, (rect[2]+rect[3])//2, 1)
            c = self.machine(view=rect, positions=places); update(c)
            [got] = self.run_entry(c)
            self.assertEqual(got[3], tip_distance(rect), rect)
        self.assertEqual(tip_distance((0, 511, 0, 223)), ((230*94) >> 8)+64)
        self.assertEqual([pair_scale(r) for r in ((0, 511, 0, 447), (0, 511, 0, 223))], [149, 122])
        self.assertEqual([size_r(FULL, 10**5), pair_scale(FULL, h=10**5), tip_distance(FULL, h=10**5)], [546, 249, 554])

    def test_attackers_that_do_not_target_you_are_marked_only_with_the_warning(self):
        c = with_accumulator(self.machine()); self.at(c, 1, 256, 224); self.at(c, 3, 400, 224)
        update(c); hit(c, 0, 3, 50); update(c)
        warn = threat.WARN_A if c.u(FRAMES) & threat.BLINK else threat.WARN_B
        tip = tip_distance((0, 511, 0, 447))
        self.assertEqual(self.run_entry(c), [('pair', 256, 224, tip, pair_scale(), threat.TARGET_COLOUR),
                                             ('pair', 400, 224, tip, pair_scale(warn=True), warn)])
        c.w(threat.CONTROL+threat.FIELDS['marks'], 1)
        self.assertEqual(self.run_entry(c), [('pair', 256, 224, tip, pair_scale(), threat.TARGET_COLOUR)])

    def test_your_own_target_has_no_second_pair_where_the_ring_is_drawn(self):
        c = self.machine(targets=[1, 0, 3, 2, 3, 4]); self.at(c, 1, 256, 224); update(c)
        self.assertEqual(self.run_entry(c), [], 'the ring\'s chevrons carry it')
        c.w(threat.CONTROL+threat.FIELDS['render_tail'], display.BAR_DRAW)
        self.assertEqual(placed(self.run_entry(c)), [('pair', 256, 224)], 'no ring in this build: the pair')
        c.w(threat.CONTROL+threat.FIELDS['render_tail'], sel.MARKER)
        c.w(row(c)+off.OFF, 1); update(c)
        self.assertEqual(placed(self.run_entry(c)), [('pair', 256, 224)], 'unlocked: no ring, the pair')
        c.w(row(c)+off.OFF, 0); update(c); self.at(c, 1, -400, 224)
        self.assertEqual(placed(self.run_entry(c)), [('edge', margin(edge_scale()), 223, threat.ORIENT['left'])],
                         'off screen: no ring there, the border chevron')
        rect = views.rectangles(4)[0]
        places = [(0, 0, 1)]*6; places[1] = ((rect[0]+rect[1])//2, (rect[2]+rect[3])//2, 1)
        c = self.quad(4, rect, places, [1, 0, 1, 1, 1, 1]); update(c, words={k: 0 for k in range(4)})
        c.events.clear(); c.packets.clear(); c.r[31] = 0xFEED0000; c.r[29] = 0x1FFFF00
        c.run(threat.QUAD_LINK)
        self.assertEqual(len(marks(c)), 1, 'quad views without the indicator entry (QMARKER): the pair')
        c.w(sel.CONTROL+sel.FIELDS['quad'], 1)
        c.events.clear(); c.packets.clear(); c.r[31] = 0xFEED0000; c.r[29] = 0x1FFFF00
        c.run(threat.QUAD_LINK)
        self.assertEqual(len(marks(c)), 0, 'beta.39: QMARKER draws the ring there, whose chevrons carry it')
        c.w(sel.CONTROL+sel.FIELDS['style'], sel.STYLES['arrow'])
        c.events.clear(); c.packets.clear(); c.r[31] = 0xFEED0000; c.r[29] = 0x1FFFF00
        c.run(threat.QUAD_LINK)
        self.assertEqual(len(marks(c)), 1, 'the arrow alone: the pair again')

    def test_placement_matches_the_rule_everywhere_including_behind_and_saturated(self):
        rng = random.Random(11)
        views_ = ((0, 511, 0, 447), (0, 254, 0, 447), (257, 511, 0, 447), (0, 254, 0, 222), (257, 511, 225, 447),
                  (128, 382, 225, 447))
        cases = [(5, 5), (511, 224), (256, 0), (256, 447), (-900, 224), (1500, 224), (256, -800), (256, 2000),
                 (-50000, 30), (70000, -90000), (3_000_000, 1), (-4_000_000, -4_000_000), (300, 300)]
        for view in views_:
            for k in range(60):
                px, py = cases[k] if k < len(cases) else (rng.randint(-3000, 3000), rng.randint(-3000, 3000))
                w = rng.choice((1, 1, 0, -5))
                # A left view is human 0's (marked: 1); any other follows side 1, human 1 (marked: human 0).
                seat, marked = (1, 0) if view[0] else (0, 1)
                c = self.machine(view=view, humans=(0, 1) if view[0] else (0,),
                                 targets=[1, 2, 3, 2, 3, 4] if view[0] else [5, 0, 3, 2, 3, 4])
                place(c, seat, ((view[0]+view[1])//2, 224, 1))
                self.at(c, marked, px, py, w)
                update(c, words={0: 0, 1: 0})
                got = self.run_entry(c)
                want = expected_mark(px, py, w, view)
                self.assertEqual(placed(got), [] if want is None else [want], (view, px, py, w))
                for mark in got:
                    scale = mark[4]
                    self.assertEqual(mark[5], threat.TARGET_COLOUR)
                    self.assertEqual(scale, pair_scale(view) if mark[0] == 'pair' else edge_scale(view))
                    x, y = mark[1], mark[2]
                    self.assertTrue(view[0] <= x <= view[1] and view[2] <= y <= view[3])

    def test_the_four_borders_and_behind_the_camera(self):
        view = (0, 511, 0, 447); cx, cy = 255, 223; m = margin(threat.EDGE_SCALE); hw, hh = 255-m, 223-m
        for (px, py, w), want in (((-400, cy, 1), (cx-hw, cy, 'left')), ((900, cy, 1), (cx+hw, cy, 'right')),
                                  ((cx, -300, 1), (cx, cy-hh+threat.TOP_INSET, 'up')), ((cx, 900, 1), (cx, cy+hh, 'down'))):
            c = self.machine(); self.at(c, 1, px, py, w); update(c)
            self.assertEqual(self.run_entry(c), [('edge', want[0], want[1], threat.ORIENT[want[2]], threat.EDGE_SCALE,
                                                  threat.TARGET_COLOUR)], (px, py))
        for px, py in ((100, 100), (400, 50), (cx, cy-1), (20, 400)):
            c = self.machine(); self.at(c, 1, px, py, -3); update(c)
            [(kind, x, y, orient, _, _)] = self.run_entry(c)
            self.assertEqual(kind, 'edge'); self.assertGreaterEqual(y, cy, 'behind the camera: the lower half')
            if px == cx: self.assertEqual((x, orient), (cx, threat.ORIENT['down']))
            else: self.assertEqual(x > cx, px < cx, 'behind the camera: the other side')
        c = with_accumulator(self.machine()); self.at(c, 1, -400, cy); update(c); hit(c, 0, 1, 50); update(c)
        warn = threat.WARN_A if c.u(FRAMES) & threat.BLINK else threat.WARN_B
        m = margin(threat.EDGE_WARN_SCALE)
        self.assertEqual(self.run_entry(c), [('edge', m, cy, threat.ORIENT['left'], threat.EDGE_WARN_SCALE, warn)],
                         'a warning off screen: 2x, blinking')

    def test_top_inset_lowers_the_top_border_only(self):
        m = margin(threat.EDGE_SCALE)
        c = self.machine(); self.at(c, 1, 255, -500); update(c)
        self.assertEqual(placed(self.run_entry(c)), [('edge', 255, m+threat.TOP_INSET, threat.ORIENT['up'])], 'the default')
        from regional import screen_y
        self.assertEqual(threat.TOP_INSET, screen_y(74 if __import__('mod_settings').ADAPTER == 'BT4' else 56))
        c.w(threat.CONTROL+threat.FIELDS['top_inset'], 20)
        self.assertEqual(placed(self.run_entry(c)), [('edge', 255, m+20, threat.ORIENT['up'])])
        self.at(c, 1, -500, -400)
        self.assertEqual(expected_mark(-500, -400, 1, (0, 511, 0, 447), inset=20)[1:3], (m, m+20))
        self.assertEqual(placed(self.run_entry(c))[0][1:3], (m, m+20), 'a top-corner side chevron is lowered too')
        self.at(c, 1, 255, 900); self.assertEqual(placed(self.run_entry(c)), [('edge', 255, 223+(223-m), threat.ORIENT['down'])])
        self.at(c, 1, 255, 3)
        self.assertEqual(placed(self.run_entry(c)), [('pair', 255, 20+margin(pair_scale()))], 'an on-screen pair too')

    def test_every_gate_hides_the_marks_and_the_tail_still_runs_once(self):
        import rush_cinematics as rush
        import cinematic_policy as cinema
        from result_presentation import RESULT
        camera = 0x1950000
        cases = [((BATTLE_STATE, 2), 'intro'), ((RESULT, 1), 'result'), ((core.PAIR+4, 1), 'paired pause'),
                 ((threat.CONTROL+threat.FIELDS['marks'], 0), 'hidden'), ((threat.CONTROL+4, MANAGER+4), 'stale'),
                 ((ACTORS[0]+0x1278, 1), 'CPU seat'), ((ACTORS[0]+0x9E4, 0), 'dead seat')]
        for (address, value), name in cases:
            c = self.machine(); update(c); c.w(address, value)
            self.assertEqual(self.run_entry(c), [], name); self.assertEqual(c.events, ['marker'], name)
        c = self.machine(); update(c); c.w(FRAMES, c.u(FRAMES)+2)
        self.assertEqual(self.run_entry(c), [], 'a stale record'); self.assertEqual(c.events, ['marker'])
        c = self.machine(); update(c); c.w(0x2FEBCC, camera); c.w(camera+812, 1)
        self.assertEqual(self.run_entry(c), [], 'cinematic camera'); self.assertEqual(c.events, ['marker'])
        c = self.machine(); update(c); c.w(rush.CONTROL, rush.MAGIC)
        c.callbacks[rush.OWNER] = lambda m: m.r.__setitem__(2, 1)
        self.assertEqual(self.run_entry(c), [], 'shared rush'); self.assertEqual(c.events, ['marker'])
        c = self.machine(); update(c)
        c.write(cinema.CONTROL, struct.pack('<2I', cinema.MAGIC, MANAGER)); c.w(cinema.CONTROL+cinema.SHARED_STOP, 3)
        self.assertEqual(self.run_entry(c), [], 'shared ultimate stop'); self.assertEqual(c.events, ['marker'])
        c.w(cinema.CONTROL+cinema.SHARED_STOP, 0); self.assertEqual(len(self.run_entry(c)), 1)

    def test_a_unique_close_up_hides_the_native_marks_two_do_not_quad_ignores_it(self):
        import cinematic_policy as cinema
        c = self.machine(); update(c)
        c.write(cinema.CONTROL, struct.pack('<2I', cinema.MAGIC, MANAGER)); c.w(cinema.CONTROL+16, 1)
        c.write(cinema.CLASSIFY, cinema.classify())
        def close_up(i, on, action=261):
            byte = ACTORS[i]+cinema.PRIORITY_FLAG_BYTES[0]
            c.write(byte, bytes([cinema.PRIORITY_FLAG_BIT if on else 0])); act(c, i, action)
        close_up(2, True); self.assertEqual(self.run_entry(c), [], 'an ally ultimate close-up')
        c.w(cinema.CONTROL+16, 0); self.assertEqual(len(self.run_entry(c)), 1, 'the unchecked class keeps your view')
        c.w(cinema.CONTROL+16, 1); close_up(3, True); self.assertEqual(len(self.run_entry(c)), 1, 'two: the native tie')
        close_up(3, False, 11); close_up(2, True, 100); self.assertEqual(len(self.run_entry(c)), 1, 'an ordinary action')
        close_up(2, True, 240); self.assertEqual(len(self.run_entry(c)), 1, 'transformations unchecked')
        c.w(cinema.CONTROL+20, 1); self.assertEqual(self.run_entry(c), [])

    def test_split_views_draw_each_seats_own_marks(self):
        rects_ = views.rectangles(2)
        for seat, rect in enumerate(rects_):
            places = [(0, 0, 1)]*6
            places[0] = (127, 300, 1); places[1] = (384, 300, 1)
            places[3] = (100, 100, 1); places[2] = (400, 100, 1)
            c = self.machine(humans=(0, 1), view=rect, positions=places, targets=[5, 4, 1, 0, 5, 4])
            update(c, words={0: 0, 1: 0})
            want = expected_mark(100, 100, 1, rect) if seat == 0 else expected_mark(400, 100, 1, rect)
            got = self.run_entry(c)
            self.assertEqual(placed(got), [want], seat)
            if want[0] == 'pair': self.assertEqual(got[0][3], tip_distance(rect))

    def quad(self, humans, rect, places, targets):
        c = self.machine(humans=tuple(range(humans)), view=rect, positions=places, mode='ffa', targets=targets)
        c.write(views.CONTROL, struct.pack('<4I', views.MAGIC, MANAGER, 6, 1)); c.w(views.CONTROL+views.VIEW_COUNT, humans)
        for k, other in enumerate(views.rectangles(humans)):
            for i, v in enumerate(other): c.w(views.CAMERAS+k*1024+512+4*i, v)
            c.w(views.SUBJECTS+4*k, k)
        c.callbacks[A(0x102708)] = lambda m: (m.events.append('link'), m.r.__setitem__(2, 0xAAAA), m.r.__setitem__(3, 0xBBBB))
        return c

    def test_quad_views_draw_each_seats_marks_after_the_link_and_keep_v0_v1(self):
        for humans in (2, 3, 4):
            rects_ = views.rectangles(humans)
            for seat, rect in enumerate(rects_):
                places = [(0, 0, 1)]*6; targets = [4, 4, 4, 4, seat, 4]
                for k, other in enumerate(rects_): places[k] = ((other[0]+other[1])//2, (other[2]+other[3])//2+40, 1)
                places[4] = ((rect[0]+rect[1])//2, (rect[2]+rect[3])//2, 1)
                c = self.quad(humans, rect, places, targets); update(c, words={k: 0 for k in range(humans)})
                c.events.clear(); c.packets.clear(); c.r[31] = 0xFEED0000; c.r[29] = 0x1FFFF00
                c.run(threat.QUAD_LINK)
                self.assertEqual((c.r[2], c.r[3]), (0xAAAA, 0xBBBB))
                self.assertEqual(c.events[0], 'link')
                cx, cy = places[4][0], places[4][1]
                self.assertEqual(placed(marks(c)), [expected_mark(cx, cy, 1, rect)], (humans, seat))
                self.assertEqual(marks(c)[0][3], tip_distance(rect), 'your own target in a quad view: the pair')

    def test_dead_or_absent_enemies_and_allies_are_never_marked(self):
        c = self.machine(targets=[5, 0, 0, 0, 0, 2]); c.w(ACTORS[3]+0x9E4, 0); update(c)
        self.assertEqual(len(self.run_entry(c)), 1, 'only 1: 3 is dead, 2/4 are allies')

    def test_the_marks_write_nothing_but_packets(self):
        c = self.machine(); act(c, 1, 100); self.at(c, 3, -500, 100); c.w(core.TABLE+12, 0); update(c)
        before = dict(c.memory)
        self.assertEqual([m[0] for m in self.run_entry(c)], ['pair', 'edge'])
        changed = {a for a, v in c.memory.items() if before.get(a, 0) != v}
        # Only the stack and the harness's GS packet buffer (its allocator starts at 0x5000000); the mod's own
        # memory (this module's CONTROL/ROWS, lockon_select, the queue) must stay untouched by the render pass.
        self.assertTrue(c.packets, 'the marks were drawn')
        self.assertEqual(sorted(hex(a) for a in changed if not (0x1FF0000 <= a < 0x2000000 or 0x5000000 <= a < 0x5100000)), [])

    def test_raster_pair_and_edge_chevrons(self):
        import numpy as np
        import gs_preview as g
        c = self.machine(); self.at(c, 1, 256, 224); self.at(c, 3, -500, 224); c.w(core.TABLE+12, 0); update(c)
        self.run_entry(c)
        grey = (90, 110, 90)
        gs = g.GS(grey); gs.feed(g.ad_packet((g.XYOFFSET_1, (1792*16) | ((Y_ORIGIN*16) << 32))))
        for packet in c.packets: gs.feed(packet)
        img = np.asarray(gs.image().convert('RGB'), np.int32)
        tip = 233 >> 4                                         # 0.9 r + 4 px at the one-view minimum r
        for x in (256-tip-2, 256+tip+2):                       # just behind each tip: red
            r, gr, b = img[224, x]; self.assertTrue(r > 200 and gr < 60 and b < 60, (x, img[224, x]))
        self.assertEqual(tuple(img[224, 256]), grey, 'the body between the pair is untouched')
        m = margin(threat.EDGE_SCALE)
        r, gr, b = img[223, m+5]; self.assertTrue(r > 200 and gr < 60, ('edge chevron', img[223, m+5]))
        self.assertEqual(tuple(img[223, m+20]), grey, 'the edge chevron is 11 px long')

    def test_ender_tail_paint_order_with_bar_draw_and_bars_draw(self):
        for tail, event in ((display.BAR_DRAW, 'bars'), (sel.MARKER, 'marker')):
            c = self.machine(); update(c); c.w(threat.CONTROL+threat.FIELDS['render_tail'], tail)
            self.run_entry(c); self.assertEqual(c.events[-1], event); self.assertEqual(c.events.count(event), 1)


BATTLE_STATE = base.BATTLE


# ---------------------------------------------------------------------------------------------- install, validators
def synthetic(count=6, entry='ffa', site='marker', marker=1):
    ram = bytearray(0x8000000)
    struct.pack_into('<I', ram, core.ACTORS, MANAGER); struct.pack_into('<I', ram, MANAGER, 2)
    struct.pack_into('<4I', ram, core.MODE, 1, count, MANAGER, count)
    struct.pack_into('<2I', ram, off.CONTROL, off.MAGIC, MANAGER)
    for p, b in off.programs(): ram[p:p+len(b)] = b
    for p, b in sel.programs(): ram[p:p+len(b)] = b
    struct.pack_into('<2I', ram, sel.CONTROL, sel.MAGIC, MANAGER); struct.pack_into('<I', ram, sel.CONTROL+sel.FIELDS['marker'], marker)
    struct.pack_into('<I', ram, sel.CONTROL+sel.FIELDS['style'], marker)
    struct.pack_into('<3I', ram, feed.CONTROL, 1, MANAGER, count)
    struct.pack_into('<3I', ram, retaliation.CONTROL, 1, MANAGER, count)
    acc = {'ffa': threat.jump(ffa.ACCUMULATE), 'prologue': retaliation.accumulate_code()[:8], 'empty': bytes(8),
           'foreign': threat.jump(0x07390000)}[entry]
    ram[retaliation.ACCUMULATE:retaliation.ACCUMULATE+8] = acc
    if entry == 'empty': ram[retaliation.CODE:retaliation.END] = bytes(retaliation.END-retaliation.CODE)
    else: ram[retaliation.ACCUMULATE+8:retaliation.ACCUMULATE+16] = retaliation.accumulate_code()[8:16]
    word = {'marker': sel.jal(sel.MARKER), 'display': sel.jal(display.BAR_DRAW), 'bars': sel.jal(bars.DRAW),
            'zero': bytes(4)}[site]
    point = sel.marker_site()[0]; ram[point:point+4] = word
    return ram


def apply(ram, manifest):
    for b in manifest['blocks']:
        data = bytes.fromhex(b['data_hex'])
        assert ram[b['address']:b['address']+len(data)].hex() == b['expected_hex']
        ram[b['address']:b['address']+len(data)] = data
    return ram


class InstallTests(unittest.TestCase):
    def test_legacy_installs_nothing_and_lockon_select_installs_for_the_new_defaults(self):
        legacy = settings(lockon_attacker_switch='never', lockon_threat_marks='hide')
        self.assertEqual(threat.build_memory(bytearray(16), settings=legacy), dict(blocks=[]))
        self.assertFalse(threat.wanted(legacy))
        for key, value in (('lockon_attacker_switch', 'tap_during_warning'), ('lockon_attacker_switch', 'when_hit'),
                           ('lockon_threat_marks', 'marks'), ('lockon_threat_marks', 'marks_and_warning')):
            values = settings(**dict(base.LEGACY, **{key: value}))
            self.assertTrue(threat.wanted(values)); self.assertTrue(sel.wanted(values), 'its wrappers need lockon_select')
        defaults = mod_settings.validate_settings({})
        self.assertEqual((defaults['lockon_attacker_switch'], defaults['lockon_threat_marks']),
                         ('tap_during_warning', 'marks_and_warning'))
        for key, bad in (('lockon_attacker_switch', 'always'), ('lockon_threat_marks', True)):
            with self.assertRaises(ValueError): mod_settings.validate_settings({key: bad})

    def test_blocks_hooks_and_control(self):
        ram = synthetic(); manifest = threat.build_memory(ram, settings=settings())
        blocks = {b['address']: bytes.fromhex(b['data_hex']) for b in manifest['blocks']}
        site = sel.marker_site()[0]
        self.assertEqual(blocks[retaliation.ACCUMULATE], threat.jump(threat.HITLOG))
        self.assertEqual((blocks[off.INPUT], blocks[off.APPLY]), (threat.jump(threat.INPUT3), threat.jump(threat.APPLY3)))
        self.assertEqual(blocks[site], threat.jal(threat.ENTRY))
        self.assertEqual(struct.unpack_from('<13I', blocks[threat.CONTROL]),
                         (threat.MAGIC, MANAGER, 1, 2, 45, 15, 90, 1000, 150, 60, ffa.ACCUMULATE, sel.MARKER, 0))
        self.assertEqual(manifest['status'], 'ATTACKER MARKS, ATTACK WARNING AND SWITCH TO ATTACKER')
        self.assertEqual(set(blocks) - {p for p, _ in threat.code_parts()},
                         {threat.CONTROL, threat.ROWS, threat.LAST, threat.CELLS, retaliation.ACCUMULATE, off.INPUT,
                          off.APPLY, site})
        apply(ram, manifest); threat.validate_memory(ram); off.validate_memory(ram); sel.validate_memory(ram)
        hidden = threat.build_memory(synthetic(), settings=settings(lockon_threat_marks='hide'))
        self.assertNotIn(site, {b['address'] for b in hidden['blocks']}, 'no marks, no display hook')

    def test_refusals(self):
        occupied = synthetic(); occupied[threat.END-1] = 1
        with self.assertRaisesRegex(ValueError, 'reservation occupied'): threat.build_memory(occupied, settings=settings())
        bare = synthetic(); bare[sel.CONTROL:sel.CONTROL+8] = bytes(8)
        with self.assertRaisesRegex(ValueError, 'require target selection'): threat.build_memory(bare, settings=settings())
        with self.assertRaisesRegex(ValueError, 'Unknown damage accumulator entry'):
            threat.build_memory(synthetic(entry='foreign'), settings=settings())
        with self.assertRaisesRegex(ValueError, 'Unknown overhead-bar display call'):
            threat.build_memory(synthetic(site='zero', marker=0), settings=settings())
        self.assertTrue(threat.build_memory(synthetic(site='zero', marker=0),
                                            settings=settings(lockon_threat_marks='hide'))['blocks'])
        nofeed = synthetic(); nofeed[feed.CONTROL:feed.CONTROL+4] = bytes(4)
        with self.assertRaisesRegex(ValueError, 'kill-feed clock'): threat.build_memory(nofeed, settings=settings())

    def test_an_empty_retaliation_reservation_skips_the_hit_memory_the_prologue_takes_the_trampoline(self):
        manifest = threat.build_memory(synthetic(entry='empty'), settings=settings())
        self.assertNotIn(retaliation.ACCUMULATE, {b['address'] for b in manifest['blocks']})
        self.assertIn('No hit memory: warnings use attack actions and projectiles only.', manifest['limitations'])
        ram = synthetic(entry='prologue'); manifest = threat.build_memory(ram, settings=settings())
        blocks = {b['address']: bytes.fromhex(b['data_hex']) for b in manifest['blocks']}
        self.assertEqual(blocks[threat.TRAMPOLINE], retaliation.accumulate_code()[:8]+threat.jump(retaliation.ACCUMULATE+8))
        self.assertEqual(manifest['effective']['acc_tail'], threat.TRAMPOLINE)
        apply(ram, manifest); threat.validate_memory(ram)
        expected = retaliation.accumulate_code()
        self.assertEqual(threat.dependency_override(ram, retaliation.ACCUMULATE, expected),
                         threat.jump(threat.HITLOG)+expected[8:])

    def test_the_overhead_bar_call_is_accepted_in_all_three_known_forms(self):
        for site, tail in (('marker', sel.MARKER), ('display', display.BAR_DRAW), ('bars', bars.DRAW)):
            ram = synthetic(site=site, marker=int(site == 'marker'))
            manifest = threat.build_memory(ram, settings=settings())
            self.assertEqual(manifest['effective']['render_tail'], tail)
            self.assertEqual(any('display settings program' in line for line in manifest['limitations']), site == 'bars')
            apply(ram, manifest); threat.validate_memory(ram)
            point = sel.marker_site()[0]
            self.assertEqual(threat.dependency_override(ram, point, sel.jal(tail)), threat.jal(threat.ENTRY))

    def test_quad_link_calls_are_found_by_pattern(self):
        emission = views.draw()
        self.assertEqual(threat.quad_sites(emission, views.DRAW, A(0x102708)), [0x06C00630, 0x06C00698] if A(0x102708) == 0x102708 else threat.quad_sites(emission, views.DRAW, A(0x102708)))
        self.assertEqual(len(threat.quad_sites(emission, views.DRAW, A(0x102708))), 2)
        ram = synthetic(); ram[views.DRAW:views.DRAW+len(emission)] = emission
        import four_player_mode
        with patch.object(four_player_mode, 'installed', lambda r: True):
            manifest = threat.build_memory(ram, settings=settings())
            self.assertEqual(manifest['effective']['quad_sites'], 2)
            apply(ram, manifest); threat.validate_memory(ram)
            self.assertEqual(threat.dependency_override(ram, views.DRAW, emission),
                             bytes(ram[views.DRAW:views.DRAW+len(emission)]))
            broken = synthetic(); changed = bytearray(emission)
            at = threat.quad_sites(emission, 0, A(0x102708))[0]; changed[at-8:at-4] = b'\0\0\0\0'
            broken[views.DRAW:views.DRAW+len(emission)] = changed
            manifest = threat.build_memory(broken, settings=settings())
            self.assertEqual(manifest['effective']['quad_sites'], 0)
            self.assertIn('Marks not drawn with a team assignment or three or four players.', manifest['limitations'])

    def test_validator_chains_accept_the_hooks_and_reject_a_changed_byte(self):
        ram = synthetic(); apply(ram, threat.build_memory(ram, settings=settings()))
        off.validate_memory(ram); sel.validate_memory(ram); threat.validate_memory(ram)
        for address in (threat.HITLOG+8, threat.INPUT3+0x40, threat.APPLY3+0x20, threat.DRAW+0x100, threat.ENTRY+4,
                        threat.QUAD_LINK+4):
            broken = bytearray(ram); broken[address] ^= 1
            with self.assertRaisesRegex(ValueError, 'Attacker marks executable changed'): threat.validate_memory(broken)
            with self.assertRaisesRegex(ValueError, 'Attacker marks executable changed'): sel.validate_memory(broken)
            with self.assertRaisesRegex(ValueError, 'Attacker marks executable changed'): off.validate_memory(broken)
        stripped = bytearray(ram); stripped[off.INPUT:off.INPUT+8] = sel.jump(sel.INPUT2)
        with self.assertRaises(ValueError): sel.validate_memory(stripped)
        with patch.object(threat, 'dependency_override', lambda ram, address, expected: expected):
            with self.assertRaisesRegex(ValueError, 'Target selection executable changed'): sel.validate_memory(ram)
            with self.assertRaises(ValueError): off.validate_memory(ram)
        for name, value in (('switch', 3), ('marks', 0), ('acc_tail', 0x07390000), ('quad_sites', 1)):
            broken = bytearray(ram); struct.pack_into('<I', broken, threat.CONTROL+threat.FIELDS[name], value)
            with self.assertRaises(ValueError, msg=name): threat.validate_memory(broken)

    def test_lockon_select_guest_bytes_are_pinned(self):
        import hashlib
        import native_map
        if native_map.ADAPTER not in SELECT_PROGRAMS_SHA256: self.skipTest('pinned for the USA addresses only')
        digest = hashlib.sha256(b''.join(struct.pack('<I', p)+b for p, b in sel.programs())).hexdigest()
        self.assertEqual(digest, SELECT_PROGRAMS_SHA256[native_map.ADAPTER])

    def test_reservation_is_owned_and_nothing_else_names_an_address_inside_it(self):
        for p, b in threat.code_parts()+threat.data_blocks(MANAGER, 1, 2, ffa.ACCUMULATE, sel.MARKER, 0):
            self.assertTrue(threat.BASE <= p and p+len(b) <= threat.END, hex(p))
        spans = sorted((p, p+len(b)) for p, b in threat.code_parts()+threat.data_blocks(MANAGER, 1, 2, 0, 0, 0)+
                       [(threat.TRAMPOLINE, threat.trampoline(bytes(8)))])
        self.assertTrue(all(e <= s for (_, e), (s, _) in zip(spans, spans[1:])), spans)
        self.assertEqual(threat.CELLS+threat.CELL_ROW*modes.ENGINE_ACTORS, 0x0694F980)
        literal = re.compile(r'\b0x0*69[0-9A-Fa-f]{5}\b')
        trees = [Path(__file__).resolve().parent]
        sibling = mod_settings.ROOT.parent/('bt4-multifighter' if mod_settings.ADAPTER == 'BT3' else 'bt3-multifighter')/'tools'
        if sibling.is_dir(): trees.append(sibling)
        for tree in trees:
            for source in tree.glob('*.py'):
                if source.name in ('lockon_threat.py', 'test_lockon_threat.py'): continue
                for m in literal.finditer(source.read_text(encoding='utf-8', errors='replace')):
                    value = int(m.group(0), 16)
                    # lock-off's reservation ends exactly where this one begins.
                    if source.name == 'lockoff_target.py' and value == threat.BASE: continue
                    self.assertFalse(threat.BASE <= value < threat.END, (source, m.group(0)))

    def test_lockon_threat_is_the_last_builder(self):
        import ast
        import fresh_team_trainer
        tree = ast.parse(Path(fresh_team_trainer.__file__).read_text(encoding='utf-8-sig'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'final_team_manifest')
        appended = [ast.unparse(n.args[0]) for n in sorted(
            (n for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == 'append' and isinstance(n.func.value, ast.Name) and n.func.value.id == 'builders'),
            key=lambda n: (n.lineno, n.col_offset))]
        self.assertIn('lockon_threat.build_memory', appended[-1]); self.assertIn('lockon_select.build_memory', appended[-2])


# lockon_select.programs() of the beta.38 target ring (pinned; beta.38 intentionally changed the beta.36 bytes).
SELECT_PROGRAMS_SHA256 = {'bt3-usa': 'e37ff03fb5d58ec2726f83fbf5a825ec9f1ff23f90e23364f7e0c866de4c9e21'}


class RealImageTests(unittest.TestCase):
    """The Sept 24 prepared images (BT3: a six-fighter FFA and its staged rematch; BT4: a teams match)."""
    def composed(self, path, values=None):
        from camera_snapshot import read_ram
        from fresh_team_trainer import compose_manifests
        ram = bytearray(read_ram(path)); values = settings() if values is None else values
        manifest = compose_manifests(ram, [lambda r: sel.build_memory(r, settings=values),
                                           lambda r: threat.build_memory(r, settings=values)])
        return apply(ram, manifest), manifest

    @unittest.skipUnless(FIXTURE_FFA.is_file(), 'Sept 24 prepared image absent from this copy')
    def test_manifest_equals_ram_and_every_validator_accepts_it(self):
        from camera_snapshot import read_ram
        import battle_modes
        ram, manifest = self.composed(FIXTURE_FFA)
        original = bytearray(read_ram(FIXTURE_FFA))
        for b in manifest['blocks']:
            self.assertEqual(original[b['address']:b['address']+len(bytes.fromhex(b['data_hex']))].hex(), b['expected_hex'])
        threat.validate_memory(ram); sel.validate_memory(ram); off.validate_memory(ram)
        self.assertEqual(battle_modes.validate_memory(ram), IMAGE_MODE)
        self.assertEqual(threat.build_memory(ram.copy() if False else bytearray(read_ram(FIXTURE_FFA)),
                                             settings=settings(lockon_attacker_switch='never', lockon_threat_marks='hide')),
                         dict(blocks=[]))
        if IMAGE_MODE == 'ffa':
            with patch.object(threat, 'dependency_override', lambda ram, address, expected: expected):
                with self.assertRaises(ValueError): battle_modes.validate_memory(ram)
            # FFA validates the accumulator's 8-byte jump followed by the rest of the original retaliation code.
            real = threat.dependency_override
            def no_accumulator(ram, address, expected):
                return expected if address == retaliation.ACCUMULATE else real(ram, address, expected)
            with patch.object(threat, 'dependency_override', no_accumulator):
                with self.assertRaisesRegex(ValueError, 'Battle-mode code changed:07462000'): battle_modes.validate_memory(ram)
        rebuilt = display.build_memory(ram, settings=settings())
        self.assertEqual([b for b in rebuilt['blocks'] if b['address'] != display.CONTROL], [], 'nothing to upgrade')
        with patch.object(threat, 'dependency_override', lambda ram, address, expected: expected):
            with self.assertRaises(ValueError): display.build_memory(ram, settings=settings())

    @unittest.skipUnless(FIXTURE_FFA.is_file(), 'Sept 24 prepared image absent from this copy')
    def test_legacy_settings_compose_exactly_the_beta36_manifest(self):
        from camera_snapshot import read_ram
        from fresh_team_trainer import compose_manifests
        ram = bytearray(read_ram(FIXTURE_FFA))
        legacy = settings(lockon_attacker_switch='never', lockon_threat_marks='hide')
        with_threat = compose_manifests(ram, [lambda r: sel.build_memory(r, settings=legacy),
                                              lambda r: threat.build_memory(r, settings=legacy)])
        without = compose_manifests(ram, [lambda r: sel.build_memory(r, settings=legacy)])
        self.assertEqual(with_threat, without)
        self.assertFalse(any(threat.BASE <= b['address'] < threat.END for b in with_threat['blocks']))

    @unittest.skipUnless(FIXTURE_REMATCH.is_file(), 'Sept 24 rematch image absent from this copy')
    def test_fight_again_plan_accepts_the_composed_image(self):
        import prepared_rematch
        ram, _ = self.composed(FIXTURE_REMATCH)
        self.assertIsNotNone(prepared_rematch.plan(ram))
        if IMAGE_MODE == 'ffa':
            with patch.object(threat, 'dependency_override', lambda ram, address, expected: expected):
                with self.assertRaises(ValueError): prepared_rematch.plan(ram)


class SettingsTests(unittest.TestCase):
    def test_rows_pages_labels_and_values(self):
        import localization
        groups = dict(mod_settings.GROUPS); fields = mod_settings.ui_fields()
        self.assertEqual(groups['Controls'].index('lockon_attacker_switch'), 8)
        self.assertEqual(groups['HUD'][-2:], ('lockon_threat_marks', 'tag_team_rush_show_meter'))
        self.assertEqual([fields[k][5] for k in threat.KEYS], ['Switch to your attacker', 'Enemies targeting you'])
        self.assertEqual([localization.tr(fields[k][5], {'language': 'es'}) for k in threat.KEYS],
                         ['Cambiar a quien te ataca', 'Enemigos que te fijan'])
        self.assertEqual([localization.value_label(v, {'language': language}) for language in ('en', 'es')
                          for v in fields['lockon_attacker_switch'][2]],
                         ['Never', 'Tap during a warning', 'Tap, or automatic when hit',
                          'Nunca', 'Pulsando durante el aviso', 'Pulsando o al recibir golpes'])
        self.assertEqual([localization.value_label(v, {'language': language}) for language in ('en', 'es')
                          for v in fields['lockon_threat_marks'][2]],
                         ['Hide', 'Arrows', 'Arrows and attack warning', 'Ocultar', 'Flechas', 'Flechas y aviso de ataque'])
        self.assertEqual(threat.LEGACY, {'lockon_attacker_switch': 'never', 'lockon_threat_marks': 'hide'})
        import ingame_settings as s
        self.assertNotIn('lockon_attacker_switch', s.DEPENDS); self.assertNotIn('lockon_threat_marks', s.DEPENDS)

    def test_installer_defaults_name_both_keys(self):
        import json
        path = mod_settings.ROOT.parent/'player-installer'/'player-defaults.json'
        if not path.is_file(): self.skipTest('player-installer is not beside this adapter')
        defaults = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((defaults['lockon_attacker_switch'], defaults['lockon_threat_marks']),
                         (mod_settings.DEFAULTS['lockon_attacker_switch'], mod_settings.DEFAULTS['lockon_threat_marks']))

    def test_play_window_hint_follows_the_setting_and_the_hold_time(self):
        import json
        import tempfile
        import localization
        import play_launcher
        tap_hint = 'During an attack warning, tap {button} to lock on to your attacker.'
        hold_hint = 'During an attack warning, your {button} target switch locks on to your attacker.'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mod-settings.json'
            for values, shown in ((dict(lockon_switch_button='l3', lockon_hold_seconds=0.0), tap_hint),
                                  (dict(lockon_switch_button='l3', lockon_hold_seconds=0.5), hold_hint),
                                  (dict(lockon_switch_button='r3'), hold_hint),
                                  (dict(lockon_switch_button='l3', lockon_hold_seconds=0.0, lockon_attacker_switch='when_hit'), tap_hint),
                                  (dict(lockon_switch_button='l3', lockon_attacker_switch='never'), None),
                                  ({'language': 'es', 'lockon_switch_button': 'l3', 'lockon_hold_seconds': 0.0}, tap_hint),
                                  ({'language': 'es', 'lockon_switch_button': 'l3', 'lockon_hold_seconds': 1.0}, hold_hint)):
                path.write_text(json.dumps(values), encoding='utf-8')
                lines = play_launcher.hint_lines(folder, 'C:/logs', windows=True)
                found = [l for l in lines if 'attack warning' in l or 'aviso de ataque' in l]
                if shown is None:
                    self.assertEqual(found, [], values); continue
                button = values['lockon_switch_button'].upper()
                self.assertEqual(found, [localization.tr(shown, values.get('language', 'en'), button=button)], values)



REGIONAL = r"""
import json, struct, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import prototype
prototype.ROOT = Path(sys.argv[2])
import native_map
assert native_map.ADAPTER == sys.argv[3], native_map.ADAPTER
import cinematic_policy as cinema
import lockon_threat as threat
import quad_viewports as views
from native_map import A
from regional import Y_ORIGIN
parts = dict(threat.code_parts())
draw = parts[threat.DRAW]
words = struct.unpack('<%dI' % (len(draw)//4), draw)
lbu = [(w & 0xFFFF) for w in words if w >> 26 == 36 and (w >> 21) & 31 == 23]
print(json.dumps(dict(ticks=[threat.HIT_WINDOW, threat.TAP_GRACE, threat.SUM_WINDOW, threat.AUTO_COOLDOWN, threat.OWN_QUIET,
                             threat.AUTO_STALE],
                      sizes={hex(p): len(d) for p, d in parts.items()}, y_origin=Y_ORIGIN,
                      flag_bytes=list(cinema.PRIORITY_FLAG_BYTES), flag_bit=cinema.PRIORITY_FLAG_BIT, lbu=lbu,
                      quad=threat.quad_sites(views.draw(), views.DRAW, A(0x102708)),
                      natives=[A(x) for x in (0x102708, 0x12CCD0, 0x1210D8, 0x120AB0, 0x120B80, 0x120AC8, 0x121ED8,
                                              0x2FEB38, 0x2FEBCC, 0x1DA9D0)],
                      gpo=[struct.unpack_from('<I', parts[threat.HITLOG], 4*i)[0] & 0xFFFF
                           for i in range(len(parts[threat.HITLOG])//4)
                           if struct.unpack_from('<I', parts[threat.HITLOG], 4*i)[0] >> 21 & 31 == 28])))
"""


class RegionalTests(unittest.TestCase):
    """The European and Japanese builds (subprocesses with TAGTEAM_ADAPTER, the disc's executable in a scratch root)."""
    def regional(self, adapter, variable, serial_file):
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        if mod_settings.ADAPTER != 'BT3': self.skipTest('the European and Japanese discs are BT3 only')
        elf = os.environ.get(variable)
        if not elf or not Path(elf).is_file(): self.skipTest(f'Set {variable} to the {serial_file} executable')
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'analysis').mkdir(); shutil.copyfile(elf, Path(root)/'analysis'/serial_file)
            result = subprocess.run([sys.executable, '-B', '-c', REGIONAL, str(Path(__file__).resolve().parent), root, adapter],
                                    capture_output=True, text=True, timeout=600,
                                    env=dict(os.environ, TAGTEAM_ADAPTER=adapter))
        self.assertEqual(result.returncode, 0, result.stdout[-2000:]+result.stderr[-4000:])
        import json
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_european_build(self):
        out = self.regional('bt3-pal', 'TAGTEAM_PAL_ELF', 'SLES_549.45')
        self.assertEqual(out['ticks'], [38, 12, 75, 125, 50, 75], '25 updates a second')
        self.assertEqual(out['y_origin'], 1792)
        self.assertEqual(len(out['quad']), 2, 'the quad link calls are found with the European addresses')
        self.assertEqual(sorted(set(out['lbu'])), sorted(set(out['flag_bytes'])))
        self.assertEqual(len(set(out['natives'])), 10, 'every native address translated')

    def test_japanese_build(self):
        out = self.regional('bt3-jpn', 'TAGTEAM_JPN_ELF', 'SLPS_258.15')
        self.assertEqual(out['ticks'], [45, 15, 90, 150, 60, 90])
        self.assertEqual(out['y_origin'], 1824)
        self.assertEqual(len(out['quad']), 2)
        self.assertEqual(sorted(set(out['lbu'])), sorted(set(out['flag_bytes'])), 'flag 0xD3 through FLAG_BITS')
        self.assertEqual(out['flag_bytes'], [0x1085+(0xD3-2)//8, 0x10AD+(0xD3-2)//8], 'Japanese flags 186..316 are two lower')

if __name__ == '__main__':
    unittest.main()
