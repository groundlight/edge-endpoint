#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

MODE="refuse"       # refuse|blackhole
BH_MS=$((24*60*60*1000))  # default 1 day for blackhole

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-refuse}"; shift 2;;
    --blackhole-ms)
      BH_MS="${2:-86400000}"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

KNS="-n ${DEPLOYMENT_NAMESPACE}"

if ! kubectl get svc toxiproxy ${KNS} >/dev/null 2>&1; then
  echo "Toxiproxy is not installed in namespace ${DEPLOYMENT_NAMESPACE}. Run enable_toxiproxy.sh first." >&2
  exit 1
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

case "${MODE}" in
  refuse)
    CODE=$(run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai" '{"enabled": false}')
    if [[ "${CODE}" =~ ^(200|201)$ ]]; then
      echo "Outage enabled: proxy disabled (connections will be refused)."
    else
      echo "Failed to disable proxy. HTTP ${CODE}" >&2
      exit 1
    fi
    ;;
  blackhole)
    echo "Enabling blackhole outage via timeout toxics: ${BH_MS}ms on both streams"
    CODE=$(run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics" '{"name":"outage_timeout_up","type":"timeout","stream":"upstream","attributes":{"timeout":'"${BH_MS}"'}}')
    [[ "${CODE}" =~ ^(200|201)$ ]] || { echo "Failed to add upstream timeout toxic. HTTP ${CODE}" >&2; exit 1; }
    CODE=$(run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics" '{"name":"outage_timeout_down","type":"timeout","stream":"downstream","attributes":{"timeout":'"${BH_MS}"'}}')
    [[ "${CODE}" =~ ^(200|201)$ ]] || { echo "Failed to add downstream timeout toxic. HTTP ${CODE}" >&2; exit 1; }
    echo "Outage enabled: connections will hang up to ${BH_MS}ms."
    ;;
  *)
    echo "Invalid --mode '${MODE}'. Use refuse|blackhole" >&2
    exit 1
    ;;
esac

