#!/bin/bash

# Package and push the edge-endpoint Helm chart to Axon edge-artifacts ECR as OCI.
#
# Usage (CI on main, after OIDC assume of oidc-ghec-edge-push):
#   EDGE_ECR_URL=794562053834.dkr.ecr.us-west-2.amazonaws.com \
#     ./publish-edge-artifacts-helm-chart.sh
#
# Pushes to oci://${EDGE_ECR_URL}/edge → edge/<chart-name>:<version>.
# Chart.yaml version is the immutable OCI tag. If that tag already exists,
# compare packaged chart contents to the published artifact: skip when they
# match; fail loudly when they differ (bump Chart.yaml version and re-release).
#
# Environment variables:
#   EDGE_ECR_URL: Registry host (required), e.g. 794562053834.dkr.ecr.us-west-2.amazonaws.com
#   ECR_REGION: AWS region (default us-west-2)
#   CHART_PATH: Chart directory relative to this script (default ../helm/groundlight-edge-endpoint)

set -euo pipefail

cd "$(dirname "$0")"

EDGE_ECR_URL="${EDGE_ECR_URL:?EDGE_ECR_URL must be set}"
ECR_REGION="${ECR_REGION:-us-west-2}"
CHART_PATH="${CHART_PATH:-../helm/groundlight-edge-endpoint}"

CHART_NAME=$(helm show chart "${CHART_PATH}" | awk '/^name:/ { print $2; exit }')
CHART_VERSION=$(helm show chart "${CHART_PATH}" | awk '/^version:/ { print $2; exit }')
if [ -z "${CHART_NAME}" ] || [ -z "${CHART_VERSION}" ]; then
  echo "Failed to read chart name/version from ${CHART_PATH}" >&2
  exit 1
fi

REPO_NAME="edge/${CHART_NAME}"
OCI_REF="oci://${EDGE_ECR_URL}/${REPO_NAME}:${CHART_VERSION}"

WORKDIR=$(mktemp -d)
trap 'rm -rf "${WORKDIR}"' EXIT

helm package "${CHART_PATH}" --destination "${WORKDIR}" --dependency-update
CHART_PKG=$(find "${WORKDIR}" -maxdepth 1 -name '*.tgz' | head -n 1)
if [ -z "${CHART_PKG}" ]; then
  echo "helm package did not produce a .tgz in ${WORKDIR}" >&2
  exit 1
fi

aws ecr get-login-password --region "${ECR_REGION}" | \
  helm registry login --username AWS --password-stdin "${EDGE_ECR_URL}"

set +e
DESCRIBE_OUT=$(aws ecr describe-images \
  --region "${ECR_REGION}" \
  --repository-name "${REPO_NAME}" \
  --image-ids "imageTag=${CHART_VERSION}" 2>&1)
DESCRIBE_RC=$?
set -e

if [ "${DESCRIBE_RC}" -ne 0 ]; then
  if echo "${DESCRIBE_OUT}" | grep -Eq 'ImageNotFoundException|RepositoryNotFoundException'; then
    helm push "${CHART_PKG}" "oci://${EDGE_ECR_URL}/edge"
    echo "Successfully pushed Helm chart to ${OCI_REF}"
    exit 0
  fi
  echo "${DESCRIBE_OUT}" >&2
  exit 1
fi

# Tag exists: pull and compare extracted chart trees (tgz digests can differ
# due to archive metadata even when contents match).
EXISTING_DIR="${WORKDIR}/existing"
mkdir -p "${EXISTING_DIR}"
helm pull "oci://${EDGE_ECR_URL}/edge/${CHART_NAME}" \
  --version "${CHART_VERSION}" \
  --destination "${EXISTING_DIR}"
EXISTING_PKG=$(find "${EXISTING_DIR}" -maxdepth 1 -name '*.tgz' | head -n 1)
if [ -z "${EXISTING_PKG}" ]; then
  echo "helm pull of ${OCI_REF} did not produce a .tgz" >&2
  exit 1
fi

LOCAL_TREE="${WORKDIR}/local-tree"
EXISTING_TREE="${WORKDIR}/existing-tree"
mkdir -p "${LOCAL_TREE}" "${EXISTING_TREE}"
tar -xzf "${CHART_PKG}" -C "${LOCAL_TREE}"
tar -xzf "${EXISTING_PKG}" -C "${EXISTING_TREE}"

if diff -rq "${LOCAL_TREE}" "${EXISTING_TREE}" >/dev/null; then
  echo "${OCI_REF} already present with matching chart contents; skipping."
  exit 0
fi

echo "Refusing to skip: ${OCI_REF} already exists with different chart contents." >&2
echo "Bump Chart.yaml version (and appVersion if needed) before publishing." >&2
echo "Diff:" >&2
diff -rq "${LOCAL_TREE}" "${EXISTING_TREE}" >&2 || true
exit 1
