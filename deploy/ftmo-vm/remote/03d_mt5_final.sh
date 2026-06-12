#!/usr/bin/env bash
# MT5 install, final form:
#   1) GL runtime libs (wine x11 driver needs them under Xvfb later)
#   2) prefix init FULLY HEADLESS (the proven-working path on this box)
#   3) silent installers headless; retry once under :1 if needed
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all

# stop the stalled 03c run (kill by exact script path; wineserver -k for wine)
pkill -f 03c_mt5_headless 2>/dev/null || true
wineserver -k 2>/dev/null || true
sleep 3

echo '── GL runtime ──'
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  libegl1 libgl1 libegl1:i386 libgl1:i386 libvulkan1 libvulkan1:i386 2>&1 | tail -2

echo '── prefix init (headless) ──'
unset DISPLAY
rm -rf "$HOME/.mt5"
wineboot -u || echo "wineboot client exit $? (init may continue)"
wineserver -w
echo 'prefix init complete'

echo '── webview2 /silent (headless) ──'
wine "$HOME/webview2.exe" /silent /install || echo "webview2 exit $? (non-fatal)"
wineserver -w || true

echo '── mt5setup /auto (headless) ──'
wine "$HOME/mt5setup.exe" /auto || echo "mt5setup exit $?"
wineserver -w || true

T64="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ ! -f "$T64" ]; then
  echo '── retry mt5setup under Xvfb :1 (GL now present) ──'
  pgrep -f 'Xvfb :1' >/dev/null || { Xvfb :1 -screen 0 1024x768x16 >/tmp/xvfb1.log 2>&1 & sleep 3; }
  DISPLAY=:1 wine "$HOME/mt5setup.exe" /auto || echo "mt5setup(:1) exit $?"
  wineserver -w || true
fi

if [ -f "$T64" ]; then
  echo "MT5 INSTALL OK: $T64"
else
  echo 'MT5 INSTALL FAILED — prefix dirs:'
  find "$HOME/.mt5/drive_c" -maxdepth 2 -type d 2>/dev/null | head -15
fi
