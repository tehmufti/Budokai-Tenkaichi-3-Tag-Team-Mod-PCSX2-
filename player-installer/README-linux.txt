TAG TEAM MOD - LINUX - START HERE / EMPIEZA AQUI

ENGLISH
1. Extract this entire archive into your home folder.
2. Open a terminal in the extracted Tag Team Mod Installer folder and run:
   sh Install.sh
3. Choose English or Spanish, then select your ISO, the official PCSX2
   AppImage and a new installation folder. Setup uses the BIOS your PCSX2
   already uses; it asks for one only if it finds none.
4. Start Play.sh in that new folder. Press Select at the main menu for
   Modded Modes. Modes chosen from the original menu play normally.
Settings: Modded Modes > Mod Settings, or Mod settings.sh in your install.

You need Linux x86-64, Python 3.11-3.14 with venv and Tk, FUSE 3 and libOpenGL.
Setup identifies missing dependencies. Use the official PCSX2 AppImage, not
Flatpak. Stable 2.6.0-2.6.3 and 2.8.0-2.8.2 are accepted (2.8.2 recommended);
other 2.x builds show an untested-version notice. PCSX2 3.x is not supported.
Supply your own BT3 USA / Europe / Japan or BT4 B14 REV2 ISO and your own PS2 BIOS.
BT4 is experimental; not every character/move has been playtested.
The European BT3 disc (SLES-54945) runs at 50 Hz, like the original game.
The Japanese BT3 disc (SLPS-25815) confirms with Circle in its own menus.

Keep the setup folder intact; you do not need to open its other files.
Full instructions, updates and troubleshooting: setup/README.md (Linux).
If setup stops, it prints a block that starts with a code like [TTM-ISO-02]
and says what to fix; nothing is changed before all checks pass. Run
sh Install.sh again with the same folder: an unfinished attempt is renamed
"Tag Team Mod (failed <date>)" (never deleted), and an existing installation is
kept (the new one goes beside it and setup offers to copy your memory cards and
mod settings; PCSX2 settings and savestates stay in the old folder).
Setup logs: ~/.local/state/tagteammod/logs.
If Play fails, run Check installation.sh in your installation folder first.
Report the mod/PCSX2 versions, mode, fighters, stage and steps that caused the
problem, and copy the block with the code.
Do not include your ISO, BIOS, memory cards or save states in a bug report.

ESPANOL
1. Extrae todo el archivo en tu carpeta personal.
2. Abre una terminal en la carpeta Tag Team Mod Installer y ejecuta:
   sh Install.sh
3. Elige el idioma, tu ISO, el AppImage oficial de PCSX2 y una carpeta
   nueva para la instalacion. El instalador usa la BIOS que ya usa tu PCSX2;
   solo la pide si no encuentra ninguna.
4. Abre Play.sh en la nueva carpeta. Pulsa Select en el menu principal
   para abrir los modos del mod. Los modos del menu original funcionan
   como en el juego normal.
Ajustes: Modos del mod > Ajustes del mod, o Mod settings.sh.

Necesitas Linux x86-64, Python 3.11-3.14 con venv y Tk, FUSE 3 y libOpenGL.
El instalador indica las dependencias que falten. Usa el AppImage oficial
de PCSX2, no Flatpak. Se admiten las versiones estables 2.6.0-2.6.3 y
2.8.0-2.8.2 (se recomienda 2.8.2). Otras versiones 2.x muestran un aviso
de version no probada. PCSX2 3.x no es compatible.
Necesitas tu propia ISO de BT3 USA / Europa / Japon o BT4 B14 REV2 y tu BIOS de PS2.
BT4 es experimental; no se han probado todos los personajes y ataques.
El BT3 europeo (SLES-54945) funciona a 50 Hz, como el juego original.
El BT3 japones (SLPS-25815) confirma con Circulo en sus propios menus.

Conserva la carpeta setup completa. No necesitas abrir sus otros archivos.
Instrucciones, actualizaciones y ayuda: setup/LEEME.md (Linux).
Si el instalador se detiene, muestra un bloque que empieza con un codigo como
[TTM-ISO-02] e indica que corregir; no cambia nada hasta superar todas las
comprobaciones. Vuelve a ejecutar sh Install.sh con la misma carpeta: el intento
sin terminar se renombra "Tag Team Mod (failed <fecha>)" (nunca se borra) y una
instalacion existente se conserva (la nueva se crea junto a ella y el
instalador ofrece copiar tus tarjetas de memoria y ajustes del mod; los ajustes
y estados guardados de PCSX2 se quedan en la carpeta anterior).
Registros del instalador: ~/.local/state/tagteammod/logs.
Si falla Play, ejecuta primero Check installation.sh. Al informar de un
error, indica las versiones del mod y PCSX2, el modo, los personajes,
el escenario y los pasos para reproducirlo, y copia el bloque con el codigo.
No adjuntes tu ISO, BIOS, tarjetas de memoria ni estados guardados.
