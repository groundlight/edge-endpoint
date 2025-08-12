#!/usr/bin/env bash
set -euo pipefail

# Remove the "outage" toxic from proxy "gl" (if present).
# Usage: ./remove_outage_toxic.sh [namespace]

NAMESPACE=${1:-edge}

echo "Removing outage toxic in namespace=${NAMESPACE}"
kubectl -n "$NAMESPACE" run toxiproxy-curl --rm -i --restart=Never --image=curlimages/curl:8.9.1 --command -- sh -c \
  "curl -sX DELETE http://toxiproxy:8474/proxies/gl/toxics/outage || true"

echo "Outage toxic removed."

