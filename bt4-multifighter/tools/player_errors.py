"""One explanation for every runtime failure: what happened, why, and how to fix it.

explain() turns an exception into an Explanation with a code (TTM-<FAMILY>-NN), a localized
'what', 'why' and 'how to fix' (the language saved in game/mod-settings.json), and an English
technical detail that is never empty. fail() is what the watcher calls: one report line, the
other block lines, a sticky status record, a report file and the in-game failure cover.

Nothing here raises: an explanation that cannot be built falls back to the English defaults.
The module is adapter-neutral (no disc serial, PINE port or title) and imports only the
standard library; localization is imported when text is needed.
"""
import dataclasses
import errno
import json
import os
import platform
import re
import struct
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
REPORTS = None          # tests point this at a temporary folder
KEEP_REPORTS = 10
CODE_PATTERN = re.compile(r'TTM-[A-Z]+-\d\d')

# ---- codes ------------------------------------------------------------------------------------

FAMILIES = {'launch': 'PLAY', 'preparation': 'MATCH', 'rematch': 'MATCH', 'fighter_update': 'MATCH',
            'observe': 'MATCH', 'menu_return': 'MENU', 'controllers': 'CTRL', 'settings': 'SET', 'disc': 'DISC'}
OPERATIONS = tuple(FAMILIES)
JOBS = ('transformation', 'body_change', 'fusion', 'costume', 'reload')
# Classes in the order explain() tests them (01-09), then the two descriptive sub-entries.
CLASSES = {'closed': 1, 'lost': 2, 'timeout': 3, 'disk_full': 4, 'no_access': 5, 'mod_check': 6,
           'coded': 7, 'descriptive': 8, 'unexpected': 9, 'unicode': 10, 'damaged_file': 11}
CLASS_TITLES = {'closed': 'PCSX2 was closed', 'lost': 'connection to PCSX2 lost', 'timeout': 'a step took too long',
                'disk_full': 'disk full', 'no_access': 'file access refused', 'mod_check': 'mod safety check failed',
                'coded': 'coded failure (the code of the error itself)', 'descriptive': 'described failure',
                'unexpected': 'unexpected error', 'unicode': 'text could not be printed',
                'damaged_file': 'a mod file is damaged'}
# Launcher refusals and startup failures (Play.cmd / Play.sh). 50-59 belong to the installer's
# generated launchers (setup/messages.json).
LAUNCH_CODES = {
    'TTM-PLAY-20': 'PCSX2 is already running',
    'TTM-PLAY-21': 'another program uses the PINE port',
    'TTM-PLAY-22': 'the game ISO was moved or deleted',
    'TTM-PLAY-23': 'the game ISO check failed',
    'TTM-PLAY-24': 'a required file is missing',
    'TTM-PLAY-25': 'the private Python (.venv) does not start',
    'TTM-PLAY-26': 'no Python with the mod packages was found',
    'TTM-PLAY-27': 'the mod settings file cannot be read',
    'TTM-PLAY-28': 'a game file of the mod is missing or does not match',
    'TTM-PLAY-29': 'the PCSX2 version is not supported',
    'TTM-PLAY-30': 'a PCSX2 setting of this installation was changed',
    'TTM-PLAY-31': 'another Play window is still running',
    'TTM-PLAY-32': 'a startup step failed',
    'TTM-PLAY-33': "the mod's helper could not start",
    'TTM-PLAY-34': "the mod's helper did not confirm PCSX2 in time",
    'TTM-PLAY-35': 'PCSX2 closed during startup',
    'TTM-PLAY-36': 'PCSX2 closed with an error',
    'TTM-PLAY-37': "the mod's helper stopped during the session",
    'TTM-PLAY-38': 'the session ended after an error',
    'TTM-PLAY-39': 'the expanded-map ISO could not be selected',
    'TTM-PLAY-40': 'unexpected launcher failure',
    'TTM-PLAY-41': 'a PCSX2 opened while Play was starting',
    'TTM-PLAY-42': 'the Mod settings window could not finish',
    'TTM-PLAY-43': 'no Python with Tk was found for Mod settings',
    'TTM-PLAY-44': 'the chosen ISO is not the installed game',
    'TTM-PLAY-45': 'the installation folder path has square brackets',
    'TTM-PLAY-46': 'the game disc chosen in Mod settings cannot be used',
}
# Mod settings > Game disc (disc_library.py) refusals, numbered after the family's classes (01-11). Their what / why /
# fix texts are disc_library.EXPLAIN (Spanish in localization.ES).
DISC_CODES = {
    'TTM-DISC-20': 'Play or this PCSX2 is running',
    'TTM-DISC-21': 'the disc belongs to the other game',
    'TTM-DISC-22': 'the disc is not enabled in this release',
    'TTM-DISC-23': "the disc's extracted files are missing or changed",
    'TTM-DISC-24': "the disc's ISO is not at its saved location",
    'TTM-DISC-25': "the chosen file is not the disc's ISO",
    'TTM-DISC-26': 'the mod could not be prepared for the disc',
    'TTM-DISC-27': 'the ISO changed while it was checked',
    'TTM-DISC-28': 'not enough free disk space',
    'TTM-DISC-29': 'the disc cannot be removed from the list',
    'TTM-DISC-30': 'another Mod settings window is changing the discs',
    'TTM-DISC-31': "the ISO is the mod's expanded-map copy",
    'TTM-DISC-32': 'not a player installation',
    'TTM-DISC-33': "the disc's stage files differ from the original disc",
    'TTM-DISC-34': 'the chosen file cannot be opened',
    'TTM-DISC-35': 'the expanded maps cannot be deleted now',
}
# Problems the watcher detects itself (Detected), numbered after each family's classes (01-11).
EVENT_CODES = {
    'TTM-MATCH-20': 'the game stopped responding during a match',
    'TTM-MATCH-21': 'a cinematic pause overran and was released',
    'TTM-MENU-20': 'the game restarted during a match',
    # Controller check-in (controller_hub): Play-window lines prefixed with the code; texts in controller_hub.SAY.
    'TTM-CTRL-20': "the mod's controller reader (SDL2) did not start",
    'TTM-CTRL-21': 'a controller has no gamepad layout',
    'TTM-CTRL-22': "a player's controller disconnected",
    'TTM-CTRL-23': 'one controller appears twice (a remapper)',
    'TTM-CTRL-24': 'one controller moves two players',
    'TTM-CTRL-25': 'controller input for players stopped',
}


