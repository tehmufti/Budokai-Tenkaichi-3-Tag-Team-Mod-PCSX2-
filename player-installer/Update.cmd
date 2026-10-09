@echo off
setlocal
if not exist "%~dp0setup\update-player.ps1" (
  echo Extract the entire updater ZIP, then run Update.cmd from its extracted folder.
  echo Extrae todo el ZIP del actualizador y ejecuta Update.cmd desde la carpeta extraida.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\update-player.ps1" %*
set "result=%errorlevel%"
pause
exit /b %result%
