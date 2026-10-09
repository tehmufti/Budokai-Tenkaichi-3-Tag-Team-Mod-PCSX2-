"""Select one adapter and expose an optional user-owned native executable.

No native game instructions are substituted or shipped. Source-only cases
execute generated hooks against explicit external-call callbacks; an accidental
native read is an assertion failure, not a fabricated all-zero executable.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADAPTER = os.environ.get('TAGTEAM_TEST_GAME', 'bt3')
if ADAPTER not in ('bt3', 'bt4'):
    raise ValueError('TAGTEAM_TEST_GAME must be bt3 or bt4')
TOOLS = ROOT / f'{ADAPTER}-multifighter' / 'tools'
sys.path[:0] = [str(HERE), str(TOOLS), str(ROOT/'release_tools/scenario-validation'), str(ROOT)]
# Online modules ship once and use the selected adapter's shared runtime.
sys.path.extend([str(ROOT/'bt3-multifighter/online/netplay/modtools'),
                 str(ROOT/'release_tools/online-hud-tests')])
os.environ['TAGTEAM_ADAPTER'] = 'bt3-usa' if ADAPTER == 'bt3' else 'bt4-b14-rev2-eng'

import prototype
import native_map

requested = os.environ.get('TAGTEAM_TEST_ELF', '').strip()
ELF = Path(requested).expanduser().resolve() if requested else native_map.elf_path(prototype.ROOT)
if requested and not ELF.is_file():
    raise FileNotFoundError('The requested native ELF does not exist')
HAS_NATIVE = ELF.is_file()
addon = os.environ.get('TAGTEAM_TEST_ADDON', '').strip()
ADDON = Path(addon).expanduser().resolve() if addon else ELF.parent/'DBZP.BIN'
if addon and not ADDON.is_file():
    raise FileNotFoundError('The requested BT4 DBZP.BIN does not exist')
HAS_FUSION_NATIVE = HAS_NATIVE and (ADAPTER != 'bt4' or ADDON.is_file())
if HAS_NATIVE:
    _native = prototype.elf_reader(ELF)
    # Imported legacy fixtures may use the original USA filename even when the
    # selected adapter owns another serial. Always bind this child to its ELF.
    prototype.elf_reader = lambda *args: _native
    native_map.elf_path = lambda *args: ELF
else:
    def unavailable(*args):
        raise AssertionError('A source-only test attempted to read native game instructions')
    prototype.elf_reader = lambda *args: (b'', (), unavailable)
