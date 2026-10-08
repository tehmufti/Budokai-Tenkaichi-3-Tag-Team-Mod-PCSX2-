@echo off
setlocal
rem Tag Team Mod setup: runs setup\install-player.ps1. Keep this file next to its setup folder.
set "TTM_ROOT=%~dp0"
if not exist "%~dp0setup\install-player.ps1" goto :not_extracted
rem A 32-bit program that opens this file starts 32-bit Windows tools: use the 64-bit PowerShell.
set "TTM_PS=powershell.exe"
if defined PROCESSOR_ARCHITEW6432 if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "TTM_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
rem Files extracted from a downloaded ZIP carry its internet mark; remove it so the setup scripts may run.
%TTM_PS% -NoProfile -NonInteractive -Command "Get-ChildItem -LiteralPath $env:TTM_ROOT -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1
rem -ExecutionPolicy Bypass cannot override a policy set by Group Policy (MachinePolicy or UserPolicy).
set "TTM_POLICY="
for /f "usebackq delims=" %%P in (`%TTM_PS% -NoProfile -NonInteractive -Command "$b = @(); foreach ($s in 'MachinePolicy','UserPolicy') { $v = [string](Get-ExecutionPolicy -Scope $s); if ($v -eq 'AllSigned' -or $v -eq 'Restricted') { $b += $s + '=' + $v } }; $b -join ', '"`) do set "TTM_POLICY=%%P"
if defined TTM_POLICY goto :policy_blocked
%TTM_PS% -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\install-player.ps1" %*
set "result=%errorlevel%"
pause
exit /b %result%

:not_extracted
set "TTM_DIR=%~dp0"
set "TTM_INZIP="
if /i not "%TTM_DIR:\Temp1_=%"=="%TTM_DIR%" set "TTM_INZIP=1"
if /i not "%TTM_DIR:\7zO=%"=="%TTM_DIR%" set "TTM_INZIP=1"
if /i not "%TTM_DIR:\Rar$EX=%"=="%TTM_DIR%" set "TTM_INZIP=1"
if /i not "%TTM_DIR:.zip\=%"=="%TTM_DIR%" set "TTM_INZIP=1"
echo ==============================================================================
echo [TTM-ZIP-01] SETUP STOPPED / INSTALACION DETENIDA
echo ------------------------------------------------------------------------------
echo WHAT HAPPENED: Install.cmd was started without its setup folder.
echo WHY: Opening a file inside a ZIP extracts only that file, so the rest of the
echo   installer is missing.
echo HOW TO FIX: Extract the whole release archive first (Windows: right-click the
echo   ZIP, Extract All). Then open the extracted "Tag Team Mod Installer" folder
echo   and run Install.cmd there.
echo Nothing was changed.
echo ------------------------------------------------------------------------------
echo QUE HA PASADO: Install.cmd se ha abierto sin su carpeta setup.
echo POR QUE: Al abrir un archivo dentro de un ZIP solo se extrae ese archivo, asi
echo   que falta el resto del instalador.
echo COMO SOLUCIONARLO: Extrae primero el archivo completo (Windows: clic derecho
echo   en el ZIP, Extraer todo). Despues abre la carpeta "Tag Team Mod Installer"
echo   extraida y ejecuta Install.cmd alli.
echo No se ha cambiado nada.
echo ------------------------------------------------------------------------------
echo FILE / ARCHIVO:
echo   "%~dp0setup\install-player.ps1"
echo Copy this block when asking for help. / Copia este bloque si pides ayuda.
echo ==============================================================================
if defined TTM_INZIP echo You opened Install.cmd from inside the ZIP. / Has abierto Install.cmd desde dentro del ZIP.
pause
exit /b 10

:policy_blocked
echo ==============================================================================
echo [TTM-OS-02] SETUP STOPPED / INSTALACION DETENIDA
echo ------------------------------------------------------------------------------
echo WHAT HAPPENED: This PC blocks PowerShell scripts through an administrator
echo   policy (%TTM_POLICY%).
echo WHY: Group Policy sets the script execution policy, and setup cannot override
echo   it.
echo HOW TO FIX: Ask the administrator of this PC to allow scripts, or install on a
echo   PC you manage.
echo Nothing was changed.
echo ------------------------------------------------------------------------------
echo QUE HA PASADO: Este PC bloquea los scripts de PowerShell mediante una
echo   directiva del administrador (%TTM_POLICY%).
echo POR QUE: La directiva de grupo fija la ejecucion de scripts y el instalador no
echo   puede cambiarla.
echo COMO SOLUCIONARLO: Pide al administrador de este PC que permita los scripts, o
echo   instalalo en un PC que administres tu.
echo No se ha cambiado nada.
echo ------------------------------------------------------------------------------
echo Copy this block when asking for help. / Copia este bloque si pides ayuda.
echo ==============================================================================
pause
exit /b 20
