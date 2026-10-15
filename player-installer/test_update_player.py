import importlib.util
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import update_player as u


class UpdateTests(unittest.TestCase):
    def test_numbering_reset_accepts_legacy_betas_but_refuses_future_downgrades(self):
        target=dict(version='0.1.0-beta.13.3',version_epoch=2)
        for number in range(14,47):
            with self.subTest(legacy=number):
                current=dict(version=f'0.1.0-beta.{number}')
                self.assertTrue(u.check_release_order(current,target,current))
        for version in ('0.1.0-beta.13.3','0.1.0-beta.13.2','0.1.0-beta.7'):
            current=dict(version=version)
            self.assertFalse(u.check_release_order(current,target,current))
        for current in (dict(version='0.1.0-beta.14',version_epoch=2),
                        dict(version='0.1.0-beta.13.4',version_epoch=2),
                        dict(version='0.1.0-beta.47'),dict(version='0.1.0-beta.30.1'),
                        dict(version='0.2.0-beta.30'),dict(version='0.1.0-beta.13.3',version_epoch=3)):
            with self.subTest(future=current),self.assertRaises(ValueError):
                u.check_release_order(current,target,current)
        # Either installed marker protects a future installation, even if the
        # other marker was written by an older installer without the epoch.
        with self.assertRaises(ValueError):
            u.check_release_order(dict(version='0.1.0-beta.30'),target,dict(version_epoch=2))
        for epoch in (True,'2',0,None):
            with self.subTest(epoch=epoch),self.assertRaises(ValueError):
                u.check_release_order(dict(version='0.1.0-beta.13.3',version_epoch=epoch),target,{})

    def test_patch_release_version_ordering(self):
        order=('0.1.0-beta.10','0.1.0-beta.11','0.1.0-beta.11.1','0.1.0-beta.11.2','0.1.0-beta.11.10','0.1.0-beta.12')
        for previous,next_version in zip(order,order[1:]):
            self.assertLess(u.version_key(previous),u.version_key(next_version))
        self.assertEqual(u.version_key('0.1.0-beta.11'),u.version_key('0.1.0-beta.11.0'))
        for value in ('','0.1.0-beta.11.1.2','0.1.0-beta.11.x','0.1.0-beta.11.1-extra'):
            with self.subTest(value=value),self.assertRaises(ValueError):u.version_key(value)

    def test_journal_restores_overwrite_new_and_deleted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'old.py').write_bytes(b'old');(root/'retired.py').write_bytes(b'retired')
            (root/'mod-settings.json').write_bytes(b'preferences')
            txn=u.Transaction(root,'new');txn.write('old.py',b'new');txn.write('sub/new.py',b'added');txn.remove('retired.py')
            self.assertTrue(u.recover(root));self.assertEqual((root/'old.py').read_bytes(),b'old')
            self.assertEqual((root/'retired.py').read_bytes(),b'retired');self.assertFalse((root/'sub/new.py').exists())
            self.assertEqual((root/'mod-settings.json').read_bytes(),b'preferences');self.assertFalse(u.recover(root))

    def test_completed_update_not_undone_without_explicit_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a').write_bytes(b'original');txn=u.Transaction(root,'new');txn.write('a',b'new');txn.finish()
            self.assertFalse(u.recover(root));self.assertEqual((root/'a').read_bytes(),b'new')
            self.assertTrue(u.recover(root,completed=True));self.assertEqual((root/'a').read_bytes(),b'original')

    def test_damage_to_backup_refuses_before_restoring_any_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a').write_bytes(b'old');txn=u.Transaction(root,'new');txn.write('a',b'new');txn.write('b',b'b')
            (txn.backup/'a').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):u.recover(root)
            self.assertEqual((root/'a').read_bytes(),b'new');self.assertEqual((root/'b').read_bytes(),b'b')

    def test_write_ahead_record_survives_failure_before_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a').write_bytes(b'old');txn=u.Transaction(root,'new')
            original=u.atomic
            def fail(path,data):
                if Path(path)==root/'a':raise OSError('simulated disk error')
                original(path,data)
            with patch.object(u,'atomic',side_effect=fail),self.assertRaises(OSError):txn.write('a',b'new')
            self.assertIn('a',json.loads((root/'update-status.json').read_text())['files'])
            u.recover(root);self.assertEqual((root/'a').read_bytes(),b'old')

    def test_refuses_traversal_ambiguous_names_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in ('../x','C:/x','/x','a\\b','a/./b','a//b','x:stream','x.','a/../b'):
                with self.subTest(path=path),self.assertRaises(ValueError):u.bounded(tmp,path)
            with patch.object(u,'linked',return_value=True),self.assertRaises(ValueError):u.bounded(tmp,'x')

    def test_update_lock_excludes_competitor(self):
        with tempfile.TemporaryDirectory() as tmp,u.update_lock(tmp):
            with self.assertRaises((ValueError,OSError)):
                with u.update_lock(tmp):pass

    def test_platform_documents_and_license_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in u.DOCUMENTS:(root/name).write_bytes(b'document')
            (root/'requirements-player-linux.lock').write_bytes(b'linux-lock')
            (root/'dependencies-linux.json').write_text(json.dumps(dict(licenses={'notices-linux/pkg/LICENSE':'sha'})))
            for name in ('notices/font/OFL.txt','notices-linux/pkg/LICENSE'):
                path=root/name;path.parent.mkdir(parents=True);path.write_bytes(b'license')
            files=u.setup_files(root,False)
            self.assertEqual(files['requirements-player.lock'],b'linux-lock')
            self.assertEqual(json.loads(files['dependencies.json'])['licenses'],{'notices/pkg/LICENSE':'sha'})
            self.assertEqual(files['notices/font/OFL.txt'],b'license')
            self.assertEqual(files['notices/pkg/LICENSE'],b'license')
            (root/'requirements-player.lock').write_bytes(b'windows-lock')
            (root/'dependencies.json').write_bytes(b'{"licenses": {}}')
            self.assertEqual(u.setup_files(root,True)['requirements-player.lock'],b'windows-lock')

    def test_bundle_rejects_extra_missing_and_modified_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'code.py').write_bytes(b'code')
            (root/'updater-files.json').write_bytes(u.json_bytes(dict(schema=1,files={'code.py':u.digest(root/'code.py')})))
            u.verify_bundle(root)
            (root/'extra.py').write_bytes(b'extra')
            with self.assertRaises(ValueError):u.verify_bundle(root)
            (root/'extra.py').unlink();(root/'code.py').write_bytes(b'changed')
            with self.assertRaises(ValueError):u.verify_bundle(root)
            (root/'code.py').unlink()
            with self.assertRaises(ValueError):u.verify_bundle(root)

    def test_launchers_support_spanish_without_encoding_failure(self):
        import install_player
        for text in install_player.windows_scripts('es').values():text.encode('ascii')

    def test_recovery_preserves_executable_mode(self):
        if os.name=='nt':self.skipTest('POSIX permission bits')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'Play.sh';script.write_bytes(b'old');script.chmod(0o755)
            txn=u.Transaction(root,'new');txn.write('Play.sh',b'new')
            self.assertEqual(script.stat().st_mode&0o777,0o755)
            txn.remove('Play.sh');u.recover(root)
            self.assertEqual(script.stat().st_mode&0o777,0o755)


