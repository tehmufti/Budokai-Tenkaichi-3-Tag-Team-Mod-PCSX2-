# Development guide

## Edit and test

Make changes in a fork. Keep native addresses, resource layouts and execution
timing specific to their adapters. A matching disc serial by itself does not
prove a different executable is safe. Do not disable adapter guards to make an
unknown image appear supported.

`python scripts/test_source.py` runs portable scanner, installer, runtime and
online tests. Cases needing a supplied disc or locally extracted executable
are explicitly skipped when that input is absent. Historical RAM captures
and tests tied to those captures are not in this snapshot.
Hardware input, cameras, performance and full-match behavior still require
playtests. Do not describe a synthetic test as live gameplay validation.

The Workbench reads models/animations from a locally supplied original BT3
disc and offers scenario authoring and live-trainer telemetry. Install its
optional GUI requirements before running `tools/modder_gui.py`. The source
snapshot contains no downloaded or extracted character models.

To try edited runtime files, use a separate installation made by the player
installer. Its `game/tools` folder contains the selected adapter's modules.
Copy only the files you intentionally changed, preserve its `player-install.json`
and local settings, and fully restart the launcher. Native-hook changes can
require reinstalling/regenerating the boot patch; old save states are not a
reliable way to validate new hooks. Keep your regular installation and saves
separate from development tests.

## Build an installer

1. Install `requirements-dev.txt` and run `scripts/fetch_dependencies.py`.
2. Supply the original USA, European and Japanese BT3 disc images locally.
   The default filenames are documented in `release_tools/build_pal_map.py`.
   They go in ignored `games/`, or use the `TAGTEAM_USA_ISO`, `TAGTEAM_PAL_ISO`
   and `TAGTEAM_JPN_ISO` environment variables with absolute paths.
3. Update `player-installer/release.json` and the changelog for your build.
4. Run `python release_tools/verify_bt4_port.py`. After reviewing intentional
   differences, `--record` refreshes the port receipt. It checks shared gameplay
   policies rather than copying USA addresses over BT4.
5. Run `python release_tools/package_player_installer.py`.

The packager validates regional address tables against the supplied discs,
checks pinned dependency hashes, and builds Windows and Linux installers with
the same player payload. Outputs go to ignored `releases/`.
The European/Japanese generators read disc files locally; native executables
and decrypted game files must never be committed.

## Build an updater

After verifying a full installer, run:

```sh
python release_tools/package_player_updater.py "/path/to/Tag Team Mod 0.1.0-beta.11.2.zip"
python release_tools/package_player_updater.py "/path/to/Tag Team Mod 0.1.0-beta.11.2 linux-x86_64.tar.gz"
```

The updater builder verifies the installer manifest, keeps its exact payload, and
omits the dependency wheels. Test update and rollback on a separate installation
before publishing. Dependency-lock changes require the full installer.

## Online

The online implementation has its own pinned guest modules. Edits must preserve
the scheduling and handshake contract on every participating client. Compare
state hashes through a real match and rematch, including disconnect and loading
failures, after changes that affect native state or execution order.

The host's **If a player fails to load** policy defaults to cancelling the start.
**Drop and continue** removes failed guests and schedules CPU control for their
fighters. Losing the host stops the session. The server-browser UI is currently
hidden; direct host-address joining remains available.

## Keep the repository clean

Do not commit ISOs, BIOS, save states, memory cards, emulator binaries, personal
settings, tokens, logs, captures, test installations or generated dependency
wheels. Review both the diff and newly added files before publishing. Preserve
third-party licenses and animation attribution. Use neutral examples in docs
and tests; redact usernames, local paths and private addresses from reports.
