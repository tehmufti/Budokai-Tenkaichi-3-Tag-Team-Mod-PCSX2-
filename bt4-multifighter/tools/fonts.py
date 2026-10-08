"""The font files the mod draws with, named in one place.

Windows keeps the exact system files it has always used (Arial, Arial Bold,
Bahnschrift, Segoe UI Black), spelled as the same strings and opened with
Pillow's default layout engine, so every picture, menu atlas and guest-code
packet stays byte-identical there, and a missing file still raises OSError
where the callers fall back (native_menu_assets, loading_art_v4,
guest_loading_screen, ingame_settings).

Everywhere else the only fonts are the bundled Liberation Sans 2.1.5 files in
vendor/fonts (SIL Open Font License 1.1, metric-compatible with Arial). There
is no system fallback and one forced layout engine (BASIC), so every Linux
installation draws the same pixels whatever fonts or libfribidi it has.
Bahnschrift and Segoe UI Black (the Ki Storm loading art) are Microsoft fonts
that cannot be redistributed; off Windows the loading art draws its lettering
with Liberation Sans Bold instead, without variation axes, compressing a run
horizontally only when it would not fit otherwise (loading_art_v4.FONTS).

Test pins that hold font pixels are keyed by identity(); tools/vendor/fonts/
README.md names the source and hashes of the bundled files.
"""
import hashlib
import io
import os
from functools import lru_cache
from pathlib import Path

WINDOWS = os.name == 'nt'
FOLDER = Path(__file__).resolve().parent/'vendor'/'fonts'
KINDS = ('sans', 'sans-bold', 'display', 'heading')
# The historical strings, byte for byte: callers and caches were built from them.
WINDOWS_FILES = {'sans': 'C:/Windows/Fonts/arial.ttf', 'sans-bold': 'C:/Windows/Fonts/arialbd.ttf',
                 'display': 'C:/Windows/Fonts/bahnschrift.ttf', 'heading': 'C:/Windows/Fonts/seguibl.ttf'}
BUNDLED_FILES = {'sans': 'LiberationSans-Regular.ttf', 'sans-bold': 'LiberationSans-Bold.ttf',
                 'display': 'LiberationSans-Bold.ttf', 'heading': 'LiberationSans-Bold.ttf'}
# Only Bahnschrift has the Weight/Width axes loading_art_v4 sets.
VARIABLE = {'display'}


def bundled():
    """True where the bundled Liberation fonts are the fonts (every platform except Windows)."""
    return not WINDOWS


def path(kind):
    """The font file for a logical font: 'sans', 'sans-bold', 'display' or 'heading'."""
    if kind not in KINDS:
        raise ValueError(f'Unknown font {kind!r}')
    return WINDOWS_FILES[kind] if not bundled() else str(FOLDER/BUNDLED_FILES[kind])


def variable(kind):
    """Whether the font behind `kind` has variation axes (Bahnschrift on Windows only)."""
    return kind in VARIABLE and not bundled()


def layout_engine():
    """None keeps Pillow's default (RAQM when available) on Windows; BASIC elsewhere."""
    if not bundled():
        return None
    from PIL import ImageFont
    return ImageFont.Layout.BASIC


def truetype(font, size):
    """ImageFont.truetype for a logical font name or a font file path.

    On Windows this is exactly the historical ImageFont.truetype(path, size).
    Elsewhere the file's bytes are handed to Pillow, so a missing or unreadable
    file raises OSError instead of Pillow quietly substituting a same-named
    system font, and the layout engine is BASIC so the pixels do not depend on
    libraqm/libfribidi.
    """
    from PIL import ImageFont
    file = path(font) if font in KINDS else str(font)
    if not bundled():
        return ImageFont.truetype(file, size)
    return ImageFont.truetype(io.BytesIO(_read(file)), size, layout_engine=ImageFont.Layout.BASIC)


@lru_cache(maxsize=8)
def _read(file):
    return Path(file).read_bytes()


def render_tag():
    """Extra cache-key bytes for pixels rendered off Windows (empty on Windows, so its keys are unchanged)."""
    if not bundled():
        return b''
    import PIL
    return f'\0layout=basic\0pillow={PIL.__version__}'.encode()


@lru_cache(maxsize=None)
def _digest(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def identity():
    """What font-drawn output depends on besides the code: the active font files
    (by content), the layout engine, the Pillow version and the FreeType it was
    built with (a distribution's Pillow may carry the same version with another
    FreeType). Test pins that hold font pixels are keyed by this string."""
    import PIL
    from PIL import features
    files = sorted({path(kind) for kind in KINDS})
    try:
        digests = '+'.join(_digest(file)[:16] for file in files)
    except OSError:
        digests = 'missing'
    engine = 'basic' if bundled() else ('raqm' if features.check('raqm') else 'basic')
    return f'{digests}/{engine}/pillow-{PIL.__version__}/freetype-{features.version("freetype2")}'
