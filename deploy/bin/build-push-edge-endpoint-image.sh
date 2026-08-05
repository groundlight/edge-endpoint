#!/bin/bash

# This script builds and pushes the edge-endpoint Docker image to ECR.
#
# Usage:
#   ./build-push-edge-endpoint-image.sh
#
# The script does the following:
# 1. Sets the image tag based on the current git commit.
# 2. Authenticates Docker with ECR.
# 3. Builds a multi-platform Docker image once and pushes it.
# 4. When EDGE_ECR_URL is set (CI on main) and the immutable edge tag is
#    absent, the same buildx invocation also tags that image into
#    edge/edge-endpoint in the Axon edge-artifacts master ECR.
# 5. When the edge tag already exists, does not rebuild. If GL_Public already
#    points at the same digest, skips. Otherwise copies the edge artifact to
#    GL_Public with buildx imagetools (digest-preserving).
#
# Environment variables:
#   EDGE_ECR_URL: If set, also publish to edge/<image> in that registry when
#                 the tag is not already present. Set by CI on main; empty
#                 otherwise.
#   EDGE_EXISTING_DIGEST: Optional. Set by CI on main after an aws ecr
#                 describe-images of edge/edge-endpoint:<tag> while OIDC edge
#                 credentials are still active. Non-empty means the immutable
#                 edge tag already exists with that digest.
#
# Note: Ensure you have the necessary AWS credentials and Docker installed.

ECR_ACCOUNT=${ECR_ACCOUNT:-767397850842}
ECR_REGION=${ECR_REGION:-us-west-2}

set -euo pipefail

# Ensure that you're in the same directory as this script before running it
cd "$(dirname "$0")"

TAG=$(./git-tag-name.sh)

EDGE_ENDPOINT_IMAGE=${EDGE_ENDPOINT_IMAGE:-edge-endpoint}  # v0.2.0 (fastapi inference server) compatible images
ECR_URL="${ECR_ACCOUNT}.dkr.ecr.${ECR_REGION}.amazonaws.com"
GL_PUBLIC_IMG="${ECR_URL}/${EDGE_ENDPOINT_IMAGE}:${TAG}"

# Authenticate docker to ECR
aws ecr get-login-password --region ${ECR_REGION} | docker login \
                  --username AWS \
                  --password-stdin  ${ECR_URL}

if [ "${1:-}" == "dev" ]; then
  echo "'$0 dev' is no longer supported!!"
  exit 1
fi

# We use docker buildx to build the image for multiple platforms. buildx comes
# installed with Docker Engine when installed via Docker Desktop. If you're
# on a Linux machine with an old version of Docker Engine, you may need to
# install buildx manually. Follow these instructions to install docker-buildx-plugin:
# https://docs.docker.com/engine/install/ubuntu/

# Install QEMU, a generic and open-source machine emulator and virtualizer
docker run --rm --privileged linuxkit/binfmt:af88a591f9cc896a52ce596b9cf7ca26a061ef97

# Check if tempbuilder already exists
if ! docker buildx ls | grep -q tempgroundlightedgebuilder; then
  # Prep for multiplatform build - the build is done INSIDE a docker container
  docker buildx create --name tempgroundlightedgebuilder --use
else
  # If tempbuilder exists, set it as the current builder
  docker buildx use tempgroundlightedgebuilder
fi

# Ensure that the tempbuilder container is running
docker buildx inspect tempgroundlightedgebuilder --bootstrap

if [ -n "${EDGE_ECR_URL:-}" ]; then
  EDGE_IMG_NAME="${EDGE_ECR_URL}/edge/${EDGE_ENDPOINT_IMAGE}:${TAG}"
  # Populated by CI while OIDC edge credentials were still active. Empty means
  # the immutable edge tag is absent (or this is a non-CI dual-publish attempt).
  EDGE_DIGEST="${EDGE_EXISTING_DIGEST:-}"

  if [ -n "${EDGE_DIGEST}" ]; then
    # Immutable edge tag already exists: never rebuild (that would diverge digests).
    GL_DIGEST=$(./ecr-image-digest.sh "${EDGE_ENDPOINT_IMAGE}" "${TAG}" "${ECR_ACCOUNT}")
    if [ "${GL_DIGEST}" = "${EDGE_DIGEST}" ]; then
      echo "${EDGE_IMG_NAME} and ${GL_PUBLIC_IMG} already present with matching digest ${EDGE_DIGEST}; skipping."
      exit 0
    fi

    echo "${EDGE_IMG_NAME} already present (${EDGE_DIGEST}); copying to ${GL_PUBLIC_IMG} without rebuild."
    docker buildx imagetools create --tag "${GL_PUBLIC_IMG}" "${EDGE_IMG_NAME}"
    GL_DIGEST_AFTER=$(./ecr-image-digest.sh "${EDGE_ENDPOINT_IMAGE}" "${TAG}" "${ECR_ACCOUNT}")
    if [ -z "${GL_DIGEST_AFTER}" ] || [ "${GL_DIGEST_AFTER}" != "${EDGE_DIGEST}" ]; then
      echo "Failed to align GL_Public with edge digest after imagetools create." >&2
      echo "  edge:      ${EDGE_DIGEST}" >&2
      echo "  GL_Public: ${GL_DIGEST_AFTER:-<missing>}" >&2
      exit 1
    fi
    echo "Successfully aligned ${GL_PUBLIC_IMG} to ${EDGE_DIGEST}"
    exit 0
  fi

  # Fresh dual-publish: one buildx invocation, two tags, same artifact digest.
  docker buildx build \
    --platform linux/arm64,linux/amd64 \
    --tag "${GL_PUBLIC_IMG}" \
    --tag "${EDGE_IMG_NAME}" \
    ../.. --push

  echo "Successfully pushed image to ECR_URL=${ECR_URL}"
  echo "${GL_PUBLIC_IMG}"
  echo "Successfully pushed image to EDGE_ECR_URL=${EDGE_ECR_URL}"
  echo "${EDGE_IMG_NAME}"
  exit 0
fi

# PR / non-main: GL_Public only.
docker buildx build \
  --platform linux/arm64,linux/amd64 \
  --tag "${GL_PUBLIC_IMG}" \
  ../.. --push

echo "Successfully pushed image to ECR_URL=${ECR_URL}"
echo "${GL_PUBLIC_IMG}"
