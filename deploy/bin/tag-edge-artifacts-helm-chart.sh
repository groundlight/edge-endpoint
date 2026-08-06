#!/bin/bash

# Point a mutable tag (e.g. latest) at an existing OCI Helm chart tag in ECR.
# Used in the **dev** edge-artifacts account after master→dev replication.
# Master stays version-tagged only; environment pointers live in deployment
# registries (same model as edge-endpoint image `latest` tagging).
#
# Usage:
#   ECR_ACCOUNT=216731772508 ./tag-edge-artifacts-helm-chart.sh latest
#
# Environment variables:
#   ECR_ACCOUNT: AWS account ID of the registry (required)
#   ECR_REGION: Region of the registry (default us-west-2)
#   CHART_PATH: Chart directory relative to this script
#     (default ../helm/groundlight-edge-endpoint)
#   SOURCE_TAG: Tag to retarget from (default: Chart.yaml version)

set -euo pipefail

cd "$(dirname "$0")"

if [ $# -ne 1 ]; then
  echo "Usage: $0 <new-tag>" >&2
  exit 1
fi

NEW_TAG=$1
ECR_ACCOUNT="${ECR_ACCOUNT:?ECR_ACCOUNT must be set}"
ECR_REGION="${ECR_REGION:-us-west-2}"
CHART_PATH="${CHART_PATH:-../helm/groundlight-edge-endpoint}"

# Only CI may move environment-pointer tags.
if [[ "${NEW_TAG}" == "latest" ]]; then
  if [ -z "${GITHUB_ACTIONS:-}" ]; then
    echo "Error: The tag '${NEW_TAG}' can only be used inside GitHub Actions." >&2
    exit 1
  fi
fi

CHART_NAME=$(awk '/^name:/ { print $2; exit }' "${CHART_PATH}/Chart.yaml")
CHART_VERSION=$(awk '/^version:/ { print $2; exit }' "${CHART_PATH}/Chart.yaml")
SOURCE_TAG="${SOURCE_TAG:-${CHART_VERSION}}"
REPO_NAME="edge/${CHART_NAME}"

if [ -z "${CHART_NAME}" ] || [ -z "${SOURCE_TAG}" ]; then
  echo "Failed to read chart name/version from ${CHART_PATH}/Chart.yaml" >&2
  exit 1
fi

echo "Tagging ${REPO_NAME}:${NEW_TAG} from ${REPO_NAME}:${SOURCE_TAG} (account=${ECR_ACCOUNT})"

IMAGE_JSON=$(aws ecr batch-get-image \
  --registry-id "${ECR_ACCOUNT}" \
  --region "${ECR_REGION}" \
  --repository-name "${REPO_NAME}" \
  --image-ids "imageTag=${SOURCE_TAG}" \
  --output json)

MANIFEST=$(echo "${IMAGE_JSON}" | jq -r '.images[0].imageManifest // empty')
MEDIA_TYPE=$(echo "${IMAGE_JSON}" | jq -r '.images[0].imageManifestMediaType // empty')

if [ -z "${MANIFEST}" ]; then
  echo "No image found for ${REPO_NAME}:${SOURCE_TAG}" >&2
  echo "${IMAGE_JSON}" >&2
  exit 1
fi

put_args=(
  --registry-id "${ECR_ACCOUNT}"
  --region "${ECR_REGION}"
  --repository-name "${REPO_NAME}"
  --image-tag "${NEW_TAG}"
  --image-manifest "${MANIFEST}"
)
if [ -n "${MEDIA_TYPE}" ] && [ "${MEDIA_TYPE}" != "null" ]; then
  put_args+=(--image-manifest-media-type "${MEDIA_TYPE}")
fi

set +e
PUT_OUT=$(aws ecr put-image "${put_args[@]}" 2>&1)
PUT_RC=$?
set -e

if [ "${PUT_RC}" -eq 0 ]; then
  echo "Tagged ${REPO_NAME}:${NEW_TAG} at the same digest as ${SOURCE_TAG}"
  exit 0
fi
if echo "${PUT_OUT}" | grep -q 'ImageAlreadyExistsException'; then
  echo "${REPO_NAME}:${NEW_TAG} already points at this digest; skipping."
  exit 0
fi
echo "${PUT_OUT}" >&2
exit 1
