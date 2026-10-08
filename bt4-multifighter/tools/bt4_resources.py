"""Exact B14 REV2 resource layout, extracted from the local BT4 disc.

Native 249C60 uses animation5150+id / combat5400+id. Native26BDFC uses
mesh5650 + twice the preceding characters' costume counts + costume,
with the current costume count added for damage. Counts come from file4.
"""
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# UI controls retained inside the expanded character table, not fighters.
MENU_ONLY = frozenset((161, 162, 163, 164))

@lru_cache(maxsize=1)
def layout():
    import compatibility_profile
    return compatibility_profile.profile()['layout']

def costume_count(character):
    if type(character) is not int or not 0 <= character < 250:
        raise ValueError('BT4 character must be an ID from 0 through 249')
    if character in MENU_ONLY:
        raise ValueError(f'BT4 slot {character} is a menu entry, not a fighter')
    count=layout()['costumes'][character]
    if not 1 <= count <= 9:
        raise ValueError(f'BT4 character slot {character} has no model costumes')
    return count

def request_files(character, costume=0, damaged=False):
    count=costume_count(character)
    if type(costume) is not int or not 0 <= costume < count:
        raise ValueError(f'Invalid BT4 costume {costume} for character {character}')
    if type(damaged) is not bool:raise ValueError('Damaged must be boolean')
    mesh=5650+2*sum(layout()['costumes'][:character])+costume+count*damaged
    mesh=layout().get('mesh_fallbacks',{}).get(str(mesh),mesh)
    return [mesh,5150+character,5400+character]

def decode_files(files):
    if len(files)!=3:raise ValueError('Three character files required')
    character=files[1]-5150;count=costume_count(character)
    if files[2]!=5400+character:raise ValueError('Animation/combat character mismatch')
    delta=files[0]-request_files(character)[0]
    if not 0<=delta<2*count:raise ValueError('Mesh/costume character mismatch')
    return character,delta%count,delta>=count
