## Version 11.2

Version 11.2 adds Potaras to online matches and fixes the flickering online menus.

- Equip Potaras from your game's item list using the button next to each fighter. The host can equip CPUs too, and your loadouts carry into rematches.
- Smaller online windows wrap and scroll instead of cutting off text or buttons.
- Ping and loading updates no longer make the menus flicker or interrupt what you're typing or selecting.

Use the full Windows ZIP or Linux archive for a new installation, or the matching **Updater** for an existing one. Your settings and saves stay in place. Everyone in an online room needs Version 11.2.

## Version 11.1

- Fixed vanish/counter exchanges choosing an old opponent after switching targets. Responses now stay with the fighter that actually triggered them.
- Fixed melee clashes continuing against defeated or removed fighters, and contact with another fighter causing a clash with the wrong opponent.
- Includes the fixes for BT3 and BT4, online play, Windows/Linux installers and updaters.

## Version 11

- Movement settings add Natural and Fighter walking/running styles alongside Classic. Walking/running remains off by default.
- Fusion settings can disable new fusions for humans and CPUs without removing preselected fused characters.
- Tournament stages use native ground-contact ring-outs. Eliminated fighters cannot revive; teammates continue until the whole team is defeated. Eligible players can take over a surviving CPU teammate. Battle rules can disable ring-outs.
- Online hosts control the new gameplay settings for the whole room. Windows and Linux installers and updaters include the same changes.

## Version 10

- New installations default Beam clash camera to Keep players' views. Existing saved settings are preserved.
- Online clients display the health, ki, stocks and portrait of their own fighter and current target.
- Separate Windows and Linux updaters upgrade an existing installation with a recoverable backup, preserving settings, saves and custom scenarios.
- Workbench Custom Scenarios adapts to smaller windows and allows editing animation donors.
- New installs include the revised three example scenarios; updates preserve existing authored scenario files.

## Version 9 - scenario and CPU-only introduction updates

- CPU-only online matches relay the host dialogue and resource completion gates; entrances no longer wait for the silent timeout.
- Modded Scenarios includes only Namek: Piccolo Arrives, Saiyan Invasion: Goku Arrives, and Cell Games: Gohan Awakens.
- Key scenes reset living fighters to safe stage positions; fallen allies cannot stall reinforcement events.
- Offline scenario launch requests do not enter the private online match-making copy.

## 0.1.0-beta.9 (Version 9)

- Windows setup creates two small, authenticated neutral selection caches locally from the player's own disc and BIOS. Fresh fighters, costumes and stages still load from the disc; no complete roster or arena match is prebuilt or distributed.
- Fresh online starts skip the repeated game boot and menu navigation. Cache ownership, source identity, archive integrity and the live native menu acknowledgement are checked before use; damaged or outdated caches fall back to normal preparation.
- The hidden builder keeps boot and native menu navigation at normal speed, accelerates cached restoration and match resource loading, avoids unused controller/audio services and rendering work, and combines the held native export with online conversion. Shorter acknowledgement and checkpoint polling recognizes completed native work sooner without changing readiness guards or timeouts. All final game-code, resource, archive and lobby checks remain enabled. Client gameplay speed is unchanged.
- The private Windows builder uses FIFO presentation with frame skipping, preventing its hidden window from capping accelerated preparation at desktop refresh speed. The player's graphics settings and normal match speed are unchanged.
- Accelerated private match confirmation holds one input until the native game acknowledges it, fixing missed confirmation after a builder resumes. Cancellation, timeouts, lost windows and replaced processes release or close only the owned input source; the complete roster, stage, time and music readback remains required.
- Independent installation files are fully hashed with at most four readers. Canonical identities, source-change checks and cache invalidation remain intact.
- Generated boot patches are reused only after authenticating their exact source identity and content. A foreign occupied patch file is never overwritten.
- BT3 USA checkpoints use compact transfers containing verified references to the matching local ISO plus compressed remaining data. Clients reconstruct and verify the exact native archive. Other supported discs retain the full checked archive transfer.
- Fresh converter proofs avoid repeated sender compression. Per-client initialization happens only in the owned paused frame-zero emulator, before the all-loaded barrier. Rematches repeat these ownership and state checks.
- A fully verified compact decode can reuse its immutable memory snapshot for lobby verification and paused per-client initialization. Each reuse checks the complete current archive identity; original archive SHA, every entry hash and CRC, native state, machine-word readback and ownership guards remain enabled. Canceled or replaced matches cannot publish a usable snapshot into a new owner.
- Resetting the hidden builder is deferred until after checkpoint delivery, reducing contention during loading. Cancel, room changes and shutdown discard stale work and close only the captured private processes.
- An unfinished private worker continues at normal speed until it reports ACTIVE. Only then may its owned process tree be parked, preventing a deliberate suspension from being mistaken for a frozen introduction. The genuine freeze watchdog is unchanged.
- Retains Version 8 gameplay hooks, regional adapters, settings defaults, installers and dependencies. Pending scenario development remains excluded from the player payload. See the source release's startup validation notes for measured timings and network limitations.

## 0.1.0-beta.8 (Version 8)

- Faster online starts: a private accelerated builder returns its fully verified match before its hidden intro/reset completes. It switches battle engines without rebooting and performs the online archive conversion in one guarded pass.
- Settled lobby selections are prepared and downloaded in the background. Start reuses only the exact selected fighters, costumes, stage, rules and human slots; last-second changes use normal preparation. No Ready votes are delayed or changed by the cache.
- Windows clients initialize their paused emulator in the lobby. Canceling, leaving or closing during initialization cannot load an old match or stop a new room's emulator.
- Lobby downloads use tagged, hash-checked streams separate from live match/resync traffic, respect bandwidth limits, and fall back safely if incomplete or stale. Full participant loading checks and native introductions remain intact.
- Concurrent foreground/background requests for the same checkpoint share one verified cache writer, preventing partial-file collisions when Start is pressed during preparation.
- Retains Version 7 gameplay hooks, regional adapters, defaults and dependency/bootstrap checks. Pending scenario development remains excluded from the player payload.

## 0.1.0-beta.7 (Version 7)

- Online accepts the new Version 7 numbering while retaining the existing game-code compatibility checks.
- Added a saved, host-only online setting: cancel the start if a player fails to load (default), or remove failed/timed-out players and continue after the remaining players load. The loading deadline is 120 seconds; the host is never dropped or replaced.
- Missing players' fighters now receive a synchronized CPU handoff at startup and on rematches, rather than remaining idle. Dropped players can rejoin as spectators.
- Retains beta.45's hidden server browser and Join address dialog. Pending scenario development remains excluded.

## 0.1.0-beta.45

- Hidden online server-browser, room-listing and directory controls for now. Opening a room from the player window does not advertise it.
- Join a room now opens an address dialog with recent hosts and an optional password. Cancel closes the dialog; missing addresses and invalid ports are reported before connecting.
- Room passwords remain available under Advanced. An unused directory setting no longer prevents opening an unlisted room.
- Includes the regional, unequal-team and lobby-flow changes from beta.44. Pending scenario development remains excluded.

## 0.1.0-beta.44

- Online now accepts independently sized teams of one to five fighters, with up to ten fighters total. Fixed native KO rendering stalls in padded unequal matches; their results use the online results screen.
- Online uses the installation's reviewed BT3 USA, Europe or Japan adapter, or BT4 B14 REV2 English/Spanish adapter. Room members still need the same exact ISO and release; this does not enable cross-region play.
- Fixed regional private preparation: PAL language/title boot flow, Japanese confirm/back inputs and executable revision, BT4 private PINE port, localized preparation checks, and requested CPU difficulty on extras.
- Return to lobby opens character selection. Leaving that room's selection through Back to hangout restores the saved playable hub. Challenge wins follow the actual players even if teams changed in selection.
- Added optional room passwords, LAN server discovery, and support for a shared HTTPS room directory. Listing is opt-in; passwords are not saved or advertised. A directory service is included for hosts who want to run one, but no public directory is operated by this release.
- Verified unequal matches, rematches and selection return with two Windows clients on the same PC under simulated latency/jitter/packet loss. Separate PCs over the internet and Linux remain unverified. A room runs one match at a time; other members spectate.
- Body Change and timed fusion remain unavailable online. Pending scenario-builder changes are excluded from this release.

## 0.1.0-beta.43

Includes everything in beta.42.

- Online play (TTM Online 2.1) is now part of the installation: Play online.cmd / Play online.sh (Linux: "Tag Team Mod - Online" menu entry). The disc, BIOS and PCSX2 come from the installation; online settings are kept in online\data, separate from mod-settings.json. Every PC installs the same release.
- Up to ten human players per online match (5 v 5): any fighter can be claimed, unclaimed fighters are CPU, spectators watch; a player who leaves becomes a CPU. Each PC shows its own fighter.
- Online rooms: matches built on the spot, host rules and camera rules for everyone, full intros, Retry (everyone must agree within 10 s) or Return to lobby, optional Hub (free roam, hit back to fight, respawn, kill feed, duels and challenges).
- Online transformations of extra fighters hold the fight about 1.7 s instead of about 4 s. Body Change and timed fusion are not available online yet. BT3 USA only.

## 0.1.0-beta.42

Includes everything in beta.41.

- Fixed TTM-MATCH-08 "Invalid native preparation block count" when a valid match setup needed more than 1,024 patch records. Both the trainer and native validator now use the reserved packet buffer's capacity, retaining the complete guard check before any patch writes.
- Invalid destinations and oversized packets are checked before publication, with the actual record and byte counts included in the error details.
- Rematches and prepared presets upgrade only the exact previous validator image; foreign code and pending transactions still reject. Original checkpoints remain unchanged.
- Preserved beta.41 camera, beam-assist and resource fixes. Pending scenario development remains outside this release.

## 0.1.0-beta.41

Includes everything in beta.40.

### Beam clash camera

- New option: Beam struggles > Beam clash camera: Switch to clash (native, the default) or Keep player views. With Keep player views a beam struggle no longer takes over the camera: in split screen each view keeps following its own player, and a single view keeps following you, from the clash to its end. Switch to clash keeps the game's own struggle camera exactly as before (in split screen a clash of two ultimates fills the whole screen).

### Beam assist

- Up to four teammates can now assist one struggle, on either side. Each assister spends its own blast stock and adds its own share (Assist multiplier, x1.5 by default) to its side's push and final damage. One side's bonus stops at x3, and the final damage of both sides together at x4. The caption shows the side's total: BEAM ASSIST X1.5, X2, X2.5, X3.
- Assisters now stand much closer, just behind and beside the struggling teammate, so they join the same beam: the first two at its shoulders, the next two a step further back and wider. They are still kept inside the arena and out of the terrain.
- Joining now starts with a short transition: the teammate flies in from where it was to its spot (about half a second) and only then takes the firing pose. When you assist, your view switches to your teammate's view of the clash only after your pose has taken, and stays there until the clash ends.
- As in beta.39, nothing is spent unless the assister actually reaches the pose; otherwise ASSIST FAILED - BUSY / BLOCKED / HIT says why, and you can try again.

