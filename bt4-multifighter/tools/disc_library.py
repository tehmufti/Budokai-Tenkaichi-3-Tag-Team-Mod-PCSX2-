"""Mod settings > Game disc: the game discs of this installation, headless (the page is disc_page.py).

Commands (python game/tools/disc_library.py COMMAND ...; never a dialog, never tkinter):
  status          [--json] [--verify]
  add ISO         [--json] [--use] [--match-language] [--accept-modified-stages]
  use KEY|ISO     [--json] [--match-language]
  find KEY ISO    [--json]
  remove KEY      [--json] [--delete-expanded-maps]
  delete-maps KEY [--json]
  verify-active   [--json]   a child process: checks the pinned disc (TAGTEAM_DISC) with the mod's own code
Exit status: 0 done; 2 refused and explained (the block on stderr and a JSON 'error' event: nothing was changed unless
the event says committed); 1 unexpected (explained as TTM-DISC-01..11).

Layout (game_profile): the disc the installation was made with keeps its files in game/; every added disc has
game/discs/<key>/ with the files setup extracts for a disc (install_profile.prepare, the installer's own code) and a
receipt disc-files.json; game/discs/active.json is the choice. Locks: game/discs/.library.lock (one change at a
time), then Play's lease analysis/autopilot/.launcher.lock, held only for the few milliseconds of the switch itself:
the slow work (hashing, scanning, the check child) runs before it. Play never takes the library lock.

Only discs of this installation's game can be used: the three BT3 discs (USA, Europe, Japan) share the bt3-usa tools, the two
BT4 B14 REV2 discs (English, Spanish) the BT4 tools. A disc of the other game is refused (TTM-DISC-21) before anything
is hashed or written. This module never imports native_map (directly or through runtime_owner): it must work while
the chosen disc is damaged, which is exactly when the player repairs it here.
"""
import argparse
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import atomic_files
import game_profile
import player_errors
import process_identity
from localization import tr, entries, language

TOOLS = Path(__file__).resolve().parent
WINDOWS = os.name == 'nt'
SCHEMA = 1
MINIMUM_FREE = 50 << 20            # a disc's names, portraits, executable and check need about 10 MB
HASH_STEP = 64 << 20               # a progress event every 64 MiB of hashing
CHECK_TIMEOUT = 180
ISO_TIMEOUT = 2.0                  # an unplugged network or USB drive can block a stat for 20 s or more
EXPANDED_MANIFESTS = ('expanded-2x.json',)

# The refusals of this page (player_errors.DISC_CODES): what happened, why, how to fix. English keys, Spanish in
# localization.ES; {play}, {mod_settings}, {check_installation} and {build_expanded_maps} are this installation's
# launchers (localization.entry), {install} the release's setup launcher.
EXPLAIN = {
    'TTM-DISC-20': ("The game disc cannot be changed while {play} or this installation's PCSX2 is open.",
                    'The running session uses the current disc until PCSX2 closes.',
                    'Close PCSX2 and wait for the {play} window to close, then try again.'),
    'TTM-DISC-21': ('This disc is {disc}, but this installation runs {family}.',
                    'An installation contains the mod for one game only; the other game needs its own mod files, '
                    'PCSX2 profile and settings.',
                    'Install the mod for that disc into a new folder with {install} from the release download. Setup can '
                    'copy your memory cards; each installation keeps its own discs and settings.'),
    'TTM-DISC-22': ('{disc} is not enabled in this release of the mod.',
                    'This release was published without support for that disc.',
                    'Use another disc, or install a release that supports it into a new folder.'),
    'TTM-DISC-23': ('The extracted files of {disc} are missing or changed.',
                    'A file in its folder game/discs/{key} was deleted or edited, or copying it was interrupted.',
                    'In {mod_settings} > Game disc, choose Add ISO… and select that ISO again (its files are extracted '
                    'again), or use another disc.'),
    'TTM-DISC-24': ('The ISO of {disc} is no longer at its saved location.',
                    'It was moved, renamed or deleted, or its drive is not connected.',
                    'Reconnect its drive, or choose Find ISO… and select the same ISO at its new location.'),
    'TTM-DISC-25': ('The chosen file is not the ISO of {disc}.',
                    'Only the same ISO file (same contents) can be found again.',
                    "Choose that disc's ISO, or add the other file as a new disc with Add ISO…."),
    'TTM-DISC-26': ('The mod could not be prepared for {disc}.',
                    "A check of the mod's game files with this disc failed, so the disc was not added or selected.",
                    'Run {check_installation}. If it passes, send this block to the mod author.'),
    'TTM-DISC-27': ('The ISO changed while it was being checked.',
                    'Another program wrote to the file, or its download or copy had not finished.',
                    'Wait until the copy or download has finished, then choose Add ISO… again.'),
    'TTM-DISC-28': ('There is not enough free disk space to add the disc.',
                    'Its names, portraits and check need about {needed} on the drive of the Tag Team Mod folder; '
                    '{free} is free.',
                    'Free some disk space, then choose Add ISO… again.'),
    'TTM-DISC-29': ('This disc cannot be removed from the list.',
                    'It is the disc in use, or the disc this installation was made with (its files belong to the '
                    'installation).',
                    'Use another disc first; the installed disc always stays in the list.'),
    'TTM-DISC-30': ('Another {mod_settings} window is changing the game discs.',
                    'Only one window can add, switch or remove discs at a time.',
                    'Wait for it to finish or close it, then try again.'),
    'TTM-DISC-31': ('The chosen ISO is the expanded-map copy the mod made, not an original disc.',
                    'Expanded maps are built from an original ISO and follow it automatically.',
                    'Add the original ISO instead; expanded maps are turned on in {mod_settings} > Launch options '
                    '(restart).'),
    'TTM-DISC-32': ('This folder is not a player installation.',
                    'Developer folders always start the ISO in their games folder.',
                    'Use a player installation made with {install} to switch discs.'),
    'TTM-DISC-33': ('The stage files of {disc} differ from the original disc.',
                    "The disc's program is the reviewed one, but its maps were changed (a map mod, or an expanded-map "
                    'copy).',
                    'Add the original ISO instead, or confirm to add this disc anyway; expanded maps are never built '
                    'from it.'),
    'TTM-DISC-34': ('The chosen file cannot be opened.',
                    'The path is mistyped, or the file was moved or its drive is not connected.',
                    'Check the path, then choose Add ISO… again.'),
    'TTM-DISC-35': ('The expanded maps of {disc} cannot be deleted now.',
                    "They are being built, or {play} or this installation's PCSX2 is using them.",
                    'Wait for the build to finish and close PCSX2, then try again.'),
}
# Results and notes (English keys, Spanish in localization.ES).
ADDED = 'Added: {disc}.'
ALREADY = 'Already added: {disc}.'
RELOCATED = 'Already added: {disc}. Its ISO location was updated.'
REPAIRED = 'The files of {disc} were extracted again.'
SWITCHED = 'Switched to {disc}. It applies the next time you start {play}.'
UNCHANGED = '{disc} is already the disc {play} starts.'
NOT_SELECTED = 'Added {disc}, but it was not selected.'
REMOVED = 'Removed {disc} from the list. The ISO itself was not changed.'
FOUND = 'Found the ISO of {disc} again: {path}'
MAPS_DELETED = 'Deleted the expanded maps of {disc} ({size}).'
NO_MAPS = '{disc} has no expanded maps to delete.'
EUROPEAN_NOTE = 'European disc (SLES-54945): the game runs at 50 Hz, like the original European release.'
JAPANESE_NOTE = ('Japanese disc (SLPS-25815, Sparking! Meteor): its menus confirm with Circle and go back with Cross; the '
                 'game text and voices are Japanese, the fighter names in the mod are English.')
