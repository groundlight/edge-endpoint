#!/bin/bash

# Look up whether edge/edge-endpoint:<git-tag> already exists in the caller's
# ECR account. When found, write EDGE_EXISTING_DIGEST to GITHUB_ENV (CI).
#
# Run while OIDC edge-push credentials are still active (before GL_Public
# credentials overwrite the AWS env).
#
# Usage:
#   ./lookup-edge-existing-digest.sh

set -euo pipefail

cd "$(dirname "$0")"

TAG=$(./git-tag-name.sh)
REPO="edge/edge-endpoint"
DIGEST=$(./ecr-image-digest.sh "${REPO}" "${TAG}")

if [ -n "${DIGEST}" ]; then
  if [ -n "${GITHUB_ENV:-}" ]; then
    echo "EDGE_EXISTING_DIGEST=${DIGEST}" >> "${GITHUB_ENV}"
  fi
  echo "Found existing ${REPO}:${TAG} (${DIGEST})"
else
  echo "No existing ${REPO}:${TAG}; will dual-publish"
fi
