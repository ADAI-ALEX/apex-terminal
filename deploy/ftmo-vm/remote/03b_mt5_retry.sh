#!/usr/bin/env bash
# Clean Wine prefix re-init + silent MT5 install (recovery for a half-initialized
# prefix from the official script's first pass).
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all

rm -rf "$HOME/.mt5"
echo '── wineboot init ──'
xvfb-run -a wineboot -u
wineserver -w

echo '── webview2 ──'
xvfb-run -a wine "$HOME/webview2.exe" /silent /install
wineserver -w || true

echo '── mt5setup /auto ──'
xvfb-run -a wine "$HOME/mt5setup.exe" /auto
wineserver -w || true

T64="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$T64" ]; then
  echo "MT5 INSTALL OK: $T64"
else
  echo "MT5 INSTALL FAILED — prefix contents:"
  find "$HOME/.mt5/drive_c" -maxdepth 3 -iname '*.exe' 2>/dev/null | head -10
fi
