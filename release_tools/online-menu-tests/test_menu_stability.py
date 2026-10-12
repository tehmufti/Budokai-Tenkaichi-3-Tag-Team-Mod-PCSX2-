"""The online menus stay steady: navigation, session packets, clicks, dialogs and resizing (no game or network).

Synthetic fixtures only (no disc, BIOS or emulator). GUI cases skip when no Tk display is available.
Run: python -m unittest discover -s release_tools/online-menu-tests -p 'test_*.py'
"""
import copy
import os
import random
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_catalog  # noqa: E402
import kit_lobby  # noqa: E402
import kit_lobby_ui as ui  # noqa: E402
import kit_settings  # noqa: E402
import ttm_online  # noqa: E402


def ui_available():
    if os.name != 'nt' and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        root = ui.tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except ui.tk.TclError:
        return False


def catalog():
    return kit_catalog.View(dict(dir='', tables_sha256='a' * 64, grid=[
        dict(row=0, col=i, base=c, forms=[c]) for i, c in enumerate((0, 22, 54, 107))],
        characters=[dict(id=c, name='Test Fighter ' + str(c), selectable=True, costumes=2, portrait='', forms=[c])
                    for c in (0, 22, 54, 107)],
        stages=[dict(id=0, name='Test Stage', thumb='', tested=True)],
        potaras=dict(slots=8, points=7, items=[dict(id=2, name='Test attack', cost=3, kind=0, group=0,
                                                    stats=[15, 0, 0, 0], effects='00' * 16)])))


