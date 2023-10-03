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

# Install QEMU, a generic and open-source machine emulator and virtualizer
docker run --rm --privileged linuxkit/binfmt:af88a591f9cc896a52ce596b9cf7ca26a061ef97

# Check if tempbuilder already exists
if ! docker buildx ls | grep -q tempmodelupdaterbuilder; then
  # Prep for multiplatform build - the build is done INSIDE a docker container
  docker buildx create --name tempmodelupdaterbuilder --use
else
  # If tempbuilder exists, set it as the current builder
  docker buildx use tempmodelupdaterbuilder
fi

# Ensure that the tempbuilder container is running
docker buildx inspect tempmodelupdaterbuilder --bootstrap

# Temporarily copy the pyproject.toml file to the model_updater directory
# to bring it into the build context
cp ../../pyproject.toml ../../model_updater/

# Build model updater image for amd64 and arm64
docker buildx build \
  --platform linux/arm64,linux/amd64 \
  --tag 723181461334.dkr.ecr.us-west-2.amazonaws.com/edge-endpoint:${TAG} \
  ../../model_updater --push

# Remove the temporary pyproject.toml file
rm ../../model_updater/pyproject.toml