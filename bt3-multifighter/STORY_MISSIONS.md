# Story missions and cinematic battle creator

Version 9 includes the scenario runtime and three curated battles in both BT3
and BT4. The player installer includes those three examples only. Workbench
authoring tools remain in the developer source distribution.

Open **BT3 Workbench.cmd → Story missions**. Missions are independent, versioned
JSON documents under `missions/`. They contain roster IDs, costumes, an optional
arena, CPU profiles, conditions and ordered actions. They contain no savestate,
RAM image, executable script, BIOS or game assets.

## Play a mission

1. Launch the game with **Play (any teams)** / **Play** and open Modded Modes
   with Select (or your configured menu button).
2. Choose **Modded Scenarios**. Browse saved missions with Up/Down; L1/R1
   move by a page. Cross opens the selected mission's roster preview.
3. Choose **1 Player** or **CPU Only** with Left/Right, then press Cross.
   The game creates a fresh battle and selects every preset fighter, form and
   costume automatically, including the reserves. Workbench can stay closed.
4. If the mission specifies an arena, it is selected automatically. Otherwise
   choose an arena from the normal stage selector. The mission's optional music
   ID is selected from this disc's native song list; leaving it unset selects
   the game's Random entry (or an available song if that disc has no Random).

All JSON documents under `missions/` appear in this browser (except the private
next-battle queue). The developer library also retains the imported Mission 100
rosters; these are not bundled in player installations. Only missions authored
for the current game's family can run.
Invalid files remain visible with an explanation and cannot be launched.
Triangle returns to the list or the modded menu. Returning from a scenario to
Modded Modes reopens the browser.

### Test this mission (quick launch)

In **BT3 Workbench → Story missions**, **Test this mission** saves the open
mission (when it has a file; a loaded preset is only validated), validates it
and starts this folder's ordinary **Play (any teams)** launcher (BT4: **Play
BT4 (any teams)**) in its own window. Press Start at the title screen: when
the main menu appears, Modded Modes opens by itself and the mission starts
exactly as if you had chosen it in Modded Scenarios (1 Player). If the game
is already running, the mission starts the next time the main menu is shown.
The request is a checksummed copy in `missions/quick-launch.json`; it is used
once and expires after 15 minutes, so a forgotten test never takes over a
later session. No emulator state is loaded and no controller input is sent.

Use **BT3 Workbench → Story missions** to create or edit these documents. The
**Event flow** tab displays a node for each trigger and its ordered actions.
Double-click a trigger or action to edit it; select an event and choose **Add
follow-up** to create a dependent branch. In the event dialog, actions can be
edited, removed or moved up/down without writing JSON. Separate trigger branches
may run independently: their screen placement does not force a time order.
Use **Replace condition**, **Add AND**, **Add OR**, or **Invert condition** to
build branches without writing JSON. Actions can also be duplicated. Fighter
and event renames update their references, including inverted conditions.
Ctrl+mouse-wheel zooms the graph; Fit and 100% restore useful views. Runtime
telemetry colors the current action and completed/failed nodes when enabled.

In a Cinematic or Voice action, **Preview / choose voice line** opens the actual
selected ISO's dialogue bank. Pick a character and bank, then double-click a
line or press Play. The list shows native line IDs and durations. Playback
volume and Stop are available; Use this line copies the character, ID and
volume into the action. A cinematic's voice starts with its animation. A
separate Voice action plays when that step is reached. Primary/alternate bank
labels are intentional: the disc determines the languages, and the in-match
game language setting chooses which bank plays. PCM stays in memory; no audio
extraction cache, emulator or external decoder installation is required.

For a second wind, allow enough event timeout for the KO fall/get-up to finish
(30 seconds is the default). One second can expire before recovery even starts.
Use **Recover at 1% → Cinematic with voice → Heal at 100% → Transform** to show a
wounded pose before the full heal. The fighter is protected while its recovery
event runs. Transformation targets must belong to the current fighter's native
form routes: for example, Goku (Mid) uses form 2, not Goku (End)'s form 4.

The older **Use for next battle** workflow also remains available for manually
selected multiplayer rosters. In that workflow the selected roster, forms,
costumes and optional arena must match the mission, and reserves must be CPUs.
Both routes store a checksummed copy of the definition, cleared after successful
preparation. They do not save an emulator state as the mission format.

For live diagnostics, enable **Runtime → Follow trainer** in Workbench. The
Story missions tab then shows the combat clock and each event's waiting,
running, complete or failed state. A failed event also displays a brief game
notice. Event execution itself does not depend on Workbench being open.

