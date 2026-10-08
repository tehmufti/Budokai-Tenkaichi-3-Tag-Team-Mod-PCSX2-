@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-modder.ps1"
if errorlevel 1 pause
exit /b
