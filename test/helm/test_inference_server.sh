#!/usr/bin/env bash
# Render-time assertions for the inferenceServer value (FastAPI or Triton inference pods).
# No cluster required — only helm template.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="${ROOT}/deploy/helm/groundlight-edge-endpoint"
TOKEN="dummy-token"
IMAGE="767397850842.dkr.ecr.us-west-2.amazonaws.com/gl-edge-inference"

fail=0
pass=0

if [[ ! -d "${CHART}/charts" ]] || [[ -z "$(ls -A "${CHART}/charts" 2>/dev/null || true)" ]]; then
  echo "Fetching chart dependencies..."
  helm dependency update "$CHART"
fi

render() {
  helm template test "$CHART" --set "groundlightApiToken=${TOKEN}" --set inferenceTag=abc123-main "$@"
}

# Needles may span lines, so match a literal substring: grep -F would split them into OR'd patterns.
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

assert_not_contains() {
  local label="$1" haystack="$2" needle="$3"
  if [[ $haystack == *"$needle"* ]]; then
    echo "FAIL $label: unexpected '$needle'"
    fail=$((fail + 1))
  else
    echo "OK  $label"
    pass=$((pass + 1))
  fi
}

assert_render_fails() {
  local label="$1" expected="$2"
  shift 2
  local err
  if err="$(render "$@" 2>&1)"; then
    echo "FAIL $label: expected helm template to fail"
    fail=$((fail + 1))
  elif grep -qF -- "$expected" <<<"$err"; then
    echo "OK  $label"
    pass=$((pass + 1))
  else
    echo "FAIL $label: failed without '$expected':"
    echo "$err" | tail -5
    fail=$((fail + 1))
  fi
}

out="$(render)"
assert_contains "fastapi is the default image" "$out" "image: ${IMAGE}:abc123-main"$'\n'
assert_contains "fastapi readiness probe" "$out" "path: /health/ready  # Checks if the server is ready"
assert_contains "fastapi pod annotation" "$out" 'groundlight.dev/inference-server: "fastapi"'
assert_not_contains "fastapi has no Triton metrics port" "$out" "containerPort: 8002"
assert_not_contains "fastapi has no shared-memory volume" "$out" "name: dshm"

out="$(render --set inferenceServer=triton)"
assert_contains "triton image tag" "$out" "image: ${IMAGE}:abc123-main-triton"
assert_contains "triton liveness probe" "$out" "path: /v2/health/live"
assert_contains "triton readiness probe" "$out" "path: /v2/health/ready  # Checks if the server is ready"
assert_contains "triton metrics port" "$out" "containerPort: 8002"
assert_contains "triton shared-memory volume" "$out" "sizeLimit: 256Mi"
assert_contains "triton pod annotation" "$out" 'groundlight.dev/inference-server: "triton"'
assert_contains "edge-endpoint knows the configured server" "$out" $'name: INFERENCE_SERVER\n          value: "triton"'
updater="$(awk '/^      - name: inference-model-updater$/ {f = 1; print; next} /^      - name: / {f = 0} f' <<<"$out")"
assert_contains "model updater knows the configured server" "$updater" $'name: INFERENCE_SERVER\n          value: "triton"'

out="$(render --set inferenceTag=jetson)"
assert_contains "jetson renders on fastapi" "$out" "image: ${IMAGE}:jetson"$'\n'

# `helm upgrade --reuse-values` from a chart that predates these settings keeps the old values
# without this chart's defaults; null removes a value the same way.
out="$(render --set inferenceServer=null)"
assert_contains "missing inferenceServer means fastapi" "$out" "image: ${IMAGE}:abc123-main"$'\n'
assert_contains "missing inferenceServer: fastapi annotation" "$out" 'groundlight.dev/inference-server: "fastapi"'
assert_contains "missing inferenceServer: edge-endpoint gets fastapi" "$out" $'name: INFERENCE_SERVER\n          value: "fastapi"'
out="$(render --set inferenceServer=triton --set inferenceDeployment.tritonShmSizeLimit=null)"
assert_contains "missing tritonShmSizeLimit defaults to 256Mi" "$out" "sizeLimit: 256Mi"

assert_render_fails "unknown server" 'inferenceServer must be "fastapi" or "triton"' --set inferenceServer=grpc
assert_render_fails "triton has no minimal image" "has no minimal image" \
  --set inferenceServer=triton --set useMinimalImage=true
assert_render_fails "triton has no Jetson image" "has no Jetson image" \
  --set inferenceServer=triton --set inferenceTag=jetson

echo
echo "Passed: $pass  Failed: $fail"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "All inferenceServer render assertions passed."
