#!/bin/bash
# Build the FIPS edge-endpoint image and publish it only to Axon master ECR.
#
# Usage:
#   ./build-push-edge-endpoint-image-fips.sh
#
# Counterpart to build-push-edge-endpoint-image.sh (GL_Public, non-FIPS). Separate
# rather than one script with a flag: Dockerfile, registry, credentials, and the
# verification gate all differ. The legacy path stays untouched.
#
#   non-FIPS -> 767397850842.dkr.ecr.us-west-2.amazonaws.com/edge-endpoint
#   FIPS     -> 794562053834.dkr.ecr.us-west-2.amazonaws.com/edge/edge-endpoint
#
# linux/amd64 only, matching gl-edge-inference FIPS (no FIPS-validated Jetson base).
#
# Set FIPS_PUSH=true to push the immutable git-sha tag (CI on main). Without it
# the script builds linux/amd64, runs verify + smoke, and never touches ECR.
# Mutable `latest` is not written here: tag-image-latest-dev.yaml moves
# `latest` in the dest-dev account after master-to-dev replication.
#
# Requires: docker buildx, a cgr.dev login (deploy/bin/ensure-chainguard-auth.sh
# locally; CI uses an OIDC-minted pull token), and when pushing, AWS credentials
# for 794562053834.

set -euxo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"

./ensure-chainguard-auth.sh

TAG=$(./git-tag-name.sh)
if [ -z "$TAG" ]; then
    echo "ERROR: git-tag-name.sh produced an empty tag" >&2
    exit 1
fi

FIPS_ECR_URL="${FIPS_ECR_URL:-794562053834.dkr.ecr.us-west-2.amazonaws.com}"
FIPS_ECR_REGION="${FIPS_ECR_REGION:-us-west-2}"
FIPS_IMAGE_PATH="${FIPS_IMAGE_PATH:-edge/edge-endpoint}"
FULL_REF="${FIPS_ECR_URL}/${FIPS_IMAGE_PATH}:${TAG}"
LOCAL_REF="edge-endpoint-fips-local:${TAG}"

DOCKERFILE="${REPO_ROOT}/Dockerfile.fips"
if [ ! -f "$DOCKERFILE" ]; then
    echo "ERROR: no Dockerfile.fips in ${REPO_ROOT}" >&2
    exit 1
fi

FIPS_PUSH="${FIPS_PUSH:-false}"

if [ "$FIPS_PUSH" = "true" ]; then
    aws ecr get-login-password --region "${FIPS_ECR_REGION}" | docker login \
        --username AWS \
        --password-stdin "${FIPS_ECR_URL}"
fi

if docker buildx inspect tempgroundlightedgebuilder >/dev/null 2>&1; then
    docker buildx use tempgroundlightedgebuilder
else
    docker buildx create --name tempgroundlightedgebuilder --use
fi
docker buildx inspect tempgroundlightedgebuilder --bootstrap

CACHE_DIR="${REPO_ROOT}/.buildx-cache-fips"
mkdir -p "${CACHE_DIR}"

# Published FIPS image is linux/amd64 only (same as gl-edge-inference FIPS).
docker buildx build \
    --platform linux/amd64 \
    --file "${DOCKERFILE}" \
    --tag "${LOCAL_REF}" \
    --cache-from=type=local,src="${CACHE_DIR}" \
    --cache-to=type=local,dest="${CACHE_DIR}",mode=max \
    --load \
    "${REPO_ROOT}"

./verify-fips-image.sh "${LOCAL_REF}" linux/amd64
./smoke-test-fips-image.sh "${LOCAL_REF}" linux/amd64

if [ "$FIPS_PUSH" != "true" ]; then
    set +x
    echo
    echo "Built and verified ${LOCAL_REF} for linux/amd64."
    echo "FIPS_PUSH is not 'true', so nothing was pushed."
    exit 0
fi

if docker buildx imagetools inspect "${FULL_REF}" >/dev/null 2>&1; then
    set +x
    echo
    echo "${FULL_REF} already exists and the tag is immutable; skipping the sha push."
    exit 0
fi

docker tag "${LOCAL_REF}" "${FULL_REF}"
docker push "${FULL_REF}"
echo "Successfully pushed FIPS image ${FULL_REF}"
