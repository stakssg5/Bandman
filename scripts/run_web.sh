#!/usr/bin/env bash
set -euo pipefail

# Install server deps if missing
python3 - <<'PY'
import sys
try:
    import fastapi, uvicorn, starlette
except Exception:
    sys.exit(1)
PY

if [ $? -ne 0 ]; then
  python3 -m pip install --upgrade pip
  python3 -m pip install fastapi uvicorn[standard]
fi

# Run server
python3 -m uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
