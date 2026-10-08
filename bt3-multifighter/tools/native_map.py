"""The game's native addresses and identity for the selected disc: USA (SLUS-21678), European (SLES-54945) or
Japanese (SLPS-25815, Sparking! Meteor).

The tools are written against the USA executable. Every native address in them goes through A(), every
gp-relative offset through GPO() (prototype.Assembler and ai_shadow.Assembler do that themselves for base
register 28), every disc file ID through FILE_ID() and every native actor-flag number through FLAG(). For the
USA adapter all of them return their input unchanged, so the USA output stays byte-identical.

For the European ('bt3-pal') and Japanese ('bt3-jpn') adapters they look the USA value up in pal_native_map.json
or jpn_native_map.json, which release_tools/build_pal_map.py (--region pal / jpn) generates from that disc's
executable and DBZP.BIN (plus reviewed values in release_tools/pal_reviewed.json / jpn_reviewed.json). An address
the table does not list raises NativeMapError: a translated build never falls back to a USA address.

Adapter: the game disc chosen for this installation (game_profile: the installed disc, or the disc chosen in
Mod settings > Game disc; else player-install.json), else 'bt3-usa'. In a developer tree the TAGTEAM_ADAPTER
environment variable overrides it; in a player installation it must name the chosen disc's adapter. It is read
once, at import; tests that need another disc's values run in a subprocess (or reload this module) with
TAGTEAM_ADAPTER=bt3-pal or bt3-jpn.

Flags: PAL is the European 50 Hz / 512-line disc (its video values), JPN the Japanese disc, TRANSLATED any disc
whose addresses come from a table (bt3-pal, bt3-jpn). The Japanese disc keeps the USA video values (NTSC, 60 Hz,
448 lines) and the USA $gp.
"""
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Adapters whose executable keeps the USA BT3 address space (identity translation).
IDENTITY_ADAPTERS = ('bt3-usa', 'bt4-b14-rev2-eng')
USA_GP, PAL_GP, JPN_GP = 0x304270, 0x305370, 0x304270
# One record per disc. table: the generated address table (None: identity); gp_key: its gp field for this disc;
# file_ids: (first, last or None, shift) ranges of USA global AFS file IDs (an ID outside every range has no reviewed
# file on that disc); flags: (first, last, shift) ranges of native actor-flag numbers (None: identity).
DISCS = {
    'bt3-usa': dict(serial='SLUS-21678', serial_file='SLUS_216.78', crc='428113C2', gp=USA_GP, video='ntsc',
                    table=None, gp_key=None, file_ids=None, flags=None),
    # The localised volumes insert files: +1 up to 4, +4 to 510, +97 to 610, +247 from 659 (no end: the European
    # volume 2 keeps the USA numbering past it).
    'bt3-pal': dict(serial='SLES-54945', serial_file='SLES_549.45', crc='A422BB13', gp=PAL_GP, video='pal',
                    table='pal_native_map.json', gp_key='pal',
                    file_ids=((1, 4, 1), (8, 510, 4), (511, 610, 97), (659, None, 247)), flags=None),
    # PZS3JP0-2: volume 0 has one file as on USA; volume 1 lacks the USA Spanish text set (USA 480-510) and half
    # of the USA second text set, so IDs fall by 1 / 32 / 82; USA 5-7 (font, battle sets) differ and volume 2
    # (from USA 3400 / JP 3318) does not align, so those IDs have no reviewed Japanese file. Native actor flags:
    # the Japanese executable lacks the USA-only flags 146 and 185, so USA flags 147..184 are one lower and
    # 186..316 two lower (every native call site that passes a constant flag agrees; nothing above 316 was seen).
    'bt3-jpn': dict(serial='SLPS-25815', serial_file='SLPS_258.15', crc='F28D21F1', gp=JPN_GP, video='ntsc',
                    table='jpn_native_map.json', gp_key='jpn',
                    file_ids=((1, 4, 0), (8, 479, -1), (511, 560, -32), (661, 3399, -82)),
                    flags=((0, 145, 0), (147, 184, -1), (186, 316, -2))),
}
TABLE_NAMES = {name: disc['table'] for name, disc in DISCS.items() if disc['table']}
# Opcodes whose 16-bit immediate is an address offset from the base register: loads, stores (GPR, COP1, COP2,
# 64/128-bit), cache/pref, and addiu/daddiu. With base register 28 the immediate is a gp offset (GPO).
GP_RELATIVE_OPS = frozenset({0x09, 0x19, 0x1A, 0x1B, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
                             0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x31, 0x33, 0x36, 0x37, 0x39, 0x3E,
                             0x3F})


