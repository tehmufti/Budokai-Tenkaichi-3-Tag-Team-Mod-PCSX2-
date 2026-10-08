# ISO compatibility and expanded maps

These tools read local PS2 ISO files. They never start PCSX2 or connect to PINE.

## Compatibility scanner

Double-click `the local project\Scan ISO compatibility.cmd` and choose an ISO, or drop
an ISO onto it. CLI: `python -m iso_compatibility "path\game.iso" --refresh`.

Reports and machine-readable profiles are in `the local project\compatibility-profiles`.
Profiles use a full ISO SHA-256, loaded executable/add-on fingerprints (ignoring unloaded ELF metadata), the disc's own volume
index, and per-resource SHA-256 hashes. Subsequent scans reuse a cache only when
the source path/size/mtime and versioned profile checksum match. Use `--refresh`
after externally editing an ISO, especially if timestamps were preserved.

Reviewed adapters: original USA BT3 (SLUS-21678), European BT3 (SLES-54945) and
BT4 B14 REV2 English and Spanish. The European disc has its own volume names
(PZS3EU*), a two-entry volume 0 (so volume-1 index = file ID - 2) and five text
languages; the scanner reads its English set (file 455). A disc no adapter
accepts is named in the refusal (`known_discs.py`). Asset-only mods
with the same reviewed code can be audited under that adapter. An unknown code
revision gets candidate resource findings but **no runtime-hook approval**.
Supporting a different executable requires reviewing addresses and adding an
adapter in `adapters.py`; a matching PCSX2 CRC is not enough.

The scanner maps populated character/form IDs, selection costume counts,
normal/damaged meshes, animation/combat bundles, BT4 AI/text/effect sidecars,
form destinations and size classes. It checks collision chains, mesh draw-node
limits, stage file mappings, both stage view modes, collision trees/vertices,
arena bounds, authored spawns, and destruction replacement resources.
Effect semantics, attacks, camera behavior, memory pressure for arbitrary teams
and gameplay remain separate tests. Passing the audit is not a crash guarantee.

BT4 startup now refreshes a stale profile before launch. Character mappings use
the scanned table; the reader uses the index inside the ISO instead of the old
extracted DBZ4.BIN. Extra creation and form reloads reject failed costume variants
with a specific diagnostic. File-ID mapping itself stays available for audits.
The stage results are exposed by `compatibility_profile.stage_support`; they do
not rewrite or remove native stage-selection entries.

Current BT4 findings: all 241 populated fighter/form entries pass for their base
costume. Of 1,558 normal/damaged costume variants, 12 fail collision requirements.
IDs161â€“164 are menu entries;231â€“235 have no costumes. The stage index reserves99
slots, including menu/empty entries. Some usable normal-stage packages have no
split-screen partner. Four stage IDs (11,23,46,58) have collision structures the
deeper audit cannot validate. Reports preserve the precise failure per variant;
those stage findings need investigation, not guessed pointer replacements.

## September 21 installer integration

`../player-installer/Install.cmd` prepares a new player-only installation from a
user-owned ISO, BIOS and PCSX2 2.8.0 folder. It uses `install_profile.prepare`
to extract references and all character labels/portraits. Matching executable,
menu-overlay and serial contracts are mandatory; changed code requires a new
reviewed adapter. Unknown revisions receive an inventory, never guessed hooks.
Reports now include every populated character/form and every stage slot.

The current BT4 feature port and remaining validation limits are recorded in
`../bt4-multifighter/PORT_STATUS_2026-09-21.md`. Structural validation is separate
from gameplay verification. A changed installed ISO requires a fresh profile.

The expanded-map builder now accepts either reviewed resource adapter and uses
its stage mappings. It leaves an entire map at native size if either view's
package cannot be converted, and also preserves native size when a destruction
destination cannot be expanded. Player installs generate their optional image
under `game/maps/`. The separate BT4 source project has its own build command;
no expanded BT4 ISO has been generated or played in this pass.

## Experimental larger maps (original BT3 build notes)

The generated `games\BT3 - Expanded Maps 2x (Experimental).iso` contains enlarged
stage data only. The original ISO and all non-stage bytes are preserved.
`Build expanded maps.cmd` builds it if missing; the current copy is already built.

In the main BT3 **Mod settings â†’ Presentation**, enable **Experimental 2x maps**,
then restart through **Play.cmd**. Disable it and restart to return
to the original ISO. This option does not affect the separate BT4 launcher or
the legacy preset launchers. Use a fresh match; an old battle savestate contains
the stage data that was present when that state was saved.

28 stages have both normal and split-screen packages expanded. Animated-scenery
IDs4,5,8,12,17,18,27 remain fully native in both modes. The change scales render
vertices, terrain collision vertices/planes/trees, visibility bounds, prop
translations, authored spawns and the **actual playable arena limits** together.
Destroyed replacement stages3 and15 are also expanded. Fighter size, movement
speed, attack reach, revival radius and camera zoom are unchanged.

This is an opt-in playtest build. Ambient effects, debris, intro cameras and
destruction cinematics are not fully converted/verified. The geometry core has
offline bounds and plane-consistency checks; gameplay was deliberately left to
the user. Check movement beyond old boundaries, floor/building collision, initial
spawns, split-screen, planet destruction, and a second match after returning to
selection. Report any mismatched terrain/effects or camera clipping.

`map-scale-2x-audit.json` in the BT3 analysis folder documents the coordinate
plans. `compatibility-profiles\expanded-maps-2x.json` records exact output/source
identity, changed file offsets and hashes, and the expanded/native stage lists.
