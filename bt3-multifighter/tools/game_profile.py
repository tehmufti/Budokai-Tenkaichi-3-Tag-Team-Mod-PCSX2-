"""Paths for an installer-owned ISO; developer folders retain their defaults.

The game disc (Mod settings > Game disc, disc_library.py). The disc an installation was made with keeps its
hash-locked files where setup put them: game-profile.json, analysis/<boot file>, assets/ and the mutable
iso-location.json. Every disc added later has its own folder discs/<key>/ (key: the first 16 hex digits of the ISO's
SHA-256) with the same files and a receipt disc-files.json, and discs/active.json names the disc Play starts. Without
active.json, or with one that names the installed disc, everything resolves exactly as in beta.33.

Play resolves the disc once (game_profile.py --where) and pins every child process to it with TAGTEAM_DISC. A pin is
authoritative: one that names no usable disc is a DiscError, never a quiet fallback to active.json or to the
installed disc (that would mix two discs in one session). Every reader of a disc file goes through this module:
analysis_dir(), assets_dir(), reference(), iso_path(), map_paths() and native_map.elf_path(ROOT).
"""
import json
import os
import re
import stat
import time
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ADAPTERS=('bt3-usa','bt3-pal','bt3-jpn','bt4-b14-rev2-eng')
# The payload (tools folder) that runs each adapter, as install_player.ADAPTERS[adapter]['payload']: one
# installation switches only between discs of one payload family.
PAYLOAD={'bt3-usa':'bt3-usa','bt3-pal':'bt3-usa','bt3-jpn':'bt3-usa','bt4-b14-rev2-eng':'bt4-b14-rev2-eng'}
# Mutable: where the installed ISO is now, after the player moved it (game-profile.json is hash-locked).
LOCATION='iso-location.json'
PIN='TAGTEAM_DISC'
# Folder and file names under ROOT. Paths are built from ROOT when used: tests move ROOT.
DISCS='discs'
ACTIVE='active.json'
RECEIPT='disc-files.json'
KEY=re.compile('[0-9a-f]{16}')
_pinned={}


class DiscError(ValueError):
    """The game disc chosen in Mod settings cannot be used: game/discs/active.json is damaged, the disc's folder
    game/discs/<key> is missing or changed, or TAGTEAM_DISC names no usable disc. Play explains it as TTM-PLAY-46,
    Check installation as TTM-CHECK-19."""
    code='TTM-PLAY-46'
    check_code='TTM-CHECK-19'
    # What is wrong, as a fixed word Check installation translates (its message is English detail): missing,
    # changed, unreadable, link, selection, family or incomplete.
    KINDS=('missing','changed','unreadable','link','selection','family','incomplete')

    def __init__(self,message,key=None,file=None,kind='changed'):
        super().__init__(message)
        self.key=key
        self.file=str(file) if file else None
        self.kind=kind if kind in self.KINDS else 'changed'
        self.details={}


def _reparse(path):
    """A junction or a symbolic link: never followed into, never trusted as a disc folder."""
    try:info=os.lstat(path)
    except OSError:return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _read_bytes(path):
    """A small record written with os.replace by another process: read with delete sharing and retried while Windows
    reports a sharing violation (atomic_files)."""
    import atomic_files
    return atomic_files._retry(lambda:atomic_files.read_bytes(path))


def _record(path,key=None):
    try:
        value=json.loads(_read_bytes(path).decode('utf-8-sig'))
    except FileNotFoundError:
        raise DiscError(f'A file of the chosen game disc is missing: {path}',key,path,'missing') from None
    except (OSError,ValueError,UnicodeError) as error:
        raise DiscError(f'A file of the chosen game disc cannot be read: {path} ({error})',key,path,'unreadable') from None
    if not isinstance(value,dict):
        raise DiscError(f'A file of the chosen game disc is damaged: {path}',key,path)
    return value


def installed_profile():
    """game-profile.json of the disc the installation was made with (hash-locked); None in a developer tree."""
    path=ROOT/'game-profile.json'
    if not path.exists():return None
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema')!=1 or value.get('adapter') not in ADAPTERS:
        raise ValueError('Invalid installed game profile; run the installer in a new folder.')
    return value


