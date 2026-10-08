"""Read the volume index from this ISO, never from a stale extracted BIN."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
import game_profile
ISO=game_profile.source_iso(ROOT.parent/'games/SLUS_219.78.DBZBT4B14REV2ENG.iso')
sys.path.insert(0,str(ROOT.parent))
from iso_compatibility.disc import Disc as IndexedDisc


class Disc(IndexedDisc):
    def __init__(self,path=ISO):
        super().__init__(path)
        if self.kind!='bt4-indexed':
            self.close()
            raise ValueError('Expected a BT4 indexed disc')
