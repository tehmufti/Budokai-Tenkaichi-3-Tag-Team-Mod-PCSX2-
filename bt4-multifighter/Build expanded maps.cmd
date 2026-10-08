@echo off
setlocal
pushd "%~dp0"
python tools\map_scale_launch.py --build
set "result=%errorlevel%"
popd
pause
exit /b %result%
