"""Run V11 regressions for BT3 and BT4 in separate interpreter processes."""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', choices=('all', 'bt3', 'bt4'), default='all')
    parser.add_argument('--bt3-elf', type=Path, help='Optional extracted native executable from your BT3 USA disc')
    parser.add_argument('--bt4-elf', type=Path, help='Optional extracted native executable from your BT4 disc')
    parser.add_argument('--bt4-addon', type=Path, help='BT4 DBZP.BIN (defaults to the directory containing its ELF)')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    if args.child:
        import support
        import unittest
        print(f'{support.ADAPTER.upper()}: '+('native instruction tests enabled' if support.HAS_NATIVE
              else 'source-only hooks; native instruction tests explicitly skipped'), flush=True)
        suite = unittest.defaultTestLoader.discover(str(here), pattern='test_*.py')
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    results = []
    for game in ('bt3', 'bt4') if args.game == 'all' else (args.game,):
        env = dict(os.environ, TAGTEAM_TEST_GAME=game)
        env.pop('TAGTEAM_TEST_ELF', None)
        env.pop('TAGTEAM_TEST_ADDON', None)
        elf = getattr(args, game+'_elf')
        if elf is not None:
            if not elf.is_file():
                parser.error(f'--{game}-elf must name an existing extracted executable')
            env['TAGTEAM_TEST_ELF'] = str(elf.resolve())
        if game == 'bt4' and args.bt4_addon is not None:
            if not args.bt4_addon.is_file():
                parser.error('--bt4-addon must name an existing extracted DBZP.BIN')
            env['TAGTEAM_TEST_ADDON'] = str(args.bt4_addon.resolve())
        result = subprocess.run([sys.executable, '-B', str(here/'run.py'), '--child'],
                                cwd=here.parents[1], env=env)
        results.append(result.returncode)
    return int(any(results))


if __name__ == '__main__':
    raise SystemExit(main())
