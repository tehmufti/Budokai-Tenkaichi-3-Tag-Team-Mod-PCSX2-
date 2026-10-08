# Version 9 online startup validation

Timing starts when the host accepts Start after the final Ready vote. The
introduction endpoint is the native introduction advancing on **both** clients
after the participant loading barrier. Controls become available later, after
the complete native introduction; no introduction was skipped to meet the target.

## Earlier qualified Version 9 online baseline

The baseline Windows ZIP was installed through its genuine frontend into a new
directory. Setup created both authenticated neutral selectors from the player's
own verified disc and BIOS. No runtime source overlay, manually primed cache,
prepared roster, speculative match preparation or running builder was present
before the cold-start timer began.

| Case | Seconds to introduction | Seconds to controls |
| --- | ---: | ---: |
| First fresh 3v2, no builder process before Start | 18.841 | 29.139 |
| Fight Again | 0.919 | 11.251 |
| New ten-fighter 5v5, immediate Start | 11.473 | 19.188 |
| Changed battle engine and free-for-all | 10.429 | 18.939 |
| Independent cold 3v2, checkpoint transfer capped at 8.192 MB/s | 18.345 | 27.709 |

These are the slower client times in each case. All five reached advancing
introductions within 20 seconds on the tested PC.

Tests used two independent Windows clients on one PC, PCSX2 2.8.2 and BT3 USA.
Gameplay UDP traffic had simulated 20 ms latency, 5 ms jitter and 3% packet loss.
The four-match suite used local uncapped TCP checkpoint transfers. A separate
cold-start test capped checkpoint transmission at 8,192,000 bytes/second
(8.192 decimal MB/s, 7.8125 MiB/s); it did not reuse a prepared matchup from the
first suite. This is not a real separate-PC internet or Linux performance test.
Regional adapters remain supported, but their full-archive fallback and slower
PCs/connections can take longer. These measurements are not a universal deadline.

## Transfer and cache sizes

| Fresh checkpoint | Native archive bytes | Transferred bytes |
| --- | ---: | ---: |
| 3v2 | 15,618,966 | 6,257,811 |
| 5v5 | 21,621,690 | 6,656,614 |
| Free-for-all engine switch | 12,932,400 | 6,657,039 |
| Independent transfer-capped 3v2 | 15,804,886 | 6,406,277 |

BT3 USA compact transfers reference verified data in the matching local ISO.
The receiver reconstructs the exact authoritative native archive and verifies
its SHA, entry hashes and CRCs. Other supported discs retain full checked
archive transfer. A smaller wire representation does not remove guest resources.

The two setup-generated neutral selectors and authenticated boot hook occupy
19,638,096 bytes, about 20 MB. Setup took approximately 115 seconds to generate
them on this PC, once. Fighters, costumes and stages still load for each fresh
match. Caches remain local and are not shipped with the mod, disc or BIOS.
Cache generation is optional for installation: if it fails, offline Play remains
available and online falls back to normal checked preparation. That fallback
does not support the fast-first-start timing claim.

## Lifecycle and guards

All five matches completed by KO and returned to selection. The full suite
covered results, Fight Again, a changed roster, an engine change and subsequent
selection return. Across both suites, 4,369 synchronized frame comparisons showed
zero differing states or desyncs. No hidden-builder reset failed. All owned
processes and PINE listeners were closed afterward.

Every client passed the owned-process, paused frame-zero, native core, machine
word readback and participant-ready barrier checks. The current native director
and frame state independently confirmed advancing introductions. All 46 online
module hashes matched production, the qualified archive and the installed files
before and after testing. Normal clients retained D3D11, 2x internal resolution
and 1x gameplay speed. Only the hidden builder used FIFO presentation, 1x
resolution and acceleration while preparing resources.

Two problems found in provisional builds were fixed before qualification:
an accelerated confirmation could miss a short input pulse, and suspending an
unfinished private worker could be counted as a frozen introduction on resume.
Confirmation now waits for native acknowledgement with the original deadline and
owned-input cleanup. Parking now requires the worker's ACTIVE status; unfinished
preparation continues normally. Genuine freeze watchdogs are unchanged.

## Installer and source checks

The genuine frontend, full ISO installation check, integrated online detection,
local cache authentication and installed native archive checks all passed.
The 21 focused portable startup suites passed 449 tests with zero failures or
errors. One Windows symbolic-link test was skipped because the test account
lacked symbolic-link privileges.

Both Windows and Linux archives passed full hashes, CRCs and member manifests,
with identical payloads. Linux permissions and neutral owner metadata were
preserved. The 590 protected Version 8 files remained byte-for-byte unchanged,
including guest/gameplay hooks, regional adapters, settings defaults, assets
and bundled dependencies. Scenario development was excluded from that baseline; it is included in the final candidate below.

User settings, controller profiles, memory cards, save states and source media
remained untouched throughout isolated qualification. Public source contains the
approved portable tests and this report, but excludes private test helpers,
session logs, local paths, game images, BIOS files, authentication keys and caches.

Earlier baseline archive SHA-256 values (superseded below):

- Windows: `3a5d5213151211830f5e108148efea8467c01607240d87cdf07fcd267a8d4ebc`
- Linux x86-64: `33ad20439c8f9af571643f7075e70ad87858f9a4faf346d918734ac0858363bc`
- Shared player payload: `e8986de31881cf84689ce776d5839281799b5f7d983f6f9abc9e73de4441cddc`


## Final Version 9 candidate: bots and scenarios

The five timing cases above qualified the online-only Version 9 baseline. After
adding the scenario runtime and correcting the bot-only dialogue gate, the final
archives were installed again through the genuine Windows frontend. A separate
cold 3v2 with all fighters controlled by CPUs and two spectator clients reached
advancing introductions in **19.417 seconds** on the slower client. The builder
was not running before Start, and no roster had been prepared in advance.

Native introductions then lasted **8.69 seconds**, versus approximately 29
seconds in the reported Version 8 bot-only session. Neutral inputs for dropped
seats now retain the host's captured, frame-specific dialogue progress; they no
longer wait for the game's dialogue timeout. No future progress is invented.
The match completed by KO and returned to character selection. There were
**877 synchronized comparisons, zero differences and zero desyncs**. This used
the same PCSX2 2.8.2 / BT3 USA two-client environment and simulated UDP conditions
described above. It is not an independent-PC or Linux gameplay certification.

Only three authored examples are installed per adapter: Namek - Piccolo
Arrives, Saiyan Invasion - Goku Arrives, and Cell Games - Gohan Awakens. The 100
developer presets and retired examples are excluded. Private online preparation
does not inherit an offline scenario queue. Both adapters have full guest-code
event-chain/resource validation; the Namek single-player replay additionally
confirmed Piccolo's entrance, handoff, ally withdrawal and resumed combat in
PCSX2. Formation resets use native stage placement and wait for unsafe actions
to finish. This is flow validation, not a difficulty/balance certification.

The final payload preserves 752 files from the preceding qualified Version 9
baseline. Windows and Linux archives have identical payload members; the full
Windows frontend, ISO check, online integration and cache authentication passed.
The three examples' timing and presentation remain editable. See
[scenario authoring and known limits](../../bt3-multifighter/STORY_MISSIONS.md).

Final archive SHA-256 values:

- Windows: `5e02acfccfff6a38b1cf5d011d49cb16459fd8cb639b84149b97d49cfda5aa38`
- Linux x86-64: `30177975037c775b2743f03693cabc7e26f65efdcba01e52872e68b81ad4cff0`
- Shared payload: `989aee988954b5b9e20d008d84f451dbb3c38ffe5efe9796a0adc2e014cacba4`
