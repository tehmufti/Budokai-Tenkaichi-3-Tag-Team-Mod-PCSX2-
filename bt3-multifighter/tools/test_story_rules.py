# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import story_missions as doc

def document(outcome='hold_at_1_hp'):
    d=doc.default_mission()
    d['finish_rules']=[dict(victim='rival',attacker='hero',attack='ultimate',otherwise=outcome)]
    return doc.validate(d)
