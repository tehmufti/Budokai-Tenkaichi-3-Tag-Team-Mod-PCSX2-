@echo off
setlocal
rem Same Python environment as an installed Play.cmd (install_player.CMD_ENVIRONMENT), except the private
rem .venv: a developer folder runs the PATH Python.
set "PYTHONHOME="
set "PYTHONPATH="
set "TAGTEAM_DISC="
set "TAGTEAM_ADAPTER="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch-autopilot.ps1"
set "launch_exit=%errorlevel%"
if not "%launch_exit%"=="0" pause
exit /b %launch_exit%
