"""Background lobby preparation must never commit stale specs or seat owners."""
import copy
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_prebuild
import kit_spec
from kit_codes import KitError


def spec():
    return kit_spec.make(tables_sha256='1' * 64,
                         teams=[[(2, 0, 0), (25, 0, None)], [(54, 0, 1)]], stage=0,
                         mod_build='0.1.0-beta.8')


class Lobby:
    phase = 'lobby'

    def __init__(self):
        self.choice = spec()
        self.ready = False
        self.owners = {0: 1, 1: 2}

    def spec(self, tables, mod_build=None):
        return self.choice

    def all_ready(self):
        raise AssertionError('Speculation must not gate on Ready')


def prep():
    return SimpleNamespace(state='warm', lock=threading.RLock(), cancel=threading.Event())


class Host(kit_prebuild.PrebuildMixin):
    def __init__(self):
        self.role, self.phase = 'host', 'lobby'
        self.lobby = Lobby()
        self.local = dict(catalog=dict(tables_sha256='1' * 64), view=object(),
                          install=dict(version='0.1.0-beta.8'))
        self.prep = prep()
        self.prep_gen = 0
        self.args = SimpleNamespace(test_hooks=True)
        self.test_prep = {}
        self.match = None
        self.jobs = {}
        self.logs, self.started, self.failed, self.published, self.builds = [], [], [], [], []
        self.during_build = None
        self.init_prebuild()

    def say(self, message):
        self.logs.append(message)

    def busy(self, name):
        return name in self.jobs

    def job(self, name, fn, *args, then=None, fail=None):
        self.jobs[name] = (fn, args, then, fail)

    def finish(self, name='prebuild'):
        fn, args, then, fail = self.jobs[name]
        try:
            value = fn(*args)
        except Exception as error:
            self.jobs.pop(name)
            fail(error)
        else:
            self.jobs.pop(name)
            then(value)

    def _prepare_locked(self, preparation, choice, folder, options, title):
        self.builds.append((preparation, copy.deepcopy(choice), copy.deepcopy(options)))
        if self.during_build:
            self.during_build()
        return dict(spec_sha=kit_spec.spec_sha(choice), options=options, file='verified.p2s', title=title)

    def auto_prepared(self, meta, gen):
        self.started.append((meta, gen))

    def auto_failed(self, error, gen):
        self.failed.append((error, gen))

    def publish_prebuild(self, meta):
        self.published.append(meta)

    def commit_start(self, choice=None):
        choice = self.lobby.choice if choice is None else choice
        self.prep_gen += 1
        self.phase = 'preparing'
        self.match = dict(spec=copy.deepcopy(choice), spec_sha=kit_spec.spec_sha(choice),
                          seats=dict(self.lobby.owners), prep_gen=self.prep_gen)


class PrebuildTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.mocks = [patch.object(kit_spec, 'validate'),
                      patch.object(kit_spec, 'title', return_value='Test match'),
                      patch.object(kit_prebuild.kit_match, 'made_match', return_value=None),
                      patch.object(kit_prebuild.kit_match, 'made_folder', return_value=Path('isolated-QA'))]
        for mock in self.mocks:
            mock.start()
            self.addCleanup(mock.stop)

    def settled(self):
        self.host.tick_prebuild(0)
        self.host.tick_prebuild(1.5)
        self.assertIn('prebuild', self.host.jobs)

    def test_waits_for_settled_edits_without_ready_or_auto_start(self):
        h = self.host
        h.tick_prebuild(0)
        h.tick_prebuild(1.49)
        self.assertFalse(h.jobs)
        h.tick_prebuild(1.5)
        h.finish()
        self.assertEqual(h.phase, 'lobby')
        self.assertFalse(h.lobby.ready)
        self.assertIsNone(h.match)
        self.assertFalse(h.started)
        self.assertEqual(len(h.published), 1)
        h.tick_prebuild(20)
        self.assertEqual(len(h.published), 1)
        self.assertFalse(h.jobs)

    def test_edit_restarts_debounce_and_freezes_the_spec(self):
        h = self.host
        h.tick_prebuild(0)
        h.lobby.choice['teams'][0][0]['character'] = 3
        h.tick_prebuild(1)
        h.tick_prebuild(2.49)
        self.assertFalse(h.jobs)
        h.tick_prebuild(2.5)
        original = copy.deepcopy(h.prebuild['spec'])
        h.lobby.choice['teams'][0][0]['character'] = 4
        self.assertEqual(h.prebuild['spec'], original)

    def test_invalid_or_random_choices_do_not_prepare_or_resolve_random(self):
        h = self.host
        for field in ('stage', 'bgm'):
            h.lobby.choice[field] = 'random'
            h.tick_prebuild(0)
            h.tick_prebuild(5)
            self.assertFalse(h.jobs)
            self.assertEqual(h.lobby.choice[field], 'random')
            h.lobby.choice[field] = 0
        with patch.object(kit_spec, 'validate', side_effect=KitError('TTM-NET-29', what='bad pick')):
            h.tick_prebuild(0)
            h.tick_prebuild(10)
        self.assertFalse(h.jobs)

    def test_never_races_warm_suspend_or_another_preparation(self):
        h = self.host
        for name in ('warm', 'suspend', 'prep'):
            h.jobs[name] = object()
            h.tick_prebuild(0)
            h.tick_prebuild(10)
            self.assertNotIn('prebuild', h.jobs)
            h.jobs.clear()
        h.prep.state = 'resetting'
        h.tick_prebuild(20)
        self.assertFalse(h.jobs)
        h.prep.state = 'suspended'
        h.tick_prebuild(30)
        self.assertIn('prebuild', h.jobs)

    def test_matching_inflight_start_adopts_and_uses_current_owners(self):
        h = self.host
        self.settled()
        h.lobby.owners = {0: 6, 1: 9}      # same human slots, different people
        h.commit_start()
        current_seats = copy.deepcopy(h.match['seats'])
        self.assertTrue(h.adopt_prebuild(h.match['spec'], None, h.prep_gen))
        h.finish()
        self.assertEqual(len(h.started), 1)
        self.assertEqual(h.started[0][1], h.prep_gen)
        self.assertEqual(h.match['seats'], current_seats)
        self.assertNotIn('owners', h.prebuild['spec'])
        self.assertFalse(h.published)

    def test_completed_exact_capture_can_be_adopted(self):
        h = self.host
        self.settled()
        h.finish()
        h.commit_start()
        self.assertTrue(h.adopt_prebuild(h.match['spec'], {}, h.prep_gen))
        self.assertEqual(len(h.started), 1)
        self.assertTrue(h.adopt_prebuild(h.match['spec'], None, h.prep_gen))
        self.assertEqual(len(h.started), 1)

    def test_cpu_ownership_or_options_change_cannot_adopt(self):
        h = self.host
        self.settled()
        h.lobby.choice['teams'][0][1]['slot'] = 2
        h.commit_start()
        self.assertFalse(h.adopt_prebuild(h.match['spec'], None, h.prep_gen))
        h.match['spec'] = h.prebuild['spec']
        h.match['spec_sha'] = h.prebuild['key'][0]
        self.assertFalse(h.adopt_prebuild(h.match['spec'], dict(test_ki=True), h.prep_gen))

    def test_changed_lobby_finishes_old_capture_only_into_cache(self):
        h = self.host
        self.settled()
        old_sha = h.prebuild['key'][0]

        def change():
            h.lobby.choice['stage'] = 1
            h.tick_prebuild(2)

        h.during_build = change
        h.finish()
        self.assertEqual(h.prebuild['meta']['spec_sha'], old_sha)
        self.assertFalse(h.started)
        self.assertFalse(h.published)

    def test_old_generation_or_replaced_copy_cannot_commit_completion(self):
        h = self.host
        self.settled()
        h.commit_start()
        self.assertTrue(h.adopt_prebuild(h.match['spec'], None, h.prep_gen))

        def invalidate():
            h.prep_gen += 1
            h.prep = prep()

        h.during_build = invalidate
        h.finish()
        self.assertFalse(h.started)
        self.assertFalse(h.failed)
        self.assertFalse(h.published)

    def test_cancel_before_worker_starts_does_not_cancel_another_owner(self):
        h = self.host
        self.settled()
        preparation = h.prep
        h.cancel_prebuild(cancel_running=True)
        self.assertFalse(preparation.cancel.is_set())
        h.finish()
        self.assertFalse(h.builds)
        self.assertFalse(h.started)

    def test_cancel_running_job_cancels_only_its_owned_copy(self):
        h = self.host
        self.settled()
        preparation = h.prep
        h.during_build = lambda: h.cancel_prebuild(cancel_running=True)
        h.finish()
        self.assertTrue(preparation.cancel.is_set())
        self.assertFalse(h.started)
        self.assertFalse(h.published)

    def test_cancel_does_not_touch_a_replacement_copy(self):
        h = self.host
        self.settled()
        record = h.prebuild
        record['running'] = True
        h.prep = prep()
        h.cancel_prebuild(cancel_running=True)
        self.assertFalse(h.prep.cancel.is_set())
        self.assertFalse(record['prep'].cancel.is_set())

    def test_failure_does_not_flood_or_change_ready_and_start_can_retry(self):
        h = self.host
        self.settled()

        def fail():
            raise ValueError('disc read failed')

        h.during_build = fail
        h.finish()
        for at in range(2, 20):
            h.tick_prebuild(at)
        self.assertFalse(h.jobs)
        self.assertFalse(h.lobby.ready)
        self.assertFalse(h.failed)
        self.assertEqual(sum('Background preparation stopped' in text for text in h.logs), 1)
        h.commit_start()
        self.assertFalse(h.adopt_prebuild(h.match['spec'], None, h.prep_gen))

    def test_wrong_callback_spec_or_options_is_rejected(self):
        h = self.host
        self.settled()
        record = h.prebuild
        h.jobs.clear()
        h._prebuild_done(record, dict(spec_sha='0' * 64, options=None))
        self.assertFalse(h.published)
        self.assertFalse(h.started)
        self.assertEqual(h.prebuild_failed_choice, record['key'])

    def test_empty_cancellation_error_and_non_dict_result_are_handled(self):
        h = self.host
        self.settled()
        record = h.prebuild
        h.jobs.clear()
        h._prebuild_failed(record, Exception())
        self.assertEqual(h.prebuild_failed_choice, record['key'])
        h._prebuild_done(record, None)
        self.assertFalse(h.published)
        self.assertFalse(h.started)

    def test_adopted_failure_uses_existing_committed_failure_path(self):
        h = self.host
        self.settled()
        h.commit_start()
        self.assertTrue(h.adopt_prebuild(h.match['spec'], None, h.prep_gen))

        def fail():
            raise ValueError('disc read failed')

        h.during_build = fail
        h.finish()
        self.assertEqual(len(h.failed), 1)
        self.assertEqual(h.failed[0][1], h.prep_gen)


if __name__ == '__main__':
    unittest.main()
