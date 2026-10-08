"""Negotiated transport controls preserve arena identity and guarded state bytes."""
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_fight
import kit_match
import kit_prefetch
import kit_prebuild
import kit_prepare
import kit_prepare_auto
import kit_state


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'base.p2s'
        self.states = self.root / 'states'
        self.memory = bytearray(512)
        self.guards = {16: 0x4e504331, 20: 4, 24: 2}
        for address, value in self.guards.items():
            struct.pack_into('<I', self.memory, address, value)
        struct.pack_into('<II', self.memory, 32, 5, 9000)
        struct.pack_into('<II', self.memory, 64, 1, 5)
        for target, name, value in [(kit_state, 'EE_SIZE', 512), (kit_match, 'QUEUE_CONTROL', 64)]:
            p = patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in [('control_words', (32, 36)), ('_control_guard_words', self.guards)]:
            p = patch.object(kit_match, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.write()

    def write(self):
        with zipfile.ZipFile(self.base, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.comment = b'native archive comment'
            z.writestr('regs.bin', b'native register bytes')
            z.writestr(kit_state.MEMORY, self.memory)
        self.recorded = dict(delay=5, max_stall=9000, sha256=kit_state.sha256(self.base))

    def build(self, delay=5, stall=9000, recorded=None):
        return kit_match.netplay_state(self.base, delay, stall, self.states, lambda _: None,
                                       base_controls=self.recorded if recorded is None else recorded)

    def test_final_negotiated_archive_never_invokes_recompression(self):
        with patch.object(kit_state, 'patch_words', side_effect=AssertionError('unexpected rewrite')):
            meta = self.build()
        self.assertEqual(meta['state_sha256'], self.recorded['sha256'])
        self.assertEqual(Path(meta['state']).read_bytes(), self.base.read_bytes())
        self.assertEqual(meta['base_controls'], dict(delay=5, max_stall=9000))

    def test_changed_rtt_retimes_existing_arena_with_actual_old_word_guards(self):
        with patch.object(kit_state, 'patch_words', wraps=kit_state.patch_words) as writer:
            result = self.build(3, 18000)
        self.assertEqual(writer.call_args.args[2], {32: (5, 3), 36: (9000, 18000)})
        expected = bytearray(self.memory)
        struct.pack_into('<II', expected, 32, 3, 18000)
        with zipfile.ZipFile(result['state']) as z:
            self.assertEqual(z.read(kit_state.MEMORY), expected)
            self.assertEqual(z.read('regs.bin'), b'native register bytes')
            self.assertEqual(z.comment, b'native archive comment')

    def test_old_cache_retains_delay_one_guards(self):
        struct.pack_into('<II', self.memory, 32, 1, 18000)
        self.write()
        result = kit_match.netplay_state(self.base, 4, states=self.states, say=lambda _: None)
        self.assertEqual(kit_state.read_words(result['state'], [32, 36]), {32: 4, 36: 18000})

    def test_legacy_metadata_cannot_silently_accept_other_base_controls(self):
        with self.assertRaises(kit_match.KitError):
            kit_match.netplay_state(self.base, 5, states=self.states, say=lambda _: None)
        self.assertFalse(list(self.states.glob('*.json')))

    def test_control_record_requires_exact_full_archive_hash(self):
        for value in [dict(delay=5, max_stall=9000), dict(self.recorded, sha256='0' * 64)]:
            with self.subTest(value=value), self.assertRaises(kit_match.KitError):
                self.build(recorded=value)
        self.assertFalse(list(self.states.glob('*.p2s')))

    def test_control_record_is_not_authority_for_wrong_archive_values(self):
        with self.assertRaises(kit_match.KitError):
            self.build(recorded=dict(self.recorded, delay=4))

    def test_bad_core_identity_or_pending_queue_is_rejected(self):
        original = bytes(self.memory)
        for address, wrong in [(16, 0), (20, 3), (24, 1), (68, 4)]:
            with self.subTest(address=address):
                self.memory[:] = original
                struct.pack_into('<I', self.memory, address, wrong)
                self.write()
                with self.assertRaises(kit_match.KitError):
                    self.build()

    def test_bool_fraction_and_out_of_range_controls_fail_before_io(self):
        for delay, stall in [(True, 9000), (5, False), (1.0, 9000), (5, 9000.0),
                             (0, 9000), (31, 9000), (5, 59), (5, 216001)]:
            with self.subTest(delay=delay, stall=stall), self.assertRaises(kit_match.KitError):
                kit_match.netplay_state(self.root / 'missing', delay, stall)

    def test_wrong_cache_receipt_controls_rebuilds_instead_of_reusing(self):
        meta = self.build()
        receipt = Path(meta['state']).with_suffix('.json')
        receipt.write_text(json.dumps(dict(meta, delay=4)), encoding='utf-8')
        result = self.build()
        self.assertEqual(result['delay'], 5)
        self.assertEqual(json.loads(receipt.read_text())['delay'], 5)

    def test_wrong_expected_tuple_rejected_even_with_valid_output_cache(self):
        self.build()
        with self.assertRaises(kit_match.KitError):
            self.build(recorded=dict(self.recorded, delay=4))

    def test_copy_cannot_publish_changed_source_with_old_base_hash(self):
        original_copy = kit_match.shutil.copyfile
        def changing(source, target):
            self.memory[300] ^= 1
            self.write()
            return original_copy(source, target)
        with patch.object(kit_match.shutil, 'copyfile', side_effect=changing), self.assertRaises(kit_match.KitError):
            self.build()
        self.assertFalse(list(self.states.glob('*.json')))

    def test_transport_snapshot_is_copied_and_legacy_metadata_has_no_declared_controls(self):
        value = dict(delay=5, max_stall=9000)
        snapshot = kit_match.transport_controls(value)
        value['delay'] = 7
        self.assertEqual(snapshot['delay'], 5)
        self.assertIsNone(kit_match.prepared_controls(dict(netplay_sha256='1' * 64)))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controls = dict(delay=5, max_stall=9000)

    def test_in_process_converter_receives_separate_validated_controls(self):
        with patch.object(kit_prepare, 'have_packages', return_value=True), \
                patch.object(kit_prepare, '_convert', return_value={'verify_sha': 'x'}) as convert:
            kit_prepare.convert('capture', self.root, 'names', spec={'stage': 0}, options={'test_ki': True},
                                controls=self.controls)
        self.assertEqual(convert.call_args.kwargs['controls'], self.controls)
        self.assertEqual(convert.call_args.args[4], {'test_ki': True})

    def test_subprocess_converter_preserves_controls_outside_test_options(self):
        python = self.root / 'python.exe'
        python.write_bytes(b'fixture')
        with patch.object(kit_prepare, 'have_packages', return_value=False), \
                patch.object(kit_prepare.subprocess, 'run', return_value=SimpleNamespace(
                    stdout='{"verify_sha":"ok"}', stderr='', returncode=0)) as run:
            kit_prepare.convert('capture', self.root, 'names', python=python, controls=self.controls)
        command = run.call_args.args[0]
        self.assertEqual(len(command), 10)
        self.assertEqual(command[:3], [str(python), str(Path(kit_prepare.__file__)), 'convert'])
        self.assertEqual(json.loads(Path(command[-2]).read_text()), self.controls)
        self.assertEqual(command[-3], '-')  # no test options
        self.assertEqual(command[-1], '-')  # no held-export receipt

    def test_state_worker_uses_start_snapshot_even_if_host_configuration_changes(self):
        owner = dict(delay=5, max_stall=9000, spec={'stage': 0}, spec_sha='1' * 64,
                     base_controls=dict(self.controls, sha256='2' * 64))
        session = SimpleNamespace(args=SimpleNamespace(max_stall=18000), states=self.root, say=lambda _: None)
        with patch.object(kit_match, 'netplay_state', return_value={'state': 'verified'}) as state, \
                patch.object(kit_fight.kit_verify, 'file_words', return_value={}), \
                patch.object(kit_fight.kit_verify, 'problems', return_value=[]), \
                patch.object(kit_fight.kit_verify, 'sha', return_value='verified'), \
                patch.object(kit_fight.netplay_fixups, 'fixed_sha256', return_value='fixed'):
            kit_fight.FightMixin.state_job(session, 'base', owner)
        self.assertEqual(state.call_args.args[1:3], (5, 9000))
        self.assertEqual(state.call_args.kwargs['base_controls'], owner['base_controls'])

    def test_prefetch_job_captures_stall_limit_before_worker_starts(self):
        session = SimpleNamespace(role='host', phase='lobby', args=SimpleNamespace(max_stall=9000),
                                  busy=lambda _: False, match_delay=lambda: 5, jobs=[])
        session.prefetch_state_job = lambda *a: None
        session.prefetch_state_ready = lambda *a: None
        session.say = lambda _: None
        session.job = lambda *a, **k: session.jobs.append((a, k))
        self.assertTrue(kit_prefetch.PrefetchMixin.publish_prebuild(session, {'file': 'base'}))
        session.args.max_stall = 18000
        self.assertEqual(session.jobs[0][0][3:], (5, 9000))

    def test_preparation_copy_forwards_controls_without_changing_test_options(self):
        import threading
        session = SimpleNamespace(lock=threading.RLock())
        with patch.object(kit_prepare_auto.PrepCopy, '_prepare', return_value={'ok': True}) as prepare:
            session._prepare = prepare
            result = kit_prepare_auto.PrepCopy.prepare(session, {'stage': 0}, self.root,
                options={'test_ki': True}, controls=self.controls)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(prepare.call_args.kwargs['controls'], self.controls)
        self.assertEqual(prepare.call_args.args[-1], {'test_ki': True})

    def test_changed_transport_latency_does_not_restart_settled_arena_build(self):
        import test_prebuild
        h = test_prebuild.Host()
        h.args.max_stall = 9000
        h.match_delay = lambda: 5
        with patch.object(kit_prebuild.kit_spec, 'validate'), \
                patch.object(kit_prebuild.kit_spec, 'title', return_value='fixture'), \
                patch.object(kit_match, 'made_match', return_value=None), \
                patch.object(kit_match, 'made_folder', return_value=self.root):
            h.tick_prebuild(0)
            h.tick_prebuild(1.5)
            owner = h.prebuild
            h.match_delay = lambda: 9
            h.args.max_stall = 18000
            h.tick_prebuild(2)
            self.assertIs(h.prebuild, owner)
            h.finish()
            h.tick_prebuild(3)
        self.assertEqual(len(h.builds), 1)
        self.assertFalse(h.started)
        self.assertFalse(h.lobby.ready)

    def test_stale_prepare_generation_does_not_use_negotiated_controls_or_touch_arena(self):
        import threading
        prep = SimpleNamespace(lock=threading.RLock(), cancel=threading.Event())
        session = SimpleNamespace(prep_gen=2, _prepare_locked=lambda *a, **k: self.fail('stale build ran'))
        with self.assertRaises(kit_prepare_auto.Cancelled):
            kit_fight.FightMixin.prepare_job(session, prep, 1, {}, self.root, None, 'fixture', self.controls)


if __name__ == '__main__':
    unittest.main()
