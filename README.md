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

The compiled executables will be in the `dist` folder:

- `CryptoPRPlus.exe` — GUI app
- `ScanUntilProfit.exe` — CLI that scans addresses across chains until a positive balance is found.

### Run the CLI scanner (cross‑platform)

Examples:

```bash
# Use defaults (public RPCs and demo addresses)
python3 apps/scan_until_profit.py

# Provide your own addresses (comma‑separated)
python3 apps/scan_until_profit.py --addresses "0x...,bc1...,T..."

# Or from a file (one address per line)
python3 apps/scan_until_profit.py --file my_addresses.txt

# Limit chains and throttle requests a bit
python3 apps/scan_until_profit.py --chains eth,btc,tron --sleep-ms 300
```

## Build macOS app (.app)

Requirements: macOS with Python 3.10+ and pip.

```bash
bash scripts/build_macos_app.sh python3
```

This will produce `dist/CryptoPRPlus.app`.

Note: On first launch, macOS Gatekeeper may block unsigned apps. Use Finder: right‑click the app -> Open -> Open.

## Configure real RPCs/APIs (optional)

The GUI includes a basic integration that can query balances across a few chains using public endpoints. For higher reliability, set environment variables to your own RPCs:

- `ETH_RPC_URL` — Ethereum JSON-RPC URL
- `POLYGON_RPC_URL` — Polygon JSON-RPC URL
- `BSC_RPC_URL` — BSC JSON-RPC URL
- `OP_RPC_URL` — Optimism JSON-RPC URL
- `BTC_API_BASE` — Blockstream-like REST base (default `https://blockstream.info/api`)
- `TRON_API_BASE` — TronGrid base (default `https://api.trongrid.io`)

Addresses are currently seeded in the GUI; you can wire your own list by adapting `WalletCheckerApp._seed_demo_addresses()` or exposing a file picker.