DISC_NOTES = {'bt3-pal': EUROPEAN_NOTE, 'bt3-jpn': JAPANESE_NOTE}
# The address table a translated BT3 disc runs with (install_player.ADAPTERS native_map).
TABLES = {'bt3-pal': 'pal_native_map.json', 'bt3-jpn': 'jpn_native_map.json'}
# Saves: the BT3 discs keep separate game saves, the two BT4 discs share one (notes() says only its own family's).
SAVES_NOTE_BT3 = ('Game progress is saved per disc: characters unlocked with one BT3 disc (USA, Europe or Japan) are not '
                  'unlocked with the others.')
SAVES_NOTE_BT4 = 'Both BT4 discs share one save: what you unlock with one is unlocked with the other.'
BT4_STATES = ('Both BT4 discs use the same PCSX2 save-state names: load a save state only with the disc it was made '
              'with.')
CHANGE_DISC = "PCSX2's own Change Disc during a session is not supported; switch discs here with PCSX2 closed."
MAPS_NOT_BUILT = ('Expanded maps are on, but they are not built for this disc yet: run {build_expanded_maps} before the '
                  'next {play} (about {needed}; {free} free), or the original maps are used.')
LANGUAGE_SET = "The mod's menus and messages are now in Spanish, like this disc."
POST_COMMIT = 'The switch was saved, but a follow-up step failed: {detail}'
DEVELOPER = ('This developer folder always starts the ISO in its games folder; the game disc can be changed only in a '
             'player installation.')
PROGRESS = {'identify': 'Checking the chosen file…', 'extract': 'Extracting fighter names and portraits…',
            'verify': 'Checking the mod with this disc…', 'switch': 'Switching to {disc}…',
            'relink': 'Checking the game ISO: {percent}%', 'delete': 'Deleting…'}


class Placeholders(dict):
    """format_map values: a placeholder nobody filled shows as '?' instead of raising."""

    def __missing__(self, key):
        return '?'


class Refusal(Exception):
    """A coded refusal (exit 2). committed: the change itself was saved before this step failed."""

    def __init__(self, code, file=None, details='', committed=False, **values):
        super().__init__(f'{code} {details}'.strip())
        self.code, self.file, self.details, self.values, self.committed = code, file, details, values, committed


def size_text(size):
    """'3.0 GB', '812 MB', '6 KB' (decimal units, like the file managers players use)."""
    size = float(size or 0)
    for unit, scale in (('GB', 1e9), ('MB', 1e6), ('KB', 1e3)):
        if size >= scale:
            return f'{size / scale:.1f} {unit}' if unit == 'GB' else f'{size / scale:.0f} {unit}'
    return f'{int(size)} B'


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def reparse(path):
    return game_profile._reparse(path)


def remove_tree(path):
    """Delete a folder this module made: files first, then folders deepest first. A junction or a symbolic link
    inside is removed itself (os.rmdir or os.unlink on the link), never followed. A file that cannot be deleted
    (antivirus, OneDrive) leaves the folder in place; status retries it. True when the folder is gone."""
    path = Path(path)
    if not path.exists() and not reparse(path):
        return True
    if reparse(path):
        try:
            (os.rmdir if path.is_dir() else os.unlink)(path)
            return True
        except OSError:
            return False
    folders, ok = [path], True
    for directory, names, files in os.walk(path, topdown=True, followlinks=False):
        kept = []
        for name in names:
            child = Path(directory)/name
            if reparse(child):
                try:
                    os.rmdir(child)
                except OSError:
                    try:
                        os.unlink(child)
                    except OSError:
                        ok = False
            else:
                kept.append(name)
                folders.append(child)
        names[:] = kept
        for name in files:
            try:
                os.unlink(Path(directory)/name)
            except FileNotFoundError:
                pass
            except OSError:
                try:
                    os.chmod(Path(directory)/name, stat.S_IWRITE)
                    os.unlink(Path(directory)/name)
                except OSError:
                    ok = False
    for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        try:
            os.rmdir(folder)
        except FileNotFoundError:
            pass
        except OSError:
            ok = False
    return ok and not path.exists()


def exists_within(path, timeout=ISO_TIMEOUT):
    """Whether a file exists, with a time limit: None (unknown) when the drive does not answer in time."""
    result = []
    worker = threading.Thread(target=lambda: result.append(Path(path).is_file()), daemon=True)
    worker.start()
    worker.join(timeout)
    return result[0] if result else None


