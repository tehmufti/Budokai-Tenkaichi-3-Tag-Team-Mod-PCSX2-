"""Common initial archives are modified only in an owned paused frame-zero VM."""
import copy
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_fight
import kit_match
import kit_state
import kit_verify
import netplay_core as nc


class Link:
    pid = 99

    def __init__(self, memory, target):
        self.memory = bytearray(memory)
        self.target = target
        self.vm_status = 'paused'
        self.writes = []
        self.on_write = None
        self.sentinel = 0
        self.loads = 0
        self.closed = 0

    def close(self):
        self.closed += 1

    def status(self):
        return self.vm_status

    def read_ranges(self, ranges):
        return [bytes(self.memory[a:a + n]) for a, n in ranges]

    def write_ranges(self, ranges):
        self.writes.append(list(ranges))
        for address, data in ranges:
            self.memory[address:address + len(data)] = data
        if self.on_write:
            self.on_write(self)

    def w32(self, address, value):
        self.sentinel = value

    def u32(self, address):
        return self.sentinel

    def load_state(self, slot):
        with zipfile.ZipFile(self.target) as z:
            self.memory[:] = z.read(kit_state.MEMORY)
        self.sentinel = 0
        self.loads += 1


class Emulator:
    START_PAUSED = True
    CAN_POST_KEYS = True
    pid = 99

    def __init__(self, target, link):
        self.target, self.link = target, link
        self.stopped = 0
        self.pause_allowed = True
        self.owner = self.pid

    def state_file(self, slot):
        return self.target

    def pine_owner(self):
        return self.owner

    def ensure_paused(self, link):
        if self.pause_allowed:
            link.vm_status = 'paused'
        return self.pause_allowed

    def ensure_running(self, link):
        link.vm_status = 'running'
        return True

    def stop(self):
        self.stopped += 1


class Session(kit_fight.FightMixin):
    def __init__(self, source, target, memory):
        self.match = dict(state=str(source), sha=kit_state.sha256(source), delay=3, mask=3, epoch=7)
        self.epoch, self.load_generation = 7, 1
        self.phase, self.role = 'loading', 'guest'
        self.load_lock = threading.RLock()
        self.link = Link(memory, target)
        self.emulator = Emulator(target, self.link)
        self.watch_side = 0
        self.profile = {'local': {'show_native_hud': True}}
        self.local, self.cfg = {'iso': 'locally-chosen.iso'}, {}
        self.jobs, self.started = [], []
        self.rematch_copy = None

    def my_slot(self):
        return 0

    def job(self, name, fn, *args, then=None, fail=None):
        self.jobs.append((name, fn, args, then, fail))

    def begin_fight(self, late):
        self.started.append(late)


def static_words(ram, static=False):
    return {'native_static': struct.unpack('<I', ram.read_ranges([(64, 4)])[0])[0]}


class PausedMachineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source, self.target = self.root / 'source.p2s', self.root / 'slot241.p2s'
        self.memory = bytearray(512)
        struct.pack_into('<I', self.memory, 64, 0x12345678)
        self.base = 256
        for name, value in dict(magic=nc.MAGIC, layout=nc.LAYOUT, enable=1, mode=nc.LOCKSTEP,
                state=nc.ARMED, frame=0, delay=3, mask=3, local_slot=nc.NO_SLOT, self_feed=1).items():
            struct.pack_into('<I', self.memory, self.base + nc.F[name], value)
        for p in (patch.object(nc, 'CONTROL', self.base), patch.object(kit_state, 'EE_SIZE', 512),
                  patch.object(kit_verify, 'words', side_effect=static_words),
                  patch.object(kit_match, 'machine_words', side_effect=self.machine_words)):
            p.start()
            self.addCleanup(p.stop)
        self.write_source()
        self.s = Session(self.source, self.target, self.memory)

    def write_source(self):
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.comment = b'untouched native archive'
            z.writestr('native.bin', b'CPU GS SPU IOP bytes')
            z.writestr(kit_state.MEMORY, self.memory)

    def machine_words(self, source, slot, watch, local, sealed, *, memory):
        a = self.base + nc.F['local_slot']
        return {a: (struct.unpack_from('<I', memory, a)[0], nc.NO_SLOT if slot is None else slot),
                416: (struct.unpack_from('<I', memory, 416)[0], int(local['show_native_hud']))}

    def plan(self):
        return kit_match.paused_machine_copy(self.source, self.target, 0, 0,
            self.s.profile['local'], 2, state_sha=kit_state.sha256(self.source), delay=3, mask=3)

    def test_common_copy_preserves_every_archive_byte_and_never_calls_writer(self):
        with patch.object(kit_match, 'machine_copy', side_effect=AssertionError('repacked')), \
                patch.object(kit_state, 'patch_words', side_effect=AssertionError('repacked')):
            plan = self.plan()
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(plan['sha'], hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_paused_initial_vm_gets_only_guarded_fields_before_resume(self):
        plan = self.plan()
        kit_match.apply_paused_machine(self.s.link, plan)
        expected = bytearray(self.memory)
        for a, (_, new) in plan['guards'].items():
            struct.pack_into('<I', expected, a, new)
        self.assertEqual(self.s.link.memory, expected)
        self.assertEqual(self.s.link.status(), 'paused')
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_running_vm_never_receives_machine_writes(self):
        plan = self.plan()
        self.s.link.vm_status = 'running'
        with self.assertRaisesRegex(ValueError, 'paused'):
            kit_match.apply_paused_machine(self.s.link, plan)
        self.assertFalse(self.s.link.writes)

    def test_owner_loss_before_write_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'current'):
            kit_match.apply_paused_machine(self.s.link, self.plan(), current=lambda: False)
        self.assertFalse(self.s.link.writes)

    def test_started_core_or_changed_guard_or_static_never_receives_writes(self):
        for address in (self.base + nc.F['frame'], self.base + nc.F['state'],
                        self.base + nc.F['local_slot'], 64):
            with self.subTest(address=address):
                self.s.link.memory[:] = self.memory
                struct.pack_into('<I', self.s.link.memory, address, 2)
                with self.assertRaises(ValueError):
                    kit_match.apply_paused_machine(self.s.link, self.plan())
                self.assertFalse(self.s.link.writes)

    def test_failed_readback_or_unpause_after_batch_never_falls_back(self):
        for action in (lambda link: setattr(link, 'vm_status', 'running'),
                       lambda link: struct.pack_into('<I', link.memory, 416, 2),
                       lambda link: struct.pack_into('<I', link.memory, 64, 0)):
            with self.subTest(action=action):
                self.s.link.memory[:] = self.memory
                self.s.link.vm_status = 'paused'
                self.s.link.on_write = action
                with self.assertRaises(ValueError):
                    kit_match.apply_paused_machine(self.s.link, self.plan())
        self.assertEqual(len(self.s.link.writes), 3)

    def test_wrong_source_sha_and_noninitial_archive_are_rejected_before_target(self):
        for change in ('hash', 'frame'):
            if change == 'frame':
                struct.pack_into('<I', self.memory, self.base + nc.F['frame'], 10)
                self.write_source()
            expected = '0' * 64 if change == 'hash' else kit_state.sha256(self.source)
            with self.assertRaises(ValueError):
                kit_match.paused_machine_copy(self.source, self.target, 0, 0, self.s.profile['local'], 2,
                                              state_sha=expected, delay=3, mask=3)
        self.assertFalse(self.target.exists())

    def test_verified_existing_common_file_is_reused_without_copying(self):
        self.plan()
        with patch.object(kit_match.shutil, 'copyfile', side_effect=AssertionError('unnecessary copy')):
            self.plan()

    def test_profile_and_watch_inputs_are_frozen_before_worker_runs(self):
        request = self.s.load_request()
        self.s.profile['local']['show_native_hud'] = False
        self.s.watch_side = 1
        record = self.s.build_copy(request)
        self.assertEqual(record['plan']['guards'][416][1], 1)
        self.assertEqual(request['watch'], 0)
        self.assertEqual(record['plan']['core'][self.base + nc.F['delay']], 3)

    def test_mutated_match_controls_invalidate_worker_and_callbacks(self):
        for key, value in (('delay', 8), ('sha', 'f' * 64), ('mask', 15),
                           ('state', 'another-state.p2s'), ('pnach', 'another.pnach'),
                           ('spec_sha', 'e' * 64), ('max_stall', 60)):
            with self.subTest(key=key):
                request = self.s.load_request()
                previous = self.s.match.get(key)
                self.s.match[key] = value
                with self.assertRaisesRegex(ValueError, 'superseded'):
                    self.s.build_copy(request)
                self.assertFalse(self.s.link.writes)
                if previous is None:
                    self.s.match.pop(key)
                else:
                    self.s.match[key] = previous

    def test_foreign_owner_is_not_paused_before_copy(self):
        self.s.emulator.owner = 777
        with self.assertRaisesRegex(ValueError, 'before pausing'):
            self.s.build_copy()
        self.assertEqual(self.s.link.loads, 0)
        self.assertFalse(self.s.link.writes)

    def test_linux_contract_uses_conventional_copy_before_any_live_mutation(self):
        self.s.emulator.START_PAUSED = False
        with patch.object(kit_match, 'machine_copy', return_value=self.target) as conventional, \
                patch.object(kit_match, 'paused_machine_copy', side_effect=AssertionError('unsafe path')):
            result = self.s.build_copy()
        self.assertIsNone(result['plan'])
        self.assertEqual(conventional.call_count, 1)
        self.assertFalse(self.s.link.writes)

    def test_unavailable_initial_pause_falls_back_before_loading(self):
        self.s.emulator.pause_allowed = False
        with patch.object(kit_match, 'machine_copy', return_value=self.target) as conventional:
            result = self.s.build_copy()
        self.assertIsNone(result['plan'])
        self.assertEqual(conventional.call_count, 1)
        self.assertEqual(self.s.link.loads, 0)

    def test_retry_reloads_common_archive_and_reapplies_current_epoch_plan(self):
        for epoch in (7, 8):
            self.s.epoch = epoch
            self.s.match['epoch'] = epoch
            self.s.load_generation += 1
            record = self.s.build_copy()
            self.s.pine_load(record)
            self.assertEqual(struct.unpack_from('<I', self.s.link.memory, self.base + nc.F['local_slot'])[0], 0)
            self.assertEqual(struct.unpack_from('<I', self.s.link.memory, 416)[0], 1)
        self.assertEqual(self.s.link.loads, 2)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_partial_live_failure_closes_owned_emulator_without_conventional_fallback(self):
        record = self.s.build_copy()
        self.s.link.on_write = lambda link: struct.pack_into('<I', link.memory, 416, 2)
        with patch.object(kit_match, 'machine_copy', side_effect=AssertionError('unsafe fallback')), \
                self.assertRaises(ValueError):
            self.s.pine_load(record)
        self.assertEqual(self.s.emulator.stopped, 1)

    def test_wrong_epoch_or_target_hash_cannot_be_applied(self):
        record = self.s.build_copy()
        record['epoch'] += 1
        with self.assertRaises(ValueError):
            self.s.pine_load(record)
        self.assertEqual(self.s.link.loads, 0)
        record['epoch'] -= 1
        self.target.write_bytes(b'corrupted archive')
        with self.assertRaises(ValueError):
            self.s.pine_load(record)
        self.assertEqual(self.s.link.loads, 0)

    def test_stale_callback_does_not_start_new_owner_or_epoch(self):
        record = self.s.build_copy()
        self.s.schedule_pine_load(record)
        then = self.s.jobs[0][3]
        self.s.epoch += 1
        then(0.1)
        self.s.epoch -= 1
        self.s.match = copy.deepcopy(self.s.match)
        then(0.1)
        self.assertFalse(self.s.started)

    def test_foreign_pine_owner_is_not_mutated_or_killed(self):
        record = self.s.build_copy()
        self.s.emulator.owner = 777
        with self.assertRaises(ValueError):
            self.s.pine_load(record)
        self.assertEqual(self.s.link.loads, 0)
        self.assertFalse(self.s.link.writes)
        self.assertEqual(self.s.emulator.stopped, 0)

    def test_stale_launch_closes_only_captured_link_and_original_owned_process(self):
        request = self.s.load_request()
        result = dict(pid=99, link=self.s.link, process_token=('process', 'original'))
        self.s.epoch += 1
        with patch.object(self.s, '_load_process_token', return_value=('process', 'original')):
            self.s.launch_completed(result, request)
        self.assertEqual(result['link'].closed, 1)
        self.assertEqual(self.s.emulator.stopped, 1)
        self.assertFalse(self.s.started)

    def test_stale_launch_does_not_stop_new_instance_pid_or_process_identity(self):
        for changed in ('instance', 'pid', 'listener', 'identity', 'unreadable'):
            with self.subTest(changed=changed):
                s = Session(self.source, self.target, self.memory)
                request = s.load_request()
                em, captured_link = s.emulator, s.link
                result = dict(pid=99, link=captured_link, process_token=('process', 'original'))
                s.epoch += 1
                s.link = Link(self.memory, self.target)
                token = ('process', 'original')
                if changed == 'instance':
                    s.emulator = Emulator(self.target, s.link)
                elif changed == 'pid':
                    em.pid = 100
                elif changed == 'listener':
                    em.owner = 100
                elif changed == 'identity':
                    token = ('process', 'replacement')
                elif changed == 'unreadable':
                    token = None
                with patch.object(s, '_load_process_token', return_value=token):
                    s.launch_completed(result, request)
                self.assertEqual(em.stopped, 0)
                self.assertEqual(captured_link.closed, 1)
                self.assertEqual(s.link.closed, 0)

    def test_current_launch_callback_preserves_owned_link(self):
        request = self.s.load_request()
        result = dict(pid=99, link=self.s.link, process_token=('process', 'original'))
        with patch.object(self.s, 'game_launched') as completed:
            self.s.launch_completed(result, request)
        completed.assert_called_once_with(result)
        self.assertEqual(self.s.link.closed, 0)
        self.assertEqual(self.s.emulator.stopped, 0)



    def decoded_proof(self):
        import kit_wire_codec
        data = self.source.read_bytes()
        return kit_state.decoded_memory(self.source, kit_wire_codec.DecodedState(data, bytes(self.memory),
            hashlib.sha256(data).hexdigest(), kit_wire_codec._DECODE_TOKEN))

    def test_decoded_snapshot_plan_matches_conventional_and_retains_live_guards(self):
        conventional = self.plan()
        proof = self.decoded_proof()
        with patch.object(kit_state, 'StateArchive', side_effect=AssertionError('redundant decode')):
            fast = kit_match.paused_machine_copy(self.source, self.target, 0, 0, self.s.profile['local'], 2,
                state_sha=kit_state.sha256(self.source), delay=3, mask=3, snapshot=proof)
        self.assertEqual(fast, conventional)
        self.s.link.vm_status = 'running'
        with self.assertRaisesRegex(ValueError, 'paused'):
            kit_match.apply_paused_machine(self.s.link, fast)
        self.assertFalse(self.s.link.writes)

    def test_snapshot_has_no_authority_to_skip_core_frame_or_target_hash_checks(self):
        proof = self.decoded_proof()
        struct.pack_into('<I', self.memory, self.base + nc.F['frame'], 1)
        self.write_source()
        current = self.decoded_proof()
        with self.assertRaises(ValueError):
            kit_match.paused_machine_copy(self.source, self.target, 0, 0, self.s.profile['local'], 2,
                state_sha=kit_state.sha256(self.source), delay=3, mask=3, snapshot=current)
        self.assertFalse(self.target.exists())
        with self.assertRaises(ValueError):
            kit_match.paused_machine_copy(self.source, self.target, 0, 0, self.s.profile['local'], 2,
                state_sha=kit_state.sha256(self.source), delay=3, mask=3, snapshot=proof)

    def test_stale_load_snapshot_cannot_start_or_mutate_a_new_owner(self):
        import kit_wire
        self.s.match['size'] = self.source.stat().st_size
        manager = kit_wire.Manager.__new__(kit_wire.Manager)
        manager.lock = threading.RLock()
        manager.decoded_memory = self.decoded_proof()
        self.s.local['wire'] = manager
        request = self.s.load_request()
        self.assertIs(request['snapshot'], manager.decoded_memory)
        self.s.match = dict(self.s.match, epoch=8)
        with self.assertRaisesRegex(ValueError, 'superseded'):
            self.s.build_copy(request)
        self.assertFalse(self.s.link.writes)
        self.assertFalse(self.target.exists())

    def test_finished_machine_plan_does_not_retain_full_decoded_ram_in_retry_record(self):
        import kit_wire
        self.s.match['size'] = self.source.stat().st_size
        manager = kit_wire.Manager.__new__(kit_wire.Manager)
        manager.lock = threading.RLock()
        manager.decoded_memory = self.decoded_proof()
        self.s.local['wire'] = manager
        request = self.s.load_request()
        record = self.s.build_copy(request)
        self.assertIs(request['snapshot'], manager.decoded_memory)
        self.assertIsNone(record['request']['snapshot'])
        self.assertEqual(record['plan']['sha'], self.s.match['sha'])
        kit_match.apply_paused_machine(self.s.link, record['plan'])


if __name__ == '__main__':
    unittest.main()
