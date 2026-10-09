TAG TEAM MOD - UPDATE AN EXISTING INSTALLATION

1. Extract the whole download.
2. Close Play, Play online, PCSX2, Mod Settings and Workbench.
3. Run Update.cmd (Windows) or sh Update.sh (Linux).
4. Choose your installed Tag Team Mod folder: the one containing Play.cmd/Play.sh.
5. Wait for "Update complete", then use your existing Play shortcut.

Keep everyone in an online room on the same release.
Your game discs, BIOS, emulator, controller bindings, saves, settings, online profile
and existing custom scenarios are preserved. New example filenames are added; existing
scenario files are not replaced, because you may have edited them.

Replaced files are backed up in update-backups inside your installation. Interrupted
or failed updates restore the previous files. Run the updater again after a power
loss to recover before playing. To undo a completed update, use:
  Windows: Update.cmd -Installation "C:\Games\Tag Team Mod" -Restore
  Linux:   sh Update.sh "/path/to/Tag Team Mod" --restore

This updates a player installation, not a source checkout. It supports the same
BT3/BT4 discs as the full installer. The updater checks the dependency lock before
making changes; releases requiring a different Python dependency set require the
full installer. It never downloads a game, BIOS or emulator.

ACTUALIZAR UNA INSTALACION EXISTENTE

Extrae todo el archivo. Cierra el mod y PCSX2. Ejecuta Update.cmd (Windows) o
sh Update.sh (Linux) y elige la carpeta donde instalaste el mod (contiene Play.cmd
o Play.sh). Espera a que termine y usa el mismo acceso directo para jugar.

Se conservan tus partidas, ajustes, mandos, perfil online y escenarios editados.
Todos los participantes de una sala online deben usar la misma version.
Los archivos sustituidos se guardan en update-backups. Si se interrumpe la
actualizacion, vuelve a ejecutar el actualizador antes de jugar para recuperarla.
