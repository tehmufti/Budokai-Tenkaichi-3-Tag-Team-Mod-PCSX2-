"""Private parallel identity guards; no emulator or game data needed."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bt3-multifighter/online/netplay'))
import kit_selector_cache as cache

class ParallelHashTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        with cache._HASH_LOCK:cache._HASHES.clear()
    def files(self,n=12,size=100000):
        paths=[]
        for i in range(n):
            p=self.root/f'file-{i:02}.bin';p.write_bytes(bytes([i])*size);paths.append(p)
        return paths
    def expected(self,paths):
        return hashlib.sha256(cache.canonical({p.relative_to(self.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths})).hexdigest()
    def test_exact_canonical_digest_with_sorted_rows_duplicate_paths_and_missing_files(self):
        paths=self.files()
        result=cache.files_digest(self.root,list(reversed(paths))+[paths[1],self.root/'missing'])
        self.assertEqual(result,self.expected(paths))
    def test_readers_are_bounded_to_four_and_all_full_hashes_match(self):
        paths=self.files();limits=[]
        class CapturedPool(ThreadPoolExecutor):
            def __init__(self,*a,**kw):limits.append(kw['max_workers']);super().__init__(*a,**kw)
        with patch('concurrent.futures.ThreadPoolExecutor',CapturedPool):
            self.assertEqual(cache.files_digest(self.root,paths),self.expected(paths))
        self.assertEqual(limits,[4])
    def test_tiny_groups_do_not_construct_a_pool(self):
        paths=self.files(32,10)
        with patch('concurrent.futures.ThreadPoolExecutor',side_effect=AssertionError('tiny group overhead')):
            self.assertEqual(cache.files_digest(self.root,paths),self.expected(paths))
    def test_escaped_path_rejected_before_hashing_any_file(self):
        paths=self.files()
        other=tempfile.TemporaryDirectory();self.addCleanup(other.cleanup)
        escaped=Path(other.name)/'outside.bin';escaped.write_bytes(b'not installation content')
        with patch.object(cache,'sha',side_effect=AssertionError('must validate bounds first')):
            with self.assertRaisesRegex(ValueError,'escapes'):
                cache.files_digest(self.root,paths+[escaped])
    def test_malformed_path_is_rejected(self):
        with self.assertRaises(TypeError):cache.files_digest(self.root,[None])
    def test_symlink_to_outside_is_rejected(self):
        other=tempfile.TemporaryDirectory();self.addCleanup(other.cleanup)
        escaped=Path(other.name)/'file';escaped.write_bytes(b'outside')
        link=self.root/'linked'
        try:link.symlink_to(escaped)
        except OSError:self.skipTest('symlink privilege unavailable')
        with self.assertRaisesRegex(ValueError,'escapes'):cache.files_digest(self.root,[link])
    def test_mid_read_mutation_fails_and_is_not_memoized(self):
        path=self.root/'changing.bin';path.write_bytes(b'x'*(2<<20))
        original_open=Path.open;changed=False
        class ChangingReader:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def read(self,size):
                nonlocal changed
                data=self.stream.read(size)
                if data and not changed:
                    changed=True
                    with original_open(path,'ab')as out:out.write(b'changed while hashing')
                return data
        def opened(p,*args,**kwargs):
            result=original_open(p,*args,**kwargs)
            return ChangingReader(result)if p==path and args and args[0]=='rb'else result
        with patch.object(Path,'open',opened):
            with self.assertRaisesRegex(ValueError,'changed while'):cache.sha(path,memo=True)
        self.assertEqual(cache._HASHES,{})
    def test_concurrent_same_file_memo_publishes_only_the_full_correct_digest(self):
        paths=self.files();expected=self.expected(paths)
        with ThreadPoolExecutor(max_workers=4)as pool:
            results=list(pool.map(lambda _:cache.files_digest(self.root,paths),range(6)))
        self.assertEqual(results,[expected]*6)
        for path in paths:self.assertEqual(cache.sha(path,memo=True),hashlib.sha256(path.read_bytes()).hexdigest())
    def test_replacement_invalidates_process_local_memo(self):
        path=self.root/'replace';path.write_bytes(b'old');old=cache.sha(path,memo=True)
        replacement=self.root/'replacement';replacement.write_bytes(b'new');replacement.replace(path)
        new=cache.sha(path,memo=True)
        self.assertNotEqual(new,old);self.assertEqual(new,hashlib.sha256(b'new').hexdigest())
if __name__=='__main__':unittest.main()
