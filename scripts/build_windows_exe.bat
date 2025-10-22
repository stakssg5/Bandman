@echo off
setlocal enabledelayedexpansion

set PYTHON_EXE=python

REM Install PyInstaller
%PYTHON_EXE% -m pip install --upgrade pip pyinstaller || goto :error

REM Build
set ENTRY=%~dp0..\apps\zoeseed.py
%PYTHON_EXE% -m PyInstaller --onefile --name "Zoe seed" --noconsole "%ENTRY%" || goto :error

echo.
echo Build complete. Find the exe in the dist folder as "Zoe seed.exe".
exit /b 0

:error
echo Build failed with error %errorlevel%.
exit /b %errorlevel%
