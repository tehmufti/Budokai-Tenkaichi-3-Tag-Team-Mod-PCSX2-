#!/bin/sh
# Tag Team Mod setup for Linux x86-64. Run it from the extracted release folder: sh Install.sh
# (sh Install.sh --help lists the options for a headless install). It finds a Python 3.11-3.14 with venv
# (and Tk for the setup dialogs), then runs setup/install_linux.py. Set TAGTEAM_PYTHON to use a
# specific Python, for example one installed with uv: TAGTEAM_PYTHON="$(uv python find 3.12)" sh Install.sh
# Messages printed here come before the language choice, so they are in English, then Spanish.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || exit 1

# --destination, --iso and --pcsx2 make a headless install (the BIOS comes from --bios or PCSX2's settings): no Tk.
need_tk=1; d=; i=; p=
for arg in "$@"; do
  case $arg in
    -h|--help) need_tk=0 ;;
    --destination|--destination=*) d=1 ;;
    --iso|--iso=*) i=1 ;;
    --pcsx2|--pcsx2=*) p=1 ;;
  esac
done
[ -n "$d" ] && [ -n "$i" ] && [ -n "$p" ] && need_tk=0

pause() {
  if [ "$need_tk" = 1 ] && [ -t 0 ]; then printf 'Press Enter to close / Pulsa Intro para cerrar. '; read -r _; fi
}

# Opened from a file manager there is no terminal: the error is also shown in a dialog.
show_error() {
  printf '%s\n' "$1" >&2
  show_dialog "$1"
}

show_dialog() {
  [ -t 2 ] && return 0
  [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || return 0
  if command -v zenity >/dev/null 2>&1 && zenity --error --no-markup --title="Tag Team Mod" --text="$1" >/dev/null 2>&1; then return 0; fi
  if command -v kdialog >/dev/null 2>&1 && kdialog --title "Tag Team Mod" --error "$1" >/dev/null 2>&1; then return 0; fi
  if command -v xmessage >/dev/null 2>&1 && xmessage -center "Tag Team Mod: $1" >/dev/null 2>&1; then return 0; fi
  if command -v notify-send >/dev/null 2>&1; then notify-send "Tag Team Mod" "$1" >/dev/null 2>&1; fi
  return 0
}

rule='=============================================================================='
thin='------------------------------------------------------------------------------'
copy='Copy this block when asking for help. / Copia este bloque si pides ayuda.'

if [ ! -f "$here/setup/install_linux.py" ]; then
  show_error "$rule
[TTM-ZIP-01] SETUP STOPPED / INSTALACION DETENIDA
$thin
WHAT HAPPENED: Install.sh was started without its setup folder.
WHY: Only part of the release archive was extracted, or Install.sh was copied
  out of the Tag Team Mod Installer folder.
HOW TO FIX: Extract the whole linux-x86_64.tar.gz archive, open the extracted
  Tag Team Mod Installer folder and run sh Install.sh there.
Nothing was changed.
$thin
QUE HA PASADO: Install.sh se ha abierto sin su carpeta setup.
POR QUE: Solo se extrajo una parte del archivo, o Install.sh se copio fuera de
  la carpeta Tag Team Mod Installer.
COMO SOLUCIONARLO: Extrae el archivo linux-x86_64.tar.gz completo, abre la
  carpeta Tag Team Mod Installer extraida y ejecuta alli sh Install.sh.
No se ha cambiado nada.
$thin
FILE / ARCHIVO:
  $here/setup/install_linux.py
$copy
$rule"
  pause
  exit 10
fi

case $(uname -m) in
  x86_64|amd64) ;;
  *) show_error "$rule
[TTM-OS-01] SETUP STOPPED / INSTALACION DETENIDA
$thin
WHAT HAPPENED: Tag Team Mod needs a 64-bit Intel/AMD (x86-64) Linux system;
  this one is $(uname -m).
HOW TO FIX: Install on a 64-bit Intel/AMD PC.
Nothing was changed.
$thin
QUE HA PASADO: Tag Team Mod necesita un Linux de 64 bits Intel/AMD (x86-64);
  este es $(uname -m).
COMO SOLUCIONARLO: Instalalo en un PC Intel/AMD de 64 bits.
No se ha cambiado nada.
$thin
$copy
$rule"; pause; exit 20 ;;
esac

# The bundled wheels serve 64-bit CPython 3.11-3.14 (not the free-threaded build); venv needs ensurepip
# (Debian/Ubuntu: python3-venv). The probe prints why a Python cannot be used (also valid for old Pythons).
probe='import sys, struct, platform, sysconfig
if sys.version_info[:2] not in ((3, 11), (3, 12), (3, 13), (3, 14)):
    print("it is Python %d.%d; the bundled packages serve 3.11 to 3.14" % tuple(sys.version_info[:2]))
    sys.exit(1)
