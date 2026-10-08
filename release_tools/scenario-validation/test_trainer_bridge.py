"""No socket/emulator: real guest transactions against the MIPS test machine."""
import json
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import trainer_bridge as b
from test_native_preparation import machine


class Client:
    def __init__(self, cpu): self.cpu = cpu; self.reads = 0
    def read(self, address, size): self.reads += 1; return self.cpu.read(address, size)
    def read_u32(self, address): return b.word(self.read(address, 4))
    def write(self, address, data): self.cpu.write(address, data)
    def write_u32(self, address, value):
        self.cpu.w(address, value)
        if address == b.prep.CONTROL+16: self.cpu.w(b.prep.CONTROL+20, value)
        if address == b.prep.CONTROL+4: self.cpu.run(b.prep.CODE)


def fixture():
    c = machine(); p = Client(c); manager = 0x1800000
    c.w(b.prep.CONTROL+16, 0); c.w(b.prep.CONTROL+20, 0); c.w(manager, 2)
    c.write(b.core.MODE, struct.pack('<4I', 1, 4, manager, 4))
    c.write(b.modes.CONTROL, struct.pack('<6I', b.modes.MAGIC, manager, 4, 2, 5, 7))
    c.w(0x2FEB38, 0x1700000); c.w(0x1700000, 3)
    for i in range(4):
        actor, model = 0x1900000+0x1600*i, 0x2000000+0x2000*i
        c.w(b.core.POINTERS+4*i, actor); c.w(b.core.MODELS+4*i, model); c.w(b.core.TABLE+4*i, i ^ 1)
        c.w(actor+12, i); c.w(actor+0x994, 1); c.w(actor+0x998, 2)
        c.w(model+12, i); c.w(actor+0x9A4+164, i)
        c.write(actor+0x9E4+164, struct.pack('<7I', 23000, 30000, 0, 40000, 50000, 120000, 500000))
    return p


def request(state, **updates):
    result = {key: state['fighters'][0][key] for key in ('physical', 'actor', 'model', 'character', 'slot', 'row')}
    result.update(epoch='epoch', created=time.time(), field='hp', value=25000)
    result.update(updates); return result


