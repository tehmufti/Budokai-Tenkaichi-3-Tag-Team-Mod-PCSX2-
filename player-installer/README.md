# Tag Team Mod — public beta

**Español:** [guía de instalación y uso](LEEME.md). Setup offers English / Español.
The Spanish BT4 disc starts with Spanish mod menus and prompts, even if setup ran in English.
Change it later in **Mod Settings → Menus → Language / Idioma**. Saved in game,
it changes the mod menus when you leave Mod Settings and match text from the
next match; reopen the desktop editor to see its new language. Mod menus, settings,
loading screens and battle prompts are translated. The ISO's names, dialogue and
text are unchanged; technical logs and diagnostic tools remain in English.

One installer supports **BT3 USA**, **BT3 Europe**, **BT3 Japan** (*Sparking! Meteor*) and
**BT4 B14 REV2 (English / Español)**.
The European disc (SLES-54945, AU/EU) runs at 50 Hz, like the original European game;
the mod lists its English character names. The Japanese disc (SLPS-25815) keeps its
Japanese game text and voices, and its own menus confirm with Circle and go back with
Cross; the mod shows English character names, and the mod's own screens (Choose your
teams, the in-game Mod Settings) keep the buttons their footers show. BT4 support is
experimental: its resource scanner and runtime adapter are included, but every
fighter/move/stage combination has not been verified in gameplay.

## Install

The ZIP has one launcher, **Install.cmd**, a short **README.txt**, and a
**setup** folder. Keep that folder intact; its files run automatically.

1. Extract this **entire ZIP** to a normal folder. Do not run Install.cmd from
   inside the ZIP.
2. Have your uncompressed game ISO, your PS2 BIOS ROM, and an extracted
   PCSX2 for Windows x64 ready: any 2.x from **2.6.0** on (3.x is not accepted
   yet). Use a stable release: 2.6.0, 2.6.1, 2.6.2, 2.6.3, 2.8.0, 2.8.1 or
   2.8.2; the newest,
   [PCSX2 2.8.2](https://github.com/PCSX2/pcsx2/releases/tag/v2.8.2), is
   recommended. 2.8.0 and 2.8.2 were played with the mod; the others were
   checked against PCSX2's source code. Nightlies and other 2.x builds install
   with an "untested version" notice; if the mod does not recognise such a
   build's savestate format, it stops with a message when the first modded
   match is prepared. Versions before 2.6.0 are refused. Select
   **pcsx2-qt.exe**, not an installer executable.
3. Open **Install.cmd**. Setup offers the recommended folder
   **%USERPROFILE%\Games\Tag Team Mod** (choose No to pick another parent
   folder), then asks for the ISO and the PCSX2 executable. Setup uses the BIOS
   your PCSX2 is already set up with (PCSX2 **Settings → BIOS**): it reads that
   PCSX2's settings (beside pcsx2-qt.exe for a portable PCSX2, or in the folder
   its portable.txt names; otherwise Documents\PCSX2) and never changes them.
   When that PCSX2 has none, setup also reads the settings of another PCSX2 on
   this PC and says so. Identical copies of one BIOS dump count as one, and a
   configured file setup cannot use is named in yellow. When none is selected
   and PCSX2's BIOS folder holds several, setup takes the one PCSX2 itself
   starts with: the first PS2 BIOS by name, on an NTFS drive (where Windows
   lists files in that order). It asks for a BIOS only when that PCSX2 has
   none set up, or has several and setup cannot tell which one PCSX2 starts
   with; the file dialog then opens in PCSX2's BIOS folder. To use another
   BIOS, start setup from a command prompt with
   `Install.cmd -Bios "D:\BIOS\SCPH-70012.bin"`. The file dialogs also show
   compressed images (.chd, .cso, .7z, .zip...) so setup can tell you how to
   convert them. Install into a short, writable local folder, outside
   Program Files and cloud-synced folders; setup warns about OneDrive, network
   drives, Program Files and running as administrator, and refuses paths with
   square brackets `[ ]`. At least 3.5 GiB of free space is required, excluding
   your ISO and optional expanded-map copy.
4. Setup checks every selected file and the folder **before it changes
   anything** and lists all problems at once. Then it prepares Python, creates
   the folder and installs. Wait for **Ready**. Open **Play.cmd** in the new
   installation.

If Windows shows "Windows protected your PC" for Install.cmd, choose **More
info → Run anyway**: the files are the ones you extracted from the ZIP. Setup
removes the downloaded-file mark from its own files. If a PC administrator
blocks PowerShell scripts through Group Policy, setup says so (TTM-OS-02); only
that administrator can allow them.

