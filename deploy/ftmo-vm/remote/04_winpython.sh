#!/usr/bin/env bash
# Windows Python 3.10 silently installed INSIDE the ~/.mt5 Wine prefix —
# the MetaTrader5 pip package only ships Windows wheels.
# Runs HEADLESS: /quiet installer needs no display, and the X11 path is the
# fragile one on this box.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
unset DISPLAY
cd "$HOME"

PYEXE=python-3.10.11-amd64.exe
[ -f "$PYEXE" ] || wget -q "https://www.python.org/ftp/python/3.10.11/$PYEXE"
echo "── installing Windows Python 3.10.11 into $WINEPREFIX ──"
wine "$PYEXE" /quiet InstallAllUsers=1 PrependPath=1 \
  Include_test=0 Include_doc=0 Include_tcltk=0 Include_launcher=0 \
  || echo "installer exit $?"
wineserver -w || true

WPY="$WINEPREFIX/drive_c/Program Files/Python310/python.exe"
if [ -f "$WPY" ]; then
  wine "C:\\Program Files\\Python310\\python.exe" -V
  echo "WIN-PYTHON OK"
else
  echo "WIN-PYTHON FAILED — not found in prefix"
  exit 1
fi
