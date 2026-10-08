"""The selected disc's values that are not native addresses: screen geometry, GS VRAM, disc files, language.

native_map.py translates native addresses and holds the disc identity and platform numbers (HZ, ACTOR_HZ,
DISPLAY_H, Y_ORIGIN, VRAM_SHIFT, FILE_ID, ticks). This module derives from them what the mod's GS overlays,
texture uploads and disc readers need. For the USA adapter every helper returns its input unchanged and every
constant is the USA value, so the USA output stays byte-identical.

European disc (bt3-pal, SLES-54945), read from the European executable (research platform-memory.md 1.1, 3.4):
- The frame is 512 lines, not 448: XYOFFSET Y 1792 (USA 1824), SCISSOR y1 511 (447), frame bottom 2304 (2272).
  The overlays were designed for 512x448; on the European frame their screen rows are stretched by 512/448
  (screen_y), the same 8/7 the European conversion applies to its own 2D layout.
- GS VRAM: the 512-line frame, back and Z buffers end at block 0x3000 (USA 0x2A00) and every native texture
  bank moves +0x600 blocks (tbp). The mod's own texture zones that share the native layout move with them.
- Disc files: the localised volumes insert files (native_map.FILE_ID); the English text set is file 455.

Japanese disc (bt3-jpn, SLPS-25815 Sparking! Meteor), read from the Japanese executable and disc: the USA frame,
VRAM and timing (NTSC, 448 lines, 60 Hz), but
- its own volumes PZS3JP0-2 (native_map.FILE_ID) with a Japanese-only text set (file 450): the mod takes the
  fighter names from bt3_english_names.json instead (TEXT_LANGUAGE 'ja');
- its menus accept with Circle and go back with Cross (MENU_ACCEPT / MENU_BACK below), and its main-menu title
  starts with the katakana Dragon Ball;
- its game font has the ASCII letters but no accented Latin ones (NATIVE_FONT_ASCII).
"""
from native_map import PAL, JPN, SERIAL, DISPLAY_H, Y_ORIGIN, VRAM_SHIFT, FILE_ID

NTSC_H = 448                         # the frame height every overlay was authored for
SCREEN_H = DISPLAY_H                 # this disc's frame height (448 / 512)
SCISSOR_Y1 = DISPLAY_H - 1           # last visible row (447 / 511)
FRAME_BOTTOM = 2048 + DISPLAY_H//2   # native "bottom" in pixels: 0x8E00/16 (2272) / 0x9000/16 (2304)

# screen_y on the European frame: (y * 18725) >> 14 is y*512/448 (8/7) to within 0.01 px over the frame; guest
# code computes exactly the same value (emit_window_y), so host-built and guest-built geometry agree.
Y_MUL, Y_SHIFT = 18725, 14


def screen_y(y):
    """A row of the 512x448 design frame -> this disc's screen row (USA: unchanged; European: *512/448)."""
    if not PAL:
        return y
    if type(y) is not int:
        return y * DISPLAY_H / NTSC_H
    return (y * Y_MUL) >> Y_SHIFT


def window_y(y):
    """GS window Y (pixels) of design row y: Y_ORIGIN + screen_y(y)."""
    return Y_ORIGIN + screen_y(y)


def xyz2_y(y):
    """The XYZ2 Y field (1/16 px) of design row y."""
    return window_y(y) * 16


def emit_window_y(a, rd, ry, shift):
    """Guest code: rd = (Y_ORIGIN + screen_y(ry)) << shift, for a design row in register ry.

    USA: `addiu rd, ry, 1824; sll rd, rd, shift`, exactly the words the emitters always wrote.
    European: addiu rd, zero, Y_MUL; mult rd, ry, rd (EE: rd = lo); sra rd, rd, Y_SHIFT; addiu rd, rd, 1792;
    sll rd, rd, shift. rd must differ from ry; LO/HI are clobbered.
    """
    if not PAL:
        a.addiu(rd, ry, Y_ORIGIN); a.r(0, rd, 0, rd, shift)
        return
    if rd == ry:
        raise ValueError('emit_window_y needs a destination other than its source')
    a.addiu(rd, 0, Y_MUL); a.r(24, rd, ry, rd); a.r(3, rd, 0, rd, Y_SHIFT); a.addiu(rd, rd, Y_ORIGIN)
    if shift:
        a.r(0, rd, 0, rd, shift)


def tbp(block):
    """A GS block address of the native USA VRAM layout -> this disc's (European: +0x600)."""
    return block + VRAM_SHIFT


