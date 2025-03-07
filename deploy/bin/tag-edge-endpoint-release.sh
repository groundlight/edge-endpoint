#!/bin/bash

# Put a specific tag on an existing image in ECR
# Assumptions:
# - The image is already built and pushed to ECR
# - The image is tagged with the git commit hash

set -e  # Exit immediately on error
set -o pipefail

ECR_ACCOUNT=${ECR_ACCOUNT:-767397850842}
ECR_REGION=${ECR_REGION:-us-west-2}

# Ensure that you're in the same directory as this script before running it
cd "$(dirname "$0")"

# Check if an argument is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <new-tag>"
    exit 1
fi

NEW_TAG=$1

# Only the pipeline can create releases
if [[ "$NEW_TAG" == "pre-release" || "$NEW_TAG" == "release" ]]; then
    if [ -z "$GITHUB_ACTIONS" ]; then
        echo "Error: The tag '$NEW_TAG' can only be used inside GitHub Actions."
        exit 1
    fi
fi

GIT_TAG=$(./git-tag-name.sh)
EDGE_ENDPOINT_IMAGE=${EDGE_ENDPOINT_IMAGE:-edge-endpoint}  # v0.2.0 (fastapi inference server) compatible images
ECR_URL="${ECR_ACCOUNT}.dkr.ecr.${ECR_REGION}.amazonaws.com"
ECR_REPO="${ECR_URL}/${EDGE_ENDPOINT_IMAGE}"

# Authenticate docker to ECR
aws ecr get-login-password --region ${ECR_REGION} | docker login \
                  --username AWS \
                  --password-stdin  ${ECR_URL}

echo "📥 Pulling image: $ECR_REPO:$GIT_TAG"
docker pull $ECR_REPO:$GIT_TAG

# Tag the image with the new tag
echo "🏷️ Tagging image as: $ECR_REPO:$NEW_TAG"
docker tag $ECR_REPO:$GIT_TAG $ECR_REPO:$NEW_TAG

# Push the newly tagged image
echo "🚀 Pushing image: $ECR_REPO:$NEW_TAG"
docker push $ECR_REPO:$NEW_TAG

echo "✅ Image successfully retagged and pushed: $ECR_REPO:$NEW_TAG"
