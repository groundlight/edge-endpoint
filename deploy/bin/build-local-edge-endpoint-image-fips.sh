#!/bin/bash

# FIPS local k3s import. Same mechanics as build-local-edge-endpoint-image.sh
# (Dockerfile.fips, Chainguard auth). Defaults to the Axon-dev image name so
# the tag matches Helm for api.groundlight.dev.axon.com and the registry stays
# the FIPS boundary. Override for GL_Public naming:
#   ECR_ACCOUNT=767397850842 EDGE_ENDPOINT_IMAGE=edge-endpoint \
#     ./deploy/bin/build-local-edge-endpoint-image-fips.sh

set -e

cd "$(dirname "$0")"

export DOCKERFILE="${DOCKERFILE:-Dockerfile.fips}"
export ECR_ACCOUNT="${ECR_ACCOUNT:-216731772508}"
export EDGE_ENDPOINT_IMAGE="${EDGE_ENDPOINT_IMAGE:-edge/edge-endpoint}"
exec ./build-local-edge-endpoint-image.sh
