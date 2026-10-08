"""Extract Mission 100's original enemy rosters from the user's USA BT3 disc.

Unknown native restrictions are retained verbatim in provenance, not guessed.
The extraction is offline and never creates or loads an emulator save state.
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

import story_missions as missions


def extract(iso):
    # The archive entry and nested data are verified by lengths and every row.
    # Do not silently apply this USA table layout to a different modded disc.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from iso_compatibility.labels import unpack_bpe, english_label
    from iso_compatibility.disc import Disc, package as spans
    # Read the source disc's identity, independent of the Workbench's currently
    # selected adapter. In particular, a PAL Workbench may import a USA disc.
    with Disc(iso) as disc:
        if disc.serial!='SLUS_216.78' or disc.region!='US' or disc.kind!='bt3-afs':
            raise ValueError('Mission 100 import currently requires an original USA BT3 ISO')
        raw=disc.read(452)
    outer = spans(raw); start, end = outer[1]
    data = unpack_bpe(raw[start:end]); parts = spans(data)
    def part(i):
        a, b = parts[i]; return data[a:b]
    metadata, roster, text = part(9), part(10), part(17)
    if len(metadata) != 5248 or len(roster) != 22016:
        raise ValueError('This disc does not have the verified USA Mission 100 tables')
    labels = [english_label(text[a:b]) for a,b in spans(text)]
    names = labels[216:316]
    if len(names) != 100 or not all(names): raise ValueError('Mission 100 names are incomplete')
    result = []
    checksum = hashlib.sha256(metadata+roster+text).hexdigest()
    for index in range(100):
        meta = struct.unpack_from('<13I', metadata, index*52)
        if tuple(meta[8:13]) != tuple(range(index*5, index*5+5)):
            raise ValueError(f'Mission {index+1} has an unexpected roster reference')
        enemies = []
        for slot in range(5):
            row = struct.unpack_from('<11I', roster, (index*5+slot)*44)
            if row[0] == 999: continue
            if row[0] > 160 or row[1] > 3: raise ValueError('Unknown Mission 100 character/costume')
            enemies.append(dict(id=f'enemy-{slot+1}', team=2, slot=slot+1,
                character=row[0], costume=row[1], source={'native_record': list(row)}))
        # The original mode lets the player choose allies. A starting fighter is
        # an editable placeholder, explicitly not a claimed original hero roster.
        d = dict(schema=missions.SCHEMA, version=1, id=f'mission100-{index+1:03}',game_family='bt3',
            title=f'{index+1:03} - {names[index]}',
            description='Original Mission 100 enemy roster. Choose your own allies. Native restrictions are preserved in source metadata; story events are optional.',
            player_selection=True, fighters=[dict(id='hero', team=1, slot=1, character=0)]+enemies,
            events=[], source=dict(kind='mission100', number=index+1,
                native_metadata=list(meta), table_sha256=checksum,
                restrictions_enforced=False, stage_verified=False))
        result.append(missions.validate(d))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('iso', type=Path)
    p.add_argument('--output', type=Path, default=missions.LIBRARY/'Mission 100')
    args=p.parse_args(); rows=extract(args.iso)
    for row in rows: missions.save(args.output/(row['id']+'.json'), row)
    print(f'Extracted all {len(rows)} original Mission 100 rosters to {args.output}')


if __name__ == '__main__': main()
