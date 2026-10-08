@echo off
rem TTM Online Kit: find a Python 3.9+ for Play online.cmd and relay.cmd (sets PY; call it, do not run it).
rem Order: 1. --install "FOLDER" on the command line (that Tag Team Mod installation's own .venv Python)
rem        2. the TTM_PYTHON environment variable  3. the Python this kit used last time (data\python-path.txt)
rem        4. the Python launcher (py -3)  5. %LOCALAPPDATA%\Programs\Python\Python3*  6. python on PATH
rem The kit itself needs only Python's standard library (preparing a new match needs the installation's Python).
set "PY="
set "TTM_INSTALL="
call :scan %*
if defined TTM_INSTALL if exist "%TTM_INSTALL%\.venv\Scripts\python.exe" set "PY=%TTM_INSTALL%\.venv\Scripts\python.exe"
if defined TTM_INSTALL if not defined PY if exist "%TTM_INSTALL%\..\.venv\Scripts\python.exe" set "PY=%TTM_INSTALL%\..\.venv\Scripts\python.exe"
if not defined PY if defined TTM_PYTHON set "PY=%TTM_PYTHON%"
if not defined PY if exist "%~dp0..\data\python-path.txt" set /p PY=<"%~dp0..\data\python-path.txt"
if defined PY if not exist "%PY%" set "PY="
if defined PY call :check "%PY%" || set "PY="
if not defined PY for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do call :check "%%P" && set "PY=%%P"
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" call :check "%%D\python.exe" && set "PY=%%D\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do if not defined PY call :check "%%P" && set "PY=%%P"
exit /b 0

:check
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
exit /b %ERRORLEVEL%

:scan
if "%~1"=="" exit /b 0
if /i "%~1"=="--install" set "TTM_INSTALL=%~2"
shift
goto :scan
