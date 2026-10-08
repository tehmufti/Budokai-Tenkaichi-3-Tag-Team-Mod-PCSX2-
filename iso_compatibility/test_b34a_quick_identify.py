"""Beta.34: the Game disc page identifies an ISO without hashing it, names it, and tells a changed stage set.

Reads the ISOs in ../games and the scan profiles in ../compatibility-profiles when present (read only); never
hashes a whole ISO (hashing is patched to fail) and writes nothing.
"""
import copy
import json
import time
import unittest
from pathlib import Path
from unittest import mock

from iso_compatibility import adapters, known_discs, scanner

ROOT = Path(__file__).resolve().parents[1]
GAMES = ROOT/'games'
PROFILES = ROOT/'compatibility-profiles'
DISCS = {
    'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso': ('bt3-usa', True, 'BT3 USA / code-compatible translations'),
    'Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) (Versus Fighting) (ISO) (PS2).iso':
        ('bt3-pal', True, 'BT3 Europe SLES-54945 (En/Fr/De/Es/It)'),
    'Dragon Ball Z - Sparking! Meteor (Japan).iso': ('bt3-jpn', True, 'BT3 Japan SLPS-25815 (Sparking! Meteor)'),
    'SLUS_219.78.DBZBT4B14REV2ENG.iso': ('bt4-b14-rev2-eng', True, 'BT4 B14 REV2 English'),
    'SLUS_219.78.DBZBT4B14REV2.iso': ('bt4-b14-rev2-eng', True, 'BT4 B14 REV2 Spanish'),
    'Dragon Ball Z - Budokai 3 (USA).iso': (None, False, None),
}
PAYLOAD = {'bt3-usa': 'bt3-usa', 'bt3-pal': 'bt3-usa', 'bt3-jpn': 'bt3-usa', 'bt4-b14-rev2-eng': 'bt4-b14-rev2-eng'}


class QuickIdentifyTests(unittest.TestCase):
    def test_each_disc_is_named_in_about_a_second_without_hashing(self):
        present = [name for name in DISCS if (GAMES/name).is_file()]
        if not present:
            self.skipTest('no game ISO in ../games')
        with mock.patch.object(scanner, 'hash_file', side_effect=AssertionError('hashed')):
            for name in present:
                with self.subTest(name=name):
                    started = time.monotonic()
                    adapter, evidence, serial = adapters.quick_identify(GAMES/name)
                    self.assertLess(time.monotonic() - started, 5)
                    expected = DISCS[name]
                    self.assertEqual((adapter if expected[1] else None, evidence['verified'], evidence.get('variant')),
                                     expected)
                    if not evidence['verified']:
                        self.assertIn('refusal', evidence)
                    if expected[2] == 'BT4 B14 REV2 Spanish':
                        self.assertEqual(evidence['native_language'], 'es')

    def test_an_image_that_is_not_an_iso_is_refused_by_the_preflight(self):
        import tempfile
        from iso_compatibility.disc import FormatError
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'x.iso'
            path.write_bytes(b'CISO' + bytes(0x9000))
            with self.assertRaises(FormatError) as caught:
                adapters.quick_identify(path)
            self.assertEqual(caught.exception.code, 'TTM-ISO-03')


class TitleTests(unittest.TestCase):
    def test_every_reviewed_variant_has_a_title_region_and_family(self):
        labels = {label: adapter for adapter, label, *_ in adapters.VARIANTS}
        self.assertEqual(set(known_discs.TITLES), set(labels))
        for label, (title, region, family) in known_discs.TITLES.items():
            with self.subTest(label=label):
                self.assertEqual(family, PAYLOAD[labels[label]])
                self.assertTrue(title and region)
        self.assertEqual(set(known_discs.FAMILY_TITLES), set(PAYLOAD.values()))
        self.assertEqual(set(known_discs.STAGE_DIGESTS), set(labels))


class StageDigestTests(unittest.TestCase):
    def profiles(self):
        found = []
        for path in sorted(PROFILES.glob('*.json')):
            if len(path.stem) != 64:
                continue
            profile = json.loads(path.read_text(encoding='utf-8'))
            if profile.get('identity', {}).get('runtime_adapter_verified'):
                found.append(profile)
        if not found:
            self.skipTest('no verified scan profile in ../compatibility-profiles')
        return found

    def test_the_reviewed_discs_have_their_recorded_stage_files(self):
        for profile in self.profiles():
            variant = profile['identity']['runtime_match']['variant']
            with self.subTest(variant=variant):
                self.assertEqual(known_discs.stage_digest(profile), known_discs.STAGE_DIGESTS[variant])
                self.assertIs(known_discs.stages_modified(profile), False)

    def test_one_changed_stage_file_is_a_modified_disc(self):
        """A9 (c): the mod's expanded-map copy changes 56 of them; a single one is enough."""
        profile = copy.deepcopy(self.profiles()[0])
        stage = str(profile['layout']['stage_base'])
        profile['resources'][stage] = dict(profile['resources'][stage], sha256='0' * 64)
        self.assertIs(known_discs.stages_modified(profile), True)
        self.assertIsNone(known_discs.stages_modified(dict(identity={}, layout={})))
        self.assertIsNone(known_discs.stage_digest(dict(layout=dict(stage_base=1))))


if __name__ == '__main__':
    unittest.main()
