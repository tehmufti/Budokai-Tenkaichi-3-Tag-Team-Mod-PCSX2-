"""A stage image read while the game is still setting up a native leader's model is not used.

TTM-MATCH-08 "Leader0 model pointer is outside valid aligned game RAM" (about once in a hundred preparations): the
image for the third capture of a preparation showed no model-table entry for leader 0, although the first capture
a second earlier had passed. The native-frame session now waits, bounded and in running time, for both leaders'
models, reads the memory again, and only when they never settle lets capture() report what it always reported.
No emulator, no sleeping: a fake game whose memory fills late, and a fake clock.
"""
import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import camera_snapshot
import fresh_team_trainer as trainer
import localization
import native_preparation as native
import patch_state
import selected_team_capture as selection
from selected_team_capture import (ACTOR_BYTES, MANAGER_GLOBAL, MODEL_TABLE, RAM_BYTES, leader_models_live,
                                   leader_models_pending)

MANAGER, ACTORS = 0x01870400, 0x018706C0
MODELS, RESOURCES = (0x008C02F0, 0x008C1970), (0x0092B96C, 0x0092B9A4)
REPORTED = 'Leader0 model pointer is outside valid aligned game RAM'      # the words of the failure report
STEP = 0.05                                                               # the wait looks at the game this often


def match(*updates):
    """A 128 MiB image holding just the words of a fresh native two-leader match that the readiness test reads."""
    ram = bytearray(RAM_BYTES)
    w = lambda address, value: struct.pack_into('<I', ram, address, value)
    w(MANAGER_GLOBAL, MANAGER); w(MANAGER, 2); w(MANAGER+4, ACTORS)
    for side in range(2):
        actor = ACTORS+side*ACTOR_BYTES
        for offset in (0, 8, 12): w(actor+offset, side)
        w(MODEL_TABLE+4*side, MODELS[side])
        w(MODELS[side]+16, side); w(MODELS[side]+4, 1); w(MODELS[side]+8, 1); w(MODELS[side]+20, RESOURCES[side])
        w(RESOURCES[side]+52, side); w(RESOURCES[side]+48, 1)
    for address, value in updates: w(address, value)
    return bytes(ram)


READY = match()
NO_MODEL = match((MODEL_TABLE, 0))                         # what the failed preparation's image showed


def words(image):
    return lambda address: struct.unpack_from('<I', image, address)[0]


class Game:
    """A running game seen through PINE. schedule: [(running seconds from the first look, image), ...]; the
    image whose time has come is the memory. Counts looks (status calls), words read and whole-memory reads."""

    def __init__(self, schedule, pauses=()):
        self.schedule = sorted(schedule, key=lambda item: item[0]); self.pauses = pauses
        self.now = 0.0; self.looks = 0; self.reads = []; self.words = 0

    def active(self):
        return self.now-sum(max(0, min(self.now, end)-start) for start, end in self.pauses)

    def memory(self):
        current = self.schedule[0][1]
        for at, image in self.schedule:
            if self.active() >= at: current = image
        return current

    def status(self):
        self.looks += 1
        return 'paused' if any(start <= self.now < end for start, end in self.pauses) else 'running'

    def read_u32(self, address):
        self.words += 1
        return struct.unpack_from('<I', self.memory(), address)[0]

    def read_ram(self, client):
        self.reads.append(round(self.active(), 2))
        return self.memory()

    def sleep(self, seconds):
        self.now += seconds
        if self.now > 5000: raise AssertionError('the wait did not end')

    def __enter__(self): return self

    def __exit__(self, *_): return False


