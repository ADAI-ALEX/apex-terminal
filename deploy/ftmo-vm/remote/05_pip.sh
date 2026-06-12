#!/usr/bin/env bash
# MetaTrader5 (+numpy) into the Wine Windows Python. Headless — pip needs no X.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
unset DISPLAY
PY='C:\Program Files\Python310\python.exe'
REQ="Z:\\home\\ubuntu\\apex-v4\\requirements.txt"

wine "$PY" -m pip install --upgrade pip --no-warn-script-location 2>&1 | tail -3
wine "$PY" -m pip install --no-warn-script-location -r "$REQ" 2>&1 | tail -6
wine "$PY" -c "import MetaTrader5 as mt5, numpy; print('MetaTrader5', mt5.__version__, '| numpy', numpy.__version__)" \
  && echo "PIP OK" || echo "PIP FAILED"
