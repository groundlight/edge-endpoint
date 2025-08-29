#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

MODE="refuse"         # refuse|blackhole
UP_MS=5000             # how long cloud is reachable
DOWN_MS=5000           # how long cloud is unreachable
BH_MS=30000            # blackhole timeout to apply when down
ITERATIONS=2           # 0 = infinite until Ctrl+C

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:-refuse}"; shift 2;;
    --up-ms) UP_MS="${2:-5000}"; shift 2;;
    --down-ms) DOWN_MS="${2:-5000}"; shift 2;;
    --blackhole-ms) BH_MS="${2:-30000}"; shift 2;;
    --iterations) ITERATIONS="${2:-0}"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

KNS="-n ${DEPLOYMENT_NAMESPACE}"

if ! kubectl get svc toxiproxy ${KNS} >/dev/null 2>&1; then
  echo "Toxiproxy is not installed in namespace ${DEPLOYMENT_NAMESPACE}. Run enable_toxiproxy.sh first." >&2
  exit 1
fi

sleep_ms() { awk -v ms="$1" 'BEGIN { printf "%.3f\n", ms/1000 }' | xargs sleep; }

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

create_or_update_timeout_toxic() {
  local NAME="$1"; local STREAM="$2"; local TIMEOUT_MS="$3"
  local CODE
  CODE=$(run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics" '{"name":"'"${NAME}"'","type":"timeout","stream":"'"${STREAM}"'","attributes":{"timeout":'"${TIMEOUT_MS}"'}}')
  if [[ ! "${CODE}" =~ ^(200|201)$ ]]; then
    CODE=$(run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/${NAME}" '{"attributes":{"timeout":'"${TIMEOUT_MS}"'}}')
  fi
  [[ "${CODE}" =~ ^(200|201)$ ]] || return 1
}

cleanup() {
  if [[ "${MODE}" == "refuse" ]]; then
    run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai" '{"enabled": true}' >/dev/null
  else
    run_curl_code DELETE "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/outage_timeout_up" >/dev/null
    run_curl_code DELETE "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/outage_timeout_down" >/dev/null
  fi
  echo; echo "Flapping stopped. Cleaned up."
}
trap cleanup INT TERM

echo "Starting outage flapping: mode=${MODE} up=${UP_MS}ms down=${DOWN_MS}ms (blackhole-ms=${BH_MS})"

COUNT=0
while :; do
  # UP period (normal)
  if [[ "${MODE}" == "refuse" ]]; then
    run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai" '{"enabled": true}' >/dev/null
  else
    # Ensure timeout toxics removed during UP
    run_curl_code DELETE "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/outage_timeout_up" >/dev/null
    run_curl_code DELETE "http://toxiproxy:8474/proxies/api_groundlight_ai/toxics/outage_timeout_down" >/dev/null
  fi
  echo -n "."; sleep_ms "${UP_MS}"

  # DOWN period (outage)
  if [[ "${MODE}" == "refuse" ]]; then
    run_curl_code POST "http://toxiproxy:8474/proxies/api_groundlight_ai" '{"enabled": false}' >/dev/null
  else
    create_or_update_timeout_toxic outage_timeout_up upstream "${BH_MS}" || true
    create_or_update_timeout_toxic outage_timeout_down downstream "${BH_MS}" || true
  fi
  echo -n "x"; sleep_ms "${DOWN_MS}"

  if [[ "${ITERATIONS}" -gt 0 ]]; then
    COUNT=$((COUNT+1))
    if [[ "${COUNT}" -ge "${ITERATIONS}" ]]; then
      break
    fi
  fi
done

cleanup
