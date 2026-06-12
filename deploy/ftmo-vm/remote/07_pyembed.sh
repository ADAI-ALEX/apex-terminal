#!/usr/bin/env bash
# Windows Python via the EMBEDDABLE zip (no Burn installer — Wine-safe),
# placed at C:\Python310 inside the ~/.mt5 prefix, then get-pip + MetaTrader5.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
unset DISPLAY
cd "$HOME"

command -v unzip >/dev/null || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y unzip >/dev/null
[ -f python-3.10.11-embed-amd64.zip ] || \
  wget -q https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip

PYDIR="$WINEPREFIX/drive_c/Python310"
rm -rf "$PYDIR"
mkdir -p "$PYDIR"
unzip -q -o python-3.10.11-embed-amd64.zip -d "$PYDIR"

# embeddable distro ships with site-packages disabled — enable it for pip
sed -i 's/^#import site/import site/' "$PYDIR/python310._pth"

wget -q https://bootstrap.pypa.io/get-pip.py -O "$PYDIR/get-pip.py"
PY='C:\Python310\python.exe'
echo '── get-pip ──'
wine "$PY" 'C:\Python310\get-pip.py' --no-warn-script-location 2>&1 | tail -2
echo '── pip install MetaTrader5 numpy ──'
wine "$PY" -m pip install --no-warn-script-location MetaTrader5 "numpy>=1.24,<3" 2>&1 | tail -4
wine "$PY" -c "import MetaTrader5 as mt5, numpy; print('MetaTrader5', mt5.__version__, '| numpy', numpy.__version__)" \
  && echo 'PYSTACK OK' || echo 'PYSTACK FAILED'
