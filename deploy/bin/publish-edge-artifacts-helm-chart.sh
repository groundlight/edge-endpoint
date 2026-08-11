#!/bin/bash

# Package and push the edge-endpoint Helm chart to Axon edge-artifacts ECR as OCI.
#
# Usage (CI on main, after OIDC assume of oidc-ghec-edge-push):
#   EDGE_ECR_URL=794562053834.dkr.ecr.us-west-2.amazonaws.com \
#     ./publish-edge-artifacts-helm-chart.sh
#
# Pushes to oci://${EDGE_ECR_URL}/edge/<chart-name>:<git-tag>, using
# ./git-tag-name.sh (same as edge-endpoint images). Packages as
# 0.0.0-<git-tag> because Helm requires SemVer, then aliases that ECR tag to
# <git-tag>. Skips if <git-tag> already exists.
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
# Account id is the first label of the ECR hostname (NNNN.dkr.ecr...).
ECR_ACCOUNT="${EDGE_ECR_URL%%.*}"

CHART_NAME=$(helm show chart "${CHART_PATH}" | awk '/^name:/ { print $2; exit }')
if [ -z "${CHART_NAME}" ]; then
  echo "Failed to read chart name from ${CHART_PATH}" >&2
  exit 1
fi

# Canonical Axon OCI tag: git revision (matches edge-endpoint image tags).
OCI_TAG=$(./git-tag-name.sh)
# Helm package --version must be SemVer; wrap the git tag as a prerelease.
HELM_VERSION="0.0.0-${OCI_TAG}"

REPO_NAME="edge/${CHART_NAME}"
OCI_REF="oci://${EDGE_ECR_URL}/${REPO_NAME}:${OCI_TAG}"
HELM_OCI_REF="oci://${EDGE_ECR_URL}/${REPO_NAME}:${HELM_VERSION}"

# Return 0 if the ECR tag exists, 1 if not found, exit on other AWS errors.
ecr_tag_exists() {
  local tag=$1
  local out rc
  set +e
  out=$(aws ecr describe-images \
    --region "${ECR_REGION}" \
    --repository-name "${REPO_NAME}" \
    --image-ids "imageTag=${tag}" 2>&1)
  rc=$?
  set -e
  if [ "${rc}" -eq 0 ]; then
    return 0
  fi
  if echo "${out}" | grep -Eq 'ImageNotFoundException|RepositoryNotFoundException'; then
    return 1
  fi
  echo "${out}" >&2
  exit 1
}

if ecr_tag_exists "${OCI_TAG}"; then
  echo "${OCI_REF} already published; skipping."
  exit 0
fi

WORKDIR=$(mktemp -d)
trap 'rm -rf "${WORKDIR}"' EXIT

helm package "${CHART_PATH}" \
  --destination "${WORKDIR}" \
  --dependency-update \
  --version "${HELM_VERSION}"
CHART_PKG=$(find "${WORKDIR}" -maxdepth 1 -name '*.tgz' | head -n 1)
if [ -z "${CHART_PKG}" ]; then
  echo "helm package did not produce a .tgz in ${WORKDIR}" >&2
  exit 1
fi

aws ecr get-login-password --region "${ECR_REGION}" | \
  helm registry login --username AWS --password-stdin "${EDGE_ECR_URL}"

if ! ecr_tag_exists "${HELM_VERSION}"; then
  helm push "${CHART_PKG}" "oci://${EDGE_ECR_URL}/edge"
  echo "Successfully pushed Helm chart to ${HELM_OCI_REF}"
else
  echo "${HELM_OCI_REF} already present; aliasing to ${OCI_TAG}"
fi

ECR_ACCOUNT="${ECR_ACCOUNT}" ECR_REGION="${ECR_REGION}" SOURCE_TAG="${HELM_VERSION}" \
  ./tag-edge-artifacts-helm-chart.sh "${OCI_TAG}"
echo "Successfully published Helm chart to ${OCI_REF}"
