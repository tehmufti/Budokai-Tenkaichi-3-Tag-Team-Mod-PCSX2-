"""Native executable caching preserves fresh files and independent callers."""
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from prototype import elf_reader, _elf_reader_cached


def fixture(value):
    blob=bytearray(88);blob[:7]=b'\x7fELF\x01\x01\x01'
    struct.pack_into('<I',blob,28,52);struct.pack_into('<HH',blob,42,32,1)
    struct.pack_into('<8I',blob,52,1,84,0x100000,0,4,4,0,0)
    struct.pack_into('<I',blob,84,value)
    return bytes(blob)


class ElfReaderCacheTests(unittest.TestCase):
    def test_repeated_reader_uses_one_disk_read_without_sharing_mutable_segments(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'game.elf';p.write_bytes(fixture(7));_elf_reader_cached.cache_clear()
            original=Path.read_bytes
            with patch.object(Path,'read_bytes',autospec=True,side_effect=original) as read:
                _,segments,first=elf_reader(p);segments.clear()
                _,segments,second=elf_reader(p)
                self.assertEqual(read.call_count,1);self.assertEqual(len(segments),1)
                self.assertEqual(first(0x100000,4),second(0x100000,4))

    def test_replaced_same_size_executable_invalidates_cache_and_old_reader_stays_consistent(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'game.elf';p.write_bytes(fixture(7));old=elf_reader(p)[2]
            stamp=p.stat();p.write_bytes(fixture(9))
            os.utime(p,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+10000000))
            self.assertEqual(elf_reader(p)[2](0x100000,4),struct.pack('<I',9))
            self.assertEqual(old(0x100000,4),struct.pack('<I',7))
            with self.assertRaises(ValueError):old(0xFFFFFF,4)


if __name__=='__main__':unittest.main()
