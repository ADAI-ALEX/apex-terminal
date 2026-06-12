#!/usr/bin/env bash
# Run one strategy leg on NATIVE Linux Python via the file bridge.
# usage: run_leg.sh btc|us500
set -uo pipefail
leg="${1:?usage: run_leg.sh btc|us500}"
case "$leg" in
  btc)   script=global_macro_v4.py;          logf=btc_console.log ;;
  us500) script=auction_flow_v5_1_hybrid.py; logf=us500_console.log ;;
  *) echo "unknown leg: $leg" >&2; exit 1 ;;
esac
cd "$HOME/apex-v4"
export APEX_MT5_MODE=bridge
exec python3 "$script" 2>&1 | tee -a "$logf"
