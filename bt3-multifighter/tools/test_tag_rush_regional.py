"""Tag attacks on the European and Japanese BT3 discs: the complete offline install plan, read from each real disc.

A synthetic captured 2v2 (the test_tag_rush_install fixture) is prepared in a bt3-pal / bt3-jpn process with that
disc's ISO: every disc-backed asset, scene, pose, beam-audio and HUD piece must build, and every native hook must
replace exactly the words the regional executable holds at the translated site. Skipped without the discs.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
GAMES = HERE.parents[1] / 'games'
DISCS = {'bt3-pal': ('SLES_549.45', 'Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) '
                     '(Versus Fighting) (ISO) (PS2).iso'),
         'bt3-jpn': ('SLPS_258.15', 'Dragon Ball Z - Sparking! Meteor (Japan).iso')}
SCRIPT = r'''
import json, struct, sys
import tag_rush_install as install, cinematic_contact_guard as contact, inactive_actor_guard as inactive
import viewport_hud as hud, tag_rush_special_beam as beam
from native_map import A, ADAPTER, elf_path
from prototype import ROOT, elf_reader
from test_tag_rush_install import fixture, w, OPTIONS
roster = [int(x) for x in sys.argv[2].split(',')]
ram = fixture()
for index, character in enumerate(roster):
    w(ram, 0x2300000 + index * 0x2000 + 12, character)
plan = install.build_offline(ram, OPTIONS, iso=sys.argv[1], training=True)
native = elf_reader(elf_path(ROOT))[2]
hooks = []
for block in plan['blocks']:
    address, expected = block['address'], bytes.fromhex(block['expected_hex'])
    # contact.PROTECTED and the rush contact site already hold the cinematic contact guard's jumps (installed and
    # audited by cinematic_contact_guard before tag attacks); every other site must still hold the disc's words.
    if address < 0x400000 and address not in (contact.PROTECTED, install.launch.CONTACT_HOOK):
        hooks.append([address, expected == native(address, len(expected))])
print(json.dumps(dict(adapter=ADAPTER, usable=plan['usable'], hooks=hooks, blocks=len(plan['blocks']),
                      characters=[r['character'] for r in plan['characters']],
                      method=struct.unpack('<I', native(A(0x2C38E0), 4))[0] == beam.KIND0_UPDATE())))
'''


class RegionalTagPlanTests(unittest.TestCase):
    def plan(self, adapter, roster):
        serial, iso = DISCS[adapter]
        if not (GAMES / iso).is_file() or not (HERE.parent / 'analysis' / serial).is_file():
            self.skipTest(f'{adapter}: the disc or its executable is not present here')
        env = dict(os.environ, TAGTEAM_ADAPTER=adapter, PYTHONDONTWRITEBYTECODE='1')
        env.pop('TAGTEAM_ONLINE_PREPARATION', None)
        result = subprocess.run([sys.executable, '-c', SCRIPT, str(GAMES / iso), ','.join(map(str, roster))], cwd=HERE,
                                env=env, capture_output=True, text=True, timeout=600)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    def check(self, adapter):
        for roster in ((0, 1, 2, 3), (0, 22, 56, 57)):
            out = self.plan(adapter, roster)
            self.assertEqual(out['adapter'], adapter)
            self.assertTrue(out['usable'])
            self.assertEqual(out['characters'], list(roster))
            # recovery, sound queue, rush retarget/commit, CPU decisions, beam audio
            self.assertGreaterEqual(len(out['hooks']), 6)
            self.assertEqual([a for a, ok in out['hooks'] if not ok], [], 'hook originals differ from the disc')
            self.assertTrue(out['method'], 'Special Beam Cannon update is not the class method of this disc')

    def test_european_disc(self):
        self.check('bt3-pal')

    def test_japanese_disc(self):
        self.check('bt3-jpn')


if __name__ == '__main__':
    unittest.main()
