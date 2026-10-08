import ctypes
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import input_binding as binding
import mod_settings as settings


class FakeSDL:
    """Hotplug enumeration compacts; physical player indices do not."""
    def __init__(self):
        self.devices=[dict(instance=10+i,player=i,buttons=set(),axes=[0]*6) for i in range(4)]
        self.hints={};self.initial_hints=None;self.opened=[];self.closed=[]
        def init(_):self.initial_hints=dict(self.hints);return 0
        def device(pad):return next((d for d in self.devices if d['instance']==pad),None)
        def opening(index):self.opened.append(self.devices[index]['instance']);return self.opened[-1]
        functions={
            'SDL_SetHint':lambda key,value:self.hints.update({key:value}) or 1,
            'SDL_InitSubSystem':init,'SDL_QuitSubSystem':lambda _:None,
            'SDL_NumJoysticks':lambda:len(self.devices),'SDL_IsGameController':lambda index:1,
            'SDL_JoystickGetDeviceInstanceID':lambda index:self.devices[index]['instance'],
            'SDL_GameControllerOpen':opening,'SDL_GameControllerClose':self.closed.append,
            'SDL_GameControllerGetAttached':lambda pad:int(device(pad) is not None),
            'SDL_GameControllerGetPlayerIndex':lambda pad:device(pad)['player'],
            'SDL_GameControllerUpdate':lambda:None,
            'SDL_GameControllerGetButton':lambda pad,button:int(binding.SDL_BUTTONS[button] in device(pad)['buttons']),
            'SDL_GameControllerGetAxis':lambda pad,axis:device(pad)['axes'][axis]}
        for name,fn in functions.items():setattr(self,name,Mock(side_effect=fn))


