#!/usr/bin/env bash
# Unstick the swap (stale wineserver blocked `wineserver -w`), verify the
# MetaTrader5 package imports under wine-stable, then run the IPC probe.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
PY='C:\Python310\python.exe'
cd "$HOME/apex-v4"

pkill -f wine_stable_swap 2>/dev/null || true
wineserver -k 2>/dev/null || true
sleep 3

echo '── verify package import ──'
if ! wine "$PY" -c "import MetaTrader5 as m; print('pkg', m.__version__)" 2>/dev/null; then
  echo 'import failed — reinstalling MetaTrader5 5.0.5735'
  timeout 300 wine "$PY" -m pip install --quiet --no-warn-script-location MetaTrader5==5.0.5735 2>&1 | tail -1
  wine "$PY" -c "import MetaTrader5 as m; print('pkg', m.__version__)"
fi

echo '── IPC probe (wine-stable) ──'
timeout 420 wine "$PY" remote/probe_ipc.py
pkill -f terminal64[.]exe 2>/dev/null || true
echo STABLE_PROBE_DONE
