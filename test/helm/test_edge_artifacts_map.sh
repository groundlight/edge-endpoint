#!/usr/bin/env bash
# Render-time assertions for edgeArtifactsMap / upstreamEndpoint resolution.
# No cluster required — only helm template.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="${ROOT}/deploy/helm/groundlight-edge-endpoint"
TOKEN="dummy-token"

GL_PUBLIC_REG="767397850842.dkr.ecr.us-west-2.amazonaws.com"
AXON_DEV_REG="216731772508.dkr.ecr.us-west-2.amazonaws.com/edge"
AXON_USA_REG="686194638722.dkr.ecr.us-east-1.amazonaws.com/edge"
GL_PUBLIC_BUCKET="pinamod-artifacts-public"
AXON_DEV_BUCKET="edge-model-artifacts-edgemodelartifactsdevreplicabucket131ac6fa"
AXON_USA_BUCKET="edge-model-artifac-edgemodelartifactsusslgreplicabucket0f431ed4"

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
  if grep -qF -- "$needle" <<<"$haystack"; then
    echo "OK  $label"
    pass=$((pass + 1))
  else
    echo "FAIL $label: missing '$needle'"
    fail=$((fail + 1))
  fi
}

assert_render_fails() {
  local label="$1"
  shift
  local err
  if err="$(render "$@" 2>&1)"; then
    echo "FAIL $label: expected helm template to fail"
    fail=$((fail + 1))
  else
    if grep -qE 'not a recognized Groundlight API URL|must be an absolute HTTP' <<<"$err"; then
      echo "OK  $label"
      pass=$((pass + 1))
    else
      echo "FAIL $label: failed, but without expected error message:"
      echo "$err" | tail -5
      fail=$((fail + 1))
    fi
  fi
}

assert_gl_public() {
  local label="$1" out="$2"
  assert_contains "$label registry" "$out" "${GL_PUBLIC_REG}/edge-endpoint:release"
  assert_contains "$label inference" "$out" "${GL_PUBLIC_REG}/gl-edge-inference:release"
  assert_contains "$label bucket" "$out" "value: \"${GL_PUBLIC_BUCKET}\""
  assert_contains "$label schedule" "$out" 'schedule: "0 * * * *"'
  assert_contains "$label v2" "$out" "reader-credentials/v2"
  assert_contains "$label ecr login region" "$out" "get-login-password --region us-west-2"
}

assert_axon_dev() {
  local label="$1" out="$2"
  assert_contains "$label registry" "$out" "${AXON_DEV_REG}/edge-endpoint:latest"
  assert_contains "$label inference" "$out" "${AXON_DEV_REG}/gl-edge-inference:latest"
  assert_contains "$label docker-server host" "$out" "docker-server=216731772508.dkr.ecr.us-west-2.amazonaws.com"
  if grep -qF 'docker-server=216731772508.dkr.ecr.us-west-2.amazonaws.com/edge' <<<"$out"; then
    echo "FAIL $label: docker-server unexpectedly includes /edge prefix"
    fail=$((fail + 1))
  else
    echo "OK  $label docker-server has no /edge prefix"
    pass=$((pass + 1))
  fi
  assert_contains "$label bucket" "$out" "value: \"${AXON_DEV_BUCKET}\""
  assert_contains "$label schedule" "$out" 'schedule: "*/15 * * * *"'
  assert_contains "$label v2" "$out" "reader-credentials/v2"
  assert_contains "$label ecr login region" "$out" "get-login-password --region us-west-2"
}

