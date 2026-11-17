"""Team identity on screen in a Team Battle with three to five teams.

Every view shows a chip with its fighter's team ("TEAM 3" in the team's colour) beside the status panel: one full
view also names the team of the fighter it is locked on to, at the opposite panel. When the match is decided the
winning team is named in large letters ("TEAM 3 WINS").

A per-view HUD extension (viewport_hud.HUD_EXTENSION_MODULES): the team table itself is its control word, so it is
drawn only in such a match. Text goes through the kill feed's font; the banner uses a three-times scaled copy of
the feed's text routine. Nothing here exists in any other match.
"""
import struct

import battle_mode_policy as policy
import fresh_team_camera as camera
import fresh_team_combat as core
import guest_killfeed as feed
import localization
import spectator_takeover as takeover
import tag_rush_hud as meter
import viewport_hud as hud
from native_map import A
from prototype import Assembler
from regional import Y_ORIGIN, screen_y

# The free part of the battle-mode reservation (0x07121000 holds the time-over rule).
CODE, BIG_TEXT, DATA, END = 0x07122000, 0x07123000, 0x07123800, 0x07124000
SCALE = 3                      # banner glyphs: 15 x 21 pixels, 18 pixels per character
RECORD = 32                    # a string record: 28 bytes of text, then its left edge on the 512-pixel screen
CHIP, BANNER = 'TEAM {team}', 'TEAM {team} WINS'
CHIP_WIDTH = 48                # room kept for a chip at the right-hand panel ("EQUIPO 5" is 8 characters)
CHIP_DROP = 16                 # rows the chip moves down while the tag meter is shown in its place
BANNER_ROW = 150
REGS = (*range(16, 24), 31)


def big_text_code():
    """a0 string, a1/a2 GS 12.4 screen origin, a3 ABGR: guest_killfeed.text_code, every unit times SCALE."""
    def units(reg):
        a.r(0, 14, 0, reg, 5); a.r(0, reg, 0, reg, 4); a.r(0x21, reg, reg, 14)        # * 48
    step = 16*SCALE
    a = Assembler(BIG_TEXT)
    a.addiu(29, 29, -0x60)
    for i, r in enumerate(REGS): a.i(63, r, 29, i*8)
    for d, s in zip(range(16, 20), range(4, 8)): a.move(d, s)
    a.call(A(0x100878)); a.move(20, 2); a.li(8, feed.TEMPLATE)
    for off in range(0, 112, 4): a.lw(9, 8, off); a.sw(9, 20, off)
    a.sw(19, 20, 80); a.addiu(21, 20, 112); a.move(22, 0); a.move(23, 0)
    a.label('char'); a.i(36, 8, 16, 0); a.branch(4, 8, 0, 'finish')
    a.i(12, 8, 8, 127); a.r(0, 8, 0, 8, 7); a.li(9, feed.FONT); a.r(0x2D, 8, 8, 9); a.lw(9, 8)
    a.addiu(8, 8, 4)
    a.label('run'); a.branch(4, 9, 0, 'next'); a.lw(10, 8)
    a.i(12, 11, 10, 255); units(11); a.r(0x2D, 11, 11, 17)
    a.r(3, 12, 0, 10, 8); a.i(12, 12, 12, 255); units(12); a.r(0x2D, 12, 12, 18)
    a.r(3, 13, 0, 10, 16); units(13); a.r(0x2D, 13, 13, 11); a.addiu(14, 12, step)
    a.r(0, 12, 0, 12, 16); a.r(0x25, 11, 11, 12); a.sw(11, 21); a.sw(0, 21, 4)
    a.r(0, 14, 0, 14, 16); a.r(0x25, 13, 13, 14); a.sw(13, 21, 8); a.sw(0, 21, 12)
    a.addiu(21, 21, 16); a.addiu(22, 22, 1); a.addiu(8, 8, 4); a.addiu(9, 9, -1); a.jump('run')
    a.label('next'); a.addiu(16, 16, 1); a.addiu(17, 17, 6*step); a.addiu(23, 23, 1)
    a.i(11, 8, 23, 28); a.branch(5, 8, 0, 'char')
    a.label('finish'); a.i(13, 8, 22, 0x8000); a.sw(8, 20, 96); a.move(4, 21); a.call(A(0x100890))
    for i, r in enumerate(REGS): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x60); a.jr()
    data = a.finish(); assert BIG_TEXT+len(data) <= DATA; return data


