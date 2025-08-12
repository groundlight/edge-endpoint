#!/usr/bin/env bash
set -euo pipefail

# Blocks egress to api.groundlight.ai:443 with iptables DROP rules.

HOSTNAME=${1:-api.groundlight.ai}
PORT=443

echo "Resolving $HOSTNAME ..."
IPS=$(getent ahosts "$HOSTNAME" | awk '{print $1}' | sort -u)
if [ -z "$IPS" ]; then
  echo "Failed to resolve $HOSTNAME" >&2
  exit 1
fi

for ip in $IPS; do
  echo "Adding DROP rule for $ip:$PORT"
  sudo iptables -I OUTPUT -p tcp -d "$ip" --dport "$PORT" -j DROP
done

echo "Outage enabled for $HOSTNAME on port $PORT. To remove, run disable_outage_linux.sh"

