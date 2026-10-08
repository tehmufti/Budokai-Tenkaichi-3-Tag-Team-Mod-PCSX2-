"""Fresh writer provenance avoids redundant work without changing a wire byte."""
import copy
import dataclasses
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'bt3-multifighter/online/netplay'), str(ROOT), str(Path(__file__).resolve().parent)]
import kit_paths
import kit_fight
import kit_match
import kit_wire
import kit_wire_codec as codec
import kit_verify
from test_wire_optional_thumbnail import FakeIso


def producer_report(path, words=None):
    words = {'synthetic': ['fully verified', 3]} if words is None else words
    sha = kit_wire.sha(path)
    return dict(words=words, verify_sha=kit_verify.sha(words), netplay_sha256=sha,
        netplay=dict(sha256=sha, controls=dict(delay=1, max_stall=18000),
            archive_proof=dict(schema=1, writer='python-zipfile-deflate-1', zlib=zlib.ZLIB_RUNTIME_VERSION,
                               sha256=sha, size=Path(path).stat().st_size)))


class FreshProven(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root, self.iso = Path(directory.name), FakeIso()
        self.path = self.root / 'fresh.p2s'
        for item in (
            # These tests prove archive provenance/validation dispatch, not native guest code.
            patch.object(kit_fight.netplay_fixups, 'fixed_sha256', return_value='0' * 64),
            patch.object(codec, 'EE_SIZE', 2 << 20),
            patch.object(codec, 'detect_references', side_effect=lambda ram, iso: [
                dict(file_id=7, destination=0x100000, length=len(iso.raw), file_sha256=codec.digest(iso.raw))]),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.raw = self.archive()
        self.path.write_bytes(self.raw)
        self.report = producer_report(self.path)
        self.proof = kit_wire.fresh_preparation_proof(self.path, self.report)

    def archive(self, duplicate=None):
        buffer = io.BytesIO()
        ram = bytearray(codec.EE_SIZE)
        ram[0x100000:0x100000 + len(self.iso.raw)] = self.iso.raw
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for name in sorted(codec.REQUIRED_ENTRIES):
                archive.writestr(name, ram if name == 'eeMemory.bin' else b'native', compresslevel=1)
            if duplicate:
                archive.writestr(duplicate, b'duplicate', compresslevel=1)
        return buffer.getvalue()

    def test_fresh_wire_is_identical_and_decoder_still_reconstructs_exact_archive(self):
        old = codec.encode_state(self.path, self.iso)
        with patch.object(codec, 'deflate', side_effect=AssertionError('redundant sender Deflate')):
            fresh = codec.encode_state(self.path, self.iso, fresh_proof=self.proof)
        self.assertEqual(fresh.wire, old.wire)
        self.assertEqual(codec.decode_state(fresh.wire, self.iso, old.archive_sha256), self.raw)

    def test_unknown_and_disk_shaped_proofs_keep_existing_reproducibility_checks(self):
        for proof in (None, self.report['netplay']['archive_proof'], dataclasses.asdict(self.proof)):
            with self.subTest(proof=type(proof).__name__), patch.object(codec, 'deflate', wraps=codec.deflate) as echo:
                codec.encode_state(self.path, self.iso, fresh_proof=proof)
                self.assertEqual(echo.call_count, len(codec.REQUIRED_ENTRIES))

    def test_wrong_sha_size_or_zlib_proof_never_skips_deflate(self):
        for change in ('sha', 'size', 'zlib'):
            proof = copy.copy(self.proof)
            key, value = {'sha': ('archive_sha256', 'f' * 64), 'size': ('archive_size', 1),
                          'zlib': ('zlib_version', 'another-runtime')}[change]
            object.__setattr__(proof, key, value)
            with self.subTest(change=change), patch.object(codec, 'deflate', wraps=codec.deflate) as echo:
                codec.encode_state(self.path, self.iso, fresh_proof=proof)
                self.assertGreater(echo.call_count, 0)

    def test_factory_rejects_changed_file_words_writer_or_runtime(self):
        for change in ('file', 'words', 'writer', 'runtime', 'sha', 'bool_schema'):
            report = copy.deepcopy(self.report)
            if change == 'file':
                self.path.write_bytes(self.raw + b'changed')
            elif change == 'words':
                report['words']['synthetic'].append('changed')
            elif change == 'writer':
                report['netplay']['archive_proof']['writer'] = 'level-6-unknown'
            elif change == 'runtime':
                report['netplay']['archive_proof']['zlib'] = 'other-zlib'
            elif change == 'sha':
                report['netplay_sha256'] = 'a' * 64
            else:
                report['netplay']['archive_proof']['schema'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                kit_wire.fresh_preparation_proof(self.path, report)
            self.path.write_bytes(self.raw)

    def test_crc_failure_is_not_hidden_by_valid_fresh_provenance_type(self):
        bad = bytearray(self.raw)
        entry = codec.zip_layout(bad)[0]
        bad[entry['zip_offset']] ^= 0x40
        self.path.write_bytes(bad)
        proof = kit_wire.fresh_preparation_proof(self.path, producer_report(self.path))
        with self.assertRaises(codec.WireRejected):
            codec.encode_state(self.path, self.iso, fresh_proof=proof)

    def test_words_are_immutable_copies_and_proof_cannot_be_serialized_or_forged(self):
        self.report['words']['synthetic'].append('new caller mutation')
        words = self.proof.words()
        words['synthetic'].append('mutated')
        self.assertEqual(self.proof.words(), {'synthetic': ['fully verified', 3]})
        with self.assertRaises(TypeError):
            json.dumps(self.proof)
        with self.assertRaises(ValueError):
            kit_wire.FreshArchiveProof(self.proof.archive_sha256, len(self.raw), {}, None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.proof.archive_size = 1

    def test_bounded_process_local_registry_never_accepts_wire_or_disk_objects(self):
        manager = kit_wire.Manager.__new__(kit_wire.Manager)
        manager.lock, manager.fresh_proofs = threading.RLock(), {}
        self.assertFalse(manager.register_fresh(self.report))
        for index in range(12):
            self.path.write_bytes(self.raw + bytes([index]))
            proof = kit_wire.fresh_preparation_proof(self.path, producer_report(self.path))
            self.assertTrue(manager.register_fresh(proof))
        self.assertEqual(len(manager.fresh_proofs), 8)

    def test_state_job_reuses_words_only_for_exact_proved_final_archive(self):
        session = SimpleNamespace(args=SimpleNamespace(max_stall=18000), states=self.root, say=lambda _: None)
        owner = dict(delay=1, max_stall=18000, base_controls=None, spec={}, spec_sha='s')
        meta = dict(state=str(self.path), state_sha256=self.proof.archive_sha256, size=len(self.raw))
        with patch.object(kit_match, 'netplay_state', return_value=meta), \
                patch.object(kit_verify, 'problems', return_value=[]) as problems, \
                patch.object(kit_verify, 'file_words', side_effect=AssertionError('duplicate 128 MiB inflate')):
            output = kit_fight.FightMixin.state_job(session, self.path, owner, self.proof)
        self.assertEqual(output['verify_sha'], self.report['verify_sha'])
        problems.assert_called_once_with(self.proof.words(), owner['spec'], '0' * 64)

    def test_retimed_unknown_or_disk_proof_uses_normal_validation(self):
        session = SimpleNamespace(args=SimpleNamespace(max_stall=18000), states=self.root, say=lambda _: None)
        owner = dict(delay=1, max_stall=18000, base_controls=None, spec={}, spec_sha='s')
        for proof, sha in ((self.proof, 'f' * 64), (None, self.proof.archive_sha256),
                           (self.report, self.proof.archive_sha256)):
            meta = dict(state=str(self.path), state_sha256=sha, size=len(self.raw))
            with self.subTest(proof=type(proof).__name__), \
                    patch.object(kit_match, 'netplay_state', return_value=meta), \
                    patch.object(kit_verify, 'problems', return_value=[]), \
                    patch.object(kit_verify, 'file_words', return_value={}) as disk:
                kit_fight.FightMixin.state_job(session, self.path, owner, proof)
                disk.assert_called_once_with(str(self.path))

    def test_stale_match_owner_discards_state_result_even_with_proof(self):
        owner = dict(spec_sha='s')
        session = SimpleNamespace(match=owner, states=self.root, say=lambda _: None, jobs=[],
            set_phase=lambda _: None, offer_match=Mock(), state_failed=Mock(), state_job=Mock())
        session.job = lambda *a, **kw: session.jobs.append((a, kw))
        meta = dict(file=str(self.path), netplay_sha256=self.proof.archive_sha256,
                    controls=dict(delay=1, max_stall=18000), _fresh_proof=self.proof)
        kit_fight.FightMixin.match_made(session, meta)
        session.match = dict(spec_sha='another')
        session.jobs[0][1]['then']({'wire': 'finished immutable state'})
        session.offer_match.assert_not_called()

    def test_fresh_proof_is_attached_only_after_disk_metadata_is_written(self):
        folder = self.root / 'prepared'
        report = dict(self.report, pnach='guarded-hooks', family='bt3-usa')
        def prepare(*args, **kwargs):
            folder.mkdir()
            (folder / 'netplay.p2s').write_bytes(self.raw)
            return report
        prep = SimpleNamespace(prepare=Mock(side_effect=prepare), install={})
        session = SimpleNamespace(host_language=lambda: 'en', on_prep_progress=Mock(), say=Mock())
        with patch.object(kit_match, 'made_match', return_value=None), \
                patch.object(kit_match, 'prune_made'), patch.object(kit_fight.kit_spec, 'spec_sha', return_value='s'):
            made = kit_fight.FightMixin._prepare_locked(session, prep, {}, folder, None, 'Fresh match')
        self.assertIs(type(made['_fresh_proof']), kit_wire.FreshArchiveProof)
        disk = json.loads((folder / 'match.json').read_text())
        self.assertNotIn('_fresh_proof', disk)
        self.assertNotIn('archive_proof', disk)

    def test_cached_disk_metadata_cannot_call_fresh_proof_factory(self):
        cached = dict(file='existing.p2s', archive_proof=self.report['netplay']['archive_proof'])
        session = SimpleNamespace(on_prep_progress=Mock())
        with patch.object(kit_match, 'made_match', return_value=cached), \
                patch.object(kit_fight.kit_spec, 'spec_sha', return_value='s'), \
                patch.object(kit_wire, 'fresh_preparation_proof', side_effect=AssertionError('disk provenance')):
            output = kit_fight.FightMixin._prepare_locked(session, None, {}, self.root, None, 'Cached match')
        self.assertIs(output, cached)
        self.assertNotIn('_fresh_proof', output)


if __name__ == '__main__':
    unittest.main()