class UpdateFlowTests(unittest.TestCase):
    @contextmanager
    def installation(self,adapter,version='0.1.0-beta.13.3',epoch=None):
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            base=Path(tmp);root=base/'installed';setup=base/'setup'
            root.mkdir();setup.mkdir();(root/'game/tools').mkdir(parents=True)
            release=dict(version='0.1.0-beta.13.3',version_epoch=2)
            installed=dict(version=version)
            if epoch is not None:installed['version_epoch']=epoch
            files={'game/tools/updated.py':b'new runtime\n','online/netplay/new.py':b'new online\n',
                   'release.json':u.json_bytes(release)}
            # Even a receipt claiming the desired file hashes must not prevent
            # repair when the actual files are old, missing or damaged.
            hashes={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
            hashes['game/tools/retired.py']=hashlib.sha256(b'retired').hexdigest()
            receipt=dict(schema=1,adapter=adapter,files=hashes,**installed)
            for name,data in {'installed-files.json':u.json_bytes(receipt),'release.json':u.json_bytes(installed),
                              'game/player-install.json':u.json_bytes(installed),
                              'install-status.json':u.json_bytes(dict(ready=True,**installed)),
                              'requirements-player.lock':b'deps','game/tools/updated.py':b'old runtime\n',
                              'game/tools/retired.py':b'retired',
                              'game/mod-settings.json':b'{"language":"es"}',
                              'online/data/profile.json':b'private profile',
                              'game/missions/mine.json':b'edited scenario',
                              'game/runtime28/memcards/Mcd001.ps2':b'save data'}.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            for name,data in {'release.json':u.json_bytes(release),'player-payload.zip':b'checked payload',
                              'requirements-player.lock':b'deps','requirements-player-linux.lock':b'deps'}.items():
                (setup/name).write_bytes(data)
            (setup/'updater-files.json').write_bytes(u.json_bytes(dict(schema=1,files={
                path.name:u.digest(path) for path in setup.iterdir()})))
            def run(destination,script,*args):
                if Path(script).name=='compile-hook.py':
                    hooks=Path(args[1]);hooks.mkdir();(hooks/'test.pnach').write_bytes(b'generated hook')
                else:
                    (destination/'check-status.json').write_bytes(u.json_bytes(dict(ready=True,installation_valid=True)))
            installer=SimpleNamespace(unpack=lambda *_:None,runtime_graphics_plan=lambda *_:{})
            stack.enter_context(patch.dict('sys.modules',install_player=installer))
            stack.enter_context(patch.object(u,'assert_closed'))
            stack.enter_context(patch.object(u,'source_files',return_value=files))
            stack.enter_context(patch.object(u,'run',side_effect=run))
            yield root,setup,files

    def test_same_version_refresh_repairs_actual_files_and_is_repeatable(self):
        for adapter in ('bt3-usa','bt3-pal','bt3-jpn','bt4-b14-rev2-eng'):
            with self.subTest(adapter=adapter),self.installation(adapter) as (root,setup,files):
                protected={name:(root/name).read_bytes() for name in ('game/mod-settings.json',
                    'online/data/profile.json','game/missions/mine.json','game/runtime28/memcards/Mcd001.ps2')}
                result=u.update(root,setup)
                self.assertEqual(result['version'],'0.1.0-beta.13.3')
                self.assertEqual(result['changed'],3)
                self.assertFalse((root/'game/tools/retired.py').exists())
                self.assertFalse(u.changed_files(root,files))
                receipt=u.read_json(root/'installed-files.json')
                self.assertEqual(receipt['version_epoch'],2)
                self.assertEqual(receipt['update_payload_sha256'],u.digest(setup/'player-payload.zip'))
                self.assertEqual(u.update(root,setup)['changed'],0)
                (root/'game/tools/updated.py').write_bytes(b'corrupt')
                (root/'online/netplay/new.py').unlink()
                self.assertEqual(u.update(root,setup)['changed'],2)
                self.assertFalse(u.changed_files(root,files))
                self.assertEqual(protected,{name:(root/name).read_bytes() for name in protected})

    def test_legacy_higher_number_updates_through_the_full_update_flow(self):
        for version in ('0.1.0-beta.30','0.1.0-beta.46'):
            with self.subTest(version=version),self.installation('bt3-usa',version) as (root,setup,files):
                u.update(root,setup)
                self.assertEqual(u.read_json(root/'installed-files.json')['version_epoch'],2)
                self.assertFalse(u.changed_files(root,files))

    def test_true_newer_installation_is_not_changed(self):
        with self.installation('bt3-usa','0.1.0-beta.30',2) as (root,setup,files):
            before=(root/'installed-files.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'newer than this updater'):u.update(root,setup)
            self.assertEqual((root/'installed-files.json').read_bytes(),before)
            self.assertEqual((root/'game/tools/updated.py').read_bytes(),b'old runtime\n')
            self.assertFalse((root/'update-status.json').exists())

    def test_same_version_verification_failure_rolls_back(self):
        with self.installation('bt4-b14-rev2-eng') as (root,setup,files):
            receipt=(root/'installed-files.json').read_bytes()
            original=u.run
            def tamper(destination,script,*args):
                original(destination,script,*args)
                if Path(script).name=='check_installation.py':
                    (destination/'game/tools/updated.py').write_bytes(b'unexpected change')
            with patch.object(u,'run',side_effect=tamper),self.assertRaisesRegex(ValueError,'final check'):
                u.update(root,setup)
            self.assertEqual((root/'installed-files.json').read_bytes(),receipt)
            self.assertEqual((root/'game/tools/updated.py').read_bytes(),b'old runtime\n')
            self.assertTrue((root/'game/tools/retired.py').is_file())
            self.assertFalse((root/'online/netplay/new.py').exists())


if __name__=='__main__':unittest.main()
