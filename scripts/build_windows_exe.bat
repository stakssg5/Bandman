@echo off
setlocal enabledelayedexpansion

set PYTHON_EXE=python

REM Install PyInstaller
%PYTHON_EXE% -m pip install --upgrade pip pyinstaller || goto :error

REM Build
set ENTRY=%~dp0..\apps\wallet_checker_gui.py
REM Produces a single-file GUI app without console window
%PYTHON_EXE% -m PyInstaller --onefile --name CryptoPRPlus --noconsole "%ENTRY%" || goto :error

echo.
echo Build complete. Find CryptoPRPlus.exe in the dist folder.
exit /b 0

:error
echo Build failed with error %errorlevel%.
exit /b %errorlevel%
