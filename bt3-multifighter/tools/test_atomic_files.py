"""Filesystem-only regression of the live Windows status-file sharing failure."""
import ctypes
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import atomic_files as files


class AtomicFileTests(unittest.TestCase):
    def test_transient_access_denial_retries_without_losing_old_or_new_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'; files.write_json(path, {'old': 1})
            replace = os.replace; calls = []
            def locked_first(source, target):
                calls.append(Path(source))
                if len(calls) <= 2:
                    self.assertEqual(files.read_json(path), {'old': 1})
                    raise PermissionError(13, 'Reader briefly denies replacement')
                return replace(source, target)
            with patch.object(files.os, 'replace', side_effect=locked_first):
                files.write_json(path, {'new': 2})
            self.assertEqual(len(calls), 3); self.assertEqual(files.read_json(path), {'new': 2})
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_permanent_replace_failure_keeps_original_and_cleans_own_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'; files.write_json(path, {'old': 1})
            with patch.object(files.os, 'replace', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError): files.write_json(path, {'new': 2}, timeout=0)
            self.assertEqual(files.read_json(path), {'old': 1})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_concurrent_writers_and_readers_only_observe_complete_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'; files.write_json(path, dict(writer=0, text='x'*4096))
            errors = []; names = []; stop = threading.Event(); replace = os.replace
            def tracked(source, target): names.append(str(source)); return replace(source, target)
            def writer(number):
                try:
                    for _ in range(20): files.write_json(path, dict(writer=number, text=str(number)*4096))
                except BaseException as error: errors.append(error)
            def reader():
                try:
                    while not stop.is_set():
                        value = files.read_json(path)
                        if len(value['text']) != 4096: raise AssertionError('Partial document')
                except BaseException as error: errors.append(error)
            with patch.object(files.os, 'replace', side_effect=tracked):
                reading = threading.Thread(target=reader); reading.start()
                workers = [threading.Thread(target=writer, args=(n,)) for n in (1, 2)]
                for worker in workers: worker.start()
                for worker in workers: worker.join(timeout=5)
                stop.set(); reading.join(timeout=5)
            # Windows/background readers may require multiple replacements for
            # one write, but each logical write owns exactly one unique temp.
            self.assertFalse(errors); self.assertGreaterEqual(len(names), 40)
            self.assertEqual(len(set(names)), 40)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows delete-sharing regression')
    def test_actual_windows_read_handle_denies_replace_then_retry_succeeds(self):
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                       w.DWORD, w.DWORD, w.HANDLE]
        kernel.CreateFileW.restype = w.HANDLE; kernel.CloseHandle.argtypes = [w.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'presentation.json'; files.write_json(path, dict(old=1))
            handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            denied = threading.Event(); errors = []; replace = os.replace
            def tracked(source, target):
                try: return replace(source, target)
                except PermissionError:
                    denied.set(); raise
            def writer():
                try: files.write_json(path, dict(new=2))
                except BaseException as error: errors.append(error)
            try:
                with patch.object(files.os, 'replace', side_effect=tracked):
                    worker = threading.Thread(target=writer); worker.start()
                    self.assertTrue(denied.wait(timeout=1), 'Did not reproduce Windows sharing denial')
                    kernel.CloseHandle(handle); handle = None
                    worker.join(timeout=3)
                    self.assertFalse(worker.is_alive())
            finally:
                if handle: kernel.CloseHandle(handle)
            self.assertFalse(errors); self.assertEqual(files.read_json(path), dict(new=2))


if __name__ == '__main__': unittest.main()
