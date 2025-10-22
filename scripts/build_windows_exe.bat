@echo off
setlocal enabledelayedexpansion

set PYTHON_EXE=python

REM Install PyInstaller
%PYTHON_EXE% -m pip install --upgrade pip pyinstaller || goto :error

REM Build GUI app
set ENTRY=%~dp0..\apps\wallet_checker_gui.py
REM Produces a single-file GUI app without console window
%PYTHON_EXE% -m PyInstaller --onefile --name CryptoPRPlus --noconsole "%ENTRY%" || goto :error

REM Build CLI scanner that exits when balance > 0
set ENTRY_CLI=%~dp0..\apps\scan_until_profit.py
%PYTHON_EXE% -m PyInstaller --onefile --name ScanUntilProfit --paths "%~dp0.." "%ENTRY_CLI%" || goto :error

echo.
echo Build complete. Find CryptoPRPlus.exe and ScanUntilProfit.exe in the dist folder.
exit /b 0

:error
echo Build failed with error %errorlevel%.
exit /b %errorlevel%
