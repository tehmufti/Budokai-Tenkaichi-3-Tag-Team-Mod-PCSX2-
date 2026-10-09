# Version 11 regression checks

Run both adapters from the repository root:

```sh
python -B release_tools/version11-tests/run.py
```

Each adapter runs in a separate process. No emulator, BIOS, ISO, saved state,
personal settings, or captured RAM is required for the source-only checks.
Generated fusion guards execute in the shared MIPS interpreter; gait checks
verify compressed curves, quaternion normalization, unchanged unrelated clips,
cycle timing, and allocated memory limits.
Tournament cases execute the generated per-fighter ring-out policy, current
roster-row selection, intro guards, and stale-owner rejection.
Online checks execute the desync probe and verify that ring-out elimination
and movement settings affect its gameplay hash, while debug counters do not.

Native-instruction tests are explicitly skipped unless you supply your own
extracted executable. They never substitute fabricated native code.

```sh
python -B release_tools/version11-tests/run.py \
  --bt3-elf /path/to/SLUS_216.78 \
  --bt4-elf /path/to/SLUS_219.78 \
  --bt4-addon /path/to/DBZP.BIN
```

`--game bt3` or `--game bt4` selects one adapter. For BT4, `DBZP.BIN` is also
needed for the native fusion paths; it is found beside the provided executable
unless `--bt4-addon` specifies another location. The tests read these files
without changing or copying them.

The native tests cover admission/consent cancellation, existing fusion
completion, walk/run substitution inside the original clip decoder, root
adaptation after native conversion, and guarded installation/rematch handling.
They also execute the tournament's original ground-contact decisions and
full-team result predicates, including unequal teams and revival exclusion.
These are offline instruction and data checks, not a substitute for gameplay
or visual testing.

The small fixture modules reuse the interpreter and synthetic actor helpers
already present in `release_tools/scenario-validation`. No game assets are
included here.
The online checks also reuse the existing interpreter in
`release_tools/online-hud-tests`. An optional `TAGTEAM_NETPLAY_FIXTURE` can name
your own prepared match for an additional real-state hash check.
