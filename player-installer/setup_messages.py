"""Coded setup messages for Tag Team Mod (standard library only).

messages.json holds every installer code TTM-<FAMILY>-NN with English and Spanish what / why / fix texts and named
{placeholders}. render() draws the plain ASCII-framed block players copy when they ask for help; install-player.ps1
draws the same block from the same file (Format-SetupFailure), and a test compares the two. setup and
check_installation.py use this module; when it or messages.json is missing, check_installation.py prints plain English.
"""
import datetime
import errno
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata

HERE = Path(__file__).resolve().parent
CATALOG = HERE/'messages.json'
WIDTH = 78
CODE = re.compile(r'TTM-([A-Z0-9]+)-(\d\d)')
PLACEHOLDER = re.compile(r'\{(\w+)\}')
WINDOWS = os.name == 'nt'
# Used when messages.json is missing (an installation made before this file existed): the same labels as the file.
LABELS = {
    'en': dict(what='WHAT HAPPENED', why='WHY', fix='HOW TO FIX', file='FILE', details='DETAILS', log='LOG',
               unchanged='Nothing was changed.', copy='Copy this block when asking for help.',
               setup='SETUP STOPPED', check='INSTALLATION CHECK FAILED', launcher='CANNOT START',
               warning='WARNING', notice='NOTE', ok='OK', warn='WARN', fail='FAIL'),
    'es': dict(what='QUE HA PASADO', why='POR QUE', fix='COMO SOLUCIONARLO', file='ARCHIVO', details='DETALLES',
               log='REGISTRO', unchanged='No se ha cambiado nada.', copy='Copia este bloque si pides ayuda.',
               setup='INSTALACION DETENIDA', check='LA COMPROBACION DE LA INSTALACION HA FALLADO',
               launcher='NO SE PUEDE INICIAR', warning='AVISO', notice='NOTA', ok='OK', warn='AVISO', fail='ERROR'),
}
FAMILIES = dict(ZIP=10, OS=20, DEST=30, PY=40, PCSX2=50, BIOS=60, ISO=70, PAYLOAD=80, CHECK=90, PLAY=2)
_cache = {}


def catalog(path=None):
    """messages.json as a dict; an empty catalog (labels only) when it is missing or damaged."""
    path = Path(path or CATALOG)
    key = str(path)
    if key not in _cache:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data.get('codes'), dict): raise ValueError('no codes')
        except (OSError, ValueError, AttributeError):
            data = dict(schema=1, width=WIDTH, families=FAMILIES, labels=LABELS, codes={})
        _cache[key] = data
    return _cache[key]


def family(code):
    match = CODE.fullmatch(str(code))
    return match.group(1) if match else 'PAYLOAD'


def exit_code(code):
    """The installer's process exit code for a failure code: 10 ZIP ... 90 CHECK (see messages.json 'families')."""
    return int(catalog().get('families', FAMILIES).get(family(code), 80))


def platform_values(windows=None):
    """Launcher names, the recommended folder and setup's BIOS option for the placeholders every text may use."""
    windows = WINDOWS if windows is None else windows
    if windows:
        home = os.environ.get('USERPROFILE') or str(Path.home())
        return dict(install='Install.cmd', play='Play.cmd', check='Check installation.cmd', settings='Mod settings.cmd',
                    recommended=str(Path(home)/'Games'/'Tag Team Mod'), platform='Windows x64',
                    cards='game/runtime28/memcards', bios_option='-Bios')
    return dict(install='Install.sh', play='Play.sh', check='Check installation.sh', settings='Mod settings.sh',
                recommended='~/Games/Tag Team Mod', platform='Linux x86-64 (AppImage)',
                cards='game/runtime28/PCSX2/memcards', bios_option='--bios')


def labels(lang):
    return dict(LABELS['en'], **catalog().get('labels', LABELS).get(lang if lang in ('en', 'es') else 'en', {}))


def pick(value, lang):
    """A placeholder value: plain text, or {'en': ..., 'es': ...} for text that is itself translated."""
    if isinstance(value, dict): return str(value.get(lang) or value.get('en') or '')
    return '' if value is None else str(value)


def fill(template, lang, values, /):
    """Replace each named {placeholder}; an unknown one becomes '?' (never a KeyError). install-player.ps1 does the
    same with .Replace('{name}', value)."""
    text = str(template)
    for name, value in values.items():
        text = text.replace('{'+name+'}', pick(value, lang))
    return PLACEHOLDER.sub('?', text)