def _codes():
    codes = {}
    for family in dict.fromkeys(FAMILIES.values()):
        for kind, number in CLASSES.items():
            if kind != 'coded':
                codes[f'TTM-{family}-{number:02d}'] = CLASS_TITLES[kind]
    codes.update(LAUNCH_CODES)
    codes.update(EVENT_CODES)
    codes.update(DISC_CODES)
    return codes


CODES = _codes()


def code_for(operation, kind):
    return f'TTM-{FAMILIES.get(operation, "MATCH")}-{CLASSES.get(kind, 9):02d}'


# ---- text (English keys; Spanish in localization.ES) ---------------------------------------------

LABELS = {'what': 'WHAT HAPPENED', 'why': 'WHY', 'fix': 'HOW TO FIX', 'file': 'FILE', 'details': 'DETAILS',
          'log': 'LOG', 'report': 'REPORT', 'unchanged': 'Nothing was changed.',
          'copy': 'Copy this block when asking for help.'}
LABELS_ES = {'what': 'QUE HA PASADO', 'why': 'POR QUE', 'fix': 'COMO SOLUCIONARLO', 'file': 'ARCHIVO',
             'details': 'DETALLES', 'log': 'REGISTRO', 'report': 'INFORME', 'unchanged': 'No se ha cambiado nada.',
             'copy': 'Copia este bloque si pides ayuda.'}

