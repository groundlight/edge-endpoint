#!/usr/bin/env bash
# Render-time assertions for the uvicornWorkers, nginxWorkerConnections, and
# inferenceDeployment.workers values.
# No cluster required — only helm template.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="${ROOT}/deploy/helm/groundlight-edge-endpoint"
TOKEN="dummy-token"

fail=0
pass=0

# CI checkouts do not include charts/; fetch Chart.yaml dependencies once.
if [[ ! -d "${CHART}/charts" ]] || [[ -z "$(ls -A "${CHART}/charts" 2>/dev/null || true)" ]]; then
  echo "Fetching chart dependencies..."
  helm dependency update "$CHART"
fi

render() {
  helm template test "$CHART" --set "groundlightApiToken=${TOKEN}" "$@"
}

assert_contains() {
  local label="$1" haystack="$2" needle="$3"
  if [[ $haystack == *"$needle"* ]]; then
    echo "OK  $label"
    pass=$((pass + 1))
  else
    echo "FAIL $label: missing '$needle'"
    fail=$((fail + 1))
  fi
}

EDGE_ENDPOINT_PORT_ARGS='"--host", "0.0.0.0", "--port", "6718"'
STATUS_MONITOR_CMD='"--workers", "1", "--host", "0.0.0.0", "--port", "8123"'

# The inference pod template renders into a ConfigMap, so match the env var and its value together.
inference_workers_env() {
  printf 'name: WORKERS  # Number of uvicorn workers for the inference server\n              value: "%s"' "$1"
}

out="$(render)"
assert_contains "default uvicorn workers" "$out" "\"--workers\", \"8\", ${EDGE_ENDPOINT_PORT_ARGS}"
assert_contains "default nginx worker_connections" "$out" "worker_connections 256;"
assert_contains "default inference workers" "$out" "$(inference_workers_env 1)"

out="$(render --set uvicornWorkers=3 --set nginxWorkerConnections=1024 --set inferenceDeployment.workers=4)"
assert_contains "uvicornWorkers override" "$out" "\"--workers\", \"3\", ${EDGE_ENDPOINT_PORT_ARGS}"
assert_contains "nginxWorkerConnections override" "$out" "worker_connections 1024;"
assert_contains "inferenceDeployment.workers override" "$out" "$(inference_workers_env 4)"
assert_contains "status monitor keeps one worker" "$out" "$STATUS_MONITOR_CMD"

# `helm upgrade --reuse-values` from a chart that predates these values keeps the old values
# without this chart's defaults; null removes a value the same way.
out="$(render --set uvicornWorkers=null --set nginxWorkerConnections=null --set inferenceDeployment.workers=null)"
assert_contains "missing uvicornWorkers means 8" "$out" "\"--workers\", \"8\", ${EDGE_ENDPOINT_PORT_ARGS}"
assert_contains "missing nginxWorkerConnections means 256" "$out" "worker_connections 256;"
assert_contains "missing inferenceDeployment.workers means 1" "$out" "$(inference_workers_env 1)"

echo
echo "Passed: $pass  Failed: $fail"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "All worker setting render assertions passed."
