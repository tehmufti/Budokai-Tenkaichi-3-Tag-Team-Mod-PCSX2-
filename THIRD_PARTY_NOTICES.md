# Third-party licenses and attribution

The project's own code is GPL-3.0-only. The following components retain their
upstream licenses; GPL does not replace their notices.

- **Liberation Sans 2.1.5:** SIL Open Font License 1.1. The fonts and license
  are under each runtime's `tools/vendor/fonts/`.
- **SDL GameControllerDB:** zlib license, retained beside
  `tools/vendor/game_controller_db.txt`. Upstream:
  <https://github.com/mdqinc/SDL_GameControllerDB>.
- **Walking/running samples:** adapted from Mannequiny v0.4.0 by GDQuest,
  Luciano Munoz and contributors, CC BY 4.0. Full attribution, source links
  and modifications are in `assets/licenses/Mannequiny.txt` in each runtime.
- **SDL2:** downloaded runtime, not checked into this source tree. Its license
  is retained at `tools/vendor/SDL2-LICENSE.txt`. Upstream:
  <https://github.com/libsdl-org/SDL/tree/SDL2>.
- **pycaw:** downloaded Windows audio package, with its license retained inside
  the upstream wheel. Upstream: <https://github.com/AndreMiras/pycaw>.
- **Player Python dependencies:** Pillow, NumPy, pycdlib, pyelftools, zstandard,
  Capstone, comtypes and psutil. Exact versions and hashes are in
  `player-installer/dependencies*.json`. Their upstream license texts are in
  `player-installer/notices/` and `notices-linux/`, including bundled libraries.
- **Optional Workbench dependencies:** PySide6/Qt and PyOpenGL are installed
  separately; their distributions retain their own licenses.

PCSX2, Python, Microsoft runtimes, game images and PS2 BIOS files are not
included in this source repository. The installer uses locally supplied or
upstream-installed components. See `player-installer/THIRD_PARTY_NOTICES.md`
for the player release's distribution notices.

Natural and Fighter motion samples are adapted from the CMU Graphics Lab
Motion Capture Database, using Bruce Hahne's BVH conversion. The data
was obtained from mocap.cs.cmu.edu, created with NSF EIA-0196217 funding.
These animation assets retain their separate CMU terms: incorporation
in projects and commercial products is permitted; resale of the motion
data itself, including converted data, is prohibited. See
each runtime's assets/licenses/CMU-Motion-Capture.txt and CMU-READMEFIRST.txt.
The mod code remains GPL-3.0-only; it does not relicense these assets.
