#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  APEX ALGO — start.sh  (VPS / Linux / macOS)
#  First run installs deps + creates .env; then launches the algo.
# ─────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "         APEX ALGO  v1.0  (Linux/VPS)"
echo "============================================"

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found (need 3.11+)."; exit 1; }

if [ ! -d "venv" ]; then
  echo "[SETUP] First run — creating venv + installing deps..."
  python3 -m venv venv
  # shellcheck disable=SC1091
  source venv/bin/activate
  python -m pip install --upgrade pip -q
  pip install -r requirements.txt -q
else
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ">> Created .env — fill in IG + Anthropic credentials, then re-run."
  exit 0
fi

export IG_ACC_TYPE="${IG_ACC_TYPE:-DEMO}"
echo "Starting Apex Algo (IG_ACC_TYPE=$IG_ACC_TYPE)..."
exec python main.py
