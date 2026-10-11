"""Choose an actual fighter's sustained beam pose for cooperative effects.

Native 203C40 maps special subtype 2 (211050 / parameters[316 + slot])
to charged beam actions 271..273. Other subtypes include spheres, volleys,
rushes and explosions; their firing frame need not resemble a beam at all.
The native clash handler's own generic 364 is the safe presentation fallback.
This does not change a special, its slot, or any native clash participant.
"""

GENERIC = 364
SLOTS = (2, 3, 4)


def candidates(parameters):
    """Ordered (own clip, source slot) pairs; slot 0 denotes generic clash."""
    if len(parameters) != 640:
        raise ValueError('Expected the complete native special metadata')
    charged = tuple((196 + 34 * slot, slot) for slot in SLOTS
                    if parameters[316 + slot] == 2 and parameters[313 + slot] != 1)
    # Arale's native type6 mouth beam has no generic364 bank entry. The native
    # clash handler already uses its own264; retain that fallback only for this
    # reviewed beam family, never turn a missing generic into a rush pose.
    fallback = ((264, 2),) if parameters[315] == 6 else ()
    return charged + ((GENERIC, 0),) + fallback


def emit_select(a, model, parameters, prefix):
    """Validated model/640-byte params -> v0 clip (-1 absent), v1 source slot.

    Clobbers t0..t3 and v0/v1 only; no calls, writes, or actor-state changes.
    Caller must reject native 1C4650 paired-retarget flags before playing.
    The model/parameter registers must be outside this scratch set.
    """
    assert model not in (2, 3, 8, 9, 10, 11)
    assert parameters not in (2, 3, 8, 9, 10, 11)
    def pointer(reg, fail):
        a.i(12, 9, reg, 3); a.branch(5, 9, 0, fail)
        a.li(10, 0x100000); a.r(0x2B, 9, reg, 10); a.branch(5, 9, 0, fail)
        a.li(10, 0x7FFFFF8); a.r(0x2B, 9, 10, reg); a.branch(5, 9, 0, fail)
        # Native BPE header starts with decoded bytes; the pose scratch is48KiB.
        a.lw(9, reg); a.addiu(9, 9, -32); a.li(10, 49152-32+1); a.r(0x2B, 9, 9, 10)
        a.branch(4, 9, 0, fail)
    # Try the three native beam slots without duplicating the bounded bank
    # check. Empty package entries still have a valid nonzero runtime pointer.
    a.li(2, 264); a.li(3, 2)
    a.label(f'{prefix}_slot')
    a.r(0x21, 11, parameters, 3)
    a.i(36, 8, 11, 316); a.li(9, 2); a.branch(5, 8, 9, f'{prefix}_next')
    a.i(36, 8, 11, 313); a.li(9, 1); a.branch(4, 8, 9, f'{prefix}_next')
    a.r(0, 11, 0, 2, 2); a.r(0x21, 11, model, 11); a.lw(11, 11, 192)
    pointer(11, f'{prefix}_next'); a.jump(f'{prefix}_done')
    a.label(f'{prefix}_next'); a.addiu(2, 2, 34); a.addiu(3, 3, 1)
    a.i(11, 8, 3, 5); a.branch(5, 8, 0, f'{prefix}_slot')
    a.lw(11, model, 192 + 4 * GENERIC); pointer(11, f'{prefix}_mouth')
    a.li(2, GENERIC); a.move(3, 0); a.jump(f'{prefix}_done')
    a.label(f'{prefix}_mouth')
    a.i(36,8,parameters,315);a.li(9,6);a.branch(5,8,9,f'{prefix}_absent')
    a.lw(11,model,192+4*264);pointer(11,f'{prefix}_absent')
    a.li(2,264);a.li(3,2);a.jump(f'{prefix}_done')
    a.label(f'{prefix}_absent'); a.li(2, -1); a.move(3, 0)
    a.label(f'{prefix}_done')