def data():
    """Five chip records, then five banner records (text in the battle's language, banner centred)."""
    out = bytearray()
    for template, scale in ((CHIP, 1), (BANNER, SCALE)):
        for team in range(policy.MAX_TEAMS):
            text = localization.guest(template.format(team=team+1))
            if len(text) > 27: raise ValueError('Team caption too long for its record')
            left = max(4, 256-len(text)*6*scale//2)
            out += text.ljust(28, b'\0')+struct.pack('<I', left)
    return bytes(out)


def _team(a, out, index, fail):
    """out = team of physical index (0..4), else fail. t0/t1."""
    a.i(11, 8, index, 12); a.branch(4, 8, 0, fail)
    a.li(8, policy.SQUAD+policy.SQUAD_FIELDS['team_of']); a.r(0x21, 8, 8, index); a.i(36, out, 8, 0)
    a.i(11, 8, out, policy.MAX_TEAMS); a.branch(4, 8, 0, fail)


def _text(a, routine, record, x, y):
    """Draw the record (register) at pixel x, y (registers) in its team's colour (s6 holds the team)."""
    a.move(4, record); a.addiu(5, x, 1792); a.r(0, 5, 0, 5, 4); a.addiu(6, y, Y_ORIGIN); a.r(0, 6, 0, 6, 4)
    a.li(8, policy.SQUAD+policy.SQUAD_FIELDS['colors']); a.r(0, 9, 0, 22, 2); a.r(0x21, 8, 8, 9); a.lw(7, 8)
    a.call(routine)


def draw_code():
    """One HUD pass: this view's chip (and the locked-on fighter's chip in one full view), then the banner."""
    F = policy.SQUAD_FIELDS
    a = Assembler(CODE); a.addiu(29, 29, -0x60)
    for i, r in enumerate(REGS): a.i(63, r, 29, i*8)
    a.li(16, policy.SQUAD); a.lw(8, 16); a.li(9, policy.SQUAD_MAGIC); a.branch(5, 8, 9, 'done')
    a.lw(8, 16, F['manager']); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'done')
    a.lw(17, 28, -22176); takeover.pointer(a, 17, 832, 'done')
    # s2 view index (-1: one full view), s3 subject, s4 left edge, s5 top edge of this pass
    a.lw(20, 17, 512); a.lw(21, 17, 520)
    if policy.squad_feature('tag_attacks'):
        # The tag meter's label goes where the chip stands: with tag attacks installed in this match and the meter
        # shown, every chip of this pass is drawn CHIP_DROP rows lower.
        a.li(8, meter.SHOW); a.lw(8, 8); a.branch(4, 8, 0, 'chip_row')
        a.li(8, meter.CONTROL); a.lw(9, 8); a.li(10, meter.MAGIC); a.branch(5, 9, 10, 'chip_row')
        a.lw(9, 8, 4); a.lw(10, 28, -22364); a.branch(5, 9, 10, 'chip_row')
        for off in (12, 60):
            a.lw(9, 8, off); a.addiu(10, 0, 1); a.branch(5, 9, 10, 'chip_row')
        a.addiu(21, 21, screen_y(CHIP_DROP))
        a.label('chip_row')
    a.call(hud.ACTIVE); a.branch(4, 2, 0, 'full')
    a.move(18, 0); a.li(19, hud.VIEWS)
    a.label('view')
    a.lw(8, 19); a.branch(4, 8, 0, 'next')
    for native, descriptor in ((512, 4), (516, 8), (520, 12), (524, 16)):
        a.lw(8, 17, native); a.lw(9, 19, descriptor); a.branch(5, 8, 9, 'next')
    a.lw(11, 19, 20); takeover.pointer(a, 11, 4, 'banner'); a.lw(19, 11); a.jump('chip')   # pointer() uses t0/t1
    a.label('next'); a.addiu(18, 18, 1); a.addiu(19, 19, hud.VIEW_STRIDE)
    a.addiu(8, 0, hud.MAX_VIEWS); a.branch(5, 18, 8, 'view'); a.jump('banner')
    a.label('full'); a.addiu(18, 0, -1); a.li(8, camera.SUCCESSOR_CONTROL); a.lw(19, 8, 8)
    a.label('chip')
    _team(a, 22, 19, 'banner')
    a.r(0, 8, 0, 22, 5); a.li(23, DATA); a.r(0x21, 23, 23, 8)
    a.branch(1, 18, 0, 'full_chip')                                  # bltz: one full view
    # a split view: beside its own panel, mirrored in the right-hand column
    a.addiu(5, 20, meter.SPLIT_X); a.i(12, 8, 18, 1); a.branch(4, 8, 0, 'split_ready')
    a.lw(5, 17, 516); a.addiu(5, 5, -meter.SPLIT_X-CHIP_WIDTH)
    a.label('split_ready'); a.addiu(6, 21, screen_y(meter.SPLIT_Y))
    a.move(9, 5); a.move(10, 6); _text(a, feed.TEXT, 23, 9, 10); a.jump('banner')
    a.label('full_chip')
    a.addiu(9, 20, meter.FULL_X); a.addiu(10, 21, screen_y(meter.FULL_LABEL)); _text(a, feed.TEXT, 23, 9, 10)
    # the fighter this view is locked on to: its team at the opposite panel
    a.i(11, 8, 19, 12); a.branch(4, 8, 0, 'banner')
    a.li(8, core.TABLE); a.r(0, 9, 0, 19, 2); a.r(0x21, 8, 8, 9); a.lw(19, 8)
    _team(a, 22, 19, 'banner')
    a.r(0, 8, 0, 22, 5); a.li(23, DATA); a.r(0x21, 23, 23, 8)
    a.lw(9, 17, 516); a.addiu(9, 9, -meter.FULL_X-CHIP_WIDTH); a.addiu(10, 21, screen_y(meter.FULL_LABEL))
    _text(a, feed.TEXT, 23, 9, 10)
    a.label('banner')
    a.lw(22, 16, F['winner_team']); a.i(11, 8, 22, policy.MAX_TEAMS); a.branch(4, 8, 0, 'done')
    a.r(0, 8, 0, 22, 5); a.li(23, DATA+RECORD*policy.MAX_TEAMS); a.r(0x21, 23, 23, 8)
    a.lw(9, 23, 28); a.addiu(10, 0, screen_y(BANNER_ROW)); _text(a, BIG_TEXT, 23, 9, 10)
    a.label('done')
    for i, r in enumerate(REGS): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x60); a.jr()
    data_ = a.finish(); assert CODE+len(data_) <= BIG_TEXT; return data_