def text(code, part, lang='en', /, **values):
    """One part ('what', 'why' or 'fix') of a code, filled, in 'en' or 'es'."""
    row = catalog()['codes'].get(code)
    if row is None: return pick(values.get('reason'), lang) if part == 'what' else ''
    lang = lang if lang in ('en', 'es') else 'en'
    return fill(row[lang][part], lang, dict(platform_values(), **values))


def fold(value):
    """ASCII only (for .cmd files): accents dropped, anything else as '?'."""
    value = unicodedata.normalize('NFKD', str(value)).replace('\u00bf', '').replace('\u00a1', '')
    return ''.join(c for c in value if not unicodedata.combining(c)).encode('ascii', 'replace').decode('ascii')


def wrap(text, width=WIDTH, indent='  '):
    """Greedy word wrap on single spaces; continuation lines are indented. install-player.ps1 (Format-Wrapped) uses
    the same rule so both renderers draw identical blocks."""
    lines = []
    for paragraph in str(text).split('\n'):
        line = ''
        for word in (w for w in paragraph.split(' ') if w):
            if not line: line = word if not lines else indent+word
            elif len(line)+1+len(word) <= width: line += ' '+word
            else:
                lines.append(line); line = indent+word
        if line: lines.append(line)
    return lines


def _files(file):
    if file is None or file == '' or file == []: return []
    return [str(f) for f in (file if isinstance(file, (list, tuple)) else [file])]


def render(code, lang='en', /, *, file=None, log=None, detail=None, unchanged=None, ascii=False, **values):
    """The failure block: the code first, then WHAT HAPPENED / WHY / HOW TO FIX, 'Nothing was changed.' when true,
    the file(s), the English details, the log and 'Copy this block when asking for help.' lang 'both' shows English
    then Spanish (used before the language is chosen). Paths sit on their own lines, never wrapped."""
    languages = ('en', 'es') if lang == 'both' else (lang if lang in ('en', 'es') else 'en',)
    row = catalog()['codes'].get(code, {})
    if unchanged is None: unchanged = bool(row.get('unchanged'))
    kind = row.get('kind') or ('check' if family(code) == 'CHECK' else 'launcher' if family(code) == 'PLAY' else 'setup')
    both = lambda key: ' / '.join(labels(l)[key] for l in languages)
    out = ['='*WIDTH, f'[{code}] {both(kind)}', '-'*WIDTH]
    for index, language in enumerate(languages):
        if index: out.append('-'*WIDTH)
        names = labels(language)
        for part in ('what', 'why', 'fix'):
            body = text(code, part, language, **values)
            if body: out += wrap(names[part]+': '+body)
        if unchanged: out.append(names['unchanged'])
    if len(languages) > 1: out.append('-'*WIDTH)
    paths = _files(file)
    if paths:
        out.append(both('file')+':')
        out += ['  '+path for path in paths]
    if detail: out += wrap(both('details')+': '+str(detail))
    if log:
        out.append(both('log')+':')
        out.append('  '+str(log))
    out += wrap(both('copy'))
    out.append('='*WIDTH)
    block = '\n'.join(out)
    return fold(block) if ascii else block


def line(code, lang='en', /, **values):
    """A one-line checklist entry for a warning or notice: 'TTM-DEST-21 <what> <fix>'."""
    return ' '.join(part for part in (code, text(code, 'what', lang, **values), text(code, 'fix', lang, **values)) if part)


class SetupFailure(ValueError):
    """A coded failure. str() is the 'what' text plus the detail (English unless lang says otherwise), so logs and
    existing callers stay readable; render() gives the player's block in either language."""
    def __init__(self, code, /, *, file=None, detail='', unchanged=None, lang='en', **values):
        self.code, self.file, self.detail, self.unchanged = code, file, str(detail or ''), unchanged
        self.values = {k: (v if isinstance(v, dict) else '' if v is None else str(v)) for k, v in values.items()}
        what = text(code, 'what', lang, **self.values) or code
        super().__init__(what+(' ('+self.detail+')' if self.detail else ''))

    def details(self):
        """install-status.json / check-status.json 'error_details' (JSON)."""
        data = dict(self.values)
        if self.file is not None: data['file'] = [str(f) for f in self.file] if isinstance(self.file, (list, tuple)) else str(self.file)
        if self.detail: data['detail'] = self.detail
        if self.unchanged is not None: data['unchanged'] = bool(self.unchanged)
        return data

    @classmethod
    def from_details(cls, code, details):
        details = dict(details or {})
        file, detail, unchanged = details.pop('file', None), details.pop('detail', ''), details.pop('unchanged', None)
        return cls(code, file=file, detail=detail, unchanged=unchanged, **details)

    def render(self, lang='en', log=None, ascii=False):
        return render(self.code, lang, file=self.file, log=log, detail=self.detail, unchanged=self.unchanged,
                      ascii=ascii, **self.values)


