"""Private online preparation must not consume an offline scenario request."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bt3-multifighter/online/netplay'))
import kit_prepare as prepare


class ScenarioQueueIsolation(unittest.TestCase):
    def test_refresh_discards_private_requests_but_preserves_source_and_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            prep = root / 'prep'
            dest = prep / 'Tag Team Mod'
            for folder in (source, dest):
                (folder / 'game/missions/Examples').mkdir(parents=True)
                (folder / 'Play.cmd').write_text('rem test')
                for name in prepare.SCENARIO_QUEUES:
                    (folder / 'game/missions' / name).write_text('offline request')
            (source / 'game/missions/Examples/example.json').write_text('preset')
            (prep / 'copy.json').write_text(json.dumps(dict(source=str(source), version='9')))
            run = SimpleNamespace(args=SimpleNamespace(prep_pine_slot=1, pine_slot=2, hidden=False),
                                  say=lambda text: None, install=dict(root=str(source), version='9'))
            with patch.object(prepare.kit_paths, 'PREP', prep):
                prepare.Prepare(run).copy_installation()
            for name in prepare.SCENARIO_QUEUES:
                self.assertFalse((dest / 'game/missions' / name).exists())
                self.assertEqual((source / 'game/missions' / name).read_text(), 'offline request')
            self.assertEqual((dest / 'game/missions/Examples/example.json').read_text(), 'preset')

    def test_absent_private_folder_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'absent'
            prepare.clear_private_scenario_queues(dest)
            self.assertFalse(dest.exists())


if __name__ == '__main__':
    unittest.main()
