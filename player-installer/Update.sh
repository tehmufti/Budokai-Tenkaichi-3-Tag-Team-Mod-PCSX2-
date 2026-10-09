#!/bin/sh
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
installation=${1:-}
if [ -z "$installation" ]; then
  if command -v zenity >/dev/null 2>&1; then
    installation=$(zenity --file-selection --directory --title='Choose your installed Tag Team Mod folder') || exit 1
  elif command -v kdialog >/dev/null 2>&1; then
    installation=$(kdialog --getexistingdirectory . --title 'Choose your installed Tag Team Mod folder') || exit 1
  else
    printf 'Installed Tag Team Mod folder / Carpeta donde instalaste el mod: '
    IFS= read -r installation || exit 1
  fi
else
  shift
fi
python="$installation/.venv/bin/python"
if [ ! -x "$python" ] || [ ! -f "$here/setup/update_player.py" ]; then
  printf '%s\n' 'Choose the installed mod folder containing Play.sh; extract the entire updater first.' >&2
  exit 2
fi
PYTHONUTF8=1 PYTHONNOUSERSITE=1 PYTHONPATH= PYTHONHOME= "$python" -B "$here/setup/update_player.py" "$installation" "$@"
