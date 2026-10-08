"""Beta.34 review fixes, installer side: TTM-CHECK-19 says what is wrong with the chosen game disc in the player's
language, and setup's copy from an older installation says that the discs added there were not copied. Offline:
temporary installations only, no ISO is read, no emulator starts."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import check_installation as checker
import install_player as installer
import setup_messages as messages
from test_b34a_disc_check import installation, library, iso_check, write

TRANSLATIONS = json.loads((Path(__file__).resolve().parent/'installer-es.json').read_text(encoding='utf-8'))


class CheckReasonTests(unittest.TestCase):
    def failure(self, damage):
        with tempfile.TemporaryDirectory() as folder:
            root = installation(folder, tools=True)
            key, disc = library(root, Path(folder)/'eu.iso')
            write(root/'game'/'discs'/'active.json', dict(schema=1, key=key))
            damage(disc)
            run = iso_check(root)
            return checker.iso_failure(run.stderr, run.returncode)

    def test_check_19_says_what_is_wrong_in_the_players_language(self):
        cases = (('changed', lambda disc: (disc/'analysis'/'SLES_549.45').write_bytes(b'edited'),
                  'uno de sus archivos extraídos se modificó o está dañado'),
                 ('missing', lambda disc: (disc/'analysis'/'SLES_549.45').unlink(),
                  'falta uno de sus archivos extraídos'),
                 ('incomplete', lambda disc: write(disc/'disc-files.json', dict(schema=1, state='pending')),
                  'no se añadió por completo'))
        for kind, damage, spanish in cases:
            with self.subTest(kind=kind):
                failure = self.failure(damage)
                self.assertEqual(failure.code, 'TTM-CHECK-19')
                reason = failure.values['reason']
                self.assertEqual(reason['en'], checker.DISC_REASONS[kind])
                self.assertEqual(reason['es'], spanish)
                what = messages.text('TTM-CHECK-19', 'what', 'es', reason=reason['es'], **messages.platform_values())
                self.assertIn(spanish, what)
                self.assertNotIn('A file of the chosen game disc', what, 'no English sentence in the Spanish block')
                self.assertIn('game/discs', failure.render('es'), 'the English message stays in DETAILS and FILE')

    def test_every_reason_is_translated(self):
        for reason in checker.DISC_REASONS.values():
            with self.subTest(reason=reason):
                self.assertIn(reason, checker.SPANISH)
                self.assertNotEqual(checker.SPANISH[reason], reason)


class ImportNoteTests(unittest.TestCase):
    def test_setup_says_how_many_added_discs_it_did_not_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            old = installation(Path(folder)/'old')
            for key in ('e6330ee0780e6f2d', '0123456789abcdef'):
                (old/'game'/'discs'/key).mkdir(parents=True)
            (old/'game'/'discs'/'.trash-e6330ee0780e6f2d-1234').mkdir()
            (old/'game'/'discs'/'active.json').write_text('{}')
            self.assertEqual(installer.added_discs(old), 2)
            self.assertEqual(installer.added_discs(Path(folder)/'none'), 0)
            new = installation(Path(folder)/'new')
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                code = installer.main(['--destination', str(new), '--import-from', str(old), '--language', 'es'])
            self.assertEqual(code, 0)
            lines = out.getvalue().splitlines()
        settings = messages.platform_values()['settings']
        spanish = TRANSLATIONS[installer.NOT_IMPORTED_DISCS]
        self.assertIn(spanish.format(count=2, settings=settings), lines)
        self.assertEqual(lines[-1], TRANSLATIONS[installer.NOT_IMPORTED], 'the PCSX2 note stays last')
        english = installer.import_summary([], [], 'en', 1)
        self.assertIn(installer.NOT_IMPORTED_DISCS.format(count=1, settings=settings), english)
        self.assertNotIn('{', ' '.join(english))
        self.assertEqual(installer.import_summary([], [], 'en'), installer.import_summary([], [], 'en', 0),
                         'nothing is said when no disc was added')
        self.assertEqual(sorted(__import__('re').findall(r'\{\w+\}', spanish)),
                         sorted(__import__('re').findall(r'\{\w+\}', installer.NOT_IMPORTED_DISCS)))


if __name__ == '__main__':
    unittest.main()
