"""Resolve the optional expanded-map ISO before starting PCSX2."""
import os
from pathlib import Path
import sys
import mod_settings
from localization import tr

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iso_compatibility.expanded_maps import installed,SOURCE,OUTPUT,MANIFEST
import game_profile
# The developer tree's paths. An installation's paths belong to the game disc chosen in Mod settings > Game disc
# and are resolved when used (paths()): a settings window follows a switch, and a damaged choice never breaks the
# import (Play explains it: exit 4).
SOURCE,OUTPUT,MANIFEST=(game_profile.ROOT.parent/'games/SLUS_219.78.DBZBT4B14REV2ENG.iso',game_profile.ROOT/'maps/expanded-2x.iso',game_profile.ROOT/'maps/expanded-2x.json')
DEFAULTS=(SOURCE,OUTPUT,MANIFEST)


MISSING='Expanded maps are on, but the expanded ISO is missing or out of date. Starting the original ISO; run Build expanded maps.cmd first.'
MODIFIED='This game disc was added although its stage files differ from the original disc, so expanded maps are not built from it.'
BUILDING='Expanded maps are already being built or deleted for this game disc. Wait for it to finish.'


def paths():
    """(original ISO, expanded-map ISO, manifest) of the chosen game disc."""
    return game_profile.map_paths(*DEFAULTS)


def expanded_ready():
    """Whether the expanded-map ISO is built and still matches its manifest."""
    return installed(*paths()) is not None


def selected_iso(settings=None, checked=False):
    """The ISO to boot. A missing expanded build never stops a launch: the
    original ISO starts instead, with a warning on stderr (stdout is the path)."""
    if not checked: game_profile.check()
    source,output,manifest=paths()
    values=mod_settings.load_settings() if settings is None else settings
    if not values.get('expanded_maps',False):return source
    if installed(source,output,manifest) is None:
        message=tr(MISSING,values)
        try:print(message,file=sys.stderr)
        except UnicodeEncodeError:print(message.encode('ascii','replace').decode(),file=sys.stderr)
        return source
    return output


def build_lock(output):
    """One expanded-map build per disc (maps/.build.lock or maps/<key>/.build.lock): Mod settings > Game disc never
    deletes a build that is still being written. None in a developer tree."""
    if game_profile.installed() is None:return None
    from process_identity import FileLock
    output.parent.mkdir(parents=True,exist_ok=True)
    lock=FileLock(output.parent/'.build.lock')
    if not lock.acquire():
        raise ValueError(tr(BUILDING))
    return lock


def main(argv=None):
    """Exit 0 with the ISO path as the last stdout line (--json: a JSON string, ASCII-safe for PowerShell),
    2 when the installed game ISO fails its check, 4 when the game disc chosen in Mod settings cannot be used
    (the TTM-PLAY-46 block is on stderr), 1 when the expanded-map build or selection fails."""
    import json
    argv=sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout,sys.stderr):
        try:stream.reconfigure(errors='backslashreplace')
        except (AttributeError,ValueError,OSError):pass
    build='--build' in argv
    if build:
        # Build expanded maps is an entry point: it builds for the disc chosen now, never an inherited pin.
        os.environ.pop(game_profile.PIN,None)
        game_profile.forget()
    try:
        if not build:game_profile.check()
        chosen=paths()   # once per run: a switch during a build never mixes two discs
    except game_profile.DiscError as error:
        print('\n'.join(game_profile.disc_block(error)),file=sys.stderr);return 4
    except (OSError,ValueError) as error:
        print(str(error),file=sys.stderr);return 2 if not build else 1
    try:
        if build:
            from iso_compatibility.expanded_maps import build as build_maps
            if game_profile.stages_modified():raise ValueError(tr(MODIFIED))
            lock=build_lock(chosen[1])
            try:build_maps(*chosen)
            finally:
                if lock is not None:lock.release()
            print(tr('Expanded maps built: {path}',path=chosen[1]))
        else:
            path=selected_iso(checked=True)
            print(json.dumps(str(path)) if '--json' in argv else path)
    except game_profile.DiscError as error:
        print('\n'.join(game_profile.disc_block(error)),file=sys.stderr);return 4
    except (OSError,ValueError) as error:
        print(str(error),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
