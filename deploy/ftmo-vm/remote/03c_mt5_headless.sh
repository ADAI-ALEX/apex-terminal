#!/usr/bin/env bash
# MT5 install, attempt 3: persistent Xvfb :1 if possible, else fully headless
# (wineboot proved to work with no display on this box post-reboot).
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all

pkill -f mt5setup 2>/dev/null || true
pkill -f wineboot 2>/dev/null || true
wineserver -k 2>/dev/null || true
sleep 2

echo '── Xvfb sanity ──'
pkill -f 'Xvfb :1' 2>/dev/null || true
Xvfb :1 -screen 0 1024x768x16 >/tmp/xvfb1.log 2>&1 &
XPID=$!
sleep 3
if kill -0 "$XPID" 2>/dev/null; then
  echo "Xvfb :1 alive (pid $XPID) — using DISPLAY=:1"
  export DISPLAY=:1
else
  echo "Xvfb died ($(tail -c 200 /tmp/xvfb1.log)) — going fully headless"
  unset DISPLAY
fi

echo '── prefix init ──'
rm -rf "$HOME/.mt5"
wineboot -u
wineserver -w

echo '── webview2 /silent ──'
wine "$HOME/webview2.exe" /silent /install || echo "webview2 exit code $? (non-fatal)"
wineserver -w || true

echo '── mt5setup /auto ──'
wine "$HOME/mt5setup.exe" /auto
echo "mt5setup exit code $?"
wineserver -w || true

T64="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$T64" ]; then
  echo "MT5 INSTALL OK: $T64"
else
  echo 'MT5 INSTALL FAILED — prefix dirs:'
  find "$HOME/.mt5/drive_c" -maxdepth 2 -type d 2>/dev/null | head -15
fi
kill "$XPID" 2>/dev/null || true
