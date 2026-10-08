"""Scenario distribution includes curated documents, not the local launch queue."""
import unittest
import build_player_bundle as bundle


class ScenarioPayloadTests(unittest.TestCase):
    def test_browser_and_exact_curated_library_are_shipped_for_each_adapter(self):
        files=bundle.payload_files()
        examples={'Examples/namek-piccolo-arrives.json','Examples/saiyans-goku-arrives.json',
                  'Examples/cell-games-gohan-awakens.json'}
        for adapter in ('bt3-usa','bt4-b14-rev2-eng'):
            self.assertIn(adapter+'/tools/scenario_menu.py',files)
            expected=examples.copy()
            prefix=adapter+'/missions/'
            self.assertEqual({p.removeprefix(prefix) for p in files if p.startswith(prefix)},expected)
        self.assertFalse(any('next-battle' in path for path in files))


if __name__=='__main__':unittest.main()
