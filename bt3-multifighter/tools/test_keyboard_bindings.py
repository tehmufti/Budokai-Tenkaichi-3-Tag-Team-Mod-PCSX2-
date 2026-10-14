"""Keyboard profiles preserve controllers, hotkeys and independent player controls."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import keyboard_bindings as k

class BindingsTests(unittest.TestCase):
    def test_physical_keys_match_pcsx2_names(self):
        for raw,wanted in [('a','A'),('A','A'),('space','Space'),('Return','Return'),('kp_enter','NumpadEnter'),
                           ('KP_4','Numpad4'),('KP_Add','NumpadPlus'),('semicolon','Semicolon'),('colon','Semicolon'),
                           ('Shift_R','Shift'),('ntilde','Ntilde'),('ñ','Ntilde'),('exclam','1')]:
            with self.subTest(raw=raw):self.assertEqual(k.event_key(SimpleNamespace(keysym=raw,keycode=0)),wanted)
        self.assertIsNone(k.event_key(SimpleNamespace(keysym='invalid',keycode=0)))
    def test_windows_keypad_uses_physical_code(self):
        with patch.object(k.os,'name','nt'):
            self.assertEqual(k.event_key(SimpleNamespace(keysym='2',keycode=0x62)),'Numpad2')
            self.assertEqual(k.event_key(SimpleNamespace(keysym='plus',keycode=0x6B)),'NumpadPlus')
    def test_invalid_input_cannot_insert_ini_rows(self):
        for profile in (None,[],{'macro':'Q'},{'Cross':'Q\n[Hotkeys]'},{'Cross':'Keyboard/Q'},{'Cross':True}):
            with self.subTest(profile=profile),self.assertRaises(ValueError):k.validate(profile)
        for key in k.ONLINE_RESERVED:
            with self.assertRaises(ValueError):k.validate({'Cross':key},online=True)
    def test_primary_and_stick_mappings_are_independent(self):
        self.assertEqual(k.bindings(k.DEFAULT,online=True)['LUp'],'Keyboard/W')
        self.assertEqual(k.bindings(k.DEFAULT,online=True)['Up'],'Keyboard/Up')
        self.assertEqual(k.bindings({'Square':'J'})['Cross'],'')
    def test_repeated_rows_are_preserved_and_replaced_without_duplicates(self):
        text='; untouched\r\n[pad1]\r\ncross = SDL-0/FaceSouth\r\nCross = Keyboard/Q\r\n[Hotkeys]\r\nScreenshot = Keyboard/F8\r\n'
        self.assertEqual(k.ini_values(text)[('Pad1','Cross')],['SDL-0/FaceSouth','Keyboard/Q'])
        changed=k.ini_replace(text,{('Pad1','Cross'):['SDL-0/FaceSouth','Keyboard/Space']})
        self.assertEqual(k.ini_values(changed)[('Pad1','Cross')],['SDL-0/FaceSouth','Keyboard/Space'])
        self.assertIn('; untouched',changed);self.assertIn('Screenshot = Keyboard/F8',changed)
    def test_duplicate_notice_allows_deliberate_shared_keys(self):
        self.assertEqual(k.duplicates({'LUp':'W','Up':'W','Cross':''}),{'W':['LUp','Up']})

class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=self.root/'runtime28/inis/PCSX2.ini';self.config.parent.mkdir(parents=True)
        self.config.write_text('[EmuCore]\nEnableCheats = true\n[Pad1]\nType = DualShock2\nSquare = SDL-0/FaceWest\nSquare = Keyboard/Z\nCross = SDL-0/FaceSouth\n[Pad2]\nType = None\nCross = SDL-1/FaceSouth\n[Hotkeys]\nTogglePause = Keyboard/Space\nToggleTurbo = Keyboard/Tab\nScreenshot = Keyboard/F8\nToggleFullscreen = Keyboard/Alt & Keyboard/Return\n')
    def test_launch_without_profile_changes_nothing(self):
        before=self.config.read_bytes();self.assertFalse(k.apply_offline(self.root,self.config));self.assertEqual(self.config.read_bytes(),before)
    def test_pads_hotkeys_and_other_settings_survive_repeated_launches(self):
        k.save_offline('Pad1',k.DEFAULT,self.root);self.assertTrue(k.apply_offline(self.root,self.config))
        values=k.ini_values(self.config.read_text())
        self.assertEqual(values[('Pad1','Square')],['SDL-0/FaceWest','Keyboard/J'])
        self.assertEqual(values[('Pad2','Type')],['None'])
        self.assertEqual(values[('Pad2','Cross')],['SDL-1/FaceSouth'])
        self.assertEqual(values[('Hotkeys','TogglePause')],[''])
        self.assertEqual(values[('Hotkeys','ToggleTurbo')],[''])
        self.assertEqual(values[('Hotkeys','Screenshot')],['Keyboard/F8'])
        self.assertEqual(values[('Hotkeys','ToggleFullscreen')],['Keyboard/Alt & Keyboard/Return'])
        first=self.config.read_bytes();self.assertFalse(k.apply_offline(self.root,self.config));self.assertEqual(self.config.read_bytes(),first)
        k.save_offline('Pad1',{},self.root);k.apply_offline(self.root,self.config)
        values=k.ini_values(self.config.read_text());self.assertEqual(values[('Hotkeys','TogglePause')],['Keyboard/Space'])
        self.assertEqual(values[('Pad1','Square')],['SDL-0/FaceWest'])
    def test_user_hotkey_change_is_not_restored_over(self):
        k.save_offline('Pad1',k.DEFAULT,self.root);k.apply_offline(self.root,self.config)
        self.config.write_text(k.ini_replace(self.config.read_text(),{('Hotkeys','TogglePause'):['Keyboard/P']}))
        k.save_offline('Pad1',{},self.root);k.apply_offline(self.root,self.config)
        self.assertEqual(k.ini_values(self.config.read_text())[('Hotkeys','TogglePause')],['Keyboard/P'])
    def test_two_players_save_atomically_without_losing_other_profile(self):
        k.save_offline_profiles({'Pad1':k.DEFAULT,'Pad2':{'Square':'F'}},self.root)
        k.save_offline('Pad1',{'Square':'Z'},self.root)
        self.assertEqual(k.load_offline(self.root)['pads']['Pad2']['Square'],'F')
        k.apply_offline(self.root,self.config)
        self.assertEqual(k.ini_values(self.config.read_text())[('Pad2','Square')],['Keyboard/F'])
    def test_corrupt_profile_can_be_repaired_without_losing_original(self):
        (self.root/k.FILE).write_text('{broken')
        with self.assertRaises(ValueError):k.apply_offline(self.root,self.config)
        k.save_offline('Pad1',k.DEFAULT,self.root)
        self.assertEqual((self.root/(k.FILE+'.bak')).read_text(),'{broken')
        self.assertEqual(k.load_offline(self.root)['pads']['Pad1']['LUp'],'W')
    def test_backup_values_cannot_insert_extra_sections(self):
        (self.root/k.FILE).write_text(json.dumps({'schema':1,'pads':{},'hotkeys':{'test':{'X\n[Unsafe]':['Keyboard/Q']}}}))
        with self.assertRaises(ValueError):k.load_offline(self.root)
    def test_only_owned_runtime_can_be_written(self):
        k.save_offline('Pad1',k.DEFAULT,self.root)
        with self.assertRaises(ValueError):k.apply_offline(self.root,self.root.parent/'outside.ini')

if __name__=='__main__':unittest.main()
