@echo off
rem Double-click to build RAH iRacing Overlay. Extra arguments are passed through,
rem e.g. build.bat --skip-tests
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python was not found. Install 64-bit Python 3.10-3.13 from
    echo https://www.python.org/downloads/windows/  ^(or: winget install Python.Python.3.13^)
    goto :end
)

%PY% build_exe.py %*
if errorlevel 1 (
    echo.
    echo Build FAILED. See the messages above.
) else (
    echo.
    echo Build finished. Open dist\RAH_Telemetry_Overlay\RAH_Telemetry_Overlay.exe
)

:end
if "%~1"=="" pause
endlocal
