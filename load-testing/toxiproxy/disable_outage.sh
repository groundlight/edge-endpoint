#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

KNS="-n ${DEPLOYMENT_NAMESPACE}"

if ! kubectl get svc toxiproxy ${KNS} >/dev/null 2>&1; then
  echo "Toxiproxy is not installed in namespace ${DEPLOYMENT_NAMESPACE}." >&2
  exit 0
fi

run_curl_code() {
  local METHOD="$1"; shift
  local URL="$1"; shift
  local BODY="${1:-}"; [[ $# -gt 0 ]] && shift || true
  local PODNAME="curl-tmp-$(date +%s)-$RANDOM"
  if [[ -n "${BODY}" ]]; then
    kubectl run "${PODNAME}" ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
      -sS -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' -X "${METHOD}" -d "${BODY}" "${URL}" >/dev/null 2>&1 || true
  else
    kubectl run "${PODNAME}" ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
      -sS -o /dev/null -w '%{http_code}\n' -X "${METHOD}" "${URL}" >/dev/null 2>&1 || true
  fi
  for i in $(seq 1 30); do
    PHASE=$(kubectl get pod "${PODNAME}" ${KNS} -o jsonpath='{.status.phase}' 2>/dev/null || true)
    if [[ "${PHASE}" == "Succeeded" || "${PHASE}" == "Failed" ]]; then
      break
    fi
    sleep 0.3
  done
  local OUT
  OUT=$(kubectl logs "${PODNAME}" ${KNS} 2>/dev/null || true)
  kubectl delete pod "${PODNAME}" ${KNS} --now --wait=false >/dev/null 2>&1 || true
  echo "${OUT}" | grep -oE '^[0-9]{3}$' || echo ""
}

# Re-enable proxy (if it was disabled)
CODE=$(run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai" '{"enabled": true}')
if [[ ! "${CODE}" =~ ^(200|201)$ ]]; then
  echo "Warning: could not enable proxy (HTTP ${CODE})."
fi

# Remove timeout toxics if present
for name in outage_timeout_up outage_timeout_down; do
  CODE=$(run_curl_code DELETE "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/${name}")
  case "${CODE}" in
    200|204) echo "Removed ${name}.";;
    404) echo "${name} not present.";;
    *) echo "Unexpected response removing ${name}: HTTP ${CODE}";;
  esac
done

echo "Outage disabled."

