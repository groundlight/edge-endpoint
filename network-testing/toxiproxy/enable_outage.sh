#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

MODE="blackhole"       # refuse|blackhole
BH_MS=30000
BH_STREAM="up"       # up|down|both

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-refuse}"; shift 2;;
    --blackhole-ms)
      BH_MS="${2:-30000}"; shift 2;;
    --blackhole-stream)
      BH_STREAM="${2:-both}"; shift 2;;
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

# Validate BH_STREAM
case "${BH_STREAM}" in
  up|down|both) ;;
  *) echo "Invalid --blackhole-stream value: ${BH_STREAM}. Use one of: up|down|both" >&2; exit 1;;
esac

create_or_update_timeout_toxic() {
  local NAME="$1"; local STREAM="$2"; local TIMEOUT_MS="$3"
  local CODE
  CODE=$(run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics" '{"name":"'"${NAME}"'","type":"timeout","stream":"'"${STREAM}"'","attributes":{"timeout":'"${TIMEOUT_MS}"'}}')
  if [[ ! "${CODE}" =~ ^(200|201)$ ]]; then
    CODE=$(run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/${NAME}" '{"attributes":{"timeout":'"${TIMEOUT_MS}"'}}')
  fi
  [[ "${CODE}" =~ ^(200|201)$ ]]
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
    echo "Enabling blackhole outage via timeout toxics: ${BH_MS}ms on ${BH_STREAM} stream(s)"
    if [[ "${BH_STREAM}" == "up" || "${BH_STREAM}" == "both" ]]; then
      create_or_update_timeout_toxic outage_timeout_up upstream "${BH_MS}" || { echo "Failed to ensure upstream timeout toxic" >&2; exit 1; }
    else
      run_curl_code DELETE "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/outage_timeout_up" >/dev/null || true
    fi
    if [[ "${BH_STREAM}" == "down" || "${BH_STREAM}" == "both" ]]; then
      create_or_update_timeout_toxic outage_timeout_down downstream "${BH_MS}" || { echo "Failed to ensure downstream timeout toxic" >&2; exit 1; }
    else
      run_curl_code DELETE "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/outage_timeout_down" >/dev/null || true
    fi
    echo "Outage enabled: connections will hang up to ${BH_MS}ms on ${BH_STREAM}."
    ;;
  *)
    echo "Invalid --mode '${MODE}'. Use refuse|blackhole" >&2
    exit 1
    ;;
esac

