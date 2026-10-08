"""Controller check-in rules (T3): pure, table-driven; no SDL, no PINE."""
import itertools
import unittest

import controller_checkin as c
from controller_checkin import START, SELECT, LEFT, RIGHT


def table(count=4, **extra):
    devices = {}
    for i in range(count):
        devices[f'k{i}'] = c.Device(key=f'k{i}', name='Pad', display=f'Pad {i}', serial=f's{i}', vid=0x54C, pid=0x9CC,
                                    guid=f'g{i}', first_seen=float(i), order=i+1)
    for key, values in extra.items():
        for name, value in values.items():setattr(devices[key], name, value)
    return devices


class Desk:
    """A CheckIn with a clock: press() steps through a down edge, the join delay and the release."""
    def __init__(self, humans=4, mode='three_or_more', team_mode=True, devices=None, keep=True):
        self.now = 100.0; self.devices = devices if devices is not None else table(); self.out = []
        self.c = c.CheckIn(mode, keep); self.step()
        self.c.open(humans, team_mode, self.now, self.devices, mode=mode, keep=keep)

    def step(self, events=(), **kw):
        self.c.step(self.now, self.devices, list(events), **kw)
        self.out.append(self.c.take())

    def wait(self, seconds, **kw):
        end = self.now+seconds
        while self.now < end:self.now = min(end, self.now+.05); self.step(**kw)

    def press(self, key, bit=START, hold=.05, settle=.2, **kw):
        self.step([(self.now, key, 'down', bit)], **kw); self.wait(hold, **kw)
        self.step([(self.now, key, 'up', bit)], **kw); self.wait(settle, **kw)

    def seats(self):return [(s.source, s.key) for s in self.c.roster.seats]

    def messages(self):return [m for out in self.out for m in out[0]]

    def notices(self):return [n for out in self.out for n in out[1]]

    def claims(self):return [m for out in self.out for m in out[2]]


class JoinTests(unittest.TestCase):
    def test_four_players_start_empty_and_join_three_and_four_first_then_one_and_two(self):
        d = Desk()
        self.assertEqual(d.seats(), [('empty', None)]*4)
        d.step([(d.now, 'k2', 'down', START)]); d.wait(.1)
        self.assertEqual(d.seats()[2], ('empty', None), 'not before the matching window closed')
        d.wait(.1); self.assertEqual(d.seats()[2], ('hub', 'k2'))
        d.step([(d.now, 'k2', 'up', START)])
        for key in ('k0', 'k1', 'k3'):d.press(key)
        self.assertEqual(d.seats(), [('hub', 'k1'), ('hub', 'k3'), ('hub', 'k2'), ('hub', 'k0')])
        self.assertIn(('k2', START), d.claims())

    def test_a_controller_pcsx2_uses_as_port_k_takes_seat_k_and_keeps_pass_through(self):
        d = Desk(devices=table(k3=dict(native_port=1), k1=dict(native_port=2)))
        d.press('k3'); d.press('k0'); d.press('k1')
        self.assertEqual(d.seats(), [('native', 'k3'), ('native', 'k1'), ('hub', 'k0'), ('empty', None)])
        self.assertEqual(c.p12(d.c.roster, False), (False, 3, (None, None)))

    def test_the_first_mod_read_join_turns_default_seats_into_empty(self):
        d = Desk(humans=2)
        self.assertEqual(d.seats(), [('default', None)]*2)
        d.now += 1; d.step(); self.assertTrue(c.ready(d.c.roster, d.now), 'two players: PCSX2 order is ready as is')
        d.press('k2')
        self.assertEqual(d.seats(), [('hub', 'k2'), ('empty', None)])
        self.assertTrue(d.c.roster.hub_joined); self.assertEqual(c.waiting(d.c.roster), [2])
        self.assertEqual(c.p12(d.c.roster, False), (True, 2, ('k2', None)))

    def test_two_or_more_starts_empty_for_two_players(self):
        self.assertEqual(Desk(humans=2, mode='two_or_more').seats(), [('empty', None)]*2)

    def test_a_controller_never_holds_two_seats(self):
        d = Desk(); d.press('k0'); d.press('k0'); d.press('k0', hold=2.5)
        self.assertEqual([k for s, k in d.seats()].count('k0'), 1)

    def test_a_keyboard_start_takes_its_port_seat_or_shows_keyboard_taken(self):
        d = Desk(humans=2)
        d.press('pcsx2:1')
        self.assertEqual(d.seats()[0], ('pseudo', 'pcsx2:1'))
        self.assertEqual(c.p12(d.c.roster, False)[:2], (False, 3))
        d = Desk(devices=table(k0=dict(native_port=1)))
        d.press('k0'); d.press('pcsx2:1')
        self.assertEqual(d.seats()[0], ('native', 'k0'), 'nobody is bumped')
        self.assertEqual(d.notices()[-1], ('keyboard_taken', dict(k=1)))
        d.press('pcsx2:2'); self.assertEqual(d.seats()[1], ('pseudo', 'pcsx2:2'))

    def test_a_pseudo_seat_is_named_after_a_controller_without_layout(self):
        d = Desk(humans=2)
        d.step([(d.now, 'pcsx2:1', 'down', START)], labels={1: 'USB Gamepad'}); d.wait(.2, labels={1: 'USB Gamepad'})
        self.assertEqual(d.c.roster.seat(1).name, 'USB Gamepad')

    def test_joins_only_while_player_setup_is_open(self):
        d = Desk(); d.c.close(True, d.now); d.press('k0')
        self.assertEqual(d.seats(), [('empty', None)]*4)


