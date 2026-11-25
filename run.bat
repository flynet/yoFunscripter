@echo off
rem Start yoFunscripter from the source checkout (development run).
rem
rem   run.bat
rem
rem The virtual environment is created on the first run. The release build is a
rem packaged exe (build.ps1): this script is for working on the code.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Creating the virtual environment...
    uv sync
    if errorlevel 1 goto :error
)

rem src is on the path so a checkout runs even when the project is not installed.
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
start "yoFunscripter" ".venv\Scripts\pythonw.exe" -m yofunscripter
exit /b 0

:error
echo.
echo Could not create the virtual environment. Install uv (https://docs.astral.sh/uv/)
echo and run "uv sync" in this folder.
pause
exit /b 1