class BridgeTests(unittest.TestCase):
    def test_reads_selected_row_and_skips_absent_padded_actor(self):
        p = fixture(); state = b.snapshot(p)
        self.assertEqual(len(state['fighters']), 3)
        self.assertEqual(state['mode'], 'coop')
        self.assertEqual(state['fighters'][0]['hp'], 23000)
        self.assertEqual(state['fighters'][0]['stocks'], 120000)
        self.assertTrue(state['editable'])

    def test_real_guest_commit_edits_only_selected_gauge_and_releases_hold(self):
        p = fixture(); state = b.snapshot(p); fighter = state['fighters'][0]
        before = p.read(fighter['actor'], 0x1600)
        b.edit(p, request(state), state, 'epoch')
        expected = bytearray(before); struct.pack_into('<I', expected, fighter['row']-fighter['actor'], 25000)
        self.assertEqual(p.read(fighter['actor'], 0x1600), expected)
        self.assertEqual(p.read_u32(b.prep.CONTROL+16), 0)

    def test_rejects_stale_invalid_and_dead_edits_before_hold(self):
        for changes in ({'epoch': 'old'}, {'created': time.time()-10}, {'created': 'bad'}, {'character': 90},
                        {'created': 10**400}, {'created': float('nan')}, {'created': float('inf')},
                        {'value': 0}, {'value': 30001}, {'value': True}, {'field': 'actor'}, {'field': []}, {'row': 12}):
            p = fixture(); state = b.snapshot(p)
            with self.subTest(changes=changes), self.assertRaises(b.Rejected): b.edit(p, request(state, **changes), state, 'epoch')
            self.assertEqual(p.read_u32(b.prep.CONTROL+16), 0)
        p = fixture(); state = b.snapshot(p); state['fighters'][0]['alive'] = False
        with self.assertRaises(b.Rejected): b.edit(p, request(state), state, 'epoch')

    def test_body_replaced_before_hold_is_rejected_and_hold_released(self):
        p = fixture(); state = b.snapshot(p)
        p.cpu.w(state['fighters'][0]['model']+12, 91)
        with self.assertRaises(b.Rejected): b.edit(p, request(state), state, 'epoch')
        self.assertEqual(p.read_u32(b.prep.CONTROL+16), 0)
        self.assertEqual(p.read_u32(state['fighters'][0]['row']), 23000)

    def test_uncertain_guest_commit_stays_held_and_propagates(self):
        p = fixture(); state = b.snapshot(p)
        with patch.object(b.prep, 'apply', side_effect=TimeoutError('unknown receipt')):
            with self.assertRaises(TimeoutError): b.edit(p, request(state), state, 'epoch')
        self.assertEqual(p.read_u32(b.prep.CONTROL+16), 1)

    def test_existing_hold_or_pending_transaction_is_not_stolen(self):
        for offset in (16, 20, 4):
            p = fixture(); state = b.snapshot(p); p.cpu.w(b.prep.CONTROL+offset, 1)
            with self.assertRaises(b.Rejected): b.edit(p, request(state), state, 'epoch')
            self.assertEqual(p.read_u32(b.prep.CONTROL+offset), 1)
            self.assertEqual(p.read_u32(state['fighters'][0]['row']), 23000)

    def test_rewind_between_preflight_and_hold_cannot_edit_reused_body(self):
        p = fixture(); p.cpu.w(b.prep.CONTROL+40, 100); state = b.snapshot(p)
        quiet = b.prep.quiet
        def rewind(client):
            quiet(client); client.cpu.w(b.prep.CONTROL+40, 5)
        with patch.object(b.prep, 'quiet', side_effect=rewind), self.assertRaises(b.Rejected):
            b.edit(p, request(state), state, 'epoch')
        self.assertEqual(p.read_u32(state['fighters'][0]['row']), 23000)
        self.assertEqual(p.read_u32(b.prep.CONTROL+16), 0)

    def test_native_body_change_wins_hold_race_without_gui_releasing_it(self):
        import body_swap
        p = fixture(); state = b.snapshot(p); quiet = b.prep.quiet
        def claim(client):
            quiet(client)
            client.write(body_swap.CONTROL, struct.pack('<6I', body_swap.MAGIC, state['manager'], state['count'], 0, 3, 1))
        with patch.object(b.prep, 'quiet', side_effect=claim), self.assertRaises(b.Rejected):
            b.edit(p, request(state), state, 'epoch')
        self.assertEqual(p.read_u32(state['fighters'][0]['row']), 23000)
        self.assertEqual(p.read_u32(b.prep.CONTROL+16), 1)

    def test_no_lease_means_no_game_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            p = fixture(); bridge = b.Bridge(folder); bridge.service(p)
            self.assertEqual(p.reads, 0)

    def test_defusion_wins_hold_race_without_gui_edit_or_resume(self):
        import fusion_duration as duration
        p=fixture();state=b.snapshot(p);quiet=b.prep.quiet
        def claim(client):
            quiet(client)
            client.write(duration.CONTROL,struct.pack('<4I',duration.MAGIC,state['manager'],state['count'],1))
            client.cpu.w(duration.RECORDS,3)
        with patch.object(b.prep,'quiet',side_effect=claim),self.assertRaises(b.Rejected):
            b.edit(p,request(state),state,'epoch')
        self.assertEqual(p.read_u32(state['fighters'][0]['row']),23000)
        self.assertEqual(p.read_u32(b.prep.CONTROL+16),1)

    def test_epoch_survives_socket_reconnect_but_changes_on_worker_or_rewind(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); b.atomic_files.write_json(path/'lease.json', {'created': time.time()})
            bridge = b.Bridge(folder); p = fixture(); worker = SimpleNamespace(form_job=None)
            bridge.service(p, worker); first = bridge.epoch
            bridge.next_poll = 0; bridge.service(Client(p.cpu), worker)
            self.assertEqual(bridge.epoch, first)
            p.cpu.w(b.prep.CONTROL+40, 50); bridge.next_poll = 0; bridge.service(p, worker)
            p.cpu.w(b.prep.CONTROL+40, 2); bridge.next_poll = 0; bridge.service(p, worker)
            self.assertNotEqual(bridge.epoch, first)
            second = bridge.epoch; bridge.next_poll = 0; bridge.service(p, SimpleNamespace(form_job=None))
            self.assertNotEqual(bridge.epoch, second)

    def test_busy_reload_rejects_command_and_does_not_replay_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); b.atomic_files.write_json(path/'lease.json', {'created': time.time()})
            bridge = b.Bridge(folder); p = fixture(); worker = SimpleNamespace(form_job=None)
            bridge.service(p, worker)
            state = b.atomic_files.read_json(path/'snapshot.json')
            b.atomic_files.write_json(path/'requests'/'one.json', request(state, epoch=bridge.epoch))
            worker.form_job = object(); bridge.next_poll = 0; bridge.service(p, worker)
            self.assertFalse(b.atomic_files.read_json(path/'results'/'one.json')['ok'])
            worker.form_job = None; bridge.next_poll = 0; bridge.service(p, worker)
            self.assertEqual(p.read_u32(state['fighters'][0]['row']), 23000)
            self.assertFalse(list((path/'requests').glob('*.json')))

    def test_malformed_command_is_rejected_without_stopping_trainer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); b.atomic_files.write_json(path/'lease.json', {'created': time.time()})
            b.atomic_files.write_json(path/'requests'/'bad.json', ['not a command'])
            bridge = b.Bridge(folder); bridge.service(fixture())
            self.assertFalse(b.atomic_files.read_json(path/'results'/'bad.json')['ok'])

    def test_any_exception_after_guest_commit_begins_is_terminal_for_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); b.atomic_files.write_json(path/'lease.json', {'created': time.time()})
            bridge = b.Bridge(folder); p = fixture(); worker = SimpleNamespace(form_job=None)
            bridge.service(p, worker); state = b.atomic_files.read_json(path/'snapshot.json')
            for token in ('first', 'second'):
                b.atomic_files.write_json(path/'requests'/(token+'.json'), request(state, epoch=bridge.epoch))
            bridge.next_poll = 0
            with patch.object(b.prep, 'apply', side_effect=TypeError('uncertain commit')):
                with self.assertRaises(TypeError): bridge.service(p, worker)
            self.assertEqual(p.read_u32(b.prep.CONTROL+16), 1)
            self.assertTrue((path/'requests'/'second.json').exists())
            self.assertFalse(b.atomic_files.read_json(path/'results'/'first.json')['ok'])

    def test_unreadable_command_does_not_stop_game_or_acquire_hold(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); b.atomic_files.write_json(path/'lease.json', {'created': time.time()})
            b.atomic_files.write_json(path/'requests'/'locked.json', {})
            original = b.atomic_files.read_json
            def read(at):
                if Path(at).suffix == '.processing': raise PermissionError('sharing')
                return original(at)
            p = fixture()
            with patch.object(b.atomic_files, 'read_json', side_effect=read): b.Bridge(folder).service(p)
            self.assertEqual(p.read_u32(b.prep.CONTROL+16), 0)
            self.assertFalse(b.atomic_files.read_json(path/'results'/'locked.json')['ok'])

    def test_submission_order_is_preserved_across_distinct_hold_cycles(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); b.atomic_files.write_json(path/'lease.json', {'created': time.time()})
            bridge = b.Bridge(folder); p = fixture(); worker = SimpleNamespace(form_job=None)
            bridge.service(p, worker); state = b.atomic_files.read_json(path/'snapshot.json')
            for name, value, mtime in (('z-first', 24000, 1000), ('a-second', 26000, 1001)):
                target = path/'requests'/(name+'.json')
                b.atomic_files.write_json(target, request(state, epoch=bridge.epoch, value=value))
                os.utime(target, (mtime, mtime))
            bridge.next_poll = 0; bridge.service(p, worker)
            self.assertEqual(p.read_u32(state['fighters'][0]['row']), 24000)
            bridge.next_poll = 0; bridge.service(p, worker)
            self.assertEqual(p.read_u32(state['fighters'][0]['row']), 26000)


if __name__ == '__main__': unittest.main()