def replace_retrying(source, target, timeout=5.0):
    """os.replace, retried while Windows reports a sharing violation (an antivirus scanning a new file)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)


class Library:
    """The discs of the installation whose game folder is game_profile.ROOT. emit(event) receives each event."""

    def __init__(self, emit=None):
        self.emit = emit or (lambda event: None)
        self._iso_modules = False

    # ---- paths (from game_profile.ROOT when used: tests move it)

    @property
    def game(self):
        return Path(game_profile.ROOT)

    @property
    def install(self):
        return self.game.parent

    @property
    def discs(self):
        return self.game/game_profile.DISCS

    @property
    def active_file(self):
        return self.discs/game_profile.ACTIVE

    @property
    def cache(self):
        return self.install/'compatibility-profiles'

    @property
    def lease_path(self):
        return self.game/'analysis'/'autopilot'/'.launcher.lock'

    @property
    def owner_path(self):
        return self.game/'analysis'/'autopilot'/'.owner.lock'

    @property
    def emulator(self):
        import runtime_profile
        return runtime_profile.executable(self.game/'runtime28')

    def progress(self, stage, **values):
        self.emit(dict(event='progress', stage=stage, **values))

    def iso_compatibility(self):
        if not self._iso_modules:
            if (self.install/'iso_compatibility').is_dir() and str(self.install) not in sys.path:
                sys.path.insert(0, str(self.install))
            if str(TOOLS.parent.parent) not in sys.path:
                sys.path.append(str(TOOLS.parent.parent))
            self._iso_modules = True
        import iso_compatibility.known_discs as known
        return known

    # ---- the installation

    def installation(self):
        base = game_profile.installed_profile()
        if base is None:
            raise Refusal('TTM-DISC-32')
        marker = game_profile._marker_adapter() or base['adapter']
        if marker not in game_profile.PAYLOAD:
            raise ValueError(f'player-install.json names an unknown adapter: {marker}')
        try:
            release = json.loads((self.install/'release.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            release = {}
        enabled = release.get('adapters') if isinstance(release.get('adapters'), dict) else None
        payload = game_profile.PAYLOAD[marker]
        return dict(base=base, payload=payload, installed_key=game_profile.key_of(base), release=release,
                    enabled=set(enabled) if enabled is not None else {a for a, p in game_profile.PAYLOAD.items()
                                                                       if p == payload},
                    version=str(release.get('version') or ''))

    def title(self, variant):
        known = self.iso_compatibility()
        return tr(known.TITLES[variant][0]) if variant in known.TITLES else (variant or '?')

    def family_title(self, payload):
        known = self.iso_compatibility()
        return tr(known.FAMILY_TITLES.get(payload, payload))

    def values(self, **extra):
        names = entries()
        names['install'] = 'Install.cmd' if WINDOWS else 'Install.sh'
        names.update(extra)
        return names

    # ---- locks

    def running(self):
        """'play' while a Play window holds its lease or the mod's helper owns a PCSX2, 'pcsx2' while this
        installation's PCSX2 runs, else None. Probing creates no file."""
        if process_identity.held(self.lease_path) or process_identity.held(self.owner_path):
            return 'play'
        if process_identity.running_emulators(self.emulator):
            return 'pcsx2'
        return None

    def library_lock(self):
        """discs/.library.lock: one add, switch or removal at a time (TTM-DISC-30 while another window has it)."""
        if reparse(self.discs):
            raise Refusal('TTM-DISC-23', file=self.discs, key='', disc='game/discs',
                          details='The game disc folder is a link, which the mod never follows.')
        self.discs.mkdir(parents=True, exist_ok=True)
        lock = process_identity.FileLock(self.discs/'.library.lock')
        if not lock.acquire():
            raise Refusal('TTM-DISC-30')
        return lock

    def lease(self, timeout=.5):
        """Play's launcher lease, for the switch itself (TTM-DISC-20 while a Play window holds it)."""
        self.lease_path.parent.mkdir(parents=True, exist_ok=True)
        lock = process_identity.FileLock(self.lease_path)
        deadline = time.monotonic() + timeout
        while not lock.acquire():
            if time.monotonic() >= deadline:
                raise Refusal('TTM-DISC-20')
            time.sleep(.05)
        return lock

    # ---- the discs

    def disc_record(self, key, installation):
        """(profile, receipt or None, folder) of a disc in the list; raises DiscError for a damaged added disc."""
        if key == installation['installed_key']:
            return installation['base'], None, self.game
        record = game_profile.library_disc(key, base=installation['base'])
        return record['profile'], record['receipt'], record['folder']

    def describe(self, profile, receipt=None):
        known = self.iso_compatibility()
        variant = str(profile.get('runtime_variant') or '')
        title, region, _ = known.TITLES.get(variant, (variant or '?', '', ''))
        return dict(title=tr(title), region=tr(region) if region else '', variant=variant,
                    serial=known.serial_text(profile.get('serial')), adapter=profile.get('adapter'),
                    native_language=(receipt or {}).get('native_language') or known.NATIVE_LANGUAGE.get(variant),
                    stages_modified=bool((receipt or {}).get('stages_modified')))

    def iso_of(self, profile):
        return game_profile.iso_path(profile)

    def selection(self):
        """(chosen key or None, problem): discs/active.json's key (None: the installed disc), or the DiscError of a
        damaged choice."""
        try:
            key, _ = game_profile.selection()
        except game_profile.DiscError as error:
            return None, error
        return key, None

    # ---- identify (writes nothing)

    def expanded_copy(self, path):
        """True when the ISO is an expanded-map copy made by the mod: it lies in an installation's game/maps folder,
        or a manifest beside it (or this installation's) records it as its output."""
        try:
            resolved = Path(os.path.abspath(path))
        except (OSError, ValueError):
            return False
        parts = [part.lower() for part in resolved.parts]
        if any(a == 'game' and b == 'maps' for a, b in zip(parts, parts[1:])):
            return True
        for manifest in self.manifests(resolved):
            try:
                output = json.loads(manifest.read_text(encoding='utf-8')).get('output') or {}
                named = str(output.get('path', ''))
                if os.path.normcase(named) == os.path.normcase(str(resolved)):
                    return True
                # The same file through another path (a junction, a mapped drive): compare the file itself.
                if named and os.path.isfile(named) and os.path.samefile(named, resolved):
                    return True
            except (OSError, ValueError, AttributeError):
                continue
        return False

    def manifests(self, iso=None):
        found = []
        if iso is not None:
            found += [Path(iso).parent/name for name in EXPANDED_MANIFESTS]
            found.append(Path(iso).parent.parent/'compatibility-profiles'/'expanded-maps-2x.json')
        maps = self.game/'maps'
        if maps.is_dir() and not reparse(maps):
            found.append(maps/'expanded-2x.json')
            for child in maps.iterdir():
                if child.is_dir() and not reparse(child):
                    found.append(child/'expanded-2x.json')
        return [path for path in found if path.is_file()]

    def output_sha(self, sha):
        for manifest in self.manifests():
            try:
                if json.loads(manifest.read_text(encoding='utf-8')).get('output_sha256') == sha:
                    return True
            except (OSError, ValueError, AttributeError):
                continue
        return False

    def refusal_text(self, evidence):
        known = self.iso_compatibility()
        refusal = evidence.get('refusal')
        if refusal:
            return known.message(refusal['template'], refusal.get('disc'), refusal['serial'], translate=tr)
        return str(evidence.get('reason') or 'No reviewed runtime adapter matches this disc.')

    def identify(self, path, installation):
        """(adapter, evidence) of a supported disc of this installation's game, in about a second; refusals are
        TTM-ISO-01..09 (the installer's texts), TTM-DISC-21/22/31/34. Nothing is hashed or written."""
        self.progress('identify')
        path = Path(path)
        try:
            present = path.is_file()
        except OSError:
            present = False
        if not present:
            raise Refusal('TTM-DISC-34', file=path)
        if self.expanded_copy(path):
            raise Refusal('TTM-DISC-31', file=path)
        self.iso_compatibility()
        from iso_compatibility.adapters import quick_identify
        from iso_compatibility.disc import FormatError
        try:
            adapter, evidence, _ = quick_identify(path)
        except FormatError as error:
            if error.code:
                raise Refusal(error.code, file=path, details=getattr(error, 'cause', '') or str(error),
                              **error.details) from None
            raise Refusal('TTM-ISO-09', file=path, details=str(error), reason=str(error)) from None
        except OSError as error:
            raise Refusal('TTM-DISC-34', file=path, details=player_errors.short(error)) from None
        if not evidence.get('verified'):
            raise Refusal('TTM-ISO-08', file=path, reason=self.refusal_text(evidence))
        variant = evidence.get('variant')
        if game_profile.PAYLOAD.get(adapter) != installation['payload']:
            raise Refusal('TTM-DISC-21', file=path, disc=self.title(variant),
                          family=self.family_title(installation['payload']))
        if adapter not in installation['enabled']:
            raise Refusal('TTM-DISC-22', file=path, disc=self.title(variant))
        return adapter, evidence

    # ---- add

    def scan_progress(self, line):
        found = re.fullmatch(r'Fingerprinting ISO: (\d+)%', line)
        counted = re.fullmatch(r'Checking (fighter|stage) resources: (\d+)/(\d+)', line)
        if found:
            self.progress('hash', percent=int(found.group(1)))
        elif counted:
            self.progress(counted.group(1) + 's', done=int(counted.group(2)), total=int(counted.group(3)))
        elif line == 'Using unchanged ISO compatibility profile':
            self.progress('hash', percent=100, cached=True)

    def scan(self, path, adapter):
        from iso_compatibility.scanner import scan
        from iso_compatibility.disc import FormatError
        try:
            profile = scan(path, self.cache, progress=self.scan_progress, progress_step=HASH_STEP)
        except FormatError as error:
            if 'changed while scanning' in str(error):
                raise Refusal('TTM-DISC-27', file=path, details=str(error)) from None
            if error.code:
                raise Refusal(error.code, file=path, details=str(error), **error.details) from None
            raise Refusal('TTM-ISO-09', file=path, details=str(error), reason=str(error)) from None
        identity = profile['identity']
        if not profile['capabilities']['runtime_hooks'] or identity['adapter'] != adapter:
            raise Refusal('TTM-ISO-08', file=path, reason=self.refusal_text(identity.get('runtime_match', {})))
        return profile

    def check_table(self, profile, path):
        """The European and Japanese discs run the bt3-usa tools with pal_native_map.json / jpn_native_map.json: that
        table must have been made from exactly this disc's executable and DBZP.BIN (install_player.check_native_map)."""
        identity = profile['identity']
        if identity['adapter'] not in TABLES:
            return
        table = TOOLS/TABLES[identity['adapter']]
        try:
            doc = json.loads(table.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise Refusal('TTM-DISC-26', file=table, details=player_errors.short(error),
                          disc=self.title(identity['runtime_match'].get('variant'))) from None
        members = identity['members']
        if not (doc.get('schema') == 1 and doc.get('adapter') == identity['adapter'] and
                doc.get('elf_sha256') == members.get('/' + identity['serial'] + ';1') and
                doc.get('dbzp_sha256') == members.get('/BIN/DBZP.BIN;1')):
            raise Refusal('TTM-DISC-26', file=table, details=f'The {table.name} address table was made from another '
                          'executable or DBZP.BIN.', disc=self.title(identity['runtime_match'].get('variant')))

    def free_space(self, needed=MINIMUM_FREE):
        try:
            free = shutil.disk_usage(self.game).free
        except OSError:
            return
        if free < needed:
            raise Refusal('TTM-DISC-28', needed=size_text(needed), free=size_text(free))

    def receipt_files(self, folder):
        import hashlib
        files = {}
        for directory, names, found in os.walk(folder, followlinks=False):
            names[:] = [name for name in names if not reparse(Path(directory)/name)]
            for name in found:
                path = Path(directory)/name
                relative = path.relative_to(folder).as_posix()
                if relative in (game_profile.RECEIPT, '.owner.json', game_profile.LOCATION) or reparse(path):
                    continue
                with open(path, 'rb') as stream:
                    files[relative] = hashlib.file_digest(stream, 'sha256').hexdigest()
        return files

    def extract(self, path, profile, installation, modified):
        """A new disc folder in staging (the installer's install_profile.prepare), with a pending receipt."""
        from iso_compatibility.install_profile import prepare
        from iso_compatibility.disc import FormatError
        self.progress('extract')
        staging = self.discs/f'.staging-{secrets.token_hex(4)}'
        staging.mkdir(parents=True)
        atomic_files.write_json(staging/'.owner.json', dict(pid=os.getpid(), started=process_identity.started()))
        try:
            try:
                prepare(path, staging, self.cache, progress=lambda line: self.progress('extract', line=str(line)),
                        tools=TOOLS)
            except FormatError as error:
                if 'changed' in str(error):
                    raise Refusal('TTM-DISC-27', file=path, details=str(error)) from None
                raise Refusal('TTM-ISO-09', file=path, details=str(error), reason=str(error)) from None
            identity = profile['identity']
            if json.loads((staging/'game-profile.json').read_text(encoding='utf-8'))['iso_sha256'] != identity['iso_sha256']:
                raise Refusal('TTM-DISC-27', file=path)
            match = identity.get('runtime_match', {})
            receipt = dict(schema=SCHEMA, state='pending', key=identity['iso_sha256'][:16],
                           iso_sha256=identity['iso_sha256'], adapter=identity['adapter'], variant=match.get('variant'),
                           serial=identity['serial'], pcsx2_crc=identity['pcsx2_crc'],
                           native_language=match.get('native_language'), stages_modified=bool(modified),
                           added_at=now(), added_by_release=installation['version'], verified_release=None,
                           files=self.receipt_files(staging))
            atomic_files.write_json(staging/game_profile.RECEIPT, receipt)
            return staging
        except BaseException:
            remove_tree(staging)
            raise

    def check_child(self, key):
        """Run the mod's own checks for disc `key` in a child process pinned to it (verify-active). (code, lines)."""
        self.progress('verify')
        env = dict(os.environ, BT3_RUNTIME_PROFILE='runtime28', PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        env[game_profile.PIN] = key
        env.pop('TAGTEAM_ADAPTER', None)
        options = dict(cwd=str(self.game), env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=CHECK_TIMEOUT)
        if WINDOWS:
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run([sys.executable, '-u', str(TOOLS/'disc_library.py'), 'verify-active', '--json'],
                                    **options)
        except subprocess.TimeoutExpired:
            return None, [f'The check did not finish within {CHECK_TIMEOUT} s.']
        lines = (result.stdout + result.stderr).decode('utf-8', 'replace').splitlines()
        return result.returncode, [line for line in lines if line.strip()]

    def verified(self, key, folder, receipt, installation, title):
        """Run the check child; on success the receipt says ready and names this release."""
        code, lines = self.check_child(key)
        if code != 0:
            detail = ' | '.join(lines[-6:]) or f'exit {code}'
            for line in reversed(lines):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get('event') == 'error':
                    detail = f'{event.get("code")}: {event.get("details") or event.get("what")}'
                    break
            raise Refusal('TTM-DISC-26', file=folder, details=detail, disc=title)
        receipt = dict(receipt, state='ready', verified_release=installation['version'])
        atomic_files.write_json(folder/game_profile.RECEIPT, receipt)
        return receipt

    def trash(self, folder, key):
        target = self.discs/f'.trash-{key}-{secrets.token_hex(4)}'
        replace_retrying(folder, target)
        remove_tree(target)

    def relocate(self, folder, path, sha):
        """Save where a disc's ISO is now (its iso-location.json; for the installed disc game/iso-location.json)."""
        atomic_files.write_bytes(folder/game_profile.LOCATION,
                                 (json.dumps(dict(path=str(Path(path).resolve()), sha256=sha), ensure_ascii=True,
                                             indent=2) + '\n').encode('ascii'))

    def add(self, path, use=False, match_language=False, accept_modified=False):
        """Add an ISO of this installation's game. Returns the result event (and continues with use when asked)."""
        started = time.monotonic()
        installation = self.installation()
        adapter, evidence = self.identify(path, installation)     # refusals before anything is written
        if self.running() == 'play' and use:
            raise Refusal('TTM-DISC-20')
        lock = self.library_lock()
        try:
            self.free_space()
            self.clean()
            profile = self.scan(path, adapter)
            identity = profile['identity']
            sha, key = identity['iso_sha256'], identity['iso_sha256'][:16]
            title = self.title(identity['runtime_match'].get('variant'))
            if self.output_sha(sha):
                raise Refusal('TTM-DISC-31', file=path)
            known = self.iso_compatibility()
            modified = known.stages_modified(profile)
            if modified and not accept_modified:
                raise Refusal('TTM-DISC-33', file=path, disc=title)
            self.check_table(profile, path)
            note, template = [], None
            if key == installation['installed_key']:
                current = self.iso_of(installation['base'])
                if os.path.normcase(os.path.abspath(current)) != os.path.normcase(os.path.abspath(path)):
                    self.relocate(self.game, path, sha)
                    template = RELOCATED
                else:
                    template = ALREADY
            else:
                folder = self.discs/key
                existing = None
                if folder.exists() or reparse(folder):
                    try:
                        existing = game_profile.library_disc(key, base=installation['base'])
                        game_profile.verify_files(existing)
                    except game_profile.DiscError:
                        existing = None
                if existing is not None:
                    current = self.iso_of(existing['profile'])
                    if os.path.normcase(os.path.abspath(current)) != os.path.normcase(os.path.abspath(path)):
                        self.relocate(folder, path, sha)
                        template = RELOCATED
                    else:
                        template = ALREADY
                else:
                    repair = folder.exists() or reparse(folder)
                    staging = self.extract(path, profile, installation, modified)
                    self.install_folder(staging, folder, key, installation, title)
                    template = REPAIRED if repair else ADDED
            result = dict(event='result', ok=True, action='add', key=key, message=tr(template, disc=title), notes=note,
                          disc=self.row(key, installation), seconds=round(time.monotonic() - started, 2))
        finally:
            lock.release()
        if use:
            try:
                switched = self.use(key, match_language=match_language)
            except Refusal as refusal:
                result['notes'].append(tr(NOT_SELECTED, disc=title))
                refusal.added = result
                raise
            result['action'] = 'add+use'
            if switched.get('language'):
                # The switch also changed the mod's language: the added disc's line follows it.
                result['message'] = tr(template, disc=self.title(identity['runtime_match'].get('variant')))
            result['message'] = result['message'] + ' ' + switched['message']
            result['notes'] += switched['notes']
            result['committed'] = True
        return result

    def install_folder(self, staging, folder, key, installation, title):
        """Move a staged disc into discs/<key> (still pending), run the check child pinned to it, then mark it ready.
        Only a pinned check child ever reads a pending folder, so a half-checked disc is never chosen. A damaged
        folder of the same disc goes to the trash first; for the disc Play starts, that swap happens under Play's
        lease, so its folder is never missing while a Play could start."""
        active = self.active_key(installation) == key
        lease, old = None, None
        try:
            if active:
                if self.running():
                    raise Refusal('TTM-DISC-20')
                lease = self.lease()
            if reparse(folder):
                os.rmdir(folder) if folder.is_dir() else os.unlink(folder)
            elif folder.exists():
                old = self.discs/f'.trash-{key}-{secrets.token_hex(4)}'
                replace_retrying(folder, old)
            replace_retrying(staging, folder)
        except BaseException:
            if old is not None and not folder.exists():
                try:
                    replace_retrying(old, folder)   # put the previous folder back: never leave the disc without one
                    old = None
                except OSError:
                    pass
            remove_tree(staging)
            raise
        finally:
            if lease is not None:
                lease.release()
        if old is not None:
            remove_tree(old)   # after the lease: Play waits only for the two renames
        receipt = json.loads((folder/game_profile.RECEIPT).read_text(encoding='utf-8'))
        try:
            self.verified(key, folder, receipt, installation, title)
        except BaseException:
            if not active:
                self.trash(folder, key)
            raise
        try:
            (folder/'.owner.json').unlink()
        except OSError:
            pass

    # ---- use

    def target_key(self, target, installation):
        text = str(target)
        if game_profile.KEY.fullmatch(text) or text == installation['installed_key']:
            return text
        if Path(text).suffix.lower() == '.iso' or Path(text).exists():
            return None
        raise Refusal('TTM-DISC-23', key=text, disc=text, details=f'No game disc with the key {text!r}.')

    def use(self, target, match_language=False):
        """Make a disc of the list the one Play starts. The slow checks run first, without Play's lease; the switch
        itself is one compare-and-swap write of discs/active.json under the lease."""
        started = time.monotonic()
        installation = self.installation()
        key = self.target_key(target, installation)
        if key is None:
            return self.add(target, use=True, match_language=match_language)
        installed = key == installation['installed_key']
        if self.active_key(installation) == key:
            try:
                profile = self.disc_record(key, installation)[0]
                title = self.title(profile.get('runtime_variant'))
            except game_profile.DiscError:
                title = self.folder_title(key)
            return dict(event='result', ok=True, action='use', key=key, committed=False, notes=[],
                        message=tr(UNCHANGED, **self.values(disc=title)), disc=self.row(key, installation),
                        seconds=round(time.monotonic() - started, 2))
        if self.running():
            raise Refusal('TTM-DISC-20')
        lock = self.library_lock()
        try:
            before = self.read_active()
            try:
                profile, receipt, folder = self.disc_record(key, installation)
                if receipt is not None:
                    game_profile.verify_files(dict(key=key, installed=False, folder=folder, receipt=receipt))
            except game_profile.DiscError as error:
                raise Refusal('TTM-DISC-23', file=getattr(error, 'file', None), details=str(error), key=key,
                              disc=self.folder_title(key)) from None
            title = self.title(profile.get('runtime_variant'))
            if profile['adapter'] not in installation['enabled']:
                raise Refusal('TTM-DISC-22', disc=title)
            iso = self.iso_of(profile)
            if not installed and exists_within(iso) is False:
                raise Refusal('TTM-DISC-24', file=iso, disc=title)
            if receipt is not None and receipt.get('verified_release') != installation['version']:
                receipt = self.verified(key, folder, receipt, installation, title)
            self.progress('switch', disc=title)
            lease = self.lease()
            try:
                if process_identity.held(self.owner_path) or process_identity.running_emulators(self.emulator):
                    raise Refusal('TTM-DISC-20')
                if self.read_active() != before:
                    raise Refusal('TTM-DISC-30')
                if receipt is not None:
                    game_profile.library_disc(key, base=installation['base'])
                atomic_files.write_json(self.active_file, dict(schema=SCHEMA, key=key, iso_sha256=profile['iso_sha256'],
                                                               adapter=profile['adapter'], switched_at=now()))
            except game_profile.DiscError as error:
                raise Refusal('TTM-DISC-23', details=str(error), key=key, disc=title) from None
            finally:
                lease.release()
        finally:
            lock.release()
        # After the commit: failures here are warnings of a saved switch, never "nothing was changed". The language is
        # saved first, so the title, every note and the message are in the language the player just chose.
        warnings, language_set = [], None
        if match_language and self.describe(profile, receipt).get('native_language') == 'es':
            try:
                import mod_settings
                if mod_settings.load_settings().get('language') != 'es':
                    mod_settings.save_settings({'language': 'es'})
                    language_set = 'es'
            except Exception as error:  # noqa: BLE001
                warnings.append(tr(POST_COMMIT, detail=player_errors.short(error)))
        title = self.title(profile.get('runtime_variant'))
        notes = self.notes(key, profile, receipt, installation)
        try:
            self.write_reports(profile, folder, installed)
        except Exception as error:  # noqa: BLE001
            warnings.append(tr(POST_COMMIT, detail=player_errors.short(error)))
        if language_set:
            notes.append(tr(LANGUAGE_SET, 'es'))
        return dict(event='result', ok=True, action='use', key=key, committed=True, language=language_set,
                    message=tr(SWITCHED, **self.values(disc=title)), notes=notes, warnings=warnings,
                    disc=self.row(key, installation), seconds=round(time.monotonic() - started, 2))

    def read_active(self):
        try:
            return game_profile._read_bytes(self.active_file)
        except FileNotFoundError:
            return None

    def active_key(self, installation):
        key, problem = self.selection()
        if problem is not None:
            return None
        return key or installation['installed_key']

    def folder_title(self, key):
        if not game_profile.KEY.fullmatch(str(key)) or reparse(self.discs) or reparse(self.discs/key):
            return str(key)
        try:
            profile = json.loads((self.discs/key/'game-profile.json').read_text(encoding='utf-8'))
            return self.title(profile.get('runtime_variant'))
        except (OSError, ValueError, AttributeError):
            return key

    def notes(self, key, profile, receipt, installation):
        notes = [tr(SAVES_NOTE_BT4 if profile['adapter'].startswith('bt4') else SAVES_NOTE_BT3), tr(CHANGE_DISC)]
        if profile['adapter'] in DISC_NOTES:
            notes.insert(0, tr(DISC_NOTES[profile['adapter']]))
        if profile['adapter'].startswith('bt4'):
            notes.insert(0, tr(BT4_STATES))
        try:
            import mod_settings
            maps_on = bool(mod_settings.load_settings().get('expanded_maps'))
        except Exception:  # noqa: BLE001
            maps_on = False
        if maps_on and not self.maps_built(key, installation):
            try:
                size = Path(self.iso_of(profile)).stat().st_size
            except OSError:
                size = 3 << 30
            try:
                free = shutil.disk_usage(self.game).free
            except OSError:
                free = 0
            notes.append(tr(MAPS_NOT_BUILT, **self.values(needed=size_text(size), free=size_text(free))))
        return notes

    def write_reports(self, profile, folder, installed):
        """game/COMPATIBILITY.md and the installation's COMPATIBILITY.md describe the disc Play starts."""
        self.iso_compatibility()
        from iso_compatibility.scanner import report
        source = self.cache/(profile['iso_sha256'] + '.json')
        if source.is_file():
            text = report(json.loads(source.read_text(encoding='utf-8')))
        elif (folder/'COMPATIBILITY.md').is_file() and not installed:
            text = (folder/'COMPATIBILITY.md').read_text(encoding='utf-8')
        else:
            return
        for target in (self.game/'COMPATIBILITY.md', self.install/'COMPATIBILITY.md'):
            atomic_files.write_bytes(target, text.encode('utf-8'))

    # ---- find, remove, expanded maps

    def find(self, key, path):
        """The same ISO (same SHA-256) of a disc in the list, at a new location."""
        installation = self.installation()
        lock = self.library_lock()
        try:
            try:
                profile, receipt, folder = self.disc_record(key, installation)
            except game_profile.DiscError as error:
                raise Refusal('TTM-DISC-23', details=str(error), key=key, disc=self.folder_title(key)) from None
            title = self.title(profile.get('runtime_variant'))
            if key == self.active_key(installation) and self.running():
                raise Refusal('TTM-DISC-20')
            if not Path(path).is_file():
                raise Refusal('TTM-DISC-34', file=path)
            self.iso_compatibility()
            from iso_compatibility.scanner import hash_file
            try:
                sha = hash_file(path, lambda line: self.scan_progress(line), HASH_STEP)
            except OSError as error:
                raise Refusal('TTM-DISC-34', file=path, details=player_errors.short(error)) from None
            if sha != profile['iso_sha256']:
                raise Refusal('TTM-DISC-25', file=path, disc=title)
            self.relocate(folder, path, sha)
            return dict(event='result', ok=True, action='find', key=key, committed=True, notes=[],
                        message=tr(FOUND, disc=title, path=str(Path(path).resolve())), disc=self.row(key, installation))
        finally:
            lock.release()

    def maps_folder(self, key, installation):
        return self.game/'maps' if key == installation['installed_key'] else self.game/'maps'/key

    def maps_built(self, key, installation):
        folder = self.maps_folder(key, installation)
        return (folder/'expanded-2x.json').is_file() and (folder/'expanded-2x.iso').is_file()

    def maps_size(self, folder):
        total = 0
        for name in ('expanded-2x.iso', 'expanded-2x.json'):
            try:
                total += (folder/name).stat().st_size
            except OSError:
                pass
        return total

    def delete_maps(self, key, locked=False):
        """Delete one disc's expanded-map build (the files its own manifest names): about 3 GB each."""
        installation = self.installation()
        key = str(key)
        if key != installation['installed_key'] and not game_profile.KEY.fullmatch(key):
            # Only a disc key names a maps folder (game/maps/<key>): never a path such as '..'.
            raise Refusal('TTM-DISC-23', key=key, disc=key, details=f'No game disc with the key {key!r}.')
        lock = None if locked else self.library_lock()
        try:
            folder = self.maps_folder(key, installation)
            title = self.folder_title(key) if key != installation['installed_key'] else \
                self.title(installation['base'].get('runtime_variant'))
            if not self.maps_built(key, installation) and not (folder/'expanded-2x.iso').exists():
                return dict(event='result', ok=True, action='delete-maps', key=key, committed=False, notes=[],
                            message=tr(NO_MAPS, disc=title))
            if self.running():
                raise Refusal('TTM-DISC-35', **self.values(disc=title))
            build = process_identity.FileLock(folder/'.build.lock')
            if (folder/'.build.lock').exists() and not build.acquire(create=False):
                raise Refusal('TTM-DISC-35', **self.values(disc=title))
            try:
                size = self.maps_size(folder)
                manifest = folder/'expanded-2x.json'
                output = folder/'expanded-2x.iso'
                try:
                    named = json.loads(manifest.read_text(encoding='utf-8')).get('output', {}).get('path')
                except (OSError, ValueError, AttributeError):
                    named = None
                if output.exists() and named and os.path.normcase(os.path.abspath(named)) == \
                        os.path.normcase(os.path.abspath(output)):
                    output.unlink()
                if manifest.exists():
                    manifest.unlink()
            finally:
                build.release()
            if folder != self.game/'maps':
                for name in ('.build.lock',):
                    try:
                        (folder/name).unlink()
                    except OSError:
                        pass
                try:
                    folder.rmdir()
                except OSError:
                    pass
            return dict(event='result', ok=True, action='delete-maps', key=key, committed=True, notes=[],
                        message=tr(MAPS_DELETED, disc=title, size=size_text(size)))
        finally:
            if lock is not None:
                lock.release()

    def remove(self, key, delete_maps=False):
        installation = self.installation()
        lock = self.library_lock()
        try:
            active = self.active_key(installation)
            if key in (installation['installed_key'], active):
                raise Refusal('TTM-DISC-29')
            if self.running():
                raise Refusal('TTM-DISC-20')
            folder = self.discs/key
            if not game_profile.KEY.fullmatch(str(key)) or not (folder.exists() or reparse(folder)):
                raise Refusal('TTM-DISC-23', key=key, disc=key, details=f'No game disc with the key {key!r}.')
            title = self.folder_title(key)
            notes = []
            if delete_maps:
                notes.append(self.delete_maps(key, locked=True)['message'])
            if reparse(folder):
                os.rmdir(folder) if folder.is_dir() else os.unlink(folder)
            else:
                self.trash(folder, key)
            return dict(event='result', ok=True, action='remove', key=key, committed=True, notes=notes,
                        message=tr(REMOVED, disc=title))
        finally:
            lock.release()

    # ---- status

    def clean(self):
        """Remove abandoned staging folders (their owner is gone) and leftover trash. Runs under the library lock.
        A game/discs that is a link is never walked (the library lock refuses it too)."""
        if not self.discs.is_dir() or reparse(self.discs):
            return
        for child in self.discs.iterdir():
            name = child.name
            if name.startswith('.trash-'):
                remove_tree(child)
            elif name.startswith('.staging-'):
                try:
                    owner = json.loads((child/'.owner.json').read_text(encoding='utf-8'))
                    live = process_identity.alive(owner.get('pid'), owner.get('started'))
                except (OSError, ValueError, AttributeError):
                    live = False
                if not live:
                    remove_tree(child)
            elif game_profile.KEY.fullmatch(name) and (child/'.owner.json').is_file():
                try:
                    receipt = json.loads((child/game_profile.RECEIPT).read_text(encoding='utf-8'))
                    owner = json.loads((child/'.owner.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if receipt.get('state') == 'pending' and not process_identity.alive(owner.get('pid'), owner.get('started')):
                    if child.name != self.selection()[0]:
                        self.trash(child, name)

    def leftovers(self):
        if not self.discs.is_dir() or reparse(self.discs):
            return False
        for child in self.discs.iterdir():
            if child.name.startswith(('.trash-', '.staging-')) or (child/'.owner.json').is_file():
                return True
        return False

    def row(self, key, installation, verify=False, active=None):
        installed = key == installation['installed_key']
        active = self.active_key(installation) if active is None else active
        row = dict(key=key, installed=installed, active=key == active, files='ok', iso=None, iso_present=None,
                   expanded_maps_built=self.maps_built(key, installation), added_at=None,
                   maps_bytes=self.maps_size(self.maps_folder(key, installation)))
        try:
            profile, receipt, folder = self.disc_record(key, installation)
            if receipt is not None:
                row['added_at'] = receipt.get('added_at')
                if verify:
                    game_profile.verify_files(dict(key=key, installed=False, folder=folder, receipt=receipt))
        except game_profile.DiscError as error:
            row.update(files='damaged', problem=str(error), title=self.folder_title(key), serial='', region='',
                       adapter=None, iso_sha256=None)
            try:
                receipt = json.loads((self.discs/key/game_profile.RECEIPT).read_text(encoding='utf-8'))
                if receipt.get('state') == 'pending':
                    row['files'] = 'pending'
            except (OSError, ValueError, AttributeError):
                pass
            return row
        row.update(self.describe(profile, receipt), iso_sha256=profile.get('iso_sha256'))
        row['iso'] = self.iso_of(profile)
        row['iso_present'] = exists_within(row['iso']) if row['iso'] else False
        return row

    def status(self, verify=False):
        try:
            installation = self.installation()
        except Refusal:
            return dict(event='status', schema=SCHEMA, installation=dict(developer=True, note=tr(DEVELOPER)),
                        active=None, installed=None, running=None, discs=[], problems=[], orphans=[],
                        language=language())
        if self.leftovers():
            lock = process_identity.FileLock(self.discs/'.library.lock')
            if lock.acquire():
                try:
                    self.clean()
                finally:
                    lock.release()
        key, problem = self.selection()
        active = None if problem is not None else (key or installation['installed_key'])
        keys = [installation['installed_key']]
        rows = []
        if self.discs.is_dir() and not reparse(self.discs):
            for child in sorted(self.discs.iterdir()):
                if game_profile.KEY.fullmatch(child.name) and child.name != installation['installed_key']:
                    keys.append(child.name)
        for disc in keys:
            rows.append(self.row(disc, installation, verify=verify, active=active))
        rows[1:] = sorted(rows[1:], key=lambda row: (row.get('added_at') or '', row['key']))
        problems = []
        if problem is not None:
            problems.append(self.problem('TTM-PLAY-46', problem))
        elif active is not None and active not in keys:
            problems.append(self.problem('TTM-PLAY-46', game_profile.DiscError(f'The chosen game disc {active} is not in the list.')))
        for row in rows:
            if row['files'] == 'damaged' and row['active']:
                problems.append(self.problem('TTM-DISC-23', row.get('problem'), disc=row.get('title'), key=row['key']))
        orphans = []
        maps = self.game/'maps'
        if maps.is_dir() and not reparse(maps):
            for child in sorted(maps.iterdir()):
                if child.is_dir() and game_profile.KEY.fullmatch(child.name) and child.name not in keys:
                    orphans.append(dict(key=child.name, bytes=self.maps_size(child), folder=str(child)))
        family = self.family_title(installation['payload'])
        experimental = [label for adapter, label in (installation['release'].get('adapters') or {}).items()
                        if game_profile.PAYLOAD.get(adapter) == installation['payload'] and 'experimental' in str(label)]
        return dict(event='status', schema=SCHEMA,
                    installation=dict(payload=installation['payload'], family_title=family, developer=False,
                                      experimental=bool(experimental), version=installation['version']),
                    active=active, installed=installation['installed_key'], running=self.running(), discs=rows,
                    problems=problems, orphans=orphans, language=language())

    def problem(self, code, error, **values):
        what, why, fix = self.texts(code, values)
        return dict(code=code, what=what, why=why, fix=fix, details=str(error) if error else '')

    # ---- texts

    def texts(self, code, values):
        names = Placeholders(self.values(**{k: v for k, v in values.items() if v is not None}))
        fill = lambda text: tr(text).format_map(names) if text else ''
        if code in EXPLAIN:
            return tuple(fill(text) for text in EXPLAIN[code])
        if code == 'TTM-PLAY-46':
            return (fill('The game disc chosen in {mod_settings} cannot be used.'),
                    fill('Its extracted files are missing or changed, or the selection file game/discs/active.json is '
                         'damaged.'),
                    fill('Open {mod_settings} > Game disc and choose a disc again (the disc you installed with always '
                         'works), then start {play} again.'))
        catalogue = self.catalogue()
        if catalogue is not None and code in catalogue.catalog().get('codes', {}):
            lang = language()
            return tuple(catalogue.text(code, part, lang, **values) for part in ('what', 'why', 'fix'))
        self.iso_compatibility()
        from iso_compatibility.disc import IMAGE_TEXT
        try:
            what = IMAGE_TEXT[code].format(**values) if code in IMAGE_TEXT else str(values.get('reason') or code)
        except (KeyError, IndexError, ValueError):
            what = str(values.get('reason') or code)
        return what, '', ''

    def catalogue(self):
        """The installer's message catalogue (setup_messages.py and messages.json beside game/), or None."""
        path = self.install/'setup_messages.py'
        if not path.is_file():
            return None
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location('installed_setup_messages', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:  # noqa: BLE001 - plain English then
            return None

    def error_event(self, error):
        if isinstance(error, Refusal):
            code, values = error.code, dict(error.values)
            what, why, fix = self.texts(code, values)
            committed = error.committed or bool(getattr(error, 'added', None))
            block = player_errors.block(code, what, why, fix, file=error.file, details=error.details,
                                        nothing_changed=not committed)
            event = dict(event='error', code=code, what=what, why=why, fix=fix,
                         file=str(error.file) if error.file else None, details=error.details,
                         nothing_changed=not committed, committed=committed, block=block)
            if getattr(error, 'added', None):
                event['added'] = error.added
            return event
        explained = player_errors.explain(error, 'disc')
        block = player_errors.block(explained.code, explained.what, explained.cause, explained.action,
                                    details=explained.detail)
        return dict(event='error', code=explained.code, what=explained.what, why=explained.cause,
                    fix=explained.action, file=None, details=explained.detail, nothing_changed=False,
                    committed=False, block=block)


# ---- the check child ----------------------------------------------------------------------------------------------

def verify_active(emit):
    """The mod's own checks with the pinned disc, as Play's probe runs them (autopilot.py --check 'game files'):
    the adapter and executable (the European table against it), the native guards, the boot hook, the names and
    portraits, the kill-feed labels and the mod settings. Runs in a child process: native_map resolves the disc at
    import."""
    if not os.environ.get(game_profile.PIN):
        raise ValueError('verify-active checks the disc named by TAGTEAM_DISC; it was not set.')
    record = game_profile.resolve()
    if record is None:
        raise Refusal('TTM-DISC-32')
    game_profile.verify_files(record)
    import native_map
    profile = record['profile']
    if native_map.SERIAL_FILE != profile.get('serial'):
        raise ValueError(f'The tools resolved {native_map.SERIAL_FILE}, but the disc boots {profile.get("serial")}.')
    elf = native_map.elf_path(game_profile.ROOT)
    if not elf.is_file() or record['folder'] not in elf.parents:
        raise ValueError(f'The executable of the chosen disc is not where the tools read it: {elf}')
    if native_map.TRANSLATED:
        native_map.table()
    import autopilot
    autopilot.native_guards()
    import guest_loading_screen
    guest_loading_screen.pnach()
    import character_names
    table = character_names.character_table()
    if not table:
        raise ValueError('The fighter names of the chosen disc cannot be read.')
    for row in table.values():
        info = character_names.character_info(row['character_id'])
        if info['bitmap_path'] and not Path(info['bitmap_path']).is_file():
            raise ValueError(f'A portrait of the chosen disc is missing: {info["bitmap_path"]}')
    import guest_killfeed
    guest_killfeed.name_data({i: row.get('name', '') for i, row in table.items()})
    import mod_settings
    mod_settings.load_settings()
    if (TOOLS/'bt4_preflight.py').is_file():
        import bt4_preflight
        bt4_preflight.check()
    import game_profile as profiles
    emit(dict(event='result', ok=True, action='verify-active', key=record['key'], adapter=record['adapter'],
              serial=native_map.SERIAL, crc=profiles.pcsx2_crc(), fighters=len(table)))


# ---- command line -------------------------------------------------------------------------------------------------

def printer(as_json):
    """The event sink: JSON lines (ASCII) on stdout, or the player's text."""
    def emit(event):
        if as_json:
            print(json.dumps(event), flush=True)
            return
        kind = event.get('event')
        try:
            if kind == 'progress':
                stage = event.get('stage')
                if stage == 'hash':
                    print(tr('Checking the game ISO: {percent}%', percent=event.get('percent', 0)), flush=True)
                elif stage in ('fighters', 'stages'):
                    template = f'Checking {stage[:-1]} resources: {{done}}/{{total}}'
                    print(tr(template, done=event.get('done'), total=event.get('total')), flush=True)
                elif stage in PROGRESS and 'line' not in event:
                    print(tr(PROGRESS[stage], **{k: v for k, v in event.items() if k not in ('event', 'stage')}),
                          flush=True)
            elif kind == 'result':
                for line in [event.get('message')] + list(event.get('notes') or []) + list(event.get('warnings') or []):
                    if line:
                        print(line, flush=True)
            elif kind == 'status':
                print(json.dumps(event, ensure_ascii=False, indent=2), flush=True)
            elif kind == 'error':
                print('\n'.join(event['block']), file=sys.stderr, flush=True)
        except UnicodeEncodeError:
            print(json.dumps(event), flush=True)
    return emit


def parser():
    result = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = result.add_subparsers(dest='command', required=True)
    status = commands.add_parser('status')
    status.add_argument('--verify', action='store_true', help="Re-hash every added disc's files")
    add = commands.add_parser('add')
    add.add_argument('iso', type=Path)
    add.add_argument('--use', action='store_true')
    add.add_argument('--match-language', action='store_true')
    add.add_argument('--accept-modified-stages', action='store_true')
    use = commands.add_parser('use')
    use.add_argument('target')
    use.add_argument('--match-language', action='store_true')
    find = commands.add_parser('find')
    find.add_argument('key')
    find.add_argument('iso', type=Path)
    remove = commands.add_parser('remove')
    remove.add_argument('key')
    remove.add_argument('--delete-expanded-maps', action='store_true')
    maps = commands.add_parser('delete-maps')
    maps.add_argument('key')
    commands.add_parser('verify-active')
    for command in commands.choices.values():
        command.add_argument('--json', action='store_true', help='One JSON object per line (for the settings page)')
    return result


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='backslashreplace')
        except (AttributeError, ValueError, OSError):
            pass
    args = parser().parse_args(argv)
    if args.command != 'verify-active':
        # An entry point: an inherited pin never decides which disc these commands change.
        os.environ.pop(game_profile.PIN, None)
        game_profile.forget()
    emit = printer(args.json)
    library = Library(emit)
    result = None
    try:
        if args.command == 'status':
            result = library.status(verify=args.verify)
        elif args.command == 'add':
            result = library.add(args.iso, use=args.use, match_language=args.match_language,
                                 accept_modified=args.accept_modified_stages)
        elif args.command == 'use':
            result = library.use(args.target, match_language=args.match_language)
        elif args.command == 'find':
            result = library.find(args.key, args.iso)
        elif args.command == 'remove':
            result = library.remove(args.key, delete_maps=args.delete_expanded_maps)
        elif args.command == 'delete-maps':
            result = library.delete_maps(args.key)
        else:
            verify_active(emit)
    except Refusal as refusal:
        return report(emit, library.error_event(refusal), 2)
    except Exception as error:  # noqa: BLE001 - one explained failure, never a bare traceback
        event = library.error_event(error)
        if args.command == 'verify-active':
            event['traceback'] = ''.join(__import__('traceback').format_exception(error))[-2000:]
        return report(emit, event, 1)
    if result is None:
        return 0
    try:
        emit(result)
    except Exception:  # noqa: BLE001 - the action is done; only its report could not be written
        # The action itself succeeded (a switch, an add or a removal is saved) and only its report could not be
        # written (a closed pipe): that is never turned into an error event saying the disc "could not be changed".
        # The caller re-reads the discs. Only a status that could not be written fails.
        return 1 if result.get('event') == 'status' else 0
    return 0


def report(emit, event, code):
    """Emit a refusal or failure event; when even that cannot be written (a closed pipe), the exit code tells."""
    try:
        emit(event)
    except Exception:  # noqa: BLE001
        pass
    return code


if __name__ == '__main__':
    raise SystemExit(main())
