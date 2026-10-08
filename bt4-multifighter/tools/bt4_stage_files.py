"""Use authored normal maps where B14 REV2 has empty split-screen files.

Only IDs53/54 are reviewed fallbacks. The normal renderer already supports
the trainer's independent views; this retains the same map and its MAPD,
effects, anchors and boundaries, rather than selecting a different arena.
"""
import struct
from prototype import Assembler,ROOT,elf_reader
from native_map import elf_path

# Unused gap between the selector route and its mailbox; this code has no
# mutable state. Keep the selector's CODE/ROUTE/CONTROL reservations intact.
CODE=0x06C32000
STAGES=(53,54)
SITES=((0x127FA4,0x127FBC),(0x127350,0x127364))


def payload(entry,resume):
    a=Assembler(entry)
    for stage in STAGES:
        a.addiu(1,2,-stage);a.branch(4,1,0,'normal')
    a.addiu(4,2,1622);a.jump(resume)
    a.label('normal');a.addiu(4,2,1523);a.jump(resume)
    return a.finish()


def code_pieces():
    native=elf_reader(elf_path(ROOT))[2]
    pieces=[]
    for index,(site,resume) in enumerate(SITES):
        expected=(0x10000000|((resume-site-4)//4),0x24440656)
        if struct.unpack('<2I',native(site,8))!=expected:
            raise ValueError('BT4 split-stage loader signature changed')
        entry=CODE+index*0x100;code=payload(entry,resume)
        assert len(code)<=0x100
        pieces.extend(((entry,code),(site,struct.pack('<2I',(2<<26)|(entry>>2),0))))
    return pieces
