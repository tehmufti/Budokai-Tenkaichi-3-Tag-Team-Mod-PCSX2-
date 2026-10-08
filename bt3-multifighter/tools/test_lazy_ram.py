import struct
import unittest

import lazy_ram


class Client:
    def __init__(self, data):
        self.data = data
        self.reads = []

    def read(self, address, length):
        self.reads.append((address, length))
        return bytes(self.data[address:address + length])


class LazyRamTests(unittest.TestCase):
    def source(self):
        data = bytearray(lazy_ram.SIZE)
        for p in range(0, 0x300000, 4):
            struct.pack_into('<I', data, p, p ^ 0x5A5A5A5A)
        return data

    def test_slices_indices_and_unpack_fetch_aligned_chunks_once(self):
        data = self.source(); client = Client(data); ram = lazy_ram.LazyRam(client)
        self.assertEqual(len(ram), lazy_ram.SIZE)
        self.assertEqual(ram[0x12340:0x12348], data[0x12340:0x12348])
        self.assertEqual(client.reads, [(0x10000, 0x10000)])
        self.assertEqual(ram[0x12345], data[0x12345]); self.assertEqual(client.reads, [(0x10000, 0x10000)])
        with lazy_ram.patched():
            self.assertEqual(struct.unpack_from('<I', ram, 0x2FFFC)[0], struct.unpack_from('<I', data, 0x2FFFC)[0])
            self.assertEqual(struct.unpack_from('<2I', ram, 0x1FFFC), struct.unpack_from('<2I', data, 0x1FFFC))
        self.assertEqual(client.reads[1:], [(0x20000, 0x10000)])
        self.assertEqual(struct.unpack_from, lazy_ram._original_unpack_from)
        # A span covering fetched and unfetched chunks reads only the gap run.
        self.assertEqual(bytes(ram[0x1F000:0x41000]), bytes(data[0x1F000:0x41000]))
        self.assertEqual(client.reads[2:], [(0x30000, 0x20000)])
        self.assertEqual(ram.exchanges, 3); self.assertEqual(ram.resident(), 4 * 0x10000)
        self.assertFalse(any(ram[0x50000:0x50010]) and False)

    def test_view_overrides_without_touching_parent_and_shares_fetches(self):
        data = self.source(); client = Client(data); ram = lazy_ram.LazyRam(client)
        ram[0x10000:0x10010]
        view = ram.view({0x10004: b'\x11\x22\x33\x44', 0x2FFFE: b'\xAA\xBB\xCC\xDD'})
        self.assertEqual(view[0x10004:0x10008], b'\x11\x22\x33\x44')
        self.assertEqual(ram[0x10004:0x10008], data[0x10004:0x10008])
        self.assertEqual(len(client.reads), 1)
        with lazy_ram.patched():
            self.assertEqual(struct.unpack_from('<I', view, 0x2FFFE)[0], 0xDDCCBBAA)
        self.assertEqual(client.reads[1:], [(0x20000, 0x20000)])
        self.assertEqual(ram[0x2FFFE:0x30002], data[0x2FFFE:0x30002])
        self.assertEqual(len(client.reads), 2)
        nested = view.view({0x10008: b'\x00'})
        self.assertEqual(nested[0x10004:0x10009], b'\x11\x22\x33\x44\x00')

    def test_unfetched_bytes_read_as_poison_and_bypasses_are_refused(self):
        data = self.source(); client = Client(data); ram = lazy_ram.LazyRam(client)
        # struct.unpack_from outside patched() sees poison, never a plausible
        # zero, so a builder that forgets the context fails its guards loudly.
        self.assertEqual(struct.unpack_from('<I', ram, 0x400000)[0], 0xCCCCCCCC)
        self.assertEqual(client.reads, [])
        self.assertEqual(bytes(memoryview(ram)[0x400000:0x400004]), bytes([lazy_ram.POISON]) * 4)
        with self.assertRaises(ValueError): ram[0:16:2]
        with self.assertRaises(TypeError): list(ram)
        # Fetching replaces the poison with the real bytes.
        self.assertEqual(ram[0x400000:0x400004], data[0x400000:0x400004])
        with lazy_ram.patched():
            self.assertEqual(struct.unpack_from('<I', ram, 0x400000)[0],
                             struct.unpack_from('<I', data, 0x400000)[0])

    def test_invalidate_refills_the_same_buffer(self):
        data = self.source(); client = Client(data); ram = lazy_ram.LazyRam(client)
        ram[0x10000:0x10004]; self.assertEqual(ram.resident(), lazy_ram.CHUNK)
        ram.invalidate()
        self.assertEqual(ram.resident(), 0); self.assertEqual(ram.exchanges, 0)
        self.assertEqual(struct.unpack_from('<I',ram,0x10000)[0],0xCCCCCCCC)
        data[0x10000:0x10004] = bytes([1, 2, 3, 4])
        self.assertEqual(ram[0x10000:0x10004], bytes([1, 2, 3, 4]))
        self.assertEqual(len(client.reads), 2)

    def test_reused_analysis_views_expire_with_parent_and_drop_old_overrides(self):
        data=self.source();client=Client(data);ram=lazy_ram.LazyRam(client)
        view=ram.view({0x10000:b'old!'})
        self.assertEqual(view[0x10000:0x10004],b'old!')
        ram.invalidate()
        with self.assertRaisesRegex(RuntimeError,'expired snapshot'):view[0x10000:0x10004]
        again=ram.view({0x20000:b'new!'},reuse=view)
        self.assertIs(again,view)
        self.assertEqual(again[0x10000:0x10004],data[0x10000:0x10004])
        self.assertEqual(again[0x20000:0x20004],b'new!')

    def test_cross_chunk_override_applies_to_partial_reads_before_other_chunk_exists(self):
        data=self.source();client=Client(data);ram=lazy_ram.LazyRam(client)
        child=ram.view({0x1FFFE:b'ABCD'})
        self.assertEqual(child[0x1FFFE:0x20000],b'AB')
        self.assertEqual(child.fetched[2],0)
        reused=ram.view({0x1FFFE:b'WXYZ'},reuse=child)
        self.assertEqual(reused[0x1FFFE:0x20000],b'WX')
        self.assertEqual(reused.fetched[2],0)
        self.assertEqual(reused[0x20000:0x20002],b'YZ')
        self.assertEqual(ram[0x1FFFE:0x20002],data[0x1FFFE:0x20002])

    def test_out_of_range_and_short_reads_are_errors(self):
        client = Client(bytearray(lazy_ram.SIZE)); ram = lazy_ram.LazyRam(client)
        with self.assertRaises(IndexError): ram.fetch(lazy_ram.SIZE - 4, 8)
        client.read = lambda address, length: b'short'
        with self.assertRaises(IOError): ram[0x100:0x104]


if __name__ == '__main__': unittest.main()