# What stopped, per operation (and per fighter-update job).
STOPPED = {
    'launch': 'Play could not start',
    'preparation': 'Match setup stopped',
    'rematch': 'The rematch could not be loaded',
    'menu_return': 'The return to the menu failed',
    'controllers': 'Controller setup failed',
    'settings': 'Mod settings could not be used',
    'disc': 'The game disc could not be changed',
    'observe': 'The mod stopped following the match',
    'modded_modes': 'At the main menu',   # observe with context where='Modded Modes menu' (autopilot pager faults)
    'transformation': 'The transformation could not be applied',
    'body_change': 'The body change could not be applied',
    'fusion': 'The fusion could not be applied',
    'costume': 'The costume change could not be applied',
    'reload': 'A fighter update could not be applied',
}
REASONS = {
    'closed': 'PCSX2 was closed.',
    'lost': 'the mod lost its connection to PCSX2.',
    'timeout': 'a step did not finish in time.',
    'disk_full': 'the disk is full.',
    'no_access': 'Windows refused access to a mod file.',
    'mod_check': 'a mod safety check failed.',
    'unexpected': 'an unexpected error occurred.',
    'unicode': 'a file or folder name could not be printed.',
    'damaged_file': 'a mod file is damaged.',
}
CAUSES = {
    'closed': '',
    'lost': 'PCSX2 stopped responding, crashed or was closed.',
    'timeout': 'The game was paused, the PCSX2 window was minimized, or the PC was busy.',
    'disk_full': 'The drive that holds the Tag Team Mod folder has no free space left.',
    'no_access': 'OneDrive, an antivirus program or another program locked or blocked a file in the Tag Team Mod folder.',
    'mod_check': 'This combination of fighters, stage and disc is not supported, or the mod has a bug.',
    'coded': '',
    'descriptive': '',
    'unexpected': '',
    'unicode': 'A folder name contains characters this console cannot show.',
    'damaged_file': 'The file was cut short or edited by hand.',
}
RESTART = 'Close PCSX2, then start {play} again.'
ACTIONS = {
    'closed': 'Start {play} again when you want to play.',
    'lost': RESTART,
    'timeout': 'Close PCSX2, then start {play} again and keep the game running in its window while it loads.',
    'disk_full': 'Free some disk space, close PCSX2, then start {play} again.',
    'no_access': 'Close PCSX2, pause OneDrive or allow the Tag Team Mod folder in your antivirus, then start {play} again.',
    'mod_check': 'Close PCSX2, then start {play} again and try other fighters or another stage. If it happens again, send the report file to the mod author.',
    'coded': RESTART,
    'descriptive': RESTART,
    'unexpected': 'Close PCSX2, then start {play} again. If it happens again, send the report file to the mod author.',
    'unicode': 'Move the Tag Team Mod folder to a path with plain letters, then start {play} again.',
    'damaged_file': 'Close PCSX2, then start {play} again. If it happens again, install the mod again into a new folder.',
}
RECOVERED = 'You can keep playing. If it happens again, send the report file to the mod author.'
# Mod settings > Game disc (operation 'disc') works while PCSX2 is closed: its next step is on that page, not in Play.
DISC_ACTION = 'Try again in {mod_settings} > Game disc. If it happens again, send this block to the mod author.'
DISC_ACTIONS = {
    'disk_full': 'Free some disk space, then try again in {mod_settings} > Game disc.',
    'no_access': 'Pause OneDrive or allow the Tag Team Mod folder in your antivirus, then try again in {mod_settings} > Game disc.',
    'damaged_file': 'Try again in {mod_settings} > Game disc. If it happens again, install the mod again into a new folder.',
    'unicode': 'Move the Tag Team Mod folder to a path with plain letters, then try again in {mod_settings} > Game disc.',
}
# Descriptive messages with a better next step than restarting.
SETTINGS_FILE = re.compile(r'mod settings|mod-settings\.json', re.I)
SETTINGS_CAUSE = 'The file game/mod-settings.json is damaged or comes from an unsupported version.'
SETTINGS_ACTION = 'Open {mod_settings} and choose Restore defaults (or delete game/mod-settings.json), then start {play} again.'

# In-game covers: fixed upper-case literals (no launcher names), translated, then fitted by the painter.
COVER_LINES = {
    'launch': 'SETUP STOPPED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'preparation': 'SETUP STOPPED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'rematch': 'REMATCH FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'menu_return': 'MENU RETURN FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'controllers': 'CONTROLLER SETUP FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'settings': 'SETTINGS FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'observe': 'MOD STOPPED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'transformation': 'TRANSFORMATION FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'body_change': 'BODY CHANGE FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'fusion': 'FUSION FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'costume': 'COSTUME CHANGE FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
    'reload': 'FIGHTER UPDATE FAILED - CLOSE PCSX2, THEN START PLAY AGAIN',
}
RECOVERED_COVER_LINES = {
    'menu_return': 'BACK AT THE MAIN MENU - YOU CAN KEEP PLAYING',
    'fighter_update': 'FIGHTER UPDATES OFF FOR THIS MATCH',
}
RECOVERED_COVER = 'SOMETHING WENT WRONG - YOU CAN KEEP PLAYING'
COVER_DETAIL = 'CODE {code} - DETAILS IN THE PLAY WINDOW'
COVER_LIMIT = 60


# ---- the explanation ------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Explanation:
    code: str
    what: str
    cause: str
    action: str
    detail: str
    stage: str = None
    report: Path = None
    recovered: bool = False
    kind: str = 'unexpected'
    operation: str = 'launch'
    job: str = None


class Detected(RuntimeError):
    """A problem the mod detects and describes itself (EVENT_CODES, or a class code such as TTM-MATCH-02).

    what/why/fix are fixed English templates: explain() translates them (localization.ES) and fills in this
    installation's launcher names ({play}, {mod_settings}). The message is the English technical detail
    (DETAILS), so numbers and paths never enter a translated sentence."""

    def __init__(self, code, what, why='', fix='', detail=''):
        super().__init__(detail or what)
        self.code, self.what, self.why, self.fix = code, what, why, fix


def _localization():
    try:
        import localization
        return localization
    except Exception:
        return None


def tr(text, **values):
    """localization.tr, or English when it cannot be used. Values are never templates."""
    loc = _localization()
    if loc is not None:
        try:
            return loc.tr(text, **values)
        except Exception:
            pass
    try:
        return text.format(**values) if values else text
    except Exception:
        return text


