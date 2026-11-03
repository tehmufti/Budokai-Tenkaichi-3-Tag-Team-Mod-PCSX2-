"""Installer-owned BT4 graphics fixes do not change online emulation identity."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bt3-multifighter/online/netplay'))
import kit_ident as ident
import bt4_graphics_fixes as graphics

DATABASE=b'''SLUS-21678:
  name: BT3
  gsHWFixes:
    halfPixelOffset: 1
    nativeScaling: 1
    beforeDraw: OI_DBZBTGames
  gameFixes:
    - FpuCompareHack
'''


class GraphicsBuildIdentityTests(unittest.TestCase):
    def test_exact_generated_suffix_only_and_both_line_endings(self):
        for original in (DATABASE,DATABASE.replace(b'\n',b'\r\n'),b'\xef\xbb\xbf'+DATABASE):
            installed=graphics.plan(original,graphics.ADAPTER)['data']
            self.assertEqual(graphics.original_database(installed),original)
            self.assertEqual(graphics.original_database(original),original)
            variants=(installed+b'\n',installed.replace(b'halfPixelOffset: 1',b'halfPixelOffset: 2',1),
                      installed.replace(graphics.END.encode(),b'  gameFixes: [FpuCompareHack]\n'+graphics.END.encode()),
                      installed.replace(graphics.END.encode(),b''),installed+installed[len(original):])
            for changed in variants:self.assertEqual(graphics.original_database(changed),changed)

    def test_generated_alias_matches_official_but_modified_emulation_does_not(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name);(root/'resources').mkdir()
            (root/'pcsx2-qt.exe').write_bytes(b'test executable');(root/'core.dll').write_bytes(b'test library')
            (root/'resources/patches.zip').write_bytes(b'test patches')
            database=root/graphics.RESOURCE;database.write_bytes(DATABASE)
            base=ident.pcsx2_identity(root)
            reviewed={base['digest']:dict(version='2.8.2',platform='Windows',savestate=ident.SAVESTATE_VERSION)}
            with patch.dict(ident.TESTED_PCSX2,reviewed,clear=True):
                installed=graphics.plan(DATABASE,graphics.ADAPTER)['data'];database.write_bytes(installed)
                actual=ident.tree_digest(*ident.pcsx2_files(root))[0]
                result=ident.pcsx2_identity(root)
                self.assertTrue(result['tested']);self.assertEqual(result['digest'],base['digest'])
                self.assertEqual(result['installed_digest'],actual)
                for path in (database,root/'core.dll',root/'pcsx2-qt.exe',root/'resources/patches.zip'):
                    data=path.read_bytes();path.write_bytes(data+b'changed')
                    self.assertFalse(ident.pcsx2_identity(root)['tested'],path.name)
                    path.write_bytes(data)
                # A modified base database cannot be blessed by regenerating a matching alias.
                modified=DATABASE.replace(b'FpuCompareHack',b'OtherCpuFix')
                database.write_bytes(graphics.plan(modified,graphics.ADAPTER)['data'])
                self.assertFalse(ident.pcsx2_identity(root)['tested'])

    def test_graphics_correction_does_not_block_windows_linux_peer(self):
        windows=ident._build('316afb5f46df0b83e0a551b9532b6d54f605b2a073cbc5a6ecbd86045e18deda','','Windows',29)
        windows['installed_digest']='93045d6c84e72b25bdf61089d8183678a1b04b1d47b709c5a05579306147a078'
        linux=ident._build('0c46bb6a88aa2782b10853a7b07cf3387ba99cbef2b966372cd2315b8571abea','','Linux AppImage',1)
        # Exercise the actual handshake, keeping the unrelated identities equal.
        from test_patch_identity import PatchIdentityTests
        fixture=PatchIdentityTests();fixture.setUp()
        try:
            one=fixture.identity(fixture.installation('windows'))
            two=fixture.identity(fixture.installation('linux'))
            one['pcsx2']=windows;two['pcsx2']=linux
            self.assertEqual(fixture.refusals(one,two),[])
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