def key_of(profile):
    """A disc's key: the first 16 hex digits of its ISO's SHA-256 (None without a valid one)."""
    sha=str((profile or {}).get('iso_sha256') or '').lower()
    return sha[:16] if re.fullmatch('[0-9a-f]{64}',sha) else None


def installed_key():
    return key_of(installed_profile())


def _marker_adapter():
    marker=ROOT/'player-install.json'
    return json.loads(marker.read_text(encoding='utf-8')).get('adapter') if marker.is_file() else None


def _pin():
    return os.environ.get(PIN,'').strip() or None


def selection():
    """(key, source) of the chosen disc: TAGTEAM_DISC when set, else game/discs/active.json, else (None, None)."""
    pin=_pin()
    if pin is not None:return pin,PIN
    folder=ROOT/DISCS
    if _reparse(folder):
        raise DiscError(f'The game disc folder is a link, which the mod never follows: {folder}',None,folder,'link')
    path=folder/ACTIVE
    try:raw=_read_bytes(path)
    except FileNotFoundError:return None,None
    except OSError as error:
        raise DiscError(f'The game disc selection cannot be read: {path} ({error})',None,path,'selection') from None
    try:
        value=json.loads(raw.decode('utf-8-sig'))
        key=value.get('key') if isinstance(value,dict) and value.get('schema')==1 else None
    except (ValueError,UnicodeError):
        key=None
    if not isinstance(key,str) or not KEY.fullmatch(key):
        raise DiscError(f'The game disc selection is damaged: {path}',None,path,'selection')
    return key,ACTIVE


def library_disc(key,allow_pending=False,base=None):
    """The record of an added disc discs/<key> (cheap checks only: JSON records, family, receipt state, no hashing).
    Raises DiscError. The installed disc is never a library disc."""
    if not isinstance(key,str) or not KEY.fullmatch(key):
        raise DiscError(f'{key!r} is not the key of a game disc.',None,ROOT/DISCS,'selection')
    base=installed_profile() if base is None else base
    discs=ROOT/DISCS
    folder=discs/key
    if _reparse(discs) or _reparse(folder):
        raise DiscError(f'The folder of the chosen game disc is a link, which the mod never follows: {folder}',key,folder,'link')
    if not folder.is_dir():
        raise DiscError(f'The folder of the chosen game disc is missing: {folder}',key,folder,'missing')
    profile=_record(folder/'game-profile.json',key)
    if profile.get('schema')!=1 or profile.get('adapter') not in ADAPTERS or key_of(profile)!=key:
        raise DiscError(f'The game profile of the chosen game disc is damaged: {folder/"game-profile.json"}',key,folder)
    try:
        family=PAYLOAD[_marker_adapter() or base['adapter']]
    except (OSError,ValueError,KeyError,TypeError) as error:
        raise DiscError(f'This installation does not name its game: {error}',key,ROOT/'player-install.json','family') from None
    if PAYLOAD[profile['adapter']]!=family:
        raise DiscError(f'The chosen game disc ({profile["adapter"]}) belongs to another game than this installation '
                        f'({family}).',key,folder,'family')
    receipt=_record(folder/RECEIPT,key)
    state=receipt.get('state')
    if (receipt.get('schema')!=1 or receipt.get('iso_sha256')!=profile.get('iso_sha256') or
            receipt.get('adapter')!=profile['adapter'] or not isinstance(receipt.get('files'),dict) or
            state not in ('ready','pending') or (state=='pending' and not allow_pending)):
        raise DiscError(f'The chosen game disc was not added completely: {folder/RECEIPT}',key,folder/RECEIPT,'incomplete')
    return dict(key=key,installed=False,folder=folder,profile=profile,adapter=profile['adapter'],receipt=receipt)