## Events

Conditions include elapsed combat time, a fighter's defeat, their first form
change, being in a specified form, an upper/lower HP threshold, another completed
or failed event, and a fighter being active or having exited the scene.
**Delay after that event** measures from its completion, rather than its start.
An event can release its protection and continue on failure, or fail the scenario;
an **Event failed** branch can provide an alternate sequence.
**Planet / arena destruction completed** fires after the game's destruction
sequence finishes and combat can resume. It can launch reinforcements, dialogue,
cinematics or other actions, and can also be used in win/fail conditions. Choose
the destruction occurrence (1 by default); each event still runs once. The JSON
condition is `{"type":"planet_destroyed","occurrence":1}`. Starting a battle
on an already destroyed arena, normal map loading and breaking individual
objects do not count. The Workbench's live scenario status includes the count
and the destination arena of the last completed destruction.
The JSON format supports nested `all`, `any`, and `not` groups, editable through
the condition controls. Times stop while paused, while the preparation loading
screen is up, during the opening intro and when the game's cinematic stop or an
authored shot is active: combat time 0 is "Fight!", and a delay never fires
inside a shot.

Actions execute in order:

- **Enter:** admit a preloaded reserve at a safe formation position using the
  current arena's native spawn/terrain routines, including destruction maps.
  The generic entrance uses the native get-up followed by a taunt pose/voice.
  Set `intro` to false to omit the taunt.
- **Recover:** restore a defeated fighter's configured HP percentage, play the
  native get-up, and protect them from attacks and control during recovery.
  Current human/CPU ownership is preserved, including a prior CPU takeover.
- **Transform:** request a real ordinary form through native commands and the
  existing resource loader. It waits for that body to finish replacing the old
  one. This is not an arbitrary character replacement or fusion command.
- **Heal:** set a living fighter's HP to the requested percentage.
- **Taunt:** wait for a normal action window and play the native taunt.
- **Message:** display a short story cue in each viewport for a chosen duration.
  (Story text display is being redesigned; the three examples use none.)
- **Wait:** delay the next action while combat continues. Enable Freeze to hold
  the preceding cinematic camera and freeze fighters for up to 30 seconds.
  Ordinary waits count toward the event timeout; frozen shots do not.
- **Set stats:** change any selected HP, current-health percentage, damage,
  defense, invulnerability, nonlethal protection, ki, blast-stock or CPU
  difficulty value. Omitted values retain their current setting. Larger defense
  multipliers reduce incoming damage. Changing maximum HP alone does not refill
  health; also set Current HP to 100% for a fresh phase.
- **Take control:** move a numbered human controller to an active living fighter
  at a safe action window. It cannot steal another human's body. In the browser's
  CPU Only mode this step is skipped successfully and the entrant remains a CPU.
- **Target:** set a fighter's opponent explicitly, useful after a phase change.
- **Despawn:** retire a fighter from the scene without a fake KO or kill credit.
  Transfer its human controller first. Native actor storage remains allocated;
  the fighter is hidden and cannot fight or prevent the scripted result.
- **Defeat:** queue the game's real KO action, for an authored sacrifice or
  other story event. It can trigger subsequent Defeated conditions.

For a second wind, use **defeated → Recover → Transform → Message**. The native
transformation follows the mod's current cinematic settings. It is not a new
authored camera sequence. Events are one-shot. Each event has an adjustable
timeout, and a failed event releases its locks and invulnerability. Pending
reinforcements/recoveries defer a team's defeat for the configurable
**Reinforcement grace** period (default 30 combat seconds); they cannot strand
an unwinnable match indefinitely.

## CPU controls

Each fighter can have a CPU transformation likelihood slider. This accepts
0–100% of ordinary native AI attempts; it does not force a form that the AI
never requests. Existing global restrictions still apply. Scripted Transform
actions bypass the random preference, while native form/resource admission
checks still apply.

Select a destination fighter and choose **Copy CPU settings…** to name another
mission CPU as the source. At match setup it copies that source's configured
difficulty/behavior words and rebuilds the destination's native decision
cache. The destination retains its own moves, body, animation and AI resource
dataset. Its mission probability profile is copied independently. Both slots
must be CPUs; this button does not copy a human player's settings.

## Mission 100