class LeaveAndTeamTests(unittest.TestCase):
    def test_select_leaves_and_two_players_return_to_the_default_order(self):
        d = Desk(humans=2); d.press('k2'); d.press('k3')
        self.assertEqual(d.seats(), [('hub', 'k2'), ('hub', 'k3')])
        d.press('k2', SELECT); self.assertEqual(d.seats()[0], ('empty', None))
        d.press('k3', SELECT)
        self.assertEqual(d.seats(), [('default', None)]*2); self.assertFalse(d.c.roster.hub_joined)
        d = Desk(humans=2); d.press('pcsx2:2'); d.press('pcsx2:2', SELECT)
        self.assertEqual(d.seats(), [('default', None)]*2)

    def test_left_right_toggles_the_own_team_of_seats_2_to_4_only(self):
        d = Desk(); [d.press(k) for k in ('k0', 'k1', 'k2', 'k3')]
        teams = [s.team for s in d.c.roster.seats]
        for key in ('k0', 'k1', 'k2', 'k3'):d.press(key, RIGHT)
        holder = {s.key: s for s in d.c.roster.seats}
        self.assertEqual(holder[d.c.roster.seat(1).key].team, teams[0], 'seat 1 uses the cursor')
        self.assertEqual([s.team for s in d.c.roster.seats[1:]], [t ^ 1 for t in teams[1:]])
        d = Desk(team_mode=False); d.press('k0'); d.press('k0', LEFT)
        self.assertEqual(d.c.roster.seat(3).team, 0)

    def test_clear_returns_every_seat_to_the_start_state(self):
        d = Desk(); d.press('k0'); d.press('k1'); d.c.clear(d.now)
        self.assertEqual(d.seats(), [('empty', None)]*4)


class TwinTests(unittest.TestCase):
    def test_mirrored_presses_claim_the_controller_with_a_serial_and_ignore_the_copy(self):
        d = Desk(devices=table(k0=dict(serial=''), k1=dict(serial='real')))
        d.step([(d.now, 'k0', 'down', START), (d.now+.01, 'k1', 'down', START)]); d.wait(.3)
        self.assertEqual(d.seats()[2], ('hub', 'k1')); self.assertEqual(d.devices['k0'].twin_of, 'k1')
        self.assertIn(('warning', 'TTM-CTRL-23', 'twin', dict(name='Pad 1')), d.messages())
        self.assertEqual(d.notices()[-1][0], 'twin')
        d.press('k0'); self.assertNotIn('k0', [k for s, k in d.seats()], 'the copy never joins')
        self.assertEqual(c.extras(d.devices, d.c.roster).count('k0'), 0)

    def test_without_serials_the_earlier_controller_is_claimed_and_divergence_clears_the_mark(self):
        d = Desk(devices=table(k0=dict(serial=''), k1=dict(serial='')))
        d.step([(d.now, 'k1', 'down', START), (d.now+.005, 'k0', 'down', START)]); d.wait(.3)
        self.assertEqual(d.seats()[2], ('hub', 'k0')); self.assertEqual(d.devices['k1'].twin_of, 'k0')
        d.press('k1', LEFT); self.assertEqual(d.devices['k1'].twin_of, 'k0')
        d.press('k1', RIGHT)
        self.assertIsNone(d.devices['k1'].twin_of, 'two presses the other did not make: two controllers after all')

    def test_a_copy_of_an_already_claimed_controller_never_takes_a_second_seat(self):
        d = Desk(); d.press('k0')
        d.step([(d.now, 'k0', 'down', START), (d.now+.004, 'k1', 'down', START)]); d.wait(.3)
        self.assertEqual(d.devices['k1'].twin_of, 'k0'); self.assertNotIn('k1', [k for s, k in d.seats()])


