"""Reviewed runtime adapters. Disc layout recognition is not hook compatibility."""
from dataclasses import dataclass
from .disc import require, executable_fingerprint, pcsx2_crc
from .known_discs import explain


# Stage-loader immediates checked by verify_stage_mapping: the normal loader,
# then the planet-destruction replacement loader (stage, split stage, effects).
USA_STAGE_HOOKS = (0x127FB8, 0x127FA8, 0x127CFC, 0x127360, 0x127354, 0x127384)
# The same six instructions in the European executable (paired to USA by their
# instruction context; research: disc-resources.md, "Adapter values for PAL").
PAL_STAGE_HOOKS = (0x1280E8, 0x1280D8, 0x127E2C, 0x127490, 0x127484, 0x1274B4)
# And in the Japanese executable (each USA instruction +8; the immediates are one
# lower: stages 368, split stages 407, stage effects 333).
JPN_STAGE_HOOKS = (0x127FC0, 0x127FB0, 0x127D04, 0x127368, 0x12735C, 0x12738C)


@dataclass(frozen=True)
class Adapter:
    name: str
    kind: str
    elf_sha256: str
    characters: int
    stage_count: int
    stage_base: int
    split_stage_base: int
    stage_effect_base: int
    collision_capacity: int
    menu_only: tuple = ()
    addon_sha256: str = ''
    serial: str = 'SLUS_216.78'      # boot executable named by SYSTEM.CNF
    region: str = 'US'               # BT3 volume names: /DATA/PZS3<region><n>.AFS
    character_base: int = 1424       # BT3 first costume model; +8 animation, +9 combat
    character_table_file: int = 4    # character selection rows (costume counts)
    ui_text_file: int = 451          # English names, forms and portraits (package 1, parts 29-31)
    stage_hooks: tuple = USA_STAGE_HOOKS
    text_language: str = 'en'        # the language of ui_text_file's names (ja: English names ship with the tools)

    def files(self, character, costume, damaged, counts):
        if self.kind == 'bt4-indexed':
            return [5650 + 2*sum(counts[:character]) + costume + counts[character]*damaged,
                    5150 + character, 5400 + character]
        base = self.character_base
        return [base + 10*character + costume + 4*damaged,
                base + 8 + 10*character, base + 9 + 10*character]


ADAPTERS = (
    Adapter('bt3-usa', 'bt3-afs',
            '811188ba9b416500d921cd4d9514df0cbf42f3a41a99cf5aac5a3da37171bf99',
            161, 35, 369, 408, 334, 0x3800, (),
            '30f61f9c78c3859e5dd4fcfd8df6753b0f2d2c64beb924b92da5b2eaaa5e09cc'),
    Adapter('bt4-b14-rev2-eng', 'bt4-indexed',
            '6c38c69f17e852ce9146b0576afbcd45ebe13208921c06e088b712c01dd84d3a',
            250, 99, 1523, 1622, 1424, 0x6000, (161,162,163,164),
            '0562c337d27adbb141030ddd616326118b181cee381a512351bc4421b8a35707',
            serial='SLUS_219.78'),
    # European BT3 (AU/EU, SLES-54945, 50 Hz). Same fighters, stages and costume
    # counts; its volume 0 has 2 entries and the English text set grew to five
    # languages, so global file IDs move (+4 up to 510, +247 from 659). The
    # values were derived by hash-aligning the AFS tables and confirmed against
    # the European executable's own immediates. English text set: 455.
    Adapter('bt3-pal', 'bt3-afs',
            '98ff35e7962da9533ae7aa0b337ee316bc24527678a897c0e946db424153f228',
            161, 35, 373, 412, 338, 0x3800, (),
            '81d029a54c1cf8ceb1232db698594a39dc42f8c3d7533d43c849b51bf262523b',
            serial='SLES_549.45', region='EU', character_base=1671, character_table_file=5,
            ui_text_file=455, stage_hooks=PAL_STAGE_HOOKS),
    # Japanese BT3 (Dragon Ball Z: Sparking! Meteor, SLPS-25815 VER 1.01, NTSC).
    # Same fighters, stages, costume counts, fusions and combat files as USA;
    # its volume 1 lacks the USA Spanish text set and half of the second text
    # set, so global file IDs fall (-1 to 479, -32 to 560, -82 from 661). Its
    # text set (450) holds Japanese names only: the English names ship with the
    # tools (bt3_english_names.json); the portraits come from the disc.
    Adapter('bt3-jpn', 'bt3-afs',
            'bde07b4d5986a7fc9af40eb18381cc0ae1db33ccf07f70ac4bc955de68453011',
            161, 35, 368, 407, 333, 0x3800, (),
            'd857f8ae629d4a082224ed7d561c7b878e47185781799e5e7198ed1ba983d36d',
            serial='SLPS_258.15', region='JP', character_base=1342, character_table_file=4,
            ui_text_file=450, stage_hooks=JPN_STAGE_HOOKS, text_language='ja'),
)
BY_NAME = {adapter.name: adapter for adapter in ADAPTERS}


