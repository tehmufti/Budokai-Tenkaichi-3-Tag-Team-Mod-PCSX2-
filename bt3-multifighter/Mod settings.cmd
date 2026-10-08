@echo off
setlocal
rem Same Python environment as an installed Play.cmd (install_player.CMD_ENVIRONMENT), except the private
rem .venv: a developer folder runs the PATH Python.
set "PYTHONHOME="
set "PYTHONPATH="
set "TAGTEAM_DISC="
set "TAGTEAM_ADAPTER="
start "" powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0launch-settings.ps1"
