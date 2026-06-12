#!/usr/bin/env bash
# Extract FTMO access-point hosts from servers.dat and probe raw TCP:443.
set -uo pipefail
CFG="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/config"
echo "── config dir ──"
ls -la "$CFG" | head -10
SRV="$CFG/servers.dat"
[ -f "$SRV" ] || { echo NO_SERVERS_DAT; exit 1; }
echo "── candidate hosts in servers.dat ──"
HOSTS=$(strings "$SRV" | grep -oE '[A-Za-z0-9.-]+\.[A-Za-z]{2,}(:[0-9]+)?' | sort -u | head -12)
echo "$HOSTS"
echo "── TCP probes ──"
for h in $HOSTS; do
  host="${h%%:*}"
  port="${h##*:}"
  [ "$port" = "$h" ] && port=443
  if timeout 5 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null; then
    echo "TCP OK   $host:$port"
  else
    echo "TCP FAIL $host:$port"
  fi
done
echo NET_PROBE_DONE