class ReadinessTests(unittest.TestCase):
    def test_a_complete_pair_of_leaders_is_ready(self):
        self.assertIsNone(leader_models_pending(READY))
        self.assertEqual(leader_models_live(words(READY)), MODELS)

    def test_the_reported_image_is_pending_with_the_words_of_the_report(self):
        self.assertEqual(leader_models_pending(NO_MODEL), REPORTED)
        self.assertIsNone(leader_models_live(words(NO_MODEL)))

    def test_every_word_the_game_completes_late_is_waited_for(self):
        for side in range(2):
            model, resource = MODELS[side], RESOURCES[side]
            for update, reason in (((MODEL_TABLE+4*side, 0), 'model pointer is outside valid aligned game RAM'),
                                   ((MODEL_TABLE+4*side, model+4), 'model pointer is outside valid aligned game RAM'),
                                   ((MODEL_TABLE+4*side, 0x08000000), 'model pointer is outside valid aligned game RAM'),
                                   ((MODEL_TABLE+4*side, 0x000FFFF0), 'model pointer is outside valid aligned game RAM'),
                                   ((model+4, 0), 'model has not completed initialization'),
                                   ((model+8, 0), 'model has not completed initialization'),
                                   ((model+16, 7), 'model has not completed initialization'),
                                   ((model+20, 0), 'resource pointer is outside valid aligned game RAM'),
                                   ((resource+48, 0), 'is not using its native reserved loaded resource record'),
                                   ((resource+52, 1-side), 'is not using its native reserved loaded resource record')):
                with self.subTest(side=side, update=update):
                    image = match(update)
                    self.assertEqual(leader_models_pending(image), f'Leader{side} {reason}')
                    self.assertIsNone(leader_models_live(words(image)))

    def test_the_reasons_are_capture_s_own_words(self):
        source = Path(selection.__file__).read_text(encoding='utf-8')
        body = source[source.index('def capture('):]
        for text in ("f'{label} pointer is outside valid aligned game RAM'", "f'Leader{side} model'",
                     "f'Leader{side} model has not completed initialization'", "f'Leader{side} resource'",
                     "f'Leader{side} is not using its native reserved loaded resource record'"):
            self.assertIn(text, body)

    def test_anything_that_is_not_a_fresh_two_leader_match_is_left_to_capture(self):
        for update in ((MANAGER_GLOBAL, 0), (MANAGER, 6), (MANAGER+4, 0), (MANAGER+4, ACTORS+4), (ACTORS, 1),
                       (ACTORS+ACTOR_BYTES+8, 0), (ACTORS+12, 3)):
            with self.subTest(update=update):
                image = match(update, (MODEL_TABLE, 0))
                self.assertIsNone(leader_models_pending(image))
                self.assertIsNone(leader_models_live(words(image)))
        self.assertIsNone(leader_models_pending(bytes(0x100000)))
        self.assertIsNone(leader_models_pending(bytes(RAM_BYTES)))


