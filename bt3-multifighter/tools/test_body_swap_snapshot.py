import unittest
from types import SimpleNamespace

import body_swap_snapshot as fix
import lazy_ram


class SnapshotTests(unittest.TestCase):
    def client(self):
        state=SimpleNamespace(value=1,calls=[],short=False)
        def read(address,length):
            state.calls.append(('read',address,length));return bytes([state.value])*length
        def batch(ranges):
            state.calls.append(('batch',list(ranges)))
            return [bytes([state.value])*(n-int(state.short)) for _,n in ranges]
        state.read=read;state.read_ranges=batch
        return state

    def test_renew_batches_fresh_known_pages_and_expires_analysis_views(self):
        p=self.client();ram=fix.Snapshot(p)
        self.assertEqual(ram[12],1);self.assertEqual(ram[3*lazy_ram.CHUNK],1)
        view=ram.view({12:b'\x05'});self.assertEqual(view[12],5)
        p.calls.clear();p.value=2;identity=id(ram)
        self.assertIs(ram.renew(p),ram);self.assertEqual(id(ram),identity)
        self.assertEqual(p.calls,[('batch',[(0,lazy_ram.CHUNK),(3*lazy_ram.CHUNK,lazy_ram.CHUNK)])])
        self.assertEqual((ram[12],ram[3*lazy_ram.CHUNK]),(2,2))
        with self.assertRaisesRegex(RuntimeError,'expired'):view[12]
        # Newly discovered pages remain lazy and also read the current client.
        self.assertEqual(ram[8*lazy_ram.CHUNK],2);self.assertEqual(p.calls[-1][0],'read')

    def test_short_batch_is_poisoned_and_no_old_bytes_survive_reconnect(self):
        p=self.client();ram=fix.Snapshot(p);ram[1];ram[3*lazy_ram.CHUNK]
        p.short=True
        with self.assertRaisesRegex(IOError,'Short'):ram.renew(p)
        self.assertEqual(sum(ram.fetched),0)
        self.assertEqual(bytearray.__getitem__(ram,1),lazy_ram.POISON)
        p2=self.client();p2.value=7;ram.renew(p2)
        self.assertEqual(p2.calls,[]);self.assertEqual(ram[1],7)
        self.assertEqual(p2.calls,[('read',0,lazy_ram.CHUNK)])

    def test_clients_without_batch_still_use_fresh_reads(self):
        p=self.client();del p.read_ranges
        ram=fix.Snapshot(p);self.assertEqual(ram[1],1)
        p.value=2;ram.renew(p);self.assertEqual(sum(ram.fetched),0)
        self.assertEqual(ram[1],2)


if __name__=='__main__':unittest.main()
