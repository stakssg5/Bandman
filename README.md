# Wallet Checker GUI (Crypto PR+ clone)

Quick desktop demo that mimics the mini‑app UI and streams fake "wallet check" results.

## Run locally (Linux/macOS/Windows)

```bash
python3 apps/wallet_checker_gui.py
```

## Build Windows .exe

Requirements: Python 3.10+ and pip on Windows.

Option 1 — PowerShell:
```powershell
scripts\build_windows_exe.ps1 -PythonExe python -Noconsole
```

Option 2 — CMD:
```bat
scripts\build_windows_exe.bat
```

The compiled executable `CryptoPRPlus.exe` will be in the `dist` folder.

## Build macOS app (.app)

Requirements: macOS with Python 3.10+ and pip.

```bash
bash scripts/build_macos_app.sh python3
```

This will produce `dist/CryptoPRPlus.app`.

Note: On first launch, macOS Gatekeeper may block unsigned apps. Use Finder: right‑click the app -> Open -> Open.
