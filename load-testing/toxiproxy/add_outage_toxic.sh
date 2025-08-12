#!/usr/bin/env bash
set -euo pipefail

# Create a timeout toxic named "outage" on proxy "gl" (downstream). Default 45000 ms.
# Usage: ./add_outage_toxic.sh [namespace] [timeout_ms]

NAMESPACE=${1:-edge}
TIMEOUT_MS=${2:-45000}

echo "Adding outage toxic (timeout=${TIMEOUT_MS}ms) in namespace=${NAMESPACE}"
kubectl -n "$NAMESPACE" run toxiproxy-curl --rm -i --restart=Never --image=curlimages/curl:8.9.1 --command -- sh -c \
  "curl -sX POST http://toxiproxy:8474/proxies/gl/toxics \
    -H 'Content-Type: application/json' \
    -d '{\"name\":\"outage\",\"type\":\"timeout\",\"stream\":\"downstream\",\"attributes\":{\"timeout\":$TIMEOUT_MS}}' || true"

echo "Done. Use enable_outage.sh / disable_outage.sh to toggle it."

