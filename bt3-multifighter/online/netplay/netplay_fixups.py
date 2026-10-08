"""Online fixups of the installed mod code (spec 6.7f): fail closed on any byte this kit does not expect.

spectator_feedback.draw (0x07287000) draws the takeover offer ("PRESS SQUARE TO TAKE OVER") of one seat. In the single
view its 'full' path hard-codes seat 0 (`daddu s2, zero, zero`), so online both windows drew player 1's offer and
player 2 never saw its own. The fixup replaces that instruction with a call of a 13-word stub placed in the unused
tail of the same reservation: s2 = netplay_core CONTROL.local_slot (0x07B01010) when the netplay magic is present and
the slot is 0 or 1, else 0 (offline behaviour unchanged).
  * The call's delay slot is the next instruction (`lui t0, 0x0712`, the start of `li t0, modes.CONTROL`); the stub
    uses only t1, t2 and s2, so t0 is intact when the stub returns to the `ori` that completes it. ra is saved by the
    drawing code's own prologue (viewport_hud.save).
  * Drawing only: the offer state the drawing code keeps per seat (spectator_feedback CONTROL 0x0728D000) is not in
    the netplay hash, so each PC drawing its own seat cannot cause a difference.
The drawing code must be byte-identical to the one recorded from Tag Team Mod beta.35 (and found identical in
beta.36 .. beta.42): FEEDBACK_SHA256 over the whole DRAW..PROBE reservation; anything else is refused (TTM-NET-24).
"""
import hashlib
import struct

DRAW, PROBE = 0x07287000, 0x07289000
SEAT_AT = 0x0728729C                    # `daddu s2, zero, zero` after the label 'full'
STUB = 0x07288F00                       # unused tail of the DRAW reservation (the code ends at +0x6EC)
MODES_CONTROL = 0x0712F000              # spectator_takeover.modes.CONTROL (battle_mode_policy)
FEEDBACK_SHA256 = '573a72f64c7e909d9c2a1f8b7a5af8955c31b500e998cce84f70d57e1535f0c5'
USA_FIXED_SHA256 = '7613a7a3f4ea6c1c6f2c6ed3d9e94d11ec7845f2c74a777dae110c08fbf6b662'   # the same after the fixup
SEAT_ZERO = 0x0000902D                  # daddu s2, zero, zero
NC_BASE_HI, NC_CONTROL_LO, NC_LOCAL_SLOT_LO, NC_MAGIC = 0x07B0, 0x1000, 0x1010, 0x4E504331


def expected_draw():
    import spectator_feedback
    code = spectator_feedback.draw(automatic=True, configurable=True)
    return code.ljust(PROBE - DRAW, b'\0')


def fixed_sha256():
    return hashlib.sha256(seat_code(expected_draw())).hexdigest()


def _i(op, rs, rt, imm):
    return (op << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def stub_words():
    return [
        _i(15, 0, 9, NC_BASE_HI),                 # lui   t1, 0x07B0
        _i(35, 9, 10, NC_CONTROL_LO),             # lw    t2, 0x1000(t1)       CONTROL.magic
        _i(15, 0, 18, NC_MAGIC >> 16),            # lui   s2, 0x4E50
        _i(13, 18, 18, NC_MAGIC & 0xFFFF),        # ori   s2, s2, 0x4331
        _i(5, 10, 18, 6),                         # bne   t2, s2, done
        SEAT_ZERO,                                #  daddu s2, zero, zero      (delay slot: the default seat 0)
        _i(35, 9, 10, NC_LOCAL_SLOT_LO),          # lw    t2, 0x1010(t1)       CONTROL.local_slot
        _i(11, 10, 9, 2),                         # sltiu t1, t2, 2
        _i(4, 9, 0, 2),                           # beq   t1, zero, done
        0,                                        #  nop
        (10 << 21) | (18 << 11) | 0x2D,           # daddu s2, t2, zero
        (31 << 21) | 8,                           # done: jr ra
        0,                                        #  nop
    ]


def call_word():
    return (3 << 26) | ((STUB >> 2) & 0x3FFFFFF)  # jal STUB


def seat_address(draw):
    # PAL's larger GS viewport emits extra instructions before this block.
    needle = struct.pack('<3I', SEAT_ZERO, _i(15, 0, 8, MODES_CONTROL >> 16),
                         _i(13, 8, 8, MODES_CONTROL & 0xFFFF))
    at = draw.find(needle)
    if at < 0 or at & 3 or draw.find(needle, at + 1) >= 0:
        raise ValueError('the takeover prompt has no unique seat instruction')
    return DRAW + at


def seat_code(draw):
    """The DRAW reservation with the fixup applied (bytes of DRAW..PROBE)."""
    out = bytearray(draw)
    struct.pack_into('<I', out, seat_address(draw) - DRAW, call_word())
    stub = struct.pack(f'<{len(stub_words())}I', *stub_words())
    out[STUB - DRAW:STUB - DRAW + len(stub)] = stub
    return bytes(out)


def seat_blocks(ram):
    """[(address, expected bytes, new bytes)] of the seat fixup for a capture's RAM (bytes-like, 128 MiB); ValueError
    when the drawing code is not the recorded one."""
    draw = bytes(ram[DRAW:PROBE])
    if draw != expected_draw():
        raise ValueError('the takeover prompt code (spectator_feedback, 0x07287000) is not the one recorded from Tag '
                         'Team Mod for the selected disc')
    seat = seat_address(draw)
    stub_len = 4 * len(stub_words())
    if any(draw[STUB - DRAW:STUB - DRAW + stub_len]) or len(draw.rstrip(b'\0')) > STUB - DRAW:
        raise ValueError('the space for the takeover prompt fixup is in use')
    fixed = seat_code(draw)
    return [(seat, draw[seat - DRAW:seat - DRAW + 4], fixed[seat - DRAW:seat - DRAW + 4]),
            (STUB, draw[STUB - DRAW:STUB - DRAW + stub_len], fixed[STUB - DRAW:STUB - DRAW + stub_len])]
