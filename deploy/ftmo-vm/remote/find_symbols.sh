#!/usr/bin/env bash
# Extract index/crypto symbol names from the FTMO symbols database.
set -uo pipefail
BASE="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/Bases/FTMO-Demo"
find "$BASE" -iname '*symbol*' 2>/dev/null
for f in $(find "$BASE" -iname '*symbol*' -type f 2>/dev/null); do
  echo "── $f ──"
  strings "$f" | grep -oE '^[A-Z0-9.]{3,12}$' | grep -iE '500|BTC|SPX|NAS|US3|USTEC' | sort -u | head -20
done