class NativeMapError(LookupError):
    """A native reference has no reviewed value for the selected disc."""


def _resolve_adapter():
    import game_profile
    value = os.environ.get('TAGTEAM_ADAPTER', '').strip()
    source = 'TAGTEAM_ADAPTER'
    chosen = game_profile.installed_adapter()
    if value and chosen is not None and value != chosen:
        # A player installation runs the disc chosen for it: a leftover override would mix two discs.
        raise NativeMapError(f'TAGTEAM_ADAPTER={value!r} does not match the game disc chosen for this installation '
                             f'({chosen}); clear TAGTEAM_ADAPTER.')
    if not value:
        value, source = chosen or 'bt3-usa', 'the installed game profile'
    if value in ('bt3-pal', 'bt3-jpn'):
        return value
    if value in IDENTITY_ADAPTERS:
        return 'bt3-usa'
    raise NativeMapError(f'Unknown game adapter {value!r} from {source}; expected bt3-usa, bt3-pal or bt3-jpn.')


ADAPTER = _resolve_adapter()
_DISC = DISCS[ADAPTER]
PAL = ADAPTER == 'bt3-pal'                # the European 50 Hz / 512-line disc
JPN = ADAPTER == 'bt3-jpn'                # the Japanese disc (Sparking! Meteor)
TRANSLATED = _DISC['table'] is not None   # native addresses come from an address table
TABLE = HERE / (_DISC['table'] or 'pal_native_map.json')

SERIAL = _DISC['serial']
SERIAL_FILE = _DISC['serial_file']
CRC = _DISC['crc']
CHEAT_PREFIX = f'{SERIAL}_{CRC}'
GP = _DISC['gp']                          # the $gp register value of the native executable

HZ = 50 if PAL else 60                    # presentation fields per second
ACTOR_HZ = 25 if PAL else 30              # game-logic ticks per second
DISPLAY_H = 512 if PAL else 448           # interlaced frame height in lines
Y_ORIGIN = 1792 if PAL else 1824          # GS XYOFFSET Y in pixels (2048 - DISPLAY_H/2)
VRAM_SHIFT = 0x600 if PAL else 0          # GS blocks the larger PAL frame/Z buffers push native banks up


def elf_path(game_dir):
    """The chosen disc's copy of the executable. For this game folder that is game_profile.analysis_dir() (the
    installed disc's analysis/, or the folder of the disc chosen in Mod settings > Game disc); any other folder
    (tests, audits, a developer tree) keeps game_dir/analysis/<serial file>."""
    import game_profile
    try:
        this = Path(game_dir).resolve() == Path(game_profile.ROOT).resolve()
    except OSError:
        this = False
    if this:
        return game_profile.analysis_dir() / SERIAL_FILE
    return Path(game_dir) / 'analysis' / SERIAL_FILE


def ticks(n, base=60):
    """A mod-owned duration of n ticks at `base` Hz, in presentation fields of this disc.

    Native frame counts must come from the executable, never from this helper."""
    return n if not PAL else int(round(n * HZ / base))


# ------------------------------------------------------------------------------------------ the table

_table = None


def _hex(value):
    return int(value, 16)