The BT3 tree's `missions/Mission 100/` contains all 100 original USA BT3 enemy rosters and names,
extracted from the user's disc, with their original costumes. The original mode
lets the player choose allies, so Goku in the player slot is an editable
placeholder, not a claim about the original player roster.

Load a preset, choose your allies, and save a custom copy. **Make enemy waves**
turns an event-free preset into sequential opponents: each reserve enters after
the previous opponent is defeated. Leave them active from the start for a
simultaneous battle, or author your own time/form/defeat events.

Original native stage/restriction/Potara records are retained as provenance but
are **not yet interpreted or enforced**. These are enemy-roster presets, not
certified reproductions of every original rule or 100 authored story scripts.
No invented dialogue is presented as original game dialogue. The import tool
requires the original USA ISO and reads only those tables.

## Cinematics, voices and battle rules

In **Story missions → Events**, add **Cinematic** to an event's ordered actions.
Choose the fighter who appears, an independent animation donor, and a clip.
**Preview / choose animation** opens the existing green-grid model viewer with
the recipient's model and the donor's animation. Clip 384 is the generic intro
on the tested BT3 characters. Other clips can be inspected before choosing them.
Set duration, animation speed, and the camera's start/end eye and look-at offsets.
Disable **Play an animation** for a camera-only shot that preserves the current
pose. Pan interpolation can be smooth, linear, ease-in or ease-out. Freeze waits
after a shot provide breathing room before the next action or phase.
Enable **Reset living fighters to the stage formation before this shot** to
re-establish positions and facing before a scene. This uses the current stage's
terrain and formation placement, including expanded maps. It waits for bound
attacks or reloads to finish, clears ordinary motion, and leaves corpses,
retired fighters and unused reserves alone. The three examples use this at
their opening and major phase changes.
Coordinates are world-axis offsets around the fighter; negative Y points up.
A cinematic with an animation waits for a safe idle window; a camera-only shot
(and a frozen wait) starts at once and freezes everyone in their live pose. A
shot holds combat, hides status panels, plays its pose, and restores the
previous camera and animation afterward. An event owns each fighter it uses
until it ends; run cast changes in parallel only with an event that uses other
fighters. When a story ends, a team's original leader that the story retired is
shown again for the native result pose (the result presents original leaders).
Animation assets and camera paths are prepared before battle, with no ISO reads
during the shot. Borrowed root travel is removed so the fighter stays at its mark.

For an entrance, add **Enter** with its default taunt disabled, then **Cinematic**
for that reserve. It first completes the protected native get-up, then plays the
authored shot. For a second wind, use **Recover → Transform → Cinematic**. Events
may combine several shots to focus different characters in order.

Enable **Play a voice line with this shot**, or add a separate **Voice** action.
The voice character is independent of both the body and the animation donor.
Line IDs are the disc's native character-bank indices, 0–99; the game's chosen
voice language is retained. Not every character has an audible line at every
index. A scripted voice takes its side's dialogue stream; two simultaneous
same-side voice cues can replace one another. These are skeletal animation
shots, not copies of a donor's weapons, particle effects or complete move scripts.

**Edit fighter** now includes HP (10,000 per bar), native CPU difficulty, ordinary
transformation permission, allowed destination form IDs and a transformation
count limit. Scripted Transform actions deliberately bypass the ordinary policy.
CPU copying copies configuration/difficulty while retaining the recipient's
own moves, model and AI resource data.

**Rules / outcomes** supports combined AND/OR win and fail conditions. An authored
win condition prevents an early enemy-team KO from winning before the condition
is met. Native player-team defeat still loses. If win and fail become true on
the same update, failure wins. A required finishing rule selects a victim,
attacker, attack category (any, special, ultimate), and optionally the attacker's
form at impact. Each rule offers both wrong-finisher behaviors:

- **Leave at 1 HP:** other damage is nonlethal until the requirement is met.
- **Fail scenario:** a wrong *fatal* hit loses the scenario; ordinary nonfatal
  hits remain permitted.

The native pause/results menus omit character selection by default for preset
scenarios. Rules can explicitly allow it, or disable Retry; Main Menu remains.
Per-fighter **Starting stat overrides** expose the same settings as Set stats.
They can make a boss unbeatable at first, then rebalance it when help arrives.
CPU setting copies use the source's effective difficulty, including its override,
while retaining the recipient's unrelated stat overrides.

## Three show-based battles