class Client:
    closed = False

    def __init__(self):
        self.sent = []

    def send(self, command, **fields):
        self.sent.append(dict(cmd=command, **fields))

    def poll(self, timeout=0):
        return []

    def close(self):
        pass


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@unittest.skipUnless(ui_available(), 'Tk display unavailable')
class MenuStability(unittest.TestCase):
    def setUp(self):
        self.app = ui.App(Client(), ttm_online.build_parser().parse_args([]))
        self.errors = []
        self.app.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.app.update_overlay = lambda: None
        self.app.catalog = catalog()
        lobby = kit_lobby.Lobby(host_name='Host')
        self.guest = lobby.join('Guest')
        lobby.join('Watcher')
        lobby.match['teams'] = [[dict(character=0, costume=0, owner=None, potaras=[]) for _ in range(3)],
                                [dict(character=107, costume=0, owner=None, potaras=[]) for _ in range(3)]]
        lobby.match['teams'][0][0]['owner'] = 1
        lobby.match['teams'][1][0]['owner'] = self.guest
        self.lobby_state = dict(phase='lobby', role='host', me=1, lang='en', lobby=copy.deepcopy(lobby.snapshot()),
                                services=['cpu_transform'], joinwith=dict(main='192.0.2.15'),
                                profile=dict(name='Host', local={}), kit='test')

    def tearDown(self):
        self.app.alive = False
        for timer in self.app.root.tk.call('after', 'info'):
            try:
                self.app.root.after_cancel(timer)
            except ui.tk.TclError:
                pass
        try:
            self.app.root.destroy()
        except ui.tk.TclError:
            pass

    def settle(self, ms=400):
        self.app.root.after(ms, self.app.root.quit)
        self.app.root.mainloop()
        self.app.root.update_idletasks()
        self.assertEqual(self.errors, [])

    def state(self, **changes):
        state = copy.deepcopy(self.lobby_state)
        state.update(changes)
        return state

    def screens(self):
        """One state per screen of a session's life."""
        lobby = self.state()
        return [
            self.state(phase='start', lobby=None),
            self.state(phase='check', lobby=None, checks=[dict(key='iso', ok=True, note='disc'),
                                                          dict(key='kit', ok=None, note='')]),
            lobby,
            self.state(phase='preparing', match=dict(title='A vs B'), progress=dict(step='prep.loading', pct=30)),
            self.state(phase='loading', match=dict(title='A vs B'), progress=dict(step='load.waiting', pct=90)),
            self.state(phase='fight', match=dict(title='A vs B'), status=dict(frame=100, slot=0, rtt_ms=20, delay=2)),
            self.state(phase='results', match=dict(title='A vs B', seats={'1': 0}),
                       results=dict(winner=1, how='ko', compared=100, differing=0, seconds=60),
                       vote=dict(left_s=8, agreed=[], players=[1, 2], epoch=1)),
        ]

    # ---- navigation ------------------------------------------------------------------------------------------------
    def test_navigation_stress_keeps_drafts_closes_dialogs_and_does_not_leak(self):
        app = self.app
        app.chat_rows = [dict(at='10:00', who='Host', text='hello')]
        app.chat_var.set('typed but not sent')
        app.name_var.set('Draft name')
        expected = {'start': 'start', 'check': 'check', 'lobby': 'lobby', 'preparing': 'prep', 'loading': 'prep',
                    'fight': 'fight', 'results': 'results'}
        rng = random.Random(7)
        counts = []
        for loop in range(6):
            for state in self.screens():
                state = copy.deepcopy(state)
                state['lang'] = rng.choice(('en', 'es'))
                app.on_state(state)
                if state['phase'] == 'lobby':
                    app.open_rules()                        # a dialog left open when the screen changes
                self.assertEqual(app.screen, expected[state['phase']])
                app.root.update()
            counts.append(sum(1 for _ in descendants(app.root)))
        self.settle()
        tops = [w for w in app.root.winfo_children() if isinstance(w, ui.tk.Toplevel)]
        self.assertEqual(tops, [])                           # every dialog closed with its screen
        self.assertLessEqual(max(counts) - min(counts), 5)   # no widgets pile up across loops
        self.assertEqual(app.chat_var.get(), 'typed but not sent')
        self.assertEqual(app.name_var.get(), 'Draft name')

    def test_language_switch_and_advanced_keep_typed_name(self):
        app = self.app
        app.on_state(self.state(phase='start', lobby=None))
        app.name_var.set('New name')
        app.toggle_adv()
        app.toggle_lang()
        app.toggle_adv()
        self.settle()
        self.assertEqual(app.name_var.get(), 'New name')
        self.assertEqual(app.lang, 'es')
        # The session's echo of the saved name is shown only while the player has not typed something else.
        app.save_start_fields()
        app.on_state(self.state(phase='start', lobby=None, lang='es', profile=dict(name='New name', local={})))
        self.assertEqual(app.name_var.get(), 'New name')

    def test_stale_question_is_ignored_after_the_screen_changed(self):
        app = self.app
        guest = self.state(role='guest', me=self.guest)
        app.on_state(guest)

        def confirm(text):
            app.on_state(self.state(role='guest', me=self.guest, phase='loading', progress=dict(step='load.waiting')))
            return True
        app.confirm = confirm
        app.client.sent.clear()
        app.leave()
        self.assertEqual(app.client.sent, [])

    def test_pump_survives_a_drawing_error_and_rebuilds(self):
        app = self.app
        app.on_state(self.screens()[-1])
        boom = {'n': 0}
        real = app.update_results

        def flaky():
            boom['n'] += 1
            if boom['n'] == 2:
                raise ValueError('one bad packet')
            return real()
        app.update_results = flaky
        app.root.after(1400, app.root.quit)
        app.root.mainloop()
        self.assertGreater(boom['n'], 5)                     # the pump kept running and the screen came back
        self.assertEqual(app.screen, 'results')

    # ---- session packets -----------------------------------------------------------------------------------------
    def test_roster_and_rule_changes_update_in_place(self):
        app = self.app
        app.on_state(self.state())
        self.settle()
        before = [str(w) for w in descendants(app.body)]
        combo = app.rule_widgets['bgm']
        state = self.state()
        state['lobby']['match']['teams'][1][2].update(character=54, costume=1)
        state['lobby']['match']['bgm'] = 4
        state['lobby']['match']['stage'] = 'random'
        app.on_state(state)
        self.settle()
        self.assertEqual(before, [str(w) for w in descendants(app.body)])
        self.assertIs(combo, app.rule_widgets['bgm'])
        self.assertEqual(combo.get(), app.T('room.track', n=5))
        self.assertIn('54', app.team_rows[(1, 2)].name.cget('text'))
        # A structural change (team size) rebuilds only the teams panel.
        state = copy.deepcopy(state)
        state['lobby']['match']['teams'][0].append(dict(character=22, costume=0, owner=None, potaras=[]))
        people = [str(w) for w in descendants(app.people)]
        app.on_state(state)
        self.settle()
        self.assertIn((0, 3), app.team_rows)
        self.assertEqual(people, [str(w) for w in descendants(app.people)])

    def test_fighter_picker_does_not_silently_overwrite_a_remote_change(self):
        app = self.app
        app.on_state(self.state())
        app.open_picker(1, 1)
        app.picker['pick'](22)
        state = self.state()
        state['lobby']['match']['teams'][1][1].update(owner=self.guest, character=54)
        app.on_state(state)
        app.client.sent.clear()
        app.picker['ok']()
        self.assertEqual(app.client.sent, [])                # first OK only shows what changed
        app.picker['ok']()
        self.assertEqual(app.client.sent[-1], dict(cmd='fighter', team=1, index=1, character=22, costume=0))

    def test_guest_picker_closes_when_its_fighter_is_taken_away(self):
        app = self.app
        guest = self.state(role='guest', me=self.guest)
        app.on_state(guest)
        app.open_picker(1, 0)
        self.assertTrue(app.dialog.winfo_exists())
        state = self.state(role='guest', me=self.guest)
        state['lobby']['match']['teams'][1][0]['owner'] = None
        app.on_state(state)
        self.assertIsNone(app.dialog)

    def test_guest_rules_dialog_follows_the_host(self):
        app = self.app
        app.on_state(self.state(role='guest', me=self.guest))
        app.open_rules()
        key = next(k for k, w in app.setting_widgets.items() if isinstance(w, ui.ttk.Combobox))
        kind, options = kit_settings.choices(key)
        values = kit_settings.gameplay_expand(self.lobby_state['lobby']['match'].get('gameplay'))
        other = next(o for o in options if o != values.get(key))
        state = self.state(role='guest', me=self.guest)
        state['lobby']['match']['gameplay'] = dict(state['lobby']['match'].get('gameplay') or {}, **{key: other})
        app.on_state(state)
        self.assertEqual(app.setting_widgets[key].get(), kit_settings.value_text(key, other, app.lang))

    def test_chat_appends_lines_and_keeps_the_typed_message(self):
        app = self.app
        app.chat_rows = [dict(at='10:00', who='A', text='one')]
        app.on_state(self.state())
        app.chat_var.set('draft')
        for n in range(40):
            app.chat_rows.append(dict(at='10:01', who='B', text=f'line {n}'))
            app.draw_chat()
        text = app.chat_text.get('1.0', 'end-1c').splitlines()
        self.assertEqual(len(text), 30)
        self.assertTrue(text[-1].endswith('line 39'))
        self.assertEqual(app.chat_var.get(), 'draft')

    # ---- clicks --------------------------------------------------------------------------------------------------
    def test_repeated_clicks_send_one_command(self):
        app = self.app
        app.on_state(self.state(phase='start', lobby=None))
        for _ in range(5):
            app.host_button.invoke()
        self.assertEqual(sum(m['cmd'] == 'host' for m in app.client.sent), 1)
        state = self.state()
        for m in state['lobby']['members']:
            m['ready'] = True
        app.on_state(state)
        for _ in range(4):
            app.start_button.invoke()
        self.assertEqual(sum(m['cmd'] == 'start' for m in app.client.sent), 1)
        app.on_state(self.state(role='guest', me=self.guest))
        app.client.sent.clear()
        app.ready_button.invoke()
        app.ready_button.invoke()                           # waits for the session's answer
        self.assertEqual([m['ready'] for m in app.client.sent if m['cmd'] == 'ready'], [True])
        state = self.state(role='guest', me=self.guest)
        next(m for m in state['lobby']['members'] if m['id'] == self.guest)['ready'] = True
        app.on_state(state)
        app.ready_button.invoke()                           # answered: the next click un-readies
        self.assertEqual([m['ready'] for m in app.client.sent if m['cmd'] == 'ready'], [True, False])

    def test_spin_box_sends_one_change_per_pause(self):
        app = self.app
        app.on_state(self.state())
        app.open_rules()
        spin = next(w for w in app.setting_widgets.values() if isinstance(w, ui.ttk.Spinbox))
        app.client.sent.clear()
        spin.focus_force()
        for _ in range(10):                                  # ten quick clicks on the arrow
            spin.event_generate('<<Increment>>')
        self.settle(700)
        sent = [m for m in app.client.sent if m['cmd'] == 'rules']
        self.assertLessEqual(len(sent), 2)
        self.assertEqual(list(sent[-1]['gameplay'].values())[0], spin.get())

    # ---- errors --------------------------------------------------------------------------------------------------
    def test_one_error_window_that_follows_the_session(self):
        app = self.app
        start = self.state(phase='start', lobby=None)
        app.on_state(dict(start, error=dict(code='A', en='First problem', remedies=['logs'])))
        first = app.error_window
        app.on_state(dict(start, error=dict(code='B', en='Second problem', remedies=[])))
        self.assertIs(app.error_window, first)
        self.assertEqual(sum(isinstance(w, ui.tk.Toplevel) for w in app.root.winfo_children()), 1)
        app.on_state(start)                                  # dismissed elsewhere (or a new attempt began)
        self.assertIsNone(app.error_window)
        app.on_state(dict(start, error=dict(code='A', en='First problem', remedies=['logs'])))
        self.assertIsNotNone(app.error_window)               # the same problem again is shown again

    def test_resizing_after_the_session_was_lost_is_harmless(self):
        app = self.app
        app.on_state(self.state())
        app.lost()
        for size in ('900x600', '1300x800', '700x450'):
            app.root.geometry(size)
            self.settle(120)
        self.assertEqual(app.screen, 'lost')

    # ---- layout --------------------------------------------------------------------------------------------------
    def test_flow_height_is_stable(self):
        app = self.app
        app.on_state(self.state())
        self.settle()
        flow = app.lobby_buttons
        flow.arrange()
        height = int(flow.cget('height'))
        flow.positions = None                                # force the buttons to be placed again
        flow.arrange()
        self.assertEqual(int(flow.cget('height')), height)

    def test_resize_stress_keeps_actions_pinned_and_controls_whole(self):
        app = self.app
        rng = random.Random(3)
        for lang in ('en', 'es'):
            app.on_state(self.state(lang=lang))
            last = None
            for _ in range(10):
                width, height = rng.randint(640, 1500), rng.randint(360, 950)
                app.root.geometry(f'{ui.px(width)}x{ui.px(height)}')
                app.root.update()                            # a drag: no settling between sizes
            for width, height in ((1400, 860), (1100, 700), (1120, 700), (1135, 700), (980, 540), (640, 360)):
                app.root.geometry(f'{ui.px(width)}x{ui.px(height)}')
                self.settle(500)
                body = app.body.winfo_width()
                if body >= ui.px(ui.WIDE_ON):
                    self.assertTrue(app.lobby_layout)
                elif body < ui.px(ui.WIDE_OFF):
                    self.assertFalse(app.lobby_layout)
                else:                                        # between the thresholds the layout keeps its state
                    self.assertEqual(app.lobby_layout, last)
                last = app.lobby_layout
                for button in app.lobby_buttons.widgets:     # the actions never scroll away
                    self.assertTrue(button.winfo_ismapped())
                    y = button.winfo_rooty() - app.root.winfo_rooty()
                    self.assertLessEqual(y + button.winfo_height(), app.root.winfo_height())
                for widget in descendants(app.body):
                    if isinstance(widget, (ui.tk.Button, ui.tk.Label)) and widget.winfo_ismapped() and \
                            widget.cget('text'):
                        where = f'{lang} {width}x{height} {widget} {widget.cget("text")!r}'
                        self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth(), where)
                        self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), widget.master.winfo_width(),
                                             where)

    def test_dialogs_keep_their_buttons_when_small(self):
        app = self.app
        app.on_state(self.state())
        for opener in (lambda: app.open_picker(0, 0), app.open_stage_picker, lambda: app.open_potara_picker(0, 0)):
            opener()
            win = app.dialog
            win.geometry('300x200')                          # below the minimum: the minimum wins
            self.settle(300)
            for button in (w for w in descendants(win) if isinstance(w, ui.tk.Button) and w.cget('text')):
                self.assertTrue(button.winfo_ismapped(), button.cget('text'))
                y = button.winfo_rooty() - win.winfo_rooty()
                self.assertLessEqual(y + button.winfo_height(), win.winfo_height(), button.cget('text'))
            app.close_dialog()


if __name__ == '__main__':
    unittest.main()