def entries(short=False):
    """{name: launcher} for this installation (localization.entry), with plain fallbacks."""
    names = ('play', 'mod_settings', 'check_installation', 'scan_compatibility', 'build_expanded_maps', 'pcsx2_settings')
    loc = _localization()
    found = {}
    for name in names:
        try:
            found[name] = loc.entry(name, short=short) if loc is not None else ''
        except Exception:
            found[name] = ''
    found['play'] = found['play'] or 'Play'
    found['mod_settings'] = found['mod_settings'] or 'Mod settings'
    return found


def labels():
    loc = _localization()
    try:
        return LABELS_ES if loc is not None and loc.language() == 'es' else LABELS
    except Exception:
        return LABELS


def _frames(error):
    try:
        return traceback.extract_tb(error.__traceback__) if error.__traceback__ is not None else []
    except Exception:
        return []


def _ours(filename):
    try:
        path = Path(filename).resolve()
        return path.parent == TOOLS or 'iso_compatibility' in path.parts
    except Exception:
        return False


def _deepest_tools_frame(error):
    frames = _frames(error)
    for frame in reversed(frames):
        if _ours(frame.filename):
            return frame
    return frames[-1] if frames else None


def _names(error):
    return {cls.__name__ for cls in type(error).__mro__}


def classify(error):
    """The class of a failure (CLASSES), first match wins."""
    names = _names(error)
    if 'EmulatorClosed' in names:
        return 'closed'
    frames = _frames(error)
    in_pine = bool(frames) and Path(frames[-1].filename).name == 'pine.py'
    winerror = getattr(error, 'winerror', None)
    if ('PineError' in names or isinstance(error, ConnectionError) or winerror in (10053, 10054, 10061)
            or (isinstance(error, TimeoutError) and in_pine)):
        return 'lost'
    if isinstance(error, TimeoutError):
        return 'timeout'
    if isinstance(error, OSError):
        if error.errno == errno.ENOSPC or winerror in (112, 39):
            return 'disk_full'
        if error.errno in (errno.EACCES, errno.EROFS) or winerror in (5, 32, 33):
            return 'no_access'
    if isinstance(error, (AssertionError, IndexError, KeyError, struct.error, TypeError, AttributeError,
                          ZeroDivisionError)):
        # "In a tools frame": raised by the mod's own code (or the ISO scanner), or with no traceback at all.
        if not frames or _ours(frames[-1].filename):
            return 'mod_check'
    code = getattr(error, 'code', None)
    if isinstance(code, str) and CODE_PATTERN.fullmatch(code):
        return 'coded'
    if isinstance(error, UnicodeError):
        return 'unicode'
    if isinstance(error, json.JSONDecodeError):
        return 'damaged_file'
    if isinstance(error, (ValueError, RuntimeError)) and str(error).strip():
        return 'descriptive'
    return 'unexpected'


def short(error):
    """One English line that is never empty: the message, or the exception type where the mod raised
    it, with that line's source (an assert without a message says nothing by itself)."""
    try:
        name = type(error).__name__
        try:
            text = ' '.join(str(error).split())
        except Exception:
            text = ''
        frame = _deepest_tools_frame(error)
        where = f'{Path(frame.filename).name}:{frame.lineno} in {frame.name}' if frame is not None else ''
        source = ' '.join((frame.line or '').split()) if frame is not None else ''
        if text and isinstance(error, (ValueError, RuntimeError, OSError)) and not isinstance(error, UnicodeError):
            result = text
        elif text:
            result = f'{name}: {text}' + (f' at {where}' if where else '')
        elif where:
            result = f'{name} at {where}' + (f': {source}' if source else '')
        else:
            result = name
        return result[:600] or name
    except Exception:
        return 'Error'


def translate_message(message):
    """A static message translates whole; 'Sentence (technical detail)' or 'Sentence: detail' translates the
    sentence and keeps the detail. The message is never used as a format template."""
    translated = tr(message)
    if translated != message:
        return translated
    # A message that names this installation's launchers matches its template ('... start {play} again.').
    names = {name: value for name, value in entries().items() if value and value in message}
    if names and '{' not in message:
        template = message
        for name, value in sorted(names.items(), key=lambda item: -len(item[1])):
            template = template.replace(value, '{' + name + '}')
        translated = tr(template)
        if translated != template:
            try:
                return translated.format(**names)
            except (KeyError, IndexError, ValueError):
                pass
    for separator in (' (', ': '):
        head, found, rest = message.partition(separator)
        if found and head:
            translated = tr(head)
            if translated != head:
                return translated + found + rest
    return message


