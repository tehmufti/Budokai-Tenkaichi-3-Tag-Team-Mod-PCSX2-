"""Resize the real lobby with long labels and full teams; no game or network."""
import copy
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'bt3-multifighter/online/netplay'))
import kit_catalog
from support import catalog, ui_available
import kit_lobby
import kit_lobby_ui as ui
import ttm_online
from test_potara_picker import Client


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@unittest.skipUnless(ui_available(), "Tk display unavailable")
class ResizeTests(unittest.TestCase):
    def setUp(self):
        self.app = ui.App(Client(), ttm_online.build_parser().parse_args([]))
        self.errors = []
        self.app.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.app.update_overlay = lambda: None
        self.app.catalog = catalog()
        lobby = kit_lobby.Lobby(host_name='Long Display Name')
        guest = lobby.join('Another Player')
        lobby.match['teams'] = [[dict(character=54, costume=0, owner=None, potaras=[2,124,137])
                                 for _ in range(5)] for _ in range(2)]
        lobby.match['teams'][0][0]['owner'] = 1
        lobby.match['teams'][1][0]['owner'] = guest
        self.state = dict(phase='lobby', role='host', me=1, lang='en', lobby=copy.deepcopy(lobby.snapshot()),
                          services=['cpu_transform'], joinwith=dict(main='192.0.2.15'))

    def settle(self):
        self.app.root.after(650, self.app.root.quit)
        self.app.root.mainloop()
        self.app.root.update_idletasks()
        self.assertEqual(self.errors, [])

    def tearDown(self):
        for timer in self.app.root.tk.call('after', 'info'):
            command = str(self.app.root.tk.call('after', 'info', timer)[0])
            if command in (self.app.root._tclCommands or []):
                self.app.root.after_cancel(timer)
        self.app.root.destroy()

    def assert_full_controls(self, parent):
        for widget in descendants(parent):
            if isinstance(widget, (ui.tk.Button, ui.tk.Label)) and widget.winfo_ismapped():
                if not widget.cget('text'):
                    continue
                with self.subTest(text=widget.cget('text')):
                    self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
                    self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
                    self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), widget.master.winfo_width())
                    if isinstance(widget, ui.tk.Label) and int(widget.cget('width')) == 1:
                        self.assertLessEqual(widget.winfo_pixels(widget.cget('wraplength')), widget.winfo_width())

    def test_host_resize_both_languages_and_restore_wide_layout(self):
        for lang in ('en', 'es'):
            self.state['lang'] = lang
            self.app.on_state(copy.deepcopy(self.state))
            for width, height in ((1220,760), (980,540), (640,360), (1400,850)):
                self.app.root.geometry(f'{ui.px(width)}x{ui.px(height)}')
                self.settle()
                self.assertEqual(self.app.lobby_layout, width >= 1130)
                self.assert_full_controls(self.app.body)
                if width < 1130:
                    self.assertLess(self.app.viewport.canvas.yview()[1], 1)
                    self.app.viewport.canvas.yview_moveto(1)
                    self.settle()
                    self.assertGreater(self.app.viewport.canvas.yview()[0], 0)

    def test_guest_ready_controls_and_long_notice_fit(self):
        self.state.update(role='guest', me=2)
        self.state['lobby']['notice'] = dict(key='notice.invalid_pick', args=dict(what='A long equipment explanation '*12))
        self.app.on_state(copy.deepcopy(self.state))
        self.app.root.geometry(f'{ui.px(640)}x{ui.px(360)}')
        self.settle()
        self.assert_full_controls(self.app.body)
        self.assertIn(self.app.ready_button, self.app.lobby_buttons.widgets)
        self.app.ready_button.invoke()
        self.assertEqual(self.app.client.sent[-1], dict(cmd='ready', ready=True))

    def test_start_checks_loading_and_results_wrap_in_small_window(self):
        self.app.files = dict(integrated=True, iso='A long game filename.iso', bios='Your BIOS.bin')
        self.app.advanced_open = True
        self.app.root.geometry(f'{ui.px(640)}x{ui.px(360)}')
        state = copy.deepcopy(self.state)
        state.update(lang='es', profile=dict(name='Player'),
                     checks=[dict(ok=True, key='iso', note='A long disc information line ' * 9)],
                     match=dict(title='Gogeta and the other fighters in this match ' * 6),
                     progress=dict(step='prep.loading', pct=50, eta_s=5),
                     results=dict(winner=1, how='ko', compared=120, differing=0, seconds=180),
                     vote=dict(left_s=8, agreed=[1,2], players=[1,2]))
        for phase in ('start', 'check', 'preparing', 'fight', 'results'):
            with self.subTest(phase=phase):
                state['phase'] = phase
                self.app.on_state(copy.deepcopy(state))
                self.settle()
                self.assert_full_controls(self.app.body)

    def test_scrolling_survives_picker_close_and_lobby_updates(self):
        self.app.on_state(copy.deepcopy(self.state))
        self.app.root.geometry(f'{ui.px(640)}x{ui.px(360)}')
        self.settle()
        self.app.open_potara_picker(0,1)
        self.app.close_dialog()
        state = copy.deepcopy(self.state)
        state['lobby']['match']['teams'][0][1]['owner'] = 2
        self.app.on_state(state)
        self.settle()
        self.assert_full_controls(self.app.body)
        self.app.viewport.canvas.yview_moveto(0)
        widget = self.app.head_line
        self.assertEqual(self.app.scroll(type('Wheel', (), dict(widget=widget, delta=-120, num=0))()), 'break')
        self.assertGreater(self.app.viewport.canvas.yview()[0], 0)


if __name__ == '__main__':
    unittest.main()
