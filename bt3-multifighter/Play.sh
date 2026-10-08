#!/bin/sh
# Developer tree on Linux: start the modded game with the runtime28 profile (runtime28/pcsx2-qt.AppImage,
# PCSX2's data in runtime28/PCSX2). Player installations get their own generated Play.sh. Run: sh Play.sh
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
python="$here/../.venv/bin/python"
[ -x "$python" ] || python=python3
trap : INT  # Ctrl+C stops the launcher (it cleans up); this script survives it to reach the pause
PYTHONNOUSERSITE=1 "$python" -u "$here/tools/play_launcher.py" play --runtime-profile runtime28 "$@"
rc=$?
if [ "$rc" -ne 0 ] && [ -t 0 ]; then printf 'Press Enter to close. '; read -r _; fi
exit "$rc"