def native_count(usa, pal):
    """A native frame or tick count the mod copies or compares: the USA executable's value, or the European
    executable's (each caller cites where it was read in pal.elf)."""
    return pal if PAL else usa


# ---- disc -------------------------------------------------------------------------------------------------
ISO_NAME = ('Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) (Versus Fighting) (ISO) (PS2).iso'
            if PAL else 'Dragon Ball Z - Sparking! Meteor (Japan).iso' if JPN
            else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
DISC_REGION = 'EU' if PAL else 'JP' if JPN else 'US'
AFS1 = f'/DATA/PZS3{DISC_REGION}1.AFS;1'
ENGLISH_TEXT = FILE_ID(451)          # names, forms and portraits (package 1 entries 29..31): 451 / 455 / 450
# The language of that text set's names and forms. The Japanese set has kanji/kana names the mod's fonts cannot
# draw: its English names come from bt3_english_names.json (english_names), its portraits from the disc.
TEXT_LANGUAGE = 'ja' if JPN else 'en'
ENGLISH_NAMES = 'bt3_english_names.json'


def english_names():
    """[(base name, form)] of the 161 BT3 fighters in English (bt3_english_names.json, made by
    release_tools/build_english_names.py from the USA disc's text set; the roster order and IDs are the same on
    every BT3 disc)."""
    import json
    from pathlib import Path
    doc = json.loads((Path(__file__).resolve().parent / ENGLISH_NAMES).read_text(encoding='utf-8'))
    rows = [(row['base_name'], row['form']) for row in doc['characters']]
    if len(rows) != 161 or not all(base for base, _ in rows):
        raise ValueError(f'{ENGLISH_NAMES} does not list the 161 BT3 fighters')
    return rows


def open_disc(iso_path):
    """iso_compatibility.disc.Disc for the selected disc, refusing the other region's ISO."""
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    from iso_compatibility.disc import Disc, FormatError
    disc = Disc(iso_path)
    if disc.kind != 'bt3-afs' or disc.region != DISC_REGION:
        disc.close()
        raise FormatError(f'{Path(iso_path).name} is not the {SERIAL} disc these tools are set up for.')
    return disc


def read_disc_file(iso_path, usa_file_id):
    """One disc file by its USA global ID (translated with FILE_ID) from the selected disc's ISO."""
    with open_disc(iso_path) as disc:
        return disc.read(FILE_ID(usa_file_id))


# ---- language ---------------------------------------------------------------------------------------------
# The first string of the main-menu text table (DBT, package 450/454 part 27). The European disc shows the
# console's language: English, German and Italian start 'Dragon Ball Z', French too, Spanish with an inverted exclamation mark.
# 16 bytes (8 UTF-16 units) read at the table's first string: the only prefixes the five languages use. The
# Japanese table starts with the katakana Dragon Ball (FF FE C9 30 E9 30 B4 30 F3 30 DC 30 FC 30 EB 30).
MAIN_MENU_TITLES = (('\ufeffDragon ', '\ufeff\u00a1Dragon') if PAL else
                    ('\ufeff\u30c9\u30e9\u30b4\u30f3\u30dc\u30fc\u30eb',) if JPN else ('\ufeffDragon ',))
MAIN_MENU_PREFIXES = tuple(title.encode('utf-16le') for title in MAIN_MENU_TITLES)
# The game font draws the mod's main-menu descriptions (native_menu_assets.dbt). The Japanese font has the printable
# ASCII letters but none of the accented Latin ones the Spanish texts use, so they are folded to ASCII there.
NATIVE_FONT_ASCII = JPN


# ---- menu buttons -----------------------------------------------------------------------------------------
# The native menus read a decision word per pad (pad record +0x18C/+0x190, translated from the raw pad by 2574F0:
# Circle 0x2000 -> 0x100, Cross 0x4000 -> 0x200, Triangle 0x1000 -> 0x400). The USA and European menus accept with
# Cross (0x200) and go back with Triangle (0x400); the Japanese menus accept with Circle (0x100) and go back with
# Cross (0x200): 207 + 33 decide and 108 + 3 cancel tests of the overlay and the executable moved that way. The
# mod's pages inside the native main menu follow the disc: RAW_ACCEPT / RAW_BACK are the raw pad bits
# (+0x148/+0x150) of the same two buttons.
MENU_ACCEPT, MENU_BACK = (0x100, 0x200) if JPN else (0x200, 0x400)
RAW_ACCEPT, RAW_BACK = (0x2000, 0x4000) if JPN else (0x4000, 0x1000)
