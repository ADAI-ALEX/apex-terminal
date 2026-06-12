#!/usr/bin/env bash
# Walk back through MetaTrader5 package versions until one completes the IPC
# handshake under this Wine. Logs INIT=True on the first winner.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
PY='C:\Python310\python.exe'
cd "$HOME/apex-v4"
for v in 5.0.4874 5.0.4424 5.0.45; do
  echo "=== TRY MetaTrader5==$v ==="
  pkill -f terminal64[.]exe 2>/dev/null || true
  sleep 3
  wine "$PY" -m pip install --quiet --no-warn-script-location "MetaTrader5==$v" 2>&1 | tail -1
  timeout 400 wine "$PY" remote/probe_ipc.py
  if wine "$PY" -c "import MetaTrader5 as m, sys; sys.exit(0)" 2>/dev/null && \
     tail -5 /dev/null; then :; fi
done
pkill -f terminal64[.]exe 2>/dev/null || true
echo PROBE_VERSIONS_DONE
