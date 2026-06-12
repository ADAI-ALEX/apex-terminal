#!/usr/bin/env bash
# Install FTMO's branded MT5 (ships FTMO server records), copy servers.dat
# into our stock portable terminal, restart it, and verify authorization.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
STOCK="$HOME/.mt5/drive_c/Program Files/MetaTrader 5"

pkill -f 'terminal64[.]exe' 2>/dev/null || true
sleep 3

echo '── install FTMO MT5 /auto ──'
timeout 540 wine "$HOME/ftmo5setup.exe" /auto
echo "ftmo setup exit $?"
sleep 3

FTMO_DIR=$(find "$HOME/.mt5/drive_c/Program Files" -maxdepth 1 -iname '*FTMO*' -type d | head -1)
echo "ftmo install dir: ${FTMO_DIR:-NOT_FOUND}"

SRV=""
if [ -n "$FTMO_DIR" ] && [ -f "$FTMO_DIR/config/servers.dat" ]; then
  SRV="$FTMO_DIR/config/servers.dat"
else
  # server records may only materialize after a first boot of the FTMO terminal
  if [ -n "$FTMO_DIR" ] && [ -f "$FTMO_DIR/terminal64.exe" ]; then
    echo '── boot FTMO terminal once to materialize servers.dat ──'
    (cd "$FTMO_DIR" && timeout 120 wine terminal64.exe /portable >/dev/null 2>&1) || true
    pkill -f 'terminal64[.]exe' 2>/dev/null || true
    sleep 3
    [ -f "$FTMO_DIR/config/servers.dat" ] && SRV="$FTMO_DIR/config/servers.dat"
  fi
fi

if [ -z "$SRV" ]; then
  echo 'SERVERS_DAT_NOT_FOUND — listing candidates:'
  find "$HOME/.mt5/drive_c" -iname 'servers.dat' 2>/dev/null
  exit 1
fi
cp "$SRV" "$STOCK/config/servers.dat"
echo "servers.dat copied from: $SRV"

echo '── restart stock terminal ──'
tmux kill-window -t apex:mt5 2>/dev/null || true
pkill -f 'terminal64[.]exe' 2>/dev/null || true
sleep 3
tmux new-window -t apex -n mt5 "bash $HOME/apex-v4/remote/run_terminal.sh"
sleep 200

echo '── verdict ──'
iconv -f UTF-16LE -t UTF-8 "$STOCK/logs/$(date -u +%Y%m%d).log" 2>/dev/null \
  | grep -iE 'authoriz|network|expert' | tail -6
echo '── heartbeat ──'
cat "$STOCK/MQL5/Files/apex/heartbeat.txt" 2>/dev/null || echo NO_HEARTBEAT
echo FTMO_SERVERS_DONE
