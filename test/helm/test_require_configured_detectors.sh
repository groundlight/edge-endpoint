#!/usr/bin/env bash
# Render-time assertions for the requireConfiguredDetectors value, which the edge-endpoint uses to
# reject unlisted detectors and the inference-model-updater uses to delete their inference pods.
# No cluster required — only helm template.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="${ROOT}/deploy/helm/groundlight-edge-endpoint"
TOKEN="dummy-token"

fail=0
pass=0

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

container() { awk -v c="$1" '$0 == "      - name: " c {f = 1; print; next} /^      - name: / {f = 0} f' <<<"$2"; }
env_var() { printf -- '- name: REQUIRE_CONFIGURED_DETECTORS\n          value: "%s"' "$1"; }

out="$(render)"
assert_contains "edge-endpoint requires configured detectors by default" "$(container edge-endpoint "$out")" "$(env_var true)"
assert_contains "updater requires configured detectors by default" "$(container inference-model-updater "$out")" "$(env_var true)"

out="$(render --set requireConfiguredDetectors=false)"
assert_contains "edge-endpoint accepts unlisted detectors" "$(container edge-endpoint "$out")" "$(env_var false)"
assert_contains "updater keeps unlisted detectors' pods" "$(container inference-model-updater "$out")" "$(env_var false)"

echo
echo "Passed: $pass  Failed: $fail"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "All requireConfiguredDetectors render assertions passed."