class BindingTests(unittest.TestCase):
    def test_background_capture_configures_polling_before_opening_devices(self):
        sdl=FakeSDL();sdl.devices[2]['buttons']={'FaceWest'}
        with patch.object(binding.ctypes,'CDLL',return_value=sdl):capture=binding.ControllerCapture(background=True)
        try:
            self.assertEqual(sdl.initial_hints,{b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS':b'1',
                b'SDL_JOYSTICK_WGI':b'0',b'SDL_JOYSTICK_RAWINPUT':b'0'})
            self.assertEqual(capture.pressed(),{'SDL-2/FaceWest'})
        finally:capture.close()
        self.assertCountEqual(sdl.closed,[10,11,12,13])

    def test_default_rebind_backend_is_unchanged(self):
        sdl=FakeSDL()
        with patch.object(binding.ctypes,'CDLL',return_value=sdl):capture=binding.ControllerCapture()
        capture.close()
        self.assertEqual(sdl.initial_hints,{b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS':b'1'})

    def test_background_disconnect_reconnect_keeps_other_player_seats(self):
        sdl=FakeSDL();sdl.devices[3]['buttons']={'FaceNorth'}
        with patch.object(binding.ctypes,'CDLL',return_value=sdl):capture=binding.ControllerCapture(background=True)
        try:
            del sdl.devices[2] # SDL device 2 now refers to physical controller 4.
            self.assertEqual(capture.pressed(),{'SDL-3/FaceNorth'})
            self.assertEqual([s for s,_ in capture.controllers],[0,1,3])
            sdl.devices.append(dict(instance=99,player=2,buttons={'FaceWest'},axes=[0]*6))
            self.assertEqual(capture.pressed(),{'SDL-2/FaceWest','SDL-3/FaceNorth'})
            capture.update();self.assertEqual(sdl.opened,[10,11,12,13,99])
        finally:capture.close()
        self.assertCountEqual(sdl.closed,[10,11,12,13,99])

    def test_every_ps2_button_and_duration_round_trip(self):
        for name,mask in binding.MASKS.items():
            prefs=settings.validate_settings({settings.LOCKON_KEY:name,settings.LOCKON_HOLD_KEY:0})
            self.assertEqual(settings.lockon_mask(prefs),mask)
            self.assertEqual(settings.lockon_updates(prefs),0)
        for seconds,frames in ((.5,15),(1,30),(.01,1),(2.25,68),(3600,108000)):
            self.assertEqual(settings.lockon_updates({settings.LOCKON_HOLD_KEY:seconds}),frames)
        for invalid in (-1,3601,True,'1',None,float('nan'),float('inf')):
            with self.assertRaises(ValueError):settings.validate_settings({settings.LOCKON_HOLD_KEY:invalid})

    def test_rebind_uses_actual_remapping_and_rejects_ambiguity_or_chord(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'PCSX2.ini'
            path.write_text('[Pad1]\nCross = SDL-0/FaceNorth\nSquare = Keyboard/X\n'
                            'R1 = SDL-0/+RightTrigger\nL1 = SDL-0/LeftShoulder & SDL-0/RightShoulder\n'
                            '[Pad2]\nTriangle = SDL-1/FaceSouth\nCircle = Keyboard/X\n'
                            '[GameList]\nRecursivePaths = one\nRecursivePaths = two\n')
            raw=path.read_bytes();maps=binding.mappings(path)
            self.assertEqual(binding.resolve({'SDL-0/FaceNorth'},maps),'cross')
            self.assertEqual(binding.resolve({'SDL-1/FaceSouth'},maps),'triangle')
            self.assertEqual(binding.resolve({'SDL-0/+RightTrigger'},maps),'r1')
            self.assertIsNone(binding.resolve({'SDL-0/LeftShoulder'},maps))
            self.assertIsNone(binding.resolve({'SDL-2/FaceSouth'},maps))
            with self.assertRaisesRegex(ValueError,'several'):binding.resolve({'Keyboard/x'},maps)
            self.assertEqual(path.read_bytes(),raw)

    def test_keyboard_keys_match_pcsx2_names(self):
        for key,name in (('space','Space'),('Return','Return'),('Prior','PageUp'),('Shift_L','Shift'),('x','x')):
            self.assertEqual(binding.keyboard_sources(key),('Keyboard/'+name,))

    def test_windows_loads_the_bundled_dll_exactly_as_before(self):
        sdl=FakeSDL()
        with patch.object(binding,'WINDOWS',True),patch.object(binding.ctypes,'CDLL',return_value=sdl) as load:
            binding.ControllerCapture().close()
        vendor=binding.ROOT/'tools/vendor/SDL2.dll'
        self.assertEqual(load.call_args.args,(str(vendor if vendor.is_file() else binding.ROOT/'runtime128/SDL2.dll'),))
        with patch.object(binding.ctypes,'CDLL',return_value=sdl) as load:binding.load_sdl('custom/SDL2.dll')
        self.assertEqual(load.call_args.args,('custom/SDL2.dll',))

    def test_linux_loads_the_system_sdl2_and_never_the_windows_dll(self):
        sdl=FakeSDL()
        with patch.object(binding,'WINDOWS',False),patch.object(binding.ctypes,'CDLL',return_value=sdl) as load,\
             patch('ctypes.util.find_library',side_effect=AssertionError('the soname loaded directly')):
            self.assertIs(binding.load_sdl(),sdl)
        self.assertEqual(load.call_args.args,('libSDL2-2.0.so.0',))
        def only_found(name):
            if name!='/usr/lib64/libSDL2-2.0.so.0':raise OSError(f'{name}: cannot open shared object file')
            return sdl
        with patch.object(binding,'WINDOWS',False),patch.object(binding.ctypes,'CDLL',side_effect=only_found) as load,\
             patch('ctypes.util.find_library',return_value='/usr/lib64/libSDL2-2.0.so.0') as find:
            self.assertIs(binding.load_sdl(),sdl)
        find.assert_called_once_with('SDL2-2.0')
        self.assertFalse(any('.dll' in str(call.args[0]) for call in load.call_args_list))

    def test_missing_sdl2_is_a_clear_catchable_error(self):
        with patch.object(binding,'WINDOWS',False),\
             patch.object(binding.ctypes,'CDLL',side_effect=OSError('libSDL2-2.0.so.0: cannot open shared object file')),\
             patch('ctypes.util.find_library',return_value=None):
            with self.assertRaises(binding.SDLUnavailable) as caught:binding.ControllerCapture(background=True)
            self.assertIsInstance(caught.exception,OSError)   # the rebind dialog's existing fallback catches it
            for text in ('libSDL2-2.0.so.0','controllers 3 and 4','libsdl2-2.0-0','Players 1 and 2 are not affected'):
                self.assertIn(text,str(caught.exception))
            self.assertTrue(binding.sdl_status().startswith('unavailable. SDL2 (libSDL2-2.0.so.0) is not installed'))
        with patch.object(binding,'WINDOWS',False),patch.object(binding.ctypes,'CDLL',return_value=FakeSDL()):
            self.assertEqual(binding.sdl_status(),'SDL2 available')

    def test_the_rebind_capture_never_logs_a_device_list(self):
        # The players' controllers are read and logged by the controller hub (controller_hub.py), not here.
        self.assertFalse(hasattr(binding,'device_report'))
        for windows,background in ((True,True),(False,True),(False,False)):
            with patch.object(binding,'WINDOWS',windows),patch.object(binding.ctypes,'CDLL',return_value=FakeSDL()),\
                 patch('builtins.print') as printed:
                binding.ControllerCapture(background=background).close()
            printed.assert_not_called()

    def test_real_linux_library_lookup_reports_what_is_installed(self):
        if os.name=='nt':self.skipTest('Linux library lookup')
        try:ctypes.CDLL('libSDL2-2.0.so.0');installed=True
        except OSError:installed=False
        status=binding.sdl_status()
        self.assertEqual(status=='SDL2 available',installed,status)
        if not installed:
            with self.assertRaisesRegex(binding.SDLUnavailable,'controllers 3 and 4'):binding.ControllerCapture(background=True)

    def test_hold_preference_survives_unrelated_settings_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            settings.SettingsController(path).save('none',lockon='cross',lockon_hold=.1)
            prefs=settings.save_settings({'future':42},path)
            self.assertEqual((prefs[settings.LOCKON_KEY],prefs[settings.LOCKON_HOLD_KEY]),('cross',.1))


if __name__=='__main__':unittest.main()
