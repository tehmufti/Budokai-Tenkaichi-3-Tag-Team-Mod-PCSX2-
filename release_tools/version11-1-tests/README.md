# Counter and vanish regressions

These cases run native counter acceptance, queued dispatch and melee clashes
alongside the generated guard in the small MIPS interpreter. They require your
own extracted game executable; BT4 also needs its DBZP.BIN. No game code or
saved match is included. Without those inputs the native cases are skipped.

```sh
python release_tools/version11-1-tests/run.py --game bt3 --bt3-elf /path/to/SLUS_216.78
python release_tools/version11-1-tests/run.py --game bt4 --bt4-elf /path/to/SLUS_219.78 --bt4-addon /path/to/DBZP.BIN
```

The cases reproduce stale-target responses, exercise actual counter contacts,
test KO/removal during both melee clashes, and check installation and tamper
guards. Camera appearance and live input still need an emulator playtest.
