# Bundled fonts

Liberation Sans 2.1.5, Regular and Bold, unmodified. They are the only fonts
the mod draws with outside Windows (tools/fonts.py). Liberation Sans is
metric-compatible with Arial, so text measured for the Windows screens keeps
its width budget. Windows keeps its own system fonts and does not use these
files.

License: SIL Open Font License 1.1, in LICENSE next to this file (copied from
the release archive).

Source: https://github.com/liberationfonts/liberation-fonts/releases/tag/2.1.5
Archive: liberation-fonts-ttf-2.1.5.tar.gz
(https://github.com/liberationfonts/liberation-fonts/files/7261482/liberation-fonts-ttf-2.1.5.tar.gz)

| File | Bytes | SHA-256 |
|---|---|---|
| liberation-fonts-ttf-2.1.5.tar.gz | 2385008 | 7191c669bf38899f73a2094ed00f7b800553364f90e2637010a69c0e268f25d0 |
| LiberationSans-Regular.ttf | 410712 | 76d04c18ea243f426b7de1f3ad208e927008f961dc5945e5aad352d0dfde8ee8 |
| LiberationSans-Bold.ttf | 414456 | 788abee4c806d660e8aee46689dd8540cd4bb98da03dcc9d171ce3efd99a9173 |
| LICENSE | 4414 | 93fed46019c38bbe566b479d22148e2e8a1e85ada614accb0211c37b2c61c19b |

The archive's SHA-512 (b9f178fa...254f943fed) matches the one Alpine Linux
pins for its font-liberation 2.1.5 package.

Visual differences outside Windows:

- Menus, the in-game settings, team assignment, player badges and prompts use
  Liberation Sans with Pillow's basic layout (no kerning), so a line can be up
  to about 4% wider than on Windows. Every screen's width and sprite budget is
  tested with these fonts (test_fonts.py).
- The Ki Storm loading art uses Liberation Sans Bold in place of Bahnschrift
  (condensed) and Segoe UI Black, which are Microsoft fonts that cannot be
  redistributed. Its lettering is wider and lighter than on Windows. The art
  shrinks a run to fit its box as before, and only when that is not enough
  (for example LEGENDARY SUPER SAIYAN in a six-fighter card) compresses it
  horizontally.
- The menu label cache (native_menu_labels.json) holds Windows Arial atlases
  only, so the native menu labels are drawn live on Linux (a fraction of a
  second when the menu is prepared).