class LostTests(unittest.TestCase):
    def setUp(self):
        self.d = Desk(humans=3, team_mode=False)
        for key in ('k0', 'k1', 'k2'):self.d.press(key)
        self.d.c.close(True, self.d.now)

    def test_a_lost_seat_is_reported_once_and_the_same_controller_restores_it(self):
        d = self.d; d.devices['k0'].connected = False; d.wait(.1)
        seat = d.c.roster.seat(3)
        self.assertTrue(seat.lost)
        self.assertEqual([m[1] for m in d.messages()].count('TTM-CTRL-22'), 1)
        self.assertEqual(c.private(d.c.roster, d.devices), (None, None))
        d.devices['k0'].connected = True; d.wait(.1); d.devices['k0'].connected = False; d.wait(.1)
        self.assertEqual([m[1] for m in d.messages()].count('TTM-CTRL-22'), 1, 'once per seat per match')
        d.devices['k0'].connected = True; d.wait(.1)
        self.assertFalse(seat.lost); self.assertIn(('info', None, 'back', dict(n=3, name='Pad 0')), d.messages())

    def test_a_new_controller_of_the_same_model_within_60_s_restores_it(self):
        d = self.d; d.devices['k1'].connected = False; d.wait(.1)
        lost = next(s for s in d.c.roster.seats if s.lost)
        d.devices['k9'] = c.Device(key='k9', display='Pad 9', vid=0x54C, pid=0x9CC, connected=False, order=10)
        d.wait(1); d.devices['k9'].connected = True; d.wait(.1)
        self.assertEqual((lost.key, lost.lost), ('k9', False))
        d.devices['k9'].connected = False; d.wait(61)
        d.devices['k8'] = c.Device(key='k8', display='Pad 8', vid=0x54C, pid=0x9CC, order=11); d.wait(.1)
        self.assertTrue(lost.lost, 'too late: no automatic restore')

    def test_holding_start_two_seconds_on_a_free_controller_takes_the_lowest_lost_seat(self):
        d = self.d; d.devices['k2'].connected = False; d.devices['k0'].connected = False; d.wait(.1)
        d.step([(d.now, 'k3', 'down', START)]); d.wait(1.5)
        self.assertEqual([s.number for s in d.c.roster.seats if s.lost], [2, 3])   # k2 joined seat 2, k0 seat 3
        d.wait(.6)
        self.assertEqual(d.c.roster.seat(2).key, 'k3'); self.assertTrue(d.c.roster.seat(3).lost)
        self.assertIn(('k3', START), d.claims())
        self.assertEqual(d.c.roster.seat(2).source, 'hub', 'a takeover is mod-read, so START is masked')

    def test_a_takeover_by_a_pcsx2_port_controller_is_mod_read_too(self):
        # k3 is PCSX2's port 1 and seat 1 (k1) is lost: a pass-through seat would let the held START pause the match.
        d = self.d; d.devices['k3'].native_port = 1; d.devices['k1'].connected = False; d.wait(.1)
        d.step([(d.now, 'k3', 'down', START)]); d.wait(2.1)
        seat = d.c.roster.seat(1)
        self.assertEqual((seat.source, seat.key, seat.lost), ('hub', 'k3', False))
        self.assertIn(('k3', START), d.claims())

    def test_a_takeover_by_a_pcsx2_port_controller_prefers_its_own_ports_lost_seat(self):
        # Seats 1 (k1) and 2 (k2) are lost; k3 is PCSX2's port 2: it takes seat 2 (mod-read), never seat 1 while its
        # own port's seat would pass it through in menus (one pad moving two players).
        d = self.d; d.devices['k3'].native_port = 2
        d.devices['k1'].connected = False; d.devices['k2'].connected = False; d.wait(.1)
        d.step([(d.now, 'k3', 'down', START)]); d.wait(2.1)
        self.assertEqual((d.c.roster.seat(2).source, d.c.roster.seat(2).key), ('hub', 'k3'))
        self.assertTrue(d.c.roster.seat(1).lost)

    def test_a_controller_pcsx2_passes_to_its_own_player_never_takes_over_a_second_seat(self):
        # Two players: k1 is PCSX2 port 1 (seat 1 native), seat 2 is PCSX2's default order and k3 is port 2. k1 is lost
        # in the match: k3 holding START is player 2's own pause and never also takes player 1.
        d = Desk(humans=2, devices=table(k1=dict(native_port=1), k3=dict(native_port=2)))
        d.press('k1'); self.assertEqual(d.seats(), [('native', 'k1'), ('default', None)])
        d.c.close(True, d.now); d.devices['k1'].connected = False; d.wait(.1)
        d.step([(d.now, 'k3', 'down', START)]); d.wait(2.5)
        self.assertTrue(d.c.roster.seat(1).lost); self.assertEqual(d.seats()[1], ('default', None))
        self.assertNotIn(('k3', START), d.claims())
        d.step([(d.now, 'k3', 'up', START)])
        # A free controller still takes the lost seat.
        d.step([(d.now, 'k0', 'down', START)]); d.wait(2.1)
        self.assertEqual(d.seats()[0], ('hub', 'k0'))
        self.assertEqual(c.p12(d.c.roster, True), (True, 2, ('k0', None)), 'player 2 still passes PCSX2 port 2 through')

    def test_in_player_setup_a_join_fills_lost_seats_first(self):
        d = Desk(); d.press('k0'); d.devices['k0'].connected = False; d.wait(.1)
        d.press('k1'); self.assertEqual(d.c.roster.seat(3).key, 'k1')