These are paced, playable adaptations of particular fights, rather than exact
reproductions of every episode. Dialogue uses the disc's real voice banks, with
no invented audio. Manual transformations are disabled in all three; the Cell
story has one explicitly scripted SS2 transformation. The scenes show no
on-screen text: story text display is being redesigned, so the examples use
camera shots, voices and pacing only (the Message action itself remains).
Each scene starts after the game's own intros and "Fight!", opens with the
villain's line, and hands control over with the camera on the opponent while
the departing allies leave off screen.

**Namek â€” Piccolo Arrives.** Start as Kid Gohan in Namek armor alongside Krillin
in Namek armor and Vegeta (Scouter) in his shoulderless Namek outfit. Second-form
Frieza (150,000 HP, 1.6Ã— damage, 6Ã— defense, nonlethal protection) cannot be
beaten yet: hold out for 40 seconds of combat. Piccolo End lands with a voiced
push-in shot; Player 1 moves to him while the camera cuts to Frieza, and
Gohan/Krillin/Vegeta withdraw off camera. The duel is Piccolo's 45,000 HP
(1.3Ã— damage, 1.2Ã— defense) against Frieza's 45,000 HP at normal damage and
difficulty 3. Defeat Frieza to win. Losing Gohan before Piccolo lands, or
Piccolo afterwards, fails. Piccolo End is the playable stand-in for Nail-fused
Piccolo; victory ends this adaptation before Frieza's third form.
[Official second-form Frieza/Piccolo account](https://en.dragon-ball-official.com/news/01_1819.html),
[Krillin's Namek armor](https://en.dragon-ball-official.com/news/01_991.html).

**Saiyan Invasion â€” Goku Arrives.** Gohan, Krillin and Piccolo face an
untouchable Nappa. After 25 seconds, once Gohan is below half health (at the
latest after 35 seconds), the camera holds on Nappa as Piccolo cries out, then
on Gohan as Piccolo falls. About eight seconds later Goku lands; Player 1 moves to him while the camera is on Nappa
and the others withdraw. Defeat a rebalanced Nappa (36,000 HP, difficulty 2);
Vegeta then steps in with his own intro and a cut to Goku, and Nappa's body
leaves during that shot. Defeating Vegeta wins; losing Gohan before Goku lands,
or Goku afterwards, fails. This condenses the battle and omits the Kaioken and
Great Ape phases.
[Official Nappa battle account](https://en.dragon-ball-official.com/news/01_759.html).

**Cell Games â€” Gohan Awakens.** SS1 Teen Gohan cannot hurt Perfect Cell yet.
After 35 seconds of combat Android 16 lands with a voiced shot and Cell turns
on him (drawing Cell away from Gohan); the camera cuts to Cell and Android 16
falls. A high shot holds on Gohan as he cries
out while Android 16's body leaves, then the scripted SS2 transformation (the game's own
transformation scene) and SS2 Gohan's intro follow.
Gohan is restored to 50,000 HP with stronger damage/defense; Cell becomes a
fairer 65,000-HP opponent. Only an ultimate from SS2 Gohan can finish Cell;
other damage leaves him at 1 HP. Cell's self-destruction and return are omitted.
[Official Android 16/Gohan account](https://en.dragon-ball-official.com/news/01_839.html).

Authoring notes from the live pass (October 6, evening): camera offsets are
world axes around the fighter, so frame a shot from the side the fighter faces
(teams start facing each other) and keep the eye within about 30 units, or it
can end up inside hills. The combat clock stops during shots, so a delay never
fires inside one; an event owns every fighter it touches until it ends, so a
parallel event must use different fighters (for example the allies' exits
during the opponent's reaction shot). A shot of a player-side extra that no
player is viewing rendered an empty frame (fresh entrants in particular), so
Player 1 moves to Piccolo/Goku before their entrance shot, and holds Android 16
only for his shot before returning to Gohan. In CPU Only mode no player moves,
so those entrance shots can still show an empty frame.
Entrances are camera-only push-ins with the entrant's voice; Vegeta's and SS2
Gohan's borrowed intro clips are used and render correctly. Mid-fight reaction shots use a high
three-quarter angle: a fighter's live facing is unknown, and a low front camera
was blocked by the fighter standing in front of the subject.

Old examples, including the custom Example2, are preserved outside the browser
in `analysis/oct06-scenarios/retired-examples/`, with a hash receipt. The 100
Mission 100 roster presets remain available in the developer library only.

## Current limits and validation

- The BT3 and BT4 development runtimes both include the mission system. Their
  character-ID families are checked; a BT3 preset cannot silently run with BT4
  IDs. Converting Mission 100 to BT4 needs a verified character mapping.
- The in-game browser constructs fresh character/stage screens and publishes
  the authored roster into native records. The manual Workbench queue remains
  an advanced route: select matching fighters, arena and music yourself.
- Current runtime capacity is five selected fighters per side; the document
  format allows larger rosters for future adapters. Native slot 1 on each side
  must start active. Later entrances use CPU extras. Sequential 1v1 is supported
  within that preloaded roster.
- Custom donor animations, held camera shots and independent voices are
  supported. Entirely new fighters are not streamed mid-match: reserves and
  cinematic resources are preloaded. Different skeleton proportions can make
  some borrowed poses look odd; preview them on the recipient. A skeletal clip
  can depend on native move effects that are intentionally absent from a shot.
- A shot is at most 30 seconds, with a bounded 344 KiB shared animation/camera
  arena. Reusing clips saves space. Oversized programs fail validation rather
  than overwrite another runtime feature. Dead fighters need Recover before a
  cinematic; a native rush, form reload or other unsafe state delays its start.
- Documents, references, dependencies, byte size, code space and prepared-world
  identity are checked. Native form availability is checked when its event
  runs; an unsupported form fails visibly instead of rewriting a model pointer.
- Mission elapsed time and event completion live alongside the simulated world.
  Existing rematch/reset behavior therefore resets the story consistently. The
  mod's existing rematch implementation may use an emulator checkpoint; **a
  mission definition does not** and starts through fresh match preparation.

Offline guest-code tests exercise native get-up/spawn, pause/results selection,
damage attribution, both finishing outcomes, form restrictions, camera handoff,
timeouts, ownership, CPU copies and one-shot timing. Qt tests cover the creator;
the donor-model preview loader was checked against the original ISO. A separate
live BT3 test verified Trunks's intro on Goku, status-HUD suppression, camera
framing and return to combat. BT4 has matching scenario tests and resource checks;
European BT3 has compilation/menu/asset checks. These are **not certification of
every character, clip or multiplayer scene**. The October 6 tests additionally
execute the complete event/control/result chains of all three examples and
build their full preparation plans against both user-owned ISOs. The selected
costumes, clip durations, voice headers and native stage resources validate
offline. BT4 preview decoding also handles its edited mesh packages and reports
repairs/unsupported animation channels. On the evening of October 6 all three
examples were played live on the USA BT3 disc in CPU Only mode (hidden-desktop
rig, quick launch), and the reworked versions again; the Player 1 handoffs were
checked with the Workbench's Test this mission button. They remain marked
`gameplay_tested=false` until the user's own playtest; human difficulty in
particular is a first estimate. Version 9 installs the runtime and these three examples. On October 8, the
Namek single-player replay verified the new formation resets, Piccolo entrance,
control handoff, ally withdrawal and return to combat. The other two scenes
retain guest-code event-chain and resource validation; visual tuning is ongoing.

## Developer continuation

- Data/validation: `tools/story_missions.py`.
- Guest event compiler: `tools/story_runtime.py`, reservation
  `0x06BE0000..0x06C00000`, between fusion records and quad-view storage.
- Safe human handoff and cast retirement: `tools/story_cast.py`, within the
  story rules reservation. Retirement is distinct from KO and reserve admission.
- Native menu clones: `tools/story_menus.py`, `0x06970000..0x06978000`.
- Finisher/form/outcome rules: `tools/story_rules.py`, `0x06990000..0x069A0000`.
- Preloaded shots/voice: `tools/story_cinematics.py`, `0x069A0000..0x06A00000`;
  held updates are serviced by `native_preparation`, not host polling.
- Native creator: `tools/story_editor.py`, mounted by `modder_gui.py`.
- Original roster importer: `tools/mission100.py`.
- Integration: `autopilot.py` admits armed singleton team matches;
  `fresh_team_trainer.py` preflights selection and installs the guest program;
  `trainer_bridge.py` exposes read-only status when Workbench telemetry is on.
- `npc_transform_policy.build_memory(force=True)` installs the preference hook
  for scripted forms even if ordinary global settings would need no patch.
- Test modules: `test_story_missions.py` and `test_story_editor.py`.

The held renderer/HUD gained scenario gates; native camera records are saved
and restored without replacing ordinary zoom/lock-on behavior. Before a public
build, review the new runtime closure/BT4 port receipt,
run live mission/rematch tests, and decide how to distribute the creator and
mission library (the existing player package excludes modder tools).