Setup requires Windows x64 (Intel/AMD) and Python 3.11 x64 with Tk. It uses an
existing compatible Python or installs it through WinGet. If WinGet is missing,
install [Python 3.11 x64](https://www.python.org/downloads/release/python-3119/)
first, then retry in a new folder. Setup also checks the
[Microsoft Visual C++ x64 runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
and installs it if missing. Windows may request elevation for that prerequisite.
All eight player Python dependencies are bundled, version-pinned and
hash-checked; they install without contacting a package server. Internet is
needed only for missing system prerequisites or obtaining PCSX2.

After validation, Windows setup briefly starts a hidden, isolated emulator to
build reusable online selection caches from your own disc and BIOS. This adds
about two minutes on the tested PC and about 20 MB of cache files. No match
roster is prebuilt. If this optional step fails, Play remains available and
online falls back to its checked native preparation. The game ISO and original
BIOS remain unchanged. PCSX2 and the BIOS are copied into an isolated profile; existing
emulator settings, memory cards and save states are not imported or overwritten.
The private profile needs its own copy of the BIOS because the mod runs its own
PCSX2 settings, so it never changes the PCSX2 you already use.
The ISO is referenced in place: keep it at the selected path.

## Linux

Linux support is new in this beta: the installer, dependencies and checks run on
Linux, but gameplay on Linux still needs live testing. It needs a 64-bit
Intel/AMD (x86-64) system and the official **PCSX2 AppImage** for Linux, any
2.x from 2.6.0 on (the same versions as on Windows;
`pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage` from the
[PCSX2 2.8.2](https://github.com/PCSX2/pcsx2/releases/tag/v2.8.2) page is
recommended). Download the separate **linux-x86_64.tar.gz** release archive.

- **Flatpak PCSX2 is not supported.** Its sandbox gives PCSX2 a private
  runtime folder, so the mod cannot reach PCSX2's PINE connection (a socket in
  that folder), and its settings live inside the sandbox instead of the mod's
  private profile. Setup refuses Flatpak files with this explanation.
  PCSX2 packages from your distribution are not supported yet either.
- **Python 3.11, 3.12, 3.13 or 3.14 (64-bit) with venv and Tk.** Debian,
  Ubuntu, Mint: `sudo apt install python3-venv python3-tk`; Fedora:
  `sudo dnf install python3-tkinter`; Arch: `sudo pacman -S tk`; openSUSE:
  `sudo zypper install python3-tk`. Ubuntu 22.04 and older ship Python 3.10:
  install python3.11 (with python3.11-venv and python3.11-tk) first. Setup was
  checked on Ubuntu 24.04 (Python 3.12, WSL2); the bundled wheels cover
  CPython 3.11 to 3.14. Python 3.15 needs a later release with refreshed wheels.
- **Steam Deck, Fedora Atomic, Bazzite and other read-only systems:** install
  [uv](https://docs.astral.sh/uv/) in your home folder, run
  `uv python install 3.12`, then start setup with
  `TAGTEAM_PYTHON="$(uv python find 3.12)" sh Install.sh`. That Python
  (python-build-standalone) includes venv and Tk.
- **FUSE 3 and libOpenGL:** the AppImage needs a setuid `fusermount3`
  (package fuse3, installed on most desktops; libfuse2 is not needed) and
  `libOpenGL.so.0` (libopengl0 on Debian/Ubuntu, libglvnd-opengl on Fedora,
  libglvnd on Arch). Setup stops and names what is missing.
- **Three or four players** also need `libSDL2-2.0.so.0` (libsdl2-2.0-0 on
  Debian/Ubuntu, SDL2 or sdl2-compat elsewhere). Controllers 3 and 4 are read
  directly and PCSX2's memory is shared through /proc, so run PCSX2 as the same
  user (the launcher does). Players check in on Player Setup by pressing START,
  so the order Linux detects controllers in matters only for PCSX2's own players
  1 and 2: check those bindings with **PCSX2 settings.sh**. When 3-4 player
  input is unavailable, those modes say so instead of starting (TTM-CTRL-20).

Install: extract the whole archive into your home folder, open a terminal in
**Tag Team Mod Installer** and run `sh Install.sh`. Choose the language, a
parent folder, the ISO and the AppImage in the dialogs. As on Windows, setup
uses the BIOS your PCSX2 is already set up with (the settings the AppImage
starts with: `$XDG_CONFIG_HOME/PCSX2` or `~/.config/PCSX2`, or those in the
`.config` or `.home` folder named after the AppImage file; then those in
`PCSX2/` beside the AppImage, used with `-portable`, and those of a Flatpak
PCSX2) and asks for one only when it finds none it can use (with several BIOS
files and none selected, it always asks on Linux). Started from a
file manager, setup shows why it asks, and the final window names the BIOS it
copied. Without a desktop, pass them instead: `sh Install.sh --destination
~/Games/"Tag Team Mod" --iso ... --pcsx2 ... --language en`, adding
`--bios ...` when your PCSX2 has no BIOS set up (`sh Install.sh --help`). The
installation folder must be on a Linux file system (not FAT, exFAT or a
Windows drive) that allows running programs. Setup copies the AppImage into
the new installation, so the downloaded file can be deleted afterwards.

Play: run **Play.sh** in the new installation (`sh Play.sh` in a terminal, or
the **Tag Team Mod.desktop** entry, which opens a terminal for the launcher).
Closing the terminal after the game has started leaves PCSX2 running.
**Mod settings.sh** opens the desktop settings editor, **PCSX2
settings.sh** opens this installation's own PCSX2 without a game (controller
bindings), and **Check installation.sh** runs the installation check. The
.desktop files start the same scripts; copy them to
`~/.local/share/applications` for menu entries. On Linux the memory cards and
save states are under **game/runtime28/PCSX2/memcards** and
**game/runtime28/PCSX2/sstates**.

Differences from Windows: text is drawn with the bundled Liberation Sans
(Arial's widths, slightly different letters), and the Ki Storm loading art uses
it instead of the Windows-only Bahnschrift and Segoe UI Black. There is no
desktop cover or automatic mute while a match loads (the in-game loading screen
still shows), and when the game has to be paused, the launcher asks you to press
PCSX2's pause key instead of pressing it for you. If the private Python
environment stops working after a system upgrade, Play.sh says so: run
Install.sh and choose the folder of the installation itself; setup installs a
fresh copy beside it and offers to copy your memory cards and mod settings.

## Play and controls

At the ordinary main menu, press **Select** to open **Modded Modes**. Native-menu
selections play normally. Choose Team Battle, Free-for-All or Modded Training,
then the number of players. Team modes ask Player 1 to assign each controller's
team before selecting fighters; put everyone on one team for cooperative play.
Player badges identify each human's fighter slots. Player 1 chooses CPU additions.

**Controller check-in.** With two to four players, the player/team setup screen
(Player Setup) lists every player with the controller they use, and a light on
their row flashes with each of their presses. With three or four players, each
player presses **START** once on their own controller to join; **Continue**
unlocks when every seat is filled. A controller PCSX2 already uses as its player
1 or 2 keeps that number (PCSX2 keeps its mapping and rumble); any other
controller becomes player 3, then 4, then fills players 1 and 2 if they are
still free. **SELECT** leaves a seat, Left/Right on your own controller changes
your team, and **Clear check-ins** starts over. With two players, PCSX2's order
stays the default, but anyone may still press START to check in. A keyboard, or
a pad only PCSX2 can read, joins as player 1 or 2 through PCSX2 (press its
START). Check-ins are kept for the next matches until Play closes; Co-op, which
has no Player Setup, uses them too, or the connection order.
**Mod Settings → Players and controllers → Controller check-in** chooses when
check-in is required: with 3 or 4 players (new installations), with 2 to 4
players, or **Optional (connection order)**, which keeps the earlier order
(players 3 and 4 are the third and fourth controller connected).

If a player's controller disconnects, only that player's fighter stands still
(TTM-CTRL-22 in the Play window): reconnect it, or hold START for 2 seconds on a
free controller to take over the seat. The mod reads controllers with PCSX2's
controller database (and your own game_controller_db.txt in PCSX2's data
folder, if you have one).

Players 3 and 4 never come from PCSX2: the game loads no multitap support, so
PCSX2's Pad 3 and Pad 4 bindings and its multitap setting do nothing. Players 1
and 2 use PCSX2 **Settings → Controllers** in this isolated profile. For
keyboard play, bind the first controller there, including Select.

Default target/spectator switching is a tap of **L3**; the button and hold
duration can be changed in **Mod Settings → Controls**. A tap picks the next
enemy to the right, around you (Controls can switch this to nearest first or
selection order). New installations pick with the right stick alone: while
you are locked on in combat, flick it (no button needed) and left/right steps
around you, up/down picks the enemy above or below your target; the right stick
then no longer moves the camera. Unlocked, it moves the camera as before, and
R3 always transforms. To pick only while holding L3 (and keep the stick's
camera controls), set **Controls → Picking with the right stick** to
**Hold switch button**. When your target is defeated,
the enemy nearest your screen centre becomes your target. A gold arrow above
its head marks your target in your own view and drops in when you switch
targets. **HUD → Target indicator** can show a yellow double ring with side
arrows (as in the PSP game Tenkaichi Tag Team) around its body instead, or
both; the ring is sized to your target on screen (smaller far away and in
split screen). It shows in every layout, each view marking its own player's
target. Switch it off with **HUD → Mark your target**, separately from the
health bars. During an attack
warning (or up to half a second after it) the switch tap locks on to the enemy
attacking you instead (**Controls → Switch to your attacker**: Never, Tap during
a warning, or Tap, or automatic when hit). Red arrows point in at the enemies
locked on to you, or sit on the edge of your view when they are off screen;
they grow and blink yellow and red while that enemy attacks you (so do your
target ring's arrows when your target attacks you)
(**HUD → Enemies targeting you**), in every layout. New installations
also bind lock-off to **L3 held for 0.5 seconds**: hold L3 alone. With the
stick alone it happens after the hold time, while you hold; with **Hold switch
button** the unlock happens when you let go, so a late flick still aims. Tap L3 to acquire the
visible enemy closest to your camera centre.
With no enemy on screen, you stay unlocked. Lock-off can be disabled or rebound
separately in Controls. New installations
enable revival (3 stocks, 3 seconds nearby), shared ultimate/transformation
cameras and an 80-second Fusion Dance time limit. Potara fusions have no timer.
After defeat, watch a living CPU teammate and use the displayed takeover button.
Enemy takeovers, CPU-only takeover and FFA takeover are disabled.

Close PCSX2 normally to stop its helpers and close the launcher console.
Startup errors remain visible. Start with Play.cmd each time; loading an old
save state from a different mod build is not a supported upgrade path.

## Settings

**Modded Modes → Mod Settings** (controller) and **Mod settings.cmd** (desktop
editor) offer every setting in the same 17 categories: Menus, Players and controllers,
Controls, Movement, Cinematics, Fusion, Fighters, Giants, HUD, Split-screen HUD,
Spectating, Revival, Outnumbered, Beam struggles, Training, Launch
options (restart), Diagnostics. Both also
offer the per-character CPU transformation exceptions and Restore defaults
(your language is kept). Each category has a help note. **Fusion** has two
swap-mode switches: the "Fused - Player n has control" message and the
"Pn takes control in" countdown. **Beam struggles** sets the clash camera, the
struggle length, an early win by an input lead, the CPU's strength, hits on
struggling fighters and beam assists. **Beam clash camera**: Switch to clash
(the game's own struggle camera, the default) or Keep player views (every view,
split or single, keeps following its own player during a clash). Beam assist:
stand near a struggling teammate (**Assist range from the struggling ally**, 60
by default) and press **R3** alone (the hint "R3 - BEAM ASSIST" shows while
you are in range). You fly in to a spot just behind and beside your teammate,
then join the struggle in the firing pose until it ends; only once your pose
has taken does your view switch to your teammate's view of the clash. Only once
the teammate is posed does the assist spend 1 blast stock and add its share of
push and final damage ("BEAM ASSIST X1.5"); if they cannot join (busy, hit or
no room), nothing is spent and "ASSIST FAILED - BUSY / BLOCKED / HIT" says
why. Up to four teammates per side can assist, each paying its own stock and
adding its own share (one side's bonus stops at x3, "BEAM ASSIST X3"); CPU
teammates can assist too. That R3 press never
transforms you; R3 works as usual when you cannot assist. New installations start with hits on struggling fighters and
beam assists (CPU allies too) switched on; with every option off nothing
changes.

**Movement → Walk and run on the ground** makes fighters walk or run on solid
ground instead of gliding just above it; dashes, jumps, flight and water stay as
they are. Tilt the left stick past the set amount (60% by default) to run, less
to walk; computer fighters always run. Ground speed follows each fighter's leg
length (**Size changes ground speed**, on): small fighters run slower with
bounding strides, large ones faster. Running builds up over a third of a second,
a sharp turn back skids, and the legs move at the speed the fighter really
travels, so the feet stay planted. Walking and running speeds are percentages of
a natural run (40% and 100% by default). It is off by default. **Cinematics → Keep attacks and transformations at their current
location** (off by default) plays rushes, ultimates and transformations where
they start instead of at the arena centre; a ranged ultimate still brings its
target to the attacker, and afterwards anyone left under the ground is put back
on it.

**Cinematics → Battle camera zoom-out** pulls the ordinary battle camera
further back than the game's own: 100% (the default) is the game's camera, up
to 200% in 5% steps. One value applies to every player's view, including split
screen and spectating, in Team Battle, Free-for-All and Modded Training (a
quick place to try values); native-menu battles keep the game's camera.
Close-ups (ultimates, transformations, intros, grabs, results) keep their own
framing, and walls and scenery can still pull the camera closer. With larger
giants, the giant camera distance multiplies it; no camera is pushed beyond a
fixed distance, so very large fighters gain less. A computer fighter you are
watching may fight slightly differently at a higher zoom.

**Outnumbered** helps a fighter on the smaller team or, by default, one that two
or more enemies target. **Off** (the default) changes nothing. **Balanced** and
**Strong** set four kinds of help and **Custom (rows below)** uses the rows
below: damage follows the living team sizes (per extra enemy each of you faces,
the smaller side deals more and takes less, at most 300% dealt and at least 40%
taken; equal teams and free-for-all keep normal damage); recovery and get-up
speed shortens knock-backs, get-ups and hit reactions; protection after getting
up makes ordinary hits neither stagger nor hurt you (Blast 2 attacks, rushes and
throws still do); and the combo breaker gives one second of that protection
after a set number of hits, at most every 5 seconds and never during a rush or
throw. Balanced is +15%/-10% per extra enemy, 150%, 0.5 s and 12 hits; Strong
+40%/-30%, 200%, 1 s and 8 hits. **Who counts as outnumbered** and **Help
applies to** (Every fighter or Players only) apply to every preset. The red
arrows of **HUD → Enemies targeting you** show who is attacking you.

In game, the category list uses Cross to open, Circle for help, Square to save
and exit and Triangle to close; it asks first if there are unsaved changes. On
a category page: Up/Down select (hold to repeat), Left/Right or Cross change,
L2/R2 move ten steps or to the first/last value, L1/R1 switch category, Circle
shows help, Square saves and Triangle goes back. In the exception list,
Left/Right cycle Default/Allow/Block, L1/R1 turn a page, L2/R2 five pages and
Select shows only the exceptions. The menu switch button acts as Back.

Most saved changes apply from the next match (each help note says when); a
Fight Again rematch keeps the settings of its match. **Launch options** apply
after restarting Play.cmd, and loading speed from the next loading screen. If
you turn the mod mode menus off, only Mod settings.cmd can turn them back on.

### Switching the game disc

The desktop editor (Mod settings.cmd; Mod settings.sh on Linux) has one more
page after the 17 categories: **Game disc**. It chooses which of your ISOs Play
starts, and each change applies at once (Save and Cancel are for the other
pages):

- **Add ISO…** checks an ISO and adds it to the list. An ISO of another game or
  an unsupported disc is refused within a second, before anything is written.
  Adding reads the whole ISO once (up to a minute for a 3-6 GB file; instant if
  setup or Scan compatibility already checked that file) and extracts its
  fighter names, portraits and game program into `game/discs` (about 10 MB).
- **Use this disc** makes the selected disc the one Play starts, from the next
  Play. It takes under a second and is refused while Play or this
  installation's PCSX2 is open.
- **Find ISO…** points a disc at its moved ISO (only the same file is
  accepted). **Remove from list** deletes a disc's extracted files, never the
  ISO; the disc you installed with always stays. **Delete expanded maps**
  deletes that disc's expanded-map ISO (about 3 GB).
- One installation switches between the discs of **one game**: BT3 USA, BT3
  Europe and BT3 Japan, or BT4 B14 REV2 English and Spanish. Switching between BT3 and BT4
  is not possible in one installation: install the mod for the other game into
  a new folder with Install.cmd (setup offers to copy your memory cards).
- Game progress is saved per disc: characters unlocked with one BT3 disc are
  not unlocked with another. The European disc runs at 50 Hz. Both
  BT4 discs use the same PCSX2 save-state names, so load a save state only with
  the disc it was made with. PCSX2's own Change Disc during a session is not
  supported.
- Expanded maps are built per disc: after switching, run Build expanded
  maps.cmd again if you use them.
- A new release installs into a new folder: setup copies your memory cards and
  mod settings, but not the discs you added here (it says how many). Add their
  ISOs again on the Game disc page of the new installation.
- If the chosen disc's files are damaged, Play stops with TTM-PLAY-46 and Check
  installation reports TTM-CHECK-19: open Mod settings.cmd > Game disc and
  choose a disc again (the disc you installed with always works), or choose Add
  ISO… with the same ISO to extract its files again.

## Online play

The installation includes online play (TTM Online): **Play online.cmd** (Linux:
**Play online.sh**, or the "Tag Team Mod - Online" menu entry) opens the online
room window next to Play.cmd. Nothing has to be chosen: it uses this
installation's selected BT3 USA/Europe/Japan or reviewed BT4 English/Spanish
disc, its BIOS and its PCSX2 build. Everyone in a room needs identical disc contents. Every PC installs this same release.

- One PC hosts a room, the others join it with the host's address. Everybody
  joins watching; any of the up to ten fighters (5 v 5) can be claimed by a
  player, every other fighter is a CPU. Each team independently holds 1-5 fighters. The host builds the match on the spot
  and its rules (gameplay and camera rules included) apply to everybody.
- Return to lobby opens character selection. Back to hangout is a separate
  host action. A room has one active match; independent challenge instances are
  not supported yet. Optional password-protected listings work on LAN or via a
  shared directory URL; no public directory service is included.
- Online settings (your room name, the host's rules, your display choices) live
  in `online\data` and never change the offline `game\mod-settings.json`.
  The online PCSX2 is its own copy (`online\pcsx2`; Linux: the installation's
  AppImage with its own configuration in `online/linux`), so online play never
  changes your offline PCSX2 profile, memory cards or savestates.
- Over the internet, forward port 47400 (TCP and UDP) on the host, or use a VPN
  such as Tailscale, ZeroTier or Radmin VPN. `online\README - Play online.txt`
  explains rooms, rules, the hub and every message code.
- Updating: a new installation imports the online settings with your memory
  cards. Uninstalling: deleting the installation folder removes the online part
  too.

## Features and compatibility

The installed **COMPATIBILITY.md** lists the selected disc's populated
characters/forms, costumes, stages, destruction destinations and fusion recipes.
Supported executable adapters:

| Disc | Status |
| --- | --- |
| BT3 USA, SLUS-21678 | Public beta runtime adapter |
| BT3 Europe, SLES-54945 | Public beta runtime adapter; runs at 50 Hz like the original European game |
| BT3 Japan (*Sparking! Meteor*), SLPS-25815 | Public beta runtime adapter; its menus confirm with Circle; English character names |
| BT4 B14 REV2 English / Español, SLUS-21978 | Experimental public beta runtime adapter |
| Asset mods with the same reviewed executable and menu overlay | Scanned; install only if runtime checks pass |
| Other releases (such as the Japanese *Sparking! Meteor* demo, SLPM-61162), other BT4 builds, or changed executable/menu code | Setup names the disc and the supported discs, then stops; COMPATIBILITY.md keeps the inventory |

A resource-check pass is not proof that every move, effect or stage works.
BT4 has some invalid costume/resource entries, which are reported and guarded.
The latest BT4 fusion-camera changes still need a natural-match playtest.
Three/four-player views and unusual fusion/defusion combinations remain beta.
Expanded maps and larger giants are experimental and off by default; map
rendering, collision or move reach can still have limitations.

**Build expanded maps.cmd** creates a separate optional ISO. Allow additional
space equal to your ISO plus build working space. Unsupported layouts remain
native size. Enable expanded maps in Mod Settings only after the build succeeds.

## Disk usage and saves

Diagnostic RAM dumps, freeze dumps, texture dumps and battle-history recording
are off by default. Match preparation still needs temporary working files and a
rematch checkpoint. Old generated sessions are pruned on launch, retaining recent
sessions and archives referenced by trainer-owned save slots. Your manual saves
and cards are excluded from that cleanup. Enabling diagnostic recording can use
substantial space.

Your cards and states are under **game/runtime28/memcards** and
**game/runtime28/sstates**. Mod preferences are **game/mod-settings.json**.
Use a memory card, rather than a modded save state, to keep game progress across
mod versions.

## Troubleshooting

The launcher names below use Windows `.cmd` names; on Linux use the corresponding
`.sh` files. Linux memory cards and states are in **game/runtime28/PCSX2/memcards**
and **game/runtime28/PCSX2/sstates**.

On Linux, missing required graphics/FUSE packages mean **not ready**, even when
the installed files pass validation. If you deliberately install offline with
`--allow-missing-libraries`, install those packages and rerun **Check installation.sh**
before playing. Missing SDL2 only prevents the mod's three/four-player input and
controller check-in; it does not block one/two-player readiness.

- **Setup failed:** setup prints one block per problem. It starts with a code
  such as **[TTM-BIOS-02]** and says what happened, why, how to fix it, whether
  anything was changed, which file is involved and where the log is. Copy that
  block when asking for help. The setup log is
  **%LOCALAPPDATA%\TagTeamMod\logs\setup-<date>.log** (Linux:
  **~/.local/state/tagteammod/logs**); once the installation folder exists it is
  also copied to **installer.log** there, and **install-status.json** records
  the code (`error_code`). Fix the problem and run Install.cmd again with the
  **same** folder: an unfinished attempt is renamed to
  **Tag Team Mod (failed <date>)** and setup continues. Setup never deletes a
  folder; delete the renamed one yourself once the new installation works.
- **Common codes:** TTM-ZIP-01, Install.cmd was opened inside the ZIP (extract
  the whole ZIP first). TTM-ISO-01/02/03/04, the image is an archive, CHD, CSO/ZSO
  or BIN/CUE (extract it, `chdman extractdvd -i game.chd -o game.iso`,
  `maxcso --decompress game.cso -o game.iso`, or convert BIN/CUE to ISO).
  TTM-ISO-06, the ISO is incomplete (download or copy it again). TTM-ISO-07,
  the ISO is damaged (dump or copy it again and check it against redump.org).
  TTM-BIOS-02, a PlayStation 1 BIOS was selected or set up in PCSX2 (select
  the 4 MiB PS2 BIOS). TTM-BIOS-07/08, a setup started with its folder, ISO
  and PCSX2 on the command line found no BIOS in PCSX2's settings, or several
  and none selected (select one in PCSX2 **Settings → BIOS**, or add -Bios /
  --bios).
  TTM-BIOS-06, a companion file of a BIOS dump (.ROM1, .ROM2, .EROM, .NVM or
  .MEC) was selected (select the 4 MiB .bin or .rom0 of the same dump). TTM-PCSX2-02/03,
  PCSX2 is too old or is 3.x. TTM-PCSX2-05, only pcsx2-qt.exe was extracted
  (extract the whole PCSX2 download). TTM-PY-03, Python 3.11 lacks "tcl/tk and
  IDLE" (Settings → Apps → Python 3.11 → Modify). TTM-DEST-04, the folder has
  square brackets. TTM-CHECK-02, installation files are missing: antivirus
  quarantine is the usual cause. TTM-PLAY-50, a launcher was copied out of its
  folder: make a shortcut instead.
- **Checksum error:** extract a fresh complete release ZIP. Do not mix files
  from separate releases. The ZIP's adjacent .sha256 file records its hash.
- **Unsupported ISO:** setup names the disc it found (for example the Japanese
  *Sparking! Meteor* demo, another BT4 build, or a modified USA, European or Japanese executable)
  and lists the supported discs. Read COMPATIBILITY.md. Renaming an ISO or its
  serial will not make different executable code compatible.
- **Game or menu fails:** close the emulator, run **Check installation.cmd**,
  and read **check-installation.log** / **check-status.json**. It checks installed
  code/resources, exact dependencies, ISO identity and important settings without
  launching the emulator. It does not reset your preferences or repair files
  silently. A full-disc recheck is available by running it with --full-iso.
- **No mod menu:** launch via Play.cmd, reach the ordinary main menu, and press
  Select. Check the launcher's error message and your controller's Select binding.
  If the mod mode menus were turned off, turn them on in Mod settings.cmd.
- **PCSX2 version:** keep the PCSX2 this installation was made with; its copy
  is checked with the other files. To change version, install a fresh copy
  with the new PCSX2. Save states from PCSX2 2.6 and 2.8 cannot be loaded by
  each other. Play.cmd sets PCSX2's save-state compression to Zstandard for
  each session (the mod cannot read Deflate64 or LZMA2) and restores your
  choice when PCSX2 closes.
- **Update/repair:** run the new Install.cmd, answer No to the recommended
  folder unless your installation is there, and choose the folder of your
  installation itself (the one that contains Play.cmd). An existing installation
  is never changed: the new one is created beside it as **<folder name>
  <version>** (for example **Tag Team Mod <version>**), and setup offers to copy
  your memory cards (**game/runtime28/memcards/*.ps2**) and
  **game/mod-settings.json** into it. The mod settings are copied only between
  installations of the same game (BT3 to BT3, BT4 to BT4); from the other game
  only the memory cards are offered. If the copy fails (TTM-DEST-27), the new
  installation still works: copy the .ps2 files by hand. PCSX2 settings
  (controller bindings, graphics) and PCSX2 savestates are not copied: they stay
  in the old folder, so set your controller bindings again in the new
  installation's PCSX2 if you changed them. Do not copy old trainer snapshots,
  cheats or generated caches. Keep the old folder until the new one is verified.
- **"The private Python of this installation no longer starts" (TTM-PLAY-51):**
  its Python 3.11 was uninstalled or moved. Run Install.cmd of the same release,
  answer No to the recommended folder unless the installation is there, choose
  the installation folder itself (the one that contains Play.cmd), and answer
  Yes when setup offers to repair its private Python (only its .venv folder is
  rebuilt). An installation from another release is repaired by that release's
  Install.cmd.
- **The ISO was moved or renamed:** Play offers to find it; it accepts only the
  same disc (the same SHA-256), so a different or changed ISO is refused. You
  can also move it back to the path Check installation shows.
- **Play stops with an error:** the Play window stays open after an error (exit
  status 2 or 3) so you can read and copy the message. Failure reports are
  saved in **game\analysis\failures**. The private PCSX2 of an installation is
  **game\runtime28\pcsx2-qt.exe** (on Linux, PCSX2 settings.sh opens it).
- **Controllers (TTM-CTRL codes in the Play window):**
  - **TTM-CTRL-20:** players 3 and 4 cannot join because the mod's controller
    reader (SDL2) did not start. Players 1 and 2 keep their PCSX2 controllers. On
    Linux install libsdl2-2.0-0 (Debian/Ubuntu), SDL2 or sdl2-compat.
  - **TTM-CTRL-21:** a controller is connected but has no gamepad layout, so it
    cannot be player 3 or 4. It can still be player 1 or 2 through PCSX2
    (Settings → Controllers), or switch it to its XInput/X mode.
  - **TTM-CTRL-22:** a player's controller disconnected; that fighter stands
    still. Reconnect it, or hold START for 2 seconds on a free controller.
  - **TTM-CTRL-23:** one controller appears twice (DS4Windows, Steam Input or
    another remapper); the mod uses one copy. If a player moves twice, hide the
    copy (HidHide) or turn the remapper off.
  - **TTM-CTRL-24:** one controller moves two players: it checked in as one
    player and PCSX2 also uses it for another port. Remove it from that port in
    PCSX2 Settings → Controllers, or let it check in as that player.
  - **TTM-CTRL-25:** controller input for players stopped; the line says why.
    The match goes on and players 1 and 2 use their PCSX2 controllers.
- **No sound in menus or fights (Windows):** releases before 0.1.0-beta.34
  could leave PCSX2 muted in the Windows volume mixer when PCSX2 was closed
  during a mod loading or error screen, and Windows keeps that mute for the
  next start. Play of this release unmutes its own PCSX2 by itself. For an
  older installation, start its Play.cmd and, while the game runs, open the
  volume mixer (right-click the speaker icon on the taskbar > Volume mixer, or
  Settings > System > Sound > Volume mixer), find PCSX2 and unmute it.
- **The loading screen stays at 0 %:** Fixed: rarely, the loading screen
  stayed at 0 % on 'Loading your selected fighters...' (any fighters or
  stage). On beta.36 or older, press Start to continue.
- **A big match freezes for good, or two pairs stand still for about 20
  seconds (TTM-MATCH-21):** Fixed: a match with more than two fighters per side
  could freeze while many fighters drew after-image trails (for example a 5v5
  on Muscle Tower with ultimates), and a rush or an ultimate that started while
  another pair's rush ran could hold both pairs (beta.36 and older).
- **TTM-MATCH-08 "Additional cached primary-row reference prevents safe
  relocation":** Fixed: some music (for example 'Hero - Kibou no Uta -' on the
  Spanish BT4 disc), the data of a few fighters and BT4 stage 70 could stop a
  match while it got ready. If this code still appears, the message names the
  value and the address it found: include it when you report the problem.
- **Uninstall:** close the emulator, back up any wanted memory cards/states and
  preferences, then remove only this installation folder. The original ISO,
  original BIOS and original emulator are outside it and remain untouched.
  Python and Microsoft runtime prerequisites are shared and are not removed.
- **Linux: Play.sh asks you to close the emulator, but PCSX2 is closed:** a
  program opened from inside PCSX2 (for example a file manager or a browser
  started from its menus) inherits the AppImage's `APPIMAGE` setting, so Play.sh
  counts it as PCSX2 and names it after "Found:". Close that program, then start
  Play.sh again.
- **Linux: Mod settings.sh or PCSX2 settings.sh shows an error:** started from
  the desktop, they report errors in a dialog. Details are in
  **game/analysis/settings/launcher.log** (Mod settings) and
  **pcsx2-settings.log** (PCSX2 settings). When PCSX2 cannot start, the message
  names the missing system library or FUSE part.

When reporting a problem, include the mod version, game version, mode/player
count, selected fighters/forms/stage, what happened and the relevant error.
The checker and installer **do not upload anything**. Logs may contain local
paths; review them before sharing. No memory cards, BIOS, ISO or full dumps are
needed for an ordinary installer report.

The package contains player runtime tools only: no Workbench, research captures
or developer test suite. See CHANGELOG.md and THIRD_PARTY_NOTICES.md.
