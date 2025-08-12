#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOYMENT_NAMESPACE:-}" ]]; then
  echo "ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)" >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <latency_ms> [--jitter <jitter_ms>] [--direction down|up|both]" >&2
  exit 1
fi

LAT_MS="$1"; shift || true
JITTER_MS=0
DIRECTION="down"
if [[ "${1:-}" == "--jitter" ]]; then
  shift
  JITTER_MS="${1:-0}"
  shift || true
fi
if [[ "${1:-}" == "--direction" ]]; then
  shift
  DIRECTION="${1:-down}"
fi

KNS="-n ${DEPLOYMENT_NAMESPACE}"

echo "Adding latency toxic(s): direction=${DIRECTION} latency=${LAT_MS}ms jitter=${JITTER_MS}ms"
case "${DIRECTION}" in
  down)
    kubectl run --rm -i curl-tmp ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
      -sS -X POST http://toxiproxy:8474/proxies/api_groundlight_ai/toxics \
      -H 'Content-Type: application/json' \
      -d "{\"name\": \"fixed_latency_down\", \"type\": \"latency\", \"stream\": \"downstream\", \"attributes\": { \"latency\": ${LAT_MS}, \"jitter\": ${JITTER_MS} } }"
    ;;
  up)
    kubectl run --rm -i curl-tmp ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
      -sS -X POST http://toxiproxy:8474/proxies/api_groundlight_ai/toxics \
      -H 'Content-Type: application/json' \
      -d "{\"name\": \"fixed_latency_up\", \"type\": \"latency\", \"stream\": \"upstream\", \"attributes\": { \"latency\": ${LAT_MS}, \"jitter\": ${JITTER_MS} } }"
    ;;
  both)
    kubectl run --rm -i curl-tmp ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
      -sS -X POST http://toxiproxy:8474/proxies/api_groundlight_ai/toxics \
      -H 'Content-Type: application/json' \
      -d "{\"name\": \"fixed_latency_up\", \"type\": \"latency\", \"stream\": \"upstream\", \"attributes\": { \"latency\": ${LAT_MS}, \"jitter\": ${JITTER_MS} } }"
    kubectl run --rm -i curl-tmp ${KNS} --restart=Never --image=curlimages/curl:8.5.0 -- \
      -sS -X POST http://toxiproxy:8474/proxies/api_groundlight_ai/toxics \
      -H 'Content-Type: application/json' \
      -d "{\"name\": \"fixed_latency_down\", \"type\": \"latency\", \"stream\": \"downstream\", \"attributes\": { \"latency\": ${LAT_MS}, \"jitter\": ${JITTER_MS} } }"
    ;;
  *)
    echo "ERROR: invalid --direction value '${DIRECTION}'. Use down|up|both" >&2
    exit 1
    ;;
esac

echo "Done."
