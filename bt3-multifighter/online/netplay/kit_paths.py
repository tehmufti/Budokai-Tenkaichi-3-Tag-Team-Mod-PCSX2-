"""Where everything of the TTM Online Kit lives (all paths are inside the kit folder) and the import setup.

  <kit>/Play online.cmd, Play online.sh, README - Play online.txt, LEAME - Jugar en linea.txt
  <kit>/netplay/            this code (kit_*.py, the lockstep session) and netplay/modtools (the Tag Team Mod
                            beta.41 modules that build a netplay match: netplay_core, netplay_view, hub_mode, ...)
  <kit>/match/              the runtime pnach of each accepted Tag Team Mod build family (beta.35..42), the memory
                            cards every PC starts from, the PCSX2.ini template
  <kit>/pcsx2/              PCSX2 2.8.2 (unmodified release copy, GPL-3.0: pcsx2/docs/GPL.html)
Created while it runs (never anywhere else):
  <kit>/data/               kit-settings.json (where the game ISO and the BIOS are), python-path.txt
  <kit>/states/             netplay matches built or received (by sha256), reused when both PCs already have one
  <kit>/matches/            matches the host's game made (reused when the same match starts again)
  <kit>/prep/               the host's private copy of its Tag Team Mod installation (it makes the matches)
  <kit>/runs/<date-time>/   logs of each session (console log, per-update state hashes, summary)
  <kit>/linux/PCSX2/        on Linux only: the data folder of the PCSX2 AppImage the player gives with --pcsx2
                            (XDG_CONFIG_HOME=<kit>/linux; the player's own PCSX2 settings are not touched)
  <kit>/data/session.json   the running session process {port, token, pid} (a new lobby window re-attaches to it)
Development only: TTM_KIT_RUNTIME=DIR puts every folder the kit writes (data, states, matches, prep, runs, linux) and
the PCSX2 it starts (DIR/pcsx2, a copy) under DIR, so two test 'PCs' can share one code tree.

Kit 2.1, INSIDE A TAG TEAM MOD INSTALLATION (the mod's installer puts the online files in <installation>/online and
'Play online.cmd' / 'Play online.sh' next to Play.cmd): INSTALL_ROOT is that installation; the kit takes the game ISO
and the BIOS from it (kit_install.read_installation), its PCSX2 is <installation>/online/pcsx2 (the installer's copy of
the installation's own PCSX2 build: the online profile, memory cards and states never touch the offline ones), and
everything it writes stays in <installation>/online (data/profile.json: the online settings, separate from the mod's
mod-settings.json). Nothing has to be chosen on the start screen.
"""
import os
import sys
from pathlib import Path

NETPLAY = Path(__file__).resolve().parent
KIT = NETPLAY.parent
MODTOOLS = NETPLAY / 'modtools'
MATCH = KIT / 'match'
RUNTIME = MATCH / 'runtime'
INI_TEMPLATE = MATCH / 'PCSX2.ini.template'
RUNTIME_ROOT = Path(os.environ['TTM_KIT_RUNTIME']).resolve() if os.environ.get('TTM_KIT_RUNTIME') else KIT
PCSX2 = RUNTIME_ROOT / 'pcsx2'
DATA = RUNTIME_ROOT / 'data'
STATES = RUNTIME_ROOT / 'states'
MATCHES = RUNTIME_ROOT / 'matches'
PREP = RUNTIME_ROOT / 'prep'
RUNS = RUNTIME_ROOT / 'runs'
LINUX = RUNTIME_ROOT / 'linux'
SETTINGS = DATA / 'kit-settings.json'
INSTALL_ROOT = KIT.parent if KIT.name == 'online' and (KIT.parent / 'game' / 'player-install.json').is_file() else None
INTEGRATED = INSTALL_ROOT is not None              # kit 2.1: the online part of a Tag Team Mod installation
PYTHON_TXT = DATA / 'python-path.txt'


def setup():
        from kit_adapter import bootstrap
        global ADAPTER
        ADAPTER = bootstrap(sys.modules[__name__])


setup()