class SettleTests(unittest.TestCase):
    def settle(self, game, first):
        session = trainer.StreamingSession.__new__(trainer.StreamingSession)
        out = io.StringIO()
        with patch.object(trainer.time, 'monotonic', side_effect=lambda: game.now), \
                patch.object(trainer.time, 'sleep', side_effect=game.sleep), \
                patch.object(native, 'read_ram', side_effect=game.read_ram), \
                patch.object(localization, 'language', return_value='en'), \
                contextlib.redirect_stdout(out):
            image = session.settled_leaders(game, first)
        return image, out.getvalue()

    def test_a_ready_image_is_returned_untouched_without_one_look_at_the_game(self):
        game = Game([(0, READY)])
        image, text = self.settle(game, READY)
        self.assertIs(image, READY)
        self.assertEqual((game.looks, game.words, game.reads, game.now, text), (0, 0, [], 0.0, ''))
        # and an image that is not a native two-leader match at all: capture()'s business, at once
        other = bytes(RAM_BYTES)
        image, text = self.settle(game, other)
        self.assertIs(image, other); self.assertEqual((game.looks, game.reads, text), (0, [], ''))

    def test_memory_that_fills_late_is_read_again_once_the_leaders_stand(self):
        game = Game([(0, NO_MODEL), (0.39, READY)])
        image, text = self.settle(game, NO_MODEL)
        self.assertIs(image, READY)
        self.assertIsNone(leader_models_pending(image))
        self.assertEqual(len(game.reads), 1)                         # one further read of the whole memory
        self.assertGreaterEqual(game.reads[0], 0.39+STEP*(trainer.LEADER_LOOKS-1))   # only after three equal looks
        self.assertLess(game.now, 0.39+STEP*(trainer.LEADER_LOOKS+1))
        self.assertIn('Waiting for the game to finish setting up the first fighters...', text)
        self.assertRegex(text, r'First fighters ready after 0\.[45] s \(memory read 2 times\)\.')

    def test_an_entry_that_flickers_is_not_read_until_it_holds_still(self):
        second = MODELS[0]+0x1680*4
        other = match((MODEL_TABLE, second), (second+16, 0), (second+4, 1), (second+8, 1), (second+20, RESOURCES[0]))
        self.assertIsNone(leader_models_pending(other))             # a second complete model for leader 0
        # complete, gone, complete on another model, gone, that model again, then the final one: no three equal
        # looks before 0.49 s
        game = Game([(0, READY), (0.09, NO_MODEL), (0.19, other), (0.29, NO_MODEL), (0.39, other), (0.49, READY)])
        image, text = self.settle(game, NO_MODEL)
        self.assertIs(image, READY)
        self.assertEqual(len(game.reads), 1)
        self.assertGreaterEqual(game.reads[0], 0.49+STEP*(trainer.LEADER_LOOKS-1))
        self.assertLess(game.reads[0], 0.49+STEP*(trainer.LEADER_LOOKS+1))

    def test_a_second_image_caught_in_a_rebuild_is_waited_for_again(self):
        # the game shows complete leaders, but the memory read first catches leader 1 without its model
        late = match((MODEL_TABLE+4, 0))

        class Tearing(Game):
            def read_ram(self, client):
                self.reads.append(round(self.active(), 2))
                return late if len(self.reads) == 1 else READY
        game = Tearing([(0, READY)])
        image, text = self.settle(game, NO_MODEL)
        self.assertIs(image, READY)
        self.assertEqual(len(game.reads), 2)
        self.assertRegex(text, r'memory read 3 times')

    def test_leaders_that_never_stand_end_the_wait_and_capture_reports_as_before(self):
        game = Game([(0, NO_MODEL)])
        image, text = self.settle(game, NO_MODEL)
        self.assertIs(image, NO_MODEL)
        self.assertEqual(game.reads, [])                             # nothing worth reading again
        self.assertGreaterEqual(game.now, trainer.LEADER_WAIT-0.01)
        self.assertLess(game.now, trainer.LEADER_WAIT+0.2)
        self.assertRegex(text, r'First fighters not ready after 8\.[01] s: '+REPORTED)
        self.assertEqual(leader_models_pending(image), REPORTED)     # capture() stops the setup with these words

    def test_the_further_reads_are_bounded_too(self):
        class Stuck(Game):                                           # the game looks ready, every image is not
            def read_ram(self, client):
                self.reads.append(round(self.active(), 2))
                return NO_MODEL
        game = Stuck([(0, READY)])
        image, text = self.settle(game, NO_MODEL)
        self.assertIs(image, NO_MODEL)
        self.assertEqual(len(game.reads), trainer.LEADER_READS)
        self.assertLess(game.now, 1.0)
        self.assertIn('First fighters not ready after', text)

    def test_a_paused_emulator_is_waited_for_and_only_running_time_counts(self):
        game = Game([(0, NO_MODEL), (0.99, READY)], pauses=((0.5, 900.5),))      # a fifteen-minute settings dialog
        image, text = self.settle(game, NO_MODEL)
        self.assertIs(image, READY)
        self.assertGreater(game.now, 900)
        self.assertLess(game.active(), 0.99+STEP*(trainer.LEADER_LOOKS+2))
        # never fills, with the same pause: the bound is running time
        game = Game([(0, NO_MODEL)], pauses=((0.5, 900.5),))
        image, text = self.settle(game, NO_MODEL)
        self.assertIs(image, NO_MODEL)
        self.assertGreaterEqual(game.active(), trainer.LEADER_WAIT-0.01)
        self.assertLess(game.active(), trainer.LEADER_WAIT+0.3)

    def test_a_lost_connection_ends_the_wait_with_its_own_error(self):
        class Gone(Game):
            def status(self):
                raise TimeoutError('PINE socket did not respond within 10 seconds')
        with self.assertRaisesRegex(TimeoutError, 'PINE socket'):
            self.settle(Gone([(0, NO_MODEL)]), NO_MODEL)

    def test_the_bounds(self):
        self.assertEqual(trainer.LEADER_STAGES, ('original-selected-match', 'heap-ready', 'resources-ready'))
        self.assertTrue(0 < trainer.LEADER_WAIT <= 10 and 1 <= trainer.LEADER_READS <= 5 and trainer.LEADER_LOOKS >= 3)


