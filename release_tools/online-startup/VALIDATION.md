# Version 8 online startup validation

Times below are host Start (the final ready/commit) to the native introduction
advancing on **both** clients, after the participant load barrier. They are not
just lobby UI timestamps. The original introductions are retained.

| Case | Seconds to intro |
| --- | ---: |
| Uncached 3v1, warm engine, no speculative prebuild | 15.906 |
| Changed 3v1 roster, immediate Start | 12.532 |
| Uncached 5v5, warm engine, ten distinct fighters, no speculative prebuild | 17.329 |
| Changed 5v5 roster, immediate Start | 14.065 |
| Rematches | 0.363–0.398 |
| Prepared/downloaded 3v1, capped transfer | 2.515 |
| Prepared/downloaded changed 5v5, capped transfer | 2.145 |

The tests used two isolated Windows clients on one PC, PCSX2 2.8.2, simulated
20 ms latency, 5 ms jitter and 3% gameplay packet loss. The last two cases capped
checkpoint transfer at 1 MB/s; the immediate fresh cases used loopback TCP.
Full fights, rematches and return to the character-selection lobby completed
with zero differing synchronized frames. Portable source tests also pass.
Only QA-owned processes were closed; the final inventory confirmed none remained.

Background preparation is real work, not an altered Ready timer. The first room
warm-up took about 23 seconds. At the 1 MB/s cap, preparation plus checked download
before Start took 51.74 seconds initially (including warm-up) and 33.58 seconds
for the changed 5v5. Ready remains available throughout. Starting before the
cache/download is ready uses the ordinary preparation path.

These measurements do not guarantee a fixed time on every PC or connection.
Fully cold immediate startup is not certified under 20 seconds.
A fresh 20.7 MB checkpoint alone needs about 21 seconds over a 1 MB/s link;
one deliberately unprefetched changed-roster start took 34.157 seconds there.
Lobby prefetch avoids repeating that wait **after** Start. Separate PCs over
real internet connections and Linux gameplay have not been certified by these
tests. The release preserves the prior regional adapters and offline game hooks.