def pieces():
    return [(CODE, draw_code()), (BIG_TEXT, big_text_code()), (DATA, data())]


def entry():
    return (policy.SQUAD, policy.SQUAD_MAGIC, CODE)


def hud_extension(ram):
    """viewport_hud per-view extension entry while the team HUD is installed, else None."""
    if len(ram) < END or struct.unpack_from('<I', ram, policy.SQUAD)[0] != policy.SQUAD_MAGIC: return None
    if bytes(ram[CODE:CODE+16]) != draw_code()[:16]: return None
    return entry()


def hud_patch(ram):
    """Add the draw entry to the installed one/two-view wrapper or three/four-view renderer (known bytes only)."""
    if struct.unpack_from('<I', ram, hud.CONTROL)[0] != hud.MAGIC: return []
    import quad_viewports as quad
    mine = entry()
    before = hud.hud_extensions(ram)
    without = tuple(e for e in before if e != mine)
    candidates = (before, without) if before != without else (without,)
    after = without+(mine,)
    previous = struct.unpack_from('<I', ram, hud.CONTROL+16)[0]
    if struct.unpack_from('<I', ram, quad.CONTROL)[0] == quad.MAGIC:
        address, limit = quad.DRAW, quad.SELECT
        for extensions in candidates:
            old = quad.draw(extensions)
            if ram[address:address+len(old)] == old: break
        else: raise ValueError('Unknown per-view HUD renderer for the team HUD')
        new = quad.draw(after)
    else:
        address, limit = hud.CODE, hud.ACTIVE
        for extensions, kwargs in ((e, k) for e in candidates for k in (dict(deferred=True), dict())):
            old = hud.wrapper(previous, extensions=extensions, **kwargs)
            if ram[address:address+len(old)] == old:
                new = hud.wrapper(previous, extensions=after, **kwargs); break
        else: raise ValueError('Unknown viewport HUD wrapper for the team HUD')
    if old == new: return []
    if len(new) > limit-address: raise ValueError('The team HUD exceeds the HUD drawing reservation')
    if any(ram[address+len(old):address+len(new)]): raise ValueError('Team HUD extension tail occupied')
    return [(address, old, new)]


@policy.matching_install
def build_memory(ram, source='<prepared>'):
    """Install the team HUD in a match of three to five teams (a no-op anywhere else and when already installed)."""
    if len(ram) != 0x8000000: raise ValueError('Requires 128MiB captured EE RAM')
    if not policy.squad_feature('hud') or struct.unpack_from('<I', ram, policy.SQUAD)[0] != policy.SQUAD_MAGIC:
        return dict(source=str(source), blocks=[], status='NO TEAM HUD IN THIS MATCH')
    blocks = []
    virtual = bytearray(ram)
    for address, new in pieces():
        old = bytes(ram[address:address+len(new)])
        if old == new: continue
        if any(old): raise ValueError(f'Team HUD reservation occupied:{address:08X}')
        blocks.append(dict(address=address, expected_hex=old.hex(), data_hex=new.hex()))
        virtual[address:address+len(new)] = new
    for address, old, new in hud_patch(virtual):
        current = bytes(ram[address:address+len(new)])
        blocks.append(dict(address=address, expected_hex=current.hex(), data_hex=new.hex()))
    return dict(source=str(source), blocks=blocks, entry=CODE)
