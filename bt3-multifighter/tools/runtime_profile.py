"""Explicit portable runtime selection, inherited by all launcher helpers."""
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
# Desktop settings can run outside Play.cmd. Installer-owned profiles only ship
# runtime28; do not point their rebind dialog at a nonexistent developer runtime.
NAME=os.environ.get('BT3_RUNTIME_PROFILE','runtime28' if (ROOT/'player-install.json').is_file() else 'runtime128')
# runtime28 is only the player folder's name: it runs any PCSX2 2.x from the minimum in
# pcsx2_versions.json on. runtime128 is the developer runtime and stays on one audited build.
VERSIONS={'runtime128':'PCSX2 v2.5.211 (developer)','runtime28':'PCSX2 2.x player runtime (pcsx2_versions.json)'}
if NAME not in VERSIONS:raise ValueError('Unknown BT3 portable runtime profile')
WINDOWS=os.name=='nt'


def executable(directory,windows=None):
    """The emulator in a portable runtime folder: pcsx2-qt.exe on Windows, the official AppImage elsewhere."""
    windows=WINDOWS if windows is None else windows
    return Path(directory)/('pcsx2-qt.exe' if windows else 'pcsx2-qt.AppImage')


def data_directory(directory,windows=None):
    """PCSX2's data folder (inis, bios, cheats, sstates, memcards, logs) for a runtime folder.

    Portable PCSX2 on Windows keeps it beside pcsx2-qt.exe. An AppImage started with -portable
    uses dirname($APPIMAGE)/PCSX2 instead (Pcsx2Config.cpp, PCSX2 2.6 and 2.8).
    """
    windows=WINDOWS if windows is None else windows
    return Path(directory) if windows else Path(directory)/'PCSX2'


DIRECTORY=ROOT/NAME
EXECUTABLE=executable(DIRECTORY)
DATA=data_directory(DIRECTORY)
CONFIG=DATA/'inis/PCSX2.ini'
STATES=DATA/'sstates'
CHEATS=DATA/'cheats'


def require_version(version):
    """Check the PINE version string ('PCSX2 v2.8.2', 'PCSX2 v2.7.361', ...) for this runtime."""
    import pcsx2_versions as versions  # loaded on use: importing this module never needs the data file
    if NAME=='runtime28':
        if not versions.player_accepts(version):
            raise ValueError(f"This installation's PCSX2 ({NAME}) must be {versions.player_requirement()}; it reports {version}")
    elif not versions.developer_accepts(version):
        raise ValueError(f'The developer PCSX2 ({NAME}) must be v{versions.text(versions.policy()["developer"])}; it reports {version}')