### Fixes

- Fixed matches stopping with TTM-MATCH-08 "Replacement texture group is not independent" after a costume or form reload. The game frees a texture group when a short effect ends even if a fighter still uses it, and the next reload could be handed that fighter's group. Reloads now first mark every group still in use and take the highest free one.
- Fixed a rare stop when an extra Cell absorbed an Android with almost no texture groups left ("Cell form request changed after auxiliary publication"). The absorption scene is skipped in that case and Cell still changes form.

## 0.1.0-beta.40

- Updated ground walking and running with the approved animation revision, body-proportioned root motion and continuous native cadence. Other movement animations keep their existing clips.
- Safer defusion placement around terrain and arena boundaries; original bodies load before the power-down presentation, and multiplayer camera ownership is restored without the legacy two-player fallback overwriting it.
- Restored the native drawing state for interactive clash prompts in split-screen and prevented a HUD code region from overlapping four-view cinematic checks.
- BT3 uses PCSX2 automatic graphics corrections during the session to avoid offset character outlines at higher internal resolutions. BT4 retains its existing graphics-fix preferences. Original emulator preferences are restored on exit.
- Preserved beta.39 lock-on and beam-assist changes. Scenario development remains outside this release.

## 0.1.0-beta.39

### Lock-on indicator

- The gold arrow above your target is back as the default target indicator. The Tenkaichi Tag Team ring is now an option: HUD > Target indicator: Gold arrow (default), Ring, or Arrow and ring. HUD > Mark your target (was Ring around your target) still switches the indicator off. Settings saved by beta.38 get the arrow.
- The ring is much smaller and follows your target's size on screen: about 12 to 34 pixels across the radius in a full view, smaller far away, and smaller again in split-screen views.
- The indicator now shows in every layout, including two-player split screen with a team assignment and three or four players; each view marks its own player's target.
- The red arrows for enemies targeting you follow the same sizing: smaller far away and in split and quad views; the arrows on the view edge are smaller too.

### Beam assist

- The bonus (one blast stock, more push and more final damage) is now paid only once your teammate is actually posed in the struggle. If they cannot join (busy, hit, or no room to stand), the assist is cancelled with nothing spent and the caption says why: ASSIST FAILED - BUSY, BLOCKED or HIT. You can try again.
- The assisting teammate now stays posed next to their ally for the whole struggle (they no longer fall out of the shot). A CPU teammate stands beside its ally inside your camera's view of the struggle; when you assist, your view turns down the beam toward the enemy. The teammate is kept inside the arena and out of the terrain.

## 0.1.0-beta.38

### Removed

- Tag attacks are gone: they did not work well enough. The Mod Settings page Tag attacks is removed (Mod Settings now has 17 categories), Select changes the battle camera distance again as in the original game, and the tag attack captions and Play window hints are gone. Saved settings from beta.37 that still name tag attack options load normally; those options are ignored. Matches are prepared exactly as beta.37 prepared them with tag attacks off.
- Splash damage is gone: no more damage to nearby fighters when a beam struggle ends or from ultimates. The options Splash damage when a beam struggle ends, Ultimate attack splash damage, Splash damage, Splash radius and Splash also hits the attacker's allies are removed (old saved values are ignored). The other beam struggle options are unchanged.

### Lock-on: Tenkaichi Tag Team look

- Your lock-on target now has a yellow double ring with an arrow on each side around its body, like the PSP game Tenkaichi Tag Team, instead of the gold arrow. The ring keeps the same size on screen near and far, and shrinks in when you switch targets.
- Enemies targeting you are marked by a pair of red arrows pointing in at them instead of a red square, or by one red arrow on the edge of your view pointing toward them when they are off screen. While an enemy attacks you, its arrows grow and blink yellow and red; when that enemy is your target, the ring's side arrows blink instead.
- The logic and the settings are the same as in beta.37. Settings names: HUD > Ring around your target (was Arrow above your target); HUD > Enemies targeting you: Hide, Arrows, or Arrows and attack warning (were Marks).

### Beam assist

- Beam assists work differently. Stand near a teammate who is in a beam struggle (new option Assist range from the struggling ally, default 60) and press R3 alone: it spends 1 blast stock, you are placed behind your teammate in your own beam-firing pose until the struggle ends, and your side pushes harder and deals more final damage (the Assist multiplier, default 150%, unchanged). One assist per side. CPU teammates can assist too (option CPU fighters assist too, on).
- The caption says "BEAM ASSIST X1.5" ("APOYO AL RAYO X1.5" in Spanish). The hint "R3 - BEAM ASSIST" ("R3 - APOYAR AL RAYO") shows while you are close enough to assist.
- The R3 press that starts an assist is taken before your fighter reads it, so it never transforms you. When you cannot assist, R3 works as usual.
- The Blast 2 or Ultimate input no longer assists.

### Walk and run

