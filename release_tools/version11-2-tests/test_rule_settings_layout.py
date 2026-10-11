"""The real online settings stay reachable at small sizes without rebuilding controls."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_lobby
import kit_lobby_ui as ui
import kit_settings
import ttm_online


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


class SettingsLayoutTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app = ui.App(Client(), ttm_online.build_parser().parse_args([]))
        except ui.tk.TclError as error:
            self.skipTest(f'Tk display unavailable: {error}')
        self.app.root.withdraw()
        self.errors = []
        self.app.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.app.update_overlay = lambda: None
        lobby = kit_lobby.Lobby(host_name='Host')
        self.app.state = dict(role='host', me=1, lobby=copy.deepcopy(lobby.snapshot()))
        self.app.client.sent.clear()

    def settle(self):
        self.app.root.after(120, self.app.root.quit)
        self.app.root.mainloop()
        self.app.root.update_idletasks()
        self.assertEqual(self.errors, [])

    def tearDown(self):
        self.app.close_dialog()
        for timer in self.app.root.tk.call('after', 'info'):
            command = str(self.app.root.tk.call('after', 'info', timer)[0])
            if command in (self.app.root._tclCommands or []):
                self.app.root.after_cancel(timer)
        self.app.root.destroy()

    def assert_fit(self, win):
        viewport = win.settings_viewport
        self.assertGreater(viewport.winfo_height(), 20)
        for widget in descendants(win):
            if not widget.winfo_ismapped():
                continue
            if isinstance(widget, (ui.tk.Label, ui.ttk.Combobox, ui.ttk.Spinbox)):
                with self.subTest(text=widget.cget('text') if isinstance(widget, ui.tk.Label) else str(widget)):
                    self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
                    self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
                    self.assertGreaterEqual(widget.winfo_rootx(), win.winfo_rootx())
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                         win.winfo_rootx() + win.winfo_width())
        close = next(widget for widget in win.winfo_children() if isinstance(widget, ui.tk.Button))
        self.assertTrue(close.winfo_ismapped())
        self.assertLessEqual(close.winfo_y() + close.winfo_height(), win.winfo_height())

    def test_rules_reflow_scroll_and_preserve_edits_in_both_languages(self):
        for language in ('en', 'es'):
            self.app.lang = language
            self.app.open_rules()
            win = self.app.dialog
            self.settle()
            self.assertLessEqual(win.winfo_width(), self.app.root.winfo_screenwidth())
            self.assertLessEqual(win.winfo_height(), self.app.root.winfo_screenheight())
            widgets = dict(self.app.setting_widgets)
            multiplier = widgets['fusion_potara_health_multiplier']
            self.assertEqual(float(multiplier.cget('increment')), .25)
            multiplier.set('1.75')
            for width, height in ((1360, 720), (960, 540), (640, 360), (360, 300), (1360, 720)):
                win.geometry(f'{ui.px(width)}x{ui.px(height)}')
                self.settle()
                self.assert_fit(win)
                self.assertEqual(widgets, self.app.setting_widgets)
                self.assertEqual(multiplier.get(), '1.75')
                self.assertTrue(all(widget.winfo_exists() for widget in widgets.values()))
                if width < 700:
                    viewport = win.settings_viewport
                    self.assertLess(viewport.canvas.yview()[1], 1)
                    viewport.canvas.yview_moveto(1)
                    self.settle()
                    self.assertGreater(viewport.canvas.yview()[0], 0)
                    self.assertEqual(self.app.scroll(type('Wheel', (), dict(widget=viewport.content,
                                                                          delta=120, num=0))()), 'break')
            multiplier.tk.call(multiplier.cget('command'))
            self.assertIn(dict(cmd='rules', gameplay={'fusion_potara_health_multiplier': '1.75'}),
                          self.app.client.sent)
            self.app.close_dialog()

    def test_guest_rules_stay_read_only_and_display_scrolls(self):
        self.app.state.update(role='guest', me=2)
        self.app.open_rules()
        self.app.dialog.geometry(f'{ui.px(400)}x{ui.px(300)}')
        self.settle()
        self.assert_fit(self.app.dialog)
        self.assertTrue(all(str(widget.cget('state')) == 'disabled' for widget in self.app.setting_widgets.values()))
        self.app.open_display()
        self.app.dialog.geometry(f'{ui.px(400)}x{ui.px(300)}')
        self.settle()
        self.assert_fit(self.app.dialog)
        self.assertEqual(set(self.app.setting_widgets), set(kit_settings.default_local()))
        viewport = self.app.dialog.settings_viewport
        viewport.canvas.yview_moveto(1)
        self.settle()
        self.assertGreater(viewport.canvas.yview()[0], 0)


if __name__ == '__main__':
    unittest.main()
