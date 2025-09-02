#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

KNS="-n ${DEPLOYMENT_NAMESPACE}"

if ! kubectl get svc toxiproxy ${KNS} >/dev/null 2>&1; then
  echo "Toxiproxy is not installed in namespace ${DEPLOYMENT_NAMESPACE}."
  exit 0
fi

run_curl_code() {
  local METHOD="$1"; shift
  local URL="$1"; shift
  local PODNAME="curl-tmp-$(date +%s)-$RANDOM"
  kubectl run "${PODNAME}" ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
    -sS -o /dev/null -w '%{http_code}\n' -X "${METHOD}" "${URL}" >/dev/null 2>&1 || true
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

run_curl_body() {
  local METHOD="$1"; shift
  local URL="$1"; shift
  local PODNAME="curl-tmp-$(date +%s)-$RANDOM"
  kubectl run "${PODNAME}" ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
    -sS -X "${METHOD}" "${URL}" >/dev/null 2>&1 || true
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
  echo "${OUT}"
}

CODE=$(run_curl_code GET "http://toxiproxy:8474/proxies/api_groundlight_ai")
if [[ "${CODE}" == "404" ]]; then
  echo "Proxy 'api_groundlight_ai' not found. Run enable_toxiproxy.sh first."
  exit 0
fi

BODY=$(run_curl_body GET "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics")

if [[ -z "${BODY}" ]]; then
  echo "No response from Toxiproxy admin API."
  exit 1
fi

# Summarize toxics present
echo "Current toxics on api_groundlight_ai:"

names=($(echo "${BODY}" | grep -oE '"name"\s*:\s*"[^"]+"' | sed 's/.*:\s*"\([^"]*\)"/\1/'))
types=($(echo "${BODY}" | grep -oE '"type"\s*:\s*"[^"]+"' | sed 's/.*:\s*"\([^"]*\)"/\1/'))
streams=($(echo "${BODY}" | grep -oE '"stream"\s*:\s*"[^"]+"' | sed 's/.*:\s*"\([^"]*\)"/\1/'))

if [[ ${#names[@]} -eq 0 ]]; then
  echo "- none"
else
  for i in "${!names[@]}"; do
    n="${names[$i]}"; t="${types[$i]:-?}"; s="${streams[$i]:-?}"
    echo "- ${n} (type=${t}, stream=${s})"
  done
fi

echo
echo "Raw JSON:" 
echo "${BODY}"

