# Budokai Tenkaichi Tag Team Mod for PCSX2

Simultaneous fighters, teams and free-for-all battles for Budokai Tenkaichi 3,
with split-screen for up to four local players and an experimental online mode.
The mod also supports reviewed European and Japanese BT3 discs and BT4 B14 REV2
English/Spanish adapters.

## Play

Download the **Version 13 installer** from [Releases](https://github.com/tehmufti/Budokai-Tenkaichi-3-Tag-Team-Mod-PCSX2-/releases/tag/v0.1.0-beta.13).
Windows and Linux x86-64 downloads are available. Existing installations can use the
separate **Updater** download: extract it, run Update, and choose the installed mod folder.
Settings, saves, online profiles and edited scenarios are preserved; replaced files are backed up.
Keep everyone in an online room on the same release. Supply your own compatible
game disc image, PS2 BIOS and PCSX2 installation; none is included here.
The release includes English and Spanish mod interfaces.

This is a beta. The installer checks structural compatibility; that does not
mean every character, costume, stage and move has been playtested. Online peers
must use the same compatible disc, mod build and agreed settings.

Version 13 expands offline tag-team rush attacks for BT3 USA and BT4, with
character-specific beams, more varied melee endings, CPU tag attacks and an
Early Goku / Early Piccolo grab variant. Fill both meters and press charge ki +
Triangle + Left; a teammate targeting the same enemy accepts with the same input.
Mod Settings includes live pictures for HUD and other visual options.
Giants cannot use tag attacks, and tag attacks are not available online.

Fusion settings also let you set separate health, damage and defense bonuses for
Potara and non-Potara fusions. Both are off by default. They apply to fusions
performed during the match; choosing a fused character keeps its normal stats.

The HUD and online menus now follow the game's own style. Tag meters sit below
each player's health bar, and HUD settings offer Native or Classic target markers.

## Source layout

| Folder | Purpose |
| --- | --- |
| `bt3-multifighter/tools` | BT3 runtime, native hooks, cameras, AI, HUD and Workbench |
| `bt4-multifighter/tools` | BT4 runtime and its resource-loader adaptations |
| `bt3-multifighter/online` | Online lobby, deterministic session and pinned guest modules |
| `iso_compatibility` | Disc scanner, adapter checks and expanded-map tools |
| `player-installer` | Windows/Linux installer source, locked dependency records and notices |
| `release_tools` | Payload packaging, region-table generation and port checks |
| `scripts` | Dependency bootstrap and tests that need no emulator |

The BT3 and BT4 trees intentionally retain the existing layout so changes can
be installed and compared without changing the trainer's import behavior.
Online's `netplay/modtools` is a pinned guest implementation, not a spare copy:
changing it can alter the code that participating clients execute.
The small `analysis` inputs are authored patch-upgrade receipts used by guards;
they are not RAM dumps or session logs.

## Development

Use 64-bit Python 3.11 on Windows. Linux player installations also support the
Python versions listed in `player-installer/dependencies-linux.json`.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux:   source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/test_source.py
```

To fetch the pinned build dependencies and blank online-card templates:

```sh
python scripts/fetch_dependencies.py
```

An existing Version 13 Windows ZIP can be used instead of downloading it:

```sh
python scripts/fetch_dependencies.py --release-zip "/path/to/Tag Team Mod 0.1.0-beta.13.zip"
```

Downloaded wheels, DLLs, cards, private preferences and generated output are
ignored by Git. The optional native Workbench dependencies are separate:

```sh
python -m pip install -r bt3-multifighter/requirements-gui.txt
python bt3-multifighter/tools/modder_gui.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for building installers, working on region
adapters, using an installed game's runtime, and validating changes.

## Development source and downloads

Version 13 is available in Releases. Main may receive further development changes;
use the release tag for the source behind the installers and updaters.
Choose a new version before distributing a modified build.

## License

The mod's original code is **GPL-3.0-only**. Distributed derivatives must comply
with GPLv3, including its source-availability requirements. Third-party assets
and libraries retain their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
