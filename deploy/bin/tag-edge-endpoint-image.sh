#!/bin/bash

# Put a specific tag on an existing image in ECR.
# Assumptions:
# - The image is already built and pushed to ECR
# - The image is tagged with the git commit hash
#
# Environment variables:
#   ECR_ACCOUNT: AWS account ID of the registry (default: legacy GL_Public 767397850842)
#   ECR_REGION: Region of the registry (default: us-west-2)
#   ECR_REPOSITORY_PREFIX: Optional repository path prefix. Use "edge/" for
#     Axon edge-artifacts registries (master or deployment accounts).
#   EDGE_ENDPOINT_IMAGE: Image/repository basename (default: edge-endpoint)

set -e  # Exit immediately on error
set -o pipefail

ECR_ACCOUNT=${ECR_ACCOUNT:-767397850842}
ECR_REGION=${ECR_REGION:-us-west-2}
ECR_REPOSITORY_PREFIX=${ECR_REPOSITORY_PREFIX:-}

# Ensure that you're in the same directory as this script before running it
cd "$(dirname "$0")"

# Check if an argument is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <new-tag>"
    exit 1
fi

NEW_TAG=$1

# Only the pipeline can create releases
if [[ "$NEW_TAG" == "pre-release" || "$NEW_TAG" == "release" || "$NEW_TAG" == "latest" ]]; then
    if [ -z "$GITHUB_ACTIONS" ]; then
        echo "Error: The tag '$NEW_TAG' can only be used inside GitHub Actions."
        exit 1
    fi
fi

GIT_TAG=$(./git-tag-name.sh)
EDGE_ENDPOINT_IMAGE=${EDGE_ENDPOINT_IMAGE:-edge-endpoint}  # v0.2.0 (fastapi inference server) compatible images
ECR_URL="${ECR_ACCOUNT}.dkr.ecr.${ECR_REGION}.amazonaws.com"
ECR_REPO="${ECR_URL}/${ECR_REPOSITORY_PREFIX}${EDGE_ENDPOINT_IMAGE}"

# Authenticate docker to ECR
aws ecr get-login-password --region ${ECR_REGION} | docker login \
                  --username AWS \
                  --password-stdin  ${ECR_URL}

# Tag the image with the new tag
# To do this, we need to pull the digest SHA of the existing multiplatform image
# and then create the tag on that SHA. Otherwise imagetools will create a tag for
# just the platform where the command is run.
echo "🏷️ Tagging image $ECR_REPO:$GIT_TAG with tag $NEW_TAG"
digest=$(docker buildx imagetools inspect $ECR_REPO:$GIT_TAG --format '{{json .}}' | jq -r .manifest.digest)
docker buildx imagetools create --tag $ECR_REPO:$NEW_TAG $ECR_REPO@${digest}

echo "✅ Image successfully tagged: $ECR_REPO:$NEW_TAG"
