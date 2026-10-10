import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import update_player as u


class UpdateTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
