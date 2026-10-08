"""Controller lifetime, process replacement and failed-setup isolation regressions."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_map import elf_path
if not elf_path(Path(__file__).resolve().parents[1]).is_file():
    raise unittest.SkipTest('Requires locally extracted native executable')

import autopilot
import pine
import runtime_owner as owner


class StopLoop(BaseException):
    pass


class OwnershipTests(unittest.TestCase):
    def tearDown(self):
        pine.set_runtime_guard(None)

    def test_os_lease_excludes_another_process_and_releases_after_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'owner.lock'
            args = [sys.executable, '-c',
                    'import sys,time;from runtime_owner import claim;'
                    's=claim(sys.argv[1],timeout=0);print("claimed",flush=True);time.sleep(30)', str(path)]
            child = subprocess.Popen(args, cwd=Path(__file__).parent, stdout=subprocess.PIPE,
                                     text=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                self.assertEqual(child.stdout.readline().strip(),'claimed')
                with self.assertRaisesRegex(ValueError,'already running'):
                    owner.claim(path,timeout=0)
                child.terminate();child.wait(timeout=5)
                with owner.claim(path,timeout=0): pass
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)
                child.stdout.close()

    def test_process_death_or_pid_reuse_permanently_revokes_lease(self):
        process = Mock(pid=123)
        process.exe.return_value = str(owner.EXECUTABLE)
        process.create_time.return_value = 100
        process.is_running.side_effect = [True,False,True]
        with patch.object(owner.psutil,'Process',return_value=process):
            lease=owner.EmulatorLifetime(123)
        with self.assertRaises(owner.EmulatorClosed):lease.require_alive()
        with self.assertRaises(owner.EmulatorClosed):lease.require_alive()
        self.assertEqual(process.is_running.call_count,2)

    def test_wrong_executable_never_acquires_runtime_identity(self):
        process=Mock();process.exe.return_value=str(Path(sys.executable))
        with patch.object(owner.psutil,'Process',return_value=process):
            with self.assertRaisesRegex(ValueError,'isolated emulator'):
                owner.EmulatorLifetime(123)

    def test_lifetime_carries_its_pid_into_the_pine_peer_check(self):
        process=Mock(pid=4321);process.exe.return_value=str(owner.EXECUTABLE);process.is_running.return_value=True
        with patch.object(owner.psutil,'Process',return_value=process):lease=owner.EmulatorLifetime(4321)
        self.assertEqual(lease.pid,4321)
        pine.set_runtime_guard(lease.require_alive);self.assertEqual(pine._runtime_pid,4321)

    @unittest.skipUnless(os.name=='nt','Windows executable comparison')
    def test_windows_comparison_is_unchanged(self):
        self.assertTrue(owner.WINDOWS)
        process=Mock(pid=5);process.exe.return_value=str(owner.EXECUTABLE).upper();process.is_running.return_value=True
        with patch.object(owner.psutil,'Process',return_value=process),\
             patch.object(owner,'appimage_process',side_effect=AssertionError('Linux identity on Windows')):
            owner.EmulatorLifetime(5)   # resolve() compares case-insensitively, exactly as before
        process.environ.assert_not_called()


    def test_dead_owner_blocks_reads_writes_and_state_load_before_socket_access(self):
        guard=Mock(side_effect=owner.EmulatorClosed('closed'))
        pine.set_runtime_guard(guard)
        p=pine.PineClient();p.sock=Mock()
        with patch.object(pine.socket,'create_connection') as connect:
            for operation in (lambda:p.read_u32(0xD8080),lambda:p.write_u32(0xD8080,1),
                              lambda:p.load_state(219),lambda:p.save_state(219)):
                with self.assertRaises(owner.EmulatorClosed):operation()
            connect.assert_not_called();p.sock.sendall.assert_not_called()

    def test_owner_dying_during_connection_cannot_publish_to_replacement(self):
        for windows in (True,False):   # loopback TCP on Windows, the Unix socket elsewhere
            pine.set_runtime_guard(Mock(side_effect=[None,None,owner.EmulatorClosed('replaced')]))
            replacement=Mock()
            with patch.object(pine,'WINDOWS',windows),patch.dict(os.environ,{'TAGTEAM_PINE_SOCKET':'/tmp/x.sock'}),\
                 patch.object(pine.socket,'AF_UNIX',getattr(pine.socket,'AF_UNIX',1),create=True),\
                 patch.object(pine.socket,'create_connection',return_value=replacement),\
                 patch.object(pine.socket,'socket',return_value=replacement):
                with self.assertRaises(owner.EmulatorClosed):pine.PineClient().write_u32(0xD8080,1)
            replacement.sendall.assert_not_called();replacement.close.assert_called_once()

    def test_watcher_exits_before_observing_replacement_even_with_active_worker(self):
        lifetime=SimpleNamespace(process=SimpleNamespace(pid=123),
                                 require_alive=Mock(side_effect=owner.EmulatorClosed('closed')))
        watcher=autopilot.Autopilot(lifetime=lifetime);watcher.worker=Mock()
        with patch.object(autopilot.time,'sleep'),patch.object(watcher,'observe') as observe,\
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(owner.EmulatorClosed):watcher.run()
        observe.assert_not_called();watcher.worker.is_alive.assert_not_called()

    def test_menu_polls_keep_selector_input_but_full_teardown_closes_it(self):
        watcher=autopilot.Autopilot()
        watcher.menu_input=Mock();watcher.controller_input=Mock()
        for _ in range(3):watcher.reset_reload_worker(keep_menu_input=True)
        watcher.menu_input.close.assert_not_called()
        self.assertEqual(watcher.controller_input.close.call_count,3)
        watcher.reset_reload_worker();watcher.menu_input.close.assert_called_once()

    def test_duplicate_cli_has_no_pine_or_presentation_side_effects(self):
        import loading_presentation
        with patch.object(sys,'argv',['autopilot.py','--emulator-pid','123']),\
             patch.object(owner,'claim',side_effect=ValueError('already running')),\
             patch.object(loading_presentation,'LoadingPresentation') as cover,\
             patch.object(autopilot,'PineClient') as client,\
             contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(autopilot.main(),1)
        client.assert_not_called();cover.assert_not_called()

    def test_setup_failure_never_loads_boot_archive_even_when_menu_saved(self):
        for message in ('Another team preparation is already running',
                        'Patch installation requires an acknowledged combat hold'):
            watcher=autopilot.Autopilot();watcher.state='PREPARING';watcher.menu_saved=True
            watcher.current_key=('captured',);watcher.worker=Mock();watcher.worker.is_alive.return_value=False
            watcher.result=dict(ok=False,error=message)
            with patch.object(watcher,'observe',side_effect=[SimpleNamespace(loop=0),StopLoop()]),\
                 patch.object(watcher,'load_file') as load,patch.object(watcher,'uncover') as uncover,\
                 patch.object(watcher,'cover'),patch.object(autopilot.time,'sleep'),\
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(StopLoop):watcher.run()
            # Beta.33 round 2 (G7a): no boot archive is ever loaded, but at the menus (no in-game cover there) the
            # failure cover comes down once and the explanation is repeated in the Play window.
            self.assertEqual(watcher.state,'FAILED');load.assert_not_called();uncover.assert_called_once()
            self.assertIn('Match setup stopped',watcher.last_error['what']);self.assertEqual(watcher.last_error['code'][:10],'TTM-MATCH-')



class AppImageIdentityTests(unittest.TestCase):
    """Linux: the launched PID is the AppImage, then (same PID) usr/bin/pcsx2-qt from its FUSE mount."""
    def setUp(self):
        self.folder=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.folder)
        self.appimage=self.folder/'pcsx2-qt.AppImage';self.appimage.write_bytes(b'\x7fELF appimage')
        patcher=patch.object(owner,'WINDOWS',False);patcher.start();self.addCleanup(patcher.stop)

    def lease(self,exe,environ=None,pid=77):
        process=Mock(pid=pid);process.is_running.return_value=True
        process.create_time.return_value=12.5
        if isinstance(exe,BaseException):process.exe.side_effect=exe
        else:process.exe.return_value=exe
        if isinstance(environ,BaseException):process.environ.side_effect=environ
        else:process.environ.return_value=environ or {}
        with patch.object(owner.psutil,'Process',return_value=process):
            return owner.EmulatorLifetime(pid,executable=self.appimage)

    def test_accepted_before_and_after_the_runtime_execs_pcsx2(self):
        self.assertEqual(self.lease(str(self.appimage)).created,12.5)   # pre-exec: /proc/pid/exe is the AppImage
        link=self.folder/'link.AppImage'
        try:link.symlink_to(self.appimage)
        except (OSError,NotImplementedError):link=self.appimage
        mount='/tmp/.mount_pcsx2abc/usr/bin/pcsx2-qt'
        for name in (str(self.appimage),str(link)):
            lease=self.lease(mount,{'APPIMAGE':name})
            self.assertEqual((lease.pid,lease.created,lease.closed),(77,12.5,False))

    def test_other_programs_other_appimages_and_hidden_processes_are_refused(self):
        other=self.folder/'other.AppImage';other.write_bytes(b'\x7fELF other')
        mount='/tmp/.mount_pcsx2abc/usr/bin/pcsx2-qt'
        for exe,environ in ((mount,{'APPIMAGE':str(other)}),(mount,{}),(mount,{'APPIMAGE':''}),
                            ('/usr/bin/python3',{'APPIMAGE':str(self.appimage)}),(str(other),{}),
                            (mount,owner.psutil.AccessDenied(77)),(owner.psutil.AccessDenied(77),{})):
            with self.subTest(exe=exe,environ=environ),self.assertRaisesRegex(ValueError,'isolated emulator'):
                self.lease(exe,environ)

    def test_an_exited_emulator_is_closed_not_foreign(self):
        for exe,environ in ((owner.psutil.NoSuchProcess(77),{}),
                            ('/tmp/.mount_x/usr/bin/pcsx2-qt',owner.psutil.ZombieProcess(77))):
            with self.subTest(exe=exe),self.assertRaises(owner.EmulatorClosed):
                self.lease(exe,environ)

    def test_pid_reuse_still_revokes_the_lease(self):
        process=Mock(pid=77);process.exe.return_value=str(self.appimage);process.create_time.return_value=1
        process.is_running.side_effect=[True,False,True]
        with patch.object(owner.psutil,'Process',return_value=process):lease=owner.EmulatorLifetime(77,executable=self.appimage)
        for _ in range(2):
            with self.assertRaises(owner.EmulatorClosed):lease.require_alive()
        self.assertEqual(process.is_running.call_count,2)


@unittest.skipUnless(sys.platform.startswith('linux'),'real /proc identity')
class RealProcessIdentityTests(unittest.TestCase):
    """Real processes and real psutil: a copy of sleep plays the AppImage and the mounted pcsx2-qt."""
    def setUp(self):
        self.folder=Path(tempfile.mkdtemp(prefix='ttm-owner-',dir='/tmp'));self.addCleanup(shutil.rmtree,self.folder)
        self.appimage=self.folder/'pcsx2-qt.AppImage';shutil.copy2(shutil.which('sleep'),self.appimage)
        mount=self.folder/'.mount_pcsx2/usr/bin';mount.mkdir(parents=True)
        self.binary=mount/'pcsx2-qt';shutil.copy2(shutil.which('sleep'),self.binary)
        self.children=[];self.addCleanup(self.stop)

    def stop(self):
        for child in self.children:
            if child.poll() is None:child.kill()
            child.wait(timeout=5)

    def start(self,program,environ):
        child=subprocess.Popen([str(program),'30'],env=environ);self.children.append(child)
        deadline=time.monotonic()+5
        while owner.psutil.Process(child.pid).exe()!=str(program) and time.monotonic()<deadline:time.sleep(.01)
        return child

    def test_launched_appimage_and_mounted_pcsx2_are_accepted_and_others_refused(self):
        with patch.object(owner,'WINDOWS',False):
            pre=self.start(self.appimage,dict(os.environ))
            self.assertEqual(owner.EmulatorLifetime(pre.pid,executable=self.appimage).pid,pre.pid)
            mounted=self.start(self.binary,dict(os.environ,APPIMAGE=str(self.appimage)))
            lease=owner.EmulatorLifetime(mounted.pid,executable=self.appimage)
            foreign=self.start(self.binary,dict(os.environ,APPIMAGE=str(self.binary)))
            with self.assertRaisesRegex(ValueError,'isolated emulator'):
                owner.EmulatorLifetime(foreign.pid,executable=self.appimage)
            lease.require_alive();mounted.kill();mounted.wait(timeout=5)
            with self.assertRaises(owner.EmulatorClosed):lease.require_alive()


if __name__=='__main__':unittest.main()
