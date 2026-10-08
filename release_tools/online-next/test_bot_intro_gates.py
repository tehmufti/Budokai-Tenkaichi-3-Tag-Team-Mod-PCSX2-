"""All-CPU rooms and departed seats retain real frame-scheduled loader/voice gates."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'bt3-multifighter/online/netplay'))
import kit_lockstep as lockstep


def hub(slot=None):
    h=lockstep.Hub.__new__(lockstep.Hub)
    h.slot=slot;h.layout=4;h.delay=1;h.dropped={0:1};h.have={0:1,1:1}
    h.inputs={0:{},1:{}};h.own_aux={}
    return h


class BotIntroGates(unittest.TestCase):
    def test_spectator_host_relays_capture_gates_with_neutral_buttons(self):
        h=hub();h.own_aux={1:0x00000101,2:0x00010101,3:0x00020102}
        h.fill_dropped(3)
        self.assertEqual(h.inputs[0],{f:(lockstep.nc.NEUTRAL,v) for f,v in h.own_aux.items()})
        self.assertEqual(h.have[0],4)

    def test_no_future_gate_is_fabricated_or_changed_after_publication(self):
        h=hub();h.own_aux={1:0x10000,3:0x20000};h.fill_dropped(3)
        self.assertEqual(h.have[0],2);self.assertNotIn(3,h.inputs[0])
        h.own_aux[1]=0xEE0000;h.own_aux[2]=0x10000;h.fill_dropped(4)
        self.assertEqual(h.inputs[0][1][1],0x10000)
        self.assertEqual(h.inputs[0][3][1],0x20000)

    def test_departed_seat_gets_host_gates_never_host_buttons(self):
        h=hub(1);h.inputs[1]={1:(bytes(8),0x00010304)};h.fill_dropped(1)
        self.assertEqual(h.inputs[0][1],(lockstep.nc.NEUTRAL,0x00010304))
        self.assertEqual(h.have[0],2)

    def test_legacy_layout_keeps_neutral_input(self):
        h=hub();h.layout=1;h.fill_dropped(1)
        self.assertEqual(h.have[0],4)
        self.assertTrue(all(v==lockstep.neutral_item() for v in h.inputs[0].values()))


if __name__=='__main__':unittest.main()
