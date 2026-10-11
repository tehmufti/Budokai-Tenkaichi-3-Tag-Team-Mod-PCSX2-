"""Lightweight tag-attack admission before importing native guest builders."""
import os
from pathlib import Path

ONLINE_PREPARATION_ENV = 'TAGTEAM_ONLINE_PREPARATION'
ONLINE_PREPARATION_MARKER = 'online-held-export-owner.json'
SUPPORTED_ADAPTERS = frozenset(('bt3-usa', 'bt4-b14-rev2-eng'))


def preparation_reason(settings, battle_mode, root, *, adapter=None, online=False):
    """An empty reason admits offline preparation; no ISO or guest code is read."""
    if not settings.get('tag_team_rush_enabled', True):
        return 'Tag-team rush is disabled.'
    if (online or os.environ.get(ONLINE_PREPARATION_ENV) == '1'
            or (Path(root) / ONLINE_PREPARATION_MARKER).is_file()):
        return 'Tag-team rush is unavailable online.'
    if battle_mode == 'ffa':
        return 'Tag-team rush requires teammates.'
    if adapter is None:
        from native_map import ADAPTER
        adapter = ADAPTER
    if adapter not in SUPPORTED_ADAPTERS:
        return 'Tag-team rush currently supports BT3 USA and BT4 English/Spanish.'
    return ''
