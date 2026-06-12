#!/usr/bin/env bash
# Foreground MT5 installer retry under a fresh Xvfb, with full output.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all

pkill -f 'mt5setup[.]exe' 2>/dev/null || true
wineserver -k 2>/dev/null || true
sleep 3
pkill -f '[X]vfb :1' 2>/dev/null || true
sleep 1
Xvfb :1 -screen 0 1280x800x16 >/tmp/x.log 2>&1 &
sleep 3
export DISPLAY=:1
xdpyinfo -display :1 >/dev/null 2>&1 && echo XVFB_OK || echo XVFB_FAIL

cd "$HOME"
timeout 540 wine mt5setup.exe /auto
echo "SETUP_EXIT=$?"
wineserver -w 2>/dev/null || true
T64="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$T64" ]; then echo T64_OK; else echo T64_STILL_MISSING; fi
