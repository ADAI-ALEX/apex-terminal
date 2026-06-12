#!/usr/bin/env bash
# Privacy-preserving login-config diagnostic: show common.ini with the password
# masked, plus shape checks on the .env credentials.
set -uo pipefail
CFG="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/config/common.ini"
echo "── common.ini (password masked) ──"
if [ -f "$CFG" ]; then
  PLEN=$(grep -E '^Password=' "$CFG" | head -1 | cut -d= -f2- | tr -d '\r\n' | wc -c)
  sed "s/^Password=.*/Password=<MASKED len=$PLEN>/" "$CFG"
else
  echo "MISSING: $CFG"
fi
echo "── .env shape ──"
L=$(grep -E '^MT5_LOGIN=' "$HOME/apex-v4/.env" | head -1 | cut -d= -f2- | tr -d '\r')
S=$(grep -E '^MT5_SERVER=' "$HOME/apex-v4/.env" | head -1 | cut -d= -f2- | tr -d '\r')
echo "login_len=${#L}"
case "$L" in
  *[!0-9]*) echo "login_numeric=NO" ;;
  *)        echo "login_numeric=YES" ;;
esac
echo "server=$S"
