"""Exercise the actual equipment window without starting a game or network."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'bt3-multifighter/online/netplay'))
import kit_catalog
from support import catalog, ui_available
import kit_lobby
import kit_lobby_ui
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


@unittest.skipUnless(ui_available(), "Tk display unavailable")
class PickerTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.app = kit_lobby_ui.App(self.client, ttm_online.build_parser().parse_args([]))
        self.app.root.withdraw()
        self.app.catalog = catalog()
        self.lobby = kit_lobby.Lobby()
        self.guest = self.lobby.join('Guest')
        self.app.state = dict(role='host', me=1, lobby=copy.deepcopy(self.lobby.snapshot()))
        self.client.sent.clear()

    def tearDown(self):
        self.app.root.update_idletasks()
        for timer in self.app.root.tk.call('after', 'info'):
            command = str(self.app.root.tk.call('after', 'info', timer)[0])
            if command in (self.app.root._tclCommands or []):
                self.app.root.after_cancel(timer)
        self.app.root.destroy()

    def select(self, ident):
        picker = self.app.potara_picker
        picker['available'].selection_clear(0, 'end')
        picker['available'].selection_set(picker['shown'].index(ident))
        picker['add']()

    def test_host_can_equip_cpu_and_cancel_is_a_draft(self):
        self.app.open_potara_picker(0, 0)
        self.select(2)
        self.select(124)
        self.select(137)
        picker = self.app.potara_picker
        self.assertEqual(picker['draft'], [2, 124, 137])
        self.select(1)  # Another attack upgrade is rejected, preserving the draft.
        self.assertEqual(picker['draft'], [2, 124, 137])
        picker['win'].destroy()
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.app.match()['teams'][0][0].get('potaras', []), [])
        self.app.open_potara_picker(0, 0)
        self.select(2)
        self.app.potara_picker['ok']()
        self.assertEqual(self.client.sent[-1]['potaras'], [2])

    def test_guest_can_only_save_owned_fighter_and_stale_pick_is_not_sent(self):
        self.app.state.update(role='guest', me=self.guest)
        self.app.open_potara_picker(0, 0)
        self.app.potara_picker['ok']()
        self.assertEqual(self.client.sent, [])
        self.app.match()['teams'][0][0]['owner'] = self.guest
        self.app.open_potara_picker(0, 0)
        self.select(2)
        self.app.potara_picker['ok']()
        self.assertEqual(self.client.sent[-1]['potaras'], [2])
        self.client.sent.clear()
        self.app.open_potara_picker(0, 0)
        self.app.state['lobby'] = copy.deepcopy(self.app.state['lobby'])
        self.app.match()['teams'][0][0]['costume'] = 1
        self.app.potara_picker['ok']()
        self.assertEqual(self.client.sent, [])

    def test_spanish_picker_keeps_controls_inside_small_window(self):
        self.app.lang = 'es'
        self.app.root.deiconify()
        self.app.root.update()
        self.app.open_potara_picker(0, 0)
        picker = self.app.potara_picker
        picker['win'].geometry('620x410')
        picker['win'].deiconify()
        picker['win'].update()
        picker['search'].set('Training')
        self.assertIn(124, picker['shown'])
        self.assertNotIn(2, picker['shown'])
        self.assertGreater(picker['available'].winfo_height(), 40)
        self.assertLess(picker['available'].winfo_height(), picker['win'].winfo_height())


if __name__ == '__main__':
    unittest.main()
