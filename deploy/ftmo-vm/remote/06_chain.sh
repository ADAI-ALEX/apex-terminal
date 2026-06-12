#!/usr/bin/env bash
# Self-chaining tail of the provisioning pipeline: wait for the MT5 install
# marker, then Windows Python, then pip MetaTrader5. One log: ~/chain.log.
set -uo pipefail
echo "chain: waiting for MT5 install marker…"
until grep -qE 'MT5 INSTALL (OK|FAILED)' "$HOME/mt5c.log" 2>/dev/null; do sleep 15; done
if ! grep -q 'MT5 INSTALL OK' "$HOME/mt5c.log"; then
  echo 'CHAIN ABORTED: MT5 install failed'
  exit 1
fi
echo "chain: MT5 OK — installing Windows Python"
bash "$HOME/apex-v4/remote/04_winpython.sh"
echo "chain: pip stage"
bash "$HOME/apex-v4/remote/05_pip.sh"
echo 'CHAIN DONE'
