#!/usr/bin/env bash
# Identify the FTMO S&P 500 CFD symbol + its tick freshness.
set -uo pipefail
A="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/MQL5/Files/apex"
SF="$A/symbols_all.txt"
echo "=== symbols_all.txt ==="
if [ -f "$SF" ]; then
  echo "count=$(wc -l < "$SF")  age=$(( $(date +%s) - $(stat -c %Y "$SF") ))s"
else
  echo "MISSING — EA has not dumped yet"; exit 0
fi
echo "=== S&P / index / cash candidates ==="
grep -iE '500|SPX|US3|US10|US100|USA|GER|DAX|NAS|NDX|UST|DJI|cash|\.c$|\.cfd' "$SF" | sort -u
echo "=== full non-6char-FX list (indices/metals/CFDs) ==="
awk 'length($0) < 6 || length($0) > 6 || $0 !~ /^[A-Z]{6}$/' "$SF" | sort -u | head -60
