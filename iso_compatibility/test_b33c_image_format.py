"""Readable, coded errors for files that are not complete plain ISO images (beta.33 group C, finding H2 / IF-12)."""
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from .disc import Disc, FormatError, image_problem, preflight
from . import scanner

ROOT = Path(__file__).resolve().parents[1]
USA = ROOT/'games/Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
RAW_SYNC = b'\x00'+b'\xff'*10+b'\x00'


def pvd_image(blocks=18, declared=None):
    data = bytearray(blocks*2048); data[0x8000:0x8006] = b'\x01CD001'
    struct.pack_into('<I', data, 0x8050, blocks if declared is None else declared)
    return bytes(data)


def damaged_file_system():
    """A small, complete ISO 9660 image (valid volume descriptor and size) whose root directory block is overwritten:
    a damaged dump, not another kind of file."""
    import io
    import pycdlib
    iso = pycdlib.PyCdlib(); iso.new()
    config = b'BOOT2 = cdrom0:\\SLUS_123.45;1\r\n'
    iso.add_fp(io.BytesIO(config), len(config), '/SYSTEM.CNF;1')
    out = io.BytesIO(); iso.write_fp(out); iso.close()
    data = bytearray(out.getvalue())
    root = struct.unpack_from('<I', data, 0x8000+156+2)[0]
    data[root*2048:(root+1)*2048] = b'\xff'*2048
    return bytes(data)


class ImageFormatTests(unittest.TestCase):
    SAMPLES = {'chd': (b'MComprHD'+bytes(9000), 'TTM-ISO-02', {'format': 'CHD'}),
               'cso': (b'CISO'+bytes(9000), 'TTM-ISO-03', {'format': 'CSO', 'extension': 'cso'}),
               'zso': (b'ZISO'+bytes(9000), 'TTM-ISO-03', {'format': 'ZSO', 'extension': 'zso'}),
               '7z': (b"7z\xbc\xaf'\x1c"+bytes(9000), 'TTM-ISO-01', {'format': '7z'}),
               'zip': (b'PK\x03\x04'+bytes(9000), 'TTM-ISO-01', {'format': 'ZIP'}),
               'rar': (b'Rar!\x1a\x07\x01\x00'+bytes(9000), 'TTM-ISO-01', {'format': 'RAR'}),
               'gz': (b'\x1f\x8b\x08'+bytes(9000), 'TTM-ISO-01', {'format': 'gzip (.gz)'}),
               'raw': (RAW_SYNC+bytes(60000), 'TTM-ISO-04', {}),
               'cue': (b'FILE "BT3.bin" BINARY\n  TRACK 01 MODE2/2352\n', 'TTM-ISO-04', {}),
               'empty': (b'', 'TTM-ISO-05', {'size': 0}),
               'zeros': (bytes(1 << 20), 'TTM-ISO-05', {'size': 1 << 20}),
               'truncated': (pvd_image(18, declared=1000), 'TTM-ISO-06', {'size': 18*2048, 'expected': 1000*2048}),
               'plain': (pvd_image(18), None, None), 'padded': (pvd_image(18, declared=10), None, None)}

    def test_every_sample_is_named_before_it_is_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, (data, code, details) in self.SAMPLES.items():
                path = Path(tmp)/(name+'.iso'); path.write_bytes(data)
                with self.subTest(sample=name):
                    self.assertEqual(image_problem(data[:0x10000], len(data)), (code, details) if code else None)
                    if code is None: preflight(path); continue
                    with self.assertRaises(FormatError) as caught: preflight(path)
                    self.assertEqual((caught.exception.code, caught.exception.details), (code, details))
                    self.assertNotIn('{', str(caught.exception))
                    # The scanner names the problem before hashing the whole file.
                    with patch.object(scanner, 'hash_file', side_effect=AssertionError('hashed')), self.assertRaises(FormatError) as scanned:
                        scanner.scan(path, Path(tmp)/'cache', refresh=True)
                    self.assertEqual(scanned.exception.code, code)

    def test_pycdlib_and_struct_errors_become_coded_format_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, data, code in (('empty', b'', 'TTM-ISO-05'), ('zeros', bytes(1 << 20), 'TTM-ISO-05'),
                                     ('cso', b'CISO'+bytes(9000), 'TTM-ISO-03'), ('truncated', pvd_image(18, declared=1000), 'TTM-ISO-06')):
                path = Path(tmp)/(name+'.iso'); path.write_bytes(data)
                with self.subTest(sample=name), self.assertRaises(FormatError) as caught: Disc(path)
                self.assertEqual(caught.exception.code, code)
                self.assertIn('(', str(caught.exception), 'the library error stays as the technical detail')
            # A structural FormatError without a known cause keeps no code (setup reports it as TTM-ISO-09).
            self.assertIsNone(FormatError('Changed AFS header').code)

    def test_a_disc_image_with_a_broken_file_system_is_called_damaged_not_another_kind_of_file(self):
        """TTM-ISO-05 says the file has no ISO 9660 volume descriptor; a damaged dump has one (TTM-ISO-07)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'damaged.iso'; data = damaged_file_system(); path.write_bytes(data)
            self.assertIsNone(image_problem(data[:0x10000], len(data)), 'the head and the size look like a complete ISO')
            preflight(path)
            with self.assertRaises(FormatError) as caught: Disc(path)
            self.assertEqual((caught.exception.code, caught.exception.details), ('TTM-ISO-07', {}))
            self.assertIn('PyCdlib', caught.exception.cause, 'the library error is kept as the technical detail')
            with self.assertRaises(FormatError) as scanned: scanner.scan(path, Path(tmp)/'cache', refresh=True)
            self.assertEqual(scanned.exception.code, 'TTM-ISO-07')
            # Setup's block: the catalog text, the library's words as DETAILS.
            import sys
            sys.path.insert(0, str(ROOT/'player-installer'))
            try: import setup_messages
            finally: sys.path.remove(str(ROOT/'player-installer'))
            failure = setup_messages.classify(caught.exception)
            self.assertEqual((failure.code, failure.detail), ('TTM-ISO-07', caught.exception.cause))
            block = failure.render('es')
            self.assertIn('[TTM-ISO-07]', block); self.assertIn('redump.org', block); self.assertIn('DETALLES: PyCdlib', block)

    @unittest.skipUnless(USA.is_file(), 'the USA disc is not installed here')
    def test_an_incomplete_copy_of_the_real_disc_says_how_much_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            partial = Path(tmp)/'partial.iso'
            with USA.open('rb') as source: partial.write_bytes(source.read(96 << 20))
            with self.assertRaises(FormatError) as caught: Disc(partial)
            self.assertEqual(caught.exception.code, 'TTM-ISO-06')
            self.assertEqual(caught.exception.details, dict(size=96 << 20, expected=os.path.getsize(USA)))
            preflight(USA)


if __name__ == '__main__': unittest.main()
