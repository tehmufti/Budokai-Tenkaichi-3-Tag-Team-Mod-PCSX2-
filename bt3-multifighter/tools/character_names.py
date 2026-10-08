"""Verified English names/forms and actual portraits extracted from the local ISO."""
import json
from functools import lru_cache
from pathlib import Path

ASSETS=Path(__file__).resolve().parents[1]/'assets'


def assets_folder():
    """The chosen game disc's names and portraits (game_profile.assets_dir: the installed disc's assets/, or the
    folder of the disc chosen in Mod settings > Game disc). A damaged choice (game_profile.DiscError) reads as no
    names at all, never as another disc's."""
    import game_profile
    return game_profile.assets_dir()


@lru_cache(maxsize=1)
def character_table():
    try: rows=json.loads((assets_folder()/'characters.json').read_text(encoding='utf-8'))['characters']
    except (OSError,ValueError,KeyError):return {}
    return {row['character_id']:row for row in rows if isinstance(row,dict) and isinstance(row.get('character_id'),int)}


def character_info(character_id):
    row=character_table().get(character_id,{})
    folder=assets_folder() if row.get('portrait') or row.get('bitmap') else ASSETS
    return dict(character_id=character_id,name=row.get('name',f'Fighter {character_id}'),
        base_name=row.get('base_name',f'Fighter {character_id}'),form=row.get('form',''),
        portrait_path=str(folder/row['portrait']) if row.get('portrait') else None,
        bitmap_path=str(folder/row['bitmap']) if row.get('bitmap') else None)


def character_name(character_id):return character_info(character_id)['name']
