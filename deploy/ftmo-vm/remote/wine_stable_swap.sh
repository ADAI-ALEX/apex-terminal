#!/usr/bin/env bash
# Swap winehq-staging 11.10 → winehq-stable, restore current MetaTrader5
# package, and re-run the IPC probe. The staging build's experimental patches
# are the prime suspect for the persistent -10005 IPC handshake failure.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
PY='C:\Python310\python.exe'
cd "$HOME/apex-v4"

echo '── quiesce wine ──'
pkill -f terminal64[.]exe 2>/dev/null || true
wineserver -k 2>/dev/null || true
sleep 3

echo '── swap to winehq-stable ──'
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-downgrades winehq-stable 2>&1 | tail -3
echo "wine now: $(wine --version)"

echo '── restore MetaTrader5 5.0.5735 ──'
wine "$PY" -m pip install --quiet --no-warn-script-location MetaTrader5==5.0.5735 2>&1 | tail -1
wineserver -w || true

echo '── IPC probe on wine-stable ──'
timeout 420 wine "$PY" remote/probe_ipc.py
pkill -f terminal64[.]exe 2>/dev/null || true
echo SWAP_PROBE_DONE