def table():
    """The loaded address table of a translated disc. Raises NativeMapError when it is missing or does not fit."""
    global _table
    if _table is not None:
        return _table
    if not TRANSLATED:
        raise NativeMapError('The USA adapter has no translation table.')
    try:
        doc = json.loads(TABLE.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise NativeMapError(f'Address table for {SERIAL} unavailable ({TABLE.name}): {error}') from None
    if doc.get('schema') != 1 or doc.get('adapter') != ADAPTER:
        raise NativeMapError(f'{TABLE.name} is not a schema-1 {ADAPTER} table.')
    gp = doc.get('gp', {})
    if _hex(gp.get('usa', '0')) != USA_GP or _hex(gp.get(_DISC['gp_key'], '0')) != GP:
        raise NativeMapError(f'{TABLE.name} has unexpected gp values {gp}.')
    elf = elf_path(ROOT)
    if not elf.is_file():
        # A developer tree may lack the executable; a player installation always has the chosen disc's copy, and the
        # table is only valid for that exact executable.
        import game_profile
        if game_profile.installed() is not None:
            raise NativeMapError(f'{elf} is missing: {TABLE.name} cannot be checked against the executable of the '
                                 'chosen game disc.')
    elif hashlib.sha256(elf.read_bytes()).hexdigest() != doc.get('elf_sha256'):
        raise NativeMapError(f'{elf} is not the executable {TABLE.name} was generated from; '
                             'reinstall or regenerate the table.')
    addr = {_hex(k): _hex(v) for k, v in doc.get('addr', {}).items()}
    addr.update({_hex(k): _hex(v) for k, v in doc.get('overrides', {}).items()})
    ranges = {}
    for key, (pal, length) in doc.get('ranges', {}).items():
        usa, usa_len = key.split('+')
        ranges[(_hex(usa), _hex(usa_len))] = (_hex(pal), _hex(length))
    segments = sorted((_hex(lo), _hex(hi), int(delta)) for lo, hi, delta in gp.get('segments', ()))
    _table = dict(addr=addr, ranges=ranges, segments=segments, doc=doc)
    return _table


DISC_NAME = {'bt3-pal': 'European', 'bt3-jpn': 'Japanese'}.get(ADAPTER, 'USA')


def _pal_address(usa):
    if type(usa) is not int:
        raise TypeError(f'native address must be an int, not {type(usa).__name__}')
    value = table()['addr'].get(usa)
    if value is None:
        raise NativeMapError(f'No reviewed {DISC_NAME} address for USA {usa:#x}.')
    return value


def _pal_gp_target(usa):
    t = table()
    value = t['addr'].get(usa)
    if value is not None:
        return value
    for lo, hi, delta in t['segments']:
        if lo <= usa < hi:
            return usa + delta
    raise NativeMapError(f'No reviewed {DISC_NAME} address for the gp-relative USA target {usa:#x}.')


def _shifted(value, ranges, missing):
    for lo, hi, shift in ranges:
        if value >= lo and (hi is None or value <= hi):
            return value + shift
    raise NativeMapError(missing)


if TRANSLATED:
    def A(usa_addr):
        """USA native address -> this disc's native address (NativeMapError when not reviewed)."""
        return _pal_address(usa_addr)

    def GPO(usa_gp_offset):
        """USA gp-relative offset -> this disc's offset reaching the same variable."""
        off = int(usa_gp_offset)
        if 0x8000 <= off <= 0xFFFF:
            off -= 0x10000
        if not -0x8000 <= off < 0x8000:
            raise NativeMapError(f'gp offset out of range: {usa_gp_offset!r}')
        new = _pal_gp_target(USA_GP + off) - GP
        if not -0x8000 <= new < 0x8000:
            raise NativeMapError(f'USA gp offset {off} does not reach its {DISC_NAME} target through $gp.')
        return new

    def RANGE(usa_addr, usa_len):
        """USA native byte range -> (this disc's address, length)."""
        reviewed = table()['ranges'].get((usa_addr, usa_len))
        if reviewed is not None:
            return reviewed
        start = A(usa_addr)
        if usa_len > 4:
            last = usa_addr + usa_len - 4
            if A(last) != start + usa_len - 4:
                raise NativeMapError(f'USA range {usa_addr:#x}+{usa_len:#x} changes layout in the {DISC_NAME} '
                                     'executable and has no reviewed range.')
        return start, usa_len

    _FILE_SHIFTS = _DISC['file_ids']

    def FILE_ID(usa_id):
        """USA disc (AFS) global file ID -> this disc's ID (the localised volumes insert or lack files)."""
        return _shifted(usa_id, _FILE_SHIFTS, f'No reviewed {DISC_NAME} disc file for USA file ID {usa_id}.')
else:
    def A(usa_addr):
        return usa_addr

    def GPO(usa_gp_offset):
        return usa_gp_offset

    def RANGE(usa_addr, usa_len):
        return usa_addr, usa_len

    def FILE_ID(usa_id):
        return usa_id


if _DISC['flags']:
    _FLAG_SHIFTS = _DISC['flags']

    def FLAG(usa_flag):
        """USA native actor-flag number (the bit the native 1DA9D0/1DAA50/1DAC78/... set, clear and query in the
        actor's flag banks at +0x1085/+0x10AD/+0x10D5) -> this disc's number."""
        return _shifted(usa_flag, _FLAG_SHIFTS, f'USA actor flag {usa_flag} has no reviewed {DISC_NAME} flag.')
else:
    def FLAG(usa_flag):
        return usa_flag


def FLAG_BITS(usa_flags):
    """(byte index in a flag bank, bit mask) of USA actor flags that share one byte on this disc: a guest load of
    bank + index masked with the mask tests them. NativeMapError when they fall into different bytes."""
    flags = [FLAG(f) for f in usa_flags]
    index = {f >> 3 for f in flags}
    if len(index) != 1:
        raise NativeMapError(f'USA actor flags {list(usa_flags)} do not share one flag byte on the {DISC_NAME} disc.')
    mask = 0
    for f in flags:
        mask |= 1 << (f & 7)
    return index.pop(), mask
