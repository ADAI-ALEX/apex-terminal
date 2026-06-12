#!/usr/bin/env bash
# Last targeted experiment: wine 9.0 (the era of known-good MT5+Python+Wine
# reports). Rebuilds the prefix automatically if the wine-11 prefix refuses
# to load, reusing cached installers (~/mt5setup.exe, python zip).
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
PY='C:\Python310\python.exe'
T64="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
cd "$HOME/apex-v4"

pkill -f terminal64[.]exe 2>/dev/null || true
wineserver -k 2>/dev/null || true
sleep 3

echo '── downgrade to wine 9.0 ──'
VER=$(apt-cache madison wine-stable | grep -oE '9\.0[^ |]*' | head -1 | tr -d ' ')
echo "target: ${VER:-none}"
if [ -z "$VER" ]; then echo NO_WINE9_AVAILABLE; exit 1; fi
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-downgrades \
  winehq-stable="$VER" wine-stable="$VER" wine-stable-amd64="$VER" \
  wine-stable-i386:i386="$VER" 2>&1 | tail -2
echo "wine now: $(wine --version)"

echo '── fresh Xvfb ──'
pkill -f '[X]vfb :1' 2>/dev/null || true
sleep 1
Xvfb :1 -screen 0 1280x800x16 >/tmp/xvfb1.log 2>&1 &
sleep 3
export DISPLAY=:1
xdpyinfo -display :1 >/dev/null 2>&1 && echo XVFB_OK || echo XVFB_FAIL

echo '── prefix compatibility check ──'
if [ ! -f "$T64" ] || ! timeout 180 wine cmd /c echo PREFIX_OK 2>/dev/null | grep -q PREFIX_OK; then
  echo 'PREFIX INCOMPATIBLE — rebuilding (mt5 + python reinstall)'
  wineserver -k 2>/dev/null || true
  rm -rf "$HOME/.mt5"
  wineboot -u; wineserver -w
  wine "$HOME/webview2.exe" /silent /install 2>/dev/null; wineserver -w 2>/dev/null
  wine "$HOME/mt5setup.exe" /auto 2>/dev/null; wineserver -w 2>/dev/null
  if [ ! -f "$T64" ]; then echo MT5_REINSTALL_FAILED; exit 1; fi
  echo MT5_REINSTALL_OK
  PYDIR="$WINEPREFIX/drive_c/Python310"
  mkdir -p "$PYDIR"
  unzip -q -o "$HOME/python-3.10.11-embed-amd64.zip" -d "$PYDIR"
  sed -i 's/^#import site/import site/' "$PYDIR/python310._pth"
  wget -q https://bootstrap.pypa.io/get-pip.py -O "$PYDIR/get-pip.py"
  wine "$PY" 'C:\Python310\get-pip.py' --no-warn-script-location 2>&1 | tail -1
  wine "$PY" -m pip install --quiet --no-warn-script-location \
    MetaTrader5==5.0.5735 "numpy>=1.24,<3" 2>&1 | tail -1
  echo 'Z:/home/ubuntu/apex-v4' > "$PYDIR/Lib/site-packages/apex.pth"
else
  echo PREFIX_OK_UNDER_WINE9
fi

echo '── boot terminal, settle 150s ──'
nohup wine "$T64" >/tmp/term_boot.log 2>&1 &
sleep 150
pgrep -f terminal64[.]exe >/dev/null && echo TERMINAL_ALIVE || echo TERMINAL_DEAD

echo '── probe ──'
timeout 320 wine "$PY" remote/probe_ipc2.py
pkill -f terminal64[.]exe 2>/dev/null || true
echo WINE9_DONE
