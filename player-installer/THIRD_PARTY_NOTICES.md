# Third-party components

The exact versions, wheel filenames, upstream project links and SHA-256 hashes
are in dependencies.json. The notices directory preserves the upstream license
texts shipped inside those wheels, including their bundled dependencies.
The installed Python packages also retain their original metadata and licenses.

Bundled Python components: Pillow, NumPy, pycdlib, pyelftools, zstandard,
Capstone, comtypes and psutil. These wheels are unmodified.

The player payload includes an unmodified SDL2 runtime with its license at
game/tools/vendor/SDL2-LICENSE.txt and a pycaw wheel with its license inside
the wheel at game/tools/vendor-wheels/pycaw-20251023-py3-none-any.whl.
Upstream projects: https://github.com/libsdl-org/SDL/tree/SDL2 and
https://github.com/AndreMiras/pycaw.

The player payload also includes an unmodified copy of the SDL game controller
database (game_controller_db.txt from the SDL_GameControllerDB project, as
shipped in PCSX2 2.8.2's resources folder) at
game/tools/vendor/game_controller_db.txt, under the zlib licence (see
game/tools/vendor/game_controller_db-LICENSE.txt). The mod's controller reader
uses it only when the installed PCSX2 has no copy of its own. Upstream project:
https://github.com/mdqinc/SDL_GameControllerDB.

The player payload also includes the unmodified Liberation Sans 2.1.5 fonts
(Regular and Bold) at game/tools/vendor/fonts/, with their SIL Open Font
License 1.1 in that folder and in notices/liberation-fonts/LICENSE. They are
used outside Windows only. Upstream project:
https://github.com/liberationfonts/liberation-fonts.

Walking and running motion data is adapted from Mannequiny v0.4.0 by GDQuest,
Luciano Munoz and contributors, under Creative Commons Attribution 4.0
(CC BY 4.0). The modified motion samples are in game/tools/ground_motion.py;
attribution, source links and a description of the changes are in
game/assets/licenses/Mannequiny.txt. No source mannequin model is included.
Source: https://github.com/gdquest-demos/godot-3d-mannequin/releases/tag/v0.4.0
License: https://creativecommons.org/licenses/by/4.0/

PCSX2, Python and the Microsoft Visual C++ runtime are not redistributed in
this ZIP. Setup copies the user's supplied PCSX2 application and preserves its
resources/docs, uses an existing Python installation or installs it via WinGet,
and installs the Microsoft runtime if missing. Their upstream terms apply.

No game ISO, PS2 BIOS, memory card, game save, RAM capture or extracted native
game executable is included. Fighter portraits and native references are
extracted locally from the selected ISO during setup. This is an unofficial
fan modification, not an official Dragon Ball or PCSX2 release.

Natural and Fighter motion samples are adapted from the CMU Graphics Lab
Motion Capture Database, using Bruce Hahne's BVH conversion. The data
was obtained from mocap.cs.cmu.edu, created with NSF EIA-0196217 funding.
These animation assets retain their separate CMU terms: incorporation
in projects and commercial products is permitted; resale of the motion
data itself, including converted data, is prohibited. See
game/assets/licenses/CMU-Motion-Capture.txt and CMU-READMEFIRST.txt.
The mod code remains GPL-3.0-only; it does not relicense these assets.
