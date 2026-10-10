# Online equipment and window regressions

Run with Python 3.11 and Tk:

```sh
python -m unittest discover -s release_tools/version11-2-tests -p 'test_*.py'
```

The fixtures are synthetic and require no disc, BIOS or saved match. Equipment
cases cover ownership, budgets, categories, canonical native rows and cache
identity. Window cases resize the real English/Spanish interface, exercise the
equipment picker, and check that telemetry preserves controls, drafts, scroll
position and hub challenge selections. GUI cases skip when no Tk display is
available. Native equipment application and online gameplay require the player's
own supported disc and emulator.
