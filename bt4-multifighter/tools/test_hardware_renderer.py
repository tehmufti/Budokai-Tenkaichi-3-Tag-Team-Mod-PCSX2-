"""Render-device selection and reversible offline / isolated online settings."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hardware_renderer as hw

CPU = dict(type=4, name='llvmpipe (LLVM 15.0.7, 256 bits)')
GPU = dict(type=2, name='Discrete GPU')


class HardwareRendererTests(unittest.TestCase):
    def choose(self, devices, renderer='14', adapter='', platform='linux'):
        return hw.overrides(renderer, adapter, platform=platform, devices=devices)

    def test_cpu_vulkan_uses_automatic_hardware_selection(self):
        self.assertEqual(self.choose([CPU]), {'Renderer':'-1', 'Adapter':''})
        self.assertEqual(self.choose([CPU], adapter=CPU['name']), {'Renderer':'-1', 'Adapter':''})
        self.assertEqual(self.choose([CPU], adapter='old GPU name'), {'Renderer':'-1', 'Adapter':''})

    def test_real_hardware_and_explicit_other_renderers_are_preserved(self):
        for device_type in (0, 1, 2, 3):
            self.assertEqual(self.choose([dict(GPU, type=device_type)]), {})
        for renderer in ('-1', '12', '13', '3', '15', 'nonsense'):
            self.assertEqual(self.choose([CPU], renderer=renderer), {})
        self.assertEqual(self.choose([CPU], platform='win32'), {})

    def test_mixed_devices_honor_named_adapter_and_default_order(self):
        self.assertTrue(self.choose([CPU, GPU]))
        self.assertEqual(self.choose([GPU, CPU]), {})
        self.assertTrue(self.choose([GPU, CPU], adapter=CPU['name']))
        self.assertEqual(self.choose([CPU, GPU], adapter=GPU['name']), {})
        self.assertEqual(self.choose([CPU, GPU], adapter='unknown GPU'), {})
        self.assertEqual(self.choose([CPU, dict(GPU, name=CPU['name'])], adapter=CPU['name']), {})

    def test_invalid_or_missing_inventory_never_changes_a_setting(self):
        for inventory in ([], {}, [None], [dict(type=5, name='x')], [dict(type=4, name='')]):
            self.assertEqual(self.choose(inventory), {})
        with patch.object(hw, 'vulkan_devices', return_value=None):
            self.assertEqual(self.choose(None), {})

    def test_non_vulkan_and_windows_do_not_load_or_probe_drivers(self):
        with patch.object(hw, 'vulkan_devices', side_effect=AssertionError('unexpected probe')):
            self.assertEqual(hw.overrides('14', platform='win32'), {})
            self.assertEqual(hw.overrides('-1', platform='linux'), {})
            self.assertEqual(hw.overrides('13', platform='linux'), {})

    def test_probe_timeout_crash_and_bad_output_are_nonfatal(self):
        for failure in (OSError('missing driver'), subprocess.TimeoutExpired('probe', 4),
                        subprocess.CalledProcessError(-11, 'probe')):
            hw.vulkan_devices.cache_clear()
            with patch.object(hw.subprocess, 'run', side_effect=failure):
                self.assertIsNone(hw.vulkan_devices())
        for output in (b'not json', b'[]', b'x'*32769):
            hw.vulkan_devices.cache_clear()
            with patch.object(hw.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,stdout=output)):
                self.assertIsNone(hw.vulkan_devices())
        hw.vulkan_devices.cache_clear()

    def test_probe_returns_valid_inventory_and_is_cached(self):
        hw.vulkan_devices.cache_clear()
        with patch.object(hw.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,stdout=json.dumps([CPU]))) as run:
            self.assertEqual(hw.vulkan_devices(), [CPU])
            self.assertEqual(hw.vulkan_devices(), [CPU])
            self.assertEqual(run.call_count, 1)
        hw.vulkan_devices.cache_clear()

    def test_offline_session_restores_preferences_and_keeps_new_user_edits(self):
        import presentation_settings as session
        original = b'[EmuCore/GS]\nRenderer = 14\nupscale_multiplier = 3\nAdapter = llvmpipe\n[Pad1]\nCross = Keyboard/J\n'
        for edit in (False, True):
            with self.subTest(edit=edit), tempfile.TemporaryDirectory() as folder:
                config, receipt = Path(folder)/'PCSX2.ini', Path(folder)/'receipt.json'
                config.write_bytes(original)
                with patch.object(hw, 'overrides', return_value={'Renderer':'-1','Adapter':''}), \
                     patch('bt4_graphics_fixes.session', return_value=dict(adapter='bt3-usa',ready=True)), \
                     patch('mod_settings.load_settings', return_value=dict(widescreen_patch=False)), \
                     patch('widescreen_support.embedded', return_value=False), contextlib.redirect_stdout(io.StringIO()):
                    session.apply(config, receipt)
                applied = config.read_bytes()
                self.assertIn(b'Renderer = -1', applied)
                self.assertIn(b'upscale_multiplier = 3', applied)
                self.assertIn(b'Cross = Keyboard/J', applied)
                if edit:
                    config.write_bytes(applied.replace(b'Renderer = -1', b'Renderer = 12'))
                self.assertTrue(session.restore(config, receipt))
                self.assertEqual(config.read_bytes(), original.replace(b'Renderer = 14', b'Renderer = 12') if edit else original)

    def test_online_session_uses_same_guard_without_changing_emulation_policy(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'bt3-multifighter/online/netplay'))
        import kit_emu, kit_ident
        template = '[EmuCore/GS]\nRenderer = 12\nupscale_multiplier = 3\n'
        original = template
        with patch.object(hw, 'overrides', return_value={'Renderer':'-1', 'Adapter':''}) as choose, \
             contextlib.redirect_stdout(io.StringIO()):
            result = kit_emu.make_ini(template, pine_slot=28011, pad1={}, bios_name='bios.bin',
                                     extra=[('EmuCore/GS','Renderer','14'), ('EmuCore/GS','Adapter',CPU['name'])])
        choose.assert_called_once_with('14', CPU['name'])
        self.assertEqual(kit_ident.ini_values(result)['EmuCore/GS/Renderer'], '-1')
        self.assertEqual(kit_ident.ini_values(result)['EmuCore/GS/upscale_multiplier'], '3')
        self.assertFalse(kit_ident.forced_problems(result))
        self.assertEqual(template, original)


if __name__ == '__main__':
    unittest.main()
