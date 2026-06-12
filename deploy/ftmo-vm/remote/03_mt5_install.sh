#!/usr/bin/env bash
# MetaTrader 5 via the OFFICIAL MetaQuotes Linux script (download.mql5.com),
# executed headless inside xvfb. The script installs WineHQ stable and creates
# the ~/.mt5 prefix; we pass the MT5 installer the /auto flag for silent mode.
set -euo pipefail
cd "$HOME"

# Official URL from https://www.metatrader5.com/en/terminal/help/start_advanced/install_linux
wget -q https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5linux.sh -O mt5linux.sh
chmod +x mt5linux.sh
echo "── mt5linux.sh downloaded ($(wc -c < mt5linux.sh) bytes) ──"

# Force the MT5 setup itself to run silently (/auto) — headless box.
# The official script launches: wine "$HOME/mt5setup.exe" (sometimes without /auto).
if ! grep -q '/auto' mt5linux.sh; then
  sed -i 's#wine "\$HOME/mt5setup.exe"#wine "\$HOME/mt5setup.exe" /auto#g' mt5linux.sh
  sed -i "s#wine \$HOME/mt5setup.exe#wine \$HOME/mt5setup.exe /auto#g" mt5linux.sh
  echo "patched installer invocation to silent (/auto)"
fi

export WINEDEBUG=-all
xvfb-run -a ./mt5linux.sh
wineserver -w || true

T64="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$T64" ]; then
  echo "MT5 INSTALL OK: $T64"
else
  echo "MT5 terminal not found at expected path — listing prefix:" >&2
  find "$HOME/.mt5/drive_c" -maxdepth 3 -iname '*.exe' 2>/dev/null | head -20
  exit 1
fi
