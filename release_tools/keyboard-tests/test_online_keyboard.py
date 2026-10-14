"""Online keyboard profiles stay local and cannot disrupt a running match."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path(__import__('os').environ.get('KEYBOARD_TEST_ROOT',ROOT))
sys.path.insert(0,str(SOURCE/'bt3-multifighter/online/netplay'))
import kit_emu as em
import kit_controller as controller
import kit_ident
import keyboard_bindings as kb

class OnlineBindings(unittest.TestCase):
    def test_legacy_keyboard_and_sdl_are_unchanged_without_profile(self):
        self.assertEqual(em.pad1_bindings('keyboard'),{em.PAD_NAMES[key]:'Keyboard/'+value[3] for key,value in em.PAD1_KEYS.items()})
        self.assertEqual(em.pad1_bindings('SDL-1')['Square'],'SDL-1/FaceWest')
        self.assertEqual(em.pad1_bindings('SDL-1',kb.DEFAULT),em.pad1_bindings('SDL-1'))
    def test_different_peer_keys_do_not_change_simulation_identity(self):
        other=dict(kb.DEFAULT,Square='Z',LUp='I')
        template='[Pad1]\nType = DualShock2\nSquare = Keyboard/J\n[Hotkeys]\nLoadStateFromSlot = Keyboard/F3\n'
        ini=[]
        for mapping in (kb.DEFAULT,other):
            value=em.make_ini(template,pine_slot=28460,pad1=em.pad1_bindings('keyboard',mapping),bios_name='test.bin')
            self.assertFalse(kit_ident.forced_problems(value))
            self.assertEqual(kb.ini_values(value)[('Pad1','Square')],['Keyboard/'+mapping['Square']])
            self.assertNotIn('LoadStateFromSlot = Keyboard/F3',value)
            self.assertEqual(kb.ini_values(value)[('Hotkeys','TogglePause')],['Keyboard/Pause'])
            ini.append(value)
        # Input mappings are intentionally omitted from the emulator compatibility rules.
        keys={(section,key):value for section,key,value in kit_ident.FORCED}
        parsed=[kb.ini_values(value) for value in ini]
        self.assertEqual({pair:parsed[0].get(pair) for pair in keys},{pair:parsed[1].get(pair) for pair in keys})
    def test_controller_validates_before_mutating_and_keeps_config_local(self):
        c=controller.Controller.__new__(controller.Controller)
        c.cfg={'pad':'SDL-0'};c.phase='start';c.emulator=None;c.fail=Mock();c.invalidate_preboot=Mock()
        c.save_settings=Mock(return_value=True);c.dirty=False
        c.cmd_setup({'pad':'keyboard','keyboard_bindings':kb.DEFAULT})
        self.assertEqual(c.cfg['keyboard_bindings'],kb.DEFAULT);c.save_settings.assert_called_once();c.invalidate_preboot.assert_called_once()
        current=copy.deepcopy(c.cfg);c.cmd_setup({'keyboard_bindings':{'Square':'F8'}})
        self.assertEqual(c.cfg,current);self.assertTrue(c.fail.called)
        c.phase='fight';c.fail.reset_mock();c.cmd_setup({'keyboard_bindings':dict(kb.DEFAULT,Square='Z')})
        self.assertEqual(c.cfg,current);self.assertTrue(c.fail.called)
    def test_binding_edit_restarts_only_owned_idle_emulator(self):
        c=controller.Controller.__new__(controller.Controller)
        c.cfg={'pad':'keyboard','keyboard_bindings':dict(kb.DEFAULT)};c.phase='start';c.fail=Mock();c.invalidate_preboot=Mock()
        c.save_settings=Mock(return_value=True);c.emulator=Mock();c.emulator.alive.return_value=True
        old=c.emulator;c.cmd_setup({'keyboard_bindings':dict(kb.DEFAULT,Square='Z')})
        old.stop.assert_called_once();self.assertIsNone(c.emulator)
    def test_saved_keyboard_settings_survive_reloading_without_leaking_other_fields(self):
        with tempfile.TemporaryDirectory(dir=SOURCE/'release_tools') as folder,patch.object(controller.kit_paths,'DATA',Path(folder)):
            c=controller.Controller.__new__(controller.Controller)
            c.cfg={'pad':'keyboard','keyboard_bindings':dict(kb.DEFAULT),'private_other_field':'not saved'}
            self.assertTrue(c.save_settings())
            c.args=SimpleNamespace(hidden=False,keyboard=False);c.detect_lang=Mock(return_value='en')
            loaded=c.load_settings();self.assertEqual(loaded['keyboard_bindings'],kb.DEFAULT)
            self.assertNotIn('private_other_field',loaded)
    def test_hidden_preparation_keeps_legacy_bot_keys(self):
        import ast
        tree=ast.parse((SOURCE/'bt3-multifighter/online/netplay/kit_controller.py').read_text())
        setup=next(node for node in __import__('ast').walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                   and node.func.attr=='setup' and any(key.arg=='keyboard_bindings' for key in node.keywords))
        expression=next(key.value for key in setup.keywords if key.arg=='keyboard_bindings')
        self.assertIsInstance(expression,ast.IfExp);self.assertIsNone(expression.body.value)
        self.assertEqual(ast.unparse(expression.test),'a.hidden')

class MenuBindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import kit_lobby_ui
        cls.ui=kit_lobby_ui
    def setUp(self):
        fixture_path=SOURCE/'release_tools/online-menu-tests/test_menu_stability.py'
        spec=importlib.util.spec_from_file_location('keyboard_menu_fixture',fixture_path)
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        self.fixture=fixture
        if not fixture.ui_available():self.skipTest('Tk unavailable')
        self.app=self.ui.App(fixture.Client(),fixture.ttm_online.build_parser().parse_args([]))
        self.app.state={'phase':'start','lang':'en','settings':{'pad':'SDL-0'},'profile':{'name':'Player'}}
        self.app.build_start();self.app.root.update()
        self.addCleanup(self.close)
    def close(self):
        self.app.alive=False
        for timer in self.app.root.tk.call('after','info'):
            try:self.app.root.after_cancel(timer)
            except self.ui.tk.TclError:pass
        self.app.root.destroy()
    def test_keyboard_is_visible_without_advanced_and_is_saved(self):
        self.assertFalse(self.app.advanced_open)
        widgets=list(self.fixture.descendants(self.app.root))
        button=next(w for w in widgets if hasattr(w,'cget') and w.winfo_class() in ('Button','TButton') and w.cget('text')==self.app.T('input.bindings'))
        self.assertTrue(button.winfo_ismapped())
        self.app.adv['pad'].set(self.app.T('adv.pad.keyboard'))
        fields=self.app.save_start_fields();self.assertEqual(fields['pad'],'keyboard')
    def test_editor_selects_keyboard_and_sends_valid_saved_profile(self):
        import keyboard_controls_ui
        with patch.object(keyboard_controls_ui,'show',return_value=dict(kb.DEFAULT)) as dialog:
            self.app.edit_keyboard()
        self.assertEqual(dialog.call_args.args[1],kb.DEFAULT)
        sent=self.app.client.sent[-1];self.assertEqual(sent['pad'],'keyboard');self.assertEqual(sent['keyboard_bindings'],kb.DEFAULT)

if __name__=='__main__':unittest.main()
