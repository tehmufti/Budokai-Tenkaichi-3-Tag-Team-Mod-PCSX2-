"""Host-owned fusion settings and deterministic receipt coverage."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import struct
import types
import unittest
from unittest.mock import patch

import mod_settings

ROOT=Path(__file__).resolve().parents[2]
ONLINE=ROOT/'bt3-multifighter'/'online'/'netplay'
KEYS=tuple(key for kind in ('potara','non_potara')
           for key in (f'fusion_{kind}_buffs_enabled',
                       *(f'fusion_{kind}_{stat}_multiplier'for stat in ('health','damage','defense'))))


def settings_module():
    # Import the real host-rule classifier without launching its path/profile
    # discovery, which would select an installation or change the adapter.
    spec=importlib.util.spec_from_file_location('_fusion_online_settings',ONLINE/'kit_settings.py')
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'kit_paths':types.ModuleType('kit_paths')}):
        spec.loader.exec_module(module)
    return module


class FusionOnlineSettingsTests(unittest.TestCase):
    def test_all_eight_settings_belong_to_the_host_and_default_off(self):
        online=settings_module()
        self.assertFalse(online.unclassified())
        defaults=online.default_gameplay()
        for key in KEYS:
            self.assertEqual(online.CLASS[key],'gameplay')
            self.assertNotIn(key,online.LOCAL)
            self.assertEqual(defaults[key],False if key.endswith('_enabled') else 1.0)
        groups=dict(online.groups())
        self.assertTrue(set(KEYS).issubset(groups['Fusion']))

    def test_same_host_values_reach_all_peers_independent_of_services(self):
        online=settings_module()
        host={key:(True if key.endswith('_enabled') else 1.5 if '_non_potara_'in key else 2.25)
              for key in KEYS}
        host['fusion_non_potara_health_multiplier']=3.0
        delta=online.gameplay_diff(host)
        self.assertFalse(online.gameplay_problems(delta))
        for services in ({},{'fusion_timer':True,'body_change':True,'cpu_transform':True}):
            built=online.match_settings(delta,services,'es')
            for key,value in host.items():self.assertEqual(built[key],value)
            self.assertFalse(built['tag_team_rush_enabled'])
        self.assertEqual(online.gameplay_expand(delta),online.normalised_gameplay(delta))

    def test_invalid_multiplier_is_rejected_before_match_preparation(self):
        online=settings_module()
        for key in KEYS:
            value='enabled' if key.endswith('_enabled') else 8
            with self.subTest(key=key):
                self.assertTrue(online.gameplay_problems({key:value}))
                self.assertEqual(online.normalised_gameplay({key:value})[key],mod_settings.DEFAULTS[key])


class FusionOnlineHashTests(unittest.TestCase):
    def test_all_gameplay_receipt_fields_change_the_lean_hash_but_padding_does_not(self):
        import native_map,prototype
        if not native_map.elf_path(prototype.ROOT).is_file():
            def unavailable(*args):
                raise AssertionError('Descriptor coverage must not execute native game code')
            reader=patch.object(prototype,'elf_reader',return_value=(b'',(),unavailable))
            reader.start();self.addCleanup(reader.stop)
        import fusion_buffs as buffs
        spec=importlib.util.spec_from_file_location('_fusion_online_hash',ONLINE/'modtools'/'netplay_state_hash.py')
        hashes=importlib.util.module_from_spec(spec);spec.loader.exec_module(hashes)
        rows=hashes.fusion_buff_rows()
        addresses={address+4*i for kind,cls,address,offset,words,_ in rows for i in range(words)}
        expected=set(range(buffs.CONTROL,buffs.CONTROL+48,4))
        padding=[]
        for index in range(buffs.policy.ENGINE_ACTORS):
            row=buffs.ROWS+index*buffs.STRIDE
            expected.update(row+offset for offset in buffs.R.values())
            expected.update(range(row+buffs.BANKS,row+buffs.BANKS+5*buffs.BANK_STRIDE,4))
            padding.extend((row+24,row+60,row+144,row+252))
        self.assertEqual(addresses,expected)
        self.assertTrue(all(kind==hashes.DIRECT and cls==6 and offset==0 for kind,cls,_,offset,_,_ in rows))
        for profile in ('lean','full'):
            table=hashes.descriptors(profile)
            self.assertTrue(all(row in table for row in rows))
            self.assertLess(len(hashes.table_bytes(table)),0x1000)
        ram=bytearray(0x8000000);baseline,_=hashes.reference(ram,profile='lean')
        for address in expected:
            struct.pack_into('<I',ram,address,1)
            actual,_=hashes.reference(ram,profile='lean')
            self.assertNotEqual(actual[6],baseline[6],hex(address))
            self.assertEqual(actual[:6]+actual[7:],baseline[:6]+baseline[7:])
            struct.pack_into('<I',ram,address,0)
        for address in padding:
            struct.pack_into('<I',ram,address,1)
        self.assertEqual(hashes.reference(ram,profile='lean')[0],baseline)
        # The standalone USA kit reads this file instead of rebuilding it.
        # Other adapters regenerate their native-address descriptors at runtime.
        if native_map.SERIAL=='SLUS-21678':
            with patch.object(sys,'path',[str(ONLINE/'modtools'),*sys.path]),patch.dict(sys.modules,{'netplay_state_hash':hashes}):
                import netplay_core,netplay_view
                table_rows=netplay_core.table_rows('lean',netplay_view.hash_rows())
                table=hashes.table_bytes(rows=table_rows)
            stored=json.loads((ONLINE/'data/hash-table.json').read_text(encoding='utf-8'))
            self.assertEqual(stored['hex'],table.hex())
            self.assertEqual(stored['sha256'],hashlib.sha256(table).hexdigest())
            self.assertEqual((stored['rows'],stored['bytes']),(len(table_rows),len(table)))


if __name__=='__main__':unittest.main()
