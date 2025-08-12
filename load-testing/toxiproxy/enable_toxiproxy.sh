#!/usr/bin/env bash
set -euo pipefail

# Requires:
# - kubectl context pointing at the target cluster
# - DEPLOYMENT_NAMESPACE set to the namespace where edge endpoint is installed

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

KNS="-n ${DEPLOYMENT_NAMESPACE}"

echo "[1/5] Ensuring namespace exists: ${DEPLOYMENT_NAMESPACE}"
kubectl get ns "${DEPLOYMENT_NAMESPACE}" >/dev/null 2>&1 || kubectl create ns "${DEPLOYMENT_NAMESPACE}"

echo "[2/5] Deploying Toxiproxy"
kubectl apply ${KNS} -f "$(dirname "$0")/k8s-toxiproxy.yaml"

echo "[3/5] Waiting for Toxiproxy pod to be Ready"
kubectl wait ${KNS} --for=condition=Available deploy/toxiproxy --timeout=90s

echo "[4/5] Creating/Updating Toxiproxy proxy for api.groundlight.ai:443"
# Use an in-cluster curl pod to reach the ClusterIP service
kubectl run --rm -i curl-tmp ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
  -sS -X POST http://toxiproxy:8474/proxies \
  -H 'Content-Type: application/json' \
  -d '{"name":"api_groundlight_ai","listen":"0.0.0.0:10443","upstream":"api.groundlight.ai:443","enabled":true}' || true

kubectl run --rm -i curl-tmp ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
  -sS -X POST http://toxiproxy:8474/proxies/api_groundlight_ai \
  -H 'Content-Type: application/json' \
  -d '{"upstream":"api.groundlight.ai:443","enabled":true}' >/dev/null

echo "[5/5] Patching edge-endpoint Deployment hostAliases to direct api.groundlight.ai to Toxiproxy"
SVC_IP=$(kubectl get svc toxiproxy ${KNS} -o jsonpath='{.spec.clusterIP}')
kubectl patch deploy edge-endpoint ${KNS} --type merge -p "{\"spec\":{\"template\":{\"spec\":{\"hostAliases\":[{\"ip\":\"${SVC_IP}\",\"hostnames\":[\"api.groundlight.ai\"]}]}}}}"

echo "Waiting for rollout to complete..."
kubectl rollout status deploy/edge-endpoint ${KNS} --timeout=120s

echo "Done enabling Toxiproxy."