def resolve():
    """The chosen disc: dict(key, installed, folder, profile, adapter[, receipt]). installed=True is the disc the
    installation was made with (its files in this folder). None in a developer tree. Raises DiscError.

    A process pinned by TAGTEAM_DISC resolves once and keeps that answer for its whole life, so a folder damaged
    during a session never fails deep inside the watcher. An unpinned process (the settings window) resolves on
    every call and follows a switch."""
    pin=_pin()
    memo=(str(ROOT),pin)
    if pin is not None and memo in _pinned:return _pinned[memo]
    base=installed_profile()
    if base is None:return None
    key,source=selection()
    installed_=key_of(base)
    if key is None or key==installed_:
        record=dict(key=installed_,installed=True,folder=ROOT,profile=base,adapter=base['adapter'])
    else:
        record=library_disc(key,allow_pending=source==PIN,base=base)
    if pin is not None:_pinned[memo]=record
    return record


def forget():
    """Drop the pinned resolution (tests; a pinned process never needs it)."""
    _pinned.clear()


def verify_files(record):
    """Re-hash an added disc's files against its receipt (about 6-9 MB). DiscError when one is missing, changed or
    reached through a link. The installed disc's files belong to installed-files.json (Check installation)."""
    import hashlib
    if record is None or record['installed']:return
    folder=record['folder']
    for name,digest in sorted(record['receipt']['files'].items()):
        relative=Path(name)
        path=folder/relative
        if relative.is_absolute() or '..' in relative.parts or not name:
            raise DiscError(f'The receipt of the chosen game disc names a file outside its folder: {name}',record['key'],folder/RECEIPT)
        parent=folder
        for part in relative.parts:
            parent=parent/part
            if _reparse(parent):
                raise DiscError(f'A file of the chosen game disc is reached through a link: {parent}',record['key'],parent,'link')
        try:
            with open(path,'rb') as stream:found=hashlib.file_digest(stream,'sha256').hexdigest()
        except FileNotFoundError:
            raise DiscError(f'A file of the chosen game disc is missing: {path}',record['key'],path,'missing') from None
        except OSError as error:
            raise DiscError(f'A file of the chosen game disc cannot be read: {path} ({error})',record['key'],path,'unreadable') from None
        if found!=digest:
            raise DiscError(f'A file of the chosen game disc was changed: {path}',record['key'],path)


def installed():
    """The chosen disc's game profile (the installed disc's game-profile.json, or discs/<key>/game-profile.json);
    None in a developer tree."""
    record=resolve()
    return record['profile'] if record else None


def active_key():
    """The key of the disc Play starts now: the pin, else discs/active.json, else the installed disc's."""
    key,_=selection()
    return key or installed_key()


def disc_dir():
    """The chosen disc's folder: this game folder for the installed disc (and a developer tree), else discs/<key>."""
    record=resolve()
    return record['folder'] if record else ROOT


def analysis_dir():
    return disc_dir()/'analysis'


def assets_dir():
    return disc_dir()/'assets'


def reference(name):
    """A reference file extracted from the chosen disc (DBZ4.BIN, DBZP.BIN, character-parameters.bin)."""
    return analysis_dir()/name


def stages_modified():
    """True when the chosen disc was added although its stage files differ from the original disc (expanded maps
    are never built from it)."""
    record=resolve()
    return bool(record and not record['installed'] and record['receipt'].get('stages_modified'))


def installed_adapter():
    """The chosen disc's adapter (its game profile, else player-install.json); None in a developer tree. The
    installation's marker and the chosen disc must belong to one payload family (bt3-pal and bt3-jpn run the bt3-usa
    tools)."""
    profile=installed()
    marker=ROOT/'player-install.json'
    value=json.loads(marker.read_text(encoding='utf-8')).get('adapter') if marker.is_file() else None
    if profile:
        if value is not None and PAYLOAD.get(value)!=PAYLOAD[profile['adapter']]:
            raise ValueError('player-install.json and game-profile.json name different games; reinstall in a new folder.')
        return profile['adapter']
    if value is not None and value not in ADAPTERS:
        raise ValueError('Invalid player-install.json adapter; run the installer in a new folder.')
    return value


def _folder_of(profile):
    """The folder that holds a disc's iso-location.json: this game folder for the installed disc, else discs/<key>."""
    key=key_of(profile)
    if key and key!=installed_key() and (ROOT/DISCS/key).is_dir():return ROOT/DISCS/key
    return ROOT


