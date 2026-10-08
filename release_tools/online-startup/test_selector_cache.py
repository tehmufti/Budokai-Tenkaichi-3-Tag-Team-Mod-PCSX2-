"""Portable production-helper guards; no emulator or game media is launched."""
import json
import hashlib
import hmac
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_paths
import kit_selector_cache as cache


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with cache._VALIDATION_LOCK:
            cache._VALIDATED_ARCHIVES.clear()
        self.prep = self.root / 'prep'
        self.store = cache.SelectorCache(self.prep / 'native-selector-cache')
        self.ident = dict(schema=1, iso='exactiso', bios='exactbios', code='exactcode')
        self.proof = dict(engine='teams', choice=0, native_code_sha256='exact')
        self.archive = dict(version_hex='exact', entries={'ee': 'exact'})
        self.dest = self.prep / 'Tag Team Mod'
        self.source = self.dest / 'game/runtime28/sstates/native.p2s'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'checkednativecheckpoint')
        self.hook_data = b'exact generated native loading hooks\n'
        self.hook_name = 'SLUS-21678_428113C2_BT3Loading.pnach'
        self.hook_target = self.dest / 'game/runtime28/cheats' / self.hook_name
        self.hook_target.parent.mkdir(parents=True)
        self.hook_target.write_bytes(self.hook_data)
        self.hook_receipt = self.hook_target.with_suffix('.owned-sha256')
        self.hook_receipt.write_text(hashlib.sha256(self.hook_data).hexdigest() + '\n')
        self.hooks = SimpleNamespace(pnach=lambda: self.hook_data)
        self.menu = SimpleNamespace(CONTROL=0x1000, MAGIC=0x12345678, code_pieces=lambda: [],
                                    SELECTIONS=[('teams', 1), ('ffa', 1)])
        self.menu.old = SimpleNamespace(CODE=0x2000, CONTROL=0x3000, FIELDS={'frames': 24},
                                        code_pieces=lambda: [(0x2000, b'frame-code')])
        self.status = dict(state='MENU', battle_mode='teams', humans=1,
                           launcher_token='a' * 32, native_mode_receipt=dict(epoch=1, choice=0, custom=True))
        self.lease = SimpleNamespace(read=lambda copy: self.status.copy())
        self.copy = SimpleNamespace(lock=threading.RLock(),
            base=SimpleNamespace(dest=self.dest, desktop='private', pid=None),
            slot=29901, iso=self.root / 'disc.iso', check=lambda: None,
            at_map_select=lambda: True, pine=lambda **kwargs: None)
        self.patches = [patch.object(cache, 'archive_payload', return_value=(b'ram', self.archive)),
                        patch.object(cache, 'selector', return_value=self.proof),
                        patch.dict(sys.modules, {'native_mode_menu': self.menu,
                            'guest_loading_screen': self.hooks,
                            'game_profile': SimpleNamespace(cheat_name=lambda serial: self.hook_name),
                            'native_map': SimpleNamespace(SERIAL='SLUS-21678', CRC='428113c2')}),
                        patch.object(kit_paths, 'PREP', self.prep)]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        class Pine:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        self.copy.pine = lambda **kwargs: Pine()

    def publish(self):
        return self.store.publish(self.source, 'teams', self.ident, self.lease, self.copy)

    def hook_boot(self):
        self.publish()
        return self.store.stage_boot(self.copy, 'teams', self.ident)

    def resign_boot(self, descriptor, change):
        change(descriptor['claim'])
        descriptor['mac'] = hmac.new(self.store.key, cache.canonical(descriptor['claim']), hashlib.sha256).hexdigest()
        return descriptor

    def hook_cache_path(self, descriptor):
        hook = descriptor['claim']['record']['boot_hooks']
        return self.store.paths('teams', self.ident)[0].parent / ('boot-hooks-' + hook['sha256'] + '.pnach')

    def test_generated_hook_publish_and_atomic_install_bind_exact_recipe_bytes(self):
        descriptor = self.hook_boot()
        hook = descriptor['claim']['record']['boot_hooks']
        self.assertEqual(hook, dict(schema=1, filename=self.hook_name, size=len(self.hook_data),
                                    sha256=hashlib.sha256(self.hook_data).hexdigest()))
        self.assertEqual(self.hook_cache_path(descriptor).read_bytes(), self.hook_data)
        self.hook_target.unlink(); self.hook_receipt.unlink()
        receipt = cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual(receipt, dict(sha256=hook['sha256'], bytes=len(self.hook_data)))
        self.assertEqual(self.hook_target.read_bytes(), self.hook_data)
        self.assertEqual(self.hook_receipt.read_text(), hook['sha256'] + '\n')
        self.assertEqual(list(self.hook_target.parent.glob('.ttm-selector-*')), [])

    def test_hook_publish_does_not_sign_modified_installed_bytes_or_replace_valid_record(self):
        self.publish()
        paths = self.store.paths('teams', self.ident)
        old = [path.read_bytes() for path in paths]
        self.hook_target.write_bytes(b'changed generated native hooks')
        with self.assertRaisesRegex(ValueError, 'size differs|checksum differs'):
            self.publish()
        self.assertEqual([path.read_bytes() for path in paths], old)

    def test_changed_hook_source_recipe_rejects_old_generated_installation(self):
        self.hooks.pnach = lambda: b'a new native recipe'
        with self.assertRaisesRegex(ValueError, 'size differs|checksum differs'):
            self.publish()
        self.assertFalse(self.store.paths('teams', self.ident)[1].exists())

    def test_corrupt_hook_with_preserved_stat_is_rejected_before_private_writes(self):
        descriptor = self.hook_boot()
        path = self.hook_cache_path(descriptor); stamp = path.stat()
        path.write_bytes(b'x' * stamp.st_size)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        before = (self.hook_target.read_bytes(), self.hook_receipt.read_bytes())
        with self.assertRaisesRegex(ValueError, 'checksum differs'):
            cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual((self.hook_target.read_bytes(), self.hook_receipt.read_bytes()), before)

    def test_missing_hook_cache_is_rejected_without_changing_native_files(self):
        descriptor = self.hook_boot(); self.hook_cache_path(descriptor).unlink()
        before = (self.hook_target.read_bytes(), self.hook_receipt.read_bytes())
        with self.assertRaises(OSError): cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual((self.hook_target.read_bytes(), self.hook_receipt.read_bytes()), before)

    def test_legacy_signed_selector_requests_full_native_generation(self):
        descriptor = self.hook_boot()
        self.resign_boot(descriptor, lambda claim: claim['record'].pop('boot_hooks'))
        self.assertFalse(cache.install_boot_hooks(descriptor, self.dest, self.ident))

    def test_hook_identity_hmac_or_signed_state_tamper_cannot_install(self):
        descriptor = self.hook_boot(); before = self.hook_target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'identity'):
            cache.install_boot_hooks(descriptor, self.dest, dict(self.ident, code='another code'))
        descriptor['claim']['record']['boot_hooks']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'authentication'):
            cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual(self.hook_target.read_bytes(), before)

    def test_signed_hook_filename_bounds_and_hash_are_still_guarded(self):
        for values in ({'filename': '../outside.pnach'}, {'size': cache.MAX_BOOT_HOOKS + 1},
                       {'size': True}, {'sha256': '../outside'}, {'schema': 2}):
            with self.subTest(values=values):
                descriptor = self.hook_boot()
                self.resign_boot(descriptor, lambda claim: claim['record']['boot_hooks'].update(values))
                before = (self.hook_target.read_bytes(), self.hook_receipt.read_bytes())
                with self.assertRaises((OSError, ValueError)):
                    cache.install_boot_hooks(descriptor, self.dest, self.ident)
                self.assertEqual((self.hook_target.read_bytes(), self.hook_receipt.read_bytes()), before)

    def test_unrelated_occupied_private_hook_is_not_replaced_even_with_cached_payload(self):
        descriptor = self.hook_boot(); self.hook_target.write_bytes(b'unrelated user content')
        before = (self.hook_target.read_bytes(), self.hook_receipt.read_bytes())
        with self.assertRaisesRegex(cache.OccupiedBootHooks, 'occupied'):
            cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual((self.hook_target.read_bytes(), self.hook_receipt.read_bytes()), before)

    def test_old_owned_hook_is_replaced_and_receipt_tracks_full_readback(self):
        descriptor = self.hook_boot(); old = b'old generated native hooks'
        self.hook_target.write_bytes(old); self.hook_receipt.write_text(hashlib.sha256(old).hexdigest())
        cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual(self.hook_target.read_bytes(), self.hook_data)
        self.assertEqual(self.hook_receipt.read_text().strip(), hashlib.sha256(self.hook_data).hexdigest())

    def test_atomic_new_hook_install_cannot_overwrite_a_destination_race(self):
        descriptor = self.hook_boot(); self.hook_target.unlink(); self.hook_receipt.unlink()
        link = cache.os.link
        def occupied(source, destination):
            Path(destination).write_bytes(b'race-created foreign content')
            return link(source, destination)
        with patch.object(cache.os, 'link', side_effect=occupied), self.assertRaises(cache.OccupiedBootHooks):
            cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual(self.hook_target.read_bytes(), b'race-created foreign content')
        self.assertFalse(self.hook_receipt.exists())

    def test_hook_readback_failure_does_not_publish_an_owned_receipt(self):
        descriptor = self.hook_boot(); self.hook_target.unlink(); self.hook_receipt.unlink()
        digest = cache.sha
        with patch.object(cache, 'sha', side_effect=lambda path, **kwargs:
                '0' * 64 if Path(path) == self.hook_target else digest(path, **kwargs)):
            with self.assertRaisesRegex(ValueError, 'readback'):
                cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertFalse(self.hook_receipt.exists())

    def test_hook_cache_path_escape_is_rejected_before_native_installation(self):
        descriptor = self.hook_boot(); source = self.hook_cache_path(descriptor)
        resolve = Path.resolve
        def escaped(path, *args, **kwargs):
            return self.root / 'outside.pnach' if path == source else resolve(path, *args, **kwargs)
        with patch.object(Path, 'resolve', escaped), self.assertRaisesRegex(ValueError, 'cache path escapes'):
            cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual(self.hook_target.read_bytes(), self.hook_data)

    def test_hook_destination_or_receipt_escape_cannot_touch_external_content(self):
        descriptor = self.hook_boot(); external = self.root / 'user.pnach'; external.write_bytes(b'user data')
        resolve = Path.resolve
        for escaped_path in (self.hook_target, self.hook_receipt):
            with self.subTest(path=escaped_path):
                def escaped(path, *args, **kwargs):
                    return external if path == escaped_path else resolve(path, *args, **kwargs)
                with patch.object(Path, 'resolve', escaped), self.assertRaisesRegex(ValueError, 'destination escapes'):
                    cache.install_boot_hooks(descriptor, self.dest, self.ident)
                self.assertEqual(external.read_bytes(), b'user data')

    def test_old_owned_hook_atomic_replacement_does_not_mutate_a_hardlinked_original(self):
        descriptor = self.hook_boot(); self.hook_target.unlink()
        original = self.root / 'original.pnach'; original.write_bytes(b'older owned native hooks')
        os.link(original, self.hook_target)
        self.hook_receipt.write_text(hashlib.sha256(original.read_bytes()).hexdigest())
        cache.install_boot_hooks(descriptor, self.dest, self.ident)
        self.assertEqual(original.read_bytes(), b'older owned native hooks')
        self.assertEqual(self.hook_target.read_bytes(), self.hook_data)

    def test_round_trip_checks_archive_crc_layout_and_live_code(self):
        self.publish()
        path, record = self.store.validate('teams', self.ident)
        self.assertEqual(record['state_sha256'], cache.sha(path))
        cache.archive_payload.assert_called_with(path)
        cache.selector.assert_called_with(b'ram', 'teams')

    def test_identity_scoping_keeps_two_builds_separate(self):
        self.publish()
        other = dict(self.ident, iso='otheriso')
        self.assertNotEqual(self.store.paths('teams', self.ident), self.store.paths('teams', other))
        self.assertFalse(self.store.available('teams', other))
        self.assertTrue(self.store.available('teams', self.ident))

    def test_metadata_relabel_cannot_bypass_hmac(self):
        self.publish()
        _, path = self.store.paths('teams', self.ident)
        value = json.loads(path.read_text())
        value['record']['selector']['engine'] = 'ffa'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'authentication'):
            self.store.validate('teams', self.ident)

    def test_corrupt_archive_refused_before_decompression(self):
        self.publish()
        path, _ = self.store.paths('teams', self.ident)
        path.write_bytes(b'corrupted')
        cache.archive_payload.reset_mock()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.store.validate('teams', self.ident)
        cache.archive_payload.assert_not_called()

    def test_repeated_validation_keeps_full_hash_and_hmac_without_reinflation(self):
        self.publish()
        self.store.validate('teams', self.ident)
        cache.archive_payload.reset_mock()
        with patch.object(cache, 'sha', wraps=cache.sha) as digest:
            self.store.validate('teams', self.ident)
            self.store.validate('teams', self.ident)
        self.assertEqual(digest.call_count, 2)
        cache.archive_payload.assert_not_called()
        _, metadata = self.store.paths('teams', self.ident)
        value = json.loads(metadata.read_text())
        value['mac'] = '0' * 64
        metadata.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'authentication'):
            self.store.validate('teams', self.ident)

    def test_archive_change_with_preserved_size_and_mtime_cannot_use_validation_memo(self):
        self.publish()
        path, _ = self.store.validate('teams', self.ident)
        stamp = path.stat()
        path.write_bytes(b'x' * stamp.st_size)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        cache.archive_payload.reset_mock()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.store.validate('teams', self.ident)
        cache.archive_payload.assert_not_called()

    def resign_record(self, change):
        _, metadata = self.store.paths('teams', self.ident)
        value = json.loads(metadata.read_text())
        change(value['record'])
        value['mac'] = hmac.new(self.store.key, cache.canonical(value['record']), hashlib.sha256).hexdigest()
        metadata.write_bytes(cache.canonical(value))

    def test_new_signed_record_requires_fresh_payload_proof(self):
        self.publish()
        self.store.validate('teams', self.ident)
        self.resign_record(lambda record: record['archive']['entries'].update(ee='changed'))
        cache.archive_payload.reset_mock()
        with self.assertRaisesRegex(ValueError, 'validation differs'):
            self.store.validate('teams', self.ident)
        self.assertEqual(cache.archive_payload.call_count, 1)

    def test_changed_native_code_recipe_cannot_use_old_archive_proof(self):
        self.publish()
        self.store.validate('teams', self.ident)
        self.menu.code_pieces = lambda: [(0x1000, b'changed native code')]
        cache.selector.side_effect = ValueError('native code changed')
        cache.archive_payload.reset_mock()
        with self.assertRaisesRegex(ValueError, 'native code changed'):
            self.store.validate('teams', self.ident)
        self.assertEqual(cache.archive_payload.call_count, 1)

    def test_validation_record_is_fresh_and_memo_is_bounded_without_ram(self):
        self.publish()
        with patch.object(cache, 'MAX_VALIDATED_ARCHIVES', 2):
            for created in range(3):
                self.resign_record(lambda record, value=created: record.update(created=value))
                _, record = self.store.validate('teams', self.ident)
                record['selector']['engine'] = 'caller mutation'
            _, fresh = self.store.validate('teams', self.ident)
            self.assertEqual(fresh['selector']['engine'], 'teams')
            with cache._VALIDATION_LOCK:
                self.assertEqual(len(cache._VALIDATED_ARCHIVES), 2)
                self.assertTrue(all(value is True for value in cache._VALIDATED_ARCHIVES.values()))

    def test_archive_change_during_first_decode_is_not_memoized(self):
        self.publish()
        path, _ = self.store.paths('teams', self.ident)
        def changing_archive(_):
            path.write_bytes(b'changed during decode')
            return b'ram', self.archive
        cache.archive_payload.side_effect = changing_archive
        with self.assertRaisesRegex(ValueError, 'changed during native validation'):
            self.store.validate('teams', self.ident)
        with cache._VALIDATION_LOCK:
            self.assertEqual(len(cache._VALIDATED_ARCHIVES), 0)

    def test_same_mode_fields_do_not_replace_genuine_structured_choice(self):
        self.status['native_mode_receipt']['epoch'] = 0
        with self.assertRaisesRegex(ValueError, 'genuine'):
            self.publish()
        self.status['native_mode_receipt'] = dict(epoch=1, choice=1, custom=True)
        with self.assertRaisesRegex(ValueError, 'genuine'):
            self.publish()

    def test_only_private_capture_can_be_published(self):
        self.source = self.root / 'user-state.p2s'
        self.source.write_bytes(b'userstate')
        with self.assertRaisesRegex(ValueError, 'locally captured private'):
            self.publish()

    def test_failed_capture_does_not_replace_valid_cached_template(self):
        self.publish()
        path, metadata = self.store.paths('teams', self.ident)
        previous = (path.read_bytes(), metadata.read_bytes())
        cache.selector.side_effect = ValueError('native code changed')
        with self.assertRaisesRegex(ValueError, 'native code changed'):
            self.publish()
        self.assertEqual(previous, (path.read_bytes(), metadata.read_bytes()))

    def test_concurrent_writers_publish_consistent_archive_and_metadata(self):
        errors = []
        def publish():
            try:
                self.publish()
            except Exception as error:
                errors.append(error)
        workers = [threading.Thread(target=publish) for _ in range(3)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(5)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.store.validate('teams', self.ident)
        self.assertEqual(list(path.name for path in self.store.paths('teams', self.ident)[0].parent.glob(
            '.ttm-selector-*')), [])

    def restore_fixture(self, *, stale=False, worker=False, leased=False, lost_owner=False):
        self.publish()
        events = []
        words = {self.menu.CONTROL: self.menu.MAGIC,
                 self.menu.CONTROL + 4: 2 if leased else 0,
                 self.menu.CONTROL + 12: 0, self.menu.CONTROL + 16: 0}
        if worker: self.status['state'] = 'PREPARING'
        class Pine:
            loaded = False
            probes = 0
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def info(self): return dict(status='running')
            def require_game(self, **kwargs): return dict(status=self.info()['status'], serial='SLUS-21678', crc='428113c2')
            def read_ranges(self, ranges): return []
            def read(self, at, size): return b'frame-code' if at == 0x2000 else bytes(size)
            def load_state(self, slot):
                self.loaded = True; events.append('queued-load')
            def read_u32(inner, at):
                if at == self.menu.old.CONTROL + self.menu.old.FIELDS['frames']:
                    return 101 if 'authorize' in events else 100
                if inner.loaded and at == self.menu.CONTROL + 12 and words[at] == 0xffffffff:
                    inner.probes += 1
                    if inner.probes == 2:
                        words[at] = 0; events.append('load-completed')
                return words[at]
            def write_u32(inner, at, value):
                words[at] = value
                if at == self.menu.CONTROL + 12 and value == 0xffffffff:
                    events.append('canary-set')
                if at == self.menu.CONTROL + 4 and value == 3:
                    events.append('authorize')
                    words[self.menu.CONTROL + 4] = words[self.menu.CONTROL + 12] = 0
                    if not stale:
                        self.status['native_mode_receipt'] = dict(epoch=2, choice=0, custom=True)
        client = Pine()
        self.copy.pine = lambda **kwargs: client
        self.copy.sleep = lambda seconds: __import__('time').sleep(min(seconds, .005))
        self.copy.engine, self.copy.state, self.copy.settings_written = 'ffa', 'cold', {'stale': True}
        def owner(copy):
            if lost_owner and 'queued-load' in events:
                raise ValueError('private instance changed')
            return 77
        return events, patch.object(cache, '_owner', side_effect=owner)

    def test_canary_proves_async_load_before_new_epoch_authorizes_warm(self):
        events, owner = self.restore_fixture()
        with owner:
            result = self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1)
        self.assertTrue(result['queued_load_canary'])
        self.assertLess(events.index('canary-set'), events.index('queued-load'))
        self.assertLess(events.index('load-completed'), events.index('authorize'))
        self.assertEqual(self.copy.state, 'warm')
        self.assertEqual(self.copy.engine, 'teams')
        self.assertIsNone(self.copy.settings_written)

    def test_stale_epoch_cannot_mark_warm_even_when_mode_and_pager_match(self):
        events, owner = self.restore_fixture(stale=True)
        with owner, self.assertRaisesRegex(ValueError, 'did not authorize'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=.04)
        self.assertIn('authorize', events)
        self.assertEqual(self.copy.state, 'cold')

    def test_active_preparation_worker_cannot_restore_even_known_archive(self):
        events, owner = self.restore_fixture(worker=True)
        with owner, self.assertRaisesRegex(ValueError, 'active preparation worker'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1)
        self.assertEqual(events, [])

    def test_leased_pager_cannot_be_overwritten(self):
        events, owner = self.restore_fixture(leased=True)
        with owner, self.assertRaisesRegex(ValueError, 'unleased'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1)
        self.assertEqual(events, [])

    def test_replaced_private_instance_cannot_receive_mode_commit(self):
        events, owner = self.restore_fixture(lost_owner=True)
        with owner, self.assertRaisesRegex(ValueError, 'private instance changed'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1)
        self.assertNotIn('authorize', events)

    def boot_fixture(self, **kwargs):
        events, owner = self.restore_fixture(**kwargs)
        descriptor = self.store.stage_boot(self.copy, 'teams', self.ident)
        self.lease.folder = self.dest / 'game/analysis/autopilot/current'
        self.lease.folder.mkdir(parents=True)
        request = dict(selector_boot=descriptor, identity=self.ident, token=self.status['launcher_token'],
                       slot=self.copy.slot, root=str(self.dest), iso=str(self.copy.iso))
        self.request = self.lease.folder / 'private-launch.json'
        self.request.write_text(json.dumps(request))
        return events, owner, descriptor

    def test_direct_boot_requires_fresh_ack_without_queueing_second_load(self):
        events, owner, descriptor = self.boot_fixture()
        path = Path(descriptor['claim']['state_path'])
        with owner:
            receipt = self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1, boot=descriptor)
        self.assertEqual(events, ['authorize'])
        self.assertFalse(receipt['queued_load_canary'])
        self.assertTrue(receipt['direct_state_boot'])
        self.assertEqual(receipt['native_mode_receipt']['epoch'], 2)
        self.assertEqual(self.copy.state, 'warm')
        self.assertFalse(path.exists())

    def test_direct_boot_does_not_inspect_partial_paused_startup_memory(self):
        events, owner, descriptor = self.boot_fixture()
        client = self.copy.pine()
        reads = [0]
        def initializing_info():
            reads[0] += 1
            return dict(status='paused' if reads[0] < 4 else 'running')
        client.info = initializing_info
        def live_proof(memory, engine):
            if isinstance(memory, cache.LiveMemory):
                self.assertGreaterEqual(reads[0], 4)
            return self.proof
        cache.selector.side_effect = live_proof
        with owner:
            receipt = self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1, boot=descriptor)
        self.assertEqual(events, ['authorize'])
        self.assertEqual(receipt['loaded_game']['status'], 'running')

    def test_direct_boot_never_authorizes_a_vm_that_remains_paused(self):
        events, owner, descriptor = self.boot_fixture()
        self.copy.pine().info = lambda: dict(status='paused')
        cache.selector.reset_mock()
        with owner, self.assertRaisesRegex(ValueError, 'did not finish its authenticated selector startup'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=.04, boot=descriptor)
        self.assertEqual(events, [])
        cache.selector.assert_not_called()
        self.assertEqual(self.copy.state, 'cold')

    def test_direct_boot_requires_native_guest_frame_progress_after_python_ack(self):
        events, owner, descriptor = self.boot_fixture()
        client = self.copy.pine()
        read = client.read_u32
        client.read_u32 = lambda at: 100 if at == self.menu.old.CONTROL + 24 else read(at)
        with owner, self.assertRaisesRegex(ValueError, 'did not authorize'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=.04, boot=descriptor)
        self.assertEqual(events, ['authorize'])
        self.assertEqual(self.copy.state, 'cold')

    def test_direct_boot_rejects_modified_counter_code_before_commit(self):
        events, owner, descriptor = self.boot_fixture()
        self.copy.pine().read = lambda at, size: bytes(size)
        with owner, self.assertRaisesRegex(ValueError, 'frame counter code differs'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1, boot=descriptor)
        self.assertEqual(events, [])

    def test_direct_boot_counter_wrap_still_proves_progress(self):
        events, owner, descriptor = self.boot_fixture()
        client = self.copy.pine()
        read = client.read_u32
        client.read_u32 = lambda at: (0 if 'authorize' in events else 0xffffffff) \
            if at == self.menu.old.CONTROL + 24 else read(at)
        with owner:
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1, boot=descriptor)
        self.assertEqual(self.copy.state, 'warm')

    def test_direct_boot_pause_after_ack_cannot_mark_warm(self):
        events, owner, descriptor = self.boot_fixture()
        self.copy.pine().info = lambda: dict(status='paused' if 'authorize' in events else 'running')
        with owner, self.assertRaisesRegex(ValueError, 'did not authorize'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=.04, boot=descriptor)
        self.assertEqual(events, ['authorize'])
        self.assertEqual(self.copy.state, 'cold')

    def test_direct_boot_refuses_stale_epoch_and_keeps_copy_cold(self):
        events, owner, descriptor = self.boot_fixture(stale=True)
        with owner, self.assertRaisesRegex(ValueError, 'did not authorize'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=.04, boot=descriptor)
        self.assertEqual(events, ['authorize'])
        self.assertEqual(self.copy.state, 'cold')

    def test_staged_archive_tampering_fails_before_native_writes(self):
        events, owner, descriptor = self.boot_fixture()
        Path(descriptor['claim']['state_path']).write_bytes(b'tampered')
        with owner, self.assertRaisesRegex(ValueError, 'checksum'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1, boot=descriptor)
        self.assertEqual(events, [])

    def test_boot_descriptor_relabel_cannot_bypass_local_authentication(self):
        _, _, descriptor = self.boot_fixture()
        descriptor['claim']['engine'] = 'ffa'
        with self.assertRaisesRegex(ValueError, 'authentication'):
            cache.validate_boot(descriptor, self.dest, self.ident)

    def test_different_live_launcher_token_cannot_authorize_boot(self):
        events, owner, descriptor = self.boot_fixture()
        value = json.loads(self.request.read_text()); value['token'] = 'b' * 32
        self.request.write_text(json.dumps(value))
        with owner, self.assertRaisesRegex(ValueError, 'Current owned launcher'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1, boot=descriptor)
        self.assertEqual(events, [])

    def test_startup_requires_exact_live_native_selector_and_code(self):
        events, owner, descriptor = self.boot_fixture()
        cache.selector.side_effect = lambda memory, engine: dict(self.proof, native_code_sha256='changed') \
            if isinstance(memory, cache.LiveMemory) else self.proof
        with owner, self.assertRaisesRegex(ValueError, 'Startup live selector differs'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1, boot=descriptor)
        self.assertEqual(events, [])

    def test_stage_boot_never_targets_active_or_user_emulator(self):
        self.publish()
        self.copy.base.pid = 77
        with self.assertRaisesRegex(ValueError, 'fresh isolated'):
            self.store.stage_boot(self.copy, 'teams', self.ident)
        self.copy.base.pid = None; self.copy.base.dest = self.root / 'user'
        with self.assertRaisesRegex(ValueError, 'fresh isolated'):
            self.store.stage_boot(self.copy, 'teams', self.ident)

    def test_signed_boot_path_still_cannot_escape_private_save_folder(self):
        import hashlib
        import hmac
        _, _, descriptor = self.boot_fixture()
        descriptor['claim']['state_path'] = str(self.root / 'user-state.p2s')
        descriptor['mac'] = hmac.new(self.store.key, cache.canonical(descriptor['claim']), hashlib.sha256).hexdigest()
        with self.assertRaisesRegex(ValueError, 'outside the private'):
            cache.validate_boot(descriptor, self.dest, self.ident)

    def test_checked_snapshot_reuse_keeps_full_sha_without_reinflating(self):
        _, _, descriptor = self.boot_fixture()
        cache.archive_payload.reset_mock()
        self.assertEqual(cache.validate_boot(descriptor, self.dest, self.ident, inflate=False),
                         Path(descriptor['claim']['state_path']))
        cache.archive_payload.assert_not_called()
        Path(descriptor['claim']['state_path']).write_bytes(b'corrupt snapshot')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            cache.validate_boot(descriptor, self.dest, self.ident, inflate=False)
        cache.archive_payload.assert_not_called()

    def test_boot_still_checks_original_cache_record_authentication(self):
        events, owner, descriptor = self.boot_fixture()
        _, metadata = self.store.paths('teams', self.ident)
        value = json.loads(metadata.read_text()); value['record']['selector']['choice'] = 1
        metadata.write_text(json.dumps(value))
        with owner, self.assertRaisesRegex(ValueError, 'authentication'):
            self.store.restore(self.copy, 'teams', self.ident, self.lease, timeout=1, boot=descriptor)
        self.assertEqual(events, [])


class IndependentGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def config(self, extra=''):
        path = self.root / 'PCSX2.ini'
        path.write_text('[UI]\nStartFullscreen=false\n[Folders]\nBios=bios\n'
                        '[EmuCore]\nPINESlot=28011\nEnablePINE=true\nEnableCheats=true\n'
                        '[EmuCore/CPU]\nExtraMemory=true\n[EmuCore/GS]\nRenderer=-1\n'
                        'upscale_multiplier=1\n[InputSources]\nSDL=false\nXInput=false\nDInput=false\n'
                        '[Pad1]\nType=DualShock2\nCross=Keyboard/Q\n' + extra)
        return path

    def test_machine_pine_ui_paths_and_bindings_do_not_invalidate_semantic_identity(self):
        path = self.config()
        before = cache.semantic_config(path)
        path.write_text(path.read_text().replace('28011', '29999').replace('Bios=bios', 'Bios=D:/other/bios').replace(
            'StartFullscreen=false', 'StartFullscreen=true').replace('Cross=Keyboard/Q', 'Cross=Keyboard/P'))
        self.assertEqual(before, cache.semantic_config(path))

    def test_memory_and_renderer_changes_remain_guarded(self):
        path = self.config()
        before = cache.semantic_config(path)
        path.write_text(path.read_text().replace('Renderer=-1', 'Renderer=12'))
        self.assertNotEqual(before, cache.semantic_config(path))
        path.write_text(path.read_text().replace('ExtraMemory=true', 'ExtraMemory=false'))
        with self.assertRaisesRegex(ValueError, 'expanded'):
            cache.semantic_config(path)

    def test_fifo_presentation_keys_participate_in_exact_selector_identity(self):
        for key in ('VsyncEnable', 'DisableMailboxPresentation'):
            with self.subTest(key=key):
                path = self.config()
                original = path.read_text()
                path.write_text(original.replace('upscale_multiplier=1', 'upscale_multiplier=1\n' + key + '=true'))
                enabled = cache.semantic_config(path)
                self.assertEqual(enabled['EmuCore/GS'][key], 'true')
                path.write_text(path.read_text().replace(key + '=true', key + '=false'))
                self.assertNotEqual(enabled, cache.semantic_config(path))
                path.write_text(original)
                self.assertNotEqual(enabled, cache.semantic_config(path))

    def test_real_controller_backend_cannot_enter_private_cache(self):
        path = self.config()
        path.write_text(path.read_text().replace('SDL=false', 'SDL=true'))
        with self.assertRaisesRegex(ValueError, 'isolated keyboard'):
            cache.semantic_config(path)

    def test_full_hash_memo_does_not_accept_same_size_replacement(self):
        path = self.root / 'media'
        path.write_bytes(b'1234')
        previous = cache.sha(path, memo=True)
        replacement = path.with_suffix('.new')
        replacement.write_bytes(b'5678'); os.replace(replacement, path)
        self.assertNotEqual(previous, cache.sha(path, memo=True))

    def test_oversized_zip_entries_rejected_before_decode(self):
        path = self.root / 'bad.p2s'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('eeMemory.bin', b'tiny')
        with patch('state128.read_entry') as decode, patch('zipfile.ZipFile.infolist', return_value=[
                SimpleNamespace(filename='eeMemory.bin', file_size=cache.RAM_BYTES + 1, flag_bits=0)]):
            with self.assertRaisesRegex(ValueError, 'oversized'):
                cache.archive_payload(path)
            decode.assert_not_called()

    def test_duplicate_zip_inventory_refused_before_decode(self):
        path = self.root / 'duplicate.p2s'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('eeMemory.bin', b'tiny')
        info = SimpleNamespace(filename='eeMemory.bin', file_size=4, flag_bits=0)
        with patch('state128.read_entry') as decode, patch('zipfile.ZipFile.infolist', return_value=[info, info]):
            with self.assertRaisesRegex(ValueError, 'inventory'):
                cache.archive_payload(path)
            decode.assert_not_called()

    def test_foreign_pine_owner_is_refused_before_vm_operation(self):
        import kit_paths
        dest = kit_paths.PREP / 'Tag Team Mod'
        copy = SimpleNamespace(base=SimpleNamespace(dest=dest, desktop='private', pid=77), slot=29999,
                               check=lambda: None)
        with patch('kit_win.pid_alive', return_value=True), patch('kit_win.listener_pid', return_value=88), \
                self.assertRaisesRegex(ValueError, 'does not own'):
            cache._owner(copy)

    def test_private_path_and_pid_are_not_enough_without_exact_executable(self):
        import kit_paths
        dest = kit_paths.PREP / 'Tag Team Mod'
        copy = SimpleNamespace(base=SimpleNamespace(dest=dest, desktop='private', pid=77), slot=29999,
                               check=lambda: None)
        with patch('kit_win.pid_alive', return_value=True), patch('kit_win.listener_pid', return_value=77), \
                patch('kit_win.process_path', return_value=str(self.root / 'foreign.exe')), \
                self.assertRaisesRegex(ValueError, 'does not own'):
            cache._owner(copy)

    def test_inactive_native_expiry_is_not_an_outstanding_menu_lease(self):
        import kit_prepare_auto as auto
        import struct
        manager, obj, control = 0x200000, 0x400000, 0x1000
        words = {auto.MANAGER: manager, auto.TEAM_OBJECT: obj, auto.LOOP: 0,
                 manager + 0x18: auto.TEAM_SELECT, obj + 0x3c6c: 1,
                 control: 0x12345678, control + 4: 0, control + 12: 0, control + 16: 179}
        for index, offset in enumerate(auto.SIDES):
            words[obj + 0x8e8 + 4 * index] = obj + offset
            words[obj + offset + 0x134] = 1
        class Memory:
            def __len__(self): return cache.RAM_BYTES
            def __getitem__(self, span): return struct.pack('<I', words.get(span.start, 0))
        menu = SimpleNamespace(CONTROL=control, MAGIC=0x12345678, code_pieces=lambda: [],
                               SELECTIONS=[('teams', 1), ('ffa', 1)])
        with patch.dict(sys.modules, {'native_mode_menu': menu}), patch('menu_return.validate_clean'):
            self.assertEqual(cache.selector(Memory(), 'teams')['scene'], auto.TEAM_SELECT)
            words[control + 4] = 1
            with self.assertRaisesRegex(ValueError, 'outstanding menu lease'):
                cache.selector(Memory(), 'teams')

    def watcher_fixture(self):
        copy = SimpleNamespace(base=SimpleNamespace(dest=self.root / 'private'))
        folder = copy.base.dest / 'game/analysis/autopilot/current'
        folder.mkdir(parents=True)
        status = dict(pid=99, emulator_pid=77, emulator_created=1234.5, launcher_token='a' * 32,
                      native_mode_receipt=dict(epoch=0, choice=None, custom=False), state='MENU')
        path = folder / 'status.json'
        path.write_text(json.dumps(status))
        return copy, folder, path, status

    def test_same_emulator_with_replaced_watcher_token_cannot_keep_lease(self):
        copy, folder, path, status = self.watcher_fixture()
        with patch.object(cache, '_owner', return_value=77), patch('kit_win.pid_alive', return_value=True):
            lease = cache.WatchLease(copy, folder)
            status['launcher_token'] = 'b' * 32
            path.write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, 'instance changed'):
                lease.read(copy)

    def test_pine_pid_reused_with_different_creation_record_is_not_same_instance(self):
        copy, folder, path, status = self.watcher_fixture()
        with patch.object(cache, '_owner', return_value=77), patch('kit_win.pid_alive', return_value=True):
            lease = cache.WatchLease(copy, folder)
            status['emulator_created'] += 10
            path.write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, 'instance changed'):
                lease.read(copy)


if __name__ == '__main__':
    unittest.main()