if struct.calcsize("P") != 8 or platform.machine().lower() not in ("x86_64", "amd64"):
    print("it is not a 64-bit x86-64 Python")
    sys.exit(1)
if sysconfig.get_config_var("Py_GIL_DISABLED"):
    print("it is a free-threaded build, which the bundled packages do not serve")
    sys.exit(1)
try:
    import venv, ensurepip
    ensurepip.version()
except Exception:
    print("its venv/ensurepip part is missing")
    sys.exit(1)'
python=
rejected=
tagteam_rejected=
first=${TAGTEAM_PYTHON:+yes}
for candidate in ${TAGTEAM_PYTHON:+"$TAGTEAM_PYTHON"} python3.14 python3.13 python3.12 python3.11 python3; do
  label=$candidate
  [ -n "$first" ] && label="TAGTEAM_PYTHON=$candidate"
  from_env=$first; first=
  if ! command -v "$candidate" >/dev/null 2>&1; then
    [ -n "$from_env" ] && { tagteam_rejected="$label: not found"; rejected="$rejected
  $tagteam_rejected"; }
    continue
  fi
  why=$("$candidate" -I -c "$probe" 2>/dev/null) || why=${why:-it does not start}
  if [ -z "$why" ] && [ "$need_tk" = 1 ] && ! "$candidate" -I -c 'import tkinter' >/dev/null 2>&1; then
    why='its Tk part (tkinter), needed for the setup dialogs, is missing'
  fi
  if [ -n "$why" ]; then
    rejected="$rejected
  $label: $why"
    [ -n "$from_env" ] && tagteam_rejected="$label: $why"
    continue
  fi
  python=$candidate
  break
done

if [ -n "$python" ] && [ -n "$tagteam_rejected" ]; then
  echo "Note: $tagteam_rejected. Using $python instead." >&2
fi

if [ -z "$python" ]; then
  message="$rule
[TTM-PY-20] SETUP STOPPED / INSTALACION DETENIDA
$thin
Tag Team Mod setup needs Python 3.11, 3.12, 3.13 or 3.14 (64-bit) with the venv module"
  [ "$need_tk" = 1 ] && message="$message
and Tk for the setup dialogs (or pass --destination, --iso and --pcsx2,
plus --bios when setup does not find the BIOS your PCSX2 uses)."
  [ -n "$rejected" ] && message="$message
Pythons tried that cannot be used:$rejected"
  message="$message
Install the missing packages, then run sh Install.sh again:
  Debian, Ubuntu, Mint, Pop!_OS: sudo apt install python3 python3-venv python3-tk
  Fedora:                        sudo dnf install python3 python3-tkinter
  Arch, Manjaro, EndeavourOS:    sudo pacman -S python tk
  openSUSE:                      sudo zypper install python3 python3-tk
Ubuntu 22.04 and older ship an older Python: install python3.11 with python3.11-venv and python3.11-tk.
Steam Deck, Fedora Atomic/Bazzite and other read-only systems: install uv (https://docs.astral.sh/uv/),
run 'uv python install 3.12', then: TAGTEAM_PYTHON=\"\$(uv python find 3.12)\" sh Install.sh
Nothing was changed.
$thin
El instalador de Tag Team Mod necesita Python 3.11, 3.12, 3.13 o 3.14 (64 bits) con el modulo venv
y Tk para sus ventanas (o indica --destination, --iso y --pcsx2,
y --bios si el instalador no encuentra la BIOS que usa tu PCSX2).
Instala los paquetes que faltan con los comandos de arriba y vuelve a ejecutar sh Install.sh.
En Steam Deck, Fedora Atomic/Bazzite y otros sistemas de solo lectura, instala uv y usa TAGTEAM_PYTHON
como se indica arriba.
No se ha cambiado nada.
$thin
$copy
$rule"
  show_error "$message"
  pause
  exit 40
fi

# Without a terminal, an error that setup could not show in its own window (before Tk opens, or without a display
# for Tk) is written to this file and shown here in a dialog.
errfile=
if [ ! -t 2 ]; then errfile=$(mktemp "${TMPDIR:-/tmp}/tagteam-setup.XXXXXX" 2>/dev/null) || errfile=; fi
env PYTHONNOUSERSITE=1 PYTHONPATH= PYTHONUTF8=1 PYTHONIOENCODING=utf-8 TAGTEAM_SETUP_ERROR_FILE="$errfile" \
  "$python" -I -X utf8 "$here/setup/install_linux.py" "$@"
rc=$?
if [ -n "$errfile" ]; then
  [ -s "$errfile" ] && show_dialog "$(cat "$errfile")"
  rm -f "$errfile"
fi
pause
exit "$rc"