def _operation_key(operation, context):
    if operation == 'fighter_update':
        job = (context or {}).get('job') if isinstance(context, dict) else None
        return job if job in JOBS else 'reload'
    if operation == 'observe' and isinstance(context, dict) and context.get('where') == 'Modded Modes menu':
        return 'modded_modes'   # a menu fault, not 'the mod stopped following the match'
    return operation if operation in STOPPED else 'launch'


# Names keep their capital after 'Match setup stopped:' (Windows, OneDrive, a launcher name ...).
PROPER_NOUNS = ('Windows', 'OneDrive', 'PCSX2', 'Python', 'Linux', 'Tk', 'Tag', 'Mod', 'Play', 'Check', 'Scan', 'Build')
# The first words of a sentence that tells the player what to do (English, then Spanish): a descriptive
# message that carries its own action shows it once, as HOW TO FIX, not also inside WHAT HAPPENED.
IMPERATIVES = ('Close ', 'Start ', 'Restart ', 'Reopen ', 'Relaunch ', 'Open ', 'Run ', 'Install ', 'Reinstall ',
               'Free ', 'Move ', 'Choose ', 'Delete ', 'Pause ', 'Allow ', 'Try ', 'Do not ', "Don't ", 'Put ',
               'Reconnect ', 'Turn ', 'Rebuild ', 'Update ', 'Press ', 'Wait ', 'Resume ',
               'Cierra ', 'Inicia ', 'Vuelve a ', 'Abre ', 'Ejecuta ', 'Instala ', 'Libera ', 'Mueve ', 'Elige ',
               'Borra ', 'Pausa ', 'Permite ', 'Prueba ', 'No ejecutes ', 'No abras ', 'Pon ', 'Conecta ',
               'Desactiva ', 'Actualiza ', 'Pulsa ', 'Espera ', 'Reanuda ', 'Reinicia ')
SENTENCE = re.compile(r'(?<=[.!?])\s+(?=\S)')


def _lower_first(text):
    """'The disk...' -> 'the disk...' after 'Match setup stopped:'; 'PCSX2 ...' and 'Windows ...' keep
    their capitals."""
    word = text.split(' ', 1)[0].rstrip('.,:;')
    if word in PROPER_NOUNS or word.split('.', 1)[0] in PROPER_NOUNS:
        return text
    return text[0].lower() + text[1:] if len(text) > 1 and text[0].isupper() and text[1].islower() else text


def split_action(text):
    """(what, own action) of a descriptive message: its first sentence that tells the player what to do
    starts the action. (text, '') when it has none (a one-sentence message never splits)."""
    try:
        sentences = SENTENCE.split(text)
        for index, sentence in enumerate(sentences[1:], 1):
            if sentence.startswith(IMPERATIVES):
                return ' '.join(sentences[:index]), ' '.join(sentences[index:])
    except Exception:
        pass
    return text, ''


def explain(error, operation, stage=None, context=None, *, recovered=False):
    """An Explanation of `error` during `operation` (FAMILIES). Never raises."""
    detail = short(error)
    operation = operation if operation in FAMILIES else 'launch'
    job = _operation_key(operation, context) if operation == 'fighter_update' else None
    try:
        kind = classify(error)
        code = error.code if kind == 'coded' else code_for(operation, kind)
        names = entries()
        if kind == 'coded' and isinstance(error, Detected):
            # Its own sentences: no 'what stopped' heading, and its own next step even when recovered.
            fix = error.fix or (RECOVERED if recovered else ACTIONS['coded'])
            return Explanation(code=code, what=tr(error.what, **names), cause=tr(error.why, **names) if error.why else '',
                               action=tr(fix, **names), detail=detail, stage=str(stage) if stage else None,
                               recovered=bool(recovered), kind=kind, operation=operation, job=job)
        stopped = tr(STOPPED[_operation_key(operation, context)])
        cause = tr(CAUSES.get(kind, ''))
        if kind in ('coded', 'descriptive'):
            message = ' '.join(str(error).split())
            reason, own_action = split_action(translate_message(message))
            if SETTINGS_FILE.search(message):
                cause, action = tr(SETTINGS_CAUSE), tr(SETTINGS_ACTION, **names)
            else:
                action = own_action or tr(DISC_ACTIONS.get(kind, DISC_ACTION) if operation == 'disc' else ACTIONS[kind],
                                          **names)
        else:
            reason = tr(REASONS[kind])
            action = tr(DISC_ACTIONS.get(kind, DISC_ACTION) if operation == 'disc' else ACTIONS[kind], **names)
        what = f'{stopped}: {_lower_first(reason)}'
        if recovered and kind != 'closed':
            action = tr(RECOVERED)
        return Explanation(code=code, what=what, cause=cause, action=action, detail=detail,
                           stage=str(stage) if stage else None, recovered=bool(recovered), kind=kind,
                           operation=operation, job=job)
    except Exception:
        kind = 'unexpected'
        return Explanation(code=code_for(operation, kind), what=f'{STOPPED.get(operation, STOPPED["launch"])}: '
                           f'{REASONS[kind]}', cause='', action=RESTART.format(play='Play'), detail=detail,
                           stage=str(stage) if stage else None, recovered=bool(recovered), kind=kind,
                           operation=operation, job=job)


