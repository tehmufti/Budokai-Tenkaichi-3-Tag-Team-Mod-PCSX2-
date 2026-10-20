"""Oct 19 loading speed pass: work moved off the loading screen keeps every result and every check.

- tag_rush_install.reviewed_once / pose_assets: the disc-derived reviews run once per watcher process for one disc
  file and pack; a failure is never remembered; an unreadable disc path runs exactly as before.
- fresh_team_trainer.PlayableExport: a StreamingSession writes the rematch archive while the start is acknowledged,
  and the preparation only succeeds (and names the archive) after it is written and verified.
- fresh_team_trainer.warm_preparation: never raises, and builds nothing for tag attacks that are off.
- native_hud_style.build_atlas: a repeated bake returns exactly the first one.
"""
import json
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import fresh_team_trainer as trainer
import tag_rush_install as install


class TagRushMemoTests(unittest.TestCase):
    def setUp(self):
        install._MEMO.clear()
        self.addCleanup(install._MEMO.clear)
        self.folder = tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.iso = Path(self.folder.name)/'disc.iso';self.iso.write_bytes(b'disc')
        self.pack = dict(blocks=[(0x06D10000, b'\x01\x02'), (0x06D10010, b'\x03')], variants={})

    def test_review_runs_once_for_one_disc_and_pack(self):
        with patch.object(install, 'review_playtest_assets') as review:
            for _ in range(3):install.reviewed_once(self.pack, self.iso)
        self.assertEqual(review.call_count, 1)

    def test_a_changed_pack_or_disc_is_reviewed_again(self):
        with patch.object(install, 'review_playtest_assets') as review:
            install.reviewed_once(self.pack, self.iso)
            changed = dict(self.pack, blocks=[(0x06D10000, b'\x01\x09'), (0x06D10010, b'\x03')])
            install.reviewed_once(changed, self.iso)
            self.iso.write_bytes(b'other disc')   # size (and time) change: a new identity
            install.reviewed_once(self.pack, self.iso)
        self.assertEqual(review.call_count, 3)

    def test_a_failed_review_is_raised_every_time(self):
        with patch.object(install, 'review_playtest_assets', side_effect=ValueError('Tag attack donor clip changed')) as review:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'donor clip'):install.reviewed_once(self.pack, self.iso)
        self.assertEqual(review.call_count, 2)

    def test_an_unreadable_disc_path_is_never_remembered(self):
        with patch.object(install, 'review_playtest_assets') as review, \
             patch.object(install.pose_profiles, 'build_assets', return_value=dict(blocks=[])) as pose:
            for _ in range(2):
                install.reviewed_once(self.pack, Path(self.folder.name)/'missing.iso')
                install.pose_assets(Path(self.folder.name)/'missing.iso', False)
        self.assertEqual((review.call_count, pose.call_count), (2, 2))

    def test_pose_assets_are_built_once_and_handed_out_as_private_copies(self):
        built = dict(blocks=[(0x06DE4000, b'pose')], table_address=0x06DE4000, sources=[dict(character=1)])
        with patch.object(install.pose_profiles, 'build_assets', return_value=built) as pose:
            first = install.pose_assets(self.iso, False)
            first['sources'].append('changed by a caller')
            second = install.pose_assets(self.iso, False)
            install.pose_assets(self.iso, True)
        self.assertEqual(pose.call_count, 2)          # one per (disc, bt4) pair
        self.assertEqual(second, dict(built, sources=[dict(character=1)]))

    def test_a_concurrent_caller_waits_for_the_review_in_progress(self):
        started, release, calls = threading.Event(), threading.Event(), []
        def slow(pack, iso=None):
            calls.append(1);started.set();release.wait(5)
        with patch.object(install, 'review_playtest_assets', side_effect=slow):
            worker = threading.Thread(target=install.reviewed_once, args=(self.pack, self.iso));worker.start()
            started.wait(5)
            second = threading.Thread(target=install.reviewed_once, args=(self.pack, self.iso));second.start()
            release.set();worker.join(5);second.join(5)
        self.assertEqual(len(calls), 1)

    def test_the_pack_and_admission_are_read_once_and_handed_out_as_copies(self):
        pack = dict(blocks=[(0x06D10000, b'')], variants={'a': dict(count=1)})
        with patch.object(install, 'cached_assets', return_value=(pack, 'key')) as assets,              patch.object(install, 'disc_admission', return_value=[dict(character=1, supported=True)]) as admission:
            first, _ = install.assets_once(self.iso)
            first['variants']['a']['count'] = 9
            second, key = install.assets_once(self.iso)
            rows = install.admission_once(self.iso);rows.append('x')
            install.admission_once(self.iso)
        self.assertEqual((assets.call_count, admission.call_count, key), (1, 1, 'key'))
        self.assertEqual(second['variants']['a']['count'], 1)

    def test_prefetch_never_raises(self):
        with patch.object(install, 'selected_iso', side_effect=OSError('no disc')):
            self.assertFalse(install.prefetch(dict(trainer.mod_settings.DEFAULTS, tag_team_rush_enabled=True)))


