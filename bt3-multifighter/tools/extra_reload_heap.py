"""Bounded, read-only heap admission for an ordinary extra form.

The bound covers three files at the per-file ceiling and every staging
allocation, in one contiguous free block. It makes no allocation/reservation.
Native first-fit is called only after validating the complete bounded heap chain.
"""
from native_map import A, elf_path
from prototype import Assembler, ROOT, elf_reader
import battle_mode_policy as policy

ENTRY,END=0x07664000,0x07665000
# Why the last refusal happened, so a transformation that never starts can be
# told apart from one that was never asked for: 1 the extended arena bounds
# words do not describe the heap this build was compiled for, 2 the bounded
# block chain did not validate, 3 native first-fit found no free block at all,
# 4 the block it found did not survive validation.
REASON=ENTRY+0xF00
START,STOP=0x02000000,0x06000000
MAX_BLOCKS=4096
# Per-file ceiling of the budget. All 349 real character/costume bundles were
# measured: the largest file is 1,443,840 bytes (an animation bank), the largest
# main 843,776 and the largest whole bundle 2,762,752. Two MiB a file keeps a
# wide margin, damaged mains included. The old ceiling was the loader's own
# 8 MiB file limit, a 24 MiB demand: a ten-fighter match leaves about 30 MiB of
# heap1 and each completed form keeps its old buffers, so extras could transform
# only about twice a match. Three-a-side installs carry that old budget.
FILE_CEILING,LEGACY_FILE_CEILING=0x200000,0x800000
STAGING=((0x30000,64),(192,32),(0x6E10,64),(0x6E10,64))


def allocations():
    """The budgeted allocations for the build being emitted."""
    legacy=policy.emitted_capacity()==policy.LEGACY_TEAM_CAPACITY
    return ((LEGACY_FILE_CEILING if legacy else FILE_CEILING,64),)*3+STAGING


def need():
    return sum(size+alignment+36 for size,alignment in allocations())


ALLOCATIONS=((FILE_CEILING,64),)*3+STAGING
NEED=sum(size+alignment+36 for size,alignment in ALLOCATIONS)
SAVED=(1,)+tuple(range(3,29))+(30,31)
NATIVE=elf_reader(elf_path(ROOT))[2]
HELPERS=((A(0x255078),0x80),(A(0x2550F8),0x70),(A(0x254F48),0x38))


def code():
    a=Assembler(ENTRY);a.addiu(29,29,-0x100)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)
    for p,v in ((A(0x2FF084),START),(A(0x2FF08C),STOP)):
        a.li(8,p);a.lw(8,8);a.li(9,v);a.branch(5,8,9,'reject_bounds')
    a.li(16,START);a.li(17,STOP);a.li(18,MAX_BLOCKS)
    a.label('walk');a.r(0x23,9,17,16);a.i(11,9,9,32);a.branch(5,9,0,'reject_walk')
    a.lw(8,16);a.li(9,0x53484254);a.branch(5,8,9,'reject_walk')
    a.lw(19,16,16);a.i(11,8,19,32);a.branch(5,8,0,'reject_walk')
    a.i(12,8,19,3);a.branch(5,8,0,'reject_walk')
    a.r(0x23,8,17,16);a.r(0x2B,8,8,19);a.branch(5,8,0,'reject_walk')
    a.r(0x21,20,16,19);a.lw(8,20,-4);a.branch(5,8,19,'reject_walk')
    a.lw(8,16,4);a.i(11,9,8,2);a.branch(4,9,0,'reject_walk');a.branch(4,8,0,'free')
    a.lw(8,16,20);a.addiu(9,16,32);a.r(0x2B,9,8,9);a.branch(5,9,0,'reject_walk')
    a.addiu(9,20,-4);a.r(0x2B,9,9,8);a.branch(5,9,0,'reject_walk')
    a.lw(9,16,24);a.r(0x23,10,20,8);a.addiu(10,10,-4)
    a.r(0x2B,9,10,9);a.branch(5,9,0,'reject_walk');a.jump('next')
    a.label('free');a.lw(8,16,24);a.addiu(9,19,-32);a.branch(5,8,9,'reject_walk')
    a.label('next');a.branch(4,20,17,'find');a.addiu(18,18,-1);a.branch(4,18,0,'reject_walk')
    a.move(16,20);a.jump('walk')
    a.label('find');a.li(4,need());a.addiu(5,0,1);a.call(A(0x255078))
    a.branch(4,2,0,'reject_empty')
    a.li(8,START);a.r(0x2B,8,2,8);a.branch(5,8,0,'reject_find')
    a.li(8,STOP-32);a.r(0x2B,8,8,2);a.branch(5,8,0,'reject_find')
    a.lw(8,2,4);a.branch(5,8,0,'reject_find');a.lw(8,2,16);a.li(9,need())
    a.r(0x2B,9,8,9);a.branch(5,9,0,'reject_find')
    a.li(9,STOP);a.r(0x23,9,9,2);a.r(0x2B,9,9,8);a.branch(5,9,0,'reject_find')
    a.addiu(2,0,1);a.jump('done')
    for name,reason in (('reject_bounds',1),('reject_walk',2),('reject_empty',3),('reject_find',4)):
        a.label(name);a.li(8,REASON);a.addiu(9,0,reason);a.sw(9,8);a.move(2,0);a.jump('done')
    a.label('done')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x100);a.jr();result=a.finish();assert len(result)<END-ENTRY;return result


def validate_native(ram):
    for p,n in HELPERS:
        if ram[p:p+n]!=NATIVE(p,n):raise ValueError(f'Native heap admission helper changed:{p:08X}')


def pieces():return [(ENTRY,code())]