# Adapter IDs are stable installation/payload keys, not a language restriction.
# Pair a whole loaded image with its reviewed add-on; never mix revisions just
# because their hook addresses or CRC happen to match. Resources are audited
# separately using the selected ISO's own index, including translated assets.
VARIANTS = (
    ('bt3-usa', 'BT3 USA / code-compatible translations',
     '024b4a558d90c24ea7ff193ad8a9e4cb808be4d7097e915cdda571c549adea9f',
     BY_NAME['bt3-usa'].addon_sha256, None),
    ('bt4-b14-rev2-eng', 'BT4 B14 REV2 English',
     '94322df93b20907c1204d6c3e80df8f1b556febb302e84fb3e52ad17e929e043',
     BY_NAME['bt4-b14-rev2-eng'].addon_sha256, 'en'),
    ('bt4-b14-rev2-eng', 'BT4 B14 REV2 Spanish',
     '790e5a966c640ced122e9c9285d1be0d96857bd0d38cc0b0edd42a1966817382',
     '6639aa78a1ab63a392ac2cbccd70350307d6bc5ecb57dc3d60a3671a2df022fd', 'es'),
    # The game picks its text language (En/Es/De/Fr/It) from the console; the
    # mod reads the English set, so no mod language is implied.
    ('bt3-pal', 'BT3 Europe SLES-54945 (En/Fr/De/Es/It)',
     '096e0601a57f92ef6f912d5ef4c3b8132a785876fa0a5650e893506b5ace697c',
     BY_NAME['bt3-pal'].addon_sha256, None),
    # Japanese text and voices; the mod keeps its English or Spanish.
    ('bt3-jpn', 'BT3 Japan SLPS-25815 (Sparking! Meteor)',
     'c57f643136fe571745227b35a1d3dd28e53cd4707e42fdc3f5fe0c74a9f94ba7',
     BY_NAME['bt3-jpn'].addon_sha256, None),
)


def candidate(disc):
    """The adapter whose resource layout the disc is audited under: the boot
    serial decides between adapters of one layout kind (never the first of a
    kind); an unknown serial falls back to the adapter for the disc's volume
    region. Being a candidate enables nothing: runtime_match proves the code."""
    same_kind = [a for a in ADAPTERS if a.kind == disc.kind]
    return (next((a for a in same_kind if a.serial == disc.serial), None)
            or next((a for a in same_kind if a.region == getattr(disc, 'region', None)), None)
            or next(iter(same_kind), None))


def runtime_match(disc):
    adapter=candidate(disc)
    fingerprint=executable_fingerprint(disc.elf)
    evidence=dict(loaded_elf_sha256=fingerprint,pcsx2_crc=pcsx2_crc(disc.elf),
                  variant=None,verified=False)
    if adapter is None:
        evidence['reason']='No adapter for this resource layout/region; language selection alone cannot relocate game code.'
        return adapter,explain(disc,evidence)
    if disc.serial!=adapter.serial:
        evidence['reason']=f'This adapter expects executable {adapter.serial}; found {disc.serial}. A different region/boot identity needs a reviewed port.'
        return adapter,explain(disc,evidence)
    if adapter.kind=='bt3-afs' and getattr(disc,'region',None)!=adapter.region:
        # The executable names its own volumes (pzs3us*/pzs3eu*/pzs3jp*); another region's file IDs differ.
        evidence['reason']=f'This executable reads PZS3{adapter.region} data volumes; this disc has {getattr(disc,"region",None) or "other"} volumes.'
        return adapter,explain(disc,evidence)
    candidates=[v for v in VARIANTS if v[0]==adapter.name and v[2]==fingerprint]
    if not candidates:
        evidence['reason']='Loaded game code or memory layout differs from every reviewed variant. Translated resources and unloaded ELF metadata are allowed; changed engine code needs a reviewed adapter.'
        return adapter,explain(disc,evidence,changed='executable')
    for _,label,_,addon,language in candidates:
        if disc.member_hashes.get('/BIN/DBZP.BIN;1','')==addon:
            evidence.update(variant=label,native_language=language,verified=True,reason='Loaded executable and menu/game add-on match a reviewed variant; resources are scanned independently.')
            return adapter,evidence
    evidence['reason']='The executable is recognized, but DBZP.BIN contains unreviewed menu/game code or belongs to a different revision.'
    return adapter,explain(disc,evidence,changed='addon')


def identify(disc):
    adapter,evidence=runtime_match(disc)
    return adapter,evidence['verified']


def quick_identify(path):
    """(adapter name or None, runtime_match evidence, boot serial) of an ISO without hashing the whole image: the
    image preflight (FormatError TTM-ISO-01..06), the ISO 9660 tree, SYSTEM.CNF, the boot executable, DBZP.BIN and
    the volume tables (TTM-ISO-05/07 when unreadable), then runtime_match. About a second; it writes nothing, so a
    refused disc leaves no trace (Mod settings > Game disc)."""
    from .disc import Disc,preflight
    preflight(path)
    with Disc(path) as disc:
        adapter,evidence=runtime_match(disc)
        return (adapter.name if adapter else None),evidence,disc.serial


def verify_stage_mapping(disc, adapter):
    # Actual immediates in the normal loader and destruction replacement loader,
    # at the adapter's own executable addresses. Requiring both prevents an
    # apparently working initial map with wrong replacement resources after a
    # planet-destruction ultimate.
    require(len(adapter.stage_hooks)==6,'Adapter has no reviewed stage-loader addresses')
    wanted=(adapter.stage_base,adapter.split_stage_base,adapter.stage_effect_base)*2
    for address, value in zip(adapter.stage_hooks, wanted):
        instruction = int.from_bytes(disc.native(address,4),'little')
        require(instruction >> 26 == 9 and instruction & 0xffff == value,
                f'Stage loader mapping changed at {address:08X}')
