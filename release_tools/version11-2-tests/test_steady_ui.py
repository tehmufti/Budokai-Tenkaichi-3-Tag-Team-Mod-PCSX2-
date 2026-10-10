"""Session telemetry must not destroy online controls or discard their drafts."""
import copy
import unittest

import test_responsive_menu as responsive
import kit_lobby_ui as ui

descendants = responsive.descendants

class SteadyTests(unittest.TestCase):
    setUp = responsive.ResizeTests.setUp
    tearDown = responsive.ResizeTests.tearDown
    settle = responsive.ResizeTests.settle

    def identities(self, parent):
        return [str(widget) for widget in descendants(parent)]

    def test_ping_ready_and_warming_preserve_controls_draft_scroll_and_equipment_dialog(self):
        self.app.on_state(copy.deepcopy(self.state))
        self.app.root.geometry(f'{ui.px(640)}x{ui.px(360)}')
        self.settle()
        self.app.rename_var.set('Draft name')
        self.app.viewport.canvas.yview_moveto(.35)
        scroll = self.app.viewport.canvas.yview()
        before = self.identities(self.app.body)
        self.app.open_potara_picker(0,1)
        picker = self.app.potara_picker
        draft = list(picker['draft'])
        events = []
        self.app.root.bind('<Destroy>', lambda event: events.append(str(event.widget)), add='+')
        for n in range(30):
            state = copy.deepcopy(self.state)
            for member in state['lobby']['members']:
                member.update(rtt_ms=10+n, ready=bool(n%2), can_prepare=bool(n%2))
            state['lobby']['warm'] = dict(state='warming', eta_s=50-n, pct=n*2)
            self.app.on_state(state)
            self.app.root.update_idletasks()
        self.settle()
        self.assertEqual(before, self.identities(self.app.body))
        self.assertEqual(events, [])
        self.assertEqual(self.app.rename_var.get(), 'Draft name')
        self.assertEqual(picker['draft'], draft)
        self.assertTrue(picker['win'].winfo_exists())
        self.assertAlmostEqual(scroll[0], self.app.viewport.canvas.yview()[0], places=2)
        self.assertIn('21', self.app.warm_label.cget('text'))

    def test_ownership_and_rename_still_update_people_and_buttons(self):
        self.app.on_state(copy.deepcopy(self.state))
        self.settle()
        entry = self.app.rename_entry
        state = copy.deepcopy(self.state)
        state['lobby']['match']['teams'][0][0]['owner'] = None
        next(m for m in state['lobby']['members'] if m['id'] == 1)['name'] = 'New name'
        self.app.on_state(state)
        self.settle()
        self.assertIs(entry, self.app.rename_entry)
        self.assertEqual(self.app.rename_var.get(), 'New name')
        self.assertIn('New name', self.app.member_labels[1][0].cget('text'))
        self.assertIn(self.app.T('room.watching'), self.app.member_labels[1][1].cget('text'))
        self.assertNotIn(self.app.watch_button, self.app.lobby_buttons.widgets)

    def test_checks_update_in_place_and_results_do_not_redraw_unchanged_values(self):
        state = copy.deepcopy(self.state)
        state.update(phase='check', checks=[dict(key='iso', ok=None, note='Checking disc')])
        self.app.on_state(state)
        self.settle()
        before = self.identities(self.app.check_box)
        state['checks'][0].update(ok=True, note='Disc ready')
        self.app.on_state(state)
        self.settle()
        self.assertEqual(before, self.identities(self.app.check_box))
        self.assertEqual(self.app.check_rows[0][1].cget('text'), 'Disc ready')
        state.update(phase='results', results=dict(winner=1, how='ko', seconds=60),
                     vote=dict(left_s=8, agreed=[], players=[1,2]))
        self.app.on_state(state)
        self.settle()
        updates = []
        original = self.app.res_winner.configure
        self.app.res_winner.configure = lambda **options: (updates.append(options), original(**options))[-1]
        for _ in range(100):
            self.app.update_results()
        self.assertEqual(updates, [])

    def test_hub_score_updates_preserve_challenge_choice(self):
        state = copy.deepcopy(self.state)
        state.update(phase='fight', status=dict(slot=0), lobby=dict(hub=dict(rows=[
            dict(i=0,name='Goku',member=1,kills=0,deaths=0,wins=0),
            dict(i=1,name='Vegeta',member=2,kills=0,deaths=0,wins=0),
            dict(i=2,name='Piccolo',member=3,kills=0,deaths=0,wins=0)],
            open=0, parked=0, duel=None, challenges=[], feed=[])))
        self.app.on_state(state)
        self.settle()
        before = self.identities(self.app.hub_box)
        choice = next(w for w in descendants(self.app.hub_box) if isinstance(w,ui.ttk.Combobox))
        choice.set('Piccolo')
        state['lobby']['hub']['rows'][1].update(kills=3,down=True,engaged=True)
        state['lobby']['hub']['feed'] = ['Vegeta defeated Goku']
        self.app.on_state(state)
        self.settle()
        self.assertEqual(before, self.identities(self.app.hub_box))
        self.assertEqual(choice.get(), 'Piccolo')
        self.assertEqual(self.app.hub_score_labels[1][1].cget('text'), '3')
        self.assertEqual(int(self.app.hub_score_labels[1][0].grid_info()['row']), 0)


if __name__ == '__main__':
    unittest.main()
