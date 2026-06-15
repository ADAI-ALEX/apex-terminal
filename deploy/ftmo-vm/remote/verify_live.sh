#!/usr/bin/env bash
set -uo pipefail
APEX="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/MQL5/Files/apex"
echo "=== heartbeat freshness ==="
if [ -f "$APEX/heartbeat.txt" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$APEX/heartbeat.txt") ))
  echo "age=${age}s"; cat "$APEX/heartbeat.txt"
else
  echo NO_HB
fi
echo "=== respawn engine legs ==="
bash "$HOME/apex-v4/remote/respawn_legs.sh"
echo "=== wait 70s for attach ==="
sleep 70
echo "--- BTC ---"; tail -3 "$HOME/apex-v4/global_macro_v4.log"
echo "--- US500 ---"; tail -3 "$HOME/apex-v4/auction_flow_v5_1.log"
echo "=== live SP500m feed ==="
head -3 "$APEX/sym_SP500m.txt" 2>/dev/null || echo NO_FEED
echo VERIFY_LIVE_DONE