class PlayableExportTests(unittest.TestCase):
    class Fake:
        def __init__(self, run):self.run, self.source = run, run/'18-ready-held.p2s'

    def test_join_names_the_archive_only_after_it_is_written(self):
        with tempfile.TemporaryDirectory() as folder:
            session = self.Fake(Path(folder))
            gate = threading.Event()
            def patched(source, manifest, output):
                gate.wait(5);Path(output).write_bytes(b'archive');return dict(output=str(output))
            with patch('patch_state.patch', side_effect=patched):
                export = trainer.PlayableExport(session, session.source, dict(blocks=[]), session.run/'19-playable-team.p2s')
                export.start()
                self.assertEqual(session.source.name, '18-ready-held.p2s')   # still the held checkpoint
                gate.set();export.join()
            self.assertEqual(session.source.name, '19-playable-team.p2s')
            self.assertEqual(json.loads((session.run/'playable-export.json').read_text())['output'],
                             str(session.run/'19-playable-team.p2s'))

    def test_a_failed_archive_fails_the_preparation_and_keeps_the_held_source(self):
        with tempfile.TemporaryDirectory() as folder:
            session = self.Fake(Path(folder))
            with patch('patch_state.patch', side_effect=ValueError('Block 0 guard mismatch')):
                export = trainer.PlayableExport(session, session.source, dict(blocks=[]), session.run/'19-playable-team.p2s')
                export.start()
                with self.assertRaisesRegex(ValueError, 'guard mismatch'):export.join()
            self.assertEqual(session.source.name, '18-ready-held.p2s')

    def test_only_the_streaming_session_writes_it_in_the_background(self):
        self.assertTrue(trainer.StreamingSession.background_export)
        self.assertFalse(getattr(trainer.Session, 'background_export', False))


class LateExportFailureTests(unittest.TestCase):
    def test_a_rematch_archive_failing_after_the_start_leaves_the_match_running(self):
        session = trainer.StreamingSession.__new__(trainer.StreamingSession)
        export = trainer.PlayableExport(PlayableExportTests.Fake(Path(tempfile.gettempdir())), Path('held.p2s'),
                                        dict(blocks=[]), Path('playable.p2s'))
        export.error = OSError('disk full')
        source = inspect_source()
        # prepare() joins after release_start and turns the error into rematch_unavailable instead of raising.
        self.assertIn("self.rematch_unavailable=f'{type(error).__name__}: {error}'", source)
        with self.assertRaisesRegex(OSError, 'disk full'):export.join()


def inspect_source():
    import inspect
    return inspect.getsource(trainer.Session.prepare)


class WarmPreparationTests(unittest.TestCase):
    def test_disabled_tag_attacks_import_and_build_nothing_for_them(self):
        settings = dict(trainer.mod_settings.DEFAULTS, tag_team_rush_enabled=False, ground_running=False)
        with patch.object(install, 'prefetch') as prefetch:
            trainer.warm_preparation(settings, 'teams').join(60)
        prefetch.assert_not_called()

    def test_a_failing_warm_up_never_raises(self):
        with patch('importlib.import_module', side_effect=ImportError('broken')):
            thread = trainer.warm_preparation({'not': 'settings'}, 'teams')
            thread.join(60)
        self.assertFalse(thread.is_alive())


class HudAtlasMemoTests(unittest.TestCase):
    def test_a_repeated_bake_returns_the_same_atlas(self):
        import native_hud_style as hud
        hud._BAKED.clear();self.addCleanup(hud._BAKED.clear)
        glyphs = {ord('A'): (0, 0, 4, 0), ord('?'): (4, 0, 4, 1)}
        font = dict(header=0x1234, glyphs=glyphs)
        idx = bytes((i*7) & 15 for i in range(32*20))
        with patch.object(hud, 'find_font', return_value=font), patch.object(hud, 'font_planes', return_value=(32, 20, idx)), \
             patch.object(hud, '_bake', wraps=hud._bake) as bake:
            first = hud.build_atlas(b'')
            second = hud.build_atlas(b'')
        self.assertEqual(first, second)
        self.assertEqual(bake.call_count, 1)
        self.assertEqual(first[5], dict(font='0x1234', glyphs=2, atlas_rows=1))


if __name__ == '__main__':
    unittest.main()