# Windows error numbers: 112 disk full, 39 handle disk full; 5 access denied, 32 sharing violation, 33 lock violation.
DISK_FULL_WINERRORS = (112, 39)
NO_ACCESS_WINERRORS = (5, 32, 33)


def classify(error, translate=lambda text: text, reason='TTM-PAYLOAD-02', unexpected='TTM-PAYLOAD-90', known=None,
             step=''):
    """A SetupFailure for any exception: a SetupFailure as it is; an error carrying a TTM code (iso_compatibility's
    FormatError) with that code; disk full / access refused; a timeout; a plain ValueError with its message as the
    translated reason (known maps exact messages to a code whose what is '{reason}'); anything else as unexpected."""
    if isinstance(error, SetupFailure): return error
    code = getattr(error, 'code', None)
    if isinstance(code, str) and CODE.fullmatch(code):
        values = {k: v for k, v in (getattr(error, 'details', None) or {}).items() if isinstance(v, (str, int, float))}
        message = str(error)
        values.setdefault('reason', dict(en=message, es=translate(message)))
        # iso_compatibility's FormatError keeps the library's own words (pycdlib, struct) as .cause: the DETAILS line.
        return SetupFailure(code, detail=str(getattr(error, 'cause', '') or ''), **values)
    if isinstance(error, OSError):
        winerror = getattr(error, 'winerror', None)
        target = getattr(error, 'filename', None)
        detail = f'{type(error).__name__}: {error}'
        if error.errno == errno.ENOSPC or winerror in DISK_FULL_WINERRORS:
            return SetupFailure('TTM-OS-03', file=target, detail=detail)
        if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS) or winerror in NO_ACCESS_WINERRORS:
            return SetupFailure('TTM-OS-04', file=target, detail=detail)
    if isinstance(error, subprocess.TimeoutExpired):
        command = error.cmd if isinstance(error.cmd, (list, tuple)) else [error.cmd]
        name = step or (Path(str(command[1])).name if len(command) > 1 else str(command[0]))
        return SetupFailure('TTM-PAYLOAD-05', step=name, detail=f'timeout after {error.timeout} s')
    if isinstance(error, ValueError):
        message = str(error)
        target = (known or {}).get(message, reason)
        return SetupFailure(target, reason=dict(en=message, es=translate(message)))
    return SetupFailure(unexpected, detail=f'{type(error).__name__}: {error}')


def write_status(path, failure, **fields):
    """Write a failed status file atomically (ASCII JSON, which PowerShell 5.1 reads safely): the given fields plus
    ready=false, stage=FAILED, error (English), error_code and error_details."""
    path = Path(path)
    data = dict(fields, ready=False, stage='FAILED', error=str(failure), error_code=failure.code,
                error_details=failure.details())
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    os.replace(temporary, path)
    return data


def log_directory(windows=None):
    """Where setup keeps its logs: %LOCALAPPDATA%\\TagTeamMod\\logs, or ~/.local/state/tagteammod/logs on Linux
    (TAGTEAM_SETUP_LOGS overrides both, as in install-player.ps1)."""
    if os.environ.get('TAGTEAM_SETUP_LOGS'): return Path(os.environ['TAGTEAM_SETUP_LOGS'])
    windows = WINDOWS if windows is None else windows
    if windows:
        base = os.environ.get('LOCALAPPDATA') or str(Path.home()/'AppData'/'Local')
        return Path(base)/'TagTeamMod'/'logs'
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local'/'state')/'tagteammod'/'logs'


def new_log_path(prefix='setup', folder=None):
    """A new timestamped log path in the log folder (created); the temporary folder when that cannot be created."""
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    for candidate in ((Path(folder),) if folder else (log_directory(), Path(tempfile.gettempdir()))):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            path = candidate/f'{prefix}-{stamp}.log'
            number = 1
            while path.exists():
                number += 1; path = candidate/f'{prefix}-{stamp}-{number}.log'
            return path
        except OSError:
            continue
    return Path(tempfile.gettempdir())/f'{prefix}-{stamp}.log'