class SnapshotTests(unittest.TestCase):
    """The stage images capture() reads go through the wait; later stages and ready images do not."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target in (patch.multiple(trainer, ROOT=self.root, STATES=self.root/'runtime128/sstates'),
                       patch.object(patch_state, 'OUTPUT_ROOT', self.root/'analysis/prepared-states'),
                       patch.object(trainer.mod_settings, 'load_settings', return_value=dict(trainer.mod_settings.DEFAULTS))):
            target.start(); self.addCleanup(target.stop)

    def snapshot(self, label, game, diagnostics=False):
        """(the image snapshot() returned, the image the builders are given, the stage file's bytes or None)."""
        session = trainer.StreamingSession(settings={'keep_preparation_diagnostics': diagnostics})
        try:
            session.client = lambda *args, **kwargs: game
            with patch.object(trainer.time, 'monotonic', side_effect=lambda: game.now), \
                    patch.object(trainer.time, 'sleep', side_effect=game.sleep), \
                    patch.object(native, 'quiet') as quiet, patch.object(native, 'read_ram', side_effect=game.read_ram), \
                    contextlib.redirect_stdout(io.StringIO()):
                ram = session.snapshot(label)
            self.assertEqual(quiet.call_count, 1)
            given = camera_snapshot.read_ram(session.source)
            kept = session.source.read_bytes() if session.source.exists() else None
            return ram, given, kept
        finally:
            with contextlib.redirect_stdout(io.StringIO()): session.close()

    def test_each_captured_stage_hands_the_builders_the_settled_image(self):
        for label in trainer.LEADER_STAGES:
            with self.subTest(label=label):
                game = Game([(0, NO_MODEL), (0.29, READY)])
                ram, given, kept = self.snapshot(label, game)
                self.assertEqual(len(game.reads), 2)
                self.assertIs(ram, READY)
                self.assertTrue(given == READY)                              # what every builder is given
                self.assertIsNone(leader_models_pending(given))

    def test_a_kept_stage_file_holds_the_settled_image(self):
        game = Game([(0, NO_MODEL), (0.29, READY)])
        ram, given, kept = self.snapshot('original-selected-match', game, diagnostics=True)
        self.assertTrue(kept == READY)

    def test_a_ready_stage_is_read_once_and_later_stages_are_not_looked_at(self):
        game = Game([(0, READY)])
        ram, given, kept = self.snapshot('resources-ready', game)
        self.assertEqual((len(game.reads), game.looks, game.words), (1, 0, 0))
        for label in ('actors-created', 'render-observed', 'render-ready', 'tag-rush-ready'):
            with self.subTest(label=label):
                game = Game([(0, NO_MODEL)])            # once the fighters exist the leaders are not this wait's business
                ram, given, kept = self.snapshot(label, game)
                self.assertEqual((len(game.reads), game.looks, game.words), (1, 0, 0))
                self.assertIs(ram, NO_MODEL)

    def test_the_savestate_session_is_unchanged(self):
        import inspect
        self.assertNotIn('settled_leaders', inspect.getsource(trainer.Session.snapshot))
        self.assertIn('settled_leaders', inspect.getsource(trainer.StreamingSession.snapshot))


class WordsTests(unittest.TestCase):
    def test_spanish(self):
        self.assertEqual(localization.tr('Waiting for the game to finish setting up the first fighters...', 'es'),
                         'Esperando a que el juego termine de preparar a los primeros luchadores...')
        self.assertEqual(localization.tr('First fighters ready after 0.4 s (memory read 2 times).', 'es'),
                         'Primeros luchadores listos tras 0.4 s (memoria leída 2 veces).')
        self.assertEqual(localization.tr('First fighters not ready after 8.0 s: '+REPORTED, 'es'),
                         'Los primeros luchadores no están listos tras 8.0 s: '+REPORTED)
        for text in ('Waiting for the game to finish setting up the first fighters...',
                     'First fighters ready after 0.4 s (memory read 2 times).'):
            self.assertEqual(localization.tr(text, 'en'), text)


if __name__ == '__main__':
    unittest.main()
