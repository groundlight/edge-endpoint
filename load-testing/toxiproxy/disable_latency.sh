#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

KNS="-n ${DEPLOYMENT_NAMESPACE}"

echo "Removing latency toxics if present"

# Ensure toxiproxy service exists
if ! kubectl get svc toxiproxy ${KNS} >/dev/null 2>&1; then
  echo "Toxiproxy service not found in namespace ${DEPLOYMENT_NAMESPACE}. Nothing to remove."
  exit 0
fi

# Helper to run curl inside a short-lived pod and print only the HTTP code
run_curl_code() {
  local METHOD="$1"; shift
  local URL="$1"; shift
  local PODNAME="curl-tmp-$(date +%s)-$RANDOM"
  # Start a short-lived pod without --rm so we can fetch clean logs
  kubectl run "${PODNAME}" ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
    -sS -o /dev/null -w '%{http_code}\n' -X "${METHOD}" "${URL}" >/dev/null 2>&1 || true

  # Wait until pod finishes (Succeeded/Failed) up to ~15s
  for i in $(seq 1 30); do
    PHASE=$(kubectl get pod "${PODNAME}" ${KNS} -o jsonpath='{.status.phase}' 2>/dev/null || true)
    if [[ "${PHASE}" == "Succeeded" || "${PHASE}" == "Failed" ]]; then
      break
    fi
    sleep 0.5
  done
  # Read the single-line curl output from logs
  local OUT
  OUT=$(kubectl logs "${PODNAME}" ${KNS} 2>/dev/null || true)
  # Cleanup pod
  kubectl delete pod "${PODNAME}" ${KNS} --now --wait=false >/dev/null 2>&1 || true

  echo "${OUT}" | grep -oE '^[0-9]{3}$' || echo ""
}

for name in fixed_latency_up fixed_latency_down; do
  CODE=$(run_curl_code DELETE "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/${name}")
  case "${CODE}" in
    200|204)
      echo "Toxic ${name} removed."
      ;;
    404)
      echo "Toxic ${name} was not present."
      ;;
    *)
      echo "Toxic ${name}: unexpected response code ${CODE}."
      ;;
  esac
done
