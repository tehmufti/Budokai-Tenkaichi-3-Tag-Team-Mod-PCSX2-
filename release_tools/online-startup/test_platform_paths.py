"""A Linux host uses its own AppImage profile and never the playing socket."""
from pathlib import Path
import ast, json, os, sys, tempfile, unittest
from unittest.mock import patch, MagicMock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bt3-multifighter/online/netplay'))
import kit_platform as platform
import kit_install, kit_controller


class PlatformPaths(unittest.TestCase):
    def test_installation_reads_the_correct_bios_and_python_on_both_platforms(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game=root/'game';game.mkdir()
            (game/'player-install.json').write_text(json.dumps({'adapter':'bt3-usa','version':'0.1.0-beta.14.3'}))
            (game/'game-profile.json').write_text(json.dumps({'adapter':'bt3-usa','iso':'game.iso'}))
            for windows in (True,False):
                with patch.object(platform,'WINDOWS',windows),patch.object(kit_install,'load_settings',return_value={}):
                    runtime=platform.data(root);(runtime/'inis').mkdir(parents=True,exist_ok=True)
                    (runtime/'inis/PCSX2.ini').write_text('[Folders]\nBios=bios\n[Filenames]\nBIOS=own.bin\n')
                    python=platform.python(root);python.parent.mkdir(parents=True,exist_ok=True);python.touch()
                    record=kit_install.read_installation(root)
                    self.assertEqual(record['bios'],str(runtime/'bios/own.bin'))
                    self.assertEqual(record['python'],str(python))

    def test_preparation_does_not_use_the_clients_socket_override(self):
        with patch.dict(os.environ,{'TAGTEAM_PINE_SOCKET':'/wrong/client.sock','XDG_RUNTIME_DIR':'/tmp'}):
            self.assertEqual(platform.socket_path(32123),'/tmp/pcsx2.sock.32123')

    def test_foreign_preparation_socket_is_rejected_and_closed(self):
        import pine
        connection=MagicMock()
        with patch.object(platform,'WINDOWS',False),patch.object(platform.socket,'AF_UNIX',1,create=True),patch.object(platform.socket,'socket',return_value=connection),patch.object(pine,'peer_pid',return_value=101):
            with self.assertRaisesRegex(pine.PineError,'another emulator'):
                platform.client(32123,pid=202)
            connection.close.assert_called_once()

    def test_linux_host_is_checked_for_an_installation_instead_of_rejected(self):
        with patch.object(kit_controller.os,'name','posix'):
            self.assertEqual(kit_controller.Controller.prep_problem(None,None,None,None),('why.no_install',None))

    def test_linux_cleanup_handles_kernels_without_working_pidfd_wait(self):
        import kit_win,psutil
        parent,child=MagicMock(),MagicMock()
        parent.children.return_value=[child]
        parent.is_running.return_value=False
        child.is_running.return_value=True
        child.status.return_value=psutil.STATUS_RUNNING
        with patch.object(kit_win,'WINDOWS',False),patch.object(kit_win,'pid_alive',return_value=True),\
             patch.object(psutil,'Process',return_value=parent),patch.object(psutil,'wait_procs',side_effect=OSError(22,'pidfd')):
            self.assertTrue(kit_win.kill_tree(1))
        parent.terminate.assert_called_once()
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        parent.kill.assert_not_called()

    def test_private_linux_builder_allows_clients_but_refuses_its_own_emulator_or_socket(self):
        import kit_prepare
        source=(ROOT/'bt3-multifighter/tools/play_launcher.py').read_text()
        for old,new in kit_prepare.patches(32123)['game/tools/play_launcher.py']:
            self.assertEqual(source.count(old),1)
            source=source.replace(old,new)
        method=next(node for node in ast.walk(ast.parse(source))
                    if isinstance(node,ast.FunctionDef) and node.name=='running_emulators')
        namespace=dict(Path=Path,WINDOWS=False,PINE_SLOT=32123,other_emulators=lambda:['other client'],
                       looks_like_pcsx2=lambda *a:True,PINE_SERVER='{where}')
        root=Path('/isolated/prep/Tag Team Mod/game')
        emulator=root/'runtime28/pcsx2-qt.AppImage'
        instance=type('Private',(),dict(root=root,emulator_path=emulator,socket='/own.socket'))()
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<private launcher>','exec'),namespace)
        namespace['linux_processes']=lambda:[(1,'pcsx2-qt',None,'/online/client.AppImage')]
        namespace['pine_in_use']=lambda *a:False
        self.assertEqual(namespace['running_emulators'](instance),[])
        namespace['linux_processes']=lambda:[(2,'pcsx2-qt',None,str(emulator))]
        self.assertEqual(namespace['running_emulators'](instance),['pcsx2-qt (process 2)'])
        namespace['linux_processes']=lambda:[]
        namespace['pine_in_use']=lambda *a:True
        self.assertEqual(namespace['running_emulators'](instance),['/own.socket'])
        instance.root=Path('/not/a/private/copy')
        with self.assertRaisesRegex(ValueError,'private installation'):
            namespace['running_emulators'](instance)


if __name__=='__main__':unittest.main()
