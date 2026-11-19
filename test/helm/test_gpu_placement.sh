#!/usr/bin/env bash
# Render-time assertions for the GPU placement ledger that Triton inference pods on GPU devices share.
# No cluster required — only helm template.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="${ROOT}/deploy/helm/groundlight-edge-endpoint"
TOKEN="dummy-token"
LEDGER="/run/groundlight/gpu-placement"

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

inference_template() { awk '/^  inference_deployment_template.yaml: \|/ {f = 1} f && /^---/ {exit} f' <<<"$1"; }
updater() { awk '/^      - name: inference-model-updater$/ {f = 1; print; next} /^      - name: / {f = 0} f' <<<"$1"; }

assert_uses_ledger() {
  local label="$1" out="$2"
  local template
  template="$(inference_template "$out")"
  assert_contains "ledger annotation ($label)" "$template" 'groundlight.dev/gpu-placement: "ledger"'
  assert_contains "ledger directory env ($label)" "$template" \
    $'- name: GL_GPU_PLACEMENT_DIRECTORY\n              value: '"${LEDGER}"$'\n'
  assert_contains "ledger mount ($label)" "$template" $'- mountPath: '"${LEDGER}"$'\n              name: gpu-placement'
  assert_contains "ledger hostPath ($label)" "$template" \
    $'- hostPath:\n              path: '"${LEDGER}"$'\n              type: DirectoryOrCreate\n            name: gpu-placement'
  assert_contains "updater knows the ledger is on ($label)" "$(updater "$out")" \
    $'name: GPU_PLACEMENT\n          value: "ledger"'
}

assert_no_ledger() {
  local label="$1" out="$2"
  local template
  template="$(inference_template "$out")"
  assert_contains "no ledger annotation ($label)" "$template" 'groundlight.dev/gpu-placement: "none"'
  assert_not_contains "no ledger env ($label)" "$template" "GL_GPU_PLACEMENT_DIRECTORY"
  assert_not_contains "no ledger volume ($label)" "$template" "name: gpu-placement"
  assert_not_contains "no ledger hostPath ($label)" "$template" "$LEDGER"
  assert_contains "updater knows the ledger is off ($label)" "$(updater "$out")" \
    $'name: GPU_PLACEMENT\n          value: "none"'
}

# The ledger spreads time-sliced pods too, so it doesn't depend on gpuSharing.
assert_uses_ledger "triton" "$(render --set inferenceServer=triton)"
out="$(render --set inferenceServer=triton --set gpuSharing=mps)"
assert_uses_ledger "triton with mps" "$out"
assert_contains "mps still mounts its pipe directory" "$(inference_template "$out")" "name: mps-pipe"

for args in "" "--set inferenceServer=fastapi" "--set inferenceServer=triton --set inferenceFlavor=cpu" \
  "--set inferenceServer=fastapi --set inferenceTag=jetson" \
  "--set inferenceServer=triton --set hostPathVolumes=false" \
  "--set inferenceServer=triton --set inferenceDeployment.hostPID=false"; do
  # shellcheck disable=SC2086
  assert_no_ledger "${args:-defaults}" "$(render $args)"
done

# The shared-cluster flavor forbids hostPath and hostPID, so its Triton pods place their instances on their own.
out="$(render -f "${CHART}/values-eks.yaml" --set inferenceServer=triton \
  --set upstreamEndpoint=http://janzu.test.svc.cluster.local \
  --set edgeArtifactsProfile=https://api.dev.groundlight.ai \
  --set sharedModelRepo.storageClassName=efs-test \
  --set inferenceDeployment.modelsVolume.emptyDir="{}")"
assert_no_ledger "eks flavor" "$out"
assert_not_contains "eks flavor: no hostPath in inference pods" "$(inference_template "$out")" "hostPath:"

# A --reuse-values upgrade from a chart without hostPathVolumes or inferenceDeployment.hostPID renders them as unset.
assert_uses_ledger "unset hostPathVolumes and hostPID" \
  "$(render --set inferenceServer=triton --set hostPathVolumes=null --set inferenceDeployment.hostPID=null)"

echo
echo "Passed: $pass  Failed: $fail"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "All GPU placement render assertions passed."
