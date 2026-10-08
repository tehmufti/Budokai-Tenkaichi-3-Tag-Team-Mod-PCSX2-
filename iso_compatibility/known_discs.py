"""Name the Budokai Tenkaichi 3 family disc behind a refusal and say which discs are supported.

Recognition only explains why a disc cannot be installed. It never enables an
adapter: adapters.runtime_match proves the executable and DBZP.BIN instead.
The installer shows these texts in the setup language; every template, disc
name and the supported-discs sentence is a key of installer-es.json.
"""
import hashlib
import re

SUPPORTED = ('Supported discs: Budokai Tenkaichi 3 USA (SLUS-21678), Europe (SLES-54945) or Japan (SLPS-25815, '
             'Sparking! Meteor), and Budokai Tenkaichi 4 B14 REV2 English / Spanish.')

# Boot executables (SYSTEM.CNF BOOT2) -> English disc names.
DISCS = {
    'SLUS_216.78': 'Budokai Tenkaichi 3 USA (SLUS-21678)',
    'SLES_549.45': 'Budokai Tenkaichi 3 Europe (SLES-54945)',
    'SLPS_258.15': 'Dragon Ball Z: Sparking! Meteor, the Japanese Budokai Tenkaichi 3 (SLPS-25815)',
    'SLPM_611.62': 'the Japanese Dragon Ball Z: Sparking! Meteor demo (SLPM-61162)',
}
# The reviewed BT3 executables (a refusal for these means changed code or files).
REVIEWED_BT3 = ('SLUS_216.78', 'SLES_549.45', 'SLPS_258.15')
BT4_SERIAL = 'SLUS_219.78'

KNOWN_RELEASE = 'The selected ISO is {disc}. This release is not supported.'
MODIFIED_EXECUTABLE = ('The selected ISO is {disc}, but its game executable differs from the original disc. '
                       'Modified executables are not supported; select an unmodified image of the disc.')
MODIFIED_ADDON = ('The selected ISO is {disc}, but its menu and game code (BIN/DBZP.BIN) differs from the original '
                  'disc. Modified game code is not supported; select an unmodified image of the disc.')
MODIFIED_LAYOUT = ('The selected ISO boots the executable of {disc}, but its data files are not laid out like that '
                   'disc. Modified discs are not supported; select an unmodified image of the disc.')
OTHER_BT4 = ('The selected ISO is a Budokai Tenkaichi 4 build other than B14 REV2 English / Spanish ({serial}). '
             'Only that BT4 build is supported.')
OTHER_BT3 = 'The selected ISO looks like a Budokai Tenkaichi 3 family disc ({serial}) that has no reviewed adapter.'
NOT_SUPPORTED = 'The selected ISO ({serial}) is not a supported game.'
TEMPLATES = (KNOWN_RELEASE, MODIFIED_EXECUTABLE, MODIFIED_ADDON, MODIFIED_LAYOUT, OTHER_BT4, OTHER_BT3, NOT_SUPPORTED)
BT3_VOLUME = re.compile(r'^/DATA/PZS3[A-Z0-9]{2}1\.AFS;1$', re.IGNORECASE)


def serial_text(serial):
    """'SLPS-25815' for the boot file name 'SLPS_258.15'; other names unchanged."""
    match = re.fullmatch(r'([A-Z]{4})_(\d{3})\.(\d{2})', str(serial or '').upper())
    return f'{match[1]}-{match[2]}{match[3]}' if match else str(serial or 'unknown')


def recognize(disc, changed=None):
    """(template, English disc name or None) for a disc that no reviewed adapter accepts.
    changed: 'executable' or 'addon' when the serial matched an adapter but that code differs."""
    serial = str(disc.serial or '').upper()
    # BT4 builds first: an older build may still boot the BT3 USA executable name.
    if serial == BT4_SERIAL or disc.kind == 'bt4-indexed' or '/BIN/DBZ4.BIN;1' in disc.members:
        return OTHER_BT4, None
    if serial in REVIEWED_BT3:
        return {'executable': MODIFIED_EXECUTABLE, 'addon': MODIFIED_ADDON}.get(changed, MODIFIED_LAYOUT), DISCS[serial]
    if serial in DISCS:
        return KNOWN_RELEASE, DISCS[serial]
    if any(BT3_VOLUME.match(member) for member in disc.members):
        return OTHER_BT3, None
    return NOT_SUPPORTED, None


def message(template, disc, serial, translate=lambda text: text):
    """The refusal in one language: translate(template) with the (translated) disc name, then the supported discs."""
    return (translate(template).format(disc=translate(disc) if disc else '', serial=serial)
            + ' ' + translate(SUPPORTED))


