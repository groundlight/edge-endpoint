#!/usr/bin/env bash
set -euo pipefail

# Show current Toxiproxy proxies and toxics in the namespace.
# Usage: ./status.sh [namespace]

NAMESPACE=${1:-edge}

echo "[status] Proxies in namespace=${NAMESPACE}"
kubectl -n "$NAMESPACE" run toxiproxy-curl --rm -i --restart=Never --image=curlimages/curl:8.9.1 --command -- sh -c \
  "curl -s http://toxiproxy:8474/proxies || true"

echo
echo "[status] Toxics for proxy 'gl' (if exists)"
kubectl -n "$NAMESPACE" run toxiproxy-curl --rm -i --restart=Never --image=curlimages/curl:8.9.1 --command -- sh -c \
  "curl -s http://toxiproxy:8474/proxies/gl/toxics || true"

