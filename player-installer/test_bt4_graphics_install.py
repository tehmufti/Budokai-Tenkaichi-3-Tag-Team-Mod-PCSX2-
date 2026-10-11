"""Copied emulator graphics corrections participate in setup/update ownership."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import install_player as install
import update_player as update

TOOLS=Path(__file__).resolve().parents[1]/'bt4-multifighter/tools'
DB=(b'SLUS-21678:\n  name: "BT3"\n  gsHWFixes:\n'
    b'    halfPixelOffset: 5\n    nativeScaling: 4\n    beforeDraw: "OI_DBZBTGames"\n')
ADAPTER='bt4-b14-rev2-eng'


def runtime(root,data=DB):
    root=Path(root);(root/'resources').mkdir(parents=True)
    (root/'resources/GameIndex.yaml').write_bytes(data)
    (root/'pcsx2-qt.exe').write_bytes(b'fixture')
    return root


class GraphicsInstallTests(unittest.TestCase):
    def test_install_changes_only_copied_resource_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(install,'WINDOWS',True):
            root=Path(tmp);source=runtime(root/'source');copy=runtime(root/'copy')
            (copy/'settings.ini').write_bytes(b'UserHacks and resolution preferences')
            result=install.install_runtime_graphics(copy,ADAPTER,TOOLS)
            self.assertTrue(result['ready'])
            first=(copy/'resources/GameIndex.yaml').read_bytes()
            self.assertIn(b'SLUS-21978:',first)
            install.install_runtime_graphics(copy,ADAPTER,TOOLS)
            self.assertEqual((copy/'resources/GameIndex.yaml').read_bytes(),first)
            self.assertEqual((source/'resources/GameIndex.yaml').read_bytes(),DB)
            self.assertEqual((copy/'settings.ini').read_bytes(),b'UserHacks and resolution preferences')

    def test_linux_and_bt3_setup_do_not_edit_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy=runtime(tmp)
            for windows,adapter in ((False,ADAPTER),(True,'bt3-usa'),(True,'bt3-pal'),(True,'bt3-jpn')):
                with patch.object(install,'WINDOWS',windows):
                    self.assertFalse(install.install_runtime_graphics(copy,adapter,TOOLS)['ready'])
                    self.assertEqual((copy/'resources/GameIndex.yaml').read_bytes(),DB)

    def test_update_journals_both_emulators_and_restores_both_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(install,'WINDOWS',True):
            root=Path(tmp);tools=root/'game/tools';tools.mkdir(parents=True)
            shutil.copy2(TOOLS/'bt4_graphics_fixes.py',tools)
            offline=runtime(root/'game/runtime28');online=runtime(root/'online/pcsx2',DB.replace(b'nativeScaling: 4',b'nativeScaling: 2'))
            originals={str(path.relative_to(root)):(path/'resources/GameIndex.yaml').read_bytes() for path in (offline,online)}
            transaction=update.Transaction(root,'0.1.0-beta.12')
            changed=update.update_runtime_graphics(root,ADAPTER,install,transaction)
            self.assertEqual(set(changed),{'game/runtime28/resources/GameIndex.yaml','online/pcsx2/resources/GameIndex.yaml'})
            for name,raw in changed.items():
                self.assertEqual((root/name).read_bytes(),raw)
                self.assertEqual(raw.count(b'SLUS-21978:'),1)
            self.assertIn(b'nativeScaling: 2',changed['online/pcsx2/resources/GameIndex.yaml'])
            self.assertTrue(update.recover(root))
            for path,raw in originals.items():self.assertEqual((root/path/'resources/GameIndex.yaml').read_bytes(),raw)

    def test_existing_game_database_entry_is_not_replaced_by_update(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(install,'WINDOWS',True):
            root=Path(tmp);tools=root/'game/tools';tools.mkdir(parents=True)
            shutil.copy2(TOOLS/'bt4_graphics_fixes.py',tools)
            custom=DB+b'SLUS-21978:\n  name: Custom entry\n'
            copy=runtime(root/'game/runtime28',custom)
            transaction=update.Transaction(root,'0.1.0-beta.12')
            self.assertEqual(update.update_runtime_graphics(root,ADAPTER,install,transaction),{})
            self.assertEqual((copy/'resources/GameIndex.yaml').read_bytes(),custom)


if __name__=='__main__':unittest.main()
