"""Consume the ISO-scoped offline audit; never connect to PCSX2."""
from pathlib import Path
from functools import lru_cache
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iso_compatibility.scanner import cached_profile, scan

import game_profile
ISO=game_profile.source_iso(Path(__file__).resolve().parents[2]/'games/SLUS_219.78.DBZBT4B14REV2ENG.iso')


@lru_cache(maxsize=1)
def profile():
    result=cached_profile(ISO)
    if result is None:
        # Play scans the ISO again before every launch (bt4_preflight), so starting it again is the fix.
        from localization import entry
        raise ValueError(f'The BT4 ISO compatibility profile is missing or outdated. Close PCSX2, then start {entry("play") or "Play"} again to scan the ISO again.')
    if result['identity']['adapter']!='bt4-b14-rev2-eng' or not result['capabilities']['runtime_hooks']:
        raise ValueError('This ISO needs a reviewed BT4 runtime adapter; no game memory was changed.')
    return result


def prepare(progress=print):
    result=scan(ISO,progress=progress)
    profile.cache_clear();fighters.cache_clear()
    profile()
    return result


@lru_cache(maxsize=1)
def fighters():
    return {r['character_id']:r for r in profile()['characters']}


def require_variant(character,costume,damaged):
    row=fighters().get(character)
    if row is None:raise ValueError(f'BT4 slot {character} is not a fighter with usable resources')
    variant=next((v for v in row['costumes'] if (v['costume'],v['damaged'])==(costume,damaged)),None)
    if variant is None or not variant['structurally_valid']:
        reason=variant.get('error','shared animation/AI resources failed validation') if variant else 'costume is absent'
        raise ValueError(f"BT4 {row['name']} {row['form']}, costume {costume+1}{' (damaged)' if damaged else ''}: {reason}. Choose another costume; see compatibility-profiles for the audit.")
    return variant


def stage_support(stage_id,split_screen=False):
    rows=profile()['stages']
    if type(stage_id) is not int or not 0<=stage_id<len(rows):
        raise ValueError('Stage ID is outside the scanned ISO layout')
    return rows[stage_id]['variants']['split_screen' if split_screen else 'normal']
