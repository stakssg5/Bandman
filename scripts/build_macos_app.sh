#!/usr/bin/env bash
set -euo pipefail

# Builds a macOS .app bundle using PyInstaller
# Usage:
#   bash scripts/build_macos_app.sh [python_executable]
# Example:
#   bash scripts/build_macos_app.sh python3

PYTHON_EXE="${1:-python3}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTRY="${ROOT_DIR}/apps/wallet_checker_gui.py"

if [[ ! -f "${ENTRY}" ]]; then
  echo "Entry script not found: ${ENTRY}" >&2
  exit 1
fi

# Ensure PyInstaller is available
"${PYTHON_EXE}" -m pip install --upgrade pip pyinstaller

# Build a GUI app bundle (.app) with no console window
"${PYTHON_EXE}" -m PyInstaller \
  --windowed \
  --name "CryptoPRPlus" \
  --osx-bundle-identifier "com.example.cryptoprplus" \
  "${ENTRY}"

APP_PATH="${ROOT_DIR}/dist/CryptoPRPlus.app"
if [[ -d "${APP_PATH}" ]]; then
  echo "\nBuild complete. Open the app at: ${APP_PATH}" \
       "\nRight-click -> Open if Gatekeeper blocks unsigned apps." 
else
  echo "Build finished but app not found in dist/." >&2
  exit 2
fi
