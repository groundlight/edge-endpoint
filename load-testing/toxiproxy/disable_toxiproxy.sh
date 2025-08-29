#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

KNS="-n ${DEPLOYMENT_NAMESPACE}"

echo "[1/3] Removing hostAliases from edge-endpoint Deployment (if present)"
set +e
kubectl patch deploy edge-endpoint ${KNS} --type json -p '[
  {"op":"remove","path":"/spec/template/spec/hostAliases"}
]' >/dev/null 2>&1 || true
set -e

echo "[2/3] Deleting Toxiproxy resources"
kubectl delete ${KNS} -f "$(dirname "$0")/k8s-toxiproxy.yaml" --ignore-not-found

echo "[3/3] Waiting for edge-endpoint rollout"
kubectl rollout restart deploy/edge-endpoint ${KNS}
kubectl rollout status deploy/edge-endpoint ${KNS} --timeout=120s

echo "Done. Traffic is no longer routed through Toxiproxy."