- Walk and run on the ground (Mod Settings > Movement, off by default) was redesigned:
  - Ground speed follows each fighter's leg length, from 55% to 125% of Goku's: small fighters run slower with longer, bounding strides, large ones faster. New option Size changes ground speed (on).
  - Running builds up over a third of a second, a sharp turn back while running skids, and braking plays a stop step.
  - The legs move at the speed the fighter really travels (at most 9 steps per second; a fighter that would need more is slowed instead), so the feet stay planted instead of sliding.
  - Running speed and Walking speed are now percentages of a natural run (100% is about 60% of the game's own ground speed for Goku).

### BT3 Europe, BT3 Japan and BT4

- The changes are the same on every supported disc.

Known issues:

- Beam assist: the struggling side's beam does not grow; only the push and the final damage change. The assisting fighter is placed without checking the arena edges.
- Lock-on: the arrow sizes do not shrink with three or four players, so they look larger in small views.
- Before packaging, each change was played live in its own test build on BT3 USA; the release was then checked once live on a fresh BT3 USA installation.

## 0.1.0-beta.37

### Fixes

- Fixed: a match with more than two fighters per side could freeze for good while several fighters drew after-image trails at the same time, for example a 5v5 Team Battle on Muscle Tower with ultimates (also seen in online matches). The game keeps those trails in lists made for two fighters; every fighter now has its own list.
- Fixed: when a rush or an ultimate started while another pair's rush was still running, both pairs could stand frozen for about 20 seconds until the mod released them (TTM-MATCH-21). The fighters a shared camera shows, and the two fighters of a rush that is still running, now keep moving, and a shared camera no longer starts while another pair's rush runs.
- Cinematics: a shared camera now pauses only the fighters outside its scene (Mod Settings > Cinematics > Special-move pause; the page's help says so).
- Fixed: rarely, a match never finished loading: the loading screen stayed at 0 % on 'Loading your selected fighters...'. It was reported with Cell (1st Form) and Dr. Wheelo against Vegeta (Scouter) and Krillin on the Hyperbolic Time Chamber, but it could happen with any fighters and stage. On beta.36 or older, press Start to continue.
- Fixed: a match could stop while getting ready with TTM-MATCH-08 ("Additional cached primary-row reference prevents safe relocation"), on the first fight or on a later one after a new character selection, and you had to close PCSX2 and start Play again. Three kinds of game data could look like a game address to the mod's safety check:
  - the music or a voice line playing at that moment, for example 'Hero - Kibou no Uta -' on the Spanish BT4 disc;
  - the animation, model or combat data of a few fighters, for example Super Trunks on BT3 USA, and Yamcha, Great Ape Baby, Bardock in his third costume, or Golden Frieza or Top leading a team on the Spanish BT4 disc;
  - the stage: on the English BT4 disc every match on stage 70 stopped this way.
- The check now ignores the game's music and voice buffers on every supported disc (BT3 USA, Europe and Japan, BT4 English and Spanish), and recognises a fighter's own files and the stage file as game data where they are exactly as on the disc. Everything else it checks is unchanged. If the check ever stops a match again, the message names the value and the address it found.

### Controllers: check-in

- Player Setup is now a live controller panel. Each row names that player's controller, and a light on the row flashes when that player presses something. With three or four players, everyone presses START once on their own controller to join, and Continue unlocks when every seat is filled. A controller PCSX2 already uses as its player 1 or 2 keeps that number; any other controller becomes player 3, then 4, then fills players 1 and 2. SELECT leaves a seat, Left/Right on your own controller changes your team, and Clear check-ins starts over. With two players, PCSX2's order stays the default, but anyone may check in. Check-ins are kept for the next matches until Play closes.
- A keyboard, or a pad only PCSX2 can read, joins as player 1 or 2 through PCSX2 by pressing its START; those seats keep PCSX2's mapping and rumble.
- Settings: Mod Settings > Players and controllers (the page was called Character select) > Controller check-in: Required with 3 or 4 players (the default for new installations and Restore defaults), Required with 2 to 4 players, or Optional (connection order), the earlier behaviour, which settings imported from an older installation keep until you change it. Keep check-ins for the next matches is on.
- If a player's controller disconnects, only that fighter stands still (TTM-CTRL-22); reconnecting it, or holding START for 2 seconds on a free controller, gives the seat back without pausing the game.
- Fixed: choosing controllers could close Player Setup and send everyone back to the player list (the controller reader took 3 seconds to attach). It now attaches in milliseconds and never holds up the screen.
- Fixed: PlayStation-type controllers (DualShock 4, DualSense, Switch Pro) could stop working for the mod after Player Setup or between screens, so players had no input until PCSX2 was restarted. One controller reader now runs for the whole Play session.
- Fixed: players were identified by a controller number that changed with the order pads were switched on, so one pad could drive two players and another nobody. Controllers are now identified by the pad itself, shown by name, and matched against PCSX2's own controller ports.
- Fixed: many controllers PCSX2 reads (PS2-to-USB adapters, Logitech, 8BitDo and Hori pads in DirectInput mode) were invisible to the mod. It now loads PCSX2's controller database, and your own game_controller_db.txt in PCSX2's data folder if you have one.
- Fixed: a pad shown twice by DS4Windows or Steam Input could never be chosen. The mod now uses one copy and says so (TTM-CTRL-23).
- Every controller problem now has a TTM-CTRL code (20 to 25) with English and Spanish text in the Play window and a line on the panel; README and LEEME list them.
- Players 3 and 4 never come from PCSX2 (the game loads no multitap support); the README no longer suggests fixing them in PCSX2's settings.

### Lock-on: who is targeting you

- New: marks for the enemies targeting you. A small red square sits left of the overhead bar of each enemy locked on to you, or on the edge of your view in that enemy's direction when it is off screen. While that enemy attacks you (an attack or blast aimed at you, one of its projectiles, or a hit on you in the last 1.5 seconds) its mark grows and flashes yellow and red. Each player sees the marks for their own fighter in every layout: one view, split screen, two players with a team assignment, and three or four players. Setting: Mod Settings > HUD > Enemies targeting you: Hide, Marks, or Marks and attack warning (the default).
- New: switch to your attacker. During an attack warning, or up to half a second after it, the target-switch tap locks on to the enemy attacking you: the one that hit you most recently, otherwise the nearest one attacking. Without a warning the tap switches as before. Setting: Mod Settings > Controls > Switch to your attacker: Never, Tap during a warning (the default), or Tap, or automatic when hit (which also switches by itself when one enemy deals 1000 HP within 3 seconds, at most every 5 seconds).
- Both are on for every installation, settings imported from beta.36 included. The marks and the switch are independent: with the marks hidden, the switch still follows the unseen warning. With Never and Hide, matches play exactly as in beta.36.
- The marks are hidden during shared ultimates and other cinematic cameras, grabs and rush cinematics, result screens, and while one fighter's transformation or ultimate close-up owns the view. A defeated or spectating player sees none.

### Outnumbered

- New settings page Mod Settings > Outnumbered (after Revival), off by default. Help when outnumbered: Off, Balanced, Strong or Custom (rows below). A fighter is helped while it is alive and on the side with fewer living fighters (Team Battle, Co-op) or, with Who counts as outnumbered at Smaller team or 2+ attackers (the default), while two or more living enemies target it (every mode, Free-for-all included). Help applies to: Every fighter (the default) or Players only.
- Damage follows the living team sizes: per extra enemy each of you faces, the smaller side deals more and takes less (at most 300% dealt, at least 40% taken). Equal teams and Free-for-all keep normal damage.
- Recovery and get-up speed: knock-back flights, knock-downs, get-ups and hit reactions advance faster while helped.
- Protection after getting up: for the set time after a get-up starts, ordinary hits neither stagger nor hurt; Blast 2 attacks (super ki blasts, rush supers, ultimates), rushes and throws still do.
- Combo breaker: after the set number of combo hits, one second of the same protection and an ended knock-back, at most every 5 seconds; it waits while a rush, throw or paired super runs.
- Balanced: +15%/-10% per extra enemy, 150% speed, 0.5 s protection, breaker at 12 hits. Strong: +40%/-30%, 200%, 1 s, 8 hits. Custom starts from the Balanced values. Off, or Custom with every value row neutral, plays exactly as beta.36.

### Tag attacks

- New settings page Mod Settings > Tag attacks (after Outnumbered), on for new installations and Restore defaults; settings imported from beta.36 keep it off until you turn it on. In Team Battle and Co-op, a player who has a teammate presses Select (Tag attack button: Select or L3): the nearest free living CPU teammate (Who answers the call: Nearest free partner, or Every free partner) dashes at the caller's target and attacks with its rush-in and melee string, then fights on by itself. Its hits chain onto a target you are hitting (a tag combo).
- L2 held with the tag button makes that teammate fire its own Blast 2 super at your target (L2 + tag button: partner fires a super; off by default, because in testing it hit a stunned target only once in five calls). It is the teammate's own move, so it can miss or be blocked.
- A call costs blast stocks (Tag attack cost, default 1; Partner super cost, default 2), paid at the press and refunded when no teammate sets off or the super never starts. Then you wait (Wait between calls, default 5 seconds).
- With no CPU teammate free, a human teammate gets PARTNER NEEDS HELP and you get HELP REQUESTED; nothing is paid. Human teammates are never controlled.
- Captions at the bottom left of your view say what happened (PARTNER RUSH, TEAM RUSH, PARTNER SUPER, NEED n BLAST STOCK(S), TAG ATTACK NOT READY, NO TARGET, TARGET BUSY, NO PARTNER FREE, and so on; in Spanish too). With three or four players there are no captions.
- While Select is the tag button, Select no longer changes the battle camera distance (near, mid, far) for a player who has a teammate; your starting distance and Battle camera zoom-out still apply. L3 alone has no game action, so choosing L3 changes nothing else.
- Not in free-for-all, Modded Training or CPU-only matches, and off while the tag button is also the target-switch button, or the lock-off button while lock-off is on (the Play window says so). Turned off, matches play exactly as in beta.36.

### Beam struggles

- New settings page Mod Settings > Beam struggles (after Tag attacks):
  - Beam struggle length: Native (the default), Long (x2) or Very long (x4) of the disc's own contest time.
  - Win early by leading by N inputs (0 = off, the default; up to 35): the struggle ends the moment one side leads by N.
  - CPU struggle strength (25-200%, default 100%).
  - Others can hit fighters in a beam struggle: enemies of a struggling fighter can hit them with melee and ki blasts (never throws, grabs, specials or rush cinematics); struggling fighters do not flinch, and health lost during the struggle weakens their push (Push lost per health lost, default 200%). A knockout ends the struggle.
  - Splash damage when a beam struggle ends, and Ultimate attack splash damage (Off, Energy ultimates or All ultimates): fighters near the loser or near the ultimate's target take a share of the hit (Splash damage, default 50% at the centre; Splash radius, default 60), less farther out. Splash never knocks out (it stops at 1 health) and, unless "Splash also hits the attacker's allies" is on, only hits the attacker's enemies.
  - Teammates can assist a beam struggle: a teammate's Blast 2 or Ultimate input during a struggle spends 1 blast stock; that side pushes harder and the final damage grows by the Assist multiplier (default 150%), whoever loses (at most two assists per side). CPU fighters assist too (option, on). A caption shows "BEAM ASSIST X1.5", and an eligible human teammate sees "BLAST 2 - BEAM ASSIST".
- New installations and Restore defaults start with hits on struggling fighters, splash when a struggle ends, splash from energy ultimates and team assists (CPU allies too) switched on, with the native struggle length. Settings imported from beta.36 keep every option off; with every option off, beam struggles play exactly as in beta.36.

### Walk and run on the ground

- New settings page Mod Settings > Movement (after Controls). Walk and run on the ground (off by default): on solid ground, fighters walk or run with new animations instead of gliding just above it. Dashes, jumps, flight and water stay as they are.
- Stick tilt to run (default 60%; 0 = always run): tilt the left stick past it to run, less to walk. Computer fighters always run; so does a pad with no analog reading (d-pad). Walking speed (default 40%) and Running speed (default 100%) are percentages of the game's own ground speed.
- The upper body turns toward the locked-on target while running sideways. Close to the target, where the game makes fighters circle it, they walk, back off or sidestep instead of hovering.

### Keep attacks and transformations in place

- New option Mod Settings > Cinematics > Keep attacks and transformations at their current location (off by default): rushes, ultimates and transformations play where they start instead of moving the fighters to the arena centre; the attacker never moves. A ranged ultimate still brings its target to the attacker (the animation needs both in one scene). A fighter that would end up under uneven ground is put on the ground instead, and the arena's own limits keep living fighters inside the arena.

### Settings

- Mod Settings (in game and Mod settings.cmd) now has 18 categories: Menus, Players and controllers, Controls, Movement, Cinematics, Fusion, Fighters, Giants, HUD, Split-screen HUD, Spectating, Revival, Outnumbered, Tag attacks, Beam struggles, Training, Launch options, Diagnostics. The in-game category list scrolls (with arrows) when they do not all fit.

### Developer folders

- Developer folders (bt3-multifighter and bt4-multifighter, started with "Play (any teams).cmd" / "Play BT4 (any teams).cmd"): a setting their mod-settings.json lacks, a missing file and Restore defaults now take player-installer/player-defaults.json, exactly as a new installation does, so they get the same features as an installed Play. The Play window names any setting that still differs ("Details: python tools/dev_settings_parity.py --report"). Installations and upgrades are unchanged.

### BT3 Europe, BT3 Japan and BT4

- The fixes and the new features are the same on every supported disc.

Known issues:

- De-fusions look as they did in beta.36: the planned smoother de-fusion is not part of this release.
- Before packaging, each fix and each new feature was played live in its own test build (on BT3 USA, the music fix also on BT4); the release build that combines them was checked offline only.
- Tag attacks: the partner's super is its own Blast 2 and can miss; captions show only with one or two views.
- Beam struggles: computer fighters seldom attack fighters in a struggle, so hits on struggling fighters come mostly from human players. A fighter next to the clash sees mostly the white glow of the beams, as in the original game.
- Enemies targeting you: knock-down damage and projectiles hitting a guarding fighter do not count as hits (those attacks still warn).
- In the in-game Mod Settings, the down arrow of the category list overlaps the corner of the selected row.
- The target arrow and the overhead health bars are not drawn with three or four players, or in a two-player match set up with a team assignment (the marks of the enemies targeting you are).
- A mute you set in the Windows volume mixer while a loading screen is up is undone when that screen ends; set it again afterwards.
- One installation switches only between the discs of one game; BT3 and BT4 need separate installations. A new installation does not copy the discs you added.
- Not played live before this release was packaged: a Linux desktop with controllers and sound; three or four human players with physical controllers (the check-in was played with virtual controllers); fusions and Ginyu's Body Change on the Japanese disc.

## 0.1.0-beta.36

### Japanese disc

- New: the Japanese BT3, Dragon Ball Z Sparking! Meteor (SLPS-25815), is supported next to BT3 USA and BT3 Europe. Setup recognises its ISO and installs the mod from it. A BT3 installation of this release can also add it on the Game disc page (Mod settings.cmd > Game disc) and switch between the USA, European and Japanese discs there.
- The mod runs one code base on all three BT3 discs: every USA game address is translated through a reviewed table built from the Japanese executable (985 addresses), and anything missing from the table stops the build instead of being guessed. The Japanese disc's file numbers, fighter state numbers, menu buttons and the 13 game functions the Japanese build changed are handled explicitly.
- The game keeps its Japanese text and voices. The mod's menus, loading screens and battle prompts are in English or Spanish, as on the other discs, and the mod shows English character names; the portraits come from your disc. The game's own font has no accented letters, so the Spanish descriptions the mod writes into the main menu (Modded Modes) are shown without accents.
- Buttons: the Japanese menus confirm with Circle and go back with Cross, and so do the mod's pages inside them (Modded Modes, opened with Select on the main menu, and its mode pages). At the end of a match, Circle picks Fight Again. The mod's own screens keep the buttons their footers show: Cross confirms and Triangle goes back in Choose your teams, and the in-game Mod Settings opens a category with Cross, saves with Square and closes with Triangle.
- First start with a new memory card: the Japanese game asks whether to create game data and then whether to format the card, with No highlighted both times. Press Left and then Circle for Yes to keep your progress; with No the game goes on without saving.
- Game progress is saved per disc: characters unlocked with the USA or European disc are not unlocked on the Japanese one.
- A Japanese ISO that beta.35 refused is scanned again. The Japanese Sparking! Meteor demo (SLPM-61162) is still not supported; setup names it and stops.
- Setup's and the Game disc page's messages name the Japanese disc among the supported BT3 discs, in English and Spanish.

### BT3 USA, BT3 Europe and BT4

- No gameplay change: the game code the mod writes for these discs is byte-identical to beta.35.

### Played live

- Before this release was packaged, on PCSX2 2.8.2, with installations made from test downloads of these changes and started through their own Play.cmd (keyboard controls through PCSX2's own bindings, no physical controller), on the Japanese disc:
  - a Team Battle 3v3 with 1 player, a free-for-all of 8 fighters with 1 player and a two-player split-screen Team Battle 3v3, all picked from the Japanese menus, and a Team Battle 5v5 with 1 player.
  - In those matches: the loading screen with English names and the disc's portraits; the battle camera zoom-out at 150%, picking targets with the right stick alone, taps of the switch button and the target arrow; computer ultimates with their cinematics; an extra fighter's Kaioken and extra fighters' damaged-costume reloads; taking over a teammate with Square and transforming it up to Super Saiyan 3 with R3; a new target after a KO; the camera moving to a teammate after a player's fighter falls, for Player 1 and for Player 2; a time-out; and Fight Again from the Japanese end menu.
  - Modded Modes on the Japanese main menu in English and in Spanish.
- One USA installation switched USA > Japan > Europe > USA on the Game disc page, and Play started each disc to Modded Modes. Check installation passed after every switch.

These changes apply to BT3 on Windows and Linux. The Linux package includes the Japanese disc too, but it was not tried on Linux.

Known issues:

- Not played live on the Japanese disc before this release was packaged: fusions; Ginyu's Body Change; a match with Spanish mod menus; three or four human players; the in-game Mod Settings; Build expanded maps; Linux. A computer extra fighter was not seen transforming on its own on the Japanese disc (a taken-over one did).
- A rush between two fighters can stop the match for about 30 seconds when a third fighter uses a special move at the same time. The mod then releases it (TTM-MATCH-21) and the match goes on.
- The target arrow and the overhead health bars are not drawn with three or four players, or in a two-player match set up with a team assignment.
- A mute you set in the Windows volume mixer while a loading screen is up is undone when that screen ends; set it again afterwards.
- One installation switches only between the discs of one game; BT3 and BT4 need separate installations. A new installation does not copy the discs you added.
- Not played live before this release was packaged: a Linux desktop with controllers and sound; a BT4 match on the Spanish disc; three or four human players; a physical controller.

## 0.1.0-beta.35

### Lock-on

- New: pick your target with the right stick alone, the default on new installations (Mod settings > Controls > Picking with the right stick: Stick alone (in combat), in the desktop window or the in-game Mod Settings). While you are locked on in combat, flick the right stick with no button held: left or right steps to the next enemy around you, up or down picks the enemy above or below your target, one target per flick. The right stick then no longer moves the camera. Unlocked, it moves the camera as before, and a tap of the switch button locks on again. R3 always wins: a flick with R3 pressed at the same moment, just before or just after it picks nothing, so transformations always go through. The stick alone also works when the switch button is R3.
- Holding the switch button (L3 on new installations) and flicking the right stick, as in beta.34, still works with the stick alone. To make the right stick pick targets only while you hold the switch button, and keep its own camera controls while locked on, set Picking with the right stick to Hold switch button. An installation that copies its settings from an older one keeps Hold switch button. Like every setting, the choice applies from the next match.
- Controls > "Switch button + right stick picks a target" is now "Right stick picks a target"; your choice carries over. Turned off, the right stick picks no target in either way.
- With the stick alone, lock-off (holding the switch button alone) happens once its hold time is reached, while you hold, as before beta.34. With Hold switch button it still happens when you let go, so a late flick still aims.
- Fixed: with Hold switch button, holding R3 before a flick made the game see R3 released and pressed again; with a switch button other than L3 that could start a transformation.
- A new target arrow: a bevelled gold dart that drops in when your target changes or you lock on again, bobs for about two seconds, then holds still. It is drawn under the health bars, so it never hides one.
- "Marker above your target" is now HUD > Arrow above your target, a switch of its own, separate from the health bars: the arrow shows with the health bars off, and the bars show with the arrow off. If you had turned the old marker off, try the new arrow. Like the overhead health bars, it is not drawn with three or four players, or in a two-player match set up with a team assignment; those split-screen panels show each player's target instead.
- Restart Play and prepare a new match after updating: a Fight Again of a match prepared before the update is refused.

### Camera

- New: Mod settings > Cinematics > Battle camera zoom-out (the desktop window or the in-game Mod Settings). 100% (the default) is the game's own camera; up to 200% in 5% steps pulls the battle camera further back. At 100% nothing new is installed.
- It moves back the follow and lock-on cameras of every fighter a player is watching: single view, split screen, three- and four-player views, after a KO and while spectating, in Team Battle, Free-for-All and Modded Training (a quick place to try values). One value applies to every player's view.
- What it does not change: close-ups keep their framing (ultimates, specials, transformations, grabs and throws, beam struggles, intros and results; they start from, and blend back to, the zoomed camera); battles started from the game's own menus keep the game's camera; and the cameras of computer fighters nobody is watching stay the game's own.
- The game's own camera smoothing is kept at every zoom. Walls and scenery can still pull the camera closer.
- Giants: with Larger canonical-style giants on, the Giants page's Giant follow camera distance and the zoom-out multiply, up to a fixed limit, so very large fighters gain less. The Giants help says so.
- A computer fighter you are watching may fight slightly differently at a higher zoom (the game's AI reads its own camera).
- Applies from the next match; Fight Again keeps the setting of its match.

### Played live

- Before this release was packaged, on PCSX2 2.8.2, with installations made from test downloads of these changes and started through their own Play.cmd (keyboard controls through PCSX2's own bindings, no physical controller):
  - BT4 B14 REV2 English, a 10-fighter free-for-all (1 player and 9 CPU fighters on Tournament of Power - Climax). With Hold switch button, taps of L3 stepped through the enemies in circle order, holding L3 and flicking the right stick stepped one target, and lock-off happened on release. With the stick alone, each flick stepped one target and no stick command reached the fighter, lock-off happened while L3 was held, and a flick with R3 at the same moment picked nothing. The arrow with the health bars off, the bars with the arrow off, and a two-player split with an arrow in each view. The zoom-out at 200% together with the stick alone and the arrow, and a match with every new setting at its default (nothing of the zoom-out installed).
  - BT3 USA, a Team Battle of 1 player against CPU fighters, with Hold switch button and with the stick alone; there a flick with R3 at the same moment started the transformation instead of picking a target.
  - The zoom-out at 150% through Play on BT3 USA, BT3 Europe and BT4 English, and at 100%, 150% and 200% in prepared test matches of BT3 USA and BT4 (also on PCSX2 2.5.211): one view, split screen, three- and four-player views, giants and several stages.

These changes apply to BT3 (USA and Europe) and BT4, on Windows and Linux. The in-game settings screens change only on the Controls, HUD and Cinematics pages and the Controls, HUD, Cinematics and Giants help.

Known issues:

- A rush between two fighters can stop the match for about 30 seconds when a third fighter uses a special move at the same time. The mod then releases it (TTM-MATCH-21) and the match goes on.
- The target arrow and the overhead health bars are not drawn with three or four players, or in a two-player match set up with a team assignment.
- With the stick alone, the right stick's own camera controls do nothing while you are locked on in combat: the camera side swing and the game's camera-distance change on right stick up. Unlocked, they work as before.
- While the Start pause menu is open, a tap of the switch button (as in beta.34) or, with the stick alone, a flick of the right stick still changes your target; the pause menu itself does not react to the right stick.
- Near walls and scenery, a high zoom-out makes the game's wall check pull the camera in more often, and the camera jumps further when it does. In tests on some stages this was clear at 175% and at 200%. Lower the zoom-out if it bothers you.
- At a high zoom-out the fighters look smaller, but the health bars and the target arrow keep their size.
- A mute you set in the Windows volume mixer while a loading screen is up is undone when that screen ends; set it again afterwards.
- One installation switches only between the discs of one game; BT3 and BT4 need separate installations. A new installation does not copy the discs you added.
- Not played live before this release was packaged: a Linux desktop with controllers and sound; a BT4 match on the Spanish disc; three or four human players; a physical controller (quick or light right-stick flicks with the stick alone are still to be played on a real pad).

## 0.1.0-beta.34

### Game disc switcher

- Mod settings (the desktop window, Mod settings.cmd; Mod settings.sh on Linux) has a new **Game disc** page. Add your other ISOs of the same game there and choose which one Play starts. BT3 USA and BT3 Europe switch in one installation, and so do BT4 B14 REV2 English and Spanish. The first time you add an ISO it is read once in full (up to about a minute); after that, a switch takes under a second.
- A disc of the other game (BT3 in a BT4 installation, or the reverse) is refused with TTM-DISC-21: it needs its own installation.
- Each added disc keeps its own fighter names, portraits, game program and expanded maps in game/discs, and game progress is saved per disc. Play reads your choice once when it starts and runs the whole session on that disc. Switching is refused while Play or the installation's PCSX2 is open (TTM-DISC-20).
- If the chosen disc's files are damaged, Play stops with TTM-PLAY-46 instead of starting another disc, and Check installation reports TTM-CHECK-19. Choose a disc again on the Game disc page (the disc you installed with always works), or add the same ISO again to extract its files again. The page, Play and Check installation explain every refusal with a code (TTM-DISC-20 to -35), in English and Spanish.
- The mod's own expanded-map ISO cannot be added as a disc (TTM-DISC-31), and expanded maps are never built from a disc whose stage files were changed. Expanded maps are built per disc: run Build expanded maps.cmd again after switching if you use them.
- Messages that told you to install the mod again for another ISO now point to Mod settings > Game disc.
- Setup's copy from an older installation does not copy the discs you added; it says how many it left behind. Add their ISOs again on the new installation's Game disc page.
- The Play window names the disc it starts and says where to choose another. While Play or its PCSX2 is open, the Game disc page says so and does not offer Use this disc. An ISO being added can be stopped with the page's Stop button; nothing of it is kept.
- When you choose the Spanish BT4 disc, the page asks whether to show the mod's own menus and messages in Spanish too. Choosing a disc never switches the language back; change it in Mod settings > Menus if you want.

### Stability

- Fixed the rare freeze while a match or a rematch was starting (a known issue in beta.33). It had two causes in the mod's own game code. Some of it left the game's stack a few bytes out of line; if the game switched tasks at that moment, the game's global data pointer came back wrong and the match hung. And the code that keeps the other fighters visible during a special move kept a memory address in one of two processor registers that the PS2 system itself overwrites whenever the game is interrupted. Every part of the mod now keeps the stack aligned, and none keeps an address in those registers. On the test rig the old code froze 3 times in about 300 match starts; the fixed code started about 1,300 matches without a freeze.
- Fixed code that could freeze a match while a defeated player watches or takes over a teammate, and during Body Change: it kept memory addresses in the same two processor registers. No such freeze was seen in testing; this fix is preventive.
- Closing PCSX2, or shutting its game down, during Fight Again is no longer reported as a failed rematch.
- The freeze check still reports a picture that stops for 5 seconds (TTM-MATCH-20), but time the computer spent asleep no longer counts.
- Match setup no longer stops when Windows briefly runs out of network ports (WinError 10048/10055): the connection to PCSX2 is tried again.
- Closing PCSX2 while the fighters' intros play at the end of match preparation is a normal close again. It was reported as a lost connection (TTM-MATCH-02), and the Play window stayed open with an error. Closing PCSX2 during a match no longer shows "Waiting for PCSX2 to start the game." first.
- A free-for-all is named as one in the Play window ("New free-for-all with 10 fighters" instead of "New 5v5 match"), and its loading screen no longer starts with "Preparing team battle".

### Sound

- Fixed fights and menus with no sound on Windows. The cause: while a loading screen or an error screen was up, the mod muted its PCSX2 in the Windows volume mixer. If PCSX2 was closed while such a screen was up (the error screen even asked you to close it), Windows remembered that mute for that PCSX2 and applied it every time it started again, so every later session was silent.
- The fix: every Play launch now unmutes its own PCSX2 as soon as its sound starts (on each output device), and error screens never mute: if a match setup, fighter update or rematch fails while the match keeps running, you hear it until the menus. A mute you set yourself in the volume mixer during a session stays on through loading screens.
- Older installations that are already silent: a new installation has its own PCSX2, which Windows has not muted, so installing this release is enough for it. An installation of beta.33 or earlier keeps its mute until you remove it by hand: start its Play.cmd, and while the game is running open the Windows volume mixer (right-click the speaker icon on the taskbar and choose Volume mixer, or Settings > System > Sound > Volume mixer), find PCSX2 and unmute it. Do the same for any other PCSX2 that went silent after it was closed during a mod loading or error screen. Linux never muted PCSX2.

### Lock-on

- A tap of the switch button (L3 by default) now picks the next enemy to the right, around you, in a fixed circle, so every enemy is reached in turn. Mod settings > Controls > Target switch order can change this to Nearest first, or to Selection order (the previous behaviour).
- New: hold the switch button and flick the right stick. Left or right steps to the next enemy around you; up or down picks the enemy above or below your target. While you are unlocked, a flick locks on to the nearest enemy in that direction. From the flick until you let go of the stick, the stick only aims, so its own actions never fire, and an R3 click while flicking is ignored. Turn this off with Controls > Switch button + right stick picks a target; it is also off when the switch button is R3.
- Lock-off (L3 held for 0.5 s on new installations): hold the button alone, then release it. While the right stick can aim, the unlock happens when you let go, so a late flick still aims instead of unlocking you.
- When your target is defeated, the enemy nearest your screen centre becomes your target, as your view was when it fell (after a cinematic, once your own view is back). Controls > When your target is defeated > Game default keeps the game's own choice.
- A small gold arrow marks your target in your own view during combat, with one or two players (Mod settings > HUD > Marker above your target). Three- and four-player split screens draw no overhead bars or arrow; their panels show each player's target instead.
- Selection order, Game default, and the right stick and the marker switched off together restore the previous behaviour. After updating, restart Play and prepare a new match.

### Setup: the BIOS comes from your PCSX2

- Setup no longer asks for the PS2 BIOS when your PCSX2 already has one: it uses the BIOS set up in the PCSX2 you select (PCSX2 Settings > BIOS) and copies it into the installation's private profile, as before. It reads the settings that PCSX2 starts with: on Windows beside pcsx2-qt.exe (or in the folder its portable.txt names) for a portable PCSX2, otherwise Documents\PCSX2; on Linux $XDG_CONFIG_HOME/PCSX2 or ~/.config/PCSX2, or the .config / .home folder named after the AppImage. Setup only reads your PCSX2 settings; it never changes them.
- The checklist names the settings file the BIOS came from, and says so when it is another PCSX2's (read only when the selected PCSX2 gives none). Identical copies of one BIOS dump count once. A BIOS set up in PCSX2 that is a PS1 BIOS or a companion file of a dump is named with the usual code, also when setup then uses the only PS2 BIOS of that folder.
- When no BIOS is selected (or the selected one is missing) and PCSX2's BIOS folder holds several, setup on Windows takes the one PCSX2 itself starts with: the first PS2 BIOS of 4 to 8 MiB by name, skipping hidden files as PCSX2 does, when that folder is on an NTFS drive (other drives list files in another order; a folder reached through a link or on a network drive also keeps asking). The checklist says "the BIOS your PCSX2 starts with, from" (or "the BIOS another PCSX2 on this PC starts with, from") and names that folder.
- Setup asks only when that PCSX2 has no BIOS set up, or has several different BIOS files and none selected and setup cannot tell which one PCSX2 starts with (a drive that is not NTFS, Linux, or a selected file that is not a PS2 BIOS); the file dialog then opens in PCSX2's BIOS folder. -Bios (Windows) and --bios (Linux) still choose a BIOS yourself.
- An unattended setup (folder, ISO and PCSX2 given on the command line) opens no dialog: without a BIOS it can use, it stops with TTM-BIOS-07 (none set up) or TTM-BIOS-08 (several, none selected); when it also refuses that PCSX2, the PCSX2 problem is the main block. On Linux, --destination, --iso and --pcsx2 are enough for a setup without Tk, and a setup started from a file manager shows why it asks for a BIOS in a window and names the copied BIOS in its final window.

### BT4

- Everything above applies to BT4 B14 REV2 as well: the English/Spanish disc switch, the freeze fixes, the sound fix and the new lock-on.
- The BT4 free-for-all start error "Missing own special resource" reported in September was already fixed in beta.9, and the match that stopped responding on September 23 (a special move's summon that found no free resource row) was fixed in beta.33.
- Played live on BT4 B14 REV2 English with PCSX2 2.8.2, installed from the download and started through the installation's own Play.cmd (keyboard controls, no physical controller). The 5v5 matches and the disc switches ran on the release candidate, one revision before the last fixes:
  - A 10-fighter free-for-all (1 player and 9 CPU fighters on Tournament of Power - Climax, started from its stage select). The lock-on: taps of L3 reached all 9 CPU fighters in circle order; right-stick flicks left and right stepped one target, and no stick command reached the fighter; holding L3 and releasing it turned the lock-on off; a defeated target passed the lock-on to the enemy nearest the screen centre; the gold arrow marked the target. CPU ultimates played with sound. The first match and three Fight Again rematches (each ready in 1 to 3 seconds) started without a freeze.
  - Two 5v5 Team Battles (1 player and 9 CPU fighters) on Kami's Lookout - Night and Planet - Evening.
  - Switching discs: Spanish, English, Spanish, English, with Play started after each switch. Each start ran the chosen disc (its title screen was in that disc's language, and its program was in memory). A switch while Play ran was refused with TTM-DISC-20, and the BT3 USA and Europe ISOs were refused with TTM-DISC-21. Adding the Spanish ISO took about 17 seconds; a switch took under a second.
- Sound in those BT4 sessions: PCSX2 was never muted or silent during the intros, the fights, the ultimates or the results. The mod mutes it only while its own loading screen is up (about 24 seconds for a first free-for-all preparation, 1 to 2.5 seconds for a Fight Again). Closing PCSX2 during a loading screen, or ending its process, left no mod helper running, and the next Play removed the mute Windows had kept within about a second.
- Before this release was packaged, the new lock-on had also been played on PCSX2 2.5.211, with the full sound pass there.

These changes apply to BT3 (USA and Europe) and BT4, on Windows and Linux (the sound fix is Windows-only). The game patches, in-game code and menus are unchanged apart from the fixes and the lock-on above, and the in-game settings screens change only on the lock-on lines.

Known issues:

- A rush between two fighters can stop the match for about 30 seconds when a third fighter uses a special move at the same time. The mod then releases it (TTM-MATCH-21) and the match goes on.
- Three- and four-player split screens show no lock-on arrow (they have no overhead bars).
- A mute you set in the Windows volume mixer while a loading screen is up is undone when that screen ends; set it again afterwards.
- One installation switches only between the discs of one game; BT3 and BT4 need separate installations. A new installation does not copy the discs you added.
- Not played live in this release: a Linux desktop with controllers and sound; a BT3 match on the European disc (it was started to its menus only); a BT4 match on the Spanish disc (it was started to its menus only); the Game disc page of a BT4 installation (its switches ran through the same backend); BT4 with two or more human players or a physical controller. The rare-freeze fix was tested live on the USA disc; the European disc and BT4 use the same fixed code but were not tested that way.

## 0.1.0-beta.33

### Installer

- Setup checks everything before it changes anything, and names the problem: a compressed, archived, CD-image or incomplete game ISO; a PS1 or PS3 BIOS, or one of the .ROM1, .ROM2, .EROM, .NVM or .MEC companion files of a PS2 BIOS dump; a PCSX2 that is too old, 3.x, 32-bit or incomplete; a folder without enough space or write access, or with square brackets in its path. It warns about OneDrive, network drives, Program Files and running as administrator.
- Every setup problem is shown as one block with a code (TTM-...), what happened, why and how to fix it, in English or Spanish, and says when nothing was changed. The setup log is kept in %LOCALAPPDATA%\TagTeamMod\logs (Linux: ~/.local/state/tagteammod/logs) and in the installation's installer.log.
- Install.cmd started from inside the ZIP explains that the ZIP must be extracted first. It removes the "downloaded from the internet" block, explains a Group Policy script block and always uses 64-bit PowerShell.
- Retrying after a failure or upgrading no longer needs a new folder. An unfinished attempt is renamed aside (never deleted), and a new version is installed beside a complete installation, with an offer to copy your memory cards and, for the same game only, your mod settings. Copying them and creating Desktop shortcuts can no longer turn a finished installation into a failure; a problem there is shown as a warning.
- Python and prerequisites: python.org installs in custom folders are found, a Python found only on PATH no longer blocks WinGet, a missing Tk or venv is named, WinGet errors are explained and the Visual C++ 14.40 or newer runtime is checked. Choosing the installation folder itself offers to repair its broken private Python.
- A damaged ISO is reported as damaged (TTM-ISO-07). Paths containing & print correctly. A PCSX2 installed with Scoop is accepted. The private PCSX2 profile binds the pause key (Space).
- Check installation reports coded failures in English and Spanish, with an antivirus hint and no traceback. A Play.cmd copied out of its folder, and a broken private Python, explain what to do.
- Linux: Install.sh is bilingual, checks its setup folder, and shows installer errors in a dialog when it is started without a terminal. Windows: the installation's README.txt now also has Spanish lines.
- A setup failure after the installation folder was created says what the next run does: it renames that folder aside and installs a fresh copy. While it checks the new installation, setup no longer prints raw check lines (a SHA-256, the release line); they stay in the setup log.
- The installation check (TTM-CHECK-02 to -05, -07, -14 and -15) and Play's missing-file and broken private Python messages (TTM-PLAY-24, -25, -28, -30, and -51 on Linux) now say what setup really does: run Install.cmd (Install.sh on Linux) and choose the installation's own folder, and setup installs a fresh copy beside it and offers to copy your memory cards and mod settings. On Windows the same release still offers to repair a private Python that no longer starts. They no longer tell you to copy files into a new folder by hand.
- The copy summary at the end of setup, and the note when setup installs beside an existing installation, say that PCSX2's own settings (controller bindings, graphics) and PCSX2 savestates are not copied: they stay in the old folder. The README update steps say so too.
- The installation's README.txt also has the European disc note in Spanish, and on Linux its lines in Spanish.

### Error messages

- Play explains every failure in a framed block with a code, what happened, why and how to fix it, in English or Spanish. The window stays open after an error.
- Play names what blocks it (a running PCSX2 with its path, or the program using the connection port), waits a few seconds for this installation's own PCSX2 to finish closing, and can end a stuck one after asking.
- A moved game ISO can be found again: Play asks for its new location and accepts only the same file.
- A failed match setup shows a red "setup stopped" screen with the code in game, and a failure report is saved in game\analysis\failures (the last 10 are kept).
- Messages name only launchers that exist in your installation (Play.cmd, Play.sh, Mod settings.cmd and so on), never the developer launchers.
- Accented or non-Latin folder names no longer break Play or its messages.
- A match that stops responding (its picture no longer changes) is explained with a code (TTM-MATCH-20), in English or Spanish, and the Play window keeps the explanation on screen after you close PCSX2. With freeze snapshots off (the default) it tells you how to turn them on (Mod settings > Diagnostics) for the next time; with them on, the snapshot is saved and the report file names it. If the picture moves again, the match goes on and it counts as a handled problem.
- A game that stops drawing while a match is starting is reported as frozen after 10 seconds, instead of "paused or minimized" after 90 seconds. With freeze snapshots on, a snapshot of it is saved first.
- A cinematic pause that the mod had to release is shown as a handled problem with a code (TTM-MATCH-21), Spanish text and a report file.
- After a failed setup, rematch or fighter update, the game's own menus are no longer covered or muted: the failure screen comes down when the game reaches its menus, and the explanation is shown once more in the Play window.
- Play and Mod settings refuse to start from a folder whose path has square brackets, and say how to fix it (TTM-PLAY-45), instead of stopping with an unexpected error.
- More messages are in Spanish and carry a code: the mod's helper stopping during a session (TTM-PLAY-37), the controller 3-4 and controller assignment notices, the original-menu match line, PCSX2 not answering for a while, the Modded Modes menu notices (now with their real next step), Mod settings failures on Linux, and a broken private Python on Linux (TTM-PLAY-51). Windows refusing access to PCSX2 for controllers 3 and 4 is explained as refused access instead of an unexpected error.
- The 1v3 setup failure "All actors must be held in native idle11" is fixed. A fighter that started its idle taunt during setup stopped the setup; setup now waits until every fighter stands still before placing them. A fighter that never stands still stops the setup after about 30 seconds with a plain message: start the match again from character selection.
- A damaged or missing installation marker no longer makes messages name the developer launchers. The broken private Python block shows its base Python on a line of its own instead of cutting the path in two.
- Starting Play after a normal session no longer says the last session was interrupted when it reuses its savestate slots.
- The Play window's routine lines are plain words in your language: a new match being prepared, the match and the rematch ready, waiting in the menus, the connection to PCSX2 (no longer "PINE"), the chosen mode and the untested PCSX2 version notice. Choosing the original game menu is shown as the original game menu, not as a team selection. The rematch checkpoint path is kept in watcher.log only.
- The moved game ISO block names Play.cmd (Play.sh on Linux) the same way in both launchers.
- The Play window no longer shows the start-up steps' technical lines (a SHA-256, the list of old folders cleaned up, the session speed and savestate settings) or "Using unchanged ISO compatibility profile" on every launch; they stay in the launch logs. In a Spanish installation the match preparation steps, the game ISO check progress and the start-up retry notice are in Spanish. Arriving at the main menu says "Original game menu" instead of "Original game menu chosen", since nobody chose it, and the note about reused savestate slots stays in watcher.log.

### Stability

- Interrupted sessions no longer use up savestate slots 220-239, and rematches keep one archive instead of adding a new one each time.
- A brief emulator connection error no longer stops the mod, and closing PCSX2 during a match is no longer reported as a failure.
- After a match that ends in a menu the mod cannot restore, the game returns to the clean main menu, with sound, instead of stopping the mod.
- Pausing PCSX2 during loading or during a fighter update waits instead of failing.
- Re-attaching fighter updates in the middle of a match no longer freezes combat.
- Space is sent only to the game window of the PCSX2 that Play started, never into a PCSX2 dialog.
- Clearing out old generated folders, or an old display-settings record, no longer blocks Play.
- A broken Modded Modes menu is switched off once, with an explanation, instead of being reset over and over.

### European disc

- A single in-game loading screen check that differs while a match ends no longer tells you to restart PCSX2. The mod checks again and warns only if the difference persists, naming the address.
- Resetting PCSX2 during a European match reproduces what the first European session showed: the game restarts. The mod now says so ("The game restarted during the match, so the mod loaded the clean main menu", TTM-MENU-20) and you can keep playing, instead of a failed return to the menu. Whether that session was reset from PCSX2 or by the game itself is not known.
- Lock-on and lock-off holds on the same button are kept at least one update apart at both 25 and 30 Hz, so the target switch can no longer become unreachable. A hand-edited lock-off hold that was too close is raised by 0.5 s.

These changes apply to BT3 (USA and Europe) and BT4. The USA and BT4 game patches, in-game code, menus and settings screens are byte-identical to beta.32.

Three live stress passes ran on scratch copies of the developer PCSX2 (2.5.211) with CPU fighters: match setup (2v2, 3v3 and 1v3), about an hour of matches, more than 100 rematches, pauses, freezes, dropped connections and closing PCSX2 on the USA disc, a European match with rematches and a reset, CPU transformations, rushes and ultimates, and the Modded Modes menu up to character selection. They found the 1v3 setup failure, the frozen-start message and the slot wording fixed above. Some messages were checked offline only. There was no human player, BT4, Linux, Great Ape, co-op fusion or 4-player split screen run. A final pass played two fresh installations made from this release through their own Play.cmd and PCSX2 2.8.2: the European disc in Spanish and the USA disc in English, each from boot through Modded Modes to a 2v2 prepared from character selection, a forced freeze kept on screen (TTM-MATCH-20) and a second Play refused while one runs. It found the Play window lines fixed above.

Known issues:

- A rare freeze early in a match's opening (seen once in about 200 match starts) is not fixed yet; turning on freeze snapshots helps find it.
- A rush between two fighters can stop the match for about 30 seconds when a third fighter uses a special move at the same time. The mod then releases it (TTM-MATCH-21) and the match goes on.

## 0.1.0-beta.32

- Fix team match preparation on the European disc stopping with "PREPARATION FAILED: ." after "Initializing individual NPCs...". The dust and terrain effects for extra fighters copy two native routines and locate their owner-table loads by their global-data offset; that offset is different in the European executable and was not translated.
- The complete final match setup was replayed offline against memory read from a live European 2v2 preparation and now composes; a new test builds these routines for both discs. USA and BT4 output is unchanged.

## 0.1.0-beta.31

- Add the European BT3 disc (SLES-54945; Original, Platinum, Collector's Edition and Australia/NZ are the same disc). Setup recognises it and installs the mod from it; the European game keeps its native 50 Hz and 512-line picture.
- The mod's code stays one source for both discs: every USA game address is translated through a reviewed table built from the European executable (987 addresses, all exact or high-confidence matches), and anything missing from the table stops the build instead of being guessed. Disc file numbers, graphics memory, screen placement, 50 Hz durations and the 17 game functions the European build changed are handled explicitly.
- Unsupported BT3-family discs (Japanese Sparking! Meteor and its demo, modified executables) are now named in setup, with the list of supported discs, in English and Spanish.
- USA and BT4 output is byte-identical to beta.30. The European install, its patch file and the offline audit of every generated European write were verified; gameplay on the European disc has not been played yet and needs a live check.

## 0.1.0-beta.30

- Fix match preparation with starting battle-damaged clothes, including BT4's Ragged Clothes Potara. Capture and resource validation now use each fighter's native clothes state instead of assuming intact models.
- Load and deduplicate extra fighters by character, costume and clothes state. An intact and damaged copy can coexist, and extras no longer inherit their leader's pending damage state.
- Applies to BT3 and both supported BT4 languages, on Windows and Linux. Resource identity, geometry and collision guards remain enabled.
- Verified two BT4 2v1 preparation/combat runs with native damaged-clothes inputs (leaders plus extra, and extra only), plus real-disc bundle and guest-code regression checks. This does not certify every Potara combination or character's artwork.

## 0.1.0-beta.29

- Keep reassigned controllers active through winner animations and the results menu in BT3 and BT4. Ending combat previously closed their input service while its guest hook remained enabled, preventing confirmation of Fight Again and other result-menu choices.
- Preserve the same input lifetime when the game advances into results between trainer polls; actual menu exits and rematch restores still release the old input services.
- Rematches launched without a loading-screen presentation no longer reactivate an archived loading cover that has no owner to dismiss it.
- Repeated prepared-match restoration and the native Fight Again transition were checked in BT3. These fixes do not certify every reported rematch symptom or BT4 character/stage combination.

## 0.1.0-beta.28

- Fix Spanish BT4's main-menu detection, including the native opening “¡”, so Select enables the mod menu and menu checkpoints can be captured. Accept BT4 dialogue-table alignment in the legacy menu detector too.
- Spanish BT4 installations now start with Spanish mod menus, settings, loading screens and battle prompts, even when setup runs in English. Language remains adjustable after installation.
- Fix match setup rejecting localized character/form names. Compact battle labels fold accents, support percent signs, and visibly shorten overlong names within their allocated slots; full names remain on loading screens. Applied to BT3 and BT4. All 250 Spanish BT4 labels are checked, and BT4 launch preflight now exercises this text path.
- Preserve Spanish ordinal/number signs when extracting names, including Android numbers and Freezer/Cell form numbers. Retains the reviewed executable, add-on, stage and fighter resource checks.
- Includes prior Windows prerequisite fixes and Linux support. Resource/install checks do not certify every move or stage; BT4 remains experimental.

## 0.1.0-beta.27

- Add the Spanish BT4 B14 REV2 ISO to the reviewed runtime variants. Its own resources, reference executable, labels and portraits are extracted and checked; the English ISO is not required.
- Preserve Spanish accented character/form names, and verify BT4 local references against the selected disc instead of a fixed English hash.
- Compare loaded executable code/layout separately from ELF packaging metadata. Pair the executable with its reviewed add-on and report the specific unsupported component. Runtime identity, cheat and checkpoint names follow the selected disc CRC.
- Includes the beta.26 WinGet source fix. Original European/PAL BT3 is not certified by this update.
- Offline resource and installation validation is separate from gameplay testing; BT4 remains experimental.

# 0.1.0-beta.26

- Windows prerequisite setup now explicitly uses the `winget` source for Python 3.11 and Microsoft Visual C++. An unrelated Microsoft Store source/certificate error (such as 0x8a15005e on a fresh Windows VM) no longer blocks these package searches. Certificate and installer-hash verification remain enabled.
- No gameplay, defaults or Linux installation behavior changes. Includes all beta25 changes for both BT3 and BT4.
- If a previous setup failed, extract this complete installer and choose a new installation folder; do not merge it into the failed partial install.

# 0.1.0-beta.25

- Fix Free-for-All character-selection badges using a stale Team Battle assignment. Three/four-player FFA slot labels now match the actual player seats even after a previous team setup, for both BT3 and BT4.
- Keep Player 1 Back available during delegated selection, the Linux help/readiness fixes and all earlier gameplay changes.
- Give Windows and Linux downloads separate, bilingual Start Here instructions with their correct launchers and short troubleshooting steps. The downloads still show just Install, README and setup at the top level.
- Audit the offline regressions before release; repair outdated trainer fixtures and test expectations for reviewed BT4 costume/stage fallbacks. Rendered HUD/menu/loading pixels are unchanged by this update. This remains a public beta; a successful install or structural ISO scan does not certify every character, move or stage.
- Restart Play and prepare a new match after updating. Use a new installation folder and follow the save/settings transfer instructions in the README when replacing an existing install.

# 0.1.0-beta.24

- Player 1 can always press Triangle (the mapped Back button) during delegated multiplayer character selection, including while Players 2, 3 or 4 choose their character, form or costume. Back wins over a simultaneous confirmation and remains available during controller handoffs or if the selecting controller disconnects.
- Respects Assign controllers and shared selection. Ordinary selection stays with the assigned player; original-game selectors retain native behavior. Included in BT3 and BT4 on Windows and Linux.
- Restart Play to load the updated menu hook. Existing installed copies need the new installer; an already running emulator keeps its current code. Automated selector and captured native cancel-dispatch tests passed; controller playtesting remains pending.

# 0.1.0-beta.23

- Linux settings help now names the installed `.sh` launchers in English and Spanish, including Mod settings and Build expanded maps. Windows wording and rendered screens stay unchanged. Both BT3 and BT4 include the correction.
- Check installation no longer reports ready when required Linux graphics/FUSE dependencies are missing. An explicit `--allow-missing-libraries` offline installation still completes, but clearly reports that system packages must be installed before playing; its saved readiness remains false. Optional SDL2 remains a warning for three/four-player input. The override cannot bypass corrupt files, incompatible dependencies, ISO checks or failed runtime checks.
- Reviewed the Linux launch, ownership, controller-memory and packaging paths; targeted Windows and WSL regression checks passed. Full Linux desktop gameplay with controllers/audio remains unverified. Existing unrelated full-suite failures are not claimed fixed by this release.

# 0.1.0-beta.22

- Linux support (new, both BT3 and BT4): a separate `Tag Team Mod 0.1.0-beta.22 linux-x86_64.tar.gz` with `Install.sh`. It works with the official PCSX2 AppImage 2.6.0 or later (x86-64) and installs offline, with bundled Python packages for Python 3.11-3.14. The install provides `Play.sh`, `Mod settings.sh`, `Check installation.sh` and `PCSX2 settings.sh` (for controller bindings in the mod's own PCSX2 profile), plus desktop entries.
- Linux needs Python with venv and tkinter, FUSE (`fusermount3`), `libOpenGL.so.0` (package `libopengl0` on Debian/Ubuntu) and, for three or four players and Assign controllers, `libSDL2-2.0.so.0`. The installer checks these and names the missing packages. Flatpak PCSX2 is not supported, because its sandbox hides the socket the mod talks to.
- On Linux the mod talks to PCSX2 through PCSX2's own socket and reaches controllers 3 and 4 through PCSX2's shared memory file; no special permissions are needed. Menus and labels use the bundled Liberation Sans font, so text looks slightly different from Windows.
- Tested on Linux (WSL Ubuntu 24.04, PCSX2 2.8.2 AppImage): installation, launching, the mod's boot hooks and the connection to the running game, up to the title screen. A full match on a Linux desktop with controllers is still to be checked.
- On Linux, if the 3-4 player check cannot confirm PCSX2's memory yet, it says so ("could not be confirmed yet; retrying"), tries again after 2, 4, 8, 16 and then every 30 seconds (at once for a new selection screen, match or controller assignment), and reports once a later check confirms that players 3 and 4 are available again.
- Windows: menus, loading screens and generated game code are byte-identical. One behaviour change (on Linux too): when the mod cannot attach controllers, either the ones set with Assign controllers or players 3 and 4, it now reports the problem and play continues with the default controls, instead of stopping the launcher or ending the match. Players 1 and 2 keep their PCSX2 controllers; if players 3 and 4 fail, their controllers stay off for that match and are tried again in the next one; Assign controllers can be used again in Player Setup.
- Check installation on Linux names a missing SDL2 once.

# 0.1.0-beta.21

- Fix repeated native search animations while manually unlocked. Holding the lock-off button again is idempotent, and ordinary movement/attacks retain their native input bits and registers.
- Suppress acquisition line/sound effects for manual locking and unlocking. Natural game lock acquisition retains its effects.
- Add HUD -> Target HUD while unlocked: Only with one enemy left (default), Hide, or Always show. Applies to the native target status panel and every split-screen target panel; player status and other interface elements remain available. Counts living opponents, excluding absent and fusion-consumed fighters, with free-for-all relationships respected.
- Include the fixes and bilingual setting in BT3 and BT4. BT3 live movement, repeated lock-off, relocking and HUD visibility were checked; BT4 was verified with automated guest-code and captured-memory tests.
- Restart Play and prepare a new match after updating. Existing rematch/savestate images retain their previously installed guest code.

# 0.1.0-beta.20

- Add manual lock-off: hold L3 for 0.5 seconds by default. Releasing the long press keeps you unlocked; tapping L3 switches targets or locks back on.
- Reacquire the living enemy closest to the centre of your own camera view. Offscreen, behind-camera, absent, defeated and allied fighters are excluded; no candidate leaves you unlocked. Supports single view and two-, three- and four-player views, including FFA.
- Controls settings provide an enable switch, independent lock-off binding and adjustable hold time, in English and Spanish. Shared bindings automatically extend the lock-off time when needed to distinguish it from target switching.
- Preserve native cinematic/damage ownership and valid internal combat references. CPUs and spectators keep their existing targeting behavior. Split-screen target status panels hide while unlocked.
- Included in BT3 and BT4. Automated guest-code, captured-memory preparation and installer checks passed; new-match gameplay confirmation remains pending. Restart Play and prepare a new match after updating; existing rematch/savestate images retain their old code.

# 0.1.0-beta.19

- Prevent the native summon loader from constructing a model from a failed or invalid resource. This caused a hard freeze during Goku's Super Spirit Bomb in a ten-fighter BT4 match.
- Give cinematic summons two dedicated overflow resource records when the ordinary character/costume/form records are full. Temporary character models load normally, keep independent ownership, and release their buffers when the move or match ends.
- Keep two texture groups available when admitting extra form/costume replacements; recheck texture capacity when consuming a cinematic resource. Exhausted or malformed loads fail safely before native geometry construction.
- Apply the shared fix to BT3 and BT4. The captured BT4 Spirit Bomb failure was replayed with a valid model binding and normal resource cleanup. This is separate from the shorter costume-update pauses, which remain a performance limitation.
- Restart Play and prepare a new match after updating. Existing saved/prepared matches contain their previously installed guest code.

# 0.1.0-beta.18

- Revival keeps progressing while you move inside the revive radius or perform the native idle taunt. Safe movement/taunt transitions no longer reset the timer. Damage, leaving range, attacking, and unsafe actor states still interrupt; stock cost and recovery protection are unchanged.
- Defeated players can take over living allied CPUs during ordinary movement, charging, punching and ki attacks. Current and queued rushes, grabs/clashes, ultimates, transformations, reloads and active cinematic cameras still block takeover. Ownership changes preserve the ongoing animation and ordinary queued actions.
- The takeover hint uses the same expanded eligibility. Both changes apply to BT3 and BT4, including three/four-player seats. Revival help is updated in English and Spanish.
- Automated guest-code and preparation tests passed; manual gameplay confirmation remains pending. Restart Play and prepare a new match for the new behavior; existing rematch/savestate images retain their installed code.

# 0.1.0-beta.17

- Add Assign controllers to the two-, three- and four-player setup screens. Each player presses Cross / A to claim a different controller. Team Battle and Training retain team assignment; multiplayer Free-for-All has a player setup screen.
- Apply the chosen controller order to character selection and gameplay. Assigned gamepads use standard controls; PCSX2 bindings are left untouched. Restore default controller order returns to the previous input path. Assignments last for the current Play session.
- Reject duplicate or simultaneous claims, capture quick button presses, and neutralize disconnected or stale input. Cancel keeps the existing assignment. All new prompts are available in English and Spanish.
- Include the changes in BT3 and BT4, preserving the beta.16 settings, loading screens and performance improvements. Hardware/remote-controller gameplay verification remains pending.

# 0.1.0-beta.16

- Fusion: two new switches on the Fusion page hide the "FUSED - PLAYER n HAS CONTROL" line and the "Pn TAKES CONTROL IN s" countdown. They matter only when two-human fusion controls swap every 20 s. Both are on by default, and with both on the game code is unchanged.
- Settings are reorganised into 14 categories: Menus, Character select, Controls, Cinematics, Fusion, Fighters, Giants, HUD, Split-screen HUD, Spectating, Revival, Training, Launch options (restart) and Diagnostics. Labels and choices are clearer, each category has an accurate help note in English and Spanish, and Restore defaults returns to the values you installed with without changing your language. Saved settings keep working.
- Every setting is now available in the in-game Mod Settings: a category list, per-character CPU transformation exceptions, Restore defaults, help (Circle), ten-step changes (L2/R2) and hold-to-repeat. Unsaved changes are confirmed before closing.
- Fix: in Spanish, opening some in-game settings pages stopped the launcher. Every in-game settings screen now draws well within the limit in both languages, and a screen that cannot be drawn shows an error instead of stopping anything.
- The loading animation speed applies from the next loading screen. Experimental 2x maps can only be turned on after Build expanded maps.cmd has run; if the expanded ISO is missing, Play starts the original game with a warning.
- PCSX2 2.6.0 and later are supported. The supported stable releases are 2.6.0-2.6.3 and 2.8.0-2.8.2; other 2.x builds, including nightlies, are allowed with a notice. The mod recognises each version's savestate format and keeps savestates in a format it can read for each session. 2.8.0 and 2.8.2 were played with the mod; the other releases were checked against PCSX2's source code.
- Both the BT3 and BT4 adapters include these changes.

# 0.1.0-beta.15

- Fix a circular cinematic pause when an ultimate overlaps another fighter's special or transformation. Live native activations can finish their own pause instead of freezing one another until the emergency timeout.
- Preserve the selected ultimate camera, native impact/resource holds, and the existing timeout safeguard. Idle, defeated and unrelated fighters are not exempted from the shared pause.
- Safely upgrade previously prepared matches, including three/four-player split screen, with strict executable validation.
- Include the correction in both BT3 and BT4, retaining all beta.14 loading and performance improvements.

# 0.1.0-beta.14

- Shorter loading before a match. The new Mod Settings > Presentation > Fast disc loading option is on by default. It shortens the emulated disc delays; a 5v5 load measured about 7 s faster. The change takes effect at the next launch. Turning it off uses normal disc timing, and the emulator's own value is restored when the game closes.
- Add Mod Settings > Presentation > Emulated PS2 CPU speed (Default, 130, 180 or 300%). A higher speed keeps four-player split screen at 30 fps more often, but it needs a faster PC. Default leaves PCSX2's own setting unchanged.
- New installations run the PS2 vector unit on its own thread (MTVU), as every tested setup did. The beta.13 installer already did this, but its notes did not say so.
- Fighter loading reads each queued file in fewer frames, and preparation copies less emulator memory. On a 5v5 that is about 1.5-3 s less, depending on the number of files.
- A rematch with unchanged settings reuses the prepared save state instead of rebuilding it, which is about 1.4 s faster.
- Four-player split screen spends less emulated CPU time each frame on the draw-list reset, teammate lookups, the revive command scan and the cinematic checks. With four views and ten fighters that is about 5% of each frame. Game behaviour is unchanged.
- The body-swap and extra-transformation cleanup now waits by emulated time instead of by loop count, so it stays correct when the CPU speed is raised.
- Both the BT3 and BT4 adapters include these changes.

# 0.1.0-beta.13

- Confirm BT4 includes BT3's shared CPU behavior and targeting: damage memory, distance/opportunity scoring, target commitment, reduced crowding, and team-aware opponent selection. These runtime changes were already present in beta.12.
- Installer builds now reject differences in the shared CPU policies or their final gameplay installation, even when recording a new BT4 port receipt.
- Validate BT4 CPU transformation rules using its scanned roster and giant classifications, including character IDs beyond the original BT3 roster.

# 0.1.0-beta.12

- Show player/CPU ownership badges above character-selection slots in every modded mode, including one- through four-player Free-for-All, in BT3 and BT4.
- Free-for-All badges follow the actual selection order for unequal rosters. They ignore stale team assignments and avoid duplicating player numbers across unfinished columns.
- Keep the existing Controls toggle for slot labels; native character selection and controller ownership are unchanged.

# 0.1.0-beta.11

- BT4: allow declared-empty collision entries without invalid private collision pointers, including fresh extras, form reloads, and resident body exchanges.
- BT4: keep the same costume appearance when a damaged model file is empty; preserve the logical damage state through staging and commit.
- BT4: route the two missing split-screen map files (53/54) to their same-arena normal geometry in both initial and destruction loaders.
- Inventory truly empty stage slots separately from playable-map failures. Original ISO files are unchanged.
- All 1,558 BT4 costume variants passed the runtime resource parser. Gameplay validation remains separate.

# Tag Team Mod 0.1.0-beta.10

- Keep character-selection control with the player whose pick is pending,
  even when browsing another player's occupied slot. Advance control only
  when the accepted roster changes, with held-button protection at handoffs.
- Add Controls > Allow all controllers during character selection, in English
  and Spanish. Any of the four controllers may operate the shared selector;
  conflicting inputs are not combined. Player/team assignments stay unchanged.
  This setting is off by default and applies to modded character selection.
- Audit all fighter special-effect slots, transformation destinations, costumes,
  normal/split stages and destruction destinations. Declared empty effect slots
  are supported; malformed nonempty slots still fail. Stage transitions also
  validate the destination's effects and propagate missing resources.
- Includes both BT3 and BT4 runtime changes and the latest launcher startup
  error logging/retry improvements. ISO audits describe structural compatibility
  separately from gameplay verification and retain known BT4 costume/stage gaps
  in the generated compatibility report.

# Tag Team Mod 0.1.0-beta.9

- Fix BT4 setup failing with "Missing own special resource" for Top (Destroyer)
  and other fighters whose combat bundle deliberately has an empty effect slot.
  Respect the native empty-slot path for leaders and extras, while continuing
  to reject missing resources for nonempty slots and invalid pointers.
- Both adapters include the resource check, and failures now identify the
  fighter, character, slot and pointer to make genuine problems diagnosable.

# Tag Team Mod 0.1.0-beta.8

- Align split-screen portraits, health layers, pips and blast-stock gauges with
  the game's original HUD frame. Preserve fractional coordinates through drawing
  so scaled ki bars have consistent widths and spacing. Restore the two-player
  HUD size and move the inner panels closer to the timer while leaving a gap.
- Keep the shared fusion camera through the final fusion pose, including when
  Player 2 initiates fusion as an extra fighter.
- Play a power-down animation before timed defusion, restore each player's
  camera before controls resume, and place the partners apart using terrain
  checks. The new animation can be disabled in Mod Settings; it is on by default.
- Both BT3 and BT4 adapters include these changes. Existing installation
  preferences are retained, including language selection during setup and
  diagnostic dumps being off by default.

# Tag Team Mod 0.1.0-beta.7

- Fix a match freezing during an ultimate when "Shared ultimate camera and pause
  everyone" is on. The mod paused every fighter outside the ultimate, including
  the fighter it was aimed at, so the move could never finish and the pause
  never ended. A shared pause is now released after 900 updates, the same
  presentation cannot pause anyone again, and a battle that keeps producing
  such pauses stops pausing for the rest of that match. The camera is released
  with the fighters. The same limit covers the shared transformation and rush
  camera pauses. Both adapters include the fix.
- The launcher window now reports when a cinematic pause had to be released,
  with how long it lasted, so the move that caused it can be reported.

# Tag Team Mod 0.1.0-beta.6

- Fix a launch stopping with "Could not prepare the isolated display settings"
  and "Duplicate graphics setting". A PCSX2 profile can hold the same key
  twice, so the emulator's own on-screen-display value could sit beside the
  temporary one setup applies, and every later launch refused to start. Setup
  now keeps one entry per key, restores the emulator's own value afterwards,
  and reads profiles whose lines end in doubled carriage returns. An affected
  profile repairs itself on the next launch. Both adapters include the fix.

# Tag Team Mod 0.1.0-beta.5

- Fix backing out of character selection stopping the trainer with "Native
  animated label nodes changed". A ready menu may still be constructing its
  first highlighted label. Both adapters accept that valid animation state
  while retaining row, node-slot, texture and ownership validation.
- Returning from a modded selector can rearm its remembered mode menu normally.
  PCSX2 2.8.0 and 2.8.2 remain supported.

# Tag Team Mod 0.1.0-beta.4

- Support PCSX2 2.8.2 in setup and both runtime adapters; retain 2.8.0 support.
- Fix first-launch menu failure on fresh saves. The native Shenron menu entry
  only exists when all seven Dragon Balls are collected; both native layouts
  are now recognized without weakening asset or executable validation.

# Tag Team Mod 0.1.0-beta.3

- Keep the original loading minigame visible until arena initialization. The
  mod prepares its pictures silently during native loading, then shows its
  mode-specific screen at the transition into the map.
- In every one-player modded mode, hide the mod's overhead bar for the player.
  This follows teammate takeovers; other fighter bars and the native HUD retain
  their existing behavior. Multiplayer and CPU-only matches are unchanged.
- Both changes are included in BT3 and BT4. Installation defaults are unchanged.

# Tag Team Mod 0.1.0-beta.2

- Simplified download: open Install.cmd; support files are grouped under setup.
- BT3 and BT4 share the reviewed installation preferences: L3 tap targeting,
  revival enabled (3 stocks / 3 seconds), shared ultimate/transformation cameras,
  an 80-second Fusion Dance limit, and 121% top-row HUD scale. Language remains
  an installer choice. Large maps, giants and diagnostic dumps remain off.
- Removed lore-timer settings; timed fusions are limited to Fusion Dance.
- The mode-specific loading cover starts during native disc loading, before
  the battle object and arena intro camera are initialized. Real-match timing
  still needs visual confirmation.
- Carried the PINE connection/write optimizations, loading-picture pre-rendering,
  texture quantization cache and menu-scratch cleanup to both adapters.
- Included the revised Spanish strings, installer messages and complete guide.
- Retained BT4-specific metadata loading, roster ranges and legacy-hook cleanup.

# Tag Team Mod 0.1.0-beta.1

First packaged public beta for Windows x64. One installer selects BT3 USA or
BT4 B14 REV2 English from the ISO's verified executable and resource layout.
BT4 is experimental; see the compatibility report and limitations in README.md.

- English / Español selection in setup and Mod Settings; translated mod menus,
  settings, loading artwork and gameplay prompts in both adapters. Spanish guide
  included. Game names, dialogue and technical logs retain their source language.

- Simultaneous team fights, free-for-all and modded training; one through four
  human players, team assignment, split-screen, target switching and settings.
- Shared latest HUD sizing and sharpness, compact three/four-view fusion and
  score overlays, faster main-menu activation and fusion-camera routing fixes.
- Mode-specific loading artwork is included for both game adapters.
- Optional revival, spectator takeover, fusion controls/timers, expanded maps
  and larger giants. Experimental features remain opt-in in new installations.
- Verified dependency wheels are bundled. Checksums cover the installer and
  its payload; setup uses a private Python environment and emulator profile.
- Startup authenticates the actual Python worker through a unique launch token,
  including Windows virtual-environment redirectors, and tracks it for cleanup.
- Existing ISOs, BIOS files, emulator profiles, memory cards and saves are not
  overwritten. Play.cmd appears only when setup checks finish successfully.
- Check installation.cmd checks files, dependencies, ISO identity and settings
  without opening an emulator. Setup and check errors produce local reports.
- Diagnostic dumps/history are off by default. Generated sessions are retained
  in bounded batches; trainer-owned checkpoint references are protected.

This release packages the current gameplay build. It does not claim every
character, costume, effect, fusion and stage combination has been playtested.