def console_lines(e):
    """The label lines of one failure (the watcher log and the Play window show these)."""
    try:
        text = labels()
        lines = [f'[{e.code}] {text["what"]}: {e.what}']
        if e.cause:
            lines.append(f'{text["why"]}: {e.cause}')
        lines.append(f'{text["fix"]}: {e.action}')
        lines.append(f'{text["details"]}: {e.detail}' + (f' (step: {e.stage})' if e.stage else ''))
        if e.report:
            lines.append(f'{text["report"]}: {e.report}')
        return lines
    except Exception:
        return [f'[{getattr(e, "code", "TTM-PLAY-40")}] WHAT HAPPENED: {getattr(e, "what", "")}']


def record_lines(record):
    """The label lines of a saved failure (fail()'s owner.last_error record), to show it again later: a
    FAILED watcher repeats it once the game reaches its menus. [] for anything that is not such a record."""
    try:
        if not isinstance(record, dict) or not record.get('what'):
            return []
        text = labels()
        lines = [f'[{record.get("code") or "TTM-PLAY-38"}] {text["what"]}: {record["what"]}']
        if record.get('cause'):
            lines.append(f'{text["why"]}: {record["cause"]}')
        if record.get('action'):
            lines.append(f'{text["fix"]}: {record["action"]}')
        if record.get('report'):
            lines.append(f'{text["report"]}: {record["report"]}')
        return lines
    except Exception:
        return []


def cover_text(e):
    """Two upper-case lines for the in-game failure cover, already translated (<= 60 characters)."""
    try:
        if e.recovered:
            first = RECOVERED_COVER_LINES.get(e.operation, RECOVERED_COVER)
        else:
            first = COVER_LINES.get(e.job or e.operation, COVER_LINES['preparation'])
        first = tr(first).upper()[:COVER_LIMIT]
        second = tr(COVER_DETAIL, code=e.code).upper()[:COVER_LIMIT]
        return first, second
    except Exception:
        return COVER_LINES['preparation'], COVER_DETAIL.format(code=getattr(e, 'code', 'TTM-PLAY-40'))


def cover_title(lines):
    """The desktop cover's title for cover_text's lines: what stopped (translated), e.g. 'The rematch could
    not be loaded' for a rematch; 'Match setup stopped' when the line is not one of ours."""
    try:
        first = str(tuple(lines)[0])
        keys = ['preparation'] + [key for key in COVER_LINES if key not in ('preparation', 'launch')]
        for key in keys:
            if tr(COVER_LINES[key]).upper()[:COVER_LIMIT] == first:
                return tr(STOPPED[key])
        for key, text in RECOVERED_COVER_LINES.items():
            if tr(text).upper()[:COVER_LIMIT] == first:
                return tr(STOPPED['reload' if key == 'fighter_update' else key])
    except Exception:
        pass
    return tr(STOPPED['preparation'])


def release_frames(error):
    """Drop the local variables of a kept exception's finished frames (RAM snapshots, manifests); file
    names and line numbers stay for short() and the report. A frame still running is left alone."""
    try:
        traceback.clear_frames(error.__traceback__)
    except Exception:
        pass


# ---- the framed block (Play windows; launch-autopilot.ps1 draws the same frame) ------------------

WIDTH = 78


