#!/usr/bin/env bash
set -euo pipefail

# Enable the "outage" toxic on proxy "gl".
# Usage: ./enable_outage.sh [namespace]

NAMESPACE=${1:-edge}

echo "Enabling outage toxic in namespace=${NAMESPACE}"
kubectl -n "$NAMESPACE" run toxiproxy-curl --rm -i --restart=Never --image=curlimages/curl:8.9.1 --command -- sh -c \
  "curl -sX POST http://toxiproxy:8474/proxies/gl/toxics/outage -H 'Content-Type: application/json' -d '{\"enabled\":true}' || true"

echo "Outage toxic enabled."