class OutputTests(unittest.TestCase):
    def roster(self, sources, lost=()):
        roster = c.Roster(len(sources), 'three_or_more')
        for seat, source in zip(roster.seats, sources):
            seat.source = source; seat.key = f'k{seat.number}' if source in ('hub', 'native', 'pseudo') else None
            if seat.number in lost:seat.lost_since = 1.0
        return roster

    def test_p12_for_every_source_combination(self):
        sources = ('empty', 'default', 'hub', 'native', 'pseudo')
        for a, b in itertools.product(sources, repeat=2):
            for in_match in (False, True):
                armed, mask, keys = c.p12(self.roster((a, b, 'hub')), in_match)
                self.assertEqual(armed, 'hub' in (a, b))
                self.assertEqual(mask, (a != 'hub')+2*(b != 'hub'))
                self.assertEqual(keys, tuple('k%d' % n if s == 'hub' else None for n, s in ((1, a), (2, b))))
        self.assertEqual(c.p12(self.roster(('hub', 'native'), lost=(2,)), False), (True, 2, ('k1', None)))
        self.assertEqual(c.p12(self.roster(('native', 'native'), lost=(2,)), True), (True, 1, (None, None)))
        self.assertEqual(c.p12(None, True), (False, 3, (None, None)))

    def test_connection_order_reproduces_beta36_players_3_and_4(self):
        devices = {f'x{i}': c.Device(key=f'x{i}', xinput=i, order=10+i) for i in range(4)}
        devices['ds4'] = c.Device(key='ds4', order=1)
        roster = c.Roster(4, 'connection_order')
        self.assertEqual([s.source for s in roster.seats], ['default', 'default', 'classic', 'classic'])
        self.assertEqual(c.private(roster, devices), ('x2', 'x3'))
        devices['x2'].native_confirmed = True; devices['x2'].native_port = 1
        self.assertEqual(c.private(roster, devices), ('x3', 'ds4'), 'a confirmed PCSX2 port is skipped')
        self.assertEqual(c.p12(roster, True), (False, 3, (None, None)))

    def test_extras_skip_twins_pcsx2_ports_and_claimed_controllers_most_recent_first(self):
        devices = table(6)
        for i, active in enumerate((5, 9, 7, 8, 6, 1)):devices[f'k{i}'].last_active = active
        devices['k1'].twin_of = 'k5'; devices['k3'].native_port = 2
        roster = c.Roster(2, 'three_or_more'); roster.seat(1).source, roster.seat(1).key = 'hub', 'k2'
        self.assertEqual(c.extras(devices, roster), ('k4', 'k0'))

    def test_extras_never_give_a_second_cursor_to_a_controller_that_may_be_pcsx2s_own(self):
        devices = table(4)
        for i, active in enumerate((9, 8, 2, 1)):devices[f'k{i}'].last_active = active
        roster = c.Roster(2, 'three_or_more')   # two humans on PCSX2's ports 1-2 (default seats), ports not identified
        self.assertEqual(c.extras(devices, roster), ('k2', 'k3'), 'the first two stand in for ports 1-2 (beta.36)')
        devices['k2'].native_port = 1
        self.assertEqual(c.extras(devices, roster), ('k1', 'k3'), 'port 1 identified: one stand-in left')
        roster.seat(2).source, roster.seat(2).key = 'hub', 'k3'
        self.assertEqual(c.extras(devices, roster), ('k0', 'k1'), 'port 2 overridden: it moves nobody')

    def test_ready_waits_half_a_second_after_the_last_change(self):
        d = Desk(humans=3, team_mode=False)
        for key in ('k0', 'k1', 'k2'):d.press(key, settle=.16)
        self.assertFalse(c.ready(d.c.roster, d.now))
        d.wait(.5); self.assertTrue(c.ready(d.c.roster, d.now))

    def test_kept_check_ins_fill_the_next_player_setup(self):
        d = Desk(); [d.press(k) for k in ('k0', 'k1', 'k2', 'k3')]
        d.c.close(True, d.now)
        before = d.seats()
        d.devices['k1'].connected = False
        roster = d.c.open(3, False, d.now, d.devices)
        kept = [(s.source, s.key) for s in roster.seats]
        expected = [x if x[1] != 'k1' else ('empty', None) for x in before[:3]]
        self.assertEqual(kept, expected)
        roster = d.c.open(4, True, d.now, d.devices, keep=False)
        self.assertEqual([s.source for s in roster.seats], ['empty']*4)

    def test_a_selection_without_player_setup_uses_kept_check_ins_or_connection_order(self):
        d = Desk(); [d.press(k) for k in ('k0', 'k1', 'k2', 'k3')]
        d.c.close(True, d.now)
        self.assertIs(d.c.select(4, True, d.now, d.devices), d.c.roster, 'the roster Player Setup just committed')
        roster = d.c.select(3, False, d.now, d.devices)
        self.assertEqual([s.source for s in roster.seats], ['hub']*3)
        d.devices['k3'].connected = False
        d.c.step(d.now, d.devices, [])   # k3 is seat 2 here: lost
        roster = d.c.select(4, False, d.now, d.devices)
        self.assertEqual([s.source for s in roster.seats], ['default', 'default', 'classic', 'classic'])

    def test_double_drive_is_reported_once_per_pair(self):
        d = Desk(humans=3, team_mode=False); d.press('k0')
        d.devices['k0'].native_port = 1; d.devices['k0'].native_confirmed = True
        d.wait(.1); d.wait(.1)
        double = [m for m in d.messages() if m[1] == 'TTM-CTRL-24']
        self.assertEqual(double, [('warning', 'TTM-CTRL-24', 'double', dict(name='Pad 0', n=3, k=1))])

    def test_a_controller_without_layout_is_reported_once_per_guid_during_player_setup(self):
        d = Desk(devices=table(k3=dict(mapped=False)))
        d.press('k3', 0x10000000); d.press('k3', 0x10000000)
        self.assertEqual([m[1] for m in d.messages()], ['TTM-CTRL-21'])
        self.assertEqual(d.seats(), [('empty', None)]*4)

    def test_the_roster_line_names_every_player(self):
        devices = table(); roster = c.Roster(4, 'three_or_more')
        for seat, (source, key) in zip(roster.seats, (('native', 'k0'), ('pseudo', 'pcsx2:2'), ('hub', 'k1'), ('empty', None))):
            seat.source, seat.key, seat.name = source, key, devices[key].display if key in devices else ''
        self.assertEqual(c.roster_line(roster, devices),
                         'Players: P1 Pad 0 via PCSX2 port 1 (pass-through); P2 keyboard or custom binding via PCSX2 port 2 '
                         '(pass-through); P3 Pad 1 (mod); P4 empty.')


if __name__ == '__main__':unittest.main()