def iso_path(profile=None):
    """The chosen (or the given) disc's ISO path: its iso-location.json when it names the same file (its sha256
    equals the profile's iso_sha256) and that file exists, else the profile's (an ISO moved back to its added place
    is found again). None in a developer tree."""
    if profile is None:
        record=resolve()
        if not record:return None
        profile,folder=record['profile'],record['folder']
    else:
        folder=_folder_of(profile)
    if not profile:return None
    path=profile['iso']
    expected=str(profile.get('iso_sha256') or '').lower()
    try:
        location=json.loads((folder/LOCATION).read_text(encoding='utf-8-sig'))
        if (expected and isinstance(location,dict) and isinstance(location.get('path'),str)
                and str(location.get('sha256','')).lower()==expected and Path(location['path']).is_file()):
            path=location['path']
    except (OSError,ValueError,UnicodeError):
        pass
    return path


def source_iso(default):
    profile=installed()
    return Path(iso_path(profile)).resolve() if profile else Path(default).resolve()


class RelinkRefused(ValueError):
    """The chosen file is not the installed ISO (different contents)."""


def relink(path,progress=None):
    """Point the chosen disc at its moved ISO. Only the same file is accepted: its SHA-256 must equal the disc's
    iso_sha256 (which also fixes the adapter). Writes that disc's iso-location.json atomically."""
    import hashlib,tempfile
    record=resolve()
    if record is None:raise ValueError('This installation has no game profile; only an installed mod can relink its ISO.')
    path=Path(path).resolve()
    size=path.stat().st_size;digest=hashlib.sha256();done=0;mark=0
    with open(path,'rb') as stream:
        while block:=stream.read(8<<20):
            digest.update(block);done+=len(block)
            if progress is not None and done>=mark:
                progress(done*100//max(size,1));mark=done+max(size//10,1)
    value=digest.hexdigest()
    if value!=str(record['profile'].get('iso_sha256') or '').lower():
        raise RelinkRefused('The chosen file is not the installed game ISO (its contents differ).')
    folder=record['folder']
    target=folder/LOCATION
    fd,temporary=tempfile.mkstemp(prefix=LOCATION+'.',suffix='.tmp',dir=folder)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(dict(path=str(path),sha256=value),stream,ensure_ascii=True,indent=2);stream.write('\n')
        os.replace(temporary,target)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return path


@lru_cache(maxsize=1)
def pcsx2_crc():
    """Selected disc identity for PINE, cheats and savestate filenames.

    Patch manifests retain the adapter's internal ID; that is independent of
    this emulator identifier. Repackaging an otherwise identical ELF can
    change its CRC. The installer records it only after runtime validation.
    """
    from native_map import CRC
    profile=installed()
    value=profile.get('pcsx2_crc',CRC) if profile else CRC
    if not isinstance(value,str) or not re.fullmatch('[0-9A-Fa-f]{8}',value):
        raise ValueError('Invalid PCSX2 game identifier in installed profile')
    return value.upper()


def cheat_name(serial):
    return f'{serial}_{pcsx2_crc()}_BT3Loading.pnach'


def map_paths(default_source,default_output,default_manifest):
    """(original ISO, expanded-map ISO, its manifest) of the chosen disc: the installed disc keeps maps/expanded-2x.*,
    an added disc builds into maps/<key>/. A developer tree keeps the defaults."""
    record=resolve()
    if record:
        folder=ROOT/'maps' if record['installed'] else ROOT/'maps'/record['key']
        return Path(iso_path(record['profile'])).resolve(),folder/'expanded-2x.iso',folder/'expanded-2x.json'
    return Path(default_source),Path(default_output),Path(default_manifest)


def disc_title(profile,settings=None):
    """The translated full title of a disc (known_discs.TITLES), else its variant label."""
    variant=str((profile or {}).get('runtime_variant') or (profile or {}).get('variant') or '')
    try:
        import sys
        if str(ROOT.parent) not in sys.path:sys.path.insert(0,str(ROOT.parent))
        from iso_compatibility.known_discs import TITLES
        from localization import tr
        return tr(TITLES[variant][0],settings) if variant in TITLES else variant or '?'
    except Exception:  # noqa: BLE001 - a title is presentation only
        return variant or '?'


def where():
    """The disc Play starts, for the launchers (game_profile.py --where --json). An added disc's files are re-hashed
    here (about 6-9 MB): the launchers' next step, the Python probe, loads that disc's executable, and a damaged one
    must be TTM-PLAY-46 before it, never a probe failure that reads as a broken private Python (TTM-PLAY-25)."""
    record=resolve()
    if record is None:
        return dict(player=False,key=None,installed_key=None,installed=None,adapter=None,serial=None,variant=None,
                    title=None,iso=None,iso_present=None)
    verify_files(record)
    profile=record['profile']
    iso=iso_path(profile)
    return dict(player=True,key=record['key'],installed_key=installed_key(),installed=record['installed'],
                adapter=record['adapter'],serial=profile.get('serial'),variant=profile.get('runtime_variant'),
                title=disc_title(profile),iso=iso,iso_present=Path(iso).is_file())


def scan_progress(line):
    """The ISO scan's progress on stderr in the player's language. An unchanged profile says nothing: the check
    runs on every launch, and the line would only be English noise in the Play window."""
    import sys
    if line=='Using unchanged ISO compatibility profile':return
    from localization import tr
    found=re.fullmatch(r'Fingerprinting ISO: (\d+)%',line)
    counted=re.fullmatch(r'Checking (fighter|stage) resources: (\d+)/(\d+)',line)
    if found:line=tr('Checking the game ISO: {percent}%',percent=found.group(1))
    elif counted:line=tr(f'Checking {counted.group(1)} resources: {{done}}/{{total}}',done=counted.group(2),total=counted.group(3))
    print(line,file=sys.stderr,flush=True)


def check(refresh=False):
    record=resolve()
    if record is None:return None
    import sys
    sys.path.insert(0,str(ROOT.parent))
    from iso_compatibility.scanner import scan,report
    from localization import tr,entries
    verify_files(record)
    value=scan(iso_path(record['profile']),refresh=refresh,progress=scan_progress)
    changed=not value['capabilities']['runtime_hooks'] or value['identity']['adapter']!=record['adapter']
    if record['installed']:
        if changed:
            raise ValueError('Selected ISO no longer matches its installed runtime adapter. Install it in a new folder.')
        if value['identity']['iso_sha256']!=record['profile']['iso_sha256']:
            raise ValueError(tr('Selected ISO changed since installation. Add it in {mod_settings} > Game disc to refresh '
                                'portraits, resources and native references, or put the original ISO back.',**entries()))
    elif changed or value['identity']['iso_sha256']!=record['profile']['iso_sha256']:
        raise ValueError(tr('The ISO of {disc} changed since it was added. Add it again in {mod_settings} > Game disc.',
                            disc=disc_title(record['profile']),**entries()))
    if value['identity']['pcsx2_crc']!=pcsx2_crc():
        raise ValueError('Installed PCSX2 identifier differs from the scanned ISO. Reinstall to refresh the game profile.')
    # A switch made while this scan ran (Scan compatibility during Mod settings > Game disc) keeps the new disc's report.
    if active_key()==record['key']:
        (ROOT/'COMPATIBILITY.md').write_text(report(value),encoding='utf-8')
    return value


def disc_block(error):
    """The TTM-PLAY-46 block for a DiscError (the launchers print it verbatim)."""
    import player_errors
    from localization import tr,entries
    names=entries()
    return player_errors.block('TTM-PLAY-46',tr('The game disc chosen in {mod_settings} cannot be used.',**names),
                               tr('Its extracted files are missing or changed, or the selection file '
                                  'game/discs/active.json is damaged.'),
                               tr('Open {mod_settings} > Game disc and choose a disc again (the disc you installed with '
                                  'always works), then start {play} again.',**names),
                               file=getattr(error,'file',None),details=player_errors.short(error),nothing_changed=True)


def main(argv=None):
    """Scan compatibility (no arguments), --relink PATH, or --where [--json] (the disc Play starts); one result line,
    or an explained failure. Exit status: 0 done; 2 the ISO check failed, --relink got another file (TTM-PLAY-44),
    or the chosen game disc cannot be used (TTM-PLAY-46); 1 --relink could not read the chosen path (TTM-PLAY-22/23)."""
    import argparse,sys
    for stream in (sys.stdout,sys.stderr):
        try:stream.reconfigure(errors='backslashreplace')
        except (AttributeError,ValueError,OSError):pass
    parser=argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--relink',type=Path,help='The moved game ISO (only the same file is accepted)')
    parser.add_argument('--where',action='store_true',help='Print the game disc Play starts')
    parser.add_argument('--json',action='store_true',help='With --where: one ASCII JSON line')
    args=parser.parse_args(argv)
    # An entry point: a pin inherited from another session never decides; this run resolves (and pins) itself.
    os.environ.pop(PIN,None)
    forget()
    from localization import tr,entries
    import player_errors
    names=entries()
    if args.where:
        try:
            found=where()
        except DiscError as error:
            print('\n'.join(disc_block(error)),file=sys.stderr,flush=True)
            return 2
        if args.json:
            print(json.dumps(found),flush=True)
        elif found['player']:
            print(tr('Game disc: {disc}',disc=found['title']),flush=True)
            print(tr('ISO: {path}',path=found['iso']),flush=True)
        else:
            print('This developer tree has no installed game profile; Play starts the ISO in its games folder.',flush=True)
        return 0
    try:
        if args.relink:
            found=relink(args.relink,progress=lambda percent:print(tr('Checking the game ISO: {percent}%',percent=percent),
                                                                  file=sys.stderr,flush=True))
            print(tr('The game ISO is linked again: {path}',path=found),flush=True)
            try:
                import mod_settings
                if mod_settings.load_settings().get('expanded_maps') and names['build_expanded_maps']:
                    print(tr('Expanded maps are on: build them again with {build_expanded_maps} (they were made from the old location).',**names),flush=True)
            except Exception:
                pass
            return 0
        if check(refresh=True) is None:
            print('This developer tree has no installed game profile; nothing was scanned.',flush=True)
        else:
            print(tr('Compatibility report updated: {path}',path=ROOT/'COMPATIBILITY.md'),flush=True)
        return 0
    except DiscError as error:
        print('\n'.join(disc_block(error)),file=sys.stderr,flush=True)
        return 2
    except RelinkRefused as error:
        rows=player_errors.block('TTM-PLAY-44',tr('The chosen file is not the installed game ISO.'),
                                 tr('Only the same ISO file (same contents) can be used.'),
                                 tr('Choose the same ISO file again, or add another ISO in {mod_settings} > Game disc.',**names),
                                 file=args.relink,details=str(error),nothing_changed=True)
        print('\n'.join(rows),file=sys.stderr,flush=True)
        return 2
    except Exception as error:  # noqa: BLE001 - one explained failure, never a bare traceback
        if args.relink and isinstance(error,OSError):
            # A mistyped or unreadable path: nothing was linked (exit 1; 2 means another file).
            rows=player_errors.block('TTM-PLAY-22',tr('The chosen file cannot be opened.'),
                                     tr('The path is mistyped, or the file was moved or its drive is not connected.'),
                                     tr('Check the path, then start {play} again and choose the game ISO again.',**names),
                                     file=args.relink,details=player_errors.short(error),nothing_changed=True)
            print('\n'.join(rows),file=sys.stderr,flush=True)
            return 1
        missing=isinstance(error,FileNotFoundError)
        rows=player_errors.block('TTM-PLAY-22' if missing else 'TTM-PLAY-23',
                                 tr('The game ISO is no longer at its saved location.' if missing else 'The game ISO could not be checked.'),
                                 tr('It was moved, renamed or deleted, or its drive is not connected.') if missing else '',
                                 tr('Put it back or reconnect its drive, or choose its new location when {play} asks.',**names) if missing else
                                 tr('Read the message above. If you replaced the ISO, add the new file in {mod_settings} > Game disc and use it.',**names),
                                 file=getattr(error,'filename',None),details=player_errors.short(error),nothing_changed=True)
        print('\n'.join(rows),file=sys.stderr,flush=True)
        return 1 if args.relink else 2


if __name__=='__main__':raise SystemExit(main())
