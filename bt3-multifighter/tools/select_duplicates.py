"""Let a team pick the same character more than once on the native select screen.

The team select screen is not ELF code - it lives in cdrom0:\\BIN\\DBZP.BIN,
loaded at 0x334C00 - and its same-team rule is one predicate there,
sub_348E88(side, character). For every member already on the team it calls
the ELF routine sub_261650(candidate, member) and refuses the pick when that
says the two conflict: equal IDs, or either one among the other's related
forms (so Goku and Super Saiyan Goku also block each other). The same predicate
dims the portrait, refuses the pick and drives the random-pick retry.

sub_261650 already has a "never conflicts" exit. Saibamen (79), Cell Jr. (109)
and Meta-Cooler (128) branch straight to `jr ra / move v0, zero` at 0x261690,
which is why the game has always allowed repeats of those three. This patch
puts exactly that sequence at the routine's entry, so every character is
treated the way the game already treats those three.

Why the ELF and not the overlay. DBZP.BIN is re-read from disc before every
menu session (`while (1) { sub_100280(0); 0x336A90(0); sub_12BD10(); }`), and
this mod restores savestates constantly - menu checkpoints, prepared matches,
rematches - so a patch in the overlay would be wiped by a reload or rolled back
by a restore that lands inside a menu session. ELF code is never reloaded, and
the loading-screen cheat file re-asserts every word each vsync, so this holds
through all of that.

sub_261650 has exactly two callers, both select-screen predicates: 0x348F04 in
the team select (scene 0x28) and 0x36E168 in the single-team select used by
scenes 0x0D-0x1E. Nothing in battle calls it and nothing reaches it through a
pointer. Repeats are therefore allowed on every native team-picking screen,
which is the behaviour asked for, and nowhere else.
"""
from native_map import A, elf_path
import struct

from prototype import ROOT, elf_reader

CONFLICT = A(0x261650)
ORIGINAL_WORDS = (0x0080402D, 0x2404004F)   # move t0,a0 ; addiu a0,zero,0x4F
PATCH_WORDS = (0x03E00008, 0x0000102D)      # jr ra ; move v0,zero
# The routine's own exemption exit, which the patch copies verbatim.
EXEMPT_EXIT = A(0x261690)
EXEMPT = (79, 109, 128)                     # Saibamen, Cell Jr., Meta-Cooler
CALLERS = (A(0x348F04), A(0x36E168))              # both inside DBZP.BIN select screens


def code_pieces():
    """Boot-resident piece for the loading-screen cheat file."""
    native = elf_reader(elf_path(ROOT))[2]
    assert native(CONFLICT, 8) == struct.pack('<2I', *ORIGINAL_WORDS), \
        'The select-screen conflict test at 0x261650 changed'
    assert native(EXEMPT_EXIT, 8) == struct.pack('<2I', *PATCH_WORDS), \
        'The exemption exit at 0x261690 changed'
    return [(CONFLICT, struct.pack('<2I', *PATCH_WORDS))]


def state(ram):
    """'native', 'unlocked', or None when the words are neither."""
    words = struct.unpack_from('<2I', ram, CONFLICT)
    if words == ORIGINAL_WORDS: return 'native'
    if words == PATCH_WORDS: return 'unlocked'
    return None
