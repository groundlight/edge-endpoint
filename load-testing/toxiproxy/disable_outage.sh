#!/usr/bin/env bash
set -euo pipefail

# Disable the "outage" toxic on proxy "gl".
# Usage: ./disable_outage.sh [namespace]

NAMESPACE=${1:-edge}

echo "Disabling outage toxic in namespace=${NAMESPACE}"
kubectl -n "$NAMESPACE" run toxiproxy-curl --rm -i --restart=Never --image=curlimages/curl:8.9.1 --command -- sh -c \
  "curl -sX POST http://toxiproxy:8474/proxies/gl/toxics/outage -H 'Content-Type: application/json' -d '{\"enabled\":false}' || true"

echo "Outage toxic disabled."