assert_axon_usa() {
  local label="$1" out="$2"
  assert_contains "$label registry" "$out" "${AXON_USA_REG}/edge-endpoint:latest"
  assert_contains "$label inference" "$out" "${AXON_USA_REG}/gl-edge-inference:latest"
  assert_contains "$label docker-server host" "$out" "docker-server=686194638722.dkr.ecr.us-east-1.amazonaws.com"
  if grep -qF 'docker-server=686194638722.dkr.ecr.us-east-1.amazonaws.com/edge' <<<"$out"; then
    echo "FAIL $label: docker-server unexpectedly includes /edge prefix"
    fail=$((fail + 1))
  else
    echo "OK  $label docker-server has no /edge prefix"
    pass=$((pass + 1))
  fi
  assert_contains "$label bucket" "$out" "value: \"${AXON_USA_BUCKET}\""
  assert_contains "$label s3 region" "$out" 'value: "us-east-1"'
  assert_contains "$label schedule" "$out" 'schedule: "*/15 * * * *"'
  assert_contains "$label v2" "$out" "reader-credentials/v2"
  assert_contains "$label ecr login region" "$out" "get-login-password --region us-east-1"
}

echo "=== edgeArtifactsMap helm template matrix ==="

out="$(render)"
assert_gl_public "default" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.ai)"
assert_gl_public "prod canonical" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.ai/)"
assert_gl_public "prod trailing slash" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.ai/device-api)"
assert_gl_public "prod /device-api path" "$out"

out="$(render --set upstreamEndpoint=https://api.integ.groundlight.ai)"
assert_gl_public "integ" "$out"

out="$(render --set upstreamEndpoint=https://api.dev.groundlight.ai)"
assert_gl_public "api.dev.groundlight.ai" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.dev.axon.com)"
assert_axon_dev "AG1 canonical" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.dev.axon.com/)"
assert_axon_dev "AG1 trailing slash" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.dev.axon.com/device-api/)"
assert_axon_dev "AG1 /device-api path" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.usa.axon.com)"
assert_axon_usa "usa canonical" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.usa.axon.com/)"
assert_axon_usa "usa trailing slash" "$out"

out="$(render --set upstreamEndpoint=https://api.groundlight.usa.axon.com/device-api/)"
assert_axon_usa "usa /device-api path" "$out"

out="$(render \
  --set upstreamEndpoint=https://api.groundlight.dev.axon.com \
  --set ecrRegistry=999999999999.dkr.ecr.us-west-2.amazonaws.com/custom \
  --set imageTag=mytag \
  --set s3Mount.bucket=my-bucket \
  --set s3Mount.region=us-east-1)"
assert_contains "scalar override registry" "$out" "999999999999.dkr.ecr.us-west-2.amazonaws.com/custom/edge-endpoint:mytag"
assert_contains "scalar override bucket" "$out" 'value: "my-bucket"'
assert_contains "scalar override region" "$out" 'value: "us-east-1"'
# Schedule still comes from the AG1 map entry
assert_contains "scalar override keeps AG1 schedule" "$out" 'schedule: "*/15 * * * *"'

out="$(render \
  --set upstreamEndpoint=https://api.groundlight.dev.axon.com \
  --set ecrRegistry=999999999999.dkr.ecr-fips.us-east-1.amazonaws.com/custom)"
assert_contains "ecr-fips override region" "$out" "get-login-password --region us-east-1"

out="$(render \
  --set upstreamEndpoint=https://api.groundlight.dev.axon.com \
  --set ecrRegistry=ghcr.io/custom)"
assert_contains "non-ECR override falls back to awsRegion default" "$out" "get-login-password --region us-west-2"

out="$(render \
  --set upstreamEndpoint=https://api.groundlight.dev.axon.com \
  --set ecrRegistry=ghcr.io/custom \
  --set awsRegion=eu-west-1)"
assert_contains "non-ECR override falls back to explicit awsRegion" "$out" "get-login-password --region eu-west-1"

assert_render_fails "unknown host" --set upstreamEndpoint=https://api.example.invalid
assert_render_fails "lookalike host" --set upstreamEndpoint=https://api.groundlight.dev.axon.com.evil.example
assert_render_fails "typo host" --set upstreamEndpoint=https://apii.groundlight.dev.axon.com
assert_render_fails "usa lookalike host" --set upstreamEndpoint=https://api.groundlight.usa.axon.com.evil.example
assert_render_fails "malformed URL" --set upstreamEndpoint=not-a-url

echo
echo "Passed: $pass  Failed: $fail"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "All edgeArtifactsMap render assertions passed."
