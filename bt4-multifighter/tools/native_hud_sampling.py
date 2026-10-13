"""Keep native HUD sampling inside each atlas cell when PCSX2 upscales.

The game draws its HUD as textured triangle strips with inclusive UV endpoints.
At more than native resolution those endpoints can sample a neighbouring widget
(for example the black shadow below the reserve health fill). Preserve the native
geometry, filtering and upload path; region-clamp only that battle-HUD bundle,
then restore native CLAMP state before any later menu or world draw.

The wrapper owns a page inside native_hud_style's existing reservation. That kit
is the only installer; unknown hooks or occupied data are left unchanged. Both
texture contexts are supported, including the original mirrored player panels.
"""
import struct

from native_map import A
from prototype import Assembler

HOOK = A(0x225A50)
ORIGINAL = bytes.fromhex('50ffbd27ff00c630')
BASE, SIZE, TRAMP = 0x0717A000, 0x1000, 0x0717AF00
END = BASE + SIZE
HUD_MANAGER = A(0x2FEB48)
SAVED = (4, 5, 6, 7, 8, 16, 17, 18, 31)
FRAME, CLAMP, ACTIVE, V0, V1 = 0x80, 0x48, 0x50, 0x58, 0x60


def emit_packet(a, *, closing):
    a.call(A(0x100878))
    a.move(17, 2)
    # One A+D command. No changed TEX1, TEST, ALPHA, primitive or texture state.
    for offset, value in ((0, 0x8001), (4, 0x10000000), (8, 14), (12, 0), (28, 0)):
        a.li(8, value); a.sw(8, 17, offset)
    if closing:
        a.i(63, 0, 17, 16)  # native 225790 initializes CLAMP to repeat (0)
    else:
        a.i(55, 8, 29, CLAMP); a.i(63, 8, 17, 16)
    # The native draw uses context 2 for any nonzero byte in a2.
    a.lw(8, 29, 16); a.i(12, 8, 8, 255); a.r(0x2B, 8, 0, 8)
    a.addiu(8, 8, 8); a.sw(8, 17, 24)
    a.addiu(4, 17, 32); a.call(A(0x100890))


def payload():
    a = Assembler(BASE)
    a.addiu(29, 29, -FRAME)
    for index, reg in enumerate(SAVED):
        a.i(63, reg, 29, index * 8)
    a.sw(0, 29, ACTIVE)
    a.move(16, 4)
    # Only currently resident battle-HUD atlas records. All other callers use
    # the identical native routine with no extra graphics packets at all.
    a.li(8, HUD_MANAGER); a.lw(8, 8)
    a.li(9, 0x100000); a.r(0x2B, 10, 8, 9); a.branch(5, 10, 0, 'native')
    a.li(9, 0x07FFFFF0); a.r(0x2B, 10, 9, 8); a.branch(5, 10, 0, 'native')
    a.i(12, 9, 8, 3); a.branch(5, 9, 0, 'native')
    a.lw(8, 8); a.branch(5, 8, 5, 'native')
    a.lw(8, 16); a.i(12, 8, 8, 1); a.branch(5, 8, 0, 'native')
    a.i(33, 8, 16, 4); a.i(10, 9, 8, 0); a.branch(5, 9, 0, 'native')
    a.addiu(18, 0, 10)  # WMS=WMT=REGION_CLAMP
    for lo, hi, shift_lo, shift_hi, name in ((16, 18, 4, 14, 'u'), (20, 22, 24, 34, 'v')):
        a.i(33, 8, 16, lo); a.i(33, 9, 16, hi)
        # Source rectangles may be mirrored; order without altering native UVs.
        a.r(0x2A, 10, 8, 9); a.branch(5, 10, 0, name + '_ordered')
        a.move(11, 8); a.move(8, 9); a.move(9, 11)
        a.label(name + '_ordered')
        a.i(10, 10, 8, 0); a.branch(5, 10, 0, 'native')
        a.i(11, 10, 9, 1025); a.branch(4, 10, 0, 'native')
        a.branch(4, 8, 9, 'native')  # zero-area widget: retain native behavior
        a.addiu(9, 9, -1)
        a.r(0x38, 8, 0, 8, shift_lo)
        a.r(0x3C if shift_hi >= 32 else 0x38, 9, 0, 9, shift_hi % 32)
        a.r(0x25, 18, 18, 8); a.r(0x25, 18, 18, 9)
    a.i(63, 18, 29, CLAMP)
    a.addiu(8, 0, 1); a.sw(8, 29, ACTIVE)
    emit_packet(a, closing=False)
    a.label('native')
    for index, reg in enumerate(SAVED[:5]):
        a.i(55, reg, 29, index * 8)
    a.call(TRAMP)
    a.i(63, 2, 29, V0); a.i(63, 3, 29, V1)
    a.lw(8, 29, ACTIVE); a.branch(4, 8, 0, 'return')
    emit_packet(a, closing=True)
    a.label('return')
    a.i(55, 2, 29, V0); a.i(55, 3, 29, V1)
    for index, reg in enumerate(SAVED):
        a.i(55, reg, 29, index * 8)
    a.addiu(29, 29, FRAME); a.jr()
    code = a.finish()
    assert len(code) < TRAMP - BASE, len(code)
    t = Assembler(TRAMP)
    for word in struct.unpack('<2I', ORIGINAL):
        t.emit(word)
    t.jump(HOOK + 8)
    out = bytearray(SIZE)
    out[:len(code)] = code
    out[TRAMP - BASE:TRAMP - BASE + 16] = t.finish()
    return bytes(out)


def redirect():
    a = Assembler(HOOK); a.jump(BASE)
    return a.finish()


def plan(ram, *, reservation_owned=False):
    """Optional kit addition. The caller owns/checks the surrounding style area.

    Re-preparing an older style kit can add this page without rebuilding its
    runtime font or changing its settings. A different draw hook is never
    replaced, and a partly installed or edited page is never adopted.
    """
    empty = dict(pieces=[], patches=[])
    if not reservation_owned or len(ram) < END:
        return dict(empty, skipped='native HUD style reservation is not owned')
    installed, entry = bytes(ram[BASE:END]), bytes(ram[HOOK:HOOK+8])
    data = payload()
    if installed == data and entry == redirect():
        return dict(empty, installed=True)
    if entry != ORIGINAL:
        return dict(empty, skipped='native HUD draw entry changed')
    if any(installed):
        return dict(empty, skipped='native HUD sampling page is occupied')
    return dict(pieces=[(BASE, data)], patches=[(HOOK, redirect())], installed=True)
