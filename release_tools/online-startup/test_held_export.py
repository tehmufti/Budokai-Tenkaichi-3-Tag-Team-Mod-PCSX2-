"""Portable ownership/guard/CRC tests for a private held checkpoint export."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'bt3-multifighter/online/netplay'), str(ROOT)]
import kit_paths
import kit_prepare as prepare
import kit_prepare_auto as auto
import patch_state
import state128
import team_intro
import team_start_gate as gate
import guest_loading_screen as cover
import native_preparation as native
import fresh_team_combat
from native_map import SERIAL, CRC


class HeldExport(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / '16-ready-held.p2s'
        self.owner = dict(schema=1, token='a' * 32, emulator_pid=51)
        (self.root / prepare.HELD_EXPORT_OWNER).write_text(json.dumps(self.owner))
        for item in [patch.object(state128, 'TOTAL_RAM', 2 << 20), patch.object(prepare, 'A', lambda a: a & 0xffff),
            patch.object(fresh_team_combat, 'MODE', 0x1000), patch.object(gate, 'CONTROL', 0x2000),
            patch.object(gate, 'REQUEST', 0x2080), patch.object(team_intro, 'CONTROL', 0x2100),
            patch.object(team_intro, 'REQUEST', 0x2180), patch.object(cover, 'HOOK', 0x3000),
            patch.object(cover, 'CONTROL', 0x3010), patch.object(cover, 'code_pieces', return_value=[(0x3000, b'abcd')]),
            patch.object(native, 'CONTROL', 0x4000), patch.object(native, 'code_pieces', return_value=[(0x5000, b'code')])]:
            item.start(); self.addCleanup(item.stop)
        # Only CONTROL is consumed by held_export_memory. Native ELF-dependent
        # constructors are outside these synthetic archive/ownership guard tests.
        names = ('extra_ground_effects', 'extra_generic_effects', 'extra_extended_auras',
                 'extra_charge_aura', 'extra_special_pools', 'spawn_placement', 'team_participation')
        self.previous_effects = {name: sys.modules.get(name) for name in names}
        self.effects = {name: ModuleType(name) for name in names}
        self.controls = []
        for index, effect in enumerate(self.effects.values()):
            effect.CONTROL = 0x6000 + index * 0x20
            self.controls.append(effect.CONTROL)
        self.effect_imports = patch.dict(sys.modules, self.effects)
        self.effect_imports.start(); self.addCleanup(self.effect_imports.stop)
        self.ram = bytearray(2 << 20)
        self.put(0xeb14, 0x100000)
        self.put(0x1000, 1, 6, 0x100000, 6)
        self.put(gate.CONTROL, 1, 0, 0x100000, 6)
        self.put(team_intro.CONTROL, 1, 0, 0x100000)
        self.ram[0x3000:0x3004] = b'abcd'; self.put(cover.CONTROL, 1)
        self.ram[0x5000:0x5004] = b'code'; self.put(native.CONTROL, native.MAGIC)
        for control in self.controls: self.put(control, 5, 0x100000)
        self.manifest = dict(serial=SERIAL, crc=CRC, blocks=[
            dict(address=team_intro.REQUEST, expected_hex='00000000', data_hex='01000000'),
            dict(address=cover.CONTROL, expected_hex='01000000', data_hex='00000000'),
            dict(address=native.CONTROL, expected_hex=struct.pack('<I', native.MAGIC).hex(), data_hex='00000000')])
        self.write_source()
        self.exporter = self.export_method()
        self.session = SimpleNamespace(source=self.source, run=self.root, play_intro=True, index=17)
        self.exporter(self.session, self.ram, self.manifest)
        self.receipt = json.loads((self.root / 'playable-export.json').read_text())

    def put(self, address, *words):
        struct.pack_into('<' + 'I' * len(words), self.ram, address, *words)

    def write_source(self):
        with zipfile.ZipFile(self.source, 'w') as archive:
            archive.writestr('eeMemory.bin', self.ram)
            archive.writestr('SPU2.bin', b'bounded native audio data')

    def export_method(self):
        def write_json(path, data): path.write_text(json.dumps(data))
        scope = dict(ROOT=self.root, json=json, Path=Path, zipfile=zipfile, hashlib=__import__('hashlib'),
            SERIAL=SERIAL, CRC=CRC, read_entry=state128.read_entry, write_json=write_json)
        exec('def export(self, ram, manifest):\n' + prepare.HELD_EXPORT_REPLACEMENT, scope)
        return scope['export']

    def test_private_export_does_not_write_intermediate_archive_or_change_source(self):
        self.assertEqual(self.session.source, self.source)
        self.assertFalse((self.root / '17-playable-team.p2s').exists())
        self.assertEqual(self.receipt['status'], prepare.HELD_EXPORT_STATUS)
        self.assertEqual(self.receipt['source_sha256'], patch_state.file_digest(self.source))
        self.assertEqual(len(self.receipt['input_entries']), 2)

    def test_release_is_recomputed_and_only_the_three_expected_words_change(self):
        released, blocks = prepare.held_export_memory(self.source, self.ram, self.receipt)
        self.assertEqual(blocks, [(row['address'], bytes.fromhex(row['data_hex'])) for row in self.manifest['blocks']])
        expected, _ = patch_state.patch_memory(self.ram, self.manifest)
        self.assertEqual(released, expected)

    def test_bad_owner_token_pid_schema_or_new_match_is_never_accepted(self):
        self.assertTrue(auto.held_receipt_owned(self.receipt, self.owner, 51))
        for owner, pid in [(dict(self.owner, token='b' * 32), 51), (self.owner, 52),
                           (dict(self.owner, schema=True), 51), (None, 51), (dict(self.owner, token='bad'), 51)]:
            self.assertFalse(auto.held_receipt_owned(self.receipt, owner, pid))

    def test_bool_fields_in_receipt_owner_do_not_alias_integer_fields(self):
        record = copy.deepcopy(self.receipt)
        record['owner']['schema'] = True
        self.assertFalse(auto.held_receipt_owned(record, self.owner, 51))
        record = copy.deepcopy(self.receipt)
        record['owner']['emulator_pid'] = True
        self.assertFalse(auto.held_receipt_owned(record, self.owner, 51))

    def test_invalid_manifest_is_not_an_arbitrary_memory_patch(self):
        for change in ('address', 'data_hex', 'expected_hex', 'extra'):
            record = copy.deepcopy(self.receipt)
            if change == 'extra': record['release_manifest']['blocks'].append(dict(address=0x3333, data_hex='01000000', expected_hex='00000000'))
            else: record['release_manifest']['blocks'][0][change] = 0x3333 if change == 'address' else 'ffffffff'
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare.held_export_memory(self.source, self.ram, record)

    def test_changed_capture_or_ram_or_entry_inventory_fails(self):
        for key in ('source_sha256', 'source_ram_sha256', 'output_sha256', 'input_entries', 'schema', 'status'):
            record = copy.deepcopy(self.receipt)
            record[key] = True if key == 'schema' else ([] if key == 'input_entries' else 'changed')
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare.held_export_memory(self.source, self.ram, record)

    def test_synthetic_effect_imports_restore_previous_modules(self):
        for name, module in self.effects.items():
            self.assertIs(sys.modules[name], module)
        self.effect_imports.stop()
        for name, previous in self.previous_effects.items():
            self.assertIs(sys.modules.get(name), previous)

    def test_all_effect_and_terrain_guards_remain_required(self):
        for control in self.controls:
            changed = bytearray(self.ram); struct.pack_into('<I', changed, control, 4)
            record = dict(self.receipt, source_ram_sha256=__import__('hashlib').sha256(changed).hexdigest())
            with self.subTest(control=control), self.assertRaises(ValueError):
                prepare.held_export_memory(self.source, changed, record)

    def test_manager_start_request_and_intro_fail(self):
        for address, value in [(0xeb14, 0), (gate.CONTROL + 8, 0), (gate.REQUEST, 1),
                               (team_intro.CONTROL + 8, 0)]:
            changed = bytearray(self.ram); struct.pack_into('<I', changed, address, value)
            record = dict(self.receipt, source_ram_sha256=__import__('hashlib').sha256(changed).hexdigest())
            with self.subTest(address=address), self.assertRaises(ValueError):
                prepare.held_export_memory(self.source, changed, record)

    def test_export_reads_every_non_ee_payload_crc_before_publishing(self):
        raw = bytearray(self.source.read_bytes())
        with zipfile.ZipFile(self.source) as state:
            info = state.getinfo('SPU2.bin')
            address = info.header_offset + 30 + len(info.filename)
        raw[address] ^= 1; self.source.write_bytes(raw)
        (self.root / 'playable-export.json').unlink()
        with self.assertRaises(zipfile.BadZipFile): self.exporter(self.session, self.ram, self.manifest)
        self.assertFalse((self.root / 'playable-export.json').exists())

    def test_export_keeps_original_ee_crc_guard(self):
        changed = bytearray(self.ram); changed[16] ^= 1
        (self.root / 'playable-export.json').unlink()
        with self.assertRaises(ValueError): self.exporter(self.session, changed, self.manifest)
        self.assertFalse((self.root / 'playable-export.json').exists())

    def receipt_reader(self, record=None):
        dest = self.root / 'private-copy'
        directory = dest / 'game/analysis/prepared-states/new-match'
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / '16-ready-held.p2s'
        output.write_bytes(self.source.read_bytes())
        record = copy.deepcopy(record or self.receipt)
        record.update(source=str(output.resolve()), output=str(output.resolve()))
        path = directory / 'playable-export.json'
        path.write_text(json.dumps(record))
        events = []
        reader = SimpleNamespace(base=SimpleNamespace(dest=dest, pid=51), exports_before=set(),
            export_owner=self.owner, held_export=None, export_receipts=lambda: [path],
            event=lambda *args, **kwargs: events.append((args, kwargs)))
        return reader, path, output, events

    def test_early_checkpoint_requires_current_owner_and_preserves_proof(self):
        reader, _, output, events = self.receipt_reader()
        self.assertEqual(auto.PrepCopy.early_checkpoint(reader), output.resolve())
        self.assertEqual(reader.held_export['owner'], self.owner)
        self.assertEqual(len(events), 1)
        reader.base.pid = 52
        self.assertIsNone(auto.PrepCopy.early_checkpoint(reader))
        reader.base.pid = 51
        reader.export_owner = dict(self.owner, token='b' * 32)
        self.assertIsNone(auto.PrepCopy.early_checkpoint(reader))

    def test_early_checkpoint_rejects_old_changed_or_escaped_capture(self):
        reader, path, output, events = self.receipt_reader()
        reader.exports_before.add(str(path.resolve()))
        self.assertIsNone(auto.PrepCopy.early_checkpoint(reader))
        reader.exports_before.clear()
        raw = output.read_bytes(); output.write_bytes(raw + b'changed')
        self.assertIsNone(auto.PrepCopy.early_checkpoint(reader))
        output.write_bytes(raw)
        record = json.loads(path.read_text())
        record.update(source=str(self.source.resolve()), output=str(self.source.resolve()))
        path.write_text(json.dumps(record))
        self.assertIsNone(auto.PrepCopy.early_checkpoint(reader))
        self.assertEqual(events, [])

    def test_final_source_check_rejects_non_ee_change_with_valid_crc_and_identical_ee(self):
        prepare.check_held_export_source(self.source, self.receipt)
        with zipfile.ZipFile(self.source, 'w') as archive:
            archive.writestr('eeMemory.bin', self.ram)
            archive.writestr('SPU2.bin', b'different valid native audio')
        with zipfile.ZipFile(self.source) as archive:
            self.assertEqual(archive.read('eeMemory.bin'), self.ram)
            self.assertIsNone(archive.testzip())
        with self.assertRaisesRegex(ValueError, 'changed during final conversion'):
            prepare.check_held_export_source(self.source, self.receipt)

    def test_ordinary_capture_has_no_extra_held_source_read(self):
        with patch.object(patch_state, 'file_digest', side_effect=AssertionError('unneeded read')):
            prepare.check_held_export_source(self.source, None)

    def test_export_refuses_malformed_owner_before_publishing(self):
        path = self.root / 'playable-export.json'
        path.unlink()
        for owner in [[], dict(self.owner, schema=True), dict(self.owner, emulator_pid=0)]:
            (self.root / prepare.HELD_EXPORT_OWNER).write_text(json.dumps(owner))
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                self.exporter(self.session, self.ram, self.manifest)
            self.assertFalse(path.exists())

    def test_private_patch_preserves_every_original_offline_export_guard(self):
        source = (ROOT / 'bt3-multifighter/tools/fresh_team_trainer.py').read_text()
        before = source[source.index('    def export_playable('):source.index('    def release_start(', source.index('    def export_playable('))]
        old, new = prepare.patches(29099)['game/tools/fresh_team_trainer.py'][0]
        self.assertEqual(before.count(old), 1)
        changed = before.replace(old, new)
        self.assertEqual(changed.split('        owner =')[0], before.split('        report = patch')[0])
        self.assertIn('report = patch(self.source, manifest, output)', source)

class PrivateAccelerationProfile(unittest.TestCase):
    def configure(self, hidden, windows):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        copy = prepare.Prepare.__new__(prepare.Prepare)
        copy.dest, copy.orig, copy.slot = root / 'private', root / 'originals', 29990
        copy.args = SimpleNamespace(hidden=hidden)
        ini = copy.dest / 'game/runtime28/inis/PCSX2.ini'
        ini.parent.mkdir(parents=True)
        original = ('[UI]\nStartPaused = true\n[EmuCore/GS]\nRenderer = 7\n'
                    '[Framerate]\nTurboScalar = 1\n[InputSources]\nSDL = true\nXInput = true\nDInput = true\n')
        ini.write_text(original)
        with patch.object(prepare, 'patches', return_value={}), patch.object(prepare.kit_win, 'WINDOWS', windows):
            copy.patch()
        import configparser
        config = configparser.ConfigParser(interpolation=None)
        config.read(ini)
        self.assertEqual((copy.orig / 'game/runtime28/inis/PCSX2.ini').read_text(), original)
        return config

    def test_hidden_windows_only_has_null_renderer_and_private_turbo(self):
        config = self.configure(True, True)
        self.assertEqual(config.getint('EmuCore/GS', 'Renderer'), 11)
        self.assertEqual(config.getint('Framerate', 'TurboScalar'), 32)
        self.assertEqual(prepare.PRIVATE_SPEED, 32.0)
        self.assertEqual(config.getfloat('Framerate', 'NominalScalar'), 1)
        for backend in ('SDL', 'XInput', 'DInput'):
            self.assertFalse(config.getboolean('InputSources', backend))

    def test_visible_copy_does_not_change_rendering_or_game_speed(self):
        config = self.configure(False, True)
        self.assertEqual(config.getint('EmuCore/GS', 'Renderer'), 7)
        self.assertEqual(config.getint('Framerate', 'TurboScalar'), 1)
        self.assertTrue(config.getboolean('InputSources', 'SDL'))

    def test_non_windows_does_not_receive_windows_null_renderer(self):
        config = self.configure(True, False)
        self.assertEqual(config.getint('EmuCore/GS', 'Renderer'), 7)

if __name__ == '__main__': unittest.main()