def wrap(text, width):
    """Greedy word wrap on single spaces; a word longer than a line is cut (Format-Bt3Block does the same)."""
    lines, current = [], ''
    for word in str(text).split(' '):
        while len(word) > width:
            if current:
                lines.append(current)
                current = ''
            lines.append(word[:width])
            word = word[width:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += ' ' + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def frame(rows):
    """rows: (text, is_path). ASCII frame 78 columns wide; a path is never wrapped (it may pass the border)."""
    inner = WIDTH - 4
    out = ['+' + '-' * (WIDTH - 2) + '+']
    for text, is_path in rows:
        pieces = [str(text)] if is_path else wrap(text, inner)
        for piece in pieces:
            out.append('| ' + piece.ljust(inner) + ' |' if len(piece) <= inner else '| ' + piece)
    out.append('+' + '-' * (WIDTH - 2) + '+')
    return out


def block(code, what, why='', fix='', file=None, details='', report=None, log=None, nothing_changed=False,
          language=None, detail_lines=()):
    """The failure block every launcher prints (Format-Bt3Block in launcher-lifecycle.ps1 is the same):
    labels in the player's language, paths and raw detail lines on their own unwrapped lines."""
    text = LABELS_ES if (language or _language()) == 'es' else LABELS
    rows = [(f'[{code}] {text["what"]}: {what}', False)]
    if why:
        rows.append((f'{text["why"]}: {why}', False))
    if fix:
        rows.append((f'{text["fix"]}: {fix}', False))
    for label, path in (('file', file), ('report', report), ('log', log)):
        if path:
            rows.append((f'{text[label]}:', False))
            rows.append((str(path), True))
    if details:
        rows.append((f'{text["details"]}: {details}', False))
    raw = [str(line).rstrip() for line in detail_lines if line is not None and str(line).strip()]
    if raw:
        rows.append((f'{text["details"]}:', False))
        rows += [(line, True) for line in raw]
    if nothing_changed:
        rows.append((text['unchanged'], False))
    rows.append((text['copy'], False))
    return frame(rows)


def _language():
    loc = _localization()
    try:
        return loc.language() if loc is not None else 'en'
    except Exception:
        return 'en'


# ---- reports --------------------------------------------------------------------------------------

def failures_folder():
    """game/analysis/failures (prototype.ROOT when a caller moved it). A unittest process that did not
    choose a folder (REPORTS) writes to a temporary one, never into a real installation."""
    if REPORTS is not None:
        return Path(REPORTS)
    if 'unittest' in sys.modules:
        import tempfile
        return Path(tempfile.gettempdir())/'tagteam-test-failures'
    root = getattr(sys.modules.get('prototype'), 'ROOT', None) or ROOT
    return Path(root)/'analysis'/'failures'


def _english(error, e, context):
    loc = _localization()
    if loc is None:
        return e
    try:
        with loc.using('en'):
            return explain(error, e.operation, e.stage, context, recovered=e.recovered)
    except Exception:
        return e


def _version():
    try:
        return json.loads((ROOT.parent/'release.json').read_text(encoding='utf-8-sig')).get('version')
    except Exception:
        return None


def _tail(path, count=60):
    try:
        return Path(path).read_bytes().decode('utf-8', 'replace').splitlines()[-count:]
    except Exception:
        return []


def write_report(e, error, context=None):
    """game/analysis/failures/<stamp>-<code>.txt with everything a diagnosis needs; the newest 10 are
    kept. Returns the path, or None when it cannot be written (a full disk must not add a failure)."""
    try:
        folder = failures_folder()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        path = folder/f'{stamp}-{e.code}.txt'
        number = 1
        while path.exists():
            number += 1
            path = folder/f'{stamp}-{e.code}-{number}.txt'
        english = _english(error, e, context)
        context = dict(context or {})
        log_folder = context.pop('log_folder', None)
        native = sys.modules.get('native_map')
        runtime = sys.modules.get('runtime_profile')
        lines = ['Tag Team Mod failure report',
                 f'Code: {e.code}', f'Time: {time.strftime("%Y-%m-%d %H:%M:%S")}',
                 f'Operation: {e.operation}' + (f' ({e.job})' if e.job else ''),
                 f'Step: {e.stage or "-"}', f'Recovered: {"yes" if e.recovered else "no"}',
                 f'What happened: {english.what}', f'Why: {english.cause or "-"}', f'How to fix: {english.action}',
                 f'Details: {e.detail}',
                 f'Mod version: {_version() or "developer tree"}',
                 f'Game: {getattr(native, "SERIAL", "?")}' + {'bt3-pal': ' (European)', 'bt3-jpn': ' (Japanese)'}.get(
                     getattr(native, 'ADAPTER', ''), ''),
                 f'PCSX2 runtime: {getattr(runtime, "NAME", "?")}',
                 f'Python: {sys.version.split()[0]} ({sys.executable})', f'System: {platform.platform()}',
                 'Context: ' + json.dumps(context, default=str, sort_keys=True),
                 '', 'Traceback:']
        lines += ''.join(traceback.format_exception(type(error), error, error.__traceback__)).rstrip().splitlines()
        if log_folder:
            lines += ['', f'Watcher log ({Path(log_folder)/"watcher.log"}), last lines:']
            lines += _tail(Path(log_folder)/'watcher.log')
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        prune(folder)
        return path
    except Exception:
        return None


def prune(folder, keep=KEEP_REPORTS):
    try:
        reports = sorted(Path(folder).glob('*-TTM-*.txt'), key=lambda p: p.name)
        for old in reports[:-keep] if keep else reports:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError:
        pass


# ---- the watcher's failure path ---------------------------------------------------------------

# A window close makes PCSX2 stop its game first: PINE then answers 'No game is running' (or refuses the connection),
# and the process itself ends 0.5 to 2.4 s later (live 2.8.2, Sept 29; slower PCs and GPU renderers take longer). A lost
# connection is judged only after this grace, so a close during the last part of match preparation is never recorded
# as a failure; a PCSX2 that is still running after the grace lost its connection for real (reported as before).
CLOSE_GRACE = 10.0


def _closing(owner, grace=None, clock=None, sleep=None):
    """True while the owned PCSX2 is closing: its PINE errors are not failures. A PCSX2 that still runs gets
    CLOSE_GRACE seconds to end first; one that keeps running lost its connection for real (reported as before)."""
    lifetime = getattr(owner, 'lifetime', None)
    if lifetime is None:
        return False
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    deadline = clock() + (CLOSE_GRACE if grace is None else grace)
    while True:
        try:
            lifetime.require_alive()
        except Exception as error:
            return 'EmulatorClosed' in _names(error)
        if clock() >= deadline:
            return False
        sleep(.1)


def _owner_context(owner, context):
    values = {}
    for name in ('state', 'mode', 'battle_mode', 'humans', 'assignment', 'playable'):
        try:
            value = getattr(owner, name, None)
            if value is None or isinstance(value, (str, int, float, bool, list, tuple, dict)) or isinstance(value, Path):
                values[name] = value if not isinstance(value, Path) else str(value)
        except Exception:
            pass
    try:
        status = getattr(owner, 'status_file', None)
        if isinstance(status, (str, Path)):
            values['log_folder'] = str(Path(status).parent)
    except Exception:
        pass
    if isinstance(context, dict):
        values.update(context)
    return values


def note_close(e):
    """What a closing PCSX2 interrupted, for diagnosis: one line on the watcher's stderr (errors.log). The Play window
    shows errors.log only when the helper stops while PCSX2 still runs, so a player's own close never shows a code."""
    try:
        print(f'{time.strftime("%H:%M:%S")} PCSX2 closed during {e.operation}: {e.code} ({e.kind}): {e.detail}',
              file=sys.stderr, flush=True)
    except Exception:
        pass


def emit(line, level):
    """One autopilot.log-format line: 'HH:MM:SS LEVEL: text'."""
    text = f'{time.strftime("%H:%M:%S")} {level.upper()}: {line}'
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        try:
            print(text.encode('ascii', 'backslashreplace').decode('ascii'), flush=True)
        except Exception:
            pass
    except Exception:
        pass


def fail(owner, operation, error, *, stage=None, context=None, cover=True, recovered=False):
    """Report one failure: a report file, one report() line, the other block lines, a sticky
    owner.last_error and (with cover) the in-game failure cover. Never raises; a closing PCSX2 is not
    a failure (no last_error, no cover, no Play window line: the watcher's own close line follows)."""
    try:
        e = explain(error, operation, stage, context, recovered=recovered)
        closing = e.kind == 'closed' or (e.kind == 'lost' and _closing(owner))
        if closing:
            # The player closed PCSX2: no 'stopped' line with an error code (live 2.8.2, Sept 29: a close during the
            # intros printed 'lost its connection (TTM-MATCH-02)'). The watcher then says PCSX2 was closed.
            note_close(e)
            return e
        path = write_report(e, error, _owner_context(owner, context))
        if path is not None:
            e = dataclasses.replace(e, report=path)
        level = 'warning' if recovered else 'error'
        record = dict(code=e.code, what=e.what, cause=e.cause, action=e.action, detail=e.detail,
                      stage=e.stage, report=str(path) if path else None, recovered=bool(recovered),
                      time=time.strftime('%Y-%m-%d %H:%M:%S'))
        previous = getattr(owner, 'last_error', None)
        if recovered and isinstance(previous, dict) and not previous.get('recovered'):
            # Never downgrade: a failure that was not recovered stays the session's outcome (exit 3); a
            # later handled problem is only counted beside it.
            previous['later_warnings'] = int(previous.get('later_warnings') or 0) + 1
            previous['last_warning'] = dict(code=e.code, what=e.what, report=record['report'], time=record['time'])
        else:
            owner.last_error = record
        owner.report(f'{e.what} ({e.code}: {e.detail})', level=level)
        text = labels()
        for line in console_lines(e)[1:]:
            if line.startswith(text['details'] + ':') and not e.stage:
                continue  # the report line above already carries the detail
            emit(line, level)
        if cover:
            first, second = cover_text(e)
            owner.cover(first, 100, error=(first, second))
        return e
    except Exception:
        try:
            owner.report(f'{operation} failed: {short(error)}', level='warning' if recovered else 'error')
        except Exception:
            pass
        return None


if __name__ == '__main__':
    for code, title in sorted(CODES.items()):
        print(code, title)
