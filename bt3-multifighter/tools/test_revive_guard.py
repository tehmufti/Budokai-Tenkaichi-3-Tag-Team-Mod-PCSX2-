"""Guarded chip damage preserves revival; ordinary hits still interrupt it."""
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
_test_root = _TestPath(__file__).resolve().parents[1]
if not _test_elf_path(_test_root).is_file() or not (_test_root/'tools/test_teammate_revive.py').is_file():
    raise _TestUnit.SkipTest('Native executable and developer revival fixtures are required')

import unittest
import teammate_revive as r
from test_teammate_revive import machine, tick, row, hp, stock


def guard(c):
    actor=c.actors[c.source]
    c.w(actor+0x948,56)
    c.w(actor+2420,239)
    c.w(actor+0x74C,0x10)
    for flag in (0x95,0x41,0xC9,0xD5,0x1C):
        flag=r.FLAG(flag);at=actor+0x10AD+(flag>>3)
        c.write(at,bytes([c.read(at,1)[0]|(1<<(flag&7))]))
    return actor


class GuardReviveTests(unittest.TestCase):
    def test_enter_guard_take_repeated_chip_release_and_finish_once(self):
        for count in r.policy.ACTOR_COUNTS:
            with self.subTest(count=count):
                c=machine(count=count,channel=6);tick(c,2)
                actor=guard(c)
                for offset in (2380,2388,2392,2396,2400):c.w(actor+offset,56)
                tick(c);self.assertEqual(c.u(row(c,c.source)+r.F['progress']),2)
                for health,clip in ((29900,240),(29700,242)):
                    c.w(actor+0x9E4,health);c.w(actor+2420,clip);tick(c)
                    self.assertEqual(c.u(row(c,c.source)+r.F['hp']),health)
                    self.assertEqual(stock(c,c.source),500000)
                c.w(actor+0x948,11)
                for offset in (2380,2388,2392,2396,2400):c.w(actor+offset,-1)
                tick(c,2)
                self.assertEqual((hp(c,c.corpse),stock(c,c.source)),(20000,100000))
                tick(c,5);self.assertEqual(stock(c,c.source),100000)
                self.assertEqual(hp(c,c.source),29700)

    def test_blocked_hits_do_not_need_chip_damage_to_continue(self):
        c=machine(channel=4);actor=guard(c);tick(c,3)
        c.w(actor+2420,244);tick(c,2)
        self.assertEqual((hp(c,c.corpse),hp(c,c.source)),(20000,30000))

    def test_held_block_does_not_excuse_unguarded_hits_break_ko_or_busy_state(self):
        for case in ('hit','break','ko','queue','cinematic','range','unguarded_chip'):
            with self.subTest(case=case):
                c=machine(channel=5);actor=guard(c);tick(c,3)
                c.w(actor+0x9E4,29900)
                if case=='hit':c.w(actor+0x948,34)
                elif case=='break':c.w(actor+0x948,58)
                elif case=='ko':c.w(actor+0x9E4,0)
                elif case=='queue':c.w(actor+3480,1)
                elif case=='cinematic':c.w(actor+2380,253)
                elif case=='range':c.fw(actor+16,100.)
                elif case=='unguarded_chip':c.w(actor+0x948,11)
                tick(c)
                self.assertEqual(c.u(row(c,c.source)+r.F['progress']),0)
                self.assertEqual((hp(c,c.corpse),stock(c,c.source)),(0,500000))

    def test_legacy_programs_keep_their_original_blocking_rule(self):
        for version in (2,3,4,5):
            c=machine(channel=4)
            for address,data in r.program((0x073A0000,r.fusion.CONTACT,r.feed.DAMAGE,
                                           0x073C6400,r.camera.BODY),version):
                c.write(address,data)
            guard(c);tick(c,8)
            self.assertEqual((hp(c,c.corpse),stock(c,c.source)),(0,500000))


if __name__=='__main__':unittest.main()
