#!/usr/bin/env bash
# Render-time assertions for the gpuSharing value (CUDA MPS for Triton inference pods).
# No cluster required — only helm template.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="${ROOT}/deploy/helm/groundlight-edge-endpoint"
TOKEN="dummy-token"
IMAGE="767397850842.dkr.ecr.us-west-2.amazonaws.com/gl-edge-inference"
PIPE="/run/groundlight/mps/pipe"

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

# Everything up to the inference template ConfigMap's end, and the MPS daemon manifests on their own.
inference_template() { awk '/^  inference_deployment_template.yaml: \|/ {f = 1} f && /^---/ {exit} f' <<<"$1"; }
updater() { awk '/^      - name: inference-model-updater$/ {f = 1; print; next} /^      - name: / {f = 0} f' <<<"$1"; }

out="$(render --set inferenceServer=triton)"
assert_contains "none is the default annotation" "$(inference_template "$out")" 'groundlight.dev/gpu-sharing: "none"'
assert_not_contains "no MPS env by default" "$out" "CUDA_MPS_PIPE_DIRECTORY"
assert_not_contains "no MPS daemon by default" "$out" "mps-control-daemon"
assert_contains "updater knows sharing is off" "$(updater "$out")" $'name: GPU_SHARING\n          value: "none"'

out="$(render --set inferenceServer=triton --set gpuSharing=mps)"
template="$(inference_template "$out")"
assert_contains "mps pod annotation" "$template" 'groundlight.dev/gpu-sharing: "mps"'
assert_contains "mps pipe directory env" "$template" $'- name: CUDA_MPS_PIPE_DIRECTORY\n              value: '"${PIPE}"
assert_contains "mps client limit env" "$template" $'- name: GL_MPS_MAX_CLIENTS_PER_GPU\n              value: "44"'
assert_contains "mps pipe mount" "$template" $'- mountPath: '"${PIPE}"$'\n              name: mps-pipe'
assert_contains "triton keeps its private /dev/shm" "$template" "sizeLimit: 256Mi"
assert_contains "updater knows sharing is mps" "$(updater "$out")" $'name: GPU_SHARING\n          value: "mps"'
assert_contains "mps daemon DaemonSet" "$out" $'kind: DaemonSet\nmetadata:\n  name: edge-endpoint-mps-control-daemon'
assert_contains "daemon is never rolled by helm" "$out" $'updateStrategy:\n    type: OnDelete'
assert_contains "daemon uses the triton image" "$out" "image: ${IMAGE}:abc123-main-triton"$'\n        imagePullPolicy'
assert_contains "daemon pipe directory" "$out" $'- name: CUDA_MPS_PIPE_DIRECTORY\n          value: "'"${PIPE}"'"'
assert_contains "daemon is x86_64 only" "$out" $'nodeSelector:\n        kubernetes.io/arch: amd64'
assert_not_contains "never the toolkit's default pipe directory" "$out" "/tmp/nvidia-mps"

out="$(render --set inferenceServer=triton --set gpuSharing=mps --set mps.hostDirectory=/var/run/mps/ --set mps.maxClientsPerGpu=20)"
assert_contains "custom host directory" "$out" $'- name: CUDA_MPS_PIPE_DIRECTORY\n          value: "/var/run/mps/pipe"'
assert_contains "custom client limit" "$out" $'- name: GL_MPS_MAX_CLIENTS_PER_GPU\n              value: "20"'

# mps only applies to Triton pods on x86_64 GPU devices; elsewhere it renders as none, without failing.
for args in "--set inferenceServer=fastapi" "--set inferenceServer=triton --set inferenceFlavor=cpu" \
  "--set inferenceServer=fastapi --set inferenceTag=jetson"; do
  # shellcheck disable=SC2086
  out="$(render --set gpuSharing=mps $args)"
  assert_contains "mps falls back to none ($args)" "$(inference_template "$out")" 'groundlight.dev/gpu-sharing: "none"'
  assert_not_contains "no MPS daemon ($args)" "$out" "kind: DaemonSet"$'\nmetadata:\n  name: edge-endpoint-mps-control-daemon'
  assert_contains "updater gets none ($args)" "$(updater "$out")" $'name: GPU_SHARING\n          value: "none"'
done

assert_render_fails "unknown sharing" 'gpuSharing must be "none" or "mps"' --set gpuSharing=mig

# A --reuse-values upgrade from a chart without these values renders them as unset.
out="$(render --set inferenceServer=triton --set gpuSharing=null --set mps=null)"
assert_contains "unset gpuSharing means none" "$(inference_template "$out")" 'groundlight.dev/gpu-sharing: "none"'
assert_render_fails "mps without the mps values" "use --reset-then-reuse-values" \
  --set inferenceServer=triton --set gpuSharing=mps --set mps=null

echo
echo "Passed: $pass  Failed: $fail"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "All gpuSharing render assertions passed."
