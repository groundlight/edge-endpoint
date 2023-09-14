#!/bin/bash

set -ex


# Ensure that you're in the same directory as this script before running it
cd "$(dirname "$0")"

TAG=$(./git-tag-name.sh)

# Authenticate docker to ECR
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin  723181461334.dkr.ecr.us-west-2.amazonaws.com

# We use docker buildx to build the image for multiple platforms. buildx comes
# installed with Docker Engine when installed via Docker Desktop. If you're
# on a Linux machine with an old version of Docker Engine, you may need to
# install buildx manually. Follow these instructions to install docker-buildx-plugin:
# https://docs.docker.com/engine/install/ubuntu/

# Check if tempbuilder already exists
if ! docker buildx ls | grep -q tempbuilder; then
  # Prep for multiplatform build - the build is done INSIDE a docker container
  docker buildx create --name tempbuilder --use
else
  # If tempbuilder exists, set it as the current builder
  docker buildx use tempbuilder
fi

# Ensure that the tempbuilder container is running
docker buildx inspect tempbuilder --bootstrap

# Build image for amd64 and arm64
docker buildx build --platform linux/amd64,linux/arm64 --target production-image --tag edge-endpoint ../..

# Tag image
docker tag edge-endpoint:latest 723181461334.dkr.ecr.us-west-2.amazonaws.com/edge-endpoint:${TAG}

# Push image to ECR
docker push 723181461334.dkr.ecr.us-west-2.amazonaws.com/edge-endpoint:${TAG}

# Cleanup
docker buildx rm tempbuilder