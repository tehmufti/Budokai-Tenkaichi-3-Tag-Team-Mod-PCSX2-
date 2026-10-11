# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import unittest

import tag_rush_status as status
from test_tag_team_rush_guest import machine


class TagRushStatusTests(unittest.TestCase):
    def test_unreviewed_outfit_has_a_local_reason_without_a_global_match_block(self):
        c=machine();model=c.u(status.tag.core.MODELS+8)
        c.w(model+12,63);flags=c.u(status.tag.CONTROL+0x3A0)
        c.write(flags+63,b'\0');before=dict(c.memory)
        report=status.inspect_words(c.u)
        self.assertEqual(report['gate_reasons'],[])
        self.assertFalse(report['fighters'][2]['admitted'])
        self.assertIn('ordinary combat and beam assist remain available',report['fighters'][2]['unavailable'])
        self.assertTrue(report['fighters'][0]['admitted'])
        self.assertEqual(c.memory,before)

    def test_approach_diagnostics_belong_to_this_match_and_do_not_write(self):
        import tag_rush_approach as approach
        c=machine();control=status.tag.CONTROL
        for key,value in dict(magic=approach.MAGIC,active=1,
                              manager=c.u(control+status.tag.C['manager']),
                              count=c.u(control+status.tag.C['count']),
                              ticks=status.ACTOR_HZ,misses=2,connected=3).items():
            c.w(approach.STATE+approach.S[key],value)
        before=dict(c.memory)
        self.assertEqual(status.inspect_words(c.u)['approach'],
                         dict(active=True,seconds_left=round(approach.TIMEOUT/status.ACTOR_HZ-1,2),
                              misses=2,connected=3,last_miss_reason='none'))
        self.assertEqual(c.memory,before)
        c.w(approach.STATE+approach.S['manager'],0)
        self.assertNotIn('approach',status.inspect_words(c.u))

    def test_ordinary_start_has_no_false_gate_reason_and_never_writes(self):
        c=machine();c.w(status.tag.CONTROL+status.tag.C['ready'],1)
        before=dict(c.memory)
        report=status.inspect_words(c.u)
        self.assertTrue(report['installed'])
        self.assertEqual(report['gate_reasons'],[])
        self.assertEqual(len(report['fighters']),6)
        self.assertEqual(c.memory,before)

    def test_missing_and_stale_installations_are_explained_without_foreign_reads(self):
        c=machine();c.w(status.tag.CONTROL,0)
        self.assertFalse(status.inspect_words(c.u)['installed'])
        c=machine();c.w(status.tag.CONTROL+status.tag.C['manager'],0xFFFFFFFF)
        report=status.inspect_words(c.u)
        self.assertIn('Battle or fighter registry differs from this preparation',report['gate_reasons'])
        self.assertEqual(report['fighters'],[])

    def test_native_pause_menu_and_stage_transition_are_distinguished_without_writes(self):
        cases=((0x4100,['Native pause menu is open; resume from the game pause menu']),
               (0x100,['Native battle pause is active']),
               (0x2000,['Native stage transition is active']),
               (0x2100,['Native battle pause is active','Native stage transition is active']))
        for flags,expected in cases:
            c=machine();c.w(status.A(0x3337B8),flags);before=dict(c.memory)
            self.assertEqual(status.inspect_words(c.u)['gate_reasons'],expected)
            self.assertEqual(c.memory,before)

    def test_loading_pause_and_initialization_failure_have_specific_reasons(self):
        c=machine();c.w(status.tag.start.CONTROL,1);c.w(status.A(0x333700),1)
        c.w(status.tag.CONTROL+status.tag.C['ready'],0)
        c.w(status.boot.STATE,status.boot.MAGIC);c.w(status.boot.STATE+status.boot.S['phase'],3)
        c.w(status.boot.STATE+status.boot.S['error'],4)
        report=status.inspect_words(c.u)
        self.assertIn('Waiting for the match loading hold to release',report['gate_reasons'])
        self.assertIn('Game is paused',report['gate_reasons'])
        self.assertEqual(report['initialization']['error'],'Native effect initialization failed')


if __name__=='__main__':unittest.main()
