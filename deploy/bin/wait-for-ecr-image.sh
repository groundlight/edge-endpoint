#!/bin/bash

# Poll until an ECR image tag exists (e.g. after cross-account replication).
# Uses ecr-image-digest.sh so only Image/RepositoryNotFound count as missing.
#
# Usage:
#   ECR_ACCOUNT=... ECR_REGION=... ECR_REPOSITORY=edge/edge-endpoint \
#     ./wait-for-ecr-image.sh
#
# Environment variables:
#   ECR_REPOSITORY: required repository name (e.g. edge/edge-endpoint)
#   ECR_ACCOUNT: optional registry id passed to ecr-image-digest.sh
#   ECR_REGION: AWS region (default us-west-2)
#   ECR_IMAGE_TAG: tag to wait for (default: ./git-tag-name.sh)
#   WAIT_TIMEOUT_SECONDS: poll budget (default 600)
#   WAIT_POLL_SECONDS: sleep between polls (default 10)

set -euo pipefail

cd "$(dirname "$0")"

ECR_REPOSITORY="${ECR_REPOSITORY:?ECR_REPOSITORY must be set}"
ECR_REGION="${ECR_REGION:-us-west-2}"
ECR_IMAGE_TAG="${ECR_IMAGE_TAG:-$(./git-tag-name.sh)}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-600}"
WAIT_POLL_SECONDS="${WAIT_POLL_SECONDS:-10}"
REGISTRY_ID="${ECR_ACCOUNT:-}"

deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
echo "Waiting up to ${WAIT_TIMEOUT_SECONDS}s for ${ECR_REPOSITORY}:${ECR_IMAGE_TAG} (account=${REGISTRY_ID:-caller})..."

while true; do
  digest=$(./ecr-image-digest.sh "${ECR_REPOSITORY}" "${ECR_IMAGE_TAG}" "${REGISTRY_ID}")
  if [ -n "${digest}" ]; then
    echo "Tag present for ${ECR_REPOSITORY}:${ECR_IMAGE_TAG} (${digest})"
    exit 0
  fi
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "Timed out waiting for ${ECR_REPOSITORY}:${ECR_IMAGE_TAG}" >&2
    exit 1
  fi
  echo "Still missing: ${ECR_REPOSITORY}:${ECR_IMAGE_TAG}"
  sleep "${WAIT_POLL_SECONDS}"
done
