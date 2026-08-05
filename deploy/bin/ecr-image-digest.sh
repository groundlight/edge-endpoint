#!/bin/bash

# Print the ECR image digest for a repository tag, or nothing if the tag is
# missing. Only Image/RepositoryNotFoundException count as missing; other AWS
# errors fail loudly.
#
# Usage:
#   ./ecr-image-digest.sh <repository> <tag> [registry-id]
#
# Environment variables:
#   ECR_REGION: AWS region (default us-west-2)
#
# Examples:
#   ./ecr-image-digest.sh edge/edge-endpoint abc123def-main
#   ./ecr-image-digest.sh edge-endpoint abc123def-main 767397850842

set -euo pipefail

REPO="${1:?repository is required}"
TAG="${2:?tag is required}"
REGISTRY_ID="${3:-}"
ECR_REGION="${ECR_REGION:-us-west-2}"

describe_args=(
  --region "${ECR_REGION}"
  --repository-name "${REPO}"
  --image-ids "imageTag=${TAG}"
  --query 'imageDetails[0].imageDigest'
  --output text
)
if [ -n "${REGISTRY_ID}" ]; then
  describe_args+=(--registry-id "${REGISTRY_ID}")
fi

set +e
out=$(aws ecr describe-images "${describe_args[@]}" 2>&1)
rc=$?
set -e

if [ "${rc}" -eq 0 ] && [ -n "${out}" ] && [ "${out}" != "None" ]; then
  echo "${out}"
  exit 0
fi
if echo "${out}" | grep -Eq 'ImageNotFoundException|RepositoryNotFoundException'; then
  exit 0
fi
echo "${out}" >&2
exit 1