def explain(disc, evidence, changed=None):
    """Add evidence['refusal'] (template, disc, serial, supported, English text) to an unverified match."""
    template, name = recognize(disc, changed)
    serial = serial_text(disc.serial)
    evidence['refusal'] = dict(template=template, disc=name, serial=serial, supported=SUPPORTED,
                               text=message(template, name, serial))
    return evidence


# ---- The game disc page (Mod settings > Game disc) ------------------------------------------------------------
# A reviewed variant (adapters.VARIANTS label) -> (full title, region label, payload family). The titles and labels
# are whole English keys of localization.ES (never composed). The payload family is the tools folder that runs the
# disc: the European and Japanese BT3 discs run the bt3-usa payload (install_player.ADAPTERS), so one installation
# switches between the three BT3 discs, or between the two BT4 discs, but never between BT3 and BT4.
TITLES = {
    'BT3 USA / code-compatible translations': ('Budokai Tenkaichi 3 USA (SLUS-21678)', 'USA', 'bt3-usa'),
    'BT3 Europe SLES-54945 (En/Fr/De/Es/It)': ('Budokai Tenkaichi 3 Europe (SLES-54945)', 'Europe', 'bt3-usa'),
    'BT3 Japan SLPS-25815 (Sparking! Meteor)': ('Budokai Tenkaichi 3 Japan (SLPS-25815)', 'Japan', 'bt3-usa'),
    'BT4 B14 REV2 English': ('Budokai Tenkaichi 4 B14 REV2 English (SLUS-21978)', 'English', 'bt4-b14-rev2-eng'),
    'BT4 B14 REV2 Spanish': ('Budokai Tenkaichi 4 B14 REV2 Spanish (SLUS-21978)', 'Spanish', 'bt4-b14-rev2-eng'),
}
FAMILY_TITLES = {'bt3-usa': 'Budokai Tenkaichi 3 (USA, Europe or Japan)',
                 'bt4-b14-rev2-eng': 'Budokai Tenkaichi 4 B14 REV2 (English or Spanish)'}
# The language of a disc's own game text (the last field of adapters.VARIANTS; a test compares them). The Game disc
# page offers the mod's Spanish for a Spanish disc, also for the disc an installation was made with (it has no
# receipt). The BT3 discs imply no mod language.
NATIVE_LANGUAGE = {'BT4 B14 REV2 English': 'en', 'BT4 B14 REV2 Spanish': 'es'}
# The stage and split-screen stage files of each reviewed disc (stage_digest of its scan profile). A disc whose
# executable and add-on are reviewed but whose stage files differ (the mod's own expanded-map copy, or a map mod) is
# flagged: expanded maps are never built from it. Recorded from the scans of the five reviewed ISOs.
STAGE_DIGESTS = {
    'BT3 USA / code-compatible translations': 'ea2b320399f3b34e47294eb2bcb388932700129b6b15425cb4dffcab522aec6e',
    'BT3 Europe SLES-54945 (En/Fr/De/Es/It)': 'ad30df9d8671e9ad70804377a1563ec802648b113315a028f54683c45d463c34',
    'BT3 Japan SLPS-25815 (Sparking! Meteor)': '52961214c9d102259ef086094f0a4cfe0a1a886c5bf210e20b48596d0234ce89',
    'BT4 B14 REV2 English': '8c76cc5724b1e730f47400bb36966083239e6e3baed027f336f96558720338aa',
    'BT4 B14 REV2 Spanish': '8c76cc5724b1e730f47400bb36966083239e6e3baed027f336f96558720338aa',
}


def stage_digest(profile):
    """SHA-256 over the (file ID, SHA-256) of every stage and split-screen stage resource a scan profile recorded
    (layout stage_base / split_stage_base, stage_count of them each). None when the profile has no stage layout."""
    layout = profile.get('layout') or {}
    try:
        count = int(layout['stage_count'])
        ranges = [range(int(layout[name]), int(layout[name]) + count) for name in ('stage_base', 'split_stage_base')]
    except (KeyError, TypeError, ValueError):
        return None
    resources = profile.get('resources') or {}
    ids = sorted(int(key) for key in resources if any(int(key) in r for r in ranges))
    if not ids:
        return None
    return hashlib.sha256(''.join(f'{i}:{resources[str(i)]["sha256"]}\n' for i in ids).encode('ascii')).hexdigest()


def stages_modified(profile):
    """True when a reviewed disc's stage files differ from the original disc of its variant; None when unknown."""
    variant = (profile.get('identity') or {}).get('runtime_match', {}).get('variant')
    expected = STAGE_DIGESTS.get(variant)
    found = stage_digest(profile)
    if expected is None or found is None:
        return None
    return found != expected
