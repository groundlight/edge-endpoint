#!/usr/bin/env bash
set -euo pipefail

HOSTNAME=${1:-api.groundlight.ai}
PORT=443

echo "Resolving $HOSTNAME ..."
IPS=$(getent ahosts "$HOSTNAME" | awk '{print $1}' | sort -u)
if [ -z "$IPS" ]; then
  echo "Failed to resolve $HOSTNAME" >&2
  exit 1
fi

for ip in $IPS; do
  echo "Removing DROP rule for $ip:$PORT (if present)"
  sudo iptables -D OUTPUT -p tcp -d "$ip" --dport "$PORT" -j DROP || true
done

echo "Outage disabled for $HOSTNAME"

