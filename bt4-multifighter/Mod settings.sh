#!/bin/sh
# Developer tree on Linux: open Mod Settings (errors are shown in a dialog when no terminal is open).
# Player installations get their own generated "Mod settings.sh". Run: sh "Mod settings.sh"
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
python="$here/../.venv/bin/python"
[ -x "$python" ] || python=python3
export PYTHONNOUSERSITE=1
# The runtime28 profile, like Play.sh (the dev tree has no player-install.json to select it).
export BT3_RUNTIME_PROFILE="${BT3_RUNTIME_PROFILE:-runtime28}"
exec "$python" "$here/tools/play_launcher.py" settings "$@"
